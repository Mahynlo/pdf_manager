"""Annotation selection, editing and text-action dialogs for PDFViewerTab."""
from __future__ import annotations

import flet as ft
import flet.canvas as cv
import fitz

from .annotations import (
    HIGHLIGHT_COLORS, Tool, _atype,
    FREETEXT_FONTS, FREETEXT_ALIGN, FREETEXT_SIZES,
    DEFAULT_TEXT_FONT, DEFAULT_TEXT_SIZE, DEFAULT_TEXT_COLOR, DEFAULT_TEXT_ALIGN,
)
from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG, _rgb_to_hex

# Tipos de anotación de forma cerrada cuyo contorno se puede dibujar exactamente
# desde su caja (sin conocer vértices): cuadrado → rectángulo, círculo → elipse.
_GHOST_KIND = {"Square": "rect", "Circle": "oval"}

# Pixel size of each corner handle (must match _render_mixin.py constant).
_HS  = 10
_HHS = _HS / 2


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
            if gd is None:  # slot no construido (placeholder)
                continue
            gd.mouse_cursor = cursor
            gd.update()
        for t, btn in self._tool_btns.items():
            btn.bgcolor = _SELECTED_BG if t == tool else None
            btn.update()

    def _set_highlight_color(self, rgb: tuple[float, float, float]) -> None:
        self._annot.highlight_color = rgb
        self._select_tool(Tool.HIGHLIGHT, ft.MouseCursor.TEXT)
        self._show_snack("Color de resaltado actualizado")

    # ── annotation floating popup (for text-markup annotations) ───────────────

    def _show_annot_popup(self, pn: int, xref: int, pdf_rect: fitz.Rect) -> None:
        self._hide_annot_popup()
        self._selected = (pn, xref)
        if pn >= len(self._annot_popups) or self._annot_popups[pn] is None:
            return
        scale  = self.zoom * BASE_SCALE
        popup  = self._annot_popups[pn]

        _POPUP_H = 44 # E el espacio vertical que ocupa el popup; usado para posicionar el popup dentro de la página.
        _POPUP_W = 200 # El ancho del popup; usado para posicionar el popup dentro de la página.
        _MARGIN  = 8 # Margen mínimo entre el popup y los bordes de la página.

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
        if pn is not None and pn < len(self._annot_popups) and self._annot_popups[pn] is not None:
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
        if pn >= len(self._sel_handles) or self._sel_handles[pn] is None:
            return
        atype = _atype(annot)
        self._selected_atype = atype

        h = self._sel_handles[pn]

        # ── ghost de la forma (elipse/rectángulo) ─────────────────────────────
        # Se cachea el tipo y el color de trazo real para redibujar el contorno
        # mientras se mueve/redimensiona (cuando la anotación real está oculta).
        ghost_kind = _GHOST_KIND.get(atype)
        self._sel_ghost_kind = ghost_kind
        ghost_hex = "#0055FF"
        try:
            stroke = (annot.colors or {}).get("stroke")
            if stroke and len(stroke) >= 3:
                ghost_hex = _rgb_to_hex(stroke[0], stroke[1], stroke[2])
        except Exception:
            pass
        self._sel_ghost_color = ghost_hex

        # Cuando hay ghost, el marco rectangular se atenúa (1 px claro) para que
        # la figura sea el elemento dominante y la caja no "gane" a un círculo.
        h["border"].border_radius = 2
        h["border"].bgcolor = None
        h["border"].border  = (
            ft.border.all(1, "#7FA8D9") if ghost_kind
            else ft.border.all(2, "#555555")
        )

        # Markup annotations (highlight/underline/strikeout) cannot be
        # moved or resized — hide corner handles and size/thickness buttons.
        is_markup  = atype in ("Highlight", "Underline", "StrikeOut", "Squiggly")
        is_text    = atype == "FreeText"
        no_recolor = atype in ("Squiggly",)
        for name in ("tl", "tr", "bl", "br", "tm", "bm", "lm", "rm"):
            h[name].visible = not is_markup
        for name in ("scale_sep", "scale_down", "scale_up", "width_sep", "width_down", "width_up"):
            h[name].visible = not is_markup
        for name in ("color_sep", "color_btn"):
            h[name].visible = not no_recolor
        # Botón "editar texto": sólo para anotaciones de texto (FreeText).
        for name in ("edit_sep", "edit_btn"):
            h[name].visible = is_text

    def _update_sel_handles(
        self, pn: int, W: float, H: float,
        rg_left: float = 0.0, rg_top: float = 0.0,
        menu_left: float = 0.0, menu_top: float = 0.0,
    ) -> None:
        """Position all handle/menu controls inside the sel_overlay Stack.

        Todas las coordenadas son relativas al origen de ``sel_ov`` (que puede
        extenderse más allá de la anotación para contener el menú). Los handles
        de esquina son sólo visuales — los clics de redimensión se enrutan por
        el GestureDetector de la página, no por estos contenedores — así que su
        posición no necesita quedar dentro de los límites de ``sel_ov``; sólo el
        menú (botones reales) debe quedar dentro para recibir clics.
        """
        if pn >= len(self._sel_handles) or self._sel_handles[pn] is None:
            return
        h = self._sel_handles[pn]

        # The rotatable group (border + handles) occupies the bbox rect,
        # offset within sel_ov. The context menu sits outside this group.
        if "rot_group" in h:
            h["rot_group"].left   = rg_left
            h["rot_group"].top    = rg_top
            h["rot_group"].width  = W
            h["rot_group"].height = H

        h["border"].width  = W
        h["border"].height = H
        h["border"].border_radius = 2

        # Redibuja el ghost de la forma al tamaño actual de la caja, de modo que
        # siga a la figura al mover/redimensionar (la anotación real está oculta
        # durante el arrastre). El borde se enmarca 1 px adentro para no solaparse.
        ghost = h.get("ghost")
        if ghost is not None:
            kind = getattr(self, "_sel_ghost_kind", None)
            if kind:
                paint = ft.Paint(
                    stroke_width=2,
                    color=getattr(self, "_sel_ghost_color", "#0055FF"),
                    style=ft.PaintingStyle.STROKE,
                )
                gw = max(1.0, W - 2.0)
                gh = max(1.0, H - 2.0)
                ghost.shapes = [
                    cv.Oval(1.0, 1.0, gw, gh, paint=paint) if kind == "oval"
                    else cv.Rect(1.0, 1.0, gw, gh, paint=paint)
                ]
                ghost.left = 0; ghost.top = 0
                ghost.width = W; ghost.height = H
                ghost.visible = True
            elif ghost.shapes:
                ghost.shapes = []
                ghost.visible = False

        h["tl"].left = -_HHS;     h["tl"].top = -_HHS
        h["tr"].left = W - _HHS;  h["tr"].top = -_HHS
        h["bl"].left = -_HHS;     h["bl"].top = H - _HHS
        h["br"].left = W - _HHS;  h["br"].top = H - _HHS

        # Puntos medios de cada lado (redimensión de un solo eje).
        cx = W / 2 - _HHS
        cy = H / 2 - _HHS
        h["tm"].left = cx;        h["tm"].top = -_HHS
        h["bm"].left = cx;        h["bm"].top = H - _HHS
        h["lm"].left = -_HHS;     h["lm"].top = cy
        h["rm"].left = W - _HHS;  h["rm"].top = cy

        # Context menu: posición ya acotada a la página por el llamador.
        h["menu"].left = menu_left
        h["menu"].top  = menu_top
        h["menu"].visible = True

    # ── annotation selection overlay ──────────────────────────────────────────

    def _select_annot(self, pn: int, annot: fitz.Annot) -> None:
        if self._selected is not None and self._selected[0] != pn:
            old_pn = self._selected[0]
            if old_pn < len(self._sel_overlays) and self._sel_overlays[old_pn] is not None:
                self._sel_overlays[old_pn].visible = False
                if old_pn < len(self._sel_handles) and self._sel_handles[old_pn] is not None:
                    self._sel_handles[old_pn]["menu"].visible = False
                try:
                    self._sel_overlays[old_pn].update()
                except Exception:
                    pass

        self._selected = (pn, annot.xref)

        # annot.rect está SIN rotar; el overlay se dibuja en pantalla (× scale).
        # Convertir a pantalla para que coincida en páginas rotadas (identidad si
        # rotation == 0).
        pdf_rect = fitz.Rect(annot.rect) * self.doc[pn].rotation_matrix
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
        # La página puede no estar construida (placeholder) si el usuario hizo
        # scroll lejos de la selección: no hay overlay donde dibujar. Se redibuja
        # al materializar el slot (_build_page_slot llama aquí).
        if not self._is_built(pn):
            return
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
                        (fitz.Rect(a.rect) * page.rotation_matrix
                         for a in page.annots() if a.xref == xref),
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
        ox    = r.x0 * scale
        oy    = r.y0 * scale

        page_h = float(self._page_heights[pn]) if pn < len(self._page_heights) else 9999.0
        page_w = float(self._page_slots[pn].width or 9999) if pn < len(self._page_slots) else 9999.0

        # ── colocar el menú contextual dentro de la página ────────────────────
        # El menú (botones reales) debe quedar dentro de los límites de sel_ov y,
        # a su vez, dentro de la página, o Flutter no le entrega los clics.
        _MENU_W = 300.0   # ancho estimado del menú de iconos
        _MENU_H = 44.0
        _MARGIN = 6.0
        _GAP    = 6.0

        menu_abs_left = max(_MARGIN, min(ox, page_w - _MENU_W - _MARGIN))
        below_top = oy + H + _GAP
        above_top = oy - _MENU_H - _GAP
        if below_top + _MENU_H <= page_h - _MARGIN:
            menu_abs_top = below_top
        else:
            menu_abs_top = max(_MARGIN, above_top)

        # sel_ov abarca la unión del recuadro de la anotación y el menú, de modo
        # que el menú quede SIEMPRE dentro del contenedor (clickeable).
        region_left   = min(ox, menu_abs_left)
        region_top    = min(oy, menu_abs_top)
        region_right  = max(ox + W, menu_abs_left + _MENU_W)
        region_bottom = max(oy + H, menu_abs_top + _MENU_H)

        sel_ov = self._sel_overlays[pn]
        sel_ov.left    = region_left
        sel_ov.top     = region_top
        sel_ov.width   = region_right - region_left
        sel_ov.height  = region_bottom - region_top
        sel_ov.visible = True

        self._update_sel_handles(
            pn, W, H,
            rg_left=ox - region_left, rg_top=oy - region_top,
            menu_left=menu_abs_left - region_left, menu_top=menu_abs_top - region_top,
        )

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
        if pn < len(self._sel_overlays) and self._sel_overlays[pn] is not None:
            self._sel_overlays[pn].visible = False
            if pn < len(self._sel_handles) and self._sel_handles[pn] is not None:
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

    # ── text (FreeText) annotation editor ─────────────────────────────────────

    def _open_text_editor(self, pn: int, rect: fitz.Rect | None, xref: int | None = None) -> None:
        """Abre el diálogo para insertar (``xref`` None) o editar un texto.

        ``rect`` es la caja en espacio de PANTALLA donde crear el texto (se
        ignora al editar, que conserva la caja de la anotación).
        """
        is_edit = xref is not None
        props   = (self._annot.get_text_props(xref) or {}) if is_edit else {}
        cur_text  = props.get("text", "")
        cur_font  = props.get("fontname", DEFAULT_TEXT_FONT)
        cur_size  = int(props.get("fontsize", DEFAULT_TEXT_SIZE))
        cur_align = int(props.get("align", DEFAULT_TEXT_ALIGN))
        state = {"color": tuple(props.get("color", DEFAULT_TEXT_COLOR))}

        txt = ft.TextField(
            value=cur_text, multiline=True, min_lines=3, max_lines=10,
            label="Texto", autofocus=True, text_size=14,
        )
        font_dd = ft.Dropdown(
            label="Fuente", value=cur_font, width=210,
            options=[ft.dropdown.Option(key=fn, text=lbl) for lbl, fn in FREETEXT_FONTS],
        )
        size_val = str(cur_size if cur_size in FREETEXT_SIZES else DEFAULT_TEXT_SIZE)
        size_dd = ft.Dropdown(
            label="Tamaño", value=size_val, width=110,
            options=[ft.dropdown.Option(key=str(s), text=f"{s} pt") for s in FREETEXT_SIZES],
        )
        align_dd = ft.Dropdown(
            label="Alineación", value=str(cur_align), width=150,
            options=[ft.dropdown.Option(key=str(v), text=lbl) for lbl, v in FREETEXT_ALIGN],
        )
        swatch = ft.Container(
            width=24, height=24, border_radius=4,
            bgcolor=_rgb_to_hex(*state["color"]),
            border=ft.border.all(1, "outlineVariant"),
        )

        def set_color(rgb: tuple[float, float, float]) -> None:
            state["color"] = tuple(rgb)
            swatch.bgcolor = _rgb_to_hex(*rgb)
            try:
                swatch.update()
            except Exception:
                pass

        color_menu = ft.PopupMenuButton(
            content=ft.Row(
                [swatch, ft.Text("Color", size=13), ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18)],
                spacing=6, tight=True,
            ),
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Container(bgcolor=_rgb_to_hex(r, g, b), width=20, height=20, border_radius=4),
                            ft.Text(name, size=13),
                        ],
                        spacing=10,
                    ),
                    on_click=lambda e, c=rgb: set_color(c),
                )
                for name, rgb in HIGHLIGHT_COLORS
                for r, g, b in [rgb]
            ],
        )

        def save(ev=None) -> None:
            text = (txt.value or "").strip()
            if not text:
                self._show_snack("Escribe algún texto")
                return
            fn = font_dd.value or DEFAULT_TEXT_FONT
            sz = int(size_dd.value or DEFAULT_TEXT_SIZE)
            al = int(align_dd.value or DEFAULT_TEXT_ALIGN)
            col = state["color"]
            self.page_ref.close(dlg)
            with self._doc_lock:
                if is_edit:
                    new_xref = self._annot.edit_text(
                        self.doc, pn, xref, text,
                        fontname=fn, fontsize=sz, color=col, align=al,
                    )
                else:
                    new_xref = self._annot.commit_text(
                        self.doc, pn, rect, text,
                        fontname=fn, fontsize=sz, color=col, align=al,
                    )
            if not new_xref:
                self._show_snack("No se pudo guardar el texto")
                return
            # Volver al cursor y seleccionar la anotación para editar/mover al instante.
            self._select_tool(Tool.CURSOR, ft.MouseCursor.BASIC)
            self._refresh_page(pn)
            with self._doc_lock:
                for a in self.doc[pn].annots():
                    if a.xref == new_xref:
                        self.current_page = pn
                        self._select_annot(pn, a)
                        break

        def cancel(ev=None) -> None:
            self.page_ref.close(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar texto" if is_edit else "Insertar texto"),
            content=ft.Container(
                width=440,
                content=ft.Column(
                    [
                        txt,
                        ft.Row([font_dd, size_dd], spacing=10),
                        ft.Row([align_dd, color_menu], spacing=16,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ],
                    tight=True, spacing=14,
                ),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cancel),
                ft.FilledButton("Guardar" if is_edit else "Insertar", on_click=save),
            ],
        )
        self.page_ref.open(dlg)

    def _edit_selected_text(self, e=None) -> None:
        """Abre el editor para la anotación de texto seleccionada."""
        if self._selected is None:
            return
        pn, xref = self._selected
        if getattr(self, "_selected_atype", "") != "FreeText":
            return
        self._hide_annot_popup()
        rect = self._selected_visual_rect or self._selected_rect
        self._open_text_editor(pn, rect, xref=xref)

    # ── text-selection action dialog (OCR click fallback) ─────────────────────

    def _show_text_actions(self, text: str, pn: int) -> None:
        preview = text[:100] + ("…" if len(text) > 100 else "")
        dlg = ft.AlertDialog(title=ft.Text("Texto seleccionado"))

        def close(ev=None) -> None:
            self.page_ref.close(dlg)

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
            ft.TextButton("Cerrar",   on_click=close),
        ]
        self.page_ref.open(dlg)
