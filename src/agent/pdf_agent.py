"""
PDF AI Agent — arquitectura híbrida Context Caching + RAG.

Flujo para preguntas de chat (RAG):
  1. El PDF se divide en chunks y se embebe con la API del proveedor (una sola vez).
  2. En cada pregunta se buscan los chunks más relevantes por similitud coseno.
  3. Solo esos fragmentos (~5-10 páginas) se envían al LLM junto con la pregunta.

Flujo para operaciones globales (summarize / analyze / extract / redact):
  - Se usa el documento completo, cacheado en el proveedor cuando es posible
    (Gemini CachedContent, 1 hora; OpenAI: caché automática > 1024 tokens).

Proveedores soportados: Google Gemini 2.5 Flash, OpenAI GPT-4o mini.
"""
from __future__ import annotations

import datetime
import json
import threading
import time
from typing import Callable, Iterator, Optional

import numpy as np

from .extractor import to_markdown, to_pages
from .rag import RAGIndex

# ── Retry helper ──────────────────────────────────────────────────────────────

def _with_retry(fn, *, retries: int = 4, base_delay: float = 2.0):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            recoverable = (
                "503" in msg or "UNAVAILABLE" in msg
                or "429" in msg or "RESOURCE_EXHAUSTED" in msg
            )
            if not recoverable or attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))

# ── System prompts ────────────────────────────────────────────────────────────

_SYSTEM = (
    "Eres un asistente especializado en análisis de documentos PDF. "
    "El documento completo ya está en tu contexto — puedes leer todo el contenido. "
    "Responde SIEMPRE en español. Sé claro, preciso y bien estructurado. "
    "Cuando extraigas datos (fechas, nombres, cifras), cítalos exactamente como aparecen."
)

_SYSTEM_RAG = (
    "Eres un asistente especializado en análisis de documentos PDF. "
    "Se te proporcionan fragmentos del documento seleccionados por relevancia semántica. "
    "Responde SIEMPRE en español. Sé claro, preciso y bien estructurado. "
    "Cita los datos (fechas, nombres, cifras) exactamente como aparecen en el contexto. "
    "Si el contexto proporcionado no contiene información suficiente para responder, "
    "indícalo explícitamente en lugar de inventar datos."
)

# ── One-shot action prompts ───────────────────────────────────────────────────

_PROMPT_SUMMARIZE = (
    "Genera un resumen completo y bien estructurado de este documento. "
    "Incluye: tipo de documento, tema principal, puntos clave y conclusiones."
)
_PROMPT_ANALYZE = (
    "Analiza la estructura de este documento y responde:\n"
    "1. Tipo de documento\n"
    "2. Secciones o apartados identificados\n"
    "3. Jerarquía del contenido\n"
    "4. Idioma principal\n"
    "5. Formato y organización general"
)
_PROMPT_EXTRACT = (
    "Extrae la información más importante de este documento. "
    "Incluye: datos clave, cifras, fechas, partes involucradas, "
    "compromisos, obligaciones y conclusiones. "
    "Presenta el resultado como una lista estructurada."
)


def _redact_prompt(level_desc: str) -> str:
    return (
        f"Analiza este documento e identifica información que debería redactarse "
        f"(nivel: {level_desc}).\n\n"
        "INSTRUCCIONES IMPORTANTES:\n"
        "1. Para cada dato sensible extrae el FRAGMENTO MÍNIMO necesario — solo el valor, "
        "nunca el contexto que lo rodea. "
        "Ejemplo correcto: «Juan García López». "
        "Ejemplo incorrecto: «El paciente Juan García López declaró que».\n"
        "2. No repitas el mismo dato con variaciones menores.\n"
        "3. Para datos estructurados (teléfonos, emails, números de ID, cuentas bancarias, "
        "códigos postales) usa tipo=\"patron\" con una expresión regular Python válida "
        "que capture todas las variantes del formato. "
        "Para textos libres (nombres, direcciones, frases) usa tipo=\"literal\".\n\n"
        "Devuelve SOLO un JSON válido con este esquema exacto (sin texto adicional):\n"
        '{"redacciones": [{"texto": "...", "categoria": "...", "motivo": "...", "tipo": "literal|patron"}]}\n\n'
        "Categorías: nombre, dni_id, dirección, teléfono, email, cuenta_bancaria, "
        "dato_médico, contraseña, fecha_nacimiento, otro.\n"
        "tipo=\"literal\": texto exacto tal como aparece en el documento.\n"
        "tipo=\"patron\": expresión regular Python sin delimitadores (ej: "
        r'r"\d{9}" para un número de 9 dígitos).'
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

class PDFAgent:
    """
    Agente de análisis PDF con búsqueda semántica (RAG) para chat y
    contexto completo cacheado para operaciones globales.

    Parameters
    ----------
    pdf_path : str
        Ruta al archivo PDF.
    api_key : str
        API key del proveedor elegido.
    provider : str
        ``"google"`` (Gemini) o ``"openai"``.
    model : str
        Nombre del modelo. Por defecto: gemini-2.5-flash / gpt-4o-mini.
    redact_callback : callable, optional
        Llamado con list[dict] cuando suggest_redactions encuentra términos.
        Cada dict contiene: texto, categoria, motivo, tipo (literal|patron).
    ocr_overrides : dict[int, str], optional
        Texto OCR por página (0-based) para documentos escaneados.
    """

    def __init__(
        self,
        pdf_path: str,
        api_key: str,
        provider: str = "google",
        model: str = "",
        redact_callback: Optional[Callable[[list[str]], None]] = None,
        ocr_overrides: Optional[dict[int, str]] = None,
    ) -> None:
        self._pdf_path      = pdf_path
        self._api_key       = api_key
        self._provider      = provider
        self._model         = model or ("gemini-2.5-flash" if provider == "google" else "gpt-4o-mini")
        self._callback      = redact_callback
        self._ocr_overrides = ocr_overrides or {}

        self._markdown:  str | None = None
        self._cache      = None               # Gemini CachedContent
        self._cache_lock = threading.Lock()

        # RAG index (built lazily on first chat call)
        self._rag:      RAGIndex | None = None
        self._rag_lock  = threading.Lock()
        self._embedder  = None                # langchain embedder instance

        if provider == "google":
            from google import genai
            self._client = genai.Client(api_key=api_key)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                model=self._model,
                api_key=api_key,
                temperature=0.2,
            )
        else:
            raise ValueError(f"Provider desconocido: {provider!r}. Usa 'google' u 'openai'.")

    # ── Full-document markdown (lazy) ─────────────────────────────────────────

    def _get_markdown(self) -> str:
        if self._markdown is None:
            self._markdown = to_markdown(self._pdf_path, self._ocr_overrides)
        return self._markdown

    def set_ocr_overrides(self, overrides: dict[int, str]) -> None:
        """Actualiza el texto OCR e invalida el markdown, el caché y el índice RAG."""
        self._ocr_overrides = overrides
        self._markdown = None
        with self._cache_lock:
            self._invalidate_gemini_cache()
        with self._rag_lock:
            self._rag = None

    # ── Gemini context cache (for full-document operations) ───────────────────

    def _invalidate_gemini_cache(self) -> None:
        if self._cache is None:
            return
        try:
            self._client.caches.delete(name=self._cache.name)
        except Exception:
            pass
        self._cache = None

    def _cache_is_valid(self) -> bool:
        if self._cache is None:
            return False
        expire = getattr(self._cache, "expire_time", None)
        if expire is None:
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        return expire > now + datetime.timedelta(minutes=5)

    def _ensure_gemini_cache(self) -> None:
        with self._cache_lock:
            if self._cache_is_valid():
                return
            self._invalidate_gemini_cache()
            from google.genai import types
            markdown = self._get_markdown()
            document_turn = [
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"Documento completo:\n\n{markdown}")],
                ),
                types.Content(
                    role="model",
                    parts=[types.Part(text=(
                        "Documento recibido y cargado en memoria. "
                        "Listo para responder preguntas sobre él."
                    ))],
                ),
            ]
            try:
                self._cache = _with_retry(lambda: self._client.caches.create(
                    model=self._model,
                    config=types.CreateCachedContentConfig(
                        system_instruction=_SYSTEM,
                        contents=document_turn,
                        ttl=datetime.timedelta(hours=1),
                    ),
                ))
            except Exception as exc:
                self._cache = None
                self._cache_error = str(exc)

    # ── RAG index (for chat) ──────────────────────────────────────────────────

    def _make_embedder(self):
        """Instantiate the provider's embedding model (langchain interface)."""
        if self._provider == "google":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=self._api_key,
            )
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=self._api_key,
        )

    def _ensure_rag_index(self) -> None:
        """Build the RAG index lazily (called once, blocking, before first chat)."""
        with self._rag_lock:
            if self._rag is not None and self._rag.is_ready:
                return
            pages = to_pages(self._pdf_path, self._ocr_overrides)
            rag = RAGIndex()
            rag.build_from_pages(pages)
            if rag.chunk_count == 0:
                self._rag = rag
                return
            if self._embedder is None:
                self._embedder = self._make_embedder()
            rag.embed_all(self._embedder.embed_documents)
            self._rag = rag

    def _embed_query(self, text: str) -> np.ndarray:
        if self._embedder is None:
            self._embedder = self._make_embedder()
        return np.array(self._embedder.embed_query(text), dtype=np.float32)

    def _rag_context(self, question: str) -> str:
        """Return a context block of semantically relevant document chunks."""
        query_emb = self._embed_query(question)
        chunks    = self._rag.retrieve(query_emb)          # type: ignore[union-attr]
        return RAGIndex.build_context(chunks)

    def _use_rag(self) -> bool:
        """True when the RAG index is ready and large enough to be useful."""
        return self._rag is not None and self._rag.needs_rag

    # ── Gemini — full-document ask ────────────────────────────────────────────

    def _ask_gemini(self, question: str, history: list[dict] | None = None) -> str:
        self._ensure_gemini_cache()
        from google.genai import types
        contents: list[types.Content] = []
        for h in (history or []):
            role = "user" if h["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=h["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        if self._cache is not None:
            config = types.GenerateContentConfig(
                cached_content=self._cache.name,
                temperature=0.2,
                max_output_tokens=8192,
            )
        else:
            markdown = self._get_markdown()
            contents.insert(0, types.Content(
                role="user", parts=[types.Part(text=f"Documento completo:\n\n{markdown}")]
            ))
            contents.insert(1, types.Content(
                role="model", parts=[types.Part(text="Documento recibido. Listo para responder.")]
            ))
            config = types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.2,
                max_output_tokens=8192,
            )
        response = _with_retry(lambda: self._client.models.generate_content(
            model=self._model, contents=contents, config=config,
        ))
        return response.text

    # ── Gemini — RAG ask ──────────────────────────────────────────────────────

    def _ask_gemini_rag(self, question: str, history: list[dict] | None = None) -> str:
        """Send only retrieved context chunks; no document cache needed."""
        from google.genai import types
        context   = self._rag_context(question)
        user_text = f"Contexto relevante del documento:\n\n{context}\n\nPregunta: {question}"
        contents: list[types.Content] = []
        for h in (history or []):
            role = "user" if h["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=h["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_RAG,
            temperature=0.2,
            max_output_tokens=8192,
        )
        response = _with_retry(lambda: self._client.models.generate_content(
            model=self._model, contents=contents, config=config,
        ))
        return response.text

    # ── Gemini — RAG streaming ────────────────────────────────────────────────

    def _stream_gemini_rag(self, question: str, history: list[dict]) -> Iterator[str]:
        from google.genai import types
        context   = self._rag_context(question)
        user_text = f"Contexto relevante del documento:\n\n{context}\n\nPregunta: {question}"
        contents: list[types.Content] = []
        for h in (history or []):
            role = "user" if h["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=h["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_RAG,
            temperature=0.2,
            max_output_tokens=8192,
        )
        base_delay = 2.0
        for attempt in range(4):
            try:
                for chunk in self._client.models.generate_content_stream(
                    model=self._model, contents=contents, config=config,
                ):
                    if chunk.text:
                        yield chunk.text
                return
            except Exception as exc:
                msg = str(exc)
                recoverable = (
                    "503" in msg or "UNAVAILABLE" in msg
                    or "429" in msg or "RESOURCE_EXHAUSTED" in msg
                )
                if not recoverable or attempt == 3:
                    raise
                time.sleep(base_delay * (2 ** attempt))

    # ── Gemini — full-document streaming ─────────────────────────────────────

    def _stream_gemini(self, question: str, history: list[dict]) -> Iterator[str]:
        self._ensure_gemini_cache()
        from google.genai import types
        contents: list[types.Content] = []
        for h in (history or []):
            role = "user" if h["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=h["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        config_kwargs: dict = dict(temperature=0.2, max_output_tokens=8192)
        if self._cache is not None:
            config_kwargs["cached_content"] = self._cache.name
        else:
            markdown = self._get_markdown()
            contents.insert(0, types.Content(
                role="user", parts=[types.Part(text=f"Documento:\n\n{markdown}")]
            ))
            contents.insert(1, types.Content(
                role="model", parts=[types.Part(text="Listo.")]
            ))
            config_kwargs["system_instruction"] = _SYSTEM
        base_delay = 2.0
        for attempt in range(4):
            try:
                for chunk in self._client.models.generate_content_stream(
                    model=self._model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_kwargs),
                ):
                    if chunk.text:
                        yield chunk.text
                return
            except Exception as exc:
                msg = str(exc)
                recoverable = (
                    "503" in msg or "UNAVAILABLE" in msg
                    or "429" in msg or "RESOURCE_EXHAUSTED" in msg
                )
                if not recoverable or attempt == 3:
                    raise
                time.sleep(base_delay * (2 ** attempt))

    # ── OpenAI — full-document ask ────────────────────────────────────────────

    def _ask_openai(self, question: str, history: list[dict] | None = None) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        markdown = self._get_markdown()
        messages = [SystemMessage(content=f"{_SYSTEM}\n\nDocumento completo:\n\n{markdown}")]
        for h in (history or []):
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                messages.append(AIMessage(content=h["content"]))
        messages.append(HumanMessage(content=question))
        return self._llm.invoke(messages).content

    # ── OpenAI — RAG ask ─────────────────────────────────────────────────────

    def _ask_openai_rag(self, question: str, history: list[dict] | None = None) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        context  = self._rag_context(question)
        messages = [SystemMessage(
            content=f"{_SYSTEM_RAG}\n\nContexto relevante del documento:\n\n{context}"
        )]
        for h in (history or []):
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                messages.append(AIMessage(content=h["content"]))
        messages.append(HumanMessage(content=question))
        return self._llm.invoke(messages).content

    # ── Dispatch helpers ──────────────────────────────────────────────────────

    def _ask(self, question: str, history: list[dict] | None = None) -> str:
        """Full-document path — used by summarize / analyze / extract / redact."""
        if self._provider == "google":
            return self._ask_gemini(question, history)
        return self._ask_openai(question, history)

    def _ask_chat(self, question: str, history: list[dict]) -> str:
        """Chat path — uses RAG when the index is large enough."""
        self._ensure_rag_index()
        if self._use_rag():
            if self._provider == "google":
                return self._ask_gemini_rag(question, history)
            return self._ask_openai_rag(question, history)
        return self._ask(question, history)

    # ── Public — one-shot actions (full document) ─────────────────────────────

    def summarize(self) -> str:
        return self._ask(_PROMPT_SUMMARIZE)

    def analyze_structure(self) -> str:
        return self._ask(_PROMPT_ANALYZE)

    def extract_key_info(self) -> str:
        return self._ask(_PROMPT_EXTRACT)

    def suggest_redactions(self, sensitivity: str = "medium") -> str:
        level_desc = {
            "low":    "solo datos críticos: números de identidad, contraseñas, secretos",
            "medium": "datos personales (nombres, DNI, dirección, teléfono, email) y financieros",
            "high":   "cualquier información personal, privada o potencialmente sensible",
        }.get(sensitivity, "datos personales y financieros")
        raw   = self._ask(_redact_prompt(level_desc))
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        text  = raw[start:end] if start >= 0 and end > start else ""
        try:
            data    = json.loads(text)
            records = [r for r in data.get("redacciones", []) if r.get("texto")]
            if records and self._callback is not None:
                # Pass full dicts so the UI can show category, motivo and tipo.
                self._callback(records)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return raw

    # ── Public — chat (RAG) ───────────────────────────────────────────────────

    def chat(self, message: str, history: list[dict]) -> str:
        """Pregunta libre con historial. Usa búsqueda semántica para el contexto."""
        return self._ask_chat(message, history)

    def stream_chat(self, message: str, history: list[dict]) -> Iterator[str]:
        """Versión streaming del chat con RAG (Gemini) o respuesta completa (OpenAI)."""
        self._ensure_rag_index()
        if self._use_rag():
            if self._provider == "google":
                yield from self._stream_gemini_rag(message, history)
                return
            # OpenAI streaming not implemented — fall through to single response
            yield self._ask_openai_rag(message, history)
            return
        # Fallback: full-document path
        if self._provider == "google":
            yield from self._stream_gemini(message, history)
        else:
            yield self._ask_openai(message, history)
