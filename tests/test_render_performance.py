"""Performance / resource-bound tests for the viewer's rendering path.

A diferencia de ``test_renderer.py`` (correctitud funcional), estos tests fijan
las *propiedades de rendimiento* que sostienen al visor:

  · Un cache hit evita re-rasterizar (coste de render ≈ lookup de dict).
  · La memoria del render cache queda acotada bajo carga (cuenta y bytes).
  · Las cachés de texto quedan acotadas a una ventana sin importar cuántas
    páginas recorra el usuario — la propiedad que motivó ``_prune_text_caches``.

Las aserciones deterministas (tamaños acotados) son las preferidas; las basadas
en tiempo usan comparaciones relativas con márgenes amplios y toman el mínimo de
varias mediciones para no ser frágiles en CI.
"""
from __future__ import annotations

import os
import time
import types

import fitz
import pytest

from pdf_viewer.renderer import PageRenderCache, render_page
from pdf_viewer._render_mixin import _RenderMixin
from pdf_viewer._viewer_defs import _TEXT_CACHE_KEEP_PAGES


# ── helpers ────────────────────────────────────────────────────────────────────


def _text_window() -> int:
    """Tamaño máximo de la ventana de cachés de texto (radio*2 + 1)."""
    radius = max(0, (_TEXT_CACHE_KEEP_PAGES - 1) // 2)
    return radius * 2 + 1


class _FakeDoc:
    """Stand-in: sólo se usa ``len(doc)`` en _prune_text_caches."""

    def __init__(self, n: int) -> None:
        self._n = n

    def __len__(self) -> int:
        return self._n


def _make_stub(total: int) -> types.SimpleNamespace:
    """Objeto mínimo con los atributos que toca _prune_text_caches."""
    return types.SimpleNamespace(
        doc=_FakeDoc(total),
        _text_sel_start_pn=None,
        _text_sel_end_pn=None,
        _page_words={},
        _page_word_bands={},
        _page_blocks_cache={},
        _text_rects_cache={},
    )


def _all_text_caches(stub):
    return (
        stub._page_words,
        stub._page_word_bands,
        stub._page_blocks_cache,
        stub._text_rects_cache,
    )


def _best_time(fn, repeats: int = 5) -> float:
    """Mínimo de varias ejecuciones — descarta ruido de scheduling."""
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


# ── render cache: el hit evita re-rasterizar ───────────────────────────────────


class TestRenderCacheHitPerformance:
    def test_cache_hit_returns_same_object_without_rerender(self, sample_doc):
        cache = PageRenderCache()
        first = render_page(sample_doc, 0, 1.0, cache)
        second = render_page(sample_doc, 0, 1.0, cache)
        # Identidad: el segundo render NO rasterizó, devolvió el tuple cacheado.
        assert second is first
        cache.clear()

    def test_cache_hit_is_far_cheaper_than_miss(self, sample_doc):
        cache = PageRenderCache()

        miss = _best_time(lambda: render_page(sample_doc, 0, 1.0, cache), repeats=1)
        # Tras el primer render la entrada está cacheada → todas son hits.
        hit = _best_time(lambda: render_page(sample_doc, 0, 1.0, cache), repeats=8)

        # Un hit es un lookup de dict (~µs) vs rasterizar+encode+IO (≥ cientos de
        # µs). El margen 0.5× es enorme respecto al ratio real (>1000×).
        assert hit < miss * 0.5, f"hit={hit:.6f}s no es mucho menor que miss={miss:.6f}s"
        cache.clear()

    def test_rerendering_visible_window_is_cheap_on_second_pass(self, multi_page_pdf):
        """Re-renderizar la ventana visible (scroll de ida y vuelta) debe salir
        de cache: el segundo barrido es mucho más barato que el primero."""
        doc = fitz.open(str(multi_page_pdf))
        cache = PageRenderCache()
        try:
            first_pass = _best_time(
                lambda: [render_page(doc, pn, 1.0, cache) for pn in range(len(doc))],
                repeats=1,
            )
            second_pass = _best_time(
                lambda: [render_page(doc, pn, 1.0, cache) for pn in range(len(doc))],
                repeats=3,
            )
            assert second_pass < first_pass * 0.5
        finally:
            cache.clear()
            doc.close()


# ── render cache: memoria acotada bajo carga ───────────────────────────────────


class TestRenderCacheMemoryBounds:
    def test_byte_budget_bounds_memory_under_heavy_load(self):
        """Cientos de páginas grandes cacheadas → la RAM nunca supera _MAX_BYTES."""
        cache = PageRenderCache()
        cache._MAX_BYTES = 4 * 1024
        cache._MAX_ENTRIES = 10_000  # holgado: que mande el presupuesto de bytes
        for i in range(1000):
            cache.put(i, 1.0, (None, 50, 50, b"x" * 256))
        assert cache._bytes_used <= cache._MAX_BYTES
        # Y la contabilidad coincide con lo realmente almacenado.
        real = sum(len(v[3]) for v in cache._d.values() if v[3] is not None)
        assert cache._bytes_used == real

    def test_entry_count_bounds_memory_under_heavy_load(self):
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 25
        for i in range(1000):
            cache.put(i, 1.0, (None, 10, 10, b"x"))
        assert len(cache._d) <= 25

    def test_evicted_temp_files_are_removed_under_load(self, tmp_path):
        """La eviction por carga borra los archivos en disco (no se acumulan)."""
        cache = PageRenderCache()
        cache._MAX_ENTRIES = 5
        paths = []
        for i in range(50):
            p = tmp_path / f"p{i}.jpg"
            p.write_bytes(b"x" * 16)
            paths.append(p)
            cache.put(i, 1.5, (str(p), 10, 10, None))
        # Sólo ~5 entradas vivas → el resto de archivos fueron os.remove'd.
        survivors = [p for p in paths if p.exists()]
        assert len(survivors) <= 5


# ── cachés de texto: acotadas sin importar cuántas páginas se recorran ──────────


class TestTextCacheBoundedScrolling:
    def test_caches_stay_bounded_scrolling_whole_large_doc(self):
        """Propiedad clave: recorrer 1000 páginas con el cursor mantiene las
        cachés de texto en O(ventana), no en O(páginas visitadas)."""
        total = 1000
        stub = _make_stub(total)
        window = _text_window()
        max_seen = 0

        for current in range(total):
            # Simula _get_page_words / _point_has_text poblando la página actual.
            for cache in _all_text_caches(stub):
                cache[current] = ["data"]
            _RenderMixin._prune_text_caches(stub, current)
            max_seen = max(max_seen, len(stub._page_words))

        assert max_seen <= window, f"pico {max_seen} excedió la ventana {window}"
        for cache in _all_text_caches(stub):
            assert len(cache) <= window

    def test_prune_is_fast_on_very_large_cache(self):
        """La poda es lineal: vaciar ~100k×4 entradas debe ser casi instantáneo."""
        total = 100_000
        stub = _make_stub(total)
        for cache in _all_text_caches(stub):
            cache.update({pn: ["d"] for pn in range(total)})

        dt = _best_time(
            lambda: _RenderMixin._prune_text_caches(stub, total // 2), repeats=1
        )
        assert dt < 2.0, f"poda tardó {dt:.3f}s (esperado << 2s)"
        # Tras podar, sólo queda la ventana.
        assert len(stub._page_words) <= _text_window()

    def test_pruning_does_not_grow_caches(self):
        """Idempotencia de memoria: re-podar no agranda ni reintroduce páginas."""
        stub = _make_stub(500)
        for cache in _all_text_caches(stub):
            cache.update({pn: ["d"] for pn in range(500)})
        _RenderMixin._prune_text_caches(stub, 250)
        size_after_first = len(stub._page_words)
        _RenderMixin._prune_text_caches(stub, 250)
        assert len(stub._page_words) == size_after_first
