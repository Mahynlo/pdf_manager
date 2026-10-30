"""OCR y detección de orientación con los modelos de PaddleOCR sobre onnxruntime
(``paddle.py``; los modelos se cargan al usarlos)."""

from .processor import OCRDetection, OCRPageResult, OCRProcessor, OCRSegment

__all__ = [
    "OCRDetection",
    "OCRPageResult",
    "OCRProcessor",
    "OCRSegment",
]
