"""PDFViewerTab: full-featured PDF viewer — continuous scroll, lazy rendering.

Behaviour is split across focused mixin modules:
  _render_mixin.py      — page rendering, navigation, zoom, save
  _gesture_mixin.py     — pan / tap event routing
  _annot_mixin.py       — annotation selection and editing
  _text_sel_mixin.py    — word-level text selection overlay
  _ocr_mixin.py         — OCR execution and results panel
  _redact_agent_mixin.py — redaction search/apply and AI-agent chat
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import flet as ft
import fitz

from .annotations import AnnotationManager, HIGHLIGHT_COLORS, Tool
from .ocr import OCRPageResult, OCRProcessor
from .renderer import BASE_SCALE, ZOOM_LEVELS, display_to_pdf, render_page

from ._viewer_defs import (
    _TOOL_DEFS,
    _TOOLBAR_BG, _ANNOT_BG, _DIVIDER_CLR, _VIEWER_BG,
    _SEL_BAR_BG, _SEL_BAR_BDR, _OCR_PANEL_BG,
    _SELECTED_BG, _vdivider,
)
from ._render_mixin       import _RenderMixin
from ._gesture_mixin      import _GestureMixin
from ._annot_mixin        import _AnnotMixin
from ._text_sel_mixin     import _TextSelMixin
from ._ocr_mixin          import _OCRMixin
from ._redact_agent_mixin import _RedactAgentMixin


class PDFViewerTab(
    _RenderMixin,
    _GestureMixin,
    _AnnotMixin,
    _TextSelMixin,
    _OCRMixin,
    _RedactAgentMixin,
):
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

        # Night-mode state
        self._night_mode      = False
        self._viewer_body:    ft.Container | None = None
        self._night_mode_btn: ft.IconButton | None = None

        self._tab       = None
        self._annot     = AnnotationManager(on_modified=self._update)
        self._tool_btns: dict[Tool, ft.IconButton] = {}

        # Annotation selection state (page_num, xref)
        self._selected:         tuple[int, int] | None = None
        self._pending_tap:      tuple[float, float] | None = None
        self._pending_tap_page: int | None = None
        self._moving_selected   = False
        self._move_last_pdf:    tuple[float, float] | None = None

        # Triple-tap tracking (paragraph selection on SELECT tool)
        self._tap_count:     int        = 0
        self._last_tap_time: float      = 0.0
        self._last_tap_pos:  tuple      = (0.0, 0.0)
        self._last_tap_pn:   int | None = None

        # Per-page render controls
        self._page_images:      list[ft.Image]     = []
        self._drag_overlays:    list[ft.Container] = []
        self._sel_overlays:     list[ft.Container] = []
        self._ocr_overlays:     list[ft.Stack]     = []
        self._text_sel_layers:  list[ft.Stack]     = []
        self._redact_overlays:  list[ft.Stack]     = []
        self._page_slots:       list[ft.Container] = []
        self._page_gestures:    list[ft.GestureDetector] = []
        self._page_cum_offsets: list[float] = []
        self._page_heights:     list[float] = []
        self._rendered:         set[int]    = set()

        # Background rendering / eviction
        self._doc_lock       = threading.Lock()
        self._rendering:     set[int] = set()
        self._render_gen     = 0
        self._last_evict_px  = -9999.0

        # Text selection state
        self._page_words:         dict[int, list[tuple]] = {}
        self._text_sel_pn:        int | None = None
        self._text_sel_text:      str = ""
        self._text_sel_start_pdf: tuple | None = None
        self._text_sel_end_pdf:   tuple | None = None
        self._text_sel_sel_rect                = None
        self._text_sel_popups:    list[ft.Container] = []
        self._scroll_px:          float = 0.0

        # OCR state
        self._ocr_processor    = OCRProcessor(str(Path(__file__).resolve().parents[2]))
        self._ocr_by_page:     dict[int, OCRPageResult] = {}
        self._ocr_show_boxes   = False
        self._ocr_active_index = 0
        self._ocr_toggle_btn:  ft.IconButton | None = None
        self._ocr_panel_open   = False

        # OCR panel UI refs (set by _build_ocr_sidebar_panel)
        self._ocr_info:         ft.Text       | None = None
        self._ocr_source:       ft.Text       | None = None
        self._ocr_doc_kind:     ft.Text       | None = None
        self._ocr_time:         ft.Text       | None = None
        self._ocr_count:        ft.Text       | None = None
        self._ocr_results_list: ft.ListView   | None = None
        self._ocr_collapse_btn: ft.IconButton | None = None
        self._ocr_content_area: ft.Container  | None = None
        self._ocr_panel:        ft.Container  | None = None

        # Annotation popup state (floating menu for text-markup annotations)
        self._annot_popups:    list[ft.Container] = []
        self._annot_popup_pn:  int | None = None

        # Redaction state
        self._redact_panel_open     = False
        self._redact_overlays:   list[ft.Stack] = []
        self._redact_matches:    list[tuple[int, fitz.Rect, str]] = []
        self._redact_terms:      list[str] = []
        self._redact_term_matches: dict[str, list] = {}
        self._redact_preview        = False
        self._redact_case_sensitive = True
        self._redact_box_color      = "#000000"

        # Redaction panel UI refs (set by _build_redact_sidebar_panel)
        self._redact_panel:        ft.Container | None = None
        self._redact_content_area: ft.Container | None = None
        self._redact_collapse_btn: ft.IconButton | None = None
        self._redact_query_field:  ft.TextField  | None = None
        self._redact_terms_list:   ft.ListView   | None = None
        self._redact_count_text:   ft.Text       | None = None
        self._redact_incl_ocr:     ft.Switch     | None = None
        self._redact_case_btn:     ft.IconButton | None = None
        self._redact_preview_btn:  ft.IconButton | None = None
        self._redact_color_btns:   dict          = {}

        # Sidebar visibility
        self._sidebar_visible = True
        self._sidebar_btn:    ft.IconButton | None = None
        self._right_sidebar:  ft.Container | None = None

        # Sidebar mode: "ocr" | "redact" | "agent"
        self._sidebar_mode             = "ocr"
        self._sidebar_ocr_view:        ft.Container | None = None
        self._sidebar_redact_view:     ft.Container | None = None
        self._sidebar_agent_view:      ft.Container | None = None
        self._sidebar_tab_ocr_btn:     ft.Container | None = None
        self._sidebar_tab_redact_btn:  ft.Container | None = None
        self._sidebar_tab_agent_btn:   ft.Container | None = None

        # Agent panel state
        self._agent_panel_open    = True
        self._agent_toolbar_btn:  ft.IconButton | None = None
        self._agent_panel:        ft.Container  | None = None
        self._agent_content_area: ft.Container  | None = None
        self._agent_collapse_btn: ft.IconButton | None = None
        self._agent_chat_list:    ft.ListView   | None = None
        self._agent_input:        ft.TextField  | None = None
        self._agent_key_field:    ft.TextField  | None = None
        self._agent_history:      list[dict]    = []
        self._agent_instance                    = None
        self._agent_running       = False

        self._save_picker = ft.FilePicker(on_result=self._on_save_result)
        page_ref.overlay.append(self._save_picker)

        self._build()

    # ── UI assembly ───────────────────────────────────────────────────────────

    def _build(self) -> None:
        total = len(self.doc)

        # ── navigation toolbar ────────────────────────────────────────────────
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
        self.zoom_out_btn = ft.IconButton(ft.Icons.REMOVE, tooltip="Alejar",   on_click=self._zoom_out)
        self.zoom_label   = ft.Text("100%", width=52, text_align=ft.TextAlign.CENTER, size=14)
        self.zoom_in_btn  = ft.IconButton(ft.Icons.ADD,    tooltip="Acercar",  on_click=self._zoom_in)

        zoom_menu = ft.PopupMenuButton(
            icon=ft.Icons.ARROW_DROP_DOWN,
            tooltip="Nivel de zoom",
            items=[
                ft.PopupMenuItem(text="Ajustar al ancho",    on_click=self._fit_width),
                ft.PopupMenuItem(text="Ajustar a la página", on_click=self._fit_page),
                ft.PopupMenuItem(),
                *[
                    ft.PopupMenuItem(text=f"{int(z * 100)}%",
                                     on_click=lambda e, _z=z: self._set_zoom(_z))
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
                    ft.IconButton(ft.Icons.ROTATE_RIGHT, tooltip="Rotar 90°", on_click=self._rotate),
                    _vdivider(),
                    ft.IconButton(ft.Icons.UNDO,         tooltip="Deshacer última anotación  (Ctrl+Z)", on_click=self._undo),
                    _vdivider(),
                    ft.IconButton(ft.Icons.SAVE_ALT,     tooltip="Guardar PDF con anotaciones", on_click=self._save),
                    _vdivider(),
                    ft.IconButton(ft.Icons.DOCUMENT_SCANNER, tooltip="Ejecutar OCR en la página actual", on_click=self._run_ocr),
                    self._make_ocr_toggle_btn(),
                    _vdivider(),
                    self._make_agent_toolbar_btn(),
                    _vdivider(),
                    self._make_sidebar_toggle_btn(),
                    _vdivider(),
                    self._make_night_mode_btn(),
                    ft.PopupMenuButton(
                        icon=ft.Icons.MORE_VERT,
                        tooltip="Más opciones",
                        items=[
                            ft.PopupMenuItem(
                                text="Guardar PDF",
                                icon=ft.Icons.SAVE_ALT,
                                on_click=self._save,
                            ),
                            ft.PopupMenuItem(
                                text="Cerrar pestaña",
                                icon=ft.Icons.CLOSE,
                                on_click=lambda e: self.on_close(self),
                            ),
                            ft.PopupMenuItem(),
                            ft.PopupMenuItem(
                                text="Ajustar al ancho",
                                icon=ft.Icons.FIT_SCREEN,
                                on_click=self._fit_width,
                            ),
                            ft.PopupMenuItem(
                                text="Ajustar a la página",
                                icon=ft.Icons.FULLSCREEN_OUTLINED,
                                on_click=self._fit_page,
                            ),
                            ft.PopupMenuItem(
                                text="Tamaño real (100%)",
                                icon=ft.Icons.CROP_FREE,
                                on_click=lambda e: self._set_zoom(1.0),
                            ),
                        ],
                    ),
                ],
                spacing=2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            bgcolor=_TOOLBAR_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _DIVIDER_CLR)),
        )

        # ── annotation toolbar ────────────────────────────────────────────────
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
            ft.Row([*tool_btns, _vdivider(), color_menu],
                   spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=8, vertical=2),
            bgcolor=_ANNOT_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _DIVIDER_CLR)),
        )

        # ── annotation selection action bar ───────────────────────────────────
        self._sel_label = ft.Text("Anotación seleccionada", size=12, color="#555555")
        self._annot_action_bar = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.TOUCH_APP, size=16, color="#888888"),
                    self._sel_label,
                    ft.TextButton("Eliminar",      icon=ft.Icons.DELETE_OUTLINE,
                                  icon_color=ft.Colors.RED_600, on_click=self._delete_selected),
                    ft.TextButton("Cambiar color", icon=ft.Icons.PALETTE_OUTLINED,
                                  on_click=self._recolor_selected_menu),
                    ft.TextButton("Reducir",       icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                                  on_click=self._scale_down_selected),
                    ft.TextButton("Agrandar",      icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                  on_click=self._scale_up_selected),
                    ft.TextButton("Deseleccionar", icon=ft.Icons.CLOSE,
                                  on_click=self._deselect_annot),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            bgcolor=_SEL_BAR_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _SEL_BAR_BDR)),
            visible=False,
        )

        # ── sidebar panels (each mixin builds its own) ────────────────────────
        ocr_panel    = self._build_ocr_sidebar_panel()
        redact_panel = self._build_redact_sidebar_panel()
        agent_panel  = self._build_agent_sidebar_panel()

        # ── sidebar mode tab bar (3 tabs) ─────────────────────────────────────
        _TAB_DEFS = [
            ("ocr",    ft.Icons.TEXT_SNIPPET_OUTLINED, "OCR",       "#2E7D32", "#E8F5E9"),
            ("redact", ft.Icons.EDIT_OFF_OUTLINED,     "Redacción", "#E65100", "#FFF3E0"),
            ("agent",  ft.Icons.SMART_TOY_OUTLINED,    "Agente IA", "#5C35C9", "#EDE7F6"),
        ]

        def _make_tab_btn(mode: str, icon: str, label: str,
                          active_color: str, active_bg: str) -> ft.Container:
            is_active = (self._sidebar_mode == mode)
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(icon, size=16,
                                color=active_color if is_active else "#9E9E9E"),
                        ft.Text(label, size=10,
                                weight=ft.FontWeight.W_600,
                                color=active_color if is_active else "#9E9E9E",
                                text_align=ft.TextAlign.CENTER),
                    ],
                    spacing=2, tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=6, vertical=8),
                expand=True,
                bgcolor=active_bg if is_active else None,
                border=ft.border.only(
                    bottom=ft.BorderSide(2, active_color if is_active else "#E0E0E0")
                ),
                on_click=lambda e, m=mode: self._switch_sidebar_mode(m),
                ink=True,
                tooltip=label,
            )

        self._sidebar_tab_ocr_btn    = _make_tab_btn(*_TAB_DEFS[0])
        self._sidebar_tab_redact_btn = _make_tab_btn(*_TAB_DEFS[1])
        self._sidebar_tab_agent_btn  = _make_tab_btn(*_TAB_DEFS[2])

        tab_bar = ft.Container(
            content=ft.Row(
                [self._sidebar_tab_ocr_btn,
                 self._sidebar_tab_redact_btn,
                 self._sidebar_tab_agent_btn],
                spacing=0,
            ),
            bgcolor=_OCR_PANEL_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, "#CCCCCC")),
        )

        # ── three sidebar views (one visible at a time) ───────────────────────
        self._sidebar_ocr_view = ft.Container(
            content=ocr_panel,
            expand=(self._sidebar_mode == "ocr"),
            visible=(self._sidebar_mode == "ocr"),
        )
        self._sidebar_redact_view = ft.Container(
            content=redact_panel,
            expand=(self._sidebar_mode == "redact"),
            visible=(self._sidebar_mode == "redact"),
        )
        self._sidebar_agent_view = ft.Container(
            content=agent_panel,
            expand=(self._sidebar_mode == "agent"),
            visible=(self._sidebar_mode == "agent"),
        )

        self._right_sidebar = ft.Container(
            content=ft.Column(
                [tab_bar,
                 self._sidebar_ocr_view,
                 self._sidebar_redact_view,
                 self._sidebar_agent_view],
                spacing=0, expand=True,
            ),
            width=360,
            bgcolor=_OCR_PANEL_BG,
            border=ft.border.only(left=ft.BorderSide(1, "#D5E6D8")),
        )

        # ── scroll area ───────────────────────────────────────────────────────
        self.viewer_scroll = ft.Column(
            controls=[],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            on_scroll=self._on_view_scroll,
            spacing=16,
        )
        self._rebuild_scroll_content(scroll_back=False)

        viewer_body = ft.Container(
            self.viewer_scroll,
            expand=True,
            bgcolor=_VIEWER_BG,
            padding=20,
        )
        self._viewer_body = viewer_body
        main_content = ft.Row([viewer_body, self._right_sidebar], expand=True, spacing=0)

        self.view = ft.Column(
            [nav_toolbar, annot_toolbar, self._annot_action_bar, main_content],
            expand=True,
            spacing=0,
        )

    # ── tab / lifecycle ───────────────────────────────────────────────────────

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.PICTURE_AS_PDF, size=16, color=ft.Colors.RED_400),
                        ft.Text(self.filename, size=13, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
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

    # ── sidebar mode switching ────────────────────────────────────────────────

    def _switch_sidebar_mode(self, mode: str) -> None:
        """Switch sidebar between 'ocr', 'redact' and 'agent' views."""
        self._sidebar_mode = mode

        _TAB_META = {
            "ocr":    ("#2E7D32", "#E8F5E9", "_sidebar_tab_ocr_btn",    "_sidebar_ocr_view"),
            "redact": ("#E65100", "#FFF3E0", "_sidebar_tab_redact_btn", "_sidebar_redact_view"),
            "agent":  ("#5C35C9", "#EDE7F6", "_sidebar_tab_agent_btn",  "_sidebar_agent_view"),
        }

        for m, (active_color, active_bg, tab_attr, view_attr) in _TAB_META.items():
            is_active = (m == mode)

            # Show/hide view
            view: ft.Container | None = getattr(self, view_attr, None)
            if view is not None:
                view.visible = is_active
                view.expand  = is_active

            # Update tab button appearance
            btn: ft.Container | None = getattr(self, tab_attr, None)
            if btn is not None:
                col = btn.content
                if isinstance(col, ft.Column):
                    for ctrl in col.controls:
                        if isinstance(ctrl, ft.Icon):
                            ctrl.color = active_color if is_active else "#9E9E9E"
                        elif isinstance(ctrl, ft.Text):
                            ctrl.color = active_color if is_active else "#9E9E9E"
                btn.bgcolor = active_bg if is_active else None
                btn.border  = ft.border.only(
                    bottom=ft.BorderSide(2, active_color if is_active else "#E0E0E0")
                )

        # Toolbar agent button highlight
        if self._agent_toolbar_btn is not None:
            is_agent = (mode == "agent")
            self._agent_toolbar_btn.icon_color = "#5C35C9" if is_agent else None
            self._agent_toolbar_btn.bgcolor    = "#EDE7F6" if is_agent else None
            try:
                self._agent_toolbar_btn.update()
            except Exception:
                pass

        # Ensure sidebar is visible
        if not self._sidebar_visible:
            self._toggle_sidebar()

        try:
            self._right_sidebar.update()
        except Exception:
            pass

    # ── agent toolbar button ──────────────────────────────────────────────────

    def _make_agent_toolbar_btn(self) -> ft.IconButton:
        _is_agent = (self._sidebar_mode == "agent")
        self._agent_toolbar_btn = ft.IconButton(
            ft.Icons.SMART_TOY_OUTLINED,
            tooltip="Agente IA — abrir panel del agente",
            icon_color="#5C35C9" if _is_agent else None,
            bgcolor="#EDE7F6" if _is_agent else None,
            on_click=lambda e: self._switch_sidebar_mode("agent"),
        )
        return self._agent_toolbar_btn

    # ── night mode ────────────────────────────────────────────────────────────

    def _make_night_mode_btn(self) -> ft.IconButton:
        self._night_mode_btn = ft.IconButton(
            ft.Icons.DARK_MODE,
            tooltip="Modo nocturno",
            on_click=self._toggle_night_mode,
        )
        return self._night_mode_btn

    def _toggle_night_mode(self, e=None) -> None:
        self._night_mode = not self._night_mode
        if self._night_mode_btn:
            self._night_mode_btn.icon    = ft.Icons.LIGHT_MODE if self._night_mode else ft.Icons.DARK_MODE
            self._night_mode_btn.tooltip = "Desactivar modo nocturno" if self._night_mode else "Modo nocturno"
        _color = "#FFFFFFFF" if self._night_mode else None
        _blend = ft.BlendMode.DIFFERENCE if self._night_mode else None
        for img in self._page_images:
            img.color            = _color
            img.color_blend_mode = _blend
        if self._viewer_body:
            self._viewer_body.bgcolor = "#1E1E1E" if self._night_mode else _VIEWER_BG
        try:
            self.page_ref.update()
        except Exception:
            pass

    # ── select all text on current page (Ctrl+A) ─────────────────────────────

    def _select_all_page_text(self) -> None:
        pn    = self.current_page
        words = self._get_page_words(pn)
        if not words:
            self._show_snack("No hay texto en esta página")
            return
        start_pt = (
            (words[0][0].x0 + words[0][0].x1) / 2,
            (words[0][0].y0 + words[0][0].y1) / 2,
        )
        end_pt = (
            (words[-1][0].x0 + words[-1][0].x1) / 2,
            (words[-1][0].y0 + words[-1][0].y1) / 2,
        )
        sel_text = self._update_text_selection(pn, start_pt, end_pt, update_ui=True)
        if sel_text:
            self._show_text_sel_bar(sel_text)
