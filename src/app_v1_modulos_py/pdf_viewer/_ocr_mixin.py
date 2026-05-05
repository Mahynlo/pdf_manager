"""OCR execution, results display and sidebar panel for PDFViewerTab."""
from __future__ import annotations

import flet as ft

from .annotations import Tool
from .ocr import OCRPageResult
from .renderer import BASE_SCALE
from ._viewer_defs import _OCR_BOX_BG, _OCR_BOX_CLR, _OCR_PANEL_BG, _SELECTED_BG

_CHIP_BG   = "#E8F5E9"
_CHIP_FG   = "#2E7D32"
_METRIC_BG = "#F1F8E9"


def _chip(label: str, value: str, icon: str | None = None) -> ft.Container:
    """Small pill showing a label→value pair."""
    kids: list[ft.Control] = []
    if icon:
        kids.append(ft.Icon(icon, size=13, color=_CHIP_FG))
    kids.append(ft.Text(label, size=11, color="#607D8B", weight=ft.FontWeight.W_500))
    kids.append(ft.Text(value, size=11, color=_CHIP_FG, weight=ft.FontWeight.W_600))
    return ft.Container(
        content=ft.Row(kids, spacing=4, tight=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=_CHIP_BG,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=9, vertical=4),
    )


def _metric(icon: str, value: str, sublabel: str) -> ft.Container:
    """Small metric card with icon + value + sub-label."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [ft.Icon(icon, size=15, color=_CHIP_FG),
                     ft.Text(value, size=13, weight=ft.FontWeight.BOLD, color="#1B5E20")],
                    spacing=4, tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(sublabel, size=10, color="#78909C"),
            ],
            spacing=1, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=_METRIC_BG,
        border_radius=8,
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
        expand=True,
    )


class _OCRMixin:
    """OCR runner, results list, bounding-box overlay and sidebar panel."""

    # ── sidebar panel builder ─────────────────────────────────────────────────

    def _build_ocr_sidebar_panel(self) -> ft.Container:
        """Build the OCR panel and initialise all OCR UI controls."""

        # ── inference indicator ───────────────────────────────────────────────
        self._ocr_spinner      = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color="#2E7D32", visible=False,
        )
        self._ocr_stage_text   = ft.Text(
            "", size=11, color="#546E7A", italic=True, visible=False,
        )
        self._ocr_progress_bar = ft.ProgressBar(
            color="#43A047", bgcolor="#C8E6C9",
            height=4, border_radius=2,
            value=None,   # indeterminate
            visible=False,
        )
        self._ocr_running_row = ft.Row(
            [self._ocr_spinner, self._ocr_stage_text],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── stat chips (mode + doc-kind) ──────────────────────────────────────
        self._ocr_chip_mode    = ft.Container(visible=False)
        self._ocr_chip_kind    = ft.Container(visible=False)
        self._ocr_chips_row    = ft.Row(
            [self._ocr_chip_mode, self._ocr_chip_kind],
            spacing=6, wrap=True,
        )

        # ── metric cards (time + count) ───────────────────────────────────────
        self._ocr_metric_time  = ft.Container(visible=False, expand=True)
        self._ocr_metric_segs  = ft.Container(visible=False, expand=True)
        self._ocr_metrics_row  = ft.Row(
            [self._ocr_metric_time, self._ocr_metric_segs],
            spacing=6,
        )

        # ── status text (idle / error) ────────────────────────────────────────
        self._ocr_status_text  = ft.Text(
            "Ejecuta OCR para ver el texto extraído aquí.",
            size=12, color="#607D68", italic=True,
        )

        # ── copy button + header of result area ──────────────────────────────
        self._ocr_copy_btn = ft.IconButton(
            ft.Icons.CONTENT_COPY_OUTLINED,
            icon_size=16,
            tooltip="Copiar todo el texto",
            icon_color="#455A64",
            visible=False,
            on_click=self._ocr_copy_all,
            style=ft.ButtonStyle(padding=ft.padding.all(4)),
        )
        self._ocr_result_header = ft.Row(
            [
                ft.Text("Texto extraído", size=12,
                        weight=ft.FontWeight.W_600, color="#37474F"),
                ft.Container(expand=True),
                self._ocr_copy_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self._ocr_results_list = ft.ListView(
            expand=True, spacing=6,
            padding=ft.padding.only(bottom=8),
            auto_scroll=False,
        )

        self._ocr_content_area = ft.Container(
            ft.Column(
                [
                    self._ocr_running_row,
                    self._ocr_progress_bar,
                    self._ocr_status_text,
                    self._ocr_chips_row,
                    self._ocr_metrics_row,
                    ft.Divider(height=1, color="#DCE8DF"),
                    self._ocr_result_header,
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
                            ft.Text("Resultados OCR", size=14,
                                    weight=ft.FontWeight.W_600),
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

    # ── inference indicator helpers ───────────────────────────────────────────

    def _ocr_set_running(self, stage: str) -> None:
        """Show the animated spinner + progress bar with a stage description."""
        self._ocr_spinner.visible      = True
        self._ocr_stage_text.value     = stage
        self._ocr_stage_text.visible   = True
        self._ocr_progress_bar.visible = True
        self._ocr_status_text.visible  = False
        self._ocr_chip_mode.visible    = False
        self._ocr_chip_kind.visible    = False
        self._ocr_metric_time.visible  = False
        self._ocr_metric_segs.visible  = False
        self._ocr_copy_btn.visible     = False
        self._ocr_results_list.controls = []
        try:
            self._ocr_content_area.update()
        except Exception:
            pass

    def _ocr_set_idle(self, message: str) -> None:
        """Show the idle/error placeholder (no spinner)."""
        self._ocr_spinner.visible      = False
        self._ocr_stage_text.visible   = False
        self._ocr_progress_bar.visible = False
        self._ocr_status_text.value    = message
        self._ocr_status_text.visible  = True
        self._ocr_chip_mode.visible    = False
        self._ocr_chip_kind.visible    = False
        self._ocr_metric_time.visible  = False
        self._ocr_metric_segs.visible  = False
        self._ocr_copy_btn.visible     = False

    def _ocr_set_done(self, result: OCRPageResult) -> None:
        """Populate stats chips, metric cards, and copy button after OCR."""
        self._ocr_spinner.visible      = False
        self._ocr_stage_text.visible   = False
        self._ocr_progress_bar.visible = False
        self._ocr_status_text.visible  = False

        # mode chip
        mode_icon = {
            "OCR":     ft.Icons.SCANNER,
            "Nativo":  ft.Icons.TEXT_FIELDS,
            "Híbrido": ft.Icons.LAYERS,
        }.get(result.mode_label, ft.Icons.INFO_OUTLINE)
        self._ocr_chip_mode.content = _chip(
            "Modo", result.mode_label, icon=mode_icon
        ).content
        self._ocr_chip_mode.bgcolor     = _CHIP_BG
        self._ocr_chip_mode.border_radius = 20
        self._ocr_chip_mode.padding     = ft.padding.symmetric(horizontal=9, vertical=4)
        self._ocr_chip_mode.visible     = True

        # kind chip
        kind_label = self._doc_kind_label(result.doc_kind)
        kind_icon  = {
            "Texto nativo": ft.Icons.ARTICLE_OUTLINED,
            "Escaneado":    ft.Icons.IMAGE_OUTLINED,
            "Híbrido":      ft.Icons.LAYERS_OUTLINED,
        }.get(kind_label, ft.Icons.DESCRIPTION_OUTLINED)
        self._ocr_chip_kind.content = _chip(
            "Tipo", kind_label, icon=kind_icon
        ).content
        self._ocr_chip_kind.bgcolor     = _CHIP_BG
        self._ocr_chip_kind.border_radius = 20
        self._ocr_chip_kind.padding     = ft.padding.symmetric(horizontal=9, vertical=4)
        self._ocr_chip_kind.visible     = True

        # time metric
        t_ms = result.elapsed_ms
        t_val = f"{t_ms:.0f} ms" if t_ms < 1000 else f"{t_ms/1000:.1f} s"
        self._ocr_metric_time.content = _metric(
            ft.Icons.TIMER_OUTLINED, t_val, "Tiempo"
        ).content
        self._ocr_metric_time.bgcolor      = _METRIC_BG
        self._ocr_metric_time.border_radius = 8
        self._ocr_metric_time.padding      = ft.padding.symmetric(horizontal=10, vertical=6)
        self._ocr_metric_time.expand       = True
        self._ocr_metric_time.visible      = True

        # segments metric
        n_segs = len(result.segments)
        self._ocr_metric_segs.content = _metric(
            ft.Icons.FORMAT_LIST_BULLETED, str(n_segs), "Segmentos"
        ).content
        self._ocr_metric_segs.bgcolor      = _METRIC_BG
        self._ocr_metric_segs.border_radius = 8
        self._ocr_metric_segs.padding      = ft.padding.symmetric(horizontal=10, vertical=6)
        self._ocr_metric_segs.expand       = True
        self._ocr_metric_segs.visible      = True

        self._ocr_copy_btn.visible = bool(result.segments)

    # ── copy all text ─────────────────────────────────────────────────────────

    def _ocr_copy_all(self, e=None) -> None:
        result = self._ocr_by_page.get(self.current_page)
        if result is None:
            return
        text = "\n".join(seg.text for seg in result.segments if seg.text.strip())
        if text:
            self.page_ref.set_clipboard(text)
            n = len(result.segments)
            self._show_snack(f"Copiado: {n} segmento{'s' if n != 1 else ''}")

    # ── OCR execution ─────────────────────────────────────────────────────────

    def _run_ocr(self, e=None) -> None:
        if hasattr(self, "_switch_sidebar_mode"):
            self._switch_sidebar_mode("ocr")
        elif not self._sidebar_visible:
            self._toggle_sidebar()

        pn = self.current_page
        self._ocr_set_running(f"Analizando página {pn + 1}…")
        self.page_ref.update()

        try:
            with self._doc_lock:
                result = self._ocr_processor.process_page(self.doc, pn, force_ocr=True)
        except Exception as ex:
            self._ocr_set_idle(f"Error en página {pn + 1}: {ex}")
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
        self._page_words.pop(pn, None)
        self._ocr_active_index = 0
        self._refresh_ocr_ui_for_page()
        if self._agent_instance is not None:
            self._agent_instance.set_ocr_overrides(self._build_ocr_overrides())
        self._show_snack("OCR completado")
        self.page_ref.update()

    # ── OCR UI refresh ────────────────────────────────────────────────────────

    @staticmethod
    def _doc_kind_label(kind: str) -> str:
        return {"native": "Texto nativo", "scanned": "Escaneado",
                "hybrid": "Híbrido"}.get(kind, kind)

    def _refresh_ocr_ui_for_page(self) -> None:
        result = self._ocr_by_page.get(self.current_page)
        pn     = self.current_page

        if result is None:
            self._ocr_set_idle(f"Página {pn + 1}: ejecuta OCR para ver el texto.")
            self._ocr_results_list.controls = [
                ft.Container(
                    ft.Text("Ejecuta OCR para ver texto extraído aquí.",
                            size=12, color="#607D68"),
                    padding=ft.padding.all(8),
                )
            ]
            if pn < len(self._ocr_overlays):
                self._ocr_overlays[pn].visible  = False
                self._ocr_overlays[pn].controls = []
            return

        self._ocr_set_done(result)
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
                ft.Text(text_body or "Sin texto extraído",
                        size=12, selectable=True),
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
