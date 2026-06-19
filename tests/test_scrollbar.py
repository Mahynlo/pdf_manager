"""Regresión de las barras de scroll del visor (horizontal nativa + vertical custom).

Fija el comportamiento añadido para que:

  · El scroll horizontal sea EXTERIOR → su barra nativa queda anclada al fondo
    del viewport (no al final del documento).
  · La barra vertical NATIVA se use cuando la página cabe, y se reemplace por la
    barra vertical PERSONALIZADA (``_vbar``) cuando el zoom hace que la página
    desborde horizontalmente (la nativa quedaría fuera de pantalla). Nunca se
    muestran ambas a la vez.
  · El thumb personalizado mida proporcionalmente, se arrastre desplazando el
    documento, no tiemble por la realimentación del propio ``scroll_to``, se
    auto-oculte tras inactividad y cambie de color en hover / arrastre.

Construye el ``PDFViewerTab`` real contra una ``Page`` simulada (sin GUI) para
ejercitar el ``_build`` verdadero — es donde viven los controles de las barras.
"""
from __future__ import annotations

import types

import fitz
import flet as ft
import pytest

from pdf_viewer.viewer import PDFViewerTab


# ── doubles mínimos de Flet Page ────────────────────────────────────────────────
class _FakeWindow:
    width = 1400
    height = 900


class _FakePage:
    def __init__(self) -> None:
        self.overlay: list = []
        self.window = _FakeWindow()
        self.on_resized = None

    def update(self, *a, **k) -> None:
        pass

    def run_thread(self, fn, *a, **k) -> None:
        try:
            fn(*a, **k)
        except Exception:
            pass


class _ScrollEvent:
    """Imita ft.OnScrollEvent (pixels / viewport_dimension / max_scroll_extent)."""

    def __init__(self, pixels: float, viewport: float, max_extent: float) -> None:
        self.pixels = pixels
        self.viewport_dimension = viewport
        self.max_scroll_extent = max_extent


def _make_pdf(tmp_path, n: int = 6, w: int = 595, h: int = 842) -> str:
    path = tmp_path / "scroll.pdf"
    doc = fitz.open()
    for _ in range(n):
        doc.new_page(width=w, height=h)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def viewer(tmp_path):
    v = PDFViewerTab(
        path=_make_pdf(tmp_path, n=6),
        page_ref=_FakePage(),
        on_close=lambda *a: None,
    )
    # Viewport predecible: sin sidebar y en modo continuo.
    v._sidebar_visible = False
    v._right_sidebar = None
    v._display_mode = "continuous"
    v._update_scroll_column_width()
    yield v
    try:
        v.close()
    except Exception:
        pass


def _zoom_to_overflow(v) -> None:
    """Sube el zoom hasta que la página desborde el viewport horizontalmente."""
    v.zoom = 3.0
    v._rebuild_scroll_content(scroll_back=False)


# ── alternado nativa / personalizada ────────────────────────────────────────────
def test_fits_uses_native_vbar(viewer):
    v = viewer
    assert v._page_overflows_h is False
    assert v.viewer_scroll.scroll == ft.ScrollMode.AUTO      # vertical nativa visible
    assert v.viewer_hscroll.scroll == ft.ScrollMode.HIDDEN   # sin scroll horizontal
    assert v._vbar.visible is False                           # personalizada oculta


def test_overflow_uses_custom_vbar(viewer):
    v = viewer
    _zoom_to_overflow(v)
    assert v._page_overflows_h is True
    assert v.viewer_scroll.scroll == ft.ScrollMode.HIDDEN    # nativa oculta (iría fuera)
    assert v.viewer_hscroll.scroll == ft.ScrollMode.AUTO     # scroll horizontal nativo
    assert v._vbar.visible is True                            # personalizada activa


def test_toggle_back_to_native(viewer):
    v = viewer
    _zoom_to_overflow(v)
    assert v._vbar.visible is True
    v.zoom = 1.0
    v._rebuild_scroll_content(scroll_back=False)
    assert v._page_overflows_h is False
    assert v.viewer_scroll.scroll == ft.ScrollMode.AUTO
    assert v._vbar.visible is False


def test_no_two_bars_at_once(viewer):
    """Nunca debe verse la nativa vertical y la personalizada simultáneamente."""
    v = viewer
    # cabe → nativa sí, custom no
    assert (v.viewer_scroll.scroll == ft.ScrollMode.AUTO) and not v._vbar.visible
    _zoom_to_overflow(v)
    # desborda → nativa no, custom sí
    assert (v.viewer_scroll.scroll == ft.ScrollMode.HIDDEN) and v._vbar.visible


# ── geometría / arrastre del thumb ──────────────────────────────────────────────
def test_thumb_proportional(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._update_vbar_from_event(_ScrollEvent(0.0, 700.0, 3000.0))
    assert v._vbar.visible
    assert v._vbar_thumb.height <= v._vbar.height   # el thumb no excede la pista
    assert v._vbar_thumb.height >= 40.0             # piso de agarre
    assert v._vbar_travel > 0


def test_drag_scrolls_to_bottom(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._update_vbar_from_event(_ScrollEvent(0.0, 700.0, 3000.0))
    top0 = v._vbar_thumb_top
    v._on_vbar_drag_start(None)
    v._on_vbar_drag(types.SimpleNamespace(delta_y=v._vbar_travel))  # arrastrar al fondo
    v._on_vbar_drag_end(None)
    assert v._vbar_thumb_top > top0
    assert abs(v._scroll_px - v._vbar_max_extent) < 1.0            # llegó al final


def test_drag_clamps_at_top(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._update_vbar_from_event(_ScrollEvent(500.0, 700.0, 3000.0))
    v._on_vbar_drag_start(None)
    v._on_vbar_drag(types.SimpleNamespace(delta_y=-99999.0))       # arrastrar muy arriba
    v._on_vbar_drag_end(None)
    assert v._vbar_thumb_top == 0.0
    assert v._scroll_px == 0.0


def test_drag_feedback_guard(viewer):
    """Un evento de scroll mientras se arrastra NO debe reposicionar el thumb."""
    v = viewer
    _zoom_to_overflow(v)
    v._update_vbar_from_event(_ScrollEvent(0.0, 700.0, 3000.0))
    v._on_vbar_drag_start(None)
    v._on_vbar_drag(types.SimpleNamespace(delta_y=40.0))
    held = v._vbar_thumb_top
    v._update_vbar_from_event(_ScrollEvent(2999.0, 700.0, 3000.0))  # realimentación
    assert v._vbar_thumb_top == held
    v._on_vbar_drag_end(None)


def test_scroll_syncs_thumb(viewer):
    """Fuera de arrastre, el scroll real reposiciona el thumb."""
    v = viewer
    _zoom_to_overflow(v)
    v._update_vbar_from_event(_ScrollEvent(0.0, 700.0, 3000.0))
    v._update_vbar_from_event(_ScrollEvent(1500.0, 700.0, 3000.0))  # mitad
    assert v._vbar_thumb_top == pytest.approx(0.5 * v._vbar_travel, abs=1.0)


# ── auto-ocultado ────────────────────────────────────────────────────────────────
def test_autohide(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._show_vbar()
    assert v._vbar.opacity == 1.0
    v._hide_vbar()
    assert v._vbar.opacity == 0.0


def test_hover_keeps_visible(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._on_vbar_enter(None)
    assert v._vbar.opacity == 1.0
    v._hide_vbar()                       # no debe ocultar mientras hay hover
    assert v._vbar.opacity == 1.0
    v._on_vbar_exit(None)


def test_drag_keeps_visible(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._on_vbar_drag_start(None)
    v._hide_vbar()                       # no debe ocultar mientras se arrastra
    assert v._vbar.opacity == 1.0
    v._on_vbar_drag_end(None)


# ── color de estado (reposo / hover-arrastre) ───────────────────────────────────
def test_active_color_states(viewer):
    v = viewer
    _zoom_to_overflow(v)
    assert v._vbar_thumb.bgcolor == v._VBAR_THUMB_IDLE
    v._on_vbar_enter(None)
    assert v._vbar_thumb.bgcolor == v._VBAR_THUMB_ACTIVE
    v._on_vbar_exit(None)
    assert v._vbar_thumb.bgcolor == v._VBAR_THUMB_IDLE


def test_active_persists_when_hover_exits_mid_drag(viewer):
    v = viewer
    _zoom_to_overflow(v)
    v._on_vbar_drag_start(None)
    assert v._vbar_thumb.bgcolor == v._VBAR_THUMB_ACTIVE
    v._on_vbar_exit(None)                # sale el hover pero sigue arrastrando
    assert v._vbar_thumb.bgcolor == v._VBAR_THUMB_ACTIVE
    v._on_vbar_drag_end(None)
    assert v._vbar_thumb.bgcolor == v._VBAR_THUMB_IDLE


# ── helper de alto de contenido ─────────────────────────────────────────────────
def test_content_height(viewer):
    v = viewer
    expected = v._page_cum_offsets[-1] + v._page_heights[-1]
    assert v._content_height() == pytest.approx(expected)
