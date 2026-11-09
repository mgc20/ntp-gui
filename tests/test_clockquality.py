"""1.4 Uhrqualität: Temperatursensoren, Schaltsekunden-Liste, Vollbild-Uhr (/clock, /api/v1/time).

Läuft ohne chronyd und ohne echte Sensoren: sysfs wird als Ordnerbaum nachgebaut,
chronyc durch Attrappen ersetzt.
"""

import base64
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, fake_hostnames, stop_http_server  # noqa: E402

import history  # noqa: E402
import leap  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
import thermal  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEAP_REAL = FIXTURES / "leap-seconds.list"        # aus dem Image (debian:trixie, tzdata)
LEAP_EXPIRED = FIXTURES / "leap-seconds-expired.list"
NOW = 1793577600.0   # 2026-11-02 00:00 UTC


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeSys:
    """Nachgebautes /sys mit Thermalzonen, hwmon und DS18B20."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def zone(self, n, kind, millideg):
        write(self.root / "class/thermal" / f"thermal_zone{n}" / "type", kind + "\n")
        write(self.root / "class/thermal" / f"thermal_zone{n}" / "temp", f"{millideg}\n")

    def hwmon(self, n, name, temps, labels=None):
        base = self.root / "class/hwmon" / f"hwmon{n}"
        write(base / "name", name + "\n")
        for i, value in enumerate(temps, start=1):
            write(base / f"temp{i}_input", f"{value}\n")
            if labels:
                write(base / f"temp{i}_label", labels[i - 1] + "\n")

    def w1(self, serial, temperature=None, slave=None):
        base = self.root / "bus/w1/devices" / serial
        base.mkdir(parents=True, exist_ok=True)
        if temperature is not None:
            write(base / "temperature", f"{temperature}\n")
        if slave is not None:
            write(base / "w1_slave", slave)

    def cleanup(self):
        self.tmp.cleanup()


class ThermalParseTest(unittest.TestCase):
    def test_millidegrees(self):
        self.assertEqual(thermal.parse_millidegrees("48312\n"), 48.31)
        self.assertEqual(thermal.parse_millidegrees("-5000"), -5.0)
        for bad in ("", "abc", "200000", "-60000", None):
            self.assertIsNone(thermal.parse_millidegrees(bad), bad)

    def test_w1_slave(self):
        ok = "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n"
        self.assertEqual(thermal.parse_w1_slave(ok), 23.12)
        self.assertIsNone(thermal.parse_w1_slave(ok.replace("YES", "NO")), "Prüfsumme falsch → verwerfen")
        self.assertIsNone(thermal.parse_w1_slave(ok.replace("t=23125", "t=85000")), "85 °C = Einschaltwert")
        self.assertIsNone(thermal.parse_w1_slave(""))
        self.assertIsNone(thermal.parse_w1_value("-127000"))


class ThermalDiscoverTest(unittest.TestCase):
    def setUp(self):
        self.sys = FakeSys()
        self.addCleanup(self.sys.cleanup)

    def test_empty_system(self):
        self.assertEqual(thermal.discover(str(self.sys.root)), [])
        self.assertIsNone(thermal.choose([], "auto"))

    def test_pi_prefers_cpu_thermal(self):
        self.sys.zone(0, "cpu-thermal", 51234)
        self.sys.zone(1, "rp1_adc", 40000)
        self.sys.hwmon(0, "rp1_adc", [40000])
        self.sys.w1("28-0316a2794bff", temperature=21500)
        found = thermal.discover(str(self.sys.root))
        self.assertEqual([s["id"] for s in found],
                         ["thermal:cpu-thermal", "w1:28-0316a2794bff", "thermal:rp1_adc", "hwmon:rp1_adc:temp1"])
        self.assertEqual(found[0]["celsius"], 51.23)
        self.assertEqual(thermal.choose(found, "auto")["id"], "thermal:cpu-thermal")
        self.assertEqual(thermal.choose(found, "w1:28-0316a2794bff")["celsius"], 21.5)
        self.assertIsNone(thermal.choose(found, "off"))
        self.assertIsNone(thermal.choose(found, "w1:28-000000000000"), "fehlender Sensor → kein stiller Ersatz")

    def test_pc_hwmon_and_duplicates(self):
        self.sys.zone(0, "acpitz", 27800)
        self.sys.zone(1, "acpitz", 29800)
        self.sys.zone(2, "x86_pkg_temp", 45000)
        self.sys.hwmon(3, "nvme", [38850, 0], ["Composite", "Sensor 1"])
        self.sys.hwmon(4, "coretemp", [46000, 44000], ["Package id 0", "Core 0"])
        found = thermal.discover(str(self.sys.root))
        ids = [s["id"] for s in found]
        self.assertEqual(ids[0], "thermal:x86_pkg_temp")
        self.assertEqual(ids[1], "hwmon:coretemp:temp1")
        self.assertIn("thermal:acpitz", ids)
        self.assertIn("thermal:acpitz:2", ids, "zweite Zone gleichen Namens bekommt :2")
        coretemp = next(s for s in found if s["id"] == "hwmon:coretemp:temp1")
        self.assertEqual(coretemp["label"], "coretemp Package id 0")
        # Jede Kennung passt zur Prüfung der Einstellung.
        for sensor_id in ids:
            self.assertEqual(settings._as_temp_sensor(sensor_id), sensor_id)

    def test_k10temp_and_unreadable_zone(self):
        self.sys.zone(0, "broken", "")
        self.sys.hwmon(0, "k10temp", [55125])
        found = thermal.discover(str(self.sys.root))
        self.assertEqual([s["id"] for s in found], ["hwmon:k10temp:temp1"])

    def test_w1_slave_fallback_and_silent_sensor(self):
        self.sys.w1("28-0316a2794bff", slave="aa : crc=57 YES\naa t=19437\n")
        self.sys.w1("28-0416b1110aff")  # ohne Werte: falsch verkabelt, trotzdem gelistet
        found = thermal.discover(str(self.sys.root))
        by_id = {s["id"]: s for s in found}
        self.assertEqual(by_id["w1:28-0316a2794bff"]["celsius"], 19.44)
        self.assertTrue(by_id["w1:28-0316a2794bff"]["path"].endswith("w1_slave"))
        self.assertIsNone(by_id["w1:28-0416b1110aff"]["celsius"])
        self.assertEqual(thermal.choose(found, "auto")["id"], "w1:28-0316a2794bff", "auto nimmt nur Sensoren mit Wert")

    def test_monitor_status_and_sample(self):
        self.sys.zone(0, "cpu-thermal", 50000)
        with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": str(self.sys.root)}):
            mon = thermal.Monitor()
            self.assertEqual(mon.sample("auto"), 50.0)
            status = mon.status("auto")
            self.assertTrue(status["available"])
            self.assertEqual(status["sensor"]["id"], "thermal:cpu-thermal")
            self.assertNotIn("path", status["sensor"], "kein Dateipfad in der API")
            self.assertEqual(mon.status("off")["reason"], "off")
            self.assertEqual(mon.status("hwmon:k10temp:temp1")["reason"], "missing")
            self.assertIsNone(mon.sample("off"))
        empty = FakeSys()
        self.addCleanup(empty.cleanup)
        with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": str(empty.root)}):
            status = thermal.Monitor().status("auto")
            self.assertFalse(status["available"])
            self.assertEqual(status["reason"], "none")

    def test_selected_sensor_without_value(self):
        self.sys.w1("28-0316a2794bff", temperature=85000)  # DS18B20 hängt auf dem Einschaltwert
        with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": str(self.sys.root)}):
            status = thermal.Monitor().status("w1:28-0316a2794bff")
        self.assertTrue(status["available"])
        self.assertIsNone(status["celsius"])
        self.assertEqual(status["reason"], "no_value", "nicht als „wird aufgezeichnet“ melden")

    def test_setting_validation(self):
        for good in ("auto", "off", "", "thermal:cpu-thermal", "hwmon:k10temp:temp1", "hwmon:nvme:temp2:2",
                     "w1:28-0316a2794bff"):
            settings._as_temp_sensor(good)
        for bad in ("/sys/class/thermal/thermal_zone0/temp", "thermal:../../etc", "w1:28-xyz",
                    "hwmon:k10temp", "auto\nfoo", "thermal:" + "a" * 41, "w1:10-0316a2794bff"):
            with self.assertRaises(settings.ValidationError, msg=bad):
                settings._as_temp_sensor(bad)
        self.assertEqual(settings._as_temp_sensor(""), "auto")


class ThermalSummaryTest(unittest.TestCase):
    def test_pairs_need_both_values(self):
        samples = [{"t": 1, "temp": 20.0, "freq": -3.0}, {"t": 2, "freq": -3.1}, {"t": 3, "temp": 21.0},
                   {"t": 4, "temp": True, "freq": 1.0}, {"t": 5, "temp": 22.5, "freq": -3.2}]
        self.assertEqual(thermal.pairs_from_samples(samples), [[1, 20.0, -3.0], [5, 22.5, -3.2]])

    def test_summary_correlation_and_readiness(self):
        # 4 Tage, Tagesgang 18–26 °C, Frequenz folgt mit 0,15 ppm/K.
        import math
        pairs = []
        for i in range(4 * 96):
            t = i * 900.0
            temp = 22 + 4 * math.sin(2 * math.pi * t / 86400)
            pairs.append([t, temp, -5.0 + 0.15 * (temp - 22)])
        info = thermal.summarize(pairs)
        self.assertTrue(info["ready"])
        self.assertGreater(info["days"], 3.9)
        self.assertAlmostEqual(info["span_k"], 8.0, delta=0.1)
        self.assertAlmostEqual(info["correlation"], 1.0, places=3)
        short = thermal.summarize(pairs[:96])
        self.assertFalse(short["ready"], "1 Tag reicht nicht")
        self.assertEqual(thermal.summarize([])["count"], 0)
        flat = thermal.summarize([[i, 30.0, 1.0] for i in range(20)])
        self.assertIsNone(flat["correlation"])


class HistoryTempTest(unittest.TestCase):
    def test_temp_is_aggregated_sqlite_and_python(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, store.DB_NAME)
        self.addCleanup(store.close_all)
        hist = history.History(None, os.path.join(tmp.name, "history.json.gz"), days=30, db_path=db)
        self.assertEqual(hist.backend, "sqlite")
        now = int(time.time())
        for i in range(400):
            sample = {"t": now - 4000 + i * 10, "freq": -3.0, "offset": 0.0}
            if i % 2 == 0:
                sample["temp"] = 20.0 + (i % 4)   # abwechselnd 20 und 22 °C
            hist.add(sample)
        hist.save(force=True)
        rows = hist.query(None, 50)
        temps = [r["temp"] for r in rows if "temp" in r]
        self.assertTrue(temps, "temp muss die Verdichtung überleben")
        self.assertTrue(all(20.0 <= t <= 22.0 for t in temps))
        merged = history.downsample([{"t": 1, "temp": 20.0}, {"t": 2, "temp": 22.0}, {"t": 3}], 1)
        self.assertEqual(merged[0]["temp"], 21.0)


class LeapParseTest(unittest.TestCase):
    def test_real_file_from_image(self):
        parsed = leap.parse(LEAP_REAL.read_text(encoding="ascii"))
        self.assertIs(parsed["hash_ok"], True)
        info = leap.evaluate(parsed, NOW)
        self.assertEqual(info["tai_utc"], 37)
        self.assertEqual(info["last_leap_date"], "2017-01-01")
        self.assertEqual(info["last_leap_delta"], 1)
        self.assertEqual(info["leap_count"], 27)
        self.assertEqual(info["expires_date"], "2027-06-28")
        self.assertIsNone(info["next_leap_date"])
        self.assertEqual(info["days_left"], 238)
        self.assertEqual((info["level"], info["reason"]), ("ok", None))
        self.assertEqual(leap.insights(info), [])

    def test_expiring_within_60_days(self):
        parsed = leap.parse(LEAP_REAL.read_text(encoding="ascii"))
        expires = leap.to_unix(parsed["expires"])
        info = leap.evaluate(parsed, expires - 30 * 86400)
        self.assertEqual((info["level"], info["reason"], info["days_left"]), ("warn", "expiring", 30))
        items = leap.insights(info)
        self.assertEqual(len(items), 1)
        self.assertIn("Image zu alt", items[0]["title"])
        self.assertEqual(items[0]["action"], "uhrqualitaet")
        self.assertEqual(leap.evaluate(parsed, expires - 61 * 86400)["level"], "ok")

    def test_expired_fixture(self):
        parsed = leap.parse(LEAP_EXPIRED.read_text(encoding="ascii"))
        self.assertIs(parsed["hash_ok"], True, "Testdatei hat eine korrekt neu berechnete Prüfsumme")
        info = leap.evaluate(parsed, NOW)
        self.assertTrue(info["expired"])
        self.assertEqual(info["expires_date"], "2024-06-28")
        self.assertLess(info["days_left"], 0)
        self.assertEqual((info["level"], info["reason"]), ("warn", "expired"))
        self.assertIn("abgelaufen", leap.insights(info)[0]["title"])

    def test_hash_mismatch(self):
        text = re.sub(r"3692217600\s+37", "3692217600 38", LEAP_REAL.read_text(encoding="ascii"))
        parsed = leap.parse(text)
        self.assertIs(parsed["hash_ok"], False)
        info = leap.evaluate(parsed, NOW)
        self.assertEqual((info["level"], info["reason"]), ("warn", "hash"))
        self.assertEqual(info["tai_utc"], 38)

    def test_leading_zeros_in_hash_words(self):
        # Wörter mit führender Null stehen ohne sie in der Datei – Vergleich als Zahl.
        body = "#$ 3676924800\n#@ 3881174400\n2272060800 10 # 1 Jan 1972\n"
        import hashlib
        digest = hashlib.sha1(b"3676924800388117440022720608001 0".replace(b" ", b"")).hexdigest()
        words = " ".join(format(int(digest[i:i + 8], 16), "x") for i in range(0, 40, 8))
        self.assertIs(leap.parse(body + f"#h {words}\n")["hash_ok"], True)
        self.assertIs(leap.parse(body + f"#h {'0' + words}\n")["hash_ok"], True)
        self.assertIsNone(leap.parse(body)["hash_ok"], "ohne #h: unbekannt")

    def test_future_leap_and_errors(self):
        text = re.sub(r"(3692217600\s+37.*)", r"\1\n4030000000 38", LEAP_REAL.read_text(encoding="ascii"))
        info = leap.evaluate(leap.parse(text), NOW)
        self.assertEqual(info["tai_utc"], 37)
        self.assertIsNotNone(info["next_leap_date"])
        self.assertEqual(info["next_leap_delta"], 1)
        with self.assertRaises(leap.LeapFileError):
            leap.parse("#@ 4023129600\n")
        with self.assertRaises(leap.LeapFileError):
            leap.parse("2272060800 10\n")  # ohne Ablaufdatum
        with self.assertRaises(leap.LeapFileError):
            leap.parse("#@ 4023129600\nkaputt zeile\n")

    def test_status_missing_file(self):
        info = leap.status({"leapseclist": "/nicht/da"}, {"leap_status": "Normal"})
        self.assertFalse(info["available"])
        self.assertEqual(info["reason"], "missing")
        self.assertEqual(info["chrony_leap"], "Normal")
        self.assertEqual(leap.insights(info), [], "fehlende Datei meldet confgen/chrony selbst")
        info = leap.status(path=str(LEAP_REAL), now=NOW)
        self.assertTrue(info["available"])
        self.assertEqual(info["tai_utc"], 37)


class LeapSourceTest(unittest.TestCase):
    """UQ-1: Zahlen und Warnungen nur für die Datei, die chrony wirklich liest."""

    def test_error_never_quotes_file_content(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        secret = Path(tmp.name) / "nts.key"
        secret.write_text("webhook_token=SuperSecretValue123456789 more\n", encoding="ascii")
        info = leap.status(path=str(secret))
        self.assertFalse(info["available"])
        self.assertNotIn("SuperSecret", info["error"])
        self.assertNotIn("webhook", info["error"])
        self.assertIn("Zeile 1", info["error"])
        with self.assertRaises(leap.LeapFileError) as ctx:
            leap.parse("#@ 4023129600\n# Kommentar\ngeheim=wert 1\n")
        self.assertNotIn("geheim", str(ctx.exception))
        self.assertIn("Zeile 3", str(ctx.exception))

    def test_empty_setting_is_disabled(self):
        info = leap.status({"leapseclist": "", "leapsectz": ""}, {"leap_status": "Normal"}, now=NOW)
        self.assertEqual((info["source"], info["reason"], info["level"]), ("none", "disabled", "warn"))
        self.assertFalse(info["available"])
        self.assertIsNone(info["path"])
        self.assertNotIn("days_left", info, "keine Zahlen einer Datei, die chrony nicht liest")
        self.assertEqual(leap.insights(info), [])
        watch = leap.Watch(lambda *a: self.fail("kein Ereignis"), lambda since: [])
        self.assertFalse(watch.check(info, NOW))

    def test_leapsectz_makes_list_informational(self):
        exists = lambda p: p == os.path.join(leap.ZONEINFO, "right/UTC")  # noqa: E731
        with mock.patch.object(leap, "DEFAULT_PATH", str(LEAP_EXPIRED)):
            info = leap.status({"leapseclist": "", "leapsectz": "right/UTC"}, now=NOW, exists=exists)
        self.assertEqual((info["source"], info["leapsectz"]), ("tz", "right/UTC"))
        self.assertTrue(info["available"])
        self.assertEqual((info["level"], info["reason"], info["list_reason"]), ("info", "tz", "expired"))
        self.assertEqual(leap.insights(info), [], "abgelaufene Liste, die chrony ignoriert: kein Hinweis")
        watch = leap.Watch(lambda *a: self.fail("kein Ereignis"), lambda since: [])
        self.assertFalse(watch.check(info, NOW))
        # Zone fehlt im Image → confgen nimmt die Liste, also gilt sie auch hier.
        info = leap.status({"leapseclist": str(LEAP_EXPIRED), "leapsectz": "right/UTC"}, now=NOW,
                           exists=lambda p: False)
        self.assertEqual((info["source"], info["reason"]), ("list", "expired"))
        self.assertTrue(leap.insights(info))

    def test_matches_confgen_rule(self):
        import confgen
        cases = [{"leapseclist": "/a.list", "leapsectz": ""}, {"leapseclist": "", "leapsectz": ""},
                 {"leapseclist": "/a.list", "leapsectz": "right/UTC"}, {"leapseclist": "", "leapsectz": "right/UTC"}]
        for zone_exists in (True, False):
            exists = lambda p, z=zone_exists: True if p == "/a.list" else z  # noqa: E731
            for cfg in cases:
                directive = confgen.leap_directive(cfg, warn=lambda *a: None, exists=exists)
                source, detail = leap.chrony_source(cfg, exists)
                expected = {"tz": f"leapsectz {detail}", "list": f"leapseclist {detail}", "none": None}[source]
                self.assertEqual(directive, expected, (cfg, zone_exists))


class LeapWatchTest(unittest.TestCase):
    def test_expired_file_emits_leap_warn_once(self):
        emitted, recent = [], []
        watch = leap.Watch(lambda *args: emitted.append(args), lambda since: recent)
        info = leap.status(path=str(LEAP_EXPIRED), now=NOW)
        self.assertTrue(watch.check(info, NOW))
        self.assertEqual(len(emitted), 1)
        kind, level, title, data = emitted[0]
        self.assertEqual((kind, level), ("leap", "warn"))
        self.assertIn("abgelaufen", title)
        self.assertEqual(data["expires"], "2024-06-28")
        self.assertFalse(watch.check(info, NOW + 3600), "nicht bei jeder Prüfung")
        self.assertTrue(watch.check(info, NOW + 8 * 86400), "nach einer Woche Erinnerung")
        ok = leap.status(path=str(LEAP_REAL), now=NOW)
        self.assertFalse(watch.check(ok, NOW))

    def test_restart_reads_protocol(self):
        info = leap.status(path=str(LEAP_EXPIRED), now=NOW)
        key = f"expired:{info['expires']}"
        emitted = []
        watch = leap.Watch(lambda *args: emitted.append(args),
                           lambda since: [{"t": NOW - 3600, "kind": "leap", "data": {"key": key}}])
        self.assertFalse(watch.check(info, NOW), "nach Neustart nicht erneut melden")
        self.assertEqual(emitted, [])

    def test_with_real_event_store(self):
        import events
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(store, "DATA_DIR", tmp.name):
            try:
                watch = leap.Watch(events.emit, lambda since: events.query(since=since, kinds=["leap"]))
                info = leap.status(path=str(LEAP_EXPIRED))
                self.assertTrue(watch.check(info))
                rows = events.query(kinds=["leap"])
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["kind"], rows[0]["level"]), ("leap", "warn"))
                again = leap.Watch(events.emit, lambda since: events.query(since=since, kinds=["leap"]))
                self.assertFalse(again.check(info))
            finally:
                store.close_all()


class ClockStatusTest(unittest.TestCase):
    def test_levels_and_kinds(self):
        gps = {"synchronised": True, "stratum": 1, "ref_name": "PPS", "root_delay": 0.0, "root_dispersion": 2e-5,
               "system_time_offset": 1e-6, "leap_status": "Normal"}
        out = server.clock_status(gps)
        self.assertEqual((out["level"], out["source_kind"]), ("good", "GPS + PPS"))
        self.assertAlmostEqual(out["accuracy"], 2.1e-5)
        own = server.clock_status({**gps, "ref_name": "XYZ1"})
        self.assertEqual(own["source_kind"], "Referenzuhr", "eigene Refid wird nicht verraten")
        for ref in ("PHC0", "PHC1", "phc2"):
            self.assertEqual(server.clock_status({**gps, "ref_name": ref})["source_kind"], "PTP", ref)
        gnss = server.clock_status({**gps, "ref_name": "GNS1"}, {"gps_refid": "GNS1"})
        self.assertEqual(gnss["source_kind"], "GPS", "eigene gps_refid ist GPS")
        self.assertEqual(server.clock_status({**gps, "ref_name": "GNS1"}, {"gps_refid": "GPS"})["source_kind"],
                         "Referenzuhr")
        ntp = server.clock_status({**gps, "stratum": 3, "ref_name": "ptbtime1.ptb.de", "root_delay": 0.02})
        self.assertEqual(ntp["source_kind"], "NTP")
        bad = server.clock_status({**gps, "stratum": 3, "root_delay": 0.4})
        self.assertEqual(bad["level"], "warn")
        self.assertEqual(server.clock_status({})["level"], "crit")
        island = server.clock_status({"stratum": 10, "local_reference": True, "synchronised": False})
        self.assertEqual((island["level"], island["source_kind"]), ("warn", "lokal (Inselbetrieb)"))


class ClockHttpTest(unittest.TestCase):
    TRACKING = {"synchronised": True, "stratum": 2, "ref_name": "nas.fritz.box", "root_delay": 0.004,
                "root_dispersion": 0.0005, "system_time_offset": 0.0, "leap_status": "Normal"}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, {"WEB_USER": "admin", "WEB_PASSWORD": "geheim123"}),
            mock.patch.object(server.chrony, "tracking", return_value=dict(cls.TRACKING)),
        ]
        for patch in cls.patches:
            patch.start()
        os.environ.pop("CLOCK_PUBLIC", None)
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def setUp(self):
        fake_hostnames(self)  # Host-Prüfung ohne Rückwärts-DNS des Runners
        server._CLOCK_CACHE.update(t=None, tracking=None)

    def request(self, path, auth=False, host="example.com"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host}
        if auth is True:
            headers["Authorization"] = "Basic " + base64.b64encode(b"admin:geheim123").decode()
        elif auth:
            headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def set_public(self, value):
        patcher = mock.patch.dict(os.environ, {"CLOCK_PUBLIC": "true" if value else "false"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_protected_by_default(self):
        self.set_public(False)
        for path in ("/clock", "/api/v1/time", "/static/js/clock.js"):
            self.assertEqual(self.request(path)[0], 401, path)
        status, body = self.request("/api/v1/time", auth=True)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["source"], "nas.fritz.box", "angemeldet: mit Quellennamen")
        self.assertFalse(payload["public"])
        status, body = self.request("/clock", auth=True)
        self.assertEqual(status, 200)
        self.assertIn(b"/static/js/clock.js", body)

    def test_public_clock_shows_only_time(self):
        self.set_public(True)
        before = time.time()
        status, body = self.request("/api/v1/time", host="uhr.local")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(before <= payload["t1"] <= payload["t2"] <= time.time())
        self.assertTrue(payload["public"])
        self.assertIsNone(payload["source"], "ohne Anmeldung kein Quellenname")
        self.assertEqual(payload["source_kind"], "NTP")
        self.assertNotIn(b"fritz", body)
        for path in ("/clock", "/static/app.css", "/static/clock.css", "/static/js/clock.js", "/static/js/clocksync.js"):
            self.assertEqual(self.request(path, host="uhr.local")[0], 200, path)
        # Alles andere bleibt geschützt.
        for path in ("/", "/api/status", "/api/v1/status", "/static/js/app.js", "/api/leap", "/api/temperature",
                     "/metrics", "/static/index.html"):
            self.assertEqual(self.request(path, host="uhr.local")[0], 401, path)

    def test_public_clock_logged_in_gets_source(self):
        self.set_public(True)
        status, body = self.request("/api/v1/time", auth=True)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertFalse(payload["public"])
        self.assertEqual(payload["source"], "nas.fritz.box", "angemeldet: mit Quellennamen")
        status, body = self.request("/api/v1/time", auth="admin:falsch", host="uhr.local")
        self.assertEqual(status, 200, "falsches Passwort: öffentliche Antwort, kein 401")
        self.assertTrue(json.loads(body)["public"])
        self.assertIsNone(json.loads(body)["source"])

    def test_public_clock_any_host(self):
        """1.5.1: Mit clock_public antwortet die Uhr über jeden Namen (kein 403) – nur öffentlich."""
        self.set_public(True)
        for host in ("uhr.example.org", "evil.example", "192.168.1.5", "a" * 64 + ".evil.de"):
            for path in sorted(server.CLOCK_PUBLIC_PATHS):
                with self.subTest(host=host, path=path):
                    status, body = self.request(path, host=host)
                    self.assertEqual(status, 200)
                    self.assertNotIn(b"fritz", body, "kein Quellenname, keine Adresse")
            payload = json.loads(self.request("/api/v1/time", host=host)[1])
            self.assertTrue(payload["public"])
            self.assertIsNone(payload["source"])
        # Alles andere bleibt geschützt, auch über fremde Namen.
        for path in ("/", "/api/status", "/api/v1/status", "/static/js/app.js", "/api/leap", "/metrics",
                     "/static/index.html", "/api/v1/time/../status", "/static/js/../js/app.js"):
            self.assertEqual(self.request(path, host="evil.example")[0], 401, path)
        status, body = self.request("/api/v1/time", auth=True, host="evil.example")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["source"], "nas.fritz.box", "angemeldet: mit Quellennamen")

    def test_public_clock_off_any_host_needs_login(self):
        self.set_public(False)
        for path in ("/clock", "/api/v1/time", "/static/js/clock.js"):
            self.assertEqual(self.request(path, host="evil.example")[0], 401, path)

    def test_time_status_is_cached(self):
        self.set_public(False)
        # Cache-Verhalten, unabhängig vom Tempo des Runners: Die Lebensdauer ist hier 60 s, damit eine
        # Verzögerung (> 1 s, VM-Steal) mitten in der Schleife den Cache nicht ablaufen lässt.
        with mock.patch.object(server.chrony, "tracking", return_value=dict(self.TRACKING)) as tracking, \
                mock.patch.object(server, "CLOCK_CACHE_SECONDS", 60):
            for _ in range(5):
                self.assertEqual(self.request("/api/v1/time", auth=True)[0], 200)
            self.assertEqual(tracking.call_count, 1, "höchstens ein chronyc je Cache-Dauer")
            server._CLOCK_CACHE["t"] -= 120
            self.request("/api/v1/time", auth=True)
            self.assertEqual(tracking.call_count, 2)
        self.assertEqual(server.CLOCK_CACHE_SECONDS, 1.0)

    def test_v1_description(self):
        status, body = self.request("/api/v1", auth=True)
        paths = {e["path"] for e in json.loads(body)["endpoints"]}
        self.assertTrue({"/api/v1/time", "/api/v1/leap", "/api/v1/temperature"} <= paths)

    def test_leap_and_temperature_endpoints(self):
        # Fixture statt /usr/share/zoneinfo/leap-seconds.list des Hosts (fehlt ohne tzdata)
        with mock.patch.object(server.leap, "chrony_source", return_value=("list", str(LEAP_REAL))):
            status, body = self.request("/api/v1/leap", auth=True)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("tai_utc", payload)
        fake = FakeSys()
        self.addCleanup(fake.cleanup)
        fake.zone(0, "cpu-thermal", 47000)
        with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": str(fake.root)}), \
                mock.patch.object(server, "HISTORY") as hist:
            hist.query.return_value = [{"t": 1, "temp": 40.0, "freq": -2.0}, {"t": 2, "freq": -2.0}]
            server.thermal.MONITOR.sensors(refresh=True)
            status, body = self.request("/api/v1/temperature?range=86400", auth=True)
            server.thermal.MONITOR.sensors(refresh=True)
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["pairs"], [[1, 40.0, -2.0]])
        self.assertEqual(payload["summary"]["count"], 1)
        hist.query.assert_called_with(86400.0, 1500)


class ClockPublicNoPasswordTest(unittest.TestCase):
    """clock_public ohne Passwort: über fremde Namen nur die öffentliche Antwort (DNS-Rebinding)."""
    TRACKING = {"synchronised": True, "stratum": 1, "ref_name": "GPS", "root_delay": 0.0,
                "root_dispersion": 0.00002, "system_time_offset": 0.0, "leap_status": "Normal"}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items()
               if k not in {"WEB_USER", "WEB_PASSWORD", "WEB_ALLOWED_HOSTS", "CLOCK_PUBLIC"}}
        env["CLOCK_PUBLIC"] = "true"
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(server.chrony, "tracking", return_value=dict(cls.TRACKING)),
        ]
        for patch in cls.patches:
            patch.start()
        server.AUTH_CACHE.clear()
        server._REJECTED_HOSTS.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        cls.tmp.cleanup()

    def setUp(self):
        fake_hostnames(self)
        server._CLOCK_CACHE.update(t=None, tracking=None)

    def request(self, path, host, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, headers={"Host": host})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_foreign_host_gets_public_answer(self):
        with mock.patch("builtins.print") as printed:
            for path in sorted(server.CLOCK_PUBLIC_PATHS):
                with self.subTest(path=path):
                    self.assertEqual(self.request(path, "uhr.example.org")[0], 200)
            self.assertEqual(self.request("/api/v1/time", "uhr.example.org", "HEAD")[0], 200)
            payload = json.loads(self.request("/api/v1/time", "uhr.example.org")[1])
        self.assertTrue(payload["public"])
        self.assertIsNone(payload["source"], "über einen fremden Namen nie der Quellenname")
        self.assertEqual(payload["source_kind"], "GPS")
        self.assertEqual(set(payload), {"synchronised", "running", "level", "accuracy", "stratum", "leap",
                                        "leap_next", "source_kind", "t1", "t2", "public", "source"},
                         "nur Zeit, Ampel, Genauigkeit, Art der Quelle und die öffentliche Schaltsekunden-Ankündigung")
        self.assertFalse([c for c in printed.call_args_list if "uhr.example" in str(c)], "keine Ablehnung im Log")

    def test_known_host_without_password_gets_source(self):
        payload = json.loads(self.request("/api/v1/time", f"127.0.0.1:{self.port}")[1])
        self.assertFalse(payload["public"])
        self.assertEqual(payload["source"], "GPS")
        with mock.patch.dict(os.environ, {"WEB_ALLOWED_HOSTS": "uhr.example.org"}):
            self.assertEqual(json.loads(self.request("/api/v1/time", "uhr.example.org")[1])["source"], "GPS")

    def test_other_paths_keep_host_check(self):
        with mock.patch("builtins.print"):
            for path in ("/", "/api/status", "/api/v1/status", "/api/v1/gps", "/api/v1/sources", "/api/logs",
                         "/static/js/app.js", "/static/index.html", "/metrics", "/api/settings",
                         "/api/v1/time/x", "/clock/../api/status", "/api/diagnostics/preview"):
                with self.subTest(path=path):
                    self.assertEqual(self.request(path, "uhr.example.org")[0], 403)

    def test_clock_public_off_restores_host_check(self):
        with mock.patch.dict(os.environ, {"CLOCK_PUBLIC": "false"}), mock.patch("builtins.print"):
            for path in ("/clock", "/api/v1/time", "/static/js/clock.js"):
                self.assertEqual(self.request(path, "uhr.example.org")[0], 403, path)


class MetricsTest(unittest.TestCase):
    def test_temperature_and_leap_metrics(self):
        with mock.patch.object(server.chrony, "tracking", return_value={}), \
                mock.patch.object(server.chrony, "detailed_sources", return_value=[]), \
                mock.patch.object(server.chrony, "serverstats", return_value={}), \
                mock.patch.object(server.chrony, "clients", return_value=[]), \
                mock.patch.object(server.chrony, "nts_server_status", return_value={"enabled": False}), \
                mock.patch.object(server.gps, "status", return_value={"enabled": False}), \
                mock.patch.object(server.ptp, "status", return_value={"enabled": False}), \
                mock.patch.object(server.thermal.MONITOR, "last", {"t": time.time(), "celsius": 42.5}), \
                mock.patch.object(server.leap, "chrony_source", return_value=("list", str(LEAP_REAL))):
            text = server.build_metrics()
        self.assertIn("ntpgui_temperature_celsius 42.5", text)
        self.assertIn("ntpgui_tai_utc_offset_seconds 37", text)
        self.assertIn("ntpgui_leapseconds_list_days_left", text)
        with mock.patch.object(server.chrony, "tracking", return_value={}), \
                mock.patch.object(server.chrony, "detailed_sources", return_value=[]), \
                mock.patch.object(server.chrony, "serverstats", return_value={}), \
                mock.patch.object(server.chrony, "clients", return_value=[]), \
                mock.patch.object(server.chrony, "nts_server_status", return_value={"enabled": False}), \
                mock.patch.object(server.gps, "status", return_value={"enabled": False}), \
                mock.patch.object(server.ptp, "status", return_value={"enabled": False}), \
                mock.patch.object(server.leap, "chrony_source", return_value=("none", None)):
            self.assertNotIn("ntpgui_leapseconds_list_days_left", server.build_metrics(),
                             "chrony liest keine Liste – kein Ablaufdatum melden")
        with mock.patch.object(server.chrony, "tracking", return_value={}), \
                mock.patch.object(server.chrony, "detailed_sources", return_value=[]), \
                mock.patch.object(server.chrony, "serverstats", return_value={}), \
                mock.patch.object(server.chrony, "clients", return_value=[]), \
                mock.patch.object(server.chrony, "nts_server_status", return_value={"enabled": False}), \
                mock.patch.object(server.gps, "status", return_value={"enabled": False}), \
                mock.patch.object(server.ptp, "status", return_value={"enabled": False}), \
                mock.patch.object(server.thermal.MONITOR, "last", {"t": time.time() - 3600, "celsius": 42.5}):
            self.assertNotIn("ntpgui_temperature_celsius", server.build_metrics(), "veralteter Wert wird nicht gemeldet")


@unittest.skipUnless(shutil.which("node"), "node nicht installiert")
class ClockSyncJsTest(unittest.TestCase):
    """Rechnung der Vollbild-Uhr (clocksync.js) mit Node."""

    def run_js(self, code):
        module = (ROOT / "app/static/js/clocksync.js").as_uri()
        script = f"import * as c from {json.dumps(module)};\n{code}"
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_rtt_200ms_error_below_100ms(self):
        # Browseruhr geht 3,2 s nach. Fünf Messungen, RTT 200–600 ms, unsymmetrisch verteilt.
        result = self.run_js("""
          const skew = 3200; const out = [];
          const cases = [[150, 50], [300, 300], [100, 100], [500, 100], [50, 250]];
          for (const [up, down] of cases) {
            const t0 = 1000000; const t1 = t0 + skew + up; const t2 = t1 + 3; const t3 = t0 + up + 3 + down;
            out.push(c.measure(t0, t1, t2, t3));
          }
          const best = c.best(out);
          console.log(JSON.stringify({ best, error: Math.abs(best.offset - skew) }));
        """)
        self.assertEqual(result["best"]["rtt"], 200)
        self.assertLess(result["error"], 100)
        self.assertLessEqual(result["error"], result["best"]["accuracy"])

    def test_iso_week_and_format(self):
        result = self.run_js("""
          const w = (s) => c.isoWeek(new Date(s), true);
          console.log(JSON.stringify({
            a: w("2026-11-02T12:00:00Z"), b: w("2021-01-03T12:00:00Z"), d: w("2020-12-31T12:00:00Z"),
            hms: c.hms(new Date("2026-11-02T03:04:05Z"), true),
            acc: [c.fmtAccuracy(0.4), c.fmtAccuracy(4.26), c.fmtAccuracy(42), c.fmtAccuracy(1500)],
            bad: c.measure(5, 1, 0, 6), resp: c.fromResponse(1000, {t1: 1.1, t2: 1.1}, 1010),
          }));
        """)
        self.assertEqual(result["a"], {"week": 45, "year": 2026})
        self.assertEqual(result["b"], {"week": 53, "year": 2020})
        self.assertEqual(result["d"], {"week": 53, "year": 2020})
        self.assertEqual(result["hms"], "03:04:05")
        self.assertEqual(result["acc"], ["± 400 µs", "± 4,3 ms", "± 42 ms", "± 1,5 s"])
        self.assertIsNone(result["bad"], "t2 < t1 ist Unsinn")
        self.assertAlmostEqual(result["resp"]["offset"], 95, places=6)
        self.assertEqual(result["resp"]["rtt"], 10)

    def test_genauigkeit_und_quelle_folgen_der_sprache(self):
        # /clock folgt seit 1.6 der gewählten Sprache: auf Englisch Dezimalpunkt und englischer Rückfall
        # statt fest „1,5 ms“ und „Quelle“.
        i18n = json.dumps((ROOT / "app/static/js/i18n.js").as_uri())
        static = json.dumps(str(ROOT / "app/static"))
        result = self.run_js(f"""
          import {{ readFileSync }} from "node:fs";
          globalThis.fetch = async (u) => ({{ ok: true, json: async () => JSON.parse(readFileSync({static} + u.replace("/static", ""), "utf8")) }});
          const i18n = await import({i18n});
          const de = [c.fmtAccuracy(1.5), c.fmtAccuracy(1234), c.sourceText("", "")];
          await i18n.setLanguage("en");
          console.log(JSON.stringify({{ de, en: [c.fmtAccuracy(1.5), c.fmtAccuracy(1234), c.fmtAccuracy(42), c.sourceText("", ""),
                                               c.sourceText("NTP", "192.0.2.1")] }}));
        """)
        self.assertEqual(result["de"], ["± 1,5 ms", "± 1,2 s", "Quelle"])
        self.assertEqual(result["en"], ["± 1.5 ms", "± 1.2 s", "± 42 ms", "Source", "NTP (192.0.2.1)"])


class DiagnosticsW1SerialTest(unittest.TestCase):
    def test_ds18b20_serial_is_known_value(self):
        import diagnostics
        fake = FakeSys()
        self.addCleanup(fake.cleanup)
        fake.w1("28-0316a2794bff", temperature=21000)
        with mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": str(fake.root)}):
            serials = diagnostics._hardware_serials()
        self.assertIn("28-0316a2794bff", serials)
        self.assertIn("0316a2794bff", serials)


if __name__ == "__main__":
    unittest.main()
