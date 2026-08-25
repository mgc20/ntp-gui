"""Parser tests against real chronyc / pmc output."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import chrony  # noqa: E402
import gps  # noqa: E402
import ptp  # noqa: E402

# chronyc -c tracking, chrony 4.5, synchronised to an upstream server.
TRACKING_SYNCED = (
    "C0248F97,192.53.103.108,2,1787650421.510570863,0.000012345,-0.000004321,"
    "0.000031000,-12.345,0.002,0.150,0.012300000,0.000450000,64.0,Normal\n"
)
# Same command while chrony only serves its own clock ("local stratum 10").
TRACKING_LOCAL = (
    "7F7F0101,,10,1787650421.510570863,0.000000000,0.000000000,0.000000000,"
    "0.000,0.000,0.000,0.000000000,0.000000000,0.0,Normal\n"
)
SOURCES = (
    "^,*,192.53.103.108,2,6,377,23,0.000012345,0.000012000,0.000230000\n"
    "^,?,15.204.246.57,0,6,0,4294967295,0.000000000,0.000000000,0.000000000\n"
    "^,+,162.159.200.1,3,7,177,41,-0.000101000,-0.000099000,0.000410000\n"
)
SOURCESTATS = (
    "192.53.103.108,12,7,776,-0.031,0.421,0.000009000,0.000021000\n"
    "15.204.246.57,0,0,0,0.000,2000.000,0.000000000,4.000000000\n"
)
# chronyc -c clients: unset columns are encoded as 127 (interval) and 2^32-1 (last).
CLIENTS = (
    "192.168.1.24,1042,0,6,127,12,0,0,127,4294967295\n"
    "192.168.1.99,17,2,10,127,4294967295,0,0,127,4294967295\n"
)
SERVERSTATS = """NTP packets received       : 154213
NTP packets dropped        : 12
Command packets received   : 30
NTS-KE connections accepted: 0
NTP hardware RX timestamps : 0
"""
ACTIVITY = "4,0,2,0,1\n"

PMC_TIME_STATUS = """sending: GET TIME_STATUS_NP
\t000c29.fffe.abc123-1 seq 0 RESPONSE MANAGEMENT TIME_STATUS_NP
\t\tmaster_offset              -137
\t\tingress_time               1787650421510570863
\t\tcumulativeScaledRateOffset +0.000000000
\t\tgmPresent                  true
\t\tgmIdentity                 001b19.fffe.001122
"""
PMC_PORT = """sending: GET PORT_DATA_SET
\t000c29.fffe.abc123-1 seq 0 RESPONSE MANAGEMENT PORT_DATA_SET
\t\tportIdentity            000c29.fffe.abc123-1
\t\tportState               SLAVE
\t\tlogSyncInterval         -3
"""


class TestTracking(unittest.TestCase):
    def test_synced_source(self):
        tracking = chrony.parse_tracking(TRACKING_SYNCED)
        self.assertEqual(tracking["ref_name"], "192.53.103.108")
        self.assertEqual(tracking["stratum"], 2)
        self.assertAlmostEqual(tracking["system_time_offset"], 1.2345e-05)
        self.assertAlmostEqual(tracking["frequency_ppm"], -12.345)
        self.assertAlmostEqual(tracking["root_dispersion"], 0.00045)
        self.assertEqual(tracking["leap_status"], "Normal")
        self.assertTrue(tracking["synchronised"])
        self.assertFalse(tracking["local_reference"])

    def test_local_reference_is_not_synchronised(self):
        tracking = chrony.parse_tracking(TRACKING_LOCAL)
        self.assertTrue(tracking["local_reference"])
        self.assertFalse(tracking["synchronised"])

    def test_empty_output(self):
        self.assertEqual(chrony.parse_tracking(""), {})


class TestSources(unittest.TestCase):
    def setUp(self):
        self.sources = chrony.parse_sources(SOURCES)

    def test_row_count_and_labels(self):
        self.assertEqual(len(self.sources), 3)
        self.assertEqual(self.sources[0]["state_label"], "synced")
        self.assertEqual(self.sources[0]["mode_label"], "server")
        self.assertEqual(self.sources[1]["state_label"], "unreachable")
        self.assertEqual(self.sources[2]["state_label"], "combined")

    def test_reach_percentage(self):
        self.assertEqual(self.sources[0]["reach_percent"], 100)  # 377 octal = 8 of 8 polls
        self.assertEqual(self.sources[1]["reach_percent"], 0)
        self.assertEqual(self.sources[2]["reach_percent"], 88)  # 177 octal = 7 of 8

    def test_never_received_sentinel(self):
        self.assertEqual(self.sources[0]["last_rx"], 23)
        self.assertIsNone(self.sources[1]["last_rx"])

    def test_negative_offset(self):
        self.assertAlmostEqual(self.sources[2]["offset"], -0.000101)


class TestSourcestats(unittest.TestCase):
    def test_fields(self):
        stats = chrony.parse_sourcestats(SOURCESTATS)
        self.assertEqual(stats[0]["samples"], 12)
        self.assertEqual(stats[0]["span"], 776)
        self.assertAlmostEqual(stats[0]["std_dev"], 2.1e-05)


class TestClients(unittest.TestCase):
    def test_fields_and_sentinel(self):
        clients = chrony.parse_clients(CLIENTS)
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0]["address"], "192.168.1.24")
        self.assertEqual(clients[0]["ntp_packets"], 1042)
        self.assertEqual(clients[0]["ntp_last_rx"], 12)
        self.assertEqual(clients[1]["ntp_dropped"], 2)
        self.assertIsNone(clients[1]["ntp_last_rx"])

    def test_placeholder_columns_become_none(self):
        client = chrony.parse_clients(CLIENTS)[0]
        self.assertIsNone(client["cmd_interval"])
        self.assertIsNone(client["cmd_last_rx"])
        self.assertEqual(client["ntp_interval"], 6)


class TestServerstats(unittest.TestCase):
    def test_label_parsing(self):
        stats = chrony.parse_serverstats(SERVERSTATS)
        self.assertEqual(stats["ntp_packets_received"], 154213)
        self.assertEqual(stats["ntp_packets_dropped"], 12)
        self.assertEqual(stats["nts_ke_connections_accepted"], 0)
        self.assertEqual(stats["ntp_hardware_rx_timestamps"], 0)


class TestActivity(unittest.TestCase):
    def test_counters(self):
        activity = chrony.parse_activity(ACTIVITY)
        self.assertEqual(activity["online"], 4)
        self.assertEqual(activity["burst_online"], 2)
        self.assertEqual(activity["unresolved"], 1)
        self.assertEqual(activity["total"], 6)


class TestPmc(unittest.TestCase):
    def test_time_status(self):
        values = ptp.parse_pmc_output(PMC_TIME_STATUS)
        self.assertEqual(values["master_offset"], "-137")
        self.assertEqual(values["gmPresent"], "true")
        self.assertEqual(values["gmIdentity"], "001b19.fffe.001122")
        self.assertNotIn("sending", values)

    def test_port_state(self):
        values = ptp.parse_pmc_output(PMC_PORT)
        self.assertEqual(values["portState"], "SLAVE")
        self.assertEqual(values["portIdentity"], "000c29.fffe.abc123-1")

    def test_empty(self):
        self.assertEqual(ptp.parse_pmc_output(""), {})


# gpsd 3.25 reports, captured from a running daemon.
GPSD_VERSION = {"class": "VERSION", "release": "3.25", "rev": "3.25"}
GPSD_DEVICES = {"class": "DEVICES", "devices": [
    {"class": "DEVICE", "path": "/dev/ttyACM0", "driver": "NMEA0183", "bps": 38400}]}
GPSD_TPV = {"class": "TPV", "device": "/dev/ttyACM0", "mode": 3,
            "time": "2026-08-25T10:03:11.030Z", "ept": 0.005,
            "lat": 48.137333333, "lon": 11.575, "alt": 519.0, "altHAE": 566.3}
GPSD_SKY_DETAILED = {"class": "SKY", "device": "/dev/ttyACM0", "hdop": 0.89, "pdop": 1.72,
                     "vdop": 1.47, "uSat": 8, "nSat": 11, "satellites": [
                         {"PRN": 1, "ss": 42, "used": True},
                         {"PRN": 2, "ss": 40, "used": True},
                         {"PRN": 3, "ss": 22, "used": False}]}
# Some gpsd cycles carry no satellite list at all.
GPSD_SKY_BARE = {"class": "SKY", "device": "/dev/ttyACM0", "hdop": 0.89, "uSat": 8}


class TestGps(unittest.TestCase):
    def test_full_reports(self):
        state = gps.parse_reports({"VERSION": GPSD_VERSION, "DEVICES": GPSD_DEVICES,
                                   "TPV": GPSD_TPV, "SKY": GPSD_SKY_DETAILED})
        self.assertTrue(state["running"])
        self.assertTrue(state["has_fix"])
        self.assertEqual(state["mode_label"], "3D-Fix")
        self.assertEqual(state["device"], "/dev/ttyACM0")
        self.assertEqual(state["driver"], "NMEA0183")
        self.assertEqual(state["satellites_used"], 8)
        self.assertEqual(state["satellites_seen"], 11)
        self.assertEqual(state["hdop"], 0.89)
        self.assertEqual(state["snr_max"], 42)
        self.assertEqual(state["snr_avg"], 41.0)  # only the used satellites count

    def test_sky_without_satellite_list(self):
        # nSat missing must not report "0 of 8 satellites".
        state = gps.parse_reports({"TPV": GPSD_TPV, "SKY": GPSD_SKY_BARE})
        self.assertEqual(state["satellites_used"], 8)
        self.assertEqual(state["satellites_seen"], 8)

    def test_detailed_sky_wins(self):
        self.assertTrue(gps._sky_is_detailed(GPSD_SKY_DETAILED))
        self.assertFalse(gps._sky_is_detailed(GPSD_SKY_BARE))
        self.assertFalse(gps._sky_is_detailed(None))

    def test_no_fix(self):
        state = gps.parse_reports({"TPV": {"class": "TPV", "mode": 1}, "SKY": {"class": "SKY", "uSat": 0}})
        self.assertFalse(state["has_fix"])
        self.assertEqual(state["mode_label"], "kein Fix")

    def test_gpsd_unreachable(self):
        state = gps.parse_reports({})
        self.assertFalse(state["running"])
        self.assertFalse(state["has_fix"])

    def test_position_hidden_by_default(self):
        os.environ.pop("GPS_SHOW_POSITION", None)
        self.assertNotIn("lat", gps.parse_reports({"TPV": GPSD_TPV}))
        os.environ["GPS_SHOW_POSITION"] = "true"
        try:
            self.assertIn("lat", gps.parse_reports({"TPV": GPSD_TPV}))
        finally:
            os.environ.pop("GPS_SHOW_POSITION", None)


class TestRefclockSource(unittest.TestCase):
    """A GPS refclock shows up as mode '#' in chronyc sources."""

    def test_refclock_row(self):
        row = chrony.parse_sources("#,*,GPS,0,3,377,3,0.000000000,-0.001499888,0.200000003\n")[0]
        self.assertEqual(row["mode_label"], "refclock")
        self.assertEqual(row["state_label"], "synced")
        self.assertEqual(row["reach_percent"], 100)
        self.assertAlmostEqual(row["original_offset"], -0.001499888)


class TestEnvNumber(unittest.TestCase):
    """A typo in a compose file must never crash the container."""

    def setUp(self):
        import server
        self.env_number = server.env_number
        os.environ.pop("NTPGUI_TESTVAR", None)

    def tearDown(self):
        os.environ.pop("NTPGUI_TESTVAR", None)

    def test_unset_returns_default(self):
        self.assertEqual(self.env_number("NTPGUI_TESTVAR", 720, int), 720)

    def test_valid_value(self):
        os.environ["NTPGUI_TESTVAR"] = " 42 "
        self.assertEqual(self.env_number("NTPGUI_TESTVAR", 720, int), 42)

    def test_garbage_falls_back(self):
        os.environ["NTPGUI_TESTVAR"] = "zwölf"
        self.assertEqual(self.env_number("NTPGUI_TESTVAR", 720, int), 720)

    def test_empty_falls_back(self):
        os.environ["NTPGUI_TESTVAR"] = "   "
        self.assertEqual(self.env_number("NTPGUI_TESTVAR", 5.0, float), 5.0)

    def test_minimum_is_enforced(self):
        os.environ["NTPGUI_TESTVAR"] = "-3"
        self.assertEqual(self.env_number("NTPGUI_TESTVAR", 10.0, float, minimum=1.0), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
