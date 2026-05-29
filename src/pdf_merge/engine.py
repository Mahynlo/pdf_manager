"""PDF logic for the merge feature — uses PyMuPDF (`fitz`), never Flet.

Everything that touches documents on disk lives here: authenticating
encrypted PDFs, checking assembly permissions, rendering thumbnails, and the
page-by-page merge itself. The UI layer ([tab.py]) drives these functions and
turns their results / exceptions into Flet widgets.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable, Optional

import fitz

from .model import MergeSource, PDFEntry

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


# ── merge operation ───────────────────────────────────────────────────────────

ProgressFn = Callable[[int, int], None]


def merge_selection(
    sources: list[MergeSource],
    out_path: str,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Combine the selected pages of *sources* into *out_path*.

    Calls `progress(done, total)` after each inserted page (the caller decides
    how often to act on it). Returns the total number of pages written.
    """
    out_doc = fitz.open()
    total = sum(len(s.pages) for s in sources)
    done = 0
    try:
        for source in sources:
            with open_source_doc(
                source.path, password=source.password, enforce_permissions=True
            ) as src:
                for pg in source.pages:
                    out_doc.insert_pdf(src, from_page=pg, to_page=pg, start_at=-1)
                    done += 1
                    if progress is not None:
                        progress(done, total)
        out_doc.save(out_path, garbage=4, deflate=True)
    finally:
        out_doc.close()
    return total
