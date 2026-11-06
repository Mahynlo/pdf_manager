"""El backend dentro del Web Worker: lo crea y lo llama ``app/ui/src/lib/browser/worker.ts``."""

from __future__ import annotations

import json
import logging
from typing import Any

from pyodide.ffi import to_js

from app import DATA_DIR, LOG_FILE
from app.browser import background, onnx
from app.browser.files import ROOT, Files
from app.browser.host import BrowserHost


class JsChannel:
    """:class:`app.browser.host.Channel` sobre el objeto del worker."""

    def __init__(self, worker: Any) -> None:
        self._worker = worker

    def ask(self, kind: str, payload: str, data: bytes | None = None) -> tuple[str, bytes]:
        reply = self._worker.ask(kind, payload, to_js(data) if data is not None else None)
        return reply.json, reply.data.to_bytes()

    def emit(self, event: str, payload: str) -> None:
        self._worker.emit(event, payload)

    def share(self, data: bytes, content_type: str) -> str:
        return self._worker.share(to_js(data), content_type)

    def saved(self, path: str, data: bytes) -> None:
        self._worker.saved(path, to_js(data))


class Backend:
    def __init__(self, worker: Any) -> None:
        self._worker = worker
        background.install(self._poll)  # antes de importar los servicios
        from app.backend.services import build_registry, quit_warnings
        from app.backend.services.extract import ExtractService
        from app.backend.settings import Settings

        # Lo que Extraer escribe en su carpeta predeterminada también se entrega a la ventana.
        ExtractService._default_destination = staticmethod(lambda: str(ROOT / "Documentos"))

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, filename=LOG_FILE, encoding="utf-8",
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        channel = JsChannel(worker)
        onnx.install(onnx.channel_ask(channel))
        self._files = Files()
        self._host = BrowserHost(channel, self._files)
        self._registry, self._services = build_registry(self._host, Settings())
        self._warnings = quit_warnings

    def _poll(self, ms: int) -> bool:
        """Atiende una llamada que tenga que interrumpir el trabajo en curso."""
        message = self._worker.poll(ms)
        if not message:
            return False
        call = json.loads(message)
        self._worker.reply(call["id"], self.call(call["method"], json.dumps(call["args"])))
        return True

    def call(self, method: str, args: str) -> str:
        return json.dumps(self._registry.dispatch(method, json.loads(args)), default=str)

    def settle(self) -> None:
        """Tras una llamada: hace los trabajos pendientes y entrega lo que se escribió."""
        self._worker.busy(True)
        try:
            background.run_pending()
        finally:
            self._worker.busy(False)
        self._host.flush()
        self._worker.dirty(self._warnings(self._services) is not None)

    def add_file(self, path: str, data: Any) -> None:
        self._files.add(path, data.to_bytes())

    def open_files(self, paths: str) -> None:
        """PDF soltados en la ventana."""
        for path in json.loads(paths):
            self._services["documents"].open(path)

    def upload(self, url: str, data: Any) -> None:
        self._host.receive(url, data.to_bytes())
