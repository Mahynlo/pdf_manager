"""PDFViewerTab: full-featured PDF viewer — continuous scroll, lazy rendering.

Behaviour is split across focused mixin modules:
  _render_mixin.py   — page rendering, navigation, zoom, save
  _gesture_mixin.py  — pan / tap event routing
  _annot_mixin.py    — annotation selection and editing
  _text_sel_mixin.py — word-level text selection overlay
  _ocr_mixin.py      — OCR execution and results panel
  _redact_mixin.py   — redaction search, term management, preview, apply
  _profiles_mixin.py — censorship profile dialogs (create, edit, load)
  _agent_mixin.py    — AI document-analysis agent panel and chat

Escala a documentos de cientos de páginas porque el árbol de controles por
página está **virtualizado**: cada página arranca como un placeholder liviano y
su árbol pesado se construye/desinfla on-demand según la ventana visible (ver
el docstring de ``_render_mixin`` para el modelo y la invariante de None). Al
cambiar de pestaña, ``on_focus`` restaura la posición de scroll donde estaba el
usuario (``_restore_scroll_position``), ya que re-mostrar el tab reinicia el
offset del Column en Flutter. La gestión de RAM en dos pasos (shrink en
``on_blur`` + clear total en ``_do_suspend``) mantiene el documento abierto pero
libera cachés cuando el tab pierde foco.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

import flet as ft
import fitz

from .annotations import AnnotationManager, HIGHLIGHT_COLORS, Tool
from .ocr import OCRPageResult, OCRProcessor
from .renderer import BASE_SCALE, ZOOM_LEVELS, display_to_pdf, render_page, PageRenderCache

from ._viewer_defs import (
    _TOOL_DEFS,
    _TOOLBAR_BG, _ANNOT_BG, _DIVIDER_CLR, _VIEWER_BG,
    _OCR_PANEL_BG,
    _SELECTED_BG, _vdivider,
    _AUTO_SINGLE_PAGE_THRESHOLD,
    AGENT_ENABLED,
)
from ._render_mixin   import _RenderMixin
from ._gesture_mixin  import _GestureMixin
from ._annot_mixin    import _AnnotMixin
from ._text_sel_mixin import _TextSelMixin
from ._ocr_mixin      import _OCRMixin
from ._redact_mixin   import _RedactMixin
from ._profiles_mixin import _ProfilesMixin
from ._legends_mixin  import _LegendsMixin
from ._agent_mixin    import _AgentMixin
from ._print_mixin    import _PrintMixin


class PDFViewerTab(
    _RenderMixin,
    _GestureMixin,
    _AnnotMixin,
    _TextSelMixin,
    _OCRMixin,
    _RedactMixin,
    _ProfilesMixin,
    _LegendsMixin,
    _AgentMixin,
    _PrintMixin,
):
    """Manages state and UI for a single open PDF document."""

    def __init__(
        self,
        path: str,
        page_ref: ft.Page,
        on_close: Callable,
        doc: Optional[fitz.Document] = None,
    ):
        self.path     = path
        self.page_ref = page_ref
        self.on_close = on_close
        self.filename = Path(path).name
        self.doc      = doc if doc is not None else fitz.open(path)

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
        # Menú de leyendas (textos guardados) y leyenda pendiente de insertar: al
        # elegir una leyenda se activa la herramienta de texto y el siguiente clic
        # abre el editor relleno con su config (texto + estilo).
        self._legends_menu: ft.PopupMenuButton | None = None
        self._pending_legend: dict | None = None

        # Annotation selection state (page_num, xref)
        self._selected:         tuple[int, int] | None = None
        self._pending_tap:      tuple[float, float] | None = None
        self._pending_tap_page: int | None = None
        # Drag mode: None | "move" | "resize_tl" | "resize_tr" | "resize_bl" | "resize_br"
        self._drag_mode:     str | None = None
        self._move_last_pdf: tuple[float, float] | None = None
        # Cached rects for lock-free dragging (written at pan_start, applied at pan_end)
        self._drag_start_rect:   fitz.Rect | None = None
        self._drag_current_rect: fitz.Rect | None = None
        # Arrastre de "mover" entre páginas: offset puntero→esquina de la caja
        # (espacio pantalla) y página actualmente bajo el puntero. Permiten que la
        # anotación siga al cursor aunque cruce a otra página (la escritura al doc
        # ocurre una vez al soltar).
        self._move_grab_off: tuple[float, float] | None = None
        self._drag_target_pn: int | None = None
        # Current PDF rect of the selected annotation — kept in sync with the
        # document so hit-tests / handle-positioning / pan-start never need to
        # acquire the doc lock (which may be held by a background page render).
        self._selected_rect:     fitz.Rect | None = None
        # Whether the selected annotation currently has PDF_ANNOT_IS_HIDDEN set
        # (flipped on during drag so the old position doesn't show behind the
        # moving ghost).  Always reset at pan_end.
        self._drag_annot_hidden: bool = False
        # Annotation subtype of the current selection (e.g. "Square", "Circle",
        # "Line", "Polygon") — drives overlay border-radius during resize.
        self._selected_atype:    str | None = None
        self._selected_visual_rect: fitz.Rect | None = None
        # Per-page references to inner handle/menu controls inside sel_overlays
        self._sel_handles: list[dict] = []

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
        self._loading_overlays: list[ft.Container] = []
        self._page_slots:       list[ft.Container] = []
        self._page_placeholders: list[ft.Container] = []
        self._page_gestures:    list[ft.GestureDetector] = []
        self._page_cum_offsets: list[float] = []
        self._page_heights:     list[float] = []
        self._rendered:         set[int]    = set()

        # Background rendering / eviction
        self._doc_lock          = threading.Lock()
        self._render_cache      = PageRenderCache()
        self._rendering:        set[int] = set()
        self._pending_rerender: set[int] = set()
        self._render_gen     = 0
        self._last_evict_px  = -9999.0

        # Text selection state
        self._page_words:         dict[int, list[tuple]] = {}
        self._page_word_bands:    dict[int, dict[int, list]] = {}
        self._page_blocks_cache:  dict[int, list] = {}
        # Firma (si, ei, scale, es_inicio, es_fin) del último resaltado dibujado
        # por página: permite saltar el rebuild del overlay durante el arrastre
        # cuando el puntero no cambió de palabra (la mayoría de los eventos).
        self._text_sel_sig:       dict[int, tuple] = {}
        # Páginas cuya capa tiene resaltado dibujado AHORA: limpiar/recorrer
        # sólo éstas (O(selección)) en vez de las N páginas del documento por
        # evento de arrastre.
        self._text_sel_active_pages: set[int] = set()
        self._text_sel_start_pn:  int | None = None
        self._text_sel_end_pn:    int | None = None
        self._text_sel_text:      str = ""
        self._text_sel_start_pdf: tuple | None = None
        self._text_sel_end_pdf:   tuple | None = None
        self._text_sel_sel_rect                = None
        self._text_sel_popups:    list[ft.Container] = []
        self._scroll_px:          float = 0.0
        # Estado de scroll para la navegación por rueda en single/double:
        # extensión scrolleable de la página actual, alto del viewport, instante
        # del último cambio de página (enfriamiento) y rueda acumulada.
        self._scroll_max:          float = 0.0
        self._last_viewport_h:     float = 600.0
        self._single_nav_t:        float = 0.0
        self._single_nav_timer           = None
        self._single_nav_dir:      int   = 1
        self._single_nav_px:       float = 0.0
        # Handle drag state ("start" | "end" | None) and display positions
        self._sel_drag_handle:              str | None   = None
        self._text_sel_handle_start_disp:   tuple | None = None
        self._text_sel_handle_end_disp:     tuple | None = None
        # True while the smart pointer is performing a text-selection drag
        self._smart_text_sel_active: bool = False
        # Cache of text word rects per page (PDF space, invalidated on doc change)
        self._text_rects_cache: dict[int, list] = {}

        # OCR state
        self._ocr_processor    = None
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
        self._redact_preview        = True
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

        # Profile state
        from pdf_viewer._censorship_profiles import CensorshipProfile
        self._active_profile:        CensorshipProfile | None = None
        self._active_profile_label:  ft.Text       | None = None
        self._profile_save_btn:      ft.Container  | None = None
        self._profile_mgr_dlg:       ft.AlertDialog | None = None
        self._profile_edit_dlg:      ft.AlertDialog | None = None
        self._profile_search_field:  ft.TextField  | None = None
        self._profile_list_view:     ft.ListView   | None = None
        self._profile_edit_name:     ft.TextField  | None = None
        self._profile_edit_term_input: ft.TextField | None = None
        self._profile_edit_terms_list: ft.ListView  | None = None
        self._profile_import_btn:    ft.TextButton  | None = None
        self._profile_edit_terms:    list[str]      = []
        self._profile_editing_id:    str | None     = None

        # Sidebar visibility
        self._sidebar_visible = True
        self._sidebar_btn:    ft.IconButton | None = None
        self._right_sidebar:  ft.Container | None = None

        # Sidebar mode: "toc" | "ocr" | "redact" | "agent"
        self._sidebar_mode             = "ocr"
        self._sidebar_toc_view:        ft.Container | None = None
        self._sidebar_ocr_view:        ft.Container | None = None
        self._sidebar_redact_view:     ft.Container | None = None
        self._sidebar_agent_view:      ft.Container | None = None
        self._sidebar_tab_toc_btn:     ft.Container | None = None
        self._sidebar_tab_ocr_btn:     ft.Container | None = None
        self._sidebar_tab_redact_btn:  ft.Container | None = None
        self._sidebar_tab_agent_btn:   ft.Container | None = None

        # Display mode: "continuous" | "single" | "double".
        # Los PDFs largos arrancan en "página única" (más ligero); el usuario
        # puede cambiarlo con los botones de modo de vista.
        self._display_mode = (
            "single" if len(self.doc) > _AUTO_SINGLE_PAGE_THRESHOLD else "continuous"
        )
        self._page_rows:     list  = []
        self._mode_btn_continuous: ft.IconButton | None = None
        self._mode_btn_single:     ft.IconButton | None = None
        self._mode_btn_double:     ft.IconButton | None = None

        # Ink / freehand drawing state
        self._ink_points: list[tuple[float, float]] = []
        self._ink_page:   int | None                = None
        self._ink_canvases: list                    = []

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
        # Agent config extended state
        self._agent_provider_selected: str | None = None
        self._agent_provider_btns:     dict       = {}
        self._agent_key_status:        ft.Text       | None = None
        self._agent_config_section:    ft.Container  | None = None
        self._agent_config_toggle_btn: ft.IconButton | None = None
        self._agent_redact_sensitivity: str               = "medium"
        self._agent_sensitivity_btns:   dict              = {}

        # Ctrl key state — updated from main.py keyboard handler for Ctrl+Scroll zoom
        self._ctrl_pressed: bool = False

        # Lazy-suspension state (cache-only — document stays open)
        self._is_suspended:   bool                    = False
        self._suspend_timer:  threading.Timer | None  = None
        self._restore_scroll_timer: threading.Timer | None = None

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

        self._mode_btn_continuous = ft.IconButton(
            ft.Icons.VIEW_STREAM, tooltip="Scroll continuo",
            on_click=lambda e: self._set_display_mode("continuous"),
        )
        self._mode_btn_single = ft.IconButton(
            ft.Icons.ARTICLE, tooltip="Página única",
            on_click=lambda e: self._set_display_mode("single"),
        )
        self._mode_btn_double = ft.IconButton(
            ft.Icons.BOOK, tooltip="Doble página",
            on_click=lambda e: self._set_display_mode("double"),
        )
        # Resaltar el botón del modo activo (puede no ser "continuous": los PDFs
        # largos arrancan en "página única").
        _active_btn = {
            "continuous": self._mode_btn_continuous,
            "single":     self._mode_btn_single,
            "double":     self._mode_btn_double,
        }.get(self._display_mode)
        if _active_btn is not None:
            _active_btn.icon_color = "#1565C0"
            _active_btn.bgcolor    = ft.Colors.with_opacity(0.20, ft.Colors.PRIMARY)

        zoom_menu = ft.PopupMenuButton(
            icon=ft.Icons.ARROW_DROP_DOWN,
            tooltip="Nivel de zoom",
            items=[
                ft.PopupMenuItem(text="Ajustar al ancho   (Ctrl+W)",  on_click=self._fit_width),
                ft.PopupMenuItem(text="Ajustar a la página (Ctrl+F)", on_click=self._fit_page),
                ft.PopupMenuItem(),
                *[
                    ft.PopupMenuItem(text=f"{int(z * 100)}%",
                                     on_click=lambda e, _z=z: self._set_zoom(_z))
                    for z in ZOOM_LEVELS
                ],
            ],
        )

        # ── modo de vista como grupo segmentado (centro) ─────────────────────
        view_mode_group = ft.Container(
            ft.Row(
                [self._mode_btn_continuous, self._mode_btn_single, self._mode_btn_double],
                spacing=2, tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="surfaceVariant",
            border_radius=8,
            padding=ft.padding.all(2),
        )

        # ── menú de desbordamiento (acciones poco frecuentes) ────────────────
        more_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Más opciones",
            items=[
                ft.PopupMenuItem(
                    text="Guardar PDF",
                    icon=ft.Icons.SAVE_ALT,
                    on_click=self._save,
                ),
                ft.PopupMenuItem(
                    text="Imprimir documento",
                    icon=ft.Icons.PRINT,
                    on_click=self._print_pdf,
                ),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    text="Rotar 90° a la derecha",
                    icon=ft.Icons.ROTATE_RIGHT,
                    on_click=self._rotate,
                ),
                ft.PopupMenuItem(
                    text="Rotar 90° a la izquierda",
                    icon=ft.Icons.ROTATE_LEFT,
                    on_click=self._rotate_ccw,
                ),
                ft.PopupMenuItem(
                    text="Corregir orientación del escaneo",
                    icon=ft.Icons.SCREEN_ROTATION,
                    on_click=self._fix_orientation,
                ),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    text="Insertar página en blanco",
                    icon=ft.Icons.NOTE_ADD_OUTLINED,
                    on_click=self._insert_blank_page,
                ),
                ft.PopupMenuItem(
                    text="Duplicar página actual",
                    icon=ft.Icons.COPY_ALL_OUTLINED,
                    on_click=self._duplicate_page,
                ),
                ft.PopupMenuItem(
                    text="Eliminar página actual",
                    icon=ft.Icons.DELETE_OUTLINE,
                    on_click=self._delete_page,
                ),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    text="Mover página arriba",
                    icon=ft.Icons.ARROW_UPWARD,
                    on_click=self._move_page_up,
                ),
                ft.PopupMenuItem(
                    text="Mover página abajo",
                    icon=ft.Icons.ARROW_DOWNWARD,
                    on_click=self._move_page_down,
                ),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    text="Cerrar pestaña",
                    icon=ft.Icons.CLOSE,
                    on_click=lambda e: self.on_close(self),
                ),
            ],
        )

        nav_toolbar = ft.Container(
            ft.Row(
                [
                    # ── izquierda · más opciones + navegación + zoom + vista ──
                    more_menu,
                    _vdivider(),
                    self.prev_btn, self.page_input, self.total_label, self.next_btn,
                    _vdivider(),
                    self.zoom_out_btn, self.zoom_label, self.zoom_in_btn, zoom_menu,
                    _vdivider(),
                    view_mode_group,
                    _vdivider(),
                    # ── historial + OCR/IA + apariencia (pegados al grupo) ────
                    ft.IconButton(ft.Icons.UNDO, tooltip="Deshacer última anotación (Ctrl+Z)", on_click=self._undo),
                    ft.IconButton(ft.Icons.REDO, tooltip="Rehacer (Ctrl+Y)", on_click=self._redo),
                    _vdivider(),
                    ft.IconButton(ft.Icons.DOCUMENT_SCANNER, tooltip="Ejecutar OCR en la página actual", on_click=self._run_ocr),
                    self._make_ocr_toggle_btn(),
                    self._make_agent_toolbar_btn(),
                    _vdivider(),
                    self._make_night_mode_btn(),
                    # ── separador flexible · solo el panel queda al extremo ───
                    ft.Container(expand=True),
                    self._make_sidebar_toggle_btn(),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            bgcolor=_TOOLBAR_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _DIVIDER_CLR)),
        )

        # ── annotation toolbar ────────────────────────────────────────────────
        tool_btns: list[ft.Control] = []
        for i, (tool, icon, tooltip, cursor) in enumerate(_TOOL_DEFS):
            if i in (1, 4, 8, 9):  # Grupos: Cursor | Markup | Formas | Tinta | Texto
                tool_btns.append(_vdivider())
            btn = ft.IconButton(
                icon, tooltip=tooltip,
                icon_color="onSurfaceVariant",
                bgcolor=_SELECTED_BG if tool == Tool.CURSOR else None,
                on_click=lambda e, t=tool, c=cursor: self._select_tool(t, c),
            )
            self._tool_btns[tool] = btn
            tool_btns.append(btn)

        color_menu = ft.PopupMenuButton(
            icon=ft.Icons.PALETTE,
            tooltip="Color de anotación",
            items=[
                ft.PopupMenuItem(
                    text=name,
                    on_click=lambda e, c=rgb: self._set_highlight_color(c),
                )
                for name, rgb in HIGHLIGHT_COLORS
            ],
        )
        
        annot_toolbar = ft.Container(
            ft.Row([
                ft.Row(tool_btns, spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                _vdivider(),
                color_menu,
                self._make_legends_menu_btn(),
            ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=8, vertical=2),
            bgcolor=_ANNOT_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _DIVIDER_CLR)),
        )

        # ── sidebar panels (each mixin builds its own) ────────────────────────
        toc_panel    = self._build_toc_sidebar_panel()
        ocr_panel    = self._build_ocr_sidebar_panel()
        redact_panel = self._build_redact_sidebar_panel()
        agent_panel  = self._build_agent_sidebar_panel()

        # ── sidebar mode tab bar (4 tabs) ─────────────────────────────────────
        _TAB_DEFS = [
            ("toc",    ft.Icons.LIST_ALT_OUTLINED,     "Índice",    "#1565C0", ft.Colors.with_opacity(0.15, "#1565C0")),
            ("ocr",    ft.Icons.TEXT_SNIPPET_OUTLINED, "OCR",       "#2E7D32", ft.Colors.with_opacity(0.15, "#2E7D32")),
            ("redact", ft.Icons.EDIT_OFF_OUTLINED,     "Censura",   "#E65100", ft.Colors.with_opacity(0.15, "#E65100")),
            ("agent",  ft.Icons.SMART_TOY_OUTLINED,    "Agente IA", "#5C35C9", ft.Colors.with_opacity(0.15, "#5C35C9")),
        ]

        def _make_tab_btn(mode: str, icon: str, label: str,
                          active_color: str, active_bg: str) -> ft.Container:
            is_active = (self._sidebar_mode == mode)
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(icon, size=16,
                                color=active_color if is_active else "onSurfaceVariant"),
                        ft.Text(label, size=10,
                                weight=ft.FontWeight.W_600,
                                color=active_color if is_active else "onSurfaceVariant",
                                text_align=ft.TextAlign.CENTER),
                    ],
                    spacing=2, tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=6, vertical=8),
                expand=True,
                bgcolor=active_bg if is_active else None,
                border=ft.border.only(
                    bottom=ft.BorderSide(2, active_color if is_active else "outlineVariant")
                ),
                on_click=lambda e, m=mode: self._switch_sidebar_mode(m),
                ink=True,
                tooltip=label,
            )

        self._sidebar_tab_toc_btn    = _make_tab_btn(*_TAB_DEFS[0])
        self._sidebar_tab_ocr_btn    = _make_tab_btn(*_TAB_DEFS[1])
        self._sidebar_tab_redact_btn = _make_tab_btn(*_TAB_DEFS[2])
        self._sidebar_tab_agent_btn  = _make_tab_btn(*_TAB_DEFS[3])
        # Agente oculto mientras está en pulido: sin pestaña no hay forma de
        # abrir su panel (el código del agente queda intacto, ver AGENT_ENABLED).
        self._sidebar_tab_agent_btn.visible = AGENT_ENABLED

        tab_bar = ft.Container(
            content=ft.Row(
                [self._sidebar_tab_toc_btn,
                 self._sidebar_tab_ocr_btn,
                 self._sidebar_tab_redact_btn,
                 self._sidebar_tab_agent_btn],
                spacing=0,
            ),
            bgcolor=_OCR_PANEL_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, "outlineVariant")),
        )

        # ── four sidebar views (one visible at a time) ────────────────────────
        self._sidebar_toc_view = ft.Container(
            content=toc_panel,
            expand=(self._sidebar_mode == "toc"),
            visible=(self._sidebar_mode == "toc"),
        )
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
                 self._sidebar_toc_view,
                 self._sidebar_ocr_view,
                 self._sidebar_redact_view,
                 self._sidebar_agent_view],
                spacing=0, expand=True,
            ),
            width=360,
            bgcolor=_OCR_PANEL_BG,
            border=ft.border.only(left=ft.BorderSide(1, "outlineVariant")),
        )

        # ── scroll area ───────────────────────────────────────────────────────
        # viewer_scroll: Column de scroll vertical con width dinámico.
        # width = max(viewport_w, page_w + 40):
        #   · cuando page_w < viewport_w → Column llena el viewport → las páginas
        #     se centran dentro del Column vía horizontal_alignment=CENTER.
        #   · cuando page_w > viewport_w (zoom alto) → Column desborda el Row →
        #     viewer_hscroll activa el scroll horizontal.
        # NO usar expand=True: Expanded en un ListView (scroll Row) lanza error
        # en Flutter porque el main axis es no-acotado.
        self.viewer_scroll = ft.Column(
            controls=[],
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            on_scroll=self._on_view_scroll,
            spacing=16,
        )
        # viewer_hscroll: Row scrollable horizontal. Cuando viewer_scroll es más
        # ancho que el viewport el usuario puede desplazarse lateralmente.
        self.viewer_hscroll = ft.Row(
            [self.viewer_scroll],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._rebuild_scroll_content(scroll_back=False)

        viewer_body = ft.Container(
            self.viewer_hscroll,
            expand=True,
            bgcolor=_VIEWER_BG,
            padding=20,
        )
        self._viewer_body = viewer_body
        main_content = ft.Row([viewer_body, self._right_sidebar], expand=True, spacing=0)

        self.view = ft.Column(
            [nav_toolbar, annot_toolbar, main_content],
            expand=True,
            spacing=0,
        )

    # ── TOC panel ─────────────────────────────────────────────────────────────

    def _build_toc_sidebar_panel(self) -> ft.Control:
        from ._viewer_defs import _OCR_PANEL_BG
        try:
            with self._doc_lock:
                toc = self.doc.get_toc()
        except Exception:
            toc = []

        if not toc:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.LIST_ALT_OUTLINED, size=40, color="outlineVariant"),
                        ft.Text(
                            "Sin tabla de contenidos",
                            color="onSurfaceVariant",
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=ft.padding.all(24),
                expand=True,
                alignment=ft.alignment.center,
            )

        items: list[ft.Control] = []
        for entry in toc:
            level    = entry[0]
            title    = entry[1]
            page_num = entry[2]
            indent   = (level - 1) * 14
            is_top   = (level == 1)
            items.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(width=indent),
                            ft.Icon(
                                ft.Icons.CIRCLE if is_top else ft.Icons.RADIO_BUTTON_UNCHECKED,
                                size=7 if is_top else 5,
                                color="#1565C0" if is_top else "#64B5F6",
                            ),
                            ft.Container(width=5),
                            ft.Text(
                                title,
                                size=12 if is_top else 11,
                                weight=ft.FontWeight.W_600 if is_top else ft.FontWeight.NORMAL,
                                color="onSurface" if is_top else "onSurfaceVariant",
                                expand=True,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(str(page_num), size=11, color="onSurfaceVariant"),
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    on_click=lambda e, p=page_num - 1: self._scroll_to_page(
                        max(0, min(p, len(self.doc) - 1))
                    ),
                    ink=True,
                    border_radius=4,
                )
            )

        return ft.Column(
            [
                ft.Container(
                    content=ft.Text(
                        "Tabla de Contenidos",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color="onSurface",
                    ),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border=ft.border.only(bottom=ft.BorderSide(1, "outlineVariant")),
                ),
                ft.ListView(items, expand=True, spacing=0),
            ],
            spacing=0,
            expand=True,
        )

    # ── display mode ──────────────────────────────────────────────────────────

    def _set_display_mode(self, mode: str) -> None:
        self._display_mode = mode
        _btns = {
            "continuous": self._mode_btn_continuous,
            "single":     self._mode_btn_single,
            "double":     self._mode_btn_double,
        }
        for m, btn in _btns.items():
            if btn is None:
                continue
            btn.icon_color = "#1565C0" if m == mode else None
            btn.bgcolor    = ft.Colors.with_opacity(0.20, ft.Colors.PRIMARY) if m == mode else None
            try:
                btn.update()
            except Exception:
                pass

        if not self._page_rows:
            return

        if mode == "continuous":
            for row in self._page_rows:
                row.visible = True
            try:
                self.viewer_scroll.update()
            except Exception:
                pass
            self._scroll_to_page(self.current_page, instant=True)
        else:
            self._scroll_to_page(self.current_page)

    # ── page management ───────────────────────────────────────────────────────

    def _insert_blank_page(self, e=None) -> None:
        pn = self.current_page
        with self._doc_lock:
            p = self.doc[pn]
            w, h = p.rect.width, p.rect.height
            self.doc.new_page(pno=pn + 1, width=w, height=h)
        self._annot._history = [
            (pg if pg <= pn else pg + 1, xr) for pg, xr in self._annot._history
        ]
        self.total_label.value = f"/ {len(self.doc)}"
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        self._show_snack("Página en blanco insertada")

    def _duplicate_page(self, e=None) -> None:
        pn = self.current_page
        with self._doc_lock:
            self.doc.copy_page(pn, pn + 1)
        self._annot._history = [
            (pg if pg <= pn else pg + 1, xr) for pg, xr in self._annot._history
        ]
        self.total_label.value = f"/ {len(self.doc)}"
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        self._show_snack("Página duplicada")

    def _delete_page(self, e=None) -> None:
        if len(self.doc) <= 1:
            self._show_snack("No se puede eliminar la única página")
            return
        pn = self.current_page
        with self._doc_lock:
            self.doc.delete_page(pn)
        self._annot._history = [
            (pg if pg < pn else pg - 1, xr)
            for pg, xr in self._annot._history
            if pg != pn
        ]
        self.current_page = min(pn, len(self.doc) - 1)
        self.total_label.value = f"/ {len(self.doc)}"
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()
        self._show_snack("Página eliminada")

    def _move_page_up(self, e=None) -> None:
        pn = self.current_page
        if pn == 0:
            return
        with self._doc_lock:
            self.doc.move_page(pn, pn - 1)
        self._annot._history = [
            (pg - 1 if pg == pn else pg + 1 if pg == pn - 1 else pg, xr)
            for pg, xr in self._annot._history
        ]
        self.current_page = pn - 1
        self.total_label.value = f"/ {len(self.doc)}"
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()

    def _move_page_down(self, e=None) -> None:
        pn = self.current_page
        if pn >= len(self.doc) - 1:
            return
        with self._doc_lock:
            self.doc.move_page(pn, pn + 1)
        self._annot._history = [
            (pg + 1 if pg == pn else pg - 1 if pg == pn + 1 else pg, xr)
            for pg, xr in self._annot._history
        ]
        self.current_page = pn + 1
        self.total_label.value = f"/ {len(self.doc)}"
        self._rebuild_scroll_content(scroll_back=False)
        self.page_ref.update()

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

    def get_tab_info(self) -> dict:
        return {
            "label":     self.filename,
            "icon":      ft.Icons.PICTURE_AS_PDF,
            "content":   self.view,
            "closeable": True,
            "close_cb":  lambda: self.on_close(self),
            "viewer":    self,
        }

    # ── lazy suspension ───────────────────────────────────────────────────────
    #
    # Lifecycle de RAM en dos pasos cuando este tab pierde foco:
    #
    #   1) on_blur (inmediato): shrink del cache a 5 entradas. Esto libera la
    #      mayoría de las páginas cacheadas (~6-7 MB por tab) sin esperar el
    #      timer — clave cuando hay muchos PDFs abiertos.
    #
    #   2) 20 s después (_do_suspend): clear total del cache. El fitz.Document
    #      queda abierto para evitar serializar anotaciones no guardadas. Al
    #      volver al tab, un fast-resize re-renderiza las páginas visibles.
    #
    # Antes el delay era 60 s y no había shrink inmediato → con 10 PDFs
    # abiertos cada uno podía retener 8-16 MB en cache simultáneamente.

    _SUSPEND_DELAY     = 20.0  # segundos de inactividad antes de clear total
    _BLUR_SHRINK_KEEP  = 5     # entradas a conservar tras perder foco

    def on_focus(self) -> None:
        """Called by DocumentManagerUI when this tab becomes active."""
        self._cancel_suspend_timer()
        if self._is_suspended:
            self._is_suspended = False
            # fast-resize path: hides stale images, shows loading overlays,
            # and triggers lazy re-render of the first visible pages.
            self._rebuild_scroll_content(scroll_back=False)
        else:
            # Recalcular el ancho del Column por si la ventana fue redimensionada
            # mientras este tab estaba inactivo.
            self._update_scroll_column_width()
        # Restaurar la posición de scroll donde estaba el usuario. Cambiar de
        # pestaña alterna content.visible (False/True), y Flutter reinicia el
        # offset del Column de scroll al re-mostrarlo → volver a un PDF perdía la
        # hoja y saltaba al inicio. _scroll_px se mantiene a través del blur/
        # suspend, así que basta con reposicionar al recuperar el foco.
        self._restore_scroll_position()

    def _restore_scroll_position(self) -> None:
        """Reposiciona el scroll a `_scroll_px` tras recuperar el foco.

        Se hace con un pequeño retardo: al volverse visible, el scrollable de
        Flutter aún no tiene su extent calculado, así que un scroll_to inmediato
        se descartaría. El timer deja pasar un frame y luego reposiciona.
        """
        if getattr(self, "_display_mode", "continuous") != "continuous":
            return
        px = getattr(self, "_scroll_px", 0.0)
        if not px or px <= 0:
            return

        def _do() -> None:
            if getattr(self, "_is_closed", False):
                return
            try:
                self.viewer_scroll.scroll_to(offset=px, duration=0)
                self.viewer_scroll.update()
            except Exception:
                pass

        self._cancel_restore_scroll_timer()
        t = threading.Timer(0.10, _do)
        t.daemon = True
        t.start()
        self._restore_scroll_timer = t

    def _cancel_restore_scroll_timer(self) -> None:
        t = getattr(self, "_restore_scroll_timer", None)
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
            self._restore_scroll_timer = None

    def on_blur(self) -> None:
        """Called by DocumentManagerUI when another tab becomes active."""
        # Shrink inmediato: libera RAM sin esperar el timer.
        try:
            self._render_cache.shrink(self._BLUR_SHRINK_KEEP)
        except Exception:
            pass
        if hasattr(self, "_schedule_ocr_model_release"):
            try:
                self._schedule_ocr_model_release()
            except Exception:
                pass
        self._start_suspend_timer()

    def _start_suspend_timer(self) -> None:
        self._cancel_suspend_timer()
        t = threading.Timer(self._SUSPEND_DELAY, self._do_suspend)
        t.daemon = True
        t.start()
        self._suspend_timer = t

    def _cancel_suspend_timer(self) -> None:
        if self._suspend_timer is not None:
            self._suspend_timer.cancel()
            self._suspend_timer = None

    def _do_suspend(self) -> None:
        """Background-thread callback: free render cache, keep doc open."""
        if self._is_suspended:
            return
        self._render_gen += 1      # abort any in-flight renders
        self._render_cache.clear() # release cached page images
        # Liberar también las cachés de texto por página: sin esto retenían el
        # rawdict char-level de cada página visitada incluso con el tab suspendido
        # (se reconstruyen perezosamente al volver). Ver _prune_text_caches.
        self._page_words.clear()
        self._page_word_bands.clear()
        self._page_blocks_cache.clear()
        self._text_rects_cache.clear()
        self._text_sel_sig.clear()
        self._is_suspended = True

    def close(self) -> None:
        if getattr(self, "_is_closed", False):
            return
        self._is_closed = True
        self._cancel_suspend_timer()
        # Cancelar timers pendientes de render/scroll/zoom. Si no, pueden
        # dispararse tras cerrar el doc (sus callbacks hacen len(self.doc) /
        # tocan controles) y, sobre todo, cada threading.Timer referencia self,
        # manteniendo viva toda la instancia (listas de ~20 controles × N
        # páginas) hasta que disparen → memoria que no se libera.
        for _attr in ("_scroll_idle_timer", "_zoom_timer", "_render_upd_timer", "_restore_scroll_timer", "_single_nav_timer"):
            _t = getattr(self, _attr, None)
            if _t is not None:
                try:
                    _t.cancel()
                except Exception:
                    pass
                setattr(self, _attr, None)
        self._render_gen += 1  # signal running workers to exit before doc is closed
        self._render_cache.clear()
        if hasattr(self, "_cancel_ocr_model_release"):
            self._cancel_ocr_model_release()
        if getattr(self, "_ocr_processor", None) is not None:
            self._ocr_processor.release_predictor()
        if getattr(self, "_agent_instance", None) is not None:
            try:
                self._agent_instance.close()
            except Exception:
                pass
            self._agent_instance = None
        try:
            # Cerrar bajo _doc_lock: un worker puede estar rasterizando
            # (get_pixmap) sobre self.doc en este instante; cerrar el documento
            # sin sincronizar sería un use-after-free en MuPDF (crash nativo). El
            # lock espera a que termine el render en curso; los nuevos ya abortan
            # por el _render_gen incrementado arriba.
            with self._doc_lock:
                self.doc.close()
        except ValueError:
            pass
        try:
            self.page_ref.overlay.remove(self._save_picker)
            self.page_ref.update()
        except ValueError:
            pass
        try:
            self.page_ref.overlay.remove(self._print_save_picker)
            self.page_ref.update()
        except (ValueError, AttributeError):
            pass

    # ── sidebar mode switching ────────────────────────────────────────────────

    def _switch_sidebar_mode(self, mode: str) -> None:
        """Switch sidebar between 'ocr', 'redact' and 'agent' views."""
        self._sidebar_mode = mode

        _TAB_META = {
            "toc":    ("#1565C0", ft.Colors.with_opacity(0.15, "#1565C0"), "_sidebar_tab_toc_btn",    "_sidebar_toc_view"),
            "ocr":    ("#2E7D32", ft.Colors.with_opacity(0.15, "#2E7D32"), "_sidebar_tab_ocr_btn",    "_sidebar_ocr_view"),
            "redact": ("#E65100", ft.Colors.with_opacity(0.15, "#E65100"), "_sidebar_tab_redact_btn", "_sidebar_redact_view"),
            "agent":  ("#5C35C9", ft.Colors.with_opacity(0.15, "#5C35C9"), "_sidebar_tab_agent_btn",  "_sidebar_agent_view"),
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
                            ctrl.color = active_color if is_active else "onSurfaceVariant"
                        elif isinstance(ctrl, ft.Text):
                            ctrl.color = active_color if is_active else "onSurfaceVariant"
                btn.bgcolor = active_bg if is_active else None
                btn.border  = ft.border.only(
                    bottom=ft.BorderSide(2, active_color if is_active else "outlineVariant")
                )

        # Toolbar agent button highlight
        if self._agent_toolbar_btn is not None:
            is_agent = (mode == "agent")
            self._agent_toolbar_btn.icon_color = "#5C35C9" if is_agent else None
            self._agent_toolbar_btn.bgcolor    = ft.Colors.with_opacity(0.15, "#5C35C9") if is_agent else None
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
            bgcolor=ft.Colors.with_opacity(0.15, "#5C35C9") if _is_agent else None,
            on_click=lambda e: self._switch_sidebar_mode("agent"),
            visible=AGENT_ENABLED,   # oculto mientras el agente está en pulido
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
            if img is None:  # slot no construido (placeholder)
                continue
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
        sel_text = self._update_text_selection(pn, start_pt, pn, end_pt, update_ui=True)
        if sel_text:
            self._show_text_sel_bar(sel_text)
