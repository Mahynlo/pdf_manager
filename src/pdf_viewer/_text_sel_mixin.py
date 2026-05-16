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
    distribution of word x-centres. Groups words dynamically into N columns,
    preventing cross-column "bleeding" during flow selection.

    Falls back to simple row-band sort for single-column pages.
    """
    if len(words) < 4:
        result = list(words)
        result.sort(key=lambda w: (round(w[0].y0 / 5) * 5, w[0].x0))
        return result

    # Compute x-centre for every word and sort them
    x_centers = sorted((r.x0 + r.x1) / 2.0 for r, _ in words)

    # Find gaps larger than the threshold to support N columns
    threshold = max(30.0, page_width * 0.08)  # ~48 pt for A4
    splits = []
    for i in range(len(x_centers) - 1):
        gap = x_centers[i + 1] - x_centers[i]
        if gap > threshold:
            splits.append((x_centers[i] + x_centers[i + 1]) / 2.0)

    result = list(words)
    if not splits:
        # Single column: row-band sort
        result.sort(key=lambda w: (round(w[0].y0 / 5) * 5, w[0].x0))
    else:
        # Multi-column: find column index, then row-band, then x
        def get_col_index(x):
            for i, split_x in enumerate(splits):
                if x < split_x:
                    return i
            return len(splits)

        result.sort(key=lambda w: (
            get_col_index((w[0].x0 + w[0].x1) / 2.0),
            round(w[0].y0 / 5) * 5,
            w[0].x0,
        ))

    return result


class _TextSelMixin:
    """Flow-based text selection: word highlights + floating action popup."""

    # ── visual sweep selection ────────────────────────────────────────────────

    def _words_in_sweep(
        self, words: list[tuple], start_pt: tuple, end_pt: tuple
    ) -> list[tuple]:
        """Return words between start_pt and end_pt using the column-aware index.
        
        Leverages the pre-sorted list of words to perfectly maintain reading
        order and prevent cross-column bleeding.
        """
        if not words:
            return []
            
        si = self._nearest_word_index(words, start_pt)
        ei = self._nearest_word_index(words, end_pt)
        
        if si > ei:
            si, ei = ei, si
            
        return [(r, t) for r, t in words[si : ei + 1] if t.strip()]

    # ── word cache ────────────────────────────────────────────────────────────

    def _get_page_words(self, pn: int) -> list[tuple]:
        """Return (fitz.Rect, str) list for every character/word on page *pn* (cached)."""
        if pn in self._page_words:
            return self._page_words[pn]
            
        words: list[tuple] = []
        with self._doc_lock:
            page_width = self.doc[pn].rect.width
            # Extract characters instead of words for finer selection
            raw_dict = self.doc[pn].get_text("rawdict")
            for block in raw_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for char in span.get("chars", []):
                            c = char.get("c", "")
                            if c.strip():  # ignore purely space chars, we reconstruct spaces via gaps
                                words.append((fitz.Rect(char["bbox"]), c))

        if pn in self._ocr_by_page:
            for det in self._ocr_by_page[pn].detections:
                text = det.text.strip()
                if det.bbox and text:
                    rect = fitz.Rect(det.bbox)
                    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                    char_w = (x1 - x0) / max(1, len(text))
                    for i, char in enumerate(text):
                        if char.strip():
                            char_rect = fitz.Rect(x0 + i * char_w, y0, x0 + (i + 1) * char_w, y1)
                            words.append((char_rect, char))
                    
        # Column-aware reading order
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
        start_pn: int,
        start_pt: tuple | None,
        end_pn: int,
        end_pt: tuple | None,
        *,
        update_ui: bool = False,
    ) -> str:
        """
        Highlight words between *start_pt* and *end_pt* across multiple pages.
        Returns the selected text string.
        """
        if start_pn is None or end_pn is None or start_pt is None or end_pt is None:
            return ""

        spn, epn = start_pn, end_pn
        spt, ept = start_pt, end_pt
        if spn > epn or (spn == epn and spt[1] > ept[1]):
            spn, epn = epn, spn
            spt, ept = ept, spt

        scale = self.zoom * BASE_SCALE
        
        for i, layer in enumerate(self._text_sel_layers):
            if i < spn or i > epn:
                if layer.controls or getattr(layer, "visible", False):
                    layer.controls = []
                    layer.visible = False
                    if update_ui:
                        try: layer.update()
                        except Exception: pass

        full_text_parts = []
        self._text_sel_sel_rect = None
        has_any_selection = False
        
        for i in range(spn, epn + 1):
            if i >= len(self._text_sel_layers):
                continue
            words = self._get_page_words(i)
            if not words:
                continue

            page_start_pt = spt if i == spn else (0, -9999)
            page_end_pt   = ept if i == epn else (9999, 9999)
            
            selected = self._words_in_sweep(words, page_start_pt, page_end_pt)
            if not selected:
                layer = self._text_sel_layers[i]
                if layer.controls or getattr(layer, "visible", False):
                    layer.controls = []
                    layer.visible = False
                    if update_ui:
                        try: layer.update()
                        except Exception: pass
                continue
                
            has_any_selection = True
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

            if i == epn:
                self._text_sel_sel_rect = sel_rect

            _H_R = 7
            if i == spn and selected:
                first_r = selected[0][0]
                s_disp  = (first_r.x0 * scale, first_r.y1 * scale)
                self._text_sel_handle_start_disp = s_disp
                _h = dict(width=_H_R * 2, height=_H_R * 2, border_radius=_H_R, bgcolor="#0088FF", border=ft.border.all(2, "#FFFFFF"), shadow=ft.BoxShadow(blur_radius=4, color="#44000000"))
                boxes.append(ft.Container(left=s_disp[0] - _H_R, top=s_disp[1] - _H_R, **_h))
                
            if i == epn and selected:
                last_r  = selected[-1][0]
                e_disp  = (last_r.x1  * scale, last_r.y1  * scale)
                self._text_sel_handle_end_disp   = e_disp
                _h = dict(width=_H_R * 2, height=_H_R * 2, border_radius=_H_R, bgcolor="#0088FF", border=ft.border.all(2, "#FFFFFF"), shadow=ft.BoxShadow(blur_radius=4, color="#44000000"))
                boxes.append(ft.Container(left=e_disp[0] - _H_R, top=e_disp[1] - _H_R, **_h))

            layer = self._text_sel_layers[i]
            layer.controls = boxes
            layer.visible  = bool(boxes)
            if update_ui:
                try: layer.update()
                except Exception: pass

            last_r = None
            for r, t in selected:
                t = t.strip()
                if not t: continue
                if last_r is not None:
                    if abs(r.y0 - last_r.y0) > 5: full_text_parts.append("\n")
                    else:
                        char_height = last_r.y1 - last_r.y0
                        threshold = max(2.5, char_height * 0.15)
                        if r.x0 - last_r.x1 > threshold: full_text_parts.append(" ")
                full_text_parts.append(t)
                last_r = r
            if i != epn:
                full_text_parts.append("\n")

        if has_any_selection:
            self._text_sel_start_pn = start_pn
            self._text_sel_end_pn   = end_pn
        else:
            self._text_sel_start_pn = None
            self._text_sel_end_pn   = None

        return "".join(full_text_parts)

    def _clear_text_selection(self) -> None:
        for layer in self._text_sel_layers:
            if layer.controls or getattr(layer, 'visible', False):
                layer.controls = []
                layer.visible  = False
                try:
                    layer.update()
                except Exception:
                    pass
        self._text_sel_start_pn          = None
        self._text_sel_end_pn            = None
        self._text_sel_text              = ""
        self._text_sel_handle_start_disp = None
        self._text_sel_handle_end_disp   = None

    # ── floating popup ────────────────────────────────────────────────────────

    def _show_text_sel_bar(self, text: str) -> None:
        self._text_sel_text = text
        pn = getattr(self, "_text_sel_end_pn", None)
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
        start_pn = getattr(self, "_text_sel_start_pn", None)
        end_pn   = getattr(self, "_text_sel_end_pn", None)
        start_pt = self._text_sel_start_pdf
        end_pt   = self._text_sel_end_pdf
        self._hide_text_sel_bar()
        if start_pn is None or end_pn is None or start_pt is None or end_pt is None:
            return
            
        spn, epn = start_pn, end_pn
        spt, ept = start_pt, end_pt
        if spn > epn or (spn == epn and spt[1] > ept[1]):
            spn, epn = epn, spn
            spt, ept = ept, spt

        with self._doc_lock:
            for i in range(spn, epn + 1):
                words = self._get_page_words(i)
                if not words: continue
                page_start_pt = spt if i == spn else (0, -9999)
                page_end_pt   = ept if i == epn else (9999, 9999)
                selected = self._words_in_sweep(words, page_start_pt, page_end_pt)
                rects = [r for r, t in selected if t.strip()]
                if not rects: continue
                if self._annot.apply_text_tool(self.doc, i, tool, rects=rects):
                    self._refresh_page(i)

    def _text_sel_send_to_redact(self, e=None) -> None:
        """Send the current text selection to the redaction panel as a candidate.

        The region is added directly to _redact_term_matches so the user can
        review it in the censorship panel and decide whether to apply it.
        """
        start_pn = getattr(self, "_text_sel_start_pn", None)
        end_pn   = getattr(self, "_text_sel_end_pn", None)
        sel_rect = self._text_sel_sel_rect
        text     = self._text_sel_text
        self._hide_text_sel_bar()
        if start_pn is None or end_pn is None or sel_rect is None or not text:
            return

        spn = min(start_pn, end_pn)
        epn = max(start_pn, end_pn)

        # Build a display key — prefix distinguishes manual from keyword entries.
        label    = text.strip()[:60]
        term_key = f"[manual] {label}"

        # If this exact key is already in the list, append page info to deduplicate.
        existing = getattr(self, "_redact_terms", [])
        if term_key in existing:
            term_key = f"[manual] {label} (p.{spn + 1}-{epn + 1})" if spn != epn else f"[manual] {label} (p.{spn + 1})"

        # Inject directly into the redaction data structures.
        if not hasattr(self, "_redact_terms"):
            return
        self._redact_terms.append(term_key)
        matches = getattr(self, "_redact_term_matches", {})
        matches[term_key] = [(spn, fitz.Rect(sel_rect), label)]
        self._redact_term_matches = matches
        self._redact_matches = self._flatten_matches()

        # Rebuild redact panel UI
        self._rebuild_redact_terms_list()
        # Always enable preview so the zone is immediately visible in the viewer
        if not getattr(self, "_redact_preview", False):
            self._redact_preview = True
            if self._redact_preview_btn is not None:
                from ._viewer_defs import _SELECTED_BG
                self._redact_preview_btn.bgcolor    = _SELECTED_BG
                self._redact_preview_btn.icon_color = getattr(self, "_redact_box_color", "#E65100")
                try:
                    self._redact_preview_btn.update()
                except Exception:
                    pass
        self._render_redact_preview(force_update=True)

        # Switch sidebar to censorship tab and ensure it is visible
        if hasattr(self, "_switch_sidebar_mode"):
            self._switch_sidebar_mode("redact")
        if not getattr(self, "_sidebar_visible", True):
            self._toggle_sidebar()
        if self._right_sidebar is not None:
            try:
                self._right_sidebar.update()
            except Exception:
                pass

        short = label[:40] + ("…" if len(label) > 40 else "")
        self._show_snack(f'Enviado a censura: "{short}"')

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
        """Select the full word at (or nearest to) pdf_pt (double-tap)."""
        words = self._get_page_words(pn)
        if not words:
            return
        idx = self._nearest_word_index(words, pdf_pt)
        
        # Expand left to find the start of the word
        si = idx
        while si > 0:
            curr_r = words[si][0]
            prev_r = words[si - 1][0]
            # Same line and small gap (no space)
            char_height = prev_r.y1 - prev_r.y0
            threshold = max(2.5, char_height * 0.15)
            if abs(curr_r.y0 - prev_r.y0) <= 5 and (curr_r.x0 - prev_r.x1) <= threshold:
                si -= 1
            else:
                break
                
        # Expand right to find the end of the word
        ei = idx
        while ei < len(words) - 1:
            curr_r = words[ei][0]
            next_r = words[ei + 1][0]
            # Same line and small gap (no space)
            char_height = curr_r.y1 - curr_r.y0
            threshold = max(2.5, char_height * 0.15)
            if abs(curr_r.y0 - next_r.y0) <= 5 and (next_r.x0 - curr_r.x1) <= threshold:
                ei += 1
            else:
                break

        start_r = words[si][0]
        end_r   = words[ei][0]
        
        start_pt = (start_r.x0, (start_r.y0 + start_r.y1) / 2)
        end_pt   = (end_r.x1,   (end_r.y0   + end_r.y1)   / 2)
        
        self._text_sel_start_pdf = start_pt
        self._text_sel_end_pdf   = end_pt
        sel_text = self._update_text_selection(pn, start_pt, pn, end_pt, update_ui=True)
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

        sel_text = self._update_text_selection(pn, start_pt, pn, end_pt, update_ui=True)
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
