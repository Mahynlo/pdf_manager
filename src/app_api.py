from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import webview

from app_v1_modulos_py import recent_files
from app_v1_modulos_py.pdf_viewer.ocr import OCRProcessor


@dataclass
class LogEntry:
    level: str
    text: str


class AppAPI:
    def __init__(self) -> None:
        self._workspace_root = Path(__file__).resolve().parent
        self._ocr = OCRProcessor(str(self._workspace_root))

    def get_recent_files(self) -> list[dict[str, str]]:
        return [
            {"path": path, "name": Path(path).name}
            for path in recent_files.load()
        ]

    def open_pdf(self, path: str) -> dict[str, str]:
        recent_files.push(path)
        data_url = self._read_pdf_data_url(path)
        return {"path": path, "name": Path(path).name, "dataUrl": data_url}

    def pick_files(self, options: dict[str, Any]) -> list[str]:
        window = webview.windows[0]
        multiple = bool(options.get("multiple"))
        result = window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=options.get("directory", "") or "",
            allow_multiple=multiple,
            file_types=("PDF (*.pdf)",),
        )
        if not result:
            return []
        return list(result)

    def pick_directory(self, title: str) -> str | None:
        window = webview.windows[0]
        result = window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory="",
        )
        if not result:
            return None
        return result[0]

    def extract_pdf(self, payload: dict[str, Any]) -> dict[str, Any]:
        reference_path = payload.get("referencePath")
        target_paths = payload.get("targetPaths") or []
        destination_dir = payload.get("destinationDir")
        reference_pages = payload.get("referencePages") or ""
        hint_pages = payload.get("hintPages") or ""
        keywords_raw = payload.get("keywords") or ""

        log: list[LogEntry] = []
        if not target_paths:
            log.append(LogEntry("error", "Selecciona al menos un PDF objetivo."))
            return {
                "summary": "Falta seleccionar PDFs objetivo.",
                "outputPath": None,
                "log": [entry.__dict__ for entry in log],
            }

        keywords = self._collect_keywords(keywords_raw)
        if not keywords:
            log.append(LogEntry("error", "Define al menos una palabra clave para la busqueda."))
            return {
                "summary": "Faltan palabras clave.",
                "outputPath": None,
                "log": [entry.__dict__ for entry in log],
            }

        ref_tokens: set[str] = set()
        if reference_path:
            try:
                with fitz.open(reference_path) as ref_doc:
                    total_ref = len(ref_doc)
                    selected = self._parse_pages(reference_pages, total_ref)
                    pages_to_use = sorted(selected) if selected else range(total_ref)
                    for idx in pages_to_use:
                        text, _, _, _ = self._extract_page_text(ref_doc, idx)
                        ref_tokens |= self._normalize_words(text)
                    log.append(
                        LogEntry(
                            "info",
                            f"Referencia: {Path(reference_path).name} — {len(ref_tokens)} tokens",
                        )
                    )
            except Exception as exc:
                log.append(LogEntry("warn", f"Referencia no procesada: {exc}"))

        matches: list[dict[str, Any]] = []
        for path in target_paths:
            fname = Path(path).name
            try:
                doc = fitz.open(path)
            except Exception as exc:
                log.append(LogEntry("error", f"{fname}: error al abrir — {exc}"))
                continue

            with doc:
                total_pages = len(doc)
                hint_set = self._parse_pages(hint_pages, total_pages)
                scan_order = sorted(hint_set) + [i for i in range(total_pages) if i not in hint_set]

                for idx in scan_order:
                    text, mode, elapsed_ms, used_ocr = self._extract_page_text(doc, idx)
                    page_text = text.lower()
                    if not page_text.strip():
                        continue

                    kw_hits = [kw for kw in keywords if kw in page_text]
                    if len(kw_hits) == len(keywords):
                        score = float(len(kw_hits))
                        reason = f"keywords={len(kw_hits)}"
                        if ref_tokens:
                            page_tokens = self._normalize_words(text)
                            if page_tokens:
                                inter = len(ref_tokens & page_tokens)
                                union = len(ref_tokens | page_tokens)
                                jaccard = inter / union if union else 0.0
                                score += jaccard * 2
                                reason += f", sim={jaccard:.2f}"
                        matches.append(
                            {
                                "source_path": path,
                                "page_index": idx,
                                "score": score,
                                "reason": reason,
                            }
                        )
                        tag = "OCR" if used_ocr else "texto"
                        log.append(
                            LogEntry(
                                "success",
                                f"{fname} pag {idx + 1} [{mode} | {elapsed_ms:.0f}ms | {tag}]",
                            )
                        )

        if not matches:
            return {
                "summary": "Busqueda finalizada: no se encontraron coincidencias.",
                "outputPath": None,
                "log": [entry.__dict__ for entry in log],
            }

        output_dir = Path(destination_dir) if destination_dir else self._default_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = f"extraccion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        output_path = output_dir / output_name

        grouped: dict[str, list[dict[str, Any]]] = {}
        for match in matches:
            grouped.setdefault(match["source_path"], []).append(match)

        out_doc = fitz.open()
        try:
            for src_path, items in grouped.items():
                with fitz.open(src_path) as src_doc:
                    for pidx in sorted({m["page_index"] for m in items}):
                        out_doc.insert_pdf(src_doc, from_page=pidx, to_page=pidx)
            out_doc.save(str(output_path), garbage=4, deflate=True)
        finally:
            out_doc.close()

        return {
            "summary": f"Finalizado: {len(matches)} coincidencia(s).",
            "outputPath": str(output_path),
            "log": [entry.__dict__ for entry in log],
        }

    def merge_pdfs(self, payload: dict[str, Any]) -> dict[str, Any]:
        paths = payload.get("paths") or []
        output_path = payload.get("outputPath")
        if not paths:
            return {"outputPath": None, "message": "Selecciona al menos un PDF."}

        if output_path:
            out_path = Path(output_path)
        else:
            out_path = Path(paths[0]).parent / "combinado.pdf"

        out_doc = fitz.open()
        try:
            for path in paths:
                with fitz.open(path) as doc:
                    out_doc.insert_pdf(doc)
            out_doc.save(str(out_path), garbage=4, deflate=True)
        finally:
            out_doc.close()

        return {"outputPath": str(out_path), "message": "PDF combinado creado."}

    def _read_pdf_data_url(self, path: str) -> str:
        data = Path(path).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:application/pdf;base64,{b64}"

    def _default_output_dir(self) -> Path:
        return (self._workspace_root / "storage" / "temp").resolve()

    def _collect_keywords(self, raw: str) -> list[str]:
        chunks: list[str] = []
        for row in raw.splitlines():
            chunks.extend(part.strip() for part in row.split(","))
        return [c.lower() for c in chunks if c]

    def _parse_pages(self, page_input: str, total_pages: int) -> set[int]:
        out: set[int] = set()
        if not page_input.strip():
            return out
        for chunk in [c.strip() for c in page_input.replace(";", ",").split(",") if c.strip()]:
            if "-" in chunk:
                parts = chunk.split("-", 1)
                try:
                    a, b = int(parts[0].strip()), int(parts[1].strip())
                    if a > b:
                        a, b = b, a
                    out.update(idx - 1 for idx in range(a, b + 1) if 0 < idx <= total_pages)
                except ValueError:
                    pass
            else:
                try:
                    idx = int(chunk) - 1
                    if 0 <= idx < total_pages:
                        out.add(idx)
                except ValueError:
                    pass
        return out

    def _normalize_words(self, text: str) -> set[str]:
        words: set[str] = set()
        for raw in text.lower().replace("\n", " ").split():
            token = "".join(ch for ch in raw if ch.isalnum())
            if len(token) >= 4:
                words.add(token)
        return words

    def _extract_page_text(self, doc: fitz.Document, page_index: int) -> tuple[str, str, float, bool]:
        page = doc[page_index]
        needs_ocr = self._ocr.page_needs_ocr(page)
        result = self._ocr.process_page(doc, page_index, force_ocr=needs_ocr)
        text = "\n".join(seg.text for seg in result.segments if seg.text.strip())
        used_ocr = bool(result.detections)
        return text, result.mode_label, result.elapsed_ms, used_ocr
