"""Mouse / touch gesture handlers for PDFViewerTab."""
from __future__ import annotations

import math
import time

import flet as ft
import fitz

from .annotations import Tool
from .renderer import BASE_SCALE, display_to_pdf

# Pixel hit radius for corner handles and rotation handle.
_HANDLE_HIT_R = 14
# Rotation handle offset above bbox top edge (must match _annot_mixin.py).
_ROT_OFFSET = 28


class _GestureMixin:
    """Pan and tap event handling — routes to annotation or text-selection logic."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _sel_handle_positions(self, pn: int):
        """Return dict of display-space handle centres accounting for rotation.

        Returns None if there is no active selection on *pn*.
        Rotation is applied around the bbox centre.
        """
        if self._selected is None or self._selected[0] != pn:
            return None
        annot = self._get_selected_annot()
        if annot is None:
            return None

        scale = self.zoom * BASE_SCALE
        r     = annot.rect
        xref  = self._selected[1]
        angle_rad = math.radians(self._annot.get_rotation(xref))

        cx = (r.x0 + r.x1) / 2 * scale
        cy = (r.y0 + r.y1) / 2 * scale
        W  = r.width  * scale
        H  = r.height * scale

        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        def rot(dx: float, dy: float):
            return (cx + dx * cos_a - dy * sin_a,
                    cy + dx * sin_a + dy * cos_a)

        return {
            "tl":  rot(-W / 2, -H / 2),
            "tr":  rot( W / 2, -H / 2),
            "bl":  rot(-W / 2,  H / 2),
            "br":  rot( W / 2,  H / 2),
            "rot": rot(0, -H / 2 - _ROT_OFFSET),
            "cx":  cx,
            "cy":  cy,
        }

    def _detect_drag_mode(self, pn: int, dx: float, dy: float) -> str:
        """Return the drag mode string for a click at display position (dx, dy)."""
        positions = self._sel_handle_positions(pn)
        if positions is None:
            return "none"

        # Check rotation handle first (it floats above the bbox).
        rx, ry = positions["rot"]
        if math.hypot(dx - rx, dy - ry) <= _HANDLE_HIT_R:
            return "rotate"

        # Check corner handles.
        for name in ("tl", "tr", "bl", "br"):
            hx, hy = positions[name]
            if math.hypot(dx - hx, dy - hy) <= _HANDLE_HIT_R:
                return f"resize_{name}"

        # Check inside the (rotated) bounding box for move.
        annot = self._get_selected_annot()
        if annot is None:
            return "none"
        scale = self.zoom * BASE_SCALE
        r     = annot.rect
        cx, cy = positions["cx"], positions["cy"]
        angle_rad = math.radians(self._annot.get_rotation(self._selected[1]))

        # Rotate the click point back into un-rotated bbox space.
        local_x = (dx - cx) * math.cos(-angle_rad) - (dy - cy) * math.sin(-angle_rad)
        local_y = (dx - cx) * math.sin(-angle_rad) + (dy - cy) * math.cos(-angle_rad)
        half_w  = r.width  * scale / 2 + 4
        half_h  = r.height * scale / 2 + 4
        if abs(local_x) <= half_w and abs(local_y) <= half_h:
            return "move"

        return "none"

    # ── tap events ────────────────────────────────────────────────────────────

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

    # ── pan events ────────────────────────────────────────────────────────────

    def _on_pan_start(self, e: ft.DragStartEvent, pn: int) -> None:
        self._pending_tap      = None
        self._pending_tap_page = None

        if self._annot.tool == Tool.CURSOR:
            if self._selected is None or self._selected[0] != pn:
                return

            mode = self._detect_drag_mode(pn, e.local_x, e.local_y)
            if mode == "none":
                # Click outside bbox/handles deselects.
                self._deselect_annot()
                return

            self._drag_mode    = mode
            pdf_x, pdf_y       = display_to_pdf(e.local_x, e.local_y, self.zoom)
            self._move_last_pdf = (pdf_x, pdf_y)

            if mode == "rotate":
                pos = self._sel_handle_positions(pn)
                if pos:
                    self._rotate_center_disp = (pos["cx"], pos["cy"])
                    self._rotate_start_angle = math.degrees(math.atan2(
                        e.local_y - pos["cy"],
                        e.local_x - pos["cx"],
                    ))
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
            if self._drag_mode is None or self._selected is None:
                return
            if self._selected[0] != pn:
                return

            pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
            last_x, last_y = self._move_last_pdf
            dx = pdf_x - last_x
            dy = pdf_y - last_y

            if self._drag_mode == "move":
                if not (math.isclose(dx, 0.0, abs_tol=0.01)
                        and math.isclose(dy, 0.0, abs_tol=0.01)):
                    with self._doc_lock:
                        moved = self._annot.move_annot(
                            self.doc, pn, self._selected[1], dx, dy
                        )
                    if moved:
                        self._move_last_pdf = (pdf_x, pdf_y)
                        self._refresh_selected_overlay(pn)

            elif self._drag_mode.startswith("resize_"):
                handle = self._drag_mode[len("resize_"):]   # "tl" | "tr" | "bl" | "br"
                if not (math.isclose(dx, 0.0, abs_tol=0.01)
                        and math.isclose(dy, 0.0, abs_tol=0.01)):
                    with self._doc_lock:
                        annot = self._get_selected_annot_nolock(pn)
                        if annot is not None:
                            new_rect = self._compute_resize_rect(annot.rect, handle, dx, dy)
                            ok = self._annot.resize_annot(
                                self.doc, pn, self._selected[1], new_rect
                            )
                    if ok:
                        self._move_last_pdf = (pdf_x, pdf_y)
                        self._refresh_selected_overlay(pn)

            elif self._drag_mode == "rotate":
                if self._rotate_center_disp is not None:
                    cx, cy = self._rotate_center_disp
                    current_angle = math.degrees(math.atan2(
                        e.local_y - cy, e.local_x - cx
                    ))
                    delta = current_angle - self._rotate_start_angle
                    self._rotate_start_angle = current_angle
                    self._annot.add_rotation(self._selected[1], delta)
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
            if self._drag_mode is not None:
                prev_mode      = self._drag_mode
                self._drag_mode         = None
                self._move_last_pdf     = None
                self._rotate_center_disp = None
                if prev_mode in ("move",) or prev_mode.startswith("resize_"):
                    self._refresh_page(pn)
                # For rotate we only updated the overlay; no PDF re-render needed.
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

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get_selected_annot_nolock(self, pn: int) -> fitz.Annot | None:
        """Return selected annot WITHOUT acquiring the doc lock (caller holds it)."""
        if self._selected is None or self._selected[0] != pn:
            return None
        xref = self._selected[1]
        for annot in self.doc[pn].annots():
            if annot.xref == xref:
                return annot
        return None

    @staticmethod
    def _compute_resize_rect(r: fitz.Rect, handle: str, dx: float, dy: float) -> fitz.Rect:
        """Apply PDF-space delta to the named corner handle of *r*."""
        _MIN = 5.0
        x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        if handle == "tl":
            x0 = min(x0 + dx, x1 - _MIN)
            y0 = min(y0 + dy, y1 - _MIN)
        elif handle == "tr":
            x1 = max(x1 + dx, x0 + _MIN)
            y0 = min(y0 + dy, y1 - _MIN)
        elif handle == "bl":
            x0 = min(x0 + dx, x1 - _MIN)
            y1 = max(y1 + dy, y0 + _MIN)
        elif handle == "br":
            x1 = max(x1 + dx, x0 + _MIN)
            y1 = max(y1 + dy, y0 + _MIN)
        return fitz.Rect(x0, y0, x1, y1)
