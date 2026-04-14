"""Word-level text selection overlay and action popup for PDFViewerTab."""
from __future__ import annotations

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

        si = self._nearest_word_index(words, start_pt)
        ei = self._nearest_word_index(words, end_pt)
        if si > ei:
            si, ei = ei, si

        selected = words[si : ei + 1]

        boxes: list[ft.Control] = []
        sel_rect = None
        for word_rect, word_text in selected:
            t = word_text.strip()
            if not t:
                continue
            boxes.append(ft.Container(
                left   = word_rect.x0 * scale,
                top    = word_rect.y0 * scale,
                width  = max(2.0, word_rect.width  * scale),
                height = max(2.0, word_rect.height * scale),
                bgcolor="#5500AAFF",
            ))
            if sel_rect is None:
                sel_rect = fitz.Rect(word_rect)
            else:
                sel_rect = sel_rect | word_rect

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
        self._text_sel_pn   = None
        self._text_sel_text = ""

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
        pn = self._text_sel_pn
        self._hide_text_sel_bar()
        if pn is not None:
            with self._doc_lock:
                changed = self._annot.apply_text_tool(self.doc, pn, tool)
            if changed:
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
