"""Servicio ``ai``: asistente IA del visor (equivale a ``ai_dock.py`` en Qt y al panel del
agente de Flet): chat sobre el documento, resumen, datos clave y datos sensibles.

Con las dependencias del agente instaladas y una clave de API configurada, usa
``pdf_core.agent.PDFAgent`` (Gemini u OpenAI). Si no, responde en **modo básico**
con el texto del documento (lo mismo que hace la versión Qt cuando no hay agente):
búsqueda de palabras, resumen del inicio, metadatos y patrones de datos personales.

El historial de cada documento se guarda en el documento abierto. Las respuestas
se devuelven también como HTML generado desde Markdown sin HTML crudo, imágenes ni
enlaces, así se pueden insertar tal cual.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from app.backend.rpc import UserError, exposed
from app.backend.services.viewer import ViewerService
from pdf_core import redaction
from pdf_core.agent import config as agent_config

log = logging.getLogger(__name__)

SESSION = "ai"  # clave en ``_OpenDocument.extras``
PROVIDERS = {"google": "Google Gemini", "openai": "OpenAI"}
LEVELS = ("low", "medium", "high")
BASIC_NOTE = "Modo básico (sin IA): configura un proveedor y su clave de API para respuestas del agente."
MAX_SNIPPETS = 4
SNIPPET = 200
# Patrones del modo básico para «Detectar Datos Sensibles» (los de la censura).
SENSITIVE = {
    "email": "Correos electrónicos",
    "teléfono": "Teléfonos",
    "dni_id": "DNI / NIE (España)",
    "tarjeta": "Tarjetas de crédito / débito",
}


@dataclass
class _Session:
    messages: list[dict[str, Any]] = field(default_factory=list)  # lo que muestra el chat
    history: list[dict[str, str]] = field(default_factory=list)  # lo que recibe el agente
    agent: Any = None
    agent_key: tuple | None = None  # configuración con la que se creó el agente


class AiService:
    def __init__(self, viewer: ViewerService, agent_factory: Callable[..., Any] | None = None) -> None:
        self._viewer = viewer
        self._factory = agent_factory  # en las pruebas, un agente falso
        self._lock = threading.Lock()  # historial y agentes (las consultas corren sin el candado del visor)
        self._markdown = MarkdownIt("commonmark", {"html": False}).enable("table").disable(["image", "link", "autolink"])

    # ── Configuración ────────────────────────────────────────────────────
    @exposed
    def config(self) -> dict[str, Any]:
        provider = agent_config.get_provider()
        if provider not in PROVIDERS:
            provider = "google"
        return {
            "provider": provider,
            "providers": [{"id": k, "label": v} for k, v in PROVIDERS.items()],
            "model": agent_config.get_model(provider),
            "has_key": bool(agent_config.get_api_key(provider)),
            "available": self._agent_class() is not None,
        }

    @exposed
    def set_config(self, provider: str, api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
        """Proveedor, clave y modelo (``~/.extraer_pdfs_config.json``, el mismo que Flet)."""
        if provider not in PROVIDERS:
            raise UserError("Proveedor de IA no válido.", "bad_provider")
        agent_config.set_provider(provider)
        if api_key is not None and api_key.strip():
            agent_config.set_api_key(provider, api_key.strip())
        if model is not None and model.strip():
            agent_config.set_model(provider, model.strip())
        return self.config()

    # ── Conversación ─────────────────────────────────────────────────────
    @exposed
    def state(self, doc_id: int) -> dict[str, Any]:
        with self._viewer.document(doc_id) as entry:
            return {"messages": list(self._session(entry).messages), "config": self.config()}

    @exposed
    def clear(self, doc_id: int) -> dict[str, Any]:
        with self._viewer.document(doc_id) as entry:
            session = self._session(entry)
            session.messages.clear()
            session.history.clear()
        return self.state(doc_id)

    @exposed
    def chat(self, doc_id: int, message: str) -> dict[str, Any]:
        """Pregunta libre sobre el documento. Devuelve los mensajes nuevos."""
        message = message.strip()
        if not message:
            raise UserError("Escribe una pregunta.", "empty_message")
        return self._ask(doc_id, message, lambda agent, history: agent.chat(message, history),
                         lambda doc: _basic_search(doc, message))

    @exposed
    def summary(self, doc_id: int) -> dict[str, Any]:
        return self._ask(doc_id, "Generar Resumen Ejecutivo", lambda agent, _h: agent.summarize(), _basic_summary)

    @exposed
    def key_data(self, doc_id: int) -> dict[str, Any]:
        return self._ask(doc_id, "Extraer Datos Clave", lambda agent, _h: agent.extract_key_info(), _basic_key_data)

    @exposed
    def sensitive(self, doc_id: int, level: str = "medium") -> dict[str, Any]:
        """Datos que convendría censurar. La respuesta lleva ``suggestions`` para enviarlas a «Censura»."""
        if level not in LEVELS:
            raise UserError("Nivel de sensibilidad no válido.", "bad_level")

        def with_agent(agent: Any, _history: list) -> tuple[str, list[dict]]:
            suggestions = _parse_suggestions(agent.suggest_redactions(level))
            return _suggestions_text(suggestions), suggestions

        return self._ask(doc_id, "Detectar Datos Sensibles", with_agent, _basic_sensitive)

    # ── Auxiliares ───────────────────────────────────────────────────────
    def _ask(self, doc_id: int, prompt: str, with_agent: Callable, basic: Callable) -> dict[str, Any]:
        """Añade la pregunta y la respuesta al chat; la consulta corre sin ningún candado."""
        with self._viewer.document(doc_id) as entry:
            snapshot = _Snapshot.of(self._viewer, entry)
            session = self._session(entry)
        with self._lock:
            agent = self._agent_for(session, snapshot)
            history = list(session.history)
        user = {"role": "user", "text": prompt}
        suggestions: list[dict] = []
        try:
            if agent is not None:
                reply = with_agent(agent, history)
                mode = "ia"
            else:
                reply = basic(snapshot)
                mode = "básico"
            if isinstance(reply, tuple):
                reply, suggestions = reply
            answer = {"role": "assistant", "text": reply, "html": self._html(reply), "mode": mode, "suggestions": suggestions}
        except Exception as ex:  # el proveedor puede fallar por red, cuota o clave
            log.exception("Fallo del asistente IA")
            answer = {"role": "error", "text": f"{ex}\n(Verifica tu clave de API y la conexión a Internet.)", "mode": "ia"}
        with self._lock:
            session.messages += [user, answer]
            if answer["role"] == "assistant":
                session.history += [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer["text"]}]
        return {"messages": [user, answer], "config": self.config()}

    def _agent_for(self, session: _Session, snap: _Snapshot) -> Any:
        """El agente del documento (se rehace si cambió la configuración); ``None`` en modo básico."""
        cls = self._factory or self._agent_class()
        provider = agent_config.get_provider()
        key = agent_config.get_api_key(provider)
        if cls is None or not key or provider not in PROVIDERS:
            return None
        signature = (provider, key, agent_config.get_model(provider), snap.path)
        if session.agent is None or session.agent_key != signature:
            if session.agent is not None:
                getattr(session.agent, "close", lambda: None)()
            session.agent = cls(snap.path, api_key=key, provider=provider, model=signature[2],
                                ocr_overrides=snap.ocr_text or None)
            session.agent_key = signature
        return session.agent

    @staticmethod
    def _agent_class() -> Any:
        try:
            from pdf_core.agent import PDFAgent
        except ImportError:
            return None  # dependencias del agente sin instalar: modo básico
        return PDFAgent

    @staticmethod
    def _session(entry: Any) -> _Session:
        return entry.extras.setdefault(SESSION, _Session())

    def _html(self, text: str) -> str:
        return self._markdown.render(text)


@dataclass
class _Snapshot:
    """Lo que necesitan las respuestas, copiado con el candado del visor tomado."""

    path: str
    name: str
    pages: list[str]  # texto de cada página (con el de OCR en las escaneadas)
    metadata: dict[str, str]
    ocr_text: dict[int, str]

    @classmethod
    def of(cls, viewer: ViewerService, entry: Any) -> _Snapshot:
        pages, ocr_text = [], {}
        for index, page in enumerate(entry.doc):
            text = page.get_text("text")
            if not text.strip() and entry.ocr.get(viewer.page_key(entry, page)):
                text = ocr_text[index] = viewer.text_of(entry, page).text
            pages.append(text)
        return cls(entry.path, Path(entry.path).name, pages, dict(entry.doc.metadata or {}), ocr_text)


# ── Modo básico ──────────────────────────────────────────────────────────────
def _basic_search(doc: _Snapshot, prompt: str) -> str:
    words = [w.lower() for w in re.findall(r"\w+", prompt) if len(w) > 2]
    matches = []
    for i, text in enumerate(doc.pages):
        if words and any(w in text.lower() for w in words):
            matches.append(f"- **Pág {i + 1}:** {' '.join(text.split())[:SNIPPET]}…")
    if not matches:
        return f"No se encontraron coincidencias directas para la consulta.\n\n_{BASIC_NOTE}_"
    return "Coincidencias encontradas en el texto:\n\n" + "\n".join(matches[:MAX_SNIPPETS]) + f"\n\n_{BASIC_NOTE}_"


def _basic_summary(doc: _Snapshot) -> str:
    first = " ".join((doc.pages[0] if doc.pages else "").split())[:500]
    return (f"**Resumen básico**\n\nDocumento de {len(doc.pages)} páginas.\n\n"
            f"Inicio del texto: {first}…\n\n_{BASIC_NOTE}_")


def _basic_key_data(doc: _Snapshot) -> str:
    labels = {"title": "Título", "author": "Autor", "subject": "Asunto", "keywords": "Palabras clave",
              "creator": "Creador", "producer": "Productor", "creationDate": "Creación", "modDate": "Modificación"}
    rows = [f"- **{label}:** {doc.metadata[key]}" for key, label in labels.items() if doc.metadata.get(key)]
    body = "\n".join(rows) if rows else "El documento no tiene metadatos."
    return f"**Metadatos del PDF** ({doc.name}, {len(doc.pages)} páginas)\n\n{body}\n\n_{BASIC_NOTE}_"


def _basic_sensitive(doc: _Snapshot) -> tuple[str, list[dict]]:
    patterns = {label: pattern for label, pattern in redaction.PII_PATTERNS}
    found: dict[str, dict] = {}
    for category, title in SENSITIVE.items():
        pattern = re.compile(next(p for label, p in patterns.items() if title in label))
        for i, text in enumerate(doc.pages):
            for value in pattern.findall(text):
                value = value.strip().rstrip(".,;:")  # el punto que cierra la frase no es del dato
                if value and value not in found:
                    found[value] = {"texto": value, "categoria": category, "motivo": f"Encontrado en la pág. {i + 1}",
                                    "tipo": "literal"}
    # Un trozo de otro dato (los dígitos de una tarjeta que parecen un teléfono) no se repite.
    suggestions = [s for v, s in found.items() if not any(v != other and v in other for other in found)]
    return _suggestions_text(suggestions) + f"\n\n_{BASIC_NOTE}_", suggestions


def _parse_suggestions(raw: str) -> list[dict]:
    """``{"redacciones": [...]}`` de ``PDFAgent.suggest_redactions`` → sugerencias válidas."""
    start, end = raw.find("{"), raw.rfind("}") + 1
    try:
        data = json.loads(raw[start:end]) if start >= 0 and end > start else {}
    except json.JSONDecodeError:
        return []
    result = []
    for item in data.get("redacciones", []):
        text = str(item.get("texto", "")).strip()
        if text:
            result.append({"texto": text, "categoria": str(item.get("categoria", "otro")),
                           "motivo": str(item.get("motivo", "")),
                           "tipo": "patron" if item.get("tipo") == "patron" else "literal"})
    return result


def _suggestions_text(suggestions: list[dict]) -> str:
    if not suggestions:
        return "No se detectaron datos sensibles."
    lines = [f"- **{s['categoria']}:** {s['texto']}" for s in suggestions]
    return f"Se detectaron {len(suggestions)} dato(s) que convendría censurar:\n\n" + "\n".join(lines)
