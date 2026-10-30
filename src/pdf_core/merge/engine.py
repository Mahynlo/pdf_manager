"""PDF logic for the merge feature — uses PyMuPDF (`fitz`), never Flet.

Everything that touches documents on disk lives here: authenticating
encrypted PDFs, checking assembly permissions, rendering thumbnails, and the
page-by-page merge itself. The UI layer ([tab.py]) drives these functions and
turns their results / exceptions into Flet widgets.
"""
from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz

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
    if permissions < 0:
        return True
    return bool(permissions & _PDF_PERM_ASSEMBLY)


def open_source_doc(
    path: str,
    password: str | None = None,
    enforce_permissions: bool = True,
) -> fitz.Document:
    """Open a source document for merge/preview, authenticating if needed.

    Raises `MergePasswordRequiredError` / `MergeInvalidPasswordError` /
    `MergePermissionDeniedError` as appropriate. The returned document is the
    caller's to close.
    """
    doc = fitz.open(path)
    try:
        if doc.is_encrypted:
            if not password:
                raise MergePasswordRequiredError("PDF protegido requiere contraseña")
            if not doc.authenticate(password):
                raise MergeInvalidPasswordError("Contraseña incorrecta")
            if enforce_permissions and not can_assemble_permissions(doc.permissions):
                raise MergePermissionDeniedError("El PDF no permite ensamblaje")
        return doc
    except Exception:
        doc.close()
        raise


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
            pix = doc[page].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return base64.b64encode(pix.tobytes("png")).decode()
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
            mat = fitz.Matrix(scale, scale)
            for pg in pages:
                if 0 <= pg < n:
                    try:
                        pix = doc[pg].get_pixmap(matrix=mat, alpha=False)
                        out[pg] = base64.b64encode(pix.tobytes("png")).decode()
                    except Exception:
                        pass
    except Exception:
        pass
    return out


# ── merge operation ───────────────────────────────────────────────────────────

ProgressFn = Callable[[int, int], None]


@dataclass(frozen=True)
class MergeOptions:
    """Opciones del documento combinado."""
    bookmarks: bool = False  # un marcador por cada archivo de origen
    duplex: bool = False     # hoja en blanco para que cada archivo empiece en página impar
    optimize: bool = True    # garbage collection + compresión al guardar


DEFAULT_MERGE = MergeOptions()
_BLANK_SIZE = (595, 842)  # A4 en puntos


def merge_pages(
    pages: list[MergePage],
    out_path: str,
    passwords: dict[str, str | None] | None = None,
    options: MergeOptions = DEFAULT_MERGE,
    progress: ProgressFn | None = None,
) -> int:
    """Combina ``pages`` (en ese orden, pueden alternar archivos) en *out_path*.

    Cada archivo de origen se abre una sola vez. Llama a ``progress(done, total)``
    tras cada página y devuelve el total de páginas escritas (incluidas las
    hojas en blanco del modo dúplex).
    """
    passwords = passwords or {}
    out_doc = fitz.open()
    opened: dict[str, fitz.Document] = {}
    toc: list[list] = []
    current_path: str | None = None
    try:
        for done, item in enumerate(pages, start=1):
            if item.path != current_path:
                # Dúplex: el archivo nuevo debe empezar en página impar.
                if options.duplex and current_path is not None and len(out_doc) % 2:
                    out_doc.new_page(width=_BLANK_SIZE[0], height=_BLANK_SIZE[1])
                if options.bookmarks:
                    toc.append([1, Path(item.path).stem, len(out_doc) + 1])
                current_path = item.path
            src = opened.get(item.path)
            if src is None:
                src = open_source_doc(item.path, password=passwords.get(item.path), enforce_permissions=True)
                opened[item.path] = src
            out_doc.insert_pdf(src, from_page=item.page, to_page=item.page, rotate=item.rotation)
            if progress is not None:
                progress(done, len(pages))
        if toc:
            out_doc.set_toc(toc)
        if options.optimize:
            out_doc.save(out_path, garbage=4, deflate=True)
        else:
            out_doc.save(out_path)
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
