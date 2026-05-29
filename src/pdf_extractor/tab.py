"""Tab for searching and extracting pages from one or multiple PDFs.

UI + orchestration only. The extraction logic (opening docs, OCR, scoring,
saving) lives in `engine.py`; pure helpers/records live in `model.py`.

The scan runs synchronously on the UI thread and pauses when a target needs a
password: it stores `_extraction_state`, shows the password dialog, and resumes
the *same* loop (`_process_targets_from`) from the stored index once the
password is entered — so the initial run and the resume share one code path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from pdf_viewer.ocr import OCRProcessor

from . import engine
from .engine import (
    ExtractInvalidPasswordError,
    ExtractPasswordRequiredError,
    ExtractPermissionDeniedError,
    Reporter,
)
from .model import collect_keywords, doc_kind_label


class PDFExtractionTab:
    def __init__(self, page_ref: ft.Page, on_open_preview: Callable[[str], None], on_close: Callable[["PDFExtractionTab"], None] | None = None, on_open_security: Callable[[], None] | None = None):
        self.page_ref = page_ref
        self.on_open_preview = on_open_preview
        self.on_close = on_close
        self.on_open_security = on_open_security
        self.workspace_root = Path(__file__).resolve().parents[2]
        self.processor = OCRProcessor(str(self.workspace_root))

        self.reference_path: str | None = None
        self.reference_password: str | None = None
        self.target_paths: list[str] = []
        self.target_passwords: dict[int, str] = {}  # file_idx -> password mapping
        self.destination_dir = str((self.workspace_root / "storage" / "temp").resolve())
        self.last_output_path: str | None = None
        self._pending_password_file_idx: int | None = None

        # Extraction state for pause/resume (set when paused waiting for a password)
        self._extraction_state: dict | None = None
        self._is_extracting = False

        self._reporter = Reporter(
            log=self._log,
            set_progress=self._set_progress,
            log_separator=self._log_separator,
        )

        self._tab: ft.Tab | None = None
        self._pwd_dialog: ft.AlertDialog | None = None
        self._pwd_field: ft.TextField | None = None
        self._pwd_error: ft.Text | None = None
        self._build()

    # ------------------------------------------------------------------ UI

    def _build(self) -> None:
        # File pickers
        self._pick_reference = ft.FilePicker(on_result=self._on_reference_picked)
        self._pick_targets = ft.FilePicker(on_result=self._on_targets_picked)
        self._pick_destination = ft.FilePicker(on_result=self._on_destination_picked)
        self.page_ref.overlay.extend(
            [self._pick_reference, self._pick_targets, self._pick_destination]
        )

        self._pwd_field = ft.TextField(
            label="Contraseña",
            password=True,
            can_reveal_password=True,
            autofocus=True,
            on_submit=lambda _: self._confirm_protected_pdf_password(),
        )
        self._pwd_error = ft.Text("", color="#D32F2F", size=12, visible=False)
        self._pwd_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("PDF protegido"),
            content=ft.Column([self._pwd_field, self._pwd_error], tight=True, spacing=8),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self._cancel_protected_pdf()),
                ft.TextButton("Ir a Seguridad", on_click=lambda _: self._open_security_from_extraction()),
                ft.ElevatedButton("Usar", icon=ft.Icons.LOCK_OPEN, on_click=lambda _: self._confirm_protected_pdf_password()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        # ─── HEADER ────────────────────────────────────────────────────────
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FIND_IN_PAGE, size=32, color="#1565C0"),
                    ft.Column([
                        ft.Text("Extracción Inteligente de PDFs", size=22, weight="bold", color="#1E2A38"),
                        ft.Text("Busca palabras clave y extrae páginas específicas de múltiples documentos", size=13, color="#666666"),
                    ], spacing=2)
                ],
                alignment="start",
                spacing=16,
            ),
            padding=ft.padding.only(left=20, top=20, right=20, bottom=10)
        )

        # ─── PANEL IZQUIERDO (Configuración) ─────────────────────────────────
        self._ref_path_text = ft.Text("Referencia: sin archivo", size=12, color="#666666")
        self._ref_kind_text = ft.Text("Tipo: -", size=12, color="#666666")

        ref_info_container = ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF, size=16, color="#999999"), self._ref_path_text]),
                ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color="#999999"), self._ref_kind_text])
            ], spacing=4),
            padding=15,
            bgcolor="#F5F5F5",
            border_radius=8,
        )

        self._reference_pages = ft.TextField(
            label="Páginas de referencia (ej: 1,3-5)",
            hint_text="Vacío = todas",
            dense=True,
            border_color="#1E2A38",
            prefix_icon=ft.Icons.NUMBERS,
        )

        self._hint_pages = ft.TextField(
            label="Páginas sugeridas en objetivos (ej: 1,2)",
            hint_text="Se verifican primero; vacío = todas",
            dense=True,
            border_color="#1E2A38",
            prefix_icon=ft.Icons.LIGHTBULB_OUTLINE,
        )

        self._keywords = ft.TextField(
            label="Palabras clave / títulos / nombres",
            hint_text="Una por línea o separadas por coma",
            multiline=True,
            min_lines=4,
            max_lines=8,
            border_color="#1E2A38",
            prefix_icon=ft.Icons.KEY,
        )

        left_panel = ft.Column(
            [
                ft.Text("Paso 1: Documento de Referencia", size=16, weight="bold", color="#1E2A38"),
                ft.ElevatedButton(
                    "Abrir PDF Referencia",
                    icon=ft.Icons.UPLOAD_FILE,
                    on_click=lambda e: self._pick_reference.pick_files(
                        dialog_title="Seleccionar PDF referencia",
                        allowed_extensions=["pdf"],
                        allow_multiple=False,
                    ),
                    style=ft.ButtonStyle(padding=15)
                ),
                ref_info_container,
                ft.Container(height=4),
                self._reference_pages,
                ft.Divider(height=24, color="#E0E0E0"),

                ft.Text("Paso 2: Patrón de Búsqueda", size=16, weight="bold", color="#1E2A38"),
                self._keywords,
                self._hint_pages,
            ],
            spacing=10,
            expand=True,
            scroll="auto",
        )

        # ─── PANEL DERECHO (Objetivos y Resultados) ──────────────────────────
        self._target_count_text = ft.Text("Archivos objetivo: 0", size=12, color="#666666")
        self._dest_text = ft.Text(f"Destino: {self.destination_dir}", size=12, color="#666666")

        target_info_container = ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.LIBRARY_BOOKS, size=16, color="#999999"), self._target_count_text]),
                ft.Row([ft.Icon(ft.Icons.FOLDER_SPECIAL, size=16, color="#999999"), self._dest_text])
            ], spacing=4),
            padding=15,
            bgcolor="#F5F5F5",
            border_radius=8,
        )

        self._results = ft.ListView(expand=True, spacing=4, auto_scroll=True)
        self._progress = ft.Text("", size=13, color="#1565C0", weight="w500", italic=True)
        self._summary = ft.Text("Sin búsqueda ejecutada", size=13, color="#666666", weight="bold")

        self._run_btn = ft.ElevatedButton(
            "Buscar y Extraer",
            icon=ft.Icons.SEARCH,
            on_click=self._run_extraction,
            style=ft.ButtonStyle(
                bgcolor="#1565C0",
                color="white",
                padding=20
            )
        )
        self._preview_btn = ft.ElevatedButton(
            "Abrir Vista Previa",
            icon=ft.Icons.VISIBILITY,
            disabled=True,
            on_click=self._open_preview,
            style=ft.ButtonStyle(padding=20)
        )

        right_panel = ft.Column(
            [
                ft.Text("Paso 3: Objetivos y Extracción", size=16, weight="bold", color="#1E2A38"),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "Cargar PDFs Objetivo",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda e: self._pick_targets.pick_files(
                                dialog_title="Seleccionar PDFs objetivo",
                                allowed_extensions=["pdf"],
                                allow_multiple=True,
                            ),
                            style=ft.ButtonStyle(padding=15)
                        ),
                        ft.ElevatedButton(
                            "Carpeta Destino",
                            icon=ft.Icons.FOLDER,
                            on_click=lambda e: self._pick_destination.get_directory_path(
                                dialog_title="Seleccionar carpeta destino"
                            ),
                            style=ft.ButtonStyle(padding=15)
                        ),
                    ],
                    wrap=True,
                ),
                target_info_container,
                ft.Row([self._run_btn, self._preview_btn], spacing=12),

                ft.Divider(height=16, color="#E0E0E0"),

                ft.Row([ft.Icon(ft.Icons.TERMINAL, size=16, color="#1E2A38"), ft.Text("Registro de Operación", size=14, weight="bold", color="#1E2A38")]),
                self._progress,
                self._summary,

                # Terminal simulada para resultados
                ft.Container(
                    content=self._results,
                    expand=True,
                    bgcolor="#FAFAFA",
                    border=ft.border.all(1, "#E0E0E0"),
                    border_radius=8,
                    padding=12,
                ),
            ],
            spacing=10,
            expand=True,
        )

        # ─── ESTRUCTURA PRINCIPAL ──────────────────────────────────────────
        tabs_container = ft.Container(
            content=ft.Row([
                ft.Container(left_panel, expand=4, padding=ft.padding.only(right=20)),
                ft.VerticalDivider(width=1, color="#E0E0E0"),
                ft.Container(right_panel, expand=6, padding=ft.padding.only(left=10))
            ], spacing=0, vertical_alignment="start"),
            padding=20,
            expand=True
        )

        self.view = ft.Card(
            content=ft.Column([header, ft.Divider(height=1, color="#E0E0E0"), tabs_container], spacing=0),
            elevation=2,
            margin=10,
            expand=True
        )

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FIND_IN_PAGE, size=18, color="#1565C0"),
                        ft.Text("Extraer PDF", size=14, weight="w500"),
                        ft.IconButton(
                            ft.Icons.CLOSE, icon_size=14,
                            on_click=lambda e: self.on_close(self) if self.on_close else None,
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
            "label": "Extraer PDF",
            "icon": ft.Icons.FIND_IN_PAGE,
            "content": self.view,
            "closeable": True,
            "close_cb": lambda: self.on_close(self) if self.on_close else None,
        }

    # ------------------------------------------------------------------ Log helpers

    def _snack(self, message: str) -> None:
        self.page_ref.snack_bar = ft.SnackBar(ft.Text(message), open=True)

    def _log(self, text: str, color: str = "#666666") -> None:
        """Append a line to the results log and refresh."""
        self._results.controls.append(
            ft.Container(
                ft.Text(text, size=13, color=color, selectable=True, font_family="Consolas"),
                padding=ft.padding.symmetric(vertical=2, horizontal=4),
            )
        )
        self.page_ref.update()

    def _log_separator(self) -> None:
        self._results.controls.append(ft.Divider(height=1, color="#E0E0E0"))
        self.page_ref.update()

    def _set_progress(self, text: str) -> None:
        self._progress.value = text
        self.page_ref.update()

    # ------------------------------------------------------------------ Password dialog

    def _show_password_prompt(self, path: str, file_idx: int | None = None, error_message: str | None = None) -> None:
        if self._pwd_dialog is None or self._pwd_field is None or self._pwd_error is None:
            return
        self._pending_password_file_idx = file_idx
        self._pwd_field.value = ""
        self._pwd_error.value = error_message or ""
        self._pwd_error.visible = bool(error_message)
        self._pwd_dialog.title = ft.Text(f"PDF protegido: {Path(path).name}")
        self.page_ref.open(self._pwd_dialog)

    def _cancel_protected_pdf(self) -> None:
        self._pending_password_file_idx = None
        if self._pwd_dialog is not None:
            self.page_ref.close(self._pwd_dialog)

    def _open_security_from_extraction(self) -> None:
        self._pending_password_file_idx = None
        if self._pwd_dialog is not None:
            self.page_ref.close(self._pwd_dialog)
        if self.on_open_security is not None:
            self.on_open_security()

    def _confirm_protected_pdf_password(self) -> None:
        if self._pending_password_file_idx is None:
            if self._pwd_dialog is not None:
                self.page_ref.close(self._pwd_dialog)
            return

        password = (self._pwd_field.value if self._pwd_field else "") or ""
        password = password.strip()
        if not password:
            if self._pwd_error is not None:
                self._pwd_error.value = "Ingresa la contraseña"
                self._pwd_error.visible = True
            self.page_ref.update()
            return

        file_idx = self._pending_password_file_idx
        path = self.reference_path if file_idx == -1 else self.target_paths[file_idx]
        try:
            engine.open_source_doc(path, password=password).close()
        except ExtractInvalidPasswordError:
            self._show_password_prompt(path, file_idx=file_idx, error_message="Contraseña incorrecta")
            self.page_ref.update()
            return
        except ExtractPermissionDeniedError:
            self._snack(
                f"{Path(path).name} no permite copia/extracción de contenido. "
                "Usa Seguridad para crear una copia desbloqueada."
            )
            self._pending_password_file_idx = None
            if self._pwd_dialog is not None:
                self.page_ref.close(self._pwd_dialog)
            self.page_ref.update()
            return
        except Exception as ex:
            self._snack(f"Error: {ex}")
            self._pending_password_file_idx = None
            if self._pwd_dialog is not None:
                self.page_ref.close(self._pwd_dialog)
            self.page_ref.update()
            return

        # Store the password
        if file_idx == -1:
            self.reference_password = password
            self._on_reference_picked_internal(path)
        else:
            self.target_passwords[file_idx] = password

        self._pending_password_file_idx = None
        if self._pwd_dialog is not None:
            self.page_ref.close(self._pwd_dialog)

        # If extraction was paused waiting for this password, resume it
        if self._extraction_state is not None:
            self._snack("Contraseña guardada. Reanudando…")
            self._resume_extraction_sync()
        else:
            self.page_ref.update()

    # ------------------------------------------------------------------ Events

    def _on_reference_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        path = e.files[0].path
        self.reference_path = path
        self.reference_password = None
        self._on_reference_picked_internal(path)

    def _on_reference_picked_internal(self, path: str) -> None:
        self._ref_path_text.value = f"Referencia: {Path(path).name}"
        try:
            doc = engine.open_source_doc(path, password=self.reference_password)
            try:
                kind = self.processor.get_doc_kind(doc)
                self._ref_kind_text.value = f"Tipo: {doc_kind_label(kind)}"
            finally:
                doc.close()
        except ExtractPasswordRequiredError:
            self._show_password_prompt(path, file_idx=-1)
            return
        except ExtractPermissionDeniedError:
            self._ref_kind_text.value = "Tipo: error (sin permisos de extracción)"
            self._snack("PDF de referencia no permite extracción. Usa Seguridad para desbloquearlo.")
        except Exception as ex:
            self._ref_kind_text.value = f"Tipo: error ({ex})"
        self.page_ref.update()

    def _on_targets_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        self.target_paths = [f.path for f in e.files if f.path]
        self.target_passwords.clear()
        self._target_count_text.value = f"Archivos objetivo: {len(self.target_paths)}"
        self.page_ref.update()

    def _on_destination_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        self.destination_dir = e.path
        self._dest_text.value = f"Destino: {self.destination_dir}"
        self.page_ref.update()

    # ------------------------------------------------------------------ Extraction

    def _run_extraction(self, e=None) -> None:
        if not self.target_paths:
            self._log("✗ Selecciona al menos un PDF objetivo.", "#D32F2F")
            return
        keywords = collect_keywords(self._keywords.value or "")
        if not keywords:
            self._log("✗ Define al menos una palabra clave para la búsqueda.", "#D32F2F")
            return

        self._run_btn.disabled = True
        self._preview_btn.disabled = True
        self._results.controls.clear()
        self._summary.value = "Iniciando análisis…"
        self._progress.value = ""
        self.page_ref.update()

        self._is_extracting = True
        self._extraction_state = None

        hint_pages_raw = self._hint_pages.value or ""
        ref_tokens = self._process_reference()
        self._process_targets_from(0, ref_tokens, [], keywords, hint_pages_raw)

    def _process_reference(self) -> set[str]:
        """Tokenize the reference document, handling password/permission in the UI."""
        if not self.reference_path:
            return set()
        self._set_progress("Procesando documento de referencia…")
        try:
            tokens = engine.extract_reference_tokens(
                self.reference_path,
                self.reference_password,
                self._reference_pages.value or "",
                self.processor,
                reporter=self._reporter,
            )
            self._log_separator()
            return tokens
        except ExtractPasswordRequiredError:
            self._log("✗ Referencia requiere contraseña para procesarse.", "#D32F2F")
            self._show_password_prompt(self.reference_path, file_idx=-1)
            return set()
        except ExtractPermissionDeniedError:
            self._log("✗ Referencia no permite extracción de contenido.", "#D32F2F")
            return set()
        except Exception as ex:
            self._log(f"✗ Referencia no procesada: {ex}", "#D32F2F")
            return set()

    def _process_targets_from(
        self,
        start_idx: int,
        ref_tokens: set[str],
        all_matches: list,
        keywords: list[str],
        hint_pages_raw: str,
    ) -> None:
        """Scan target documents from *start_idx*; pause on a password prompt.

        Shared by the initial run and the resume-after-password path.
        """
        total_files = len(self.target_paths)
        for file_idx in range(start_idx, total_files):
            path = self.target_paths[file_idx]
            fname = Path(path).name
            self._summary.value = f"Archivo {file_idx + 1} de {total_files}: {fname}"
            self.page_ref.update()

            try:
                doc = engine.open_source_doc(path, password=self.target_passwords.get(file_idx))
            except ExtractPasswordRequiredError:
                self._log(f"✗ {fname}: requiere contraseña. Pausando búsqueda…", "#D32F2F")
                self._extraction_state = {
                    "ref_tokens": ref_tokens,
                    "all_matches": all_matches,
                    "file_idx": file_idx,
                    "keywords": keywords,
                    "hint_pages_raw": hint_pages_raw,
                }
                self._show_password_prompt(path, file_idx=file_idx)
                self._is_extracting = False
                return
            except ExtractPermissionDeniedError:
                self._log(f"✗ {fname}: no permite extracción de contenido.", "#D32F2F")
                continue
            except Exception as ex:
                self._log(f"✗ {fname}: error al abrir — {ex}", "#D32F2F")
                continue

            with doc:
                matches = engine.process_document(
                    doc,
                    path=path,
                    fname=fname,
                    file_idx=file_idx,
                    total_files=total_files,
                    keywords=keywords,
                    ref_tokens=ref_tokens,
                    hint_pages_raw=hint_pages_raw,
                    processor=self.processor,
                    reporter=self._reporter,
                )
                all_matches.extend(matches)

        self._set_progress("")
        self._finish_extraction(all_matches)

    def _resume_extraction_sync(self) -> None:
        """Reanuda la extracción tras obtener una contraseña (sincrónico)."""
        if self._extraction_state is None:
            return
        state = self._extraction_state
        self._extraction_state = None
        self._is_extracting = True
        self._process_targets_from(
            state["file_idx"],
            state["ref_tokens"],
            state["all_matches"],
            state["keywords"],
            state["hint_pages_raw"],
        )

    def _finish_extraction(self, all_matches: list) -> None:
        """Save the collected matches (if any) and update the summary."""
        if not all_matches:
            self._summary.value = "Búsqueda finalizada: no se encontraron páginas coincidentes."
            self._run_btn.disabled = False
            self._is_extracting = False
            self.page_ref.update()
            return

        out_path = engine.save_matches(
            all_matches, self.target_paths, self.target_passwords, self.destination_dir
        )
        n_files = len({m.source_path for m in all_matches})
        self.last_output_path = str(out_path)
        self._preview_btn.disabled = False
        self._summary.value = (
            f"Finalizado: {len(all_matches)} coincidencia(s) en "
            f"{n_files} archivo(s). Salida: {out_path.name}"
        )
        self._log(f"💾 Archivo guardado: {out_path}", "#1565C0")
        self._run_btn.disabled = False
        self._is_extracting = False
        self._extraction_state = None
        self.page_ref.update()

    def _open_preview(self, e=None) -> None:
        if not self.last_output_path:
            return
        self.on_open_preview(self.last_output_path)
