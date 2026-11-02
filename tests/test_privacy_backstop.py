"""Gemeine Fälle für den Datenschutzfilter und die unabhängige Schlussprüfung (egress.backstop).

Jeder Fall stammt aus dem Datenschutz-Review zu 1.3 (REVIEW 0, Funde 1–12). Für
jeden Fall gilt dreierlei:

1. Der Filter entfernt das Sensible (die genannten Teilstrings sind weg).
2. Auf dem gefilterten Ergebnis schweigen check_no_leaks UND backstop – sonst
   bräche jeder echte Export ab.
3. Wird der Filter umgangen, schlägt backstop an (für alle Fälle, die in seinen
   Suchbereich fallen: bekannte Werte, 12 Hex-Zeichen, Koordinaten, Namen mit
   Punkt …). So fällt ein künftiger Fehler im Filter auf, statt still
   durchzurutschen.
"""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import fake_hostnames  # noqa: E402

import diagnostics  # noqa: E402
import egress  # noqa: E402
import enforce  # noqa: E402

TITLE = "Zeitserver Feuerwehr Kleinkleckersdorf"
KNOWN_NAMES = ["zeitserver-keller", "ntp.mein-dorf.us", "mueller.sh"]
KNOWN = {"titel": [TITLE], "seriennummer": ["ABCDEF", "0042A7F1C3"], "schnittstelle": ["lan-mueller"]}

# (Rohtext, Teilstrings, die verschwinden müssen, schlägt backstop auf dem Rohtext an?)
TEXT_CASES = [
    # 1 – MAC im Interface-Namen
    ("iface enx001122334455", ["001122334455"], True),
    ("hwtimestamp enx001122334455", ["001122334455"], True),
    ("ptp4l[12.3]: interface wlx0011223344aa ist oben", ["0011223344aa"], True),
    ("modem wwx02aabbccddee verbunden", ["02aabbccddee"], True),
    ("address 001122334455", ["001122334455"], True),
    # 2 – eigene Domains, egal welche Endung
    ("server ntp.mein-dorf.us iburst", ["mein-dorf"], True),
    ("server zeit.familie-mueller.club iburst", ["familie-mueller"], True),
    ("2026-11-01T10:00:05Z Selected source zeit.mein-ort.us", ["mein-ort"], True),
    ("server ntp.dorf.rs iburst", ["dorf.rs"], True),
    ("pool zeit.example-home.network", ["example-home"], True),
    ("server time.meine.rocks", ["meine.rocks"], True),
    ("server ntp.weltall.space", ["weltall"], True),
    ("server ntp.mueller.family", ["mueller"], True),
    ("server ntp.haus.in", ["haus.in"], True),
    ("server ntp.haus.cc", ["haus.cc"], True),
    ("server ntp.haus.md", ["haus.md"], True),
    ("server ntp.haus.mk", ["haus.mk"], True),
    ("server ntp.haus.ms", ["haus.ms"], True),
    ("server ntp.haus.py", ["haus.py"], True),
    ("server ntp.haus.sh", ["haus.sh"], True),
    ("server ntp.haus.so", ["haus.so"], True),
    ("server ntp.haus.pm", ["haus.pm"], True),
    ("server ntp.haus.ps", ["haus.ps"], True),
    ("server zeit.müller.de", ["müller"], True),
    ("server mueller.sh iburst", ["mueller"], True),      # nur über den bekannten Namen
    ("[web] zeitserver-keller gestartet", ["zeitserver-keller"], True),
    ("Fehler bei foo_bar.privat-netz.de", ["privat-netz"], True),
    # 3 – Koordinaten im Freitext
    ("Latitude 48.137154 Longitude 11.576124", ["48.137", "11.576"], True),
    ("Breite: 48.137154, Länge: 11.576124", ["48.137", "11.576"], True),
    ("breite=48,137154 laenge=11,576124", ["48,137", "11,576"], True),
    ("N48.137154 E11.576124", ["48.137", "11.576"], True),
    ("N 48.137154, O 11.576124", ["48.137", "11.576"], True),
    ("48.137154N 11.576124E", ["48.137", "11.576"], True),
    ("S33.8688 E151.2093", ["33.868", "151.209"], True),
    ("48,137154 11,576124", ["48,137", "11,576"], True),
    ("4808.2292N 01134.5674E", ["4808.229", "01134.567"], True),
    ("$GPGLL,4807.038,N,01131.000,E,123519,A*2C", ["4807.038"], True),
    ("latE7=481371540 lonE7=115761240", ["481371540", "115761240"], True),
    ("x=4177612.123 y=855543.312 z=4728013.234", ["4177612", "855543", "4728013"], True),
    ("ECEF 4177612.1 855543.3 4728013.2", ["4177612", "855543"], True),
    ("https://maps.example.org/?q=48.1371%2C11.5761", ["48.1371", "11.5761"], True),
    ("Standort 48.137,11.576", ["48.137", "11.576"], True),
    ("48.137° N 11.576° E", ["48.137", "11.576"], True),
    ('"lat_deg": 48.137154, "lon_deg": 11.576124', ["48.137", "11.576"], True),
    ("azimuth 123.0 elevation 45.0", ["123.0", "45.0"], True),
    ("az 123 el 45", ["123", "45"], True),
    ("Höhe: 519.3 m", ["519.3"], True),
    # 6 – Laufzeiten
    ("Root delay      : 0.012345678 seconds", ["0.012345678"], True),
    ("Peer delay      : 0.023456789 seconds", ["0.023456789"], True),
    ("^* 192.53.103.108                1   6   377    34   -12us[  -13us] +/-   11ms", ["11ms", "192.53"], False),
    # 7 – von chronyc gekürzte IPv6
    ("^* 2a01:4f8:c17:5c1b:1234:5678:9a>  1   6   377    34   -12us", ["2a01", "4f8"], True),
    ("^- fe80::21b:21ff:feaa:bbcc%eth>  2   6   377    36  +120us", ["21b:21ff", "feaa"], True),
    # 8 – Titel im Freitext
    (f"[web] {TITLE} gestartet", ["Kleinkleckersdorf"], True),
    # 9 – Seriennummern ohne Ziffern bzw. ohne „serial“
    ("/dev/serial/by-id/usb-u-blox_AG_u-blox_GNSS_receiver_ABCDEF-if00", ["ABCDEF"], True),
    ("subtype1: FWVER=1.00,PROTVER=34.00,SN 1234567890AB", ["1234567890AB"], True),
    ("iSerial                 3 0042A7F1C3", ["0042A7F1C3"], True),
    # 10 – Zeitzonen
    ("Zeit 12:00 WIB", ["WIB"], False),
    ("Lokalzeit 08:00 PKT, Server in ICT", ["PKT", "ICT"], False),
    ("zone: Berlin", ["Berlin"], False),
    ("Time zone: Europe/Berlin (CET, +0100)", ["Berlin", "CET"], True),
    # weitere Kennungen
    ("container 3f2a1b4c5d6e gestartet", ["3f2a1b4c5d6e"], True),
    ("product_uuid 4c4c4544-0042-3510-8051-b4c04f4a4d32", ["4c4c4544", "b4c04f4a4d32"], True),
    ("Netz br-lan-mueller und lan-mueller", ["lan-mueller"], True),
]

# Strukturierte Fälle: (Objekt, Teilstrings, die verschwinden müssen, backstop auf kompaktem Roh-JSON?)
STRUCT_CASES = [
    ({"ptp_interface": "enx001122334455", "ntp_hw_timestamp_interface": "enx001122334455"},
     ["001122334455"], True),
    ({"address": "001122334455"}, ["001122334455"], True),
    ({"iface": {"mac": "02:11:22:33:44:55", "permaddr": "021122334455"}}, ["334455"], True),
    ({"enforce_hostnames": ["ntp.mein-dorf.us", "zeit.familie.club"]}, ["mein-dorf", "familie"], True),
    ({"ntp_sources": [{"type": "server", "host": "zeit.mueller.rocks"}]}, ["mueller"], True),
    ({"lat_deg": 48.137154, "lon_deg": 11.576124}, ["48.137", "11.576"], True),
    ({"latitude_e7": 481371540, "longitudeE7": 115761240}, ["481371540", "115761240"], True),
    ({"pos": {"x": 4177612.1, "y": 855543.3, "z": 4728013.2}}, ["4177612", "855543"], True),
    ({"breite": 48.137154, "laenge": 11.576124, "hoehe": 519.3}, ["48.137", "11.576", "519.3"], True),
    ({"lat": {"min": 48.137154, "max": 48.137160}, "lon": [11.576124, 11.576130]}, ["48.137", "11.576"], False),
    ({"az_deg": 123.4, "el_deg": 45.6}, ["123.4", "45.6"], True),
    ({"satellites": [[5, 288, 62, 45], [21, 120, 7, 18], [67, 41, 12, 21]]}, ["288", "120"], False),
    ({"gps": {"Position": {"Lat": 48.137154}}, "ECEF_X": 4177612.1}, ["48.137", "4177612"], True),
    ({"subtype1": "FWVER=1.00,SN 1234567890AB", "path": "usb-u-blox_AG_u-blox_GNSS_receiver_ABCDEF-if00"},
     ["1234567890AB", "ABCDEF"], True),
    ({"timezone": "Asia/Jakarta", "note": "zone: Jakarta"}, ["Jakarta"], True),
    ({"root_delay": 0.012345, "metrics": {"root_delay": {"n": 5, "min": 0.0123, "max": 0.0456,
                                                        "mean": 0.0234}}},
     ["0.012345", "0.0123", "0.0456", "0.0234"], False),
    ({"title": "API-Schlüssel angelegt", "data": {"api_key_name": "HA Familie Schmidt"}}, ["Schmidt"], False),
]


def sanitizer():
    return egress.Sanitizer("diagnostics", KNOWN_NAMES, KNOWN)


class TextCorpusTest(unittest.TestCase):
    def test_every_case_is_scrubbed_and_backstop_silent(self):
        for raw, secrets, _bs in TEXT_CASES:
            with self.subTest(raw=raw):
                s = sanitizer()
                clean = s.text(raw)
                for secret in secrets:
                    self.assertNotIn(secret, clean)
                self.assertEqual(egress.check_no_leaks(clean), [], clean)
                self.assertEqual(egress.backstop({"f.txt": clean.encode()}, s.backstop_known()), [], clean)

    def test_backstop_fires_when_filter_is_bypassed(self):
        known = sanitizer().backstop_known()
        for raw, _secrets, in_scope in TEXT_CASES:
            if not in_scope:
                continue
            with self.subTest(raw=raw):
                self.assertTrue(egress.backstop({"f.txt": raw.encode()}, known), raw)

    def test_whole_corpus_as_one_file(self):
        """So sieht es im Paket aus: alles zusammen in einer Datei."""
        s = sanitizer()
        raw = "\n".join(case[0] for case in TEXT_CASES)
        clean = s.text(raw)
        self.assertEqual(egress.backstop({"logs.txt": clean.encode()}, s.backstop_known()), [])
        self.assertEqual(egress.check_no_leaks(clean), [])
        findings = egress.backstop({"logs.txt": raw.encode()}, s.backstop_known())
        self.assertGreaterEqual(len({f["path"] for f in findings}), 40)
        self.assertTrue(all(f["path"].startswith("logs.txt: Zeile ") for f in findings))


class StructCorpusTest(unittest.TestCase):
    def test_every_case_is_scrubbed_and_backstop_silent(self):
        for obj, secrets, _bs in STRUCT_CASES:
            with self.subTest(obj=obj):
                s = sanitizer()
                clean = s.obj(obj)
                for text in (json.dumps(clean, ensure_ascii=False, indent=2),
                             json.dumps(clean, ensure_ascii=False)):
                    for secret in secrets:
                        self.assertNotIn(secret, text)
                    self.assertEqual(egress.backstop({"f.json": text.encode()}, s.backstop_known()), [], text)
                self.assertEqual(egress.check_no_leaks(clean), [], clean)

    def test_raw_structures_are_caught(self):
        known = sanitizer().backstop_known()
        for obj, _secrets, in_scope in STRUCT_CASES:
            with self.subTest(obj=obj):
                self.assertTrue(egress.check_no_leaks(obj) or not in_scope or
                                egress.backstop({"f.json": json.dumps(obj).encode()}, known), obj)
                if in_scope:
                    self.assertTrue(egress.backstop({"f.json": json.dumps(obj, ensure_ascii=False).encode()},
                                                    known), obj)


class HarmlessCorpusTest(unittest.TestCase):
    """Echte Ausgaben ohne Geheimnisse: der Filter darf sie nicht zerstören, backstop nicht anschlagen."""

    HARMLESS = "\n".join([
        "Reference ID    : 50505300 (PPS)",
        "Stratum         : 1",
        "System time     : 0.000000012 seconds fast of NTP time",
        "Frequency       : 12.345 ppm slow",
        "Residual freq   : +0.001 ppm",
        "Skew            : 0.012 ppm",
        "Root dispersion : 0.000012345 seconds",
        "#,*,PPS,0,4,377,12,-0.000000012,-0.000000013,0.000000150",
        "#,-,GPS,0,4,377,12,0.012345678,0.012345678,0.100000000",
        "GPS,10,6,152,-12.345,2.345,0.012345678,0.000123456",
        "PPS,12,7,180,0.001,0.012,-0.000000004,0.000000150",
        "7F000002,127.0.0.2,3,1793562069.304605497,-0.000001925,0.000000022,0.000000144,"
        "-12.345,0.000,0.001,0.01,0.000010724,14.1,Normal",
        "^* ptbtime1.ptb.de  1 6 377 34 -12us[-13us] +/- 10ms",
        "server ptbtime1.ptb.de iburst nts",
        "server time.cloudflare.com iburst nts",
        "pool 2.debian.pool.ntp.org iburst",
        "server ntp.ubuntu.com iburst",
        "server time.android.com",
        "Nie umschreiben: fritz.box",
        "chrony.conf ptp4l.conf ntp-gui.log settings.json history.json.gz server.py app.js help.md",
        "entrypoint.sh pps_gpio.ko /run/ntp-gui/events.jsonl history.json.gz.migrated",
        'Traceback (most recent call last):',
        '  File "/app/server.py", line 123, in do_GET',
        "json.decoder.JSONDecodeError: Expecting value",
        "subprocess.TimeoutExpired: timed out",
        "ptp4l[1234.567]: port 1 (eth0): master offset -12 s2 freq +1234 path delay 567",
        "phc2sys[99.5]: CLOCK_REALTIME phc offset -3 s2 freq -1234.567 delay 890",
        "[   12.345678] pps pps0: new PPS source pps@12.-1",
        "gpsd:INFO: gpsd ntpshm=3 version=3.25",
        '{"class":"VERSION","release":"3.25","rev":"3.25","proto_major":3,"proto_minor":15}',
        '{"class":"PPS","device":"/dev/pps0","real_sec":1793562069,"real_nsec":0,"clock_sec":1793562069,'
        '"clock_nsec":120,"precision":-20}',
        "Version 1.3.0, Python 3.12.3, chrony 4.5, linuxptp 4.2",
        "rms   12 max   25 freq  -1234 +/-  12 delay   567 +/-   3",
        "allow 192.168.0.0/16",
        "ptp_dst_mac 01:1B:19:00:00:00",
        "Speed: 1000Mb/s",
        "offset 0.0001234, 0.0002345 jitter",
        "z. B. client-01, <hostname-1> – u. a. bzw. d.h.",
    ])

    def test_harmless_stays_and_backstop_is_silent(self):
        s = sanitizer()
        clean = s.text(self.HARMLESS)
        self.assertEqual(egress.backstop({"chrony.txt": clean.encode()}, s.backstop_known()), [])
        self.assertEqual(egress.backstop({"chrony.txt": self.HARMLESS.encode()}, s.backstop_known()), [])
        for keep in ("ptbtime1.ptb.de", "time.cloudflare.com", "2.debian.pool.ntp.org", "ntp.ubuntu.com",
                     "time.android.com", "fritz.box", "chrony.conf", "server.py", "help.md",
                     "history.json.gz.migrated", "JSONDecodeError", "Frequency       : 12.345 ppm slow",
                     "GPS,10,6,152,-12.345,2.345,0.012345678,0.000123456", "allow 192.168.0.0/16",
                     "01:1B:19:00:00:00"):
            self.assertIn(keep, clean)

    def test_enforce_hosts_stay_readable(self):
        hosts = {h["host"] for h in enforce.KNOWN_TIME_HOSTS} | set(enforce.NEVER_REWRITE)
        for host in sorted(hosts):
            with self.subTest(host=host):
                self.assertEqual(egress.sanitize_text(f"server {host} iburst", "diagnostics")[0],
                                 f"server {host} iburst")
                self.assertEqual(egress.backstop({"f": f"server {host}".encode()}), [])


class ChronycCsvTest(unittest.TestCase):
    def test_csv_columns_are_rounded(self):
        s = egress.Sanitizer("diagnostics")
        tracking = ("C035676C,ptbtime1.ptb.de,2,1793562069.304605497,-0.000001925,0.000000022,0.000000144,"
                    "-12.345,0.000,0.001,0.012345678,0.000010724,14.1,Normal")
        out = s.chronyc(["-c", "tracking"], tracking).split(",")
        self.assertEqual(out[10], "0.01")
        self.assertEqual(out[1], "ptbtime1.ptb.de")
        sources = "^,*,192.53.103.108,1,6,377,34,-0.000012000,-0.000013000,0.011234567\n#,*,PPS,0,4,377,12,0,0,0.000000150"
        out = s.chronyc(["-n", "-c", "sources"], sources).split("\n")
        self.assertTrue(out[0].endswith(",0.01"))
        self.assertTrue(out[1].endswith(",0.000000150"))  # Refclock: keine Laufzeit, bleibt genau
        select = "*,192.53.103.108,N,-,-,-,-,-,-,-,-,-,-,4,1.0,-0.003951234,0.010754321,Normal"
        self.assertIn(",0.00,0.01,Normal", s.chronyc(["-c", "selectdata"], select))
        self.assertIn("latenz_gerundet", s.report()["removed"])

    def test_recording_lines_are_rounded(self):
        line = json.dumps({"t": 1, "kind": "chronyc", "args": ["-c", "sources"],
                           "out": "^,*,192.53.103.108,1,6,377,34,-0.000012,-0.000013,0.011234567\n"})
        clean, _ = egress.sanitize_text(line, "recording")
        parsed = json.loads(clean)
        self.assertIn(",0.01", parsed["out"])
        self.assertNotIn("0.011234567", clean)
        self.assertNotIn("192.53", clean)


class DiagnosticsBackstopTest(unittest.TestCase):
    """Ende-zu-Ende: feindselige Daten im Paket; mit Filter sauber, ohne Filter Abbruch."""

    def setUp(self):
        fake_hostnames(self)  # kein Rückwärts-DNS des Runners
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        sysroot = self.tmp / "sys"
        (sysroot / "bus/usb/devices/1-1").mkdir(parents=True)
        (sysroot / "bus/usb/devices/1-1/serial").write_text("ABCDEF\n")
        (sysroot / "bus/usb/devices/usb1").mkdir(parents=True)
        (sysroot / "bus/usb/devices/usb1/serial").write_text("0000:00:14.0\n")  # Root-Hub: keine Seriennummer
        (sysroot / "class/dmi/id").mkdir(parents=True)
        (sysroot / "class/dmi/id/board_serial").write_text("BSN-QWERTZ\n")
        (sysroot / "class/net/lan-mueller").mkdir(parents=True)
        (sysroot / "class/net/eth0").mkdir(parents=True)
        log = "\n".join([f"[web] {TITLE} gestartet"] + [c[0] for c in TEXT_CASES]
                        + ["[gps] Board BSN-QWERTZ erkannt", "[ptp] lan-mueller hat PHC /dev/ptp0"]) + "\n"
        (self.tmp / "ntp-gui.log").write_text(log, encoding="utf-8")
        hostile_events = [
            {"id": 1, "t": 1, "kind": "settings", "level": "info",
             "title": "API-Schlüssel angelegt: HA Familie Schmidt, Lindenweg 7 Kleinkleckersdorf",
             "data": {"id": "AbCdEf12", "scope": "read", "name": "HA Familie Schmidt"}, "source": "web"},
            {"id": 2, "t": 2, "kind": "gps", "level": "info", "title": "Fix",
             "data": {"lat_deg": 48.137154, "iface": "enx001122334455"}, "source": "web"},
        ]
        self.cfg = {"web_title": TITLE, "nts_server_name": "zeit.mueller-family.de",
                    "ptp_interface": "enx001122334455", "ntp_hw_timestamp_interface": "lan-mueller",
                    "enforce_hostnames": ["ntp.mein-dorf.us", "mueller.sh"],
                    "ntp_sources": [{"type": "server", "host": "zeit.familie-mueller.club"},
                                    {"type": "server", "host": "ptbtime1.ptb.de"}],
                    "bind_address": "nas-keller"}
        collectors = {
            "meta": lambda cfg, o: {"programm": "ntp-gui", "version": "1.3.0"},
            "config": lambda cfg, o: {"chrony.conf": "server zeit.familie-mueller.club iburst\n"
                                                     "server mueller.sh\nhwtimestamp lan-mueller\n"
                                                     "bindaddress nas-keller\n"},
            "chrony": lambda cfg, o: {
                "tracking": "Reference ID    : C035676C (ptbtime1.ptb.de)\nRoot delay      : 0.012345678 seconds",
                "sources": "# Spalten: …\n^,*,2a01:4f8:c17:5c1b:1234:5678:9abc:def0,1,6,377,34,-0.00001,-0.00001,"
                           "0.0123456",
                "clients_count": 3},
            "gps": lambda cfg, o: {"status": {"mode": 3, "lat_deg": 48.137154, "pos": {
                "x": 4177612.1, "y": 855543.3, "z": 4728013.2}, "satellites": [[5, 288, 62, 45], [21, 120, 7, 18]],
                "subtype1": "SN 1234567890AB", "path": "usb-u-blox_AG_u-blox_GNSS_receiver_ABCDEF-if00"}},
            "ptp": lambda cfg, o: {"status": {"interface": "enx001122334455"}, "log": "ptp4l: lan-mueller up"},
            "hardware": lambda cfg, o: {"platform": {"dmi": {"board_name": "X", "note": "BSN-QWERTZ"}}},
            "services": lambda cfg, o: {"services": {"chronyd": {"state": "running"}}},
            "events": lambda cfg, o: [diagnostics._without_key_name(e) for e in hostile_events],
            "logs": diagnostics._collect_logs,
            "settings": lambda cfg, o: {"values": dict(cfg), "herkunft": {}},
            "history": lambda cfg, o: {"metrics": {"root_delay": {"n": 3, "min": 0.0123, "max": 0.0456}}},
        }
        patches = [mock.patch.object(diagnostics, "RUN_DIR", str(self.tmp)),
                   mock.patch.dict(diagnostics.COLLECTORS, collectors),
                   mock.patch.dict(os.environ, {"NTPGUI_SYS_ROOT": str(sysroot)})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    SECRETS = ("Kleinkleckersdorf", "001122334455", "mein-dorf", "familie-mueller", "mueller.sh", "lan-mueller",
               "nas-keller", "48.137", "4177612", "ABCDEF", "1234567890AB", "BSN-QWERTZ", "Schmidt",
               "Lindenweg", "2a01:4f8", "0.012345678", "0.0123456", "mueller-family", "0042A7F1C3")

    def test_bundle_is_clean(self):
        data = diagnostics.bundle(self.cfg, {})
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = {Path(m.name).name: tar.extractfile(m).read().decode("utf-8") for m in tar.getmembers()}
        blob = "\n".join(members.values())
        for secret in self.SECRETS:
            self.assertNotIn(secret, blob, secret)
        self.assertIn("API-Schlüssel angelegt: AbCdEf12", members["events.json"])
        self.assertIn("ptbtime1.ptb.de", blob)
        self.assertIn("<titel>", members["logs.txt"])
        self.assertEqual(egress.backstop({k: v.encode() for k, v in members.items()}), [])

    def test_backstop_aborts_when_filter_is_bypassed(self):
        """Filter und check_no_leaks außer Kraft – die unabhängige Schlussprüfung bricht trotzdem ab."""
        identity = lambda self, value, *a, **k: value  # noqa: E731
        with mock.patch.object(egress.Sanitizer, "obj", identity), \
                mock.patch.object(egress.Sanitizer, "text", identity), \
                mock.patch.object(egress.Sanitizer, "chronyc", lambda self, args, value: value), \
                mock.patch.object(egress, "check_no_leaks", return_value=[]):
            with self.assertRaises(diagnostics.LeakError) as ctx:
                diagnostics.bundle(self.cfg, {})
            with self.assertRaises(diagnostics.LeakError):
                diagnostics.preview(self.cfg, {})
        kinds = {f["kind"] for f in ctx.exception.findings}
        for kind in ("bekannter_name", "bekannter_wert", "hex12", "koordinaten", "name_mit_punkt"):
            self.assertIn(kind, kinds)
        self.assertIn("nichts exportiert", str(ctx.exception))

    def test_known_values_from_config_and_system(self):
        names = diagnostics._known_names(self.cfg)
        for name in ("zeit.mueller-family.de", "ntp.mein-dorf.us", "mueller.sh", "zeit.familie-mueller.club",
                     "nas-keller"):
            self.assertIn(name, names)
        self.assertNotIn("ptbtime1.ptb.de", names)
        values = diagnostics._known_values(self.cfg)
        self.assertEqual(values["titel"], [TITLE])
        self.assertEqual(values["seriennummer"], ["ABCDEF", "BSN-QWERTZ"])
        self.assertIn("lan-mueller", values["schnittstelle"])
        self.assertIn("enx001122334455", values["schnittstelle"])
        default = diagnostics._known_values({"web_title": "NTP / PTP Time Server"})
        self.assertEqual(default["titel"], [])


if __name__ == "__main__":
    unittest.main()
