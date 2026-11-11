"""Lo que los servicios pueden pedirle a la ventana anfitriona.

Los servicios dependen de este protocolo y no de pywebview: en las pruebas se usa
un doble, y en la versión web bastará otra implementación.
"""

from __future__ import annotations

from typing import Any, Protocol


class Host(Protocol):
    def pick_pdfs(self) -> list[str]:
        """Diálogo para elegir uno o varios PDF; lista vacía si se cancela."""

    def pick_pdf(self) -> str | None:
        """Diálogo para elegir un solo PDF; ``None`` si se cancela."""

    def pick_folder(self) -> str | None:
        """Diálogo para elegir una carpeta de la que leer; ``None`` si se cancela."""

    def pick_output_folder(self) -> str | None:
        """Diálogo para elegir la carpeta donde escribir; ``None`` si se cancela."""

    def save_pdf(self, suggested_path: str) -> str | None:
        """Diálogo «Guardar como» para un PDF; ``None`` si se cancela."""

    def save_text(self, suggested_path: str) -> str | None:
        """Diálogo «Guardar como» para un .txt; ``None`` si se cancela."""

    def open_folder(self, path: str) -> None: ...

    def reveal_file(self, path: str) -> None:
        """Abre la carpeta del archivo con el archivo seleccionado."""

    def open_url(self, url: str) -> None:
        """Abre un enlace externo en el navegador predeterminado."""

    def show(self) -> None:
        """Muestra la ventana (se crea oculta hasta que el frontend está listo)."""

    def quit(self) -> None:
        """Cierra la ventana sin volver a preguntar (el usuario ya confirmó)."""

    def apply_theme(self, dark: bool) -> None:
        """Pone la barra de título nativa a juego con el tema."""

    def emit(self, event: str, payload: Any = None) -> None:
        """Envía un evento al frontend (progreso, avisos)."""

    def share_bytes(self, data: bytes, content_type: str) -> str:
        """URL de un solo uso desde la que el frontend descarga ``data`` con ``fetch``
        (para datos grandes, que por el puente irían como texto)."""

    def upload_url(self) -> str:
        """URL de un solo uso a la que el frontend sube datos con ``fetch(url, {method: 'POST'})``."""

    def uploaded(self, url: str) -> bytes | None:
        """Lo subido a ``url`` (de :meth:`upload_url`); ``None`` si no llegó o caducó."""

    def run_engine(self, task: str, data: bytes, args: dict[str, Any]) -> bytes:
        """Hace en la ventana, con el motor de EmbedPDF, lo que no sabe hacer el PDFium de Python.

        ``data`` es un PDF y el resultado, ese PDF cambiado. Tareas (``lib/engine-tasks.ts``):
        ``encrypt`` (``user``, ``owner``, ``permissions``) y ``outline`` (``items``).
        ``password`` abre ``data`` si está cifrado.
        Bloquea hasta que termina: no llamarlo desde el hilo de la ventana.

        :raises RuntimeError: si la tarea falla o no termina.
        """

    def engine_done(self, task_id: int, error: str | None) -> None:
        """La ventana terminó la tarea ``task_id`` de :meth:`run_engine`."""
