"""Extracción de páginas por palabras clave/similitud.

``PDFExtractionTab`` (interfaz Flet) se importa de forma diferida para que
``engine`` y ``model`` puedan usarse sin cargar Flet.
"""

__all__ = ["PDFExtractionTab"]


def __getattr__(name: str):
    if name == "PDFExtractionTab":
        from .tab import PDFExtractionTab

        return PDFExtractionTab
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
