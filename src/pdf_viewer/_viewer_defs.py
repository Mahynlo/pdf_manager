"""Shared constants and tiny helper functions for the PDF viewer."""
from __future__ import annotations

import flet as ft

from .annotations import Tool


# ── Feature flags ─────────────────────────────────────────────────────────────
# Agente IA (panel de análisis con LLM externo). Oculto por ahora mientras se
# perfecciona: con False NO se muestran ni la pestaña "Agente IA" del panel
# lateral ni el botón del agente en la barra de herramientas, así que no hay
# forma de invocarlo desde la UI. El código del agente queda intacto — para
# reactivarlo basta poner esto en True. (Es opt-in igual: requiere API key.)
AGENT_ENABLED = False


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
_PAGE_BG      = "#FFFFFF"   # placeholder "papel" mientras la página no se renderiza
                            # (blanco = se funde con el contenido al cargar; antes
                            # era gris y parecía un bloque de carga al hacer scroll)

# ── Page layout ───────────────────────────────────────────────────────────────
_PAGE_GAP        = 16    # vertical gap between pages (px)
_PRELOAD         = 2     # pages to render eagerly on first load
_EVICT_MARGIN    = 3     # viewport heights to keep rendered on each side
_EVICT_THRESHOLD = 400   # scroll px between eviction passes
_CACHE_KEEP_PAGES  = 5     # keep only N pages rendered around current page
# Virtualización del árbol de controles: cada página arranca como un placeholder
# liviano (sólo dimensiones + número de página) y su árbol pesado (imagen,
# overlays de selección/anotación/OCR/censura, menús y GestureDetector — ~50
# controles) se construye perezosamente al entrar en la ventana visible. Sin
# esto, abrir un PDF de cientos de páginas instanciaba decenas de miles de
# controles de golpe (Python + árbol Flutter) → congelaba la carga y disparaba
# la RAM. Las páginas que se alejan más de _SLOT_TEARDOWN_MARGIN alturas de
# viewport se "desinflan" de vuelta a placeholder para acotar la RAM al recorrer
# documentos grandes. Es mayor que _EVICT_MARGIN para que el slot sobreviva un
# poco más que su imagen y evitar reconstruir al hacer micro-scroll.
_SLOT_TEARDOWN_MARGIN = 6  # viewport heights: más allá, el slot vuelve a placeholder
# Las cachés de texto (rawdict char-level, word bands, blocks, word rects) son
# por página y, sin poda, crecían sin techo al recorrer el documento con el
# cursor — sobrevivían incluso a la suspensión que libera las imágenes. Se
# acotan a una ventana más amplia que el render cache: extraer texto es caro
# (toma _doc_lock) y la lectura normal no debe re-extraer páginas recién vistas.
_TEXT_CACHE_KEEP_PAGES = 15   # páginas de texto a conservar alrededor de la actual
# ── LOD (nivel de detalle) ────────────────────────────────────────────────────
# El tier "preview" rasteriza a una fracción del zoom objetivo: más barato de
# rasterizar y mucho menos textura/RAM (clave en equipos sin GPU). Se usa para
# las páginas vecinas (prefetch) y durante el scroll; al detenerse, la página
# enfocada sube a calidad completa.
_PREVIEW_QUALITY   = 0.66  # preview = esta fracción del zoom objetivo
_PREVIEW_MIN_ZOOM  = 0.4   # piso de legibilidad del preview
_PREVIEW_MAX_ZOOM  = 0.75  # techo absoluto del preview (acota el coste a zoom alto)
_SCROLL_IDLE_DELAY = 0.1   # seconds to wait before rendering full-res after scroll
                           # (bajado de 0.2: la página enfocada se afina a
                           # calidad completa antes tras detener el scroll)

# ── Tool button definitions ───────────────────────────────────────────────────
_TOOL_DEFS: list[tuple[Tool, str, str, ft.MouseCursor]] = [
    (Tool.CURSOR,    ft.Icons.NEAR_ME,             "Seleccionar texto y anotaciones", ft.MouseCursor.BASIC),
    (Tool.HIGHLIGHT, ft.Icons.HIGHLIGHT,            "Resaltar",                        ft.MouseCursor.TEXT),
    (Tool.UNDERLINE, ft.Icons.FORMAT_UNDERLINE,     "Subrayar",                       ft.MouseCursor.TEXT),
    (Tool.STRIKEOUT, ft.Icons.FORMAT_STRIKETHROUGH, "Tachar",                         ft.MouseCursor.TEXT),
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
