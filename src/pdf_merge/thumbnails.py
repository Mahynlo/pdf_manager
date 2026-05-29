"""Thumbnail cache for the merge feature — no Flet.

Wraps `engine.render_thumbnail` with an in-memory `(path, page) → base64 PNG`
cache at a fixed scale. The merge tab keeps two instances: 0.25× for the
selection chips / preview grid and 0.5× for the lightbox.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from . import engine


class ThumbnailCache:
    """Thread-safe cache of base64-encoded page thumbnails at one scale."""

    _DEFAULT_MAX_ENTRIES = 256
    _DEFAULT_MAX_BYTES = 48 * 1024 * 1024

    def __init__(
        self,
        scale: float,
        max_entries: int | None = None,
        max_bytes: int | None = None,
    ):
        self._scale = scale
        self._max_entries = max_entries or self._DEFAULT_MAX_ENTRIES
        self._max_bytes = max_bytes or self._DEFAULT_MAX_BYTES
        self._cache: OrderedDict[tuple[str, int], str] = OrderedDict()
        self._bytes_used = 0
        self._lock = threading.Lock()

    def get(self, path: str, page: int, password: str | None = None) -> str | None:
        """Return the cached thumbnail, rendering and caching it on a miss."""
        key = (path, page)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
        if cached is not None:
            return cached
        b64 = engine.render_thumbnail(path, page, self._scale, password=password)
        if b64 is not None:
            with self._lock:
                prev = self._cache.get(key)
                if prev is not None:
                    self._bytes_used -= len(prev)
                self._cache[key] = b64
                self._cache.move_to_end(key)
                self._bytes_used += len(b64)
                self._evict_locked()
        return b64

    def has(self, path: str, page: int) -> bool:
        with self._lock:
            return (path, page) in self._cache

    def prune_path(self, path: str) -> None:
        """Drop every cached page belonging to *path*."""
        with self._lock:
            for key in [k for k in self._cache if k[0] == path]:
                self._bytes_used -= len(self._cache[key])
                del self._cache[key]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._bytes_used = 0

    def _evict_locked(self) -> None:
        while self._cache and (
            len(self._cache) > self._max_entries
            or self._bytes_used > self._max_bytes
        ):
            _, value = self._cache.popitem(last=False)
            self._bytes_used -= len(value)
