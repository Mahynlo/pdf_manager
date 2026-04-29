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
        """Return dict of display-space handle centres (axis-aligned, no rotation)."""
        if self._selected is None or self._selected[0] != pn:
            return None

        if self._selected_visual_rect is not None:
            r = fitz.Rect(self._selected_visual_rect)
        elif self._selected_rect is not None:
            r = fitz.Rect(self._selected_rect)
        else:
            xref = self._selected[1]
            with self._doc_lock:
                page = self.doc[pn]
                r = next((fitz.Rect(a.rect) for a in page.annots() if a.xref == xref), None)
            if r is None:
                return None

        scale = self.zoom * BASE_SCALE
        x0 = r.x0 * scale
        y0 = r.y0 * scale
        x1 = r.x1 * scale
        y1 = r.y1 * scale
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2

        return {
            "tl": (x0, y0),
            "tr": (x1, y0),
            "bl": (x0, y1),
            "br": (x1, y1),
            "cx": cx,
            "cy": cy,
            "r":  r,
        }

    def _detect_drag_mode(self, pn: int, dx: float, dy: float) -> str:
        """Return the drag mode string for a click at display position (dx, dy)."""
        positions = self._sel_handle_positions(pn)
        if positions is None:
            return "none"

        for name in ("tl", "tr", "bl", "br"):
            hx, hy = positions[name]
            if math.hypot(dx - hx, dy - hy) <= _HANDLE_HIT_R:
                return f"resize_{name}"

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
        # Legacy SELECT tool (still usable programmatically).
        if self._annot.tool == Tool.SELECT:
            if (self._pending_tap is not None
                    and self._pending_tap_page == pn):
                x, y = self._pending_tap
                pdf_x, pdf_y = display_to_pdf(x, y, self.zoom)
                self._pending_tap      = None
                self._pending_tap_page = None
                if self._tap_count >= 3:
                    self._hide_text_sel_bar()
                    self._select_paragraph_at(pn, (pdf_x, pdf_y))
                    return
                if self._tap_count == 2:
                    self._hide_text_sel_bar()
                    self._select_word_at(pn, (pdf_x, pdf_y))
                    return
            self._hide_text_sel_bar()
            self._pending_tap      = None
            self._pending_tap_page = None
            return

        # Smart pointer: unified annotation + text selection.
        if self._annot.tool == Tool.CURSOR:
            if (self._pending_tap is None or self._pending_tap_page != pn):
                self._pending_tap      = None
                self._pending_tap_page = None
                return
            x, y = self._pending_tap
            self._pending_tap      = None
            self._pending_tap_page = None
            pdf_x, pdf_y = display_to_pdf(x, y, self.zoom)

            if self._tap_count >= 3:
                # Triple-tap → select paragraph
                self._deselect_annot()
                self._select_paragraph_at(pn, (pdf_x, pdf_y))
                return

            if self._tap_count == 2:
                # Double-tap → word select (or keep annotation if tapped on one)
                with self._doc_lock:
                    page  = self.doc[pn]
                    annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
                if annot:
                    self._hide_text_sel_bar()
                    self.current_page = pn
                    self._select_annot(pn, annot)
                else:
                    self._deselect_annot()
                    self._select_word_at(pn, (pdf_x, pdf_y))
                return

            # Single tap
            with self._doc_lock:
                page  = self.doc[pn]
                annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
            if annot:
                self._hide_text_sel_bar()
                self.current_page = pn
                self._select_annot(pn, annot)
            else:
                self._deselect_annot()
                self._hide_text_sel_bar()
            return

        if self._annot.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            if (self._pending_tap is None or self._pending_tap_page != pn):
                self._pending_tap      = None
                self._pending_tap_page = None
                return
            x, y = self._pending_tap
            self._pending_tap      = None
            self._pending_tap_page = None
            pdf_x, pdf_y = display_to_pdf(x, y, self.zoom)
            if self._tap_count >= 3:
                self._hide_text_sel_bar()
                self._select_paragraph_at(pn, (pdf_x, pdf_y))
                active_tool = self._annot.tool
                self._text_sel_apply(active_tool)
                self._select_last_annot(pn)
                return
            if self._tap_count == 2:
                self._hide_text_sel_bar()
                self._select_word_at(pn, (pdf_x, pdf_y))
                active_tool = self._annot.tool
                self._text_sel_apply(active_tool)
                self._select_last_annot(pn)
                return
            self._hide_text_sel_bar()
            return

        self._pending_tap      = None
        self._pending_tap_page = None

    # ── pan events ────────────────────────────────────────────────────────────

    def _on_pan_start(self, e: ft.DragStartEvent, pn: int) -> None:
        self._pending_tap      = None
        self._pending_tap_page = None

        if self._annot.tool == Tool.CURSOR:
            try:
                pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
                _H_HIT = 20  # px hit radius for handles

                # ── 1. Active annotation: check resize/move handles ───────────
                drag_seed = self._selected_visual_rect or self._selected_rect
                if (self._selected is not None
                        and self._selected[0] == pn
                        and drag_seed is not None):
                    sel_atype = getattr(self, "_selected_atype", "")
                    if sel_atype not in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
                        mode = self._detect_drag_mode(pn, e.local_x, e.local_y)
                        if mode != "none":
                            self._drag_start_rect   = fitz.Rect(drag_seed)
                            self._drag_current_rect = fitz.Rect(drag_seed)
                            self._drag_mode         = mode
                            self._move_last_pdf     = (pdf_x, pdf_y)
                            return
                    # Click outside active annotation (or on markup): deselect,
                    # then fall through to text-selection / new annotation.
                    self._deselect_annot()

                # ── 2. Text-selection handles (extend existing selection) ─────
                for hname in ("start", "end"):
                    hpos = getattr(self, f"_text_sel_handle_{hname}_disp", None)
                    if (hpos is not None
                            and self._text_sel_pn == pn
                            and math.hypot(e.local_x - hpos[0], e.local_y - hpos[1]) <= _H_HIT):
                        self._sel_drag_handle = hname
                        return

                # ── 3. Annotation under cursor → select and prepare to drag ──
                cached_rect: fitz.Rect | None = None
                found_annot = None
                is_markup   = False
                with self._doc_lock:
                    page  = self.doc[pn]
                    annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
                    if annot is not None:
                        atype = (annot.type[1]
                                 if isinstance(annot.type, (tuple, list)) and len(annot.type) > 1
                                 else "")
                        cached_rect = fitz.Rect(annot.rect)
                        found_annot = annot
                        is_markup = atype in ("Highlight", "Underline", "StrikeOut", "Squiggly")

                if found_annot is not None and cached_rect is not None:
                    self._hide_text_sel_bar()
                    self.current_page = pn
                    self._select_annot(pn, found_annot)
                    if not is_markup:
                        self._drag_mode         = "move"
                        self._move_last_pdf     = (pdf_x, pdf_y)
                        self._drag_start_rect   = cached_rect
                        self._drag_current_rect = fitz.Rect(cached_rect)
                    return

                # ── 4. Nothing found → start smart text-selection drag ────────
                self._sel_drag_handle        = None
                self._smart_text_sel_active  = True
                self._text_sel_pn            = pn
                self._text_sel_start_pdf     = (pdf_x, pdf_y)
                self._text_sel_end_pdf       = (pdf_x, pdf_y)
                self._hide_text_sel_bar()
                # Temporarily switch to text cursor for visual feedback
                for gd in self._page_gestures:
                    gd.mouse_cursor = ft.MouseCursor.TEXT
                    try:
                        gd.update()
                    except Exception:
                        pass

            except Exception:
                pass
            return

        self.current_page = pn
        pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)

        if self._annot.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            self._sel_drag_handle       = None
            self._smart_text_sel_active = True
            self._text_sel_pn           = pn
            self._text_sel_start_pdf    = (pdf_x, pdf_y)
            self._text_sel_end_pdf      = (pdf_x, pdf_y)
            self._hide_text_sel_bar()
            for gd in self._page_gestures:
                gd.mouse_cursor = ft.MouseCursor.TEXT
                try:
                    gd.update()
                except Exception:
                    pass
            return

        if self._annot.tool == Tool.INK:
            self._ink_points = [(pdf_x, pdf_y)]
            self._ink_page   = pn
            return

        if self._annot.tool == Tool.SELECT:
            # Legacy SELECT tool — hit-test handles first.
            _H_HIT = 20
            for hname in ("start", "end"):
                hpos = getattr(self, f"_text_sel_handle_{hname}_disp", None)
                if (hpos is not None
                        and self._text_sel_pn == pn
                        and math.hypot(e.local_x - hpos[0], e.local_y - hpos[1]) <= _H_HIT):
                    self._sel_drag_handle = hname
                    return
            self._sel_drag_handle    = None
            self._text_sel_start_pdf = (pdf_x, pdf_y)
            self._text_sel_end_pdf   = (pdf_x, pdf_y)
            self._hide_text_sel_bar()
        self._annot.begin(pdf_x, pdf_y)
        if self._annot.tool in (Tool.LINE, Tool.ARROW):
            self._line_drag_start_disp = (e.local_x, e.local_y)

    def _on_pan_update(self, e: ft.DragUpdateEvent, pn: int) -> None:
        if self._annot.tool == Tool.CURSOR:
            # ── Handle drag (extend existing text selection) ──────────────────
            if self._sel_drag_handle is not None:
                pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
                if self._sel_drag_handle == "start":
                    self._text_sel_start_pdf = (pdf_x, pdf_y)
                else:
                    self._text_sel_end_pdf = (pdf_x, pdf_y)
                self._update_text_selection(
                    pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
                )
                return

            # ── Annotation drag (lock-free: only overlay moves, PDF at end) ──
            if (self._drag_mode is not None
                    and self._selected is not None
                    and self._drag_current_rect is not None
                    and self._drag_start_rect is not None
                    and self._selected[0] == pn
                    and self._move_last_pdf is not None):
                try:
                    pdf_x, pdf_y   = display_to_pdf(e.local_x, e.local_y, self.zoom)
                    last_x, last_y = self._move_last_pdf
                    dx = pdf_x - last_x
                    dy = pdf_y - last_y
                    if math.isclose(dx, 0.0, abs_tol=0.01) and math.isclose(dy, 0.0, abs_tol=0.01):
                        return
                    if self._drag_mode == "move":
                        r = self._drag_current_rect
                        new_rect = fitz.Rect(r.x0+dx, r.y0+dy, r.x1+dx, r.y1+dy)
                        self._drag_current_rect = new_rect
                        self._move_last_pdf     = (pdf_x, pdf_y)
                        self._ensure_drag_ghost_active(pn)
                        self._refresh_selected_overlay(pn, annot_rect=new_rect)
                    elif self._drag_mode.startswith("resize_"):
                        handle   = self._drag_mode[len("resize_"):]
                        new_rect = self._compute_resize_rect(self._drag_current_rect, handle, dx, dy)
                        self._drag_current_rect = new_rect
                        self._move_last_pdf     = (pdf_x, pdf_y)
                        self._ensure_drag_ghost_active(pn)
                        self._refresh_selected_overlay(pn, annot_rect=new_rect)
                except Exception:
                    pass
                return

            # ── Smart text-selection drag ─────────────────────────────────────
            if getattr(self, "_smart_text_sel_active", False):
                try:
                    pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
                    self._text_sel_end_pdf = (pdf_x, pdf_y)
                    self._update_text_selection(
                        pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
                    )
                except Exception:
                    pass
            return

        pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)

        if self._annot.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            if getattr(self, "_smart_text_sel_active", False):
                self._text_sel_end_pdf = (pdf_x, pdf_y)
                self._update_text_selection(
                    pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
                )
            return

        if self._annot.tool == Tool.INK:
            ink_pts = getattr(self, "_ink_points", None)
            ink_pg  = getattr(self, "_ink_page",   None)
            if ink_pts is not None and ink_pg == pn:
                ink_pts.append((pdf_x, pdf_y))
                self._update_ink_canvas_preview(pn)
            return

        # Legacy SELECT tool handle drag
        if self._annot.tool == Tool.SELECT and self._sel_drag_handle is not None:
            if self._sel_drag_handle == "start":
                self._text_sel_start_pdf = (pdf_x, pdf_y)
            else:
                self._text_sel_end_pdf = (pdf_x, pdf_y)
            self._update_text_selection(
                pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
            )
            return

        pdf_rect = self._annot.move(pdf_x, pdf_y)
        if pdf_rect is None:
            return
        scale = self.zoom * BASE_SCALE

        if self._annot.tool == Tool.SELECT:
            self._text_sel_end_pdf = (pdf_x, pdf_y)
            self._update_text_selection(
                pn, self._text_sel_start_pdf, (pdf_x, pdf_y), update_ui=True
            )
        elif self._annot.tool in (Tool.LINE, Tool.ARROW):
            start = getattr(self, "_line_drag_start_disp", None)
            if start is not None:
                self._update_line_canvas_preview(
                    pn, start[0], start[1], e.local_x, e.local_y,
                    is_arrow=(self._annot.tool == Tool.ARROW),
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

    # ── committed-ink overlay helpers ─────────────────────────────────────────

    def _add_committed_ink_stroke(self, pn: int, pdf_pts: list[tuple[float, float]]) -> None:
        """Save *pdf_pts* as a committed (not-yet-rendered) ink stroke for *pn*."""
        committed: dict = getattr(self, "_committed_ink_points", None)
        if committed is None:
            committed = {}
            self._committed_ink_points = committed
        committed.setdefault(pn, []).append(list(pdf_pts))

    def _update_committed_ink_canvas(self, pn: int) -> None:
        """Repaint the ink canvas to show all committed-but-not-yet-rendered strokes."""
        canvases = getattr(self, "_ink_canvases", [])
        if pn >= len(canvases):
            return
        import flet.canvas as cv
        committed: dict = getattr(self, "_committed_ink_points", {})
        pts_list = committed.get(pn, [])
        shapes = []
        scale = self.zoom * BASE_SCALE
        for pts in pts_list:
            if len(pts) < 2:
                continue
            disp = [(x * scale, y * scale) for x, y in pts]
            shapes.append(cv.Path(
                elements=[cv.Path.MoveTo(disp[0][0], disp[0][1])]
                         + [cv.Path.LineTo(x, y) for x, y in disp[1:]],
                paint=ft.Paint(stroke_width=2, color="#CC1155DD",
                               style=ft.PaintingStyle.STROKE),
            ))
        canvases[pn].shapes = shapes
        try:
            canvases[pn].update()
        except Exception:
            pass

    def _on_page_rendered(self, pn: int) -> None:
        """Called by the render worker after slot.update() — clears committed overlay.

        If another render is already queued for this page (pending_rerender),
        keep the canvas: the queued render will include strokes committed after
        this render started, and clearing now would make them flash invisible.
        """
        pending = getattr(self, "_pending_rerender", set())
        if pn in pending:
            return
        committed: dict = getattr(self, "_committed_ink_points", {})
        if pn in committed:
            del committed[pn]
            self._clear_ink_canvas_preview(pn)

    # ─────────────────────────────────────────────────────────────────────────

    def _restore_smart_cursor(self) -> None:
        """Restore the GestureDetector cursor after a smart text-selection drag."""
        for gd in self._page_gestures:
            gd.mouse_cursor = self._current_cursor
            try:
                gd.update()
            except Exception:
                pass

    def _select_last_annot(self, pn: int) -> None:
        """Select the most-recently created annotation on *pn* (shows color/delete bar)."""
        if not self._annot._history:
            return
        last_pn, last_xref = self._annot._history[-1]
        if last_pn != pn:
            return
        with self._doc_lock:
            for a in self.doc[pn].annots():
                if a.xref == last_xref:
                    self._select_annot(pn, a)
                    break

    def _on_pan_end(self, e: ft.DragEndEvent, pn: int) -> None:
        if self._annot.tool == Tool.CURSOR:
            # ── Text-selection handle drag end ────────────────────────────────
            if self._sel_drag_handle is not None:
                self._sel_drag_handle = None
                sel_text = self._update_text_selection(
                    pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
                )
                if sel_text:
                    if self._text_sel_sel_rect is not None:
                        self._annot.last_rect = self._text_sel_sel_rect
                    self._show_text_sel_bar(sel_text)
                self._restore_smart_cursor()
                return

            # ── Annotation drag end ───────────────────────────────────────────
            if self._drag_mode is not None:
                prev_mode       = self._drag_mode
                self._drag_mode = None
                self._move_last_pdf = None
                was_hidden = self._drag_annot_hidden

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
                                actual_rect, new_xref, _rotation = result
                                # Use the rect PyMuPDF actually assigned so the
                                # overlay always matches the annotation exactly
                                # (Line/Arrow/Ink xref changes on delete+recreate,
                                # so the returned bbox may differ from final_rect).
                                final_rect = actual_rect
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

            # ── Smart text-selection drag end ─────────────────────────────────
            if getattr(self, "_smart_text_sel_active", False):
                self._smart_text_sel_active = False
                sel_text = self._update_text_selection(
                    pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
                )
                if not sel_text:
                    # OCR fallback for image-only pages
                    sel_rect = self._text_sel_sel_rect
                    if sel_rect is None and self._text_sel_start_pdf and self._text_sel_end_pdf:
                        sx, sy = self._text_sel_start_pdf
                        ex, ey = self._text_sel_end_pdf
                        sel_rect = fitz.Rect(min(sx,ex), min(sy,ey), max(sx,ex), max(sy,ey))
                    sel_text = self._ocr_text_in_rect(pn, sel_rect)
                if sel_text:
                    if self._text_sel_sel_rect is not None:
                        self._annot.last_rect = self._text_sel_sel_rect
                    self._show_text_sel_bar(sel_text)
                self._restore_smart_cursor()
            return

        # Legacy SELECT tool handle drag end
        if self._annot.tool == Tool.SELECT and self._sel_drag_handle is not None:
            self._sel_drag_handle = None
            sel_text = self._update_text_selection(
                pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
            )
            if sel_text:
                if self._text_sel_sel_rect is not None:
                    self._annot.last_rect = self._text_sel_sel_rect
                self._show_text_sel_bar(sel_text)
            return

        if self._annot.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            if getattr(self, "_smart_text_sel_active", False):
                self._smart_text_sel_active = False
                sel_text = self._update_text_selection(
                    pn, self._text_sel_start_pdf, self._text_sel_end_pdf, update_ui=True
                )
                if not sel_text:
                    sel_rect = self._text_sel_sel_rect
                    if sel_rect is None and self._text_sel_start_pdf and self._text_sel_end_pdf:
                        sx, sy = self._text_sel_start_pdf
                        ex, ey = self._text_sel_end_pdf
                        sel_rect = fitz.Rect(min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))
                    sel_text = self._ocr_text_in_rect(pn, sel_rect)
                if sel_text:
                    if self._text_sel_sel_rect is not None:
                        self._annot.last_rect = self._text_sel_sel_rect
                    active_tool = self._annot.tool
                    self._text_sel_apply(active_tool)
                    self._select_last_annot(pn)
                self._restore_smart_cursor()
            return

        if self._annot.tool == Tool.INK:
            ink_pts = getattr(self, "_ink_points", [])
            ink_pg  = getattr(self, "_ink_page",   None)
            if ink_pg == pn and len(ink_pts) >= 2:
                with self._doc_lock:
                    self._annot.commit_ink(self.doc, pn, ink_pts)
                # Keep the stroke visible on the ink canvas until the background
                # page re-render completes (avoids a flash where the stroke
                # appears to disappear between canvas-clear and render-done).
                self._add_committed_ink_stroke(pn, ink_pts)
                self._update_committed_ink_canvas(pn)
                # Auto-switch to cursor and select the new ink annotation so
                # the user can immediately move / style it.
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
                self._clear_ink_canvas_preview(pn)
            self._ink_points = []
            self._ink_page   = None
            return

        if self._annot.tool in (Tool.LINE, Tool.ARROW):
            self._clear_ink_canvas_preview(pn)
            self._line_drag_start_disp = None
        else:
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
            if tool in (Tool.RECT, Tool.CIRCLE, Tool.LINE, Tool.ARROW):
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
                    xref = new_markup[0]
                    with self._doc_lock:
                        for a in self.doc[pn].annots():
                            if a.xref == xref:
                                self._select_annot(pn, a)
                                break
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

    # ── ink canvas preview ────────────────────────────────────────────────────

    def _update_ink_canvas_preview(self, pn: int) -> None:
        ink_pts = getattr(self, "_ink_points", [])
        canvases = getattr(self, "_ink_canvases", [])
        if pn >= len(canvases) or len(ink_pts) < 2:
            return
        import flet.canvas as cv
        scale = self.zoom * BASE_SCALE
        disp  = [(x * scale, y * scale) for x, y in ink_pts]
        current_path = cv.Path(
            elements=[cv.Path.MoveTo(disp[0][0], disp[0][1])]
                     + [cv.Path.LineTo(x, y) for x, y in disp[1:]],
            paint=ft.Paint(
                stroke_width=2,
                color="#CC1155DD",
                style=ft.PaintingStyle.STROKE,
            ),
        )
        # Prepend any committed-but-not-yet-rendered strokes so they remain
        # visible while the user is drawing the next stroke.
        committed: dict = getattr(self, "_committed_ink_points", {})
        shapes = []
        for pts in committed.get(pn, []):
            if len(pts) < 2:
                continue
            d = [(x * scale, y * scale) for x, y in pts]
            shapes.append(cv.Path(
                elements=[cv.Path.MoveTo(d[0][0], d[0][1])]
                         + [cv.Path.LineTo(x, y) for x, y in d[1:]],
                paint=ft.Paint(stroke_width=2, color="#CC1155DD",
                               style=ft.PaintingStyle.STROKE),
            ))
        shapes.append(current_path)
        canvases[pn].shapes = shapes
        try:
            canvases[pn].update()
        except Exception:
            pass

    def _clear_ink_canvas_preview(self, pn: int) -> None:
        canvases = getattr(self, "_ink_canvases", [])
        if pn >= len(canvases):
            return
        canvases[pn].shapes = []
        try:
            canvases[pn].update()
        except Exception:
            pass

    def _update_line_canvas_preview(
        self, pn: int,
        x0: float, y0: float, x1: float, y1: float,
        is_arrow: bool = False,
    ) -> None:
        """Draw a line (optionally with arrowhead) on the ink canvas as preview."""
        canvases = getattr(self, "_ink_canvases", [])
        if pn >= len(canvases):
            return
        import flet.canvas as cv
        color = "#CCAA2200"
        stroke_w = 2.0
        elements: list = [cv.Path.MoveTo(x0, y0), cv.Path.LineTo(x1, y1)]
        if is_arrow:
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length > 1:
                arrow_len   = min(20.0, length * 0.35)
                arrow_angle = math.pi / 6
                angle       = math.atan2(dy, dx)
                for side in (-1, 1):
                    ax = x1 - arrow_len * math.cos(angle - side * arrow_angle)
                    ay = y1 - arrow_len * math.sin(angle - side * arrow_angle)
                    elements += [cv.Path.MoveTo(x1, y1), cv.Path.LineTo(ax, ay)]
        path = cv.Path(
            elements=elements,
            paint=ft.Paint(stroke_width=stroke_w, color=color, style=ft.PaintingStyle.STROKE),
        )
        canvases[pn].shapes = [path]
        try:
            canvases[pn].update()
        except Exception:
            pass

    def _on_hover(self, e: ft.HoverEvent, pn: int) -> None:
        """Update the mouse cursor as it moves over a page in CURSOR tool mode."""
        if self._annot.tool != Tool.CURSOR:
            return
        # Don't override cursor during an active drag or text-selection
        if (getattr(self, "_smart_text_sel_active", False)
                or self._sel_drag_handle is not None
                or self._drag_mode is not None):
            return
        try:
            pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
            with self._doc_lock:
                page  = self.doc[pn]
                annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
            if annot is not None:
                new_cursor = ft.MouseCursor.BASIC
            else:
                new_cursor = ft.MouseCursor.TEXT if self._point_has_text(pn, pdf_x, pdf_y) else ft.MouseCursor.BASIC
        except Exception:
            return
        gd = self._page_gestures[pn] if pn < len(self._page_gestures) else None
        if gd is not None and gd.mouse_cursor != new_cursor:
            gd.mouse_cursor = new_cursor
            try:
                gd.update()
            except Exception:
                pass

    def _point_has_text(self, pn: int, pdf_x: float, pdf_y: float) -> bool:
        """Return True if (pdf_x, pdf_y) falls inside any text word on page pn
        (native PDF text or OCR detections)."""
        pt = fitz.Point(pdf_x, pdf_y)
        # Native text (cached per page)
        cache = self._text_rects_cache
        if pn not in cache:
            try:
                with self._doc_lock:
                    words = self.doc[pn].get_text("words")
                cache[pn] = [fitz.Rect(w[0], w[1], w[2], w[3]) for w in words]
            except Exception:
                cache[pn] = []
        if any(r.contains(pt) for r in cache[pn]):
            return True
        # OCR detections (already computed; bbox is in PDF space)
        ocr_result = self._ocr_by_page.get(pn)
        if ocr_result is not None:
            for det in ocr_result.detections:
                if det.bbox.contains(pt):
                    return True
        return False

    def _on_secondary_tap(self, e, pn: int) -> None:
        """Right-click: show the action popup for the active text selection."""
        if self._annot.tool not in (Tool.SELECT, Tool.CURSOR):
            return
        if self._text_sel_pn != pn or not self._text_sel_text:
            return
        self._show_text_sel_bar(self._text_sel_text)

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
