"""Utilidades de texto (búsqueda sin tildes)."""

from __future__ import annotations

# Es habitual escribir los términos sin tilde, así que "COMITÉ" debe coincidir
# con "COMITE" y "Pública" con "Publica". La ñ/Ñ se PRESERVA a propósito: es una
# letra propia del español, no una "n con tilde" ("año" ≠ "ano"). La tabla es
# 1:1 (no cambia la longitud), así los índices de una búsqueda sobre el texto
# plegado siguen siendo válidos en el texto original (búsqueda OCR, censura).
_ACCENT_FOLD = str.maketrans(
    "áàäâãéèëêíìïîóòöôõúùüûÁÀÄÂÃÉÈËÊÍÌÏÎÓÒÖÔÕÚÙÜÛ",
    "aaaaaeeeeiiiiooooouuuuAAAAAEEEEIIIIOOOOOUUUU",
)


def fold_accents(s: str) -> str:
    """Quita tildes y diéresis conservando la ñ y la longitud (``"Canción"`` → ``"Cancion"``)."""
    return s.translate(_ACCENT_FOLD)
