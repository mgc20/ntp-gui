"""1.5.4: Proxy per Klick eintragen; Restpunkte aus der Abschlussprüfung.

- HTTPS-Hinweis: beobachteten, nicht eingetragenen Proxy per Klick als /32 bzw. /128 eintragen
  (Adresse aus der eigenen Liste des Servers, Admin, CSRF).
- TRUSTED_PROXIES breiter als /24 bzw. /64: Warnung beim Speichern und Hinweis.
- Holdover-Frist auf der monotonen Uhr.
- GPS gesperrt ohne andere auswählbare Quelle ≥ 6 h → einmal „crit“.
- Kalibrierung: window begrenzt (Standard 24 h, höchstens 7 Tage, NaN/negativ → 400), Verlauf in
  Abschnitten gelesen.
- HTTP: Fristen gegen hängende Verbindungen (Content-Length zu groß, Leerlauf, Tröpfeln).
"""

import base64
import http.client
import json
import os
import shutil
import socket
import sys
import socketserver
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import apikeys  # noqa: E402
import apiv1  # noqa: E402
import autocal  # noqa: E402
import gnssguard  # noqa: E402
import history as historymod  # noqa: E402
import holdover  # noqa: E402
import selectctl  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import webtransport as wt  # noqa: E402
from test_gnssguard import CFG, FakeChrony, StoreCase  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASIC = "Basic " + base64.b64encode(b"admin:geheim123").decode()
H = 3600.0


# --- Proxy per Klick: Hinweis --------------------------------------------------------------------

class TrustFixHintTest(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.watch = wt.TransportWatch(clock=lambda: self.now[0])

    def untrusted(self, peer, kind="basic"):
        info = wt.resolve(peer, _headers({"X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"}), [])
        self.watch.note(info, kind)

    def by_key(self):
        return {i["key"]: i for i in self.watch.insights()}

    def test_untrusted_hint_names_address_and_offers_exact_host(self):
        self.untrusted("192.168.1.7")
        items = self.by_key()
        hint = items["web_proxy_untrusted"]
        self.assertIn("192.168.1.7", hint["text"])
        [fix] = hint["fixes"]
        self.assertEqual(fix["kind"], "trust_proxy")
        self.assertEqual(fix["network"], "192.168.1.7/32")
        self.assertIn("192.168.1.7/32", fix["label"])
        self.assertIn("Als vertrauenswürdigen Proxy eintragen", fix["label"])
        self.assertIn("X-Forwarded-For", fix["confirm"])
        self.assertEqual(self.watch.untrusted_peer(fix["id"]), "192.168.1.7")
        # Dieselbe Adresse steht auch im Klartext-Hinweis (Ursache „untrusted“) mit Knopf.
        self.assertEqual(items["web_plain_http"]["fixes"][0]["id"], fix["id"])

    def test_ipv6_and_mapped_addresses(self):
        self.untrusted("fd00::10")
        self.untrusted("::ffff:192.168.1.8")
        nets = sorted(f["network"] for f in self.by_key()["web_proxy_untrusted"]["fixes"])
        self.assertEqual(nets, ["192.168.1.8/32", "fd00::10/128"])

    def test_loopback_proxy_offered_too_but_no_plain_warning(self):
        self.untrusted("127.0.0.1")
        items = self.by_key()
        self.assertNotIn("web_plain_http", items)
        self.assertEqual(items["web_proxy_untrusted"]["fixes"][0]["network"], "127.0.0.1/32")

    def test_unknown_or_expired_id(self):
        self.untrusted("192.168.1.7")
        fix_id = self.by_key()["web_proxy_untrusted"]["fixes"][0]["id"]
        self.assertIsNone(self.watch.untrusted_peer("0" * 16))
        self.assertIsNone(self.watch.untrusted_peer(""))
        self.now[0] += wt.WINDOW + 1
        self.assertIsNone(self.watch.untrusted_peer(fix_id))

    def test_reset_forgets(self):
        self.untrusted("192.168.1.7")
        fix_id = self.by_key()["web_proxy_untrusted"]["fixes"][0]["id"]
        self.watch.reset()
        self.assertIsNone(self.watch.untrusted_peer(fix_id))
        self.assertEqual(self.watch.insights(), [])

    def test_capped(self):
        for i in range(wt.MAX_SOURCES + 4):
            self.now[0] += 1
            self.untrusted(f"192.168.1.{i + 10}")
        self.assertEqual(len(self.watch.untrusted), wt.MAX_SOURCES)
        self.assertEqual(len(self.by_key()["web_proxy_untrusted"]["fixes"]), wt.SHOW_SOURCES)

    def test_readonly_key_cannot_offer_its_address(self):
        info = wt.resolve("192.168.1.66", _headers({"X-Forwarded-For": "10.0.0.1"}), [])
        self.watch.note(info, "key", can_admin=False)
        hint = self.by_key()["web_proxy_untrusted"]
        self.assertNotIn("fixes", hint)
        self.assertNotIn("192.168.1.66", hint["text"])
        self.assertEqual(self.watch.untrusted, {})

    def test_older_proxy_stays_first(self):
        self.untrusted("192.168.1.7")
        self.now[0] += 60
        self.untrusted("192.168.1.99")
        fixes = self.by_key()["web_proxy_untrusted"]["fixes"]
        self.assertEqual([f["address"] for f in fixes], ["192.168.1.7", "192.168.1.99"])
        self.now[0] += 60
        self.untrusted("192.168.1.99")  # neuer Zugriff ändert die Reihenfolge nicht
        fixes = self.by_key()["web_proxy_untrusted"]["fixes"]
        self.assertEqual(fixes[0]["address"], "192.168.1.7")

    def test_gateway_peer_warns(self):
        with mock.patch.object(wt, "default_gateways", return_value=frozenset({"172.17.0.1"})):
            self.untrusted("172.17.0.1")
            self.untrusted("192.168.1.7")
            hint = self.by_key()["web_proxy_untrusted"]
            by_addr = {f["address"]: f for f in hint["fixes"]}
            self.assertIn("Gateway des Container-Netzes", by_addr["172.17.0.1"]["confirm"])
            self.assertNotIn("Gateway", by_addr["192.168.1.7"]["confirm"])
            self.assertIn("172.17.0.1 ist das Gateway", hint["text"])

    def test_route_gateways_parsed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            v4 = Path(tmp, "route")
            v4.write_text("Iface\tDestination\tGateway\n"
                          "eth0\t00000000\t010011AC\t0003\n"
                          "eth0\t000011AC\t00000000\t0001\n")
            v6 = Path(tmp, "ipv6_route")
            v6.write_text("0" * 32 + " 00 " + "0" * 32 + " 00 fe800000000000000000000000000001 "
                          "00000400 00000001 00000000 00000003 eth0\n")
            self.assertEqual(wt._route_gateways(str(v4), str(v6)), {"172.17.0.1", "fe80::1"})
            self.assertEqual(wt._route_gateways(str(Path(tmp, "fehlt")), str(Path(tmp, "fehlt"))), set())

    def test_fix_never_in_diagnostics_fields(self):
        import diagnostics
        self.assertNotIn("fixes", diagnostics.HINT_FIELDS)


def _headers(values):
    from email.message import Message
    msg = Message()
    for name, value in values.items():
        msg[name] = value
    return msg


# --- Breite Einträge -----------------------------------------------------------------------------

class BroadProxyTest(unittest.TestCase):
    def test_broad_entries(self):
        self.assertEqual(wt.broad_entries(["192.168.1.0/24", "10.0.0.0/8", "127.0.0.1/32"]), ["10.0.0.0/8"])
        self.assertEqual(wt.broad_entries(["fd00::/64", "fd00::/48", "::1/128"]), ["fd00::/48"])
        self.assertEqual(wt.broad_entries([]), [])

    def test_hint(self):
        watch = wt.TransportWatch(clock=lambda: 0.0)
        items = watch.insights(["172.16.0.0/12"])
        self.assertEqual([i["key"] for i in items], ["web_proxy_broad"])
        self.assertEqual(items[0]["level"], "warn")
        self.assertIn("172.16.0.0/12", items[0]["text"])
        self.assertEqual(watch.insights(["172.18.0.0/24"]), [])

    def test_save_warns_but_stores(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(settings, "DATA_DIR", tmp), \
                mock.patch.object(settings, "SETTINGS_FILE", os.path.join(tmp, "settings.json")):
            result = settings.save({"trusted_proxies": "10.0.0.0/8"})
            self.assertEqual(settings.values()["trusted_proxies"], ["10.0.0.0/8"])
            self.assertIn("10.0.0.0/8", result["warnings"][0])
            self.assertNotIn("warnings", settings.save({"trusted_proxies": "10.0.0.5"}))


# --- Proxy per Klick: am echten Handler ----------------------------------------------------------

class TrustProxyHandlerTest(unittest.TestCase):
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
        os.environ.pop("TRUSTED_PROXIES", None)
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        apikeys._READY["db"] = None
        apikeys.clear_cache()
        server.AUTH_CACHE.clear()
        wt.WATCH.reset()
        cls.tmp.cleanup()

    def setUp(self):
        wt.WATCH.reset()
        try:
            os.remove(settings.SETTINGS_FILE)
        except OSError:
            pass

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(data or b"{}")
        except ValueError:
            return resp.status, {}

    def browser(self, extra=None):
        return dict({"Authorization": BASIC, "Content-Type": "application/json", "X-NTP-GUI": "1",
                     "Origin": f"http://127.0.0.1:{self.port}"}, **(extra or {}))

    def observe(self):
        """Proxy-Köpfe von 127.0.0.1, das (noch) nicht eingetragen ist → Hinweis mit Knopf."""
        status, _ = self.request("GET", "/api/v1", headers={
            "Authorization": BASIC, "X-Forwarded-For": "192.168.1.50", "X-Forwarded-Proto": "https"})
        self.assertEqual(status, 200)
        hint = next(i for i in wt.WATCH.insights() if i["key"] == "web_proxy_untrusted")
        return hint["fixes"][0]["id"]

    def test_click_adds_exact_peer_and_resets(self):
        fix_id = self.observe()
        settings.save({"trusted_proxies": ["::1/128"]})
        # Was die Anfrage sonst noch behauptet (Adresse, Netz), zählt nicht.
        status, body = self.request("POST", "/api/web/proxies/trust",
                                    {"id": fix_id, "address": "10.0.0.0/8", "network": "0.0.0.0/1"},
                                    self.browser())
        self.assertEqual(status, 200, body)
        self.assertEqual(body["network"], "127.0.0.1/32")
        self.assertEqual(settings.values()["trusted_proxies"], ["::1/128", "127.0.0.1/32"])
        self.assertIn("trusted_proxies", body["changed"])
        self.assertEqual(wt.WATCH.insights(), [])
        self.assertIsNone(wt.WATCH.untrusted_peer(fix_id))
        # Ein zweiter Klick mit derselben Kennung: der Hinweis ist weg.
        status, _ = self.request("POST", "/api/web/proxies/trust", {"id": fix_id}, self.browser())
        self.assertEqual(status, 409)

    def test_unknown_id_conflict(self):
        self.observe()
        status, body = self.request("POST", "/api/web/proxies/trust", {"id": "deadbeefdeadbeef"}, self.browser())
        self.assertEqual(status, 409)
        self.assertEqual(settings.values()["trusted_proxies"], [])
        status, _ = self.request("POST", "/api/web/proxies/trust", {"address": "127.0.0.1"}, self.browser())
        self.assertEqual(status, 409)
        self.assertEqual(settings.values()["trusted_proxies"], [])

    def test_csrf_needed(self):
        fix_id = self.observe()
        for extra in ({"X-NTP-GUI": ""}, {"Origin": "http://evil.example"}, {"Content-Type": "text/plain"}):
            with self.subTest(extra=extra):
                headers = {k: v for k, v in self.browser(extra).items() if v}
                status, _ = self.request("POST", "/api/web/proxies/trust", {"id": fix_id}, headers)
                self.assertEqual(status, 403)
        self.assertEqual(settings.values()["trusted_proxies"], [])

    def test_auth_needed(self):
        fix_id = self.observe()
        headers = self.browser()
        headers.pop("Authorization")
        status, _ = self.request("POST", "/api/web/proxies/trust", {"id": fix_id}, headers)
        self.assertEqual(status, 401)
        self.assertEqual(settings.values()["trusted_proxies"], [])

    def test_read_key_denied_and_sees_no_button(self):
        _key_id, token = apikeys.create("lesen", "read")
        fix_id = self.observe()
        bearer = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        status, body = self.request("POST", "/api/v1/web/proxies/trust", {"id": fix_id}, bearer)
        self.assertEqual(status, 403)
        self.assertEqual(body.get("scope_required"), "admin")
        self.assertEqual(settings.values()["trusted_proxies"], [])
        with mock.patch.object(server, "build_status", lambda: {"insights": wt.WATCH.insights()}):
            _status, status_body = self.request("GET", "/api/status", headers={"Authorization": f"Bearer {token}"})
            self.assertTrue(status_body["insights"])
            self.assertFalse(any("fixes" in i for i in status_body["insights"]))
            _status, status_body = self.request("GET", "/api/status", headers={"Authorization": BASIC})
            self.assertTrue(any("fixes" in i for i in status_body["insights"]))

    def test_admin_key_allowed(self):
        _key_id, token = apikeys.create("admin", "admin")
        fix_id = self.observe()
        status, body = self.request("POST", "/api/v1/web/proxies/trust", {"id": fix_id},
                                    {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.assertEqual(status, 200, body)
        self.assertEqual(settings.values()["trusted_proxies"], ["127.0.0.1/32"])

    def test_readonly_env_blocks(self):
        fix_id = self.observe()
        with mock.patch.dict(os.environ, {"WEB_READONLY": "true"}):
            status, _ = self.request("POST", "/api/web/proxies/trust", {"id": fix_id}, self.browser())
        self.assertEqual(status, 403)
        self.assertEqual(settings.values()["trusted_proxies"], [])

    def test_documented_as_admin(self):
        self.assertEqual(apiv1.required_scope("POST", "/api/v1/web/proxies/trust"), "admin")
        self.assertEqual(apiv1.required_scope("POST", "/api/web/proxies/trust"), "admin")

    def test_js_sends_only_the_id(self):
        js = (ROOT / "app" / "static" / "js" / "ui.js").read_text(encoding="utf-8")
        self.assertIn('trust_proxy: "/api/web/proxies/trust"', js)
        self.assertIn("apiPost(FIX_PATHS[fix.kind], { id: fix.id })", js)
        self.assertIn("window.confirm(", js)


# --- Kalibrierung: Fenster begrenzt ----------------------------------------------------------------

class CalibrationWindowTest(unittest.TestCase):
    def test_parse(self):
        cw = server.calibration_window
        self.assertEqual(cw(None), server.CALIBRATION_DEFAULT_WINDOW)
        self.assertEqual(cw(""), server.CALIBRATION_DEFAULT_WINDOW)
        self.assertEqual(cw("3600"), 3600.0)
        self.assertEqual(cw("0"), server.CALIBRATION_MAX_WINDOW)          # ältere Dashboards
        self.assertEqual(cw("1e12"), server.CALIBRATION_MAX_WINDOW)
        self.assertEqual(cw("inf"), server.CALIBRATION_MAX_WINDOW)
        for bad in ("nan", "NaN", "-1", "-inf", "abc"):
            self.assertIsNone(cw(bad), bad)

    def test_ui_no_longer_asks_for_everything(self):
        js = (ROOT / "app" / "static" / "js" / "pages" / "gps.js").read_text(encoding="utf-8")
        self.assertNotIn('[0, "gesamter Verlauf"]', js)
        self.assertNotIn("calWindow ?? 0", js)
        self.assertIn("CAL_DEFAULT_WINDOW = 86400", js)

    def test_autocal_getter_never_reads_everything(self):
        calls = []

        class FakeHistory:
            def snapshot(self, since=None):
                calls.append(since)
                return []

        get = autocal.make_calibration_getter(FakeHistory(), cfg_getter=lambda: {"gps_refid": "GPS"},
                                              clock=lambda: 1_000_000_000.0)
        for window in (0, -5, float("nan"), 1e12, 3600):
            get(window)
        self.assertNotIn(None, calls)
        expected = [1_000_000_000.0 - autocal.MAX_WINDOW] * 4 + [1_000_000_000.0 - 3600]
        self.assertEqual(calls, expected)


class CalibrationEndpointTest(unittest.TestCase):
    """Großer synthetischer Verlauf: 30 Tage im 60-s-Takt. Fenster 0 („gesamter Verlauf“) liest nur
    noch 7 Tage, NaN wird abgelehnt."""

    DAYS = 30
    STEP = 60

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.hist = historymod.History(None, os.path.join(cls.tmp, "history.json.gz"),
                                      days=40, db_path=os.path.join(cls.tmp, "ntp-gui.db"))
        assert cls.hist.backend == "sqlite"
        cls.end = float(int(time.time()))
        start = cls.end - cls.DAYS * 86400
        rows = []
        t = start
        while t <= cls.end:
            rows.append((int(t), json.dumps({"t": int(t), "sources": {
                "GPS": {"offset": 0.004, "state": "-", "mode": "#"},
                "nts1": {"offset": 0.0001, "state": "*", "mode": "^"},
                "nts2": {"offset": -0.0001, "state": "+", "mode": "^"}}})))
            t += cls.STEP
        with store.transaction(cls.hist.db_path) as conn:
            conn.executemany("INSERT OR REPLACE INTO samples(t, json) VALUES(?, ?)", rows)
        cls.count = len(rows)

    @classmethod
    def tearDownClass(cls):
        store.close_all()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_chunked_snapshot_complete_without_duplicates(self):
        since = self.end - 7 * 86400 + 0.5
        texts_calls = []
        original = self.hist._raw_rows

        def spy(lo, hi):
            # Jeder Abschnitt einzeln unter dem Lock – und nicht über SNAPSHOT_CHUNK hinaus.
            self.assertLessEqual(hi - lo, historymod.SNAPSHOT_CHUNK)
            texts_calls.append((lo, hi))
            return original(lo, hi)

        with mock.patch.object(self.hist, "_raw_rows", spy):
            samples = self.hist.snapshot(since)
        ts = [s["t"] for s in samples if s["t"] <= self.end]  # add() aus einem anderen Test zählt nicht
        self.assertEqual(ts, sorted(set(ts)))
        expected = [t for t in range(int(self.end - self.DAYS * 86400), int(self.end) + 1, self.STEP) if t >= since]
        self.assertEqual(ts, expected)
        self.assertGreaterEqual(len(texts_calls), 7 * 86400 // historymod.SNAPSHOT_CHUNK)

    def test_add_not_blocked_for_whole_read(self):
        """Während snapshot() läuft, kommt add() zwischen zwei Abschnitten dran."""
        started = threading.Event()
        got_in = []
        original = self.hist._raw_rows

        def slow(lo, hi):
            started.set()
            time.sleep(0.02)
            return original(lo, hi)

        def writer():
            started.wait(5)
            t0 = time.monotonic()
            self.hist.add({"t": int(self.end) + 1})
            got_in.append(time.monotonic() - t0)

        thread = threading.Thread(target=writer)
        thread.start()
        with mock.patch.object(self.hist, "_raw_rows", slow):
            self.hist.snapshot(self.end - 7 * 86400)
        thread.join(5)
        self.assertTrue(got_in)
        self.assertLess(got_in[0], 0.5)  # ein Abschnitt (~0,02 s), nicht alle 28

    def test_endpoint_window_bounds(self):
        handler = server.Handler.__new__(server.Handler)
        sent = []
        handler._send_json = lambda payload, status=200, extra=None: sent.append((status, payload))
        handler._error = lambda status, message, **extra: sent.append((status, {"error": message}))
        handler.path = "/api/gps/calibration?window=nan"
        snaps = []
        original = self.hist.snapshot

        def snapshot(since=None):
            snaps.append(since)
            return original(since)

        cfg = {"gps_refid": "GPS", "gps_offset": 0.0, "gps_delay": 0.2, "gps_enable": True}
        with mock.patch.object(server, "HISTORY", self.hist), \
                mock.patch.object(self.hist, "snapshot", snapshot), \
                mock.patch.object(settings, "values", lambda: cfg), \
                mock.patch.object(server.gpsquality, "offset_not_before", lambda c: None), \
                mock.patch.object(server.gpsquality, "annotate_calibration", lambda r, c: r):
            handler._route_get("/api/gps/calibration")
            self.assertEqual(sent[-1][0], server.HTTPStatus.BAD_REQUEST)
            handler.path = "/api/gps/calibration?window=-10"
            handler._route_get("/api/gps/calibration")
            self.assertEqual(sent[-1][0], server.HTTPStatus.BAD_REQUEST)
            self.assertEqual(snaps, [])
            handler.path = "/api/gps/calibration?window=0"
            t0 = time.monotonic()
            handler._route_get("/api/gps/calibration")
            seconds = time.monotonic() - t0
            self.assertEqual(sent[-1][0], 200)
            self.assertAlmostEqual(time.time() - snaps[-1], server.CALIBRATION_MAX_WINDOW, delta=60)
            self.assertLessEqual(sent[-1][1]["samples"], 7 * 86400 // self.STEP + 2)
            handler.path = "/api/gps/calibration"
            handler._route_get("/api/gps/calibration")
            self.assertAlmostEqual(time.time() - snaps[-1], server.CALIBRATION_DEFAULT_WINDOW, delta=60)
        # Zur Einordnung (kein harter Grenzwert – Testrechner sind verschieden schnell).
        print(f"\n[1.5.4] Kalibrierung window=0 über {self.count} Punkte (30 Tage): {seconds:.2f} s, "
              "gelesen: 7 Tage", file=sys.stderr)


# --- HTTP-Fristen -----------------------------------------------------------------------------------

class HTTPTimeoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch.object(server.Handler, "timeout", 0.5),
                       mock.patch.object(server, "REQUEST_READ_DEADLINE", 1.5),
                       mock.patch.dict(os.environ, {"WEB_USER": "", "WEB_PASSWORD": ""})]
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

    def connect(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(sock.close)
        return sock

    @staticmethod
    def closed_after(sock) -> float:
        """Sekunden, bis der Server die Verbindung schließt (Antwort wird mitgelesen)."""
        t0 = time.monotonic()
        while True:
            try:
                data = sock.recv(65536)
            except (ConnectionResetError, OSError):
                break
            if not data:
                break
        return time.monotonic() - t0

    def test_short_body_does_not_hold_thread(self):
        sock = self.connect()
        sock.sendall(b"POST /api/settings HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                     b"X-NTP-GUI: 1\r\nContent-Length: 60000\r\n\r\n{\"changes\":")
        self.assertLess(self.closed_after(sock), 5)

    def test_idle_keepalive_closed(self):
        sock = self.connect()
        sock.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        t0 = time.monotonic()
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        self.assertIn(b"HTTP/1.1", response)
        self.assertLess(self.closed_after(sock) + (time.monotonic() - t0), 5)

    def test_dripping_headers_hit_deadline(self):
        sock = self.connect()
        sock.sendall(b"GET /healthz HTTP/1.1\r\n")
        t0 = time.monotonic()
        closed = False
        while time.monotonic() - t0 < 6:
            try:
                sock.sendall(b"X-A: b\r\n")
            except OSError:
                closed = True
                break
            sock.settimeout(0.3)
            try:
                if sock.recv(4096) == b"":
                    closed = True
                    break
            except socket.timeout:
                pass
            except OSError:
                closed = True
                break
        self.assertTrue(closed)
        self.assertLess(time.monotonic() - t0, 5)

    def test_normal_requests_still_work(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for _ in range(3):
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            resp.read()
            self.assertIn(resp.status, (200, 503))
        conn.close()

    def test_idle_keepalive_not_cut_by_read_deadline(self):
        # Leerlauf zählt nicht zur Lesefrist (1,5 s): nach 2 s Pause geht die nächste Anfrage noch.
        with mock.patch.object(server.Handler, "timeout", 5.0):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            self.addCleanup(conn.close)
            conn.request("GET", "/healthz")
            conn.getresponse().read()
            time.sleep(2.0)
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            resp.read()
            self.assertIn(resp.status, (200, 503))

    def test_slow_reader_gets_whole_body(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16384)
        b.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
        a.settimeout(0.5)
        handler = server.Handler.__new__(server.Handler)
        handler.wfile = socketserver._SocketWriter(a)  # wie StreamRequestHandler (wbufsize=0)
        body = os.urandom(3 * 1024 * 1024)
        got = bytearray()

        def reader():
            while len(got) < len(body):
                chunk = b.recv(65536)
                if not chunk:
                    break
                got.extend(chunk)
                time.sleep(0.01)

        thread = threading.Thread(target=reader)
        thread.start()
        t0 = time.monotonic()
        handler._write_body(body)
        thread.join(30)
        self.assertGreater(time.monotonic() - t0, 0.5)  # länger als die Socket-Frist
        self.assertEqual(bytes(got), body)

    def test_disarm_reports_reaped(self):
        reaper = server._Reaper()
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        reaper._thread = object()
        reaper.arm(a, 0)
        reaper.reap(now=time.monotonic() + 1)
        self.assertTrue(reaper.disarm(a))
        self.assertFalse(reaper.disarm(a))

    def test_reaper_only_while_reading(self):
        reaper = server._Reaper()
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        reaper._thread = object()      # kein eigener Thread im Test
        reaper.arm(a, 10)
        self.assertEqual(reaper.reap(now=time.monotonic()), 0)
        reaper.disarm(a)
        self.assertEqual(reaper.reap(now=time.monotonic() + 100), 0)
        reaper.arm(a, 0)
        self.assertEqual(reaper.reap(now=time.monotonic() + 1), 1)
        b.settimeout(2)
        self.assertEqual(b.recv(10), b"")


# --- Holdover-Frist auf der monotonen Uhr -----------------------------------------------------------

class HoldoverMonotonicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        self.chrony = FakeChrony(gps=True, pps=False, network=5)
        self.addCleanup(selectctl.set_port(self.chrony))
        selectctl.reset_for_tests()
        self.wall = [1_800_000_000.0]
        self.mono = [500.0]
        self.events = []
        self.test = self.make()
        patcher = mock.patch.object(holdover, "TEST", self.test)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup)

    def make(self):
        test = holdover.HoldoverTest(emit=lambda *a: self.events.append(a), wall=lambda: self.wall[0],
                                     hold=lambda until: None, mono=lambda: self.mono[0])
        test.busy = lambda: ""
        test.settle = lambda: None
        return test

    def _cleanup(self):
        selectctl.reset_for_tests()
        holdover._READY["for"] = None
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def advance(self, wall=0.0, mono=0.0):
        self.wall[0] += wall
        self.mono[0] += mono
        return self.test.tick({}, self.chrony.select())

    def test_wall_jump_forward_does_not_end_test(self):
        self.test.start({"action": "start", "hours": 2, "include_network": True, "limit_ms": 1000})
        self.assertIsNone(self.advance(wall=86400, mono=60))   # Wanduhr springt einen Tag
        self.assertTrue(self.test.running())
        self.assertAlmostEqual(self.test.status()["run"]["remaining_s"], 2 * H - 60, delta=1)
        result = None
        for _ in range(130):
            result = self.advance(wall=60, mono=60) or result
            if result:
                break
        self.assertEqual(result["outcome"], "done")

    def test_wall_jump_back_does_not_extend(self):
        self.test.start({"action": "start", "hours": 1, "include_network": True, "limit_ms": 1000})
        self.assertIsNone(self.advance(wall=-86400, mono=60))
        result = None
        for _ in range(70):
            result = self.advance(wall=60, mono=60) or result
            if result:
                break
        self.assertEqual(result["outcome"], "done")

    def test_restart_recomputes_safely(self):
        self.test.start({"action": "start", "hours": 2, "include_network": True, "limit_ms": 1000})
        self.advance(wall=1800, mono=1800)
        # Neuer Prozess (monotone Uhr fängt woanders an), Wanduhr beim Neustart zurückgestellt:
        self.mono[0] = 7.0
        self.wall[0] -= 10 * 86400
        fresh = self.make()
        fresh._state = None
        self.assertLessEqual(fresh.remaining(), 2 * H)         # nie länger als der ganze Test
        self.assertGreater(fresh.remaining(), 0)
        # … Wanduhr weit voraus: Frist sofort abgelaufen, nicht negativ gerechnet.
        self.wall[0] += 20 * 86400
        later = self.make()
        self.assertEqual(later.remaining(), 0.0)


# --- GPS gesperrt, Uhr läuft frei --------------------------------------------------------------------

class FreerunAlertTest(StoreCase):
    fake_args = {"network": 0}

    def tick(self, guard, seconds, step=60.0):
        end = self.mono[0] + seconds
        while self.mono[0] < end:
            self.mono[0] += step
            self.wall[0] += step
            guard.tick(CFG, obs={"t": self.mono[0]}, select=self.chrony.select(), sources=self.chrony.sources())

    def freerun(self):
        return [e for e in self.events if "Uhr läuft frei" in e[2]]

    def test_once_after_six_hours(self):
        guard = self.guard()
        guard.action(CFG, {"action": "lock", "force": True})
        self.tick(guard, 6 * H - 300)
        self.assertEqual(self.freerun(), [])
        self.tick(guard, 600)
        [event] = self.freerun()
        self.assertEqual(event[0], "gps")
        self.assertEqual(event[1], "crit")
        self.assertTrue(event[2].startswith("GPS gesperrt, Uhr läuft frei"))
        self.assertEqual(event[3]["subject"], "gps-sperre")
        self.tick(guard, 12 * H)
        self.assertEqual(len(self.freerun()), 1)            # einmal je Sperre
        # Auch nach einem Neustart des Dashboards nicht noch einmal (gespeichert).
        fresh = self.guard()
        self.tick(fresh, 7 * H)
        self.assertEqual(len(self.freerun()), 1)
        # Freigabe und neue Sperre: wieder scharf.
        fresh.action(CFG, {"action": "unlock"})
        fresh.action(CFG, {"action": "lock", "force": True})
        self.tick(fresh, 6 * H + 120)
        self.assertEqual(len(self.freerun()), 2)

    def test_reachable_source_resets(self):
        guard = self.guard()
        guard.action(CFG, {"action": "lock", "force": True})
        self.tick(guard, 5 * H)
        self.chrony.rows["192.0.2.1"] = {"mode": "^", "auth": True, "conf": False, "offset": 0.0}
        self.tick(guard, 600)
        del self.chrony.rows["192.0.2.1"]
        self.tick(guard, 5 * H)
        self.assertEqual(self.freerun(), [])
        self.tick(guard, 2 * H)
        self.assertEqual(len(self.freerun()), 1)

    def test_holdover_test_does_not_count(self):
        guard = self.guard()
        guard.action(CFG, {"action": "lock", "force": True})
        with mock.patch.object(gnssguard, "_holdover_running", lambda: True):
            self.tick(guard, 12 * H)
        self.assertEqual(self.freerun(), [])

    def test_unlocked_never(self):
        guard = self.guard()
        self.tick(guard, 8 * H)
        self.assertEqual(self.freerun(), [])


class HelpTextTest(unittest.TestCase):
    def test_gnss_help(self):
        js = (ROOT / "app" / "static" / "js" / "help-gnss.js").read_text(encoding="utf-8")
        self.assertIn("gnss_freerun: {", js)
        self.assertIn('title: "Empfänger umgezogen → Position neu lernen"', js)
        page = (ROOT / "app" / "static" / "js" / "pages" / "gnss.js").read_text(encoding="utf-8")
        self.assertIn('info("gnss_moved"', page)
        self.assertIn('"gnss_freerun"', page)


if __name__ == "__main__":
    unittest.main()
