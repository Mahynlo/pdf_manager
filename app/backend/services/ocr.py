"""Servicio ``ocr``: reconocimiento de texto y orientación en el visor (equivale a
``ocr_panel.py`` y ``ocr_worker.py`` en Qt).

Trabaja sobre los documentos abiertos del servicio ``viewer``. Las palabras
reconocidas se guardan en el documento abierto (``ViewerService.set_ocr_words``) y
pasan a formar parte de su capa de texto: se pueden seleccionar, buscar y exportar.

Cada página es una llamada: el frontend recorre las páginas de un lote y puede
cancelarlo entre una y otra. La página se rasteriza con el candado del visor y la
inferencia (lo lento) corre sin él, así el visor sigue respondiendo.
"""

from __future__ import annotations

import gc
import logging
import threading
from pathlib import Path
from typing import Any

import fitz

from app import PROJECT_ROOT
from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from app.backend.services.viewer import ViewerService
from pdf_core.page_ranges import select_pages
from pdf_core.text_layer import words_text

log = logging.getLogger(__name__)

OCR_RELEASE_SECONDS = 12.0  # el modelo se libera tras este tiempo sin uso (como en Extraer)
PAGE_KINDS = {"native": "Digital", "scanned": "Escaneado", "hybrid": "Híbrido"}
MODE_LABELS = {"Hibrido": "Híbrido"}


def _rect(r: fitz.Rect) -> list[float]:
    return [round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1)]


class OcrService:
    def __init__(self, host: Host, viewer: ViewerService, processor: Any = None) -> None:
        self._host = host
        self._viewer = viewer
        self._processor = processor  # OCRProcessor; se crea al primer uso (carga onnx)
        self._busy = threading.Lock()  # una inferencia a la vez (el modelo no es reentrante)
        self._release_timer: threading.Timer | None = None

    @property
    def processor(self) -> Any:
        if self._processor is None:
            from pdf_core.ocr import OCRProcessor

            self._processor = OCRProcessor(str(PROJECT_ROOT))
        return self._processor

    # ── Página actual ────────────────────────────────────────────────────
    @exposed
    def page_text(self, doc_id: int, index: int) -> dict[str, Any]:
        """Lo que muestra el panel al cambiar de página: texto, tipo y cajas (OCR si lo hay, si no el nativo)."""
        with self._viewer.document(doc_id) as entry:
            page = self._viewer.page(entry, index)
            ocr = entry.ocr.get(self._viewer.page_key(entry, page))
            if ocr:
                boxes = [[round(v, 2) for v in w[:4]] for w in ocr]
            else:
                rot = page.rotation_matrix
                boxes = [_rect(fitz.Rect(w[:4]) * rot) for w in page.get_text("words")]
            return {
                "page": index,
                "text": self._viewer.text_of(entry, page).text,
                "segments": len(boxes),
                "boxes": boxes,
                "kind": PAGE_KINDS.get(self.processor.page_kind(page), "-"),
                "ocr": bool(ocr),
            }

    @exposed
    def page(self, doc_id: int, index: int) -> dict[str, Any]:
        """OCR de la página ``index`` (botón «Procesar Página Actual» y cada página de un lote)."""
        with self._viewer.document(doc_id) as entry:
            key = self._viewer.page_key(entry, self._viewer.page(entry, index))
            prepared = self.processor.prepare_page(entry.doc, index, force_ocr=True)
        result = self._recognize(prepared)
        words = [(*_rect(s.bbox), s.text) for s in result.segments if s.source == "ocr"]
        with self._viewer.document(doc_id) as entry:
            page = self._current_page(entry, index, key)
            layer = self._viewer.set_ocr_words(entry, page, words)
        return {
            "page": index,
            "text": layer.text,
            "segments": len(result.segments),
            "boxes": [list(w[:4]) for w in words],
            "elapsed_ms": round(result.elapsed_ms),
            "mode": MODE_LABELS.get(result.mode_label, result.mode_label),
            "kind": PAGE_KINDS.get(result.page_kind, "-"),
        }

    @exposed
    def area(self, doc_id: int, index: int, rect: list[float]) -> dict[str, Any]:
        """OCR del rectángulo ``rect`` (puntos de la página vista); sus palabras se suman a las de la página."""
        with self._viewer.document(doc_id) as entry:
            key = self._viewer.page_key(entry, self._viewer.page(entry, index))
            prepared = self.processor.prepare_area(entry.doc, index, fitz.Rect(rect))
        result = self._recognize(prepared)
        words = [(*_rect(s.bbox), s.text) for s in result.segments]
        with self._viewer.document(doc_id) as entry:
            page = self._current_page(entry, index, key)
            self._viewer.set_ocr_words(entry, page, words, merge=True)
            boxes = [[round(v, 2) for v in w[:4]] for w in entry.ocr[key]]
            text = words_text(words, page.rect.width)
        return {
            "page": index,
            "text": text,
            "segments": len(words),
            "boxes": boxes,
            "elapsed_ms": round(result.elapsed_ms),
        }

    def _recognize(self, prepared: Any) -> Any:
        """Inferencia sin el candado del visor; una a la vez."""
        with self._busy:
            self._cancel_release()
            try:
                return self.processor.recognize_page(prepared)
            except Exception as ex:
                log.exception("Fallo del OCR")
                raise UserError(f"Error al procesar OCR: {ex}", "ocr_failed") from ex
            finally:
                self._schedule_release()

    def _current_page(self, entry: Any, index: int, key: str) -> fitz.Page:
        page = self._viewer.page(entry, index)
        if self._viewer.page_key(entry, page) != key:
            raise UserError("La página cambió mientras se reconocía su texto.", "stale")
        return page

    # ── Lotes ────────────────────────────────────────────────────────────
    @exposed
    def batch_pages(self, doc_id: int, scope: str, custom: str = "") -> list[int]:
        """Páginas de un lote: todas, pares, impares o un rango («1-5, 8»)."""
        if scope not in ("all", "even", "odd", "custom"):
            raise UserError("Selección de páginas no válida.", "bad_scope")
        with self._viewer.document(doc_id) as entry:
            pages = select_pages(len(entry.doc), scope, custom)
        if not pages:
            raise UserError("No se seleccionaron páginas válidas.", "no_pages")
        return pages

    @exposed
    def save_text(self, doc_id: int, text: str) -> str | None:
        """«Guardar como TXT…» del resultado; devuelve la ruta (``None`` si se cancela)."""
        with self._viewer.document(doc_id) as entry:
            source = Path(entry.path)
        dest = self._host.save_text(str(source.with_name(f"{source.stem}_ocr.txt")))
        if not dest:
            return None
        try:
            Path(dest).write_text(text, encoding="utf-8")
        except OSError as ex:
            raise UserError(f"No se pudo guardar {Path(dest).name}: {ex}", "save_failed") from ex
        return dest

    # ── Orientación ──────────────────────────────────────────────────────
    @exposed
    def orientation(self, doc_id: int, index: int) -> dict[str, Any]:
        """Detecta la orientación de la página y la corrige. ``{angle, info}``: ``info`` solo si se giró."""
        with self._busy, self._viewer.document(doc_id) as entry:
            self._cancel_release()
            try:
                angle = self.processor.correction_angle(self._viewer.page(entry, index))
            except UserError:
                raise
            except Exception as ex:
                log.exception("No se pudo detectar la orientación")
                raise UserError(f"No se pudo clasificar la orientación: {ex}", "orientation_failed") from ex
            finally:
                self._schedule_release()
        if not angle:
            return {"angle": 0, "info": None}
        return {"angle": angle, "info": self._viewer.rotate(doc_id, angle, index)}

    # ── Memoria del modelo ───────────────────────────────────────────────
    def _schedule_release(self) -> None:
        self._cancel_release()
        self._release_timer = threading.Timer(OCR_RELEASE_SECONDS, self._release)
        self._release_timer.daemon = True
        self._release_timer.start()

    def _cancel_release(self) -> None:
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None

    def _release(self) -> None:
        with self._busy:
            if self._processor is not None:
                self._processor.release_predictor()
                self._processor.release_orientation_predictor()
                gc.collect()

    def close(self) -> None:
        self._cancel_release()
        self._release()
