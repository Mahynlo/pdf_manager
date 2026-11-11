"""Servicio ``viewer``: los PDF abiertos en pestañas del visor.

Cada documento abierto recibe un ``id``. pywebview atiende cada llamada en un hilo propio, así que
todo acceso a los documentos pasa por un único candado.

El dueño del documento abierto es el visor: lo abre en EmbedPDF (:meth:`ViewerService.document_url`
le da el archivo), edita las anotaciones, hace las operaciones de página y la censura con su motor y
da el ``id`` de cada página. Python no tiene el PDF abierto. Guarda de cada documento:

- **la clave de cada página** (``id:giro:revisión``), que le da el visor (:meth:`set_pages`): con
  ella sabe si la estructura es la guardada (cambios sin guardar);
- **el texto de cada página**, por clave, que también le da el visor con su motor
  (:meth:`add_texts`, solo el de las páginas que aún no tiene). Con él trabajan la capa de texto
  (``text_of``: asistente IA, panel de OCR, exportar texto) y la búsqueda de la censura;
- **las palabras reconocidas por OCR** (servicio ``ocr``), por clave. Entran en la capa de texto, y
  el visor las escribe en su documento como texto invisible, que EmbedPDF selecciona y busca como
  el texto nativo (al abrirlo, las de :meth:`document_url`). No pasan al archivo;
- lo que dice el archivo (metadatos, si los permisos dejan guardar, tamaños e índice) y el estado:
  censura aplicada, anotaciones cambiadas y el de otros servicios (``extras``).

Al guardar, el visor sube su copia y Python la escribe tal cual (:meth:`save`); al extraer una
página, sube ese PDF (:meth:`extract_page`); para exportar sus imágenes, una copia que se usa y se
suelta (:meth:`export_images`).

Los archivos se leen y se escriben con el ``Host`` (``read_file``, ``write_file``, ``file_url``),
nunca con rutas directamente: en el navegador los tiene la ventana, no Python.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from app.backend.services.documents import RECENT_CHANGED
from pdf_core import page_ops, recent_files
from pdf_core.pdf import Document, PackedPageText, PageText, PdfError, Rect, unpack_page_texts
from pdf_core.security import PDFInvalidPasswordError, PDFPasswordRequiredError, PDFSecurityManager
from pdf_core.text_layer import TextLayer, build_text_layer

log = logging.getLogger(__name__)


def _structure(keys: list[str]) -> tuple[str, ...]:
    """Qué página va en cada sitio y con qué giro (la clave sin la revisión).

    Detecta añadir, borrar, duplicar, mover y girar páginas, y también su reversión."""
    return tuple(key.rsplit(":", 1)[0] for key in keys)


def _file_layout(doc: Document) -> dict[str, Any]:
    """Lo que el visor necesita para maquetar un archivo antes de abrirlo: tamaño de cada página
    (pt, tal como se ve) e índice."""
    return {
        "pages": [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in doc],
        "toc": [{"level": lvl, "title": title, "page": page or 0} for lvl, title, page in doc.toc()],
    }


@dataclass
class _OpenDocument:
    path: str
    password: str | None
    keys: list[str]  # clave de cada página, en orden (las da el visor)
    file_keys: list[str]  # las del archivo en disco (al abrirlo y al guardarlo)
    layout: dict[str, Any]  # tamaños e índice del archivo en disco
    metadata: dict[str, str] = field(default_factory=dict)
    can_save: bool = True  # los permisos del PDF dejan guardar cambios
    baseline: tuple[str, ...] = ()  # estructura del archivo en disco
    texts: dict[str, PackedPageText] = field(default_factory=dict)  # texto de cada página por clave
    layers: dict[str, TextLayer] = field(default_factory=dict)  # capas de texto por clave
    ocr: dict[str, list[tuple]] = field(default_factory=dict)  # palabras de OCR (x0, y0, x1, y1, texto) por clave
    redacted: bool = False  # censura aplicada sin guardar: solo se guarda como copia
    annotated: bool = False  # anotaciones cambiadas en el visor sin guardar
    extras: dict[str, Any] = field(default_factory=dict)  # estado de otros servicios (p. ej. la censura en curso)

    def mark_saved(self) -> None:
        self.file_keys = list(self.keys)
        self.baseline = _structure(self.keys)
        self.redacted = False
        self.annotated = False

    @property
    def modified(self) -> bool:
        return self.redacted or self.annotated or _structure(self.keys) != self.baseline


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

        Lo lee una vez, para comprobar la contraseña y dar al visor lo que necesita para
        maquetarlo antes de abrirlo (ver :meth:`_file_info`). Errores: ``password_required`` /
        ``invalid_password`` para que el frontend pida la contraseña y reintente.
        """
        resolved = Path(path).resolve()
        path = str(resolved)
        with self._lock:
            existing = next((i for i, d in self._docs.items() if d.path == path), None)
            if existing is not None:
                return self._file_info(existing)
            try:
                data = self._host.read_file(path)
            except FileNotFoundError as ex:
                raise UserError(f"Archivo no encontrado: {resolved.name}", "not_found") from ex
            except OSError as ex:
                raise UserError(f"No se pudo leer {resolved.name}: {ex}", "open_failed") from ex
            try:
                doc = PDFSecurityManager.open_for_viewer(data, password=password or None)
            except PDFPasswordRequiredError as ex:
                raise UserError("El PDF está protegido con contraseña", "password_required") from ex
            except PDFInvalidPasswordError as ex:
                raise UserError("Contraseña incorrecta", "invalid_password") from ex
            except Exception as ex:
                log.exception("No se pudo abrir %s", path)
                raise UserError(f"No se pudo abrir {resolved.name}: {ex}", "open_failed") from ex
            with doc:
                keys = [f"{page.uid}:{page.rotation}:0" for page in doc]
                entry = _OpenDocument(path, password or None, keys, list(keys), _file_layout(doc),
                                      dict(doc.metadata or {}), PDFSecurityManager.can_save_changes(doc))
            entry.mark_saved()
            doc_id = next(self._ids)
            self._docs[doc_id] = entry
            info = self._file_info(doc_id)
        self._push_recent(path)
        return info

    @exposed
    def close_document(self, doc_id: int) -> None:
        with self._lock:
            self._docs.pop(doc_id, None)

    def close(self) -> None:
        """Olvida todos los documentos (al salir de la aplicación)."""
        with self._lock:
            self._docs.clear()

    def unsaved_documents(self) -> list[str]:
        """Nombres de los documentos con cambios sin guardar (aviso al salir)."""
        with self._lock:
            return [Path(d.path).name for d in self._docs.values() if d.modified]

    # ── El documento para EmbedPDF ───────────────────────────────────────
    @exposed
    def document_url(self, doc_id: int) -> dict[str, Any]:
        """URL de un solo uso con el archivo, para abrirlo en EmbedPDF (``host.file_url``: viaja
        en binario, sin pasar por el puente, y en el navegador sin pasar por Python).

        Un PDF cifrado sigue cifrado, para que la copia que vuelve conserve el cifrado:
        ``password`` es la contraseña con la que abrirlo. ``keys`` son las claves de sus páginas y
        ``ocr``, las palabras reconocidas de cada página que las tiene (``{index, words}``), que el
        visor escribe en el documento como texto invisible.
        """
        with self._lock:
            entry = self._doc(doc_id)
            path, password, keys = entry.path, entry.password, list(entry.file_keys)
            ocr = [{"index": i, "words": list(entry.ocr[key])} for i, key in enumerate(keys) if entry.ocr.get(key)]
        try:
            url = self._host.file_url(path)
        except OSError as ex:
            raise UserError(f"No se pudo leer {Path(path).name}: {ex}", "open_failed") from ex
        return {"url": url, "keys": keys, "password": password, "ocr": ocr}

    # ── Páginas y texto (los da el visor) ────────────────────────────────
    @exposed
    def set_pages(self, doc_id: int, keys: list[str]) -> dict[str, Any]:
        """Las páginas que tiene ahora el documento del visor: la clave de cada una, en orden.

        Se llama antes de lo que lee el texto del documento. Devuelve ``{missing, modified}``:
        ``missing``, las páginas (por su posición) cuyo texto aún no tiene Python, que el visor le
        pasa con :meth:`add_texts`.
        """
        if not all(isinstance(key, str) and key.count(":") == 2 for key in keys):
            raise UserError("Las páginas del visor no son válidas.", "bad_pages")
        with self._lock:
            entry = self._doc(doc_id)
            entry.keys = list(keys)
            missing = [i for i, key in enumerate(keys) if key not in entry.texts]
            return {"missing": missing, "modified": entry.modified}

    @exposed
    def add_texts(self, doc_id: int, upload: str, pages: list[dict[str, Any]]) -> None:
        """El texto de unas páginas, que el visor subió a ``upload`` (de :meth:`upload_url`) con su
        motor (``lib/pdf-engine/page-text.ts``). ``pages``: ``{index, geometry, count}`` de cada una
        (``index``, su posición en lo último que dio :meth:`set_pages`)."""
        data = self.received(upload)
        try:
            texts = unpack_page_texts(pages, data)
        except (PdfError, KeyError, TypeError, ValueError) as ex:
            raise UserError("No llegó bien el texto de las páginas.", "bad_texts") from ex
        with self._lock:
            entry = self._doc(doc_id)
            for index, text in texts:
                key = self.page_key(entry, index)
                entry.texts[key] = text
                entry.layers.pop(key, None)

    @exposed
    def upload_url(self) -> str:
        """URL a la que el visor sube lo que le pasa a Python: su copia del documento, el texto de
        las páginas o imágenes de página (servicio ``ocr``)."""
        return self._host.upload_url()

    def received(self, upload: str) -> bytes:
        """Lo que subió el visor a ``upload`` (de :meth:`upload_url`)."""
        data = self._host.uploaded(upload)
        if data is None:
            raise UserError("No llegó lo que envió el visor.", "upload_missing")
        return data

    # ── Para los servicios ``ocr``, ``redact`` y ``ai`` (dentro de ``document``) ──
    @contextmanager
    def document(self, doc_id: int) -> Iterator[_OpenDocument]:
        """El documento abierto ``doc_id`` con el candado tomado."""
        with self._lock:
            yield self._doc(doc_id)

    @staticmethod
    def page_key(entry: _OpenDocument, index: int) -> str:
        if not 0 <= index < len(entry.keys):
            raise UserError("Página fuera de rango.", "bad_page")
        return entry.keys[index]

    @staticmethod
    def packed_text(entry: _OpenDocument, index: int) -> PackedPageText:
        """El texto de la página ``index`` (sin el de OCR) tal como lo dio el visor: su texto y lo
        que usa la búsqueda salen sin desempaquetarlo. El visor tiene que habérselo dado
        (``set_pages`` y ``add_texts``): si no, ``text_missing``."""
        packed = entry.texts.get(ViewerService.page_key(entry, index))
        if packed is None:
            raise UserError("Falta el texto de la página: vuelve a intentarlo.", "text_missing")
        return packed

    @staticmethod
    def page_text(entry: _OpenDocument, index: int) -> PageText:
        """Como :meth:`packed_text`, pero entero: cada carácter con su posición."""
        return ViewerService.packed_text(entry, index).unpack()

    def text_of(self, entry: _OpenDocument, index: int) -> TextLayer:
        """Capa de texto de la página ``index`` en orden de lectura: texto nativo más el de OCR."""
        key = self.page_key(entry, index)
        layer = entry.layers.get(key)
        if layer is None:
            layer = entry.layers[key] = build_text_layer(self.page_text(entry, index), entry.ocr.get(key))
        return layer

    @staticmethod
    def set_ocr_words(entry: _OpenDocument, key: str, words: list[tuple], merge: bool = False) -> None:
        """Guarda las palabras de OCR de la página de clave ``key`` (o las añade, con ``merge``)."""
        entry.ocr[key] = [*entry.ocr.get(key, []), *words] if merge else list(words)
        entry.layers.pop(key, None)

    def redaction_applied(self, doc_id: int, pages: list[dict[str, Any]]) -> None:
        """El visor aplicó la censura en su documento (servicio ``redact``). ``pages``: ``{before,
        after, rects}`` de cada página censurada: su clave antes y después (sube la revisión, porque
        cambia su imagen) y los rectángulos de las marcas, en coordenadas de página.

        Las palabras de OCR que tapaban las marcas se borran para siempre (en el documento del
        visor ya no están: la censura de EmbedPDF borra también ese texto); las demás pasan a la
        clave nueva. Python tiene que tener el texto de esas páginas (sus medidas, para pasar las
        marcas a la página vista).
        """
        with self._lock:
            entry = self._doc(doc_id)
            for page in pages:
                before, after = str(page["before"]), str(page["after"])
                packed = entry.texts.get(before)
                words = entry.ocr.pop(before, [])
                if words and packed is None:
                    raise UserError("Falta el texto de la página: vuelve a intentarlo.", "text_missing")
                if words:
                    shown = [packed.geometry.to_view(rect) for rect in page["rects"]]
                    entry.ocr[after] = [w for w in words if not any(Rect(*w[:4]).intersects(r) for r in shown)]
                entry.texts.pop(before, None)  # su contenido cambió: el visor da el nuevo
                entry.layers.pop(before, None)
            entry.redacted = True

    # ── Anotaciones (las edita el visor con EmbedPDF) ────────────────────
    @exposed
    def annotations_changed(self, doc_id: int) -> dict[str, Any]:
        """El visor cambió las anotaciones: hay cambios sin guardar (aviso al cerrar). Devuelve ``{modified}``."""
        with self._lock:
            entry = self._doc(doc_id)
            entry.annotated = True
            return {"modified": entry.modified}

    # ── Guardar ──────────────────────────────────────────────────────────
    @exposed
    def save(self, doc_id: int, upload: str, keys: list[str]) -> dict[str, Any]:
        """Guarda sobre el archivo original (Ctrl+S) la copia del visor subida a ``upload``.

        La copia se escribe tal cual (la saca el motor del visor); ``keys``: la clave de cada una
        de sus páginas. Errores: ``save_not_allowed`` (permisos del PDF), ``permission_denied`` (no
        se puede escribir el archivo) y ``redacted`` (con censura aplicada no se sobrescribe el
        original); en los dos últimos el frontend ofrece «Guardar como».
        """
        data = self.received(upload)
        with self._lock:
            entry = self._doc(doc_id)
            self._check_can_save(entry)
            if entry.redacted:
                raise UserError(
                    "Este documento tiene censura aplicada.\nElige dónde guardar la copia para conservar el original.",
                    "redacted",
                )
            try:
                self._save_copy(entry, data, keys, Path(entry.path))
            except PermissionError as ex:
                raise UserError(
                    "No hay permiso para sobrescribir el archivo original. Selecciona otra ubicación.",
                    "permission_denied",
                ) from ex
            except OSError as ex:
                raise UserError(f"No se pudo guardar el archivo: {ex}", "save_failed") from ex
            info = self._info(doc_id)
        self._push_recent(info["path"])
        return info

    @exposed
    def save_as(self, doc_id: int, upload: str, keys: list[str]) -> dict[str, Any] | None:
        """Guarda la copia del visor (como en :meth:`save`) donde elija el usuario; la pestaña
        pasa a ser ese archivo. ``None`` si se cancela."""
        data = self.received(upload)
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
                self._save_copy(entry, data, keys, target)
            except OSError as ex:
                raise UserError(f"No se pudo guardar el archivo: {ex}", "save_failed") from ex
            entry.path = str(target)
            info = self._info(doc_id)
        self._push_recent(info["path"])
        return info

    def _save_copy(self, entry: _OpenDocument, data: bytes, keys: list[str], target: Path) -> None:
        """Escribe tal cual en ``target`` la copia del visor ``data``, con las páginas ``keys``.

        Se abre antes de escribirla: nunca se escribe una copia que no se pueda leer.
        """
        try:
            with Document.open(data, entry.password) as copy:
                if len(copy) != len(keys):
                    raise UserError("La copia del visor no coincide con el documento.", "sync_failed")
                layout, metadata = _file_layout(copy), dict(copy.metadata or {})
        except PdfError as ex:
            log.exception("No se pudo leer la copia del visor")
            raise UserError(f"No se pudo leer la copia del documento: {ex}", "sync_failed") from ex
        self._host.write_file(str(target), data)
        entry.keys, entry.layout, entry.metadata = list(keys), layout, metadata
        entry.mark_saved()

    @staticmethod
    def _check_can_save(entry: _OpenDocument) -> None:
        if not entry.can_save:
            raise UserError("Este PDF no permite guardar cambios por sus permisos de seguridad.", "save_not_allowed")

    # ── Exportar ─────────────────────────────────────────────────────────
    @exposed
    def extract_page(self, doc_id: int, index: int, upload: str) -> str | None:
        """Guarda como un PDF nuevo la página ``index``, que el visor subió a ``upload`` (con sus
        anotaciones: la saca su motor). Devuelve su ruta (``None`` si se cancela)."""
        data = self.received(upload)
        with self._lock:
            source = Path(self._doc(doc_id).path)
        dest = self._host.save_pdf(str(source.with_name(f"{source.stem}_pagina_{index + 1}.pdf")))
        if not dest:
            return None
        target = dest if dest.lower().endswith(".pdf") else f"{dest}.pdf"
        self._write(target, data)
        self._push_recent(target)
        return target

    @exposed
    def export_text(self, doc_id: int) -> str | None:
        """Guarda el texto de todas las páginas en un .txt; el visor tiene que haberle dado antes
        el de todas (``set_pages`` y ``add_texts``). Devuelve su ruta (``None`` si se cancela)."""
        with self._lock:
            source = Path(self._doc(doc_id).path)
        dest = self._host.save_text(str(source.with_name(f"{source.stem}_texto.txt")))
        if not dest:
            return None
        with self._lock:
            entry = self._doc(doc_id)
            pages = [self.packed_text(entry, i) for i in range(len(entry.keys))]
            ocr_text = {i: " ".join(w[4] for w in entry.ocr[key]) for i, key in enumerate(entry.keys) if key in entry.ocr}
        self._write(dest, page_ops.document_text(pages, ocr_text).encode("utf-8"))
        return dest

    @exposed
    def export_images(self, doc_id: int, upload: str) -> dict[str, Any] | None:
        """Extrae a una carpeta las imágenes incrustadas de la copia del visor subida a ``upload``
        (se lee y se suelta). Devuelve ``{folder, count}`` o ``None`` si se cancela."""
        with self._lock:
            entry = self._doc(doc_id)
            stem, password = Path(entry.path).stem, entry.password
        folder = self._host.pick_output_folder()
        if not folder:
            return None
        try:
            with Document.open(self.received(upload), password) as copy:
                count = page_ops.export_images(copy, Path(folder), stem)
        except PdfError as ex:
            raise UserError(f"No se pudo leer la copia del documento: {ex}", "sync_failed") from ex
        except OSError as ex:
            raise UserError(f"No se pudieron extraer las imágenes: {ex}", "export_failed") from ex
        return {"folder": folder, "count": count}

    def _write(self, path: str, data: bytes) -> None:
        try:
            self._host.write_file(path, data)
        except OSError as ex:
            raise UserError(f"No se pudo guardar {Path(path).name}: {ex}", "save_failed") from ex

    # ── Propiedades ──────────────────────────────────────────────────────
    @exposed
    def file_size(self, doc_id: int) -> int | None:
        """Tamaño del archivo, en bytes (diálogo de propiedades; lo demás lo da el visor)."""
        with self._lock:
            path = self._doc(doc_id).path
        return self._host.file_size(path)

    # ── Auxiliares ───────────────────────────────────────────────────────
    def _doc(self, doc_id: int) -> _OpenDocument:
        entry = self._docs.get(doc_id)
        if entry is None:
            raise UserError("El documento ya no está abierto.", "not_open")
        return entry

    def _push_recent(self, path: str) -> None:
        recent_files.push(path)
        self._host.emit(RECENT_CHANGED)

    def _info(self, doc_id: int) -> dict[str, Any]:
        """El estado del documento: ruta, nombre y cambios sin guardar (las páginas las lleva el visor)."""
        entry = self._docs[doc_id]
        return {
            "id": doc_id,
            "path": entry.path,
            "name": Path(entry.path).name,
            "modified": entry.modified,
            "annotated": entry.annotated,
            "redacted": entry.redacted,
        }

    def _file_info(self, doc_id: int) -> dict[str, Any]:
        """:meth:`_info` con lo que el visor necesita para maquetar el archivo antes de abrirlo: el
        tamaño (pt) y la clave de cada página y el índice."""
        entry = self._docs[doc_id]
        return {**self._info(doc_id), **entry.layout, "keys": list(entry.file_keys)}
