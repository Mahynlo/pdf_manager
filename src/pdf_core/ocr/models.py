"""Dónde están los modelos del OCR y cómo descargarlos si no se instalaron.

El instalador puede llevar los modelos (``assets/ocr_models``, junto a la app) o no: entonces se
descargan la primera vez que hacen falta a la carpeta del usuario (:data:`USER_DIR`). De dónde, lo
dice quien llama (``sources``: la app usa la Release de su versión en GitHub y, de respaldo, la misma
carpeta del repositorio en esa etiqueta). Cada archivo se comprueba con su suma SHA-256: tiene que
ser el mismo que lleva el instalador.

Los diccionarios del reconocedor (``*_dict.txt``) son pequeños y van siempre con la app.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "assets" / "ocr_models"
USER_DIR = Path.home() / ".pdf_manager" / "ocr_models"

_CHUNK = 256 * 1024
_TIMEOUT_S = 60


@dataclass(frozen=True)
class Model:
    name: str  # el archivo es «<name>.onnx»
    sha256: str
    size: int


# Los de assets/ocr_models (una prueba comprueba que coinciden): al cambiar uno allí, cambiarlo aquí.
MODELS = {
    m.name: m
    for m in (
        Model("PP-OCRv6_small_det", "d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e", 9_880_512),
        Model("PP-OCRv6_small_rec", "5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634", 21_159_378),
        Model("PP-LCNet_x1_0_doc_ori", "af9a0a4f317ff0709ce752067807f819cb15d883f8ecad89f28df1c6ee2d9c92", 6_788_069),
    )
}


class DownloadError(Exception):
    """No se pudo descargar un modelo de ningún origen (sin conexión, no está o es distinto)."""


def model_file(name: str) -> Path:
    """El ``.onnx`` de ``name``: el instalado con la app o, si no está, el de la carpeta del usuario."""
    bundled = BUNDLED_DIR / f"{name}.onnx"
    return bundled if bundled.is_file() else USER_DIR / f"{name}.onnx"


def missing(names: list[str] | None = None) -> list[Model]:
    """Los modelos (de ``names``; todos si es ``None``) que no están ni con la app ni descargados."""
    wanted = names if names is not None else list(MODELS)
    return [MODELS[n] for n in wanted if n in MODELS and not model_file(n).is_file()]


def download(models: list[Model], sources: Sequence[str], progress: Callable[[int, int], None] | None = None,
             opener: Callable[..., object] = urllib.request.urlopen) -> None:
    """Descarga ``models`` a :data:`USER_DIR`; ``progress(recibido, total)`` en bytes de todos.

    ``sources``: direcciones con ``{name}`` (``https://…/{name}.onnx``), por orden de preferencia; si
    una falla, se prueba la siguiente. Cada archivo se escribe aparte (``.part``) y solo se deja con
    su nombre si su suma coincide: una descarga cortada o un archivo distinto nunca llega a usarse.
    """
    if not sources:
        raise DownloadError("No hay de dónde descargar los modelos de OCR")
    total = sum(m.size for m in models)
    done = 0
    USER_DIR.mkdir(parents=True, exist_ok=True)
    for model in models:
        failures = []
        for source in sources:
            try:
                _fetch(model, source.format(name=model.name), opener,
                       lambda got, done=done: progress and progress(min(done + got, total), total))
                break
            except DownloadError as ex:
                failures.append(str(ex))
        else:
            raise DownloadError("; ".join(failures))
        done += model.size


def _fetch(model: Model, url: str, opener: Callable[..., object], progress: Callable[[int], object]) -> None:
    target = USER_DIR / f"{model.name}.onnx"
    part = target.with_suffix(".part")
    digest = hashlib.sha256()
    received = 0
    try:
        with opener(url, timeout=_TIMEOUT_S) as response, part.open("wb") as out:
            while chunk := response.read(_CHUNK):
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                progress(received)
    except OSError as ex:  # URLError/HTTPError (404…), timeout, disco lleno…
        part.unlink(missing_ok=True)
        raise DownloadError(f"{model.name} desde {url}: {ex}") from ex
    if digest.hexdigest() != model.sha256:
        part.unlink(missing_ok=True)
        raise DownloadError(f"{model.name} desde {url}: el archivo no es el esperado")
    os.replace(part, target)
