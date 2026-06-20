"""Rendering, navigation, zoom and save behaviour for PDFViewerTab.

## Virtualización del árbol de controles (slots perezosos)

El visor usa scroll continuo: una fila (`ft.Row`) por página dentro de un
`ft.Column`. Construir el árbol pesado de cada página (imagen, overlays de
selección/anotación/OCR/censura, menús flotantes y `GestureDetector` — ~50
controles) para TODAS las páginas al abrir el PDF era inviable en documentos
grandes: ~40.000 controles para 800 páginas → congelaba la carga y disparaba la
RAM (Python + árbol Flutter). Por eso el árbol se **virtualiza**:

  · Cada página arranca como un **placeholder** liviano (`_make_placeholder`):
    un `Container` con las dimensiones correctas (para que el scrollbar mida
    bien) y el número de página tenue. Construir esto para N páginas es O(N)
    barato.
  · El árbol pesado se construye **bajo demanda** (`_build_page_slot`) cuando la
    página entra en la ventana visible, y se **desinfla** de vuelta a placeholder
    (`_teardown_page_slot`) cuando se aleja más de `_SLOT_TEARDOWN_MARGIN`
    alturas de viewport (gancho en `_on_scroll_idle`). Así los slots vivos
    quedan acotados a una ventana, sin importar cuántas páginas tenga el PDF.
  · `_ensure_page_built` / `_is_built` son el contrato: `_render_page_slot`
    materializa el slot antes de rasterizar. `_page_is_active` protege de
    desinflar páginas con estado interactivo vivo (actual, selección de
    anotación, rango de texto, popup, tinta).

INVARIANTE para el resto de mixins: las listas por página (`_page_images`,
`_sel_overlays`, `_ocr_overlays`, …) tienen longitud == nº de páginas pero
contienen **None** para slots no construidos. Todo acceso indexado o iteración
sobre esas listas debe tolerar None (saltarlo). Al materializarse un slot,
`_build_page_slot` re-aplica los overlays dependientes de página que estuvieran
activos (cajas OCR, preview de censura, overlay de selección).

## Render por niveles (LOD) y scroll

`_render_page_slot` rasteriza en hilo de fondo (acotado por un `Semaphore(6)`
global). Dos tiers: COMPLETO (zoom objetivo) y PREVIEW (fracción del zoom, ~1/4
del coste). Durante un fling rápido se renderiza PREVIEW (las hojas no quedan en
blanco); al detenerse, `_on_scroll_idle` las sube a COMPLETO (swap gapless, sin
parpadeo a blanco). `_evict_distant` descarta las imágenes fuera de la ventana
para acotar RAM/VRAM; el render cache (`PageRenderCache`) y las cachés de texto
por página también se podan a una ventana.

Conversión de coordenadas viewport↔página (`_get_global_y` /
`_get_page_and_local_y`, en `_gesture_mixin`) usa los offsets acumulados
cacheados (`_page_cum_offsets`) → O(1) / O(log N), no un barrido lineal por
evento de arrastre.
"""
from __future__ import annotations

import bisect
import math
import threading
import time
from pathlib import Path

import flet as ft
import flet.canvas as cv
import fitz
from pdf_security import PDFSecurityManager

from .annotations import Tool
from .renderer import BASE_SCALE, ZOOM_LEVELS, render_page, _RENDER_SEM
from ._viewer_defs import (
    _PAGE_BG, _PAGE_GAP, _PRELOAD, _EVICT_MARGIN, _EVICT_THRESHOLD,
    _CACHE_KEEP_PAGES, _TEXT_CACHE_KEEP_PAGES, _SLOT_TEARDOWN_MARGIN,
    _PREVIEW_MAX_ZOOM, _PREVIEW_QUALITY, _PREVIEW_MIN_ZOOM,
    _SCROLL_IDLE_DELAY, _SELECTED_BG,
    _SINGLE_NAV_COOLDOWN, _SINGLE_EDGE_EPS, _SINGLE_NAV_CONFIRM,
)


class _RenderMixin:
    """Page rendering, viewport management, navigation and zoom."""

    # ── per-page control factory ──────────────────────────────────────────────

    def _rebuild_scroll_content(self, scroll_back: bool = True) -> None:
        """(Re)build all page slot controls. Called on init and after zoom/rotate."""
        self._render_gen    += 1
        self._rendering      = set()
        self._rendering_preview = set()
        self._previewed         = set()
        self._render_tokens     = {}
        self._last_evict_px  = -9999.0

        with self._doc_lock:
            total = len(self.doc)
            page_dims = [
                (int(self.doc[pn].rect.width  * BASE_SCALE * self.zoom),
                 int(self.doc[pn].rect.height * BASE_SCALE * self.zoom))
                for pn in range(total)
            ]

        # Ancho del Column: máximo entre el viewport disponible (para que las
        # páginas queden centradas cuando caben) y el ancho de la página al zoom
        # actual + margen (para activar el scroll horizontal cuando no caben).
        if page_dims:
            self._update_scroll_column_width(max(w for w, _ in page_dims))

        # ── Fast-resize path ──────────────────────────────────────────────────
        # When the page count is unchanged (zoom / rotate), reuse all existing
        # Flet controls and only update their dimensions + clear stale images.
        # This avoids recreating ~20 controls × N pages on every zoom change.
        if len(self._page_images) == total and total > 0:
            self._rendered       = set()
            self._previewed      = set()
            self._selected       = None
            self._page_words     = {}
            self._text_sel_sig   = {}
            self._text_sel_active_pages = set()
            self._text_sel_start_pn = None
            self._text_sel_end_pn   = None
            self._text_sel_text  = ""
            self._text_sel_start_pdf    = None
            self._text_sel_end_pdf      = None
            self._text_sel_sel_rect     = None
            self._annot_popup_pn        = None
            self._smart_text_sel_active = False
            self._sel_drag_handle       = None
            self._rendering             = set()
            self._rendering_preview     = set()
            self._render_tokens         = {}

            cum = 0.0
            for pn, (w, h) in enumerate(page_dims):
                # Geometría primero: el scrollbar debe medir bien aunque la
                # página siga siendo un placeholder no construido.
                self._page_cum_offsets[pn] = cum
                self._page_heights[pn]     = float(h)
                cum += h + _PAGE_GAP

                # Páginas no construidas: sólo reescalar su placeholder.
                if not self._is_built(pn):
                    ph = self._page_placeholders[pn] if pn < len(self._page_placeholders) else None
                    if ph is not None:
                        ph.width  = w
                        ph.height = h
                    continue

                img     = self._page_images[pn]
                slot    = self._page_slots[pn]
                ink     = self._ink_canvases[pn]
                load_ov = self._loading_overlays[pn]

                # Si la página ya estaba renderizada, mantenerla visible como
                # preview escalada (fit=CONTAIN) mientras llega el nuevo render.
                # El worker restaura fit=NONE al terminar.
                has_old = bool(img.src or img.src_base64)
                if has_old:
                    img.fit = ft.ImageFit.CONTAIN
                    img.visible = True
                    slot.bgcolor = _PAGE_BG
                else:
                    img.visible = False
                    slot.bgcolor = _PAGE_BG
                img.width  = w
                img.height = h
                slot.width  = w
                slot.height = h
                ink.width  = w
                ink.height = h

                load_ov.width   = w
                load_ov.height  = h
                load_ov.visible = not has_old

                self._drag_overlays[pn].visible   = False
                self._sel_overlays[pn].visible    = False
                self._text_sel_popups[pn].visible = False
                self._annot_popups[pn].visible    = False

                self._ocr_overlays[pn].controls      = []
                self._text_sel_layers[pn].controls   = []
                self._redact_overlays[pn].controls   = []
                if getattr(self, "_ocr_show_boxes", False) and pn in self._ocr_by_page:
                    self._render_ocr_boxes(pn=pn)

            display_mode = getattr(self, "_display_mode", "continuous")
            if display_mode == "single":
                for i, row in enumerate(self._page_rows):
                    row.visible = (i == self.current_page)
            elif display_mode == "double":
                pair_start = (self.current_page // 2) * 2
                for i, row in enumerate(self._page_rows):
                    row.visible = (i == pair_start or i == pair_start + 1)
            else:
                for row in self._page_rows:
                    row.visible = True

            try:
                self.viewer_scroll.update()
            except Exception:
                pass

            if display_mode in ("single", "double"):
                pair_start = (self.current_page // 2) * 2 if display_mode == "double" else self.current_page
                for p in range(pair_start, min(pair_start + 2, total)):
                    self._render_page_slot(p)
            else:
                for p in range(min(total, 1 + _PRELOAD)):
                    self._render_page_slot(p)

            if scroll_back and self._page_cum_offsets and display_mode == "continuous":
                try:
                    self.viewer_scroll.scroll_to(
                        offset=self._page_cum_offsets[self.current_page], duration=0,
                    )
                except Exception:
                    pass
            return
        # ── Full rebuild ──────────────────────────────────────────────────────
        # Page indices may have shifted (insert/delete/move), so cached images
        # are stale — clear the entire cache before rebuilding.
        _cache = getattr(self, "_render_cache", None)
        if _cache is not None:
            _cache.clear()

        # Las listas pesadas por página arrancan llenas de None: cada slot se
        # construye perezosamente (_build_page_slot) al entrar en la ventana
        # visible. Las entradas None marcan "placeholder no construido" — todo
        # iterador masivo sobre estas listas debe saltarse los None.
        self._page_images      = [None] * total
        self._drag_overlays    = [None] * total
        self._sel_overlays     = [None] * total
        self._sel_handles      = [None] * total
        self._ocr_overlays     = [None] * total
        self._text_sel_layers  = [None] * total
        self._redact_overlays  = [None] * total
        self._loading_overlays = [None] * total
        self._ink_canvases     = [None] * total
        self._page_slots       = [None] * total
        self._page_gestures    = [None] * total
        self._text_sel_popups  = [None] * total
        self._annot_popups     = [None] * total
        self._page_placeholders = [None] * total
        self._page_rows        = []
        self._page_cum_offsets = []
        self._page_heights     = []
        self._rendered             = set()
        self._selected             = None
        self._page_words           = {}
        self._text_sel_sig         = {}
        self._text_sel_active_pages = set()
        self._text_sel_start_pn    = None
        self._text_sel_end_pn      = None
        self._text_sel_text        = ""
        self._text_sel_start_pdf   = None
        self._text_sel_end_pdf     = None
        self._text_sel_sel_rect    = None
        self._smart_text_sel_active = False
        self._sel_drag_handle      = None
        self._annot_popup_pn       = None

        # Sólo placeholders livianos para TODAS las páginas (barato, O(N)). El
        # árbol pesado de cada slot se construye on-demand.
        cum   = 0.0
        rows: list[ft.Control] = []
        for pn in range(total):
            w, h = page_dims[pn]
            ph = self._make_placeholder(pn, w, h)
            self._page_placeholders[pn] = ph
            row = ft.Row([ph], alignment=ft.MainAxisAlignment.CENTER)
            self._page_rows.append(row)
            rows.append(row)
            self._page_cum_offsets.append(cum)
            self._page_heights.append(float(h))
            cum += h + _PAGE_GAP

        self.viewer_scroll.controls = rows

        # Apply display-mode visibility before first render.
        display_mode = getattr(self, "_display_mode", "continuous")
        if display_mode == "single":
            for i, row in enumerate(self._page_rows):
                row.visible = (i == self.current_page)
        elif display_mode == "double":
            pair_start = (self.current_page // 2) * 2
            for i, row in enumerate(self._page_rows):
                row.visible = (i == pair_start or i == pair_start + 1)

        if display_mode in ("single", "double"):
            pair_start = (self.current_page // 2) * 2 if display_mode == "double" else self.current_page
            for pn in range(pair_start, min(pair_start + 2, total)):
                self._render_page_slot(pn)
        else:
            for pn in range(min(total, 1 + _PRELOAD)):
                self._render_page_slot(pn)

        if scroll_back and self._page_cum_offsets and display_mode == "continuous":
            try:
                self.viewer_scroll.scroll_to(
                    offset=self._page_cum_offsets[self.current_page], duration=0,
                )
            except Exception:
                pass

    # ── lazy slot construction ────────────────────────────────────────────────

    def _make_placeholder(self, pn: int, w: int, h: int) -> ft.Container:
        """Stand-in liviano para una página cuyo slot aún no se construyó.

        Mantiene las dimensiones correctas (para el scrollbar) y muestra sólo el
        número de página muy tenue — igual que el loading overlay. Crear esto
        para N páginas es barato; el árbol pesado se difiere a _build_page_slot.
        """
        return ft.Container(
            content=ft.Text(
                f"{pn + 1}", size=13, color="#D8D8D8",
                text_align=ft.TextAlign.CENTER,
            ),
            width=w, height=h,
            alignment=ft.alignment.center,
            bgcolor=_PAGE_BG, border_radius=2,
        )

    def _is_built(self, pn: int) -> bool:
        return 0 <= pn < len(self._page_images) and self._page_images[pn] is not None

    def _ensure_page_built(self, pn: int) -> None:
        if 0 <= pn < len(self._page_rows) and not self._is_built(pn):
            self._build_page_slot(pn)

    def _page_is_active(self, pn: int) -> bool:
        """True si la página participa en algún estado interactivo vivo y por
        tanto NO debe desinflarse a placeholder (selección, popup, tinta, etc.)."""
        if pn == self.current_page:
            return True
        sel = getattr(self, "_selected", None)
        if sel is not None and sel[0] == pn:
            return True
        if getattr(self, "_annot_popup_pn", None) == pn:
            return True
        if getattr(self, "_ink_page", None) == pn:
            return True
        s = getattr(self, "_text_sel_start_pn", None)
        e = getattr(self, "_text_sel_end_pn", None)
        if s is not None and e is not None and min(s, e) <= pn <= max(s, e):
            return True
        return False

    def _build_page_slot(self, pn: int) -> None:
        """Construye el árbol pesado de controles para la página *pn* y lo monta
        en su Row (que hasta ahora mostraba sólo un placeholder)."""
        if self._is_built(pn) or not (0 <= pn < len(self._page_rows)):
            return

        with self._doc_lock:
            r = self.doc[pn].rect
            w = int(r.width  * BASE_SCALE * self.zoom)
            h = int(r.height * BASE_SCALE * self.zoom)

        img = ft.Image(
                width=w, height=h, fit=ft.ImageFit.CONTAIN, gapless_playback=True,
                visible=False,
                color="#FFFFFFFF" if self._night_mode else None,
                color_blend_mode=ft.BlendMode.DIFFERENCE if self._night_mode else None,
            )
        drag_ov = ft.Container(
            visible=False,
            bgcolor=self._annot.overlay_color,
            border=ft.border.all(1, "#0055AA"),
            left=0, top=0, width=0, height=0,
        )

        # ── interactive selection overlay ─────────────────────────────────
        _HS  = 10   # corner handle size (px)
        _HHS = _HS / 2
        _HANDLE_CLR = "#0055FF"
        _HANDLE_STYLE = dict(
            width=_HS, height=_HS,
            bgcolor=_HANDLE_CLR,
            border_radius=2,
            left=0, top=0,
        )
        sel_border = ft.Container(
            left=0, top=0, width=0, height=0,
            bgcolor="#200055FF",
            border=ft.border.all(2, _HANDLE_CLR),
        )
        sel_tl = ft.Container(**_HANDLE_STYLE)
        sel_tr = ft.Container(**_HANDLE_STYLE)
        sel_bl = ft.Container(**_HANDLE_STYLE)
        sel_br = ft.Container(**_HANDLE_STYLE)
        # Tiradores de punto medio de cada lado: redimensionan un solo eje
        # (alto desde arriba/abajo, ancho desde izquierda/derecha).
        sel_tm = ft.Container(**_HANDLE_STYLE)
        sel_bm = ft.Container(**_HANDLE_STYLE)
        sel_lm = ft.Container(**_HANDLE_STYLE)
        sel_rm = ft.Container(**_HANDLE_STYLE)
        _ctx_btn = ft.ButtonStyle(
            padding=ft.padding.all(5),
            shape=ft.RoundedRectangleBorder(radius=4),
        )
        _mc_edit_sep  = ft.Container(width=1, height=22, bgcolor="outlineVariant", visible=False)
        _mc_edit_btn  = ft.IconButton(
            ft.Icons.EDIT_OUTLINED,
            icon_color="#1565C0",
            icon_size=18,
            tooltip="Editar texto",
            on_click=self._edit_selected_text,
            style=_ctx_btn,
            visible=False,
        )
        _mc_color_sep  = ft.Container(width=1, height=22, bgcolor="outlineVariant")
        _mc_color_btn  = ft.IconButton(
            ft.Icons.PALETTE_OUTLINED,
            icon_color="#7B1FA2",
            icon_size=18,
            tooltip="Cambiar color",
            on_click=self._recolor_selected_menu,
            style=_ctx_btn,
        )
        _mc_scale_sep  = ft.Container(width=1, height=22, bgcolor="outlineVariant")
        _mc_scale_down = ft.IconButton(
            ft.Icons.REMOVE_CIRCLE_OUTLINE,
            icon_color="onSurfaceVariant",
            icon_size=18,
            tooltip="Reducir",
            on_click=self._scale_down_selected,
            style=_ctx_btn,
        )
        _mc_scale_up   = ft.IconButton(
            ft.Icons.ADD_CIRCLE_OUTLINE,
            icon_color="onSurfaceVariant",
            icon_size=18,
            tooltip="Agrandar",
            on_click=self._scale_up_selected,
            style=_ctx_btn,
        )
        _mc_width_sep  = ft.Container(width=1, height=22, bgcolor="outlineVariant")
        _mc_width_down = ft.IconButton(
            ft.Icons.REMOVE_CIRCLE,
            icon_color="#8B4513",
            icon_size=18,
            tooltip="Más fino",
            on_click=self._thin_selected,
            style=_ctx_btn,
        )
        _mc_width_up   = ft.IconButton(
            ft.Icons.ADD_CIRCLE,
            icon_color="#8B4513",
            icon_size=18,
            tooltip="Más grueso",
            on_click=self._thicken_selected,
            style=_ctx_btn,
        )
        sel_menu = ft.Container(
            left=0, top=0,
            visible=False,
            bgcolor="surface",
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=4, vertical=3),
            shadow=ft.BoxShadow(
                blur_radius=10, spread_radius=1,
                color="#33000000", offset=ft.Offset(0, 2),
            ),
            border=ft.border.all(1, "outlineVariant"),
            content=ft.Row(
                [
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_600,
                        icon_size=18,
                        tooltip="Eliminar",
                        on_click=self._delete_selected,
                        style=_ctx_btn,
                    ),
                    _mc_edit_sep,
                    _mc_edit_btn,
                    _mc_color_sep,
                    _mc_color_btn,
                    _mc_scale_sep,
                    _mc_scale_down,
                    _mc_scale_up,
                    _mc_width_sep,
                    _mc_width_down,
                    _mc_width_up,
                    ft.Container(width=1, height=22, bgcolor="outlineVariant"),
                    ft.IconButton(
                        ft.Icons.CLOSE,
                        icon_color="onSurfaceVariant",
                        icon_size=14,
                        tooltip="Deseleccionar",
                        on_click=self._deselect_annot,
                        style=_ctx_btn,
                    ),
                ],
                spacing=0, tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        # "Ghost" de la forma: dibuja el contorno real de la anotación
        # (elipse para círculo, rectángulo para cuadrado) dentro de la caja de
        # selección. Hace que la caja represente la figura y, sobre todo, que la
        # figura siga visible y se desplace con la caja durante un arrastre
        # (mientras la anotación real está oculta para no quedar "atrás").
        sel_ghost = cv.Canvas(shapes=[], left=0, top=0, width=0, height=0)
        sel_rot_group_inner = ft.Stack(
            [sel_ghost, sel_border,
             sel_tl, sel_tr, sel_bl, sel_br,
             sel_tm, sel_bm, sel_lm, sel_rm],
            clip_behavior=ft.ClipBehavior.NONE,
        )
        sel_rot_group = ft.Container(
            content=sel_rot_group_inner,
            left=0, top=0, width=0, height=0,
            clip_behavior=ft.ClipBehavior.NONE,
        )
        sel_stack = ft.Stack(
            [sel_rot_group, sel_menu],
            clip_behavior=ft.ClipBehavior.NONE,
        )
        sel_ov = ft.Container(
            content=sel_stack,
            visible=False,
            left=0, top=0, width=0, height=0,
            clip_behavior=ft.ClipBehavior.NONE,
        )
        self._sel_handles[pn] = {
            "border":     sel_border,
            "ghost":      sel_ghost,
            "tl":         sel_tl,
            "tr":         sel_tr,
            "bl":         sel_bl,
            "br":         sel_br,
            "tm":         sel_tm,
            "bm":         sel_bm,
            "lm":         sel_lm,
            "rm":         sel_rm,
            "menu":       sel_menu,
            "rot_group":  sel_rot_group,
            "edit_sep":   _mc_edit_sep,
            "edit_btn":   _mc_edit_btn,
            "color_sep":  _mc_color_sep,
            "color_btn":  _mc_color_btn,
            "scale_sep":  _mc_scale_sep,
            "scale_down": _mc_scale_down,
            "scale_up":   _mc_scale_up,
            "width_sep":  _mc_width_sep,
            "width_down": _mc_width_down,
            "width_up":   _mc_width_up,
        }
        ocr_ov      = ft.Stack([], visible=False)
        text_sel_ov = ft.Stack([], visible=False)
        redact_ov   = ft.Stack([], visible=False)

        _btn_style = ft.ButtonStyle(
            padding=ft.padding.symmetric(horizontal=6, vertical=3),
            text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_500),
            overlay_color={ft.ControlState.HOVERED: "#12000000"},
        )
        popup_ov = ft.Container(
            content=ft.Row([
                ft.TextButton(
                    "Copiar",
                    icon=ft.Icons.CONTENT_COPY,
                    icon_color="onSurfaceVariant",
                    on_click=self._text_sel_copy,
                    style=_btn_style,
                ),
                ft.Container(width=1, height=20, bgcolor="outlineVariant"),
                ft.TextButton(
                    "Resaltar",
                    icon=ft.Icons.HIGHLIGHT,
                    icon_color="#E6AC00",
                    on_click=lambda e: self._text_sel_apply(Tool.HIGHLIGHT),
                    style=_btn_style,
                ),
                ft.TextButton(
                    "Subrayar",
                    icon=ft.Icons.FORMAT_UNDERLINE,
                    icon_color="#1565C0",
                    on_click=lambda e: self._text_sel_apply(Tool.UNDERLINE),
                    style=_btn_style,
                ),
                ft.TextButton(
                    "Tachar",
                    icon=ft.Icons.FORMAT_STRIKETHROUGH,
                    icon_color="#C62828",
                    on_click=lambda e: self._text_sel_apply(Tool.STRIKEOUT),
                    style=_btn_style,
                ),
                ft.Container(width=1, height=20, bgcolor="outlineVariant"),
                ft.TextButton(
                    "Censurar",
                    icon=ft.Icons.VISIBILITY_OFF,
                    icon_color="#B71C1C",
                    on_click=lambda e: self._text_sel_send_to_redact(),
                    style=_btn_style,
                ),
                ft.Container(width=1, height=20, bgcolor="outlineVariant"),
                ft.TextButton(
                    "Buscar",
                    icon=ft.Icons.SEARCH,
                    icon_color="#1A73E8",
                    on_click=lambda e: self._text_sel_search_google(),
                    style=_btn_style,
                ),
                ft.IconButton(
                    ft.Icons.CLOSE,
                    icon_size=14,
                    icon_color="onSurfaceVariant",
                    tooltip="Cerrar selección",
                    on_click=self._text_sel_dismiss,
                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                ),
            ], spacing=0, tight=True, wrap=True, run_spacing=2,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            left=0, top=0, visible=False,
            bgcolor="surface",
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
            shadow=ft.BoxShadow(
                blur_radius=12, spread_radius=1,
                color="#44000000", offset=ft.Offset(0, 3),
            ),
            border=ft.border.all(1, "outlineVariant"),
        )

        _abtn = ft.ButtonStyle(
            padding=ft.padding.symmetric(horizontal=6, vertical=3),
            text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_500),
            overlay_color={ft.ControlState.HOVERED: "#12000000"},
        )
        annot_popup_ov = ft.Container(
            content=ft.Row([
                ft.TextButton(
                    "Eliminar",
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=ft.Colors.RED_600,
                    on_click=self._annot_popup_delete,
                    style=_abtn,
                ),
                ft.Container(width=1, height=20, bgcolor="outlineVariant"),
                ft.TextButton(
                    "Color",
                    icon=ft.Icons.PALETTE_OUTLINED,
                    icon_color="#7B1FA2",
                    on_click=self._annot_popup_recolor,
                    style=_abtn,
                ),
                ft.IconButton(
                    ft.Icons.CLOSE,
                    icon_size=14,
                    icon_color="onSurfaceVariant",
                    tooltip="Cerrar",
                    on_click=self._hide_annot_popup,
                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                ),
            ], spacing=0, tight=True,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            left=0, top=0, visible=False,
            bgcolor="surface",
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
            shadow=ft.BoxShadow(
                blur_radius=12, spread_radius=1,
                color="#44000000", offset=ft.Offset(0, 3),
            ),
            border=ft.border.all(1, "outlineVariant"),
        )

        ink_canvas = cv.Canvas(shapes=[], width=w, height=h)

        # Placeholder "hoja en blanco": fondo papel (= _PAGE_BG blanco) con
        # sólo el número de página muy tenue. Sin icono ni spinner — un
        # spinner correría un AnimationController que repinta a 60 fps
        # mientras esté en el árbol (incluso fuera de pantalla), y la
        # evicción deja decenas de overlays visibles tras el scroll → eso
        # forzaba repintado continuo (GPU en reposo, CPU/RAM sin GPU). Un
        # texto estático no programa frames y, al ser blanco, el fling se ve
        # como pasar hojas en vez de bloques grises "cargando".
        loading_ov = ft.Container(
            content=ft.Text(
                f"{pn + 1}",
                size=13, color="#D8D8D8",
                text_align=ft.TextAlign.CENTER,
            ),
            left=0, top=0, width=w, height=h,
            alignment=ft.alignment.center,
            bgcolor=_PAGE_BG,
            visible=True,
        )

        self._page_images[pn]      = img
        self._drag_overlays[pn]    = drag_ov
        self._sel_overlays[pn]     = sel_ov
        self._ocr_overlays[pn]     = ocr_ov
        self._text_sel_layers[pn]  = text_sel_ov
        self._redact_overlays[pn]  = redact_ov
        self._loading_overlays[pn] = loading_ov
        self._ink_canvases[pn]     = ink_canvas
        self._text_sel_popups[pn]  = popup_ov
        self._annot_popups[pn]     = annot_popup_ov

        slot = ft.Container(
            content=ft.Stack(
                # loading_ov va PRIMERO (al fondo): respaldo "papel" blanco
                # detrás de la imagen. Así, en la ventana en que Flutter aún
                # decodifica el archivo recién renderizado, se ve blanco y no
                # el gris del fondo del visor → sin flash gris al aparecer.
                [loading_ov, img, text_sel_ov, drag_ov, ink_canvas, sel_ov, ocr_ov, redact_ov, popup_ov, annot_popup_ov],
                clip_behavior=ft.ClipBehavior.NONE,
            ),
            width=w, height=h,
            bgcolor=_PAGE_BG,
            border_radius=2,
            clip_behavior=ft.ClipBehavior.NONE,
        )
        self._page_slots[pn] = slot

        gd = ft.GestureDetector(
            content=slot,
            on_tap_down       = lambda e, p=pn: self._on_tap_down(e, p),
            on_tap            = lambda e, p=pn: self._on_tap(e, p),
            on_pan_start      = lambda e, p=pn: self._on_pan_start(e, p),
            on_pan_update     = lambda e, p=pn: self._on_pan_update(e, p),
            on_pan_end        = lambda e, p=pn: self._on_pan_end(e, p),
            on_secondary_tap  = lambda e, p=pn: self._on_secondary_tap(e, p),
            on_hover          = lambda e, p=pn: self._on_hover(e, p),
            on_scroll         = lambda e, p=pn: self._on_page_scroll(e, p),
            mouse_cursor      = self._current_cursor,
        )
        self._page_gestures[pn] = gd

        # Montar el árbol pesado en el Row (reemplaza al placeholder). El render
        # de la imagen lo dispara el llamador vía _render_page_slot.
        self._page_rows[pn].controls = [gd]
        try:
            self._page_rows[pn].update()
        except Exception:
            pass

        # Re-aplicar overlays dependientes de página que estuvieran activos: la
        # página acaba de materializarse desde un placeholder, así que cualquier
        # estado calculado mientras era placeholder (cajas OCR, preview de
        # censura, overlay de selección) debe re-dibujarse sobre el slot nuevo.
        try:
            if getattr(self, "_ocr_show_boxes", False) and pn in self._ocr_by_page:
                self._render_ocr_boxes(pn=pn)
        except Exception:
            pass
        try:
            if getattr(self, "_redact_preview", False) and self._redact_matches:
                self._reapply_redact_page(pn)
        except Exception:
            pass
        try:
            sel = getattr(self, "_selected", None)
            if sel is not None and sel[0] == pn:
                self._refresh_selected_overlay(pn)
        except Exception:
            pass

    def _teardown_page_slot(self, pn: int) -> None:
        """Inverso de _build_page_slot: devuelve la página a un placeholder
        liviano y libera el árbol pesado de controles. No-op si no está
        construida o si participa en algún estado interactivo vivo."""
        if not self._is_built(pn) or self._page_is_active(pn):
            return
        # Aborta cualquier render en vuelo para esta página (token y flags).
        self._bump_render_token(pn)
        self._rendered.discard(pn)
        self._previewed.discard(pn)
        self._rendering.discard(pn)
        getattr(self, "_rendering_preview", set()).discard(pn)
        getattr(self, "_pending_rerender", set()).discard(pn)

        w = float(self._page_slots[pn].width or 0)
        h = float(self._page_heights[pn]) if pn < len(self._page_heights) else 0.0
        ph = self._make_placeholder(pn, int(w), int(h))
        self._page_placeholders[pn] = ph
        row = self._page_rows[pn]
        row.controls = [ph]
        try:
            row.update()
        except Exception:
            pass

        for lst in (
            self._page_images, self._drag_overlays, self._sel_overlays,
            self._sel_handles, self._ocr_overlays, self._text_sel_layers,
            self._redact_overlays, self._loading_overlays, self._ink_canvases,
            self._text_sel_popups, self._annot_popups, self._page_slots,
            self._page_gestures,
        ):
            lst[pn] = None

    def _teardown_built_distant(self, pixels: float, viewport_h: float) -> bool:
        """Desinfla a placeholder los slots construidos lejos del viewport.

        Acota la RAM al recorrer documentos grandes: sin esto, recorrer las N
        páginas terminaría construyendo el árbol pesado de todas. El margen es
        mayor que el de evicción de imágenes para no reconstruir con micro-scroll.
        """
        keep_top    = pixels - viewport_h * _SLOT_TEARDOWN_MARGIN
        keep_bottom = pixels + viewport_h * (1.0 + _SLOT_TEARDOWN_MARGIN)
        changed = False
        for pn in range(len(self._page_rows)):
            if not self._is_built(pn):
                continue
            start = self._page_cum_offsets[pn]
            page_bottom = start + self._page_heights[pn]
            if page_bottom < keep_top or start > keep_bottom:
                if self._page_is_active(pn):
                    continue
                self._teardown_page_slot(pn)
                changed = True
        return changed

    def _bump_render_token(self, pn: int) -> int:
        tokens = getattr(self, "_render_tokens", None)
        if tokens is None:
            tokens = {}
            self._render_tokens = tokens
        token = tokens.get(pn, 0) + 1
        tokens[pn] = token
        return token

    def _preview_zoom(self) -> float:
        """Zoom del tier de baja calidad (LOD).

        Fracción del zoom objetivo (más barato y menos textura), con un piso de
        legibilidad y un techo absoluto para que el prefetch de vecinas nunca
        rasterice pixmaps enormes cuando el usuario está a zoom alto.
        """
        q = max(_PREVIEW_MIN_ZOOM, self.zoom * _PREVIEW_QUALITY)
        return min(q, _PREVIEW_MAX_ZOOM, self.zoom)

    def _schedule_scroll_idle(self) -> None:
        t = getattr(self, "_scroll_idle_timer", None)
        if t is not None:
            t.cancel()
        self._scroll_idle_timer = threading.Timer(_SCROLL_IDLE_DELAY, self._on_scroll_idle)
        self._scroll_idle_timer.daemon = True
        self._scroll_idle_timer.start()

    def _on_scroll_idle(self) -> None:
        if getattr(self, "_is_closed", False):
            return
        self._scrolling = False
        px = getattr(self, "_scroll_px", 0.0)
        vh = getattr(self, "_last_viewport_h", 600.0)
        self._render_visible(float(px), float(vh), preview=False)
        self._prefetch_neighbors_preview(self.current_page)
        self._prune_render_cache(self.current_page)
        evicted = self._evict_outside_window(self.current_page)
        # Desinflar a placeholder los slots lejos del viewport para acotar la RAM
        # del árbol de controles al recorrer documentos grandes. _teardown_page_slot
        # actualiza su propio Row, por lo que no requiere page_ref.update() global.
        self._teardown_built_distant(float(px), float(vh))
        if evicted:
            try:
                self.page_ref.update()
            except Exception:
                pass

    def _prune_text_caches(self, center_page: int) -> None:
        """Acota las cachés de texto por página a una ventana alrededor de la
        página actual.

        Estas cachés (``_page_words`` char-level rawdict, ``_page_word_bands``,
        ``_page_blocks_cache``, ``_text_rects_cache``) no estaban acotadas: al
        recorrer un documento grande con el cursor se acumulaban para todas las
        páginas y sobrevivían incluso a ``_do_suspend`` (que sólo libera el
        render cache). La reconstrucción es perezosa (``_get_page_words`` /
        ``_point_has_text``), así que podar sólo añade una re-extracción si el
        usuario vuelve a una página lejana.
        """
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        radius = max(0, (_TEXT_CACHE_KEEP_PAGES - 1) // 2)
        start = max(0, center_page - radius)
        end = min(total, center_page + radius + 1)
        keep = set(range(start, end))

        # No podar páginas dentro de una selección de texto activa: re-extraer
        # rawdict char-level bajo _doc_lock en medio de un arrastre causaría jank.
        s_pn = getattr(self, "_text_sel_start_pn", None)
        e_pn = getattr(self, "_text_sel_end_pn", None)
        if s_pn is not None and e_pn is not None:
            lo, hi = sorted((s_pn, e_pn))
            keep.update(range(max(0, lo), min(total, hi + 1)))

        for cache in (
            getattr(self, "_page_words", None),
            getattr(self, "_page_word_bands", None),
            getattr(self, "_page_blocks_cache", None),
            getattr(self, "_text_rects_cache", None),
        ):
            if not cache:
                continue
            for pn in [k for k in cache if k not in keep]:
                cache.pop(pn, None)

    def _prune_render_cache(self, center_page: int) -> None:
        self._prune_text_caches(center_page)
        cache = getattr(self, "_render_cache", None)
        if cache is None:
            return
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        radius = max(0, (_CACHE_KEEP_PAGES - 1) // 2)
        start = max(0, center_page - radius)
        end = min(total, center_page + radius + 1)
        keep_pages = set(range(start, end))
        try:
            cache.keep_pages(keep_pages)
        except Exception:
            pass

    def _evict_outside_window(self, center_page: int) -> bool:
        if getattr(self, "_is_closed", False):
            return False
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return False
        radius = max(0, (_CACHE_KEEP_PAGES - 1) // 2)
        start = max(0, center_page - radius)
        end = min(total, center_page + radius + 1)
        keep_pages = set(range(start, end))
        loading_overlays = getattr(self, "_loading_overlays", [])
        evicted = False
        for pn in range(total):
            if pn in keep_pages:
                continue
            if pn not in self._rendered and pn not in self._previewed:
                continue
            self._rendered.discard(pn)
            self._previewed.discard(pn)
            img = self._page_images[pn]
            if img is None:  # slot ya desinflado a placeholder
                continue
            img.src = None
            img.src_base64 = None
            img.visible = False
            if pn < len(loading_overlays) and loading_overlays[pn] is not None:
                loading_overlays[pn].visible = True
            evicted = True
        return evicted

    def _render_page_slot(self, pn: int, preview: bool = False) -> None:
        """Schedule a background render for one page (no-op if already rendered)."""
        # Construye el árbol pesado del slot si aún es un placeholder. Es seguro
        # llamarlo desde el hilo principal (scroll/navegación); el follow-up de
        # _pending_rerender que corre en el worker sólo toca páginas ya construidas.
        self._ensure_page_built(pn)
        if not self._is_built(pn):
            return
        # El tier preview sólo aporta si rasteriza por debajo del zoom objetivo;
        # a zooms muy bajos _preview_zoom() iguala al zoom → render directo a full.
        if preview and self._preview_zoom() >= self.zoom - 1e-3:
            preview = False

        if preview:
            # No arrancar un preview que compita con un full ya en curso o hecho:
            # el full siempre gana, así evitamos que el preview pise la versión
            # nítida (los tokens lo garantizan, pero esto ahorra el render inútil).
            if pn in self._rendered or pn in self._rendering or pn in self._rendering_preview:
                return
            self._rendering_preview.add(pn)
        else:
            if pn in self._rendered or pn in self._rendering:
                if pn in self._rendering:
                    # Another render is in progress; request a follow-up render so
                    # changes committed while the current render runs are not lost.
                    getattr(self, "_pending_rerender", set()).add(pn)
                return
            self._rendering.add(pn)
        # Cancel any stale pending-rerender request for this slot; we're
        # starting fresh right now.
        getattr(self, "_pending_rerender", set()).discard(pn)
        gen = self._render_gen
        token = self._bump_render_token(pn)

        cache = getattr(self, "_render_cache", None)

        def _worker() -> None:
            try:
                with _RENDER_SEM:  # bound concurrent renders across all tabs
                    with self._doc_lock:
                        if gen != self._render_gen or pn >= len(self._page_images):
                            return
                        zoom = self._preview_zoom() if preview else self.zoom
                    # render_page toma _doc_lock sólo para rasterizar; el encode
                    # y el IO a disco corren fuera → no serializa el documento.
                    path, w, h, _ = render_page(
                        self.doc, pn, zoom, cache, doc_lock=self._doc_lock
                    )
                if gen != self._render_gen or pn >= len(self._page_images):
                    return
                if token != getattr(self, "_render_tokens", {}).get(pn, token):
                    return
                img  = self._page_images[pn]
                slot = self._page_slots[pn]
                if img is None or slot is None:  # slot desinflado mientras render en vuelo
                    return
                img.src = path
                img.src_base64 = None
                if preview:
                    self._previewed.add(pn)
                else:
                    # fit es CONTAIN siempre (ver creación de img): en un render
                    # full la imagen ya mide exactamente lo que el slot, así que
                    # CONTAIN == 1:1 (nítido). Al NO alternar fit entre CONTAIN y
                    # NONE evitamos el salto de tamaño de un frame durante el zoom
                    # mientras gapless_playback sostiene la imagen anterior.
                    img.width  = w
                    img.height = h
                    self._previewed.discard(pn)
                    # Limpiar el Rotate de transición que _rotate() pudo haber
                    # puesto para evitar el flash en blanco durante la espera.
                    if img.rotate is not None:
                        img.rotate = None
                img.visible = True
                # Fondo blanco (no None/transparente): durante el instante en
                # que Flutter decodifica la imagen recién asignada, el slot se ve
                # blanco en vez del gris del visor → sin flash gris.
                slot.bgcolor = _PAGE_BG
                loading_overlays = getattr(self, "_loading_overlays", [])
                if pn < len(loading_overlays):
                    loading_overlays[pn].visible = False
                if not preview:
                    self._rendered.add(pn)
                # Batch updates: si varios workers terminan dentro de 30 ms,
                # se consolidan. Marcamos sólo ESTE slot como sucio para que el
                # update parche el contenedor de la página y no re-serialice
                # toda la columna (menos CPU/GPU por update durante el scroll).
                self._schedule_render_update(pn)
                # Notify mixins that the page image is now up-to-date.
                try:
                    self._on_page_rendered(pn)
                except Exception:
                    pass
            finally:
                if preview:
                    self._rendering_preview.discard(pn)
                else:
                    self._rendering.discard(pn)
                # If a re-render was requested while this one was running, start it.
                pending = getattr(self, "_pending_rerender", set())
                if not preview and pn in pending:
                    pending.discard(pn)
                    self._rendered.discard(pn)
                    self._render_page_slot(pn)

        threading.Thread(target=_worker, daemon=True).start()

    def _schedule_render_update(self, pn: int | None = None) -> None:
        """Coalesce concurrent worker completions into a single UI update.

        Con un debounce de 30 ms los renders que terminan juntos comparten un
        solo flush. Los slots que cambiaron se acumulan en ``_dirty_slots`` y se
        actualizan individualmente (parche del contenedor de cada página) en
        lugar de re-serializar toda la columna en cada flush.
        """
        if pn is not None:
            dirty = getattr(self, "_dirty_slots", None)
            if dirty is None:
                dirty = set()
                self._dirty_slots = dirty
            dirty.add(pn)
        t = getattr(self, "_render_upd_timer", None)
        if t is not None:
            t.cancel()
        self._render_upd_timer = threading.Timer(0.03, self._do_render_update)
        self._render_upd_timer.start()

    def _do_render_update(self) -> None:
        if getattr(self, "_is_closed", False):
            return
        dirty = getattr(self, "_dirty_slots", None)
        try:
            if dirty:
                slots = getattr(self, "_page_slots", [])
                for pn in list(dirty):
                    if 0 <= pn < len(slots):
                        try:
                            slots[pn].update()
                        except Exception:
                            pass
                dirty.clear()
            else:
                self.viewer_scroll.update()
        except Exception:
            pass

    def _render_visible(self, pixels: float, viewport_h: float, preview: bool = False) -> None:
        if not self._page_cum_offsets:
            return
        if preview and self._preview_zoom() >= self.zoom - 1e-3:
            preview = False
        margin = viewport_h * 0.5
        top    = pixels - margin
        bottom = pixels + viewport_h + margin
        # Saltar directamente a la primera página que puede estar en el viewport:
        # bisect_right da la posición de inserción después de todos los offsets ≤ top,
        # así que -1 nos da la última página que empieza antes del borde superior.
        start_idx = max(0, bisect.bisect_right(self._page_cum_offsets, top) - 1)
        for pn in range(start_idx, len(self._page_cum_offsets)):
            start = self._page_cum_offsets[pn]
            if start > bottom:
                break
            if start + self._page_heights[pn] >= top:
                self._render_page_slot(pn, preview=preview)

    def _prefetch_neighbors_preview(self, center: int) -> None:
        """Pre-renderiza las páginas vecinas de la ventana en baja calidad (LOD).

        Así, al hacer scroll a la página anterior/siguiente, hay un preview
        instantáneo en vez de un slot en blanco. _render_page_slot(preview=True)
        es idempotente y NO toca páginas ya en full ni en render full (esas las
        cubre _render_visible), por lo que sólo rasteriza —barato— las vecinas
        que aún no tienen imagen. Las texturas de baja resolución ocupan ~1/4 de
        la RAM/VRAM de una full: el render caro queda limitado a lo enfocado.
        """
        if not self._page_cum_offsets:
            return
        if getattr(self, "_display_mode", "continuous") != "continuous":
            return
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        radius = max(0, (_CACHE_KEEP_PAGES - 1) // 2)
        start = max(0, center - radius)
        end = min(total, center + radius + 1)
        for pn in range(start, end):
            self._render_page_slot(pn, preview=True)

    def _prefetch_adjacent_pages(self, center: int) -> None:
        """Pre-renderiza a calidad COMPLETA las páginas contiguas en modo
        página única / doble.

        Al navegar con la rueda, la página destino ya estará rasterizada y su
        imagen visible (dentro de una fila oculta), de modo que el cambio sólo
        alterna la visibilidad de la fila — sin el destello blanco de rasterizar
        desde cero. ``_render_page_slot`` es idempotente: no hace nada para una
        página ya renderizada o en curso. La ventana de evicción
        (``_evict_outside_window``) conserva ±2 páginas, así que lo prefetcheado
        sobrevive hasta alejarse. Render full (no preview) para evitar también el
        swap preview→nítido al aterrizar.
        """
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        mode  = getattr(self, "_display_mode", "continuous")
        if mode == "double":
            ps = (center // 2) * 2
            targets = (ps - 2, ps - 1, ps + 2, ps + 3)
        else:
            targets = (center - 1, center + 1)
        for pn in targets:
            if 0 <= pn < total:
                self._render_page_slot(pn)

    def _evict_distant(self, pixels: float, viewport_h: float) -> bool:
        """Oculta páginas alejadas del viewport. Retorna True si eviccionó alguna."""
        keep_top    = pixels - viewport_h * _EVICT_MARGIN
        keep_bottom = pixels + viewport_h * (1.0 + _EVICT_MARGIN)
        loading_overlays = getattr(self, "_loading_overlays", [])
        evicted = False
        for pn, (start, h) in enumerate(zip(self._page_cum_offsets, self._page_heights)):
            if pn not in self._rendered and pn not in self._previewed:
                continue
            page_bottom = start + h
            if page_bottom < keep_top or start > keep_bottom:
                self._rendered.discard(pn)
                self._previewed.discard(pn)
                img = self._page_images[pn]
                if img is None:  # slot desinflado a placeholder
                    continue
                img.src = None
                img.src_base64 = None
                img.visible = False
                if pn < len(loading_overlays) and loading_overlays[pn] is not None:
                    loading_overlays[pn].visible = True
                evicted = True
        return evicted

    # ── render / update ───────────────────────────────────────────────────────

    def _rerender_page_image(self, pn: int) -> None:
        """Lightweight re-render: only re-renders the page image in background.

        Unlike _refresh_page this does NOT clear selection, update OCR UI, or
        call page_ref.update() — the background thread calls slot.update() when
        the new image is ready.  Use this after move / resize / scale so the
        UI doesn't flash.
        """
        cache = getattr(self, "_render_cache", None)
        if cache is not None:
            cache.invalidate_page(pn)
        self._rendered.discard(pn)
        self._previewed.discard(pn)
        self._render_page_slot(pn)

    def _refresh_page(self, pn: int, keep_selection: bool = False) -> None:
        if not keep_selection and self._selected is not None and self._selected[0] == pn:
            self._selected = None
            self._sel_overlays[pn].visible = False
        cache = getattr(self, "_render_cache", None)
        if cache is not None:
            cache.invalidate_page(pn)
        self._rendered.discard(pn)
        self._previewed.discard(pn)
        self._render_page_slot(pn)
        self._refresh_ocr_ui_for_page()
        self.page_ref.update()

    def _update(self) -> None:
        self._refresh_page(self.current_page)

    def _update_scroll_column_width(self, max_page_w: int | None = None) -> None:
        """Ajusta viewer_scroll.width = max(viewport_w, max_page_w + 40).

        Cuando la página cabe (max_page_w < viewport_w) el Column es tan ancho
        como el viewport → horizontal_alignment=CENTER centra las páginas.
        Cuando la página desborda (zoom alto) el Column es más ancho que el
        viewport → viewer_hscroll (exterior) activa el scroll horizontal y su
        barra nativa queda al fondo del viewport. La barra vertical se dibuja
        aparte como overlay (_vbar) anclado al borde derecho del viewport.
        """
        if max_page_w is None:
            if not self._page_heights:
                return
            with self._doc_lock:
                try:
                    max_page_w = max(
                        int(self.doc[pn].rect.width * BASE_SCALE * self.zoom)
                        for pn in range(len(self.doc))
                    )
                except Exception:
                    return

        # page_ref se pasa en __init__ → window.width disponible desde el inicio.
        try:
            win_w = int(self.page_ref.window.width or 0) or None
        except Exception:
            win_w = None

        if win_w is not None:
            sidebar_w = 0
            try:
                if self._sidebar_visible and self._right_sidebar is not None:
                    sidebar_w = int(self._right_sidebar.width or 360)
            except Exception:
                pass
            # viewer_body.padding = 20 px × 2 lados = 40 px.
            # Restamos 6 px extra de margen para que viewer_scroll.width sea
            # SIEMPRE ligeramente menor que el viewport cuando la página cabe —
            # eso evita el scroll horizontal espurio.
            viewport_w = max(400, win_w - sidebar_w - 46)
        else:
            viewport_w = max_page_w + 400   # fallback: columna amplia

        page_overflows = max_page_w > viewport_w
        self._page_overflows_h = page_overflows

        if page_overflows:
            # Página más ancha que el viewport → scroll horizontal intencional.
            # La barra vertical NATIVA se dibuja en el borde derecho del Column
            # (= fuera del viewport) → la ocultamos y usamos la barra vertical
            # PERSONALIZADA (_vbar), anclada al borde derecho del viewport.
            new_w            = max_page_w + 40
            new_hscroll_mode = ft.ScrollMode.AUTO
            new_vscroll_mode = ft.ScrollMode.HIDDEN
        else:
            # Página cabe → columna = viewport (−4 px de margen anti-redondeo).
            # El borde derecho del Column coincide con el viewport, así que la
            # barra vertical NATIVA queda bien ubicada → la usamos y ocultamos
            # la personalizada (evita ver dos barras superpuestas).
            new_w            = viewport_w - 4
            new_hscroll_mode = ft.ScrollMode.HIDDEN
            new_vscroll_mode = ft.ScrollMode.AUTO

        changed = (
            self.viewer_scroll.width         != new_w
            or self.viewer_hscroll.scroll    != new_hscroll_mode
            or self.viewer_scroll.scroll     != new_vscroll_mode
        )
        if changed:
            self.viewer_scroll.width      = new_w
            self.viewer_scroll.scroll     = new_vscroll_mode
            self.viewer_hscroll.scroll    = new_hscroll_mode
            try:
                self.viewer_hscroll.update()
            except Exception:
                pass
            try:
                self.viewer_scroll.update()
            except Exception:
                pass

        # La barra vertical personalizada sólo se usa cuando la página desborda
        # (si cabe, manda la nativa). Recalcular su geometría/visibilidad.
        self._update_vbar_geometry()

    # ── barra de scroll vertical personalizada ──────────────────────────────────
    def _content_height(self) -> float:
        """Alto total del contenido scrolleable (páginas visibles + gaps)."""
        offs = getattr(self, "_page_cum_offsets", None)
        hs   = getattr(self, "_page_heights", None)
        if not offs or not hs:
            return 0.0
        return float(offs[-1] + hs[-1])

    def _update_vbar_geometry(self) -> None:
        """Recalcula visibilidad, alto de pista y tamaño/posición del thumb de la
        barra vertical. Usa la última extensión real de scroll si la hay
        (_vbar_max_extent / _vbar_viewport_h, fijadas en _on_view_scroll) y, en
        su defecto, una estimación a partir del alto de las páginas."""
        vbar = getattr(self, "_vbar", None)
        if vbar is None:
            return

        # Sólo se usa cuando la página desborda horizontalmente; si cabe, la
        # barra vertical nativa queda bien ubicada y se encarga ella.
        if not getattr(self, "_page_overflows_h", False):
            if vbar.visible:
                vbar.visible = False
                try:
                    vbar.update()
                except Exception:
                    pass
            return

        content_h  = self._content_height()
        viewport_h = getattr(self, "_vbar_viewport_h", 0.0) or \
                     getattr(self, "_last_viewport_h", 0.0) or 0.0
        max_extent = getattr(self, "_vbar_max_extent", None)
        if max_extent is None:
            max_extent = max(0.0, content_h - viewport_h)

        # Sin desbordamiento vertical → ocultar la barra.
        if max_extent <= 1.0 or viewport_h <= 0 or content_h <= 0:
            if vbar.visible:
                vbar.visible = False
                try:
                    vbar.update()
                except Exception:
                    pass
            return

        track_h = max(40.0, viewport_h - 12.0)
        thumb_h = max(40.0, min(track_h, track_h * viewport_h / content_h))
        travel  = max(1.0, track_h - thumb_h)
        self._vbar_track_h = track_h
        self._vbar_thumb_h = thumb_h
        self._vbar_travel  = travel

        offset = min(getattr(self, "_scroll_px", 0.0), max_extent)
        thumb_top = (offset / max_extent) * travel if max_extent else 0.0
        self._vbar_thumb_top = thumb_top

        vbar.height             = track_h
        self._vbar_thumb.height = thumb_h
        self._vbar_thumb.top    = thumb_top
        vbar.visible            = True
        try:
            vbar.update()
        except Exception:
            pass
        # Flash breve al (re)aparecer (p. ej. al entrar en zoom alto) y luego
        # auto-ocultar, igual que la barra nativa.
        self._show_vbar()

    # ── auto-ocultado (estilo barra nativa) ─────────────────────────────────────
    _VBAR_HIDE_DELAY    = 1.4         # segundos de inactividad antes de desvanecer
    _VBAR_THUMB_IDLE    = "#73757575"  # gris sutil en reposo
    _VBAR_THUMB_ACTIVE  = "#CC5F5F5F"  # más intenso al pasar el cursor / arrastrar

    def _set_vbar_active(self, active: bool) -> None:
        """Cambia el color del thumb a su estado intenso (hover/arrastre) o reposo."""
        thumb = getattr(self, "_vbar_thumb", None)
        if thumb is None:
            return
        color = self._VBAR_THUMB_ACTIVE if active else self._VBAR_THUMB_IDLE
        if thumb.bgcolor != color:
            thumb.bgcolor = color
            try:
                thumb.update()
            except Exception:
                pass

    def _show_vbar(self) -> None:
        """Muestra la barra (opacidad 1) y programa su auto-ocultado."""
        vbar = getattr(self, "_vbar", None)
        if vbar is None or not vbar.visible:
            return
        if vbar.opacity != 1.0:
            vbar.opacity = 1.0
            try:
                vbar.update()
            except Exception:
                pass
        self._schedule_vbar_hide()

    def _schedule_vbar_hide(self) -> None:
        t = getattr(self, "_vbar_hide_timer", None)
        if t is not None:
            t.cancel()
        t = threading.Timer(self._VBAR_HIDE_DELAY, self._hide_vbar)
        t.daemon = True
        self._vbar_hide_timer = t
        t.start()

    def _hide_vbar(self) -> None:
        """Desvanece la barra salvo que se esté arrastrando o el cursor esté encima."""
        if getattr(self, "_is_closed", False):
            return
        if getattr(self, "_vbar_dragging", False) or getattr(self, "_vbar_hovering", False):
            return
        vbar = getattr(self, "_vbar", None)
        if vbar is None or not vbar.visible or vbar.opacity == 0.0:
            return
        vbar.opacity = 0.0
        try:
            vbar.update()
        except Exception:
            pass

    def _on_vbar_enter(self, e) -> None:
        self._vbar_hovering = True
        self._set_vbar_active(True)
        self._show_vbar()

    def _on_vbar_exit(self, e) -> None:
        self._vbar_hovering = False
        if not getattr(self, "_vbar_dragging", False):
            self._set_vbar_active(False)
        self._schedule_vbar_hide()

    def _set_vbar_thumb_top(self, top: float) -> None:
        """Posiciona el thumb (sólo lo actualiza si se movió apreciablemente)."""
        if abs(getattr(self, "_vbar_thumb_top", 0.0) - top) < 0.5:
            return
        self._vbar_thumb_top  = top
        self._vbar_thumb.top  = top
        try:
            self._vbar_thumb.update()
        except Exception:
            pass

    def _sync_vbar_thumb(self, px: float, max_extent: float) -> None:
        """Reposiciona el thumb vertical según el scroll real (llamado desde
        _on_view_scroll). No hace nada durante un arrastre del propio thumb."""
        if getattr(self, "_vbar_dragging", False):
            return
        if getattr(self, "_vbar", None) is None or not self._vbar.visible:
            return
        travel = getattr(self, "_vbar_travel", 0.0)
        if travel <= 0 or max_extent <= 0:
            return
        self._set_vbar_thumb_top(min(1.0, px / max_extent) * travel)

    def _update_vbar_from_event(self, e) -> None:
        """Actualiza la barra vertical desde un evento de scroll real. Si cambió
        la geometría (alto del viewport o extensión scrolleable) recalcula tamaño;
        si no, sólo reposiciona el thumb (barato)."""
        try:
            px = float(getattr(e, "pixels", None) or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        mx = getattr(e, "max_scroll_extent", None)
        vh = getattr(e, "viewport_dimension", None)
        geom_changed = False
        if vh:
            vh = float(vh)
            if abs((getattr(self, "_vbar_viewport_h", 0.0) or 0.0) - vh) > 0.5:
                self._vbar_viewport_h = vh
                geom_changed = True
        if mx is not None:
            mx = float(mx)
            if abs((getattr(self, "_vbar_max_extent", None) or -1.0) - mx) > 0.5:
                self._vbar_max_extent = mx
                geom_changed = True
        # Durante un arrastre del thumb, nosotros mandamos la posición: sólo
        # absorbemos las dimensiones, sin reposicionar (evita el bucle/jitter).
        if getattr(self, "_vbar_dragging", False):
            return
        if geom_changed:
            self._update_vbar_geometry()
        else:
            self._sync_vbar_thumb(px, getattr(self, "_vbar_max_extent", 0.0) or 0.0)
        # Hay scroll → mostrar la barra y reprogramar el auto-ocultado.
        self._show_vbar()

    def _on_vbar_drag_start(self, e) -> None:
        self._vbar_dragging = True
        self._set_vbar_active(True)
        self._show_vbar()

    def _on_vbar_drag_end(self, e) -> None:
        self._vbar_dragging = False
        if not getattr(self, "_vbar_hovering", False):
            self._set_vbar_active(False)
        self._schedule_vbar_hide()

    def _on_vbar_drag(self, e) -> None:
        """Arrastre del thumb → desplaza viewer_scroll verticalmente. Acumulamos
        el delta sobre la posición del thumb (fuente de verdad propia) para no
        depender del valor leído del control."""
        travel     = getattr(self, "_vbar_travel", 0.0)
        max_extent = getattr(self, "_vbar_max_extent", None)
        if max_extent is None:
            max_extent = max(0.0, self._content_height() -
                             (getattr(self, "_last_viewport_h", 0.0) or 0.0))
        if travel <= 0 or max_extent <= 0:
            return
        new_top = getattr(self, "_vbar_thumb_top", 0.0) + (e.delta_y or 0.0)
        new_top = max(0.0, min(new_top, travel))
        self._vbar_thumb_top = new_top
        self._vbar_thumb.top = new_top
        offset = (new_top / travel) * max_extent
        self._scroll_px = offset
        try:
            self._vbar_thumb.update()
        except Exception:
            pass
        try:
            self.viewer_scroll.scroll_to(offset=offset, duration=0)
        except Exception:
            pass

    def _on_window_resized(self, e=None) -> None:
        """Callback for page.on_resized: recalculate scroll column width so the
        horizontal scrollbar appears/disappears correctly and centering stays
        accurate when the user resizes the app window."""
        if getattr(self, "_is_closed", False) or getattr(self, "_is_suspended", False):
            return
        self._update_scroll_column_width()

    def _update_nav_state(self) -> None:
        if getattr(self, "_is_closed", False):
            return
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        self.page_input.value  = str(self.current_page + 1)
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == total - 1
        item = getattr(self, "_delete_page_menu_item", None)
        if item is not None:
            item.disabled = total <= 1

    def _on_view_scroll(self, e: ft.OnScrollEvent) -> None:
        # En single/double sólo registramos la posición/extensión del scroll para
        # que la navegación por rueda (_single_wheel_nav) sepa cuándo la página
        # actual llegó a su borde superior/inferior. El resto (cálculo de página
        # por punto medio, render LOD, evicción) es exclusivo del modo continuo.
        if getattr(self, "_display_mode", "continuous") != "continuous":
            px = getattr(e, "pixels", None)
            if px is not None:
                self._scroll_px  = float(px)
                self._scroll_max = float(getattr(e, "max_scroll_extent", None) or 0.0)
            vh = getattr(e, "viewport_dimension", None)
            if vh:
                self._last_viewport_h = float(vh)
            self._update_vbar_from_event(e)
            return
        pixels     = getattr(e, "pixels",            None)
        viewport_h = getattr(e, "viewport_dimension", None) or 600.0
        if pixels is None:
            return
        now     = time.monotonic()
        prev_px = getattr(self, "_scroll_px", 0.0)
        prev_t  = getattr(self, "_scroll_t", now)
        self._scroll_px = float(pixels)
        self._scroll_t  = now
        self._last_viewport_h = float(viewport_h)
        self._scrolling = True
        self._schedule_scroll_idle()
        self._update_vbar_from_event(e)

        px, vh = float(pixels), float(viewport_h)

        mid = px + vh / 2.0
        page_changed = False
        idx = bisect.bisect_right(self._page_cum_offsets, mid)
        pn = max(0, idx - 1)
        if 0 <= pn < len(self._page_cum_offsets):
            if pn != self.current_page:
                self.current_page = pn
                self._update_nav_state()
                self._refresh_ocr_ui_for_page()
                page_changed = True

        # Velocidad del scroll (px/seg) decide la calidad del render en vuelo:
        #
        #   · scroll lento/medio  → render a calidad COMPLETA directamente.
        #   · fling rápido        → render del tier PREVIEW (baja resolución,
        #     ~1/4 del coste). Antes no se renderizaba nada en un fling rápido
        #     → las hojas aparecían en blanco mientras scrolleabas. Tras
        #     virtualizar, a 6 alturas/seg apenas pasan ~4 páginas/seg, así que
        #     rasterizar un preview barato por página es asumible y elimina el
        #     hueco en blanco. El handler de idle sube esas páginas a calidad
        #     completa; con gapless_playback el swap preview→nítido no parpadea
        #     a blanco (sólo se afina la nitidez).
        dt       = max(1e-3, now - prev_t)
        velocity = abs(px - prev_px) / dt
        if velocity < vh * 6.0:
            self._render_visible(px, vh, preview=False)
        else:
            self._render_visible(px, vh, preview=True)

        # Evicción y actualización de UI en un solo bloque:
        # si eviccionamos páginas, necesitamos propagar el visible=False a Flutter
        # para liberar las texturas de GPU; se combina con el update de navegación.
        evicted = False
        if abs(px - self._last_evict_px) >= _EVICT_THRESHOLD:
            self._last_evict_px = px
            evicted = self._evict_distant(px, vh)

        if page_changed:
            self._prune_render_cache(self.current_page)
        if page_changed or evicted:
            try:
                self.page_ref.update()
            except Exception:
                pass

    def _show_snack(self, msg: str) -> None:
        self.page_ref.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
        self.page_ref.update()

    # ── navigation ────────────────────────────────────────────────────────────

    def _scroll_to_page(self, pn: int, instant: bool = False) -> None:
        self.current_page = pn
        self._update_nav_state()
        self._render_page_slot(pn)
        self._prefetch_neighbors_preview(pn)
        self._prune_render_cache(pn)
        self._evict_outside_window(pn)
        self._refresh_ocr_ui_for_page()
        display_mode = getattr(self, "_display_mode", "continuous")
        if display_mode in ("single", "double") and getattr(self, "_page_rows", None):
            npages = len(self._page_heights)
            if display_mode == "single":
                for i, row in enumerate(self._page_rows):
                    row.visible = (i == pn)
                content_h = self._page_heights[pn] if pn < npages else 0.0
            else:
                pair_start = (pn // 2) * 2
                for i, row in enumerate(self._page_rows):
                    row.visible = (i == pair_start or i == pair_start + 1)
                if pair_start + 1 < len(self._page_rows):
                    self._render_page_slot(pair_start + 1)
                # Las dos páginas se apilan verticalmente en el Column de scroll.
                content_h = self._page_heights[pair_start] if pair_start < npages else 0.0
                if pair_start + 1 < npages:
                    content_h += _PAGE_GAP + self._page_heights[pair_start + 1]
            # La nueva página arranca en su borde superior. Pre-calcular su
            # extensión scrolleable (alto del contenido − viewport) para que la
            # navegación por rueda sepa de inmediato si cabe entero o hay que
            # desplazarse dentro antes de saltar. Sin esto, una página alta
            # heredaría el max de la anterior y saltaría de golpe.
            self._scroll_px = 0.0
            vh = getattr(self, "_last_viewport_h", 600.0) or 600.0
            self._scroll_max = max(0.0, float(content_h) - vh)
            self._cancel_single_nav_timer()
            # update() primero: oculta las filas en Flutter antes de mover el scroll.
            # Si se envía scroll_to antes de update(), Flutter ve todas las filas
            # visibles al saltar a offset=0 → parpadeo de "todo el documento".
            try:
                self.viewer_scroll.update()
            except Exception:
                pass
            try:
                self.viewer_scroll.scroll_to(offset=0, duration=0)
            except Exception:
                pass
            self.page_ref.update()
            # Pre-renderizar las páginas adyacentes en segundo plano para que el
            # siguiente salto de rueda muestre una imagen ya lista en vez de
            # rasterizar desde cero (lo que causaba el ligero parpadeo blanco).
            self._prefetch_adjacent_pages(pn)
            return
        try:
            self.viewer_scroll.scroll_to(
                offset=self._page_cum_offsets[pn],
                duration=0 if instant else 250,
            )
        except Exception:
            pass
        self.page_ref.update()

    def _prev(self, e=None) -> None:
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        if self.current_page > 0:
            display_mode = getattr(self, "_display_mode", "continuous")
            if display_mode == "double":
                pair_start = (self.current_page // 2) * 2
                self._scroll_to_page(max(0, pair_start - 2))
            else:
                self._scroll_to_page(self.current_page - 1)

    def _next(self, e=None) -> None:
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        if self.current_page < total - 1:
            display_mode = getattr(self, "_display_mode", "continuous")
            if display_mode == "double":
                pair_start = (self.current_page // 2) * 2
                self._scroll_to_page(min(total - 1, pair_start + 2))
            else:
                self._scroll_to_page(self.current_page + 1)

    def _go_to_page(self, e) -> None:
        try:
            n = int(self.page_input.value) - 1
            doc_len = len(self.doc)
            if 0 <= n < doc_len:
                self._scroll_to_page(n)
                return
        except ValueError:
            pass
        self.page_input.value = str(self.current_page + 1)
        self.page_input.update()

    # ── zoom ──────────────────────────────────────────────────────────────────

    def _apply_zoom(self) -> None:
        if getattr(self, "_is_closed", False):
            return
        self.zoom_label.value = f"{int(round(self.zoom * 100))}%"
        saved = self.current_page
        # Preserve fractional position within the current page so zooming
        # keeps the same content centred in the viewport.
        frac = 0.0
        if saved < len(self._page_cum_offsets) and saved < len(self._page_heights):
            page_h = self._page_heights[saved]
            if page_h > 0:
                within = self._scroll_px - self._page_cum_offsets[saved]
                frac = max(0.0, min(1.0, within / page_h))

        # _rebuild_scroll_content (ruta rápida) ya hace viewer_scroll.update()
        # con las nuevas dimensiones; aquí sólo reposicionamos el scroll y
        # consolidamos en UN solo page_ref.update() — antes eran dos, cada uno
        # re-serializaba todo el árbol de la página en cada paso de zoom.
        self._rebuild_scroll_content(scroll_back=False)
        try:
            if saved < len(self._page_cum_offsets) and saved < len(self._page_heights):
                target = self._page_cum_offsets[saved] + frac * self._page_heights[saved]
            else:
                target = self._page_cum_offsets[saved] if saved < len(self._page_cum_offsets) else 0.0
            self.viewer_scroll.scroll_to(offset=target, duration=0)
        except Exception:
            pass
        self.page_ref.update()

    def _on_page_scroll(self, e, pn: int) -> None:
        """Handle scroll-wheel events over a page. Ctrl+Scroll zooms in/out."""
        import time
        # _ctrl_pressed is set by main.py on keydown (Flet has no keyup event).
        # We expire it after 1 s so releasing Ctrl restores normal scroll.
        # On systems with key auto-repeat the Ctrl keydown keeps refreshing
        # _ctrl_time (~30 ms), so zoom works for the entire hold duration.
        ctrl = (
            getattr(self, "_ctrl_pressed", False)
            and (time.monotonic() - getattr(self, "_ctrl_time", 0.0)) < 1.0
        )
        delta = getattr(e, "scroll_delta_y", None)
        if delta is None:
            delta = getattr(e, "delta_y", 0)
        if ctrl:
            if delta < 0:
                self._zoom_in()
            elif delta > 0:
                self._zoom_out()
            return
        # Sin Ctrl: en página única / doble la rueda navega entre páginas
        # (estilo Adobe). El modo continuo deja que el scroll nativo actúe.
        if getattr(self, "_display_mode", "continuous") != "continuous" and delta:
            self._single_wheel_nav(float(delta))

    def _single_wheel_nav(self, delta: float) -> None:
        """Navegación por rueda en modo página única / doble (estilo Adobe).

        Si la página actual no cabe en el viewport, primero se deja desplazar
        dentro de ella; sólo al alcanzar el borde (arriba/abajo) se cambia de
        página. ``delta>0`` = rueda hacia abajo.

        El cambio de página se confirma tras ``_SINGLE_NAV_CONFIRM`` segundos:
        si en ese lapso el scroll interno se movió (página alta cuyo
        ``_scroll_max`` aún no estaba calibrado por un evento real de scroll), se
        cancela. Así no hace falta adivinar la altura del viewport en frío.
        """
        going_down = delta > 0
        scroll_px  = getattr(self, "_scroll_px", 0.0)
        scroll_max = getattr(self, "_scroll_max", 0.0)
        # ¿Puede la página desplazarse en este sentido? Entonces es scroll
        # interno: que lo maneje el scroll nativo, no navegamos.
        if going_down and scroll_px < scroll_max - _SINGLE_EDGE_EPS:
            self._cancel_single_nav_timer()
            return
        if not going_down and scroll_px > _SINGLE_EDGE_EPS:
            self._cancel_single_nav_timer()
            return
        self._schedule_single_nav(going_down, scroll_px)

    def _cancel_single_nav_timer(self) -> None:
        t = getattr(self, "_single_nav_timer", None)
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
            self._single_nav_timer = None

    def _schedule_single_nav(self, going_down: bool, scroll_px: float) -> None:
        if time.monotonic() - getattr(self, "_single_nav_t", 0.0) < _SINGLE_NAV_COOLDOWN:
            return  # enfriamiento: absorbe el resto del "fling"
        self._cancel_single_nav_timer()
        self._single_nav_dir = 1 if going_down else -1
        self._single_nav_px  = scroll_px
        t = threading.Timer(_SINGLE_NAV_CONFIRM, self._fire_single_nav)
        t.daemon = True
        self._single_nav_timer = t
        t.start()

    def _fire_single_nav(self) -> None:
        self._single_nav_timer = None
        if getattr(self, "_is_closed", False):
            return
        # Si el scroll se movió desde que se programó, era desplazamiento interno
        # de una página alta (ya calibrada): no cambiar de página.
        if abs(getattr(self, "_scroll_px", 0.0) - getattr(self, "_single_nav_px", 0.0)) > _SINGLE_EDGE_EPS:
            return
        now = time.monotonic()
        if now - getattr(self, "_single_nav_t", 0.0) < _SINGLE_NAV_COOLDOWN:
            return
        try:
            total = len(self.doc)
        except (ValueError, AttributeError):
            return
        going_down = getattr(self, "_single_nav_dir", 1) > 0
        if going_down and self.current_page < total - 1:
            self._single_nav_t = now
            self._next()
        elif not going_down and self.current_page > 0:
            self._single_nav_t = now
            self._prev()

    def _zoom_out(self, e=None) -> None:
        candidates = [z for z in ZOOM_LEVELS if z < self.zoom - 0.01]
        if candidates:
            self.zoom = candidates[-1]
            self.zoom_label.value = f"{int(round(self.zoom * 100))}%"
            try:
                self.zoom_label.update()
            except Exception:
                pass
            self._schedule_zoom_apply()

    def _zoom_in(self, e=None) -> None:
        candidates = [z for z in ZOOM_LEVELS if z > self.zoom + 0.01]
        if candidates:
            self.zoom = candidates[0]
            self.zoom_label.value = f"{int(round(self.zoom * 100))}%"
            try:
                self.zoom_label.update()
            except Exception:
                pass
            self._schedule_zoom_apply()

    def _schedule_zoom_apply(self) -> None:
        """Debounce zoom rebuilds: espera 120 ms desde el último cambio de nivel."""
        t = getattr(self, "_zoom_timer", None)
        if t is not None:
            t.cancel()
        self._zoom_timer = threading.Timer(0.12, self._apply_zoom)
        self._zoom_timer.start()

    def _set_zoom(self, z: float) -> None:
        self.zoom = z
        self._apply_zoom()

    def _fit_width(self, e=None) -> None:
        with self._doc_lock:
            pw = self.doc[self.current_page].rect.width
        self.zoom = ((self.page_ref.width or 900) - 72) / (pw * BASE_SCALE)
        self._apply_zoom()

    def _fit_page(self, e=None) -> None:
        with self._doc_lock:
            p = self.doc[self.current_page]
            pw, ph = p.rect.width, p.rect.height
        avail_w = (self.page_ref.width  or 900) - 72
        avail_h = (self.page_ref.height or 650) - 180
        self.zoom = min(avail_w / (pw * BASE_SCALE), avail_h / (ph * BASE_SCALE))
        self._apply_zoom()

    # ── other toolbar actions ─────────────────────────────────────────────────

    def _rotate(self, e=None, delta: int = 90) -> None:
        pn = self.current_page
        with self._doc_lock:
            p = self.doc[pn]
            p.set_rotation((p.rotation + delta) % 360)
        self._is_modified = True

        # Girar visualmente la imagen vieja mientras llega el nuevo render.
        # ft.Rotate es un Transform puramente compositor (sin coste de layout):
        # _rebuild_scroll_content ve has_old=True y mantiene la imagen visible,
        # evitando el flash en blanco. El worker limpia img.rotate al terminar.
        img = self._page_images[pn] if pn < len(self._page_images) else None
        if img is not None and (img.src or img.src_base64):
            img.rotate = ft.Rotate(
                angle=math.radians(delta), alignment=ft.alignment.center
            )
            img.fit = ft.ImageFit.CONTAIN
        elif img is not None:
            img.src = img.src_base64 = None
            img.visible = False

        self._ocr_by_page.pop(pn, None)
        self._page_words.pop(pn, None)
        self._page_word_bands.pop(pn, None)
        self._page_blocks_cache.pop(pn, None)
        self._text_rects_cache.pop(pn, None)
        _rcache = getattr(self, "_render_cache", None)
        if _rcache is not None:
            _rcache.invalidate_page(pn)

        saved = pn
        self._rebuild_scroll_content(scroll_back=False)

        # scroll_to primero, luego update: Flutter aplica el nuevo layout y
        # posiciona antes de que el render asíncrono llegue.
        try:
            self.viewer_scroll.scroll_to(offset=self._page_cum_offsets[saved], duration=0)
        except Exception:
            pass
        self.page_ref.update()

        # Forzar render inmediato de la página rotada y de las vecinas visibles.
        # _rebuild_scroll_content solo re-renderiza las primeras _PRELOAD páginas,
        # lo que deja sin actualizar cualquier página fuera de ese rango inicial.
        self._render_page_slot(pn)
        self._schedule_scroll_idle()

    def _rotate_ccw(self, e=None) -> None:
        """Rotar la página actual 90° en sentido antihorario."""
        self._rotate(delta=-90)

    def _rotate_180(self, e=None) -> None:
        """Voltear la página actual 180°."""
        self._rotate(delta=180)

    def _rotate_180_all(self, e=None) -> None:
        """Voltear todas las páginas del documento 180°."""
        with self._doc_lock:
            n = len(self.doc)
            for i in range(n):
                p = self.doc[i]
                p.set_rotation((p.rotation + 180) % 360)
        self._is_modified = True

        # Para 180° las dimensiones del slot no cambian (W×H igual), así que
        # aplicar ft.Rotate(π) sobre las imágenes construidas evita el flash en
        # blanco: el fast-resize path ve has_old=True y mantiene todo visible.
        rot_angle = math.radians(180)
        for img in self._page_images:
            if img is not None and (img.src or img.src_base64):
                img.rotate = ft.Rotate(angle=rot_angle, alignment=ft.alignment.center)
                img.fit = ft.ImageFit.CONTAIN
            elif img is not None:
                img.src = img.src_base64 = None
                img.visible = False

        self._ocr_by_page.clear()
        self._page_words.clear()
        self._page_word_bands.clear()
        self._page_blocks_cache.clear()
        self._text_rects_cache.clear()
        _rcache = getattr(self, "_render_cache", None)
        if _rcache is not None:
            _rcache.clear()

        saved = self.current_page
        self._rebuild_scroll_content(scroll_back=False)
        try:
            self.viewer_scroll.scroll_to(offset=self._page_cum_offsets[saved], duration=0)
        except Exception:
            pass
        self.page_ref.update()
        self._render_page_slot(saved)
        self._schedule_scroll_idle()

    def _save(self, e=None) -> None:
        self._save_picker.save_file(
            dialog_title="Guardar PDF con anotaciones",
            file_name=self.filename,
            allowed_extensions=["pdf"],
        )

    def _save_in_place(self, e=None, _close_after: bool = False) -> None:
        """Sobreescribe el archivo PDF original con los cambios actuales.

        Usa tobytes() para serializar en memoria y write_bytes() para escribir
        directamente sobre el original, evitando problemas de bloqueo de archivos
        en Windows que surgirían con un fichero temporal + os.replace().
        """
        if not PDFSecurityManager.can_save_changes(self.doc):
            self._show_snack(
                "Este PDF no permite guardar cambios por sus permisos de seguridad"
            )
            return

        original = Path(self.path)
        try:
            with self._doc_lock:
                data = self.doc.tobytes(garbage=4, deflate=True)
            original.write_bytes(data)
            self._is_modified = False
            self._has_content_changes = False
            self._doc_initial_state = self._compute_doc_state()
            self._show_snack(f"Guardado: {original.name}")
            if _close_after:
                self.on_close(self)
        except PermissionError:
            self._show_snack(
                "Sin permiso para sobrescribir el archivo. "
                "Usa 'Guardar PDF como…' para guardarlo en otra ubicación."
            )
        except Exception as ex:
            self._show_snack(f"Error al guardar: {ex}")

    def _on_save_result(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        # Garantizar la extensión .pdf: allowed_extensions no la fuerza en todas
        # las plataformas, así que si el usuario escribe el nombre sin ella el
        # archivo quedaría sin extensión.
        path = e.path
        if Path(path).suffix.lower() != ".pdf":
            path += ".pdf"
        try:
            if not PDFSecurityManager.can_save_changes(self.doc):
                self._show_snack("Este PDF no permite guardar cambios por sus permisos de seguridad")
                return
            with self._doc_lock:
                self.doc.save(path, garbage=4, deflate=True)
            self._is_modified = False
            self._has_content_changes = False
            self._doc_initial_state = self._compute_doc_state()
            self._show_snack(f"Guardado: {Path(path).name}")
            if self._pending_close_after_save:
                self._pending_close_after_save = False
                self.on_close(self)
        except Exception as ex:
            self._pending_close_after_save = False
            self._show_snack(f"Error al guardar: {ex}")

    # ── undo ──────────────────────────────────────────────────────────────────

    def _undo(self, e=None) -> None:
        with self._doc_lock:
            pn = self._annot.undo_last(self.doc)
        if pn is not None:
            self._is_modified = True
            self._refresh_page(pn)
        else:
            self._show_snack("Nada que deshacer")

    def _redo(self, e=None) -> None:
        with self._doc_lock:
            pn = self._annot.redo_last(self.doc)
        if pn is not None:
            self._is_modified = True
            self._refresh_page(pn)
        else:
            self._show_snack("Nada que rehacer")
