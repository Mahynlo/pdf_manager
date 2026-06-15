"""MergePDFTab — Flet tab that combines multiple PDFs with per-page selection.

This module is the coordinator: it owns the shared state (loaded entries,
output path, thumbnail caches, merge flag) and the file pickers / merge worker,
and wires together the UI components in `widgets/`. The widget trees themselves
live in those components; the PDF logic lives in `engine.py` / `model.py`.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import flet as ft

from . import engine
from .engine import (
    MergeInvalidPasswordError,
    MergePasswordRequiredError,
    MergePermissionDeniedError,
)
from .model import PDFEntry
from .thumbnails import ThumbnailCache
from .widgets import EntryCard, LightboxDialog, PasswordDialog, PdfListPanel, PreviewGrid
from .widgets.preview_grid import PREVIEW_MAX_PAGES

_THUMB_SCALE = 0.25   # selection chips / preview grid
_LARGE_SCALE = 0.5    # lightbox dialog


class MergePDFTab:
    """Singleton, closeable tab for combining multiple PDFs."""

    def __init__(
        self,
        page_ref:    ft.Page,
        on_close:    Callable[["MergePDFTab"], None],
        on_open_pdf: Callable[[str], None],
        on_open_security: Callable[[], None] | None = None,
    ):
        self.page_ref    = page_ref
        self.on_close    = on_close
        self.on_open_pdf = on_open_pdf
        self.on_open_security = on_open_security

        # ── shared state ────────────────────────────────────────────────────
        self._tab: ft.Tab | None = None
        self._entries: list[PDFEntry] = []
        self._output_path: str | None = None
        self._last_merged: str | None = None
        self._thumbs       = ThumbnailCache(_THUMB_SCALE)
        self._large_thumbs = ThumbnailCache(_LARGE_SCALE)
        self._merging = False
        self._pending_password_paths: list[str] = []

        # Right-panel controls tied to merge state (built in _build).
        self._status_text:  ft.Text           | None = None
        self._output_label: ft.Text           | None = None
        self._merge_btn:    ft.ElevatedButton  | None = None
        self._result_row:   ft.Container       | None = None
        self._progress_bar: ft.ProgressBar     | None = None

        # ── components ──────────────────────────────────────────────────────
        self._entry_card = entry_card = EntryCard(
            self._thumbs,
            on_toggle_page=self._toggle_page,
            on_select_all=self._select_all_pages,
            on_invert=self._invert_pages,
            on_apply_range=self._apply_range,
            on_toggle_chips=self._toggle_chips_expand,
            on_move=self._move_entry,
            on_remove=self._remove_entry,
            on_request_thumbs=self._render_thumbs_async,
            on_restore_order=self._restore_order,
        )
        self._pdf_list = PdfListPanel(
            on_add=self._open_picker,
            on_clear=self._clear_all,
            entry_card=entry_card,
        )
        self._preview  = PreviewGrid(
            self._thumbs,
            on_open=self._open_preview_dialog,
            on_request_thumbs=self._render_thumbs_async,
            on_reorder=self._reorder_page,
        )
        self._lightbox = LightboxDialog(self.page_ref, self._large_thumbs)
        self._pwd      = PasswordDialog(
            self.page_ref,
            on_confirm=self._confirm_add_protected_pdf,
            on_cancel=self._cancel_add_protected_pdf,
            on_open_security=self._open_security_from_merge,
        )

        # ── file pickers ────────────────────────────────────────────────────
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
        self._thumbs.clear()
        self._large_thumbs.clear()
        self._entry_card.clear()
        self._preview.clear()
        for picker in (self._pick_pdfs, self._save_picker):
            try:
                self.page_ref.overlay.remove(picker)
            except ValueError:
                pass

    # ── refresh helpers ─────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._pdf_list.rebuild(self._entries)
        self._update_merge_btn()

    def _refresh_preview(self) -> None:
        total = self._preview.rebuild(self._entries)
        if self._status_text is not None:
            if total <= 0:
                self._status_text.value = ""
                self._status_text.color = "onSurfaceVariant"
            elif self._preview.overflow > 0:
                self._status_text.value = (
                    f"{total} páginas · vista previa limitada a {PREVIEW_MAX_PAGES}"
                )
                self._status_text.color = "#F57C00"
            else:
                self._status_text.value = f"{total} página(s)"
                self._status_text.color = "onSurfaceVariant"
        self._update_merge_btn()

    def _render_thumbs_async(self, path: str, pages: list[int], password: str | None = None) -> None:
        uncached = [p for p in pages if not self._thumbs.has(path, p)]
        if not uncached:
            return

        def _worker() -> None:
            # Una sola apertura del PDF para todas las páginas pendientes.
            self._thumbs.warm_many(path, uncached, password=password)
            self._refresh_list()
            self._refresh_preview()
            try:
                self.page_ref.update()
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    # ── layout ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.MERGE_TYPE, size=32, color="#2E7D32"),
                    ft.Column([
                        ft.Text("Combinar PDFs", size=22, weight="bold", color="onSurface"),
                        ft.Text("Selecciona páginas de varios documentos y crea un PDF único", size=13, color="onSurfaceVariant"),
                    ], spacing=2)
                ],
                alignment="start",
                spacing=16,
            ),
            padding=ft.padding.only(left=20, top=20, right=20, bottom=10)
        )

        self._status_text  = ft.Text("", size=12, color="onSurfaceVariant")
        self._progress_bar = ft.ProgressBar(visible=False, color="#2E7D32", bgcolor="outlineVariant")
        self._output_label = ft.Text(
            "Sin ruta de salida seleccionada",
            size=12, color="onSurfaceVariant", max_lines=1, overflow="ellipsis", expand=True,
        )
        self._merge_btn = ft.ElevatedButton(
            "Combinar y guardar",
            icon=ft.Icons.MERGE_TYPE,
            on_click=self._on_merge,
            disabled=True,
            tooltip="Combina las páginas seleccionadas y guarda el nuevo PDF",
            style=ft.ButtonStyle(
                bgcolor="#026E07", padding=15, color="#F1E7E7",
                text_style=ft.TextStyle(size=12),
            )
        )
        self._result_row = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color="#2E7D32", size=18),
                    ft.Text("", size=12, expand=True, overflow="ellipsis", color="onSurface"),
                    ft.TextButton("Abrir", on_click=self._open_result, style=ft.ButtonStyle(color="#2E7D32")),
                ],
                spacing=8,
                vertical_alignment="center",
            ),
            visible=False,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.GREEN),
            border_radius=8,
        )

        right_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PREVIEW, color="#2E7D32", size=20),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Paso 2: Vista previa del resultado",
                                        size=15, weight="bold", color="onSurface",
                                    ),
                                    ft.Text(
                                        "Arrastra una página para reordenarla dentro de su PDF",
                                        size=11, color="onSurfaceVariant", italic=True,
                                    ),
                                ],
                                spacing=0,
                            ),
                            ft.Container(expand=True),
                            self._status_text,
                        ],
                        vertical_alignment="center",
                        spacing=8,
                    ),
                    ft.Divider(height=1, color="outlineVariant"),
                    ft.Container(self._preview.control, expand=True),
                    self._progress_bar,
                    ft.Divider(height=1, color="outlineVariant"),
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.SAVE_ALT, size=16, color="onSurfaceVariant"),
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
            bgcolor="surfaceVariant",
        )

        main_content = ft.Row(
            [self._pdf_list.control, right_panel],
            expand=True,
            spacing=0,
            vertical_alignment="stretch",
        )

        self.view = ft.Card(
            content=ft.Column([header, ft.Divider(height=1, color="outlineVariant"), main_content], spacing=0),
            elevation=2,
            margin=10,
            expand=True
        )

        self._refresh_list()

    # ── password dialog flow ──────────────────────────────────────────────────

    def _show_next_password_prompt(self, error_message: str | None = None) -> None:
        if not self._pending_password_paths:
            return
        self._pwd.prompt(Path(self._pending_password_paths[0]).name, error_message)

    def _cancel_add_protected_pdf(self) -> None:
        if self._pending_password_paths:
            self._pending_password_paths.pop(0)
        self._pwd.close()
        self._show_next_password_prompt()

    def _open_security_from_merge(self) -> None:
        if self._pending_password_paths:
            self._pending_password_paths.pop(0)
        self._pwd.close()
        if self.on_open_security is not None:
            self.on_open_security()
        self._show_next_password_prompt()

    def _confirm_add_protected_pdf(self, password: str) -> None:
        if not self._pending_password_paths:
            self._pwd.close()
            return

        password = (password or "").strip()
        if not password:
            self._pwd.show_error("Ingresa la contraseña")
            return

        src_path = self._pending_password_paths[0]
        try:
            entry = engine.open_entry(src_path, password=password)
        except MergeInvalidPasswordError:
            self._show_next_password_prompt("Contraseña incorrecta")
            self.page_ref.update()
            return
        except MergePermissionDeniedError:
            self._snack(
                f"{Path(src_path).name} no permite ensamblaje. Usa Seguridad para crear una copia desbloqueada."
            )
            self._pending_password_paths.pop(0)
            self._pwd.close()
            self._show_next_password_prompt()
            self.page_ref.update()
            return
        except Exception as ex:
            self._snack(f"Error abriendo {Path(src_path).name}: {ex}")
            self._pending_password_paths.pop(0)
            self._pwd.close()
            self._show_next_password_prompt()
            self.page_ref.update()
            return

        self._entries.append(entry)
        self._suggest_output_path(src_path)
        self._pending_password_paths.pop(0)
        self._pwd.close()
        self._refresh_list()
        self._refresh_preview()
        self._show_next_password_prompt()
        self.page_ref.update()

    # ── PDF list management ───────────────────────────────────────────────────

    def _snack(self, message: str) -> None:
        self.page_ref.snack_bar = ft.SnackBar(ft.Text(message), open=True)

    def _suggest_output_path(self, src_path: str) -> None:
        """Default the output path to <dir-of-first-pdf>/combinado.pdf."""
        if self._output_path is not None:
            return
        suggested = str(Path(src_path).parent / "combinado.pdf")
        self._output_path = suggested
        if self._output_label is not None:
            self._output_label.value = suggested

    def _open_picker(self) -> None:
        self._pick_pdfs.pick_files(
            dialog_title="Seleccionar PDFs para combinar",
            allowed_extensions=["pdf"],
            allow_multiple=True,
        )

    def _on_pdfs_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        added = False
        for f in e.files:
            normalized_path = engine.normalize_path(f.path)
            if any(engine.normalize_path(en.path) == normalized_path for en in self._entries):
                continue
            try:
                entry = engine.open_entry(normalized_path)
                self._entries.append(entry)
                self._suggest_output_path(normalized_path)
                added = True
            except MergePasswordRequiredError:
                if normalized_path not in self._pending_password_paths:
                    self._pending_password_paths.append(normalized_path)
            except MergePermissionDeniedError:
                self._snack(f"{Path(normalized_path).name} está protegido y no permite ensamblaje.")
            except Exception as ex:
                self._snack(f"Error abriendo {Path(normalized_path).name}: {ex}")
        if added:
            self._refresh_list()
            self._refresh_preview()
        if self._pending_password_paths:
            self._show_next_password_prompt()
        self.page_ref.update()

    def _clear_all(self) -> None:
        for entry in self._entries:
            entry.close()
        self._entries.clear()
        self._thumbs.clear()
        self._large_thumbs.clear()
        self._entry_card.clear()
        self._preview.clear()
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    # ── page selection callbacks ──────────────────────────────────────────────

    def _toggle_page(self, entry_idx: int, page: int) -> None:
        self._entries[entry_idx].toggle(page)
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    def _select_all_pages(self, entry_idx: int, value: bool) -> None:
        self._entries[entry_idx].set_all(value)
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    def _invert_pages(self, entry_idx: int) -> None:
        self._entries[entry_idx].invert()
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    def _apply_range(self, entry_idx: int, text: str) -> None:
        self._entries[entry_idx].set_range(text)
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    def _reorder_page(self, entry: PDFEntry, from_page: int, to_page: int) -> None:
        """Mueve una página dentro de un mismo PDF (arrastrar y soltar)."""
        entry.move_page(from_page, to_page)
        self._refresh_preview()
        self.page_ref.update()

    def _restore_order(self, entry_idx: int) -> None:
        self._entries[entry_idx].restore_order()
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    def _toggle_chips_expand(self, entry_idx: int) -> None:
        self._entries[entry_idx].chips_expanded ^= True
        self._refresh_list()
        self.page_ref.update()

    def _move_entry(self, idx: int, delta: int) -> None:
        new_idx = idx + delta
        if 0 <= new_idx < len(self._entries):
            self._entries[idx], self._entries[new_idx] = (
                self._entries[new_idx], self._entries[idx]
            )
            self._refresh_list()
            self._refresh_preview()
            self.page_ref.update()

    def _remove_entry(self, idx: int) -> None:
        entry = self._entries.pop(idx)
        self._thumbs.prune_path(entry.path)
        self._entry_card.prune_path(entry.path)
        self._preview.prune_path(entry.path)
        entry.close()
        self._refresh_list()
        self._refresh_preview()
        self.page_ref.update()

    # ── lightbox ───────────────────────────────────────────────────────────────

    def _open_preview_dialog(self, flat_idx: int) -> None:
        self._lightbox.open(self._preview.items, flat_idx)

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
            self._snack("No hay páginas seleccionadas")
            self.page_ref.update()
            return

        # Prevent overwriting an input file
        for en in self._entries:
            if Path(en.path).resolve() == Path(self._output_path).resolve():
                self._snack(
                    f"El archivo de salida no puede ser igual a un archivo de entrada ({en.filename})"
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

        out_path = self._output_path
        # Immutable snapshot — UI changes during the merge can't affect the result.
        sources  = [en.as_source() for en in self._entries]

        def _worker() -> None:
            last_update = [time.monotonic()]

            def _progress(done: int, total: int) -> None:
                now = time.monotonic()
                if now - last_update[0] < 0.2:
                    return
                last_update[0] = now
                if self._progress_bar:
                    self._progress_bar.value = done / total
                if self._status_text:
                    self._status_text.value = f"Combinando… {done}/{total} páginas"
                try:
                    self.page_ref.update()
                except Exception:
                    pass

            try:
                total_pages = engine.merge_selection(sources, out_path, progress=_progress)

                self._last_merged = out_path
                self._merging = False
                if self._progress_bar:
                    self._progress_bar.value = 1.0
                if self._status_text:
                    self._status_text.value = f"Completado — {total_pages} páginas"
                if self._result_row is not None and self._result_row.content is not None:
                    self._result_row.content.controls[1].value = f"Guardado: {Path(out_path).name}"
                    self._result_row.visible = True
                self._update_merge_btn()
                self._snack(f"PDF combinado guardado: {Path(out_path).name}")
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
                self._snack(f"Error al combinar PDFs: {ex}")
                try:
                    self.page_ref.update()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _open_result(self, e=None) -> None:
        if self._last_merged:
            self.on_open_pdf(self._last_merged)
