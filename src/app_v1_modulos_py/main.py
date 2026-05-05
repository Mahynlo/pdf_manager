"""App entry point: navbar + home screen + tab shell + file picker."""

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow running as a script (python main.py) by fixing sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "app_v1_modulos_py"

import flet as ft

from . import recent_files as rf
from .document_manager_ui import DocumentManagerUI
from .home import HomePage
from .pdf_extractor import PDFExtractionTab
from .pdf_merge import MergePDFTab
from .pdf_viewer import PDFViewerTab
from .settings_tab import SettingsTab

_NAVBAR_BG     = "#1E2A38"
_NAVBAR_FG     = "#FFFFFF"
_NAVBAR_FG_DIM = "#90A4AE"


def main(page: ft.Page) -> None:
    page.title        = "Extraer PDFs"
    page.theme_mode   = ft.ThemeMode.LIGHT
    page.padding      = 0
    page.window.icon  = "icon.png"

    open_tabs:     list[PDFViewerTab]      = []
    extractor_tab: PDFExtractionTab | None = None
    merge_tab:     MergePDFTab      | None = None
    settings_tab:  SettingsTab      | None = None

    doc_mgr = DocumentManagerUI(page)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _show_error(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
        page.update()

    def _fixed_count() -> int:
        """Number of 'system' tabs before the PDF viewer tabs."""
        n = 1  # home
        if extractor_tab is not None:
            n += 1
        if merge_tab is not None:
            n += 1
        if settings_tab is not None:
            n += 1
        return n

    def _merge_tab_idx() -> int:
        return 1 + (1 if extractor_tab is not None else 0)

    def _settings_tab_idx() -> int:
        return 1 + (1 if extractor_tab is not None else 0) + (1 if merge_tab is not None else 0)

    def _rebuild_tabs(selected_index: int | None = None) -> None:
        if selected_index is None:
            selected_index = doc_mgr.selected_index

        infos = [home.get_tab_info()]
        if extractor_tab is not None:
            infos.append(extractor_tab.get_tab_info())
        if merge_tab is not None:
            infos.append(merge_tab.get_tab_info())
        if settings_tab is not None:
            infos.append(settings_tab.get_tab_info())
        for v in open_tabs:
            infos.append(v.get_tab_info())

        doc_mgr.rebuild(infos, selected_index)

    # ── Abrir pdf ─────────────────────────────────────────────────────────────

    def _open_pdf_path(path: str) -> None:
        for i, existing in enumerate(open_tabs):
            if existing.path == path:
                _rebuild_tabs(_fixed_count() + i)
                return
        try:
            viewer = PDFViewerTab(path, page, _close_viewer_tab)
        except Exception as ex:
            _show_error(f"Error abriendo {Path(path).name}: {ex}")
            return
        open_tabs.append(viewer)
        rf.push(path)
        home.refresh_recent()
        _rebuild_tabs(_fixed_count() + len(open_tabs) - 1)

    def _open_picker() -> None:
        file_picker.pick_files(
            dialog_title="Abrir PDF",
            allowed_extensions=["pdf"],
            allow_multiple=True,
        )

    # ── extractor tab ─────────────────────────────────────────────────────────

    def _open_extractor() -> None:
        nonlocal extractor_tab
        if extractor_tab is None:
            extractor_tab = PDFExtractionTab(page, _open_pdf_path)
        _rebuild_tabs(1)

    # ── merge tab ─────────────────────────────────────────────────────────────

    def _open_merge() -> None:
        nonlocal merge_tab
        if merge_tab is not None:
            _rebuild_tabs(_merge_tab_idx())
            return
        merge_tab = MergePDFTab(page, _close_merge_tab, _open_pdf_path)
        _rebuild_tabs(_merge_tab_idx())

    def _close_merge_tab(tab: MergePDFTab) -> None:
        nonlocal merge_tab
        tab.close()
        merge_tab = None
        _rebuild_tabs(0)

    # ── settings tab ─────────────────────────────────────────────────────────

    def _open_settings() -> None:
        nonlocal settings_tab
        if settings_tab is not None:
            _rebuild_tabs(_settings_tab_idx())
            return
        settings_tab = SettingsTab(page, _close_settings_tab)
        _rebuild_tabs(_settings_tab_idx())

    def _close_settings_tab(tab: SettingsTab) -> None:
        nonlocal settings_tab
        settings_tab = None
        _rebuild_tabs(0)

    # ── close viewer tab ─────────────────────────────────────────────────────

    def _close_viewer_tab(viewer: PDFViewerTab) -> None:
        idx = open_tabs.index(viewer)
        viewer.close()
        open_tabs.remove(viewer)
        fc = _fixed_count()
        if open_tabs:
            _rebuild_tabs(fc + min(idx, len(open_tabs) - 1))
        else:
            _rebuild_tabs(0)

    # ── file picker result ────────────────────────────────────────────────────

    def _on_file_picked(e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        last_new: int | None = None
        for f in e.files:
            already_open = False
            for i, existing in enumerate(open_tabs):
                if existing.path == f.path:
                    last_new = _fixed_count() + i
                    already_open = True
                    break
            if already_open:
                continue
            try:
                viewer = PDFViewerTab(f.path, page, _close_viewer_tab)
            except Exception as ex:
                _show_error(f"Error abriendo {Path(f.path).name}: {ex}")
                continue
            open_tabs.append(viewer)
            rf.push(f.path)
            last_new = _fixed_count() + len(open_tabs) - 1

        home.refresh_recent()
        if last_new is not None:
            _rebuild_tabs(last_new)

    # ── keyboard shortcuts ────────────────────────────────────────────────────

    def _on_keyboard(e: ft.KeyboardEvent) -> None:
        for v in open_tabs:
            v._ctrl_pressed = e.ctrl
        if e.ctrl and e.key.upper() == "O":
            _open_picker()
            return
        if not open_tabs:
            return
        idx = doc_mgr.selected_index - _fixed_count()
        if not (0 <= idx < len(open_tabs)):
            return
        v = open_tabs[idx]
        if e.ctrl and e.key.upper() == "Z":
            v._undo()
            return
        if e.ctrl and e.key.upper() == "A":
            v._select_all_page_text()
            return
        match e.key:
            case "Arrow Left" | "Arrow Up":
                v._prev()
            case "Arrow Right" | "Arrow Down":
                v._next()
            case "+" | "=":
                if not e.ctrl:
                    v._zoom_in()
            case "-":
                if not e.ctrl:
                    v._zoom_out()

    # ── persistent navbar ─────────────────────────────────────────────────────

    def _nav_btn(
        icon: str,
        label: str,
        on_click,
        tooltip: str = "",
    ) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=16, color=_NAVBAR_FG),
                    ft.Text(label, size=13, color=_NAVBAR_FG, weight=ft.FontWeight.W_500),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            border_radius=8,
            tooltip=tooltip,
            on_click=on_click,
            ink=True,
            ink_color="#FFFFFF22",
        )

    navbar = ft.Container(
        content=ft.Row(
            [
                # ── brand ──
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PICTURE_AS_PDF, size=22, color="#EF5350"),
                        ft.Text(
                            "Extraer PDFs",
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=_NAVBAR_FG,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(expand=True),
                # ── action buttons ──
                _nav_btn(
                    ft.Icons.FOLDER_OPEN_OUTLINED,
                    "Abrir PDF",
                    lambda e: _open_picker(),
                    tooltip="Abrir uno o varios PDF (Ctrl+O)",
                ),
                _nav_btn(
                    ft.Icons.FIND_IN_PAGE_OUTLINED,
                    "Extraer texto",
                    lambda e: _open_extractor(),
                    tooltip="Abrir pestaña de extracción por palabras clave",
                ),
                _nav_btn(
                    ft.Icons.MERGE_TYPE,
                    "Combinar PDFs",
                    lambda e: _open_merge(),
                    tooltip="Combinar múltiples PDFs en uno",
                ),
                ft.Container(width=4),
                ft.Container(
                    width=1, height=20,
                    bgcolor=_NAVBAR_FG_DIM,
                ),
                ft.Container(width=4),
                _nav_btn(
                    ft.Icons.SETTINGS_OUTLINED,
                    "Configuración",
                    lambda e: _open_settings(),
                    tooltip="Abrir configuración de la aplicación",
                ),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=_NAVBAR_BG,
        padding=ft.padding.symmetric(horizontal=16, vertical=6),
        border=ft.border.only(bottom=ft.BorderSide(1, "#2E3E50")),
    )

    # ── wiring ────────────────────────────────────────────────────────────────

    def _on_keyboard_up(e: ft.KeyboardEvent) -> None:
        for v in open_tabs:
            v._ctrl_pressed = e.ctrl

    file_picker = ft.FilePicker(on_result=_on_file_picked)
    page.overlay.append(file_picker)
    page.on_keyboard_event    = _on_keyboard
    page.on_keyboard_event_up = _on_keyboard_up

    home = HomePage(
        page_ref=page,
        on_open_extractor=_open_extractor,
        on_open_merge=_open_merge,
        on_open_picker=_open_picker,
        on_open_pdf=_open_pdf_path,
    )

    body = ft.Column(
        [navbar, doc_mgr.control],
        expand=True,
        spacing=0,
    )

    _rebuild_tabs(0)
    page.add(body)

    # Open PDF passed as command-line argument (e.g. from OS file association)
    if len(sys.argv) > 1:
        candidate = sys.argv[1]
        if candidate.lower().endswith(".pdf") and Path(candidate).exists():
            _open_pdf_path(candidate)


ft.app(main)
