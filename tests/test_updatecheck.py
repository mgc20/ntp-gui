"""Update-Hinweis (updatecheck.py) und Zweck „update_check“ im Filter (egress.py).

Abnahme aus docs/konzept/version-1.4.md, Thema 7:
* ausgeschaltet → null Netzzugriffe (Socket-Attrappe);
* eingeschaltet → genau eine Anfrage pro Tag gegen eine Attrappe;
* Kopfzeilen ohne Version und Kennung, keine Weiterleitungen.
"""

import json
import os
import random
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import egress  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import updatecheck  # noqa: E402

DAY = 86400
T0 = 1_800_000_000 - (1_800_000_000 % DAY)  # Tagesbeginn (UTC)


def release(tag="v1.4.0", name="ntp-gui 1.4.0", body="Neu: Benachrichtigungen", **extra):
    data = {"tag_name": tag, "name": name, "body": body, "draft": False, "prerelease": False,
            "html_url": "https://evil.example/phish", "published_at": "2026-11-01T10:00:00Z"}
    data.update(extra)
    return json.dumps(data).encode()


class FakeResponse:
    def __init__(self, body=b"{}", status=200):
        self.body, self.status = body, status

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, body):
        self.body = body
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        return FakeResponse(self.body)


class TempStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = self.tmp

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class VersionTest(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updatecheck.is_newer("1.4.0", "1.3.2"))
        self.assertTrue(updatecheck.is_newer("v1.10.0", "1.9.9"))
        self.assertTrue(updatecheck.is_newer("2.0.0", "1.99.99"))
        self.assertFalse(updatecheck.is_newer("1.3.2", "1.3.2"))
        self.assertFalse(updatecheck.is_newer("1.3.1", "1.3.2"))
        self.assertTrue(updatecheck.is_newer("1.4.0", "1.4.0-rc.1"))
        self.assertFalse(updatecheck.is_newer("1.4.0-rc.1", "1.4.0"))
        self.assertTrue(updatecheck.is_newer("1.4.0-rc.10", "1.4.0-rc.9"))
        self.assertIsNone(updatecheck.is_newer("1.4.0", "dev"))
        self.assertIsNone(updatecheck.is_newer("latest", "1.3.2"))
        self.assertEqual(updatecheck.plain_version("v1.4.0"), "1.4.0")
        self.assertIsNone(updatecheck.plain_version("v1.4.0/../../x"))


class ParseTest(unittest.TestCase):
    def test_link_is_built_not_taken(self):
        info = updatecheck.parse_release(release())
        self.assertEqual(info["version"], "1.4.0")
        self.assertEqual(info["url"], "https://github.com/ConGp20/ntp-gui/releases/tag/v1.4.0")
        self.assertNotIn("evil", json.dumps(info))
        self.assertFalse(info["attention"])
        self.assertEqual(info["published"], 1793527200.0)

    def test_attention_markers(self):
        for body in ("## BREAKING: Port 8080 → 8443", "**Achtung beim Update:** Volume prüfen", "⚠ alte Variablen entfallen"):
            with self.subTest(body=body):
                info = updatecheck.parse_release(release(body="Neu: X\n" + body))
                self.assertTrue(info["attention"])
                self.assertNotIn("*", info["attention_note"])
                self.assertNotIn("#", info["attention_note"])
        self.assertFalse(updatecheck.parse_release(release(body="breaking news? nein, kleine Fixes"))["attention"])

    def test_title_cleaned(self):
        info = updatecheck.parse_release(release(name="ntp-gui‮ 1.4\x00 " + "x" * 300))
        self.assertLessEqual(len(info["title"]), updatecheck.MAX_TITLE)
        self.assertNotIn("‮", info["title"])
        self.assertNotIn("\x00", info["title"])

    def test_rejects(self):
        for raw in (b"not json", b"[]", release(tag="latest"), release(prerelease=True), release(draft=True),
                    "\xff".encode("latin-1")):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(updatecheck.UpdateError):
                    updatecheck.parse_release(raw)


class EgressTest(unittest.TestCase):
    def test_purpose(self):
        self.assertIn("update_check", egress.PURPOSES)

    def test_fixed_request(self):
        url, headers = egress.update_check_request()
        self.assertEqual(url, "https://api.github.com/repos/ConGp20/ntp-gui/releases/latest")
        self.assertEqual(headers["User-Agent"], "ntp-gui")
        self.assertFalse(any(ch.isdigit() for value in headers.values() for ch in value))

    def test_rejects_version_id_or_other_target(self):
        bad = [
            dict(headers={"User-Agent": "ntp-gui/1.4.0"}),
            dict(headers={"User-Agent": "ntp-gui", "X-Instance": "abc"}),
            dict(headers={"User-Agent": "ntp-gui", "Accept": "application/json; id=12345"}),
            dict(headers={"Accept": "application/json"}),
            dict(url=egress.UPDATE_CHECK_URL + "?v=1.3.2"),
            dict(url="https://example.org/releases/latest"),
            # Werte ohne Ziffern, die trotzdem etwas über die Instanz verraten: Hostname, Ort, Base32-Kennung
            dict(headers={"User-Agent": "ntp-gui", "Accept": "zeitserver.fritz.box"}),
            dict(headers={"User-Agent": "ntp-gui", "Accept": "berlin-mitte"}),
            dict(headers={"User-Agent": "ntp-gui", "Accept": "mfrggzdfmztwq"}),
            dict(headers={"User-Agent": "ntp-gui", "Accept": "application/json"}),
        ]
        for kwargs in bad:
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                with self.assertRaises(egress.UpdateCheckRejected):
                    egress.update_check_request(**kwargs)


    def test_second_layer_runs_central_checks(self):
        # Auch wenn die erste Schicht später gelockert würde: check_no_leaks/backstop laufen mit.
        with mock.patch.object(egress, "check_no_leaks", wraps=egress.check_no_leaks) as leaks, \
                mock.patch.object(egress, "backstop", wraps=egress.backstop) as bs:
            egress.update_check_request()
        self.assertTrue(leaks.called)
        self.assertTrue(bs.called)
        text = egress._render_update_request(egress.UPDATE_CHECK_URL,
                                              {"User-Agent": "ntp-gui", "Accept": "zeitserver.fritz.box"})
        base = egress._render_update_request(egress.UPDATE_CHECK_URL, egress.UPDATE_CHECK_HEADERS)
        self.assertTrue(egress._update_findings(text) - egress._update_findings(base))


class FetchTest(unittest.TestCase):
    def test_request_shape(self):
        opener = FakeOpener(release())
        raw = updatecheck.fetch(opener)
        self.assertEqual(json.loads(raw)["tag_name"], "v1.4.0")
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, egress.UPDATE_CHECK_URL)
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("User-agent"), "ntp-gui")
        self.assertEqual(timeout, updatecheck.TIMEOUT)

    def test_real_opener_has_no_default_user_agent_or_proxy(self):
        opener = updatecheck._opener()
        self.assertEqual(opener.addheaders, [])
        kinds = {type(h) for h in opener.handlers}
        self.assertNotIn(urllib.request.ProxyHandler, kinds)
        self.assertNotIn(urllib.request.HTTPHandler, kinds, "nur https")
        self.assertNotIn(urllib.request.FileHandler, kinds)

    def test_size_limit(self):
        opener = FakeOpener(b"x" * (updatecheck.MAX_RESPONSE + 10))
        with self.assertRaisesRegex(updatecheck.UpdateError, "zu groß"):
            updatecheck.fetch(opener)

    def test_no_redirect(self):
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opener = updatecheck._opener()
            opener.add_handler(urllib.request.HTTPHandler())  # nur für den lokalen Test
            with self.assertRaisesRegex(updatecheck.UpdateError, "Weiterleitung"):
                try:
                    opener.open(f"http://127.0.0.1:{server.server_port}/start", timeout=5)
                except updatecheck.UpdateError:
                    raise
                except Exception as exc:  # urllib verpackt Fehler aus Handlern teils
                    raise updatecheck.UpdateError(updatecheck._describe(exc)) from None
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(hits, ["/start"], "keine zweite Anfrage an das Weiterleitungsziel")


class NoNetwork:
    """Socket-Attrappe: jeder Versuch, eine Verbindung oder DNS-Abfrage zu starten, wird gezählt."""

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


class ScheduleTest(TempStore):
    def checker(self, enabled=True, fetcher=None, seed=1, emit=None):
        return updatecheck.Checker("1.3.2", lambda: enabled, fetcher=fetcher or (lambda: release()),
                                   state=updatecheck.Store(), rng=random.Random(seed), emit=emit)

    def test_disabled_makes_no_network_access(self):
        # Echter Abruf (fetch) – ausgeschaltet darf er nie erreicht werden.
        check = updatecheck.Checker("1.3.2", lambda: False, state=updatecheck.Store(), rng=random.Random(3))
        with NoNetwork() as net:
            for minute in range(0, 3 * 24 * 60, 7):
                self.assertFalse(check.tick(T0 + minute * 60))
            status = check.status(T0)
            # auch der echte Thread nicht
            stop = threading.Event()
            thread = threading.Thread(target=updatecheck.run, args=(check, stop, 0.005))
            thread.start()
            threading.Event().wait(0.1)
            stop.set()
            thread.join(2)
        self.assertEqual(net.calls, [])
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["next_check"])
        self.assertIsNone(status["latest"])
        self.assertEqual(updatecheck.insights(status), [])

    def test_settings_default_off(self):
        field = next(f for f in settings.SCHEMA if f["key"] == "update_check")
        self.assertIs(field["default"], False)
        self.assertEqual(field["env"], "UPDATE_CHECK")
        self.assertIn("öffentliche IP", field["help"])

    def test_exactly_one_request_per_day(self):
        calls = []

        def fetcher():
            calls.append(1)
            return release()

        check = self.checker(fetcher=fetcher)
        per_day = {}
        for minute in range(0, 5 * 24 * 60):
            now = T0 + minute * 60
            if check.tick(now):
                per_day[now // DAY] = per_day.get(now // DAY, 0) + 1
        self.assertEqual(len(calls), 5)
        self.assertEqual(sorted(per_day.values()), [1, 1, 1, 1, 1])

    def test_random_time_of_day(self):
        times = []
        for seed in range(6):
            check = updatecheck.Checker("1.3.2", lambda: True, fetcher=lambda: release(),
                                        state=updatecheck.Store(), rng=random.Random(seed))
            check.state.save({})
            check.data = {}
            for minute in range(0, 24 * 60):
                if check.tick(T0 + minute * 60):
                    times.append(minute)
                    break
        self.assertEqual(len(times), 6)
        self.assertGreater(len(set(times)), 3, "jeder Tag/jede Instanz würfelt eine eigene Uhrzeit")

    def test_failure_does_not_retry_same_day_and_restart_keeps_count(self):
        calls = []

        def failing():
            calls.append(1)
            raise updatecheck.UpdateError("GitHub nicht erreichbar")

        check = self.checker(fetcher=failing)
        for minute in range(0, 24 * 60):
            check.tick(T0 + minute * 60)
        self.assertEqual(len(calls), 1)
        self.assertEqual(check.status(T0 + DAY - 1)["error"], "GitHub nicht erreichbar")
        # Neustart am selben Tag: neuer Checker, gleiche Datenbank, neue Zufallszeit → keine zweite Anfrage
        again = self.checker(fetcher=failing, seed=99)
        for minute in range(0, 24 * 60, 5):
            again.tick(T0 + minute * 60)
        self.assertEqual(len(calls), 1)

    def test_status_insight_and_event(self):
        emitted = []
        check = self.checker(fetcher=lambda: release(body="**Achtung beim Update:** neues Volume"),
                             emit=lambda *a: emitted.append(a))
        check.check(T0 + 100)
        check.check(T0 + DAY + 100)
        status = check.status(T0 + DAY + 200)
        self.assertTrue(status["available"])
        self.assertTrue(status["attention"])
        self.assertEqual(status["latest"]["version"], "1.4.0")
        self.assertGreater(status["next_check"], T0 + DAY + 200)
        self.assertEqual(len(emitted), 1, "Ereignis nur einmal je neuer Version")
        self.assertEqual(emitted[0][0], "update")
        self.assertEqual(emitted[0][1], "warn")
        self.assertEqual(emitted[0][3]["subject"], "update:1.4.0")
        self.assertIs(emitted[0][3]["resolves"], False)
        found = updatecheck.insights(status)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["key"], "update_available")
        self.assertIn("Neue Version 1.4.0 verfügbar", found[0]["title"])
        self.assertIn("Achtung beim Update", found[0]["text"])
        self.assertIn("Diun", found[0]["text"])
        self.assertNotIn("Watchtower ist", found[0]["text"].replace("Watchtower ist seit", ""))
        self.assertTrue(found[0]["link"].startswith("https://github.com/ConGp20/ntp-gui/releases/"))

    def test_status_not_blocked_by_slow_fetch(self):
        """/api/status und /metrics dürfen nie auf GitHub warten (Sperre nicht während der Anfrage)."""
        started, release_fetch = threading.Event(), threading.Event()

        self.addCleanup(release_fetch.set)

        def slow():
            started.set()
            release_fetch.wait(30)  # hängt den ganzen Test über: ein Warten fiele mit ~30 s auf
            return release()

        check = self.checker(fetcher=slow)
        check.slots[T0 // DAY] = 0.0
        worker = threading.Thread(target=check.tick, args=(T0 + 10,))
        worker.start()
        try:
            self.assertTrue(started.wait(10))
            t = time.monotonic()
            status = check.status(T0 + 11)
            self.assertLess(time.monotonic() - t, 5, "status() hat auf den Abruf gewartet")
            self.assertEqual(status["last_attempt"], T0 + 10)
            self.assertFalse(check.tick(T0 + 12), "kein zweiter Abruf, solange einer läuft")
        finally:
            release_fetch.set()
            worker.join(5)
        self.assertEqual(check.status(T0 + 20)["latest"]["version"], "1.4.0")

    def test_overall_deadline(self):
        hang = threading.Event()
        self.addCleanup(hang.set)
        # Der Abruf hängt 30 s; die Frist (0,2 s) muss das deutlich abkürzen. Die Reserve bis 10 s
        # gilt Thread-Wechseln und SQLite-Schreibvorgängen auf einem vollen Runner (2,2 s gesehen).
        check = updatecheck.Checker("1.3.2", lambda: True, fetcher=lambda: hang.wait(30) and release(),
                                    state=updatecheck.Store(), rng=random.Random(1), deadline=0.2)
        t = time.monotonic()
        data = check.check(T0 + 5)
        self.assertLess(time.monotonic() - t, 10)
        self.assertIn("Zeitüberschreitung", data["error"])
        self.assertEqual(updatecheck.DEADLINE, 20.0)

    def test_same_or_older_version_no_hint(self):
        check = self.checker(fetcher=lambda: release(tag="v1.3.2"))
        check.check(T0)
        status = check.status(T0)
        self.assertFalse(status["available"])
        self.assertEqual(updatecheck.insights(status), [])

    def test_disabled_hides_stored_result(self):
        enabled = [True]
        check = updatecheck.Checker("1.3.2", lambda: enabled[0], fetcher=lambda: release(),
                                    state=updatecheck.Store(), rng=random.Random(1))
        check.check(T0)
        self.assertTrue(check.status(T0)["available"])
        enabled[0] = False
        status = check.status(T0)
        self.assertFalse(status["available"])
        self.assertIsNone(status["latest"])


class ServerWiringTest(TempStore):
    def test_metrics_and_status(self):
        import server
        check = updatecheck.Checker(server.VERSION, lambda: True, fetcher=lambda: release(tag="v99.0.0"),
                                    state=updatecheck.Store(), rng=random.Random(1))
        check.check(T0)
        with mock.patch.object(updatecheck, "CHECKER", check), \
                mock.patch.object(server.chrony, "tracking", return_value={}), \
                mock.patch.object(server.chrony, "detailed_sources", return_value=[]), \
                mock.patch.object(server.chrony, "serverstats", return_value={}), \
                mock.patch.object(server.chrony, "clients", return_value=[]), \
                mock.patch.object(server.chrony, "nts_server_status", return_value={"enabled": False}), \
                mock.patch.object(server.gps, "status", return_value={"enabled": False}), \
                mock.patch.object(server.ptp, "status", return_value={"enabled": False}):
            text = server.build_metrics()
        self.assertIn("ntpgui_update_available 1", text)
        self.assertIn("ntpgui_update_check_last_success_timestamp_seconds", text)


if __name__ == "__main__":
    unittest.main()
