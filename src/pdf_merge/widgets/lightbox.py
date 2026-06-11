"""LightboxDialog — modal preview of a single result page with navigation.

Opened with the flat `(entry, original_page)` list from the preview grid and a
start index; renders 0.5× thumbnails and lets the user page through the result.
"""
from __future__ import annotations

import flet as ft

from ..model import PDFEntry
from ..thumbnails import ThumbnailCache


class LightboxDialog:
    def __init__(self, page: ft.Page, large_thumbs: ThumbnailCache):
        self._page = page
        self._large = large_thumbs
        self._items: list[tuple[PDFEntry, int]] = []
        self._cursor = 0

        self._img = ft.Image(width=300, height=420, fit=ft.ImageFit.CONTAIN, src_base64="")
        self._nav = ft.Text("", size=13, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER)
        self._prev = ft.IconButton(
            ft.Icons.CHEVRON_LEFT, icon_size=28,
            tooltip="Página anterior en el resultado",
            on_click=lambda e: self._navigate(-1),
        )
        self._next = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT, icon_size=28,
            tooltip="Página siguiente en el resultado",
            on_click=lambda e: self._navigate(+1),
        )
        self._info = ft.Column(
            [
                ft.Text("", size=13, weight=ft.FontWeight.W_500,
                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.PREVIEW, color=ft.Colors.PRIMARY, size=20),
                    ft.Text("Vista previa", size=16, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=self._img,
                            bgcolor="surfaceVariant",
                            border_radius=6,
                            alignment=ft.alignment.center,
                            width=300, height=420,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        ft.Row(
                            [self._prev, self._nav, self._next],
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        self._info,
                    ],
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                width=320,
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: self._page.close(self._dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def open(self, items: list[tuple[PDFEntry, int]], start_idx: int) -> None:
        if not items:
            return
        self._items = items
        self._cursor = max(0, min(start_idx, len(items) - 1))
        self._update_content()
        self._page.open(self._dialog)

    def _navigate(self, delta: int) -> None:
        if not self._items:
            return
        self._cursor = max(0, min(self._cursor + delta, len(self._items) - 1))
        self._update_content()
        self._page.update()

    def _update_content(self) -> None:
        if not self._items:
            return
        total = len(self._items)
        idx = self._cursor
        entry, orig_pg = self._items[idx]

        # Single page render — fast enough to do synchronously
        large_b64 = self._large.get(entry.path, orig_pg, password=entry.password)
        self._img.src_base64 = large_b64 if large_b64 else None
        self._img.src = None

        self._nav.value = f"{idx + 1} / {total}"
        self._prev.disabled = idx == 0
        self._next.disabled = idx == total - 1

        info = self._info.controls
        info[0].value = entry.filename
        info[1].value = f"Página original: {orig_pg + 1} de {entry.total}"
        info[2].value = f"Posición en resultado: {idx + 1} de {total}"
