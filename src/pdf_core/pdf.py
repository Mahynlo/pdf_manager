"""Documentos PDF con PDFium (``pypdfium2``): la única puerta de Python al motor.

PDFium no es seguro entre hilos, ni siquiera con documentos distintos, y las llamadas a
través de ``ctypes`` sueltan el GIL: todo lo que toca el motor pasa por :data:`LOCK`. Por eso
las páginas no se quedan abiertas: cada operación abre la página, la usa y la cierra.

Los documentos se leen siempre a memoria: así no bloquean el archivo y se puede sobrescribir.

Coordenadas: :class:`Rect` usa puntos con el origen arriba a la izquierda.

- *de página*: la página sin girar (las de las anotaciones, como las de EmbedPDF);
- *de vista*: la página tal como se ve, ya girada (:meth:`Page.to_view` y :meth:`Page.to_page`).

Lo que este PDFium no sabe hacer (censurar, cifrar, escribir marcadores) lo hace el de EmbedPDF
en la ventana: ver ``Host.run_engine``.
"""

from __future__ import annotations

import ctypes
import math
import struct
import threading
import zlib
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw

LOCK = threading.RLock()
UNRESTRICTED = -1  # permisos de un PDF sin cifrar o abierto como propietario
OCR_MARK = b"ExtraerPDFsOCR"  # marca del texto invisible (el visor la busca para quitarlo)
_OCR_FONT = b"Helvetica"
_META_KEYS = {
    "Title": "title", "Author": "author", "Subject": "subject", "Keywords": "keywords",
    "Creator": "creator", "Producer": "producer", "CreationDate": "creationDate", "ModDate": "modDate",
}
_HYPHENS = {0x02, 0xFFFE}  # guion de fin de línea según PDFium
_ALL_PERMISSIONS = 0xF3C  # imprimir, modificar, copiar, anotar, formularios, accesibilidad, ensamblar


class PdfError(ValueError):
    """El archivo no se puede leer como PDF."""


class PasswordError(PdfError):
    """Hace falta contraseña, o la indicada no es la correcta."""


def locked(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        with LOCK:
            return method(*args, **kwargs)

    return wrapper


class Rect(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return 0.0 if self.is_empty else self.width * self.height

    @property
    def is_empty(self) -> bool:
        return self.x1 <= self.x0 or self.y1 <= self.y0

    def intersects(self, other: Sequence[float]) -> bool:
        return not (self & Rect(*other)).is_empty

    def __and__(self, other: Sequence[float]) -> Rect:  # type: ignore[override]
        o = Rect(*other)
        return Rect(max(self.x0, o.x0), max(self.y0, o.y0), min(self.x1, o.x1), min(self.y1, o.y1))


class Char(NamedTuple):
    """Un carácter de la página, en orden de contenido, en coordenadas de página.

    ``rect`` es la caja de su glifo y ``box`` la holgada, con la altura de la fuente: la de
    buscar y censurar, que cubre también tildes y descendentes.
    """

    text: str
    rect: Rect
    box: Rect
    line: int


@dataclass
class TextMap:
    """Texto de una página con la posición de cada carácter (``rects[i]`` es la de ``text[i]``)."""

    text: str
    rects: list[Rect | None]  # None en espacios y saltos de línea
    lines: list[int]

    def rects_of(self, start: int, end: int) -> list[Rect]:
        """Rectángulos de ``text[start:end]`` en coordenadas de página: uno por línea."""
        boxes: dict[int, list[Rect]] = {}
        for i in range(start, end):
            rect = self.rects[i]
            if rect is not None:
                boxes.setdefault(self.lines[i], []).append(rect)
        return [_union(run) for run in boxes.values()]


class _Meta(NamedTuple):
    """Lo que se consulta a menudo de una página, leído una sola vez."""

    width: float  # sin girar
    height: float
    left: float  # esquina de su caja visible
    top: float
    rotation: int


class Page:
    """Una página de un :class:`Document`. Solo guarda su número: el motor no la tiene abierta."""

    def __init__(self, doc: Document, index: int) -> None:
        self.parent = doc
        self.number = index
        self._text: TextMap | None = None
        self._chars: list[Char] | None = None

    @contextmanager
    def _opened(self) -> Iterator[pdfium.PdfPage]:
        with LOCK:
            page = self.parent.raw[self.number]
            try:
                yield page
            finally:
                page.close()

    @property
    def _meta(self) -> _Meta:
        return self.parent._page_meta(self.number)

    @property
    def uid(self) -> int:
        """Identifica la página en este documento aunque se mueva."""
        return self.parent.uids[self.number]

    @property
    def rotation(self) -> int:
        return self._meta.rotation

    @property
    def rect(self) -> Rect:
        """La página tal como se ve (ya girada)."""
        meta = self._meta
        if meta.rotation in (90, 270):
            return Rect(0, 0, meta.height, meta.width)
        return Rect(0, 0, meta.width, meta.height)

    @locked
    def set_rotation(self, angle: int) -> None:
        with self._opened() as page:
            page.set_rotation(angle % 360)
        self.parent._meta.pop(self.number, None)

    # ── Coordenadas ──────────────────────────────────────────────────────
    def to_view(self, rect: Sequence[float]) -> Rect:
        """De coordenadas de página a la página tal como se ve."""
        x0, y0, x1, y1 = rect
        meta = self._meta
        w, h = meta.width, meta.height
        if meta.rotation == 90:
            return Rect(h - y1, x0, h - y0, x1)
        if meta.rotation == 180:
            return Rect(w - x1, h - y1, w - x0, h - y0)
        if meta.rotation == 270:
            return Rect(y0, w - x1, y1, w - x0)
        return Rect(x0, y0, x1, y1)

    def to_page(self, rect: Sequence[float]) -> Rect:
        """De la página tal como se ve a coordenadas de página."""
        x0, y0, x1, y1 = rect
        meta = self._meta
        w, h = meta.width, meta.height
        if meta.rotation == 90:
            return Rect(y0, h - x1, y1, h - x0)
        if meta.rotation == 180:
            return Rect(w - x1, h - y1, w - x0, h - y0)
        if meta.rotation == 270:
            return Rect(w - y1, x0, w - y0, x1)
        return Rect(x0, y0, x1, y1)

    def _from_pdf(self, left: float, bottom: float, right: float, top: float) -> Rect:
        """De las coordenadas de PDFium (origen abajo) a coordenadas de página."""
        meta = self._meta
        return Rect(left - meta.left, meta.top - top, right - meta.left, meta.top - bottom)

    # ── Texto ────────────────────────────────────────────────────────────
    @locked
    def chars(self) -> list[Char]:
        """Los caracteres de la página, también los espacios y saltos de línea."""
        if self._chars is not None:
            return self._chars
        result: list[Char] = []
        tight = [ctypes.c_double() for _ in range(4)]
        refs = [ctypes.byref(v) for v in tight]
        loose = raw.FS_RECTF()
        empty = Rect(0, 0, 0, 0)
        line = 0
        rotation = self.rotation
        with self._opened() as page:
            # PDFium ordena el texto como se ve: el de una página girada se lee en su sentido
            # original, y las coordenadas no cambian.
            if rotation:
                page.set_rotation(0)
            text = page.get_textpage()
            try:
                handle = text.raw
                for i in range(raw.FPDFText_CountChars(handle)):
                    code = raw.FPDFText_GetUnicode(handle, i)
                    if code in (0, 0x0D):
                        continue
                    if code == 0x0A:
                        result.append(Char("\n", empty, empty, line))
                        line += 1
                        continue
                    rect = box = empty
                    if raw.FPDFText_GetCharBox(handle, i, *refs):
                        left, right, bottom, top = (v.value for v in tight)
                        rect = box = self._from_pdf(left, bottom, right, top)
                    if raw.FPDFText_GetLooseCharBox(handle, i, loose):
                        box = self._from_pdf(loose.left, loose.bottom, loose.right, loose.top)
                    result.append(Char("-" if code in _HYPHENS else chr(code), rect, box, line))
            finally:
                text.close()
                if rotation:
                    page.set_rotation(rotation)
        self._chars = result
        return result

    def text_map(self) -> TextMap:
        if self._text is None:
            chars = self.chars()
            self._text = TextMap(
                "".join(c.text for c in chars),
                [c.box if c.text.strip() else None for c in chars],
                [c.line for c in chars],
            )
        return self._text

    def text(self) -> str:
        return self.text_map().text

    def words(self) -> list[tuple[Rect, str, int]]:
        """Palabras de la página: ``(rect, texto, línea)``, en coordenadas de página."""
        words: list[tuple[Rect, str, int]] = []
        run: list[Char] = []

        def flush() -> None:
            if run:
                words.append((_union([c.box for c in run]), "".join(c.text for c in run), run[0].line))
                run.clear()

        for char in self.chars():
            if char.text.strip():
                run.append(char)
            else:
                flush()
        flush()
        return words

    @locked
    def text_direction(self) -> tuple[float, float]:
        """Sentido dominante del texto en la vista, ponderado por caracteres (``(0, 0)`` sin texto).

        Es un vector con ``y`` hacia abajo: ``(1, 0)`` se lee de izquierda a derecha.
        """
        wx = wy = 0.0
        turn = math.radians(self.rotation)
        with self._opened() as page:
            text = page.get_textpage()
            try:
                handle = text.raw
                for i in range(raw.FPDFText_CountChars(handle)):
                    if raw.FPDFText_GetUnicode(handle, i) <= 0x20 or raw.FPDFText_IsGenerated(handle, i) == 1:
                        continue
                    angle = raw.FPDFText_GetCharAngle(handle, i)
                    if angle >= 0:  # horario, como /Rotate
                        wx += math.cos(angle + turn)
                        wy += math.sin(angle + turn)
            finally:
                text.close()
        return wx, wy

    # ── Imágenes ─────────────────────────────────────────────────────────
    @locked
    def render(self, scale: float = 1.0, clip: Sequence[float] | None = None, annots: bool = True, rotation: int = 0) -> np.ndarray:
        """La página tal como se ve (más ``rotation`` grados) como matriz RGB ``alto × ancho × 3``.

        ``clip``: rectángulo de vista al que recortar.
        """
        crop = (0, 0, 0, 0)
        if clip is not None:
            view = self.rect
            x0, y0, x1, y1 = clip
            crop = (x0, view.height - y1, view.width - x1, y0)
        with self._opened() as page:
            bitmap = page.render(scale=scale, rotation=rotation % 360, crop=crop, may_draw_forms=False,
                                 draw_annots=annots, rev_byteorder=True, prefer_bgrx=False)
            try:
                image = bitmap.to_numpy()
                return (image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, 2)).copy()
            finally:
                bitmap.close()

    def _images(self) -> Iterator[tuple[Any, tuple[float, ...]]]:
        """Las imágenes de la página con la matriz de cada una hasta la página."""
        with self._opened() as page:
            yield from _walk_images(raw.FPDFPage_CountObjects(page), lambda i: raw.FPDFPage_GetObject(page, i), _IDENTITY)

    @locked
    def image_rects(self) -> list[Rect]:
        """Dónde hay imágenes (también dentro de Form XObjects), en coordenadas de vista."""
        rects: list[Rect] = []
        for _obj, matrix in self._images():
            corners = [_apply(matrix, x, y) for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
            xs, ys = [p[0] for p in corners], [p[1] for p in corners]
            rects.append(self.to_view(self._from_pdf(min(xs), min(ys), max(xs), max(ys))))
        return rects

    @locked
    def has_images(self) -> bool:
        return any(True for _ in self._images())

    @locked
    def export_images(self) -> list[tuple[str, bytes]]:
        """Las imágenes incrustadas como ``(extensión, datos)``: JPEG y JPEG 2000 sin recodificar."""
        found = (_image_bytes(obj) for obj, _matrix in self._images())
        return [image for image in found if image]

    # ── Anotaciones ──────────────────────────────────────────────────────
    @locked
    def redact_rects(self) -> list[Rect]:
        """Rectángulos (de página) de las marcas de censura."""
        rects = []
        with self._opened() as page:
            for i in range(raw.FPDFPage_GetAnnotCount(page)):
                annot = raw.FPDFPage_GetAnnot(page, i)
                try:
                    box = raw.FS_RECTF()
                    if raw.FPDFAnnot_GetSubtype(annot) == raw.FPDF_ANNOT_REDACT and raw.FPDFAnnot_GetRect(annot, box):
                        rects.append(self._from_pdf(box.left, box.bottom, box.right, box.top))
                finally:
                    raw.FPDFPage_CloseAnnot(annot)
        return rects

    # ── Texto invisible (OCR) ────────────────────────────────────────────
    @locked
    def add_invisible_text(self, words: Iterable[tuple[Rect, str]]) -> int:
        """Escribe cada palabra (rectángulo de vista, texto) como texto invisible; devuelve cuántas.

        Cada palabra ocupa su rectángulo y se lee en el sentido en que se ve la página. Lleva la
        marca :data:`OCR_MARK`: el motor del visor la quita de las copias que salen de él
        (``app/ui/src/lib/pdf-engine/native.ts``), así el texto reconocido no pasa al archivo.
        """
        written = 0
        doc = self.parent.raw
        font = raw.FPDFText_LoadStandardFont(doc, _OCR_FONT)
        with self._opened() as page:
            for rect, text in words:
                obj = raw.FPDFPageObj_CreateTextObj(doc, font, 12.0)
                encoded = (text + "\0").encode("utf-16-le")
                raw.FPDFText_SetText(obj, ctypes.cast(encoded, ctypes.POINTER(raw.FPDF_WCHAR)))
                raw.FPDFTextObj_SetTextRenderMode(obj, raw.FPDF_TEXTRENDERMODE_INVISIBLE)
                raw.FPDFPageObj_AddMark(obj, OCR_MARK)
                box = [ctypes.c_float() for _ in range(4)]
                raw.FPDFPageObj_GetBounds(obj, *[ctypes.byref(v) for v in box])
                left, bottom, right, top = (v.value for v in box)
                if right <= left or top <= bottom:
                    raw.FPDFPageObj_Destroy(obj)
                    continue
                raw.FPDFPageObj_Transform(obj, *self._fit(rect, left, bottom, right - left, top - bottom))
                raw.FPDFPage_InsertObject(page, obj)
                written += 1
            if written:
                raw.FPDFPage_GenerateContent(page)
        self._chars = self._text = None
        return written

    def _fit(self, rect: Rect, left: float, bottom: float, width: float, height: float) -> tuple[float, ...]:
        """Matriz que lleva la caja de un texto recién creado al rectángulo de vista ``rect``.

        Se pasa por un espacio con ``y`` hacia arriba alineado con la vista; desde ahí a la
        página según su giro (inverso del /Rotate) y a la caja visible de la página.
        """
        meta = self._meta
        sx, sy = rect.width / width, rect.height / height
        # En ese espacio: u = sx (x - left) + u0 ; v = sy (y - bottom) + v0
        u0, v0 = rect.x0 - sx * left, self.rect.height - rect.y1 - sy * bottom
        w, h = meta.width, meta.height
        if meta.rotation == 90:  # x = w - v ; y = u
            a, b, c, d, e, f = 0, sx, -sy, 0, w - v0, u0
        elif meta.rotation == 180:  # x = w - u ; y = h - v
            a, b, c, d, e, f = -sx, 0, 0, -sy, w - u0, h - v0
        elif meta.rotation == 270:  # x = v ; y = h - u
            a, b, c, d, e, f = 0, -sx, sy, 0, v0, h - u0
        else:
            a, b, c, d, e, f = sx, 0, 0, sy, u0, v0
        return float(a), float(b), float(c), float(d), float(e + meta.left), float(f + meta.top - meta.height)


class Document:
    """Un PDF abierto en memoria."""

    def __init__(self, document: pdfium.PdfDocument, path: str = "") -> None:
        self.raw = document
        self.name = path
        self._meta: dict[int, _Meta] = {}
        self._next_uid = len(document) + 1
        self.uids = list(range(1, self._next_uid))

    # ── Abrir y cerrar ───────────────────────────────────────────────────
    @classmethod
    @locked
    def open(cls, source: str | Path | bytes, password: str | None = None) -> Document:
        """Abre un PDF de disco o de memoria.

        :raises PasswordError: si hace falta contraseña o no es la correcta.
        :raises PdfError: si no se puede leer como PDF.
        :raises OSError: si no se puede leer el archivo.
        """
        path = "" if isinstance(source, bytes) else str(source)
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        try:
            return cls(pdfium.PdfDocument(data, password=password or None), path)
        except pdfium.PdfiumError as ex:
            if ex.err_code == raw.FPDF_ERR_PASSWORD:
                raise PasswordError(str(ex)) from ex
            raise PdfError(str(ex)) from ex

    @classmethod
    @locked
    def new(cls) -> Document:
        return cls(pdfium.PdfDocument.new())

    @locked
    def close(self) -> None:
        self.raw.close()

    def __enter__(self) -> Document:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── Páginas ──────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.uids)

    def __getitem__(self, index: int) -> Page:
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return Page(self, index)

    def __iter__(self) -> Iterator[Page]:
        return (Page(self, i) for i in range(len(self)))

    @locked
    def _page_meta(self, index: int) -> _Meta:
        meta = self._meta.get(index)
        if meta is None:
            page = self.raw[index]
            try:
                box = raw.FS_RECTF()
                if raw.FPDF_GetPageBoundingBox(page, box):
                    left, bottom, right, top = box.left, box.bottom, box.right, box.top
                else:
                    (right, top), left, bottom = page.get_size(), 0.0, 0.0
                meta = _Meta(right - left, top - bottom, left, top, page.get_rotation())
            finally:
                page.close()
            self._meta[index] = meta
        return meta

    def adopt_uids(self, other: Document) -> None:
        """Toma los identificadores de ``other``, un documento con las mismas páginas."""
        self.uids = list(other.uids)
        self._next_uid = other._next_uid

    def set_uids(self, uids: Sequence[int]) -> None:
        """Pone a las páginas los identificadores ``uids``, uno por página y en orden."""
        if len(uids) != len(self.uids):
            raise ValueError(f"{len(uids)} identificadores para {len(self.uids)} páginas")
        self.uids = list(uids)
        self._next_uid = max(self._next_uid, max(uids, default=0) + 1)

    def _take_uid(self) -> int:
        self._next_uid += 1
        return self._next_uid - 1

    @locked
    def new_page(self, index: int, width: float, height: float) -> None:
        self.raw.new_page(width, height, index).close()
        self.uids.insert(index, self._take_uid())
        self._meta.clear()

    @locked
    def delete_page(self, index: int) -> None:
        self.raw.del_page(index)
        del self.uids[index]
        self._meta.clear()

    @locked
    def move_page(self, src: int, dst: int) -> None:
        """Mueve la página ``src`` para que quede en la posición final ``dst``."""
        if src == dst:
            return
        if not raw.FPDF_MovePages(self.raw, (ctypes.c_int * 1)(src), 1, dst):
            raise PdfError("No se pudo mover la página")
        self.uids.insert(dst, self.uids.pop(src))
        self._meta.clear()

    @locked
    def insert_pages(self, source: Document, pages: Sequence[int], at: int | None = None, uids: Sequence[int] | None = None) -> None:
        """Copia ``pages`` de ``source`` (con sus anotaciones) en la posición ``at`` (por defecto, al final).

        ``uids``: los identificadores que llevarán, para devolver una página a su sitio.
        """
        index = len(self) if at is None else at
        self.raw.import_pages(source.raw, list(pages), index)
        self.uids[index:index] = list(uids) if uids is not None else [self._take_uid() for _ in pages]
        self._meta.clear()

    # ── Estado ───────────────────────────────────────────────────────────
    @property
    @locked
    def encrypted(self) -> bool:
        """True si el archivo está cifrado."""
        return raw.FPDF_GetSecurityHandlerRevision(self.raw) != -1

    @property
    @locked
    def permissions(self) -> int:
        """Bits de permiso del PDF, o :data:`UNRESTRICTED` si no se aplica ninguna restricción."""
        bits = raw.FPDF_GetDocPermissions(self.raw) & _ALL_PERMISSIONS
        return UNRESTRICTED if bits == _ALL_PERMISSIONS or not self.encrypted else bits

    @property
    @locked
    def metadata(self) -> dict[str, str]:
        info = self.raw.get_metadata_dict(skip_empty=True)
        return {key: info[name] for name, key in _META_KEYS.items() if name in info}

    @property
    @locked
    def version(self) -> str:
        number = self.raw.get_version()
        return f"{number // 10}.{number % 10}" if number else ""

    @locked
    def toc(self) -> list[tuple[int, str, int | None]]:
        """Marcadores: ``(nivel desde 1, título, índice de página o None)``."""
        result = []
        for item in self.raw.get_toc():
            dest = item.get_dest()
            result.append((item.level + 1, item.get_title() or "", dest.get_index() if dest else None))
        return result

    # ── Guardar ──────────────────────────────────────────────────────────
    @locked
    def to_bytes(self, decrypt: bool = False) -> bytes:
        """El PDF entero (sin tocar el documento abierto). Conserva su cifrado salvo con ``decrypt``."""
        out = BytesIO()
        self.raw.save(out, flags=raw.FPDF_REMOVE_SECURITY if decrypt else raw.FPDF_NO_INCREMENTAL)
        return out.getvalue()

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(self.to_bytes())


# ── Auxiliares ───────────────────────────────────────────────────────────────
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _union(rects: Sequence[Rect]) -> Rect:
    return Rect(min(r.x0 for r in rects), min(r.y0 for r in rects), max(r.x1 for r in rects), max(r.y1 for r in rects))


def _apply(m: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _compose(inner: tuple[float, ...], outer: tuple[float, ...]) -> tuple[float, ...]:
    """Primero ``inner`` y después ``outer``."""
    a, b, c, d, e, f = inner
    return (
        a * outer[0] + b * outer[2], a * outer[1] + b * outer[3],
        c * outer[0] + d * outer[2], c * outer[1] + d * outer[3],
        e * outer[0] + f * outer[2] + outer[4], e * outer[1] + f * outer[3] + outer[5],
    )


def _matrix(obj: Any) -> tuple[float, ...]:
    m = raw.FS_MATRIX()
    if not raw.FPDFPageObj_GetMatrix(obj, m):
        return _IDENTITY
    return (m.a, m.b, m.c, m.d, m.e, m.f)


def _walk_images(count: int, get: Any, parent: tuple[float, ...]) -> Iterator[tuple[Any, tuple[float, ...]]]:
    for i in range(count):
        obj = get(i)
        kind = raw.FPDFPageObj_GetType(obj)
        matrix = _compose(_matrix(obj), parent)
        if kind == raw.FPDF_PAGEOBJ_IMAGE:
            yield obj, matrix
        elif kind == raw.FPDF_PAGEOBJ_FORM:
            yield from _walk_images(
                raw.FPDFFormObj_CountObjects(obj), lambda k, form=obj: raw.FPDFFormObj_GetObject(form, k), matrix
            )


def _image_bytes(obj: Any) -> tuple[str, bytes] | None:
    """Una imagen como ``(extensión, datos)``."""
    filters = []
    buffer = ctypes.create_string_buffer(64)
    for i in range(raw.FPDFImageObj_GetImageFilterCount(obj)):
        size = raw.FPDFImageObj_GetImageFilter(obj, i, buffer, 64)
        filters.append(buffer.raw[:max(0, size - 1)].decode("ascii", "replace"))
    native = {"DCTDecode": "jpg", "JPXDecode": "jp2"}.get(filters[0]) if len(filters) == 1 else None
    if native:
        size = raw.FPDFImageObj_GetImageDataRaw(obj, None, 0)
        data = ctypes.create_string_buffer(size)
        raw.FPDFImageObj_GetImageDataRaw(obj, data, size)
        return native, data.raw
    handle = raw.FPDFImageObj_GetBitmap(obj)
    if not handle:
        return None
    bitmap = pdfium.PdfBitmap.from_raw(handle)
    try:
        image = bitmap.to_numpy()
        if image.ndim == 3:  # PDFium da BGR o BGRA
            image = image[:, :, [2, 1, 0]]
        return "png", png(image)
    finally:
        bitmap.close()


def png(image: np.ndarray) -> bytes:
    """Una matriz ``alto × ancho`` (gris) o ``alto × ancho × 3`` (RGB) como PNG."""
    height, width = image.shape[:2]
    channels = 1 if image.ndim == 2 else image.shape[2]
    rows = np.zeros((height, 1 + width * channels), np.uint8)  # cada fila empieza por su filtro (0)
    rows[:, 1:] = image.reshape(height, -1)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 0 if channels == 1 else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + chunk(b"IEND", b"")
