"""Mouse / touch gesture handlers for PDFViewerTab."""
from __future__ import annotations

import math
import time

import flet as ft
import fitz

from .annotations import Tool
from .renderer import BASE_SCALE, display_to_pdf

# Pixel hit radius for corner handles.
_HANDLE_HIT_R = 20


class _GestureMixin:
    """Pan and tap event handling — routes to annotation or text-selection logic."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _sel_handle_positions(self, pn: int):
        """Return dict of display-space handle centres.

        Returns None if there is no active selection on *pn*.  Reads from the
        cached ``_selected_rect`` to stay lock-free (the doc lock is often
        held by a background page render and blocking here stalls pan_start).
        """
        if self._selected is None or self._selected[0] != pn:
            return None

        if self._selected_rect is not None:
            r = fitz.Rect(self._selected_rect)
        else:
            xref = self._selected[1]
            with self._doc_lock:
                page = self.doc[pn]
                r = next((fitz.Rect(a.rect) for a in page.annots() if a.xref == xref), None)
            if r is None:
                return None

        scale = self.zoom * BASE_SCALE
        cx = (r.x0 + r.x1) / 2 * scale
        cy = (r.y0 + r.y1) / 2 * scale
        W  = r.width  * scale
        H  = r.height * scale

        return {
            "tl":  (cx - W / 2, cy - H / 2),
            "tr":  (cx + W / 2, cy - H / 2),
            "bl":  (cx - W / 2, cy + H / 2),
            "br":  (cx + W / 2, cy + H / 2),
            "rot": (cx,           cy - H / 2 - 30),
            "cx":  cx,
            "cy":  cy,
            "r":   r,
        }

    def _detect_drag_mode(self, pn: int, dx: float, dy: float) -> str:
        """Return the drag mode string for a click at display position (dx, dy)."""
        positions = self._sel_handle_positions(pn)
        if positions is None:
            return "none"

        # Rotation handle takes priority — it sits above the box outside the bbox.
        rx, ry = positions["rot"]
        if math.hypot(dx - rx, dy - ry) <= _HANDLE_HIT_R:
            return "rotate"

        # Check corner handles.
        for name in ("tl", "tr", "bl", "br"):
            hx, hy = positions[name]
            if math.hypot(dx - hx, dy - hy) <= _HANDLE_HIT_R:
                return f"resize_{name}"

        # Check inside the bounding box for move.
        scale  = self.zoom * BASE_SCALE
        r      = positions["r"]
        cx, cy = positions["cx"], positions["cy"]
        half_w = r.width  * scale / 2 + 12
        half_h = r.height * scale / 2 + 12
        if abs(dx - cx) <= half_w and abs(dy - cy) <= half_h:
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
            try:
                pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)

                # If there is already a selection on this page, try handles first.
                # Lock-free path: use the cached rect so we don't block waiting
                # for the background render worker to release the doc lock.
                if (self._selected is not None
                        and self._selected[0] == pn
                        and self._selected_rect is not None):
                    mode = self._detect_drag_mode(pn, e.local_x, e.local_y)
                    if mode == "rotate":
                        positions = self._sel_handle_positions(pn)
                        if positions is None:
                            return
                        cx, cy = positions["cx"], positions["cy"]
                        self._drag_mode = "rotate"
                        self._drag_start_rect   = fitz.Rect(self._selected_rect)
                        self._drag_current_rect = fitz.Rect(self._selected_rect)
                        self._drag_rotate_start_angle = math.atan2(
                            e.local_y - cy, e.local_x - cx,
                        )
                        self._drag_rotate_delta = 0.0
                        # Hide the context menu — it would look odd rotating.
                        if pn < len(self._sel_handles):
                            self._sel_handles[pn]["menu"].visible = False
                            try:
                                self._sel_handles[pn]["menu"].update()
                            except Exception:
                                pass
                        return
                    if mode != "none":
                        self._drag_start_rect   = fitz.Rect(self._selected_rect)
                        self._drag_current_rect = fitz.Rect(self._selected_rect)
                        self._drag_mode     = mode
                        self._move_last_pdf = (pdf_x, pdf_y)
                        return
                    # Drag started outside annotation — keep selection, do nothing.
                    return

                # No selection: try to auto-select any shape annotation under cursor
                # so the user can drag it directly without tapping first.
                cached_rect: fitz.Rect | None = None
                found_annot = None
                with self._doc_lock:
                    page  = self.doc[pn]
                    annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
                    if annot is not None:
                        atype = (annot.type[1]
                                 if isinstance(annot.type, (tuple, list)) and len(annot.type) > 1
                                 else "")
                        # Shape annotations only: text markup uses popup instead.
                        if atype not in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                            cached_rect = fitz.Rect(annot.rect)
                            found_annot = annot

                if found_annot is not None and cached_rect is not None:
                    self._select_annot(pn, found_annot)
                    self._drag_mode         = "move"
                    self._move_last_pdf     = (pdf_x, pdf_y)
                    self._drag_start_rect   = cached_rect
                    self._drag_current_rect = fitz.Rect(cached_rect)
            except Exception:
                pass
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
            # Lock-free drag: compute new rect from cached rect + delta, update only
            # the selection overlay.  The PDF document is written once at pan_end.
            if (self._drag_mode is None
                    or self._selected is None
                    or self._drag_current_rect is None):
                return
            if self._selected[0] != pn:
                return

            # Rotation branch: no pdf-coord deltas needed, just angle from centre.
            if self._drag_mode == "rotate":
                if self._drag_rotate_start_angle is None:
                    return
                positions = self._sel_handle_positions(pn)
                if positions is None:
                    return
                cx, cy = positions["cx"], positions["cy"]
                angle_now = math.atan2(e.local_y - cy, e.local_x - cx)
                self._drag_rotate_delta = angle_now - self._drag_rotate_start_angle
                self._ensure_drag_ghost_active(pn)
                self._apply_rotation_preview(pn, self._drag_rotate_delta)
                return

            if self._move_last_pdf is None:
                return

            try:
                pdf_x, pdf_y   = display_to_pdf(e.local_x, e.local_y, self.zoom)
                last_x, last_y = self._move_last_pdf
                dx = pdf_x - last_x
                dy = pdf_y - last_y

                if math.isclose(dx, 0.0, abs_tol=0.01) and math.isclose(dy, 0.0, abs_tol=0.01):
                    return

                if self._drag_mode == "move":
                    r = self._drag_current_rect
                    new_rect = fitz.Rect(
                        r.x0 + dx, r.y0 + dy,
                        r.x1 + dx, r.y1 + dy,
                    )
                    self._drag_current_rect = new_rect
                    self._move_last_pdf     = (pdf_x, pdf_y)
                    self._ensure_drag_ghost_active(pn)
                    self._refresh_selected_overlay(pn, annot_rect=new_rect)

                elif self._drag_mode.startswith("resize_"):
                    handle   = self._drag_mode[len("resize_"):]   # "tl" | "tr" | "bl" | "br"
                    new_rect = self._compute_resize_rect(
                        self._drag_current_rect, handle, dx, dy,
                    )
                    self._drag_current_rect = new_rect
                    self._move_last_pdf     = (pdf_x, pdf_y)
                    self._ensure_drag_ghost_active(pn)
                    self._refresh_selected_overlay(pn, annot_rect=new_rect)
            except Exception:
                pass
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
                prev_mode       = self._drag_mode
                self._drag_mode = None
                self._move_last_pdf = None
                was_hidden = self._drag_annot_hidden

                # Rotation branch: commit the accumulated angle to the PDF, clear
                # the visual preview transform.
                if prev_mode == "rotate":
                    angle_rad = self._drag_rotate_delta
                    self._drag_rotate_start_angle = None
                    self._drag_rotate_delta       = 0.0
                    # Clear the preview rotation on the overlay regardless of outcome.
                    self._clear_rotation_preview(pn)
                    try:
                        if self._selected is not None and abs(angle_rad) > 0.001:
                            xref = self._selected[1]
                            angle_deg = math.degrees(angle_rad)
                            with self._doc_lock:
                                result = self._annot.rotate_annot(
                                    self.doc, pn, xref, angle_deg,
                                )
                                if was_hidden:
                                    # Unhide using the (possibly new) xref so the
                                    # annotation is visible again after rerender.
                                    target_xref = result[1] if result else xref
                                    self._annot.set_annot_hidden(
                                        self.doc, pn, target_xref, False,
                                    )
                            self._drag_annot_hidden = False
                            if result is not None:
                                new_rect, new_xref = result
                                self._selected = (pn, new_xref)
                                self._refresh_selected_overlay(pn, annot_rect=new_rect)
                            self._rerender_page_image(pn)
                        else:
                            # Tiny rotation — just unhide and refresh overlay.
                            if was_hidden and self._selected is not None:
                                with self._doc_lock:
                                    self._annot.set_annot_hidden(
                                        self.doc, pn, self._selected[1], False,
                                    )
                                self._drag_annot_hidden = False
                                self._rerender_page_image(pn)
                    except Exception:
                        if self._drag_annot_hidden and self._selected is not None:
                            try:
                                with self._doc_lock:
                                    self._annot.set_annot_hidden(
                                        self.doc, pn, self._selected[1], False,
                                    )
                            except Exception:
                                pass
                            self._drag_annot_hidden = False
                            self._rerender_page_image(pn)
                    finally:
                        self._drag_start_rect   = None
                        self._drag_current_rect = None
                    return

                try:
                    if (prev_mode == "move" or prev_mode.startswith("resize_")) \
                            and self._selected is not None \
                            and self._drag_current_rect is not None \
                            and self._drag_start_rect is not None:
                        xref       = self._selected[1]
                        final_rect = self._drag_current_rect
                        start_rect = self._drag_start_rect
                        wrote_doc  = False
                        new_xref   = xref
                        # Single document write at gesture end + clear HIDDEN flag.
                        with self._doc_lock:
                            result = None
                            if prev_mode == "move":
                                total_dx = final_rect.x0 - start_rect.x0
                                total_dy = final_rect.y0 - start_rect.y0
                                if abs(total_dx) > 0.01 or abs(total_dy) > 0.01:
                                    result = self._annot.move_annot(
                                        self.doc, pn, xref, total_dx, total_dy,
                                    )
                                    wrote_doc = True
                            else:
                                result = self._annot.resize_annot(
                                    self.doc, pn, xref, final_rect,
                                )
                                wrote_doc = True
                            if result is not None:
                                new_rect, new_xref = result
                                final_rect = new_rect
                            if was_hidden:
                                # If xref changed (polygon delete+recreate), the
                                # old annot is gone and the new one is not hidden.
                                if new_xref == xref:
                                    self._annot.set_annot_hidden(
                                        self.doc, pn, xref, False,
                                    )
                        self._drag_annot_hidden = False
                        if new_xref != xref:
                            self._selected = (pn, new_xref)
                        # Update overlay + cached rect first so the next pan_start
                        # sees the new geometry without waiting for the render.
                        self._refresh_selected_overlay(pn, annot_rect=final_rect)
                        # Background re-render (no full page flash).
                        if wrote_doc or was_hidden:
                            self._rerender_page_image(pn)
                except Exception:
                    # Best-effort: if we hid the annot but crashed, unhide it
                    # so the user doesn't end up with an invisible annotation.
                    if self._drag_annot_hidden and self._selected is not None:
                        try:
                            with self._doc_lock:
                                self._annot.set_annot_hidden(
                                    self.doc, pn, self._selected[1], False
                                )
                        except Exception:
                            pass
                        self._drag_annot_hidden = False
                        self._rerender_page_image(pn)
                finally:
                    self._drag_start_rect   = None
                    self._drag_current_rect = None
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
            # Shapes: auto-switch to cursor and select the new annotation so the
            # user can immediately move / resize without manually switching tool.
            if tool in (Tool.RECT, Tool.CIRCLE, Tool.LINE):
                self._select_tool(Tool.CURSOR, ft.MouseCursor.BASIC)
                if self._annot._history:
                    last_pn, last_xref = self._annot._history[-1]
                    if last_pn == pn:
                        with self._doc_lock:
                            for a in self.doc[pn].annots():
                                if a.xref == last_xref:
                                    self._select_annot(pn, a)
                                    break
                self._rerender_page_image(pn)
            else:
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

    def _apply_rotation_preview(self, pn: int, angle_rad: float) -> None:
        """Apply a visual-only rotation to the selection overlay during a
        rotation-handle drag.  Rotates around the bbox centre (not the
        container centre, which is offset down by MENU_EXTRA).
        """
        if pn >= len(self._sel_overlays):
            return
        sel_ov = self._sel_overlays[pn]
        total_h = sel_ov.height or 0
        # _MENU_EXTRA from _annot_mixin — the menu sits below the bbox inside
        # the same container, so the bbox centre is shifted up from the
        # container's geometric centre.
        from ._annot_mixin import _MENU_EXTRA
        if total_h > _MENU_EXTRA:
            box_h = total_h - _MENU_EXTRA
            # Alignment y: -1 is top edge, +1 is bottom edge. We want the pivot
            # at y = box_h/2 from the top, while the container's midpoint is at
            # total_h/2. So offset = (box_h/2 - total_h/2) / (total_h/2).
            ay = (box_h / 2 - total_h / 2) / (total_h / 2)
        else:
            ay = 0.0
        sel_ov.rotate = ft.Rotate(angle=angle_rad, alignment=ft.Alignment(0.0, ay))
        try:
            sel_ov.update()
        except Exception:
            pass

    def _clear_rotation_preview(self, pn: int) -> None:
        """Remove any rotation preview transform from the selection overlay."""
        if pn >= len(self._sel_overlays):
            return
        sel_ov = self._sel_overlays[pn]
        sel_ov.rotate = None
        try:
            sel_ov.update()
        except Exception:
            pass

    def _ensure_drag_ghost_active(self, pn: int) -> None:
        """Hide the real annotation the first time a drag moves so the
        selection overlay looks like it is moving the annotation itself
        instead of trailing behind a stale page image.
        """
        if self._drag_annot_hidden or self._selected is None:
            return
        if self._selected[0] != pn:
            return
        xref = self._selected[1]
        try:
            with self._doc_lock:
                ok = self._annot.set_annot_hidden(self.doc, pn, xref, True)
        except Exception:
            return
        if ok:
            self._drag_annot_hidden = True
            self._rerender_page_image(pn)

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
