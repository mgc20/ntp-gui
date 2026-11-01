"""Diagnosepaket (app/diagnostics.py): Inhalt, Filter, Schlussprüfung, Grenzen, Log-Seite."""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import diagnostics  # noqa: E402
import egress  # noqa: E402

CHRONY_CONF = """# erzeugt von ntp-gui
server ptbtime1.ptb.de iburst nts
server zeit.mueller-family.de iburst
server 192.168.178.1 iburst
allow 192.168.0.0/16
ntsserverkey /etc/letsencrypt/live/zeit.mueller-family.de/privkey.pem
refclock SHM 0 refid GPS offset 0.0 delay 0.2
"""

LOG = "\n".join([
    "[main] starte: /usr/sbin/chronyd -d -r -f /etc/chrony/chrony.conf",
    "2026-11-01T10:00:00Z chronyd version 4.3 starting",
    "2026-11-01T10:00:05Z Selected source 192.53.103.108 (ptbtime1.ptb.de)",
    "[gps] WARNUNG: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0 fehlt – gpsd wartet",
    "[main] Dienst 'gpsd' (PID 42) wurde unerwartet beendet (Exit 1) – Neustart in 5 s; NTP läuft weiter.",
    "[web] Position 48.1371543, 11.5761249 (sollte nie im Log stehen)",
    "[web] Client 192.168.178.23 fragt an",
    "[config] FEHLER: Konfiguration konnte nicht erzeugt werden",
]) + "\n"


def fake_collectors():
    return {
        "meta": lambda cfg, o: {"programm": "ntp-gui", "version": "1.3.0", "utc_offset": "+01:00",
                                "timezone": "Europe/Berlin"},
        "config": lambda cfg, o: {"chrony.conf": CHRONY_CONF, "ptp4l.conf": "# nicht lesbar"},
        "chrony": lambda cfg, o: {"tracking": "Reference ID    : C035676C (ptbtime1.ptb.de)\nStratum : 2",
                                  "sources": "^* 192.53.103.108  1 6 377 34 -12us[-13us] +/- 11ms",
                                  "clients_count": 3},
        "clients": lambda cfg, o: [{"address": "192.168.178.23", "ntp_packets": 12},
                                   {"address": "2a02:8070:aa:bb::5", "ntp_packets": 3}],
        "gps": lambda cfg, o: {"status": {"mode": 3, "lat": 48.1371543, "lon": 11.5761249, "hdop": 0.9,
                                          "satellites": [{"prn": 5, "elevation": 40, "azimuth": 100, "snr": 40,
                                                          "used": True}]}},
        "ptp": lambda cfg, o: {"status": {"enabled": False}, "log": "ptp4l[1.0]: selected local clock "
                                                                   "001b21.fffe.aabbcc as best master"},
        "hardware": lambda cfg, o: {"platform": {"dmi": {"product_name": "NUC", "product_serial": "G6BY12345"}}},
        "services": lambda cfg, o: {"services": {"chronyd": {"state": "running"}}},
        "events": lambda cfg, o: [{"id": 1, "t": 1, "kind": "gps", "level": "warn", "title": "GPS-Fix verloren",
                                   "data": {"lat": 48.1371543}, "source": "web"}],
        "logs": diagnostics._collect_logs,
        "settings": lambda cfg, o: {"values": {"web_title": "Zeit bei Müllers", "nts_server_name":
                                               "zeit.mueller-family.de"},
                                    "herkunft": {"default": ["web_title"]}},
        "history": lambda cfg, o: diagnostics.summarize_history([]),
        "recording": lambda cfg, o: json.dumps({"t": 1, "kind": "gpsd", "line": json.dumps(
            {"class": "TPV", "mode": 3, "lat": 48.1371543, "lon": 11.5761249})}) + "\n",
    }


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "ntp-gui.log").write_text(LOG, encoding="utf-8")
        patches = [mock.patch.object(diagnostics, "RUN_DIR", str(self.tmp)),
                   mock.patch.dict(diagnostics.COLLECTORS, fake_collectors())]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.cfg = {"nts_server_name": "zeit.mueller-family.de", "web_title": "Zeit bei Müllers"}

    def test_preview_is_clean_and_complete(self):
        result = diagnostics.preview(self.cfg, {"include_clients": True, "include_recording": True})
        self.assertTrue(result["ok"])
        names = [s["name"] for s in result["sections"]]
        self.assertEqual(names, ["meta", "config", "chrony", "clients", "gps", "ptp", "hardware", "services",
                                 "events", "logs", "settings", "history", "recording"])
        text = json.dumps(result["content"], ensure_ascii=False)
        for secret in ("48.137", "11.576", "mueller", "Müllers", "192.168.178.1 ", "192.168.178.23",
                       "192.53.103.108", "A50285BI", "G6BY12345", "aabbcc", "Europe/Berlin", "2a02:8070",
                       "C035676C"):
            self.assertNotIn(secret, text, secret)
        self.assertEqual(egress.check_no_leaks(result["content"]), [])
        # Nützliches bleibt
        self.assertIn("ptbtime1.ptb.de", text)
        self.assertIn("allow 192.168.0.0/16", result["content"]["config"]["chrony.conf"])
        self.assertEqual(result["content"]["gps"]["status"]["hdop"], 0.9)
        self.assertEqual(result["content"]["clients"][0]["address"], "client-02")  # client-01 = Router aus der Konfiguration
        removed = result["removed"]
        self.assertIn("position", removed["removed"])
        self.assertIn("position", removed["labels"])
        self.assertGreater(removed["pseudonyms"], 0)
        for section in result["sections"]:
            self.assertGreater(section["size"], 0)
            self.assertIn("title", section)

    def test_clients_only_on_request(self):
        result = diagnostics.preview(self.cfg, {})
        names = [s["name"] for s in result["sections"]]
        self.assertNotIn("clients", names)
        self.assertNotIn("recording", names)
        self.assertEqual(result["content"]["chrony"]["clients_count"], 3)

    def test_bundle_matches_preview(self):
        options = {"include_recording": True}
        data = diagnostics.bundle(self.cfg, options)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = {Path(m.name).name: tar.extractfile(m).read().decode("utf-8") for m in tar.getmembers()}
            prefixes = {Path(m.name).parent.name for m in tar.getmembers()}
        self.assertEqual(len(prefixes), 1)
        self.assertTrue(next(iter(prefixes)).startswith("ntp-gui-diagnose-"))
        self.assertIn("MANIFEST.txt", members)
        self.assertIn("config.txt", members)
        self.assertIn("logs.txt", members)
        self.assertIn("recording.jsonl", members)
        self.assertIn("gps.json", members)
        json.loads(members["gps.json"])
        manifest = members["MANIFEST.txt"]
        self.assertIn("nirgendwohin hochgeladen", manifest)
        self.assertIn("position", manifest)
        self.assertIn(egress.CATEGORIES["position"], manifest)
        for name, text in members.items():
            with self.subTest(name=name):
                self.assertEqual(egress.check_no_leaks(text), [])
                self.assertNotIn("48.137", text)
        preview = diagnostics.preview(self.cfg, options)
        for section in preview["sections"]:
            filename, text = diagnostics._render(section["name"], preview["content"][section["name"]])
            self.assertEqual(filename, section["file"])
            self.assertEqual(members[filename], text)

    def test_leak_aborts_export(self):
        finding = [{"kind": "position", "path": "gps.lat", "text": "lat=1"}]
        with mock.patch.object(egress, "check_no_leaks", return_value=finding):
            with self.assertRaises(diagnostics.LeakError) as ctx:
                diagnostics.bundle(self.cfg, {})
            with self.assertRaises(diagnostics.LeakError):
                diagnostics.preview(self.cfg, {})
        self.assertEqual(ctx.exception.findings, finding)
        self.assertIn("nichts exportiert", str(ctx.exception))

    def test_slow_collector_does_not_block(self):
        def slow(cfg, options):
            time.sleep(5)
            return {}
        with mock.patch.dict(diagnostics.COLLECTORS, {"hardware": slow}), \
                mock.patch.object(diagnostics, "DEADLINE", 0.3):
            start = time.monotonic()
            content = diagnostics.build(self.cfg)
            self.assertLess(time.monotonic() - start, 2.0)
        self.assertIn("Zeitüberschreitung", content["hardware"]["fehler"])

    def test_failing_collector_is_reported(self):
        def broken(cfg, options):
            raise RuntimeError("chronyd antwortet nicht")
        with mock.patch.dict(diagnostics.COLLECTORS, {"chrony": broken}):
            content = diagnostics.build(self.cfg)
        self.assertIn("chronyd antwortet nicht", content["chrony"]["fehler"])

    def test_sections_are_capped(self):
        big = "\n".join(f"[chrony] Zeile {i} " + "x" * 100 for i in range(20000))
        with mock.patch.dict(diagnostics.COLLECTORS, {"logs": lambda cfg, o: big}):
            result = diagnostics.preview(self.cfg, {})
        logs = next(s for s in result["sections"] if s["name"] == "logs")
        self.assertTrue(logs["truncated"])
        self.assertLessEqual(logs["size"], diagnostics.SECTION_CAP + 100)
        self.assertIn("Zeile 19999", result["content"]["logs"])  # das Ende bleibt

    def test_real_collectors_do_not_crash(self):
        # Ohne chronyd/gpsd/ptp4l: jeder Abschnitt liefert etwas (notfalls eine Fehlermeldung).
        real = {name: func for name, func in diagnostics.COLLECTORS.items()}
        with mock.patch.dict(diagnostics.COLLECTORS, {
                "meta": diagnostics._collect_meta, "config": diagnostics._collect_config,
                "services": diagnostics._collect_services, "logs": diagnostics._collect_logs,
                "history": lambda cfg, o: diagnostics.summarize_history(o.get("history") or [])}):
            start = time.monotonic()
            content = diagnostics.build(self.cfg, ["meta", "config", "services", "logs", "history"],
                                        {"version": "1.3.0", "history": []})
            self.assertLess(time.monotonic() - start, 3.0)
        self.assertEqual(content["meta"]["version"], "1.3.0")
        self.assertRegex(content["meta"]["utc_offset"], r"^[+-]\d\d:\d\d$")
        self.assertNotIn("timezone", content["meta"])
        self.assertIn("fehler", content["services"])
        self.assertTrue(real)


class HelpersTest(unittest.TestCase):
    def test_options_from_query(self):
        self.assertEqual(diagnostics.options_from_query({"clients": "1", "recording": "0"}),
                         {"include_clients": True, "include_recording": False})
        opts = diagnostics.options_from_query({"sections": "meta,logs,unbekannt"})
        self.assertEqual(opts["sections"], ["meta", "logs"])

    def test_history_summary_has_no_raw_series(self):
        now = time.time()
        samples = [{"t": now - 100 + i, "offset": 1e-6 * i, "rms": 2e-6, "stratum": 2 if i < 5 else 1,
                    "sources": {"192.53.103.108": {"o": 1e-5, "s": "*"}},
                    "gps": {"used": 8, "hdop": 0.9}} for i in range(10)]
        samples.append({"t": now - 3 * 86400, "offset": 99.0})  # älter als 24 h
        summary = diagnostics.summarize_history(samples, since=now - 86400)
        self.assertEqual(summary["samples"], 10)
        self.assertEqual(summary["metrics"]["offset"]["n"], 10)
        self.assertEqual(summary["metrics"]["offset"]["max"], 9e-6)
        self.assertEqual(summary["stratum_changes"], 1)
        self.assertEqual(summary["sources"]["192.53.103.108"]["states"], {"*": 10})
        self.assertEqual(summary["gps"]["used"]["mean"], 8)
        self.assertEqual(diagnostics.summarize_history([]), {"samples": 0})


class LogsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        p = mock.patch.object(diagnostics, "RUN_DIR", str(self.tmp))
        p.start()
        self.addCleanup(p.stop)

    def test_missing_log(self):
        result = diagnostics.logs()
        self.assertFalse(result["available"])
        self.assertEqual(result["lines"], [])

    def test_levels_filter_and_rotation(self):
        (self.tmp / "ntp-gui.log.1").write_text("[main] alte Zeile\n", encoding="utf-8")
        (self.tmp / "ntp-gui.log").write_text(LOG, encoding="utf-8")
        result = diagnostics.logs(lines=500)
        self.assertTrue(result["available"])
        self.assertEqual(result["lines"][0]["text"], "[main] alte Zeile")
        def level(prefix):
            return next(line["level"] for line in result["lines"] if line["text"].startswith(prefix))
        self.assertEqual(level("[gps] WARNUNG"), "warn")
        self.assertEqual(level("[config] FEHLER"), "crit")
        self.assertEqual(level("[main] Dienst 'gpsd'"), "crit")
        self.assertEqual(level("2026-11-01T10:00:00Z chronyd"), "info")
        self.assertEqual(result["lines"][1]["source"], "main")
        problems = diagnostics.logs(level="warn")
        self.assertEqual({line["level"] for line in problems["lines"]}, {"warn", "crit"})
        found = diagnostics.logs(q="GPSD")
        self.assertTrue(found["lines"])
        self.assertTrue(all("gpsd" in line["text"].lower() for line in found["lines"]))
        self.assertEqual(len(diagnostics.logs(lines=2)["lines"]), 2)
        self.assertEqual(len(diagnostics.logs(lines="kaputt")["lines"]), 9)


if __name__ == "__main__":
    unittest.main()
