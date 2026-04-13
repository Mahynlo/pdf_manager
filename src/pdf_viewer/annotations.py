"""Annotation tools and drag-gesture state machine."""

from enum import Enum
from typing import Callable

import fitz


class Tool(Enum):
    CURSOR    = "cursor"
    SELECT    = "select"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    RECT      = "rect"
    CIRCLE    = "circle"
    LINE      = "line"


OVERLAY_COLOR: dict[Tool, str] = {
    Tool.SELECT:    "#400080FF",
    Tool.HIGHLIGHT: "#80FFDD00",
    Tool.UNDERLINE: "#400000CC",
    Tool.STRIKEOUT: "#40CC0000",
    Tool.RECT:      "#400055AA",
    Tool.CIRCLE:    "#40008833",
    Tool.LINE:      "#40AA2200",
}

STROKE_COLOR: dict[Tool, tuple[float, float, float]] = {
    Tool.HIGHLIGHT: (1.0,  0.90, 0.0),
    Tool.UNDERLINE: (0.0,  0.20, 0.80),
    Tool.STRIKEOUT: (0.80, 0.0,  0.0),
    Tool.RECT:      (0.0,  0.33, 0.67),
    Tool.CIRCLE:    (0.0,  0.55, 0.0),
    Tool.LINE:      (0.70, 0.0,  0.0),
}

HIGHLIGHT_COLORS: list[tuple[str, tuple[float, float, float]]] = [
    ("Amarillo", (1.0, 0.95, 0.0)),
    ("Verde",    (0.5, 1.0,  0.3)),
    ("Azul",     (0.4, 0.8,  1.0)),
    ("Rosa",     (1.0, 0.5,  0.8)),
    ("Naranja",  (1.0, 0.70, 0.0)),
    ("Rojo",     (0.9, 0.2,  0.2)),
    ("Morado",   (0.6, 0.3,  1.0)),
]


def _word_rects(page: fitz.Page, clip: fitz.Rect) -> list[fitz.Rect]:
    words = page.get_text("words", clip=clip)
    return [fitz.Rect(w[0], w[1], w[2], w[3]) for w in words]


def _line_merged_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    """Merge adjacent word rects by visual line for smoother markup appearance."""
    if not rects:
        return []

    sorted_rects = sorted(rects, key=lambda r: (r.y0, r.x0))
    merged: list[fitz.Rect] = []
    current = fitz.Rect(sorted_rects[0])

    for rect in sorted_rects[1:]:
        # Consider words in the same text line when vertical overlap is significant.
        overlap = min(current.y1, rect.y1) - max(current.y0, rect.y0)
        min_height = min(current.height, rect.height)
        same_line = min_height > 0 and overlap >= min_height * 0.5
        if same_line:
            current = fitz.Rect(
                min(current.x0, rect.x0),
                min(current.y0, rect.y0),
                max(current.x1, rect.x1),
                max(current.y1, rect.y1),
            )
            continue

        merged.append(current)
        current = fitz.Rect(rect)

    merged.append(current)
    return merged


class AnnotationManager:
    """Tracks tool selection and drag state; applies annotations to a document."""

    def __init__(self, on_modified: Callable):
        self.on_modified = on_modified
        self.tool = Tool.CURSOR
        self.highlight_color: tuple[float, float, float] = STROKE_COLOR[Tool.HIGHLIGHT]
        self._start: tuple[float, float] | None = None
        self._last_rect: fitz.Rect | None = None
        # Saved after a SELECT drag so the viewer can offer deferred text actions.
        self.last_rect: fitz.Rect | None = None
        # History for undo: list of (page_num, annot_xref) in insertion order.
        self._history: list[tuple[int, int]] = []

    # ── tool selection ──────────────────────────────────────────────────────

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool

    @property
    def overlay_color(self) -> str:
        return OVERLAY_COLOR.get(self.tool, "#40808080")

    # ── drag lifecycle ──────────────────────────────────────────────────────

    def begin(self, x: float, y: float) -> None:
        self._start = (x, y)
        self._last_rect = None

    def move(self, x: float, y: float) -> fitz.Rect | None:
        if self._start is None:
            return None
        sx, sy = self._start
        self._last_rect = fitz.Rect(
            min(sx, x), min(sy, y),
            max(sx, x), max(sy, y),
        )
        return self._last_rect

    def commit(self, doc: fitz.Document, page_num: int) -> tuple[bool, str | None]:
        """Apply the pending drag as an annotation.

        Returns (page_was_modified, selected_text_or_None).
        """
        if self._start is None or self._last_rect is None:
            self._start = None
            return False, None

        rect = self._last_rect
        self._start = None
        self._last_rect = None

        if rect.width < 3 and rect.height < 3:
            return False, None

        page = doc[page_num]

        # ── text selection (copy / deferred annotation) ──────────────────────
        if self.tool == Tool.SELECT:
            text = page.get_text("text", clip=rect).strip()
            if text:
                self.last_rect = rect
            return False, text or None

        # ── text markup ──────────────────────────────────────────────────────
        if self.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            rects = _line_merged_rects(_word_rects(page, rect))
            if not rects:
                return False, None
            if self.tool == Tool.HIGHLIGHT:
                annot = page.add_highlight_annot(rects)
                annot.set_colors(stroke=self.highlight_color)
            elif self.tool == Tool.UNDERLINE:
                annot = page.add_underline_annot(rects)
                annot.set_colors(stroke=STROKE_COLOR[Tool.UNDERLINE])
            else:
                annot = page.add_strikeout_annot(rects)
                annot.set_colors(stroke=STROKE_COLOR[Tool.STRIKEOUT])
            annot.update()
            self._history.append((page_num, annot.xref))
            return True, None

        # ── shape tools ──────────────────────────────────────────────────────
        if self.tool == Tool.RECT:
            annot = page.add_rect_annot(rect)
            annot.set_colors(stroke=STROKE_COLOR[Tool.RECT])
            annot.set_border(width=2)
            annot.update()
            self._history.append((page_num, annot.xref))
            return True, None

        if self.tool == Tool.CIRCLE:
            annot = page.add_circle_annot(rect)
            annot.set_colors(stroke=STROKE_COLOR[Tool.CIRCLE])
            annot.set_border(width=2)
            annot.update()
            self._history.append((page_num, annot.xref))
            return True, None

        if self.tool == Tool.LINE:
            annot = page.add_line_annot(rect.tl, rect.br)
            annot.set_colors(stroke=STROKE_COLOR[Tool.LINE])
            annot.set_border(width=2)
            annot.update()
            self._history.append((page_num, annot.xref))
            return True, None

        return False, None

    # ── undo ─────────────────────────────────────────────────────────────────

    def undo_last(self, doc: fitz.Document) -> int | None:
        """Remove the most recently added annotation (any page).

        Returns the page number it was on, or None if nothing to undo.
        """
        if not self._history:
            return None
        page_num, xref = self._history[-1]
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref == xref:
                page.delete_annot(annot)
                self._history.pop()
                return page_num
        self._history.pop()  # xref gone already; clean up history
        return page_num

    def undo(self, doc: fitz.Document, page_num: int | None = None) -> bool:
        """Compatibility wrapper used by viewer code."""
        return self.undo_last(doc) is not None

    # ── annotation hit-test & editing ─────────────────────────────────────────

    def get_annot_at(self, page: fitz.Page, x: float, y: float) -> fitz.Annot | None:
        """Return the topmost annotation at PDF point (x, y), or None."""
        pt = fitz.Point(x, y)
        result = None
        for annot in page.annots():
            # Expand hit-area a little so thin lines are easier to pick.
            hit = fitz.Rect(annot.rect)
            hit.x0 -= 3
            hit.y0 -= 3
            hit.x1 += 3
            hit.y1 += 3
            if hit.contains(pt):
                result = annot
        return result

    def delete_annot(self, doc: fitz.Document, page_num: int, xref: int) -> bool:
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref == xref:
                page.delete_annot(annot)
                self._history = [(p, x) for p, x in self._history if x != xref]
                return True
        return False

    def change_annot_color(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        color: tuple[float, float, float],
    ) -> bool:
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref == xref:
                annot.set_colors(stroke=color)
                annot.update()
                return True
        return False

    def move_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        dx: float,
        dy: float,
    ) -> bool:
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            r = annot.rect
            annot.set_rect(fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy))
            annot.update()
            return True
        return False

    def scale_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        factor: float,
    ) -> bool:
        if factor <= 0:
            return False
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            r = annot.rect
            cx = (r.x0 + r.x1) / 2
            cy = (r.y0 + r.y1) / 2
            half_w = max(1.0, r.width * factor / 2)
            half_h = max(1.0, r.height * factor / 2)
            annot.set_rect(fitz.Rect(cx - half_w, cy - half_h, cx + half_w, cy + half_h))
            annot.update()
            return True
        return False

    # ── deferred text annotation ──────────────────────────────────────────────

    def apply_text_tool(self, doc: fitz.Document, page_num: int, tool: Tool) -> bool:
        """Apply a markup annotation to the area saved from the last SELECT drag."""
        if self.last_rect is None:
            return False
        rect = self.last_rect
        page = doc[page_num]
        rects = _line_merged_rects(_word_rects(page, rect))
        if not rects:
            self.last_rect = None
            return False

        if tool == Tool.HIGHLIGHT:
            annot = page.add_highlight_annot(rects)
            annot.set_colors(stroke=self.highlight_color)
        elif tool == Tool.UNDERLINE:
            annot = page.add_underline_annot(rects)
            annot.set_colors(stroke=STROKE_COLOR[Tool.UNDERLINE])
        elif tool == Tool.STRIKEOUT:
            annot = page.add_strikeout_annot(rects)
            annot.set_colors(stroke=STROKE_COLOR[Tool.STRIKEOUT])
        else:
            return False

        annot.update()
        self._history.append((page_num, annot.xref))
        self.last_rect = None
        return True
