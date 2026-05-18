"""App entry point: navbar + home screen + tab shell + file picker."""

import sys
import os
import threading
import time
from pathlib import Path
import platform

import flet as ft

import recent_files as rf
from document_manager_ui import DocumentManagerUI
from home import HomePage
from pdf_extractor import PDFExtractionTab
from pdf_merge import MergePDFTab
from pdf_security import (
    PDFInvalidPasswordError,
    PDFPasswordRequiredError,
    PDFSecurityManager,
    PDFSecurityTab,
)
from pdf_viewer import PDFViewerTab
from settings_tab import SettingsTab

import win32event  # type: ignore[reportMissingImports]
import win32api  # type: ignore[reportMissingImports]
import winerror  # type: ignore[reportMissingImports]
import win32pipe  # type: ignore[reportMissingImports]
import win32file  # type: ignore[reportMissingImports]

# Single-instance IPC (pywin32 named pipes en Windows / local TCP en otros)
# Permite que la app ejecutada por "Abrir con" reenvíe la ruta a la instancia activa.
_incoming_paths: list[str] = []
_incoming_lock = threading.Lock()
_incoming_event = threading.Event()


def _clean_path_argument(arg: str) -> str | None:
    """Limpia y valida un argumento de ruta desde línea de comandos.
    
    Elimina comillas del registro de Windows, espacios extra, y backticks.
    Verifica que sea un archivo PDF existente y retorna la ruta absoluta.
    
    Args:
        arg: Argumento de línea de comandos que podría ser una ruta a PDF
        
    Returns:
        Ruta absoluta resolvida o None si es inválida/no existe
    """
    clean = arg.strip(" \"'`")
    if not clean.lower().endswith(".pdf"):
        return None
    try:
        abs_path = str(Path(clean).resolve())
        if Path(abs_path).exists():
            return abs_path
    except Exception:
        pass
    return None


if platform.system() == "Windows":
    if any(module is None for module in (win32event, win32api, winerror, win32pipe, win32file)):
        raise ImportError("pywin32 no está disponible en este build de Windows")

    _MUTEX_NAME = "ExtraerPDFs_SingleInstance_Mutex"
    _PIPE_NAME = r"\\.\pipe\ExtraerPDFs_IPC_Pipe"

    # Intentar obtener el Mutex para verificar si ya hay una instancia
    _mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
    _last_error = win32api.GetLastError()

    if _last_error == winerror.ERROR_ALREADY_EXISTS:
        # Ya existe una instancia. Somos el cliente (instancia secundaria)
        try:
            # Recolectar PDFs válidos de los argumentos
            payload_lines = []
            for arg in sys.argv[1:]:
                cleaned = _clean_path_argument(arg)
                if cleaned:
                    payload_lines.append(cleaned)
            
            if not payload_lines:
                payload_lines.append("__ACTIVATE__")
                
            payload = "\n".join(payload_lines) + "\n"
            
            # Esperar a que el pipe del servidor esté listo (timeout: 3s)
            try:
                win32file.WaitNamedPipe(_PIPE_NAME, 3000)
            except Exception:
                pass
                
            # Intentar enviar las rutas al servidor (instancia primaria)
            try:
                handle = win32file.CreateFile(
                    _PIPE_NAME,
                    win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None
                )
                win32file.WriteFile(handle, payload.encode("utf-8"))
                win32file.CloseHandle(handle)
            except Exception:
                # Si falla la comunicación, igualmente salimos
                pass
        except Exception:
            pass
        # Terminar inmediatamente: evitar que Flet cargue la GUI en el cliente
        os._exit(0)
    else:
        # Somos el servidor (primera instancia)
        def _ipc_server_loop() -> None:
            """Loop de servidor que escucha conexiones en el Named Pipe."""
            while True:
                pipe = None
                try:
                    # Crear nueva instancia del pipe para la siguiente conexión
                    pipe = win32pipe.CreateNamedPipe(
                        _PIPE_NAME,
                        win32pipe.PIPE_ACCESS_INBOUND,
                        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                        win32pipe.PIPE_UNLIMITED_INSTANCES,
                        65536, 65536,
                        0,
                        None
                    )
                    # Bloquear hasta que un cliente se conecte
                    win32pipe.ConnectNamedPipe(pipe, None)
                    
                    # Leer datos del cliente
                    try:
                        result, data = win32file.ReadFile(pipe, 65536)
                        payload = data.decode("utf-8", errors="ignore")
                        
                        # Procesar cada línea recibida
                        for raw in payload.splitlines():
                            # Las rutas ya vienen limpias del cliente
                            path = raw.strip()
                            if not path:
                                continue
                            # Agregar a la cola para procesamiento
                            with _incoming_lock:
                                _incoming_paths.append(path)
                        # Señalar que hay datos nuevos
                        _incoming_event.set()
                    finally:
                        if pipe is not None:
                            win32file.CloseHandle(pipe)
                except Exception:
                    if pipe is not None:
                        try:
                            win32file.CloseHandle(pipe)
                        except Exception:
                            pass
                    time.sleep(0.1)

        _ipc_thread = threading.Thread(target=_ipc_server_loop, daemon=True)
        _ipc_thread.start()
else:
    # Linux/macOS Fallback: usar TCP local
    import socket
    _IPC_PORT = 57422
    
    try:
        _ipc_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _ipc_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _ipc_server_socket.bind(("127.0.0.1", _IPC_PORT))
        _ipc_server_socket.listen(5)

        def _ipc_server_loop() -> None:
            """Loop de servidor TCP para recibir rutas de otras instancias."""
            while True:
                try:
                    conn, _addr = _ipc_server_socket.accept()
                    with conn:
                        conn.settimeout(2.0)
                        try:
                            data = conn.recv(8192)
                        except socket.timeout:
                            continue
                        if not data:
                            continue
                        payload = data.decode("utf-8", errors="ignore")
                        
                        # Procesar cada línea recibida
                        for raw in payload.splitlines():
                            # Las rutas ya vienen limpias del cliente
                            path = raw.strip()
                            if not path:
                                continue
                            with _incoming_lock:
                                _incoming_paths.append(path)
                        _incoming_event.set()
                except Exception:
                    time.sleep(0.1)

        _ipc_thread = threading.Thread(target=_ipc_server_loop, daemon=True)
        _ipc_thread.start()
    except OSError:
        # No se pudo crear el socket servidor: somos una instancia secundaria
        try:
            with socket.create_connection(("127.0.0.1", _IPC_PORT), timeout=1) as s:
                sent_any = False
                for arg in sys.argv[1:]:
                    cleaned = _clean_path_argument(arg)
                    if cleaned:
                        s.sendall((cleaned + "\n").encode("utf-8"))
                        sent_any = True
                if not sent_any:
                    try:
                        s.sendall(b"__ACTIVATE__\n")
                    except Exception:
                        pass
        except Exception:
            pass
        os._exit(0)

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
    security_tab:  PDFSecurityTab   | None = None
    settings_tab:  SettingsTab      | None = None
    pending_password_paths: list[str] = []

    doc_mgr = DocumentManagerUI(page)


    password_field = ft.TextField(
        label="Contraseña",
        password=True,
        can_reveal_password=True,
        autofocus=True,
        on_submit=lambda _: _confirm_password_open(),
    )
    password_error = ft.Text("", color="#D32F2F", size=12, visible=False)

    password_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("PDF protegido"),
        content=ft.Column([password_field, password_error], tight=True, spacing=8),
        actions_alignment=ft.MainAxisAlignment.END,
        actions=[],
    )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _show_error(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
        page.update()

    def _activate_window() -> None:
        try:
            page.window.minimized = False
            page.window.visible = True
            page.window.focused = True
            page.update()
            page.window.to_front()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

    def _fixed_count() -> int:
        """Number of 'system' tabs before the PDF viewer tabs."""
        n = 1  # home
        if extractor_tab is not None:
            n += 1
        if merge_tab is not None:
            n += 1
        if security_tab is not None:
            n += 1
        if settings_tab is not None:
            n += 1
        return n

    def _merge_tab_idx() -> int:
        return 1 + (1 if extractor_tab is not None else 0)

    def _security_tab_idx() -> int:
        return 1 + (1 if extractor_tab is not None else 0) + (1 if merge_tab is not None else 0)

    def _settings_tab_idx() -> int:
        return 1 + (1 if extractor_tab is not None else 0) + (1 if merge_tab is not None else 0) + (1 if security_tab is not None else 0)

    def _rebuild_tabs(selected_index: int | None = None) -> None:
        if selected_index is None:
            selected_index = doc_mgr.selected_index

        infos = [home.get_tab_info()]
        if extractor_tab is not None:
            infos.append(extractor_tab.get_tab_info())
        if merge_tab is not None:
            infos.append(merge_tab.get_tab_info())
        if security_tab is not None:
            infos.append(security_tab.get_tab_info())
        if settings_tab is not None:
            infos.append(settings_tab.get_tab_info())
        for v in open_tabs:
            infos.append(v.get_tab_info())

        doc_mgr.rebuild(infos, selected_index)

    # ── Abrir pdf ─────────────────────────────────────────────────────────────

    def _show_next_password_dialog(error_message: str | None = None) -> None:
        if not pending_password_paths:
            return
        current_path = pending_password_paths[0]
        password_field.value = ""
        password_error.value = error_message or ""
        password_error.visible = bool(error_message)
        password_dialog.title = ft.Text(f"PDF protegido: {Path(current_path).name}")
        page.open(password_dialog)

    def _enqueue_password_prompt(path: str) -> None:
        if path in pending_password_paths:
            return
        pending_password_paths.append(path)
        if len(pending_password_paths) == 1:
            _show_next_password_dialog()

    def _cancel_password_open() -> None:
        if pending_password_paths:
            pending_password_paths.pop(0)
        page.close(password_dialog)
        _show_next_password_dialog()

    def _confirm_password_open() -> None:
        if not pending_password_paths:
            page.close(password_dialog)
            return

        password = (password_field.value or "").strip()
        if not password:
            password_error.value = "Ingresa la contraseña"
            password_error.visible = True
            page.update()
            return

        target_path = pending_password_paths.pop(0)
        page.close(password_dialog)
        _open_pdf_path(target_path, password=password)
        _show_next_password_dialog()

    password_dialog.actions = [
        ft.TextButton("Cancelar", on_click=lambda _: _cancel_password_open()),
        ft.ElevatedButton("Abrir", icon=ft.Icons.LOCK_OPEN, on_click=lambda _: _confirm_password_open()),
    ]

    def _open_pdf_path(path: str, password: str | None = None) -> bool:
        for i, existing in enumerate(open_tabs):
            if existing.path == path:
                _rebuild_tabs(_fixed_count() + i)
                _activate_window()
                return True

        doc = None
        try:
            doc = PDFSecurityManager.open_for_viewer(path, password=password)
            viewer = PDFViewerTab(path, page, _close_viewer_tab, doc=doc)
        except PDFPasswordRequiredError:
            if doc is not None:
                doc.close()
            _enqueue_password_prompt(path)
            return False
        except PDFInvalidPasswordError:
            if doc is not None:
                doc.close()
            if path not in pending_password_paths:
                pending_password_paths.insert(0, path)
            _show_next_password_dialog("Contraseña incorrecta")
            return False
        except Exception as ex:
            if doc is not None:
                doc.close()
            _show_error(f"Error abriendo {Path(path).name}: {ex}")
            return False
        open_tabs.append(viewer)
        rf.push(path)
        home.refresh_recent()
        _rebuild_tabs(_fixed_count() + len(open_tabs) - 1)
        _activate_window()
        return True

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
            extractor_tab = PDFExtractionTab(page, _open_pdf_path, _close_extractor_tab, _open_security)
        _rebuild_tabs(1)

    def _close_extractor_tab(tab: PDFExtractionTab) -> None:
        nonlocal extractor_tab
        extractor_tab = None
        _rebuild_tabs(0)

    # ── merge tab ─────────────────────────────────────────────────────────────

    def _open_merge() -> None:
        nonlocal merge_tab
        if merge_tab is not None:
            _rebuild_tabs(_merge_tab_idx())
            return
        merge_tab = MergePDFTab(page, _close_merge_tab, _open_pdf_path, _open_security)
        _rebuild_tabs(_merge_tab_idx())

    def _close_merge_tab(tab: MergePDFTab) -> None:
        nonlocal merge_tab
        tab.close()
        merge_tab = None
        _rebuild_tabs(0)

    # ── security tab ──────────────────────────────────────────────────────────

    def _on_pdf_unlocked(path: str, password: str) -> None:
        """Callback when a PDF is unlocked in the security tab."""
        _open_pdf_path(path, password=password)

    def _open_security() -> None:
        nonlocal security_tab
        if security_tab is not None:
            _rebuild_tabs(_security_tab_idx())
            return
        security_tab = PDFSecurityTab(page, _on_pdf_unlocked, _close_security_tab)
        _rebuild_tabs(_security_tab_idx())

    def _close_security_tab(tab: PDFSecurityTab) -> None:
        nonlocal security_tab
        tab.close()
        security_tab = None
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
        for f in e.files:
            _open_pdf_path(f.path)

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
                _nav_btn(
                    ft.Icons.LOCK,
                    "Seguridad",
                    lambda e: _open_security(),
                    tooltip="Desbloquear PDFs protegidos",
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
        on_open_security=_open_security,
        on_open_pdf=_open_pdf_path,
    )

    body = ft.Column(
        [navbar, doc_mgr.control],
        expand=True,
        spacing=0,
    )

    _rebuild_tabs(0)
    page.add(body)

    # Watcher thread: espera señales del servidor IPC y programa el procesamiento
    # de rutas en el hilo de Flet usando page.run_task().
    def _incoming_watcher() -> None:
        while True:
            # Esperar hasta que haya algo nuevo
            _incoming_event.wait()
            try:
                # Procesamos las rutas en el hilo actual del watcher
                # Los cambios a la UI se sincronizan internamente en Flet
                _process_incoming_paths()
            except Exception:
                pass
            finally:
                _incoming_event.clear()

    # Procesar rutas recibidas desde otras instancias (single-instance IPC)
    def _process_incoming_paths() -> None:
        """Procesa rutas que llegan del IPC desde otras instancias.
        
        Esta función se ejecuta cuando:
        1. Hay nuevas rutas en _incoming_paths desde _ipc_server_loop()
        2. O al inicio, para procesar argumentos de línea de comandos
        """
        try:
            while True:
                with _incoming_lock:
                    if not _incoming_paths:
                        break
                    candidate = _incoming_paths.pop(0)
                if not candidate:
                    continue
                if candidate == "__ACTIVATE__":
                    _activate_window()
                    continue
                # Las rutas ya vienen limpias y validadas del IPC
                try:
                    _open_pdf_path(candidate)
                except Exception:
                    pass
        except Exception:
            pass

    threading.Thread(target=_incoming_watcher, daemon=True).start()

    # Procesar PDFs pasados como argumentos de línea de comandos (doble clic, "Abrir con", etc.)
    # Esto ocurre solo en la primera instancia; instancias secundarias envían por IPC y salen
    for arg in sys.argv[1:]:
        cleaned = _clean_path_argument(arg)
        if cleaned:
            # Agregar a la cola para procesamiento uniforme
            with _incoming_lock:
                _incoming_paths.append(cleaned)
    
    # Procesar las rutas iniciales (ya sea del IPC o de los argumentos)
    _process_incoming_paths()


ft.app(main)
