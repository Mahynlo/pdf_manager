"""Visor PDF.

``PDFViewerTab`` (interfaz Flet) se importa de forma diferida: así los módulos
sin interfaz (``pdf_viewer.ocr``, ``_censorship_profiles``, ``_text_legends``…)
pueden usarse desde el cliente PySide6 sin cargar Flet.
"""

__all__ = ["PDFViewerTab"]


def __getattr__(name: str):
    if name == "PDFViewerTab":
        from .viewer import PDFViewerTab

        return PDFViewerTab
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
