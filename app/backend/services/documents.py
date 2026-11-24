"""Servicio ``documents``: abrir PDFs e imágenes y la lista de archivos recientes.

Todas las aperturas pasan por :meth:`DocumentService.open` (también las que
piden otras herramientas): emite ``document:open`` y el frontend abre la pestaña
del visor, que carga el PDF con el servicio ``viewer`` (y lo añade a recientes).

Las imágenes (:meth:`DocumentService.open_many`, desde «Abrir» o arrastradas) no se abren: emite
``images:open`` con todas juntas y el frontend las convierte en un PDF nuevo con el diálogo
«Imágenes a PDF» (lee cada una con :meth:`DocumentService.image_url`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from pdf_core import recent_files

RECENT_CHANGED = "recent:changed"
OPEN_REQUESTED = "document:open"
IMAGES_REQUESTED = "images:open"
# Las que sabe dibujar la ventana (WebView2 y los navegadores): el diálogo «Imágenes a PDF».
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg")


def is_image(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


class DocumentService:
    def __init__(self, host: Host) -> None:
        self._host = host

    def open(self, path: str, password: str | None = None) -> None:
        """Pide al frontend abrir ``path`` en el visor (con ``password`` si ya se conoce)."""
        if not self._exists(path):
            raise UserError(f"No se encontró el archivo: {Path(path).name}", "not_found")
        self._host.emit(OPEN_REQUESTED, {"path": path, "password": password})

    def open_many(self, paths: list[str]) -> None:
        """Abre cada PDF de ``paths`` en el visor; las imágenes, todas juntas en un PDF nuevo."""
        images = [path for path in paths if is_image(path)]
        for path in paths:
            if not is_image(path):
                self.open(path)
        if images:
            self._host.emit(IMAGES_REQUESTED, {"paths": images})

    @exposed
    def open_dialog(self) -> list[str]:
        """Diálogo «Abrir» (PDF o imágenes, uno o varios); devuelve las rutas elegidas."""
        paths = self._host.pick_documents()
        self.open_many(paths)
        return paths

    @exposed
    def image_url(self, path: str) -> str:
        """URL de un solo uso con la imagen ``path`` (de ``images:open``), para leerla en la ventana."""
        if not is_image(path):
            raise UserError(f"No es una imagen: {Path(path).name}", "not_image")
        try:
            return self._host.file_url(path)
        except OSError as ex:
            raise UserError(f"No se pudo leer {Path(path).name}: {ex}", "open_failed") from ex

    def _exists(self, path: str) -> bool:
        """Si ``path`` es un archivo que se puede abrir: lo dice el host (en el navegador, los
        archivos los tiene la ventana, no el disco de Python)."""
        return self._host.file_size(path) is not None

    @exposed
    def recent(self) -> list[dict[str, Any]]:
        """Los últimos abiertos: ``path``, ``name``, ``folder`` y ``size`` (bytes, o ``None``)."""
        return [{"path": p, "name": Path(p).name, "folder": str(Path(p).parent), "size": self._host.file_size(p)}
                for p in recent_files.load(self._exists)]

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
