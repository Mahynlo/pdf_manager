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

# Cache entry: (file_path: str | None, width: int, height: int, png_bytes: bytes | None)
# - file_path set, png_bytes=None  → JPEG en disco (zoom > 1.0)
# - file_path=None, png_bytes set  → PNG en memoria (zoom ≤ 1.0)
CacheEntry = tuple


class PageRenderCache:
    """Thread-safe LRU cache for rendered page images (per document instance).

    Tiene dos límites: cantidad de entradas y bytes totales en memoria. La
    eviction sucede cuando se supera cualquiera de los dos. Esto evita que
    múltiples documentos abiertos acumulen cientos de MB de PNGs cacheados.
    """
    _MAX_ENTRIES = 25                  # antes 40: menos huella con varios PDFs abiertos
    _MAX_BYTES   = 8 * 1024 * 1024     # 8 MB de PNGs por tab (hard cap)

    def __init__(self) -> None:
        self._d: OrderedDict[tuple[int, float], CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._bytes_used = 0

    @staticmethod
    def _entry_bytes(entry: CacheEntry) -> int:
        # entry = (path, w, h, png_bytes)
        png = entry[3]
        return len(png) if png is not None else 0

    def get(self, pn: int, zoom: float) -> CacheEntry | None:
        key = (pn, round(zoom, 2))
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def _evict_one_locked(self) -> None:
        _, popped = self._d.popitem(last=False)
        self._bytes_used -= self._entry_bytes(popped)
        if popped[0] is not None:  # file path → borrar archivo temporal
            try:
                os.remove(popped[0])
            except Exception:
                pass

    def put(self, pn: int, zoom: float, data: CacheEntry) -> None:
        key = (pn, round(zoom, 2))
        with self._lock:
            if key in self._d:
                # Reemplazo: descontar el viejo antes de sobrescribir.
                self._bytes_used -= self._entry_bytes(self._d[key])
            self._d[key] = data
            self._d.move_to_end(key)
            self._bytes_used += self._entry_bytes(data)
            while len(self._d) > self._MAX_ENTRIES or self._bytes_used > self._MAX_BYTES:
                if len(self._d) <= 1:
                    break  # nunca eviccionar la única entrada
                self._evict_one_locked()

    def invalidate_page(self, pn: int) -> None:
        with self._lock:
            keys_to_delete = [k for k in self._d if k[0] == pn]
            for k in keys_to_delete:
                data = self._d.pop(k)
                self._bytes_used -= self._entry_bytes(data)
                if data[0] is not None:
                    try:
                        os.remove(data[0])
                    except Exception:
                        pass

    def clear(self) -> None:
        with self._lock:
            for data in self._d.values():
                if data[0] is not None:
                    try:
                        os.remove(data[0])
                    except Exception:
                        pass
            self._d.clear()
            self._bytes_used = 0

    def shrink(self, max_entries: int) -> None:
        """Evict entries until len(cache) <= max_entries. Llamado en on_blur."""
        with self._lock:
            while len(self._d) > max_entries:
                self._evict_one_locked()


def render_page(
    doc: fitz.Document,
    page_num: int,
    zoom: float,
    cache: PageRenderCache | None = None,
) -> CacheEntry:
    """Render a PDF page.

    Returns (file_path, width, height, png_bytes):
      - zoom ≤ 1.0: PNG en memoria (png_bytes set, file_path=None)
      - zoom > 1.0: JPEG en disco (file_path set, png_bytes=None)
    Caller must hold doc_lock before calling this function.
    """
    if cache is not None:
        hit = cache.get(page_num, zoom)
        if hit is not None:
            return hit

    page = doc[page_num]
    mat = fitz.Matrix(zoom * BASE_SCALE, zoom * BASE_SCALE)

    # alpha=False: sin canal alfa → 25% menos RAM y conversión evitada.
    pix = page.get_pixmap(matrix=mat, alpha=False)

    if zoom <= 1.0:
        # PNG crudo en memoria: sin overhead de base64 (33%) en el caché.
        # El worker codifica a base64 sólo al asignar a img.src_base64.
        raw = pix.tobytes("png")
        result: CacheEntry = (None, pix.width, pix.height, raw)
    else:
        # JPEG a disco para zooms altos (pixmaps grandes: calidad alta sin exceso).
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        jpg_q = 90 if zoom <= 2.0 else 82
        pix.save(temp_path, output="jpeg", jpg_quality=jpg_q)
        result = (temp_path, pix.width, pix.height, None)

    del pix  # libera el bitmap (~54 MB a zoom=4) antes de que el GC actúe

    if cache is not None:
        cache.put(page_num, zoom, result)

    return result


def display_to_pdf(x: float, y: float, zoom: float) -> tuple[float, float]:
    """Convert on-screen pixel coordinates to PDF point coordinates."""
    scale = zoom * BASE_SCALE
    return x / scale, y / scale
