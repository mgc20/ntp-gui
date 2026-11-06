"""1.5.4: Allan-Abweichung der Systemuhr (app/allan.py, Seite „Uhrqualität“, /api/clockquality/allan).

Die Mathematik wird gegen eine Lehrbuch-Umsetzung hier im Test geprüft (überlappende ADEV aus Phasendaten,
σ²(τ) = Σ (x[i+2m] − 2x[i+m] + x[i])² / (2 τ² (N − 2m))), dazu die bekannten Steigungen im log-log-Bild:
weißes Frequenzrauschen −1/2, weißes Phasenrauschen −1.
"""

import base64
import http.client
import json
import math
import os
import random
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, fake_hostnames, stop_http_server  # noqa: E402

import allan  # noqa: E402
import diagnostics  # noqa: E402
import history  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402


def reference_adev(y, tau0, m):
    """Lehrbuch: überlappende ADEV aus Phasendaten x (Integral der Frequenz)."""
    x = [0.0]
    for v in y:
        x.append(x[-1] + v * tau0)
    n = len(x)
    tau = m * tau0
    terms = [(x[i + 2 * m] - 2 * x[i + m] + x[i]) ** 2 for i in range(n - 2 * m)]
    return math.sqrt(sum(terms) / (2 * tau * tau * (n - 2 * m)))


def slope(points, lo, hi):
    """Steigung der Ausgleichsgeraden in log-log zwischen τ-Grenzen."""
    xs = [math.log10(p["tau"]) for p in points if lo <= p["tau"] <= hi]
    ys = [math.log10(p["adev"]) for p in points if lo <= p["tau"] <= hi]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sum((a - mx) ** 2 for a in xs)


class MathTest(unittest.TestCase):
    def test_matches_reference_without_gaps(self):
        rnd = random.Random(7)
        y = [rnd.gauss(0, 1e-8) for _ in range(3000)]
        points = allan.adev(y, 10.0)
        self.assertGreater(len(points), 8)
        for p in points:
            ref = reference_adev(y, 10.0, p["m"])
            self.assertAlmostEqual(p["adev"] / ref, 1.0, places=9, msg=f"m={p['m']}")
            self.assertEqual(p["pairs"], len(y) - 2 * p["m"] + 1)
        self.assertLessEqual(points[-1]["m"], len(y) // 4, "τ höchstens ein Viertel der Messdauer")

    def test_white_fm_slope_minus_half(self):
        rnd = random.Random(1)
        y = [rnd.gauss(0, 1e-8) for _ in range(20000)]
        points = allan.adev(y, 1.0)
        self.assertAlmostEqual(slope(points, 1, 1000), -0.5, delta=0.06)
        # σ(τ0) einer weißen Folge = ihre Standardabweichung
        self.assertAlmostEqual(points[0]["adev"] / 1e-8, 1.0, delta=0.03)

    def test_white_pm_slope_minus_one(self):
        rnd = random.Random(2)
        x = [rnd.gauss(0, 1e-9) for _ in range(20001)]
        y = [(b - a) / 1.0 for a, b in zip(x, x[1:])]
        points = allan.adev(y, 1.0)
        self.assertAlmostEqual(slope(points, 1, 1000), -1.0, delta=0.08)
        for p in points[:6]:
            self.assertAlmostEqual(p["adev"] / reference_adev(y, 1.0, p["m"]), 1.0, places=9)

    def test_log_spacing_and_confidence(self):
        rnd = random.Random(3)
        y = [rnd.gauss(0, 1e-8) for _ in range(10000)]
        points = allan.adev(y, 1.0)
        ms = [p["m"] for p in points]
        self.assertEqual(ms[:6], [1, 2, 3, 4, 6, 10])  # 5 je Dekade, gerundet, ohne Doppelte
        for p in points:
            self.assertLess(p["lo"], p["adev"])
            self.assertGreater(p["hi"], p["adev"])
        ns = [p["n"] for p in points]
        self.assertEqual(ns, sorted(ns, reverse=True), "weniger unabhängige Paare bei größerem τ")
        self.assertAlmostEqual(points[-1]["n"], 10000 / points[-1]["m"] - 1, delta=2)
        # Größeres τ, weniger Paare: relativ breiterer Bereich
        width = [(p["hi"] - p["lo"]) / p["adev"] for p in points]
        self.assertGreater(width[-1], width[0] * 5)

    def test_gaps_are_skipped_not_bridged(self):
        rnd = random.Random(4)
        y = [rnd.gauss(0, 1e-8) for _ in range(4000)]
        gapped = list(y)
        for i in range(1000, 1500):
            gapped[i] = None
        # Ein Sprung genau in der Lücke darf nicht zählen.
        for i in range(1500, 4000):
            gapped[i] = gapped[i] + 5e-7
        points = allan.adev(gapped, 1.0)
        self.assertTrue(points)
        # Kleine τ: Fenster beiderseits der Lücke sind leer → kein Paar überbrückt den Sprung.
        self.assertLess(points[0]["adev"], 1.5e-8)
        self.assertLess(points[0]["pairs"], 4000 - 2)

    def test_stride_cap_keeps_estimate(self):
        rnd = random.Random(5)
        y = [rnd.gauss(0, 1e-8) for _ in range(30000)]
        full = {p["m"]: p["adev"] for p in allan.adev(y, 1.0, max_pairs=10 ** 9)}
        capped = allan.adev(y, 1.0, max_pairs=2000)
        for p in capped:
            self.assertLessEqual(p["pairs"], 2000)
            self.assertAlmostEqual(p["adev"] / full[p["m"]], 1.0, delta=0.2)

    def test_grid_interval_and_cap(self):
        times = [1000.0 + 11 * i for i in range(1000)]
        tau0, y = allan.grid(times, [1.0] * 1000)
        self.assertEqual(tau0, 11.0)
        self.assertEqual(len(y), 1000)
        tau0, y = allan.grid(times, [1.0] * 1000, max_bins=100)
        self.assertGreater(tau0, 11.0)
        self.assertLessEqual(len(y), 100)
        self.assertTrue(all(v == 1.0 for v in y))


class ComputeTest(unittest.TestCase):
    def series(self, hours, interval=10.0, noise=0.002, seed=9):
        rnd = random.Random(seed)
        t0 = 1_793_000_000
        return [(t0 + i * interval, round(1.67 + rnd.gauss(0, noise), 3))
                for i in range(int(hours * 3600 / interval))]

    def test_too_short(self):
        self.assertEqual(allan.compute([])["reason"], "no_history")
        out = allan.compute(self.series(1.5))
        self.assertFalse(out["available"])
        self.assertEqual(out["reason"], "few")

    def test_result_shape_and_units(self):
        out = allan.compute(self.series(30))
        self.assertTrue(out["available"])
        self.assertEqual(out["source"], "freq")
        self.assertEqual(out["tau0"], 10.0)
        self.assertAlmostEqual(out["coverage"], 1.0)
        first = out["points"][0]
        # 0,002 ppm weißes Rauschen = 2e-9 als Bruchteil (Rundung auf 0,001 ppm kommt dazu)
        self.assertAlmostEqual(first["adev"] / 2e-9, 1.0, delta=0.1)
        self.assertTrue(first["short"])
        self.assertFalse(out["points"][-1]["short"])
        self.assertLessEqual(out["points"][-1]["tau"], out["span"] / 4)
        summary = out["summary"]
        self.assertEqual(summary["level"], "very_quiet")
        self.assertIsNotNone(summary["hour"])
        self.assertIsNone(summary["day"], "30 h Verlauf reichen nicht für τ ≈ 1 Tag")

    def test_levels(self):
        def at_hour(value):
            return allan.interpret([{"tau": 3600.0, "adev": value, "short": False}])
        self.assertEqual(at_hour(5e-10)["level"], "very_quiet")
        self.assertEqual(at_hour(4e-9)["level"], "quiet")
        self.assertIn("Pi-Quarz", at_hour(4e-9)["text"])
        self.assertEqual(at_hour(3e-8)["level"], "typical")
        self.assertEqual(at_hour(3e-7)["level"], "restless")

    def test_rising_after_minimum(self):
        pts = [{"tau": t, "adev": a, "short": t < 900} for t, a in
               [(10, 5e-9), (1000, 1e-9), (3600, 8e-10), (20000, 4e-9)]]
        self.assertEqual(allan.interpret(pts)["rising_after"], 3600)

    def test_compact_numbers_only(self):
        out = allan.compact(allan.compute(self.series(30)))
        self.assertTrue(out["available"])
        for row in out["points"]:
            self.assertEqual(len(row), 3)
            self.assertTrue(all(isinstance(v, (int, float)) for v in row))
        self.assertNotIn("text", out)
        self.assertEqual(allan.compact(allan.compute([]))["reason"], "no_history")

    def test_cache(self):
        calls = []

        def loader():
            calls.append(1)
            return self.series(3)
        cache = allan.Cache(loader, seconds=600)
        first = cache.get()
        second = cache.get()
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(len(calls), 1)
        cache.get(fresh=True)
        self.assertEqual(len(calls), 2)
        broken = allan.Cache(lambda: 1 / 0)
        self.assertEqual(broken.get()["reason"], "error")


class HistorySeriesTest(unittest.TestCase):
    def test_sqlite_and_memory_agree(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.close_all)
        hist = history.History(None, os.path.join(tmp.name, "history.json.gz"), days=30,
                               db_path=os.path.join(tmp.name, store.DB_NAME))
        mem = history.History(None, None, days=30)
        self.assertEqual(hist.backend, "sqlite")
        now = 1_793_000_000
        with mock.patch.object(history.time, "time", return_value=now + 10):
            for i in range(300):
                sample = {"t": now - 3000 + i * 10, "offset": 0.0}
                if i % 7:
                    sample["freq"] = 1.6 + i / 1000
                hist.add(dict(sample))
                mem.add(dict(sample))
            hist.save(force=True)
            hist.add({"t": now + 5, "freq": 9.0})   # noch im Puffer
            mem.add({"t": now + 5, "freq": 9.0})
            a = hist.series("freq")
            b = mem.series("freq")
        self.assertEqual(a, b)
        self.assertEqual(a[-1], (now + 5, 9.0))
        self.assertEqual(len(a), 300 - len(range(0, 300, 7)) + 1)


class AllanHttpTest(unittest.TestCase):
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

    def setUp(self):
        fake_hostnames(self)

    def request(self, path, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": "example.com"}
        if auth:
            headers["Authorization"] = "Basic " + base64.b64encode(b"admin:geheim123").decode()
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_endpoint(self):
        series = ComputeTest().series(10)
        cache = allan.Cache(lambda: series)
        with mock.patch.object(server, "ALLAN", cache):
            self.assertEqual(self.request("/api/v1/clockquality/allan", auth=False)[0], 401)
            status, body = self.request("/api/v1/clockquality/allan")
            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertTrue(payload["available"])
            self.assertTrue(payload["points"])
            status, body = self.request("/api/clockquality/allan")
            self.assertTrue(json.loads(body)["cached"])
        described = [e for e in server.apiv1.ENDPOINTS if e["path"] == "/clockquality/allan"]
        self.assertEqual(described[0]["scope"], "read")

    def test_loader_reads_history_freq(self):
        hist = mock.Mock()
        hist.series.return_value = []
        with mock.patch.object(server, "HISTORY", hist):
            out = allan.Cache(server.ALLAN.loader).get()
        hist.series.assert_called_with("freq")
        self.assertEqual(out["reason"], "no_history")


class DiagnosticsTest(unittest.TestCase):
    def test_history_section_has_allan_numbers(self):
        compact = allan.compact(allan.compute(ComputeTest().series(30)))
        out = diagnostics._collect_history({}, {"history": [], "allan": compact})
        self.assertEqual(out["allan"]["points"], compact["points"])
        out = diagnostics._collect_history({}, {"history": []})
        self.assertNotIn("allan", out)

    def test_bundle_passes_privacy_filter(self):
        compact = allan.compact(allan.compute(ComputeTest().series(30)))
        content = diagnostics.build({}, ["history"], {"history": [], "allan": compact})
        text = json.dumps(content, ensure_ascii=False)
        self.assertIn("allan", text)
        self.assertNotIn("Pi-Quarz", text, "nur Zahlen, keine Sätze")


class PageTest(unittest.TestCase):
    def test_page_and_help_wired(self):
        page = (ROOT / "app/static/js/pages/clockquality.js").read_text(encoding="utf-8")
        self.assertIn("/api/clockquality/allan", page)
        self.assertIn("logLogChart", page)
        charts = (ROOT / "app/static/js/charts.js").read_text(encoding="utf-8")
        self.assertIn("export function logLogChart", charts)
        helps = (ROOT / "app/static/js/help-uhr.js").read_text(encoding="utf-8")
        for key in ("adev", "adev_best", "adev_hour", "adev_day", "adev_basis"):
            self.assertIn(f"  {key}: {{", helps)


if __name__ == "__main__":
    unittest.main()
