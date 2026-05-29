"""Data model and pure helpers for the extraction feature — no Flet, no I/O.

Holds the match record (`PageMatch`) and the small pure transforms that parse
page ranges, tokenize text, and split the keyword input.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PageMatch:
    """One page selected for extraction, with its relevance score."""
    source_path: str
    page_index: int
    score: float
    reason: str


def parse_pages(page_input: str, total_pages: int) -> set[int]:
    """'1,3-5' (1-based, semicolons allowed) → set of 0-based page indices."""
    out: set[int] = set()
    if not page_input.strip():
        return out
    for chunk in [c.strip() for c in page_input.replace(";", ",").split(",") if c.strip()]:
        if "-" in chunk:
            parts = chunk.split("-", 1)
            try:
                a, b = int(parts[0].strip()), int(parts[1].strip())
                if a > b:
                    a, b = b, a
                out.update(idx - 1 for idx in range(a, b + 1) if 0 < idx <= total_pages)
            except ValueError:
                pass
        else:
            try:
                idx = int(chunk) - 1
                if 0 <= idx < total_pages:
                    out.add(idx)
            except ValueError:
                pass
    return out


def normalize_words(text: str) -> set[str]:
    """Lower-cased alphanumeric tokens of length ≥ 4 (for Jaccard similarity)."""
    words: set[str] = set()
    for raw in text.lower().replace("\n", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 4:
            words.add(token)
    return words


def collect_keywords(raw: str) -> list[str]:
    """Split the keyword box (lines and/or commas) into lower-cased terms."""
    chunks: list[str] = []
    for row in raw.splitlines():
        chunks.extend(part.strip() for part in row.split(","))
    return [c.lower() for c in chunks if c]


def doc_kind_label(kind: str) -> str:
    return {"native": "Texto nativo", "hybrid": "Híbrido", "scanned": "Escaneado"}.get(
        kind, kind
    )
