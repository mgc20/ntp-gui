"""Tests für das Ereignisprotokoll (events.py)."""

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import events  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402


class EventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = settings.DATA_DIR
        settings.DATA_DIR = os.path.join(self.tmp, "data")
        events._PENDING.clear()

    def tearDown(self):
        store.close_all()
        settings.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_emit_and_query(self):
        events.emit("source", "info", "Quelle gewechselt: GPS", {"from": "pool", "to": "GPS"})
        events.emit("gps", "warn", "GPS-Fix verloren")
        events.emit("service", "crit", "chronyd ausgefallen", source="supervisor")
        rows = events.query()
        self.assertEqual([r["kind"] for r in rows], ["service", "gps", "source"])
        self.assertEqual(rows[2]["data"], {"from": "pool", "to": "GPS"})
        self.assertEqual(set(rows[0]), {"id", "t", "kind", "level", "title", "data", "source"})
        self.assertEqual([r["kind"] for r in events.query(level="warn")], ["service", "gps"])
        self.assertEqual([r["kind"] for r in events.query(kinds=["gps", "source"])], ["gps", "source"])
        self.assertEqual([r["kind"] for r in events.query(kinds="gps")], ["gps"])
        self.assertEqual(len(events.query(limit=1)), 1)

    def test_time_filter(self):
        with mock.patch("time.time", return_value=1000.0):
            events.emit("startup", "info", "alt")
        events.emit("startup", "info", "neu")
        self.assertEqual([r["title"] for r in events.query(since=2000)], ["neu"])
        self.assertEqual([r["title"] for r in events.query(until=2000)], ["alt"])

    def test_emit_never_raises(self):
        events.emit("x", "bogus", "\n".join(["zeile"] * 3), {"obj": object()})
        row = events.query()[0]
        self.assertEqual(row["level"], "info")
        self.assertEqual(row["title"], "zeile zeile zeile")
        with mock.patch.object(store, "transaction", side_effect=OSError("voll")):
            events.emit("gps", "warn", "gepuffert")  # kein Fehler
        self.assertEqual(len(events._PENDING), 1)
        events.emit("gps", "info", "danach")
        self.assertEqual([r["title"] for r in events.query(limit=2)], ["danach", "gepuffert"])

    def test_data_size_limited(self):
        events.emit("other", "info", "groß", {"x": "a" * 20000})
        self.assertEqual(events.query()[0]["data"], {"truncated": True})

    def test_prune(self):
        with mock.patch.object(events, "MAX_ROWS", 5):
            for i in range(8):
                events.emit("other", "info", f"e{i}")
            events.prune()
            self.assertEqual(events.count(), 5)
        with mock.patch("time.time", return_value=time.time() - 91 * 86400):
            events.emit("other", "info", "uralt")
        events.prune()
        self.assertNotIn("uralt", [r["title"] for r in events.query()])

    def test_threads(self):
        def work():
            for i in range(30):
                events.emit("other", "info", f"t{i}")

        threads = [threading.Thread(target=work) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(events.count(), 150)

    def test_ingest_supervisor(self):
        path = os.path.join(self.tmp, "events.jsonl")
        now = int(time.time())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": now - 5, "kind": "service", "level": "warn",
                                     "title": "gpsd neu gestartet", "data": {"service": "gpsd"}}) + "\n")
            handle.write("kein json\n")
            handle.write('{"t": %d, "kind": "reload", "level": "info", "title": "teil' % (now - 4))  # unvollständig
        self.assertEqual(events.ingest_supervisor(path), 1)
        self.assertEqual(events.ingest_supervisor(path), 0)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('weise"}\n')
        self.assertEqual(events.ingest_supervisor(path), 1)
        rows = events.query()
        self.assertEqual([r["source"] for r in rows], ["supervisor", "supervisor"])
        self.assertEqual(rows[1]["data"], {"service": "gpsd"})
        self.assertEqual(rows[1]["t"], now - 5)
        # Datei neu angelegt (z. B. Container-Neustart, RUN_DIR ist tmpfs): von vorn lesen.
        os.unlink(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": now, "kind": "startup", "level": "info", "title": "Start"}) + "\n")
        self.assertEqual(events.ingest_supervisor(path), 1)
        self.assertEqual(events.ingest_supervisor(os.path.join(self.tmp, "fehlt")), 0)


    @staticmethod
    def _line(t, title):
        return json.dumps({"t": t, "kind": "service", "level": "info", "title": title}) + "\n"

    def test_ingest_reads_rest_after_rotation(self):
        """Review 1/5: Zeilen, die vor der Rotation noch in die alte Datei kamen, gehen nicht verloren."""
        path = os.path.join(self.tmp, "events.jsonl")
        now = int(time.time())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 9, "eins"))
        self.assertEqual(events.ingest_supervisor(path), 1)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(self._line(now - 8, "zwei"))
            handle.write(self._line(now - 7, "drei"))
        os.replace(path, path + ".1")     # wie emit_event im Supervisor ab 1 MB
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 6, "vier"))
        self.assertEqual(events.ingest_supervisor(path), 3)
        self.assertEqual(events.ingest_supervisor(path), 0)
        self.assertEqual(sorted(r["title"] for r in events.query()), ["drei", "eins", "vier", "zwei"])

    def test_ingest_rotation_without_new_file_yet(self):
        path = os.path.join(self.tmp, "events.jsonl")
        now = int(time.time())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 9, "eins"))
        events.ingest_supervisor(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(self._line(now - 8, "zwei"))
        os.replace(path, path + ".1")
        self.assertEqual(events.ingest_supervisor(path), 0)   # neue Datei fehlt noch
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 5, "drei"))
        self.assertEqual(events.ingest_supervisor(path), 2)
        self.assertEqual(sorted(r["title"] for r in events.query()), ["drei", "eins", "zwei"])

    def test_ingest_detects_inode_reuse(self):
        """Gleicher Inode, gleiche Größe, anderer Inhalt (tmpfs nach Container-Neustart): neu lesen."""
        path = os.path.join(self.tmp, "events.jsonl")
        now = int(time.time())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 100, "Start A"))
        self.assertEqual(events.ingest_supervisor(path), 1)
        # Inhalt gleicher Länge an gleicher Stelle (Inode bleibt): simuliert die Wiederverwendung.
        with open(path, "r+", encoding="utf-8") as handle:
            handle.write(self._line(now - 1, "Start B"))
        self.assertEqual(events.ingest_supervisor(path), 1)
        self.assertEqual(sorted(r["title"] for r in events.query()), ["Start A", "Start B"])
        self.assertEqual(events.ingest_supervisor(path), 0)

    def test_ingest_fingerprint_survives_growth(self):
        path = os.path.join(self.tmp, "events.jsonl")
        now = int(time.time())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 50, "a"))
        events.ingest_supervisor(path)
        for i in range(10):   # wächst über 256 Bytes hinaus
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(self._line(now - 40 + i, f"n{i}"))
            self.assertEqual(events.ingest_supervisor(path), 1)
        self.assertEqual(events.count(), 11)

    def test_ingest_legacy_state_without_fingerprint(self):
        path = os.path.join(self.tmp, "events.jsonl")
        now = int(time.time())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._line(now - 50, "alt"))
        events._ensure()
        with store.transaction() as conn:
            conn.execute("INSERT INTO events_meta(key, value) VALUES(?, ?)",
                         ("ingest:" + os.path.abspath(path),
                          json.dumps({"inode": os.stat(path).st_ino, "offset": os.stat(path).st_size})))
        self.assertEqual(events.ingest_supervisor(path), 0)   # schon gelesen – nicht doppelt


if __name__ == "__main__":
    unittest.main()
