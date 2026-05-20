"""App entry point: navbar + home screen + tab shell + file picker.

IPC de instancia única implementado con socket TCP local + archivo de bloqueo.
Compatible con `flet build` (sin pywin32 ni dependencias nativas del SO).
"""

import sys
import os
import socket
import threading
import time
import tempfile
import struct
from pathlib import Path

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


# ---------------------------------------------------------------------------
# IPC: Instancia única  (socket TCP loopback + archivo de bloqueo)
# ---------------------------------------------------------------------------
# Estrategia:
#   1. Se elige un puerto fijo (configurable) en loopback.
#   2. La primera instancia logra hacer bind() en ese puerto → es el SERVIDOR.
#   3. Las instancias siguientes no pueden hacer bind() → son CLIENTES:
#      envían sus rutas PDF al servidor y terminan.
#   4. Un archivo de bloqueo en el directorio temporal del usuario guarda el
#      PID del servidor; se usa solo como señal de "hay proceso vivo", pero la
#      fuente de verdad es el bind del socket.
# ---------------------------------------------------------------------------

_IPC_PORT      = 57423          # Cambia si hay conflicto con otra app
_IPC_HOST      = "127.0.0.1"
_LOCK_FILENAME = "extrar_pdfs.lock"
_WEB_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "storage" / "temp"

_WEB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_incoming_paths: list[str] = []
_incoming_lock  = threading.Lock()
_incoming_event = threading.Event()
_ui_ready       = threading.Event()


def _lock_file_path() -> Path:
    return Path(tempfile.gettempdir()) / _LOCK_FILENAME


def _clean_path_argument(arg: str) -> str | None:
    """Limpia y valida un argumento de ruta desde línea de comandos.

    Elimina comillas, espacios extra y backticks. Verifica que sea un PDF
    existente y retorna la ruta absoluta resuelta, o None si es inválido.
    """
    clean = arg.strip(" \"'`")
    if not clean.lower().endswith(".pdf"):
        return None
    try:
        abs_path = Path(clean).resolve()
        if abs_path.exists():
            return str(abs_path)
    except Exception:
        pass
    return None


def _collect_initial_paths() -> list[str]:
    """Recolecta rutas PDF desde sys.argv (modo empaquetado Flet-compatible)."""
    paths: list[str] = []
    
    # En builds de Flet, los args propios de Flutter vienen primero.
    # Filtramos solo los que terminan en .pdf y existen en disco.
    for arg in sys.argv[1:]:
        # Flet/Flutter puede pasar args como --dart-entrypoint-args=ruta
        if "=" in arg:
            arg = arg.split("=", 1)[1]
        cleaned = _clean_path_argument(arg)
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
    
    # Fallback: variable de entorno (ya no es el método principal, pero se mantiene)
    env_val = os.environ.get("EXTRAR_PDF_PATH", "").strip()
    if env_val:
        for raw in env_val.split("|"):
            cleaned = _clean_path_argument(raw)
            if cleaned and cleaned not in paths:
                paths.append(cleaned)
    
    return paths


def _send_to_server(paths: list[str], retries: int = 8, delay: float = 0.4) -> bool:
    """Envía rutas al servidor con reintentos para cubrir el arranque lento.
    
    El servidor puede tardar varios segundos en estar listo (Flutter + Python).
    Con 8 reintentos × 0.4 s = hasta 3.2 s de espera total.
    """
    payload_lines = paths if paths else ["__ACTIVATE__"]
    payload = "\n".join(payload_lines)
    data = payload.encode("utf-8")
    header = struct.pack(">I", len(data))
    
    for attempt in range(retries):
        try:
            with socket.create_connection((_IPC_HOST, _IPC_PORT), timeout=2) as s:
                s.sendall(header + data)
            return True
        except OSError:
            if attempt < retries - 1:
                time.sleep(delay)
    return False


def _try_bind_server() -> socket.socket | None:
    """Intenta crear y vincular el socket servidor.

    Retorna el socket listo (listen) o None si el puerto ya está ocupado
    (lo que indica que hay otra instancia corriendo).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((_IPC_HOST, _IPC_PORT))
        sock.listen(10)
        return sock
    except OSError:
        sock.close()
        return None


def _write_lock_file() -> None:
    try:
        _lock_file_path().write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def _remove_lock_file() -> None:
    try:
        _lock_file_path().unlink(missing_ok=True)
    except Exception:
        pass


def _ipc_server_loop(server_sock: socket.socket) -> None:
    """Acepta conexiones entrantes y encola las rutas recibidas."""
    server_sock.settimeout(1.0)          # para poder salir limpio si se cierra
    while True:
        try:
            conn, _ = server_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break                        # socket cerrado: terminamos
        try:
            conn.settimeout(3.0)
            # Leer header de longitud (4 bytes big-endian)
            raw_len = _recv_exact(conn, 4)
            if raw_len is None:
                continue
            msg_len = struct.unpack(">I", raw_len)[0]
            if msg_len > 1_048_576:      # sanidad: máx 1 MB
                continue
            raw_body = _recv_exact(conn, msg_len)
            if raw_body is None:
                continue
            payload = raw_body.decode("utf-8", errors="ignore")
            with _incoming_lock:
                for line in payload.splitlines():
                    line = line.strip()
                    if line:
                        _incoming_paths.append(line)
            _incoming_event.set()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


def _recv_exact(conn: socket.socket, n: int) -> bytes | None:
    """Lee exactamente n bytes de conn; retorna None en caso de error/EOF."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
        except Exception:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ── Intento de convertirse en servidor ──────────────────────────────────────

_server_socket: socket.socket | None = _try_bind_server()

if _server_socket is None:
    # ── CLIENTE: ya hay una instancia corriendo ──────────────────────────────
    valid_paths = _collect_initial_paths()
    _send_to_server(valid_paths)
    os._exit(0)
else:
    # ── SERVIDOR: somos la primera instancia ────────────────────────────────
    _write_lock_file()

    _ipc_thread = threading.Thread(
        target=_ipc_server_loop,
        args=(_server_socket,),
        daemon=True,
        name="ipc-server",
    )
    _ipc_thread.start()

    # Encolar rutas iniciales (argv / env var) para la primera instancia
    for path in _collect_initial_paths():
        _incoming_paths.append(path)


# ---------------------------------------------------------------------------
# Constantes de UI
# ---------------------------------------------------------------------------

_NAVBAR_BG     = "#1E2A38"
_NAVBAR_FG     = "#FFFFFF"
_NAVBAR_FG_DIM = "#90A4AE"


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------

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

    # ── Diálogo de contraseña ────────────────────────────────────────────────

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
        """Trae la ventana al frente, desminimizando si es necesario."""
        try:
            page.window.minimized = False
            page.window.visible   = True
            page.window.focused   = True
            page.update()
            page.window.to_front()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

    def _fixed_count() -> int:
        """Número de pestañas 'sistema' antes de las pestañas de visor PDF."""
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
        return (
            1
            + (1 if extractor_tab is not None else 0)
            + (1 if merge_tab is not None else 0)
            + (1 if security_tab is not None else 0)
        )

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

    # ── Abrir PDF ─────────────────────────────────────────────────────────────

    def _show_next_password_dialog(error_message: str | None = None) -> None:
        if not pending_password_paths:
            return
        current_path = pending_password_paths[0]
        password_field.value   = ""
        password_error.value   = error_message or ""
        password_error.visible = bool(error_message)
        password_dialog.title  = ft.Text(f"PDF protegido: {Path(current_path).name}")
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
            password_error.value   = "Ingresa la contraseña"
            password_error.visible = True
            page.update()
            return

        target_path = pending_password_paths.pop(0)
        page.close(password_dialog)
        _open_pdf_path(target_path, password=password)
        _show_next_password_dialog()

    password_dialog.actions = [
        ft.TextButton("Cancelar", on_click=lambda _: _cancel_password_open()),
        ft.ElevatedButton(
            "Abrir",
            icon=ft.Icons.LOCK_OPEN,
            on_click=lambda _: _confirm_password_open(),
        ),
    ]

    def _open_pdf_path(path: str | None, password: str | None = None) -> bool:
        if not path:
            _show_error("No se recibió una ruta válida para el PDF seleccionado")
            return False

        pdf_name = Path(path).name

        # Si ya está abierto, cambiar a esa pestaña
        for i, existing in enumerate(open_tabs):
            if existing.path == path:
                _rebuild_tabs(_fixed_count() + i)
                _activate_window()
                return True

        doc = None
        try:
            doc    = PDFSecurityManager.open_for_viewer(path, password=password)
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
            _show_error(f"Error abriendo {pdf_name}: {ex}")
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

    # ── Pestaña extractor ─────────────────────────────────────────────────────

    def _open_extractor() -> None:
        nonlocal extractor_tab
        if extractor_tab is None:
            extractor_tab = PDFExtractionTab(
                page, _open_pdf_path, _close_extractor_tab, _open_security
            )
        _rebuild_tabs(1)

    def _close_extractor_tab(tab: PDFExtractionTab) -> None:
        nonlocal extractor_tab
        extractor_tab = None
        _rebuild_tabs(0)

    # ── Pestaña combinar ──────────────────────────────────────────────────────

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

    # ── Pestaña seguridad ─────────────────────────────────────────────────────

    def _on_pdf_unlocked(path: str, password: str) -> None:
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

    # ── Pestaña configuración ─────────────────────────────────────────────────

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

    # ── Cerrar pestaña visor ──────────────────────────────────────────────────

    def _close_viewer_tab(viewer: PDFViewerTab) -> None:
        idx = open_tabs.index(viewer)
        viewer.close()
        open_tabs.remove(viewer)
        fc = _fixed_count()
        if open_tabs:
            _rebuild_tabs(fc + min(idx, len(open_tabs) - 1))
        else:
            _rebuild_tabs(0)

    # ── Resultado del file picker ─────────────────────────────────────────────

    def _on_file_picked(e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        for f in e.files:
            if not f.path:
                _show_error(
                    f"No se pudo abrir {f.name}: en la versión web el archivo debe subirse primero"
                )
                continue
            _open_pdf_path(f.path)

    # ── Atajos de teclado ─────────────────────────────────────────────────────

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

    def _on_keyboard_up(e: ft.KeyboardEvent) -> None:
        for v in open_tabs:
            v._ctrl_pressed = e.ctrl

    # ── Navbar persistente ────────────────────────────────────────────────────

    def _nav_btn(icon: str, label: str, on_click, tooltip: str = "") -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=16, color=_NAVBAR_FG),
                    ft.Text(
                        label,
                        size=13,
                        color=_NAVBAR_FG,
                        weight=ft.FontWeight.W_500,
                    ),
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
                ft.Container(width=1, height=20, bgcolor=_NAVBAR_FG_DIM),
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

    # ── Wiring ────────────────────────────────────────────────────────────────

    file_picker = ft.FilePicker(on_result=_on_file_picked)
    page.overlay.append(file_picker)
    page.on_keyboard_event    = _on_keyboard
    if hasattr(page, "on_keyboard_event_up"):
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

    # ── Limpieza al cerrar la ventana ────────────────────────────────────────

    def _on_window_event(e: ft.WindowEvent) -> None:
        if e.type == ft.WindowEventType.CLOSE:
            _remove_lock_file()
            try:
                _server_socket.close()  # type: ignore[union-attr]
            except Exception:
                pass

    page.window.on_event = _on_window_event

    # ── Procesador de rutas entrantes (IPC + args iniciales) ─────────────────

    def _process_incoming_paths() -> None:
        """Desencola y abre PDFs recibidos por IPC o desde argv."""
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
            try:
                _open_pdf_path(candidate)
            except Exception:
                pass

    def _incoming_watcher() -> None:
        """Hilo daemon: espera el evento IPC y despacha al hilo de Flet."""
        while True:
            _incoming_event.wait()
            _incoming_event.clear()
            _ui_ready.wait()
            try:
                # page.run_task programa el callback en el event-loop de Flet
                page.run_task(_process_incoming_paths_async)
            except Exception:
                pass

    async def _process_incoming_paths_async() -> None:
        """Versión async de _process_incoming_paths para run_task."""
        _process_incoming_paths()

    threading.Thread(
        target=_incoming_watcher,
        daemon=True,
        name="ipc-watcher",
    ).start()

    _ui_ready.set()
    if _incoming_paths:
        _incoming_event.set()


ft.app(main, upload_dir=str(_WEB_UPLOAD_DIR))