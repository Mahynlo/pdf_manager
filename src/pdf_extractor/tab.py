"""Tab for searching and extracting pages from one or multiple PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import flet as ft
import fitz

from pdf_viewer.ocr import OCRProcessor


@dataclass
class PageMatch:
    source_path: str
    page_index: int
    score: float
    reason: str


class PDFExtractionTab:
    def __init__(self, page_ref: ft.Page, on_open_preview: Callable[[str], None]):
        self.page_ref = page_ref
        self.on_open_preview = on_open_preview
        self.workspace_root = Path(__file__).resolve().parents[2]
        self.processor = OCRProcessor(str(self.workspace_root))

        self.reference_path: str | None = None
        self.target_paths: list[str] = []
        self.destination_dir = str((self.workspace_root / "storage" / "temp").resolve())
        self.last_output_path: str | None = None

        self._tab: ft.Tab | None = None
        self._build()

    # ------------------------------------------------------------------ UI

    def _build(self) -> None:
        self._ref_path_text = ft.Text("Referencia: sin archivo", size=12, color="#546E7A")
        self._ref_kind_text = ft.Text("Tipo: -", size=12, color="#546E7A")
        self._target_count_text = ft.Text("Archivos objetivo: 0", size=12, color="#546E7A")
        self._dest_text = ft.Text(f"Destino: {self.destination_dir}", size=12, color="#546E7A")

        self._reference_pages = ft.TextField(
            label="Páginas de referencia (ej: 1,3-5)",
            hint_text="Vacío = todas",
            dense=True,
        )
        self._hint_pages = ft.TextField(
            label="Página sugerida en cada objetivo (ej: 1,2)",
            hint_text="Se verifican primero; vacío = buscar en todas",
            dense=True,
        )
        self._keywords = ft.TextField(
            label="Palabras clave / títulos / nombres de formato",
            hint_text="Una por línea o separadas por coma",
            multiline=True,
            min_lines=4,
            max_lines=8,
        )

        self._results = ft.ListView(expand=True, spacing=2, auto_scroll=True)
        self._progress = ft.Text("", size=12, color="#1565C0", italic=True)
        self._summary = ft.Text("Sin búsqueda ejecutada", size=12, color="#546E7A")

        self._run_btn = ft.ElevatedButton(
            "Buscar y extraer",
            icon=ft.Icons.SEARCH,
            on_click=self._run_extraction,
        )
        self._preview_btn = ft.OutlinedButton(
            "Abrir vista previa",
            icon=ft.Icons.VISIBILITY,
            disabled=True,
            on_click=self._open_preview,
        )

        self._pick_reference = ft.FilePicker(on_result=self._on_reference_picked)
        self._pick_targets = ft.FilePicker(on_result=self._on_targets_picked)
        self._pick_destination = ft.FilePicker(on_result=self._on_destination_picked)
        self.page_ref.overlay.extend(
            [self._pick_reference, self._pick_targets, self._pick_destination]
        )

        left_panel = ft.Container(
            ft.Column(
                [
                    ft.Text("Referencia", size=15, weight=ft.FontWeight.W_600),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "Abrir PDF referencia",
                                icon=ft.Icons.UPLOAD_FILE,
                                on_click=lambda e: self._pick_reference.pick_files(
                                    dialog_title="Seleccionar PDF referencia",
                                    allowed_extensions=["pdf"],
                                    allow_multiple=False,
                                ),
                            ),
                        ]
                    ),
                    self._ref_path_text,
                    self._ref_kind_text,
                    self._reference_pages,
                    ft.Divider(height=1),
                    ft.Text("Patrón de búsqueda", size=15, weight=ft.FontWeight.W_600),
                    self._keywords,
                    ft.Divider(height=1),
                    ft.Text("Opciones avanzadas", size=14, weight=ft.FontWeight.W_500),
                    self._hint_pages,
                ],
                spacing=8,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.padding.all(12),
            bgcolor="#F8FAFC",
            border=ft.border.only(right=ft.BorderSide(1, "#DCE3EA")),
            expand=1,
        )

        right_panel = ft.Container(
            ft.Column(
                [
                    ft.Text("Objetivos y extracción", size=15, weight=ft.FontWeight.W_600),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "Cargar PDFs objetivo",
                                icon=ft.Icons.FOLDER_OPEN,
                                on_click=lambda e: self._pick_targets.pick_files(
                                    dialog_title="Seleccionar PDFs objetivo",
                                    allowed_extensions=["pdf"],
                                    allow_multiple=True,
                                ),
                            ),
                            ft.OutlinedButton(
                                "Carpeta destino",
                                icon=ft.Icons.FOLDER,
                                on_click=lambda e: self._pick_destination.get_directory_path(
                                    dialog_title="Seleccionar carpeta destino"
                                ),
                            ),
                        ],
                        wrap=True,
                    ),
                    self._target_count_text,
                    self._dest_text,
                    ft.Row([self._run_btn, self._preview_btn]),
                    self._progress,
                    self._summary,
                    ft.Divider(height=1),
                    ft.Text("Registro de operación", size=13, color="#455A64"),
                    ft.Container(self._results, expand=True),
                ],
                spacing=8,
                expand=True,
            ),
            padding=ft.padding.all(12),
            expand=2,
        )

        self.view = ft.Row([left_panel, right_panel], expand=True, spacing=0)

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FIND_IN_PAGE, size=16, color=ft.Colors.BLUE_400),
                        ft.Text("Extraer PDF", size=13),
                    ],
                    spacing=6,
                    tight=True,
                ),
                content=self.view,
            )
        return self._tab

    # ------------------------------------------------------------------ Events

    def _on_reference_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        self.reference_path = e.files[0].path
        self._ref_path_text.value = f"Referencia: {Path(self.reference_path).name}"
        try:
            with fitz.open(self.reference_path) as doc:
                kind = self.processor.get_doc_kind(doc)
                self._ref_kind_text.value = f"Tipo: {self._doc_kind_label(kind)}"
        except Exception as ex:
            self._ref_kind_text.value = f"Tipo: error ({ex})"
        self.page_ref.update()

    def _on_targets_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        self.target_paths = [f.path for f in e.files if f.path]
        self._target_count_text.value = f"Archivos objetivo: {len(self.target_paths)}"
        self.page_ref.update()

    def _on_destination_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        self.destination_dir = e.path
        self._dest_text.value = f"Destino: {self.destination_dir}"
        self.page_ref.update()

    # ------------------------------------------------------------------ Helpers

    @staticmethod
    def _doc_kind_label(kind: str) -> str:
        return {"native": "Texto nativo", "hybrid": "Híbrido", "scanned": "Escaneado"}.get(
            kind, kind
        )

    @staticmethod
    def _parse_pages(page_input: str, total_pages: int) -> set[int]:
        out: set[int] = set()
        if not page_input.strip():
            return out
        for chunk in [c.strip() for c in page_input.replace(";", ",").split(",") if c.strip()]:
            if "-" in chunk:
                parts = chunk.split("-", 1)
                try:
                    a, b = int(parts[0].strip()), int(parts[1].strip())
                    if a > b:
                        a, b = b, a
                    out.update(idx - 1 for idx in range(a, b + 1) if 0 < idx <= total_pages)
                except ValueError:
                    pass
            else:
                try:
                    idx = int(chunk) - 1
                    if 0 <= idx < total_pages:
                        out.add(idx)
                except ValueError:
                    pass
        return out

    @staticmethod
    def _normalize_words(text: str) -> set[str]:
        words: set[str] = set()
        for raw in text.lower().replace("\n", " ").split():
            token = "".join(ch for ch in raw if ch.isalnum())
            if len(token) >= 4:
                words.add(token)
        return words

    def _extract_page_text(
        self, doc: fitz.Document, page_index: int
    ) -> tuple[str, str, float, bool]:
        """Extract text from a page without forcing OCR unnecessarily.

        Returns:
            text        – extracted text (native and/or OCR)
            mode_label  – 'Nativo' | 'OCR' | 'Híbrido' | 'Sin texto'
            elapsed_ms  – wall time in milliseconds
            used_ocr    – True if the OCR engine was actually invoked
        """
        page = doc[page_index]
        needs_ocr = self.processor.page_needs_ocr(page)

        # Only pass force_ocr when the page has no native text at all.
        result = self.processor.process_page(doc, page_index, force_ocr=needs_ocr)
        text = "\n".join(seg.text for seg in result.segments if seg.text.strip())
        used_ocr = bool(result.detections)
        return text, result.mode_label, result.elapsed_ms, used_ocr

    def _collect_keywords(self) -> list[str]:
        raw = self._keywords.value or ""
        chunks: list[str] = []
        for row in raw.splitlines():
            chunks.extend(part.strip() for part in row.split(","))
        return [c.lower() for c in chunks if c]

    def _log(self, text: str, color: str = "#455A64") -> None:
        """Append a line to the results log and refresh."""
        self._results.controls.append(
            ft.Container(
                ft.Text(text, size=12, color=color, selectable=True),
                padding=ft.padding.symmetric(vertical=1, horizontal=4),
            )
        )
        self.page_ref.update()

    def _log_separator(self) -> None:
        self._results.controls.append(ft.Divider(height=1, color="#E0E0E0"))
        self.page_ref.update()

    def _set_progress(self, text: str) -> None:
        self._progress.value = text
        self.page_ref.update()

    # ------------------------------------------------------------------ Core

    def _run_extraction(self, e=None) -> None:  # noqa: C901 (complexity ok for a monolith step)
        if not self.target_paths:
            self._log("✗ Selecciona al menos un PDF objetivo.", "#B00020")
            return
        kws = self._collect_keywords()
        if not kws:
            self._log("✗ Define al menos una palabra clave para la búsqueda.", "#B00020")
            return

        self._run_btn.disabled = True
        self._preview_btn.disabled = True
        self._results.controls.clear()
        self._summary.value = "Iniciando análisis…"
        self._progress.value = ""
        self.page_ref.update()

        hint_pages_raw = self._hint_pages.value or ""

        # ── Reference document ───────────────────────────────────────────────
        ref_tokens: set[str] = set()
        if self.reference_path:
            self._set_progress("Procesando documento de referencia…")
            try:
                with fitz.open(self.reference_path) as ref_doc:
                    total_ref = len(ref_doc)
                    selected = self._parse_pages(self._reference_pages.value or "", total_ref)
                    pages_to_use = sorted(selected) if selected else range(total_ref)
                    for i in pages_to_use:
                        self._set_progress(
                            f"Referencia: página {i + 1}/{total_ref} — {Path(self.reference_path).name}"
                        )
                        text, mode, ms, used_ocr = self._extract_page_text(ref_doc, i)
                        ref_tokens |= self._normalize_words(text)
                    self._log(
                        f"Referencia: {Path(self.reference_path).name} — "
                        f"{len(ref_tokens)} tokens, {len(list(pages_to_use))} páginas procesadas",
                        "#0D47A1",
                    )
                    self._log_separator()
            except Exception as ex:
                self._log(f"✗ Referencia no procesada: {ex}", "#B00020")

        # ── Target documents ─────────────────────────────────────────────────
        all_matches: list[PageMatch] = []
        total_files = len(self.target_paths)

        for file_idx, path in enumerate(self.target_paths):
            fname = Path(path).name
            self._summary.value = f"Archivo {file_idx + 1} de {total_files}: {fname}"
            self.page_ref.update()

            try:
                doc = fitz.open(path)
            except Exception as ex:
                self._log(f"✗ {fname}: error al abrir — {ex}", "#B00020")
                continue

            with doc:
                total_pages = len(doc)
                doc_kind = self.processor.get_doc_kind(doc)
                doc_kind_label = self._doc_kind_label(doc_kind)

                self._log(
                    f"📄 [{file_idx + 1}/{total_files}] {fname} — {doc_kind_label}, {total_pages} página(s)",
                    "#0D47A1",
                )

                # Warn early if the whole document is scanned (OCR will be slow).
                if doc_kind == "scanned":
                    self._log(
                        "  ⚠ Documento escaneado — se ejecutará OCR en cada página sin texto nativo.",
                        "#E65100",
                    )

                # Build scan order: hint pages first, then remaining pages.
                hint_set = self._parse_pages(hint_pages_raw, total_pages)
                if hint_set:
                    other_pages = [i for i in range(total_pages) if i not in hint_set]
                    scan_order = sorted(hint_set) + other_pages
                    self._log(
                        f"  ℹ Páginas sugeridas verificadas primero: "
                        f"{', '.join(str(p + 1) for p in sorted(hint_set))}",
                        "#546E7A",
                    )
                else:
                    scan_order = list(range(total_pages))

                file_matches: list[PageMatch] = []
                pages_with_ocr = 0
                pages_skipped = 0

                for i in scan_order:
                    is_hint = i in hint_set
                    hint_tag = " ⭐" if is_hint else ""

                    self._set_progress(
                        f"Analizando: {fname} — página {i + 1}/{total_pages}{hint_tag}"
                    )

                    # ── Per-page text extraction ──────────────────────────────
                    page_obj = doc[i]
                    page_k = self.processor.page_kind(page_obj)

                    text, mode, elapsed_ms, used_ocr = self._extract_page_text(doc, i)
                    page_text_lower = text.lower()

                    if used_ocr:
                        pages_with_ocr += 1

                    time_tag = f"{elapsed_ms:.0f}ms"
                    ocr_tag = " | OCR" if used_ocr else ""

                    # ── Keyword matching ──────────────────────────────────────
                    if not page_text_lower.strip():
                        pages_skipped += 1
                        # Only log skipped hint pages; skip noise for other empty pages.
                        if is_hint:
                            self._log(
                                f"  ~ Pág {i + 1}{hint_tag} [{mode} | {time_tag}]: sin texto extraíble",
                                "#FF6F00",
                            )
                        continue

                    kw_hits = [kw for kw in kws if kw in page_text_lower]

                    if len(kw_hits) == len(kws):
                        score = float(len(kw_hits))
                        reason = f"keywords={len(kw_hits)}"

                        if ref_tokens:
                            page_tokens = self._normalize_words(text)
                            if page_tokens:
                                inter = len(ref_tokens & page_tokens)
                                union = len(ref_tokens | page_tokens)
                                jaccard = inter / union if union else 0.0
                                score += jaccard * 2  # weight similarity
                                reason += f", sim={jaccard:.2f}"

                        file_matches.append(PageMatch(path, i, score, reason))

                        shown = ", ".join(f'"{k}"' for k in kw_hits[:5])
                        extra = f" +{len(kw_hits) - 5} más" if len(kw_hits) > 5 else ""
                        self._log(
                            f"  ✓ Pág {i + 1}{hint_tag} [{mode}{ocr_tag} | {time_tag}]: "
                            f"{shown}{extra}",
                            "#1B5E20",
                        )
                    else:
                        # Always report hint-page misses; silently skip other pages.
                        if is_hint:
                            self._log(
                                f"  ~ Pág {i + 1}{hint_tag} [{mode}{ocr_tag} | {time_tag}]: "
                                f"no coincide",
                                "#FF6F00",
                            )

                # ── Per-file summary ──────────────────────────────────────────
                file_matches.sort(key=lambda m: m.score, reverse=True)
                all_matches.extend(file_matches)

                ocr_note = f", OCR en {pages_with_ocr} pág." if pages_with_ocr else ""
                skip_note = f", {pages_skipped} omitidas" if pages_skipped else ""
                if file_matches:
                    self._log(
                        f"  → {len(file_matches)} página(s) encontrada(s){ocr_note}{skip_note}",
                        "#1565C0",
                    )
                else:
                    self._log(
                        f"  → Sin coincidencias{ocr_note}{skip_note}",
                        "#757575",
                    )
                self._log_separator()

        self._set_progress("")

        # ── Save output ───────────────────────────────────────────────────────
        if not all_matches:
            self._summary.value = "Búsqueda finalizada: no se encontraron páginas coincidentes."
            self._run_btn.disabled = False
            self.page_ref.update()
            return

        dest = Path(self.destination_dir)
        dest.mkdir(parents=True, exist_ok=True)
        out_name = f"extraccion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        out_path = dest / out_name

        grouped: dict[str, list[PageMatch]] = {}
        for match in all_matches:
            grouped.setdefault(match.source_path, []).append(match)

        out_doc = fitz.open()
        try:
            for src_path, matches in grouped.items():
                with fitz.open(src_path) as src_doc:
                    for pidx in sorted({m.page_index for m in matches}):
                        out_doc.insert_pdf(src_doc, from_page=pidx, to_page=pidx)
            out_doc.save(str(out_path), garbage=4, deflate=True)
        finally:
            out_doc.close()

        self.last_output_path = str(out_path)
        self._preview_btn.disabled = False
        self._summary.value = (
            f"Finalizado: {len(all_matches)} coincidencia(s) en "
            f"{len(grouped)} archivo(s). Salida: {out_path.name}"
        )
        self._log(f"💾 Archivo guardado: {out_path}", "#0D47A1")
        self._run_btn.disabled = False
        self.page_ref.update()

    def _open_preview(self, e=None) -> None:
        if not self.last_output_path:
            return
        self.on_open_preview(self.last_output_path)
