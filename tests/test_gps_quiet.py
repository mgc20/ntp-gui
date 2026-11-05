"""1.5.4 – GPS bei schwachem Empfang ruhig: Hinweis „gps_nofix“ und die Kurzfassung für die Übersicht.

Diagnosepaket 1.5.3 (VK-162 drinnen, GPS nur Rückfallebene, 5 NTS-Quellen): Der Hinweis lautete
„GPS hat noch keinen Fix“ (warn), obwohl der Fix nur kam und ging und die Netzquellen die Zeit trugen.
Die Replays zu Positionssprung, Ereignissen und Fehlerschranke stehen in test_gnssguard
(WeakGeometryTest), test_statewatch (WeakReceptionTest) und test_gpsquality (BoundHysteresisTest).
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import gpsquality  # noqa: E402
import insights  # noqa: E402
import statewatch  # noqa: E402

CFG = {"ntp_minsources": 1, "gps_refid": "GPS", "gps_delay": 0.2}
NET_OK = [{"mode": "^", "name": "nts1", "state": "*", "reach": 255},
          {"mode": "^", "name": "nts2", "state": "+", "reach": 255},
          {"mode": "#", "name": "GPS", "state": "?", "reach": 0}]
NET_DOWN = [{"mode": "^", "name": "nts1", "state": "?", "reach": 0},
            {"mode": "#", "name": "GPS", "state": "?", "reach": 0}]


def nofix(sources, summary=None, pps=""):
    status = {"chrony_running": True, "tracking": {}, "sources": sources, "system": {},
              "ui": {"storage": {"persistent": True}, "auth": {"enabled": True}},
              "gps": {"enabled": True, "running": True, "has_fix": False, "satellites_seen": 15,
                      "satellites_used": 0, "pps": pps},
              "gps_summary": summary}
    return next(i for i in insights.build(status, CFG) if i["key"] == "gps_nofix")


class NoFixHintTest(unittest.TestCase):
    def test_flapping_fix_with_network_is_info(self):
        item = nofix(NET_OK, {"weak": True, "last_fix_s": 240})
        self.assertEqual(item["level"], "info")
        self.assertEqual(item["title"], "GPS gerade ohne Fix – schwacher Empfang, kommt und geht")
        self.assertIn("vor 4 min", item["text"])
        self.assertIn("Netzquellen tragen die Zeit", item["text"])

    def test_recent_fix_without_weak_flag(self):
        item = nofix(NET_OK, {"weak": False, "last_fix_s": 1200})
        self.assertEqual(item["title"], "GPS gerade ohne Fix – schwacher Empfang, kommt und geht")

    def test_no_fix_ever_is_old_wording(self):
        item = nofix(NET_OK, {"weak": False, "last_fix_s": None})
        self.assertEqual(item["title"], "GPS hat noch keinen Fix")
        self.assertEqual(item["level"], "info")              # Netz trägt: GPS ist nur Rückfallebene

    def test_warn_when_gps_matters(self):
        self.assertEqual(nofix(NET_DOWN, {"weak": True, "last_fix_s": 60})["level"], "warn")
        self.assertEqual(nofix(NET_OK, {"weak": True, "last_fix_s": 60}, pps="/dev/pps0")["level"], "warn")
        item = nofix(NET_DOWN, None)
        self.assertEqual((item["level"], item["title"]), ("warn", "GPS hat noch keinen Fix"))
        self.assertIn("keine Netzquelle", item["text"])


class SummaryTest(unittest.TestCase):
    def test_overview_carries_weak_and_last_fix(self):
        now = [0.0]
        watch = statewatch.StateWatcher(lambda *a, **k: None, clock=lambda: now[0])
        for mode in [3, 3, 1, 1] * 6:
            watch.sample({"gps": {"mode": mode}})
            now[0] += 10
        stability = watch.gps_stability()
        self.assertTrue(stability["weak"])
        self.assertEqual(stability["last_fix_s"], 20)   # zuletzt bestätigt beim ersten „1“
        with mock.patch.object(gpsquality, "_cached_assessment", return_value={"available": False}), \
                mock.patch.object(gpsquality, "role", return_value={"role": "fallback"}):
            summary = gpsquality.overview({"gps_enable": True}, None, None, stability)
        self.assertEqual((summary["weak"], summary["last_fix_s"]), (True, 20))

    def test_reception_weak_from_assessment(self):
        cases = [([{"key": "changes", "level": "yellow"}], True), ([{"key": "fix", "level": "red"}], True),
                 ([{"key": "fix", "level": "yellow"}], False), ([{"key": "cn0", "level": "red"}], False), ([], False)]
        for reasons, expected in cases:
            with mock.patch.object(gpsquality, "_cached_assessment", return_value={"reasons": reasons}):
                self.assertIs(gpsquality.reception_weak(None), expected, reasons)
        with mock.patch.object(gpsquality, "_cached_assessment", side_effect=RuntimeError("kaputt")):
            self.assertFalse(gpsquality.reception_weak(None))


if __name__ == "__main__":
    unittest.main()
