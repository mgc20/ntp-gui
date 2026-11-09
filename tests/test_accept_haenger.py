"""Kein blockierendes accept(): Bricht ein Client seine Verbindung zwischen select() und accept() ab,
darf der Server-Thread nicht bis zur nächsten Verbindung hängen (sonst hängt auch shutdown()).

Nachgestellt, indem _handle_request_noblock() ohne wartende Verbindung aufgerufen wird – genau die
Lage nach einem Abbruch: select() hat „lesbar“ gemeldet, die Verbindung ist aber schon weg."""

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer  # noqa: E402


class _Leer(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _kehrt_zurueck(server) -> bool:
    done = threading.Event()

    def run():
        server._handle_request_noblock()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    return done.wait(2.0)


class AcceptBlockiertNichtTest(unittest.TestCase):
    def test_produktivserver(self):
        import server  # noqa: PLC0415

        httpd = server.QuietHTTPServer(("127.0.0.1", 0), _Leer)
        try:
            self.assertEqual(httpd.socket.gettimeout(), 0.0)
            self.assertTrue(_kehrt_zurueck(httpd), "accept() blockiert ohne wartende Verbindung")
        finally:
            httpd.server_close()

    def test_testserver(self):
        httpd = JoiningHTTPServer(("127.0.0.1", 0), _Leer)
        try:
            self.assertEqual(httpd.socket.gettimeout(), 0.0)
            self.assertTrue(_kehrt_zurueck(httpd), "accept() blockiert ohne wartende Verbindung")
        finally:
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
