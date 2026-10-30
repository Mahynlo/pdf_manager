"""Una sola ventana de la app (equivale a ``src_qt/core/single_instance.py``).

La primera instancia escucha en una tubería con nombre del usuario (``multiprocessing``,
sin dependencias). Si se vuelve a lanzar la app —por ejemplo con «Abrir con» desde el
Explorador— la nueva instancia envía sus PDF a la primera y sale; la primera los abre
y pasa al frente. Una lista vacía significa «el usuario volvió a abrir la app».
"""

from __future__ import annotations

import getpass
import hashlib
import logging
import os
import threading
from collections.abc import Callable
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 0.5  # s que espera la secundaria a la principal
MAX_PATHS = 200


def _address(name: str) -> tuple[str, str]:
    """Dirección y familia de la tubería: única por usuario."""
    user = hashlib.sha1(getpass.getuser().encode("utf-8")).hexdigest()[:12]
    if os.name == "nt":
        return rf"\\.\pipe\{name}_{user}", "AF_PIPE"
    return str(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"{name}_{user}.sock"), "AF_UNIX"


class SingleInstance:
    def __init__(self, name: str = "extraer_pdfs_web") -> None:
        self._address, self._family = _address(name)
        self._authkey = f"{name}:{getpass.getuser()}".encode()
        self._listener: Listener | None = None
        self._serving: threading.Thread | None = None
        self._closed = False

    def acquire(self, paths: list[str]) -> bool:
        """True si esta es la instancia principal. Si no, envía ``paths`` a la principal y devuelve False."""
        for _attempt in range(2):
            if self._send(paths):
                return False
            try:
                if self._family == "AF_UNIX" and Path(self._address).exists():
                    Path(self._address).unlink()  # socket que dejó una instancia que terminó mal
                self._listener = Listener(self._address, self._family, authkey=self._authkey)
                return True
            except OSError:
                # Otra instancia acaba de crear la tubería a la vez: se le envían las rutas.
                log.info("Otra instancia se adelantó; se reintenta como secundaria")
        return True  # sin IPC posible: mejor abrir una ventana más que no abrir ninguna

    def _send(self, paths: list[str]) -> bool:
        if self._family == "AF_UNIX" and not Path(self._address).exists():
            return False
        if os.name == "nt":
            try:
                import _winapi

                _winapi.WaitNamedPipe(self._address, int(CONNECT_TIMEOUT * 1000))
            except OSError:
                return False  # no hay instancia principal escuchando
            # La principal podrá pasar su ventana al frente (Windows lo impide si no).
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        try:
            with Client(self._address, self._family, authkey=self._authkey) as conn:
                conn.send(list(paths)[:MAX_PATHS])
            return True
        except (OSError, EOFError):
            return False
        except Exception:  # p. ej. AuthenticationError si la tubería es de otro programa
            log.warning("No se pudo hablar con la instancia principal", exc_info=True)
            return False

    def listen(self, on_paths: Callable[[list[str]], None]) -> None:
        """Atiende a las instancias secundarias en un hilo; ``on_paths`` recibe PDF existentes."""
        if self._listener is None:
            return

        listener = self._listener

        def serve() -> None:
            while not self._closed:
                try:
                    conn = listener.accept()
                except (OSError, EOFError):
                    if self._closed:
                        return
                    continue
                except Exception:  # cliente que no sabe la clave
                    log.warning("Conexión rechazada", exc_info=True)
                    continue
                if self._closed:  # la conexión de close() para despertar a accept()
                    conn.close()
                    return
                self._receive(conn, on_paths)

        self._serving = threading.Thread(target=serve, name="single-instance", daemon=True)
        self._serving.start()

    @staticmethod
    def _receive(conn: Connection, on_paths: Callable[[list[str]], None]) -> None:
        with conn:
            try:
                data = conn.recv()
            except (OSError, EOFError):
                return
        if not isinstance(data, list):
            return
        paths = [str(Path(p).resolve()) for p in data if isinstance(p, str) and p.strip() and Path(p).is_file()]
        try:
            on_paths(paths)
        except Exception:
            log.exception("Error al abrir los archivos recibidos")

    def close(self) -> None:
        """Deja de ser la instancia principal: otra que se lance ya podrá serlo."""
        self._closed = True
        if self._serving is not None and self._serving.is_alive():
            # accept() no se interrumpe al cerrar el Listener (en Windows la tubería seguiría
            # aceptando a otras instancias): una conexión propia lo despierta para que salga.
            try:
                with Client(self._address, self._family, authkey=self._authkey):
                    pass
            except Exception:
                log.debug("No se pudo despertar al hilo de la instancia única", exc_info=True)
            self._serving.join(2)
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
