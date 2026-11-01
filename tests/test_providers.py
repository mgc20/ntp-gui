"""Aufzeichnung und Wiedergabe der Datenquellen (app/providers.py)."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

import chrony  # noqa: E402
import gps  # noqa: E402
import providers  # noqa: E402
import ptp  # noqa: E402

TRACKING_A = "A9FEA97B,PHC0,1,1700000000.1,0.000001,0.000002,0.000003,-1.5,0.0,0.01,0.0001,0.0002,16.0,Normal\n"
TRACKING_B = TRACKING_A.replace("PHC0", "GPS").replace("-1.5", "-2.5")

FAKE_CHRONYC = """#!/bin/sh
# Gefälschtes chronyc: gibt den Inhalt von $FAKE_DIR/<letztes Argument> aus.
for last; do :; done
if [ "$last" = "kaputt" ]; then echo "506 Cannot talk to daemon" >&2; exit 1; fi
cat "$FAKE_DIR/$last"
"""


class ProviderTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.run_dir = self.dir / "run"
        fake = self.dir / "chronyc"
        fake.write_text(FAKE_CHRONYC)
        fake.chmod(0o755)
        env = {"NTPGUI_RUN_DIR": str(self.run_dir), "NTPGUI_CHRONYC": str(fake),
               "FAKE_DIR": str(self.dir)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ("NTPGUI_REPLAY", "NTPGUI_REPLAY_SPEED", "CHRONYC_HOST"):
            os.environ.pop(key, None)
        providers.stop()
        providers.reset_replay()
        self.addCleanup(providers.reset_replay)
        self.addCleanup(providers.stop)

    def set_tracking(self, text):
        (self.dir / "tracking").write_text(text)

    def lines(self, path):
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def replay(self, path, speed=None):
        os.environ["NTPGUI_REPLAY"] = str(path)
        if speed is not None:
            os.environ["NTPGUI_REPLAY_SPEED"] = str(speed)
        providers.reset_replay()


class RecordReplayTests(ProviderTestBase):
    def test_live_run_via_fake_chronyc(self):
        self.set_tracking(TRACKING_A)
        self.assertEqual(chrony.tracking()["ref_name"], "PHC0")
        with self.assertRaises(chrony.ChronyError):
            chrony.run("kaputt")
        with self.assertRaises(providers.ProviderError) as ctx:
            providers.run("chronyc", ["kaputt"], 2)
        self.assertEqual(ctx.exception.returncode, 1)
        self.assertIn("506", str(ctx.exception))

    def test_nothing_recorded_without_recording(self):
        self.set_tracking(TRACKING_A)
        chrony.tracking()
        self.assertFalse(self.run_dir.exists() and any(self.run_dir.iterdir()))

    def test_roundtrip(self):
        self.set_tracking(TRACKING_A)
        status = providers.start_recording(60)
        self.assertTrue(status["active"])
        self.assertTrue(os.path.basename(status["path"]).startswith("recording-"))
        chrony.tracking()
        with self.assertRaises(chrony.ChronyError):
            chrony.run("kaputt")
        status = providers.stop()
        self.assertFalse(status["active"])
        self.assertEqual(status["entries"], 2)
        self.assertEqual(status["bytes"], os.path.getsize(status["path"]))
        entries = self.lines(status["path"])
        self.assertEqual(entries[0]["kind"], "chronyc")
        self.assertEqual(entries[0]["args"], ["-c", "tracking"])
        self.assertEqual(entries[0]["out"], TRACKING_A)
        for key in ("t", "kind", "args", "out"):
            self.assertIn(key, entries[1])
        # Nach stop() wird nichts mehr aufgezeichnet.
        chrony.tracking()
        self.assertEqual(len(self.lines(status["path"])), 2)

        # Wiedergabe: das echte Programm darf nicht mehr laufen.
        self.set_tracking(TRACKING_B)
        self.replay(status["path"])
        with mock.patch.object(providers.subprocess, "run", side_effect=AssertionError("live!")):
            self.assertEqual(chrony.tracking()["ref_name"], "PHC0")
            with self.assertRaises(chrony.ChronyError):
                chrony.run("kaputt")
            with self.assertRaises(chrony.ChronyError):  # nie aufgezeichnet
                chrony.run("-c", "sources")
            self.assertEqual(chrony.sources(), [])
        self.assertEqual(providers.status()["replay"]["entries"], 2)

    def test_chronyc_host_not_recorded(self):
        self.set_tracking(TRACKING_A)
        os.environ["CHRONYC_HOST"] = "/irgendwo/sock"
        providers.start_recording(60)
        with mock.patch.object(providers.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, TRACKING_A, "")) as run:
            chrony.tracking()
        self.assertIn("/irgendwo/sock", run.call_args[0][0])
        entry = self.lines(providers.stop()["path"])[0]
        self.assertEqual(entry["args"], ["-c", "tracking"])

    def test_timeline_and_loop(self):
        path = self.dir / "rec.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in [
            {"t": 1000.0, "kind": "chronyc", "args": ["-c", "tracking"], "out": "A"},
            {"t": 1010.0, "kind": "chronyc", "args": ["-c", "tracking"], "out": "B"},
            {"t": 1005.0, "kind": "chronyc", "args": ["serverstats"], "out": "S"},
        ]) + "kein json\n")
        now = [0.0]
        rep = providers.Replay(str(path), speed=1, clock=lambda: now[0])
        self.assertEqual(rep.skipped, 1)
        expect = {0: "A", 5: "A", 9.9: "A", 10: "B", 10.9: "B", 11.5: "A", 21.2: "B"}
        for elapsed, out in expect.items():
            now[0] = elapsed
            self.assertEqual(rep.lookup("chronyc", ["-c", "tracking"])["out"], out, elapsed)
        now[0] = 0  # vor dem ersten serverstats-Eintrag: der früheste gilt
        self.assertEqual(rep.lookup("chronyc", ["serverstats"])["out"], "S")
        self.assertIsNone(rep.lookup("chronyc", ["clients"]))
        fast = providers.Replay(str(path), speed=2, clock=lambda: now[0])
        now[0] = 5
        self.assertEqual(fast.lookup("chronyc", ["-c", "tracking"])["out"], "B")

    def test_replay_speed_env_and_missing_file(self):
        self.replay(self.dir / "gibtsnicht.jsonl", speed="kaputt")
        with self.assertRaises(chrony.ChronyError):
            chrony.run("-c", "tracking")
        self.assertEqual(chrony.tracking(), {})
        self.assertIn("error", providers.status()["replay"])
        self.assertEqual(gps.poll_gpsd(timeout=0.2), {})

    def test_pmc_replay_ignores_socket_path(self):
        path = self.dir / "rec.jsonl"
        out = "sending: GET TIME_STATUS_NP\n\tabc RESPONSE MANAGEMENT TIME_STATUS_NP\n\t\tmaster_offset 42\n"
        path.write_text(json.dumps({"t": 1.0, "kind": "pmc", "rc": 0, "out": out,
                                    "args": ["-u", "-b", "0", "-d", "0", "-s", "/anderer/pfad",
                                             "GET TIME_STATUS_NP"]}) + "\n")
        self.replay(path)
        with mock.patch.object(ptp, "_cfg", return_value={"ptp_domain": 0}), \
                mock.patch.object(ptp, "_pmc_base",
                                  return_value=["/x/pmc", "-u", "-s", "/var/run/ptp4l"]):
            self.assertEqual(ptp._query("TIME_STATUS_NP")["master_offset"], "42")
            self.assertEqual(ptp._query("PORT_DATA_SET"), {})

    def test_cli_replay_info(self):
        path = self.dir / "rec.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in [
            {"t": 10.0, "kind": "chronyc", "args": ["-c", "tracking"], "out": "A"},
            {"t": 12.0, "kind": "gpsd", "args": ["?WATCH={}"], "out": "{}", "s": 1},
            {"t": 13.5, "kind": "ethtool", "args": ["-T", "eth0"], "out": "x"},
        ]))
        proc = subprocess.run([sys.executable, str(APP / "providers.py"), "replay-info", str(path)],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        info = json.loads(proc.stdout)
        self.assertEqual(info["entries"], 3)
        self.assertEqual(info["duration"], 3.5)
        self.assertEqual(info["kinds"], {"chronyc": 1, "gpsd": 1, "ethtool": 1})
        self.assertEqual(info["gpsd_sessions"], 1)
        bad = subprocess.run([sys.executable, str(APP / "providers.py")], capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(bad.returncode, 2)


class RecordingLimitTests(ProviderTestBase):
    def test_duration_bounds(self):
        for value in (0, 3601, "abc", None):
            with self.assertRaises(ValueError):
                providers.start_recording(value)
        self.assertTrue(providers.start_recording(3600)["active"])

    def test_expires(self):
        providers.start_recording(5)
        with providers._REC_LOCK:
            providers._REC["until"] = time.time() - 1
        status = providers.status()
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "zeit")
        providers._record("chronyc", ["x"], "y")
        self.assertEqual(status["path"] and os.path.getsize(status["path"]), 0)

    def test_size_cap(self):
        with mock.patch.object(providers, "MAX_BYTES", 1000):
            path = providers.start_recording(60)["path"]
            for _ in range(50):
                providers._record("chronyc", ["-c", "clients"], "x" * 100)
            status = providers.status()
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "größe")
        self.assertLessEqual(os.path.getsize(path), 1000)
        self.assertEqual(status["bytes"], os.path.getsize(path))
        self.assertEqual(len(self.lines(path)), status["entries"])

    def test_keeps_only_latest_recordings(self):
        paths = [providers.start_recording(60)["path"] for _ in range(5)]
        left = sorted(p.name for p in self.run_dir.iterdir())
        self.assertEqual(len(left), providers.KEEP_RECORDINGS)
        self.assertIn(os.path.basename(paths[-1]), left)

    def test_concurrent_writes(self):
        path = providers.start_recording(60)["path"]
        done = subprocess.CompletedProcess([], 0, "out " * 50, "")
        errors = []

        def worker(n):
            try:
                for i in range(40):
                    if i % 2:
                        providers.call("ethtool", ["-T", f"eth{n}"], 1)
                    else:
                        providers._record("chronyc", ["-c", "sources"], f"{n}-{i}")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        with mock.patch.object(providers.subprocess, "run", return_value=done):
            threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(errors, [])
        status = providers.stop()
        entries = self.lines(path)  # jede Zeile vollständiges JSON
        self.assertEqual(len(entries), 320)
        self.assertEqual(status["entries"], 320)
        self.assertEqual(status["bytes"], os.path.getsize(path))


class FakeGpsd:
    """Mini-gpsd: nimmt eine Verbindung pro Zeilenliste an und schickt die Zeilen."""

    def __init__(self, sessions):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        self.received = []
        self.thread = threading.Thread(target=self.serve, args=(sessions,), daemon=True)
        self.thread.start()

    def serve(self, sessions):
        for lines in sessions:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                self.received.append(conn.recv(1024))
                conn.sendall(b"".join(json.dumps(line).encode() + b"\n" for line in lines))

    def close(self):
        self.server.close()
        self.thread.join(2)


TPV = {"class": "TPV", "mode": 3, "time": "2026-11-01T12:00:00.000Z"}
SKY = {"class": "SKY", "nSat": 9, "uSat": 7, "satellites": [{"PRN": 5, "used": True}]}


class GpsdReplayTests(ProviderTestBase):
    def test_gpsd_record_and_replay(self):
        sessions = [[{"class": "VERSION", "release": "3.22"}, TPV, SKY],
                    [{"class": "DEVICES", "devices": []},
                     {"class": "PPS", "device": "/dev/pps0", "real_sec": 6, "real_nsec": 0,
                      "clock_sec": 6, "clock_nsec": 100}]]
        fake = FakeGpsd(sessions)
        os.environ["GPSD_HOST"] = "127.0.0.1"
        os.environ["GPSD_PORT"] = str(fake.port)
        try:
            path = providers.start_recording(60)["path"]
            live = gps.poll_gpsd(timeout=2)
            live_pps = gps.probe_pps(timeout=0.5)
            providers.stop()
        finally:
            fake.close()
        self.assertIn(b"?WATCH=", fake.received[0])
        self.assertEqual(live["TPV"]["mode"], 3)
        self.assertTrue(live_pps["seen"])
        entries = self.lines(path)
        self.assertTrue(all(e["kind"] == "gpsd" for e in entries))
        self.assertEqual(len({e["s"] for e in entries}), 2)

        # gpsd ist weg – die Wiedergabe liefert dieselben Meldungen.
        self.replay(path)
        self.assertEqual(gps.poll_gpsd(timeout=0.5), live)
        replayed = gps.probe_pps(timeout=0.5)
        self.assertTrue(replayed["reachable"] and replayed["seen"])
        self.assertEqual(replayed["pps_devices"], live_pps["pps_devices"])

    def test_replay_without_gpsd_lines_is_unreachable(self):
        path = self.dir / "rec.jsonl"
        path.write_text(json.dumps({"t": 1, "kind": "chronyc", "args": ["x"], "out": ""}) + "\n")
        self.replay(path)
        self.assertEqual(gps.poll_gpsd(timeout=0.2), {})
        self.assertFalse(gps.probe_pps(timeout=0.2)["reachable"])


if __name__ == "__main__":
    unittest.main()
