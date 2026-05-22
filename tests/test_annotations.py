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
