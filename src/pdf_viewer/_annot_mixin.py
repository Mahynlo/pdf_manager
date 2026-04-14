"""Annotation selection, editing and text-action dialogs for PDFViewerTab."""
from __future__ import annotations

import flet as ft
import fitz

from .annotations import HIGHLIGHT_COLORS, Tool
from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG, _rgb_to_hex


class _AnnotMixin:
    """Annotation tool selection, selection overlay and edit operations."""

    # ── tool selection ────────────────────────────────────────────────────────

    # ── annotation floating popup ─────────────────────────────────────────────

    def _show_annot_popup(self, pn: int, xref: int, pdf_rect: fitz.Rect) -> None:
        """Show the floating annotation action popup below pdf_rect."""
        self._hide_annot_popup()
        self._selected = (pn, xref)
        if pn >= len(self._annot_popups):
            return
        scale  = self.zoom * BASE_SCALE
        popup  = self._annot_popups[pn]
        popup.left    = max(0.0, pdf_rect.x0 * scale)
        popup.top     = pdf_rect.y1 * scale + 8
        popup.visible = True
        self._annot_popup_pn = pn
        try:
            popup.update()
        except Exception:
            pass

    def _hide_annot_popup(self, e=None) -> None:
        """Hide the annotation popup (does not clear self._selected)."""
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

    # ── annotation selection overlay ──────────────────────────────────────────

    def _select_annot(self, pn: int, annot: fitz.Annot) -> None:
        if self._selected is not None and self._selected[0] != pn:
            old_pn = self._selected[0]
            if old_pn < len(self._sel_overlays):
                self._sel_overlays[old_pn].visible = False
                try:
                    self._sel_overlays[old_pn].update()
                except Exception:
                    pass

        self._selected = (pn, annot.xref)
        annot_name = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else "Anotación"
        self._sel_label.value = f"{annot_name} seleccionada — arrastra para mover"

        scale  = self.zoom * BASE_SCALE
        r      = annot.rect
        sel_ov = self._sel_overlays[pn]
        sel_ov.left    = r.x0     * scale
        sel_ov.top     = r.y0     * scale
        sel_ov.width   = r.width  * scale
        sel_ov.height  = r.height * scale
        sel_ov.visible = True
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
        sel_ov = self._sel_overlays[pn]
        sel_ov.left    = r.x0    * scale
        sel_ov.top     = r.y0    * scale
        sel_ov.width   = max(2, r.width  * scale)
        sel_ov.height  = max(2, r.height * scale)
        sel_ov.visible = True
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
        if pn < len(self._sel_overlays):
            self._sel_overlays[pn].visible = False
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
