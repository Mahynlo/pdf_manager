"""Settings tab — opens as a closeable tab from the navbar."""

from __future__ import annotations

from typing import Callable

import flet as ft


_PANEL_BG    = "#F8F9FB"
_SECTION_CLR = ft.Colors.PRIMARY
_DIVIDER_CLR = ft.Colors.OUTLINE_VARIANT


def _section_label(text: str) -> ft.Text:
    return ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=_SECTION_CLR)


def _row_setting(
    icon: str,
    title: str,
    subtitle: str,
    control: ft.Control,
) -> ft.Container:
    return ft.Container(
        ft.Row(
            [
                ft.Icon(icon, size=22, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Column(
                    [
                        ft.Text(title,    size=14, weight=ft.FontWeight.W_500),
                        ft.Text(subtitle, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=2,
                    expand=True,
                ),
                control,
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=0, vertical=10),
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
                        ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=16),
                        ft.Text("Configuración", size=13, weight=ft.FontWeight.W_500),
                        ft.IconButton(
                            ft.Icons.CLOSE,
                            icon_size=14,
                            tooltip="Cerrar pestaña",
                            on_click=lambda e: self.on_close(self),
                            style=ft.ButtonStyle(padding=ft.padding.all(0)),
                        ),
                    ],
                    spacing=4,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                content=self.view,
            )
        return self._tab

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        is_dark = self._page.theme_mode == ft.ThemeMode.DARK

        self._dark_switch = ft.Switch(
            value=is_dark,
            on_change=self._on_dark_toggle,
        )

        settings_card = ft.Container(
            ft.Column(
                [
                    _section_label("Apariencia"),
                    ft.Divider(height=1, color=_DIVIDER_CLR),
                    _row_setting(
                        ft.Icons.DARK_MODE_OUTLINED,
                        "Modo oscuro",
                        "Cambia entre tema claro y oscuro",
                        self._dark_switch,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.padding.all(20),
            bgcolor=ft.Colors.SURFACE,
            border_radius=12,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        )

        self.view = ft.Column(
            [
                ft.Container(
                    ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.SETTINGS_OUTLINED,
                                size=28,
                                color=ft.Colors.PRIMARY,
                            ),
                            ft.Text(
                                "Configuración",
                                size=24,
                                weight=ft.FontWeight.W_800,
                                color=ft.Colors.ON_SURFACE,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.only(left=32, top=28, bottom=8),
                ),
                ft.Container(
                    ft.Column(
                        [settings_card],
                        spacing=16,
                    ),
                    padding=ft.padding.symmetric(horizontal=32, vertical=8),
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        )

    # ── handlers ─────────────────────────────────────────────────────────────

    def _on_dark_toggle(self, e: ft.ControlEvent) -> None:
        self._page.theme_mode = (
            ft.ThemeMode.DARK if e.control.value else ft.ThemeMode.LIGHT
        )
        self._page.update()
