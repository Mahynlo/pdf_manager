"""App entry point: tab shell + file picker."""

from pathlib import Path

import flet as ft

from pdf_extractor import PDFExtractionTab
from pdf_viewer import PDFViewerTab


def main(page: ft.Page) -> None:
    page.title = "Visor de PDFs"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0

    open_tabs: list[PDFViewerTab] = []
    extractor_tab: PDFExtractionTab | None = None

    tabs_ctrl = ft.Tabs(
        expand=True,
        tab_alignment=ft.TabAlignment.START,
        animation_duration=150,
        tabs=[],
    )

    body = ft.Column([tabs_ctrl], expand=True, spacing=0)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _open_picker() -> None:
        file_picker.pick_files(
            dialog_title="Abrir PDF",
            allowed_extensions=["pdf"],
            allow_multiple=True,
        )

    def _set_body(ctrl: ft.Control) -> None:
        body.controls = [ctrl]
        page.update()

    def _show_error(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
        page.update()

    def _rebuild_tabs(selected_index: int | None = None) -> None:
        base_tabs = [extractor_tab.get_tab()] if extractor_tab else []
        tabs_ctrl.tabs = [*base_tabs, *[t.get_tab() for t in open_tabs]]

        if selected_index is None:
            selected_index = tabs_ctrl.selected_index or 0

        if not tabs_ctrl.tabs:
            tabs_ctrl.selected_index = None
        else:
            tabs_ctrl.selected_index = max(0, min(selected_index, len(tabs_ctrl.tabs) - 1))
        _set_body(tabs_ctrl)

    def _open_pdf_path(path: str) -> None:
        for i, existing in enumerate(open_tabs):
            if existing.path == path:
                _rebuild_tabs(i + 1)
                return
        try:
            viewer = PDFViewerTab(path, page, close_tab)
        except Exception as ex:
            _show_error(f"Error abriendo {Path(path).name}: {ex}")
            return
        open_tabs.append(viewer)
        _rebuild_tabs(len(open_tabs))

    # ── tab management ───────────────────────────────────────────────────────

    def close_tab(viewer: PDFViewerTab) -> None:
        idx = open_tabs.index(viewer)
        viewer.close()
        open_tabs.remove(viewer)
        if open_tabs:
            _rebuild_tabs(min(idx, len(open_tabs) - 1) + 1)
        else:
            _rebuild_tabs(0)

    def on_file_picked(e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        last_new: int | None = None
        for f in e.files:
            # Switch to existing tab if the file is already open
            opened_existing = False
            for i, existing in enumerate(open_tabs):
                if existing.path == f.path:
                    last_new = i + 1
                    opened_existing = True
                    break
            if opened_existing:
                continue
            try:
                viewer = PDFViewerTab(f.path, page, close_tab)
            except Exception as ex:
                _show_error(f"Error abriendo {Path(f.path).name}: {ex}")
                continue
            open_tabs.append(viewer)
            last_new = len(open_tabs)

        if last_new is not None:
            _rebuild_tabs(last_new)

    # ── keyboard shortcuts ───────────────────────────────────────────────────

    def on_keyboard(e: ft.KeyboardEvent) -> None:
        if e.ctrl and e.key.upper() == "O":
            _open_picker()
            return
        if not open_tabs:
            return
        idx = (tabs_ctrl.selected_index or 0) - 1
        if not (0 <= idx < len(open_tabs)):
            return
        v = open_tabs[idx]
        if e.ctrl and e.key.upper() == "Z":
            v._undo()
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

    # ── wiring ───────────────────────────────────────────────────────────────

    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.append(file_picker)
    page.on_keyboard_event = on_keyboard

    extractor_tab = PDFExtractionTab(page, _open_pdf_path)
    _rebuild_tabs(0)

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ft.Colors.RED_400, size=28),
        title=ft.Text("Visor de PDFs", weight=ft.FontWeight.BOLD),
        actions=[
            ft.IconButton(
                ft.Icons.FIND_IN_PAGE,
                tooltip="Ir a Extraer PDF",
                on_click=lambda e: _rebuild_tabs(0),
            ),
            ft.IconButton(
                ft.Icons.FOLDER_OPEN,
                tooltip="Abrir PDF  (Ctrl+O)",
                on_click=lambda e: _open_picker(),
            ),
        ],
        bgcolor="#F3F3F3",
    )

    page.add(body)


ft.app(main)
