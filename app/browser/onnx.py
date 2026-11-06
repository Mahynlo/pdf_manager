"""El ``onnxruntime`` del OCR en el navegador: lo poco que usa ``pdf_core.ocr.paddle``.

Pyodide no tiene onnxruntime. Los modelos corren con onnxruntime-web en otro worker
(``app/ui/src/lib/browser/onnx-worker.ts``): esto solo le pasa los tensores por el canal.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

Ask = Callable[[str, Any, bytes | None], tuple[Any, bytes]]


class SessionOptions:
    log_severity_level = 0


def session_class(ask: Ask) -> type:
    class InferenceSession:
        def __init__(self, path: str, _options: SessionOptions | None = None, providers: list[str] | None = None) -> None:
            self._model = Path(path).name
            value, _ = ask("onnx", {"model": self._model}, None)
            _raise(value)

        def run(self, _outputs: None, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
            (name, tensor), = feeds.items()
            tensor = np.ascontiguousarray(tensor, dtype=np.float32)
            request = {"model": self._model, "input": name, "shape": list(tensor.shape)}
            value, data = ask("onnx", request, tensor.tobytes())
            _raise(value)
            return [np.frombuffer(data, dtype=np.float32).reshape(value["shape"])]

    return InferenceSession


def _raise(value: dict[str, Any] | None) -> None:
    if value and value.get("error"):
        raise RuntimeError(value["error"])


def install(ask: Ask) -> None:
    """Hace que ``import onnxruntime`` dé este módulo."""
    module = ModuleType("onnxruntime")
    module.SessionOptions = SessionOptions
    module.InferenceSession = session_class(ask)
    sys.modules["onnxruntime"] = module


def channel_ask(channel: Any) -> Ask:
    """:data:`Ask` sobre un :class:`app.browser.host.Channel`."""

    def ask(kind: str, payload: Any, data: bytes | None) -> tuple[Any, bytes]:
        text, reply = channel.ask(kind, json.dumps(payload), data)
        return json.loads(text), reply

    return ask
