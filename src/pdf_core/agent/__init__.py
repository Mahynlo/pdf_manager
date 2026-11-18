"""Agente de IA para documentos PDF (Gemini, OpenAI o un modelo local): chat con búsqueda
de fragmentos, resumen, datos clave y sugerencias de censura.

Su cliente (el SDK ``openai``) no está en la versión de navegador: ``config`` y ``providers`` se
pueden usar sin él y ``PDFAgent`` se importa al pedirlo.
"""

__all__ = ["PDFAgent"]


def __getattr__(name: str):
    if name == "PDFAgent":
        from .pdf_agent import PDFAgent

        return PDFAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
