"""Arranque de PDF Manager.

    uv run python -m app.main            # la app (compila la interfaz si cambió)
    uv run python -m app.main --dev      # con recarga al guardar: arranca también «pnpm dev»
    uv run python -m app.main --debug    # con herramientas de desarrollo (F12)
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

# Permite ejecutar este archivo directamente (python app/main.py).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import webview  # noqa: E402

from app import DATA_DIR, LOG_FILE, UI_DIST_DIR, ui_dev  # noqa: E402
from app.backend.rpc import Api  # noqa: E402
from app.backend.services import build_registry, quit_warnings  # noqa: E402
from app.backend.settings import Settings  # noqa: E402
from app.host import WebviewHost  # noqa: E402
from app.single_instance import SingleInstance  # noqa: E402
from app.webview_cache import discard_stale_cache  # noqa: E402
from pdf_core.launch_args import collect_pdf_paths  # noqa: E402

SHOW_FALLBACK_SECONDS = 3.0  # si el frontend falla al arrancar, la ventana se muestra igual


def _setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
    )


def frontend_url(dev_server: str | None, storage: Path) -> str:
    """URL de la interfaz que abre la ventana: la compilación de ``app/ui`` o, con
    ``dev_server``, el servidor de Vite (``pnpm dev``), con recarga al guardar."""
    if dev_server:
        if not ui_dev.responds(dev_server):
            raise SystemExit(f"No responde el servidor de la interfaz en {dev_server}: "
                             "usa --dev para que la app lo arranque, o «pnpm dev» en app/ui")
        return dev_server
    index = UI_DIST_DIR / "index.html"
    if not index.is_file():
        raise SystemExit(f"No existe {index}: compila la interfaz con «pnpm build» en app/ui")
    discard_stale_cache(UI_DIST_DIR, storage)  # que WebView2 no use módulos JS de una versión anterior
    return str(index)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF Manager")
    parser.add_argument("--debug", action="store_true", help="abre las herramientas de desarrollo")
    parser.add_argument("--dev", action="store_true",
                        help="recarga al guardar: arranca «pnpm dev» (o usa el que ya esté en marcha) y lo cierra al salir")
    parser.add_argument("--dev-server", metavar="URL",
                        help="abre la interfaz desde un servidor de Vite ya arrancado (p. ej. http://localhost:5173)")
    args, _rest = parser.parse_known_args(argv)  # el resto son los PDF de «Abrir con»
    _setup_logging()
    log = logging.getLogger("app.main")
    incoming = collect_pdf_paths([sys.argv[0], *(sys.argv[1:] if argv is None else argv)])
    instance = SingleInstance()
    if not instance.acquire(incoming):
        log.info("Ya hay una ventana abierta: se le enviaron %d PDF", len(incoming))
        return 0
    storage = DATA_DIR / "webview"
    if args.dev:
        args.dev_server = ui_dev.start_dev_server()
    elif not args.dev_server:
        ui_dev.ensure_built()
    url = frontend_url(args.dev_server, storage)

    settings = Settings()
    host = WebviewHost()
    registry, services = build_registry(host, settings)
    window = webview.create_window(
        "Extraer PDFs",
        url=url,
        js_api=Api(registry),
        width=1280,
        height=820,
        min_size=(960, 640),
        hidden=True,  # se muestra cuando el frontend ya aplicó el tema (app.ready)
    )
    documents = services["documents"]

    def _open_dropped(paths: list[str]) -> None:
        """PDFs arrastrados desde el Explorador: se abren como con «Abrir PDF»."""
        for path in paths:
            documents.open(path)

    # Con cambios sin guardar o trabajos en curso, el frontend pregunta antes de salir (y llama a ``app.quit``).
    host.attach(window, lambda: quit_warnings(services), _open_dropped)

    def _open_from_other_instance(paths: list[str]) -> None:
        """«Abrir con» (u otro lanzamiento) con la app ya abierta."""
        for path in paths:
            documents.open(path)
        host.bring_to_front()

    instance.listen(_open_from_other_instance)
    # Los PDF del arranque se abren cuando el frontend ya escucha.
    services["app"].when_ready(lambda: _open_dropped(incoming))

    def _show_fallback() -> None:
        try:
            host.show()
        except Exception:  # la ventana ya se cerró
            pass

    window.events.loaded += lambda: threading.Timer(SHOW_FALLBACK_SECONDS, _show_fallback).start()

    def _close_services() -> None:
        for service in services.values():
            close = getattr(service, "close", None)
            if close is not None:
                close()

    window.events.closed += _close_services
    window.events.closed += host.close
    window.events.closed += instance.close
    webview.start(http_server=True, private_mode=False, storage_path=str(storage), debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
