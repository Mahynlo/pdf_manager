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

import threading
from typing import Callable

import flet as ft

from ..model import PDFEntry, accent_color_for
from ..thumbnails import ThumbnailCache

# Tope de celdas que la vista previa dibuja a la vez. La rejilla NO virtualiza
# (a diferencia del visor), así que cada página seleccionada crea ~10 controles
# y retiene su PNG; pasados unos cientos eso consume memoria y puede ralentizar
# la UI. Limitamos la VISTA PREVIA (no la combinación, que incluye todas).
PREVIEW_MAX_PAGES = 500

# Carga perezosa de miniaturas: en vez de renderizar las (hasta) 500 de golpe,
# solo se piden las de la ventana visible (± margen) y se van cargando al
# desplazarse. El render se hace tras un breve reposo del scroll (no durante el
# fling), igual que la subida de calidad del visor.
_INITIAL_WINDOW = 60      # celdas a cargar al construir (cubre la parte de arriba)
_WINDOW_MARGIN  = 18      # celdas extra por encima/debajo de lo visible (cargar)
_TEARDOWN_MARGIN = 48     # más allá de la ventana de carga se LIBERA la imagen
_SCROLL_DEBOUNCE = 0.15   # s de reposo antes de pedir la ventana tras desplazar


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
        # Nº de páginas seleccionadas que NO se dibujan por el tope (0 = todas
        # mostradas). El tab lo usa para avisar en el estado.
        self.overflow = 0

        # Carga perezosa por scroll.
        self._frac: tuple[float, float] | None = None   # (top, bottom) visible
        self._last_window: tuple[int, int] | None = None
        self._scroll_timer: threading.Timer | None = None

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
        self.control = ft.Column(
            [self._empty], scroll="auto", expand=True, on_scroll=self._on_scroll
        )

    def rebuild(self, entries: list[PDFEntry]) -> int:
        """Rebuild the grid; returns the total page count in the result.

        Se dibujan como máximo `PREVIEW_MAX_PAGES` celdas; las que sobran se
        cuentan en `self.overflow` y se anuncian con un aviso. El total devuelto
        y la combinación siguen incluyendo TODAS las páginas seleccionadas.
        """
        items: list[ft.Control] = []
        flat:  list[tuple[PDFEntry, int]] = []
        total = 0
        shown = 0
        shown_by_path: dict[str, list[int]] = {}
        pw_by_path: dict[str, str | None] = {}

        for entry in entries:
            for pg in entry.selected_pages:
                total += 1
                if shown < PREVIEW_MAX_PAGES:
                    flat.append((entry, pg))
                    items.append(self._cell(entry, pg, shown + 1, shown))
                    shown_by_path.setdefault(entry.path, []).append(pg)
                    pw_by_path[entry.path] = entry.password
                    shown += 1

        self.items = flat
        self.overflow = total - shown

        if not items:
            self.control.controls = [self._empty]
        else:
            self._wrap.controls = items
            controls: list[ft.Control] = [self._wrap]
            if self.overflow > 0:
                controls.insert(0, self._overflow_banner(total))
            self.control.controls = controls

        # Carga perezosa + liberación: aplica la ventana visible sin pedir update
        # (el tab llama a page.update() tras este rebuild).
        self._last_window = None
        self._apply_window(do_update=False)
        return total

    # ── lazy thumbnail windowing (carga cercanas, libera lejanas) ─────────────

    def _load_range(self, shown: int) -> tuple[int, int]:
        """Rango [start, end) de celdas a cargar según el scroll actual."""
        if self._frac is None:
            return 0, min(shown, _INITIAL_WINDOW)
        top, bot = self._frac
        start = int(top * shown) - _WINDOW_MARGIN
        end = int(bot * shown) + _WINDOW_MARGIN
        return max(0, start), min(shown, end)

    def _apply_window(self, do_update: bool) -> None:
        """Pone la imagen en las celdas dentro de la ventana y la LIBERA en las
        que quedaron lejos (placeholder), acotando la memoria a la vecindad."""
        shown = len(self.items)
        if shown == 0:
            return
        start, end = self._load_range(shown)
        keep_lo = start - _TEARDOWN_MARGIN
        keep_hi = end + _TEARDOWN_MARGIN

        changed = False
        for idx, (entry, pg) in enumerate(self.items):
            cell = self._cells.get((entry.path, pg))
            if cell is None:
                continue
            in_keep = keep_lo <= idx < keep_hi
            if in_keep and not cell["has_img"]:
                b64 = self._thumbs.peek(entry.path, pg)
                if b64:
                    cell["stack"].controls[0] = self._thumb_ctrl(b64)
                    cell["has_img"] = True
                    changed = True
            elif not in_keep and cell["has_img"]:
                # Libera el PNG/textura de las celdas lejanas.
                cell["stack"].controls[0] = self._thumb_ctrl(None)
                cell["has_img"] = False
                changed = True

        self._request_window(start, end)

        if do_update and changed:
            try:
                self.control.update()
            except Exception:
                pass

    def _request_window(self, start: int, end: int) -> None:
        """Pide al worker renderizar (solo las no cacheadas) de items[start:end]."""
        if self._on_request_thumbs is None or not self.items:
            return
        start = max(0, start)
        end = min(len(self.items), end)
        if start >= end or (start, end) == self._last_window:
            return
        self._last_window = (start, end)

        by_path: dict[str, list[int]] = {}
        pw_by_path: dict[str, str | None] = {}
        for entry, pg in self.items[start:end]:
            by_path.setdefault(entry.path, []).append(pg)
            pw_by_path[entry.path] = entry.password
        for path, pages in by_path.items():
            self._on_request_thumbs(path, pages, pw_by_path[path])

    def _on_scroll(self, e) -> None:
        shown = len(self.items)
        if shown == 0:
            return
        viewport = getattr(e, "viewport_dimension", 0) or 0
        content = (getattr(e, "max_scroll_extent", 0) or 0) + viewport
        if content <= 0:
            return
        pixels = getattr(e, "pixels", 0) or 0
        self._frac = (pixels / content, (pixels + viewport) / content)
        # Aplica tras un breve reposo: durante un fling no se rinde/libera cada
        # posición intermedia, solo donde el scroll se detiene.
        if self._scroll_timer is not None:
            self._scroll_timer.cancel()
        self._scroll_timer = threading.Timer(_SCROLL_DEBOUNCE, self._flush_window)
        self._scroll_timer.daemon = True
        self._scroll_timer.start()

    def _flush_window(self) -> None:
        self._apply_window(do_update=True)

    def _overflow_banner(self, total: int) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color="#F57C00", size=18),
                    ft.Text(
                        f"Vista previa limitada a {PREVIEW_MAX_PAGES} de {total} páginas "
                        "para no consumir demasiados recursos. La combinación incluirá "
                        "TODAS las páginas seleccionadas.",
                        size=11, color="onSurfaceVariant", expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment="center",
            ),
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ORANGE),
            border=ft.border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.ORANGE)),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            margin=ft.margin.only(bottom=8),
        )

    def prune_path(self, path: str) -> None:
        for key in [k for k in self._cells if k[0] == path]:
            del self._cells[key]

    def clear(self) -> None:
        self._cells.clear()
        if self._scroll_timer is not None:
            self._scroll_timer.cancel()
            self._scroll_timer = None
        self._frac = None
        self._last_window = None

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

        if cell is None:
            # La imagen NO se pone aquí: la gobierna `_apply_window` según la
            # ventana visible (carga las cercanas, libera las lejanas). Se crea
            # siempre con placeholder.
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
                [self._thumb_ctrl(None), accent_bar, seq_badge, pg_badge]
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
                "seq_text": seq_text, "state": state, "has_img": False,
            }
            self._cells[key] = cell
        else:
            if cell["seq_text"].value != str(seq):
                cell["seq_text"].value = str(seq)
            cell["state"]["flat_idx"] = flat_idx

        return cell["target"]
