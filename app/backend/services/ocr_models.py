"""Los modelos del OCR en el escritorio: si el instalador no los llevaba, se descargan la primera vez.

Lo usan los servicios que reconocen texto (``ocr`` y ``extract``) antes de cargar los modelos. La
descarga avisa a la ventana con el evento :data:`OCR_DOWNLOAD` (``{"percent": n}``, al final
``{"done": true}`` o ``{"failed": true}``), que la muestra en la barra de estado.

De dónde (:data:`SOURCES`), siempre del repositorio y de la versión de la app:
1. la Release de esta versión en GitHub, donde el workflow ``build-web.yml`` sube los modelos de
   ``src/assets/ocr_models`` junto al instalador;
2. de respaldo, esa misma carpeta del repositorio en la etiqueta de esta versión.

En el navegador no se usa: los modelos los sirve la propia web (``app/browser/onnx.py``).
"""

from __future__ import annotations

import logging
import threading

from app import APP_VERSION, GITHUB_REPO
from app.backend.host import Host
from app.backend.rpc import UserError
from pdf_core.ocr import models

log = logging.getLogger(__name__)

OCR_DOWNLOAD = "ocr:download"
_TAG = f"v{APP_VERSION}"
SOURCES = (
    f"https://github.com/{GITHUB_REPO}/releases/download/{_TAG}/{{name}}.onnx",
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{_TAG}/src/assets/ocr_models/{{name}}.onnx",
)


class OcrModels:
    def __init__(self, host: Host) -> None:
        self._host = host
        self._lock = threading.Lock()  # una sola descarga aunque lo pidan el visor y Extraer a la vez

    def ensure(self) -> None:
        """Deja los modelos listos: si falta alguno, lo descarga (y espera). ``UserError`` si no se puede."""
        with self._lock:
            todo = models.missing()
            if not todo:
                return
            log.info("Descargando modelos de OCR: %s", ", ".join(m.name for m in todo))
            last = -1

            def progress(received: int, total: int) -> None:
                nonlocal last
                percent = received * 100 // total
                if percent != last:
                    last = percent
                    self._host.emit(OCR_DOWNLOAD, {"percent": percent})

            self._host.emit(OCR_DOWNLOAD, {"percent": 0, "megabytes": round(sum(m.size for m in todo) / 1e6)})
            try:
                models.download(todo, SOURCES, progress)
            except models.DownloadError as ex:
                log.warning("%s", ex)
                self._host.emit(OCR_DOWNLOAD, {"failed": True})
                raise UserError(
                    "No se pudieron descargar los modelos de OCR. Comprueba la conexión a internet e "
                    "inténtalo de nuevo.", "ocr_download") from ex
            self._host.emit(OCR_DOWNLOAD, {"done": True})
