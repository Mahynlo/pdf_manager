"""Tests for `pdf_viewer.annotations` — annotation manager and pure helpers.

Critical behaviors:
  · Drag lifecycle: begin → move → commit (RECT path)
  · History tracking + undo_last semantics
  · delete_annot keeps history coherent (no orphan xrefs)
  · get_annot_at hit-testing prefers shapes over markup
  · _rdp_simplify and _catmull_rom polyline helpers (pure math)
"""
from __future__ import annotations

import math

import fitz
import pytest

from pdf_viewer.annotations import (
    AnnotationManager,
    Tool,
    _atype,
    _catmull_rom,
    _find_annot_by_xref,
    _rdp_simplify,
)


# ─────────────────────────────────────────────────────────────── AnnotationManager


@pytest.fixture
def mgr() -> AnnotationManager:
    return AnnotationManager(on_modified=lambda *_a, **_kw: None)


class TestDragLifecycle:
    def test_initial_state(self, mgr):
        assert mgr.tool is Tool.CURSOR
        assert mgr._start is None
        assert mgr._last_rect is None
        assert mgr._history == []

    def test_set_tool(self, mgr):
        mgr.set_tool(Tool.RECT)
        assert mgr.tool is Tool.RECT

    def test_begin_records_start(self, mgr):
        mgr.begin(10.0, 20.0)
        assert mgr._start == (10.0, 20.0)
        assert mgr._raw_start == (10.0, 20.0)

    def test_move_without_begin_returns_none(self, mgr):
        assert mgr.move(50.0, 50.0) is None

    def test_move_returns_normalized_rect(self, mgr):
        """move() returns a Rect with x0 ≤ x1 and y0 ≤ y1 regardless of drag direction."""
        mgr.begin(100.0, 200.0)
        # Drag up-and-left → rect must still have ordered corners
        rect = mgr.move(50.0, 150.0)
        assert rect is not None
        assert rect.x0 == 50.0 and rect.x1 == 100.0
        assert rect.y0 == 150.0 and rect.y1 == 200.0

    def test_commit_without_drag_returns_false(self, mgr, sample_doc):
        modified, text = mgr.commit(sample_doc, 0)
        assert modified is False
        assert text is None

    def test_commit_too_small_rect_is_discarded(self, mgr, sample_doc):
        """A drag covering less than 3×3 pt should not create an annotation."""
        mgr.set_tool(Tool.RECT)
        mgr.begin(100.0, 100.0)
        mgr.move(101.0, 101.0)   # 1×1 rect — below the 3pt threshold
        modified, _ = mgr.commit(sample_doc, 0)
        assert modified is False
        assert mgr._history == []


class TestRectAnnotation:
    def test_commit_rect_creates_annotation(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(100.0, 100.0)
        mgr.move(200.0, 200.0)
        modified, text = mgr.commit(sample_doc, 0)
        assert modified is True
        assert text is None

        # Annotation now exists on page 0. Hold the page reference alive
        # so the annot proxy doesn't get invalidated by PyMuPDF.
        page = sample_doc[0]
        annots = list(page.annots())
        assert len(annots) == 1
        assert _atype(annots[0]) == "Square"

    def test_commit_appends_to_history(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(100.0, 100.0)
        mgr.move(200.0, 200.0)
        mgr.commit(sample_doc, 0)
        assert len(mgr._history) == 1
        page_num, xref = mgr._history[0]
        assert page_num == 0
        assert xref > 0

    def test_drag_state_resets_after_commit(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(100.0, 100.0)
        mgr.move(200.0, 200.0)
        mgr.commit(sample_doc, 0)
        assert mgr._start is None
        assert mgr._last_rect is None


class TestUndo:
    def test_undo_empty_history_returns_none(self, mgr, sample_doc):
        assert mgr.undo_last(sample_doc) is None

    def test_undo_removes_last_annotation(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(100.0, 100.0)
        mgr.move(200.0, 200.0)
        mgr.commit(sample_doc, 0)
        assert len(list(sample_doc[0].annots())) == 1

        pn = mgr.undo_last(sample_doc)
        assert pn == 0
        assert mgr._history == []
        assert len(list(sample_doc[0].annots())) == 0

    def test_undo_pops_only_latest(self, mgr, sample_doc):
        """Two RECTs → undo removes the second, leaves the first."""
        mgr.set_tool(Tool.RECT)
        for box in [(50, 50, 100, 100), (150, 150, 200, 200)]:
            mgr.begin(box[0], box[1])
            mgr.move(box[2], box[3])
            mgr.commit(sample_doc, 0)
        assert len(mgr._history) == 2

        pn = mgr.undo_last(sample_doc)
        assert pn == 0
        assert len(mgr._history) == 1
        # The remaining annotation is the first one we drew
        annots = list(sample_doc[0].annots())
        assert len(annots) == 1
        assert annots[0].xref == mgr._history[0][1]

    def test_undo_across_pages(self, mgr, multi_page_pdf):
        """undo_last returns the page number of the last annotation, not always 0."""
        doc = fitz.open(str(multi_page_pdf))
        try:
            mgr.set_tool(Tool.RECT)
            # Annotation on page 0
            mgr.begin(50, 50); mgr.move(100, 100); mgr.commit(doc, 0)
            # Annotation on page 2 (last one in history)
            mgr.begin(50, 50); mgr.move(100, 100); mgr.commit(doc, 2)

            pn = mgr.undo_last(doc)
            assert pn == 2
            # Page 0 still has its annotation
            assert len(list(doc[0].annots())) == 1
            assert len(list(doc[2].annots())) == 0
        finally:
            doc.close()


class TestDeleteAnnot:
    def test_delete_removes_from_history(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(50, 50); mgr.move(100, 100); mgr.commit(sample_doc, 0)
        mgr.begin(150, 150); mgr.move(200, 200); mgr.commit(sample_doc, 0)

        # Delete the FIRST annotation by its xref
        first_xref = mgr._history[0][1]
        ok = mgr.delete_annot(sample_doc, 0, first_xref)
        assert ok is True

        # History should no longer contain that xref
        xrefs_left = [xref for _pn, xref in mgr._history]
        assert first_xref not in xrefs_left
        # The OTHER annotation is still there
        assert len(mgr._history) == 1

    def test_delete_unknown_xref_returns_false(self, mgr, sample_doc):
        assert mgr.delete_annot(sample_doc, 0, 99999) is False


class TestHitTest:
    def test_get_annot_at_returns_annotation_inside_rect(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(100, 100); mgr.move(200, 200); mgr.commit(sample_doc, 0)
        # Hold page ref alive for the duration of the annot interaction.
        page = sample_doc[0]
        annot = mgr.get_annot_at(page, 150, 150)
        assert annot is not None
        assert _atype(annot) == "Square"

    def test_get_annot_at_returns_none_outside_any(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(100, 100); mgr.move(200, 200); mgr.commit(sample_doc, 0)
        page = sample_doc[0]
        assert mgr.get_annot_at(page, 400, 400) is None


# ───────────────────────────────────────────────────────────── helper utilities


class TestAtypeHelper:
    def test_atype_returns_string(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(50, 50); mgr.move(100, 100); mgr.commit(sample_doc, 0)
        page = sample_doc[0]
        annot = list(page.annots())[0]
        assert _atype(annot) == "Square"


class TestFindAnnotByXref:
    def test_found(self, mgr, sample_doc):
        mgr.set_tool(Tool.RECT)
        mgr.begin(50, 50); mgr.move(100, 100); mgr.commit(sample_doc, 0)
        xref = mgr._history[0][1]
        page = sample_doc[0]
        annot = _find_annot_by_xref(page, xref)
        assert annot is not None
        assert annot.xref == xref

    def test_not_found(self, sample_doc):
        page = sample_doc[0]
        assert _find_annot_by_xref(page, 99999) is None


# ──────────────────────────────────────────────────────── RDP simplification


class TestRdpSimplify:
    def test_short_input_unchanged(self):
        pts = [(0.0, 0.0), (5.0, 5.0)]
        assert _rdp_simplify(pts) == pts

    def test_collinear_points_collapse_to_endpoints(self):
        """All-on-a-line input simplifies to just first and last point."""
        pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (10.0, 0.0)]
        result = _rdp_simplify(pts, epsilon=0.1)
        assert result == [(0.0, 0.0), (10.0, 0.0)]

    def test_zigzag_preserves_peaks(self):
        """A clear peak (distance ≫ epsilon) must survive simplification."""
        pts = [(0.0, 0.0), (5.0, 50.0), (10.0, 0.0)]
        result = _rdp_simplify(pts, epsilon=1.0)
        # The middle peak is far from the start-end line → must be retained
        assert (5.0, 50.0) in result

    def test_high_epsilon_aggressive_reduction(self):
        """A large epsilon should reduce more aggressively."""
        pts = [(0.0, 0.0), (5.0, 0.5), (10.0, -0.3), (15.0, 0.1), (20.0, 0.0)]
        result = _rdp_simplify(pts, epsilon=10.0)
        assert len(result) == 2  # Just start and end


# ─────────────────────────────────────────────────────────── Catmull-Rom spline


class TestCatmullRom:
    def test_short_input_unchanged(self):
        pts = [(0.0, 0.0), (1.0, 1.0)]
        assert _catmull_rom(pts) == pts

    def test_endpoints_preserved(self):
        """The spline must pass through the first and last input points."""
        pts = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0), (15.0, 5.0)]
        result = _catmull_rom(pts, steps=4)
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]

    def test_intermediate_points_lie_in_bounding_box(self):
        """Smoothed points should stay within the input's bounding box (loosely)."""
        pts = [(0.0, 0.0), (5.0, 10.0), (10.0, 5.0), (15.0, 0.0)]
        result = _catmull_rom(pts, steps=5)
        xs = [p[0] for p in result]
        ys = [p[1] for p in result]
        # Catmull-Rom can overshoot slightly at curve peaks; allow a small margin
        assert min(xs) >= -1 and max(xs) <= 16
        assert min(ys) >= -3 and max(ys) <= 13

    def test_increases_point_count(self):
        """Smoothing should produce more points than input (for ≥3 points)."""
        pts = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        result = _catmull_rom(pts, steps=5)
        assert len(result) > len(pts)


# ─────────────────────────────────────────────────────────────── FreeText (texto)


class TestTextAnnotation:
    """commit_text / edit_text / props tracking for FreeText annotations."""

    def _freetexts(self, page):
        return [a for a in page.annots() if _atype(a) == "FreeText"]

    # Nota: una fitz.Annot deja de ser válida si su fitz.Page se libera
    # (el Annot guarda un enlace débil a la página). Por eso cada test
    # mantiene viva la variable `page` mientras lee anotaciones — igual que
    # el código de producción, que siempre opera dentro de `with _doc_lock:
    # page = doc[pn]; for a in page.annots()`.

    def test_commit_text_creates_freetext(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "Hola áéí Ñ",
            fontname="tibo", fontsize=18, color=(0.1, 0.1, 0.8), align=1,
        )
        assert xref is not None
        annots = self._freetexts(page)
        assert len(annots) == 1
        assert annots[0].info.get("content") == "Hola áéí Ñ"
        assert mgr._history[-1] == (0, xref)

    def test_commit_empty_text_is_discarded(self, mgr, sample_doc):
        page = sample_doc[0]
        assert mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "   ") is None
        assert self._freetexts(page) == []

    def test_commit_text_enforces_min_box(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 52, 52), "x")
        annot = _find_annot_by_xref(page, xref)
        assert annot.rect.width >= 40 and annot.rect.height >= 20

    def test_props_tracked(self, mgr, sample_doc):
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "abc",
            fontname="cour", fontsize=24, color=(0, 0, 0), align=2,
        )
        props = mgr.get_text_props(xref)
        assert props["fontname"] == "cour"
        assert props["fontsize"] == 24.0
        assert props["align"] == 2

    def test_edit_text_updates_content_and_props(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "viejo")
        new_xref = mgr.edit_text(
            sample_doc, 0, xref, "nuevo", fontname="tiro", fontsize=20, color=(1, 0, 0),
        )
        assert new_xref is not None
        annot = _find_annot_by_xref(page, new_xref)
        assert annot.info.get("content") == "nuevo"
        assert mgr.get_text_props(new_xref)["fontsize"] == 20.0
        # old props dropped
        assert mgr.get_text_props(xref) is None

    def test_move_resize_preserve_text(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "persiste")
        mgr.move_annot(sample_doc, 0, xref, 20, 30)
        annot = self._freetexts(page)[0]
        assert annot.info.get("content") == "persiste"
        mgr.resize_annot(sample_doc, 0, annot.xref, fitz.Rect(60, 60, 400, 200))
        annot = self._freetexts(page)[0]
        assert annot.info.get("content") == "persiste"

    def test_recolor_changes_text_color(self, mgr, sample_doc):
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "color")
        assert mgr.change_annot_color(sample_doc, 0, xref, (1, 0, 0)) is True
        assert mgr.get_text_props(xref)["color"] == (1, 0, 0)

    def test_undo_redo_restores_text(self, mgr, sample_doc):
        page = sample_doc[0]
        mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "deshacer",
            fontname="hebo", fontsize=16,
        )
        assert mgr.undo_last(sample_doc) == 0
        assert self._freetexts(page) == []
        assert mgr.redo_last(sample_doc) == 0
        restored = self._freetexts(page)
        assert len(restored) == 1
        assert restored[0].info.get("content") == "deshacer"

    def test_delete_drops_props(self, mgr, sample_doc):
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "borrar")
        assert mgr.delete_annot(sample_doc, 0, xref) is True
        assert mgr.get_text_props(xref) is None

    def test_read_text_props_reconstructs_after_reopen(self, mgr, sample_doc, tmp_path):
        """Regresión: tras guardar y reabrir, el texto sigue siendo editable.

        ``_text_props`` sólo vive en memoria; un manager nuevo (documento
        reabierto) no lo tiene. ``read_text_props`` debe reconstruir
        texto/fuente/tamaño/color/alineación/recuadro leyendo la anotación.
        """
        mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 120), "Hola\nmundo",
            fontname="tiro", fontsize=18, color=(0.2, 0.4, 0.9),
            align=1, border_width=1.5,
        )
        out = tmp_path / "saved.pdf"
        sample_doc.save(str(out), garbage=4, deflate=True)

        # Manager + documento nuevos: nada en caché (simula reabrir el archivo).
        fresh = AnnotationManager(on_modified=lambda *_a, **_kw: None)
        reopened = fitz.open(str(out))
        page  = reopened[0]
        ft    = self._freetexts(page)[0]
        assert fresh.get_text_props(ft.xref) is None  # caché vacía

        props = fresh.read_text_props(reopened, 0, ft.xref)
        assert props is not None
        assert props["text"] == "Hola\nmundo"
        assert props["fontname"] == "tiro"
        assert props["fontsize"] == 18.0
        assert props["color"] == pytest.approx((0.2, 0.4, 0.9), abs=1e-3)
        assert props["align"] == 1
        assert props["border_width"] == pytest.approx(1.5)

        # Y ahora la edición funciona conservando el estilo reconstruido.
        new_xref = fresh.edit_text(
            reopened, 0, ft.xref, "Editado",
            fontname=props["fontname"], fontsize=props["fontsize"],
            color=props["color"], align=props["align"],
            border_width=props["border_width"],
        )
        assert new_xref is not None
        assert self._freetexts(reopened[0])[0].info.get("content") == "Editado"
        reopened.close()

    def test_take_text_rect_default_box_on_click(self, mgr):
        mgr.set_tool(Tool.TEXT)
        mgr.begin(100.0, 200.0)  # click without drag
        rect = mgr.take_text_rect()
        assert rect is not None
        assert rect.width > 0 and rect.height > 0

    def test_take_text_rect_uses_drag(self, mgr):
        mgr.set_tool(Tool.TEXT)
        mgr.begin(100.0, 100.0)
        mgr.move(260.0, 180.0)
        rect = mgr.take_text_rect()
        assert rect.x0 == 100.0 and rect.x1 == 260.0


# ───────────────────────────────────────────────────────────────────── Duplicate


class TestDuplicate:
    """duplicate_annot: copia desplazada que reutiliza snapshot/recreate."""

    def _make_rect(self, mgr, doc) -> int:
        mgr.set_tool(Tool.RECT)
        mgr.begin(50.0, 50.0)
        mgr.move(150.0, 120.0)
        mgr.commit(doc, 0)
        return mgr._history[-1][1]

    def test_duplicate_rect_offsets_and_tracks_history(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = self._make_rect(mgr, sample_doc)
        orig = fitz.Rect(_find_annot_by_xref(page, xref).rect)
        new_xref = mgr.duplicate_annot(sample_doc, 0, xref, 12.0, 12.0)
        assert new_xref is not None and new_xref != xref
        assert mgr._history[-1] == (0, new_xref)
        # La copia está desplazada respecto al original (página sin rotar). El
        # recreate de un Square reajusta ~1pt por el borde (igual que undo/redo),
        # así que la tolerancia es holgada.
        copy = fitz.Rect(_find_annot_by_xref(page, new_xref).rect)
        assert copy.x0 == pytest.approx(orig.x0 + 12.0, abs=2.0)
        assert copy.y0 == pytest.approx(orig.y0 + 12.0, abs=2.0)
        # Mismo tamaño (±borde).
        assert copy.width == pytest.approx(orig.width, abs=3.0)

    def test_duplicate_missing_xref_returns_none(self, mgr, sample_doc):
        assert mgr.duplicate_annot(sample_doc, 0, 999999, 5, 5) is None

    def test_duplicate_freetext_copies_props(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "copia",
            fontname="tibo", fontsize=18, color=(0.2, 0.2, 0.7), align=1,
        )
        new_xref = mgr.duplicate_annot(sample_doc, 0, xref, 10.0, 10.0)
        assert new_xref is not None
        props = mgr.get_text_props(new_xref)
        assert props is not None
        assert props["fontname"] == "tibo"
        assert props["fontsize"] == 18.0
        assert props["align"] == 1
        # El original sigue intacto.
        assert mgr.get_text_props(xref)["text"] == "copia"
        assert _find_annot_by_xref(page, new_xref).info.get("content") == "copia"

    def test_duplicate_preserves_rotation(self, mgr, sample_doc):
        xref = self._make_rect(mgr, sample_doc)
        mgr.rotate_annot(sample_doc, 0, xref, 30.0)
        rot_xref = mgr._history[-1][1] if mgr._history else xref
        # rotate de Square conserva xref → sigue siendo xref
        new_xref = mgr.duplicate_annot(sample_doc, 0, xref, 8.0, 8.0)
        assert new_xref is not None
        assert mgr.get_rotation(new_xref) == pytest.approx(30.0, abs=0.01)

    def test_duplicate_line_recreates(self, mgr, sample_doc):
        page = sample_doc[0]
        mgr.set_tool(Tool.LINE)
        mgr.begin(40.0, 40.0)
        mgr.move(200.0, 160.0)
        mgr.commit(sample_doc, 0)
        xref = mgr._history[-1][1]
        new_xref = mgr.duplicate_annot(sample_doc, 0, xref, 15.0, 15.0)
        assert new_xref is not None and new_xref != xref
        lines = [a for a in page.annots() if _atype(a) == "Line"]
        assert len(lines) == 2


# ─────────────────────────────────────────────────────────────── Text box variant


class TestTextBox:
    """Variante 'caja de texto': FreeText con recuadro (border_width > 0)."""

    def test_commit_with_border_tracks_width(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "caja",
            fontname="helv", fontsize=16, border_width=1.5,
        )
        assert mgr.get_text_props(xref)["border_width"] == 1.5
        assert _find_annot_by_xref(page, xref).border["width"] == 1.5

    def test_plain_text_has_zero_border(self, mgr, sample_doc):
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "plano")
        assert mgr.get_text_props(xref)["border_width"] == 0.0

    def test_change_width_adjusts_border(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "caja", border_width=1.5,
        )
        new_xref = mgr.change_annot_width(sample_doc, 0, xref, +1.0)
        assert new_xref is not None
        assert mgr.get_text_props(new_xref)["border_width"] == 2.5
        assert _find_annot_by_xref(page, new_xref).border["width"] == 2.5
        # El texto se conserva tras recrear.
        assert _find_annot_by_xref(page, new_xref).info.get("content") == "caja"

    def test_change_width_clamps_minimum(self, mgr, sample_doc):
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "caja", border_width=1.0,
        )
        # Restar más allá del mínimo (0.5) no baja de ahí.
        nx = mgr.change_annot_width(sample_doc, 0, xref, -5.0)
        assert mgr.get_text_props(nx)["border_width"] == 0.5

    def test_change_width_noop_on_plain_text(self, mgr, sample_doc):
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "plano")
        # Sin recuadro, el grosor no aplica: mismo xref y border_width sigue 0.
        assert mgr.change_annot_width(sample_doc, 0, xref, +1.0) == xref
        assert mgr.get_text_props(xref)["border_width"] == 0.0

    def test_scale_preserves_border_and_text(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "caja", border_width=2.0,
        )
        res = mgr.scale_annot(sample_doc, 0, xref, 1.3)
        nx = res[1] if res else xref
        annot = _find_annot_by_xref(page, nx)
        assert annot.info.get("content") == "caja"
        assert annot.border["width"] == 2.0

    def test_edit_can_toggle_border(self, mgr, sample_doc):
        page = sample_doc[0]
        xref = mgr.commit_text(sample_doc, 0, fitz.Rect(50, 50, 300, 110), "t")
        assert mgr.get_text_props(xref)["border_width"] == 0.0
        # Activar recuadro al editar.
        nx = mgr.edit_text(sample_doc, 0, xref, "t", border_width=1.5)
        assert mgr.get_text_props(nx)["border_width"] == 1.5
        assert _find_annot_by_xref(page, nx).border["width"] == 1.5
        # Quitarlo de nuevo.
        nx2 = mgr.edit_text(sample_doc, 0, nx, "t", border_width=0.0)
        assert mgr.get_text_props(nx2)["border_width"] == 0.0

    def test_duplicate_keeps_border(self, mgr, sample_doc):
        xref = mgr.commit_text(
            sample_doc, 0, fitz.Rect(50, 50, 300, 110), "caja", border_width=2.0,
        )
        nx = mgr.duplicate_annot(sample_doc, 0, xref, 10.0, 10.0)
        assert mgr.get_text_props(nx)["border_width"] == 2.0
