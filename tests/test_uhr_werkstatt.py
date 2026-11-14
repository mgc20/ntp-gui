"""Uhr-Werkstatt (1.6, T6): Designs, Adressparameter, Ton auf der Sekunde, Geräteversatz, Osterei.

Die reinen Rechnungen stehen in app/static/js/clockkit.js und laufen hier mit Node: Zeigerwinkel der
Bahnhofsuhr, Wortuhr für alle Fünf-Minuten-Schritte (deutsch und englisch), Klappzahlen, Allowlist der
Parameter, Ton-Planung mit gemockter AudioContext (Start innerhalb ±2 ms der vollen Serversekunde).
Dazu der Server-Teil (leap_next in /api/v1/time, öffentliche Dateien) und Regeln für clock.js/clock.css
(CSS statt JS-Schleife, ruhig mit prefers-reduced-motion, Versatz bleibt im Browser).
"""

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
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import leap  # noqa: E402
import server  # noqa: E402

LEAP_REAL = Path(__file__).resolve().parent / "fixtures" / "leap-seconds.list"


# Standardwerte der Darstellungsparameter (Studiouhr A3/A4), damit die Erwartungen kurz bleiben.
DISPLAY_DEFAULTS = {"layout": "auto", "safe": None, "bg": None, "scale": 100, "show": None, "weight": None, "shift": None,
                    "color": "amber", "sub": "utc", "seconds": "both", "h12": False, "face": "sans", "colon": "steady",
                    "lz": True, "date": "long", "look": None, "accent": None,
                    # Countdown und Timer (A5)
                    "until": None, "timer": None, "after": "up", "warn": [300, 60, 10], "beep": 0, "label": None,
                    "cd": "below", "lock": False}


def run_kit(code: str):
    module = json.dumps((JS / "clockkit.js").as_uri())
    script = f"import * as k from {module};\n{code}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ClockKitTest(unittest.TestCase):
    def test_zeigerwinkel(self):
        out = run_kit("""
          console.log(JSON.stringify({
            a: k.handAngles(10, 15, 42, 500), b: k.handAngles(0, 0, 0, 0), c: k.handAngles(23, 59, 58, 600),
            d: k.handAngles(12, 30, 29, 250), e: k.handAngles(3, 0, 59, 999), step: k.handAngles(10, 15, 42, 500, { step: true }),
            half: k.handAngles(6, 0, 29, 250),
          }));
        """)
        self.assertEqual((out["a"]["hour"], out["a"]["minute"]), (307.5, 90))
        self.assertAlmostEqual(out["a"]["second"], 42.5 / 58.5 * 360, places=6)
        self.assertEqual(out["b"], {"hour": 0, "minute": 0, "second": 0})
        self.assertEqual((out["c"]["hour"], out["c"]["minute"]), (359.5, 354))
        self.assertEqual(out["c"]["second"], 0, "nach 58,5 s wartet der Zeiger auf der 12")
        self.assertEqual(out["e"]["second"], 0)
        self.assertEqual((out["d"]["hour"], out["d"]["minute"]), (15, 180))
        self.assertAlmostEqual(out["half"]["second"], 180, places=6, msg="29,25 s = halbe Runde von 58,5 s")
        self.assertEqual(out["step"]["second"], 252, "ruhig: sekundenweise springen")

    def test_wortuhr_alle_fuenf_minuten(self):
        out = run_kit("""
          const de = [], en = [];
          for (let m = 0; m < 60; m += 5) { de.push(k.wordClock(10, m, "de").text); en.push(k.wordClock(10, m, "en").text); }
          console.log(JSON.stringify({ de, en, dots: [0, 1, 2, 3, 4, 7, 59].map((m) => k.wordClock(10, m).dots),
            one: k.wordClock(13, 0).text, halfOne: k.wordClock(0, 30).text, midnight: k.wordClock(0, 0).text,
            noon: k.wordClock(11, 55).text, enOne: k.wordClock(1, 0, "en").text, enTwelve: k.wordClock(23, 40, "en").text,
            round: k.wordClock(10, 19).text }));
        """)
        self.assertEqual(out["de"], [
            "ES IST ZEHN UHR", "ES IST FÜNF NACH ZEHN", "ES IST ZEHN NACH ZEHN", "ES IST VIERTEL NACH ZEHN",
            "ES IST ZWANZIG NACH ZEHN", "ES IST FÜNF VOR HALB ELF", "ES IST HALB ELF", "ES IST FÜNF NACH HALB ELF",
            "ES IST ZWANZIG VOR ELF", "ES IST VIERTEL VOR ELF", "ES IST ZEHN VOR ELF", "ES IST FÜNF VOR ELF"])
        self.assertEqual(out["en"], [
            "IT IS TEN O'CLOCK", "IT IS FIVE PAST TEN", "IT IS TEN PAST TEN", "IT IS QUARTER PAST TEN",
            "IT IS TWENTY PAST TEN", "IT IS TWENTY-FIVE PAST TEN", "IT IS HALF PAST TEN", "IT IS TWENTY-FIVE TO ELEVEN",
            "IT IS TWENTY TO ELEVEN", "IT IS QUARTER TO ELEVEN", "IT IS TEN TO ELEVEN", "IT IS FIVE TO ELEVEN"])
        self.assertEqual(out["dots"], [0, 1, 2, 3, 4, 2, 4])
        self.assertEqual(out["one"], "ES IST EIN UHR")
        self.assertEqual(out["halfOne"], "ES IST HALB EINS")
        self.assertEqual(out["midnight"], "ES IST ZWÖLF UHR")
        self.assertEqual(out["noon"], "ES IST FÜNF VOR ZWÖLF")
        self.assertEqual(out["enOne"], "IT IS ONE O'CLOCK")
        self.assertEqual(out["enTwelve"], "IT IS TWENTY TO TWELVE")
        self.assertEqual(out["round"], "ES IST VIERTEL NACH ZEHN", "abgerundet auf fünf Minuten")

    def test_klappzahlen(self):
        out = run_kit("""
          console.log(JSON.stringify({
            digits: k.timeDigits(9, 5, 7), short: k.timeDigits(9, 5, 7, false),
            first: k.flipDigits("", "101542"), next: k.flipDigits("101542", "101543"),
            hour: k.flipDigits("095959", "100000"), length: k.flipDigits("1015", "101500"),
          }));
        """)
        self.assertEqual(out["digits"], "090507")
        self.assertEqual(out["short"], "0905")
        self.assertFalse(any(d["changed"] for d in out["first"]), "erster Aufbau klappt nicht")
        self.assertEqual("".join(d["digit"] for d in out["first"]), "101542")
        self.assertEqual([d["changed"] for d in out["next"]], [False] * 5 + [True])
        self.assertEqual([d["changed"] for d in out["hour"]], [True, True, True, True, True, True])
        self.assertFalse(any(d["changed"] for d in out["length"]))

    def test_parameter_allowlist(self):
        out = run_kit("""
          const zones = ["Europe/Berlin", "America/New_York"];
          const p = (q) => k.parseParams(q, zones);
          console.log(JSON.stringify({
            ok: p("?design=wort&kiosk=1&eink=0&tz=America/New_York"),
            bad: p("?design=<script>&kiosk=yes&eink=2&tz=Mars/Olympus&x=1"),
            long: p("?tz=" + "A".repeat(200)),
            empty: p(""), none: k.parseParams("?tz=Europe/Berlin", [], {}),
            safe: [k.safeDesign("nixie"), k.safeDesign("../x"), k.safeDesign(null)],
            label: k.zoneLabel("America/New_York"), designs: k.DESIGNS,
            zones: k.supportedZones().includes("Europe/Berlin"),
            noIntl: k.supportedZones({}),
          }));
        """)
        self.assertEqual(out["ok"], {"design": "wort", "kiosk": True, "eink": False, "tz": "America/New_York",
                                     "lead": 0, "maxerr": 100, **DISPLAY_DEFAULTS, "ignored": []})
        self.assertEqual(out["bad"], {"design": None, "kiosk": False, "eink": False, "tz": None,
                                      "lead": 0, "maxerr": 100, **DISPLAY_DEFAULTS,
                                      "ignored": ["design", "kiosk", "eink", "tz"]})
        self.assertIsNone(out["long"]["tz"])
        self.assertEqual(out["empty"]["ignored"], [])
        self.assertIsNone(out["none"]["tz"], "ohne Liste und ohne Intl keine Zeitzone")
        self.assertEqual(out["safe"], ["nixie", "digital", "digital"])
        self.assertEqual(out["label"], "New York")
        self.assertEqual(out["designs"], ["digital", "studio", "bahnhof", "nixie", "flip", "wort"])
        self.assertTrue(out["zones"], "Node kennt Intl.supportedValuesOf")
        self.assertEqual(out["noIntl"], [])

    def test_zeitzone_kanonische_namen_und_utc(self):
        # V8 listet in supportedValuesOf nur CLDR-Altnamen (Asia/Calcutta) und kein UTC – gültige
        # IANA-Namen nimmt die Uhr trotzdem an; geprüft wird mit Intl.DateTimeFormat, streng nach Zeichen.
        out = run_kit("""
          const p = (q) => k.parseParams(q, k.supportedZones()).tz;
          console.log(JSON.stringify({
            ok: ["UTC", "Asia/Kolkata", "Europe/Kyiv", "Asia/Ho_Chi_Minh", "Etc/GMT+5", "Europe/London", "Asia/Calcutta"]
              .map((z) => p("?tz=" + encodeURIComponent(z))),
            bad: ["Mars/Olympus", "Europe/Berlin<x>", "Europe/Berlin%20", "../etc", "", "Europe/" + "A".repeat(80)]
              .map((z) => p("?tz=" + encodeURIComponent(z))),
            ignored: k.parseParams("?tz=Mars/Olympus", k.supportedZones()).ignored,
            noIntl: k.parseParams("?tz=Asia/Kolkata", [], {}).tz,
            listOnly: k.parseParams("?tz=Europe/Berlin", ["Europe/Berlin"], {}).tz,
          }));
        """)
        self.assertEqual(out["ok"], ["UTC", "Asia/Kolkata", "Europe/Kyiv", "Asia/Ho_Chi_Minh", "Etc/GMT+5",
                                     "Europe/London", "Asia/Calcutta"])
        self.assertEqual(out["bad"], [None] * 6)
        self.assertEqual(out["ignored"], ["tz"])
        self.assertIsNone(out["noIntl"], "ohne Intl keine zweite Zeitzone")
        self.assertEqual(out["listOnly"], "Europe/Berlin")

    def test_ton_auf_der_vollen_sekunde(self):
        """Gemockte AudioContext: Jeder Ton startet innerhalb ±2 ms der vollen Serversekunde (nach Versatz)."""
        out = run_kit("""
          const started = [];
          const param = () => ({ setValueAtTime() {}, linearRampToValueAtTime() {} });
          function fakeCtx({ currentTime, stamp, outputLatency = 0 }) {
            return {
              currentTime, outputLatency, destination: {},
              getOutputTimestamp: stamp ? () => stamp : undefined,
              createOscillator: () => ({ type: "", frequency: { value: 0 }, connect() {}, start(at) { started.push(at); }, stop() {} }),
              createGain: () => ({ gain: param(), connect() {} }),
            };
          }
          const results = [];
          // Browseruhr geht 3,2006 s nach; Ausgabezeitstempel 20 ms alt; zwei krumme Ausgangslagen.
          for (const [wall, perf, offset, stamp, latency] of [
            [1782807342123.4, 5020.25, 3200.6, { contextTime: 12.3, performanceTime: 5000.25 }, 0],
            [1782807420987.9, 812345.5, -1234.25, { contextTime: 801.004, performanceTime: 812330.0 }, 0],
            [1782807342777.7, 4000, 15.5, null, 0.0213],
          ]) {
            started.length = 0;
            const ctx = fakeCtx({ currentTime: stamp ? stamp.contextTime + 0.02 : 50.5, stamp, outputLatency: latency });
            const clock = k.audioClock(ctx, perf, wall, offset);
            const plan = k.planTones(clock, { mode: "seconds", horizonMs: 3000 });
            for (const tone of plan) k.scheduleTone(ctx, tone);
            // Unabhängig nachrechnen: Wann (Browseruhr) kommt der Ton aus dem Gerät, welche Serverzeit ist das?
            const errors = started.map((at) => {
              const heardWall = stamp ? wall - (perf - stamp.performanceTime) + (at - stamp.contextTime) * 1000
                : wall + (at - (ctx.currentTime - latency)) * 1000;
              const server = heardWall + offset;
              return server - Math.round(server / 1000) * 1000;
            });
            results.push({ errors, seconds: plan.map((t) => t.second), kinds: plan.map((t) => t.kind),
              exact: clock.exact, ahead: plan.map((t) => t.at - ctx.currentTime) });
          }
          const cd = k.planTones({ audio: 0, server: 1782807340000.5 }, { mode: "countdown", horizonMs: 25000 });
          const after = k.planTones({ audio: 0, server: 1782807340000.5 }, { afterSecond: 1782807341, horizonMs: 3000 });
          console.log(JSON.stringify({ results, countdown: cd.map((t) => [t.second % 60, t.kind]),
            after: after.map((t) => t.second), values: [k.countdownValue(1782807349999), k.countdownValue(1782807350000),
              k.countdownValue(1782807359500), k.countdownValue(1782807360200)] }));
        """)
        for result in out["results"]:
            self.assertGreaterEqual(len(result["errors"]), 2)
            for error in result["errors"]:
                self.assertLessEqual(abs(error), 2.0, f"Ton {error} ms neben der vollen Sekunde")
            self.assertEqual(result["seconds"], sorted(result["seconds"]))
            self.assertTrue(all(b - a == 1 for a, b in zip(result["seconds"], result["seconds"][1:])))
            self.assertTrue(all(a > -0.03 for a in result["ahead"]))
        self.assertTrue(out["results"][0]["exact"])
        self.assertFalse(out["results"][2]["exact"], "ohne getOutputTimestamp: currentTime minus Latenz")
        # Sekunde …420 ist eine volle Minute (1782807420 % 60 == 0): langer Ton.
        kinds = dict(zip(out["results"][1]["seconds"], out["results"][1]["kinds"]))
        self.assertEqual(kinds.get(1782807420), "long")
        self.assertEqual(kinds.get(1782807421), "short")
        self.assertEqual(out["countdown"], [[50, "count"], [51, "count"], [52, "count"], [53, "count"], [54, "count"],
                                            [55, "count"], [56, "count"], [57, "count"], [58, "count"], [59, "count"],
                                            [0, "long"]])
        self.assertEqual(out["after"], [1782807342, 1782807343])
        self.assertEqual(out["values"], [None, 10, 1, 0])

    def test_geraeteversatz(self):
        out = run_kit("""
          console.log(JSON.stringify({
            exact: k.deviceDrift(1.2, 2), good: k.deviceDrift(-80, 2), warn: k.deviceDrift(420, 3),
            crit: k.deviceDrift(-3200, 3), none: k.deviceDrift(NaN),
            fmt: [k.fmtDrift(42.4), k.fmtDrift(3200), k.fmtDrift(12345), k.fmtDrift(125000), k.fmtDrift(-999.6)],
          }));
        """)
        self.assertEqual(out["exact"], {"tone": "good", "dir": "exact", "abs": 1.2})
        self.assertEqual(out["good"]["dir"], "ahead", "negativer Versatz: Gerät geht vor")
        self.assertEqual(out["good"]["tone"], "good")
        self.assertEqual((out["warn"]["tone"], out["warn"]["dir"]), ("warn", "behind"))
        self.assertEqual((out["crit"]["tone"], out["crit"]["dir"]), ("crit", "ahead"))
        self.assertIsNone(out["none"])
        self.assertEqual(out["fmt"], ["42 ms", "3,2 s", "12 s", "2 min 5 s", "1000 ms"])

    def test_geraeteversatz_bei_ungenauer_messung(self):
        # Grün „weniger als 0,1 s daneben“ nur, wenn auch |Versatz| + Genauigkeit unter 0,1 s bleibt.
        out = run_kit("""
          console.log(JSON.stringify([k.deviceDrift(150, 200), k.deviceDrift(900, 1200), k.deviceDrift(-40, 99),
                                      k.deviceDrift(150, 120), k.deviceDrift(0, 100), k.deviceDrift(99, 99),
                                      k.deviceDrift(60, 50), k.deviceDrift(-70, 29), k.deviceDrift(60, 39),
                                      k.deviceDrift(-30, 40), k.deviceDrift(40, 60)]));
        """)
        self.assertEqual(out[0], {"tone": "unknown", "dir": "uncertain", "abs": 150})
        self.assertEqual(out[1], {"tone": "unknown", "dir": "uncertain", "abs": 900})
        self.assertEqual(out[2], {"tone": "unknown", "dir": "uncertain", "abs": 40}, "40 ± 99 ms: bis 139 ms möglich")
        self.assertEqual((out[3]["tone"], out[3]["dir"]), ("warn", "behind"), "sicher außerhalb der Genauigkeit")
        self.assertEqual(out[4]["dir"], "uncertain")
        self.assertEqual(out[5], {"tone": "unknown", "dir": "uncertain", "abs": 99}, "99 ± 99 ms: bis 198 ms möglich")
        self.assertEqual(out[6], {"tone": "unknown", "dir": "uncertain", "abs": 60}, "60 ± 50 ms: bis 110 ms möglich")
        self.assertEqual((out[7]["tone"], out[7]["dir"]), ("good", "ahead"), "70 ± 29 ms: höchstens 99 ms")
        self.assertEqual((out[8]["tone"], out[8]["dir"]), ("good", "behind"), "60 ± 39 ms: höchstens 99 ms")
        self.assertEqual(out[9], {"tone": "good", "dir": "exact", "abs": 30})
        self.assertEqual(out[10]["dir"], "uncertain", "Grenzfall 40 + 60 = 100 ms ist nicht mehr grün")

    def test_fmt_drift_rundet_vor_dem_aufteilen(self):
        # Erst auf ganze Sekunden runden, dann Minuten und Sekunden ableiten: nie „60 s“ oder „1 min 60 s“.
        out = run_kit("console.log(JSON.stringify([59600, 59999, 60000, 119600, 3599700, 9960, 9940, 999.4, -119600]"
                      ".map((v) => k.fmtDrift(v))));")
        self.assertEqual(out, ["1 min 0 s", "1 min 0 s", "1 min 0 s", "2 min 0 s", "60 min 0 s", "10 s", "9,9 s",
                               "999 ms", "2 min 0 s"])

    def test_osterei_schaltsekunde(self):
        out = run_kit("""
          const at = (s) => Date.parse(s);
          console.log(JSON.stringify([
            k.leapEgg(at("2026-06-30T08:15:42Z"), "Normal", null),
            k.leapEgg(at("2026-12-31T23:59:59Z"), "Normal", "2027-01-01"),
            k.leapEgg(at("2026-06-30T12:00:00Z"), "Insert second", null),
            k.leapEgg(at("2026-06-30T12:00:00Z"), "Delete second", null),
            k.leapEgg(at("2026-07-01T00:00:00Z"), "Insert second", "2026-07-01"),
            k.leapEgg(at("2026-06-29T23:59:59Z"), "Normal", null),
            k.leapEgg(at("2026-12-31T12:00:00Z"), "Normal", "2027-07-01"),
          ]));
        """)
        self.assertEqual(out, ["possible", "insert", "insert", "delete", None, None, "possible"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ZeitbasisTest(unittest.TestCase):
    """Studiouhr A1: Anker auf performance.now(), Fehlerschranke, Zustände, ausgegraute Stellen."""

    def test_sprung_der_geraeteuhr_veraendert_die_anzeige_nicht(self):
        # Messung wie in clock.js: t0/t3 aus der Geräteuhr, t1/t2 vom Server, perf = performance.now() bei t3.
        # Danach springt Date.now() um +1 h bzw. −1 h; die Anzeige folgt nur performance.now().
        out = run_kit("""
          const server = Date.parse("2026-06-30T08:15:42.500Z");
          const wall0 = server - 300000, perf0 = 1000, rtt = 8;
          const t0 = wall0, t3 = wall0 + rtt, t1 = server, t2 = server;
          const offset = ((t1 - t0) + (t2 - t3)) / 2;
          const anchor = k.anchorFrom({ offset, rtt, accuracy: rtt / 2, at: t3, perf: perf0 + rtt });
          const shown = (perf, wall) => new Date(k.anchoredNow(anchor, perf, wall)).toISOString();
          const old = (wall) => new Date(wall + offset).toISOString();   // frühere Rechnung: Date.now() + Versatz
          const perf = perf0 + rtt + 1500, wallNormal = t3 + 1500;
          console.log(JSON.stringify({
            normal: shown(perf, wallNormal), ahead: shown(perf, wallNormal + 3600000), behind: shown(perf, wallNormal - 3600000),
            oldNormal: old(wallNormal), oldAhead: old(wallNormal + 3600000),
            none: k.anchoredNow(null, perf, 12345), bad: k.anchorFrom({ offset: 1, at: 2 }),
          }));
        """)
        self.assertEqual(out["normal"], "2026-06-30T08:15:44.004Z")
        self.assertEqual(out["ahead"], out["normal"], "Geräteuhr +1 h: Anzeige unverändert")
        self.assertEqual(out["behind"], out["normal"], "Geräteuhr −1 h: Anzeige unverändert")
        self.assertEqual(out["oldNormal"], out["normal"])
        self.assertNotEqual(out["oldAhead"], out["normal"], "die alte Rechnung wäre mitgesprungen")
        self.assertEqual(out["none"], 12345, "ohne Anker: Gerätezeit")
        self.assertIsNone(out["bad"], "ohne perf kein Anker")

    def test_standby_und_uhrsprung_gelten_nicht_als_abgeglichen(self):
        # Plattformen, deren performance.now() im Systemschlaf steht: 1 h Standby fehlt im Anker. Ebenso eine
        # verstellte Geräteuhr bei stehender monotoner Uhr. Beides erkennt wallJump; bis zum neuen Anker degraded.
        out = run_kit("""
          const server0 = Date.UTC(2026, 10, 13, 12, 0, 0);
          const anchor = k.anchorFrom({ at: server0, offset: 0, perf: 1000 });
          const bound = k.errorBound({ serverAccMs: 1, rttMs: 4, ageMs: 1500 });
          const state = (jumped) => k.syncState({ anchored: true, sinceOkMs: 1500, boundMs: jumped ? null : bound, jumped });
          const sleep = k.wallJump(anchor, 2500, server0 + 3600000 + 1500);   // perf ohne Schlafzeit, Date mit
          const jump = k.wallJump(anchor, 1000, server0 + 3600000);           // perf steht, Date.now +1 h
          const back = k.wallJump(anchor, 1000, server0 - 3600000);
          console.log(JSON.stringify({
            wall: anchor.wall, sleep, jump, back,
            normal: k.wallJump(anchor, 61000, server0 + 60000),
            slew: k.wallJump(anchor, 61000, server0 + 60000 + 1999),
            limit: k.wallJump(anchor, 61000, server0 + 60000 + 2001),
            noWall: k.wallJump({ server: 1, perf: 1 }, 5, 1e12), noAnchor: k.wallJump(null, 5, 1e12),
            stateJump: state(jump), stateSleep: state(sleep), stateNormal: state(false),
            freeButJumped: k.syncState({ anchored: true, sinceOkMs: 60000, boundMs: bound, jumped: true }),
            noneStaysNone: k.syncState({ anchored: false, jumped: true }),
            fine: k.fineDigits(null).seconds, consts: k.WALL_JUMP_MS,
          }));
        """)
        self.assertEqual(out["wall"], 1794571200000, "Anker merkt sich t3 der Geräteuhr")
        self.assertTrue(out["sleep"], "Standby mit stehender monotoner Uhr erkannt")
        self.assertTrue(out["jump"], "Geräteuhr +1 h bei stehender monotoner Uhr erkannt")
        self.assertTrue(out["back"])
        self.assertFalse(out["normal"])
        self.assertFalse(out["slew"], "unter 2 s Abweichung: kein Sprung")
        self.assertTrue(out["limit"])
        self.assertFalse(out["noWall"])
        self.assertFalse(out["noAnchor"])
        self.assertEqual(out["stateJump"], "degraded", "data-sync darf nach dem Uhrsprung nicht ok sein")
        self.assertEqual(out["stateSleep"], "degraded")
        self.assertEqual(out["stateNormal"], "ok")
        self.assertEqual(out["freeButJumped"], "degraded", "auch ohne Antwort nicht als frei laufend mit Schranke")
        self.assertEqual(out["noneStaysNone"], "none")
        self.assertEqual(out["fine"], "unsure", "unbekannte Schranke: Sekunden grau")
        self.assertEqual(out["consts"], 2000)

    def test_fehlerschranke_waechst_mit_dem_alter(self):
        out = run_kit("""
          const b = (age, extra = {}) => k.errorBound({ serverAccMs: 0.4, rttMs: 6, ageMs: age, ...extra });
          console.log(JSON.stringify({
            ages: [0, 1000, 60000, 600000, 3600000].map((a) => b(a)),
            frame: b(0, { frameMs: 8.3 }), badFrame: b(0, { frameMs: -1 }),
            noAcc: k.errorBound({ serverAccMs: NaN, rttMs: 6, ageMs: 0 }), empty: k.errorBound(),
            consts: [k.DRIFT_PPM, k.FRAME_MS, k.STALE_MS, k.TICK_GAP_MS],
          }));
        """)
        ages = out["ages"]
        self.assertAlmostEqual(ages[0], 0.4 + 3 + 17, places=9, msg="Server + RTT/2 + ein Bild")
        self.assertTrue(all(b > a for a, b in zip(ages, ages[1:])), ages)
        self.assertAlmostEqual(ages[3] - ages[0], 30.0, places=6, msg="50 ppm × 10 min = 30 ms")
        self.assertAlmostEqual(ages[4] - ages[0], 180.0, places=6)
        self.assertAlmostEqual(out["frame"], 0.4 + 3 + 8.3, places=9)
        self.assertAlmostEqual(out["badFrame"], ages[0], places=9)
        self.assertIsNone(out["noAcc"], "ohne Server-Genauigkeit keine belegbare Schranke")
        self.assertIsNone(out["empty"])
        self.assertEqual(out["consts"], [50, 17, 10000, 2000])

    def test_zustaende(self):
        out = run_kit("""
          const s = (o) => k.syncState(o);
          console.log(JSON.stringify([
            s({}), s({ anchored: false, sinceOkMs: 0, boundMs: 1 }),
            s({ anchored: true, sinceOkMs: 500, boundMs: 20 }),
            s({ anchored: true, sinceOkMs: 10001, boundMs: 20 }),
            s({ anchored: true, sinceOkMs: Infinity, boundMs: 500 }),
            s({ anchored: true, sinceOkMs: 500, boundMs: 101 }),
            s({ anchored: true, sinceOkMs: 500, boundMs: 101, maxerrMs: 200 }),
            s({ anchored: true, sinceOkMs: 500, boundMs: null }),
            s({ anchored: true, sinceOkMs: 500, boundMs: 20, serverSynced: false }),
            s({ anchored: true, sinceOkMs: 10000, boundMs: 100 }),
          ]));
        """)
        self.assertEqual(out, ["none", "none", "ok", "free", "free", "degraded", "ok", "degraded", "degraded", "ok"])

    def test_feinste_stelle(self):
        out = run_kit("""
          const f = (b, o) => k.fineDigits(b, o);
          console.log(JSON.stringify({
            sharp: f(10), tenthsGrey: f(51), frameGrey: f(21), frameSure: f(19),
            degraded: f(101), secondsGrey: f(501, { maxerrMs: 1000 }), fps50: f(11, { fps: 50 }),
            unknown: f(null), custom: f(150, { maxerrMs: 200 }),
          }));
        """)
        self.assertEqual(out["sharp"], {"seconds": "sure", "tenths": "sure", "frames": "sure"})
        self.assertEqual(out["tenthsGrey"]["tenths"], "unsure", "Zehntel ab > 50 ms grau")
        self.assertEqual(out["frameGrey"]["frames"], "unsure", "25 fps: ab > 20 ms (½ Frame) grau")
        self.assertEqual(out["frameSure"]["frames"], "sure")
        self.assertEqual(out["degraded"], {"seconds": "sure", "tenths": "off", "frames": "off"},
                         "über maxerr verschwinden Zehntel und Frames")
        self.assertEqual(out["secondsGrey"]["seconds"], "unsure", "ab > 0,5 s trägt die Schranke keine Sekunden")
        self.assertEqual(out["fps50"]["frames"], "unsure", "50 fps: ½ Frame = 10 ms")
        self.assertEqual(out["unknown"], {"seconds": "unsure", "tenths": "off", "frames": "off"})
        self.assertEqual(out["custom"]["tenths"], "unsure")

    def test_taktluecke_bildauffrischung_dauer(self):
        out = run_kit("""
          console.log(JSON.stringify({
            gap: [k.tickGap(1000, 2000, 1000), k.tickGap(1000, 4000, 1000), k.tickGap(1000, 4001, 1000),
                  k.tickGap(0, 61000, 60000), k.tickGap(0, 62001, 60000), k.tickGap(NaN, 5000, 1000)],
            frame: [k.frameFromStamps([0, 16.7, 33.4, 50.1, 66.8, 83.5]), k.frameFromStamps([0, 8.3, 16.6, 25, 33.3]),
                    k.frameFromStamps([0, 1000, 2000]), k.frameFromStamps([]), k.frameFromStamps(null)],
            age: [k.fmtAge(25400), k.fmtAge(185000), k.fmtAge(7300000), k.fmtAge(-1)],
          }));
        """)
        self.assertEqual(out["gap"], [False, False, True, False, True, False])
        self.assertAlmostEqual(out["frame"][0], 16.7, places=6)
        self.assertAlmostEqual(out["frame"][1], 8.3, delta=0.05)
        self.assertEqual(out["frame"][2:], [17, 17, 17], "Hintergrund-Tab oder nichts gemessen: 17 ms")
        self.assertEqual(out["age"], ["25 s", "3 min", "2 h", "–"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ParameterSchemaTest(unittest.TestCase):
    """Studiouhr A2: parseParams über PARAM_SCHEMA, mit Fuzzing aller Parameter."""

    HOSTILE = [
        "<script>alert(1)</script>", "javascript:alert(1)", "red;background:url(https://example.com/x.png)",
        "1;color:red", "\"><img src=x onerror=alert(1)>", "'", "`", "\\u0000", "\u0000", "\u0007", "\u001b[31m",
        "‮evil", "​1", "1​", "\ud800", "%00", "%3Cb%3E", "a" * 65, "1" * 70, "9" * 5000,
        " 1", "1 ", "+1", "-1", "1e2", "0x10", "1.5", "NaN", "Infinity", "", "null", "undefined", "__proto__",
        "constructor", "toString", "../../etc/passwd", "Europe/Berlin\n", "data:text/html,<b>",
    ]

    def test_schema_tabelle(self):
        out = run_kit("""
          console.log(JSON.stringify({ schema: k.PARAM_SCHEMA, defaults: k.paramDefaults(), frozen: Object.isFrozen(k.PARAM_SCHEMA)
            && k.PARAM_SCHEMA.every((e) => Object.isFrozen(e)) }));
        """)
        names = [entry["name"] for entry in out["schema"]]
        self.assertEqual(names, ["design", "kiosk", "eink", "tz", "lead", "maxerr", *DISPLAY_DEFAULTS])
        types = {entry["name"]: entry["type"] for entry in out["schema"]}
        self.assertEqual(types, {"design": "enum", "kiosk": "flag", "eink": "flag", "tz": "zone", "lead": "int",
                                 "maxerr": "int", "layout": "enum", "safe": "int", "bg": "enum", "scale": "int",
                                 "show": "list", "weight": "enum", "shift": "int", "color": "enum", "sub": "enum",
                                 "seconds": "enum", "h12": "flag", "face": "enum", "colon": "enum", "lz": "flag",
                                 "date": "enum", "look": "enum", "accent": "color", "until": "time",
                                 "timer": "duration", "after": "enum", "warn": "intlist", "beep": "int", "label": "label",
                                 "cd": "enum", "lock": "flag"})
        lead = next(e for e in out["schema"] if e["name"] == "lead")
        self.assertEqual((lead["min"], lead["max"], lead["default"]), (0, 200, 0))
        self.assertEqual(out["defaults"], {"design": None, "kiosk": False, "eink": False, "tz": None, "lead": 0,
                                           "maxerr": 100, **DISPLAY_DEFAULTS})
        self.assertTrue(out["frozen"])
        for forbidden in ("lat", "lon", "latitude", "longitude", "location", "geo"):
            self.assertNotIn(forbidden, names, "keine Standortangaben im Schema")

    def test_gueltige_werte(self):
        out = run_kit("""
          const z = k.supportedZones();
          const p = (q) => k.parseParams(q, z);
          console.log(JSON.stringify({
            lead: ["0", "40", "200", "007"].map((v) => p("?lead=" + v).lead),
            maxerr: ["10", "250", "1000"].map((v) => p("?maxerr=" + v).maxerr),
            flags: ["1", "0", "true", "false"].map((v) => p("?kiosk=" + v).kiosk),
            first: p("?lead=40&lead=80").lead, unknown: p("?foo=1&lat=48.1&lon=11.5&bar=<x>"),
            all: p("?design=nixie&kiosk=1&eink=1&tz=UTC&lead=120&maxerr=50"),
          }));
        """)
        self.assertEqual(out["lead"], [0, 40, 200, 7])
        self.assertEqual(out["maxerr"], [10, 250, 1000])
        self.assertEqual(out["flags"], [True, False, True, False])
        self.assertEqual(out["first"], 40, "doppelte Namen: der erste gilt")
        self.assertEqual(out["unknown"], {"design": None, "kiosk": False, "eink": False, "tz": None, "lead": 0,
                                          "maxerr": 100, **DISPLAY_DEFAULTS, "ignored": []}, "Unbekanntes still ignoriert")
        self.assertEqual(out["all"], {"design": "nixie", "kiosk": True, "eink": True, "tz": "UTC", "lead": 120,
                                      "maxerr": 50, **DISPLAY_DEFAULTS, "ignored": []})

    def test_fuzzing_aller_parameter(self):
        values = json.dumps(self.HOSTILE + ["1001", "99999", "-0", "２０", "٢٠"])
        out = run_kit(f"""
          const values = {values};
          const z = k.supportedZones();
          const defaults = k.paramDefaults();
          const results = [];
          for (const entry of k.PARAM_SCHEMA) {{
            for (const v of values) {{
              const out = k.parseParams("?" + new URLSearchParams([[entry.name, v]]).toString(), z);
              const raw = k.parseParams("?" + entry.name + "=" + v, z);   // auch ungekodiert
              for (const r of [out, raw]) {{
                const changed = Object.keys(defaults).filter((n) => r[n] !== defaults[n]);
                if (changed.length || !r.ignored.includes(entry.name)) results.push([entry.name, v, changed, r.ignored]);
              }}
            }}
          }}
          console.log(JSON.stringify(results));
        """)
        # Jeder feindliche Wert bleibt wirkungslos: Standardwerte, der Name steht in ignored – kodiert und roh. Zwei
        # Ausnahmen sind gewollt: Die Kurzzeile (label) nimmt harmlose Wörter wie „javascript:alert(1)“ als Text an (sie
        # landet nur per textContent im DOM), und „1001“ ist für warn eine gültige Schwelle in Sekunden.
        rest = [r for r in out if not (r[0] == "warn" and r[1] == "1001")]
        accepted = [r for r in rest if r[0] == "label"]
        for name, value, changed, ignored in accepted:
            self.assertEqual(changed, ["label"])
            self.assertRegex(value, r"^[\w .,:!?+\-/()#&']{1,24}$")
            self.assertNotRegex(value, r"[<>\"`;{}\\]|[\x00-\x1f]")
        self.assertEqual([r for r in rest if r[0] != "label"], [], rest[:5])

    def test_typen_label_und_zeit(self):
        out = run_kit("""
          const schema = [
            { name: "label", type: "label", len: 24, default: null },
            { name: "tzl", type: "label", len: 8, charset: /^[A-Za-z0-9 ]+$/, default: null },
            { name: "until", type: "time", default: null },
          ];
          const p = (name, v) => k.parseParams("?" + new URLSearchParams([[name, v]]).toString(), [], globalThis.Intl, schema)[name];
          const okLabels = ["bis ON AIR", "Café 20:15", "Nächste Sendung!", "Studio #2 (Regie)", "A&B"];
          const badLabels = ["<b>x</b>", "a;b", "x\\u0000", "\\u202eabc", " links", "rechts ", "\\"zitat\\"", "a{b}",
                             "back\\\\slash", "x".repeat(25), "", "javascript:alert(1)".replace(":", "\\u0000"),
                             "url(x)\\u000a", "Zeile\\nZwei", "\\u200bunsichtbar"];
          console.log(JSON.stringify({
            ok: okLabels.map((v) => p("label", v)), bad: badLabels.map((v) => p("label", v)),
            tzl: ["NYC", "LON 2", "Tokyo123", "TOKYO-1", "Zürich", "ABCDEFGHI"].map((v) => p("tzl", v)),
            long: p("label", "ä".repeat(24)), longer: p("label", "ä".repeat(25)),
            times: ["20:15", "20:15:30", "00:00", "23:59:59", "2026-12-31T23:59:59", "2026-12-31T23:59", "2028-02-29T12:00"]
              .map((v) => p("until", v)),
            badTimes: ["24:00", "20:60", "7:05", "20:15Z", "2026-02-30T10:00", "2027-02-29T12:00", "2026-13-01T00:00",
                       "2026-12-31 23:59", "javascript:20:15", "20:15:00.5", "T20:15", "<20:15>"].map((v) => p("until", v)),
          }));
        """)
        self.assertEqual(out["ok"], ["bis ON AIR", "Café 20:15", "Nächste Sendung!", "Studio #2 (Regie)", "A&B"])
        self.assertEqual(out["bad"], [None] * 15)
        self.assertEqual(out["tzl"], ["NYC", "LON 2", "Tokyo123", None, None, None])
        self.assertEqual(out["long"], "ä" * 24)
        self.assertIsNone(out["longer"])
        self.assertEqual(out["times"], [
            {"kind": "daily", "h": 20, "m": 15, "s": 0}, {"kind": "daily", "h": 20, "m": 15, "s": 30},
            {"kind": "daily", "h": 0, "m": 0, "s": 0}, {"kind": "daily", "h": 23, "m": 59, "s": 59},
            {"kind": "iso", "y": 2026, "mo": 12, "d": 31, "h": 23, "m": 59, "s": 59},
            {"kind": "iso", "y": 2026, "mo": 12, "d": 31, "h": 23, "m": 59, "s": 0},
            {"kind": "iso", "y": 2028, "mo": 2, "d": 29, "h": 12, "m": 0, "s": 0}])
        self.assertEqual(out["badTimes"], [None] * 12)


class ServerTeilTest(unittest.TestCase):
    def test_leap_next_aus_leap_py(self):
        with mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "2027-01-01"}):
            self.assertEqual(server._clock_leap_next({}), "2027-01-01")
        with mock.patch.object(server.leap, "status", return_value={"available": False, "next_leap_date": "2027-01-01"}):
            self.assertIsNone(server._clock_leap_next({}))
        with mock.patch.object(server.leap, "status", side_effect=RuntimeError("kaputt")):
            self.assertIsNone(server._clock_leap_next({}))
        with mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "/etc/x"}):
            self.assertIsNone(server._clock_leap_next({}), "nur ein Datum, nie ein Pfad")
        # Echte Liste (keine angekündigte Schaltsekunde): None, aber kein Fehler.
        with mock.patch.object(leap, "chrony_source", return_value=("list", str(LEAP_REAL))):
            self.assertIsNone(server._clock_leap_next({}))

    def test_time_payload_hat_leap_next_ohne_pfad(self):
        tracking = {"synchronised": True, "stratum": 2, "ref_name": "192.0.2.1", "root_delay": 0.001,
                    "root_dispersion": 0.0001, "system_time_offset": 0.0, "leap_status": "Normal"}
        with mock.patch.object(server, "_clock_tracking", return_value=tracking), \
                mock.patch.object(server.leap, "status", return_value={"available": True, "next_leap_date": "2027-01-01",
                                                                        "path": "/geheim/leap.list"}):
            payload = server.time_payload(1.0, public=True)
        self.assertEqual(payload["leap_next"], "2027-01-01")
        self.assertNotIn("geheim", json.dumps(payload))
        self.assertIsNone(payload["source"])

    def test_oeffentliche_dateien_ohne_konfiguration(self):
        public = server.CLOCK_PUBLIC_PATHS
        for path in ("/static/js/clockkit.js", "/static/js/util.js", "/static/js/i18n.js", "/static/i18n/de.json",
                     "/static/i18n/en.json"):
            self.assertIn(path, public)
        for path in ("/static/js/app.js", "/static/js/ui.js", "/static/index.html", "/api/status", "/api/leap"):
            self.assertNotIn(path, public)
        # Jede öffentliche JS-Datei importiert nur andere öffentliche Dateien.
        for path in sorted(p for p in public if p.endswith(".js")):
            text = (STATIC / path[len("/static/"):]).read_text(encoding="utf-8")
            for target in re.findall(r"""^import .* from ["']\./([\w-]+\.js)["']""", text, re.M):
                self.assertIn(f"/static/js/{target}", public, f"{path} lädt {target}")
            self.assertNotRegex(text, r"fetch\(\s*[\"'`]/api/(?!v1/time|v1/clock/profile\?)",
                                f"{path}: nur /api/v1/time und das Profil")


class SeitenregelnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")

    def test_bewegung_per_css_nicht_per_js_schleife(self):
        # requestAnimationFrame nur zum einmaligen Messen der Bildauffrischung (sechs Bilder), nie als Dauerschleife.
        start = self.js.index("function measureFrame()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertEqual(self.js.count("requestAnimationFrame"), body.count("requestAnimationFrame"))
        self.assertIn("stamps.length < FRAME_SAMPLES", body)
        for match in re.finditer(r"setInterval\([^,]+,\s*([A-Z_0-9]+)\)", self.js):
            self.assertIn(match.group(1), {"RESYNC_MS", "POLL_MS"})
        self.assertIn("@keyframes bh-sweep", self.css)
        self.assertRegex(self.css, r"97\.5% \{ transform: rotate\(360deg\)")
        self.assertIn("animation: bh-sweep 60s linear infinite", self.css)

    def test_zeitbasis_monoton_und_zustand_sichtbar(self):
        # Anzeige aus Anker + performance.now(), nie aus Date.now() + Versatz (springt mit der Geräteuhr).
        self.assertNotRegex(self.js, r"Date\.now\(\)\s*\+\s*offset")
        self.assertIn("kit.anchoredNow(state.anchor, perf, Date.now())", self.js)
        self.assertIn("measured.perf = perf3", self.js)
        self.assertIn("kit.tickGap(", self.js, "Neumessung nach einer Taktlücke")
        self.assertRegex(self.js, r'addEventListener\("visibilitychange"[\s\S]{0,200}burst\(\)')
        # Zustand als Text mit Symbol (nie nur Farbe), Sekunden einzeln ausgrauen.
        self.assertIn('id="clock-sync"', self.html)
        self.assertIn('id="clock-sync-text"', self.html)
        self.assertIn('id="local-sec"', self.html)
        for state in ("ok", "free", "degraded", "none"):
            self.assertIn(f'"clock.sync_{state}"', self.js)
        self.assertIn(':root[data-seconds="unsure"] .clock-sec', self.css)
        # Vorlauf nur für die Anzeige, der Ton bleibt auf der echten Serverzeit.
        self.assertIn("trueMs() + params.lead", self.js)
        self.assertIn("kit.audioClock(ctx, perf, trueMs(perf), 0)", self.js)

    def test_uhrsprung_im_takt_und_band(self):
        # Bei jedem Takt Wanduhr gegen Anker prüfen; bis zum neuen Anker keine Schranke, eigener Text, sofort messen.
        self.assertRegex(self.js, r"if \(!state\.jumped && kit\.wallJump\(state\.anchor, perf, Date\.now\(\)\)\) \{\s*"
                                  r"state\.jumped = true;\s*burst\(\);")
        self.assertIn("state.jumped = false;", self.js)
        self.assertIn("state.anchor && !state.jumped ? kit.errorBound(", self.js)
        self.assertIn('t("clock.sync_jump")', self.js)
        # Band: Abgleich statt eines zweiten „Anzeige ±“, und kein grünes „synchron“ bei unsicherer Anzeige.
        self.assertNotIn("clock.display_acc", self.js)
        self.assertIn('t("clock.match_acc"', self.js)
        self.assertRegex(self.js, r'if \(display === "degraded"\) \{\s*if \(tone === "good"\) tone = "warn";')
        self.assertIn("if (info.state !== state.bandSync) renderBandLive();", self.js)

    def test_zustandszeile_lesbar_und_im_bild(self):
        # In der Reihe mit UTC/KW (bei wenig Höhe daneben), Größe mit der Fläche ohne 22-px-Deckel, Kiosk nicht kleiner.
        sub = self.html[self.html.index('<div class="clock-sub">'):self.html.index("</main>")]
        self.assertIn('id="clock-sync"', sub)
        rule = re.search(r"\.clock-sync \{[^}]*\}", self.css).group(0)
        self.assertIn("font-size: max(12px, min(2vh + 4px, 1.6vw + 6px))", rule)
        self.assertNotRegex(self.css, r"body\.is-kiosk \.clock-sync")
        self.assertRegex(self.css, r"@media \(max-height: 480px\) \{[^@]*\.clock-sync \{ flex: 0 1 auto; \}")

    def test_rotlicht_kontrast(self):
        def lum(hexcolor):
            out = []
            for i in (1, 3, 5):
                c = int(hexcolor[i:i + 2], 16) / 255
                out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
            return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

        def contrast(a, b):
            x, y = lum(a), lum(b)
            return (max(x, y) + 0.05) / (min(x, y) + 0.05)
        red = re.search(r':root\[data-mode="red"\] \{([^}]*)\}', self.css).group(1)
        var = dict(re.findall(r"--([\w-]+): (#[0-9a-f]{6})", red))
        self.assertGreaterEqual(contrast(var["ink"], var["bg"]), 4.5)
        self.assertGreaterEqual(contrast(var["ink-unsure"], var["bg"]), 3.0, "graue Stellen im Rotlicht ≥ 3:1")
        self.assertGreater(contrast(var["ink"], var["ink-unsure"]), 1.5, "grau bleibt von --ink unterscheidbar")
        self.assertIn(':root[data-mode="red"] .clock-sync, :root[data-mode="red"] .clock-sync[data-sync] { color: var(--ink); }',
                      self.css)
        self.assertIn(':root[data-seconds="unsure"] .clock-sec,\n:root[data-seconds="unsure"] .flip-card.is-sec .flip-digit '
                      '{ color: var(--ink-unsure); }', self.css)
        self.assertIn("body.is-stale .clock-time { color: var(--ink-unsure); }", self.css)

    def test_ruhig_mit_reduced_motion(self):
        block = self.css[self.css.rindex("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn(".bh-second.is-sweep", block)
        self.assertIn(".flip-card .flip-digit", block)
        self.assertIn("prefers-reduced-motion: reduce", self.js, "Sekundenzeiger springt dann sekundenweise")

    def test_versatz_bleibt_im_browser(self):
        # Nur feste Schlüssel im localStorage; der gemessene Versatz wird nie gespeichert oder gesendet.
        keys = re.findall(r"store\(\s*([^,)]+)", self.js)
        self.assertTrue(keys)
        for key in keys:
            self.assertRegex(key.strip(), r'^(DESIGN_KEY|"ntp-gui-clock-(theme|red)"|link\.STORE_KEY|key)$')
        self.assertEqual(re.findall(r"fetch\(\s*[\"`]([^\"`?]+)", self.js), ["/api/v1/time", "/api/v1/clock/profile"])
        self.assertNotRegex(self.js, r"method:\s*\"POST\"|sendBeacon|WebSocket")
        self.assertNotIn("localStorage.setItem", self.js.replace("window.localStorage.setItem(key, value)", ""))

    def test_html_texte_gleich_katalog(self):
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))

        def get(key):
            node = de
            for part in key.split("."):
                node = node[part]
            return node
        for key, text in re.findall(r'data-i18n="([^"]+)"[^>]*>([^<]+)<', self.html):
            self.assertEqual(get(key), text.strip(), key)
        for match in re.finditer(r'title="([^"]+)" data-i18n-title="([^"]+)"', self.html):
            self.assertEqual(get(match.group(2)), match.group(1))

    def test_hell_dunkel_knopf_ohne_widerspruechlichen_zustand(self):
        # Der Knopf beschriftet die Aktion („Dunkel“ im hellen Modus) – ein aria-pressed dazu meldete
        # Screenreadern „Dunkel, gedrückt“, obwohl die Uhr hell ist. Also kein aria-pressed am Knopf.
        button = re.search(r'<button[^>]*id="mode-theme"[^>]*>', self.html).group(0)
        self.assertNotIn("aria-pressed", button)
        self.assertNotRegex(self.js, r'\$\("mode-theme"\)\.setAttribute\("aria-pressed"')
        self.assertIn('$("mode-red").setAttribute("aria-pressed"', self.js, "Rotlicht bleibt ein echter Umschalter")

    def test_bahnhofsuhr_eigenes_design(self):
        # Generisches Zifferblatt: offener Ring statt gefüllter Kelle, keine Herstellernamen.
        self.assertIn("bh-second-ring", self.js)
        self.assertRegex(self.css, r"\.bh-second-ring \{ fill: none;")
        for name in ("SBB", "Mondaine", "Swiss"):
            self.assertNotIn(name, self.js + self.css + self.html)


def _lum(hexcolor):
    out = []
    for i in (1, 3, 5):
        c = int(hexcolor[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _contrast(a, b):
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class LayoutEngineTest(unittest.TestCase):
    """Studiouhr A3: resolveLayout an allen Grenzen, Sicherheitsrand, Pixel-Shift, Auto-Anpassung."""

    def test_resolve_layout_grenzwerte(self):
        cases = [
            # Höhe < 120 → strip (vor allem anderen)
            ((1920, 119.99), "strip"), ((300, 119), "strip"), ((1920, 120), "banner"), ((200, 120), "tile"),
            # Seitenverhältnis ≥ 3:1 → banner
            ((900, 300), "banner"), ((899.99, 300), "normal"), ((3840, 945), "banner"), ((1920, 126), "banner"),
            # ≤ 1:1,6 → column
            ((500, 800), "column"), ((500.5, 800), "normal"), ((390, 663), "column"), ((1080, 1807), "column"),
            # kleiner als 480×270 (beides) → tile
            ((479.99, 269.99), "tile"), ((480, 269), "normal"), ((479, 270), "normal"), ((400, 211), "tile"),
            ((300, 200), "tile"),
            # sonst normal
            ((1920, 945), "normal"), ((768, 909), "normal"), ((360, 459), "normal"), ((480, 176), "normal"),
            # ungültige Maße
            ((0, 0), "normal"), ((-1, 500), "normal"), (("x", 500), "normal"), ((float("nan"), 1), "normal"),
        ]
        sizes = json.dumps([[w if w == w else None, h] for (w, h), _ in cases])
        out = run_kit(f"""
          const sizes = {sizes}.map(([w, h]) => [w === null ? NaN : w, h]);
          console.log(JSON.stringify({{ got: sizes.map(([w, h]) => k.resolveLayout(w, h)),
            forced: ["banner", "tile", "auto", "bogus"].map((p) => k.effectiveLayout(p, 1920, 945)),
            stacked: [k.stackedTime("column", 300, 900), k.stackedTime("column", 300, 899), k.stackedTime("normal", 300, 900)],
            limits: k.LAYOUT_LIMITS, layouts: k.LAYOUTS }}));
        """)
        self.assertEqual(out["got"], [want for _, want in cases])
        self.assertEqual(out["forced"], ["banner", "tile", "normal", "normal"])
        self.assertEqual(out["stacked"], [True, False, False])
        self.assertEqual(out["layouts"], ["auto", "normal", "banner", "column", "strip", "tile"])

    def test_css_spiegelt_resolve_layout(self):
        # Gleiche Grenzen in clock.css (@container) wie in LAYOUT_LIMITS, Rangfolge: spätere Regel gewinnt.
        out = run_kit("console.log(JSON.stringify(k.LAYOUT_LIMITS));")
        css = (STATIC / "clock.css").read_text(encoding="utf-8")
        rules = re.findall(r"@container clock-stage ([^{]+)\{ \.clock-stage > \.clock-main \{ --cq-layout: (\w+); \} \}", css)
        self.assertEqual([name for _q, name in rules], ["tile", "column", "banner", "strip"])
        queries = {name: q.strip() for q, name in rules}
        self.assertEqual(queries["strip"], f"(height < {out['stripHeight']}px)")
        self.assertEqual(queries["banner"], f"(aspect-ratio >= {out['bannerRatio']}/1)")
        self.assertAlmostEqual(5 / 8, out["columnRatio"])
        self.assertEqual(queries["column"], "(aspect-ratio <= 5/8)")
        self.assertEqual(queries["tile"], f"(width < {out['tileWidth']}px) and (height < {out['tileHeight']}px)")
        # Rückfall: Alles mit cq-Einheiten steht in @supports (container-type: size).
        outside = re.sub(r"@supports \(container-type: size\) \{.*?\n\}\n", "", css, flags=re.S)
        outside = re.sub(r"@supports \(container-type: size\) \{[^\n]*\}\n", "", outside)
        self.assertEqual(re.findall(r"[^\n]*\d(?:cqw|cqh|cqmin)\b[^\n]*", outside), [],
                         "cq-Einheiten nur innerhalb von @supports")
        self.assertIn(".clock-stage { container: clock-stage / size;", css)

    def test_rand_shift_und_anpassung(self):
        out = run_kit("""
          const P = (q) => k.parseParams(q, []);
          const base = Date.UTC(2026, 5, 30, 8, 0, 0);
          console.log(JSON.stringify({
            safe: [k.safeMargin(P("")), k.safeMargin(P("?layout=tile")), k.safeMargin(P("?layout=tile&safe=0")),
                   k.safeMargin(P("?safe=10")), k.safeMargin(P("?safe=11"))],
            level: [k.shiftLevel(P(""), "digital"), k.shiftLevel(P(""), "studio"), k.shiftLevel(P("?shift=0"), "studio"),
                    k.shiftLevel(P("?shift=2"), "digital"), k.shiftLevel(P("?shift=3"), "digital")],
            index: Array.from({ length: 10 }, (_, i) => k.shiftIndex(base + i * 120000)),
            inside: [k.shiftIndex(base + 119999) === k.shiftIndex(base), k.shiftIndex(-1), k.shiftIndex(NaN)],
            fit: [k.fitFactor({ width: 200, height: 50 }, { width: 100, height: 100 }),
                  k.fitFactor({ width: 50, height: 50 }, { width: 100, height: 100 }),
                  k.fitFactor({ width: 100, height: 300 }, { width: 200, height: 100 }),
                  k.fitFactor({ width: 3, height: 3 }, { width: 1000, height: 0 }), k.fitFactor(null, null),
                  k.fitFactor({ width: 1e6, height: 1 }, { width: 1, height: 1 })],
          }));
        """)
        self.assertEqual(out["safe"], [0, 5, 0, 10, 0])
        self.assertEqual(out["level"], [0, 1, 0, 2, 0])
        self.assertEqual(sorted(out["index"][:8]), list(range(8)), "acht Positionen")
        self.assertEqual(out["index"][8:], out["index"][:2], "Zyklus nach 16 min von vorn")
        self.assertEqual(out["inside"], [True, 7, 0])
        self.assertEqual(out["fit"], [0.5, 1, 0.333, 1, 1, 0.1])

    def test_streifen_ohne_kopfzeile(self):
        # Automatischer Streifen blendet Kopfzeile und Band aus (compact); danach wird mit der Höhe samt beiden entschieden,
        # damit das Layout nicht zurückspringt. Ausdrücklich gewählte Layouts bleiben, wie sie sind.
        out = run_kit("""
          console.log(JSON.stringify([
            k.chromeLayout("auto", 1920, 46), k.chromeLayout("auto", 1920, 120, 74), k.chromeLayout("auto", 1920, 194, 74),
            k.chromeLayout("auto", 1920, 126), k.chromeLayout("strip", 1920, 1080), k.chromeLayout("strip", 1920, 46),
            k.chromeLayout("tile", 1920, 46), k.chromeLayout("bogus", 1920, 86), k.chromeLayout("auto", 1920, 160, NaN),
          ]));
        """)
        self.assertEqual(out, [
            {"layout": "strip", "compact": True}, {"layout": "strip", "compact": True},
            {"layout": "banner", "compact": False}, {"layout": "banner", "compact": False},
            {"layout": "strip", "compact": False}, {"layout": "strip", "compact": False},
            {"layout": "tile", "compact": False}, {"layout": "strip", "compact": True},
            {"layout": "banner", "compact": False},
        ])

    def test_anpassung_bis_zur_ruhe(self):
        # Gekappte erste Messung (max-width: 100 %): Die Zeit misst 1000 px, auch wenn sie 1600 px wäre. Ein Durchgang
        # ergäbe 0,8 und damit 1280 px > 800 px; fitConverge regelt nach, bis es passt.
        out = run_kit("""
          const capped = (f) => ({ needed: { width: Math.min(1600 * f, 1000), height: 10 }, available: { width: 800, height: 100 } });
          const calls = [];
          const plain = (f) => { calls.push(f); return { needed: { width: 400 * f, height: 50 * f }, available: { width: 800, height: 100 } }; };
          const shrink = (f) => ({ needed: { width: 2000 * f, height: 10 }, available: { width: 1000, height: 100 } });
          console.log(JSON.stringify({ capped: k.fitConverge(capped), plain: k.fitConverge(plain), calls,
            shrink: k.fitConverge(shrink), none: k.fitConverge(() => null), bad: k.fitConverge(null),
            floor: k.fitConverge((f) => ({ needed: { width: 1e6 * f, height: 1 }, available: { width: 1, height: 1 } })) }));
        """)
        self.assertLessEqual(1600 * out["capped"], 800 + 1e-9)
        self.assertGreater(1600 * out["capped"], 760, "nicht unnötig klein")
        self.assertEqual((out["plain"], out["calls"]), (1, [1]), "passt: eine Messung, Faktor 1")
        self.assertEqual(out["shrink"], 0.5)
        self.assertEqual((out["none"], out["bad"]), (1, 1))
        self.assertEqual(out["floor"], 0.1)

    def test_schwarz_ist_immer_dunkel(self):
        # ?bg=black legt das Schema auf dunkel fest (helle Schrift); Thema und E-Ink gehen vor, sonst die gespeicherte Wahl.
        out = run_kit("""
          console.log(JSON.stringify([
            k.colorScheme({ bg: "black", stored: "light" }), k.colorScheme({ stored: "light" }), k.colorScheme({}),
            k.colorScheme({ bg: "transparent", stored: "light" }), k.colorScheme({ look: "paper", bg: "black" }),
            k.colorScheme({ eink: true, bg: "black" }), k.colorScheme({ look: "x", stored: "bogus" }),
          ]));
        """)
        self.assertEqual(out, [
            {"scheme": "dark", "locked": True}, {"scheme": "light", "locked": False}, {"scheme": "dark", "locked": False},
            {"scheme": "light", "locked": False}, {"scheme": "light", "locked": True},
            {"scheme": "light", "locked": True}, {"scheme": "dark", "locked": False},
        ])
        css = (STATIC / "clock.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.clock-stage > \.clock-main \{[^}]*max-width: none; margin: 0;",
                         "4K/32:9: main nicht auf --page-max gedeckelt")

    def test_darstellungsparameter(self):
        out = run_kit("""
          const P = (q) => k.parseParams(q, []);
          console.log(JSON.stringify({
            show: [P("?show=time,date,x").show, P("?show=time,time,status").show, P("?show=x,y").show, P("?show=").show],
            accent: ["ff8800", "FF8800", "amber", "#ff8800", "ff880", "ff88001", "red;x", "fff"].map((v) =>
              P("?" + new URLSearchParams([["accent", v]])).accent),
            values: P("?layout=banner&safe=7&bg=transparent&scale=150&weight=bold&shift=2&color=ice&sub=date&seconds=ring"
              + "&h12=1&face=seg&colon=blink&lz=0&date=iso&look=paper"),
            bad: P("?layout=world&scale=49&scale=201&bg=white&weight=900&color=pink&sub=x&face=dseg7&look=neon").ignored,
            scaleHigh: P("?scale=201").scale,
          }));
        """)
        self.assertEqual(out["show"], [["time", "date"], ["time", "status"], None, None])
        self.assertEqual(out["accent"], ["ff8800", "ff8800", "amber", None, None, None, None, None])
        values = out["values"]
        for key, want in {"layout": "banner", "safe": 7, "bg": "transparent", "scale": 150, "weight": "bold", "shift": 2,
                          "color": "ice", "sub": "date", "seconds": "ring", "h12": True, "face": "seg", "colon": "blink",
                          "lz": False, "date": "iso", "look": "paper"}.items():
            self.assertEqual(values[key], want, key)
        self.assertEqual(values["ignored"], [])
        self.assertEqual(out["bad"], ["layout", "bg", "scale", "weight", "color", "sub", "face", "look"])
        self.assertEqual(out["scaleHigh"], 100)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class FarbenUndZiffernTest(unittest.TestCase):
    """Studiouhr A4: Palette, Themen, Kontrast ≥ 4,5:1, 7-Segment-Ziffern."""

    @classmethod
    def setUpClass(cls):
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")
        cls.kit = run_kit("""console.log(JSON.stringify({ palette: k.PALETTE, looks: k.LOOKS, theme: k.THEME_BG,
          studio: k.STUDIO_COLORS, segments: k.SEGMENTS, designs: k.DESIGNS }));""")

    def looks_css(self):
        found = {}
        for name, body in re.findall(r':root\[data-look="(\w+)"\]:not\(\[data-mode\]\) \{([^}]*)\}', self.css):
            found[name] = dict(re.findall(r"--([\w-]+): (#[0-9a-f]{6})", body))
        return found

    def test_palette_auf_schwarz(self):
        self.assertGreaterEqual(len(self.kit["palette"]), 10)
        for name, color in self.kit["palette"].items():
            with self.subTest(name=name):
                self.assertGreaterEqual(_contrast(color, "#000000"), 4.5)
        self.assertTrue(set(self.kit["studio"]) <= set(self.kit["palette"]))
        self.assertEqual(self.kit["studio"], ["amber", "red", "green", "cyan", "white", "ice"])

    def test_themen_kontrast_und_gleicher_hintergrund(self):
        looks = self.looks_css()
        self.assertEqual(sorted(looks), sorted(self.kit["looks"]))
        self.assertLessEqual(len(looks), 6, "höchstens sechs Themen")
        self.assertLessEqual(len(self.kit["designs"]), 8, "höchstens acht Designs")
        for name, var in looks.items():
            with self.subTest(look=name):
                self.assertEqual(var["bg"], self.kit["looks"][name]["bg"], "Hintergrund in CSS und JS gleich")
                for key in ("ink", "ink-2", "ink-muted", "accent"):
                    self.assertGreaterEqual(_contrast(var[key], var["bg"]), 4.5, key)
                self.assertGreaterEqual(_contrast(var["ink-unsure"], var["bg"]), 3.0)
                self.assertGreater(_contrast(var["ink"], var["ink-unsure"]), 1.5, "grau bleibt unterscheidbar")
                scheme = "light" if _lum(var["bg"]) > 0.5 else "dark"
                self.assertEqual(self.kit["looks"][name]["scheme"], scheme)
        app = (STATIC / "app.css").read_text(encoding="utf-8")
        for theme, bg in self.kit["theme"].items():
            self.assertRegex(app, rf':root\[data-theme="{theme}"\] \{{\s*--bg: {bg};')

    def test_akzent_immer_mindestens_4_5(self):
        bgs = json.dumps(sorted({*(v["bg"] for v in self.kit["looks"].values()), *self.kit["theme"].values()}))
        out = run_kit(f"""
          const bgs = {bgs};
          const values = [...Object.keys(k.PALETTE), "ffffff", "000000", "808080", "ff8800", "0000ff", "ffff00"];
          const worst = [];
          for (const bg of bgs) for (const v of values) {{
            const r = k.ensureContrast(k.colorValue(v), bg);
            worst.push([bg, v, r.hex, Math.round(r.ratio * 100) / 100, r.adjusted]);
          }}
          console.log(JSON.stringify({{ worst, kept: k.ensureContrast("#ffb000", "#000000"),
            bad: [k.ensureContrast("red", "#000000"), k.colorValue("#ff0000"), k.colorValue("javascript:"), k.colorValue("ice")],
            bgs: [k.colorBackground({{ look: "paper" }}), k.colorBackground({{ bg: "black" }}),
                  k.colorBackground({{ theme: "light" }}), k.colorBackground({{ look: "x", theme: "y" }})] }}));
        """)
        for bg, value, hexcolor, ratio, _adjusted in out["worst"]:
            with self.subTest(bg=bg, value=value):
                self.assertGreaterEqual(ratio, 4.5)
                self.assertGreaterEqual(_contrast(hexcolor, bg), 4.5)
        self.assertEqual(out["kept"], {"hex": "#ffb000", "ratio": out["kept"]["ratio"], "adjusted": False})
        self.assertEqual(out["bad"], [None, None, None, "#a8d8ff"])
        self.assertEqual(out["bgs"], ["#f6f1e7", "#000000", "#f4f6f9", "#0d1117"])

    def test_sieben_segmente(self):
        segments = self.kit["segments"]
        self.assertEqual(segments["8"], "abcdefg")
        self.assertEqual(segments[" "], "")
        # Symbol: genau sieben Segmente a–g, nur Polygone, keine Schrift.
        symbol = re.search(r'<symbol id="seg7" viewBox="0 0 50 90">(.*?)</symbol>', self.html, re.S).group(1)
        self.assertEqual(re.findall(r'class="seg seg-([a-g])"', symbol), list("abcdefg"))
        self.assertNotIn("<text", symbol)
        # CSS: je Ziffer genau die leuchtenden Segmente, inaktive über --seg-off schwach sichtbar.
        for digit in "0123456789":
            rule = re.search(rf"\.d-{digit} \{{([^}}]*)\}}", self.css).group(1)
            self.assertEqual("".join(sorted(re.findall(r"--seg-([a-g]): 1;", rule))), segments[digit], digit)
        for seg in "abcdefg":
            self.assertIn(f".seg-{seg} {{ fill-opacity: var(--seg-{seg}, var(--seg-off)); }}", self.css)
        out = run_kit("""console.log(JSON.stringify({ cls: [k.segClass("4"), k.segClass(" "), k.segClass("x", "is-sec")],
          hours: [[9, {}], [9, { lz: false }], [0, { h12: true }], [12, { h12: true }], [23, { h12: true, lz: false }],
                  [13, { h12: true }]].map(([h, o]) => k.hourText(h, o)),
          ring: [k.ringLit(0, 0), k.ringLit(1, 0), k.ringLit(42, 42), k.ringLit(43, 42), k.ringLit(59, 59)] }));""")
        self.assertEqual(out["cls"], ["seg7 d-4", "seg7 d-blank", "seg7 d-blank is-sec"])
        self.assertEqual(out["hours"], [{"text": "09", "ampm": ""}, {"text": " 9", "ampm": ""},
                                        {"text": "12", "ampm": "AM"}, {"text": "12", "ampm": "PM"},
                                        {"text": "11", "ampm": "PM"}, {"text": "01", "ampm": "PM"}])
        self.assertEqual(out["ring"], [True, False, True, False, True])


class DarstellungsregelnTest(unittest.TestCase):
    """Studiouhr A3/A4: CSP, keine Animationen, öffentliche Dateien."""

    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.faces = (JS / "clockfaces.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")

    def test_farben_und_groessen_nur_per_cssom(self):
        # Nur feste Variablen per setProperty, Werte aus dem Schema bzw. aus kit.ensureContrast; kein style-Attribut.
        props = set(re.findall(r'setProperty\("([^"]+)"', self.js))
        self.assertEqual(props, {"--accent", "--studio-ink", "--safe", "--clock-scale", "--fit", "--info-w"})
        for text in (self.js, self.faces):
            self.assertNotRegex(text, r"setAttribute\(\s*[\"']style|\.style\.cssText|innerHTML")
        self.assertIn("kit.ensureContrast(kit.colorValue(params.accent), bg)", self.js)
        self.assertRegex(self.js, r'if \(root\.dataset\.mode\) \{\s*style\.removeProperty\("--accent"\);')

    def test_keine_animation_im_neuen_teil(self):
        block = self.css[self.css.index("/* --- Studiouhr A3: Bühne"):]
        self.assertNotRegex(block, r"animation|transition|@keyframes|filter:")
        self.assertNotIn("requestAnimationFrame", self.faces)
        self.assertNotRegex(self.faces, r"setTimeout|setInterval")
        for index in range(1, 8):
            self.assertIn(f".clock-main.shift-{index} {{ transform: translate(", self.css)
        self.assertIn("SHIFT_PERIOD_MS = 120_000", (JS / "clockkit.js").read_text(encoding="utf-8"))

    def test_oeffentliche_pfade_genau(self):
        self.assertEqual(server.CLOCK_PUBLIC_PATHS, {
            "/clock", "/api/v1/time", "/api/v1/clock/profile", "/static/app.css", "/static/clock.css", "/static/js/clock.js",
            "/static/js/clocksync.js", "/static/js/clockkit.js", "/static/js/clockfaces.js", "/static/js/clockcount.js",
            "/static/js/clocklink.js",
            "/static/js/util.js", "/static/js/i18n.js", "/static/i18n/de.json", "/static/i18n/en.json"})
        self.assertIn('import * as faces from "./clockfaces.js";', self.js)
        self.assertIn('import * as cd from "./clockcount.js";', self.js)


def run_count(code: str):
    module = json.dumps((JS / "clockcount.js").as_uri())
    kit = json.dumps((JS / "clockkit.js").as_uri())
    script = f"import * as c from {module};\nimport * as k from {kit};\n{code}"
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class CountdownTest(unittest.TestCase):
    """Studiouhr A5: Countdown/Count-up auf Serverzeit, Umstellungstage, Farbstufen, Überzeit, Timer-Engine."""

    def test_countdown_ueber_mitternacht(self):
        out = run_count("""
          const Z = "Europe/Berlin";
          const at = (iso, spec) => (c.untilTarget(spec, Date.parse(iso), Z) - Date.parse(iso)) / 1000;
          const d = (h, m, s = 0) => ({ kind: "daily", h, m, s });
          console.log(JSON.stringify({
            nextDay: at("2026-11-13T22:50:00Z", d(0, 10)),          // 23:50 → 00:10 morgen: 20 min
            today: at("2026-11-13T18:00:00Z", d(20, 15)),           // 19:00 → 20:15 heute
            exact: at("2026-11-13T19:15:00Z", d(20, 15)),           // genau auf dem Ziel: 0
            hold: at("2026-11-13T19:45:00Z", d(20, 15)),            // 30 min danach: Überzeit
            holdEnd: at("2026-11-13T20:15:00Z", d(20, 15)),         // 1 h danach: nächster Tag
            yesterday: at("2026-11-13T23:10:00Z", d(23, 30)),       // 00:10, Ziel 23:30 gestern: noch Überzeit
            seconds: at("2026-11-13T19:14:30Z", d(20, 15, 30)),
            iso: at("2026-12-31T21:59:59Z", { kind: "iso", y: 2026, mo: 12, d: 31, h: 23, m: 59, s: 59 }),
            isoPast: at("2027-01-01T00:00:00Z", { kind: "iso", y: 2026, mo: 12, d: 31, h: 23, m: 59, s: 59 }),
            view: c.countdownView(1_200_000).text,
          }));
        """)
        self.assertEqual(out["nextDay"], 20 * 60)
        self.assertEqual(out["today"], 75 * 60)
        self.assertEqual(out["exact"], 0)
        self.assertEqual(out["hold"], -30 * 60)
        self.assertEqual(out["holdEnd"], 23 * 3600)
        self.assertEqual(out["yesterday"], -40 * 60)
        self.assertEqual(out["seconds"], 60)
        self.assertEqual(out["iso"], 3600)
        self.assertEqual(out["isoPast"], -3601, "ISO-Ziel bleibt fest, auch wenn es vorbei ist")
        self.assertEqual(out["view"], "−20:00")

    def test_umstellungstage_mit_fester_zone(self):
        out = run_count("""
          const Z = "Europe/Berlin";
          const span = (iso, spec, zone = Z) => (c.untilTarget(spec, Date.parse(iso), zone) - Date.parse(iso)) / 3600_000;
          const when = (iso, spec, zone = Z) => new Date(c.untilTarget(spec, Date.parse(iso), zone)).toISOString();
          const d = (h, m, s = 0) => ({ kind: "daily", h, m, s });
          console.log(JSON.stringify({
            // 29.3.2026: 02:00 MEZ → 03:00 MESZ, der Tag hat 23 Stunden.
            springLater: span("2026-03-28T23:30:00Z", d(3, 30)),      // 00:30 → 03:30: nur 2 h
            springGap: when("2026-03-28T23:30:00Z", d(2, 30)),        // 02:30 gibt es nicht: 03:30 MESZ
            springNoon: span("2026-03-28T22:50:00Z", d(12, 0)),       // 23:50 am 28.3. → 12:00 am 29.3.: 11 h 10 min
            springDay: span("2026-03-29T00:00:00Z", d(0, 0)),         // 01:00 am 29.3. → 00:00 am 30.3.: 22 h (Tag mit 23 h)
            // 25.10.2026: 03:00 MESZ → 02:00 MEZ, der Tag hat 25 Stunden.
            autumnLater: span("2026-10-24T22:30:00Z", d(3, 30)),      // 00:30 → 03:30: 4 h
            autumnTwice: when("2026-10-24T22:30:00Z", d(2, 30)),      // 02:30 doppelt: die erste (MESZ)
            autumnDay: span("2026-10-24T23:00:00Z", d(0, 0)),         // 01:00 am 25.10. → 00:00 am 26.10.: 24 h (Tag mit 25 h)
            iso: when("2026-03-01T00:00:00Z", { kind: "iso", y: 2026, mo: 3, d: 29, h: 3, m: 0, s: 0 }),
            // Andere feste Zone: New York stellt am 8.3.2026 um (02:00 → 03:00).
            ny: span("2026-03-08T05:30:00Z", d(12, 0), "America/New_York"),
            utc: span("2026-03-28T23:30:00Z", d(3, 30), "UTC"),
            unusable: [c.usableZone("Mars/Olymp"), c.usableZone(""), c.usableZone(null), c.usableZone("Europe/Berlin")],
          }));
        """)
        self.assertEqual(out["springLater"], 2)
        self.assertEqual(out["springGap"], "2026-03-29T01:30:00.000Z")
        self.assertAlmostEqual(out["springNoon"], 11 + 10 / 60)
        self.assertEqual(out["springDay"], 22)
        self.assertEqual(out["autumnLater"], 4)
        self.assertEqual(out["autumnTwice"], "2026-10-25T00:30:00.000Z")
        self.assertEqual(out["autumnDay"], 24)
        self.assertEqual(out["iso"], "2026-03-29T01:00:00.000Z")
        self.assertEqual(out["ny"], 10.5, "00:30 EST → 12:00 EDT: eine Stunde weniger als 11,5 h Wanduhr")
        self.assertEqual(out["utc"], 4)
        self.assertEqual(out["unusable"], [None, None, None, "Europe/Berlin"])

    def test_farbstufen_und_ueberzeit(self):
        out = run_count("""
          const v = (ms, opts) => { const r = c.countdownView(ms, opts); return [r.phase, r.level, r.text, r.limit]; };
          console.log(JSON.stringify({
            levels: [400_000, 300_001, 300_000, 61_000, 60_000, 10_500, 10_000, 1, 0].map((ms) => v(ms)),
            custom: [130_000, 120_000, 30_000, 5_000].map((ms) => v(ms, { warn: [120, 30] })),
            over: [-1, -999, -1000, -61_000, -3_723_000].map((ms) => v(ms)),
            stop: [0, -5000].map((ms) => v(ms, { after: "stop" })),
            long: [3_600_000, 3_600_001, 90_061_000].map((ms) => v(ms)),
            en: v(90_061_000, { dayUnit: "d" }), coarse: [v(61_000, { coarse: true }), v(-61_000, { coarse: true })],
            none: v(NaN),
            watch: [c.stopwatchText(0), c.stopwatchText(61_250), c.stopwatchText(61_250, { tenths: true }),
              c.stopwatchText(3_723_400, { tenths: true, decimal: "." })],
            limits: [300, 90, 60, 10].map(c.fmtLimit),
          }));
        """)
        m = "−"
        self.assertEqual(out["levels"], [
            ["before", "none", f"{m}06:40", None], ["before", "none", f"{m}05:01", None],
            ["before", "warn", f"{m}05:00", 300], ["before", "warn", f"{m}01:01", 300],
            ["before", "alert", f"{m}01:00", 60], ["before", "alert", f"{m}00:11", 60],
            ["before", "final", f"{m}00:10", 10], ["before", "final", f"{m}00:01", 10],
            ["over", "over", "+00:00:00", None]])
        self.assertEqual(out["custom"], [["before", "none", f"{m}02:10", None], ["before", "warn", f"{m}02:00", 120],
                                         ["before", "alert", f"{m}00:30", 30], ["before", "alert", f"{m}00:05", 30]])
        self.assertEqual([x[2] for x in out["over"]], ["+00:00:00", "+00:00:00", "+00:00:01", "+00:01:01", "+01:02:03"])
        self.assertTrue(all(x[:2] == ["over", "over"] for x in out["over"]))
        self.assertEqual(out["stop"], [["done", "done", "00:00", None], ["done", "done", "00:00", None]])
        self.assertEqual([x[2] for x in out["long"]], [f"{m}01:00:00", f"{m}01:00:01", f"{m}1 T 01:01:01"])
        self.assertEqual(out["en"][2], f"{m}1 d 01:01:01")
        self.assertEqual([x[2] for x in out["coarse"]], [f"{m}00:02", "+00:01"])
        self.assertEqual(out["none"][:3], ["none", "none", "--:--"])
        self.assertEqual(out["watch"], ["00:00", "01:01", "01:01,2", "01:02:03.4"])
        self.assertEqual(out["limits"], ["5 min", "1 min 30 s", "1 min", "10 s"])

    def test_ansagen_nur_an_schwellen(self):
        out = run_count("""
          const seq = [62, 61, 60, 59, 11, 10, 9, 1, 0, 0];
          const said = [];
          for (let i = 1; i < seq.length; i += 1) { const s = c.announceStep(seq[i - 1], seq[i]); if (s !== null) said.push(s); }
          console.log(JSON.stringify({ said, first: c.announceStep(NaN, 60), jump: c.announceStep(70, 5), up: c.announceStep(5, 10) }));
        """)
        self.assertEqual(out["said"], [60, 10, 0])
        self.assertIsNone(out["first"], "beim Laden nichts ansagen")
        self.assertEqual(out["jump"], 10)
        self.assertIsNone(out["up"])

    def test_until_zone_erst_nach_antwort(self):
        out = run_count("""
          console.log(JSON.stringify({
            open: c.untilZone(null) === undefined, early: c.untilZone(undefined, { waitedMs: 4999 }) === undefined,
            server: c.untilZone({ zone: "Europe/Berlin" }), bad: c.untilZone({ zone: "Mars/Olympus" }),
            none: c.untilZone({}), failed: c.untilZone(null, { failed: true }), late: c.untilZone(null, { waitedMs: c.ZONE_WAIT_MS }),
          }));
        """)
        self.assertTrue(out["open"], "ohne Antwort noch keine Zone (kein Rechnen in der Zone des Browsers)")
        self.assertTrue(out["early"])
        self.assertEqual(out["server"], "Europe/Berlin")
        self.assertIsNone(out["bad"])
        self.assertIsNone(out["none"], "Antwort ohne Zone: Browser")
        self.assertIsNone(out["failed"], "Messung fehlgeschlagen (z. B. 401): Browser")
        self.assertIsNone(out["late"], "nach der Wartezeit: Browser")

    def test_until_wartet_auf_den_ersten_anker(self):
        out = run_count("""
          const status = { zone: "Europe/Berlin" };
          console.log(JSON.stringify({
            early: c.untilZone(status, { anchored: false, waitedMs: 800 }) === undefined,
            anchored: c.untilZone(status, { anchored: true, waitedMs: 800 }),
            late: c.untilZone(status, { anchored: false, waitedMs: c.ZONE_WAIT_MS }),
            plain: c.untilZone(status),
          }));
        """)
        self.assertTrue(out["early"], "Antwort da, Anker noch nicht: noch kein Countdown (Gerätezeit spränge)")
        self.assertEqual(out["anchored"], "Europe/Berlin")
        self.assertEqual(out["late"], "Europe/Berlin", "ohne Anker nach der Wartezeit trotzdem rechnen")
        self.assertEqual(out["plain"], "Europe/Berlin")

    def test_browserzone_folgt_der_systemzone(self):
        out = run_count("""
          const ms = Date.parse("2026-11-13T18:00:00Z");
          process.env.TZ = "Europe/Berlin";
          const berlin = c.zoneParts(ms, null).h;
          process.env.TZ = "Europe/London";
          const london = c.zoneParts(ms, null).h;
          console.log(JSON.stringify({ berlin, london, date: new Date(ms).getHours() }));
        """)
        self.assertEqual(out["berlin"], 19)
        self.assertEqual(out["london"], 18, "nach einem Wechsel der Systemzone rechnet ?until= in der neuen")
        self.assertEqual(out["london"], out["date"])

    def test_eink_takt_auf_das_ziel(self):
        out = run_count("""
          const min = (h, m, s = 0) => Date.UTC(2026, 10, 13, h, m, s);
          const now = min(20, 15, 0);
          console.log(JSON.stringify({
            plain: c.einkDelay(now + 20_000),
            target: c.einkDelay(now, min(20, 15, 30) - now),            // Ziel 20:15:30: genau dort
            steps: c.einkDelay(min(10, 1, 0), 40_000 + 60_000),        // Timer endet 10:02:40: Minutensprung 10:01:40
            over: c.einkDelay(min(10, 2, 0), -10_000),                 // 10 s Überzeit: nächster Sprung in 50 s (+00:01)
            far: c.einkDelay(min(10, 0, 30), 3_600_000),               // volle Stunde voraus: volle Minute gilt
            none: c.einkDelay(min(10, 0, 30), NaN),
          }));
        """)
        self.assertEqual(out["plain"], 40_005)
        self.assertEqual(out["target"], 30_005)
        self.assertEqual(out["steps"], 40_005)
        self.assertEqual(out["over"], 50_005)
        self.assertEqual(out["far"], 30_005)
        self.assertEqual(out["none"], 30_005)

    def test_geplante_toene_lassen_sich_stoppen(self):
        out = run_count("""
          const log = [];
          const osc = (id, fail) => ({ stop: (t) => { if (fail) throw new Error("x"); log.push([id, t]); }, disconnect: () => log.push([id, "off"]) });
          const rest = k.stopTones([osc("a"), osc("b", true), osc("c")]);
          console.log(JSON.stringify({ rest, log, empty: k.stopTones(null) }));
        """)
        self.assertEqual(out["rest"], [])
        self.assertEqual(out["empty"], [])
        self.assertEqual(out["log"], [["a", 0], ["a", "off"], ["b", "off"], ["c", 0], ["c", "off"]])

    def test_timer_engine_auf_monotoner_uhr(self):
        out = run_count("""
          let t = c.timerNew(90_000);
          const log = [];
          const read = (now) => { const r = c.timerRead(t, now); log.push([r.state, r.elapsed, r.remaining]); };
          read(1000);
          t = c.timerToggle(t, 1000); read(31_000);          // 30 s gelaufen
          t = c.timerToggle(t, 31_000); read(500_000);       // angehalten: bleibt bei 30 s
          t = c.timerToggle(t, 500_000); read(560_000);      // weiter: 90 s → Ziel
          read(565_000);                                     // 5 s Überzeit
          t = c.timerReset(t); read(600_000);
          let w = c.timerNew(null);
          w = c.timerToggle(w, 10);
          const watch = c.timerRead(w, 12_345);
          console.log(JSON.stringify({ log, watch, frozen: Object.isFrozen(t), invalid: c.timerNew(-5).duration,
            delays: [
              c.timerDelay({ remaining: 4_300, elapsed: 0 }), c.timerDelay({ remaining: 4_000, elapsed: 0 }),
              c.timerDelay({ remaining: -1_200, elapsed: 0 }), c.timerDelay({ remaining: null, elapsed: 12_345 }),
              c.timerDelay({ remaining: null, elapsed: 12_345 }, 100),
            ] }));
        """)
        self.assertEqual(out["log"], [["idle", 0, 90000], ["running", 30000, 60000], ["paused", 30000, 60000],
                                      ["running", 90000, 0], ["running", 95000, -5000], ["idle", 0, 90000]])
        self.assertEqual(out["watch"], {"state": "running", "elapsed": 12335, "remaining": None})
        self.assertTrue(out["frozen"])
        self.assertIsNone(out["invalid"])
        self.assertEqual(out["delays"], [302, 1002, 802, 657, 57])

    def test_timer_folgt_nicht_der_geraeteuhr(self):
        # Die Engine kennt nur die Zeitpunkte, die ihr performance.now() liefert – Date.now() kommt nicht vor.
        text = (JS / "clockcount.js").read_text(encoding="utf-8")
        self.assertNotIn("Date.now", text)
        self.assertNotRegex(text, r"setTimeout|setInterval|requestAnimationFrame|document\.|window\.")

    def test_piepen_in_den_letzten_sekunden(self):
        out = run_count("""
          const clock = { audio: 100, server: 1_000_000, exact: true };
          const target = 1_005_000;   // in 5 s
          const first = c.planCountdownTones(clock, target, 10, { horizonMs: 1500 });
          // Takt je Sekunde (leicht versetzt): jeder Ton genau einmal, keiner doppelt, keiner fehlt.
          const all = [];
          let lastK = Infinity;
          for (let ms = 999_990; ms <= 1_007_000; ms += 1000) {
            for (const tone of c.planCountdownTones({ audio: 100 + (ms - 1_000_000) / 1000, server: ms }, target, 10, { lastK })) {
              all.push([tone.k, Math.round(tone.at * 1000) / 1000]);
              lastK = tone.k;
            }
          }
          const later = c.planCountdownTones({ audio: 104, server: 1_004_000 }, target, 10, { lastK: 2 });
          console.log(JSON.stringify({ first, later, all, off: c.planCountdownTones(clock, target, 0),
            past: c.planCountdownTones({ audio: 110, server: 1_010_000 }, target, 10) }));
        """)
        self.assertEqual([(t["k"], t["kind"]) for t in out["first"]], [(5, "count"), (4, "count")])
        self.assertAlmostEqual(out["first"][0]["at"], 100.0)
        self.assertAlmostEqual(out["first"][1]["at"], 101.0)
        self.assertEqual(out["all"], [[5, 100.0], [4, 101.0], [3, 102.0], [2, 103.0], [1, 104.0], [0, 105.0]])
        self.assertEqual([(t["k"], t["kind"]) for t in out["later"]], [(1, "count"), (0, "long")])
        self.assertAlmostEqual(out["later"][-1]["at"], 105.0)
        self.assertEqual(out["later"][-1]["freq"], 1000)
        self.assertEqual(out["first"][0]["freq"], 1500)
        self.assertEqual(out["off"], [])
        self.assertEqual(out["past"], [], "längst vorbei: kein Nachholen")

    def test_parameter_countdown(self):
        out = run_kit("""
          const P = (q) => k.parseParams(q, []);
          const one = (name, v) => P("?" + new URLSearchParams([[name, v]]))[name];
          console.log(JSON.stringify({
            timer: ["90s", "25m", "1h30m", "2m30s", "24h", "25h", "0s", "90", "1m1h", "1.5m", "m", "-5m", "90s;x"].map((v) => one("timer", v)),
            durations: ["90s", "1h", "0m", ""].map(k.parseDuration),
            warn: ["300,60,10", "10,60,300", "60", "120,30", "300,60,10,5", "300,300", "0", "3601", "60,x", "60,", " 60"].map((v) => one("warn", v)),
            beep: ["0", "10", "60", "61", "-1"].map((v) => one("beep", v)),
            after: ["up", "stop", "down"].map((v) => one("after", v)),
            cd: ["main", "below", "top"].map((v) => one("cd", v)),
            label: ["bis ON AIR", "<b>x</b>", "x".repeat(25)].map((v) => one("label", v)),
            lock: one("lock", "1"),
            all: P("?until=20:15&after=stop&warn=120,30&beep=5&label=bis%20ON%20AIR&cd=main&lock=1"),
            defaults: P(""),
            frozen: Object.isFrozen(P("").warn) && Object.isFrozen(P("?warn=5").warn),
          }));
        """)
        self.assertEqual(out["timer"], [90000, 1500000, 5400000, 150000, 86400000, None, None, None, None, None, None, None, None])
        self.assertEqual(out["durations"], [90000, 3600000, None, None])
        self.assertEqual(out["warn"], [[300, 60, 10], [300, 60, 10], [60], [120, 30], [300, 60, 10], [300, 60, 10],
                                       [300, 60, 10], [300, 60, 10], [300, 60, 10], [300, 60, 10], [300, 60, 10]])
        self.assertEqual(out["beep"], [0, 10, 60, 0, 0])
        self.assertEqual(out["after"], ["up", "stop", "up"])
        self.assertEqual(out["cd"], ["main", "below", "below"])
        self.assertEqual(out["label"], ["bis ON AIR", None, None])
        self.assertTrue(out["lock"])
        a = out["all"]
        self.assertEqual((a["until"], a["after"], a["warn"], a["beep"], a["label"], a["cd"], a["lock"], a["ignored"]),
                         ({"kind": "daily", "h": 20, "m": 15, "s": 0}, "stop", [120, 30], 5, "bis ON AIR", "main", True, []))
        self.assertEqual((out["defaults"]["after"], out["defaults"]["warn"], out["defaults"]["cd"]), ("up", [300, 60, 10], "below"))
        self.assertTrue(out["frozen"])


class CountdownSeitenTest(unittest.TestCase):
    """Studiouhr A5: Server-Zeitzone, Seitenregeln für Countdown und Tastenkürzel."""

    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")

    def test_zeitzone_des_servers_in_time(self):
        tracking = {"synchronised": True, "stratum": 1, "ref_name": "PPS", "root_delay": 0.0, "root_dispersion": 0.0001,
                    "leap_status": "Normal"}
        server._CLOCK_ZONE.update(t=None, zone=None)
        with mock.patch.object(server, "_clock_tracking", return_value=tracking), \
                mock.patch.object(server, "iana_timezone", return_value="Europe/Berlin") as zone:
            first = server.time_payload(1.0, public=True)
            second = server.time_payload(2.0, public=True)
        self.assertEqual((first["zone"], second["zone"]), ("Europe/Berlin", "Europe/Berlin"))
        self.assertEqual(zone.call_count, 1, "höchstens einmal je Minute gelesen")
        server._CLOCK_ZONE.update(t=None, zone=None)
        with mock.patch.object(server, "_clock_tracking", return_value=tracking), \
                mock.patch.dict("os.environ", {"TZ": "/usr/share/zoneinfo/../../etc/passwd"}):
            self.assertIsNone(server.time_payload(1.0, public=True)["zone"], "nie ein Pfad")
        server._CLOCK_ZONE.update(t=None, zone=None)

    def test_tastenkuerzel_laut_konzept(self):
        start = self.js.index("function onKey(event)")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("if (!state.ready || params.lock || event.ctrlKey || event.altKey || event.metaKey", body)
        self.assertIn('target.closest("select, input, textarea")', body)
        for key, action in (("f", "toggleFullscreen"), ("d", "nextDesign"), ("l", "nextLayout"), ("u", "toggleUtc"),
                            ("t", "toggleTenths"), ("r", "resetTimer"), ("a", "announceTime")):
            self.assertIn(f"{key}: {action}", body)
        for key in ('"+"', '"-"', '"\u2212"', '"?"', 'key === " "'):
            self.assertIn(key, body)
        self.assertIn("toggleTimer()", body)
        self.assertEqual(self.js.count('addEventListener("keydown", onKey)'), 1)
        # Übersicht der Kürzel im HTML: alle Tasten der Konzept-Tabelle (ohne O, das kommt mit On-Air).
        for key in ("F", "D", "L", "U", "T", "Leertaste", "R", "+", "−", "A", "?"):
            self.assertIn(f"<kbd>{key}</kbd>", self.html)

    def test_countdown_nur_text_und_klassen(self):
        start = self.js.index("function renderCountdown(")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('setText($("cd-label"), label)', body)
        self.assertNotRegex(self.js, r"innerHTML|insertAdjacentHTML|speechSynthesis|SpeechSynthesis")
        self.assertIn("cd.untilTarget(params.until, nowMs, zone)", body)
        self.assertIn("countZone()", body)
        # Nie nur Farbe: Symbol und Text je Stufe; kein Blinken im neuen Teil.
        self.assertIn('setText($("cd-icon")', body)
        self.assertIn('setText($("cd-state"), status || levelText(view))', body)
        block = self.css[self.css.index("/* --- Studiouhr A5"):]
        self.assertNotRegex(block, r"animation|transition|@keyframes|blink")
        for level in ("warn", "alert", "final", "over"):
            self.assertIn(f'[data-level="{level}"]', block)
        # Ton über denselben Weg wie „Ton auf der Sekunde“.
        self.assertIn("kit.audioClock(tone.ctx, perf, trueMs(perf), 0)", self.js)
        self.assertIn("kit.scheduleTone(tone.ctx, planned)", self.js)

    def test_until_wartet_auf_zone_des_servers(self):
        start = self.js.index("function renderCountdown(")
        body = self.js[start:self.js.index("\n}\n", start)]
        # Ohne Zone noch keine Rechnung (kein Sprung um die Zonendifferenz); Zonenwechsel setzt Ansage und Ton zurück.
        self.assertIn("if (zone === undefined)", body)
        self.assertIn("cd.countdownView(NaN, opts)", body)
        reset = body[body.index("if (zone !== state.cdZone)"):body.index("if (zone === undefined)")]
        self.assertIn("state.cdPrev = NaN", reset)
        self.assertIn("stopCountdownTones()", reset)
        self.assertIn("cd.untilZone(state.status, { failed: Boolean(state.error)", self.js)

    def test_anker_setzt_ansage_zurueck(self):
        start = self.js.index("async function burst()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("state.cdPrev = NaN", body[body.index("state.anchor = anchor"):])
        self.assertIn("anchored: Boolean(state.anchor)", self.js)

    def test_toene_verstummen_bei_pause_reset_und_neuem_ziel(self):
        for name in ("function toggleTimer()", "function resetTimer()"):
            start = self.js.index(name)
            body = self.js[start:self.js.index("\n}\n", start)]
            self.assertIn("stopCountdownTones()", body, name)
        start = self.js.index("function countdownTones(")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("tone.oscs.push(osc)", body)
        self.assertIn("> 1500) stopCountdownTones()", body)
        start = self.js.index("function stopCountdownTones()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("kit.stopTones(state.cdTone.oscs)", body)

    def test_eink_takt_folgt_dem_countdown(self):
        start = self.js.index("function tick()")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("const remaining = renderCountdown(nowMs)", body)
        self.assertIn("cd.einkDelay(later, remaining - (later - nowMs))", body)

    def test_lock_sperrt_bedienung_aber_nicht_rotlicht(self):
        rule = next(line for line in self.css.splitlines() if line.startswith("body.is-locked :is("))
        for selector in (".clock-design", "#mode-tone", "#mode-custom"):
            self.assertIn(selector, rule)
        # Rotlicht und Hell/Dunkel haben keinen Adressparameter: unter lock=1 müssen sie schaltbar bleiben.
        for selector in ("#mode-full", "#mode-theme", "#mode-red", "#mode-device"):
            self.assertNotIn(selector, rule)

    def test_lock_vollbild_ohne_taste_f(self):
        for lang in ("de", "en"):
            data = json.loads((ROOT / "app" / "static" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
            with self.subTest(lang=lang):
                self.assertNotRegex(data["clock"]["full_title_locked"], r"\b(F|Taste|key)\b")
                self.assertRegex(data["clock"]["full_title"], r"\bF\b")
        self.assertIn('$("mode-full").dataset.i18nTitle = "clock.full_title_locked"', self.js)
        start = self.js.index("function relabel(")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('if (params.lock) $("mode-full").title = t("clock.full_title_locked")', body)

    def test_doku_beschreibt_lock(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_text = (ROOT / "app" / "static" / "js" / "help-uhr.js").read_text(encoding="utf-8")
        for name, text in (("README", readme), ("help-uhr.js", help_text)):
            with self.subTest(name=name):
                self.assertNotIn("`?lock=1` schaltet die Tasten ab.", text)
                self.assertIn("Rotlicht", text[text.index("?lock=1"):text.index("?lock=1") + 300])

    def test_lock_verspricht_keine_bedienung(self):
        start = self.js.index("function renderCountdown(")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('t(params.lock ? "clock.cd_locked" : "clock.cd_idle")', body)
        for lang, word in (("de", "Leertaste"), ("en", "space")):
            text = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]["cd_locked"]
            self.assertNotIn(word, text)
            self.assertIn("lock=1", text)

    def test_kuerzel_uebersicht_modal_mit_fokus_zurueck(self):
        self.assertRegex(self.html, r'id="keys" role="dialog" aria-modal="true"')
        self.assertIn('id="clock-main" tabindex="-1"', self.html)
        start = self.js.index("function showKeys(open)")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("state.keysReturn = ", body)
        self.assertIn("back.focus(", body)
        self.assertIn('$("keys").addEventListener("keydown", trapKeys)', self.js)

    def test_countdown_texte_lesbar_und_ortszeit_im_banner(self):
        block = self.css[self.css.index("/* --- Studiouhr A5"):]
        for selector, floor in ((".clock-cd-head {", "12px"), (".clock-cd-state {", "12px"),
                                (':root[data-cd="main"] .clock-cd-now {', "13px")):
            rule = block[block.index(selector):block.index("}", block.index(selector))]
            self.assertRegex(rule, rf"font-size: max\([0-9.]+em, {floor}\)", selector)
        banner = ':root[data-cd="main"] .clock-stage[data-layout="banner"] .clock-cd-now {'
        rule = block[block.index(banner):block.index("}", block.index(banner))]
        self.assertNotIn("display: none", rule, "im Banner bleibt die Uhrzeit bei cd=main sichtbar")


if __name__ == "__main__":
    unittest.main()
