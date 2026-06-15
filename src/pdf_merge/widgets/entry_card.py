"""EntryCard — builds the UI card for one source PDF in the merge list.

Stateful builder: configured once with the thumbnail cache and the per-entry
action callbacks, then `build()` is called on every list rebuild for each entry.

Para evitar parpadeo al (de)seleccionar páginas, las tarjetas (por `path`) y los
chips de página (por `(path, page)`) se **reutilizan** entre reconstrucciones —
Flet reconcilia por identidad de objeto (`hash(ctrl)`), así que reusar el mismo
control evita re-añadir el widget de imagen y re-decodificar el base64. En cada
reconstrucción solo se mutan los atributos que cambian (selección, contador,
índice, rango). Los handlers leen el índice actual desde `self._idx_by_path`
para mantener closures estables.
"""
from __future__ import annotations

from typing import Callable

import flet as ft

from ..model import PDFEntry, accent_color_for, selection_to_range
from ..thumbnails import ThumbnailCache

_CHIPS_PREVIEW = 30
_CHIPS_MAX     = 120

_TW, _TH = 54, 72


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
        on_restore_order:  Callable[[int], None],
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
        self._on_restore_order = on_restore_order

        # Caches reutilizables.
        self._cards: dict[str, dict] = {}            # path -> card refs
        self._chips: dict[tuple[str, int], dict] = {}  # (path, page) -> chip refs
        self._idx_by_path: dict[str, int] = {}       # índice actual de cada entry

    # ── public API ────────────────────────────────────────────────────────────

    def build(self, idx: int, entry: PDFEntry, total_entries: int) -> ft.Container:
        self._idx_by_path[entry.path] = idx

        card = self._cards.get(entry.path)
        if card is None:
            card = self._build_card(entry)
            self._cards[entry.path] = card

        # ── mutables que dependen del estado ────────────────────────────────
        card["up_btn"].disabled   = (idx == 0)
        card["down_btn"].disabled = (idx == total_entries - 1)
        card["restore_btn"].disabled = not entry.is_reordered
        card["count_text"].value  = f"{entry.selected_count}/{entry.total} págs."

        new_range = selection_to_range(entry.selected)
        if card["range_field"].value != new_range:
            card["range_field"].value = new_range

        # ── chips de página ─────────────────────────────────────────────────
        if entry.chips_expanded:
            visible_n = min(_CHIPS_MAX, entry.total)
        else:
            visible_n = min(_CHIPS_PREVIEW, entry.total)

        chips: list[ft.Control] = [self._chip(entry, p) for p in range(visible_n)]
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
                    on_click=lambda e, p=entry.path: self._on_toggle_chips(self._idx_by_path[p]),
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
        card["chips_row"].controls = chips

        return card["container"]

    def prune_path(self, path: str) -> None:
        self._cards.pop(path, None)
        self._idx_by_path.pop(path, None)
        for key in [k for k in self._chips if k[0] == path]:
            del self._chips[key]

    def clear(self) -> None:
        self._cards.clear()
        self._chips.clear()
        self._idx_by_path.clear()

    # ── builders ──────────────────────────────────────────────────────────────

    def _thumb_ctrl(self, thumb_b64: str | None) -> ft.Control:
        # Solo-cache: construir la UI no debe renderizar (lo hace el worker
        # async disparado por _on_request_thumbs).
        if thumb_b64:
            return ft.Image(
                src_base64=thumb_b64, width=_TW, height=_TH,
                fit=ft.ImageFit.COVER, gapless_playback=True,
            )
        return ft.Container(
            width=_TW, height=_TH, bgcolor="surfaceVariant",
            content=ft.Icon(ft.Icons.PICTURE_AS_PDF, size=20, color=ft.Colors.OUTLINE),
            alignment=ft.alignment.center,
        )

    def _chip(self, entry: PDFEntry, pg: int) -> ft.Container:
        key = (entry.path, pg)
        sel = entry.selected[pg]
        thumb_b64 = self._thumbs.peek(entry.path, pg)

        chip = self._chips.get(key)
        if chip is None:
            overlay = ft.Container(left=0, right=0, top=0, bottom=0)
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
            stack = ft.Stack([self._thumb_ctrl(thumb_b64), overlay, num_badge])
            container = ft.Container(
                content=stack,
                width=_TW, height=_TH,
                border_radius=4,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                on_click=lambda e, p=entry.path, i=pg: self._on_toggle_page(self._idx_by_path[p], i),
                ink=True,
            )
            chip = {
                "container": container, "stack": stack, "overlay": overlay,
                "has_img": bool(thumb_b64), "sel": None,
            }
            self._chips[key] = chip

        # Selection-dependent visuals: blue tint when selected, dark when excluded.
        if chip["sel"] != sel:
            chip["overlay"].bgcolor = "#1976D244" if sel else "#00000066"
            chip["container"].border = ft.border.all(
                2, ft.Colors.PRIMARY if sel else ft.Colors.OUTLINE_VARIANT
            )
            chip["container"].tooltip = (
                f"Página {pg + 1}  ({'seleccionada' if sel else 'no incluida'})"
            )
            chip["sel"] = sel

        if thumb_b64 and not chip["has_img"]:
            chip["stack"].controls[0] = self._thumb_ctrl(thumb_b64)
            chip["has_img"] = True

        return chip["container"]

    def _build_card(self, entry: PDFEntry) -> dict:
        path = entry.path

        up_btn = ft.IconButton(
            ft.Icons.ARROW_UPWARD, icon_size=14,
            tooltip="Mover arriba",
            on_click=lambda e, p=path: self._on_move(self._idx_by_path[p], -1),
        )
        down_btn = ft.IconButton(
            ft.Icons.ARROW_DOWNWARD, icon_size=14,
            tooltip="Mover abajo",
            on_click=lambda e, p=path: self._on_move(self._idx_by_path[p], +1),
        )
        count_text = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        restore_btn = ft.TextButton(
            "Restaurar", icon=ft.Icons.RESTART_ALT,
            style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
            on_click=lambda e, p=path: self._on_restore_order(self._idx_by_path[p]),
            tooltip="Restaurar el orden original de las páginas",
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
            on_blur=lambda e, p=path: self._on_apply_range(self._idx_by_path[p], e.control.value),
            on_submit=lambda e, p=path: self._on_apply_range(self._idx_by_path[p], e.control.value),
        )
        chips_row = ft.Row([], wrap=True, spacing=4, run_spacing=4)

        container = ft.Container(
            content=ft.Column(
                [
                    # header row
                    ft.Row(
                        [
                            # Punto del color de acento del PDF (leyenda para la
                            # franja que identifica sus páginas en la vista previa).
                            ft.Container(
                                width=10, height=10, border_radius=5,
                                bgcolor=accent_color_for(path),
                                tooltip="Color de este PDF en la vista previa",
                            ),
                            ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ft.Colors.ERROR, size=18),
                            ft.Text(
                                entry.filename, size=13, weight=ft.FontWeight.W_500,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                color=ft.Colors.ON_SURFACE, expand=True,
                            ),
                            up_btn,
                            down_btn,
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE, icon_size=14,
                                tooltip="Quitar de la lista",
                                icon_color=ft.Colors.ERROR,
                                on_click=lambda e, p=path: self._on_remove(self._idx_by_path[p]),
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
                                on_click=lambda e, p=path: self._on_select_all(self._idx_by_path[p], True),
                            ),
                            ft.TextButton(
                                "Ninguna", icon=ft.Icons.DESELECT,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, p=path: self._on_select_all(self._idx_by_path[p], False),
                            ),
                            ft.TextButton(
                                "Invertir", icon=ft.Icons.SWAP_HORIZ,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, p=path: self._on_invert(self._idx_by_path[p]),
                                tooltip="Invertir la selección de páginas",
                            ),
                            restore_btn,
                            ft.Container(expand=True),
                            count_text,
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # page range input
                    ft.Row([range_field], spacing=0),
                    # page chips
                    chips_row,
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

        return {
            "container": container,
            "up_btn": up_btn,
            "down_btn": down_btn,
            "restore_btn": restore_btn,
            "count_text": count_text,
            "range_field": range_field,
            "chips_row": chips_row,
        }
