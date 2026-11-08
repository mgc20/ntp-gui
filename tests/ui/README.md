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

- auf der Clients-Seite: bei 390 px Karten statt Tabelle ohne Überbreite, bei 1440 px die Tabelle, Name direkt in
  der Liste (✎ öffnet das Feld, Esc bricht ab, Enter speichert; der Name wird danach wieder entfernt),
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
```

Läuft der Server schon (z. B. mit `NTPGUI_CHRONYC=tests/ui/fake_chronyc.py`), genügt:

```sh
node tests/ui/tour.js http://127.0.0.1:18300
```

Ausgabe ist JSON: `problems` listet die Routen mit Befund (leer = alles in Ordnung), `summary` eine
Zeile je Route. Rückgabecode 0 ohne Befund, 1 mit Befund, 2 bei einem Fehler im Rundgang selbst.
