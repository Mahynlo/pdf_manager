"""Word-level text selection overlay and action popup for PDFViewerTab."""
from __future__ import annotations

import urllib.parse

import flet as ft
import fitz

from .annotations import Tool
from .renderer import BASE_SCALE


# ── column-aware reading order ────────────────────────────────────────────────

def _sort_words_column_aware(words: list[tuple], page_width: float) -> list[tuple]:
    """Sort words in column-aware reading order.

    Detects multi-column layouts by finding significant gaps in the horizontal
    distribution of word x-centres.  When a gap ≥ 8 % of page width is found,
    words are sorted column-first (left column entirely before right column),
    which prevents cross-column "bleeding" during flow selection.

    Falls back to simple row-band sort for single-column pages.
    """
    if len(words) < 4:
        result = list(words)
        result.sort(key=lambda w: (round(w[0].y0 / 5) * 5, w[0].x0))
        return result

    # Compute x-centre for every word and sort them
    x_centers = sorted((r.x0 + r.x1) / 2.0 for r, _ in words)

    # Find the single largest gap between consecutive x-centres
    max_gap = 0.0
    split_x = None
    for i in range(len(x_centers) - 1):
        gap = x_centers[i + 1] - x_centers[i]
        if gap > max_gap:
            max_gap = gap
            split_x = (x_centers[i] + x_centers[i + 1]) / 2.0

    threshold = max(30.0, page_width * 0.08)  # ~48 pt for A4

    result = list(words)
    if split_x is None or max_gap < threshold:
        # Single column: row-band sort
        result.sort(key=lambda w: (round(w[0].y0 / 5) * 5, w[0].x0))
    else:
        # Multi-column: column index first, then row-band, then x
        result.sort(key=lambda w: (
            0 if (w[0].x0 + w[0].x1) / 2.0 < split_x else 1,
            round(w[0].y0 / 5) * 5,
            w[0].x0,
        ))

    return result


class _TextSelMixin:
    """Flow-based text selection: word highlights + floating action popup."""

    # ── visual sweep selection ────────────────────────────────────────────────

    @staticmethod
    def _words_in_sweep(
        words: list[tuple], start_pt: tuple, end_pt: tuple
    ) -> list[tuple]:
        """Return words that fall within the visual sweep from start_pt to end_pt.

        Uses bounding-box line-band logic instead of sorted-list index ranges,
        so the result is always correct regardless of the column-aware sort order.
        Words on the first line are filtered by start x, words on the last line
        by end x, and all intermediate lines are included in full.
        """
        px_s, py_s = start_pt
        px_e, py_e = end_pt
        # Normalise: ensure the start point is above (or left of) the end point
        if py_s > py_e or (abs(py_s - py_e) < 2 and px_s > px_e):
            px_s, py_s, px_e, py_e = px_e, py_e, px_s, py_s

        BAND = 5  # pt tolerance for line-band grouping
        start_band = round(py_s / BAND) * BAND
        end_band   = round(py_e / BAND) * BAND

        result: list[tuple] = []
        for r, t in words:
            if not t.strip():
                continue
            word_band = round(r.y0 / BAND) * BAND
            if word_band < start_band or word_band > end_band:
                continue
            if start_band == end_band:
                # Single-line drag: include words whose rect overlaps [px_s, px_e]
                lo, hi = min(px_s, px_e), max(px_s, px_e)
                if r.x1 < lo - BAND or r.x0 > hi + BAND:
                    continue
            elif word_band == start_band:
                # First line: only words to the right of (or touching) start x
                if r.x1 < px_s - BAND:
                    continue
            elif word_band == end_band:
                # Last line: only words to the left of (or touching) end x
                if r.x0 > px_e + BAND:
                    continue
            result.append((r, t))

        # Sort by (line-band, x) so text output is always in reading order
        result.sort(key=lambda w: (round(w[0].y0 / BAND) * BAND, w[0].x0))
        return result

    # ── word cache ────────────────────────────────────────────────────────────

    def _get_page_words(self, pn: int) -> list[tuple]:
        """Return (fitz.Rect, str) list for every word on page *pn* (cached)."""
        if pn in self._page_words:
            return self._page_words[pn]
        with self._doc_lock:
            raw        = self.doc[pn].get_text("words")
            page_width = self.doc[pn].rect.width
        words: list[tuple] = [
            (fitz.Rect(w[0], w[1], w[2], w[3]), w[4]) for w in raw
        ]
        if pn in self._ocr_by_page:
            for det in self._ocr_by_page[pn].detections:
                if det.bbox and det.text.strip():
                    words.append((det.bbox, det.text))
        # Column-aware reading order (handles 2-column layouts correctly)
        words = _sort_words_column_aware(words, page_width)
        self._page_words[pn] = words
        return words

    # ── flow-based selection ──────────────────────────────────────────────────

    def _nearest_word_index(
        self, words: list[tuple], pt: tuple[float, float]
    ) -> int:
        """Return the index of the word at or nearest to PDF point *pt*."""
        if not words:
            return 0
        px, py = pt
        for i, (r, _) in enumerate(words):
            if r.x0 <= px <= r.x1 and r.y0 <= py <= r.y1:
                return i
        best_i, best_d = 0, float("inf")
        for i, (r, _) in enumerate(words):
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            d = (px - cx) ** 2 + (py - cy) ** 2
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    def _update_text_selection(
        self,
        pn: int,
        start_pt: tuple | None,
        end_pt: tuple | None,
        *,
        update_ui: bool = False,
    ) -> str:
        """
        Highlight words between *start_pt* and *end_pt* in reading order.
        Returns the selected text string.
        """
        if pn >= len(self._text_sel_layers) or start_pt is None or end_pt is None:
            return ""

        scale = self.zoom * BASE_SCALE
        words = self._get_page_words(pn)
        if not words:
            return ""

        # Bounding-box sweep: independent of column-sort order, so words are
        # never incorrectly excluded because their sorted index falls outside [si:ei].
        selected = self._words_in_sweep(words, start_pt, end_pt)
        if not selected:
            # Fallback for single-click or very small drag: nearest word
            si = self._nearest_word_index(words, start_pt)
            ei = self._nearest_word_index(words, end_pt)
            if si > ei:
                si, ei = ei, si
            selected = [(r, t) for r, t in words[si : ei + 1] if t.strip()]

        # Group word rects by line band (5 pt tolerance) so we render one
        # Container per line instead of one per word.  This prevents Flet from
        # dropping controls when updating a large Stack, and fills visual gaps
        # between words on the same line.
        from collections import defaultdict
        line_bands: dict = defaultdict(list)
        for word_rect, word_text in selected:
            if not word_text.strip():
                continue
            band = round(word_rect.y0 / 5) * 5
            line_bands[band].append(word_rect)

        boxes: list[ft.Control] = []
        sel_rect: fitz.Rect | None = None
        for band in sorted(line_bands):
            rects = line_bands[band]
            x0 = min(r.x0 for r in rects)
            x1 = max(r.x1 for r in rects)
            y0 = min(r.y0 for r in rects)
            y1 = max(r.y1 for r in rects)
            boxes.append(ft.Container(
                left   = x0 * scale,
                top    = y0 * scale,
                width  = max(2.0, (x1 - x0) * scale),
                height = max(2.0, (y1 - y0) * scale),
                bgcolor="#5500AAFF",
            ))
            line_r = fitz.Rect(x0, y0, x1, y1)
            sel_rect = line_r if sel_rect is None else sel_rect | line_r

        # Draggable handles at the start and end of the selection
        _H_R = 7  # handle circle radius in display px
        if selected:
            first_r = selected[0][0]
            last_r  = selected[-1][0]
            s_disp  = (first_r.x0 * scale, first_r.y1 * scale)
            e_disp  = (last_r.x1  * scale, last_r.y1  * scale)
            self._text_sel_handle_start_disp = s_disp
            self._text_sel_handle_end_disp   = e_disp
            _h = dict(
                width=_H_R * 2, height=_H_R * 2,
                border_radius=_H_R,
                bgcolor="#0088FF",
                border=ft.border.all(2, "#FFFFFF"),
                shadow=ft.BoxShadow(blur_radius=4, color="#44000000"),
            )
            boxes.append(ft.Container(left=s_disp[0] - _H_R, top=s_disp[1] - _H_R, **_h))
            boxes.append(ft.Container(left=e_disp[0] - _H_R, top=e_disp[1] - _H_R, **_h))
        else:
            self._text_sel_handle_start_disp = None
            self._text_sel_handle_end_disp   = None

        layer = self._text_sel_layers[pn]
        layer.controls = boxes
        layer.visible  = bool(boxes)
        self._text_sel_pn       = pn if boxes else None
        self._text_sel_sel_rect = sel_rect
        if update_ui:
            try:
                layer.update()
            except Exception:
                pass

        return " ".join(t.strip() for _, t in selected if t.strip())

    def _clear_text_selection(self) -> None:
        pn = self._text_sel_pn
        if pn is not None and pn < len(self._text_sel_layers):
            layer = self._text_sel_layers[pn]
            layer.controls = []
            layer.visible  = False
            try:
                layer.update()
            except Exception:
                pass
        self._text_sel_pn                = None
        self._text_sel_text              = ""
        self._text_sel_handle_start_disp = None
        self._text_sel_handle_end_disp   = None

    # ── floating popup ────────────────────────────────────────────────────────

    def _show_text_sel_bar(self, text: str) -> None:
        self._text_sel_text = text
        pn = self._text_sel_pn
        if pn is None or pn >= len(self._text_sel_popups):
            return
        popup    = self._text_sel_popups[pn]
        sel_rect = self._text_sel_sel_rect
        scale    = self.zoom * BASE_SCALE
        if sel_rect is not None:
            _POPUP_H = 44   # estimated popup height in display px
            _POPUP_W = 310  # estimated popup width in display px
            _MARGIN  = 8

            page_h = float(self._page_heights[pn]) if pn < len(self._page_heights) else 9999.0
            page_w = float(self._page_slots[pn].width or 9999) if pn < len(self._page_slots) else 9999.0

            # Vertical: show below selection unless popup would overflow the page bottom
            below_top = sel_rect.y1 * scale + _MARGIN
            above_top = sel_rect.y0 * scale - _POPUP_H - _MARGIN

            if below_top + _POPUP_H <= page_h - _MARGIN:
                popup.top = below_top
            else:
                popup.top = max(_MARGIN, above_top)

            # Horizontal: align with selection start, clamped so popup stays on page
            popup.left = max(0.0, min(sel_rect.x0 * scale, page_w - _POPUP_W))

        popup.visible = True
        try:
            popup.update()
        except Exception:
            pass

    def _hide_text_sel_bar(self) -> None:
        self._clear_text_selection()
        for popup in self._text_sel_popups:
            if popup.visible:
                popup.visible = False
                try:
                    popup.update()
                except Exception:
                    pass

    # ── popup actions ─────────────────────────────────────────────────────────

    def _text_sel_copy(self, e=None) -> None:
        text = self._text_sel_text
        self._hide_text_sel_bar()
        if text:
            self.page_ref.set_clipboard(text)
            short = text[:60] + ("…" if len(text) > 60 else "")
            self._show_snack(f'Copiado: "{short}"')

    def _text_sel_apply(self, tool: Tool) -> None:
        pn       = self._text_sel_pn
        start_pt = self._text_sel_start_pdf
        end_pt   = self._text_sel_end_pdf
        self._hide_text_sel_bar()
        if pn is None:
            return
        with self._doc_lock:
            changed = self._annot.apply_text_tool(self.doc, pn, tool)
        if changed:
            self._refresh_page(pn)
            return
        # Fallback: native text lookup found nothing (scanned/OCR page).
        # Use the word rects collected during text selection, which include
        # OCR-detected words that don't exist in the native PDF content stream.
        if start_pt is None or end_pt is None:
            return
        words = self._get_page_words(pn)
        if not words:
            return
        from .annotations import STROKE_COLOR, _line_merged_rects
        selected = self._words_in_sweep(words, start_pt, end_pt)
        if not selected:
            si = self._nearest_word_index(words, start_pt)
            ei = self._nearest_word_index(words, end_pt)
            if si > ei:
                si, ei = ei, si
            selected = [(r, t) for r, t in words[si : ei + 1] if t.strip()]
        rects = [r for r, t in selected if t.strip()]
        if not rects:
            return
        merged = _line_merged_rects(rects)
        if not merged:
            return
        with self._doc_lock:
            page = self.doc[pn]
            if tool == Tool.HIGHLIGHT:
                annot = page.add_highlight_annot(merged)
                annot.set_colors(stroke=self._annot.highlight_color)
            elif tool == Tool.UNDERLINE:
                annot = page.add_underline_annot(merged)
                annot.set_colors(stroke=STROKE_COLOR[Tool.UNDERLINE])
            elif tool == Tool.STRIKEOUT:
                annot = page.add_strikeout_annot(merged)
                annot.set_colors(stroke=STROKE_COLOR[Tool.STRIKEOUT])
            else:
                return
            annot.update()
            self._annot._history.append((pn, annot.xref))
        self._refresh_page(pn)

    def _text_sel_dismiss(self, e=None) -> None:
        self._hide_text_sel_bar()

    # ── OCR fallback ──────────────────────────────────────────────────────────

    def _ocr_text_in_rect(self, pn: int, rect: fitz.Rect | None) -> str:
        if rect is None:
            return ""
        result = self._ocr_by_page.get(pn)
        if not result:
            return ""
        parts: list[str] = []
        for seg in result.segments:
            if seg.bbox and rect.intersects(seg.bbox):
                t = seg.text.strip()
                if t:
                    parts.append(t)
        return " ".join(parts)

    # ── word selection (double-tap) ───────────────────────────────────────────

    def _select_word_at(self, pn: int, pdf_pt: tuple) -> None:
        """Select the single word at (or nearest to) pdf_pt."""
        words = self._get_page_words(pn)
        if not words:
            return
        idx = self._nearest_word_index(words, pdf_pt)
        r, _ = words[idx]
        mid_y = (r.y0 + r.y1) / 2
        start_pt = (r.x0, mid_y)
        end_pt   = (r.x1, mid_y)
        self._text_sel_start_pdf = start_pt
        self._text_sel_end_pdf   = end_pt
        sel_text = self._update_text_selection(pn, start_pt, end_pt, update_ui=True)
        if sel_text:
            self._show_text_sel_bar(sel_text)

    # ── paragraph selection (triple-tap) ──────────────────────────────────────

    def _select_paragraph_at(self, pn: int, pdf_pt: tuple) -> None:
        """Select all words in the text block that contains *pdf_pt*."""
        px, py = pdf_pt
        with self._doc_lock:
            blocks = self.doc[pn].get_text("blocks")

        # Find the block that contains the click point (type 0 = text block)
        target_rect: fitz.Rect | None = None
        for block in blocks:
            x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
            btype = block[6] if len(block) > 6 else 0
            if btype != 0:
                continue
            if x0 <= px <= x1 and y0 <= py <= y1:
                target_rect = fitz.Rect(x0, y0, x1, y1)
                break

        # Fallback: nearest text block by centre distance
        if target_rect is None:
            best_dist = float("inf")
            for block in blocks:
                x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
                btype = block[6] if len(block) > 6 else 0
                if btype != 0:
                    continue
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                if d < best_dist:
                    best_dist   = d
                    target_rect = fitz.Rect(x0, y0, x1, y1)

        if target_rect is None:
            return

        words = self._get_page_words(pn)
        si: int | None = None
        ei: int | None = None
        for i, (r, _) in enumerate(words):
            if target_rect.intersects(r):
                if si is None:
                    si = i
                ei = i

        if si is None:
            return

        start_r = words[si][0]
        end_r   = words[ei][0]
        start_pt = ((start_r.x0 + start_r.x1) / 2, (start_r.y0 + start_r.y1) / 2)
        end_pt   = ((end_r.x0   + end_r.x1)   / 2, (end_r.y0   + end_r.y1)   / 2)

        sel_text = self._update_text_selection(pn, start_pt, end_pt, update_ui=True)
        if sel_text:
            self._show_text_sel_bar(sel_text)

    # ── external search ───────────────────────────────────────────────────────

    def _text_sel_search_google(self, e=None) -> None:
        """Open a Google search for the currently selected text."""
        text = self._text_sel_text
        self._hide_text_sel_bar()
        if text:
            q = urllib.parse.quote_plus(text[:200])
            self.page_ref.launch_url(f"https://www.google.com/search?q={q}")
