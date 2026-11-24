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
  Schaltsekunden-Banner am 30.6.; dazu Kiosk, E-Ink mit zweiter Zeitzone und unzulässige Parameter ohne Überbreite.
  Die Playwright-Uhr ist dabei angehalten (`install` + `pauseAt`, vorgerückt nur per `runFor`), weil die Anzeige seit
  der monotonen Zeitbasis mit `performance.now()` weiterläuft; der Mock antwortet mit der passenden Serverzeit,
- die Studiouhr A1 (`clockStudioChecks`) auf neun Flächen (360×640, 390×844, 768×1024, 1920×1080, 3840×2160,
  3840×1080, 1920×200, 480×270, 1080×1920) je in den Zuständen `ok`, `free`, `degraded` und `none`: `data-sync`,
  Zustand als Text mit Symbol, Uhrzeit, graue Sekunden, kein Ziffernumbruch, keine Überbreite; dazu ein Sprung der
  Geräteuhr um ±1 h (Anzeige unverändert), eine Taktlücke wie nach dem Standby (Neumessung) und `?lead=`,
- der Countdown der Studiouhr A5 (`clockCountdownChecks`, einzeln mit `TOUR_COUNTDOWN_ONLY=1`) auf denselben neun
  Flächen: Countdown unter der Uhr (gelb mit Symbol und Text), als Hauptanzeige in den letzten 10 s (fett rot) und
  Überzeit – gerechnet nach der gemockten Serverzeit samt Zeitzone des Servers, im Bild und ohne Umbruch; dazu
  `after=stop`, abweichende Zone des Servers, E-Ink, Timer (Leertaste, R), Stoppuhr mit Zehnteln (T), die Tasten D, L,
  U, +, ?, A, `lock=1` und die Ansage beim Unterschreiten von 1 min,
- die Spielereien der Studiouhr C1 (`clockTimerChecks`, einzeln mit `TOUR_TIMER_ONLY=1`): eine Eieruhr läuft auf den
  neun Flächen und fest als Streifen bzw. Kachel ab („Zeit ist um!“ als Text mit Rahmen, Überzeit, im Bild, ohne Umbruch
  und Scrollbalken), Merken bei gesperrtem Speicher (ehrliche Meldung), Timer und Nacht auf Handys im Querformat (Touch; bei 640×360, 740×360 und 844×390 bleibt die Leiste einzeilig
  wie in 1.9 und die Ziffern mindestens 20 % der Fensterhöhe), das Panel „Timer“ bei
  390 und 1440 px (Schnellwahl, „+1 min“, eigene Dauer, Pomodoro, eigener Countdown merken und entfernen, Tippflächen
  ≥ 24 px), der Phasenwechsel des Pomodoro, der Nachtmodus nach Uhrzeit und per Taste N, keine Knöpfe in den
  Voreinstellungen `studio`, `tile`, `banner`, mit `kiosk=1`, `lock=1`, `fun=0` und in OBS (`window.obsstudio`), dort
  auch kein N in der Kürzel-Übersicht, dazu
  ein Lauf in Echtzeit ohne Long Tasks und ohne Bildschleife,
- Binäruhr und Zusätze der Studiouhr C2 (`clockExtrasChecks`, einzeln mit `TOUR_EXTRAS_ONLY=1`): `?design=binary` (BCD
  und `bin=plain`) zeigt auf den neun Flächen die gemockte Serverzeit als Lämpchen; `?show=moon,nerd,progress` auf den
  neun Flächen im Bild (in Kachel, Streifen und auf Bühnen unter 360 px Höhe außer im Banner nie), Nerd-Zeile mit TAI und
  GPS aus `tai_utc` des Mocks bzw. „–“ ohne den Wert, Balken für Tag, Jahr und Eieruhr, Klick auf den Mond (Südhalbkugel,
  nur localStorage); im Banner 3840×1080 mit allen Zusätzen mindestens 24 px Abstand von Zeit und Zusätzen zum Rand;
  keine Zusätze in `studio`, `tile`, `banner`, mit `fun=0` und ohne `show`; im Ruhebetrieb keine
  Long Tasks und keine Bildschleife,
- Spiel, Zeitzeichen und Ostereier der Studiouhr C3 (`clockFunChecks`, einzeln mit `TOUR_FUN_ONLY=1`): Osterei 13:37 auf
  den neun Flächen (im Bild; in Kachel, Streifen und Fenstern bis 320 px Höhe nie, Streifen auch fest per
  `?layout=strip` und per Taste L bei 1920×1080), Design `tc` mit Zone des Servers (Ei zu deren 13:37 bei Gerät in
  UTC), Neujahr mit CSS-Konfetti (bei
  „weniger Bewegung“ nur Text), Konami-Code (Konfetti, Binäruhr nicht gemerkt, das abschließende A sagt nichts an); nie
  ein Ei oder Konfetti mit `eggs=0`, `fun=0`, in `studio`, `tile`, `banner`, mit `kiosk=1` (auch `p=nerd&kiosk=1`),
  `lock=1` und in OBS, auch nicht, wenn der Profil-Abruf ausfällt (`studio`, `tile`, `banner` und ein eigenes Profil
  mit 503: auch keine Knöpfe Timer, Spiel, Nacht), und nicht über dem Prüfbild `?test=sync` (13:37 und Neujahr); Panel „Spiel“ bei 390, 768 und 1920 px (Tipp mit Maus und Enter, Ergebnis, Messgenauigkeit,
  Bestwert im localStorage, Tippflächen ≥ 24 px, gesperrter Speicher ehrlich; langer Druck von 700 ms mit Maus und
  Finger ergibt genau eine Wertung, ein Klick ohne Zeiger wie vom Screenreader genau eine), Zeitzeichen-Knöpfe im Panel
  Ton; dazu ein
  Lauf in Echtzeit ohne Long Tasks und ohne Bildschleife, Konfetti danach wieder weg,
- die „Heute“-Zeitleiste der Übersicht mit einem erfundenen Tag (Holdover 03:00–04:30, drei Ereignisse) bei 390 und
  1440 px: genau drei Marker an der richtigen Stelle, Holdover-Abschnitt im Band, Marker im Diagramm, Tagesbericht-Satz,
  Tippflächen ≥ 24 px; per Tastatur Band → Pos1 → Enter öffnet „So sah es um … aus“ (ohne Satellitenwinkel), Esc gibt den
  Fokus ans Band zurück, Tab erreicht den ersten Marker, Enter öffnet den Dialog; der Filter blendet eine Art aus,
- das Statusband der Übersicht (1.6.1) mit erfundenen Hinweisen (2 Warnungen, 3 Infos, 1 Erfolg) bei 390, 1440,
  2000 und 2560 px, hell und dunkel: Kennzahl-Kacheln < 220 px, Sparkline direkt unter der Notiz, keine leere Fläche > 150 px,
  keine Überbreite, je Hinweis höchstens eine sichtbare Textzeile, „3 Informationen · 1 in Ordnung“;
  ausgeklappte Infos als kompakte Zeilen wie die Warnungen (nicht höher), Aktionen höchstens 850 px hinter dem
  Textende (so viel wie bei 1440 px); dazu die Uhrqualität bei 2000 px ohne gestreckte Karte (≤ 80 px leer unter Vollbild-Uhr/Schaltsekunden),
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
TOUR_TIMER_ONLY=1 tests/ui/rundgang.sh        # nur Studiouhr C1: Eieruhr, Pomodoro, eigene Countdowns, Nachtmodus, keine Knöpfe in Studio/Kachel/Kiosk/OBS
TOUR_EXTRAS_ONLY=1 tests/ui/rundgang.sh       # nur Studiouhr C2: Binäruhr, Mondphase, Nerd-Zeile, Fortschrittsbalken
TOUR_FUN_ONLY=1 tests/ui/rundgang.sh          # nur Studiouhr C3: Spiel „Tippe auf :00“, Zeitzeichen, Ostereier, Konfetti
TOUR_CLOCK_ONLY=1 tests/ui/rundgang.sh        # nur die Uhr-Werkstatt /clock (Designs, Kiosk, E-Ink, Ruhe zwischen den Minuten, Leiste bei offenem Panel)
TOUR_TIMELINE_ONLY=1 tests/ui/rundgang.sh     # nur „Heute“-Zeitleiste: Band, Marker, Tagesbericht, Tastatur (erfundener Tag)
TOUR_HERO_ONLY=1 tests/ui/rundgang.sh         # nur das Statusband der Übersicht (TOUR_HERO_SHOTS=<Ordner> für Fotos)
```

Läuft der Server schon (z. B. mit `NTPGUI_CHRONYC=tests/ui/fake_chronyc.py`), genügt:

```sh
node tests/ui/tour.js http://127.0.0.1:18300
```

Ausgabe ist JSON: `problems` listet die Routen mit Befund (leer = alles in Ordnung), `summary` eine
Zeile je Route. Rückgabecode 0 ohne Befund, 1 mit Befund, 2 bei einem Fehler im Rundgang selbst.
