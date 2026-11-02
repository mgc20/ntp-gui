"""Grandmaster-Fix: phc2sys-Richtung, chronyd -x, Grandmaster-Ankündigung, Profile."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import confgen  # noqa: E402
import ptp  # noqa: E402
import settings  # noqa: E402

TRACK_PPS = {"leap_status": "Normal", "stratum": 1, "system_time_offset": 2e-7,
             "root_delay": 0.0, "root_dispersion": 1.5e-6}
TRACK_NTP = {"leap_status": "Normal", "stratum": 2, "system_time_offset": 1e-4,
             "root_delay": 0.004, "root_dispersion": 0.0005}
TRACK_UNSYNC = {"leap_status": "Not synchronised", "stratum": 16, "system_time_offset": 0.0,
                "root_delay": 1.0, "root_dispersion": 1.0}

PPS_LOCKED = [{"mode": "#", "state": "*", "name": "PPS", "reach": 0o377},
              {"mode": "#", "state": "-", "name": "GPS", "reach": 0o377},
              {"mode": "^", "state": "+", "name": "192.0.2.1", "reach": 0o377}]
PPS_SETTLING = [{"mode": "#", "state": "*", "name": "PPS", "reach": 0o17}]
NMEA_ONLY = [{"mode": "#", "state": "*", "name": "GPS", "reach": 0o377}]
NTP_ONLY = [{"mode": "#", "state": "?", "name": "PPS", "reach": 0},
            {"mode": "^", "state": "*", "name": "192.0.2.1", "reach": 0o377}]


class GrandmasterDecisionTests(unittest.TestCase):
    def test_pps_locked_is_class_6_gnss(self):
        props = ptp.grandmaster_properties(TRACK_PPS, PPS_LOCKED)
        self.assertEqual(props["clockClass"], 6)
        self.assertEqual(props["timeSource"], 0x20)
        self.assertEqual((props["timeTraceable"], props["frequencyTraceable"],
                          props["currentUtcOffsetValid"], props["ptpTimescale"]), (1, 1, 1, 1))
        self.assertEqual(props["clockAccuracy"], 0x24)  # 1,7 µs -> "innerhalb 2,5 µs"
        self.assertEqual(props["currentUtcOffset"], 37)

    def test_pps_not_yet_stable_stays_248(self):
        props = ptp.grandmaster_properties(TRACK_PPS, PPS_SETTLING)
        self.assertEqual(props["clockClass"], 248)
        self.assertEqual(props["timeSource"], 0x20)
        self.assertEqual(props["reason"], "gps_pps_settling")

    def test_nmea_only_is_traceable_but_not_class_6(self):
        track = dict(TRACK_PPS, root_dispersion=0.004)
        props = ptp.grandmaster_properties(track, NMEA_ONLY)
        self.assertEqual(props["clockClass"], 248)
        self.assertEqual(props["timeSource"], 0x20)
        self.assertEqual(props["timeTraceable"], 1)
        self.assertEqual(props["clockAccuracy"], 0x2B)  # 4 ms -> "innerhalb 10 ms"

    def test_ntp(self):
        props = ptp.grandmaster_properties(TRACK_NTP, NTP_ONLY)
        self.assertEqual((props["clockClass"], props["timeSource"]), (248, 0x50))
        self.assertEqual(props["timeTraceable"], 1)
        self.assertEqual(props["clockAccuracy"], 0x2B)  # 0,1+0,5+2 ms -> 10 ms

    def test_unsynchronised(self):
        props = ptp.grandmaster_properties(TRACK_UNSYNC, [])
        self.assertEqual((props["clockClass"], props["timeSource"]), (248, 0xA0))
        self.assertEqual((props["timeTraceable"], props["frequencyTraceable"],
                          props["currentUtcOffsetValid"]), (0, 0, 0))
        self.assertEqual(props["clockAccuracy"], 0xFE)

    def test_no_selected_source_is_unsynchronised(self):
        props = ptp.grandmaster_properties(TRACK_NTP, [{"mode": "^", "state": "+", "name": "x"}])
        self.assertEqual(props["timeSource"], 0xA0)

    def test_chrony_unreachable_means_no_decision(self):
        self.assertIsNone(ptp.grandmaster_properties({}, PPS_LOCKED))

    def test_holdover_after_pps_loss(self):
        props = ptp.grandmaster_properties(TRACK_NTP, NTP_ONLY, holdover_age=120, holdover_limit=900)
        self.assertEqual((props["clockClass"], props["timeSource"], props["reason"]),
                         (7, 0x20, "holdover"))
        props = ptp.grandmaster_properties(TRACK_NTP, NTP_ONLY, holdover_age=1200, holdover_limit=900)
        self.assertEqual(props["clockClass"], 248)
        # Ohne Synchronisation kein Holdover-Versprechen.
        props = ptp.grandmaster_properties(TRACK_UNSYNC, [], holdover_age=10)
        self.assertEqual(props["clockClass"], 248)

    def test_leap_flags(self):
        props = ptp.grandmaster_properties(dict(TRACK_PPS, leap_status="Insert second"), PPS_LOCKED)
        self.assertEqual((props["leap61"], props["leap59"]), (1, 0))
        props = ptp.grandmaster_properties(dict(TRACK_PPS, leap_status="Delete second"), PPS_LOCKED)
        self.assertEqual((props["leap61"], props["leap59"]), (0, 1))

    def test_custom_refid_and_utc_offset(self):
        props = ptp.grandmaster_properties(TRACK_PPS, [{"mode": "#", "state": "*", "name": "NMEA"}],
                                           gps_refid="NMEA", utc_offset=38)
        self.assertEqual((props["timeSource"], props["currentUtcOffset"]), (0x20, 38))

    def test_accuracy_codes(self):
        self.assertEqual(ptp.accuracy_code(20e-9), 0x20)
        self.assertEqual(ptp.accuracy_code(1e-6), 0x23)
        self.assertEqual(ptp.accuracy_code(0.5), 0x2F)
        self.assertEqual(ptp.accuracy_code(100.0), 0x31)
        self.assertEqual(ptp.accuracy_code(None), 0xFE)

    def test_pmc_command_format(self):
        cmd = ptp.grandmaster_command(ptp.grandmaster_properties(TRACK_PPS, PPS_LOCKED))
        self.assertEqual(cmd, "SET GRANDMASTER_SETTINGS_NP clockClass 6 clockAccuracy 0x24 "
                              "offsetScaledLogVariance 0xffff currentUtcOffset 37 leap61 0 leap59 0 "
                              "currentUtcOffsetValid 1 ptpTimescale 1 timeTraceable 1 "
                              "frequencyTraceable 1 timeSource 0x20")


class ExpertEnvTests(unittest.TestCase):
    """PTP_TX_TIMESTAMP_TIMEOUT, PTP_UDS_ADDRESS, PTP_UTC_OFFSET, PTP_HOLDOVER_SECONDS."""

    def test_ptp4l_conf_values(self):
        cfg = _cfg()
        text = confgen.render_ptp4l(cfg, {})
        self.assertRegex(text, r"tx_timestamp_timeout\s+10\n")
        self.assertRegex(text, r"uds_address\s+/var/run/ptp4l\n")
        self.assertNotIn("utc_offset", text)
        text = confgen.render_ptp4l(cfg, {"PTP_TX_TIMESTAMP_TIMEOUT": "50",
                                          "PTP_UDS_ADDRESS": "/run/ptp/gm", "PTP_UTC_OFFSET": "38"})
        self.assertRegex(text, r"tx_timestamp_timeout\s+50\n")
        self.assertRegex(text, r"uds_address\s+/run/ptp/gm\n")
        self.assertRegex(text, r"utc_offset\s+38\n")

    def test_ptp4l_role_options_use_linuxptp4_names(self):
        # linuxptp 4.x (trixie) meldet slaveOnly/masterOnly als veraltet:
        # "option slaveOnly is deprecated, please use clientOnly instead"
        for mode, client, server in (("slave", 1, 0), ("master", 0, 1), ("auto", 0, 0)):
            text = confgen.render_ptp4l(_cfg(ptp_mode=mode), {})
            self.assertRegex(text, rf"\nclientOnly\s+{client}\n")
            self.assertRegex(text, rf"\nserverOnly\s+{server}\n")
            self.assertNotIn("slaveOnly", text)
            self.assertNotIn("masterOnly", text)

    def test_invalid_values_fall_back_with_warning(self):
        env = {"PTP_TX_TIMESTAMP_TIMEOUT": "10\nslaveOnly 1", "PTP_UDS_ADDRESS": "/run/a b",
               "PTP_UTC_OFFSET": "-5", "PTP_HOLDOVER_SECONDS": "inf"}
        text = confgen.render_ptp4l(_cfg(), env)
        self.assertRegex(text, r"tx_timestamp_timeout\s+10\n")
        self.assertNotIn("slaveOnly 1\n", text)
        self.assertRegex(text, r"clientOnly\s+0\n")
        self.assertRegex(text, r"uds_address\s+/var/run/ptp4l\n")
        self.assertNotIn("utc_offset", text)
        warnings = confgen.expert_env_warnings(env)
        self.assertEqual(len(warnings), 4)
        self.assertTrue(all(w.startswith("WARNUNG") for w in warnings))
        self.assertEqual(confgen.expert_env_warnings({"PTP_UTC_OFFSET": "37"}), [])
        for bad in ("relativ/pfad", "/a/../etc/x", "/run/x;rm"):
            self.assertEqual(settings.ptp_uds_address({"PTP_UDS_ADDRESS": bad}), "/var/run/ptp4l")

    def test_grandmaster_numbers(self):
        with mock.patch.dict(os.environ, {"PTP_UTC_OFFSET": "38", "PTP_HOLDOVER_SECONDS": "0"}):
            self.assertEqual((ptp.utc_offset(), ptp.holdover_seconds()), (38, 0.0))
        with mock.patch.dict(os.environ, {"PTP_UTC_OFFSET": "abc", "PTP_HOLDOVER_SECONDS": "-1"}):
            self.assertEqual((ptp.utc_offset(), ptp.holdover_seconds()), (37, 900.0))
        with mock.patch.dict(os.environ, {"PTP_UDS_ADDRESS": "/run/ptp/gm"}):
            self.assertIn("/run/ptp/gm", ptp._pmc_base(GrandmasterUpdateTests.CFG))


# Anfangszustand, wie ihn ein frisch gestarteter Prozess sieht
PRISTINE_GM_STATE = dict(ptp._GM_STATE)


class GrandmasterUpdateTests(unittest.TestCase):
    CFG = {"ptp_enable": True, "ptp_interface": "eth0", "ptp_mode": "master", "ptp_domain": 0,
           "ptp_profile": "default", "gps_refid": "GPS"}

    def setUp(self):
        self.saved = dict(ptp._GM_STATE)
        ptp._GM_STATE.update(key=None, accuracy=None, sent=float("-inf"), failed=0.0, last_locked=None,
                             logged_error=False)
        # Die ptp4l-Kennung kommt sonst aus der Prozesstabelle des Hosts: Läuft dort gerade ein ptp4l an
        # oder ab (z. B. Ptp4lSyntaxTests einer parallel laufenden Testsuite), ändert sich der Schlüssel
        # und es wird mitten im Test „wegen Neustart“ gesendet. Tests, die die Kennung brauchen, patchen
        # sie selbst; die Kennung selbst prüft Ptp4lIdentityTests.
        patcher = mock.patch.object(ptp, "_ptp4l_identity", return_value="svc:1:1")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        ptp._GM_STATE.clear()
        ptp._GM_STATE.update(self.saved)

    def test_sends_only_on_change_and_rate_limits(self):
        sent = []
        with mock.patch.object(ptp, "_send_grandmaster", side_effect=lambda c, p: sent.append(p) or True):
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1000.0)
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1010.0)   # unverändert
            ptp._update_grandmaster(self.CFG, TRACK_NTP, NTP_ONLY, 1012.0)     # Holdover (Klasse 7)
            ptp._update_grandmaster(self.CFG, TRACK_UNSYNC, [], 1013.0)        # < 5 s: warten
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1400.0)   # zurück auf 6
        self.assertEqual([p["clockClass"] for p in sent], [6, 7, 6])

    def test_first_send_right_after_boot(self):
        """monotonic() zählt ab Systemstart: Auch 2 s nach dem Booten geht die erste Ankündigung hinaus."""
        ptp._GM_STATE.clear()
        ptp._GM_STATE.update(PRISTINE_GM_STATE)  # Zustand wie direkt nach dem Import
        sent = []
        with mock.patch.object(ptp, "_send_grandmaster", side_effect=lambda c, p: sent.append(p) or True):
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 2.0)
        self.assertEqual(len(sent), 1)

    def test_failure_backs_off_and_never_raises(self):
        calls = []
        with mock.patch.object(ptp, "_send_grandmaster", side_effect=lambda c, p: calls.append(1) or False):
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1000.0)
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1010.0)
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1031.0)
        self.assertEqual(len(calls), 2)
        with mock.patch.object(ptp, "_send_grandmaster", side_effect=RuntimeError("kaputt")), \
                mock.patch("builtins.print"):
            ptp.update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED)  # wirft nicht

    def test_resends_after_ptp4l_restart(self):
        sent = []
        ident = ["svc:100:1000"]
        with mock.patch.object(ptp, "_send_grandmaster", side_effect=lambda c, p: sent.append(p) or True), \
                mock.patch.object(ptp, "_ptp4l_identity", side_effect=lambda: ident[0]):
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1000.0)
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1010.0)   # unverändert
            ident[0] = "svc:200:1015"                                         # ptp4l neu gestartet
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1020.0)
            ptp._update_grandmaster(self.CFG, TRACK_PPS, PPS_LOCKED, 1030.0)   # wieder unverändert
        self.assertEqual(len(sent), 2)

    def test_status_shows_effective_transport(self):
        self.assertEqual(ptp._effective_transport({"ptp_profile": "gptp", "ptp_transport": "UDPv4"}), "L2")
        self.assertEqual(ptp._effective_transport({"ptp_profile": "gptp", "ptp_transport": "UDPv6"}), "UDPv6")
        self.assertEqual(ptp._effective_transport({"ptp_profile": "default", "ptp_transport": "UDPv4"}), "UDPv4")

    def test_not_master_does_nothing(self):
        with mock.patch.object(ptp, "_send_grandmaster") as send:
            for mode in ("slave", "auto"):
                ptp._update_grandmaster(dict(self.CFG, ptp_mode=mode), TRACK_PPS, PPS_LOCKED, 1000.0)
            ptp._update_grandmaster(dict(self.CFG, ptp_enable=False), TRACK_PPS, PPS_LOCKED, 1000.0)
        send.assert_not_called()

    def test_gptp_profile_adds_transport_specific(self):
        self.assertIn("-t", ptp._pmc_base(dict(self.CFG, ptp_profile="gptp")))
        self.assertNotIn("-t", ptp._pmc_base(self.CFG))


class Ptp4lIdentityTests(unittest.TestCase):
    def test_ptp4l_identity_sources(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "services.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"services": {"ptp4l": {"state": "running", "pid": 4711, "since": 99}}}')
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": tmp}):
            self.assertEqual(ptp._ptp4l_identity(), "svc:4711:99")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"services": {"ptp4l": {"state": "stopped", "pid": null}}}')
            with mock.patch.object(ptp, "_proc_identity", return_value="proc:1:2") as proc:
                self.assertEqual(ptp._ptp4l_identity(), "proc:1:2")
                proc.assert_called_with("ptp4l")
        # /proc-Suche: der eigene Prozess über seinen comm-Namen.
        with open("/proc/self/comm", encoding="utf-8") as handle:
            comm = handle.read().strip()
        self.assertIn(f"proc:{os.getpid()}:", ptp._proc_identity(comm) or "")
        self.assertIsNone(ptp._proc_identity("kein-solcher-prozess"))


def _cfg(**over):
    cfg = settings.values({})
    cfg.update(ptp_enable=True, ptp_interface="eth0", phc2sys_enable=True)
    cfg.update(over)
    return cfg


class Phc2sysPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (settings.DATA_DIR, settings.SETTINGS_FILE)
        settings.DATA_DIR = os.path.join(self.tmp, "ntp-gui")
        settings.SETTINGS_FILE = os.path.join(settings.DATA_DIR, "settings.json")
        settings._CACHE.update(mtime=None, data=None)

    def tearDown(self):
        settings.DATA_DIR, settings.SETTINGS_FILE = self.saved
        settings._CACHE.update(mtime=None, data=None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_is_automatic(self):
        self.assertEqual(settings.values({})["phc2sys_options"], "")

    def test_master_copies_system_clock_to_phc(self):
        plan = confgen.phc2sys_plan(_cfg(ptp_mode="master"))
        self.assertEqual(plan["options"], "-a -rr -m")
        self.assertTrue(plan["start"])
        self.assertFalse(plan["nocontrol"])  # chronyd regelt weiter nach GPS/NTP

    def test_slave_steers_system_clock(self):
        plan = confgen.phc2sys_plan(_cfg(ptp_mode="slave"))
        self.assertEqual(plan["options"], "-a -r -m")
        self.assertTrue(plan["nocontrol"])

    def test_auto_keeps_slave_semantics_with_hint(self):
        plan = confgen.phc2sys_plan(_cfg(ptp_mode="auto"))
        self.assertEqual(plan["options"], "-a -r -m")
        self.assertTrue(plan["nocontrol"])
        self.assertTrue(any("Grandmaster" in note for note in plan["notes"]))

    def test_disabled_or_no_ptp(self):
        plan = confgen.phc2sys_plan(_cfg(phc2sys_enable=False, ptp_mode="master"))
        self.assertFalse(plan["start"])
        self.assertFalse(plan["nocontrol"])
        self.assertTrue(any("frei" in note for note in plan["notes"]))
        plan = confgen.phc2sys_plan(_cfg(ptp_enable=False))
        self.assertEqual((plan["start"], plan["nocontrol"]), (False, False))
        plan = confgen.phc2sys_plan(_cfg(ptp_interface=""))
        self.assertFalse(plan["start"])

    def test_software_timestamping(self):
        plan = confgen.phc2sys_plan(_cfg(ptp_time_stamping="software", ptp_mode="slave"))
        self.assertFalse(plan["start"])
        self.assertTrue(plan["nocontrol"])  # ptp4l stellt die Systemuhr selbst
        plan = confgen.phc2sys_plan(_cfg(ptp_time_stamping="software", ptp_mode="master"))
        self.assertEqual((plan["start"], plan["nocontrol"]), (False, False))

    def test_custom_options(self):
        cases = {
            # "-a -r -m" genau ist der alte Standard und gilt als Grandmaster als
            # "automatisch" (test_legacy_default_in_master_is_automatic); gleiche
            # Optionen in anderer Reihenfolge bleiben eigene Optionen.
            "-a -r": True, "-a -m -r": True, "-a -rr -m": False, "-a -r -r": False,
            "-s eth0 -c CLOCK_REALTIME -w": True, "-s eth0 -w": True,
            "-s CLOCK_REALTIME -c eth0 -O 37": False, "-a -rr -c CLOCK_REALTIME": True,
        }
        for options, expected in cases.items():
            with self.subTest(options=options):
                plan = confgen.phc2sys_plan(_cfg(ptp_mode="master", phc2sys_options=options))
                self.assertEqual(plan["options"], options)
                self.assertEqual(plan["nocontrol"], expected)
                # Stellt phc2sys als Grandmaster die Systemuhr, muss das laut im Log stehen.
                self.assertEqual(any(n.startswith("WARNUNG") for n in plan["notes"]), expected)

    def test_legacy_default_in_master_is_automatic(self):
        for legacy in ("-a -r -m", "  -a  -r   -m "):
            with self.subTest(legacy=legacy):
                plan = confgen.phc2sys_plan(_cfg(ptp_mode="master", phc2sys_options=legacy))
                self.assertEqual(plan["options"], "-a -rr -m")
                self.assertFalse(plan["nocontrol"])  # chronyd regelt weiter nach GPS/NTP
                self.assertTrue(any("alte Standard" in n for n in plan["notes"]))
                self.assertFalse(any(n.startswith("WARNUNG") for n in plan["notes"]))
        # Als Slave ist "-a -r -m" weiter genau richtig und bleibt unverändert.
        plan = confgen.phc2sys_plan(_cfg(ptp_mode="slave", phc2sys_options="-a -r -m"))
        self.assertEqual((plan["options"], plan["nocontrol"]), ("-a -r -m", True))
        self.assertEqual(plan["notes"], [])

    def test_phc_refclock_skipped_as_master_with_phc2sys(self):
        def render(**over):
            warnings = []
            # leapseclist aus dem Fixture: ohne tzdata im Image käme sonst eine Warnung dazu
            leap_list = str(Path(__file__).resolve().parent / "fixtures" / "leap-seconds.list")
            text = confgen.render_chrony(_cfg(phc_refclock="/dev/null", leapseclist=leap_list, **over), {},
                                         warn=lambda *a: warnings.append(a))
            return text, warnings
        text, warnings = render(ptp_mode="master")
        self.assertNotIn("refclock PHC", text)
        self.assertTrue(any("WARNUNG" in w[1] and "/dev/null" in w[1] for w in warnings))
        text, warnings = render(ptp_mode="slave")
        self.assertIn("refclock PHC /dev/null", text)
        self.assertEqual(warnings, [])
        # Ohne phc2sys gibt es keine Rückkopplung in die PHC.
        text, _ = render(ptp_mode="master", phc2sys_enable=False)
        self.assertIn("refclock PHC /dev/null", text)

    def test_rr_accepted_by_validation(self):
        self.assertEqual(settings.validate({"phc2sys_options": "-a -rr -m"})["phc2sys_options"],
                         "-a -rr -m")
        with self.assertRaises(settings.ValidationError):
            settings.validate({"phc2sys_options": "-a -r; rm -rf /"})

    def test_domain_uds_and_gptp_are_passed_to_phc2sys(self):
        plan = confgen.phc2sys_plan(_cfg(ptp_mode="master", ptp_domain=24, ptp_profile="gptp"),
                                    {"PTP_UDS_ADDRESS": "/run/ptp/ptp4l"})
        self.assertEqual(plan["options"],
                         "-a -rr -m -n 24 -z /run/ptp/ptp4l --transportSpecific=1")

    def test_apply_exports(self):
        env = {"PTP_ENABLE": "true", "PTP_INTERFACE": "eth0", "PTP_MODE": "master",
               "PHC2SYS_ENABLE": "true", "NTP_POOLS": "", "GPS_WAIT_SECONDS": "0"}
        with mock.patch.object(confgen, "CHRONY_CONF", os.path.join(self.tmp, "chrony.conf")), \
                mock.patch.object(confgen, "PTP4L_CONF", os.path.join(self.tmp, "ptp4l.conf")), \
                mock.patch.object(confgen, "CUSTOM_CHRONY", os.path.join(self.tmp, "none")), \
                mock.patch.object(confgen, "CUSTOM_PTP4L", os.path.join(self.tmp, "none")), \
                mock.patch.object(confgen, "_log"):
            out = confgen.apply(env)
            self.assertEqual(out["NTPGUI_PHC2SYS_OPTIONS"], "-a -rr -m")
            self.assertEqual(out["NTPGUI_CHRONY_NOCONTROL"], "0")
            self.assertEqual(out["NTPGUI_PHC2SYS_START"], "1")
            out = confgen.apply(dict(env, PTP_MODE="slave"))
            self.assertEqual(out["NTPGUI_CHRONY_NOCONTROL"], "1")
            # Bisherige Env-Variable bleibt gültig.
            out = confgen.apply(dict(env, PHC2SYS_OPTIONS="-a -r"))
            self.assertEqual((out["NTPGUI_PHC2SYS_OPTIONS"], out["NTPGUI_CHRONY_NOCONTROL"]),
                             ("-a -r", "1"))


class HomelabOptionTests(Phc2sysPlanTests):
    def chrony(self, env):
        warnings = []
        text = confgen.render_chrony(settings.values(env), env, warn=lambda *a: warnings.append(a))
        return text, warnings

    def test_local_orphan(self):
        text, _ = self.chrony({"LOCAL_ORPHAN": "true"})
        self.assertIn("local stratum 10 orphan", text)
        text, _ = self.chrony({})
        self.assertIn("local stratum 10\n", text)
        text, warnings = self.chrony({"LOCAL_ORPHAN": "true", "SERVE_UNSYNCED": "false"})
        self.assertNotIn("local stratum", text)
        self.assertTrue(warnings)

    def test_pps_options_from_env_and_gui(self):
        env = {"GPS_ENABLE": "true", "GPS_DEVICE": "/dev/null", "GPS_PPS_DEVICE": "/dev/zero",
               "GPS_PPS_POLL": "4", "GPS_PPS_OPTIONS": "prefer trust"}
        text, _ = self.chrony(env)
        self.assertIn("refclock PPS /dev/zero lock GPS refid PPS poll 4 prefer trust", text)
        settings.save({"gps_pps_options": "offset 0.0000025", "gps_pps_poll": 2})
        text, _ = self.chrony(env)
        self.assertIn("refclock PPS /dev/zero lock GPS refid PPS poll 2 offset 0.0000025", text)

    def test_pps_options_validation(self):
        for bad in ("refid X", "poll 3", "lock GPS", "prefer\nallow all", "bogus 1"):
            with self.subTest(bad=bad), self.assertRaises(settings.ValidationError):
                settings.validate({"gps_pps_options": bad})
        # Ungültige Env-Werte fallen mit Fehlermeldung auf den Standard zurück.
        eff = settings.effective({"GPS_PPS_OPTIONS": "refid X"})["gps_pps_options"]
        self.assertEqual(eff["value"], "")
        self.assertTrue(eff["error"])

    def test_ptp_interval_fields_from_env(self):
        env = {"PTP_LOG_ANNOUNCE_INTERVAL": "0", "PTP_LOG_MIN_DELAY_REQ_INTERVAL": "-4",
               "PTP_ANNOUNCE_RECEIPT_TIMEOUT": "4"}
        text = confgen.render_ptp4l(_cfg(**{k: v for k, v in settings.values(env).items()
                                            if k.startswith("ptp_log") or k.startswith("ptp_ann")}), env)
        self.assertRegex(text, r"logAnnounceInterval\s+0\n")
        self.assertRegex(text, r"logMinDelayReqInterval\s+-4\n")
        self.assertRegex(text, r"announceReceiptTimeout\s+4\n")
        with self.assertRaises(settings.ValidationError):
            settings.validate({"ptp_log_announce_interval": 9})

    def test_defaults_unchanged(self):
        text = confgen.render_ptp4l(_cfg(), {})
        for pattern in (r"logAnnounceInterval\s+1\n", r"logMinDelayReqInterval\s+-3\n",
                        r"announceReceiptTimeout\s+3\n", r"network_transport\s+UDPv4\n",
                        r"delay_mechanism\s+E2E\n", r"priority1\s+128\n"):
            self.assertRegex(text, pattern)
        self.assertNotIn("transportSpecific", text)
        self.assertNotIn("dscp", text)

    def test_gptp_profile(self):
        text = confgen.render_ptp4l(_cfg(ptp_profile="gptp"), {})
        for pattern in (r"network_transport\s+L2\n", r"delay_mechanism\s+P2P\n",
                        r"transportSpecific\s+0x1\n", r"gmCapable\s+1\n", r"priority1\s+248\n",
                        r"logAnnounceInterval\s+0\n", r"ptp_dst_mac\s+01:80:C2:00:00:0E\n",
                        r"follow_up_info\s+1\n", r"path_trace_enabled\s+1\n"):
            self.assertRegex(text, pattern)
        # Ein ausdrücklich gesetzter Wert gewinnt gegen das Profil.
        text = confgen.render_ptp4l(_cfg(ptp_profile="gptp", ptp_priority1=100), {})
        self.assertRegex(text, r"priority1\s+100\n")

    def test_aes67_profile(self):
        text = confgen.render_ptp4l(_cfg(ptp_profile="aes67"), {})
        for pattern in (r"network_transport\s+UDPv4\n", r"delay_mechanism\s+E2E\n",
                        r"logSyncInterval\s+-3\n", r"logAnnounceInterval\s+1\n",
                        r"dscp_event\s+46\n", r"dscp_general\s+46\n", r"domainNumber\s+0\n"):
            self.assertRegex(text, pattern)

    def test_hotplug_paths(self):
        cfg = settings.values({"GPS_ENABLE": "true", "GPS_DEVICE": "/dev/ttyACM-fehlt",
                               "GPS_PPS_DEVICE": "/dev/pps-fehlt"})
        self.assertEqual(confgen.hotplug_paths(cfg), ["/dev/ttyACM-fehlt", "/dev/pps-fehlt"])
        cfg = settings.values({"GPS_ENABLE": "true", "GPS_DEVICE": "/dev/null"})
        self.assertEqual(confgen.hotplug_paths(cfg), [])
        cfg = settings.values({"GPS_ENABLE": "false", "GPS_DEVICE": "/dev/ttyACM-fehlt"})
        self.assertEqual(confgen.hotplug_paths(cfg), [])

    @unittest.skipUnless(shutil.which("ptp4l"), "ptp4l nicht installiert")
    def test_ptp4l_accepts_profiles(self):
        import subprocess
        for profile in ("default", "aes67", "gptp"):
            with self.subTest(profile=profile):
                text = confgen.render_ptp4l(_cfg(ptp_profile=profile, ptp_interface="lo",
                                                 ptp_time_stamping="software"),
                                            {"PTP_UDS_ADDRESS": os.path.join(self.tmp, f"u-{profile}")})
                conf = Path(self.tmp, f"{profile}.conf")
                conf.write_text(text)
                # Ungültige Schlüssel lässt ptp4l sofort mit Fehler enden; gültige
                # Konfiguration läuft, bis das Timeout greift (Exit 124).
                proc = subprocess.run(["timeout", "2", "ptp4l", "-f", str(conf), "-i", "lo", "-q"],
                                      capture_output=True, text=True)
                self.assertNotIn("failed to parse configuration", proc.stderr + proc.stdout)
                self.assertNotIn("unknown option", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
