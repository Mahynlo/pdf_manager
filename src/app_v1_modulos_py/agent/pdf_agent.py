"""
PDF AI Agent — arquitectura Context Caching.

Flujo:
  1. El PDF se convierte a Markdown (pymupdf4llm) una sola vez.
  2. El Markdown se sube a la API del proveedor como contexto cacheado.
     - Gemini: CachedContent explícito (google-genai SDK).
       Duración: 1 hora. Se renueva automáticamente.
     - OpenAI: automático en servidor para prompts > 1024 tokens.
  3. Cada pregunta del usuario envía SOLO la pregunta + historial.
     El modelo ya "conoce" el documento desde la caché.

Coste estimado después del primer upload:
  Gemini  → ~90 % menos tokens por pregunta.
  OpenAI  → cache hit automático, descuento según plan.

Soporta Google Gemini 2.5 Flash y OpenAI GPT-4o mini.
"""
from __future__ import annotations

import datetime
import json
import threading
import time
from typing import Callable, Iterator, Optional

from .extractor import to_markdown

# ── Retry helper ──────────────────────────────────────────────────────────────

def _with_retry(fn, *, retries: int = 4, base_delay: float = 2.0):
    """
    Ejecuta fn() con reintentos exponenciales ante errores 503/429.
    Lanza la última excepción si se agotan los intentos.
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            recoverable = "503" in msg or "UNAVAILABLE" in msg or "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if not recoverable or attempt == retries - 1:
                raise
            delay = base_delay * (2 ** attempt)   # 2 s, 4 s, 8 s, 16 s
            time.sleep(delay)

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = (
    "Eres un asistente especializado en análisis de documentos PDF. "
    "El documento completo ya está en tu contexto — puedes leer todo el contenido. "
    "Responde SIEMPRE en español. Sé claro, preciso y bien estructurado. "
    "Cuando extraigas datos (fechas, nombres, cifras), cítalos exactamente como aparecen."
)

# Prompts reutilizables para las acciones directas
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
        f"(nivel: {level_desc}).\n"
        "Devuelve SOLO un JSON válido con este esquema exacto:\n"
        '{"redacciones": [{"texto": "...", "categoria": "...", "motivo": "..."}]}\n'
        "Categorías posibles: nombre, dni_id, dirección, teléfono, email, "
        "cuenta_bancaria, dato_médico, contraseña, otro.\n"
        "Incluye solo el texto literal que aparece en el documento, no patrones."
    )


# ── Agent class ───────────────────────────────────────────────────────────────

class PDFAgent:
    """
    Agente de análisis PDF con Context Caching.

    El documento se convierte a Markdown y se cachea en el proveedor
    una sola vez por sesión. Las preguntas posteriores son baratas.

    Parameters
    ----------
    pdf_path : str
        Ruta al archivo PDF.
    api_key : str
        API key del proveedor elegido.
    provider : str
        "google" (Gemini) o "openai".
    model : str
        Nombre del modelo. Por defecto: gemini-2.5-flash / gpt-4o-mini.
    redact_callback : callable, optional
        Llamado con list[str] cuando suggest_redactions encuentra términos.
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

        self._markdown:     str | None = None           # markdown del documento
        self._cache         = None                      # CachedContent (Gemini)
        self._cache_lock    = threading.Lock()

        # Inicializar cliente según proveedor
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

    # ── Markdown del documento (lazy, una sola vez) ────────────────────────────

    def _get_markdown(self) -> str:
        if self._markdown is None:
            self._markdown = to_markdown(self._pdf_path, self._ocr_overrides)
        return self._markdown

    def set_ocr_overrides(self, overrides: dict[int, str]) -> None:
        """Actualiza el texto OCR e invalida el caché (Markdown y contexto remoto)."""
        self._ocr_overrides = overrides
        self._markdown = None
        with self._cache_lock:
            self._invalidate_gemini_cache()

    # ── Context Cache — Gemini ─────────────────────────────────────────────────

    def _invalidate_gemini_cache(self) -> None:
        """Elimina el caché remoto de Gemini (debe llamarse con _cache_lock)."""
        if self._cache is None:
            return
        try:
            self._client.caches.delete(name=self._cache.name)
        except Exception:
            pass
        self._cache = None

    def _cache_is_valid(self) -> bool:
        """True si el caché existe y le quedan más de 5 minutos de vida."""
        if self._cache is None:
            return False
        expire = getattr(self._cache, "expire_time", None)
        if expire is None:
            return True  # sin TTL conocido, asumimos válido
        now = datetime.datetime.now(datetime.timezone.utc)
        return expire > now + datetime.timedelta(minutes=5)

    def _ensure_gemini_cache(self) -> None:
        """
        Crea o renueva el CachedContent de Gemini con el documento completo.
        Se ejecuta como máximo una vez por hora.
        """
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
                # Documento demasiado pequeño u otro error de caching:
                # marcamos cache=None para que _ask_gemini use fallback directo.
                self._cache = None
                self._cache_error = str(exc)

    # ── Petición al modelo ─────────────────────────────────────────────────────

    def _ask_gemini(self, question: str, history: list[dict] | None = None) -> str:
        self._ensure_gemini_cache()

        from google.genai import types

        # Construir los mensajes de conversación (sin el documento, ya está en caché)
        contents: list[types.Content] = []
        for h in (history or []):
            role = "user" if h["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=h["content"])])
            )
        contents.append(
            types.Content(role="user", parts=[types.Part(text=question)])
        )

        if self._cache is not None:
            # Camino eficiente: documento en caché
            config = types.GenerateContentConfig(
                cached_content=self._cache.name,
                temperature=0.2,
                max_output_tokens=8192,
            )
        else:
            # Fallback: documento pequeño o error de caché → incluirlo inline
            markdown = self._get_markdown()
            contents.insert(
                0,
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"Documento completo:\n\n{markdown}")],
                ),
            )
            contents.insert(
                1,
                types.Content(
                    role="model",
                    parts=[types.Part(text="Documento recibido. Listo para responder.")],
                ),
            )
            config = types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.2,
                max_output_tokens=8192,
            )

        response = _with_retry(lambda: self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        ))
        return response.text

    def _ask_openai(self, question: str, history: list[dict] | None = None) -> str:
        """
        OpenAI: incluye el markdown completo en cada request.
        OpenAI cachea automáticamente prompts > 1024 tokens,
        así que a partir de la segunda pregunta hay descuento.
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        markdown = self._get_markdown()
        messages = [
            SystemMessage(content=f"{_SYSTEM}\n\nDocumento completo:\n\n{markdown}")
        ]
        for h in (history or []):
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                messages.append(AIMessage(content=h["content"]))
        messages.append(HumanMessage(content=question))

        return self._llm.invoke(messages).content

    def _ask(self, question: str, history: list[dict] | None = None) -> str:
        """Despacha al proveedor correcto."""
        if self._provider == "google":
            return self._ask_gemini(question, history)
        return self._ask_openai(question, history)

    # ── Métodos directos (1 llamada LLM cada uno) ─────────────────────────────

    def summarize(self) -> str:
        """Resumen completo del documento."""
        return self._ask(_PROMPT_SUMMARIZE)

    def analyze_structure(self) -> str:
        """Análisis de estructura y tipo del documento."""
        return self._ask(_PROMPT_ANALYZE)

    def extract_key_info(self) -> str:
        """Extracción de información clave."""
        return self._ask(_PROMPT_EXTRACT)

    def suggest_redactions(self, sensitivity: str = "medium") -> str:
        """
        Identificación de información sensible a redactar.
        Llama a redact_callback con la lista de términos encontrados.
        """
        level_desc = {
            "low":    "solo datos críticos: números de identidad, contraseñas, secretos",
            "medium": "datos personales (nombres, DNI, dirección, teléfono, email) y financieros",
            "high":   "cualquier información personal, privada o potencialmente sensible",
        }.get(sensitivity, "datos personales y financieros")

        raw = self._ask(_redact_prompt(level_desc))

        # Extraer el bloque JSON de la respuesta
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        text  = raw[start:end] if start >= 0 and end > start else ""

        try:
            data  = json.loads(text)
            terms = [r["texto"] for r in data.get("redacciones", []) if r.get("texto")]
            if terms and self._callback is not None:
                self._callback(terms)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return raw

    # ── Chat (preguntas libres con historial) ──────────────────────────────────

    def chat(self, message: str, history: list[dict]) -> str:
        """
        Pregunta libre con historial de conversación.
        El documento ya está en la caché del proveedor.
        """
        return self._ask(message, history)

    def stream_chat(self, message: str, history: list[dict]) -> Iterator[str]:
        """
        Versión streaming del chat (Gemini solamente).
        Para OpenAI hace una llamada normal y devuelve de golpe.
        """
        if self._provider == "google":
            yield from self._stream_gemini(message, history)
        else:
            yield self._ask_openai(message, history)

    def _stream_gemini(self, question: str, history: list[dict]) -> Iterator[str]:
        self._ensure_gemini_cache()

        from google.genai import types

        contents: list[types.Content] = []
        for h in (history or []):
            role = "user" if h["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=h["content"])])
            )
        contents.append(
            types.Content(role="user", parts=[types.Part(text=question)])
        )

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
                return   # stream completo sin error
            except Exception as exc:
                msg = str(exc)
                recoverable = "503" in msg or "UNAVAILABLE" in msg or "429" in msg or "RESOURCE_EXHAUSTED" in msg
                if not recoverable or attempt == 3:
                    raise
                time.sleep(base_delay * (2 ** attempt))
