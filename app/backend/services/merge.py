"""Servicio ``merge`` (Combinar): PDFs cargados, selección de páginas y combinación.

Envuelve el motor ``pdf_core.merge`` sin lógica de PDF propia. El backend
es la única fuente de verdad: cada operación que cambia algo devuelve el estado
completo (:meth:`MergeService.state`) y el frontend se repinta a partir de él.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.backend.host import Host
from app.backend.imaging import page_data_url
from app.backend.rpc import UserError, exposed
from app.backend.services.documents import DocumentService
from pdf_core.merge import engine
from pdf_core.merge.engine import (
    MergeInvalidPasswordError,
    MergeOptions,
    MergePasswordRequiredError,
    MergePermissionDeniedError,
)
from pdf_core.merge.model import MergePage, PDFEntry, accent_color_for, selection_to_range

THUMB_SCALE = 0.3
PREVIEW_SCALE = 1.5
_PROGRESS_INTERVAL = 0.1  # s entre eventos de progreso (el puente no necesita más)


@dataclass
class _Item:
    id: int
    entry: PDFEntry
    rotation: int = 0  # giro extra de todo el documento (múltiplo de 90)


class MergeService:
    def __init__(self, host: Host, documents: DocumentService) -> None:
        self._host = host
        self._documents = documents
        self._lock = threading.RLock()
        self._items: list[_Item] = []
        self._next_id = 1
        # Orden manual de la vista previa (arrastrar y soltar); se descarta al cambiar la selección.
        self._custom_order: list[tuple[int, int]] | None = None
        self._output: str | None = None
        self._last_result: str | None = None
        self._busy = False

    # ── Estado ───────────────────────────────────────────────────────────────
    @exposed
    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": [self._entry_state(item) for item in self._items],
                "preview": [list(key) for key in self._preview_keys()],
                "output": self._output,
                "last_result": self._last_result,
                "busy": self._busy,
            }

    @staticmethod
    def _entry_state(item: _Item) -> dict[str, Any]:
        e = item.entry
        return {
            "id": item.id,
            "name": e.filename,
            "path": e.path,
            "total": e.total,
            "selected": list(e.selected),
            "count": e.selected_count,
            "range": selection_to_range(e.selected),
            "rotation": item.rotation,
            "accent": accent_color_for(e.path),
        }

    def _preview_keys(self) -> list[tuple[int, int]]:
        if self._custom_order is not None:
            return list(self._custom_order)
        return [(item.id, p) for item in self._items for p in item.entry.selected_pages]

    def _changed(self) -> dict[str, Any]:
        self._custom_order = None
        return self.state()

    def _item(self, item_id: int) -> _Item:
        item = next((i for i in self._items if i.id == item_id), None)
        if item is None:
            raise UserError("El documento ya no está en la lista.", "not_found")
        return item

    # ── Carga de documentos ──────────────────────────────────────────────────
    @exposed
    def pick_files(self) -> dict[str, Any]:
        return self.add_paths(self._host.pick_pdfs())

    @exposed
    def pick_folder(self) -> dict[str, Any]:
        folder = self._host.pick_folder()
        paths = [str(p) for p in sorted(Path(folder).glob("**/*.pdf"))] if folder else []
        return self.add_paths(paths)

    @exposed
    def add_paths(self, paths: list[str]) -> dict[str, Any]:
        """Añade los PDF; devuelve el estado, los que piden contraseña y los errores."""
        locked: list[str] = []
        errors: list[str] = []
        with self._lock:
            known = {item.entry.path for item in self._items}
            for path in paths:
                norm = engine.normalize_path(path)
                if norm in known:
                    continue
                name = Path(norm).name
                try:
                    self._register(engine.open_entry(norm))
                    known.add(norm)
                except MergePasswordRequiredError:
                    locked.append(norm)
                except MergePermissionDeniedError:
                    errors.append(f"{name} está protegido y no permite ensamblaje.")
                except Exception as ex:
                    errors.append(f"Error abriendo {name}: {ex}")
            return {"state": self._changed(), "locked": locked, "errors": errors}

    @exposed
    def unlock(self, path: str, password: str) -> dict[str, Any]:
        try:
            entry = engine.open_entry(path, password=password)
        except MergeInvalidPasswordError:
            raise UserError("Contraseña incorrecta", "invalid_password") from None
        except MergePermissionDeniedError:
            raise UserError(f"{Path(path).name} no permite ensamblaje.", "permission_denied") from None
        with self._lock:
            self._register(entry)
            return self._changed()

    def _register(self, entry: PDFEntry) -> None:
        self._items.append(_Item(self._next_id, entry))
        self._next_id += 1
        if not self._output:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._output = str(Path(entry.path).parent / f"combinado_{ts}.pdf")

    # ── Lista de documentos ──────────────────────────────────────────────────
    @exposed
    def remove(self, item_id: int) -> dict[str, Any]:
        with self._lock:
            item = self._item(item_id)
            self._items.remove(item)
            item.entry.close()
            return self._changed()

    @exposed
    def clear(self) -> dict[str, Any]:
        with self._lock:
            self.close()
            return self._changed()

    @exposed
    def move(self, item_id: int, delta: int) -> dict[str, Any]:
        with self._lock:
            idx = self._items.index(self._item(item_id))
            new_idx = idx + delta
            if 0 <= new_idx < len(self._items):
                self._items[idx], self._items[new_idx] = self._items[new_idx], self._items[idx]
            return self._changed()

    @exposed
    def sort_by_name(self) -> dict[str, Any]:
        with self._lock:
            self._items.sort(key=lambda i: i.entry.filename.lower())
            return self._changed()

    @exposed
    def reverse(self) -> dict[str, Any]:
        with self._lock:
            self._items.reverse()
            return self._changed()

    @exposed
    def rotate(self, item_id: int, delta: int) -> dict[str, Any]:
        with self._lock:
            item = self._item(item_id)
            item.rotation = (item.rotation + delta) % 360
            return self.state()  # girar no cambia qué páginas entran ni su orden

    # ── Selección de páginas ─────────────────────────────────────────────────
    @exposed
    def toggle(self, item_id: int, page: int) -> dict[str, Any]:
        with self._lock:
            entry = self._item(item_id).entry
            if 0 <= page < entry.total:
                entry.toggle(page)
            return self._changed()

    @exposed
    def select_all(self, item_id: int, value: bool) -> dict[str, Any]:
        with self._lock:
            self._item(item_id).entry.set_all(bool(value))
            return self._changed()

    @exposed
    def invert(self, item_id: int) -> dict[str, Any]:
        with self._lock:
            self._item(item_id).entry.invert()
            return self._changed()

    @exposed
    def set_range(self, item_id: int, text: str) -> dict[str, Any]:
        with self._lock:
            self._item(item_id).entry.set_range(text)
            return self._changed()

    @exposed
    def reorder(self, keys: list[list[int]]) -> dict[str, Any]:
        """Fija el orden de la vista previa (puede intercalar páginas de varios archivos)."""
        with self._lock:
            order = [(int(i), int(p)) for i, p in keys]
            if sorted(order) != sorted(self._preview_keys()):
                raise UserError("La vista previa cambió mientras se reordenaba.", "stale")
            self._custom_order = order
            return self.state()

    # ── Imágenes ─────────────────────────────────────────────────────────────
    @exposed
    def thumbnails(self, item_id: int, pages: list[int]) -> dict[str, str]:
        """Miniaturas ``{página: data URL}`` de las páginas pedidas (las inválidas se omiten)."""
        with self._lock:  # fitz.Document no admite hilos concurrentes
            item = self._item(item_id)
            doc = item.entry.doc
            return {
                str(p): page_data_url(doc[p], THUMB_SCALE, item.rotation, quality=70)
                for p in pages
                if 0 <= p < item.entry.total
            }

    @exposed
    def page_image(self, item_id: int, page: int) -> str:
        with self._lock:
            item = self._item(item_id)
            if not 0 <= page < item.entry.total:
                raise UserError("Página fuera de rango.", "out_of_range")
            return page_data_url(item.entry.doc[page], PREVIEW_SCALE, item.rotation, quality=88)

    # ── Combinar ─────────────────────────────────────────────────────────────
    @exposed
    def choose_output(self) -> dict[str, Any]:
        dest = self._host.save_pdf(self._output or str(Path.home() / "combinado.pdf"))
        with self._lock:
            if dest:
                self._output = dest
            return self.state()

    @exposed
    def merge(self, options: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Combina la vista previa en el archivo de salida; ``None`` si se cancela el destino."""
        if not self._output:
            self.choose_output()
        with self._lock:
            if self._busy:
                raise UserError("Ya hay una combinación en curso.", "busy")
            if not self._output:
                return None
            by_id = {item.id: item for item in self._items}
            pages = [
                MergePage(by_id[i].entry.path, p, by_id[i].rotation) for i, p in self._preview_keys()
            ]
            if not pages:
                raise UserError("No hay páginas seleccionadas para combinar.", "empty")
            passwords = {item.entry.path: item.entry.password for item in self._items}
            out_path = self._output
            self._busy = True

        opts = options or {}
        merge_options = MergeOptions(
            bookmarks=bool(opts.get("bookmarks", True)),
            duplex=bool(opts.get("duplex", False)),
            optimize=bool(opts.get("optimize", True)),
        )
        last_emit = 0.0

        def progress(done: int, total: int) -> None:
            nonlocal last_emit
            now = time.monotonic()
            if done == total or now - last_emit >= _PROGRESS_INTERVAL:
                last_emit = now
                self._host.emit("merge:progress", {"done": done, "total": total})

        try:
            count = engine.merge_pages(pages, out_path, passwords=passwords, options=merge_options, progress=progress)
        except Exception as ex:
            raise UserError(f"No se pudo generar el archivo: {ex}", "merge_failed") from ex
        finally:
            with self._lock:
                self._busy = False
        with self._lock:
            self._last_result = out_path
            return {"count": count, "path": out_path, "state": self.state()}

    @exposed
    def open_result(self) -> None:
        if self._last_result and Path(self._last_result).is_file():
            self._documents.open(self._last_result)

    @exposed
    def open_output_folder(self) -> None:
        if self._output:
            self._host.open_folder(str(Path(self._output).parent))

    def close(self) -> None:
        """Cierra todos los documentos abiertos (al vaciar la lista o salir de la app)."""
        with self._lock:
            for item in self._items:
                item.entry.close()
            self._items.clear()
            self._custom_order = None
