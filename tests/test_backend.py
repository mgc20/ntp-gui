"""Tests for settings, config generation, calibration, insights and the new parsers."""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import chrony  # noqa: E402
import confgen  # noqa: E402
import devices  # noqa: E402
import history  # noqa: E402
import insights  # noqa: E402
import ptp  # noqa: E402
import settings  # noqa: E402

# chronyc -c selectdata (chrony 4.5): GPS refclock too uncertain, two servers.
SELECTDATA = (
    "D,GPS,N,-,-,-,-,-,-,-,-,-,-,2,1.0,-0.143002570,0.256997436,Normal\n"
    "*,127.0.0.1,N,-,-,-,-,-,-,-,-,-,-,3,1.0,-0.000004267,0.000008347,Normal\n"
    "+,127.0.0.2,N,-,-,-,-,-,-,-,-,-,-,0,1.0,-0.000004585,0.000003916,Normal\n"
    "x,192.0.2.7,N,-,-,-,-,-,-,-,-,-,-,0,1.0,0.051000000,0.052000000,Normal\n"
)

NTPDATA = """
Remote address  : 127.0.0.1 (7F000001)
Remote port     : 10123
Local address   : 127.0.0.1 (7F000001)
Leap status     : Normal
Version         : 4
Mode            : Server
Stratum         : 2
Poll interval   : 1 (2 seconds)
Precision       : -25 (0.000000030 seconds)
Root delay      : 0.000000 seconds
Root dispersion : 0.000000 seconds
Reference ID    : 7F7F0101 ()
Reference time  : Sun Nov 01 12:32:20 2026
Offset          : -0.000008954 seconds
Peer delay      : 0.000027329 seconds
Peer dispersion : 0.000000064 seconds
Response time   : 0.000167352 seconds
Jitter asymmetry: +0.48
NTP tests       : 111 111 1101
Interleaved     : No
Authenticated   : No
TX timestamping : Kernel
RX timestamping : Kernel
Total TX        : 659
Total RX        : 659
Total valid RX  : 659
Total good RX   : 309
"""

AUTHDATA = (
    "ptbtime1.ptb.de,NTS,1,15,256,1234,0,0,8,64\n"
    "127.0.0.1,-,0,0,0,4294967295,0,0,0,0\n"
)

ETHTOOL_I210 = """Time stamping parameters for enp3s0:
Capabilities:
\thardware-transmit
\tsoftware-transmit
\thardware-receive
\tsoftware-receive
\tsoftware-system-clock
\thardware-raw-clock
PTP Hardware Clock: 0
Hardware Transmit Timestamp Modes:
\toff
\ton
"""

ETHTOOL_VIRTIO = """Time stamping parameters for eth0:
Capabilities:
\tsoftware-transmit
\tsoftware-receive
\tsoftware-system-clock
PTP Hardware Clock: none
Hardware Transmit Timestamp Modes: none
"""

PTP4L_LOG = [
    "ptp4l[100.1]: port 1 (eth0): INITIALIZING to LISTENING on INIT_COMPLETE",
    "ptp4l[106.2]: port 1 (eth0): LISTENING to UNCALIBRATED on RS_SLAVE",
    "ptp4l[107.9]: port 1 (eth0): UNCALIBRATED to SLAVE on MASTER_CLOCK_SELECTED",
    "ptp4l[123.4]: rms   23 max   51 freq  -1234 +/-  12 delay   812 +/-   3",
]


class SettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (settings.DATA_DIR, settings.SETTINGS_FILE)
        settings.DATA_DIR = os.path.join(self.tmp, "ntp-gui")
        settings.SETTINGS_FILE = os.path.join(settings.DATA_DIR, "settings.json")
        settings._CACHE.update(mtime=None, data=None)
        self.env_backup = dict(os.environ)
        for key in list(os.environ):
            if key.startswith(("NTP_", "GPS_", "PTP_", "NTS_", "WEB_", "PHC")):
                del os.environ[key]

    def tearDown(self):
        settings.DATA_DIR, settings.SETTINGS_FILE = self.saved
        settings._CACHE.update(mtime=None, data=None)
        os.environ.clear()
        os.environ.update(self.env_backup)
        shutil.rmtree(self.tmp, ignore_errors=True)


class SettingsTests(SettingsTestCase):
    def test_defaults(self):
        values = settings.values({})
        self.assertEqual(values["ntp_sources"][0]["host"], "pool.ntp.org")
        self.assertFalse(values["gps_enable"])
        self.assertEqual(values["gps_delay"], 0.2)

    def test_env_overrides_default_and_gui_overrides_env(self):
        env = {"GPS_ENABLE": "true", "GPS_OFFSET": "0.05"}
        eff = settings.effective(env)
        self.assertEqual(eff["gps_offset"]["value"], 0.05)
        self.assertEqual(eff["gps_offset"]["source"], "env")
        settings.save({"gps_offset": 0.123})
        eff = settings.effective(env)
        self.assertEqual(eff["gps_offset"]["value"], 0.123)
        self.assertEqual(eff["gps_offset"]["source"], "gui")
        settings.reset(["gps_offset"])
        self.assertEqual(settings.effective(env)["gps_offset"]["source"], "env")

    def test_env_sources(self):
        env = {"NTP_POOLS": "de.pool.ntp.org", "NTP_SERVERS": "192.0.2.1",
               "NTP_NTS_SERVERS": "ptbtime1.ptb.de"}
        sources = settings.values(env)["ntp_sources"]
        self.assertEqual([(s["type"], s["host"], s["nts"]) for s in sources], [
            ("pool", "de.pool.ntp.org", False), ("server", "192.0.2.1", False),
            ("server", "ptbtime1.ptb.de", True)])

    def test_invalid_env_falls_back(self):
        eff = settings.effective({"GPS_DELAY": "lots"})
        self.assertEqual(eff["gps_delay"]["value"], 0.2)
        self.assertTrue(eff["gps_delay"]["error"])

    def test_save_reports_restart(self):
        result = settings.save({"gps_offset": 0.1, "web_title": "Uhr"})
        self.assertEqual(set(result["changed"]), {"gps_offset", "web_title"})
        self.assertTrue(result["restart"])
        self.assertFalse(settings.save({"web_title": "Uhr 2"})["restart"])
        self.assertEqual(settings.save({"web_title": "Uhr 2"})["changed"], [])

    def test_file_permissions(self):
        settings.save({"web_title": "x"})
        self.assertEqual(stat.S_IMODE(os.stat(settings.SETTINGS_FILE).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(settings.DATA_DIR).st_mode), 0o700)

    def test_rejects_injection(self):
        bad = [
            {"ntp_sources": [{"type": "server", "host": "a.example\nallow all"}]},
            {"ntp_sources": [{"type": "server", "host": "a.example", "options": "cmdallow"}]},
            {"allow_networks": ["10.0.0.0/8\ncmdallow"]},
            {"gps_device": "/dev/ttyACM0; rm -rf /"},
            {"gps_refclock_options": "trust\nlocal"},
            {"web_title": "x" * 500},
            {"unknown_key": 1},
            {"gps_delay": -1},
        ]
        for change in bad:
            with self.subTest(change=change):
                with self.assertRaises(settings.ValidationError) as ctx:
                    settings.save(change)
                self.assertTrue(getattr(ctx.exception, "fields", None))
        self.assertFalse(os.path.exists(settings.SETTINGS_FILE))

    def test_accepts_valid_source_options(self):
        settings.save({"ntp_sources": [
            {"type": "server", "host": "ptbtime1.ptb.de", "nts": True, "prefer": True, "options": "minpoll 4"},
            {"type": "pool", "host": "de.pool.ntp.org"},
        ]})
        sources = settings.values({})["ntp_sources"]
        self.assertTrue(sources[0]["nts"])
        self.assertEqual(sources[0]["options"], "minpoll 4")

    def test_passwords(self):
        encoded = settings.hash_password("geheim123")
        self.assertTrue(settings.verify_password("geheim123", encoded))
        self.assertFalse(settings.verify_password("falsch", encoded))
        with self.assertRaises(settings.ValidationError):
            settings.set_credentials("admin", "kurz")
        with self.assertRaises(settings.ValidationError):
            settings.set_credentials("ad min", "langgenug")
        settings.set_credentials("admin", "langgenug")
        creds = settings.stored_credentials()
        self.assertEqual(creds["user"], "admin")
        self.assertNotIn("langgenug", Path(settings.SETTINGS_FILE).read_text())
        self.assertNotIn("auth", settings.export_values())
        settings.set_credentials("", None)
        self.assertIsNone(settings.stored_credentials())

    def test_public_schema_has_no_functions(self):
        import json
        json.dumps(settings.public_schema())


class ConfgenTests(SettingsTestCase):
    def render(self, env=None, **changes):
        if changes:
            settings.save(changes)
        warnings = []
        text = confgen.render_chrony(settings.values(env or {}), env or {},
                                     warn=lambda *a: warnings.append(a))
        return text, warnings

    def test_default_config(self):
        text, _ = self.render()
        self.assertIn("pool pool.ntp.org iburst maxsources 4", text)
        self.assertIn("allow 192.168.0.0/16", text)
        self.assertIn("local stratum 10", text)
        self.assertIn("dumpdir /var/lib/chrony", text)
        self.assertNotIn("refclock", text)

    def test_nts_and_flags(self):
        text, _ = self.render(ntp_sources=[
            {"type": "server", "host": "ptbtime1.ptb.de", "nts": True, "prefer": True},
            {"type": "server", "host": "192.0.2.1", "noselect": True},
        ])
        self.assertRegex(text, r"server ptbtime1\.ptb\.de iburst .*nts")
        self.assertRegex(text, r"server ptbtime1\.ptb\.de .*prefer")
        self.assertRegex(text, r"server 192\.0\.2\.1 .*noselect")
        self.assertIn("ntsdumpdir", text)
        self.assertIn("nocerttimecheck 1", text)

    def test_gps_refclock(self):
        device = "/dev/null"  # exists everywhere and passes the /dev/ check
        text, _ = self.render(gps_enable=True, gps_device=device, gps_offset=0.057,
                              gps_delay=0.01, gps_select="prefer", gps_bound_mode="manual")
        line = next(l for l in text.splitlines() if l.startswith("refclock SHM"))
        self.assertIn("offset 0.057", line)
        self.assertIn("delay 0.01", line)
        self.assertIn("prefer", line)
        self.assertIn("refid GPS", line)

    def test_gps_missing_device_warns(self):
        text, warnings = self.render(gps_enable=True, gps_device="/dev/does-not-exist")
        self.assertNotIn("refclock SHM", text)
        self.assertTrue(warnings)

    def test_no_serving_without_allow(self):
        text, _ = self.render(allow_networks=[])
        self.assertNotIn("\nallow", text)

    @unittest.skipUnless(shutil.which("chronyd"), "chronyd not installed")
    def test_chronyd_accepts_config(self):
        device = "/dev/null"  # exists everywhere and passes the /dev/ check
        version = subprocess.run(["chronyd", "-v"], capture_output=True, text=True).stdout
        match = re.search(r"version (\d+)\.(\d+)", version)
        # leapseclist kennt chrony erst ab 4.6 (Image: Debian trixie); ältere Test-Hosts
        # prüfen den Rest der Konfiguration ohne diese Zeile.
        extra = {} if match and (int(match[1]), int(match[2])) >= (4, 6) else {"leapseclist": ""}
        text, _ = self.render(
            **extra,
            gps_enable=True, gps_device=device, ntp_ratelimit=True, ntp_minsources=2,
            ntp_sources=[{"type": "server", "host": "ptbtime1.ptb.de", "nts": True}])
        conf = os.path.join(self.tmp, "chrony.conf")
        Path(conf).write_text(text)
        result = subprocess.run(["chronyd", "-p", "-f", conf], capture_output=True, text=True)
        if result.returncode and "Permission denied" in result.stderr:
            # AppArmor-Profil des Hosts (z. B. GitHub-Runner) erlaubt chronyd kein /tmp –
            # der Container-Test prüft die erzeugte Konfiguration dann im Image.
            self.skipTest("chronyd darf die Testdatei nicht lesen (AppArmor)")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_leap_directive(self):
        import confgen
        notes = []
        warn = lambda _t, msg: notes.append(msg)
        cfg = {"leapsectz": "", "leapseclist": "/usr/share/zoneinfo/leap-seconds.list"}
        self.assertEqual(confgen.leap_directive(cfg, warn, exists=lambda p: True),
                         "leapseclist /usr/share/zoneinfo/leap-seconds.list")
        # Altes right/UTC im trixie-Image: fällt auf die Liste zurück, mit Hinweis.
        cfg["leapsectz"] = "right/UTC"
        self.assertEqual(confgen.leap_directive(cfg, warn, exists=lambda p: "right" not in p),
                         "leapseclist /usr/share/zoneinfo/leap-seconds.list")
        self.assertTrue(notes)
        self.assertEqual(confgen.leap_directive(cfg, warn, exists=lambda p: True),
                         "leapsectz right/UTC")
        self.assertIsNone(confgen.leap_directive(cfg, warn, exists=lambda p: False))

    def test_ptp4l_config(self):
        settings.save({"ptp_enable": True, "ptp_interface": "eth0", "ptp_domain": 24,
                       "ptp_transport": "L2", "ptp_time_stamping": "software"})
        text = confgen.render_ptp4l(settings.values({}), {})
        self.assertRegex(text, r"domainNumber\s+24\n")
        self.assertRegex(text, r"network_transport\s+L2\n")
        self.assertRegex(text, r"time_stamping\s+software\n")
        self.assertIn("[eth0]", text)


class CalibrationTests(unittest.TestCase):
    @staticmethod
    def samples(count, bias, step=10, noise=0.0005):
        out = []
        for i in range(count):
            jitter = noise if i % 2 else -noise
            out.append({"t": i * step, "sources": {
                "GPS": {"o": bias + jitter, "s": "D", "k": "#"},
                "a": {"o": 0.00001, "s": "*", "k": "^"},
                "b": {"o": -0.00001, "s": "+", "k": "^"},
                "c": {"o": 0.5, "s": "x", "k": "^"},
            }})
        return out

    def test_insufficient(self):
        self.assertEqual(history.calibrate(self.samples(5, 0.05), "GPS", 0.0, 0.2)["status"], "insufficient")

    def test_preliminary_and_ready(self):
        result = history.calibrate(self.samples(60, 0.057), "GPS", 0.0, 0.2)
        self.assertEqual(result["status"], "preliminary")
        self.assertAlmostEqual(result["bias"], 0.057, places=3)
        result = history.calibrate(self.samples(400, 0.057), "GPS", 0.0, 0.2)
        self.assertEqual(result["status"], "ready")
        self.assertAlmostEqual(result["suggested_offset"], 0.057, places=3)
        self.assertGreaterEqual(result["suggested_delay"], 0.005)
        self.assertLessEqual(result["suggested_delay"], 0.2)

    def test_offset_adds_to_current(self):
        result = history.calibrate(self.samples(400, 0.010), "GPS", 0.050, 0.2)
        self.assertAlmostEqual(result["suggested_offset"], 0.060, places=3)

    def test_already_calibrated(self):
        result = history.calibrate(self.samples(400, 0.0001), "GPS", 0.057, 0.01)
        self.assertEqual(result["status"], "calibrated")

    def test_history_roundtrip(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "h.json.gz")
            store = history.History(100, path)
            for i in range(150):
                store.add({"t": i, "offset": i * 1e-6})
            self.assertEqual(len(store.snapshot()), 100)
            store.save(force=True)
            again = history.History(100, path)
            self.assertEqual(again.load(), 100)
            self.assertLessEqual(len(history.downsample(again.snapshot(), 10)), 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ParserTests(unittest.TestCase):
    def test_selectdata(self):
        rows = {r["name"]: r for r in chrony.parse_selectdata(SELECTDATA)}
        self.assertEqual(rows["GPS"]["select_state"], "large_distance")
        self.assertEqual(rows["127.0.0.1"]["select_state"], "best")
        self.assertEqual(rows["127.0.0.2"]["select_state"], "combined")
        self.assertEqual(rows["192.0.2.7"]["select_state"], "falseticker")
        self.assertAlmostEqual(rows["GPS"]["interval_low"], -0.143002570)
        self.assertAlmostEqual(rows["GPS"]["interval_high"], 0.256997436)

    def test_ntpdata(self):
        (row,) = chrony.parse_ntpdata(NTPDATA)
        self.assertEqual(row["stratum"], 2)
        self.assertAlmostEqual(row["peer_delay"], 0.000027329)
        self.assertEqual(row["ntp_tests_passed"], 9)
        self.assertEqual(row["ntp_tests_total"], 10)
        self.assertEqual(row["total_good_rx"], 309)

    def test_authdata(self):
        rows = {r["name"]: r for r in chrony.parse_authdata(AUTHDATA)}
        self.assertEqual(rows["ptbtime1.ptb.de"]["mode"], "NTS")
        self.assertEqual(rows["ptbtime1.ptb.de"]["cookies"], 8)
        self.assertIsNone(rows["127.0.0.1"]["last_ke_ago"])

    def test_ethtool(self):
        i210 = devices.parse_ethtool_t(ETHTOOL_I210)
        self.assertTrue(i210["hardware_tx"] and i210["hardware_rx"])
        self.assertEqual(i210["phc_index"], "0")
        virtio = devices.parse_ethtool_t(ETHTOOL_VIRTIO)
        self.assertFalse(virtio["hardware_tx"])
        self.assertIsNone(virtio["phc_index"])

    def test_ptp4l_log(self):
        metrics = ptp.parse_log_metrics(PTP4L_LOG)
        self.assertEqual(metrics["rms_ns"], 23)
        self.assertEqual(metrics["max_ns"], 51)
        self.assertEqual(metrics["freq_ppb"], -1234)
        self.assertEqual(metrics["path_delay_ns"], 812)
        self.assertEqual(len(metrics["transitions"]), 3)


class InsightTests(unittest.TestCase):
    CFG = {"ntp_minsources": 1, "gps_refid": "GPS", "gps_delay": 0.2}

    STATUS = {"chrony_running": True, "tracking": {}, "sources": [], "system": {},
              "ui": {"storage": {"persistent": True}, "auth": {"enabled": True}}}

    def ptp_keys(self, **cfg):
        base = {"ptp_enable": True, "ptp_interface": "eth0", "ptp_time_stamping": "hardware",
                "phc2sys_enable": True, "phc2sys_options": ""}
        base.update(cfg)
        return {i["key"]: i for i in insights.build(self.STATUS, dict(self.CFG, **base))
                if i["key"].startswith("ptp_")}

    def test_ptp_grandmaster_without_phc2sys(self):
        items = self.ptp_keys(ptp_mode="master", phc2sys_enable=False)
        self.assertEqual(list(items), ["ptp_gm_free_running"])
        item = items["ptp_gm_free_running"]
        self.assertEqual((item["level"], item["action"], item["title"]),
                         ("warn", "settings", "PTP-Grandmaster verteilt eine frei laufende Uhr"))
        self.assertEqual(self.ptp_keys(ptp_mode="master"), {})
        # Software-Zeitstempel: keine Kartenuhr, also nichts frei Laufendes.
        self.assertEqual(self.ptp_keys(ptp_mode="master", phc2sys_enable=False,
                                       ptp_time_stamping="software"), {})
        self.assertEqual(self.ptp_keys(ptp_mode="master", phc2sys_enable=False, ptp_enable=False), {})
        self.assertEqual(self.ptp_keys(ptp_mode="master", phc2sys_enable=False, ptp_interface=""), {})

    def test_ptp_grandmaster_custom_options_steer_system_clock(self):
        self.assertEqual(list(self.ptp_keys(ptp_mode="master", phc2sys_options="-a -r")),
                         ["ptp_gm_phc2sys_options"])
        # Alter Standard "-a -r -m" gilt als automatisch → kein Hinweis.
        self.assertEqual(self.ptp_keys(ptp_mode="master", phc2sys_options="-a -r -m"), {})

    def test_ptp_auto_mode_warnings(self):
        self.assertEqual(list(self.ptp_keys(ptp_mode="auto")), ["ptp_auto_phc2sys"])
        self.assertEqual(list(self.ptp_keys(ptp_mode="auto", ptp_time_stamping="software")),
                         ["ptp_auto_software"])
        self.assertEqual(self.ptp_keys(ptp_mode="auto", phc2sys_enable=False), {})
        self.assertEqual(self.ptp_keys(ptp_mode="slave"), {})
        self.assertTrue(all(i["level"] == "warn" for i in
                            self.ptp_keys(ptp_mode="auto", ptp_time_stamping="software").values()))

    def test_nts_grammar(self):
        nts = {"enabled": True, "cert": "/certs/a.pem", "key": "/certs/b.pem"}
        text = insights.nts_server_insights(nts)[0]["text"]
        self.assertIn("/certs/a.pem und /certs/b.pem fehlen.", text)
        text = insights.nts_server_insights(dict(nts, key_exists=True))[0]["text"]
        self.assertIn("/certs/a.pem fehlt.", text)
        both = dict(nts, cert_exists=True, key_exists=True, cert_readable=False, key_readable=False)
        text = insights.nts_server_insights(both)[0]["text"]
        self.assertIn("existieren, lassen sich aber nicht lesen", text)
        one = dict(both, key_readable=True)
        self.assertIn("/certs/a.pem existiert, lässt sich aber nicht lesen",
                      insights.nts_server_insights(one)[0]["text"])

    def keys(self, status, cfg=None):
        return {i["key"] for i in insights.build(status, cfg or self.CFG)}

    def test_chrony_down_short_circuits(self):
        self.assertEqual(self.keys({"chrony_running": False}), {"chrony_down"})

    def test_gps_distance_and_uncalibrated(self):
        status = {
            "chrony_running": True,
            "tracking": {"synchronised": True, "stratum": 2},
            "sources": [
                {"mode": "^", "name": "a", "state": "*", "reach": 255},
                {"mode": "#", "name": "GPS", "reach": 255, "select_state": "large_distance", "offset": 0.057},
            ],
            "gps": {"enabled": True, "running": True, "has_fix": True},
            "ui": {"storage": {"persistent": True}, "auth": {"enabled": True}},
        }
        keys = self.keys(status)
        self.assertIn("synced", keys)
        self.assertIn("gps_distance", keys)
        self.assertNotIn("gps_uncal", keys)
        status["sources"][1]["select_state"] = "falseticker"
        self.assertIn("gps_falseticker", self.keys(status))
        status["sources"][1]["select_state"] = "not_combined"
        self.assertIn("gps_uncal", self.keys(status))

    def test_gps_hints_in_auto_mode_need_no_click(self):
        status = {
            "chrony_running": True,
            "tracking": {"synchronised": True, "stratum": 2},
            "sources": [
                {"mode": "^", "name": "a", "state": "*", "reach": 255},
                {"mode": "#", "name": "GPS", "reach": 255, "select_state": "falseticker", "offset": 0.051},
            ],
            "gps": {"enabled": True, "running": True, "has_fix": True},
            "ui": {"storage": {"persistent": True}, "auth": {"enabled": True}},
        }
        auto = dict(self.CFG, gps_autocal="auto")
        items = {i["key"]: i for i in insights.build(status, auto)}
        self.assertEqual(items["gps_falseticker"]["level"], "info")
        self.assertIn("nichts tun", items["gps_falseticker"]["text"])
        status["sources"][1]["select_state"] = "large_distance"
        items = {i["key"]: i for i in insights.build(status, auto)}
        self.assertNotIn("übernehmen", items["gps_distance"]["text"])
        manual = {i["key"]: i for i in insights.build(status, dict(self.CFG, gps_autocal="suggest"))}
        self.assertIn("übernehmen", manual["gps_distance"]["text"])

    def test_unreachable_and_island(self):
        status = {
            "chrony_running": True,
            "tracking": {"synchronised": False, "local_reference": True, "stratum": 10},
            "sources": [{"mode": "^", "name": "x", "hostname": "pool", "reach": 0}],
        }
        keys = self.keys(status)
        self.assertIn("island", keys)
        self.assertIn("unreach:x", keys)


if __name__ == "__main__":
    unittest.main()
