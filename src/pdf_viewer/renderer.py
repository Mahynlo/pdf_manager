"""PDF page rendering utilities."""
from __future__ import annotations

import base64
import threading
from collections import OrderedDict

import fitz

BASE_SCALE = 1.5
ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]

# Global semaphore: cap concurrent page renders across all open tabs.
_RENDER_SEM = threading.Semaphore(4)


class PageRenderCache:
    """Thread-safe LRU cache for rendered page images (per document instance)."""
    _MAX_ENTRIES = 25

    def __init__(self) -> None:
        self._d: OrderedDict[tuple[int, float], tuple[str, int, int]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, pn: int, zoom: float) -> tuple[str, int, int] | None:
        key = (pn, round(zoom, 2))
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, pn: int, zoom: float, data: tuple[str, int, int]) -> None:
        key = (pn, round(zoom, 2))
        with self._lock:
            self._d[key] = data
            self._d.move_to_end(key)
            while len(self._d) > self._MAX_ENTRIES:
                self._d.popitem(last=False)

    def invalidate_page(self, pn: int) -> None:
        with self._lock:
            for k in [k for k in self._d if k[0] == pn]:
                del self._d[k]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


def render_page(
    doc: fitz.Document,
    page_num: int,
    zoom: float,
    cache: PageRenderCache | None = None,
) -> tuple[str, int, int]:
    """Render a PDF page to a base64-encoded JPEG.

    Returns (b64_data, pixel_width, pixel_height).
    Caller must hold doc_lock before calling this function.
    """
    if cache is not None:
        hit = cache.get(page_num, zoom)
        if hit is not None:
            return hit

    page = doc[page_num]
    mat = fitz.Matrix(zoom * BASE_SCALE, zoom * BASE_SCALE)
    pix = page.get_pixmap(matrix=mat)
    # JPEG does not support alpha; flatten to RGB if needed.
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    # PNG for low zoom (text is small — lossless avoids visible compression blur);
    # JPEG at high quality for high zoom (large pixmaps keep reasonable size).
    if zoom <= 1.0:
        img_bytes = pix.tobytes("png")
    else:
        jpg_q = 95 if zoom <= 2.0 else 92
        img_bytes = pix.tobytes("jpeg", jpg_quality=jpg_q)
    b64 = base64.b64encode(img_bytes).decode()
    result = b64, pix.width, pix.height

    if cache is not None:
        cache.put(page_num, zoom, result)

    return result


def display_to_pdf(x: float, y: float, zoom: float) -> tuple[float, float]:
    """Convert on-screen pixel coordinates to PDF point coordinates."""
    scale = zoom * BASE_SCALE
    return x / scale, y / scale
