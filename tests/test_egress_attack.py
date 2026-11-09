"""Regressionstests aus dem Angriffstest auf den Datenschutzfilter (1.3, Funde L1–L9 und Export-DoS).

Jeder Fall ist eine Reproduktion aus dem Angriff. Geprüft wird jeweils:

1. Der Filter entfernt das Sensible.
2. Auf dem Ergebnis schweigen check_no_leaks und backstop (sonst bräche jeder echte Export ab).
3. check_no_leaks erkennt die rohe Eingabe (es prüft dieselben Regeln wie der Filter).
4. Für die Kernfälle schlägt auch die unabhängige Schlussprüfung (backstop) auf der rohen Eingabe an.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import fake_hostnames  # noqa: E402

import diagnostics  # noqa: E402
import egress  # noqa: E402

# (Eingabe, Teilstrings, die verschwinden müssen, backstop muss die rohe Eingabe sehen)
TEXT_CASES = [
    # L3 – Koordinaten im Freitext
    ("fix 3 48.137 11.576 519.3 12", ["48.137", "11.576"], True),
    ("481371540,115761240", ["481371540"], True),
    ("N 48° 08.229 E 011° 34.567", ["08.229", "34.567"], True),
    ("N48 08.229 E011 34.567", ["08.229", "34.567"], True),
    ("48d08m13.8sN 11d34m34.0sE", ["13.8s", "34.0s"], True),
    ("48 8 13.75 N 11 34 34.04 E", ["13.75", "34.04"], True),
    ("Latitude: 48 deg 8' 13.75\" N", ["13.75", "48 deg"], True),
    ("https://www.openstreetmap.org/?mlat=48.13715&mlon=11.57612#map=18", ["48.13715", "11.57612"], True),
    ("lat%3D48.137154%26lon%3D11.576124", ["48.137154", "11.576124"], True),
    ("mlat=48.137154", ["48.137154"], True),
    ("Lat.: 48.137154", ["48.137154"], True),
    ("lati 48.137154 longi 11.576124", ["48.137154", "11.576124"], True),
    ("Breitengrad 48.137154 Längengrad 11.576124", ["48.137154", "11.576124"], True),
    ("x=11.576124 y=48.137154", ["48.137154", "11.576124"], True),
    ("Koordinaten: 48.137154 und 11.576124", ["48.137154"], True),
    ("48.137154 - 11.576124", ["48.137154"], True),
    ("ECEF x=417761212 y=84619345 z=472889378 cm", ["417761212"], True),
    ("ECEF 4177612123 855543312 4728013234 mm", ["4177612123"], True),
    ("ubxtool -p CFG-TMODE3 -z CFG-TMODE-LAT,481371540", ["481371540"], True),
    ("Satellit 5: Azimut 123, Elevation 45", ["123", "45"], True),
    ("  5  288  62  45  Y", ["288"], True),
    ("sat 5 288° 62°", ["288"], True),
    ("GPGSV,3,1,11,03,03,111,00,04,15,270,00*74", ["270"], True),
    ("gpsd:IO: <= GPS: $GIGSV,1,1,02,03,45,123,40,05,12,300,30*7A", ["300"], True),
    ("gpsd:IO: <= GPS: $PUBX,03,02,5,U,123,45,40,000,7,U,300,12,30,000*1C", ["300"], True),
    ("$GIGGA,092750.000,5321.6802,N,00630.3372,W,1,8,1.03,61.7,M,55.2,M,,*76", ["5321.6802", "61.7"], True),
    # L5 – Seriennummern, lange Hex-Kennungen
    ("S/N: XQ9876ZT", ["XQ9876ZT"], True),
    ("iSerialNumber: ABCDEF123", ["ABCDEF123"], True),
    ("Serial No. 12345678", ["12345678"], True),
    ("Seriennr.: 12345678", ["12345678"], True),
    ("Serien-Nr. 87654321", ["87654321"], True),
    ("/dev/serial/by-id/usb-u-blox_AG_u-blox_GNSS_receiver_QWERTZUIOP-if00", ["QWERTZUIOP"], False),
    ("machine-id 3f2a1b4c5d6e7f8091a2b3c4d5e6f708", ["3f2a1b4c"], True),
    ("/docker/3f2a1b4c5d6e7f8091a2b3c4d5e6f7083f2a1b4c5d6e7f8091a2b3c4d5e6f708", ["3f2a1b4c"], True),
    # L6 – Zertifikats-DN
    ("subject=C = DE, ST = Bayern, L = Kleinkleckersdorf, O = Feuerwehr Kleinkleckersdorf, CN = zeit.mueller.de",
     ["Bayern", "Kleinkleckersdorf", "Feuerwehr", "mueller"], True),
    ("/C=DE/ST=Bayern/L=Kleinkleckersdorf/CN=zeit", ["Bayern", "Kleinkleckersdorf"], True),
    ("CN=zeit, OU=Keller", ["Keller"], True),
    # L7 – eigene Domains trotz Datei-/Code-Ausnahme
    ("zeit.mueller.new", ["mueller"], True),
    ("kowalski.pl", ["kowalski"], True),
    ("ntp.mueller.target", ["mueller"], True),
    ("zeit.mueller.dE", ["mueller"], True),
    ("zeit。mueller。de", ["mueller"], True),
    ("zeit .mueller.de", ["mueller"], True),
    # L8 – Laufzeiten außerhalb von Root/Peer delay
    ("ptbtime1.ptb.de antwortet in 23.456 ms", ["23.456"], True),
    ("RTT 23.456 ms zu time.cloudflare.com", ["23.456"], True),
    ("delay=0.023456", ["0.023456"], True),
    ("Delay           : 0.023456789", ["0.023456789"], True),
    ("Root distance   : 0.012345678 seconds", ["0.012345678"], True),
    ("Root delay      : 1.2345e-02 seconds", ["1.2345e-02", "1.23e-02"], False),
    ("Peer delay      : 23.456ms", ["23.456", "23.46"], False),
    # L9 – MAC, EUI-64, POSIX-TZ, Zonennamen
    ("link/ether 00 11 22 33 44 55", ["00 11 22 33 44 55"], True),
    ("MAC 00.11.22.33.44.55", ["00.11.22.33.44.55"], True),
    ("MAC 001122-334455", ["001122-334455"], True),
    ("gm 00-11-22-ff-fe-33-44-55", ["00-11-22-ff-fe-33-44-55"], True),
    ("TZ=CET-1CEST,M3.5.0,M10.5.0/3", ["M3.5.0", "CEST"], True),
    ("Zeitzone: W. Europe Standard Time", ["Europe Standard"], True),
    ("Mitteleuropäische Zeit", ["Mitteleuropäische"], True),
    # L1 – RefID in CSV-Zeilen und mit Bezeichnung
    ("5DB8D3A1,zeit.mueller.de,2,1793562069.3,-0.00000192,0.0,0.0,-12.3,0.0,0.0,0.01,0.0,14.1,Normal",
     ["5DB8D3A1", "mueller"], True),
    ("refid=5DB8D3A1", ["5DB8D3A1"], True),
    # Sonstiges
    ("ip-91-184-211-161", ["91-184-211-161"], True),
    ("Authorization: Bearer ntpg_abcdef0123456789abcdef0123", ["abcdef0123456789"], True),
]

STRUCT_CASES = [
    # L4 – Paare und Winkel, die die eingerückte JSON-Datei zerreißt
    ({"x": 11.576124, "y": 48.137154}, ["48.137154"]),
    ({"fix": [519.3, 48.137154, 11.576124]}, ["48.137154"]),
    ({"p": [1700000000, 48.137154, 11.576124]}, ["48.137154"]),
    ({"a": 48.137154, "b": 11.576124}, ["48.137154"]),
    ({"Breitengrad": 48.137154, "Laengengrad": 11.576124}, ["48.137154"]),
    ({"mlat": 48.137154}, ["48.137154"]),
    ({"sats": [["G05", 288, 62, 45]]}, ["288"]),
    ({"skyview": {"5": [288, 62]}}, ["288"]),
    ({"serial": ["ABCDEFGH"]}, ["ABCDEFGH"]),
    ({"serial": {"value": "ABCDEFGH"}}, ["ABCDEFGH"]),
    ({"sn": ["XYZ987654"]}, ["XYZ987654"]),
    ({"hostname": ["nas-keller"]}, ["nas-keller"]),
    ({"hosts": ["nas-keller", "zeit.mueller.de"]}, ["nas-keller", "mueller"]),
    ({"tz": {"name": "Berlin"}}, ["Berlin"]),
    ({"cert": {"subject": {"CN": "zeit.mueller.de", "L": "Kleinkleckersdorf"}}}, ["Kleinkleckersdorf", "mueller"]),
    ({"cert": {"subject_cn": "zeit.mueller.de", "dns_names": ["mueller.pl"]}}, ["mueller"]),
    ({"issuer": {"O": "Feuerwehr Kleinkleckersdorf"}}, ["Feuerwehr"]),
    ({"locality": "Kleinkleckersdorf"}, ["Kleinkleckersdorf"]),
    ({"web_password": "geheim123"}, ["geheim123"]),
    ({"pw": "geheim123"}, ["geheim123"]),
    ({"note": "Bearer ntpg_abcdef0123456789abcdef0123"}, ["abcdef0123456789"]),
    # L8 – Laufzeiten
    ({"time_ms": 23.456, "host": "ptbtime1.ptb.de"}, ["23.456"]),
    ({"round_trip_time": 0.023456}, ["0.023456"]),
    ({"delay_us": 23456}, ["23456"]),
    ({"peer_delay": "0.023456789"}, ["0.023456789"]),
    # L2 – Reverse-DNS-Namen in chrony-Datensätzen
    ({"address": "iPhone-von-Hans", "ntp_packets": 12}, ["iPhone"]),
    ({"address": "iPhone-von-Hans"}, ["iPhone"]),
    ({"mode": "^", "state": "*", "name": "nas-keller", "stratum": 2}, ["nas-keller"]),
    ({"ref_id": "5DB8D3A1", "ref_name": "nas-keller"}, ["5DB8D3A1", "nas-keller"]),
    ({"reference": "5DB8D3A1"}, ["5DB8D3A1"]),
    ({"ref_id": 1572393889}, ["1572393889"]),
    # Entwurf: Satellitenliste (sichtbare PRNs zu einer Zeit grenzen die Region ein)
    ({"class": "SKY", "time": "2026-11-01T10:00:00Z", "satellites": [
        {"PRN": 5, "gnssid": 0, "svid": 5, "ss": 40, "used": True},
        {"PRN": 7, "gnssid": 0, "svid": 7, "ss": 30, "used": False}]}, ['"PRN"', '"svid"']),
]


def _dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


class TextAttackTest(unittest.TestCase):
    def test_filter_removes_and_checks_stay_silent(self):
        for raw, secrets, _bs in TEXT_CASES:
            with self.subTest(raw=raw):
                s = egress.Sanitizer("diagnostics")
                clean = s.text(raw)
                for secret in secrets:
                    self.assertNotIn(secret, clean)
                self.assertEqual(egress.check_no_leaks(clean), [], clean)
                self.assertEqual(egress.backstop({"f.txt": clean.encode()}, s.backstop_known()), [], clean)
                self.assertEqual(s.text(clean), clean, "Filter-Ausgabe muss ein Fixpunkt sein")

    def test_raw_input_is_caught(self):
        for raw, _secrets, in_backstop in TEXT_CASES:
            with self.subTest(raw=raw):
                self.assertTrue(egress.check_no_leaks(raw), raw)
                if in_backstop:
                    self.assertTrue(egress.backstop({"f.txt": raw.encode()}, {}), raw)

    def test_harmless_text_stays(self):
        keep = [
            "server.py", "app.js", "help.md", "entrypoint.sh", "/usr/lib/x86_64-linux-gnu/libssl.so",
            "test_egress.py", "chrony.conf.new", "json.decoder.JSONDecodeError",
            "Frequency       : 12.345 ppm slow", "Update interval : 64.2 seconds",
            "ptp4l[1234.567]: port 1 (eth0): master offset -12 s2 freq +1234 path delay 567",
            "GPS,10,6,152,-12.345,2.345,0.012345678,0.000123456",
            "Root dispersion : 0.000010724 seconds", "offset 4.000000000 seconds",
            "2026-11-01 10:00:00 Selected source 127.0.0.1", "Version 1.3.0, Python 3.12.3",
            "rms   12 max   25 freq  -1234 +/-  12 delay   567 +/-   3",
        ]
        for text in keep:
            with self.subTest(text=text):
                self.assertEqual(egress.sanitize_text(text, "diagnostics")[0], text)
                self.assertEqual(egress.backstop({"f.txt": text.encode()}, {}), [], text)
                self.assertEqual(egress.check_no_leaks(text), [], text)

    def test_delays_round_to_10_ms_in_their_unit(self):
        s = egress.Sanitizer("diagnostics")
        self.assertEqual(s.text("Root delay      : 1.2345e-02 seconds"), "Root delay      : 0.01 seconds")
        self.assertEqual(s.text("Peer delay      : 23.456ms"), "Peer delay      : 20ms")
        self.assertEqual(s.text("antwortet in 23.456 ms"), "antwortet in 20 ms")
        self.assertEqual(s.text("rtt 23456 us"), "rtt 20000 us")


class StructAttackTest(unittest.TestCase):
    def test_filter_removes_and_checks_stay_silent(self):
        for raw, secrets in STRUCT_CASES:
            with self.subTest(raw=raw):
                s = egress.Sanitizer("diagnostics")
                clean = s.obj(raw)
                text = _dump(clean)
                for secret in secrets:
                    self.assertNotIn(secret, text)
                self.assertEqual(egress.check_no_leaks(clean), [], text)
                self.assertEqual(egress.backstop({"f.json": text.encode()}, s.backstop_known()), [], text)
                compact = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
                self.assertEqual(egress.backstop_compact_json({"f": compact.encode()}), [], compact)

    def test_raw_structures_are_caught(self):
        for raw, _secrets in STRUCT_CASES:
            with self.subTest(raw=raw):
                self.assertTrue(egress.check_no_leaks(raw), raw)

    def test_compact_json_backstop_sees_pairs(self):
        for raw in ({"x": 11.576124, "y": 48.137154}, {"fix": [519.3, 48.137154, 11.576124]},
                    {"lat": "48.137154", "lon": "11.576124"}):
            compact = json.dumps(raw, separators=(",", ":"))
            with self.subTest(raw=raw):
                self.assertTrue(egress.backstop_compact_json({"f": compact.encode()}))
        self.assertEqual(egress.backstop_compact_json({"f": b'{"offset":0.000123,"freq":-12.345,"skew":0.012}'}),
                         [])

    def test_satellite_list_becomes_sums(self):
        clean = egress.Sanitizer("diagnostics").obj(STRUCT_CASES[-1][0])
        gps = clean["satellites"]["je_system"]["GPS"]
        self.assertEqual((gps["gesehen"], gps["benutzt"], gps["snr_max"]), (2, 1, 40))

    def test_harmless_structures_stay(self):
        for raw in ({"frequency_ppm": -12.345, "skew_ppm": 0.012, "offset": 0.000123},
                    {"load": [0.52, 0.48, 0.45]}, {"satellites_used": 9, "satellites_seen": 14},
                    {"mode": "#", "state": "*", "name": "GPS"}, {"ref_id": "47505300", "ref_name": "GPS"},
                    {"cert_exists": True, "cert": "/etc/ntp-gui/nts.crt"}):
            with self.subTest(raw=raw):
                self.assertEqual(egress.Sanitizer("diagnostics").obj(raw), raw)
                self.assertEqual(egress.check_no_leaks(raw), [])


class ChronycCsvAttackTest(unittest.TestCase):
    """L1/L2: RefID und Namen in den CSV-Spalten von chronyc -c (auch in Aufzeichnungen)."""

    def test_tracking_refid_and_name(self):
        s = egress.Sanitizer("recording")
        out = s.chronyc(["-c", "tracking"], "5DB8D3A1,zeit.mueller.new,2,1793562069.3,-0.000001925,0.0,0.0,"
                                            "-12.345,0.000,0.001,0.012345678,0.000010724,14.1,Normal")
        self.assertNotIn("5DB8D3A1", out)
        self.assertNotIn("mueller", out)
        self.assertTrue(out.startswith("<refid>,<hostname-"))
        self.assertIn(",0.01,", out)

    def test_refclock_stays(self):
        s = egress.Sanitizer("recording")
        row = "47505300,GPS,1,1793562069.3,-0.000001925,0.0,0.0,-12.345,0.000,0.001,0.0,0.0,14.1,Normal"
        self.assertTrue(s.chronyc(["-c", "tracking"], row).startswith("47505300,GPS,"))
        self.assertTrue(s.chronyc(["-n", "-c", "sources"], "#,*,PPS,0,4,377,12,0.0,0.0,0.0").startswith("#,*,PPS,"))

    def test_reverse_dns_names(self):
        s = egress.Sanitizer("recording")
        clients = s.chronyc(["-c", "clients"], "iPhone-von-Hans,12,0,6,6,34,0,0,-,-")
        sources = s.chronyc(["-c", "sources"], "^,+,nas-keller,2,6,377,34,-0.000012,-0.000013,0.011234")
        stats = s.chronyc(["-c", "sourcestats"], "nas-keller,10,6,152,-12.345,2.345,0.0123,0.0001")
        self.assertNotIn("iPhone", clients)
        self.assertNotIn("nas-keller", sources + stats)
        # gleicher Name → gleiches Pseudonym
        self.assertEqual(sources.split(",")[2], stats.split(",")[0])

    def test_host_option_does_not_confuse_command(self):
        s = egress.Sanitizer("recording")
        out = s.chronyc(["-h", "/run/chrony/chronyd.sock", "-c", "tracking"],
                        "5DB8D3A1,x.example.de,2,1793562069.3,0,0,0,0,0,0,0.012345,0,14.1,Normal")
        self.assertNotIn("5DB8D3A1", out)

    def test_recording_entry(self):
        s = egress.Sanitizer("recording")
        line = json.dumps({"t": 1, "kind": "chronyc", "args": ["-c", "tracking"],
                           "out": "5DB8D3A1,zeit.mueller.new,2,1793562069.3,0,0,0,0,0,0,0.012345,0,14.1,Normal\n"})
        clean = s.text(line)
        self.assertNotIn("5DB8D3A1", clean)
        self.assertEqual(egress.check_no_leaks(clean), [])
        self.assertTrue(egress.check_no_leaks(line))


class ExportDenialTest(unittest.TestCase):
    """Ein von außen ins Log geschriebener Host-Name darf den Export nicht verhindern."""

    def setUp(self):
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        log = "\n".join([
            "[web] Anfrage für unbekannten Host-Namen „" + "a" * 64 + ".attacker.de“ abgelehnt",
            "[web] Anfrage für unbekannten Host-Namen „" + "b" * 300 + ".evil.de“ abgelehnt",
            "[web] lat\"=48.137154 seltsam geschrieben",
            "[main] alles gut",
        ]) + "\n"
        (self.tmp / "ntp-gui.log").write_text(log, encoding="utf-8")
        only_logs = {name: (lambda cfg, o: {}) for name in diagnostics.COLLECTORS}
        only_logs["logs"] = diagnostics._collect_logs
        for p in (mock.patch.object(diagnostics, "RUN_DIR", str(self.tmp)),
                  mock.patch.dict(diagnostics.COLLECTORS, only_logs)):
            p.start()
            self.addCleanup(p.stop)

    def test_long_labels_and_odd_lines_do_not_abort(self):
        result = diagnostics.preview({}, {})
        self.assertTrue(result["ok"])
        logs = result["content"]["logs"]
        self.assertNotIn("attacker", logs)
        self.assertNotIn("evil", logs)
        self.assertNotIn("48.137154", logs)
        # Seit der Auswertung des 1.6.0-Pakets mit Fundart: „[Zeile entfernt – Datenschutz: koordinaten]“
        self.assertIn(diagnostics.DROPPED_LINE[:-1] + ": koordinaten]", logs)
        self.assertIn("[main] alles gut", logs)
        self.assertIn("zeile_entfernt", result["removed"]["removed"])
        data = diagnostics.bundle({}, {})
        self.assertGreater(len(data), 100)


if __name__ == "__main__":
    unittest.main()
