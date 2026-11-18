"""Studiouhr B2: Weltzeit (?tz= mit bis zu sechs Zonen, ?tzl= mit Kurznamen, Layout world).

Die reinen Rechnungen stehen in app/static/js/clockworld.js und laufen hier mit Node, immer zu festen Zeitpunkten:
Abweichung zur Bezugszeit und Tageswechsel an den Umstellungstagen beider Seiten (Europa 29.3. und 25.10., USA 8.3.
und 1.11., Australien), Zonen mit 30- und 45-Minuten-Versatz, die Datumsgrenze. Dazu: derselbe Parameter in Schema,
Server-Allowlist, Link-Baukasten und Doku, Kurznamen mit Sonderzeichen werden verworfen, die Texte in beiden Sprachen
und Regeln für clock.js/clock.css (Kurzname nur als Text, Tag/Nacht mit Text-Alternative, keine Leiste in Streifen und
Kachel). Dazu die Schreibweise der Listen (Leerzeichen um die Kommas, Länge in Zeichen – Uhr und Server gleich) und
die Regeln des Einpassens: ?show= ohne tz, Zeilen der Leiste, Raster einspaltig vor dem Weglassen, ?h12=1 in den Zonen,
Wachsen der Leiste, Vorschlagsliste im Link-Baukasten.
"""

import json
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

M = "−"   # Minuszeichen der Anzeige


def run_world(code: str):
    mods = {name: json.dumps((JS / f"{name}.js").as_uri()) for name in ("clockworld", "clockkit", "clocklink", "clockcount")}
    script = (f"import * as w from {mods['clockworld']};\nimport * as k from {mods['clockkit']};\n"
              f"import * as l from {mods['clocklink']};\nimport * as c from {mods['clockcount']};\n"
              # Zeile einer Zone zum Zeitpunkt iso, gesehen aus der Zone ref: [Uhrzeit, Abweichung, Tageswechsel, Nacht]
              "const row = (iso, zone, ref = 'Europe/Berlin') => { const ms = Date.parse(iso);\n"
              "  const r = w.worldRow(ms, { zone, label: '' }, c.zoneOffset(ms, ref)); return [r.time, r.delta, r.day, r.night]; };\n"
              f"{code}")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120,
                         env={"TZ": "Pacific/Auckland", "PATH": __import__("os").environ.get("PATH", "")})
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class UmstellungstageTest(unittest.TestCase):
    """Feste Zeitpunkte; die Zeitzone des Rechners (hier Pacific/Auckland) spielt keine Rolle."""

    def test_europa_stellt_am_29_maerz_um(self):
        out = run_world("""
          console.log(JSON.stringify({
            before: ["Europe/London", "America/New_York", "Asia/Tokyo", "UTC"].map((z) => row("2026-03-29T00:59:00Z", z)),
            after: ["Europe/London", "America/New_York", "Asia/Tokyo", "UTC"].map((z) => row("2026-03-29T01:00:00Z", z)),
          }));
        """)
        # 01:59 MEZ: London stellt im selben Augenblick um (immer 1 h zurück), die USA sind seit dem 8.3. voraus.
        self.assertEqual(out["before"], [["00:59", f"{M}1 h", 0, True], ["20:59", f"{M}5 h", -1, True],
                                         ["09:59", "+8 h", 0, False], ["00:59", f"{M}1 h", 0, True]])
        # 03:00 MESZ: New York wieder 6 h zurück, Tokio nur noch 7 h voraus, UTC 2 h zurück.
        self.assertEqual(out["after"], [["02:00", f"{M}1 h", 0, True], ["21:00", f"{M}6 h", -1, True],
                                        ["10:00", "+7 h", 0, False], ["01:00", f"{M}2 h", 0, True]])

    def test_europa_stellt_am_25_oktober_zurueck(self):
        out = run_world("""
          console.log(JSON.stringify({
            before: ["America/New_York", "Asia/Tokyo", "Europe/London"].map((z) => row("2026-10-25T00:59:59Z", z)),
            after: ["America/New_York", "Asia/Tokyo", "Europe/London"].map((z) => row("2026-10-25T01:00:00Z", z)),
            usBack: [row("2026-11-01T05:59:00Z", "America/New_York"), row("2026-11-01T06:00:00Z", "America/New_York")],
          }));
        """)
        self.assertEqual(out["before"], [["20:59", f"{M}6 h", -1, True], ["09:59", "+7 h", 0, False], ["01:59", f"{M}1 h", 0, True]])
        # Zweite Stunde 2 Uhr in Berlin (MEZ): die USA stellen erst am 1.11. zurück – eine Woche lang nur 5 h.
        self.assertEqual(out["after"], [["21:00", f"{M}5 h", -1, True], ["10:00", "+8 h", 0, False], ["01:00", f"{M}1 h", 0, True]])
        self.assertEqual(out["usBack"], [["01:59", f"{M}5 h", 0, True], ["01:00", f"{M}6 h", 0, True]])

    def test_usa_stellen_am_8_maerz_um(self):
        out = run_world("""
          console.log(JSON.stringify({
            ny: [row("2026-03-08T06:59:00Z", "America/New_York"), row("2026-03-08T07:00:00Z", "America/New_York")],
            la: [row("2026-03-08T09:59:00Z", "America/Los_Angeles"), row("2026-03-08T10:00:00Z", "America/Los_Angeles")],
            // Von New York aus gesehen springt Berlin am selben Tag von +6 auf +5.
            fromNy: [row("2026-03-08T06:59:00Z", "Europe/Berlin", "America/New_York"),
              row("2026-03-08T07:00:00Z", "Europe/Berlin", "America/New_York")],
            phoenix: [row("2026-03-08T12:00:00Z", "America/Phoenix", "America/Los_Angeles"),
              row("2026-03-07T12:00:00Z", "America/Phoenix", "America/Los_Angeles")],
          }));
        """)
        self.assertEqual(out["ny"], [["01:59", f"{M}6 h", 0, True], ["03:00", f"{M}5 h", 0, True]])
        self.assertEqual(out["la"], [["01:59", f"{M}9 h", 0, True], ["03:00", f"{M}8 h", 0, True]])
        self.assertEqual(out["fromNy"], [["07:59", "+6 h", 0, False], ["08:00", "+5 h", 0, False]])
        self.assertEqual([r[1] for r in out["phoenix"]], ["±0 h", "+1 h"], "Arizona stellt nicht um")

    def test_suedhalbkugel_und_halbe_stunden(self):
        out = run_world("""
          console.log(JSON.stringify({
            sydney: ["2026-01-15T12:00:00Z", "2026-04-04T15:59:00Z", "2026-04-04T16:00:00Z", "2026-07-15T12:00:00Z",
              "2026-10-03T16:00:00Z"].map((t) => row(t, "Australia/Sydney")),
            half: ["Asia/Kolkata", "Asia/Kathmandu", "Australia/Adelaide", "America/St_Johns", "Pacific/Chatham",
              "Australia/Eucla"].map((z) => row("2026-01-15T12:00:00Z", z)),
            halfUtc: ["Asia/Kolkata", "Asia/Kathmandu", "America/St_Johns"].map((z) => row("2026-01-15T12:00:00Z", z, "UTC")),
            lordHowe: [row("2026-01-15T12:00:00Z", "Australia/Lord_Howe", "UTC"), row("2026-07-15T12:00:00Z", "Australia/Lord_Howe", "UTC")],
          }));
        """)
        # Sydney: im Januar Sommerzeit (+10 gegen MEZ), nach dem 5.4. Normalzeit gegen MESZ (+8), ab 4.10. wieder +9.
        self.assertEqual([r[:3] for r in out["sydney"]], [["23:00", "+10 h", 0], ["02:59", "+9 h", 1], ["02:00", "+8 h", 1],
                                                          ["22:00", "+8 h", 0], ["03:00", "+9 h", 1]])
        self.assertEqual([r[:3] for r in out["half"]], [["17:30", "+4:30 h", 0], ["17:45", "+4:45 h", 0], ["22:30", "+9:30 h", 0],
                                                        ["08:30", f"{M}4:30 h", 0], ["01:45", "+12:45 h", 1],
                                                        ["20:45", "+7:45 h", 0]])
        self.assertEqual([r[1] for r in out["halfUtc"]], ["+5:30 h", "+5:45 h", f"{M}3:30 h"])
        self.assertEqual([r[:2] for r in out["lordHowe"]], [["23:00", "+11 h"], ["22:30", "+10:30 h"]], "Sommerzeit nur 30 min")

    def test_datumsgrenze(self):
        out = run_world("""
          const at = "2026-06-30T10:30:00Z";
          console.log(JSON.stringify({
            utc: ["Pacific/Kiritimati", "Etc/GMT+12", "Pacific/Auckland", "Pacific/Pago_Pago", "Pacific/Apia"].map((z) => row(at, z, "UTC")),
            edge: [row(at, "Etc/GMT+12", "Pacific/Kiritimati"), row(at, "Pacific/Kiritimati", "Etc/GMT+12")],
            // Nachbarn über die Grenze: Samoa (Apia) und Amerikanisch-Samoa zeigen dieselbe Uhrzeit, einen Tag versetzt.
            samoa: row(at, "Pacific/Apia", "Pacific/Pago_Pago"),
            midnight: [row("2026-12-31T22:59:59Z", "Asia/Tokyo"), row("2026-12-31T23:00:00Z", "Asia/Tokyo"),
              row("2026-12-31T23:00:00Z", "America/New_York")],
            text: [1, -1, 2, -2, 0, 1.5].map((n) => w.dayShiftText(n)),
            textEn: [w.dayShiftText(1, { day: "day", days: "days" }), w.dayShiftText(-2, { day: "day", days: "days" })],
            shift: [w.dayShift(0, 0, 0), w.dayShift(NaN, 0, 0), w.dayShift(86399999, 0, 1), w.dayShift(0, 0, -1)],
          }));
        """)
        self.assertEqual(out["utc"], [["00:30", "+14 h", 1, True], ["22:30", f"{M}12 h", -1, True], ["22:30", "+12 h", 0, True],
                                      ["23:30", f"{M}11 h", -1, True], ["23:30", "+13 h", 0, True]])
        self.assertEqual(out["edge"], [["22:30", f"{M}26 h", -2, True], ["00:30", "+26 h", 2, True]])
        self.assertEqual(out["samoa"], ["23:30", "+24 h", 1, True])
        # Silvester in Berlin: Tokio ist bis 23:59:59 MEZ einen Tag voraus, danach im selben Tag; New York dann einen zurück.
        self.assertEqual(out["midnight"], [["07:59", "+8 h", 1, False], ["08:00", "+8 h", 0, False], ["18:00", f"{M}6 h", -1, True]])
        self.assertEqual(out["text"], ["+1 Tag", f"{M}1 Tag", "+2 Tage", f"{M}2 Tage", "", ""])
        self.assertEqual(out["textEn"], ["+1 day", f"{M}2 days"])
        self.assertEqual(out["shift"], [0, 0, 1, -1])

    def test_tag_und_nacht_nach_der_uhrzeit_der_zone(self):
        out = run_world("""
          console.log(JSON.stringify({
            hours: [0, 5, 6, 12, 17, 18, 23].map((h) => w.isNight(h)),
            rows: ["2026-06-30T03:59:00Z", "2026-06-30T04:00:00Z", "2026-06-30T15:59:00Z", "2026-06-30T16:00:00Z"]
              .map((t) => row(t, "Europe/Berlin", "UTC")),
            symbols: [w.SUN, w.MOON].map((s) => [...s].map((c) => c.codePointAt(0).toString(16))),
            view: w.worldView(Date.parse("2026-06-30T08:15:42.500Z"), w.worldEntries(["Europe/London", "Asia/Tokyo"], ["LON"]), 7200000),
            none: [w.worldView(NaN, [], 0), w.worldView(0, null, 0)],
          }));
        """)
        self.assertEqual(out["hours"], [True, True, False, False, False, True, True])
        self.assertEqual([(r[0], r[3]) for r in out["rows"]], [("05:59", True), ("06:00", False), ("17:59", False), ("18:00", True)])
        self.assertEqual(out["symbols"], [["2600", "fe0e"], ["263e", "fe0e"]], "Textzeichen, kein buntes Emoji")
        self.assertEqual([(r["label"], r["time"], r["delta"], r["day"], r["night"]) for r in out["view"]],
                         [("LON", "09:15", f"{M}1 h", 0, False), ("Tokyo", "17:15", "+7 h", 0, False)])
        self.assertEqual(out["none"], [[], []])

    def test_abweichung_als_text(self):
        out = run_world("""
          console.log(JSON.stringify([0, 3600000, -3600000, 19800000, 20700000, -12600000, 50400000, 29999, -30000, NaN, 1800000]
            .map((ms) => w.fmtDelta(ms))));
        """)
        self.assertEqual(out, ["±0 h", "+1 h", f"{M}1 h", "+5:30 h", "+5:45 h", f"{M}3:30 h", "+14 h", "±0 h", "±0 h", "",
                               "+0:30 h"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ParameterTest(unittest.TestCase):
    def test_zonen_kommagetrennt_und_mehrfach(self):
        out = run_world("""
          const z = k.supportedZones();
          const p = (q) => { const r = k.parseParams(q, z); return [r.tz, r.tzl, r.ignored]; };
          console.log(JSON.stringify({
            one: p("?tz=Europe/London"),
            comma: p("?tz=Europe/London,America/New_York,Asia/Tokyo&tzl=LON,NYC,TYO"),
            repeat: p("?tz=Europe/London&tz=America/New_York&tz=Asia/Tokyo&tzl=LON&tzl=NYC"),
            mixed: p("?tz=Europe/London,Asia/Tokyo&tz=UTC"),
            encoded: p("?tz=Europe%2FLondon%2CAsia%2FTokyo&tzl=Lon%20don,T%C5%8Dky%C5%8D"),
            six: p("?tz=UTC,Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney"),
            seven: p("?tz=UTC,Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney,Europe/Paris"),
            sevenRepeat: p("?" + ["UTC", "Europe/London", "America/New_York", "Asia/Tokyo", "Asia/Kolkata", "Australia/Sydney",
              "Europe/Paris"].map((n) => "tz=" + n).join("&")),
            double: p("?tz=Europe/London,europe/london"),
            oneBad: p("?tz=Europe/London,Mars/Olympus"),
            emptyItem: [p("?tz=Europe/London,"), p("?tz=,Europe/London"), p("?tz=")],
            gaps: p("?tz=UTC,Asia/Tokyo,Europe/Paris&tzl=,TYO"),
            frozen: Object.isFrozen(k.parseParams("?tz=UTC&tzl=Z", z).tz) && Object.isFrozen(k.parseParams("?tz=UTC&tzl=Z", z).tzl),
            limits: [k.MAX_ZONES, k.ZONE_LABEL_LEN],
          }));
        """)
        self.assertEqual(out["one"], [["Europe/London"], None, []], "eine Zone wie bisher")
        self.assertEqual(out["comma"], [["Europe/London", "America/New_York", "Asia/Tokyo"], ["LON", "NYC", "TYO"], []])
        self.assertEqual(out["repeat"], [["Europe/London", "America/New_York", "Asia/Tokyo"], ["LON", "NYC"], []])
        self.assertEqual(out["mixed"][0], ["Europe/London", "Asia/Tokyo", "UTC"])
        self.assertEqual(out["encoded"], [["Europe/London", "Asia/Tokyo"], ["Lon don", "Tōkyō"], []])
        self.assertEqual(len(out["six"][0]), 6)
        self.assertEqual(out["seven"], [None, None, ["tz"]], "mehr als sechs Zonen: der ganze Wert gilt nicht")
        self.assertEqual(out["sevenRepeat"], [None, None, ["tz"]])
        self.assertEqual(out["double"], [None, None, ["tz"]])
        self.assertEqual(out["oneBad"], [None, None, ["tz"]], "sonst passten die Kurznamen nicht mehr zu ihren Zonen")
        self.assertEqual(out["emptyItem"], [[None, None, ["tz"]]] * 3)
        self.assertEqual(out["gaps"][1], ["", "TYO"])
        self.assertTrue(out["frozen"])
        self.assertEqual(out["limits"], [6, 16])

    def test_kurznamen_mit_sonderzeichen_werden_verworfen(self):
        bad = ["<b>", "a<b", "NYC;x", "a&b", 'a"b', "a'b", "a/b", "a_b", "a:b", "a(b)", "x" * 17, "\u00a0NYC", "NYC\t", "a\tb", "a‮b",
               "a\u0000b", "a​b", "javascript:alert(1)", "{{x}}", "a=b", "100%", "a+b", "a\\b", "a\nb", "🙂",
               "A,B,C,D,E,F,G", ",,", ""]
        good = ["NYC", "New York", "St. Louis", "Port-au-Prince", "Zürich", "東京", "Studio 2", "x" * 16, "A,,C", ",B"]
        out = run_world(f"""
          const z = k.supportedZones();
          const p = (v) => k.parseParams("?" + new URLSearchParams([["tz", "UTC"], ["tzl", v]]).toString(), z);
          console.log(JSON.stringify({{ bad: {json.dumps(bad)}.map((v) => [p(v).tzl, p(v).ignored]),
            good: {json.dumps(good)}.map((v) => p(v).tzl) }}));
        """)
        for value, got in zip(bad, out["bad"]):
            self.assertEqual(got, [None, ["tzl"]], repr(value))
        self.assertEqual(out["good"], [v.split(",") for v in good])
        # Der Server prüft gleich streng (Profile).
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.check_value("tzl", value)
        for value in good:
            self.assertEqual(clockprofiles.check_value("tzl", value), value)

    def test_server_allowlist_gleich_streng(self):
        ok = ["UTC", "Europe/London", "Europe/London,America/New_York,Asia/Tokyo",
              "UTC,Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney"]
        bad = ["Europe/London,", ",Europe/London", "Europe/London,Mars/Olympus", "Europe/London,Europe/London",
               "Europe/London,europe/london", "UTC,Europe/London,America/New_York,Asia/Tokyo,Asia/Kolkata,Australia/Sydney,Europe/Paris",
               "Europe/London\n", "Europe/London,Asia/Tokyo\n", "Europe/London,\tAsia/Tokyo", "Europe/London ,, Asia/Tokyo", "../../etc/passwd", "A" * 65, ""]
        for value in ok:
            self.assertEqual(clockprofiles.check_value("tz", value), value)
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(clockprofiles.ProfileError):
                    clockprofiles.check_value("tz", value)
        with self.assertRaises(clockprofiles.ProfileError):
            clockprofiles.check_value("tzl", "NYC\n")
        self.assertEqual(clockprofiles.PARAMS["tz"], ("zonelist", {"max_items": 6}))
        self.assertEqual(clockprofiles.PARAMS["tzl"], ("labellist", {"len": 16, "max_items": 6}))
        self.assertIn("world", clockprofiles.PARAMS["layout"][1]["values"])
        clean = clockprofiles.clean_profiles({"welt": {"params": {"layout": "world", "tz": "Europe/London,Asia/Tokyo",
                                                                     "tzl": "LON,TYO"}}})
        self.assertEqual(clean["welt"]["params"], {"tz": "Europe/London,Asia/Tokyo", "tzl": "LON,TYO", "layout": "world"})
        public = clockprofiles.public_profile("welt", clean)
        self.assertEqual(public["params"]["tzl"], "LON,TYO")
        # Uhr und Server urteilen über dieselben Werte gleich.
        out = run_world(f"""
          const z = k.supportedZones();
          const e = k.PARAM_SCHEMA.find((x) => x.name === "tz");
          console.log(JSON.stringify({{ ok: {json.dumps(ok)}.map((v) => k.checkParam(e, v, z).ok),
            bad: {json.dumps(bad)}.map((v) => k.checkParam(e, v, z).ok) }}));
        """)
        self.assertEqual(out["ok"], [True] * len(ok))
        self.assertEqual(out["bad"], [False] * len(bad))

    def test_link_baukasten(self):
        out = run_world("""
          const z = k.supportedZones();
          console.log(JSON.stringify({
            query: l.buildQuery({ tz: "Europe/London,Asia/Tokyo", tzl: "LON,TYO", layout: "world" }, z),
            bad: l.buildQuery({ tz: "Europe/London,Mars/Olympus", tzl: "<b>" }, z),
            raw: l.rawParams("?tz=Europe/London&tz=Asia/Tokyo&tzl=LON&tzl=TYO&layout=world", z),
            round: k.parseParams("?" + l.buildQuery({ tz: "Europe/London,Asia/Tokyo", tzl: "LON,TYO" }, z), z).tz,
            layered: l.effectiveQuery({ search: "?tzl=A,B", profile: { tz: "Europe/London,Asia/Tokyo", tzl: "LON,TYO" }, zones: z }),
            group: l.FORM_GROUPS.find((g) => g.names.includes("tz")).names,
            valid: [l.rawValid("tz", "UTC,Asia/Tokyo", z), l.rawValid("tz", "UTC,UTC", z), l.rawValid("tzl", "A,B", z),
              l.rawValid("tzl", "A;B", z)],
            limit: [k.rawLimit(k.PARAM_SCHEMA.find((e) => e.name === "tz")), k.rawLimit(k.PARAM_SCHEMA.find((e) => e.name === "tzl")),
              k.rawLimit(k.PARAM_SCHEMA.find((e) => e.name === "label"))],
          }));
        """)
        self.assertIn("layout=world", out["query"])
        self.assertEqual(out["bad"], "")
        self.assertEqual(out["raw"], {"tz": "Europe/London,Asia/Tokyo", "tzl": "LON,TYO", "layout": "world"})
        self.assertEqual(out["round"], ["Europe/London", "Asia/Tokyo"])
        params = dict(pair.split("=") for pair in out["layered"].split("&"))
        self.assertEqual(set(params), {"tz", "tzl"})
        self.assertIn("A", params["tzl"], "Adresse schlägt Profil")
        self.assertEqual(out["group"][:2], ["tz", "tzl"])
        self.assertEqual(out["valid"], [True, False, True, False])
        self.assertEqual(out["limit"], [6 * 64 + 5, 6 * 16 + 5, 64])

    def test_zonen_der_adresse_ohne_kurznamen_des_profils(self):
        # tz und tzl gehören zusammen (gleiche Reihenfolge): Ersetzt die Adresse die Zonen, ohne Kurznamen zu nennen,
        # gelten die Kurznamen des Profils nicht weiter – sonst stünde New York unter „LON“.
        out = run_world("""
          const z = k.supportedZones();
          const profile = { tz: "Europe/London,Asia/Tokyo", tzl: "LON,TYO", design: "studio" };
          const eff = (search) => l.effectiveQuery({ search, profile, zones: z });
          const entries = (search) => { const p = k.parseParams("?" + eff(search), z);
            return w.worldEntries(p.tz, p.tzl).map((e) => [e.zone, e.label]); };
          console.log(JSON.stringify({
            other: eff("?p=regie&tz=America/New_York"), otherEntries: entries("?p=regie&tz=America/New_York"),
            both: eff("?p=regie&tz=America/New_York&tzl=NYC"),
            same: eff("?p=regie&tz=Europe/London,Asia/Tokyo"), sameEntries: entries("?p=regie&tz=Europe/London,Asia/Tokyo"),
            labels: eff("?p=regie&tzl=A,B"), none: eff("?p=regie&scale=120"),
            layers: [l.layerQuery({ tz: "UTC", tzl: "A" }, { tz: "Asia/Tokyo" }), l.layerQuery({ tzl: "A" }, { tz: "Asia/Tokyo" }),
              l.layerQuery({ tz: "UTC", tzl: "A" }, { tz: "Asia/Tokyo" }, { tzl: "B" }), l.layerQuery({ tz: "UTC", tzl: "A" }, { design: "flip" })],
          }));
        """)
        self.assertEqual(out["other"], "design=studio&tz=America%2FNew_York")
        self.assertEqual(out["otherEntries"], [["America/New_York", "New York"]])
        self.assertEqual(out["both"], "design=studio&tz=America%2FNew_York&tzl=NYC")
        self.assertIn("tzl=LON%2CTYO", out["same"], "dieselben Zonen noch einmal: Die Kurznamen passen weiter")
        self.assertEqual(out["sameEntries"], [["Europe/London", "LON"], ["Asia/Tokyo", "TYO"]])
        self.assertIn("tz=Europe%2FLondon%2CAsia%2FTokyo", out["labels"])
        self.assertIn("tzl=A%2CB", out["labels"])
        self.assertIn("tzl=LON%2CTYO", out["none"])
        self.assertEqual(out["layers"], ["tz=Asia%2FTokyo", "tz=Asia%2FTokyo", "tz=Asia%2FTokyo&tzl=B", "design=flip&tz=UTC&tzl=A"])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class DarstellungTest(unittest.TestCase):
    def test_beschriftung_und_modus(self):
        out = run_world("""
          console.log(JSON.stringify({
            entries: w.worldEntries(["America/New_York", "Asia/Tokyo", "UTC"], ["NYC", ""]),
            none: [w.worldEntries(null, null), w.worldEntries([], ["A"]), w.worldEntries(["", 5, null], [])],
            fallback: w.worldEntries(null, null, { fallback: true }),
            capped: w.worldEntries(Array.from({ length: 9 }, (_, i) => "Etc/GMT+" + i), []).length,
            mode: [w.worldMode(0, "normal"), w.worldMode(1, "normal"), w.worldMode(2, "normal"), w.worldMode(6, "banner"),
              w.worldMode(0, "world"), w.worldMode(1, "world"), w.worldMode(3, "world"), w.worldMode(undefined, "strip")],
          }));
        """)
        self.assertEqual(out["entries"], [{"zone": "America/New_York", "label": "NYC"}, {"zone": "Asia/Tokyo", "label": "Tokyo"},
                                          {"zone": "UTC", "label": "UTC"}])
        self.assertEqual(out["none"], [[], [], []])
        self.assertEqual(out["fallback"], [{"zone": "UTC", "label": "UTC"}])
        self.assertEqual(out["capped"], 6)
        self.assertEqual(out["mode"], ["none", "single", "bar", "bar", "grid", "grid", "grid", "none"])

    def test_raster_und_zeilen_je_flaeche(self):
        out = run_world("""
          const g = (n, w_, h) => { const r = w.worldGrid(n, w_, h); return [r.cols, r.rows, r.flow]; };
          console.log(JSON.stringify({
            wide: [1, 2, 3, 4, 5, 6].map((n) => g(n, 1920, 1080)),
            stele: [g(6, 1080, 1920), g(3, 390, 844)],
            banner: [g(6, 3840, 1080), g(4, 1920, 200), g(6, 1920, 640), g(6, 1919, 640)],
            tall: [g(6, 390, 560), g(3, 390, 560), g(1, 390, 560), g(5, 600, 601)],
            narrow: [w.worldLines("normal", 560, 6, 390), w.worldLines("normal", 560, 6, 720), w.worldLines("normal", 300, 6, 390)],
            odd: [g(0, 1920, 1080), g(9, 1920, 1080), g(6, 0, 0), g(6, 480, 270), g(6, 1000, 1600), g(6, 1001, 1600)],
            lines: [["strip", 60, 6], ["tile", 135, 6], ["normal", 945, 6], ["normal", 419, 6], ["normal", 420, 1], ["banner", 126, 6],
              ["banner", 945, 6], ["banner", 945, 2], ["column", 663, 6], ["column", 663, 2], ["normal", 945, 0], ["world", 945, 6]]
              .map(([layout, h, n]) => w.worldLines(layout, h, n)),
          }));
        """)
        self.assertEqual(out["wide"], [[1, 1, "grid"], [2, 1, "grid"], [3, 1, "grid"], [2, 2, "grid"], [3, 2, "grid"], [3, 2, "grid"]])
        self.assertEqual(out["stele"], [[1, 6, "list"], [1, 3, "list"]])
        self.assertEqual(out["banner"], [[6, 1, "row"], [4, 1, "row"], [6, 1, "row"], [3, 2, "grid"]])
        self.assertEqual(out["odd"], [[1, 1, "grid"], [3, 2, "grid"], [3, 2, "grid"], [3, 2, "grid"], [1, 6, "list"], [2, 3, "grid"]])
        self.assertEqual(out["tall"], [[2, 3, "grid"], [2, 2, "grid"], [1, 1, "grid"], [2, 3, "grid"]])
        self.assertEqual(out["narrow"], [3, 2, 1])
        self.assertEqual(out["lines"], [0, 0, 2, 1, 1, 2, 3, 2, 6, 2, 0, 2])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class ListenSchreibweiseTest(unittest.TestCase):
    """tz und tzl: Leerzeichen um die Kommas zählen nicht, die Länge zählt in Zeichen – in der Uhr und im Server gleich."""

    def both(self, name, values):
        out = run_world(f"""
          const z = k.supportedZones();
          const e = k.PARAM_SCHEMA.find((x) => x.name === {json.dumps(name)});
          console.log(JSON.stringify({json.dumps(values)}.map((v) => {{ const r = k.checkParam(e, v, z);
            return r.ok ? k.listRaw(e, v) : null; }})));
        """)
        server_side = []
        for value in values:
            try:
                server_side.append(clockprofiles.check_value(name, value))
            except clockprofiles.ProfileError:
                server_side.append(None)
        self.assertEqual(out, server_side, "Uhr und Server urteilen gleich und liefern dieselbe Schreibweise")
        return out

    def test_leerzeichen_nach_dem_komma(self):
        got = self.both("tz", ["Europe/London, Asia/Tokyo", " Europe/London ,Asia/Tokyo ", "Europe/London,  Asia/Tokyo",
                               "Europe/London, ", "Europe/London,\tAsia/Tokyo", "Europe /London", "Europe/London, Europe/London"])
        self.assertEqual(got, ["Europe/London,Asia/Tokyo"] * 3 + [None] * 4)
        got = self.both("tzl", ["LON, TYO", " LON , New York ", "LON, ,SYD", " , ", "LON, TYO"])
        self.assertEqual(got, ["LON,TYO", "LON,New York", "LON,,SYD", None, None])
        out = run_world("""
          const z = k.supportedZones();
          const p = k.parseParams("?tz=Europe/London,%20Asia/Tokyo&tzl=LON,%20TYO", z);
          console.log(JSON.stringify({ tz: p.tz, tzl: p.tzl, ignored: p.ignored,
            query: l.buildQuery({ tz: "Europe/London, Asia/Tokyo", tzl: " LON , TYO" }, z),
            raw: l.rawParams("?tz=Europe/London,+Asia/Tokyo&tzl=LON,+TYO", z),
            valid: [l.rawValid("tz", "Europe/London, Asia/Tokyo", z), l.rawValid("tz", "Europe/London, Mars/Olympus", z)],
            other: k.listRaw(k.PARAM_SCHEMA.find((x) => x.name === "label"), " a , b "),
          }));
        """)
        self.assertEqual(out["tz"], ["Europe/London", "Asia/Tokyo"])
        self.assertEqual(out["tzl"], ["LON", "TYO"])
        self.assertEqual(out["ignored"], [])
        self.assertEqual(out["query"], "tz=Europe%2FLondon,Asia%2FTokyo&tzl=LON,TYO", "der Link nennt die Liste ohne Leerzeichen")
        self.assertEqual(out["raw"], {"tz": "Europe/London,Asia/Tokyo", "tzl": "LON,TYO"})
        self.assertEqual(out["valid"], [True, False])
        self.assertEqual(out["other"], " a , b ", "nur Listen werden bereinigt")
        clean = clockprofiles.clean_profiles({"welt": {"params": {"tz": "Europe/London, Asia/Tokyo", "tzl": "LON, TYO"}}})
        self.assertEqual(clean["welt"]["params"], {"tz": "Europe/London,Asia/Tokyo", "tzl": "LON,TYO"})

    def test_laenge_zaehlt_in_zeichen(self):
        astral = "\U0001d400"            # ein Buchstabe außerhalb der BMP: zwei UTF-16-Einheiten, ein Zeichen
        split = "é"               # e + Akzent: nach NFC ein Zeichen
        six = ",".join([astral * 16] * 6)
        got = self.both("tzl", [six, ",".join([astral * 16] * 4), ",".join([astral * 17] * 2), ",".join([split * 16] * 6),
                                ",".join([split * 17]), six + "," + astral, "A" + " " * 400, "A," + " " * 404, "x" * 102])
        nfc = ",".join(["é" * 16] * 6)
        self.assertEqual(got, [six, ",".join([astral * 16] * 4), None, nfc, None, None, "A", None, None])
        out = run_world(f"""
          const z = k.supportedZones();
          const p = k.parseParams("?tz=Europe/London&tzl=" + encodeURIComponent({json.dumps(",".join([astral * 16] * 4))}), z);
          console.log(JSON.stringify({{ n: p.tzl.length, len: [...p.tzl[0]].length, ignored: p.ignored, slack: k.LIST_SLACK }}));
        """)
        self.assertEqual(out, {"n": 4, "len": 16, "ignored": [], "slack": clockprofiles.LIST_SLACK})


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class EinpassenTest(unittest.TestCase):
    """Reine Regeln, nach denen clock.js Leiste und Raster einpasst."""

    def test_show_ohne_tz_laesst_keine_weltzeit_zu(self):
        out = run_world("""
          console.log(JSON.stringify({
            allowed: [w.worldAllowed(null), w.worldAllowed(undefined), w.worldAllowed(["time", "tz"]), w.worldAllowed(["time", "date"]),
              w.worldAllowed([])],
            mode: [w.worldMode(6, "world", false), w.worldMode(6, "normal", false), w.worldMode(1, "normal", false),
              w.worldMode(6, "world", true), w.worldMode(6, "banner")],
          }));
        """)
        self.assertEqual(out["allowed"], [True, True, True, False, False])
        self.assertEqual(out["mode"], ["none", "none", "none", "grid", "bar"])

    def test_hinweis_auf_fehlende_zonen_ist_keine_eigene_zeile(self):
        out = run_world("""
          const b = (top, h) => ({ top, bottom: top + h });
          console.log(JSON.stringify([
            w.lineCount([b(708, 50), b(708, 50), b(770, 50), b(770, 50), b(781, 34)]),   // „+2“ 11 px tiefer in Zeile zwei
            w.lineCount([b(197, 23), b(197, 23), b(197, 23), b(224, 18)]),               // „+3“ allein in Zeile zwei
            w.lineCount([b(300, 23), b(300, 23), b(304, 17)]),
            w.lineCount([b(10, 20), b(30, 20), b(50, 20)]),
            w.lineCount([b(50, 20), b(10, 20)]), w.lineCount([]), w.lineCount(null), w.lineCount([{ top: NaN, bottom: 1 }]),
          ]));
        """)
        self.assertEqual(out, [2, 2, 1, 3, 2, 0, 0, 0])

    def test_raster_erst_einspaltig_dann_weniger_zonen(self):
        out = run_world("""
          const s = (n, w_, h) => w.worldSteps(n, w_, h).map((x) => `${x.shown}${x.dense ? "d" : "n"}${x.list ? "L" : ""}`).join(" ");
          const g = (n, w_, h, o) => { const r = w.worldGrid(n, w_, h, o); return [r.cols, r.rows, r.flow]; };
          console.log(JSON.stringify({
            wide: s(6, 1920, 1080), tall: s(6, 360, 459), stele: s(3, 390, 844), square: s(2, 600, 600), banner: s(2, 1920, 200),
            list: [g(6, 360, 459, { list: true }), g(6, 360, 459), g(4, 360, 459, { list: true }), g(6, 1920, 1080, { list: false })],
          }));
        """)
        self.assertEqual(out["wide"], "6n 6d 5d 4d 3d 2d 1d")
        # Höher als breit, aber kein Hochformat: jede Stufe auch als eine Spalte, alle sechs vor dem Weglassen.
        self.assertEqual(out["tall"], "6n 6nL 6d 6dL 5d 5dL 4d 4dL 3d 3dL 2d 2dL 1d 1dL")
        self.assertEqual(out["stele"], "3n 3d 2d 1d", "im Hochformat ist das Raster schon einspaltig")
        self.assertEqual(out["square"], "2n 2d 1d")
        self.assertEqual(out["banner"], "2n 2d 1d")
        self.assertEqual(out["list"], [[1, 6, "list"], [2, 3, "grid"], [1, 4, "list"], [3, 2, "grid"]])

    def test_zonen_mit_h12_wie_die_grosse_zeit(self):
        out = run_world("""
          const at = Date.parse("2026-01-15T12:00:30Z");
          const r = (zone, h12) => { const x = w.worldRow(at, { zone, label: "" }, 0, undefined, { h12 }); return [x.time, x.ampm, x.hour, x.night]; };
          console.log(JSON.stringify({
            h12: ["Europe/London", "Asia/Tokyo", "Pacific/Kiritimati", "Etc/GMT+12", "Asia/Kolkata"].map((z) => r(z, true)),
            h24: ["Europe/London", "Asia/Tokyo", "Etc/GMT+12"].map((z) => r(z, false)),
            view: w.worldView(at, [{ zone: "Asia/Tokyo", label: "TYO" }], 0, undefined, { h12: true }).map((x) => `${x.label} ${x.time} ${x.ampm} ${x.delta}`),
            plain: w.worldView(at, [{ zone: "Asia/Tokyo", label: "TYO" }]).map((x) => `${x.time}|${x.ampm}`),
          }));
        """)
        self.assertEqual(out["h12"], [["12:00", "PM", 12, False], ["09:00", "PM", 21, True], ["02:00", "AM", 2, True],
                                      ["12:00", "AM", 0, True], ["05:30", "PM", 17, False]])
        self.assertEqual(out["h24"], [["12:00", "", 12, False], ["21:00", "", 21, True], ["00:00", "", 0, True]])
        self.assertEqual(out["view"], ["TYO 09:00 PM +9 h"])
        self.assertEqual(out["plain"], ["21:00|"])

    def test_leiste_darf_freie_hoehe_nutzen(self):
        out = run_world("""
          console.log(JSON.stringify([w.barGrowSteps(146, 17.6), w.barGrowSteps(600, 20), w.barGrowSteps(91, 16.5), w.barGrowSteps(60, 13),
            w.barGrowSteps(0, 13), w.barGrowSteps(100, 0), w.barGrowSteps(NaN, 13), w.BAR_GROW_MAX, w.BAR_GROW_SHARE]));
        """)
        self.assertEqual(out[0], [1.659, 1.439, 1.22], "bis ein Fünftel der Zeithöhe, größte Stufe zuerst")
        self.assertEqual(out[1], [1.8, 1.533, 1.267], "nie mehr als das 1,8-Fache")
        self.assertEqual(out[2], [1.103, 1.069, 1.034])
        self.assertEqual(out[3:7], [[], [], [], []], "schon groß genug oder nichts zu messen: bleibt, wie sie ist")
        self.assertEqual(out[7:], [1.8, 0.2])

    def test_vorschlagsliste_fuer_jede_zone_der_liste(self):
        out = run_world("""
          const z = ["Asia/Tokyo", "Europe/London", "UTC"];
          const six = "UTC,Europe/London,Asia/Tokyo,Asia/Kolkata,Australia/Sydney,Europe/Paris,";
          console.log(JSON.stringify([l.zoneSuggestions("", z), l.zoneSuggestions("Euro", z), l.zoneSuggestions("Europe/London,", z),
            l.zoneSuggestions("europe/london, As", z), l.zoneSuggestions(six, z), l.zoneSuggestions(null, z), l.zoneSuggestions("UTC,", [])]));
        """)
        self.assertEqual(out[0], ["Asia/Tokyo", "Europe/London", "UTC"])
        self.assertEqual(out[1], ["Asia/Tokyo", "Europe/London", "UTC"], "vor dem ersten Komma filtert der Browser")
        self.assertEqual(out[2], ["Europe/London,Asia/Tokyo", "Europe/London,UTC"], "schon genannte Zonen fehlen")
        self.assertEqual(out[3], ["europe/london, Asia/Tokyo", "europe/london, UTC"], "wie getippt, auch mit Leerzeichen")
        self.assertEqual(out[4:], [[], ["Asia/Tokyo", "Europe/London", "UTC"], []])
        form = (JS / "clocklink.js").read_text(encoding="utf-8")
        self.assertIn('(name === "tz" && zones.length ? `${prefix}-zones` : null)', form)
        self.assertIn('node("datalist", { id: `${prefix}-zones` })', form)


class TexteUndSeiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (JS / "clock.js").read_text(encoding="utf-8")
        cls.world = (JS / "clockworld.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "clock.css").read_text(encoding="utf-8")
        cls.html = (STATIC / "clock.html").read_text(encoding="utf-8")

    def test_texte_in_beiden_sprachen(self):
        keys = ["world_label", "world_day", "world_days", "world_daytime", "world_night", "world_delta_title", "world_more_one", "world_more_other"]
        for lang in ("de", "en"):
            clock = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["clock"]
            for key in keys:
                self.assertTrue(clock.get(key), f"{lang}: clock.{key}")
            self.assertTrue(clock["layout_name"]["world"])
            self.assertTrue(clock["link"]["f"]["tzl"])
            self.assertIn("{count}", clock["world_more_one"])
            self.assertIn("{count}", clock["world_more_other"])
            self.assertNotIn("world_more", clock, "Einzahl und Mehrzahl getrennt")
            self.assertIn("{ref}", clock["world_delta_title"])
        core = (JS / "i18n.js").read_text(encoding="utf-8")
        for key in keys + ['"world": "Weltzeit"']:
            self.assertIn(key, core, "auch im eingebauten Kern (vor dem Laden des Katalogs)")

    def test_doku_nennt_die_parameter(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_text = (JS / "help-uhr.js").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "integrationen" / "studiouhr.md").read_text(encoding="utf-8")
        for name, text in (("README", readme), ("help-uhr.js", help_text), ("studiouhr.md", guide)):
            for word in ("tzl=", "layout=world", "+1 Tag", "16 Zeichen", "sechs Zeitzonen", "Standort", "h12=1", "Bildwände"):
                self.assertIn(word, text, f"{name}: {word}")

    def test_kurzname_nur_als_text_und_symbol_mit_alternative(self):
        start = self.js.index("function buildWorld(mode, entries)")
        build = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn("label.textContent = entry.label;", build)
        self.assertIn('sun.setAttribute("role", "img");', build)
        self.assertNotRegex(self.js + self.world, r"innerHTML|insertAdjacentHTML|outerHTML")
        start = self.js.index("function renderWorld(ms)")
        render = self.js[start:self.js.index("\n}\n", start)]
        self.assertIn('setAttr(item.sun, "aria-label", phase);', render)
        self.assertIn("world.dayShiftText(row.day, words)", render, "Tageswechsel als Text, nicht nur als Farbe")
        self.assertIn('id="world" role="list"', self.html)
        # Reine Rechnung: kein DOM, keine Zeitgeber, kein Standort, kein Netz.
        self.assertNotRegex(self.world, r"document\.|window\.|setTimeout|setInterval|requestAnimationFrame|fetch\(|geolocation|"
                                        r"\blat\b|\blon\b|localStorage")

    def test_einpassen_in_clock_js(self):
        js = self.js
        # ?show= ohne tz: keine Weltzeit, im Layout world gilt die Automatik.
        self.assertIn('world.worldMode(params.tz ? params.tz.length : 0, state.picked, world.worldAllowed(params.show))', js)
        self.assertIn('const want = params.layout === "world" && !world.worldAllowed(params.show) ? "auto" : params.layout;', js)
        # Raster ohne eine einzige Zone: Uhr im automatischen Layout statt klein auf leerer Fläche.
        start = js.index("function fitTime()")
        fit = js[start:js.index("\n}\n", start)]
        self.assertIn('stageLayout(kit.resolveLayout(state.stage.width, state.stage.height));', fit)
        self.assertLess(fit.index('stageLayout("world");'), fit.index("fitGrid(main);"))
        # Jede Zelle einzeln gegen die Bühne, Zeilen über world.lineCount, Mehrzahl aus dem Katalog.
        start = js.index("function worldInside()")
        self.assertIn("...worldBoxes()", js[start:js.index("\n}\n", start)])
        self.assertIn("return world.lineCount(worldBoxes());", js)
        self.assertNotIn("offsetTop", js)
        self.assertIn('t("clock.world_more", { count: rest })', js)
        start = js.index("function fitGrid(main)")
        grid = js[start:js.index("\n}\n", start)]
        self.assertIn("world.worldSteps(total, state.stage.width, state.stage.height)", grid)
        self.assertIn('setAttr(stage, "data-world-flow", grid.flow);', grid)
        # Leiste wächst nur über die Variable --world-grow (CSSOM), AM/PM leer ohne ?h12=1.
        self.assertIn("calc(max(13px, var(--info) * 0.82) * var(--world-grow, 1))", self.css)
        self.assertIn(".wz-ampm:empty { display: none; }", self.css)
        self.assertIn("{ h12: params.h12 }", js)

    def test_seite_und_stil(self):
        self.assertIn("/static/js/clockworld.js", server.CLOCK_PUBLIC_PATHS)
        self.assertIn('import * as world from "./clockworld.js";', self.js)
        block = self.css[self.css.index("/* --- Studiouhr B2: Weltzeit"):]
        self.assertNotRegex(block, r"animation|transition|@keyframes|filter:|url\(")
        self.assertIn(".clock-world[hidden], .clock-world [hidden] { display: none; }", block)
        self.assertIn('.clock-stage:is([data-layout="strip"], [data-layout="tile"]) .clock-world { display: none; }', block)
        self.assertIn(':root[data-show]:not([data-show~="tz"]) .clock-world { display: none; }', block)
        self.assertIn(".wz-day:empty { display: none; }", block)
        # Kleinste Schrift 12 px: in der Leiste per CSS, im Raster über die Auto-Anpassung.
        for selector in (".wz-label", ".wz-meta", ".wz-more"):
            rule = block[block.index(f"\n{selector} {{"):]
            self.assertRegex(rule[:rule.index("}")], r"font-size: max\([0-9.]+em, 12px\)", selector)
        self.assertIn("const WORLD_MIN_PX = 12;", self.js)
        start = self.js.index("function fitGrid(main)")
        self.assertIn("worldSmallest() >= WORLD_MIN_PX", self.js[start:self.js.index("\n}\n", start)])
        # Streifen und Kachel: keine Leiste.
        self.assertIn('if (!n || layout === "strip" || layout === "tile") return 0;', self.world)


if __name__ == "__main__":
    unittest.main()
