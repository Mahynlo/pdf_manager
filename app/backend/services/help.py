"""Servicio ``help`` (Ayuda): guías en Markdown convertidas a HTML, con su índice y un buscador.

El HTML se genera sin permitir HTML crudo dentro del Markdown (``html=False``):
así es seguro insertarlo en la página tal cual.

Cada guía empieza así (``src/assets/ayuda/``; el número del nombre del archivo da el orden)::

    # 📄 Visor de PDF
    Leer, recorrer y organizar un documento.     ← resumen (el primer párrafo)

    ## Primera sección                            ← entrada del índice de la guía

Dentro de las guías:

- ```Ctrl+S``` (código con una tecla) se muestra como teclas: ``<kbd>Ctrl</kbd>+<kbd>S</kbd>``.
- Una cita que empieza por **Consejo:**, **Importante:** o **Nota:** es un recuadro de ese tipo.
"""

from __future__ import annotations

import base64
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

from app import PROJECT_ROOT
from app.backend.rpc import UserError, exposed

log = logging.getLogger(__name__)

# Carpetas donde se buscan los manuales (la primera que exista).
DOCS_DIRS: tuple[Path, ...] = (
    PROJECT_ROOT / "src" / "assets" / "ayuda",
    PROJECT_ROOT / "docs" / "ayuda",
    PROJECT_ROOT / "assets" / "ayuda",
)


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml"}

# Una combinación de teclas escrita como código: `Ctrl+S`, `Ctrl+Mayús+S`, `Supr`, `F3`, `↑`.
_KEY = r"(?:Ctrl|Mayús|Shift|Alt|Supr|Intro|Esc|Tab|Inicio|Fin|Re Pág|Av Pág|Rueda|F\d{1,2}|[A-Z0-9]|[+\-=]|[↑↓←→]|−)"
_KEYS = re.compile(rf"^{_KEY}(?:\s*\+\s*{_KEY})*$")
# Recuadros: la primera palabra en negrita de la cita.
_CALLOUTS = {"consejo": "tip", "importante": "warning", "atención": "warning", "nota": "note"}
# Emoji (o símbolo) al principio del título: el icono de la guía.
_ICON = re.compile(r"^(\W+?)\s+(?=\w)")
_SEARCH_RESULTS = 12


def _fold(text: str) -> str:
    """Minúsculas y sin tildes: «Índice» y «indice» se encuentran igual."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _find(text: str, word: str) -> int:
    """Posición en ``text`` de ``word`` (ya sin tildes), o -1: la de ``_fold(text)`` no vale, porque
    quitar tildes cambia la longitud."""
    folded, starts = "", []
    for i, char in enumerate(text):
        piece = _fold(char)
        starts.extend([i] * len(piece))
        folded += piece
    at = folded.find(word)
    return starts[at] if at >= 0 else -1


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(text)).strip("-") or "seccion"


def _plain(markdown: str) -> str:
    """Texto sin las marcas de Markdown (para los fragmentos del buscador)."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)  # imágenes
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # enlaces: su texto
    text = re.sub(r"[*_`#>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _keys(text: str) -> str:
    """``Ctrl+S`` → ``<kbd>Ctrl</kbd>+<kbd>S</kbd>``; en ``Ctrl++`` el segundo «+» es la tecla."""
    parts = re.split(r"(?<=\S)\s*\+\s*(?=\S)", text)
    return "+".join(f"<kbd>{escapeHtml(part)}</kbd>" for part in parts)


class HelpService:
    def __init__(self, docs_dirs: tuple[Path, ...] = DOCS_DIRS) -> None:
        self._dir = next((d for d in docs_dirs if d.is_dir()), None)
        self._markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
        rules = self._markdown.renderer.rules
        default_image = rules["image"]
        default_code = rules["code_inline"]

        def image(_renderer, tokens, idx, options, env):
            tokens[idx].attrSet("src", self._image_src(tokens[idx].attrGet("src") or ""))
            tokens[idx].attrSet("loading", "lazy")
            return default_image(tokens, idx, options, env)

        def code_inline(_renderer, tokens, idx, options, env):
            content = tokens[idx].content.strip()
            if _KEYS.match(content):
                return f'<span class="keys">{_keys(content)}</span>'
            return default_code(tokens, idx, options, env)

        self._markdown.add_render_rule("image", image)
        self._markdown.add_render_rule("code_inline", code_inline)

    # ── Imágenes ──────────────────────────────────────────────────────────
    def _image_src(self, src: str) -> str:
        """Imagen local del manual como data URL.

        Las rutas como ``/ayuda_img/x.png`` son relativas a la carpeta de recursos (la
        que contiene la de manuales); no se sirve nada fuera de ella.
        """
        if self._dir is None or src.startswith(("http://", "https://", "data:")):
            return src
        root = self._dir.parent.resolve()
        path = (root / src.lstrip("/")).resolve()
        mime = _IMAGE_TYPES.get(path.suffix.lower())
        if mime is None or not path.is_relative_to(root) or not path.is_file():
            return src
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    # ── Guías ─────────────────────────────────────────────────────────────
    def _files(self) -> list[Path]:
        return sorted(self._dir.glob("*.md")) if self._dir else []

    def _read(self, file_name: str) -> str:
        if file_name not in {f.name for f in self._files()}:
            raise UserError("Documento no encontrado.", "not_found")
        try:
            return (self._dir / file_name).read_text(encoding="utf-8")  # type: ignore[operator]
        except OSError as ex:
            log.warning("No se pudo leer la ayuda %s", file_name, exc_info=True)
            raise UserError(f"No se pudo leer el documento: {ex}", "read_error") from ex

    def _parse(self, file_name: str, text: str) -> dict[str, Any]:
        """Título, icono, resumen, índice y los tokens del cuerpo (sin el título ni el resumen)."""
        tokens = self._markdown.parse(text)
        title, icon, summary = re.sub(r"^\d+_", "", Path(file_name).stem).replace("_", " ").capitalize(), "", ""
        if len(tokens) > 2 and tokens[0].type == "heading_open" and tokens[0].tag == "h1":
            title = tokens[1].content.replace("**", "").strip()
            if match := _ICON.match(title):
                icon, title = match.group(1).strip(), title[match.end():]
            tokens = tokens[3:]
            if len(tokens) > 2 and tokens[0].type == "paragraph_open":
                summary = _plain(tokens[1].content)
                tokens = tokens[3:]
        sections: list[dict[str, str]] = []
        used: set[str] = set()
        for i, token in enumerate(tokens):
            if token.type == "heading_open" and token.tag == "h2":
                name = tokens[i + 1].content.replace("**", "").strip()
                anchor = _slug(name)
                while anchor in used:
                    anchor += "-2"
                used.add(anchor)
                token.attrSet("id", anchor)
                sections.append({"id": anchor, "title": name})
            elif token.type == "blockquote_open" and i + 2 < len(tokens) and tokens[i + 2].type == "inline":
                first = re.match(r"\*\*([^*:]+):?\*\*", tokens[i + 2].content)
                kind = _CALLOUTS.get(_fold(first.group(1)).strip()) if first else None
                if kind:
                    token.attrJoin("class", f"callout callout--{kind}")
        return {"title": title, "icon": icon, "summary": summary, "sections": sections, "tokens": tokens}

    @exposed
    def documents(self) -> list[dict[str, str]]:
        """Las guías en orden: ``file``, ``title``, ``icon`` (un emoji) y ``summary``."""
        guides = []
        for path in self._files():
            try:
                info = self._parse(path.name, path.read_text(encoding="utf-8"))
            except OSError:
                log.warning("No se pudo leer la ayuda %s", path.name, exc_info=True)
                continue
            guides.append({"file": path.name, "title": info["title"], "icon": info["icon"], "summary": info["summary"]})
        return guides

    @exposed
    def document(self, file_name: str) -> dict[str, Any]:
        """Guía ``file_name`` como HTML, con su índice; solo se aceptan los nombres que da :meth:`documents`."""
        info = self._parse(file_name, self._read(file_name))
        html = self._markdown.renderer.render(info.pop("tokens"), self._markdown.options, {})
        return {**info, "html": html}

    @exposed
    def search(self, query: str) -> list[dict[str, str]]:
        """Secciones de todas las guías que contienen todas las palabras de ``query`` (sin tildes ni
        mayúsculas): ``file``, ``guide``, ``section`` (id; vacío si es el principio), ``title`` y ``snippet``."""
        words = _fold(query).split()
        if not words:
            return []
        results: list[dict[str, str]] = []
        for path in self._files():
            text = path.read_text(encoding="utf-8")
            info = self._parse(path.name, text)
            ids = iter(info["sections"])
            # Trozos de la guía: el principio (con el título) y cada «## sección».
            for n, chunk in enumerate(re.split(r"^## ", text, flags=re.MULTILINE)):
                section = next(ids, None) if n else None
                if not n:
                    chunk = re.sub(r"^# .*$", "", chunk, count=1, flags=re.MULTILINE)  # el título ya se muestra
                plain = _plain(chunk)
                if not all(word in _fold(plain) for word in words):
                    continue
                start = max(0, _find(plain, words[0]) - 60)
                snippet = ("…" if start else "") + plain[start:start + 180].strip() + ("…" if start + 180 < len(plain) else "")
                results.append({
                    "file": path.name,
                    "guide": info["title"],
                    "section": section["id"] if section else "",
                    "title": section["title"] if section else info["title"],
                    "snippet": snippet,
                })
                if len(results) >= _SEARCH_RESULTS:
                    return results
        return results
