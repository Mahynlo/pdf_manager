"""PreviewGrid — right-panel grid of every page that will appear in the result.

Rebuilt from the entry list; exposes the flat `(entry, original_page)` ordering
in `items`, which the lightbox uses for navigation.
"""
from __future__ import annotations

from typing import Callable

import flet as ft

from ..model import PDFEntry
from ..thumbnails import ThumbnailCache


class PreviewGrid:
    def __init__(
        self,
        thumbs: ThumbnailCache,
        *,
        on_open: Callable[[int], None],
        on_request_thumbs: Callable[[str, list[int], str | None], None] | None = None,
    ):
        self._thumbs = thumbs
        self._on_open = on_open
        self._on_request_thumbs = on_request_thumbs
        self.items: list[tuple[PDFEntry, int]] = []

        self._wrap = ft.Row([], wrap=True, spacing=4, run_spacing=4)
        self._empty = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.PREVIEW, size=40, color=ft.Colors.OUTLINE),
                    ft.Text(
                        "Sin páginas seleccionadas",
                        size=13, color=ft.Colors.OUTLINE, italic=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment="center",
                spacing=8,
                alignment="center",
            ),
            expand=True,
            alignment=ft.alignment.center,
            visible=True,
        )
        self.control = ft.Column([self._empty], scroll="auto", expand=True)

    def rebuild(self, entries: list[PDFEntry]) -> int:
        """Rebuild the grid; returns the total page count in the result."""
        items: list[ft.Control] = []
        flat:  list[tuple[PDFEntry, int]] = []
        total = 0

        for entry in entries:
            for pg in entry.selected_pages:
                flat_idx = total   # 0-based index in result
                total += 1
                flat.append((entry, pg))
                items.append(self._make_cell(entry, pg, total, flat_idx))

        self.items = flat
        if not items:
            self.control.controls = [self._empty]
        else:
            self._wrap.controls = items
            self.control.controls = [self._wrap]

        # Pide al worker async que renderice (en lote, una apertura por PDF) las
        # páginas que falten en cache; al terminar refresca y aparecen.
        if self._on_request_thumbs is not None:
            for entry in entries:
                pages = list(entry.selected_pages)
                if pages:
                    self._on_request_thumbs(entry.path, pages, entry.password)
        return total

    def _make_cell(self, entry: PDFEntry, pg: int, seq: int, flat_idx: int) -> ft.Container:
        # Solo-cache: el render lo hace el worker async (ver rebuild()).
        thumb_b64 = self._thumbs.peek(entry.path, pg)
        if thumb_b64:
            thumb_ctrl: ft.Control = ft.Image(
                src_base64=thumb_b64, width=56, height=76, fit=ft.ImageFit.COVER,
            )
        else:
            thumb_ctrl = ft.Container(
                width=56, height=76, bgcolor="surfaceVariant",
                content=ft.Icon(ft.Icons.PICTURE_AS_PDF, size=18, color=ft.Colors.OUTLINE),
                alignment=ft.alignment.center,
            )

        # Sequential number badge (top-right)
        seq_badge = ft.Container(
            content=ft.Text(
                str(seq), size=8, color="white",
                weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER,
            ),
            bgcolor="#000000CC",
            padding=ft.padding.symmetric(horizontal=3, vertical=1),
            right=0, top=0,
            border_radius=ft.border_radius.only(bottom_left=3),
        )
        # Original page badge (bottom-left)
        pg_badge = ft.Container(
            content=ft.Text(
                f"p{pg + 1}", size=7, color="white", text_align=ft.TextAlign.CENTER,
            ),
            bgcolor="#1976D2CC",
            padding=ft.padding.symmetric(horizontal=3, vertical=1),
            left=0, bottom=0,
            border_radius=ft.border_radius.only(top_right=3),
        )

        return ft.Container(
            content=ft.Stack([thumb_ctrl, seq_badge, pg_badge]),
            width=60, height=80,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ink=True,
            ink_color="#00000018",
            tooltip="Clic para ampliar",
            on_click=lambda e, i=flat_idx: self._on_open(i),
        )
