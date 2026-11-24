"""Zeitwächter-Ping (heartbeat.py) und Zweck „heartbeat“ im Filter (egress.py).

Geprüft: Form der Anfrage (leere Feldliste, nur GET, fester User-Agent, Zustand nur in der Adresse),
Zielschutz wie bei den Benachrichtigungen (netguard, keine Weiterleitungen, kurze Frist), Takt und
Ergebnis, „aus“ ohne jede Verbindung, Umgang mit der Adresse als Geheimnis (Lese-Schlüssel, Export,
Sicherung, Diagnosepaket) und die beiden Routen am echten HTTP-Handler.
"""

import base64
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import backup  # noqa: E402
import diagnostics  # noqa: E402
import egress  # noqa: E402
import events  # noqa: E402
import heartbeat  # noqa: E402
import notify  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

LOOPBACK = {"OUTBOUND_TARGETS": "loopback"}


class Recorder:
    """Kleiner HTTP-Server: merkt sich Methode, Pfad, Kopfzeilen und Body jeder Anfrage."""

    def __init__(self, status=200, location=None, delay=0.0):
        self.hits = []
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                recorder.hits.append({"method": self.command, "path": self.path,
                                      "headers": dict(self.headers), "body": body})
                if delay:
                    time.sleep(delay)
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"OK")

            do_GET = do_POST = _answer  # noqa: N815

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, path="/ping/abc123"):
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class NoNetwork:
    """Socket-Attrappe: jeder Versuch einer Verbindung oder DNS-Abfrage wird gezählt und abgelehnt."""

    def __init__(self):
        self.calls = []

    def _deny(self, name):
        def fn(*args, **kwargs):
            self.calls.append(name)
            raise OSError("Netz in diesem Test verboten")
        return fn

    def __enter__(self):
        self.patches = [mock.patch.object(socket, "socket", side_effect=self._deny("socket")),
                        mock.patch.object(socket, "create_connection", side_effect=self._deny("create_connection")),
                        mock.patch.object(socket, "getaddrinfo", side_effect=self._deny("getaddrinfo"))]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


class EgressTest(unittest.TestCase):
    def test_purpose_with_empty_field_list(self):
        self.assertIn("heartbeat", egress.PURPOSES)
        self.assertEqual(egress.HEARTBEAT_FIELDS, ())
        egress.Sanitizer("heartbeat")  # Zweck ist dem Filter bekannt

    def test_healthchecks_form(self):
        base = "https://hc-ping.com/0a1b2c3d-1111-2222-3333-444455556666"
        self.assertEqual(egress.heartbeat_request(base, "up"), (base, {"User-Agent": "ntp-gui"}))
        self.assertEqual(egress.heartbeat_request(base, "down")[0], base + "/fail")
        self.assertEqual(egress.heartbeat_request(base + "/?rid=7#x", "down")[0],
                         "https://hc-ping.com/0a1b2c3d-1111-2222-3333-444455556666/fail?rid=7")

    def test_kuma_form_detected_and_status_replaced(self):
        base = "http://kuma.lan:3001/api/push/Ab12Cd?status=up&msg=OK&ping="
        self.assertEqual(egress.heartbeat_flavor(base), "kuma")
        self.assertEqual(egress.heartbeat_request(base, "up")[0],
                         "http://kuma.lan:3001/api/push/Ab12Cd?status=up&msg=OK")
        self.assertEqual(egress.heartbeat_request(base, "down")[0],
                         "http://kuma.lan:3001/api/push/Ab12Cd?status=down&msg=kritisch")
        # ausdrücklich gewählt auch für eine andere Adresse
        self.assertEqual(egress.heartbeat_request("https://w.example/hb", "down", "kuma")[0],
                         "https://w.example/hb?status=down&msg=kritisch")

    def test_silent_sends_nothing_when_critical(self):
        self.assertIsNone(egress.heartbeat_request("https://w.example/hb", "down", "silent"))
        self.assertEqual(egress.heartbeat_request("https://w.example/hb", "up", "silent")[0], "https://w.example/hb")

    def test_rejects_anything_beyond_the_fixed_form(self):
        base = "https://w.example/hb"
        bad = [dict(state="ok"), dict(fields={"offset": 0.1}), dict(headers={"User-Agent": "ntp-gui/1.11"}),
               dict(headers={"User-Agent": "ntp-gui", "X-Host": "zeitserver"}), dict(mode="post")]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                args = {"state": "up", **kwargs}
                with self.assertRaises(egress.HeartbeatRejected):
                    egress.heartbeat_request(base, args.pop("state"), **args)
        with self.assertRaises(egress.HeartbeatRejected):
            egress.heartbeat_request("ftp://w.example/hb", "up")


class ValidateTest(unittest.TestCase):
    def test_accepts_and_rejects(self):
        ok = ["", "https://hc-ping.com/abc", "http://kuma.lan:3001/api/push/abc", "http://192.168.1.5:3001/api/push/x",
              "http://watch.example.org/"]
        for url in ok:
            with self.subTest(url=url):
                self.assertEqual(heartbeat.validate_url(url), url)
        bad = ["ftp://x.example/", "https://u:p@x.example/", "http://169.254.169.254/latest",
               "http://127.0.0.1:3001/api/push/x", "http://watch.example.org/api/push/geheim", "https://x.example/ a"]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    heartbeat.validate_url(url)

    def test_loopback_only_with_outbound_targets(self):
        with mock.patch.dict(os.environ, LOOPBACK):
            self.assertEqual(heartbeat.validate_url("http://127.0.0.1:3001/api/push/x"),
                             "http://127.0.0.1:3001/api/push/x")

    def test_settings_fields_default_off(self):
        fields = {f["key"]: f for f in settings.SCHEMA}
        self.assertEqual(fields["heartbeat_url"]["default"], "")
        self.assertEqual(fields["heartbeat_interval"]["default"], 60)
        self.assertEqual(fields["heartbeat_mode"]["default"], "auto")
        self.assertIn("öffentliche IP", fields["heartbeat_url"]["help"])
        with self.assertRaises(settings.ValidationError):
            settings.validate({"heartbeat_interval": 5})
        with self.assertRaises(settings.ValidationError):
            settings.validate({"heartbeat_mode": "post"})
        with self.assertRaises(settings.ValidationError):
            settings.validate({"heartbeat_url": "http://169.254.169.254/"})


class SendTest(unittest.TestCase):
    def test_get_without_body_and_fixed_headers(self):
        with mock.patch.dict(os.environ, LOOPBACK), Recorder() as rec:
            self.assertEqual(heartbeat.send(rec.url(), "up", "healthchecks"), "up")
            self.assertEqual(heartbeat.send(rec.url(), "down", "healthchecks"), "fail")
            self.assertEqual(heartbeat.send(rec.url("/api/push/tok"), "down"), "fail")
        self.assertEqual([h["path"] for h in rec.hits],
                         ["/ping/abc123", "/ping/abc123/fail", "/api/push/tok?status=down&msg=kritisch"])
        for hit in rec.hits:
            self.assertEqual(hit["method"], "GET")
            self.assertEqual(hit["body"], b"")
            self.assertEqual(hit["headers"].get("User-Agent"), "ntp-gui")
            self.assertNotIn("Content-Type", hit["headers"])

    def test_no_redirect(self):
        with mock.patch.dict(os.environ, LOOPBACK), Recorder(status=302, location="/elsewhere") as rec:
            with self.assertRaisesRegex(heartbeat.PingError, "Weiterleitung"):
                heartbeat.send(rec.url(), "up")
        self.assertEqual(len(rec.hits), 1, "keine zweite Anfrage an das Weiterleitungsziel")

    def test_http_error_and_short_deadline(self):
        with mock.patch.dict(os.environ, LOOPBACK), Recorder(status=500) as rec:
            with self.assertRaisesRegex(heartbeat.PingError, "HTTP 500"):
                heartbeat.send(rec.url(), "up")
        with mock.patch.dict(os.environ, LOOPBACK), Recorder(delay=2.0) as rec:
            started = time.monotonic()
            with self.assertRaisesRegex(heartbeat.PingError, "Zeitüberschreitung"):
                heartbeat.send(rec.url(), "up", timeout=0.5)
            self.assertLess(time.monotonic() - started, 1.8)

    def test_loopback_blocked_by_default(self):
        with mock.patch.dict(os.environ, {"OUTBOUND_TARGETS": ""}), Recorder() as rec:
            with self.assertRaisesRegex(heartbeat.PingError, "gesperrt"):
                heartbeat.send(rec.url(), "up")
        self.assertEqual(rec.hits, [])

    def test_name_resolving_to_blocked_address(self):
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        with mock.patch.object(socket, "getaddrinfo", return_value=infos), \
                mock.patch.object(socket.socket, "connect", side_effect=AssertionError("keine Verbindung")):
            with self.assertRaisesRegex(heartbeat.PingError, "nicht erreichbar oder nicht erlaubt"):
                heartbeat.send("https://watch.example.org/hb", "up")

    def test_secret_over_http_only_into_own_network(self):
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80))]
        with mock.patch.object(socket, "getaddrinfo", return_value=infos), \
                mock.patch.object(socket.socket, "connect", side_effect=AssertionError("keine Verbindung")):
            with self.assertRaisesRegex(heartbeat.PingError, "eigenen Netz"):
                heartbeat.send("http://kuma.lan/api/push/geheim", "up")


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PingerTest(unittest.TestCase):
    def make(self, url="https://w.example/hb", state="up", sender=None, interval=60, mode="auto"):
        self.cfg = {"url": url, "interval": interval, "mode": mode}
        self.clock = FakeClock()
        self.sent = []
        self.events = []

        def default_sender(u, s, m):
            self.sent.append((u, s, m))
            return "fail" if s == "down" else "up"

        state_fn = state if callable(state) else (lambda: state)
        return heartbeat.Pinger(lambda: self.cfg, state_fn, sender=sender or default_sender,
                                emit=lambda *a: self.events.append(a), clock=self.clock, wall=lambda: 1.7e9)

    def test_off_makes_no_network_access(self):
        ping = heartbeat.Pinger(lambda: {"url": "", "interval": 60, "mode": "auto"}, lambda: "up")
        with NoNetwork() as net:
            for _ in range(5):
                self.assertFalse(ping.tick())
            stop = threading.Event()
            thread = threading.Thread(target=heartbeat.run, args=(ping, stop, 0.005))
            thread.start()
            threading.Event().wait(0.1)
            stop.set()
            thread.join(2)
        self.assertEqual(net.calls, [])
        status = ping.status(full=True)
        self.assertFalse(status["enabled"])
        self.assertEqual(status["url"], "")
        with self.assertRaises(heartbeat.PingError):
            ping.test()

    def test_interval(self):
        ping = self.make(interval=60)
        self.assertTrue(ping.tick())
        self.clock.t += 59
        self.assertFalse(ping.tick())
        self.clock.t += 1
        self.assertTrue(ping.tick())
        self.assertEqual(len(self.sent), 2)
        self.cfg["interval"] = 1  # unter dem Minimum: 30 s
        self.clock.t += 29
        self.assertFalse(ping.tick())
        self.clock.t += 1
        self.assertTrue(ping.tick())

    def test_new_url_pings_at_once(self):
        ping = self.make()
        ping.tick()
        self.cfg["url"] = "https://w2.example/hb"
        self.assertTrue(ping.tick())
        self.assertEqual(self.sent[-1][0], "https://w2.example/hb")

    def test_state_down_and_state_errors(self):
        ping = self.make(state="down")
        ping.tick()
        self.assertEqual(self.sent[-1][1], "down")

        def broken():
            raise RuntimeError("kaputt")

        ping = self.make(state=broken)
        ping.tick()
        self.assertEqual(self.sent[-1][1], "down", "Zustand unbekannt = lieber kritisch")
        self.assertEqual(ping.status()["last_sent"], "fail")

    def test_failures_raise_one_event_and_recovery(self):
        fail = {"on": True}

        def sender(u, s, m):
            if fail["on"]:
                raise heartbeat.PingError("Zeitüberschreitung (5 s)")
            return "up"

        ping = self.make(sender=sender)
        for _ in range(5):
            ping.tick(force=True)
        status = ping.status()
        self.assertEqual(status["failures"], 5)
        self.assertEqual(status["error"], "Zeitüberschreitung (5 s)")
        self.assertEqual(len(self.events), 1)
        kind, level, title, data, source = self.events[0]
        self.assertEqual((kind, level), ("heartbeat", "warn"))
        self.assertNotIn("w.example", json.dumps([title, data]))
        fail["on"] = False
        ping.tick(force=True)
        self.assertEqual(len(self.events), 2)
        self.assertEqual(self.events[1][1], "info")
        self.assertTrue(self.events[1][3]["resolves"])
        self.assertIsNone(ping.status()["error"])

    def test_test_button_rate_limited(self):
        ping = self.make()
        ping.test()
        with self.assertRaises(heartbeat.TestRateLimited):
            ping.test()
        self.clock.t += heartbeat.TEST_GAP
        ping.test()
        self.assertEqual(len(self.sent), 2)

    def test_status_hides_url(self):
        ping = self.make(url="https://hc-ping.com/0a1b2c3d-geheim")
        ping.tick()
        self.assertNotIn("geheim", json.dumps(ping.status()))
        self.assertNotIn("url", ping.status())
        self.assertEqual(ping.status(full=True)["url"], "https://hc-ping.com/…")
        self.assertEqual(ping.status()["flavor"], "healthchecks")
        self.assertIsNotNone(ping.status()["next"])


class SecretTest(unittest.TestCase):
    URL = "https://hc-ping.com/0a1b2c3d-geheim"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(settings, "DATA_DIR", self.tmp.name),
                        mock.patch.object(settings, "SETTINGS_FILE", os.path.join(self.tmp.name, "settings.json"))]
        for p in self.patches:
            p.start()
        settings.save({"heartbeat_url": self.URL, "heartbeat_interval": 120})

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_masked_for_read_keys(self):
        self.assertIn("heartbeat_url", settings.MASKED_FOR_READ)
        masked = settings.public_schema(masked=True)
        field = next(f for f in masked["fields"] if f["key"] == "heartbeat_url")
        self.assertEqual(field["value"], "https://hc-ping.com/…")
        self.assertNotIn("geheim", json.dumps(masked))
        exported = settings.export_values(masked=True)
        self.assertNotIn("geheim", json.dumps(exported))
        self.assertIn("heartbeat_url", exported["masked"])
        full = settings.export_values()
        self.assertEqual(full["values"]["heartbeat_url"], self.URL)

    def test_backup_leaves_it_out(self):
        self.assertIn("heartbeat_url", backup.SECRET_SETTINGS)
        part = backup.settings_part()
        self.assertNotIn("heartbeat_url", part["values"])
        self.assertIn("heartbeat_url", part["omitted"])
        self.assertEqual(part["values"]["heartbeat_interval"], 120)

    def test_diagnostics_only_says_set(self):
        out = diagnostics._collect_settings({}, {})
        self.assertEqual(out["values"]["heartbeat_url"], "gesetzt")
        self.assertNotIn("geheim", json.dumps(out))


class EventKindTest(unittest.TestCase):
    def test_kind_known_and_resolving(self):
        self.assertIn("heartbeat", events.KINDS)
        self.assertIn("heartbeat", notify.RESOLVING_KINDS)
        self.assertIn("heartbeat", notify.KIND_LABELS)


class RouteTest(unittest.TestCase):
    """GET /api/notify zeigt den Zustand (Adresse gekürzt), POST …/heartbeat/test nur mit Verwaltungsrecht."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123", **LOOPBACK}),
            mock.patch.object(server, "heartbeat_state", lambda: "up"),
            mock.patch.object(heartbeat, "PINGER", None),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("WEB_READONLY", None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.read_id, cls.read_key = apikeys.create("Lesen", "read")
        cls.admin_id, cls.admin_key = apikeys.create("Verwalten", "admin")

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    def basic(self):
        return {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode(), "X-NTP-GUI": "1"}

    def test_routes(self):
        with Recorder() as rec:
            settings.save({"heartbeat_url": rec.url("/api/push/geheim")})
            self.addCleanup(settings.save, {"heartbeat_url": ""})
            status, _ = self.request("POST", "/api/v1/notify/heartbeat/test", {}, self.bearer(self.read_key))
            self.assertEqual(status, 403)
            self.assertEqual(rec.hits, [])
            status, payload = self.request("POST", "/api/notify/heartbeat/test", {}, self.basic())
            self.assertEqual(status, 200, payload)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["heartbeat"]["last_sent"], "up")
            self.assertNotIn("geheim", json.dumps(payload))
            status, payload = self.request("POST", "/api/notify/heartbeat/test", {}, self.basic())
            self.assertEqual(status, 429)
            self.assertEqual([h["path"] for h in rec.hits], ["/api/push/geheim?status=up&msg=OK"])
            status, payload = self.request("GET", "/api/notify", headers=self.basic())
            self.assertEqual(status, 200)
            self.assertTrue(payload["heartbeat"]["enabled"])
            self.assertTrue(payload["heartbeat"]["url"].endswith("/…"))
            self.assertNotIn("geheim", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
