"""Robustheit des HTTP-Servers (1.9).

- Höchstzahl gleichzeitiger Verbindungen: Darüber wird sofort geschlossen, ohne Thread; ein nicht
  startbarer Thread legt den Server nicht lahm.
- /healthz fragt chronyd zwischengespeichert ab, nicht je Anfrage.
- Unerwartete Fehler: an den Client nur eine allgemeine Meldung, Einzelheiten ins Log.
- Tief verschachteltes JSON: 400 statt Abbruch ohne Antwort.
- Schutzköpfe (COOP, CORP, Permissions-Policy, Trusted Types), Server-Kopf ohne Python-Version.
- Teure GET-Routen nur aus dem Dashboard; HEAD auf sie baut nichts.
- Sicherung: Namensmuster ohne angehängten Zeilenumbruch, kein doppelter Kopf.
- Watchdog im Entrypoint: Prüfung ohne Subshell, ein laufender Dienst gilt nie als tot.
"""

import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import backup  # noqa: E402
import chrony  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

TRACKING = {"reference_id": "7F7F0101", "stratum": 3}


class _Base(unittest.TestCase):
    """Server im offenen Modus (kein Passwort) mit eigenem Datenordner."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items()
               if k not in ("WEB_USER", "WEB_PASSWORD", "WEB_PASSWORD_FILE", "WEB_READONLY", "WEB_REQUIRE_AUTH")}
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
        ]
        for patch in cls.patches:
            patch.start()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp, resp.read()
        finally:
            conn.close()

    def raw(self, data: bytes) -> bytes:
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(data)
            out = b""
            try:
                while chunk := sock.recv(65536):
                    out += chunk
                    if b"\r\n\r\n" in out:
                        head, _, rest = out.partition(b"\r\n\r\n")
                        m = re.search(rb"Content-Length: (\d+)", head)
                        if m and len(rest) >= int(m.group(1)):
                            break
            except socket.timeout:
                pass
            return out


class HealthzCacheTest(_Base):
    def setUp(self):
        server._HEALTHZ_CACHE.update(t=None, tracking=None)

    def test_many_requests_start_one_query(self):
        calls = []
        with mock.patch.object(chrony, "tracking", side_effect=lambda: calls.append(1) or TRACKING):
            for _ in range(6):
                resp, body = self.request("GET", "/healthz")
                self.assertEqual(resp.status, 200)
                self.assertEqual(json.loads(body)["status"], "ok")
        self.assertEqual(len(calls), 1)

    def test_cache_expires(self):
        calls = []
        with mock.patch.object(chrony, "tracking", side_effect=lambda: calls.append(1) or {}):
            resp, _ = self.request("GET", "/healthz")
            self.assertEqual(resp.status, 503)
            server._HEALTHZ_CACHE["t"] -= server.HEALTHZ_CACHE_SECONDS + 1
            self.request("GET", "/healthz")
        self.assertEqual(len(calls), 2)


class InternalErrorTest(_Base):
    SECRET = "/opt/geheimer/pfad/datei"

    def test_get_error_text_stays_in_log(self):
        log = io.StringIO()
        with mock.patch.object(server.Handler, "_route_get", side_effect=OSError(2, "weg", self.SECRET)), \
                mock.patch("sys.stdout", log):
            resp, body = self.request("GET", "/api/status")
        self.assertEqual(resp.status, 500)
        self.assertNotIn(self.SECRET.encode(), body)
        self.assertIn("Interner Fehler", json.loads(body)["error"])
        self.assertIn(self.SECRET, log.getvalue())

    def test_post_error_text_stays_in_log(self):
        with mock.patch.object(server.Handler, "_route_post", side_effect=RuntimeError(self.SECRET)), \
                mock.patch("sys.stdout", io.StringIO()):
            resp, body = self.request("POST", "/api/settings", body=b"{}",
                                      headers={"Content-Type": "application/json", "X-NTP-GUI": "1"})
        self.assertEqual(resp.status, 500)
        self.assertNotIn(self.SECRET.encode(), body)

    def test_overlong_static_name_is_404_without_path(self):
        resp, body = self.request("GET", "/static/" + "a" * 300)
        self.assertEqual(resp.status, 404)
        self.assertNotIn(str(server.STATIC_DIR).encode(), body)

    def test_static_name_with_nul_is_404(self):
        out = self.raw(b"GET /static/x\x00y HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 404") or out.startswith(b"HTTP/1.1 400"), out[:80])
        self.assertNotIn(b"null character", out)
        self.assertNotIn(str(server.STATIC_DIR).encode(), out)


class DeepJsonTest(_Base):
    def test_deeply_nested_json_gets_400(self):
        body = ('{"changes":' + "[" * 30000 + "]" * 30000 + "}").encode()
        self.assertLess(len(body), server.MAX_BODY)
        resp, data = self.request("POST", "/api/settings", body=body,
                                  headers={"Content-Type": "application/json", "X-NTP-GUI": "1"})
        self.assertEqual(resp.status, 400)
        self.assertIn("verschachtelt", json.loads(data)["error"])

    def test_backup_manifest_deeply_nested_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write("[" * 100000 + "]" * 100000)
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(backup.RestoreError):
            backup._read_json(handle.name, "manifest.json")


class HeaderTest(_Base):
    def test_modern_protection_headers(self):
        for path in ("/", "/healthz", "/static/app.css", "/gibt-es-nicht"):
            resp, _ = self.request("GET", path)
            self.assertEqual(resp.getheader("Cross-Origin-Opener-Policy"), "same-origin", path)
            self.assertEqual(resp.getheader("Cross-Origin-Resource-Policy"), "same-origin", path)
            policy = resp.getheader("Permissions-Policy") or ""
            for feature in ("camera=()", "microphone=()", "geolocation=()"):
                self.assertIn(feature, policy, path)
            for needed in ("fullscreen", "screen-wake-lock", "autoplay", "clipboard-write"):
                self.assertNotIn(needed, policy, f"{path}: die Uhr braucht {needed}")
            csp = resp.getheader("Content-Security-Policy")
            self.assertIn("require-trusted-types-for 'script'", csp)
            self.assertIn("trusted-types 'none'", csp)

    def test_server_header_without_python_version(self):
        for path in ("/healthz", "/"):
            resp, _ = self.request("GET", path)
            self.assertEqual(resp.getheader("Server"), "ntp-gui", path)

    def test_error_page_server_header(self):
        out = self.raw(b"GET / HTTP/9.9\r\n\r\n")
        self.assertIn(b"Server: ntp-gui\r\n", out)
        self.assertNotIn(b"Python", out)


def _fake_create(dest, version=""):
    with open(dest, "wb") as handle:
        handle.write(b"\x1f\x8b sicherung")
    return {"created": time.time()}


class CostlyGetTest(_Base):
    def test_cross_site_backup_is_refused(self):
        with mock.patch.object(backup, "create", side_effect=_fake_create) as create:
            for site in ("cross-site", "same-site"):
                resp, _ = self.request("GET", "/api/backup", headers={"Sec-Fetch-Site": site})
                self.assertEqual(resp.status, 403, site)
            create.assert_not_called()

    def test_dashboard_and_tools_may_download(self):
        with mock.patch.object(backup, "create", side_effect=_fake_create) as create:
            for headers in ({"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}):
                resp, body = self.request("GET", "/api/backup", headers=headers)
                self.assertEqual(resp.status, 200, headers)
                self.assertEqual(body, b"\x1f\x8b sicherung")
                self.assertEqual(len(resp.msg.get_all("X-Content-Type-Options")), 1, "Kopf doppelt")
            self.assertEqual(create.call_count, 3)

    def test_cross_site_diagnostics_refused(self):
        for path in ("/api/diagnostics/bundle", "/api/diagnostics/preview?async=1"):
            resp, _ = self.request("GET", path, headers={"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(resp.status, 403, path)

    def test_hardware_refresh_only_from_dashboard(self):
        import hardware
        with mock.patch.object(hardware, "report", return_value={"ok": True}) as report:
            resp, _ = self.request("GET", "/api/hardware?refresh=1", headers={"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(resp.status, 403)
            report.assert_not_called()
            resp, _ = self.request("GET", "/api/hardware", headers={"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(resp.status, 200)  # ohne Neuprüfung nur Lesen

    def test_head_backup_builds_nothing(self):
        with mock.patch.object(backup, "create", side_effect=_fake_create) as create:
            resp, _ = self.request("HEAD", "/api/backup")
            self.assertEqual(resp.status, 405)
            self.assertEqual(resp.getheader("Allow"), "GET")
            create.assert_not_called()

    def test_stored_name_with_trailing_newline_does_not_match(self):
        self.assertIsNotNone(backup._STORED_RE.match("nacht-20261121.tar.gz"))
        self.assertIsNone(backup._STORED_RE.match("nacht-20261121.tar.gz\n"))


class ConnectionLimitTest(unittest.TestCase):
    LIMIT = 4

    def setUp(self):
        patches = [mock.patch.object(server.Handler, "timeout", 20.0),
                   mock.patch.object(server.QuietHTTPServer, "max_connections", self.LIMIT),
                   mock.patch.object(chrony, "tracking", return_value=TRACKING)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        server._HEALTHZ_CACHE.update(t=None, tracking=None)
        self.httpd = server.make_server("127.0.0.1", 0)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _idle(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(sock.close)
        return sock

    def _healthz(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/healthz")
            return conn.getresponse().status
        finally:
            conn.close()

    def _wait_busy(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.LIMIT - self.httpd._slots._value >= count:
                return
            time.sleep(0.02)
        self.fail("Verbindungen nicht angenommen")

    def test_connection_over_limit_is_closed_at_once(self):
        idle = [self._idle() for _ in range(self.LIMIT)]
        self._wait_busy(self.LIMIT)
        extra = self._idle()
        extra.settimeout(3)
        started = time.monotonic()
        try:
            data = extra.recv(1)
        except ConnectionResetError:
            data = b""
        self.assertEqual(data, b"", "Verbindung über der Grenze blieb offen")
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertGreaterEqual(self.httpd.rejected_connections, 1)
        for sock in idle:
            sock.close()
        deadline = time.monotonic() + 5
        while self.httpd._slots._value < self.LIMIT and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self._healthz(), 200, "nach dem Schließen wieder Platz")

    def test_thread_start_failure_keeps_server_running(self):
        real_start = threading.Thread.start

        def failing_start(thread):
            if thread._target == self.httpd.process_request_thread:
                raise RuntimeError("can't start new thread")
            return real_start(thread)

        with mock.patch.object(threading.Thread, "start", failing_start):
            sock = self._idle()
            sock.settimeout(3)
            try:
                data = sock.recv(1)
            except ConnectionResetError:
                data = b""
            self.assertEqual(data, b"")
        self.assertEqual(self.httpd._slots._value, self.LIMIT, "Platz nicht freigegeben")
        self.assertEqual(self._healthz(), 200)

    def test_limit_from_environment(self):
        text = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn('env_number("WEB_MAX_CONNECTIONS"', text)
        self.assertIn("`WEB_MAX_CONNECTIONS`", (ROOT / "README.md").read_text(encoding="utf-8"))


def _entrypoint_function(name: str) -> str:
    text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{.*?^\}}$", text, re.S | re.M)
    assert match, name
    return match.group(0)


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class WatchdogWithoutForkTest(unittest.TestCase):
    """service_alive darf keinen Prozess starten: Bei erreichter Prozessgrenze schlüge sonst die Prüfung
    fehl, und der Watchdog hielte einen laufenden Pflichtdienst für tot."""

    def test_check_uses_no_subshell(self):
        for name in ("service_alive", "wait_exec"):
            self.assertNotIn("$(", _entrypoint_function(name), name)

    def run_alive(self, prelude: str) -> str:
        proc = subprocess.Popen(["sleep", "30"])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        time.sleep(0.2)
        script = ("set -euo pipefail\n" + _entrypoint_function("wait_exec") + "\n"
                  + _entrypoint_function("service_alive") + "\n" + prelude + "\n"
                  + f'if service_alive "{proc.pid}=sleep"; then echo lebt; else echo tot; fi\n'
                  + 'if service_alive "999999999=sleep"; then echo lebt; else echo tot; fi\n'
                  + f'if service_alive "{proc.pid}=anders"; then echo lebt; else echo tot; fi\n')
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20,
                              check=True).stdout.split()

    def test_living_service_alive_when_external_tools_fail(self):
        # Ohne nutzbare externe Programme (wie bei erreichter Prozessgrenze) bleibt das Ergebnis richtig.
        out = self.run_alive('cat() { return 1; }\nPATH=/nonexistent')
        self.assertEqual(out, ["lebt", "tot", "tot"])

    def test_normal_case(self):
        self.assertEqual(self.run_alive(""), ["lebt", "tot", "tot"])

    def test_watchdog_loop_survives_failed_clock_read(self):
        text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("MONO=$(mono) || MONO=${MONO:-0}", text)


if __name__ == "__main__":
    unittest.main()
