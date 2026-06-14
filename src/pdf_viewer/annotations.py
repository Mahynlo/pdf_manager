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
    TEXT      = "text"


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
    Tool.TEXT:      "#40555555",
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
    ("Cian",     (0.0, 0.80, 0.90)),
    ("Verde os.",(0.0, 0.55, 0.0)),
    ("Gris",     (0.5, 0.5,  0.5)),
    ("Negro",    (0.0, 0.0,  0.0)),
]

# Fuentes para la anotación de texto (FreeText). Son las fuentes base PDF
# (Base-14): no requieren incrustar archivos, se renderizan igual en cualquier
# lector y soportan acentos/ñ (codificación WinAnsi). Cada entrada es
# (etiqueta_es, nombre_interno_pymupdf). Cubrir negrita/cursiva con nombres
# distintos es la forma fiable de variar el estilo sin TTF externos.
FREETEXT_FONTS: list[tuple[str, str]] = [
    ("Helvetica",           "helv"),
    ("Helvetica negrita",   "hebo"),
    ("Helvetica cursiva",   "heit"),
    ("Times",               "tiro"),
    ("Times negrita",       "tibo"),
    ("Times cursiva",       "tiit"),
    ("Courier (monoesp.)",  "cour"),
    ("Courier negrita",     "cobo"),
]

# Alineación del párrafo (valor entero que espera add_freetext_annot).
FREETEXT_ALIGN: list[tuple[str, int]] = [
    ("Izquierda", 0),
    ("Centro",    1),
    ("Derecha",   2),
]

# Tamaños de fuente ofrecidos en el editor (pt).
FREETEXT_SIZES: list[int] = [8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48]

# Valores por defecto de una anotación de texto nueva.
DEFAULT_TEXT_FONT  = "helv"
DEFAULT_TEXT_SIZE  = 14
DEFAULT_TEXT_COLOR = (0.0, 0.0, 0.0)
DEFAULT_TEXT_ALIGN = 0


# ── module-level helpers ───────────────────────────────────────────────────────

def _atype(annot: fitz.Annot) -> str:
    """Return the annotation type string (e.g. 'Square', 'Ink', 'Highlight')."""
    t = annot.type
    return t[1] if isinstance(t, (tuple, list)) and len(t) > 1 else ""


def _find_annot_by_xref(page: fitz.Page, xref: int) -> fitz.Annot | None:
    """Return the annotation with the given xref on *page*, or None."""
    for annot in page.annots():
        if annot.xref == xref:
            return annot
    return None


def _rdp_simplify(
    pts: list[tuple[float, float]],
    epsilon: float = 1.5,
) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker polyline simplification.

    Removes points within *epsilon* PDF units of the simplified line so
    Catmull-Rom smoothing operates on fewer, more meaningful vertices —
    smaller PDF ink annotations and faster rendering.
    """
    if len(pts) < 3:
        return list(pts)

    start, end = pts[0], pts[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    line_len = math.hypot(dx, dy)

    max_dist = 0.0
    max_idx  = 0
    for i in range(1, len(pts) - 1):
        if line_len < 1e-9:
            dist = math.hypot(pts[i][0] - start[0], pts[i][1] - start[1])
        else:
            dist = abs(
                dy * pts[i][0] - dx * pts[i][1]
                + end[0] * start[1] - end[1] * start[0]
            ) / line_len
        if dist > max_dist:
            max_dist = dist
            max_idx  = i

    if max_dist <= epsilon:
        return [start, end]

    left  = _rdp_simplify(pts[:max_idx + 1], epsilon)
    right = _rdp_simplify(pts[max_idx:], epsilon)
    return left[:-1] + right  # avoid duplicate midpoint


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


def _char_rects(page: fitz.Page, clip: fitz.Rect) -> list[fitz.Rect]:
    """Extract character bounding boxes within the clipping region."""
    raw_dict = page.get_text("rawdict", clip=clip)
    rects: list[fitz.Rect] = []
    for block in raw_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    if char.get("c", "").strip():
                        rects.append(fitz.Rect(char["bbox"]))
    return rects


def _line_merged_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    """Merge adjacent character rects by visual line for smoother markup appearance."""
    if not rects:
        return []

    sorted_rects = sorted(rects, key=lambda r: (r.y0, r.x0))
    merged: list[fitz.Rect] = []
    current = fitz.Rect(sorted_rects[0])

    for rect in sorted_rects[1:]:
        overlap = min(current.y1, rect.y1) - max(current.y0, rect.y0)
        min_height = min(current.height, rect.height)
        same_line = min_height > 0 and overlap >= min_height * 0.5

        # Prevent merging across massive horizontal gaps (columns / table cells).
        horizontal_gap = rect.x0 - current.x1
        max_gap = current.height * 2.0

        if same_line and horizontal_gap <= max_gap:
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


# ── rotated-page coordinate helpers ────────────────────────────────────────────
# El subsistema interactivo (gestos, overlay) trabaja en espacio de PANTALLA
# (el de la imagen renderizada, que respeta /Rotate). PyMuPDF lee/escribe la
# geometría de las anotaciones en espacio SIN rotar. Estos helpers convierten en
# la frontera de AnnotationManager. Todas las matrices son identidad si la página
# no está rotada (rotation == 0), por lo que no afectan al caso común.

def _to_page_rect(page: fitz.Page, r: fitz.Rect) -> fitz.Rect:
    """Pantalla → espacio sin rotar de la página."""
    return fitz.Rect(r) * page.derotation_matrix


def _to_screen_rect(page: fitz.Page, r: fitz.Rect) -> fitz.Rect:
    """Espacio sin rotar de la página → pantalla."""
    return fitz.Rect(r) * page.rotation_matrix


def _to_page_delta(page: fitz.Page, dx: float, dy: float) -> tuple[float, float]:
    """Transforma un vector de desplazamiento de pantalla a espacio sin rotar
    (sólo la parte lineal de la matriz; la traslación no aplica a un vector)."""
    m  = page.derotation_matrix
    p0 = fitz.Point(0.0, 0.0) * m
    p1 = fitz.Point(dx, dy) * m
    return p1.x - p0.x, p1.y - p0.y


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
        # Redo stack: snapshots of annotations removed by undo, recreated on redo.
        # A new annotation invalidates it (see _push_history).
        self._redo_stack: list[dict] = []
        # Visual (unrotated) rect per annotation xref.
        self._visual_rects: dict[int, fitz.Rect] = {}
        # Rotation in degrees per xref.
        self._rotations: dict[int, float] = {}
        # Propiedades de cada anotación de texto (FreeText) por xref:
        # {"text", "fontname", "fontsize", "color", "align", "fill"}. Se usan
        # para pre-rellenar el editor y para recrear la apariencia al editar
        # (PyMuPDF no expone fontname/fontsize de un FreeText de forma fiable).
        self._text_props: dict[int, dict] = {}

    # ── internal helpers ────────────────────────────────────────────────────────

    def _push_history(self, page_num: int, xref: int) -> None:
        """Record a newly created annotation and invalidate the redo stack."""
        self._history.append((page_num, xref))
        self._redo_stack.clear()

    def _remap_xref(self, page_num: int, old_xref: int, new_xref: int) -> None:
        """Update the history entry for (page_num, old_xref) to new_xref in-place."""
        for i, (p, x) in enumerate(self._history):
            if p == page_num and x == old_xref:
                self._history[i] = (page_num, new_xref)

    def get_visual_rect(self, xref: int) -> fitz.Rect | None:
        vr = self._visual_rects.get(xref)
        return fitz.Rect(vr) if vr is not None else None

    def get_rotation(self, xref: int) -> float:
        return float(self._rotations.get(xref, 0.0))

    # ── tool selection ──────────────────────────────────────────────────────────

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool

    @property
    def overlay_color(self) -> str:
        return OVERLAY_COLOR.get(self.tool, "#40808080")

    # ── drag lifecycle ──────────────────────────────────────────────────────────

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
        # Las coords de arrastre llegan en espacio de PANTALLA (rotado). Las APIs
        # de PyMuPDF (get_text(clip), add_*_annot) trabajan en espacio SIN rotar.
        # derotation_matrix es identidad si la página no está rotada.
        derot = page.derotation_matrix

        # ── text selection (copy / deferred annotation) ──────────────────────
        if self.tool == Tool.SELECT:
            # last_*rect se conservan en PANTALLA (el resto del código y el
            # fallback OCR los usan en ese espacio); sólo el clip se des-rota.
            self.last_select_rect = rect   # always saved (OCR fallback uses this)
            text = page.get_text("text", clip=rect * derot).strip()
            if text:
                self.last_rect = rect
            return False, text or None

        # ── text markup ──────────────────────────────────────────────────────
        if self.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            rects = _line_merged_rects(_char_rects(page, rect * derot))
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
            self._push_history(page_num, annot.xref)
            return True, None

        # ── shape tools ──────────────────────────────────────────────────────
        if self.tool == Tool.RECT:
            annot = page.add_rect_annot(rect * derot)
            annot.set_colors(stroke=STROKE_COLOR[Tool.RECT])
            annot.set_border(width=2)
            annot.update()
            self._push_history(page_num, annot.xref)
            return True, None

        if self.tool == Tool.CIRCLE:
            annot = page.add_circle_annot(rect * derot)
            annot.set_colors(stroke=STROKE_COLOR[Tool.CIRCLE])
            annot.set_border(width=2)
            annot.update()
            self._push_history(page_num, annot.xref)
            return True, None

        if self.tool == Tool.LINE:
            if raw_start is None or raw_end is None:
                return False, None
            p1 = fitz.Point(*raw_start) * derot
            p2 = fitz.Point(*raw_end) * derot
            if math.hypot(p2.x - p1.x, p2.y - p1.y) < 5:
                return False, None
            annot = page.add_line_annot(p1, p2)
            annot.set_colors(stroke=STROKE_COLOR[Tool.LINE])
            annot.set_border(width=2)
            annot.update()
            self._push_history(page_num, annot.xref)
            return True, None

        if self.tool == Tool.ARROW:
            if raw_start is None or raw_end is None:
                return False, None
            p1 = fitz.Point(*raw_start) * derot
            p2 = fitz.Point(*raw_end) * derot
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
            self._push_history(page_num, annot.xref)
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
        # Simplify with RDP before smoothing: fewer input points → fewer output
        # vertices, smaller PDF, faster rendering. Quality is preserved because
        # RDP removes only collinear/near-collinear points.
        simplified = _rdp_simplify(pdf_points) if len(pdf_points) >= 3 else list(pdf_points)
        smoothed   = _catmull_rom(simplified)  if len(simplified)  >= 3 else simplified
        page  = doc[page_num]
        # Puntos en espacio de PANTALLA → des-rotar al espacio de la página
        # (identidad si rotation == 0).
        derot     = page.derotation_matrix
        smoothed  = [tuple(fitz.Point(x, y) * derot) for x, y in smoothed]
        annot = page.add_ink_annot([smoothed])
        annot.set_colors(stroke=STROKE_COLOR[Tool.INK])
        annot.set_border(width=2)
        annot.update()
        self._push_history(page_num, annot.xref)
        return True

    # ── text (FreeText) annotation ───────────────────────────────────────────────

    def take_text_rect(self) -> fitz.Rect | None:
        """Devuelve la caja de arrastre pendiente (espacio de PANTALLA) para la
        herramienta TEXT y resetea el estado de arrastre.

        Si no hubo un arrastre real (sólo un clic), devuelve una caja por
        defecto anclada en el punto inicial. El editor luego ajusta el tamaño;
        ``commit_text`` garantiza una caja mínima usable.
        """
        rect  = self._last_rect
        start = self._raw_start
        self._start     = None
        self._last_rect = None
        self._raw_start = None
        self._raw_end   = None
        if rect is not None and (rect.width >= 8 or rect.height >= 8):
            return fitz.Rect(rect)
        if start is not None:
            x, y = start
            return fitz.Rect(x, y, x + 200, y + 40)
        return None

    @staticmethod
    def _normalize_text_props(
        text: str,
        fontname: str | None,
        fontsize: float | None,
        color: tuple[float, float, float] | None,
        align: int | None,
        fill: tuple[float, float, float] | None,
    ) -> dict:
        return {
            "text":     text,
            "fontname": fontname or DEFAULT_TEXT_FONT,
            "fontsize": float(fontsize or DEFAULT_TEXT_SIZE),
            "color":    tuple(color) if color is not None else DEFAULT_TEXT_COLOR,
            "align":    int(align) if align is not None else DEFAULT_TEXT_ALIGN,
            "fill":     tuple(fill) if fill is not None else None,
        }

    def _make_freetext(self, page: fitz.Page, rect: fitz.Rect, props: dict) -> fitz.Annot:
        """Crea un FreeText en *rect* (espacio SIN rotar) con *props* y construye
        su apariencia. Centraliza el patrón usado por crear/editar/recrear."""
        annot = page.add_freetext_annot(
            rect, props["text"],
            fontsize=props["fontsize"],
            fontname=props["fontname"],
            text_color=props["color"],
            fill_color=props["fill"],
            align=props["align"],
        )
        # update() reconstruye el appearance stream; sin esto el texto/color no
        # siempre se reflejan al renderizar (mismo motivo que en los markup).
        annot.update(
            fontsize=props["fontsize"],
            fontname=props["fontname"],
            text_color=props["color"],
            fill_color=props["fill"],
        )
        return annot

    def commit_text(
        self,
        doc: fitz.Document,
        page_num: int,
        rect: fitz.Rect,
        text: str,
        fontname: str | None = None,
        fontsize: float | None = None,
        color: tuple[float, float, float] | None = None,
        align: int | None = None,
        fill: tuple[float, float, float] | None = None,
    ) -> int | None:
        """Crea una anotación de texto en *rect* (espacio de PANTALLA).

        Devuelve el xref de la anotación creada, o None si no hay texto.
        """
        text = (text or "").strip()
        if not text:
            return None
        page  = doc[page_num]
        # rect llega en pantalla (rotado) → des-rotar al espacio de la página
        # (identidad si rotation == 0), como hacen el resto de herramientas.
        r = fitz.Rect(rect) * page.derotation_matrix
        r.normalize()
        # Caja mínima usable: si es muy pequeña el texto se recortaría.
        if r.width < 40:
            r.x1 = r.x0 + 40
        if r.height < 20:
            r.y1 = r.y0 + 20
        props = self._normalize_text_props(text, fontname, fontsize, color, align, fill)
        annot = self._make_freetext(page, r, props)
        self._text_props[annot.xref] = props
        self._push_history(page_num, annot.xref)
        return annot.xref

    def edit_text(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        text: str,
        fontname: str | None = None,
        fontsize: float | None = None,
        color: tuple[float, float, float] | None = None,
        align: int | None = None,
        fill: tuple[float, float, float] | None = None,
    ) -> int | None:
        """Edita una anotación de texto existente (texto/fuente/tamaño/color/
        alineación) conservando su caja y rotación.

        Se borra y recrea para forzar el refresco del appearance stream
        (``update`` no siempre lo refresca; mismo patrón que ``_line_replace``).
        Devuelve el nuevo xref, o None en fallo.
        """
        text = (text or "").strip()
        if not text:
            return None
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None or _atype(annot) != "FreeText":
            return None
        rect     = fitz.Rect(annot.rect)            # ya en espacio sin rotar
        rotation = self._rotations.get(xref, 0.0)
        props    = self._normalize_text_props(text, fontname, fontsize, color, align, fill)

        page.delete_annot(annot)
        new_annot = self._make_freetext(page, rect, props)
        if rotation:
            _apply_rot(new_annot, rotation)

        new_xref = new_annot.xref
        self._remap_xref(page_num, xref, new_xref)
        self._text_props.pop(xref, None)
        self._rotations.pop(xref, None)
        self._visual_rects.pop(xref, None)
        self._text_props[new_xref] = props
        if rotation:
            self._rotations[new_xref] = rotation
        return new_xref

    def get_text_props(self, xref: int) -> dict | None:
        """Devuelve una copia de las propiedades de texto de *xref*, o None."""
        props = self._text_props.get(xref)
        return dict(props) if props is not None else None

    # ── undo ─────────────────────────────────────────────────────────────────────

    def undo_last(self, doc: fitz.Document) -> int | None:
        """Remove the most recently added annotation (any page).

        Captures a snapshot of the annotation before deleting so it can be
        recreated with :meth:`redo_last`.

        Returns the page number it was on, or None if nothing to undo.
        """
        if not self._history:
            return None
        page_num, xref = self._history[-1]
        page = doc[page_num]
        for annot in page.annots():
            if annot.xref == xref:
                snap = self._snapshot_annot(annot)
                if snap is not None:
                    snap["page_num"] = page_num
                    self._redo_stack.append(snap)
                page.delete_annot(annot)
                self._history.pop()
                return page_num
        self._history.pop()  # xref gone already; clean up history
        return page_num

    # ── redo ───────────────────────────────────────────────────────────────────

    def redo_last(self, doc: fitz.Document) -> int | None:
        """Recreate the annotation most recently removed by :meth:`undo_last`.

        Returns the page number it was recreated on, or None if nothing to redo.
        """
        if not self._redo_stack:
            return None
        snap = self._redo_stack.pop()
        page_num = snap.get("page_num", 0)
        try:
            page = doc[page_num]
        except Exception:
            return None
        annot = self._recreate_annot(page, snap)
        if annot is None:
            return None
        # Re-add directly to history (do NOT clear the redo stack here).
        self._history.append((page_num, annot.xref))
        return page_num

    def _snapshot_annot(self, annot: fitz.Annot) -> dict | None:
        """Serialise an annotation's geometry and style into a plain dict."""
        try:
            atype = annot.type[1]
        except Exception:
            return None
        data: dict = {"type": atype, "rect": tuple(annot.rect)}
        try:
            colors = annot.colors or {}
            data["stroke"] = colors.get("stroke")
            data["fill"]   = colors.get("fill")
        except Exception:
            data["stroke"] = data["fill"] = None
        try:
            data["width"] = (annot.border or {}).get("width", 2) or 2
        except Exception:
            data["width"] = 2
        try:
            data["opacity"] = annot.opacity
        except Exception:
            data["opacity"] = None

        if atype in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
            raw = annot.vertices or []
            pts = []
            for p in raw:
                try:
                    pts.append(fitz.Point(float(p[0]), float(p[1])))
                except (TypeError, IndexError):
                    pts.append(fitz.Point(float(p.x), float(p.y)))
            quads = [
                fitz.Quad(pts[i], pts[i + 1], pts[i + 2], pts[i + 3])
                for i in range(0, len(pts) - 3, 4)
            ]
            data["quads"] = quads or None
        elif atype == "Line":
            raw = annot.vertices or []
            data["points"] = [tuple(p) for p in raw] if raw else None
            try:
                le = annot.line_ends
                data["line_ends"] = (int(le[0]), int(le[1])) if le else (0, 0)
            except Exception:
                data["line_ends"] = (0, 0)
        elif atype == "Ink":
            strokes = _ink_verts_from_annot(annot)
            data["strokes"] = (
                [[tuple(p) for p in s] for s in strokes] if strokes else None
            )
        elif atype == "FreeText":
            # El texto/estilo no se leen de forma fiable del annot; se toman del
            # registro propio (fallback al contenido embebido para el texto).
            props = self._text_props.get(annot.xref)
            if props is None:
                try:
                    content = annot.info.get("content", "")
                except Exception:
                    content = ""
                props = self._normalize_text_props(content, None, None, None, None, None)
            data["text_props"] = dict(props)
        # Square / Circle are fully described by rect.
        return data

    def _recreate_annot(self, page: fitz.Page, data: dict) -> fitz.Annot | None:
        """Rebuild an annotation from a :meth:`_snapshot_annot` dict."""
        atype = data.get("type")
        try:
            if atype == "Highlight":
                if not data.get("quads"):
                    return None
                annot = page.add_highlight_annot(data["quads"])
            elif atype == "Underline":
                if not data.get("quads"):
                    return None
                annot = page.add_underline_annot(data["quads"])
            elif atype == "StrikeOut":
                if not data.get("quads"):
                    return None
                annot = page.add_strikeout_annot(data["quads"])
            elif atype == "Squiggly":
                if not data.get("quads"):
                    return None
                annot = page.add_squiggly_annot(data["quads"])
            elif atype == "Square":
                annot = page.add_rect_annot(fitz.Rect(data["rect"]))
            elif atype == "Circle":
                annot = page.add_circle_annot(fitz.Rect(data["rect"]))
            elif atype == "Line":
                pts = data.get("points")
                if not pts or len(pts) < 2:
                    return None
                annot = page.add_line_annot(fitz.Point(pts[0]), fitz.Point(pts[1]))
                le = data.get("line_ends", (0, 0))
                if le != (0, 0):
                    try:
                        annot.set_line_ends(*le)
                    except Exception:
                        pass
            elif atype == "Ink":
                strokes = data.get("strokes")
                if not strokes:
                    return None
                annot = page.add_ink_annot(strokes)
            elif atype == "FreeText":
                props = data.get("text_props")
                if not props or not (props.get("text") or "").strip():
                    return None
                annot = self._make_freetext(page, fitz.Rect(data["rect"]), props)
                self._text_props[annot.xref] = dict(props)
                return annot  # apariencia/estilo ya aplicados por _make_freetext
            else:
                return None
        except Exception:
            return None

        stroke, fill = data.get("stroke"), data.get("fill")
        if stroke is not None or fill is not None:
            try:
                annot.set_colors(stroke=stroke, fill=fill)
            except Exception:
                pass
        # Markup annots (Highlight/Underline/StrikeOut/Squiggly) reject set_border.
        if atype not in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
            try:
                annot.set_border(width=data.get("width", 2))
            except Exception:
                pass
        if data.get("opacity") is not None:
            try:
                annot.set_opacity(data["opacity"])
            except Exception:
                pass
        annot.update()
        return annot

    def undo(self, doc: fitz.Document, page_num: int | None = None) -> bool:
        """Compatibility wrapper used by viewer code."""
        return self.undo_last(doc) is not None

    # ── annotation hit-test & editing ─────────────────────────────────────────────

    def get_annot_at(self, page: fitz.Page, x: float, y: float) -> fitz.Annot | None:
        """Return the annotation at PDF point (x, y), preferring shapes over markup.

        (x, y) llega en espacio de PANTALLA (rotado); ``annot.rect`` de PyMuPDF
        está SIN rotar, así que des-rotamos el punto antes del hit-test
        (identidad si la página no está rotada)."""
        _MARKUP = {"Highlight", "Underline", "StrikeOut", "Squiggly"}
        pt = fitz.Point(x, y) * page.derotation_matrix
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
            if _atype(annot) in _MARKUP:
                markup_result = annot
            else:
                shape_result = annot
        # Shapes (rect/circle/line/etc.) take priority over markup overlays so
        # that a shape drawn under a highlight/underline remains selectable.
        return shape_result if shape_result is not None else markup_result

    def delete_annot(self, doc: fitz.Document, page_num: int, xref: int) -> bool:
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return False
        page.delete_annot(annot)
        self._history = [(p, x) for p, x in self._history if x != xref]
        self._visual_rects.pop(xref, None)
        self._rotations.pop(xref, None)
        self._text_props.pop(xref, None)
        return True

    def change_annot_color(
        self,
        doc: fitz.Document,
        page_num: int,
        xref: int,
        color: tuple[float, float, float],
    ) -> bool:
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return False
        rotation = self._rotations.get(xref, 0.0)
        # FreeText: "color" es el color del texto, no el trazo del borde.
        if _atype(annot) == "FreeText":
            _reset_ap(annot)
            annot.update(text_color=color)
            props = self._text_props.get(xref)
            if props is not None:
                props["color"] = tuple(color)
            if rotation:
                _apply_rot(annot, rotation)
            return True
        _reset_ap(annot)
        annot.set_colors(stroke=color)
        annot.update()
        if rotation:
            _apply_rot(annot, rotation)
        return True

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
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return None

        # El delta llega en pantalla; la geometría interna está sin rotar.
        dx, dy = _to_page_delta(page, dx, dy)

        at = _atype(annot)

        if at == "Ink":
            strokes = _ink_verts_from_annot(annot)
            if not strokes:
                return None
            new_strokes = [[fitz.Point(pt.x + dx, pt.y + dy) for pt in s] for s in strokes]
            try:
                new_annot = _ink_replace(page, annot, new_strokes)
            except Exception:
                return None
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return _to_screen_rect(page, new_annot.rect), new_annot.xref, 0.0

        if at in ("Line", "Polygon", "PolyLine"):
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
            new_annot = _line_replace(page, annot, new_verts) if at == "Line" else _polygon_replace(page, annot, new_verts, at)
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return _to_screen_rect(page, new_annot.rect), new_annot.xref, 0.0

        rotation = self._rotations.get(xref, 0.0)
        cached   = self._visual_rects.get(xref)
        base     = cached if cached is not None else fitz.Rect(annot.rect)
        new_visual = fitz.Rect(
            base.x0 + dx, base.y0 + dy,
            base.x1 + dx, base.y1 + dy,
        )
        try:
            _reset_ap(annot)
            annot.set_rect(new_visual)
            annot.update()
            if rotation:
                _apply_rot(annot, rotation)
        except Exception:
            return None
        self._visual_rects[annot.xref] = fitz.Rect(new_visual)
        return _to_screen_rect(page, new_visual), annot.xref, rotation

    @staticmethod
    def _translate_snapshot(snap: dict, dx: float, dy: float) -> None:
        """Desplaza in-place la geometría de un snapshot por (dx, dy) sin rotar."""
        r = snap.get("rect")
        if r:
            snap["rect"] = (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
        pts = snap.get("points")
        if pts:
            snap["points"] = [(p[0] + dx, p[1] + dy) for p in pts]
        strokes = snap.get("strokes")
        if strokes:
            snap["strokes"] = [[(x + dx, y + dy) for (x, y) in s] for s in strokes]
        quads = snap.get("quads")
        if quads:
            m = fitz.Matrix(1, 0, 0, 1, dx, dy)
            snap["quads"] = [q * m for q in quads]

    def move_annot_to_page(
        self,
        doc: fitz.Document,
        src_pn: int,
        xref: int,
        dst_pn: int,
        new_rect_unrot: fitz.Rect,
    ) -> tuple[fitz.Rect, int] | None:
        """Mueve una anotación de ``src_pn`` a ``dst_pn``.

        Reubica su geometría (sin rotar) para que su caja quede en
        ``new_rect_unrot`` en la página destino. Recrea en destino ANTES de
        borrar en origen, de modo que un fallo no pierda la anotación.
        Devuelve ``(new_rect_unrot, new_xref)`` o ``None``.
        """
        if src_pn == dst_pn:
            return None
        try:
            src   = doc[src_pn]
            annot = _find_annot_by_xref(src, xref)
            if annot is None:
                return None
            snap = self._snapshot_annot(annot)
            if snap is None or not snap.get("rect"):
                return None
            old = snap["rect"]
            self._translate_snapshot(
                snap, new_rect_unrot.x0 - old[0], new_rect_unrot.y0 - old[1]
            )
            dst = doc[dst_pn]
            new_annot = self._recreate_annot(dst, snap)
            if new_annot is None:
                return None
            # Sólo tras recrear con éxito se borra el original.
            src.delete_annot(annot)
            new_xref = new_annot.xref
            self._history = [
                (dst_pn, new_xref) if (p == src_pn and x == xref) else (p, x)
                for p, x in self._history
            ]
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return fitz.Rect(new_annot.rect), new_xref
        except Exception:
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
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return False
        flag = fitz.PDF_ANNOT_IS_HIDDEN
        cur  = annot.flags
        new  = (cur | flag) if hidden else (cur & ~flag)
        if new != cur:
            rotation = self._rotations.get(xref, 0.0)
            _reset_ap(annot)
            annot.set_flags(new)
            annot.update()
            if rotation:
                _apply_rot(annot, rotation)
        return True

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
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return None

        # new_rect llega en pantalla; la geometría interna está sin rotar.
        new_rect = _to_page_rect(page, new_rect)

        at = _atype(annot)

        if at == "Ink":
            strokes = _ink_verts_from_annot(annot)
            if not strokes:
                return None
            old_rect    = annot.rect
            new_strokes = [[_map_point(pt, old_rect, new_rect) for pt in s] for s in strokes]
            try:
                new_annot = _ink_replace(page, annot, new_strokes)
            except Exception:
                return None
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return _to_screen_rect(page, new_annot.rect), new_annot.xref, 0.0

        if at in ("Line", "Polygon", "PolyLine"):
            verts = annot.vertices
            if not verts or len(verts) < 2:
                return None
            old_rect  = annot.rect
            new_verts = []
            for v in verts:
                try:
                    vx, vy = float(v[0]), float(v[1])
                except (TypeError, IndexError):
                    vx, vy = float(v.x), float(v.y)
                new_verts.append(_map_point(fitz.Point(vx, vy), old_rect, new_rect))
            new_annot = _line_replace(page, annot, new_verts) if at == "Line" else _polygon_replace(page, annot, new_verts, at)
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return _to_screen_rect(page, new_annot.rect), new_annot.xref, 0.0

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
        return _to_screen_rect(page, new_rect), annot.xref, rotation

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
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return None

        at = _atype(annot)

        if at in ("Line", "Polygon", "PolyLine"):
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
            new_annot = _polygon_replace(page, annot, new_verts, at)
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return fitz.Rect(new_annot.rect), new_annot.xref, 0.0

        # Square / Circle / FreeText: visually rotate via the Form
        # XObject's /Matrix (apn_matrix). PyMuPDF's native set_rotation
        # stores /Rotate but MuPDF does not render Square/Circle at
        # arbitrary angles — only bbox expansion happens. We instead
        # keep /Rect equal to the visual rect and set apn_matrix so the
        # appearance is rotated around the rect's centre.
        current      = self._rotations.get(xref, 0.0)
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
            _reset_ap(annot)
            annot.set_rect(vr)
            annot.update()
            _apply_rot(annot, new_rotation)
        except Exception:
            return None
        self._visual_rects[annot.xref] = fitz.Rect(vr)
        self._rotations[annot.xref]    = float(new_rotation)
        return vr, annot.xref, float(new_rotation)

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
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return None

        at = _atype(annot)

        # Use the cached pre-rotation rect when available so scale is
        # applied to the user-facing shape, not PyMuPDF's expanded bbox.
        cached = self._visual_rects.get(xref)
        r      = fitz.Rect(cached) if cached is not None else fitz.Rect(annot.rect)
        cx     = (r.x0 + r.x1) / 2
        cy     = (r.y0 + r.y1) / 2
        half_w = max(1.0, r.width  * factor / 2)
        half_h = max(1.0, r.height * factor / 2)
        new_rect = fitz.Rect(cx - half_w, cy - half_h, cx + half_w, cy + half_h)

        if at == "Ink":
            strokes = _ink_verts_from_annot(annot)
            if not strokes:
                return None
            old_rect    = fitz.Rect(annot.rect)
            new_strokes = [[_map_point(pt, old_rect, new_rect) for pt in s] for s in strokes]
            try:
                new_annot = _ink_replace(page, annot, new_strokes)
            except Exception:
                return None
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return _to_screen_rect(page, new_rect), new_annot.xref

        if at == "Line":
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
                self._remap_xref(page_num, xref, new_annot.xref)
                self._visual_rects.pop(xref, None)
                return _to_screen_rect(page, new_rect), new_annot.xref

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
        return _to_screen_rect(page, new_rect), annot.xref

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
        page  = doc[page_num]
        annot = _find_annot_by_xref(page, xref)
        if annot is None:
            return None

        at     = _atype(annot)
        border = annot.border or {}
        cur_w  = float(border.get("width") or 2)
        new_w  = max(0.5, min(20.0, cur_w + delta))

        if at == "Ink":
            strokes = _ink_verts_from_annot(annot)
            if not strokes:
                return None
            try:
                new_annot = _ink_replace(page, annot, strokes, new_width=new_w)
            except Exception:
                return None
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return new_annot.xref

        if at == "Line":
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
            self._remap_xref(page_num, xref, new_annot.xref)
            self._visual_rects.pop(xref, None)
            self._rotations.pop(xref, None)
            return new_annot.xref

        if at == "Square":
            colors = {}
            try:
                colors = annot.colors or {}
            except Exception:
                pass
            stroke   = colors.get("stroke")
            rect     = fitz.Rect(annot.rect)
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
            self._remap_xref(page_num, xref, new_xref)
            if rotation:
                self._rotations[new_xref] = rotation
            self._visual_rects.pop(xref, None)
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

    # ── deferred text annotation ──────────────────────────────────────────────

    def apply_text_tool(self, doc: fitz.Document, page_num: int, tool: Tool, rects: list[fitz.Rect] | None = None, rects_are_final: bool = False) -> bool:
        """Apply a markup annotation to the area saved from the last SELECT drag, or to explicit rects.

        ``rects`` y ``last_rect`` llegan en espacio de PANTALLA (rotado); aquí se
        des-rotan al espacio de la página antes de extraer/crear los markup.
        derotation_matrix es identidad si la página no está rotada.

        ``rects_are_final``: el llamador ya fusionó (``_line_merged_rects``) en el
        marco de lectura correcto y convirtió los rects al espacio SIN rotar de la
        página. Necesario en páginas rotadas con OCR, donde el texto es horizontal
        en PANTALLA: fusionar tras des-rotar agruparía mal (el texto queda de lado
        en el espacio sin rotar) → bandas. Ver ``_text_sel_apply``.
        """
        page = doc[page_num]
        derot = page.derotation_matrix
        if rects is None:
            if self.last_rect is None:
                return False
            rects = _line_merged_rects(_char_rects(page, fitz.Rect(self.last_rect) * derot))
            if not rects:
                self.last_rect = None
                return False
        elif rects_are_final:
            if not rects:
                return False
            # ya fusionados y en espacio sin rotar → usar tal cual
        else:
            if not rects:
                return False
            rects = _line_merged_rects([fitz.Rect(r) * derot for r in rects])

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
        self._push_history(page_num, annot.xref)
        self.last_rect = None
        return True
