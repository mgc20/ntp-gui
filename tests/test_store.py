"""Tests für store.py (SQLite-Grundlage) und den SQLite-Verlauf in history.py."""

import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import history  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402


class TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        self.env = dict(os.environ)
        for key in ("HISTORY_SIZE", "HISTORY_DAYS"):
            os.environ.pop(key, None)

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp, ignore_errors=True)


class StoreTest(TempDataDir):
    def test_path_follows_data_dir(self):
        self.assertEqual(store.path(), os.path.join(settings.DATA_DIR, "ntp-gui.db"))

    def test_connect_wal_and_permissions(self):
        conn = store.connect()
        self.assertIs(conn, store.connect())
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(os.stat(store.path()).st_mode & 0o777, 0o600)

    def test_migrate_applies_each_step_once(self):
        steps = ["CREATE TABLE a (x INTEGER); INSERT INTO a VALUES (1);"]
        self.assertEqual(store.migrate("t", steps), 1)
        self.assertEqual(store.migrate("t", steps), 0)
        steps.append("ALTER TABLE a ADD COLUMN y TEXT DEFAULT ';'")
        self.assertEqual(store.migrate("t", steps), 1)
        self.assertEqual(store.schema_version("t"), 2)
        self.assertEqual(store.query("SELECT x, y FROM a"), [(1, ";")])

    def test_failed_migration_rolls_back(self):
        with self.assertRaises(Exception):
            store.migrate("bad", ["CREATE TABLE b (x INTEGER); SELECT * FROM nope;"])
        self.assertEqual(store.schema_version("bad"), 0)
        self.assertEqual(store.query("SELECT name FROM sqlite_master WHERE name='b'"), [])

    def test_transaction_rollback(self):
        store.migrate("t", ["CREATE TABLE a (x INTEGER)"])
        with self.assertRaises(RuntimeError):
            with store.transaction() as conn:
                conn.execute("INSERT INTO a VALUES (1)")
                raise RuntimeError("abbrechen")
        self.assertEqual(store.query("SELECT count(*) FROM a"), [(0,)])

    def test_threads(self):
        store.migrate("t", ["CREATE TABLE a (x INTEGER)"])

        def work():
            for i in range(50):
                with store.transaction() as conn:
                    conn.execute("INSERT INTO a VALUES (?)", (i,))
                store.query("SELECT count(*) FROM a")

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(store.query("SELECT count(*) FROM a"), [(400,)])


def sample(t, offset=1e-6, sources=True):
    s = {"t": t, "offset": offset, "rms": 1e-6, "freq": -2.0, "served": t * 2, "clients": 3}
    if sources:
        s["sources"] = {"GPS": {"o": offset * 2, "s": "*", "k": "#"},
                        "pool": {"o": offset, "s": "+", "k": "^"}}
        s["gps"] = {"used": 7, "hdop": 1.0}
    return s


class HistorySqliteTest(TempDataDir):
    def make(self, size=8640, **kw):
        return history.History(size, os.path.join(settings.DATA_DIR, "history.json.gz"), **kw)

    def test_backend_and_shared_db(self):
        h = self.make()
        self.assertEqual(h.backend, "sqlite")
        self.assertEqual(h.db_path, store.path())
        self.assertIsNone(h.size)  # 8640 ohne HISTORY_SIZE = keine Obergrenze

    def test_explicit_history_size_is_cap(self):
        os.environ["HISTORY_SIZE"] = "8640"
        self.assertEqual(self.make().size, 8640)
        h = self.make(size=50)
        for i in range(80):
            h.add(sample(1000 + i * 10))
        self.assertEqual(len(h.snapshot()), 50)
        h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], 50)
        self.assertEqual(len(h.snapshot()), 50)

    def test_pending_visible_and_flushed(self):
        h = self.make()
        for i in range(10):
            h.add(sample(1000 + i * 10))
        self.assertEqual(len(h.snapshot()), 10)
        self.assertFalse(h.save())  # noch nicht fällig
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], 0)
        self.assertTrue(h.save(force=True))
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], 10)
        again = self.make()
        self.assertEqual(again.load(), 10)
        self.assertEqual([s["t"] for s in again.snapshot(1050)], [1050, 1060, 1070, 1080, 1090])

    def test_retention_days_relative_to_newest(self):
        h = self.make(days=1)
        h.add(sample(1_000_000))
        h.add(sample(1_000_000 + 2 * 86400))
        h.save(force=True)
        self.assertEqual([s["t"] for s in h.snapshot()], [1_000_000 + 2 * 86400])

    def test_query_downsamples_like_python(self):
        h = self.make()
        for i in range(2000):
            h.add(sample(100_000 + i * 10, offset=(i % 2) * 2e-6))
        h.save(force=True)
        h.add(sample(100_000 + 2000 * 10))  # im Puffer
        out = h.query(None, 100)
        self.assertLessEqual(len(out), 100)
        self.assertGreater(len(out), 50)
        self.assertEqual(out[-1]["t"], 100_000 + 2000 * 10)
        self.assertAlmostEqual(out[0]["offset"], 1e-6, delta=2e-7)
        self.assertEqual(out[0]["sources"]["GPS"]["s"], "*")
        self.assertAlmostEqual(out[0]["sources"]["GPS"]["o"], 2e-6, delta=4e-7)
        self.assertEqual(out[0]["gps"]["used"], 7)
        # Zählerstand ist der letzte Wert im Fenster, nicht das Mittel.
        self.assertEqual(out[-1]["served"], (100_000 + 2000 * 10) * 2)
        # Kurzer Zeitraum: unverdichtet.
        self.assertEqual(len(h.query(100, 600)), 11)

    def test_query_uses_rollup_for_long_ranges(self):
        h = self.make()
        rows = [(100_000 + i * 10, json.dumps(sample(100_000 + i * 10))) for i in range(40_000)]
        with store.transaction() as conn:
            conn.executemany("INSERT INTO samples(t, json) VALUES(?, ?)", rows)
        self.assertGreater(history._backfill_rollup(store.path()), 1000)
        out = h.query(None, 600)
        self.assertLessEqual(len(out), 600)
        self.assertGreater(len(out), 300)
        self.assertEqual(out[0]["sources"]["pool"]["k"], "^")

    def test_nan_does_not_break_storage(self):
        h = self.make()
        h.add({"t": 5000, "offset": float("nan"), "sources": {"x": {"o": float("inf")}}})
        h.add(sample(5010))
        self.assertTrue(h.save(force=True))
        self.assertEqual(len(h.query(None, 10)), 2)

    def test_migrates_gzip_once(self):
        path = os.path.join(settings.DATA_DIR, "history.json.gz")
        os.makedirs(settings.DATA_DIR)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump([sample(3000 + i * 10) for i in range(30)] + ["kaputt"], handle)
        h = self.make()
        self.assertEqual(h.load(), 30)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(path + ".migrated"))
        self.assertEqual(store.query("SELECT count(*) FROM samples_5m")[0][0], 1)
        self.assertEqual(self.make().load(), 30)

    def test_fallback_to_memory_and_gzip(self):
        blocker = os.path.join(self.tmp, "file")
        Path(blocker).write_text("x")
        h = history.History(100, os.path.join(blocker, "history.json.gz"))
        self.assertEqual(h.backend, "memory")
        h.add(sample(10))
        self.assertEqual(len(h.query(None, 10)), 1)
        self.assertFalse(h.save(force=True))  # Ordner nicht anlegbar, aber kein Absturz

    def test_no_path_is_memory_only(self):
        h = history.History(5, None)
        for i in range(8):
            h.add(sample(i))
        self.assertEqual(h.backend, "memory")
        self.assertEqual(len(h.snapshot()), 5)

    def test_threads(self):
        h = self.make()

        def work(base):
            for i in range(100):
                h.add(sample(base + i))
                if i % 25 == 0:
                    h.save(force=True)
                h.query(None, 50)

        threads = [threading.Thread(target=work, args=(k * 1000,)) for k in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        h.save(force=True)
        self.assertEqual(store.query("SELECT count(*) FROM samples")[0][0], 400)


if __name__ == "__main__":
    unittest.main()
