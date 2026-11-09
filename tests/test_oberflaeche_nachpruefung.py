"""Zweite Fehlersuche an der Oberfläche von 1.6 – je bestätigtem Befund ein Test, der vor der Korrektur rot war.

  * Einrichtung, Schritt „Clients“: eine Container-ID (Docker-Bridge) wird nicht als Rechnername angeboten.
  * Tagesbericht: „Verlauf nur über … h“ misst die Abdeckung an der echten Tageslänge (23/25 h bei Umstellung).
  * Einstellungen: Ein Klick auf die Speicherleiste geht nicht verloren, weil die Leiste ihre Knöpfe behält;
    der Quellen-Editor übernimmt den Hostnamen beim Tippen, ohne sich neu aufzubauen (Fokus bleibt).
  * Vorschau: „wirkt nur im Dashboard“ nur, wenn keine Änderung einen Neustart der Zeitdienste braucht.
  * Verlassen-Dialog: „Abbrechen“ springt im Verlauf zurück, statt einen fremden Eintrag zu überschreiben.
  * Tastenkürzel: nicht bei offenem modalem Dialog; ein Seitenwechsel schließt offene Dialoge.
  * Offset je Quelle: Pool-Mitglieder mit gleichem Hostnamen bekommen eindeutige Linienenden und Legenden.
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

from test_darstellung_t1 import DOM_SHIM  # noqa: E402 – DOM-Attrappe mit Ereignissen und Eltern

EXTRA = r"""
Element.prototype.showModal = function () { this.open = true; };
Element.prototype.close = function () { if (!this.open) return; this.open = false;
  for (const fn of this.listeners.close || []) fn({}); };
Element.prototype.fire = function (type, event = {}) { for (const fn of this.listeners[type] || []) fn({ target: this, ...event }); };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
globalThis.CSS = { escape: (s) => String(s) };
const i18n = await import(JS + "/i18n.js");
const { readFileSync } = await import("node:fs");
i18n._setCatalogs({ de: JSON.parse(readFileSync(new URL(JS + "/../i18n/de.json"), "utf-8")) }, "de");
globalThis.find = (root, pred) => (pred(root) ? [root] : []).concat(root.findAll(pred));
globalThis.byClass = (root, cls) => find(root, (n) => String(n.attrs?.class || "").split(" ").includes(cls));
globalThis.tick = () => new Promise((r) => setTimeout(r, 0));
"""


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class NodeTest(unittest.TestCase):
    def run_js(self, code: str, tz: str = "UTC"):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dom.mjs").write_text(DOM_SHIM, encoding="utf-8")
            script = Path(tmp) / "run.mjs"
            root = json.dumps(JS.resolve().as_uri())
            script.write_text(f'import "./dom.mjs";\nconst JS = {root};\n{EXTRA}\n{code}', encoding="utf-8")
            env = {**os.environ, "TZ": tz}
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------- Einrichtung (Befund 1)
class RechnernameTest(NodeTest):
    def rows(self, hostname: str):
        return self.run_js(f"""
const setup = await import(JS + "/pages/setup.js");
window.location.hostname = "192.168.1.10";
const ctx = {{ status: {{ system: {{ hostname: {json.dumps(hostname)}, addresses: ["192.168.1.10"] }} }}, uiState: {{}},
  subpath: "clients", data: (k) => (k === "setup" ? {{ can_write: true, items: [] }} : undefined), dataError: () => null, rerender() {{}}, afterRender() {{}}, invalidate() {{}} }};
const root = document.createElement("div");
root.append(...[].concat(setup.render(ctx)).flat(Infinity).filter(Boolean));
console.log(JSON.stringify({{ text: root.textContent, codes: byClass(root, "mono").map((n) => n.textContent) }}));
""")

    def test_container_id_wird_nicht_angeboten(self):
        for name in ("3f2a9c1b7d4e", "3f2a9c1b7d4e" * 5 + "abcd"):
            with self.subTest(name=name):
                out = self.rows(name)
                self.assertNotIn(name, out["codes"])
                self.assertNotIn("Rechnername", out["text"])
                self.assertIn("192.168.1.10", out["codes"], "die Adresse bleibt")

    def test_echter_rechnername_bleibt(self):
        out = self.rows("zeitserver")
        self.assertIn("zeitserver", out["codes"])
        self.assertIn("Rechnername", out["text"])


# --------------------------------------------------------------------------- Tagesbericht (Befund 6)
class TagesberichtTest(NodeTest):
    def line(self, hours: float, covered_h: float):
        return self.run_js(f"""
const tl = await import(JS + "/timeline.js");
const start = 1774735200;
const report = {{ samples: 8000, synced_pct: 100, covered_s: {covered_h} * 3600, start, end: start + {hours} * 3600 }};
const ctx = {{ status: {{ system: {{}} }}, uiState: {{}}, data: () => ({{ report }}) }};
console.log(JSON.stringify(tl.dailyReportCard(ctx).textContent));
""")

    def test_sommerzeit_tag_lueckenlos(self):
        self.assertNotIn("Verlauf nur", self.line(23, 23 - 11 / 3600))

    def test_winterzeit_tag_mit_luecke(self):
        self.assertIn("Verlauf nur", self.line(25, 23.2))

    def test_normaler_tag_unveraendert(self):
        self.assertNotIn("Verlauf nur", self.line(24, 24 - 11 / 3600))
        self.assertNotIn("Verlauf nur", self.line(24, 23.1))
        self.assertIn("Verlauf nur", self.line(24, 22.5))


# --------------------------------------------------------------------------- Einstellungen (Befunde 7, 8)
SETTINGS = r"""
const page = await import(JS + "/pages/settings.js");
const pool = { type: "pool", host: "pool.ntp.org", nts: false, prefer: false, noselect: false, options: "" };
const field = (key, type, section, value, restart, extra = {}) => ({ key, type, section, value, default: value, restart,
  label: key, hint: "", ...extra });
const schema = { readonly: false, notes: [], storage: { persistent: true },
  sections: [{ key: "ntp", label: "NTP" }, { key: "gps", label: "GPS" }, { key: "web", label: "Web" }],
  fields: [field("ntp_minsources", "int", "ntp", 1, "services"), field("ntp_sources", "sources", "ntp", [pool], "services"),
    field("gps_device", "device", "gps", "/dev/ttyACM0", "services"), field("web_title", "text", "web", "NTP", "none")] };
const posts = [];
let previewFiles = [{ name: "chrony.conf", status: "same", diff: [] }, { name: "ptp4l.conf", status: "unused", diff: [] }];
globalThis.fetch = async (url, init) => { posts.push({ url, body: JSON.parse(init.body) });
  return { ok: true, json: async () => (url.endsWith("/preview") ? { files: previewFiles, notes: [] } : { restart: false }) }; };
globalThis.window.confirm = () => true;
const uiState = {};
const ctx = { status: { system: {} }, uiState, data: (k) => (k === "settings" ? schema : undefined), dataError: () => null,
  rerender() {}, afterRender() {}, invalidate() {}, refresh() {}, watchReload() {} };
const show = (tab) => { window.location.hash = `#/system/einstellungen?s=${tab}`; const root = document.createElement("main");
  root.append(...[].concat(page.render(ctx)).flat(Infinity).filter(Boolean)); return root; };
const buttons = (root) => byClass(root, "save-bar")[0].findAll((n) => n.tagName === "BUTTON");
const byId = (root, id) => find(root, (n) => n.attrs?.id === id)[0];
"""


class SpeicherleisteTest(NodeTest):
    def test_knoepfe_bleiben_beim_aendern_bestehen(self):
        # Befund 7: Verliert ein Feld beim Drücken auf „Speichern“ den Fokus und ändert dabei den Entwurf,
        # darf die Leiste ihre Knöpfe nicht neu bauen – sonst treffen Drücken und Loslassen verschiedene Elemente.
        out = self.run_js(SETTINGS + r"""
const root = show("quellen");
const min = byId(root, "f-ntp_minsources");
min.value = "2"; min.fire("input");
const before = buttons(root);
min.value = "3"; min.fire("input");
const after = buttons(root);
console.log(JSON.stringify({ count: before.length, same: before.every((b, i) => b === after[i]),
  attached: after.every((b) => before.includes(b)), summary: byClass(root, "save-summary")[0].textContent }));
""")
        self.assertEqual(out["count"], 3)
        self.assertTrue(out["same"])
        self.assertTrue(out["attached"])
        self.assertIn("1 Änderung", out["summary"])

    def test_hostname_beim_tippen_ohne_neuaufbau(self):
        out = self.run_js(SETTINGS + r"""
const root = show("quellen");
const host = find(root, (n) => n.attrs?.["aria-label"] === "Server oder Pool")[0];
host.value = "time.example.org";
host.fire("input");
const still = find(root, (n) => n === host).length === 1;
const draft = uiState.settings.draft.ntp_sources;
await buttons(root).find((b) => b.textContent === "Speichern").fire("click");
await tick();
console.log(JSON.stringify({ still, draft, posts }));
""")
        self.assertTrue(out["still"], "das Feld bleibt im Editor – der Fokus geht nicht verloren")
        self.assertEqual(out["draft"][0]["host"], "time.example.org")
        self.assertEqual(len(out["posts"]), 1)
        self.assertEqual(out["posts"][0]["body"]["changes"]["ntp_sources"][0]["host"], "time.example.org")

    def test_andere_zellen_behalten_den_getippten_namen(self):
        out = self.run_js(SETTINGS + r"""
const root = show("quellen");
const host = find(root, (n) => n.attrs?.["aria-label"] === "Server oder Pool")[0];
host.value = "time.example.org"; host.fire("input");
const nts = find(root, (n) => n.attrs?.["aria-label"] === "NTS")[0];
nts.checked = true; nts.fire("change");
console.log(JSON.stringify(uiState.settings.draft.ntp_sources));
""")
        self.assertEqual(out[0]["host"], "time.example.org")
        self.assertTrue(out[0]["nts"])


class VorschauTest(NodeTest):
    def preview(self, tab: str, key: str, value: str):
        return self.run_js(SETTINGS + f"""
const root = show({json.dumps(tab)});
const input = byId(root, {json.dumps("f-" + key)});
input.value = {json.dumps(value)}; input.fire("input");
buttons(root).find((b) => b.textContent === "Vorschau").fire("click");
await tick(); await tick();
const dialog = byClass(document.body, "preview-dialog")[0];
console.log(JSON.stringify(dialog.textContent));
""")

    def test_neustart_wird_nicht_verharmlost(self):
        text = self.preview("gps", "gps_device", "/dev/ttyUSB0")
        self.assertNotIn("nur im Dashboard", text)
        self.assertIn("Neustart der Zeitdienste", text)

    def test_reine_dashboard_aenderung_bleibt(self):
        text = self.preview("zugang", "web_title", "Uhr")
        self.assertIn("nur im Dashboard", text)


class KatalogTest(unittest.TestCase):
    def test_neuer_text_in_beiden_sprachen(self):
        for lang in ("de", "en"):
            data = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
            self.assertTrue(data["settings"]["preview"].get("none_restart"), lang)


# --------------------------------------------------------------------------- Verlauf (Befund 9)
class VerlaufTest(NodeTest):
    """„Abbrechen“ im Verlassen-Dialog: der Handler (routes.js: hashChange, den app.js aufruft) gegen einen
    nachgebauten Browser-Verlauf – hashchange kommt wie im Browser erst nach dem Handler an."""

    SCRIPT = r"""
const routes = await import(JS + "/routes.js");
const EINST = "#/system/einstellungen?s=lan";
// Browser: Einträge mit Hash und state, Zeiger; ein Link schneidet „Vor“ ab; location.replace ersetzt den
// Eintrag (state null); go/Link/replace lösen hashchange aus, wenn sich der Hash ändert – nachgelagert.
function browser(start) {
  const entries = [{ hash: start, state: null }];
  let i = 0;
  const queue = [];
  const moved = (before) => { if (entries[i].hash !== before) queue.push(1); };
  const b = {
    entries, get i() { return i; }, get state() { return entries[i].state; }, get hash() { return entries[i].hash; },
    replaceState(state) { entries[i].state = state; },
    go(n) { const before = b.hash; i = Math.max(0, Math.min(entries.length - 1, i + n)); moved(before); },
    link(hash) { const before = b.hash; entries.splice(i + 1); entries.push({ hash, state: null }); i += 1; moved(before); },
    replace(hash) { const before = b.hash; entries[i] = { hash, state: null }; moved(before); },
    queue,
  };
  return b;
}
// App wie app.js: Start nummeriert (navIndex = stampEntry(history, 0)), jeder hashchange geht durch hashChange.
// Die Einstellungen sind „dirty“; leaveAllowed fragt wie app.js nur beim Wechsel auf eine andere Seite.
function app(start, answers) {
  const b = browser(start);
  const a = { b, shown: routes.stampEntry(b, 0), page: start, dirty: start === EINST, prompts: 0, renders: [] };
  const leaveAllowed = () => {
    if (b.hash === a.page || !a.dirty) return true;
    a.prompts += 1;
    if (!answers.shift()) return false;
    a.dirty = false;
    return true;
  };
  const redirect = () => {
    const found = routes.resolve(b.hash);
    if (!found.redirect) return false;
    b.replace(found.redirect);
    return true;
  };
  a.settle = () => {
    let guard = 0;
    while (b.queue.length) {
      b.queue.shift();
      if (++guard > 20) throw new Error("Endlosschleife im Verlauf");
      const step = routes.hashChange(b, a.shown, { leaveAllowed, redirect });
      a.shown = step.shown;
      if (step.show) { a.page = b.hash; a.dirty = b.hash === EINST; a.renders.push(b.hash); }
    }
  };
  a.view = () => ({ hash: b.hash, page: a.page, shown: a.shown, prompts: a.prompts, renders: a.renders.slice(),
    list: b.entries.map((e) => e.hash), nav: b.entries.map((e) => routes.entryIndex(e.state)) });
  return a;
}
const run = (answers, steps) => {
  const a = app("#/", answers);
  const out = [];
  for (const step of steps) { step(a.b); a.settle(); out.push(a.view()); }
  return out;
};
const out = {};
// Zurück → Abbrechen → Zurück → OK: die vorige Seite bleibt im Verlauf und erscheint
out.back = run([false, true], [(b) => b.link("#/gps"), (b) => b.link(EINST), (b) => b.go(-1), (b) => b.go(-1)]);
// history.go(-2) → Abbrechen: zurück auf die Einstellungen, alle Einträge bleiben
out.jump = run([false], [(b) => b.link("#/gps"), (b) => b.link(EINST), (b) => b.go(-2)]);
// Link → Abbrechen → Vor → Abbrechen → Vor → OK: der Link-Eintrag liegt als Vor-Eintrag dahinter
out.link = run([false, false, true], [(b) => b.link(EINST), (b) => b.link("#/gps"), (b) => b.go(1), (b) => b.go(1)]);
// Alte Route per Link: umgestellt ohne eigenen Eintrag, gezeichnet wird nur das Ziel
out.legacy = run([], [(b) => b.link("#/ptp")]);
out.legacyTarget = routes.resolve("#/ptp").redirect;
out.keep = routes.stampState({ other: 1 }, 4);
console.log(JSON.stringify(out));
"""

    def test_abbrechen_ueberschreibt_keinen_eintrag(self):
        out = self.run_js(self.SCRIPT)
        full = ["#/", "#/gps", "#/system/einstellungen?s=lan"]
        back = out["back"]
        # Start nummeriert mit 1, jeder neue Eintrag mit der nächsten Nummer.
        self.assertEqual(back[1]["nav"], [1, 2, 3])
        cancel = back[2]
        self.assertEqual(cancel["hash"], full[2], "Abbrechen bleibt auf den Einstellungen")
        self.assertEqual((cancel["list"], cancel["nav"]), (full, [1, 2, 3]), "kein Eintrag überschrieben")
        self.assertEqual(cancel["prompts"], 1, "der Rücksprung fragt nicht noch einmal")
        self.assertEqual(cancel["renders"], ["#/gps", full[2]], "der Rücksprung zeichnet nicht neu")
        again = back[3]
        self.assertEqual((again["hash"], again["page"], again["shown"]), ("#/gps", "#/gps", 2))
        self.assertEqual(again["prompts"], 2)

        jump = out["jump"][2]
        self.assertEqual((jump["hash"], jump["page"], jump["shown"]), (full[2], full[2], 3))
        self.assertEqual((jump["list"], jump["nav"], jump["prompts"]), (full, [1, 2, 3], 1))
        self.assertEqual(jump["renders"], ["#/gps", full[2]])

        link = out["link"]
        einst = ["#/", full[2], "#/gps"]
        self.assertEqual((link[1]["hash"], link[1]["shown"]), (full[2], 2))
        self.assertEqual(link[1]["list"], einst, "der Link-Eintrag bleibt als Vor-Eintrag")
        self.assertEqual(link[1]["nav"], [1, 2, None])
        self.assertEqual(link[1]["renders"], [full[2]], "kein doppelter Einstellungen-Eintrag, kein Neuzeichnen")
        self.assertEqual((link[2]["hash"], link[2]["prompts"], link[2]["list"]), (full[2], 2, einst))
        last = link[3]
        self.assertEqual((last["hash"], last["page"], last["shown"], last["prompts"]), ("#/gps", "#/gps", 3, 3))
        self.assertEqual((last["list"], last["nav"]), (einst, [1, 2, 3]))

        legacy = out["legacy"][0]
        target = out["legacyTarget"]
        self.assertTrue(target)
        self.assertEqual((legacy["list"], legacy["nav"]), (["#/", target], [1, 2]))
        self.assertEqual(legacy["renders"], [target], "die alte Route wird nicht gezeichnet")
        self.assertEqual(out["keep"], {"other": 1, "nav": 4})

    def test_app_nutzt_den_handler(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        handler = app[app.index('window.addEventListener("hashchange"'):]
        handler = handler[:handler.index("\n});")]
        # Der getestete Rumpf ist der von app.js: der Handler ruft hashChange als Erstes, zeichnet nur bei show.
        lines = [line.strip() for line in handler.splitlines()[1:4]]
        self.assertEqual(lines, ["const step = hashChange(history, navIndex, { leaveAllowed, redirect: redirectLegacy });",
                                 "navIndex = step.shown;", "if (!step.show) return;"])
        self.assertNotIn("replaceState", handler, "Abbrechen darf keinen Verlaufseintrag überschreiben")
        self.assertIn("\nnavIndex = stampEntry(history, navIndex);\n", app, "Start nummeriert den ersten Eintrag")
        self.assertNotIn("function stampEntry", app, "nur die getestete Fassung aus routes.js")


# --------------------------------------------------------------------------- Dialoge und Kürzel (Befunde 10, 15)
class DialogKuerzelTest(unittest.TestCase):
    app = (JS / "app.js").read_text(encoding="utf-8")

    def test_kuerzel_ruhen_bei_offenem_dialog(self):
        handlers = re.findall(r'document\.addEventListener\("keydown", \(event\) => \{\n(.*?)\n\}\);', self.app, re.S)
        shortcut = [h for h in handlers if "onShortcut(event)" in h]
        self.assertEqual(len(shortcut), 1)
        self.assertIn('querySelector("dialog[open]")', shortcut[0])

    def test_seitenwechsel_schliesst_dialoge(self):
        handler = self.app[self.app.index('window.addEventListener("hashchange"'):]
        handler = handler[:handler.index("\n});")]
        self.assertIn("closeDialogs(", handler)
        body = self.app[self.app.index("function closeDialogs("):]
        body = body[:body.index("\n}")]
        self.assertIn('querySelectorAll("dialog[open]")', body)
        self.assertIn(".close()", body)


# --------------------------------------------------------------------------- Offset je Quelle (Befund 11)
class PoolNamenTest(NodeTest):
    def test_linienenden_eindeutig(self):
        out = self.run_js(r"""
const ch = await import(JS + "/charts.js");
const ids = ["192.0.2.1", "192.0.2.2", "198.51.100.3", "203.0.113.4"];
const series = ids.map((id, k) => ({ id, label: "pool.ntp.org", points: [[0, k * 1e-3], [60, k * 1e-3 + 1e-4]] }));
const host = document.createElement("div");
ch.lineChart(host, { series, events: false });
console.log(JSON.stringify(byClass(host, "chart-end-label").map((n) => n.textContent)));
""")
        self.assertEqual(len(out), 4)
        self.assertEqual(len(set(out)), 4, out)

    def test_quellenseite_beschriftet_pool_mitglieder(self):
        out = self.run_js(r"""
const page = await import(JS + "/pages/sources.js");
const ids = ["192.0.2.1", "192.0.2.2", "198.51.100.3"];
const sources = [...ids.map((name) => ({ name, hostname: "pool.ntp.org", mode: "^", state: "+" })),
  { name: "192.0.2.9", hostname: "ptbtime1.ptb.de", mode: "^", state: "*" }];
const history = [0, 60].map((t) => ({ t, sources: Object.fromEntries([...ids, "192.0.2.9"].map((n, k) => [n, { o: k * 1e-3 }])) }));
const pending = [];
const ctx = { status: { sources, system: { time: 60 } }, history, range: 3600, uiState: {}, data: () => undefined,
  dataError: () => null, rerender() {}, afterRender: (fn) => pending.push(fn), setRange() {}, invalidate() {} };
const root = document.createElement("main");
root.append(...[].concat(page.render(ctx)).flat(Infinity).filter(Boolean));
pending.forEach((fn) => fn());
console.log(JSON.stringify({ legend: byClass(root, "legend-item").map((n) => n.textContent),
  ends: byClass(root, "chart-end-label").map((n) => n.textContent) }));
""")
        legend = out["legend"]
        self.assertEqual(len(legend), 4, out)
        self.assertEqual(len(set(legend)), 4, legend)
        self.assertIn("ptbtime1.ptb.de", legend, "eindeutige Namen bleiben, wie sie sind")
        self.assertTrue(all("pool.ntp.org" in name for name in legend if name != "ptbtime1.ptb.de"))
        self.assertEqual(sorted(out["ends"]), ["192.0.2.1", "192.0.2.2", "198.51.100.3", "ptbtime1"])


if __name__ == "__main__":
    unittest.main()
