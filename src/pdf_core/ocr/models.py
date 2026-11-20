"""Dónde están los modelos del OCR y cómo descargarlos si no se instalaron.

El instalador puede llevar los modelos (``assets/ocr_models``, junto a la app) o no: entonces se
descargan la primera vez que hacen falta a la carpeta del usuario (:data:`USER_DIR`), desde el
repositorio de PaddlePaddle en Hugging Face, en la versión fijada y comprobando su suma SHA-256. Son
los mismos archivos que van en el instalador (ver ``assets/ocr_models/README.md``).

Los diccionarios del reconocedor (``*_dict.txt``) son pequeños y van siempre con la app.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "assets" / "ocr_models"
USER_DIR = Path.home() / ".pdf_manager" / "ocr_models"

_CHUNK = 256 * 1024
_TIMEOUT_S = 60


@dataclass(frozen=True)
class Model:
    name: str
    repo: str  # PaddlePaddle/<repo> en Hugging Face
    revision: str  # commit fijado: el archivo no cambia aunque el repositorio se actualice
    sha256: str
    size: int

    @property
    def url(self) -> str:
        return f"https://huggingface.co/PaddlePaddle/{self.repo}/resolve/{self.revision}/inference.onnx"


MODELS = {
    m.name: m
    for m in (
        Model("PP-OCRv6_small_det", "PP-OCRv6_small_det_onnx", "28fe5895c24fd108c19eb3e8479f4ab385fbfc62",
              "d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e", 9_880_512),
        Model("PP-OCRv6_small_rec", "PP-OCRv6_small_rec_onnx", "b8f84f0b80c529de40b4fbb3544b84fa7233a513",
              "5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634", 21_159_378),
        Model("PP-LCNet_x1_0_doc_ori", "PP-LCNet_x1_0_doc_ori_onnx", "7330ab7039123e46af2dc03154b9969aa412c61d",
              "af9a0a4f317ff0709ce752067807f819cb15d883f8ecad89f28df1c6ee2d9c92", 6_788_069),
    )
}


class DownloadError(Exception):
    """No se pudo descargar un modelo (sin conexión, servidor caído o archivo distinto)."""


def model_file(name: str) -> Path:
    """El ``.onnx`` de ``name``: el instalado con la app o, si no está, el de la carpeta del usuario."""
    bundled = BUNDLED_DIR / f"{name}.onnx"
    return bundled if bundled.is_file() else USER_DIR / f"{name}.onnx"


def missing(names: list[str] | None = None) -> list[Model]:
    """Los modelos (de ``names``; todos si es ``None``) que no están ni con la app ni descargados."""
    wanted = names if names is not None else list(MODELS)
    return [MODELS[n] for n in wanted if n in MODELS and not model_file(n).is_file()]


def download(models: list[Model], progress: Callable[[int, int], None] | None = None,
             opener: Callable[..., object] = urllib.request.urlopen) -> None:
    """Descarga ``models`` a :data:`USER_DIR`; ``progress(recibido, total)`` en bytes de todos.

    Cada archivo se escribe aparte (``.part``) y solo se deja con su nombre si su suma coincide:
    una descarga cortada o un archivo cambiado nunca llega a usarse.
    """
    total = sum(m.size for m in models)
    received = 0
    USER_DIR.mkdir(parents=True, exist_ok=True)
    for model in models:
        target = USER_DIR / f"{model.name}.onnx"
        part = target.with_suffix(".part")
        digest = hashlib.sha256()
        try:
            with opener(model.url, timeout=_TIMEOUT_S) as response, part.open("wb") as out:
                while chunk := response.read(_CHUNK):
                    out.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress:
                        progress(min(received, total), total)
        except OSError as ex:  # URLError, timeout, disco lleno…
            part.unlink(missing_ok=True)
            raise DownloadError(f"No se pudo descargar {model.name}: {ex}") from ex
        if digest.hexdigest() != model.sha256:
            part.unlink(missing_ok=True)
            raise DownloadError(f"El archivo descargado de {model.name} no es el esperado")
        os.replace(part, target)
