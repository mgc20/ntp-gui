# Version 1.5 und folgende: Staffelung, Bewertung, Abnahme

Stand: 02.11.2026 · Grundlage: [ROADMAP](../../ROADMAP.md), Stand 1.3.2 (`app/clientmon.py`,
`app/enforce.py`, `app/gps.py`, `app/egress.py`, `app/events.py`, `app/store.py`), die 1.4 in Arbeit,
[Entscheidungsrahmen](entscheidungsrahmen.md), [Entscheidungen E1–E14](entscheidungen.md),
[Bausteine](bausteine.md), [Community-Dienste](community-dienste.md), [version-1.4.md](version-1.4.md)

## 0. Was seit 1.4-Planung neu ist (Anlässe)

| # | Anlass | Folge für die Planung |
|---|---|---|
| R1 | AdGuard-DNS-Umschreibung **und** UniFi-NAT-Umleitung gleichzeitig: Schleife, sobald ntp-gui seine eigenen Upstream-Namen über den umschreibenden DNS auflöst | 1.4 bringt eigene DNS-Server/DoT/DoH für ntp-gui. 1.5: **Schleifen erkennen und erklären** (Thema 10) |
| R2 | Messungen der Zeitabweichung von Clients sind besonders gefragt | Clients sind das Alleinstellungsmerkmal. 1.4 baut Clients 2.0; 1.5 setzt mit **Clients 3** fort (Thema 9) |
| R3 | Verbreitetes USB-GPS (z. B. VK-162, u-blox 7, **ohne PPS**), schwacher Empfang drinnen, Fix kommt und geht | sehr verbreitete Billig-Hardware → **„GPS ohne PPS“ ehrlich bewerten und begleiten** (Thema 3), noch vor der u-blox-Werkbank |
| R4 | Diagnosepaket auf dem Pi zu langsam (behoben in 1.3.2) | Leistungsbudget als Regressionstest (Querschnitt, Abschnitt 3) |
| R5 | Maintainer hat VPS, will Community-Nutzen (Website wie ntp-tester.eu, Schwarm, Relay); öffentliche Dienste nicht ausgeschlossen (E10) | konkreter erster Schritt in Abschnitt 4.6: **Zeit-Check-Website + Server-Test** |
| R6 | Grundsätze: größter Community-Nutzen, machbar für einen Maintainer mit KI, Sicherheit durch Einfachheit, OSS wiederverwenden, möglichst viel Funktion | Bewertung unten; „schlankes 1.5.0 + 1.5.x“ wie bei 1.4 (E3) |

## 1. Übersicht

Bewertung nach dem [Entscheidungsrahmen](entscheidungsrahmen.md#2-bewertung-fünf-fragen):
Wert = `Nutzen×2 − Aufwand − Risiko`, +1 bei OSS „ja“, +0,5 bei „teilweise“ (E8).
Aufwand: ◆ ≈ 1–3 Abende, ◆◆ ≈ 1–2 Wochenenden, ◆◆◆ mehrere Wochen.

| # | Thema | Nutzen | Aufwand | Risiko | OSS | 🔒 | Wert | Stufe | Braucht aus 1.4 |
|---|---|---|---|---|---|---|---|---|---|
| 3 | GPS ohne PPS / schwacher Empfang: Empfangsbewertung, Fix-Stabilität, Antennen-Test, Profil „nur NMEA“ | ★★★ | ◆ | R1 | teilw. | – | **4,5** | **1.5.0** | Benachrichtigungen |
| 10 | DNS/NAT-Härtung: Schleifen erkennen, Upstream-Prüfung, Resolver-Zustand | ★★★ | ◆ | R1 | teilw. | – | **4,5** | **1.5.0** (Teile ggf. 1.4.x) | eigene DNS/DoT/DoH |
| 1 | GNSS-Störungen erkennen und melden (Jamming/Spoofing) | ★★★ | ◆◆ | R1 | teilw. | – | **3,5** | **1.5.0** | Benachrichtigungen, Replay |
| 9 | Clients 3: Regeln je Gerät, Gruppen/VLAN-Ansichten, Uhrgüte je Gerät, NTS für Clients, Gerätepass | ★★★ | ◆◆ | R1 | nein | – | **3** | **1.5.0** | Clients 2.0, Benachrichtigungen |
| 13 | Englisch (i18n, Weblate) | ★★★ | ◆◆◆ (Menge) | R1 | ja | – | **3** | Gerüst **1.5.0**, UI **1.5.x**, ⓘ-Texte laufend | – |
| 15 | HTTPS fürs Dashboard: Caddy-Vorlage (E5) | ★★ | ◆ | R1 | ja | – | **3** | **1.5.0** | – |
| 2 | GPS-Sperre per `selectopts` (12b aus 1.4-Plan) | ★★ | ◆ | R2 | ja | – | **2** | **1.5.0** | 1 |
| 8 | Echter Holdover-Test (GPS/PPS auf Zeit abschalten) | ★★ | ◆ | R2 | ja | – | **2** | **1.5.0** | Code von 2 |
| 4 | u-blox lesen (MON-VER, MON-HW, NAV-STATUS … über gpsd) | ★★ | ◆◆ | R1 | ja | – | **2** | **1.5.x** | – |
| 5 | Temperaturausgleich: Fit und Vorschlag | ★★ (★★★ ohne GPS) | ◆◆ | R1 | ja | – | **2** | **1.5.x** | Temperatur aufzeichnen |
| 7 | Allan-Abweichung, „wie lange hält die Uhr?“ | ★★ | ◆◆ | R1 | teilw. | – | **1,5** | **1.5.x** | Verlauf |
| 6 | Temperaturausgleich anwenden + 24-h-Probelauf | ★★ | ◆◆ | R2 | ja | – | **1** | **1.5.x** | 5, Code von 2 |
| 11 | Verbund 1: Übersicht + Gegenmessung | ★★ | ◆◆ | R2 | ja | – | **1** | **1.5.x** | API v1, Schlüssel |
| 14 | MQTT + Home-Assistant-Discovery | ★★ | ◆◆ | R2 | ja | 🔒 | **1** | **nur auf Nachfrage** (E4) | Benachrichtigungen, HA-Doku |
| 16 | Einstellungen als Datei (TOML-Import mit `tomllib`, statt YAML) | ★ | ◆ | R1 | teilw. | – | **0,5** | **1.5.x**, klein | versionierte Einstellungen |
| 12 | Verbund 2: Einstellungen teilen (Leader/Follower) | ★★ | ◆◆ | R3 | – | – | **−1** | **1.5.x experimentell** oder 1.6 | 11 |

### Leitlinie der Staffelung

- **1.5 „GNSS-Werkbank, Clients 3, Uhrqualität“.** Zuerst, was die bekannten Probleme löst (R1, R3)
  und was am meisten gefragt ist (R2). Dann das, was aus den Daten von 1.4
  (Temperatur, Ereignisse, Alarme) Erkenntnis macht.
- **Lesend vor schreibend bleibt.** In 1.5 greift ntp-gui nur über chronys eigene, umkehrbare
  Schalter in die Zeit ein (`selectopts`, `tempcomp`) – immer mit Ereignis, Zeitlimit und Rücknahme.
  Auf den GPS-Empfänger wird **nicht** geschrieben (erst 1.6).
- **Keine neue Python-Abhängigkeit außer `python3-gps`** (Debian, ≈ 0,6 MB, für `ubxtool`; kurz-ADR).
  MQTT (paho) nur, wenn Nachfrage kommt (E4).

### Schnitt: schlankes 1.5.0, dann 1.5.x (wie E3)

| Release | Inhalt | Schätzung |
|---|---|---|
| **1.5.0** | 3, 10, 1, 2, 8, 9, 15, i18n-Gerüst | ≈ 8–10 Wochen |
| **1.5.1** | 4 (u-blox lesen), 7 (Allan), 5 (Temperatur-Fit) | ≈ 4–6 Wochen |
| **1.5.2** | Englische Oberfläche (13), 11 (Verbund 1), 16 | ≈ 4–6 Wochen |
| **1.5.3+** | 6 (tempcomp anwenden, braucht ≥ 4 Wochen Daten aus 1.5.1), 12 experimentell, 14 bei Nachfrage | je 2–4 Wochen |

**Gegenprüfung des Aufwands:** Alles zusammen sind 7 × ◆◆ + 1 × ◆◆◆ + 6 × ◆ – also **5–7 Monate**
für einen Maintainer neben dem Beruf, auch mit KI-Hilfe. Unterschätzt werden erfahrungsgemäß:
Replay-Aufzeichnungen echter Störungen (man braucht sie, bevor man Schwellwerte festlegt),
ⓘ-Texte (jede neue Anzeige, und ab 1.5 zweisprachig) und die Fehlerberichte nach 1.4.
**Wenn die Zeit knapp wird:** Reihenfolge nach Wert **3 → 10 → 1 → 9 → 15 → 2 → 8**, der Rest
rutscht ohne Diskussion in 1.5.x.

## 2. Die Themen im Einzelnen

### 3. GPS ohne PPS und schwacher Empfang (VK-162 & Co.)

- **Ausgangslage:** Der VK-162 ist ein USB-Stick mit u-blox-7-Chip (UBX-Protokoll 14 *(n. g.)*),
  liefert NMEA über USB und **keinen PPS**. Die Zeit aus NMEA schwankt um einige bis einige zehn ms
  und hat einen festen Versatz (Satzende, USB-Puffer) – die GPS-Kalibrierung aus 1.3 kann den
  Versatz lernen, nicht die Schwankung. Mit Internet und ≥ 2 NTS-Quellen ist das Netz meist
  **genauer** als dieser Empfänger. Sein Wert: **Zeit ohne Internet** und **Plausibilitätsprüfung**.
  Das muss das Dashboard ehrlich sagen, statt „GPS = Stratum 1 = besser“ zu suggerieren.
- **Was:**
  1. **Empfangsbewertung (24 h):** Anteil der Zeit mit 3D-/2D-Fix, Fix-Wechsel je Stunde, Median-
     C/N0 der vier stärksten Satelliten, genutzte Satelliten. Ergebnis als Ampel mit Satz:
     „Fix 71 % der Zeit, 14 Wechsel/h – Empfang zu schwach für eine stabile Zeitquelle“.
  2. **Fix-Flattern entschärfen:** 1.3.2 meldet Fix-Ereignisse erst nach 60 s. 1.5 fasst Flattern
     zu einem Zustand „unstet“ zusammen (ein Ereignis mit Zählung statt Paaren) und erklärt die
     Folge für chrony (Quelle wird oft unbrauchbar, chrony wählt dann das Netz – das ist richtig so).
  3. **Antennen-Test:** Knopf „5 Minuten messen“, Stick umstellen, erneut messen, Vergleich
     nebeneinander (C/N0, Satelliten, Fix-Anteil). Nur lokal; Satellitenwinkel werden angezeigt, aber
     wie bisher nie exportiert.
  4. **Praxishinweise in ⓘ:** USB-Verlängerung ans Fenster; USB-3-Ports und -SSDs stören das
     GPS-L1-Band (1,5 GHz) nachweislich – Abstand oder USB-2-Port; Metall- und Wärmeschutzverglasung
     dämpfen stark.
  5. **Profil „GPS ohne PPS“** (Einstellung, Vorschlag aus dem Hardware-Check): größere
     `delay`/Unsicherheit für die NMEA-Quelle, GPS nur auswählbar, wenn keine guten Netzquellen da
     sind (bzw. als Plausibilitätsquelle mit `noselect`, Wahl in der UI). Genaue chrony-Optionen
     (`delay`, `precision`, ggf. `trust`/`noselect`) per Replay mit echter VK-162-Aufzeichnung festlegen.
- **Ehrliche Grenze:** Software macht schwachen Empfang nicht stärker. Timing-Modus/Survey-in gibt es
  beim u-blox 7 nicht.
- **Abnahme:** Replay „VK-162 drinnen“ (Fix flattert) → ein Ereignis „unstet“ statt Dutzender, Ampel
  gelb/rot mit Begründung; Replay „draußen“ → grün; Profil erzeugt eine chrony-Konfiguration, mit der
  chronyd 4.6 startet (Container-Test); ohne Empfänger „nicht verfügbar“ statt Fehler.

### 10. DNS- und NAT-Härtung (Folgen aus R1)

- **Problem:** Schreibt AdGuard `pool.ntp.org` auf ntp-gui um und fragt ntp-gui selbst AdGuard, fragt
  chrony sich selbst. Leitet UniFi zusätzlich **jedes** ausgehende UDP 123 auf ntp-gui um und ist
  ntp-gui nicht ausgenommen, landet auch eine Quelle per IP bei sich selbst. 1.4 löst die
  Namensseite (eigene DNS/DoT/DoH-Server für ntp-gui). 1.5 macht beides **sichtbar**:
- **Was:**
  1. **Schleifen-Erkennung:** Eine Quelle ist „ich selbst“, wenn ihre Adresse eine eigene ist, ihre
     Antwort die eigene RefID/den eigenen Stratum+1 trägt oder `enforce.same_server()` sie als
     dieselbe Instanz erkennt. Ereignis `source/crit` mit Satz: „pool.ntp.org zeigt auf dich selbst –
     vermutlich DNS-Umschreibung ohne Ausnahme für ntp-gui“ bzw. „… NAT-Umleitung ohne Ausnahme“.
     Unterscheidung über die Art (Name vs. feste IP), wie der Selbsttest aus 1.3.2.
  2. **Upstream-Prüfung im Selbsttest:** Für jede eigene Quelle: mit welchem Resolver aufgelöst,
     welche Adresse, antwortet dort wirklich ein fremder Server? Zeigt die Kette
     „Name → Resolver → Adresse → Antwort“.
  3. **Resolver-Zustand:** eigene DoT/DoH-Server erreichbar? Letzte erfolgreiche Auflösung, Fehler
     als Ereignis. Hinweis, dass NTS-Quellen ihren Namen fürs Zertifikat brauchen – eine „letzte
     gute IP“ als Notlösung hilft dort nicht; besser zwei unabhängige Resolver.
  4. **Anleitungen nachschärfen:** AdGuard: „Client-spezifische Regel“ bzw. Ausnahme für die IP von
     ntp-gui; UniFi: Quelle ≠ ntp-gui (steht heute schon im Snippet) – plus Erkennung im Test, ob
     sie greift.
  5. *(Optional, später)* AdGuard-Home-API lesend abfragen (`/control/rewrite/list`), um Konflikte
     direkt zu zeigen. Braucht Zugangsdaten im LAN → eigener Egress-Zweck, opt-in; erst bei Nachfrage.
- **Abnahme:** Lab mit dnsmasq, das den Quellnamen auf ntp-gui umschreibt → Ereignis in ≤ 2 Poll-
  Intervallen, richtiger Satz; nftables-DNAT ohne Ausnahme → „NAT-Umleitung“ erkannt; korrekte
  Konfiguration → kein Ereignis; Unit-Tests für die Entscheidungslogik.

### 1. GNSS-Störungen erkennen und melden

Spezifikation wie [version-1.4.md, Thema 12](version-1.4.md#12-gnss-störungen-lokal-erkennen-15-und-12b-gps-sperren);
Ergänzungen:
- **Je Empfängergeneration ehrlich:** gpsd 3.25 (trixie) liefert C/N0 je Satellit, aber kein `jam`
  (erst 3.26). u-blox `MON-HW` (`jamInd`, AGC) gibt es auch beim u-blox 7, Spoofing-Status
  (`NAV-STATUS flags2`, `SEC-SIG`) erst ab neueren Generationen *(Feldnamen vor Umsetzung gegen die
  u-blox Interface Description prüfen)*. Ohne u-blox-Daten bleiben C/N0-Muster und der Abgleich mit
  den NTS-Quellen – das funktioniert mit **jedem** Empfänger, auch dem VK-162.
- **Stufen:** „Hinweis“ (ein schwaches Signal) → „Warnung“ (zwei Signale) → „Störung“ (starkes
  Signal: Zeitabweichung zu ≥ 2 NTS-Quellen, Positionssprung, Spoofing-Flag). Nur „Störung“ geht
  standardmäßig als Benachrichtigung raus.
- **Kein Ortsbezug nach außen:** Ereignistexte nennen Meter-Abweichung, nie Koordinaten
  (Filtertest je Benachrichtigungskanal).
- **Abnahme:** wie 1.4-Plan, zusätzlich Replay „VK-162 schwacher Empfang“ → höchstens „Hinweis“, nie
  „Störung“ (sonst lernen Nutzer, Alarme zu ignorieren).

### 2. GPS-Sperre per `selectopts`

- `chronyc selectopts <refid> +noselect` bei „Störung“, Freigabe (`-noselect`) nach 30 min ohne
  Signal, höchstens drei Wiederholungen, dann manuell. Reines Jamming → keine Sperre.
- **Einstellung:** aus / nur melden (Standard) / automatisch sperren (opt-in). Gleiches Muster wie
  die GPS-Kalibrierung.
- **Wichtig:** Eine Sperre überlebt einen chronyd-Neustart nicht (Laufzeitschalter). ntp-gui setzt
  sie nach Neustart neu, solange der Zustand „gesperrt“ in SQLite steht – sonst hebt das Speichern
  von Einstellungen die Sperre still auf.
- **Abnahme:** `chronyc sources` zeigt GPS als nicht auswählbar, nach Ablauf wieder auswählbar;
  Sperre übersteht Einstellungs-Speichern; jede Sperre/Freigabe ein Ereignis.

### 8. Echter Holdover-Test

- „Holdover für 1 h / 6 h / 24 h“: **alle** Quellen per `selectopts +noselect` – GPS/PPS und
  Netzquellen. chrony lässt die Uhr dann frei laufen, misst die Netzquellen aber weiter: Sie
  dienen als **Messreferenz**, ohne die Zeit zu beeinflussen. Danach automatisch zurück. Ergebnis: gemessener Zeitfehler
  über die Dauer, neben der Schätzung aus der Allan-Abweichung (7), sobald es die gibt.
- **Sicherheit:** Abbruch-Knopf; automatischer Abbruch bei |Offset| > Grenze (Standard 10 ms);
  Hinweis, dass Clients in der Zeit eine schlechtere Zeit bekommen. Kein Test ohne mindestens zwei
  erreichbare Messreferenzen.
- **Abnahme:** im Lab endet der Test nach Ablauf oder Grenzüberschreitung mit allen Quellen wieder
  auswählbar; Neustart von chronyd während des Tests → Test abgebrochen, Zustand sauber.

### 9. Clients 3 – „mehr davon“

Baut auf Clients 2.0 aus 1.4 auf (Detailseiten, Netzüberblick, aktiv nachmessen, Alarm). Was
dort schon fertig wird, entfällt hier.

- **Regeln je Gerät** (auf den 1.4-Benachrichtigungen): „fragt seit N h nicht mehr“ (Kamera,
  SPS, NAS), „|Abweichung| > X für M min“, „neues Gerät fragt Zeit“ (Inventar-Änderung, nützlich
  für Sicherheit). Entprellt wie alle Ereignisse.
- **Gruppen und VLAN-Ansichten:** Der Kernel entfernt VLAN-Tags vor dem Mitlesen – Gruppen
  entstehen daher aus **Netzen**, die der Nutzer benennt („IoT = 10.0.30.0/24“), mit Vorschlag aus den
  gesehenen /24-Netzen. Je Gruppe: Anzahl, Median-Abweichung, Anteil „gut“. Hinweis „In VLAN 40
  fragt kein Gerät bei dir – fehlt dort die Umleitung?“ verbindet Clients mit „Zeitserver erzwingen“.
- **Uhrgüte je Gerät:** Aus dem Sägezahn der Abweichung zwischen zwei Synchronisierungen folgen
  Abfrage-Intervall und Gangabweichung des Geräts in ppm. Liste „schlechteste Uhren im Haus“.
- **Implementierung erkennen (Heuristik):** Abfrage-Intervall, NTP-Version, Felder in der Anfrage
  (Stratum/RefID gefüllt oder leer, Zufalls-Zeitstempel) → „vermutlich chrony / ntpd / SNTP
  (Windows, IoT) / systemd-timesyncd“. Immer als „vermutlich“, mit Begründung in ⓘ.
- **NTS für Clients:** zeigen, welche Geräte NTS nutzen (`chronyc clients -k` zählt NTS-KE-
  Verbindungen *(Ausgabe vor Umsetzung prüfen)*), und je erkannter Implementierung, ob und wie sie
  NTS kann (chrony, ntpd-rs, NTPsec ja; Windows und die meisten IoT-Geräte nein). NTS-Clients
  schreiben Zufall statt Uhrzeit – passiv „nicht messbar“ ist dort **gutes** Verhalten.
- **Gerätepass:** eine druckbare Seite je Gerät (Browser-Druck, kein Export-Endpunkt): Name,
  Gruppe, vermutete Implementierung, Intervall, Abweichung (Median, P95, 7-Tage-Verlauf),
  Gangabweichung, NTS ja/nein, letzte Anfrage, **Empfehlung** („Windows: `w32tm /config
  /manualpeerlist:<ip> /syncfromflags:manual /update`“). Nützlich für Doku im Homelab und im Betrieb.
- **Daten:** neue SQLite-Tabellen per `store.py`-Migration (`client_labels`, `client_groups`,
  `client_rules`, Stundenaggregate je Gerät, 30 Tage, Obergrenze wie `MAX_CLIENTS`).
- **Datenschutz:** Client-Daten bleiben lokal. In Benachrichtigungen erscheint standardmäßig der
  **eigene Gerätename**, nicht IP oder MAC (Schalter „LAN-Adressen in Nachrichten“, Standard aus).
  Im Diagnosepaket nur mit dem vorhandenen Schalter „Client-Liste“.
- **Abnahme:** synthetischer Client mit 50 ppm Drift und 64-s-Intervall → Uhrgüte 50 ± 5 ppm,
  Intervall 64 s; Regel „fragt nicht mehr“ feuert genau einmal und meldet „wieder da“; Gruppen-
  Zuordnung per Unit-Test (IPv4/IPv6, Überlappung → spezifischeres Netz gewinnt); Gerätepass ohne
  innerHTML mit Daten; Benachrichtigung enthält ohne Schalter keine IP (Filtertest).

### 13. Englisch (i18n)

- Wie 1.4-Plan, Thema 14. **Gerüst in 1.5.0:** Kataloge `app/static/i18n/<lang>.json`, Schlüssel
  statt Text in neuen Seiten, Auswahl in den Einstellungen, Rückfall Deutsch. Die ⓘ-Texte liegen
  schon getrennt (`help.js`, `help-*.js`) – gut für Kataloge. Server-Texte (Ereignisse, Hinweise)
  bekommen Schlüssel + Parameter, damit Benachrichtigungen in der gewählten Sprache gehen.
- **Weblate** (gehostet, für Open Source kostenlos *(n. g.)*), Kataloge bleiben im Repo.
- **Pflegekosten ehrlich:** ab dann kostet jeder neue Text doppelt. Regel: Englisch darf hinterher-
  hinken; ein Test meldet fehlende Schlüssel als Warnung, nicht als Fehler.
- **Abnahme:** Test, dass jeder Schlüssel in `de` existiert; fehlende `en`-Schlüssel fallen auf
  Deutsch zurück; `tests/test_help_coverage.py` prüft weiterhin die deutsche Referenz.

### 15. HTTPS fürs Dashboard (E5: Reverse Proxy)

- E5 bleibt: **kein TLS im Python-Server.** Neu: Caddy-Block (auskommentiert) in
  `docker-compose.all-in-one.yml` mit `tls internal` für das LAN bzw. Let's Encrypt per DNS-Challenge,
  dazu Anleitung „Root-Zertifikat von Caddy auf den Geräten vertrauen“. Dashboard dann nur an
  `127.0.0.1`.
- **Abnahme:** Container-Test startet die Kombination und erreicht das Dashboard nur über HTTPS;
  Doku-Test, dass die Vorlage gültiges Compose ist (`docker compose config`).

### 4. u-blox lesen

- Wie 1.4-Plan, Thema 13 (lesen). Anzeige im Hardware-Check: Chip/Firmware (`MON-VER`),
  Protokollversion, aktive Systeme, Antennen-/Jamming-Zustand (`MON-HW`), Timing-Fähigkeit.
  Für den VK-162 ehrlich: „u-blox 7, kein Timing-Modus, kein PPS am USB“.
- **Abhängigkeit:** `python3-gps` (für `ubxtool`, kurz-ADR). Nur Polls (lesen), immer über gpsd.
- **Abnahme:** Replay mit UBX-Antworten von mindestens zwei Generationen (u-blox 7 und M8/F9).

### 5./6. Temperaturausgleich: Fit, Vorschlag, Anwenden

- 1.4 zeichnet Temperatur auf. 1.5.1 bringt **Fit + Vorschlag** nach [version-1.4.md, Thema 4](version-1.4.md#4-temperaturausgleich-des-quarzes-chrony-tempcomp)
  (Kreuzkorrelation, Klassen, Gerade/Parabel, Punktedatei, ±2 ppm, R²-Schwelle).
- **Anwenden (1.5.3):** Muster aus / vorschlagen / anwenden. ntp-gui schreibt die geglättete
  Temperatur atomar nach `/run/ntp-gui/oscillator_temp`, `tempcomp` in `chrony.conf`, Wächter bei
  veralteter Datei (> 5 Intervalle → tempcomp-Zeile entfernen, Ereignis).
- **24-h-Probelauf:** Vergleich der Frequenz-Restschwankung 24 h vorher/nachher bei ähnlicher
  Temperaturspanne; Verschlechterung > 10 % oder chrony verwirft Werte → automatische Rücknahme mit
  Ereignis. Kein automatisches Nachlernen in 1.5.
- **Abnahme:** wie 1.4-Plan; zusätzlich falsches Vorzeichen → Rücknahme im Probelauf; veraltete
  Temperaturdatei → Rücknahme ohne chronyd-Absturz.

### 7. Allan-Abweichung

- Unverändert nach [version-1.4.md, Thema 3](version-1.4.md#3-allan-abweichung-und-wie-lange-hält-die-uhr);
  in 1.4 nicht gebaut. Ergänzung: Der echte Holdover-Test (8) liefert den Messwert neben der
  Schätzung – das macht die Grenze der Schätzung sichtbar.

### 11./12. Verbund

- **Stufe 1** wie 1.4-Plan, Thema 10. Neu wegen R5: Instanz zu Hause + Instanz auf dem VPS. Ohne
  offenen Port geht das nur über ein Tunnel-Netz – **Doku für WireGuard/Tailscale/Headscale**, kein
  eigenes Relay (Entscheidungsrahmen 6.4 sinngemäß: kein zentraler Dienst des Projekts, den Instanzen
  zum Funktionieren brauchen).
- **Stufe 2** wie 1.4-Plan, Thema 11 (ein Leader, Pull, `shareable: false` als Standard, Diff-
  Vorschau, Schema-Version muss passen). R3 → nur „experimentell“, frühestens wenn Stufe 1 genutzt wird.

### 14. MQTT und Home-Assistant-Discovery

- Spezifikation steht ([version-1.4.md, Thema 2](version-1.4.md#2-mqtt-und-home-assistant)).
  1.4 liefert die REST-Sensor-Anleitung (E4). Bauen erst, wenn Nachfrage da ist – Vorschlag
  für die Schwelle in den offenen Fragen.

### 16. Einstellungen als Datei

- **Kein YAML:** Die stdlib hat keinen YAML-Parser; ein eigener wäre ein Parser für fremde
  Eingaben. Stattdessen **TOML-Import über `tomllib`** (stdlib seit Python 3.11, trixie hat 3.13)
  und Export als TOML (flache Schreibroutine, nur unsere eigenen Typen) bzw. JSON. Gleicher Validator
  wie die UI, Geheimnisse nie im Export. „Konfiguration als Code“ gibt es heute schon: Umgebungs-
  variablen in der Compose-Datei (die ist YAML).
- **Abnahme:** Rundreise Export → Import ergibt identische Einstellungen; unbekannter Schlüssel oder
  Pfadfeld → kompletter Abbruch, nichts geändert.

## 3. Querschnitt Sicherheit und Pflege

| Thema | Regel |
|---|---|
| Eingriffe in die Zeit | nur über chrony-Schalter (`selectopts`, `tempcomp`), jeder mit Ereignis, Zeitlimit, Rücknahme und Zustand in SQLite (überlebt Neustarts) |
| Hardware | in 1.5 nur lesen (UBX-Polls über gpsd); Schreiben erst 1.6 |
| Ausgehend | nichts Neues standardmäßig an; neue Zwecke im Filter nur mit eigener Feldliste (z. B. AdGuard-API `lan_dns`, falls sie kommt) |
| Client-Daten | bleiben lokal; in Nachrichten nur der eigene Gerätename, außer Schalter; Gerätepass ist eine Druckseite, kein Export-Endpunkt |
| Neue Abhängigkeiten | nur `python3-gps` (Debian, kurz-ADR); paho erst bei Nachfrage |
| Neue Eingaben | Gruppen-Netze, Regeln, TOML-Import: Allowlist-Validierung in `settings.py` bzw. Schema-Projektion; `el()`/`textContent` in der UI |
| Leistung (R4) | Container-Test mit Budget: Diagnosepaket mit 10-min-Aufzeichnung < 30 s auf x86-CI; Clients-Seite mit 2000 Geräten < 1 s Serverzeit |
| Tests | Replay-Aufzeichnungen je neuer Erkennung (Störung, VK-162, Schleife); Datenschutztest je Benachrichtigungstext |

**Fremdprojekte mit Ausstiegsplan (E9):**

| Fremdprojekt | Wofür | Wenn es eingestellt wird |
|---|---|---|
| chrony (`selectopts`, `tempcomp`, `clients -k`) | Sperre, Holdover-Test, Temperatur, NTS-Zählung | Kern des Projekts; Ersatz wäre ntpd-rs mit eigener Konfiguration – unwahrscheinlich nötig |
| gpsd + `python3-gps`/`ubxtool` | UBX-Polls | eigener Poll mit `struct` für die ≈ 5 Nachrichten über gpsd-`?DEVICE` (bausteine.md) |
| Weblate (gehostet) | Übersetzungen | Kataloge liegen im Repo; Übersetzung per Pull-Request oder selbst gehostetes Weblate |
| Caddy (Sidecar-Vorlage) | HTTPS | Traefik/NPM/Zoraxy-Anleitungen aus 1.2 bleiben gültig |
| AllanTools (nur CI) | Test-Orakel | Testwerte aus NIST SP 1065 reichen allein |
| paho-mqtt (falls 14 kommt) | MQTT | eigener Minimalclient (≈ 150–200 Zeilen) oder MQTT streichen; REST-Sensor bleibt |

## 4. 1.6 und später

| Thema | Nutzen | Aufwand | Risiko | OSS | Wert | Stufe |
|---|---|---|---|---|---|---|
| u-blox schreiben: feste Voreinstellungen | ★★ | ◆◆◆ | R3 | ja | −1 | **1.6**, nach Leseerfahrung aus 1.5 |
| `ts2phc` (PPS direkt in i210/i226/TimeHAT) | ★★ | ◆◆◆ | R2 | ja | 0 | **später, experimentell** |
| keepalived/VRRP (nur Doku) | ★ | ◆ | R1 | ja | 1 | **1.6** (Doku) |
| DCF77-Funkuhr | ★ | ◆◆ | R1 | teilw. | −0,5 | nur bei Nachfrage |
| Verbund 2, falls nicht in 1.5.x | ★★ | ◆◆ | R3 | – | −1 | 1.6 |
| „Von außen prüfen“-Knopf im Dashboard (gegen den Server-Test, 4.6) 🔒 | ★★★ | ◆ | R2 | – | 3 | **1.6**, sobald der Dienst läuft |
| Schwarm A (falsche Zeitquellen, ortsunabhängig) 🔒 | ★★★ | ◆◆◆ | R2 | teilw. | 1,5 | nach Website + Test, frühestens 1.7 |

### 4.1 u-blox schreiben

- Nur feste, geprüfte Voreinstellungen: „Timing-Modus/Survey-in“ (M8T/F9T), „Systeme“, „PPS 1 Hz/
  100 ms“, „stationäres Modell“ (auch u-blox 7, hilft dem VK-162 drinnen etwas). Immer über gpsd,
  Befehlsvorschau, vorher `ubxtool -p CONFIG` sichern, Knopf „zurück“, `-P` aus der gelesenen
  Firmware. Nur Empfänger, für die ein Community-Testbericht vorliegt (HCL), sonst ausgegraut.
- **Abnahme:** Replay der Befehlsfolgen; auf echter Hardware (M8T, F9T, u-blox 7) Hin- und
  Rückweg dokumentiert.

### 4.2 ts2phc

- Experimentell, nur auf gemeldeter Hardware (i210/i226, TimeHAT). Konkurrenz mit gpsd um die
  serielle Schnittstelle lösen (ts2phc mit `nmea`-Quelle über gpsd-Pseudo-TTY oder gpsd nur für
  den Status). Ohne Community-Tester wird es nicht gebaut.

### 4.3 keepalived/VRRP

- Doku: keepalived auf dem Host oder als Sidecar mit `network_mode: host`, `track_script` gegen
  `/healthz`; NTS-Zertifikat muss den VIP-Namen tragen. Kein keepalived im Image (`NET_ADMIN`).

### 4.4 DCF77

- Nur bei Nachfrage: USB-Empfänger als SHM-Quelle über einen fremden Dienst (z. B. `radioclkd2`
  *(Pflegezustand n. g.)*). Genauigkeit ms-Bereich, in Deutschland empfangbar – Nischennutzen.

### 4.5 Community-Dienste: Stufen

Reihenfolge aus [community-dienste.md](community-dienste.md#7-aufwand-und-nutzen-im-überblick),
angepasst an E10–E14 und R5:

| Schritt | Stufen (community-dienste.md) | Aufwand | Eigener Server-Code |
|---|---|---|---|
| **A (jetzt)** | 1 HCL über GitHub-Issues, 4 Zeitwächter-Ping in ntp-gui | 3–5 PT | keiner |
| **B (erster eigener Dienst)** | 3 Zeit-Check-Website + 5 Server-Test (Selbsttest) – siehe 4.6 | 10–14 PT | Go, ≈ 1–1,5k Zeilen |
| C | 2 Pool-/NTS-Server mit ntp-gui selbst auf den VPS | 1–2 PT, dann ≈ 1 h/Monat | keiner |
| D | 6b Statusseite öffentlicher Zeitserver aus dem Test-Dienst | ≈ 2 PT | Teil von B |
| E | 8 Schwarm A (ohne Laufzeiten, E12) | 7–10 PT | klein |
| später | 7 öffentliches Test-Formular, 9 Schwarm B (frühestens nach 1 Jahr A, E13) | Wochen | – |

**Relay:** Ein Zeit-Relay bleibt ausgeschlossen (Entscheidungsrahmen 6.4). Ein Nachrichten-Relay für
den Verbund über Standorte hinweg ist ebenfalls nicht geplant – WireGuard/Tailscale lösen das
besser und ohne Datenspur beim Projekt.

### 4.6 Erster konkreter Schritt: Zeit-Check-Website + Server-Test auf dem VPS des Maintainers

**Was die Besucher bekommen** (auch ohne ntp-gui):
1. **Zeit-Check:** „Wie falsch geht die Uhr dieses Geräts?“ – gemessen von ein bis zwei Standorten,
   mit Fehlergrenze und Erklärung. Kein Tracking.
2. **Anschluss-Selbsttest:** „Antwortet dein Internetanschluss auf NTP – und ist er ein offener
   Verstärker (Mode 6/7)?“ Getestet wird **nur die IP des Aufrufers** (kein Zielfeld). Für alle mit
   Portfreigabe, für Pool-Betreiber zusätzlich NTS-KE, Zertifikat, Stratum, Note A–F.
3. **Erklärseiten** aus denselben ⓘ-Texten wie ntp-gui.

Vorbild laut Maintainer ist ntp-tester.eu – **vor dem Bau ansehen, was es schon kann**, nicht doppeln,
sondern ergänzen oder verlinken (Kooperation ist billiger als Konkurrenz).

**Architektur:**

```
Besucher-Browser
 ├─ HTTPS ──> Statische Website (Hugo) auf GitHub Pages (E14)
 │            Zeit-Check-Seite, Erklärseiten, HCL, Impressum, Datenschutz
 ├─ HTTPS GET /t ──> VPS-A: Caddy  respond "{time.now.unix_ms}"   (CORS nur für die Website)
 ├─ HTTPS GET /t ──> VPS-B: Caddy  (zweiter Standort, optional)
 └─ HTTPS POST /api/v1/selftest ──> VPS-A: Caddy ──> tester coordinator (Go, nur 127.0.0.1)
                                         │ prüft Limits, Ziel = Quell-IP der Verbindung
                                         └─ WireGuard wg0 ──> tester probe auf VPS-B
VPS-A/B optional (Schritt C): ntp-gui als NTP/NTS-Server, Dashboard nur 127.0.0.1
Offene Ports: 80/443 (Caddy), später 123/udp + 4460/tcp. Sonst nichts.
```

**Bausteine (OSS, alle schon in [community-dienste.md](community-dienste.md#2-geprüfte-bausteine) geprüft):**
Hugo (Website), Caddy ohne `log` (Webserver, Zeit-Endpunkt, Zertifikate), Go mit beevik/ntp +
beevik/nts (E11; beevik/nts per Pseudo-Version pinnen und vendoren), WireGuard (Kernel), GitHub Pages
und Actions (Bau, Deploy), nmap-NSE nur als Test-Orakel in CI. Uptime Kuma optional für die eigene
Überwachung. **Kein** Analytics, keine Datenbank (Limit-Zähler im Speicher).

**Aufwand:** Website + Zeit-Check 2–3 PT; Server-Test (Selbsttest, ein Standort) 7–10 PT; zweiter
Standort + WireGuard +1 PT; Rechtstexte 0,5–1 PT. Zusammen **≈ 10–14 PT**, für einen Maintainer mit
KI-Hilfe realistisch **6–10 Wochenenden**, weil Go eine zweite Toolchain ist. Danach ≈ 1–2 h/Monat
(Updates per Digest + Dependabot, Abuse-Mails, Zertifikate laufen automatisch).

**Datenschutz:**
- Website auf GitHub Pages: GitHub sieht Besucher-IPs (E14 akzeptiert das für statische Inhalte;
  steht in der Datenschutzerklärung). Zeit-Endpunkt und Test auf dem VPS: Caddy ohne Zugriffslog,
  keine Cookies, kein localStorage → kein Consent-Banner (§ 25 TDDDG).
- Test-Dienst: Ziel-IP verarbeitet, nicht gespeichert; Limit-Zähler gehasht mit täglich rotierendem
  Salt, TTL 1 h; **keine teilbare Ergebnis-URL**; RTTs je Standort nur an den Aufrufer.
- ntp-gui ist in Schritt B nicht beteiligt; der Dashboard-Knopf „Von außen prüfen“ folgt in 1.6
  (Vertrag `external-test-request@1`, eigener Egress-Zweck, opt-in, Vorschau).

**Recht** *(kein Rechtsrat; vor Start einmal prüfen lassen)*:
- **Impressum nach § 5 DDG** mit ladungsfähiger Anschrift und Abuse-Kontakt. Ob ein rein privates,
  nicht kommerzielles Angebot darunter fällt, ist umstritten – sicherer ist, eins zu haben. Wer die
  Privatadresse nicht veröffentlichen will: Impressums-/Anschriftsdienst (c/o-Adresse, einige €/Monat)
  oder ein Verein als Betreiber.
- **Datenschutzerklärung nach Art. 13 DSGVO** je Dienst (Website, Zeit-Check, Test).
- Test-Dienst: Opt-out-Liste für Betreiber, User-Agent/SNI nennen den Dienst.

**Betriebskosten:** je VPS ≈ 4–10 €/Monat, Domain ≈ 1 €/Monat, GitHub Pages/Actions 0 € →
**≈ 5–25 €/Monat** je nach Zahl der Standorte, plus ggf. Impressumsdienst. Verkehr: Website und Test
vernachlässigbar; ein Pool-Server (Schritt C) ≈ 4 GB/Monat.

**Abnahme Schritt B:** Zeit-Check misst gegen einen VPS mit bekanntem Versatz (Testmodus) auf
± (RTT/2 + 1 ms) genau; Browser mit gerundeter Uhr (100 ms) bekommt Hinweis statt Fehler; Selbsttest
lehnt jedes Zielfeld ab; IP-Sperrliste greift beim Verbinden (Test mit DNS-Rebinding-Name); Limits
(10 Tests/h je IP bzw. /64) greifen; `govulncheck` grün; keine Zugriffslogs auf dem VPS (Prüfung
in der Deploy-Pipeline: Caddyfile ohne `log`).

## 5. Offene Fragen an den Maintainer

| # | Frage | Empfehlung |
|---|---|---|
| F1 | **Schnitt 1.5:** schlankes 1.5.0 (≈ 8–10 Wochen) + 1.5.x, oder alles in einem Release (≈ 5–7 Monate)? | schlank, wie E3 **→ entschieden: E15** |
| F2 | **`python3-gps` aufnehmen** (≈ 0,6 MB, für `ubxtool`) oder eigener UBX-Poll mit `struct`? | `python3-gps`: Debian-Paket, bewährt, für 1.6 (schreiben) ohnehin nötig |
| F3 | **GPS-Sperre:** Standard „nur melden“ und automatische Sperre opt-in? | ja – erst Praxisdaten, dann ggf. Standard ändern |
| F4 | **VK-162 & Co.:** Soll ntp-gui GPS ohne PPS bei guten NTS-Quellen standardmäßig nur als Plausibilitätsquelle führen (`noselect`)? | als **Vorschlag** im Hardware-Check, nicht automatisch – manche Nutzer wollen bewusst „Zeit ohne Internet“ **→ entschieden: E16 – Rückfallebene statt „nur beobachten“** |
| F5 | **Client-Daten in Benachrichtigungen:** IP/MAC erlauben? | nur eigener Gerätename; Schalter „LAN-Adressen in Nachrichten“, Standard aus |
| F6 | **Implementierung erkennen** (Heuristik „vermutlich Windows/chrony/…“) anzeigen? | ja, lokal, immer „vermutlich“, nie exportieren |
| F7 | **i18n:** Gerüst schon in 1.5.0 (jeder neue Text als Schlüssel) und Weblate gehostet? | ja; Englisch darf hinterherhinken, Deutsch bleibt Referenz |
| F8 | **HTTPS:** E5 bestätigen (Caddy-Vorlage) statt TLS im Python-Server? | E5 bestätigen |
| F9 | **YAML:** durch TOML-Import (`tomllib`, stdlib) ersetzen – oder Thema streichen? | TOML, klein; streichen ist auch vertretbar (Compose-Variablen reichen vielen) |
| F10 | **MQTT-Schwelle:** Ab wann wird gebaut (E4)? | ab 5 unabhängigen Nachfragen (Issues/👍) oder einem fertigen PR aus der Community |
| F11 | **Verbund über Standorte** (Heim + VPS): eigenes Relay oder Doku für WireGuard/Tailscale? | Doku, kein Relay |
| F12 | **Community Schritt B:** Domainname, wie viele VPS/Standorte, bei welchen Anbietern? | mit **einem** VPS starten, zweiter Standort (anderes Land/Anbieter) erst nach 4 Wochen Betrieb **→ entschieden: E17 – ein VPS** |
| F13 | **Impressum:** Privatanschrift, Anschriftsdienst oder Verein? | Anschriftsdienst für den Start; Verein erst, wenn Mitstreiter da sind |
| F14 | **Server-Test zuerst auf der Website oder zuerst als Knopf in ntp-gui?** | zuerst Website (kein ntp-gui-Release nötig, sofort für alle nützlich), Knopf in 1.6 |
| F15 | **Pool-Server (Schritt C):** VPS dauerhaft in den NTP Pool eintragen? Das ist ein Dauerversprechen. | ja, mit ntp-gui selbst, nach 4 Wochen stabilem Probebetrieb |
| F16 | **Abstimmung mit ntp-tester.eu:** Kontakt aufnehmen, bevor eigener Test gebaut wird? | ja – ergänzen statt doppeln spart Wochen **→ entschieden: E18 – eigene Lösung** |
