# UI-Rundgang (Playwright)

Werkzeug für Änderungen an der Oberfläche, **kein Teil der Unit-Testsuite**: `python3 -m unittest discover -s tests`
findet hier nichts (kein `test*.py`, kein Paket) und braucht weder Node noch Playwright.

Der Rundgang öffnet jede Route bei 1440 und 390 px, hell und dunkel, und meldet:

- Konsolen- und Seitenfehler sowie Verstöße gegen die Content-Security-Policy,
- verbotene Zahlmuster („1,000 ms“, Punkt als Dezimalzeichen vor s/ms, „12.345 ppb“),
- waagerechte Überbreite,
- ⓘ-Knöpfe, deren 24-px-Tippfläche nicht greift, und Bedienelemente, deren Rand ein ⓘ daneben
  überdeckt (`elementFromPoint` an den Innenrändern jedes Knopfs, Links und Eingabefelds),
- in den Einstellungen: sechs Reiter (je adressierbar per `?s=…`), Höhe jedes Reiters bei 1440 px unter
  2500 px ohne aufgeklappte Erweitert-Bereiche, Suche (`/` fokussiert sie, Treffer springen in den Reiter),
  „nur Geänderte“, Speicherleiste (bei 390 px über der unteren Leiste), Vorschau-Dialog mit Diff (kein loser
  Text, Diff rollt in seinem Kasten statt den Dialog zu verbreitern), die Nachfrage beim Verlassen mit
  ungespeicherten Änderungen, Tastaturfokus nach „Verwerfen“ und „zurücksetzen“, alte Sprungziele
  (`?s=dns`, `?s=api`) auch beim wiederholten Sprung und der Schalter „Nächtliche Sicherung“ im Reiter „Sichern“.

- zuerst der Willkommens-Assistent: Der Testaufbau startet mit leerem Datenverzeichnis (Erststart). Bei 390 und
  1440 px öffnet die Startseite den Assistenten von selbst; alle fünf Schritte per „Weiter“ (Tastatur), je Schritt
  Fokus auf der Überschrift, genau ein `aria-current="step"`, keine Überbreite, keine Tippfläche unter 24 px. Bei
  390 px danach „Später“ – Einstellungen und `setup_done` unverändert, kein zweites automatisches Öffnen; bei
  1440 px eine NTS-Vorlage per Tastatur mit Vorschau (Diff) und „Verwerfen“ (Fokus darf dabei nie auf `<body>`
  fallen), dann „Fertig“ – danach die Checkliste auf der Übersicht, die sich per Tastatur schließen lässt (Fokus
  danach auf dem Hauptinhalt). Einzeln stehende Links zählen bei der 24-px-Prüfung mit; im Schritt Clients wird
  keine Loopback-Adresse zum Kopieren angeboten. In `TOUR_WORDS_ONLY`/`TOUR_PAGES_ONLY` wird der Assistent nur per API abgeschlossen.
- auf der Clients-Seite: bei 390 px Karten statt Tabelle ohne Überbreite, bei 1440 px die Tabelle, Name direkt in
  der Liste (✎ öffnet das Feld, Esc bricht ab, Enter speichert; der Name wird danach wieder entfernt),
- die Uhr-Werkstatt `/clock` (1.6, T6): jedes Design (digital, Bahnhofsuhr, Nixie, Klappzahlen, Wortuhr) mit fester
  Serverzeit (Browseruhr per `page.clock` 5 min daneben, `/api/v1/time` erfunden) zeigt bei 390 und 1440 px, normal und
  im Rotlicht-Modus, die richtige Uhrzeit (DOM: Ziffern, Wortuhr-Satz, Zeigerwinkel und Phase des Sekundenzeigers) samt
  Schaltsekunden-Banner am 30.6.; dazu Kiosk, E-Ink mit zweiter Zeitzone und unzulässige Parameter ohne Überbreite,
- die „Heute“-Zeitleiste der Übersicht mit einem erfundenen Tag (Holdover 03:00–04:30, drei Ereignisse) bei 390 und
  1440 px: genau drei Marker an der richtigen Stelle, Holdover-Abschnitt im Band, Marker im Diagramm, Tagesbericht-Satz,
  Tippflächen ≥ 24 px; per Tastatur Band → Pos1 → Enter öffnet „So sah es um … aus“ (ohne Satellitenwinkel), Esc gibt den
  Fokus ans Band zurück, Tab erreicht den ersten Marker, Enter öffnet den Dialog; der Filter blendet eine Art aus,
- die sichtbare Wortzahl je Seite (`words` in der Ausgabe: innerText des Inhalts bei 1440 px, hell, ohne
  geschlossene ⓘ-Popover und zugeklappte `<details>`).

## Dateien

- `fake_chronyc.py` – erfundenes `chronyc` mit leicht schwankenden Werten, nur Beispieladressen aus
  RFC 5737 (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
- `tour.js` – der Rundgang (Node, Playwright).
- `rundgang.sh` – startet den Server mit dem erfundenen `chronyc` in einem Temp-Verzeichnis auf
  127.0.0.1, führt `tour.js` aus und beendet den Server wieder.

## Starten

Voraussetzung: Node mit Playwright und Chromium (`npm install -g playwright && npx playwright install chromium`).
Fehlt Playwright, beendet sich `rundgang.sh` ohne Fehler mit einem Hinweis.

```sh
tests/ui/rundgang.sh            # Port 18300 (der Containertest belegt 18080–18188)
tests/ui/rundgang.sh 18301      # anderer Port
TOUR_SHOTS=/tmp/fotos tests/ui/rundgang.sh   # zusätzlich Bildschirmfotos (helles Thema)
TOUR_NAV_ONLY=1 tests/ui/rundgang.sh          # nur die Navigationsprüfungen (Reiter, untere Leiste, „Mehr“, Speicherleiste)
TOUR_WORDS_ONLY=1 tests/ui/rundgang.sh        # nur die Wortzahl je Seite messen
TOUR_PAGES_ONLY=1 tests/ui/rundgang.sh        # nur Clients mit Messwert und Rohdaten der Ereignisse (erfundene Antworten)
TOUR_CLOCK_ONLY=1 tests/ui/rundgang.sh        # nur die Uhr-Werkstatt /clock (Designs, Kiosk, E-Ink, Ruhe zwischen den Minuten, Leiste bei offenem Panel)
TOUR_TIMELINE_ONLY=1 tests/ui/rundgang.sh     # nur „Heute“-Zeitleiste: Band, Marker, Tagesbericht, Tastatur (erfundener Tag)
```

Läuft der Server schon (z. B. mit `NTPGUI_CHRONYC=tests/ui/fake_chronyc.py`), genügt:

```sh
node tests/ui/tour.js http://127.0.0.1:18300
```

Ausgabe ist JSON: `problems` listet die Routen mit Befund (leer = alles in Ordnung), `summary` eine
Zeile je Route. Rückgabecode 0 ohne Befund, 1 mit Befund, 2 bei einem Fehler im Rundgang selbst.
