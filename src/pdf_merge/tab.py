"""MergePDFTab — combine multiple PDFs with visual per-page selection."""
from __future__ import annotations

import base64
import threading
import time
from pathlib import Path
from typing import Callable

import flet as ft
import fitz

_CHIPS_PREVIEW = 30
_CHIPS_MAX     = 120


# ── range helpers ─────────────────────────────────────────────────────────────

def _selection_to_range(selected: list[bool]) -> str:
    """Boolean list → compact 1-based range string, e.g. '1-5, 8, 10-15'."""
    pages = [i + 1 for i, s in enumerate(selected) if s]
    if not pages:
        return ""
    ranges: list[str] = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = p
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(ranges)


def _parse_range(text: str, total: int) -> list[bool]:
    """'1-5, 8, 10-15' (1-based, semicolons allowed) → boolean selection list."""
    selected = [False] * total
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s.strip()), int(hi_s.strip())
                lo, hi = min(lo, hi), max(lo, hi)
                for i in range(max(1, lo), min(total, hi) + 1):
                    selected[i - 1] = True
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= total:
                    selected[n - 1] = True
            except ValueError:
                pass
    return selected


# ── model ─────────────────────────────────────────────────────────────────────

class _PDFEntry:
    """One source PDF added to the merge list."""

    def __init__(self, path: str):
        self.path     = path
        self.filename = Path(path).name
        self.doc      = fitz.open(path)
        self.total    = len(self.doc)
        self.selected = [True] * self.total
        self.chips_expanded = False

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    @property
    def selected_pages(self) -> list[int]:
        return [i for i, s in enumerate(self.selected) if s]

    @property
    def selected_count(self) -> int:
        return sum(self.selected)


# ── tab ───────────────────────────────────────────────────────────────────────

class MergePDFTab:
    """Singleton, closeable tab for combining multiple PDFs."""

    def __init__(
        self,
        page_ref:    ft.Page,
        on_close:    Callable[["MergePDFTab"], None],
        on_open_pdf: Callable[[str], None],
    ):
        self.page_ref    = page_ref
        self.on_close    = on_close
        self.on_open_pdf = on_open_pdf

        self._tab: ft.Tab | None = None
        self._entries: list[_PDFEntry] = []
        self._output_path: str | None  = None
        self._last_merged: str | None  = None
        self._thumb_cache: dict[tuple[str, int], str] = {}
        self._large_cache: dict[tuple[str, int], str] = {}  # 0.5x for lightbox
        self._merging = False

        # Flat list of (entry, original_page_idx) for each result page, in order.
        # Updated by _rebuild_preview; used by the lightbox dialog for navigation.
        self._preview_items: list[tuple[_PDFEntry, int]] = []
        self._dlg_cursor: int = 0

        # UI refs (set in _build)
        self._pdf_col:       ft.Column         | None = None
        self._preview_wrap:  ft.Row            | None = None
        self._preview_col:   ft.Column         | None = None
        self._preview_empty: ft.Container      | None = None
        self._status_text:   ft.Text           | None = None
        self._output_label:  ft.Text           | None = None
        self._merge_btn:     ft.ElevatedButton | None = None
        self._result_row:    ft.Container      | None = None
        self._progress_bar:  ft.ProgressBar    | None = None

        # Lightbox dialog refs (set in _build_dialog)
        self._dialog:      ft.AlertDialog | None = None
        self._dlg_img:     ft.Image       | None = None
        self._dlg_nav:     ft.Text        | None = None
        self._dlg_info:    ft.Column      | None = None
        self._dlg_prev:    ft.IconButton  | None = None
        self._dlg_next:    ft.IconButton  | None = None

        self._pick_pdfs   = ft.FilePicker(on_result=self._on_pdfs_picked)
        self._save_picker = ft.FilePicker(on_result=self._on_save_picked)
        self.page_ref.overlay.extend([self._pick_pdfs, self._save_picker])

        self._build()

    # ── public API ────────────────────────────────────────────────────────────

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.MERGE_TYPE, size=16, color=ft.Colors.PRIMARY),
                        ft.Text("Combinar PDFs", size=13, weight=ft.FontWeight.W_500),
                        ft.IconButton(
                            ft.Icons.CLOSE, icon_size=14,
                            on_click=lambda e: self.on_close(self),
                            tooltip="Cerrar pestaña",
                            style=ft.ButtonStyle(padding=ft.padding.all(0)),
                        ),
                    ],
                    spacing=4, tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                content=self.view,
            )
        return self._tab

    def get_tab_info(self) -> dict:
        return {
            "label": "Combinar PDFs",
            "icon": ft.Icons.MERGE_TYPE,
            "content": self.view,
            "closeable": True,
            "close_cb": lambda: self.on_close(self),
        }

    def close(self) -> None:
        for entry in self._entries:
            entry.close()
        self._thumb_cache.clear()
        self._large_cache.clear()
        for picker in (self._pick_pdfs, self._save_picker):
            try:
                self.page_ref.overlay.remove(picker)
            except ValueError:
                pass

    # ── thumbnail helpers ─────────────────────────────────────────────────────

    def _get_thumb(self, path: str, page: int) -> str | None:
        key = (path, page)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        try:
            with fitz.open(path) as doc:
                if page >= len(doc):
                    return None
                mat = fitz.Matrix(0.25, 0.25)
                pix = doc[page].get_pixmap(matrix=mat, alpha=False)
                b64 = base64.b64encode(pix.tobytes("png")).decode()
                self._thumb_cache[key] = b64
                return b64
        except Exception:
            return None

    def _get_large_thumb(self, path: str, page: int) -> str | None:
        """Return a cached base64 PNG at 0.5× scale — used by the lightbox dialog."""
        key = (path, page)
        if key in self._large_cache:
            return self._large_cache[key]
        try:
            with fitz.open(path) as doc:
                if page >= len(doc):
                    return None
                mat = fitz.Matrix(0.5, 0.5)
                pix = doc[page].get_pixmap(matrix=mat, alpha=False)
                b64 = base64.b64encode(pix.tobytes("png")).decode()
                self._large_cache[key] = b64
                return b64
        except Exception:
            return None

    def _render_thumbs_async(self, path: str, pages: list[int]) -> None:
        uncached = [p for p in pages if (path, p) not in self._thumb_cache]
        if not uncached:
            return

        def _worker() -> None:
            for pg in uncached:
                self._get_thumb(path, pg)
            self._rebuild_pdf_list()
            self._rebuild_preview()
            try:
                self.page_ref.update()
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # ─── HEADER ────────────────────────────────────────────────────────
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.MERGE_TYPE, size=32, color="#2E7D32"),
                    ft.Column([
                        ft.Text("Combinar PDFs", size=22, weight="bold", color="#1E2A38"),
                        ft.Text("Selecciona páginas de varios documentos y crea un PDF único", size=13, color="#666666"),
                    ], spacing=2)
                ],
                alignment="start",
                spacing=16,
            ),
            padding=ft.padding.only(left=20, top=20, right=20, bottom=10)
        )

        # ── left panel ────────────────────────────────────────────────────────
        self._pdf_col = ft.Column([], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

        left_panel = ft.Container(
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
                                on_click=self._clear_all,
                                tooltip="Quitar todos los PDFs de la lista",
                            ),
                            ft.ElevatedButton(
                                "Agregar", icon=ft.Icons.ADD,
                                on_click=lambda e: self._pick_pdfs.pick_files(
                                    dialog_title="Seleccionar PDFs para combinar",
                                    allowed_extensions=["pdf"],
                                    allow_multiple=True,
                                ),
                                style=ft.ButtonStyle(padding=12)
                            ),
                        ],
                        vertical_alignment="center",
                        spacing=8,
                    ),
                    ft.Divider(height=1, color="#E0E0E0"),
                    ft.Container(self._pdf_col, expand=True),
                ],
                spacing=12,
                expand=True,
            ),
            expand=True,
            padding=20,
            bgcolor="#FAFAFA",
            border=ft.border.only(right=ft.BorderSide(1, "#E0E0E0")),
        )

        # ── right panel ───────────────────────────────────────────────────────
        self._preview_wrap = ft.Row([], wrap=True, spacing=4, run_spacing=4)
        self._preview_empty = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.PREVIEW, size=40, color="#BDBDBD"),
                    ft.Text(
                        "Sin páginas seleccionadas",
                        size=13, color="#999999", italic=True,
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
        self._preview_col = ft.Column(
            [self._preview_empty],
            scroll="auto",
            expand=True,
        )

        self._status_text  = ft.Text("", size=12, color="#666666")
        self._progress_bar = ft.ProgressBar(
            visible=False, color="#2E7D32",
            bgcolor="#E0E0E0",
        )
        self._output_label = ft.Text(
            "Sin ruta de salida seleccionada",
            size=12, color="#666666",
            max_lines=1, overflow="ellipsis",
            expand=True,
        )
        self._merge_btn = ft.ElevatedButton(
            "Combinar y guardar",
            icon=ft.Icons.MERGE_TYPE,
            on_click=self._on_merge,
            disabled=True,
            style=ft.ButtonStyle(
                bgcolor="#2E7D32",
                padding=15
            )
        )
        self._result_row = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color="#2E7D32", size=18),
                    ft.Text(
                        "", size=12, expand=True,
                        overflow="ellipsis",
                        color="#1E2A38",
                    ),
                    ft.TextButton("Abrir", on_click=self._open_result, style=ft.ButtonStyle(color="#2E7D32")),
                ],
                spacing=8,
                vertical_alignment="center",
            ),
            visible=False,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor="#E8F5E9",
            border_radius=8,
        )

        right_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PREVIEW, color="#2E7D32", size=20),
                            ft.Text(
                                "Paso 2: Vista previa del resultado",
                                size=15, weight="bold",
                                color="#1E2A38",
                            ),
                            ft.Container(expand=True),
                            self._status_text,
                        ],
                        vertical_alignment="center",
                        spacing=8,
                    ),
                    ft.Divider(height=1, color="#E0E0E0"),
                    ft.Container(self._preview_col, expand=True),
                    self._progress_bar,
                    ft.Divider(height=1, color="#E0E0E0"),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SAVE_ALT, size=16, color="#666666"),
                            self._output_label,
                            ft.IconButton(
                                ft.Icons.FOLDER_OPEN_OUTLINED, icon_size=16,
                                tooltip="Elegir destino",
                                on_click=self._on_choose_output,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment="center",
                    ),
                    self._result_row,
                    ft.Row([self._merge_btn], spacing=10),
                ],
                spacing=12,
                expand=True,
            ),
            width=420,
            padding=20,
            bgcolor="#FAFAFA",
        )

        # ─── MAIN CONTAINER WITH HEADER ────────────────────────────────────
        main_content = ft.Row(
            [left_panel, right_panel],
            expand=True,
            spacing=0,
            vertical_alignment="stretch",
        )

        self.view = ft.Card(
            content=ft.Column([header, ft.Divider(height=1, color="#E0E0E0"), main_content], spacing=0),
            elevation=2,
            margin=10,
            expand=True
        )

        self._rebuild_pdf_list()
        self._build_dialog()

    def _build_dialog(self) -> None:
        """Create the lightbox AlertDialog (opened on thumbnail click in preview)."""
        self._dlg_img = ft.Image(
            width=300, height=420,
            fit=ft.ImageFit.CONTAIN,
            src_base64="",
        )
        self._dlg_nav = ft.Text(
            "", size=13, weight=ft.FontWeight.W_500,
            text_align=ft.TextAlign.CENTER,
        )
        self._dlg_prev = ft.IconButton(
            ft.Icons.CHEVRON_LEFT, icon_size=28,
            tooltip="Página anterior en el resultado",
            on_click=lambda e: self._dlg_navigate(-1),
        )
        self._dlg_next = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT, icon_size=28,
            tooltip="Página siguiente en el resultado",
            on_click=lambda e: self._dlg_navigate(+1),
        )

        # Two info lines updated on each navigation
        self._dlg_info = ft.Column(
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
                        # Page image
                        ft.Container(
                            content=self._dlg_img,
                            bgcolor="#E8ECF0",
                            border_radius=6,
                            alignment=ft.alignment.center,
                            width=300, height=420,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        # Navigation row
                        ft.Row(
                            [self._dlg_prev, self._dlg_nav, self._dlg_next],
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        # Info
                        self._dlg_info,
                    ],
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                width=320,
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: self.page_ref.close(self._dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    # ── PDF list management ───────────────────────────────────────────────────

    def _on_pdfs_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        added = False
        for f in e.files:
            if any(en.path == f.path for en in self._entries):
                continue
            try:
                entry = _PDFEntry(f.path)
                self._entries.append(entry)
                # Auto-suggest output path from the directory of the first PDF added
                if self._output_path is None:
                    suggested = str(Path(f.path).parent / "combinado.pdf")
                    self._output_path = suggested
                    if self._output_label is not None:
                        self._output_label.value = suggested
                added = True
            except Exception as ex:
                self.page_ref.snack_bar = ft.SnackBar(
                    ft.Text(f"Error abriendo {Path(f.path).name}: {ex}"), open=True,
                )
        if added:
            self._rebuild_pdf_list()
            self._rebuild_preview()
        self.page_ref.update()

    def _clear_all(self, e=None) -> None:
        for entry in self._entries:
            entry.close()
        self._entries.clear()
        self._thumb_cache.clear()
        self._large_cache.clear()
        self._rebuild_pdf_list()
        self._rebuild_preview()
        self.page_ref.update()

    def _rebuild_pdf_list(self) -> None:
        if not self._entries:
            self._pdf_col.controls = [
                ft.Container(
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
            ]
        else:
            self._pdf_col.controls = [
                self._make_entry_card(i, en)
                for i, en in enumerate(self._entries)
            ]
        self._update_merge_btn()

    def _make_entry_card(self, idx: int, entry: _PDFEntry) -> ft.Container:
        _TW, _TH = 54, 72

        def _chip(pg: int) -> ft.Container:
            sel = entry.selected[pg]
            thumb_b64 = self._get_thumb(entry.path, pg)

            if thumb_b64:
                thumb: ft.Control = ft.Image(
                    src_base64=thumb_b64, width=_TW, height=_TH,
                    fit=ft.ImageFit.COVER,
                )
            else:
                thumb = ft.Container(
                    width=_TW, height=_TH, bgcolor="#D0D0D0",
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
                on_click=lambda e, i=idx, p=pg: self._toggle_page(i, p),
                ink=True,
            )

        if entry.chips_expanded:
            visible_n = min(_CHIPS_MAX, entry.total)
        else:
            visible_n = min(_CHIPS_PREVIEW, entry.total)

        chips: list[ft.Control] = [_chip(p) for p in range(visible_n)]
        self._render_thumbs_async(entry.path, list(range(visible_n)))

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
                    on_click=lambda e, i=idx: self._toggle_chips_expand(i),
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
            value=_selection_to_range(entry.selected),
            hint_text="Ej: 1-5, 8, 10-15",
            label="Rango de páginas (1-based)",
            label_style=ft.TextStyle(size=11),
            text_size=12,
            dense=True,
            border_radius=6,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=6),
            expand=True,
            tooltip="Escribe un rango y presiona Enter o haz clic fuera para aplicar",
            on_blur=lambda e, i=idx: self._apply_range(i, e.control.value),
            on_submit=lambda e, i=idx: self._apply_range(i, e.control.value),
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
                                on_click=lambda e, i=idx: self._move_entry(i, -1),
                                disabled=(idx == 0),
                            ),
                            ft.IconButton(
                                ft.Icons.ARROW_DOWNWARD, icon_size=14,
                                tooltip="Mover abajo",
                                on_click=lambda e, i=idx: self._move_entry(i, +1),
                                disabled=(idx == len(self._entries) - 1),
                            ),
                            ft.IconButton(
                                ft.Icons.DELETE_OUTLINE, icon_size=14,
                                tooltip="Quitar de la lista",
                                icon_color=ft.Colors.ERROR,
                                on_click=lambda e, i=idx: self._remove_entry(i),
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
                                on_click=lambda e, i=idx: self._select_all_pages(i, True),
                            ),
                            ft.TextButton(
                                "Ninguna", icon=ft.Icons.DESELECT,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, i=idx: self._select_all_pages(i, False),
                            ),
                            ft.TextButton(
                                "Invertir", icon=ft.Icons.SWAP_HORIZ,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=11)),
                                on_click=lambda e, i=idx: self._invert_pages(i),
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

    # ── page selection callbacks ──────────────────────────────────────────────

    def _toggle_page(self, entry_idx: int, page: int) -> None:
        self._entries[entry_idx].selected[page] ^= True
        self._rebuild_pdf_list()
        self._rebuild_preview()
        self.page_ref.update()

    def _select_all_pages(self, entry_idx: int, value: bool) -> None:
        entry = self._entries[entry_idx]
        entry.selected = [value] * entry.total
        self._rebuild_pdf_list()
        self._rebuild_preview()
        self.page_ref.update()

    def _invert_pages(self, entry_idx: int) -> None:
        entry = self._entries[entry_idx]
        entry.selected = [not s for s in entry.selected]
        self._rebuild_pdf_list()
        self._rebuild_preview()
        self.page_ref.update()

    def _apply_range(self, entry_idx: int, text: str) -> None:
        entry = self._entries[entry_idx]
        entry.selected = _parse_range(text, entry.total)
        self._rebuild_pdf_list()
        self._rebuild_preview()
        self.page_ref.update()

    def _toggle_chips_expand(self, entry_idx: int) -> None:
        self._entries[entry_idx].chips_expanded ^= True
        self._rebuild_pdf_list()
        self.page_ref.update()

    def _move_entry(self, idx: int, delta: int) -> None:
        new_idx = idx + delta
        if 0 <= new_idx < len(self._entries):
            self._entries[idx], self._entries[new_idx] = (
                self._entries[new_idx], self._entries[idx]
            )
            self._rebuild_pdf_list()
            self._rebuild_preview()
            self.page_ref.update()

    def _remove_entry(self, idx: int) -> None:
        entry = self._entries.pop(idx)
        for pg in range(entry.total):
            self._thumb_cache.pop((entry.path, pg), None)
        entry.close()
        self._rebuild_pdf_list()
        self._rebuild_preview()
        self.page_ref.update()

    # ── preview panel ─────────────────────────────────────────────────────────

    def _rebuild_preview(self) -> None:
        items: list[ft.Control] = []
        flat:  list[tuple[_PDFEntry, int]] = []
        total = 0

        for entry in self._entries:
            for pg in entry.selected_pages:
                flat_idx = total   # 0-based index in result
                total += 1
                thumb_b64 = self._get_thumb(entry.path, pg)

                if thumb_b64:
                    thumb_ctrl: ft.Control = ft.Image(
                        src_base64=thumb_b64,
                        width=56, height=76,
                        fit=ft.ImageFit.COVER,
                    )
                else:
                    thumb_ctrl = ft.Container(
                        width=56, height=76, bgcolor="#E0E0E0",
                        content=ft.Icon(
                            ft.Icons.PICTURE_AS_PDF, size=18, color=ft.Colors.OUTLINE,
                        ),
                        alignment=ft.alignment.center,
                    )

                # Sequential number badge (top-right)
                seq_badge = ft.Container(
                    content=ft.Text(
                        str(total), size=8, color="white",
                        weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    bgcolor="#000000CC",
                    padding=ft.padding.symmetric(horizontal=3, vertical=1),
                    right=0, top=0,
                    border_radius=ft.border_radius.only(bottom_left=3),
                )
                # Original page badge (bottom-left)
                pg_badge = ft.Container(
                    content=ft.Text(
                        f"p{pg + 1}", size=7, color="white",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    bgcolor="#1976D2CC",
                    padding=ft.padding.symmetric(horizontal=3, vertical=1),
                    left=0, bottom=0,
                    border_radius=ft.border_radius.only(top_right=3),
                )

                flat.append((entry, pg))
                items.append(
                    ft.Container(
                        content=ft.Stack([thumb_ctrl, seq_badge, pg_badge]),
                        width=60,
                        height=80,
                        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=4,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ink=True,
                        ink_color="#00000018",
                        tooltip="Clic para ampliar",
                        on_click=lambda e, i=flat_idx: self._open_preview_dialog(i),
                    )
                )

        self._preview_items = flat

        if not items:
            self._preview_col.controls = [self._preview_empty]
        else:
            self._preview_wrap.controls = items
            self._preview_col.controls  = [self._preview_wrap]

        if self._status_text is not None:
            self._status_text.value = f"{total} página(s)" if total > 0 else ""
        self._update_merge_btn()

    # ── lightbox dialog ───────────────────────────────────────────────────────

    def _open_preview_dialog(self, flat_idx: int) -> None:
        if not self._preview_items or self._dialog is None:
            return
        self._dlg_cursor = max(0, min(flat_idx, len(self._preview_items) - 1))
        self._dlg_update_content()
        self.page_ref.open(self._dialog)

    def _dlg_navigate(self, delta: int) -> None:
        if not self._preview_items:
            return
        self._dlg_cursor = max(0, min(
            self._dlg_cursor + delta, len(self._preview_items) - 1
        ))
        self._dlg_update_content()
        self.page_ref.update()

    def _dlg_update_content(self) -> None:
        """Refresh the dialog image and info text for the current cursor position."""
        if not self._preview_items or self._dialog is None:
            return

        total = len(self._preview_items)
        idx   = self._dlg_cursor
        entry, orig_pg = self._preview_items[idx]

        # Load large thumbnail (synchronous — single page render is fast enough)
        large_b64 = self._get_large_thumb(entry.path, orig_pg)
        if large_b64:
            self._dlg_img.src_base64 = large_b64
            self._dlg_img.src        = None
        else:
            self._dlg_img.src_base64 = None
            self._dlg_img.src        = None

        # Navigation counter
        self._dlg_nav.value = f"{idx + 1} / {total}"

        # Prev / next button state
        self._dlg_prev.disabled = idx == 0
        self._dlg_next.disabled = idx == total - 1

        # Info lines
        info_controls = self._dlg_info.controls
        info_controls[0].value = entry.filename
        info_controls[1].value = f"Página original: {orig_pg + 1} de {entry.total}"
        info_controls[2].value = f"Posición en resultado: {idx + 1} de {total}"

    def _update_merge_btn(self) -> None:
        if self._merge_btn is None:
            return
        total = sum(en.selected_count for en in self._entries)
        self._merge_btn.disabled = total == 0 or self._merging
        self._merge_btn.text = (
            f"Combinar {total} páginas" if total > 0 else "Combinar y guardar"
        )

    # ── output path ───────────────────────────────────────────────────────────

    def _on_choose_output(self, e=None) -> None:
        self._save_picker.save_file(
            dialog_title="Guardar PDF combinado",
            file_name="combinado.pdf",
            allowed_extensions=["pdf"],
        )

    def _on_save_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        self._output_path = e.path
        if self._output_label is not None:
            self._output_label.value = e.path
        if self._result_row is not None:
            self._result_row.visible = False
        self.page_ref.update()

    # ── merge operation ───────────────────────────────────────────────────────

    def _on_merge(self, e=None) -> None:
        if not self._output_path:
            self._on_choose_output()
            return

        total_selected = sum(en.selected_count for en in self._entries)
        if total_selected == 0:
            self.page_ref.snack_bar = ft.SnackBar(
                ft.Text("No hay páginas seleccionadas"), open=True,
            )
            self.page_ref.update()
            return

        # Prevent overwriting an input file
        for en in self._entries:
            if Path(en.path).resolve() == Path(self._output_path).resolve():
                self.page_ref.snack_bar = ft.SnackBar(
                    ft.Text(
                        f"El archivo de salida no puede ser igual a un archivo de entrada ({en.filename})"
                    ),
                    open=True,
                )
                self.page_ref.update()
                return

        self._merging = True
        if self._merge_btn:
            self._merge_btn.disabled = True
        if self._status_text:
            self._status_text.value = "Preparando…"
        if self._result_row:
            self._result_row.visible = False
        if self._progress_bar:
            self._progress_bar.value = None   # indeterminate spinner
            self._progress_bar.visible = True
        self.page_ref.update()

        out_path   = self._output_path
        snapshot   = [(en.path, list(en.selected_pages)) for en in self._entries]
        total_pages = sum(len(pages) for _, pages in snapshot)

        def _worker() -> None:
            try:
                out_doc = fitz.open()
                done = 0
                last_update = time.monotonic()

                for src_path, pages in snapshot:
                    with fitz.open(src_path) as src:
                        for pg in pages:
                            out_doc.insert_pdf(src, from_page=pg, to_page=pg, start_at=-1)
                            done += 1
                            now = time.monotonic()
                            if now - last_update >= 0.2:
                                last_update = now
                                pct = done / total_pages
                                if self._progress_bar:
                                    self._progress_bar.value = pct
                                if self._status_text:
                                    self._status_text.value = (
                                        f"Combinando… {done}/{total_pages} páginas"
                                    )
                                try:
                                    self.page_ref.update()
                                except Exception:
                                    pass

                out_doc.save(out_path, garbage=4, deflate=True)
                out_doc.close()

                self._last_merged = out_path
                self._merging = False
                if self._progress_bar:
                    self._progress_bar.value = 1.0
                if self._status_text:
                    self._status_text.value = f"Completado — {total_pages} páginas"
                if self._result_row is not None and self._result_row.content is not None:
                    self._result_row.content.controls[1].value = (
                        f"Guardado: {Path(out_path).name}"
                    )
                    self._result_row.visible = True
                self._update_merge_btn()
                self.page_ref.snack_bar = ft.SnackBar(
                    ft.Text(f"PDF combinado guardado: {Path(out_path).name}"), open=True,
                )
                try:
                    self.page_ref.update()
                except Exception:
                    pass

                time.sleep(1.5)
                if self._progress_bar:
                    self._progress_bar.visible = False
                try:
                    self.page_ref.update()
                except Exception:
                    pass

            except Exception as ex:
                self._merging = False
                if self._progress_bar:
                    self._progress_bar.visible = False
                if self._status_text:
                    self._status_text.value = "Error al combinar"
                self._update_merge_btn()
                self.page_ref.snack_bar = ft.SnackBar(
                    ft.Text(f"Error al combinar PDFs: {ex}"), open=True,
                )
                try:
                    self.page_ref.update()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _open_result(self, e=None) -> None:
        if self._last_merged:
            self.on_open_pdf(self._last_merged)
