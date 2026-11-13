# Studiouhr: /clock für TV, Ü-Wagen, Veranstaltungen und Alltag

Konzept für ntp-gui, zusammengeführt aus den Blickwinkeln Broadcast, Alltag und Technik. Es setzt auf T6 (1.6.0) auf.
Stand: 13.11.2026. Entscheidungen des Maintainers: Etappen A → B → C mit je einem Release; Timecode mit wählbaren Frames (Standard Zehntel, immer „nicht genlocked“); On-Air/REC auch per API-Schlüssel (Scope `clock`); Sendeablauf-Punkte zurückgestellt; `clock_public` bleibt standardmäßig aus.

## 1. Ziel

/clock wird zu einer ruhigen, professionellen Zeitanzeige für Regie, Ü-Wagen, Bühne und Wohnzimmer. Sie nutzt die genaue Serverzeit ehrlich: Sie zeigt immer, wie weit man ihr trauen kann.
Eine einzige Seite passt sich selbst an jede Fläche an: Handy, Rack-Monitor, 4K-Wand, 32:9-Banner, 9:16-Stele und Multiviewer-Kachel. Mehrere Bildschirme zeigen dasselbe, ohne dass sie miteinander reden müssen.
Alles bleibt Vanilla-JS ohne Build, CSP unverändert streng, ohne externe Ressourcen und ohne neue ausgehende Verbindungen. Der Bestand wird erweitert, es entsteht keine zweite Uhr-App.

**Leitentscheidungen der Zusammenführung**
- **Zuerst die Zeitbasis reparieren.** Heute gilt `serverMs = Date.now() + offset` (`app/static/js/clock.js`, Z. 131). Stellt das Gerät seine eigene Uhr nach, springt die Anzeige mit, bis zur nächsten Messung. Das muss vor jeder Studio-Nutzung behoben sein.
- **Synchron durch absolute Zeit, nicht durch Steuerkanal.** Countdown-Ziele sind Uhrzeiten auf der korrigierten Serverzeit. Es gibt keinen WebSocket, kein SSE und keinen neuen Port.
- **Der Link ist das Profil.** Serverseitige Profile kommen nur als dünne Schicht für „viele Bildschirme zentral ändern“ dazu: öffentlich nur lesend, Schreiben nur mit Login.
- **`frame-ancestors 'none'` und `X-Frame-Options: DENY` bleiben** (`app/server.py`, Z. 1496/1500). OBS, vMix und CasparCG laden die Seite als Browserquelle direkt. Die Vorschau im Dashboard öffnet sich in einem neuen Tab, nicht im iframe.
- **Parameternamen auf Englisch,** passend zum Bestand (`design`, `kiosk`, `eink`, `tz`). Beschriftungen und ⓘ-Texte auf Deutsch in du-Form.
- **Keine Schriftdateien.** 7-Segment-Ziffern werden als SVG selbst gezeichnet, sonst Systemschriften mit `tabular-nums`.

## 2. Kernfunktionen Broadcast

### 2.0 Fundament: monotone Zeitbasis, Freilauf, Fehlerschranke (Pflicht)
- **Anker:** Bei jedem Abgleich speichert die Seite `anchor = {server, perf}`. Danach gilt `serverMs = anchor.server + (performance.now() − anchor.perf)`. Sprünge der Geräteuhr, Nutzereingriffe und Standby wirken damit nicht mehr. Bei `visibilitychange` und bei einer Tick-Lücke über 2 s wird sofort neu gemessen.
- **Fehlerschranke** `errorBound()` als reine Funktion: Server-`accuracy` aus `/api/v1/time` + RTT/2 der besten Messung + 50 ppm × Alter der Messung + eine Bildauffrischung (über rAF einmalig gemessen, sonst 17 ms).
- **Zustände** über `data-sync="ok|free|degraded|none"` am Root, dargestellt per CSS, nie nur über Farbe:
  - `ok`: abgeglichen.
  - `free`: Server antwortet nicht mehr (> 10 s), Anzeige „frei laufend seit 3 min · ± 9 ms“.
  - `degraded`: Schranke > `maxerr` (Standard 100 ms). Zehntel und Frames verschwinden.
  - `none`: nie abgeglichen, Anzeige „Gerätezeit, nicht abgeglichen“.
- **Feinste Stelle ausgrauen:** Frames werden grau, sobald die Schranke > ½ Frame ist, Zehntel ab > 50 ms.
- **Manueller Latenzausgleich** `?lead=0..200` (ms) für die Verzögerung von TV-Bildprozessoren. Einstellen lässt er sich mit dem vorhandenen Ton auf der Sekunde.

### 2.1 Design `studio`: Studiouhr mit Sekundenkranz
- SVG-Kranz aus 60 Punkten: Die Punkte leuchten bis zur aktuellen Sekunde, dazu 12 Stundenmarken. In der Mitte HH:MM in selbst gezeichneten SVG-7-Segment-Ziffern (`<symbol>`, Segmente per Klasse), darunter die Sekunden. Inaktive Segmente sind schwach sichtbar.
- Es wird je Sekunde eine Klasse gesetzt. Zur vollen Minute werden alle Punkte zurückgesetzt. Kein Gleiten, kein Glühen, kein Blinken.
- Parameter:
  - `color=amber|red|green|cyan|white|ice`, Standard `amber`.
  - `sub=utc|tz2|date|off`, das zweite Feld unter der Zeit.
  - `seconds=ring|digits|both`.
  - `h12=1`.
- Neutral gestaltet, kein Nachbau einer Senderuhr oder Marke.

### 2.2 Große Digitalzeit (Design `digital`, erweitert)
- Gleicher 7-Segment-Satz oder wahlweise Systemschrift (`face=seg|mono|sans`). Font-Stack mit Tabellenziffern: `ui-monospace, "DejaVu Sans Mono", Menlo, Consolas, monospace`.
- Parameter:
  - `colon=steady|blink`, Standard `steady`.
  - `lz=1`, führende Null.
  - `date=long|short|iso|off`.

### 2.3 Timecode-Anzeige (Design `tc`) mit ehrlicher Grenze
- Zeigt die Tageszeit als `HH:MM:SS:FF` auf korrigierter Serverzeit in der Server-Zeitzone.
- Parameter:
  - `fps=24|25|30|50|29.97df|59.94df`.
  - `sub=frames|tenths|off`, Standard `tenths`.
- Drop-Frame wird nach der SMPTE-Formel als reine Funktion gerechnet, mit `;` als Trenner.
- `requestAnimationFrame` läuft nur für die FF- bzw. Zehntelstelle und nur in diesem Design. Bei E-Ink und `prefers-reduced-motion` nie Frames, höchstens Zehntel.
- Dauerhafte Kopfzeile: **„Anzeige-Timecode – nicht genlocked“**. Das ⓘ erklärt:
  - kein Hausreferenzsignal (Black Burst/Tri-Level),
  - ein 60-Hz-Monitor kann 25/50 fps nicht gleichmäßig zeigen,
  - Browser runden ihre Zeitgeber (Firefox mit `resistFingerprinting` auf 100 ms, das wird erkannt und angezeigt),
  - typisch ±1–2 Frames Abweichung,
  - echter Timecode kommt von LTC- oder VITC-Generatoren.

### 2.4 Countdown und Count-up mit Farbstufen
- Ziele:
  - `until=20:15[:00]`: heute in der Server-Zeitzone, sonst morgen.
  - `until=2026-12-31T23:59:59`: ISO-Zeitpunkt.
  - `timer=90s|25m`: lokale Dauer, Start mit Leertaste.
- Ablauf: `−MM:SS` bis zum Ziel, danach `+HH:MM:SS` (Überzeit bzw. „seit Sendebeginn“), oder bei `after=stop` Stillstand auf 00:00.
- Farbstufen `warn=300,60,10`: neutral, ab 5 min gelb, ab 60 s rot, die letzten 10 s fett rot. Kein Blinken, zusätzlich Symbol bzw. Text.
- Optional `beep=10`: piept in den letzten n Sekunden über den vorhandenen Tonweg aus T6.
- `label=` ist eine Kurzzeile (≤ 24 Zeichen, nur über `textContent`), z. B. „bis ON AIR“.
- `cd=main|below`: Der Countdown ist Hauptanzeige oder steht unter der Uhrzeit.
- Rechenbasis ist die Serverzeit. Dadurch zeigen alle Bildschirme gleich, und die Uhr dient im Alltag auch als Silvester-Countdown, Eieruhr oder Pomodoro.

### 2.5 Weltzeit-Leiste
- `tz=` bis zu 6-mal, jede Zone über das vorhandene `checkZone` geprüft.
- `tzl=NYC,LON,TYO` als Kurzlabels (≤ 8 Zeichen, nur `[A-Za-z0-9 ]`).
- UTC immer zuerst, dahinter die Abweichung („−5“) und der Tageswechsel („+1 T“).
- Im Banner eine Zeile, auf 16:9 als Raster 3×2, auf der Stele 1×6. Die Intl-Formatter werden gecacht.

### 2.6 Status- und Genauigkeitszeile
- Eine Zeile, z. B. „Server ±0,3 ms · GPS+PPS · Stratum 1 · PTP gesperrt · Anzeige ±12 ms · Abgleich vor 23 s“.
- `status=full|min|off`: `min` zeigt nur ein Statussymbol (Farbe + Form).
- Die Monitorlatenz kann der Browser nicht messen, das steht im ⓘ.
- Ohne Login (`clock_public`) zeigt die Zeile nur Arten und Zustände (GPS/PTP/NTP, gesperrt/frei/Holdover), keine Namen, IPs oder Grandmaster-IDs.
- Serverseitig bekommt `clock_status` zusätzlich `ptp_state` und `holdover`.

### 2.7 Multiviewer- und Browser-Quellen-Modus
- `layout=tile`: keine Kopfzeile, kein Band, kein Panel, kein Mauszeiger. Die Zeit so groß wie möglich, der Status nur als Ecksymbol.
- `safe=0..10` gibt einen Sicherheitsrand in Prozent (Title-Safe/Overscan), in der Kachel Standard 5.
- `bg=black|transparent`, transparent zum Keyen in OBS.
- Doku-Seite `docs/integrationen/studiouhr.md`: OBS, vMix und CasparCG als Browserquelle (Größe, `layout=tile`), Login über „Vollbild-Uhr ohne Anmeldung“ oder Cookie, kein iframe nötig.

### 2.8 On-Air/Tally-Anzeige (Etappe B, optional)
- Roter ON-AIR- bzw. REC-Rahmen. Gesteuert wird lokal per Taste `O`, zentral im Dashboard oder per `POST /api/v1/clock/signal` mit API-Schlüssel und eigenem Scope `clock`. Feste Werte `on_air|rec|off`, mit Rate-Limit.
- Anbindung an Stream Deck und Bildmischer über **Bitfocus Companion** (generisches HTTP-Modul). Es gibt keinen eigenen ATEM-, TSL- oder GPIO-Code.
- Bei aktivem Signal-Profil fragen die Bildschirme `/api/v1/time` im 1-s-Takt ab, sonst alle 5 s.
- Das ⓘ ist ehrlich: Das ist eine gespiegelte Anzeige mit bis zu 1 s Verzögerung, kein Tally am Bildmischer.

## 3. Individualisierung

**Rangfolge:** Profil < URL-Parameter < lokale Bedienung. `lock=1` im Profil sperrt die lokale Bedienung im Kiosk.

### 3.1 Parameter-Schema (gemeinsames Fundament)
- `parseParams` in `clockkit.js` wird von der festen Namensliste auf eine Schema-Tabelle umgestellt: `{name, typ: enum|flag|int(min,max)|zone|label(len,charset)|time, default}`.
- Unbekanntes wird wie bisher ignoriert. Werte über 64 Zeichen werden verworfen. Nichts davon kommt als HTML ins DOM.
- Fuzzing-Tests mit `<script>`, `javascript:`, `red;background:url(…)`, Unicode-Steuerzeichen und überlangen Werten.

### 3.2 Link-Baukasten (Stufe 1, ohne Server-Zustand)
- Neuer Reiter „Anzeigen“ unter Uhr & Hardware im Dashboard, gleichzeitig ein „Anpassen“-Panel direkt auf /clock.
- Das Formular baut aus dem Schema den kompletten Link. Dazu kommen „Link kopieren“ und „Vorschau“ im neuen Tab, mit Größenwahl Handy, Monitor, Banner, Kachel und Stele über `window.open` mit festen Maßen.
- Ohne URL-Parameter gilt der zuletzt im Panel gewählte Stand aus dem `localStorage`.

### 3.3 Benannte Profile serverseitig (Stufe 2)
- `/clock?p=regie`. Name `[a-z0-9-]{1,32}`, höchstens 20 Profile.
- Die Felder sind genau die Schema-Werte, ergänzt um `title` (≤ 40 Zeichen, über `textsafe.py`) und Rundown-Punkte (Etappe B).
- Gespeichert wird in `app/settings.py` mit den vorhandenen Konvertern. Schreiben nur über die Einstellungen-API mit Login und CSRF. Die Profile gehören in die Sicherung (`backup.py`).
- Öffentliches Lesen über `GET /api/v1/clock/profile?p=` nur bei `clock_public`, sonst mit Leserecht. Die Antwort enthält nur Allowlist-Felder, mit `Cache-Control: no-store`.
- `/api/v1/time` liefert `profiles_rev`. Ändert sich der Wert, lädt jeder Bildschirm sein Profil beim nächsten 5-s-Poll neu. So stellst du alle Regie-Monitore mit einem Klick auf „Countdown 20:15“.
- Mitgelieferte Voreinstellungen (fest im Code, nicht editierbar): `studio`, `tile`, `banner`, `kitchen`, `workshop`, `night`, `nerd`.

### 3.4 Farben und Themen
- Themen über `[data-look]` in `clock.css`, höchstens 6: `studio` (reines Schwarz, Bernstein), `contrast` (gelb auf schwarz), `warm`, `terminal` (Phosphorgrün), `paper` (hell), `pastel`. Rotlicht und E-Ink übersteuern das Thema wie bisher.
- Akzentfarbe aus einer festen Palette mit etwa 12 Namen. Eine freie Farbe ist nur als `accent=ff8800` erlaubt, geprüft mit Regex `^[0-9a-f]{6}$` und WCAG-Kontrast ≥ 4,5:1. Reicht der Kontrast nicht, wird automatisch die nächste Stufe gewählt.
- Gesetzt wird ausschließlich per CSSOM `documentElement.style.setProperty('--accent', …)`. Das ist unter der bestehenden CSP erlaubt, weil kein `style`-Attribut im Markup entsteht. Ein Playwright-Test belegt das.

### 3.5 Elemente an/aus und Größen
- `show=time,seconds,date,weekday,week,utc,tz,status,title,countdown,moon,nerd` (Allowlist), umgesetzt als `data-show` am Root plus CSS, ohne DOM-Umbau.
- `scale=50..200` (Prozent) als Feinschliff über `--clock-scale`. `weight=thin|regular|bold`.
- `layout=auto|normal|banner|column|strip|tile|world` (siehe Abschnitt 5).

## 4. Spielereien für den Alltag

Die Auswahl folgt der Faustformel. Jede Spielerei ist eine reine Funktion in `clockkit.js` bzw. `clockextras.js`, hat einen Test und lässt sich einzeln abschalten. Im Studio-, Tile- und Kiosk-Profil sind alle aus (`fun=0`).

| Spielerei | Kurz | Aufwand |
|---|---|---|
| Timer-Engine: Eieruhr, Stoppuhr, Pomodoro | Zustandsautomat auf `performance.now()`, rechnet aus Differenzen. Große Tasten, „+1 min“. Das ⓘ sagt: „piept nur, solange die Seite offen ist“. | 1 PT (mit Countdown geteilt) |
| Eigene Countdowns | bis zu 5 im `localStorage`. Eingebaut: Silvester, nächste Zeitumstellung, Unixzeit 2 000 000 000, NTP-Ära 2036 | 0,5 PT |
| Nachtmodus | `dim=22-6`, `dimlevel=20..80`, optional automatisch Rotlicht, auf Serverzeit | 0,5 PT |
| Design `binary` (BCD-Lämpchen) | offen aus 1.6.2 | 0,5 PT |
| Nerd-Zeile | Unix s/ms, Tag des Jahres, MJD, GPS-Woche/-Sekunde, TAI (aus `leap.py`), hex, römisch. Eine gemeinsame Quelle mit den 1.6.2-Kuriositäten | 1 PT |
| Mondphase | rein rechnerisch, kleines SVG, ±1 Tag laut ⓘ, Schalter „Südhalbkugel“ nur lokal | 0,5 PT |
| Fortschrittsbalken | Tag, Woche, Jahr („dieses Jahr zu 87 % vorbei“) | 0,25 PT |
| Spiel „Tippe genau auf :00“ | deine Abweichung neben Gerät (RTT/2) und Server (accuracy). Bestwert nur im `localStorage` | 0,5 PT |
| Zeitzeichen zur vollen Stunde | 5 kurze und ein langer Piep, opt-in über die vorhandene Ton-Logik | 0,25 PT |
| Ostereier | eine Tabelle `eggs[]`: 13:37, 12:34:56, Konami-Code (schaltet `binary` als „verstecktes“ Design frei), Konfetti zu Silvester nur in CSS, Zeitumstellung, Schaltsekunde (vorhanden). Abschalten mit `eggs=0` | 0,5 PT |
| Prüfbild `test=sync` | Blitz und Piep zur vollen Sekunde mit Millisekundenskala, um Ketten- und Lippensync-Verzögerung zu messen. Höchstens 1 Hz, Warnhinweis, nie bei `prefers-reduced-motion` (eher Profi-Werkzeug, Spaß für Streamer) | 0,5 PT |

**Später nur bei Nachfrage:** Lernuhr für Kinder (`face=learn` auf dem Bahnhof-Design), Lichtkilometer zur Fehlerschranke.
**Gestrichen:** Sonnenzeiten und Ortssternzeit, siehe Abschnitt 7.

## 5. Bildschirmgrößen und Formate

### Container statt Fenster
- `.clock-stage { container-type: size }` umhüllt `main`. Alle Größen laufen über `cqw/cqh/cqmin` mit `clamp()`, z. B. Hauptzeit `font-size: min(18cqw, 55cqh)`.
- Rückfallebene für ältere Engines (Chromium < 105, Safari < 16, alte CEF in CasparCG oder Smart-TVs): `@supports not (container-type: size)` behält die heutigen vw/vh-Regeln. Diese Engines bekommen nichts Neues, aber auch nichts Kaputtes.

### Automatische Layouts (`layout=auto`, per Parameter übersteuerbar)
`resolveLayout(w, h)` ist eine reine, getestete Funktion. Das CSS spiegelt sie über `@container`.

| Bedingung | Layout | Inhalt |
|---|---|---|
| Höhe < 120 px | `strip` | nur HH:MM:SS, Statussymbol |
| Seitenverhältnis ≥ 3:1 (32:9, 1920×200) | `banner` | Zeit links, Countdown, UTC und Weltzeit rechts in einer Zeile |
| Seitenverhältnis ≤ 1:1,6 (9:16, Handy hoch) | `column` | gestapelt, Stunden über Minuten bei sehr schmalen Formaten |
| Fläche < 480×270 | `tile` | nur Zeit, maximal groß |
| sonst | `normal` | Zeit, darunter Datum, Zweitzone und Status |

Der Zustand (`data-layout`) wird bei jeder Größenänderung (ResizeObserver) gesetzt. Eine Auto-Anpassung misst die Zeitbreite bei Design- und Größenwechsel und verhindert so jeden Ziffernumbruch.

### SVG
Studio-Kranz, 7-Segment, Bahnhof und Mondphase sind SVG mit `viewBox` und `preserveAspectRatio`. Sie werden auf Retina und 4K gestochen scharf, ohne Schriftdatei, und sehen auf jedem Gerät gleich aus.

### Hoch- und Querformat
Die Umstellung erfolgt allein über die Containermaße, nicht über `orientation`. Ein gedrehter Rack-Monitor oder eine Stele funktionieren also auch dann, wenn das Betriebssystem die Drehung nicht meldet.

### Pi-Kiosk und Leistungsbudget
- Kein Dauer-rAF außer im `tc`-Design. DOM-Updates einmal je Sekunde, nur geänderte Ziffern bzw. Segmente. Animationen nur über `transform` und `opacity`, kein `filter: blur` auf großen Flächen.
- `light=1` schaltet automatisch bei `hardwareConcurrency ≤ 2` oder `prefers-reduced-motion` (das Nixie-Glühen wird flach).
- Bei `visibilityState=hidden` werden die Ticks pausiert.
- Doku: Chromium-Kiosk-Aufruf für den Pi mit `--kiosk --noerrdialogs --disable-session-crashed-bubble`.

### Einbrennschutz und Dauerbetrieb
- `shift=0|1|2` (aus, fein ≤ 2 px, normal ≤ 1 % der Containergröße). Deterministischer Zyklus aus 8 Positionen alle 2 min über die Klassen `.shift-0…7`, damit er testbar bleibt. Im Studio-Profil steht der Standardwert auf `1`.
- Reines Schwarz als Studio-Hintergrund. Kopfzeile und Band blenden im Kiosk nach Leerlauf aus (vorhanden).
- Ist das Wake Lock verloren, fordert die Seite es stündlich neu an.
- `reload=04:00` (Standard aus): tägliches Neuladen gegen Speicherlecks in Smart-TV-Browsern. Vorher prüft ein `HEAD /clock`, dass keine Fehlerseite stehen bleibt.

### Offline
Fällt der Server aus, läuft die Uhr im Zustand `free` mit wachsender Schranke weiter (Abschnitt 2.0). Neue Versuche mit Backoff bis 30 s. Alle Ressourcen sind lokal. Ein Service Worker ist bewusst nicht vorgesehen.

### Barrierefreiheit
- Die Hauptzeit hat `aria-live=off`. Mit der Taste `A` wird die Zeit einmal angesagt. Der Countdown sagt nur an Schwellen an (1 min, 10 s, 0).
- `prefers-contrast: more` erzwingt hohe Kontraste.
- Zustände werden immer mit Symbol oder Text gezeigt, nie nur über Farbe.

### Tastenkürzel (ohne Strg/Alt)
| Taste | Wirkung |
|---|---|
| `F` | Vollbild |
| `D` | Design weiter |
| `L` | Layout weiter |
| `U` | UTC groß |
| `T` | Frames/Zehntel |
| `O` | On Air lokal |
| Leertaste / `R` | Timer starten/stoppen / zurücksetzen |
| `+` / `−` | Größe |
| `A` | Zeit ansagen |
| `?` | Hilfe |

Mit `lock=1` sind die Kürzel aus.

## 6. Sicherheit, Datenschutz, CSP

- **CSP unverändert:** `default-src 'self'`, kein `unsafe-inline`, `frame-ancestors 'none'`, `X-Frame-Options: DENY`. Farben und Größen kommen nur über Klassen oder CSSOM aus Allowlist-Werten.
- **Fremdeingaben:** URL-Parameter, Labels, Titel und Rundown-Texte gehen nur über `textContent` ins DOM und sind in Länge und Zeichensatz begrenzt. Es gibt kein freies CSS, HTML, Schrift- oder Bild-URL.
- **Öffentliche Pfade:** Jede neue statische Datei (`clockextras.js`, ggf. `clockfaces.js`) und `/api/v1/clock/profile` muss in `CLOCK_PUBLIC_PATHS` (`app/server.py`, Z. 386). Ein Test prüft, dass die Liste nur statische Dateien und die zwei lesenden Endpunkte enthält.
- **Ohne Login nur Anzeigedaten:** keine Quellnamen, IPs, Hostnamen, Grandmaster-IDs oder Einstellungen. Ein Allowlist-Test gilt für `/api/v1/time` (public) und für den Profil-Lesepfad.
- **Schreibwege:**
  - Profile nur über die Einstellungen-API mit Login und CSRF.
  - `POST /api/v1/clock/signal` (Etappe B) nur mit API-Schlüssel, Scope `clock`, Rate-Limit und festen Werten.
  - Von /clock aus wird nichts an chrony, ptp4l oder der Systemuhr geändert.
- **Datenschutz:**
  - Nichts geht nach außen: keine Webfonts, kein CDN, kein Wetter, keine Feiertags- oder Kalender-API.
  - Keine Geolocation-API, kein Standort in URL, Profil oder Sicherung. Das Schema kennt `lat` und `lon` gar nicht, ein Test sichert das ab.
  - Keine `speechSynthesis`, denn sie kann Online-Stimmen nutzen. Signale nur über WebAudio-Töne.
  - Der gemessene Geräteversatz bleibt im Browser. Es gibt keine Geräte-IDs und keine Telemetrie darüber, welche Uhren laufen.
- **Hinweis im Profil-Dialog:** Titel und Rundown sind bei öffentlicher Uhr im LAN für alle sichtbar.

## 7. Bewusst nicht

- Kein Anspruch auf Frame-Genauigkeit, Genlock oder Hausreferenzsignal. Kein LTC-Ausgang über WebAudio.
- Keine eigenen Tally- oder Bildmischer-Protokolle (ATEM, TSL UMD, NDI-Tally, GPIO). Dafür gibt es Companion.
- Kein WebSocket- oder SSE-Kanal und kein neuer Port. Kein Countdown-Start, der live auf alle Bildschirme gepusht wird. Zentral geht es nur über ein Profilziel (absolute Zeit).
- Keine Lockerung von `frame-ancestors`, keine iframe-Vorschau und keine Option „Einbetten erlauben“.
- Keine Webfonts und auch keine gebündelte DSEG7-Schrift. 7-Segment wird selbst als SVG gezeichnet.
- Kein Sendeablauf-Produkt (Dauern, Back-Timing, Import aus Planungssystemen). Rundown höchstens als Liste fester Zeitpunkte, siehe offene Frage 4.
- Keine Sonnen-, Gebets- oder Ortssternzeit, kein Wetter, keine Nachrichten.
- Keine Millisekunden in der großen Uhrzeit und keine Stelle, die die Fehlerschranke nicht trägt.
- Kein Blinken als einziges Signal und nichts über 3 Hz. Keine Ostereier oder Animationen in Studio-, Tile- oder Kiosk-Profilen.
- Kein Design-Zoo: höchstens 8 Designs und 6 Themen. Ein neues Design braucht einen Screenshot-Test. Was nach zwei Releases niemand nutzt, fliegt wieder raus.
- Kein verlässlicher Wecker (keine Notifications, kein Service Worker, kein Push).
- Kein Framework, kein Build-Schritt, kein Canvas oder WebGL.

## 8. Umsetzung in Etappen

Jede Etappe besteht aus mehreren kleinen PRs. Risiko für den Zeitdienst: A und C sind R1. B ist R1 bis R2 (Signal-Endpunkt).

### Etappe A – Grundgerüst (ca. 7–8 PT, Ziel 1.7.x)
| PR | Inhalt | PT |
|---|---|---|
| A1 | Monotone Zeitbasis, `errorBound`, `data-sync`-Zustände, Neumessung nach Standby, `lead` | 1 |
| A2 | Parameter-Schema in `clockkit.js` inklusive Fuzzing-Tests | 1 |
| A3 | Layout-Engine: `.clock-stage`, cq-Einheiten, `resolveLayout`, `@supports`-Fallback, `safe`, `bg`, `scale`, `show`, Pixel-Shift. Playwright-Matrix | 2 |
| A4 | Design `studio` (Kranz und SVG-7-Segment) plus `digital` mit 7-Segment, Paletten, Themen, CSSOM | 1,5 |
| A5 | Countdown und Count-up mit Farbstufen, Timer-Engine (lokal), Tastenkürzel | 1 |
| A6 | Link-Baukasten mit Vorschau im Tab, serverseitige Profile (lesend öffentlich, `profiles_rev`), Backup | 1,5 |

**Akzeptanz A**
- **Node-Unit-Tests** (`tests/test_uhr_werkstatt.py` bzw. neu `tests/test_clockcalc.py`):
  - Anker gegen simulierten Sprung der Geräteuhr: Die Anzeige springt nicht.
  - `errorBound` wächst mit dem Alter.
  - `resolveLayout` für alle Grenzwerte.
  - Countdown über Mitternacht und an den Umstellungstagen 29.3./25.10. mit fester Zeitzone.
  - Fuzzing von `parseParams`.
  - Kontrast jeder Palette ≥ 4,5:1.
- **Playwright mit fester Zeit:**
  - Zeit fixiert über `page.clock.setFixedTime`, `/api/v1/time` per `route.fulfill` gemockt (feste t1/t2/accuracy).
  - Viewports: 360×640, 390×844, 768×1024, 1920×1080, 3840×2160, 3840×1080 (32:9), 1920×200, 480×270, 1080×1920 (9:16).
  - Je Viewport alle Designs × Zustände (`ok`, `free`, `degraded`, `none`, Countdown < 10 s, Überzeit) mit Screenshot-Vergleich `toHaveScreenshot`. Läuft im Container mit festen Schriften (DejaVu).
  - Prüfkriterien: Die Bounding-Box der Zeit liegt im Container innerhalb des `safe`-Rands, kein Ziffernumbruch, kein Scrollbalken.
- **CSP:** Ein Test belegt, dass die Seite ohne CSP-Verletzung im Konsolenlog lädt und `setProperty` wirkt.
- **CPU:**
  - Im Playwright-Trace gibt es 0 Long Tasks über 50 ms im Ruhebetrieb.
  - Im Studio- und Digital-Design höchstens 1 Repaint je Sekunde.
  - Manuelle Abnahme auf einem Pi 4 mit Chromium-Kiosk bei 1080p: Studio < 10 % CPU, Digital < 3 %.
- **Backend:**
  - Der öffentliche Profil-Abruf liefert nur Allowlist-Felder.
  - Fremdfelder und Profilnamen außerhalb `[a-z0-9-]` werden abgewiesen.
  - Ohne `clock_public` kein Zugriff.
  - `profiles_rev` ändert sich beim Speichern.

### Etappe B – Profi-Ausbau (ca. 5–6 PT)
| PR | Inhalt | PT |
|---|---|---|
| B1 | Design `tc`: Timecode mit DF-Rechnung, rAF nur für FF/Zehntel, Beschriftung „nicht genlocked“, Erkennung der Timer-Rundung | 1,5 |
| B2 | Weltzeit-Leiste/-Raster (`tz` ×6, `tzl`), Layout `world` | 1 |
| B3 | Statuszeile vollständig (`ptp_state`, `holdover` in `clock_status`), Kachel-Feinschliff, Doku für OBS, vMix, CasparCG und Companion | 1 |
| B4 | On-Air/REC: Taste, Dashboard-Schalter, `POST /api/v1/clock/signal` (Scope `clock`, Rate-Limit), 1-s-Poll nur bei aktivem Signal-Profil | 1,5 |
| B5 | Prüfbild `test=sync` | 0,5 |

**Akzeptanz B**
- **DF-Testvektoren:**
  - 00:00:59;29 → 00:01:00;02.
  - Minute 10 ohne Sprung.
  - 23:59:59 → 00:00:00:00.
  - Bei Schranke > ½ Frame wird die FF-Stelle grau (Playwright).
- **CPU:** Im `tc`-Design mit `sub=tenths` auf dem Pi < 10 %. Frames nur auf ausdrücklichen Wunsch, ohne CPU-Zusage.
- **Weltzeit:** korrekte Abweichung und Tageswechsel an den Umstellungstagen. Labels mit Sonderzeichen werden verworfen.
- **Datenschutz:** Ein Test belegt, dass `/api/v1/time` ohne Login keine Namen, IPs oder IDs enthält, auch nicht im neuen PTP-Feld.
- **Signal:** Ohne Schlüssel oder mit falschem Scope 401/403. Werte außerhalb der Liste 400. Das Rate-Limit greift. Lasttest im Container mit 20 simulierten Bildschirmen im 1-s-Poll: p95-Antwortzeit < 50 ms.
- **Prüfbild:** Bei `prefers-reduced-motion` wird es nicht aktiviert, Blitzfrequenz ≤ 1 Hz.
- **Screenshot-Matrix** aus A, erweitert um `tc`, `world` und On-Air.

### Etappe C – Spielereien (ca. 4–5 PT, einzeln verschiebbar)
- **Inhalt:** Timer-Oberfläche (Eieruhr, Pomodoro) und eigene Countdowns, Nachtmodus, Design `binary`, Nerd-Zeile, Mondphase, Fortschrittsbalken, Spiel „Tippe auf :00“, Zeitzeichen und Ostereier mit Konami-Code. Damit sind die offenen 1.6.2-Punkte zu /clock erledigt.
- **Akzeptanz C:**
  - Jede Spielerei hat einen Node-Test mit Referenzwerten: Mondphase gegen Tabelle, TAI/GPS gegen `leap.py`.
  - Test: `eggs=0`, `fun=0` sowie die Studio-, Tile- und Kiosk-Profile zeigen nie ein Ei oder Konfetti.
  - Konfetti nur per CSS, bei `prefers-reduced-motion` nur Text.
  - CPU-Budget wie in A.
  - Die Obergrenze von 8 Designs ist eingehalten.

**Summe:** etwa 16–19 PT. Faustformel grob (Nutzen × 2 − Aufwand − Risiko):

| Baustein | Wert | Einordnung |
|---|---|---|
| A1 | 3·2 − 1 − 1 = 4 | sofort |
| Countdown | 4 | sofort |
| Layout und Kachel | 4 | sofort |
| Studio-Design | 4 | sofort |
| Profile serverseitig | 2–3 | |
| Weltzeit | 4 | |
| Timecode | 2 | |
| On-Air | 2 | OSS-Bonus durch Companion: 3 |
| Spielereien | 0–2 | plus Spaß |

## 9. Offene Fragen an den Maintainer

1. **Serverseitige Profile schon in Etappe A oder erst nach dem Link-Baukasten?**
   *Empfehlung:* in A, aber als letzter PR (A6). Der eigentliche Mehrwert für Ü-Wagen ist „zehn Monitore zentral umstellen“. Der Lesepfad ist klein und allowlist-geprüft.
2. **On-Air/Tally mit eigenem schreibenden API-Endpunkt (B4) bauen?**
   *Empfehlung:* ja, aber nur mit API-Schlüssel und Scope `clock`, mit Companion als dokumentiertem Weg. Gibt es nach 1.7 keine Rückmeldung der Community, bleibt es beim Dashboard-Schalter.
3. **Frames im Timecode-Design anbieten oder nur Zehntel?**
   *Empfehlung:* Frames anbieten, standardmäßig aus, dauerhaft als „nicht genlocked“ beschriftet und ausgegraut, wenn die Schranke sie nicht trägt. Regien fragen danach. Die Beschriftung verhindert, dass jemand die Anzeige als Referenz nutzt.
4. **Rundown-Punkte („Nächster Punkt“, höchstens 20 Zeitpunkte mit Kurztitel im Profil) aufnehmen?**
   *Empfehlung:* zurückstellen, frühestens nach B. Das ist Freitext im öffentlichen Lesepfad und die Vorstufe zu einem Sendeablauf-Produkt. Ein Countdown mit `label` deckt den Großteil ab.
5. **Soll /clock in 1.7 als Standard ohne Login erreichbar sein (`clock_public` an), damit Browserquellen in OBS, vMix und CasparCG ohne Cookie funktionieren?**
   *Empfehlung:* nein, Standard bleibt aus. Im Dashboard kommt beim Link-Baukasten ein deutlicher Hinweis mit Ein-Klick-Schalter dazu, inklusive Erklärung, was öffentlich sichtbar wird (nur Zeit, Zustände, Profil-Anzeigefelder).

