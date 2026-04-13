"""PDF page rendering utilities."""

import base64

import fitz

# Multiplier applied to the PyMuPDF render matrix so the on-screen image is
# sharper than the raw 72-DPI PDF points.
BASE_SCALE = 1.5

ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


def render_page(doc: fitz.Document, page_num: int, zoom: float) -> tuple[str, int, int]:
    """Render a PDF page to a base64-encoded PNG.

    Returns (b64_data, pixel_width, pixel_height).
    """
    page = doc[page_num]
    mat = fitz.Matrix(zoom * BASE_SCALE, zoom * BASE_SCALE)
    pix = page.get_pixmap(matrix=mat)
    b64 = base64.b64encode(pix.tobytes("png")).decode()
    return b64, pix.width, pix.height


def display_to_pdf(x: float, y: float, zoom: float) -> tuple[float, float]:
    """Convert on-screen pixel coordinates to PDF point coordinates."""
    scale = zoom * BASE_SCALE
    return x / scale, y / scale
