# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [1.1.0] – 2026-11-01

### Hinzugefügt
- **Einstellungen im Dashboard**: Zeitquellen (mit Vorlagen für PTB, Cloudflare,
  Netnod, pool.ntp.org), Zugriff aus dem LAN, NTS, GPS, PTP und das Dashboard selbst.
  Reihenfolge: Dashboard > Umgebungsvariable > Standard; jedes Feld zeigt seine Herkunft
  und lässt sich zurücksetzen. Speichern startet die Zeitdienste per SIGHUP neu, ohne
  den Container neu zu erstellen. Export/Import als JSON, Sperre mit `WEB_READONLY`.
- Dashboard-Passwort im GUI setzen (PBKDF2-Hash in `settings.json`).
- **NTS**: je Quelle zuschaltbar (`NTP_NTS_SERVERS`), Anzeige von Authentifizierung,
  Cookies und Schlüsselaustausch, `nocerttimecheck` für Geräte ohne Echtzeituhr,
  optional eigener NTS-Server (`NTS_SERVER`).
- **GPS-Kalibrierassistent**: misst die Verspätung des USB-Empfängers gegen die genutzten
  Netzwerkquellen und übernimmt Offset, Delay und Rolle (`GPS_SELECT`) per Klick.
- Neue Oberfläche mit sieben Seiten (Übersicht, Zeitquellen, GPS, PTP, Clients,
  Einstellungen, Hilfe), ⓘ-Erklärung zu jedem Wert, Hinweis-Kasten („Was gerade los ist“)
  mit konkreten Handlungsempfehlungen, Glossar und Entscheidungshilfe.
- Zeitquellen mit Auswahlzustand **und Grund** (`chronyc selectdata`), NTP-Details
  (`ntpdata`), Offset-Verlauf je Quelle.
- GPS: Himmelskarte, Signalstärke je Satellit, GNSS-Systeme, DOP-Werte, Satelliten-Verlauf.
- PTP: Voraussetzungs-Check (Host-Netzwerk, Interface, Hardware-Zeitstempel, PTP-Uhr),
  Netzwerkkarten-Übersicht per `ethtool -T`, Kennzahlen und Zustandswechsel aus dem
  ptp4l-Log, weitere Optionen (Delay-Mechanismus, Clock Class, Sync-Intervall).
- Weitere Optionen: `NTP_MINSOURCES`, `NTP_RATELIMIT`, `LEAPSECTZ`.
- Clients: Einrichtungs-Snippets für DHCP-Server und Betriebssysteme.
- Verlauf über 24 h (`HISTORY_SIZE` 8640), wird stündlich und beim Stoppen gesichert.
- Unittests für Einstellungen, Konfigurationserzeugung (inkl. `chronyd -p`),
  Kalibrierung, Hinweise und neue Parser; Integrationstest für Speichern, Neustart,
  Persistenz, CSRF-Schutz und Readonly.
- `docker-compose.pi-gps.yml`: Vorlage für einen Raspberry Pi mit USB-GPS
  (Host-Netzwerk, PTB als Rückfallebene, Vorbereitungen im Kopfkommentar).
- Grafiken im README: Banner, Architektur, DHCP-Ablauf und Genauigkeitsvergleich,
  jeweils in heller und dunkler Variante (`docs/graphics/`, erzeugt von
  `docs/graphics/make_graphics.py`).
- Dieses Changelog.

### Geändert
- chrony behält Messwerte über Neustarts (`dumpdir`, `chronyd -r`).
- Container-Image enthält `ethtool`; Standardwerte stehen nur noch im Einstellungsschema.

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

[1.1.0]: https://github.com/ConGp20/ntp-gui/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ConGp20/ntp-gui/releases/tag/v1.0.0
