from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import webbrowser


@dataclass(frozen=True)
class WindowConfig:
    title: str
    width: int
    height: int
    icon: Path | None = None
    min_width: int | None = None
    min_height: int | None = None


@dataclass(frozen=True)
class AppConfig:
    window: WindowConfig


def load_config(app_root: Path) -> AppConfig:
    title = os.environ.get("APP_TITLE", "PDF Manager Viewer")
    width = int(os.environ.get("APP_WIDTH", "1200"))
    height = int(os.environ.get("APP_HEIGHT", "800"))
    icon_env = os.environ.get("APP_ICON")
    if icon_env:
        icon = Path(icon_env)
    else:
        if sys.platform.startswith("win"):
            default_icon = app_root / "assets" / "icon.ico"
        else:
            default_icon = app_root / "assets" / "icon.png"
        icon = default_icon if default_icon.exists() else None

    return AppConfig(
        window=WindowConfig(
            title=title,
            width=width,
            height=height,
            icon=icon,
        )
    )


class OSActions:
    @staticmethod
    def open_path(path: Path) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
            return
        subprocess.run(["xdg-open", str(path)], check=False)

    @staticmethod
    def reveal_in_folder(path: Path) -> None:
        if sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(path)], check=False)
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
            return
        subprocess.run(["xdg-open", str(path.parent)], check=False)

    @staticmethod
    def open_url(url: str) -> None:
        webbrowser.open(url)
