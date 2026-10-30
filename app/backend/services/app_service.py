"""Servicio ``app``: preferencias, diagnóstico y enlaces externos."""

from __future__ import annotations

import platform
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import fitz

from app import LOG_FILE
from app.backend.host import Host
from app.backend.rpc import exposed
from app.backend.settings import Settings

LOG_TAIL_BYTES = 256 * 1024  # el visor de registro muestra solo el final del archivo
QUIT_REQUESTED = "app:quit-requested"  # se cerró la ventana con documentos sin guardar


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "?"


class AppService:
    def __init__(self, host: Host, settings: Settings, log_file: Path = LOG_FILE) -> None:
        self._host = host
        self._settings = settings
        self._log_file = log_file
        self._when_ready: list[Callable[[], None]] = []

    def when_ready(self, callback: Callable[[], None]) -> None:
        """Ejecuta ``callback`` cuando el frontend esté listo (p. ej. abrir los PDF del arranque)."""
        self._when_ready.append(callback)

    @exposed
    def settings(self) -> dict[str, Any]:
        return {"dark_theme": self._settings.dark_theme}

    @exposed
    def set_theme(self, dark: bool) -> None:
        self._settings.set("dark_theme", bool(dark))
        self._host.apply_theme(bool(dark))

    @exposed
    def ready(self) -> None:
        """El frontend ya aplicó el tema: se muestra la ventana (sin destello blanco)."""
        self._host.apply_theme(self._settings.dark_theme)
        self._host.show()
        callbacks, self._when_ready = self._when_ready, []
        for callback in callbacks:
            callback()

    @exposed
    def quit(self) -> None:
        """Sale sin volver a preguntar (el usuario aceptó perder los cambios)."""
        self._host.quit()

    @exposed
    def about(self) -> dict[str, str]:
        """Versión de la app y de los motores, para la sección de diagnóstico de Ajustes."""
        from app import APP_VERSION

        return {
            "app": APP_VERSION,
            "pymupdf": fitz.__version__,
            "pywebview": _package_version("pywebview"),
            "python": platform.python_version(),
        }

    @exposed
    def diagnostics_log(self) -> str:
        try:
            with self._log_file.open("rb") as f:
                f.seek(max(0, self._log_file.stat().st_size - LOG_TAIL_BYTES))
                return f.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
        except FileNotFoundError:
            return "No hay registro de depuración disponible."

    @exposed
    def open_url(self, url: str) -> None:
        self._host.open_url(url)
