"""Annotation selection, editing and text-action dialogs for PDFViewerTab."""
from __future__ import annotations

import math

import flet as ft
import fitz

from .annotations import HIGHLIGHT_COLORS, Tool
from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG, _rgb_to_hex

# Pixel size of each corner handle (must match _render_mixin.py constant).
_HS  = 10
_HHS = _HS / 2
_RS  = 14   # rotation handle diameter
_ROT_OFFSET = 28   # px above the bbox top edge for the rotation handle centre


class _AnnotMixin:
    """Annotation tool selection, selection overlay and edit operations."""

    # ── tool selection ────────────────────────────────────────────────────────

    def _select_tool(self, tool: Tool, cursor: ft.MouseCursor) -> None:
        if tool != Tool.SELECT:
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

    def _update_sel_handles(self, pn: int, W: float, H: float) -> None:
        """Position all handle/menu controls inside the sel_overlay Stack."""
        if pn >= len(self._sel_handles):
            return
        h = self._sel_handles[pn]

        h["border"].width  = W
        h["border"].height = H

        h["tl"].left = -_HHS;     h["tl"].top = -_HHS
        h["tr"].left = W - _HHS;  h["tr"].top = -_HHS
        h["bl"].left = -_HHS;     h["bl"].top = H - _HHS
        h["br"].left = W - _HHS;  h["br"].top = H - _HHS

        # Rotation handle: centred above the top edge.
        h["rot"].left = W / 2 - _RS / 2
        h["rot"].top  = -_ROT_OFFSET - _RS / 2

        # Thin line connecting rotation handle to top edge.
        h["rot_line"].left = W / 2 - 1
        h["rot_line"].top  = -(_ROT_OFFSET - _RS / 2)
        h["rot_line"].height = _ROT_OFFSET - _RS / 2

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
        annot_name = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else "Anotación"
        self._sel_label.value = f"{annot_name} — arrastra para mover"

        scale  = self.zoom * BASE_SCALE
        r      = annot.rect
        W      = r.width  * scale
        H      = r.height * scale

        sel_ov = self._sel_overlays[pn]
        sel_ov.left    = r.x0 * scale
        sel_ov.top     = r.y0 * scale
        sel_ov.width   = W
        sel_ov.height  = H
        sel_ov.visible = True

        # Apply stored visual rotation.
        angle_rad = math.radians(self._annot.get_rotation(annot.xref))
        sel_ov.rotate = ft.Rotate(angle=angle_rad, alignment=ft.alignment.center)

        self._update_sel_handles(pn, W, H)
        self._annot_action_bar.visible = True
        try:
            sel_ov.update()
            self._annot_action_bar.update()
        except Exception:
            pass

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

    def _refresh_selected_overlay(self, pn: int) -> None:
        annot = self._get_selected_annot()
        if annot is None:
            self._deselect_annot()
            return
        scale  = self.zoom * BASE_SCALE
        r      = annot.rect
        W      = max(2.0, r.width  * scale)
        H      = max(2.0, r.height * scale)

        sel_ov = self._sel_overlays[pn]
        sel_ov.left    = r.x0 * scale
        sel_ov.top     = r.y0 * scale
        sel_ov.width   = W
        sel_ov.height  = H
        sel_ov.visible = True

        angle_rad = math.radians(self._annot.get_rotation(annot.xref))
        sel_ov.rotate = ft.Rotate(angle=angle_rad, alignment=ft.alignment.center)

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
        self._selected = None
        self._drag_mode = None
        if pn < len(self._sel_overlays):
            self._sel_overlays[pn].visible = False
            if pn < len(self._sel_handles):
                self._sel_handles[pn]["menu"].visible = False
            try:
                self._sel_overlays[pn].update()
            except Exception:
                pass
        self._annot_action_bar.visible = False
        try:
            self._annot_action_bar.update()
        except Exception:
            pass
        self._sel_label.value = "Anotación seleccionada"

    # ── edit operations ───────────────────────────────────────────────────────

    def _delete_selected(self, e=None) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected
        self._annot.clear_rotation(xref)
        with self._doc_lock:
            deleted = self._annot.delete_annot(self.doc, pn, xref)
        self._selected = None
        if deleted:
            self._refresh_page(pn)
        else:
            self._show_snack("No se pudo eliminar la anotación")

    def _scale_selected(self, factor: float) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected
        with self._doc_lock:
            result = self._annot.scale_annot(self.doc, pn, xref, factor)
        if result:
            self._refresh_page(pn)
        else:
            self._show_snack("No se pudo ajustar el tamaño")

    def _scale_down_selected(self, e=None) -> None:
        self._scale_selected(0.85)

    def _scale_up_selected(self, e=None) -> None:
        self._scale_selected(1.15)

    def _rotate_selected(self, delta_deg: float) -> None:
        """Rotate the selected annotation visually by delta_deg degrees."""
        if self._selected is None:
            return
        pn, xref = self._selected
        self._annot.add_rotation(xref, delta_deg)
        self._refresh_selected_overlay(pn)

    def _recolor_selected_menu(self, e=None) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected

        dlg = ft.AlertDialog(title=ft.Text("Cambiar color de anotación"))

        def pick(rgb: tuple[float, float, float]) -> None:
            dlg.open = False
            self.page_ref.update()
            with self._doc_lock:
                self._annot.change_annot_color(self.doc, pn, xref, rgb)
            self._selected = None
            self._refresh_page(pn)

        def cancel(ev) -> None:
            dlg.open = False
            self.page_ref.update()

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
        self.page_ref.dialog = dlg
        dlg.open = True
        self.page_ref.update()

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
