"""Thumbnail cache for the merge feature — no Flet.

Wraps `engine.render_thumbnail` with an in-memory `(path, page) → base64 PNG`
cache at a fixed scale. The merge tab keeps two instances: 0.25× for the
selection chips / preview grid and 0.5× for the lightbox.
"""
from __future__ import annotations

import threading

from . import engine


class ThumbnailCache:
    """Thread-safe cache of base64-encoded page thumbnails at one scale."""

    def __init__(self, scale: float):
        self._scale = scale
        self._cache: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()

    def get(self, path: str, page: int, password: str | None = None) -> str | None:
        """Return the cached thumbnail, rendering and caching it on a miss."""
        key = (path, page)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        b64 = engine.render_thumbnail(path, page, self._scale, password=password)
        if b64 is not None:
            with self._lock:
                self._cache[key] = b64
        return b64

    def has(self, path: str, page: int) -> bool:
        with self._lock:
            return (path, page) in self._cache

    def prune_path(self, path: str) -> None:
        """Drop every cached page belonging to *path*."""
        with self._lock:
            for key in [k for k in self._cache if k[0] == path]:
                del self._cache[key]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
