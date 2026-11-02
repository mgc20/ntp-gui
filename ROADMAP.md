# Roadmap

ntp-gui soll ein Community-Projekt werden: ein Zeitserver fürs Heimnetz, der sich selbst
erklärt, und darum herum Dienste, von denen alle etwas haben. Die Punkte sind nach
**Nutzen** und **Aufwand** gestaffelt. Was oben steht, kommt zuerst.

Legende: ★ Nutzen (★★★ hoch) · ◆ Aufwand (◆◆◆ groß) · 🔒 betrifft Datenschutz

Vorschläge, Erfahrungsberichte und Hilfe sind willkommen – siehe [CONTRIBUTING.md](CONTRIBUTING.md).

## Grundsätze

- **Läuft lokal, ohne Cloud.** Alles, was Daten nach außen schickt, ist ein freiwilliges
  Zusatzmodul, standardmäßig aus.
- **Kein Standort, keine Kennung.** Exporte und geteilte Daten gehen durch einen zentralen
  Datenschutzfilter: keine Koordinaten, keine Satellitenwinkel, keine Seriennummern, keine
  MAC- oder öffentlichen IP-Adressen. Vor jedem Export gibt es eine Vorschau.
- **Nur ausgehende Verbindungen.** Keine Instanz muss einen Port für einen Dienst öffnen.
- **Jeder Wert wird erklärt.** Neue Anzeigen bekommen immer eine ⓘ-Erklärung.

## 1.2 – Hardware-Check, NTS hinter dem Proxy, All-in-one ✅

- Hardware-Check: Was kann diese Hardware von dem, was ntp-gui kann? (GPS-Empfänger,
  PPS, PTP-Netzwerkkarten, VM, Container-Rechte, Echtzeituhr)
- PTP-Grandmaster verteilt die GPS-Zeit (phc2sys-Richtung, Grandmaster-Daten)
- Optionale Dienste starten neu, statt den Container zu stoppen; GPS-Hotplug
- NTS-Server hinter Reverse Proxy (Nginx Proxy Manager, Zoraxy, Traefik, nginx, HAProxy)
- `docker-compose.all-in-one.yml`: kopieren, Optionen einkommentieren, fertig

## 1.3 – Fehlersuche, erzwungene Zeitserver, Fundamente ✅

| Thema | Nutzen | Aufwand | Stand |
|---|---|---|---|
| Diagnosepaket (ein Klick, mit Vorschau) und Log-Seite 🔒 | ★★★ | ◆ | ✅ |
| Zentraler Datenschutzfilter für alles, was die Instanz verlässt 🔒 | ★★★ | ◆◆ | ✅ |
| Zeitserver erzwingen: DNS-Umschreibung (AdGuard, Pi-hole, dnsmasq) und Firewall-Umleitung (OPNsense, MikroTik, OpenWrt, UniFi, nftables) samt Prüfung | ★★★ | ◆ | ✅ |
| Passive Messung der Client-Uhren (Abweichung je Gerät aus der NTP-Anfrage) | ★★★ | ◆◆ | ✅ |
| Automatische GPS-Kalibrierung (aus / vorschlagen / automatisch, behutsam, umkehrbar) | ★★ | ◆◆ | ✅ |
| Ereignisprotokoll (Quellenwechsel, Fix verloren, Neustarts, Änderungen) | ★★ | ◆ | ✅ |
| SQLite als Datenspeicher, versionierte Einstellungen mit Migration | ★★ | ◆◆ | ✅ |
| Austauschbare Datenquellen mit Aufzeichnung/Wiedergabe (Entwicklung, Demo-Modus) | ★★ | ◆◆ | ✅ |
| API-Schlüssel mit Rechten (nur lesen / verwalten), versionierte API `/api/v1` | ★★ | ◆ | ✅ |

## 1.3.1 – Debian 13 „trixie“ ✅

- Basis-Image auf Debian 13 (chrony 4.6.1, gpsd 3.25, linuxptp 4.2, Python 3.13) – bookworm bekommt seit 07/2026 nur noch LTS-Updates
- Schaltsekunden über `leapseclist` (automatische Migration von `LEAPSECTZ`)
- Künftige Debian-Versionen werden zeitnah übernommen

## 1.3.2 – Übersicht, schnelles Diagnosepaket, ruhigere GPS-Ereignisse ✅

- Übersicht neu als „Single Pane of Glass“: Statusband mit Gesamturteil, Kennzahlen mit
  Verlaufslinie, Hinweise dem passenden Bereich zugeordnet
- Klarere Diagramme überall: jetzt/min/max/Mittel, Ausreißer markiert statt Skala gesprengt,
  Lücken sichtbar, Tooltip für Maus, Touch und Tastatur
- Diagnosepaket mit Aufzeichnung etwa 8× schneller, in eigenem Prozess mit niedriger Priorität;
  Download nach der Vorschau sofort und identisch
- GPS-Fix-Ereignisse erst nach 60 s – kein „verloren/wieder da“-Flattern bei schwachem Empfang
- Selbsttest „Zeitserver erzwingen“ prüft DNS-Umschreibung und Firewall-Umleitung getrennt,
  mit Hinweis zum Hairpin-Problem
- Clients: „Zuletzt“ und „Anfragen“ aus der eigenen Messung, wenn chrony das Gerät nach einem
  Neustart nicht mehr kennt

## 1.4 – Melden, Clients 2.0, eigene DNS-Server ✅

| Thema | Nutzen | Aufwand | Stand |
|---|---|---|---|
| Benachrichtigungen (Webhook, ntfy, Gotify, Apprise-API als Zusatzcontainer für E-Mail, Telegram, Matrix …) 🔒 | ★★★ | ◆◆ | ✅ |
| Eigene DNS-Server für ntp-gui (auch DoT/DoH) – keine Schleifen mehr, wenn der LAN-DNS Zeitserver-Namen umschreibt | ★★★ | ◆ | ✅ |
| Clients 2.0: Detailseite je Gerät, Netzüberblick, aktiv nachmessen, Alarm | ★★★ | ◆◆ | ✅ |
| Temperatur aufzeichnen (Grundlage für den Temperaturausgleich in 1.5) | ★★ | ◆ | ✅ |
| Schaltsekunden-Übersicht | ★ | ◆ | ✅ |
| Uhr-Ansicht im Vollbild (Rack-Monitor, Tablet) | ★ | ◆ | ✅ |
| Update-Hinweis (opt-in) 🔒, Attestation und SBOM im Release, Dependabot | ★★ | ◆ | ✅ |
| Anleitungen: Home Assistant, Homepage, Glance, Uptime Kuma, Grafana | ★★ | ◆ | ✅ |

## 1.5 – GNSS-Werkbank, Clients 3, Uhrqualität

Begründung, Bewertung und Abnahme: [docs/konzept/version-1.5.md](docs/konzept/version-1.5.md).
Erst ein schlankes 1.5.0, dann kurze 1.5.x-Releases.

| Thema | Nutzen | Aufwand | Stufe |
|---|---|---|---|
| GPS ohne PPS und schwacher Empfang (z. B. VK-162): Empfangsbewertung, Antennen-Test, ehrliches Profil | ★★★ | ◆ | 1.5.0 |
| DNS/NAT-Schleifen erkennen und erklären (AdGuard-Umschreibung, UniFi-Umleitung) | ★★★ | ◆ | 1.5.0 |
| GNSS-Störungen erkennen (Jamming/Spoofing) und GPS vorübergehend sperren | ★★★ | ◆◆ | 1.5.0 |
| Clients 3: Regeln je Gerät, Gruppen/VLAN-Ansichten, Uhrgüte je Gerät, NTS für Clients, Gerätepass | ★★★ | ◆◆ | 1.5.0 |
| Echter Holdover-Test („wie lange hält die Uhr ohne Quelle?“) | ★★ | ◆ | 1.5.0 |
| HTTPS fürs Dashboard über Caddy-Vorlage | ★★ | ◆ | 1.5.0 |
| Mehrsprachigkeit: Gerüst, dann englische Oberfläche (Weblate) | ★★★ | ◆◆◆ | 1.5.0 / 1.5.x |
| u-blox-Empfänger auslesen (Firmware, Jamming-Anzeige, Fähigkeiten) | ★★ | ◆◆ | 1.5.x |
| Temperaturausgleich: Fit, Vorschlag, anwenden mit 24-h-Probelauf | ★★ (★★★ ohne GPS) | ◆◆ | 1.5.x |
| Allan-Abweichung | ★★ | ◆◆ | 1.5.x |
| Verbund: Übersicht und Gegenmessung; Einstellungen teilen (experimentell) | ★★ | ◆◆ | 1.5.x |
| Einstellungen als Datei (TOML) | ★ | ◆ | 1.5.x |
| MQTT mit Home-Assistant-Discovery | ★★ | ◆◆ | nur auf Nachfrage |

## 1.6 und später

| Thema | Nutzen | Aufwand |
|---|---|---|
| GPS-Empfänger aus dem Dashboard einrichten (u-blox-Voreinstellungen, mit Sicherung und „zurück“) | ★★ | ◆◆◆ |
| „Von außen prüfen“-Knopf (gegen den Server-Test der Community) 🔒 | ★★★ | ◆ |
| Gemeinsame virtuelle IP für zwei Instanzen (keepalived/VRRP, Doku) | ★ | ◆ |
| Profi-PTP mit `ts2phc` (PPS direkt in i210/i226/TimeHAT), experimentell | ★★ | ◆◆◆ |
| Funkuhr-Empfänger (DCF77), nur bei Nachfrage | ★ | ◆◆ |

## Community-Dienste (eigenes Repository, freiwillig)

Gestaffelt nach Nutzen für alle – auch für Menschen ohne ntp-gui. **Erster eigener Dienst:**
Zeit-Check-Website und Server-Test (Selbsttest des eigenen Anschlusses) auf dem VPS des
Maintainers – Architektur, Aufwand, Kosten und Recht in
[version-1.5.md, Abschnitt 4.6](docs/konzept/version-1.5.md#46-erster-konkreter-schritt-zeit-check-website--server-test-auf-dem-vps-des-maintainers).

| Dienst | Nutzen | Aufwand |
|---|---|---|
| **Zeit-Check-Website:** Abweichung der Geräteuhr, gemessen von mehreren Standorten, ohne Tracking; Erklärseiten | ★★ | ◆ |
| **Öffentliche NTP/NTS-Server** der Community im NTP Pool | ★★★ | ◆ |
| **Server-Test** („SSL Labs für NTP“): Erreichbarkeit, Stratum, NTS, Zertifikat, Sicherheitsprobleme; „Von außen prüfen“ aus dem Dashboard | ★★★ | ◆◆ |
| **Hardware-Kompatibilitätsliste** aus geteilten Hardware-Checks (zuerst über GitHub-Issues, ohne eigenen Server) 🔒 | ★★★ | ◆ |
| **Start-Offsets für GPS-Empfänger** aus der Kompatibilitätsliste | ★★ | ◆ |
| **Statusseite** öffentlicher Zeitserver (PTB, Cloudflare, Netnod, Pool) | ★★ | ◆ |
| **Zeitwächter:** freiwilliges Monitoring mit Alarm 🔒 | ★★ | ◆◆ |
| **Schwarm:** GNSS-Störungen und falsche Zeitquellen gemeinsam erkennen 🔒 | ★★★ | ◆◆◆ |
