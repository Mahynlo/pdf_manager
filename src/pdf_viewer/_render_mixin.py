"""Rendering, navigation, zoom and save behaviour for PDFViewerTab."""
from __future__ import annotations

import threading
from pathlib import Path

import flet as ft
import fitz

from .annotations import Tool
from .renderer import BASE_SCALE, ZOOM_LEVELS, render_page
from ._viewer_defs import (
    _PAGE_BG, _PAGE_GAP, _PRELOAD, _EVICT_MARGIN, _EVICT_THRESHOLD,
    _SELECTED_BG,
)


class _RenderMixin:
    """Page rendering, viewport management, navigation and zoom."""

    # ── per-page control factory ──────────────────────────────────────────────

    def _rebuild_scroll_content(self, scroll_back: bool = True) -> None:
        """(Re)build all page slot controls. Called on init and after zoom/rotate."""
        self._render_gen    += 1
        self._rendering      = set()
        self._last_evict_px  = -9999.0

        with self._doc_lock:
            total = len(self.doc)

        self._page_images      = []
        self._drag_overlays    = []
        self._sel_overlays     = []
        self._ocr_overlays     = []
        self._text_sel_layers  = []
        self._redact_overlays  = []
        self._page_slots       = []
        self._page_gestures    = []
        self._page_cum_offsets = []
        self._page_heights     = []
        self._rendered             = set()
        self._selected             = None
        self._page_words           = {}
        self._text_sel_pn          = None
        self._text_sel_text        = ""
        self._text_sel_start_pdf   = None
        self._text_sel_end_pdf     = None
        self._text_sel_sel_rect    = None
        self._text_sel_popups      = []
        self._annot_popups         = []
        self._annot_popup_pn       = None

        cum   = 0.0
        rows: list[ft.Control] = []

        with self._doc_lock:
            page_dims = [
                (int(self.doc[pn].rect.width  * BASE_SCALE * self.zoom),
                 int(self.doc[pn].rect.height * BASE_SCALE * self.zoom))
                for pn in range(total)
            ]

        for pn in range(total):
            w, h = page_dims[pn]

            img = ft.Image(
                width=w, height=h, fit=ft.ImageFit.NONE, gapless_playback=True,
                color="#FFFFFFFF" if self._night_mode else None,
                color_blend_mode=ft.BlendMode.DIFFERENCE if self._night_mode else None,
            )
            drag_ov = ft.Container(
                visible=False,
                bgcolor=self._annot.overlay_color,
                border=ft.border.all(1, "#0055AA"),
                left=0, top=0, width=0, height=0,
            )
            sel_ov = ft.Container(
                visible=False,
                bgcolor="#200055FF",
                border=ft.border.all(2, "#0055FF"),
                left=0, top=0, width=0, height=0,
            )
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

            self._page_images.append(img)
            self._drag_overlays.append(drag_ov)
            self._sel_overlays.append(sel_ov)
            self._ocr_overlays.append(ocr_ov)
            self._text_sel_layers.append(text_sel_ov)
            self._redact_overlays.append(redact_ov)
            self._text_sel_popups.append(popup_ov)
            self._annot_popups.append(annot_popup_ov)
            self._page_cum_offsets.append(cum)
            self._page_heights.append(float(h))
            cum += h + _PAGE_GAP

            slot = ft.Container(
                content=ft.Stack(
                    [img, text_sel_ov, drag_ov, sel_ov, ocr_ov, redact_ov, popup_ov, annot_popup_ov],
                    clip_behavior=ft.ClipBehavior.NONE,
                ),
                width=w, height=h,
                bgcolor=_PAGE_BG,
                border_radius=2,
                # NONE allows floating popups (popup_ov / annot_popup_ov) to
                # paint outside the page boundary without being clipped.
                clip_behavior=ft.ClipBehavior.NONE,
            )
            self._page_slots.append(slot)

            gd = ft.GestureDetector(
                content=slot,
                on_tap_down   = lambda e, p=pn: self._on_tap_down(e, p),
                on_tap        = lambda e, p=pn: self._on_tap(e, p),
                on_pan_start  = lambda e, p=pn: self._on_pan_start(e, p),
                on_pan_update = lambda e, p=pn: self._on_pan_update(e, p),
                on_pan_end    = lambda e, p=pn: self._on_pan_end(e, p),
                mouse_cursor  = self._current_cursor,
            )
            self._page_gestures.append(gd)
            rows.append(ft.Row([gd], alignment=ft.MainAxisAlignment.CENTER))

        self.viewer_scroll.controls = rows

        for pn in range(min(total, 1 + _PRELOAD)):
            self._render_page_slot(pn)

        if scroll_back and self._page_cum_offsets:
            try:
                self.viewer_scroll.scroll_to(
                    offset=self._page_cum_offsets[self.current_page], duration=0,
                )
            except Exception:
                pass

    def _render_page_slot(self, pn: int) -> None:
        """Schedule a background render for one page (no-op if already rendered)."""
        if pn in self._rendered or pn in self._rendering:
            return
        self._rendering.add(pn)
        gen = self._render_gen

        def _worker() -> None:
            try:
                with self._doc_lock:
                    if gen != self._render_gen or pn >= len(self._page_images):
                        return
                    b64, w, h = render_page(self.doc, pn, self.zoom)
                if gen != self._render_gen or pn >= len(self._page_images):
                    return
                img  = self._page_images[pn]
                slot = self._page_slots[pn]
                img.src_base64 = b64
                img.width      = w
                img.height     = h
                slot.bgcolor   = None
                self._rendered.add(pn)
                try:
                    slot.update()
                except Exception:
                    pass
            finally:
                self._rendering.discard(pn)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_visible(self, pixels: float, viewport_h: float) -> None:
        margin = viewport_h * 0.5
        top    = pixels - margin
        bottom = pixels + viewport_h + margin
        for pn, (start, h) in enumerate(zip(self._page_cum_offsets, self._page_heights)):
            if start + h >= top and start <= bottom:
                self._render_page_slot(pn)

    def _evict_distant(self, pixels: float, viewport_h: float) -> None:
        keep_top    = pixels - viewport_h * _EVICT_MARGIN
        keep_bottom = pixels + viewport_h * (1.0 + _EVICT_MARGIN)
        for pn, (start, h) in enumerate(zip(self._page_cum_offsets, self._page_heights)):
            if pn not in self._rendered:
                continue
            page_bottom = start + h
            if page_bottom < keep_top or start > keep_bottom:
                self._rendered.discard(pn)
                self._page_images[pn].src_base64 = None
                self._page_slots[pn].bgcolor = _PAGE_BG

    # ── render / update ───────────────────────────────────────────────────────

    def _refresh_page(self, pn: int) -> None:
        if self._selected is not None and self._selected[0] == pn:
            self._selected = None
            self._sel_overlays[pn].visible = False
            self._annot_action_bar.visible = False
        self._rendered.discard(pn)
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
        pixels     = getattr(e, "pixels",            None)
        viewport_h = getattr(e, "viewport_dimension", None) or 600.0
        if pixels is None:
            return
        self._scroll_px = float(pixels)

        mid = float(pixels) + float(viewport_h) / 2.0
        page_changed = False
        for pn in range(len(self._page_cum_offsets) - 1, -1, -1):
            if self._page_cum_offsets[pn] <= mid:
                if pn != self.current_page:
                    self.current_page = pn
                    self._update_nav_state()
                    self._refresh_ocr_ui_for_page()
                    page_changed = True
                break

        px, vh = float(pixels), float(viewport_h)
        self._render_visible(px, vh)
        if page_changed:
            try:
                self.page_ref.update()
            except Exception:
                pass
        if abs(px - self._last_evict_px) >= _EVICT_THRESHOLD:
            self._last_evict_px = px
            self._evict_distant(px, vh)

    def _show_snack(self, msg: str) -> None:
        self.page_ref.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
        self.page_ref.update()

    # ── navigation ────────────────────────────────────────────────────────────

    def _scroll_to_page(self, pn: int) -> None:
        self.current_page = pn
        self._update_nav_state()
        self._render_page_slot(pn)
        self._refresh_ocr_ui_for_page()
        try:
            self.viewer_scroll.scroll_to(offset=self._page_cum_offsets[pn], duration=250)
        except Exception:
            pass
        self.page_ref.update()

    def _prev(self, e=None) -> None:
        if self.current_page > 0:
            self._scroll_to_page(self.current_page - 1)

    def _next(self, e=None) -> None:
        if self.current_page < len(self.doc) - 1:
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
        self.zoom_label.value = f"{int(round(self.zoom * 100))}%"
        saved = self.current_page
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        try:
            self.viewer_scroll.scroll_to(offset=self._page_cum_offsets[saved], duration=0)
        except Exception:
            pass
        self.page_ref.update()

    def _zoom_out(self, e=None) -> None:
        candidates = [z for z in ZOOM_LEVELS if z < self.zoom - 0.01]
        if candidates:
            self.zoom = candidates[-1]
            self._apply_zoom()

    def _zoom_in(self, e=None) -> None:
        candidates = [z for z in ZOOM_LEVELS if z > self.zoom + 0.01]
        if candidates:
            self.zoom = candidates[0]
            self._apply_zoom()

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
