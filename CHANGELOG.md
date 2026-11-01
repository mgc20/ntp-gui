# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [1.3.0] – 2026-11-01

### Hinzugefügt
- **Seite „Diagnose“**: Container-Log mit Text- und Stufenfilter (`/api/logs`; der
  Supervisor schreibt dafür zusätzlich nach `/run/ntp-gui/ntp-gui.log`, rotiert ab 2 MB,
  abschaltbar mit `NTPGUI_LOGTEE=0`), Ereignisprotokoll und ein **Diagnosepaket**
  (`/api/diagnostics/preview`, `/api/diagnostics/bundle`) mit Vorschau und deutscher
  `MANIFEST.txt`. Das Paket wird nur heruntergeladen, nie hochgeladen.
- **Zentraler Datenschutzfilter** (`app/egress.py`) für alles, was die Instanz verlässt:
  keine Koordinaten, Höhe, Geschwindigkeit, Satellitenwinkel (Azimut/Elevation),
  Seriennummern (USB, DMI, `/dev/serial/by-id`), MAC-Adressen und PTP-Clock-IDs,
  öffentlichen IP-Adressen, eigenen Hostnamen, Domains und Zertifikatsnamen, Zeitzonennamen;
  private Adressen werden zu stabilen Pseudonymen (`client-07`). Laufzeiten zu Servern
  (Root/Peer delay, Fehlerschranken, RTT – auch in chronyc-Ausgaben und Aufzeichnungen) werden
  für jeden Zweck auf 10 ms gerundet; von Satelliten bleiben nur Summen je System (keine
  Satellitennummern). Zwei Schlussprüfungen – eine mit den Regeln des Filters, eine davon
  unabhängige auf den fertigen Bytes – laufen über jede Datei des Pakets und brechen den
  Export ab, wenn sie noch etwas finden; in Log und Aufzeichnung wird stattdessen nur die
  beanstandete Zeile entfernt.
- **Schutz vor DNS-Rebinding:** Ohne Passwort beantwortet das Dashboard nur Anfragen an
  IP-Adressen, `localhost`, den eigenen bzw. einteilige Hostnamen, lokale Endungen (`*.local`,
  `*.lan`, `*.home.arpa`, `*.internal` …), den NTS-Namen und `WEB_ALLOWED_HOSTS` (neu,
  kommagetrennt, `*.domain`, `*` schaltet ab); alles andere bekommt `403` mit Erklärung.
  `*.fritz.box` gilt bewusst nicht als lokal (`.box` ist eine öffentliche Endung). Mit
  Passwort oder API-Schlüssel gilt jeder Name, `/healthz` ist immer offen.
- **Ereignisprotokoll** (`/api/events`, 90 Tage): Neustarts und Ausfälle von Diensten,
  Neuladen, Zertifikate, GPS-Gerät weg/neu angesteckt (vom Supervisor), Wechsel der
  ausgewählten Quelle, GPS-Fix verloren/wieder da, PPS-Impulse ausgeblieben/wieder da,
  geänderte Einstellungen (nur Feldnamen), Kalibrierung, API-Schlüssel.
- **Zeitserver erzwingen** (Seite „Clients“, `/api/enforce/snippets`, `/api/enforce/check`):
  Anleitungen für DNS-Umschreibung (AdGuard Home, Pi-hole, dnsmasq, Unbound) und
  Firewall-Umleitung (OPNsense/pfSense, MikroTik, OpenWrt, nftables, UniFi) mit Ausnahme
  für ntp-gui selbst und Hairpin-Regel, eigene Namen per `ENFORCE_HOSTNAMES`. NTS-Server
  und `fritz.box` werden nie umgeschrieben. Die Prüfung (höchstens alle 30 s) erkennt
  wirksame Umschreibung, fehlende IPv6-Sperre und Schleifen.
- **Passive Messung der Client-Uhren** (`/api/clients/offsets`, `CLIENTMON`): Abweichung
  jeder Client-Uhr aus ihren NTP-Anfragen, ohne etwas an die Geräte zu senden; erkennt
  Clients, die ihre Zeit absichtlich verschleiern. Braucht `NET_RAW` und Host-Netzwerk.
- **Automatische GPS-Kalibrierung** (`GPS_AUTOCAL=off|suggest|auto`,
  `GPS_AUTOCAL_MAX_STEP_MS`, `GPS_AUTOCAL_MIN_HOURS`): höchstens ein kleiner Schritt je
  24 h, nur mit vertrauenswürdiger Netzreferenz, jede Änderung im Ereignisprotokoll und
  per Knopf umkehrbar (`/api/gps/autocal`, `POST /api/gps/autocal/rollback`). Die
  Automatik stellt nie weiter, solange nicht belegt ist, dass die letzte Änderung wirkt
  (Offset in der laufenden `chrony.conf` und erfolgreiches Neuladen); gemessen wird ab dem
  Zeitpunkt, an dem sie aktiv wurde.
- **API-Schlüssel** mit Recht „nur lesen“ oder „lesen und verwalten“
  (`Authorization: Bearer ntpg_…`, gespeichert wird nur ein SHA-256-Hash – PBKDF2 hätte bei
  144 Bit Zufall nichts gebracht, aber jede Anfrage mit erfundenem Schlüssel teuer gemacht;
  Schlüssel aus Vorabversionen werden beim nächsten Gebrauch umgestellt). Im
  Ereignisprotokoll steht nur die Kennung eines Schlüssels, nie sein Name. Passwort und Schlüssel
  lassen sich nur mit Benutzer/Passwort verwalten, nie mit einem Schlüssel.
- **Versionierte API `/api/v1`**; `GET /api/v1` beschreibt alle Endpunkte samt nötigem Recht.
- **Aufzeichnung und Wiedergabe** der Datenquellen (`/api/recording`, `NTPGUI_REPLAY`,
  `NTPGUI_REPLAY_SPEED`, `python3 app/providers.py replay-info`): alle Abfragen an chronyc,
  pmc, ethtool und gpsd laufen über eine Stelle (`app/providers.py`).
- Zufällige **Instanz-Kennung** (`/api/v1/instance`), jederzeit neu erzeugbar.
- Integrationstest: Log-Seite, Diagnosepaket ohne Standort und Kennungen, API-Schlüssel,
  Schutz vor DNS-Rebinding und `WEB_ALLOWED_HOSTS` (111 Prüfungen statt 68).

### Geändert
- Verlauf, Ereignisse, Client-Messwerte und API-Schlüssel liegen in SQLite (`ntp-gui.db`).
  Der Verlauf reicht jetzt **30 Tage** (`HISTORY_DAYS`), lange Zeiträume kommen aus einer
  5-Minuten-Vorverdichtung. Neue Punkte werden alle 5 Minuten geschrieben (schont
  SD-Karten). `HISTORY_SIZE` ist nur noch eine Obergrenze, wenn es gesetzt ist. Ein
  vorhandenes `history.json.gz` wird beim ersten Start übernommen und als `.migrated`
  aufbewahrt.
- Einstellungen tragen eine **Schema-Version** und werden beim Update einmalig migriert; was
  dabei geändert wurde, zeigt die Einstellungsseite oben an (`/api/settings/notes`). Auch
  Sicherungen älterer Versionen lassen sich importieren. Migration 1→2 entfernt gespeicherte
  NTS-Zertifikatspfade außerhalb von `/config`, `/certs` und `/etc/letsencrypt`.
- `/api/gps/calibration` ohne `window` wertet die letzten 24 h aus (`window=0`: alles) –
  über 30 Tage Verlauf würde die Berechnung sonst Sekunden dauern.
- Neue Navigationsseite „Diagnose“; die Einstellungsseite hat Karten für API-Schlüssel,
  Instanz-Kennung und Update-Hinweise.

### Behoben
- **Kopieren-Knöpfe** (Clients, PTP, Hardware, API-Schlüssel) funktionieren auch über
  einfaches `http://` im LAN: Ohne sichere Verbindung greift ein Ersatzweg; klappt auch der
  nicht, wird der Text markiert und ein Hinweis zeigt Strg+C.
- Hardware-Check: Ein USB-GPS an `ttyACM` (z. B. VK-162) wurde fälschlich als
  USB-Seriell-Adapter mit möglichem DCD-PPS eingestuft, wenn der Treiber-Link in `/sys`
  nicht lesbar war. `ttyACM`-Geräte kommen immer von `cdc_acm` und liefern kein PPS. Der
  GPIO-PPS-Vorschlag bei „geht nicht“ ist jetzt klar als Lösung mit anderer Hardware
  gekennzeichnet.

## [1.2.0] – 2026-11-01

### Achtung beim Update (Breaking Change)
- **NTS-Zertifikatspfade sind eingeschränkt:** `NTS_SERVER_CERT` und `NTS_SERVER_KEY`
  dürfen nur noch unter `/config`, `/certs` oder `/etc/letsencrypt` liegen (auch das Ziel
  eines Symlinks). Ein Pfad woanders (z. B. `/etc/ssl/…`) wird abgelehnt, es gilt der
  Standard `/config/nts.crt`/`/config/nts.key` – fehlen die Dateien dort, bleibt der
  NTS-Server nach dem Update aus (normales NTP läuft weiter). Grund: Die Dateien werden in
  ein für chronyd lesbares Verzeichnis kopiert; ein freier Pfad würde z. B. erlauben,
  `/etc/shadow` dorthin zu kopieren. Abhilfe: den Zertifikatsordner nach `/certs` (oder
  `/etc/letsencrypt`) mounten und die Pfade anpassen.
- `PHC2SYS_OPTIONS="-a -r -m"` (der alte Standard aus 1.1.0) wird als Grandmaster durch
  die automatische Wahl `-a -rr -m` ersetzt (Hinweis im Log) – die Variable kann entfallen.

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
  Neustart eines abgestürzten gpsd (jetzt 68 Prüfungen; 245 Unittests).

### Geändert
- **Supervisor**: Fällt gpsd, ptp4l oder phc2sys aus, startet nur dieser Dienst neu
  (Pause 5 s, 15 s, 60 s, danach alle 5 min) – NTP läuft weiter. Nur ein Ausfall von
  chronyd oder dem Dashboard beendet den Container. Fehlende Geräte werden alle 30 s
  gesucht und automatisch übernommen. Zustand in `services.json`.
- NTS-Zertifikatspfade nur noch unter `/config`, `/certs` oder `/etc/letsencrypt` –
  siehe „Achtung beim Update“.
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

#### Behoben nach dem Review vor dem Release
- **PTP-Grandmaster:** Nach jedem Neustart von ptp4l (Speichern, Hotplug, Absturz)
  kündigte er bis zu 5 Minuten `clockClass 248` an – die Daten werden jetzt sofort neu
  gesendet. Ein `PHC_REFCLOCK` zusammen mit `PTP_MODE=master` hätte chrony seine eigene
  Zeit zurückgeliefert (Zeitschleife); die Refclock-Zeile entfällt dann mit WARNUNG.
  Das Dashboard warnt, wenn ein Grandmaster mit Hardware-Zeitstempeln ohne phc2sys
  läuft; das Beispiel auf der PTP-Seite setzt `PHC2SYS_ENABLE` jetzt mit.
- **NTS-Zertifikatserneuerung** startet nur noch chronyd neu, nicht mehr gpsd, ptp4l
  und phc2sys.
- Das PTP-Profil (z. B. `gptp` → Layer 2) wird jetzt auch beim Rechte-Check (`NET_RAW`)
  und in der PTP-Statusanzeige berücksichtigt.
- Ungültige Expertenwerte (`PTP_UTC_OFFSET`, `PTP_HOLDOVER_SECONDS`,
  `PTP_TX_TIMESTAMP_TIMEOUT`, `PTP_UDS_ADDRESS`) fallen mit WARNUNG im Log auf den
  Standard zurück.
- Dashboard: keine doppelten NTS-Hinweise mehr, Grammatik „fehlen/fehlt“, PTP-Kachel
  „läuft nicht“ statt „aus“, fehlende (i)-Erklärungen in den Einstellungen, die
  Clients-Seite erfindet keine Server-IP mehr, „/dev vom Host eingehängt“ nur noch im
  Container.
- **Compose-Dateien:** Der Healthcheck liest `WEB_PORT` (wie im Dockerfile) – ein anderer
  Dashboard-Port macht den Container nicht mehr „unhealthy“. In
  `docker-compose.pi-gps.yml` erzeugte die PPS-Variante beim Einkommentieren einen
  doppelten `GPS_DEVICE`-Schlüssel. Die All-in-one-Datei lässt sich mechanisch
  einkommentieren (eingerückte `#` + zwei Leerzeichen); Kopfzeilen erfüllen das Muster
  nicht mehr.
- **Raspberry Pi:** Anleitung für den GPS-HAT korrigiert – beim Pi 3/4 liegt am Header
  sonst der Mini-UART `/dev/ttyS0` (dafür `dtoverlay=disable-bt` und
  `systemctl disable hciuart`), serielle Konsole abschalten, `/dev/serial0` empfohlen;
  beim Pi 5 ist es `/dev/ttyAMA0`.
- **README:** NPM-Zertifikatsordner per `openssl`-Schleife finden (die alte
  `grep`-Suche fand mit DNS-Challenge nichts), die zwei Namen bei NTS hinter einem Proxy
  (Zertifikat = Proxy-Name, `NTS_SERVER_NAME` = Host von ntp-gui) klar getrennt,
  Port-Veröffentlichung für Proxys in Docker, nginx-`map` mit `default`, Bridge-Modus
  verbirgt Client-IPs nur je nach Docker-Setup, `PHC_REFCLOCK` nur als Slave,
  Holdover (`clockClass 7`) und `timeSource NTP` beschrieben, `PTP_UTC_OFFSET`,
  `PTP_HOLDOVER_SECONDS`, `PTP_TX_TIMESTAMP_TIMEOUT` und `PTP_UDS_ADDRESS` dokumentiert.

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

[1.3.0]: https://github.com/ConGp20/ntp-gui/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ConGp20/ntp-gui/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ConGp20/ntp-gui/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ConGp20/ntp-gui/releases/tag/v1.0.0
