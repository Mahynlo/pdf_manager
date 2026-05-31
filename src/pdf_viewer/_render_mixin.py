"""Rendering, navigation, zoom and save behaviour for PDFViewerTab."""
from __future__ import annotations

import bisect
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
    _CACHE_KEEP_PAGES, _TEXT_CACHE_KEEP_PAGES,
    _PREVIEW_MAX_ZOOM, _PREVIEW_QUALITY, _PREVIEW_MIN_ZOOM,
    _SCROLL_IDLE_DELAY, _SELECTED_BG,
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

        # ── Fast-resize path ──────────────────────────────────────────────────
        # When the page count is unchanged (zoom / rotate), reuse all existing
        # Flet controls and only update their dimensions + clear stale images.
        # This avoids recreating ~20 controls × N pages on every zoom change.
        if len(self._page_images) == total and total > 0:
            self._rendered       = set()
            self._previewed      = set()
            self._selected       = None
            self._page_words     = {}
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

                self._page_cum_offsets[pn] = cum
                self._page_heights[pn]     = float(h)
                cum += h + _PAGE_GAP

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

        self._page_images      = []
        self._drag_overlays    = []
        self._sel_overlays     = []
        self._sel_handles      = []
        self._ocr_overlays     = []
        self._text_sel_layers  = []
        self._redact_overlays  = []
        self._loading_overlays = []
        self._ink_canvases     = []
        self._page_slots       = []
        self._page_gestures    = []
        self._page_rows        = []
        self._page_cum_offsets = []
        self._page_heights     = []
        self._rendered             = set()
        self._selected             = None
        self._page_words           = {}
        self._text_sel_start_pn    = None
        self._text_sel_end_pn      = None
        self._text_sel_text        = ""
        self._text_sel_start_pdf   = None
        self._text_sel_end_pdf     = None
        self._text_sel_sel_rect    = None
        self._smart_text_sel_active = False
        self._sel_drag_handle      = None
        self._text_sel_popups      = []
        self._annot_popups         = []
        self._annot_popup_pn       = None

        cum   = 0.0
        rows: list[ft.Control] = []

        for pn in range(total):
            w, h = page_dims[pn]

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
            _ctx_btn = ft.ButtonStyle(
                padding=ft.padding.all(5),
                shape=ft.RoundedRectangleBorder(radius=4),
            )
            _mc_color_sep  = ft.Container(width=1, height=22, bgcolor="#E0E0E0")
            _mc_color_btn  = ft.IconButton(
                ft.Icons.PALETTE_OUTLINED,
                icon_color="#7B1FA2",
                icon_size=18,
                tooltip="Cambiar color",
                on_click=self._recolor_selected_menu,
                style=_ctx_btn,
            )
            _mc_scale_sep  = ft.Container(width=1, height=22, bgcolor="#E0E0E0")
            _mc_scale_down = ft.IconButton(
                ft.Icons.REMOVE_CIRCLE_OUTLINE,
                icon_color="#555555",
                icon_size=18,
                tooltip="Reducir",
                on_click=self._scale_down_selected,
                style=_ctx_btn,
            )
            _mc_scale_up   = ft.IconButton(
                ft.Icons.ADD_CIRCLE_OUTLINE,
                icon_color="#555555",
                icon_size=18,
                tooltip="Agrandar",
                on_click=self._scale_up_selected,
                style=_ctx_btn,
            )
            _mc_width_sep  = ft.Container(width=1, height=22, bgcolor="#E0E0E0")
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
                bgcolor="#FFFFFF",
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=4, vertical=3),
                shadow=ft.BoxShadow(
                    blur_radius=10, spread_radius=1,
                    color="#33000000", offset=ft.Offset(0, 2),
                ),
                border=ft.border.all(1, "#D0D0D0"),
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
                        _mc_color_sep,
                        _mc_color_btn,
                        _mc_scale_sep,
                        _mc_scale_down,
                        _mc_scale_up,
                        _mc_width_sep,
                        _mc_width_down,
                        _mc_width_up,
                        ft.Container(width=1, height=22, bgcolor="#E0E0E0"),
                        ft.IconButton(
                            ft.Icons.CLOSE,
                            icon_color="#9E9E9E",
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
            sel_rot_group_inner = ft.Stack(
                [sel_border, sel_tl, sel_tr, sel_bl, sel_br],
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
            self._sel_handles.append({
                "border":     sel_border,
                "tl":         sel_tl,
                "tr":         sel_tr,
                "bl":         sel_bl,
                "br":         sel_br,
                "menu":       sel_menu,
                "rot_group":  sel_rot_group,
                "color_sep":  _mc_color_sep,
                "color_btn":  _mc_color_btn,
                "scale_sep":  _mc_scale_sep,
                "scale_down": _mc_scale_down,
                "scale_up":   _mc_scale_up,
                "width_sep":  _mc_width_sep,
                "width_down": _mc_width_down,
                "width_up":   _mc_width_up,
            })
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
                        icon_color="#5E5E5E",
                        on_click=self._text_sel_copy,
                        style=_btn_style,
                    ),
                    ft.Container(width=1, height=20, bgcolor="#E0E0E0"),
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
                    ft.Container(width=1, height=20, bgcolor="#E0E0E0"),
                    ft.TextButton(
                        "Censurar",
                        icon=ft.Icons.VISIBILITY_OFF,
                        icon_color="#B71C1C",
                        on_click=lambda e: self._text_sel_send_to_redact(),
                        style=_btn_style,
                    ),
                    ft.Container(width=1, height=20, bgcolor="#E0E0E0"),
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
                        icon_color="#9E9E9E",
                        tooltip="Cerrar selección",
                        on_click=self._text_sel_dismiss,
                        style=ft.ButtonStyle(padding=ft.padding.all(4)),
                    ),
                ], spacing=0, tight=True, wrap=True, run_spacing=2,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                left=0, top=0, visible=False,
                bgcolor="#FAFAFA",
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                shadow=ft.BoxShadow(
                    blur_radius=12, spread_radius=1,
                    color="#44000000", offset=ft.Offset(0, 3),
                ),
                border=ft.border.all(1, "#D0D0D0"),
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
                    ft.Container(width=1, height=20, bgcolor="#E0E0E0"),
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
                        icon_color="#9E9E9E",
                        tooltip="Cerrar",
                        on_click=self._hide_annot_popup,
                        style=ft.ButtonStyle(padding=ft.padding.all(4)),
                    ),
                ], spacing=0, tight=True,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                left=0, top=0, visible=False,
                bgcolor="#FAFAFA",
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                shadow=ft.BoxShadow(
                    blur_radius=12, spread_radius=1,
                    color="#44000000", offset=ft.Offset(0, 3),
                ),
                border=ft.border.all(1, "#D0D0D0"),
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

            self._page_images.append(img)
            self._drag_overlays.append(drag_ov)
            self._sel_overlays.append(sel_ov)
            self._ocr_overlays.append(ocr_ov)
            self._text_sel_layers.append(text_sel_ov)
            self._redact_overlays.append(redact_ov)
            self._loading_overlays.append(loading_ov)
            self._ink_canvases.append(ink_canvas)
            self._text_sel_popups.append(popup_ov)
            self._annot_popups.append(annot_popup_ov)
            self._page_cum_offsets.append(cum)
            self._page_heights.append(float(h))
            cum += h + _PAGE_GAP

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
            self._page_slots.append(slot)

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
            self._page_gestures.append(gd)
            row = ft.Row([gd], alignment=ft.MainAxisAlignment.CENTER)
            self._page_rows.append(row)
            rows.append(row)

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
        total = len(self.doc)
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
        total = len(self.doc)
        radius = max(0, (_CACHE_KEEP_PAGES - 1) // 2)
        start = max(0, center_page - radius)
        end = min(total, center_page + radius + 1)
        keep_pages = set(range(start, end))
        try:
            cache.keep_pages(keep_pages)
        except Exception:
            pass

    def _evict_outside_window(self, center_page: int) -> bool:
        total = len(self.doc)
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
            img.src = None
            img.src_base64 = None
            img.visible = False
            if pn < len(loading_overlays):
                loading_overlays[pn].visible = True
            evicted = True
        return evicted

    def _render_page_slot(self, pn: int, preview: bool = False) -> None:
        """Schedule a background render for one page (no-op if already rendered)."""
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
        total = len(self.doc)
        radius = max(0, (_CACHE_KEEP_PAGES - 1) // 2)
        start = max(0, center - radius)
        end = min(total, center + radius + 1)
        for pn in range(start, end):
            self._render_page_slot(pn, preview=True)

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
                self._page_images[pn].src = None
                self._page_images[pn].src_base64 = None
                self._page_images[pn].visible = False
                if pn < len(loading_overlays):
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

    def _update_nav_state(self) -> None:
        total = len(self.doc)
        self.page_input.value  = str(self.current_page + 1)
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == total - 1

    def _on_view_scroll(self, e: ft.OnScrollEvent) -> None:
        if getattr(self, "_display_mode", "continuous") != "continuous":
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

        # Velocidad del scroll (px/seg). En un fling rápido no alcanzamos a
        # rasterizar antes de que la página salga de pantalla → el preview
        # borroso aparece y "salta" a nítido (parpadeo). Mejor NO renderizar
        # durante el fling (placeholder limpio) y dejar que el handler de idle
        # (0.2 s tras detenerse) renderice nítido lo que quedó visible. En
        # scroll lento/medio sí renderizamos, y a calidad COMPLETA (sin paso
        # intermedio borroso): un solo cambio de imagen, sin parpadeo.
        dt       = max(1e-3, now - prev_t)
        velocity = abs(px - prev_px) / dt
        if velocity < vh * 6.0:
            self._render_visible(px, vh, preview=False)

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

    def _scroll_to_page(self, pn: int) -> None:
        self.current_page = pn
        self._update_nav_state()
        self._render_page_slot(pn)
        self._prefetch_neighbors_preview(pn)
        self._prune_render_cache(pn)
        self._evict_outside_window(pn)
        self._refresh_ocr_ui_for_page()
        display_mode = getattr(self, "_display_mode", "continuous")
        if display_mode in ("single", "double") and getattr(self, "_page_rows", None):
            if display_mode == "single":
                for i, row in enumerate(self._page_rows):
                    row.visible = (i == pn)
            else:
                pair_start = (pn // 2) * 2
                for i, row in enumerate(self._page_rows):
                    row.visible = (i == pair_start or i == pair_start + 1)
                if pair_start + 1 < len(self._page_rows):
                    self._render_page_slot(pair_start + 1)
            try:
                self.viewer_scroll.update()
            except Exception:
                pass
            self.page_ref.update()
            return
        try:
            self.viewer_scroll.scroll_to(offset=self._page_cum_offsets[pn], duration=250)
        except Exception:
            pass
        self.page_ref.update()

    def _prev(self, e=None) -> None:
        total = len(self.doc)
        if self.current_page > 0:
            display_mode = getattr(self, "_display_mode", "continuous")
            if display_mode == "double":
                pair_start = (self.current_page // 2) * 2
                self._scroll_to_page(max(0, pair_start - 2))
            else:
                self._scroll_to_page(self.current_page - 1)

    def _next(self, e=None) -> None:
        total = len(self.doc)
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
            if 0 <= n < len(self.doc):
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
        if not ctrl:
            return
        delta = getattr(e, "scroll_delta_y", None)
        if delta is None:
            delta = getattr(e, "delta_y", 0)
        if delta < 0:
            self._zoom_in()
        elif delta > 0:
            self._zoom_out()

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

    def _rotate(self, e=None) -> None:
        with self._doc_lock:
            p = self.doc[self.current_page]
            p.set_rotation((p.rotation + 90) % 360)
        self._ocr_by_page.pop(self.current_page, None)
        saved = self.current_page
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        try:
            self.viewer_scroll.scroll_to(offset=self._page_cum_offsets[saved], duration=0)
        except Exception:
            pass
        self.page_ref.update()

    def _save(self, e=None) -> None:
        self._save_picker.save_file(
            dialog_title="Guardar PDF con anotaciones",
            file_name=self.filename,
            allowed_extensions=["pdf"],
        )

    def _on_save_result(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        try:
            if not PDFSecurityManager.can_save_changes(self.doc):
                self._show_snack("Este PDF no permite guardar cambios por sus permisos de seguridad")
                return
            with self._doc_lock:
                self.doc.save(e.path, garbage=4, deflate=True)
            self._show_snack(f"Guardado: {Path(e.path).name}")
        except Exception as ex:
            self._show_snack(f"Error al guardar: {ex}")

    # ── undo ──────────────────────────────────────────────────────────────────

    def _undo(self, e=None) -> None:
        with self._doc_lock:
            pn = self._annot.undo_last(self.doc)
        if pn is not None:
            self._refresh_page(pn)
        else:
            self._show_snack("Nada que deshacer")
