"""PDF page rendering utilities."""
from __future__ import annotations

import os
import tempfile
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
                _, popped_data = self._d.popitem(last=False)
                try:
                    os.remove(popped_data[0])
                except Exception:
                    pass

    def invalidate_page(self, pn: int) -> None:
        with self._lock:
            keys_to_delete = [k for k in self._d if k[0] == pn]
            for k in keys_to_delete:
                data = self._d.pop(k)
                try:
                    os.remove(data[0])
                except Exception:
                    pass

    def clear(self) -> None:
        with self._lock:
            for k, data in self._d.items():
                try:
                    os.remove(data[0])
                except Exception:
                    pass
            self._d.clear()


def render_page(
    doc: fitz.Document,
    page_num: int,
    zoom: float,
    cache: PageRenderCache | None = None,
) -> tuple[str, int, int]:
    """Render a PDF page to a temporary file.

    Returns (file_path, pixel_width, pixel_height).
    Caller must hold doc_lock before calling this function.
    """
    if cache is not None:
        hit = cache.get(page_num, zoom)
        if hit is not None:
            return hit

    page = doc[page_num]
    mat = fitz.Matrix(zoom * BASE_SCALE, zoom * BASE_SCALE)
    
    # Generar directamente sin canal alfa mejora drásticamente
    # el consumo de RAM y la velocidad, evitando la conversión posterior.
    pix = page.get_pixmap(matrix=mat, alpha=False)
    
    fd, temp_path = tempfile.mkstemp(suffix=".png" if zoom <= 1.0 else ".jpg")
    os.close(fd)
    
    # PNG for low zoom (text is small — lossless avoids visible compression blur);
    # JPEG at high quality for high zoom (large pixmaps keep reasonable size).
    if zoom <= 1.0:
        pix.save(temp_path, output="png")
    else:
        jpg_q = 95 if zoom <= 2.0 else 92
        img_bytes = pix.tobytes("jpeg", jpg_quality=jpg_q)
        with open(temp_path, "wb") as f:
            f.write(img_bytes)

    result = temp_path, pix.width, pix.height

    if cache is not None:
        cache.put(page_num, zoom, result)

    return result


def display_to_pdf(x: float, y: float, zoom: float) -> tuple[float, float]:
    """Convert on-screen pixel coordinates to PDF point coordinates."""
    scale = zoom * BASE_SCALE
    return x / scale, y / scale
