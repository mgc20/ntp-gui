"""„Heute“-Zeitleiste (1.6, T7): Zustandsband, Ereignismarker, Tagesbericht, Zeitpunkt.

Akzeptanzkriterien aus docs/konzept/version-1.6.md (T7):
  * Replay eines Tages mit 3 bekannten Ereignissen: genau 3 Marker an den richtigen Stellen
    (± 1 Fenster), das Band zeigt die Holdover-Phase.
  * Kennzahlen des Tagesberichts stimmen mit einer unabhängigen SQL-Rechnung überein.
  * Band aus dem vorverdichteten Verlauf: mit 30 Tagen Verlauf < 500 ms.
Dazu: Datenschutz (Zeitpunkt nur mit fester Feldliste, Satelliten als Anzahl) und die Endpunkte unter
/api und /api/v1 mit Leserecht. Nur Beispielwerte; keine echten Adressen oder Orte.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import apiv1  # noqa: E402
import events  # noqa: E402
import history  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import timeline  # noqa: E402

STEP = 30  # s zwischen zwei Messpunkten im Replay


def point(t, offset=0.0002, selected=True, clients=8, gps_mode=3, pi_state=0, used=9, seen=14):
    """Ein Messpunkt wie server.collect_sample – mit Beispielquellen aus RFC 5737."""
    return {"t": int(t), "offset": offset, "rms": 0.0001, "root_delay": 0.0004, "root_dispersion": 0.0003,
            "stratum": 2, "served": 100, "clients": clients, "pi_state": pi_state,
            "sources": {"192.0.2.1": {"o": offset, "s": "*" if selected else "-", "k": "^"},
                        "198.51.100.7": {"o": 0.0004, "s": "+" if selected else "-", "k": "^"}},
            "gps": {"used": used, "seen": seen, "hdop": 0.9, "snr": 33.0, "mode": gps_mode, "cn4": 38.0}}


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        os.makedirs(settings.DATA_DIR)
        env = mock.patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        for key in ("HISTORY_SIZE", "HISTORY_DAYS"):
            os.environ.pop(key, None)
        timeline.reset_cache()

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        timeline.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self):
        return history.History(8640, os.path.join(settings.DATA_DIR, "history.json.gz"))

    def event(self, t, kind, level, title, data=None):
        events._write([events._clean(kind, level, title, data, "web", t)])


class StateTest(unittest.TestCase):
    def test_sample_state(self):
        self.assertEqual(timeline.sample_state(point(0)), "good")
        self.assertEqual(timeline.sample_state(point(0, offset=-0.007)), "warn")
        self.assertEqual(timeline.sample_state(point(0, offset=0.06)), "crit")
        self.assertEqual(timeline.sample_state(point(0, selected=False)), "holdover")
        self.assertEqual(timeline.sample_state(point(0, selected=False, offset=0.2)), "crit")
        self.assertEqual(timeline.sample_state({"t": 0, "offset": None, "sources": {}}), "crit")

    def test_bucket_state_quarter_rule(self):
        self.assertEqual(timeline.bucket_state({"g": 28, "c": 2}), "g")   # einzelner Ausreißer färbt nicht
        self.assertEqual(timeline.bucket_state({"g": 20, "h": 10}), "h")
        self.assertEqual(timeline.bucket_state({"g": 10, "w": 10, "c": 10}), "c")
        self.assertEqual(timeline.bucket_state({}), "n")
        self.assertEqual(timeline.bucket_state(None), "n")

    def test_bucket_matches_rollup(self):
        self.assertEqual(timeline.BUCKET, history.ROLLUP_SECONDS)

    def test_marker_groups(self):
        g = timeline.marker_group
        self.assertEqual(g("source", "info", "Zeitquelle gewechselt: 192.0.2.1 → 198.51.100.7"), "source")
        self.assertEqual(g("gps", "warn", "GPS-Fix verloren"), "gps")
        self.assertIsNone(g("gps", "info", "GPS-Fix wieder da"))
        self.assertEqual(g("startup", "info", "ntp-gui gestartet"), "restart")
        self.assertEqual(g("reload", "info", "Neue Einstellungen aktiv", {"result": "done"}), "restart")
        self.assertIsNone(g("reload", "info", "zurückgestellt", {"reason": "holdover"}))
        self.assertEqual(g("pi", "warn", "Unterspannung"), "pi")
        self.assertIsNone(g("settings", "info", "Einstellungen gespeichert"))
        self.assertEqual(g("dns", "warn", "DNS gestört"), "warn")


class ReplayTest(TempData):
    """Ein Tag mit Holdover 03:00–04:30, GPS-Fix weg 10:00–13:00 und drei bekannten Ereignissen."""

    def setUp(self):
        super().setUp()
        self.day0, self.day1 = timeline.day_bounds(time.time() - 3 * 86400, days_back=1)
        self.hist = self.make()
        d0 = self.day0
        self.holdover = (d0 + 3 * 3600, d0 + 4.5 * 3600)
        self.gps_off = (d0 + 10 * 3600, d0 + 13 * 3600)
        for t in range(int(d0) - 3600, int(self.day1) + 3600, STEP):
            in_hold = self.holdover[0] <= t < self.holdover[1]
            no_fix = self.gps_off[0] <= t < self.gps_off[1]
            offset = 0.0002 + (0.0001 if (t // STEP) % 2 else -0.0001)
            if t == int(d0 + 15 * 3600):
                offset = -0.0012                       # schlechtester Wert des Tages
            if d0 + 18 * 3600 <= t < d0 + 18 * 3600 + 600:
                offset = 0.008                         # 10 min Warnung
            clients = 12 if d0 + 12 * 3600 <= t < d0 + 13 * 3600 else 8
            if t >= self.day1 or t < d0:
                clients, offset = 40, 0.5               # außerhalb des Tages – darf nicht zählen
            self.hist.add(point(t, offset=offset, selected=not in_hold, clients=clients,
                                gps_mode=1 if no_fix else 3))
        self.assertTrue(self.hist.save(force=True))
        # Drei bekannte Ereignisse …
        self.known = [(d0 + 3 * 3600 + 20, "source", "warn", "Keine Zeitquelle mehr ausgewählt", None, "source"),
                      (d0 + 10 * 3600 + 70, "gps", "warn", "GPS-Fix verloren", None, "gps"),
                      (d0 + 14 * 3600 + 47 * 60, "startup", "info", "ntp-gui gestartet", {"version": "1.6.0"}, "restart")]
        for t, kind, level, title, data, _group in self.known:
            self.event(t, kind, level, title, data)
        # … und Rauschen, das keinen Marker ergeben darf.
        self.event(d0 + 5 * 3600, "settings", "info", "Einstellungen gespeichert")
        self.event(d0 + 13 * 3600, "gps", "info", "GPS-Fix wieder da")
        self.event(d0 + 16 * 3600, "api", "info", "API-Schlüssel benutzt")
        self.event(d0 + 17 * 3600, "reload", "info", "Neustart zurückgestellt", {"reason": "holdover"})
        self.now = self.day1 - 1

    def test_exactly_three_markers_at_right_place(self):
        result = timeline.build(self.hist, now=self.now)
        self.assertEqual(result["start"], self.day0)
        self.assertEqual(len(result["states"]), timeline.BUCKETS)
        marks = result["markers"]
        self.assertEqual(len(marks), 3, marks)
        for mark, (t, _kind, level, title, _data, group) in zip(marks, self.known):
            expected = int((t - self.day0) // timeline.BUCKET)
            self.assertLessEqual(abs(mark["b"] - expected), 1, mark)
            self.assertEqual((mark["group"], mark["level"], mark["title"]), (group, level, title))
            self.assertNotIn("data", mark)

    def test_band_shows_holdover_phase(self):
        result = timeline.build(self.hist, now=self.now)
        holds = [r for r in result["runs"] if r["state"] == "holdover"]
        self.assertEqual(len(holds), 1, result["runs"])
        self.assertLessEqual(abs(holds[0]["from"] - self.holdover[0]), timeline.BUCKET)
        self.assertLessEqual(abs(holds[0]["to"] - self.holdover[1]), timeline.BUCKET)
        warns = [r for r in result["runs"] if r["state"] == "warn"]
        self.assertEqual(len(warns), 1, result["runs"])
        self.assertEqual(result["states"][0], "g")
        self.assertNotIn("n", result["states"])

    def test_band_reads_rollup_not_raw(self):
        # Rohverlauf leeren: Das Band kommt allein aus der Vorverdichtung.
        with store.transaction() as conn:
            conn.execute("DELETE FROM samples")
        result = timeline.build(self.hist, now=self.now)
        self.assertEqual(len([r for r in result["runs"] if r["state"] == "holdover"]), 1)

    def test_pending_buffer_counts(self):
        # Messpunkte im Puffer (noch nicht geschrieben) erscheinen sofort im Band.
        t = int(self.day1) + 7200
        for i in range(10):
            self.hist.add(point(t + i * STEP, selected=False))
        result = timeline.build(self.hist, now=t + 9 * STEP)
        self.assertEqual(result["states"][-1], "h")

    def test_report_matches_independent_sql(self):
        report = timeline.daily_report(self.hist, self.day0, self.day1)
        sql = """
        WITH d AS (SELECT t, json FROM samples WHERE t >= :d0 AND t < :d1),
        w AS (SELECT t, json, min(max(lead(t, 1, :d1) OVER (ORDER BY t) - t, 0), 600) AS w FROM d)
        SELECT sum(w),
               sum(CASE WHEN abs(json_extract(json, '$.offset')) < 0.05 AND EXISTS (
                   SELECT 1 FROM json_each(w.json, '$.sources') s WHERE json_extract(s.value, '$.s') = '*')
                   THEN w ELSE 0 END),
               max(abs(json_extract(json, '$.offset'))),
               max(json_extract(json, '$.clients')),
               sum(CASE WHEN json_extract(json, '$.gps.mode') >= 2 THEN w ELSE 0 END),
               max(json_extract(json, '$.pi_state')),
               count(*)
          FROM w"""
        covered, synced, worst, devices, gps_s, pi, count = store.query(sql, {"d0": self.day0, "d1": self.day1})[0]
        self.assertEqual(report["samples"], count)
        self.assertAlmostEqual(report["covered_s"], covered, places=6)
        self.assertAlmostEqual(report["synced_pct"], 100 * synced / covered, places=6)
        self.assertAlmostEqual(report["worst_offset"], worst, places=9)
        self.assertEqual(report["devices"], devices)
        self.assertAlmostEqual(report["gps_hours"], gps_s / 3600, places=6)
        self.assertEqual(report["pi_state"], pi)
        # Und die erwarteten Werte des Replays.
        self.assertEqual(report["devices"], 12)
        self.assertAlmostEqual(report["worst_offset"], 0.008)
        self.assertAlmostEqual(report["gps_hours"], 21, delta=0.02)
        self.assertAlmostEqual(report["synced_pct"], 100 * (24 - 1.5) / 24, delta=0.05)
        self.assertEqual(report["pi_state"], 0)

    def test_cached_report_is_yesterday(self):
        report = timeline.build(self.hist, now=self.day1 + 3600)["report"]
        self.assertEqual(report["start"], self.day0)
        self.assertEqual(report["day"], time.strftime("%Y-%m-%d", time.localtime(self.day0 + 1)))

    def test_moment_nearest_point(self):
        at = self.holdover[0] + 200 + 7
        result = timeline.moment(self.hist, at)
        sample = result["sample"]
        self.assertEqual(tuple(sample), timeline.MOMENT_KEYS)
        self.assertLessEqual(abs(sample["t"] - at), STEP / 2)
        self.assertEqual(sample["state"], "holdover")
        self.assertIsNone(sample["source"])
        self.assertEqual(sample["satellites"], {"used": 9, "seen": 14})
        self.assertAlmostEqual(sample["bound"], 0.0004 / 2 + 0.0003)
        self.assertEqual([e["title"] for e in result["events"]], ["Keine Zeitquelle mehr ausgewählt"])
        good = timeline.moment(self.hist, self.day0 + 20 * 3600)["sample"]
        self.assertEqual(good["source"], "192.0.2.1")
        # Weit weg vom Verlauf: kein Punkt.
        self.assertIsNone(timeline.moment(self.hist, self.day0 - 5 * 86400)["sample"])


class PrivacyTest(TempData):
    def test_moment_has_no_angles_or_position(self):
        hist = self.make()
        t = int(time.time()) - 600
        sample = point(t)
        # Felder, die nie im Verlauf stehen sollten – selbst wenn: sie gehen nicht hinaus.
        sample["gps"].update(lat=48.1372, lon=11.5761, sats=[{"prn": 5, "az": 123, "el": 45}])
        sample["lat"] = 48.1372
        hist.add(sample)
        out = json.dumps(timeline.moment(hist, t))
        for word in ("48.1372", "11.5761", '"az"', '"el"', "hdop", "snr", "lat", "lon", "prn"):
            self.assertNotIn(word, out)
        self.assertIn('"used": 9', out)


class PerformanceTest(TempData):
    """30 Tage synthetischer Verlauf: Band, Marker und Tagesbericht zusammen unter 500 ms."""

    def test_thirty_days(self):
        hist = self.make()
        now = int(time.time())
        step = 20
        start = now - 30 * 86400
        rows = []
        for t in range(start, now, step):
            rows.append((t, history._dumps(point(t, offset=0.0002 if t % 7 else 0.006,
                                                 selected=(t // 3600) % 50 != 0))))
        with store.transaction(hist.db_path) as conn:
            conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)", rows)
        history._backfill_rollup(hist.db_path)
        for i in range(3000):
            self.event(start + i * 860, ("source", "gps", "settings", "startup")[i % 4],
                       ("info", "warn")[i % 2], f"Beispielereignis {i}")
        timeline.reset_cache()
        began = time.perf_counter()
        result = timeline.build(hist, now=now)
        band = time.perf_counter() - began
        began = time.perf_counter()
        marks = timeline.chart_markers(30 * 86400, now=now)
        chart = time.perf_counter() - began
        self.assertEqual(len(result["states"]), timeline.BUCKETS)
        self.assertNotIn("n", result["states"][:-1])
        self.assertGreater(result["report"]["samples"], 4000)
        self.assertGreater(len(marks["markers"]), 1000)
        self.assertLess(band, 0.5, f"Band + Tagesbericht: {band:.3f} s")
        self.assertLess(chart, 0.5, f"Marker 30 Tage: {chart:.3f} s")
        # Zweiter Abruf: Tagesbericht aus dem Zwischenspeicher, Band allein aus 288 Zeilen.
        began = time.perf_counter()
        timeline.build(hist, now=now)
        self.assertLess(time.perf_counter() - began, 0.2)


class MarkerLimitTest(TempData):
    """Nachbesserung: Infos ohne Marker dürfen echte Marker nicht aus dem Zeitraum drängen."""

    def test_info_flood_does_not_hide_markers(self):
        now = int(time.time())
        self.event(now - 80000, "source", "info", "Zeitquelle gewechselt: 192.0.2.1 → 198.51.100.7")
        rows = [events._clean("gps", "info", f"GPS-Fehlerschranke {i} angepasst", None, "web", now - 3600 + i * 0.5)
                for i in range(4100)]
        rows += [events._clean("service", "info", f"Dienst {i} läuft", None, "web", now - 3000 + i) for i in range(50)]
        rows += [events._clean("reload", "info", "Neustart zurückgestellt", {"reason": "holdover"}, "web", now - 2000 + i)
                 for i in range(50)]
        events._write(rows)
        out = timeline.chart_markers(86400, now=now)
        self.assertEqual([m["group"] for m in out["markers"]], ["source"])
        self.assertFalse(out["truncated"])
        band = timeline.build(self.make(), now=now)
        self.assertEqual([m["group"] for m in band["markers"]], ["source"])
        self.assertFalse(band["markers_truncated"])

    def test_truncated_flag(self):
        now = int(time.time())
        for i in range(5):
            self.event(now - 500 + i, "startup", "info", f"ntp-gui gestartet {i}")
        marks, truncated = timeline.marker_page(now - 1000, now, limit=3)
        self.assertTrue(truncated)
        self.assertEqual([m["title"] for m in marks], [f"ntp-gui gestartet {i}" for i in (2, 3, 4)])
        marks, truncated = timeline.marker_page(now - 1000, now, limit=5)
        self.assertFalse(truncated)
        self.assertEqual(len(marks), 5)

    def test_sql_filter_matches_marker_group(self):
        now = int(time.time())
        cases = [("source", "info", "Quelle", None), ("gps", "info", "GPS-Fix verloren (Beispiel)", None),
                 ("gps", "info", "GPS-Fix wieder da", None), ("gps", "warn", "Wenig Satelliten", None),
                 ("pps", "info", "PPS da", None), ("pps", "crit", "PPS weg", None),
                 ("startup", "info", "gestartet", None), ("service", "info", "läuft", None),
                 ("service", "warn", "neu gestartet", None), ("reload", "info", "aktiv", {"result": "done"}),
                 ("reload", "info", "zurückgestellt", {"result": "deferred"}), ("reload", "info", "Liste", [1, 2]),
                 ("pi", "info", "Spannung ok", None), ("pi", "warn", "Unterspannung", None),
                 ("settings", "info", "gespeichert", None), ("dns", "crit", "DNS gestört", None),
                 ("api", "warn", "Schlüssel abgelehnt", None), ("gps", "info", "gps-fix verloren", None)]
        for i, (kind, level, title, data) in enumerate(cases):
            self.event(now - 1000 + i, kind, level, title, data)
        # Kaputtes JSON im Datenfeld (z. B. von Hand eingetragen) darf die Abfrage nicht kippen.
        with store.transaction() as conn:
            conn.execute("INSERT INTO events(t, kind, level, title, data, source) VALUES (?, ?, ?, ?, ?, ?)",
                         (now - 10, "reload", "info", "kaputt", "{kein json", "web"))
        expected = [title for kind, level, title, data in cases if timeline.marker_group(kind, level, title, data)]
        got = [m["title"] for m in timeline.markers(now - 2000, now)]
        self.assertEqual(got, expected)


class ReportSingleFlightTest(TempData):
    """Nachbesserung: Tagesbericht im Hintergrund, nur einmal gleichzeitig, /api/timeline wartet nicht darauf."""

    def slow_hist(self, delay):
        hist = self.make()
        calls = []
        real = hist.report_rows

        def slow(start, end):
            calls.append(start)
            time.sleep(delay)
            return real(start, end)
        hist.report_rows = slow
        return hist, calls

    def test_cache_miss_does_not_block(self):
        hist, calls = self.slow_hist(1.0)
        now = int(time.time())
        for t in range(now - 3600, now, STEP):
            hist.add(point(t))
        began = time.perf_counter()
        result = timeline.build(hist, now=now)
        self.assertLess(time.perf_counter() - began, 0.5)
        self.assertTrue(result["report"]["pending"])
        self.assertEqual(result["report"]["day"], time.strftime("%Y-%m-%d", time.localtime(timeline.day_bounds(now)[0] + 1)))
        self.assertTrue(timeline.wait_report(3.0))
        report = timeline.build(hist, now=now)["report"]
        self.assertNotIn("pending", report)
        self.assertEqual(len(calls), 1)

    def test_single_flight(self):
        hist, calls = self.slow_hist(0.4)
        now = int(time.time())
        import threading
        threads = [threading.Thread(target=timeline.cached_report, args=(hist, now)) for _ in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertTrue(timeline.wait_report(3.0))
        self.assertEqual(len(calls), 1)

    def test_final_report_is_not_recomputed(self):
        hist, calls = self.slow_hist(0.0)
        now = int(time.time())
        timeline.cached_report(hist, now, wait=2.0)
        self.assertEqual(len(calls), 1)
        with mock.patch.object(timeline, "REPORT_TTL", 0.0):
            timeline.cached_report(hist, now + 60, wait=2.0)
            self.assertTrue(timeline.wait_report(3.0))
        # Gestern ist abgeschlossen (über REPORT_SETTLE nach Mitternacht): kein neues Rechnen.
        if now - timeline.day_bounds(now)[1] >= timeline.REPORT_SETTLE:
            self.assertEqual(len(calls), 1)

    def test_invalidate_drops_final_and_running_report(self):
        # Nach einer Wiederherstellung: Der abgeschlossene Bericht wird neu gerechnet, und eine Rechnung, die
        # noch auf dem alten Verlauf lief, trägt ihr Ergebnis nicht mehr ein.
        hist, calls = self.slow_hist(0.0)
        now = timeline.day_bounds(time.time())[1] + timeline.REPORT_SETTLE + 60
        timeline.cached_report(hist, now, wait=2.0)
        timeline.invalidate_report()
        timeline.cached_report(hist, now, wait=2.0)
        self.assertEqual(len(calls), 2)
        release = __import__("threading").Event()
        real = hist.report_rows

        def blocked(start, end):
            release.wait(3.0)
            return real(start, end)
        hist.report_rows = blocked
        timeline.invalidate_report()
        job = timeline._report_job(hist, now)
        timeline.invalidate_report()
        release.set()
        self.assertTrue(job.wait(3.0))
        self.assertIsNone(timeline._REPORT["key"])

    def test_warm_report_in_background(self):
        hist, calls = self.slow_hist(0.3)
        began = time.perf_counter()
        timeline.warm_report(hist)
        self.assertLess(time.perf_counter() - began, 0.1)
        self.assertTrue(timeline.wait_report(3.0))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("pending", timeline.cached_report(hist, wait=0))

    def test_collector_warms_report(self):
        server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn("timeline.warm_report(HISTORY)", server)

    def test_two_second_interval(self):
        """Kleinster Verlaufstakt (2 s) mit zwei Tagen Rohverlauf: Abruf nach dem Vorwärmen unter 500 ms,
        auch der erste Abruf (Tagesbericht noch nicht da) wartet nicht auf die Rechnung."""
        hist = self.make()
        now = int(time.time())
        rows = [(t, history._dumps(point(t))) for t in range(now - 2 * 86400, now, 2)]
        with store.transaction(hist.db_path) as conn:
            conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)", rows)
        history._backfill_rollup(hist.db_path)
        timeline.reset_cache()
        with mock.patch.object(timeline, "REPORT_WAIT", 0.0):
            began = time.perf_counter()
            first = timeline.build(hist, now=now)
            self.assertLess(time.perf_counter() - began, 0.5)
        self.assertTrue(first["report"].get("pending"))
        self.assertTrue(timeline.wait_report(10.0))
        began = time.perf_counter()
        result = timeline.build(hist, now=now)
        self.assertLess(time.perf_counter() - began, 0.2)
        self.assertGreater(result["report"]["samples"], 40000)


class ApiTest(unittest.TestCase):
    def test_endpoints_read_scope_and_v1_alias(self):
        for path in ("/timeline", "/timeline/markers", "/timeline/at"):
            self.assertEqual(apiv1.resolve("/api/v1" + path), "/api" + path)
            self.assertEqual(apiv1.required_scope("GET", "/api/v1" + path), "read")
            self.assertEqual(apiv1.required_scope("GET", "/api" + path), "read")
        server = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        for path in ("/api/timeline", "/api/timeline/markers", "/api/timeline/at"):
            self.assertIn(f'path == "{path}"', server)

    def test_marker_range_is_capped(self):
        out = timeline.chart_markers(10 ** 12, now=1_000_000_000)
        self.assertEqual(out["until"] - out["since"], timeline.MARKER_RANGE_MAX)
        self.assertEqual(timeline.chart_markers("nan", now=1)["until"] - timeline.chart_markers("nan", now=1)["since"],
                         86400)


class MemoryFallbackTest(unittest.TestCase):
    def test_without_sqlite(self):
        hist = history.History(8640, None)
        now = int(time.time())
        for t in range(now - 3600, now, STEP):
            hist.add(point(t, selected=t < now - 1800))
        result = timeline.build(hist, now=now - STEP)  # Zeit des letzten Messpunkts
        self.assertEqual(result["states"][-1], "h")
        self.assertEqual(timeline.moment(hist, now - 60)["sample"]["state"], "holdover")
        start, end = timeline.day_bounds(now + 86400)
        self.assertIsNotNone(timeline.daily_report(hist, start, end))


if __name__ == "__main__":
    unittest.main()
