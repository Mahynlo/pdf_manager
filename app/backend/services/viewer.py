"""Servicio ``viewer``: los PDF abiertos en pestañas del visor.

Cada documento abierto recibe un ``id``. Las páginas y miniaturas las dibuja el visor con
EmbedPDF a partir de :meth:`ViewerService.document_url`. pywebview atiende cada llamada en un
hilo propio, así que todo acceso a los documentos pasa por un único candado.

Las operaciones que cambian el documento devuelven su información actualizada
(``_info``): tamaños y claves de página, índice y si hay cambios sin guardar. La clave de cada
página (``id:rotación:revisión``) cambia cuando cambia su imagen (al girarla o censurarla): el
visor vuelve a cargar el documento cuando cambian, así nunca muestra una imagen anterior a la
censura.

Las anotaciones las edita el visor con EmbedPDF sobre su copia del documento. Antes de
que Python necesite el documento al día (guardar, exportar una página, cambiar las páginas o
censurar), el visor sube su copia (:meth:`ViewerService.sync_annotations`), que pasa a ser el
documento. Mientras tanto, :meth:`ViewerService.annotations_changed` avisa de que hay cambios
sin guardar.

Las operaciones de página (girar, insertar, duplicar, borrar, mover) se pueden deshacer y
rehacer (:meth:`ViewerService.undo_pages`): cada una guarda su inversa; la página borrada se
guarda aparte para devolverla.

Las palabras reconocidas por OCR (servicio ``ocr``) se guardan por clave de página.
Entran en la capa de texto (``text_of``: asistente IA, panel de OCR) y van como texto
invisible en el documento que recibe EmbedPDF, que las selecciona y las busca como el
texto nativo. Llevan una marca propia: al volver la copia se quitan, así el texto reconocido
no pasa al archivo.

Censurar lo hace el motor de EmbedPDF (``Host.run_engine``): el PDFium de Python no sabe.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from app.backend.services.documents import RECENT_CHANGED
from pdf_core import page_ops, recent_files
from pdf_core.pdf import Document, Page, PdfError, Rect
from pdf_core.security import PDFInvalidPasswordError, PDFPasswordRequiredError, PDFSecurityManager
from pdf_core.text_layer import TextLayer, build_text_layer, embed_ocr_words

log = logging.getLogger(__name__)

PAGE_UNDO_LIMIT = 30  # operaciones de página que se pueden deshacer


@dataclass
class _PageStep:
    """Una operación de página que se puede deshacer.

    ``redo`` la hace y ``undo`` la deshace; ``page`` y ``undo_page`` son la página a la que ir
    después de cada una (``None``: la actual). ``ocr`` son las palabras de OCR de cada página
    (por posición) antes de la operación: al girar una página se pierden y al deshacer vuelven.
    """

    redo: Callable[[Document], Any]
    undo: Callable[[Document], Any]
    page: int | None
    undo_page: int | None
    copy: Document | None = None  # la página borrada, para devolverla
    ocr: dict[int, list[tuple]] = field(default_factory=dict)

    def close(self) -> None:
        if self.copy is not None:
            self.copy.close()


@dataclass
class _OpenDocument:
    doc: Document
    path: str
    password: str | None
    protected: bool  # cifrado con contraseña
    baseline: tuple = field(default=())  # huella de la estructura al abrir o guardar
    layers: dict[str, TextLayer] = field(default_factory=dict)  # capas de texto por clave de página
    ocr: dict[str, list[tuple]] = field(default_factory=dict)  # palabras de OCR (x0, y0, x1, y1, texto) por clave
    revisions: dict[int, int] = field(default_factory=dict)  # id de página -> veces que cambió su contenido (censura)
    redacted: bool = False  # censura aplicada sin guardar: solo se guarda como copia
    annotated: bool = False  # anotaciones cambiadas en el visor sin guardar
    extras: dict[str, Any] = field(default_factory=dict)  # estado de otros servicios (p. ej. la censura en curso)
    undo: list[_PageStep] = field(default_factory=list)  # operaciones de página hechas
    redo: list[_PageStep] = field(default_factory=list)  # y deshechas

    def key(self, page: Page) -> str:
        """Identifica la imagen de la página: cambia al girarla o al cambiar su contenido."""
        return f"{page.uid}:{page.rotation}:{self.revisions.get(page.uid, 0)}"

    def structure(self) -> tuple:
        """Huella de la estructura de páginas: orden y rotación de cada una.

        Detecta añadir, borrar, duplicar, mover y girar páginas, y también su reversión (girar
        90° y volver a 0° deja la misma huella).
        """
        return tuple((page.uid, page.rotation) for page in self.doc)

    def mark_saved(self) -> None:
        self.baseline = self.structure()
        self.redacted = False
        self.annotated = False

    @property
    def modified(self) -> bool:
        return self.redacted or self.annotated or self.structure() != self.baseline


class ViewerService:
    def __init__(self, host: Host) -> None:
        self._host = host
        self._docs: dict[int, _OpenDocument] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ── Abrir / cerrar ───────────────────────────────────────────────────
    @exposed
    def open(self, path: str, password: str | None = None) -> dict[str, Any]:
        """Abre ``path`` (o devuelve el ya abierto) y lo añade a recientes.

        Errores: ``password_required`` / ``invalid_password`` para que el frontend
        pida la contraseña y reintente.
        """
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise UserError(f"Archivo no encontrado: {resolved.name}", "not_found")
        path = str(resolved)
        with self._lock:
            existing = next((i for i, d in self._docs.items() if d.path == path), None)
            if existing is not None:
                return self._info(existing)
            try:
                doc = PDFSecurityManager.open_for_viewer(path, password=password or None)
            except PDFPasswordRequiredError as ex:
                raise UserError("El PDF está protegido con contraseña", "password_required") from ex
            except PDFInvalidPasswordError as ex:
                raise UserError("Contraseña incorrecta", "invalid_password") from ex
            except Exception as ex:
                log.exception("No se pudo abrir %s", path)
                raise UserError(f"No se pudo abrir {resolved.name}: {ex}", "open_failed") from ex
            doc_id = next(self._ids)
            entry = _OpenDocument(doc, path, password or None, doc.encrypted)
            entry.mark_saved()
            self._docs[doc_id] = entry
            info = self._info(doc_id)
        self._push_recent(path)
        return info

    @exposed
    def close_document(self, doc_id: int) -> None:
        with self._lock:
            entry = self._docs.pop(doc_id, None)
            if entry is not None:
                self._close(entry)

    def close(self) -> None:
        """Cierra todos los documentos (al salir de la aplicación)."""
        with self._lock:
            for entry in self._docs.values():
                self._close(entry)
            self._docs.clear()

    def unsaved_documents(self) -> list[str]:
        """Nombres de los documentos con cambios sin guardar (aviso al salir)."""
        with self._lock:
            return [Path(d.path).name for d in self._docs.values() if d.modified]

    @staticmethod
    def _close(entry: _OpenDocument) -> None:
        for step in (*entry.undo, *entry.redo):
            step.close()
        try:
            entry.doc.close()
        except Exception:
            log.debug("Error al cerrar %s", entry.path, exc_info=True)

    # ── Páginas ──────────────────────────────────────────────────────────
    @exposed
    def document_url(self, doc_id: int) -> dict[str, Any]:
        """URL de un solo uso con el documento tal como está abierto, para dibujarlo con PDFium.

        Con la censura aplicada, las páginas giradas o movidas, las anotaciones (las edita
        EmbedPDF) y el texto reconocido por OCR escrito como texto invisible (así EmbedPDF lo
        selecciona como el nativo; no pasa al documento: ver :meth:`sync_annotations`). Un PDF
        cifrado sigue cifrado, para que la copia que vuelve conserve el cifrado: ``password`` es
        la contraseña con la que abrirlo. Viaja en binario por ``host.share_bytes``: por el
        puente, en base64, un PDF grande tardaría segundos. ``keys`` son las claves de página de
        esta versión: si cambian, el visor lo vuelve a pedir.
        """
        with self._lock:
            entry = self._doc(doc_id)
            data = entry.doc.to_bytes()
            keys = [entry.key(page) for page in entry.doc]
            ocr = {i: list(entry.ocr[key]) for i, key in enumerate(keys) if entry.ocr.get(key)}
            password = entry.password
            if ocr:
                data = _with_ocr_text(data, ocr, password)
        return {"url": self._host.share_bytes(data, "application/pdf"), "keys": keys, "password": password}

    @exposed
    def print_url(self, doc_id: int) -> str:
        """URL de un solo uso con el documento sin cifrar, para imprimir un PDF cifrado."""
        with self._lock:
            data = self._doc(doc_id).doc.to_bytes(decrypt=True)
        return self._host.share_bytes(data, "application/pdf")

    # ── Texto ────────────────────────────────────────────────────────────
    @staticmethod
    def _layer(entry: _OpenDocument, page: Page) -> TextLayer:
        key = entry.key(page)
        layer = entry.layers.get(key)
        if layer is None:
            layer = entry.layers[key] = build_text_layer(page, entry.ocr.get(key))
        return layer

    # ── Para el servicio ``ocr`` (llamar dentro de ``document``) ─────────
    @contextmanager
    def document(self, doc_id: int) -> Iterator[_OpenDocument]:
        """El documento abierto ``doc_id`` con el candado tomado."""
        with self._lock:
            yield self._doc(doc_id)

    @staticmethod
    def page(entry: _OpenDocument, index: int) -> Page:
        ViewerService._check_index(entry.doc, index)
        return entry.doc[index]

    @staticmethod
    def page_key(entry: _OpenDocument, page: Page) -> str:
        return entry.key(page)

    def set_ocr_words(self, entry: _OpenDocument, page: Page, words: list[tuple], merge: bool = False) -> TextLayer:
        """Guarda las palabras de OCR de ``page`` (o las añade, con ``merge``); devuelve su nueva capa de texto."""
        key = entry.key(page)
        entry.ocr[key] = [*entry.ocr.get(key, []), *words] if merge else list(words)
        entry.layers.pop(key, None)
        return self._layer(entry, page)

    def text_of(self, entry: _OpenDocument, page: Page) -> TextLayer:
        """Capa de texto de ``page``: texto nativo más el de OCR."""
        return self._layer(entry, page)

    # ── Operaciones de página ────────────────────────────────────────────
    @exposed
    def rotate(self, doc_id: int, angle: int, index: int | None = None) -> dict[str, Any]:
        """Gira la página ``index`` (o todas si es ``None``) ``angle`` grados."""
        if angle % 90:
            raise UserError("El giro debe ser múltiplo de 90°.", "bad_angle")

        def step(doc: Document) -> _PageStep:
            pages = range(len(doc)) if index is None else [index]
            return _PageStep(
                redo=lambda d: page_ops.rotate_pages(d, pages, angle),
                undo=lambda d: page_ops.rotate_pages(d, pages, -angle),
                page=index,
                undo_page=index,
            )

        return self._modify(doc_id, step, index)

    @exposed
    def insert_blank(self, doc_id: int, after: int) -> dict[str, Any]:
        def step(doc: Document) -> _PageStep:
            return _PageStep(
                redo=lambda d: page_ops.insert_blank_page(d, after),
                undo=lambda d: d.delete_page(after + 1),
                page=after + 1,
                undo_page=after,
            )

        return self._modify(doc_id, step, after)

    @exposed
    def duplicate(self, doc_id: int, index: int) -> dict[str, Any]:
        def step(doc: Document) -> _PageStep:
            return _PageStep(
                redo=lambda d: page_ops.duplicate_page(d, index),
                undo=lambda d: d.delete_page(index + 1),
                page=index + 1,
                undo_page=index,
            )

        return self._modify(doc_id, step, index)

    @exposed
    def delete_page(self, doc_id: int, index: int) -> dict[str, Any]:
        def step(doc: Document) -> _PageStep:
            if len(doc) <= 1:
                raise UserError("No se puede eliminar la única página del documento.", "last_page")
            copy = Document.new()
            copy.insert_pages(doc, [index], uids=[doc[index].uid])  # con sus anotaciones
            return _PageStep(
                redo=lambda d: d.delete_page(index),
                undo=lambda d: d.insert_pages(copy, [0], index, uids=copy.uids),
                page=max(0, index - 1),
                undo_page=index,
                copy=copy,
            )

        return self._modify(doc_id, step, index)

    @exposed
    def move_page(self, doc_id: int, src: int, dst: int) -> dict[str, Any]:
        """Mueve ``src`` a la posición final ``dst`` (botones o arrastrar miniaturas)."""

        def step(doc: Document) -> _PageStep:
            self._check_index(doc, dst)
            return _PageStep(
                redo=lambda d: d.move_page(src, dst),
                undo=lambda d: d.move_page(dst, src),
                page=dst,
                undo_page=src,
            )

        return self._modify(doc_id, step, src)

    @exposed
    def undo_pages(self, doc_id: int) -> dict[str, Any]:
        """Deshace la última operación de página. Devuelve ``{info, page}`` (``page``: a cuál ir, o ``None``)."""
        with self._lock:
            entry = self._doc(doc_id)
            if not entry.undo:
                raise UserError("No hay operaciones de página que deshacer.", "nothing_to_undo")
            step = entry.undo.pop()
            step.undo(entry.doc)
            # Vuelven las palabras de OCR que se perdieron (sin pisar las reconocidas después).
            for index, words in step.ocr.items():
                entry.ocr.setdefault(entry.key(entry.doc[index]), words)
            entry.redo.append(step)
            return {"info": self._info(doc_id), "page": step.undo_page}

    @exposed
    def redo_pages(self, doc_id: int) -> dict[str, Any]:
        """Rehace la última operación de página deshecha. Devuelve ``{info, page}``."""
        with self._lock:
            entry = self._doc(doc_id)
            if not entry.redo:
                raise UserError("No hay operaciones de página que rehacer.", "nothing_to_redo")
            step = entry.redo.pop()
            step.redo(entry.doc)
            entry.undo.append(step)
            return {"info": self._info(doc_id), "page": step.page}

    def _modify(self, doc_id: int, make_step: Callable[[Document], _PageStep], index: int | None) -> dict[str, Any]:
        """Hace la operación que da ``make_step(doc)`` y la apunta para deshacerla."""
        with self._lock:
            entry = self._doc(doc_id)
            doc = entry.doc
            if index is not None:
                self._check_index(doc, index)
            step = make_step(doc)
            step.ocr = {i: entry.ocr[k] for i, page in enumerate(doc) if (k := entry.key(page)) in entry.ocr}
            step.redo(doc)  # las anotaciones van con su página (el visor las sincronizó antes)
            entry.undo.append(step)
            for old in (*entry.redo, *entry.undo[:-PAGE_UNDO_LIMIT]):
                old.close()
            entry.redo.clear()
            del entry.undo[:-PAGE_UNDO_LIMIT]
            return self._info(doc_id)

    # ── Censura (la usa el servicio ``redact``) ──────────────────────────
    def apply_redaction_marks(self, doc_id: int) -> tuple[dict[str, Any], int]:
        """Aplica las marcas de censura del documento (las pone el visor y llegan con
        :meth:`sync_annotations`) y borra para siempre lo que hay debajo, también las palabras
        de OCR que tapan. Devuelve la información del documento y cuántas marcas se aplicaron."""
        with self._lock:
            entry = self._doc(doc_id)
            marks = {page.number: rects for page in entry.doc if (rects := page.redact_rects())}
            if not marks:
                return self._info(doc_id), 0
            try:
                data = self._host.run_engine("redact", entry.doc.to_bytes(), {"password": entry.password})
                self._replace(entry, Document.open(data, entry.password))
            except (RuntimeError, PdfError) as ex:
                log.exception("No se pudo aplicar la censura")
                raise UserError(f"No se pudo aplicar la censura: {ex}", "redact_failed") from ex
            for index, rects in marks.items():
                page = entry.doc[index]
                old_key = entry.key(page)
                entry.revisions[page.uid] = entry.revisions.get(page.uid, 0) + 1
                entry.layers.pop(old_key, None)
                words = entry.ocr.pop(old_key, None)
                if words:  # las palabras de OCR están en la página vista
                    shown = [page.to_view(r) for r in rects]
                    entry.ocr[entry.key(page)] = [w for w in words if not any(Rect(*w[:4]).intersects(r) for r in shown)]
            entry.redacted = True
            return self._info(doc_id), sum(map(len, marks.values()))

    @staticmethod
    def _replace(entry: _OpenDocument, doc: Document) -> None:
        """``doc``, con las mismas páginas, pasa a ser el documento abierto."""
        doc.adopt_uids(entry.doc)
        old, entry.doc = entry.doc, doc
        old.close()

    # ── Anotaciones (las edita el visor con EmbedPDF) ────────────────────
    @exposed
    def upload_url(self) -> str:
        """URL a la que el visor sube su copia del documento (ver :meth:`sync_annotations`)."""
        return self._host.upload_url()

    @exposed
    def sync_annotations(self, doc_id: int, upload: str) -> dict[str, Any]:
        """La copia del visor, subida a ``upload`` (de :meth:`upload_url`), pasa a ser el documento.

        Se llama antes de todo lo que necesita el documento al día. El texto de OCR que lleva
        como texto invisible no pasa al documento. Devuelve ``{modified}``.
        """
        data = self._host.uploaded(upload)
        if data is None:
            raise UserError("No llegó la copia del documento con las anotaciones.", "upload_missing")
        with self._lock:
            entry = self._doc(doc_id)
            try:
                copy = Document.open(data, entry.password)
            except PdfError as ex:
                log.exception("No se pudo leer la copia del visor")
                raise UserError(f"No se pudieron pasar las anotaciones al documento: {ex}", "sync_failed") from ex
            if len(copy) != len(entry.doc):
                copy.close()
                raise UserError("La copia del visor no coincide con el documento.", "sync_failed")
            for page in copy:
                if entry.ocr.get(entry.key(entry.doc[page.number])):
                    page.remove_invisible_text()
            self._replace(entry, copy)
            entry.annotated = True
            return {"modified": entry.modified}

    @exposed
    def annotations_changed(self, doc_id: int) -> dict[str, Any]:
        """El visor cambió las anotaciones: hay cambios sin guardar (aviso al cerrar). Devuelve ``{modified}``."""
        with self._lock:
            entry = self._doc(doc_id)
            entry.annotated = True
            return {"modified": entry.modified}

    # ── Guardar ──────────────────────────────────────────────────────────
    @exposed
    def save(self, doc_id: int) -> dict[str, Any]:
        """Guarda sobre el archivo original (Ctrl+S).

        Errores: ``save_not_allowed`` (permisos del PDF), ``permission_denied`` (no se
        puede escribir el archivo) y ``redacted`` (con censura aplicada no se sobrescribe
        el original); en los dos últimos el frontend ofrece «Guardar como».
        """
        with self._lock:
            entry = self._doc(doc_id)
            self._check_can_save(entry)
            if entry.redacted:
                raise UserError(
                    "Este documento tiene censura aplicada.\nElige dónde guardar la copia para conservar el original.",
                    "redacted",
                )
            try:
                Path(entry.path).write_bytes(entry.doc.to_bytes())
            except PermissionError as ex:
                raise UserError(
                    "No hay permiso para sobrescribir el archivo original. Selecciona otra ubicación.",
                    "permission_denied",
                ) from ex
            except OSError as ex:
                raise UserError(f"No se pudo guardar el archivo: {ex}", "save_failed") from ex
            entry.mark_saved()
            info = self._info(doc_id)
        self._push_recent(info["path"])
        return info

    @exposed
    def save_as(self, doc_id: int) -> dict[str, Any] | None:
        """Guarda una copia donde elija el usuario; la pestaña pasa a ser ese archivo. ``None`` si se cancela."""
        with self._lock:
            entry = self._doc(doc_id)
            self._check_can_save(entry)
            suggested = Path(entry.path)
            if entry.redacted:
                suggested = suggested.with_name(f"{suggested.stem}_censurado{suggested.suffix}")
        dest = self._host.save_pdf(str(suggested))  # sin el candado: el diálogo puede tardar
        if not dest:
            return None
        target = Path(dest)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(f"{target.name}.pdf")
        target = target.resolve()
        with self._lock:
            entry = self._doc(doc_id)
            try:
                target.write_bytes(entry.doc.to_bytes())
            except OSError as ex:
                raise UserError(f"No se pudo guardar el archivo: {ex}", "save_failed") from ex
            entry.path = str(target)
            entry.mark_saved()
            info = self._info(doc_id)
        self._push_recent(info["path"])
        return info

    @staticmethod
    def _check_can_save(entry: _OpenDocument) -> None:
        if not PDFSecurityManager.can_save_changes(entry.doc):
            raise UserError("Este PDF no permite guardar cambios por sus permisos de seguridad.", "save_not_allowed")

    # ── Exportar ─────────────────────────────────────────────────────────
    @exposed
    def extract_page(self, doc_id: int, index: int) -> str | None:
        """Guarda la página ``index`` como un PDF nuevo; devuelve su ruta (``None`` si se cancela)."""
        with self._lock:
            entry = self._doc(doc_id)
            self._check_index(entry.doc, index)
            source = Path(entry.path)
        dest = self._host.save_pdf(str(source.with_name(f"{source.stem}_pagina_{index + 1}.pdf")))
        if not dest:
            return None
        target = dest if dest.lower().endswith(".pdf") else f"{dest}.pdf"
        with self._lock:
            data = page_ops.extract_pages(self._doc(doc_id).doc, [index])  # con sus anotaciones
        self._write(target, data)
        self._push_recent(target)
        return target

    @exposed
    def export_text(self, doc_id: int) -> str | None:
        with self._lock:
            source = Path(self._doc(doc_id).path)
        dest = self._host.save_text(str(source.with_name(f"{source.stem}_texto.txt")))
        if not dest:
            return None
        with self._lock:
            entry = self._doc(doc_id)
            ocr_text = {
                i: " ".join(w[4] for w in entry.ocr[key])
                for i, page in enumerate(entry.doc)
                if (key := entry.key(page)) in entry.ocr
            }
            text = page_ops.document_text(entry.doc, ocr_text)
        self._write(dest, text.encode("utf-8"))
        return dest

    @exposed
    def export_images(self, doc_id: int) -> dict[str, Any] | None:
        """Extrae las imágenes incrustadas a una carpeta; ``{folder, count}`` o ``None`` si se cancela."""
        with self._lock:
            stem = Path(self._doc(doc_id).path).stem
        folder = self._host.pick_folder()
        if not folder:
            return None
        with self._lock:
            try:
                count = page_ops.export_images(self._doc(doc_id).doc, Path(folder), stem)
            except OSError as ex:
                raise UserError(f"No se pudieron extraer las imágenes: {ex}", "export_failed") from ex
        return {"folder": folder, "count": count}

    @staticmethod
    def _write(path: str, data: bytes) -> None:
        try:
            Path(path).write_bytes(data)
        except OSError as ex:
            raise UserError(f"No se pudo guardar {Path(path).name}: {ex}", "save_failed") from ex

    # ── Propiedades ──────────────────────────────────────────────────────
    @exposed
    def properties(self, doc_id: int) -> dict[str, Any]:
        """Metadatos, tamaño y seguridad (diálogo «Propiedades del documento»)."""
        with self._lock:
            entry = self._doc(doc_id)
            doc, path = entry.doc, Path(entry.path)
            meta = doc.metadata or {}
            size = path.stat().st_size if path.is_file() else None
            rows = [
                ("Ubicación:", str(path)),
                ("Tamaño:", f"{size / (1024 * 1024):.2f} MB ({size:,} bytes)" if size is not None else "Desconocido"),
                ("Páginas:", f"{len(doc)} página(s)"),
            ]
            if len(doc):
                first = doc[0]
                w, h = first.rect.width, first.rect.height
                rows += [
                    (
                        "Dimensiones pág. 1:",
                        f"{w * 0.352778:.1f} × {h * 0.352778:.1f} mm  "
                        f"({w / 72:.2f} × {h / 72:.2f} in / {w:.0f} × {h:.0f} pt)",
                    ),
                    ("Rotación inicial:", f"{first.rotation}°"),
                ]
            labels = {
                "title": "Título:", "author": "Autor:", "subject": "Asunto:", "keywords": "Palabras clave:",
                "creator": "Creador:", "producer": "Productor:", "creationDate": "Fecha de creación:",
                "modDate": "Fecha de modificación:",
            }
            rows += [(label, meta.get(key) or "") for key, label in labels.items()]
            rows += [
                ("Versión PDF:", f"PDF {doc.version or '1.7'}"),
                ("Cifrado / Seguridad:", "Protegido con contraseña" if entry.protected else "Sin cifrado"),
            ]
            return {"title": path.name, "rows": [{"label": k, "value": v or "(No especificado)"} for k, v in rows]}

    # ── Auxiliares ───────────────────────────────────────────────────────
    def _doc(self, doc_id: int) -> _OpenDocument:
        entry = self._docs.get(doc_id)
        if entry is None:
            raise UserError("El documento ya no está abierto.", "not_open")
        return entry

    @staticmethod
    def _check_index(doc: Document, index: int) -> None:
        if not 0 <= index < len(doc):
            raise UserError("Página fuera de rango.", "bad_page")

    def _page(self, doc_id: int, index: int) -> Page:
        doc = self._doc(doc_id).doc
        self._check_index(doc, index)
        return doc[index]

    def _push_recent(self, path: str) -> None:
        recent_files.push(path)
        self._host.emit(RECENT_CHANGED)

    def _info(self, doc_id: int) -> dict[str, Any]:
        """Lo que el frontend necesita para maquetar: tamaño y clave de cada página (pt), índice y estado."""
        entry = self._docs[doc_id]
        doc = entry.doc
        pages = list(doc)
        keys = [entry.key(p) for p in pages]
        alive = set(keys)
        entry.layers = {k: v for k, v in entry.layers.items() if k in alive}
        entry.ocr = {k: v for k, v in entry.ocr.items() if k in alive}  # al girar una página su OCR ya no vale
        return {
            "id": doc_id,
            "path": entry.path,
            "name": Path(entry.path).name,
            "pages": [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in pages],
            "keys": keys,
            "toc": [{"level": lvl, "title": title, "page": page or 0} for lvl, title, page in doc.toc()],
            "modified": entry.modified,
            "redacted": entry.redacted,
            "page_undo": bool(entry.undo),  # hay operaciones de página que deshacer / rehacer
            "page_redo": bool(entry.redo),
        }


def _with_ocr_text(data: bytes, ocr: dict[int, list[tuple]], password: str | None) -> bytes:
    """Copia del PDF ``data`` con las palabras de OCR de cada página como texto invisible."""
    with Document.open(data, password) as doc:
        for index, words in ocr.items():
            embed_ocr_words(doc[index], words)
        return doc.to_bytes()
