"""Qué parte del documento recibe el modelo cuando no cabe entero.

- :func:`passages`: el texto de cada página en pasajes cortos (~700 caracteres, cortados entre
  frases), así lo que se envía es lo pertinente y no páginas enteras.
- :class:`Index`: busca los pasajes de **todo el documento** que más se relacionan con la
  pregunta: por palabras (BM25, con las palabras reducidas a su raíz y sin acentos: «autores»
  encuentra «autor») y, si hay embeddings, también por significado; las dos listas se combinan
  (*reciprocal rank fusion*).
- :func:`select`: los mejores pasajes que caben en el presupuesto, como mucho unos pocos por
  página (así la respuesta puede reunir datos de todo el documento), en el orden del documento.
- :func:`condense`: una versión condensada del documento entero (las frases más informativas de
  cada tramo de páginas) para resumir o preguntar en general cuando no cabe.

Sin dependencias: NumPy solo para los embeddings.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

PASSAGE = 700  # caracteres por pasaje (~200 tokens)
PER_PAGE = 3  # pasajes como mucho de una misma página en una selección
RRF_K = 60  # constante de reciprocal rank fusion
_K1, _B = 1.5, 0.75  # BM25
_SENTENCE = re.compile(r"(?<=[.!?;:])\s+|\n{2,}")
# Palabras que no ayudan a buscar (español e inglés, ya sin acentos).
STOPWORDS = frozenset("""
que cual cuales quien quienes como cuando donde cuanto cuantos cuanta cuantas porque para por con sin
sobre entre desde hasta los las del una uno unos unas este esta estos estas ese esa esos esas aquel
fue fueron era eran ser son esta estan estaba hay han habia tiene tienen tenia sus mas muy tambien
pero sino algo nada todo todos toda todas cada otro otra otros otras dime dame puedes podrias favor
documento documentos texto pdf archivo the and for with what who which when where how are was were this that
from have has had about does did can could please tell
""".split())


@dataclass(frozen=True)
class Passage:
    page: int  # desde 1
    text: str


def passages(pages: Sequence[str], size: int = PASSAGE) -> list[Passage]:
    """Los pasajes de todas las páginas: frases seguidas hasta ``size`` caracteres."""
    result: list[Passage] = []
    for number, text in enumerate(pages, start=1):
        current = ""
        for sentence in _sentences(text):
            while len(sentence) > size:  # una «frase» enorme (tabla, lista sin puntos): se corta
                if current:
                    result.append(Passage(number, current))
                    current = ""
                result.append(Passage(number, sentence[:size]))
                sentence = sentence[size:]
            if current and len(current) + 1 + len(sentence) > size:
                result.append(Passage(number, current))
                current = ""
            current = f"{current} {sentence}" if current else sentence
        if current:
            result.append(Passage(number, current))
    return result


def terms(text: str) -> list[str]:
    """Las palabras que cuentan para buscar: sin acentos, sin las vacías y reducidas a su raíz."""
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", folded) if len(w) > 2 and w not in STOPWORDS]


def _stem(word: str) -> str:
    """Raíz aproximada (español e inglés): sin plural y con 7 letras como mucho
    («autores» → «autor», «penalización» y «penalizar» → «penaliz»)."""
    if word.isdigit():
        return word
    for ending in ("es", "s"):
        if len(word) > 4 and word.endswith(ending):
            word = word[: -len(ending)]
            break
    return word[:7]


def _sentences(text: str) -> list[str]:
    return [" ".join(s.split()) for s in _SENTENCE.split(text) if s.strip()]


class Index:
    """Los pasajes de un documento y lo necesario para buscar en ellos (se hace una vez)."""

    def __init__(self, items: list[Passage]) -> None:
        self.passages = items
        self._counts = [Counter(terms(p.text)) for p in items]
        self._lengths = [sum(c.values()) or 1 for c in self._counts]
        self._average = sum(self._lengths) / len(self._lengths) if items else 1.0
        self._df = Counter(t for c in self._counts for t in c)
        self._vectors: np.ndarray | None = None

    @property
    def has_vectors(self) -> bool:
        return self._vectors is not None

    @property
    def total_chars(self) -> int:
        return sum(len(p.text) for p in self.passages)

    def embed(self, embed: Callable[[list[str]], list], batch: int = 96) -> None:
        """Embeddings de todos los pasajes, normalizados (para buscar también por significado)."""
        vectors = []
        texts = [p.text for p in self.passages]
        for start in range(0, len(texts), batch):
            vectors += [np.asarray(v, dtype=np.float32) for v in embed(texts[start:start + batch])]
        if vectors:
            matrix = np.stack(vectors)
            self._vectors = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)

    def rank(self, query: str, query_vector: Sequence[float] | None = None) -> list[int]:
        """Los pasajes que tienen algo que ver con ``query``, del más al menos pertinente."""
        lists = []
        scores = self._bm25(terms(query))
        by_words = [i for i in sorted(range(len(scores)), key=lambda i: -scores[i]) if scores[i] > 0]
        if by_words:
            lists.append(by_words)
        if query_vector is not None and self._vectors is not None:
            q = np.asarray(query_vector, dtype=np.float32)
            similarity = self._vectors @ (q / (np.linalg.norm(q) + 1e-9))
            lists.append([int(i) for i in np.argsort(-similarity)[: max(len(by_words), 30)]])
        if len(lists) == 1:
            return lists[0]
        fused: Counter[int] = Counter()
        for ranking in lists:
            for position, index in enumerate(ranking):
                fused[index] += 1 / (RRF_K + position + 1)
        return [i for i, _ in fused.most_common()]

    def _bm25(self, query: list[str]) -> list[float]:
        n = len(self.passages)
        scores = [0.0] * n
        for term in set(query):
            df = self._df.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, count in enumerate(self._counts):
                tf = count.get(term, 0)
                if tf:
                    scores[i] += idf * tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * self._lengths[i] / self._average))
        return scores

    def informative(self, sentence: str) -> float:
        """Cuánto aporta una frase: palabras propias de este documento (ni rarísimas ni en todas partes)."""
        n = len(self.passages) or 1
        words = terms(sentence)
        if not words:
            return 0.0
        return sum(math.log(1 + n / (1 + self._df.get(w, 0))) for w in set(words) if self._df.get(w, 0) > 1) / (
            1 + math.log(1 + len(words)))


def select(index: Index, ranking: list[int], budget: int, per_page: int = PER_PAGE) -> list[Passage]:
    """Los pasajes mejor clasificados que caben en ``budget`` caracteres, como mucho ``per_page``
    de cada página, en el orden del documento."""
    chosen: list[int] = []
    used = 0
    pages: Counter[int] = Counter()
    for i in ranking:
        passage = index.passages[i]
        if pages[passage.page] >= per_page or used + len(passage.text) > budget:
            continue
        chosen.append(i)
        used += len(passage.text)
        pages[passage.page] += 1
    return [index.passages[i] for i in sorted(chosen)]


def condense(index: Index, budget: int, block_chars: int = 400) -> str:
    """El documento entero en ``budget`` caracteres: las páginas se agrupan en tramos y de cada
    tramo van sus frases más informativas (y la primera, que suele ser un título), en orden."""
    by_page: dict[int, list[str]] = {}
    for p in index.passages:
        by_page.setdefault(p.page, []).extend(_sentences(p.text))
    numbers = sorted(by_page)
    if not numbers:
        return ""
    blocks = max(1, min(len(numbers), budget // block_chars))
    size = math.ceil(len(numbers) / blocks)
    share = budget // math.ceil(len(numbers) / size)
    parts = []
    for start in range(0, len(numbers), size):
        group = numbers[start:start + size]
        sentences = [(page, s) for page in group for s in by_page[page]]
        best = sorted(range(len(sentences)), key=lambda i: -index.informative(sentences[i][1]))
        keep, used = {0}, len(sentences[0][1])
        for i in best:
            if i not in keep and used + len(sentences[i][1]) <= share:
                keep.add(i)
                used += len(sentences[i][1])
        label = f"Página {group[0]}" if len(group) == 1 else f"Páginas {group[0]}–{group[-1]}"
        text = " … ".join(sentences[i][1][:share] for i in sorted(keep))
        parts.append(f"[{label}] {text}")
    return "\n\n".join(parts)


def format_passages(items: list[Passage]) -> str:
    """Los pasajes con la página de cada uno; los seguidos de una página, juntos."""
    parts: list[str] = []
    page = None
    for p in items:
        if p.page != page:
            parts.append(f"[Página {p.page}] {p.text}")
            page = p.page
        else:
            parts[-1] += f" … {p.text}"
    return "\n\n".join(parts)
