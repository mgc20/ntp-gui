"""Hilfe mit Inhaltsverzeichnis, Unterseiten und tiefen Links (1.11).

  * helpnav.js im echten JS-Interpreter: jedes Thema hat eine eindeutige, kurze Adresse, steht genau einmal im
    Inhaltsverzeichnis, jeder Hilfe-Schlüssel hat eine Unterseite, tiefe Links #/hilfe/<thema>/<schlüssel>, alte
    Links #/hilfe?t=<schlüssel>, unbekannte Themen, Suche, vorheriges/nächstes Thema, Verweis je Seite.
  * routes.js: #/hilfe/<thema>/<schlüssel> landet ohne Weiterleitung auf der Hilfe, mit Unterpfad.
  * ⓘ-Popover und Seiten verlinken tief (kein #/hilfe?t= mehr im Code), die Suche bleibt erhalten.
  * Neue Hilfeabschnitte dieses Releases: Betrieb und Überwachung (Zeitwächter-Ping, /readyz,
    Betriebsmetriken, Fehlersuche als Verweis), SMPTE ST 2059-2 unter PTP.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"


def mod(path: str) -> str:
    return json.dumps((JS / path).resolve().as_uri())


def run_node(body: str):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "run.mjs"
        script.write_text(body, encoding="utf-8")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class HilfeNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = run_node(f"""
const n = await import({mod("helpnav.js")});
const h = await import({mod("help.js")});
const r = await import({mod("routes.js")});
const view = (sub, query) => {{
  const v = n.resolveHelp(sub, query);
  return {{ view: v.view, topic: v.topic ? v.topic.id : null, focus: v.focus ?? null, notFound: Boolean(v.notFound), missing: Boolean(v.missing) }};
}};
const route = (hash) => {{ const x = r.resolve(hash); return {{ redirect: x.redirect || null, page: x.page?.id || null, sub: x.sub ?? null, query: x.query ?? null }}; }};
console.log(JSON.stringify({{
  groups: h.HELP_GROUPS.map((g) => ({{ id: g.id ?? null, title: g.title, keys: g.keys, see: g.see || [] }})),
  help: Object.keys(h.HELP),
  sections: n.HELP_SECTIONS,
  topics: n.TOPICS.map((t) => t.id),
  hrefs: Object.fromEntries(Object.keys(h.HELP).map((k) => [k, n.helpHref(k)])),
  unknownHref: n.helpHref("gibtsnicht"), protoHref: n.helpHref("toString"),
  topicHref: [n.topicHref("gps"), n.topicHref("GPS"), n.topicHref("gibtsnicht")],
  views: {{
    index: view("", ""), legacy: view("", "t=pps"), legacyUnknown: view("", "t=gibtsnicht"), topic: view("gps", ""),
    deep: view("gps/pps", ""), deepWrongTopic: view("ptp/pps", ""), keyAsTopic: view("readyz", ""), unknown: view("gibtsnicht", ""),
    upper: view("GPS/pps", ""), topicLegacy: view("gps", "t=pps"), proto: view("constructor", ""), trailing: view("betrieb/", ""),
    moved: view("benachrichtigungen/heartbeat", ""), unknownKey: view("gps/ppss", ""), protoKey: view("gps/__proto__", ""),
    ctorKey: view("gps/constructor", ""), topicLegacyUnknown: view("gps", "t=gibtsnicht"),
  }},
  routes: {{ deep: route("#/hilfe/gps/pps"), topic: route("#/hilfe/betrieb"), legacy: route("#/hilfe?t=pps"), plain: route("#/hilfe") }},
  neighbours: {{ first: n.neighbours(n.TOPICS[0].id), last: n.neighbours(n.TOPICS[n.TOPICS.length - 1].id), gps: n.neighbours("gps") }},
  pages: Object.fromEntries(r.PAGES.map((p) => [p.id, n.pageTopic(p.id)?.id ?? null])),
  search: n.searchHelp("Falseticker").map((x) => [x.topic.id, x.keys]),
  searchEmpty: n.searchHelp("   "), searchNone: n.searchHelp("xyzzy-gibt-es-nicht"),
  // Wie util.rich(): Was nach dem Zerlegen noch ** oder ` enthält, stünde roh auf der Seite.
  raw: Object.entries(h.HELP).filter(([, v]) => String(v.text).split(/(\\*\\*[^*]+\\*\\*|`[^`]+`)/g)
    .some((part) => !/^(\\*\\*[^*]+\\*\\*|`[^`]+`)$/.test(part) && /\\*\\*|`/.test(part))).map(([k]) => k),
}}));
""")

    def test_jedes_thema_hat_eindeutige_kurze_adresse(self):
        ids = [g["id"] for g in self.data["groups"]]
        self.assertNotIn(None, ids, "jede Gruppe in HELP_GROUPS braucht eine id")
        self.assertEqual(len(ids), len(set(ids)))
        for topic_id in ids:
            self.assertRegex(topic_id, r"^[a-z][a-z0-9-]{1,23}$")

    def test_inhaltsverzeichnis_nennt_jedes_thema_genau_einmal(self):
        listed = [t for s in self.data["sections"] for t in s["topics"]]
        self.assertEqual(sorted(listed), sorted(g["id"] for g in self.data["groups"]))
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(self.data["topics"], listed)

    def test_jeder_schluessel_hat_einen_tiefen_link(self):
        topics = {g["id"]: g["keys"] for g in self.data["groups"]}
        for key, href in self.data["hrefs"].items():
            with self.subTest(key=key):
                match = re.fullmatch(r"#/hilfe/([a-z0-9-]+)/([a-z0-9_]+)", href)
                self.assertIsNotNone(match, href)
                self.assertEqual(match.group(2), key)
                self.assertIn(key, topics[match.group(1)])
        self.assertEqual(self.data["unknownHref"], "#/hilfe")
        self.assertEqual(self.data["protoHref"], "#/hilfe")
        self.assertEqual(self.data["topicHref"], ["#/hilfe/gps", "#/hilfe/gps", "#/hilfe"])

    def test_siehe_auch_zeigt_auf_vorhandene_eintraege(self):
        help_keys = set(self.data["help"])
        for group in self.data["groups"]:
            for key in group["see"]:
                with self.subTest(group=group["id"], key=key):
                    self.assertIn(key, help_keys)
                    self.assertNotIn(key, group["keys"], "Verweis auf einen Eintrag derselben Seite")

    def test_ansichten(self):
        v = self.data["views"]
        self.assertEqual(v["index"], {"view": "index", "topic": None, "focus": None, "notFound": False, "missing": False})
        self.assertEqual(v["legacy"], {"view": "topic", "topic": "gps", "focus": "pps", "notFound": False, "missing": False})
        self.assertEqual(v["legacyUnknown"]["view"], "index")
        self.assertTrue(v["legacyUnknown"]["notFound"])
        self.assertEqual(v["topic"], {"view": "topic", "topic": "gps", "focus": None, "notFound": False, "missing": False})
        self.assertEqual(v["deep"], {"view": "topic", "topic": "gps", "focus": "pps", "notFound": False, "missing": False})
        self.assertEqual(v["upper"], v["deep"])
        self.assertEqual(v["topicLegacy"], v["deep"])
        self.assertEqual(v["trailing"]["topic"], "betrieb")
        # Ein Schlüssel unter einem fremden Thema (älterer oder geteilter Link) führt auf die Unterseite seines Themas.
        self.assertEqual(v["deepWrongTopic"], v["deep"])
        self.assertEqual(v["moved"], {"view": "topic", "topic": "betrieb", "focus": "heartbeat", "notFound": False, "missing": False})
        self.assertEqual(v["keyAsTopic"], {"view": "topic", "topic": "betrieb", "focus": "readyz", "notFound": False, "missing": False})
        # Ein unbekannter Eintrag: die Unterseite des Themas mit Hinweis, nichts hervorgehoben.
        for name in ("unknownKey", "protoKey", "ctorKey", "topicLegacyUnknown"):
            self.assertEqual(v[name], {"view": "topic", "topic": "gps", "focus": None, "notFound": False, "missing": True}, name)
        for name in ("index", "legacy", "topic", "deep", "trailing"):
            self.assertFalse(v[name]["missing"], name)
        for name in ("unknown", "proto"):
            self.assertEqual(v[name], {"view": "index", "topic": None, "focus": None, "notFound": True, "missing": False}, name)

    def test_routen_ohne_weiterleitung(self):
        routes = self.data["routes"]
        self.assertEqual(routes["deep"], {"redirect": None, "page": "help", "sub": "gps/pps", "query": ""})
        self.assertEqual(routes["topic"], {"redirect": None, "page": "help", "sub": "betrieb", "query": ""})
        self.assertEqual(routes["legacy"], {"redirect": None, "page": "help", "sub": "", "query": "t=pps"})
        self.assertEqual(routes["plain"]["page"], "help")

    def test_vorheriges_und_naechstes_thema(self):
        nb = self.data["neighbours"]
        self.assertIsNone(nb["first"]["prev"])
        self.assertIsNotNone(nb["first"]["next"])
        self.assertIsNone(nb["last"]["next"])
        topics = self.data["topics"]
        at = topics.index("gps")
        self.assertEqual(nb["gps"]["prev"]["id"], topics[at - 1])
        self.assertEqual(nb["gps"]["next"]["id"], topics[at + 1])

    def test_verweis_je_seite(self):
        pages = self.data["pages"]
        for page in ("overview", "sources", "gps", "clients", "clockquality", "hardware", "ptp", "diagnose", "notify"):
            self.assertIsNotNone(pages[page], page)
        self.assertEqual(pages["gps"], "gps")
        self.assertEqual(pages["ptp"], "ptp")
        for page in ("help", "setup", "muster", "settings"):
            self.assertIsNone(pages[page], page)

    def test_suche_ueber_alle_themen_ohne_doppelte(self):
        found = self.data["search"]
        self.assertTrue(found)
        keys = [k for _topic, ks in found for k in ks]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("state_falseticker", keys)
        self.assertEqual(self.data["searchEmpty"], [])
        self.assertEqual(self.data["searchNone"], [])

    def test_hervorhebungen_ohne_rohe_zeichen(self):
        self.assertEqual(self.data["raw"], [], "**…** bzw. `…` in diesen Texten wird nicht formatiert")

    def test_neue_abschnitte_dieses_releases(self):
        groups = {g["id"]: g for g in self.data["groups"]}
        betrieb = groups["betrieb"]
        for key in ("ops_overview", "heartbeat", "heartbeat_mode", "heartbeat_status", "readyz", "metrics_ops"):
            self.assertIn(key, betrieb["keys"])
        self.assertIn("troubleshoot", betrieb["see"])
        self.assertIn("ptp_st2059", groups["ptp"]["keys"])
        self.assertEqual(self.data["hrefs"]["troubleshoot"], "#/hilfe/client-uhren/troubleshoot")
        # Der Zeitwächter-Ping steht nur noch unter Betrieb; Benachrichtigungen verweisen dorthin.
        self.assertNotIn("heartbeat", groups["benachrichtigungen"]["keys"])
        self.assertIn("heartbeat", groups["benachrichtigungen"]["see"])


class HilfeQuelltextTest(unittest.TestCase):
    def test_keine_alten_hilfelinks_im_code(self):
        found = []
        for path in sorted(JS.rglob("*.js")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("//"):
                    continue
                if "#/hilfe?t=" in line:
                    found.append(f"{path.name}:{number}")
        self.assertEqual(found, [], "Links auf die Hilfe über helpHref() bauen")

    def test_popover_verlinkt_tief(self):
        ui = (JS / "ui.js").read_text(encoding="utf-8")
        self.assertIn('href: helpHref(key), class: "popover-more"', ui)
        self.assertIn('tr("help.more")', ui)

    def test_suche_bleibt_erhalten(self):
        page = (JS / "pages" / "help.js").read_text(encoding="utf-8")
        self.assertIn('type: "search"', page)
        self.assertIn("searchHelp(", page)
        self.assertIn("ctx.uiState.helpQuery", page)

    def test_seitenverweis_in_app(self):
        app = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn("pageHelpLink(page.id)", app)

    def test_bereitschaft_im_einstellungsfeld_verlinkt(self):
        settings = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('ready_max_error_ms: "readyz"', settings)

    def test_i18n_schluessel_in_beiden_sprachen(self):
        de = json.loads((STATIC / "i18n" / "de.json").read_text(encoding="utf-8"))["help"]
        en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))["help"]
        for key in ("toc_title", "all_topics", "see_also", "more", "page_more", "search_placeholder", "search_label",
                    "nothing_found", "not_found", "prev", "next", "entry_link", "entries_one", "entries_other"):
            with self.subTest(key=key):
                self.assertIn(key, de)
                self.assertIn(key, en)
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", de[key])), sorted(re.findall(r"\{(\w+)\}", en[key])))


if __name__ == "__main__":
    unittest.main()
