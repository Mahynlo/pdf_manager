"""AI document-analysis agent panel and chat for PDFViewerTab."""
from __future__ import annotations

import json
import re
import threading

import flet as ft


def _format_agent_response(text: str) -> str:
    """Wrap JSON responses in a fenced code block for Markdown rendering."""
    stripped = text.strip()
    if stripped and stripped[0] in ('{', '[') and stripped[-1] in ('}', ']'):
        try:
            parsed = json.loads(stripped)
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            return f"```json\n{pretty}\n```"
        except Exception:
            pass
    return text


class _AgentMixin:
    """AI agent panel: provider config, chat bubbles, quick actions and redact callback."""

    # Category display: icon, background color, short label
    _CAT_DISPLAY: dict[str, tuple[str, str, str]] = {
        "nombre":          (ft.Icons.PERSON_OUTLINED,           "#1565C0", "Nombre"),
        "dni_id":          (ft.Icons.BADGE_OUTLINED,            "#E65100", "ID"),
        "dirección":       (ft.Icons.LOCATION_ON_OUTLINED,      "#2E7D32", "Dirección"),
        "teléfono":        (ft.Icons.PHONE_OUTLINED,            "#00695C", "Teléfono"),
        "email":           (ft.Icons.EMAIL_OUTLINED,            "#6A1B9A", "Email"),
        "cuenta_bancaria": (ft.Icons.ACCOUNT_BALANCE_OUTLINED,  "#B71C1C", "Banco"),
        "dato_médico":     (ft.Icons.MEDICAL_SERVICES_OUTLINED, "#AD1457", "Médico"),
        "contraseña":      (ft.Icons.KEY_OUTLINED,              "#C62828", "Contraseña"),
        "fecha_nacimiento":(ft.Icons.CAKE_OUTLINED,             "#4527A0", "F. Nac."),
        "otro":            (ft.Icons.LABEL_OUTLINED,            "onSurfaceVariant", "Otro"),
    }

    # ── sidebar panel builder ─────────────────────────────────────────────────

    def _build_agent_sidebar_panel(self) -> ft.Container:
        """Build the AI Agent panel — dedicated full-height section with Markdown chat."""
        _AGENT_BG   = ft.Colors.with_opacity(0.06, "#5C35C9")
        _AGENT_HDR  = "#5C35C9"
        _AGENT_LINE = "outlineVariant"
        _AGENT_SURF = ft.Colors.with_opacity(0.12, "#5C35C9")

        try:
            from agent.config import get_provider
            self._agent_provider_selected = get_provider()
        except Exception:
            self._agent_provider_selected = "gemini"

        # ── chat list ─────────────────────────────────────────────────────────
        self._agent_chat_list = ft.ListView(
            expand=True, spacing=8,
            padding=ft.padding.symmetric(horizontal=4, vertical=6),
            auto_scroll=True,
        )

        # ── input ─────────────────────────────────────────────────────────────
        self._agent_input = ft.TextField(
            hint_text="Pregunta sobre el documento…",
            dense=True, expand=True, shift_enter=True,
            on_submit=self._agent_send,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=20,
            filled=True,
            fill_color="surface",
            border_color=_AGENT_LINE,
            focused_border_color=_AGENT_HDR,
        )

        # ── api key field ─────────────────────────────────────────────────────
        self._agent_key_field = ft.TextField(
            hint_text="API Key…",
            dense=True, password=True, can_reveal_password=True, expand=True,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=8,
            border_color=_AGENT_LINE,
            focused_border_color=_AGENT_HDR,
        )

        # ── provider selector ─────────────────────────────────────────────────
        def _prov_btn(provider: str, label: str) -> ft.Container:
            is_sel = (self._agent_provider_selected == provider)
            return ft.Container(
                ft.Text(label, size=11, weight=ft.FontWeight.W_500,
                        color=_AGENT_HDR if is_sel else "onSurfaceVariant"),
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                border_radius=12,
                bgcolor=_AGENT_SURF if is_sel else None,
                border=ft.border.all(1, _AGENT_HDR if is_sel else "outlineVariant"),
                on_click=lambda e, p=provider: self._agent_select_provider(p),
                ink=True,
            )

        gemini_btn = _prov_btn("gemini", "Gemini")
        openai_btn = _prov_btn("openai", "OpenAI")
        self._agent_provider_btns = {"gemini": gemini_btn, "openai": openai_btn}

        # ── key status label ──────────────────────────────────────────────────
        self._agent_key_status = ft.Text("", size=10, color="onSurfaceVariant")
        self._update_agent_key_status()

        # ── config section ────────────────────────────────────────────────────
        self._agent_config_section = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Proveedor:", size=11, color="onSurfaceVariant"),
                            gemini_btn,
                            openai_btn,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            self._agent_key_field,
                            ft.IconButton(
                                ft.Icons.SAVE_ROUNDED, icon_size=18,
                                tooltip="Guardar API Key",
                                icon_color=_AGENT_HDR,
                                on_click=self._agent_save_key,
                                style=ft.ButtonStyle(padding=ft.padding.all(4)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._agent_key_status,
                ],
                spacing=6, tight=True,
            ),
            bgcolor=_AGENT_SURF,
            border_radius=8,
            padding=ft.padding.all(10),
            border=ft.border.all(1, _AGENT_LINE),
            visible=True,
        )

        # ── quick actions ─────────────────────────────────────────────────────
        _qbtn = ft.ButtonStyle(
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            text_style=ft.TextStyle(size=11),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        quick_actions = ft.Row(
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
        )

        # ── sensitivity selector ──────────────────────────────────────────────
        _SENS_COLORS = {"low": "#2E7D32", "medium": "#E65100", "high": "#C62828"}

        def _sens_btn(level: str, label: str) -> ft.Container:
            col    = _SENS_COLORS[level]
            is_sel = (getattr(self, "_agent_redact_sensitivity", "medium") == level)
            return ft.Container(
                ft.Text(label, size=10,
                        color="#FFFFFF" if is_sel else col,
                        weight=ft.FontWeight.W_500),
                bgcolor=col if is_sel else None,
                border_radius=8,
                border=ft.border.all(1, col),
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                on_click=lambda e, lv=level: self._agent_select_sensitivity(lv),
                ink=True,
            )

        s_low  = _sens_btn("low",    "Baja")
        s_med  = _sens_btn("medium", "Media")
        s_high = _sens_btn("high",   "Alta")
        self._agent_sensitivity_btns = {"low": s_low, "medium": s_med, "high": s_high}

        sensitivity_row = ft.Row(
            [
                ft.Text("Nivel de censura:", size=10, color="onSurfaceVariant"),
                s_low, s_med, s_high,
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── content area ──────────────────────────────────────────────────────
        self._agent_content_area = ft.Container(
            ft.Column(
                [
                    self._agent_config_section,
                    quick_actions,
                    sensitivity_row,
                    ft.Divider(height=1, color=_AGENT_LINE),
                    ft.Container(
                        self._agent_chat_list,
                        expand=True,
                        bgcolor="surface",
                        border_radius=10,
                        border=ft.border.all(1, _AGENT_LINE),
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
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

        # ── config toggle button ──────────────────────────────────────────────
        self._agent_config_toggle_btn = ft.IconButton(
            ft.Icons.SETTINGS_OUTLINED, icon_size=16,
            tooltip="Mostrar/ocultar configuración",
            icon_color=_AGENT_HDR,
            on_click=self._agent_toggle_config,
            style=ft.ButtonStyle(padding=ft.padding.all(4)),
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
                                icon_color="onSurfaceVariant",
                                on_click=self._agent_clear_chat,
                                style=ft.ButtonStyle(padding=ft.padding.all(4)),
                            ),
                            self._agent_config_toggle_btn,
                        ],
                        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
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

    def _toggle_agent_panel(self, e=None) -> None:
        pass

    # ── provider / key ────────────────────────────────────────────────────────

    def _agent_save_key(self, e=None) -> None:
        from agent.config import get_provider, set_api_key
        key = (self._agent_key_field.value or "").strip()
        if not key:
            self._show_snack("Introduce una API Key válida")
            return
        provider = self._agent_provider_selected or get_provider()
        set_api_key(provider, key)
        self._agent_key_field.value = ""
        self._agent_instance = None
        self._show_snack(f"API Key guardada para {provider.capitalize()}")
        self._update_agent_key_status()
        try:
            self._agent_key_field.update()
        except Exception:
            pass

    def _agent_get_or_create(self):
        if self._agent_instance is not None:
            return self._agent_instance
        from agent.config import get_api_key, get_provider, get_model
        from agent.pdf_agent import PDFAgent
        provider = self._agent_provider_selected or get_provider()
        key      = get_api_key(provider)
        if not key:
            key = (self._agent_key_field.value or "").strip()
        if not key:
            raise ValueError(
                f"No hay API Key para {provider.capitalize()}. "
                "Introdúcela en la sección de configuración del agente."
            )
        self._agent_instance = PDFAgent(
            pdf_path=self.path,
            api_key=key,
            provider=provider,
            model=get_model(provider),
            redact_callback=self._agent_redact_callback,
            ocr_overrides=self._build_ocr_overrides(),
        )
        return self._agent_instance

    def _update_agent_key_status(self) -> None:
        if self._agent_key_status is None:
            return
        try:
            from agent.config import get_api_key, get_provider
            provider = getattr(self, "_agent_provider_selected", None) or get_provider()
            key = get_api_key(provider)
            if key:
                self._agent_key_status.value = f"✓ Clave configurada ({provider.capitalize()})"
                self._agent_key_status.color = "#2E7D32"
            else:
                self._agent_key_status.value = f"✗ Sin clave para {provider.capitalize()}"
                self._agent_key_status.color = "#C62828"
        except Exception:
            self._agent_key_status.value = "Módulo de agente no disponible"
            self._agent_key_status.color = "onSurfaceVariant"
        try:
            self._agent_key_status.update()
        except Exception:
            pass

    def _agent_select_provider(self, provider: str) -> None:
        _AGENT_HDR  = "#5C35C9"
        _AGENT_SURF = ft.Colors.with_opacity(0.12, "#5C35C9")
        self._agent_provider_selected = provider
        self._agent_instance = None
        for p, btn in self._agent_provider_btns.items():
            is_sel = (p == provider)
            btn.bgcolor = _AGENT_SURF if is_sel else None
            btn.border  = ft.border.all(1, _AGENT_HDR if is_sel else "outlineVariant")
            if isinstance(btn.content, ft.Text):
                btn.content.color = _AGENT_HDR if is_sel else "onSurfaceVariant"
            try:
                btn.update()
            except Exception:
                pass
        self._update_agent_key_status()

    def _agent_toggle_config(self, e=None) -> None:
        if self._agent_config_section is None:
            return
        self._agent_config_section.visible = not self._agent_config_section.visible
        if self._agent_config_toggle_btn is not None:
            self._agent_config_toggle_btn.icon_color = (
                "#5C35C9" if self._agent_config_section.visible else "onSurfaceVariant"
            )
            try:
                self._agent_config_toggle_btn.update()
            except Exception:
                pass
        try:
            self._agent_config_section.update()
        except Exception:
            pass

    # ── sensitivity ───────────────────────────────────────────────────────────

    def _agent_select_sensitivity(self, level: str) -> None:
        self._agent_redact_sensitivity = level
        _COLORS = {"low": "#2E7D32", "medium": "#E65100", "high": "#C62828"}
        for lv, btn in self._agent_sensitivity_btns.items():
            is_sel = (lv == level)
            col = _COLORS[lv]
            btn.bgcolor = col if is_sel else None
            if isinstance(btn.content, ft.Text):
                btn.content.color = "#FFFFFF" if is_sel else col
            try:
                btn.update()
            except Exception:
                pass

    # ── chat bubbles ──────────────────────────────────────────────────────────

    def _agent_append_bubble(self, role: str, text: str) -> None:
        _AGENT_HDR = "#5C35C9"
        is_user    = role == "user"

        if is_user:
            body: ft.Control = ft.Text(
                text, size=12, selectable=True, color="onSurface",
            )
        else:
            body = ft.Markdown(
                _format_agent_response(text),
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme="github",
                on_tap_link=lambda e: self.page_ref.launch_url(e.data),
            )

        avatar = ft.Container(
            ft.Icon(
                ft.Icons.PERSON_ROUNDED if is_user else ft.Icons.AUTO_AWESOME_ROUNDED,
                size=13, color="#FFFFFF",
            ),
            bgcolor="#3949AB" if is_user else _AGENT_HDR,
            border_radius=10,
            width=26, height=26,
            alignment=ft.alignment.center,
        )

        bubble = ft.Container(
            content=body,
            bgcolor=ft.Colors.with_opacity(0.15, "#3949AB") if is_user else "surfaceVariant",
            border_radius=ft.border_radius.only(
                top_left=12, top_right=12,
                bottom_left=2  if is_user else 12,
                bottom_right=12 if is_user else 2,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border=ft.border.all(1, "outlineVariant" if is_user else "outlineVariant"),
            expand=True,
        )

        if is_user:
            row = ft.Row(
                [ft.Container(width=20), bubble, avatar],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        else:
            row = ft.Row(
                [avatar, bubble, ft.Container(width=20)],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )

        if self._agent_chat_list is not None:
            self._agent_chat_list.controls.append(row)
            try:
                self._agent_chat_list.update()
            except Exception:
                pass

    def _agent_clear_chat(self, e=None) -> None:
        self._agent_history = []
        if self._agent_chat_list is not None:
            self._agent_chat_list.controls = []
            try:
                self._agent_chat_list.update()
            except Exception:
                pass

    # ── redact callback ───────────────────────────────────────────────────────

    def _find_regex_instances(self, pattern: str, case_sensitive: bool) -> list[str]:
        """Run a regex over all page texts and return unique literal matches (max 10)."""
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            return []
        found: set[str] = set()
        with self._doc_lock:
            for pn in range(len(self.doc)):
                for m in compiled.finditer(self.doc[pn].get_text("text")):
                    val = m.group(0).strip()
                    if val:
                        found.add(val)
                    if len(found) >= 10:
                        break
                if len(found) >= 10:
                    break
        return sorted(found)

    def _agent_redact_callback(self, terms: list[dict]) -> None:
        """Display redaction suggestion chips with category badge and motivo tooltip."""
        if not terms or self._agent_chat_list is None:
            return

        _WARN          = "#E65100"
        case_sensitive = getattr(self, "_redact_case_sensitive", True)

        enriched: list[dict] = []
        for rec in terms[:30]:
            texto  = (rec.get("texto") or "").strip()
            cat    = rec.get("categoria", "otro")
            motivo = rec.get("motivo", "")
            tipo   = rec.get("tipo", "literal")
            if not texto:
                continue
            if tipo == "patron":
                instances = self._find_regex_instances(texto, case_sensitive)
                for inst in instances:
                    enriched.append({
                        "texto": inst, "categoria": cat,
                        "motivo": f"(patrón: {texto})" + (f" {motivo}" if motivo else ""),
                        "count": len(self._find_term_matches(inst, case_sensitive)),
                    })
            else:
                enriched.append({
                    "texto": texto, "categoria": cat, "motivo": motivo,
                    "count": len(self._find_term_matches(texto, case_sensitive)),
                })

        if not enriched:
            return

        chips: list[ft.Control] = []
        for item in enriched:
            texto  = item["texto"]
            cat    = item["categoria"]
            motivo = item.get("motivo", "")
            count  = item["count"]

            icon, cat_color, cat_label = self._CAT_DISPLAY.get(
                cat, self._CAT_DISPLAY["otro"]
            )

            if count == 0:
                count_label = "no hallada"
                count_color = "onSurfaceVariant"
                count_bg    = "surfaceVariant"
                text_color  = "onSurfaceVariant"
            elif count == 1:
                count_label = "1 coincid."
                count_color = _WARN
                count_bg    = ft.Colors.with_opacity(0.15, "#E65100")
                text_color  = "onSurface"
            else:
                count_label = f"{count} coincid."
                count_color = _WARN
                count_bg    = ft.Colors.with_opacity(0.15, "#E65100")
                text_color  = "onSurface"

            chips.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(
                                ft.Row(
                                    [
                                        ft.Icon(icon, size=9, color="#FFFFFF"),
                                        ft.Text(cat_label, size=9, color="#FFFFFF",
                                                weight=ft.FontWeight.W_500),
                                    ],
                                    spacing=2, tight=True,
                                ),
                                bgcolor=cat_color, border_radius=3,
                                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                            ),
                            ft.Text(
                                texto, size=11, expand=True,
                                overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                                color=text_color,
                            ),
                            ft.Container(
                                ft.Text(count_label, size=9,
                                        color=count_color, weight=ft.FontWeight.W_500),
                                bgcolor=count_bg, border_radius=4,
                                padding=ft.padding.symmetric(horizontal=5, vertical=2),
                            ),
                            ft.IconButton(
                                ft.Icons.ADD_CIRCLE_OUTLINE, icon_size=16,
                                tooltip=(
                                    f"Agregar a censura\n{motivo}" if motivo
                                    else "Agregar a la lista de censura"
                                ),
                                icon_color=_WARN if count > 0 else "outlineVariant",
                                disabled=(count == 0),
                                on_click=lambda e, _t=texto: self._agent_apply_redaction_term(_t),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="surface",
                    border_radius=6,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border=ft.border.all(1, "outlineVariant" if count > 0 else "outlineVariant"),
                    tooltip=motivo or None,
                )
            )

        found_items = [i for i in enriched if i["count"] > 0]
        header_controls: list[ft.Control] = [
            ft.Text(
                "Sugerencias de censura:", size=11,
                weight=ft.FontWeight.W_600, color=_WARN, expand=True,
            ),
        ]
        if len(found_items) > 1:
            _texts = [i["texto"] for i in found_items]
            header_controls.append(
                ft.TextButton(
                    "Agregar todos",
                    icon=ft.Icons.PLAYLIST_ADD,
                    style=ft.ButtonStyle(
                        color=_WARN,
                        padding=ft.padding.symmetric(horizontal=4, vertical=0),
                        text_style=ft.TextStyle(size=11),
                    ),
                    on_click=lambda e, ts=_texts: self._agent_add_all_redact_terms(ts),
                )
            )

        self._agent_chat_list.controls.append(
            ft.Container(
                ft.Column(
                    [
                        ft.Row(header_controls,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        *chips,
                    ],
                    spacing=4,
                ),
                bgcolor=ft.Colors.with_opacity(0.06, "#E65100"), border_radius=8,
                padding=ft.padding.all(10),
                border=ft.border.all(1, "outlineVariant"),
            )
        )
        try:
            self._agent_chat_list.update()
        except Exception:
            pass

    def _agent_apply_redaction_term(self, term: str) -> None:
        if self._redact_query_field is not None:
            self._redact_query_field.value = term
        if hasattr(self, "_switch_sidebar_mode"):
            self._switch_sidebar_mode("redact")
        self._add_redact_term()

    def _agent_add_all_redact_terms(self, terms: list[str]) -> None:
        # Cache de texto local al lote (ver _search_phrase): reutiliza el texto
        # de cada página entre todos los términos en vez de re-extraerlo por cada uno.
        _text_cache: dict = {}
        added = 0
        for term in terms:
            if term not in self._redact_terms:
                self._add_term_direct(term, text_cache=_text_cache)
                added += 1
        if added:
            self._rebuild_redact_terms_list()
            self._update_profile_save_btn()
            if self._redact_preview:
                self._render_redact_preview(force_update=True)
            self._show_snack(f"{added} término(s) agregados a la lista de censura")
            try:
                self.page_ref.update()
            except Exception:
                pass

    # ── send / quick actions ──────────────────────────────────────────────────

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
                    sensitivity = getattr(self, "_agent_redact_sensitivity", "medium")
                    reply = agent.suggest_redactions(sensitivity)
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
