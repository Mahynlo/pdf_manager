"""Tests para la virtualización del árbol de controles del visor.

El visor ya no instancia ~50 controles Flet por página al abrir el PDF: cada
página arranca como un placeholder liviano y su slot pesado se construye
perezosamente (_build_page_slot) al entrar en la ventana visible, y se "desinfla"
de vuelta (_teardown_page_slot) al alejarse. Esto es lo que evita el freeze y el
pico de RAM al abrir documentos de cientos de páginas.

Estos tests fijan las propiedades clave de ese mecanismo sin levantar la GUI:
construir e inflar es reversible, la cuenta de slots construidos queda acotada a
una ventana, y nunca se desinfla una página con estado interactivo vivo.
"""
from __future__ import annotations

import threading
import types

import fitz
import flet as ft
import pytest

from pdf_viewer._render_mixin import _RenderMixin
from pdf_viewer._text_sel_mixin import _TextSelMixin
from pdf_viewer._ocr_mixin import _OCRMixin
from pdf_viewer._viewer_defs import _PAGE_GAP, _SLOT_TEARDOWN_MARGIN


# ── helpers ─────────────────────────────────────────────────────────────────


class _Viewer(_RenderMixin, _TextSelMixin, _OCRMixin):
    """Instancia mínima de _RenderMixin para probar build/teardown.

    Cualquier atributo no fijado explícitamente (los callbacks de los botones que
    los controles referencian al crearse, p. ej. self._on_tap_down) se resuelve a
    un no-op: nos interesa la construcción del árbol, no el cableado de eventos.
    Las listas/estado que sí toca la lógica se fijan de verdad, así que un acceso
    a una lista olvidada fallaría en vez de quedar enmascarado.
    """

    def __getattr__(self, name):  # sólo se llama para atributos NO fijados
        return lambda *a, **k: None


_PAGE_LISTS = (
    "_page_images", "_drag_overlays", "_sel_overlays", "_sel_handles",
    "_ocr_overlays", "_text_sel_layers", "_redact_overlays", "_loading_overlays",
    "_ink_canvases", "_text_sel_popups", "_annot_popups", "_page_slots",
    "_page_gestures",
)


def _make_viewer(total: int, page_h: float = 842.0) -> _Viewer:
    """Visor con `total` páginas en estado 'recién reconstruido': todas las
    listas pesadas en None, placeholders + rows + geometría poblados."""
    doc = fitz.open()
    for _ in range(total):
        doc.new_page(width=595, height=page_h)

    v = _Viewer.__new__(_Viewer)
    v.doc = doc
    v._doc_lock = threading.Lock()
    v.zoom = 1.0
    v._night_mode = False
    v._current_cursor = ft.MouseCursor.BASIC
    v._annot = types.SimpleNamespace(overlay_color="#330055FF")

    # Estado de render / interacción.
    v._rendered = set()
    v._previewed = set()
    v._rendering = set()
    v._rendering_preview = set()
    v._pending_rerender = set()
    v._render_tokens = {}
    v._render_gen = 0
    v.current_page = 0
    v._selected = None
    v._annot_popup_pn = None
    v._ink_page = None
    v._text_sel_start_pn = None
    v._text_sel_end_pn = None
    v._ocr_show_boxes = False
    v._redact_preview = False
    v._ocr_by_page = {}
    v._redact_matches = []

    # Listas pesadas en None (sin construir) + placeholders/rows/geometría.
    for name in _PAGE_LISTS:
        setattr(v, name, [None] * total)
    v._page_placeholders = [None] * total
    v._page_rows = []
    v._page_cum_offsets = []
    v._page_heights = []
    cum = 0.0
    for pn in range(total):
        ph = v._make_placeholder(pn, 595, int(page_h))
        v._page_placeholders[pn] = ph
        v._page_rows.append(ft.Row([ph]))
        v._page_cum_offsets.append(cum)
        v._page_heights.append(page_h)
        cum += page_h + _PAGE_GAP
    return v


# ── build / teardown round-trip ──────────────────────────────────────────────


class TestLazyBuildTeardown:
    def test_pages_start_unbuilt(self):
        v = _make_viewer(5)
        assert all(not v._is_built(pn) for pn in range(5))
        # El Row sólo contiene el placeholder liviano.
        for row in v._page_rows:
            assert len(row.controls) == 1

    def test_ensure_build_materializes_heavy_tree(self):
        v = _make_viewer(5)
        v._ensure_page_built(2)
        assert v._is_built(2)
        # Todas las listas pesadas quedaron pobladas para esa página.
        assert isinstance(v._page_images[2], ft.Image)
        assert isinstance(v._page_slots[2], ft.Container)
        assert isinstance(v._page_gestures[2], ft.GestureDetector)
        assert isinstance(v._sel_handles[2], dict)
        # El Row ahora monta el GestureDetector (no el placeholder).
        assert v._page_rows[2].controls == [v._page_gestures[2]]
        # Las vecinas siguen sin construir.
        assert not v._is_built(1) and not v._is_built(3)

    def test_build_is_idempotent(self):
        v = _make_viewer(3)
        v._ensure_page_built(1)
        img = v._page_images[1]
        v._ensure_page_built(1)
        assert v._page_images[1] is img  # no se reconstruyó

    def test_teardown_reverts_to_placeholder(self):
        v = _make_viewer(5)
        v.current_page = 0
        v._ensure_page_built(3)
        assert v._is_built(3)

        v._teardown_page_slot(3)

        assert not v._is_built(3)
        for name in _PAGE_LISTS:
            assert getattr(v, name)[3] is None
        # El Row vuelve a mostrar un único placeholder liviano.
        assert len(v._page_rows[3].controls) == 1
        assert v._page_rows[3].controls[0] is v._page_placeholders[3]

    def test_render_bookkeeping_cleared_on_teardown(self):
        v = _make_viewer(4)
        v.current_page = 0
        v._ensure_page_built(2)
        v._rendered.add(2)
        v._previewed.add(2)
        v._teardown_page_slot(2)
        assert 2 not in v._rendered
        assert 2 not in v._previewed


# ── protección de páginas activas ────────────────────────────────────────────


class TestTeardownProtectsActivePages:
    def test_current_page_is_active(self):
        v = _make_viewer(3)
        v.current_page = 1
        assert v._page_is_active(1)
        assert not v._page_is_active(0)

    def test_selected_annotation_page_is_active(self):
        v = _make_viewer(3)
        v.current_page = 0
        v._selected = (2, 999)
        assert v._page_is_active(2)

    def test_text_selection_range_is_active(self):
        v = _make_viewer(6)
        v.current_page = 0
        v._text_sel_start_pn = 4
        v._text_sel_end_pn = 2
        for pn in (2, 3, 4):
            assert v._page_is_active(pn)
        assert not v._page_is_active(1)
        assert not v._page_is_active(5)

    def test_teardown_skips_active_page(self):
        v = _make_viewer(3)
        v.current_page = 1
        v._ensure_page_built(1)
        v._teardown_page_slot(1)  # activa → no-op
        assert v._is_built(1)


# ── ventana acotada al recorrer un documento grande ──────────────────────────


class TestBuiltWindowBounded:
    def test_distant_built_slots_are_torn_down(self):
        page_h = 800.0
        v = _make_viewer(40, page_h=page_h)
        # Construye una franja de páginas (como si se hubieran recorrido).
        for pn in range(40):
            v._ensure_page_built(pn)
        assert sum(v._is_built(pn) for pn in range(40)) == 40

        viewport_h = 900.0
        # Viewport centrado en la página 20.
        pixels = v._page_cum_offsets[20]
        v.current_page = 20

        v._teardown_built_distant(pixels, viewport_h)

        built = {pn for pn in range(40) if v._is_built(pn)}
        # Las páginas lejanas (p. ej. 0 y 39) se desinflaron…
        assert 0 not in built
        assert 39 not in built
        # …y la cuenta de slots vivos quedó acotada por la ventana de teardown
        # (mucho menor que el total), no en O(páginas recorridas).
        span_px = viewport_h * (1.0 + 2 * _SLOT_TEARDOWN_MARGIN)
        max_pages = int(span_px / page_h) + 3
        assert len(built) <= max_pages
        # La página actual sobrevive siempre.
        assert 20 in built


# ── regresión: rutas de la GUI tocan slots no construidos (None) ─────────────
#
# Estos reproducen los AttributeError vistos en runtime: barridos sobre listas
# por página que incluían slots None tras virtualizar (selección de texto multi-
# página y refresco del panel OCR cuando current_page aún no se materializó).


class TestUnbuiltSlotsToleratedByGuiPaths:
    def test_update_text_selection_skips_unbuilt_layers(self):
        # 5 páginas, selección en [1,2]; las páginas 0/3/4 quedan como placeholder
        # (capa None). El barrido que limpia las capas FUERA del rango no debe
        # romperse al toparse con los None.
        v = _make_viewer(5)
        v._page_words = {}
        v._text_sel_sel_rect = None
        v._text_sel_handle_start_disp = None
        v._text_sel_handle_end_disp = None
        v._get_page_words = lambda i: []  # sin texto → el barrido interno es no-op
        v._ensure_page_built(1)
        v._ensure_page_built(2)

        # No debe lanzar AttributeError por las capas None de 0/3/4.
        result = v._update_text_selection(1, (0.0, 0.0), 2, (10.0, 10.0))
        assert result == ""

    def test_refresh_ocr_ui_tolerates_unbuilt_current_page(self):
        # Durante el scroll, current_page se reasigna a una página que todavía es
        # un placeholder (overlay None) antes de renderizarse.
        v = _make_viewer(3)
        v.current_page = 1  # sin construir
        v._ocr_by_page = {}
        v._ocr_set_idle = lambda *a, **k: None
        v._ocr_results_list = ft.ListView()

        # No debe lanzar AttributeError por self._ocr_overlays[1] == None.
        v._refresh_ocr_ui_for_page()
        assert not v._is_built(1)
