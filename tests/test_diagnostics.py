"""Diagnosepaket (app/diagnostics.py): Inhalt, Filter, Schlussprüfung, Grenzen, Log-Seite."""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import fake_hostnames  # noqa: E402

import diagnostics  # noqa: E402
import egress  # noqa: E402

CHRONY_CONF = """# erzeugt von ntp-gui
server ptbtime1.ptb.de iburst nts
server zeit.mueller-family.de iburst
server 192.168.1.1 iburst
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
    "[web] Client 192.168.1.23 fragt an",
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
        "clients": lambda cfg, o: [{"address": "192.168.1.23", "ntp_packets": 12},
                                   {"address": "2606:4700:aa:bb::5", "ntp_packets": 3}],
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
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners
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
        self.assertEqual(names, ["meta", "hints", "config", "chrony", "clients", "gps", "ptp", "hardware", "services",
                                 "events", "logs", "settings", "history", "recording"])
        text = json.dumps(result["content"], ensure_ascii=False)
        for secret in ("48.137", "11.576", "mueller", "Müllers", "192.168.1.1 ", "192.168.1.23",
                       "192.53.103.108", "A50285BI", "G6BY12345", "aabbcc", "Europe/Berlin", "2606:4700",
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

    def test_hints_section_pseudonymises_addresses(self):
        hints = [{"level": "warn", "key": "web_plain_http", "action": "settings",
                  "title": "Dashboard über unverschlüsseltes HTTP mit Anmeldung",
                  "text": "Ungeschützt angekommen: Anmeldung von 192.168.1.40 direkt per HTTP, zuletzt vor "
                          "2 min; Anmeldung von 8.8.4.4 über 10.0.0.2 ohne Proxy-Kopf. Standort 48.1371543, "
                          "11.5761249 bei zeit.mueller-family.de",
                  "data": {"lat": 48.1371543}},
                 {"level": "info", "key": "gps_calibrating", "title": "GPS wird eingemessen", "text": "Noch 3 h."},
                 "kein dict"]
        self.addCleanup(diagnostics.set_hints_source, diagnostics._hints_source)
        diagnostics.set_hints_source(lambda: hints)
        with mock.patch.dict(diagnostics.COLLECTORS, {"hints": diagnostics._collect_hints}):
            result = diagnostics.preview(self.cfg, {})
            data = diagnostics.bundle(self.cfg, {})
        section = result["content"]["hints"]
        self.assertEqual(section["anzahl"], 2)
        self.assertEqual([h["key"] for h in section["hinweise"]], ["web_plain_http", "gps_calibrating"])
        self.assertEqual(set(section["hinweise"][0]), {"key", "level", "title", "text"})
        text = section["hinweise"][0]["text"]
        for secret in ("192.168.1.40", "8.8.4.4", "10.0.0.2", "48.137", "11.576", "mueller"):
            self.assertNotIn(secret, text, secret)
        self.assertRegex(text, r"von client-\d+ direkt per HTTP")
        self.assertIn("<öffentliche-IP>", text)
        self.assertEqual(egress.check_no_leaks(result["content"]), [])
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = {Path(m.name).name: tar.extractfile(m).read().decode("utf-8") for m in tar.getmembers()}
        self.assertIn("hints.json", members)
        self.assertIn("web_plain_http", members["hints.json"])
        self.assertNotIn("8.8.4.4", members["hints.json"])
        self.assertIn("hints.json", members["MANIFEST.txt"])

    def test_hints_without_dashboard(self):
        self.addCleanup(diagnostics.set_hints_source, diagnostics._hints_source)
        diagnostics.set_hints_source(None)
        self.assertIn("hinweis", diagnostics._collect_hints({}, {}))

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
        hang = threading.Event()
        self.addCleanup(hang.set)

        def slow(cfg, options):
            hang.wait(30)  # hängt weit länger als die Schranke unten
            return {}
        with mock.patch.dict(diagnostics.COLLECTORS, {"hardware": slow}), \
                mock.patch.object(diagnostics, "DEADLINE", 0.3):
            start = time.monotonic()
            content = diagnostics.build(self.cfg)
            self.assertLess(time.monotonic() - start, 5.0)
        self.assertIn("Zeitüberschreitung", content["hardware"]["fehler"])
        self.assertIn("nach 0,3 s", content["hardware"]["fehler"])  # deutsches Zahlformat (Nutzer liest das Paket)

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
            # build() endet nach DEADLINE; die Reserve gilt einem vollen Runner.
            self.assertLess(time.monotonic() - start, diagnostics.DEADLINE + 2.5)
        self.assertEqual(content["meta"]["version"], "1.3.0")
        self.assertRegex(content["meta"]["utc_offset"], r"^[+-]\d\d:\d\d$")
        self.assertNotIn("timezone", content["meta"])
        self.assertIn("fehler", content["services"])
        self.assertTrue(real)


class ChronySectionTest(unittest.TestCase):
    def setUp(self):
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners

    def test_tables_use_csv_mode(self):
        """Klartext-Tabellen kürzen lange Namen mit ">" – gekürzte IPv6 wären nicht sicher erkennbar."""
        for name in ("sources", "sourcestats", "selectdata", "authdata"):
            self.assertIn("-c", diagnostics.CHRONY_ARGS[name], name)

    def test_chrony_section_rounded_and_labelled(self):
        outputs = {
            "tracking": "Reference ID    : C035676C (ptbtime1.ptb.de)\nRoot delay      : 0.012345678 seconds",
            "sources": "^,*,2a00:1450:c17:5c1b:1234:5678:9abc:def0,1,6,377,34,-0.00001,-0.00001,0.0234567",
            "ntpdata": "Remote address  : 192.53.103.108 (C035676C)\nPeer delay      : 0.023456789 seconds",
        }

        def fake(args, timeout=2.0):
            for name, cmd in diagnostics.CHRONY_COMMANDS:
                if tuple(args) == cmd:
                    return outputs.get(name, "")
            return ""
        with mock.patch.object(diagnostics, "_chronyc", side_effect=fake), \
                mock.patch("chrony.clients", return_value=[]), \
                mock.patch("chrony.detailed_sources", return_value=[]):
            raw = diagnostics._collect_chrony({}, {})
        with mock.patch.dict(diagnostics.COLLECTORS, {"chrony": lambda cfg, o: raw}):
            content = diagnostics.build({}, ["chrony"])
        chrony = content["chrony"]
        self.assertIn("# Spalten:", chrony["sources"])
        self.assertTrue(chrony["sources"].splitlines()[1].endswith(",0.02"))
        self.assertNotIn("2a01", chrony["sources"])
        self.assertIn("Root delay      : 0.01 seconds", chrony["tracking"])
        self.assertIn("Peer delay      : 0.02 seconds", chrony["ntpdata"])


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



# Typische chronyc-Ausgaben (chrony 4.3/4.5), wie sie providers._record in die Aufzeichnung schreibt.
NTPDATA = ("\nRemote address  : 203.0.113.9 (CB007109)\nRemote port     : 123\nLeap status     : Normal\n"
           "Stratum         : 1\nPoll interval   : 7 (128 seconds)\nPrecision       : -25 (0.000000030 seconds)\n"
           "Root delay      : 0.000015259 seconds\nRoot dispersion : 0.000015259 seconds\n"
           "Offset          : -0.000699052 seconds\nPeer delay      : 0.023456789 seconds\n"
           "Peer dispersion : 0.000000055 seconds\nResponse time   : 0.000037578 seconds\n")
RECORDING = "".join(json.dumps(entry, separators=(",", ":")) + "\n" for entry in (
    {"t": 1.0, "kind": "chronyc", "args": ["ntpdata"], "out": NTPDATA},
    {"t": 1.1, "kind": "chronyc", "args": ["-c", "tracking"],
     "out": "CB007109,203.0.113.9,2,1793567527.899899431,-0.000001608,-0.000000035,0.000000145,"
            "-0.001,-0.000,0.001,0.023456789,0.000009993,12.1,Normal\n"},
    {"t": 1.2, "kind": "chronyc", "args": ["-c", "sources"],
     "out": "^,*,203.0.113.9,1,7,377,107,0.000345460,0.000699052,0.012345678\n"},
    {"t": 1.3, "kind": "chronyc", "args": ["tracking"],
     "out": "Reference ID    : CB007109 (203.0.113.9)\nStratum         : 2\n"
            "System time     : 0.000000044 seconds slow of NTP time\nRoot delay      : 0.023456789 seconds\n"
            "Root dispersion : 0.000459329 seconds\nUpdate interval : 2.1 seconds\n"},
))


class RecordingExportTest(unittest.TestCase):
    """Fehlerbericht 1.3.0: Export mit Aufzeichnung brach mit „latenz_gerundet“ ab."""

    def setUp(self):
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        collectors = fake_collectors()
        collectors["recording"] = lambda cfg, o: RECORDING
        for p in (mock.patch.object(diagnostics, "RUN_DIR", str(self.tmp)),
                  mock.patch.dict(diagnostics.COLLECTORS, collectors)):
            p.start()
            self.addCleanup(p.stop)

    def test_recording_with_chronyc_text_exports(self):
        content = diagnostics.build({}, ["recording"], {"include_recording": True})
        entries = [json.loads(line) for line in content["recording"].splitlines() if line.startswith("{")]
        self.assertEqual(len(entries), 4)
        ntpdata = entries[0]["out"]
        self.assertIn("Peer delay      : 0.02 seconds", ntpdata)
        self.assertIn("Root delay      : 0.00 seconds", ntpdata)
        # Werte ohne Laufzeit-Bedeutung bleiben genau (Analyse braucht sie).
        self.assertIn("Precision       : -25 (0.000000030 seconds)", ntpdata)
        self.assertIn("Offset          : -0.000699052 seconds", ntpdata)
        self.assertNotIn("203.0.113.9", content["recording"])
        self.assertTrue(entries[2]["out"].rstrip().endswith(",0.01"))
        self.assertIn("Root delay      : 0.02 seconds", entries[3]["out"])

    def test_check_reads_json_lines_like_the_filter(self):
        # Ungefiltert muss die Prüfung die genaue Laufzeit weiterhin finden – je Eintrag, nicht je Rohzeile.
        findings = egress.check_no_leaks({"recording": RECORDING})
        self.assertTrue(any(f["kind"] == "latenz_gerundet" for f in findings), findings)
        self.assertTrue(all("Zeile" in f["path"] for f in findings), findings)

    def test_hashed_ipv6_refid_removed(self):
        # chrony: Bei IPv6 ist die RefID ein Hash der Adresse (oft im Bereich 224–255.x.x.x).
        text = egress.Sanitizer("diagnostics").text("Local address   : 2001:db8::1 (E41BC59B)")
        self.assertNotIn("E41BC59B", text)
        self.assertIn("(GPS)", egress.Sanitizer("diagnostics").text("Reference ID    : 47505300 (GPS)"))

    def test_timezone_filler_word_kept(self):
        line = "2026-11-01T21:05:35Z Using right/UTC timezone to obtain leap second data"
        self.assertEqual(egress.Sanitizer("diagnostics").text(line), line)
        self.assertEqual(egress.Sanitizer("diagnostics").text("timezone=Vienna"), "timezone=<zeitzone>")


class WorkerTest(unittest.TestCase):
    """Server-Pfad: Filter im eigenen Prozess, Download nach der Vorschau ohne zweiten Lauf."""

    def setUp(self):
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "ntp-gui.log").write_text(LOG, encoding="utf-8")
        collectors = fake_collectors()
        collectors["recording"] = lambda cfg, o: RECORDING
        for p in (mock.patch.object(diagnostics, "RUN_DIR", str(self.tmp)),
                  mock.patch.dict(diagnostics.COLLECTORS, collectors),
                  mock.patch.dict(diagnostics._last, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.cfg = {"nts_server_name": "zeit.mueller-family.de", "web_title": "Zeit bei Müllers"}
        self.options = {"include_clients": True, "include_recording": True}

    def test_worker_matches_in_process(self):
        direct = diagnostics.preview(self.cfg, dict(self.options))
        worker = diagnostics.preview_locked(self.cfg, dict(self.options))
        self.assertEqual(worker["content"], direct["content"])
        self.assertEqual(worker["removed"], direct["removed"])

    def test_download_reuses_preview(self):
        view = diagnostics.preview_locked(self.cfg, dict(self.options, uptime_seconds=1))
        time.sleep(1.1)  # der Dateiname muss vom Paket kommen, nicht vom Zeitpunkt des Downloads
        with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
            body, filename = diagnostics.bundle_locked(self.cfg, dict(self.options, uptime_seconds=99),
                                                       reuse=view["reuse"])
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
            names = {Path(m.name).name for m in tar.getmembers()}
            folders = {m.name.split("/", 1)[0] for m in tar.getmembers()}
            recording = next(m for m in tar.getmembers() if m.name.endswith("recording.jsonl"))
            data = tar.extractfile(recording).read().decode("utf-8")
        self.assertIn("recording.jsonl", names)
        self.assertEqual(data, view["content"]["recording"].rstrip("\n") + "\n")
        self.assertEqual(filename, view["filename"])
        self.assertEqual(folders, {filename[:-len(".tar.gz")]})

    def test_download_without_token_rebuilds_wrong_token_is_stale(self):
        view = diagnostics.preview_locked(self.cfg, dict(self.options))
        for reuse in (None, ""):
            with mock.patch.object(diagnostics, "_run_worker", wraps=diagnostics._run_worker) as run:
                diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=reuse)
            self.assertEqual(run.call_count, 1, reuse)
        self.assertNotEqual(diagnostics._last["token"], view["reuse"])  # jeder Lauf ein neuer Merker
        # Ein Merker, der nicht (mehr) gilt: kein langer Bau in derselben Anfrage, sondern 409.
        with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
            for reuse in ("falsch", view["reuse"]):
                with self.assertRaises(diagnostics.StaleError, msg=reuse):
                    diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=reuse)

    def test_token_expires_and_settings_change_is_stale(self):
        view = diagnostics.preview_locked(self.cfg, dict(self.options))
        with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
            with self.assertRaises(diagnostics.StaleError):  # neuer Filterbegriff in den Einstellungen
                diagnostics.bundle_locked(dict(self.cfg, web_title="Neu"), dict(self.options), reuse=view["reuse"])
            with mock.patch.object(diagnostics, "REUSE_SECONDS", 0.0), self.assertRaises(diagnostics.StaleError):
                diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])
            body, _ = diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])
        self.assertTrue(body)

    def test_worker_timeout_message_uses_german_number_format(self):
        import subprocess
        with mock.patch.object(diagnostics, "WORKER_TIMEOUT", 2.5), \
                mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("python3", 2.5)), \
                mock.patch("sys.stderr"):
            with self.assertRaises(RuntimeError) as caught:
                diagnostics._run_worker({})
        self.assertEqual(str(caught.exception), "Das Diagnosepaket wurde nach 2,5 s nicht fertig.")

    def test_failed_preview_leaves_nothing_to_reuse(self):
        view = diagnostics.preview_locked(self.cfg, dict(self.options))
        with mock.patch.object(diagnostics, "_run_worker", side_effect=RuntimeError("Zeitüberschreitung")):
            with self.assertRaises(RuntimeError):
                diagnostics.preview_locked(self.cfg, dict(self.options))
        self.assertEqual(diagnostics._last, {})
        with self.assertRaises(diagnostics.StaleError):
            diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])

    def test_new_recording_rebuilds(self):
        import providers
        rec = self.tmp / "recording-1.jsonl"
        rec.write_text('{"t":1}\n', encoding="utf-8")
        status = {"active": False, "path": str(rec)}
        with mock.patch.object(providers, "status", lambda: dict(status)):
            view = diagnostics.preview_locked(self.cfg, dict(self.options))
            with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
                diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])  # unverändert
            newer = self.tmp / "recording-2.jsonl"  # neue Aufzeichnung seit der Vorschau
            newer.write_text('{"t":2}\n', encoding="utf-8")
            status["path"] = str(newer)
            with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
                diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])  # was geprüft wurde
            with mock.patch.object(diagnostics, "_run_worker", wraps=diagnostics._run_worker) as run:
                diagnostics.bundle_locked(self.cfg, dict(self.options))  # ohne Merker: die neue Aufzeichnung
            self.assertEqual(run.call_count, 1)
            view = diagnostics.preview_locked(self.cfg, dict(self.options))
            with newer.open("a", encoding="utf-8") as handle:  # Aufzeichnung wächst weiter
                handle.write('{"t":3}\n')
            # Mit dem Merker der Vorschau: genau deren Paket, kein zweiter Bau (auf dem Pi Minuten) –
            # heruntergeladen wird, was geprüft wurde.
            with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
                body, _ = diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])
            self.assertEqual(body, diagnostics._last["bundle"])
            # Ohne Merker gilt die gewachsene Aufzeichnung: neu bauen.
            with mock.patch.object(diagnostics, "_run_worker", wraps=diagnostics._run_worker) as run:
                diagnostics.bundle_locked(self.cfg, dict(self.options))
            self.assertEqual(run.call_count, 1)

    def test_waiting_requests_share_one_build(self):
        # Mehrfach geklickt / Seite neu geladen: Wer wartet, bekommt das Ergebnis des laufenden Baus.
        import threading
        real = diagnostics._run_worker
        started = threading.Event()
        go = threading.Event()
        self.addCleanup(go.set)
        calls = []

        def slow(job):
            calls.append(1)
            started.set()
            go.wait(30)  # erst weiter, wenn alle anderen nachweislich warten (statt fester 0,5 s)
            return real(job)

        class CountingLock:
            """diagnostics._lock, zählt, wer schon davor steht (``arrived`` ist dann gesetzt)."""

            def __init__(self):
                self.lock, self.entered, self.cond = threading.Lock(), 0, threading.Condition()

            def __enter__(self):
                with self.cond:
                    self.entered += 1
                    self.cond.notify_all()
                self.lock.acquire()
                return self

            def __exit__(self, *exc):
                self.lock.release()

        lock = CountingLock()
        results = []
        with mock.patch.object(diagnostics, "_run_worker", side_effect=slow), \
                mock.patch.object(diagnostics, "_lock", lock):
            first = threading.Thread(target=lambda: results.append(
                diagnostics.preview_locked(self.cfg, dict(self.options))))
            first.start()
            self.assertTrue(started.wait(10))
            others = [threading.Thread(target=lambda: results.append(
                diagnostics.preview_locked(self.cfg, dict(self.options)))) for _ in range(3)]
            others.append(threading.Thread(target=lambda: results.append(
                diagnostics.bundle_locked(self.cfg, dict(self.options)))))
            for t in others:
                t.start()
            with lock.cond:
                self.assertTrue(lock.cond.wait_for(lambda: lock.entered == 5, timeout=10))
            go.set()
            for t in [first] + others:
                t.join(30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 5)
        self.assertEqual(len({r["reuse"] for r in results if isinstance(r, dict)}), 1)
        # Eine spätere Vorschau baut wieder neu (aktueller Stand).
        with mock.patch.object(diagnostics, "_run_worker", wraps=diagnostics._run_worker) as run:
            diagnostics.preview_locked(self.cfg, dict(self.options))
        self.assertEqual(run.call_count, 1)

    def test_other_options_are_stale(self):
        view = diagnostics.preview_locked(self.cfg, dict(self.options))
        with self.assertRaises(diagnostics.StaleError):  # nie ein Paket mit anderen Schaltern als angezeigt
            diagnostics.bundle_locked(self.cfg, dict(self.options, include_clients=False), reuse=view["reuse"])

    def test_killed_worker_names_the_signal(self):
        import subprocess
        killed = subprocess.CompletedProcess([], -9, stdout=b"", stderr=b"")
        with mock.patch("subprocess.run", return_value=killed), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            with self.assertRaises(RuntimeError) as ctx:
                diagnostics._run_worker({"names": [], "raw": {}, "known_names": [], "known_values": {}})
        self.assertIn("SIGKILL", str(ctx.exception))
        self.assertIn("Arbeitsspeicher", str(ctx.exception))
        self.assertIn("SIGKILL", err.getvalue())  # auch im Container-Log
        self.assertIn("Rückgabewert 3", diagnostics._worker_failed(3, b"Traceback\nMemoryError\n"))
        self.assertIn("MemoryError", diagnostics._worker_failed(3, b"Traceback\nMemoryError\n"))

    def test_check_caches_emptied_after_each_package(self):
        diagnostics.preview_locked(self.cfg, dict(self.options))
        with mock.patch.object(diagnostics, "_run_worker", side_effect=diagnostics._package):  # im selben Prozess
            diagnostics.preview_locked(self.cfg, dict(self.options, include_clients=False))
        self.assertEqual(len(egress._TEXT_MEMO), 0)
        self.assertEqual(len(egress._JSON_MEMO), 0)

    def test_worker_filters_and_reports_errors(self):
        job = {"names": ["logs"], "raw": {"logs": "Position lat=48.1371543 lon=11.5761249"},
               "known_names": [], "known_values": {}}
        result = diagnostics._run_worker(job)
        self.assertNotIn("48.137", result["preview"]["content"]["logs"])
        self.assertTrue(result["bundle"].startswith(b"\x1f\x8b"))  # gzip
        with self.assertRaises(RuntimeError):
            diagnostics._run_worker({"names": ["logs"]})  # kaputter Auftrag → Fehlermeldung, kein Absturz

    def test_fast_path_respects_known_values(self):
        # Eine rein numerische Seriennummer, ein Titel „2048“ oder ein Hostname „4711“ sehen aus wie
        # Zahlen – der Schnellweg darf sie nicht durchlassen.
        known = {"seriennummer": ["00012345678", "4711081500"], "titel": ["2048"], "name": ["52.520008"]}
        names = ["4711", "123456"]
        samples = ["00012345678", "4711081500", "+4711081500", "2048", "52.520008", "4711", "123456",
                   "-123456", "0", "48.1371543", "2026-11-01T22:51:12Z", "20481", "4711.5"]
        for value in samples:
            fast = egress.Sanitizer("diagnostics", names, known)
            slow = egress.Sanitizer("diagnostics", names, known)
            self.assertEqual(fast._plain(value), slow._plain_uncached(value), value)
            self.assertEqual(fast.report(), slow.report(), value)
        probe = egress.Sanitizer("diagnostics", names, known)
        self.assertEqual(probe.text("00012345678"), "<seriennr>")
        self.assertEqual(probe.text("2048"), "<titel>")
        self.assertEqual(probe.text("4711"), "<hostname-1>")
        self.assertEqual(probe.obj({"id": "4711081500", "n": 2048}), {"id": "<seriennr>", "n": 2048})

    def test_numeric_serial_exports_scrubbed(self):
        # Vorher (Schnellweg ohne bekannte Werte): LeakError statt gefiltertem Export.
        collectors = dict(diagnostics.COLLECTORS,
                          hardware=lambda cfg, o: {"usb": {"product": "u-blox GNSS", "id": "00012345678"}},
                          gps=lambda cfg, o: {"status": {"device": "123456"}})
        with mock.patch.dict(diagnostics.COLLECTORS, collectors), \
                mock.patch.object(diagnostics, "_known_values",
                                  lambda cfg: {"seriennummer": {"00012345678"}}), \
                mock.patch.object(diagnostics, "_known_names", lambda cfg: {"123456"}):
            content = diagnostics.build({}, ["hardware", "gps"])
        self.assertEqual(content["hardware"]["usb"]["id"], "<seriennr>")
        self.assertEqual(content["gps"]["status"]["device"], "<hostname-1>")

    def test_fast_path_never_skips_a_change(self):
        # Was der Schnellweg durchlässt, darf der volle Filter auch nicht ändern.
        probe = egress.Sanitizer("diagnostics")
        samples = ["0", "-12", "48.1371543", "11.5761249", "-0.000699052", "1793573550.754", "1e-05",
                   "12345678901", "12345678901.12345678901", "2026-11-01T22:51:12.000Z",
                   "2026-11-01T22:51:12Z", "4807.038", "0.023456789"]
        for value in samples:
            self.assertTrue(egress._PLAIN_SAFE_RE.fullmatch(value), value)
            self.assertEqual(probe._plain_uncached(value), value, value)
        for value in ("123456789012", "192.168.1.5", "48.137,11.576", "48.137 11.576", "2001:db8::1"):
            self.assertIsNone(egress._PLAIN_SAFE_RE.fullmatch(value), value)

    def test_check_parses_huge_json_lines(self):
        # check_no_leaks auf Text parst jede JSON-Zeile, auch ab 1 MB (der Filter behandelt solche
        # Zeilen als Text und lässt Schlüssel wie "serial" stehen – die Prüfung muss sie finden).
        pad = "x" * 1_000_100
        sats = json.dumps({"sky": [[5, 120.0, 33.0, 40], [7, 200.0, 45.0, 38]], "pad": pad})
        serial = json.dumps({"serial": "ABCD1234", "pad": pad})
        for _ in range(2):  # zweiter Lauf: kein Zwischenspeicher darf das ändern
            self.assertIn(("satellitenwinkel", "Zeile 2.sky"),
                          [(f["kind"], f["path"]) for f in egress.check_no_leaks("{}\n" + sats)])
            self.assertIn(("seriennummer", "Zeile 1.serial"),
                          [(f["kind"], f["path"]) for f in egress.check_no_leaks(serial)])
        self.assertNotIn(serial.strip(), egress._JSON_MEMO._data)  # lange Zeilen nicht gemerkt

    def test_check_memo_bounded(self):
        memo = egress.LineMemo(10_000)
        for i in range(1000):
            memo.put(f"Zeile {i:04d} " + "y" * 50, ("x",))
        self.assertLessEqual(memo.bytes, 10_000)
        self.assertLess(len(memo), 1000)
        memo.put("ä" * 20_000, ())  # zu lang: nie gemerkt
        self.assertIsNone(memo.get("ä" * 20_000))
        memo.clear()
        self.assertEqual((len(memo), memo.bytes), (0, 0))

    def test_backstop_memo_same_findings(self):
        known = {"names": ["zeit.mueller-family.de"], "tokens": ["A50285BI"]}
        text = "\n".join(["ok", "Position 48.1371543, 11.5761249", "Host zeit.mueller-family.de",
                          "Seriennummer A50285BI", "ok"] * 3).encode("utf-8")
        plain = egress.backstop({"a": text, "b": text}, known)
        memo = egress.BackstopMemo(known)
        self.assertTrue(plain)
        self.assertEqual(egress.backstop({"a": text, "b": text}, known, memo), plain)
        self.assertEqual(egress.backstop({"a": text, "b": text}, known, memo), plain)
        # Anderer Satz bekannter Werte: der Speicher gilt nicht und wird nicht benutzt.
        other = egress.backstop({"a": text}, {"names": [], "tokens": []}, memo)
        self.assertEqual(other, egress.backstop({"a": text}, {"names": [], "tokens": []}))
        self.assertFalse(any(f["kind"] in ("bekannter_name", "bekannter_wert") for f in other))

    def test_cache_keeps_counts(self):
        text = "\n".join(["Remote address  : 192.53.103.108 (C035676C)", "Leap status : Normal"] * 50)
        cached = egress.Sanitizer("diagnostics")
        out_cached = cached.text(text)
        with mock.patch.object(egress, "PLAIN_CACHE_SIZE", 0):
            plain = egress.Sanitizer("diagnostics")
            out_plain = plain.text(text)
        self.assertEqual(out_cached, out_plain)
        self.assertEqual(cached.report(), plain.report())
        self.assertEqual(cached.report()["removed"]["oeffentliche_ip"], 50)


class JobTest(unittest.TestCase):
    """Vorschau als Hintergrund-Auftrag: keine Anfrage bleibt minutenlang offen (Reverse Proxy)."""

    def setUp(self):
        WorkerTest.setUp(self)
        p = mock.patch.dict(diagnostics._jobs, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def _slow_worker(self, release):
        real = diagnostics._run_worker

        def slow(job):
            release.wait(10)
            return real(job)
        return mock.patch.object(diagnostics, "_run_worker", side_effect=slow)

    def test_pending_then_done_and_download_reuses(self):
        import threading
        release = threading.Event()
        with self._slow_worker(release):
            job = diagnostics.start_job(self.cfg, dict(self.options))
            state = diagnostics.job_result(job, wait=0.05)
            self.assertTrue(state["pending"])
            self.assertEqual(state["job"], job)
            self.assertIsInstance(state["seconds"], int)
            # gleiche Schalter, während der Bau läuft: derselbe Auftrag
            self.assertEqual(diagnostics.start_job(self.cfg, dict(self.options)), job)
            release.set()
            view = diagnostics.job_result(job, wait=10)
        self.assertTrue(view["ok"])
        self.assertIn("recording", view["content"])
        with mock.patch.object(diagnostics, "_run_worker", side_effect=AssertionError("neu gebaut")):
            body, filename = diagnostics.bundle_locked(self.cfg, dict(self.options), reuse=view["reuse"])
        self.assertTrue(body)
        self.assertEqual(filename, view["filename"])

    def test_other_switches_other_job(self):
        import threading
        release = threading.Event()
        with self._slow_worker(release):
            a = diagnostics.start_job(self.cfg, dict(self.options))
            b = diagnostics.start_job(self.cfg, dict(self.options, include_clients=False))
            self.assertNotEqual(a, b)
            release.set()
            self.assertTrue(diagnostics.job_result(a, wait=10)["ok"])
            self.assertTrue(diagnostics.job_result(b, wait=10)["ok"])

    def test_failure_reaches_the_page(self):
        with mock.patch.object(diagnostics, "_run_worker", side_effect=RuntimeError("Prozess weg")):
            job = diagnostics.start_job(self.cfg, dict(self.options))
            with self.assertRaisesRegex(RuntimeError, "Prozess weg"):
                diagnostics.job_result(job, wait=10)
        with mock.patch.object(diagnostics, "_run_worker", side_effect=diagnostics.LeakError([{"kind": "x"}])):
            job = diagnostics.start_job(self.cfg, dict(self.options))
            with self.assertRaises(diagnostics.LeakError):
                diagnostics.job_result(job, wait=10)

    def test_settings_change_starts_new_job(self):
        import threading
        release = threading.Event()
        with self._slow_worker(release):
            a = diagnostics.start_job(self.cfg, dict(self.options))
            b = diagnostics.start_job(dict(self.cfg, web_title="Neu"), dict(self.options))
            self.assertNotEqual(a, b)
            release.set()
            diagnostics.job_result(a, wait=10)
            diagnostics.job_result(b, wait=10)

    def test_at_most_two_pending_jobs(self):
        import threading
        release = threading.Event()
        with self._slow_worker(release):
            jobs = [diagnostics.start_job(self.cfg, dict(self.options, sections=[s]))
                    for s in ("chrony", "gps")]
            with self.assertRaises(diagnostics.BusyError):
                diagnostics.start_job(self.cfg, dict(self.options, sections=["logs"]))
            release.set()
            for job in jobs:
                diagnostics.job_result(job, wait=10)
        diagnostics.job_result(diagnostics.start_job(self.cfg, dict(self.options, sections=["logs"])), wait=10)

    def test_foreign_error_text_stays_in_log(self):
        with mock.patch.object(diagnostics, "_run_worker", side_effect=OSError("/geheim/pfad")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            job = diagnostics.start_job(self.cfg, dict(self.options))
            with self.assertRaises(RuntimeError) as ctx:
                diagnostics.job_result(job, wait=10)
        self.assertNotIn("/geheim", str(ctx.exception))
        self.assertIn("/geheim/pfad", err.getvalue())

    def test_sections_deduplicated(self):
        self.assertEqual(diagnostics.options_from_query({"sections": "chrony,chrony,gps,chrony"})["sections"],
                         ["chrony", "gps"])

    def test_unknown_job(self):
        self.assertIsNone(diagnostics.job_result("gibtsnicht"))

    def test_old_jobs_are_forgotten(self):
        names = list(diagnostics.SECTION_TITLES)
        for n in range(diagnostics.JOB_KEEP + 3):
            job = diagnostics.start_job(self.cfg, dict(self.options, sections=[names[n]]))
            diagnostics.job_result(job, wait=10)
        self.assertLessEqual(len(diagnostics._jobs), diagnostics.JOB_KEEP + 1)
        with mock.patch.object(diagnostics, "REUSE_SECONDS", 0.0):
            diagnostics.start_job(self.cfg, dict(self.options, sections=["meta"]))
        self.assertLessEqual(len(diagnostics._jobs), 1)  # erledigte nach Ablauf vergessen


class HistoryTempSummaryTest(unittest.TestCase):
    def test_temperature_and_hourly_profile(self):
        samples = [{"t": 1000 + i * 600, "freq": 1.0 + 0.01 * (i // 6), "temp": 40.0 + (i // 6)} for i in range(18)]
        out = diagnostics.summarize_history(samples)
        self.assertEqual(out["metrics"]["temp"]["min"], 40.0)
        self.assertEqual([row["h"] for row in out["temp_freq_hourly"]], [0, 1, 2])
        self.assertEqual(out["temp_freq_hourly"][2], {"h": 2, "n": 6, "temp": 42.0, "freq": 1.02})

    def test_without_temperature_no_profile(self):
        out = diagnostics.summarize_history([{"t": 1, "freq": 1.0}, {"t": 2, "freq": 1.1}])
        self.assertNotIn("temp_freq_hourly", out)
        self.assertNotIn("temp", out["metrics"])

if __name__ == "__main__":
    unittest.main()
