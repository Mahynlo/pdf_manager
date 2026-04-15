"""Mouse / touch gesture handlers for PDFViewerTab."""
from __future__ import annotations

import math
import time

import flet as ft
import fitz

from .annotations import Tool
from .renderer import BASE_SCALE, display_to_pdf


class _GestureMixin:
    """Pan and tap event handling — routes to annotation or text-selection logic."""

    def _on_tap_down(self, e: ft.TapEvent, pn: int) -> None:
        now  = time.time()
        dist = math.hypot(
            e.local_x - self._last_tap_pos[0],
            e.local_y - self._last_tap_pos[1],
        )
        if (pn == self._last_tap_pn
                and now - self._last_tap_time < 0.5
                and dist < 20):
            self._tap_count += 1
        else:
            self._tap_count = 1
        self._last_tap_time = now
        self._last_tap_pos  = (e.local_x, e.local_y)
        self._last_tap_pn   = pn
        self._pending_tap      = (e.local_x, e.local_y)
        self._pending_tap_page = pn

    def _on_tap(self, e, pn: int) -> None:
        # Triple-tap while SELECT tool is active → select paragraph under cursor.
        if self._annot.tool == Tool.SELECT:
            if (self._tap_count >= 3
                    and self._pending_tap is not None
                    and self._pending_tap_page == pn):
                x, y = self._pending_tap
                pdf_x, pdf_y   = display_to_pdf(x, y, self.zoom)
                self._pending_tap      = None
                self._pending_tap_page = None
                self._hide_text_sel_bar()
                self._select_paragraph_at(pn, (pdf_x, pdf_y))
                return
            # Plain tap while SELECT tool is active dismisses the selection bar.
            self._hide_text_sel_bar()
            self._pending_tap      = None
            self._pending_tap_page = None
            return
        if (
            self._annot.tool != Tool.CURSOR
            or self._pending_tap is None
            or self._pending_tap_page != pn
        ):
            self._pending_tap      = None
            self._pending_tap_page = None
            return
        x, y = self._pending_tap
        self._pending_tap      = None
        self._pending_tap_page = None
        pdf_x, pdf_y = display_to_pdf(x, y, self.zoom)
        with self._doc_lock:
            page  = self.doc[pn]
            annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
        if annot:
            self.current_page = pn
            annot_type = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
            if annot_type in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                self._show_annot_popup(pn, annot.xref, annot.rect)
            else:
                self._select_annot(pn, annot)
        else:
            self._deselect_annot()

    def _on_pan_start(self, e: ft.DragStartEvent, pn: int) -> None:
        self._pending_tap      = None
        self._pending_tap_page = None

        if self._annot.tool == Tool.CURSOR:
            if self._selected is None or self._selected[0] != pn:
                return
            pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
            annot = self._get_selected_annot()
            if annot is None:
                self._deselect_annot()
                return
            hit = fitz.Rect(annot.rect)
            hit.x0 -= 3; hit.y0 -= 3; hit.x1 += 3; hit.y1 += 3
            if hit.contains(fitz.Point(pdf_x, pdf_y)):
                self._moving_selected = True
                self._move_last_pdf   = (pdf_x, pdf_y)
            return

        self.current_page = pn
        pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
        if self._annot.tool == Tool.SELECT:
            self._text_sel_start_pdf = (pdf_x, pdf_y)
            self._text_sel_end_pdf   = (pdf_x, pdf_y)
            self._hide_text_sel_bar()
        self._annot.begin(pdf_x, pdf_y)

    def _on_pan_update(self, e: ft.DragUpdateEvent, pn: int) -> None:
        if self._annot.tool == Tool.CURSOR:
            if not self._moving_selected or self._move_last_pdf is None or self._selected is None:
                return
            if self._selected[0] != pn:
                return
            pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
            last_x, last_y = self._move_last_pdf
            dx = pdf_x - last_x
            dy = pdf_y - last_y
            if math.isclose(dx, 0.0, abs_tol=0.01) and math.isclose(dy, 0.0, abs_tol=0.01):
                return
            with self._doc_lock:
                moved = self._annot.move_annot(self.doc, pn, self._selected[1], dx, dy)
            if moved:
                self._move_last_pdf = (pdf_x, pdf_y)
                self._refresh_selected_overlay(pn)
            return

        pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
        pdf_rect = self._annot.move(pdf_x, pdf_y)
        if pdf_rect is None:
            return
        scale = self.zoom * BASE_SCALE

        if self._annot.tool == Tool.SELECT:
            self._text_sel_end_pdf = (pdf_x, pdf_y)
            self._update_text_selection(
                pn, self._text_sel_start_pdf, (pdf_x, pdf_y), update_ui=True
            )
        else:
            dov = self._drag_overlays[pn]
            dov.left    = pdf_rect.x0    * scale
            dov.top     = pdf_rect.y0    * scale
            dov.width   = pdf_rect.width  * scale
            dov.height  = pdf_rect.height * scale
            dov.bgcolor = self._annot.overlay_color
            dov.visible = True
            try:
                dov.update()
            except Exception:
                pass

    def _on_pan_end(self, e: ft.DragEndEvent, pn: int) -> None:
        if self._annot.tool == Tool.CURSOR:
            if self._moving_selected:
                self._moving_selected = False
                self._move_last_pdf   = None
                self._refresh_page(pn)
            return

        dov = self._drag_overlays[pn]
        dov.visible = False
        try:
            dov.update()
        except Exception:
            pass

        tool = self._annot.tool  # save before commit changes state
        with self._doc_lock:
            modified, text = self._annot.commit(self.doc, pn)

        # Capture new text-markup annotation info before refresh clears _selected
        new_markup: tuple[int, fitz.Rect] | None = None
        if modified and tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            if self._annot._history:
                last_pn, last_xref = self._annot._history[-1]
                if last_pn == pn:
                    with self._doc_lock:
                        for a in self.doc[pn].annots():
                            if a.xref == last_xref:
                                new_markup = (last_xref, fitz.Rect(a.rect))
                                break

        if modified:
            self._clear_text_selection()
            self._refresh_page(pn)
            if new_markup is not None:
                self._show_annot_popup(pn, new_markup[0], new_markup[1])
        elif self._annot.tool == Tool.SELECT:
            sel_text = self._update_text_selection(
                pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
            )
            if not sel_text:
                sel_text = self._ocr_text_in_rect(pn, self._annot.last_select_rect)
            if sel_text:
                if self._text_sel_sel_rect is not None:
                    self._annot.last_rect = self._text_sel_sel_rect
                self._show_text_sel_bar(sel_text)
            else:
                self._hide_text_sel_bar()
        else:
            self._clear_text_selection()
