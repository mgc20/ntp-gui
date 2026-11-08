# Version 1.7 (Entwurf): „Nach außen öffnen, ohne die Privatsphäre zu öffnen“

Stand: 08.11.2026 · Entwurf (Plan, noch nicht umgesetzt, offene Fragen in Abschnitt 7) ·
Grundlage: [ROADMAP](../../ROADMAP.md), [CHANGELOG](../../CHANGELOG.md) 1.3–1.5.4,
[Entscheidungen E1–E19](entscheidungen.md), [version-1.5.md](version-1.5.md),
[version-1.6.md](version-1.6.md), [Community-Dienste](community-dienste.md),
[Bausteine](bausteine.md), [Entscheidungsrahmen](entscheidungsrahmen.md).
Zusammengeführt aus drei Blickwinkeln: Community (Reichweite), Maintainer (Aufwand, Risiko,
Sicherheit) und Belege (was die 1.5.x-Releases und echte Daten zeigen).

> **Verhältnis zu 1.6:** Dieser Entwurf war ursprünglich als 1.6 geplant. Entschieden ist:
> **1.6 bleibt rein lokal** (Fehler, Oberfläche, Spielereien, siehe [version-1.6.md](version-1.6.md)),
> die ersten Community-Funktionen kommen mit **1.7**. Daraus folgt:
> - **Ruhiger Betrieb** (früher K1) ist nach **1.6.1** vorgezogen und hier nur noch Voraussetzung.
> - Die **Allan-Abweichung** (Teil von K4) ist schon mit **1.5.4** erschienen.
> - Die übrigen Nummern (K2–K5) bleiben, damit Verweise stimmen.

## 0. Ziel

Gemeint ist ein **sichtbarer Sprung für Nutzer**, der trotzdem für **einen** Maintainer tragbar
bleibt (F1 aus E15: „schlank und dann nach und nach“). 1.7 soll drei Dinge leisten:

1. **International werden:** vollständige englische Oberfläche. Das ist der größte Hebel für
   Reichweite (Homelab- und Selfhosting-Gemeinschaften, Pool-Betreiber) und damit für Testberichte
   und Beiträge.
2. **Die Community mitmessen lassen:** Hardware- und Empfangsbericht direkt aus dem Dashboard.
   Bisher stammen alle Schwellen (Empfangsampel, „unstet“, GPS-Automatik, ± 10 ms NMEA) von
   **einem** USB-GPS drinnen ohne PPS und synthetischen Tagen.
3. **Den Blick von außen vorbereiten:** Zeit-Check und Server-Test (E17, E18) laufen als eigene
   Spur auf einem VPS des Projekts. Der Knopf „Von außen prüfen“ kommt ins Dashboard, sobald der
   Dienst ruhig läuft. **1.7.0 wartet nie auf den VPS.**

Dabei bleiben die Regeln aus 1.5: lesend vor schreibend, **jede Verbindung nach außen opt-in und
standardmäßig aus**, über `egress.sanitize` mit Vorschau, kein eingehender Port an der Instanz,
**kein Export, keine Benachrichtigung, kein Diagnosepaket und keine Sicherung, die eine
Ortsbestimmung erlaubt**.

**Ausgangslage (offene Reste aus 1.5.x):** u-blox lesen, Englisch über das Gerüst hinaus (heute nur
Navigation, Kopfzeile, Statusband, Einstellungs-Abschnitte; Kataloge ≈ 5 KB gegenüber ≈ 200 KB
deutschen ⓘ-Texten), TOML, Verbund 1, Community-Schritt A (Hardware-Liste, Zeitwächter-Ping).

## 1. Übersicht

Bewertung nach dem [Entscheidungsrahmen](entscheidungsrahmen.md#2-bewertung-fünf-fragen):
Wert = `Nutzen×2 − Aufwand − Risiko`, +1 bei OSS „ja“, +0,5 bei „teilweise“ (E8).
Aufwand: ◆ ≈ 1–3 Abende, ◆◆ ≈ 1–2 Wochenenden, ◆◆◆ mehrere Wochen. PT = Personentage.

| # | Thema | Nutzen | Aufwand | Risiko | OSS | 🔒 | Wert | Stufe |
|---|---|---|---|---|---|---|---|---|
| ~~K1~~ | Ruhiger Betrieb: Neustart-Koordinator, Zustand überlebt Neustart | ★★ | ◆◆ | R2 | nein | – | 2 | vorgezogen nach **1.6.1** |
| K2 | Hardware- und Empfangsbericht („Mit der Community teilen“) + u-blox lesen | ★★★ | ◆◆ (5–7 PT) | R1 | teilw. | 🔒 | **3,5** | **1.7.0** |
| K3 | Englisch komplett: Seiten, Einstellungsfelder, Server-Texte als Schlüssel, Weblate | ★★★ | ◆◆◆ (8–12 PT) | R1 | ja | – | **3** | **1.7.0** (ⓘ-Texte teilweise) |
| K4 | Uhrqualität 2: Holdover-Prognose, „Was bringt mein GPS?“ (nur Anzeige; Allan schon in 1.5.4) | ★★ | ◆ (2–3 PT) | R1 | teilw. | – | **3** | **1.7.0** |
| K5 | Zeitwächter-Ping (Healthchecks / Uptime Kuma, opt-in) | ★★ | ◆ (≈ 1 PT) | R1 | ja | 🔒 | **3,5** | **1.7.0** |
| – | Einstellungen als Datei (TOML) | ★(★) | ◆ | R1 | teilw. | – | 1,5 | 1.7.1 |
| – | „Von außen prüfen“ (Knopf im Dashboard) | ★★★ | ◆ hier, ◆◆◆ Dienst | R2 | teilw. | 🔒 | 3 | 1.7.2, nach VPS-Spur |
| – | Verbund 1, DNS-Filter im LAN lesen | ★★ | ◆◆ | R2 | ja | – | 1–2 | 1.7.3 |
| – | GPS-Startwerte aus der HCL, Schwellen nachschärfen | ★★ | ◆ | R1 | – | – | 2,5 | 1.7.4 |
| – | u-blox schreiben (feste Voreinstellungen) | ★★ | ◆◆◆ | R3 | ja | – | −1 | 1.7.5 experimentell oder später |

**Schätzung 1.7.0:** ≈ 16–23 PT, mit 30 % Puffer (1.5 hat gezeigt, dass Prüfbefunde Zeit
verdrängen) ≈ 7–9 Wochenenden. Die VPS-Spur läuft daneben (≈ 10–14 PT, eigenes Repository).

### Leitlinie

- **Sichtbar und schlank zugleich:** Sichtbar für Nutzer sind K2, K3, K4 und K5. Sie bauen auf dem
  ruhigen Betrieb aus 1.6.1 auf.
- **Keine neue Automatik in 1.7.0.** K4 zeigt nur an. Eine Rückfallebene mit Blick auf den Holdover
  kommt frühestens in 1.7.x und nur nach F5.
- **Kein Dienst des Projekts im Kern.** Alles in 1.7.0 funktioniert ohne VPS. Der Hardware-Bericht
  geht vom **Browser** zu GitHub, der Ping an einen Dienst des Nutzers.
- **Einzige neue Abhängigkeit:** `python3-gps` (Debian, ≈ 0,6 MB, für `ubxtool`), wie schon in
  version-1.5.md F2 empfohlen. Kurz-ADR.

### Reihenfolge innerhalb von 1.7.0

1. **K5** und **K2** (klein, unabhängig, früh fertig).
2. **K3** läuft parallel ab Beginn (Menge, nicht Schwierigkeit).
3. **K4** zuletzt (braucht Verlauf und Holdover-Messungen).

Wenn K3 nicht rechtzeitig fertig wird, rutscht der Rest der Seiten nach 1.7.1, ohne den Kern zu
brechen. Englisch darf hinterherhinken.

## 2. Kern 1.7.0 im Einzelnen

### K1. Ruhiger Betrieb – vorgezogen nach 1.6.1

Steht jetzt in [version-1.6.md, Abschnitt 3](version-1.6.md#3-scheiben-16x). Kurz: ein
Neustart-Koordinator, durch den alle Automatiken gehen (Änderungen sammeln, gemeinsam anwenden,
Obergrenze je Tag, laufende Tests haben Vorrang, jede Entscheidung als Ereignis mit Grund), und
der Zustand von Benachrichtigungen und Client-Alarm überlebt einen Neustart. Die Restposten der
Abschlussprüfung 1.5.0 sind mit 1.5.4 erledigt.

### K2. Hardware- und Empfangsbericht + u-blox lesen 🔒

- **Nutzen:** Zeigt, welcher Empfänger wo funktioniert. Liefert echte Daten, um die Schwellen
  nachzuschärfen, und ist die Grundlage für GPS-Startwerte (1.7.4) und u-blox schreiben (1.7.5).
  Für einfache USB-Empfänger ohne PPS steht dann ehrlich da, was sie können und was nicht (z. B.
  „u-blox 7, kein Timing-Modus, kein PPS am USB“).
- **Aufwand:** ◆◆ (Bericht 2–3 PT mit Action im Community-Repository, u-blox lesen 3–4 PT).
- **Umsetzungsskizze:**
  1. **u-blox lesen** über gpsd/`ubxtool` (nur Polls): `MON-VER` (Chip, Firmware, Protokoll),
     `MON-HW` (Antennenstatus, Jamming-Indikator), unterstützte Systeme. Anzeige im Hardware-Check.
     Der Jamming-Wert fließt als **schwacher** Befund in die Störungserkennung (`gnssguard`).
     Polls laufen über den Neustart-Koordinator aus 1.6.1 und lösen nie einen Neustart aus.
  2. **Bericht nach Vertrag `hardware-report@1`:** feste Allowlist der Felder, dann
     `egress.sanitize("community")` und `check_no_leaks`, dann **Vorschau** im Dashboard.
  3. Knopf „Auf GitHub öffnen“: Der **Browser** öffnet ein vorausgefülltes Issue im Repository
     `ntp-community` (Issue-Formular wie `.github/ISSUE_TEMPLATE/hardware.yml`). Die Instanz selbst
     baut keine Verbindung auf.
  4. Eine GitHub Action prüft den Bericht erneut gegen die Allowlist (zweite Sperre), der
     Maintainer gibt per Label frei. Daraus entsteht eine Tabelle (HCL) im Repository bzw. auf der
     Website.
- **Felder (Allowlist):** Modell, Chip, Firmware, Anbindung (USB/UART), PPS-Art, Plattform
  (z. B. „Raspberry Pi 4“), ntp-gui-Version; Empfangskennzahlen gerundet: Fix-Anteil (5 %-Stufen),
  Fix-Wechsel je Stunde, Median-C/N0 der vier stärksten Satelliten (ganze dB-Hz), genutzte
  Satelliten, kalibrierter Offset und Streuung (auf 1 ms gerundet), Messdauer; Datum nur als
  Kalenderwoche.
- **Akzeptanzkriterien:**
  - Replays u-blox 7 und M8/F9: Chip und Firmware korrekt erkannt; Empfänger ohne UBX
    (z. B. reines NMEA) → „nicht verfügbar“ statt Fehler.
  - Test: Kein Bericht enthält Position, Satellitenwinkel (Azimut/Elevation), Seriennummer,
    MAC-Adresse, Hostname, IP oder Zeitstempel genauer als die Woche. Ein Fuzz-Test mit
    absichtlich eingeschleusten Feldern muss vom Filter **und** von der Action abgewiesen werden.
  - Vorschau zeigt exakt den Text, der im Issue landet, und den Hinweis „öffentlich an deinem
    GitHub-Konto“.
  - Ohne Klick passiert nichts; die Funktion ist ohne Internet sichtbar, aber der Knopf erklärt,
    dass der Browser GitHub erreichen muss.
- **Datenschutz:** Kein Feld und keine Kombination erlaubt eine Ortsbestimmung: keine Position,
  keine Winkel (aus Satellitenwinkeln und Zeit ließe sich der Ort rekonstruieren), Zeit nur auf die
  Woche, C/N0 gerundet. Der Bericht ist öffentlich am GitHub-Konto des Nutzers – das steht in der
  Vorschau. Kein Upload an einen Server des Projekts (F4).

### K3. Englisch komplett

- **Nutzen:** Größter Hebel für Reichweite und Mitmachen. Ohne Englisch bleiben Hardware-Berichte,
  Issues und Tests auf den deutschsprachigen Raum beschränkt. Bis dahin gibt es Englisch nur als
  „English (Beta)“ auf ausdrücklichen Wunsch (Entscheidung F2 in 1.6).
- **Aufwand:** ◆◆◆ (Seiten 3–5 PT, Server-Texte auf Schlüssel und Parameter 3–5 PT, erste ⓘ-Texte
  2–3 PT mit KI-Erstübersetzung). Dauerhaft: jeder neue Text kostet doppelt.
- **Umsetzungsskizze:**
  1. **Seiten:** GPS, Zeitquellen, Clients, Ereignisse, Diagnose, alle Einstellungsfelder.
  2. **Server-Texte als Schlüssel mit Parametern:** Hinweise, Ereignisse, Benachrichtigungen.
     Sprache der Benachrichtigungen als eigene Einstellung.
  3. **ⓘ-Texte in 1.7.0:** Übersicht, Zeitquellen, GPS-Grundlagen. Rest laufend in 1.7.x.
  4. **Weblate-Projekt** (gehostet, OSS-Tarif) mit Deutsch als Referenz; für Mitübersetzer
     geöffnet ab 1.7.1.
  5. Erst wenn Englisch vollständig ist: Sprache automatisch nach Browser wählen, „Beta“ entfällt.
- **Akzeptanzkriterien:**
  - Mit Sprache „en“ zeigt keine Seite und kein Einstellungsfeld deutschen Text (automatischer
    Test über alle Routen; Ausnahme: ⓘ-Texte außerhalb des 1.7.0-Umfangs mit Hinweis „not yet
    translated“).
  - Test meldet fehlende Schlüssel als **Warnung**, nicht als Fehler. Deutsch bleibt vollständig.
  - Datenschutztest (`check_no_leaks`) läuft für **jede** Sprache der Benachrichtigungen.
  - Platzhalter-Prüfung: Jede Übersetzung enthält dieselben Parameter wie der deutsche Text.
- **Datenschutz:** keine neue Verbindung. Weblate bekommt nur Kataloge, keine Nutzerdaten.

### K4. Uhrqualität 2 – „Was bringt mein GPS?“

- **Nutzen:** Eine ehrliche Antwort für die vielen Nutzer mit GPS ohne PPS. In einem typischen
  Aufbau (Raspberry Pi, USB-GPS ohne PPS, mehrere NTS-Quellen) liegt der Holdover bei rund 1 ms in
  12 h, das NMEA-GPS nach der Kalibrierung bei etwa ± 16 ms (E19). Linear gerechnet läuft die freie
  Uhr bei einem Internet-Ausfall dann tagelang genauer als das GPS; real vermutlich kürzer, weil die
  Frequenz dem Tagesgang folgt. Bisher sagt das Dashboard das niemandem.
- **Aufwand:** ◆ (2–3 PT; die Allan-Abweichung gibt es seit 1.5.4).
- **Umsetzungsskizze:**
  1. **Holdover-Prognose** aus den eigenen Holdover-Tests der Instanz: erwartete Abweichung nach
     1 h, 12 h, 24 h, 7 Tagen, mit Unsicherheitsband.
  2. **Vergleich „freie Uhr vs. GPS“:** Ab wann ist die freie Uhr schlechter als die
     Fehlerschranke des GPS? Ein Satz plus kleines Diagramm im Hardware-Check.
  3. **Nur Anzeige.** Keine Änderung an der Quellenauswahl von chrony (siehe F5).
- **Akzeptanzkriterien:**
  - Ohne mindestens einen abgeschlossenen Holdover-Test: „noch keine Messung – Holdover-Test
    starten“ statt einer erfundenen Zahl.
  - Prognose auf synthetischen Daten (bekannte Drift und Rauschen) innerhalb des angezeigten
    Unsicherheitsbands.
  - Berechnung auf dem Pi 4 unter 2 s für 30 Tage Verlauf (Leistungsbudget-Test).
- **Datenschutz:** nur lokal. Ins Diagnosepaket nur die Kennzahlen, keine Rohzeitreihe.

### K5. Zeitwächter-Ping 🔒

- **Nutzen:** Die eigene Benachrichtigung kann den eigenen Ausfall nicht melden. Ein regelmäßiger
  Ping an einen Dienst des Nutzers (Uptime Kuma Push, eigenes Healthchecks, healthchecks.io)
  schlägt Alarm, wenn ntp-gui oder der Pi stumm wird. Passt zur schon dokumentierten Anbindung von
  Uptime Kuma.
- **Aufwand:** ◆ (≈ 1 PT, rund 30 Zeilen plus Einstellung und ⓘ).
- **Umsetzungsskizze:** Einstellung „Wächter-URL“ und Intervall. Alle N Minuten `GET <url>` bei
  „alles gut“, `GET <url>/fail` (bzw. Uptime-Kuma-Status `down`) bei eigenem kritischen Zustand.
  Neuer Ausgangs-Zweck `heartbeat` mit **leerer** Feldliste, über das Notify-Modul („eine Tür
  nach draußen“). Kein Dienst des Projekts.
- **Akzeptanzkriterien:**
  - Standard aus; ohne URL keine einzige Verbindung (Test).
  - Der Ping enthält keine Nutzdaten, keine Query-Parameter außer denen, die der Nutzer selbst in
    die URL geschrieben hat.
  - Zeitlimit kurz (z. B. 10 s), ein hängender Wächter blockiert nichts; Fehler nur als Ereignis.
  - Funktioniert mit Uptime Kuma Push und Healthchecks (Container-Test gegen beide).
- **Datenschutz:** ehrlicher Hinweis in ⓘ: Der Betreiber des Wächters sieht die öffentliche IP und
  die Laufzeiten der Instanz. Daher Empfehlung: eigener Dienst im LAN.

## 3. VPS-Spur parallel (Repository `ntp-community`, kein ntp-gui-Release)

| Schritt | Inhalt | Aufwand | Betrieb |
|---|---|---|---|
| B1 | Zeit-Check-Website (E18): Hugo auf GitHub Pages bzw. dem VPS (E14), Caddy ohne Zugriffslog, Erklärseiten aus `help.json`, HCL-Tabelle aus K2 | 2–3 PT + 0,5–1 PT Rechtstexte | ≈ 5–10 €/Monat, Impressum, Datenschutzerklärung |
| B2 | Server-Test in Go (E11) mit beevik/ntp und beevik/nts, **nur als Selbsttest**: Ziel ist die Quell-IP, kein Zielfeld. NTP, NTS-KE, Zertifikat (Tage bis Ablauf), Mode 6/7 (offener Verstärker), Note A–F. Limits im Speicher, Zähler gehasht mit Tagessalz, keine Ergebnis-URL | 7–10 PT | Abuse-Meldungen, `govulncheck`, Dependabot, Opt-out-Liste, ≈ 1–2 h/Monat |
| C | ntp-gui selbst als Pool-/NTS-Server auf dem VPS | 1–2 PT | Dauerversprechen, nach 4 Wochen Probebetrieb |

- **Datenschutz:** keine Zugriffslogs (die Deploy-Pipeline prüft, dass im Caddyfile kein `log`
  steht), keine Cookies, kein Analytics, keine Datenbank, keine Daten über Instanzen. Kein Dienst,
  den eine Instanz zum Funktionieren braucht.
- **Risiko beevik/nts:** Bus-Faktor 1, keine Releases → pinnen und vendoren. Ausstieg nach E9:
  NTS-Prüfung abschalten, NTP-Prüfung bleibt.
- **Blockiert durch:** Rechtliches (Impressum) und Domain (F2).

## 4. Scheiben 1.7.x

| Version | Inhalt | Bedingung |
|---|---|---|
| **1.7.1** | Einstellungen als Datei (TOML): Import mit `tomllib`, Export ohne Geheimnisse, gleicher Validator wie die Oberfläche, Allowlist der Schlüssel, unbekannter Schlüssel → ganzer Import abgebrochen, Rundreise Export → Import identisch. Rest von K3 (ⓘ-Texte Teil 2), Weblate für Mitübersetzer offen. Doku: keepalived/VRRP. | keine |
| **1.7.2** | **„Von außen prüfen“** im Dashboard: eigener Ausgangs-Zweck `external_test`, Vertrag `external-test-request@1` (Ausnahme nur `allow_fields={"nts.name"}`), opt-in, Vorschau, nur ausgehend. Ergebnisse (auch Laufzeiten je Standort) nur an den Aufrufer, keine teilbare URL. ⓘ zu CGNAT, DS-Lite und Hairpin: „von außen nicht erreichbar“ ist oft die richtige Antwort. Fällt der Dienst aus: „Dienst nicht erreichbar“, Instanz läuft normal weiter. | B2 läuft **≥ 4 Wochen** stabil |
| **1.7.3** | Verbund 1: Übersicht und Gegenmessung zweier Instanzen, Doku für WireGuard/Tailscale/Headscale, kein Relay. DNS-Filter im LAN lesen (z. B. AdGuard Home oder Pi-hole; opt-in, nur LAN, eigener Zweck `lan_dns`, nur lesend): prüft, ob die Ausnahme für ntp-gui bei der Umschreibung gesetzt ist. | keine |
| **1.7.4** | GPS-Startwerte aus der HCL (Median ab ≥ 3 Berichten je Modell), **beim Release fest eingebaut**, keine Verbindung zur Laufzeit. Schwellen (Empfangsampel, „unstet“, ± 10 ms NMEA) aus den Berichten nachschärfen. Nur bei Ja zu F5: Rückfallebene mit Blick auf den Holdover (opt-in, über die Sperre in `selectctl`). | genug HCL-Berichte; F5 |
| **1.7.5** experimentell | u-blox schreiben, kleinste Form: nur feste Voreinstellungen (stationäres Modell, Satellitensysteme, PPS 1 Hz). Vorher `ubxtool -p CONFIG` sichern, Befehlsvorschau, Knopf „zurück“. Nur für Empfänger mit HCL-Bericht, sonst ausgegraut. | Testhardware (z. B. M8T/F9T); sonst später |

## 5. Bewusst nicht in 1.7

- **Server-Test mit Zielfeld** (öffentliches Formular für fremde Ziele): SSRF, Missbrauch als
  Reflektor.
- **Eigener Zeitwächter-Dienst des Projekts** mit Konten und E-Mail: personenbezogene Daten, SMTP,
  Löschkonzept. K5 ist dafür bewusst allgemein.
- **Anonymer HCL-Upload auf den VPS:** mehr Betrieb und Spam-Abwehr; erst wenn GitHub nachweislich
  zu viele Menschen abhält.
- **Schwarm A/B:** frühestens nach Website und Server-Test (A), B nach E13.
- **MQTT/HA-Discovery oder HACS-Integration:** E4 gilt weiter (5 Nachfragen). Für Smart-Home-Systeme
  reicht die REST-Doku.
- **Temperaturausgleich anwenden:** Die bisherigen Daten zeigen keinen Zusammenhang mit der
  CPU-Temperatur (die Frequenz folgt eher der Tageszeit); erst mit einem Sensor nahe am Quarz.
- **Router- und Controller-APIs** (Zugangsdaten, große Angriffsfläche, kleiner Nutzen); nur Doku.
- **Weiter ausgelassen:** ts2phc/Profi-PTP (ohne Tester mit i210/i226/TimeHAT), DCF77, Verbund 2,
  eigenes Relay, TLS im Python-Server (E5), Telemetrie, Auto-Update, Analytics auf der Website.
- **Jede neue Automatik vor dem Neustart-Koordinator (1.6.1).**
- **Keine Kopplung:** Kein ntp-gui-Release wartet auf den VPS.

## 6. Risiken

| Risiko | Wirkung | Abhilfe |
|---|---|---|
| Englisch verdoppelt dauerhaft die Textpflege | Maintainer-Zeit, veraltete Übersetzungen | Deutsch Referenz, Englisch darf hinterherhinken, Test warnt nur; Weblate für Community |
| Datenschutz im öffentlichen Bericht (Kombination von Feldern) | Ortsbestimmung möglich | Allowlist, Rundung, Zeit nur auf die Woche, keine Winkel; zweite Prüfung per Action; Fuzz-Test |
| HCL-Moderation kostet laufend Zeit | Rückstau an Berichten | Action prüft automatisch, Freigabe per Label, keine Pflicht zur Antwort |
| VPS-Spur zieht Zeit vom Kern ab | 1.7.0 verzögert sich | strikte Entkopplung; Knopf erst 1.7.2 |
| Go als zweite Toolchain, beevik/nts Bus-Faktor 1 | Sicherheits- und Pflegelast | pinnen, vendoren, `govulncheck`; Ausstieg nach E9 |
| Recht und Abuse auf dem VPS | Mails, Haftung | Impressum per Anschriftsdienst, Selbsttest ohne Zielfeld, Limits je IP |
| Holdover-Prognose wird als Zusage verstanden | falsche Erwartung | Unsicherheitsband, Grenze in ⓘ, keine Automatik daraus in 1.7.0 |
| `python3-gps` als neue Abhängigkeit | Image-Größe, Updates | Debian-Paket, ≈ 0,6 MB, kurz-ADR |

## 7. Offene Fragen an den Maintainer

Nummern gelten für dieses Dokument; Verweise auf ältere Fragen sind mit „alt“ markiert.

| # | Frage | Empfehlung |
|---|---|---|
| F1 | **Versionsnummer:** 1.7.0 oder bewusst 2.0? Nichts in 1.7 bricht etwas: `/api/v1`, Umgebungsvariablen und Update-Pfad bleiben. | **1.7.0**, als großes Feature-Release angekündigt. 2.0 für einen echten Bruch aufheben: API v2, TOML als führendes Format, Aufräumen alter Migrationen und Variablen, Mindestversion für den Update-Pfad. |
| F2 | **Rechtliches und Domain für den VPS:** Wer steht im Impressum, welcher Domainname? Blockiert B1 und damit 1.7.2. | Anschriftsdienst statt Privatanschrift; Verein erst mit Mitstreitern. Domain kurz und neutral. |
| F3 | **Umfang Englisch in 1.7.0** und **KI-Erstübersetzung** mit Prüfung durch die Community in Ordnung? | Seiten, Einstellungsfelder und Server-Texte vollständig; ⓘ-Texte nur Übersicht, Zeitquellen, GPS-Grundlagen. KI-Erstübersetzung ja, markiert und prüfbar in Weblate. |
| F4 | **Öffentlicher Hardware- und Empfangsbericht:** nur über GitHub-Issues (Konto-Pflicht, öffentlich am Konto)? Dürfen Fix-Anteil, C/N0, Satellitenzahl und kalibrierter Offset hinein? | Nur GitHub. Empfangskennzahlen ja, gerundet, ohne Winkel, ohne Position, Datum nur als Woche. `python3-gps` dafür aufnehmen (F2 alt: ja). |
| F5 | **Rückfallebene mit Blick auf den Holdover (berührt E16):** Darf ntp-gui das GPS ohne PPS bei einem Totalausfall des Internets bewusst zurückhalten, bis die freie Uhr schlechter wäre als das GPS (opt-in)? | Erst die Anzeige aus K4 in 1.7.0, dann mit echten Daten entscheiden; frühestens 1.7.4. Bei schlechtem Internet bleibt das GPS wie bisher Rückfallebene. |

**Ebenfalls noch offen (alt, kein Blocker für 1.7.0):** VPS dauerhaft in den NTP Pool (Empfehlung:
ja, mit ntp-gui selbst, nach 4 Wochen Probebetrieb). Testhardware für u-blox schreiben (M8T/F9T)?
Ohne sie rückt 1.7.5 nach hinten.
