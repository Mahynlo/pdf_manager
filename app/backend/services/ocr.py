"""Servicio ``ocr``: reconocimiento de texto y orientación en el visor.

Las imágenes las dibuja el visor con su motor (el dueño del documento) y las sube como en
:meth:`ViewerService.upload_url`: aquí solo se reconocen. Las palabras reconocidas se guardan en
el documento abierto del servicio ``viewer`` (``ViewerService.set_ocr_words``) y pasan a su capa
de texto (asistente IA, panel de OCR, exportar texto); el visor las escribe en su documento como
texto invisible, para seleccionarlas y buscarlas.

Cada página es una llamada: el frontend recorre las páginas de un lote y puede cancelarlo entre
una y otra. La inferencia (lo lento) corre sin el candado del visor, así el visor sigue
respondiendo.
"""

from __future__ import annotations

import gc
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app import PROJECT_ROOT
from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from app.backend.services.viewer import ViewerService
from pdf_core.ocr import kind_of, mode_of
from pdf_core.page_ranges import select_pages
from pdf_core.pdf import Rect
from pdf_core.text_layer import words_text

log = logging.getLogger(__name__)

OCR_RELEASE_SECONDS = 12.0  # el modelo se libera tras este tiempo sin uso (como en Extraer)
PAGE_KINDS = {"native": "Digital", "scanned": "Escaneado", "hybrid": "Híbrido"}
MODE_LABELS = {"Hibrido": "Híbrido"}


def _rect(r: Rect) -> list[float]:
    return [round(v, 2) for v in r]


def _images(data: bytes, shapes: list[dict[str, Any]]) -> list[np.ndarray]:
    """Las imágenes RGB que subió el visor, una tras otra; ``shapes``: ``width`` y ``height`` de cada una."""
    images: list[np.ndarray] = []
    offset = 0
    for shape in shapes:
        width, height = int(shape["width"]), int(shape["height"])
        size = width * height * 3
        if width <= 0 or height <= 0 or offset + size > len(data):
            raise UserError("Las imágenes de la página no llegaron completas.", "bad_images")
        images.append(np.frombuffer(data, np.uint8, size, offset).reshape(height, width, 3))
        offset += size
    if offset != len(data):
        raise UserError("Las imágenes de la página no llegaron completas.", "bad_images")
    return images


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
    def page_text(self, doc_id: int, index: int, images: bool = False) -> dict[str, Any]:
        """Lo que muestra el panel al cambiar de página: texto, tipo y cajas (OCR si lo hay, si no el nativo).

        El visor tiene que haberle dado el texto de la página; ``images``: si la página tiene
        imágenes (lo dice su motor).
        """
        with self._viewer.document(doc_id) as entry:
            page = self._viewer.page_text(entry, index)
            ocr = entry.ocr.get(self._viewer.page_key(entry, index))
            if ocr:
                boxes = [[round(v, 2) for v in w[:4]] for w in ocr]
            else:
                boxes = [_rect(page.to_view(rect)) for rect, _text, _line in page.words()]
            return {
                "page": index,
                "text": self._viewer.text_of(entry, index).text,
                "segments": len(boxes),
                "boxes": boxes,
                "kind": PAGE_KINDS[kind_of(bool(page.text().strip()), images)],
                "ocr": bool(ocr),
            }

    @exposed
    def page(self, doc_id: int, index: int, upload: str, regions: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
        """OCR de la página ``index`` (botón «Procesar Página Actual» y cada página de un lote).

        El visor sube a ``upload`` las imágenes de ``regions`` (``rect`` de vista, ``scale`` en
        píxeles por punto, ``width`` y ``height``): las de la página o, si no tiene, la página
        entera. ``facts``, de su motor: ``lines`` (líneas de texto nativo) e ``images`` (si tiene
        imágenes). Devuelve también ``words``: las palabras, que el visor escribe en su documento.
        """
        found = self._read(upload, regions)
        with self._viewer.document(doc_id) as entry:
            key = self._viewer.page_key(entry, index)
        words, elapsed_ms = self._recognize(found)
        with self._viewer.document(doc_id) as entry:
            self._check_same_page(entry, index, key)
            self._viewer.set_ocr_words(entry, key, words)
            text = self._viewer.text_of(entry, index).text
        lines = int(facts.get("lines", 0))
        mode = mode_of(lines > 0, bool(words))
        return {
            "page": index,
            "text": text,
            "segments": lines + len(words),
            "boxes": [list(w[:4]) for w in words],
            "words": words,
            "elapsed_ms": elapsed_ms,
            "mode": MODE_LABELS.get(mode, mode),
            "kind": PAGE_KINDS[kind_of(lines > 0, bool(facts.get("images")))],
        }

    @exposed
    def area(self, doc_id: int, index: int, upload: str, region: dict[str, Any]) -> dict[str, Any]:
        """OCR de un recorte de la página ``index``: la imagen de ``region`` (como en :meth:`page`).
        Sus palabras se suman a las de la página; ``words`` son las nuevas."""
        found = self._read(upload, [region])
        with self._viewer.document(doc_id) as entry:
            key = self._viewer.page_key(entry, index)
            width = self._viewer.packed_text(entry, index).geometry.rect.width
        words, elapsed_ms = self._recognize(found)
        with self._viewer.document(doc_id) as entry:
            self._check_same_page(entry, index, key)
            self._viewer.set_ocr_words(entry, key, words, merge=True)
            boxes = [[round(v, 2) for v in w[:4]] for w in entry.ocr[key]]
        text = words_text(words, width)
        return {
            "page": index,
            "text": text,
            "segments": len(words),
            "boxes": boxes,
            "words": words,
            "elapsed_ms": elapsed_ms,
        }

    def _read(self, upload: str, regions: list[dict[str, Any]]) -> list[tuple[Rect, float, np.ndarray]]:
        """Las regiones con sus imágenes, subidas por el visor."""
        images = _images(self._viewer.received(upload), regions)
        return [(Rect(*region["rect"]), float(region["scale"]), image) for region, image in zip(regions, images, strict=True)]

    def _recognize(self, regions: list[tuple[Rect, float, np.ndarray]]) -> tuple[list[tuple], int]:
        """Inferencia sin el candado del visor; una a la vez. Devuelve las palabras
        ``(x0, y0, x1, y1, texto)`` y los milisegundos que tardó."""
        with self._busy:
            self._cancel_release()
            try:
                found, seconds = self.processor.recognize_regions(regions)
                return [(*_rect(d.bbox), d.text) for d in found], round(seconds * 1000)
            except Exception as ex:
                log.exception("Fallo del OCR")
                raise UserError(f"Error al procesar OCR: {ex}", "ocr_failed") from ex
            finally:
                self._schedule_release()

    def _check_same_page(self, entry: Any, index: int, key: str) -> None:
        if self._viewer.page_key(entry, index) != key:
            raise UserError("La página cambió mientras se reconocía su texto.", "stale")

    # ── Lotes ────────────────────────────────────────────────────────────
    @exposed
    def batch_pages(self, doc_id: int, scope: str, custom: str = "") -> list[int]:
        """Páginas de un lote: todas, pares, impares o un rango («1-5, 8»)."""
        if scope not in ("all", "even", "odd", "custom"):
            raise UserError("Selección de páginas no válida.", "bad_scope")
        with self._viewer.document(doc_id) as entry:
            pages = select_pages(len(entry.keys), scope, custom)
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
            self._host.write_file(dest, text.encode("utf-8"))
        except OSError as ex:
            raise UserError(f"No se pudo guardar {Path(dest).name}: {ex}", "save_failed") from ex
        return dest

    # ── Orientación ──────────────────────────────────────────────────────
    @exposed
    def orientation(self, upload: str, images: list[dict[str, Any]]) -> dict[str, Any]:
        """Orientación de una página escaneada por sus imágenes: ``{angle}``, los grados que hay
        que girarla (0: está bien).

        El visor sube a ``upload`` dos imágenes de la página (``width`` y ``height`` de cada una):
        a 0,8 píxeles por punto y la sonda (ver ``OCRProcessor.image_correction``). Si la página
        tiene texto, la orientación la dice su sentido y no hace falta llamar aquí. La gira el
        visor (es el dueño de las páginas), así se puede deshacer como cualquier giro.
        """
        small, probe = _images(self._viewer.received(upload), images)
        with self._busy:
            self._cancel_release()
            try:
                angle = self.processor.image_correction(small, probe)
            except Exception as ex:
                log.exception("No se pudo detectar la orientación")
                raise UserError(f"No se pudo clasificar la orientación: {ex}", "orientation_failed") from ex
            finally:
                self._schedule_release()
        return {"angle": angle}

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
