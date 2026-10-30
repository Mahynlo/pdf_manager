"""Servidor local de un solo uso para pasar datos grandes entre Python y la interfaz.

El puente de pywebview pasa los valores como texto JSON: un PDF de 40 MB tarda varios
segundos en base64. Por aquí viajan en binario:

- de Python a la interfaz (:meth:`ByteServer.share`): el frontend los descarga con ``fetch(url)``;
- de la interfaz a Python (:meth:`ByteServer.expect`): el frontend los sube con
  ``fetch(url, {method: 'POST', body})`` y Python los recoge con :meth:`ByteServer.received`.

- Solo escucha en 127.0.0.1, en un puerto libre que elige el sistema.
- Cada dato tiene un código aleatorio largo: no se puede adivinar desde otra página o programa.
- Se sirve (o se recibe) una sola vez y caduca a los :data:`TTL` segundos.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)

TTL = 120.0  # s que espera un dato a que lo descarguen (o a que lo suban)
UPLOAD = "up"  # prefijo de las URL de subida


class ByteServer:
    def __init__(self) -> None:
        self._items: dict[str, tuple[bytes, str, float]] = {}  # código -> (datos, tipo, creado)
        self._uploads: dict[str, tuple[bytes | None, float]] = {}  # código -> (datos subidos, creado)
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    def share(self, data: bytes, content_type: str) -> str:
        """URL desde la que se descarga ``data`` una vez."""
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            # Los que nadie pidió (p. ej. se cerró la pestaña antes) no se acumulan.
            for old in [t for t, (_, _, created) in self._items.items() if now - created > TTL]:
                del self._items[old]
            self._items[token] = (data, content_type, now)
            port = self._ensure_started()
        return f"http://127.0.0.1:{port}/{token}"

    def expect(self) -> str:
        """URL a la que la interfaz puede subir un dato una vez (``POST``); se recoge con :meth:`received`."""
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            for old in [t for t, (_, created) in self._uploads.items() if now - created > TTL]:
                del self._uploads[old]
            self._uploads[token] = (None, now)
            port = self._ensure_started()
        return f"http://127.0.0.1:{port}/{UPLOAD}/{token}"

    def received(self, url: str) -> bytes | None:
        """Lo subido a ``url`` (de :meth:`expect`), una sola vez; ``None`` si no llegó o caducó."""
        with self._lock:
            item = self._uploads.pop(url.rsplit("/", 1)[-1], None)
        if item is None or item[0] is None or time.monotonic() - item[1] > TTL:
            return None
        return item[0]

    def expecting(self, token: str) -> bool:
        with self._lock:
            item = self._uploads.get(token)
        return item is not None and item[0] is None

    def store(self, token: str, data: bytes) -> bool:
        """Guarda lo que llega por ``POST`` si se esperaba (y aún no llegó nada)."""
        with self._lock:
            item = self._uploads.get(token)
            if item is None or item[0] is not None:
                return False
            self._uploads[token] = (data, item[1])
        return True

    def take(self, token: str) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._items.pop(token, None)
        if item is None or time.monotonic() - item[2] > TTL:
            return None
        return item[0], item[1]

    def close(self) -> None:
        with self._lock:
            self._items.clear()
            self._uploads.clear()
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    def _ensure_started(self) -> int:
        if self._server is None:
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
            self._server.daemon_threads = True
            threading.Thread(target=self._server.serve_forever, name="byte-server", daemon=True).start()
            log.info("Servidor de datos en 127.0.0.1:%d", self._server.server_port)
        return self._server.server_port


def _handler(server: ByteServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nombre de http.server)
            item = server.take(self.path.lstrip("/"))
            if item is None:
                self.send_error(404)
                return
            data, content_type = item
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            # La interfaz se sirve desde otro puerto (pywebview o Vite); el código ya protege el dato.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 (nombre de http.server)
            prefix, _, token = self.path.lstrip("/").partition("/")
            # Solo se lee lo que se espera: nadie puede llenar la memoria con subidas a ciegas.
            ok = prefix == UPLOAD and server.expecting(token)
            if ok:
                ok = server.store(token, self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            self.send_response(204 if ok else 404)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (firma de http.server)
            log.debug("byte-server: " + format, *args)

    return Handler
