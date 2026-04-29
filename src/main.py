"""App entry point: navbar + home screen + tab shell + file picker."""

import sys
from pathlib import Path

import flet as ft

import recent_files as rf
from home import HomePage
from pdf_extractor import PDFExtractionTab
from pdf_merge import MergePDFTab
from pdf_viewer import PDFViewerTab
from settings_tab import SettingsTab

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

    tabs_ctrl = ft.Tabs(
        expand=True,
        tab_alignment=ft.TabAlignment.START,
        animation_duration=150,
        tabs=[],
    )

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
        """
        Reconstruye la las pestañas de la aplicacion en el orden correcto, asegurando que la pestaña 
        de inicio siempre esté presente y que las pestañas de extractor, combinación y configuración 
        se añadan o eliminen según su estado actual. Además, mantiene la selección de pestaña consistente 
        después de cualquier cambio.
        """
        base: list[ft.Tab] = [home.get_tab()]
        if extractor_tab is not None:
            base.append(extractor_tab.get_tab())
        if merge_tab is not None:
            base.append(merge_tab.get_tab())
        if settings_tab is not None:
            base.append(settings_tab.get_tab())
        tabs_ctrl.tabs = [*base, *[t.get_tab() for t in open_tabs]]

        if selected_index is None:
            selected_index = tabs_ctrl.selected_index or 0
        if not tabs_ctrl.tabs:
            tabs_ctrl.selected_index = None
        else:
            tabs_ctrl.selected_index = max(
                0, min(selected_index, len(tabs_ctrl.tabs) - 1)
            )
        page.update()

    # ── Abrir pdf ─────────────────────────────────────────────────────────────

    def _open_pdf_path(path: str) -> None:
        """
        Funcion que se encarga de abrir un pdf usando el path.
        """
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
        """
        Abre la pestaña de extracción de texto. Si ya está abierta, simplemente la selecciona.
        """
        nonlocal extractor_tab
        if extractor_tab is None:
            extractor_tab = PDFExtractionTab(page, _open_pdf_path)
        _rebuild_tabs(1)

    # ── merge tab ─────────────────────────────────────────────────────────────

    def _open_merge() -> None:
        """Abre la pestaña de combinación de PDFs. Si ya está abierta, simplemente la selecciona."""
        nonlocal merge_tab
        if merge_tab is not None:
            _rebuild_tabs(_merge_tab_idx())
            return
        merge_tab = MergePDFTab(page, _close_merge_tab, _open_pdf_path)
        _rebuild_tabs(_merge_tab_idx())

    def _close_merge_tab(tab: MergePDFTab) -> None:
        """Cierra la pestaña de combinación de PDFs y limpia su estado."""
        nonlocal merge_tab
        tab.close()
        merge_tab = None
        _rebuild_tabs(0)

    # ── settings tab ─────────────────────────────────────────────────────────

    def _open_settings() -> None:
        """Abre la pestaña de configuración. Si ya está abierta, simplemente la selecciona."""
        nonlocal settings_tab
        if settings_tab is not None:
            _rebuild_tabs(_settings_tab_idx())
            return
        settings_tab = SettingsTab(page, _close_settings_tab)
        _rebuild_tabs(_settings_tab_idx())

    def _close_settings_tab(tab: SettingsTab) -> None:
        """Cierra la pestaña de configuración y limpia su estado."""
        nonlocal settings_tab
        settings_tab = None
        _rebuild_tabs(0)

    # ── close viewer tab ─────────────────────────────────────────────────────

    def _close_viewer_tab(viewer: PDFViewerTab) -> None:
        """Cierra una pestaña de visor de PDF específica y actualiza la interfaz."""
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
        """Maneja el resultado del selector de archivos, abriendo cada PDF seleccionado en una nueva pestaña o enfocando la pestaña existente si ya está abierta."""
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
        """Maneja los atajos de teclado globales para la aplicación, incluyendo abrir el selector de archivos, navegar entre pestañas, y realizar acciones específicas dentro de las pestañas de visor de PDF."""
        # Keep all open viewers aware of the current Ctrl state (used for Ctrl+Scroll zoom).
        for v in open_tabs:
            v._ctrl_pressed = e.ctrl
        if e.ctrl and e.key.upper() == "O": # Ctrl+O para abrir el selector de archivos
            _open_picker()
            return
        if not open_tabs:# Si no hay pestañas de visor de PDF abiertas, no se manejan otros atajos relacionados con la navegación o acciones dentro del visor.
            return
        idx = (tabs_ctrl.selected_index or 0) - _fixed_count()
        if not (0 <= idx < len(open_tabs)): # Si la pestaña seleccionada no corresponde a un visor de PDF, no se manejan los atajos relacionados con el visor.
            return
        v = open_tabs[idx]
        if e.ctrl and e.key.upper() == "Z": # Ctrl+Z para deshacer la última acción de redacción en el visor de PDF
            v._undo()
            return
        if e.ctrl and e.key.upper() == "A": # Ctrl+A para seleccionar todo el texto en la pestaña de visor de PDF activa
            v._select_all_page_text()
            return
        match e.key:
            case "Arrow Left" | "Arrow Up": # Flechas izquierda o arriba para navegar a la página anterior en la pestaña de visor de PDF activa
                v._prev()
            case "Arrow Right" | "Arrow Down": # Flechas derecha o abajo para navegar a la página siguiente en la pestaña de visor de PDF activa
                v._next()
            case "+" | "=":
                if not e.ctrl: # Ctrl+Plus para acercar (zoom in) en la pestaña de visor de PDF activa
                    v._zoom_in()
            case "-":
                if not e.ctrl: # Ctrl+Minus para alejar (zoom out) en la pestaña de visor de PDF activa
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
        """Clear Ctrl state on key-up so Ctrl+Scroll zoom stops after releasing Ctrl."""
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
        [navbar, tabs_ctrl],
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
