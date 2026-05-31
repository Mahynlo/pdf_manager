"""Tests for the per-page text-cache pruning in `_RenderMixin`.

Las cachés de texto (``_page_words`` char-level rawdict, ``_page_word_bands``,
``_page_blocks_cache``, ``_text_rects_cache``) son por página y, sin poda,
crecían sin techo al recorrer el documento con el cursor — sobrevivían incluso a
``_do_suspend``. ``_prune_text_caches`` las acota a una ventana alrededor de la
página actual; estos tests fijan ese comportamiento.

El método sólo depende de ``self.doc`` (para ``len``), los punteros de selección
y los cuatro dicts, así que se ejercita sobre un stub liviano en vez de construir
toda la UI Flet de ``PDFViewerTab``.
"""
from __future__ import annotations

from pdf_viewer._render_mixin import _RenderMixin
from pdf_viewer._viewer_defs import _TEXT_CACHE_KEEP_PAGES


class _FakeDoc:
    """Minimal stand-in: only ``len(doc)`` is used by _prune_text_caches."""

    def __init__(self, n: int) -> None:
        self._n = n

    def __len__(self) -> int:
        return self._n


class _Stub:
    """Holds just the attributes _prune_text_caches touches."""

    def __init__(self, total: int) -> None:
        self.doc = _FakeDoc(total)
        self._text_sel_start_pn = None
        self._text_sel_end_pn = None
        # Una entrada por página en cada caché.
        self._page_words = {pn: ["w"] for pn in range(total)}
        self._page_word_bands = {pn: {0: []} for pn in range(total)}
        self._page_blocks_cache = {pn: ["b"] for pn in range(total)}
        self._text_rects_cache = {pn: ["r"] for pn in range(total)}

    # Bind the real method under test.
    _prune_text_caches = _RenderMixin._prune_text_caches

    @property
    def _all_caches(self):
        return (
            self._page_words,
            self._page_word_bands,
            self._page_blocks_cache,
            self._text_rects_cache,
        )


def _radius() -> int:
    return max(0, (_TEXT_CACHE_KEEP_PAGES - 1) // 2)


class TestPruneTextCaches:
    def test_keeps_only_window_around_center(self):
        total = 100
        center = 50
        stub = _Stub(total)
        stub._prune_text_caches(center)

        radius = _radius()
        expected = set(range(center - radius, center + radius + 1))
        for cache in stub._all_caches:
            assert set(cache) == expected

    def test_prunes_far_pages(self):
        stub = _Stub(100)
        stub._prune_text_caches(50)
        # Una página lejana queda fuera de la ventana → eviccionada.
        for cache in stub._all_caches:
            assert 0 not in cache
            assert 99 not in cache

    def test_window_clamped_at_document_start(self):
        stub = _Stub(100)
        stub._prune_text_caches(0)
        radius = _radius()
        expected = set(range(0, radius + 1))  # sin índices negativos
        for cache in stub._all_caches:
            assert set(cache) == expected

    def test_window_clamped_at_document_end(self):
        total = 100
        stub = _Stub(total)
        stub._prune_text_caches(total - 1)
        radius = _radius()
        expected = set(range(total - 1 - radius, total))
        for cache in stub._all_caches:
            assert set(cache) == expected

    def test_active_selection_pages_are_preserved(self):
        """Páginas dentro de una selección de texto activa no se podan aunque
        estén lejos de la página actual (evita re-extraer bajo _doc_lock)."""
        stub = _Stub(100)
        stub._text_sel_start_pn = 3
        stub._text_sel_end_pn = 7
        stub._prune_text_caches(50)
        for cache in stub._all_caches:
            for pn in range(3, 8):
                assert pn in cache, f"página de selección {pn} fue podada"

    def test_selection_span_handles_reversed_endpoints(self):
        """start_pn > end_pn (selección hacia atrás) debe preservar el rango."""
        stub = _Stub(100)
        stub._text_sel_start_pn = 7
        stub._text_sel_end_pn = 3
        stub._prune_text_caches(50)
        for cache in stub._all_caches:
            for pn in range(3, 8):
                assert pn in cache

    def test_small_document_keeps_everything(self):
        total = 4  # menor que la ventana → nada se poda
        stub = _Stub(total)
        stub._prune_text_caches(0)
        for cache in stub._all_caches:
            assert set(cache) == set(range(total))

    def test_empty_caches_are_safe(self):
        stub = _Stub(0)
        stub._page_words = {}
        stub._page_word_bands = {}
        stub._page_blocks_cache = {}
        stub._text_rects_cache = {}
        # No debe lanzar con dicts vacíos / doc sin páginas.
        stub._prune_text_caches(0)
        for cache in stub._all_caches:
            assert cache == {}
