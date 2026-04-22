"""Shared constants and tiny helper functions for the PDF viewer."""
from __future__ import annotations

import flet as ft

from .annotations import Tool


# ── Toolbar / layout colours ──────────────────────────────────────────────────
_SELECTED_BG  = "#DDEEFF"
_TOOLBAR_BG   = "#F3F3F3"
_ANNOT_BG     = "#EBEBEB"
_DIVIDER_CLR  = "#BDBDBD"
_VIEWER_BG    = "#757575"
_SEL_BAR_BG   = "#FFF9C4"
_SEL_BAR_BDR  = "#F0C800"
_OCR_BOX_CLR  = "#2E7D32"
_OCR_BOX_BG   = "#331B5E20"
_OCR_PANEL_BG = "#F7FBF8"
_PAGE_BG      = "#AAAAAA"   # placeholder grey while page image is not rendered

# ── Page layout ───────────────────────────────────────────────────────────────
_PAGE_GAP        = 16    # vertical gap between pages (px)
_PRELOAD         = 2     # pages to render eagerly on first load
_EVICT_MARGIN    = 3     # viewport heights to keep rendered on each side
_EVICT_THRESHOLD = 400   # scroll px between eviction passes

# ── Tool button definitions ───────────────────────────────────────────────────
_TOOL_DEFS: list[tuple[Tool, str, str, ft.MouseCursor]] = [
    (Tool.CURSOR,    ft.Icons.NEAR_ME,             "Cursor (seleccionar anotación)", ft.MouseCursor.BASIC),
    (Tool.SELECT,    ft.Icons.TEXT_FIELDS,          "Seleccionar texto",              ft.MouseCursor.TEXT),
    (Tool.HIGHLIGHT, ft.Icons.HIGHLIGHT,            "Resaltar",                       ft.MouseCursor.PRECISE),
    (Tool.UNDERLINE, ft.Icons.FORMAT_UNDERLINE,     "Subrayar",                       ft.MouseCursor.PRECISE),
    (Tool.STRIKEOUT, ft.Icons.FORMAT_STRIKETHROUGH, "Tachar",                         ft.MouseCursor.PRECISE),
    (Tool.RECT,      ft.Icons.CROP_DIN,             "Rectángulo",                     ft.MouseCursor.PRECISE),
    (Tool.CIRCLE,    ft.Icons.PANORAMA_FISH_EYE,    "Círculo / Elipse",               ft.MouseCursor.PRECISE),
    (Tool.LINE,      ft.Icons.SHOW_CHART,           "Línea",                          ft.MouseCursor.PRECISE),
    (Tool.ARROW,     ft.Icons.ARROW_FORWARD,        "Flecha",                         ft.MouseCursor.PRECISE),
    (Tool.INK,       ft.Icons.BRUSH,                "Dibujo a mano alzada",           ft.MouseCursor.PRECISE),
]


def _vdivider() -> ft.Container:
    return ft.Container(width=1, height=28, bgcolor=_DIVIDER_CLR)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
