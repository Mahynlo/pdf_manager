"""MergePDFTab — combine multiple PDFs with visual per-page selection."""
from __future__ import annotations

import base64
import threading
from pathlib import Path
from typing import Callable

import flet as ft
import fitz

# Number of page chips shown before "show more" toggle
_CHIPS_PREVIEW = 30
# Hard cap: never render more than this many thumbnail chips at once
_CHIPS_MAX = 120


class _PDFEntry:
    """One source PDF added to the merge list."""

    def __init__(self, path: str):
        self.path = path
        self.filename = Path(path).name
        self.doc = fitz.open(path)
        self.total = len(self.doc)
        self.selected = [True] * self.total   # all pages selected by default
        self.chips_expanded = False                  # show all chips or just first _CHIPS_PREVIEW

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
        self._thumb_cache: dict[tuple[str, int], str] = {}  # (path, page) -> base64 PNG

        # UI refs (set in _build)
        self._pdf_col:      ft.Column         | None = None
        self._preview_list: ft.ListView       | None = None
        self._status_text:  ft.Text           | None = None
        self._output_label: ft.Text           | None = None
        self._merge_btn:    ft.ElevatedButton | None = None
        self._result_row:   ft.Container      | None = None

        # File pickers
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

    def close(self) -> None:
        """Called by main.py when the tab is closed — clean up resources."""
        for entry in self._entries:
            entry.close()
        self._thumb_cache.clear()
        for picker in (self._pick_pdfs, self._save_picker):
            try:
                self.page_ref.overlay.remove(picker)
            except ValueError:
                pass

    def _get_thumb(self, path: str, page: int) -> str | None:
        """Return a cached base64 PNG thumbnail (opens its own fitz doc — thread-safe)."""
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

    def _render_thumbs_async(self, path: str, pages: list[int]) -> None:
        """Render uncached thumbnails in a daemon thread, then refresh the UI once."""
        uncached = [p for p in pages if (path, p) not in self._thumb_cache]
        if not uncached:
            return

        def _worker() -> None:
            for pg in uncached:
                self._get_thumb(path, pg)
            # Rebuild once all thumbnails for this batch are ready
            self._rebuild_pdf_list()
            self._rebuild_preview()
            try:
                self.page_ref.update()
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # ── left panel: PDF source list ───────────────────────────────────────
        self._pdf_col = ft.Column([], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

        left_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ft.Colors.ERROR, size=20),
                            ft.Text(
                                "PDFs a combinar", size=15, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ON_SURFACE,
                            ),
                            ft.Container(expand=True),
                            ft.ElevatedButton(
                                "Agregar PDF", icon=ft.Icons.ADD,
                                on_click=lambda e: self._pick_pdfs.pick_files(
                                    dialog_title="Seleccionar PDFs para combinar",
                                    allowed_extensions=["pdf"],
                                    allow_multiple=True,
                                ),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Container(self._pdf_col, expand=True),
                ],
                spacing=8,
                expand=True,
            ),
            expand=True,
            padding=ft.padding.all(16),
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.only(right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        # ── right panel: preview + output controls ────────────────────────────
        self._preview_list = ft.ListView([], spacing=2, expand=True)
        self._status_text  = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self._output_label = ft.Text(
            "Sin ruta de salida seleccionada",
            size=12, color=ft.Colors.ON_SURFACE_VARIANT,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
        )
        self._merge_btn = ft.ElevatedButton(
            "Combinar y guardar",
            icon=ft.Icons.MERGE_TYPE,
            on_click=self._on_merge,
            disabled=True,
        )
        # Result banner (shown after a successful merge)
        self._result_row = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=ft.Colors.PRIMARY, size=18),
                    ft.Text(
                        "", size=12, expand=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        color=ft.Colors.ON_SURFACE,
                    ),
                    ft.TextButton("Abrir", on_click=self._open_result),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=ft.Colors.PRIMARY_CONTAINER,
            border_radius=8,
        )

        right_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PREVIEW, color=ft.Colors.PRIMARY, size=20),
                            ft.Text(
                                "Vista previa del resultado", size=15,
                                weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE,
                            ),
                            ft.Container(expand=True),
                            self._status_text,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Container(self._preview_list, expand=True),
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SAVE_ALT, size=16,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                            self._output_label,
                            ft.IconButton(
                                ft.Icons.FOLDER_OPEN_OUTLINED, icon_size=16,
                                tooltip="Elegir destino",
                                on_click=self._on_choose_output,
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._result_row,
                    ft.Row([self._merge_btn], alignment=ft.MainAxisAlignment.END),
                ],
                spacing=8,
                expand=True,
            ),
            width=400,
            padding=ft.padding.all(16),
            bgcolor=ft.Colors.SURFACE,
        )

        self.view = ft.Row(
            [left_panel, right_panel],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        self._rebuild_pdf_list()

    # ── PDF list management ───────────────────────────────────────────────────

    def _on_pdfs_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        added = False
        for f in e.files:
            if any(en.path == f.path for en in self._entries):
                continue
            try:
                self._entries.append(_PDFEntry(f.path))
                added = True
            except Exception as ex:
                self.page_ref.snack_bar = ft.SnackBar(
                    ft.Text(f"Error abriendo {Path(f.path).name}: {ex}"), open=True,
                )
        if added:
            self._rebuild_pdf_list()
            self._rebuild_preview()
        self.page_ref.update()

    def _rebuild_pdf_list(self) -> None:
        if not self._entries:
            self._pdf_col.controls = [
                ft.Container(
                    ft.Text(
                        'Agrega PDFs con el botón "Agregar PDF"',
                        size=13, color=ft.Colors.OUTLINE, italic=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=ft.padding.symmetric(vertical=40, horizontal=16),
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
        """Build the interactive card for one source PDF."""

        _TW, _TH = 54, 72  # thumbnail chip dimensions

        def _chip(pg: int) -> ft.Container:
            sel = entry.selected[pg]
            thumb_b64 = self._get_thumb(entry.path, pg)

            if thumb_b64:
                thumb: ft.Control = ft.Image(
                    src_base64=thumb_b64,
                    width=_TW, height=_TH,
                    fit=ft.ImageFit.COVER,
                )
            else:
                thumb = ft.Container(
                    width=_TW, height=_TH,
                    bgcolor="#D0D0D0",
                    content=ft.Icon(ft.Icons.PICTURE_AS_PDF, size=20, color=ft.Colors.OUTLINE),
                    alignment=ft.alignment.center,
                )

            # Semi-transparent blue overlay when selected
            sel_overlay = ft.Container(
                bgcolor="#1976D244" if sel else None,
                left=0, right=0, top=0, bottom=0,
            )

            # Page number badge pinned to the bottom
            num_badge = ft.Container(
                content=ft.Text(
                    str(pg + 1), size=9,
                    color="white",
                    text_align=ft.TextAlign.CENTER,
                    weight=ft.FontWeight.BOLD,
                ),
                bgcolor="#000000BB",
                padding=ft.padding.symmetric(horizontal=3, vertical=1),
                alignment=ft.alignment.center,
                left=0, right=0, bottom=0,
            )

            return ft.Container(
                content=ft.Stack([thumb, sel_overlay, num_badge]),
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

        # Dispatch background rendering for chips not yet in cache
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
            # If the PDF exceeds the hard cap, show a notice
            if entry.chips_expanded and entry.total > _CHIPS_MAX:
                hidden = entry.total - _CHIPS_MAX
                chips.append(
                    ft.Text(
                        f"... y {hidden} páginas más — usa «Todas» o «Ninguna» para incluirlas.",
                        size=10,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        italic=True,
                    )
                )

        return ft.Container(
            content=ft.Column(
                [
                    # ── header row ────────────────────────────────────────────
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
                    # ── quick-select row ──────────────────────────────────────
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
                            ft.Container(expand=True),
                            ft.Text(
                                f"{entry.selected_count}/{entry.total} págs.",
                                size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # ── page chips ────────────────────────────────────────────
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
        rows: list[ft.Control] = []
        total = 0
        for entry in self._entries:
            for pg in entry.selected_pages:
                total += 1
                thumb_b64 = self._get_thumb(entry.path, pg)
                if thumb_b64:
                    thumb_ctrl: ft.Control = ft.Image(
                        src_base64=thumb_b64,
                        width=58,
                        height=78,
                        fit=ft.ImageFit.CONTAIN,
                        border_radius=3,
                    )
                else:
                    thumb_ctrl = ft.Container(
                        width=58, height=78,
                        bgcolor="#E0E0E0",
                        border_radius=3,
                        content=ft.Icon(
                            ft.Icons.PICTURE_AS_PDF, size=22,
                            color=ft.Colors.OUTLINE,
                        ),
                        alignment=ft.alignment.center,
                    )

                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    str(total), size=11, width=26,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                                ft.Container(
                                    content=thumb_ctrl,
                                    border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                                    border_radius=3,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            entry.filename, size=11,
                                            weight=ft.FontWeight.W_500,
                                            max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                            color=ft.Colors.ON_SURFACE,
                                        ),
                                        ft.Text(
                                            f"Página {pg + 1}", size=10,
                                            color=ft.Colors.ON_SURFACE_VARIANT,
                                        ),
                                    ],
                                    expand=True,
                                    spacing=3,
                                    alignment=ft.MainAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.padding.symmetric(horizontal=8, vertical=6),
                        border_radius=6,
                        bgcolor="#F0F0F0" if total % 2 == 0 else None,
                    )
                )

        if not rows:
            rows.append(
                ft.Container(
                    ft.Text(
                        "Sin páginas seleccionadas",
                        size=12, color=ft.Colors.OUTLINE,
                        italic=True, text_align=ft.TextAlign.CENTER,
                    ),
                    padding=ft.padding.symmetric(vertical=24),
                    alignment=ft.alignment.center,
                )
            )

        self._preview_list.controls = rows
        if self._status_text is not None:
            self._status_text.value = f"{total} página(s)" if total > 0 else ""
        self._update_merge_btn()

    def _update_merge_btn(self) -> None:
        if self._merge_btn is None:
            return
        self._merge_btn.disabled = sum(en.selected_count for en in self._entries) == 0

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
        if sum(en.selected_count for en in self._entries) == 0:
            self.page_ref.snack_bar = ft.SnackBar(
                ft.Text("No hay páginas seleccionadas"), open=True,
            )
            self.page_ref.update()
            return

        if self._merge_btn:
            self._merge_btn.disabled = True
        if self._status_text:
            self._status_text.value = "Combinando…"
        if self._result_row:
            self._result_row.visible = False
        self.page_ref.update()

        out_path = self._output_path
        # Snapshot paths + pages before threading (avoids cross-thread access to _entries)
        snapshot = [(en.path, list(en.selected_pages)) for en in self._entries]

        def _worker() -> None:
            try:
                out_doc = fitz.open()
                for src_path, pages in snapshot:
                    with fitz.open(src_path) as src:
                        for pg in pages:
                            out_doc.insert_pdf(src, from_page=pg, to_page=pg, start_at=-1)
                out_doc.save(out_path, garbage=4, deflate=True)
                out_doc.close()

                self._last_merged = out_path
                if self._status_text:
                    self._status_text.value = "Combinación completada"
                # Update result banner
                if self._result_row is not None and self._result_row.content is not None:
                    label = self._result_row.content.controls[1]
                    label.value = f"Guardado: {Path(out_path).name}"
                    self._result_row.visible = True
                self._update_merge_btn()
                self.page_ref.snack_bar = ft.SnackBar(
                    ft.Text(f"PDF combinado guardado: {Path(out_path).name}"),
                    open=True,
                )
                try:
                    self.page_ref.update()
                except Exception:
                    pass

            except Exception as ex:
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
