"""App entry point: tab shell (con marca + menú integrados) + home screen + file picker.

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

# ── Logging diagnóstico ──────────────────────────────────────────────────────
# Escribe a %USERPROFILE%\.extraer_pdfs_debug.log para diagnosticar fallos en
# "Abrir con", IPC, parseo de argv post-instalación. Best-effort: nunca lanza
# excepciones. Truncado automático al pasar 1 MB.
_DBG_LOG_PATH = Path.home() / ".extraer_pdfs_debug.log"


def _dbg_log(msg: str) -> None:
    try:
        if _DBG_LOG_PATH.exists() and _DBG_LOG_PATH.stat().st_size > 1_048_576:
            _DBG_LOG_PATH.write_text("", encoding="utf-8")
        with _DBG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n")
    except Exception:
        pass


# Marcador de arranque: tan temprano como sea posible, antes de cualquier import
# pesado o lógica que pueda fallar silenciosamente.
_dbg_log("=" * 60)
_dbg_log(f"LAUNCH | sys.argv = {sys.argv!r}")
_dbg_log(f"LAUNCH | sys.executable = {sys.executable!r}")
_dbg_log(f"LAUNCH | cwd = {os.getcwd()!r}")
_dbg_log(f"LAUNCH | EXTRAR_PDF_PATH = {os.environ.get('EXTRAR_PDF_PATH', '')!r}")
_dbg_log(f"LAUNCH | platform = {sys.platform}")

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


def _win32_cmdline_args() -> list[str]:
    """Devuelve los argumentos reales del proceso en Windows vía Win32.

    En builds de `flet build windows`, el bootstrap de Flet/Flutter resetea
    sys.argv a [''] y se pierde la ruta del PDF que Windows pasa al hacer
    "Abrir con" (extraer_pdfs.exe "C:\\ruta\\archivo.pdf"). Sin embargo, la
    línea de comandos original del proceso sigue intacta a nivel del SO:
    GetCommandLineW la devuelve sin tocar y CommandLineToArgvW la divide
    respetando comillas. Best-effort: nunca lanza.
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        shell32  = ctypes.windll.shell32

        kernel32.GetCommandLineW.restype = wintypes.LPCWSTR
        cmd = kernel32.GetCommandLineW()

        shell32.CommandLineToArgvW.restype  = ctypes.POINTER(wintypes.LPWSTR)
        shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        argc = ctypes.c_int(0)
        argv = shell32.CommandLineToArgvW(cmd, ctypes.byref(argc))
        if not argv:
            return []
        try:
            args = [argv[i] for i in range(argc.value)]
        finally:
            kernel32.LocalFree(argv)
        _dbg_log(f"WIN32 | GetCommandLineW argv = {args!r}")
        return args[1:]  # descarta el nombre del exe
    except Exception as ex:
        _dbg_log(f"WIN32 | GetCommandLineW failed: {ex!r}")
        return []


def _collect_initial_paths() -> list[str]:
    """Recolecta rutas PDF desde la línea de comandos y la variable de entorno.

    Formatos soportados en builds de Flet empaquetado:
      - Ruta directa:    extraer_pdfs.exe "C:\\ruta\\archivo.pdf"
      - Con = :          --dart-entrypoint-args=C:\\ruta\\archivo.pdf
      - Con espacio:     --dart-entrypoint-args C:\\ruta\\archivo.pdf
    Los flags de Flutter/Dart (--dart-*, --observatory-*, etc.) se ignoran.

    En Windows se combinan sys.argv (que Flet suele dejar vacío) con la línea
    de comandos real del proceso (_win32_cmdline_args), porque "Abrir con" pasa
    la ruta a nivel del SO aunque no llegue a sys.argv.
    """
    paths: list[str] = []
    args = list(sys.argv[1:])
    for extra in _win32_cmdline_args():
        if extra not in args:
            args.append(extra)
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--dart-entrypoint-args="):
            candidate = arg[len("--dart-entrypoint-args="):]
            _dbg_log(f"ARGS  | matched --dart-entrypoint-args=, candidate = {candidate!r}")
        elif arg == "--dart-entrypoint-args" and i + 1 < len(args):
            i += 1
            candidate = args[i]
            _dbg_log(f"ARGS  | matched --dart-entrypoint-args <sep>, candidate = {candidate!r}")
        elif arg.startswith("--"):
            _dbg_log(f"ARGS  | skip flag {arg!r}")
            i += 1
            continue
        else:
            candidate = arg
            _dbg_log(f"ARGS  | direct arg, candidate = {candidate!r}")
        cleaned = _clean_path_argument(candidate)
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
            _dbg_log(f"ARGS  | accepted path = {cleaned!r}")
        elif candidate:
            _dbg_log(f"ARGS  | REJECTED candidate = {candidate!r} (no .pdf ext o no existe)")
        i += 1

    env_val = os.environ.get("EXTRAR_PDF_PATH", "").strip()
    if env_val:
        _dbg_log(f"ENV   | EXTRAR_PDF_PATH = {env_val!r}")
        for raw in env_val.split("|"):
            cleaned = _clean_path_argument(raw)
            if cleaned and cleaned not in paths:
                paths.append(cleaned)
                _dbg_log(f"ENV   | accepted path = {cleaned!r}")
            elif raw:
                _dbg_log(f"ENV   | REJECTED candidate = {raw!r}")

    _dbg_log(f"COLLECT | final paths = {paths!r}")
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
            _dbg_log(f"IPC   | send OK (attempt {attempt + 1}/{retries}), paths={paths!r}")
            return True
        except OSError as ex:
            _dbg_log(f"IPC   | send FAIL attempt {attempt + 1}/{retries}: {ex!r}")
            if attempt < retries - 1:
                time.sleep(delay)
    _dbg_log(f"IPC   | send GAVE UP after {retries} attempts")
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
        _dbg_log(f"BIND  | OK on {_IPC_HOST}:{_IPC_PORT} (we are PRIMARY)")
        return sock
    except OSError as ex:
        _dbg_log(f"BIND  | FAIL on {_IPC_HOST}:{_IPC_PORT}: {ex!r} (we are SECONDARY)")
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
            _dbg_log(f"IPC   | server recv payload = {payload!r}")
            if isinstance(payload, list):
                with _incoming_lock:
                    for item in payload:
                        if isinstance(item, str) and item.strip():
                            _incoming_paths.append(item.strip())
                _incoming_event.set()
        except Exception as ex:
            _dbg_log(f"IPC   | server recv ERROR: {ex!r}")
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
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
        _dbg_log("MAIN  | running as SECONDARY instance")
        page.window.visible = False
        page.update()
        initial_paths = _collect_initial_paths()
        _dbg_log(f"MAIN  | secondary forwarding {len(initial_paths)} path(s) and exiting")
        def _secondary_send_and_exit() -> None:
            ok = _send_to_server(initial_paths)
            _dbg_log(f"MAIN  | secondary IPC {'OK' if ok else 'FAILED — primary may not be running'}")
            os._exit(0)
        threading.Thread(
            target=_secondary_send_and_exit,
            daemon=True,
            name="ipc-secondary-exit",
        ).start()
        return

    # Somos la instancia principal.
    # Configurar ventana y mostrar pantalla de carga ANTES de cualquier import
    # pesado para que el usuario vea el logo en ~0.5 s en lugar de blanco.
    # El splash nativo (pyproject.toml [tool.flet.splash]) cubre el periodo
    # anterior (Flutter-level, antes de que Python conecte); este spinner cubre
    # el periodo de importación de módulos, visible tanto en flet run como en
    # el build final.
    page.title                 = "Extraer PDFs"
    page.theme_mode            = ft.ThemeMode.LIGHT
    page.padding               = 0
    page.window.icon           = "icon.png"
    page.window.prevent_close  = False  # se activa reactivamente al modificar un doc
    page.add(ft.Container(
        content=ft.Column(
            [
                ft.Image(
                    src="PM.png",
                    width=130,
                    height=130,
                    fit=ft.ImageFit.CONTAIN,
                ),
                ft.Container(height=18),
                ft.ProgressRing(width=36, height=36, stroke_width=3, color="#CC0000"),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=0,
        ),
        expand=True,
        alignment=ft.alignment.center,
        bgcolor=ft.Colors.WHITE,
    ))
    page.update()   # ← logo + spinner visible en ~0.5 s desde que abre la ventana

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
    help_tab      = None       # HelpTab | None
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
    password_error = ft.Text("", color="error", size=12, visible=False)

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
        except Exception as ex:
            _dbg_log(f"ACTIVATE | ERROR bringing window to front: {ex!r}")
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
        if help_tab is not None:
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

    def _help_tab_idx() -> int:
        return (
            1
            + (1 if extractor_tab is not None else 0)
            + (1 if merge_tab is not None else 0)
            + (1 if security_tab is not None else 0)
            + (1 if settings_tab is not None else 0)
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
        if help_tab is not None:
            infos.append(help_tab.get_tab_info())
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
        _dbg_log(f"OPEN  | _open_pdf_path called with path={path!r} pwd={'<set>' if password else None}")
        from pdf_security import (        # lazy — carga fitz solo al abrir un PDF
            PDFInvalidPasswordError,
            PDFPasswordRequiredError,
            PDFSecurityManager,
        )
        from pdf_viewer import PDFViewerTab  # lazy — carga fitz + onnxtr

        if not path:
            _dbg_log("OPEN  | ABORT: path is empty/None")
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
            _dbg_log(f"OPEN  | password required for {path!r}")
            _enqueue_password_prompt(path)
            return False
        except PDFInvalidPasswordError:
            if doc is not None:
                doc.close()
            _dbg_log(f"OPEN  | invalid password for {path!r}")
            if path not in pending_password_paths:
                pending_password_paths.insert(0, path)
            _show_next_password_dialog("Contraseña incorrecta")
            return False
        except Exception as ex:
            if doc is not None:
                doc.close()
            _dbg_log(f"OPEN  | ERROR opening {path!r}: {ex!r}")
            _show_error(f"Error abriendo {pdf_name}: {ex}")
            return False
        finally:
            _opening_now.discard(path)

        viewer.on_modified_changed = lambda _val: _update_prevent_close()
        open_tabs.append(viewer)
        rf.push(path)
        home.refresh_recent()
        _rebuild_tabs(_fixed_count() + len(open_tabs) - 1)
        _activate_window()
        _dbg_log(f"OPEN  | SUCCESS: {path!r}")
        return True

    def _open_picker() -> None:
        file_picker.pick_files(
            dialog_title="Abrir PDF",
            allowed_extensions=["pdf"],
            allow_multiple=True,
        )

    # Botón "+" de la barra de pestañas → abrir un PDF en una pestaña nueva.
    doc_mgr.on_new_tab = _open_picker

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

    # ── Pestaña ayuda ─────────────────────────────────────────────────────────

    def _open_help() -> None:
        nonlocal help_tab
        if help_tab is not None:
            _rebuild_tabs(_help_tab_idx())
            return
        from help_tab import HelpTab  # lazy
        help_tab = HelpTab(page, _close_help_tab)
        _rebuild_tabs(_help_tab_idx())

    def _close_help_tab(tab) -> None:
        nonlocal help_tab
        help_tab = None
        _rebuild_tabs(0)

    # ── Cerrar pestaña visor ──────────────────────────────────────────────────

    def _close_viewer_tab(viewer) -> None:
        idx = open_tabs.index(viewer)
        viewer.close()
        open_tabs.remove(viewer)
        _update_prevent_close()
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

    # Dedupe del auto-repeat de las teclas de zoom: una pulsación = un nivel.
    # Mientras la tecla se mantiene, el SO emite keydowns repetidos (~30 ms);
    # como Flet (esta versión) no expone keyup, no podemos saber el "release",
    # así que ignoramos repeticiones del mismo símbolo dentro de una ventana
    # (refrescando el timestamp → un hold completo cuenta como una sola pulsación).
    _zoom_rep = {"key": "", "t": 0.0}
    _ZOOM_REPEAT_GAP = 0.5  # seg

    def _zoom_key_accept(key: str) -> bool:
        now  = time.monotonic()
        same = (key == _zoom_rep["key"])
        gap  = now - _zoom_rep["t"]
        _zoom_rep["key"] = key
        _zoom_rep["t"]   = now
        return not (same and gap < _ZOOM_REPEAT_GAP)

    def _disarm_zoom_scroll() -> None:
        # Tras un atajo Ctrl+letra el usuario NO quería zoom. Como Flet no emite
        # keyup en esta versión, _ctrl_pressed quedaría "pegado" en True y un
        # scroll inmediato con la rueda haría zoom por error (Ctrl+rueda). Lo
        # desarmamos explícitamente; el próximo keydown de Ctrl lo re-arma.
        for v in open_tabs:
            v._ctrl_pressed = False
            v._ctrl_time = 0.0

    def _on_keyboard(e: ft.KeyboardEvent) -> None:
        # NOTA: si agregas/cambias un atajo aquí, actualiza también la lista que
        # se muestra al usuario en settings_tab.py → _KEYBOARD_SHORTCUTS.
        t = time.monotonic()
        # Armar el zoom Ctrl+rueda mientras Ctrl esté presionado.
        for v in open_tabs:
            v._ctrl_pressed = e.ctrl
            if e.ctrl:
                v._ctrl_time = t

        if e.ctrl and (e.key or "").upper() == "O":
            _disarm_zoom_scroll()
            _open_picker()
            return
        if not open_tabs:
            return
        idx = doc_mgr.selected_index - _fixed_count()
        if not (0 <= idx < len(open_tabs)):
            return
        v = open_tabs[idx]

        # ── Ctrl + tecla ───────────────────────────────────────────────────────
        if e.ctrl:
            _key = e.key or ""
            _kl  = _key.lower()
            # Zoom: Ctrl con '+'/'=' (acercar), '-' (alejar), '0' (100%).
            # Flet/Flutter puede reportar estas teclas de varias formas según el
            # layout y el numpad (carácter directo, o nombre lógico como "Add",
            # "Subtract", "Equal", "Minus", "Numpad Add"…). Cubrimos todas.
            # Una vez por pulsación (no mientras se mantiene), vía _zoom_key_accept.
            _is_plus  = _key in ("+", "=") or "add" in _kl or "plus" in _kl or _kl == "equal"
            _is_minus = _key in ("-", "_") or "subtract" in _kl or "minus" in _kl
            _is_zero  = _key == "0" or _kl in ("numpad 0", "num 0", "digit 0")
            if _is_plus:
                if _zoom_key_accept("+"):
                    v._zoom_in()
                _disarm_zoom_scroll()  # un scroll posterior debe ser scroll, no zoom
                return
            if _is_minus:
                if _zoom_key_accept("-"):
                    v._zoom_out()
                _disarm_zoom_scroll()
                return
            if _is_zero:
                if _zoom_key_accept("0"):
                    v._set_zoom(1.0)
                _disarm_zoom_scroll()
                return

            # Modificador sostenido (Ctrl/Shift/Alt/Meta): mantener armado el
            # zoom Ctrl+rueda — NO desarmar ni tratar como atajo.
            if _key and any(m in _key for m in ("Control", "Shift", "Alt", "Meta")):
                return

            # Resto de atajos Ctrl+letra: NO son zoom → desarmar el zoom-rueda.
            _disarm_zoom_scroll()
            k = (e.key or "").upper()
            if k == "Z":
                if getattr(e, "shift", False):
                    v._redo()      # Ctrl+Shift+Z
                else:
                    v._undo()      # Ctrl+Z
                return
            if k == "Y":
                v._redo(); return  # Ctrl+Y
            if k == "D":
                v._duplicate_selected(); return  # Ctrl+D: duplicar anotación
            if k == "A":
                v._select_all_page_text(); return
            if k == "S":
                v._save(); return
            if k == "P":
                v._print_pdf(); return
            if k == "F":
                v._open_search(); return  # Ctrl+F: buscar texto
            if k == "H":
                v._fit_page(); return    # Ctrl+H: ajustar a la página
            if k == "W":
                v._fit_width(); return  # Ctrl+W: ajustar al ancho
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
        # El zoom YA NO se activa con '+'/'-' a secas: requiere Ctrl (arriba),
        # como en un visor típico, para no dispararse por accidente.
        match e.key:
            case "Escape":
                v._deselect_annot()
                v._hide_text_sel_bar()
            case "Delete":
                v._delete_selected()
            case "Arrow Up" | "Page Up":
                v._prev()
            case "Arrow Down" | "Page Down":
                v._next()
            case "Home":
                v._scroll_to_page(0)
            case "End":
                v._scroll_to_page(len(v.doc) - 1)

    def _on_keyboard_up(e: ft.KeyboardEvent) -> None:
        # Cuando el propio Ctrl se suelta, e.ctrl puede seguir siendo True en
        # algunas plataformas. Forzar el reset cuando la tecla es "Control".
        released_ctrl = "Control" in (e.key or "")
        for v in open_tabs:
            v._ctrl_pressed = False if released_ctrl else e.ctrl

    # ── Marca + menú de la app (vive en la barra de pestañas) ───────────────────
    # Antes esto era una barra superior propia; ahora el nombre/ícono quedan fijos
    # a la izquierda de las pestañas y sus acciones se despliegan desde un menú.
    app_menu = ft.PopupMenuButton(
        icon=ft.Icons.MENU,
        tooltip="Menú de la aplicación",
        items=[
            ft.PopupMenuItem(
                text="Abrir PDF", icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                on_click=lambda e: _open_picker(),
            ),
            ft.PopupMenuItem(
                text="Extraer texto", icon=ft.Icons.FIND_IN_PAGE_OUTLINED,
                on_click=lambda e: _open_extractor(),
            ),
            ft.PopupMenuItem(
                text="Combinar PDFs", icon=ft.Icons.MERGE_TYPE,
                on_click=lambda e: _open_merge(),
            ),
            ft.PopupMenuItem(
                text="Seguridad", icon=ft.Icons.LOCK,
                on_click=lambda e: _open_security(),
            ),
            ft.PopupMenuItem(),  # divisor
            ft.PopupMenuItem(
                text="Configuración", icon=ft.Icons.SETTINGS_OUTLINED,
                on_click=lambda e: _open_settings(),
            ),
            ft.PopupMenuItem(
                text="Ayuda", icon=ft.Icons.HELP_OUTLINE,
                on_click=lambda e: _open_help(),
            ),
        ],
    )
    app_brand = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.PICTURE_AS_PDF, size=20, color="#EF5350"),
                ft.Text(
                    "Extraer PDFs",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color="onSurface",
                ),
                app_menu,
            ],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.only(left=10, right=4),
    )
    doc_mgr.set_leading(app_brand)

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

    body = doc_mgr.control

    _rebuild_tabs(0)
    page.controls.clear()   # remueve el spinner
    page.add(body)

    # ── Limpieza al cerrar la ventana ────────────────────────────────────────

    def _update_prevent_close() -> None:
        """Activa prevent_close solo si hay documentos con cambios sin guardar.

        Con prevent_close=False la ventana se cierra sin round-trip a Python,
        lo que elimina el retardo perceptible al cerrar cuando no hay nada
        que proteger.  Se llama reactivamente desde el setter de _is_modified
        en cada PDFViewerTab, y tambien al cerrar o guardar cualquier tab.
        También refresca las etiquetas de pestañas para mostrar/ocultar el
        indicador ● de cambios sin guardar.
        """
        has_unsaved = any(getattr(v, "_is_modified", False) for v in open_tabs)
        if page.window.prevent_close != has_unsaved:
            page.window.prevent_close = has_unsaved
        # Refrescar solo el texto de las etiquetas de pestañas (indicador ●).
        # Se usa refresh_viewer_labels() en lugar de _rebuild_tabs() para no
        # interrumpir el render en curso con un page.update() extra completo.
        try:
            doc_mgr.refresh_viewer_labels()
        except Exception:
            pass

    def _do_close_app() -> None:
        """Cierra el socket IPC y destruye la ventana."""
        # threading.Timer es un hilo no-daemon: Python espera a que todos
        # terminen antes de salir. Los viewers tienen timers con delays de
        # hasta 20 s (_suspend_timer) y 1.4 s (_vbar_hide_timer) que, si
        # están activos al cerrar, bloquean el proceso y muestran el cursor
        # de carga. Los cancelamos aquí antes de destroy() para salir limpio.
        _VIEWER_TIMERS = (
            "_scroll_idle_timer", "_zoom_timer", "_render_upd_timer",
            "_restore_scroll_timer", "_single_nav_timer", "_vbar_hide_timer",
            "_suspend_timer", "_ocr_model_timer", "_orient_model_timer",
        )
        for _v in open_tabs:
            try:
                _v._render_gen += 1
                _v._is_closed = True  # evita que callbacks tardíos toquen la UI
            except Exception:
                pass
            for _attr in _VIEWER_TIMERS:
                _t = getattr(_v, _attr, None)
                if _t is not None:
                    try:
                        _t.cancel()
                    except Exception:
                        pass
        try:
            server_sock.close()
        except Exception:
            pass
        page.window.destroy()

    def _on_window_event(e: ft.WindowEvent) -> None:
        if e.type != ft.WindowEventType.CLOSE:
            return
        
        import threading
        import time
        import os

        # Chequeo instantáneo
        unsaved = [
            v for v in open_tabs
            if getattr(v, "_is_modified", False)
        ]
        
        def _execute_clean_exit():
            """Secuencia coordinada para evitar el colapso de la ventana y el deadlock."""
            # 1. Quitamos el seguro contra cierres
            page.window.prevent_close = False
            
            # 2. Le decimos a Flet que destruya la ventana limpiamente
            try:
                page.update()
                page.window.destroy()
            except Exception:
                pass
                
            # 3. Matamos Python desde un hilo secundario tras un breve retraso (100ms).
            # Esto le da tiempo al websocket de entregar el comando "destroy" a la UI.
            def _kill():
                time.sleep(0.1)
                os._exit(0)
                
            threading.Thread(target=_kill, daemon=True).start()

        if not unsaved:
            _execute_clean_exit()
            return

        names = "\n".join(f"  • {v.filename}" for v in unsaved)

        def _cancel(ev=None):
            page.close(dlg)

        def _force_close(ev=None):
            # Cerramos el diálogo primero para que no haya errores de UI
            try:
                page.close(dlg)
            except Exception:
                pass
            
            # Ejecutamos nuestra secuencia limpia de salida
            _execute_clean_exit()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Archivos sin guardar"),
            content=ft.Text(
                f"Los siguientes documentos tienen cambios sin guardar:\n\n{names}\n\n"
                "Si cierras ahora perderás esos cambios.",
                size=13,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=_cancel),
                ft.FilledButton(
                    "Cerrar sin guardar",
                    style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR),
                    on_click=_force_close,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)

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
                _dbg_log("QUEUE | __ACTIVATE__ marker — bringing window to front")
                _activate_window()
                continue
            _dbg_log(f"QUEUE | dequeued {candidate!r}, calling _open_pdf_path")
            try:
                _open_pdf_path(candidate)
            except Exception as ex:
                _dbg_log(f"QUEUE | _open_pdf_path raised: {ex!r}")

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