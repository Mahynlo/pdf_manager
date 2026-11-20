"""Servicios del backend. Cada uno se registra con un nombre (``app``, ``merge``…) en
:func:`build_registry`; el frontend los invoca como ``"nombre.metodo"``."""

from __future__ import annotations

from app.backend.host import Host
from app.backend.rpc import Registry
from app.backend.services.ai import AiService
from app.backend.services.app_service import AppService
from app.backend.services.documents import DocumentService
from app.backend.services.extract import ExtractService
from app.backend.services.help import HelpService
from app.backend.services.legends import LegendsService
from app.backend.services.merge import MergeService
from app.backend.services.ocr import OcrService
from app.backend.services.ocr_models import OcrModels
from app.backend.services.redact import RedactService
from app.backend.services.security import SecurityService
from app.backend.services.stamps import StampsService
from app.backend.services.viewer import ViewerService
from app.backend.settings import Settings


def build_registry(host: Host, settings: Settings, download_ocr_models: bool = True) -> tuple[Registry, dict[str, object]]:
    """Crea los servicios y los registra; devuelve también los servicios por nombre (para cerrarlos al salir).

    ``download_ocr_models``: si faltan los modelos del OCR, se descargan al usarlo (escritorio; en
    el navegador los sirve la web).
    """
    documents = DocumentService(host)
    viewer = ViewerService(host)
    ocr_models = OcrModels(host) if download_ocr_models else None
    services: dict[str, object] = {
        "ai": AiService(viewer),
        "app": AppService(host, settings),
        "documents": documents,
        "extract": ExtractService(host, documents, models=ocr_models),
        "help": HelpService(),
        "legends": LegendsService(),
        "merge": MergeService(host, documents),
        "ocr": OcrService(host, viewer, models=ocr_models),
        "redact": RedactService(viewer),
        "security": SecurityService(host, documents),
        "stamps": StampsService(),
        "viewer": viewer,
    }
    registry = Registry()
    for name, service in services.items():
        registry.register(name, service)
    return registry, services


def quit_warnings(services: dict[str, object]) -> dict | None:
    """Lo que se perdería al cerrar la ventana: documentos sin guardar y trabajos en curso.
    ``None`` si se puede salir sin preguntar; si no, los datos del aviso del frontend."""
    documents = services["viewer"].unsaved_documents()
    jobs = ["Extracción de páginas"] if services["extract"].running else []
    return {"documents": documents, "jobs": jobs} if documents or jobs else None
