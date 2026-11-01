"""history.py: Zeitstempel in der Zukunft, Dekodieren außerhalb der Sperre, ungemessene GPS-Werte."""

import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import history  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

DAY = 86400


def sample(t, gps=None, offset=1e-6):
    gps = gps if gps is not None else {"o": 0.012, "s": "-", "k": "#"}
    return {"t": t, "offset": offset, "served": 1,
            "sources": {"GPS": gps,
                        "a": {"o": 0.001, "s": "*", "k": "^"},
                        "b": {"o": 0.002, "s": "+", "k": "^"}}}


class TempDataDir(unittest.TestCase):
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

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, size=8640, **kw):
        return history.History(size, os.path.join(settings.DATA_DIR, "history.json.gz"), **kw)

    def count(self):
        return store.query("SELECT count(*) FROM samples")[0][0]


class FutureSampleTest(TempDataDir):
    """Review 1/2: ein Messpunkt in der Zukunft darf den Verlauf nicht leeren."""

    def test_future_sample_is_dropped(self):
        h = self.make(days=30)
        now = int(time.time())
        for i in range(100):
            h.add(sample(now - 1000 + i * 10))
        h.save(force=True)
        h.add(sample(now + 40 * DAY))
        h.save(force=True)
        self.assertEqual(self.count(), 100)
        for i in range(50):
            h.add(sample(now + i))
        h.save(force=True)
        self.assertEqual(self.count(), 150)
        self.assertEqual(len(h.query(None, 1000)), 150)
        self.assertEqual(len(h.snapshot()), 150)

    def test_existing_future_row_does_not_wipe(self):
        """Ein schon gespeicherter Zukunftspunkt (vor dem Fix) zählt nicht als „neuester“."""
        h = self.make(days=30)
        now = int(time.time())
        with store.transaction(h.db_path) as conn:
            conn.execute("INSERT INTO samples(t, json) VALUES(?, ?)",
                         (now + 40 * DAY, json.dumps(sample(now + 40 * DAY))))
        for i in range(100):
            h.add(sample(now - 1000 + i * 10))
        h.save(force=True)
        self.assertEqual(self.count(), 101)
        points = h.query(None, 1000)
        self.assertEqual(len(points), 100)
        self.assertEqual(points[-1]["t"], now - 10)
        self.assertEqual(len(h.snapshot()), 100)

    def test_clock_in_the_past_keeps_history(self):
        """Pi ohne RTC startet mit altem Datum: der echte Verlauf bleibt erhalten."""
        h = self.make(days=30)
        real = 1_800_000_000
        with mock.patch("time.time", return_value=real + 400):
            for i in range(20):
                h.add(sample(real + i * 10))
            h.save(force=True)
        with mock.patch("time.time", return_value=1_000_000_000):
            h.add(sample(1_000_000_000))
            h.save(force=True)
        self.assertEqual(self.count(), 21)

    def test_migration_skips_future(self):
        now = int(time.time())
        data = [sample(now - 100 + i) for i in range(10)] + [sample(now + 40 * DAY)]
        path = os.path.join(settings.DATA_DIR, "history.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(data, handle)
        h = self.make(days=30)
        with mock.patch("builtins.print"):
            self.assertEqual(h.load(), 10)
        self.assertTrue(os.path.exists(path + ".migrated"))

    def test_memory_fallback_ignores_future(self):
        h = history.History(100, None)
        self.assertEqual(h.backend, "memory")
        now = int(time.time())
        for i in range(5):
            h.add(sample(now - 50 + i))
        h.add(sample(now + 40 * DAY))
        self.assertEqual(len(h.snapshot()), 5)


class DecodeOutsideLockTest(TempDataDir):
    """Review 1/6: json.loads der Punkte läuft ohne self._lock, add() muss nicht warten."""

    def test_decode_without_lock(self):
        h = self.make()
        now = int(time.time())
        for i in range(20):
            h.add(sample(now - 200 + i))
        h.save(force=True)
        held = []
        real = history.History._decode

        def spy(texts):
            result = []

            def probe():
                got = h._lock.acquire(timeout=1)
                result.append(got)
                if got:
                    h._lock.release()
            t = threading.Thread(target=probe)
            t.start()
            t.join()
            held.append(not result[0])
            return real(texts)

        with mock.patch.object(history.History, "_decode", staticmethod(spy)):
            self.assertEqual(len(h.snapshot()), 20)
            self.assertEqual(len(h.query(None, 1000)), 20)
        self.assertEqual(held, [False, False])


class GpsMeasuredTest(unittest.TestCase):
    """Review 2/2: ein GPS ohne Daten („?“, Reach 0) ist keine Messung."""

    def test_gps_measured(self):
        self.assertTrue(history.gps_measured({"o": 0.01, "s": "-"}))
        self.assertTrue(history.gps_measured({"o": 0.01, "s": "*", "r": 255}))
        for bad in ({"o": 0.0, "s": "?"}, {"o": 0.01, "s": "x"}, {"o": 0.01, "s": "~"},
                    {"o": 0.0, "s": "-", "r": 0}, {"o": 0.0, "s": "-", "reach": 0},
                    {"o": None, "s": "*"}, {"o": True, "s": "*"}, {"o": float("nan"), "s": "*"},
                    None, "GPS"):
            self.assertFalse(history.gps_measured(bad), bad)

    def test_calibrate_ignores_dead_gps(self):
        t0 = 1_800_000_000
        dead = [sample(t0 + i * 10, {"o": 0.0, "s": "?", "k": "#"}) for i in range(400)]
        result = history.calibrate(dead, "GPS", 0.2, 0.2)
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["samples"], 0)
        reach0 = [sample(t0 + i * 10, {"o": 0.0, "s": "-", "k": "#", "r": 0}) for i in range(400)]
        self.assertEqual(history.calibrate(reach0, "GPS", 0.2, 0.2)["samples"], 0)

    def test_calibrate_mixed(self):
        t0 = 1_800_000_000
        good = [sample(t0 + i * 10) for i in range(300)]
        dead = [sample(t0 + 3000 + i * 10, {"o": 0.0, "s": "?", "k": "#"}) for i in range(300)]
        result = history.calibrate(good + dead, "GPS", 0.0, 0.2)
        self.assertEqual(result["samples"], 300)
        self.assertAlmostEqual(result["bias"], 0.012 - 0.0015)


if __name__ == "__main__":
    unittest.main()
