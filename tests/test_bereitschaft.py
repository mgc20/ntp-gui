"""Strenge Bereitschaftsprüfung /readyz (1.11).

- 200 nur, wenn chronyd antwortet, an eine echte Quelle synchronisiert ist und die Fehlerschranke
  (|Offset| + Root-Dispersion + Root-Delay/2) unter der Grenze liegt; sonst 503.
- Die Antwort enthält nur status und Wahrheitswerte – keine Zahlen, keine Quellen, keine Grenze.
- Grenze aus der Einstellung ready_max_error_ms bzw. READY_MAX_ERROR_MS, Standard 100 ms.
- Ohne Anmeldung und für jeden Host-Namen erreichbar wie /healthz, auch mit WEB_REQUIRE_AUTH ohne Zugang.
- /healthz bleibt unverändert.
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import apiv1  # noqa: E402
import authguard  # noqa: E402
import chrony  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

AUTH_ENV = ("WEB_USER", "WEB_PASSWORD", "WEB_PASSWORD_FILE", "WEB_REQUIRE_AUTH", "WEB_READONLY",
            "READY_MAX_ERROR_MS")

SYNCED = {"ref_id": "C0000201", "stratum": 2, "leap_status": "Normal", "synchronised": True,
          "local_reference": False, "system_time_offset": 0.0004, "root_delay": 0.010,
          "root_dispersion": 0.002}                       # Fehlerschranke 0,4 + 2 + 5 = 7,4 ms
PPS = dict(SYNCED, stratum=1, system_time_offset=2e-7, root_delay=0.0, root_dispersion=1.5e-6)
UNSYNCED = {"ref_id": "00000000", "stratum": 0, "leap_status": "Not synchronised", "synchronised": False,
            "local_reference": False, "system_time_offset": 0.0, "root_delay": 0.0, "root_dispersion": 0.0}
LOCAL = dict(SYNCED, ref_id="7F7F0101", stratum=10, synchronised=False, local_reference=True)
KEYS = {"status", "chrony", "synchronised", "within_limit"}


class ReadinessDecisionTests(unittest.TestCase):
    def test_synced_below_limit_is_ready(self):
        self.assertEqual(server.readiness(SYNCED, 100.0),
                         {"status": "ready", "chrony": True, "synchronised": True, "within_limit": True})
        self.assertEqual(server.readiness(PPS, 0.01)["status"], "ready")

    def test_error_bound_at_or_above_limit_is_not_ready(self):
        state = server.readiness(SYNCED, 7.0)
        self.assertEqual(state["status"], "not_ready")
        self.assertIs(state["synchronised"], True)
        self.assertIs(state["within_limit"], False)
        # Negativer Offset zählt mit seinem Betrag.
        self.assertEqual(server.readiness(dict(SYNCED, system_time_offset=-0.2), 100.0)["status"], "not_ready")

    def test_unsynced_local_and_silent_are_not_ready(self):
        self.assertEqual(server.readiness(UNSYNCED, 100.0),
                         {"status": "not_ready", "chrony": True, "synchronised": False, "within_limit": False})
        self.assertEqual(server.readiness(LOCAL, 100.0)["status"], "not_ready")
        self.assertEqual(server.readiness({}, 100.0),
                         {"status": "not_ready", "chrony": False, "synchronised": False, "within_limit": False})

    def test_missing_or_broken_numbers_are_not_ready(self):
        broken = dict(SYNCED)
        del broken["root_delay"]
        self.assertEqual(server.readiness(broken, 100.0)["status"], "not_ready")
        self.assertEqual(server.readiness(dict(SYNCED, root_dispersion="x"), 100.0)["status"], "not_ready")
        self.assertEqual(server.readiness(dict(SYNCED, root_dispersion=float("nan")), 100.0)["status"],
                         "not_ready")

    def test_answer_carries_only_booleans(self):
        for tracking in (SYNCED, UNSYNCED, LOCAL, {}):
            state = server.readiness(tracking, 100.0)
            self.assertEqual(set(state), KEYS)
            self.assertTrue(all(isinstance(state[k], bool) for k in KEYS - {"status"}))


class ReadyLimitSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in AUTH_ENV}
        self.patches = [mock.patch.object(settings, "DATA_DIR", self.tmp.name),
                        mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp.name, "settings.json")),
                        mock.patch.dict(os.environ, env, clear=True)]
        for patch in self.patches:
            patch.start()
        settings._CACHE.update(mtime=None, data=None)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        settings._CACHE.update(mtime=None, data=None)
        self.tmp.cleanup()

    def test_default_env_and_validation(self):
        self.assertEqual(settings.FIELDS["ready_max_error_ms"]["default"], 100.0)
        self.assertEqual(server.ready_limit_ms(), 100.0)
        self.assertEqual(settings.values({"READY_MAX_ERROR_MS": "1.5"})["ready_max_error_ms"], 1.5)
        with mock.patch.dict(os.environ, {"READY_MAX_ERROR_MS": "2.5"}):
            self.assertEqual(server.ready_limit_ms(), 2.5)
        for bad in (0, -1, 20000, "viel", float("inf"), True):
            with self.subTest(bad=bad), self.assertRaises(settings.ValidationError):
                settings.validate({"ready_max_error_ms": bad})
        self.assertEqual(settings.validate({"ready_max_error_ms": "0.5"})["ready_max_error_ms"], 0.5)

    def test_unreadable_settings_fall_back(self):
        with mock.patch.object(settings, "values", side_effect=RuntimeError("kaputt")):
            self.assertEqual(server.ready_limit_ms(), 100.0)
            with mock.patch.dict(os.environ, {"READY_MAX_ERROR_MS": "3"}):
                self.assertEqual(server.ready_limit_ms(), 3.0)

    def test_endpoint_is_described_as_public(self):
        self.assertEqual(apiv1.required_scope("GET", "/readyz"), "public")


class _ServerBase(unittest.TestCase):
    ENV: dict = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in AUTH_ENV}
        env.update(self.ENV)
        self.tracking = dict(SYNCED)
        self.patches = [
            mock.patch.object(settings, "DATA_DIR", self.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", self.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(chrony, "tracking", side_effect=lambda: self.tracking),
        ]
        for patch in self.patches:
            patch.start()
        settings._CACHE.update(mtime=None, data=None)
        server._HEALTHZ_CACHE.update(t=None, tracking=None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        authguard.GUARD.clear()
        self.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        stop_http_server(self.httpd)
        for patch in reversed(self.patches):
            patch.stop()
        store.close_all()
        settings._CACHE.update(mtime=None, data=None)
        server._HEALTHZ_CACHE.update(t=None, tracking=None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        authguard.GUARD.clear()
        self.tmp.cleanup()

    def get(self, path, host="127.0.0.1", method="GET"):
        server._HEALTHZ_CACHE.update(t=None, tracking=None)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers={"Host": host})
            resp = conn.getresponse()
            body = resp.read()
            try:
                payload = json.loads(body) if body else None
            except ValueError:
                payload = body
            return resp.status, payload, resp
        finally:
            conn.close()


class ReadyzEndpointTests(_ServerBase):
    def test_ready_and_not_ready(self):
        status, body, resp = self.get("/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ready", "chrony": True, "synchronised": True, "within_limit": True})
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")
        self.tracking = dict(UNSYNCED)
        status, body, _ = self.get("/readyz")
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "not_ready")
        self.tracking = {}
        self.assertEqual(self.get("/readyz")[0], 503)

    def test_limit_from_settings(self):
        settings.save({"ready_max_error_ms": 5})
        status, body, _ = self.get("/readyz")
        self.assertEqual(status, 503)
        self.assertEqual(body, {"status": "not_ready", "chrony": True, "synchronised": True, "within_limit": False})
        settings.save({"ready_max_error_ms": 10})
        self.assertEqual(self.get("/readyz")[0], 200)

    def test_answer_has_no_numbers(self):
        _, body, _ = self.get("/readyz")
        self.assertEqual(set(body), KEYS)
        text = json.dumps(body)
        for leak in ("0.0004", "C0000201", "100", "stratum", "offset"):
            self.assertNotIn(leak, text)

    def test_healthz_unchanged(self):
        self.tracking = dict(UNSYNCED)
        status, body, _ = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok", "chrony": True})

    def test_head_and_foreign_host_name(self):
        status, _, _ = self.get("/readyz", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/readyz", host="fremd.example")[0], 200)
        self.assertEqual(self.get("/readyz/")[0], 200)

    def test_write_methods_are_not_open(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", "/readyz", body=b"{}", headers={"Content-Type": "application/json"})
            self.assertNotEqual(conn.getresponse().status, 200)
        finally:
            conn.close()


class ReadyzLockedTests(_ServerBase):
    ENV = {"WEB_REQUIRE_AUTH": "true"}

    def test_open_while_dashboard_is_locked(self):
        self.assertEqual(self.get("/api/status")[0], 503)
        status, body, _ = self.get("/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), KEYS)


class ReadyzWithPasswordTests(_ServerBase):
    ENV = {"WEB_USER": "admin", "WEB_PASSWORD": "lang-und-eigen-42"}

    def test_no_login_needed(self):
        self.assertEqual(self.get("/api/status")[0], 401)
        self.assertEqual(self.get("/readyz")[0], 200)


if __name__ == "__main__":
    unittest.main()
