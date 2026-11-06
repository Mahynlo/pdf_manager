"""Hilos en Pyodide, que no los tiene: el trabajo de un hilo se hace después de responder a la llamada.

Los servicios crean hilos para no bloquear la llamada que los arranca. Aquí un hilo espera en una
cola y lo ejecuta :func:`run_pending` en cuanto se ha respondido, en el mismo worker: la interfaz
sigue libre porque va en otro hilo del navegador.

Mientras dura ese trabajo no llegan más llamadas, salvo las que recoge :func:`pump`: las que tienen
que poder interrumpirlo (cancelar, responder a una pregunta). Se atienden en cada evento que emite
el trabajo y mientras espera en un ``threading.Event``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable

log = logging.getLogger(__name__)

WAIT_STEP_MS = 100  # cada cuánto se mira si llegó algo mientras se espera en un Event

Poll = Callable[[int], bool]  # espera hasta `ms` y atiende lo que llegue; devuelve si atendió algo


def _no_poll(_ms: int) -> bool:
    return False


_pending: deque[threading.Thread] = deque()
_poll: Poll = _no_poll
_running = False


class DeferredThread(threading.Thread):
    def start(self) -> None:
        _pending.append(self)

    def join(self, timeout: float | None = None) -> None:
        if self in _pending:
            _pending.remove(self)
            _run(self)

    def is_alive(self) -> bool:
        return self in _pending


class NoTimer:
    """Los temporizadores solo sueltan memoria tras un rato sin usarla: aquí no se disparan."""

    daemon = True

    def __init__(self, *_args: object, **_kwargs: object) -> None: ...

    def start(self) -> None: ...

    def cancel(self) -> None: ...


class PumpedEvent(threading.Event):
    def wait(self, timeout: float | None = None) -> bool:
        end = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            left = WAIT_STEP_MS if end is None else min(WAIT_STEP_MS, int((end - time.monotonic()) * 1000))
            if left <= 0:
                return False
            _poll(left)
        return True


def install(poll: Poll) -> None:
    """Sustituye los hilos de ``threading``. Va antes de importar los servicios."""
    global _poll
    _poll = poll
    threading.Thread = DeferredThread
    threading.Timer = NoTimer
    threading.Event = PumpedEvent


def _run(thread: threading.Thread) -> None:
    try:
        thread.run()
    except Exception:
        log.exception("Fallo en el trabajo %s", thread.name)


def run_pending() -> bool:
    """Hace los trabajos en cola; devuelve si había alguno."""
    global _running
    ran = False
    _running = True
    try:
        while _pending:
            ran = True
            _run(_pending.popleft())
    finally:
        _running = False
    return ran


def pump() -> None:
    """Atiende lo que haya llegado. Solo durante un trabajo: fuera de él las llamadas llegan solas."""
    if _running:
        _poll(0)
