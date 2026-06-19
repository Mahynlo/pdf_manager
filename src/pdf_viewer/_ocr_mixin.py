"""OCR execution, results display and sidebar panel for PDFViewerTab."""
from __future__ import annotations

import gc
import threading
from pathlib import Path
import flet as ft

from .annotations import Tool
from .ocr import OCRPageResult
from .renderer import BASE_SCALE
from ._viewer_defs import _OCR_BOX_BG, _OCR_BOX_CLR, _OCR_PANEL_BG, _SELECTED_BG

_CHIP_BG   = ft.Colors.with_opacity(0.15, "#2E7D32")
_CHIP_FG   = "#2E7D32"
_METRIC_BG = "surfaceVariant"

_MAX_OCR_PAGES_CACHED = 8  # max pages kept in memory; oldest are evicted first
_OCR_MODEL_RELEASE_DELAY = 3.0  # seconds to unload OCR model after idle


def _chip(label: str, value: str, icon: str | None = None) -> ft.Container:
    """Small pill showing a label→value pair."""
    kids: list[ft.Control] = []
    if icon:
        kids.append(ft.Icon(icon, size=13, color=_CHIP_FG))
    kids.append(ft.Text(label, size=11, color="onSurfaceVariant", weight=ft.FontWeight.W_500))
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
                     ft.Text(value, size=13, weight=ft.FontWeight.BOLD, color="onSurface")],
                    spacing=4, tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(sublabel, size=10, color="onSurfaceVariant"),
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

    def _ensure_ocr_processor(self) -> None:
        if getattr(self, "_ocr_processor", None) is None:
            from .ocr import OCRProcessor
            self._ocr_processor = OCRProcessor(
                str(Path(__file__).resolve().parents[2])
            )

    # ── sidebar panel builder ─────────────────────────────────────────────────

    def _build_ocr_sidebar_panel(self) -> ft.Container:
        """Build the OCR panel and initialise all OCR UI controls."""

        # ── inference indicator ───────────────────────────────────────────────
        self._ocr_spinner      = ft.ProgressRing(
            width=28, height=28, stroke_width=3, color="#2E7D32", visible=False,
        )
        self._ocr_stage_text   = ft.Text(
            "", size=11, color="onSurfaceVariant", italic=True, visible=False,
        )
        self._ocr_progress_bar = ft.ProgressBar(
            color="#43A047", bgcolor=ft.Colors.with_opacity(0.15, "#2E7D32"),
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
            size=12, color="onSurfaceVariant", italic=True,
        )

        # ── copy button + header of result area ──────────────────────────────
        self._ocr_copy_btn = ft.IconButton(
            ft.Icons.CONTENT_COPY_OUTLINED,
            icon_size=16,
            tooltip="Copiar todo el texto",
            icon_color="onSurfaceVariant",
            visible=False,
            on_click=self._ocr_copy_all,
            style=ft.ButtonStyle(padding=ft.padding.all(4)),
        )
        self._ocr_result_header = ft.Row(
            [
                ft.Text("Texto extraído", size=12,
                        weight=ft.FontWeight.W_600, color="onSurface"),
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
                    ft.Divider(height=1, color="outlineVariant"),
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
        if hasattr(self, "_update_scroll_column_width"):
            self._update_scroll_column_width()

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

    # ── LRU eviction ─────────────────────────────────────────────────────────

    def _evict_old_ocr_pages(self, keep_pn: int) -> None:
        """Remove oldest cached OCR pages (keeping keep_pn) to bound memory use."""
        while len(self._ocr_by_page) > _MAX_OCR_PAGES_CACHED:
            evict_pn = next((p for p in self._ocr_by_page if p != keep_pn), None)
            if evict_pn is None:
                break
            del self._ocr_by_page[evict_pn]
            # Descartar también las cachés de texto derivadas de las detecciones
            # eviccionadas (palabras de selección, índice de hover): si quedaran,
            # la página seguiría seleccionable "a medias" hasta la siguiente poda
            # de ventana, con cursor de texto sobre regiones ya inertes.
            self._page_words.pop(evict_pn, None)
            self._page_word_bands.pop(evict_pn, None)
            self._text_rects_cache.pop(evict_pn, None)
            if evict_pn < len(self._ocr_overlays):
                ov = self._ocr_overlays[evict_pn]
                if ov is not None:  # slot no construido (placeholder)
                    ov.controls = []
                    ov.visible = False

    def _schedule_ocr_model_release(self) -> None:
        t = getattr(self, "_ocr_model_timer", None)
        if t is not None:
            t.cancel()
        self._ocr_model_timer = threading.Timer(
            _OCR_MODEL_RELEASE_DELAY, self._release_ocr_model
        )
        self._ocr_model_timer.daemon = True
        self._ocr_model_timer.start()

    def _cancel_ocr_model_release(self) -> None:
        t = getattr(self, "_ocr_model_timer", None)
        if t is not None:
            t.cancel()
            self._ocr_model_timer = None

    def _release_ocr_model(self) -> None:
        if getattr(self, "_ocr_processor", None) is not None:
            self._ocr_processor.release_predictor()
        gc.collect()

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

        self._cancel_ocr_model_release()
        self._ensure_ocr_processor()
        pn = self.current_page
        self._ocr_set_running(f"Analizando página {pn + 1}…")
        self.page_ref.update()

        try:
            # Solo la rasterización necesita el documento; la inferencia (los
            # segundos lentos) corre SIN _doc_lock para que los workers de
            # render no se bloqueen — antes, hacer scroll durante el OCR dejaba
            # las páginas en blanco hasta que terminara.
            with self._doc_lock:
                prep = self._ocr_processor.prepare_page(self.doc, pn, force_ocr=True)
            result = self._ocr_processor.recognize_page(prep)
        except Exception as ex:
            self._ocr_set_idle(f"Error en página {pn + 1}: {ex}")
            self._ocr_results_list.controls = [
                ft.Container(
                    ft.Text(f"Error OCR: {ex}", size=12, color="error", selectable=True),
                    padding=ft.padding.all(8),
                )
            ]
            self._show_snack(f"Error OCR: {ex}")
            self.page_ref.update()
            self._schedule_ocr_model_release()
            return

        self._ocr_by_page[pn] = result
        self._evict_old_ocr_pages(keep_pn=pn)
        gc.collect()
        # Las cachés de texto de la página quedaron obsoletas: las palabras deben
        # incluir las detecciones nuevas y el índice de hover debe reindexarlas.
        self._page_words.pop(pn, None)
        self._page_word_bands.pop(pn, None)
        self._text_rects_cache.pop(pn, None)
        self._ocr_active_index = 0
        self._refresh_ocr_ui_for_page()
        if self._agent_instance is not None:
            self._agent_instance.set_ocr_overrides(self._build_ocr_overrides())
        self._show_snack("OCR completado")
        self.page_ref.update()
        self._schedule_ocr_model_release()

    # ── auto-corrección de orientación (escaneos sin /Rotate) ─────────────────

    def _fix_orientation(self, e=None) -> None:
        """Detecta y corrige la orientación de un escaneo cuyo contenido está
        girado pero sin entrada ``/Rotate`` (la página se ve de lado).

        Detecta sobre la página actual con los modelos OCR ya incluidos y, como
        los escaneos suelen compartir orientación, aplica el mismo giro a TODAS
        las páginas vía ``page.set_rotation`` — lo que hace que se muestren
        derechas y que el resto de funciones (OCR, censura, anotaciones) trabajen
        con coordenadas correctas. No se guarda hasta que el usuario guarde."""
        self._cancel_ocr_model_release()
        self._ensure_ocr_processor()
        pn = self.current_page
        self._show_snack("Detectando orientación…")
        try:
            self.page_ref.update()
        except Exception:
            pass

        try:
            # Igual que en _run_ocr: rasterizar bajo lock, inferir (4 pasadas
            # del modelo) sin él.
            with self._doc_lock:
                probe = self._ocr_processor.render_orientation_probe(self.doc, pn)
            angle = self._ocr_processor.score_orientation(probe)
        except Exception as ex:
            self._show_snack(f"No se pudo detectar la orientación: {ex}")
            self._schedule_ocr_model_release()
            return

        if angle == 0:
            self._show_snack("La orientación ya parece correcta")
            self._schedule_ocr_model_release()
            return

        with self._doc_lock:
            n = len(self.doc)
            for p in range(n):
                page = self.doc[p]
                page.set_rotation((page.rotation + angle) % 360)

        # Las coordenadas cacheadas (imágenes, OCR, texto, censura) quedaron
        # obsoletas tras cambiar la rotación.
        _rcache = getattr(self, "_render_cache", None)
        if _rcache is not None:
            _rcache.clear()
        self._ocr_by_page = {}
        self._page_words = {}
        self._page_word_bands = {}
        self._page_blocks_cache = {}
        self._text_rects_cache = {}
        if hasattr(self, "_clear_redact_state"):
            self._clear_redact_state()

        saved = self.current_page
        self._rebuild_scroll_content(scroll_back=False)
        try:
            self.viewer_scroll.scroll_to(
                offset=self._page_cum_offsets[saved], duration=0,
            )
        except Exception:
            pass
        self._refresh_ocr_ui_for_page()
        self.page_ref.update()
        self._show_snack(
            f"Orientación corregida (+{angle}°) en {n} página(s). "
            f"Guarda el PDF para conservarlo."
        )
        self._schedule_ocr_model_release()

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
                            size=12, color="onSurfaceVariant"),
                    padding=ft.padding.all(8),
                )
            ]
            if pn < len(self._ocr_overlays) and self._ocr_overlays[pn] is not None:
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
                    ft.Text("Sin texto extraído", size=12, color="onSurfaceVariant"),
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
                border=ft.border.all(1, "outlineVariant"),
                bgcolor="surface",
                border_radius=8,
            )
        ]

    def _render_ocr_boxes(self, *, force_update: bool = False, pn: int | None = None) -> None:
        if pn is None:
            pn = self.current_page
        if pn >= len(self._ocr_overlays):
            return
        ocr_ov = self._ocr_overlays[pn]
        if ocr_ov is None:  # slot no construido (placeholder) → nada que dibujar
            return
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
