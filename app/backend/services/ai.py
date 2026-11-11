"""Servicio ``ai``: asistente IA del visor: chat sobre el documento, resumen, datos clave y
datos sensibles.

Con el cliente del agente instalado (``openai``) y un proveedor listo —Gemini u OpenAI con su clave,
o un servidor local (Ollama, LM Studio…) con un modelo elegido—, usa ``pdf_core.agent.PDFAgent``.
Si no, responde en **modo básico** con el texto del documento: búsqueda de palabras, resumen del
inicio, metadatos y patrones de datos personales.

El historial de cada documento se guarda en el documento abierto. Las respuestas
se devuelven también como HTML generado desde Markdown sin HTML crudo, imágenes ni
enlaces, así se pueden insertar tal cual.
"""

from __future__ import annotations

import importlib.util
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
from pdf_core.agent.pdf_agent import AgentDocument
from pdf_core.agent.providers import MAX_CONTEXT, MIN_CONTEXT, PROVIDERS, BadAddress, check_base_url

log = logging.getLogger(__name__)

SESSION = "ai"  # clave en ``_OpenDocument.extras``
CLIENT = "openai"  # el cliente de todos los proveedores (no está en la versión de navegador)
LEVELS = ("low", "medium", "high")
BASIC_NOTE = "Modo básico (sin IA): configura un proveedor (clave de API o IA local) para respuestas del agente."
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
        provider = _current_provider()
        return {
            "provider": provider,
            "providers": [p.to_dict() for p in PROVIDERS.values()],
            "model": agent_config.get_model(provider),
            "base_url": agent_config.get_base_url(provider),
            "context": agent_config.get_context(provider),
            "has_key": bool(agent_config.get_api_key(provider)),
            "available": self._agent_class() is not None,
        }

    @exposed
    def set_config(self, provider: str, api_key: str | None = None, model: str | None = None,
                   base_url: str | None = None, context: int | None = None) -> dict[str, Any]:
        """Proveedor, clave y modelo; en la IA local también la dirección del servidor y su
        contexto (``~/.extraer_pdfs_config.json``). Se comprueba todo antes de guardar nada."""
        known = _provider(provider)
        if known.local and base_url is not None and base_url.strip():
            base_url = _checked_url(base_url)
        if known.local and context is not None and not (
                isinstance(context, int) and MIN_CONTEXT <= context <= MAX_CONTEXT):
            raise UserError(f"El contexto tiene que estar entre {MIN_CONTEXT} y {MAX_CONTEXT} tokens.", "bad_context")
        agent_config.set_provider(provider)
        if api_key is not None and api_key.strip():
            agent_config.set_api_key(provider, api_key.strip())
        if model is not None and model.strip():
            agent_config.set_model(provider, model.strip())
        if known.local and base_url:
            agent_config.set_base_url(provider, base_url)
        if known.local and context is not None:
            agent_config.set_context(provider, context)
        return self.config()

    @exposed
    def models(self, provider: str, base_url: str | None = None, api_key: str | None = None) -> list[str]:
        """Los modelos del servidor del proveedor, para elegir uno. Sin ``api_key`` usa la guardada;
        sin ``base_url``, la configurada."""
        known = _provider(provider)
        if not _installed(CLIENT):
            raise UserError("El cliente del agente de IA no está instalado.", "not_installed")
        if known.local and base_url and base_url.strip():
            url = _checked_url(base_url)
        else:
            url = agent_config.get_base_url(provider)
        key = (api_key or "").strip() or agent_config.get_api_key(provider)
        if known.needs_key and not key:
            raise UserError("Escribe la clave de API para ver los modelos.", "no_key")
        from pdf_core.agent.pdf_agent import list_models

        try:
            return list_models(provider, key, url)
        except Exception as ex:  # red, clave o servidor apagado
            message = _without_key(str(ex), key)
            log.warning("No se pudieron listar los modelos de %s: %s: %s", provider, type(ex).__name__, message)
            raise UserError(f"No se pudieron obtener los modelos: {message}\n{_hint(provider)}", "models_failed") from None

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
        return self._ask(doc_id, message, lambda agent, doc, history: agent.chat(doc, message, history),
                         lambda doc: _basic_search(doc, message))

    @exposed
    def summary(self, doc_id: int) -> dict[str, Any]:
        return self._ask(doc_id, "Generar Resumen Ejecutivo", lambda agent, doc, _h: agent.summarize(doc), _basic_summary)

    @exposed
    def key_data(self, doc_id: int) -> dict[str, Any]:
        return self._ask(doc_id, "Extraer Datos Clave", lambda agent, doc, _h: agent.extract_key_info(doc),
                         _basic_key_data)

    @exposed
    def sensitive(self, doc_id: int, level: str = "medium") -> dict[str, Any]:
        """Datos que convendría censurar. La respuesta lleva ``suggestions`` para enviarlas a «Censura»."""
        if level not in LEVELS:
            raise UserError("Nivel de sensibilidad no válido.", "bad_level")

        def with_agent(agent: Any, doc: AgentDocument, _history: list) -> tuple[str, list[dict]]:
            suggestions = _parse_suggestions(agent.suggest_redactions(doc, level))
            return _suggestions_text(suggestions), suggestions

        return self._ask(doc_id, "Detectar Datos Sensibles", with_agent, _basic_sensitive)

    # ── Auxiliares ───────────────────────────────────────────────────────
    def _ask(self, doc_id: int, prompt: str, with_agent: Callable, basic: Callable) -> dict[str, Any]:
        """Añade la pregunta y la respuesta al chat; la consulta corre sin ningún candado."""
        with self._viewer.document(doc_id) as entry:
            snapshot = _snapshot(self._viewer, entry)
            session = self._session(entry)
        with self._lock:
            agent = self._agent_for(session)
            history = list(session.history)
        user = {"role": "user", "text": prompt}
        suggestions: list[dict] = []
        try:
            if agent is not None:
                reply = with_agent(agent, snapshot, history)
                mode = "ia"
            else:
                reply = basic(snapshot)
                mode = "básico"
            if isinstance(reply, tuple):
                reply, suggestions = reply
            answer = {"role": "assistant", "text": reply, "html": self._html(reply), "mode": mode, "suggestions": suggestions}
        except Exception as ex:  # el proveedor puede fallar por red, cuota o clave
            # Algunos clientes ponen la clave en la URL de sus errores: no llega al registro ni a la ventana.
            provider = _current_provider()
            message = _without_key(str(ex), agent_config.get_api_key(provider))
            log.error("Fallo del asistente IA: %s: %s", type(ex).__name__, message)
            answer = {"role": "error", "text": f"{message}\n{_hint(provider)}", "mode": "ia"}
        with self._lock:
            session.messages += [user, answer]
            if answer["role"] == "assistant":
                session.history += [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer["text"]}]
        return {"messages": [user, answer], "config": self.config()}

    def _agent_for(self, session: _Session) -> Any:
        """El agente del documento (se rehace si cambió la configuración); ``None`` en modo básico."""
        cls = self._factory or self._agent_class()
        provider = _current_provider()
        key = agent_config.get_api_key(provider)
        model = agent_config.get_model(provider)
        if cls is None or (PROVIDERS[provider].needs_key and not key) or not model:
            return None
        base_url, context = agent_config.get_base_url(provider), agent_config.get_context(provider)
        signature = (provider, key, model, base_url, context)
        if session.agent is None or session.agent_key != signature:
            if session.agent is not None:
                getattr(session.agent, "close", lambda: None)()
            session.agent = cls(api_key=key, provider=provider, model=model, base_url=base_url, context=context)
            session.agent_key = signature
        return session.agent

    @staticmethod
    def _agent_class() -> Any:
        if not _installed(CLIENT):
            return None  # sin el cliente del agente (p. ej. en el navegador): modo básico
        from pdf_core.agent import PDFAgent

        return PDFAgent

    @staticmethod
    def _session(entry: Any) -> _Session:
        return entry.extras.setdefault(SESSION, _Session())

    def _html(self, text: str) -> str:
        return self._markdown.render(text)


def _current_provider() -> str:
    provider = agent_config.get_provider()
    return provider if provider in PROVIDERS else "google"


def _provider(provider: str) -> Any:
    if provider not in PROVIDERS:
        raise UserError("Proveedor de IA no válido.", "bad_provider")
    return PROVIDERS[provider]


def _checked_url(url: str) -> str:
    try:
        return check_base_url(url)
    except BadAddress as ex:
        raise UserError(str(ex), "bad_address") from None


def _hint(provider: str) -> str:
    if PROVIDERS[provider].local:
        return "(Comprueba que el servidor de IA local está en marcha, su dirección y el modelo.)"
    return "(Verifica tu clave de API, el modelo y la conexión a Internet.)"


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:  # falta el paquete que lo contiene
        return False


def _snapshot(viewer: ViewerService, entry: Any) -> AgentDocument:
    """Lo que necesitan las respuestas, copiado con el candado del visor tomado: el texto de las
    páginas que le dio el visor (tiene que habérselo dado todo), con el de OCR en las escaneadas."""
    pages = []
    for index, key in enumerate(entry.keys):
        text = viewer.packed_text(entry, index).text()
        if not text.strip() and entry.ocr.get(key):
            text = viewer.text_of(entry, index).text
        pages.append(text)
    return AgentDocument(Path(entry.path).name, pages, dict(entry.metadata))


# ── Modo básico ──────────────────────────────────────────────────────────────
def _basic_search(doc: AgentDocument, prompt: str) -> str:
    words = [w.lower() for w in re.findall(r"\w+", prompt) if len(w) > 2]
    matches = []
    for i, text in enumerate(doc.pages):
        if words and any(w in text.lower() for w in words):
            matches.append(f"- **Pág {i + 1}:** {' '.join(text.split())[:SNIPPET]}…")
    if not matches:
        return f"No se encontraron coincidencias directas para la consulta.\n\n_{BASIC_NOTE}_"
    return "Coincidencias encontradas en el texto:\n\n" + "\n".join(matches[:MAX_SNIPPETS]) + f"\n\n_{BASIC_NOTE}_"


def _basic_summary(doc: AgentDocument) -> str:
    first = " ".join((doc.pages[0] if doc.pages else "").split())[:500]
    return (f"**Resumen básico**\n\nDocumento de {len(doc.pages)} páginas.\n\n"
            f"Inicio del texto: {first}…\n\n_{BASIC_NOTE}_")


def _basic_key_data(doc: AgentDocument) -> str:
    labels = {"title": "Título", "author": "Autor", "subject": "Asunto", "keywords": "Palabras clave",
              "creator": "Creador", "producer": "Productor", "creationDate": "Creación", "modDate": "Modificación"}
    rows = [f"- **{label}:** {doc.metadata[key]}" for key, label in labels.items() if doc.metadata.get(key)]
    body = "\n".join(rows) if rows else "El documento no tiene metadatos."
    return f"**Metadatos del PDF** ({doc.name}, {len(doc.pages)} páginas)\n\n{body}\n\n_{BASIC_NOTE}_"


def _basic_sensitive(doc: AgentDocument) -> tuple[str, list[dict]]:
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


def _without_key(text: str, key: str) -> str:
    """``text`` sin la clave de API (si aparece), para mostrarlo o registrarlo."""
    return text.replace(key, "•••") if key else text
