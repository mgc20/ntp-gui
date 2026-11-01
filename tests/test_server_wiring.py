"""Verdrahtung im Server: services.json → Status/Hinweise, neue Metriken.

Läuft ohne chronyd/gpsd: alle Abfragen werden durch Attrappen ersetzt.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import server  # noqa: E402

SERVICES = {
    "time": 1700000000,
    "services": {
        "chronyd": {"state": "running", "restarts": 0, "last_exit": None, "since": 1700000000,
                    "pid": 10, "optional": False, "next_retry": None, "message": ""},
        "gpsd": {"state": "restarting", "restarts": 2, "last_exit": 1, "since": 1700000100,
                 "pid": None, "optional": True, "next_retry": 1700000160,
                 "message": "beendet mit Exit 1, neuer Versuch in 60 s"},
        "ptp4l": {"state": "failed", "restarts": 0, "last_exit": None, "since": 1700000050,
                  "pid": None, "optional": True, "next_retry": None, "message": "Gerät fehlt"},
        "phc2sys": {"state": "stopped", "restarts": 0, "last_exit": None, "since": None,
                    "pid": None, "optional": True, "next_retry": None, "message": ""},
    },
}

FAKE_REPORT = {
    "pps": [{"dev": "/dev/pps0", "state": "live"}, {"dev": "/dev/pps1", "state": "silent"}],
    "matrix": [{"key": "gps_pps", "status": "ok"}, {"key": "ptp_hw", "status": "no"}],
}


class RunDirMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(server, "RUN_DIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write(self, content):
        with open(os.path.join(self.tmp.name, "services.json"), "w", encoding="utf-8") as handle:
            handle.write(content if isinstance(content, str) else json.dumps(content))


class ServicesTest(RunDirMixin, unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(server.services_status(), {})
        self.assertEqual(server.service_insights({}), [])

    def test_broken_files(self):
        for content in ("{kaputt", "[]", '{"services": 3}', '{"services": {"gpsd": "x"}}', ""):
            self.write(content)
            self.assertEqual(server.services_status(), {}, content)

    def test_parsing(self):
        self.write(SERVICES)
        svc = server.services_status()
        self.assertEqual(set(svc), {"chronyd", "gpsd", "ptp4l", "phc2sys"})
        self.assertEqual(svc["gpsd"]["state"], "restarting")
        self.assertEqual(svc["gpsd"]["restarts"], 2)
        self.assertEqual(svc["gpsd"]["last_exit"], 1)
        self.assertTrue(svc["gpsd"]["optional"])
        self.assertFalse(svc["chronyd"]["optional"])
        self.assertEqual(svc["gpsd"]["label"], "gpsd (GPS)")

    def test_unknown_state_and_bad_types(self):
        self.write({"services": {"gpsd": {"state": "explodiert", "restarts": "viele", "since": "gestern"}}})
        svc = server.services_status()["gpsd"]
        self.assertEqual(svc["state"], "unknown")
        self.assertEqual(svc["restarts"], 0)
        self.assertIsNone(svc["since"])
        self.assertEqual(server.service_insights({"gpsd": svc}), [])

    def test_insights(self):
        self.write(SERVICES)
        found = server.service_insights(server.services_status(), now=1700000130)
        by_key = {i["key"]: i for i in found}
        self.assertEqual(set(by_key), {"service_gpsd", "service_ptp4l"})
        gpsd = by_key["service_gpsd"]
        self.assertEqual(gpsd["level"], "warn")
        self.assertIn("ausgefallen und wird neu gestartet (Versuch 3)", gpsd["title"])
        self.assertIn("30 s", gpsd["text"])
        self.assertEqual(by_key["service_ptp4l"]["level"], "crit")
        self.assertIn("Gerät fehlt", by_key["service_ptp4l"]["text"])
        for item in found:
            self.assertEqual(set(item), {"level", "key", "title", "text", "action"})


class FakeBackends:
    """Ersetzt alles, was build_status/build_metrics sonst live abfragen."""

    def __init__(self, report=None, nts=None):
        self.patches = [
            mock.patch.object(server.chrony, "tracking", return_value={"stratum": 2, "synchronised": True}),
            mock.patch.object(server.chrony, "clients", return_value=[]),
            mock.patch.object(server.chrony, "detailed_sources", return_value=[]),
            mock.patch.object(server.chrony, "activity", return_value={}),
            mock.patch.object(server.chrony, "serverstats", return_value={}),
            mock.patch.object(server.chrony, "nts_server_status",
                              return_value=nts or {"enabled": False}),
            mock.patch.object(server.gps, "status", return_value={"enabled": False}),
            mock.patch.object(server.ptp, "status", return_value={"enabled": False}),
            mock.patch.object(server.hardware, "cached_insights", return_value=[]),
            mock.patch.object(server.hardware, "report",
                              side_effect=AssertionError("/metrics darf keine Prüfung starten")),
            mock.patch.object(server.hardware, "_REPORT", report, create=True),
        ]
        if hasattr(server.hardware, "cached_report"):
            self.patches.append(mock.patch.object(server.hardware, "cached_report", return_value=report))

    def __enter__(self):
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()


class StatusTest(RunDirMixin, unittest.TestCase):
    def test_status_contains_services_and_insights(self):
        self.write(SERVICES)
        with FakeBackends(), mock.patch.object(server, "system_info", return_value={}):
            status = server.build_status()
        self.assertIn("gpsd", status["services"])
        keys = {i["key"] for i in status["insights"]}
        self.assertIn("service_gpsd", keys)
        self.assertIn("service_ptp4l", keys)

    def test_status_without_file(self):
        with FakeBackends(), mock.patch.object(server, "system_info", return_value={}):
            status = server.build_status()
        self.assertEqual(status["services"], {})


class MetricsTest(RunDirMixin, unittest.TestCase):
    def test_new_gauges(self):
        self.write(SERVICES)
        nts = {"enabled": True, "days_left": 42.5}
        with FakeBackends(report=FAKE_REPORT, nts=nts):
            text = server.build_metrics()
        self.assertIn('ntpgui_service_up{service="chronyd"} 1', text)
        self.assertIn('ntpgui_service_up{service="gpsd"} 0', text)
        self.assertIn('ntpgui_service_restarts_total{service="gpsd"} 2', text)
        self.assertIn("# TYPE ntpgui_service_restarts_total counter", text)
        self.assertIn('ntpgui_pps_live{device="/dev/pps0"} 1', text)
        self.assertIn('ntpgui_pps_live{device="/dev/pps1"} 0', text)
        self.assertIn('ntpgui_hardware_capability{key="gps_pps",status="ok"} 1', text)
        self.assertIn('ntpgui_hardware_capability{key="ptp_hw",status="no"} 1', text)
        self.assertIn("ntpgui_nts_server_cert_days_left 42.5", text)
        # bestehende Metriken bleiben
        self.assertIn("ntpgui_up 1", text)
        self.assertIn("ntpgui_stratum 2", text)
        # jede Metrik genau ein HELP/TYPE
        for name in ("ntpgui_service_up", "ntpgui_pps_live", "ntpgui_hardware_capability"):
            self.assertEqual(text.count(f"# TYPE {name} "), 1)

    def test_without_report_or_files(self):
        with FakeBackends(report=None):
            text = server.build_metrics()
        self.assertNotIn("ntpgui_service_up", text)
        self.assertNotIn("ntpgui_pps_live", text)
        self.assertNotIn("ntpgui_hardware_capability", text)
        self.assertNotIn("ntpgui_nts_server_cert_days_left", text)
        self.assertIn("ntpgui_up 1", text)

    def test_broken_report(self):
        broken = {"pps": [None, {"state": "live"}], "matrix": ["x", {"key": "nts"}]}
        with FakeBackends(report=broken):
            text = server.build_metrics()
        self.assertNotIn("ntpgui_pps_live", text)
        self.assertNotIn("ntpgui_hardware_capability", text)


class RefresherTest(unittest.TestCase):
    def test_runs_and_survives_errors(self):
        stop = threading.Event()
        calls = []

        def fake_report(cfg, refresh=False):
            calls.append(refresh)
            if len(calls) == 1:
                raise RuntimeError("kaputt")
            stop.set()
            return {}

        with mock.patch.object(server, "HARDWARE_FIRST_DELAY", 0), \
                mock.patch.object(server, "HARDWARE_INTERVAL", 0.01), \
                mock.patch.object(server.hardware, "report", side_effect=fake_report), \
                mock.patch.object(server.settings, "values", return_value={}), \
                mock.patch("builtins.print"):
            worker = threading.Thread(target=server.hardware_refresher, args=(stop,), daemon=True)
            worker.start()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, [True, True])

    def test_stop_before_first_run(self):
        stop = threading.Event()
        stop.set()
        with mock.patch.object(server.hardware, "report", side_effect=AssertionError):
            server.hardware_refresher(stop)


if __name__ == "__main__":
    unittest.main()
