"""EntryCard — builds the UI card for one source PDF in the merge list.

Stateless builder: configured once with the thumbnail cache and the per-entry
action callbacks, then `build()` is called on every list rebuild to produce a
fresh `ft.Container` for the given entry.
"""
from __future__ import annotations

from typing import Callable

import flet as ft

from ..model import PDFEntry, selection_to_range
from ..thumbnails import ThumbnailCache

_CHIPS_PREVIEW = 30
_CHIPS_MAX     = 120


class EntryCard:
    def __init__(
        self,
        thumbs: ThumbnailCache,
        *,
        on_toggle_page:    Callable[[int, int], None],
        on_select_all:     Callable[[int, bool], None],
        on_invert:         Callable[[int], None],
        on_apply_range:    Callable[[int, str], None],
        on_toggle_chips:   Callable[[int], None],
        on_move:           Callable[[int, int], None],
        on_remove:         Callable[[int], None],
        on_request_thumbs: Callable[[str, list[int], str | None], None],
    ):
        self._thumbs           = thumbs
        self._on_toggle_page   = on_toggle_page
        self._on_select_all    = on_select_all
        self._on_invert        = on_invert
        self._on_apply_range   = on_apply_range
        self._on_toggle_chips  = on_toggle_chips
        self._on_move          = on_move
        self._on_remove        = on_remove
        self._on_request_thumbs = on_request_thumbs

    def build(self, idx: int, entry: PDFEntry, total_entries: int) -> ft.Container:
        _TW, _TH = 54, 72

        def _chip(pg: int) -> ft.Container:
            sel = entry.selected[pg]
            # Solo-cache: construir la UI no debe renderizar (lo hace el worker
            # async disparado por _on_request_thumbs más abajo).
            thumb_b64 = self._thumbs.peek(entry.path, pg)

            if thumb_b64:
                thumb: ft.Control = ft.Image(
                    src_base64=thumb_b64, width=_TW, height=_TH,
                    fit=ft.ImageFit.COVER,
                )
            else:
                thumb = ft.Container(
                    width=_TW, height=_TH, bgcolor="surfaceVariant",
                    content=ft.Icon(ft.Icons.PICTURE_AS_PDF, size=20, color=ft.Colors.OUTLINE),
                    alignment=ft.alignment.center,
                )

            # Blue tint when selected, dark tint when excluded
            overlay = ft.Container(
                bgcolor="#1976D244" if sel else "#00000066",
                left=0, right=0, top=0, bottom=0,
            )
            num_badge = ft.Container(
                content=ft.Text(
                    str(pg + 1), size=9, color="white",
                    text_align=ft.TextAlign.CENTER,
                    weight=ft.FontWeight.BOLD,
                ),
                bgcolor="#000000BB",
                padding=ft.padding.symmetric(horizontal=3, vertical=1),
                alignment=ft.alignment.center,
                left=0, right=0, bottom=0,
            )

            return ft.Container(
                content=ft.Stack([thumb, overlay, num_badge]),
                width=_TW, height=_TH,
                border_radius=4,
                border=ft.border.all(
                    2, ft.Colors.PRIMARY if sel else ft.Colors.OUTLINE_VARIANT
                ),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                tooltip=f"Página {pg + 1}  ({'seleccionada' if sel else 'no incluida'})",
                on_click=lambda e, i=idx, p=pg: self._on_toggle_page(i, p),
                ink=True,
            )

        if entry.chips_expanded:
            visible_n = min(_CHIPS_MAX, entry.total)
        else:
            visible_n = min(_CHIPS_PREVIEW, entry.total)

        chips: list[ft.Control] = [_chip(p) for p in range(visible_n)]
        self._on_request_thumbs(entry.path, list(range(visible_n)), entry.password)

        if entry.total > _CHIPS_PREVIEW:
            if entry.chips_expanded:
                toggle_lbl  = "Mostrar menos"
                toggle_icon = ft.Icons.EXPAND_LESS
            else:
                remaining   = entry.total - _CHIPS_PREVIEW
                toggle_lbl  = f"Ver {remaining} páginas más"
                toggle_icon = ft.Icons.EXPAND_MORE
            chips.append(
                ft.TextButton(
                    toggle_lbl, icon=toggle_icon,
                    style=ft.ButtonStyle(text_style=ft.TextStyle(size=10)),
                    on_click=lambda e, i=idx: self._on_toggle_chips(i),
                )
            )
            if entry.chips_expanded and entry.total > _CHIPS_MAX:
                hidden = entry.total - _CHIPS_MAX
                chips.append(
                    ft.Text(
                        f"... y {hidden} páginas más — usa el campo de rango para incluirlas.",
                        size=10, color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                    )
                )

        range_field = ft.TextField(
            value=selection_to_range(entry.selected),
            hint_text="Ej: 1-5, 8, 10-15",
            label="Rango de páginas (1-based)",
            label_style=ft.TextStyle(size=11),
            text_size=12,
            dense=True,
            border_radius=6,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=6),
            expand=True,
            tooltip="Escribe un rango y presiona Enter o haz clic fuera para aplicar",
            on_blur=lambda e, i=idx: self._on_apply_range(i, e.control.value),
            on_submit=lambda e, i=idx: self._on_apply_range(i, e.control.value),
        )

        return ft.Container(
            content=ft.Column(
                [
                    # header row
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ft.Colors.ERROR, size=18),
                            ft.Text(
                                entry.filename, size=13, weight=ft.FontWeight.W_500,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                color=ft.Colors.ON_SURFACE, expand=True,
                            ),
                            ft.IconButton(
                                ft.Icons.ARROW_UPWARD, icon_size=14,
                                tooltip="Mover arriba",
                                on_click=lambda e, i=idx: self._on_move(i, -1),
                                disabled=(idx == 0),
                            ),
                            ft.IconButton(
                                ft.Icons.ARROW_DOWNWARD, icon_size=14,
                                tooltip="Mover abajo",
                                on_click=lambda e, i=idx: self._on_move(i, +1),
                                disabled=(idx == total_entries - 1),
                            ),
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE, icon_size=14,
                                tooltip="Quitar de la lista",
                                icon_color=ft.Colors.ERROR,
                                on_click=lambda e, i=idx: self._on_remove(i),
                            ),
                        ],
                        spacing=2,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # quick-select row
                    ft.Row(
                        [
                            ft.TextButton(
                                "Todas", icon=ft.Icons.SELECT_ALL,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, i=idx: self._on_select_all(i, True),
                            ),
                            ft.TextButton(
                                "Ninguna", icon=ft.Icons.DESELECT,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, i=idx: self._on_select_all(i, False),
                            ),
                            ft.TextButton(
                                "Invertir", icon=ft.Icons.SWAP_HORIZ,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, i=idx: self._on_invert(i),
                                tooltip="Invertir la selección de páginas",
                            ),
                            ft.Container(expand=True),
                            ft.Text(
                                f"{entry.selected_count}/{entry.total} págs.",
                                size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # page range input
                    ft.Row([range_field], spacing=0),
                    # page chips
                    ft.Row(chips, wrap=True, spacing=4, run_spacing=4),
                ],
                spacing=4,
            ),
            padding=ft.padding.all(10),
            bgcolor=ft.Colors.SURFACE,
            border_radius=10,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            shadow=ft.BoxShadow(
                blur_radius=4, spread_radius=0,
                color=ft.Colors.SHADOW, offset=ft.Offset(0, 1),
            ),
        )
