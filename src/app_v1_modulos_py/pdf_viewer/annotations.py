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
    ARROW     = "arrow"
    INK       = "ink"


OVERLAY_COLOR: dict[Tool, str] = {
    Tool.SELECT:    "#400080FF",
    Tool.HIGHLIGHT: "#80FFDD00",
    Tool.UNDERLINE: "#400000CC",
    Tool.STRIKEOUT: "#40CC0000",
    Tool.RECT:      "#400055AA",
    Tool.CIRCLE:    "#40008833",
    Tool.LINE:      "#40AA2200",
    Tool.ARROW:     "#40AA2200",
    Tool.INK:       "#40003388",
}

STROKE_COLOR: dict[Tool, tuple[float, float, float]] = {
    Tool.HIGHLIGHT: (1.0,  0.90, 0.0),
    Tool.UNDERLINE: (0.0,  0.20, 0.80),
    Tool.STRIKEOUT: (0.80, 0.0,  0.0),
    Tool.RECT:      (0.0,  0.33, 0.67),
    Tool.CIRCLE:    (0.0,  0.55, 0.0),
    Tool.LINE:      (0.70, 0.0,  0.0),
    Tool.ARROW:     (0.70, 0.0,  0.0),
    Tool.INK:       (0.0,  0.20, 0.70),
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


def _catmull_rom(pts: list[tuple[float, float]], steps: int = 5) -> list[tuple[float, float]]:
    """Smooth a polyline with Catmull-Rom spline interpolation."""
    if len(pts) < 3:
        return list(pts)
    out: list[tuple[float, float]] = []
    for i in range(len(pts) - 1):
        p0 = pts[max(0, i - 1)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(len(pts) - 1, i + 2)]
        for s in range(steps):
            t  = s / steps
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * ((2 * p1[0])
                        + (-p0[0] + p2[0]) * t
                        + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                        + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1])
                        + (-p0[1] + p2[1]) * t
                        + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                        + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(pts[-1])
    return out


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


def _rot_matrix(rect: fitz.Rect, angle_deg: float) -> fitz.Matrix:
    """Build an ``apn_matrix`` that rotates the annotation appearance by
    *angle_deg* around the centre of *rect*.

    PyMuPDF's ``annot.set_rotation`` writes a ``/Rotate`` entry but MuPDF
    does NOT honour it for Square/Circle appearances (verified on 1.27) —
    the shape renders axis-aligned regardless. Setting the Form XObject's
    ``/Matrix`` via ``set_apn_matrix`` DOES rotate the rendered appearance.
    """
    theta   = math.radians(angle_deg)
    cos_a   = math.cos(theta)
    sin_a   = math.sin(theta)
    bx      = (rect.x0 + rect.x1) / 2
    by      = (rect.y0 + rect.y1) / 2
    m  = fitz.Matrix(1, 0, 0, 1, -bx, -by)
    m *= fitz.Matrix(cos_a, sin_a, -sin_a, cos_a, 0, 0)
    m *= fitz.Matrix(1, 0, 0, 1, bx, by)
    return m


_IDENTITY = fitz.Matrix(1, 0, 0, 1, 0, 0)


def _reset_ap(annot: fitz.Annot) -> None:
    """Reset ``apn_matrix`` to identity.

    Must be called BEFORE ``annot.update()`` on any annotation that may
    have a custom apn_matrix — PyMuPDF 1.27 has a bug where update()
    crashes with ``AttributeError('setRect')`` if the Form XObject's
    /Matrix is non-identity. Resetting keeps us on the safe path.
    """
    try:
        annot.set_apn_matrix(_IDENTITY)
    except Exception:
        pass


def _apply_rot(annot: fitz.Annot, angle_deg: float) -> None:
    """Apply rotation visually to *annot* via its AP matrix, around the
    centre of its current rect. ``annot.update()`` MUST have been called
    first (update resets apn_matrix to identity).
    """
    a = angle_deg % 360
    if a < 0:
        a += 360
    if a < 0.01 or abs(a - 360) < 0.01:
        annot.set_apn_matrix(_IDENTITY)
        return
    annot.set_apn_matrix(_rot_matrix(annot.rect, a))


def _line_replace(
    page: fitz.Page,
    annot: fitz.Annot,
    new_verts: list[fitz.Point],
    new_width: float | None = None,
) -> fitz.Annot:
    """Delete a Line annotation and recreate it, preserving color, width, and line ends (arrow tip)."""
    colors = {}
    try:
        colors = annot.colors or {}
    except Exception:
        pass
    stroke = colors.get("stroke")
    border = annot.border or {}
    width  = new_width if new_width is not None else (border.get("width", 2) or 2)
    line_ends = (0, 0)
    try:
        le = annot.line_ends
        if le:
            line_ends = (int(le[0]), int(le[1]))
    except Exception:
        pass

    page.delete_annot(annot)
    new_annot = page.add_line_annot(new_verts[0], new_verts[1])
    if stroke is not None:
        new_annot.set_colors(stroke=stroke)
    new_annot.set_border(width=width)
    if line_ends != (0, 0):
        try:
            new_annot.set_line_ends(*line_ends)
        except Exception:
            pass
    _reset_ap(new_annot)
    new_annot.update()
    return new_annot


def _ink_verts_from_annot(annot: fitz.Annot) -> list[list[fitz.Point]] | None:
    """Extract ink strokes as list[list[fitz.Point]], or None if empty."""
    raw = annot.vertices
    if not raw:
        return None
    strokes = []
    for stroke in raw:
        pts = []
        for pt in stroke:
            try:
                pts.append(fitz.Point(float(pt[0]), float(pt[1])))
            except (TypeError, IndexError):
                pts.append(fitz.Point(float(pt.x), float(pt.y)))
        if pts:
            strokes.append(pts)
    return strokes or None


def _ink_replace(
    page: fitz.Page,
    annot: fitz.Annot,
    new_strokes: list[list[fitz.Point]],
    new_width: float | None = None,
) -> fitz.Annot:
    """Delete an Ink annotation and recreate it preserving color and width."""
    colors = {}
    try:
        colors = annot.colors or {}
    except Exception:
        pass
    stroke_color = colors.get("stroke")
    border = annot.border or {}
    width  = new_width if new_width is not None else (border.get("width", 2) or 2)
    page.delete_annot(annot)
    flat = [
        [(float(p.x if hasattr(p, "x") else p[0]), float(p.y if hasattr(p, "y") else p[1])) for p in s]
        for s in new_strokes
    ]
    new_annot = page.add_ink_annot(flat)
    if stroke_color is not None:
        new_annot.set_colors(stroke=stroke_color)
    new_annot.set_border(width=width)
    new_annot.update()
    return new_annot


def _polygon_replace(
    page: fitz.Page,
    annot: fitz.Annot,
    new_verts: list[fitz.Point],
    atype: str,
) -> fitz.Annot:
    """Delete *annot* and recreate it as the same vertex-based type with
    *new_verts*, preserving stroke colour and border width.

    Why delete+recreate instead of ``set_vertices`` + ``update``:
    PyMuPDF regenerates the appearance stream from whatever geometry is
    recorded when the annotation was created. Mutating vertices afterwards
    does not always refresh the appearance stream in the rendered page,
    which manifests as the annotation appearing to "snap back" to its
    pre-mutation shape after move / resize / rotate. Recreating guarantees
    the appearance matches the new geometry.
    """
    colors = {}
    try:
        colors = annot.colors or {}
    except Exception:
        pass
    stroke = colors.get("stroke")
    border = annot.border or {}
    width  = border.get("width", 2) or 2

    page.delete_annot(annot)

    if atype == "Line":
        new_annot = page.add_line_annot(new_verts[0], new_verts[1])
    elif atype == "PolyLine":
        new_annot = page.add_polyline_annot(new_verts)
    else:  # Polygon
        new_annot = page.add_polygon_annot(new_verts)

    if stroke is not None:
        new_annot.set_colors(stroke=stroke)
    new_annot.set_border(width=width)
    new_annot.update()
    return new_annot


class AnnotationManager:
    """Tracks tool selection and drag state; applies annotations to a document."""

    def __init__(self, on_modified: Callable):
        self.on_modified = on_modified
        self.tool = Tool.CURSOR
        self.highlight_color: tuple[float, float, float] = STROKE_COLOR[Tool.HIGHLIGHT]
        self._start: tuple[float, float] | None = None
        self._last_rect: fitz.Rect | None = None
        # Raw (un-normalized) start/end points for LINE and ARROW tools.
        self._raw_start: tuple[float, float] | None = None
        self._raw_end:   tuple[float, float] | None = None
        # Saved after a SELECT drag so the viewer can offer deferred text actions.
        self.last_rect: fitz.Rect | None = None
        # Always-saved rect from the last SELECT drag (even when no native text found).
        self.last_select_rect: fitz.Rect | None = None
        # History for undo: list of (page_num, annot_xref) in insertion order.
        self._history: list[tuple[int, int]] = []
        # Visual (unrotated) rect per annotation xref. ``annot.rect`` is
        # also the visual rect here because we never expand it — rotation
        # is handled via the Form XObject's /Matrix — but caching lets the
        # viewer read it without holding the document lock during drag.
        self._visual_rects: dict[int, fitz.Rect] = {}
        # Rotation in degrees per xref. ``annot.rotation`` (/Rotate) is
        # NOT used as the source of truth: setting /Rotate makes PyMuPDF
        # expand the bbox inside update(), which undoes the work of
        # keeping /Rect at the visual size.
        self._rotations: dict[int, float] = {}

    def get_visual_rect(self, xref: int) -> fitz.Rect | None:
        vr = self._visual_rects.get(xref)
        return fitz.Rect(vr) if vr is not None else None

    def get_rotation(self, xref: int) -> float:
        return float(self._rotations.get(xref, 0.0))

    # ── tool selection ──────────────────────────────────────────────────────

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool

    @property
    def overlay_color(self) -> str:
        return OVERLAY_COLOR.get(self.tool, "#40808080")

    # ── drag lifecycle ──────────────────────────────────────────────────────

    def begin(self, x: float, y: float) -> None:
        self._start = (x, y)
        self._raw_start = (x, y)
        self._raw_end   = (x, y)
        self._last_rect = None

    def move(self, x: float, y: float) -> fitz.Rect | None:
        if self._start is None:
            return None
        sx, sy = self._start
        self._raw_end   = (x, y)
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
            self._start     = None
            self._raw_start = None
            self._raw_end   = None
            return False, None

        rect      = self._last_rect
        raw_start = self._raw_start
        raw_end   = self._raw_end
        self._start     = None
        self._last_rect = None
        self._raw_start = None
        self._raw_end   = None

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
            if raw_start is None or raw_end is None:
                return False, None
            p1 = fitz.Point(*raw_start)
            p2 = fitz.Point(*raw_end)
            if math.hypot(p2.x - p1.x, p2.y - p1.y) < 5:
                return False, None
            annot = page.add_line_annot(p1, p2)
            annot.set_colors(stroke=STROKE_COLOR[Tool.LINE])
            annot.set_border(width=2)
            annot.update()
            self._history.append((page_num, annot.xref))
            return True, None

        if self.tool == Tool.ARROW:
            if raw_start is None or raw_end is None:
                return False, None
            p1 = fitz.Point(*raw_start)
            p2 = fitz.Point(*raw_end)
            if math.hypot(p2.x - p1.x, p2.y - p1.y) < 5:
                return False, None
            annot = page.add_line_annot(p1, p2)
            annot.set_colors(stroke=STROKE_COLOR[Tool.ARROW])
            annot.set_border(width=2)
            try:
                annot.set_line_ends(0, 4)  # NONE at start, OPEN_ARROW at end
            except Exception:
                pass
            annot.update()
            self._history.append((page_num, annot.xref))
            return True, None

        return False, None

    def commit_ink(
        self,
        doc: fitz.Document,
        page_num: int,
        pdf_points: list[tuple[float, float]],
    ) -> bool:
        """Create a smoothed ink annotation from collected PDF-space points."""
        if len(pdf_points) < 2:
            return False
        smoothed = _catmull_rom(pdf_points) if len(pdf_points) >= 3 else list(pdf_points)
        page  = doc[page_num]
        annot = page.add_ink_annot([smoothed])
        annot.set_colors(stroke=STROKE_COLOR[Tool.INK])
        annot.set_border(width=2)
        annot.update()
        self._history.append((page_num, annot.xref))
        return True

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
        """Return the annotation at PDF point (x, y), preferring shapes over markup."""
        _MARKUP = {"Highlight", "Underline", "StrikeOut", "Squiggly"}
        pt = fitz.Point(x, y)
        shape_result  = None
        markup_result = None
        for annot in page.annots():
            # Expand hit-area so lines and small annotations are easier to pick.
            hit = fitz.Rect(annot.rect)
            hit.x0 -= 6
            hit.y0 -= 6
            hit.x1 += 6
            hit.y1 += 6
            if not hit.contains(pt):
                continue
            atype = (annot.type[1]
                     if isinstance(annot.type, (tuple, list)) and len(annot.type) > 1
                     else "")
            if atype in _MARKUP:
                markup_result = annot
            else:
                shape_result = annot
        # Shapes (rect/circle/line/etc.) take priority over markup overlays so
        # that a shape drawn under a highlight/underline remains selectable.
        return shape_result if shape_result is not None else markup_result

    def delete_annot(self, doc: fitz.Document, page_num: int, xref: int) -> bool:
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref == xref:
                page.delete_annot(annot)
                self._history = [(p, x) for p, x in self._history if x != xref]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
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
                rotation = self._rotations.get(xref, 0.0)
                _reset_ap(annot)
                annot.set_colors(stroke=color)
                annot.update()
                if rotation:
                    _apply_rot(annot, rotation)
                return True
        return False

    def move_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        dx: float,
        dy: float,
    ) -> tuple[fitz.Rect, int, float] | None:
        """Translate annotation by (dx, dy) in PDF coords.

        Returns ``(new_rect, new_xref, rotation_deg)`` on success, ``None``
        on failure. ``new_rect`` is the PyMuPDF bbox of the annotation after
        the move (expanded to contain any rotated appearance). For
        Line/Polygon/PolyLine the xref changes (delete+recreate) and
        rotation is always 0 because the angle is baked into the vertices.
        For Square/Circle/FreeText the xref is preserved and any existing
        /Rotate value is returned unchanged.
        """
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            if atype == "Ink":
                strokes = _ink_verts_from_annot(annot)
                if not strokes:
                    return None
                new_strokes = [[fitz.Point(pt.x + dx, pt.y + dy) for pt in s] for s in strokes]
                try:
                    new_annot = _ink_replace(page, annot, new_strokes)
                except Exception:
                    return None
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return fitz.Rect(new_annot.rect), new_annot.xref, 0.0
            if atype in ("Line", "Polygon", "PolyLine"):
                verts = annot.vertices
                if not verts or len(verts) < 2:
                    return None
                new_verts = []
                for v in verts:
                    try:
                        vx, vy = float(v[0]), float(v[1])
                    except (TypeError, IndexError):
                        vx, vy = float(v.x), float(v.y)
                    new_verts.append(fitz.Point(vx + dx, vy + dy))
                if atype == "Line":
                    new_annot = _line_replace(page, annot, new_verts)
                else:
                    new_annot = _polygon_replace(page, annot, new_verts, atype)
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return fitz.Rect(new_annot.rect), new_annot.xref, 0.0
            rotation = self._rotations.get(xref, 0.0)
            cached = self._visual_rects.get(xref)
            base   = cached if cached is not None else fitz.Rect(annot.rect)
            new_visual = fitz.Rect(
                base.x0 + dx, base.y0 + dy,
                base.x1 + dx, base.y1 + dy,
            )
            try:
                _reset_ap(annot)  # avoid PyMuPDF 1.27 setRect bug in update()
                annot.set_rect(new_visual)
                annot.update()
                if rotation:
                    _apply_rot(annot, rotation)
            except Exception:
                return None
            self._visual_rects[annot.xref] = fitz.Rect(new_visual)
            return new_visual, annot.xref, rotation
        return None

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
                rotation = self._rotations.get(xref, 0.0)
                _reset_ap(annot)
                annot.set_flags(new)
                annot.update()
                if rotation:
                    _apply_rot(annot, rotation)
            return True
        return False

    def resize_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        new_rect: fitz.Rect,
    ) -> tuple[fitz.Rect, int, float] | None:
        """Set annotation to *new_rect* (used by interactive corner-drag resize).

        ``new_rect`` is the **unrotated** (visual) rect. For a rotated
        Square/Circle/FreeText the rotation is temporarily stripped so
        ``set_rect`` sizes the real shape (instead of fitting inside the
        expanded bbox), then the rotation is re-applied. This keeps the
        visual shape at the exact size the user dragged to.

        Returns ``(pdf_bbox, new_xref, rotation_deg)`` on success, ``None``
        on failure. ``pdf_bbox`` is the PyMuPDF bbox of the annotation after
        the edit (may be larger than ``new_rect`` because of rotation).
        """
        if new_rect.is_empty or new_rect.width < 1 or new_rect.height < 1:
            return None
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            if atype == "Ink":
                strokes = _ink_verts_from_annot(annot)
                if not strokes:
                    return None
                old_rect = annot.rect
                new_strokes = [
                    [_map_point(pt, old_rect, new_rect) for pt in s]
                    for s in strokes
                ]
                try:
                    new_annot = _ink_replace(page, annot, new_strokes)
                except Exception:
                    return None
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return fitz.Rect(new_annot.rect), new_annot.xref, 0.0
            if atype in ("Line", "Polygon", "PolyLine"):
                verts = annot.vertices
                if not verts or len(verts) < 2:
                    return None
                old_rect = annot.rect
                new_verts = []
                for v in verts:
                    try:
                        vx, vy = float(v[0]), float(v[1])
                    except (TypeError, IndexError):
                        vx, vy = float(v.x), float(v.y)
                    new_verts.append(_map_point(fitz.Point(vx, vy), old_rect, new_rect))
                if atype == "Line":
                    new_annot = _line_replace(page, annot, new_verts)
                else:
                    new_annot = _polygon_replace(page, annot, new_verts, atype)
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return fitz.Rect(new_annot.rect), new_annot.xref, 0.0
            rotation = self._rotations.get(xref, 0.0)
            try:
                _reset_ap(annot)
                annot.set_rect(new_rect)
                annot.update()
                if rotation:
                    _apply_rot(annot, rotation)
            except Exception:
                return None
            self._visual_rects[annot.xref] = fitz.Rect(new_rect)
            return fitz.Rect(new_rect), annot.xref, rotation
        return None

    def rotate_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        angle_deg: float,
        visual_rect: fitz.Rect | None = None,
    ) -> tuple[fitz.Rect, int, float] | None:
        """Rotate the annotation by *angle_deg*, accumulating with any prior rotation.

        * ``Square`` / ``Circle`` / ``FreeText`` use PyMuPDF's native
          ``set_rotation`` (PDF /Rotate entry). The annotation keeps its
          original type, so subsequent move / resize / rotate continue to
          work without any conversion.
        * ``Line`` / ``Polygon`` / ``PolyLine`` rotate their vertices around
          the bbox centre (delete + recreate — the xref changes).

        ``visual_rect`` is the caller-tracked pre-rotation axis-aligned
        rect (same width/height as the original unrotated shape, same
        centre). When supplied for Square/Circle/FreeText, the rotation is
        temporarily stripped so the shape is re-sized to *visual_rect*
        before re-applying the new angle — that way repeated rotations
        don't cause PyMuPDF's expanded bbox to creep outwards.

        Returns ``(visual_rect_out, new_xref, rotation_deg)``:
        ``visual_rect_out`` is the user-facing unrotated rect (unchanged
        for Square/Circle; the new vertex bbox for Line/Polygon).
        """
        if abs(angle_deg) < 0.01:
            return None
        page = doc[page_num]

        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""

            if atype in ("Line", "Polygon", "PolyLine"):
                verts = annot.vertices
                if not verts or len(verts) < 2:
                    return None
                r = fitz.Rect(annot.rect)
                cx = (r.x0 + r.x1) / 2
                cy = (r.y0 + r.y1) / 2
                rad   = math.radians(angle_deg)
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)
                new_verts = []
                for v in verts:
                    try:
                        vx, vy = float(v[0]), float(v[1])
                    except (TypeError, IndexError):
                        vx, vy = float(v.x), float(v.y)
                    dx, dy = vx - cx, vy - cy
                    new_verts.append(fitz.Point(
                        cx + dx * cos_a - dy * sin_a,
                        cy + dx * sin_a + dy * cos_a,
                    ))
                new_annot = _polygon_replace(page, annot, new_verts, atype)
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return fitz.Rect(new_annot.rect), new_annot.xref, 0.0

            # Square / Circle / FreeText: visually rotate via the Form
            # XObject's /Matrix (apn_matrix). PyMuPDF's native set_rotation
            # stores /Rotate but MuPDF does not render Square/Circle at
            # arbitrary angles — only bbox expansion happens. We instead
            # keep /Rect equal to the visual rect and set apn_matrix so the
            # appearance is rotated around the rect's centre.
            current     = self._rotations.get(xref, 0.0)
            new_rotation = (float(current) + float(angle_deg)) % 360
            if new_rotation < 0:
                new_rotation += 360

            vr = None
            if visual_rect is not None:
                vr = fitz.Rect(visual_rect)
            else:
                cached = self._visual_rects.get(xref)
                if cached is not None:
                    vr = fitz.Rect(cached)
            if vr is None:
                vr = fitz.Rect(annot.rect)
            try:
                # Rewrite /Rect to the visual rect (unrotated) and
                # regenerate the axis-aligned appearance, then rotate the
                # Form XObject via its /Matrix. Reset apn_matrix first —
                # PyMuPDF 1.27's update() crashes if apn_matrix is
                # non-identity. set_rotation is NOT called: it would
                # cause update() to expand the bbox and render the shape
                # axis-aligned inside the expansion.
                _reset_ap(annot)
                annot.set_rect(vr)
                annot.update()
                _apply_rot(annot, new_rotation)
            except Exception:
                return None
            self._visual_rects[annot.xref] = fitz.Rect(vr)
            # Stash rotation so re-selection can recover it without
            # decoding the apn_matrix. Keyed by current xref.
            self._rotations[annot.xref] = float(new_rotation)
            return vr, annot.xref, float(new_rotation)

        return None

    def scale_annot(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        factor: float,
    ) -> tuple[fitz.Rect, int] | None:
        """Scale the annotation around its centre by *factor*.

        Returns ``(new_visual_rect, new_xref)`` on success, or None on failure.
        For Line/Arrow the xref changes (delete+recreate); for all other types
        the xref is unchanged. Callers must update their cached xref accordingly.
        """
        if factor <= 0:
            return None
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""

            # Use the cached pre-rotation rect when available so scale is
            # applied to the user-facing shape, not PyMuPDF's expanded bbox.
            cached = self._visual_rects.get(xref)
            r = fitz.Rect(cached) if cached is not None else fitz.Rect(annot.rect)
            cx = (r.x0 + r.x1) / 2
            cy = (r.y0 + r.y1) / 2
            half_w = max(1.0, r.width * factor / 2)
            half_h = max(1.0, r.height * factor / 2)
            new_rect = fitz.Rect(cx - half_w, cy - half_h, cx + half_w, cy + half_h)

            if atype == "Ink":
                strokes = _ink_verts_from_annot(annot)
                if not strokes:
                    return None
                old_rect = fitz.Rect(annot.rect)
                new_strokes = [[_map_point(pt, old_rect, new_rect) for pt in s] for s in strokes]
                try:
                    new_annot = _ink_replace(page, annot, new_strokes)
                except Exception:
                    return None
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return new_rect, new_annot.xref

            if atype == "Line":
                verts = annot.vertices
                if verts and len(verts) >= 2:
                    try:
                        vx0, vy0 = float(verts[0].x), float(verts[0].y)
                        vx1, vy1 = float(verts[1].x), float(verts[1].y)
                    except (AttributeError, TypeError):
                        vx0, vy0 = float(verts[0][0]), float(verts[0][1])
                        vx1, vy1 = float(verts[1][0]), float(verts[1][1])
                    p1 = _map_point(fitz.Point(vx0, vy0), r, new_rect)
                    p2 = _map_point(fitz.Point(vx1, vy1), r, new_rect)
                    new_annot = _line_replace(page, annot, [p1, p2])
                    self._history = [
                        (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                        for (p, x) in self._history
                    ]
                    self._visual_rects.pop(xref, None)
                    return new_rect, new_annot.xref

            rotation = self._rotations.get(xref, 0.0)
            try:
                _reset_ap(annot)
                annot.set_rect(new_rect)
                annot.update()
                if rotation:
                    _apply_rot(annot, rotation)
            except Exception:
                return None
            self._visual_rects[annot.xref] = fitz.Rect(new_rect)
            return new_rect, annot.xref
        return None

    def change_annot_width(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        delta: float,
    ) -> int | None:
        """Increase or decrease the stroke width of an annotation by *delta*.

        Returns the (possibly new) xref on success, or None on failure.
        For Line annotations the xref changes because delete+recreate is
        needed to preserve the arrow tip (line_ends).
        """
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref != xref:
                continue
            atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            border = annot.border or {}
            cur_w  = float(border.get("width") or 2)
            new_w  = max(0.5, min(20.0, cur_w + delta))

            if atype == "Ink":
                strokes = _ink_verts_from_annot(annot)
                if not strokes:
                    return None
                try:
                    new_annot = _ink_replace(page, annot, strokes, new_width=new_w)
                except Exception:
                    return None
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return new_annot.xref

            if atype == "Line":
                verts = annot.vertices
                if not verts or len(verts) < 2:
                    return None
                new_verts = []
                for v in verts:
                    try:
                        new_verts.append(fitz.Point(float(v.x), float(v.y)))
                    except (AttributeError, TypeError):
                        new_verts.append(fitz.Point(float(v[0]), float(v[1])))
                try:
                    new_annot = _line_replace(page, annot, new_verts, new_width=new_w)
                except Exception:
                    return None
                self._history = [
                    (p, new_annot.xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                self._rotations.pop(xref, None)
                return new_annot.xref

            if atype == "Square":
                colors = {}
                try:
                    colors = annot.colors or {}
                except Exception:
                    pass
                stroke = colors.get("stroke")
                rect = fitz.Rect(annot.rect)
                rotation = self._rotations.get(xref, 0.0)
                try:
                    page.delete_annot(annot)
                    new_annot = page.add_rect_annot(rect)
                    if stroke is not None:
                        new_annot.set_colors(stroke=stroke)
                    new_annot.set_border(width=new_w)
                    _reset_ap(new_annot)
                    new_annot.update()
                    if rotation:
                        _apply_rot(new_annot, rotation)
                except Exception:
                    return None
                new_xref = new_annot.xref
                self._history = [
                    (p, new_xref) if (p == page_num and x == xref) else (p, x)
                    for (p, x) in self._history
                ]
                self._visual_rects.pop(xref, None)
                if rotation:
                    self._rotations[new_xref] = rotation
                self._rotations.pop(xref, None)
                return new_xref

            rotation = self._rotations.get(xref, 0.0)
            try:
                existing = dict(annot.border or {})
                existing["width"] = new_w
                annot.set_border(existing)
                _reset_ap(annot)
                annot.update()
                if rotation:
                    _apply_rot(annot, rotation)
            except Exception:
                return None
            return xref
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
