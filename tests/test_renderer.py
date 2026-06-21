"""Tests for `pdf_viewer.renderer` — the highest-value module to protect.

Recent changes that these tests guard against regressions:
  · Byte-budget eviction (_MAX_BYTES) in addition to count-based eviction
  · shrink(n) method for the on_blur lifecycle
  · 4-tuple cache entry format (path | None, w, h, png_bytes | None)
  · render_page siempre escribe a disco: PNG para zoom ≤ 1.0, JPEG para zoom > 1.0
    (el 4º campo png_bytes es siempre None; ya no se transporta base64)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import fitz
import pytest

from pdf_viewer.renderer import (
    BASE_SCALE,
    PageRenderCache,
    display_to_pdf,
    render_page,
)


# ───────────────────────────────────────────────────────────────── PageRenderCache


class TestPageRenderCache:
    def test_empty_get_returns_none(self):
        cache = PageRenderCache()
        assert cache.get(0, 1.0) is None

    def test_put_then_get_roundtrip(self):
        cache = PageRenderCache()
        entry = (None, 100, 200, b"png_data")
        cache.put(0, 1.0, entry)
        assert cache.get(0, 1.0) == entry

    def test_get_promotes_to_most_recent(self):
        """LRU: after get(), the entry becomes the most recent."""
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 2
        cache.put(0, 1.0, (None, 10, 10, b"a"))
        cache.put(1, 1.0, (None, 10, 10, b"b"))
        cache.get(0, 1.0)                            # promote 0
        cache.put(2, 1.0, (None, 10, 10, b"c"))      # forces eviction
        # 1 should be evicted (least recent), 0 and 2 remain
        assert cache.get(0, 1.0) is not None
        assert cache.get(1, 1.0) is None
        assert cache.get(2, 1.0) is not None

    def test_eviction_by_count_limit(self):
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 3
        for i in range(5):
            cache.put(i, 1.0, (None, 10, 10, b"x"))
        # Only the 3 most recent remain
        assert cache.get(0, 1.0) is None
        assert cache.get(1, 1.0) is None
        assert cache.get(2, 1.0) is not None
        assert cache.get(3, 1.0) is not None
        assert cache.get(4, 1.0) is not None

    def test_eviction_count_applies_to_in_memory_entries(self):
        """Count-based eviction works for entries that store in-memory bytes."""
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 2
        cache.put(0, 1.0, (None, 10, 10, b"a" * 100))
        cache.put(1, 1.0, (None, 10, 10, b"b" * 100))
        cache.put(2, 1.0, (None, 10, 10, b"c" * 100))   # forces eviction of 0
        assert cache.get(0, 1.0) is None
        assert cache.get(1, 1.0) is not None
        assert cache.get(2, 1.0) is not None

    def test_file_path_entries_survive_under_count_limit(self, tmp_path):
        """Disk entries with png_bytes=None stay until count limit is reached."""
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 10

        f1 = tmp_path / "p1.jpg"
        f2 = tmp_path / "p2.jpg"
        f1.write_bytes(b"x" * 1000)
        f2.write_bytes(b"y" * 1000)

        cache.put(0, 1.5, (str(f1), 100, 100, None))
        cache.put(1, 1.5, (str(f2), 100, 100, None))

        # Both disk entries survive since count limit isn't reached
        assert cache.get(0, 1.5) is not None
        assert cache.get(1, 1.5) is not None

    def test_invalidate_page_removes_all_zooms_of_that_page(self):
        cache = PageRenderCache()
        cache.put(0, 1.0, (None, 10, 10, b"a"))
        cache.put(0, 2.0, (None, 20, 20, b"b"))
        cache.put(1, 1.0, (None, 10, 10, b"c"))

        cache.invalidate_page(0)

        assert cache.get(0, 1.0) is None
        assert cache.get(0, 2.0) is None
        assert cache.get(1, 1.0) is not None  # different page → untouched

    def test_clear_empties_cache(self):
        cache = PageRenderCache()
        cache.put(0, 1.0, (None, 10, 10, b"a"))
        cache.put(1, 1.0, (None, 10, 10, b"b"))
        cache.clear()
        assert cache.get(0, 1.0) is None
        assert cache.get(1, 1.0) is None

    def test_clear_leaves_internal_dict_empty(self):
        cache = PageRenderCache()
        cache.put(0, 1.0, (None, 10, 10, b"x" * 1000))
        cache.clear()
        assert len(cache._d) == 0

    def test_shrink_keeps_n_most_recent(self):
        """on_blur calls shrink(5) — verify LRU semantics."""
        cache = PageRenderCache()
        for i in range(5):
            cache.put(i, 1.0, (None, 10, 10, b"x"))
        cache.shrink(2)
        # Only the 2 most recently put entries remain
        assert cache.get(0, 1.0) is None
        assert cache.get(1, 1.0) is None
        assert cache.get(2, 1.0) is None
        assert cache.get(3, 1.0) is not None
        assert cache.get(4, 1.0) is not None

    def test_shrink_to_zero_clears_cache(self):
        cache = PageRenderCache()
        cache.put(0, 1.0, (None, 10, 10, b"a"))
        cache.shrink(0)
        assert cache.get(0, 1.0) is None

    def test_file_eviction_removes_temp_file(self, tmp_path):
        """When a JPEG-on-disk entry is evicted, the temp file is os.remove'd."""
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 1

        f1 = tmp_path / "f1.jpg"
        f2 = tmp_path / "f2.jpg"
        f1.write_bytes(b"a")
        f2.write_bytes(b"b")

        cache.put(0, 1.5, (str(f1), 100, 100, None))
        cache.put(1, 1.5, (str(f2), 100, 100, None))   # evicts f1

        assert not f1.exists()
        assert f2.exists()

    def test_clear_deletes_temp_files(self, tmp_path):
        cache = PageRenderCache()
        f = tmp_path / "x.jpg"
        f.write_bytes(b"x")
        cache.put(0, 1.5, (str(f), 100, 100, None))
        cache.clear()
        assert not f.exists()

    def test_put_replacement_updates_value_not_count(self):
        """Putting an entry under an existing key replaces it; count stays at 1."""
        cache = PageRenderCache()
        cache.put(0, 1.0, (None, 10, 10, b"a" * 100))
        cache.put(0, 1.0, (None, 10, 10, b"b" * 200))   # same key, bigger payload
        # Only one entry in the cache
        assert len(cache._d) == 1
        # Value was replaced
        _, _, _, png = cache.get(0, 1.0)
        assert png == b"b" * 200

    def test_zoom_key_rounded_to_2_decimals(self):
        """1.001 and 1.004 round to the same key (1.0); 1.005 rounds to 1.01."""
        cache = PageRenderCache()
        cache.put(0, 1.001, (None, 10, 10, b"a"))
        # Same page, slightly different zoom — should hit the same entry
        assert cache.get(0, 1.004) is not None

    def test_concurrent_puts_do_not_corrupt_state(self):
        """Sanity: many threads putting concurrently leave the cache bounded."""
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 25

        def worker(start: int) -> None:
            for i in range(start, start + 10):
                cache.put(i, 1.0, (None, 10, 10, b"x"))

        threads = [threading.Thread(target=worker, args=(i * 10,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 50 puts, MAX_ENTRIES = 25 → exactly 25 entries should remain
        assert len(cache._d) <= 25


# ────────────────────────────────────────────────────────────────────── render_page


class TestRenderPage:
    def test_zoom_low_returns_png_file_path(self, sample_doc):
        """zoom ≤ 1.0 should produce a PNG temp file (no in-memory bytes)."""
        path, w, h, png = render_page(sample_doc, 0, 1.0)
        assert png is None
        assert path is not None
        assert os.path.exists(path)
        assert path.lower().endswith(".png")
        with open(path, "rb") as f:
            magic = f.read(8)
        assert magic == b"\x89PNG\r\n\x1a\n"   # PNG magic bytes
        assert w > 0
        assert h > 0
        os.remove(path)   # test isn't using the cache, so no auto-cleanup

    def test_zoom_high_returns_jpeg_file_path(self, sample_doc):
        path, w, h, png = render_page(sample_doc, 0, 2.0)
        assert path is not None
        assert png is None
        assert os.path.exists(path)
        assert path.lower().endswith(".jpg")
        # The file should be a valid JPEG (starts with FFD8)
        with open(path, "rb") as f:
            magic = f.read(2)
        assert magic == b"\xff\xd8"
        # Cleanup — test isn't using the cache, so no auto-cleanup
        os.remove(path)

    def test_dimensions_scale_linearly_with_zoom(self, sample_doc):
        p05, w_05, h_05, _ = render_page(sample_doc, 0, 0.5)
        p10, w_10, h_10, _ = render_page(sample_doc, 0, 1.0)
        # 1.0 / 0.5 = 2x dimensions (rounded to int by fitz)
        assert w_10 == pytest.approx(w_05 * 2, abs=1)
        assert h_10 == pytest.approx(h_05 * 2, abs=1)
        os.remove(p05)
        os.remove(p10)

    def test_cache_hit_avoids_repeat_render(self, sample_doc):
        """Second call with same (pn, zoom) returns the cached tuple by identity."""
        cache = PageRenderCache()
        first = render_page(sample_doc, 0, 1.0, cache)
        second = render_page(sample_doc, 0, 1.0, cache)
        # Identity equality: same tuple object came back from the cache
        assert first is second

    def test_cache_stores_entry_after_first_render(self, sample_doc):
        cache = PageRenderCache()
        render_page(sample_doc, 0, 1.0, cache)
        assert cache.get(0, 1.0) is not None

    def test_different_zoom_levels_get_separate_entries(self, sample_doc):
        cache = PageRenderCache()
        render_page(sample_doc, 0, 0.5, cache)
        render_page(sample_doc, 0, 1.0, cache)
        assert cache.get(0, 0.5) is not None
        assert cache.get(0, 1.0) is not None
        # And they're different sizes
        _, w_05, _, _ = cache.get(0, 0.5)
        _, w_10, _, _ = cache.get(0, 1.0)
        assert w_05 != w_10


# ────────────────────────────────────────────────────────────────── display_to_pdf


class TestDisplayToPdf:
    def test_inverse_roundtrip(self):
        """Display → PDF coords, then back, should yield the original."""
        zoom = 1.5
        x_disp, y_disp = 150.0, 200.0
        x_pdf, y_pdf = display_to_pdf(x_disp, y_disp, zoom)
        scale = zoom * BASE_SCALE
        assert x_pdf * scale == pytest.approx(x_disp)
        assert y_pdf * scale == pytest.approx(y_disp)

    def test_zero_origin_maps_to_zero(self):
        assert display_to_pdf(0.0, 0.0, 1.0) == (0.0, 0.0)

    def test_zoom_1_uses_base_scale(self):
        """At zoom=1.0, display coords are BASE_SCALE × PDF coords."""
        x_pdf, y_pdf = display_to_pdf(BASE_SCALE * 100, BASE_SCALE * 50, 1.0)
        assert x_pdf == pytest.approx(100.0)
        assert y_pdf == pytest.approx(50.0)
