"""Pasar las anotaciones de una copia de un PDF al documento original.

El visor edita las anotaciones con EmbedPDF (PDFium) sobre una copia del documento y,
antes de guardar o de cambiar las páginas, la devuelve entera. De esa copia solo se
toman las anotaciones: el resto (contenido de las páginas, cifrado, el texto de OCR que
la copia lleva como texto invisible) sigue siendo el del documento original.

Las anotaciones se copian tal cual, como objetos PDF (diccionario, apariencia, imágenes
de los sellos, ventanas emergentes, respuestas), con el injerto de MuPDF, así que no se
pierde ningún tipo ni propiedad. Se quedan las del original que el visor no edita:

- los campos de formulario (*Widget*), que además cuelgan del formulario del documento;
- los enlaces (*Link*), cuyos destinos apuntan a páginas: injertarlos copiaría esas páginas.
"""

from __future__ import annotations

import fitz
from pymupdf import mupdf

_KEPT = ("Widget", "Link")


def _name(text: str) -> mupdf.PdfObj:
    return mupdf.pdf_new_name(text)


def _kept(annot: mupdf.PdfObj) -> bool:
    subtype = mupdf.pdf_dict_get(annot, _name("Subtype"))
    return any(mupdf.pdf_name_eq(subtype, _name(kind)) for kind in _KEPT)


def _annots(page: mupdf.PdfObj) -> list[mupdf.PdfObj]:
    array = mupdf.pdf_dict_get(page, _name("Annots"))
    return [mupdf.pdf_array_get(array, i) for i in range(mupdf.pdf_array_len(array))]


def replace_annotations(dst: fitz.Document, src: fitz.Document) -> None:
    """Sustituye las anotaciones de cada página de ``dst`` por las de la misma página de ``src``.

    ``src`` es una copia de ``dst`` con las mismas páginas en el mismo orden (se modifica: se
    le quitan las referencias a sus páginas). Los formularios y enlaces de ``dst`` se conservan.
    """
    if len(src) != len(dst):
        raise ValueError(f"la copia tiene {len(src)} páginas y el documento {len(dst)}")
    source = fitz._as_pdf_document(src)
    target = fitz._as_pdf_document(dst)
    parent = _name("P")
    # Cada anotación apunta a su página (/P): se quita antes de injertar ninguna, o el injerto
    # se llevaría también la página de la copia (una ventana emergente llega por su anotación).
    incoming = []
    for index in range(len(src)):
        annots = [annot for annot in _annots(mupdf.pdf_lookup_page_obj(source, index)) if not _kept(annot)]
        for annot in annots:
            mupdf.pdf_dict_del(annot, parent)
        incoming.append(annots)
    graft = mupdf.pdf_new_graft_map(target)  # un objeto compartido se copia una sola vez
    for index, annots in enumerate(incoming):
        page = mupdf.pdf_lookup_page_obj(target, index)
        kept = [annot for annot in _annots(page) if _kept(annot)]
        array = mupdf.pdf_new_array(target, len(kept) + len(annots))
        for annot in kept:
            mupdf.pdf_array_push(array, annot)
        for annot in annots:
            copy = mupdf.pdf_graft_mapped_object(graft, annot)
            mupdf.pdf_dict_put(copy, parent, page)
            mupdf.pdf_array_push(array, copy)
        mupdf.pdf_dict_put(page, _name("Annots"), array)
