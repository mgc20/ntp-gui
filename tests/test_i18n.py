"""Sprachkataloge (app/static/i18n/*.json) und ihre Verwendung im Dashboard.

Regeln (docs/konzept/version-1.5.md, Thema 13):
  * Deutsch (de) ist die Referenz: Jeder Schlüssel, den das Dashboard benutzt, steht dort – sonst Fehler.
  * Englisch darf hinterherhinken: Fehlende en-Schlüssel sind KEIN Fehler, sondern stehen im
    Abdeckungsbericht (python3 tests/test_i18n.py --report); im Browser gilt dann der deutsche Text.
  * en darf aber nichts enthalten, was es in de nicht gibt, und muss dieselben Platzhalter benutzen.
  * Die ⓘ-Erklärungen bleiben vorerst deutsch und werden weiter von test_help_coverage.py geprüft.
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
I18N = STATIC / "i18n"
JS = STATIC / "js"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401

import settings  # noqa: E402

NAMESPACES = ("app", "nav", "overview", "settings", "help")
KEY_LITERAL = re.compile(r"""["'`]((?:%s)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)["'`]""" % "|".join(NAMESPACES))
HTML_ATTR = re.compile(r'data-i18n(?:-title|-aria-label)?="([^"]+)"')
PLACEHOLDER = re.compile(r"\{(\w+)\}")
PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


def load(lang: str) -> dict:
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def flatten(node, prefix=""):
    """{"a": {"b": "x"}} → {"a.b": "x"}; Nicht-Strings bleiben als Wert stehen (Test meldet sie)."""
    out = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def base_key(key: str) -> str:
    for suffix in PLURAL_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def used_keys() -> list[tuple[str, str]]:
    """(Datei, Schlüssel) für jeden statisch erkennbaren Katalogschlüssel im Dashboard."""
    found = []
    for path in sorted(JS.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        found += [(path.name, m.group(1)) for m in KEY_LITERAL.finditer(text)]
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    found += [("index.html", m.group(1)) for m in HTML_ATTR.finditer(html)]
    # Dynamische Schlüssel der Einstellungsseite: je Abschnitt Titel und Beschreibung.
    found += [("settings.js", f"settings.section.{key}.{part}") for key, _l, _d in settings.SECTIONS
              for part in ("title", "description")]
    return found


def missing_in(catalog: dict, key: str) -> bool:
    return key not in catalog and f"{key}_other" not in catalog


def coverage_report() -> str:
    de, en = flatten(load("de")), flatten(load("en"))
    missing = sorted(k for k in de if k not in en)
    lines = [f"en: {len(de) - len(missing)} von {len(de)} Texten übersetzt ({100 * (len(de) - len(missing)) / max(1, len(de)):.0f} %)"]
    lines += [f"  fehlt: {key}" for key in missing]
    return "\n".join(lines)


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.de = flatten(load("de"))
        cls.en = flatten(load("en"))

    def test_catalogs_are_flat_strings(self):
        for lang, catalog in (("de", self.de), ("en", self.en)):
            for key, value in catalog.items():
                with self.subTest(lang=lang, key=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertRegex(key, r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")

    def test_scanner_sees_usage(self):
        keys = {k for _f, k in used_keys()}
        for key in ("nav.overview", "app.footer", "overview.verdict.good_title", "app.skip_link"):
            self.assertIn(key, keys)

    def test_every_used_key_exists_in_de(self):
        missing = sorted({f"{f} → {k}" for f, k in used_keys() if missing_in(self.de, k)})
        self.assertEqual(missing, [], "Schlüssel fehlen im deutschen Referenzkatalog")

    def test_en_has_nothing_extra(self):
        extra = sorted(set(self.en) - set(self.de))
        self.assertEqual(extra, [], "en kennt Schlüssel, die es in de nicht gibt")

    def test_placeholders_match(self):
        for key, text in self.en.items():
            if key in self.de:
                with self.subTest(key=key):
                    self.assertEqual(set(PLACEHOLDER.findall(text)), set(PLACEHOLDER.findall(self.de[key])))

    def test_plural_forms_complete(self):
        for key in self.de:
            base = base_key(key)
            if base != key:
                with self.subTest(key=key):
                    self.assertIn(f"{base}_other", self.de)

    def test_settings_sections_match_server(self):
        # Deutsch kommt doppelt vor (Server-Schema und Katalog) – beides muss gleich bleiben.
        for key, label, description in settings.SECTIONS:
            with self.subTest(section=key):
                self.assertEqual(self.de[f"settings.section.{key}.title"], label)
                self.assertEqual(self.de[f"settings.section.{key}.description"], description)

    def test_no_markup_in_catalogs(self):
        # Kataloge landen per textContent im DOM; HTML darin wäre ein Zeichen für falsche Nutzung.
        for lang, catalog in (("de", self.de), ("en", self.en)):
            for key, value in catalog.items():
                with self.subTest(lang=lang, key=key):
                    self.assertNotRegex(value, r"<[a-zA-Z/]")

    def test_coverage_report_runs(self):
        report = coverage_report()
        self.assertIn("en:", report)
        if "fehlt:" in report:
            print("\n[i18n] " + report, file=sys.stderr)  # Hinweis, kein Fehler: Englisch darf hinterherhinken


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class RuntimeTest(unittest.TestCase):
    """i18n.js im echten JS-Interpreter: Rückfall auf Deutsch, Plural, Platzhalter."""

    SCRIPT = """
import * as i18n from %(module)s;
const de = { nav: { overview: "Übersicht" }, x: { n_one: "{count} Punkt", n_other: "{count} Punkte" },
  y: { hello: "Hallo {name}" }, only: { de: "nur deutsch" } };
const en = { nav: { overview: "Overview" }, x: { n_one: "{count} item", n_other: "{count} items" },
  y: { hello: "Hello {name}" } };
i18n._setCatalogs({ de, en }, "en");
const out = {
  translated: i18n.t("nav.overview"),
  fallback: i18n.t("only.de"),
  unknown: i18n.t("gibt.es.nicht"),
  one: i18n.t("x.n", { count: 1 }),
  many: i18n.t("x.n", { count: 3 }),
  param: i18n.t("y.hello", { name: "<b>GPS</b>" }),
  missingParam: i18n.t("y.hello"),
  has: i18n.has("only.de"),
  browserEn: i18n.browserLanguage(["en-US", "de-DE"]),
  browserFr: i18n.browserLanguage(["fr-FR"]),
  browserDe: i18n.browserLanguage(["de-AT"]),
};
i18n._setCatalogs({ de, en }, "de");
out.de = i18n.t("nav.overview");
console.log(JSON.stringify(out));
"""

    def test_runtime(self):
        module = json.dumps((JS / "i18n.js").resolve().as_uri())
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "run.mjs"
            script.write_text(self.SCRIPT % {"module": module}, encoding="utf-8")
            result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["translated"], "Overview")
        self.assertEqual(out["fallback"], "nur deutsch")
        self.assertEqual(out["unknown"], "gibt.es.nicht")
        self.assertEqual(out["one"], "1 item")
        self.assertEqual(out["many"], "3 items")
        self.assertEqual(out["param"], "Hello <b>GPS</b>")  # Text, kein HTML – landet per textContent
        self.assertEqual(out["missingParam"], "Hello {name}")
        self.assertTrue(out["has"])
        self.assertEqual((out["browserEn"], out["browserFr"], out["browserDe"]), ("en", "de", "de"))
        self.assertEqual(out["de"], "Übersicht")

    def test_syntax_of_touched_modules(self):
        for name in ("i18n.js", "app.js", "pages/overview.js", "pages/settings.js", "pages/help.js", "help-web.js"):
            with self.subTest(module=name):
                result = subprocess.run(["node", "--check", str(JS / name)], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    if "--report" in sys.argv:
        print(coverage_report())
        sys.exit(0)
    unittest.main()
