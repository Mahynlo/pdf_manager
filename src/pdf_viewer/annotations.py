"""Annotation tools and drag-gesture state machine."""

import math
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


def _map_point(p: fitz.Point, old: fitz.Rect, new: fitz.Rect) -> fitz.Point:
    """Map *p* from *old* rect's coordinate space into *new* rect's space."""
    ow = max(old.width, 0.001)
    oh = max(old.height, 0.001)
    tx = (p.x - old.x0) / ow
    ty = (p.y - old.y0) / oh
    return fitz.Point(new.x0 + tx * new.width, new.y0 + ty * new.height)


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
        # Always-saved rect from the last SELECT drag (even when no native text found).
        self.last_select_rect: fitz.Rect | None = None
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
            self.last_select_rect = rect   # always saved (OCR fallback uses this)
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
            # Expand hit-area so lines and small annotations are easier to pick.
            hit = fitz.Rect(annot.rect)
            hit.x0 -= 6
            hit.y0 -= 6
            hit.x1 += 6
            hit.y1 += 6
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
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            if atype in ("Line", "Polygon", "PolyLine"):
                verts = annot.vertices
                if verts and len(verts) >= 2:
                    new_verts = [fitz.Point(v.x + dx, v.y + dy) for v in verts]
                    annot.set_vertices(new_verts)
                    annot.update()
                    return True
            r = annot.rect
            annot.set_rect(fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy))
            annot.update()
            return True
        return False

    def set_annot_hidden(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        hidden: bool,
    ) -> bool:
        """Toggle the PDF_ANNOT_IS_HIDDEN flag so the annotation disappears
        from the rendered image while its PDF state is untouched.

        Used during interactive drag so the old position doesn't show under
        the moving ghost overlay.
        """
        page = doc[page_num]
        flag = fitz.PDF_ANNOT_IS_HIDDEN
        for annot in page.annots():
            if annot.xref != xref:
                continue
            cur = annot.flags
            new = (cur | flag) if hidden else (cur & ~flag)
            if new != cur:
                annot.set_flags(new)
                annot.update()
            return True
        return False

    def resize_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        new_rect: fitz.Rect,
    ) -> bool:
        """Set annotation to an explicit new rect (used by interactive corner-drag resize)."""
        if new_rect.is_empty or new_rect.width < 1 or new_rect.height < 1:
            return False
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            if atype == "Line":
                verts = annot.vertices
                if verts and len(verts) >= 2:
                    old_rect = annot.rect
                    p1 = _map_point(fitz.Point(verts[0].x, verts[0].y), old_rect, new_rect)
                    p2 = _map_point(fitz.Point(verts[1].x, verts[1].y), old_rect, new_rect)
                    annot.set_vertices([p1, p2])
                    annot.update()
                    return True
            annot.set_rect(new_rect)
            annot.update()
            return True
        return False

    def rotate_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        angle_deg: float,
    ) -> tuple[fitz.Rect, int] | None:
        """Rotate the annotation around its centre by *angle_deg*.

        * ``Line`` rotates its two vertices in place (xref preserved).
        * ``Square`` / ``Circle`` cannot rotate natively — they are replaced
          with a ``Polygon`` approximation (square → 4 rotated corners,
          circle → 36-point ellipse) and given a fresh xref.

        Returns ``(new_rect, new_xref)`` on success, or ``None`` on failure.
        """
        if abs(angle_deg) < 0.01:
            return None
        page = doc[page_num]
        rad     = math.radians(angle_deg)
        cos_a   = math.cos(rad)
        sin_a   = math.sin(rad)

        def _rotate(p: fitz.Point, cx: float, cy: float) -> fitz.Point:
            dx, dy = p.x - cx, p.y - cy
            return fitz.Point(cx + dx * cos_a - dy * sin_a,
                              cy + dx * sin_a + dy * cos_a)

        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""

            if atype == "Line":
                verts = annot.vertices
                if not verts or len(verts) < 2:
                    return None
                cx = (verts[0].x + verts[1].x) / 2
                cy = (verts[0].y + verts[1].y) / 2
                new_verts = [_rotate(fitz.Point(v.x, v.y), cx, cy) for v in verts]
                annot.set_vertices(new_verts)
                annot.update()
                return fitz.Rect(annot.rect), annot.xref

            # Square / Circle → Polygon conversion (only way to visually rotate).
            if atype not in ("Square", "Circle"):
                return None

            colors = annot.colors or {}
            stroke = colors.get("stroke")
            border = annot.border or {}
            width  = border.get("width", 2) or 2
            r = fitz.Rect(annot.rect)
            cx = (r.x0 + r.x1) / 2
            cy = (r.y0 + r.y1) / 2

            if atype == "Square":
                corners = [
                    fitz.Point(r.x0, r.y0),
                    fitz.Point(r.x1, r.y0),
                    fitz.Point(r.x1, r.y1),
                    fitz.Point(r.x0, r.y1),
                ]
            else:
                # Circle → 36-point ellipse sampled around centre, then rotated.
                rx = (r.x1 - r.x0) / 2
                ry = (r.y1 - r.y0) / 2
                n  = 36
                corners = [
                    fitz.Point(cx + rx * math.cos(2 * math.pi * i / n),
                               cy + ry * math.sin(2 * math.pi * i / n))
                    for i in range(n)
                ]

            rotated = [_rotate(p, cx, cy) for p in corners]

            # Replace the annot: delete old, add polygon, copy style.
            page.delete_annot(annot)
            new_annot = page.add_polygon_annot(rotated)
            if stroke is not None:
                new_annot.set_colors(stroke=stroke)
            new_annot.set_border(width=width)
            new_annot.update()

            # Keep undo history consistent (swap xref in the stack).
            self._history = [
                (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                for (p, x) in self._history
            ]
            return fitz.Rect(new_annot.rect), new_annot.xref

        return None

    def scale_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        factor: float,
    ) -> fitz.Rect | None:
        """Scale the annotation around its centre by *factor*.

        Returns the new PDF rect on success, or None on failure.
        """
        if factor <= 0:
            return None
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            r = annot.rect
            cx = (r.x0 + r.x1) / 2
            cy = (r.y0 + r.y1) / 2
            half_w = max(1.0, r.width * factor / 2)
            half_h = max(1.0, r.height * factor / 2)
            new_rect = fitz.Rect(cx - half_w, cy - half_h, cx + half_w, cy + half_h)
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            if atype == "Line":
                verts = annot.vertices
                if verts and len(verts) >= 2:
                    p1 = _map_point(fitz.Point(verts[0].x, verts[0].y), r, new_rect)
                    p2 = _map_point(fitz.Point(verts[1].x, verts[1].y), r, new_rect)
                    annot.set_vertices([p1, p2])
                    annot.update()
                    return new_rect
            annot.set_rect(new_rect)
            annot.update()
            return new_rect
        return None

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
