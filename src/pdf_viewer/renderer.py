"""PDF page rendering utilities."""
from __future__ import annotations

import os
import tempfile
import threading
from collections import OrderedDict

import fitz

BASE_SCALE = 1.5

# Niveles de zoom intermedios agregados para transiciones más fluidas
ZOOM_LEVELS = [
    0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0
]

# Global semaphore: cap concurrent page renders across all open tabs.
# Subido de 4 → 6: durante un cambio de zoom las 5-6 páginas visibles arrancan
# en paralelo y terminan ~al mismo tiempo, lo que permite que el debounce de
# 30 ms en _schedule_render_update agrupe TODOS los swaps en un único update
# del viewer (sin cascada visible entre las primeras 4 y la 5ª-6ª).
_RENDER_SEM = threading.Semaphore(6)

# Cache entry: (file_path: str, width: int, height: int, png_bytes: None)
# Todas las páginas se cachean como archivo en disco (PNG para zoom ≤ 1.0,
# JPEG para zoom > 1.0). El 4º campo se conserva por compatibilidad y siempre
# es None — ya no se mantienen bytes de imagen en RAM ni se transporta base64.
CacheEntry = tuple


class PageRenderCache:
    """Thread-safe LRU cache for rendered page images (per document instance).

    Límite por número de entradas. Las páginas se guardan como archivos
    temporales en disco (PNG/JPEG); la eviction borra el archivo.  El cap
    evita que múltiples documentos abiertos acumulen demasiados archivos temp.
    """
    _MAX_ENTRIES = 25   # antes 40: menos huella con varios PDFs abiertos

    def __init__(self) -> None:
        self._d: OrderedDict[tuple[int, float], CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, pn: int, zoom: float) -> CacheEntry | None:
        key = (pn, round(zoom, 2))
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def _evict_one_locked(self) -> None:
        _, popped = self._d.popitem(last=False)
        if popped[0] is not None:  # file path → borrar archivo temporal
            try:
                os.remove(popped[0])
            except Exception:
                pass

    def put(self, pn: int, zoom: float, data: CacheEntry) -> None:
        key = (pn, round(zoom, 2))
        with self._lock:
            if key in self._d:
                old = self._d[key]
                if old[0] and old[0] != data[0]:
                    try:
                        os.remove(old[0])
                    except Exception:
                        pass
            self._d[key] = data
            self._d.move_to_end(key)
            while len(self._d) > self._MAX_ENTRIES:
                if len(self._d) <= 1:
                    break
                self._evict_one_locked()

    def invalidate_page(self, pn: int) -> None:
        with self._lock:
            keys_to_delete = [k for k in self._d if k[0] == pn]
            for k in keys_to_delete:
                data = self._d.pop(k)
                if data[0] is not None:
                    try:
                        os.remove(data[0])
                    except Exception:
                        pass

    def keep_pages(self, pages: set[int]) -> None:
        """Evict cache entries whose page is not in the provided set."""
        if not pages:
            return
        with self._lock:
            keys_to_delete = [k for k in self._d if k[0] not in pages]
            for k in keys_to_delete:
                data = self._d.pop(k)
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
    doc_lock: "threading.Lock | None" = None,
    *,
    preview: bool = False,
) -> CacheEntry:
    """Render a PDF page to a temp file.

    Returns (file_path, width, height, None):
      - preview=False, zoom ≤ 1.0: PNG en disco (sin pérdida, texto nítido)
      - preview=False, zoom > 1.0: JPEG en disco (calidad alta sin exceso)
      - preview=True: JPEG q65 siempre — las imágenes preview son temporales
        (≤100 ms antes del upgrade a calidad completa) y no necesitan lossless;
        JPEG q65 es ~3-5x más pequeño → menos IO a disco → preview aparece antes.

    Concurrencia: si se pasa ``doc_lock`` se toma SÓLO durante la rasterización
    (``fitz`` no es thread-safe). La codificación y el IO a disco — la parte
    cara — corren fuera del lock, de modo que páginas del mismo documento ya no
    se serializan por completo. Si ``doc_lock`` es None el llamador debe
    garantizar el acceso exclusivo a ``doc``.
    """
    if cache is not None:
        hit = cache.get(page_num, zoom)
        if hit is not None:
            return hit

    mat = fitz.Matrix(zoom * BASE_SCALE, zoom * BASE_SCALE)

    # alpha=False: sin canal alfa → 25% menos RAM y conversión evitada.
    if doc_lock is not None:
        with doc_lock:
            pix = doc[page_num].get_pixmap(matrix=mat, alpha=False)
    else:
        pix = doc[page_num].get_pixmap(matrix=mat, alpha=False)

    # ── Codificación + IO fuera del doc_lock ──────────────────────────────────
    # pix es una copia independiente del bitmap, no toca el documento.
    if zoom <= 1.0 and not preview:
        # PNG sin pérdida: mantiene la nitidez del texto al zoom habitual.
        # A disco (no base64 en memoria) → transporte ligero hacia Flutter.
        fd, temp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            pix.save(temp_path, output="png")
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise
    else:
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        if preview:
            # Tier LOD: calidad reducida — es temporal, se reemplaza en ≤100 ms.
            jpg_q = 65
        else:
            jpg_q = 90 if zoom <= 2.0 else (82 if zoom <= 3.0 else 80)
        try:
            pix.save(temp_path, output="jpeg", jpg_quality=jpg_q)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise
    result: CacheEntry = (temp_path, pix.width, pix.height, None)

    del pix  # libera el bitmap (~54 MB a zoom=4) antes de que el GC actúe

    if cache is not None:
        cache.put(page_num, zoom, result)

    return result


def display_to_pdf(x: float, y: float, zoom: float) -> tuple[float, float]:
    """Convert on-screen pixel coordinates to PDF point coordinates."""
    scale = zoom * BASE_SCALE
    return x / scale, y / scale