#!/usr/bin/env python3
"""
IG-Scraper Pro - versao desktop (Windows/Mac/Linux)

Abre o app numa janela propria (sem terminal, sem precisar abrir o
navegador manualmente). E o ponto de entrada usado pelo build do
PyInstaller -- veja packaging/windows/.
"""
import os
import sys
import socket
import threading
import time


def _data_dir():
    """Pasta gravavel do usuario pra guardar contas, sessoes, banco e
    downloads. Nunca a pasta de instalacao (Program Files nao e gravavel
    sem admin)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "IGScraperPro")
    os.makedirs(path, exist_ok=True)
    return path


# precisa ser definido ANTES de importar app.py, que le essa variavel
# na hora de montar os caminhos de downloads/sessions/db/etc
os.environ["IGSCRAPER_DATA_DIR"] = _data_dir()

import app as flask_app_module  # noqa: E402


def _free_port(preferred=5000):
    """Usa 5000 se estiver livre; senao acha outra porta livre (evita
    conflito se outra instancia ou outro programa ja estiver usando)."""
    candidates = [preferred] + list(range(5050, 5090))
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


def _wait_server_ready(port, timeout=10):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    import webview

    flask_app_module.init_db()
    flask_app_module.init_files()
    flask_app_module._sync_auto_mode()  # religa o agendamento se estava ligado

    port = _free_port()

    def run_server():
        flask_app_module.app.run(
            host="127.0.0.1", port=port, debug=False,
            use_reloader=False, threaded=True,
        )

    threading.Thread(target=run_server, daemon=True).start()
    _wait_server_ready(port)

    webview.create_window(
        "IG-Scraper Pro",
        f"http://127.0.0.1:{port}/",
        width=480, height=880, min_size=(380, 640),
    )
    webview.start()


if __name__ == "__main__":
    main()
