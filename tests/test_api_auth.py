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


class StateWatchTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.events.append(a))

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
