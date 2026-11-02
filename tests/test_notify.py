"""Tests für Benachrichtigungen (notify.py) und den Zweck „notify“ im Filter (egress.py)."""

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import apiv1  # noqa: E402
import egress  # noqa: E402
import events  # noqa: E402
import notify  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402


# --------------------------------------------------------------------------- Testziel
class Target:
    """Kleiner HTTP-Server als Ziel: merkt sich Anfragen, Antwort pro Test einstellbar."""

    def __init__(self):
        self.requests = []
        self.status = 200
        self.location = None
        self.delay = 0.0
        self.body = b"ok"
        target = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                target.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if target.delay:
                    time.sleep(target.delay)
                self.send_response(target.status)
                if target.location:
                    self.send_header("Location", target.location)
                self.send_header("Content-Length", str(len(target.body)))
                self.end_headers()
                try:
                    self.wfile.write(target.body)
                except OSError:
                    pass

            do_GET = do_POST  # noqa: N815

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def wait(self, count, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end and len(self.requests) < count:
            time.sleep(0.02)
        return len(self.requests) >= count


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        self.saved_file = settings.SETTINGS_FILE
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        settings.SETTINGS_FILE = os.path.join(settings.DATA_DIR, "settings.json")
        notify._reset_for_tests()
        events._STATE["ready_for"] = None
        events._LISTENERS.clear()
        self.known = mock.patch.object(notify, "_known", return_value=(["nas.home.lan"], {}))
        self.known.start()

    def tearDown(self):
        self.known.stop()
        notify._reset_for_tests()
        events._LISTENERS.clear()
        store.close_all()
        settings.DATA_DIR = self.saved
        settings.SETTINGS_FILE = self.saved_file
        shutil.rmtree(self.tmp, ignore_errors=True)


def channel(**over):
    base = {"id": "abcdef0123", "name": "Test", "type": "webhook", "enabled": True, "url": "http://127.0.0.1:9/",
            "topic": "", "secret": "", "min_level": "warn", "kinds": [], "debounce_min": 15,
            "rate_per_hour": 30, "resolved": True}
    base.update(over)
    return base


def ev(kind, level, title, t, data=None, ident=1):
    return {"id": ident, "t": t, "kind": kind, "level": level, "title": title, "data": data, "source": "web"}


# --------------------------------------------------------------------------- Prüfung
class ValidateTest(unittest.TestCase):
    def test_urls(self):
        ok = ["http://ntfy.lan", "https://ntfy.sh/", "http://192.168.1.5:8080/hook?x=1", "http://[fd00::1]:80/a",
              "https://hooks.example.org/a/b-c_d~e"]
        bad = ["ftp://x.lan/", "file:///etc/passwd", "http://user:pw@host.lan/", "http://host.lan/a b",
               "http://host.lan/\nX: y", "javascript:alert(1)", "http://", "http://host.lan:99999/",
               "http://-bad-.lan/", "http://host.lan/<script>", "gopher://host.lan/", "http://h.lan/" + "a" * 400]
        for url in ok:
            self.assertTrue(settings.http_url_ok(url), url)
        for url in bad:
            self.assertFalse(settings.http_url_ok(url), url)

    def test_channel_rules(self):
        clean = notify.validate({"name": " Handy ", "type": "ntfy", "url": "https://ntfy.sh", "topic": "zeit_42",
                                 "secret": "tk_abc", "kinds": "gps, pps", "min_level": "crit"})
        self.assertEqual(clean["name"], "Handy")
        self.assertEqual(clean["kinds"], ["gps", "pps"])
        self.assertEqual(clean["debounce_min"], notify.DEFAULT_DEBOUNCE_MIN)
        for bad in ({"name": "x", "type": "ntfy", "url": "https://ntfy.sh"},                    # Thema fehlt
                    {"name": "x", "type": "gotify", "url": "https://g.lan"},                    # Token fehlt
                    {"name": "x", "type": "apprise", "url": "http://apprise:8000"},             # Schlüssel/URLs
                    {"name": "x", "type": "smtp", "url": "https://x.lan"},
                    {"name": "x\x07", "type": "webhook", "url": "https://x.lan"},
                    {"name": "x", "type": "webhook", "url": "https://x.lan", "kinds": ["GPS!"]},
                    {"name": "x", "type": "webhook", "url": "https://x.lan", "min_level": "debug"},
                    {"name": "x", "type": "webhook", "url": "https://x.lan", "debounce_min": -1},
                    {"name": "x", "type": "webhook", "url": "https://x.lan", "rate_per_hour": 0},
                    {"name": "x", "type": "webhook", "url": "https://x.lan", "secret": "a b"}):
            with self.subTest(bad=bad), self.assertRaises(notify.NotifyError):
                notify.validate(bad)

    def test_kinds_are_generic(self):
        # Künftige Quellen (z. B. „Client-Uhr weicht ab“) brauchen keine Änderung an notify.py.
        clean = notify.validate({"name": "x", "type": "webhook", "url": "https://x.lan", "kinds": ["client_clock"]})
        self.assertEqual(clean["kinds"], ["client_clock"])


# --------------------------------------------------------------------------- Regeln
class RouterTest(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.router = notify.ChannelRouter(channel(), clock=lambda: self.now[0])

    def offer(self, *args, **kw):
        return self.router.offer(ev(*args, **kw))

    def test_crit_sends_once(self):
        out = self.offer("gps", "crit", "GPS-Fix verloren", 1000)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "GPS-Fix verloren")
        self.assertEqual(out[0]["level"], "crit")

    def test_ten_equal_events_one_message_then_resolved_with_duration(self):
        sent = []
        for i in range(10):
            self.now[0] = 1000 + i * 6
            sent += self.offer("service", "warn", "Dienst gpsd unerwartet beendet", self.now[0], {"service": "gpsd"})
        self.assertEqual(len(sent), 1)
        self.now[0] = 1000 + 2400
        out = self.offer("service", "info", "Dienst gpsd läuft wieder", self.now[0], {"service": "gpsd"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Dienst gpsd läuft wieder – Dauer 40 min")
        self.assertTrue(out[0]["resolved"])
        self.assertEqual(out[0]["duration_s"], 2400)
        self.assertEqual(out[0]["suppressed"], 9)

    def test_flapping_catches_up_with_last_state(self):
        sent = self.offer("gps", "warn", "GPS-Fix verloren", 1000)
        self.now[0] = 1010
        sent += self.offer("gps", "info", "GPS-Fix wieder da", 1010)            # behoben (Dauer 10 s)
        for i in range(4):                                                        # flattert weiter
            self.now[0] = 1020 + i * 20
            sent += self.offer("gps", "warn", "GPS-Fix verloren", self.now[0])
            self.now[0] += 10
            sent += self.offer("gps", "info", "GPS-Fix wieder da", self.now[0])
        self.now[0] = 1200
        sent += self.offer("gps", "warn", "GPS-Fix verloren", 1200)              # endet im Problem
        self.assertEqual([m["title"] for m in sent], ["GPS-Fix verloren", "GPS-Fix wieder da – Dauer 10 s"])
        self.now[0] = 1500
        self.assertEqual(self.router.tick(), [])                                  # Sperrzeit läuft noch
        self.now[0] = 1000 + 15 * 60
        late = self.router.tick()
        self.assertEqual(len(late), 1)
        self.assertTrue(late[0]["title"].startswith("GPS-Fix verloren (besteht seit "))
        self.now[0] = 2000
        out = self.offer("gps", "info", "GPS-Fix wieder da", 2000)
        self.assertEqual(out[0]["title"], "GPS-Fix wieder da – Dauer 13 min")

    def test_pending_dropped_when_resolved_in_window(self):
        self.offer("gps", "warn", "GPS-Fix verloren", 1000)
        self.offer("gps", "info", "GPS-Fix wieder da", 1001)
        self.now[0] = 1100
        self.assertEqual(self.offer("gps", "warn", "GPS-Fix verloren", 1100), [])
        self.assertEqual(self.offer("gps", "info", "GPS-Fix wieder da", 1110), [])
        self.now[0] = 9000
        self.assertEqual(self.router.tick(), [])

    def test_escalation_bypasses_debounce(self):
        self.offer("service", "warn", "Dienst gpsd beendet", 1000, {"service": "gpsd"})
        out = self.offer("service", "crit", "Pflichtdienst gpsd ausgefallen", 1001, {"service": "gpsd"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["level"], "crit")

    def test_subjects_are_separate(self):
        a = self.offer("pps", "warn", "PPS-Impulse ausgeblieben (/dev/pps0)", 1000, {"device": "/dev/pps0"})
        b = self.offer("pps", "warn", "PPS-Impulse ausgeblieben (/dev/pps1)", 1000, {"device": "/dev/pps1"})
        self.assertEqual((len(a), len(b)), (1, 1))

    def test_filters(self):
        router = notify.ChannelRouter(channel(min_level="crit", kinds=["gps"]), clock=lambda: 1000.0)
        self.assertEqual(router.offer(ev("gps", "warn", "x", 1000)), [])
        self.assertEqual(router.offer(ev("service", "crit", "x", 1000)), [])
        self.assertEqual(len(router.offer(ev("gps", "crit", "x", 1000))), 1)
        # „behoben“ kommt trotz Mindeststufe crit – es gehört zum gemeldeten Problem.
        self.assertEqual(len(router.offer(ev("gps", "info", "wieder da", 1100))), 1)
        info = notify.ChannelRouter(channel(min_level="info"), clock=lambda: 1000.0)
        self.assertEqual(len(info.offer(ev("source", "info", "Zeitquelle gewechselt", 1000))), 1)
        self.assertEqual(info.offer(ev("source", "info", "Zeitquelle gewechselt", 1000)), [])  # entprellt

    def test_update_events_never_pair(self):
        """Zwei Achtung-Releases nacheinander, dann ein normales: jedes kommt einzeln, nie „behoben“."""
        router = notify.ChannelRouter(channel(min_level="info"), clock=lambda: self.now[0])

        def update(version, level, t, attention=False):
            self.now[0] = t
            title = f"Neue Version {version} verfügbar" + (" – Achtung beim Update" if attention else "")
            return router.offer(ev("update", level, title, t,
                                   {"subject": f"update:{version}", "resolves": False, "version": version}))

        a = update("1.4.0", "warn", 1000, True)
        b = update("1.5.0", "warn", 1000 + 7 * 86400, True)
        c = update("1.5.1", "info", 1000 + 30 * 86400)
        self.now[0] = 1000 + 30 * 86400
        other = router.offer(ev("other", "info", "Irgendwas", 1000 + 30 * 86400))
        for out, title in ((a, "Neue Version 1.4.0 verfügbar – Achtung beim Update"),
                           (b, "Neue Version 1.5.0 verfügbar – Achtung beim Update"),
                           (c, "Neue Version 1.5.1 verfügbar")):
            self.assertEqual([m["title"] for m in out], [title])
            self.assertFalse(out[0]["resolved"])
        self.assertEqual(a[0]["level"], "warn")
        self.assertFalse(any(m.get("resolved") for m in other))
        self.assertIn("update", events.KINDS)
        self.assertEqual(notify.KIND_LABELS["update"], "Update-Hinweis")
        # auch ohne Betreff (gleicher Schlüssel „update:“): die Art allein verhindert das Paaren
        bare = notify.ChannelRouter(channel(min_level="info", debounce_min=0), clock=lambda: 5000.0)
        self.assertEqual(len(bare.offer(ev("update", "warn", "Neue Version 1.4.0 – Achtung", 5000))), 1)
        self.assertEqual(len(bare.offer(ev("update", "warn", "Neue Version 1.5.0 – Achtung", 5000))), 1)
        last = bare.offer(ev("update", "info", "Neue Version 1.5.1 verfügbar", 5000))
        self.assertEqual([(m["title"], m["resolved"]) for m in last], [("Neue Version 1.5.1 verfügbar", False)])

    def test_resolved_can_be_switched_off(self):
        router = notify.ChannelRouter(channel(resolved=False), clock=lambda: 1000.0)
        router.offer(ev("gps", "warn", "GPS-Fix verloren", 1000))
        self.assertEqual(router.offer(ev("gps", "info", "GPS-Fix wieder da", 1050)), [])

    def test_notify_events_never_routed(self):
        self.assertEqual(self.offer("notify", "crit", "Kanal kaputt", 1000), [])

    def test_debounce_zero(self):
        router = notify.ChannelRouter(channel(debounce_min=0, min_level="info"), clock=lambda: 1000.0)
        self.assertEqual(len(router.offer(ev("source", "info", "a", 1000))), 1)
        self.assertEqual(len(router.offer(ev("source", "info", "b", 1000))), 1)

    def test_duration_format(self):
        self.assertEqual(notify.fmt_duration(42), "42 s")
        self.assertEqual(notify.fmt_duration(2400), "40 min")
        self.assertEqual(notify.fmt_duration(3 * 3600 + 120), "3 h 2 min")
        self.assertEqual(notify.fmt_duration(3 * 86400), "3 Tage")


# --------------------------------------------------------------------------- Filter
class EgressNotifyTest(unittest.TestCase):
    def test_purpose_known(self):
        self.assertIn("notify", egress.PURPOSES)
        egress.Sanitizer("notify")

    def test_only_allowlisted_fields(self):
        out = egress.notify_message({"title": "GPS-Fix verloren", "level": "crit", "kind": "gps", "time": 1.5e9,
                                     "data": {"lat": 52.52, "device": "/dev/ttyACM0"}, "secret": "x",
                                     "url": "http://nas.lan/"})
        self.assertEqual(set(out), {"title", "level", "kind", "time"})

    def test_coordinate_in_title_removed(self):
        out = egress.notify_message({"title": "Position 52.52001, 13.40495 gemeldet", "level": "warn"})
        self.assertNotIn("52.52", json.dumps(out))
        self.assertEqual(egress.check_no_leaks(out), [])

    def test_names_and_ips_filtered(self):
        out = egress.notify_message({"title": "Zeitquelle gewechselt: nas.home.lan → 203.0.113.9 (192.168.1.5)"},
                                    ["nas.home.lan"])
        text = out["title"]
        for leak in ("nas.home.lan", "203.0.113.9", "192.168.1.5"):
            self.assertNotIn(leak, text)
        self.assertIn("ptbtime1.ptb.de", egress.notify_message({"title": "Quelle ptbtime1.ptb.de"})["title"])

    def test_level_and_kind_normalised(self):
        out = egress.notify_message({"title": "x", "level": "boom", "kind": "Bad Kind"})
        self.assertEqual((out["level"], out["kind"]), ("info", "other"))

    def test_leak_raises(self):
        with mock.patch.object(egress, "check_no_leaks", return_value=[{"kind": "position"}]):
            with self.assertRaises(egress.NotifyLeak):
                egress.notify_message({"title": "x"})


# --------------------------------------------------------------------------- Versand
class DeliverTest(unittest.TestCase):
    def setUp(self):
        self.target = Target()
        self.clean = {"title": "GPS-Fix verloren", "text": "Kritisch · GPS · 01.11. 10:00 Uhr", "level": "crit",
                      "kind": "gps", "time": 1.5e9, "resolved": False}

    def tearDown(self):
        self.target.close()

    def test_webhook_with_signature(self):
        ch = channel(url=self.target.url + "/hook", secret="geheim")
        notify.deliver(ch, self.clean, "1.4.0")
        req = self.target.requests[0]
        self.assertEqual(req["path"], "/hook")
        body = json.loads(req["body"])
        self.assertEqual(body["title"], "GPS-Fix verloren")
        self.assertEqual(body["source"], "ntp-gui")
        expected = "sha256=" + hmac.new(b"geheim", req["body"], hashlib.sha256).hexdigest()
        self.assertEqual(req["headers"]["x-ntpgui-signature"], expected)
        self.assertEqual(req["headers"]["x-ntpgui-event"], "gps")

    def test_hmac_test_vector_from_readme(self):
        self.assertEqual(notify.signature("geheim", b'{"source":"ntp-gui","test":true}'),
                         "sha256=aa6b045120327114063405a2160f1f0e2257424dfb0c0a0728d2881de0104c6e")

    def test_ntfy_gotify_apprise_shapes(self):
        notify.deliver(channel(type="ntfy", url=self.target.url, topic="zeit", secret="tk"),
                       dict(self.clean, link="http://zeit.lan/#/gps"))
        notify.deliver(channel(type="gotify", url=self.target.url + "/", secret="apptoken"), self.clean)
        notify.deliver(channel(type="apprise", url=self.target.url, topic="ntp"), self.clean)
        notify.deliver(channel(type="apprise", url=self.target.url, secret="mailto://a:b@x.lan"), self.clean)
        ntfy, gotify, apprise_key, apprise_urls = self.target.requests
        payload = json.loads(ntfy["body"])
        self.assertEqual((ntfy["path"], payload["topic"], payload["priority"], payload["click"]),
                         ("/", "zeit", 5, "http://zeit.lan/#/gps"))
        self.assertEqual(ntfy["headers"]["authorization"], "Bearer tk")
        self.assertEqual(gotify["path"], "/message")
        self.assertEqual(gotify["headers"]["x-gotify-key"], "apptoken")
        self.assertEqual(json.loads(gotify["body"])["priority"], 8)
        self.assertEqual(apprise_key["path"], "/notify/ntp")
        self.assertEqual(json.loads(apprise_key["body"])["type"], "failure")
        self.assertEqual(apprise_urls["path"], "/notify/")
        self.assertEqual(json.loads(apprise_urls["body"])["urls"], "mailto://a:b@x.lan")

    def test_umlauts_in_title(self):
        notify.deliver(channel(type="ntfy", url=self.target.url, topic="zeit"),
                       dict(self.clean, title="Zeitquelle gewechselt: ä → ö"))
        self.assertIn("ä → ö", json.loads(self.target.requests[0]["body"])["title"])

    def test_redirect_not_followed(self):
        self.target.status, self.target.location = 302, self.target.url + "/elsewhere"
        with self.assertRaises(notify.DeliveryError) as ctx:
            notify.deliver(channel(url=self.target.url + "/hook"), self.clean)
        self.assertIn("Weiterleitung", str(ctx.exception))
        time.sleep(0.2)
        self.assertEqual(len(self.target.requests), 1)

    def test_http_error_and_auth(self):
        self.target.status = 500
        with self.assertRaisesRegex(notify.DeliveryError, "HTTP 500"):
            notify.deliver(channel(url=self.target.url), self.clean)
        self.target.status = 401
        with self.assertRaisesRegex(notify.DeliveryError, "Token"):
            notify.deliver(channel(url=self.target.url), self.clean)

    def test_timeout(self):
        self.target.delay = 1.0
        with mock.patch.object(notify, "TIMEOUT", 0.2), \
                self.assertRaisesRegex(notify.DeliveryError, "Zeitüberschreitung"):
            notify.deliver(channel(url=self.target.url), self.clean)

    def test_response_size_capped(self):
        self.target.body = b"x" * (notify.MAX_RESPONSE * 4)
        notify.deliver(channel(url=self.target.url), self.clean)  # liest höchstens MAX_RESPONSE, kein Fehler

    def test_connection_refused_text_has_no_url(self):
        with self.assertRaises(notify.DeliveryError) as ctx:
            notify.deliver(channel(url="http://127.0.0.1:9/geheim-pfad"), self.clean)
        self.assertNotIn("geheim", str(ctx.exception))
        self.assertNotIn("127.0.0.1", str(ctx.exception))

    def test_no_proxy_and_no_file_handler(self):
        names = {type(h).__name__ for h in notify._opener().handlers}
        self.assertNotIn("ProxyHandler", names)
        self.assertNotIn("FileHandler", names)
        self.assertNotIn("FTPHandler", names)
        self.assertNotIn("DataHandler", names)


# --------------------------------------------------------------------------- Speicher + Threads
class StoreTest(TempData):
    def test_secret_masked_and_kept(self):
        saved = notify.save_channel({"name": "Handy", "type": "gotify", "url": "https://gotify.lan",
                                     "secret": "SuperGeheim123"})
        flat = json.dumps(notify.api_config()) + json.dumps(notify.api_status()) + json.dumps(saved)
        self.assertNotIn("SuperGeheim123", flat)
        self.assertTrue(saved["secret_set"])
        notify.save_channel({"id": saved["id"], "name": "Handy 2"})           # Token bleibt
        self.assertEqual(notify.get_channel(saved["id"])["secret"], "SuperGeheim123")
        with self.assertRaises(notify.NotifyError):                          # Gotify ohne Token
            notify.save_channel({"id": saved["id"], "secret": ""})
        events_text = json.dumps(events.query(limit=50))
        self.assertNotIn("SuperGeheim123", events_text)
        self.assertNotIn("gotify.lan", events_text)

    def test_status_endpoint_has_no_url(self):
        notify.save_channel({"name": "Hook", "type": "webhook", "url": "https://hooks.example.org/x"})
        self.assertNotIn("hooks.example.org", json.dumps(notify.api_status()))

    def test_delete_and_limit(self):
        ids = [notify.save_channel({"name": f"k{i}", "type": "webhook", "url": "https://x.lan"})["id"]
               for i in range(notify.MAX_CHANNELS)]
        with self.assertRaises(notify.NotifyError):
            notify.save_channel({"name": "zu viel", "type": "webhook", "url": "https://x.lan"})
        self.assertTrue(notify.delete_channel(ids[0]))
        self.assertFalse(notify.delete_channel(ids[0]))
        self.assertFalse(notify.delete_channel("../etc"))

    def test_events_after_id_and_listener(self):
        calls = []
        events.add_listener(lambda: calls.append(1))
        events.emit("gps", "warn", "a")
        events.emit("gps", "info", "b")
        rows = events.after_id(0)
        self.assertEqual([r["title"] for r in rows], ["a", "b"])
        self.assertEqual(events.after_id(rows[0]["id"])[0]["title"], "b")
        self.assertEqual(events.max_id(), rows[1]["id"])
        self.assertEqual(len(calls), 2)


class EndToEndTest(TempData):
    def setUp(self):
        super().setUp()
        self.target = Target()

    def tearDown(self):
        self.target.close()
        super().tearDown()

    def add(self, **over):
        data = {"name": "Hook", "type": "webhook", "url": self.target.url + "/hook"}
        data.update(over)
        return notify.save_channel(data)["id"]

    def test_gps_crit_within_5s_exactly_one(self):
        self.add(kinds=["gps"])
        self.add(name="nur PPS", kinds=["pps"])
        notify.start("test")
        time.sleep(0.3)
        start = time.monotonic()
        events.emit("gps", "crit", "GPS-Fix verloren bei 52.52001, 13.40495", {"lat": 52.52001})
        self.assertTrue(self.target.wait(1, timeout=5.0))
        self.assertLess(time.monotonic() - start, 5.0)
        time.sleep(0.5)
        self.assertEqual(len(self.target.requests), 1)
        body = self.target.requests[0]["body"].decode()
        self.assertNotIn("52.52", body)
        self.assertNotIn("lat", json.loads(body))

    def test_ten_in_a_minute_then_resolved(self):
        self.add()
        notify.start("test")
        time.sleep(0.3)
        for _ in range(10):
            events.emit("gps", "warn", "GPS-Fix verloren")
        time.sleep(0.5)
        events.emit("gps", "info", "GPS-Fix wieder da")
        self.assertTrue(self.target.wait(2))
        time.sleep(0.5)
        titles = [json.loads(r["body"])["title"] for r in self.target.requests]
        self.assertEqual(len(titles), 2)
        self.assertEqual(titles[0], "GPS-Fix verloren")
        self.assertRegex(titles[1], r"^GPS-Fix wieder da – Dauer \d+ s$")

    def test_retry_then_drop_with_local_event(self):
        self.target.status = 500
        cid = self.add()
        with mock.patch.object(notify, "RETRY_DELAYS", (0.05, 0.05, 0.05)):
            notify.start("test")
            time.sleep(0.3)
            events.emit("service", "crit", "Pflichtdienst chronyd ausgefallen", {"service": "chronyd"})
            self.assertTrue(self.target.wait(4))
            end = time.monotonic() + 3
            dropped = []
            while time.monotonic() < end and not dropped:
                dropped = events.query(kinds=["notify"])
                time.sleep(0.05)
        self.assertEqual(len(self.target.requests), 4)
        self.assertIn("verworfen", dropped[0]["title"])
        status = notify.get_channel(cid)
        self.assertEqual((status["failed"], status["dropped"]), (4, 1))
        self.assertIn("HTTP 500", status["last_error"])
        time.sleep(0.5)
        self.assertEqual(len(self.target.requests), 4)  # das notify-Ereignis selbst geht nicht hinaus

    def test_rate_limit(self):
        cid = self.add(rate_per_hour=2, debounce_min=0)
        notify.start("test")
        time.sleep(0.3)
        for i in range(5):
            events.emit("service", "warn", f"Dienst d{i} beendet", {"service": f"d{i}"})
        self.target.wait(2)
        # Auf den Zustand warten statt fest zu schlafen: Auf einem ausgelasteten CI-Runner kam das
        # „verworfen“-Ereignis erst nach mehr als 0,8 s an.
        end = time.monotonic() + 5
        while time.monotonic() < end and (notify.get_channel(cid)["dropped"] < 3
                                           or not events.query(kinds=["notify"])):
            time.sleep(0.05)
        time.sleep(0.3)  # kein vierter Versand und kein zweites Ereignis hinterher
        self.assertEqual(len(self.target.requests), 2)
        self.assertEqual(notify.get_channel(cid)["dropped"], 3)
        self.assertEqual(len(events.query(kinds=["notify"])), 1)

    def test_rate_limit_event_shortly_after_boot(self):
        # Fehler aus der CI: monotonic() zählt ab Systemstart. War der Rechner kürzer als eine Stunde an,
        # blieb das „gedrosselt“-Ereignis aus, weil limit_noted mit 0.0 begann.
        real = time.monotonic
        start = real()
        # Nur notify sieht „120 s seit Systemstart“; die Warteschleifen des Tests laufen mit der echten Uhr.
        fake = types.SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
        fake.monotonic = lambda: 120.0 + real() - start
        with mock.patch.object(notify, "time", fake):
            self.test_rate_limit()

    def test_hanging_channel_blocks_nothing(self):
        slow = Target()
        slow.delay = 3.0
        try:
            self.add(name="langsam", url=slow.url)
            self.add(name="schnell")
            notify.start("test")
            time.sleep(0.3)
            events.emit("gps", "crit", "GPS-Fix verloren")
            self.assertTrue(self.target.wait(1, timeout=1.5))
        finally:
            slow.close()

    def test_disabled_channel_and_backlog(self):
        self.add(enabled=False)
        events.emit("gps", "crit", "vor dem Start")  # lag schon vor dem Start in der Datenbank
        notify.start("test")
        time.sleep(0.3)
        events.emit("gps", "crit", "GPS-Fix verloren")
        time.sleep(0.6)
        self.assertEqual(self.target.requests, [])

    def test_test_message(self):
        cid = self.add(secret="geheim")
        result = notify.send_test(cid)
        self.assertTrue(result["ok"])
        body = json.loads(self.target.requests[0]["body"])
        self.assertTrue(body["test"])
        self.assertEqual(result["status"]["state"], "ok")
        self.target.status = 302
        self.target.location = "http://example.org/"
        result = notify.send_test(cid)
        self.assertFalse(result["ok"])
        self.assertIn("Weiterleitung", result["error"])
        with self.assertRaises(notify.NotifyError):
            notify.send_test("nichtda00")

    def test_dashboard_link(self):
        settings.save({"notify_dashboard_url": "http://zeit.lan:8080/"})
        self.add()
        notify.start("test")
        time.sleep(0.3)
        events.emit("gps", "crit", "GPS-Fix verloren")
        self.assertTrue(self.target.wait(1))
        self.assertEqual(json.loads(self.target.requests[0]["body"])["link"], "http://zeit.lan:8080/#/gps")
        with self.assertRaises(settings.ValidationError):
            settings.save({"notify_dashboard_url": "javascript:alert(1)"})


class ScopeTest(unittest.TestCase):
    def test_scopes(self):
        import server  # noqa: F401 – trägt die Endpunkte ein
        self.assertEqual(apiv1.required_scope("GET", "/api/notify"), "admin")
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/notify"), "admin")
        self.assertEqual(apiv1.required_scope("GET", "/api/v1/notify/status"), "read")
        for path in ("/api/notify/channels", "/api/notify/channels/delete", "/api/notify/test"):
            self.assertEqual(apiv1.required_scope("POST", path), "admin")
        self.assertEqual(apiv1.resolve("/api/v1/notify/status"), "/api/notify/status")


# --------------------------------------------------------------------------- Prüfbefunde (1.4)
class RouterFindingsTest(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.router = notify.ChannelRouter(channel(), clock=lambda: self.now[0])

    def at(self, t, kind, level, title, data=None):
        self.now[0] = t
        return [m["title"] for m in self.router.offer(ev(kind, level, title, t, data))]

    def test_crit_never_waits_behind_pending_warn(self):
        gpsd = {"service": "gpsd"}
        self.assertEqual(self.at(0, "service", "warn", "Dienst gpsd beendet", gpsd), ["Dienst gpsd beendet"])
        self.assertEqual(self.at(10, "service", "info", "Dienst gpsd läuft wieder", gpsd),
                         ["Dienst gpsd läuft wieder – Dauer 10 s"])
        self.assertEqual(self.at(40, "service", "warn", "Dienst gpsd beendet", gpsd), [])      # entprellt
        self.assertEqual(self.at(50, "service", "info", "Dienst gpsd läuft wieder", gpsd), [])
        self.assertEqual(self.at(80, "service", "warn", "Dienst gpsd beendet", gpsd), [])      # wartet
        self.assertEqual(self.at(90, "service", "crit", "Pflichtdienst gpsd ausgefallen", gpsd),
                         ["Pflichtdienst gpsd ausgefallen"])

    def test_crit_after_resolved_goes_out_at_once(self):
        self.assertEqual(len(self.at(0, "gps", "warn", "GPS-Fix verloren")), 1)
        self.assertEqual(len(self.at(5, "gps", "info", "GPS-Fix wieder da")), 1)
        self.assertEqual(self.at(10, "gps", "crit", "GPS ausgefallen"), ["GPS ausgefallen"])
        # danach greift das Entprellen wieder: gleiches crit noch einmal → nichts Neues
        self.assertEqual(self.at(20, "gps", "crit", "GPS ausgefallen"), [])

    def test_warn_flapping_still_debounced(self):
        self.at(0, "gps", "warn", "GPS-Fix verloren")
        self.at(5, "gps", "info", "GPS-Fix wieder da")
        self.assertEqual(self.at(10, "gps", "warn", "GPS-Fix verloren"), [])

    def test_unrelated_info_does_not_resolve(self):
        self.assertEqual(len(self.at(0, "calibration", "warn", "GPS-Kalibrierung zurückgenommen: 0.1 s → 0.0 s")), 1)
        self.assertEqual(self.at(7200, "calibration", "info", "GPS-Kalibrierung: neuer Vorschlag 0.12 s"), [])
        self.assertIsNotNone(self.router.state["calibration:"]["open_since"])

    def test_resolves_flag_and_kinds(self):
        self.assertTrue(notify.resolves(ev("gps", "info", "x", 0)))
        self.assertFalse(notify.resolves(ev("calibration", "info", "x", 0)))
        self.assertTrue(notify.resolves(ev("client_clock", "info", "x", 0, {"resolves": True})))
        self.assertFalse(notify.resolves(ev("gps", "info", "x", 0, {"resolves": False})))
        self.at(0, "client_clock", "warn", "Uhr weicht ab")
        self.assertEqual(self.at(60, "client_clock", "info", "Uhr wieder im Rahmen", {"resolves": True}),
                         ["Uhr wieder im Rahmen – Dauer 1 min"])

    def test_client_alarms_are_separate_subjects(self):
        a, b = {"address": "192.168.1.20"}, {"address": "192.168.1.21"}
        self.assertEqual(len(self.at(0, "clients", "warn", "Uhr von A weicht ab", a)), 1)
        self.assertEqual(len(self.at(1, "clients", "warn", "Uhr von B weicht ab", b)), 1)
        self.assertEqual(self.at(60, "clients", "info", "Uhr von B wieder im Rahmen", b),
                         ["Uhr von B wieder im Rahmen – Dauer 59 s"])
        self.assertIsNotNone(self.router.state["clients:192.168.1.20"]["open_since"])


class Dripper:
    """Ziel, das Kopfzeilen und dann den Body byteweise langsam schickt (oder schon die Kopfzeilen)."""

    def __init__(self, headers_too=False, step=0.1):
        import socket as _socket
        self.sock = _socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/"
        self.headers_too, self.step, self.stop = headers_too, step, False
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        try:
            conn.recv(65536)
            head = b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n"
            data = head + b"x" * 1000 if self.headers_too else b"x" * 1000
            if not self.headers_too:
                conn.sendall(head)
            for i in range(len(data)):
                if self.stop:
                    break
                conn.sendall(data[i:i + 1])
                time.sleep(self.step)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.stop = True
        self.sock.close()


class DeadlineTest(unittest.TestCase):
    clean = {"title": "x", "text": "y", "level": "warn", "kind": "gps", "time": 1.5e9}

    def check(self, target):
        start = time.monotonic()
        with mock.patch.object(notify, "TIMEOUT", 0.6), \
                self.assertRaisesRegex(notify.DeliveryError, "Zeitüberschreitung"):
            notify.deliver(channel(url=target.url), self.clean)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_dripping_body_hits_total_deadline(self):
        target = Dripper()
        try:
            self.check(target)
        finally:
            target.close()

    def test_dripping_headers_hit_total_deadline(self):
        target = Dripper(headers_too=True)
        try:
            self.check(target)
        finally:
            target.close()

    def test_slow_name_resolution_hits_deadline(self):
        def slow(*args, **kwargs):
            time.sleep(3)
            raise OSError("zu spät")
        start = time.monotonic()
        with mock.patch.object(notify.socket, "getaddrinfo", slow), mock.patch.object(notify, "TIMEOUT", 0.4), \
                self.assertRaisesRegex(notify.DeliveryError, "Zeitüberschreitung"):
            notify.deliver(channel(url="http://ziel.lan/"), self.clean)
        self.assertLess(time.monotonic() - start, 1.5)

    def test_send_test_bounded(self):
        target = Dripper()
        tmp = tempfile.mkdtemp()
        saved = settings.DATA_DIR
        try:
            settings.DATA_DIR = os.path.join(tmp, "data")
            notify._reset_for_tests()
            with mock.patch.object(notify, "_known", return_value=([], {})):
                cid = notify.save_channel({"name": "x", "type": "webhook", "url": target.url})["id"]
                start = time.monotonic()
                with mock.patch.object(notify, "TIMEOUT", 0.6):
                    result = notify.send_test(cid)
            self.assertFalse(result["ok"])
            self.assertIn("Zeitüberschreitung", result["error"])
            self.assertLess(time.monotonic() - start, 2.0)
        finally:
            target.close()
            notify._reset_for_tests()
            events._LISTENERS.clear()
            store.close_all()
            settings.DATA_DIR = saved
            shutil.rmtree(tmp, ignore_errors=True)


class UrlFormsTest(unittest.TestCase):
    def test_ntfy_topic_in_url_is_moved_out(self):
        clean = notify.validate({"name": "x", "type": "ntfy", "url": "https://ntfy.sh/zeitserver-8f3k",
                                 "topic": "zeitserver-8f3k"})
        self.assertEqual((clean["url"], clean["topic"]), ("https://ntfy.sh", "zeitserver-8f3k"))
        clean = notify.validate({"name": "x", "type": "ntfy", "url": "https://ntfy.sh/zeitserver-8f3k/"})
        self.assertEqual((clean["url"], clean["topic"]), ("https://ntfy.sh", "zeitserver-8f3k"))
        url, _body, _h = notify.build_request(dict(channel(type="ntfy"), **clean), {"title": "t"})
        self.assertEqual(url, "https://ntfy.sh/")

    def test_query_rejected_for_server_types(self):
        for kind, extra in (("gotify", {"secret": "tok"}), ("ntfy", {"topic": "t"}), ("apprise", {"topic": "k"})):
            with self.subTest(kind=kind), self.assertRaisesRegex(notify.NotifyError, "ohne"):
                notify.validate(dict({"name": "x", "type": kind, "url": "http://srv.lan/?x=1"}, **extra))
        # Webhooks dürfen eine Abfrage haben
        notify.validate({"name": "x", "type": "webhook", "url": "http://srv.lan/hook?x=1"})

    def test_paths_joined_properly(self):
        url, _b, _h = notify.build_request(channel(type="gotify", url="http://g.lan/sub/?x=1", secret="t"), {})
        self.assertEqual(url, "http://g.lan/sub/message?x=1")
        url, _b, _h = notify.build_request(channel(type="apprise", url="http://apprise:8000/", topic="ntp"), {})
        self.assertEqual(url, "http://apprise:8000/notify/ntp")


class SecretGuardTest(TempData):
    def test_secret_not_reused_for_new_target(self):
        cid = notify.save_channel({"name": "G", "type": "gotify", "url": "http://gotify.lan",
                                   "secret": "AppTokenSECRET123"})["id"]
        for change in ({"url": "http://127.0.0.1:9999"}, {"url": "https://gotify.lan"},
                       {"url": "http://gotify.lan:8080"}, {"type": "ntfy", "topic": "zeit"}):
            with self.subTest(change=change), self.assertRaisesRegex(notify.NotifyError, "Token neu"):
                notify.save_channel(dict({"id": cid}, **change))
        self.assertEqual(notify.get_channel(cid)["url"], "http://gotify.lan")
        notify.save_channel({"id": cid, "url": "http://gotify.lan/"})           # gleiches Ziel: bleibt
        self.assertEqual(notify.get_channel(cid)["secret"], "AppTokenSECRET123")
        notify.save_channel({"id": cid, "url": "http://neu.lan", "secret": "NeuesToken"})
        self.assertEqual(notify.get_channel(cid)["secret"], "NeuesToken")
        cid2 = notify.save_channel({"name": "A", "type": "apprise", "url": "http://apprise:8000",
                                    "secret": "mailto://user:MailPass@mail.lan"})["id"]
        with self.assertRaises(notify.NotifyError):
            notify.save_channel({"id": cid2, "url": "http://boese.lan"})
        notify.save_channel({"id": cid2, "url": "http://boese.lan", "secret": "", "topic": "ntp"})  # ausdrücklich entfernt
        self.assertEqual(notify.get_channel(cid2)["secret"], "")

    def test_url_path_masked_and_kept(self):
        saved = notify.save_channel({"name": "HA", "type": "webhook",
                                     "url": "http://homeassistant.lan:8123/api/webhook/geheime-id-42"})
        self.assertEqual(saved["url"], "http://homeassistant.lan:8123/…")
        self.assertTrue(saved["url_hidden"])
        self.assertNotIn("geheime-id-42", json.dumps(notify.api_config()) + json.dumps(notify.api_status()))
        notify.save_channel({"id": saved["id"], "name": "HA 2", "url": ""})     # leer = behalten
        self.assertEqual(notify.get_channel(saved["id"])["url"],
                         "http://homeassistant.lan:8123/api/webhook/geheime-id-42")
        plain = notify.save_channel({"name": "N", "type": "ntfy", "url": "https://ntfy.sh", "topic": "t"})
        self.assertEqual((plain["url"], plain["url_hidden"]), ("https://ntfy.sh", False))

    def test_status_for_read_keys_has_no_name(self):
        notify.save_channel({"name": "Handy von Max", "type": "webhook", "url": "https://x.lan"})
        status = notify.api_status()
        self.assertNotIn("Handy von Max", json.dumps(status))
        self.assertEqual(set(status["channels"][0]), {"id", "type", "enabled", "status"})

    def test_token_over_plain_http_only_locally(self):
        base = {"name": "n", "type": "ntfy", "topic": "zeit", "secret": "tk_x"}
        for url in ("http://ntfy.sh", "http://9.9.9.9", "http://push.example.org"):
            with self.subTest(url=url), self.assertRaisesRegex(notify.NotifyError, "https"):
                notify.validate(dict(base, url=url))
        for url in ("https://ntfy.sh", "http://ntfy.lan", "http://192.168.1.5:8080", "http://apprise:8000",
                    "http://[fd00::1]", "http://box.home.arpa", "http://127.0.0.1:9"):
            with self.subTest(url=url):
                notify.validate(dict(base, url=url))
        notify.validate({"name": "n", "type": "webhook", "url": "http://hooks.example.org/x"})  # ohne Token


class PositionTest(TempData):
    def test_restart_does_not_resend(self):
        target = Target()
        try:
            notify.save_channel({"name": "Hook", "type": "webhook", "url": target.url + "/hook"})
            notify.start("test")
            time.sleep(0.3)
            events.emit("gps", "warn", "GPS-Fix verloren")
            events.emit("service", "crit", "Pflichtdienst gpsd ausgefallen", {"service": "gpsd"})
            self.assertTrue(target.wait(2))
            time.sleep(0.3)
            rows = store.query("SELECT value FROM notify_meta WHERE key='last_id'")
            self.assertEqual(int(rows[0][0]), events.max_id())                # sofort gesichert, nicht erst nach 10 s
            notify._reset_for_tests()                                         # „Neustart“
            notify.start("test")
            time.sleep(0.8)
            events.emit("settings", "info", "weckt den Verteiler")
            time.sleep(0.6)
            self.assertEqual(len(target.requests), 2)
        finally:
            target.close()

    def test_stop_flushes_position(self):
        notify._ensure()
        n = notify.Notifier()
        n.last_id, n.saved_id, n.saved_at = 42, 0, time.monotonic()
        n._save_position()                                                    # gedrosselt: nichts
        self.assertEqual(store.query("SELECT value FROM notify_meta WHERE key='last_id'"), [])
        n.stop()
        self.assertEqual(store.query("SELECT value FROM notify_meta WHERE key='last_id'")[0][0], "42")


class KnownNamesTest(unittest.TestCase):
    def setUp(self):
        notify._KNOWN.update(t=0.0, ok=False, names=[], values={})

    def tearDown(self):
        notify._KNOWN.update(t=0.0, ok=False, names=[], values={})

    def test_fails_closed_without_previous_list(self):
        import diagnostics
        with mock.patch.object(diagnostics, "_known_names", side_effect=RuntimeError("kaputt")):
            with self.assertRaises(egress.NotifyLeak):
                notify._known()
            with self.assertRaises(egress.NotifyLeak):
                notify.outgoing({"title": "x", "level": "warn", "kind": "gps"})

    def test_keeps_previous_list_on_failure(self):
        import diagnostics
        with mock.patch.object(diagnostics, "_known_names", return_value=["zeitserver"]), \
                mock.patch.object(diagnostics, "_client_names", return_value=[]):
            self.assertEqual(notify._known()[0], ["zeitserver"])
        notify._KNOWN["t"] = -1e9  # abgelaufen
        with mock.patch.object(diagnostics, "_known_names", side_effect=RuntimeError("kaputt")):
            self.assertEqual(notify._known()[0], ["zeitserver"])
            out = notify.outgoing({"title": "Dienst auf zeitserver neu gestartet", "level": "warn", "kind": "service"})
        self.assertNotIn("zeitserver", out["title"])


class NotifyCoordTest(unittest.TestCase):
    def test_written_zeros_count(self):
        for title in ("GPS-Position 52.5200, 13.4050 erreicht", "52.52,13.40", "Ort 52.52 13.40", "48,14; 11,58",
                      "Position -33.87, 151.21", "52.5200 N, 13.4050 E"):
            with self.subTest(title=title):
                out = egress.notify_message({"title": title, "level": "warn"})
                self.assertIn("<koordinaten>", out["title"])
                for part in ("52.52", "13.40", "48,14", "151.21", "13.4050"):
                    self.assertNotIn(part, out["title"])

    def test_harmless_numbers_stay(self):
        for title in ("GPS-Kalibrierung zurückgenommen: 0.1 s → 0.0 s", "Uhr von PC weicht um +12.34 ms ab",
                      "Version 1.4.0 verfügbar", "Schaltsekunde am 31.12.2026", "Frequenz 0.25, 0.75 ppm"):
            with self.subTest(title=title):
                self.assertEqual(egress.notify_message({"title": title})["title"], title)


if __name__ == "__main__":
    unittest.main()
