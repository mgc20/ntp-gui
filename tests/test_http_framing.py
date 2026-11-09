"""HTTP-Rahmung: ein ungelesener Anfrage-Körper darf nie als nächste Anfrage gelten.

- GET/HEAD mit Körper, POST-Antworten vor dem Lesen des Körpers (405 auf /api/v1 …): Antwort mit
  „Connection: close“, danach zu – sonst würde der Körper auf einer Keep-alive-Verbindung (z. B.
  hinter einem Reverse Proxy) als weitere Anfrage ausgeführt (CL.0-Desync).
- Transfer-Encoding wird nicht unterstützt: 501, nichts ausführen, Verbindung zu.
- Widersprüchliche oder nicht rein numerische Content-Length-Köpfe: 400, Verbindung zu.
- Abfragewerte nan/inf fallen auf den Standard zurück statt HTTP 500.
"""

import http.client
import json
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import server  # noqa: E402

HIDDEN = b"GET /api/v1/instance HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"


class BodyFramingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reloads = []
        cls.patches = [mock.patch.object(server.Handler, "timeout", 1.0),
                       mock.patch.dict(os.environ, {"WEB_USER": "", "WEB_PASSWORD": "", "WEB_READONLY": ""}),
                       mock.patch.object(server, "trigger_reload", lambda: cls.reloads.append(1) or False)]
        for patch in cls.patches:
            patch.start()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()

    def setUp(self):
        self.reloads.clear()

    def exchange(self, raw: bytes) -> tuple[bytes, bool]:
        """Rohe Anfrage senden, alles bis zum Schließen (oder 3 s Stille) lesen.
        Ergebnis: (empfangene Bytes, ob der Server die Verbindung geschlossen hat)."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        self.addCleanup(sock.close)
        sock.sendall(raw)
        data = b""
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                return data, False
            except OSError:
                return data, True
            if not chunk:
                return data, True
            data += chunk
        return data, False

    def assert_single_closed(self, data: bytes, closed: bool) -> None:
        self.assertEqual(data.count(b"HTTP/1.1 "), 1, data)
        self.assertTrue(closed)
        head = data.split(b"\r\n\r\n", 1)[0].lower()
        self.assertIn(b"connection: close", head)

    def test_get_body_not_run_as_next_request(self):
        data, closed = self.exchange(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: "
                                     + str(len(HIDDEN)).encode() + b"\r\n\r\n" + HIDDEN)
        self.assert_single_closed(data, closed)
        self.assertNotIn(b"instance_id", data)

    def test_head_body_not_run_as_next_request(self):
        data, closed = self.exchange(b"HEAD /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: "
                                     + str(len(HIDDEN)).encode() + b"\r\n\r\n" + HIDDEN)
        self.assert_single_closed(data, closed)

    def test_post_index_405_closes(self):
        data, closed = self.exchange(b"POST /api/v1 HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: "
                                     + str(len(HIDDEN)).encode() + b"\r\n\r\n" + HIDDEN)
        self.assertTrue(data.startswith(b"HTTP/1.1 405"), data)
        self.assert_single_closed(data, closed)

    def test_post_invalid_length_closes(self):
        data, closed = self.exchange(b"POST /api/reload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                     b"Content-Type: application/json\r\nX-NTP-GUI: 1\r\n"
                                     b"Content-Length: 99999999\r\n\r\n" + HIDDEN)
        self.assertTrue(data.startswith(b"HTTP/1.1 400"), data)
        self.assert_single_closed(data, closed)

    def test_chunked_rejected_and_not_executed(self):
        body = b"2\r\n{}\r\n0\r\n\r\n"
        data, closed = self.exchange(b"POST /api/reload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                     b"Content-Type: application/json\r\nX-NTP-GUI: 1\r\n"
                                     b"Transfer-Encoding: chunked\r\n\r\n" + body)
        self.assertTrue(data.startswith(b"HTTP/1.1 501"), data)
        self.assert_single_closed(data, closed)
        self.assertEqual(self.reloads, [])

    def test_conflicting_content_length_rejected(self):
        # Erst „0“, dann die echte Länge: headers.get() sähe nur die 0 – der Körper liefe als
        # nächste Anfrage. Erwartet: 400, nichts ausgeführt, Verbindung zu.
        for method, extra in ((b"GET /healthz", b""),
                              (b"POST /api/reload", b"Content-Type: application/json\r\nX-NTP-GUI: 1\r\n")):
            with self.subTest(method=method):
                self.reloads.clear()
                data, closed = self.exchange(method + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n" + extra
                                             + b"Content-Length: 0\r\nContent-Length: "
                                             + str(len(HIDDEN)).encode() + b"\r\n\r\n" + HIDDEN)
                self.assertTrue(data.startswith(b"HTTP/1.1 400"), data)
                self.assert_single_closed(data, closed)
                self.assertNotIn(b"instance_id", data)
                self.assertEqual(self.reloads, [])

    def test_non_numeric_content_length_rejected(self):
        for value in (b"+0", b"-1", b"0x10", b"1, 1"):
            with self.subTest(value=value):
                data, closed = self.exchange(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                             b"Content-Length: " + value + b"\r\n\r\n" + HIDDEN)
                self.assertTrue(data.startswith(b"HTTP/1.1 400"), data)
                self.assert_single_closed(data, closed)

    def test_repeated_equal_content_length_accepted(self):
        data, closed = self.exchange(b"POST /api/reload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                     b"Content-Type: application/json\r\nX-NTP-GUI: 1\r\n"
                                     b"Content-Length: 2\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
        self.assertTrue(data.startswith(b"HTTP/1.1 200"), data)
        self.assertEqual(len(self.reloads), 1)

    def test_keepalive_still_works_for_complete_requests(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        for _ in range(2):
            conn.request("POST", "/api/reload", body=b"{}",
                         headers={"Content-Type": "application/json", "X-NTP-GUI": "1"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIsNone(resp.getheader("Connection"))
            resp.read()
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            self.assertIsNone(resp.getheader("Connection"))
            resp.read()
        self.assertEqual(len(self.reloads), 2)

    def test_nonfinite_query_values_use_default(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        for path in ("/api/history?points=nan", "/api/history?points=inf", "/api/history?range=-inf",
                     "/api/events?limit=nan", "/api/events?since=inf", "/api/logs?lines=inf"):
            with self.subTest(path=path):
                conn.request("GET", path)
                resp = conn.getresponse()
                body = resp.read()
                self.assertEqual(resp.status, 200, body)
                self.assertIsInstance(json.loads(body), dict)


class EnvLikeTest(unittest.TestCase):
    def test_nonfinite_falls_back(self):
        for raw in ("nan", "NaN", "inf", "-inf", "Infinity", "1e999"):
            with self.subTest(raw=raw):
                self.assertEqual(server.env_like(raw, 7.0), 7.0)

    def test_finite_kept(self):
        self.assertEqual(server.env_like("12.5", 7.0), 12.5)
        self.assertEqual(server.env_like("-3", 7.0), -3.0)
        self.assertEqual(server.env_like("", 7.0), 7.0)
        self.assertEqual(server.env_like("abc", 7.0), 7.0)


if __name__ == "__main__":
    unittest.main()
