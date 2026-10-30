"""Implementación de :class:`app.backend.host.Host` sobre una ventana pywebview (WebView2 en Windows)."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

from app.backend.services.app_service import QUIT_REQUESTED
from app.byte_server import ByteServer

log = logging.getLogger(__name__)

PDF_TYPES = ("Archivos PDF (*.pdf)",)
TEXT_TYPES = ("Archivos de Texto (*.txt)",)
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


class WebviewHost:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._close_blocker: Callable[[], Any] | None = None
        self._on_drop_files: Callable[[list[str]], Any] | None = None
        self._quitting = False
        self._bytes = ByteServer()  # datos grandes con el frontend (ver share_bytes y upload_url)

    def attach(
        self,
        window: webview.Window,
        close_blocker: Callable[[], Any] | None = None,
        on_drop_files: Callable[[list[str]], Any] | None = None,
    ) -> None:
        """``close_blocker`` devuelve ``None`` si la ventana puede cerrarse, o los datos del
        evento ``QUIT_REQUESTED`` con los que el frontend pregunta antes de salir.
        ``on_drop_files`` recibe las rutas de los PDF arrastrados a la ventana."""
        self._window = window
        self._close_blocker = close_blocker
        self._on_drop_files = on_drop_files
        window.events.closing += self._on_closing
        window.events.minimized += lambda: self._memory_target(low=True)
        window.events.restored += lambda: self._memory_target(low=False)
        window.events.maximized += lambda: self._memory_target(low=False)
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
        pdfs = [p for p in paths if p and p.lower().endswith(".pdf") and Path(p).is_file()]
        if pdfs and self._on_drop_files is not None:
            self._on_drop_files(pdfs)

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

    def pick_pdf(self) -> str | None:
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=PDF_TYPES)
        return result[0] if result else None

    def pick_folder(self) -> str | None:
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

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
            subprocess.Popen(["explorer", "/select,", os.path.normpath(file)])
        else:
            self.open_folder(str(file.parent))

    def open_url(self, url: str) -> None:
        if url.startswith(("http://", "https://", "mailto:")):
            webbrowser.open(url)

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

    def close(self) -> None:
        """Al cerrar la ventana: detiene el servidor de datos."""
        self._bytes.close()
