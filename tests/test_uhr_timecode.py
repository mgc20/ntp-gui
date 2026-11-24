"""Studiouhr B1: Timecode-Anzeige (Design tc).

Die reinen Rechnungen stehen in app/static/js/clocktc.js und laufen hier mit Node: Drop-Frame-Zählung mit den
Testvektoren aus docs/konzept/studiouhr.md (Akzeptanz B), Tageslänge, Tageszeit → Framenummer, die Anzeige mit
Zehnteln oder Frames, der Zustand der Feinstelle (grau über ½ Frame bzw. 50 ms, weg über maxerr) und die Erkennung
grob gerundeter Zeitgeber. Dazu: derselbe Parameter in Schema, Server-Allowlist, Link-Baukasten und Doku, die Texte
in beiden Sprachen und Regeln für clock.js/clock.css (Bildschleife nur für die Feinstelle, E-Ink ohne Feinstelle).
"""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import clockprofiles  # noqa: E402
import server  # noqa: E402


def run_tc(code: str):
    mods = {name: json.dumps((JS / f"{name}.js").as_uri()) for name in ("clocktc", "clockkit", "clocklink")}
    script = (f"import * as tc from {mods['clocktc']};\nimport * as k from {mods['clockkit']};\n"
              f"import * as l from {mods['clocklink']};\n{code}")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class DropFrameTest(unittest.TestCase):
    def test_testvektoren_aus_akzeptanz_b(self):
        out = run_tc("""
          const df = tc.tcRate("29.97"), df60 = tc.tcRate("59.94"), pal = tc.tcRate("25");
          const text = (n, rate) => { const c = tc.framesToTc(n, rate); const p = (v) => String(v).padStart(2, "0");
            return `${p(c.h)}:${p(c.m)}:${p(c.s)}${rate.drop ? ";" : ":"}${p(c.f)}`; };
          const at = (h, m, s, f, rate) => tc.tcToFrames({ h, m, s, f }, rate);
          console.log(JSON.stringify({
            start: text(0, df),
            minute1: [text(at(0, 0, 59, 29, df), df), text(at(0, 0, 59, 29, df) + 1, df)],
            minute10: [text(at(0, 9, 59, 29, df), df), text(at(0, 9, 59, 29, df) + 1, df), text(at(0, 9, 59, 29, df) + 2, df)],
            minute1x60: [text(at(0, 0, 59, 59, df60), df60), text(at(0, 0, 59, 59, df60) + 1, df60)],
            minute10x60: [text(at(0, 9, 59, 59, df60), df60), text(at(0, 9, 59, 59, df60) + 1, df60)],
            hour: text(107892, df),
            dayEndDf: [text(at(23, 59, 59, 29, df), df), text(at(23, 59, 59, 29, df) + 1, df)],
            dayEndPal: [text(at(23, 59, 59, 24, pal), pal), text(at(23, 59, 59, 24, pal) + 1, pal)],
            negative: text(-1, df),
            dropped: [at(0, 1, 0, 0, df), at(0, 1, 0, 1, df), at(0, 1, 0, 2, df), at(0, 10, 0, 0, df), at(0, 1, 0, 3, df60),
              at(0, 1, 0, 4, df60)],
            invalid: [tc.framesToTc(NaN, df), at(24, 0, 0, 0, pal), at(0, 0, 0, 25, pal), at(0, 0, 0.5, 0, pal)],
          }));
        """)
        self.assertEqual(out["start"], "00:00:00;00")
        self.assertEqual(out["minute1"], ["00:00:59;29", "00:01:00;02"])
        self.assertEqual(out["minute10"], ["00:09:59;29", "00:10:00;00", "00:10:00;01"], "Minute 10 ohne Sprung")
        self.assertEqual(out["minute1x60"], ["00:00:59;59", "00:01:00;04"])
        self.assertEqual(out["minute10x60"], ["00:09:59;59", "00:10:00;00"])
        self.assertEqual(out["hour"], "01:00:00;00", "eine Timecode-Stunde = 107 892 Frames")
        self.assertEqual(out["dayEndDf"], ["23:59:59;29", "00:00:00;00"])
        self.assertEqual(out["dayEndPal"], ["23:59:59:24", "00:00:00:00"])
        self.assertEqual(out["negative"], "23:59:59;29")
        self.assertEqual(out["dropped"], [None, None, 1800, 17982, None, 3600], "weggelassene Nummern gibt es nicht")
        self.assertEqual(out["invalid"], [None, None, None, None])

    def test_tageslaenge_und_rundreise_ueber_den_ganzen_tag(self):
        out = run_tc("""
          const days = {};
          for (const fps of Object.keys(tc.TC_RATES)) days[fps] = tc.dayFrames(tc.tcRate(fps));
          // Jede Framenummer eines Drop-Frame-Tages ergibt genau einen Timecode, der zurück auf dieselbe Nummer führt,
          // und die Timecodes steigen streng an.
          const bad = [];
          for (const fps of ["29.97", "59.94"]) {
            const rate = tc.tcRate(fps);
            let last = -1;
            for (let n = 0; n < tc.dayFrames(rate); n += 1) {
              const c = tc.framesToTc(n, rate);
              const order = ((c.h * 60 + c.m) * 60 + c.s) * rate.nominal + c.f;
              if (tc.tcToFrames(c, rate) !== n || order <= last) { bad.push([fps, n]); break; }
              last = order;
            }
          }
          const pal = tc.tcRate("25");
          const palBad = [0, 1, 24, 25, 1499, 1500, 89999, 90000, 2159999].filter((n) => tc.tcToFrames(tc.framesToTc(n, pal), pal) !== n);
          console.log(JSON.stringify({ days, bad, palBad, unknown: tc.tcRate("23.976").fps, frame: [tc.frameMs(tc.tcRate("25")),
            Math.round(tc.frameMs(tc.tcRate("29.97")) * 1000) / 1000] }));
        """)
        self.assertEqual(out["days"], {"24": 2073600, "25": 2160000, "30": 2592000, "50": 4320000, "60": 5184000,
                                       "29.97": 2589408, "59.94": 5178816})
        self.assertEqual(out["bad"], [])
        self.assertEqual(out["palBad"], [])
        self.assertEqual(out["unknown"], "25", "unbekannte Bildrate: 25 fps")
        self.assertEqual(out["frame"], [40, 33.367])

    def test_tageszeit_zu_framenummer(self):
        out = run_tc("""
          const df = tc.tcRate("29.97"), pal = tc.tcRate("25");
          // Drop-Frame folgt der Tageszeit nur näherungsweise: innerhalb von zehn Minuten −60 … +67 ms, dazu bis zum
          // Tagesende 86,4 ms Rückstand (2 589 408 statt 2 589 410,6 Frames). Mehr als 0,15 s werden es nie.
          let worst = 0;
          for (let ms = 0; ms < tc.DAY_MS; ms += 7919) {
            const c = tc.framesToTc(tc.frameAt(ms, df), df);
            const shown = (((c.h * 60 + c.m) * 60 + c.s) + c.f / 30) * 1000;
            worst = Math.max(worst, Math.abs(shown - ms));
          }
          console.log(JSON.stringify({
            pal: [tc.frameAt(0, pal), tc.frameAt(39.9, pal), tc.frameAt(40, pal), tc.frameAt(999.9, pal), tc.frameAt(1000, pal)],
            df: [tc.frameAt(0, df), tc.frameAt(33.3, df), tc.frameAt(33.4, df), tc.frameAt(1001, df)],
            worst, last: tc.frameAt(tc.DAY_MS - 1, df) === tc.dayFrames(df) - 1,
            hold: tc.frameAt(tc.DAY_MS - 80, df) === tc.dayFrames(df) - 1,
            before: tc.frameAt(tc.DAY_MS - 120, df) < tc.dayFrames(df) - 1,
            lastPal: tc.frameAt(tc.DAY_MS - 1, pal), nan: [tc.frameAt(NaN, pal), tc.frameAt(0, null)],
            day: [tc.dayMs(0), tc.dayMs(tc.DAY_MS + 5), tc.dayMs(-1), tc.dayMs(Date.UTC(2026, 5, 30, 8, 15, 42, 500), 7200000),
              tc.dayMs(NaN), tc.dayMs(0, NaN)],
          }));
        """)
        self.assertEqual(out["pal"], [0, 0, 1, 24, 25])
        self.assertEqual(out["df"], [0, 0, 1, 30])
        self.assertLess(out["worst"], 150)
        self.assertGreater(out["worst"], 60)
        self.assertTrue(out["last"] and out["hold"] and out["before"],
                        "die letzten 86,4 ms des Tages bleiben auf dem letzten Frame (kein vorzeitiges 00:00:00;00)")
        self.assertEqual(out["lastPal"], 2159999)
        self.assertEqual(out["nan"], [None, None])
        self.assertEqual(out["day"], [0, 5, 86399999, 36942500, None, None])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class AnzeigeTest(unittest.TestCase):
    def test_zehntel_frames_und_ohne_feinstelle(self):
        out = run_tc("""
          const at = (h, m, s, ms) => ((h * 60 + m) * 60 + s) * 1000 + ms;
          console.log(JSON.stringify({
            tenths: tc.tcView(at(10, 15, 42, 500), "25", "tenths"),
            floor: tc.tcView(at(10, 15, 42, 999.9), "25", "tenths").text,
            frames: tc.tcView(at(10, 15, 42, 500), "25", "frames"),
            frames50: tc.tcView(at(10, 15, 42, 500), "50", "frames").text,
            frames24: tc.tcView(at(10, 15, 42, 999), "24", "frames").text,
            df: tc.tcView(at(0, 1, 0, 100), "29.97", "frames"),
            off: tc.tcView(at(23, 59, 59, 999), "60", "off"),
            dflt: tc.tcView(at(1, 2, 3, 450), undefined).text,
            none: [tc.tcView(NaN, "25", "tenths").text, tc.tcView(NaN, "25", "frames").text, tc.tcView(NaN, "25", "off").text],
            wrap: tc.tcView(tc.DAY_MS + at(0, 0, 1, 0), "25", "frames").text,
          }));
        """)
        self.assertEqual(out["tenths"], {"hh": "10", "mm": "15", "ss": "42", "sep": ".", "fine": "5", "text": "10:15:42.5"})
        self.assertEqual(out["floor"], "10:15:42.9", "Zehntel werden abgerundet")
        self.assertEqual(out["frames"], {"hh": "10", "mm": "15", "ss": "42", "sep": ":", "fine": "12", "text": "10:15:42:12"})
        self.assertEqual(out["frames50"], "10:15:42:25")
        self.assertEqual(out["frames24"], "10:15:42:23")
        self.assertEqual(out["df"]["sep"], ";")
        self.assertRegex(out["df"]["text"], r"^00:0[01]:\d\d;\d\d\Z")
        self.assertEqual(out["off"], {"hh": "23", "mm": "59", "ss": "59", "sep": "", "fine": "", "text": "23:59:59"})
        self.assertEqual(out["dflt"], "01:02:03.4", "Standard: Zehntel")
        self.assertEqual(out["none"], ["--:--:--.-", "--:--:--:--", "--:--:--"])
        self.assertEqual(out["wrap"], "00:00:01:00")

    def test_feinstelle_nur_auf_wunsch_frames(self):
        out = run_tc("""
          console.log(JSON.stringify({
            standard: ["utc", "tz2", "date", "tenths", null, undefined].map((s) => tc.fineMode(s)),
            frames: tc.fineMode("frames"), off: tc.fineMode("off"),
            reduced: [tc.fineMode("frames", { reduced: true }), tc.fineMode("tenths", { reduced: true })],
            eink: ["frames", "tenths", "utc"].map((s) => tc.fineMode(s, { eink: true })),
            noSeconds: tc.fineMode("frames", { seconds: false }),
            studio: ["utc", "tz2", "date", "off", "tenths", "frames"].map(tc.studioSub),
          }));
        """)
        self.assertEqual(out["standard"], ["tenths"] * 6)
        self.assertEqual((out["frames"], out["off"]), ("frames", "off"))
        self.assertEqual(out["reduced"], ["tenths", "tenths"], "weniger Bewegung: nie Frames, höchstens Zehntel")
        self.assertEqual(out["eink"], ["off", "off", "off"], "E-Ink: keine Feinstelle")
        self.assertEqual(out["noSeconds"], "off")
        self.assertEqual(out["studio"], ["utc", "tz2", "date", "off", "utc", "utc"])

    def test_feinstelle_grau_und_ausgeblendet(self):
        out = run_tc("""
          const lv = (o) => { const r = tc.fineLevel(o); return [r.level, r.reason]; };
          console.log(JSON.stringify({
            limits: [tc.fineLevel({ mode: "frames", fps: "25" }).limit, tc.fineLevel({ mode: "frames", fps: "50" }).limit,
              tc.fineLevel({ mode: "tenths" }).limit, Math.round(tc.fineLevel({ mode: "frames", fps: "29.97" }).limit * 100) / 100],
            frames25: [19.9, 20, 20.1, 100, 100.1].map((boundMs) => lv({ mode: "frames", fps: "25", boundMs })),
            frames50: [9.9, 10.1].map((boundMs) => lv({ mode: "frames", fps: "50", boundMs })),
            tenths: [49.9, 50.1, 100, 101].map((boundMs) => lv({ mode: "tenths", boundMs })),
            maxerr: [lv({ mode: "tenths", boundMs: 30, maxerrMs: 20 }), lv({ mode: "tenths", boundMs: 300, maxerrMs: 1000 })],
            unknown: [lv({ mode: "tenths", boundMs: null }), lv({ mode: "frames", boundMs: NaN })],
            off: lv({ mode: "off", boundMs: 1 }),
            grain: [lv({ mode: "tenths", boundMs: 5, grainMs: 100 }), lv({ mode: "tenths", boundMs: 5, grainMs: 16.7 }),
              lv({ mode: "frames", fps: "50", boundMs: 5, grainMs: 16.7 }), lv({ mode: "frames", fps: "25", boundMs: 5, grainMs: 16.7 }),
              lv({ mode: "tenths", boundMs: 5, grainMs: Infinity }), lv({ mode: "tenths", boundMs: 5, grainMs: null }),
              lv({ mode: "tenths", boundMs: 5, grainMs: 1 }), lv({ mode: "tenths", boundMs: 500, grainMs: 100 }),
              lv({ mode: "tenths", boundMs: 60, grainMs: 100 })],
          }));
        """)
        self.assertEqual(out["limits"], [20, 10, 50, 16.68])
        self.assertEqual(out["frames25"], [["sure", ""], ["sure", ""], ["unsure", "bound"], ["unsure", "bound"], ["off", "bound"]],
                         "Frames grau über ½ Frame, weg über maxerr")
        self.assertEqual(out["frames50"], [["sure", ""], ["unsure", "bound"]])
        self.assertEqual(out["tenths"], [["sure", ""], ["unsure", "bound"], ["unsure", "bound"], ["off", "bound"]])
        self.assertEqual(out["maxerr"], [["off", "bound"], ["unsure", "bound"]])
        self.assertEqual(out["unknown"], [["off", "bound"], ["off", "bound"]], "ohne Schranke keine Feinstelle")
        self.assertEqual(out["off"], ["off", ""])
        self.assertEqual(out["grain"], [["unsure", "grain"], ["sure", ""], ["unsure", "grain"], ["sure", ""], ["unsure", "grain"],
                                        ["sure", ""], ["sure", ""], ["off", "bound"], ["unsure", "bound"]])

    def test_grobe_zeitgeber_erkennen(self):
        out = run_tc("""
          const every = (n, step, round) => Array.from({ length: n }, (_, i) => { const v = 1000.3 + i * step;
            return round ? Math.floor(v / round) * round : v; });
          const fine = every(12, 4.2, 0);
          const ms1 = every(12, 4.2, 1);
          const rfp100 = every(60, 4.2, 100);
          const rfp16 = every(20, 4.2, 100 / 6);
          const stuck = Array.from({ length: tc.GRAIN_MAX_SAMPLES }, () => 500);
          console.log(JSON.stringify({
            fine: tc.timerGrain(fine), ms1: tc.timerGrain(ms1), rfp100: tc.timerGrain(rfp100),
            rfp16: Math.round(tc.timerGrain(rfp16) * 10) / 10, stuck: tc.timerGrain(stuck) === Infinity,
            few: [tc.timerGrain(every(11, 4.2, 0)), tc.timerGrain([]), tc.timerGrain(null)],
            unsorted: tc.timerGrain([...ms1].reverse()),
            done: [tc.grainDone(every(11, 4.2, 0)), tc.grainDone(fine), tc.grainDone(every(12, 4.2, 100)),
              tc.grainDone(every(60, 4.2, 100)), tc.grainDone(stuck), tc.grainDone(null)],
          }));
        """)
        self.assertEqual(out["fine"], 4.2)
        self.assertGreaterEqual(out["ms1"], 1)
        self.assertLessEqual(out["ms1"], 5)
        self.assertEqual(out["rfp100"], 100, "auf 100 ms gerundete Zeitgeber")
        self.assertEqual(out["rfp16"], 16.7)
        self.assertTrue(out["stuck"], "bewegt sich der Wert nie, ist das Raster gröber als die Messung")
        self.assertEqual(out["few"], [None, None, None])
        self.assertEqual(out["unsorted"], out["ms1"])
        self.assertEqual(out["done"], [False, True, False, True, True, False],
                         "bei grobem Raster so lange messen, bis drei verschiedene Werte da sind")

    def test_ausgeblendete_feinstelle_zeigt_die_wanduhr_sekunde(self):
        # Drop-Frame läuft der Wanduhr früh am Tag nach: 5 ms nach der vollen Sekunde steht der Timecode noch auf ;29
        # der vorigen Sekunde. Ohne sichtbare Feinstelle wird nur dann gezeichnet – also mit der Wanduhr rechnen.
        out = run_tc("""
          const at = (h, m, s, ms) => ((h * 60 + m) * 60 + s) * 1000 + ms;
          const shown = (tod, fps, level) => tc.tcView(tod, fps, tc.paintMode("frames", level)).text;
          console.log(JSON.stringify({
            frames: [tc.tcView(34005, "29.97", "frames").text, tc.tcView(at(1, 0, 34, 5), "29.97", "frames").text,
              tc.tcView(at(1, 15, 43, 5), "59.94", "frames").text],
            off: [shown(34005, "29.97", "off"), shown(at(1, 0, 34, 5), "29.97", "off"), shown(at(1, 15, 43, 5), "59.94", "off")],
            visible: [shown(34005, "29.97", "sure"), shown(34005, "29.97", "unsure")],
            modes: [tc.paintMode("frames", "off"), tc.paintMode("tenths", "off"), tc.paintMode("frames", "unsure"),
              tc.paintMode("tenths", "sure"), tc.paintMode("off", "off")],
          }));
        """)
        self.assertEqual(out["frames"], ["00:00:33;29", "01:00:33;29", "01:15:42;59"], "der Timecode läuft hier nach")
        self.assertEqual(out["off"], ["00:00:34", "01:00:34", "01:15:43"])
        self.assertEqual(out["visible"], ["00:00:33;29", "00:00:33;29"], "mit sichtbarer Feinstelle bleibt es der Timecode")
        self.assertEqual(out["modes"], ["off", "off", "frames", "tenths", "off"])

    def test_taste_t_wechsel(self):
        out = run_tc("""
          const walk = (start, base, n) => { const seen = []; let cur = start;
            for (let i = 0; i < n; i += 1) { cur = tc.nextFine(cur, base); seen.push(cur); } return seen; };
          console.log(JSON.stringify({ standard: walk("tenths", "tenths", 3), frames: walk("frames", "frames", 3),
            off: walk("off", "off", 4), studio: walk("utc", "utc", 2), none: walk(undefined, undefined, 2) }));
        """)
        self.assertEqual(out["standard"], ["frames", "tenths", "frames"])
        self.assertEqual(out["frames"], ["tenths", "frames", "tenths"])
        self.assertEqual(out["off"], ["tenths", "frames", "off", "tenths"], "mit ?sub=off führt T zurück zu aus")
        self.assertEqual(out["studio"], ["frames", "tenths"])
        self.assertEqual(out["none"], ["frames", "tenths"])

    def test_kalendertag_in_der_zone_des_servers(self):
        mods = json.dumps((JS / "clockcount.js").as_uri())
        out = run_tc(f"""
          const cd = await import({mods});
          const day = (iso, zone) => {{ const ms = Date.parse(iso); return tc.zoneDay(ms, cd.zoneOffset(ms, zone)); }};
          console.log(JSON.stringify({{
            auckland: day("2026-11-15T15:37:27Z", "Pacific/Auckland"), tokyo: day("2026-11-15T15:46:37Z", "Asia/Tokyo"),
            berlin: day("2026-11-15T15:37:27Z", "Europe/Berlin"), honolulu: day("2026-01-01T05:00:00Z", "Pacific/Honolulu"),
            leap: day("2028-02-28T23:30:00Z", "Europe/Berlin"), invalid: [tc.zoneDay(NaN, 0), tc.zoneDay(0, NaN)],
          }}));
        """)
        self.assertEqual(out["auckland"], {"y": 2026, "mo": 11, "d": 16}, "dort ist schon Montag")
        self.assertEqual(out["tokyo"], {"y": 2026, "mo": 11, "d": 16})
        self.assertEqual(out["berlin"], {"y": 2026, "mo": 11, "d": 15})
        self.assertEqual(out["honolulu"], {"y": 2025, "mo": 12, "d": 31}, "über den Jahreswechsel zurück")
        self.assertEqual(out["leap"], {"y": 2028, "mo": 2, "d": 29})
        self.assertEqual(out["invalid"], [None, None])

    def test_ohne_dom_und_zeitgeber(self):
        text = (JS / "clocktc.js").read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        self.assertNotRegex(code, r"\bdocument\b|\bwindow\b|setTimeout|setInterval|requestAnimationFrame|Date\.now|performance")
        self.assertEqual(re.findall(r'from "([^"]+)"', text), ["./clockkit.js"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ParameterTest(unittest.TestCase):
    """fps und die Werte tenths/frames von sub: gleich in Schema, Server-Allowlist, Link-Baukasten und Doku."""

    FPS = ["24", "25", "30", "50", "60", "29.97", "59.94"]

    def test_schema(self):
        out = run_tc("""
          const p = (q) => k.parseParams(q);
          const entry = (name) => k.PARAM_SCHEMA.find((e) => e.name === name);
          console.log(JSON.stringify({
            fps: entry("fps"), sub: entry("sub"), designs: k.DESIGNS, rates: Object.keys(tc.TC_RATES), list: k.TC_FPS,
            ok: p("?design=tc&fps=29.97&sub=frames"), dflt: p("?design=tc"),
            bad: ["23.976", "29,97", "29.970", "25 ", "025", "2997", "1e1", "<script>", "", "30000/1001", "59.94df"]
              .map((v) => p("?fps=" + encodeURIComponent(v))).map((r) => [r.fps, r.ignored]),
            every: k.TC_FPS.map((v) => p("?fps=" + v).fps),
          }));
        """)
        self.assertEqual(out["fps"], {"name": "fps", "type": "enum", "values": self.FPS, "default": "25"})
        self.assertEqual(out["sub"]["values"], ["utc", "tz2", "date", "off", "tenths", "frames"])
        self.assertEqual(out["sub"]["default"], "utc", "Standard bleibt; das Design tc zeigt damit Zehntel")
        self.assertIn("tc", out["designs"])
        self.assertLessEqual(len(out["designs"]), 8, "höchstens acht Designs")
        self.assertEqual(sorted(out["rates"]), sorted(self.FPS))
        self.assertEqual(out["list"], self.FPS)
        self.assertEqual((out["ok"]["design"], out["ok"]["fps"], out["ok"]["sub"], out["ok"]["ignored"]), ("tc", "29.97", "frames", []))
        self.assertEqual((out["dflt"]["fps"], out["dflt"]["sub"]), ("25", "utc"))
        for fps, ignored in out["bad"]:
            self.assertEqual((fps, ignored), ("25", ["fps"]))
        self.assertEqual(out["every"], self.FPS)

    def test_server_allowlist(self):
        self.assertEqual(list(clockprofiles.PARAMS["fps"][1]["values"]), self.FPS)
        self.assertEqual(clockprofiles.PARAMS["fps"][0], "enum")
        self.assertIn("tc", clockprofiles.DESIGNS)
        clean = clockprofiles.clean_profile({"title": "Schnitt", "params": {"design": "tc", "fps": "59.94", "sub": "frames"}})
        self.assertEqual(clean["params"], {"design": "tc", "sub": "frames", "fps": "59.94"})
        self.assertEqual(clockprofiles.check_value("fps", 50), "50")
        self.assertEqual(clockprofiles.check_value("sub", "tenths"), "tenths")
        for bad in ("23.976", "29,97", "29.970", "25\n", " 25", "025", "", "59.94df", "<b>", 29.97, None, ["25"]):
            with self.subTest(bad=bad):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.check_value("fps", bad)
        public = clockprofiles.public_profile("schnitt", {"schnitt": {"title": "S", "params": {"design": "tc", "fps": "23.976"}}})
        self.assertEqual(public["params"], {"design": "tc"}, "unzulässige Bildrate wird nicht ausgeliefert")

    def test_link_baukasten(self):
        out = run_tc("""
          const groups = l.FORM_GROUPS.filter((g) => g.names.includes("fps")).map((g) => g.key);
          console.log(JSON.stringify({
            groups, all: k.PARAM_SCHEMA.every((e) => l.FORM_GROUPS.filter((g) => g.names.includes(e.name)).length === 1),
            link: l.buildQuery({ design: "tc", fps: "29.97", sub: "frames" }),
            dflt: l.buildQuery({ design: "tc", fps: "25", sub: "utc" }),
            bad: l.buildQuery({ design: "tc", fps: "23.976" }),
            valid: [l.rawValid("fps", "59.94"), l.rawValid("fps", "59,94"), l.rawValid("sub", "frames")],
            layered: l.effectiveQuery({ search: "?fps=50", profile: { design: "tc", fps: "29.97", sub: "frames" } }),
            stored: l.storedQuery("design=tc&fps=60&sub=tenths"),
          }));
        """)
        self.assertEqual(out["groups"], ["digits"])
        self.assertTrue(out["all"], "jeder Parameter steht in genau einer Gruppe")
        self.assertEqual(out["link"], "design=tc&sub=frames&fps=29.97")
        self.assertEqual(out["dflt"], "design=tc")
        self.assertEqual(out["bad"], "design=tc")
        self.assertEqual(out["valid"], [True, False, True])
        self.assertEqual(out["layered"], "design=tc&sub=frames&fps=50", "Adresse geht vor dem Profil")
        self.assertEqual(out["stored"], "design=tc&sub=tenths&fps=60")

    def test_doku_nennt_parameter_und_grenze(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_text = (JS / "help-uhr.js").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        for name, text in (("README", readme), ("help-uhr.js", help_text), ("studiouhr.md", guide)):
            with self.subTest(name=name):
                plain = text.replace("\\|", "|")
                self.assertIn("design=tc", plain)
                self.assertIn("fps=24|25|30|50|60|29.97|59.94", plain)
                self.assertRegex(plain, r"sub=(tenths\|)?frames")
                self.assertIn("Anzeige-Timecode – nicht genlocked", plain)
                self.assertIn("halbes Frame", plain)


class TexteUndSeiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")
        cls.cat = {lang: json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
                   for lang in ("de", "en")}

    def test_texte_in_beiden_sprachen(self):
        keys = ["tc_label", "tc_info_title", "tc_info", "tc_rate", "tc_rate_df", "tc_fine_tenths", "tc_fine_frames",
                "tc_fine_off", "tc_unsure_tenths", "tc_unsure_frames", "tc_grain", "tc_grain_unknown", "tc_reduced",
                "hint_tc_tenths", "hint_tc_frames", "hint_tc_reduced", "hint_tc_eink", "hint_tc_off", "hint_tc_noseconds",
                "tc_why_frames", "tc_why_tenths", "tc_why_grain", "tc_why_off"]
        for lang, clock in self.cat.items():
            for key in keys:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(clock.get(key))
                    self.assertIn(f'"clock.{key}"', self.js, "Text wird auch benutzt")
            self.assertTrue(clock["design"]["tc"])
            self.assertTrue(clock["link"]["f"]["fps"])
        de = self.cat["de"]
        self.assertEqual(de["tc_label"], "Anzeige-Timecode – nicht genlocked")
        for part in ("Hausreferenzsignal", "Black Burst", "60-Hz-Monitor", "resistFingerprinting", "100 ms", "± 1 bis 2 Frames",
                     "LTC", "VITC", "halbes Frame", "Drop-Frame"):
            self.assertIn(part, de["tc_info"])
        for part in ("black burst", "60 Hz", "resistFingerprinting", "100 ms", "LTC", "VITC"):
            self.assertIn(part, self.cat["en"]["tc_info"])
        self.assertEqual(self.cat["en"]["tc_label"], "Display timecode – not genlocked")
        # du-Form in den Texten, die jemanden ansprechen.
        for key in ("tc_info", "tc_grain", "tc_reduced", "hint_tc_reduced"):
            self.assertRegex(de[key], r"\b[Dd]ein\b", key)
            self.assertNotRegex(de[key], r"\b(Ihr|Ihre|Ihren|Ihrem|Ihnen)\b", key)
        for placeholder_key, names in (("tc_unsure_tenths", ("{acc}", "{limit}")), ("tc_unsure_frames", ("{acc}", "{limit}")),
                                       ("tc_grain", ("{grain}",)), ("tc_rate", ("{fps}",)), ("tc_rate_df", ("{fps}",))):
            for lang, clock in self.cat.items():
                for name in names:
                    self.assertIn(name, clock[placeholder_key], f"{lang} {placeholder_key}")

    def test_auswahl_und_kuerzel(self):
        self.assertIn('<option value="tc" data-i18n="clock.design.tc">Timecode</option>', self.html)
        self.assertIn("Frames", self.cat["de"]["keys"]["t"])
        self.assertIn("frames", self.cat["en"]["keys"]["t"])
        start = self.js.index("function toggleTenths()")
        body = self.js[start:self.js.index("\n}\n", start)]
        # Nur wenn der Timecode die Hauptanzeige ist: Mit ?cd=main schaltet T die Zehntel von Timer und Stoppuhr.
        self.assertIn('if (state.design === "tc" && !countdownMain()) { toggleTcFine(); return; }', body)
        start = self.js.index("function toggleTcFine()")
        fine = self.js[start:self.js.index("\n}\n", start)]
        # Ohne Sekunden kein Wechsel und keine Erfolgsmeldung; ?sub=off führt wieder zu „aus“.
        self.assertLess(fine.index('hint(t("clock.hint_tc_noseconds")); return;'), fine.index("state.tcSub = want"))
        self.assertIn("tc.nextFine(state.tcSub || params.sub, params.sub)", fine)
        self.assertIn('if (want === "off") hint(t("clock.hint_tc_off"));', fine)

    def test_kopfzeile_immer_und_feinstelle_nie_nur_farbe(self):
        start = self.js.index("function buildTc(face)")
        build = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('t("clock.tc_label")', build)
        self.assertIn('infoButton("clock.tc_info_title", "clock.tc_info")', build)
        self.assertIn('row.setAttribute("aria-hidden", "true")', build)
        self.assertNotIn("innerHTML", self.js)
        block = self.css[self.css.index("/* --- Studiouhr B1"):self.css.index("/* --- Studiouhr A5")]
        self.assertIn('.tc-fine[data-level="unsure"] { color: var(--ink-unsure); }', block)
        self.assertIn('.tc-fine[data-level="off"] { visibility: hidden; }', block)
        self.assertIn(".tc-fine.is-gone { display: none; }", block)
        self.assertNotRegex(block, r"\banimation\b|\btransition\b|@keyframes", "Ziffernwechsel ohne Animation")
        # Die Kopfzeile bricht um statt aus dem Bild zu laufen.
        head = block[block.index(".tc-head {"):block.index("}", block.index(".tc-head {"))]
        self.assertNotIn("nowrap", head)
        self.assertIn("max-width: 100%", head)
        # Wo die Zeile unter der Zeit ausgeblendet ist, steht der Grund kurz in der Kopfzeile (.tc-why).
        self.assertIn(".tc-why { display: none; }", block)
        hidden = len(re.findall(r"\.tc-note[^{}]*\{ display: none; \}", block))
        self.assertEqual(hidden, 2, "Streifen/Kachel und niedrige Flächen")
        self.assertEqual(block.count(".tc-why { display: inline; }"), hidden, "je ausgeblendeter Zeile der Grund in der Kopfzeile")
        self.assertIn('.clock-stage:is([data-layout="strip"], [data-layout="tile"]) .tc-why { display: inline; }', block)
        self.assertIn("@media (max-height: 320px) { .face-tc { font-size: min(15vw, 30vh); } .tc-note { display: none; } "
                      ".tc-why { display: inline; } }", block)
        # Die Kopfzeile wird in keinem Layout ausgeblendet (nur ⓘ und die Zeile darunter).
        for rule in re.findall(r"[^{}]*\{[^{}]*display: none[^{}]*\}", block):
            selector = rule.split("{")[0]
            if ".tc-head" in selector:
                self.assertRegex(selector, r"\.tc-head \.info", rule)
            self.assertNotIn(".tc-label", selector)
        for selector, floor in ((".tc-head {", "12px"), (".tc-note {", "12px")):
            rule = block[block.index(selector):block.index("}", block.index(selector))]
            self.assertRegex(rule, rf"font-size: max\([0-9.]+em, {floor}\)", selector)
        # Der Grund für eine graue oder fehlende Feinstelle steht als Text unter der Zeit.
        start = self.js.index("function renderTc(ms)")
        render = self.js[start:self.js.index("\n}\n", start)]
        for key in ("clock.tc_grain", "clock.tc_fine_off", "clock.tc_unsure_frames", "clock.tc_unsure_tenths", "clock.tc_reduced",
                    "clock.tc_why_grain", "clock.tc_why_off", "clock.tc_why_frames", "clock.tc_why_tenths"):
            self.assertIn(key, render)
        # Ausgeblendete Feinstelle: Sekunden aus der Wanduhr; die Auto-Anpassung misst nur die Ziffernzeile.
        self.assertIn("paintTc(ms, tc.paintMode(mode, level.level))", render)
        start = self.js.index("function timeBox()")
        self.assertIn("[state.face.row]", self.js[start:self.js.index("\n}\n", start)])
        start = self.js.index("function fitOnce(main)")
        self.assertIn("tcFixed()", self.js[start:self.js.index("\n}\n", start)])
        start = self.js.index("function fitTimeOnly()")
        self.assertIn("fitOnce(main)", self.js[start:self.js.index("\n}\n", start)])

    def test_datum_und_nebenzeile_in_der_zone_des_servers(self):
        start = self.js.index("function render(now)")
        body = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("tcForeignOffset(now.getTime())", body)
        self.assertIn("tc.zoneDay(now.getTime(), foreign)", body)
        self.assertIn('setText($("local-date"), dateText(day));', body)
        self.assertIn("isoWeek(day)", body)
        self.assertIn("kit.zoneLabel(tcZone())", body)
        start = self.js.index("function tcForeignOffset(ms)")
        foreign = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('if (state.design !== "tc") return null;', foreign)
        self.assertIn("zone !== browserZone()", foreign)

    def test_bildschleife_nur_fuer_die_feinstelle(self):
        start = self.js.index("function tcRunning()")
        body = self.js[start:self.js.index("\n}\n", start)]
        for need in ('state.design === "tc"', 'state.tcLevel !== "off"', 'tcMode() !== "off"',
                     'document.visibilityState === "visible"'):
            self.assertIn(need, body)
        start = self.js.index("function tcMode()")
        mode = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("eink: params.eink, reduced: reducedMotion.matches", mode)
        # Die Bildschleife schreibt nur Text (paintTc), sie misst und baut nichts.
        start = self.js.index("function paintTc(ms, mode)")
        paint = self.js[start:self.js.index("\n}\n", start)]
        self.assertNotRegex(paint, r"fitTime|getBoundingClientRect|getComputedStyle|setAttribute|setAttr\(")

    def test_datei_oeffentlich_und_eingebunden(self):
        self.assertIn("/static/js/clocktc.js", server.CLOCK_PUBLIC_PATHS)
        self.assertIn('import * as tc from "./clocktc.js";', self.js)
        self.assertTrue((JS / "clocktc.js").is_file())


if __name__ == "__main__":
    unittest.main()
