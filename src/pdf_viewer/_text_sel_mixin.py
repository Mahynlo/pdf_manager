"""Word-level text selection overlay and action popup for PDFViewerTab."""
from __future__ import annotations

import math
import urllib.parse
from collections import defaultdict

import flet as ft
import fitz

from .annotations import Tool, _line_merged_rects
from .renderer import BASE_SCALE


# ── column-aware reading order ────────────────────────────────────────────────

def _sort_words_column_aware(words: list[tuple], page_width: float, pos=None) -> list[tuple]:
    """Sort words in column-aware reading order.

    Detects multi-column layouts by finding significant gaps in the horizontal
    distribution of word x-centres. Groups words dynamically into N columns,
    preventing cross-column "bleeding" during flow selection.

    Falls back to simple row-band sort for single-column pages.

    ``pos`` mapea el rect almacenado (en pantalla) al rect a usar para el ORDEN
    de lectura. En páginas rotadas (/Rotate 90/270) el texto se ve vertical en
    pantalla pero es horizontal en el espacio SIN rotar; pasando ``pos`` =
    des-rotación, el orden de lectura (renglones por Y, columnas por X) vuelve a
    ser correcto. Por defecto (identidad) opera directamente sobre el rect.
    """
    if pos is None:
        pos = lambda r: r
    if len(words) < 4:
        result = list(words)
        result.sort(key=lambda w: (round(pos(w[0]).y0 / 5) * 5, pos(w[0]).x0))
        return result

    # Compute x-centre for every word and sort them
    x_centers = sorted((pos(r).x0 + pos(r).x1) / 2.0 for r, *_ in words)

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
        result.sort(key=lambda w: (round(pos(w[0]).y0 / 5) * 5, pos(w[0]).x0))
    else:
        # Multi-column: find column index, then row-band, then x
        def get_col_index(x):
            for i, split_x in enumerate(splits):
                if x < split_x:
                    return i
            return len(splits)

        result.sort(key=lambda w: (
            get_col_index((pos(w[0]).x0 + pos(w[0]).x1) / 2.0),
            round(pos(w[0]).y0 / 5) * 5,
            pos(w[0]).x0,
        ))

    return result


class _TextSelMixin:
    """Flow-based text selection: word highlights + floating action popup."""

    # ── visual sweep selection ────────────────────────────────────────────────

    def _words_in_sweep(
        self, words: list[tuple], start_pt: tuple, end_pt: tuple,
        pn: int | None = None,
    ) -> list[tuple]:
        """Return words between start_pt and end_pt using the column-aware index.

        Leverages the pre-sorted list of words to perfectly maintain reading
        order and prevent cross-column bleeding.
        """
        if not words:
            return []

        si = self._nearest_word_index(words, start_pt, pn)
        ei = self._nearest_word_index(words, end_pt, pn)

        if si > ei:
            si, ei = ei, si

        return [w for w in words[si : ei + 1] if w[1].strip()]

    # ── marco de lectura (orden de selección en páginas rotadas) ──────────────

    def _reading_frames(self, pn: int) -> tuple[bool, "fitz.Matrix", "fitz.Matrix"]:
        """Devuelve (usa_sin_rotar, des-rotación, rotación) para el ORDEN DE
        LECTURA en una página rotada.

        El marco donde el texto es horizontal depende de la FUENTE:
        - Texto **nativo** (`rawdict`/bloques): horizontal en el espacio SIN
          rotar (mediabox). En una página rotada hay que des-rotar el rect de
          pantalla para ordenar/agrupar, y volver a rotar para dibujar.
        - Detecciones **OCR**: el OCR corre sobre la imagen MOSTRADA (ya
          derecha), así que sus cajas son horizontales en PANTALLA → identidad.
        - Páginas sin rotar: identidad.

        Por eso un escaneo con `/Rotate` que se ve derecho (OCR) y una hoja
        nativa que el usuario rotó 90° necesitan marcos opuestos.
        """
        rot = self.doc[pn].rotation
        if rot and not (
            pn in self._ocr_by_page and self._ocr_by_page[pn].detections
        ):
            p = self.doc[pn]
            return True, p.derotation_matrix, p.rotation_matrix
        return False, fitz.Identity, fitz.Identity

    # ── word cache ────────────────────────────────────────────────────────────

    def _get_page_words(self, pn: int) -> list[tuple]:
        """Return (fitz.Rect, char, word_start) list for every character on page *pn* (cached).

        ``word_start`` marca el primer carácter de cada palabra OCR. Las cajas
        OCR de palabras adyacentes se tocan/solapan (hueco ~0), así que el
        heurístico de espacios por hueco no las separa; con esta marca la
        reconstrucción de texto inserta el espacio entre palabras OCR. El texto
        nativo no la usa (``False``): sus caracteres tienen huecos reales y los
        espacios se infieren por hueco como siempre.
        """
        if pn in self._page_words:
            return self._page_words[pn]

        words: list[tuple] = []
        with self._doc_lock:
            page = self.doc[pn]
            page_width = page.rect.width
            # rawdict/get_text devuelven coords SIN rotar; las detecciones OCR ya
            # vienen en espacio de PANTALLA. Llevamos el texto nativo a pantalla
            # con rotation_matrix (identidad si rotation == 0) para que TODO el
            # subsistema (overlay de selección, hit-test contra clics que ya están
            # en pantalla, orden de lectura) trabaje en un único espacio coherente.
            rot_mat = page.rotation_matrix
            # Extract characters instead of words for finer selection
            raw_dict = page.get_text("rawdict")
            for block in raw_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for char in span.get("chars", []):
                            c = char.get("c", "")
                            if c.strip():  # ignore purely space chars, we reconstruct spaces via gaps
                                words.append((fitz.Rect(char["bbox"]) * rot_mat, c, False))

        if pn in self._ocr_by_page:
            for det in self._ocr_by_page[pn].detections:
                text = det.text.strip()
                if det.bbox and text:
                    rect = fitz.Rect(det.bbox)
                    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                    char_w = (x1 - x0) / max(1, len(text))
                    first = True   # marca el inicio de la palabra OCR
                    for i, char in enumerate(text):
                        if char.strip():
                            char_rect = fitz.Rect(x0 + i * char_w, y0, x0 + (i + 1) * char_w, y1)
                            words.append((char_rect, char, first))
                            first = False

        # Orden de lectura: en páginas rotadas (/Rotate 90/270) el texto se ve
        # vertical en pantalla pero es horizontal SIN rotar. Ordenamos en ese
        # espacio (renglones por Y, columnas por X) des-rotando cada rect; los
        # rects ALMACENADOS siguen en pantalla (overlay, hit-test, dibujo).
        use_unrot, derot_read, _ = self._reading_frames(pn)
        if use_unrot:
            rot = self.doc[pn].rotation
            # ancho de la página en el marco de lectura (sin rotar)
            sort_w = self.doc[pn].rect.height if rot in (90, 270) else page_width
            words = _sort_words_column_aware(
                words, sort_w, pos=lambda r: fitz.Rect(r) * derot_read
            )
        else:
            words = _sort_words_column_aware(words, page_width)
        self._page_words[pn] = words

        # Build y-band spatial index: {band: [(original_idx, rect), ...]}
        bands: dict[int, list[tuple[int, fitz.Rect]]] = {}
        for idx, (r, *_rest) in enumerate(words):
            band = round(r.y0 / 5) * 5
            if band not in bands:
                bands[band] = []
            bands[band].append((idx, r))
        self._page_word_bands[pn] = bands

        return words

    # ── flow-based selection ──────────────────────────────────────────────────

    def _nearest_word_index(
        self, words: list[tuple], pt: tuple[float, float], pn: int | None = None
    ) -> int:
        """Return the index of the word at or nearest to PDF point *pt*.

        Uses the pre-built y-band index (O(k)) when *pn* is provided, falling
        back to a full O(n) scan otherwise.
        """
        if not words:
            return 0
        px, py = pt

        bands = self._page_word_bands.get(pn) if pn is not None else None
        if bands:
            query_band = round(py / 5) * 5
            # ±2 bands = ±10 pt — covers typical text line heights
            candidates: list[tuple[int, fitz.Rect]] = []
            for db in range(-2, 3):
                b = query_band + db * 5
                if b in bands:
                    candidates.extend(bands[b])
            if not candidates:
                # Click is in whitespace; scan all bands (same cost as O(n))
                for band_list in bands.values():
                    candidates.extend(band_list)

            for i, r in candidates:
                if r.x0 <= px <= r.x1 and r.y0 <= py <= r.y1:
                    return i
            best_i, best_d = 0, float("inf")
            for i, r in candidates:
                cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            return best_i

        # O(n) fallback (band index not yet built)
        for i, (r, *_rest) in enumerate(words):
            if r.x0 <= px <= r.x1 and r.y0 <= py <= r.y1:
                return i
        best_i, best_d = 0, float("inf")
        for i, (r, *_rest) in enumerate(words):
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
            if layer is None:  # slot no construido (placeholder)
                continue
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
            
            selected = self._words_in_sweep(words, page_start_pt, page_end_pt, pn=i)
            if not selected:
                layer = self._text_sel_layers[i]
                if layer is not None and (layer.controls or getattr(layer, "visible", False)):
                    layer.controls = []
                    layer.visible = False
                    if update_ui:
                        try: layer.update()
                        except Exception: pass
                continue
                
            has_any_selection = True
            # Agrupar por renglón en el marco donde el texto es horizontal
            # (sin rotar para texto nativo rotado; pantalla para OCR / sin
            # rotar). Cuando el marco de lectura es la pantalla (caso común:
            # rotation==0 u OCR), ``rotated_read`` es False y se evitan TODAS las
            # multiplicaciones de matriz → mismo coste que antes en el camino
            # caliente del arrastre de selección.
            rotated_read, derot_i, rot_i = self._reading_frames(i)
            line_bands: dict = defaultdict(list)
            for word_rect, word_text, *_ws in selected:
                if not word_text.strip():
                    continue
                ur = (fitz.Rect(word_rect) * derot_i) if rotated_read else word_rect
                band = round(ur.y0 / 5) * 5
                line_bands[band].append(ur)

            boxes: list[ft.Control] = []
            sel_rect: fitz.Rect | None = None
            for band in sorted(line_bands):
                urects = line_bands[band]
                ux0 = min(r.x0 for r in urects)
                ux1 = max(r.x1 for r in urects)
                uy0 = min(r.y0 for r in urects)
                uy1 = max(r.y1 for r in urects)
                # un renglón → franja correcta en pantalla
                sr = fitz.Rect(ux0, uy0, ux1, uy1)
                if rotated_read:
                    sr = sr * rot_i
                boxes.append(ft.Container(
                    left   = sr.x0 * scale,
                    top    = sr.y0 * scale,
                    width  = max(2.0, sr.width * scale),
                    height = max(2.0, sr.height * scale),
                    bgcolor="#5500AAFF",
                ))
                sel_rect = sr if sel_rect is None else sel_rect | sr

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

            # La página puede estar fuera de pantalla y sin construir (placeholder):
            # en ese caso no hay capa donde dibujar los recuadros, pero igual
            # acumulamos su texto abajo para que la copia incluya el rango completo.
            layer = self._text_sel_layers[i]
            if layer is not None:
                layer.controls = boxes
                layer.visible  = bool(boxes)
                if update_ui:
                    try: layer.update()
                    except Exception: pass

            last_ur = None
            for r, t, *ws in selected:
                word_start = bool(ws and ws[0])   # primer char de palabra OCR
                t = t.strip()
                if not t: continue
                ur = (fitz.Rect(r) * derot_i) if rotated_read else r  # renglones/espacios en marco de lectura
                if last_ur is not None:
                    if abs(ur.y0 - last_ur.y0) > 5:
                        full_text_parts.append("\n")
                    elif word_start:
                        # frontera de palabra OCR conocida (las cajas se tocan →
                        # el hueco no la delata); insertar espacio explícito.
                        full_text_parts.append(" ")
                    else:
                        char_height = last_ur.y1 - last_ur.y0
                        threshold = max(2.5, char_height * 0.15)
                        if ur.x0 - last_ur.x1 > threshold: full_text_parts.append(" ")
                full_text_parts.append(t)
                last_ur = ur
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
            if layer is None:  # slot no construido (placeholder)
                continue
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
        if pn is None or pn >= len(self._text_sel_popups) or self._text_sel_popups[pn] is None:
            return
        popup    = self._text_sel_popups[pn]
        sel_rect = self._text_sel_sel_rect
        scale    = self.zoom * BASE_SCALE
        if sel_rect is not None:
            _NATURAL_W = 560  # ancho de la barra con TODAS las etiquetas en una fila
            _ROW_H     = 32   # alto de cada fila de la barra
            _MARGIN    = 8

            page_h = float(self._page_heights[pn]) if pn < len(self._page_heights) else 9999.0
            page_w = float(self._page_slots[pn].width or 9999) if pn < len(self._page_slots) else 9999.0

            # La barra vive DENTRO del contenedor de la página; Flutter no entrega
            # clics a nada que sobresalga de ese contenedor. Si la barra completa
            # no cabe a lo ancho (p. ej. a zoom bajo), limitamos su ancho y la Row
            # hace wrap a una 2ª fila en vez de desbordar → los botones siguen
            # respondiendo.
            avail_w = max(120.0, page_w - 2 * _MARGIN)
            width   = min(float(_NATURAL_W), avail_w)
            popup.width = width
            lines   = max(1, math.ceil(_NATURAL_W / width))
            popup_h = 8 + lines * _ROW_H

            # Vertical: debajo de la selección salvo que se salga por abajo.
            below_top = sel_rect.y1 * scale + _MARGIN
            above_top = sel_rect.y0 * scale - popup_h - _MARGIN
            if below_top + popup_h <= page_h - _MARGIN:
                popup.top = below_top
            else:
                popup.top = max(_MARGIN, above_top)

            # Horizontal: alineada con el inicio de la selección, acotada para que
            # la barra quede completamente dentro de la página.
            popup.left = max(_MARGIN, min(sel_rect.x0 * scale, page_w - width - _MARGIN))

        popup.visible = True
        try:
            popup.update()
        except Exception:
            pass

    def _hide_text_sel_bar(self) -> None:
        self._clear_text_selection()
        for popup in self._text_sel_popups:
            if popup is None:  # slot no construido (placeholder)
                continue
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
                selected = self._words_in_sweep(words, page_start_pt, page_end_pt, pn=i)
                rects = [r for r, t, *_ in selected if t.strip()]
                if not rects: continue
                # rects en PANTALLA. La fusión por renglones debe hacerse en el
                # marco donde el texto es HORIZONTAL (pantalla para OCR, sin rotar
                # para nativo) o agruparía mal → bandas. Y hay que pasar QUADS
                # (no rects) al markup: des-rotar un rect pierde la orientación y
                # el subrayado/tachado caería en el borde equivocado; un quad
                # conserva las 4 esquinas, así el subrayado queda DEBAJO del texto.
                page = self.doc[i]
                use_unrot, derot_read, _ = self._reading_frames(i)
                read_rects = [fitz.Rect(r) * derot_read for r in rects]
                merged = _line_merged_rects(read_rects)   # franjas en marco de lectura
                # marco de lectura → espacio SIN rotar de la página (para add_*_annot)
                read_to_page = fitz.Identity if use_unrot else page.derotation_matrix
                quads = [m.quad * read_to_page for m in merged]
                if self._annot.apply_text_tool(
                    self.doc, i, tool, rects=quads, rects_are_final=True
                ):
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
        idx = self._nearest_word_index(words, pdf_pt, pn)

        # «Misma línea / hueco» se evalúa en el marco donde el texto es
        # horizontal (sin rotar para nativo rotado; pantalla para OCR).
        # Sin transformaciones cuando el marco ya es la pantalla (caso común).
        rotated_read, derot, _ = self._reading_frames(pn)
        def _u(j):
            r = words[j][0]
            return (fitz.Rect(r) * derot) if rotated_read else r

        # Expand left to find the start of the word
        si = idx
        while si > 0:
            curr_r = _u(si)
            prev_r = _u(si - 1)
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
            curr_r = _u(ei)
            next_r = _u(ei + 1)
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
        if pn in self._page_blocks_cache:
            blocks = self._page_blocks_cache[pn]
        else:
            with self._doc_lock:
                page = self.doc[pn]
                raw_blocks = page.get_text("blocks")
                rot_mat = page.rotation_matrix
            # Almacenar los bloques en espacio de PANTALLA (igual que las palabras
            # y el punto de clic) para que el hit-test funcione en páginas rotadas.
            # rotation_matrix es identidad si rotation == 0.
            blocks = []
            for b in raw_blocks:
                r = fitz.Rect(b[0], b[1], b[2], b[3]) * rot_mat
                blocks.append((r.x0, r.y0, r.x1, r.y1, *b[4:]))
            self._page_blocks_cache[pn] = blocks

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
        for i, (r, *_rest) in enumerate(words):
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
