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

## Verhalten

Freundlich, sachlich, hilfsbereit. Wir sind hier, um gemeinsam bessere Zeit ins Heimnetz zu
bringen.
