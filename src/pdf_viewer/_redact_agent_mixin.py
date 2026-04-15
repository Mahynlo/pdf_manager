"""Redaction search/apply and AI-agent chat panel for PDFViewerTab."""
from __future__ import annotations

import re
import string
import threading

import flet as ft
import fitz

from .renderer import BASE_SCALE
from ._viewer_defs import _SELECTED_BG


class _RedactAgentMixin:
    """Text redaction workflow and AI document-analysis agent panel."""

    # ── sidebar panel builders ────────────────────────────────────────────────

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

        # ── preview + collapse ────────────────────────────────────────────────
        self._redact_preview_btn = ft.IconButton(
            ft.Icons.PREVIEW_OUTLINED, icon_size=18,
            tooltip="Mostrar/ocultar zonas marcadas en el documento",
            on_click=self._toggle_redact_preview,
        )
        self._redact_collapse_btn = ft.IconButton(
            ft.Icons.EXPAND_MORE, icon_size=18,
            tooltip="Expandir panel Redacción",
            on_click=self._toggle_redact_panel,
        )

        self._redact_content_area = ft.Container(
            ft.Column(
                [
                    # ── agregar término ───────────────────────────────────────
                    _section_label("Agregar texto a redactar", ft.Icons.ADD_CIRCLE_OUTLINE),
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
                            _section_label("Lista de redacciones", ft.Icons.LIST_ALT_OUTLINED),
                            ft.Container(expand=True),
                            self._redact_count_text,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_terms_list,
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
                        "Aplicar redacción al documento", icon=ft.Icons.EDIT_OFF,
                        color="#FFFFFF", bgcolor=_REDACT_MID,
                        on_click=self._apply_redaction, expand=True,
                        style=ft.ButtonStyle(
                            padding=ft.padding.symmetric(vertical=10)
                        ),
                    ),
                ],
                spacing=8, expand=True,
            ),
            expand=True, visible=self._redact_panel_open,
            padding=ft.padding.only(top=4),
        )
        self._redact_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.EDIT_OFF, size=18, color=_REDACT_HDR),
                            ft.Text("Redacción", size=14, weight=ft.FontWeight.W_600,
                                    color=_REDACT_HDR),
                            ft.Container(expand=True),
                            self._redact_collapse_btn,
                        ],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_content_area,
                ],
                spacing=4, expand=self._redact_panel_open,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=_REDACT_BG,
            border=ft.border.only(top=ft.BorderSide(1, "#FFE0B2")),
            expand=self._redact_panel_open,
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

    def _build_agent_sidebar_panel(self) -> ft.Container:
        """Build the AI Agent collapsible panel and initialise its controls."""
        _AGENT_BG  = "#F3F0FF"
        _AGENT_HDR = "#5C35C9"

        self._agent_chat_list = ft.ListView(
            expand=True, spacing=6,
            padding=ft.padding.only(bottom=8),
            auto_scroll=True,
        )
        self._agent_input = ft.TextField(
            hint_text="Pregunta sobre el documento…",
            dense=True, expand=True, shift_enter=True,
            on_submit=self._agent_send,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
        )
        self._agent_key_field = ft.TextField(
            hint_text="API Key (Google Gemini u OpenAI)",
            dense=True, password=True, can_reveal_password=True, expand=True,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
        )
        self._agent_collapse_btn = ft.IconButton(
            ft.Icons.EXPAND_MORE, icon_size=18,
            tooltip="Expandir panel Agente IA",
            on_click=self._toggle_agent_panel,
        )
        self._agent_content_area = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            self._agent_key_field,
                            ft.IconButton(ft.Icons.KEY, icon_size=18,
                                          tooltip="Guardar API Key",
                                          on_click=self._agent_save_key),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "Resumir", icon=ft.Icons.SUMMARIZE_OUTLINED,
                                style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=8, vertical=4)),
                                on_click=lambda e: self._agent_quick("Genera un resumen completo del documento.", direct_action="summarize"),
                            ),
                            ft.OutlinedButton(
                                "Estructura", icon=ft.Icons.ACCOUNT_TREE_OUTLINED,
                                style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=8, vertical=4)),
                                on_click=lambda e: self._agent_quick("Analiza la estructura y el tipo de este documento.", direct_action="analyze"),
                            ),
                            ft.OutlinedButton(
                                "Redactar", icon=ft.Icons.EDIT_OFF_OUTLINED,
                                style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=8, vertical=4)),
                                on_click=lambda e: self._agent_quick("Identifica la información sensible que debería redactarse.", direct_action="redact"),
                            ),
                        ],
                        spacing=4, wrap=True,
                    ),
                    ft.Divider(height=1, color="#D1C4E9"),
                    ft.Container(self._agent_chat_list, expand=True),
                    ft.Row(
                        [
                            self._agent_input,
                            ft.IconButton(ft.Icons.SEND, icon_size=18,
                                          tooltip="Enviar", icon_color=_AGENT_HDR,
                                          on_click=self._agent_send),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6, expand=True,
            ),
            expand=True, visible=self._agent_panel_open,
        )
        self._agent_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SMART_TOY_OUTLINED, size=18, color=_AGENT_HDR),
                            ft.Text("Agente IA", size=14, weight=ft.FontWeight.W_600),
                            ft.Container(expand=True),
                            self._agent_collapse_btn,
                        ],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._agent_content_area,
                ],
                spacing=4, expand=self._agent_panel_open,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=_AGENT_BG,
            border=ft.border.only(top=ft.BorderSide(1, "#D1C4E9")),
            expand=self._agent_panel_open,
        )
        return self._agent_panel

    # ── panel collapse ────────────────────────────────────────────────────────

    def _toggle_redact_panel(self, e=None) -> None:
        self._redact_panel_open = not self._redact_panel_open
        if self._redact_content_area is not None:
            self._redact_content_area.visible = self._redact_panel_open
        if self._redact_collapse_btn is not None:
            self._redact_collapse_btn.icon    = ft.Icons.EXPAND_LESS if self._redact_panel_open else ft.Icons.EXPAND_MORE
            self._redact_collapse_btn.tooltip = "Contraer panel Redacción" if self._redact_panel_open else "Expandir panel Redacción"
        if self._redact_panel is not None:
            self._redact_panel.expand = self._redact_panel_open
            col = self._redact_panel.content
            if isinstance(col, ft.Column):
                col.expand = self._redact_panel_open
        try:
            self._right_sidebar.update()
        except Exception:
            pass

    def _toggle_agent_panel(self, e=None) -> None:
        self._agent_panel_open = not self._agent_panel_open
        if self._agent_content_area is not None:
            self._agent_content_area.visible = self._agent_panel_open
        if self._agent_collapse_btn is not None:
            self._agent_collapse_btn.icon    = ft.Icons.EXPAND_LESS if self._agent_panel_open else ft.Icons.EXPAND_MORE
            self._agent_collapse_btn.tooltip = "Contraer panel Agente IA" if self._agent_panel_open else "Expandir panel Agente IA"
        if self._agent_panel is not None:
            self._agent_panel.expand = self._agent_panel_open
            col = self._agent_panel.content
            if isinstance(col, ft.Column):
                col.expand = self._agent_panel_open
        try:
            self._right_sidebar.update()
        except Exception:
            pass

    # ── AI agent ──────────────────────────────────────────────────────────────

    def _agent_save_key(self, e=None) -> None:
        from agent.config import get_provider, set_api_key
        key = (self._agent_key_field.value or "").strip()
        if not key:
            self._show_snack("Introduce una API Key válida")
            return
        set_api_key(get_provider(), key)
        self._agent_key_field.value = ""
        self._agent_instance = None
        self._show_snack("API Key guardada")
        try:
            self._agent_key_field.update()
        except Exception:
            pass

    def _agent_get_or_create(self):
        if self._agent_instance is not None:
            return self._agent_instance
        from agent.config import get_api_key, get_provider, get_model
        from agent.pdf_agent import PDFAgent
        provider = get_provider()
        key      = get_api_key(provider)
        if not key:
            key = (self._agent_key_field.value or "").strip()
        if not key:
            raise ValueError("No hay API Key configurada. Introduce una en el panel del agente.")
        self._agent_instance = PDFAgent(
            pdf_path=self.path,
            api_key=key,
            provider=provider,
            model=get_model(provider),
            redact_callback=self._agent_redact_callback,
            ocr_overrides=self._build_ocr_overrides(),
        )
        return self._agent_instance

    def _agent_redact_callback(self, terms: list[str]) -> None:
        if not terms or self._agent_chat_list is None:
            return
        chips = []
        for term in terms[:20]:
            t = term
            chips.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Text(t, size=11, expand=True),
                            ft.IconButton(
                                ft.Icons.EDIT_OFF, icon_size=14,
                                tooltip="Buscar para redactar",
                                on_click=lambda e, _t=t: self._agent_apply_redaction_term(_t),
                            ),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#FFE0B2", border_radius=6,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                )
            )
        self._agent_chat_list.controls.append(
            ft.Container(
                ft.Column([
                    ft.Text("Términos sugeridos para redactar:", size=11,
                            weight=ft.FontWeight.W_600, color="#E65100"),
                    *chips,
                ], spacing=4),
                bgcolor="#FFF8F0", border_radius=8, padding=ft.padding.all(8),
            )
        )
        try:
            self._agent_chat_list.update()
        except Exception:
            pass

    def _agent_apply_redaction_term(self, term: str) -> None:
        if self._redact_query_field is not None:
            self._redact_query_field.value = term
        if not self._redact_panel_open:
            self._toggle_redact_panel()
        if not self._sidebar_visible:
            self._toggle_sidebar()
        self._add_redact_term()

    def _agent_append_bubble(self, role: str, text: str) -> None:
        is_user = role == "user"
        bubble = ft.Container(
            ft.Text(text, size=12, selectable=True,
                    color="#1A237E" if is_user else "#212121"),
            bgcolor="#E8EAF6" if is_user else "#F3F0FF",
            border_radius=ft.border_radius.only(
                top_left=10, top_right=10,
                bottom_left=0 if is_user else 10,
                bottom_right=10 if is_user else 0,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(left=40 if is_user else 0, right=0 if is_user else 40),
        )
        if self._agent_chat_list is not None:
            self._agent_chat_list.controls.append(bubble)
            try:
                self._agent_chat_list.update()
            except Exception:
                pass

    def _agent_send(self, e=None) -> None:
        if self._agent_running:
            return
        msg = (self._agent_input.value or "").strip()
        if not msg:
            return
        self._agent_input.value = ""
        try:
            self._agent_input.update()
        except Exception:
            pass
        self._agent_quick(msg)

    def _agent_quick(self, message: str, direct_action: str = "") -> None:
        if self._agent_running:
            self._show_snack("El agente ya está procesando una solicitud…")
            return
        if not self._agent_panel_open:
            self._toggle_agent_panel()
        if not self._sidebar_visible:
            self._toggle_sidebar()

        self._agent_append_bubble("user", message)
        self._agent_history.append({"role": "user", "content": message})

        thinking = ft.Container(
            ft.Row([
                ft.ProgressRing(width=14, height=14, stroke_width=2),
                ft.Text("Pensando…", size=11, color="#5C35C9"),
            ], spacing=6),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
        )
        if self._agent_chat_list is not None:
            self._agent_chat_list.controls.append(thinking)
            try:
                self._agent_chat_list.update()
            except Exception:
                pass

        self._agent_running = True

        def _run():
            try:
                agent = self._agent_get_or_create()
                if direct_action == "summarize":
                    reply = agent.summarize()
                elif direct_action == "analyze":
                    reply = agent.analyze_structure()
                elif direct_action == "extract":
                    reply = agent.extract_key_info()
                elif direct_action == "redact":
                    reply = agent.suggest_redactions()
                else:
                    reply = agent.chat(message, self._agent_history[:-1])
            except Exception as ex:
                reply = f"Error: {ex}"
            finally:
                self._agent_running = False
            self._agent_history.append({"role": "assistant", "content": reply})
            if self._agent_chat_list is not None:
                try:
                    self._agent_chat_list.controls.remove(thinking)
                except ValueError:
                    pass
            self._agent_append_bubble("assistant", reply)

        threading.Thread(target=_run, daemon=True).start()

    # ── redaction search / apply ──────────────────────────────────────────────

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
        # get_text("words") → (x0, y0, x1, y1, word_text, block_no, line_no, word_no)
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

        # Sort by reading order: round y0 to 10-pt bands, then by x0
        sorted_dets = sorted(
            [d for d in detections if d.text.strip()],
            key=lambda d: (round(d.bbox.y0 / 10) * 10, d.bbox.x0),
        )
        if not sorted_dets:
            return []

        # Build concatenated text and a parallel list mapping each char → det index
        parts: list[str] = []
        char_to_det: list[int] = []

        for i, det in enumerate(sorted_dets):
            if parts:           # separator space between detections
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
        if self._redact_preview:
            self._render_redact_preview(force_update=True)
        if not self._redact_panel_open:
            self._toggle_redact_panel()
        self.page_ref.update()

    def _remove_redact_term(self, term: str) -> None:
        if term in self._redact_terms:
            self._redact_terms.remove(term)
        self._redact_term_matches.pop(term, None)
        self._redact_matches = self._flatten_matches()
        self._rebuild_redact_terms_list()
        if self._redact_preview:
            self._render_redact_preview(force_update=True)
        self.page_ref.update()

    def _rebuild_redact_terms_list(self) -> None:
        if self._redact_terms_list is None:
            return
        _HDR = "#E65100"
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
        # update color dots in terms list
        self._rebuild_redact_terms_list()
        # re-render preview with new color
        if self._redact_preview:
            self._render_redact_preview(force_update=True)

    # ── preview ───────────────────────────────────────────────────────────────

    def _render_redact_preview(self, *, force_update: bool = False) -> None:
        affected: set[int] = set()
        for pn in range(len(self._redact_overlays)):
            ov = self._redact_overlays[pn]
            if ov.visible or ov.controls:
                ov.visible  = False
                ov.controls = []
                affected.add(pn)

        if self._redact_preview and self._redact_matches:
            scale  = self.zoom * BASE_SCALE
            color  = getattr(self, "_redact_box_color", "#000000")
            # Semi-transparent fill: color + "88" (53 % opacity) for preview
            fill   = color + "88"
            by_page: dict[int, list[fitz.Rect]] = {}
            for pn, rect, _ in self._redact_matches:
                by_page.setdefault(pn, []).append(rect)
            for pn, rects in by_page.items():
                if pn >= len(self._redact_overlays):
                    continue
                boxes: list[ft.Control] = [
                    ft.Container(
                        left=r.x0 * scale, top=r.y0 * scale,
                        width=max(2, r.width * scale),
                        height=max(2, r.height * scale),
                        bgcolor=fill,
                        border=ft.border.all(2, color),
                        tooltip="Zona a redactar",
                    )
                    for r in rects
                ]
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
            self._show_snack("Agrega al menos un término antes de aplicar la redacción")
            return
        color = getattr(self, "_redact_box_color", "#000000")
        r_f = int(color[1:3], 16) / 255
        g_f = int(color[3:5], 16) / 255
        b_f = int(color[5:7], 16) / 255
        fill = (r_f, g_f, b_f)

        affected_pages: set[int] = set()
        failed_apply: list[int] = []

        with self._doc_lock:
            # ── add annotations ───────────────────────────────────────────────
            for pn, rect, _ in self._redact_matches:
                # Explicit expansion: 2 pts on each side covers descenders/
                # ascenders and OCR bbox inaccuracies.
                r = fitz.Rect(rect.x0 - 2, rect.y0 - 2,
                              rect.x1 + 2, rect.y1 + 2)
                try:
                    self.doc[pn].add_redact_annot(
                        r, fill=fill, cross_out=False,
                    )
                    affected_pages.add(pn)
                except Exception:
                    pass

            # ── apply (permanently burns the fill into the content stream) ───
            for pn in affected_pages:
                page = self.doc[pn]
                try:
                    ok = page.apply_redacts(
                        images=fitz.PDF_REDACT_IMAGE_PIXELS
                    )
                    if not ok:
                        # apply_redacts returns False on failure (no exception)
                        failed_apply.append(pn)
                except Exception as ex:
                    # Fallback: try without image-pixel redaction
                    try:
                        page.apply_redacts()
                    except Exception:
                        failed_apply.append(pn)

            # ── draw a solid rect as a guaranteed visual cover ────────────────
            # apply_redacts modifies the content stream but on some PDFs the
            # result may not re-render immediately.  Drawing an opaque rect on
            # top ensures the area is always visually covered.
            for pn in affected_pages:
                page = self.doc[pn]
                by_page = [rect for _pn, rect, _ in self._redact_matches
                           if _pn == pn]
                for rect in by_page:
                    r = fitz.Rect(rect.x0 - 2, rect.y0 - 2,
                                  rect.x1 + 2, rect.y1 + 2)
                    try:
                        page.draw_rect(r, color=fill, fill=fill, width=0)
                    except Exception:
                        pass

        for pn in affected_pages:
            self._ocr_by_page.pop(pn, None)
            self._rendered.discard(pn)

        self._clear_redact_state()
        self._rebuild_scroll_content(scroll_back=False)

        if failed_apply:
            msg = (f"Redacción aplicada en {len(affected_pages)} página(s)"
                   f" ({len(failed_apply)} página(s) con problemas: "
                   f"{', '.join(str(p+1) for p in failed_apply)})")
        else:
            msg = f"Redacción aplicada en {len(affected_pages)} página(s)"
        self._show_snack(msg)
        self.page_ref.update()

    def _clear_redact_state(self) -> None:
        self._redact_matches      = []
        self._redact_terms        = []
        self._redact_term_matches = {}
        self._redact_preview      = False
        if self._redact_query_field is not None:
            self._redact_query_field.value = ""
        if self._redact_preview_btn is not None:
            self._redact_preview_btn.bgcolor    = None
            self._redact_preview_btn.icon_color = None
        if self._redact_terms_list is not None:
            self._rebuild_redact_terms_list()
        for ov in self._redact_overlays:
            ov.visible  = False
            ov.controls = []
