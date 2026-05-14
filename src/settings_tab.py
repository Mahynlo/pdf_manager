"""Settings tab — opens as a closeable tab from the navbar."""

from __future__ import annotations

from typing import Callable

import flet as ft


def _section_label(text: str) -> ft.Text:
    # Usamos "primary" en texto para que Flet lo adapte al tema sin usar Enums
    return ft.Text(text, size=14, weight="bold", color="primary")


def _row_setting(
    icon: str,
    title: str,
    subtitle: str,
    control: ft.Control,
) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                # Contenedor del ícono que adapta su fondo automáticamente
                ft.Container(
                    content=ft.Icon(icon, size=24, color="primary"),
                    bgcolor="primaryContainer",
                    padding=10,
                    border_radius=8,
                ),
                ft.Column(
                    [
                        # Al no ponerle color, Flet lo hace negro en día y blanco en noche
                        ft.Text(title, size=15, weight="w600"),
                        ft.Text(subtitle, size=13, color="onSurfaceVariant"),
                    ],
                    spacing=2,
                    expand=True,
                ),
                control,
            ],
            spacing=16,
            vertical_alignment="center",
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=12),
        border_radius=8,
    )


class SettingsTab:
    """A full-page settings tab that can be opened and closed."""

    def __init__(self, page_ref: ft.Page, on_close: Callable[["SettingsTab"], None]):
        self._page    = page_ref
        self.on_close = on_close
        self._tab: ft.Tab | None = None
        self._build()

    # ── public ───────────────────────────────────────────────────────────────

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=16, color="primary"),
                        ft.Text("Configuración", size=13, weight="w500"),
                        ft.IconButton(
                            ft.Icons.CLOSE,
                            icon_size=14,
                            tooltip="Cerrar pestaña",
                            on_click=lambda e: self.on_close(self),
                            style=ft.ButtonStyle(padding=0),
                        ),
                    ],
                    spacing=6,
                    tight=True,
                    vertical_alignment="center",
                ),
                content=self.view,
            )
        return self._tab

    def get_tab_info(self) -> dict:
        return {
            "label": "Configuración",
            "icon": ft.Icons.SETTINGS_OUTLINED,
            "content": self.view,
            "closeable": True,
            "close_cb": lambda: self.on_close(self),
        }

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        current_theme = str(self._page.theme_mode).lower()
        is_dark = "dark" in current_theme

        self._dark_switch = ft.Switch(
            value=is_dark,
            on_change=self._on_dark_toggle,
            active_color="primary"
        )

        # ─── HEADER ────────────────────────────────────────────────────────
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SETTINGS, size=32, color="primary"),
                    ft.Column([
                        ft.Text("Configuración General", size=22, weight="bold"),
                        ft.Text("Administra las preferencias y la apariencia de la aplicación", size=13, color="onSurfaceVariant"),
                    ], spacing=2)
                ],
                alignment="start",
                spacing=16,
            ),
            padding=ft.padding.only(left=20, top=20, right=20, bottom=10)
        )

        settings_card = ft.Container(
            content=ft.Column(
                [
                    _section_label("Apariencia"),
                    ft.Divider(height=1, color="outlineVariant"),
                    _row_setting(
                        ft.Icons.DARK_MODE_OUTLINED,
                        "Modo oscuro",
                        "Cambia entre tema claro y oscuro para mayor comodidad visual",
                        self._dark_switch,
                    ),
                ],
                spacing=12,
            ),
            padding=20,
            # "surfaceVariant" es el string clave: es blanco grisáceo en día y gris oscuro de noche
            bgcolor="surfaceVariant",
            border_radius=12,
            border=ft.border.all(1, "outlineVariant"),
        )

        tabs_container = ft.Container(
            content=ft.Column([settings_card], spacing=16),
            padding=30,
            expand=True,
        )

        self.view = ft.Card(
            content=ft.Column([header, ft.Divider(height=1, color="outlineVariant"), tabs_container], spacing=0),
            elevation=2,
            margin=10,
            expand=True
        )

    # ── handlers ─────────────────────────────────────────────────────────────

    def _on_dark_toggle(self, e: ft.ControlEvent) -> None:
        # Se actualiza el modo de la app
        self._page.theme_mode = "dark" if e.control.value else "light"
        self._page.update()