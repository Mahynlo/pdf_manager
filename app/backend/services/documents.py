"""Servicio ``documents``: abrir PDFs y la lista de archivos recientes.

Todas las aperturas pasan por :meth:`DocumentService.open` (también las que
piden otras herramientas): emite ``document:open`` y el frontend abre la pestaña
del visor, que carga el PDF con el servicio ``viewer`` (y lo añade a recientes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from pdf_core import recent_files

RECENT_CHANGED = "recent:changed"
OPEN_REQUESTED = "document:open"


class DocumentService:
    def __init__(self, host: Host) -> None:
        self._host = host

    def open(self, path: str, password: str | None = None) -> None:
        """Pide al frontend abrir ``path`` en el visor (con ``password`` si ya se conoce)."""
        if not Path(path).is_file():
            raise UserError(f"No se encontró el archivo: {Path(path).name}", "not_found")
        self._host.emit(OPEN_REQUESTED, {"path": path, "password": password})

    @exposed
    def open_dialog(self) -> list[str]:
        """Diálogo «Abrir PDF» (uno o varios); devuelve las rutas elegidas."""
        paths = self._host.pick_pdfs()
        for path in paths:
            self.open(path)
        return paths

    @exposed
    def recent(self) -> list[dict[str, Any]]:
        return [{"path": p, "name": Path(p).name, "folder": str(Path(p).parent)} for p in recent_files.load()]

    @exposed
    def remove_recent(self, path: str) -> list[dict[str, Any]]:
        recent_files.remove(path)
        self._host.emit(RECENT_CHANGED)
        return self.recent()

    @exposed
    def clear_recent(self) -> list[dict[str, Any]]:
        recent_files.clear()
        self._host.emit(RECENT_CHANGED)
        return self.recent()

    @exposed
    def reveal(self, path: str) -> None:
        self._host.reveal_file(path)
