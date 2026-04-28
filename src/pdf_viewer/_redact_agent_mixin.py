"""Redaction search/apply and AI-agent chat panel for PDFViewerTab."""
from __future__ import annotations

import json
import re
import string
import threading

import flet as ft
import fitz

from ._censorship_profiles import get_profile_manager, CensorshipProfile


# ── response formatter ────────────────────────────────────────────────────────

def _format_agent_response(text: str) -> str:
    """Wrap JSON responses in a fenced code block for Markdown rendering.

    If *text* looks like a JSON object or array (starts/ends with {}/[]),
    it is pretty-printed and returned inside a ```json fence so that
    ft.Markdown renders it with syntax highlighting.  Plain Markdown text
    is returned unchanged.
    """
    stripped = text.strip()
    if stripped and stripped[0] in ('{', '[') and stripped[-1] in ('}', ']'):
        try:
            parsed = json.loads(stripped)
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            return f"```json\n{pretty}\n```"
        except Exception:
            pass
    return text

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

    def _build_agent_sidebar_panel(self) -> ft.Container:
        """Build the AI Agent panel — dedicated full-height section with Markdown chat."""
        _AGENT_BG   = "#F3F0FF"
        _AGENT_HDR  = "#5C35C9"
        _AGENT_LINE = "#D1C4E9"

        # ── chat list ─────────────────────────────────────────────────────────
        self._agent_chat_list = ft.ListView(
            expand=True, spacing=10,
            padding=ft.padding.symmetric(horizontal=6, vertical=8),
            auto_scroll=True,
        )

        # ── input ─────────────────────────────────────────────────────────────
        self._agent_input = ft.TextField(
            hint_text="Pregunta sobre el documento…",
            dense=True, expand=True, shift_enter=True,
            on_submit=self._agent_send,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_radius=20,
            filled=True,
            fill_color="#FFFFFF",
            border_color=_AGENT_LINE,
            focused_border_color=_AGENT_HDR,
        )

        # ── api key ───────────────────────────────────────────────────────────
        self._agent_key_field = ft.TextField(
            hint_text="API Key (Google Gemini u OpenAI)",
            dense=True, password=True, can_reveal_password=True, expand=True,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_color=_AGENT_LINE,
            focused_border_color=_AGENT_HDR,
        )

        _qbtn = ft.ButtonStyle(
            padding=ft.padding.symmetric(horizontal=6, vertical=4),
            text_style=ft.TextStyle(size=11),
        )

        # ── content area ──────────────────────────────────────────────────────
        self._agent_content_area = ft.Container(
            ft.Column(
                [
                    # API key row
                    ft.Row(
                        [
                            self._agent_key_field,
                            ft.IconButton(
                                ft.Icons.KEY, icon_size=18,
                                tooltip="Guardar API Key",
                                icon_color=_AGENT_HDR,
                                on_click=self._agent_save_key,
                            ),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # Quick action buttons
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "Resumir", icon=ft.Icons.SUMMARIZE_OUTLINED,
                                style=_qbtn,
                                on_click=lambda e: self._agent_quick(
                                    "Genera un resumen completo del documento.",
                                    direct_action="summarize",
                                ),
                            ),
                            ft.OutlinedButton(
                                "Estructura", icon=ft.Icons.ACCOUNT_TREE_OUTLINED,
                                style=_qbtn,
                                on_click=lambda e: self._agent_quick(
                                    "Analiza la estructura y el tipo de este documento.",
                                    direct_action="analyze",
                                ),
                            ),
                            ft.OutlinedButton(
                                "Censurar", icon=ft.Icons.EDIT_OFF_OUTLINED,
                                style=_qbtn,
                                on_click=lambda e: self._agent_quick(
                                    "Identifica la información sensible que debería censurarse.",
                                    direct_action="redact",
                                ),
                            ),
                        ],
                        spacing=4, wrap=True,
                    ),
                    ft.Divider(height=1, color=_AGENT_LINE),
                    # Chat bubble area — fills all remaining height
                    ft.Container(
                        self._agent_chat_list,
                        expand=True,
                        bgcolor="#FAFAFA",
                        border_radius=8,
                        border=ft.border.all(1, _AGENT_LINE),
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    # Input row
                    ft.Row(
                        [
                            self._agent_input,
                            ft.IconButton(
                                ft.Icons.SEND_ROUNDED, icon_size=20,
                                tooltip="Enviar (Enter)",
                                icon_color=_AGENT_HDR,
                                on_click=self._agent_send,
                                style=ft.ButtonStyle(padding=ft.padding.all(6)),
                            ),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8, expand=True,
            ),
            expand=True,
            padding=ft.padding.only(top=6),
        )

        # ── panel container ───────────────────────────────────────────────────
        self._agent_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SMART_TOY_ROUNDED, size=18, color=_AGENT_HDR),
                            ft.Text(
                                "Agente IA",
                                size=14, weight=ft.FontWeight.W_600, color=_AGENT_HDR,
                            ),
                            ft.Container(expand=True),
                            ft.IconButton(
                                ft.Icons.DELETE_SWEEP_OUTLINED, icon_size=16,
                                tooltip="Limpiar conversación",
                                icon_color="#9E9E9E",
                                on_click=self._agent_clear_chat,
                                style=ft.ButtonStyle(padding=ft.padding.all(4)),
                            ),
                        ],
                        spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._agent_content_area,
                ],
                spacing=4, expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=_AGENT_BG,
            expand=True,
        )
        return self._agent_panel

    # ── panel collapse (no-ops — collapse handled by sidebar tab switching) ────

    def _toggle_redact_panel(self, e=None) -> None:
        pass

    def _toggle_agent_panel(self, e=None) -> None:
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
                                tooltip="Buscar para censurar",
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
                    ft.Text("Términos sugeridos para censurar:", size=11,
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
        # Switch to redaction view so the redaction panel is visible
        if hasattr(self, "_switch_sidebar_mode"):
            self._switch_sidebar_mode("redact")
        self._add_redact_term()

    def _agent_append_bubble(self, role: str, text: str) -> None:
        _AGENT_HDR = "#5C35C9"
        is_user    = role == "user"

        if is_user:
            body: ft.Control = ft.Text(
                text, size=12, selectable=True, color="#1A237E",
            )
        else:
            # Render assistant response as Markdown (JSON auto-wrapped in code block)
            body = ft.Markdown(
                _format_agent_response(text),
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme="github",
                on_tap_link=lambda e: self.page_ref.launch_url(e.data),
            )

        bubble = ft.Container(
            content=body,
            bgcolor="#E8EAF6" if is_user else "#FFFFFF",
            border_radius=ft.border_radius.only(
                top_left=12, top_right=12,
                bottom_left=2  if is_user else 12,
                bottom_right=12 if is_user else 2,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            margin=ft.margin.only(
                left=32 if is_user else 0,
                right=0  if is_user else 32,
            ),
            border=ft.border.all(1, "#C5CAE9" if is_user else "#E0E0E0"),
        )
        if self._agent_chat_list is not None:
            self._agent_chat_list.controls.append(bubble)
            try:
                self._agent_chat_list.update()
            except Exception:
                pass

    def _agent_clear_chat(self, e=None) -> None:
        """Clear all visible bubbles and reset conversation history."""
        self._agent_history = []
        if self._agent_chat_list is not None:
            self._agent_chat_list.controls = []
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
        # Switch to agent view and ensure sidebar is open
        if hasattr(self, "_switch_sidebar_mode"):
            self._switch_sidebar_mode("agent")
        elif not self._sidebar_visible:
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
        if self._redact_terms_list is None: # si la liesta de términos a redactar no se ha inicializado
            return
        _HDR = "#E65100" # color de fondo para el contador de coincidencias en cada término
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
                        tooltip="Zona a censurar",
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
        if not self._redact_matches: # si no ay fraces a redactar no se puede aplicar la redacción
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
            # ── añadir anotaciones ───────────────────────────────────────────────
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
            if pn in self._ocr_by_page:
                # Only remove OCR detections/segments that overlap with the
                # redacted areas; keep the rest so the user can keep working
                # with non-redacted OCR text on the same page.
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
            self._page_words.pop(pn, None)  # flush cached words for this page
            self._rendered.discard(pn)

        self._clear_redact_state()
        self._rebuild_scroll_content(scroll_back=False)

        if failed_apply:
            msg = (f"Censura aplicada en {len(affected_pages)} página(s)"
                   f" ({len(failed_apply)} página(s) con problemas: "
                   f"{', '.join(str(p+1) for p in failed_apply)})")
        else:
            msg = f"Censura aplicada en {len(affected_pages)} página(s)"
        # Refresh OCR sidebar so it reflects surviving detections (or shows
        # "sin ejecutar" only when all OCR data for the current page was redacted).
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
            ov.visible  = False
            ov.controls = []

    # ── censorship profiles ───────────────────────────────────────────────────

    _REDACT_HDR  = "#E65100"
    _SECTION_CLR = "#795548"

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
        # Update button label depending on whether there's an active profile
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

    # ── profile manager dialog ────────────────────────────────────────────────

    def _open_profile_manager(self, e=None) -> None:
        _HDR = self._REDACT_HDR

        self._profile_search_field = ft.TextField(
            hint_text="Buscar perfil…",
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            border_radius=8,
            border_color="#FFCCBC",
            focused_border_color=_HDR,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            on_change=lambda e: self._filter_profiles(),
        )
        self._profile_list_view = ft.ListView(spacing=2, padding=ft.padding.only(top=4))
        self._rebuild_profile_list()

        self._profile_mgr_dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.FOLDER_SPECIAL_OUTLINED, color=_HDR, size=20),
                    ft.Text("Perfiles de Censura", size=15, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    ft.IconButton(
                        ft.Icons.ADD_CIRCLE_OUTLINE, icon_size=20,
                        tooltip="Crear nuevo perfil",
                        icon_color=_HDR,
                        on_click=lambda e: self._open_create_profile_dialog(),
                        style=ft.ButtonStyle(padding=ft.padding.all(4)),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
            ),
            content=ft.Container(
                ft.Column(
                    [
                        self._profile_search_field,
                        ft.Container(
                            self._profile_list_view,
                            height=300,
                            width=400,
                            border=ft.border.all(1, "#FFE0B2"),
                            border_radius=8,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=420,
                padding=ft.padding.only(top=4),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda e: self.page_ref.close(self._profile_mgr_dlg),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page_ref.open(self._profile_mgr_dlg)

    def _filter_profiles(self) -> None:
        self._rebuild_profile_list(
            (self._profile_search_field.value or "") if self._profile_search_field else ""
        )
        try:
            self._profile_list_view.update()
        except Exception:
            pass

    def _rebuild_profile_list(self, query: str = "") -> None:
        mgr      = get_profile_manager()
        profiles = mgr.search(query)
        _HDR     = self._REDACT_HDR
        _SEC     = self._SECTION_CLR

        if not profiles:
            self._profile_list_view.controls = [
                ft.Container(
                    ft.Text(
                        "No hay perfiles. Crea uno con el botón ＋" if not query
                        else "Sin resultados para esa búsqueda.",
                        size=12, color="#9E9E9E", italic=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=ft.padding.all(24),
                    alignment=ft.alignment.center,
                )
            ]
            return

        tiles: list[ft.Control] = []
        for idx, p in enumerate(profiles):
            n    = len(p.terms)
            is_active = self._active_profile is not None and self._active_profile.id == p.id
            tile = ft.Container(
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(
                                            p.name, size=13,
                                            weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500,
                                            color=_HDR if is_active else "#4E342E",
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                            max_lines=1, expand=True,
                                        ),
                                        *(
                                            [ft.Container(
                                                ft.Text("activo", size=9, color="#FFFFFF"),
                                                bgcolor=_HDR, border_radius=4,
                                                padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                            )]
                                            if is_active else []
                                        ),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Text(
                                    f"{n} término{'s' if n != 1 else ''}",
                                    size=11, color="#9E9E9E",
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                        ft.Row(
                            [
                                ft.IconButton(
                                    ft.Icons.EDIT_OUTLINED, icon_size=16,
                                    tooltip="Editar perfil",
                                    icon_color=_SEC,
                                    on_click=lambda e, pid=p.id: self._open_create_profile_dialog(pid),
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                                ft.IconButton(
                                    ft.Icons.FILE_DOWNLOAD_OUTLINED, icon_size=16,
                                    tooltip="Cargar este perfil en la sesión",
                                    icon_color=_HDR,
                                    on_click=lambda e, pid=p.id: self._load_profile(pid),
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                                ft.IconButton(
                                    ft.Icons.DELETE_OUTLINE, icon_size=16,
                                    tooltip="Eliminar perfil",
                                    icon_color="#D32F2F",
                                    on_click=lambda e, pid=p.id, pname=p.name: self._confirm_delete_profile(pid, pname),
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                border_radius=6,
                bgcolor="#FFF3E0" if is_active else ("#FFFFFF" if idx % 2 == 0 else "#FFF8F0"),
                border=ft.border.all(1, _HDR) if is_active else None,
            )
            tiles.append(tile)

        self._profile_list_view.controls = tiles

    # ── create / edit profile dialog ──────────────────────────────────────────

    def _open_create_profile_dialog(
        self,
        profile_id: str | None = None,
        initial_terms: list[str] | None = None,
    ) -> None:
        _HDR = self._REDACT_HDR
        _SEC = self._SECTION_CLR

        try:
            self.page_ref.close(self._profile_mgr_dlg)
        except Exception:
            pass

        mgr      = get_profile_manager()
        existing = mgr.get(profile_id) if profile_id else None
        self._profile_editing_id = profile_id
        if profile_id is not None:
            self._profile_edit_terms = list(existing.terms) if existing else []
        elif initial_terms is not None:
            self._profile_edit_terms = list(initial_terms)
        else:
            self._profile_edit_terms = []

        self._profile_edit_name = ft.TextField(
            label="Nombre del perfil",
            value=existing.name if existing else "",
            hint_text="Ej: PII – Datos personales",
            dense=True,
            border_color="#FFCCBC",
            focused_border_color=_HDR,
        )
        self._profile_edit_term_input = ft.TextField(
            hint_text="Agregar término…",
            dense=True, expand=True,
            border_color="#FFCCBC",
            focused_border_color=_HDR,
            on_submit=self._profile_dlg_add_term,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )
        self._profile_edit_terms_list = ft.ListView(spacing=4, height=160)
        self._rebuild_edit_terms_list()

        has_session_terms = bool(self._redact_terms)

        def _go_back(e=None):
            try:
                self.page_ref.close(self._profile_edit_dlg)
            except Exception:
                pass
            self._open_profile_manager()

        def _save(e=None):
            # Auto-add any term that's typed but not yet confirmed with Add
            pending = (self._profile_edit_term_input.value or "").strip()
            if pending and pending not in self._profile_edit_terms:
                self._profile_edit_terms.append(pending)
                self._profile_edit_term_input.value = ""
                self._rebuild_edit_terms_list()

            name = (self._profile_edit_name.value or "").strip()
            if not name:
                self._profile_edit_name.error_text = "El nombre es obligatorio"
                try:
                    self._profile_edit_name.update()
                except Exception:
                    pass
                return
            if self._profile_editing_id:
                mgr.update(
                    self._profile_editing_id,
                    name=name,
                    terms=self._profile_edit_terms,
                )
                if self._active_profile and self._active_profile.id == self._profile_editing_id:
                    self._active_profile = mgr.get(self._profile_editing_id)
                    self._update_profile_label()
                    self._update_profile_save_btn()
            else:
                mgr.create(
                    name, self._profile_edit_terms,
                    color=self._redact_box_color,
                    case_sensitive=self._redact_case_sensitive,
                )
            try:
                self.page_ref.close(self._profile_edit_dlg)
            except Exception:
                pass
            self._show_snack(f"Perfil «{name}» guardado")
            self._open_profile_manager()

        import_btn = ft.TextButton(
            "← Importar términos de la sesión actual",
            icon=ft.Icons.DOWNLOAD_OUTLINED,
            on_click=self._profile_import_session_terms,
            visible=has_session_terms,
            style=ft.ButtonStyle(
                color=_SEC,
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                text_style=ft.TextStyle(size=11),
            ),
        )
        self._profile_import_btn = import_btn

        self._profile_edit_dlg = ft.AlertDialog(
            title=ft.Text(
                "Editar perfil" if existing else "Nuevo perfil",
                size=15, weight=ft.FontWeight.W_600,
            ),
            content=ft.Container(
                ft.Column(
                    [
                        self._profile_edit_name,
                        ft.Divider(height=1, color="#FFE0B2"),
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.LIST_ALT_OUTLINED, size=13, color=_SEC),
                                ft.Text(
                                    "Términos a censurar", size=11,
                                    weight=ft.FontWeight.W_600, color=_SEC,
                                ),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            [
                                self._profile_edit_term_input,
                                ft.IconButton(
                                    ft.Icons.ADD, icon_size=18, icon_color=_HDR,
                                    tooltip="Agregar término",
                                    on_click=self._profile_dlg_add_term,
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Container(
                            self._profile_edit_terms_list,
                            border=ft.border.all(1, "#FFE0B2"),
                            border_radius=8,
                            padding=ft.padding.all(4),
                        ),
                        import_btn,
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=400,
                padding=ft.padding.only(top=4),
            ),
            actions=[
                ft.TextButton("← Volver", on_click=_go_back),
                ft.FilledButton(
                    "Guardar", icon=ft.Icons.SAVE_OUTLINED,
                    style=ft.ButtonStyle(bgcolor=_HDR),
                    on_click=_save,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page_ref.open(self._profile_edit_dlg)

    def _rebuild_edit_terms_list(self) -> None:
        _HDR = self._REDACT_HDR

        if not self._profile_edit_terms:
            self._profile_edit_terms_list.controls = [
                ft.Container(
                    ft.Text("Sin términos", size=11, color="#9E9E9E", italic=True),
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                )
            ]
            return

        chips: list[ft.Control] = []
        for i, term in enumerate(self._profile_edit_terms):
            chips.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(width=8, height=8, bgcolor=_HDR, border_radius=4),
                            ft.Text(
                                term, size=12, expand=True,
                                overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                                color="#4E342E",
                            ),
                            ft.IconButton(
                                ft.Icons.CLOSE, icon_size=14,
                                tooltip="Quitar",
                                icon_color="#9E9E9E",
                                on_click=lambda e, idx=i: self._profile_dlg_remove_term(idx),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=6,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, "#FFCCBC"),
                )
            )
        self._profile_edit_terms_list.controls = chips

    def _profile_dlg_add_term(self, e=None) -> None:
        term = (self._profile_edit_term_input.value or "").strip()
        if not term or term in self._profile_edit_terms:
            return
        self._profile_edit_terms.append(term)
        self._profile_edit_term_input.value = ""
        self._rebuild_edit_terms_list()
        try:
            self._profile_edit_term_input.update()
            self._profile_edit_terms_list.update()
        except Exception:
            pass

    def _profile_dlg_remove_term(self, idx: int) -> None:
        if 0 <= idx < len(self._profile_edit_terms):
            self._profile_edit_terms.pop(idx)
            self._rebuild_edit_terms_list()
            try:
                self._profile_edit_terms_list.update()
            except Exception:
                pass

    def _profile_import_session_terms(self, e=None) -> None:
        for term in self._redact_terms:
            if term not in self._profile_edit_terms:
                self._profile_edit_terms.append(term)
        self._rebuild_edit_terms_list()
        try:
            self._profile_edit_terms_list.update()
        except Exception:
            pass
        if self._profile_import_btn is not None:
            self._profile_import_btn.visible = False
            try:
                self._profile_import_btn.update()
            except Exception:
                pass

    # ── load / save profile ───────────────────────────────────────────────────

    def _load_profile(self, profile_id: str) -> None:
        mgr     = get_profile_manager()
        profile = mgr.get(profile_id)
        if profile is None:
            return

        try:
            self.page_ref.close(self._profile_mgr_dlg)
        except Exception:
            pass

        # Clear current session
        self._redact_terms.clear()
        self._redact_term_matches.clear()
        self._redact_matches.clear()
        if self._redact_preview:
            for ov in self._redact_overlays:
                ov.visible  = False
                ov.controls = []
            self._redact_preview = False

        # Apply profile settings
        self._redact_case_sensitive = profile.case_sensitive
        if self._redact_case_btn is not None:
            if self._redact_case_sensitive:
                self._redact_case_btn.icon    = ft.Icons.FONT_DOWNLOAD_OUTLINED
                self._redact_case_btn.bgcolor = "#FFE0B2"
                self._redact_case_btn.tooltip = "Distinguir mayúsculas (activo = sí)"
            else:
                self._redact_case_btn.icon    = ft.Icons.FONT_DOWNLOAD_OFF_OUTLINED
                self._redact_case_btn.bgcolor = None
                self._redact_case_btn.tooltip = "Ignorar mayúsculas (activo = no)"
            try:
                self._redact_case_btn.update()
            except Exception:
                pass

        if profile.color in self._redact_color_btns:
            self._select_redact_color(profile.color)

        # Load terms
        for term in profile.terms:
            self._add_term_direct(term)

        self._active_profile = profile
        self._rebuild_redact_terms_list()
        self._update_profile_label()
        self._update_profile_save_btn()
        try:
            self.page_ref.update()
        except Exception:
            pass

        n = len(profile.terms)
        found = len(self._redact_terms)
        if found < n:
            self._show_snack(
                f"Perfil «{profile.name}» cargado — "
                f"{found}/{n} términos encontrados en el documento"
            )
        else:
            self._show_snack(f"Perfil «{profile.name}» cargado ({found} términos)")

    def _save_current_as_profile(self, e=None) -> None:
        if not self._redact_terms:
            self._show_snack("No hay términos en la sesión actual")
            return

        if self._active_profile is not None:
            mgr = get_profile_manager()
            mgr.update(self._active_profile.id, terms=list(self._redact_terms))
            self._active_profile = mgr.get(self._active_profile.id)
            self._update_profile_save_btn()
            self._show_snack(f"Perfil «{self._active_profile.name}» actualizado")
        else:
            self._open_create_profile_dialog(initial_terms=list(self._redact_terms))

    def _confirm_delete_profile(self, profile_id: str, name: str) -> None:
        def _do_delete(e):
            try:
                self.page_ref.close(confirm_dlg)
            except Exception:
                pass
            mgr = get_profile_manager()
            mgr.delete(profile_id)
            if self._active_profile and self._active_profile.id == profile_id:
                self._active_profile = None
                self._update_profile_label()
                self._update_profile_save_btn()
            self._show_snack(f"Perfil «{name}» eliminado")
            self._rebuild_profile_list(
                (self._profile_search_field.value or "") if self._profile_search_field else ""
            )
            try:
                self._profile_list_view.update()
            except Exception:
                pass

        confirm_dlg = ft.AlertDialog(
            title=ft.Text("Eliminar perfil"),
            content=ft.Text(
                f'¿Eliminar el perfil «{name}»?\nEsta acción no se puede deshacer.',
                size=13,
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda e: self.page_ref.close(confirm_dlg),
                ),
                ft.FilledButton(
                    "Eliminar",
                    style=ft.ButtonStyle(bgcolor="#D32F2F"),
                    on_click=_do_delete,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page_ref.open(confirm_dlg)
