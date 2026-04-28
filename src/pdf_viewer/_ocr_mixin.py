"""OCR execution, results display and sidebar panel for PDFViewerTab."""
from __future__ import annotations

import flet as ft

from .annotations import Tool
from .ocr import OCRPageResult
from .renderer import BASE_SCALE
from ._viewer_defs import _OCR_BOX_BG, _OCR_BOX_CLR, _OCR_PANEL_BG, _SELECTED_BG


class _OCRMixin:
    """OCR runner, results list, bounding-box overlay and sidebar panel."""

    # ── sidebar panel builder ─────────────────────────────────────────────────

    def _build_ocr_sidebar_panel(self) -> ft.Container:
        """Build the OCR panel and initialise all OCR UI controls."""
        self._ocr_info     = ft.Text("OCR: sin ejecutar", size=12, color="#455A64")
        self._ocr_source   = ft.Text("Modo: -",           size=12, color="#455A64")
        self._ocr_doc_kind = ft.Text("Documento: -",      size=12, color="#455A64")
        self._ocr_time     = ft.Text("Tiempo: -",         size=12, color="#455A64")
        self._ocr_count    = ft.Text("Resultados: -",     size=12, color="#455A64")
        self._ocr_results_list = ft.ListView(
            expand=True, spacing=6,
            padding=ft.padding.only(bottom=8),
            auto_scroll=False,
        )
        self._ocr_content_area = ft.Container(
            ft.Column(
                [
                    self._ocr_info,
                    self._ocr_source,
                    self._ocr_doc_kind,
                    self._ocr_time,
                    self._ocr_count,
                    ft.Divider(height=1, color="#DCE8DF"),
                    ft.Container(self._ocr_results_list, expand=True),
                ],
                spacing=6,
                expand=True,
            ),
            expand=True,
        )
        self._ocr_panel = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TEXT_SNIPPET, size=18, color="#2E7D32"),
                            ft.Text("Resultados OCR", size=14, weight=ft.FontWeight.W_600),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._ocr_content_area,
                ],
                spacing=4,
                expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=_OCR_PANEL_BG,
            expand=True,
        )
        return self._ocr_panel

    # ── helpers used in nav toolbar ───────────────────────────────────────────

    def _make_ocr_toggle_btn(self) -> ft.IconButton:
        self._ocr_toggle_btn = ft.IconButton(
            ft.Icons.GRID_ON,
            tooltip="Mostrar/Ocultar detección OCR",
            on_click=self._toggle_ocr_boxes,
        )
        return self._ocr_toggle_btn

    def _make_sidebar_toggle_btn(self) -> ft.IconButton:
        self._sidebar_btn = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT,
            tooltip="Ocultar panel lateral",
            on_click=self._toggle_sidebar,
        )
        return self._sidebar_btn

    # ── sidebar visibility ────────────────────────────────────────────────────

    def _toggle_sidebar(self, e=None) -> None:
        self._sidebar_visible = not self._sidebar_visible
        if self._right_sidebar is not None:
            self._right_sidebar.visible = self._sidebar_visible
            try:
                self._right_sidebar.update()
            except Exception:
                pass
        if self._sidebar_btn is not None:
            if self._sidebar_visible:
                self._sidebar_btn.icon    = ft.Icons.CHEVRON_RIGHT
                self._sidebar_btn.tooltip = "Ocultar panel lateral"
            else:
                self._sidebar_btn.icon    = ft.Icons.CHEVRON_LEFT
                self._sidebar_btn.tooltip = "Mostrar panel lateral"
            try:
                self._sidebar_btn.update()
            except Exception:
                pass

    # ── OCR execution ─────────────────────────────────────────────────────────

    def _run_ocr(self, e=None) -> None:
        # Switch to OCR view so results are visible
        if hasattr(self, "_switch_sidebar_mode"):
            self._switch_sidebar_mode("ocr")
        elif not self._sidebar_visible:
            self._toggle_sidebar()
        pn = self.current_page
        self._ocr_info.value = f"OCR página {pn + 1}: procesando inferencia..."
        self.page_ref.update()
        try:
            with self._doc_lock:
                result = self._ocr_processor.process_page(self.doc, pn, force_ocr=True)
        except Exception as ex:
            self._ocr_info.value  = f"OCR página {pn + 1}: error"
            self._ocr_time.value  = "Tiempo: -"
            self._ocr_count.value = "Resultados: 0"
            self._ocr_results_list.controls = [
                ft.Container(
                    ft.Text(f"Error OCR: {ex}", size=12, color="#B00020", selectable=True),
                    padding=ft.padding.all(8),
                )
            ]
            self._show_snack(f"Error OCR: {ex}")
            self.page_ref.update()
            return

        self._ocr_by_page[pn] = result
        self._page_words.pop(pn, None)  # invalidate so OCR words are included on next selection
        self._ocr_active_index = 0
        self._refresh_ocr_ui_for_page()
        if self._agent_instance is not None:
            self._agent_instance.set_ocr_overrides(self._build_ocr_overrides())
        self._show_snack("OCR ejecutado")
        self.page_ref.update()

    # ── OCR UI refresh ────────────────────────────────────────────────────────

    @staticmethod
    def _doc_kind_label(kind: str) -> str:
        return {"native": "Texto nativo", "scanned": "Escaneado", "hybrid": "Híbrido"}.get(kind, kind)

    def _refresh_ocr_ui_for_page(self) -> None:
        result = self._ocr_by_page.get(self.current_page)
        pn     = self.current_page

        if result is None:
            self._ocr_info.value      = f"OCR página {pn + 1}: sin ejecutar"
            self._ocr_source.value    = "Modo: -"
            self._ocr_doc_kind.value  = "Documento: -"
            self._ocr_time.value      = "Tiempo: -"
            self._ocr_count.value     = "Resultados: 0"
            self._ocr_results_list.controls = [
                ft.Container(
                    ft.Text("Ejecuta OCR para ver texto extraído aquí.", size=12, color="#607D68"),
                    padding=ft.padding.all(8),
                )
            ]
            if pn < len(self._ocr_overlays):
                self._ocr_overlays[pn].visible  = False
                self._ocr_overlays[pn].controls = []
            return

        self._ocr_info.value     = f"OCR página {pn + 1}: {len(result.segments)} segmentos"
        self._ocr_source.value   = f"Modo: {result.mode_label}"
        self._ocr_doc_kind.value = f"Documento: {self._doc_kind_label(result.doc_kind)}"
        self._ocr_time.value     = f"Tiempo: {result.elapsed_ms:.0f} ms"
        self._ocr_count.value    = f"Resultados: {len(result.segments)}"
        self._build_ocr_results_list(result)
        self._render_ocr_boxes()

    def _toggle_ocr_boxes(self, e=None) -> None:
        pn = self.current_page
        if pn not in self._ocr_by_page:
            self._show_snack("Primero ejecuta OCR en esta página")
            return
        self._ocr_show_boxes = not self._ocr_show_boxes
        self._render_ocr_boxes(force_update=True)
        if self._ocr_toggle_btn is not None:
            self._ocr_toggle_btn.bgcolor    = _SELECTED_BG if self._ocr_show_boxes else None
            self._ocr_toggle_btn.icon_color = _OCR_BOX_CLR if self._ocr_show_boxes else None
            try:
                self._ocr_toggle_btn.update()
            except Exception:
                pass

    def _build_ocr_results_list(self, result: OCRPageResult) -> None:
        if not result.segments:
            self._ocr_results_list.controls = [
                ft.Container(
                    ft.Text("Sin texto extraído", size=12, color="#607D68"),
                    padding=ft.padding.all(8),
                )
            ]
            return
        text_body = "\n".join(seg.text for seg in result.segments if seg.text.strip())
        self._ocr_results_list.controls = [
            ft.Container(
                ft.Text(text_body or "Sin texto extraído", size=12, selectable=True),
                padding=ft.padding.all(10),
                border=ft.border.all(1, "#E3ECE5"),
                bgcolor="#FFFFFF",
                border_radius=8,
            )
        ]

    def _render_ocr_boxes(self, *, force_update: bool = False, pn: int | None = None) -> None:
        if pn is None:
            pn = self.current_page
        if pn >= len(self._ocr_overlays):
            return
        ocr_ov = self._ocr_overlays[pn]
        result = self._ocr_by_page.get(pn)
        if result is None or not self._ocr_show_boxes:
            ocr_ov.visible  = False
            ocr_ov.controls = []
            if force_update:
                try:
                    ocr_ov.update()
                except Exception:
                    pass
            return

        scale = self.zoom * BASE_SCALE
        boxes: list[ft.Control] = []

        def _make_ocr_click(d, p):
            def _handler(e):
                if self._annot.tool == Tool.SELECT:
                    self._show_text_actions(d.text, p)
            return _handler

        for det in result.detections:
            r = det.bbox
            boxes.append(
                ft.Container(
                    left=r.x0 * scale, top=r.y0 * scale,
                    width=max(2, r.width * scale), height=max(2, r.height * scale),
                    bgcolor=_OCR_BOX_BG,
                    border=ft.border.all(2, _OCR_BOX_CLR),
                    tooltip=f"OCR ({det.score:.2f}): {det.text[:120]}",
                    on_click=_make_ocr_click(det, pn),
                )
            )
        ocr_ov.controls = boxes
        ocr_ov.visible  = True
        if force_update:
            try:
                ocr_ov.update()
            except Exception:
                pass

    # ── OCR overrides for AI agent ────────────────────────────────────────────

    def _build_ocr_overrides(self) -> dict[int, str]:
        overrides: dict[int, str] = {}
        for pn, result in self._ocr_by_page.items():
            text = "\n".join(seg.text for seg in result.segments if seg.text.strip())
            if text:
                overrides[pn] = text
        return overrides
