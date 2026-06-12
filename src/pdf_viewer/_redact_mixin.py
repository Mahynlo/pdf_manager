"""Redaction search/apply workflow for PDFViewerTab."""
from __future__ import annotations

import re
import string

import flet as ft
import fitz

from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG


# Plegado de acentos para la búsqueda de censura: es habitual escribir los
# términos sin tilde, así que "COMITÉ" debe coincidir con "COMITE" y "Pública"
# con "Publica" — para la búsqueda son la misma palabra (solo cambia el acento).
# La ñ/Ñ se PRESERVA a propósito: es una letra propia del español, no una "n con
# tilde" ("año" ≠ "ano"). La tabla es 1:1 (no cambia la longitud), lo que importa
# para mapear posiciones de caracteres en la búsqueda OCR.
_ACCENT_FOLD = str.maketrans(
    "áàäâãéèëêíìïîóòöôõúùüûÁÀÄÂÃÉÈËÊÍÌÏÎÓÒÖÔÕÚÙÜÛ",
    "aaaaaeeeeiiiiooooouuuuAAAAAEEEEIIIIOOOOOUUUU",
)


def _fold_accents(s: str) -> str:
    """Pliega tildes/diéresis a la vocal base, conservando la ñ."""
    return s.translate(_ACCENT_FOLD)


class _RedactMixin:
    """Text redaction: term management, search, preview and apply."""

    _REDACT_HDR  = "#E65100"
    _SECTION_CLR = "#795548"

    # Tope de coincidencias por término. Buscar una palabra muy común ("de",
    # "la"…) con matching de subcadena produce decenas de miles de coincidencias
    # → congela el hilo de UI al acumularlas/dibujarlas. Al alcanzar el tope se
    # corta la búsqueda y se avisa al usuario que refine el término. No es un
    # límite de uso real: censurar miles de zonas no es revisable a mano.
    _REDACT_MAX_MATCHES = 1000

    # ── sidebar panel builder ─────────────────────────────────────────────────

    def _build_redact_sidebar_panel(self) -> ft.Container:
        """Build the Redaction collapsible panel and initialise its controls."""
        _REDACT_BG   = ft.Colors.with_opacity(0.06, "#E65100")
        _REDACT_HDR  = "#E65100"
        _REDACT_MID  = "#BF360C"
        _SECTION_CLR = "#795548"

        def _section_label(text: str, icon: str) -> ft.Row:
            return ft.Row(
                [
                    ft.Icon(icon, size=13, color=_SECTION_CLR),
                    ft.Text(text, size=11, weight=ft.FontWeight.W_600,
                            color=_SECTION_CLR),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        # ── perfil activo ─────────────────────────────────────────────────────
        self._active_profile_label = ft.Text(
            "Sin perfil", size=11, color=_SECTION_CLR,
            italic=True, expand=True,
            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
        )
        profile_banner = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_OUTLINED, size=14, color=_SECTION_CLR),
                    self._active_profile_label,
                    ft.IconButton(
                        ft.Icons.TUNE, icon_size=15,
                        tooltip="Gestionar perfiles de censura",
                        icon_color=_REDACT_HDR,
                        on_click=self._open_profile_manager,
                        style=ft.ButtonStyle(padding=ft.padding.all(3)),
                    ),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.18, "#E65100"),
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
        )

        # ── input + options ───────────────────────────────────────────────────
        self._redact_query_field = ft.TextField(
            hint_text="Escribe una frase y pulsa Enter para agregar…",
            dense=True, expand=True,
            on_submit=self._add_redact_term,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_color="outlineVariant",
            focused_border_color=_REDACT_HDR,
        )
        self._redact_case_btn = ft.IconButton(
            ft.Icons.FONT_DOWNLOAD_OUTLINED, icon_size=18,
            tooltip="Distinguir mayúsculas (activo = sí)",
            icon_color=_REDACT_HDR, bgcolor=ft.Colors.with_opacity(0.15, "#E65100"),
            on_click=self._toggle_case_sensitive,
            style=ft.ButtonStyle(padding=ft.padding.all(4)),
        )
        self._redact_incl_ocr = ft.Switch(
            value=True,
            label="Buscar en OCR",
            label_style=ft.TextStyle(size=11, color=_SECTION_CLR),
            active_color=_REDACT_HDR,
        )

        # ── terms list ────────────────────────────────────────────────────────
        self._redact_count_text = ft.Text(
            "", size=11, color=_SECTION_CLR, italic=True,
        )
        self._redact_terms_list = ft.ListView(
            spacing=4,
            padding=ft.padding.only(bottom=4),
            expand=True,
        )

        # ── guardar en perfil ─────────────────────────────────────────────────
        self._profile_save_btn = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.SAVE_OUTLINED, size=14, color=_REDACT_HDR),
                    ft.Text(
                        "Guardar en perfil", size=11,
                        color=_REDACT_HDR, weight=ft.FontWeight.W_500,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=self._save_current_as_profile,
            ink=True,
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border=ft.border.all(1, "outlineVariant"),
            visible=False,
        )

        # ── color selector ────────────────────────────────────────────────────
        _PALETTE = [
            ("#000000", "Negro"),
            ("#B71C1C", "Rojo oscuro"),
            ("#0D47A1", "Azul oscuro"),
            ("#1B5E20", "Verde oscuro"),
        ]
        self._redact_color_btns = {}
        color_ctrls: list[ft.Control] = []
        for hex_c, name in _PALETTE:
            is_sel = hex_c == self._redact_box_color
            btn = ft.Container(
                width=22, height=22,
                bgcolor=hex_c,
                border_radius=11,
                border=ft.border.all(3, _REDACT_HDR if is_sel else "outlineVariant"),
                tooltip=name,
                on_click=lambda e, c=hex_c: self._select_redact_color(c),
                ink=True,
            )
            self._redact_color_btns[hex_c] = btn
            color_ctrls.append(btn)

        # ── preview button ────────────────────────────────────────────────────
        self._redact_preview_btn = ft.IconButton(
            ft.Icons.PREVIEW_OUTLINED, icon_size=18,
            tooltip="Mostrar/ocultar zonas marcadas en el documento",
            on_click=self._toggle_redact_preview,
            bgcolor=_SELECTED_BG if getattr(self, "_redact_preview", True) else None,
            icon_color=getattr(self, "_redact_box_color", "#000000")
                       if getattr(self, "_redact_preview", True) else None,
        )

        # ── ZONA 1 · cabecera compacta (perfil + entrada) ────────────────────
        _top_zone = ft.Column(
            [
                profile_banner,
                _section_label("Agregar texto a censurar", ft.Icons.ADD_CIRCLE_OUTLINE),
                ft.Row(
                    [self._redact_query_field, self._redact_case_btn],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._redact_incl_ocr,
            ],
            spacing=8,
            tight=True,
        )

        # ── ZONA 2 · lista flexible (crece para llenar el espacio) ────────────
        _list_header = ft.Row(
            [
                _section_label("Lista de censuras", ft.Icons.LIST_ALT_OUTLINED),
                ft.Container(expand=True),
                self._redact_count_text,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── ZONA 3 · barra de acción anclada abajo ────────────────────────────
        _action_bar = ft.Container(
            ft.Column(
                [
                    self._profile_save_btn,
                    ft.Row(
                        [
                            _section_label("Color", ft.Icons.PALETTE_OUTLINED),
                            ft.Container(expand=True),
                            *color_ctrls,
                            ft.Container(width=4),
                            self._redact_preview_btn,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.ElevatedButton(
                        "Aplicar censura al documento", icon=ft.Icons.EDIT_OFF,
                        color="#FFFFFF", bgcolor=_REDACT_MID,
                        on_click=self._apply_redaction, expand=True,
                        style=ft.ButtonStyle(
                            padding=ft.padding.symmetric(vertical=12)
                        ),
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            padding=ft.padding.only(top=8),
            border=ft.border.only(top=ft.BorderSide(1, "outlineVariant")),
        )

        self._redact_content_area = ft.Container(
            ft.Column(
                [
                    _top_zone,
                    ft.Divider(height=1, color="outlineVariant"),
                    _list_header,
                    self._redact_terms_list,
                    _action_bar,
                ],
                spacing=8, expand=True,
            ),
            expand=True,
            padding=ft.padding.only(top=4),
        )
        self._redact_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.EDIT_OFF, size=18, color=_REDACT_HDR),
                            ft.Text("Censura", size=14, weight=ft.FontWeight.W_600,
                                    color=_REDACT_HDR),
                        ],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_content_area,
                ],
                spacing=4, expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=_REDACT_BG,
            expand=True,
        )
        return self._redact_panel

    def _toggle_case_sensitive(self, e=None) -> None:
        self._redact_case_sensitive = not self._redact_case_sensitive
        if self._redact_case_btn is not None:
            if self._redact_case_sensitive:
                self._redact_case_btn.icon        = ft.Icons.FONT_DOWNLOAD_OUTLINED
                self._redact_case_btn.bgcolor     = ft.Colors.with_opacity(0.15, "#E65100")
                self._redact_case_btn.tooltip     = "Distinguir mayúsculas (activo = sí)"
            else:
                self._redact_case_btn.icon        = ft.Icons.FONT_DOWNLOAD_OFF_OUTLINED
                self._redact_case_btn.bgcolor     = None
                self._redact_case_btn.tooltip     = "Ignorar mayúsculas (activo = no)"
            try:
                self._redact_case_btn.update()
            except Exception:
                pass

    def _toggle_redact_panel(self, e=None) -> None:
        pass

    # ── profile label / save-btn helpers ─────────────────────────────────────

    def _update_profile_label(self) -> None:
        if self._active_profile_label is None:
            return
        if self._active_profile is not None:
            self._active_profile_label.value  = self._active_profile.name
            self._active_profile_label.italic  = False
            self._active_profile_label.weight  = ft.FontWeight.W_500
        else:
            self._active_profile_label.value  = "Sin perfil"
            self._active_profile_label.italic  = True
            self._active_profile_label.weight  = None
        try:
            self._active_profile_label.update()
        except Exception:
            pass

    def _update_profile_save_btn(self) -> None:
        if self._profile_save_btn is None:
            return
        has_terms = bool(self._redact_terms)
        label_ctrl = self._profile_save_btn.content.controls[1]
        if has_terms and self._active_profile is not None:
            label_ctrl.value = f"Actualizar «{self._active_profile.name}»"
        else:
            label_ctrl.value = "Guardar en perfil"
        self._profile_save_btn.visible = has_terms
        try:
            self._profile_save_btn.update()
        except Exception:
            pass

    # ── text search ───────────────────────────────────────────────────────────

    def _search_phrase(
        self, page, query: str, case_sensitive: bool,
        text_cache: dict | None = None, pn: int | None = None,
        whole_word: bool = False,
    ) -> list[fitz.Rect]:
        """Return all bounding rects where *query* appears in *page*.

        Strategy:
        1. Try PyMuPDF's native ``search_for`` (fast, handles single-span phrases).
           For case-insensitive, extract all exact-case variants via regex first.
        2. If no hits AND the query is multi-word, fall back to a word-by-word
           scan using ``get_text("words")``.  This catches phrases spread across
           different text blocks or spans (common in PDF titles/headers).

        ``whole_word``: cuando es True se **omite** ``search_for`` (que hace
        matching de SUBCADENA — "la" coincide dentro de "tabla", "regla"…) y se
        matchea contra los **tokens** de ``get_text("words")`` por igualdad, de
        modo que "la" solo coincide con la palabra "la" suelta. PyMuPDF no tiene
        un flag nativo de palabra completa, así que el matching por tokens es la
        vía correcta. Reduce de decenas de miles de coincidencias a unas pocas.

        ``text_cache`` (opcional, indexado por ``pn``) memoiza el ``get_text`` /
        ``get_text("words")`` de la página. El texto de una página es idéntico
        para todos los términos de un lote (cargar un perfil añade N términos en
        serie), así que reusarlo evita re-parsear el documento entero por término
        (N×P extracciones → P). Es un cache que provee el llamador del lote y que
        descarta al terminar, por lo que nunca queda obsoleto. Si es None, el
        comportamiento es idéntico al de antes (extracción directa).
        """
        q = query.strip()
        if not q:
            return []

        re_flags = 0 if case_sensitive else re.IGNORECASE

        def _cached(kind: str, extract):
            if text_cache is None or pn is None:
                return extract()
            entry = text_cache.get(pn)
            if entry is None:
                entry = {}
                text_cache[pn] = entry
            if kind not in entry:
                entry[kind] = extract()
            return entry[kind]

        q_words = q.split()

        # ── 1. Native search_for (matching de subcadena) ──────────────────────
        # Solo en modo NO palabra-completa. Si encuentra, o si es una sola
        # palabra, devolvemos; multi-palabra sin hit cae al matching por tokens.
        if not whole_word:
            native: list[fitz.Rect] = []
            if case_sensitive:
                native = [fitz.Rect(r) for r in page.search_for(q)]
            else:
                page_text = _cached("text", page.get_text)
                seen: set[str] = set()
                for m in re.finditer(re.escape(q), page_text, re_flags):
                    variant = page_text[m.start():m.end()]
                    if variant not in seen:
                        seen.add(variant)
                        native.extend(fitz.Rect(r) for r in page.search_for(variant))
            if native or len(q_words) == 1:
                return native

        # ── 2. Matching por TOKENS ────────────────────────────────────────────
        # Modo palabra-completa (cualquier nº de palabras) y también el fallback
        # multi-palabra del modo subcadena. Compara tokens enteros → nunca matchea
        # dentro de otra palabra.
        if not q_words:
            return []
        pw = _cached("words", lambda: page.get_text("words"))

        def _norm(w: str) -> str:
            w = _fold_accents(w.strip(string.punctuation))
            return w.lower() if not case_sensitive else w

        cmp_q = [_norm(w) for w in q_words]
        n = len(q_words)
        rects: list[fitz.Rect] = []
        for i in range(len(pw) - n + 1):
            chunk = pw[i:i + n]
            if [_norm(w[4]) for w in chunk] == cmp_q:
                # Una frase puede CRUZAR de renglón o de columna. Fusionar todo
                # en un solo min/max producía un rect gigante que abarcaba el
                # ancho completo entre ambas líneas y censuraba texto ajeno.
                # Un rect por (bloque, línea) censura exactamente las palabras
                # de la frase. get_text("words") → (x0,y0,x1,y1, word, block,
                # line, word_no).
                runs: dict[tuple, list] = {}
                for w in chunk:
                    runs.setdefault((w[5], w[6]), []).append(w)
                for run in runs.values():
                    x0 = min(w[0] for w in run)
                    y0 = min(w[1] for w in run)
                    x1 = max(w[2] for w in run)
                    y1 = max(w[3] for w in run)
                    rects.append(fitz.Rect(x0, y0, x1, y1))
        return rects

    def _search_phrase_in_ocr(
        self, detections, query: str, case_sensitive: bool,
        whole_word: bool = False,
        cache_entry: dict | None = None,
    ) -> list[tuple[fitz.Rect, str]]:
        """Search for *query* across all OCR detections on a page.

        OCR engines return one detection per word/fragment.  Searching for a
        phrase inside a single detection always fails for multi-word queries.
        This method concatenates detections in reading order, runs the regex on
        the resulting string, then maps each match back to the involved
        detections and merges their bounding boxes.

        ``whole_word`` rodea el patrón con límites de palabra (``\\b``) para que
        "la" no coincida dentro de "tabla" — paridad con el modo palabra-completa
        del texto nativo.

        ``cache_entry`` (dict por página del ``text_cache`` del lote) memoiza el
        concatenado (sorted_dets, char_to_det, full_text): cargar un perfil con
        N términos re-concatenaba las detecciones de cada página OCR N veces.
        Igual que el cache nativo, lo provee el llamador del lote y se descarta
        al terminar — nunca queda obsoleto.
        """
        if not detections:
            return []

        re_flags = 0 if case_sensitive else re.IGNORECASE

        prep = cache_entry.get("ocr_concat") if cache_entry is not None else None
        if prep is None:
            sorted_dets = sorted(
                [d for d in detections if d.text.strip()],
                key=lambda d: (round(d.bbox.y0 / 10) * 10, d.bbox.x0),
            )

            parts: list[str] = []
            char_to_det: list[int] = []
            for i, det in enumerate(sorted_dets):
                if parts:
                    parts.append(" ")
                    char_to_det.append(-1)
                for ch in det.text:
                    parts.append(ch)
                    char_to_det.append(i)

            # Plegar acentos en el texto y la consulta (tabla 1:1 → las posiciones
            # de caracteres siguen alineadas con char_to_det) para que "COMITÉ"
            # coincida con "COMITE", igual que en la búsqueda de texto nativo.
            full_text = _fold_accents("".join(parts))
            prep = (sorted_dets, char_to_det, full_text)
            if cache_entry is not None:
                cache_entry["ocr_concat"] = prep

        sorted_dets, char_to_det, full_text = prep
        if not sorted_dets:
            return []

        pattern = re.escape(_fold_accents(query))
        if whole_word:
            pattern = r"\b" + pattern + r"\b"
        results: list[tuple[fitz.Rect, str]] = []
        for m in re.finditer(pattern, full_text, re_flags):
            det_indices: set[int] = set()
            for ci in range(m.start(), m.end()):
                di = char_to_det[ci]
                if di >= 0:
                    det_indices.add(di)
            if not det_indices:
                continue
            involved = [sorted_dets[di] for di in sorted(det_indices)]
            label = full_text[m.start():m.end()][:80]

            # Igual que en el camino nativo: una frase que cruza de renglón no
            # debe fusionarse en un solo rect gigante (censuraría el bloque
            # completo entre líneas). Agrupar las detecciones por renglón
            # (centro vertical con tolerancia) y emitir un rect por línea.
            involved.sort(key=lambda d: (d.bbox.y0, d.bbox.x0))
            line_grp: list = [involved[0]]
            grps: list[list] = [line_grp]
            for d in involved[1:]:
                ref = line_grp[-1].bbox
                tol = max(3.0, min(ref.y1 - ref.y0, d.bbox.y1 - d.bbox.y0) * 0.7)
                cy_d   = (d.bbox.y0 + d.bbox.y1) / 2
                cy_ref = (ref.y0 + ref.y1) / 2
                if abs(cy_d - cy_ref) > tol:
                    line_grp = [d]
                    grps.append(line_grp)
                else:
                    line_grp.append(d)
            for grp in grps:
                merged = fitz.Rect(
                    min(d.bbox.x0 for d in grp),
                    min(d.bbox.y0 for d in grp),
                    max(d.bbox.x1 for d in grp),
                    max(d.bbox.y1 for d in grp),
                )
                results.append((merged, label))

        return results

    # ── term management ───────────────────────────────────────────────────────

    def _find_term_matches(
        self, term: str, case_sensitive: bool,
        text_cache: dict | None = None,
    ) -> list[tuple[int, fitz.Rect, str]]:
        """Search *term* across the whole document (PDF text + OCR) and return
        a flat list of (page_num, rect, label) tuples.

        ``text_cache`` se reenvía a ``_search_phrase`` para reusar el texto ya
        extraído de cada página entre términos de un mismo lote (ver allí)."""
        cap = self._REDACT_MAX_MATCHES
        # La búsqueda de censura es SIEMPRE por palabra completa: "la" no coincide
        # dentro de "tabla". Evita la explosión de coincidencias (y el freeze) con
        # palabras comunes y es el comportamiento esperable al censurar términos.
        whole_word = True
        matches: list[tuple[int, fitz.Rect, str]] = []
        # Coincidencias nativas por página (en pantalla) para deduplicar las de
        # OCR: en PDFs híbridos/buscables la misma palabra existe en la capa
        # nativa Y como detección OCR → sin este filtro se dibujaban DOS
        # recuadros de censura por hit (el nativo, más alto por métrica de
        # fuente, y el OCR ajustado al píxel) y la censura se aplicaba doble.
        native_by_pn: dict[int, list[fitz.Rect]] = {}
        # Lock POR PÁGINA (no durante todo el documento): la búsqueda de un
        # término en un PDF grande tardaba lo suyo y, con el lock retenido de
        # principio a fin, los workers de render quedaban bloqueados — hacer
        # scroll durante una búsqueda mostraba páginas en blanco. Entre página
        # y página el lock se libera y el render intercala.
        with self._doc_lock:
            total = len(self.doc)
        for pn in range(total):
            with self._doc_lock:
                if pn >= len(self.doc):   # el documento pudo cambiar entre páginas
                    break
                page = self.doc[pn]
                for r in self._search_phrase(
                    page, term, case_sensitive, text_cache=text_cache, pn=pn,
                    whole_word=whole_word,
                ):
                    # El label de una coincidencia de BÚSQUEDA no se usa en ningún
                    # lado (_apply_redaction y el preview lo ignoran), así que
                    # guardamos el término directamente en vez de llamar a
                    # page.get_textbox(r) por cada coincidencia — esa llamada
                    # nativa por match era el cuello de botella al buscar palabras
                    # muy comunes (miles de coincidencias × textbox descartado).
                    # Almacenar SIEMPRE en espacio de pantalla (rotado), igual que
                    # las detecciones OCR, para que coincida con la imagen mostrada
                    # y con la vista previa. _apply_redaction des-rota al escribir.
                    # rotation_matrix es identidad si la página no está rotada.
                    r_screen = fitz.Rect(r) * page.rotation_matrix
                    matches.append((pn, r_screen, term))
                    native_by_pn.setdefault(pn, []).append(r_screen)
            # Cortacircuitos: una palabra muy común generaría decenas de miles
            # de coincidencias y congelaría la UI. Al alcanzar el tope, cortar.
            if len(matches) >= cap:
                del matches[cap:]
                return matches
        if self._redact_incl_ocr is not None and self._redact_incl_ocr.value:

            def _dup_of_native(rect: fitz.Rect, pn: int) -> bool:
                """True si *rect* (hit OCR) solapa ≥50% con un hit nativo de la
                misma página → es la misma palabra detectada dos veces.

                Al detectar el duplicado, el hit nativo ADOPTA la geometría del
                OCR: en escaneos buscables la caja nativa usa la métrica de la
                fuente invisible (más alta/ancha que la tinta) mientras la OCR
                abraza los píxeles — sin esto el recuadro de censura por
                búsqueda salía visiblemente más grande que uno manual. El rect
                mutado es el MISMO objeto ya guardado en ``matches``. La caja
                OCR sigue intersectando todos los chars nativos (solape ≥50%),
                así que apply_redactions elimina igualmente el texto oculto.
                """
                for nr in native_by_pn.get(pn, ()):
                    ix = min(rect.x1, nr.x1) - max(rect.x0, nr.x0)
                    iy = min(rect.y1, nr.y1) - max(rect.y0, nr.y0)
                    if ix > 0 and iy > 0:
                        inter = ix * iy
                        if inter >= 0.5 * min(rect.get_area(), nr.get_area()):
                            nr.x0, nr.y0 = rect.x0, rect.y0
                            nr.x1, nr.y1 = rect.x1, rect.y1
                            return True
                return False

            for pn, result in self._ocr_by_page.items():
                # Compartir el dict por página del text_cache con el concatenado
                # OCR (claves disjuntas de las nativas "text"/"words").
                entry = text_cache.setdefault(pn, {}) if text_cache is not None else None
                for rect, label in self._search_phrase_in_ocr(
                    result.detections, term, case_sensitive, whole_word=whole_word,
                    cache_entry=entry,
                ):
                    if _dup_of_native(rect, pn):
                        continue
                    matches.append((pn, rect, label))
                    if len(matches) >= cap:
                        del matches[cap:]
                        return matches
        return matches

    def _flatten_matches(self) -> list[tuple[int, fitz.Rect, str]]:
        flat: list[tuple[int, fitz.Rect, str]] = []
        for t in self._redact_terms:
            flat.extend(self._redact_term_matches.get(t, []))
        return flat

    def _add_redact_term(self, e=None) -> None:
        if self._redact_query_field is None:
            return
        term = (self._redact_query_field.value or "").strip()
        if not term:
            return
        if term in self._redact_terms:
            self._show_snack("Esa frase ya está en la lista")
            return
        case_sensitive = getattr(self, "_redact_case_sensitive", True)
        matches = self._find_term_matches(term, case_sensitive)
        if not matches:
            self._show_snack("No se encontró la frase en el documento")
            return
        capped = len(matches) >= self._REDACT_MAX_MATCHES
        self._redact_terms.append(term)
        self._redact_term_matches[term] = matches
        self._redact_matches = self._flatten_matches()
        self._redact_query_field.value = ""
        try:
            self._redact_query_field.update()
        except Exception:
            pass
        self._rebuild_redact_terms_list()
        self._update_profile_save_btn()
        # mostrar las zonas de censura por defecto en cuanto hay términos
        self._redact_preview = True
        if self._redact_preview_btn is not None:
            self._redact_preview_btn.bgcolor    = _SELECTED_BG
            self._redact_preview_btn.icon_color = getattr(self, "_redact_box_color", "#000000")
            try:
                self._redact_preview_btn.update()
            except Exception:
                pass
        self._render_redact_preview(force_update=True)
        self.page_ref.update()
        if capped:
            self._show_snack(
                f"«{term}» es muy común: se limitó a {self._REDACT_MAX_MATCHES} "
                "zonas. Refiná el término para censurar solo lo que necesitas."
            )

    def _add_term_direct(self, term: str, text_cache: dict | None = None) -> None:
        """Add a term without reading from the input field (for programmatic use).

        ``text_cache`` permite a un llamador que añade varios términos en serie
        (cargar perfil, lote del agente) compartir el texto extraído de cada
        página entre términos. Ver ``_search_phrase``."""
        term = term.strip()
        if not term or term in self._redact_terms:
            return
        case_sensitive = getattr(self, "_redact_case_sensitive", True)
        matches = self._find_term_matches(term, case_sensitive, text_cache=text_cache)
        if not matches:
            return
        self._redact_terms.append(term)
        self._redact_term_matches[term] = matches
        self._redact_matches = self._flatten_matches()

    def _remove_redact_term(self, term: str) -> None:
        if term in self._redact_terms:
            self._redact_terms.remove(term)
        self._redact_term_matches.pop(term, None)
        self._redact_matches = self._flatten_matches()
        self._rebuild_redact_terms_list()
        self._update_profile_save_btn()
        if self._redact_preview:
            self._render_redact_preview(force_update=True)
        self.page_ref.update()

    def _rebuild_redact_terms_list(self) -> None:
        if self._redact_terms_list is None:
            return
        _HDR  = "#E65100"
        color = getattr(self, "_redact_box_color", "#000000")

        if not self._redact_terms:
            self._redact_terms_list.controls = [
                ft.Container(
                    ft.Text(
                        "Sin términos — escribe una frase y pulsa Enter",
                        size=11, color="onSurfaceVariant", italic=True,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=8),
                )
            ]
            if self._redact_count_text is not None:
                self._redact_count_text.value = ""
        else:
            total = sum(
                len(self._redact_term_matches.get(t, [])) for t in self._redact_terms
            )
            pages_hit = len({
                pn
                for t in self._redact_terms
                for pn, _, _ in self._redact_term_matches.get(t, [])
            })
            if self._redact_count_text is not None:
                self._redact_count_text.value = (
                    f"{total} coincid. en {pages_hit} pág."
                )
            rows: list[ft.Control] = []
            for term in self._redact_terms:
                n   = len(self._redact_term_matches.get(term, []))
                _t  = term
                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Container(
                                    width=12, height=12,
                                    bgcolor=color, border_radius=6,
                                ),
                                ft.Text(
                                    term, size=11, expand=True,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    color="onSurface",
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        str(n), size=9,
                                        color="#FFFFFF",
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    bgcolor=_HDR, border_radius=4,
                                    padding=ft.padding.symmetric(
                                        horizontal=5, vertical=2
                                    ),
                                ),
                                ft.IconButton(
                                    ft.Icons.CLOSE, icon_size=12,
                                    tooltip="Eliminar de la lista",
                                    icon_color="#795548",
                                    style=ft.ButtonStyle(
                                        padding=ft.padding.all(2)
                                    ),
                                    on_click=lambda e, t=_t: self._remove_redact_term(t),
                                ),
                            ],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.padding.symmetric(horizontal=8, vertical=5),
                        border_radius=6,
                        border=ft.border.all(1, "outlineVariant"),
                        bgcolor="surface",
                    )
                )
            self._redact_terms_list.controls = rows

        try:
            self._redact_terms_list.update()
        except Exception:
            pass
        if self._redact_count_text is not None:
            try:
                self._redact_count_text.update()
            except Exception:
                pass

    def _select_redact_color(self, color: str) -> None:
        self._redact_box_color = color
        for c, btn in self._redact_color_btns.items():
            btn.border = ft.border.all(3, "#E65100" if c == color else "outlineVariant")
            try:
                btn.update()
            except Exception:
                pass
        self._rebuild_redact_terms_list()
        if self._redact_preview:
            self._render_redact_preview(force_update=True)

    # ── preview ───────────────────────────────────────────────────────────────

    def _reapply_redact_page(self, pn: int) -> None:
        """Redibuja los recuadros de preview de censura sobre UNA página.

        Se llama al construir un slot perezosamente (_build_page_slot): la página
        pudo materializarse desde un placeholder con el preview ya activo, por lo
        que _render_redact_preview (ejecutado antes) no pudo poner sus cajas."""
        if not getattr(self, "_redact_preview", False):
            return
        if pn >= len(self._redact_overlays):
            return
        ov = self._redact_overlays[pn]
        if ov is None:
            return
        scale = self.zoom * BASE_SCALE
        color = getattr(self, "_redact_box_color", "#000000")
        fill  = color + "88"
        boxes: list[ft.Control] = []
        for term in self._redact_terms:
            for mp, rect, _ in self._redact_term_matches.get(term, []):
                if mp != pn:
                    continue
                boxes.append(ft.Container(
                    left=rect.x0 * scale, top=rect.y0 * scale,
                    width=max(2, rect.width * scale),
                    height=max(2, rect.height * scale),
                    bgcolor=fill,
                    border=ft.border.all(2, color),
                    tooltip="Clic para eliminar esta zona de censura",
                    ink=True,
                    on_click=lambda e, _t=term, _p=pn, _r=rect: self._remove_redact_match(_t, _p, _r),
                ))
        ov.controls = boxes
        ov.visible  = bool(boxes)
        try:
            ov.update()
        except Exception:
            pass

    def _render_redact_preview(self, *, force_update: bool = False) -> None:
        affected: set[int] = set()
        for pn in range(len(self._redact_overlays)):
            ov = self._redact_overlays[pn]
            if ov is None:  # slot no construido (placeholder)
                continue
            if ov.visible or ov.controls:
                ov.visible  = False
                ov.controls = []
                affected.add(pn)

        if self._redact_preview and self._redact_matches:
            scale  = self.zoom * BASE_SCALE
            color  = getattr(self, "_redact_box_color", "#000000")
            fill   = color + "88"
            by_page: dict[int, list[tuple[fitz.Rect, str]]] = {}
            for term in self._redact_terms:
                for pn, rect, _ in self._redact_term_matches.get(term, []):
                    by_page.setdefault(pn, []).append((rect, term))
            for pn, rect_terms in by_page.items():
                if pn >= len(self._redact_overlays):
                    continue
                if self._redact_overlays[pn] is None:
                    # Página no construida (placeholder): las cajas se re-aplican
                    # al materializar el slot (_reapply_redact_page).
                    continue
                boxes: list[ft.Control] = []
                for r, term in rect_terms:
                    boxes.append(ft.Container(
                        left=r.x0 * scale, top=r.y0 * scale,
                        width=max(2, r.width * scale),
                        height=max(2, r.height * scale),
                        bgcolor=fill,
                        border=ft.border.all(2, color),
                        tooltip="Clic para eliminar esta zona de censura",
                        ink=True,
                        on_click=lambda e, _t=term, _p=pn, _r=r: self._remove_redact_match(_t, _p, _r),
                    ))
                ov = self._redact_overlays[pn]
                ov.controls = boxes
                ov.visible  = True
                affected.add(pn)

        if force_update:
            for pn in affected:
                if pn < len(self._redact_overlays):
                    try:
                        self._redact_overlays[pn].update()
                    except Exception:
                        pass

    def _remove_redact_match(self, term: str, pn: int, rect: fitz.Rect) -> None:
        """Remove one specific redaction zone from the viewer and the terms list."""
        if term not in self._redact_term_matches:
            return
        new_matches = [
            (p, r, l)
            for p, r, l in self._redact_term_matches[term]
            if not (p == pn and r == rect)
        ]
        if not new_matches:
            if term in self._redact_terms:
                self._redact_terms.remove(term)
            self._redact_term_matches.pop(term, None)
        else:
            self._redact_term_matches[term] = new_matches
        self._redact_matches = self._flatten_matches()
        self._rebuild_redact_terms_list()
        if not self._redact_matches:
            self._redact_preview = False
            if self._redact_preview_btn is not None:
                self._redact_preview_btn.bgcolor    = None
                self._redact_preview_btn.icon_color = None
                try:
                    self._redact_preview_btn.update()
                except Exception:
                    pass
        self._render_redact_preview(force_update=True)
        self._show_snack("Zona de censura eliminada")

    def _toggle_redact_preview(self, e=None) -> None:
        if not self._redact_matches:
            self._show_snack("Agrega al menos un término para ver la vista previa")
            return
        self._redact_preview = not self._redact_preview
        self._render_redact_preview(force_update=True)
        if self._redact_preview_btn is not None:
            self._redact_preview_btn.bgcolor    = _SELECTED_BG if self._redact_preview else None
            self._redact_preview_btn.icon_color = getattr(self, "_redact_box_color", "#E65100") \
                                                  if self._redact_preview else None
            try:
                self._redact_preview_btn.update()
            except Exception:
                pass

    # ── apply ─────────────────────────────────────────────────────────────────

    def _apply_redaction(self, e=None) -> None:
        if not self._redact_matches:
            self._show_snack("Agrega al menos un término antes de aplicar la censura")
            return
        color = getattr(self, "_redact_box_color", "#000000")
        r_f = int(color[1:3], 16) / 255
        g_f = int(color[3:5], 16) / 255
        b_f = int(color[5:7], 16) / 255
        fill = (r_f, g_f, b_f)

        affected_pages: set[int] = set()
        failed_apply: list[int] = []

        with self._doc_lock:
            for pn in {p for p, _, _ in self._redact_matches}:
                try:
                    self.doc[pn].clean_contents()
                except Exception:
                    pass

            for pn, rect, _ in self._redact_matches:
                page = self.doc[pn]
                # Las coincidencias están en espacio de PANTALLA (rotado, el de
                # la imagen renderizada). add_redact_annot opera en el espacio
                # SIN rotar de la página (mediabox), así que en páginas rotadas
                # (p. ej. escaneos con /Rotate 90/270) hay que des-rotar el rect
                # o la censura aparece transpuesta. derotation_matrix es la
                # identidad cuando rotation == 0, así que es seguro siempre.
                r = (fitz.Rect(rect.x0, rect.y0 - 1,
                               rect.x1, rect.y1 + 1)
                     * page.derotation_matrix)
                try:
                    page.add_redact_annot(
                        r, fill=fill, cross_out=False,
                    )
                    affected_pages.add(pn)
                except Exception:
                    pass

            for pn in affected_pages:
                page = self.doc[pn]
                try:
                    ok = page.apply_redactions(
                        images=fitz.PDF_REDACT_IMAGE_PIXELS,
                        text=fitz.PDF_REDACT_TEXT_REMOVE,
                    )
                    if not ok:
                        failed_apply.append(pn)
                except Exception:
                    try:
                        page.apply_redactions()
                    except Exception:
                        failed_apply.append(pn)
                try:
                    page.clean_contents()
                except Exception:
                    pass

            for pn in affected_pages:
                page = self.doc[pn]
                by_page = [rect for _pn, rect, _ in self._redact_matches
                           if _pn == pn]
                for rect in by_page:
                    # mismo espacio sin rotar que add_redact_annot (ver arriba)
                    r = (fitz.Rect(rect.x0 - 1, rect.y0 - 2,
                                   rect.x1 + 1, rect.y1 + 2)
                         * page.derotation_matrix)
                    try:
                        page.draw_rect(r, color=None, fill=fill, width=0)
                    except Exception:
                        pass

        for pn in affected_pages:
            if pn in self._ocr_by_page:
                redacted_rects = [
                    fitz.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2)
                    for _pn, r, _ in self._redact_matches
                    if _pn == pn
                ]
                result = self._ocr_by_page[pn]
                result.detections = [
                    det for det in result.detections
                    if not det.bbox or not any(
                        rr.intersects(det.bbox) for rr in redacted_rects
                    )
                ]
                result.segments = [
                    seg for seg in result.segments
                    if not seg.bbox or not any(
                        rr.intersects(seg.bbox) for rr in redacted_rects
                    )
                ]
                if not result.detections and not result.segments:
                    del self._ocr_by_page[pn]
            self._page_words.pop(pn, None)
            self._rendered.discard(pn)

        _rcache = getattr(self, "_render_cache", None)
        if _rcache is not None:
            for pn in affected_pages:
                _rcache.invalidate_page(pn)

        self._clear_redact_state()

        for pn in sorted(affected_pages):
            self._rerender_page_image(pn)

        if failed_apply:
            msg = (f"Censura aplicada en {len(affected_pages)} página(s)"
                   f" ({len(failed_apply)} página(s) con problemas: "
                   f"{', '.join(str(p+1) for p in failed_apply)})")
        else:
            msg = f"Censura aplicada en {len(affected_pages)} página(s)"
        self._refresh_ocr_ui_for_page()
        self._show_snack(msg)
        self.page_ref.update()

    def _clear_redact_state(self) -> None:
        self._redact_matches      = []
        self._redact_terms        = []
        self._redact_term_matches = {}
        self._redact_preview      = False
        self._active_profile      = None
        if self._redact_query_field is not None:
            self._redact_query_field.value = ""
        if self._redact_preview_btn is not None:
            self._redact_preview_btn.bgcolor    = None
            self._redact_preview_btn.icon_color = None
        if self._redact_terms_list is not None:
            self._rebuild_redact_terms_list()
        self._update_profile_save_btn()
        self._update_profile_label()
        for ov in self._redact_overlays:
            if ov is None:  # slot no construido (placeholder)
                continue
            ov.visible  = False
            ov.controls = []
