"""PdfListPanel — left panel: "Paso 1" header plus the scrollable PDF list."""
from __future__ import annotations

from typing import Callable

import flet as ft

from ..model import PDFEntry
from .entry_card import EntryCard


class PdfListPanel:
    """Owns the left column of PDF cards and rebuilds it from the entry list."""

    def __init__(
        self,
        *,
        on_add:   Callable[[], None],
        on_clear: Callable[[], None],
        entry_card: EntryCard,
    ):
        self._entry_card = entry_card
        self._col = ft.Column([], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

        self.control = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PICTURE_AS_PDF, color="#D32F2F", size=20),
                            ft.Text(
                                "Paso 1: Selecciona PDFs",
                                size=15, weight="bold",
                                color="#1E2A38",
                            ),
                            ft.Container(expand=True),
                            ft.TextButton(
                                "Limpiar",
                                icon=ft.Icons.CLEAR_ALL,
                                style=ft.ButtonStyle(
                                    color="#D32F2F",
                                    text_style=ft.TextStyle(size=11),
                                ),
                                on_click=lambda e: on_clear(),
                                tooltip="Quitar todos los PDFs de la lista",
                            ),
                            ft.ElevatedButton(
                                "Agregar", icon=ft.Icons.ADD,
                                on_click=lambda e: on_add(),
                                tooltip="Agregar uno o más PDFs a la lista",
                                style=ft.ButtonStyle(padding=12),
                            ),
                        ],
                        vertical_alignment="center",
                        spacing=8,
                    ),
                    ft.Divider(height=1, color="#E0E0E0"),
                    ft.Container(self._col, expand=True),
                ],
                spacing=12,
                expand=True,
            ),
            expand=True,
            padding=20,
            bgcolor="#FAFAFA",
            border=ft.border.only(right=ft.BorderSide(1, "#E0E0E0")),
        )

    def rebuild(self, entries: list[PDFEntry]) -> None:
        if not entries:
            self._col.controls = [self._empty_placeholder()]
        else:
            self._col.controls = [
                self._entry_card.build(i, en, len(entries))
                for i, en in enumerate(entries)
            ]

    @staticmethod
    def _empty_placeholder() -> ft.Container:
        return ft.Container(
            ft.Column(
                [
                    ft.Icon(ft.Icons.UPLOAD_FILE, size=48, color=ft.Colors.OUTLINE),
                    ft.Text(
                        'Agrega PDFs con el botón "Agregar PDF"',
                        size=13, color=ft.Colors.OUTLINE, italic=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            padding=ft.padding.symmetric(vertical=60, horizontal=16),
            alignment=ft.alignment.center,
        )
