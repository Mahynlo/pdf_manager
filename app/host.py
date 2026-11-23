"""Implementación de :class:`app.backend.host.Host` sobre una ventana pywebview (WebView2 en Windows)."""

from __future__ import annotations

import ctypes
import itertools
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

from app.backend.host import is_external_url
from app.backend.services.app_service import QUIT_REQUESTED
from app.backend.services.documents import IMAGE_SUFFIXES, is_image
from app.byte_server import ByteServer

log = logging.getLogger(__name__)

ENGINE_TASK = "engine:task"
ENGINE_TIMEOUT = 300  # segundos
PDF_TYPES = ("Archivos PDF (*.pdf)",)
_IMAGES = ";".join(f"*{suffix}" for suffix in IMAGE_SUFFIXES)
DOCUMENT_TYPES = (f"PDF e imágenes (*.pdf;{_IMAGES})", *PDF_TYPES, f"Imágenes ({_IMAGES})")
TEXT_TYPES = ("Archivos de Texto (*.txt)",)
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


# Lo que el menú de WebView2 trae de navegador y en la app sobra (nombres de CoreWebView2ContextMenuItem).
_BROWSER_MENU_ITEMS = frozenset({
    "back", "forward", "reload", "saveAs", "print", "createQrCode", "share", "webCapture", "inspectElement",
    "openLinkInNewWindow", "copyLinkLocation", "saveLinkAs", "copyLinkToHighlight", "openImageInNewWindow",
    "saveImageAs", "copyImageLocation", "saveMediaAs", "loop", "showAllControls", "readAloud", "translate",
    "openInDefaultBrowser", "moreTools", "other",
})


def _filter_menu(args: Any) -> None:
    """``ContextMenuRequested``: menú solo en campos de texto o sobre texto seleccionado, y sin lo de navegador."""
    try:
        target = args.ContextMenuTarget
        if not (target.IsEditable or target.HasSelection):
            args.Handled = True  # sin menú
            return
        items = args.MenuItems
        for i in range(items.Count - 1, -1, -1):
            if items[i].Name in _BROWSER_MENU_ITEMS:
                items.RemoveAt(i)
        # Sin separadores al principio, al final ni dos seguidos (los de lo que se quitó).
        for i in range(items.Count - 1, -1, -1):
            separator = str(items[i].Kind) == "Separator"
            if separator and (i == 0 or i == items.Count - 1 or str(items[i - 1].Kind) == "Separator"):
                items.RemoveAt(i)
        log.debug("Menú del botón derecho: %s", [items[i].Name for i in range(items.Count)])
    except Exception:
        log.debug("No se pudo filtrar el menú del botón derecho", exc_info=True)


def _enable_native_menus() -> None:
    """El menú del botón derecho de WebView2 donde sirve: en los campos de texto (las sugerencias
    del corrector, cortar, copiar, pegar) y sobre texto seleccionado (copiar). En el resto de la
    ventana sigue sin salir, y los menús propios (pestañas, recientes, visor) no cambian: cancelan
    el del navegador.

    pywebview lo quita fuera de ``--debug`` al crear WebView2, y el ajuste solo vale desde la
    siguiente navegación (la app es una sola página: no vuelve a navegar). Por eso se activa justo
    antes de cargar la página, envolviendo ``EdgeChrome.load_url`` (pywebview 6.2: lo llama después
    de poner sus ajustes). Revisarlo al actualizar pywebview. Solo WebView2."""
    if os.name != "nt":
        return
    try:
        from webview.platforms import edgechromium
    except Exception:
        log.debug("Sin WebView2: no se activa el menú del botón derecho", exc_info=True)
        return
    original = edgechromium.EdgeChrome.load_url
    if getattr(original, "native_menus", False):
        return

    def load_url(browser: Any, url: str) -> None:
        try:
            core = browser.webview.CoreWebView2
            core.Settings.AreDefaultContextMenusEnabled = True
            if not getattr(browser, "menu_filtered", False):
                core.ContextMenuRequested += lambda _sender, args: _filter_menu(args)
                browser.menu_filtered = True
        except Exception:
            log.debug("No se pudo activar el menú del botón derecho de WebView2", exc_info=True)
        original(browser, url)

    load_url.native_menus = True  # type: ignore[attr-defined]
    edgechromium.EdgeChrome.load_url = load_url


class WebviewHost:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._close_blocker: Callable[[], Any] | None = None
        self._on_drop_files: Callable[[list[str]], Any] | None = None
        self._quitting = False
        self._bytes = ByteServer()  # datos grandes con el frontend (ver share_bytes y upload_url)
        self._task_ids = itertools.count(1)
        self._tasks: dict[int, Future[str | None]] = {}  # tareas de run_engine en curso

    def attach(
        self,
        window: webview.Window,
        close_blocker: Callable[[], Any] | None = None,
        on_drop_files: Callable[[list[str]], Any] | None = None,
    ) -> None:
        """``close_blocker`` devuelve ``None`` si la ventana puede cerrarse, o los datos del
        evento ``QUIT_REQUESTED`` con los que el frontend pregunta antes de salir.
        ``on_drop_files`` recibe las rutas de los PDF e imágenes arrastrados a la ventana."""
        self._window = window
        self._close_blocker = close_blocker
        self._on_drop_files = on_drop_files
        window.events.closing += self._on_closing
        window.events.minimized += lambda: self._memory_target(low=True)
        window.events.restored += lambda: self._memory_target(low=False)
        window.events.maximized += lambda: self._memory_target(low=False)
        _enable_native_menus()
        if on_drop_files is not None:
            window.events.loaded += self._listen_drops

    def _memory_target(self, low: bool) -> None:
        """Con la ventana minimizada, WebView2 suelta la memoria que puede (cachés de imágenes y
        del motor de JavaScript) y vuelve a trabajar normal al restaurarla. Solo WebView2."""
        if os.name != "nt":
            return
        try:
            from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel as Level
            from System import Action

            form = self.window.native
            level = Level.Low if low else Level.Normal

            def apply() -> None:  # en el hilo de la ventana, como pide WebView2
                form.browser.webview.CoreWebView2.MemoryUsageTargetLevel = level

            form.Invoke(Action(apply))
        except Exception:
            log.debug("No se pudo cambiar el uso de memoria de WebView2", exc_info=True)

    def _listen_drops(self) -> None:
        # El navegador no da la ruta de un archivo soltado; pywebview la añade al evento
        # (``pywebviewFullPath``) solo si el «drop» se escucha desde Python.
        self.window.dom.document.events.drop += DOMEventHandler(self._on_drop, prevent_default=True)

    def _on_drop(self, event: dict[str, Any]) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files]
        found = [p for p in paths if p and (p.lower().endswith(".pdf") or is_image(p)) and Path(p).is_file()]
        if found and self._on_drop_files is not None:
            self._on_drop_files(found)

    def _on_closing(self) -> bool:
        if self._quitting or self._close_blocker is None:
            return True
        payload = self._close_blocker()
        if payload is None:
            return True
        # El cierre llega en el hilo de la interfaz y run_js esperaría a ese mismo
        # hilo: el evento se envía desde otro.
        threading.Thread(target=self.emit, args=(QUIT_REQUESTED, payload), daemon=True).start()
        return False

    @property
    def window(self) -> webview.Window:
        if self._window is None:
            raise RuntimeError("La ventana aún no existe")
        return self._window

    # ── Diálogos ─────────────────────────────────────────────────────────────
    def pick_pdfs(self) -> list[str]:
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=PDF_TYPES)
        return list(result or [])

    def pick_documents(self) -> list[str]:
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=DOCUMENT_TYPES)
        return list(result or [])

    def pick_pdf(self) -> str | None:
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=PDF_TYPES)
        return result[0] if result else None

    def pick_folder(self) -> str | None:
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def pick_output_folder(self) -> str | None:
        return self.pick_folder()

    def save_pdf(self, suggested_path: str) -> str | None:
        return self._save_dialog(suggested_path, PDF_TYPES)

    def save_text(self, suggested_path: str) -> str | None:
        return self._save_dialog(suggested_path, TEXT_TYPES)

    def _save_dialog(self, suggested_path: str, file_types: tuple[str, ...]) -> str | None:
        suggested = Path(suggested_path)
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(suggested.parent),
            save_filename=suggested.name,
            file_types=file_types,
        )
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    # ── Documentos del visor: los archivos del disco ─────────────────────────
    def read_file(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        Path(path).write_bytes(data)

    def file_size(self, path: str) -> int | None:
        file = Path(path)
        return file.stat().st_size if file.is_file() else None

    def file_url(self, path: str) -> str:
        return self.share_bytes(self.read_file(path), "application/pdf")

    # ── Escritorio ───────────────────────────────────────────────────────────
    def open_folder(self, path: str) -> None:
        if not Path(path).is_dir():
            log.warning("Carpeta inexistente: %s", path)
            return
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 - ruta local elegida por el usuario
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])

    def reveal_file(self, path: str) -> None:
        file = Path(path)
        if os.name == "nt" and file.exists():
            # Con la ruta completa: sin ella, Windows buscaría también un explorer.exe en la carpeta actual.
            explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
            subprocess.Popen([str(explorer), "/select,", os.path.normpath(file)])  # noqa: S603
        else:
            self.open_folder(str(file.parent))

    def open_url(self, url: str) -> None:
        if is_external_url(url):
            webbrowser.open(url.strip())
        else:
            log.warning("Enlace no permitido: %.80r", url)

    # ── Ventana ──────────────────────────────────────────────────────────────
    def show(self) -> None:
        self.window.show()

    def bring_to_front(self) -> None:
        """Muestra y activa la ventana (al recibir PDF de otra instancia)."""
        try:
            self.window.restore()
            self.window.show()
            if os.name == "nt":
                ctypes.windll.user32.SetForegroundWindow(self.window.native.Handle.ToInt32())
        except Exception:
            log.debug("No se pudo traer la ventana al frente", exc_info=True)

    def quit(self) -> None:
        self._quitting = True
        self.window.destroy()

    def apply_theme(self, dark: bool) -> None:
        """Barra de título oscura/clara (atributo DWM de Windows 10 20H1+); en otros sistemas no hace nada."""
        if os.name != "nt":
            return
        try:
            hwnd = self.window.native.Handle.ToInt32()
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            log.debug("No se pudo cambiar el color de la barra de título", exc_info=True)

    def emit(self, event: str, payload: Any = None) -> None:
        self.window.run_js(f"window.pdfm && window.pdfm.emit({json.dumps(event)}, {json.dumps(payload)})")

    def share_bytes(self, data: bytes, content_type: str) -> str:
        return self._bytes.share(data, content_type)

    def upload_url(self) -> str:
        return self._bytes.expect()

    def uploaded(self, url: str) -> bytes | None:
        return self._bytes.received(url)

    def run_engine(self, task: str, data: bytes, args: dict[str, Any]) -> bytes:
        task_id = next(self._task_ids)
        upload = self.upload_url()
        done: Future[str | None] = Future()
        self._tasks[task_id] = done
        try:
            self.emit(ENGINE_TASK, {
                "id": task_id, "task": task, "args": args, "upload": upload,
                "url": self.share_bytes(data, "application/pdf"),
            })
            try:
                error = done.result(timeout=ENGINE_TIMEOUT)
            except TimeoutError as ex:
                raise RuntimeError("El motor del visor no respondió.") from ex
        finally:
            del self._tasks[task_id]
        if error:
            raise RuntimeError(error)
        result = self.uploaded(upload)
        if result is None:
            raise RuntimeError("No llegó el resultado del motor del visor.")
        return result

    def engine_done(self, task_id: int, error: str | None) -> None:
        """La ventana terminó la tarea ``task_id`` de :meth:`run_engine`."""
        done = self._tasks.get(task_id)
        if done is not None:
            done.set_result(error)

    def close(self) -> None:
        """Al cerrar la ventana: detiene el servidor de datos."""
        self._bytes.close()
