"""PreviewGrid — right-panel grid of every page that will appear in the result.

Rebuilt from the entry list; exposes the flat `(entry, original_page)` ordering
in `items`, which the lightbox uses for navigation.

Reordenar: cada celda es un `Draggable` envuelto en un `DragTarget` cuyo `group`
es el path del PDF, así que solo se puede arrastrar y soltar una página sobre
otra **del mismo PDF**. Soltar inserta la página de origen en la posición de la
de destino (`on_reorder`), desplazando las demás.

Para evitar parpadeo al (de)seleccionar páginas, las celdas se **reutilizan**
entre reconstrucciones (cacheadas por `(path, page)`): Flet reconcilia por
identidad de objeto (`hash(ctrl)`), así que reusar el mismo control evita que
el cliente re-añada el widget de imagen y vuelva a decodificar el base64.
"""
from __future__ import annotations

from typing import Callable

import flet as ft

from ..model import PDFEntry, accent_color_for
from ..thumbnails import ThumbnailCache


class PreviewGrid:
    def __init__(
        self,
        thumbs: ThumbnailCache,
        *,
        on_open: Callable[[int], None],
        on_request_thumbs: Callable[[str, list[int], str | None], None] | None = None,
        on_reorder: Callable[[PDFEntry, int, int], None] | None = None,
    ):
        self._thumbs = thumbs
        self._on_open = on_open
        self._on_request_thumbs = on_request_thumbs
        self._on_reorder = on_reorder
        self.items: list[tuple[PDFEntry, int]] = []

        # Celdas reutilizables cacheadas por (path, page).
        self._cells: dict[tuple[str, int], dict] = {}

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
                items.append(self._cell(entry, pg, total, flat_idx))

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

    def prune_path(self, path: str) -> None:
        for key in [k for k in self._cells if k[0] == path]:
            del self._cells[key]

    def clear(self) -> None:
        self._cells.clear()

    # ── drag & drop reorder ──────────────────────────────────────────────────

    @staticmethod
    def _visual_of(target: ft.DragTarget) -> ft.Container:
        # DragTarget → Draggable → Container visual
        return target.content.content

    def _on_will_accept(self, e) -> None:
        accept = e.data == "true"
        vis = self._visual_of(e.control)
        vis.border = ft.border.all(
            2, ft.Colors.PRIMARY if accept else ft.Colors.ERROR
        )
        e.control.update()

    def _on_leave(self, e) -> None:
        vis = self._visual_of(e.control)
        vis.border = ft.border.all(1, ft.Colors.OUTLINE_VARIANT)
        e.control.update()

    def _on_accept(self, e) -> None:
        vis = self._visual_of(e.control)
        vis.border = ft.border.all(1, ft.Colors.OUTLINE_VARIANT)
        e.control.update()

        src = e.page.get_control(e.src_id)
        if src is None or self._on_reorder is None:
            return
        from_entry, from_pg = src.data
        to_entry, to_pg = e.control.data
        if from_entry is not to_entry or from_pg == to_pg:
            return
        self._on_reorder(to_entry, from_pg, to_pg)

    # ── cell building ────────────────────────────────────────────────────────

    def _thumb_ctrl(self, thumb_b64: str | None) -> ft.Control:
        if thumb_b64:
            return ft.Image(
                src_base64=thumb_b64, width=56, height=76, fit=ft.ImageFit.COVER,
                gapless_playback=True,
            )
        return ft.Container(
            width=56, height=76, bgcolor="surfaceVariant",
            content=ft.Icon(ft.Icons.PICTURE_AS_PDF, size=18, color=ft.Colors.OUTLINE),
            alignment=ft.alignment.center,
        )

    def _cell(self, entry: PDFEntry, pg: int, seq: int, flat_idx: int) -> ft.DragTarget:
        key = (entry.path, pg)
        cell = self._cells.get(key)
        thumb_b64 = self._thumbs.peek(entry.path, pg)

        if cell is None:
            accent = accent_color_for(entry.path)
            seq_text = ft.Text(
                str(seq), size=8, color="white",
                weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER,
            )
            seq_badge = ft.Container(  # Sequential number badge (top-right)
                content=seq_text,
                bgcolor="#000000CC",
                padding=ft.padding.symmetric(horizontal=3, vertical=1),
                right=0, top=0,
                border_radius=ft.border_radius.only(bottom_left=3),
            )
            pg_badge = ft.Container(  # Original page badge (bottom-left), tinted per PDF
                content=ft.Text(
                    f"p{pg + 1}", size=7, color="white", text_align=ft.TextAlign.CENTER,
                ),
                bgcolor=f"{accent}CC",
                padding=ft.padding.symmetric(horizontal=3, vertical=1),
                left=0, bottom=0,
                border_radius=ft.border_radius.only(top_right=3),
            )
            # Franja superior con el color del PDF: distingue de un vistazo a qué
            # documento pertenece cada página (los grupos contiguos comparten color).
            accent_bar = ft.Container(
                left=0, right=0, top=0, height=5, bgcolor=accent,
            )
            stack = ft.Stack(
                [self._thumb_ctrl(thumb_b64), accent_bar, seq_badge, pg_badge]
            )
            state = {"flat_idx": flat_idx}
            visual = ft.Container(
                content=stack,
                width=60, height=80,
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=4,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ink=True,
                ink_color="#00000018",
                tooltip="Arrastra para reordenar · clic para ampliar",
                on_click=lambda e, s=state: self._on_open(s["flat_idx"]),
            )
            draggable = ft.Draggable(
                group=entry.path,
                content=visual,
                content_feedback=ft.Container(
                    content=ft.Text(
                        f"p{pg + 1}", size=11, color="white",
                        weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER,
                    ),
                    width=44, height=58,
                    bgcolor=ft.Colors.PRIMARY,
                    border_radius=4,
                    alignment=ft.alignment.center,
                    opacity=0.9,
                ),
                data=(entry, pg),
            )
            target = ft.DragTarget(
                group=entry.path,
                content=draggable,
                on_will_accept=self._on_will_accept,
                on_accept=self._on_accept,
                on_leave=self._on_leave,
                data=(entry, pg),
            )
            cell = {
                "target": target, "stack": stack,
                "seq_text": seq_text, "state": state, "has_img": bool(thumb_b64),
            }
            self._cells[key] = cell
        else:
            if cell["seq_text"].value != str(seq):
                cell["seq_text"].value = str(seq)
            cell["state"]["flat_idx"] = flat_idx
            if thumb_b64 and not cell["has_img"]:
                cell["stack"].controls[0] = self._thumb_ctrl(thumb_b64)
                cell["has_img"] = True

        return cell["target"]
