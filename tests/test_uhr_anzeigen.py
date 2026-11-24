"""Studiouhr Etappe C2: Design binary, Nerd-Zeile, Mondphase und Fortschrittsbalken.

Die reinen Rechnungen stehen in app/static/js/clockextras.js und laufen hier mit Node gegen Referenzwerte:
Binäruhr gegen die Bits aus Python, TAI und GPS-Zeit gegen TAI−UTC aus app/leap.py (mit der leap-seconds.list aus
tests/fixtures) und gegen bekannte GPS-Wochenwechsel, Mondphase gegen eine Tabelle bekannter Neu- und Vollmonde
(Finsternisse), Fortschrittsbalken in fester Zeitzone samt Umstellungstag. Dazu Schema, Server-Allowlist (tai_utc in
/api/v1/time) und Regeln für clock.js/clock.css/clock.html: Standard aus, nie mit fun=0 bzw. in Studio-, Kachel- und
Banner-Voreinstellung, keine neue Datei, kein Zeitgeber, höchstens acht Designs.
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import clockprofiles  # noqa: E402
import leap  # noqa: E402
import server  # noqa: E402

UTC = datetime.timezone.utc
GPS_EPOCH = int(datetime.datetime(1980, 1, 6, tzinfo=UTC).timestamp())


def run_fx(code: str, tz: str | None = None):
    mods = {name: json.dumps((JS / f"{name}.js").as_uri()) for name in ("clockextras", "clockkit")}
    script = f"import * as x from {mods['clockextras']};\nimport * as k from {mods['clockkit']};\n{code}"
    import os
    env = {**os.environ, "TZ": tz} if tz else None
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def ms(text: str) -> int:
    return int(datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class BinaeruhrTest(unittest.TestCase):
    def test_bcd_und_dual_gegen_python(self):
        samples = [(0, 0, 0), (13, 37, 0), (12, 34, 56), (23, 59, 59), (9, 5, 7), (20, 48, 39)]
        out = run_fx(f"""
          const s = {json.dumps(samples)};
          console.log(JSON.stringify({{
            bcd: s.map(([h, m, sec]) => x.binaryLamps(h, m, sec)),
            plain: s.map(([h, m, sec]) => x.binaryLamps(h, m, sec, {{ mode: "plain" }})),
            short: x.binaryLamps(13, 37, 59, {{ seconds: false }}),
            bad: [[24, 0, 0], [0, 60, 0], [0, 0, 60], [-1, 0, 0], [1.5, 0, 0], ["1", 0, 0]].map((v) => x.binaryLamps(...v)),
            badMode: x.binaryLamps(1, 2, 3, {{ mode: "hex" }}), modes: x.BIN_MODES, kit: k.BIN_MODES,
          }}));
        """)
        for (h, m, s), bcd, plain in zip(samples, out["bcd"], out["plain"]):
            with self.subTest(time=(h, m, s)):
                digits = [h // 10, h % 10, m // 10, m % 10, s // 10, s % 10]
                sizes = [2, 4, 3, 4, 3, 4]
                self.assertEqual([g["value"] for g in bcd["groups"]], digits)
                for group, digit, size in zip(bcd["groups"], digits, sizes):
                    self.assertEqual([b["weight"] for b in group["bits"]], [2 ** i for i in range(size - 1, -1, -1)])
                    self.assertEqual(sum(b["weight"] for b in group["bits"] if b["on"]), digit)
                for group, value, size in zip(plain["groups"], (h, m, s), (5, 6, 6)):
                    self.assertEqual(len(group["bits"]), size)
                    self.assertEqual("".join("1" if b["on"] else "0" for b in group["bits"]), format(value, f"0{size}b"))
        self.assertEqual([g["value"] for g in out["short"]["groups"]], [1, 3, 3, 7], "ohne Sekunden nur HH:MM")
        self.assertEqual(out["bad"], [None] * 6)
        self.assertIsNone(out["badMode"])
        self.assertEqual(out["modes"], ["bcd", "plain"])
        self.assertEqual(out["kit"], out["modes"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NerdZeileTest(unittest.TestCase):
    """TAI und GPS-Zeit mit TAI−UTC aus leap.py (leap-seconds.list aus dem Image), nie fest eingebaut."""

    TIMES = ["1980-01-06T00:00:00Z", "1999-08-21T23:59:46Z", "1999-08-21T23:59:47Z", "2012-06-30T23:59:59Z",
             "2012-07-01T00:00:00Z", "2016-12-31T23:59:59Z", "2017-01-01T00:00:00Z", "2019-04-06T23:59:41Z",
             "2019-04-06T23:59:42Z", "2026-11-23T12:34:56Z"]

    def leap_table(self):
        parsed = leap.parse((FIXTURES / "leap-seconds.list").read_text(encoding="ascii"))
        return {t: leap.evaluate(parsed, ms(t) / 1000)["tai_utc"] for t in self.TIMES}

    def test_tai_und_gps_gegen_leap_py(self):
        table = self.leap_table()
        self.assertEqual(table["2016-12-31T23:59:59Z"], 36)
        self.assertEqual(table["2017-01-01T00:00:00Z"], 37)
        self.assertEqual(table["1980-01-06T00:00:00Z"], 19)
        out = run_fx(f"""
          const table = {json.dumps({t: [ms(t), v] for t, v in table.items()})};
          const res = {{}};
          for (const [t, [stamp, tai]] of Object.entries(table)) res[t] = x.nerdValues(stamp, tai);
          console.log(JSON.stringify(res));
        """)
        for text, tai in table.items():
            with self.subTest(time=text):
                stamp = ms(text)
                got = out[text]
                unix = stamp // 1000
                self.assertEqual(got["unix"], unix)
                self.assertEqual(got["taiMs"], stamp + tai * 1000)
                self.assertEqual(got["gpsUtc"], tai - 19)
                gps = unix - GPS_EPOCH + tai - 19
                self.assertEqual(got["gps"], {"week": gps // 604800, "sow": gps % 604800})
                self.assertAlmostEqual(got["mjd"], stamp / 86_400_000 + 40587, places=9)
        # Bekannte GPS-Wochenwechsel (Rollover 1024 und 2048): GPS-Zeit 00:00:00 = UTC minus GPS−UTC.
        self.assertEqual(out["1999-08-21T23:59:47Z"]["gps"], {"week": 1024, "sow": 0})
        self.assertEqual(out["1999-08-21T23:59:46Z"]["gps"], {"week": 1023, "sow": 604799})
        self.assertEqual(out["2019-04-06T23:59:42Z"]["gps"], {"week": 2048, "sow": 0})
        self.assertEqual(out["2019-04-06T23:59:41Z"]["gps"]["week"], 2047)
        self.assertEqual(out["1980-01-06T00:00:00Z"]["gps"], {"week": 0, "sow": 0})

    def test_ohne_tai_utc_keine_geratene_zahl(self):
        out = run_fx("""
          const t = Date.UTC(2026, 10, 23, 12, 0, 0);
          console.log(JSON.stringify({
            none: x.nerdValues(t, null), bad: [9, 101, 37.5, "37", true, NaN, undefined].map((v) => x.nerdValues(t, v).taiMs),
            check: [10, 37, 100, 9, 101, 37.5, "37", true, null].map(x.taiUtc), hms: x.hmsOf(t + 37000), nan: x.nerdValues(NaN, 37),
            mjd2000: x.nerdValues(Date.UTC(2000, 0, 1), 32).mjd, mjd0: x.nerdValues(Date.UTC(1858, 10, 17), null).mjd,
            doy: [[2024, 12, 31], [2026, 3, 1], [2026, 1, 1], [2028, 2, 29]].map((d) => x.dayOfYear(...d)),
          }));
        """)
        self.assertIsNone(out["none"]["taiMs"])
        self.assertIsNone(out["none"]["gps"])
        self.assertEqual(out["bad"], [None] * 7)
        self.assertEqual(out["check"], [10, 37, 100, None, None, None, None, None, None])
        self.assertEqual(out["hms"], "12:00:37")
        self.assertIsNone(out["nan"])
        self.assertEqual(out["mjd2000"], 51544)
        self.assertEqual(out["mjd0"], 0)
        self.assertEqual(out["doy"], [366, 60, 1, 60])

    def test_hex_und_roemisch(self):
        samples = [0, 1, 4, 9, 14, 40, 49, 90, 99, 400, 1994, 2026, 3999]
        out = run_fx(f"""
          const s = {json.dumps(samples)};
          console.log(JSON.stringify({{ roman: s.map(x.roman), bad: [-1, 4000, 1.5, "7", null].map(x.roman),
            times: [[0, 0], [18, 44], [23, 59], [12, 5]].map(([h, m]) => x.romanTime(h, m)),
            badTimes: [[24, 0], [0, 60], [null, 1], [1.5, 2]].map(([h, m]) => x.romanTime(h, m)),
            hex: [0, 255, 2000000000, -1, 1.5, NaN].map(x.unixHex), nerdHex: x.nerdValues(Date.UTC(2033, 4, 18, 3, 33, 20), null).hex }}));
        """)

        def py_roman(n):
            if n == 0:
                return "N"
            table = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                     (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
            out = ""
            for value, sign in table:
                while n >= value:
                    out += sign
                    n -= value
            return out
        self.assertEqual(out["roman"], [py_roman(n) for n in samples])
        self.assertEqual(out["roman"][10:12], ["MCMXCIV", "MMXXVI"])
        self.assertEqual(out["bad"], [None] * 5)
        self.assertEqual(out["times"], ["N:N", "XVIII:XLIV", "XXIII:LIX", "XII:V"])
        self.assertEqual(out["badTimes"], [None] * 4)
        self.assertEqual(out["hex"], ["0x0", "0xFF", f"0x{2_000_000_000:X}", None, None, None])
        self.assertEqual(out["nerdHex"], "0x77359400", "Unixzeit 2 000 000 000")

    def test_kein_fester_schaltsekunden_wert_im_code(self):
        text = (JS / "clockextras.js").read_text(encoding="utf-8")
        nerd = text[text.index("// --- Nerd-Zeile"):text.index("// --- Mondphase")]
        self.assertNotRegex(nerd, r"\b3[0-9]\b", "TAI−UTC kommt vom Server, nicht aus dem Code")
        self.assertIn("TAI_GPS_S = 19", nerd, "nur der feste Abstand GPS = TAI − 19 s")


class ServerTaiTest(unittest.TestCase):
    def test_tai_utc_aus_leap_py(self):
        with mock.patch.object(leap, "chrony_source", return_value=("list", str(FIXTURES / "leap-seconds.list"))):
            self.assertEqual(server._clock_tai_utc({}), 37)
            self.assertEqual(server._clock_leap({}), {"leap_next": None, "tai_utc": 37})
        cases = [({"available": True, "tai_utc": 38, "next_leap_date": "2027-01-01"}, 38),
                 ({"available": False, "tai_utc": 37}, None), ({"available": True, "tai_utc": "37"}, None),
                 ({"available": True, "tai_utc": True}, None), ({"available": True, "tai_utc": 1000}, None),
                 ({"available": True, "tai_utc": None}, None)]
        for info, want in cases:
            with self.subTest(info=info), mock.patch.object(server.leap, "status", return_value=info):
                self.assertEqual(server._clock_tai_utc({}), want)
        with mock.patch.object(server.leap, "status", side_effect=RuntimeError("kaputt")):
            self.assertEqual(server._clock_leap({}), {"leap_next": None, "tai_utc": None})

    def test_time_payload_nur_die_zahl(self):
        tracking = {"synchronised": True, "stratum": 2, "ref_name": "192.0.2.1", "root_delay": 0.001,
                    "root_dispersion": 0.0001, "system_time_offset": 0.0, "leap_status": "Normal"}
        status = {"available": True, "tai_utc": 37, "next_leap_date": None, "path": "/geheim/leap.list"}
        with mock.patch.object(server, "_clock_tracking", return_value=tracking), \
                mock.patch.object(server.leap, "status", return_value=status):
            payload = server.time_payload(1.0, public=True)
        self.assertEqual(payload["tai_utc"], 37)
        self.assertNotIn("geheim", json.dumps(payload))
        doc = next(e for e in server.apiv1.ENDPOINTS if e["path"] == "/time")
        self.assertIn("tai_utc", json.dumps(doc, ensure_ascii=False), "dokumentiert in der API-Übersicht")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class MondphaseTest(unittest.TestCase):
    # Bekannte Neu- und Vollmonde (UTC, auf die Minute) – Sonnen- bzw. Mondfinsternisse, also gut belegte Zeitpunkte.
    TABLE = [("2000-01-06T18:14Z", 0), ("1999-08-11T11:08Z", 0), ("2006-03-29T10:15Z", 0), ("2015-09-28T02:50Z", 180),
             ("2017-08-21T18:30Z", 0), ("2018-07-27T20:20Z", 180), ("2019-07-02T19:16Z", 0), ("2021-05-26T11:14Z", 180),
             ("2022-11-08T11:02Z", 180), ("2023-10-14T17:55Z", 0), ("2024-04-08T18:21Z", 0), ("2025-03-14T06:55Z", 180),
             ("2026-03-03T11:38Z", 180), ("2026-08-12T17:37Z", 0)]

    def test_neu_und_vollmond_gegen_tabelle(self):
        table = [[ms(t), angle] for t, angle in self.TABLE]
        out = run_fx(f"""
          const table = {json.dumps(table)};
          console.log(JSON.stringify(table.map(([t, a]) => ({{
            phase: x.moonPhase(t), next: x.nextMoonPhase(t - 5 * 86400000, a),
          }}))));
        """)
        for (text, angle), got in zip(self.TABLE, out):
            with self.subTest(time=text):
                phase = got["phase"]
                diff = (phase["angle"] - angle + 540) % 360 - 180
                self.assertLess(abs(diff), 1.0, f"Elongation {phase['angle']:.2f}°")
                self.assertEqual(phase["key"], "new" if angle == 0 else "full")
                if angle == 0:
                    self.assertLess(phase["illum"], 0.001)
                else:
                    self.assertGreater(phase["illum"], 0.999)
                self.assertLess(abs(got["next"] - ms(text)), 2 * 3600_000, "nächster Neu-/Vollmond auf 2 h genau")

    def test_phasen_namen_und_alter(self):
        start = ms("2024-04-08T18:21Z")
        days = [0, 3.7, 7.4, 11, 14.8, 18.5, 22.1, 25.8]
        out = run_fx(f"""
          const res = {json.dumps(days)}.map((d) => x.moonPhase({start} + d * 86400000));
          console.log(JSON.stringify({{ res, names: x.MOON_PHASES, bad: x.moonPhase(NaN), syn: x.SYNODIC_DAYS }}));
        """)
        self.assertEqual([r["key"] for r in out["res"]], out["names"])
        for day, r in zip(days, out["res"]):
            gap = abs(r["age"] - day)
            self.assertLess(min(gap, out["syn"] - gap), 1.0, f"Alter nach {day} Tagen (im Kreis gemessen)")
            self.assertEqual(r["waxing"], r["angle"] < 180)
        self.assertIsNone(out["bad"])
        self.assertAlmostEqual(out["syn"], 29.530589)

    def test_svg_pfad(self):
        out = run_fx("""
          console.log(JSON.stringify({
            nu: x.moonPath(0), full: x.moonPath(180), q1: x.moonPath(90), q3: x.moonPath(270),
            cres: x.moonPath(45), gib: x.moonPath(135), wane: x.moonPath(315),
            south: x.moonPath(45, { south: true }), r: x.moonPath(90, { r: 49 }), nan: x.moonPath(NaN),
          }));
        """)
        self.assertEqual(out["nu"], "", "Neumond: nichts beleuchtet")
        self.assertEqual(out["full"], "M 50 0 A 50 50 0 1 1 50 100 A 50 50 0 1 1 50 0 Z")
        self.assertEqual(out["q1"], "M 50 0 A 50 50 0 0 1 50 100 A 0 50 0 0 0 50 0 Z", "rechte Hälfte")
        self.assertEqual(out["q3"], "M 50 0 A 50 50 0 0 0 50 100 A 0 50 0 0 1 50 0 Z", "linke Hälfte")
        self.assertEqual(out["cres"], "M 50 0 A 50 50 0 0 1 50 100 A 35.36 50 0 0 0 50 0 Z", "Sichel rechts")
        self.assertEqual(out["gib"], "M 50 0 A 50 50 0 0 1 50 100 A 35.36 50 0 0 1 50 0 Z", "Dreiviertel rechts")
        self.assertEqual(out["wane"], "M 50 0 A 50 50 0 0 0 50 100 A 35.36 50 0 0 1 50 0 Z", "Sichel links")
        self.assertEqual(out["south"], out["wane"], "Südhalbkugel: zunehmende Sichel links")
        self.assertEqual(out["r"], "M 50 1 A 49 49 0 0 1 50 99 A 0 49 0 0 0 50 1 Z")
        self.assertEqual(out["nan"], "")
        for d in out.values():
            self.assertRegex(d, r"^[MAZ0-9 .]*$", "nur Zahlen und Befehle")


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class FortschrittTest(unittest.TestCase):
    def test_zeitraeume_in_fester_zone(self):
        out = run_fx("""
          const at = (y, mo, d, h = 0, mi = 0) => new Date(y, mo - 1, d, h, mi).getTime();
          const f = (kind, t) => x.periodProgress(kind, t);
          console.log(JSON.stringify({
            noon: f("day", at(2026, 11, 23, 12)).fraction, midnight: f("day", at(2026, 11, 23)).fraction,
            dst: f("day", at(2026, 3, 29, 12)), fall: f("day", at(2026, 10, 25, 12)),
            monday: f("week", at(2026, 11, 23)).fraction, sunday: f("week", at(2026, 11, 29, 12)).fraction,
            month: f("month", at(2026, 2, 15)).fraction, year: f("year", at(2026, 7, 2, 12)).fraction,
            leapyear: f("year", at(2028, 7, 2)).fraction, bad: [f("decade", 0), f("day", NaN)],
            pct: [0, 0.004, 0.5, 0.999, 1, 1.2, -1, NaN, null].map(x.percentOf),
          }));
        """, tz="Europe/Berlin")
        self.assertAlmostEqual(out["noon"], 0.5)
        self.assertEqual(out["midnight"], 0)
        self.assertEqual(out["dst"]["end"] - out["dst"]["start"], 23 * 3600_000, "Umstellungstag hat 23 h")
        self.assertAlmostEqual(out["dst"]["fraction"], 11 / 23)
        self.assertEqual(out["fall"]["end"] - out["fall"]["start"], 25 * 3600_000)
        self.assertAlmostEqual(out["fall"]["fraction"], 13 / 25)
        self.assertEqual(out["monday"], 0, "die Woche beginnt am Montag")
        self.assertAlmostEqual(out["sunday"], 6.5 / 7)
        self.assertAlmostEqual(out["month"], 14 / 28)
        self.assertAlmostEqual(out["year"], (182 * 24 + 12) / (365 * 24), places=3)
        self.assertAlmostEqual(out["leapyear"], 183 / 366, places=3)
        self.assertEqual(out["bad"], [None, None])
        self.assertEqual(out["pct"], [0, 0, 50, 99, 100, 100, 0, None, None])

    def test_zeitraeume_in_der_zone_der_anzeige(self):
        # Gerät in Kiritimati (UTC+14), angezeigtes Datum in UTC (Design tc mit Zone des Servers): Die Balken folgen der
        # Zone der Anzeige, nicht der des Geräts.
        out = run_fx("""
          const t = Date.UTC(2026, 10, 23, 12);
          const f = (kind, off) => x.periodProgress(kind, t, off);
          console.log(JSON.stringify({ dayUtc: f("day", 0), dayDev: f("day", null), weekUtc: f("week", 0).fraction,
            yearUtc: f("year", 0), dayPlus2: f("day", 2 * 3600_000).fraction, monthUtc: f("month", 0).fraction }));
        """, tz="Pacific/Kiritimati")
        self.assertEqual(out["dayUtc"]["start"], ms("2026-11-23T00:00:00Z"))
        self.assertAlmostEqual(out["dayUtc"]["fraction"], 0.5)
        self.assertAlmostEqual(out["dayDev"]["fraction"], 2 / 24, msg="Gerätezeit: schon 02:00 am 24.11.")
        self.assertAlmostEqual(out["weekUtc"], 0.5 / 7, msg="Montag, 23.11., 12:00 UTC")
        self.assertEqual(out["yearUtc"]["start"], ms("2026-01-01T00:00:00Z"))
        self.assertAlmostEqual(out["dayPlus2"], 14 / 24)
        self.assertAlmostEqual(out["monthUtc"], (22 * 24 + 12) / (30 * 24))

    def test_balken_auswahl_und_timer(self):
        out = run_fx("""
          const timer = { duration: 600000, state: "running", start: 1000, acc: 0 };
          console.log(JSON.stringify({
            plain: x.barsFor(null, false), timer: x.barsFor(null, true), chosen: x.barsFor(["year", "timer", "week"], false),
            chosenT: x.barsFor(["year", "timer"], true), bars: x.BARS, kit: k.BARS,
            run: x.timerProgress(timer, 1000 + 150000), over: x.timerProgress(timer, 1000 + 900000),
            watch: x.timerProgress({ duration: null, state: "running", start: 0, acc: 0 }, 5000), none: x.timerProgress(null, 0),
          }));
        """)
        self.assertEqual(out["plain"], ["day", "year"])
        self.assertEqual(out["timer"], ["day", "timer"])
        self.assertEqual(out["chosen"], ["week", "year"], "timer ohne Eieruhr fällt weg, Reihenfolge fest")
        self.assertEqual(out["chosenT"], ["year", "timer"])
        self.assertEqual(out["bars"], out["kit"])
        self.assertAlmostEqual(out["run"], 0.25)
        self.assertEqual(out["over"], 1)
        self.assertIsNone(out["watch"])
        self.assertIsNone(out["none"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class StandardAusTest(unittest.TestCase):
    def test_show_aufteilen_und_wann_sichtbar(self):
        presets = {name: entry["params"] for name, entry in clockprofiles.PRESETS.items()}
        out = run_fx(f"""
          const presets = {json.dumps(presets)};
          const shown = (q, layout = "normal") => {{ const p = k.parseParams(q); const s = x.splitShow(p.show);
            return {{ base: s.base, extras: x.extrasShown({{ extras: s.extras, fun: p.fun, kiosk: p.kiosk, layout, eink: p.eink }}) }}; }};
          const all = "&show=moon,nerd,progress";
          const res = {{}};
          for (const [name, params] of Object.entries(presets)) res[name] = shown("?" + new URLSearchParams(params).toString() + all);
          console.log(JSON.stringify({{ presets: res, plain: shown(""), only: shown("?show=moon"), mixed: shown("?show=time,nerd"),
            fun0: shown("?fun=0" + all), tile: shown(all, "tile"), strip: shown(all, "strip"), eink: shown("?eink=1" + all),
            kiosk: shown("?kiosk=1" + all), kioskDirect: x.extrasShown({{ extras: ["moon"], kiosk: true }}),
            crowdedLow: x.extrasShown({{ extras: ["moon"], height: 171, layout: "banner", crowded: true }}),
            crowdedHigh: x.extrasShown({{ extras: ["moon"], height: 640, layout: "banner", crowded: true }}),
            merged: [x.mergeShow(["moon"], ["time"]), x.mergeShow(["moon"], null), x.mergeShow(["date", "nerd"], ["time"]),
              x.mergeShow(["time"], ["time"]), x.mergeShow(null, ["time"]), x.mergeShow(["moon"], ["time", "nerd"])],
            low: x.extrasShown({{ extras: ["moon"], height: 359 }}),
            lowBanner: x.extrasShown({{ extras: ["moon"], height: 150, layout: "banner" }}),
            high: x.extrasShown({{ extras: ["moon"], height: 360 }}), nerdPreset: shown("?" + new URLSearchParams(presets.nerd).toString()),
            none: x.splitShow(null), items: x.EXTRA_ITEMS, show: k.SHOW_ITEMS }}));
        """)
        self.assertEqual(out["plain"], {"base": None, "extras": []}, "Standard: keine Zusätze")
        self.assertEqual(out["only"], {"base": None, "extras": ["moon"]}, "nur Zusätze: Grundelemente bleiben")
        self.assertEqual(out["mixed"], {"base": ["time"], "extras": ["nerd"]})
        for name in ("studio", "tile", "banner"):
            self.assertEqual(out["presets"][name]["extras"], [], f"{name}: fun=0, nie Zusätze")
        self.assertEqual(out["fun0"]["extras"], [])
        self.assertEqual(out["tile"]["extras"], [])
        self.assertEqual(out["strip"]["extras"], [])
        self.assertEqual(out["eink"]["extras"], ["moon", "progress"], "E-Ink: ohne Sekunden-Zeile")
        self.assertEqual(out["kiosk"]["extras"], [], "Kiosk: keine Spielereien (Konzept, Abschnitt 4)")
        self.assertEqual(out["kioskDirect"], [])
        self.assertEqual(out["crowdedLow"], [], "niedriger Banner mit Countdown oder Weltzeit-Leiste: kein Platz")
        self.assertEqual(out["crowdedHigh"], ["moon"])
        self.assertEqual(out["merged"], [
            {"base": ["time"], "extras": ["moon"]}, {"base": None, "extras": ["moon"]},
            {"base": ["date"], "extras": ["nerd"]}, {"base": ["time"], "extras": []}, {"base": None, "extras": []},
            {"base": ["time"], "extras": ["moon"]}], "nennt die Adresse nur Zusätze, bleibt die Auswahl des Profils; show ist schon zusammengeführt")
        self.assertEqual(out["low"], [], "zu niedrige Bühne: kein Platz")
        self.assertEqual(out["lowBanner"], ["moon"], "im Banner neben der Zeit")
        self.assertEqual(out["high"], ["moon"])
        self.assertEqual(out["nerdPreset"]["extras"], ["moon", "nerd", "progress"])
        self.assertEqual(out["none"], {"base": None, "extras": []})
        self.assertEqual(out["items"], ["moon", "nerd", "progress"])
        self.assertEqual(out["show"][-3:], out["items"])

    def test_schema_und_server(self):
        out = run_fx("""
          const entry = (n) => k.PARAM_SCHEMA.find((e) => e.name === n);
          const p = (q) => k.parseParams(q);
          console.log(JSON.stringify({ bin: entry("bin"), bars: entry("bars"), designs: k.DESIGNS, max: k.MAX_DESIGNS,
            ok: p("?design=binary&bin=plain&bars=year,day&show=progress"),
            bad: ["hex", "BCD", "<b>"].map((v) => p("?bin=" + encodeURIComponent(v)).bin),
            badBars: ["decade", "", "day;year"].map((v) => p("?bars=" + encodeURIComponent(v)).bars) }));
        """)
        self.assertEqual(out["bin"], {"name": "bin", "type": "enum", "values": ["bcd", "plain"], "default": "bcd"})
        self.assertEqual(out["bars"]["values"], ["day", "week", "month", "year", "timer"])
        self.assertIsNone(out["bars"]["default"])
        self.assertEqual(out["ok"]["design"], "binary")
        self.assertEqual(out["ok"]["bin"], "plain")
        self.assertEqual(out["ok"]["bars"], ["year", "day"])
        self.assertEqual(out["bad"], ["bcd"] * 3)
        self.assertEqual(out["badBars"], [None] * 3)
        self.assertLessEqual(len(out["designs"]), out["max"])
        self.assertEqual(out["max"], 8, "höchstens acht Designs (Konzept, Abschnitt 7)")
        self.assertEqual(list(clockprofiles.DESIGNS), out["designs"])
        self.assertEqual(clockprofiles.check_value("bin", "plain"), "plain")
        self.assertEqual(clockprofiles.check_value("bars", "day,timer"), "day,timer")
        self.assertEqual(clockprofiles.check_value("show", "moon,nerd,progress"), "moon,nerd,progress")
        for name, value in (("bin", "hex"), ("bars", "day,day"), ("bars", "decade"), ("show", "time,sun")):
            with self.subTest(name=name, value=value), self.assertRaises(clockprofiles.ProfileError):
                clockprofiles.check_value(name, value)
        nerd = clockprofiles.public_profile("nerd", {})
        self.assertIn("nerd", nerd["params"]["show"].split(","))
        self.assertIn("moon", nerd["params"]["show"].split(","))


class SeitenregelnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.fx = (JS / "clockextras.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")

    def body(self, name):
        start = self.js.index(name)
        return self.js[start:self.js.index("\n}\n", start)]

    def test_designauswahl_und_obergrenze(self):
        options = re.findall(r'<option value="([a-z]+)" data-i18n="clock\.design\.', self.html)
        self.assertEqual(options, list(clockprofiles.DESIGNS))
        self.assertLessEqual(len(options), 8)
        for lang in ("de", "en"):
            data = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            with self.subTest(lang=lang):
                self.assertTrue(data["design"]["binary"])
                self.assertEqual(sorted(data["moon"]), sorted(["new", "waxing_crescent", "first_quarter", "waxing_gibbous",
                                                               "full", "waning_gibbous", "last_quarter", "waning_crescent"]))
                self.assertEqual(sorted(data["nerd"]), sorted(["unix", "hex", "tai", "gps", "mjd", "doy", "iso", "roman"]))
                self.assertEqual(sorted(data["bar_say"]), ["day", "month", "week", "year"])
                self.assertEqual(sorted(data["link"]["bars_item"]), sorted(["day", "week", "month", "year", "timer"]))
                for key in ("day", "week", "month", "year", "timer", "pomo_work", "pomo_break", "pomo_long"):
                    self.assertTrue(data["bar"][key], key)
                self.assertTrue(data["link"]["f"]["bin"])
                self.assertTrue(data["link"]["f"]["bars"])
                self.assertIn("±1", data["moon_info"])

    def test_keine_neue_datei_kein_zeitgeber(self):
        self.assertNotRegex(self.fx, r"setTimeout|setInterval|requestAnimationFrame|fetch\(|localStorage\.|document\.")
        extras = self.js[self.js.index("// --- Zusätze C2"):self.js.index("// --- Prüfbild ?test=sync")]
        self.assertNotRegex(extras, r"setTimeout|setInterval|requestAnimationFrame|fetch\(|innerHTML")
        binary = self.js[self.js.index("// --- Design binary"):self.js.index("// --- Design tc")]
        self.assertNotRegex(binary, r"setTimeout|setInterval|requestAnimationFrame|innerHTML|\.style\b")
        self.assertIn("renderExtras(now.getTime(), { day, offset: zoned ? foreign : null,", self.body("function render("))
        public = [p for p in server.CLOCK_PUBLIC_PATHS if p.endswith(".js")]
        self.assertEqual(len(public), 11, "keine neue öffentliche Datei")

    def test_show_aufgeteilt_nach_dem_profil(self):
        start = self.body("async function start()")
        call = "fx.mergeShow(params.show, state.profileShow)"
        self.assertLess(start.index("await loadProfile()"), start.index(call))
        self.assertLess(start.index(call), start.index("applyDisplayParams()"))
        self.assertIn("params.show = split.base;", start)
        self.assertIn("state.profileShow = kit.parseParams(link.effectiveQuery({ profile: profile.params, zones: ZONES }), ZONES).show;",
                      self.body("async function loadProfile("))
        self.assertIn("fx.extrasShown({ extras: state.extraWish, fun: FUN_ON, kiosk: params.kiosk,\n"
                      "    layout: state.layout, eink: params.eink, height: state.stage.height, crowded })", self.body("function renderExtras("))

    def test_suedhalbkugel_nur_lokal(self):
        self.assertIn('const SOUTH_KEY = "ntp-gui-clock-south";', self.js)
        self.assertIn('store(SOUTH_KEY, state.south ? "1" : "0");', self.body("function toggleSouth("))
        self.assertNotIn("south", json.dumps(clockprofiles.PARAMS), "kein Parameter, kein Profilfeld")
        self.assertIn("$(\"moon\").disabled = !CONTROLS.fun;", self.body("function renderMoon("))
        self.assertIn("if (!CONTROLS.fun) return;", self.body("function toggleSouth("))

    def test_balken_nur_per_transform_und_cssom(self):
        self.assertIn("transform: scaleX(var(--bar, 0));", self.css)
        self.assertIn('bar.fill.style.setProperty("--bar", ', self.body("function renderBars("))
        self.assertIn('node.setAttribute("role", "progressbar");', self.body("function buildBars("))
        self.assertIn('.clock-stage:is([data-layout="strip"], [data-layout="tile"]) .clock-extras { display: none; }', self.css)
        self.assertNotRegex(self.css[self.css.index("Studiouhr C2"):], r"animation|transition|filter:")

    def test_hoehe_der_zusaetze_beobachtet(self):
        watch = self.body("function watchExtras(")
        self.assertIn("new window.ResizeObserver(", watch)
        self.assertIn("if (height === state.extrasHeight", watch)
        self.assertIn('for (const node of [$("clock-stage"), ...$("clock-main").children]) observer.observe(node);', watch)
        self.assertIn("EXTRAS_REFITS", watch, "begrenzt: kein Hin und Her")
        self.assertIn("watchExtras();", self.body("async function start()"))
        self.assertIn('state.extrasHeight = $("extras").offsetHeight;', self.body("function fitTimeOnly("))

    def test_zusaetze_ohne_platz_fallen_weg(self):
        self.assertIn("checkExtrasRoom();", self.body("function fitTime("))
        room = self.body("function checkExtrasRoom(")
        self.assertIn("state.extrasNoRoom = true;", room)
        self.assertIn('if (state.extrasNoRoom || box.hidden || !state.face || state.layout !== "banner") return;', room,
                      "keine Schleife, nur im Banner")
        self.assertIn("state.extrasNoRoom ? [] : fx.extrasShown(", self.body("function renderExtras("))
        self.assertIn("state.extrasNoRoom = false;", self.body("function applyLayout("), "neue Größe: neuer Versuch")

    def test_banner_raster_mit_countdown_und_weltzeit(self):
        for areas in ('"time date" "time sub" "time extras"', '"time cd" "time date" "time sub" "time extras"',
                      '"time date" "time sub" "time world" "time extras"',
                      '"time cd" "time date" "time sub" "time world" "time extras"'):
            self.assertIn(f"grid-template-areas: {areas};", self.css)
        c2 = self.css[self.css.index("Studiouhr C2"):]
        self.assertIn(':root[data-cd="below"] .clock-stage[data-layout="banner"][data-world="bar"] .clock-main', c2,
                      "spätere Regel mit mindestens gleicher Spezifität")

    def test_banner_mit_zusaetzen_haelt_abstand_zum_rand(self):
        # Befund 1.10: Mit Zusätzen füllt das Banner-Raster die ganze Breite – ein eigener Innenabstand hält Zeit und
        # Nerd-Zeile vom Bildrand fern (3840 × 1080: 48 px), ohne ihn stießen beide an den Rand.
        c2 = self.css[self.css.index("Studiouhr C2"):]
        self.assertIn('.clock-stage[data-layout="banner"] .clock-main:has(> .clock-extras:not([hidden])) { padding-inline: 1.25cqw; }', c2)

    def test_mondtitel_ohne_doppelpunkt(self):
        for lang in ("de", "en"):
            data = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            date = data["moon_date"].replace("{d}", "24").replace("{m}", "11")
            for key in ("moon_next_full", "moon_next_new"):
                with self.subTest(lang=lang, key=key):
                    self.assertNotIn("..", data[key].replace("{date}", date))

    def test_nerd_im_tag_der_anzeige(self):
        nerd = self.body("function renderNerd(")
        self.assertIn("const day = at.day instanceof Date ? at.day : new Date(nowMs);", nerd)
        self.assertIn("isoWeek(day)", nerd)
        self.assertNotIn("isoWeek(now)", nerd)
        self.assertIn("fx.romanTime(at.h, at.m)", nerd)
        self.assertIn("(state.extrasAt || {}).offset", self.body("function renderBars("))

    def test_tai_aus_dem_server(self):
        nerd = self.body("function renderNerd(")
        self.assertIn("fx.nerdValues(nowMs, status.tai_utc)", nerd)
        self.assertIn('v.taiMs === null ? "–"', nerd)


if __name__ == "__main__":
    unittest.main()
