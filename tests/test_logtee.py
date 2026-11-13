"""logtee.py (Log-Datei neben dem Container-Log) und die Ereignis-Helfer des Supervisors."""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import logtee  # noqa: E402


class BrokenStream(io.BytesIO):
    def write(self, data):
        raise BrokenPipeError("Leser weg")


class LogteeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = self.tmp / "ntp-gui.log"

    def test_copies_unchanged(self):
        data = b"[chrony] starte\n[gps] \xc3\x9cmlaut und kaputtes \xff Byte\nohne Zeilenende"
        out = io.BytesIO()
        logtee.run(io.BytesIO(data), out, str(self.path))
        self.assertEqual(out.getvalue(), data)
        self.assertEqual(self.path.read_bytes(), data)

    def test_known_gpsd_shm_line_is_explained(self):
        # Beim Beenden von gpsd stand ohne Präfix eine „failed“-Zeile im Log.
        # Sie ist harmlos (das SHM-Segment gehört chronyd) und wird darum erklärt, nicht verschluckt.
        data = (b"[chrony] Konfiguration geschrieben\n"
                b"SHM: shmctl(7) for IPC_RMID failed, Operation not permitted(1)\n"
                b"SHM: shmget(0x4e545030, 96, 01600) for unit 0 failed\n")
        out = io.BytesIO()
        logtee.run(io.BytesIO(data), out, str(self.path))
        lines = out.getvalue().decode().splitlines()
        self.assertEqual(lines[0], "[chrony] Konfiguration geschrieben")
        self.assertTrue(lines[1].startswith("[gps] "), lines[1])
        self.assertIn("harmlos", lines[1])
        self.assertIn("IPC_RMID", lines[1])
        self.assertNotIn("failed", lines[1])
        self.assertEqual(lines[2], "SHM: shmget(0x4e545030, 96, 01600) for unit 0 failed")  # anderes: unverändert
        self.assertEqual(self.path.read_text().splitlines(), lines)

    def test_rotation_keeps_one_old_file(self):
        out = io.BytesIO()
        lines = b"".join(f"Zeile {i:04d} ".encode() + b"x" * 80 + b"\n" for i in range(100))
        logtee.run(io.BytesIO(lines), out, str(self.path), max_bytes=1000)
        self.assertEqual(out.getvalue(), lines)
        self.assertTrue((self.tmp / "ntp-gui.log.1").exists())
        self.assertFalse((self.tmp / "ntp-gui.log.2").exists())
        self.assertLessEqual(self.path.stat().st_size, 1000)
        self.assertLessEqual((self.tmp / "ntp-gui.log.1").stat().st_size, 1000)
        self.assertTrue(self.path.read_bytes().endswith(b"Zeile 0099 " + b"x" * 80 + b"\n"))

    def test_unwritable_file_never_stops_stdout(self):
        blocked = self.tmp / "verzeichnis"
        blocked.mkdir()
        out = io.BytesIO()
        logtee.run(io.BytesIO(b"a\nb\n"), out, str(blocked))  # Pfad ist ein Verzeichnis
        self.assertEqual(out.getvalue(), b"a\nb\n")

    def test_broken_stdout_keeps_file(self):
        logtee.run(io.BytesIO(b"a\nb\n"), BrokenStream(), str(self.path))
        self.assertEqual(self.path.read_bytes(), b"a\nb\n")

    def test_interrupted_read_is_retried(self):
        class Flaky(io.BytesIO):
            calls = 0

            def readline(self, *a):
                Flaky.calls += 1
                if Flaky.calls == 2:
                    raise InterruptedError("EINTR")
                return super().readline(*a)
        out = io.BytesIO()
        logtee.run(Flaky(b"a\nb\nc\n"), out, str(self.path))
        self.assertEqual(out.getvalue(), b"a\nb\nc\n")

    def test_deleted_file_is_recreated(self):
        target = logtee.RotatingFile(str(self.path))
        target.write(b"eins\n")
        self.path.unlink()
        target.write(b"zwei\n")
        target.close()
        self.assertEqual(self.path.read_bytes(), b"zwei\n")

    def test_as_process(self):
        env = dict(os.environ, NTPGUI_RUN_DIR=str(self.tmp))
        proc = subprocess.run([sys.executable, str(ROOT / "app" / "logtee.py")], input=b"x\ny\n",
                              capture_output=True, env=env, timeout=20, check=True)
        self.assertEqual(proc.stdout, b"x\ny\n")
        self.assertEqual(self.path.read_bytes(), b"x\ny\n")


def _functions(*names):
    text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    chunks = []
    for name in names:
        match = re.search(rf"^{name}\(\) \{{.*?^\}}$", text, re.S | re.M)
        assert match, name
        chunks.append(match.group(0))
    return "\n".join(chunks)


@unittest.skipUnless(shutil.which("bash") and shutil.which("stat"), "bash/stat fehlen")
class SupervisorEventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def bash(self, body, check=True, app_dir=None):
        script = (f"set -euo pipefail\nRUN_DIR='{self.tmp}'\nAPP_DIR='{app_dir or ROOT / 'app'}'\n"
                  "EVENTS_MAX=1048576\n"
                  "LOGTEE_PID=''\nLOG_OUT_FD=''\nLOG_ERR_FD=''\nnow() { echo 1700000000; }\n"
                  + _functions("json_str", "emit_event", "start_logtee", "stop_logtee") + "\n" + body)
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=check)

    def events(self):
        lines = (self.tmp / "events.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def test_emit_event_writes_valid_json(self):
        self.bash("""
emit_event service warn 'Dienst gpsd unerwartet beendet (Exit 143) – "Neustart" in 5 s' service=gpsd exit=143 delay=5
emit_event reload info $'Zeile mit\\nUmbruch, \\\\Backslash und\\tTab' reason=hotplug device=/dev/ttyACM0
emit_event startup info 'ntp-gui gestartet' version= kaputt
""")
        events = self.events()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0], {"t": 1700000000, "kind": "service", "level": "warn",
                                     "title": 'Dienst gpsd unerwartet beendet (Exit 143) – "Neustart" in 5 s',
                                     "data": {"service": "gpsd", "exit": 143, "delay": 5}})
        self.assertEqual(events[1]["title"], "Zeile mit Umbruch, \\Backslash und Tab")
        self.assertEqual(events[1]["data"], {"reason": "hotplug", "device": "/dev/ttyACM0"})
        self.assertEqual(events[2]["data"], {"version": ""})

    def test_emit_event_never_fails(self):
        (self.tmp / "events.jsonl").mkdir()  # nicht beschreibbar
        result = self.bash("emit_event service info test; echo weiter")
        self.assertIn("weiter", result.stdout)

    def test_emit_event_rotates(self):
        (self.tmp / "events.jsonl").write_text("x" * 2000 + "\n")
        self.bash("EVENTS_MAX=1000\nemit_event startup info neu")
        self.assertTrue((self.tmp / "events.jsonl.1").exists())
        self.assertEqual(len(self.events()), 1)

    def test_logtee_keeps_container_log_and_exit_code(self):
        result = self.bash("""
trap stop_logtee EXIT
start_logtee
echo "[main] auf stdout"
echo "[main] auf stderr" >&2
( echo "[kind] von einem Kindprozess" )
exit 3
""", check=False)
        self.assertEqual(result.returncode, 3)
        combined = result.stdout + result.stderr
        for line in ("[main] auf stdout", "[main] auf stderr", "[kind] von einem Kindprozess"):
            self.assertIn(line, combined)
        log = (self.tmp / "ntp-gui.log").read_text(encoding="utf-8")
        self.assertIn("[main] auf stdout", log)
        self.assertIn("[main] auf stderr", log)
        self.assertIn("[kind] von einem Kindprozess", log)

    def test_cat_takes_over_when_logtee_exits_cleanly(self):
        """Review 1/3: endet logtee mit Exit 0 (z. B. nach einem Lesefehler), liest cat weiter."""
        fake = self.tmp / "fakeapp"
        fake.mkdir()
        (fake / "logtee.py").write_text("import sys\nsys.stdout.write(sys.stdin.readline())\n"
                                        "sys.stdout.flush()\nsys.exit(0)\n")
        result = self.bash("""
trap stop_logtee EXIT
start_logtee
echo "[main] erste Zeile"
for i in $(seq 1 3000); do echo "[main] Zeile $i"; done
echo "[main] letzte Zeile"
exit 5
""", check=False, app_dir=fake)
        self.assertEqual(result.returncode, 5, result.stderr[-500:])
        self.assertIn("[main] erste Zeile", result.stdout)
        self.assertIn("[main] letzte Zeile", result.stdout)

    def test_stop_prints_no_stray_error(self):
        """Review 1/4: kein „/proc/<pid>/stat: No such file or directory“ beim Beenden."""
        result = self.bash("""
trap stop_logtee EXIT
start_logtee
echo "[main] hallo"
exit 0
""", check=False)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("/stat", result.stdout + result.stderr)
        self.assertIn("[main] hallo", result.stdout)

    def test_logtee_off(self):
        result = self.bash("NTPGUI_LOGTEE=0\nstart_logtee\necho hallo")
        self.assertIn("hallo", result.stdout)
        self.assertFalse((self.tmp / "ntp-gui.log").exists())

    def test_entrypoint_routes_output_early_and_restores_on_exit(self):
        text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        body = text[text.index("# --- Vorbereitung"):]
        self.assertLess(body.index("start_logtee"), body.index("apply_config"))
        self.assertIn("trap 'stop_logtee' EXIT", text)
        for kind in ("service", "reload", "cert", "gps", "startup"):
            self.assertRegex(text, rf"EMIT_EVENT(:-:)?}}?\"? {kind} (info|warn|crit) ")


if __name__ == "__main__":
    unittest.main()
