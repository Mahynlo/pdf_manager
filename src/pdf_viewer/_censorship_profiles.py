"""Censorship profile persistence — save/load named lists of redaction terms."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

_PROFILES_FILE = Path.home() / ".extraer_pdfs_profiles.json"
_singleton: "ProfileManager | None" = None


@dataclass
class CensorshipProfile:
    id: str # unique identifier, e.g. UUID
    name: str # human-friendly name for the profile
    terms: list[str] # list of terms to censor (exact matches, not regex)
    color: str = "#000000" # hex color code for highlighting censored terms
    case_sensitive: bool = True # whether term matching is case-sensitive
    whole_word: bool = True # whether to match whole words only ("la" ≠ "tabla")

    def to_dict(self) -> dict:
        """Funcion se encarga de convertir el perfil a un diccionario para su almacenamiento."""
        return {
            "id": self.id,
            "name": self.name,
            "terms": list(self.terms),
            "color": self.color,
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CensorshipProfile":
        """
        Crea un perfil de censura a partir de un diccionario.
        """
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Sin nombre"),
            terms=list(d.get("terms", [])),
            color=d.get("color", "#000000"),
            case_sensitive=bool(d.get("case_sensitive", True)),
            whole_word=bool(d.get("whole_word", True)),
        )


class ProfileManager:
    def __init__(self) -> None:
        self._profiles: list[CensorshipProfile] = []
        self._load()

    def _load(self) -> None:
        """
        Crga el perfil de cencura desde un archivo JSON. Si el archivo no existe o hay un error, se inicia con una lista vacía de perfiles.
        """
        try:
            if _PROFILES_FILE.exists():
                data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
                self._profiles = [
                    CensorshipProfile.from_dict(p) for p in data.get("profiles", [])
                ]
        except Exception:
            self._profiles = []

    def _save(self) -> None:
        """
        Guarda el perfil de cencura en un archivo JSON.
        """
        try:
            _PROFILES_FILE.write_text(
                json.dumps(
                    {"profiles": [p.to_dict() for p in self._profiles]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def all(self) -> list[CensorshipProfile]:
        """
        Retorna una lista de todos los perfiles de censura.
        """
        return list(self._profiles)

    def search(self, query: str) -> list[CensorshipProfile]:
        """
        Busca perfiles de cenecura.
        """
        q = query.strip().lower()
        if not q:
            return self.all()
        return [
            p for p in self._profiles
            if q in p.name.lower() or any(q in t.lower() for t in p.terms)
        ]

    def get(self, profile_id: str) -> CensorshipProfile | None:
        return next((p for p in self._profiles if p.id == profile_id), None)

    def create(
        self,
        name: str,
        terms: list[str],
        color: str = "#000000",
        case_sensitive: bool = True,
        whole_word: bool = True,
    ) -> CensorshipProfile:
        """
        Crea un nuevo perfil de censura.
        """
        profile = CensorshipProfile(
            id=str(uuid.uuid4()),
            name=name.strip() or "Sin nombre",
            terms=list(terms),
            color=color,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
        )
        self._profiles.append(profile)
        self._save()
        return profile

    def update(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        terms: list[str] | None = None,
        color: str | None = None,
        case_sensitive: bool | None = None,
        whole_word: bool | None = None,
    ) -> bool:
        """
        Actualiza un perfil de censura existente.
        """
        p = self.get(profile_id)
        if p is None:
            return False
        if name is not None:
            p.name = name.strip() or p.name
        if terms is not None:
            p.terms = list(terms)
        if color is not None:
            p.color = color
        if case_sensitive is not None:
            p.case_sensitive = case_sensitive
        if whole_word is not None:
            p.whole_word = whole_word
        self._save()
        return True

    def delete(self, profile_id: str) -> bool:
        """
        Elimina un perfil de censura.
        """
        before = len(self._profiles)
        self._profiles = [p for p in self._profiles if p.id != profile_id]
        if len(self._profiles) < before:
            self._save()
            return True
        return False


def get_profile_manager() -> ProfileManager:
    """
    Retorna el singleton ProfileManager, creando una instancia si aún no existe."""
    global _singleton
    if _singleton is None:
        _singleton = ProfileManager()
    return _singleton
