"""Studiouhr B4: On-Air/REC-Signal der Vollbild-Uhr.

  * clocksignal.py: feste Zustände, Ablaufzeit, signal_rev, Prüfung der Anfrage, Rate-Limit.
  * Recht „clock“ der API-Schlüssel: setzt nur das Signal, liest nichts und ändert sonst nichts.
  * Am echten HTTP-Handler: ohne Schlüssel 401, falsches Recht 403, Werte außerhalb der Liste 400, zu viele Anfragen
    429; Anmeldung nur mit Pflicht-Kopf; /api/v1/time meldet signal und signal_rev – öffentlich nur den festen Wert.
  * Protokoll: Wechsel mit Kennung des Schlüssels, ohne Adresse des Aufrufers und ohne Namen des Schlüssels.
  * Der Zustand steht nur im Speicher: keine Einstellung, nichts in der Sicherung.
  * Last: 20 Bildschirme im Sekundentakt gegen den Testserver, p95 der Antwortzeit unter 50 ms.
  * Uhr: Parameter signal in Schema, Server-Liste, Baukasten und Doku; reine Funktionen aus clockkit.js mit Node.
"""

import base64
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, fake_hostnames, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import apiv1  # noqa: E402
import backup  # noqa: E402
import clockprofiles  # noqa: E402
import clocksignal  # noqa: E402
import events  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

PATH = "/api/v1/clock/signal"
TRACKING = {"synchronised": True, "stratum": 2, "ref_name": "nas.fritz.box", "root_delay": 0.001,
            "root_dispersion": 0.0002, "system_time_offset": 0.0, "leap_status": "Normal"}


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def run_node(code: str):
    kit = json.dumps((JS / "clockkit.js").as_uri())
    link = json.dumps((JS / "clocklink.js").as_uri())
    script = f"import * as k from {kit};\nimport * as l from {link};\n{code}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class ZustandTest(unittest.TestCase):
    def test_feste_liste(self):
        self.assertEqual(clocksignal.STATES, ("off", "on_air", "rec"))

    def test_anfrage_pruefen(self):
        self.assertEqual(clocksignal.parse({"state": "on_air"}), ("on_air", None))
        self.assertEqual(clocksignal.parse({"state": "rec", "ttl": 60}), ("rec", 60))
        self.assertEqual(clocksignal.parse({"state": "rec", "ttl": None}), ("rec", None))
        self.assertEqual(clocksignal.parse({"state": "off", "ttl": 60}), ("off", None), "aus läuft nicht ab")
        self.assertEqual(clocksignal.parse({"state": "on_air", "ttl": clocksignal.TTL_MAX}), ("on_air", 86400))
        bad = [{}, {"state": None}, {"state": "ON_AIR"}, {"state": "onair"}, {"state": "standby"}, {"state": "on_air\n"},
               {"state": " rec"}, {"state": ["rec"]}, {"state": 1}, {"state": True}, {"state": "<b>rec</b>"},
               {"state": "on_air", "ttl": 0}, {"state": "on_air", "ttl": -5}, {"state": "on_air", "ttl": 86401},
               {"state": "on_air", "ttl": "60"}, {"state": "on_air", "ttl": 1.5}, {"state": "on_air", "ttl": True},
               {"state": "on_air", "text": "Sendung"}, {"state": "on_air", "label": "x"}, {"signal": "on_air"},
               ["on_air"], "on_air", None]
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(clocksignal.SignalError):
                    clocksignal.parse(value)

    def test_setzen_und_rev(self):
        signal = clocksignal.Signal(FakeClock())
        first = signal.read()
        self.assertEqual((first["signal"], first["expired"]), ("off", False))
        self.assertRegex(first["signal_rev"], r"\A[0-9a-f]{12}\Z")
        on = signal.set("on_air")
        self.assertEqual((on["signal"], on["expires_in"], on["changed"], on["expired"]), ("on_air", None, True, False))
        self.assertNotEqual(on["signal_rev"], first["signal_rev"])
        again = signal.set("on_air")
        self.assertFalse(again["changed"])
        self.assertEqual(again["signal_rev"], on["signal_rev"], "derselbe Zustand: derselbe Stand")
        rec = signal.set("rec")
        self.assertEqual(signal.read()["signal"], "rec")
        off = signal.set("off")
        self.assertEqual(len({first["signal_rev"], on["signal_rev"], rec["signal_rev"], off["signal_rev"]}), 4)
        with self.assertRaises(clocksignal.SignalError):
            signal.set("standby")
        self.assertEqual(signal.read()["signal"], "off")

    def test_rev_nach_neustart_anders(self):
        self.assertNotEqual(clocksignal.Signal().read()["signal_rev"], clocksignal.Signal().read()["signal_rev"])

    def test_ablaufzeit(self):
        clock = FakeClock()
        signal = clocksignal.Signal(clock)
        on = signal.set("on_air", 30)
        self.assertEqual(on["expires_in"], 30)
        clock.now += 29.9
        self.assertEqual(signal.read(), {"signal": "on_air", "signal_rev": on["signal_rev"], "expired": False, "expired_by": None})
        clock.now += 0.2
        gone = signal.read()
        self.assertEqual((gone["signal"], gone["expired"]), ("off", True))
        self.assertNotEqual(gone["signal_rev"], on["signal_rev"])
        self.assertFalse(signal.read()["expired"], "nur einmal gemeldet")
        # Derselbe Zustand noch einmal: Die Ablaufzeit beginnt neu; ohne ttl bleibt er stehen.
        signal.set("rec", 10)
        clock.now += 8
        first = signal.read()["signal_rev"]
        again = signal.set("rec", 10)
        self.assertFalse(again["changed"])
        self.assertNotEqual(again["signal_rev"], first, "neue Ablaufzeit: neuer Stand, damit Anzeigen sie nicht fortschreiben")
        clock.now += 8
        self.assertEqual(signal.read()["signal"], "rec")
        self.assertIsNone(signal.set("rec")["expires_in"])
        clock.now += 1e6
        self.assertEqual(signal.read()["signal"], "rec")
        # Abgelaufen und neu gesetzt: ein Wechsel, kein „unverändert“.
        signal.set("on_air", 5)
        clock.now += 6
        late = signal.set("on_air")
        self.assertEqual((late["changed"], late["expired"]), (True, True))
        # Abgelaufen und dann „off“: kein Wechsel mehr, aber der Ablauf wird gemeldet – genau einmal.
        signal.set("rec", 5)
        clock.now += 6
        off = signal.set("off")
        self.assertEqual((off["signal"], off["changed"], off["expired"]), ("off", False, True))
        self.assertFalse(signal.set("off")["expired"])
        self.assertFalse(signal.read()["expired"])

    def test_rate_limit(self):
        clock = FakeClock()
        limit = clocksignal.RateLimit(10, clock)
        self.assertEqual([limit.allow("a") for _ in range(12)], [True] * 10 + [False] * 2)
        self.assertTrue(limit.allow("b"), "je Kennung getrennt")
        clock.now += 0.5
        self.assertFalse(limit.allow("a"), "dieselbe Sekunde: weiter gesperrt")
        clock.now += 0.5
        self.assertEqual(sum(limit.allow("a") for _ in range(30)), 10, "nach einer Sekunde wieder zehn")
        clock.now += 60
        self.assertEqual(sum(limit.allow("a") for _ in range(30)), 10, "eine Pause spart nichts an")
        # In keiner Sekunde – wo immer sie beginnt – mehr als zehn: Dauerfeuer in Schritten von 1 ms über 3 s.
        clock.now += 5
        start, times = clock.now, []
        for step in range(3000):
            clock.now = start + step / 1000
            if limit.allow("a"):
                times.append(clock.now)
        self.assertEqual(len(times), 30)
        for i, t0 in enumerate(times):
            self.assertLessEqual(sum(1 for t in times[i:] if t - t0 < 1.0), 10)
        # Abgelehnte Anfragen verlängern die Sperre nicht.
        limit.reset()
        for _ in range(50):
            limit.allow("a")
        clock.now += 1.0
        self.assertTrue(limit.allow("a"))
        for i in range(clocksignal.RATE_BUCKETS_MAX + 50):
            limit.allow(f"k{i}")
        self.assertLessEqual(len(limit._buckets), clocksignal.RATE_BUCKETS_MAX)

    def test_nur_im_speicher(self):
        source = (ROOT / "app" / "clocksignal.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"^\s*(import|from)\s+(settings|store|backup|sqlite3|os|pathlib)\b", "kein Speichern")
        self.assertNotRegex(source, r"\bopen\(")
        self.assertFalse([key for key in settings.FIELDS if "signal" in key], "keine Einstellung – nichts für die Sicherung")
        self.assertNotIn("clocksignal", (ROOT / "app" / "backup.py").read_text(encoding="utf-8"))


class RechtTest(unittest.TestCase):
    def test_recht_clock(self):
        self.assertIn("clock", apikeys.SCOPES)
        self.assertTrue(apikeys.SCOPE_LABELS["clock"])
        for method in ("GET", "HEAD", "POST", "PUT", "DELETE"):
            self.assertFalse(apikeys.allows("clock", method), method)
        self.assertTrue(apikeys.allows("read", "GET"))
        self.assertTrue(apikeys.allows("admin", "POST"))

    def test_endpunkt_beschrieben(self):
        self.assertEqual(apiv1.required_scope("POST", PATH), "clock")
        self.assertEqual(apiv1.required_scope("POST", PATH + "/"), "clock")
        self.assertEqual(apiv1.required_scope("GET", PATH), "read", "lesen geht dort nicht mit dem Recht clock")
        self.assertEqual(apiv1.required_scope("POST", "/api/v1/clock/profile"), "admin")
        entry = next(e for e in apiv1.describe()["endpoints"] if e["path"] == PATH)
        self.assertEqual((entry["method"], entry["scope"]), ("POST", "clock"))
        self.assertEqual(entry["response_keys"], ["signal", "signal_rev", "expires_in"])
        time_entry = next(e for e in apiv1.describe()["endpoints"] if e["path"] == "/api/v1/time")
        self.assertLessEqual({"signal", "signal_rev"}, set(time_entry["response_keys"]))
        self.assertEqual([e["path"] for e in apiv1.ENDPOINTS if e["scope"] == "clock"], ["/clock/signal"])

    def test_nicht_oeffentlich_schreibbar(self):
        self.assertNotIn(PATH, server.CLOCK_PUBLIC_PATHS)


class SignalHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
            mock.patch.object(server.chrony, "tracking", return_value=dict(TRACKING)),
        ]
        for patch in cls.patches:
            patch.start()
        for name in ("WEB_READONLY", "CLOCK_PUBLIC"):
            os.environ.pop(name, None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.read_id, cls.read_key = apikeys.create("Lesen", "read")
        cls.admin_id, cls.admin_key = apikeys.create("Verwalten", "admin")
        cls.clock_id, cls.clock_key = apikeys.create("Regiepult Studio 2", "clock")
        cls.other_id, cls.other_key = apikeys.create("Zweites Pult", "clock")

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

    def setUp(self):
        fake_hostnames(self)
        self.clock = FakeClock()
        for patch in (mock.patch.object(server, "CLOCK_SIGNAL", clocksignal.Signal(self.clock)),
                      mock.patch.object(server, "CLOCK_SIGNAL_RATE", clocksignal.RateLimit()),
                      mock.patch.dict(server._SIGNAL_AUDIT, {"t": None, "tokens": server.SIGNAL_AUDIT_BURST, "pending": None,
                                                             "skipped": 0, "keys": []})):
            patch.start()
            self.addCleanup(patch.stop)
        server._CLOCK_CACHE.update(t=None, tracking=None)
        for name in ("audit", "expiry"):
            self.addCleanup(server._signal_timer, name, None)

    def request(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        hdrs = {"Host": "example.com", **(headers or {})}
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        text = resp.read()
        out_headers = dict(resp.getheaders())
        conn.close()
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
        return resp.status, payload, out_headers

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def basic(csrf=True):
        headers = {"Authorization": "Basic " + base64.b64encode(b"admin:geheim123").decode()}
        if csrf:
            headers["X-NTP-GUI"] = "1"
        return headers

    def set_public(self, value=True):
        patcher = mock.patch.dict(os.environ, {"CLOCK_PUBLIC": "true" if value else "false"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def time(self, headers=None):
        return self.request("GET", "/api/v1/time", headers=headers if headers is not None else self.basic())[1]

    # --- Rechte ---------------------------------------------------------------------------------------------
    def test_ohne_schluessel_401(self):
        self.assertEqual(self.request("POST", PATH, {"state": "on_air"})[0], 401)
        status, _body, headers = self.request("POST", PATH, {"state": "on_air"}, self.bearer("ntpg_" + "x" * 32))
        self.assertEqual(status, 401)
        self.assertIn("Bearer", headers.get("WWW-Authenticate", ""))
        self.assertEqual(self.request("POST", PATH, {"state": "on_air"}, {"X-NTP-GUI": "1"})[0], 401)
        self.set_public(True)
        self.assertEqual(self.request("POST", PATH, {"state": "on_air"}, {"X-NTP-GUI": "1"})[0], 401,
                         "die Uhr ohne Anmeldung liest nur")
        self.assertEqual(self.time()["signal"], "off")

    def test_falsches_recht_403(self):
        status, payload, _h = self.request("POST", PATH, {"state": "on_air"}, self.bearer(self.read_key))
        self.assertEqual(status, 403)
        self.assertEqual(payload["scope_required"], "clock")
        self.assertEqual(self.time()["signal"], "off")

    def test_recht_clock_setzt(self):
        before = self.time()
        status, payload, headers = self.request("POST", PATH, {"state": "on_air"}, self.bearer(self.clock_key))
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"signal", "signal_rev", "expires_in"})
        self.assertEqual((payload["signal"], payload["expires_in"]), ("on_air", None))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        after = self.time()
        self.assertEqual((after["signal"], after["signal_rev"]), ("on_air", payload["signal_rev"]))
        self.assertNotEqual(before["signal_rev"], after["signal_rev"])
        self.assertEqual(self.request("POST", PATH, {"state": "rec", "ttl": 90}, self.bearer(self.clock_key))[1]["expires_in"], 90)
        self.assertEqual(self.time()["signal"], "rec")
        self.assertEqual(self.request("POST", PATH, {"state": "off"}, self.bearer(self.admin_key))[0], 200,
                         "ein Verwaltungsschlüssel darf es auch")
        self.assertEqual(self.time()["signal"], "off")

    def test_recht_clock_darf_sonst_nichts(self):
        key = self.bearer(self.clock_key)
        for path in ("/api/v1/status", "/api/status", "/api/v1/settings", "/api/v1/events", "/api/v1/time",
                     "/api/v1/clock/profile?p=studio", "/api/v1", "/metrics", "/", "/clock", "/static/js/app.js",
                     "/api/apikeys", "/api/v1/instance", "/api/v1/backup", PATH):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path, headers=key)[0], 403)
        for path, body in (("/api/v1/settings", {"values": {"web_title": "x"}}), ("/api/v1/reload", {}),
                           ("/api/apikeys", {"name": "x", "scope": "admin"}), ("/api/auth", {"clear": True}),
                           ("/api/v1/setup", {"action": "done"}), ("/api/v1/recording", {"action": "stop"}),
                           ("/api/v1/clock/profile", {}), ("/api/v1/clock/signal/extra", {"state": "rec"}),
                           ("/api/unbekannt", {})):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, body, key)[0], 403)
        self.assertNotEqual(settings.values().get("web_title"), "x")
        # Mit der Uhr ohne Anmeldung bekommt auch dieser Schlüssel nur die öffentliche Antwort.
        self.set_public(True)
        status, payload, _h = self.request("GET", "/api/v1/time", headers=key)
        self.assertEqual(status, 200)
        self.assertTrue(payload["public"])
        self.assertIsNone(payload["source"])

    def test_anmeldung_nur_mit_pflicht_kopf(self):
        self.assertEqual(self.request("POST", PATH, {"state": "on_air"}, self.basic(csrf=False))[0], 403)
        self.assertEqual(self.time()["signal"], "off")
        foreign = dict(self.basic(), Origin="http://evil.example")
        self.assertEqual(self.request("POST", PATH, {"state": "on_air"}, foreign)[0], 403)
        self.assertEqual(self.request("POST", PATH, raw=b'{"state":"on_air"}',
                                      headers=dict(self.basic(), **{"Content-Type": "text/plain"}))[0], 403)
        self.assertEqual(self.request("POST", PATH, {"state": "on_air"}, self.basic())[0], 200)
        self.assertEqual(self.time()["signal"], "on_air")

    def test_gesperrt_mit_web_readonly(self):
        with mock.patch.dict(os.environ, {"WEB_READONLY": "true"}):
            self.assertEqual(self.request("POST", PATH, {"state": "on_air"}, self.bearer(self.clock_key))[0], 403)
        self.assertEqual(self.time()["signal"], "off")

    # --- Werte ----------------------------------------------------------------------------------------------
    def test_werte_ausserhalb_der_liste_400(self):
        key = self.bearer(self.other_key)
        bad = [{}, {"state": "ON"}, {"state": "standby"}, {"state": "on_air\n"}, {"state": ["rec"]}, {"state": 1},
               {"state": "on_air", "ttl": 0}, {"state": "on_air", "ttl": "60"}, {"state": "on_air", "ttl": 86401},
               {"state": "on_air", "ttl": True}, {"state": "on_air", "text": "Sendung läuft"}]
        for body in bad:
            with self.subTest(body=body):
                server.CLOCK_SIGNAL_RATE.reset()
                status, payload, _h = self.request("POST", PATH, body, key)
                self.assertEqual(status, 400)
                self.assertEqual(payload["states"], ["off", "on_air", "rec"])
        server.CLOCK_SIGNAL_RATE.reset()
        self.assertEqual(self.request("POST", PATH, raw=b"[1]", headers=key)[0], 400)
        self.assertEqual(self.request("POST", PATH, raw=b"{kaputt", headers=key)[0], 400)
        self.assertEqual(self.time()["signal"], "off")

    def test_rate_limit_429(self):
        key = self.bearer(self.clock_key)
        with mock.patch.object(server, "CLOCK_SIGNAL_RATE", clocksignal.RateLimit(10, FakeClock())):
            codes = [self.request("POST", PATH, {"state": "on_air" if i % 2 else "rec"}, key) for i in range(14)]
            self.assertEqual([c[0] for c in codes], [200] * 10 + [429] * 4)
            self.assertEqual(codes[-1][2].get("Retry-After"), "1")
            self.assertIn("error", codes[-1][1])
            self.assertEqual(self.request("POST", PATH, {"state": "off"}, self.bearer(self.other_key))[0], 200,
                             "je Schlüssel getrennt")
            self.assertEqual(self.request("POST", PATH, {"state": "off"}, self.basic())[0], 200)
            # Auch ungültige Anfragen zählen mit.
            server.CLOCK_SIGNAL_RATE.reset()
            mixed = [self.request("POST", PATH, {"state": "x"}, key)[0] for _ in range(12)]
            self.assertEqual(mixed, [400] * 10 + [429] * 2)
        self.assertEqual(clocksignal.RATE_PER_SECOND, 10)

    def test_ablaufzeit_am_endpunkt(self):
        self.request("POST", PATH, {"state": "on_air", "ttl": 5}, self.bearer(self.clock_key))
        rev = self.time()["signal_rev"]
        self.clock.now += 4
        self.assertEqual(self.time()["signal"], "on_air")
        self.clock.now += 2
        late = self.time()
        self.assertEqual(late["signal"], "off")
        self.assertNotEqual(late["signal_rev"], rev)

    # --- Lesen ----------------------------------------------------------------------------------------------
    def test_oeffentlich_nur_der_zustand(self):
        self.set_public(True)
        self.request("POST", PATH, {"state": "rec", "ttl": 600}, self.bearer(self.clock_key))
        status, payload, _h = self.request("GET", "/api/v1/time", headers={"Host": "uhr.example.org"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["public"])
        self.assertEqual(payload["signal"], "rec")
        self.assertRegex(payload["signal_rev"], r"\A[0-9a-f]{12}\Z")
        text = json.dumps(payload)
        for secret in (self.clock_id, "Regiepult", "Studio 2", "fritz", "ttl", "expires", "600", "api_key"):
            self.assertNotIn(secret, text)
        self.assertEqual({k for k in payload if "signal" in k}, {"signal", "signal_rev"})
        self.assertEqual(self.request("GET", PATH, headers={"Host": "uhr.example.org"})[0], 401)

    def test_time_payload_nur_feste_werte(self):
        with mock.patch.object(server, "_clock_tracking", return_value=dict(TRACKING)):
            self.assertEqual(server.time_payload(1.0, public=True)["signal"], "off")
            broken = mock.Mock()
            broken.read.side_effect = RuntimeError("kaputt")
            with mock.patch.object(server, "CLOCK_SIGNAL", broken):
                out = server.time_payload(1.0, public=True)
            self.assertEqual((out["signal"], out["signal_rev"]), ("off", ""), "ein Fehler hält die Uhr nie auf")

    # --- Protokoll ------------------------------------------------------------------------------------------
    def audit(self):
        return [row for row in events.query(kinds=["settings"], limit=200) if "On-Air-Signal" in row["title"]]

    def test_protokoll_ohne_adresse_und_namen(self):
        before = len(self.audit())
        self.request("POST", PATH, {"state": "on_air", "ttl": 120}, self.bearer(self.clock_key))
        rows = self.audit()
        self.assertEqual(len(rows), before + 1)
        row = rows[0]
        self.assertEqual(row["title"], "On-Air-Signal der Uhr: ON AIR")
        self.assertEqual(row["data"], {"state": "on_air", "ttl": 120, "api_key": self.clock_id})
        self.assertEqual(row["source"], "api")
        text = repr(row)
        for secret in ("127.0.0.1", "example.com", "Regiepult", "Studio 2", self.clock_key):
            self.assertNotIn(secret, text)
        # Derselbe Zustand mit derselben Ablaufzeit (keine): kein neuer Eintrag.
        self.request("POST", PATH, {"state": "off"}, self.bearer(self.clock_key))
        count = len(self.audit())
        self.request("POST", PATH, {"state": "off"}, self.bearer(self.clock_key))
        self.request("POST", PATH, {"state": "off", "ttl": 30}, self.bearer(self.clock_key))
        self.assertEqual(len(self.audit()), count)

    def test_protokoll_anmeldung_und_ablauf(self):
        before = len(self.audit())
        self.request("POST", PATH, {"state": "rec", "ttl": 5}, self.basic())
        row = self.audit()[0]
        self.assertEqual((row["title"], row["source"], row["data"]), ("On-Air-Signal der Uhr: REC", "web", {"state": "rec", "ttl": 5}))
        self.clock.now += 6
        self.time()
        rows = self.audit()
        self.assertEqual(len(rows), before + 2)
        self.assertEqual((rows[0]["title"], rows[0]["data"], rows[0]["source"]),
                         ("On-Air-Signal der Uhr: aus", {"state": "off", "reason": "ttl", "set_by": "web"}, "system"))

    def test_protokoll_ablauf_ohne_abfrage(self):
        # Kein Bildschirm fragt ab: Die Ablaufzeit verstreicht, dann kommt „off“. Der Ablauf steht trotzdem im Protokoll.
        key = self.bearer(self.clock_key)
        self.request("POST", PATH, {"state": "on_air", "ttl": 1}, key)
        before = len(self.audit())
        self.clock.now += 2.5
        status, payload, _h = self.request("POST", PATH, {"state": "off"}, key)
        self.assertEqual((status, payload["signal"]), (200, "off"))
        for name in ("expired", "expired_by", "changed", "ttl_changed"):
            self.assertNotIn(name, payload)
        rows = self.audit()
        self.assertEqual(len(rows), before + 1)
        self.assertEqual((rows[0]["title"], rows[0]["data"], rows[0]["source"]),
                         ("On-Air-Signal der Uhr: aus", {"state": "off", "reason": "ttl", "set_by": "api",
                                                         "api_key": self.clock_id}, "system"))
        # Abgelaufen und gleich neu gesetzt: erst der Ablauf, dann der neue Zustand.
        self.request("POST", PATH, {"state": "rec", "ttl": 1}, key)
        self.clock.now += 2
        count = len(self.audit())
        self.request("POST", PATH, {"state": "rec"}, key)
        rows = self.audit()
        self.assertEqual(len(rows), count + 2)
        self.assertEqual(rows[1]["data"], {"state": "off", "reason": "ttl", "set_by": "api", "api_key": self.clock_id})
        self.assertEqual(rows[0]["data"], {"state": "rec", "api_key": self.clock_id})

    def test_protokoll_ablaufzeit_bei_gleichem_zustand(self):
        # Die Anmeldung setzt ON AIR ohne Ablaufzeit, ein Schlüssel hängt eine Ablaufzeit von 1 s an: Das Signal geht
        # aus. Beides steht mit der Kennung des Schlüssels im Protokoll – der Eintrag und der Ablauf.
        self.request("POST", PATH, {"state": "on_air"}, self.basic())
        before = len(self.audit())
        status, payload, _h = self.request("POST", PATH, {"state": "on_air", "ttl": 1}, self.bearer(self.clock_key))
        self.assertEqual((status, payload), (200, {"signal": "on_air", "signal_rev": payload["signal_rev"], "expires_in": 1}))
        rows = self.audit()
        self.assertEqual(len(rows), before + 1, "derselbe Zustand mit neuer Ablaufzeit wird eingetragen")
        self.assertEqual((rows[0]["title"], rows[0]["source"], rows[0]["data"]),
                         ("On-Air-Signal der Uhr: ON AIR – Ablaufzeit geändert", "api",
                          {"state": "on_air", "ttl": 1, "api_key": self.clock_id, "reason": "ttl_changed"}))
        self.clock.now += 2.5
        self.assertEqual(self.time()["signal"], "off")
        rows = self.audit()
        self.assertEqual(len(rows), before + 2)
        self.assertEqual((rows[0]["source"], rows[0]["data"]),
                         ("system", {"state": "off", "reason": "ttl", "set_by": "api", "api_key": self.clock_id}))
        # Verlängern und Aufheben einer laufenden Ablaufzeit: je ein Eintrag, der letzte ohne ttl.
        self.request("POST", PATH, {"state": "rec", "ttl": 60}, self.basic())
        count = len(self.audit())
        self.request("POST", PATH, {"state": "rec", "ttl": 86400}, self.bearer(self.admin_key))
        self.request("POST", PATH, {"state": "rec"}, self.bearer(self.clock_key))
        rows = self.audit()
        self.assertEqual(len(rows), count + 2)
        self.assertEqual(rows[1]["data"]["ttl"], 86400)
        self.assertEqual((rows[0]["title"], rows[0]["data"]),
                         ("On-Air-Signal der Uhr: REC – Ablaufzeit aufgehoben",
                          {"state": "rec", "api_key": self.clock_id, "reason": "ttl_changed"}))
        # Nach dem Aufheben läuft nichts mehr ab; wer die Ablaufzeit gesetzt hat, steht nicht in /api/v1/time.
        self.clock.now += 90000
        payload = self.time()
        self.assertEqual(payload["signal"], "rec")
        self.assertNotIn(self.clock_id, json.dumps(payload))
        self.assertNotIn("expired", json.dumps(payload))

    def test_signal_merkt_wer_die_ablaufzeit_setzt(self):
        clock = FakeClock()
        signal = clocksignal.Signal(clock)
        first = signal.set("on_air", None, {"source": "web"})
        self.assertEqual((first["changed"], first["ttl_changed"], first["expired_by"]), (True, False, None))
        second = signal.set("on_air", 10, "zweiter")
        self.assertEqual((second["changed"], second["ttl_changed"]), (False, True))
        self.assertNotEqual(first["signal_rev"], second["signal_rev"])
        same = signal.set("on_air", 10, "dritter")
        self.assertEqual((same["changed"], same["ttl_changed"], same["signal_rev"]), (False, False, second["signal_rev"]))
        clock.now += 11
        now = signal.read()
        self.assertEqual((now["signal"], now["expired"], now["expired_by"]), ("off", True, "zweiter"))
        self.assertEqual((signal.read()["expired"], signal.read()["expired_by"]), (False, None))
        signal.set("rec", 5, "vierter")
        clock.now += 6
        late = signal.set("rec", None, "fünfter")
        self.assertEqual((late["expired"], late["expired_by"], late["changed"], late["ttl_changed"]), (True, "vierter", True, False))
        clock.now += 100
        self.assertEqual(signal.read()["expired_by"], None)

    def test_ablauf_zeitgeber(self):
        # Mit Ablaufzeit liest ein Zeitgeber den Zustand, sobald sie um ist; ohne wird er abgestellt.
        with mock.patch.object(server, "CLOCK_SIGNAL", clocksignal.Signal()):
            before = len(self.audit())
            self.request("POST", PATH, {"state": "on_air", "ttl": 1}, self.bearer(self.clock_key))
            self.assertIsNotNone(server._SIGNAL_TIMERS["expiry"])
            deadline = time.monotonic() + 5
            while len(self.audit()) < before + 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            rows = self.audit()
            self.assertEqual(len(rows), before + 2, "„aus“ steht im Protokoll, ohne dass jemand abfragt")
            self.assertEqual(rows[0]["data"], {"state": "off", "reason": "ttl", "set_by": "api", "api_key": self.clock_id})
            self.request("POST", PATH, {"state": "rec", "ttl": 600}, self.bearer(self.clock_key))
            self.assertIsNotNone(server._SIGNAL_TIMERS["expiry"])
            self.request("POST", PATH, {"state": "rec"}, self.bearer(self.clock_key))
            self.assertIsNone(server._SIGNAL_TIMERS["expiry"])

    def test_protokoll_vorrat_und_nachtrag(self):
        # Die ersten Wechsel stehen sofort da; ist der Vorrat leer, kommt je Minute höchstens ein Eintrag dazu: der
        # letzte Stand mit der Zahl der übersprungenen Wechsel und den Kennungen der Schlüssel, die geschaltet haben.
        burst, period = server.SIGNAL_AUDIT_BURST, server.SIGNAL_AUDIT_SECONDS
        self.assertGreaterEqual(period, 60.0)
        before = len(self.audit())
        for i in range(burst):
            server.signal_audit({"state": "off" if i % 2 else "on_air", "source": "api", "api_key": "k1"}, mono=100.0 + i)
        self.assertEqual(len(self.audit()), before + burst, "der Vorrat steht sofort im Protokoll")
        self.assertNotIn("skipped", self.audit()[0]["data"])
        for i in range(9):
            server.signal_audit({"state": "rec" if i % 2 else "off", "source": "api", "api_key": "k2" if i == 3 else "k1"},
                                mono=110.0 + i)
        self.assertEqual(len(self.audit()), before + burst, "schnelle Wechsel füllen das Protokoll nicht")
        self.assertIsNotNone(server._SIGNAL_TIMERS["audit"], "ein Zeitgeber trägt nach, auch wenn niemand abfragt")
        server.signal_audit(None, mono=100.0 + period - 1)
        self.assertEqual(len(self.audit()), before + burst)
        server.signal_audit(None, mono=100.0 + period + 0.1)
        rows = self.audit()
        self.assertEqual(len(rows), before + burst + 1, "der letzte Stand wird nachgetragen")
        self.assertEqual(rows[0]["data"], {"state": "off", "api_key": "k1", "skipped": 8, "api_keys": ["k2"]})
        server.signal_audit(None, mono=100.0 + period + 30)
        self.assertEqual(len(self.audit()), before + burst + 1)
        # Dauerbetrieb im Sekundentakt: ein Eintrag je Minute, nicht je Sekunde.
        count = len(self.audit())
        start = 100.0 + period + 31
        for second in range(600):
            server.signal_audit({"state": "off" if second % 2 else "on_air", "source": "api", "api_key": "k1"}, mono=start + second)
        self.assertLessEqual(len(self.audit()) - count, 600 / period + 1)
        self.assertGreaterEqual(len(self.audit()) - count, 600 / period - 1)
        # Nach einer langen Pause ist der Vorrat wieder voll, aber nie größer als am Anfang.
        count = len(self.audit())
        later = start + 600 + 100 * period
        server.signal_audit(None, mono=later)   # trägt den letzten Stand nach
        later += 100 * period
        count = len(self.audit())
        for i in range(burst + 5):
            server.signal_audit({"state": "off" if i % 2 else "rec", "source": "web"}, mono=later + 1 + i / 10)
        self.assertEqual(len(self.audit()) - count, burst)

    def test_protokoll_nachtrag_zeitgeber(self):
        # Vorrat leer, danach fragt niemand ab: Der Zeitgeber trägt den letzten Stand von selbst nach.
        key = self.bearer(self.clock_key)
        with mock.patch.object(server, "SIGNAL_AUDIT_BURST", 1), mock.patch.object(server, "SIGNAL_AUDIT_SECONDS", 1.0):
            server._SIGNAL_AUDIT.update(t=None, tokens=1)
            before = len(self.audit())
            self.request("POST", PATH, {"state": "rec"}, key)
            self.request("POST", PATH, {"state": "off"}, key)
            self.assertEqual(len(self.audit()), before + 1)
            started = time.monotonic()
            while len(self.audit()) < before + 2 and time.monotonic() - started < 5:
                time.sleep(0.05)
            rows = self.audit()
            self.assertEqual(len(rows), before + 2)
            self.assertLess(time.monotonic() - started, 2.5)
            self.assertEqual((rows[0]["title"], rows[0]["data"]), ("On-Air-Signal der Uhr: aus", {"state": "off", "api_key": self.clock_id}))

    def test_protokoll_verdraengt_keine_anderen_ereignisse(self):
        # Eigenes Kontingent: Von den Einträgen des Signals bleiben nur die neuesten, die übrigen Ereignisse bleiben
        # alle – auch wenn das Signal weit mehr Einträge schreibt, als das Protokoll Zeilen hält.
        self.assertEqual(events._QUOTAS.get(("settings", server.SIGNAL_AUDIT_TITLE)), server.SIGNAL_AUDIT_ROWS)
        self.assertLess(server.SIGNAL_AUDIT_ROWS, events.MAX_ROWS // 10)
        events.emit("api", "info", "API-Schlüssel angelegt: vorher")
        events.emit("settings", "info", "Einstellungen geändert: vorher")
        others = events.count() - len(self.audit())
        with mock.patch.dict(events._QUOTAS, {("settings", server.SIGNAL_AUDIT_TITLE): 20}), \
                mock.patch.object(events, "MAX_ROWS", others + 25), \
                mock.patch.object(server, "SIGNAL_AUDIT_BURST", 10_000), \
                mock.patch.object(events, "PRUNE_EVERY", 50):
            server._SIGNAL_AUDIT.update(t=None, tokens=10_000)
            for i in range(400):
                server.signal_audit({"state": "off" if i % 2 else "on_air", "source": "api", "api_key": "k1"}, mono=1000.0 + i)
            events.prune()
            titles = [row["title"] for row in events.query(limit=1000)]
            self.assertEqual(len(self.audit()), 20)
            self.assertEqual(events.count(), others + 20)
            self.assertIn("API-Schlüssel angelegt: vorher", titles)
            self.assertIn("Einstellungen geändert: vorher", titles)
            self.assertEqual(self.audit()[0]["data"]["state"], "off", "die neuesten bleiben")

    def test_nicht_in_der_sicherung(self):
        self.request("POST", PATH, {"state": "on_air"}, self.bearer(self.clock_key))
        self.assertEqual([name for name in os.listdir(self.tmp.name) if "signal" in name], [], "keine Datei für den Zustand")
        status, payload, _h = self.request("GET", "/api/v1/settings/export", headers=self.basic())
        self.assertEqual(status, 200)
        self.assertNotIn("on_air", json.dumps(payload))
        path = os.path.join(self.tmp.name, "sicherung.tar.gz")
        backup.create(path, "test")
        self.addCleanup(os.unlink, path)
        import tarfile
        with tarfile.open(path) as archive:
            names = archive.getnames()
            text = b"".join(archive.extractfile(m).read() for m in archive.getmembers() if m.isfile() and m.size < 2_000_000)
        self.assertEqual([name for name in names if "signal" in name], [])
        self.assertNotIn(b'"signal"', text)
        self.assertNotIn(b"signal_rev", text)

    # --- Last -----------------------------------------------------------------------------------------------
    @unittest.skipIf(os.environ.get("NTPGUI_SKIP_LOADTEST"), "Lasttest abgeschaltet (NTPGUI_SKIP_LOADTEST)")
    def test_last_20_bildschirme_im_sekundentakt(self):
        """20 Bildschirme fragen /api/v1/time drei Sekunden lang im Sekundentakt ab (versetzt, wie echte Geräte), dabei
        wechselt das Signal. p95 der Antwortzeit unter 50 ms; bei Störung durch andere Last zählt der beste von drei Läufen."""
        self.set_public(True)
        screens, rounds, interval, limit = 20, 3, 1.0, 0.050

        def measure():
            times, errors, seen = [], [], set()
            lock = threading.Lock()
            start = time.monotonic() + 0.2

            def screen(index):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
                try:
                    for n in range(rounds):
                        wait = start + index * interval / screens + n * interval - time.monotonic()
                        if wait > 0:
                            time.sleep(wait)
                        t0 = time.perf_counter()
                        try:
                            conn.request("GET", "/api/v1/time", headers={"Host": "uhr.example.org"})
                            resp = conn.getresponse()
                            payload = json.loads(resp.read())
                            took = time.perf_counter() - t0
                            ok = resp.status == 200 and payload["signal"] in clocksignal.STATES
                        except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
                            took, ok, payload = time.perf_counter() - t0, False, {"error": repr(exc)}
                            conn.close()
                        with lock:
                            times.append(took)
                            seen.add(payload.get("signal"))
                            if not ok:
                                errors.append(payload)
                finally:
                    conn.close()

            threads = [threading.Thread(target=screen, args=(i,), daemon=True) for i in range(screens)]
            for thread in threads:
                thread.start()
            for n in range(rounds * 2):   # das Pult schaltet währenddessen
                time.sleep(interval / 2)
                self.request("POST", PATH, {"state": ("on_air", "rec", "off")[n % 3]}, self.bearer(self.other_key))
            for thread in threads:
                thread.join(30)
            times.sort()
            return times, errors, seen

        best = None
        for _attempt in range(3):
            times, errors, seen = measure()
            self.assertEqual(errors, [])
            self.assertEqual(len(times), screens * rounds)
            self.assertGreaterEqual(len(seen & set(clocksignal.STATES)), 2, "die Bildschirme sehen den Wechsel")
            p95 = times[max(0, int(len(times) * 0.95) - 1)]
            best = p95 if best is None else min(best, p95)
            if best < limit:
                break
        self.assertLess(best, limit, f"p95 {best * 1000:.1f} ms")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class UhrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "app" / "static" / "clock.css").read_text(encoding="utf-8")
        cls.html = (ROOT / "app" / "static" / "clock.html").read_text(encoding="utf-8")

    def test_parameter_an_allen_vier_stellen(self):
        out = run_node("""
          const entry = k.PARAM_SCHEMA.find((e) => e.name === "signal");
          console.log(JSON.stringify({ entry, groups: l.FORM_GROUPS.flatMap((g) => g.names), addressOnly: k.ADDRESS_ONLY,
            skip: l.STORE_SKIP, on: k.parseParams("?signal=1").signal, off: k.parseParams("").signal,
            bad: k.parseParams("?signal=rec"), query: l.buildQuery({ signal: "1" }), none: l.buildQuery({ signal: "0" }),
            profile: l.effectiveQuery({ search: "?p=regie", profile: { signal: "1", design: "studio" } }) }));
        """)
        self.assertEqual(out["entry"], {"name": "signal", "type": "flag", "default": False})
        self.assertEqual(clockprofiles.PARAMS["signal"], ("flag", {}))
        self.assertIn("signal", out["groups"])
        self.assertNotIn("signal", out["addressOnly"], "wirkt auch aus einem Profil")
        self.assertNotIn("signal", out["skip"])
        self.assertTrue(out["on"])
        self.assertFalse(out["off"])
        self.assertEqual((out["bad"]["signal"], out["bad"]["ignored"]), (False, ["signal"]))
        self.assertEqual((out["query"], out["none"]), ("signal=1", ""))
        self.assertEqual(out["profile"], "design=studio&signal=1")
        self.assertEqual(clockprofiles.clean_profile({"params": {"signal": "1"}})["params"], {"signal": "1"})
        with self.assertRaises(clockprofiles.ProfileError):
            clockprofiles.clean_profile({"params": {"signal": "rec"}})
        doc = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        self.assertIn("`signal=1`", doc)
        for lang in ("de", "en"):
            data = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
            self.assertTrue(data["clock"]["link"]["f"]["signal"], lang)

    def test_abfragetakt(self):
        out = run_node("""
          console.log(JSON.stringify([k.pollInterval({ signal: true }), k.pollInterval({ signal: false }), k.pollInterval({}),
            k.pollInterval(), k.pollInterval({ signal: "1" }), k.pollInterval(k.parseParams("?signal=1")),
            k.pollInterval(k.parseParams("?design=studio")), k.POLL_MS, k.SIGNAL_POLL_MS]));
        """)
        self.assertEqual(out, [1000, 5000, 5000, 5000, 5000, 1000, 5000, 5000, 1000])
        self.assertIn("setInterval(poll, kit.pollInterval(params))", self.js)
        self.assertNotRegex(self.js, r"setInterval\(poll, [0-9A-Z_]+\)", "kein fester Takt neben pollInterval")
        self.assertIn("if (state.polling) return;", self.js)

    def test_zustand_und_anzeige(self):
        out = run_node("""
          const v = (o) => k.signalView(o);
          console.log(JSON.stringify({
            states: k.SIGNAL_STATES,
            clean: ["on_air", "rec", "off", "ON_AIR", "standby", "<b>rec</b>", "", null, undefined, 1, true, ["rec"], { a: 1 }].map(k.signalState),
            off: v(), disabled: v({ enabled: false, central: "rec" }), central: v({ enabled: true, central: "rec" }),
            foreign: v({ enabled: true, central: "<img src=x>" }), local: v({ local: true }),
            localDisabled: v({ enabled: false, central: "rec", local: true }),
            both: v({ enabled: true, central: "rec", local: true }),
            centralOffLocal: v({ enabled: true, central: "off", local: true }),
            stale: v({ enabled: true, central: "on_air", sinceOkMs: 10001 }),
            fresh: v({ enabled: true, central: "on_air", sinceOkMs: 10000 }),
            never: v({ enabled: true, central: "on_air", sinceOkMs: Infinity }),
            staleOff: v({ enabled: true, central: "off", sinceOkMs: 99999 }),
            localStale: v({ local: true, sinceOkMs: 99999 }),
            truthy: v({ local: "ja" }),
          }));
        """)
        self.assertEqual(out["states"], list(clocksignal.STATES), "Uhr und Server kennen dieselben Zustände")
        self.assertEqual(out["clean"], ["on_air", "rec", "off"] + ["off"] * 10)
        off = {"state": "off", "local": False, "stale": False}
        self.assertEqual(out["off"], off)
        self.assertEqual(out["disabled"], off, "ohne signal=1 zeigt der Bildschirm das zentrale Signal nicht")
        self.assertEqual(out["central"], {"state": "rec", "local": False, "stale": False})
        self.assertEqual(out["foreign"], off)
        self.assertEqual(out["local"], {"state": "on_air", "local": True, "stale": False})
        self.assertEqual(out["localDisabled"], out["local"])
        self.assertEqual(out["both"], out["central"], "das zentrale Signal geht vor")
        self.assertEqual(out["centralOffLocal"], out["local"])
        self.assertEqual(out["stale"], {"state": "on_air", "local": False, "stale": True})
        self.assertFalse(out["fresh"]["stale"])
        self.assertTrue(out["never"]["stale"])
        self.assertEqual(out["staleOff"], off)
        self.assertEqual(out["localStale"], out["local"], "das lokale Signal hängt nicht am Server")
        self.assertEqual(out["truthy"], off)

    def test_seite_text_und_symbol(self):
        self.assertRegex(self.html, r'<p class="clock-signal" id="signal" data-signal="off" hidden>')
        for part in ('class="clock-signal-icon" aria-hidden="true"', 'id="signal-text"', 'id="signal-note"',
                     '<dt><kbd>O</kbd></dt><dd data-i18n="clock.keys.o">'):
            self.assertIn(part, self.html)
        # Text nur aus dem Sprachkatalog (fester Zustand), nie aus der Antwort.
        start = self.js.index("function renderSignal()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("kit.signalView(", body)
        self.assertIn("t(`clock.signal.${view.state}`)", body)
        self.assertNotRegex(body, r"innerHTML|status\.signal_rev|\.style\.")
        self.assertIn("o: toggleSignal,", self.js)
        for lang in ("de", "en"):
            clock = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            with self.subTest(lang=lang):
                self.assertEqual(clock["signal"], {"on_air": "ON AIR", "rec": "REC"})
                self.assertEqual(set(clock["signal_say"]), set(clocksignal.STATES))
                for key in ("signal_local", "signal_stale", "hint_signal_on", "hint_signal_off"):
                    self.assertTrue(clock[key], key)
                self.assertTrue(clock["keys"]["o"])
        core = run_node(f"""
          const i = await import({json.dumps((JS / "i18n.js").as_uri())});
          console.log(JSON.stringify([i.CORE_DE.clock.signal, i.CORE_DE.clock.signal_stale, i.CORE_DE.clock.keys.o]));
        """)
        self.assertEqual(core[0], {"on_air": "ON AIR", "rec": "REC"}, "auch ohne Sprachkatalog steht der Text da")
        self.assertTrue(core[1] and core[2])

    def test_taste_o_neben_zentralem_signal(self):
        out = run_node("""
          const g = (o) => k.signalToggle(o);
          console.log(JSON.stringify({
            on: g(), off: g({ local: true }), plain: g({ enabled: false, central: "rec" }),
            blocked: g({ enabled: true, central: "rec" }), blockedLocal: g({ enabled: true, central: "on_air", local: true }),
            centralOff: g({ enabled: true, central: "off" }), foreign: g({ enabled: true, central: "standby", local: true }),
          }));
        """)
        self.assertEqual(out["on"], {"local": True, "blocked": False})
        self.assertEqual(out["off"], {"local": False, "blocked": False})
        self.assertEqual(out["plain"], {"local": True, "blocked": False}, "ohne signal=1 zählt das zentrale Signal nicht")
        self.assertEqual(out["blocked"], {"local": False, "blocked": True})
        self.assertEqual(out["blockedLocal"], {"local": False, "blocked": True}, "nichts bleibt unbemerkt vorgemerkt")
        self.assertEqual(out["centralOff"], {"local": True, "blocked": False})
        self.assertEqual(out["foreign"], {"local": False, "blocked": False})
        start = self.js.index("function toggleSignal()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("kit.signalToggle(", body)
        self.assertIn('"clock.hint_signal_central"', body)
        start = self.js.index("function renderSignal()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('if (view.state !== "off" && !view.local) state.signalLocal = false;', body)
        for lang in ("de", "en"):
            clock = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            self.assertTrue(clock["hint_signal_central"], lang)
            self.assertTrue(clock["signal_stale_short"], lang)
            self.assertLessEqual(len(clock["signal_stale_short"]), 12, "Kurzfassung für 240 px Breite")
        block = self.css[self.css.index("/* --- Studiouhr B4: On-Air/REC-Signal"):]
        self.assertIn("body.has-signal .clock-hint { top: auto; bottom:", block, "der Kurzhinweis verdeckt den Balken nicht")

    def test_ablaufzeit_in_der_anzeige(self):
        out = run_node("""
          const e = (o) => k.signalExpiry(o);
          const until = { rev: "aaaa00000001", at: 5000 };
          console.log(JSON.stringify({
            ok: e({ state: "rec", rev: "aaaa00000001", until, now: 1000 }), none: e(),
            other: e({ state: "rec", rev: "bbbb00000002", until, now: 1000 }),
            past: e({ state: "rec", rev: "aaaa00000001", until, now: 5000 }),
            off: e({ state: "off", rev: "aaaa00000001", until, now: 1000 }),
            norev: e({ state: "rec", rev: "", until: { rev: "", at: 5000 }, now: 1000 }),
            broken: e({ state: "rec", rev: "aaaa00000001", until: { rev: "aaaa00000001", at: "bald" }, now: 1000 }),
            foreign: e({ state: "standby", rev: "aaaa00000001", until, now: 1000 }),
          }));
        """)
        self.assertEqual(out["ok"], 5000)
        for name in ("none", "other", "past", "off", "norev", "broken", "foreign"):
            self.assertIsNone(out[name], name)
        page = (JS / "pages" / "displays.js").read_text(encoding="utf-8")
        self.assertIn("kit.signalExpiry(", page)
        self.assertIn('t("pages.displays.signal_done_ttl"', page)
        # Der Zustand wird gemerkt und beim Neuzeichnen sofort gezeigt; der Text nur gesetzt, wenn er sich ändert.
        start = page.index("function signalCard(")
        body = page[start:page.index("\n}\n", start)]
        self.assertNotIn('text: t("pages.displays.signal_unknown")', body)
        self.assertEqual(body.count("now.textContent = "), 1)
        self.assertIn("if (now.textContent !== text) now.textContent = text;", body)
        self.assertIn("Date.now() - st.signalAt >= SIGNAL_REFRESH_MS", body)
        self.assertNotIn("clearInterval(signalTimer);\n  signalTimer = setInterval", page)
        for lang in ("de", "en"):
            pages = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["pages"]["displays"]
            for key, parts in (("signal_now_until", ("{state}", "{time}")), ("signal_done_ttl", ("{state}", "{span}"))):
                for part in parts:
                    self.assertIn(part, pages[key], f"{lang}: {key}")

    def test_groesse_und_enge(self):
        block = self.css[self.css.index("/* --- Studiouhr B4: On-Air/REC-Signal"):]
        # Keine enge Obergrenze (4K), flache Streifen zählen die Breite mit.
        self.assertIn("font-size: clamp(14px, max(3.2vmin, min(1.2vw, 11vh)), 96px);", block)
        self.assertIn("--signal-w: clamp(4px, max(0.9vmin, min(0.3vw, 3vh)), 40px);", block)
        # Wird es eng, kürzt nur der Hinweis – Symbol und Zustand nie.
        self.assertRegex(block, r"\.clock-signal-icon \{ flex: none;")
        self.assertIn(".clock-signal-text { flex: none; }", block)
        self.assertRegex(block, r"\.clock-signal-note \{[^}]*min-width: 0; overflow: hidden; text-overflow: ellipsis;")
        self.assertRegex(block, r"@media \(max-width: 440px\) \{\s*\.clock-signal-note \{ display: none; \}\s*"
                                r"\.clock-signal-note-short \{ display: block; \}")
        self.assertIn('id="signal-note-short"', self.html)
        self.assertIn('setText($("signal-note-short"),', self.js)

    def test_stil_ohne_blinken_mit_kontrast(self):
        block = self.css[self.css.index("/* --- Studiouhr B4: On-Air/REC-Signal"):]
        self.assertNotRegex(block, r"animation|transition|@keyframes|blink|url\(")
        self.assertIn(".clock-signal[hidden] { display: none; }", block)
        self.assertIn('body.clock-page.has-signal[data-signal="rec"] { border-style: double;', block)
        self.assertIn("body.clock-page.has-signal[data-signal-stale] { border-style: dashed; }", block)
        self.assertRegex(block, r'\.clock-signal\[data-signal="rec"\] \.clock-signal-icon \{', "REC hat ein eigenes Symbol")
        pairs = re.findall(r"--signal: (#[0-9a-f]{6}); --signal-ink: (#[0-9a-f]{6});", block)
        self.assertEqual(len(pairs), 4, "Standard, Rotlicht, E-Ink, Nachtmodus (C1)")
        ratios = run_node(f"console.log(JSON.stringify({json.dumps(pairs)}.map(([a, b]) => k.contrastRatio(a, b))));")
        for ratio in ratios:
            self.assertGreaterEqual(ratio, 4.5)
        self.assertRegex(block, r"font-size: clamp\(14px,")

    def test_layout_springt_nicht_beim_schalten(self):
        # Rahmen und Balken nehmen der Bühne Platz: Das Layout wird mit der Fläche ohne Signal gewählt.
        start = self.js.index("function applyLayout(")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("const taken = signalSpace();", body)
        self.assertIn("kit.chromeLayout(want, width + taken.width, height + taken.height,", body)
        # Auch die gemerkte Höhe von Kopfzeile und Band zählt ohne das Signal – sonst pendelte der automatische Streifen.
        self.assertIn("document.documentElement.clientHeight - height - taken.height)", body)
        block = self.css[self.css.index("/* --- Studiouhr B4: On-Air/REC-Signal"):]
        self.assertRegex(block, r"@media \(max-height: 240px\) \{\s*body\.has-signal \.clock-bar \{ display: none; \}")

    def test_dashboard_schalter(self):
        page = (JS / "pages" / "displays.js").read_text(encoding="utf-8")
        self.assertIn('apiPost("/api/v1/clock/signal", body)', page)
        self.assertIn("signalCard(ctx, st, readonly)", page)
        self.assertIn('help: "clock_signal"', page)
        self.assertNotIn('"aria-pressed"', page)
        self.assertNotIn("innerHTML", page)
        settings_page = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('el("option", { value: "clock", text: "nur On-Air-Signal der Uhr" })', settings_page)
        self.assertEqual(apikeys.SCOPE_LABELS["clock"], "nur On-Air-Signal der Uhr")
        help_text = (JS / "help-uhr.js").read_text(encoding="utf-8")
        self.assertIn("clock_signal: {", help_text)
        self.assertIn("kein Tally", help_text)
        for lang in ("de", "en"):
            pages = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["pages"]["displays"]
            self.assertEqual(set(pages["signal_name"]), set(clocksignal.STATES))
            for key in ("signal_title", "signal_sub", "signal_now", "signal_unknown", "signal_ttl", "signal_note", "signal_api"):
                self.assertTrue(pages[key], f"{lang}: {key}")

    def test_doku_mit_platzhalter(self):
        doc = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        self.assertIn("POST /api/v1/clock/signal", doc)
        self.assertIn("Authorization: Bearer ntpg_…", doc)
        self.assertIn('{"state": "on_air"}', doc)
        self.assertIn("kein Tally", doc)
        self.assertNotRegex(doc, r"ntpg_[A-Za-z0-9_-]{32}", "nur ein Platzhalter, kein echter Schlüssel")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("/api/v1/clock/signal", readme)
        self.assertIn("`clock`", readme)


if __name__ == "__main__":
    unittest.main()
