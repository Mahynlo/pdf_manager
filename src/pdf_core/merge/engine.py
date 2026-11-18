"""PDF logic for the merge feature — uses PDFium (`pdf_core.pdf`).

Everything that touches documents on disk lives here: authenticating
encrypted PDFs, checking assembly permissions, rendering thumbnails, and the
page-by-page merge itself.
"""
from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pdf_core.pdf import UNRESTRICTED, Document, PasswordError, png

from .model import MergePage, MergeSource, PDFEntry

_PDF_PERM_ASSEMBLY = 1024


# ── exceptions ──────────────────────────────────────────────────────────────

class MergeError(ValueError):
    """Base class for merge-source errors surfaced to the UI."""


class MergePasswordRequiredError(MergeError):
    """An encrypted PDF needs a password for merge operations."""


class MergeInvalidPasswordError(MergeError):
    """Authentication failed for an encrypted PDF."""


class MergePermissionDeniedError(MergeError):
    """The PDF does not allow document assembly for merging."""


# ── path / permission helpers ────────────────────────────────────────────────

def normalize_path(path: str) -> str:
    """Normalize a file path for consistent comparison and storage."""
    return str(Path(path).resolve())


def can_assemble_permissions(permissions: int) -> bool:
    """Return True when permissions include assembly, or are unrestricted."""
    return permissions == UNRESTRICTED or bool(permissions & _PDF_PERM_ASSEMBLY)


def open_source_doc(
    path: str,
    password: str | None = None,
    enforce_permissions: bool = True,
) -> Document:
    """Open a source document for merge/preview, authenticating if needed.

    Raises `MergePasswordRequiredError` / `MergeInvalidPasswordError` /
    `MergePermissionDeniedError` as appropriate. The returned document is the
    caller's to close.
    """
    try:
        doc = Document.open(path, password)
    except PasswordError as ex:
        if not password:
            raise MergePasswordRequiredError("PDF protegido requiere contraseña") from ex
        raise MergeInvalidPasswordError("Contraseña incorrecta") from ex
    if enforce_permissions and not can_assemble_permissions(doc.permissions):
        doc.close()
        raise MergePermissionDeniedError("El PDF no permite ensamblaje")
    return doc


def open_entry(path: str, password: str | None = None) -> PDFEntry:
    """Open *path* (enforcing assembly permissions) and wrap it in a PDFEntry."""
    normalized = normalize_path(path)
    doc = open_source_doc(normalized, password=password, enforce_permissions=True)
    return PDFEntry(normalized, doc, password=password)


# ── thumbnail rendering ───────────────────────────────────────────────────────

def render_thumbnail(
    path: str,
    page: int,
    scale: float,
    password: str | None = None,
) -> str | None:
    """Render one page to a base64-encoded PNG at *scale*, or None on failure.

    Permissions are not enforced here — thumbnails are display-only.
    """
    try:
        with open_source_doc(path, password=password, enforce_permissions=False) as doc:
            if page >= len(doc):
                return None
            return base64.b64encode(png(doc[page].render(scale))).decode()
    except Exception:
        return None


def render_thumbnails_batch(
    path: str,
    pages: list[int],
    scale: float,
    password: str | None = None,
) -> dict[int, str]:
    """Render several pages of one PDF to base64 PNGs in a SINGLE document open.

    Returns ``{page: base64_png}`` for the pages that rendered. Mucho más
    eficiente que llamar a `render_thumbnail` por página (que reabre y reparsea
    el PDF cada vez): aquí se abre una sola vez para todas las páginas pedidas.
    """
    out: dict[int, str] = {}
    if not pages:
        return out
    try:
        with open_source_doc(path, password=password, enforce_permissions=False) as doc:
            n = len(doc)
            for pg in pages:
                if 0 <= pg < n:
                    try:
                        out[pg] = base64.b64encode(png(doc[pg].render(scale))).decode()
                    except Exception:
                        pass
    except Exception:
        pass
    return out


# ── merge operation ───────────────────────────────────────────────────────────

ProgressFn = Callable[[int, int], None]
OutlineFn = Callable[[bytes, list[dict]], bytes]  # escribe los marcadores: los hace el motor de EmbedPDF


@dataclass(frozen=True)
class MergeOptions:
    """Opciones del documento combinado."""
    bookmarks: bool = False  # un marcador por cada archivo de origen
    duplex: bool = False     # hoja en blanco para que cada archivo empiece en página impar


DEFAULT_MERGE = MergeOptions()
_BLANK_SIZE = (595, 842)  # A4 en puntos


def merge_pages(
    pages: list[MergePage],
    out_path: str,
    passwords: dict[str, str | None] | None = None,
    options: MergeOptions = DEFAULT_MERGE,
    progress: ProgressFn | None = None,
    outline: OutlineFn | None = None,
) -> int:
    """Combina ``pages`` (en ese orden, pueden alternar archivos) en *out_path*.

    Cada archivo de origen se abre una sola vez. Llama a ``progress(done, total)``
    tras cada página y devuelve el total de páginas escritas (incluidas las
    hojas en blanco del modo dúplex). ``outline`` escribe los marcadores de ``options.bookmarks``.
    """
    passwords = passwords or {}
    out_doc = Document.new()
    opened: dict[str, Document] = {}
    toc: list[dict] = []
    current_path: str | None = None
    try:
        for done, item in enumerate(pages, start=1):
            if item.path != current_path:
                # Dúplex: el archivo nuevo debe empezar en página impar.
                if options.duplex and current_path is not None and len(out_doc) % 2:
                    out_doc.new_page(len(out_doc), *_BLANK_SIZE)
                if options.bookmarks:
                    toc.append({"title": Path(item.path).stem, "page": len(out_doc)})
                current_path = item.path
            src = opened.get(item.path)
            if src is None:
                src = open_source_doc(item.path, password=passwords.get(item.path), enforce_permissions=True)
                opened[item.path] = src
            out_doc.insert_pages(src, [item.page])
            if item.rotation:
                added = out_doc[len(out_doc) - 1]
                added.set_rotation(added.rotation + item.rotation)
            if progress is not None:
                progress(done, len(pages))
        data = out_doc.to_bytes()
        if toc and outline is not None:
            data = outline(data, toc)
        Path(out_path).write_bytes(data)
        return len(out_doc)
    finally:
        out_doc.close()
        for doc in opened.values():
            doc.close()


def merge_selection(
    sources: list[MergeSource],
    out_path: str,
    progress: ProgressFn | None = None,
) -> int:
    """Combine the selected pages of *sources* (one source after another) into *out_path*."""
    pages = [MergePage(s.path, pg) for s in sources for pg in s.pages]
    passwords = {s.path: s.password for s in sources}
    return merge_pages(pages, out_path, passwords=passwords, progress=progress)
