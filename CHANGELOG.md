# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [1.2.0] – 2026-11-01

### Hinzugefügt
- **Hardware-Check** (Seite „Hardware“, `GET /api/hardware`, `?refresh=1` prüft neu):
  erkennt GPS-Empfänger über USB-ID, gpsd und Anschlussart (USB-Modem, USB-Seriell,
  UART), den PPS-Weg (GPIO, DCD, keiner) samt live ankommender Impulse, PTP-fähige
  Netzwerkkarten, VM/Hypervisor, Docker Desktop/WSL, Container-Rechte und RTC. Eine
  Matrix sagt je Funktion „geht / geht mit Änderung / eingeschränkt / geht nicht“ – mit
  erreichbarer Genauigkeit und fertigem Ausschnitt für Compose-Datei, `.env` oder
  Boot-Konfiguration. Läuft im Hintergrund alle 5 Minuten; Ergebnisse auch als Hinweise
  und in `/metrics`.
- **`docker-compose.all-in-one.yml`**: eine Datei zum Kopieren. Aktiv ist, was jeder
  braucht; GPS, PPS, PTP, NTS-Server, Orphan-Verbund, Passwort, Bridge-Alternative und
  Hotplug (`/dev` + `device_cgroup_rules`, Major-Nummern für PPS/PTP aus `.env`) stehen
  als erklärte Blöcke zum Einkommentieren daneben.
- **NTS-Server hinter einem Reverse Proxy**: Zertifikate von Nginx Proxy Manager, Zoraxy,
  certbot & Co. direkt nutzbar (`/certs`, `/etc/letsencrypt`), `NTS_SERVER_NAME`
  (`ntsntpserver`) und `NTS_SERVER_PORT` (`ntsport`). Cert und Key werden geprüft (PEM,
  Größe, passendes Paar) und für chronyd kopiert; bei Erneuerung startet chronyd
  automatisch neu, ein unpassendes Paar ersetzt nie das letzte gültige. Anleitung für
  NPM, Zoraxy, Traefik, nginx und HAProxy im README.
- **NTS-Server-Status** im Dashboard: Name, Port, Aussteller, Restlaufzeit, selbst
  signiert, ob der Name im Zertifikat steht – mit Hinweisen, wenn etwas nicht passt.
- **Grandmaster-Ankündigung**: ntp-gui setzt `clockClass`, `clockAccuracy`, `timeSource`
  und UTC-Offset per `GRANDMASTER_SETTINGS_NP` laufend nach dem Zustand von chrony
  (`clockClass 6`/`timeSource GPS` erst mit stabilem GPS + PPS).
- **PTP-Profile** `default`, `aes67` und `gptp` (`PTP_PROFILE`) sowie
  `PTP_LOG_ANNOUNCE_INTERVAL`, `PTP_ANNOUNCE_RECEIPT_TIMEOUT` und
  `PTP_LOG_MIN_DELAY_REQ_INTERVAL`.
- **Orphan-Modus** für zwei Server im Verbund (`LOCAL_ORPHAN`).
- **Karte „Dienste“** in der Übersicht: Zustand, Neustarts und nächster Versuch je Dienst;
  Hinweis bei Ausfall; Prometheus-Metriken `ntpgui_service_up`,
  `ntpgui_service_restarts_total`, `ntpgui_hardware_capability`, `ntpgui_pps_live`,
  `ntpgui_nts_server_cert_days_left`.
- Erklärung (ⓘ) zu jedem neuen Wert; ein Test stellt sicher, dass kein angezeigter Wert
  ohne Erklärung bleibt.
- Integrationstest: NTS-Server mit selbst signiertem Zertifikat inkl. Zertifikatswechsel,
  Neustart eines abgestürzten gpsd (jetzt 68 Prüfungen; 221 Unittests).

### Geändert
- **Supervisor**: Fällt gpsd, ptp4l oder phc2sys aus, startet nur dieser Dienst neu
  (Pause 5 s, 15 s, 60 s, danach alle 5 min) – NTP läuft weiter. Nur ein Ausfall von
  chronyd oder dem Dashboard beendet den Container. Fehlende Geräte werden alle 30 s
  gesucht und automatisch übernommen. Zustand in `services.json`.
- **Achtung, kann bestehende Setups betreffen:** `NTS_SERVER_CERT`/`NTS_SERVER_KEY`
  müssen jetzt unter `/config`, `/certs` oder `/etc/letsencrypt` liegen (sonst gilt der
  Standard `/config/nts.crt`), weil die Dateien in ein für chronyd lesbares Verzeichnis
  kopiert werden. Zertifikate an anderen Orten bitte dorthin mounten.
- Die Kopien von Zertifikat und Schlüssel gehören `root:_chrony` mit `0640` – chronyd
  kann sie lesen, aber nicht verändern.
- `PHC2SYS_OPTIONS` ist standardmäßig leer und wird passend zur Rolle gewählt.
- Compose-Vorlagen verweisen auf die All-in-one-Datei und die Hardware-Seite;
  `docker-compose.pi-gps.yml` mit Healthcheck, PPS/GPIO-Variante und Kalibrierung über
  das Dashboard; `docker-compose.ptp.yml` und `docker-compose.gps.yml` mit Healthcheck.
- README: neue Abschnitte „Alles in einem“, „Hardware-Check“, „NTS hinter einem Reverse
  Proxy“, „Dienste und Neustarts“, PTP-Rollen und -Profile; bisher fehlende Variablen
  dokumentiert (u. a. `GPS_OPTIONS`, `GPS_PPS_POLL`, `GPS_PPS_OPTIONS`,
  `GPS_PPS_SHM_UNIT`, `PHC_REFCLOCK_OPTIONS`, `CHRONY_LOG`, `GPSD_HOST`,
  `CUSTOM_CHRONY_CONF`, `CUSTOM_PTP4L_CONF`, `MAXUPDATESKEW`).

### Behoben
- **PTP-Grandmaster verteilte nicht die Zeit von chrony/GPS**: phc2sys stellte im
  Master-Betrieb die falsche Uhr. Jetzt `phc2sys -a -rr` – chronyd regelt die
  Systemuhr, phc2sys überträgt sie mit korrektem UTC-Offset auf die Netzwerkkarte. Als
  Slave weiterhin `-a -r` mit chronyd `-x`.
- Ein abgestürzter optionaler Dienst (z. B. gpsd nach Abziehen des Empfängers) stoppte
  den ganzen Container samt NTP.
- README: Kalibrier-Endpunkt heißt `?window=` (`?seconds=` geht weiter), time-pi richtig
  beschrieben (PPS dort direkt in die i226 per `ts2phc`, das ntp-gui nicht unterstützt),
  „Dante“ präzisiert zu „AES67 (Dante nur im AES67-Modus)“.
- `docker-compose.pi-gps.yml` verwies zur Kalibrierung noch auf `chronyc sourcestats`
  statt auf den Assistenten im Dashboard.
- Dashboard zeigte als Version weiterhin 1.1.0.

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

[1.2.0]: https://github.com/ConGp20/ntp-gui/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ConGp20/ntp-gui/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ConGp20/ntp-gui/releases/tag/v1.0.0
