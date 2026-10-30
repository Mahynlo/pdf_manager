"""E/S del documento PDF independiente de la interfaz (la usan el visor Qt y el HTML)."""

from __future__ import annotations

import logging

import fitz

log = logging.getLogger(__name__)


def _doc_has_signatures(doc: fitz.Document) -> bool:
    try:
        return doc.get_sigflags() >= 1
    except Exception:
        return False


def is_encrypted_file(doc: fitz.Document) -> bool:
    """True si el PDF está cifrado en origen, se haya autenticado o no.

    No se usa ``doc.needs_pass``: consultarlo después de ``authenticate`` estropea
    el descifrado en PyMuPDF 1.27 (las páginas salen en blanco con errores AES).
    """
    return bool((doc.metadata or {}).get("encryption"))


def sanitize_doc(doc: fitz.Document) -> fitz.Document:
    """Normalize non-standard raw-deflate streams to standard zlib.

    Avoids blank pages and zlib errors when saving or editing annotations.
    Skips encrypted docs and docs with digital signatures.
    """
    if doc.is_encrypted or _doc_has_signatures(doc) or len(doc) > 150:
        return doc
    try:
        raw = doc.tobytes(garbage=0, deflate=False, clean=False)
        if len(raw) > 15 * 1024 * 1024:  # Skip large files (>15 MB)
            return doc
        page_count = len(doc)
        with fitz.open("pdf", raw) as _tmp:
            clean = _tmp.tobytes(garbage=4, deflate=True, clean=True)
        res = fitz.open("pdf", clean)
        if len(res) == page_count:
            doc.close()
            return res
        res.close()
    except Exception:
        # Se sigue con el documento original: la normalización es una mejora opcional.
        log.debug("No se pudo normalizar el PDF", exc_info=True)
    return doc


def serialize_document(doc: fitz.Document) -> bytes:
    """Serializa ``doc`` a bytes listos para escribir en disco.

    Igual que el ``_save_in_place`` de Flet: primero ``tobytes(garbage=0)`` para
    no alterar el estado interno del documento abierto y después se limpia en un
    documento efímero. Los PDF cifrados conservan su cifrado (no se pueden
    reabrir sin contraseña, así que se serializan directamente; sin
    ``PDF_ENCRYPT_KEEP`` PyMuPDF los guardaría sin contraseña).
    """
    if is_encrypted_file(doc):
        return doc.tobytes(garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    raw = doc.tobytes(garbage=0, deflate=False, clean=False)
    with fitz.open("pdf", raw) as tmp:
        return tmp.tobytes(garbage=4, deflate=True, clean=True)


def reopen_from_bytes(data: bytes, password: str | None = None) -> fitz.Document:
    """Abre ``data`` en memoria (sin bloquear ni depender del archivo en disco)."""
    doc = fitz.open("pdf", data)
    if password and doc.is_encrypted:
        doc.authenticate(password)
    return doc


def page_structure_state(doc: fitz.Document) -> tuple:
    """Huella de la estructura de páginas: orden (xref) y rotación de cada una.

    Detecta añadir/eliminar/duplicar/mover/rotar páginas y también su reversión
    (p. ej. rotar 90° y volver a 0° deja la misma huella).
    """
    return tuple((page.xref, page.rotation) for page in doc)
