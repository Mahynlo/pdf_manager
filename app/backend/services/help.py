"""Servicio ``help`` (Ayuda): manuales en Markdown convertidos a HTML.

El HTML se genera sin permitir HTML crudo dentro del Markdown (``html=False``):
así es seguro insertarlo en la página tal cual.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from app import PROJECT_ROOT
from app.backend.rpc import UserError, exposed

log = logging.getLogger(__name__)

# Carpetas donde se buscan los manuales (la primera que exista), como en la versión Qt.
DOCS_DIRS: tuple[Path, ...] = (
    PROJECT_ROOT / "src" / "assets" / "ayuda",
    PROJECT_ROOT / "docs" / "ayuda",
    PROJECT_ROOT / "assets" / "ayuda",
)


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml"}


def _title(file_name: str) -> str:
    return Path(file_name).stem.replace("_", " ")


class HelpService:
    def __init__(self, docs_dirs: tuple[Path, ...] = DOCS_DIRS) -> None:
        self._dir = next((d for d in docs_dirs if d.is_dir()), None)
        self._markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
        default_image = self._markdown.renderer.rules["image"]

        def image(_renderer, tokens, idx, options, env):
            tokens[idx].attrSet("src", self._image_src(tokens[idx].attrGet("src") or ""))
            return default_image(tokens, idx, options, env)

        self._markdown.add_render_rule("image", image)

    def _image_src(self, src: str) -> str:
        """Imagen local del manual como data URL.

        Las rutas como ``/ayuda_img/x.png`` son relativas a la carpeta de recursos (la
        que contiene la de manuales); no se sirve nada fuera de ella.
        """
        if self._dir is None or src.startswith(("http://", "https://", "data:")):
            return src
        root = self._dir.parent.resolve()
        path = (root / src.lstrip("/")).resolve()
        mime = _IMAGE_TYPES.get(path.suffix.lower())
        if mime is None or not path.is_relative_to(root) or not path.is_file():
            return src
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    @exposed
    def documents(self) -> list[dict[str, str]]:
        if self._dir is None:
            return []
        return [{"file": f.name, "title": _title(f.name)} for f in sorted(self._dir.glob("*.md"))]

    @exposed
    def document(self, file_name: str) -> dict[str, Any]:
        """Manual ``file_name`` como HTML; solo se aceptan los nombres que da :meth:`documents`."""
        if file_name not in {d["file"] for d in self.documents()}:
            raise UserError("Documento no encontrado.", "not_found")
        try:
            text = (self._dir / file_name).read_text(encoding="utf-8")
        except OSError as ex:
            log.warning("No se pudo leer la ayuda %s", file_name, exc_info=True)
            raise UserError(f"No se pudo leer el documento: {ex}", "read_error") from ex
        title = _title(file_name)
        return {"title": title, "html": self._markdown.render(f"# 📖 Manual de Usuario - {title}\n\n{text}")}
