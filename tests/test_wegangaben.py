"""Wegangaben in Bedientexten (1.6): „Einstellungen → X“ nennt nur Reiter, die es wirklich gibt.

Seit 1.6 liegen die Einstellungen unter System → Einstellungen und sind in Reiter geteilt
(pages/settings.js TABS: Quellen, LAN-Server, GPS, PTP, Dashboard & Zugang, Sichern). Texte, die noch
Abschnitte der alten Seite nennen („Einstellungen → Dashboard“, „Einstellungen → NTS“,
„Einstellungen → Zeitquellen, erweitert“ …), schicken Nutzer ins Leere. Geprüft wird jede Datei unter
app/ – Python-Texte vom Server, JS-Seiten und Hilfen, i18n-Kataloge:

  * Nach „Einstellungen →“ bzw. „Settings →“ folgt der Name eines Reiters in derselben Sprache.
  * Davor steht „System →“ – die Einstellungen sind ein Reiter der Gruppe System.
  * Nach „System →“ bzw. „Uhr & Hardware →“ folgt ein Reiter dieser Gruppe (routes.js PAGES).

Ausgenommen sind Menüpfade fremder Geräte (AdGuard, Pi-hole, UniFi) und Link-Pfeile am Textende
(„Zu den Einstellungen →“). Über Zeilen zerlegte Texte ("… → " + "…") werden vorher zusammengefügt.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STATIC = APP / "static"
CATALOGS = {"de": STATIC / "i18n" / "de.json", "en": STATIC / "i18n" / "en.json"}
SETTINGS_WORD = {"de": "Einstellungen", "en": "Settings"}

# Menüpfade fremder Geräte, die mit „Einstellungen →“ beginnen (kein Reiter von ntp-gui).
FOREIGN = ("Client-Einstellungen",   # AdGuard Home
           "All settings",           # Pi-hole v6
           "Policy Table",           # UniFi Network 9.4+
           "Policy Engine",          # UniFi Network 9.3
           "Netzwerke")              # UniFi (DHCP-Beispiel auf der Clients-Seite)

ARROW = r"\s*→\s*"
# Zeilenweise zerlegte Zeichenketten: "…" + "…" (JS) bzw. "…" "…" (Python) bzw. `…` + `…`.
JOIN = re.compile(r"[\"'`]\s*\+?\s*\n\s*\+?\s*f?[\"'`]")


def _lookup(catalog: dict, key: str) -> str:
    node = catalog
    for part in key.split("."):
        node = node[part]
    return node


def _catalogs() -> dict:
    return {lang: json.loads(path.read_text(encoding="utf-8")) for lang, path in CATALOGS.items()}


def settings_tabs() -> dict:
    """Reiternamen der Einstellungen je Sprache, aus pages/settings.js TABS und den Katalogen."""
    source = (STATIC / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    block = re.search(r"export const TABS = \[(.*?)\];", source, re.S)
    keys = re.findall(r'titleKey:\s*"([^"]+)"', block.group(1))
    cats = _catalogs()
    return {lang: [_lookup(cats[lang], key) for key in keys] for lang in cats}


def group_tabs() -> dict:
    """Gruppen mit Reitern (routes.js): {Sprache: {Gruppenname: [Reiternamen]}}."""
    source = (STATIC / "js" / "routes.js").read_text(encoding="utf-8")
    nav = re.findall(r'\{ id: "(\w+)",[^}]*titleKey: "([^"]+)"[^}]*group: true', source)
    pages = re.findall(r'nav: "(\w+)", tab: true, titleKey: "([^"]+)"', source)
    cats = _catalogs()
    out = {}
    for lang, cat in cats.items():
        out[lang] = {_lookup(cat, key): [_lookup(cat, tkey) for gid, tkey in pages if gid == nav_id]
                     for nav_id, key in nav}
    return out


def _starts_with_name(rest: str, names) -> bool:
    for name in names:
        if rest.startswith(name):
            after = rest[len(name):len(name) + 1]
            if not after or not (after.isalnum() or after in "-_"):
                return True
    return False


def check_text(text: str, tabs: dict, groups: dict) -> list:
    """Fehlerhafte Wegangaben in einem Text (nach dem Zusammenfügen zerlegter Zeichenketten)."""
    text = JOIN.sub("", text)
    problems = []
    for lang, word in SETTINGS_WORD.items():
        for m in re.finditer(r"(?<![\w-])" + word + ARROW, text):
            rest = text[m.end():m.end() + 80]
            if not rest or rest[0] in "\"'`<)*\n" or rest.startswith("\\n"):
                continue  # Link-Pfeil am Textende („Zu den Einstellungen →“)
            if _starts_with_name(rest, FOREIGN):
                continue
            shown = text[max(0, m.start() - 20):m.end() + 40].replace("\n", " ")
            if not _starts_with_name(rest, tabs[lang]):
                problems.append(f"kein Reiter nach „{word} →“: …{shown}…")
            elif not re.search("System" + ARROW + r"$", text[max(0, m.start() - 12):m.start()]):
                problems.append(f"„System →“ fehlt vor „{word} →“: …{shown}…")
    # Gruppenname → Reiter in allen Sprachen („System“ heißt in beiden Katalogen gleich).
    merged = {}
    for by_group in groups.values():
        for group, names in by_group.items():
            merged.setdefault(group, set()).update(names)
    for group, names in merged.items():
        for m in re.finditer(r"(?<![\w-])" + re.escape(group) + ARROW, text):
            rest = text[m.end():m.end() + 80]
            if not rest or rest[0] in "\"'`<)\n":
                continue
            if not _starts_with_name(rest, sorted(names, key=len, reverse=True)):
                    shown = text[max(0, m.start() - 20):m.end() + 40].replace("\n", " ")
                    problems.append(f"kein Reiter nach „{group} →“: …{shown}…")
    return problems


def settings_sections() -> dict:
    """Abschnitte (Karten) je Reiter der Einstellungen (de): {Reitername: [Abschnitt-ids]}."""
    source = (STATIC / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    block = re.search(r"export const TABS = \[(.*?)\];", source, re.S).group(1)
    cat = _catalogs()["de"]
    return {_lookup(cat, key): re.findall(r'"(\w+)"', sections)
            for key, sections in re.findall(r'titleKey:\s*"([^"]+)",\s*sections:\s*\[([^\]]*)\]', block)}


def check_field_paths(text: str, tab_sections: dict, section_titles: dict, fields: dict) -> list:
    """Wege bis zu einem Feld („Reiter → [„Karte“ →] [Erweitert →] „Feld““) gegen das Schema prüfen.

    „Erweitert“ steht genau dann im Weg, wenn das Feld advanced ist. Zeigt ein Reiter mehrere Karten,
    hat jede ihren eigenen Knopf „Erweitert“ – dann muss die Karte genannt sein. Eine genannte Karte
    muss die des Feldes sein. fields: {Feldname: (Abschnitt-id, advanced)}.
    """
    text = JOIN.sub("", text)
    tabs = "|".join(re.escape(name) for name in sorted(tab_sections, key=len, reverse=True))
    pattern = re.compile(r"Einstellungen" + ARROW + "(" + tabs + ")" + ARROW
                         + r"(?:„([^“]+)“" + ARROW + r")?(Erweitert" + ARROW + r")?„([^“]+)“")
    titles = {title: sid for sid, title in section_titles.items()}
    problems = []
    for m in pattern.finditer(text):
        tab, card, advanced, label = m.groups()
        if card and card in fields and not advanced:   # „Reiter → „Feld““ ohne Karte
            continue
        if label not in fields:
            continue
        section, is_advanced = fields[label]
        shown = m.group(0)
        if section not in tab_sections[tab]:
            problems.append(f"Feld liegt nicht im Reiter „{tab}“: {shown}")
        if bool(advanced) != is_advanced:
            problems.append(("„Erweitert“ im Weg, Feld ist aber kein erweitertes" if advanced
                             else "„Erweitert“ fehlt im Weg") + f": {shown}")
        if card is not None and titles.get(card) != section:
            problems.append(f"falsche Karte „{card}“: {shown}")
        if card is None and advanced and len(tab_sections[tab]) > 1:
            problems.append(f"Karte fehlt (Reiter mit mehreren „Erweitert“-Knöpfen): {shown}")
    return problems


def app_files():
    for path in sorted(APP.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".js", ".json", ".html", ".css", ".txt", ".md"}:
            yield path


class WegangabenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tabs = settings_tabs()
        cls.groups = group_tabs()

    def test_reiternamen_gelesen(self):
        self.assertIn("Dashboard & Zugang", self.tabs["de"])
        self.assertIn("Quellen", self.tabs["de"])
        self.assertIn("Dashboard & access", self.tabs["en"])
        self.assertIn("Benachrichtigungen", self.groups["de"]["System"])
        self.assertIn("Einstellungen", self.groups["de"]["System"])
        self.assertIn("Settings", self.groups["en"]["System"])

    def test_jede_wegangabe_nennt_einen_echten_reiter(self):
        problems = []
        for path in app_files():
            text = path.read_text(encoding="utf-8")
            for problem in check_text(text, self.tabs, self.groups):
                problems.append(f"{path.relative_to(ROOT)}: {problem}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_pruefung_erkennt_alte_wege(self):
        bad = [
            "Passwort unter Einstellungen → Dashboard setzen.",
            "(Einstellungen → NTS → „NTS-Server für das LAN anbieten“)",
            "Standard ist … (Einstellungen → Zeitquellen, erweitert).",
            "prüfe unter Einstellungen → Benachrichtigungen",
            'Rückgängig: Einstellungen → "\n    "Dashboard → „Vertrauenswürdige Proxys“.',
            "API key (Settings → Dashboard → API keys)",
            "unter Einstellungen → Quellen ohne Gruppe",
            "unter System → Werkzeuge",
        ]
        for text in bad:
            with self.subTest(text=text):
                self.assertTrue(check_text(text, self.tabs, self.groups), text)

    def test_pruefung_laesst_richtige_und_fremde_wege_durch(self):
        good = [
            "unter System → Einstellungen → Dashboard & Zugang → „Erlaubte Namen“",
            "(System → Einstellungen → Quellen → „NTS (Network Time Security)“ → Erweitert → „NTS-Server für das LAN anbieten“)",
            "Rückgängig: System → \"\n    + \"Einstellungen → Quellen → „DNS für ntp-gui“.",
            "(System → Settings → Dashboard & access → API keys)",
            "System → Einstellungen → LAN-Server",
            "unter System → Benachrichtigungen",
            "Fünf Schritte unter **System → Einrichtung**",
            "Zu den Einstellungen →",
            "Pi-hole v6: Einstellungen → All settings → Miscellaneous",
            "  Einstellungen → Policy Table → Create New Policy → NAT\\n",
            "Alle Quellen-Einstellungen →",
        ]
        for text in good:
            with self.subTest(text=text):
                self.assertEqual(check_text(text, self.tabs, self.groups), [], text)


    def _field_context(self):
        import sys
        sys.path.insert(0, str(APP))
        import settings  # noqa: E402
        titles = {sid: title for sid, title, _ in settings.SECTIONS}
        fields = {f["label"]: (f["section"], bool(f["advanced"])) for f in settings.SCHEMA}
        return settings_sections(), titles, fields

    def test_feldwege_passen_zum_schema(self):
        ctx = self._field_context()
        problems = []
        for path in app_files():
            for problem in check_field_paths(path.read_text(encoding="utf-8"), *ctx):
                problems.append(f"{path.relative_to(ROOT)}: {problem}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_feldwege_pruefung_erkennt_fehler(self):
        ctx = self._field_context()
        bad = [
            "Einstellungen → Dashboard & Zugang → Erweitert → „Erlaubte Namen“",
            "Einstellungen → Quellen → Erweitert → „NTS-Server für das LAN anbieten“",
            "Einstellungen → Quellen → „Zeitquellen (NTP)“ → Erweitert → „NTS-Server für das LAN anbieten“",
            "Einstellungen → Quellen → „NTS (Network Time Security)“ → „NTS-Server für das LAN anbieten“",
        ]
        for text in bad:
            with self.subTest(text=text):
                self.assertTrue(check_field_paths(text, *ctx), text)
        good = [
            "Einstellungen → Dashboard & Zugang → „Erlaubte Namen“",
            "Einstellungen → Quellen → „NTS (Network Time Security)“ → Erweitert → „NTS-Server für das LAN anbieten“",
            "Einstellungen → Quellen → „Zeitquellen (NTP)“ → Erweitert → „Schaltsekunden-Liste“",
        ]
        for text in good:
            with self.subTest(text=text):
                self.assertEqual(check_field_paths(text, *ctx), [], text)


if __name__ == "__main__":
    unittest.main()
