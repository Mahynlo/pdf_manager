"""PDF Manager con interfaz en Svelte (pywebview + WebView2) y backend Python.

- ``app/backend``: lógica sin interfaz (servicios expuestos al frontend). No importa
  Qt ni pywebview, así se prueba sin ventana y se podrá reutilizar en la versión web.
- ``app/ui``: la interfaz, en Svelte; compila a ``app/ui/dist`` (``pnpm build``).
  Ver ``docs/web/svelte.md``.
- ``app/host.py`` / ``app/main.py``: la ventana pywebview que une ambos.

La lógica de PDF está en ``src/pdf_core`` (lo único de ``src/`` que importa la app).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Versión de la app web (la del instalador). Va aparte de pyproject.toml, que lleva la de
# Flet (0.1.28) y solo admite versiones PEP 440: «-web» marca la versión de prueba.
APP_VERSION = "0.1.29-web"

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
SRC_DIR: Path = PROJECT_ROOT / "src"
UI_DIR: Path = Path(__file__).resolve().parent / "ui"  # la interfaz (fuentes en src/)
UI_DIST_DIR: Path = UI_DIR / "dist"  # su compilación, que abre la ventana
DATA_DIR: Path = Path.home() / ".pdf_manager"  # preferencias, registro y datos de WebView2
LOG_FILE: Path = DATA_DIR / "app.log"

# ``pdf_core`` está en ``src/`` (compartido con Flet mientras siga en producción).
for _p in (str(PROJECT_ROOT), str(SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
