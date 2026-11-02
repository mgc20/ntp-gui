# Changelog

Alle nennenswerten Änderungen an ntp-gui. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Geändert
- **Diagnosepaket nimmt bis zu 12 MB Aufzeichnung mit** (bisher 4 MB). Eine einstündige
  Aufzeichnung wurde sonst auf die letzte halbe Stunde gekürzt. Auf dem Raspberry Pi dauert das
  Paket damit länger; das Dashboard bleibt währenddessen bedienbar.
- Die Verlaufs-Kennzahlen im Diagnosepaket enthalten die Temperatur und ein Stundenprofil
  Temperatur ↔ Frequenz (Mittel je Stunde) – Grundlage für den Temperaturausgleich.

## [1.4.0] – 2026-11-02

### Hinzugefügt
- **Benachrichtigungen:** Der Server meldet sich, wenn etwas passiert – über **ntfy**,
  **Gotify**, **Webhook** (JSON, optional mit HMAC-SHA256-Signatur im Header
  `X-NTPGUI-Signature`) oder **Apprise-API** (E-Mail, Telegram, Matrix, Signal und über 100
  weitere Dienste über einen Zusatz-Container). Neue Seite „Benachrichtigungen“: Kanäle
  anlegen, Filter nach Stufe und Art, „Testnachricht senden“, Zustellstand je Kanal. Ohne
  angelegten Kanal verlässt nichts den Server.
  - Gleiche Meldungen werden **entprellt** (Standard: höchstens alle 15 min je Art und
    Gerät/Dienst). Ist ein Problem vorbei, kommt „behoben“ mit Dauer („GPS-Fix wieder da –
    Dauer 40 min“); als „behoben“ zählen nur echte Gegenstücke. Ein zurückgehaltenes Problem,
    das am Ende der Sperrzeit noch besteht, wird nachgeholt. „Kritisch“ geht immer sofort
    hinaus – auch nach einer Warnung oder direkt nach einem „behoben“.
  - Klappt die Zustellung nicht, versucht der Server es nach 30 s, 2 min und 10 min erneut;
    danach wird die Nachricht verworfen und das steht im Ereignisprotokoll (neue Art
    „Benachrichtigung“). Je Kanal gilt ein Limit (Standard 30 je Stunde), jeder Kanal hat einen
    eigenen Thread, jede Zustellung eine Gesamtfrist von 10 s (Namensauflösung, Verbindung und
    Antwort zusammen). Nach einem Neustart werden schon zugestellte Meldungen nicht noch einmal
    verschickt.
  - `https://ntfy.sh/<thema>` wird erkannt; bei ntfy, Gotify und Apprise wird eine Adresse mit
    `?…` abgelehnt.
  - Neue Einstellung „Adresse des Dashboards (für Links)“ (`NOTIFY_DASHBOARD_URL`): Nachrichten
    verlinken dann direkt auf die passende Seite.
- **Eigene DNS-Server für ntp-gui:** Unter Einstellungen → „DNS für ntp-gui“ stellst du ein,
  worüber ntp-gui selbst Namen auflöst: System-DNS (Standard, wie bisher), eigene DNS-Server
  (klassisches DNS an feste IP-Adressen), DNS-over-TLS oder DNS-over-HTTPS (`DNS_MODE`,
  `DNS_SERVERS`, `DNS_DOT`, `DNS_DOH`, `DNS_PIN`, `DNS_FALLBACK`). So läuft chronyd nicht mehr in
  eine Schleife, wenn AdGuard Home oder Pi-hole Zeitserver-Namen wie pool.ntp.org auf ntp-gui
  umschreibt. Dafür startet ein kleiner Weiterleiter nur auf 127.0.0.1 im Container, und
  `/etc/resolv.conf` zeigt darauf. Das Original wird gesichert und beim Zurückschalten, beim
  Beenden und nach einem Absturz zurückgeschrieben.
  - DoT/DoH prüfen das Zertifikat des Servers. Optional trägst du feste Adressen ein
    (z. B. `dns.quad9.net=9.9.9.9`) – nötig, wenn der Container keinen anderen DNS hat
    (`dns: 127.0.0.1`); ein eigener Hinweis sagt das. Antwortet keiner deiner Server, fragt
    ntp-gui den ursprünglichen DNS des Containers (abschaltbar; Antworten daraus bleiben nur
    5 s im Cache) und meldet das als Ereignis der neuen Art „DNS“.
  - Ein einzelner langsamer Name schaltet einen Server nicht ab; erst drei
    Zeitüberschreitungen in Folge oder ein harter Fehler zählen als Ausfall. DoH hat eine harte
    Frist je Anfrage, auch gegen Server, die ihre Antwort Byte für Byte tröpfeln lassen.
  - Neuer Hinweis „Schleife durch DNS-Umschreibung“: erscheint, wenn eine eigene Zeitquelle
    per DNS auf ntp-gui selbst zeigt, und empfiehlt einen eigenen DNS-Modus.
  - Zeitserver erzwingen: Die Firewall-Anleitungen (UniFi, OPNsense/pfSense, MikroTik,
    OpenWrt, nftables) enthalten jetzt eine optionale „DNS-Umleitung per Firewall“ (Port 53
    auf AdGuard/Pi-hole), mit Pflicht-Ausnahme für ntp-gui.
- **Clients im Detail:**
  - **Verlauf je Client:** 7 Tage Abweichung, Poll-Feld, NTP-Version und tatsächlicher
    Abstand der Anfragen (höchstens alle 2 min ein Punkt). Erste und letzte Sichtung überstehen
    Neustarts.
  - **Detailseite je Gerät** (`#/clients/<adresse>`, ein Klick in der Client-Liste): Diagramm
    der Abweichung (1 h bis 7 Tage), Abstand der Anfragen und Poll, „messbar“ mit Begründung,
    VLAN, erste/letzte Sichtung, Name aus dem Reverse-DNS, MAC-Adresse (nur wenn das Gerät im
    selben Netz steht) und Hersteller, falls eine OUI-Liste vorhanden ist (`/config/oui.txt`).
  - **Vermutete Client-Software** (Windows/w32time, systemd-timesyncd, chrony/NTPsec/OpenNTPD,
    ntpd, SNTP/IoT, Apple) – begründet und klar als Vermutung gekennzeichnet.
  - **Eigene Namen und Notizen** für Geräte (nur Admins): bleiben lokal, erscheinen in Liste,
    Überblick und Ereignisanzeige. Gespeicherte Ereignisse nennen nur die Adresse; im
    Diagnosepaket und in Benachrichtigungen wird nie ein Name verschickt, Notizen werden nie
    exportiert.
  - **Netzüberblick** auf der Clients-Seite: Verteilung der Abweichungen (< 1 ms … > 1 s,
    falsche Uhr), die fünf Geräte mit der größten Abweichung, verstummte Geräte und Geräte, die
    öfter als alle 8 s fragen (kurze Schwälle wie ntpd-iburst zählen nicht).
  - **„Aktiv nachmessen“:** eine einzelne NTP-Anfrage an ein bekanntes Gerät im LAN zeigt bei
    Routern, NAS und manchen Kameras Abweichung und Laufzeit, auch wenn sie ihre Sendezeit
    verschleiern. Pro Gerät höchstens alle 30 s, insgesamt höchstens 10 pro Minute; nicht für
    link-lokale IPv6-Adressen.
  - **Alarm bei falsch gehender Client-Uhr:** neue Einstellung `CLIENTS_ALARM_MS` (Standard
    aus). Gemeldet wird nach zwei Messungen in Folge über der Schwelle („Uhr von … weicht um …
    ab“, Art Clients), „wieder im Rahmen“ erst unter der halben Schwelle.
  - Neue Einstellung `CLIENTS_RDNS` (Standard **aus**): Reverse-DNS nur für private Adressen,
    nur beim Öffnen der Detailseite, nie über DoT/DoH und nie, wenn ein beteiligter DNS-Server
    öffentlich ist.
- **Neue Seite „Uhrqualität“** (Navigation nach PTP):
  - **Temperatur wird aufgezeichnet** (nur messen, noch kein Temperaturausgleich): Thermalzonen
    (Raspberry Pi `cpu-thermal`), Sensorchips am PC (`k10temp`, `coretemp`, `x86_pkg_temp`) und
    DS18B20 am 1-Wire-Bus werden selbst gefunden. Streudiagramm Temperatur ↔ Frequenz,
    Temperatur- und Frequenzverlauf, Spanne, Messdauer und Zusammenhang (r). Nach 1–3 Tagen mit
    Tag-/Nacht-Wechsel siehst du, ob sich ein Temperaturausgleich lohnt – den Vorschlag dafür
    bringt 1.5. Neue Einstellung **Temperatursensor** (`TEMP_SENSOR`, Standard `auto`, `off` =
    aus); der Hardware-Check listet alle gefundenen Sensoren; ein Sensor ohne plausiblen Wert
    (z. B. DS18B20 auf 85 °C) wird als „liefert keinen Wert“ gemeldet.
  - **Schaltsekunden-Übersicht:** TAI−UTC, letzte Schaltsekunde, Ablaufdatum der
    `leap-seconds.list` mit verbleibenden Tagen, SHA-1-Prüfsumme und Leap-Status von chrony –
    immer für die Datei, die chrony wirklich liest. Läuft die Liste in weniger als 60 Tagen ab
    (oder ist sie abgelaufen oder verändert), erscheint der Hinweis „Image zu alt – Update
    einspielen“ und ein Ereignis „Schaltsekunde“. ntp-gui lädt die Liste bewusst nicht selbst
    aus dem Internet.
- **Vollbild-Uhr unter `/clock`** für Wandmonitor und Tablet: große Ortszeit und UTC, Datum,
  Kalenderwoche und ein Statusband (Ampel, Genauigkeit, Art der Quelle). Die Anzeige wird wie
  bei NTP mit vier Zeitstempeln an die Serveruhr angeglichen (fünf Messungen, kürzeste Laufzeit
  gewinnt) – die Uhr des Tablets ist egal. Hell, Dunkel und Rotlicht, Wake Lock (wo der Browser
  es erlaubt), Taste F für Vollbild, graue Ampel nach 10 s ohne Verbindung. Erreichbar über das
  neue Uhr-Symbol oben rechts. Neue Einstellung **Vollbild-Uhr ohne Anmeldung**
  (`CLOCK_PUBLIC`, Standard aus): nur `/clock` und `/api/v1/time` ohne Passwort – mit Uhrzeit,
  Ampel, Genauigkeit und Art der Quelle, ohne Namen, Adressen oder Einstellungen.
- **Update-Hinweis (opt-in, Standard aus):** Einmal am Tag zu einer zufälligen Uhrzeit fragt
  ntp-gui bei GitHub nach der neuesten Version (`releases/latest`) und vergleicht sie lokal.
  Ist eine neuere da, erscheinen ein Banner und in der Übersicht ein Hinweis mit Release-Titel,
  Link zu den Release-Notizen und der Markierung „Achtung beim Update“, wenn der Release-Text
  „BREAKING“ oder „Achtung“ enthält. Kein Download, kein automatisches Update; für
  Automatisierung Diun oder What's up Docker. Einschalten unter Einstellungen → Dashboard →
  „Update-Hinweis“ oder `UPDATE_CHECK=true`. Ehrlich gesagt: GitHub sieht dann einmal am Tag
  deine öffentliche IP-Adresse (grob ortbar) und dass dort vermutlich ntp-gui läuft.
- **Grafana-Dashboard** `docs/grafana/ntp-gui.json` und **Prometheus-Alarmregeln**
  `docs/prometheus/alerts.yml` (nicht synchron, Abweichung zu groß, keine Quelle, GPS ohne
  Fix, PPS weg, Dienst gestört, NTS-Zertifikat und Schaltsekunden-Liste laufen ab, neue
  Version). Ein Test stellt sicher, dass jede verwendete Metrik in `/metrics` existiert.
- **Anleitungen für Integrationen** unter `docs/integrationen/`: Home Assistant, Homepage und
  Glance, Uptime Kuma, Grafana/Prometheus.
- **Übersicht:** Die Kachel „Systemuhr“ zeigt Temperatur (wenn ein Sensor aufzeichnet) und
  wie lange die Schaltsekunden-Liste noch gilt; die Kachel „Dienste“ zeigt den DNS-Weiterleiter,
  den DNS-Modus und den Zustand der Benachrichtigungen.
- **Neue Metriken:** `ntpgui_max_error_seconds`, `ntpgui_sources`, `ntpgui_sources_usable`,
  `ntpgui_info{version}`, `ntpgui_service_enabled`, `ntpgui_temperature_celsius`,
  `ntpgui_leapseconds_list_days_left`, `ntpgui_tai_utc_offset_seconds`; mit Update-Hinweis
  `ntpgui_update_available` und `ntpgui_update_check_last_success_timestamp_seconds`.
- **Neue API-Endpunkte** (alle auch unter `/api/v1`, beschrieben in `GET /api/v1`):
  `/notify/status` (Leserecht, nur Kennung, Art und Zustellstand), `/notify`,
  `/notify/channels`, `/notify/channels/delete`, `/notify/test` (Verwaltungsrecht), `/dns`,
  `/clients/overview`, `/clients/detail?ip=…`, `/clients/meta` und `/clients/probe`
  (Verwaltungsrecht), `/temperature`, `/leap`, `/time`, `/update`. `/api/v1/status` hat neu
  `dns`, `leap`, `notify` und `update`, `/clients/offsets` liefert zusätzlich `names`,
  `/events` zusätzlich `display_title`.

### Geändert
- Alarm `NtpGuiServiceDown` und Grafana-Kachel „Dienste gestört“ zählen nur Dienste, die laut
  Einstellungen laufen sollen (`ntpgui_service_enabled`) – absichtlich gestoppte Dienste lösen
  keinen Alarm aus.
- Das Update-Banner liegt nicht in der klebenden Kopfzeile und ist auf dem Handy kompakt.
- Im Diagramm-Kopf steht bei Zeiträumen über einem Tag auch das Datum („Verlauf ab …“).

### Behoben
- **Hardware-Check schlug beim VK-162 & Co. weiter „/dev/pps0 einbinden“ vor.** gpsd hängt beim
  Öffnen selbst eine PPS-Leitungsdisziplin an `/dev/ttyACM0` (`/dev/pps0`, Name „acm0“); über einen
  USB-Empfänger kommt dort aber nie ein Impuls. Der Empfänger bleibt jetzt „kein PPS“, der Check
  erklärt, woher `/dev/pps0` stammt, und rät nicht mehr zum Einbinden. Allgemein: Ein PPS-Gerät,
  das am Host noch nie einen Impuls gezählt hat, wird nicht mehr zum Einbinden vorgeschlagen.
- Hardware-Check auf dem Pi: Neben einem erkannten USB-Empfänger erscheint die leere Mini-UART
  `ttyS0` nicht mehr als zweite „Empfänger“-Karte mit „PPS über GPIO möglich“.
- **Container konnte sich beim Speichern von Einstellungen beenden** (auch in 1.3.x): Kam eine
  Änderung genau, während die Zeitdienste neu starteten, traf das Signal an den Supervisor die
  bash mitten in einer Befehlsersetzung („trap: unexpected EOF while looking for matching `)'“) –
  der Supervisor und damit der Container endeten. Das Dashboard bittet jetzt per Datei
  (`/run/ntp-gui/reload.request`) um das Neuladen statt per SIGHUP. Im Belastungstest (150
  schnelle Wechsel) bleibt der Container stabil; vorher endete er nach 21 bzw. 48 Wechseln.
- Ein frisch gestarteter Dienst galt in den ersten Millisekunden als „beendet“ (der Prozess trug
  noch den Namen der Shell); der Supervisor wartet jetzt kurz auf den Start.
- Sperrzeiten (Benachrichtigungen, Prüfung „Zeitserver erzwingen“, Anmelde-Cache) laufen auf der
  monotonen Uhr: Stellt chrony die Systemuhr (Pi ohne Echtzeituhr), verlängert das keine Sperre
  mehr. Mehrere Zeitvergleiche gingen in der ersten Stunde nach dem Systemstart falsch
  (Startwert 0 statt „noch nie“) – u. a. blieb das Benachrichtigungs-Ereignis „gedrosselt“ aus.
- Eigener Rechnername: Der vollständige Name (Rückwärts-DNS) wird einmal im Hintergrund
  ermittelt und gemerkt, statt bei jeder Anfrage mit fremdem Host-Kopf – ein langsamer Resolver
  hielt sonst jedes Mal einen Anfrage-Thread fest.
- DNS-Weiterleiter: Die Statusdatei konnte bei gleichzeitigem Schreiben halb geschrieben gelesen
  werden (Dashboard zeigte den Weiterleiter dann als „gestoppt“); die Meldung bei belegtem Port
  nennt jetzt den richtigen Port.

### Sicherheit
- **Datenschutz bei Benachrichtigungen:** Jede Nachricht läuft durch den Datenschutzfilter
  (neuer Zweck `notify` mit eigener Feldliste). Hinaus gehen nur Titel, Text, Stufe, Art und
  Zeit – keine Koordinaten (auch nicht mit Nullen am Ende wie „52.5200, 13.4050“), keine
  öffentlichen IP-Adressen, keine eigenen Hostnamen, keine Ereignisdaten, keine Client-Namen.
  Kann die Liste eigener Namen nicht ermittelt werden, wird nicht gesendet. Weiterleitungen
  werden nie befolgt, Proxys aus der Umgebung nicht benutzt, Antworten höchstens 64 KiB.
- Benachrichtigungs-Tokens werden nur als „gesetzt“ angezeigt, stehen nie im Ereignisprotokoll
  oder Diagnosepaket und gehen nie an ein geändertes Ziel (Art, Host, Port oder Schema
  geändert ⇒ Token neu eingeben). Über `http://` nur an Adressen im eigenen Netz. Adressen mit
  Pfad (Webhook-IDs) zeigen Dashboard und API nur gekürzt.
- Update-Hinweis: Die Anfrage an GitHub ist fest verdrahtet (eigener Filterzweck
  `update_check`): User-Agent nur „ntp-gui“, ohne Version und Kennung, keine Daten der Instanz,
  keine Weiterleitungen, Gesamtfrist 20 s, Antwort höchstens 512 KiB. Ausgeschaltet gibt es
  keinerlei Netzzugriff.
- DNS für ntp-gui: Loopback-Adressen auf Port 53 (auch `::ffff:127.0.0.1`) sind als
  DNS-Server abgelehnt; API-Schlüssel mit Leserecht sehen DoH-Adressen nur gekürzt (sie können
  eine Konto-Kennung enthalten, z. B. bei NextDNS). Status, Ereignisse und Diagnosepaket nennen
  nur den Servernamen.
- Clients: MAC-Adressen verlassen die Instanz nie; Namen und Notizen lehnen unsichtbare und
  Bidi-Steuerzeichen ab; „private Adresse“ heißt genau RFC 1918, CGNAT, Link-lokal, ULA,
  Loopback (6to4, Teredo, NAT64 zählen nicht). Der Client-Verlauf ist auch insgesamt begrenzt
  (höchstens 2 Mio. Messpunkte), wechselnde Absenderadressen können `/data` nicht füllen.
- Vollbild-Uhr ohne Anmeldung: Anonyme Anfragen an `/clock` und `/api/v1/time` unterliegen dem
  Schutz vor DNS-Rebinding; `/api/v1/time` fragt chrony höchstens einmal pro Sekunde ab.
- Diagnosepaket: Seriennummern von DS18B20-Fühlern werden entfernt.
- **Lieferkette:** Jeder Release bringt je Architektur (amd64, arm64) eine SBOM (SPDX) und einen
  Schwachstellen-Bericht (Grype) mit, beide aus dem veröffentlichten Digest; der Release bricht
  bei einer kritischen Lücke mit verfügbarer Korrektur ab. Herkunftsnachweis (SLSA Build
  Provenance) am Image, prüfbar mit `gh attestation verify`. Alle GitHub Actions per
  Commit-SHA festgenagelt, OIDC-Token nur im eigenen Job, Release-Builds ohne Cache,
  Basis-Image per Digest festgenagelt; Dependabot schlägt Updates für Actions und Basis-Image
  vor. Image-Tags werden erst nach Scan und Nachweis gesetzt.
- Integrations-Doku: Hinweis, dass der API-Schlüssel über HTTP im Klartext reist – HTTPS über
  einen Reverse-Proxy oder ein vertrauenswürdiges Netz nutzen, je Integration ein eigener
  Lese-Schlüssel.

## [1.3.2] – 2026-11-02

### Geändert
- **Übersicht neu als „Single Pane of Glass“:** Statusband mit Gesamturteil und vier
  Kennzahlen samt Verlaufslinie; Hinweise einzeilig (Details aufklappbar) und dem passenden
  Bereich zugeordnet, der ihre Farbe übernimmt; Kacheln für Systemuhr, Zeitquellen, GPS, PTP,
  Clients, Dienste und die letzten Ereignisse.
- **Klarere Diagramme** auf allen Seiten: Kopfzeile mit jetzt/min/max/Mittel, einzelne
  Ausreißer (z. B. beim Start) werden ausgeblendet und markiert statt die Skala zu sprengen,
  Lücken sichtbar, Fadenkreuz mit Tooltip (Maus, Touch, Tastatur), Zeitachse in Ortszeit, eine
  Einheit je Achse, Zahlen einheitlich mit Dezimalkomma; bessere Kontraste und Texte für
  Bildschirmleser.
- **GPS-Fix-Ereignisse erst nach 60 s:** Bei schwachem Empfang kam und ging der Fix im
  Minutentakt und füllte das Protokoll mit „verloren/wieder da“-Paaren.
- **Selbsttest „Zeitserver erzwingen“** prüft DNS-Umschreibung (per Name) und
  Firewall-Umleitung (per IP-Adresse, `216.239.35.0`) getrennt – per Name greift schon der DNS.
  Dazu ein Hinweis, wie man das Hairpin-Problem erkennt.
- **Diagnosepaket mit Aufzeichnung deutlich schneller:** Filter und Schlussprüfungen merken
  sich gleiche Zeilen, Vorschau und Paket entstehen in einem Durchgang. Mit einer echten
  10-Minuten-Aufzeichnung (2347 Einträge, 1,5 MB) brauchten Vorschau und Download bisher
  zusammen 78 s (33 s + 45 s), jetzt 9 s (gemessen auf x86; auf einem Raspberry Pi entsprechend
  länger). Das Ergebnis ist byteweise dasselbe wie vorher.
- **Das Dashboard bleibt währenddessen bedienbar**, auch in anderen Tabs: Gefiltert wird in
  einem eigenen Prozess mit niedriger Priorität (`nice 10`), nicht mehr im Dashboard-Prozess.
- **Download nach der Vorschau sofort und identisch:** Steht eine Vorschau auf der Seite
  (gleiche Schalter, höchstens 10 Minuten alt, Aufzeichnung unverändert), liefert
  „Herunterladen“ genau dieses Paket, ohne neu zu bauen. Dateiname, Ordner und MANIFEST tragen
  den Zeitpunkt des Pakets.
- Mehrfach geklickt oder Seite neu geladen: Wartende Anfragen bekommen das Ergebnis des gerade
  laufenden Baus, statt jede für sich neu zu bauen.

### Behoben
- **Clients:** „Zuletzt“ und „Anfragen“ zeigten bei manchen Geräten „–“. chrony leert seine
  Client-Liste bei jedem Neustart (etwa nach dem Speichern von Einstellungen); ntp-gui nimmt
  dann die Werte der eigenen Messung (mit * markiert).
- Der Download lieferte nach einer fehlgeschlagenen Vorschau oder nach einer neuen Aufzeichnung
  ein älteres Paket. Er nimmt jetzt nur die Vorschau, die gerade angezeigt wird; nach dem
  Umschalten von „Client-Liste“ oder „Aufzeichnung einschließen“ verschwindet die alte Vorschau.
- Wird der Diagnose-Prozess beendet (z. B. vom OOM-Killer), nennt die Meldung das Signal
  („beendet durch SIGKILL (9) – vermutlich zu wenig Arbeitsspeicher“) und steht auch im
  Container-Log.
- Zwischenspeicher der Prüfungen sind nach Speicher begrenzt und werden nach jedem Paket
  geleert – kein langsam wachsender Speicherverbrauch im Dashboard-Prozess.
- Hinweis während des Bauens: Mit Aufzeichnung dauert es auf einem Raspberry Pi „eine bis
  mehrere Minuten“ (bisher „etwa eine Minute“).

## [1.3.1] – 2026-11-01

### Geändert
- **Basis-Image Debian 13 „trixie“** (`debian:trixie-slim`) statt bookworm: chrony 4.6.1,
  gpsd 3.25, linuxptp 4.2, Python 3.13. bookworm bekommt seit 07/2026 nur noch LTS-Updates.
- **Schaltsekunden über `leapseclist /usr/share/zoneinfo/leap-seconds.list`** (neue
  Einstellung `LEAPSECLIST`); trixie hat keine Zone `right/UTC` mehr. Ein gespeichertes
  `LEAPSECTZ=right/UTC` wird beim ersten Start automatisch entfernt (Einstellungs-Schema 3,
  Hinweiskarte auf der Einstellungsseite). `LEAPSECTZ` bleibt nur für eigene Images mit
  `right/`-Zonen; fehlt die Zone, nimmt ntp-gui die Liste.
- `ptp4l.conf` schreibt `clientOnly`/`serverOnly` statt `slaveOnly`/`masterOnly`. linuxptp 4.2
  meldete die alten Namen bei jedem Start als veraltet im PTP-Log.

### Behoben
- **Diagnosepaket mit Aufzeichnung** brach mit „latenz_gerundet“ ab, obwohl richtig gefiltert
  war: Die Schlussprüfung las die JSON-Zeilen der Aufzeichnung als Rohtext, so stand z. B.
  „Precision (0.000000030 seconds)“ neben „Root delay“. Sie prüft JSON-Zeilen jetzt wie der
  Filter.
- **Datenschutz:** chrony-RefIDs von IPv6-Adressen (ein Hash der Adresse, z. B.
  `Local address … (E41BC59B)` in `ntpdata`) blieben stehen, wenn sie zufällig im
  Multicast-Bereich lagen. Unbedenklich sind jetzt nur Namen (GPS, PPS …), Loopback und 0.0.0.0.
- „timezone to …“ in chrony-Logs wurde fälschlich als Zeitzone ersetzt.
- Ohne `NTPGUI_VERSION` meldeten Dashboard, `/api/status` und Diagnosepaket noch Version
  1.3.0; das Startereignis hatte keine Version.

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

[1.4.0]: https://github.com/ConGp20/ntp-gui/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/ConGp20/ntp-gui/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/ConGp20/ntp-gui/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/ConGp20/ntp-gui/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ConGp20/ntp-gui/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ConGp20/ntp-gui/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ConGp20/ntp-gui/releases/tag/v1.0.0
