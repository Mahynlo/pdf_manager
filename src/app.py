import atexit
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

import webview

from app_config import load_config

APP_ROOT = Path(__file__).resolve().parent
VITE_DIR = APP_ROOT / "visor_pdf"
DIST_INDEX = VITE_DIR / "dist" / "index.html"
VITE_HOST = "127.0.0.1"
VITE_PORT = 5173


def _is_port_open(host: str, port: int) -> bool:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.settimeout(0.5)
		return sock.connect_ex((host, port)) == 0


def _pick_port(host: str, start_port: int, limit: int = 10) -> int:
	for offset in range(limit):
		port = start_port + offset
		if not _is_port_open(host, port):
			return port
	raise RuntimeError("No hay puertos libres para Vite.")


def _start_vite(port: int) -> subprocess.Popen:
	if not VITE_DIR.exists():
		raise FileNotFoundError(f"No existe {VITE_DIR}")
	npm_path = shutil.which("npm")
	if not npm_path:
		raise FileNotFoundError("No se encontro 'npm' en PATH. Instala Node.js y reinicia la terminal.")
	command = [
		npm_path,
		"run",
		"dev",
		"--",
		"--host",
		VITE_HOST,
		"--port",
		str(port),
	]
	popen_kwargs = {
		"cwd": str(VITE_DIR),
		"env": os.environ.copy(),
	}
	if sys.platform.startswith("win"):
		popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
		popen_kwargs["stdin"] = subprocess.DEVNULL
	return subprocess.Popen(command, **popen_kwargs)


def _stop_process(proc: subprocess.Popen | None) -> None:
	if not proc or proc.poll() is not None:
		return
	try:
		if sys.platform.startswith("win"):
			subprocess.run(
				["taskkill", "/PID", str(proc.pid), "/T", "/F"],
				check=False,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
		else:
			proc.send_signal(signal.SIGTERM)
		proc.wait(timeout=5)
	except Exception:
		proc.kill()


def _open_window(url: str, config, on_close=None) -> None:
	kwargs = {
		"title": config.window.title,
		"url": url,
		"width": config.window.width,
		"height": config.window.height,
	}
	if config.window.icon:
		kwargs["icon"] = str(config.window.icon)
	try:
		window = webview.create_window(**kwargs)
	except TypeError:
		kwargs.pop("icon", None)
		window = webview.create_window(**kwargs)
	if on_close is not None:
		window.events.closed += lambda: on_close()
	gui = os.environ.get("APP_GUI")
	start_kwargs = {"debug": False, "http_server": False}
	if gui:
		start_kwargs["gui"] = gui
	if config.window.icon:
		start_kwargs["icon"] = str(config.window.icon)
	webview.start(**start_kwargs)


def run_dev(config) -> None:
	port = _pick_port(VITE_HOST, VITE_PORT)
	vite_proc = _start_vite(port)
	atexit.register(_stop_process, vite_proc)

	vite_url = f"http://{VITE_HOST}:{port}"
	try:
		_open_window(vite_url, config)
	finally:
		_stop_process(vite_proc)


def run_prod(config) -> None:
	if not DIST_INDEX.exists():
		print(f"Error: No se encontro {DIST_INDEX}")
		print("Ejecuta 'npm run build' en src/visor_pdf.")
		sys.exit(1)
	_open_window(str(DIST_INDEX), config)


def main() -> None:
	config = load_config(APP_ROOT)
	mode = os.environ.get("APP_MODE", "dev").lower()
	if len(sys.argv) > 1:
		mode = sys.argv[1].lower().lstrip("-")

	if mode in {"prod", "production"}:
		run_prod(config)
	else:
		run_dev(config)


if __name__ == "__main__":
	main()
