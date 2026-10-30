"""Sellos de texto: los rápidos del menú «Sellos» y su aspecto al insertarlos.

Las leyendas guardadas por el usuario viven en ``pdf_core.legends``
(``~/.extraer_pdfs_legends.json``), compartido por todas las versiones.
"""

from __future__ import annotations

# Sellos rápidos siempre disponibles en el menú «Sellos» (texto, color).
DEFAULT_STAMPS: list[tuple[str, str]] = [
    ("CONFIDENCIAL", "#D32F2F"),
    ("APROBADO", "#2E7D32"),
    ("BORRADOR", "#E65100"),
    ("URGENTE", "#C2185B"),
    ("COPIA", "#1565C0"),
    ("REVISADO", "#00838F"),
]

STAMP_FONT_SIZE = 13  # pt, como add_stamp_legend en Qt
STAMP_BORDER = 1.5  # pt
STAMP_SIZE = (105.0, 29.0)  # pt (210×58 en la escena de Qt, a 2 unidades por punto)


def rgb_to_hex(rgb: tuple[float, float, float] | list[float]) -> str:
    """Color RGB 0..1 (formato del almacén de leyendas) → ``#RRGGBB``."""
    r, g, b = (max(0, min(255, round(c * 255))) for c in list(rgb)[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
