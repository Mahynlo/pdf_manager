"""Servicio ``extract`` (Extraer): documentos, opciones y el trabajo en segundo plano.

Equivale a ``src_qt/ui/tools/extractor/tab.py`` sin la interfaz. Mientras corre
un trabajo, sus avisos llegan al frontend como eventos ``extract:*``.
"""

from __future__ import annotations

import gc
import threading
from pathlib import Path
from typing import Any

from app import PROJECT_ROOT
from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from app.backend.services.documents import DocumentService
from app.backend.services.extract.job import ExtractJob, ExtractRequest
from pdf_core.extractor import engine
from pdf_core.extractor.engine import (
    ExtractInvalidPasswordError,
    ExtractPasswordRequiredError,
    ExtractPermissionDeniedError,
    MatchOptions,
)
from pdf_core.extractor.model import doc_kind_label

OCR_RELEASE_SECONDS = 12.0  # el modelo de OCR se libera tras este tiempo sin uso
DEFAULT_DESTINATION = PROJECT_ROOT / "storage" / "temp"

# Preajustes del menú «Preajustes»: (texto, palabras clave que se añaden).
PRESETS: tuple[tuple[str, str], ...] = (
    ("Facturas / Recibos / Tributos", "factura, total, base imponible, importe, iva, fecha"),
    ("Identificación / DNI / NIF / Pasaporte", "dni, nie, nif, pasaporte, titular, nombre, apellidos"),
    ("Contratos / Cláusulas Legales", "contrato, partes, cláusula, firma, vigencia, estipulaciones"),
    ("Balances y Estados Financieros", "balance, activo, pasivo, patrimonio neto, pérdidas y ganancias"),
    ("Certificados / Diplomas / Actas", "certifica, diploma, acta, resolución, acreditación"),
)


def _check_password(path: str, password: str) -> None:
    """Valida la contraseña de un PDF para extraer; lanza ``UserError`` si no sirve."""
    try:
        engine.open_source_doc(path, password=password).close()
    except ExtractPasswordRequiredError:
        raise UserError("Ingresa la contraseña", "empty_password") from None
    except ExtractInvalidPasswordError:
        raise UserError("Contraseña incorrecta", "invalid_password") from None
    except ExtractPermissionDeniedError:
        raise UserError("PDF sin permisos de extracción", "permission_denied") from None


class ExtractService:
    def __init__(self, host: Host, documents: DocumentService, processor: Any = None) -> None:
        self._host = host
        self._documents = documents
        self._processor = processor  # OCRProcessor; se crea al primer uso (carga onnx)
        self._lock = threading.RLock()
        self._reference: dict[str, Any] | None = None  # {path, name, kind, password}
        self._targets: list[str] = []
        self._passwords: dict[str, str] = {}
        self._destination = self._default_destination()
        self._last_output: str | None = None
        self._job: ExtractJob | None = None
        self._idle = threading.Event()  # puesto mientras no hay trabajo en curso
        self._idle.set()
        self._release_timer: threading.Timer | None = None
        # Contraseña pedida por el trabajo: la ruta que espera y la respuesta.
        self._pending_path: str | None = None
        self._answer: str | None = None
        self._answered = threading.Event()

    @staticmethod
    def _default_destination() -> str:
        try:
            DEFAULT_DESTINATION.mkdir(parents=True, exist_ok=True)
            return str(DEFAULT_DESTINATION.resolve())
        except OSError:
            return str(Path.home() / "Documents")

    @property
    def processor(self) -> Any:
        if self._processor is None:
            from pdf_core.ocr import OCRProcessor

            self._processor = OCRProcessor(str(PROJECT_ROOT))
        return self._processor

    # ── Estado ───────────────────────────────────────────────────────────────
    @exposed
    def state(self) -> dict[str, Any]:
        with self._lock:
            ref = self._reference
            return {
                "reference": {"name": ref["name"], "path": ref["path"], "kind": ref["kind"]} if ref else None,
                "targets": [{"path": p, "name": Path(p).name} for p in self._targets],
                "destination": {"path": self._destination, "name": Path(self._destination).name},
                "running": self._job is not None,
                "last_output": self._last_output,
            }

    @exposed
    def presets(self) -> list[dict[str, str]]:
        return [{"label": label, "keywords": kw} for label, kw in PRESETS]

    # ── Referencia ───────────────────────────────────────────────────────────
    @exposed
    def pick_reference(self) -> dict[str, Any]:
        """Elige la referencia; ``locked`` indica que hay que pedir su contraseña."""
        path = self._host.pick_pdf()
        if not path:
            return {"state": self.state(), "locked": False}
        with self._lock:
            self._reference = {"path": path, "name": Path(path).name, "kind": "-", "password": None}
            try:
                with engine.open_source_doc(path) as doc:
                    self._reference["kind"] = f"{doc_kind_label(self.processor.get_doc_kind(doc))} ({len(doc)} páginas)"
            except ExtractPasswordRequiredError:
                return {"state": self.state(), "locked": True}
            except Exception as ex:
                self._reference["kind"] = f"error ({ex})"
            return {"state": self.state(), "locked": False}

    @exposed
    def unlock_reference(self, password: str) -> dict[str, Any]:
        with self._lock:
            if not self._reference:
                raise UserError("No hay documento de referencia.", "not_found")
            _check_password(self._reference["path"], password)
            self._reference.update(password=password, kind="Autenticado")
            return self.state()

    @exposed
    def clear_reference(self) -> dict[str, Any]:
        with self._lock:
            self._reference = None
            return self.state()

    # ── Documentos objetivo y destino ────────────────────────────────────────
    def _add_targets(self, paths: list[str]) -> dict[str, Any]:
        with self._lock:
            for p in paths:
                if p not in self._targets:
                    self._targets.append(p)
            return self.state()

    @exposed
    def pick_targets(self) -> dict[str, Any]:
        return self._add_targets(self._host.pick_pdfs())

    @exposed
    def pick_target_folder(self) -> dict[str, Any]:
        folder = self._host.pick_folder()
        return self._add_targets([str(p.resolve()) for p in Path(folder).glob("**/*.pdf")] if folder else [])

    @exposed
    def clear_targets(self) -> dict[str, Any]:
        with self._lock:
            self._targets.clear()
            self._passwords.clear()
            return self.state()

    @exposed
    def choose_destination(self) -> dict[str, Any]:
        folder = self._host.pick_folder()
        with self._lock:
            if folder:
                self._destination = folder
            return self.state()

    @exposed
    def open_destination(self) -> None:
        self._host.open_folder(self._destination)

    @exposed
    def open_result(self) -> None:
        if self._last_output and Path(self._last_output).is_file():
            self._documents.open(self._last_output)

    # ── Ejecución ────────────────────────────────────────────────────────────
    @exposed
    def start(self, params: dict[str, Any]) -> dict[str, Any]:
        """Inicia la búsqueda (``mode="smart"``) o la extracción por rango (``mode="range"``)."""
        mode = "range" if params.get("mode") == "range" else "smart"
        with self._lock:
            if self._job is not None:
                raise UserError("Ya hay una extracción en curso.", "busy")
            if not self._targets:
                raise UserError("Selecciona al menos un PDF objetivo.", "no_targets")
            if mode == "smart" and not str(params.get("keywords", "")).strip():
                raise UserError("Define al menos una palabra clave para la búsqueda.", "no_keywords")
            ref = self._reference or {}
            request = ExtractRequest(
                mode=mode,
                targets=list(self._targets),
                destination=self._destination,
                passwords=dict(self._passwords),
                keywords=str(params.get("keywords", "")).strip(),
                reference=ref.get("path"),
                reference_password=ref.get("password"),
                reference_pages=str(params.get("reference_pages", "")).strip(),
                hint_pages=str(params.get("hint_pages", "")).strip(),
                range_text=str(params.get("range", "")).strip(),
                options=MatchOptions(
                    match_all=bool(params.get("match_all", True)),
                    case_sensitive=bool(params.get("case_sensitive", False)),
                    ignore_accents=bool(params.get("ignore_accents", True)),
                    whole_word=bool(params.get("whole_word", False)),
                ),
                split_by_doc=bool(params.get("split_by_doc", False)),
            )
            self._cancel_release()
            self._job = ExtractJob(request, self.processor, self._host.emit, self._ask_password)
            self._idle.clear()
            threading.Thread(target=self._run, args=(self._job,), name="extract", daemon=True).start()
            return self.state()

    def _run(self, job: ExtractJob) -> None:
        job.run()
        with self._lock:
            self._passwords.update(job.request.passwords)  # las contraseñas dadas sirven para la próxima vez
            if job.request.reference_password and self._reference:
                self._reference["password"] = job.request.reference_password
            if job.result["path"]:
                self._last_output = job.result["path"]
            self._job = None
        self._schedule_release()
        # Se avisa ya liberado el trabajo: el frontend puede iniciar otro en cuanto lo recibe.
        if job.error:
            self._host.emit("extract:error", job.error)
        else:
            self._host.emit("extract:finished", job.result)
        self._idle.set()

    @property
    def running(self) -> bool:
        """Hay una extracción en curso (aviso al salir de la aplicación)."""
        with self._lock:
            return self._job is not None

    def wait(self, timeout: float | None = None) -> bool:
        """Espera a que termine el trabajo en curso (pruebas y cierre de la app)."""
        return self._idle.wait(timeout)

    @exposed
    def reset(self) -> None:
        """Al cerrar la pestaña: cancela lo que esté en curso y vacía referencia y objetivos."""
        self.cancel()
        with self._lock:
            self._reference = None
            self._targets.clear()
            self._passwords.clear()
            self._last_output = None

    @exposed
    def cancel(self) -> None:
        with self._lock:
            if self._job is not None:
                self._job.cancel()
        self._deliver(None)  # por si el trabajo espera una contraseña

    # ── Contraseñas pedidas durante el trabajo ───────────────────────────────
    def _ask_password(self, path: str) -> str | None:
        """Lo llama el hilo del trabajo: pide la contraseña al frontend y espera la respuesta."""
        self._answered.clear()
        self._pending_path = path
        self._host.emit("extract:password", {"path": path, "name": Path(path).name})
        self._answered.wait()
        self._pending_path = None
        return self._answer

    def _deliver(self, password: str | None) -> None:
        self._answer = password
        self._answered.set()

    @exposed
    def answer_password(self, password: str | None) -> None:
        """Respuesta del diálogo: ``None`` omite el archivo; una contraseña incorrecta se rechaza."""
        path = self._pending_path
        if path is None:
            return
        if password is not None:
            _check_password(path, password)
        self._deliver(password)

    # ── Memoria del OCR ──────────────────────────────────────────────────────
    def _schedule_release(self) -> None:
        self._cancel_release()
        self._release_timer = threading.Timer(OCR_RELEASE_SECONDS, self._release_ocr)
        self._release_timer.daemon = True
        self._release_timer.start()

    def _cancel_release(self) -> None:
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None

    def _release_ocr(self) -> None:
        with self._lock:
            if self._job is None and self._processor is not None:
                self._processor.release_predictor()
                gc.collect()

    def close(self) -> None:
        self.cancel()
        self.wait(5)
        self._cancel_release()
        self._release_ocr()
