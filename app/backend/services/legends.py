"""Servicio ``legends``: sellos rápidos y leyendas guardadas (menú «Sellos» del visor).

Usa el mismo almacén que Qt y Flet (``pdf_core.legends``), así las tres
versiones comparten las leyendas. Equivale a ``legends_dialog.py`` en Qt.
"""

from __future__ import annotations

import re
from typing import Any

from app.backend.rpc import UserError, exposed
from pdf_core.legends import TextLegend, get_legend_manager
from pdf_core.stamps import DEFAULT_STAMPS, STAMP_FONT_SIZE, hex_to_rgb, rgb_to_hex

FAVORITES = 5  # leyendas más usadas que aparecen en el menú
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _legend(legend: TextLegend) -> dict[str, Any]:
    return {
        "id": legend.id, "name": legend.name, "text": legend.text,
        "color": rgb_to_hex(legend.color), "font_size": round(legend.fontsize),
    }


class LegendsService:
    @exposed
    def menu(self) -> dict[str, Any]:
        """Sellos rápidos y las leyendas más usadas (se pide al abrir el menú)."""
        return {
            "stamps": [{"text": text, "color": color} for text, color in DEFAULT_STAMPS],
            "favorites": [_legend(x) for x in get_legend_manager().most_used(FAVORITES)],
        }

    @exposed
    def all(self) -> list[dict[str, Any]]:
        return [_legend(x) for x in get_legend_manager().all()]

    @exposed
    def create(self, text: str, color: str, font_size: int = STAMP_FONT_SIZE) -> list[dict[str, Any]]:
        text = text.strip()
        if not text:
            raise UserError("Escribe el texto del sello.", "empty")
        if not _HEX.match(color or ""):
            raise UserError("Color no válido.", "bad_color")
        get_legend_manager().create(text, text, fontsize=max(8, min(72, int(font_size))), color=hex_to_rgb(color))
        return self.all()

    @exposed
    def delete(self, legend_id: str) -> list[dict[str, Any]]:
        get_legend_manager().delete(legend_id)
        return self.all()

    @exposed
    def used(self, legend_id: str) -> None:
        """Se insertó la leyenda: sube en el menú de favoritas."""
        get_legend_manager().bump_usage(legend_id)
