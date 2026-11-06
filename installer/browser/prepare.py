"""Deja en ``app/ui/public-web`` lo que la versión de navegador carga al arrancar.

- ``pyodide/``: Python en wasm (del paquete ``pyodide`` de ``app/ui``) y los wheels que usa el
  backend, comprobados contra su suma. Todo se sirve desde la misma web: sin CDN en tiempo de uso.
- ``onnx/``, ``ocr_models/``: onnxruntime-web y los modelos del OCR (se bajan al usar el OCR).
- ``backend.zip``: ``app/backend``, ``app/browser``, ``src/pdf_core`` y el manual.

Lo llama ``pnpm build:web``. Lo descargado se conserva entre compilaciones (no entra en git).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "app" / "ui"
OUT = UI / "public-web"
PYODIDE = UI / "node_modules" / "pyodide"
CORE = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json")
PYPI = ("pypdfium2", "markdown-it-py", "mdurl")  # no van con Pyodide: se bajan de PyPI
PYODIDE_PACKAGES = ("numpy",)  # van con Pyodide: se bajan de su CDN

ONNX = UI / "node_modules" / "onnxruntime-web" / "dist"
ONNX_FILES = ("ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm")
MODELS = ROOT / "src" / "assets" / "ocr_models"

SOURCES = ("app/__init__.py", "app/backend", "app/browser", "src/pdf_core")
ASSETS = ("src/assets/ayuda", "src/assets/ayuda_img", "src/assets/ayuda_svg")


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _save_checked(target: Path, url: str, sha256: str) -> None:
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
        return
    data = _get(url)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"La suma de {target.name} no coincide")
    target.write_bytes(data)
    print("descargado", target.name, flush=True)


def _locked_version(name: str) -> str:
    """Versión de ``name`` en ``uv.lock`` (la misma que en el escritorio)."""
    match = re.search(rf'name = "{name}"\nversion = "([^"]+)"', (ROOT / "uv.lock").read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"{name} no está en uv.lock")
    return match.group(1)


def _pypi_wheel(name: str, abi: str) -> dict:
    """El wheel de ``name`` para Pyodide (o el puro), en la versión de ``uv.lock``."""
    version = _locked_version(name)
    files = json.loads(_get(f"https://pypi.org/pypi/{name}/{version}/json"))["urls"]
    wheels = [f for f in files if f["filename"].endswith(".whl")]
    found = [f for f in wheels if f"pyemscripten_{abi}_wasm32" in f["filename"] or f["filename"].endswith("none-any.whl")]
    if not found:
        raise SystemExit(f"{name} {version} no tiene wheel para Pyodide (ABI {abi})")
    return found[0]


def core() -> dict:
    target = OUT / "pyodide"
    target.mkdir(parents=True, exist_ok=True)
    for name in CORE:
        shutil.copyfile(PYODIDE / name, target / name)
    lock = json.loads((PYODIDE / "pyodide-lock.json").read_text(encoding="utf-8"))
    version = json.loads((PYODIDE / "package.json").read_text(encoding="utf-8"))["version"]
    for name in PYODIDE_PACKAGES:
        package = lock["packages"][name]
        file = package["file_name"]
        _save_checked(target / file, f"https://cdn.jsdelivr.net/pyodide/v{version}/full/{file}", package["sha256"])
    return lock


def wheels(lock: dict) -> list[str]:
    target = OUT / "pyodide"
    names = []
    for name in PYPI:
        wheel = _pypi_wheel(name, lock["info"]["abi_version"])
        _save_checked(target / wheel["filename"], wheel["url"], wheel["digests"]["sha256"])
        names.append(wheel["filename"])
    return names


def ocr() -> None:
    for folder, files in (("onnx", [ONNX / name for name in ONNX_FILES]), ("ocr_models", MODELS.glob("*.onnx"))):
        (OUT / folder).mkdir(exist_ok=True)
        for file in files:
            shutil.copyfile(file, OUT / folder / file.name)


def backend() -> None:
    with zipfile.ZipFile(OUT / "backend.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in (*SOURCES, *ASSETS):
            path = ROOT / entry
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for file in files:
                if "__pycache__" not in file.parts:
                    archive.write(file, file.relative_to(ROOT).as_posix())
        for file in MODELS.glob("*.txt"):  # los diccionarios: los modelos van aparte
            archive.write(file, file.relative_to(ROOT).as_posix())


def main() -> int:
    if not PYODIDE.is_dir():
        raise SystemExit("Falta el paquete pyodide: ejecuta «pnpm install» en app/ui")
    lock = core()
    manifest = {"packages": list(PYODIDE_PACKAGES), "wheels": wheels(lock)}
    ocr()
    backend()
    (OUT / "backend.json").write_text(json.dumps(manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
