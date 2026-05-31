"""Redaction search/apply workflow for PDFViewerTab."""
from __future__ import annotations

import re
import string

import flet as ft
import fitz

from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG


class _RedactMixin:
    """Text redaction: term management, search, preview and apply."""

    _REDACT_HDR  = "#E65100"
    _SECTION_CLR = "#795548"

    # ── sidebar panel builder ─────────────────────────────────────────────────

    def _build_redact_sidebar_panel(self) -> ft.Container:
        """Build the Redaction collapsible panel and initialise its controls."""
        _REDACT_BG   = "#FFF8F0"
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
            bgcolor="#FFECB3",
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
        )

        # ── input + options ───────────────────────────────────────────────────
        self._redact_query_field = ft.TextField(
            hint_text="Escribe una frase y pulsa Enter para agregar…",
            dense=True, expand=True,
            on_submit=self._add_redact_term,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_color="#FFCCBC",
            focused_border_color=_REDACT_HDR,
        )
        self._redact_case_btn = ft.IconButton(
            ft.Icons.FONT_DOWNLOAD_OUTLINED, icon_size=18,
            tooltip="Distinguir mayúsculas (activo = sí)",
            icon_color=_REDACT_HDR, bgcolor="#FFE0B2",
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
            height=160,
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
            border=ft.border.all(1, "#FFCCBC"),
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
                border=ft.border.all(3, _REDACT_HDR if is_sel else "#DDDDDD"),
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
        )

        self._redact_content_area = ft.Container(
            ft.Column(
                [
                    # ── perfil ────────────────────────────────────────────────
                    profile_banner,
                    # ── agregar término ───────────────────────────────────────
                    ft.Divider(height=1, color="#FFE0B2"),
                    _section_label("Agregar texto a censurar", ft.Icons.ADD_CIRCLE_OUTLINE),
                    ft.Row(
                        [self._redact_query_field, self._redact_case_btn],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_incl_ocr,
                    # ── lista de términos ─────────────────────────────────────
                    ft.Divider(height=1, color="#FFE0B2"),
                    ft.Row(
                        [
                            _section_label("Lista de censuras", ft.Icons.LIST_ALT_OUTLINED),
                            ft.Container(expand=True),
                            self._redact_count_text,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_terms_list,
                    self._profile_save_btn,
                    # ── color + vista previa ──────────────────────────────────
                    ft.Divider(height=1, color="#FFE0B2"),
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
                    # ── aplicar ───────────────────────────────────────────────
                    ft.ElevatedButton(
                        "Aplicar censura al documento", icon=ft.Icons.EDIT_OFF,
                        color="#FFFFFF", bgcolor=_REDACT_MID,
                        on_click=self._apply_redaction, expand=True,
                        style=ft.ButtonStyle(
                            padding=ft.padding.symmetric(vertical=10)
                        ),
                    ),
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
                self._redact_case_btn.bgcolor     = "#FFE0B2"
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

    def _search_phrase(self, page, query: str, case_sensitive: bool) -> list[fitz.Rect]:
        """Return all bounding rects where *query* appears in *page*.

        Strategy:
        1. Try PyMuPDF's native ``search_for`` (fast, handles single-span phrases).
           For case-insensitive, extract all exact-case variants via regex first.
        2. If no hits AND the query is multi-word, fall back to a word-by-word
           scan using ``get_text("words")``.  This catches phrases spread across
           different text blocks or spans (common in PDF titles/headers).
        """
        q = query.strip()
        if not q:
            return []

        re_flags = 0 if case_sensitive else re.IGNORECASE

        # ── 1. Native search_for ──────────────────────────────────────────────
        native: list[fitz.Rect] = []
        if case_sensitive:
            native = [fitz.Rect(r) for r in page.search_for(q)]
        else:
            page_text = page.get_text()
            seen: set[str] = set()
            for m in re.finditer(re.escape(q), page_text, re_flags):
                variant = page_text[m.start():m.end()]
                if variant not in seen:
                    seen.add(variant)
                    native.extend(fitz.Rect(r) for r in page.search_for(variant))

        q_words = q.split()
        if native or len(q_words) == 1:
            return native

        # ── 2. Word-by-word fallback for multi-word phrases ───────────────────
        pw = page.get_text("words")

        def _norm(w: str) -> str:
            w = w.strip(string.punctuation)
            return w.lower() if not case_sensitive else w

        cmp_q = [_norm(w) for w in q_words]
        n = len(q_words)
        rects: list[fitz.Rect] = []
        for i in range(len(pw) - n + 1):
            chunk = pw[i:i + n]
            if [_norm(w[4]) for w in chunk] == cmp_q:
                x0 = min(w[0] for w in chunk)
                y0 = min(w[1] for w in chunk)
                x1 = max(w[2] for w in chunk)
                y1 = max(w[3] for w in chunk)
                rects.append(fitz.Rect(x0, y0, x1, y1))
        return rects

    def _search_phrase_in_ocr(
        self, detections, query: str, case_sensitive: bool
    ) -> list[tuple[fitz.Rect, str]]:
        """Search for *query* across all OCR detections on a page.

        OCR engines return one detection per word/fragment.  Searching for a
        phrase inside a single detection always fails for multi-word queries.
        This method concatenates detections in reading order, runs the regex on
        the resulting string, then maps each match back to the involved
        detections and merges their bounding boxes.
        """
        if not detections:
            return []

        re_flags = 0 if case_sensitive else re.IGNORECASE

        sorted_dets = sorted(
            [d for d in detections if d.text.strip()],
            key=lambda d: (round(d.bbox.y0 / 10) * 10, d.bbox.x0),
        )
        if not sorted_dets:
            return []

        parts: list[str] = []
        char_to_det: list[int] = []

        for i, det in enumerate(sorted_dets):
            if parts:
                parts.append(" ")
                char_to_det.append(-1)
            for ch in det.text:
                parts.append(ch)
                char_to_det.append(i)

        full_text = "".join(parts)

        results: list[tuple[fitz.Rect, str]] = []
        for m in re.finditer(re.escape(query), full_text, re_flags):
            det_indices: set[int] = set()
            for ci in range(m.start(), m.end()):
                di = char_to_det[ci]
                if di >= 0:
                    det_indices.add(di)
            if not det_indices:
                continue
            involved = [sorted_dets[di] for di in sorted(det_indices)]
            merged = fitz.Rect(
                min(d.bbox.x0 for d in involved),
                min(d.bbox.y0 for d in involved),
                max(d.bbox.x1 for d in involved),
                max(d.bbox.y1 for d in involved),
            )
            label = full_text[m.start():m.end()][:80]
            results.append((merged, label))

        return results

    # ── term management ───────────────────────────────────────────────────────

    def _find_term_matches(
        self, term: str, case_sensitive: bool
    ) -> list[tuple[int, fitz.Rect, str]]:
        """Search *term* across the whole document (PDF text + OCR) and return
        a flat list of (page_num, rect, label) tuples."""
        matches: list[tuple[int, fitz.Rect, str]] = []
        with self._doc_lock:
            for pn in range(len(self.doc)):
                page = self.doc[pn]
                for r in self._search_phrase(page, term, case_sensitive):
                    try:
                        label = page.get_textbox(r).strip()[:80]
                    except Exception:
                        label = term
                    matches.append((pn, r, label or term))
        if self._redact_incl_ocr is not None and self._redact_incl_ocr.value:
            for pn, result in self._ocr_by_page.items():
                for rect, label in self._search_phrase_in_ocr(
                    result.detections, term, case_sensitive
                ):
                    matches.append((pn, rect, label))
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
        if self._redact_preview:
            self._render_redact_preview(force_update=True)
        self.page_ref.update()

    def _add_term_direct(self, term: str) -> None:
        """Add a term without reading from the input field (for programmatic use)."""
        term = term.strip()
        if not term or term in self._redact_terms:
            return
        case_sensitive = getattr(self, "_redact_case_sensitive", True)
        matches = self._find_term_matches(term, case_sensitive)
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
                        size=11, color="#BCAAA4", italic=True,
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
                                    color="#4E342E",
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
                        border=ft.border.all(1, "#FFCCBC"),
                        bgcolor="#FFFFFF",
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
            btn.border = ft.border.all(3, "#E65100" if c == color else "#DDDDDD")
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
                r = fitz.Rect(rect.x0, rect.y0 - 1,
                              rect.x1, rect.y1 + 1)
                try:
                    self.doc[pn].add_redact_annot(
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
                    r = fitz.Rect(rect.x0 - 1, rect.y0 - 2,
                                  rect.x1 + 1, rect.y1 + 2)
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
