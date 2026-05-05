import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import webview

APP_ROOT = Path(__file__).resolve().parent
VITE_DIR = APP_ROOT / "visor_pdf"
DIST_INDEX = VITE_DIR / "dist" / "index.html"
VITE_HOST = "127.0.0.1"
VITE_PORT = 5173
VITE_URL = f"http://{VITE_HOST}:{VITE_PORT}"


def _wait_for_port(host: str, port: int, timeout_s: float = 20.0) -> bool:
	deadline = time.time() + timeout_s
	while time.time() < deadline:
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
			sock.settimeout(0.5)
			if sock.connect_ex((host, port)) == 0:
				return True
		time.sleep(0.2)
	return False


def _start_vite() -> subprocess.Popen:
	if not VITE_DIR.exists():
		raise FileNotFoundError(f"No existe {VITE_DIR}")
	command = [
		"npm",
		"run",
		"dev",
		"--",
		"--host",
		VITE_HOST,
		"--port",
		str(VITE_PORT),
	]
	return subprocess.Popen(
		command,
		cwd=str(VITE_DIR),
		env=os.environ.copy(),
	)


def _stop_process(proc: subprocess.Popen | None) -> None:
	if not proc or proc.poll() is not None:
		return
	try:
		proc.send_signal(signal.SIGTERM)
		proc.wait(timeout=5)
	except Exception:
		proc.kill()


def _open_window(url: str) -> None:
	webview.create_window(
		title="PDF Manager Viewer",
		url=url,
		width=1200,
		height=800,
	)
	webview.start(gui="qt", debug=False, http_server=False)


def run_dev() -> None:
	vite_proc = _start_vite()
	atexit.register(_stop_process, vite_proc)

	if not _wait_for_port(VITE_HOST, VITE_PORT, timeout_s=25.0):
		_stop_process(vite_proc)
		print("Vite no inicio a tiempo.")
		sys.exit(1)

	_open_window(VITE_URL)


def run_prod() -> None:
	if not DIST_INDEX.exists():
		print(f"Error: No se encontro {DIST_INDEX}")
		print("Ejecuta 'npm run build' en src/visor_pdf.")
		sys.exit(1)
	_open_window(str(DIST_INDEX))


def main() -> None:
	mode = os.environ.get("APP_MODE", "dev").lower()
	if len(sys.argv) > 1:
		mode = sys.argv[1].lower().lstrip("-")

	if mode in {"prod", "production"}:
		run_prod()
	else:
		run_dev()


if __name__ == "__main__":
	main()
