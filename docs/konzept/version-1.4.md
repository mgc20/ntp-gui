# Version 1.4 und folgende: Staffelung, Bewertung, Abnahme

Stand: 01.11.2026 · Grundlage: [ROADMAP](../../ROADMAP.md), 1.3-Bausteine im Arbeitsbaum
(`app/events.py`, `app/store.py`, `app/egress.py`, `app/apikeys.py`, `app/apiv1.py`),
[Entscheidungsrahmen](entscheidungsrahmen.md), [Bausteine](bausteine.md)

## 1. Übersicht

Bewertung nach dem [Entscheidungsrahmen](entscheidungsrahmen.md#2-bewertung-fünf-fragen):
Nutzen ★, Aufwand ◆, Risiko R, Wert = `Nutzen×2 − Aufwand − Risiko (+1 bei OSS ja)`.

| # | Thema | Nutzen | Aufwand | Risiko | OSS | 🔒 | Wert | Stufe | Braucht aus 1.3 |
|---|---|---|---|---|---|---|---|---|---|
| A | Basis-Image trixie | ★★ | ◆◆ | R1 | ja | – | 2 (Voraussetzung) | **1.3.1** ✅ | Container-Test, Replay |
| 1 | Benachrichtigungen (Kern: Webhook, ntfy, Apprise-API; danach E-Mail, Gotify) | ★★★ | ◆ (Kern) / ◆◆ (alles) | R2 | teilw. | 🔒 | 2–3 | **1.4** | Ereignisse, Filter, Store |
| 2 | MQTT + Home Assistant (nur senden) | ★★ | ◆◆ | R2 | ja | 🔒 | 1 | **1.4** | Ereignisse, Filter |
| 3 | Allan-Abweichung, „wie lange hält die Uhr?“ | ★★ | ◆◆ | R1 | teilw. | – | 1–2 | **1.4** | Store (Verlauf), Replay |
| 4 | Temperaturausgleich: messen und vorschlagen | ★★ (★★★ ohne GPS) | ◆◆ | R1 | ja | – | 2 | **1.4** messen, **1.5** anwenden | Store, Muster GPS-Kalibrierung |
| 5 | Schaltsekunden-Übersicht | ★ | ◆ | R1 | ja | – | 1 | **1.4** | Ereignisse |
| 6 | Vollbild-Uhr | ★ | ◆ | R1 | – | – | 0 (aber sehr sichtbar) | **1.4** | API v1 |
| 7 | Update-Hinweis (opt-in) + Attestations | ★★ | ◆ | R1 | ja | 🔒 | 3 | **1.4** | Filter, Ereignisse |
| 8 | Grafana-Dashboard + Alarmregeln | ★★ | ◆ | R1 | ja | – | 3 | **1.4** | – |
| 9 | HTTPS fürs Dashboard (stdlib, opt-in) | ★★ | ◆ | R1 | ja | – | 3 | **1.4** | API-Schlüssel (Grund dafür) |
| 10 | Verbund 1: Übersicht + Gegenmessung | ★★ | ◆◆ | R2 | ja (chrony) | – | 1 | **1.4 falls Zeit**, sonst 1.5 | API-Schlüssel, API v1, Store |
| 11 | Verbund 2: Einstellungen teilen | ★★ | ◆◆ | R3 | – | – | −1 | **1.5** | versionierte Einstellungen |
| 12 | GNSS-Störungen erkennen (melden) | ★★★ | ◆◆ | R1 | teilw. | – | 3 | **1.5** | Ereignisse, Replay |
| 12b | … GPS automatisch sperren | ★★ | ◆ | R2 | ja (chrony) | – | 2 | **1.5** | trixie (`selectopts`) |
| 13 | u-blox lesen (Status, Firmware, Konfiguration) | ★★ | ◆◆ | R1 | ja | – | 2 | **1.5** | Store |
| 13b | u-blox schreiben (Voreinstellungen) | ★★ | ◆◆◆ | R3 | ja | – | −1 | **1.6** | 13, Snapshots |
| 14 | Englisch (i18n) | ★★★ | ◆◆◆ (Menge) | R1 | ja (Weblate) | – | 3 | **1.5** Gerüst + UI, Hilfetexte nach und nach | – |
| 15 | Einstellungen als YAML | ★ | ◆ | R1 | – | – | 0 | **1.5** (klein) | versionierte Einstellungen |
| 16 | Doku: keepalived/VRRP, Caddy, Log-Versand | ★ | ◆ | R1 | ja | – | 1 | **1.5** | – |
| 17 | ts2phc (PPS in die Netzwerkkarte) | ★★ | ◆◆◆ | R2 | ja | – | 0 | **später, experimentell** | trixie |
| 18 | DCF77-Funkuhr | ★ | ◆◆ | R1 | teilw. | – | −1 | **später**, nur bei Nachfrage | – |

### Leitlinie der Staffelung

- **1.4 „Melden, Einbinden, Uhrqualität sichtbar“:** Was jede Installation sofort nutzt (Alarme,
  Home Assistant, Grafana) und was die vorhandenen Messdaten erklärt (Allan, Temperatur,
  Schaltsekunden). **Nichts davon schreibt auf Hardware oder steuert die Uhr.**
- **1.5 „GNSS-Werkbank, Verbund, Englisch“:** Alles mit höherem Risiko. Bis dahin liefern die
  Praxis-Logs aus 1.3/1.4 die Schwellwerte für Störungserkennung und Temperaturausgleich.
- **Später:** hardwareabhängig, kaum testbar, kleiner Nutzerkreis.

### Wenn die Zeit knapp wird

Reihenfolge innerhalb 1.4 nach Wert: **A → 1 → 7 → 8 → 9 → 2 → 4 (messen) → 3 → 5 → 6 → 10.**
Was nicht fertig wird, rutscht ohne Diskussion nach 1.5. Ein Release mit fünf fertigen Themen ist
besser als eines mit zehn halben.

### Realistischer Gesamtaufwand (Gegenprüfung)

Summiert man die Tabelle, ergibt 1.4 komplett: 5 × ◆◆ (A, 2, 3, 4, 10) + 6 × ◆ ≈ **5–10
Wochenenden plus 6–18 Abende**, also für einen Maintainer neben Beruf eher **3–4 Monate** als
einige Wochen. Dazu kommen Fehlerberichte aus 1.3, die erfahrungsgemäß die ersten Wochen nach
einem Release binden. Unterschätzt sind vor allem:
- **Benachrichtigungen:** Entprellen, Problem/behoben-Paare, Backoff, Ratenlimit, Warteschlange,
  Test-Knopf und UI sind zusammen eher ◆◆. Darum Kern zuerst (Webhook + ntfy; Apprise-API über
  den Webhook deckt Gotify, Telegram, Matrix, E-Mail usw. ab), E-Mail/Gotify/Ruhezeiten nur bei Nachfrage.
- **Temperaturausgleich:** Kreuzkorrelation, Klassen, zwei Fits und Rekonstruktion der
  unkompensierten Frequenz sind eher ◆◆◆, wenn man die Tests ernst nimmt. Vorschlag: in 1.4 nur
  **Sensor finden + Paare aufzeichnen + Streudiagramm**; Fit und Vorschlag in 1.5.
- **trixie-Wechsel (erledigt in 1.3.1):** gpsd 3.22 → 3.25 und linuxptp 3.1 → 4.2; Replay-Aufzeichnungen
  beider Versionen bleiben nötig, um Formatänderungen zu fangen.

**Empfehlung für ein schlankes 1.4 (≈ 6–8 Wochen):** 1 (Kern), 7, 8, 5, 6 und die
Doku-Ideen unten. MQTT, Allan, Temperatur-Fit und Verbund werden 1.4.x bzw. 1.5.

### Ergänzende Ideen mit hohem Nutzen und kleinem Aufwand

| Idee | Nutzen | Aufwand | Warum |
|---|---|---|---|
| **Home Assistant per REST-Sensor** (nur Doku: YAML-Beispiel gegen `/api/v1` mit Lese-Schlüssel) | ★★ | ◆ | liefert 80 % von Thema 2 ohne neue Abhängigkeit und ohne ausgehende Verbindung; MQTT kann folgen |
| **Homepage/Homarr/Glance-Widget** (nur Doku: „Custom API“-Widget gegen `/api/v1/status`) | ★★ | ◆ | sehr verbreitet in Homelabs, hoher Sichtbarkeitseffekt |
| **Uptime-Kuma-NTP-Monitor** (nur Doku; NTP-Monitor seit Uptime Kuma 2.5, 01.08.2026) | ★ | ◆ | externe Überwachung des NTP-Ports mit einem Werkzeug, das viele schon haben |
| **Lieferkette im Release-Workflow:** SBOM (`docker buildx --sbom`/syft) + Schwachstellen-Scan (Trivy oder Grype) + Dependabot für Basis-Image und Actions | ★★ | ◆ | macht die Pflege des Basis-Images sichtbar und automatisch; im Repo gibt es heute kein `dependabot.yml` |
| **Zeitwächter-Ping** (siehe [community-dienste.md](community-dienste.md#stufe-4-zeitwächter)) | ★★ | ◆ (≈ 30 Zeilen) | funktioniert sofort mit healthchecks.io/Uptime-Kuma-Push, ganz ohne eigenen Dienst |

## 2. Die Themen im Einzelnen

### A. Basis-Image auf Debian 13 „trixie“ (erledigt in 1.3.1)

- **Was:** `FROM debian:trixie-slim`; chrony 4.6.1, gpsd 3.25, linuxptp 4.2.
- **Warum:** bookworm ist seit 12.07.2026 nur noch LTS. `selectopts` (ab chrony 4.4) erlaubt, eine Quelle zur Laufzeit auf `noselect` zu setzen – ohne chronyd-Neustart, der den Regelzustand kostet. Das brauchen Holdover-Test, Störungs-Sperre und Probelauf beim Temperaturausgleich. `leapseclist` gibt es ab chrony 4.6.
- **Falle:** `right/UTC` liegt in trixie in `tzdata-legacy`. **Umgesetzt:** `confgen.py` schreibt `leapseclist /usr/share/zoneinfo/leap-seconds.list`; ein gespeichertes `LEAPSECTZ=right/UTC` wird per Einstellungsmigration (Schema 3) entfernt, mit Hinweiskarte statt still.
- **Abnahme:** Container-Test komplett grün; Replay-Tests aller Parser (chronyc, gpsd, ptp4l/pmc) grün; `chronyc tracking` zeigt nach Start einen Leap-Status ≠ „?“; Test, dass `leap-seconds.list` existiert und chrony sie lädt; Versionsstände der Kernpakete stehen im Release-Text.
- **Sicherheit:** senkt das Risiko (aktuelle Pakete, regulärer Sicherheitssupport).

### 1. Benachrichtigungen 🔒

- **Was:** Regeln „Ereignis → Kanal“ auf Basis von `events.KINDS`/`LEVELS`, Filter nach Stufe (`warn`/`crit`) und Art (`gps`, `pps`, `service`, `cert`, `leap`, `source` …).
  - Kanäle (stdlib): Webhook (JSON, optional HMAC-Signatur), ntfy, Gotify, E-Mail (nur STARTTLS/SMTPS), Apprise-API (`POST /notify/` an einen Sidecar → > 100 Dienste).
  - **Entprellen:** gleicher Schlüssel (Art + Quelle) höchstens einmal je X Minuten; „Problem“ und „behoben“ als Paar mit Dauer („GPS wieder da, Dauer 40 min“).
  - Wiederholung mit Backoff (30 s, 2 min, 10 min, dann verwerfen + Ereignis `notify`), Ratenlimit je Kanal (z. B. 30/h), Knopf „Testnachricht senden“, optionale Ruhezeit nur für `info`/`warn`.
- **Sicherheit:**
  - Der 1.3-Filter kennt heute nur die Zwecke `diagnostics`, `recording`, `community` (`egress.PURPOSES`). Benachrichtigungen, Update-Hinweis und Zeitwächter brauchen je einen **eigenen Zweck** (z. B. `notify`, `update_check`) mit eigener Feldliste – nicht einfach `community` wiederverwenden.
  - Alles läuft durch die **eine Tür nach draußen**: Filter (`sanitize` + `check_no_leaks`), Timeout 10 s, Antwortgröße begrenzt, **keine Weiterleitungen** (eigener `HTTPRedirectHandler`, `urllib` folgt sonst automatisch).
  - Nur `http`/`https`. Kanäle legt nur ein Admin an (Verwaltungsrecht) – das begrenzt SSRF auf Personen, die ohnehin Admin sind; steht so im README.
  - Tokens/Passwörter maskiert in der UI, nie im Diagnosepaket, nie in Ereignistexten.
  - Eigener Thread mit Warteschlange: Ein hängender Kanal blockiert weder Messung noch HTTP-Server.
- **Abnahme:** `gps/crit` → innerhalb 5 s genau eine Nachricht je passendem Kanal; zehn gleiche Ereignisse in einer Minute → eine Nachricht, „behoben“ mit Dauer; Ziel antwortet 302 → keine zweite Anfrage; Koordinate im Ereignistext wird vom Filter entfernt; HMAC-Testvektor im README reproduzierbar.

### 2. MQTT und Home Assistant

- **Was:** Publisher, **nur senden**. Abonniert wird ausschließlich `homeassistant/status`, um nach einem HA-Neustart die Discovery erneut zu senden (mit zufälliger Verzögerung).
  - Discovery geräteweise auf `homeassistant/device/<id>/config` (`dev`, `o`, `cmps`); Rückfall: klassisch je Entität.
  - Sensoren: Systemoffset, Frequenzfehler, Stratum, aktive Quelle, Root Dispersion, Satelliten genutzt/sichtbar, Clients. Binärsensoren: synchron, GPS-Fix, PPS, je Dienst „läuft“. Diagnose: Schaltsekunden-Status, Tage bis Zertifikatsablauf.
  - Verfügbarkeit per LWT. Beim Abschalten leere retained Configs (sonst „Geister-Entitäten“).
  - Instanz-ID: zufällige UUID, lokal erzeugt – weder Hostname noch MAC.
- **Entscheidung (Baustein):** `python3-paho-mqtt` 2.1.0 aus trixie statt eigenem Protokollcode – Begründung in [bausteine.md, 3.2](bausteine.md#32-mqtt). Das ist die erste Python-Abhängigkeit außerhalb der stdlib und wird als kurz-ADR festgehalten.
- **Sicherheit:** keine Befehle aus HA (keine Steuerfläche); Payloads durch den Filter; **Koordinaten nie als Entität**; Brokerpasswort wie bei 1; TLS mit System-CA oder CA-Datei unter `/config`.
- **Abnahme:** gegen Mosquitto in CI erscheint die Discovery; nach hartem Beenden steht die Verfügbarkeit nach Keepalive auf `offline`; HA-Birth löst Neuveröffentlichung aus; „Abschalten“ entfernt die Entitäten; kein Payload enthält Koordinaten (Filtertest).

### 3. Allan-Abweichung und „wie lange hält die Uhr?“

- **Was:** überlappende Allan-Abweichung σ_y(τ) aus chronys Frequenzverlauf (SQLite), reines Python nach NIST SP 1065: `σ²(τ) = Σ (x[i+2m] − 2x[i+m] + x[i])² / (2τ²(N − 2m))`. Lücken (Neustarts) teilen die Reihe. log-log-Diagramm mit Konfidenzband. Bei aktivem Temperaturausgleich wird die unkompensierte Frequenz rekonstruiert (siehe 4).
- **Holdover-Schätzung:** Zeitfehler nach T ≈ |Δf₀|·T + T·σ_y(T), als „Größenordnung“ für 1 h, 6 h, 24 h. Beispiel: σ_y(1 h) = 5·10⁻⁸ → ≈ 0,18 ms nach 1 h.
- **Ehrliche Grenze:** chronys Frequenz ist eine Regel-Schätzung, nicht der Quarz. Anzeige nur für τ ≥ 4 × maximales Poll-Intervall und τ ≤ Datenlänge/10; steht in der ⓘ-Erklärung. Dazu CSV-Export für TimeLab/Stable32.
- **1.5:** echter **Holdover-Test** – GPS/PPS per `selectopts` für N Stunden auf `noselect`, chrony misst weiter, danach automatisch zurück. Messwert statt Schätzung.
- **Abnahme:** weißes Frequenzrauschen → Steigung ≈ τ^−½; linearer Drift → ≈ τ^+1; Übereinstimmung mit AllanTools (nur in CI) auf 1e-9 relativ; keine Rechnung über Lücken; unter 24 h Daten der Hinweis „zu wenig Daten“.

### 4. Temperaturausgleich des Quarzes (chrony `tempcomp`)

- **chrony kann es bereits:** `tempcomp <datei> <intervall> <T0> <k0> <k1> <k2>` oder `tempcomp <datei> <intervall> <punktedatei>`; Temperatur in Milligrad, Korrektur in ppm; Ergebnisse außerhalb ±10 ppm verwirft chrony.
- **Messfalle:** Die von chrony berichtete Frequenz enthält die Korrektur bereits; unkompensiert gilt näherungsweise `f_unkomp ≈ f_tracking + comp`. Bei aktivem tempcomp muss die Messung die Korrektur aus `tempcomp.log` addieren, sonst lernt sie ihre eigene Korrektur.
- **1.4 messen und vorschlagen:**
  1. Sensoren auflisten (`thermal_zone*`, `hwmon*`, DS18B20); der Hardware-Check zeigt Kandidaten. In VMs meist „nicht verfügbar“.
  2. Paare (T, f_unkomp) nur speichern, solange eine gute Referenz aktiv ist (GPS+PPS oder ≥ 3 NTS-Quellen, Root Dispersion unter Schwelle).
  3. Vorschlag erst ab 3 Tagen, ≥ 4 K Spanne, ≥ 5 belegten 0,5-K-Klassen.
  4. Verzögerung T↔f per Kreuzkorrelation (0–30 min) als Qualitätsmaß.
  5. Median je Klasse, Gerade und Parabel (Normalgleichungen, stdlib), R², Steigung, Restfehler.
  6. Vorschlag als **Punktedatei**, T0 = Median-Temperatur; außerhalb des Messbereichs je ein Punkt mit gleichem Wert (verhindert lineare Extrapolation); Werte hart auf ±2 ppm begrenzt.
  7. Vorschlag nur bei R² ≥ 0,5 und ≥ 20 % erwarteter Verbesserung, sonst „lohnt nicht“ mit Begründung.
- **1.5 anwenden** (Muster GPS-Kalibrierung: aus / vorschlagen / automatisch): ntp-gui schreibt eine geglättete Temperaturdatei (`/run/ntp-gui/oscillator_temp`, atomar), Wächter bei veralteter Datei, **Probelauf 24 h** mit automatischer Rücknahme bei Verschlechterung.
- **Ehrlich:** Mit GPS+PPS ist der Gewinn klein; er zeigt sich im Holdover und bei reinem NTP. Ein Fit ist hardware- und einbauortspezifisch – **nie** im Verbund oder in der Community-Liste teilen.
- **Abnahme:** Replay mit künstlich 0,15 ppm/K + Rauschen → Fit 0,15 ± 0,02; kein Mitlernen der eigenen Korrektur (synthetisches `tempcomp.log`); erzeugte Punktedatei startet chronyd 4.6 fehlerfrei (Container-Test); falsches Vorzeichen → Rücknahme im Probelauf (1.5); ohne Sensor „nicht verfügbar“ statt Fehler.

### 5. Schaltsekunden-Übersicht

- **Was:** aus `leap-seconds.list`: letzte Schaltsekunde, TAI−UTC (derzeit 37 s), Ablaufdatum der Datei (Prüfsumme mit `hashlib`); dazu chronys Leap-Status. ⓘ-Erklärung zu IERS Bulletin C und zum CGPM-Beschluss, Schaltsekunden spätestens 2035 abzuschaffen (Quelle vor Veröffentlichung verlinken).
- Warnung „Image zu alt“, wenn die Liste in < 60 Tagen abläuft → guter Anlass für den Update-Hinweis (7). Kein eigener IERS-Download.
- **Abnahme:** Parser-Tests mit echten Dateien; abgelaufene Testdatei → Ereignis `leap/warn`.

### 6. Vollbild-Uhr

- **Was:** Seite `/clock`: große Uhrzeit (lokal/UTC), Datum, ISO-Woche, Statusband (grün/gelb/rot mit Genauigkeit und Quelle). Abgleich der Browseruhr per Vier-Zeitstempel-Austausch über `/api/v1/time`, fünf Messungen, kleinste RTT gewinnt, Genauigkeit ±RTT/2. Wake-Lock, Dunkel- und Rotlicht-Modus.
- **Sicherheit:** standardmäßig wie das Dashboard geschützt; optional „Uhr ohne Anmeldung“ zeigt nur Zeit und Ampel. Keine API-Schlüssel in URLs (landen in Proxy-Logs).
- **Abnahme:** bei simulierter RTT 200 ms Abweichung < 100 ms; nach 10 s Verbindungsverlust graue Ampel; kein Layout-Bruch von 320 px bis 4K.
- Wert rechnerisch 0, aber hoher Werbeeffekt (Screenshots, Foren) bei sehr kleinem Aufwand – darum trotzdem 1.4.

### 7. Update-Hinweis (opt-in) und Attestations 🔒

- **Was:** einmal täglich zu zufälliger Uhrzeit `GET https://api.github.com/repos/mgc20/ntp-gui/releases/latest`, User-Agent `ntp-gui` ohne Version und Kennung, Vergleich lokal. Anzeige: neue Version, Changelog-Link, Markierung „Achtung beim Update“. **Kein automatisches Update, kein Download.** Für Automatisierung: Verweis auf Diun bzw. WUD (nicht Watchtower – seit 17.12.2025 archiviert).
- **Datenschutz ehrlich:** GitHub sieht dabei täglich die öffentliche IP (grob ortbar per GeoIP) und dass dort vermutlich ntp-gui läuft. Technisch unvermeidbar, darum opt-in und genau so in der Vorschau.
- **Release-Workflow:** `actions/attest` mit `push-to-registry: true`; README zeigt `gh attestation verify oci://ghcr.io/mgc20/ntp-gui:<ver> -R mgc20/ntp-gui`. Keine Verifikation in der Instanz (sigstore-python wäre eine große Abhängigkeit für nichts).
- **Abnahme:** genau eine Anfrage pro Tag gegen einen Mock; Header ohne Version/ID; abgeschaltet → null Netzzugriffe (Socket-Monkeypatch); CI verifiziert die Attestation nach dem Push.

### 8. Grafana-Dashboard und Alarmregeln

- `docs/grafana/ntp-gui.json` (Variable `instance`), `docs/prometheus/alerts.yml`; Veröffentlichung auf grafana.com.
- **Abnahme:** Test prüft, dass jede im Dashboard und in den Regeln verwendete Metrik im `/metrics`-Output existiert.

### 9. HTTPS fürs Dashboard (opt-in)

- `ssl.SSLContext(PROTOCOL_TLS_SERVER)`, `minimum_version = TLSv1_2`; Zertifikat aus den NTS-Pfaden (`/config`, `/certs`, `/etc/letsencrypt`), Neuladen wie bei NTS; optional selbstsigniert. Seit 1.3 gibt es API-Schlüssel – die sollen im LAN nicht im Klartext laufen.
- **Abnahme:** TLS 1.1 wird abgelehnt; Zertifikatswechsel ohne Neustart; **ein Client, der verbindet und schweigt, blockiert keine anderen Anfragen** (Handshake nicht im Annahme-Thread, siehe [bausteine.md, 3.7](bausteine.md#37-ts2phc-keepalived-https-logs)); Caddy-Sidecar als Alternative in der Doku.

### 10. Verbund, Stufe 1: Übersicht und Gegenmessung

- Peer-Liste (Name, URL, **Lese-API-Schlüssel**, höchstens 8). Übersicht per `GET /api/v1/status` alle 30 s, ausgehend.
- **Gegenmessung ohne eigenen NTP-Code:** Jeder Peer kommt als `server <peer> iburst noselect` (mit `nts`, falls vorhanden) in die chrony-Konfiguration. chrony misst, die Peers beeinflussen die Zeit nicht. Ergebnis: Matrix „A sieht B mit +12 µs“, Warnung über Schwelle. Kein doppelter Eintrag mit `LOCAL_ORPHAN`-Partnern.
- **Sicherheit:** Peer-Antworten werden gegen ein Schema validiert, Größe/Zeit begrenzt, keine Weiterleitungen. Schlüssel liegt in SQLite (Rechte 600) – Verschlüsselung brächte nichts, weil der Schlüssel daneben läge; steht so im README.
- **Abnahme:** zwei Container sehen sich gegenseitig; `chronyc sources` zeigt den Peer als nicht ausgewählt; falscher Schlüssel → „Schlüssel abgelehnt“; 10 MB Müll → Abbruch am Größenlimit.

### 11. Verbund, Stufe 2: Einstellungen teilen (1.5)

Bewusst einfache Regeln:
1. **Ein Leader, kein Multi-Master.** Follower ziehen (Pull), der Leader schiebt nie.
2. Pro Follower und Abschnitt einzeln opt-in.
3. **Nie teilbar:** Geräte, Ports, GPS-/PPS-Pfade, Kalibrier-Offsets, tempcomp, Zertifikate, Schlüssel, Passwörter, Tokens, Dateipfade. Im Schema `shareable: false`, Standard ist „nicht teilbar“.
4. Lokal geändertes Feld wird „lokal festgehalten“ und nicht überschrieben.
5. Schema-Version passt nicht → nichts anwenden.
6. Erste Übernahme nur mit Diff-Vorschau; jede Übernahme schreibt ein Ereignis mit Diff (Geheimnisse maskiert).
7. Validierung durch denselben Validator wie UI-Eingaben (`settings.py`).
- **Abnahme:** manipulierter Export mit Pfadfeld oder unbekanntem Schlüssel wird komplett abgelehnt; festgehaltenes Feld überlebt drei Leader-Änderungen; Schema-Mismatch ändert nichts.

### 12. GNSS-Störungen lokal erkennen (1.5) und 12b GPS sperren

- **Was gpsd liefert:** SKY `ss` (C/N0) je Satellit, `used`, `health`; TPV-Position. `jam` und Antennenstatus erst ab gpsd 3.26 – **nicht** in trixie. u-blox-AGC/Jamming (UBX-MON-HW, MON-RF) und Spoofing-Status (NAV-STATUS `flags2`, SEC-SIG) per Poll **über gpsd** (`?DEVICE` mit Hex-Payload, so arbeitet auch `ubxtool`). Ein Poll liest nur. Feldnamen und Firmware-Stände vor der Umsetzung gegen die u-blox Interface Description prüfen.
- **Signale:** gleichzeitiger C/N0-Einbruch ≥ 6 dB in < 60 s; AGC/`jamInd`; unnatürlich gleichmäßiges C/N0; GPS-Zeit weicht vom Median ≥ 2 NTS-Quellen ab bzw. chrony markiert GPS als Falseticker; Positionssprung > 100 m bei stationärem Empfänger; Spoofing-Flag des Empfängers.
- **Reaktion (12b):** Sperre per `chronyc selectopts <refid> +noselect` nur bei **starken** Signalen (Zeitabweichung zu ≥ 2 NTS-Quellen, Positionssprung, Spoofing-Flag). Freigabe nach 30 min ohne Signal, höchstens drei Wiederholungen, dann manuell. Reines Jamming → keine Sperre (chrony schaltet bei Fix-Verlust ohnehin um), nur Erklärung und Benachrichtigung.
- **Ehrliche Grenzen:** langsames Spoofing unter der NTS-Unsicherheit (einige ms) ist nicht erkennbar; Schnee/Flugzeuge erzeugen C/N0-Einbrüche → Hysterese und Stufe „Hinweis“, solange nur ein Signal anschlägt.
- **Datenschutz:** Referenzposition nur lokal, im Filter „nie exportieren“; gespeichert wird nur die Abweichung in Metern.
- **Abnahme:** Replay-Aufzeichnungen (a) C/N0-Einbruch, (b) Zeitsprung 50 ms, (c) Positionssprung, (d) langsamer Abfall wie Schneefall → (a)–(c) erkannt in ≤ 60 s, (d) kein Alarm; bei aktivierter Sperre zeigt `chronyc sources` GPS als `noselect`, nach Ablauf wieder auswählbar.

### 13. u-blox-Einrichtung (1.5 lesen, 1.6 schreiben)

- **Lesen (1.5):** Firmware (`MON-VER`), Protokollversion, aktive Systeme, Timing-Modus, Zeitimpuls-Einstellungen – angezeigt im Hardware-Check. Braucht `python3-gps` (≈ 0,6 MB) für `ubxtool`.
- **Schreiben (1.6):** nur feste, geprüfte Voreinstellungen („Timing-Modus/Survey-in“, „Systeme“, „PPS 1 Hz/100 ms“), immer über gpsd, Befehlsvorschau, vorher `-p CONFIG` sichern, Knopf „zurück“. `-P` (Protokollversion) aus der gelesenen Firmware ableiten, nie raten.
- **Risiko R3:** falsche Befehle können einen Empfänger bis zum Werksreset unbrauchbar konfigurieren. Darum erst nach den Leseerfahrungen und mit Testberichten zu M8T, F9T und M10.
- **Abnahme (lesen):** Replay mit aufgezeichneten UBX-Antworten von mindestens zwei Empfängergenerationen.

### 14. Englisch (i18n)

- Gerüst in 1.5: Textkatalog je Sprache (JSON), Auswahl im Dashboard, Deutsch bleibt Referenz. Übersetzung über **Weblate** (gehostet, für Open Source kostenlos *(n. g.)*), damit die Community beiträgt.
- Erst Oberfläche, dann die ⓘ-Texte schrittweise (hardware.py ≈ 1500 Zeilen, `help.js`). Fehlende Übersetzung fällt auf Deutsch zurück.
- Nutzen ★★★ wegen Reichweite; der Aufwand ist Menge, nicht Technik.

### 15. Einstellungen als YAML

- Export/Import der versionierten Einstellungen als YAML-Datei unter `/config` – **ohne** neue Abhängigkeit nur, wenn eine kleine, strikte Teilmenge reicht; sonst JSON statt YAML. Gleicher Validator wie die UI. Klein halten, sonst weglassen.

## 3. Querschnitt Sicherheit

| Thema | Regel |
|---|---|
| Ausgehend | eine Tür: Filter, Timeout, Größenlimit, keine Redirects, Liste „ausgehende Verbindungen“ im Dashboard |
| Geheimnisse | in SQLite, Dateirechte 600, maskiert in UI, nie im Diagnosepaket/Ereignistext |
| Neue Abhängigkeiten | nur aus Debian, je eine kurz-ADR (1.4: `python3-paho-mqtt`; 1.5: `python3-gps`) |
| Hardware/Uhr | lesend vor schreibend; jede automatische Aktion umkehrbar, mit Ereignis und Probelauf |
| Tests | jede Funktion mit Unit- oder Replay-Test; Datenschutz-Tests (Koordinate im Text → entfernt) für jeden Kanal |

## 4. Offene Fragen

1. **Umfang 1.4:** volles Paket (≈ 3–4 Monate) oder schlankes 1.4 (≈ 6–8 Wochen, siehe oben)
   mit schnellerem Release und 1.4.x-Nachlieferungen?
2. **MQTT jetzt oder später:** Erst REST-Sensor-Doku und MQTT nur bei Nachfrage – oder gleich
   paho als erste Nicht-stdlib-Abhängigkeit?
3. **HTTPS im Dashboard:** stdlib-TLS bauen oder nur Reverse Proxy dokumentieren (vgl.
   [bausteine.md, Offene Fragen](bausteine.md#5-offene-fragen-entscheidung-des-maintainers))?
4. **E-Mail-Kanal:** eigener `smtplib`-Kanal (Passwort-Speicherung, TLS-Varianten, Support-Fragen)
   oder nur über Apprise-API?
5. **Vollbild-Uhr ohne Anmeldung:** Soll es diesen Schalter geben? Er ist bequem für
   Wandmonitore, öffnet aber die erste unauthentifizierte Seite neben `/healthz`.
