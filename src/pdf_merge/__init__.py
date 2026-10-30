"""Combinación de PDFs.

``MergePDFTab`` (interfaz Flet) se importa de forma diferida para que
``engine`` y ``model`` puedan usarse sin cargar Flet.
"""

__all__ = ["MergePDFTab"]


def __getattr__(name: str):
    if name == "MergePDFTab":
        from .tab import MergePDFTab

        return MergePDFTab
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
