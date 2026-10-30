"""Agente de IA para documentos PDF (Gemini u OpenAI): chat con búsqueda semántica,
resumen, datos clave y sugerencias de censura.

Sus dependencias (``google-genai``, ``langchain-*``, ``pymupdf4llm``) son opcionales:
``config`` se puede usar sin ellas y ``PDFAgent`` se importa al pedirlo.
"""

__all__ = ["PDFAgent"]


def __getattr__(name: str):
    if name == "PDFAgent":
        from .pdf_agent import PDFAgent

        return PDFAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
