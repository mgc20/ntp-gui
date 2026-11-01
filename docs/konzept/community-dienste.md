# Community-Dienste (eigenes Repository)

Stand: 01.11.2026 · Grundlage: [ROADMAP](../../ROADMAP.md) (Abschnitt „Community-Dienste“),
`app/egress.py` (1.3, Zwecke `diagnostics` / `recording` / `community`),
[Entscheidungsrahmen](entscheidungsrahmen.md), [Bausteine](bausteine.md)

Die Community-Dienste sind **freiwillig und zusätzlich**. ntp-gui funktioniert ohne sie
vollständig. Keine Instanz muss für sie einen Port öffnen; alles, was eine Instanz sendet, ist
opt-in, läuft durch den zentralen Filter und erlaubt keine Ortsbestimmung.

## 1. Kurzfassung und Startempfehlung

| # | Stufe | Nutzen | Aufwand | Eigener Server-Code | Kernbaustein |
|---|---|---|---|---|---|
| 1 | Hardware-Kompatibilitätsliste (HCL) + GPS-Startwerte 🔒 | ★★★ | 2–4 PT | **keiner** | GitHub Issue-Formular + Action, Hugo |
| 2 | Öffentliche NTP/NTS-Server im NTP Pool | ★★★ | 1–2 PT, dann ≈ 1 h/Monat | **keiner** | ntp-gui selbst (chrony), Caddy |
| 3 | Zeit-Check-Website | ★★ | 2–3 PT | **keiner** (Caddy-Platzhalter) | Caddy, Hugo, ≈ 300 Zeilen JS |
| 4 | Zeitwächter (Ausfallalarm) 🔒 | ★★ | 2–3 PT + 1 PT in ntp-gui | **keiner** | Healthchecks (oder Uptime-Kuma-Push) |
| 5 | Server-Test „Von außen prüfen“, nur eigene IP | ★★★ | 7–10 PT | Go, ≈ 1–1,5k Zeilen | beevik/ntp, beevik/nts |
| 6 | Statusseite öffentlicher Zeitserver | ★★ | 0,5 PT (Uptime Kuma) bzw. 2 PT (nach 5) | keiner bzw. Teil von 5 | Uptime Kuma ≥ 2.5 |
| 7 | Server-Test als öffentliches Formular (beliebige Ziele) | ★★ | +5 PT | Erweiterung von 5 | – (hier liegt das Missbrauchsrisiko) |
| 8 | Schwarm A: falsche Zeitquellen erkennen, ortsunabhängig 🔒 | ★★★ | 7–10 PT | klein | SQLite |
| 9 | Schwarm B: GNSS-Störungen regional 🔒 | ★★★ | Wochen bis Monate | groß | MapLibre (nur mit Vorbehalt, s. u.) |

**Empfohlener Start:** Stufe **1 (HCL)** und Stufe **2 (Pool-Server)** – bestes Verhältnis von
Nutzen zu Aufwand, **ohne eigenen Server-Code**. Danach 3 und 4, die ebenfalls nur fertige
Software konfigurieren. Der größte Einzelnutzen (Stufe 5) ist das erste eigene Stück Server-Code;
es startet bewusst als **Selbsttest ohne Zielfeld**, was SSRF und Missbrauch als Reflektor
ausschließt. Das öffentliche Formular (7) und der regionale Schwarm (9) kommen nur, wenn die
früheren Stufen Nutzer haben.

**Leitentscheidungen (Sicherheit durch Einfachheit):**
1. **Statisch, wo es geht:** Hugo baut die Website, Caddy liefert aus, **ohne Zugriffslogs**.
2. **Fertige Software statt eigenem Code:** Caddy, chrony/ntp-gui, Healthchecks, Uptime Kuma, GitHub Issues/Actions; eigener Code nur als dünne Schicht über beevik/ntp + beevik/nts.
3. **Der Test-Dienst prüft standardmäßig nur die anfragende IP.**
4. **Keine neue Datenbankfamilie:** SQLite oder JSON-Dateien. Zeitreihen-DBs erst, falls Schwarm B wirklich kommt.
5. **Kein Analytics, keine Cookies** → kein Consent-Banner nötig (§ 25 TDDDG).

## 2. Geprüfte Bausteine

| Projekt | Was es kann | Lizenz | Pflege/Reife | Verwendung |
|---|---|---|---|---|
| **chrony** | NTP/NTS-Server, `ratelimit`/`ntsratelimit`, kein Mode 7 | GPL-2.0 | Debian-Standard, aktiv | Pool-Server (über ntp-gui) |
| **ntpd-rs** | NTP+NTS in Rust, Metrik-Exporter, experimentelle NTS-Pool-Unterstützung; 2.0-Alpha mit großem Umbau | Apache-2.0 OR MIT | aktiv; CVE-2026-26076 (DoS durch NTS-Pakete) in 1.7.1 behoben; in Debian | optional: ein VPS im **experimentellen NTS-Pool** |
| **pendulum-project/nts-pool** | Verwaltung und NTS-KE-Server für NTS-Pools, „work in progress“ | *(n. g.)* | experimentell, IETF-Draft (Experimental) | nur beobachten |
| **beevik/ntp** (Go) | SNTP-Client, `QueryWithOptions`, `Response.Validate` | BSD-2 | etabliert | Test-Dienst: NTP-Messung |
| **beevik/nts** (Go) | NTS-Client (RFC 8915), eigener TLS-Config, **Dialer** und Resolver | BSD-2 | klein (≈ 35 Commits, 26 Sterne, **keine Releases**, geprüft 01.11.2026), **Bus-Faktor 1** | Test-Dienst: NTS-KE + authentisierte Abfrage; über den Dialer lässt sich die IP-Sperre durchsetzen |
| **ntppool/monitor** | Monitor-Agent des NTP Pools, < 20 MB RAM | MIT | aktiv, an Pool-Infrastruktur gebunden | **nicht** als Basis; VPS als Pool-Monitore anbieten (Beitrag zur Szene) |
| **Uptime Kuma** | NTP-Monitor ab 2.5 (Stratum, Offset, RefID …), **kein NTS**, Push-Monitore, Statusseiten | MIT | sehr aktiv | Statusseite 6a; Alternative zum Zeitwächter |
| **Gatus** | HTTP/TCP/UDP/DNS…, UDP nur Verbindungsaufbau, kein NTP | Apache-2.0 | aktiv | **ungeeignet** |
| **Healthchecks** | Dead-Man-Switch per Ping-URL, `/fail`, Alarme u. a. über ntfy, Selbstregistrierung | BSD-3 | sehr aktiv (v5.0, Oktober 2026) | **Zeitwächter** |
| **ntfy** | Push-Benachrichtigungen | Apache-2.0/GPL-2.0 | aktiv | Alarmkanal |
| **SuperQ/chrony_exporter** | Prometheus-Exporter für chrony | Apache-2.0 *(n. g.)* | v0.14.0 (Aug. 2026) | Überwachung der eigenen VPS, falls Prometheus läuft |
| **NTPmon** | Check mit Schwellen nach RFC 8633 | **AGPL-3.0** | Debian-Paket vorhanden *(Aktivität n. g.)* | nur **Idee** für die Schwellen (aus RFC 8633 selbst ableiten); **keinen Code übernehmen**, sonst AGPL für den Test-Dienst |
| **nmap NSE** `ntp-monlist`/`ntp-info` | Mode-7/Mode-6-Abfragen | NPSL | etabliert | **Test-Orakel in CI**, nicht eingebettet |
| **Caddy** | automatisches HTTPS, Platzhalter `{time.now.unix_ms}`, ohne `log` keine Zugriffslogs | Apache-2.0 | sehr aktiv | Webserver, Zeit-Endpunkt |
| **mholt/caddy-ratelimit** | Rate-Limit-Modul, nicht im Standard-Build (nur per `xcaddy`-Eigenbuild) | Apache-2.0 | aktiv | **meiden**, weil Eigenbuild = eigene Image-Pflege; Limits im Test-Dienst selbst |
| **Hugo** | statische Seiten, ein Binary | Apache-2.0 | sehr aktiv | Website (einfacher als Astro mit npm-Kette) |
| **MapLibre GL JS** | Vektorkarten | BSD-3 | aktiv | nur Schwarm B |
| **Plausible** | Webanalyse | AGPL-3 | – | **weglassen** |

**Es gibt keine fertige „SSL Labs für NTP“-Software** – nur Kommandozeilenwerkzeuge (NTS-Tester,
`ntske-test`, nmap-Skripte). Der Test-Dienst wird also selbst gebaut, aber als dünne Schicht.

## 3. Repository und Betrieb

```
ntp-community/
  site/                     Hugo: Zeit-Check, Erklärseiten, HCL, Statusseite, Impressum/Datenschutz
    data/hardware/*.json    von der Action erzeugt (ein Bericht je Datei)
    data/help.json          aus ntp-gui exportiert (gleiche ⓘ-Texte, MIT)
  tester/                   Go-Modul: Test-Dienst (coordinator | probe | status-cron)
  schemas/                  JSON-Schemas der Datenverträge (versioniert, Abschnitt 6)
  deploy/
    compose.edge.yml        je VPS: ntp-gui (Pool-Server) + Caddy (Zeit-Endpunkt) + tester probe
    compose.core.yml        ein VPS: Caddy (Site) + tester coordinator + Healthchecks (+ Uptime Kuma)
    hosts/<vps>.env         außerhalb von Git bzw. mit sops verschlüsselt
  .github/ISSUE_TEMPLATE/hardware-report.yml
  .github/workflows/{hcl.yml, site.yml, tester.yml, deploy.yml}
```

- **Images per Digest pinnen**, Updates per Renovate/Dependabot – bewusst, kein Watchtower.
- **Deploy:** Action → SSH → `docker compose pull && up -d`; einfachere Alternative: Cron mit `git pull` auf dem VPS (kein SSH-Schlüssel in GitHub).
- **Zwischen den VPS:** WireGuard (Kernel). Die Probe-API lauscht nur auf `wg0`.
- **Offene Ports:** 80/443 (Caddy), 123/udp (NTP), 4460/tcp (NTS-KE). Sonst nichts.
- **Website auf dem eigenen VPS**, nicht GitHub Pages (das gäbe Besucher-IPs an GitHub). Gebaut wird trotzdem in Actions.

## 4. Stufen im Detail

### Stufe 1: Hardware-Kompatibilitätsliste und GPS-Startwerte (kein Server)

**Ablauf**
1. Auf der Hardware-Seite: „Mit der Community teilen“. ntp-gui baut den Bericht: `hardware.report()` → **Projektion auf die Allowlist** (`hardware-report@1`) → `egress.sanitize(purpose="community")` → `egress.check_no_leaks()`. Findet die Prüfung etwas, wird nichts exportiert. Dann Vorschau.
2. Klick auf „Auf GitHub öffnen“: **Der Browser** öffnet `…/ntp-community/issues/new?template=hardware-report.yml&report=<JSON>`. GitHub füllt Issue-Formularfelder per Query-Parameter vor; zu lange URLs ergeben `414`, darum bleibt der Bericht < 6 KB. Rückfall: „JSON kopieren“.
   - **Die Instanz selbst baut keine Verbindung auf.**
   - Ehrlich: Der Nutzer braucht ein GitHub-Konto, und der Bericht hängt öffentlich daran. Das steht in der Vorschau.
3. Eine **GitHub Action** validiert gegen das Schema (stdlib) und lässt **`egress.check_no_leaks` aus dem ntp-gui-Tag erneut laufen** (Filter wiederverwendet). Sie kommentiert und setzt Labels.
4. Der Maintainer setzt `approved` → die Action schreibt `site/data/hardware/<issue>.json`, committet, schließt das Issue.

**GPS-Startwerte:** Median je (Modul, Anbindung, PPS-Art) ab **n ≥ 3** Berichten → `offsets.json`. **Die Tabelle wird beim Release fest in ntp-gui eingebaut** – keine Laufzeitverbindung. Die automatische GPS-Kalibrierung aus 1.3 startet dann mit dem Community-Wert statt mit 0.

**Aufwand:** 2–4 PT. **Risiko:** gering; Freigabe per Label verhindert ungeprüfte Daten.

### Stufe 2: Öffentliche NTP/NTS-Server

- **ntp-gui selbst auf den VPS** (nur Netzquellen, Dashboard an `127.0.0.1`) – Eigenbetrieb erprobt das Produkt. NTS-Zertifikat: Caddy holt es, chrony liest es aus dem gemeinsamen Volume (Mechanik aus 1.2).
- **NTP-Pool-Anforderungen:** statische IP (Änderung höchstens jährlich), dauerhafte Verbindung, ≈ 384–512 kbit/s, Stratum 3–4 erlaubt, **nicht pool.ntp.org als Upstream**. Last per „netspeed“. Größenordnung ≈ 22 Anfragen/s ≈ 4 GB/Monat.
- **Upstream:** PTB, Netnod, Cloudflare (NTS). **Keine Leap-Smearing-Quellen** (Google, AWS) beimischen.
- **Härtung:** `ratelimit interval 1 burst 16`, `ntsratelimit`, `cmdport 0`. chrony beantwortet kein Mode 7 → keine Verstärkung.
- **NTS:** Der NTP Pool verteilt kein NTS → eigene Liste veröffentlichen (`nts1.<domain>` …). **Optional:** ein VPS mit ntpd-rs im **experimentellen NTS-Pool** – nur als Experiment, der Standard ist Draft.
- **Nebenbei:** VPS als Monitore für den NTP Pool anbieten.

**Aufwand:** 1–2 PT, danach ≈ 1 h/Monat. **Risiko:** IP-Wechsel des VPS erfordert neuen Pool-Eintrag; Steal-Time im Dashboard beobachten.

**Nicht vergessen:** laufende Kosten (je VPS ≈ 4–10 €/Monat, Domain), Abuse-Meldungen
(NTP-Server ziehen Scans und Beschwerden an) und das **Impressum mit ladungsfähiger Anschrift**
(§ 5 DDG) – für einen privaten Maintainer eine echte Hürde. Ein Pool-Server ist zudem ein
Dauerversprechen: Wer ihn abschaltet, muss ihn im Pool vorher abmelden.

### Stufe 3: Zeit-Check-Website

- **Ohne eigenen Server-Code:** Caddy beantwortet `/t` mit `respond "{time.now.unix_ms}"`, `Cache-Control: no-store`, CORS nur für die eigene Site. Die Seite misst per `fetch` über Keep-Alive 12–20 Proben je Standort, verwirft die erste, nimmt die mit der kleinsten RTT: `offset = t_server − (t0 + t3)/2`, Fehlergrenze `±(RTT/2 + 1 ms)`. Jeder Standort einzeln angezeigt.
- **Browser, die die Uhr runden** (Firefox `privacy.resistFingerprinting`, Tor/Mullvad Browser: 100 ms): Erkennung, wenn alle Werte Vielfache von 100 sind → Hinweis statt Fehler.
- **Erklärseiten** aus `data/help.json`, im ntp-gui-CI aus den ⓘ-Texten exportiert → eine Textquelle für beide Projekte.
- **Kein Tracking:** keine Cookies, kein localStorage, keine fremden Fonts/CDNs, strenge CSP, Caddy ohne `log`.

**Aufwand:** 2–3 PT. **Risiko:** gering.

### Stufe 4: Zeitwächter

- Selbst gehostetes **Healthchecks**; Nutzer registrieren sich dort selbst und tragen die **Ping-URL** in ntp-gui ein (Einstellung „Zeitwächter-URL“, Teil der 1.4-Benachrichtigungen).
- ntp-gui ruft alle N Minuten `GET <url>` bei „alles gut“ und `GET <url>/fail` bei eigenem Fehler auf. **Keine Nutzdaten.** Bleibt der Ping aus, alarmiert Healthchecks.
- **Kein Lock-in:** gleiche Einstellung funktioniert mit healthchecks.io, eigenem Healthchecks oder Uptime-Kuma-Push. ntp-gui implementiert nur „pinge URL X“ (≈ 30 Zeilen).
- **Personenbezug:** E-Mail-Adressen → Datenschutzerklärung, Löschkonzept, Backup-Frist, SMTP nötig.
- **Ehrlich in der Vorschau:** Der Ping hat keinen Inhalt, aber der Betreiber des Wächters sieht alle N Minuten die öffentliche IP (grob ortbar per GeoIP) und wann die Instanz läuft. Für Nutzer, die das nicht wollen: eigenes Healthchecks bzw. Uptime Kuma im LAN.
- **Empfehlung:** Der ntp-gui-Teil (≈ 30 Zeilen) lohnt sich **sofort in 1.4**, unabhängig davon, ob das Projekt je einen eigenen Wächter betreibt.

**Aufwand:** 2–3 PT Betrieb + 1 PT in ntp-gui.

### Stufe 5: Server-Test, zuerst als Selbsttest

**Architektur:** ein Go-Binary `tester`: `coordinator` (Kern-VPS hinter Caddy, prüft Limits, verteilt über WireGuard), `probe` (je Edge-VPS, nur `wg0`), `status-cron` (Stufe 6b).

| Prüfung | Umsetzung | Ergebnis |
|---|---|---|
| NTP: Stratum, RefID, Leap, Root Delay/Dispersion, Offset und RTT je Standort | beevik/ntp, 3 Abfragen je Probe, ≥ 2 s Abstand | Werte; Asymmetrie sichtbar |
| IPv4 und IPv6 | getrennte Namen `test4.` / `test6.` | je Adressfamilie |
| NTS-KE: TLS 1.3, ALPN `ntske/1`, AEAD, Cookies | beevik/nts mit eigenem Dialer | ok/Fehler mit Erklärung |
| Zertifikat: Kette, Name, Tage bis Ablauf | `tls.ConnectionState` | Warnung < 14 Tage |
| authentisierte NTP-Abfrage über NTS | beevik/nts | ok/Fehler |
| Mode 6 beantwortet? | ein 12-Byte-Paket, ≤ 2 KB gelesen | Warnung mit Verstärkungsfaktor |
| Mode 7 (monlist) beantwortet? | ein Paket, ≤ 2 KB, nie wiederholt | kritisch |
| Note A–F | Schwellen nach RFC 8633 (wie NTPmon) | Note + Befunde |

**Missbrauchs- und SSRF-Schutz** (im Go-Code, Caddy bleibt Standard):
1. **Selbsttest (Standard):** **kein Zielfeld**; getestet wird die Quell-IP der HTTPS-Verbindung. Ein optionaler NTS-Name wird nur genutzt, wenn er genau auf diese IP auflöst. Mode-6/7-Prüfungen sind hier vertretbar, weil Ziel und Auftraggeber identisch sind.
2. **Öffentliches Formular (Stufe 7, später):** IP-Prüfung **beim Verbinden** (`net.Dialer.Control`, schützt gegen DNS-Rebinding); Sperrliste privater, reservierter und Dokumentationsnetze (inkl. `100.64.0.0/10`, `::ffff:0:0/96` entpackt, `64:ff9b::/96`, `fc00::/7`, eigene VPS-Netze); nur Ports 123/udp und 4460/tcp; **kein Mode 6/7 gegen fremde Ziele**.
3. **Limits:** je Quell-IP (IPv6 je /64) 10 Tests/h; je Ziel 1 Test/10 min (Cache); global ≤ 20 gleichzeitig; Timeouts UDP 2 s, TLS 5 s, gesamt 20 s; Lesegrenzen UDP 2 KB, NTS-KE 16 KB. Zähler im Speicher, **IPs gehasht mit täglich rotierendem Salt**, TTL 1 h.
4. Opt-out-Liste für Betreiber, Abuse-Kontakt im Impressum, User-Agent/SNI nennen den Dienst.
5. Fällt der Dienst aus, bleibt ntp-gui voll funktionsfähig („Dienst nicht erreichbar“).

**Datenschutz:** Die Ziel-IP ist personenbezogen; sie wird verarbeitet, **nicht gespeichert**; Ergebnis nur an den Aufrufer. RTTs je Standort erlauben grobe Ortung → nicht veröffentlichen, **keine teilbare Ergebnis-URL mit Ziel** (bewusst anders als SSL Labs).

**Aufwand:** 7–10 PT, Formular +5 PT – für einen Maintainer, der bisher nur Python pflegt, eher am oberen Ende, denn Go ist eine **zweite Sprache mit eigener Toolchain, CI und Abhängigkeitspflege**. **Risiko:** beevik/nts (Bus-Faktor 1, keine Releases) → per Pseudo-Version in `go.mod` pinnen, `go mod vendor`, in CI gegen Cloudflare/Netnod/PTB testen, im Notfall forken (BSD-2, überschaubar).

### Stufe 6: Statusseite öffentlicher Zeitserver

- **6a (0,5 PT):** Uptime Kuma ≥ 2.5 mit NTP-Monitoren (PTB, Cloudflare, Netnod, time.nl, Pool DE/EU, eigene Server). Grenzen: kein NTS, ein Messort.
- **6b (≈ 2 PT, nach 5):** `tester status-cron` misst alle 5 min von allen Proben, inkl. NTS und Zertifikatsablauf → `status.json` (30 Tage SQLite) → statische Seite. Danach entfällt Uptime Kuma.
- Last für Fremdserver: ≤ 1 Abfrage je 5 min je Probe und Server.

### Stufe 8/9: Schwarm

- **Vorbild GPSJam:** 24-h-Aggregate in Hexagonen aus ADS-B-Integritätsangaben (NIC/NACp) vieler Flugzeuge. **adsb.lol** bietet freie Daten (Lizenz vor Nutzung prüfen) – eine Overlay-Karte wäre ohne eigene Datensammlung möglich.
- **Phase A (empfohlen, 7–10 PT), ortsunabhängig:** Opt-in-Instanzen melden stündlich je **bekanntem öffentlichem Zeitserver** (nur Namen aus `PUBLIC_TIME_HOSTS` des Filters) Offset (1 ms gerundet), Delay (10 ms gerundet, wie `purpose="community"` schon tut), Erreichbarkeit, GNSS-Zustand als Klasse (`ok|degraded|lost`) und **PPS gegen Netzkonsens** (Spoofing-Signatur). Server: Median/MAD; Zeitserver „falsch“ erst bei ≥ 5 Instanzen aus ≥ 5 verschiedenen /24 bzw. /48. Globale GNSS-Ereignisse erkennt man am Anteil betroffener Instanzen – **ohne Ort**.
  - Vergiftungsschutz: monatlich rotierendes Instanz-Token (keine dauerhafte Kennung), Rate-Limit, robuste Statistik, Mindestanzahl. Ergebnisse sind „Hinweise“, nie Beweise.
- **Phase B (nur mit Vorbehalt):** steht im **direkten Konflikt mit „keine Ortsbestimmung“**. Vertretbar nur so: Nutzer wählt eine grobe Region selbst aus einer Liste (Bundesland bzw. H3-Auflösung ≤ 3, ≈ 12.000 km²), **nie aus GPS abgeleitet**; Veröffentlichung nur bei **k ≥ 5** je Zelle, 24 h verzögert, als Tagesaggregat. Restrisiko in dünn besiedelten Zellen. Ehrlich: Bodenstationen sehen Jamming viel schlechter als Flugzeuge; der Mehrwert liegt beim **Zeit-Spoofing**, nicht in der Fläche. Erst angehen, wenn Phase A Nutzer hat.

## 5. Sicherheit, Datenschutz, Recht

**Sicherheit**
- Eigener Code nur im Test-Dienst und im Schwarm-Endpunkt: Go, distroless, read-only Root-FS, keine Capabilities, Nicht-Root. Nur Caddy spricht öffentlich HTTP.
- NTP-Verstärkung: eigene Server ohne Mode 6/7 (chrony); der Tester sendet je Prüfung genau ein kleines Paket.
- Geheimnisse (WireGuard, SMTP, Healthchecks) nur in `hosts/*.env` außerhalb von Git bzw. mit sops.
- Lieferkette: Images per Digest, `go.sum` + `govulncheck` in CI, Hugo-Version gepinnt.
- Wacklige Bausteine: beevik/nts und das NTS-Pool-Experiment – beide ersetzbar oder optional.

**Datenschutz und deutsches Recht** *(kein Rechtsrat; vor Betrieb einmal fachkundig prüfen lassen)*

| Dienst | Was wird verarbeitet | Regel |
|---|---|---|
| alle Webangebote | – | Impressum nach § 5 DDG, mit Abuse-Kontakt; Datenschutzerklärung nach Art. 13 DSGVO je Dienst |
| Website / Zeit-Check | IP nur zur Auslieferung (Art. 6 Abs. 1 lit. f) | keine Zugriffslogs, keine Cookies, kein localStorage → kein Consent nach § 25 TDDDG |
| Test-Dienst | Ziel-IP, ggf. NTS-Name | verarbeitet, nicht gespeichert; Limit-Zähler gehasht ≤ 1 h; falls Sicherheitslogs nötig: höchstens 7 Tage (Praxiswert nach BGH III ZR 391/13) |
| NTP-Server | Client-IPs | chrony hält Statistiken nur im Speicher |
| Zeitwächter | E-Mail, Ping-Zeitpunkte | Vertrag (lit. b), Löschung mit dem Konto, Backups mit Frist |
| HCL | Bericht am GitHub-Konto | freiwillig; Hinweis, dass GitHub Verantwortlicher der Plattform ist |

## 6. Datenverträge mit ntp-gui

Allgemein: Jede Nachricht trägt `"schema": "ntp-gui/<name>@<major>"`. Unbekannte Felder werden
auf beiden Seiten **verworfen** (Allowlist-Projektion **vor** `sanitize`). Neue Felder kommen
optional in Minor-Versionen; Entfernen oder Umdeuten erhöht die Major-Version. Die Schemas liegen
in `ntp-community/schemas/`; ntp-gui hat einen Test, der seine Ausgaben dagegen prüft.

### 6.1 `hardware-report@1` (Zweck `community`; Browser → GitHub-Issue)

```json
{
  "schema": "ntp-gui/hardware-report@1",
  "ntp_gui": "1.3.0",
  "month": "2026-11",
  "platform": {"arch": "aarch64", "board_family": "raspberry-pi",
               "board_model": "Raspberry Pi 5 Model B Rev 1.0", "hypervisor": null,
               "container": "docker", "network": "host", "kernel": "6.6"},
  "receivers": [{"usb_vid": "1546", "usb_pid": "01a9", "product": "u-blox GNSS receiver",
                 "driver": "cdc_acm", "gpsd_subtype": "u-blox", "module": "ZED-F9T",
                 "generation": "9", "timing": true, "pps": "gpio", "pps_ok": true}],
  "ptp": [{"driver": "igc", "hw_timestamping": true, "phc": true}],
  "rtc": {"present": true, "driver": "rpi-rtc"},
  "matrix": [{"key": "gps", "status": "ok"}, {"key": "pps", "status": "warn"}],
  "gps_offset": {"source": "auto", "offset_ms": 123.4, "sigma_ms": 2.1, "hours": 24},
  "note": ""
}
```

- **Nie enthalten:** Seriennummern, `by-id`-Pfade, MAC, PTP-Clock-ID, Hostname, Titel, Zeitzone, Koordinaten, Satellitenwinkel, genaue Zeitpunkte (nur Monat), volle Kernel-Version (nur Major.Minor).
- `note` ist Freitext → `sanitize_text` + `check_no_leaks`.

### 6.2 `external-test-request@1` (Instanz → Test-Dienst, HTTPS POST, ausgehend)

```
POST https://test4.<domain>/api/v1/selftest      (bzw. test6. für IPv6)
```
```json
{
  "schema": "ntp-gui/external-test-request@1",
  "client": "ntp-gui/1.4.0",
  "checks": ["ntp", "nts", "cert", "mode6", "mode7"],
  "ntp_port": 123,
  "nts": {"name": "time.example.org", "port": 4460}
}
```

- **Kein Zielfeld.** Ziel ist die Quell-IP.
- `nts.name` ist der eigene Domainname – genau das, was der Filter sonst entfernt. Er wird als **ausdrücklich bestätigtes Feld** behandelt: Die Vorschau sagt „Gesendet werden: deine öffentliche IP (technisch unvermeidbar) und der Name time.example.org“. Im Filter braucht es dafür eine `allow_fields={"nts.name"}`-Ausnahme für genau diesen Vertrag – eine kleine Änderung am 1.3-Filter, abzustimmen mit dessen Stand.
- Antwort: Befunde mit Schlüsseln (`ntp.ok`, `nts.cert_days` …), deutsche Texte werden in ntp-gui aus Schlüsseln erzeugt (gleiche ⓘ-Quelle), Größe ≤ 32 KB.

### 6.3 Zeitwächter-Ping (Instanz → Healthchecks o. Ä.)

- `GET <url>` bzw. `GET <url>/fail`, **ohne Body**, User-Agent `ntp-gui` ohne Version. Die URL selbst ist ein Geheimnis (maskiert, nie im Diagnosepaket).

### 6.4 `swarm-report@1` (nur Schwarm A, stündlich, opt-in)

```json
{
  "schema": "ntp-gui/swarm-report@1",
  "token": "<monatlich rotierend>",
  "hour": "2026-11-01T14",
  "servers": [{"name": "ptbtime1.ptb.de", "offset_ms": 0, "delay_ms": 20, "reachable": true}],
  "gnss": "ok",
  "pps_vs_net_ms": 0
}
```

- `servers[].name` nur aus `PUBLIC_TIME_HOSTS`; Offset auf 1 ms, Delay auf 10 ms gerundet; Stunde statt Zeitstempel; keine Version, kein Hostname, keine IP-Liste.
- **Ortungsrisiko durch Laufzeiten (Gegenprüfung):** Laufzeiten zu *mehreren* bekannten
  Servern an verschiedenen Orten (PTB, Netnod, time.nl, NIST …) sind ein Fingerabdruck des
  Standorts – selbst auf 10 ms gerundet reicht das bei 5–10 Servern für Land oder Region
  (Prinzip der RTT-Trilateration, das auch Stufe 5 als Risiko nennt). Das widerspricht „keine
  Ortsbestimmung“. Darum: **`delay_ms` im Schwarm-Bericht weglassen** (für „falsche Zeitquelle“
  genügen Offset und Erreichbarkeit) oder höchstens als Klasse `ok|hoch` ohne Zahl. Gleiches gilt
  für die Delay-Rundung im 1.3-Filter bei `purpose="community"`: Für Zwecke, die Delays zu vielen
  Servern zugleich enthalten, ist Runden allein kein ausreichender Schutz.
- **Quell-IP:** Der Schwarm-Server sieht die IP jeder meldenden Instanz. Die Regel „≥ 5
  verschiedene /24 bzw. /48“ darf nur mit einem gesalzenen Hash des Präfixes im Speicher arbeiten
  (Salt rotiert täglich, nichts auf Platte); Caddy davor ohne Zugriffslog.

## 7. Aufwand und Nutzen im Überblick

| Reihenfolge | Stufen | Summe Aufwand | Was die Community bekommt |
|---|---|---|---|
| Start | 1 + 2 | 3–6 PT | Hardware-Liste, bessere GPS-Startwerte in jedem Release, eigene Pool- und NTS-Server |
| danach | 3 + 4 + 6a | 5–7 PT | Zeit-Check für alle (auch ohne ntp-gui), Ausfallalarm, Statusseite |
| dann | 5 (+ 6b) | 9–12 PT | „Von außen prüfen“ mit Note, NTS-fähige Statusseite |
| bei Bedarf | 7, 8 | 12–15 PT | öffentlicher Test, Erkennung falscher Zeitquellen |
| vielleicht | 9 | Wochen–Monate | regionale GNSS-Störungskarte (nur mit k-Anonymität) |

## 8. Quellen

- NTP Pool: [Server beitragen](https://www.ntppool.org/en/join.html) · [ntppool/monitor](https://github.com/ntppool/monitor)
- NTS-Pool: [pendulum-project/nts-pool](https://github.com/pendulum-project/nts-pool) · [ntpd-rs](https://github.com/pendulum-project/ntpd-rs) · [draft-ietf-ntp-nts-keyexchange-pool](https://datatracker.ietf.org/doc/draft-ietf-ntp-nts-keyexchange-pool/)
- Go-Bibliotheken: [beevik/ntp](https://github.com/beevik/ntp) · [beevik/nts](https://github.com/beevik/nts)
- Monitoring: [Uptime Kuma](https://github.com/louislam/uptime-kuma) · [Healthchecks](https://github.com/healthchecks/healthchecks) · [Gatus](https://github.com/TwiN/gatus) · [chrony_exporter](https://github.com/SuperQ/chrony_exporter) · [NTPmon](https://github.com/paulgear/ntpmon) · [RFC 8633 (NTP Best Current Practices)](https://www.rfc-editor.org/rfc/rfc8633) · [RFC 8915 (NTS)](https://www.rfc-editor.org/rfc/rfc8915)
- Caddy: [Platzhalter (`time.now.unix_ms`)](https://caddyserver.com/docs/conventions#placeholders) · [caddy-ratelimit](https://github.com/mholt/caddy-ratelimit)
- GitHub: [Issue-Formulare, Vorbelegung per Query-Parameter](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
- Schwarm: [GPSJam FAQ](https://gpsjam.org/faq) · [adsb.lol](https://www.adsb.lol/)
- nmap: [ntp-monlist](https://nmap.org/nsedoc/scripts/ntp-monlist.html)
- Recht: [§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html) · [§ 25 TDDDG](https://www.gesetze-im-internet.de/ttdsg/__25.html) · BGH, Urteil vom 03.07.2014, III ZR 391/13 (Speicherung von IP-Adressen bis 7 Tage zur Störungsabwehr) *(Aktenzeichen aus der Recherche, Volltext nicht neu geprüft)*
- Gegenprüfung 01.11.2026: [beevik/nts](https://github.com/beevik/nts) · [NTPmon-Lizenz (AGPL-3.0)](https://github.com/paulgear/ntpmon) · [Uptime Kuma 2.5 mit NTP-Monitor](https://linuxiac.com/uptime-kuma-2-5-adds-ntp-monitoring-and-rootless-docker-support/) · [CVE-2026-26076 (Debian-Tracker)](https://security-tracker.debian.org/tracker/CVE-2026-26076) · [Healthchecks-Releases (v5.0.3)](https://github.com/healthchecks/healthchecks/releases)
- Versionen und Pflegestände (Healthchecks v5.0, Uptime Kuma 2.5/3.0-beta, ntpd-rs 1.7.1/2.0-alpha, chrony_exporter v0.14.0, CVE-2026-26076) stammen aus der Recherche vom 01.11.2026 und sollten vor dem Aufbau eines Dienstes erneut geprüft werden.

## 9. Offene Fragen

1. **Betreiberrolle:** Will der Maintainer überhaupt öffentlich auftreten (Impressum mit
   Anschrift, Abuse-Kontakt, laufende VPS-Kosten)? Wenn nein, bleiben nur Stufe 1 (GitHub) und
   der Zeitwächter-Ping in ntp-gui (gegen fremde Healthchecks-Instanzen) – beides ohne eigenen Betrieb.
2. **Zweite Sprache Go** für den Test-Dienst, oder Python mit eigenem dünnen NTS-Client?
   Go hat die passenden Bibliotheken; Python hält alles in einer Toolchain, NTS-Code wäre aber
   eigener Kryptografie-nahe Code (nicht empfohlen).
3. **Schwarm A ohne Laufzeiten:** Reicht Offset + Erreichbarkeit für den Nutzen? (Empfehlung: ja,
   `delay_ms` streichen.)
4. **Schwarm B (Region):** grundsätzlich streichen, weil „keine Ortsbestimmung“ hier nur
   statistisch (k ≥ 5) und nicht technisch garantiert ist? Vorschlag: nicht planen, bis Phase A
   ein Jahr läuft.
5. **Website-Hosting:** eigener VPS (keine Besucher-IPs an Dritte, aber Betrieb) oder GitHub
   Pages für die rein statischen Teile (HCL, Erklärseiten) und VPS nur für den Zeit-Endpunkt?
