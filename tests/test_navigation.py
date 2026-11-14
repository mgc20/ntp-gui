"""T2 GUI-Erneuerung, Teil „Navigation“ (docs/konzept/version-1.6.md, Punkte 3, 6 und 7).

  * Routentabelle (app/static/js/routes.js) im echten JS-Interpreter: jede Seite erreichbar, jeder
    Navigationseintrag zeigt auf eine Seite, Gruppen haben Reiter, jede alte Route (bis 1.5) hat ein
    Ziel – mit Unterpfad und Abfrageteil, ohne Umweg über eine zweite Weiterleitung.
  * Keine alten Links mehr im Code (außer in der Weiterleitungstabelle LEGACY): jeder Hash-Link in
    den Seiten landet ohne Weiterleitung; Ziele vom Server (Hinweise, Benachrichtigungen) ebenso.
  * Tastenkürzel (shortcuts.js): g o / g s / …, „/“ und „?“ – nie in Eingabefeldern, nie mit
    Strg/Alt/Meta.
  * Fußzeile ohne /metrics · /api/status · /healthz; die stehen jetzt in der Hilfe.
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
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

# Routen bis 1.5 (Navigation mit elf Einträgen) → erwartete Seite nach der Weiterleitung.
OLD_ROUTES = {
    "#/": ("overview", "#/"),
    "#/quellen": ("sources", None),
    "#/gps": ("gps", None),
    "#/ptp": ("ptp", "#/uhr/ptp"),
    "#/uhrqualitaet": ("clockquality", "#/uhr/qualitaet"),
    "#/hardware": ("hardware", "#/uhr/hardware"),
    "#/clients": ("clients", None),
    "#/diagnose": ("diagnose", "#/system/diagnose"),
    "#/benachrichtigungen": ("notify", "#/system/benachrichtigungen"),
    "#/einstellungen": ("settings", "#/system/einstellungen"),
    "#/hilfe": ("help", None),
}
OLD_NAMES = ("ptp", "uhrqualitaet", "hardware", "diagnose", "benachrichtigungen", "einstellungen", "gnss", "gpsquality")
OLD_LINK = re.compile(r"#/(?:%s)\b" % "|".join(OLD_NAMES))
HASH_LITERAL = re.compile(r"""["'`](#/[^"'`$\s]*)""")
# Aktionen im Server, die keine Hinweise sind (Autokalibrierung, GNSS-Sperre, Holdover-Test).
NON_INSIGHT_ACTIONS = {"none", "suggest", "apply", "lock", "unlock", "relearn", "reset", "start", "stop", "abort"}


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


def code_lines(path: Path):
    """Zeilen ohne reine Kommentarzeilen (Kommentare dürfen die alten Namen erklären)."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if not stripped.startswith(("//", "*", "/*", "#")):
            yield number, line


def frontend_files():
    return [*sorted(JS.glob("*.js")), *sorted((JS / "pages").glob("*.js"))]


def run_node(body: str):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "run.mjs"
        script.write_text(body, encoding="utf-8")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class RoutenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = run_node(f"""
const r = await import({mod("routes.js")});
const resolveAll = (hash, dev = false) => {{
  const first = r.resolve(hash, dev);
  const second = first.redirect ? r.resolve(first.redirect, dev) : null;
  return {{ redirect: first.redirect || null, page: (second || first).page?.id || null, sub: (second || first).sub ?? null,
    query: (second || first).query ?? null, again: Boolean(second && second.redirect) }};
}};
const hashes = {json.dumps(sorted(set(OLD_ROUTES) | {
    "", "#", "#main", "#/unbekannt", "#/uhr", "#/uhr/", "#/system", "#/system?s=web", "#/uhr/gibtsnicht",
    "#/einstellungen?s=gps", "#/system/einstellungen?s=gps", "#/hardware/x/y?z=1", "#/UHRQUALITAET",
    "#/clients/192.0.2.10", "#/clients/192.0.2.10/pass", "#/clients/2001%3Adb8%3A%3A1", "#/gnss", "#/gpsquality",
    "#/hilfe?t=pps", "#/ptp/", "#/muster", "#/einstellungen/"}))};
const out = {{ nav: r.NAV, pages: r.PAGES, legacy: r.LEGACY, groups: r.GROUPS, resolved: {{}}, dev: resolveAll("#/muster", true),
  routes: Object.fromEntries(r.PAGES.map((p) => [p.id, r.route(p.id)])),
  tabs: Object.fromEntries(r.NAV.map((n) => [n.id, r.tabsOf(n.id).map((p) => p.id)])),
  actions: Object.fromEntries(Object.keys(r.ACTION_PAGES).map((a) => [a, r.actionHref(a)])), unknownAction: r.actionHref("gibtsnicht"),
  proto: r.actionHref("toString") }};
for (const h of hashes) out.resolved[h] = resolveAll(h);
for (const p of r.PAGES) if (!p.dev) out.resolved[r.route(p.id)] = resolveAll(r.route(p.id));
for (const n of r.NAV) out.resolved[n.href] = resolveAll(n.href);
console.log(JSON.stringify(out));
""")

    def resolved(self, hash_):
        return self.table["resolved"][hash_]

    def test_sieben_eintraege(self):
        titles = [n["titleKey"] for n in self.table["nav"]]
        self.assertEqual(titles, ["nav.overview", "nav.sources", "nav.gps", "nav.clients", "nav.uhr", "nav.system", "nav.help"])
        self.assertEqual([n["id"] for n in self.table["nav"] if n.get("bottom")], ["overview", "sources", "gps", "clients"])

    def test_gruppen_und_reiter(self):
        self.assertEqual(self.table["tabs"]["uhr"], ["clockquality", "hardware", "ptp", "displays"])
        self.assertEqual(self.table["tabs"]["system"], ["diagnose", "notify", "settings", "setup"])
        # Standardreiter = erster: Gruppe ohne Reiter → erster Reiter, auch mit Abfrageteil.
        self.assertEqual(self.resolved("#/uhr")["redirect"], "#/uhr/qualitaet")
        self.assertEqual(self.resolved("#/uhr/")["redirect"], "#/uhr/qualitaet")
        self.assertEqual(self.resolved("#/system?s=web")["redirect"], "#/system/diagnose?s=web")
        self.assertEqual(self.resolved("#/uhr/gibtsnicht")["page"], "clockquality")

    def test_jede_seite_erreichbar(self):
        nav_ids = {n["id"] for n in self.table["nav"]}
        for page in self.table["pages"]:
            with self.subTest(page=page["id"]):
                hit = self.resolved(self.table["routes"][page["id"]])
                if page.get("dev"):
                    self.assertEqual(self.table["dev"]["page"], page["id"])
                    continue
                self.assertIsNone(hit["redirect"], "kanonische Route darf nicht weiterleiten")
                self.assertEqual(hit["page"], page["id"])
                self.assertIn(page["nav"], nav_ids)
                self.assertTrue((JS / "pages" / f"{page['id']}.js").exists())

    def test_jeder_nav_eintrag_zeigt_auf_seine_seite(self):
        pages = {p["id"]: p for p in self.table["pages"]}
        for entry in self.table["nav"]:
            with self.subTest(nav=entry["id"]):
                hit = self.resolved(entry["href"])
                self.assertIsNone(hit["redirect"])
                self.assertEqual(pages[hit["page"]]["nav"], entry["id"])

    def test_module_in_app_js(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        modules = re.search(r"const MODULES = \{([^}]*)\}", app).group(1)
        names = {n.strip() for n in modules.split(",")}
        for page in self.table["pages"]:
            with self.subTest(page=page["id"]):
                self.assertIn(page["id"], names)
                self.assertRegex(app, r'import \* as %s from "\./pages/\w+\.js";' % page["id"])

    def test_alte_routen_landen_richtig(self):
        for old, (page, target) in OLD_ROUTES.items():
            with self.subTest(route=old):
                hit = self.resolved(old)
                self.assertEqual(hit["page"], page)
                self.assertFalse(hit["again"], "höchstens eine Weiterleitung")
                if target and target != old:
                    self.assertEqual(hit["redirect"], target)
                else:
                    self.assertIsNone(hit["redirect"])

    def test_jede_alte_route_hat_ein_ziel(self):
        page_paths = {p["path"] for p in self.table["pages"]}
        for old, target in self.table["legacy"].items():
            with self.subTest(old=old):
                self.assertIn(target, page_paths)
                self.assertNotIn(old, page_paths)
                hit = self.resolved(f"#/{old}") if f"#/{old}" in self.table["resolved"] else None
                if hit:
                    self.assertEqual(hit["redirect"], f"#/{target}")

    def test_unterpfad_und_abfrage_bleiben(self):
        self.assertEqual(self.resolved("#/einstellungen?s=gps")["redirect"], "#/system/einstellungen?s=gps")
        self.assertEqual(self.resolved("#/hardware/x/y?z=1")["redirect"], "#/uhr/hardware/x/y?z=1")
        self.assertEqual(self.resolved("#/UHRQUALITAET")["redirect"], "#/uhr/qualitaet")
        self.assertEqual(self.resolved("#/ptp/")["redirect"], "#/uhr/ptp")
        self.assertEqual(self.resolved("#/einstellungen/")["redirect"], "#/system/einstellungen")
        settings = self.resolved("#/system/einstellungen?s=gps")
        self.assertEqual((settings["page"], settings["query"]), ("settings", "s=gps"))
        self.assertEqual(self.resolved("#/hilfe?t=pps")["query"], "t=pps")
        for hash_, sub in (("#/clients/192.0.2.10", "192.0.2.10"), ("#/clients/192.0.2.10/pass", "192.0.2.10/pass"),
                           ("#/clients/2001%3Adb8%3A%3A1", "2001:db8::1")):
            with self.subTest(hash=hash_):
                hit = self.resolved(hash_)
                self.assertEqual((hit["page"], hit["sub"], hit["redirect"]), ("clients", sub, None))

    def test_nie_leere_seite(self):
        for hash_ in ("", "#", "#main", "#/unbekannt", "#/muster", "#/gnss", "#/gpsquality"):
            with self.subTest(hash=hash_):
                self.assertTrue(self.resolved(hash_)["page"])
        self.assertEqual(self.resolved("#/muster")["page"], "overview", "Musterseite nur mit ?dev=1")
        self.assertEqual(self.resolved("#/gnss")["page"], "gps")
        self.assertEqual(self.resolved("#main")["page"], "overview")

    def test_hinweis_ziele(self):
        actions = self.table["actions"]
        self.assertIsNone(self.table["unknownAction"])
        self.assertIsNone(self.table["proto"])
        self.assertEqual(actions["hardware"], "#/uhr/hardware")
        self.assertEqual(actions["uhrqualitaet"], "#/uhr/qualitaet")  # ältere Server
        # Jede Aktion, die der Server in Hinweisen schickt, hat ein Ziel.
        found = set()
        for path in sorted((ROOT / "app").glob("*.py")):
            found |= set(re.findall(r"""["']?action["']?\s*[:=]\s*["']([a-z_]+)["']""", path.read_text(encoding="utf-8")))
        for action in sorted(found - NON_INSIGHT_ACTIONS):
            with self.subTest(action=action):
                self.assertIn(action, actions)
                self.assertIsNotNone(actions[action])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class KeineAltenLinksTest(unittest.TestCase):
    def test_keine_alten_hash_links_im_code(self):
        found = []
        for path in frontend_files():
            if path.name == "routes.js":
                continue  # Weiterleitungstabelle LEGACY
            for number, line in code_lines(path):
                if OLD_LINK.search(line):
                    found.append(f"{path.name}:{number}: {line.strip()[:100]}")
        for path in [STATIC / "index.html", ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if OLD_LINK.search(line):
                    found.append(f"{path.name}:{number}: {line.strip()[:100]}")
        self.assertEqual(found, [])

    def test_jeder_hash_link_landet_ohne_weiterleitung(self):
        links = set()
        for path in frontend_files():
            if path.name == "routes.js":
                continue
            for _number, line in code_lines(path):
                links |= set(HASH_LITERAL.findall(line))
        self.assertTrue(links)
        out = run_node(f"""
const r = await import({mod("routes.js")});
const links = {json.dumps(sorted(links))};
console.log(JSON.stringify(Object.fromEntries(links.map((h) => [h, r.resolve(h).redirect || null]))));
""")
        self.assertEqual({k: v for k, v in out.items() if v}, {})

    def test_einstellungen_sprungziele_landen_im_richtigen_reiter(self):
        # Einstellungen 2.0: Reiter im Abfrageteil (?s=gps). Jedes Sprungziel im Code (Hash-Literal oder
        # route("settings", "", "s=…")) und jedes alte (?s=web, ?s=nts …) landet in einem echten Reiter –
        # nie stillschweigend im ersten, weil der Abschnitt unbekannt ist.
        targets = set()
        for path in frontend_files():
            for _number, line in code_lines(path):
                targets |= set(re.findall(r"#/(?:system/)?einstellungen\?s=([a-z]+)", line))
                targets |= set(re.findall(r"""route\("settings",\s*"",\s*["'`]s=([a-z]+)""", line))
        self.assertTrue({"gps", "web", "ptp"} <= targets, targets)
        legacy = {"ntp": "quellen", "nts": "quellen", "dns": "quellen", "lan": "lan", "gps": "gps", "ptp": "ptp",
                  "web": "zugang", "auth": "zugang", "api": "zugang", "backup": "sichern"}
        out = run_node(f"""
globalThis.document = {{ addEventListener() {{}}, createElement: () => ({{}}) }};
globalThis.window = {{ addEventListener() {{}}, location: {{ hash: "" }} }};
const s = await import({mod("pages/settings.js")});
const r = await import({mod("routes.js")});
const ids = s.TABS.map((x) => x.id);
const probe = {json.dumps(sorted(targets | set(legacy)))};
console.log(JSON.stringify({{ ids, tabs: Object.fromEntries(probe.map((x) => [x, s.tabFromQuery(`s=${{x}}`)])),
  links: Object.fromEntries(ids.map((id) => {{ const hit = r.resolve(r.route("settings", "", `s=${{id}}`));
    return [id, {{ page: hit.page?.id || null, query: hit.query, redirect: hit.redirect || null }}]; }})),
  old: r.resolve("#/einstellungen?s=web").redirect }}));
""")
        self.assertEqual(out["ids"], ["quellen", "lan", "gps", "ptp", "zugang", "sichern"])
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue(target in out["ids"] or target in legacy, f"?s={target} hat keinen Reiter")
        for target, tab in legacy.items():
            self.assertEqual(out["tabs"][target], tab, target)
        for tab_id, hit in out["links"].items():
            with self.subTest(tab=tab_id):
                self.assertEqual(hit, {"page": "settings", "query": f"s={tab_id}", "redirect": None})
        self.assertEqual(out["old"], "#/system/einstellungen?s=web")

    def test_server_ziele_der_benachrichtigungen(self):
        import notify
        pages = sorted(set(notify.KIND_PAGES.values()))
        out = run_node(f"""
const r = await import({mod("routes.js")});
const pages = {json.dumps(pages)};
console.log(JSON.stringify(Object.fromEntries(pages.map((p) => {{ const x = r.resolve(`#/${{p}}`);
  return [p, {{ redirect: x.redirect || null, page: x.page?.id || null }}]; }}))));
""")
        for path, hit in out.items():
            with self.subTest(path=path):
                self.assertIsNone(hit["redirect"], f"#/{path} ist eine alte Route")
                self.assertNotEqual(hit["page"], "overview", f"#/{path} landet nur auf der Übersicht")
        self.assertEqual(notify.KIND_PAGES["service"], "system/diagnose")
        self.assertEqual(notify.KIND_PAGES["pi"], "uhr/hardware")


class FusszeileUndHilfeTest(unittest.TestCase):
    def test_fusszeile_ohne_api_links_hilfe_mit(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        footer = html[html.index('<footer'):html.index('</footer>')]
        for href in ("/metrics", "/api/status", "/healthz"):
            self.assertNotIn(href, footer)
        help_page = (JS / "pages" / "help.js").read_text(encoding="utf-8")
        for href in ("/metrics", "/api/status", "/healthz"):
            self.assertIn(f'"{href}"', help_page)
        self.assertIn('t("help.api.title")', help_page)
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))
        self.assertEqual(de["help"]["api"]["title"], "API & Automatisierung")

    def test_untere_leiste_und_kurzer_titel(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="bottombar"', html)
        self.assertIn('data-i18n="app.title_short">NTP-GUI<', html)
        self.assertIn("env(safe-area-inset-bottom", css)
        self.assertNotIn(" style=", html)

    def test_abstand_der_unteren_leiste_nicht_auf_clock_und_speicherleiste_darueber(self):
        # Prüfung im Browser: tests/ui/tour.js (navChecks). Hier nur die Regeln im Handy-Block, in dem die
        # untere Leiste entsteht: /clock lädt app.css mit und darf keinen 60-px-Streifen bekommen; die
        # klebende Speicherleiste der Einstellungen muss über der Leiste (57 px) kleben, nicht dahinter.
        css = (STATIC / "app.css").read_text(encoding="utf-8")
        start = css.index(".bottombar { display: grid;")
        block = css[css.rindex("@media (max-width: 640px) {", 0, start):]
        block = block[:block.index("\n}\n")]
        self.assertNotRegex(block, r"(?m)^\s*body\s*\{[^}]*padding-bottom")
        self.assertRegex(block, r"body:not\(\.clock-page\)\s*\{\s*padding-bottom: calc\(60px")
        bottom = re.search(r"\.save-bar\s*\{\s*bottom: calc\((\d+)px \+ env\(safe-area-inset-bottom", block)
        self.assertIsNotNone(bottom)
        self.assertGreaterEqual(int(bottom.group(1)), 57)

    def test_englisch_bleibt_beta_und_neue_texte_uebersetzt(self):
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))
        en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
        self.assertIn("Beta", en["app"]["language_title"])
        for key in ("uhr", "system"):
            self.assertIn(key, de["nav"])
            self.assertIn(key, en["nav"])
        for key in ("more", "ptp_off", "title_short"):
            self.assertIn(key, en["app"])
        self.assertEqual(set(de["app"]["shortcuts"]), set(en["app"]["shortcuts"]))


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TastenkuerzelTest(unittest.TestCase):
    SCRIPT = """
const s = await import(%(module)s);
let clock = 1000;
const calls = [];
const handler = s.createShortcuts({
  go: (id) => calls.push(`go:${id}`),
  search: () => { calls.push("search"); return hasSearch; },
  help: () => calls.push("help"),
}, () => clock);
let hasSearch = true;
const body = { tagName: "BODY" };
const ev = (key, target = body, extra = {}) => { const e = { key, target, defaultPrevented: false, prevented: false,
  preventDefault() { this.prevented = true; }, ...extra }; return e; };
const press = (...keys) => keys.map((k) => { const e = typeof k === "string" ? ev(k) : k; const r = handler(e); return [r, e.prevented]; });
const out = {};
out.goKeys = s.GO_KEYS;
out.go = Object.fromEntries(Object.keys(s.GO_KEYS).map((k) => [k, press("g", k)[1]]));
out.slash = press("/")[0][0];
hasSearch = false;
out.slashNone = press("/")[0][0];
hasSearch = true;
out.question = press("?")[0][0];
const input = { tagName: "INPUT", type: "search" };
const textarea = { tagName: "TEXTAREA" };
const select = { tagName: "SELECT" };
const editable = { tagName: "DIV", isContentEditable: true };
const checkbox = { tagName: "INPUT", type: "checkbox" };
out.inInput = press(ev("g", input), ev("o", input), ev("/", input), ev("?", input));
out.inTextarea = press(ev("g", textarea), ev("o", textarea), ev("?", textarea));
out.inSelect = press(ev("?", select));
out.inEditable = press(ev("g", editable), ev("s", editable));
out.mixed = press(ev("g", input), ev("o"));
out.onCheckbox = press(ev("?", checkbox));
out.modifiers = press(ev("?", body, { ctrlKey: true }), ev("g", body, { altKey: true }), ev("o"),
  ev("g"), ev("o", body, { metaKey: true }), ev("/", body, { ctrlKey: true }));
out.timeout = (() => { const a = handler(ev("g")); clock += s.SEQUENCE_MS + 1; return [a, handler(ev("o"))]; })();
out.composing = handler(ev("?", body, { isComposing: true }));
out.prevented = handler(ev("?", body, { defaultPrevented: true }));
out.unknownSecond = press("g", "x", "?").map((x) => x[0]);
out.typing = [input, textarea, select, editable, checkbox, body, null, { tagName: "INPUT" }].map((t) => s.isTypingTarget(t));
out.list = s.shortcutList();
out.calls = calls;
console.log(JSON.stringify(out));
"""

    @classmethod
    def setUpClass(cls):
        cls.out = run_node(cls.SCRIPT % {"module": mod("shortcuts.js")})

    def test_g_folgen(self):
        self.assertEqual(self.out["goKeys"], {"o": "overview", "s": "sources", "g": "gps", "c": "clients", "u": "uhr", "y": "system"})
        for key, (result, prevented) in self.out["go"].items():
            with self.subTest(key=key):
                self.assertEqual(result, f"go:{self.out['goKeys'][key]}")
                self.assertTrue(prevented)

    def test_suche_und_uebersicht(self):
        self.assertEqual(self.out["slash"], "search")
        self.assertIsNone(self.out["slashNone"], "ohne Suchfeld: nichts tun, Taste nicht schlucken")
        self.assertEqual(self.out["question"], "help")

    def test_eingabefelder_werden_ignoriert(self):
        for name in ("inInput", "inTextarea", "inSelect", "inEditable"):
            with self.subTest(field=name):
                self.assertTrue(all(result is None and not prevented for result, prevented in self.out[name]), self.out[name])
        # „g“ im Feld, „o“ danach außerhalb: keine angefangene Folge aus dem Feld.
        self.assertEqual(self.out["mixed"][1][0], None)
        self.assertEqual(self.out["onCheckbox"][0][0], "help", "Kästchen nehmen keine Buchstaben auf")
        self.assertEqual(self.out["typing"], [True, True, True, True, False, False, False, True])

    def test_nie_mit_strg_alt_meta(self):
        results = [r for r, _p in self.out["modifiers"]]
        self.assertEqual(results, [None, None, None, "pending", None, None])
        self.assertFalse(any(p for _r, p in self.out["modifiers"]))
        self.assertIsNone(self.out["composing"])
        self.assertIsNone(self.out["prevented"])

    def test_folge_verfaellt(self):
        self.assertEqual(self.out["timeout"], ["pending", None])
        self.assertEqual(self.out["unknownSecond"], ["pending", None, "help"])

    def test_aufrufe_und_liste(self):
        self.assertEqual(self.out["calls"].count("help"), 3)
        keys = [" ".join(k) for k, _label in self.out["list"]]
        self.assertEqual(keys, ["g o", "g s", "g g", "g c", "g u", "g y", "/", "?"])

    def test_app_haengt_handler_an(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn("createShortcuts(", app)
        self.assertRegex(app, r'document\.addEventListener\("keydown", \(event\) => \{\n  if \(shortcutDialog\?\.open')


if __name__ == "__main__":
    unittest.main()
