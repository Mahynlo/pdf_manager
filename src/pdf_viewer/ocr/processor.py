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


@dataclass
class OCRSegment:
    text: str
    source: str  # native | ocr
    bbox: fitz.Rect


@dataclass
class OCRDetection:
    text: str
    score: float
    source: str  # ocr
    bbox: fitz.Rect


@dataclass
class OCRPageResult:
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

        return words, elapsed

    def get_doc_kind(self, doc: fitz.Document) -> str:
        """Classify the document as 'native', 'scanned', or 'hybrid'.

        Result is cached per document path so processing multiple files in
        one session does not bleed cache between them.
        """
        key = doc.name or id(doc)
        if key in self._doc_kind_cache:
            return self._doc_kind_cache[key]

        text_pages = 0
        image_pages = 0
        max_pages = min(len(doc), 20)

        for i in range(max_pages):
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
        content = page.get_text("dict")
        for block in content.get("blocks", []):
            if block.get("type") != 1:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
            if rect.width < 8 or rect.height < 8:
                continue
            regions.append(rect)

        # Some scanned PDFs have no image blocks; OCR the whole page as fallback.
        if not regions:
            regions.append(page.rect)
        return regions

    @staticmethod
    def _pixmap_to_ndarray(pix: fitz.Pixmap) -> np.ndarray:
        arr = np.frombuffer(pix.samples, dtype=np.uint8)
        arr = arr.reshape(pix.height, pix.width, pix.n)
        if pix.n >= 3:
            return arr[:, :, :3].copy()
        return arr.copy()

    def _ocr_on_regions(self, page: fitz.Page) -> tuple[list[OCRSegment], list[OCRDetection], float]:
        segments: list[OCRSegment] = []
        detections: list[OCRDetection] = []
        total_elapsed = 0.0

        for rect in self._image_regions(page):
            pix = page.get_pixmap(
                matrix=fitz.Matrix(_SCALE_FOR_OCR, _SCALE_FOR_OCR),
                clip=rect,
                alpha=False,
            )
            img = self._pixmap_to_ndarray(pix)

            words, elapsed = self._run_predictor(img)
            total_elapsed += elapsed

            for px_rect, text, score in words:
                x0 = rect.x0 + px_rect.x0 / _SCALE_FOR_OCR
                y0 = rect.y0 + px_rect.y0 / _SCALE_FOR_OCR
                x1 = rect.x0 + px_rect.x1 / _SCALE_FOR_OCR
                y1 = rect.y0 + px_rect.y1 / _SCALE_FOR_OCR
                pdf_rect = fitz.Rect(x0, y0, x1, y1)

                segments.append(OCRSegment(text=text, source="ocr", bbox=pdf_rect))
                detections.append(OCRDetection(text=text, score=score, source="ocr", bbox=pdf_rect))

        return segments, detections, total_elapsed

    def process_page(self, doc: fitz.Document, page_num: int, force_ocr: bool = False) -> OCRPageResult:
        page = doc[page_num]
        doc_kind = self.get_doc_kind(doc)
        page_kind = self.page_kind(page)

        start = perf_counter()
        native_segments = self._native_segments(page)
        ocr_segments: list[OCRSegment] = []
        detections: list[OCRDetection] = []
        ocr_elapsed = 0.0

        if force_ocr or page_kind in ("hybrid", "scanned"):
            ocr_segments, detections, ocr_elapsed = self._ocr_on_regions(page)

        segments = [*native_segments, *ocr_segments]
        segments.sort(key=lambda s: (s.bbox.y0, s.bbox.x0))

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
