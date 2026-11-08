"""T2 GUI-Erneuerung, Teil „Seiten entschlacken“ (docs/konzept/version-1.6.md, T2 Punkt 5).

  * Quellenfarben fest je Quelle: Hash des Namens → Platz in der Palette, unabhängig von der
    Reihenfolge; GPS/PPS immer in derselben Signalfarbe; jede Farbe mit mindestens 3:1 Kontrast
    zum Diagrammhintergrund in beiden Themen.
  * Linien-Endbeschriftungen nur mit Kurznamen (Hostname ohne Domain, IP unverändert).
  * Clients: Spalten ohne einen einzigen Messwert fallen weg; auf dem Handy Karten statt Tabelle;
    Name direkt in der Liste (✎), schreibgeschützt ohne ✎.
  * Zeitquellen: „Grund“ nur, wenn er etwas anderes sagt als „Zustand“.
  * Eine Erklärzeile: splitExplain teilt lange Texte, ohne etwas zu verlieren.
  * F16: Der Phasentext der automatischen Kalibrierung steht nur einmal da.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_frontend_states import DOM  # noqa: E402 – dieselbe DOM-Attrappe


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


def luminance(color: str) -> float:
    value = color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NodeTest(unittest.TestCase):
    def run_js(self, body: str, mobile: bool = False):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            prelude = 'import { text, withAttr, ctx } from "./dom.mjs";\n'
            prelude += "globalThis.getComputedStyle = () => ({ getPropertyValue: () => \"\" });\n"
            if mobile:
                prelude += "window.matchMedia = (q) => ({ matches: /max-width: 640px/.test(q) });\n"
            script.write_text(prelude + body, encoding="utf-8")
            env = {**os.environ, "TZ": "UTC"}
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])


class FarbenTest(NodeTest):
    def colors(self):
        return self.run_js(f"""
const ch = await import({mod("charts.js")});
const names = ["192.0.2.1", "198.51.100.7", "203.0.113.9", "uhr1.example.net", "time.example.org", "2001:db8::5"];
const out = {{ palette: ch.SERIES_PALETTE, signal: ch.SIGNAL_COLOR, bg: ch.CHART_BACKGROUND }};
const pick = (list, theme) => {{ const slots = ch.assignSlots(list);
  return Object.fromEntries(list.map((n) => [n, ch.colorFor(n, slots, theme).color])); }};
out.a = pick(names, "light");
out.b = pick([...names].reverse(), "light");
out.again = pick(names, "light");
out.alone = Object.fromEntries(names.map((n) => [n, ch.colorFor(n, null, "dark").color]));
out.gps = ["GPS", "gps", "PPS", "NMEA", "SHM0", "PHC0"].map((n) => [n, ch.colorFor(n, null, "light"), ch.colorFor(n, null, "dark")]);
out.distinct = new Set(names.map((n) => {{ const c = ch.colorFor(n, ch.assignSlots(names), "light"); return `${{c.color}}|${{c.dash}}`; }})).size;
out.hash = [ch.hashName("192.0.2.1"), ch.hashName("192.0.2.1"), ch.hashName("192.0.2.2")];
console.log(JSON.stringify(out));
""")

    def test_stabil_und_unabhaengig_von_der_reihenfolge(self):
        out = self.colors()
        self.assertEqual(out["a"], out["b"])
        self.assertEqual(out["a"], out["again"])
        self.assertEqual(out["hash"][0], out["hash"][1])
        self.assertNotEqual(out["hash"][0], out["hash"][2])
        # Innerhalb eines Diagramms unterscheidbar: Farbe und Strichelung zusammen sind eindeutig.
        self.assertEqual(out["distinct"], 6)
        # Ohne Menge (einzelne Quelle): trotzdem immer dieselbe Farbe aus der Palette.
        for color in out["alone"].values():
            self.assertIn(color, out["palette"]["dark"])

    def test_farbe_haengt_nicht_an_den_nachbarn(self):
        # ptbtime3.ptb.de und time.google.com landen per Hash auf demselben Platz. Die Farbe einer Quelle
        # darf trotzdem nicht davon abhängen, welche anderen Quellen im selben Diagramm stehen.
        out = self.run_js(f"""
const ch = await import({mod("charts.js")});
const pick = (name, list) => ch.colorFor(name, ch.assignSlots(list), "light");
const a = "ptbtime3.ptb.de", b = "time.google.com";
console.log(JSON.stringify({{ same: ch.hashName(a) % 8 === ch.hashName(b) % 8,
  alone: [pick(a, [a]), pick(b, [b])], both: [pick(a, [a, b]), pick(b, [a, b])],
  hash: [ch.colorFor(a, null, "light"), ch.colorFor(b, null, "light")],
  more: ["192.0.2.1", "192.0.2.2", "192.0.2.3", "uhr1.example.net"].map((n) =>
    ch.colorFor(n, ch.assignSlots(["192.0.2.1", "192.0.2.2", "192.0.2.3", "uhr1.example.net", a, b]), "dark").color),
  moreAlone: ["192.0.2.1", "192.0.2.2", "192.0.2.3", "uhr1.example.net"].map((n) => ch.colorFor(n, null, "dark").color) }}));
""")
        self.assertTrue(out["same"], "Testvoraussetzung: beide Namen auf demselben Platz")
        for i in range(2):
            self.assertEqual(out["alone"][i]["color"], out["both"][i]["color"])
            self.assertEqual(out["alone"][i]["color"], out["hash"][i]["color"])
        self.assertEqual(out["more"], out["moreAlone"])
        # Gleiche Farbe im selben Diagramm → eine der beiden gestrichelt.
        self.assertNotEqual(out["both"][0]["dash"], out["both"][1]["dash"])
        self.assertFalse(out["alone"][0]["dashed"])
        self.assertFalse(out["alone"][1]["dashed"])

    def test_gps_und_pps_in_fester_signalfarbe(self):
        out = self.colors()
        for name, light, dark in out["gps"]:
            with self.subTest(name=name):
                self.assertEqual(light["color"], out["signal"]["light"])
                self.assertEqual(dark["color"], out["signal"]["dark"])
                self.assertTrue(light["signal"])
        for theme in ("light", "dark"):
            self.assertNotIn(out["signal"][theme], out["palette"][theme])
        self.assertFalse(dict((n, l) for n, l, _ in out["gps"])["GPS"]["dashed"])
        self.assertTrue(dict((n, l) for n, l, _ in out["gps"])["PPS"]["dashed"])

    def test_kontrast_gegen_diagrammhintergrund(self):
        out = self.colors()
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        for theme in ("light", "dark"):
            block = re.search(r':root\[data-theme="%s"\]\s*\{(.*?)\}' % theme, css, re.S).group(1)
            surface = re.search(r"--surface:\s*(#[0-9a-fA-F]{6})", block).group(1).lower()
            self.assertEqual(out["bg"][theme], surface, f"{theme}: CHART_BACKGROUND passt nicht zu --surface")
            for color in [*out["palette"][theme], out["signal"][theme]]:
                with self.subTest(theme=theme, color=color):
                    self.assertGreaterEqual(contrast(color, surface), 3.0)


class KurznamenTest(NodeTest):
    def test_kurznamen(self):
        out = self.run_js(f"""
const ch = await import({mod("charts.js")});
const one = ["uhr1.example.net", "time.example.org", "ntp1.example.com.", "192.0.2.1", "2001:db8::5",
  "GPS", "Abstand der Anfragen und mehr", "rechner"].map((n) => [n, ch.shortName(n)]);
const many = Object.fromEntries(ch.shortNames(["a.example.net", "a.example.org", "198.51.100.7"]));
console.log(JSON.stringify({{ one: Object.fromEntries(one), many }}));
""")
        one = out["one"]
        self.assertEqual(one["uhr1.example.net"], "uhr1")
        self.assertEqual(one["time.example.org"], "example")
        self.assertEqual(one["ntp1.example.com."], "example")
        self.assertEqual(one["192.0.2.1"], "192.0.2.1")
        self.assertEqual(one["2001:db8::5"], "2001:db8::5")
        self.assertEqual(one["GPS"], "GPS")
        self.assertEqual(one["rechner"], "rechner")
        self.assertLessEqual(len(one["Abstand der Anfragen und mehr"]), 14)
        self.assertTrue(one["Abstand der Anfragen und mehr"].endswith("…"))
        many = out["many"]
        self.assertNotEqual(many["a.example.net"], many["a.example.org"])
        self.assertEqual(many["198.51.100.7"], "198.51.100.7")

    def test_kurznamen_bleiben_eindeutig(self):
        groups = [
            ["abcdefghijklmnopqrstuvwxyz-1.example.org", "abcdefghijklmnopqrstuvwxyz-2.example.org"],
            ["abcdefghijklmnopqrstuvwxyz.eins.example.org", "abcdefghijklmnopqrstuvwxyz.zwei.example.org",
             "abcdefghijklmnopqrstuvwxyz.drei.example.org"],
            ["sehr-lange-gleiche-bezeichnung-a", "sehr-lange-gleiche-bezeichnung-b"],
            ["x1.a.org", "y1.a.org"],
        ]
        out = self.run_js(f"""
const ch = await import({mod("charts.js")});
console.log(JSON.stringify({json.dumps(groups)}.map((g) => Object.fromEntries(ch.shortNames(g)))));
""")
        for group, short in zip(groups, out):
            with self.subTest(group=group):
                values = [short[n] for n in group]
                self.assertEqual(len(set(values)), len(values), values)
                for v in values:
                    self.assertLessEqual(len(v), 22)
        self.assertTrue(out[0][groups[0][0]].endswith("-1"), out[0])
        self.assertEqual(out[3], {"x1.a.org": "x1", "y1.a.org": "y1"})


class ClientsTest(NodeTest):
    STATUS = {"system": {"time": 1783000000}, "serverstats": {},
              "clients": [{"address": "192.0.2.10", "ntp_packets": 50, "ntp_dropped": 0, "ntp_interval": 6, "ntp_last_rx": 3},
                          {"address": "192.0.2.11", "ntp_packets": 9, "ntp_dropped": 0, "ntp_interval": 6, "ntp_last_rx": 8}]}

    OFFSETS = {"192.0.2.10": {"measurable": True, "ewma": 0.0012, "min": 0.001, "max": 0.0014, "count": 12, "state": "ok"},
               "192.0.2.12": {"measurable": False, "state": "verschleiert", "requests": 4, "last_seen": 1783000000}}

    def render(self, mobile=False, readonly=False, scores=None, offsets=None):
        data = {"clientoffsets": {"available": True, "clients": offsets or {}, "names": {"192.0.2.10": "NAS im Keller"}},
                "clientquality": {"scores": scores or {}, "worst": [], "rated": 0}}
        return self.run_js(f"""
const clients = await import({mod("pages/clients.js")});
const D = {json.dumps(data)};
const status = {json.dumps(self.STATUS)};
const nodes = clients.render(ctx({{ status, readonly: {json.dumps(readonly)}, data: (k) => D[k] }}));
const heads = withAttr(nodes, "class", "num").filter((n) => n.tagName === "TH").map((n) => n.textContent.trim());
const allTh = [];
let nested = 0;
const walk = (n, inCell) => {{ if (!n) return; if (n.tagName === "TH") allTh.push(n.textContent.trim());
  if (inCell && (n.tagName === "TD" || n.tagName === "TH")) nested += 1;
  for (const c of n.childNodes || []) walk(c, inCell || ["TD", "TH", "DD", "DT"].includes(n.tagName)); }};
[].concat(nodes).forEach((n) => walk(n, false));
const list = withAttr(nodes, "class", "card").find((n) => /Geräte, die diesen Server fragen/.test(n.textContent)) || null;
const infos = list ? withAttr(list, "class", "info").filter((n) => n.attrs.class === "info").map((n) => n.attrs["aria-label"]) : [];
console.log(JSON.stringify({{ th: allTh, nested, infos, cards: withAttr(nodes, "class", "client-card").filter((n) => n.attrs.class === "client-card").length,
  tables: withAttr(nodes, "class", "clients-table").length, edit: withAttr(nodes, "class", "name-edit").length,
  text: text(nodes) }}));
""", mobile=mobile)

    def test_spalten_ohne_messwert_fallen_weg(self):
        out = self.render()
        heads = " ".join(out["th"])
        for kept in ("Anfragen", "Verworfen", "Intervall", "Zuletzt"):
            self.assertIn(kept, heads)
        # Keine eigene Messung, keine Uhrgüte → diese Spalten haben keinen Wert und fehlen.
        for gone in ("Uhr geht falsch um", "messbar", "Güte"):
            self.assertNotIn(gone, heads)
        out = self.render(scores={"192.0.2.10": {"score": 80, "tone": "good"}})
        self.assertIn("Güte", " ".join(out["th"]))

    def test_visible_columns_rein(self):
        out = self.run_js(f"""
const clients = await import({mod("pages/clients.js")});
const cols = clients.clientColumns({{ offsets: {{}}, scores: {{}}, lastAge: () => null }});
const rows = [{{ address: "192.0.2.10", ntp_packets: 3 }}, {{ address: "192.0.2.11" }}];
console.log(JSON.stringify(clients.visibleColumns(cols, rows).map((c) => c.key)));
""")
        self.assertEqual(out, ["packets"])

    def test_handy_karten_statt_tabelle(self):
        out = self.render(mobile=True)
        self.assertEqual(out["cards"], 2)
        self.assertEqual(out["tables"], 0)
        desk = self.render(mobile=False)
        self.assertEqual(desk["cards"], 0)
        self.assertEqual(desk["tables"], 1)

    def test_messwert_spalten_ohne_verschachtelte_zellen(self):
        for mobile in (False, True):
            with self.subTest(mobile=mobile):
                out = self.render(mobile=mobile, offsets=self.OFFSETS)
                self.assertIn("+1,2 ms", out["text"])
                self.assertIn("messbar", out["text"])
                self.assertEqual(out["nested"], 0)

    def test_karten_haben_dieselben_erklaerungen_wie_die_tabelle(self):
        desk = self.render(offsets=self.OFFSETS)
        phone = self.render(mobile=True, offsets=self.OFFSETS)
        self.assertGreater(len(desk["infos"]), 5)
        self.assertEqual(sorted(phone["infos"]), sorted(desk["infos"]))
        # 192.0.2.12 kennt nur die eigene Messung → „*“; die Erklärung dazu steht auf dem Handy sichtbar da.
        self.assertIn("4*", phone["text"])
        self.assertIn("* aus der eigenen Messung", phone["text"])
        self.assertNotIn("* aus der eigenen Messung", self.render(mobile=True)["text"])

    def test_name_bearbeiten_nur_mit_schreibrecht(self):
        self.assertEqual(self.render()["edit"], 2)
        self.assertIn("NAS im Keller", self.render()["text"])
        self.assertEqual(self.render(readonly=True)["edit"], 0)


class GrundTest(NodeTest):
    def table_heads(self, sources):
        return self.run_js(f"""
const src = await import({mod("pages/sources.js")});
const status = {{ system: {{ time: 1783000000 }}, sources: {json.dumps(sources)} }};
const nodes = src.render(ctx({{ status }}));
const th = [];
const walk = (n) => {{ if (!n) return; if (n.tagName === "TH") th.push(n.textContent.trim()); for (const c of n.childNodes || []) walk(c); }};
[].concat(nodes).forEach(walk);
console.log(JSON.stringify({{ th, differs: {json.dumps(sources)}.map((s) => src.reasonDiffers(s)) }}));
""")

    def test_grund_nur_wenn_anders_als_zustand(self):
        same = [{"name": "192.0.2.1", "state": "*", "select_state": "best", "mode": "^"},
                {"name": "198.51.100.7", "state": "+", "select_state": "combined", "mode": "^"}]
        out = self.table_heads(same)
        self.assertEqual(out["differs"], [False, False])
        self.assertFalse([h for h in out["th"] if h.startswith("Grund")])
        other = same + [{"name": "203.0.113.9", "state": "-", "select_state": "large_distance", "mode": "^"}]
        out = self.table_heads(other)
        self.assertEqual(out["differs"], [False, False, True])
        self.assertTrue([h for h in out["th"] if h.startswith("Grund")])


class ErklaerzeileTest(NodeTest):
    def test_split_verliert_nichts(self):
        texts = [
            "Kurz und gut.",
            "Für Geräte, die den Zeitserver aus DHCP ignorieren und fest eingebaute Namen fragen. Wähle dein System – "
            "die Anleitung ist mit der Adresse dieses Servers ausgefüllt, sobald sie bekannt ist.",
            "Die FRITZ!Box verteilt Option 42 nicht frei, z. B. dort Geräte direkt einstellen oder einen anderen "
            "DHCP-Server nutzen. Für Geräte mit fest eingebautem Server hilft **Zeitserver erzwingen** weiter unten.",
        ]
        out = self.run_js(f"""
const ui = await import({mod("ui.js")});
console.log(JSON.stringify({json.dumps(texts)}.map((t) => ui.splitExplain(t))));
""")
        self.assertEqual(out[0], {"first": "Kurz und gut.", "rest": ""})
        for original, part in zip(texts[1:], out[1:]):
            self.assertLessEqual(len(part["first"]), 140)
            self.assertTrue(part["rest"])
            self.assertEqual(re.sub(r"\W", "", (part["first"] + part["rest"]).lower()), re.sub(r"\W", "", original.lower()))
        self.assertNotRegex(out[2]["first"], r"z\.$")
        self.assertEqual(out[2]["first"].count("**") % 2, 0)

    def test_karte_mit_langem_untertitel(self):
        out = self.run_js(f"""
const ui = await import({mod("ui.js")});
const long = "Erster Satz der Erklärung bleibt sichtbar. " + "Der Rest wandert ins ⓘ und bleibt dort vollständig lesbar. ".repeat(4);
const node = ui.card("Titel", {{ help: "ntp", sub: long }});
console.log(JSON.stringify({{ text: text(node), info: withAttr(node, "class", "info").filter((n) => n.attrs.class === "info").length }}));
""")
        self.assertIn("Erster Satz der Erklärung bleibt sichtbar.", out["text"])
        self.assertLessEqual(out["text"].count("Der Rest wandert"), 1)
        self.assertLess(len(out["text"]), 160)
        self.assertEqual(out["info"], 1)


class KalibrierungF16Test(NodeTest):
    def test_phasentext_nur_einmal(self):
        phase = "Misst die Abweichung GPS ↔ Netz seit 08.11. 10:00 – ein Vorschlag frühestens am 08.11. 16:00."
        auto = {"plan": phase + " So arbeitet sie: messen → korrigieren.",
                "phase": {"label": "misst", "text": phase}, "decision": {"reason": phase}}
        held = {"plan": "Gesperrt wegen GNSS-Störung – hier entscheidest du.", "phase": {"label": "gesperrt", "text": "x"},
                "decision": {"reason": "Störung", "guard_hold": True}}
        out = self.run_js(f"""
const gps = await import({mod("pages/gps.js")});
console.log(JSON.stringify([gps.autocalTexts({json.dumps(auto)}), gps.autocalTexts({json.dumps(held)}),
  gps.autocalTexts({{ plan: null, phase: {{ text: "A" }}, decision: {{ reason: "A" }} }})]));
""")
        self.assertIsNone(out[0]["phaseText"])
        self.assertIsNone(out[0]["reason"])
        self.assertTrue(out[0]["plan"].startswith("Misst"))
        self.assertTrue(out[1]["held"])
        self.assertFalse(out[1]["holdCallout"])
        self.assertEqual(out[2]["phaseText"], "A")
        self.assertIsNone(out[2]["reason"])


class QuelltextTest(unittest.TestCase):
    def test_keine_inline_styles_in_neuen_bausteinen(self):
        for path in (JS / "pages" / "clients.js", JS / "charts.js", JS / "ui.js"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotRegex(source, r"setAttribute\(\s*[\"']style[\"']")
                self.assertNotIn("innerHTML", source)

    def test_diagnose_nutzt_range_picker_und_ptp_chart_card(self):
        self.assertIn("rangePicker(", (JS / "pages" / "diagnose.js").read_text(encoding="utf-8"))
        self.assertIn("chartCard(", (JS / "pages" / "ptp.js").read_text(encoding="utf-8"))
        self.assertIn("chartCard(", (JS / "pages" / "clientdetail.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
