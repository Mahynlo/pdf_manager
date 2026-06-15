"""Data model for the merge feature — no Flet, no UI concerns.

Holds the per-PDF selection state (`PDFEntry`), the immutable description of
what to merge (`MergeSource`), and the helpers that convert between a boolean
page selection and the compact 1-based range notation shown in the UI.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

import fitz


# ── per-PDF accent color ──────────────────────────────────────────────────────

# Paleta de acentos distinguibles (legibles en claro y oscuro). Cada PDF recibe
# un color estable derivado de su ruta, para distinguir en la vista previa qué
# página pertenece a qué documento.
ACCENT_PALETTE = [
    "#1976D2",  # azul
    "#E64A19",  # naranja intenso
    "#388E3C",  # verde
    "#7B1FA2",  # morado
    "#C2185B",  # rosa
    "#00838F",  # turquesa
    "#F57C00",  # naranja
    "#5D4037",  # café
]


def accent_color_for(path: str) -> str:
    """Color de acento estable (independiente del orden) para un PDF dado."""
    return ACCENT_PALETTE[zlib.crc32(path.encode("utf-8")) % len(ACCENT_PALETTE)]


# ── range helpers ─────────────────────────────────────────────────────────────

def selection_to_range(selected: list[bool]) -> str:
    """Boolean list → compact 1-based range string, e.g. '1-5, 8, 10-15'."""
    pages = [i + 1 for i, s in enumerate(selected) if s]
    if not pages:
        return ""
    ranges: list[str] = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = p
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(ranges)


def parse_range(text: str, total: int) -> list[bool]:
    """'1-5, 8, 10-15' (1-based, semicolons allowed) → boolean selection list."""
    selected = [False] * total
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s.strip()), int(hi_s.strip())
                lo, hi = min(lo, hi), max(lo, hi)
                for i in range(max(1, lo), min(total, hi) + 1):
                    selected[i - 1] = True
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= total:
                    selected[n - 1] = True
            except ValueError:
                pass
    return selected


# ── model ─────────────────────────────────────────────────────────────────────

class PDFEntry:
    """One source PDF added to the merge list.

    Owns the open `fitz.Document` while the entry is in the list; `close()`
    releases it when the entry is removed or the tab is closed.
    """

    def __init__(self, path: str, doc: fitz.Document, password: str | None = None):
        self.path     = path
        self.filename = Path(path).name
        self.doc      = doc
        self.password = password
        self.is_encrypted = doc.is_encrypted
        self.total    = len(self.doc)
        # `selected` es la pertenencia (incluida/excluida) indexada por página
        # original; `order` es la secuencia EXPLÍCITA de salida de las páginas
        # incluidas. Invariante: `order` contiene exactamente los índices con
        # `selected[i] is True`. Toda mutación pasa por los métodos de abajo
        # para mantener ambos en sincronía.
        self.selected = [True] * self.total
        self.order    = list(range(self.total))
        self.chips_expanded = False

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    @property
    def selected_pages(self) -> list[int]:
        """Páginas incluidas en el orden de salida elegido por el usuario."""
        return list(self.order)

    @property
    def selected_count(self) -> int:
        return len(self.order)

    @property
    def is_reordered(self) -> bool:
        """True si el orden actual difiere del orden original ascendente."""
        return self.order != sorted(self.order)

    # ── mutadores de selección/orden (mantienen el invariante) ────────────────

    def toggle(self, page: int) -> None:
        if self.selected[page]:
            self.selected[page] = False
            try:
                self.order.remove(page)
            except ValueError:
                pass
        else:
            self.selected[page] = True
            if page not in self.order:
                self.order.append(page)

    def set_all(self, value: bool) -> None:
        if value:
            self.selected = [True] * self.total
            present = set(self.order)
            for p in range(self.total):
                if p not in present:
                    self.order.append(p)
        else:
            self.selected = [False] * self.total
            self.order = []

    def invert(self) -> None:
        self.selected = [not s for s in self.selected]
        self.order = [p for p in range(self.total) if self.selected[p]]

    def set_range(self, text: str) -> None:
        self.selected = parse_range(text, self.total)
        self.order = [p for p in range(self.total) if self.selected[p]]

    def move_page(self, from_page: int, to_page: int) -> None:
        """Reinserta `from_page` en la posición que ocupa `to_page` en el orden."""
        try:
            from_pos = self.order.index(from_page)
            to_pos = self.order.index(to_page)
        except ValueError:
            return
        pg = self.order.pop(from_pos)
        self.order.insert(to_pos, pg)

    def restore_order(self) -> None:
        """Restaura el orden original ascendente de las páginas incluidas."""
        self.order = sorted(self.order)

    def as_source(self) -> "MergeSource":
        """Immutable snapshot of this entry's current selection for merging."""
        return MergeSource(self.path, list(self.selected_pages), self.password)


@dataclass(frozen=True)
class MergeSource:
    """Immutable description of pages to pull from one PDF during a merge.

    Snapshots are taken before the background merge starts, so UI changes
    while merging cannot affect the result.
    """
    path: str
    pages: list[int]
    password: str | None = None
