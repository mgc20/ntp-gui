"""Sprünge der Systemzeit (B5, B7): Fristen, Zwischenspeicher und Laufzeit hängen an der monotonen
Uhr, nicht an der Wanduhr. Die Wanduhr bleibt nur für Zeitstempel.

Läuft ohne chronyd/gpsd/ptp4l: alle Abfragen werden durch Attrappen ersetzt.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import gps  # noqa: E402
import ptp  # noqa: E402
import server  # noqa: E402


class Clock:
    """Wanduhr und monotone Uhr getrennt stellbar."""

    def __init__(self):
        self.wall = 1_800_000_000.0
        self.mono = 10_000.0

    def step(self, seconds):        # normale Zeit vergeht: beide Uhren laufen
        self.wall += seconds
        self.mono += seconds

    def jump(self, seconds):        # nur die Systemzeit springt
        self.wall += seconds

    def patch(self, module):
        return (mock.patch.object(module.time, "time", side_effect=lambda: self.wall),
                mock.patch.object(module.time, "monotonic", side_effect=lambda: self.mono))


class CacheTtlTest(unittest.TestCase):
    """B5: Nach einem Rücksprung der Systemzeit darf der Status-Zwischenspeicher nicht einfrieren."""

    def run_status(self, module, status, collect_name, collect):
        clock = Clock()
        wall, mono = clock.patch(module)
        calls = []

        def counting(*_args, **_kwargs):
            calls.append(clock.wall)
            return collect()

        with wall, mono, mock.patch.object(module, "enabled", return_value=True), \
                mock.patch.object(module, collect_name, side_effect=counting):
            status()
            clock.jump(-3600)
            for _ in range(3):
                clock.step(10)
                status()
        return calls

    def setUp(self):
        gps._CACHE = {}
        gps._CACHE_TIME = 0.0
        ptp._CACHE.clear()
        ptp._CACHE_TIME = 0.0
        self.addCleanup(lambda: (setattr(gps, "_CACHE", {}), setattr(gps, "_CACHE_TIME", 0.0),
                                 ptp._CACHE.clear(), setattr(ptp, "_CACHE_TIME", 0.0)))

    def test_gps_cache_follows_monotonic_clock(self):
        with mock.patch.object(gps, "_remember_position"), \
                mock.patch.object(gps, "_setting", return_value=""):
            calls = self.run_status(gps, gps.status, "poll_gpsd", lambda: {})
        self.assertEqual(len(calls), 4)

    def test_ptp_cache_follows_monotonic_clock(self):
        calls = self.run_status(ptp, ptp.status, "_collect", lambda: {"running": True})
        self.assertEqual(len(calls), 4)


class UptimeTest(unittest.TestCase):
    """B7: Laufzeit des Servers nach monotoner Uhr."""

    def test_system_info_uptime_survives_backward_jump(self):
        with mock.patch.object(server.time, "time", return_value=server.time.time() - 3600), \
                mock.patch.object(server, "clock_control", return_value={}), \
                mock.patch.object(server.socket, "getaddrinfo", return_value=[]):
            info = server.system_info(server.settings.values())
        self.assertGreaterEqual(info["uptime_seconds"], 0)
        self.assertLess(info["uptime_seconds"], 3600)

    def test_system_info_uptime_ignores_forward_jump(self):
        with mock.patch.object(server.time, "time", return_value=server.time.time() + 400 * 86400), \
                mock.patch.object(server, "clock_control", return_value={}), \
                mock.patch.object(server.socket, "getaddrinfo", return_value=[]):
            info = server.system_info(server.settings.values())
        self.assertLess(info["uptime_seconds"], 86400)

    def test_diag_options_uptime_survives_backward_jump(self):
        handler = server.Handler.__new__(server.Handler)
        with mock.patch.object(server.time, "time", return_value=server.time.time() - 3600), \
                mock.patch.object(server.HISTORY, "snapshot", return_value=[]), \
                mock.patch.object(server.ALLAN, "get", return_value=None):
            options = handler._diag_options({})
        self.assertGreaterEqual(options["uptime_seconds"], 0)
        self.assertLess(options["uptime_seconds"], 3600)


def _entrypoint_text():
    return (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")


def _functions(*names):
    text = _entrypoint_text()
    chunks = []
    for name in names:
        match = re.search(rf"^{name}\(\) \{{.*?^\}}$", text, re.S | re.M)
        assert match, name
        chunks.append(match.group(0))
    return "\n".join(chunks)


class PruneClockFeedTest(unittest.TestCase):
    """B4: Der Status-Abruf (collect_sample) füllt den Zwischenspeicher für events.clock_state –
    außerhalb von events._LOCK, damit prune() selbst nie chronyc aufruft."""

    def tearDown(self):
        import events
        events._CLOCK.update(plausible=None, at=None, noted=False, held=False)

    def test_collect_sample_feeds_clock_state(self):
        import chrony
        import events
        from test_parsers import TRACKING_LOCAL
        events._CLOCK.update(plausible=None, at=None, noted=False, held=False)
        with mock.patch.object(chrony, "tracking", return_value=chrony.parse_tracking(TRACKING_LOCAL)), \
                mock.patch.object(chrony, "serverstats", return_value={}), \
                mock.patch.object(chrony, "clients", return_value=[]), \
                mock.patch.object(chrony, "merged_sources", return_value=[]), \
                mock.patch.object(gps, "enabled", return_value=False), \
                mock.patch.object(ptp, "enabled", return_value=False):
            server.collect_sample()
        self.assertIs(events.clock_state(), True)
        with mock.patch.object(chrony, "tracking", return_value={}), \
                mock.patch.object(chrony, "serverstats", return_value={}), \
                mock.patch.object(chrony, "clients", return_value=[]), \
                mock.patch.object(chrony, "merged_sources", return_value=[]), \
                mock.patch.object(gps, "enabled", return_value=False), \
                mock.patch.object(ptp, "enabled", return_value=False):
            server.collect_sample()
        self.assertIsNone(events.clock_state())  # chronyc nicht abfragbar = unbekannt


class EntrypointMonotonicStaticTest(unittest.TestCase):
    """B5: Fristen im Supervisor nach /proc/uptime, nicht nach Wanduhr (und nicht nach $SECONDS –
    das rechnet bash aus gettimeofday und springt mit der Systemzeit)."""

    def test_deadlines_use_monotonic_clock(self):
        text = _entrypoint_text()
        self.assertIn("/proc/uptime", _functions("mono"))
        self.assertNotRegex(text, r"NEXT_HOTPLUG=\$\(\( *(\$\(now\)|\$?NOW)")
        self.assertNotRegex(text, r"\(\( *\$?NOW *>= *(NEXT_HOTPLUG|NEXT_NTS_CERT|\$\{SVC_NEXT)")
        self.assertNotRegex(text, r"check_nts_cert \"\$NOW\"")
        self.assertNotIn("$SECONDS", text)
        restart = _functions("schedule_restart")
        self.assertNotIn("$(now)", restart)
        self.assertIn("$(mono)", restart)
        self.assertRegex(_functions("set_state"), r"SVC_STARTED\[\$1\]=\"\$\(mono\)\"")


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class EntrypointMonotonicTest(unittest.TestCase):
    STUBS = """
set -euo pipefail
log() { :; }
write_status() { :; }
declare -A SVC_ENTRY=() SVC_STATE=() SVC_RESTARTS=() SVC_EXIT=() SVC_SINCE=() \\
           SVC_NEXT=() SVC_STARTED=() SVC_FAILS=() SVC_NOTE=() SVC_ON=()
SERVICES=(gpsd); OPTIONAL_SERVICES=" gpsd "
BACKOFF=(5 15 60 300); STABLE_AFTER=600
json_str() { printf '"%s"' "$1"; }
"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_bash(self, body, *funcs):
        script = self.STUBS + f"RUN_DIR='{self.tmp}'\n" + _functions(*funcs) + "\n" + body
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              timeout=20, check=True).stdout.split()

    def test_mono_reads_proc_uptime(self):
        out = self.run_bash('a=$(mono); sleep 1.1; b=$(mono); echo "$a" "$b"', "now", "mono")
        with open("/proc/uptime", encoding="utf-8") as handle:
            uptime = float(handle.read().split()[0])
        a, b = (int(x) for x in out)
        self.assertLessEqual(abs(a - uptime), 5)
        self.assertGreaterEqual(b - a, 1)

    def test_restart_deadline_ignores_wall_clock_jump(self):
        """Dienst stirbt, dann springt die Systemzeit eine Stunde zurück: Neustart-Frist und
        Laufzeit bleiben richtig; services.json nennt next_retry weiter als Unix-Zeit."""
        out = self.run_bash("""
WALL=1700000000; MONO=100
now() { echo "$WALL"; }
mono() { echo "$MONO"; }
set_state gpsd running
SVC_FAILS[gpsd]=2   # zwei Fehlstarts zuvor; nach stabilem Lauf zählt das nicht mehr
MONO=$(( MONO + 700 )); WALL=$(( WALL + 700 - 3600 ))   # 700 s gelaufen, Uhr springt -1 h
SVC_ENTRY[gpsd]="999999999=gpsd"
schedule_restart gpsd 2>/dev/null
echo "next:${SVC_NEXT[gpsd]}" "fails:${SVC_FAILS[gpsd]}"
cat "$RUN_DIR/services.json"
""", "write_services", "set_state", "wait_exec", "service_alive", "schedule_restart")
        self.assertEqual(out[0], "next:805")      # mono 800 + 5 s Pause
        self.assertEqual(out[1], "fails:1")       # 700 s ≥ STABLE_AFTER → Zähler zurückgesetzt (sonst 3, Pause 60 s)
        data = json.loads(" ".join(out[2:]))
        self.assertEqual(data["services"]["gpsd"]["next_retry"], 1700000000 + 700 - 3600 + 5)


if __name__ == "__main__":
    unittest.main()
