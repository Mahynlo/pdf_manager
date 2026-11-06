"""Implementación de :class:`app.backend.host.Host` en el navegador.

Lo que necesita a la ventana (diálogos, el motor de EmbedPDF) se le pide por un :class:`Channel`,
y Python espera la respuesta como espera a un diálogo en el escritorio. Lo que no tiene sentido en
un navegador (abrir una carpeta del sistema, la barra de título) no hace nada.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Protocol

from app.browser import background
from app.browser.files import Files


class Channel(Protocol):
    """Lo que ofrece el worker (``app/ui/src/lib/browser/worker.ts``)."""

    def ask(self, kind: str, payload: str, data: bytes | None = None) -> tuple[str, bytes]:
        """Pide algo a la ventana y espera: devuelve la respuesta (JSON) y sus datos."""

    def emit(self, event: str, payload: str) -> None: ...

    def share(self, data: bytes, content_type: str) -> str:
        """URL ``blob:`` con ``data``."""

    def saved(self, path: str, data: bytes) -> None:
        """Se escribió ``path``: la ventana lo guarda en el archivo real o lo descarga."""


class BrowserHost:
    def __init__(self, channel: Channel, files: Files) -> None:
        self._channel = channel
        self._files = files
        self._upload_ids = itertools.count(1)
        self._uploads: dict[str, bytes] = {}

    def _ask(self, kind: str, payload: Any = None, data: bytes | None = None) -> tuple[Any, bytes]:
        text, reply = self._channel.ask(kind, json.dumps(payload), data)
        return json.loads(text), reply

    def _picked(self, value: dict[str, Any], data: bytes) -> list[str]:
        """Copia los archivos que eligió el usuario: ``data`` los lleva uno detrás de otro."""
        paths, start = [], 0
        for item in value["files"]:
            self._files.add(item["path"], data[start:start + item["size"]])
            start += item["size"]
            paths.append(item["path"])
        return paths

    # ── Diálogos ─────────────────────────────────────────────────────────────
    def pick_pdfs(self) -> list[str]:
        return self._picked(*self._ask("pick", {"multiple": True}))

    def pick_pdf(self) -> str | None:
        return next(iter(self._picked(*self._ask("pick", {"multiple": False}))), None)

    def pick_folder(self) -> str | None:
        return self._folder(output=False)

    def pick_output_folder(self) -> str | None:
        return self._folder(output=True)

    def _folder(self, output: bool) -> str | None:
        value, data = self._ask("folder", {"output": output})
        if value is None:
            return None
        self._picked(value, data)
        Path(value["path"]).mkdir(parents=True, exist_ok=True)
        return value["path"]

    def save_pdf(self, suggested_path: str) -> str | None:
        return self._save(suggested_path, "pdf")

    def save_text(self, suggested_path: str) -> str | None:
        return self._save(suggested_path, "txt")

    def _save(self, suggested_path: str, kind: str) -> str | None:
        path, _ = self._ask("save", {"name": Path(suggested_path).name, "kind": kind})
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return path

    # ── Sin equivalente en un navegador ──────────────────────────────────────
    def open_folder(self, path: str) -> None: ...

    def reveal_file(self, path: str) -> None: ...

    def show(self) -> None: ...

    def quit(self) -> None: ...

    def apply_theme(self, dark: bool) -> None: ...

    # ── Ventana ──────────────────────────────────────────────────────────────
    def open_url(self, url: str) -> None:
        if url.startswith(("http://", "https://", "mailto:")):
            self.emit("browser:open-url", url)

    def emit(self, event: str, payload: Any = None) -> None:
        self._channel.emit(event, json.dumps(payload))
        background.pump()

    def share_bytes(self, data: bytes, content_type: str) -> str:
        return self._channel.share(data, content_type)

    def upload_url(self) -> str:
        return f"upload:{next(self._upload_ids)}"

    def receive(self, url: str, data: bytes) -> None:
        """La ventana subió ``data`` a ``url`` (de :meth:`upload_url`)."""
        self._uploads[url] = data

    def uploaded(self, url: str) -> bytes | None:
        return self._uploads.pop(url, None)

    def run_engine(self, task: str, data: bytes, args: dict[str, Any]) -> bytes:
        value, result = self._ask("engine", {"task": task, "args": args}, data)
        if value and value.get("error"):
            raise RuntimeError(value["error"])
        return result

    def engine_done(self, task_id: int, error: str | None) -> None:
        """Sin uso: la respuesta de :meth:`run_engine` llega por el canal."""

    def flush(self) -> None:
        """Entrega a la ventana lo que escribieron los servicios."""
        for path in self._files.changed():
            self._channel.saved(str(path), path.read_bytes())
