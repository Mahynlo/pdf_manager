"""Tests for the orientation detection and correction system.

Covers:
  - detect_orientation_native(): direction-vector detection for native PDFs
  - score_orientation_fast(): pixel-heuristic detection for scanned pages
  - probe_orientation(): dispatch between native / scanned paths
  - page_kind() / get_doc_kind(): document classification
  - rotation_matrix linear-part math (the (p - origin) pattern)
  - set_rotation() arithmetic

No test here loads the MobileNetV3 ML model (score_orientation_classifier).
"""
from __future__ import annotations

import numpy as np
import pytest
import fitz

from pdf_viewer.ocr.processor import OCRProcessor


# ─────────────────────────────────────── helpers


def _proc() -> OCRProcessor:
    return OCRProcessor(workspace_root=".")


def _native_doc(n_lines: int = 3, rotation: int = 0) -> fitz.Document:
    """Return an open fitz.Document with one page, native text, and /Rotate=rotation."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i in range(n_lines):
        page.insert_text((72, 80 + i * 40), f"Texto de prueba línea {i + 1}", fontsize=12)
    if rotation:
        page.set_rotation(rotation)
    return doc


def _apply_linear(rm: fitz.Matrix, dx: float, dy: float) -> tuple[float, float]:
    """Apply only the rotational part of an affine matrix (cancels translation)."""
    origin = fitz.Point(0.0, 0.0) * rm
    p = fitz.Point(dx, dy) * rm
    return p.x - origin.x, p.y - origin.y


# ──────────────────────────────────────────── detect_orientation_native


class TestDetectOrientationNative:
    """Core direction-vector detection — no ML model involved."""

    def test_no_rotation_returns_zero(self):
        doc = _native_doc(rotation=0)
        try:
            assert OCRProcessor.detect_orientation_native(doc[0]) == 0
        finally:
            doc.close()

    def test_rotate_180_detected(self):
        doc = _native_doc(n_lines=5, rotation=180)
        try:
            assert OCRProcessor.detect_orientation_native(doc[0]) == 180
        finally:
            doc.close()

    def test_rotate_90_detected_returns_270(self):
        """/Rotate 90 with portrait content → needs +270° to restore portrait."""
        doc = _native_doc(n_lines=5, rotation=90)
        try:
            angle = OCRProcessor.detect_orientation_native(doc[0])
            assert angle == 270
            assert (90 + angle) % 360 == 0
        finally:
            doc.close()

    def test_rotate_270_detected_returns_90(self):
        """/Rotate 270 with portrait content → needs +90° to restore portrait."""
        doc = _native_doc(n_lines=5, rotation=270)
        try:
            angle = OCRProcessor.detect_orientation_native(doc[0])
            assert angle == 90
            assert (270 + angle) % 360 == 0
        finally:
            doc.close()

    def test_empty_page_returns_zero(self):
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        try:
            assert OCRProcessor.detect_orientation_native(doc[0]) == 0
        finally:
            doc.close()

    def test_full_page_text_rotate_180(self):
        """Full-page text (not just top) is still correctly detected at 180°.

        The old Y-position / 65%-threshold method failed here;
        the direction-vector method should not.
        """
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        for i in range(20):
            page.insert_text((72, 35 + i * 38), f"Línea {i + 1} con bastante texto de relleno", fontsize=11)
        page.set_rotation(180)
        try:
            assert OCRProcessor.detect_orientation_native(doc[0]) == 180
        finally:
            doc.close()

    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_correction_restores_rotation_to_zero(self, rotation):
        """Applying detected angle to page.rotation always yields 0."""
        doc = _native_doc(n_lines=5, rotation=rotation)
        try:
            angle = OCRProcessor.detect_orientation_native(doc[0])
            corrected = (rotation + angle) % 360
            assert corrected == 0, (
                f"rotation={rotation}, detected={angle}, result={corrected}"
            )
        finally:
            doc.close()

    def test_pages_evaluated_independently(self):
        """Each page in a mixed document is evaluated on its own."""
        doc = fitz.open()
        # Page 0: correct
        p0 = doc.new_page(width=595, height=842)
        p0.insert_text((72, 100), "Página correcta sin rotación", fontsize=12)
        # Page 1: inverted
        p1 = doc.new_page(width=595, height=842)
        for i in range(5):
            p1.insert_text((72, 80 + i * 40), f"Página invertida línea {i}", fontsize=12)
        p1.set_rotation(180)
        try:
            assert OCRProcessor.detect_orientation_native(doc[0]) == 0
            assert OCRProcessor.detect_orientation_native(doc[1]) == 180
        finally:
            doc.close()

    def test_single_line_of_text(self):
        """A page with only one line of text still returns the correct angle."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Una sola línea", fontsize=14)
        page.set_rotation(180)
        try:
            assert OCRProcessor.detect_orientation_native(doc[0]) == 180
        finally:
            doc.close()


# ──────────────────────── rotation_matrix linear-part math


class TestRotationMatrixLinearPart:
    """Validate the (p - origin) pattern that extracts pure rotation from an affine matrix.

    This is the fix for the original bug where fitz.Point(dx, dy) * rotation_matrix
    included the page translation (e, f), making a rightward (1,0) vector appear as
    a large positive point like (594, 842) for /Rotate 180.
    """

    def test_rotation_0_is_identity(self):
        doc = _native_doc(rotation=0)
        try:
            vx, vy = _apply_linear(doc[0].rotation_matrix, 1.0, 0.0)
            assert abs(vx - 1.0) < 1e-6 and abs(vy) < 1e-6
        finally:
            doc.close()

    def test_rotation_180_flips_direction(self):
        """For /Rotate 180, direction (1, 0) becomes (-1, 0) in display space."""
        doc = _native_doc(rotation=180)
        try:
            vx, vy = _apply_linear(doc[0].rotation_matrix, 1.0, 0.0)
            assert abs(vx - (-1.0)) < 1e-6 and abs(vy) < 1e-6
        finally:
            doc.close()

    def test_rotation_90_wy_is_positive(self):
        """For /Rotate 90 with portrait text (1,0), wy > 0 → algorithm returns 270°."""
        doc = _native_doc(rotation=90)
        try:
            vx, vy = _apply_linear(doc[0].rotation_matrix, 1.0, 0.0)
            assert vy > 0, f"Expected vy > 0 for /Rotate 90, got ({vx:.4f}, {vy:.4f})"
        finally:
            doc.close()

    def test_rotation_270_wy_is_negative(self):
        """For /Rotate 270 with portrait text (1,0), wy < 0 → algorithm returns 90°."""
        doc = _native_doc(rotation=270)
        try:
            vx, vy = _apply_linear(doc[0].rotation_matrix, 1.0, 0.0)
            assert vy < 0, f"Expected vy < 0 for /Rotate 270, got ({vx:.4f}, {vy:.4f})"
        finally:
            doc.close()

    def test_naive_multiply_wrong_for_180(self):
        """Without (p - origin), the result for /Rotate 180 is wrong (the original bug).

        fitz.Point(1, 0) * rotation_matrix_180 gives something like (W-1, H) —
        both components are large positive — not the direction (-1, 0) we need.
        """
        doc = _native_doc(rotation=180)
        try:
            rm = doc[0].rotation_matrix
            naive = fitz.Point(1.0, 0.0) * rm
            # The naive result must NOT look like a leftward direction:
            # it includes the page translation so both coords are positive/large.
            assert naive.x > 0 or naive.y > 0, (
                "Naive multiply for 180° should yield a large positive result "
                "due to translation, not (-1, 0)"
            )
            # But the corrected version IS (-1, 0):
            origin = fitz.Point(0.0, 0.0) * rm
            vx = naive.x - origin.x
            assert abs(vx - (-1.0)) < 1e-6
        finally:
            doc.close()


# ──────────────────────────────────── score_orientation_fast


class TestScoreOrientationFast:
    """Pixel-heuristic orientation scorer — no ML, < 15 ms, designed for scanned pages."""

    def test_blank_white_image_returns_zero(self):
        img = np.full((400, 300, 3), 255, dtype=np.uint8)
        assert OCRProcessor.score_orientation_fast(img) == 0

    def test_solid_black_image_returns_zero(self):
        img = np.zeros((400, 300, 3), dtype=np.uint8)
        assert OCRProcessor.score_orientation_fast(img) == 0

    def test_grayscale_and_rgb_match(self):
        """2-D (grayscale) and 3-D (RGB) inputs give the same result."""
        gray = np.full((400, 300), 230, dtype=np.uint8)
        rgb = np.full((400, 300, 3), 230, dtype=np.uint8)
        assert OCRProcessor.score_orientation_fast(gray) == OCRProcessor.score_orientation_fast(rgb)

    def test_horizontal_stripes_not_lateral(self):
        """Horizontal text-like stripes → result is 0 or 180, never 90 or 270."""
        img = np.full((500, 400), 240, dtype=np.uint8)
        for y in (80, 140, 200, 260, 320, 380):
            img[y:y + 7, 40:360] = 25
        result = OCRProcessor.score_orientation_fast(img)
        assert result not in (90, 270), f"Horizontal stripes gave {result}"

    def test_vertical_stripes_are_lateral(self):
        """Vertical text-like stripes → result is 90 or 270."""
        img = np.full((400, 500), 240, dtype=np.uint8)
        for x in (60, 130, 200, 270, 340, 410):
            img[40:360, x:x + 7] = 25
        result = OCRProcessor.score_orientation_fast(img)
        assert result in (90, 270), f"Vertical stripes gave {result}"

    def test_returns_one_of_four_angles(self):
        """Whatever the input, the return value is always in {0, 90, 180, 270}."""
        rng = np.random.default_rng(42)
        for _ in range(10):
            img = rng.integers(0, 256, (300, 400, 3), dtype=np.uint8)
            assert OCRProcessor.score_orientation_fast(img) in (0, 90, 180, 270)


# ──────────────────────────────────────────── probe_orientation


class TestProbeOrientation:
    """Dispatch logic: native pages → direction vectors; empty pages → image methods."""

    def test_native_page_returns_non_none_angle(self):
        doc = _native_doc(rotation=0)
        try:
            img, native_angle = _proc().probe_orientation(doc, 0)
            assert native_angle is not None
            assert isinstance(img, np.ndarray) and img.size > 0
        finally:
            doc.close()

    def test_empty_page_returns_none_angle(self):
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        try:
            img, native_angle = _proc().probe_orientation(doc, 0)
            assert native_angle is None
            assert isinstance(img, np.ndarray) and img.size > 0
        finally:
            doc.close()

    def test_rotated_native_page_native_angle_matches_detect(self):
        """probe_orientation must return the same angle as detect_orientation_native."""
        doc = _native_doc(n_lines=5, rotation=180)
        try:
            _, native_angle = _proc().probe_orientation(doc, 0)
            direct = OCRProcessor.detect_orientation_native(doc[0])
            assert native_angle == direct
        finally:
            doc.close()

    def test_image_shape_is_reasonable(self):
        """The rasterized probe must be a 3-D RGB array with sensible dimensions."""
        doc = _native_doc()
        try:
            img, _ = _proc().probe_orientation(doc, 0)
            assert img.ndim == 3
            assert img.shape[2] == 3
            assert img.shape[0] >= 50 and img.shape[1] >= 50
        finally:
            doc.close()


# ──────────────────────────────── document / page classification


class TestDocumentClassification:

    def test_text_only_page_is_native(self):
        doc = _native_doc()
        try:
            assert _proc().page_kind(doc[0]) == "native"
        finally:
            doc.close()

    def test_empty_page_is_scanned(self):
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        try:
            assert _proc().page_kind(doc[0]) == "scanned"
        finally:
            doc.close()

    def test_get_doc_kind_native_document(self):
        doc = fitz.open()
        for _ in range(3):
            p = doc.new_page(width=595, height=842)
            p.insert_text((72, 100), "Texto nativo", fontsize=12)
        try:
            assert _proc().get_doc_kind(doc) == "native"
        finally:
            doc.close()

    def test_page_needs_ocr_with_text_is_false(self):
        doc = _native_doc()
        try:
            assert _proc().page_needs_ocr(doc[0]) is False
        finally:
            doc.close()

    def test_page_needs_ocr_without_text_is_true(self):
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        try:
            assert _proc().page_needs_ocr(doc[0]) is True
        finally:
            doc.close()

    def test_get_doc_kind_result_is_cached(self):
        """Second call with the same document returns the cached value."""
        doc = _native_doc()
        proc = _proc()
        try:
            kind1 = proc.get_doc_kind(doc)
            kind2 = proc.get_doc_kind(doc)
            assert kind1 == kind2 == "native"
        finally:
            doc.close()


# ────────────────────────────── correction arithmetic


class TestCorrectionArithmetic:
    """set_rotation((current + correction) % 360) must always yield a valid angle."""

    @pytest.mark.parametrize("current, correction, expected", [
        (0,   0,   0),
        (0,   90,  90),
        (0,   180, 180),
        (0,   270, 270),
        (90,  270, 0),      # 90° rotated page corrected by 270° → portrait
        (180, 180, 0),      # inverted page corrected by 180° → correct
        (270, 90,  0),      # 270° rotated page corrected by 90° → portrait
        (90,  90,  180),
        (180, 90,  270),
        (270, 270, 180),
    ])
    def test_rotation_arithmetic(self, current, correction, expected):
        assert (current + correction) % 360 == expected

    @pytest.mark.parametrize("rotation", [90, 180, 270])
    def test_end_to_end_detect_and_apply(self, rotation):
        """Detect the angle, apply it with set_rotation, verify the page reads /Rotate 0."""
        doc = _native_doc(n_lines=6, rotation=rotation)
        try:
            angle = OCRProcessor.detect_orientation_native(doc[0])
            assert angle != 0, f"Expected non-zero angle for /Rotate {rotation}, got 0"
            doc[0].set_rotation((doc[0].rotation + angle) % 360)
            assert doc[0].rotation == 0, (
                f"After correction page should have /Rotate 0, "
                f"got {doc[0].rotation} (started at {rotation}, applied {angle})"
            )
        finally:
            doc.close()
