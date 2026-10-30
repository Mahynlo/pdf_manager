"""Interpretación de rangos de páginas escritos por el usuario ("1, 3-5; 8")."""

from __future__ import annotations


def parse_pages(page_input: str, total_pages: int) -> set[int]:
    """'1,3-5' (1-based, ``;`` también separa) → conjunto de índices 0-based.

    Ignora valores fuera de rango o mal escritos y acepta rangos invertidos
    ("5-3" == "3-5").
    """
    out: set[int] = set()
    for chunk in (c.strip() for c in page_input.replace(";", ",").split(",")):
        if not chunk:
            continue
        try:
            if "-" in chunk:
                a_s, b_s = chunk.split("-", 1)
                a, b = sorted((int(a_s.strip()), int(b_s.strip())))
                out.update(n - 1 for n in range(a, b + 1) if 0 < n <= total_pages)
            else:
                n = int(chunk)
                if 0 < n <= total_pages:
                    out.add(n - 1)
        except ValueError:
            continue
    return out


def parse_page_list(page_input: str, total_pages: int) -> list[int]:
    """Como :func:`parse_pages`, pero como lista ordenada."""
    return sorted(parse_pages(page_input, total_pages))


SCOPES = ("all", "current", "custom", "odd", "even")
SUBSETS = ("all", "odd", "even")


def select_pages(
    total_pages: int,
    scope: str,
    custom: str = "",
    current: int = 0,
    subset: str = "all",
    reverse: bool = False,
) -> list[int]:
    """Páginas (0-based) elegidas en un diálogo de impresión u OCR por lotes.

    ``scope``: todas, la actual, un rango escrito (``custom``), o solo impares/pares.
    ``subset`` filtra después por impares/pares (numeración 1-based, como se ven) y
    ``reverse`` invierte el orden. Valores desconocidos lanzan ``ValueError``.
    """
    if scope not in SCOPES or subset not in SUBSETS:
        raise ValueError(f"selección no válida: {scope!r}, {subset!r}")
    if scope == "all":
        pages = list(range(total_pages))
    elif scope == "current":
        pages = [current] if 0 <= current < total_pages else []
    elif scope == "custom":
        pages = parse_page_list(custom, total_pages)
    else:
        pages = list(range(0 if scope == "odd" else 1, total_pages, 2))
    if subset != "all":
        pages = [p for p in pages if (p % 2 == 0) == (subset == "odd")]
    return pages[::-1] if reverse else pages
