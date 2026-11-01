# Entscheidungen

Getroffene Entscheidungen zu den offenen Fragen aus den Konzeptdokumenten. Neue
Entscheidungen werden unten angehängt (kurz: Frage, Entscheidung, Begründung, Datum).
Format und Bewertung: siehe [entscheidungsrahmen.md](entscheidungsrahmen.md).

## 2026-11-01

| # | Frage | Entscheidung | Begründung |
|---|---|---|---|
| E1 | Basis-Image | **Umstieg auf Debian 13 „trixie“ als 1.3.1**, direkt nach 1.3.0 | bookworm hat seit 12.07.2026 nur noch LTS-Sicherheitsupdates; trixie bringt chrony 4.6, gpsd 3.25, linuxptp 4.2. Künftige Debian-Versionen zeitnah übernehmen. |
| E2 | Schaltsekunden unter trixie | **Direkt auf `leapseclist /usr/share/zoneinfo/leap-seconds.list`**, `LEAPSECTZ` wird automatisch migriert | trixie hat kein `right/UTC` mehr; ohne Umstellung hätte chrony still keine Schaltsekunden-Daten. Der Container-Test prüft das. |
| E3 | Umfang 1.4 | **Schlanke 1.4** (~6–8 Wochen), danach 1.4.x / 1.5 in kurzen Abständen | Häufige, kleine Releases sind für einen Maintainer besser beherrschbar. |
| E4 | Home Assistant | **Zuerst Dokumentation (REST-Sensor)**, MQTT erst auf Nachfrage | keine neue Abhängigkeit, nichts geht nach draußen |
| E5 | HTTPS fürs Dashboard | **Nur Reverse Proxy dokumentieren** (NPM, Zoraxy, Traefik, Caddy) | Eigenbau hätte Fallstricke (Handshake blockiert den Server, Zertifikatswechsel); Proxys sind meist schon vorhanden. |
| E6 | E-Mail-Benachrichtigung | **Über Apprise-API** (optionaler Zusatzcontainer), kein eigener SMTP-Kanal | deckt E-Mail, Telegram, Matrix, Gotify u. v. m. ab, ohne eigenen Code |
| E7 | Uhr-Vollbildansicht ohne Login | **Als Option, standardmäßig aus** | nützlich für Rack-Monitore; nur lesend, ohne Konfigurationsdaten |
| E8 | Bewertungsformel | **„OSS teilweise“ zählt +0,5** | spiegelt den geringeren, aber vorhandenen Nutzen von Wiederverwendung |
| E9 | Ausstiegsplan | **Jede Entscheidung für ein Fremdprojekt nennt in einer Zeile, was passiert, wenn es eingestellt wird** | Beispiel Watchtower (2025 archiviert) |
| E10 | Öffentliche Community-Dienste (Impressum, VPS-Kosten) | **Nicht grundsätzlich ausgeschlossen** – wird je Stufe entschieden | Bis dahin: Stufen ohne eigenen öffentlichen Server zuerst (Hardware-Liste über GitHub). |
| E11 | Sprache des Server-Tests | **Go mit bewährter NTS-Bibliothek** (gepinnt und mitgeliefert) | eigener NTS-Client wäre riskant und aufwendig |
| E12 | Schwarm Stufe A | **Ohne Laufzeitwerte** | mehrere Laufzeiten würden die Region verraten |
| E13 | Schwarm Stufe B (regional) | **Frühestens nach einem Jahr Stufe A neu bewerten** | Datenschutz und Datenqualität erst mit Erfahrung beurteilbar |
| E14 | Website-Hosting | **GitHub Pages für statische Teile**, eigener VPS nur für den Messpunkt | minimaler Betrieb, kein eigener Webserver für Inhalte |
