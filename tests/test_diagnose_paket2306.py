"""Diagnosepaket 2306 (Datenschutz der Aufzeichnung): Zählwerte, DOP und das Alter des NTS-Schlüsseltauschs.

Alle Daten synthetisch (RFC-5737-Adressen, erfundene Satelliten).
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

H = 3600


def sky(t: str, expected: int, received: int) -> dict:
    """SKY mit `received` Satelliten mit Signal und `expected` weiteren ohne (ss=0 bzw. ohne ss)."""
    sats = [{"PRN": i + 1, "gnssid": 0, "svid": i + 1, "ss": 30.0 + i, "used": i < 4} for i in range(received)]
    for i in range(expected):
        sat = {"PRN": 40 + i, "gnssid": 0, "svid": 40 + i, "used": False}
        if i % 2:
            sat["ss"] = 0.0
        sats.append(sat)
    return {"class": "SKY", "time": t, "nSat": len(sats), "uSat": 4, "hdop": 1.23, "pdop": 2.34, "gdop": 2.71,
            "satellites": sats}


class SatelliteCountTest(unittest.TestCase):
    def test_satellites_without_signal_leave_no_trace(self):
        # Satelliten ohne Signal stehen nur aus dem Almanach in der Liste – ihre Zahl folgt der Geometrie
        # (Auf- und Untergänge). Sie dürfen in der Aufzeichnung keine Zahl erzeugen, die sich mit der Zeit ändert.
        rows = [egress.Sanitizer("recording").obj(sky(f"2026-01-01T00:{m:02d}:00Z", expected, 6))
                for m, expected in enumerate((3, 4, 5, 4, 2))]
        self.assertEqual(len({json.dumps({k: v for k, v in r.items() if k != "time"}, sort_keys=True)
                              for r in rows}), 1, rows)
        for row in rows:
            self.assertNotIn("nSat", row)
            gps = row["satellites"]["je_system"]["GPS"]
            self.assertNotIn("gesehen", gps)
        # Im Schnappschuss (ein einzelner Wert) bleiben die Summen – ohne die Satelliten ohne Signal.
        gps = egress.Sanitizer("diagnostics").obj(sky("2026-01-01T00:00:00Z", 5, 6))["satellites"]["je_system"]["GPS"]
        self.assertEqual((gps["empfangen"], gps["benutzt"]), (6, 4))

    @staticmethod
    def rising(t: str, ss: float, used: bool = False) -> dict:
        """7 Satelliten mit Signal, dazu PRN 20, der gerade aufgeht (ss 0 → >0, dann benutzt)."""
        sats = [{"PRN": i, "gnssid": 0, "svid": i, "ss": 35.0, "used": i < 5} for i in range(1, 8)]
        sats.append({"PRN": 20, "gnssid": 0, "svid": 20, "ss": ss, "used": used})
        return {"class": "SKY", "time": t, "uSat": 5 + used, "hdop": 1.0, "satellites": sats}

    def test_rising_satellite_leaves_no_step_in_recording(self):
        # Prüfbefund: Ein aufgehender Satellit bekommt erstmals Signal (ss 0 → 14) und wird dann benutzt.
        # „empfangen“, „benutzt“, uSat und der Mittelwert sprängen genau dann – der Zeitpunkt des Aufgangs
        # stünde sekundengenau in der Aufzeichnung.
        steps = [("12:00:00", 0.0, False), ("12:00:10", 0.0, False), ("12:00:20", 14.0, False),
                 ("12:00:30", 16.0, False), ("12:05:00", 22.0, True)]
        # Zweck „recording“ und – so läuft das Diagnosepaket – gpsd-Einträge der Aufzeichnung.
        direct = egress.Sanitizer("recording")
        rows = [direct.obj(self.rising(f"2026-01-01T{t}Z", ss, used)) for t, ss, used in steps]
        packet = egress.Sanitizer("diagnostics")
        lines = "\n".join(json.dumps({"t": 1767268800 + 10 * i, "kind": "gpsd", "args": ["w"], "s": 1,
                                       "out": json.dumps(self.rising(f"2026-01-01T{t}Z", ss, used))})
                          for i, (t, ss, used) in enumerate(steps))
        from_packet = [json.loads(json.loads(line)["out"]) for line in packet.text(lines).split("\n")]
        for series in (rows, from_packet):
            self.assertEqual(len({json.dumps({k: v for k, v in r.items() if k != "time"}, sort_keys=True)
                                  for r in series}), 1, series)
            for row in series:
                self.assertNotIn("uSat", row)
                self.assertEqual(row["satellites"]["je_system"], {"GPS": {"snr_max": 35}})
        # Derselbe Sanitizer filtert danach einen Schnappschuss wieder mit Summen (kein hängender Zustand).
        snap = packet.obj({"satellites": self.rising("x", 14.0)["satellites"]})
        self.assertEqual(snap["satellites"]["je_system"]["GPS"]["empfangen"], 8)
        self.assertIn("Aufzeichnung", egress.CATEGORIES["satellitenliste"])


class DopTest(unittest.TestCase):
    def test_vdop_tdop_not_recoverable(self):
        # PDOP² = HDOP² + VDOP², GDOP² = PDOP² + TDOP²: Mit HDOP, PDOP und GDOP wären VDOP/TDOP rückrechenbar.
        sanitizer = egress.Sanitizer("recording")
        clean = sanitizer.obj(sky("2026-01-01T00:00:00Z", 0, 6))
        self.assertEqual(clean.get("hdop"), 1.2)
        self.assertNotIn("pdop", clean)
        self.assertNotIn("gdop", clean)
        status = egress.Sanitizer("diagnostics").obj({"hdop": 0.8333, "pdop": 1.4642, "gdop": 1.61, "vdop": 1.2})
        self.assertEqual(status, {"hdop": 0.8})
        self.assertIn("HDOP", egress.CATEGORIES["dop"])
        self.assertNotIn("PDOP", egress.CATEGORIES["dop"].split("es bleibt")[-1])


class AuthdataAgeTest(unittest.TestCase):
    ROW = "192.0.2.1,NTS,1,15,256,{age},0,0,8,64"

    def recording_rows(self, start_age: int, seconds: int, step: int = 11) -> list[tuple[int, str]]:
        out = []
        for t in range(0, seconds, step):
            entry = {"kind": "chronyc", "args": ["-c", "authdata"], "out": self.ROW.format(age=start_age + t)}
            clean = egress.Sanitizer("recording").obj(entry)
            out.append((t, clean["out"].split(",")[5]))
        return out

    def test_recording_has_no_rounding_step(self):
        # Ein gleichmäßig wachsendes Alter, gerundet: Der Sprung über eine Rundungsgrenze verrät den genauen
        # Zeitpunkt des Schlüsseltauschs. In der Aufzeichnung darf die Spalte darum gar nicht variieren.
        rows = self.recording_rows(2 * H - 200, 600)        # überquert 2,5 h (Rundung auf Stunden)
        self.assertEqual(len({value for _t, value in rows}), 1, rows[:3])
        self.assertFalse(any(value.isdigit() for _t, value in rows))
        rows = self.recording_rows(3 * 86400 + 12 * H - 300, 600)   # Tagesgrenze
        self.assertEqual(len({value for _t, value in rows}), 1)

    def test_snapshot_stays_coarse(self):
        row = egress.Sanitizer("diagnostics").chronyc(["-c", "authdata"], self.ROW.format(age=123457))
        # Im Schnappschuss (chrony.txt, ein einzelner Wert) bleibt das grob gerundete Alter.
        self.assertEqual(row.split(",")[5], "86400")


if __name__ == "__main__":
    unittest.main()
