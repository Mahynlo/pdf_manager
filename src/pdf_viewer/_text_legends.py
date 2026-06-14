"""Plantillas de texto ("leyendas") — guardar/cargar textos pre-escritos
reutilizables que se insertan rápidamente como anotaciones de texto.

Mismo patrón que ``_censorship_profiles`` (singleton + JSON en el home del
usuario), pero el contenido es un texto libre en vez de una lista de términos.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_LEGENDS_FILE = Path.home() / ".extraer_pdfs_legends.json"
_singleton: "LegendManager | None" = None


# Estilo por defecto de una leyenda (refleja los DEFAULT_TEXT_* del editor; se
# mantienen aquí para que la capa de almacenamiento no dependa del visor).
_DEF_FONT  = "helv"
_DEF_SIZE  = 14.0
_DEF_COLOR = (0.0, 0.0, 0.0)
_DEF_ALIGN = 0
_DEF_BW    = 0.0


@dataclass
class TextLegend:
    id: str           # identificador único (UUID)
    name: str         # nombre corto que se muestra en el menú
    text: str         # texto pre-escrito que se inserta (modificable al colocar)
    # Estilo guardado (misma config que el modal de texto), para insertar la
    # frase ya formateada sin tener que reconfigurarla cada vez.
    fontname: str = _DEF_FONT
    fontsize: float = _DEF_SIZE
    color: tuple[float, float, float] = _DEF_COLOR
    align: int = _DEF_ALIGN
    border_width: float = _DEF_BW
    use_count: int = 0      # nº de veces insertada (ordena el menú rápido)
    last_used: float = 0.0  # epoch de la última inserción (desempata el orden)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "text": self.text,
            "fontname": self.fontname,
            "fontsize": self.fontsize,
            "color": list(self.color),
            "align": self.align,
            "border_width": self.border_width,
            "use_count": self.use_count,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextLegend":
        color = d.get("color", _DEF_COLOR)
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Sin nombre"),
            text=d.get("text", ""),
            fontname=d.get("fontname", _DEF_FONT) or _DEF_FONT,
            fontsize=float(d.get("fontsize", _DEF_SIZE) or _DEF_SIZE),
            color=tuple(color) if color is not None else _DEF_COLOR,
            align=int(d.get("align", _DEF_ALIGN) or 0),
            border_width=float(d.get("border_width", _DEF_BW) or 0.0),
            use_count=int(d.get("use_count", 0) or 0),
            last_used=float(d.get("last_used", 0.0) or 0.0),
        )

    def style_props(self) -> dict:
        """Config de estilo en el formato que consume el editor de texto."""
        return {
            "text":         self.text,
            "fontname":     self.fontname,
            "fontsize":     self.fontsize,
            "color":        tuple(self.color),
            "align":        self.align,
            "border_width": self.border_width,
        }


class LegendManager:
    def __init__(self) -> None:
        self._legends: list[TextLegend] = []
        self._load()

    def _load(self) -> None:
        try:
            if _LEGENDS_FILE.exists():
                data = json.loads(_LEGENDS_FILE.read_text(encoding="utf-8"))
                self._legends = [
                    TextLegend.from_dict(x) for x in data.get("legends", [])
                ]
        except Exception:
            self._legends = []

    def _save(self) -> None:
        try:
            _LEGENDS_FILE.write_text(
                json.dumps(
                    {"legends": [x.to_dict() for x in self._legends]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def all(self) -> list[TextLegend]:
        return list(self._legends)

    def most_used(self, limit: int = 5) -> list[TextLegend]:
        """Devuelve las leyendas más usadas (desempate: uso más reciente)."""
        ordered = sorted(
            self._legends,
            key=lambda x: (x.use_count, x.last_used),
            reverse=True,
        )
        return ordered[:limit] if limit and limit > 0 else ordered

    def bump_usage(self, legend_id: str) -> bool:
        """Registra una inserción: +1 al contador y marca el uso reciente."""
        x = self.get(legend_id)
        if x is None:
            return False
        x.use_count += 1
        x.last_used = time.time()
        self._save()
        return True

    def search(self, query: str) -> list[TextLegend]:
        q = query.strip().lower()
        if not q:
            return self.all()
        return [
            x for x in self._legends
            if q in x.name.lower() or q in x.text.lower()
        ]

    def get(self, legend_id: str) -> TextLegend | None:
        return next((x for x in self._legends if x.id == legend_id), None)

    def create(
        self,
        name: str,
        text: str,
        *,
        fontname: str = _DEF_FONT,
        fontsize: float = _DEF_SIZE,
        color: tuple[float, float, float] = _DEF_COLOR,
        align: int = _DEF_ALIGN,
        border_width: float = _DEF_BW,
    ) -> TextLegend:
        legend = TextLegend(
            id=str(uuid.uuid4()),
            name=name.strip() or "Sin nombre",
            text=text,
            fontname=fontname or _DEF_FONT,
            fontsize=float(fontsize),
            color=tuple(color),
            align=int(align),
            border_width=float(border_width),
        )
        self._legends.append(legend)
        self._save()
        return legend

    def update(
        self,
        legend_id: str,
        *,
        name: str | None = None,
        text: str | None = None,
        fontname: str | None = None,
        fontsize: float | None = None,
        color: tuple[float, float, float] | None = None,
        align: int | None = None,
        border_width: float | None = None,
    ) -> bool:
        x = self.get(legend_id)
        if x is None:
            return False
        if name is not None:
            x.name = name.strip() or x.name
        if text is not None:
            x.text = text
        if fontname is not None:
            x.fontname = fontname or x.fontname
        if fontsize is not None:
            x.fontsize = float(fontsize)
        if color is not None:
            x.color = tuple(color)
        if align is not None:
            x.align = int(align)
        if border_width is not None:
            x.border_width = float(border_width)
        self._save()
        return True

    def delete(self, legend_id: str) -> bool:
        before = len(self._legends)
        self._legends = [x for x in self._legends if x.id != legend_id]
        if len(self._legends) < before:
            self._save()
            return True
        return False


def get_legend_manager() -> LegendManager:
    """Devuelve el singleton ``LegendManager`` (lo crea en el primer uso)."""
    global _singleton
    if _singleton is None:
        _singleton = LegendManager()
    return _singleton
