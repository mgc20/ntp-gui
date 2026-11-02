"""Integrationen: Grafana-Dashboard und Prometheus-Alarmregeln passen zu /metrics.

Jede Metrik, die docs/grafana/ntp-gui.json oder docs/prometheus/alerts.yml benutzt, muss im
Output von server.build_metrics() stehen – mit HELP und TYPE. Die Daten dahinter sind
Attrappen, die jede optionale Metrik einschalten (GPS, PTP, NTS, Temperatur, Schaltsekunden,
Update-Hinweis, PPS).
"""

import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import updatecheck  # noqa: E402

DASHBOARD = ROOT / "docs" / "grafana" / "ntp-gui.json"
ALERTS = ROOT / "docs" / "prometheus" / "alerts.yml"
FIXTURES = ROOT / "tests" / "fixtures"
METRIC_RE = re.compile(r"\bntpgui_[a-z0-9_]+\b")

TRACKING = {"ref_id": "50505300", "ref_name": "PPS", "stratum": 1, "system_time_offset": 2e-7,
            "last_offset": 1e-7, "rms_offset": 3e-7, "frequency_ppm": -12.3, "skew_ppm": 0.01,
            "root_delay": 1e-6, "root_dispersion": 2e-5, "leap_status": "Normal", "synchronised": True}
SOURCES = [{"name": "PPS", "mode_label": "Referenzuhr", "state": "*", "offset": 1e-7, "stratum": 0,
            "reach_percent": 100, "std_dev": 1e-7, "authenticated": False},
           {"name": "ptbtime1.ptb.de", "mode_label": "Server", "state": "-", "offset": 2e-4, "stratum": 1,
            "reach_percent": 75, "std_dev": 1e-4, "authenticated": True}]
SERVERSTATS = {"ntp_packets_received": 1234, "ntp_packets_dropped": 2, "nts_ke_connections_accepted": 5}
GPS = {"enabled": True, "running": True, "mode": 3, "satellites_used": 9, "satellites_seen": 14, "hdop": 0.8,
       "snr_avg": 38.5}
PTP = {"enabled": True, "running": True, "offset_ns": 12, "meanPathDelay": 800, "stepsRemoved": 1}
SERVICES = {"chronyd": {"state": "running", "restarts": 0}, "gpsd": {"state": "running", "restarts": 1}}
REPORT = {"pps": [{"dev": "/dev/pps0", "state": "live"}], "matrix": [{"key": "gps_pps", "status": "ok"}]}


def full_metrics() -> str:
    tmp = tempfile.mkdtemp()
    saved = settings.DATA_DIR
    settings.DATA_DIR = tmp
    try:
        check = updatecheck.Checker(server.VERSION, lambda: True,
                                    fetcher=lambda: json.dumps({"tag_name": "v99.0.0", "name": "x"}).encode(),
                                    state=updatecheck.Store(), rng=random.Random(1))
        check.check(time.time())
        patches = [
            mock.patch.object(server.chrony, "tracking", return_value=TRACKING),
            mock.patch.object(server.chrony, "detailed_sources", return_value=SOURCES),
            mock.patch.object(server.chrony, "serverstats", return_value=SERVERSTATS),
            mock.patch.object(server.chrony, "clients", return_value=[{"address": "192.168.1.5"}] * 3),
            mock.patch.object(server.chrony, "nts_server_status", return_value={"enabled": True, "days_left": 40}),
            mock.patch.object(server.gps, "status", return_value=GPS),
            mock.patch.object(server.ptp, "status", return_value=PTP),
            mock.patch.object(server, "services_status", return_value=SERVICES),
            mock.patch.object(server.thermal.MONITOR, "last", {"t": time.time(), "celsius": 41.0}),
            mock.patch.object(server.leap, "file_path", return_value=str(FIXTURES / "leap-seconds.list")),
            # Die Liste aus dem Fixture, nicht die tzdata-Datei des Hosts (fehlt in schlanken Images)
            mock.patch.object(server.leap, "chrony_source",
                              return_value=("list", str(FIXTURES / "leap-seconds.list"))),
            mock.patch.object(server.hardware, "_REPORT", REPORT, create=True),
            mock.patch.object(updatecheck, "CHECKER", check),
        ]
        if hasattr(server.hardware, "cached_report"):
            patches.append(mock.patch.object(server.hardware, "cached_report", return_value=REPORT))
        for p in patches:
            p.start()
        try:
            return server.build_metrics()
        finally:
            for p in reversed(patches):
                p.stop()
    finally:
        store.close_all()
        settings.DATA_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)


def dashboard_exprs() -> list[str]:
    data = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    out = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("expr", "definition") and isinstance(value, str):
                    out.append(value)
                elif key == "query" and isinstance(value, (str, dict)):
                    out.append(value if isinstance(value, str) else str(value.get("query", "")))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


def alert_exprs() -> list[str]:
    """expr-Zeilen ohne YAML-Bibliothek (PyYAML ist keine Abhängigkeit)."""
    return [m.group(1) for m in re.finditer(r"^\s+expr:\s*(.+)$", ALERTS.read_text(encoding="utf-8"), re.M)]


class MetricsCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = full_metrics()
        cls.exposed = set(re.findall(r"^# TYPE (ntpgui_[a-z0-9_]+) ", cls.text, re.M))
        cls.helped = set(re.findall(r"^# HELP (ntpgui_[a-z0-9_]+) \S", cls.text, re.M))

    def test_fake_enables_everything(self):
        for name in ("ntpgui_gps_fix_mode", "ntpgui_ptp_offset_seconds", "ntpgui_nts_server_cert_days_left",
                     "ntpgui_temperature_celsius", "ntpgui_leapseconds_list_days_left", "ntpgui_update_available",
                     "ntpgui_pps_live", "ntpgui_service_up", "ntpgui_max_error_seconds", "ntpgui_sources_usable"):
            self.assertIn(name, self.exposed)

    def test_every_metric_has_help(self):
        self.assertEqual(self.exposed - self.helped, set())

    def test_dashboard_metrics_exist(self):
        used = {name for expr in dashboard_exprs() for name in METRIC_RE.findall(expr)}
        self.assertGreater(len(used), 15)
        self.assertEqual(sorted(used - self.exposed), [], "Dashboard nutzt Metriken, die /metrics nicht kennt")

    def test_alert_metrics_exist(self):
        exprs = alert_exprs()
        self.assertGreaterEqual(len(exprs), 8)
        used = {name for expr in exprs for name in METRIC_RE.findall(expr)}
        self.assertEqual(sorted(used - self.exposed), [], "Alarmregeln nutzen Metriken, die /metrics nicht kennt")
        for needed in ("ntpgui_synchronised", "ntpgui_system_time_offset_seconds", "ntpgui_sources_usable",
                       "ntpgui_gps_fix_mode", "ntpgui_nts_server_cert_days_left", "ntpgui_leapseconds_list_days_left"):
            self.assertIn(needed, used)

    def test_max_error_value(self):
        line = next(l for l in self.text.splitlines() if l.startswith("ntpgui_max_error_seconds "))
        value = float(line.split()[1])
        self.assertAlmostEqual(value, 2e-7 + 2e-5 + 0.5e-6, places=12)
        self.assertIn("ntpgui_sources 2", self.text)
        self.assertIn("ntpgui_sources_usable 1", self.text)
        self.assertRegex(self.text, r'ntpgui_info\{version="[^"]+"\} 1')


class DashboardShapeTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    def test_variables(self):
        names = {v["name"]: v for v in self.data["templating"]["list"]}
        self.assertEqual(names["datasource"]["type"], "datasource")
        self.assertEqual(names["datasource"]["query"], "prometheus")
        self.assertEqual(names["instance"]["type"], "query")

    def test_every_query_filters_instance_and_uses_variable_datasource(self):
        for panel in self.data["panels"]:
            if panel["type"] == "row":
                continue
            with self.subTest(panel=panel["title"]):
                self.assertEqual(panel["datasource"]["uid"], "${datasource}")
                self.assertTrue(panel.get("description"))
                for target in panel["targets"]:
                    self.assertIn('instance=~"$instance"', target["expr"])

    def test_ids_unique_and_titles_german(self):
        ids = [p["id"] for p in self.data["panels"]]
        self.assertEqual(len(ids), len(set(ids)))
        titles = {p["title"] for p in self.data["panels"]}
        for title in ("Offset", "Max. Fehler", "Frequenz", "Stratum", "Quellen", "GPS-Satelliten", "Temperatur"):
            self.assertIn(title, titles)


class AlertsShapeTest(unittest.TestCase):
    def test_yaml_if_available(self):
        try:
            import yaml  # nur wenn installiert – keine Abhängigkeit
        except ImportError:
            self.skipTest("PyYAML nicht installiert")
        data = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
        rules = data["groups"][0]["rules"]
        for rule in rules:
            with self.subTest(alert=rule.get("alert")):
                self.assertTrue(rule["alert"].startswith("NtpGui"))
                self.assertIn(rule["labels"]["severity"], {"info", "warning", "critical"})
                self.assertTrue(rule["annotations"]["summary"])
        self.assertEqual(len(rules), len(alert_exprs()))


class DocsTest(unittest.TestCase):
    def test_integration_docs_use_existing_endpoints(self):
        docs = ROOT / "docs" / "integrationen"
        for name in ("home-assistant.md", "homepage-glance.md", "uptime-kuma.md", "grafana-prometheus.md"):
            with self.subTest(doc=name):
                text = (docs / name).read_text(encoding="utf-8")
                for path in re.findall(r"/api/v1/[a-z/]+", text):
                    self.assertTrue(server.apiv1.resolve(path) or path == "/api/v1/time", path)


if __name__ == "__main__":
    unittest.main()
