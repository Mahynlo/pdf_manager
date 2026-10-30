"""Servicio ``redact``: la censura de un documento del visor (equivale a ``redact_panel.py``
y ``redact_widgets.py`` en Qt).

Lo que se va a censurar son las marcas de censura del visor (anotaciones ``Redact`` de
EmbedPDF): se revisan, se mueven, se borran y se deshacen en la página. Este servicio busca
dónde aparece cada término (:meth:`RedactService.find`: frases, patrones, texto de OCR) para
que el visor ponga sus marcas, y aplica las marcas que le llegan con las anotaciones
(:meth:`RedactService.apply`).

Cada documento abierto guarda sus opciones de búsqueda, su color y su perfil activo en el
propio documento abierto, así desaparecen al cerrarlo. Los perfiles (listas de términos con
nombre) se comparten con las versiones Flet y Qt (``pdf_core.censorship_profiles``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.backend.rpc import UserError, exposed
from app.backend.services.viewer import ViewerService
from pdf_core import redaction
from pdf_core.censorship_profiles import get_profile_manager

SESSION = "redact"  # clave en ``_OpenDocument.extras``
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


@dataclass
class _Session:
    case_sensitive: bool = False
    whole_word: bool = False
    search_ocr: bool = True
    color: str = "#000000"
    profile_id: str | None = None


class RedactService:
    def __init__(self, viewer: ViewerService) -> None:
        self._viewer = viewer

    # ── Estado ───────────────────────────────────────────────────────────
    @exposed
    def state(self, doc_id: int) -> dict[str, Any]:
        """Opciones de búsqueda, color y perfil activo."""
        with self._viewer.document(doc_id) as entry:
            return self._state(entry)

    @exposed
    def patterns(self) -> list[dict[str, str]]:
        return [{"label": label, "pattern": pattern} for label, pattern in redaction.PII_PATTERNS]

    @exposed
    def set_options(self, doc_id: int, case_sensitive: bool, whole_word: bool, search_ocr: bool) -> dict[str, Any]:
        with self._viewer.document(doc_id) as entry:
            session = self._session(entry)
            session.case_sensitive, session.whole_word, session.search_ocr = (
                bool(case_sensitive), bool(whole_word), bool(search_ocr))
            return self._state(entry)

    @exposed
    def set_color(self, doc_id: int, color: str) -> dict[str, Any]:
        with self._viewer.document(doc_id) as entry:
            self._session(entry).color = _check_color(color)
            return self._state(entry)

    # ── Buscar ───────────────────────────────────────────────────────────
    @exposed
    def find(self, doc_id: int, terms: list[str]) -> list[dict[str, Any]]:
        """Dónde aparece cada término (frase o expresión regular), con las opciones del documento.

        Devuelve ``[{term, kind, matches: [{page, rect}]}]``, con ``rect`` en coordenadas de la
        página sin girar (las de las anotaciones). ``kind`` es ``texto`` o ``regex``.
        """
        terms = [t.strip() for t in terms if t.strip()]
        with self._viewer.document(doc_id) as entry:
            session = self._session(entry)
            texts: dict[int, str] = {}  # el texto de cada página se extrae una vez para todos los términos
            result = []
            for term in terms:
                regex = redaction.looks_like_regex(term)
                options = {"case_sensitive": session.case_sensitive, "whole_word": session.whole_word, "regex": regex}
                matches = []
                for index, page in enumerate(entry.doc):
                    if index not in texts:
                        texts[index] = page.get_text("text")
                    rects = redaction.find_in_page(page, term, text=texts[index], **options)
                    words = entry.ocr.get(entry.key(page)) if session.search_ocr else None
                    if words:  # las palabras de OCR están en la página vista
                        derot = page.derotation_matrix
                        found = [r * derot for r in redaction.find_in_ocr(words, term, **options)]
                        rects += [r for r in found if not any(r.intersects(n) for n in rects)]
                    matches += [{"page": index, "rect": [round(v, 2) for v in r]} for r in rects]
                result.append({"term": term, "kind": "regex" if regex else "texto", "matches": matches})
            return result

    # ── Aplicar ──────────────────────────────────────────────────────────
    @exposed
    def apply(self, doc_id: int) -> dict[str, Any]:
        """Censura de forma irreversible lo que tapan las marcas. ``{info, count}``.

        Las marcas llegan antes con las anotaciones del visor (``viewer.sync_annotations``).
        """
        info, count = self._viewer.apply_redaction_marks(doc_id)
        if not count:
            raise UserError("No hay marcas de censura en el documento.", "no_marks")
        with self._viewer.document(doc_id) as entry:
            self._session(entry).profile_id = None  # como Qt: tras aplicar, la lista queda vacía
        return {"info": info, "count": count}

    # ── Perfiles ─────────────────────────────────────────────────────────
    @exposed
    def profiles(self, query: str = "") -> list[dict[str, Any]]:
        return [{"id": p.id, "name": p.name, "terms": len(p.terms)} for p in get_profile_manager().search(query)]

    @exposed
    def create_profile(self, name: str) -> list[dict[str, Any]]:
        if not name.strip():
            raise UserError("Escribe un nombre para el perfil.", "empty_name")
        get_profile_manager().create(name.strip(), [])
        return self.profiles()

    @exposed
    def rename_profile(self, profile_id: str, name: str) -> list[dict[str, Any]]:
        if not name.strip():
            raise UserError("Escribe un nombre para el perfil.", "empty_name")
        get_profile_manager().update(profile_id, name=name.strip())
        return self.profiles()

    @exposed
    def delete_profile(self, profile_id: str) -> list[dict[str, Any]]:
        get_profile_manager().delete(profile_id)
        return self.profiles()

    @exposed
    def load_profile(self, doc_id: int, profile_id: str) -> dict[str, Any]:
        """Activa el perfil: sus opciones y su color. Devuelve ``{state, terms}``: el visor marca sus términos."""
        profile = get_profile_manager().get(profile_id)
        if profile is None:
            raise UserError("El perfil ya no existe.", "not_found")
        with self._viewer.document(doc_id) as entry:
            session = self._session(entry)
            session.case_sensitive, session.whole_word = profile.case_sensitive, profile.whole_word
            session.color = profile.color.upper() if HEX_COLOR.fullmatch(profile.color) else "#000000"
            session.profile_id = profile.id
            return {"state": self._state(entry), "terms": list(profile.terms)}

    @exposed
    def save_profile(self, doc_id: int, terms: list[str], name: str | None = None) -> dict[str, Any]:
        """Guarda ``terms`` (los términos marcados; no las selecciones ni las áreas, que son de este
        documento) en el perfil activo o, si no hay, en uno nuevo llamado ``name``."""
        manager = get_profile_manager()
        terms = list(dict.fromkeys(t.strip() for t in terms if t.strip()))
        if not terms:
            raise UserError("Añade al menos un término para guardar el perfil.", "no_terms")
        with self._viewer.document(doc_id) as entry:
            session = self._session(entry)
            options = {"terms": terms, "color": session.color, "case_sensitive": session.case_sensitive,
                       "whole_word": session.whole_word}
            if session.profile_id and manager.get(session.profile_id):
                manager.update(session.profile_id, **options)
            else:
                if not (name or "").strip():
                    raise UserError("Escribe un nombre para el perfil.", "empty_name")
                session.profile_id = manager.create(name.strip(), **options).id
            return self._state(entry)

    # ── Auxiliares ───────────────────────────────────────────────────────
    @staticmethod
    def _session(entry: Any) -> _Session:
        return entry.extras.setdefault(SESSION, _Session())

    def _state(self, entry: Any) -> dict[str, Any]:
        session = self._session(entry)
        profile = get_profile_manager().get(session.profile_id) if session.profile_id else None
        return {
            "case_sensitive": session.case_sensitive,
            "whole_word": session.whole_word,
            "search_ocr": session.search_ocr,
            "color": session.color,
            "profile": {"id": profile.id, "name": profile.name} if profile else None,
        }


def _check_color(color: str) -> str:
    if not HEX_COLOR.fullmatch(color or ""):
        raise UserError("Color no válido.", "bad_color")
    return color.upper()
