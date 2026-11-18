"""Los archivos del usuario en el navegador: copias en el sistema de archivos virtual de Pyodide.

Los servicios trabajan con rutas, como en el escritorio. La ventana elige las rutas (``/files/…``)
y sabe a qué archivo real corresponde cada una; :meth:`Files.changed` dice qué escribieron los
servicios, para que la ventana lo guarde en el archivo real o lo descargue.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path("/files")


class Files:
    def __init__(self, root: Path = ROOT) -> None:
        self._root = root
        self._known: dict[Path, tuple[int, int]] = {}

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int]:
        info = path.stat()
        return info.st_mtime_ns, info.st_size

    def add(self, path: str, data: bytes) -> None:
        """Copia en ``path`` un archivo del usuario (no cuenta como cambiado)."""
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        self._known[file] = self._stamp(file)

    def changed(self) -> list[Path]:
        """Archivos nuevos o cambiados desde la última vez."""
        found = []
        for path in (p for p in self._root.rglob("*") if p.is_file()):
            stamp = self._stamp(path)
            if self._known.get(path) != stamp:
                self._known[path] = stamp
                found.append(path)
        return found
