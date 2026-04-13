"""PDFViewerTab: full-featured PDF viewer — continuous scroll, lazy rendering."""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Callable

import flet as ft
import fitz

from .annotations import AnnotationManager, HIGHLIGHT_COLORS, Tool
from .ocr import OCRPageResult, OCRProcessor
from .renderer import BASE_SCALE, ZOOM_LEVELS, display_to_pdf, render_page


# ── constants ───────────────────────────────────────────────────────────────

_TOOL_DEFS: list[tuple[Tool, str, str, ft.MouseCursor]] = [
    (Tool.CURSOR,    ft.Icons.NEAR_ME,             "Cursor (seleccionar anotación)", ft.MouseCursor.BASIC),
    (Tool.SELECT,    ft.Icons.TEXT_FIELDS,          "Seleccionar texto",              ft.MouseCursor.TEXT),
    (Tool.HIGHLIGHT, ft.Icons.HIGHLIGHT,            "Resaltar",                       ft.MouseCursor.PRECISE),
    (Tool.UNDERLINE, ft.Icons.FORMAT_UNDERLINE,     "Subrayar",                       ft.MouseCursor.PRECISE),
    (Tool.STRIKEOUT, ft.Icons.FORMAT_STRIKETHROUGH, "Tachar",                         ft.MouseCursor.PRECISE),
    (Tool.RECT,      ft.Icons.CROP_DIN,             "Rectángulo",                     ft.MouseCursor.PRECISE),
    (Tool.CIRCLE,    ft.Icons.PANORAMA_FISH_EYE,    "Círculo / Elipse",               ft.MouseCursor.PRECISE),
    (Tool.LINE,      ft.Icons.SHOW_CHART,           "Línea",                          ft.MouseCursor.PRECISE),
]

_SELECTED_BG  = "#DDEEFF"
_TOOLBAR_BG   = "#F3F3F3"
_ANNOT_BG     = "#EBEBEB"
_DIVIDER_CLR  = "#BDBDBD"
_VIEWER_BG    = "#757575"
_SEL_BAR_BG   = "#FFF9C4"
_SEL_BAR_BDR  = "#F0C800"
_OCR_BOX_CLR  = "#2E7D32"
_OCR_BOX_BG   = "#331B5E20"
_OCR_PANEL_BG = "#F7FBF8"
_PAGE_BG         = "#AAAAAA"  # placeholder grey while page image is not rendered
_PAGE_GAP        = 16         # vertical gap between pages (px)
_PRELOAD         = 2          # pages to render eagerly on first load
_EVICT_MARGIN    = 3          # viewport heights of buffer to keep rendered on each side
_EVICT_THRESHOLD = 400        # scroll pixels between eviction passes


def _vdivider() -> ft.Container:
    return ft.Container(width=1, height=28, bgcolor=_DIVIDER_CLR)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


# ── main class ───────────────────────────────────────────────────────────────

class PDFViewerTab:
    """Manages state and UI for a single open PDF document."""

    def __init__(self, path: str, page_ref: ft.Page, on_close: Callable):
        self.path     = path
        self.page_ref = page_ref
        self.on_close = on_close
        self.filename = Path(path).name
        self.doc      = fitz.open(path)

        self.current_page    = 0
        self.zoom            = 1.0
        self._current_cursor = ft.MouseCursor.BASIC

        self._tab       = None
        self._annot     = AnnotationManager(on_modified=self._update)
        self._tool_btns: dict[Tool, ft.IconButton] = {}

        # Annotation selection state  (page_num, xref)
        self._selected:         tuple[int, int] | None = None
        self._pending_tap:      tuple[float, float] | None = None
        self._pending_tap_page: int | None = None
        self._moving_selected   = False
        self._move_last_pdf:    tuple[float, float] | None = None

        # Per-page render state
        self._page_images:      list[ft.Image] = []
        self._drag_overlays:    list[ft.Container] = []
        self._sel_overlays:     list[ft.Container] = []
        self._ocr_overlays:     list[ft.Stack] = []
        self._page_slots:       list[ft.Container] = []
        self._page_gestures:    list[ft.GestureDetector] = []
        self._page_cum_offsets: list[float] = []   # scroll-offset of each page top
        self._page_heights:     list[float] = []   # display pixel height of each page
        self._rendered:         set[int] = set()   # pages with base64 image loaded

        # Background rendering / eviction
        self._doc_lock       = threading.Lock()   # protects fitz.Document access
        self._rendering:     set[int] = set()     # pages with a render in-flight
        self._render_gen     = 0                  # incremented on rebuild to cancel stale renders
        self._last_evict_px  = -9999.0            # last scroll position where eviction ran

        self._ocr_processor  = OCRProcessor(str(Path(__file__).resolve().parents[2]))
        self._ocr_by_page:   dict[int, OCRPageResult] = {}
        self._ocr_show_boxes = False
        self._ocr_active_index = 0

        self._save_picker = ft.FilePicker(on_result=self._on_save_result)
        page_ref.overlay.append(self._save_picker)

        self._build()

    # ────────────────────────────────────────────── build

    def _build(self) -> None:
        total = len(self.doc)

        # ── navigation toolbar ─────────────────────────
        self.prev_btn = ft.IconButton(
            ft.Icons.NAVIGATE_BEFORE, tooltip="Página anterior",
            on_click=self._prev, disabled=True,
        )
        self.page_input = ft.TextField(
            value="1", width=52, dense=True,
            text_align=ft.TextAlign.CENTER,
            on_submit=self._go_to_page,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=0),
        )
        self.total_label = ft.Text(f"/ {total}", size=14)
        self.next_btn = ft.IconButton(
            ft.Icons.NAVIGATE_NEXT, tooltip="Página siguiente",
            on_click=self._next, disabled=(total <= 1),
        )
        self.zoom_out_btn = ft.IconButton(
            ft.Icons.REMOVE, tooltip="Alejar", on_click=self._zoom_out,
        )
        self.zoom_label = ft.Text(
            "100%", width=52, text_align=ft.TextAlign.CENTER, size=14,
        )
        self.zoom_in_btn = ft.IconButton(
            ft.Icons.ADD, tooltip="Acercar", on_click=self._zoom_in,
        )

        zoom_menu = ft.PopupMenuButton(
            icon=ft.Icons.ARROW_DROP_DOWN,
            tooltip="Nivel de zoom",
            items=[
                ft.PopupMenuItem(text="Ajustar al ancho",    on_click=self._fit_width),
                ft.PopupMenuItem(text="Ajustar a la página", on_click=self._fit_page),
                ft.PopupMenuItem(),
                *[
                    ft.PopupMenuItem(
                        text=f"{int(z * 100)}%",
                        on_click=lambda e, _z=z: self._set_zoom(_z),
                    )
                    for z in ZOOM_LEVELS
                ],
            ],
        )

        nav_toolbar = ft.Container(
            ft.Row(
                [
                    self.prev_btn, self.page_input, self.total_label, self.next_btn,
                    _vdivider(),
                    self.zoom_out_btn, self.zoom_label, self.zoom_in_btn, zoom_menu,
                    _vdivider(),
                    ft.IconButton(
                        ft.Icons.ROTATE_RIGHT, tooltip="Rotar 90°",
                        on_click=self._rotate,
                    ),
                    _vdivider(),
                    ft.IconButton(
                        ft.Icons.UNDO, tooltip="Deshacer última anotación  (Ctrl+Z)",
                        on_click=self._undo,
                    ),
                    _vdivider(),
                    ft.IconButton(
                        ft.Icons.SAVE_ALT, tooltip="Guardar PDF con anotaciones",
                        on_click=self._save,
                    ),
                    _vdivider(),
                    ft.IconButton(
                        ft.Icons.DOCUMENT_SCANNER,
                        tooltip="Ejecutar OCR en la página actual",
                        on_click=self._run_ocr,
                    ),
                    ft.IconButton(
                        ft.Icons.GRID_ON,
                        tooltip="Mostrar/Ocultar detección OCR",
                        on_click=self._toggle_ocr_boxes,
                    ),
                ],
                spacing=2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            bgcolor=_TOOLBAR_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _DIVIDER_CLR)),
        )

        # ── annotation toolbar ─────────────────────────
        tool_btns: list[ft.Control] = []
        for tool, icon, tooltip, cursor in _TOOL_DEFS:
            btn = ft.IconButton(
                icon, tooltip=tooltip,
                icon_color="#444444",
                bgcolor=_SELECTED_BG if tool == Tool.CURSOR else None,
                on_click=lambda e, t=tool, c=cursor: self._select_tool(t, c),
            )
            self._tool_btns[tool] = btn
            tool_btns.append(btn)

        color_menu = ft.PopupMenuButton(
            icon=ft.Icons.PALETTE,
            tooltip="Color de resaltado",
            items=[
                ft.PopupMenuItem(
                    text=name,
                    on_click=lambda e, c=rgb: self._set_highlight_color(c),
                )
                for name, rgb in HIGHLIGHT_COLORS
            ],
        )

        annot_toolbar = ft.Container(
            ft.Row(
                [*tool_btns, _vdivider(), color_menu],
                spacing=2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=2),
            bgcolor=_ANNOT_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _DIVIDER_CLR)),
        )

        # ── annotation selection action bar ──────────────────────────────────
        self._sel_label = ft.Text("Anotación seleccionada", size=12, color="#555555")
        self._annot_action_bar = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.TOUCH_APP, size=16, color="#888888"),
                    self._sel_label,
                    ft.TextButton(
                        "Eliminar",
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_600,
                        on_click=self._delete_selected,
                    ),
                    ft.TextButton(
                        "Cambiar color",
                        icon=ft.Icons.PALETTE_OUTLINED,
                        on_click=self._recolor_selected_menu,
                    ),
                    ft.TextButton(
                        "Reducir",
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        on_click=self._scale_down_selected,
                    ),
                    ft.TextButton(
                        "Agrandar",
                        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                        on_click=self._scale_up_selected,
                    ),
                    ft.TextButton(
                        "Deseleccionar",
                        icon=ft.Icons.CLOSE,
                        on_click=self._deselect_annot,
                    ),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            bgcolor=_SEL_BAR_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _SEL_BAR_BDR)),
            visible=False,
        )

        # ── OCR side panel ────────────────────────────────────────────────────
        self._ocr_info      = ft.Text("OCR: sin ejecutar", size=12, color="#455A64")
        self._ocr_source    = ft.Text("Modo: -",           size=12, color="#455A64")
        self._ocr_doc_kind  = ft.Text("Documento: -",      size=12, color="#455A64")
        self._ocr_time      = ft.Text("Tiempo: -",         size=12, color="#455A64")
        self._ocr_count     = ft.Text("Resultados: -",     size=12, color="#455A64")
        self._ocr_results_list = ft.ListView(
            expand=True, spacing=6,
            padding=ft.padding.only(bottom=8),
            auto_scroll=False,
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
                    ),
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
            width=360,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=_OCR_PANEL_BG,
            border=ft.border.only(left=ft.BorderSide(1, "#D5E6D8")),
            visible=True,
        )

        # ── scroll area (all pages stacked vertically) ────────────────────────
        self.viewer_scroll = ft.Column(
            controls=[],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            on_scroll=self._on_view_scroll,
            spacing=_PAGE_GAP,
        )

        # Populate per-page controls and render first pages eagerly
        self._rebuild_scroll_content(scroll_back=False)

        viewer_body = ft.Container(
            self.viewer_scroll,
            expand=True,
            bgcolor=_VIEWER_BG,
            padding=20,
        )

        main_content = ft.Row(
            [viewer_body, self._ocr_panel],
            expand=True,
            spacing=0,
        )

        self.view = ft.Column(
            [nav_toolbar, annot_toolbar, self._annot_action_bar, main_content],
            expand=True,
            spacing=0,
        )

    # ────────────────────────────────────────────── per-page control factory

    def _rebuild_scroll_content(self, scroll_back: bool = True) -> None:
        """(Re)build all page slot controls. Called on init and after zoom/rotate."""
        # Increment generation so any in-flight render workers abort cleanly
        self._render_gen    += 1
        self._rendering      = set()
        self._last_evict_px  = -9999.0

        with self._doc_lock:
            total = len(self.doc)

        self._page_images      = []
        self._drag_overlays    = []
        self._sel_overlays     = []
        self._ocr_overlays     = []
        self._page_slots       = []
        self._page_gestures    = []
        self._page_cum_offsets = []
        self._page_heights     = []
        self._rendered         = set()
        self._selected         = None

        cum   = 0.0
        rows: list[ft.Control] = []

        # Pre-read all page dimensions under the lock (fast metadata read)
        with self._doc_lock:
            page_dims = [
                (int(self.doc[pn].rect.width  * BASE_SCALE * self.zoom),
                 int(self.doc[pn].rect.height * BASE_SCALE * self.zoom))
                for pn in range(total)
            ]

        for pn in range(total):
            w, h = page_dims[pn]

            img = ft.Image(
                width=w, height=h,
                fit=ft.ImageFit.NONE,
                gapless_playback=True,
            )
            drag_ov = ft.Container(
                visible=False,
                bgcolor=self._annot.overlay_color,
                border=ft.border.all(1, "#0055AA"),
                left=0, top=0, width=0, height=0,
            )
            sel_ov = ft.Container(
                visible=False,
                bgcolor="#200055FF",
                border=ft.border.all(2, "#0055FF"),
                left=0, top=0, width=0, height=0,
            )
            ocr_ov = ft.Stack([], visible=False)

            self._page_images.append(img)
            self._drag_overlays.append(drag_ov)
            self._sel_overlays.append(sel_ov)
            self._ocr_overlays.append(ocr_ov)
            self._page_cum_offsets.append(cum)
            self._page_heights.append(float(h))
            cum += h + _PAGE_GAP

            slot = ft.Container(
                content=ft.Stack([img, drag_ov, sel_ov, ocr_ov]),
                width=w, height=h,
                bgcolor=_PAGE_BG,
                border_radius=2,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
            self._page_slots.append(slot)

            gd = ft.GestureDetector(
                content=slot,
                on_tap_down  = lambda e, p=pn: self._on_tap_down(e, p),
                on_tap       = lambda e, p=pn: self._on_tap(e, p),
                on_pan_start = lambda e, p=pn: self._on_pan_start(e, p),
                on_pan_update= lambda e, p=pn: self._on_pan_update(e, p),
                on_pan_end   = lambda e, p=pn: self._on_pan_end(e, p),
                mouse_cursor = self._current_cursor,
            )
            self._page_gestures.append(gd)
            rows.append(ft.Row([gd], alignment=ft.MainAxisAlignment.CENTER))

        self.viewer_scroll.controls = rows

        # Eagerly render the first few visible pages
        for pn in range(min(total, 1 + _PRELOAD)):
            self._render_page_slot(pn)

        if scroll_back and self._page_cum_offsets:
            try:
                self.viewer_scroll.scroll_to(
                    offset=self._page_cum_offsets[self.current_page],
                    duration=0,
                )
            except Exception:
                pass

    def _render_page_slot(self, pn: int) -> None:
        """Schedule background render for one page (no-op if rendered/in-flight)."""
        if pn in self._rendered or pn in self._rendering:
            return
        self._rendering.add(pn)
        gen = self._render_gen

        def _worker() -> None:
            try:
                with self._doc_lock:
                    # Abort if layout was rebuilt while waiting for the lock
                    if gen != self._render_gen or pn >= len(self._page_images):
                        return
                    b64, w, h = render_page(self.doc, pn, self.zoom)

                # UI update outside the lock (no fitz access)
                if gen != self._render_gen or pn >= len(self._page_images):
                    return
                img  = self._page_images[pn]
                slot = self._page_slots[pn]
                img.src_base64 = b64
                img.width      = w
                img.height     = h
                slot.bgcolor   = None  # remove grey placeholder
                self._rendered.add(pn)
                try:
                    slot.update()
                except Exception:
                    pass
            finally:
                self._rendering.discard(pn)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_visible(self, pixels: float, viewport_h: float) -> None:
        """Schedule renders for all pages that are currently (or nearly) visible."""
        margin = viewport_h * 0.5
        top    = pixels - margin
        bottom = pixels + viewport_h + margin
        for pn, (start, h) in enumerate(zip(self._page_cum_offsets, self._page_heights)):
            if start + h >= top and start <= bottom:
                self._render_page_slot(pn)  # no-op if already rendered/in-flight

    def _evict_distant(self, pixels: float, viewport_h: float) -> None:
        """Free base64 image data for pages well outside the current viewport.

        Only pages whose entire height is outside a _EVICT_MARGIN-viewport buffer
        on each side are freed. They will be re-rendered lazily when scrolled back.
        """
        keep_top    = pixels - viewport_h * _EVICT_MARGIN
        keep_bottom = pixels + viewport_h * (1.0 + _EVICT_MARGIN)
        for pn, (start, h) in enumerate(zip(self._page_cum_offsets, self._page_heights)):
            if pn not in self._rendered:
                continue
            page_bottom = start + h
            if page_bottom < keep_top or start > keep_bottom:
                self._rendered.discard(pn)
                self._page_images[pn].src_base64 = None
                self._page_slots[pn].bgcolor = _PAGE_BG
                # No slot.update() here — pages are off-screen.
                # When the user scrolls back, _render_page_slot will set the new
                # src_base64 and call slot.update() from the worker thread.

    # ────────────────────────────────────────────── render / update

    def _refresh_page(self, pn: int) -> None:
        """Re-render one page after annotation change."""
        # Clear annotation selection if it was on this page
        if self._selected is not None and self._selected[0] == pn:
            self._selected = None
            self._sel_overlays[pn].visible = False
            self._annot_action_bar.visible = False

        self._rendered.discard(pn)
        self._render_page_slot(pn)
        self._refresh_ocr_ui_for_page()
        self.page_ref.update()

    def _update(self) -> None:
        """Called by AnnotationManager.on_modified; re-renders current page."""
        self._refresh_page(self.current_page)

    def _update_nav_state(self) -> None:
        total = len(self.doc)
        self.page_input.value    = str(self.current_page + 1)
        self.prev_btn.disabled   = self.current_page == 0
        self.next_btn.disabled   = self.current_page == total - 1

    def _on_view_scroll(self, e: ft.OnScrollEvent) -> None:
        pixels     = getattr(e, "pixels",            None)
        viewport_h = getattr(e, "viewport_dimension", None) or 600.0

        if pixels is None:
            return

        # Update current_page to whichever page's centre is closest to mid-viewport
        mid        = float(pixels) + float(viewport_h) / 2.0
        page_changed = False
        for pn in range(len(self._page_cum_offsets) - 1, -1, -1):
            if self._page_cum_offsets[pn] <= mid:
                if pn != self.current_page:
                    self.current_page = pn
                    self._update_nav_state()
                    self._refresh_ocr_ui_for_page()
                    page_changed = True
                break

        px = float(pixels)
        vh = float(viewport_h)
        self._render_visible(px, vh)

        # Flush nav/OCR changes to the client whenever the visible page changes
        if page_changed:
            try:
                self.page_ref.update()
            except Exception:
                pass

        # Evict distant pages, but throttled to avoid iterating the full list every event
        if abs(px - self._last_evict_px) >= _EVICT_THRESHOLD:
            self._last_evict_px = px
            self._evict_distant(px, vh)

    def _show_snack(self, msg: str) -> None:
        self.page_ref.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
        self.page_ref.update()

    # ────────────────────────────────────────────── navigation

    def _scroll_to_page(self, pn: int) -> None:
        self.current_page = pn
        self._update_nav_state()
        self._render_page_slot(pn)
        self._refresh_ocr_ui_for_page()
        try:
            self.viewer_scroll.scroll_to(
                offset=self._page_cum_offsets[pn],
                duration=250,
            )
        except Exception:
            pass
        self.page_ref.update()

    def _prev(self, e=None) -> None:
        if self.current_page > 0:
            self._scroll_to_page(self.current_page - 1)

    def _next(self, e=None) -> None:
        if self.current_page < len(self.doc) - 1:
            self._scroll_to_page(self.current_page + 1)

    def _go_to_page(self, e) -> None:
        try:
            n = int(self.page_input.value) - 1
            if 0 <= n < len(self.doc):
                self._scroll_to_page(n)
                return
        except ValueError:
            pass
        self.page_input.value = str(self.current_page + 1)
        self.page_input.update()

    # ────────────────────────────────────────────── zoom

    def _apply_zoom(self) -> None:
        """Rebuild all page slots with the new zoom level and return to current page."""
        self.zoom_label.value = f"{int(round(self.zoom * 100))}%"
        saved = self.current_page
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        try:
            self.viewer_scroll.scroll_to(
                offset=self._page_cum_offsets[saved],
                duration=0,
            )
        except Exception:
            pass
        self.page_ref.update()

    def _zoom_out(self, e=None) -> None:
        candidates = [z for z in ZOOM_LEVELS if z < self.zoom - 0.01]
        if candidates:
            self.zoom = candidates[-1]
            self._apply_zoom()

    def _zoom_in(self, e=None) -> None:
        candidates = [z for z in ZOOM_LEVELS if z > self.zoom + 0.01]
        if candidates:
            self.zoom = candidates[0]
            self._apply_zoom()

    def _set_zoom(self, z: float) -> None:
        self.zoom = z
        self._apply_zoom()

    def _fit_width(self, e=None) -> None:
        with self._doc_lock:
            p = self.doc[self.current_page]
            pw = p.rect.width
        available = (self.page_ref.width or 900) - 72
        self.zoom = available / (pw * BASE_SCALE)
        self._apply_zoom()

    def _fit_page(self, e=None) -> None:
        with self._doc_lock:
            p = self.doc[self.current_page]
            pw, ph = p.rect.width, p.rect.height
        avail_w = (self.page_ref.width  or 900) - 72
        avail_h = (self.page_ref.height or 650) - 180
        self.zoom = min(
            avail_w / (pw * BASE_SCALE),
            avail_h / (ph * BASE_SCALE),
        )
        self._apply_zoom()

    # ────────────────────────────────────────────── other toolbar actions

    def _rotate(self, e=None) -> None:
        with self._doc_lock:
            p = self.doc[self.current_page]
            p.set_rotation((p.rotation + 90) % 360)
        self._ocr_by_page.pop(self.current_page, None)
        saved = self.current_page
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        try:
            self.viewer_scroll.scroll_to(
                offset=self._page_cum_offsets[saved],
                duration=0,
            )
        except Exception:
            pass
        self.page_ref.update()

    def _save(self, e=None) -> None:
        self._save_picker.save_file(
            dialog_title="Guardar PDF con anotaciones",
            file_name=self.filename,
            allowed_extensions=["pdf"],
        )

    def _on_save_result(self, e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        try:
            with self._doc_lock:
                self.doc.save(e.path, garbage=4, deflate=True)
            self._show_snack(f"Guardado: {Path(e.path).name}")
        except Exception as ex:
            self._show_snack(f"Error al guardar: {ex}")

    # ────────────────────────────────────────────── undo

    def _undo(self, e=None) -> None:
        with self._doc_lock:
            pn = self._annot.undo_last(self.doc)
        if pn is not None:
            self._refresh_page(pn)
        else:
            self._show_snack("Nada que deshacer")

    # ────────────────────────────────────────────── annotation tool selection

    def _select_tool(self, tool: Tool, cursor: ft.MouseCursor) -> None:
        self._annot.set_tool(tool)
        self._current_cursor = cursor
        for gd in self._page_gestures:
            gd.mouse_cursor = cursor
            gd.update()
        for t, btn in self._tool_btns.items():
            btn.bgcolor = _SELECTED_BG if t == tool else None
            btn.update()

    def _set_highlight_color(self, rgb: tuple[float, float, float]) -> None:
        self._annot.highlight_color = rgb
        self._select_tool(Tool.HIGHLIGHT, ft.MouseCursor.PRECISE)
        self._show_snack("Color de resaltado actualizado")

    # ────────────────────────────────────────────── OCR

    @staticmethod
    def _doc_kind_label(kind: str) -> str:
        return {"native": "Texto nativo", "scanned": "Escaneado", "hybrid": "Híbrido"}.get(kind, kind)

    def _refresh_ocr_ui_for_page(self) -> None:
        result = self._ocr_by_page.get(self.current_page)
        pn = self.current_page

        if result is None:
            self._ocr_info.value  = f"OCR página {pn + 1}: sin ejecutar"
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

    def _run_ocr(self, e=None) -> None:
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
        self._ocr_active_index = 0
        self._refresh_ocr_ui_for_page()
        self._show_snack("OCR ejecutado")
        self.page_ref.update()

    def _toggle_ocr_boxes(self, e=None) -> None:
        pn = self.current_page
        if pn not in self._ocr_by_page:
            self._show_snack("Primero ejecuta OCR en esta página")
            return
        self._ocr_show_boxes = not self._ocr_show_boxes
        self._render_ocr_boxes()
        self.page_ref.update()

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

    def _render_ocr_boxes(self) -> None:
        pn = self.current_page
        if pn >= len(self._ocr_overlays):
            return
        ocr_ov = self._ocr_overlays[pn]
        result = self._ocr_by_page.get(pn)
        if result is None or not self._ocr_show_boxes:
            ocr_ov.visible  = False
            ocr_ov.controls = []
            return

        scale = self.zoom * BASE_SCALE
        boxes: list[ft.Control] = []
        for det in result.detections:
            r = det.bbox
            boxes.append(
                ft.Container(
                    left=r.x0 * scale,
                    top=r.y0 * scale,
                    width=max(2, r.width  * scale),
                    height=max(2, r.height * scale),
                    bgcolor=_OCR_BOX_BG,
                    border=ft.border.all(2, _OCR_BOX_CLR),
                    tooltip=f"OCR ({det.score:.2f}): {det.text[:120]}",
                )
            )
        ocr_ov.controls = boxes
        ocr_ov.visible  = True

    # ────────────────────────────────────────────── annotation selection

    def _select_annot(self, pn: int, annot: fitz.Annot) -> None:
        # Hide overlay on previously-selected page if different
        if self._selected is not None and self._selected[0] != pn:
            old_pn = self._selected[0]
            if old_pn < len(self._sel_overlays):
                self._sel_overlays[old_pn].visible = False
                try:
                    self._sel_overlays[old_pn].update()
                except Exception:
                    pass

        self._selected = (pn, annot.xref)
        annot_name = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else "Anotación"
        self._sel_label.value = f"{annot_name} seleccionada — arrastra para mover"

        scale  = self.zoom * BASE_SCALE
        r      = annot.rect
        sel_ov = self._sel_overlays[pn]
        sel_ov.left   = r.x0    * scale
        sel_ov.top    = r.y0    * scale
        sel_ov.width  = r.width  * scale
        sel_ov.height = r.height * scale
        sel_ov.visible = True
        self._annot_action_bar.visible = True
        try:
            sel_ov.update()
            self._annot_action_bar.update()
        except Exception:
            pass

    def _get_selected_annot(self) -> fitz.Annot | None:
        if self._selected is None:
            return None
        pn, xref = self._selected
        with self._doc_lock:
            page = self.doc[pn]
            for annot in page.annots():
                if annot.xref == xref:
                    return annot
        return None

    def _refresh_selected_overlay(self, pn: int) -> None:
        annot = self._get_selected_annot()
        if annot is None:
            self._deselect_annot()
            return
        scale  = self.zoom * BASE_SCALE
        r      = annot.rect
        sel_ov = self._sel_overlays[pn]
        sel_ov.left   = r.x0    * scale
        sel_ov.top    = r.y0    * scale
        sel_ov.width  = max(2, r.width  * scale)
        sel_ov.height = max(2, r.height * scale)
        sel_ov.visible = True
        try:
            sel_ov.update()
        except Exception:
            pass

    def _deselect_annot(self, e=None) -> None:
        if self._selected is None:
            return
        pn = self._selected[0]
        self._selected = None
        if pn < len(self._sel_overlays):
            self._sel_overlays[pn].visible = False
            try:
                self._sel_overlays[pn].update()
            except Exception:
                pass
        self._annot_action_bar.visible = False
        try:
            self._annot_action_bar.update()
        except Exception:
            pass
        self._sel_label.value = "Anotación seleccionada"

    def _delete_selected(self, e=None) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected
        with self._doc_lock:
            deleted = self._annot.delete_annot(self.doc, pn, xref)
        self._selected = None
        if deleted:
            self._refresh_page(pn)
        else:
            self._show_snack("No se pudo eliminar la anotación")

    def _scale_selected(self, factor: float) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected
        with self._doc_lock:
            result = self._annot.scale_annot(self.doc, pn, xref, factor)
        if result:
            self._refresh_page(pn)
        else:
            self._show_snack("No se pudo ajustar el tamaño")

    def _scale_down_selected(self, e=None) -> None:
        self._scale_selected(0.85)

    def _scale_up_selected(self, e=None) -> None:
        self._scale_selected(1.15)

    def _recolor_selected_menu(self, e=None) -> None:
        if self._selected is None:
            return
        pn, xref = self._selected

        dlg = ft.AlertDialog(title=ft.Text("Cambiar color de anotación"))

        def pick(rgb: tuple[float, float, float]) -> None:
            dlg.open = False
            self.page_ref.update()
            with self._doc_lock:
                self._annot.change_annot_color(self.doc, pn, xref, rgb)
            self._selected = None
            self._refresh_page(pn)

        def cancel(ev) -> None:
            dlg.open = False
            self.page_ref.update()

        dlg.content = ft.Column(
            [
                ft.TextButton(
                    content=ft.Row(
                        [
                            ft.Container(bgcolor=_rgb_to_hex(r, g, b), width=22, height=22, border_radius=4),
                            ft.Text(name, size=14),
                        ],
                        spacing=10,
                    ),
                    on_click=lambda ev, c=rgb: pick(c),
                )
                for name, rgb in HIGHLIGHT_COLORS
                for r, g, b in [rgb]
            ],
            tight=True, spacing=2,
        )
        dlg.actions = [ft.TextButton("Cancelar", on_click=cancel)]
        self.page_ref.dialog = dlg
        dlg.open = True
        self.page_ref.update()

    # ────────────────────────────────────────────── text selection dialog

    def _show_text_actions(self, text: str, pn: int) -> None:
        preview = text[:100] + ("…" if len(text) > 100 else "")
        dlg = ft.AlertDialog(title=ft.Text("Texto seleccionado"))

        def close(ev=None) -> None:
            dlg.open = False
            self.page_ref.update()

        def copy_text(ev) -> None:
            close()
            self.page_ref.set_clipboard(text)
            short = text[:60] + ("…" if len(text) > 60 else "")
            self._show_snack(f"Copiado: \"{short}\"")

        def apply_tool(tool: Tool) -> None:
            close()
            with self._doc_lock:
                changed = self._annot.apply_text_tool(self.doc, pn, tool)
            if changed:
                self._refresh_page(pn)

        dlg.content = ft.Column([ft.Text(preview, size=13, selectable=True)], tight=True)
        dlg.actions = [
            ft.TextButton("Copiar",    icon=ft.Icons.CONTENT_COPY,        on_click=copy_text),
            ft.TextButton("Resaltar",  icon=ft.Icons.HIGHLIGHT,           on_click=lambda ev: apply_tool(Tool.HIGHLIGHT)),
            ft.TextButton("Subrayar",  icon=ft.Icons.FORMAT_UNDERLINE,    on_click=lambda ev: apply_tool(Tool.UNDERLINE)),
            ft.TextButton("Tachar",    icon=ft.Icons.FORMAT_STRIKETHROUGH, on_click=lambda ev: apply_tool(Tool.STRIKEOUT)),
            ft.TextButton("Cerrar", on_click=close),
        ]
        self.page_ref.dialog = dlg
        dlg.open = True
        self.page_ref.update()

    # ────────────────────────────────────────────── gesture handlers

    def _on_tap_down(self, e: ft.TapEvent, pn: int) -> None:
        self._pending_tap      = (e.local_x, e.local_y)
        self._pending_tap_page = pn

    def _on_tap(self, e, pn: int) -> None:
        if self._annot.tool != Tool.CURSOR or self._pending_tap is None or self._pending_tap_page != pn:
            self._pending_tap      = None
            self._pending_tap_page = None
            return
        x, y = self._pending_tap
        self._pending_tap      = None
        self._pending_tap_page = None
        pdf_x, pdf_y = display_to_pdf(x, y, self.zoom)
        with self._doc_lock:
            page  = self.doc[pn]
            annot = self._annot.get_annot_at(page, pdf_x, pdf_y)
        if annot:
            self.current_page = pn
            self._select_annot(pn, annot)
        else:
            self._deselect_annot()

    def _on_pan_start(self, e: ft.DragStartEvent, pn: int) -> None:
        self._pending_tap      = None
        self._pending_tap_page = None

        if self._annot.tool == Tool.CURSOR:
            if self._selected is None or self._selected[0] != pn:
                return
            pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
            annot = self._get_selected_annot()
            if annot is None:
                self._deselect_annot()
                return
            hit = fitz.Rect(annot.rect)
            hit.x0 -= 3; hit.y0 -= 3; hit.x1 += 3; hit.y1 += 3
            if hit.contains(fitz.Point(pdf_x, pdf_y)):
                self._moving_selected = True
                self._move_last_pdf   = (pdf_x, pdf_y)
            return

        self.current_page = pn
        pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
        self._annot.begin(pdf_x, pdf_y)

    def _on_pan_update(self, e: ft.DragUpdateEvent, pn: int) -> None:
        if self._annot.tool == Tool.CURSOR:
            if not self._moving_selected or self._move_last_pdf is None or self._selected is None:
                return
            if self._selected[0] != pn:
                return
            pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
            last_x, last_y = self._move_last_pdf
            dx = pdf_x - last_x
            dy = pdf_y - last_y
            if math.isclose(dx, 0.0, abs_tol=0.01) and math.isclose(dy, 0.0, abs_tol=0.01):
                return
            with self._doc_lock:
                moved = self._annot.move_annot(self.doc, pn, self._selected[1], dx, dy)
            if moved:
                self._move_last_pdf = (pdf_x, pdf_y)
                self._refresh_selected_overlay(pn)
            return

        pdf_x, pdf_y = display_to_pdf(e.local_x, e.local_y, self.zoom)
        pdf_rect = self._annot.move(pdf_x, pdf_y)
        if pdf_rect is None:
            return
        scale  = self.zoom * BASE_SCALE
        dov    = self._drag_overlays[pn]
        dov.left    = pdf_rect.x0     * scale
        dov.top     = pdf_rect.y0     * scale
        dov.width   = pdf_rect.width  * scale
        dov.height  = pdf_rect.height * scale
        dov.bgcolor = self._annot.overlay_color
        dov.visible = True
        try:
            dov.update()
        except Exception:
            pass

    def _on_pan_end(self, e: ft.DragEndEvent, pn: int) -> None:
        if self._annot.tool == Tool.CURSOR:
            if self._moving_selected:
                self._moving_selected = False
                self._move_last_pdf   = None
                self._refresh_page(pn)
            return

        dov = self._drag_overlays[pn]
        dov.visible = False
        try:
            dov.update()
        except Exception:
            pass

        with self._doc_lock:
            modified, text = self._annot.commit(self.doc, pn)
        if modified:
            self._refresh_page(pn)
        elif text:
            self._show_text_actions(text, pn)

    # ────────────────────────────────────────────── tab / lifecycle

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.PICTURE_AS_PDF, size=16, color=ft.Colors.RED_400),
                        ft.Text(
                            self.filename, size=13,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
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
        self.doc.close()
        try:
            self.page_ref.overlay.remove(self._save_picker)
            self.page_ref.update()
        except ValueError:
            pass
