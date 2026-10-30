"""Data model and pure helpers for the extraction feature — no Flet, no I/O.

Holds the match record (`PageMatch`) and the small pure transforms that parse
page ranges, tokenize text, and split the keyword input.
"""
from __future__ import annotations

from dataclasses import dataclass

from pdf_core.page_ranges import parse_pages  # noqa: F401  (reexportado: lo usan engine y el cliente Qt)


@dataclass
class PageMatch:
    """One page selected for extraction, with its relevance score."""
    source_path: str
    page_index: int
    score: float
    reason: str



def normalize_words(text: str) -> set[str]:
    """Lower-cased alphanumeric tokens of length ≥ 4 (for Jaccard similarity)."""
    words: set[str] = set()
    for raw in text.lower().replace("\n", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 4:
            words.add(token)
    return words


def collect_keywords(raw: str, lower: bool = True) -> list[str]:
    """Split the keyword box (lines and/or commas) into terms (lower-cased by default)."""
    chunks: list[str] = []
    for row in raw.splitlines():
        chunks.extend(part.strip() for part in row.split(","))
    return [c.lower() if lower else c for c in chunks if c]


def doc_kind_label(kind: str) -> str:
    return {"native": "Texto nativo", "hybrid": "Híbrido", "scanned": "Escaneado"}.get(
        kind, kind
    )
