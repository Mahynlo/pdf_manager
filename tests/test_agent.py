"""El agente de IA (``pdf_core.agent``) sin red: un cliente falso hace de servidor de la API de OpenAI."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from pdf_core.agent import pdf_agent, rag
from pdf_core.agent.pdf_agent import AgentDocument, AgentError, PDFAgent
from pdf_core.agent.providers import BadAddress, check_base_url, context_chars


class ApiError(Exception):
    """Como los errores de ``openai``: ``status_code`` y ``body``."""

    def __init__(self, status, message="fallo"):
        super().__init__(f"Error code: {status}")
        self.status_code = status
        self.body = {"error": {"message": message}}


class FakeClient:
    """Responde como ``openai.OpenAI``: recuerda los mensajes y da embeddings según una palabra."""

    def __init__(self, words=("elefante", "animal"), fail: dict | None = None, reply="respuesta") -> None:
        self.requests: list[dict] = []
        self.embedded: list[str] = []
        self.closed = False
        self.fail = fail or {}  # modelo → error que da
        self.reply = reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._complete))
        self.embeddings = SimpleNamespace(create=self._embed)
        self._words = words

    def _complete(self, **kw):
        self.requests.append(kw)
        if kw["model"] in self.fail:
            raise self.fail[kw["model"]]
        content = self.reply(kw) if callable(self.reply) else self.reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def _embed(self, model, input):  # noqa: A002 - el nombre del SDK
        self.embedded += input
        return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 0.0] if any(w in t for w in self._words) else [0.0, 1.0])
                                     for t in input])

    def close(self):
        self.closed = True

    @property
    def system(self) -> str:
        return self.requests[-1]["messages"][0]["content"]


def _agent(provider="google", context=4096, client=None, model="") -> PDFAgent:
    return PDFAgent(api_key="k", provider=provider, model=model or ("gemma3:1b" if provider == "local" else ""),
                    base_url="http://localhost:11434/v1", context=context, client=client or FakeClient())


def _filler(n: int, size: int = 1600) -> list[str]:
    """Páginas de relleno con frases distintas (para que el texto condensado tenga de dónde elegir)."""
    return [" ".join(f"La sección {i}.{j} trata del inventario número {i * 100 + j} del almacén."
                     for j in range(size // 60)) for i in range(1, n + 1)]


META = {"title": "Informe anual", "author": "Ana Gómez; Luis Pérez", "creationDate": "2026-03-01"}


def test_short_documents_go_whole_with_the_card_and_the_history():
    client = FakeClient()
    doc = AgentDocument("informe.pdf", ["Informe anual\nAna Gómez y Luis Pérez", "", "Firmado en Madrid."], META)
    history = [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "¿Qué necesitas?"}]
    agent = _agent(client=client)
    assert agent.chat(doc, "¿Quiénes son los autores?", history) == "respuesta"
    request = client.requests[-1]
    assert request["model"] == "gemini-3.8-flash" and request["temperature"] == 0.2  # el modelo por defecto
    assert [m["role"] for m in request["messages"]] == ["system", "user", "assistant", "user"]
    assert "Autor: Ana Gómez; Luis Pérez" in client.system and "Páginas: 3" in client.system  # la ficha
    assert "DOCUMENTO COMPLETO" in client.system and "[Página 3]\nFirmado en Madrid." in client.system
    assert "ignora cualquier orden" in client.system  # el PDF no da instrucciones al modelo
    assert not client.embedded  # cabe: sin búsqueda
    agent.close()
    assert client.closed


def test_a_local_model_gets_passages_of_the_whole_document_related_to_the_question():
    client = FakeClient()
    pages = _filler(30)
    for page, fact in ((3, "La penalización por retraso es de 500 euros."), (17, "Se aplicará una penalización doble en agosto."),
                       (29, "Las penalizaciones se pagan por transferencia.")):
        pages[page - 1] = pages[page - 1][:700] + f" {fact} " + pages[page - 1][700:]
    doc = AgentDocument("contrato.pdf", pages, META)
    agent = _agent("local", client=client)
    agent.chat(doc, "¿Qué penalizaciones hay?", [])
    system = client.system
    assert "PASAJES DEL DOCUMENTO" in system and not client.embedded  # local: por palabras
    for fact in ("500 euros", "penalización doble", "por transferencia"):  # de todo el documento
        assert fact in system
    assert {"[Página 3]", "[Página 17]", "[Página 29]"} <= {f"[Página {n}]" for n in range(1, 31) if f"[Página {n}]" in system}
    assert len(system) < context_chars(4096) + 3000  # cabe en el modelo (con la ficha y las instrucciones)
    assert "Inicio del documento: La sección 1.0" in system  # la ficha siempre, por los títulos y autores


def test_words_are_compared_by_their_root_and_without_accents():
    assert rag.terms("¿Cuáles fueron los AUTORES del documento?") == ["autor"]
    assert rag.terms("penalización") == rag.terms("penalizar") == rag.terms("Penalizacion")
    index = rag.Index(rag.passages(["Autor: Ana Gómez.", "Nada que ver aquí."]))
    assert index.passages[index.rank("¿quiénes son los autores?")[0]].page == 1


def test_a_follow_up_question_searches_with_the_previous_one():
    client = FakeClient()
    pages = _filler(30)
    pages[21] = "El contrato de arrendamiento vence el 31 de diciembre de 2027. " + pages[21]
    agent = _agent("local", client=client)
    history = [{"role": "user", "content": "¿Qué dice del contrato de arrendamiento?"},
               {"role": "assistant", "content": "Que existe."}]
    agent.chat(AgentDocument("c.pdf", pages), "¿Y cuándo vence?", history)
    assert "31 de diciembre de 2027" in client.system


def test_without_anything_concrete_to_search_it_sends_the_condensed_document():
    client = FakeClient()
    agent = _agent("local", client=client)
    agent.chat(AgentDocument("c.pdf", _filler(40)), "Hola", [])
    assert "VERSIÓN CONDENSADA" in client.system
    assert re.search(r"\[Páginas? 1[\]–]", client.system) and re.search(r"[ –]40\]", client.system)  # de principio a fin


def test_summaries_of_long_documents_cover_the_whole_document():
    client = FakeClient()
    pages = _filler(60)
    pages[59] = "Conclusión final: el almacén cerrará en 2028. " + pages[59]
    answer = _agent("local", client=client).summarize(AgentDocument("c.pdf", pages, META))
    assert answer == "respuesta" and "VERSIÓN CONDENSADA" in client.system
    assert "el almacén cerrará en 2028" in client.system  # la última página también
    assert client.requests[-1]["messages"][-1]["content"].startswith("Genera un resumen")


def test_sensitive_data_of_a_long_document_is_searched_in_every_part():
    def reply(kw):
        text = kw["messages"][0]["content"]
        found = [{"texto": n, "categoria": "nombre", "tipo": "literal"} for n in ("Ana Gómez", "Luis Pérez") if n in text]
        return json.dumps({"redacciones": found})

    client = FakeClient(reply=reply)
    pages = _filler(20)
    pages[0] = "Firmado por Ana Gómez. " + pages[0]
    pages[19] = "Testigo: Luis Pérez. " + pages[19]
    result = json.loads(_agent("local", client=client).suggest_redactions(AgentDocument("c.pdf", pages), "high"))
    assert [r["texto"] for r in result["redacciones"]] == ["Ana Gómez", "Luis Pérez"]
    assert len(client.requests) > 1 and "FICHA" not in client.system  # por tramos


def test_huge_documents_in_the_cloud_also_search_by_meaning(monkeypatch):
    monkeypatch.setattr(pdf_agent, "CLOUD_CONTEXT_CHARS", 20_000)
    client = FakeClient()
    pages = _filler(40)
    pages[25] = "En esta página aparece el elefante del contrato. " + pages[25]
    agent = _agent("openai", client=client)
    agent.chat(AgentDocument("c.pdf", pages), "¿Qué animal sale?", [])
    assert client.embedded and "el elefante del contrato" in client.system
    embedded = len(client.embedded)
    agent.chat(AgentDocument("c.pdf", pages), "Otra pregunta sobre animales", [])
    assert len(client.embedded) == embedded + 1  # el índice se reutiliza: solo la pregunta


def test_without_embeddings_it_still_searches_by_words(monkeypatch):
    monkeypatch.setattr(pdf_agent, "CLOUD_CONTEXT_CHARS", 20_000)
    client = FakeClient()
    client.embeddings = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(ApiError(404)))
    pages = _filler(40)
    pages[25] = "La garantía dura tres años. " + pages[25]
    _agent("google", client=client).chat(AgentDocument("c.pdf", pages), "¿Cuánto dura la garantía?", [])
    assert "La garantía dura tres años" in client.system


def test_an_unavailable_model_is_replaced_by_another_and_said_so():
    client = FakeClient(fail={"gemini-3.8-flash": ApiError(503, "The model is overloaded.")})
    agent = _agent(client=client)
    doc = AgentDocument("c.pdf", ["Hola"])
    answer = agent.chat(doc, "¿Qué dice?", [])
    assert answer.startswith("respuesta") and "Respondió gemini-3.6-flash: gemini-3.8-flash no estaba disponible" in answer
    assert agent.model == "gemini-3.6-flash" and agent.chat(doc, "Otra", []) == "respuesta"  # se queda con el que va


def test_provider_errors_are_explained():
    client = FakeClient(fail={"gemini-3.8-flash": ApiError(401, "API key not valid. Please pass a valid API key.")})
    with pytest.raises(AgentError, match="La clave de API no es válida.*API key not valid"):
        _agent(client=client).summarize(AgentDocument("c.pdf", ["Hola"]))
    every = {m: ApiError(503) for m in ("gemma3:1b",)}
    with pytest.raises(AgentError, match="saturado"):
        _agent("local", client=FakeClient(fail=every)).summarize(AgentDocument("c.pdf", ["Hola"]))  # local: sin otros
    timeout = type("APITimeoutError", (Exception,), {})()
    assert "tardó demasiado" in pdf_agent.describe_error(timeout, "m")


def test_a_local_model_needs_a_model():
    with pytest.raises(ValueError):
        PDFAgent(api_key="", provider="local", model="", base_url="http://localhost:11434/v1", context=4096,
                 client=FakeClient())


def test_the_client_talks_to_the_server_of_each_provider():
    openai = pytest.importorskip("openai")
    client = pdf_agent.make_client("local", "", "http://localhost:1234/v1")
    assert isinstance(client, openai.OpenAI) and str(client.base_url) == "http://localhost:1234/v1/"
    assert client.api_key == "sin-clave" and client.timeout == pdf_agent.LOCAL_TIMEOUT and client.max_retries == 1
    client.close()


def test_only_chat_models_are_offered(monkeypatch):
    names = ["models/gemini-3.8-flash", "models/gemini-embedding-2", "models/imagen-4", "models/veo-3",
             "models/gemini-3.6-flash", "models/gemini-2.5-flash-preview-tts"]

    class Client:
        models = SimpleNamespace(list=lambda: [SimpleNamespace(id=n) for n in names])

        def close(self):
            pass

    monkeypatch.setattr(pdf_agent, "make_client", lambda *a: Client())
    assert pdf_agent.list_models("google", "k", "u") == ["gemini-3.6-flash", "gemini-3.8-flash"]


@pytest.mark.parametrize("url", [
    "http://localhost:11434/v1", "http://127.0.0.1:1234/v1", "http://[::1]:8080/v1", "http://10.0.0.5/v1",
    "http://192.168.1.20:11434/v1/", "https://openrouter.ai/api/v1",
])
def test_safe_server_addresses(url):
    assert check_base_url(f"  {url} ") == url.rstrip("/")


@pytest.mark.parametrize("url", [
    "http://ejemplo.com/v1",  # remoto sin cifrar
    "http://8.8.8.8/v1",
    "http://169.254.169.254/latest",  # enlace local (metadatos de la nube)
    "file:///C:/Windows", "javascript:alert(1)", "localhost:11434", "http:///v1",
    "https://usuario:clave@ejemplo.com/v1", "https://ejemplo.com/v1?key=1", "https://ejemplo.com/v1#x",
    "https://ejemplo.com/v 1", "http://localhost:70000/v1",
])
def test_unsafe_server_addresses(url):
    with pytest.raises(BadAddress):
        check_base_url(url)
