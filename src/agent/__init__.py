"""Compatibilidad (Flet/Qt): el agente vive en ``pdf_core.agent``.

``agent.config``, ``agent.pdf_agent``… son alias de los módulos de ``pdf_core.agent``.
Se borrará al retirar las versiones Flet y Qt. (``agente.py`` es un ejemplo suelto.)
"""

__all__ = ["PDFAgent"]


def __getattr__(name: str):
    if name == "PDFAgent":
        from pdf_core.agent.pdf_agent import PDFAgent

        return PDFAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
