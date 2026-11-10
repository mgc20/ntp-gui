"""Zentraler Datenschutzfilter (app/egress.py): realistische Daten und gemeine Fälle.

Grundsatz: Aus nichts, was die Instanz verlässt, darf sich ein Standort bestimmen
oder ein Gerät wiedererkennen lassen. Jede Prüfung hier hat zwei Seiten: Das
Sensible verschwindet – und das Nützliche (Fix-Modus, DOP, SNR, PRN, Offsets,
Dateinamen, bekannte Zeitserver) bleibt.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import egress  # noqa: E402

LAT, LON = 48.1371543, 11.5761249


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


GPS_STATUS = {
    "enabled": True, "running": True, "gpsd_release": "3.22", "device": "/dev/ttyACM0",
    "driver": "u-blox", "baud": 9600, "mode": 3, "mode_label": "3D-Fix", "has_fix": True,
    "time": "2026-11-01T10:00:00.000Z", "time_error": 0.005,
    "lat": LAT, "lon": LON, "alt": 519.3, "altHAE": 566.8, "altMSL": 519.3,
    "speed": 0.021, "track": 213.4, "climb": -0.01, "eph": 2.1, "epv": 3.4,
    "satellites_used": 9, "satellites_seen": 14, "hdop": 0.86, "pdop": 1.42, "vdop": 1.13,
    "gdop": 1.6, "tdop": 0.8, "xdop": 0.5, "ydop": 0.6, "leapseconds": 18, "snr_avg": 38.4, "snr_max": 45,
    "satellites": [
        {"prn": 5, "system": "GPS", "svid": 5, "elevation": 62, "azimuth": 288, "snr": 45, "used": True, "health": 1},
        {"prn": 67, "system": "GLONASS", "svid": 3, "elevation": 12.5, "azimuth": 41.0, "snr": 21, "used": False,
         "health": 1},
    ],
    "systems": {"GPS": {"seen": 8, "used": 6}, "GLONASS": {"seen": 6, "used": 3}},
    "pps": "/dev/pps0",
}

TPV = {"class": "TPV", "device": "/dev/ttyACM0", "status": 2, "mode": 3, "time": "2026-11-01T10:00:00.000Z",
       "leapseconds": 18, "ept": 0.005, "lat": LAT, "lon": LON, "altHAE": 566.8, "altMSL": 519.3,
       "alt": 519.3, "epx": 3.1, "epy": 4.2, "epv": 5.0, "track": 213.4, "magtrack": 216.0, "magvar": 3.1,
       "speed": 0.021, "climb": -0.01, "eps": 0.6, "epc": 1.0, "geoidSep": 47.5, "eph": 4.8, "sep": 7.1,
       "ecefx": 4177632.1, "ecefy": 855543.3, "ecefz": 4728013.2, "ecefpAcc": 5.0, "velN": 0.01,
       "velE": -0.02, "velD": 0.0, "dgpsSta": 451}
SKY = {"class": "SKY", "device": "/dev/ttyACM0", "time": "2026-11-01T10:00:00.000Z", "xdop": 0.5, "ydop": 0.6,
       "vdop": 1.1, "tdop": 0.8, "hdop": 0.9, "gdop": 1.6, "pdop": 1.4, "nSat": 14, "uSat": 9,
       "satellites": [{"PRN": 5, "gnssid": 0, "svid": 5, "el": 62.0, "az": 288.0, "ss": 45.0, "used": True,
                       "health": 1},
                      {"PRN": 21, "gnssid": 0, "svid": 21, "el": 7.0, "az": 120.0, "ss": 18.0, "used": False}]}

HARDWARE = {
    "platform": {"container": "docker", "arch": "x86_64", "hypervisor": None,
                 "dmi": {"sys_vendor": "LENOVO", "product_name": "ThinkCentre M720q",
                         "product_serial": "PC1ABCDE", "board_serial": "L1HF9AB00XY", "product_uuid":
                         "4c4c4544-0042-3510-8051-b4c04f4a4d32"},
                 "summary": "LENOVO ThinkCentre M720q · Docker · Host-Netz"},
    "gps": {"receivers": [
        {"tty": "ttyUSB0", "dev": "/dev/ttyUSB0",
         "stable_path": "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0",
         "usb": {"vid": "0403", "pid": "6001", "manufacturer": "FTDI", "product": "FT232R USB UART",
                 "serial": "A50285BI"},
         "verdict": "Dein Empfänger: FT232R über USB-Seriell-Adapter (FTDI)."},
        {"tty": "ttyACM0", "dev": "/dev/ttyACM0",
         "stable_path": "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00",
         "usb": {"vid": "1546", "pid": "01a7"}},
    ]},
    "ptp": {"clocks": [{"name": "enp3s0", "mac": "00:1b:21:aa:bb:cc", "phc": "/dev/ptp0",
                        "clock_identity": "001b21.fffe.aabbcc"}]},
    "interfaces": [{"name": "enp3s0", "address": "00:1B:21:AA:BB:CC", "speed": 1000, "speed_mbit": 1000}],
}

CHRONY_TEXT = """Reference ID    : C035676C (ptbtime1.ptb.de)
Stratum         : 2
Ref time (UTC)  : Sun Nov 01 10:00:00 2026
System time     : 0.000001234 seconds fast of NTP time
Last offset     : -0.000000876 seconds
RMS offset      : 0.000012345 seconds
Frequency       : 12.345 ppm slow
Root delay      : 0.012345678 seconds
Leap status     : Normal
MS Name/IP address         Stratum Poll Reach LastRx Last sample
===============================================================================
^* 192.53.103.108                1   6   377    34   -12us[  -13us] +/-   11ms
^+ 162.159.200.1                 3   6   377    35   +45us[  +44us] +/-   10ms
^- 192.168.1.1                 2   6   377    36  +120us[ +119us] +/-   20ms
^- 2a00:1450:c17:1234::1          2   6   377    36  +120us[ +119us] +/-   20ms
#* GPS                           0   4   377    12   +1us[   +1us] +/-  100ns
Remote address  : 2a00:1450:c17:1234::1 (2A001450)
"""


class PositionTest(unittest.TestCase):
    def test_gps_status_keeps_quality_drops_position(self):
        clean, report = egress.sanitize(GPS_STATUS, "diagnostics")
        for key in ("lat", "lon", "alt", "altHAE", "altMSL", "speed", "track", "climb", "eph", "epv"):
            self.assertNotIn(key, clean)
        for key in ("mode", "has_fix", "satellites_used",
                    "satellites_seen", "snr_avg", "time", "leapseconds", "systems", "pps"):
            self.assertEqual(clean[key], GPS_STATUS[key], key)
        # Diagnose 1.6.0: HDOP bleibt (auf eine Stelle), richtungsabhängige gehen; 2306 auch PDOP/GDOP
        # (aus ihnen wären VDOP/TDOP rückrechenbar).
        self.assertEqual(clean["hdop"], round(GPS_STATUS["hdop"], 1))
        for key in ("xdop", "ydop", "vdop", "tdop", "pdop", "gdop"):
            self.assertNotIn(key, clean)
        # Keine Einzelsatelliten (PRN) mehr – die sichtbare Menge zu einer Zeit grenzt die Region ein.
        self.assertNotIn("prn", json.dumps(clean["satellites"]))
        self.assertEqual(clean["satellites"]["je_system"]["GPS"]["benutzt"], 1)
        self.assertGreaterEqual(report["removed"]["satellitenliste"], 1)
        self.assertGreaterEqual(report["removed"]["position"], 5)
        self.assertEqual(report["removed"]["satellitenwinkel"], 4)
        self.assertEqual(report["removed"]["bewegung"], 3)
        self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertTrue(egress.check_no_leaks(GPS_STATUS))

    def test_gpsd_tpv_allowlist(self):
        clean, _ = egress.sanitize(TPV, "recording")
        self.assertEqual(set(clean), {"class", "device", "status", "mode", "time", "leapseconds", "ept"})

    def test_gpsd_sky_keeps_only_per_system_sums(self):
        clean, report = egress.sanitize(SKY, "recording")
        self.assertNotIn("PRN", json.dumps(clean))
        self.assertNotIn("svid", json.dumps(clean))
        # Aufzeichnung (Zeitreihe, 2306): keine Zählwerte, die mit Auf- und Untergängen springen.
        self.assertEqual(clean["satellites"]["je_system"]["GPS"], {"snr_max": 45})
        self.assertNotIn("uSat", clean)
        gps = egress.sanitize(SKY, "diagnostics")[0]["satellites"]["je_system"]["GPS"]
        self.assertEqual(gps["empfangen"], len(SKY["satellites"]))
        self.assertEqual(gps["snr_max"], 45)
        self.assertEqual(clean["hdop"], 0.9)
        self.assertEqual(report["removed"]["satellitenwinkel"], 4)

    def test_gpsd_raw_lines_in_recording(self):
        lines = [json.dumps(TPV), json.dumps(SKY),
                 json.dumps({"class": "GST", "device": "/dev/ttyACM0", "time": "x", "rms": 1.5, "major": 3.1,
                             "minor": 2.2, "orient": 12.0, "lat": 2.1, "lon": 1.8, "alt": 3.3}),
                 json.dumps({"class": "RTCM3", "type": 1005, "station_id": 12, "x": 4177632.1}),
                 json.dumps({"class": "POLL", "time": "x", "tpv": [TPV], "sky": [SKY]}),
                 json.dumps({"class": "PPS", "device": "/dev/pps0", "real_sec": 1, "real_nsec": 0,
                             "clock_sec": 1, "clock_nsec": 120}),
                 "keine JSON-Zeile mit lat=48.1371543 und lon=11.5761249"]
        clean, _ = egress.sanitize_text("\n".join(lines), "recording")
        self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertNotIn("48.13", clean)
        self.assertNotIn("4177632", clean)
        parsed = [json.loads(line) for line in clean.splitlines()[:6]]
        self.assertEqual(parsed[2], {"class": "GST", "device": "/dev/ttyACM0", "time": "x", "rms": 1.5})
        self.assertEqual(parsed[3]["class"], "RTCM3")
        self.assertNotIn("station_id", parsed[3])
        self.assertNotIn("lat", parsed[4]["tpv"][0])
        self.assertEqual(parsed[5]["clock_nsec"], 120)

    def test_recording_wrapper_with_embedded_gpsd_line(self):
        # Aufzeichnungen speichern gpsd-Zeilen als String in einem JSON-Objekt.
        rec = json.dumps({"t": 1, "kind": "gpsd", "line": json.dumps(TPV)})
        clean, _ = egress.sanitize_text(rec, "recording")
        self.assertNotIn("48.137", clean)
        self.assertEqual(egress.check_no_leaks(clean), [])

    def test_coordinates_in_free_text(self):
        cases = [
            f"Standort {LAT}, {LON} im Keller",
            f"pos={LAT};{LON}",
            "51.5074, -0.1278",                       # London: Länge nahe 0
            "-33.8688 151.2093",                      # Sydney, Leerzeichen
            "48.137154 N, 11.576124 E",
            "48.137154° N 11.576124° E",
            "48°08'13.8\"N 11°34'34.0\"E",
            "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
            "$GNRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
            "lat: 48.1, lon: 11.5, alt=520",
            "'latitude': 48.137154, 'longitude': 11.576124",
            "Elevation=45 Azimuth: 120",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(egress.check_no_leaks(text), "ungefiltert muss es auffallen")
                clean, _ = egress.sanitize_text(text, "community")
                self.assertEqual(egress.check_no_leaks(clean), [], clean)
                self.assertNotIn("48.13", clean)
                self.assertNotIn("4807.038", clean)

    def test_no_false_coordinates(self):
        harmless = [
            "System time     : 0.000001234 seconds fast of NTP time",
            "Frequency       : 12.345 ppm slow",
            "offset 0.0001234, 0.0002345 jitter",      # beide < 1: keine Koordinate
            "Version 4.3, Python 3.11.2",
            "2026-11-01T17:53:35Z chronyd version 4.5 starting",
            "rms   12 max   25 freq  -1234 +/-  12 delay   567 +/-   3",
            "Speed: 1000Mb/s",
        ]
        for text in harmless:
            with self.subTest(text=text):
                clean, report = egress.sanitize_text(text, "community")
                self.assertEqual(clean, text)
                self.assertEqual(egress.check_no_leaks(text), [])

    def test_coordinate_list_in_structure(self):
        clean, _ = egress.sanitize({"x": [LAT, LON], "offsets": [0.0001, 0.0002]}, "diagnostics")
        self.assertEqual(clean["x"], "<koordinaten>")
        self.assertEqual(clean["offsets"], [0.0001, 0.0002])
        self.assertTrue(egress.check_no_leaks({"x": [LAT, LON]}))

    def test_mixed_case_and_nested_keys(self):
        data = {"Device": {"Position": {"Lat": LAT, "LON": LON}, "ALT_HAE": 500.1},
                "list": [[{"Latitude": LAT}], {"nested": {"Azimuth": 12, "EL": 4}}]}
        self.assertGreaterEqual(len(egress.check_no_leaks(data)), 3)
        clean, _ = egress.sanitize(data, "diagnostics")
        self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertNotIn("48.13", dump(clean))

    def test_nic_speed_is_not_motion(self):
        clean, _ = egress.sanitize({"interfaces": [{"name": "eth0", "speed": 1000}]}, "community")
        self.assertEqual(clean["interfaces"][0]["speed"], 1000)


class IdentifierTest(unittest.TestCase):
    def test_hardware_report(self):
        clean, report = egress.sanitize(HARDWARE, "community")
        text = dump(clean)
        for secret in ("PC1ABCDE", "L1HF9AB00XY", "4c4c4544", "A50285BI", "aa:bb:cc", "AA:BB:CC", "aabbcc"):
            self.assertNotIn(secret, text)
        self.assertEqual(clean["platform"]["dmi"]["product_name"], "ThinkCentre M720q")
        recv = clean["gps"]["receivers"]
        self.assertEqual(recv[0]["stable_path"], "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_<seriennr>-if00-port0")
        # u-blox-Namen ohne Seriennummer bleiben unverändert
        self.assertEqual(recv[1]["stable_path"], HARDWARE["gps"]["receivers"][1]["stable_path"])
        self.assertEqual(recv[0]["usb"], {"vid": "0403", "pid": "6001", "manufacturer": "FTDI",
                                          "product": "FT232R USB UART"})
        self.assertEqual(clean["interfaces"][0]["address"], "<mac>")
        self.assertTrue(clean["ptp"]["clocks"][0]["clock_identity"].startswith("<uhr-id-"))
        self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertTrue(egress.check_no_leaks(HARDWARE))
        self.assertIn("seriennummer", report["removed"])

    def test_by_id_variants(self):
        cases = {
            "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0":
                "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_<seriennr>-if00-port0",
            "usb-Prolific_Technology_Inc._USB-Serial_Controller_D-if00-port0":
                "usb-Prolific_Technology_Inc._USB-Serial_Controller_D-if00-port0",
            "usb-1a86_USB_Serial-if00-port0": "usb-1a86_USB_Serial-if00-port0",
            "usb-u-blox_AG_u-blox_GNSS_receiver_0123456789ABCDEF-if00":
                "usb-u-blox_AG_u-blox_GNSS_receiver_<seriennr>-if00",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                clean, _ = egress.sanitize_text(f"GPS_DEVICE=/dev/serial/by-id/{raw}", "community")
                self.assertEqual(clean, f"GPS_DEVICE=/dev/serial/by-id/{expected}")
                self.assertEqual(egress.check_no_leaks(clean), [])

    def test_serial_in_text(self):
        clean, _ = egress.sanitize_text("product_serial: PF1ABC23\nSerial Number: 12345678\nID_SERIAL_SHORT=A50285BI",
                                        "diagnostics")
        self.assertNotIn("PF1ABC23", clean)
        self.assertNotIn("12345678", clean)
        self.assertNotIn("A50285BI", clean)
        self.assertEqual(egress.check_no_leaks(clean), [])

    def test_serial_without_separator(self):
        text = "Gerät an serial 1234ABCD9876\niSerial                 3 0042A7F1C3"
        self.assertTrue(egress.check_no_leaks(text))
        clean, report = egress.sanitize_text(text, "diagnostics")
        self.assertNotIn("1234ABCD9876", clean)
        self.assertNotIn("0042A7F1C3", clean)
        self.assertEqual(report["removed"].get("seriennummer"), 2)
        self.assertEqual(egress.check_no_leaks(clean), [])
        # Schnittstellennamen sind keine Seriennummern.
        for harmless in ("GPS on serial ttyAMA0", "serial port /dev/ttyS0", "serial 0"):
            self.assertEqual(egress.sanitize_text(harmless, "diagnostics")[0], harmless)

    def test_mac_formats(self):
        for mac in ("00:1b:21:aa:bb:cc", "00-1B-21-AA-BB-CC", "001b.21aa.bbcc"):
            with self.subTest(mac=mac):
                clean, _ = egress.sanitize_text(f"link/ether {mac} brd ff:ff:ff:ff:ff:ff", "community")
                self.assertEqual(clean, "link/ether <mac> brd ff:ff:ff:ff:ff:ff")
                self.assertEqual(egress.check_no_leaks(clean), [])
        # Multicast-Ziele der PTP-Konfiguration kennzeichnen kein Gerät
        conf = "ptp_dst_mac\t\t01:1B:19:00:00:00\np2p_dst_mac\t\t01:80:C2:00:00:0E"
        self.assertEqual(egress.sanitize_text(conf, "community")[0], conf)

    def test_ptp_clock_identity(self):
        text = ("ptp4l[12.3]: selected local clock 001b21.fffe.aabbcc as best master\n"
                "ptp4l[13.0]: port 1 (enp3s0): new foreign master 001122.fffe.334455-1\n"
                "ptp4l[14.0]: selected best master clock 001122.fffe.334455\n"
                "clockIdentity\t\t000000.0000.000000")
        clean, _ = egress.sanitize_text(text, "diagnostics")
        lines = clean.splitlines()
        self.assertIn("<uhr-id-1>", lines[0])
        self.assertIn("<uhr-id-2>", lines[1])
        self.assertIn("<uhr-id-2>", lines[2])  # derselbe Master → dasselbe Pseudonym (ohne Port-Suffix)
        self.assertIn("000000.0000.000000", lines[3])
        self.assertEqual(egress.check_no_leaks(clean), [])

    def test_secrets_and_title(self):
        data = {"values": {"web_title": "Zeitserver Familie Müller, Hauptstr. 5", "web_refresh_seconds": 5},
                "auth": {"user": "admin", "hash": "pbkdf2$..."}, "password": "geheim"}
        clean, report = egress.sanitize(data, "diagnostics")
        self.assertEqual(clean, {"values": {"web_title": "<titel>", "web_refresh_seconds": 5}})
        self.assertEqual(report["removed"]["zugangsdaten"], 2)
        default, _ = egress.sanitize({"web_title": "NTP / PTP Time Server"}, "diagnostics")
        self.assertEqual(default["web_title"], "NTP / PTP Time Server")

    def test_cert_names(self):
        status = {"enabled": True, "name": "zeit.mueller-family.de", "subject": "zeit.mueller-family.de",
                  "names": ["zeit.mueller-family.de", "ntp.mueller-family.de"],
                  "cert_issuer": "Let's Encrypt – R11", "cert": "/etc/letsencrypt/live/zeit.mueller-family.de/fullchain.pem"}
        clean, _ = egress.sanitize(status, "diagnostics")
        self.assertNotIn("mueller", dump(clean))
        self.assertEqual(clean["cert_issuer"], "Let's Encrypt – R11")
        self.assertEqual(clean["names"], ["<zertifikatsname>", "<zertifikatsname>"])
        self.assertEqual(clean["cert"], "/etc/letsencrypt/live/<hostname-1>/fullchain.pem")
        self.assertEqual(clean["name"], "<hostname-1>")  # gleicher Name → gleiches Pseudonym
        own, _ = egress.sanitize({"cert_issuer": "zeit.mueller-family.de"}, "diagnostics")
        self.assertEqual(own["cert_issuer"], "<aussteller>")

    def test_email(self):
        clean, _ = egress.sanitize_text("Kontakt: max.mustermann@example.de", "community")
        self.assertEqual(clean, "Kontakt: <e-mail>")


class AddressTest(unittest.TestCase):
    def test_chrony_output(self):
        clean, report = egress.sanitize_text(CHRONY_TEXT, "diagnostics")
        self.assertIn("Reference ID    : <refid> (ptbtime1.ptb.de)", clean)
        self.assertIn("^* <öffentliche-IP>", clean)
        self.assertIn("^- client-01", clean)
        self.assertIn("#* GPS", clean)
        self.assertNotIn("2a01", clean)
        self.assertNotIn("2A001450", clean)
        self.assertIn("RMS offset      : 0.000012345 seconds", clean)  # Messwerte bleiben
        self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertTrue(egress.check_no_leaks(CHRONY_TEXT))

    def test_refclock_refid_stays(self):
        for line in ("Reference ID    : 47505300 (GPS)", "Reference ID    : 50505300 (PPS)",
                     "Reference ID    : 7F000001 ()"):
            with self.subTest(line=line):
                self.assertEqual(egress.sanitize_text(line, "community")[0], line)
        clean, _ = egress.sanitize({"ref_id": "C035676C", "ref_name": "GPS"}, "community")
        self.assertEqual(clean, {"ref_id": "<refid>", "ref_name": "GPS"})

    def test_pseudonyms_are_stable_per_run(self):
        s = egress.Sanitizer("diagnostics")
        a = s.text("client 192.168.1.20 fragt, dann 10.0.0.5, dann wieder 192.168.1.20")
        b = s.obj({"address": "192.168.1.20", "other": "fe80::1%eth0"})
        self.assertEqual(a, "client client-01 fragt, dann client-02, dann wieder client-01")
        self.assertEqual(b, {"address": "client-01", "other": "client-03"})
        fresh, _ = egress.sanitize({"x": "10.0.0.5"}, "diagnostics")
        self.assertEqual(fresh["x"], "client-01")  # neuer Lauf, neue Zuordnung

    def test_ip_classes(self):
        cases = {
            "127.0.0.1:323": "127.0.0.1:323",
            "::1": "::1",
            "0.0.0.0": "0.0.0.0",
            "224.0.1.129": "224.0.1.129",          # PTP-Multicast
            "ff0e::181": "ff0e::181",
            "allow 192.168.0.0/16": "allow 192.168.0.0/16",
            "allow fd00::/8": "allow fd00::/8",
            "allow 100.64.0.0/10": "allow 100.64.0.0/10",
            "deny 81.2.3.0/24": "deny <öffentliche-IP>/24",
            "8.8.8.8": "<öffentliche-IP>",
            "2001:4860:4860::8888": "<öffentliche-IP>",
            "[2606:4700:1234:5600::1]:4460": "[<öffentliche-IP>]:4460",
            "::ffff:81.2.3.4": "<öffentliche-IP>",
            "100.101.102.103": "client-01",         # CGNAT/Tailscale
            "169.254.10.20": "client-01",
            "fd12:3456:789a::5": "client-01",
            "addr:2a00:1450::1": "addr:<öffentliche-IP>",     # ohne Leerzeichen davor
            "client_81.2.3.4": "client_<öffentliche-IP>",
            "Server 2a00:1450::1.": "Server <öffentliche-IP>.",  # Satzende
            "::ffff:10.1.2.3": "client-01",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                clean, _ = egress.sanitize_text(raw, "community")
                self.assertEqual(clean, expected)
                self.assertEqual(egress.check_no_leaks(clean), [])

    def test_no_false_ips(self):
        for text in ("Uhrzeit 17:53:35", "Version 1.3.0", "ptp4l[1234.567]", "dead:beef", "a::b::c"):
            with self.subTest(text=text):
                self.assertEqual(egress.sanitize_text(text, "community")[0], text)

    def test_dict_keys_with_addresses(self):
        clean, _ = egress.sanitize({"sources": {"81.2.3.4": {"o": 1e-5}, "81.2.3.5": {"o": 2e-5},
                                                "192.168.1.2": {"o": 0}}}, "diagnostics")
        self.assertEqual(sorted(clean["sources"]), ["<öffentliche-IP>", "<öffentliche-IP> (2)", "client-01"])


class HostnameTest(unittest.TestCase):
    def test_known_time_services_stay(self):
        text = ("server ptbtime1.ptb.de iburst nts\nserver time.cloudflare.com nts\npool de.pool.ntp.org\n"
                "server sth1.nts.netnod.se nts\nserver time.google.com\nserver time.nist.gov")
        self.assertEqual(egress.sanitize_text(text, "community")[0], text)

    def test_own_domains_replaced(self):
        text = "server ntp.meine-firma.de iburst\nserver nas.fritz.box\nserver drucker.local\nserver zeit.berlin"
        clean, report = egress.sanitize_text(text, "community")
        self.assertEqual(clean, "server <hostname-1> iburst\nserver <hostname-2>\nserver <hostname-3>\n"
                                "server <hostname-4>")
        self.assertEqual(report["removed"]["hostname"], 4)

    def test_file_names_are_not_domains(self):
        text = ("chrony.conf ptp4l.conf ntp-gui.log settings.json history.json.gz server.py app.js "
                "help.md entrypoint.sh /run/ntp-gui/events.jsonl pps_gpio.ko")
        self.assertEqual(egress.sanitize_text(text, "community")[0], text)

    def test_host_keys_and_known_names(self):
        data = {"ntp_sources": [{"type": "server", "host": "nas"}, {"type": "pool", "host": "pool.ntp.org"},
                                {"type": "server", "host": "192.168.1.5"}],
                "hostname": "zeitserver-keller", "nts_server_name": "time.example-family.net"}
        clean, _ = egress.sanitize(data, "diagnostics", known_names=["zeitserver-keller"])
        self.assertEqual(clean["ntp_sources"][0]["host"], "<hostname-1>")
        self.assertEqual(clean["ntp_sources"][1]["host"], "pool.ntp.org")
        self.assertEqual(clean["ntp_sources"][2]["host"], "client-01")
        self.assertEqual(clean["hostname"], "<hostname-2>")
        text, _ = egress.sanitize_text("[web] zeitserver-keller gestartet; ntp-gui läuft", "diagnostics",
                                       known_names=["zeitserver-keller"])
        self.assertEqual(text, "[web] <hostname-1> gestartet; ntp-gui läuft")

    def test_reverse_dns_name(self):
        clean, _ = egress.sanitize_text("4.3.2.81.in-addr.arpa", "community")
        self.assertNotIn("81", clean)


class TimezoneAndLatencyTest(unittest.TestCase):
    def test_zone_names(self):
        for text in ("TZ=Europe/Berlin", "/usr/share/zoneinfo/America/Argentina/Buenos_Aires", "Zeit 12:00 CEST"):
            with self.subTest(text=text):
                self.assertTrue(egress.check_no_leaks(text))
                clean, _ = egress.sanitize_text(text, "diagnostics")
                self.assertIn("<zeitzone>", clean)
                self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertEqual(egress.sanitize_text("leapsectz right/UTC", "diagnostics")[0], "leapsectz right/UTC")

    def test_timezone_keys_keep_offset(self):
        clean, _ = egress.sanitize({"timezone": "Europe/Vienna", "tz": "+01:00", "zone": "UTC"}, "diagnostics")
        self.assertEqual(clean, {"timezone": "<zeitzone>", "tz": "+01:00", "zone": "UTC"})

    def test_every_purpose_rounds_delays(self):
        data = {"root_delay": 0.012345, "sources": [{"delay": 0.0237, "offset": 0.0000123}],
                "rtt_ms": 23.7, "peer_delay": 0.004}
        clean, report = egress.sanitize(data, "community")
        self.assertEqual(clean["root_delay"], 0.01)
        self.assertEqual(clean["sources"][0], {"delay": 0.02, "offset": 0.0000123})
        self.assertEqual(clean["rtt_ms"], 20)
        self.assertEqual(clean["peer_delay"], 0.0)
        self.assertEqual(report["removed"]["latenz_gerundet"], 4)
        # Seit 1.3: für jeden Zweck – auch Diagnosepakete verlassen die Instanz.
        for purpose in ("diagnostics", "recording"):
            other, _ = egress.sanitize(data, purpose)
            self.assertEqual(other, clean, purpose)


class ContractTest(unittest.TestCase):
    def test_report_shape(self):
        clean, report = egress.sanitize({"a": 1}, "diagnostics")
        self.assertEqual(clean, {"a": 1})
        self.assertEqual(report, {"removed": {}, "pseudonyms": 0})
        text, report = egress.sanitize_text("", "community")
        self.assertEqual(text, "")
        self.assertEqual(set(report), {"removed", "pseudonyms"})

    def test_unknown_purpose(self):
        with self.assertRaises(ValueError):
            egress.sanitize({}, "werbung")

    def test_every_category_has_german_explanation(self):
        clean, _ = egress.sanitize_text(CHRONY_TEXT + "\n" + json.dumps(TPV), "community")
        for key in ("position", "satellitenwinkel", "seriennummer", "mac", "oeffentliche_ip", "private_ip",
                    "hostname", "zeitzone", "zugangsdaten", "titel", "refid", "latenz_gerundet"):
            self.assertIn(key, egress.CATEGORIES)

    def test_findings_shape(self):
        findings = egress.check_no_leaks({"gps": {"lat": LAT}})
        self.assertEqual(findings[0]["kind"], "position")
        self.assertEqual(findings[0]["path"], "gps.lat")
        self.assertEqual(egress.check_no_leaks(b"8.8.8.8")[0]["kind"], "oeffentliche_ip")

    def test_input_not_modified(self):
        original = json.loads(json.dumps(GPS_STATUS))
        egress.sanitize(GPS_STATUS, "community")
        self.assertEqual(GPS_STATUS, original)

    def test_everything_together_is_clean(self):
        blob = {"gps": GPS_STATUS, "hw": HARDWARE, "chrony": CHRONY_TEXT,
                "raw": "\n".join(json.dumps(x) for x in (TPV, SKY))}
        for purpose in egress.PURPOSES:
            with self.subTest(purpose=purpose):
                clean, _ = egress.sanitize(blob, purpose)
                self.assertEqual(egress.check_no_leaks(clean), [])
                self.assertEqual(egress.check_no_leaks(dump(clean)), [])

    def test_large_text_is_fast(self):
        """Schutz vor katastrophalem Backtracking (das bräuchte Minuten). Gemessen wird die CPU-Zeit
        dieses Threads, nicht die Wanduhr: Auf einem geteilten 2-Kern-Runner zählte sonst jeder
        andere Prozess mit (4,4 s statt 0,9 s unter Last)."""
        import time

        def lines(n, tag):
            return "\n".join(f"[chrony] 2026-11-01T10:00:{i % 60:02d}Z Selected source 192.168.{tag}.{i % 250} "
                             f"offset 0.000{i:04d} jitter" for i in range(n))

        def cpu(text):
            start = time.thread_time()
            egress.sanitize_text(text, "diagnostics")
            return time.thread_time() - start

        egress.sanitize_text(lines(50, 3), "diagnostics")  # Aufwärmen (Regex-Übersetzung)
        small = cpu(lines(500, 1))
        large = cpu(lines(5000, 2))
        self.assertLess(large, 5.0)
        # Linear statt quadratisch: zehnfache Eingabe, höchstens ~30-fache Zeit (quadratisch: 100-fach).
        self.assertLess(large, 30 * max(small, 0.01), (small, large))


if __name__ == "__main__":
    unittest.main()
