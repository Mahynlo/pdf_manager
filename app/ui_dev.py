"""Compilar y servir la interfaz (``app/ui``) desde la propia app, sin llamar a pnpm a mano.

- ``ensure_built()``: antes de abrir la ventana, compila la interfaz (``pnpm build``) si
  falta la compilación o algún archivo cambió después de ella.
- ``start_dev_server()``: para ``--dev``, arranca ``pnpm dev`` (o usa el que ya esté en
  marcha), espera a que responda y lo detiene al cerrar la app.

En el ejecutable empaquetado no hay fuentes (``app/ui/src``): solo se usa la compilación.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from app import UI_DIR

log = logging.getLogger(__name__)

DEV_SERVER_URL = "http://localhost:5173"  # el puerto fijo de vite.config.js
DEV_SERVER_WAIT = 60.0  # s: la primera vez Vite optimiza las dependencias
# Lo que entra en la compilación, además de src/.
_CONFIG_FILES = ("index.html", "package.json", "pnpm-lock.yaml", "vite.config.js", "svelte.config.js")


def responds(url: str, timeout: float = 3.0) -> bool:
    """Si el servidor contesta (sin pasar por el proxy del sistema)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def _newest_source(ui_dir: Path) -> float:
    paths = [*(ui_dir / name for name in _CONFIG_FILES), ui_dir / "src"]
    newest = 0.0
    for path in paths:
        files = path.rglob("*") if path.is_dir() else [path]
        newest = max([newest, *(f.stat().st_mtime for f in files if f.is_file())])
    return newest


def needs_build(ui_dir: Path = UI_DIR) -> bool:
    """La compilación falta o es más antigua que alguna fuente (en el ejecutable, nunca)."""
    if not (ui_dir / "src").is_dir():
        return False
    index = ui_dir / "dist" / "index.html"
    return not index.is_file() or _newest_source(ui_dir) > index.stat().st_mtime


def _pnpm(*args: str) -> None:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("Hace falta pnpm para compilar la interfaz (https://pnpm.io/installation)")
    if not (UI_DIR / "node_modules").is_dir():
        print("Instalando las dependencias de la interfaz (pnpm install)…", flush=True)
        if subprocess.run([pnpm, "install"], cwd=UI_DIR).returncode:
            raise SystemExit("No se pudieron instalar las dependencias de la interfaz (pnpm install en app/ui)")
    if args and subprocess.run([pnpm, *args], cwd=UI_DIR).returncode:
        raise SystemExit(f"Falló «pnpm {' '.join(args)}» en app/ui")


def ensure_built() -> None:
    """Compila la interfaz si hace falta (la primera vez, o tras cambiarla)."""
    if not needs_build():
        return
    print("Compilando la interfaz (pnpm build)…", flush=True)
    log.info("La interfaz cambió: se compila")
    _pnpm("build")


def _stop(process: subprocess.Popen) -> None:
    """Detiene pnpm y el Vite que lanzó (en Windows, todo el árbol de procesos)."""
    if process.poll() is not None:
        return
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)


def start_dev_server(url: str = DEV_SERVER_URL) -> str:
    """Arranca ``pnpm dev`` si no está ya en marcha y devuelve su URL cuando responde."""
    if responds(url):
        log.info("Se usa el servidor de Vite que ya estaba en marcha (%s)", url)
        return url
    _pnpm()  # dependencias, si faltan
    print("Arrancando el servidor de la interfaz (pnpm dev)…", flush=True)
    process = subprocess.Popen([shutil.which("pnpm"), "dev"], cwd=UI_DIR)
    atexit.register(_stop, process)  # se detiene al cerrar la app (también si falla al arrancar)
    deadline = time.monotonic() + DEV_SERVER_WAIT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit("«pnpm dev» terminó al arrancar: revisa el mensaje de arriba")
        if responds(url, timeout=1.0):
            return url
        time.sleep(0.3)
    raise SystemExit(f"El servidor de la interfaz no respondió en {url} tras {DEV_SERVER_WAIT:.0f} s")
