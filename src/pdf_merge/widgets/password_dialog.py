"""PasswordDialog — prompts for an encrypted PDF's password.

Pure widget: it gathers the password and reports Cancel / Add / "go to
Security" back through callbacks. The queue of pending protected files and the
authentication logic live in the tab.
"""
from __future__ import annotations

from typing import Callable

import flet as ft


class PasswordDialog:
    def __init__(
        self,
        page: ft.Page,
        *,
        on_confirm:       Callable[[str], None],
        on_cancel:        Callable[[], None],
        on_open_security: Callable[[], None],
    ):
        self._page = page

        self._field = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            autofocus=True,
            on_submit=lambda _: on_confirm(self._field.value or ""),
        )
        self._error = ft.Text("", color="#D32F2F", size=12, visible=False)
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("PDF protegido"),
            content=ft.Column([self._field, self._error], tight=True, spacing=8),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: on_cancel()),
                ft.TextButton("Ir a Seguridad", on_click=lambda _: on_open_security()),
                ft.ElevatedButton(
                    "Agregar", icon=ft.Icons.LOCK_OPEN,
                    on_click=lambda _: on_confirm(self._field.value or ""),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def prompt(self, filename: str, error: str | None = None) -> None:
        """Open the dialog for *filename*, optionally showing an error message."""
        self._field.value = ""
        self._error.value = error or ""
        self._error.visible = bool(error)
        self._dialog.title = ft.Text(f"PDF protegido: {filename}")
        self._page.open(self._dialog)

    def show_error(self, message: str) -> None:
        self._error.value = message
        self._error.visible = True
        self._page.update()

    def close(self) -> None:
        self._page.close(self._dialog)
