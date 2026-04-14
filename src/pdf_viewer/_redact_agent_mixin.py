"""Redaction search/apply and AI-agent chat panel for PDFViewerTab."""
from __future__ import annotations

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
        _REDACT_BG  = "#FFF8F0"
        _REDACT_HDR = "#E65100"

        self._redact_query_field = ft.TextField(
            hint_text="Texto a buscar…", dense=True, expand=True,
            on_submit=self._run_redact_search,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
        )
        self._redact_incl_ocr = ft.Switch(
            value=True, label="Incluir OCR",
            label_style=ft.TextStyle(size=12),
        )
        self._redact_results_list = ft.ListView(
            expand=True, spacing=4,
            padding=ft.padding.only(bottom=8),
            auto_scroll=False,
        )
        self._redact_replace_field = ft.TextField(
            hint_text="Reemplazar con… (vacío = caja negra)",
            dense=True, expand=True,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
        )
        self._redact_preview_btn = ft.IconButton(
            ft.Icons.PREVIEW_OUTLINED, icon_size=18,
            tooltip="Mostrar/ocultar vista previa en documento",
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
                    ft.Row(
                        [
                            self._redact_query_field,
                            ft.IconButton(ft.Icons.SEARCH, icon_size=18,
                                          tooltip="Buscar en el documento",
                                          on_click=self._run_redact_search),
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_incl_ocr,
                    ft.Text("Coincidencias:", size=11, color="#795548"),
                    ft.Container(self._redact_results_list, expand=True),
                    ft.Divider(height=1, color="#FFE0B2"),
                    ft.Row(
                        [self._redact_replace_field, self._redact_preview_btn],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.ElevatedButton(
                        "Aplicar redacción", icon=ft.Icons.EDIT_OFF,
                        color="#FFFFFF", bgcolor=_REDACT_HDR,
                        on_click=self._apply_redaction, expand=True,
                    ),
                ],
                spacing=6, expand=True,
            ),
            expand=True, visible=self._redact_panel_open,
        )
        self._redact_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.EDIT_OFF, size=18, color=_REDACT_HDR),
                            ft.Text("Redacción", size=14, weight=ft.FontWeight.W_600),
                            ft.Container(expand=True),
                            self._redact_collapse_btn,
                        ],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._redact_content_area,
                ],
                spacing=4, expand=self._redact_panel_open,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=_REDACT_BG,
            border=ft.border.only(top=ft.BorderSide(1, "#FFE0B2")),
            expand=self._redact_panel_open,
        )
        return self._redact_panel

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
        self._run_redact_search()

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

    def _run_redact_search(self, e=None) -> None:
        if self._redact_query_field is None or self._redact_results_list is None:
            return
        query = (self._redact_query_field.value or "").strip()
        if not query:
            self._show_snack("Escribe un término de búsqueda")
            return
        self._clear_redact_state(keep_query=True)

        matches: list[tuple[int, fitz.Rect, str]] = []
        with self._doc_lock:
            total = len(self.doc)
            for pn in range(total):
                page  = self.doc[pn]
                rects = page.search_for(query)
                for r in rects:
                    try:
                        label = page.get_textbox(r).strip()[:80]
                    except Exception:
                        label = query
                    matches.append((pn, fitz.Rect(r), label or query))

        if self._redact_incl_ocr is not None and self._redact_incl_ocr.value:
            q_lower = query.lower()
            for pn, result in self._ocr_by_page.items():
                for det in result.detections:
                    if q_lower in det.text.lower():
                        matches.append((pn, fitz.Rect(det.bbox), det.text[:80]))

        self._redact_matches = matches

        if not matches:
            self._redact_results_list.controls = [
                ft.Container(
                    ft.Text("Sin coincidencias", size=12, color="#795548", italic=True),
                    padding=ft.padding.all(8),
                )
            ]
        else:
            rows: list[ft.Control] = []
            for i, (pn, rect, label) in enumerate(matches):
                _pn = pn
                rows.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Text(f"Pág. {pn + 1}", size=11, color="#E65100",
                                        weight=ft.FontWeight.W_600, width=48),
                                ft.Text(label, size=11, expand=True, max_lines=2,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.IconButton(ft.Icons.MY_LOCATION, icon_size=14,
                                              tooltip="Ir a esta página",
                                              on_click=lambda ev, p=_pn: self._scroll_to_page(p)),
                            ],
                            spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.padding.symmetric(horizontal=6, vertical=4),
                        border_radius=6,
                        border=ft.border.all(1, "#FFE0B2"),
                        bgcolor="#FFFFFF",
                    )
                )
            self._redact_results_list.controls = rows

        if not self._redact_panel_open:
            self._toggle_redact_panel()
        else:
            try:
                self._redact_results_list.update()
            except Exception:
                pass
        self.page_ref.update()

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
            by_page: dict[int, list[fitz.Rect]] = {}
            for pn, rect, _ in self._redact_matches:
                by_page.setdefault(pn, []).append(rect)
            for pn, rects in by_page.items():
                if pn >= len(self._redact_overlays):
                    continue
                boxes: list[ft.Control] = [
                    ft.Container(
                        left=r.x0 * scale, top=r.y0 * scale,
                        width=max(2, r.width * scale), height=max(2, r.height * scale),
                        bgcolor="#33E6510030",
                        border=ft.border.all(2, "#E65100"),
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
            self._show_snack("Primero busca texto para redactar")
            return
        self._redact_preview = not self._redact_preview
        self._render_redact_preview(force_update=True)
        if self._redact_preview_btn is not None:
            self._redact_preview_btn.bgcolor    = _SELECTED_BG if self._redact_preview else None
            self._redact_preview_btn.icon_color = "#E65100"     if self._redact_preview else None
            try:
                self._redact_preview_btn.update()
            except Exception:
                pass

    def _apply_redaction(self, e=None) -> None:
        if not self._redact_matches:
            self._show_snack("Sin coincidencias para redactar — ejecuta una búsqueda primero")
            return
        replacement = ""
        if self._redact_replace_field is not None:
            replacement = (self._redact_replace_field.value or "").strip()

        affected_pages: set[int] = set()
        errors = 0
        with self._doc_lock:
            for pn, rect, _ in self._redact_matches:
                try:
                    page = self.doc[pn]
                    if replacement:
                        page.add_redact_annot(rect, text=replacement, fill=(1, 1, 1))
                    else:
                        page.add_redact_annot(rect, fill=(0, 0, 0))
                    affected_pages.add(pn)
                except Exception:
                    errors += 1
            for pn in affected_pages:
                try:
                    self.doc[pn].apply_redacts()
                except Exception:
                    errors += 1

        for pn in affected_pages:
            self._ocr_by_page.pop(pn, None)
            self._rendered.discard(pn)

        self._clear_redact_state()
        self._rebuild_scroll_content(scroll_back=False)

        msg = f"Redacción aplicada en {len(affected_pages)} página(s)"
        if errors:
            msg += f" ({errors} error(s))"
        self._show_snack(msg)
        self.page_ref.update()

    def _clear_redact_state(self, keep_query: bool = False) -> None:
        self._redact_matches = []
        self._redact_preview = False
        if not keep_query and self._redact_query_field is not None:
            self._redact_query_field.value = ""
        if self._redact_replace_field is not None:
            self._redact_replace_field.value = ""
        if self._redact_preview_btn is not None:
            self._redact_preview_btn.bgcolor    = None
            self._redact_preview_btn.icon_color = None
        if self._redact_results_list is not None:
            self._redact_results_list.controls = []
        for ov in self._redact_overlays:
            ov.visible  = False
            ov.controls = []
