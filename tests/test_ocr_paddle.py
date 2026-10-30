"""Motor de OCR con los modelos de PaddleOCR (``pdf_core.ocr.paddle``).

Las primeras pruebas cubren el pre y posprocesado con NumPy; las demás cargan
los modelos reales (``src/assets/ocr_models``) sobre un escaneo generado.
"""
from __future__ import annotations

import fitz
import numpy as np
import pytest

from pdf_core.ocr import OCRProcessor
from pdf_core.ocr.paddle import MODELS_DIR, REC_MODEL, connected_boxes, resize

LINES = [
    "Factura número 2024 del año pasado",
    "Dirección: Calle Mayor, España",
    "Importe total pendiente de pago",
] * 6


def _scan(rotation: int = 0) -> fitz.Document:
    """PDF de una página que solo es una imagen (como un escaneo), con ``/Rotate``."""
    text = fitz.open()
    page = text.new_page(width=595, height=842)
    for i, line in enumerate(LINES):
        page.insert_text((60, 80 + i * 38), line, fontsize=16, fontname="helv")
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    scan = fitz.open()
    out = scan.new_page(width=595, height=842)
    out.insert_image(out.rect, pixmap=pix)
    if rotation:
        out.set_rotation(rotation)
    return scan


@pytest.fixture(scope="module")
def processor() -> OCRProcessor:
    return OCRProcessor(".")


# ── Pre y posprocesado ───────────────────────────────────────────────────────
def test_resize_is_bilinear_like_opencv():
    img = (np.arange(4, dtype=np.uint8).reshape(2, 2, 1)) * 10
    out = resize(img, 4, 4)[..., 0]
    assert out.dtype == np.float32
    np.testing.assert_allclose(out[0], [0, 2.5, 7.5, 10])  # lo mismo que cv2.INTER_LINEAR
    np.testing.assert_allclose(out[:, 0], [0, 5, 15, 20])
    same = np.random.default_rng(0).integers(0, 255, (7, 9, 3), dtype=np.uint8)
    np.testing.assert_array_equal(resize(same, 9, 7), same)


def test_connected_boxes_join_diagonals_and_separate_blobs():
    mask = np.zeros((8, 10), bool)
    mask[1, 1:3] = True
    mask[2, 3] = True    # toca el tramo anterior solo en diagonal: mismo componente
    mask[5:7, 6:9] = True
    assert sorted(connected_boxes(mask)) == [(1, 1, 4, 3), (6, 5, 9, 7)]
    assert connected_boxes(np.zeros((3, 3), bool)) == []


def test_models_are_bundled():
    for name in ("PP-OCRv6_small_det.onnx", f"{REC_MODEL}.onnx", f"{REC_MODEL}_dict.txt", "PP-LCNet_x1_0_doc_ori.onnx"):
        assert (MODELS_DIR / name).is_file(), name


# ── Modelos reales ───────────────────────────────────────────────────────────
def test_reads_spanish_words_with_boxes(processor):
    with _scan() as doc:
        result = processor.process_page(doc, 0)
    words = [d.text for d in result.detections]
    assert result.mode_label == "OCR"
    for expected in ("Factura", "número", "año", "Dirección:", "España", "Importe"):
        assert expected in words
    first = next(d for d in result.detections if d.text == "Factura")
    after = next(d for d in result.detections if d.text == "número")
    # Cajas por palabra en coordenadas de la página, en la primera línea y en orden.
    assert 50 < first.bbox.x0 < after.bbox.x0 and first.bbox.x1 <= after.bbox.x0 + 2
    assert first.bbox.y0 < 80 < first.bbox.y1 + 4
    assert all(0 <= d.score <= 1 for d in result.detections)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_orientation_classifier_gives_the_correction(processor, rotation):
    with _scan(rotation) as doc:
        page = doc[0]
        img = processor._pixmap_to_ndarray(page.get_pixmap(matrix=fitz.Matrix(0.8, 0.8), alpha=False))
        angle, confidence = processor.classify_orientation(img)
        assert angle == (360 - rotation) % 360 and confidence > 0.9
        assert processor.correction_angle(page) == (360 - rotation) % 360


def test_release_and_reload(processor):
    processor.predictor
    processor.release_predictor()
    processor.release_orientation_predictor()
    assert processor._predictor is None and processor._orientation_predictor is None
    with _scan() as doc:
        assert processor.process_page(doc, 0).detections  # se vuelve a cargar al usarlo
