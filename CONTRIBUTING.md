# Mitmachen

Schön, dass du ntp-gui besser machen willst! Jeder Beitrag hilft – auch ohne eine Zeile Code.

## Ohne Programmieren

- **Erfahrungsbericht zur Hardware:** Öffne im Dashboard die Seite **Hardware** und teile
  das Ergebnis über das Issue-Formular „Hardware-Bericht“. Daraus entsteht die
  Kompatibilitätsliste (welcher GPS-Empfänger, welche Netzwerkkarte, welcher Pi funktioniert
  wie gut). Bitte keine Koordinaten, Seriennummern oder öffentlichen IP-Adressen einfügen.
- **Fehler melden:** Formular „Fehlerbericht“. Je genauer, desto besser: Version, Hardware,
  Compose-Ausschnitt, was du erwartet hast und was passiert ist. Am meisten hilft ein
  **Diagnosepaket** (Seite **Diagnose** → Vorschau → Herunterladen): Es ist bereits gefiltert –
  ohne Standort, Seriennummern, MAC- und öffentliche IP-Adressen. Schau dir die Vorschau an,
  bevor du es anhängst.
- **Erklärungen verbessern:** Ist ein ⓘ-Text unklar oder falsch? Ein Issue oder ein kleiner
  Pull Request an `app/static/js/help.js` reicht.
- **Übersetzen:** Siehe [Übersetzen](#übersetzen) unten – Englisch zuerst, weitere Sprachen
  gern.
- **Ideen:** Formular „Idee“. Die geplanten Themen stehen in [ROADMAP.md](ROADMAP.md).

## Mit Code

```bash
python3 -m unittest discover -s tests -v   # Unittests (ohne laufenden chronyd)
docker build -t ntp-gui:test .
tests/container-test.sh ntp-gui:test       # Integrationstest gegen das gebaute Image
```

Grundregeln:

- **Keine neuen Abhängigkeiten.** Das Dashboard nutzt nur die Python-Standardbibliothek
  und Vanilla-JavaScript ohne Build-Schritt.
- **Jeder angezeigte Wert bekommt eine Erklärung** (ⓘ mit einem Eintrag in `help.js` oder
  einem eigenen `help-*.js`-Modul, das `help.js` einbindet). `tests/test_help_coverage.py`
  prüft das.
- **Oberfläche auf Deutsch**, in der Du-Form, konkret und mit dem „Warum“.
- **Sicherheit:** Jeder Wert, der in eine Konfigurationsdatei gelangt, wird gegen eine
  Positivliste geprüft. Im Frontend nur `textContent`, nie `innerHTML` mit fremden Daten.
- **Datenschutz:** Was die Instanz verlässt, darf keinen Standort verraten (keine
  Koordinaten, Satellitenwinkel, Seriennummern, MAC- oder öffentlichen IP-Adressen). Jeder
  Export läuft durch `app/egress.py` (`sanitize`/`sanitize_text`) und zum Schluss durch
  `egress.check_no_leaks` – findet die Prüfung etwas, wird nichts exportiert. Vor jedem Export
  gibt es eine Vorschau, hochgeladen wird nie automatisch.
- **Tests:** Neue Funktionen bringen Tests mit; die CI muss grün sein.

Pull Requests bitte gegen `main`. Kleine, fokussierte Änderungen lassen sich am schnellsten
prüfen.

## Übersetzen

Seit 1.5.0 gibt es ein Gerüst für mehrere Sprachen. **Deutsch ist die Referenz**, Englisch darf
hinterherhinken: Fehlt ein englischer Text, zeigt das Dashboard den deutschen – nie einen leeren
Platz oder einen rohen Schlüssel. Die Sprache wählt jeder Betrachter selbst (Knopf „DE/EN“ oben
rechts oder **Einstellungen → Dashboard**); gespeichert wird sie nur im Browser. Ohne Wahl gilt die
Sprache des Browsers.

**Wo die Texte liegen:** `app/static/i18n/<sprache>.json`, z. B. `de.json` und `en.json`. Das
Format ist verschachteltes JSON im Stil von **i18next v4** – in Weblate die Dateiformat-Wahl
„i18next JSON file v4“, Ausgangssprache `de`, Dateimaske `app/static/i18n/*.json`:

```json
{
  "nav": { "overview": "Übersicht" },
  "overview": {
    "facts": {
      "clients_one": "{n} Client",
      "clients_other": "{n} Clients"
    }
  }
}
```

- **Schlüssel** sind klein, mit Punkt als Pfad (`overview.facts.clients`) und nach Bereichen
  geordnet (`app`, `nav`, `overview`, `settings`, `help`).
- **Platzhalter** in geschweiften Klammern (`{n}`, `{title}`) werden beim Anzeigen ersetzt und
  müssen in jeder Sprache dieselben sein.
- **Mehrzahl** über die Endungen `_one`/`_other` (weitere Formen wie `_few` nach den Regeln der
  Sprache, `Intl.PluralRules`). Der Code übergibt die Anzahl als `count`.
- **Nur Text**, kein HTML: Alles landet per `textContent` im Dashboard.

**Im Code:** `import { t } from "./i18n.js"` und `t("nav.overview")` bzw.
`t("overview.facts.clients", { count, n: fmtNumber(count) })`. Feste Texte in `index.html`
bekommen `data-i18n="schlüssel"` (bzw. `data-i18n-title`, `data-i18n-aria-label`). Neue Seiten
und neue Texte bitte gleich als Schlüssel anlegen – erst in `de.json`, dann, wenn du kannst, in
`en.json`.

**Prüfen:** `tests/test_i18n.py` schlägt fehl, wenn ein benutzter Schlüssel in `de.json` fehlt, wenn
`en.json` Schlüssel kennt, die es in `de.json` nicht gibt, oder wenn Platzhalter abweichen.
Fehlende englische Texte sind **kein** Fehler; die Liste zeigt

```bash
python3 tests/test_i18n.py --report
```

**Stand und Grenzen (1.5.0):** Übersetzt sind Navigation, Kopfzeile, das Statusband der Übersicht
und die Abschnittstitel der Einstellungen. Die ⓘ-Erklärungen (`help.js`, `help-*.js`) bleiben
vorerst deutsch – `tests/test_help_coverage.py` prüft weiterhin die deutsche Referenz –, ebenso
Texte vom Server (Hinweise, Ereignisse, Benachrichtigungen) und das Zahlenformat. Diese Teile
folgen schrittweise in 1.5.x.

## Verhalten

Freundlich, sachlich, hilfsbereit. Wir sind hier, um gemeinsam bessere Zeit ins Heimnetz zu
bringen.
