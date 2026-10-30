"""Llamadas del frontend al backend: métodos expuestos, despacho y formato de respuesta.

El frontend solo puede invocar métodos marcados con :func:`exposed` de un servicio
registrado; cualquier otro nombre se rechaza. Toda respuesta tiene la forma
``{"ok": True, "value": ...}`` o ``{"ok": False, "error": {"code", "message"}}``,
que ``app/ui/src/lib/api.js`` convierte en una promesa resuelta o rechazada.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

_EXPOSED_ATTR = "__rpc_exposed__"
F = TypeVar("F", bound=Callable[..., Any])


class UserError(Exception):
    """Error previsto cuyo mensaje se muestra al usuario tal cual (p. ej. contraseña incorrecta)."""

    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


def exposed(func: F) -> F:
    """Marca un método de servicio como invocable desde el frontend."""
    setattr(func, _EXPOSED_ATTR, True)
    return func


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


class Registry:
    """Tabla ``"servicio.metodo" -> callable`` con solo los métodos expuestos."""

    def __init__(self) -> None:
        self._methods: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, service: object) -> None:
        for attr in dir(type(service)):
            if getattr(getattr(type(service), attr), _EXPOSED_ATTR, False):
                self._methods[f"{name}.{attr}"] = getattr(service, attr)

    def methods(self) -> list[str]:
        return sorted(self._methods)

    def dispatch(self, method: str, args: list[Any] | None = None) -> dict[str, Any]:
        func = self._methods.get(method)
        if func is None:
            return _failure("unknown_method", f"Método desconocido: {method}")
        try:
            return {"ok": True, "value": func(*(args or []))}
        except UserError as ex:
            return _failure(ex.code, str(ex))
        except Exception as ex:  # el frontend nunca debe quedarse sin respuesta
            log.exception("Fallo en %s", method)
            return _failure("internal", f"Error inesperado: {ex}")


class Api:
    """Objeto publicado como ``window.pywebview.api``: un único punto de entrada.

    pywebview ejecuta cada llamada en su propio hilo; los servicios protegen su
    estado con un candado.
    """

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def call(self, method: str, args: list[Any] | None = None) -> dict[str, Any]:
        return self._registry.dispatch(method, args)
