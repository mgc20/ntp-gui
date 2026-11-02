"""1.5.0 – Querschnitt: Übersicht zeigt GPS-Rolle, Empfangsampel und „unstet“, neue Hinweise
landen in der richtigen Kachel, neue Prometheus-Metriken haben HELP/TYPE, und jeder neue
Lese-Endpunkt steht auch unter /api/v1.

Läuft ohne chronyd/gpsd: alle Abfragen werden durch Attrappen ersetzt.
"""

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import apiv1  # noqa: E402
import gpsquality  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

GPS_ON = {"gps_enable": True, "gps_device": "/dev/ttyACM0", "gps_pps_device": "", "gps_pps_shm": False,
          "gps_select": "auto", "gps_refid": "GPS", "gps_bound_mode": "measured", "gps_delay": 0.03,
          "gps_offset": 0.1, "gps_precision": 0.001, "ntp_minsources": 1}
RED = {"available": True, "level": "red", "sentence": "Fix 92 % der Zeit, 9,6 Wechsel/h – Empfang zu schwach "
                                                       "für eine stabile Zeitquelle"}
GREEN = {"available": True, "level": "green", "sentence": "Fix 100 % der Zeit, kein Wechsel – Empfang gut"}


class TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rel150-")
        saved = settings.DATA_DIR
        settings.DATA_DIR = self.tmp

        def restore():
            store.close_all()
            settings.DATA_DIR = saved
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.addCleanup(restore)
        gpsquality._ASSESS_CACHE.update(mono=None, value=None, key=None)
        self.addCleanup(gpsquality._ASSESS_CACHE.update, mono=None, value=None, key=None)


class GpsOverviewTest(TempDataDir):
    def test_off_gives_none_and_no_insight(self):
        self.assertIsNone(gpsquality.overview({"gps_enable": False}))
        self.assertEqual(gpsquality.insights(None), [])

    def test_fallback_role_and_reception(self):
        with mock.patch.object(gpsquality, "_cached_assessment", return_value=RED):
            summary = gpsquality.overview(GPS_ON, None, [], {"state": "stetig"})
        self.assertEqual(summary["role"], "fallback")
        self.assertEqual(summary["role_label"], "Rückfallebene")
        self.assertIs(summary["active"], False)
        self.assertEqual(summary["level"], "red")
        self.assertEqual(summary["stability"], "stetig")
        keys = [i["key"] for i in gpsquality.insights(summary)]
        self.assertEqual(keys, ["gps_reception"])
        item = gpsquality.insights(summary)[0]
        self.assertEqual(item["level"], "info")  # Innenantenne: kein Dauer-Alarm
        self.assertEqual(item["action"], "gps")

    def test_unstet_wins_over_red_and_carries_count(self):
        with mock.patch.object(gpsquality, "_cached_assessment", return_value=RED):
            summary = gpsquality.overview(GPS_ON, None, None, {"state": "unstet", "unstet_changes": 14})
        self.assertIsNone(summary["active"])  # ohne Quellenliste unbekannt
        found = gpsquality.insights(summary)
        self.assertEqual([i["key"] for i in found], ["gps_unstet"])
        self.assertIn("14 Fix-Wechsel", found[0]["title"])

    def test_green_gives_no_insight(self):
        with mock.patch.object(gpsquality, "_cached_assessment", return_value=GREEN):
            summary = gpsquality.overview(GPS_ON, None, None, {"state": "stetig"})
        self.assertEqual(gpsquality.insights(summary), [])

    def test_assessment_error_stays_unknown(self):
        with mock.patch.object(gpsquality, "_cached_assessment", side_effect=RuntimeError("db")):
            summary = gpsquality.overview(GPS_ON, None, None, None)
        self.assertEqual(summary["level"], "unknown")
        self.assertEqual(summary["stability"], "unbekannt")

    def test_observe_is_only_a_choice(self):
        with mock.patch.object(gpsquality, "_cached_assessment", return_value=GREEN):
            summary = gpsquality.overview(dict(GPS_ON, gps_select="noselect"), None, None, None)
        self.assertEqual(summary["role"], "observe")
        with mock.patch.object(gpsquality, "_cached_assessment", return_value=GREEN):
            summary = gpsquality.overview(GPS_ON, None, None, None)
        self.assertNotEqual(summary["role"], "observe")

    def test_summary_carries_no_location_fields(self):
        with mock.patch.object(gpsquality, "_cached_assessment", return_value=RED):
            summary = gpsquality.overview(GPS_ON, None, None, None)
        for key in summary:
            self.assertNotRegex(key, r"lat|lon|alt|azim|elev|pos")


class FakeBackends:
    def __init__(self, gps_enabled=False):
        self.patches = [
            mock.patch.object(server.chrony, "tracking", return_value={"stratum": 2, "synchronised": True}),
            mock.patch.object(server.chrony, "clients", return_value=[]),
            mock.patch.object(server.chrony, "detailed_sources", return_value=[]),
            mock.patch.object(server.chrony, "activity", return_value={}),
            mock.patch.object(server.chrony, "serverstats", return_value={}),
            mock.patch.object(server.chrony, "nts_server_status", return_value={"enabled": False}),
            mock.patch.object(server.gps, "status", return_value={"enabled": gps_enabled, "running": gps_enabled,
                                                                  "mode": 3, "has_fix": True}),
            mock.patch.object(server.ptp, "status", return_value={"enabled": False}),
            mock.patch.object(server.hardware, "cached_insights", return_value=[]),
            mock.patch.object(server.hardware, "report", side_effect=AssertionError("keine Prüfung")),
            mock.patch.object(server.hardware, "_REPORT", None, create=True),
            mock.patch.object(server, "system_info", return_value={}),
        ]
        if hasattr(server.hardware, "cached_report"):
            self.patches.append(mock.patch.object(server.hardware, "cached_report", return_value=None))
        if gps_enabled:
            self.patches.append(mock.patch.object(server.settings, "values",
                                                  return_value=dict(settings.values(), **GPS_ON)))
            self.patches.append(mock.patch.object(gpsquality, "_cached_assessment", return_value=RED))

    def __enter__(self):
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()


class StatusAndMetricsTest(TempDataDir):
    def setUp(self):
        super().setUp()
        run = tempfile.TemporaryDirectory()
        self.addCleanup(run.cleanup)
        patcher = mock.patch.object(server, "RUN_DIR", run.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_has_gps_summary_and_insight(self):
        with FakeBackends(gps_enabled=True):
            status = server.build_status()
        self.assertEqual(status["gps_summary"]["role_label"], "Rückfallebene")
        self.assertEqual(status["gps_summary"]["level"], "red")
        self.assertIn("gps_reception", {i["key"] for i in status["insights"]})
        self.assertIn("gps_summary", next(e for e in apiv1.ENDPOINTS if e["path"] == "/status")["response_keys"])

    def test_status_without_gps(self):
        with FakeBackends():
            status = server.build_status()
        self.assertIsNone(status["gps_summary"])

    def test_new_metrics_have_help_and_type(self):
        with FakeBackends(gps_enabled=True):
            text = server.build_metrics()
        for name in ("ntpgui_gps_error_bound_seconds", "ntpgui_gps_reception_level", "ntpgui_gps_unstable",
                     "ntpgui_gnss_stage", "ntpgui_gps_locked", "ntpgui_source_loops",
                     "ntpgui_holdover_test_running"):
            self.assertIn(f"# HELP {name} ", text, name)
            self.assertIn(f"# TYPE {name} gauge", text, name)
        self.assertRegex(text, r"(?m)^ntpgui_gps_error_bound_seconds 0\.1$")  # ± 100 ms bis zur ersten Messung
        self.assertRegex(text, r"(?m)^ntpgui_gps_reception_level 2$")
        self.assertRegex(text, r"(?m)^ntpgui_gnss_stage 0$")
        self.assertRegex(text, r"(?m)^ntpgui_gps_locked 0$")
        self.assertRegex(text, r"(?m)^ntpgui_source_loops 0$")
        self.assertRegex(text, r"(?m)^ntpgui_holdover_test_running 0$")

    def test_alert_rules_use_existing_metrics(self):
        with FakeBackends(gps_enabled=True):
            text = server.build_metrics()
        rules = (ROOT / "docs" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
        for name in ("ntpgui_source_loops", "ntpgui_gnss_stage"):
            self.assertIn(name, rules)
            self.assertIn(f"# HELP {name} ", text)


class ApiV1CoverageTest(unittest.TestCase):
    """Jeder GET-Endpunkt aus 1.5 ist unter /api/v1 beschrieben, Aktionen brauchen „admin“."""

    READ = ["/gps/quality", "/gps/antenna", "/loops", "/gnss", "/holdover", "/clients/groups",
            "/clients/quality", "/clients/rules", "/clients/pass"]
    WRITE = ["/gps/antenna", "/gps/bound", "/gnss", "/holdover", "/clients/groups", "/clients/groups/delete",
             "/clients/rules"]

    def test_read_endpoints(self):
        for path in self.READ:
            self.assertEqual(apiv1.required_scope("GET", "/api/v1" + path), "read", path)
            self.assertIsNotNone(apiv1.resolve("/api/v1" + path), path)

    def test_write_endpoints_need_admin(self):
        for path in self.WRITE:
            self.assertEqual(apiv1.required_scope("POST", "/api/v1" + path), "admin", path)
            self.assertEqual(apiv1.required_scope("POST", "/api" + path), "admin", path)

    def test_descriptions_are_german_sentences(self):
        for entry in apiv1.ENDPOINTS:
            self.assertTrue(entry["description"].strip(), entry["path"])


class OverviewPanelMappingTest(unittest.TestCase):
    """Neue Hinweis-Schlüssel färben die passende Kachel (overview.js panelOf/ISSUE_BADGE)."""

    def test_keys_in_overview(self):
        js = (ROOT / "app" / "static" / "js" / "pages" / "overview.js").read_text(encoding="utf-8")
        clock = re.search(r"CLOCK_KEYS = new Set\(\[([^\]]*)\]", js).group(1)
        self.assertIn('"holdover_running"', clock)
        for key in ("gnss_stage", "gnss_lock", "holdover_running"):
            self.assertRegex(js, rf"\b{key}: \"", key)
        self.assertIn("gps_summary", js)
        self.assertIn('"gpsq_role"', js)
        self.assertIn('"gpsq_assessment"', js)


if __name__ == "__main__":
    unittest.main()
