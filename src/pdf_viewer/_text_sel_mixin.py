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

    # Precompute the reading-frame rect once per word. En páginas rotadas ``pos``
    # es una multiplicación de matriz; el key del sort la invocaba 2-3 veces por
    # palabra. Materializarla una sola vez elimina ese trabajo redundante (y en el
    # caso común sin rotar ``pos`` es identidad → casi gratis). Ordenamos índices
    # —el sort de Python es estable— y reproyectamos al final.
    prects = [pos(w[0]) for w in words]

    if len(words) < 4:
        order = sorted(
            range(len(words)),
            key=lambda i: (round(prects[i].y0 / 5) * 5, prects[i].x0),
        )
        return [words[i] for i in order]

    # Compute x-centre for every word and sort them
    x_centers = sorted((r.x0 + r.x1) / 2.0 for r in prects)

    # Find gaps larger than the threshold to support N columns
    threshold = max(30.0, page_width * 0.08)  # ~48 pt for A4
    splits = []
    for i in range(len(x_centers) - 1):
        gap = x_centers[i + 1] - x_centers[i]
        if gap > threshold:
            splits.append((x_centers[i] + x_centers[i + 1]) / 2.0)

    if not splits:
        # Single column: row-band sort
        order = sorted(
            range(len(words)),
            key=lambda i: (round(prects[i].y0 / 5) * 5, prects[i].x0),
        )
    else:
        # Multi-column: find column index, then row-band, then x
        def get_col_index(x):
            for k, split_x in enumerate(splits):
                if x < split_x:
                    return k
            return len(splits)

        order = sorted(
            range(len(words)),
            key=lambda i: (
                get_col_index((prects[i].x0 + prects[i].x1) / 2.0),
                round(prects[i].y0 / 5) * 5,
                prects[i].x0,
            ),
        )

    return [words[i] for i in order]


# ── line clustering (robustez para OCR: jitter de baseline y leve sesgo) ───────

def _line_tol(rects: list) -> float:
    """Tolerancia vertical adaptativa para agrupar rects en renglones.

    Basada en la altura MEDIANA de caja → escala con el tamaño de fuente / del
    escaneo. El texto nativo da ~5 pt (igual que el umbral fijo de antes); el
    OCR, cuyas cajas son por palabra (alto = renglón) y con ``y0`` ruidoso, da
    una tolerancia mayor que absorbe el jitter sin fundir renglones vecinos.
    """
    if not rects:
        return 5.0
    heights = sorted(max(0.0, r.y1 - r.y0) for r in rects)
    med = heights[len(heights) // 2]
    return max(3.0, med * 0.6)


def _assign_line_indices(words: list[tuple], pos=None) -> list[tuple]:
    """Anexa un índice de renglón (4º elem) a palabras YA en orden de lectura.

    Recorre la lista (ya ordenada) y abre un renglón nuevo cuando el centro
    vertical salta más que la tolerancia respecto a la MEDIA MÓVIL del renglón
    (no la palabra previa): así una caja con jitter no arrastra el ancla al
    renglón siguiente y los vecinos no se fusionan. No reordena.
    """
    if pos is None:
        pos = lambda r: r
    if not words:
        return []
    prects = [pos(w[0]) for w in words]
    tol = _line_tol(prects)
    out: list[tuple] = []
    mean: float | None = None      # media móvil del centro vertical del renglón
    cnt = 0
    lid = -1
    for w, pr in zip(words, prects):
        cy = (pr.y0 + pr.y1) / 2
        if mean is None or abs(cy - mean) > tol:
            lid += 1
            mean = cy
            cnt = 1
        else:
            cnt += 1
            mean += (cy - mean) / cnt
        out.append((*w[:3], lid))
    return out


def _sort_words_clustered(words: list[tuple], page_width: float, pos=None) -> list[tuple]:
    """Orden de lectura por CLUSTERING de renglones, robusto para OCR.

    En vez de bandear por ``round(y0/5)*5`` (frágil: dos palabras de un mismo
    renglón con ``y0`` a 3 pt caen en bandas distintas y, en un escaneo con leve
    inclinación, el renglón se invierte), agrupa por centro vertical con
    tolerancia adaptativa siguiendo la baseline. Devuelve tuplas de longitud 4
    ``(rect, char, word_start, line_idx)``.
    """
    if pos is None:
        pos = lambda r: r
    n = len(words)
    if n == 0:
        return []
    prects = [pos(w[0]) for w in words]
    cy = [(r.y0 + r.y1) / 2 for r in prects]
    cx = [(r.x0 + r.x1) / 2 for r in prects]
    tol = _line_tol(prects)

    # Detección de columnas (mismo heurístico de huecos que el sorter por bandas).
    xs = sorted(cx)
    threshold = max(30.0, page_width * 0.08)
    splits = []
    for i in range(len(xs) - 1):
        if xs[i + 1] - xs[i] > threshold:
            splits.append((xs[i] + xs[i + 1]) / 2.0)

    def col_of(x: float) -> int:
        for k, sx in enumerate(splits):
            if x < sx:
                return k
        return len(splits)

    cols = [col_of(x) for x in cx]

    # Dentro de cada columna, recorrer de arriba a abajo y agrupar renglones.
    # El ancla del renglón es su MEDIA MÓVIL de centro vertical (no la palabra
    # previa): una sola caja con jitter no arrastra el ancla hasta el renglón
    # siguiente, así que renglones vecinos NO se fusionan (era la causa del
    # "bloque": al fundirse, el resaltado dibujaba un único rectángulo enorme).
    order0 = sorted(range(n), key=lambda i: (cols[i], cy[i], prects[i].x0))
    line_id = [0] * n
    cur_col: int | None = None
    mean: float | None = None
    cnt = 0
    lid = -1
    for i in order0:
        if cols[i] != cur_col or mean is None or abs(cy[i] - mean) > tol:
            lid += 1
            cur_col = cols[i]
            mean = cy[i]
            cnt = 1
        else:
            cnt += 1
            mean += (cy[i] - mean) / cnt   # media móvil del renglón
        line_id[i] = lid

    order = sorted(range(n), key=lambda i: (line_id[i], prects[i].x0))
    return [(*words[i][:3], line_id[i]) for i in order]


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

    def _is_ocr_page(self, pn: int) -> bool:
        """True si la página tiene detecciones OCR (cajas por palabra, no nativas)."""
        return pn in self._ocr_by_page and bool(self._ocr_by_page[pn].detections)

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

        # Extracción nativa (MuPDF) bajo el lock; el armado de la lista de chars
        # —Python puro sobre el dict YA extraído— corre FUERA del lock. El bucle
        # no toca self.doc, y mantenerlo bajo el lock serializaba con los workers
        # de render, que necesitan el mismo _doc_lock para rasterizar: seleccionar
        # texto en una página densa bloqueaba el render de las páginas vecinas.
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

        words: list[tuple] = []
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
        #
        # Cada palabra queda como tupla de longitud 4 ``(rect, char, word_start,
        # line_idx)``: el índice de renglón lo consumen el resaltado, la
        # reconstrucción de texto y la selección por palabra/párrafo para
        # comportarse como en texto nativo (sin saltos de línea falsos ni
        # resaltados partidos) aun cuando las cajas OCR tienen ``y0`` ruidoso.
        use_unrot, derot_read, _ = self._reading_frames(pn)
        if use_unrot:
            rot = self.doc[pn].rotation
            # ancho de la página en el marco de lectura (sin rotar)
            sort_w = self.doc[pn].rect.height if rot in (90, 270) else page_width
            pos = lambda r: fitz.Rect(r) * derot_read
            words = _sort_words_column_aware(words, sort_w, pos=pos)
            words = _assign_line_indices(words, pos=pos)
        elif self._is_ocr_page(pn):
            # OCR: orden por clustering de renglones (robusto a jitter/sesgo).
            # Las cajas OCR ya están en espacio de PANTALLA → pos identidad.
            words = _sort_words_clustered(words, page_width)
        else:
            words = _sort_words_column_aware(words, page_width)
            words = _assign_line_indices(words)
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
            for word_rect, word_text, *rest in selected:
                if not word_text.strip():
                    continue
                ur = (fitz.Rect(word_rect) * derot_i) if rotated_read else word_rect
                # Agrupar por índice de renglón precomputado (consistente con el
                # orden de lectura); fallback a banda por y0 si faltara.
                key = rest[1] if len(rest) >= 2 else round(ur.y0 / 5) * 5
                line_bands[key].append(ur)

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
            last_li = None
            for r, t, *ws in selected:
                word_start = bool(ws and ws[0])   # primer char de palabra OCR
                li = ws[1] if len(ws) >= 2 else None   # índice de renglón
                t = t.strip()
                if not t: continue
                ur = (fitz.Rect(r) * derot_i) if rotated_read else r  # renglones/espacios en marco de lectura
                if last_ur is not None:
                    if li is not None and last_li is not None:
                        new_line = li != last_li      # salto por renglón (robusto)
                    else:
                        new_line = abs(ur.y0 - last_ur.y0) > 5   # fallback
                    if new_line:
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
                last_li = li
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

        def _li(j):
            return words[j][3] if len(words[j]) > 3 else None

        def _word_start(j):
            return bool(words[j][2]) if len(words[j]) > 2 else False

        def _same_word(a: int, b: int) -> bool:
            """Mismo renglón y hueco horizontal pequeño → misma palabra.

            En OCR las cajas de palabras vecinas se tocan (hueco ~0); ``word_start``
            marca la frontera. En texto nativo ``word_start`` es siempre False y
            manda el hueco, como antes.
            """
            la, lb = _li(a), _li(b)
            ra, rb = _u(a), _u(b)
            if la is not None and lb is not None:
                if la != lb:
                    return False
            elif abs(ra.y0 - rb.y0) > 5:
                return False
            gap = max(ra.x0, rb.x0) - min(ra.x1, rb.x1)
            char_height = max(ra.y1 - ra.y0, rb.y1 - rb.y0)
            threshold = max(2.5, char_height * 0.15)
            return gap <= threshold

        # Expand left to find the start of the word
        si = idx
        while si > 0:
            if _word_start(si):           # 'si' inicia su palabra OCR → frenar
                break
            if not _same_word(si, si - 1):
                break
            si -= 1

        # Expand right to find the end of the word
        ei = idx
        while ei < len(words) - 1:
            if _word_start(ei + 1):       # el siguiente char inicia otra palabra
                break
            if not _same_word(ei, ei + 1):
                break
            ei += 1

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

        # OCR: no hay bloques nativos → sintetizar el párrafo agrupando renglones
        # contiguos (separación vertical regular) alrededor del clic, usando los
        # índices de renglón precomputados. Replica el triple-tap nativo.
        if target_rect is None and self._is_ocr_page(pn):
            self._select_ocr_paragraph_at(pn, pdf_pt)
            return

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

    def _select_ocr_paragraph_at(self, pn: int, pdf_pt: tuple) -> None:
        """Triple-tap en páginas OCR: selecciona el párrafo (renglones contiguos).

        Sin bloques de layout, aproxima el párrafo expandiendo desde el renglón
        del clic hacia arriba/abajo mientras la separación entre renglones
        consecutivos sea regular; corta en huecos grandes (cambio de párrafo) y
        nunca cruza de columna (el salto de columna da un hueco muy negativo).
        """
        words = self._get_page_words(pn)
        if not words:
            return
        idx = self._nearest_word_index(words, pdf_pt, pn)
        click_li = words[idx][3] if len(words[idx]) > 3 else None
        if click_li is None:
            return

        # Extensión vertical (y0/y1) por renglón.
        line_y0: dict[int, float] = {}
        line_y1: dict[int, float] = {}
        for w in words:
            li = w[3] if len(w) > 3 else None
            if li is None:
                continue
            r = w[0]
            line_y0[li] = min(line_y0.get(li, r.y0), r.y0)
            line_y1[li] = max(line_y1.get(li, r.y1), r.y1)

        order = sorted(line_y0)
        if click_li not in line_y0:
            return
        heights = sorted(line_y1[k] - line_y0[k] for k in line_y0)
        med_h = heights[len(heights) // 2] if heights else 10.0
        gap_max = med_h * 1.6        # hueco mayor → frontera de párrafo
        gap_min = -med_h * 0.5       # leve solape (descendentes) permitido

        pos = order.index(click_li)
        p = pos
        while p > 0:                 # expandir hacia arriba
            a, b = order[p], order[p - 1]
            if gap_min <= line_y0[a] - line_y1[b] <= gap_max:
                p -= 1
            else:
                break
        lo = order[p]
        p = pos
        while p < len(order) - 1:    # expandir hacia abajo
            a, b = order[p], order[p + 1]
            if gap_min <= line_y0[b] - line_y1[a] <= gap_max:
                p += 1
            else:
                break
        hi = order[p]

        sel_idx = [j for j, w in enumerate(words) if len(w) > 3 and lo <= w[3] <= hi]
        if not sel_idx:
            return
        si, ei = min(sel_idx), max(sel_idx)
        start_r, end_r = words[si][0], words[ei][0]
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
