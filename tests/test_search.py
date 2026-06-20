"""Tests para la funcionalidad de búsqueda de texto en el visor.

Cubre:
  - _search_worker(): búsqueda en hilo de fondo, resultados correctos,
    cancelación por token (_search_gen).
  - _search_next() / _search_prev(): navegación circular entre coincidencias.
  - _render_search_overlay(): construcción de cajas visuales.
  - _clear_search(): limpieza de estado.
  - _send_to_redact(): interoperabilidad — transferencia del término a censura.
"""
from __future__ import annotations

import threading
import types
from unittest.mock import MagicMock, patch

import fitz
import pytest

from pdf_viewer._search_mixin import _SearchMixin
from pdf_viewer._render_mixin import _RenderMixin


# ── stub mínimo ──────────────────────────────────────────────────────────────


class _Viewer(_SearchMixin):
    """Stub que mezcla _SearchMixin con el estado mínimo necesario."""

    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_doc_with_text(text: str = "hola mundo prueba") -> fitz.Document:
    """Crea un PDF en memoria de una sola página con texto indexable."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    return doc


def _make_viewer(doc: fitz.Document | None = None) -> _Viewer:
    """Stub con el estado mínimo para los métodos bajo prueba."""
    v = _Viewer.__new__(_Viewer)
    v.doc = doc or _make_doc_with_text()
    v._doc_lock = threading.Lock()
    v.zoom = 1.0

    # Estado de búsqueda
    v._search_query           = ""
    v._search_results         = {}
    v._search_matches_flat    = []
    v._search_match_idx       = -1
    v._search_gen             = 0
    v._search_case_sensitive  = False
    v._search_overlays        = []
    v._page_cum_offsets       = [0.0]
    v._page_heights           = [800.0]
    v._last_viewport_h        = 600.0

    # UI refs como objetos simples
    v._search_field        = types.SimpleNamespace(value="", focus=lambda: None)
    v._search_count_label  = types.SimpleNamespace(value="", update=lambda: None)
    v._search_results_list = types.SimpleNamespace(controls=[], update=lambda: None)
    v._search_case_btn     = types.SimpleNamespace(
        icon_color="onSurfaceVariant",
        icon="search",
        update=lambda: None,
    )
    v._search_toolbar_btn  = None

    # Redacción (para _send_to_redact)
    v._redact_query_field = types.SimpleNamespace(value="")
    v._sidebar_calls: list[str] = []
    v._switch_sidebar_mode = lambda m: v._sidebar_calls.append(m)
    v._add_redact_term_calls: list = []
    v._add_redact_term = lambda: v._add_redact_term_calls.append(True)

    # Scroll / slot mocks
    v.viewer_scroll = types.SimpleNamespace(scroll_to=lambda **kw: None)
    v._ensure_page_built = lambda pn: None

    # page_ref
    v.page_ref = types.SimpleNamespace(update=lambda: None)

    # Snacks
    v._snack_msgs: list[str] = []
    v._show_snack = lambda msg: v._snack_msgs.append(msg)

    return v


# ── búsqueda: resultados ─────────────────────────────────────────────────────


class TestSearchResults:
    def test_finds_existing_word(self):
        doc = _make_doc_with_text("hola mundo prueba")
        v = _make_viewer(doc)

        v._search_field.value = "hola"
        v._on_search_submit()
        # Esperar a que el worker termine (daemon thread)
        import time; time.sleep(0.3)

        assert 0 in v._search_results
        assert len(v._search_results[0]) >= 1

    def test_no_results_for_missing_word(self):
        doc = _make_doc_with_text("hola mundo")
        v = _make_viewer(doc)

        v._search_field.value = "zzz_no_existe"
        v._on_search_submit()
        import time; time.sleep(0.3)

        assert len(v._search_results) == 0
        assert len(v._search_matches_flat) == 0

    def test_case_insensitive_by_default(self):
        doc = _make_doc_with_text("Hola MUNDO")
        v = _make_viewer(doc)

        v._search_field.value = "hola"
        v._search_case_sensitive = False
        v._on_search_submit()
        import time; time.sleep(0.3)

        assert 0 in v._search_results

    def test_case_sensitive_misses_wrong_case(self):
        doc = _make_doc_with_text("Hola MUNDO")
        v = _make_viewer(doc)

        v._search_field.value = "hola"
        v._search_case_sensitive = True
        v._on_search_submit()
        import time; time.sleep(0.3)

        # "hola" en minúsculas no debe encontrarse si "Hola" está en mayúsculas
        assert len(v._search_results) == 0

    def test_flat_list_length_equals_total_matches(self):
        # Dos palabras iguales en el texto
        doc = _make_doc_with_text("hola hola hola")
        v = _make_viewer(doc)

        v._search_field.value = "hola"
        v._on_search_submit()
        import time; time.sleep(0.3)

        total = sum(len(qs) for qs in v._search_results.values())
        assert len(v._search_matches_flat) == total

    def test_multipage_results(self):
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 100), f"palabra pagina{i}", fontsize=12)

        v = _make_viewer(doc)
        v._page_cum_offsets = [0.0, 820.0, 1640.0]
        v._page_heights = [800.0, 800.0, 800.0]

        v._search_field.value = "palabra"
        v._on_search_submit()
        import time; time.sleep(0.4)

        assert len(v._search_results) == 3


# ── navegación ───────────────────────────────────────────────────────────────


class TestSearchNavigation:
    def _viewer_with_matches(self) -> _Viewer:
        doc = _make_doc_with_text("hola hola hola")
        v = _make_viewer(doc)
        v._search_field.value = "hola"
        v._on_search_submit()
        import time; time.sleep(0.3)
        return v

    def test_next_advances_index(self):
        v = self._viewer_with_matches()
        if not v._search_matches_flat:
            pytest.skip("El texto no produjo coincidencias en este entorno")

        v._search_match_idx = 0
        total = len(v._search_matches_flat)
        v._search_next()
        assert v._search_match_idx == 1 % total

    def test_next_wraps_from_last_to_first(self):
        v = self._viewer_with_matches()
        if not v._search_matches_flat:
            pytest.skip("El texto no produjo coincidencias en este entorno")

        v._search_match_idx = len(v._search_matches_flat) - 1
        v._search_next()
        assert v._search_match_idx == 0

    def test_prev_wraps_from_first_to_last(self):
        v = self._viewer_with_matches()
        if not v._search_matches_flat:
            pytest.skip("El texto no produjo coincidencias en este entorno")

        v._search_match_idx = 0
        v._search_prev()
        assert v._search_match_idx == len(v._search_matches_flat) - 1

    def test_prev_decrements_index(self):
        v = self._viewer_with_matches()
        if not v._search_matches_flat or len(v._search_matches_flat) < 2:
            pytest.skip("Menos de 2 coincidencias")

        v._search_match_idx = 2 % len(v._search_matches_flat)
        v._search_prev()
        assert v._search_match_idx == 1

    def test_next_noop_without_results(self):
        v = _make_viewer()
        v._search_match_idx = -1
        v._search_next()  # debe no lanzar excepción
        assert v._search_match_idx == -1

    def test_prev_noop_without_results(self):
        v = _make_viewer()
        v._search_match_idx = -1
        v._search_prev()
        assert v._search_match_idx == -1


# ── cancelación ──────────────────────────────────────────────────────────────


class TestSearchCancel:
    def test_incrementing_gen_stops_worker(self):
        """Un worker con gen desactualizado debe abortar antes de escribir resultados."""
        doc = fitz.open()
        for _ in range(20):          # varias páginas para dar tiempo al abort
            page = doc.new_page()
            page.insert_text((72, 100), "termino buscado", fontsize=12)

        v = _make_viewer(doc)
        v._page_cum_offsets = [i * 820.0 for i in range(20)]
        v._page_heights     = [800.0] * 20

        # Arrancar con gen=5 pero incrementar inmediatamente → el worker con
        # gen=5 debe abortarse antes de completar todos los resultados.
        v._search_gen = 5
        v._search_field.value = "termino"
        gen = v._search_gen
        # Ejecutar directamente el worker en el hilo actual no es posible sin
        # bloquear el test; en cambio verificamos que el token funciona:
        # si lanzamos y luego incrementamos el gen, el resultado no se almacena.
        import threading
        done = threading.Event()
        original_results = {}

        def worker_wrapper():
            v._search_worker("termino", False, gen)
            done.set()

        t = threading.Thread(target=worker_wrapper, daemon=True)
        # Incrementar gen ANTES de que arranque el worker (simula nueva búsqueda)
        v._search_gen += 1
        t.start()
        done.wait(timeout=2.0)

        # El worker vio gen != _search_gen y abortó: resultados deben estar vacíos
        assert len(v._search_results) == 0

    def test_new_search_clears_previous_results(self):
        doc = _make_doc_with_text("hola mundo")
        v = _make_viewer(doc)

        v._search_field.value = "hola"
        v._on_search_submit()
        import time; time.sleep(0.3)

        # Segunda búsqueda con otro término
        v._search_field.value = "zzz_no_existe"
        v._on_search_submit()
        time.sleep(0.3)

        assert len(v._search_matches_flat) == 0


# ── overlays ─────────────────────────────────────────────────────────────────


class TestSearchOverlays:
    def test_render_overlay_noop_when_slot_not_built(self):
        """Si el slot no está construido (None), _render_search_overlay no lanza."""
        v = _make_viewer()
        v._search_overlays = [None]
        v._search_results  = {0: []}
        v._render_search_overlay(0)  # No debe lanzar

    def test_render_overlay_builds_boxes(self):
        """Con quads reales, se construyen containers dentro del Stack."""
        import flet as ft
        v = _make_viewer()
        stack = ft.Stack([], visible=False)
        v._search_overlays = [stack]

        # Quad sintético
        q = fitz.Quad(fitz.Point(10, 20), fitz.Point(60, 20),
                      fitz.Point(10, 35), fitz.Point(60, 35))
        v._search_results = {0: [q]}
        v._search_matches_flat = [(0, 0)]
        v._search_match_idx = 0

        v._render_search_overlay(0, [q])

        assert len(stack.controls) == 1
        box = stack.controls[0]
        assert isinstance(box, ft.Container)
        assert stack.visible is True

    def test_current_match_uses_orange(self):
        """La coincidencia activa debe usar el color naranja (#FF6F00)."""
        import flet as ft
        v = _make_viewer()
        stack = ft.Stack([], visible=False)
        v._search_overlays = [stack]

        q = fitz.Quad(fitz.Point(10, 20), fitz.Point(60, 20),
                      fitz.Point(10, 35), fitz.Point(60, 35))
        v._search_results = {0: [q]}
        v._search_matches_flat = [(0, 0)]
        v._search_match_idx = 0
        v._render_search_overlay(0, [q])

        assert "#FF6F00" in (stack.controls[0].bgcolor or "")

    def test_non_current_match_uses_yellow(self):
        """Una coincidencia no activa usa el amarillo (#FDD835)."""
        import flet as ft
        v = _make_viewer()
        stack = ft.Stack([], visible=False)
        v._search_overlays = [stack]

        q0 = fitz.Quad(fitz.Point(10, 20), fitz.Point(60, 20),
                       fitz.Point(10, 35), fitz.Point(60, 35))
        q1 = fitz.Quad(fitz.Point(10, 50), fitz.Point(60, 50),
                       fitz.Point(10, 65), fitz.Point(60, 65))
        v._search_results = {0: [q0, q1]}
        v._search_matches_flat = [(0, 0), (0, 1)]
        v._search_match_idx = 0  # activa es la 0
        v._render_search_overlay(0, [q0, q1])

        # La segunda caja (qi=1) no es la activa → amarillo
        assert "#FDD835" in (stack.controls[1].bgcolor or "")

    def test_clear_all_overlays(self):
        """_clear_all_search_overlays vacía los controles de todos los Stacks."""
        import flet as ft
        v = _make_viewer()
        stack0 = ft.Stack([ft.Container()], visible=True)
        stack1 = ft.Stack([ft.Container(), ft.Container()], visible=True)
        v._search_overlays = [stack0, stack1]

        v._clear_all_search_overlays()

        assert stack0.controls == []
        assert stack1.controls == []
        assert stack0.visible is False
        assert stack1.visible is False


# ── _clear_search ─────────────────────────────────────────────────────────────


class TestClearSearch:
    def test_clear_resets_all_state(self):
        v = _make_viewer()
        v._search_query = "algo"
        v._search_results = {0: []}
        v._search_matches_flat = [(0, 0)]
        v._search_match_idx = 0
        v._search_gen = 3

        v._clear_search()

        assert v._search_query == ""
        assert v._search_results == {}
        assert v._search_matches_flat == []
        assert v._search_match_idx == -1
        assert v._search_field.value == ""

    def test_clear_increments_gen_to_cancel_worker(self):
        v = _make_viewer()
        v._search_gen = 5
        v._clear_search()
        assert v._search_gen == 6


# ── interoperabilidad con censura ─────────────────────────────────────────────


class TestSendToRedact:
    def test_transfers_query_to_redact_field(self):
        v = _make_viewer()
        v._search_query = "término secreto"

        v._send_to_redact()

        assert v._redact_query_field.value == "término secreto"

    def test_switches_to_redact_mode(self):
        v = _make_viewer()
        v._search_query = "algo"

        v._send_to_redact()

        assert "redact" in v._sidebar_calls

    def test_calls_add_redact_term(self):
        v = _make_viewer()
        v._search_query = "algo"

        v._send_to_redact()

        assert len(v._add_redact_term_calls) == 1

    def test_noop_when_query_empty(self):
        v = _make_viewer()
        v._search_query = ""

        v._send_to_redact()

        assert v._sidebar_calls == []
        assert v._add_redact_term_calls == []
