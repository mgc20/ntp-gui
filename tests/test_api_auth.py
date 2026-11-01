"""API-Schlüssel, /api/v1 und Ereignisse aus Zustandswechseln – am echten HTTP-Handler.

Läuft ohne chronyd: nur Routen, die keine chronyc-Abfrage brauchen.
"""

import base64
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import apikeys  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import statewatch  # noqa: E402
import store  # noqa: E402


class ApiAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("WEB_READONLY", None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.read_id, cls.read_key = apikeys.create("Lesen", "read")
        cls.admin_id, cls.admin_key = apikeys.create("Verwalten", "admin")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return resp.status, payload

    def basic(self):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(), "X-NTP-GUI": "1"}

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    def test_without_login_denied(self):
        self.assertEqual(self.request("GET", "/api/v1/instance")[0], 401)

    def test_read_key_reads_but_cannot_write(self):
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.bearer(self.read_key))[0], 200)
        status, payload = self.request("POST", "/api/v1/reload", {}, self.bearer(self.read_key))
        self.assertEqual(status, 403)
        self.assertEqual(payload["scope_required"], "admin")

    def test_admin_key_writes_without_csrf_header(self):
        status, payload = self.request("POST", "/api/v1/reload", {}, self.bearer(self.admin_key))
        self.assertEqual(status, 200)
        self.assertIn("reload_triggered", payload)

    def test_key_post_still_needs_json(self):
        status, _ = self.request("POST", "/api/v1/reload", None,
                                 dict(self.bearer(self.admin_key), **{"Content-Type": "text/plain"}))
        self.assertEqual(status, 403)

    def test_session_endpoints_never_with_key(self):
        for path, body in (("/api/apikeys", {"name": "x", "scope": "admin"}), ("/api/auth", {"clear": True}),
                           ("/api/instance/rotate", {}), ("/api/keys/revoke", {"id": self.read_id})):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, body, self.bearer(self.admin_key))[0], 403)
        self.assertEqual(self.request("GET", "/api/apikeys", headers=self.bearer(self.admin_key))[0], 403)

    def test_basic_login_manages_keys(self):
        status, payload = self.request("GET", "/api/keys", headers=self.basic())
        self.assertEqual(status, 200)
        self.assertIn(self.admin_id, [k["id"] for k in payload["keys"]])
        self.assertNotIn("token", json.dumps(payload))

    def test_bad_and_revoked_keys(self):
        status, _ = self.request("GET", "/api/v1/instance", headers=self.bearer("ntpg_AAAAAAAAbbbbbbbbbbbbbbbbbbbbbbbb"))
        self.assertEqual(status, 401)
        key_id, token = apikeys.create("Kurzlebig", "read")
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.bearer(token))[0], 200)
        status, _ = self.request("POST", "/api/apikeys/revoke", {"id": key_id}, self.basic())
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=self.bearer(token))[0], 401)

    def test_basic_post_keeps_csrf(self):
        headers = self.basic()
        del headers["X-NTP-GUI"]
        self.assertEqual(self.request("POST", "/api/reload", {}, headers)[0], 403)

    def test_v1_index_and_unknown(self):
        status, payload = self.request("GET", "/api/v1", headers=self.basic())
        self.assertEqual(status, 200)
        paths = {e["path"] for e in payload["endpoints"]}
        for path in ("/api/v1/status", "/api/v1/events", "/api/v1/diagnostics/bundle", "/api/v1/gps/autocal"):
            self.assertIn(path, paths)
        self.assertEqual(self.request("GET", "/api/v1/gibtsnicht", headers=self.basic())[0], 404)

    def test_settings_notes_in_schema(self):
        status, payload = self.request("GET", "/api/v1/settings", headers=self.bearer(self.read_key))
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema_version"], settings.SCHEMA_VERSION)
        self.assertIsInstance(payload["notes"], list)


class HostCheckTest(unittest.TestCase):
    """DNS-Rebinding: ohne Passwort nur bekannte bzw. lokale Host-Namen."""

    def test_host_allowed_rules(self):
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": ""}), \
                mock.patch.object(server.socket, "gethostname", return_value="ntpbox"), \
                mock.patch.object(server.socket, "getfqdn", return_value="ntpbox.example.net"):
            for ok in ("192.0.2.5:8080", "127.0.0.1", "[::1]:8080", "[fe80::1%eth0]:80", "localhost:8080",
                       "app.localhost", "raspberrypi:8080", "ntpbox", "NTPBOX.example.net.", "pi.local",
                       "pi.lan:8080", "pi.home.arpa", "zeit.internal", "", None):
                with self.subTest(ok=ok):
                    self.assertTrue(server.host_allowed(ok))
            for bad in ("attacker.example:8080", "rebind.evil.com", "192.0.2.5.nip.io", "localhost.evil.com",
                        "fritz.box.evil.com", "local.evil.com",
                        # ".box" ist eine öffentliche Endung – fritz.box war schon fremd registriert
                        "pi.fritz.box", "fritz.box"):
                with self.subTest(bad=bad):
                    self.assertFalse(server.host_allowed(bad))
            self.assertTrue(server.host_allowed("zeit.example.org", nts_name="Zeit.Example.org"))
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "zeit.example.org, *.mein-dorf.us"}):
            self.assertTrue(server.host_allowed("zeit.example.org:8080"))
            self.assertTrue(server.host_allowed("ntp.mein-dorf.us"))
            self.assertTrue(server.host_allowed("mein-dorf.us"))
            self.assertFalse(server.host_allowed("evil-mein-dorf.us"))
            self.assertFalse(server.host_allowed("attacker.example"))
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "*"}):
            self.assertTrue(server.host_allowed("attacker.example"))
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "*.fritz.box"}):
            self.assertTrue(server.host_allowed("pi.fritz.box"))

    def test_logged_host_is_cleaned(self):
        """Der Host-Header landet im Log – überlang oder mit fremden Zeichen nur als <ungültig>."""
        self.assertEqual(server.safe_host_for_log("attacker.example"), "attacker.example")
        self.assertEqual(server.safe_host_for_log("a" * 64 + ".attacker.de"), "<ungültig>")
        self.assertEqual(server.safe_host_for_log("x" * 300), "<ungültig>")
        self.assertEqual(server.safe_host_for_log("evil\u201c.de"), "<ungültig>")
        self.assertEqual(server.safe_host_for_log("evil.de/../x"), "<ungültig>")


class HostCheckServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in {"WEB_USER", "WEB_PASSWORD", "WEB_ALLOWED_HOSTS"}}
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
        ]
        for patch in cls.patches:
            patch.start()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        server._REJECTED_HOSTS.clear()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.key_id, cls.key = apikeys.create("Lesen", "read")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        cls.tmp.cleanup()

    def request(self, method, path, host, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host)
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        data = json.dumps(body).encode() if body is not None else b""
        if method == "POST":
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data if method == "POST" else None)
        resp = conn.getresponse()
        raw = resp.read()
        ctype = resp.getheader("Content-Type", "")
        conn.close()
        return resp.status, raw, ctype

    def test_ip_and_localhost_allowed(self):
        self.assertEqual(self.request("GET", "/api/v1/instance", f"127.0.0.1:{self.port}")[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/instance", f"localhost:{self.port}")[0], 200)

    def test_foreign_host_rejected_with_german_explanation(self):
        server._REJECTED_HOSTS.clear()
        with mock.patch("builtins.print") as printed:
            status, raw, ctype = self.request("GET", "/api/logs", "attacker.example:8087")
            self.assertEqual(status, 403)
            self.assertIn("json", ctype)
            payload = json.loads(raw)
            self.assertEqual(payload["reason"], "host_not_allowed")
            self.assertIn("WEB_ALLOWED_HOSTS", payload["error"])
            self.assertIn("Passwort", payload["error"])
            status, raw, ctype = self.request("GET", "/", "attacker.example")
            self.assertEqual(status, 403)
            self.assertIn("text/html", ctype)
            self.assertIn("WEB_ALLOWED_HOSTS".encode(), raw)
            self.assertEqual(self.request("POST", "/api/reload", "attacker.example", {"X-NTP-GUI": "1"}, {})[0], 403)
            self.assertEqual(self.request("GET", "/api/status", "attacker.example")[0], 403)
        logged = [c for c in printed.call_args_list if "attacker.example" in str(c)]
        self.assertEqual(len(logged), 1)  # nur einmal je Name protokolliert

    def test_healthz_always_allowed(self):
        self.assertNotEqual(self.request("GET", "/healthz", "attacker.example")[0], 403)

    def test_env_allow_list(self):
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "zeit.example.org"}), mock.patch("builtins.print"):
            self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org:8080")[0], 200)
            self.assertEqual(self.request("GET", "/api/v1/instance", "attacker.example")[0], 403)

    def test_api_key_works_with_any_host(self):
        status, _, _ = self.request("GET", "/api/v1/instance", "ntp.example.org",
                                    {"Authorization": f"Bearer {self.key}"})
        self.assertEqual(status, 200)

    def test_with_password_any_host(self):
        with mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}):
            auth = {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode()}
            self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org", auth)[0], 200)
            self.assertEqual(self.request("GET", "/api/v1/instance", "zeit.example.org")[0], 401)


class StateWatchTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.events.append(a), gps_fix_hold=0)

    @staticmethod
    def sample(selected="A", mode=3):
        return {"sources": {"A": {"s": "*" if selected == "A" else "+"},
                            "B": {"s": "*" if selected == "B" else "-"}},
                "gps": {"mode": mode, "used": 8}}

    def feed(self, *samples):
        for s in samples:
            self.watch.sample(s)

    def test_first_state_is_no_event(self):
        self.feed(self.sample(), self.sample(), self.sample())
        self.assertEqual(self.events, [])

    def test_source_change_needs_confirmation(self):
        self.feed(self.sample("A"), self.sample("A"), self.sample("B"), self.sample("A"))
        self.assertEqual(self.events, [])  # ein einzelner Ausreißer
        self.feed(self.sample("B"), self.sample("B"))
        self.assertEqual([(e[0], e[1]) for e in self.events], [("source", "info")])
        self.assertIn("A → B", self.events[0][2])

    def test_fix_lost_and_back(self):
        self.feed(self.sample(mode=3), self.sample(mode=3), self.sample(mode=1), self.sample(mode=1))
        self.feed(self.sample(mode=3), self.sample(mode=3))
        self.assertEqual([(e[0], e[1], e[2]) for e in self.events],
                         [("gps", "warn", "GPS-Fix verloren"), ("gps", "info", "GPS-Fix wieder da")])

    def test_pps_lost_and_back(self):
        live = {"pps": [{"dev": "/dev/pps0", "state": "live"}]}
        silent = {"pps": [{"dev": "/dev/pps0", "state": "silent"}]}
        for rep in (live, {"pps": [{"dev": "/dev/pps0", "state": "unknown"}]}, silent, silent, live):
            self.watch.hardware(rep)
        self.assertEqual([(e[0], e[1]) for e in self.events], [("pps", "warn"), ("pps", "info")])

    def test_never_live_is_not_lost(self):
        for _ in range(3):
            self.watch.hardware({"pps": [{"dev": "/dev/pps1", "state": "never"}]})
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
