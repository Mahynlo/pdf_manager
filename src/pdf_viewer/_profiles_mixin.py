"""Censorship profile management dialogs for PDFViewerTab."""
from __future__ import annotations

import flet as ft

from ._censorship_profiles import get_profile_manager


class _ProfilesMixin:
    """Create, edit, load and delete censorship profiles."""

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

        self._redact_terms.clear()
        self._redact_term_matches.clear()
        self._redact_matches.clear()
        if self._redact_preview:
            for ov in self._redact_overlays:
                ov.visible  = False
                ov.controls = []
            self._redact_preview = False

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
