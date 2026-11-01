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

## 1.3 – Fehlersuche, erzwungene Zeitserver, Fundamente

| Thema | Nutzen | Aufwand |
|---|---|---|
| Diagnosepaket (ein Klick, mit Vorschau) und Log-Seite 🔒 | ★★★ | ◆ |
| Zentraler Datenschutzfilter für alles, was die Instanz verlässt 🔒 | ★★★ | ◆◆ |
| Zeitserver erzwingen: DNS-Umschreibung (AdGuard, Pi-hole, dnsmasq) und Firewall-Umleitung (OPNsense, MikroTik, OpenWrt, UniFi, nftables) samt Prüfung | ★★★ | ◆ |
| Passive Messung der Client-Uhren (Abweichung je Gerät aus der NTP-Anfrage) | ★★★ | ◆◆ |
| Automatische GPS-Kalibrierung (aus / vorschlagen / automatisch, behutsam, umkehrbar) | ★★ | ◆◆ |
| Ereignisprotokoll (Quellenwechsel, Fix verloren, Neustarts, Änderungen) | ★★ | ◆ |
| SQLite als Datenspeicher, versionierte Einstellungen mit Migration | ★★ | ◆◆ |
| Austauschbare Datenquellen mit Aufzeichnung/Wiedergabe (Entwicklung, Demo-Modus) | ★★ | ◆◆ |
| API-Schlüssel mit Rechten (nur lesen / verwalten), versionierte API `/api/v1` | ★★ | ◆ |

## 1.4 – nach den ersten Praxis-Logs

| Thema | Nutzen | Aufwand |
|---|---|---|
| Benachrichtigungen: Webhook, ntfy, Gotify, E-Mail, MQTT | ★★★ | ◆ |
| Home-Assistant-Anbindung (MQTT mit automatischer Erkennung) | ★★ | ◆ |
| Temperaturausgleich des Quarzes (chrony `tempcomp`, Werte gemessen und vorgeschlagen) | ★★★ | ◆◆ |
| Stabilität ohne Quelle (Allan-Abweichung, „wie lange hält die Uhr?“) | ★★ | ◆◆ |
| Verbund: mehrere Instanzen im Überblick, gegenseitige Prüfung, Einstellungen teilen | ★★ | ◆◆ |
| Uhr-Ansicht im Vollbild (Rack-Monitor, Tablet) | ★ | ◆ |
| Schaltsekunden-Übersicht | ★ | ◆ |

## Später

| Thema | Nutzen | Aufwand |
|---|---|---|
| GPS-Empfänger aus dem Dashboard einrichten (u-blox Timing-Modus, Systeme, PPS) | ★★ | ◆◆ |
| Störungen erkennen (Jamming/Spoofing) und GPS vorübergehend sperren | ★★★ | ◆◆ |
| Profi-PTP mit `ts2phc` (PPS direkt in i210/i226/TimeHAT) | ★★ | ◆◆◆ |
| Gemeinsame virtuelle IP für zwei Instanzen (keepalived/VRRP) | ★ | ◆◆ |
| Einstellungen als YAML (Konfiguration als Code) | ★ | ◆ |
| Mehrsprachigkeit (Englisch zuerst) | ★★ | ◆◆ |
| Funkuhr-Empfänger (DCF77) | ★ | ◆◆ |

## Community-Dienste (eigenes Repository, freiwillig)

Gestaffelt nach Nutzen für alle – auch für Menschen ohne ntp-gui.

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
