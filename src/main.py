"""App entry point: navbar + home screen + tab shell + file picker.

IPC de instancia única via TCP loopback.

PROBLEMA RAÍZ en flet build windows:
  Flutter crea y muestra la ventana ANTES de que Python corra.
  Cualquier chequeo a nivel de módulo (os._exit) mata el proceso
  pero la ventana ya estaba visible → ventana huérfana persistente.

SOLUCIÓN: el chequeo de instancia única ocurre DENTRO de main(page),
  donde ya tenemos acceso a page.window.visible para ocultar la ventana
  antes de que el usuario la vea y cerrarla limpiamente.
"""

from __future__ import annotations

import sys
import os
import json
import socket
import struct
import threading
import time
import tempfile
from pathlib import Path

import flet as ft

# Los módulos de características (pdf_viewer, pdf_extractor, pdf_merge,
# pdf_security, settings_tab) se importan de forma lazy dentro de main()
# o dentro de las funciones que los usan. Esto hace que:
#   · La instancia secundaria ("Abrir con") salga en milisegundos
#     antes de que el usuario vea la ventana en blanco.
#   · La instancia primaria muestre el home rápidamente.
# recent_files, document_manager_ui y home se importan dentro de main()
# después del check de instancia única, por la misma razón.


_IPC_PORT = 57423          # Puerto fijo; cambia si hay conflicto con otra app
_IPC_HOST = "127.0.0.1"

_WEB_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "storage" / "temp"

try:
    _WEB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    # Fallback seguro si está en C:\Program Files y no hay permisos de admin
    _WEB_UPLOAD_DIR = Path(tempfile.gettempdir()) / "extrar_pdfs_upload"
    _WEB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_incoming_paths: list[str] = []
_incoming_lock  = threading.Lock()
_incoming_event = threading.Event()
_ui_ready       = threading.Event()


def _clean_path_argument(arg: str) -> str | None:
    """Limpia y valida una posible ruta PDF.

    Elimina comillas, espacios extra y backticks. Verifica que sea un PDF
    existente y retorna la ruta absoluta resuelta, o None si es inválido.
    """
    clean = arg.strip(" \"'`\r\n")
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
    """Recolecta rutas PDF desde sys.argv y variable de entorno.

    Formatos soportados en builds de Flet empaquetado:
      - Ruta directa:    extraer_pdfs.exe "C:\\ruta\\archivo.pdf"
      - Con = :          --dart-entrypoint-args=C:\\ruta\\archivo.pdf
      - Con espacio:     --dart-entrypoint-args C:\\ruta\\archivo.pdf
    Los flags de Flutter/Dart (--dart-*, --observatory-*, etc.) se ignoran.
    """
    paths: list[str] = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--dart-entrypoint-args="):
            candidate = arg[len("--dart-entrypoint-args="):]
        elif arg == "--dart-entrypoint-args" and i + 1 < len(args):
            i += 1
            candidate = args[i]
        elif arg.startswith("--"):
            i += 1
            continue
        else:
            candidate = arg
        cleaned = _clean_path_argument(candidate)
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
        i += 1

    env_val = os.environ.get("EXTRAR_PDF_PATH", "").strip()
    if env_val:
        for raw in env_val.split("|"):
            cleaned = _clean_path_argument(raw)
            if cleaned and cleaned not in paths:
                paths.append(cleaned)

    return paths


def _recv_exact(conn: socket.socket, n: int) -> bytes | None:
    """Lee exactamente n bytes del socket; retorna None en EOF o error."""
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


def _send_to_server(paths: list[str], retries: int = 5, delay: float = 0.35) -> bool:
    """Envía rutas al servidor con reintentos para cubrir el arranque lento.

    5 reintentos × 0.35 s = hasta 1.75 s de espera total.
    Para la app ya abierta conecta en el primer intento (< 5 ms).
    """
    payload = json.dumps(paths if paths else ["__ACTIVATE__"]).encode("utf-8")
    header = struct.pack(">I", len(payload))

    for attempt in range(retries):
        try:
            with socket.create_connection((_IPC_HOST, _IPC_PORT), timeout=2) as s:
                s.sendall(header + payload)
            return True
        except OSError:
            if attempt < retries - 1:
                time.sleep(delay)
    return False


def _try_bind_server() -> socket.socket | None:
    """Intenta hacer bind del servidor IPC.

    En Windows usa SO_EXCLUSIVEADDRUSE en lugar de SO_REUSEADDR.
    SO_REUSEADDR en Windows permite que múltiples procesos hagan bind
    en el mismo puerto (a diferencia de Linux donde falla correctamente).
    SO_EXCLUSIVEADDRUSE garantiza que bind() falle si ya hay otra instancia.

    Retorna el socket listo (listen) o None si ya hay otra instancia.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            # Constante 2752 (0xAC0) — no siempre exportada en socket.*
            _SO_EXCL = getattr(socket, "SO_EXCLUSIVEADDRUSE", 2752)
            sock.setsockopt(socket.SOL_SOCKET, _SO_EXCL, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((_IPC_HOST, _IPC_PORT))
        sock.listen(10)
        return sock
    except OSError:
        sock.close()
        return None


def _ipc_server_loop(server_sock: socket.socket) -> None:
    """Acepta conexiones entrantes y encola las rutas recibidas."""
    server_sock.settimeout(1.0)
    while True:
        try:
            conn, _ = server_sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            conn.settimeout(3.0)
            raw_len = _recv_exact(conn, 4)
            if raw_len is None:
                continue
            msg_len = struct.unpack(">I", raw_len)[0]
            if msg_len > 1_048_576:      # sanidad: máx 1 MB
                continue
            raw_body = _recv_exact(conn, msg_len)
            if raw_body is None:
                continue
            payload = json.loads(raw_body.decode("utf-8"))
            if isinstance(payload, list):
                with _incoming_lock:
                    for item in payload:
                        if isinstance(item, str) and item.strip():
                            _incoming_paths.append(item.strip())
                _incoming_event.set()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


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
    # ── Instancia única: primer acto antes de cualquier UI ───────────────────
    # Aquí (dentro de main) ya tenemos page.window para ocultar la ventana
    # si somos una instancia secundaria, evitando la ventana huérfana.
    server_sock = _try_bind_server()

    if server_sock is None:
        # Somos una instancia secundaria. Ocultar la ventana antes de que el
        # usuario la vea, reenviar rutas a la instancia principal y salir.
        page.window.visible = False
        page.update()
        initial_paths = _collect_initial_paths()
        threading.Thread(
            target=lambda: (_send_to_server(initial_paths), os._exit(0)),
            daemon=True,
            name="ipc-secondary-exit",
        ).start()
        return

    # Somos la instancia principal.
    # Configurar ventana y mostrar spinner ANTES de cualquier import pesado
    # para que el usuario vea contenido en ~0.5 s en lugar de blanco.
    page.title       = "Extraer PDFs"
    page.theme_mode  = ft.ThemeMode.LIGHT
    page.padding     = 0
    page.window.icon = "icon.png"
    page.add(ft.Container(
        content=ft.Column(
            [ft.ProgressRing(width=44, height=44, stroke_width=3, color="#1E2A38")],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        alignment=ft.alignment.center,
        bgcolor=ft.Colors.WHITE,
    ))
    page.update()   # ← spinner visible en ~0.5 s desde que abre la ventana

    # Importar módulos de la app DESPUÉS del spinner para no bloquear la UI.
    # Las instancias secundarias salen antes de llegar aquí.
    import recent_files as rf
    from document_manager_ui import DocumentManagerUI
    from home import HomePage

    _ipc_thread = threading.Thread(
        target=_ipc_server_loop,
        args=(server_sock,),
        daemon=True,
        name="ipc-server",
    )
    _ipc_thread.start()
    _incoming_paths.extend(_collect_initial_paths())

    # ─────────────────────────────────────────────────────────────────────────

    open_tabs:     list = []   # list[PDFViewerTab]
    extractor_tab = None       # PDFExtractionTab | None
    merge_tab     = None       # MergePDFTab | None
    security_tab  = None       # PDFSecurityTab | None
    settings_tab  = None       # SettingsTab | None
    pending_password_paths: list[str] = []
    _opening_now:  set  = set()  # paths being opened; prevents double-open

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
        from pdf_security import (        # lazy — carga fitz solo al abrir un PDF
            PDFInvalidPasswordError,
            PDFPasswordRequiredError,
            PDFSecurityManager,
        )
        from pdf_viewer import PDFViewerTab  # lazy — carga fitz + onnxtr

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

        # Evitar doble-apertura por doble-clic o clics rápidos repetidos
        if path in _opening_now:
            return True
        _opening_now.add(path)

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
        finally:
            _opening_now.discard(path)

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
            from pdf_extractor import PDFExtractionTab  # lazy
            extractor_tab = PDFExtractionTab(
                page, _open_pdf_path, _close_extractor_tab, _open_security
            )
        _rebuild_tabs(1)

    def _close_extractor_tab(tab) -> None:
        nonlocal extractor_tab
        extractor_tab = None
        _rebuild_tabs(0)

    # ── Pestaña combinar ──────────────────────────────────────────────────────

    def _open_merge() -> None:
        nonlocal merge_tab
        if merge_tab is not None:
            _rebuild_tabs(_merge_tab_idx())
            return
        from pdf_merge import MergePDFTab  # lazy
        merge_tab = MergePDFTab(page, _close_merge_tab, _open_pdf_path, _open_security)
        _rebuild_tabs(_merge_tab_idx())

    def _close_merge_tab(tab) -> None:
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
        from pdf_security import PDFSecurityTab  # lazy
        security_tab = PDFSecurityTab(page, _on_pdf_unlocked, _close_security_tab)
        _rebuild_tabs(_security_tab_idx())

    def _close_security_tab(tab) -> None:
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
        from settings_tab import SettingsTab  # lazy
        settings_tab = SettingsTab(page, _close_settings_tab)
        _rebuild_tabs(_settings_tab_idx())

    def _close_settings_tab(tab) -> None:
        nonlocal settings_tab
        settings_tab = None
        _rebuild_tabs(0)

    # ── Cerrar pestaña visor ──────────────────────────────────────────────────

    def _close_viewer_tab(viewer) -> None:
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
        t = time.monotonic()
        for v in open_tabs:
            v._ctrl_pressed = e.ctrl
            if e.ctrl:
                v._ctrl_time = t
        if e.ctrl and e.key.upper() == "O":
            _open_picker()
            return
        if not open_tabs:
            return
        idx = doc_mgr.selected_index - _fixed_count()
        if not (0 <= idx < len(open_tabs)):
            return
        v = open_tabs[idx]

        # ── Ctrl + key ────────────────────────────────────────────────────────
        if e.ctrl:
            k = e.key.upper()
            if k == "Z":
                v._undo(); return
            if k == "A":
                v._select_all_page_text(); return
            if k == "S":
                v._save(); return
            if k == "P":
                v._print_pdf(); return
            if k == "C":
                if getattr(v, "_text_sel_text", ""):
                    v._text_sel_copy()
                return
            if e.key == "Home":
                v._scroll_to_page(0); return
            if e.key == "End":
                v._scroll_to_page(len(v.doc) - 1); return
            return

        # ── Sin modificador ───────────────────────────────────────────────────
        match e.key:
            case "Escape":
                v._deselect_annot()
                v._hide_text_sel_bar()
            case "Arrow Left" | "Arrow Up" | "Page Up":
                v._prev()
            case "Arrow Right" | "Arrow Down" | "Page Down":
                v._next()
            case "Home":
                v._scroll_to_page(0)
            case "End":
                v._scroll_to_page(len(v.doc) - 1)
            case "+" | "=":
                v._zoom_in()
            case "-":
                v._zoom_out()
            case "w" | "W":
                v._fit_width()
            case "f" | "F":
                v._fit_page()

    def _on_keyboard_up(e: ft.KeyboardEvent) -> None:
        # Cuando el propio Ctrl se suelta, e.ctrl puede seguir siendo True en
        # algunas plataformas. Forzar el reset cuando la tecla es "Control".
        released_ctrl = "Control" in (e.key or "")
        for v in open_tabs:
            v._ctrl_pressed = False if released_ctrl else e.ctrl

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
    page.controls.clear()   # remueve el spinner
    page.add(body)

    # ── Limpieza al cerrar la ventana ────────────────────────────────────────

    def _on_window_event(e: ft.WindowEvent) -> None:
        if e.type == ft.WindowEventType.CLOSE:
            try:
                server_sock.close()
            except Exception:
                pass

    page.window.on_event = _on_window_event

    # ── Procesador de rutas entrantes (IPC + args iniciales) ─────────────────

    async def _process_incoming_paths() -> None:
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
                page.run_task(_process_incoming_paths)
            except Exception:
                pass

    threading.Thread(
        target=_incoming_watcher,
        daemon=True,
        name="ipc-watcher",
    ).start()

    _ui_ready.set()
    if _incoming_paths:
        _incoming_event.set()

    # Pre-calentar imports pesados en background para que el primer PDF abra rápido
    def _prewarm() -> None:
        try:
            import pdf_viewer    # noqa: F401
            import pdf_security  # noqa: F401
        except Exception:
            pass
    threading.Thread(target=_prewarm, daemon=True, name="prewarm").start()


ft.app(main, upload_dir=str(_WEB_UPLOAD_DIR))