"""Trabajo de extracción en segundo plano (equivale a ``ExtractorWorker`` de la versión Qt).

Ejecuta ``pdf_core.extractor.engine`` en un hilo y avisa al frontend con eventos
``extract:*`` (registro, progreso, coincidencias). Al terminar deja ``result`` o
``error``; el servicio los comunica cuando ya liberó el trabajo. Puede pedir
contraseñas a mitad del proceso y se puede cancelar.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdf_core.extractor import engine
from pdf_core.extractor.engine import ExtractPasswordRequiredError, ExtractPermissionDeniedError, MatchOptions, Reporter
from pdf_core.extractor.model import PageMatch, collect_keywords, parse_pages

Emit = Callable[[str, Any], None]
AskPassword = Callable[[str], "str | None"]  # ruta -> contraseña o None si se omite

# El motor colorea sus mensajes con colores fijos (o nombres de Flet); el frontend usa tonos del tema.
_TONES = {
    "#D32F2F": "danger",
    "#ED6C02": "warning",
    "#E65100": "warning",
    "#2E7D32": "success",
    "#1565C0": "info",
    "onSurfaceVariant": "muted",
}


@dataclass
class ExtractRequest:
    mode: str  # "smart" (palabras clave) | "range" (rango numérico)
    targets: list[str]
    destination: str
    passwords: dict[str, str] = field(default_factory=dict)  # ruta -> contraseña
    keywords: str = ""
    reference: str | None = None
    reference_password: str | None = None
    reference_pages: str = ""
    hint_pages: str = ""
    range_text: str = ""
    options: MatchOptions = field(default_factory=MatchOptions)
    split_by_doc: bool = False
    prefix: str = "extraccion"


class ExtractJob:
    def __init__(self, request: ExtractRequest, processor: Any, emit: Emit, ask_password: AskPassword) -> None:
        self.request = request
        self._processor = processor
        self._emit = emit
        self._ask_password = ask_password
        self._cancelled = threading.Event()
        self.result: dict[str, Any] = {"path": "", "count": 0, "files": 0}
        self.error: str | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    # ── avisos al frontend ───────────────────────────────────────────────────
    def _log(self, text: str, color: str = "#1565C0") -> None:
        self._emit("extract:log", {"text": text, "tone": _TONES.get(color)})

    def _progress(self, text: str) -> None:
        self._emit("extract:progress", text)

    def _summary(self, text: str) -> None:
        self._emit("extract:summary", text)

    def _separator(self) -> None:
        self._emit("extract:separator", None)

    def _finished(self, out_path: str = "", count: int = 0, files: int = 0) -> None:
        self._progress("")
        self.result = {"path": out_path, "count": count, "files": files}

    def _on_match(self, match: PageMatch, mode: str, _ms: float, used_ocr: bool, hits: list[str]) -> None:
        self._emit("extract:match", {
            "name": Path(match.source_path).name,
            "page": match.page_index + 1,
            "score": round(match.score, 2),
            "terms": ", ".join(hits),
            "mode": f"{mode} (OCR)" if used_ocr else mode,
        })

    # ── ejecución ────────────────────────────────────────────────────────────
    def run(self) -> None:
        try:
            if self.request.mode == "range":
                self._run_range()
            else:
                self._run_smart()
        except Exception as ex:  # el frontend debe enterarse siempre del final
            self._progress("")
            self.error = f"Error inesperado: {ex}"

    def _run_smart(self) -> None:
        req = self.request
        keywords = collect_keywords(req.keywords, lower=not req.options.case_sensitive)
        reporter = Reporter(log=self._log, set_progress=self._progress, log_separator=self._separator)
        ref_tokens = self._reference_tokens(reporter)

        matches: list[PageMatch] = []
        total = len(req.targets)
        for idx, path in enumerate(req.targets):
            if self.cancelled:
                self._log("⏹️ Proceso cancelado por el usuario.", "#E65100")
                break
            name = Path(path).name
            self._summary(f"Archivo {idx + 1} de {total}: {name}")
            doc = self._open_target(path)
            if doc is None:
                continue
            with doc:
                matches += engine.process_document(
                    doc, path=path, fname=name, file_idx=idx, total_files=total, keywords=keywords,
                    ref_tokens=ref_tokens, hint_pages_raw=req.hint_pages, processor=self._processor,
                    reporter=reporter, options=req.options, should_cancel=lambda: self.cancelled,
                    on_match=self._on_match,
                )

        if self.cancelled:
            return self._finished()
        if not matches:
            self._summary("Búsqueda finalizada: no se encontraron páginas coincidentes.")
            return self._finished()
        by_index = {i: req.passwords[p] for i, p in enumerate(req.targets) if p in req.passwords}
        try:
            out_path = engine.save_matches(
                matches, req.targets, by_index, req.destination, prefix=req.prefix, split_by_doc=req.split_by_doc
            )
        except Exception as ex:
            self._progress("")
            self.error = f"Error al guardar resultado: {ex}"
            return None
        self._log(f"💾 Archivo guardado: {out_path}")
        self._finished(str(out_path), len(matches), len({m.source_path for m in matches}))
        return None

    def _reference_tokens(self, reporter: Reporter) -> set[str]:
        """Tokens del documento de referencia (vacío si no hay o no se puede leer)."""
        req = self.request
        if not req.reference:
            return set()
        self._progress("Procesando documento de referencia…")
        password = req.reference_password
        for attempt in range(2):
            try:
                tokens = engine.extract_reference_tokens(
                    req.reference, password, req.reference_pages, self._processor, reporter=reporter
                )
                self._separator()
                return tokens
            except ExtractPasswordRequiredError:
                if attempt:
                    break
                self._log("✗ Referencia requiere contraseña para procesarse.", "#D32F2F")
                password = self._ask_password(req.reference)
                if password is None:
                    break
                req.reference_password = password
            except ExtractPermissionDeniedError:
                self._log("✗ Referencia no permite extracción de contenido.", "#D32F2F")
                break
            except Exception as ex:
                self._log(f"✗ Referencia no procesada: {ex}", "#D32F2F")
                break
        return set()

    def _open_target(self, path: str) -> fitz.Document | None:
        """Abre un PDF objetivo pidiendo contraseña si hace falta; None si se omite."""
        name = Path(path).name
        try:
            return engine.open_source_doc(path, password=self.request.passwords.get(path))
        except ExtractPasswordRequiredError:
            self._log(f"✗ {name}: requiere contraseña. Solicitando…", "#D32F2F")
            password = self._ask_password(path)
            if password is None:
                self._log(f"✗ {name}: omitido (sin contraseña)", "#D32F2F")
                return None
            self.request.passwords[path] = password
            try:
                return engine.open_source_doc(path, password=password)
            except Exception as ex:
                self._log(f"✗ {name}: error tras contraseña — {ex}", "#D32F2F")
        except ExtractPermissionDeniedError:
            self._log(f"✗ {name}: no permite extracción de contenido.", "#D32F2F")
        except Exception as ex:
            self._log(f"✗ {name}: error al abrir — {ex}", "#D32F2F")
        return None

    def _run_range(self) -> None:
        req = self.request
        dest = Path(req.destination)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        total_pages = 0
        last_out = ""
        for path in req.targets:
            if self.cancelled:
                break
            stem = Path(path).stem
            self._progress(f"Extrayendo rango: {stem}")
            doc = self._open_target(path)
            if doc is None:
                continue
            with doc:
                pages = parse_pages(req.range_text, len(doc))
                if not pages:
                    self._log(f"~ {stem}: ninguna página en el rango especificado ({len(doc)} pág. total)", "#ED6C02")
                    continue
                out_path = dest / f"{req.prefix}_{stem}_{stamp}.pdf"
                engine.write_pages(doc, pages, out_path)
            total_pages += len(pages)
            last_out = str(out_path)
            self._log(f"✓ {stem}: {len(pages)} páginas extraídas → {out_path.name}", "#2E7D32")
        if total_pages:
            self._finished(last_out, total_pages, len(req.targets))
        else:
            self._summary("Extracción finalizada sin páginas extraídas.")
            self._finished()
