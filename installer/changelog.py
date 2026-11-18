"""El CHANGELOG de cada versión, a partir de los commits. Ver docs/web/versiones.md.

    uv run python installer/changelog.py preview      lo que entraría en la próxima versión
    uv run python installer/changelog.py add          añade a CHANGELOG.md la sección de APP_VERSION
    uv run python installer/changelog.py notes        esa sección, para la Release de GitHub

``add`` y ``notes`` admiten la versión como argumento (``0.1.30-web``); sin él, es ``APP_VERSION``
de ``app/__init__.py``. Los commits los agrupa git-cliff (``cliff.toml``); las secciones ya escritas
no se tocan, así que se pueden retocar a mano antes de publicar.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
TITLE = "# Changelog"
GIT_CLIFF = "git-cliff@2.14.2"  # versión fija: la salida no cambia sin que lo decidamos


def app_version(root: Path = ROOT) -> str:
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', (root / "app" / "__init__.py").read_text(encoding="utf-8"), re.M)
    if match is None:
        raise SystemExit("No se encontró APP_VERSION en app/__init__.py")
    return match.group(1)


def section(text: str, version: str) -> str | None:
    """La sección ``## [version]`` de un changelog, sin su título; ``None`` si no está."""
    lines = text.replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith(f"## [{version}]")), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
    return "\n".join(lines[start + 1:end]).strip()


def insert(text: str, new: str) -> str:
    """``text`` con la sección ``new`` justo debajo del título, encima de las anteriores."""
    body = text.replace("\r\n", "\n")
    rest = body[len(TITLE):] if body.startswith(TITLE) else body
    return f"{TITLE}\n\n{new.strip()}\n\n{rest.lstrip()}"


def generate(tag: str | None) -> str:
    """Los commits desde la última etiqueta, agrupados (git-cliff). Con ``tag``, como esa versión."""
    command = ["uvx", GIT_CLIFF, "--unreleased", "--strip", "header"]
    if tag:
        command += ["--tag", tag]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8", check=False)
    if done.returncode:
        raise SystemExit(f"git-cliff falló:\n{done.stderr}")
    return done.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("command", choices=("preview", "add", "notes"))
    parser.add_argument("version", nargs="?", help="p. ej. 0.1.30-web (por defecto, APP_VERSION)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # la consola de Windows no es UTF-8

    if args.command == "preview":
        print(generate(None) or "No hay commits desde la última etiqueta.")
        return 0

    version = (args.version or app_version()).removeprefix("v")
    text = CHANGELOG.read_text(encoding="utf-8")
    found = section(text, version)
    if args.command == "notes":
        if not found:
            raise SystemExit(f"CHANGELOG.md no tiene la sección [{version}]: "
                             "ejecuta «uv run python installer/changelog.py add» y súbela antes de etiquetar")
        print(found)
        return 0

    if found is not None:
        raise SystemExit(f"CHANGELOG.md ya tiene la sección [{version}]: edítala a mano, o cambia APP_VERSION")
    new = generate(f"v{version}")
    if not section(new, version):
        raise SystemExit("No hay commits desde la última etiqueta: nada que añadir")
    CHANGELOG.write_text(insert(text, new), encoding="utf-8", newline="\n")
    print(f"Añadida la sección [{version}] a CHANGELOG.md. Revísala antes de subirla.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
