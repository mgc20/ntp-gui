# Version 1.6: „Zuhause besser“ – lokal, mit Spaß und in Ordnung gebracht

Stand: 08.11.2026 · Plan, offene Fragen entschieden (Abschnitt 6) · Grundlage: Stand 1.5.4,
[ROADMAP](../../ROADMAP.md), [Entscheidungen E1–E19](entscheidungen.md),
[version-1.5.md](version-1.5.md), [Entscheidungsrahmen](entscheidungsrahmen.md).
Zusammengeführt aus vier Durchsichten: Fehlersuche Backend, Fehlersuche Frontend (beide am Code
gegengeprüft), GUI/UX-Durchsicht mit synthetischem Testaufbau (erfundenes `chronyc`/`gpsd`,
mehrere NTS-Quellen, einige Dutzend Clients, 48 h Verlauf) und Ideensammlung für lokale Funktionen.
Der bisherige Entwurf „Nach außen öffnen …“ (Englisch komplett, Hardware-Bericht, Zeitwächter-Ping,
„Von außen prüfen“, VPS-Spur) wird **1.7**: [version-1.7-entwurf.md](version-1.7-entwurf.md).

## 0. Ziel und Leitlinie

Entscheidung des Maintainers: **„Erste Community-Funktionen erst in 1.7, vorher noch weitere lokale
Themen, die sinnvoll sind, Spielereien sind, Fehler beheben, GUI verbessern.“**

1.6 soll sich für Nutzer wie ein neues Release anfühlen, ohne dass etwas Neues das Haus verlässt:

1. **Qualität:** alle bestätigten Fehler aus den beiden Fehlersuchen beheben (Anhang A). Vorrang
   haben B1 (Kalibrierkarte lädt den ganzen Verlauf), B2 (kein Socket-Timeout), F1 (Zeitzone),
   F2 (Verbindungsverlust) und F3 (endloses „Lade …“).
2. **Ruhigere Oberfläche:** weniger Text, gleiche Bausteine überall, eine Navigation, die aufs
   Handy passt, Einstellungen, die man findet. Das ist der sichtbare Sprung.
3. **Spaß:** Spielereien, die etwas erklären (Uhr-Designs, Ton auf der Sekunde, „Heute“-Zeitleiste).
4. **Nützliches für den eigenen Pi:** Pi-Zustand (Drosselung, Unterspannung), vollständige
   Sicherung, geführte Einrichtung.

**Leitplanken (gelten für jedes Thema):**

- **Keine neue Verbindung nach außen.** Kein neuer Ausgangs-Zweck in `egress.py`. Wo eine Nachricht
  verschickt wird (Tagesbericht), dann nur über die vorhandenen, vom Nutzer eingerichteten
  Benachrichtigungskanäle und opt-in.
- **Keine neue Abhängigkeit** in Python und im Frontend. Alles mit stdlib, SVG, CSS, WebAudio.
- **Keine neue Automatik**, die in die Zeit eingreift. 1.6 zeigt an, erklärt, sichert.
- **Datenschutz:** Exporte, Diagnosepakete, Benachrichtigungen und Sicherungen dürfen nie eine
  Standortbestimmung erlauben: keine Position, keine Satellitenwinkel. Jedes neue Exportformat
  bekommt einen Test gegen den Datenschutzfilter.
- **Sicherheit durch Einfachheit:** Wiederherstellen nur mit Vorschau und Versionsprüfung;
  neue Eingaben über die Allowlist in `settings.py`; UI baut DOM nur über `el()`/`textContent`.
- **Deutsch ist Referenz.** Englisch wird in 1.6 nicht ausgebaut, aber das halbe Englisch (F4) wird
  beseitigt: Standard ist Deutsch, Englisch nur auf ausdrücklichen Wunsch als „English (Beta)“
  (Entscheidung F2). Englisch komplett bleibt in 1.7 (Reichweite = Community-Thema).

## 1. Übersicht

Bewertung nach dem [Entscheidungsrahmen](entscheidungsrahmen.md#2-bewertung-fünf-fragen):
Wert = `Nutzen×2 − Aufwand − Risiko`, +1 bei OSS „ja“, +0,5 bei „teilweise“ (E8). Spaß (☺) zählt
nicht in den Wert, sondern entscheidet bei Gleichstand.
Aufwand: ◆ ≈ 1–3 Abende, ◆◆ ≈ 1–2 Wochenenden, ◆◆◆ mehrere Wochen. PT = Personentage.

| # | Thema | Nutzen | Spaß | Aufwand | Risiko | 🔒 | Wert | Stufe |
|---|---|---|---|---|---|---|---|---|
| T1 | Grundreinigung: alle bestätigten Fehler (27) + beobachtete Ungereimtheiten | ★★★ | – | ◆◆ (4–6 PT) | R1 | – | **3** | **1.6.0**, zuerst |
| T2 | GUI-Erneuerung: Bausteine + Zahlenformat, Navigation neu, Einstellungen 2.0, Seiten entschlacken | ★★★ | ☺ | ◆◆ (6–8 PT) | R2 | – | **2** | **1.6.0** |
| T3 | Willkommens-Assistent „In 3 Minuten fertig“ + Checkliste | ★★★ | ☺ | ◆◆ (3–4 PT) | R1 | – | **3** | **1.6.0** |
| T4 | Pi-Zustand: Drosselung, Unterspannung, Lüfter, Takt | ★★★ | ☺ | ◆ (1–2 PT) | R1 | – | **4** | **1.6.0** |
| T5 | Sicherung und Wiederherstellung (alles außer Position) | ★★★ | – | ◆◆ (3–4 PT) | R2 | 🔒 | **2** | **1.6.0** |
| T6 | Uhr-Werkstatt: `/clock`-Designs, Kiosk, Ton auf der Sekunde, „Wie falsch geht dein Gerät?“ | ★★ | ☺☺☺ | ◆ (2–3 PT) | R1 | – | **3** | **1.6.0** |
| T7 | „Heute“-Zeitleiste: Zustandsband 24 h, Ereignismarker in allen Diagrammen, Tagesbericht | ★★ | ☺☺ | ◆◆ (3–4 PT) | R1 | – | **2** | **1.6.0** (Tagesbericht-Nachricht 1.6.1) |
| – | Ruhiger Betrieb (Neustart-Koordinator), aus dem 1.7-Entwurf vorgezogen | ★★ | – | ◆◆ | R2 | – | 1 | **1.6.1** (siehe Frage F1) |
| – | Hilfe mit Inhaltsverzeichnis und Unterseiten, ⓘ verlinkt „mehr →“ | ★★ | – | ◆ | R1 | – | 3 | 1.6.1 |
| – | PPS-Bastelanleitung + Prüfassistent | ★★★ | ☺☺ | ◆ | R1 | – | 4 | 1.6.1 (Doku kann schon mit 1.6.0) |
| – | Prometheus erweitern + Grafana-JSON | ★★ | – | ◆ | R1 | – | 2,5 | 1.6.1 |
| – | Satelliten-Spuren, Zeitraffer, Abschattungskarte | ★★ | ☺☺☺ | ◆◆ | R2 | 🔒 | 0 (+Spaß) | 1.6.2 (Frage F5) |
| – | Rangliste der LAN-Uhren, Zeit-Kuriositäten, Ostereier | ★ | ☺☺☺ | ◆ | R1 | – | 0–1 (+Spaß) | 1.6.2 |
| – | Wochenbericht als Druckseite, Stratum-Baum | ★★ | ☺ | ◆◆ | R1 | – | 1 | 1.6.3 |

**Schätzung 1.6.0:** ≈ 22–31 PT, mit 30 % Puffer ≈ 8–11 Wochenenden. Das ist so groß wie der
1.7-Entwurf; dafür ist fast alles Frontend oder Lesen, also geringes Risiko für den Zeitdienst.

**Wenn die Zeit knapp wird:** Einstellungen 2.0 (Teil von T2) und T7 dürfen nach 1.6.1 rutschen,
T1 nie.

### Reihenfolge innerhalb von 1.6.0 (festgelegt)

**T1 → T4 → T5 → T2 → T3 → T6 → T7**, je Thema ein kurzer PR (größere Themen in mehreren PRs) mit
unabhängiger Prüfung auf Korrektheit sowie Sicherheit und Datenschutz.

1. **T1 Grundreinigung** zuerst, damit Regressionen nicht in GUI-Änderungen untergehen. Der
   Frontend-Teil von T1 behebt die Fehler gezielt am bestehenden Code; was ohnehin in die neuen
   Bausteine gehört (Zahlenformate F14/F15, `errorState`), bekommt in T1 die kleinste Korrektur und
   wandert in T2 in die Bausteine. Die Vorrang-Fehler B1/B2 können als **1.5.5** vorab erscheinen,
   wenn 1.6.0 länger als 4 Wochen braucht.
2. **T4 Pi-Zustand** (klein, unabhängig, wird von T3 gebraucht).
3. **T5 Sicherung** vor dem großen Umbau – sie schützt Nutzerdaten, bevor sich viel ändert.
4. **T2 GUI-Erneuerung:** Bausteine (`ui.js`-Komponenten, `fmt*`) vor jeder Seitenarbeit, dann
   Navigation, Einstellungen 2.0 und die Seiten einzeln.
5. **T3 Willkommens-Assistent** (nutzt Hardware-Check, T4 und die Speichervorschau aus T2).
6. **T6 Uhr-Werkstatt**, dann **T7 „Heute“-Zeitleiste**. Danach 1.6.0 veröffentlichen.

## 2. Kern 1.6.0 im Einzelnen

### T1. Grundreinigung: alle bestätigten Fehler

- **Nutzen:** Die Fehlersuche hat 27 bestätigte Fehler gefunden (Anhang A), davon fünf mit
  spürbarer Wirkung: B1 (Kalibrierkarte fragt alle 15 s den **gesamten** Verlauf ab; gemessen
  13,9 s Serverzeit und ≈ 1,1 GB), B2 (ein halber Request hält einen Thread für immer), F1
  (Uhrzeit in der Browser-Zeitzone mit Etikett der Server-Zeitzone), F2 (bei Verbindungsverlust
  bleiben alte Werte stehen, als wären sie aktuell), F3 („Lade …“ für immer bei API-Fehlern).
- **Aufwand:** ◆◆ (Backend 2–3 PT, Frontend 2–3 PT, viele Punkte sind Einzeiler).
- **Umsetzungsskizze (nach Gruppen):**
  1. **Last und Robustheit:** B1 – Frontend-Standard auf 24 h (`calWindow ?? 86400`), Server
     behandelt `window=0`/`nan` als „Standard“, „gesamter Verlauf“ nur auf Klick und serverseitig
     verdichtet (höchstens ≈ 2000 Punkte); Umwandlung außerhalb des Locks gilt schon, aber die
     Abfrage selbst begrenzen (gleich in `autocal.py:733`). B2 – `Handler.timeout = 30`
     (`StreamRequestHandler` setzt damit `settimeout`). B3 – `address_family` aus `WEB_BIND`
     ableiten (`:` → AF_INET6), Fehlermeldung mit dem echten `OSError`-Text.
  2. **Uhren:** B4 – Aufräumen nur, wenn die Uhr synchron ist (chrony `Leap status normal` und
     kleiner Offset) **und** `now` nicht hinter dem neuesten gespeicherten `t` liegt; sonst
     überspringen und Ereignis „Aufräumen ausgesetzt: Systemzeit unplausibel“. B5/B7 –
     `time.monotonic()` für Cache-TTL, `_last_save`, Uptime; in `entrypoint.sh` `$SECONDS` statt
     `printf '%(%s)T'`. Gleichzeitig der Restposten aus 1.5.0: Holdover-Frist auf der monotonen Uhr.
  3. **Daten:** B6 – Flush mit `INSERT OR IGNORE` wie die Migration (oder `ON CONFLICT DO NOTHING`).
     B8 – `confgen._write` mit `try/finally unlink`; `apply()` rendert **beide** Dateien zuerst in
     Tempdateien und benennt erst um, wenn beide fertig sind; schlägt etwas fehl, keine
     Umbenennung und kein Neustart, Meldung stimmt dann („bisherige Einstellungen weiter aktiv“).
  4. **Frontend-Zustand:** F2 – bei Verbindungsverlust Seiteninhalt sichtbar als „veraltet seit …“
     abdunkeln (Overlay mit Zeit), Handler für `online` und `visibilitychange` lösen sofort einen
     Abruf aus, Backoff höchstens 30 s bleibt. F3 – `ctx.data()` liefert bei Fehler ein
     Fehlerobjekt; ein gemeinsamer `emptyState`/`errorState` aus T2 ersetzt alle `undefined`-Prüfungen.
     F1 – `toLocaleString(…, { timeZone: sys.timezone })`.
  5. **Darstellung:** F4 halbes Englisch (siehe Frage F2), F5 sichtbare Beschriftung der
     Checkboxen unter 720 px, F8 Popover schließt erst ab 40 px Scrollweg, F9/F10 Kontraste
     (Primärknopf dunkel z. B. #2f7ee6 oder dunkle Schrift; `--ink-muted` hell z. B. #5f6b7a, beide
     ≥ 4,5:1 nachgerechnet im Test), F11 „jetzt“ mit Rohwert-min/max oder Hinweis „Mittelwerte“,
     F12 IPs nicht umbrechen (`overflow-wrap: normal`, `white-space: nowrap`), F14/F15 alles über
     `fmt*` aus T2, F17 veraltete Versionstexte raus, F18 Titel kürzen statt abschneiden.
  6. **Kleinkram:** `REASON_TONE` löschen, `aria-label` am `span` durch `role="img"` oder sichtbaren
     Text ersetzen, „Noch keine Geräte gesehen“ nur, wenn die Liste wirklich leer ist,
     **CSP-Header** `default-src 'self'; img-src 'self' data:; style-src 'self'` (vorher prüfen, ob
     Inline-Styles vorkommen; sonst `style-src 'self' 'unsafe-inline'` als Übergang).
  7. **Doku B9:** konkrete Zeile `proxy_set_header Host $host;` für nginx/NPM in
     `docs/integrationen/https.md`.
  8. **Beobachtete Ungereimtheiten** aus der GUI-Durchsicht (Anhang B, U1–U17), soweit nicht schon
     oben enthalten. Bei U6 (Anfragen/min 6,0 ↔ 0,0) und U7 (Hardware-Check „Kein GPS-Empfänger“
     trotz Fix) zuerst mit Daten aus Diagnosepaketen prüfen; U7 entspricht F7 – Regel: liefert gpsd ein aktives
     Gerät mit Fix, schlägt das die sysfs-Suche (betrifft vor allem entferntes gpsd über `GPSD_HOST`).
- **Akzeptanzkriterien:**
  - Für jeden Fehler aus Anhang A ein Test (Unit, Container oder Playwright), der vor dem Fix rot
    und danach grün ist. Ausnahmen (reine Texte) stehen im CHANGELOG.
  - B1: Kalibrierkarte mit 30 Tagen Verlauf auf dem Pi 4 < 300 ms Serverzeit je Abruf.
  - B2: Ein Client, der 10 Bytes eines angekündigten 1-KiB-Bodys schickt, belegt nach 30 s keinen
    Thread mehr (Thread-Zählung im Test).
  - B4: Systemuhr um +1 Jahr verstellt → keine Zeile in `events`, `clientmon_samples` gelöscht.
  - F2: Server gestoppt → innerhalb von 35 s steht „veraltet seit hh:mm:ss“ über dem Inhalt;
    Server wieder da → Hinweis weg ohne Neuladen.
  - Kontrasttest: alle Text-Tokens ≥ 4,5:1 in beiden Themen.
- **Datenschutz:** nichts Neues. Der CSP-Header verbessert die Lage zusätzlich.

### T2. GUI-Erneuerung

- **Nutzen:** Der sichtbare Sprung. Gemessen (Anhang B): Einstellungen 8053 px Desktop /
  12423 px Handy mit 2291 Wörtern und 44 Feldern, GPS 8186 px und 73 ⓘ auf dem Handy, Navigation
  2,7 Bildschirmbreiten breit, ⓘ-Tippflächen 18 px. Die meisten Ungereimtheiten (Zahlenformate,
  „± 1,000 ms“, Zeitraum-Knöpfe, leere Diagramme) entstehen, weil jede Seite ihre eigenen
  Bausteine hat.
- **Aufwand:** ◆◆ (Bausteine 1–2 PT, Navigation 1 PT, Einstellungen 2.0 2–3 PT, Texte kürzen
  1–2 PT – reine Textarbeit, gut mit KI-Hilfe).
- **Umsetzungsskizze:**
  1. **Bausteine in `ui.js`:** `statCard`, `kvRow`, `rangePicker` (eine Komponente für Minuten bis
     Tage), `emptyState`/`errorState`, `chartCard` (klappt flache und leere Diagramme auf eine Zeile
     zusammen: „Maximaler Fehler: stabil um ± 420 µs – Diagramm zeigen“, „Satelliten im Verlauf:
     sammelt seit 23:30“), `infoButton` (Symbol 14 px, Tippfläche 32 px, blass bis Hover/Fokus).
     Eine Musterseite `#/muster` nur mit `?dev=1`.
  2. **Zahlen in `util.js`:** `fmtDuration`, `fmtPpm`, `fmtNumber`, `fmtDate` mit
     `Intl.NumberFormat`/`DateTimeFormat` der gewählten Sprache, automatisch passende Einheit
     (ns/µs/ms/s), **keine Nullen am Ende** („± 1 ms“ statt „± 1,000 ms“), Komma im Deutschen,
     ISO-Zeiten (F15) immer formatiert. `toFixed` ist danach in Seiten verboten (Lint-Regel per
     `grep` im Test).
  3. **Navigation:** 11 → 7 Einträge: Übersicht · Zeitquellen · GPS · Clients · Uhr & Hardware
     (Uhrqualität, Hardware, PTP) · System (Diagnose, Benachrichtigungen, Einstellungen) · Hilfe.
     Ausgeschaltetes PTP erscheint nur als Zeile „Nicht genutzt“. Alte Hash-Routen leiten weiter.
     Auf dem Handy eine **untere Leiste** mit Übersicht, Quellen, GPS, Clients und „Mehr“; Titel
     kurz („NTP-GUI“ + Hostname im Menü).
  4. **Einstellungen 2.0:** Reiter (Quellen · LAN-Server · GPS · PTP · Dashboard & Zugang ·
     Sichern), Suchfeld, Schalter „nur Geänderte“. Abzeichen nur noch bei geänderten Werten
     („geändert · zurücksetzen“). Pro Feld höchstens eine Zeile (≤ 140 Zeichen) sichtbar, der Rest
     im ⓘ; „Erweitert“ je Abschnitt eingeklappt. **Klebende Speicherleiste:** „3 Änderungen ·
     Neustart der Zeitdienste nötig · Speichern / Verwerfen“ mit **Vorschau als Diff der
     `chrony.conf`/`ptp4l.conf`** (confgen rendert ohnehin, nur nicht schreiben). Versionsgeschichte
     („Standard ab 1.5.2“) raus aus der Oberfläche.
  5. **Seiten entschlacken:** gleiche Regel wie in den Einstellungen (eine Zeile sichtbar). Zeitquellen:
     „Grund“ nur, wenn anders als „Zustand“. Clients: Gerätename per Klick direkt in der Tabelle,
     Spalten ohne Messwert ausblenden, auf dem Handy Karten statt Tabelle. Rohtext der Ereignisse
     eingeklappt. Quellenfarben fest je Quelle (gleich in allen Diagrammen, GPS immer dieselbe
     Signalfarbe), Linien-Endbeschriftungen nur mit Kurznamen.
  6. **Fußzeile:** `/metrics · /api/status · /healthz` wandern in die Hilfe („API & Automatisierung“).
  7. **Tastenkürzel** (`g o`, `g s`, `/`, `?`) – klein, nebenbei.
- **Akzeptanzkriterien:**
  - Playwright-Rundgang über alle Routen, Desktop 1440 px und Handy 390 px, beide Themen: keine
    Konsolenfehler, kein waagerechter Seiten-Überlauf, keine Tippfläche < 24 px (Ziel 32 px), kein
    Text `\d,000 ` oder `\d\.\d+ (s|ms)` in deutscher Sprache, Kontrast ≥ 4,5:1. Grundlage sind die
    Skripte aus der GUI-Durchsicht (`shots.js`, `probe.js`).
  - Einstellungen am Desktop < 2500 px Höhe (ohne aufgeklappte Erweitert-Bereiche), Suche findet
    jedes Feld nach Name und ⓘ-Text.
  - Navigation passt bei 390 px ohne waagerechtes Scrollen.
  - Alte Lesezeichen (`#/ptp`, `#/hardware`, …) landen auf der richtigen Seite.
  - Speichervorschau zeigt genau die Zeilen, die nach dem Speichern in der Datei stehen
    (Test: Vorschau == Datei nach `apply`).
- **Datenschutz:** nichts Neues. Gerätenamen bleiben in der lokalen SQLite.
- **Risiko R2:** großer Umbau aller Seiten. Abhilfe: Bausteine zuerst, Seiten einzeln umstellen,
  jede Seite mit Vorher/Nachher-Screenshot im PR.

### T3. Willkommens-Assistent „In 3 Minuten fertig“

- **Nutzen:** Ein neuer Nutzer landet heute auf drei gelben Hinweisen und 44 Einstellungen. Der
  Hardware-Check weiß schon fast alles, was ein Assistent braucht; es fehlt nur die Führung.
  Weniger Issues der Art „GPS geht nicht“ / „Uhr wird nicht geregelt“.
- **Aufwand:** ◆◆ (3–4 PT).
- **Umsetzungsskizze:**
  1. Erscheint beim ersten Start (kein gespeichertes `setup_done`) oder per Knopf in „System“.
     Jeder Schritt überspringbar, nichts wird ohne „Übernehmen“ geschrieben.
  2. Schritte: **(a) Prüfen** – Hardware-Check auswerten: Volume vorhanden? `SYS_TIME`? GPS gefunden?
     Pi-Zustand (T4) ok? Jeder rote Punkt mit genau einer Abhilfe (Compose-Zeile zum Kopieren).
     **(b) Zeitquellen** – Vorlagen mit einem Klick (öffentliche NTS-Server, z. B. PTB, Netnod, Cloudflare),
     vorhandene Auswahl wird angezeigt, nicht ersetzt. **(c) GPS** – ja/nein, ehrlich nach E16
     („ohne PPS: Rückfallebene, Netz ist meist genauer“), Hinweis auf PPS-Anleitung.
     **(d) Clients** – eigene IP/Hostname zum Kopieren, Schnipsel für Windows, macOS, Linux und
     Verweis auf die bestehenden Anleitungen für Router und Smart-Home-Systeme. **(e) Benachrichtigung**
     – optional vorhandenen Kanal einrichten,
     Testnachricht (nutzt bestehenden Code).
  3. Danach eine **Checkliste-Karte** auf der Übersicht („4 von 5 erledigt“), die verschwindet,
     wenn alles grün ist oder der Nutzer sie schließt.
  4. Gespeicherte Änderungen laufen über denselben Weg wie die Einstellungen (Validierung,
     Speichervorschau aus T2).
- **Akzeptanzkriterien:**
  - Frische Installation (leeres Datenverzeichnis): Assistent erscheint; „Überspringen“ an jeder
    Stelle hinterlässt keine Änderung.
  - Mit Testaufbau „ohne Volume, ohne SYS_TIME“ nennt Schritt (a) beide Probleme mit Abhilfe.
  - Bestehende Installation (Update von 1.5.x): Assistent erscheint **nicht** von selbst, nur ein
    dezenter Hinweis „Einrichtung prüfen“ einmalig.
  - Playwright-Lauf durch alle Schritte, 390 px und 1440 px.
- **Datenschutz:** keine Verbindung nach außen. Die Vorlagen sind feste Listen im Code; die
  Erreichbarkeit der Server prüft chrony selbst nach dem Speichern, nicht der Assistent.

### T4. Pi-Zustand: Drosselung, Unterspannung, Lüfter

- **Nutzen:** Fehlt heute ganz (`thermal.py` liest nur Temperaturen). Unterspannung und
  Takt-Drosselung erklären Sprünge in Frequenz und Offset und sind auf Pis mit schwachem Netzteil
  häufig – und unsichtbar. Gehört zur Uhrqualität.
- **Aufwand:** ◆ (1–2 PT).
- **Umsetzungsskizze:**
  1. Neues kleines Modul `pistate.py`, nur lesen, jede Quelle optional:
     `get_throttled` (Firmware-Bitfeld, Pfad unter `/sys/devices/platform/soc/soc:firmware/` *(n. g.,
     im Container eventuell nicht sichtbar)*), hwmon `rpi_volt/in0_lcrit_alarm` (Unterspannung,
     seit Kernel 5.x), hwmon `fan1_input`, `cpufreq/scaling_cur_freq`. Kein `vcgencmd` (braucht
     `/dev/vchiq`).
  2. Karte „Pi-Zustand“ auf „Uhr & Hardware“: Unterspannung jetzt/seit Start, gedrosselt jetzt/seit
     Start, Takt, Lüfter. Ohne Datei: Zeile fehlt (kein „unbekannt“-Rauschen auf x86).
  3. Ereignisse „Unterspannung erkannt“ / „Takt gedrosselt“ (mit Entprellung), Metrik
     `ntpgui_pi_undervoltage`, `ntpgui_pi_throttled`, Verlauf in `history` (eine Spalte).
  4. In den Hardware-Check und den Assistenten (T3) übernehmen; Hinweis auf offizielles Netzteil.
- **Akzeptanzkriterien:**
  - Testaufbau mit gefälschtem sysfs (Bitfeld 0x50005): Karte zeigt „Unterspannung jetzt und seit
    Start“, genau ein Ereignis, kein weiteres bei gleichem Wert.
  - x86 ohne die Dateien: keine Karte, keine Warnung, kein Fehler im Log.
  - Container-Test: Pfade nur gelesen, keine neue Capability, kein neues Volume.
- **Datenschutz:** nur lokal; Werte dürfen ins Diagnosepaket (keine Personen- oder Ortsdaten).

### T5. Sicherung und Wiederherstellung

- **Nutzen:** Heute lassen sich nur die Einstellungen exportieren. Verlauf, Kalibrierung,
  Client-Gruppen und -Namen, Regeln und Benachrichtigungskanäle gehen bei einer neuen SD-Karte
  verloren. Ein Klick „Alles sichern“ erspart Stunden und schützt die Kalibrierung (≥ 6 h Messung).
- **Aufwand:** ◆◆ (3–4 PT).
- **Umsetzungsskizze:**
  1. `GET /api/backup` (nur angemeldet, wie der Einstellungsexport) liefert `.tar.gz`:
     `manifest.json` (Format-Version, ntp-gui-Version, Schema-Version, Liste der Teile, SHA-256 je
     Datei), SQLite-Abzug über `VACUUM INTO` in eine Tempdatei, Einstellungen, Kalibrierung,
     Gruppen/Namen/Regeln, Kanäle **ohne Geheimnisse** (Tokens werden durch Platzhalter ersetzt,
     Entscheidung F4).
  2. **Ausgeschlossen:** gelernte GPS-Position, Satellitenwinkel, NTS-Schlüssel und -Zertifikate,
     API-Schlüssel, Kanal-Tokens. Ausschluss als Allowlist der Tabellen/Spalten, nicht als
     Blocklist; die Positionsspalten werden im Abzug geleert (`UPDATE … SET lat=NULL …` im Tempabzug).
  3. `POST /api/restore` in zwei Schritten: hochladen → **Vorschau** („Verlauf 30 Tage, 12 Geräte,
     4 Gruppen, Kalibrierung vom 02.11., 2 Kanäle ohne Token – bitte neu eingeben“) → bestätigen.
     Prüfungen: Größenlimit (eigenes, z. B. 200 MB, statt `MAX_BODY`), nur bekannte Dateinamen,
     keine Pfade mit `..`/absolut/Links (`tarfile` mit `filter="data"`), Prüfsummen, Schema-Version ≤
     eigene (ältere werden migriert, neuere abgelehnt). Vor dem Überschreiben automatisch eine
     Sicherung des jetzigen Stands ins Datenverzeichnis.
  4. Optional: nächtliche Sicherung ins Datenverzeichnis, 7 Stände rollierend (Schalter, Standard aus).
- **Akzeptanzkriterien:**
  - Rundreise: Sicherung → frischer Container → Wiederherstellung → Einstellungen, Gruppen, Namen,
    Kalibrierung und Verlauf identisch (Test vergleicht Tabelleninhalte außer ausgeschlossenen Spalten).
  - Sicherung enthält keine Position und keine Geheimnisse: Test sucht im entpackten Abzug nach den
    bekannten Koordinaten des Testaufbaus (als Zahl und gerundet), nach Satellitenwinkel-Tabellen
    und nach den Test-Tokens der Kanäle.
  - Bösartige Archive (Pfad `../`, Symlink, 1-GB-Datei, falsche Prüfsumme, neuere Schema-Version)
    werden mit klarer Meldung abgelehnt, nichts wird geschrieben.
  - Sicherung von 30 Tagen Verlauf auf dem Pi 4 < 10 s, blockiert andere Requests nicht.
- **Datenschutz:** 🔒 Die Datei enthält Client-IPs und Gerätenamen. Hinweis beim Herunterladen
  („enthält Daten über Geräte in deinem Netz – nicht öffentlich teilen“), Dateiname ohne Hostname
  der Instanz optional. Keine Position, keine Geheimnisse (Standard).
- **Risiko R2:** Wiederherstellen überschreibt. Abhilfe: Vorschau, automatische Sicherung vorher,
  Versionsprüfung, Ereignis „Wiederhergestellt aus Sicherung vom …“.

### T6. Uhr-Werkstatt: `/clock` wird zur Spielwiese

- **Nutzen:** Spaß mit Zweck – `/clock` ist die Seite, die Nutzer anderen zeigen (Rack-Monitor,
  Küche, Werkstatt). Ton auf der Sekunde hilft beim Stellen von Uhren ohne NTP (Backofen, Auto,
  Armbanduhr). „Wie falsch geht dein Gerät?“ macht die Genauigkeit für Familie und Kollegen erlebbar.
- **Aufwand:** ◆ (2–3 PT, je Design ≈ ½ Tag).
- **Umsetzungsskizze:**
  1. **Designs** (Auswahl im Browser gemerkt, `?design=`): zum Start vier – **Bahnhofsuhr** (SVG,
     Sekundenzeiger mit Halt auf der 12), **Nixie** (CSS-Glow), **Klappzahlen** (Flip je Ziffer),
     **Wortuhr** („ES IST VIERTEL NACH ZEHN“). Binär/7-Segment später. Alle mit
     `prefers-reduced-motion` ruhig.
  2. **Kiosk** `?kiosk=1`: ohne Leiste, Mauszeiger versteckt, Wake Lock (gibt es schon), Status-Ticker
     unten. **E-Ink** `?eink=1`: schwarzweiß, nur Minutenwechsel. Zweite Zeitzone `?tz=`.
  3. **Ton auf der Sekunde** (WebAudio, erst nach Klick): kurzer Piep jede Sekunde, langer zur
     Minute, „Uhr stellen“-Countdown („Drücke bei 0“). Geplant mit `AudioContext.currentTime` und
     dem Versatz aus `clocksync.js`; Anzeige der erwarteten Genauigkeit (±5 ms Ziel, Laufzeit des
     Lautsprechers nicht enthalten – steht im ⓘ).
  4. **„Wie falsch geht dein Gerät?“:** `clocksync.js` misst den Versatz der Browseruhr ohnehin;
     groß anzeigen mit Ampel und Erklärung („dein Handy holt die Zeit vom Mobilfunknetz“). Hinweis,
     dass Browser die Uhr teils runden.
  5. Osterei nebenbei: am 30.6./31.12. Banner „23:59:60 wäre heute möglich“ (aus `leap.py`).
- **Akzeptanzkriterien:**
  - Jedes Design zeigt im Playwright-Test mit fester Serverzeit die richtige Uhrzeit (Bild- bzw.
    DOM-Vergleich), auch bei 390 px und im Rotlicht-Modus.
  - Ton: im Test mit gemockter `AudioContext` liegt der geplante Startzeitpunkt innerhalb ±2 ms
    der vollen Sekunde nach Versatz.
  - `/clock` ohne Login (E7) zeigt weiterhin keine Konfigurationsdaten; neue Parameter werden
    allowlist-geprüft (`design`, `kiosk`, `eink`, `tz` aus `Intl.supportedValuesOf('timeZone')`).
  - CPU im Kiosk-Modus auf dem Pi-Browser < 10 % (Animationen per CSS, nicht per JS-Schleife).
- **Datenschutz:** Der Browserversatz wird nur im Browser angezeigt, nicht gespeichert und nicht
  gesendet.

### T7. „Heute“-Zeitleiste und Ereignismarker

- **Nutzen:** „Was war um 03:12?“ ist die häufigste Frage nach einem Alarm. Verlauf und
  Ereignisprotokoll liegen schon vor, aber getrennt.
- **Aufwand:** ◆◆ (3–4 PT).
- **Umsetzungsskizze:**
  1. **Ereignismarker** in allen Zeitdiagrammen (`charts.js`: senkrechte dünne Linie mit Symbol,
     Tooltip mit Ereignistext, Filter nach Art). Zuerst – allein schon ◆ und nützlich.
  2. **Zustandsband 24 h** auf der Übersicht: farbiges Band (synchron / Warnung / Fehler / Holdover),
     Marker für GPS-Fix weg, Quellenwechsel, Neustart. Klick → Seitenleiste „so sah es um 03:12
     aus“ (Quelle, Offset, Fehlerschranke, Satelliten – aus `history`, nächstgelegener Punkt).
  3. **Tagesbericht-Karte** „Gestern: 99,8 % synchron, schlechtester Wert ± 1,2 ms, 12 Geräte,
     GPS 21 h nutzbar, Pi ohne Unterspannung“. In 1.6.1 optional als tägliche Nachricht über
     vorhandene Kanäle (opt-in, Text durch `check_no_leaks`).
- **Akzeptanzkriterien:**
  - Replay eines Tages mit 3 bekannten Ereignissen: genau 3 Marker an den richtigen Stellen
    (± 1 Pixel-Bucket), Band zeigt die Holdover-Phase.
  - Kennzahlen des Tagesberichts stimmen mit einer unabhängigen SQL-Rechnung im Test überein.
  - Übersicht mit Band lädt auf dem Pi 4 < 500 ms Serverzeit (vorverdichtet, kein Rohverlauf).
- **Datenschutz:** nur lokal; Tagesbericht-Nachricht ohne IPs/MACs (nur Anzahl Geräte, E-Regel aus
  1.5: eigener Gerätename höchstens).

## 3. Scheiben 1.6.x

| Release | Inhalt | Voraussetzung |
|---|---|---|
| **1.6.1** | **Ruhiger Betrieb** (Neustart-Koordinator, Zustand der Benachrichtigungen/Alarme überlebt Neustart) – aus dem 1.7-Entwurf vorgezogen (Entscheidung F1), weil es Fehlerbehebung ist und 1.7 dann auf ruhigem Grund steht. **Hilfe** mit Inhaltsverzeichnis, Sprungmarken und Unterseiten (`#/hilfe/gps`), ⓘ mit „mehr in der Hilfe →“. **PPS-Bastelanleitung** mit Prüfassistent auf „Uhr & Hardware“ (Empfänger mit PPS-Ausgang am GPIO, `dtoverlay=pps-gpio`, ehrliche Erwartung µs statt ms). **Prometheus**: Metriken je Gruppe (je Gerät nur per Schalter, Obergrenze ≈ 100), Ereigniszähler, Holdover-Ergebnis, GNSS-Störung, Pi-Zustand, Automatik-Status; Grafana-JSON aktualisiert. Tagesbericht als Nachricht (opt-in). Restliche Einstellungen 2.0, falls aus 1.6.0 gerutscht. | 1.6.0 |
| **1.6.2** | **Satelliten-Spuren** (Entscheidung F5): Winkel alle 60 s in eigener Tabelle, nur lokal, 24 h rollierend; Himmelskarte mit Spuren, Zeitraffer-Regler, **Abschattungskarte** (wo steht nie ein Satellit über 10°? – hilft Nutzern mit USB-GPS drinnen ohne PPS bei der Antennensuche). Vorher Test, dass die Tabelle nie in Export, Diagnose, Sicherung, Benachrichtigung oder API gelangt. **Rangliste der LAN-Uhren** („Wer geht am genauesten?“, Podest, Aufsteiger der Woche, aus Uhrgüte je Gerät). **Zeit-Kuriositäten** (GPS-Woche, GPS−UTC, TAI, Julianisches Datum, Countdown Unixzeit 2 000 000 000 und 2038, NTP-Ära 2036, nächste Zeitumstellung). Weitere `/clock`-Designs (Binär, 7-Segment), Konami-Osterei. | F5 ✅ |
| **1.6.3** | **Wochenbericht** als Druckseite `/report?week=` (PDF über die Druckfunktion des Browsers, keine Bibliothek). **Stratum-Baum** als SVG (Quellen → Pi → PTP → Client-Gruppen, Linienfarbe nach Güte). Erfolge/Abzeichen („100 Tage synchron“) dezent, abschaltbar. | – |

Danach beginnt 1.7 (Community: Englisch komplett, Hardware-Bericht, Zeitwächter-Ping, „Von außen
prüfen“; Uhrqualität 2 bleibt im 1.7-Entwurf). Die VPS-Spur kann trotzdem parallel laufen, weil sie
kein ntp-gui-Release braucht.

## 4. Bewusst nicht in 1.6

- **Jede neue Verbindung nach außen** und jeder Community-Dienst (→ 1.7).
- **Englisch komplett** (→ 1.7). In 1.6 nur: kein halbes Englisch mehr (F2 unten), neue Texte gleich
  als Schlüssel.
- **MQTT/HA-Discovery:** E4 gilt weiter (5 Nachfragen oder fertiger PR). Für Home Assistant reicht
  die REST-Doku; ein fertiges HA-Paket (YAML) ist Doku und kann jederzeit kommen.
- **u-blox schreiben:** schreibt auf Hardware (R3), braucht Testhardware und HCL-Berichte → 1.7+.
- **Temperaturausgleich anwenden:** Daten zeigen keinen Zusammenhang mit der CPU-Temperatur.
- **Lokale Zeitstempelstelle (RFC 3161):** Kryptografie, Schlüsselverwaltung, falsch verstandene
  Rechtswirkung – nicht machen.
- **Uhrqualität 2 (Holdover-Prognose, „Was bringt mein GPS?“):** bleibt im 1.7-Entwurf, damit 1.6
  nicht überläuft. Die Allan-Abweichung ist schon mit 1.5.4 gekommen.
- **Neue Automatiken**, die in die Quellenauswahl eingreifen.
- **Eigenes Frontend-Framework oder Build-Schritt:** die Bausteine bleiben Vanilla-JS-Module.

## 5. Risiken

| Risiko | Wirkung | Abhilfe |
|---|---|---|
| GUI-Umbau aller Seiten (T2) | neue Darstellungsfehler, lange PR-Reviews | Bausteine zuerst; Seite für Seite; Playwright-Rundgang als Pflicht-Test; Vorher/Nachher-Screenshots |
| Navigation neu | Nutzer finden Dinge nicht, Lesezeichen brechen | Weiterleitungen alter Routen, kurzer Hinweis „Navigation neu“ einmalig, CHANGELOG mit Tabelle alt → neu |
| Wiederherstellen (T5) | Datenverlust, bösartiges Archiv | Vorschau, Auto-Sicherung vorher, `tarfile` `filter="data"`, Allowlist der Dateien, Prüfsummen, Versionsprüfung, Fuzz-Test |
| Position in Sicherung oder Diagnose | Ortsbestimmung möglich | Allowlist statt Blocklist, Test mit bekannten Testkoordinaten, Satellitenwinkel nie exportieren |
| B4-Fix (Aufräumen aussetzen) | Datenbank wächst bei dauerhaft falscher Uhr | Aussetzen nur bei unplausibler Zeit, Ereignis + Hinweis; Größenobergrenze bleibt als harte Grenze |
| Umfang 1.6.0 (≈ 22–31 PT) | Release zieht sich, 1.7 rückt weg | feste Rutsch-Reihenfolge (Abschnitt 1); B1/B2 notfalls als 1.5.5 vorab |
| CSP-Header | einzelne Seiten brechen (Inline-Styles/Handler) | erst `Content-Security-Policy-Report-Only` in einem Testlauf, Playwright prüft Konsolen-Verstöße |
| Textkürzung (T2) | Erklärtiefe geht verloren | nichts löschen, nur ins ⓘ oder in die Hilfe verschieben; Wortzahl je Seite als Messwert im PR |
| Spielereien verdrängen Pflicht | Fehler bleiben liegen | T1 vor allem anderen; T6 nur, was bis zum Freeze fertig ist |

## 6. Entschiedene Fragen

Entschieden am 08.11.2026 nach der jeweiligen Empfehlung.

| # | Frage | Entscheidung |
|---|---|---|
| F1 | **Ruhiger Betrieb** (Neustart-Koordinator, Zustand überlebt Neustart) aus dem 1.7-Entwurf nach **1.6.1** vorziehen? | **Ja.** Es ist Fehlerbehebung (1.5.1–1.5.4 gingen auf diese Wechselwirkungen zurück), komplett lokal, und 1.7 baut dann auf ruhigem Grund. |
| F2 | **Sprache bis 1.7:** Standard immer Deutsch, Englisch nur auf ausdrücklichen Wunsch als „English (Beta)“ – statt automatisch nach Browsersprache? | **Ja.** Englisch bis 1.7 nur als „Beta“. Halbes Englisch ist schlechter als Deutsch. Automatische Wahl erst, wenn 1.7 Englisch vollständig hat. |
| F3 | **Navigation 11 → 7 Einträge** mit Untergruppen „Uhr & Hardware“ und „System“, auf dem Handy untere Leiste? | **Ja**, 7 Einträge; alte Links und Lesezeichen leiten weiter. Der größte einzelne Gewinn auf dem Handy. |
| F4 | **Sicherung mit Geheimnissen** (Kanal-Tokens, API-Schlüssel)? | **Nein.** Keine Tokens in die Sicherung. Ohne neue Abhängigkeit gibt es keine gute Verschlüsselung; Tokens nach der Wiederherstellung neu eingeben (die Vorschau listet sie). Position und NTS-Schlüssel nie. |
| F5 | **Satellitenwinkel speichern** (24 h, nur lokal) für Spuren, Zeitraffer und Abschattungskarte in 1.6.2? Winkel über die Zeit verraten grob den Standort. | **Ja, nur lokal 24 h** – nie in Export, Diagnosepaket, Sicherung, Benachrichtigung oder API. Eigene Tabelle, Ausschluss per Allowlist mit eigenem Test; Schalter „Satellitenverlauf aufzeichnen“, Standard an, im ⓘ erklärt. |

## Anhang A: Bestätigte Fehler

Am Code gegengeprüft (Prüfung „Fehler für 1.6“). **27 bestätigt** (8 Backend, 1 Doku-Lücke,
14 Frontend, 4 Kleinkram), 1 plausibel, 3 unbestätigt. Vorrang: **B1, B2, F1, F2, F3**.

| # | Fehler | Ort | Status | Vorrang | Behebung (Kurz) |
|---|---|---|---|---|---|
| B1 | Kalibrierkarte lädt standardmäßig den gesamten Verlauf (`window=0`, auch `nan`), alle 15 s; umgeht `CALIBRATION_DEFAULT_WINDOW` | `gps.js:216`, `server.py:1539f`, `autocal.py:733` | bestätigt | **hoch** | Standard 24 h, `window<=0`/`nan` → Standard, Gesamtverlauf verdichtet |
| B2 | Kein Socket-Timeout: Request ≤ 64 KiB, der weniger Bytes schickt als angekündigt, hält einen Thread für immer | `server.py` `class Handler` | bestätigt | **hoch** | `Handler.timeout = 30` |
| B3 | `WEB_BIND` auf IPv6 scheitert (AF_INET fest), jeder `OSError` als „Port nicht verfügbar“ gemeldet | `QuietHTTPServer`, `server.py:1993ff` | bestätigt | mittel | `address_family` aus Adresse, echte Fehlermeldung |
| B4 | Aufräumen nach Wanduhr: Zeit in der Zukunft löscht `events` und `clientmon_samples` (bei `clientmon_clients` nur nicht aktuelle Geräte) | `events.prune`, clientmon | bestätigt (Einschr.) | mittel | Aufräumen nur bei plausibler Zeit |
| B5 | Intervalle nach Wanduhr (Cache-TTL, `_last_save`, Hotplug/Dienste/NTS-Zertifikat in `entrypoint.sh`) | `gps.py:221`, `ptp.py:188`, `history.save`, `entrypoint.sh:71` | bestätigt | gering | `time.monotonic()`, `$SECONDS` |
| B6 | `INSERT OR REPLACE` beim Flush überschreibt; Diagramme können stehen bleiben | `history.py:186` | bestätigt | mittel | `INSERT OR IGNORE` |
| B7 | Uptime nach Wanduhr | `server.py:88/541/1675` | bestätigt | gering | `time.monotonic()` |
| B8 | Tempdateien in confgen werden nicht aufgeräumt; scheitert `ptp4l.conf`, läuft chronyd mit neuer Datei, Status sagt „bisherige Einstellungen aktiv“ | `confgen._write`, `apply()`, `reload_services` | bestätigt | mittel | erst beide rendern, dann umbenennen, `try/finally unlink` |
| B9 | Doku: konkrete nginx-Zeile `proxy_set_header Host $host;` fehlt (Verhalten des Codes korrekt) | `docs/integrationen/https.md:21` | bestätigt (Doku) | gering | Zeile ergänzen |
| F1 | Kopfzeile formatiert in Browser-Zeitzone, Etikett zeigt Server-Zeitzone | `app.js:183` | bestätigt | **hoch** | `timeZone: sys.timezone` |
| F2 | Verbindungsverlust: Inhalt bleibt wie aktuell stehen; kein `online`/`visibilitychange` in `app.js` | `app.js` | bestätigt | **hoch** | „veraltet seit …“-Overlay, Handler |
| F3 | Endloses „Lade …“, weil `ctx.data()` bei Fehler `undefined` liefert | `clients.js:98/141/230/359`, `clockquality.js:52/123`, `overview.js:459` | bestätigt | **hoch** | `errorState`, Fehlerobjekt |
| F4 | Halbes Englisch durch automatische Browsersprache (Kataloge je 95 Schlüssel) | `i18n.js` `browserLanguage()` | bestätigt | mittel | Standard DE (Frage F2) |
| F5 | Checkboxen ohne sichtbare Beschriftung unter 720 px | `.src-editor-head`, `box()` | bestätigt | mittel | sichtbares Label |
| F7 | GPS „Kein Empfänger“ bei entferntem gpsd oder Gerät ohne sysfs-Eintrag | `receivers_info` | bestätigt (seltener) | mittel | aktives gpsd-Gerät schlägt sysfs |
| F8 | Popover schließt bei jedem Scrollen | `ui.js:26` | bestätigt | gering | erst ab 40 px |
| F9 | Kontrast Primärknopf dunkel 3,10:1 | `app.css` | bestätigt | mittel | Farbe anpassen |
| F10 | Kontrast `--ink-muted` hell 4,28:1 auf #f4f6f9 | `app.css` | bestätigt | mittel | dunkler |
| F11 | „jetzt“ außerhalb von min/max (Vergleich mit Fenster-Mittelwerten) | `statsHeader` | bestätigt | gering | Hinweis/Rohwerte |
| F12 | IP-Adressen brechen um | `app.css:712` | bestätigt | gering | `nowrap` |
| F14 | Dezimalpunkt statt Komma | `sources.js:48/63`, `gps.js:363/365/414` | bestätigt | mittel | `fmt*` |
| F15 | Roher ISO-String der GPS-Zeit | `gps.js:411` | bestätigt | gering | `fmtDate` |
| F17 | Veraltete Versionstexte („Temperaturausgleich ab 1.5“) | `clockquality.js:44/71`, auch `help*.js` („Standard ab 1.5.2“) | bestätigt | gering | Texte ohne Versionsgeschichte |
| K1 | `REASON_TONE` ungenutzt | `gpsquality.js:10` | bestätigt | gering | löschen |
| K2 | Kein CSP-Header | `app/*.py` | bestätigt | mittel | CSP setzen |
| K3 | `aria-label` an `span` ohne Rolle | `ui.js:114` | bestätigt | gering | `role="img"` oder Text |
| K4 | „Noch keine Geräte gesehen“ unter gefüllter Liste | `clients.js:244` | bestätigt | gering | Bedingung korrigieren |
| F18 | Titel bei 390 px abgeschnitten | `.topbar h1` | plausibel | gering | kurzer Titel (T2) |
| F6 | Waagerechte Verschiebung auf der Hilfe-Seite | – | unbestätigt | – | im Playwright-Rundgang prüfen |
| F13 | Tabellen bei 390 px ohne Schatten am Rand | `.table-scroll` | unbestätigt (Gestaltung) | – | Karten/Schatten in T2 |
| F16 | Doppelter Phasentext Kalibrierung | – | unbestätigt (von GUI-Durchsicht beobachtet, U11) | – | in T2 |

Kein Fehler: i18n-Speicher roh statt JSON (`writeStored`).

## Anhang B: Beobachtete Ungereimtheiten aus der GUI-Durchsicht

Im Testaufbau gesehen, nicht alle am Code geprüft. Werden in T1/T2 mit erledigt.

| # | Befund | Deckt sich mit |
|---|---|---|
| U1 | „± 1,000 ms“ / „± 14,000 ms“ liest sich als tausend | F14 → `fmtDuration` |
| U2 | gemischte Zahlenformate („0.0008 s“ neben „+828,2 µs“) | F14 |
| U3 | halb übersetzte Oberfläche | F4 |
| U4 | Client-Detailseite leer, obwohl chrony das Gerät kennt | neu |
| U5 | „Noch keine Geräte gesehen“ | K4 |
| U6 | Anfragen/min 6,0 (Übersicht) ↔ 0,0 (Clients) | neu, mit echten Daten prüfen |
| U7 | Hardware-Check „Kein GPS-Empfänger“ trotz 3D-Fix | F7 |
| U8 | Zeitraum-Knöpfe ohne Wirkung auf Uhrqualität | neu |
| U9 | „Uhrqualität i“ – ⓘ im Überschriftentext | K3 (Barrierefreiheit) |
| U10 | „Zustand“ und „Grund“ fast immer gleich | neu |
| U11 | Phase der GPS-Automatik doppelt | F16 |
| U12 | abgeschnittene Auswahllisten („(empfohle“) | neu |
| U13 | abgeschnittene Linien-Endbeschriftungen | neu |
| U14 | `/clock`: „GPS (GPS)“ | neu |
| U15 | Versionsgeschichte im Bedientext | F17 |
| U16 | Rohtext der Ereignisse ungefiltert sichtbar | neu |
| U17 | ⓘ-Tippfläche 18 px (< 24 px WCAG 2.2) | neu |
| I3 | leere Diagramme belegen ≈ 300 px | neu → `chartCard` |
| I4 | Fußzeile mit `/metrics · /api/status · /healthz` für Laien | neu |

Die Messwerte stammen aus einem Playwright-Rundgang gegen den synthetischen Testaufbau. Die
Skripte (Rundgang, Messung, erfundenes `chronyc`/`gpsd`) werden mit T2 als Testwerkzeug ins
Repository übernommen.
