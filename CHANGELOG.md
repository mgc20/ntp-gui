# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Hinzugefügt
- `docker-compose.pi-gps.yml`: Vorlage für einen Raspberry Pi mit USB-GPS
  (Host-Netzwerk, PTB als Rückfallebene, Vorbereitungen im Kopfkommentar).
- Grafiken im README: Banner, Architektur, DHCP-Ablauf und Genauigkeitsvergleich,
  jeweils in heller und dunkler Variante (`docs/graphics/`, erzeugt von
  `docs/graphics/make_graphics.py`).
- Dieses Changelog.

## [1.0.0] – 2026-11-01

Erste Veröffentlichung.

### Hinzugefügt
- NTP-Server mit chronyd, konfiguriert über Umgebungsvariablen oder eine eigene
  `chrony.conf` unter `/config`.
- Web-Dashboard ohne externe Abhängigkeiten: Status, Offset-Verlauf, Zeitquellen,
  NTP-Clients, GPS-Fix, PTP-Zustand und aktive Konfiguration, hell und dunkel.
- GPS als Referenzuhr über gpsd (z. B. VK-162 per USB), optional mit PPS.
- PTP (IEEE 1588) mit ptp4l und phc2sys, als Master, Slave oder PTP→NTP-Brücke.
- JSON-API, Prometheus-Endpunkt `/metrics` und `/healthz` für den Healthcheck.
- Optionale HTTP-Basic-Auth für das Dashboard.
- Supervisor, der jeden Dienst überwacht und den Container bei einem Ausfall
  beendet, damit die Restart-Policy greift.
- Automatische Erkennung von fehlendem `CAP_SYS_TIME` (chronyd läuft dann mit `-x`).
- Compose-Beispiele für Standard-, GPS- und PTP-Betrieb.
- CI mit Unittests und Integrationstest gegen das gebaute Image; Release-Workflow,
  der das Image für amd64 und arm64 nach ghcr.io veröffentlicht.

[Unveröffentlicht]: https://github.com/ConGp20/ntp-gui/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ConGp20/ntp-gui/releases/tag/v1.0.0
