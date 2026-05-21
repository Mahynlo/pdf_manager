"""Hybrid OCR utilities: native PDF text + OCR only on image regions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import fitz
import numpy as np
from onnxtr.models import ocr_predictor


_SCALE_FOR_OCR = 2.0
_MAX_OCR_PX = 2000  # cap longest edge to avoid huge pixmaps on large pages


@dataclass
class OCRSegment:
    """
    Represents a segment of text extracted from a page.
    """
    text: str
    source: str  # native | ocr
    bbox: fitz.Rect


@dataclass
class OCRDetection: 
    """
    Represents a single OCR detection with confidence score.
    """
    text: str
    score: float
    source: str  # ocr
    bbox: fitz.Rect


@dataclass
class OCRPageResult:
    """
    Represents the result of processing a single page, including its classification,
    the segments of text found, and the time taken.
    """
    page_kind: str  # scanned | native | hybrid
    doc_kind: str   # scanned | native | hybrid
    mode_label: str  # OCR | Nativo | Hibrido
    elapsed_ms: float
    segments: list[OCRSegment]
    detections: list[OCRDetection]


class OCRProcessor:

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        self.model_root = self.workspace_root / "modelos"
        self._predictor: Any | None = None
        # Keyed by doc.name (file path) so different documents don't share state.
        self._doc_kind_cache: dict[str, str] = {}

    @property
    def predictor(self):
        if self._predictor is None:
            os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
            # Use bundled models (src/onnxtr_cache/) so the compiled app works offline.
            # Falls back to the default ~/.cache/onnxtr/ if the bundled folder is missing.
            bundled = Path(__file__).resolve().parents[2] / "assets" / "onnxtr_cache"
            if bundled.exists():
                os.environ["ONNXTR_CACHE_DIR"] = str(bundled)
            self._predictor = ocr_predictor(
                det_arch="db_mobilenet_v3_large",
                reco_arch="crnn_mobilenet_v3_small",
                detect_language=False,
                load_in_8_bit=False,
            )
        return self._predictor

    @staticmethod
    def _geometry_to_pixel_rect(geometry: Any, width: int, height: int) -> fitz.Rect | None:
        if geometry is None:
            return None
        coords = np.asarray(geometry, dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 2:
            return None

        xs = coords[:, 0]
        ys = coords[:, 1]

        # OnnxTR usually exports normalized coordinates in [0, 1].
        if max(float(np.max(xs)), float(np.max(ys))) <= 1.5:
            xs = xs * width
            ys = ys * height

        x0 = float(np.min(xs))
        y0 = float(np.min(ys))
        x1 = float(np.max(xs))
        y1 = float(np.max(ys))
        return fitz.Rect(x0, y0, x1, y1)

    def _run_predictor(self, img: np.ndarray) -> tuple[list[tuple[fitz.Rect, str, float]], float]:
        """ Regresa una lista de tuplas (rectángulo, texto, puntuación) para cada palabra detectada en la imagen, junto con el tiempo que tomó ejecutar el predictor.
        """
        start = perf_counter()
        document = self.predictor([img])
        elapsed = perf_counter() - start

        page = document.pages[0]
        h, w = img.shape[:2]
        words: list[tuple[fitz.Rect, str, float]] = []

        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    text = str(getattr(word, "value", "")).strip()
                    if not text:
                        continue
                    rect = self._geometry_to_pixel_rect(getattr(word, "geometry", None), w, h)
                    if rect is None:
                        continue
                    conf = getattr(word, "confidence", 1.0)
                    score = float(conf) if conf is not None else 1.0
                    words.append((rect, text, score))

        # page holds a reference into document — release both before returning
        # so onnxtr's internal tensors and feature maps can be freed by the GC.
        del page, document
        return words, elapsed

    def get_doc_kind(self, doc: fitz.Document) -> str:
        """Clasificar el documento como 'nativo', 'escaneado' o 'híbrido' según el contenido de sus páginas.
         - 'nativo' si tiene al menos una página con texto extraíble y ninguna con imágenes.
         - 'escaneado' si tiene al menos una página con imágenes y ninguna con texto extraíble.
         - 'híbrido' si tiene al menos una página con texto extraíble y al menos una página con imágenes.
         - Si no tiene páginas con texto ni imágenes, se clasifica como 'escaneado' por defecto.
         - Solo se analizan las primeras 20 páginas para determinar el tipo de documento, para mejorar el rendimiento en documentos largos.
         -
        """
        key = doc.name or id(doc)
        if key in self._doc_kind_cache:
            return self._doc_kind_cache[key]

        text_pages = 0
        image_pages = 0
        max_pages = min(len(doc), 20)

        for i in range(max_pages):
            if text_pages > 0 and image_pages > 0:
                break  # already "hybrid" — no need to scan more pages
            page = doc[i]
            has_text = bool(page.get_text("text").strip())
            has_images = bool(page.get_images(full=True))
            if has_text:
                text_pages += 1
            if has_images:
                image_pages += 1

        if text_pages > 0 and image_pages == 0:
            kind = "native"
        elif text_pages == 0 and image_pages > 0:
            kind = "scanned"
        elif text_pages == 0 and image_pages == 0:
            kind = "scanned"
        else:
            kind = "hybrid"

        self._doc_kind_cache[key] = kind
        return kind

    def page_kind(self, page: fitz.Page) -> str:
        """"
        Clasificar la página como 'nativa', 'escaneada' o 'híbrida' según su contenido.
         - 'nativa' si tiene texto extraíble pero no imágenes.
         - 'escaneada' si tiene imágenes pero no texto extraíble.
         - 'híbrida' si tiene tanto texto extraíble como imágenes.
         - Si no tiene texto ni imágenes, se clasifica como 'escaneada' por defecto.
        """
        has_text = bool(page.get_text("text").strip())
        has_images = bool(page.get_images(full=True))
        if has_text and not has_images:
            return "native"
        if has_images and not has_text:
            return "scanned"
        if has_images and has_text:
            return "hybrid"
        return "scanned" if not has_text else "native"

    def page_needs_ocr(self, page: fitz.Page) -> bool:
        """Return True only when the page lacks extractable native text."""
        return not bool(page.get_text("text").strip())

    def _native_segments(self, page: fitz.Page) -> list[OCRSegment]:
        segments: list[OCRSegment] = []
        for block in page.get_text("blocks"):
            if len(block) < 7:
                continue
            x0, y0, x1, y1, text, _, block_type = block[:7]
            if block_type != 0:
                continue
            clean = str(text).strip()
            if not clean:
                continue
            segments.append(
                OCRSegment(
                    text=clean,
                    source="native",
                    bbox=fitz.Rect(float(x0), float(y0), float(x1), float(y1)),
                )
            )
        return segments

    def _image_regions(self, page: fitz.Page) -> list[fitz.Rect]:
        regions: list[fitz.Rect] = []
        # get_image_info() only returns image metadata (bbox, size, …) without
        # loading all text content like get_text("dict") would.
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if not bbox:
                continue
            rect = fitz.Rect(bbox)
            if rect.width < 8 or rect.height < 8:
                continue
            regions.append(rect)

        # Some scanned PDFs have no image blocks; OCR the whole page as fallback.
        if not regions:
            regions.append(page.rect)
        return regions

    @staticmethod
    def _pixmap_to_ndarray(pix: fitz.Pixmap) -> np.ndarray:
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        return (arr[:, :, :3] if pix.n >= 3 else arr).copy()

    @staticmethod
    def _ocr_scale(rect: fitz.Rect) -> float:
        longest = max(rect.width, rect.height)
        scale = _SCALE_FOR_OCR
        if longest * scale > _MAX_OCR_PX:
            scale = _MAX_OCR_PX / longest
        return max(scale, 1.0)

    def _ocr_on_regions(self, page: fitz.Page) -> tuple[list[OCRSegment], list[OCRDetection], float]:
        segments: list[OCRSegment] = []
        detections: list[OCRDetection] = []
        total_elapsed = 0.0

        for rect in self._image_regions(page):
            scale = self._ocr_scale(rect)
            pix = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                clip=rect,
                alpha=False,
            )
            img = self._pixmap_to_ndarray(pix)
            del pix  # free pixmap memory before inference

            words, elapsed = self._run_predictor(img)
            del img  # free image array after inference
            total_elapsed += elapsed

            for px_rect, text, score in words:
                x0 = rect.x0 + px_rect.x0 / scale
                y0 = rect.y0 + px_rect.y0 / scale
                x1 = rect.x0 + px_rect.x1 / scale
                y1 = rect.y0 + px_rect.y1 / scale
                pdf_rect = fitz.Rect(x0, y0, x1, y1)

                segments.append(OCRSegment(text=text, source="ocr", bbox=pdf_rect))
                detections.append(OCRDetection(text=text, score=score, source="ocr", bbox=pdf_rect))

        return segments, detections, total_elapsed

    def process_page(self, doc: fitz.Document, page_num: int, force_ocr: bool = False) -> OCRPageResult:
        page = doc[page_num] # numeo de página es 0-indexed en PyMuPDF
        doc_kind = self.get_doc_kind(doc) #Clasificación del documento: Nativo, Escaneado o Híbrido
        page_kind = self.page_kind(page) #Clasificación de la página: Nativa, Escaneada o Híbrida

        start = perf_counter() #Tiempo de inicio para medir el tiempo total de procesamiento de la página
        native_segments = self._native_segments(page) #Extracción de segmentos de texto nativos de la página
        ocr_segments: list[OCRSegment] = [] #Inicialización de la lista de segmentos OCR, se llenará solo si se necesita OCR
        detections: list[OCRDetection] = [] #Inicialización de la lista de detecciones OCR, se llenará solo si se necesita OCR
        ocr_elapsed = 0.0 #Inicialización del tiempo de OCR, se actualizará solo si se realiza OCR

        if force_ocr or page_kind in ("hybrid", "scanned"): 
            ocr_segments, detections, ocr_elapsed = self._ocr_on_regions(page)

        segments = [*native_segments, *ocr_segments]
        segments.sort(key=lambda s: (s.bbox.y0, s.bbox.x0))

        #Tipo de página: Nativo, Escaneado o Híbrido
        if native_segments and ocr_segments:
            mode = "Hibrido"
        elif native_segments:
            mode = "Nativo"
        elif ocr_segments:
            mode = "OCR"
        else:
            mode = "Sin texto"

        wall_elapsed = perf_counter() - start
        elapsed_ms = max(wall_elapsed, ocr_elapsed) * 1000

        return OCRPageResult(
            page_kind=page_kind,
            doc_kind=doc_kind,
            mode_label=mode,
            elapsed_ms=elapsed_ms,
            segments=segments,
            detections=detections,
        )
