"""RAG utilities: text chunking, in-memory vector index, semantic retrieval.

Pipeline
--------
1. build_from_pages()  — split pymupdf4llm page chunks into smaller Chunk objects.
2. embed_all()         — embed every chunk via a provider embedding function.
3. retrieve()          — cosine similarity search; returns top-K + adjacent neighbors.
4. build_context()     — format selected chunks into a readable context block.

No external vector-store dependency: similarity is computed with numpy (already
a transitive dependency via onnxruntime).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


# ── Chunking constants ────────────────────────────────────────────────────────

_CHUNK_SIZE    = 1800   # chars ≈ 450 tokens
_CHUNK_OVERLAP = 200    # chars
_TOP_K         = 6      # candidates before neighbor expansion
_RAG_MIN_CHUNKS = 8     # below this, RAG adds no benefit → use full context


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    text:      str
    page_num:  int          # 1-based
    chunk_idx: int          # position within page
    embedding: np.ndarray | None = field(default=None, repr=False)


# ── Index ─────────────────────────────────────────────────────────────────────

class RAGIndex:
    """In-memory semantic index built from page-chunked document text."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._matrix: np.ndarray | None = None   # shape (n, dim), float32

    # ── Build ─────────────────────────────────────────────────────────────────

    def build_from_pages(self, pages: list[dict]) -> None:
        """
        Populate the index from the list returned by ``extractor.to_pages()``.

        Each page dict must have ``metadata.page_number`` (1-based) and ``text``.
        """
        self._chunks = []
        self._matrix = None
        for page_data in pages:
            pn   = page_data["metadata"].get("page_number", 1)
            text = (page_data.get("text") or "").strip()
            if not text:
                continue
            for idx, chunk_text in enumerate(self._split_text(text)):
                self._chunks.append(Chunk(text=chunk_text, page_num=pn, chunk_idx=idx))

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """Sliding-window split with overlap."""
        size    = _CHUNK_SIZE
        overlap = _CHUNK_OVERLAP
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            chunks.append(text[start:end])
            if end == len(text):
                break
            start += size - overlap
        return chunks or [text]

    # ── Embed ─────────────────────────────────────────────────────────────────

    def embed_all(
        self,
        embed_fn: Callable[[list[str]], list[list[float]]],
        batch_size: int = 96,
    ) -> None:
        """
        Embed all chunks and build the similarity matrix.

        Parameters
        ----------
        embed_fn:
            Function that accepts a list of strings and returns a list of
            float vectors (e.g. ``embedder.embed_documents``).
        batch_size:
            Maximum number of texts per API call (Gemini caps at 100).
        """
        texts = [c.text for c in self._chunks]
        if not texts:
            return

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            all_embeddings.extend(embed_fn(texts[i : i + batch_size]))

        for chunk, emb in zip(self._chunks, all_embeddings):
            chunk.embedding = np.array(emb, dtype=np.float32)

        self._matrix = np.stack([c.embedding for c in self._chunks], axis=0)

    # ── Retrieve ──────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query_emb: np.ndarray,
        top_k: int = _TOP_K,
    ) -> list[Chunk]:
        """
        Return the most relevant chunks via cosine similarity.

        Each top-K hit is expanded with its immediate neighbors so the LLM
        receives continuous context rather than isolated fragments.
        The result is sorted in document order.
        """
        if self._matrix is None or not self._chunks:
            return list(self._chunks)

        q = query_emb.astype(np.float32)
        q /= np.linalg.norm(q) + 1e-9

        norms  = np.linalg.norm(self._matrix, axis=1, keepdims=True) + 1e-9
        scores = (self._matrix / norms) @ q          # shape (n,)

        k       = min(top_k, len(self._chunks))
        top_idx = np.argpartition(scores, -k)[-k:]
        top_idx = sorted(top_idx.tolist(), key=lambda i: float(-scores[i]))

        # Expand each hit with its immediate neighbors.
        expanded: set[int] = set()
        for idx in top_idx:
            for neighbor in (idx - 1, idx, idx + 1):
                if 0 <= neighbor < len(self._chunks):
                    expanded.add(neighbor)

        # Return in document order for coherent reading.
        return [self._chunks[i] for i in sorted(expanded)]

    # ── Context formatting ────────────────────────────────────────────────────

    @staticmethod
    def build_context(chunks: list[Chunk]) -> str:
        """Format retrieved chunks as a readable context block with page markers."""
        parts: list[str] = []
        prev_page: int | None = None
        for chunk in chunks:
            if chunk.page_num != prev_page:
                parts.append(f"<!-- Página {chunk.page_num} -->")
                prev_page = chunk.page_num
            parts.append(chunk.text)
        return "\n\n".join(parts)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._matrix is not None and len(self._chunks) > 0

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def needs_rag(self) -> bool:
        """True when the index is large enough to benefit from retrieval."""
        return self.is_ready and self._chunks.__len__() >= _RAG_MIN_CHUNKS
