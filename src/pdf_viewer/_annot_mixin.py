"""Annotation selection, editing and text-action dialogs for PDFViewerTab."""
from __future__ import annotations

import flet as ft
import fitz

from .annotations import HIGHLIGHT_COLORS, Tool
from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG, _rgb_to_hex

# Pixel size of each corner handle (must match _render_mixin.py constant).
_HS  = 10
_HHS = _HS / 2
# Extra height added to sel_ov so the context menu (below the annotation) is
# within the container's hit-test region (Flutter ignores clicks outside bounds).
_MENU_EXTRA = 52


class _AnnotMixin:
    """Annotation tool selection, selection overlay and edit operations."""

    # ── tool selection ────────────────────────────────────────────────────────

    def _select_tool(self, tool: Tool, cursor: ft.MouseCursor) -> None:
        # CURSOR is the smart pointer (text + annotation); keep text selection
        # visible when switching between annotation drawing tools and back to it.
        if tool not in (Tool.SELECT, Tool.CURSOR):
            self._hide_text_sel_bar()
        self._hide_annot_popup()
        self._annot.set_tool(tool)
        self._current_cursor = cursor
        for gd in self._page_gestures:
            gd.mouse_cursor = cursor
            gd.update()
        for t, btn in self._tool_btns.items():
            btn.bgcolor = _SELECTED_BG if t == tool else None
            btn.update()

    def _set_highlight_color(self, rgb: tuple[float, float, float]) -> None:
        self._annot.highlight_color = rgb
        self._select_tool(Tool.HIGHLIGHT, ft.MouseCursor.PRECISE)
        self._show_snack("Color de resaltado actualizado")

    # ── annotation floating popup (for text-markup annotations) ───────────────

    def _show_annot_popup(self, pn: int, xref: int, pdf_rect: fitz.Rect) -> None:
        self._hide_annot_popup()
        self._selected = (pn, xref)
        if pn >= len(self._annot_popups):
            return
        scale  = self.zoom * BASE_SCALE
        popup  = self._annot_popups[pn]

        _POPUP_H = 44
        _POPUP_W = 200
        _MARGIN  = 8

        page_h = float(self._page_heights[pn]) if pn < len(self._page_heights) else 9999.0
        page_w = float(self._page_slots[pn].width or 9999) if pn < len(self._page_slots) else 9999.0

        below_top = pdf_rect.y1 * scale + _MARGIN
        above_top = pdf_rect.y0 * scale - _POPUP_H - _MARGIN

        popup.top  = below_top if below_top + _POPUP_H <= page_h - _MARGIN else max(_MARGIN, above_top)
        popup.left = max(0.0, min(pdf_rect.x0 * scale, page_w - _POPUP_W))

        popup.visible = True
        self._annot_popup_pn = pn
        try:
            popup.update()
        except Exception:
            pass

    def _hide_annot_popup(self, e=None) -> None:
        pn = self._annot_popup_pn
        if pn is not None and pn < len(self._annot_popups):
            popup = self._annot_popups[pn]
            if popup.visible:
                popup.visible = False
                try:
                    popup.update()
                except Exception:
                    pass
        self._annot_popup_pn = None

    def _annot_popup_delete(self, e=None) -> None:
        self._hide_annot_popup()
        self._delete_selected()

    def _annot_popup_recolor(self, e=None) -> None:
        self._hide_annot_popup()
        self._recolor_selected_menu()

    # ── selection overlay helpers ─────────────────────────────────────────────

    def _apply_overlay_style(
        self, pn: int, annot: fitz.Annot, W: float, H: float,
    ) -> None:
        """Restyle the selection border so it visually matches the annotation
        type/colour.  Makes the overlay read as a live ghost of the annotation
        while its real image is hidden during drag.
        """
        if pn >= len(self._sel_handles):
            return
        atype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
        self._selected_atype = atype

        h = self._sel_handles[pn]

        # Fixed neutral border regardless of annotation color
        h["border"].border_radius = 2
        h["border"].bgcolor = None
        h["border"].border  = ft.border.all(2, "#555555")

        # Markup annotations (highlight/underline/strikeout) cannot be
        # moved or resized — hide corner handles and size/thickness buttons.
        is_markup  = atype in ("Highlight", "Underline", "StrikeOut", "Squiggly")
        no_recolor = atype in ("Squiggly",)
        for name in ("tl", "tr", "bl", "br"):
            h[name].visible = not is_markup
        for name in ("scale_sep", "scale_down", "scale_up", "width_sep", "width_down", "width_up"):
            h[name].visible = not is_markup
        for name in ("color_sep", "color_btn"):
            h[name].visible = not no_recolor

    def _update_sel_handles(self, pn: int, W: float, H: float) -> None:
        """Position all handle/menu controls inside the sel_overlay Stack."""
        if pn >= len(self._sel_handles):
            return
        h = self._sel_handles[pn]

        # The rotatable group (border + handles + rot knob) occupies the
        # bbox rect. The context menu sits outside this group so it does
        # not rotate with the annotation.
        if "rot_group" in h:
            h["rot_group"].left   = 0
            h["rot_group"].top    = 0
            h["rot_group"].width  = W
            h["rot_group"].height = H

        h["border"].width  = W
        h["border"].height = H
        h["border"].border_radius = 2

        h["tl"].left = -_HHS;     h["tl"].top = -_HHS
        h["tr"].left = W - _HHS;  h["tr"].top = -_HHS
        h["bl"].left = -_HHS;     h["bl"].top = H - _HHS
        h["br"].left = W - _HHS;  h["br"].top = H - _HHS

        # Context menu: just below the bbox, left-aligned.
        h["menu"].left = 0
        h["menu"].top  = H + 6
        h["menu"].visible = True

    # ── annotation selection overlay ──────────────────────────────────────────

    def _select_annot(self, pn: int, annot: fitz.Annot) -> None:
        if self._selected is not None and self._selected[0] != pn:
            old_pn = self._selected[0]
            if old_pn < len(self._sel_overlays):
                self._sel_overlays[old_pn].visible = False
                if old_pn < len(self._sel_handles):
                    self._sel_handles[old_pn]["menu"].visible = False
                try:
                    self._sel_overlays[old_pn].update()
                except Exception:
                    pass

        self._selected = (pn, annot.xref)

        pdf_rect = fitz.Rect(annot.rect)
        self._selected_rect        = pdf_rect
        self._selected_visual_rect = fitz.Rect(pdf_rect)

        self._apply_overlay_style(pn, annot, 0, 0)
        self._refresh_selected_overlay(pn, annot_rect=self._selected_visual_rect)

    def _get_selected_annot(self) -> fitz.Annot | None:
        if self._selected is None:
            return None
        pn, xref = self._selected
        with self._doc_lock:
            page = self.doc[pn]
            for annot in page.annots():
                if annot.xref == xref:
                    return annot
        return None

    def _refresh_selected_overlay(self, pn: int, annot_rect: fitz.Rect | None = None) -> None:
        """Reposition the selection overlay for the annotation on page *pn*."""
        if annot_rect is None:
            if self._selected is None:
                return
            if self._selected_visual_rect is not None:
                annot_rect = fitz.Rect(self._selected_visual_rect)
            elif self._selected_rect is not None:
                annot_rect = fitz.Rect(self._selected_rect)
            else:
                xref = self._selected[1]
                with self._doc_lock:
                    page = self.doc[pn]
                    annot_rect = next(
                        (fitz.Rect(a.rect) for a in page.annots() if a.xref == xref),
                        None,
                    )
                if annot_rect is None:
                    self._deselect_annot()
                    return

        self._selected_visual_rect = fitz.Rect(annot_rect)
        self._selected_rect        = fitz.Rect(annot_rect)

        scale = self.zoom * BASE_SCALE
        r     = annot_rect
        W     = max(2.0, r.width  * scale)
        H     = max(2.0, r.height * scale)

        sel_ov = self._sel_overlays[pn]
        sel_ov.left    = r.x0 * scale
        sel_ov.top     = r.y0 * scale
        sel_ov.width   = W
        sel_ov.height  = H + _MENU_EXTRA
        sel_ov.visible = True

        self._update_sel_handles(pn, W, H)

        try:
            sel_ov.update()
        except Exception:
            pass

    def _deselect_annot(self, e=None) -> None:
        self._hide_annot_popup()
        if self._selected is None:
            return
        pn = self._selected[0]
        # If a drag left the annotation hidden (e.g. tool changed mid-drag),
        # unhide before dropping the reference so it doesn't stay invisible.
        if self._drag_annot_hidden:
            try:
                with self._doc_lock:
                    self._annot.set_annot_hidden(
                        self.doc, pn, self._selected[1], False
                    )
            except Exception:
                pass
            self._drag_annot_hidden = False
            self._rerender_page_image(pn)
        self._selected = None
        self._selected_rect = None
        self._selected_visual_rect = None
        self._selected_atype = None
        self._drag_mode = None
        if pn < len(self._sel_overlays):
            self._sel_overlays[pn].visible = False
            if pn < len(self._sel_handles):
                self._sel_handles[pn]["menu"].visible = False
            try:
                self._sel_overlays[pn].update()
            except Exception:
                pass

    # ── edit operations ───────────────────────────────────────────────────────

    def _delete_selected(self, e=None) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected
        with self._doc_lock:
            deleted = self._annot.delete_annot(self.doc, pn, xref)
        if deleted:
            self._deselect_annot()   # oculta overlay + action bar, limpia self._selected
            self._refresh_page(pn)
        else:
            self._show_snack("No se pudo eliminar la anotación")

    def _scale_selected(self, factor: float) -> None:
        if self._selected is None:
            return
        if getattr(self, "_selected_atype", "") in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
            return
        pn, xref = self._selected
        with self._doc_lock:
            result = self._annot.scale_annot(self.doc, pn, xref, factor)
        if result is not None:
            new_rect, new_xref = result
            if new_xref != xref:
                self._selected = (pn, new_xref)
            # scale_annot operates in PDF space; when rotated, the bbox it
            # returns is the expanded one — scale the visual rect by the
            # same factor so the overlay tracks the shape.
            if self._selected_visual_rect is not None:
                vr = self._selected_visual_rect
                cx = (vr.x0 + vr.x1) / 2
                cy = (vr.y0 + vr.y1) / 2
                hw = vr.width * factor / 2
                hh = vr.height * factor / 2
                scaled_visual = fitz.Rect(cx - hw, cy - hh, cx + hw, cy + hh)
            else:
                scaled_visual = new_rect
            self._refresh_selected_overlay(pn, annot_rect=scaled_visual)
            self._rerender_page_image(pn)
        else:
            self._show_snack("No se pudo ajustar el tamaño")

    def _scale_down_selected(self, e=None) -> None:
        self._scale_selected(0.85)

    def _scale_up_selected(self, e=None) -> None:
        self._scale_selected(1.15)

    def _change_selected_width(self, delta: float) -> None:
        if self._selected is None:
            return
        if getattr(self, "_selected_atype", "") in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
            return
        pn, xref = self._selected
        with self._doc_lock:
            new_xref = self._annot.change_annot_width(self.doc, pn, xref, delta)
        if new_xref is not None:
            if new_xref != xref:
                self._selected = (pn, new_xref)
            self._rerender_page_image(pn)
        else:
            self._show_snack("No se pudo cambiar el grosor")

    def _thin_selected(self, e=None) -> None:
        self._change_selected_width(-1.0)

    def _thicken_selected(self, e=None) -> None:
        self._change_selected_width(+1.0)

    def _recolor_selected_menu(self, e=None) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected

        dlg = ft.AlertDialog(modal=True, title=ft.Text("Cambiar color de anotación"))

        def pick(rgb: tuple[float, float, float]) -> None:
            self.page_ref.close(dlg)
            with self._doc_lock:
                ok = self._annot.change_annot_color(self.doc, pn, xref, rgb)
            if not ok:
                self._show_snack("No se pudo cambiar el color")
                return
            self._rerender_page_image(pn)
            self._refresh_selected_overlay(pn)

        def cancel(ev) -> None:
            self.page_ref.close(dlg)

        dlg.content = ft.Column(
            [
                ft.TextButton(
                    content=ft.Row(
                        [
                            ft.Container(bgcolor=_rgb_to_hex(r, g, b), width=22, height=22, border_radius=4),
                            ft.Text(name, size=14),
                        ],
                        spacing=10,
                    ),
                    on_click=lambda ev, c=rgb: pick(c),
                )
                for name, rgb in HIGHLIGHT_COLORS
                for r, g, b in [rgb]
            ],
            tight=True, spacing=2,
        )
        dlg.actions = [ft.TextButton("Cancelar", on_click=cancel)]
        self.page_ref.open(dlg)

    # ── text-selection action dialog (OCR click fallback) ─────────────────────

    def _show_text_actions(self, text: str, pn: int) -> None:
        preview = text[:100] + ("…" if len(text) > 100 else "")
        dlg = ft.AlertDialog(title=ft.Text("Texto seleccionado"))

        def close(ev=None) -> None:
            dlg.open = False
            self.page_ref.update()

        def copy_text(ev) -> None:
            close()
            self.page_ref.set_clipboard(text)
            short = text[:60] + ("…" if len(text) > 60 else "")
            self._show_snack(f'Copiado: "{short}"')

        def apply_tool(tool: Tool) -> None:
            close()
            with self._doc_lock:
                changed = self._annot.apply_text_tool(self.doc, pn, tool)
            if changed:
                self._refresh_page(pn)

        dlg.content = ft.Column([ft.Text(preview, size=13, selectable=True)], tight=True)
        dlg.actions = [
            ft.TextButton("Copiar",   icon=ft.Icons.CONTENT_COPY,         on_click=copy_text),
            ft.TextButton("Resaltar", icon=ft.Icons.HIGHLIGHT,            on_click=lambda ev: apply_tool(Tool.HIGHLIGHT)),
            ft.TextButton("Subrayar", icon=ft.Icons.FORMAT_UNDERLINE,     on_click=lambda ev: apply_tool(Tool.UNDERLINE)),
            ft.TextButton("Tachar",   icon=ft.Icons.FORMAT_STRIKETHROUGH, on_click=lambda ev: apply_tool(Tool.STRIKEOUT)),
            ft.TextButton("Cerrar", on_click=close),
        ]
        self.page_ref.dialog = dlg
        dlg.open = True
        self.page_ref.update()
