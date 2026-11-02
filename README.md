<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/graphics/banner-dark.svg">
  <img alt="ntp-gui – Zeitserver-Appliance für das LAN" src="docs/graphics/banner-light.svg">
</picture>
</p>

<p align="center">
  <a href="https://github.com/ConGp20/ntp-gui/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ConGp20/ntp-gui/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/ConGp20/ntp-gui/releases/latest"><img alt="Release" src="https://img.shields.io/badge/release-v1.4.0-0969da"></a>
  <img alt="Plattformen" src="https://img.shields.io/badge/platform-amd64%20%7C%20arm64-1a7f37">
  <img alt="Image" src="https://img.shields.io/badge/image-ghcr.io-8250df">
  <a href="LICENSE"><img alt="Lizenz: MIT" src="https://img.shields.io/badge/license-MIT-59636e"></a>
</p>

<p align="center">
  <a href="#schnellstart">Schnellstart</a> ·
  <a href="#alles-in-einem">Alles in einem</a> ·
  <a href="#hardware-check">Hardware-Check</a> ·
  <a href="#per-dhcp-verteilen-option-42">DHCP</a> ·
  <a href="#zeitserver-erzwingen">Erzwingen</a> ·
  <a href="#dns-für-ntp-gui-gegen-schleifen-durch-dns-umschreibung">DNS</a> ·
  <a href="#was-ist-möglich">Was ist möglich?</a> ·
  <a href="#nts--abgesicherte-zeit">NTS</a> ·
  <a href="#stratum-1-mit-gps">GPS</a> ·
  <a href="#ptp">PTP</a> ·
  <a href="#uhrqualität-temperatur-schaltsekunden-vollbild-uhr">Uhrqualität</a> ·
  <a href="#benachrichtigungen">Benachrichtigungen</a> ·
  <a href="#diagnose--fehlersuche">Diagnose</a> ·
  <a href="#konfiguration">Konfiguration</a> ·
  <a href="#api--automatisierung">API</a> ·
  <a href="ROADMAP.md">Roadmap</a> ·
  <a href="CONTRIBUTING.md">Mitmachen</a>
</p>

Ein Container, der **NTP (chrony)**, optional einen **GPS-Empfänger** und **PTP (linuxptp)**
zusammenbringt und alles in einem Web-Dashboard sichtbar macht. Gedacht als kleine
Zeitserver-Appliance für das eigene Netz: in einer VM, auf einem Mini-PC oder einem
Raspberry Pi starten, die Adresse per **DHCP Option 42** verteilen – fertig.

- **Ein Container, alles drin** – chronyd, gpsd, ptp4l/phc2sys und das Dashboard, überwacht von einem Supervisor
- **Stratum 1 ohne Internet** – mit einem USB-GPS wie dem VK-162 für ~15 €, auf Wunsch mit PPS
- **Alles im Dashboard einstellbar** – Zeitquellen, NTS, GPS, PTP, Zugriff; Umgebungsvariablen dienen nur noch als Startwerte
- **Erklärt sich selbst** – zu jedem Wert ein ⓘ mit Erklärung, ein Hinweis-Kasten sagt, was gerade los ist und was zu tun ist
- **GPS-Kalibrierassistent** – misst die USB-Verspätung gegen die Netzwerkquellen und übernimmt Offset und Delay per Klick – auf Wunsch auch automatisch, behutsam und umkehrbar
- **NTS** – kryptografisch abgesicherte Zeit von PTB, Cloudflare, Netnod & Co., optional auch als NTS-Server – auch hinter einem Reverse Proxy, mit dessen Let's-Encrypt-Zertifikat
- **Hardware-Check** – erkennt GPS-Empfänger, PPS, PTP-Netzwerkkarten, VM und Container-Rechte und sagt, was geht und welche Zeile in der Compose-Datei fehlt
- **Zeitserver erzwingen** – fertige Anleitungen für AdGuard, Pi-hole, dnsmasq, Unbound, OPNsense, MikroTik, OpenWrt, nftables und UniFi, damit auch Geräte mit fest eingebautem Zeitserver bei dir landen – samt Prüfung per Klick
- **Wie genau gehen meine Clients?** – misst passiv aus den NTP-Anfragen, wie weit die Uhr jedes Geräts im LAN danebenliegt – mit 7-Tage-Verlauf und Detailseite je Gerät, Netzüberblick und Alarm bei falsch gehender Uhr
- **Benachrichtigungen** – per ntfy, Gotify, Webhook oder Apprise (E-Mail, Telegram, Matrix …), entprellt, mit „behoben“-Meldung und durch den Datenschutzfilter
- **Uhrqualität** – Temperatur gegen Frequenz, Ablauf der Schaltsekunden-Liste und eine Vollbild-Uhr unter `/clock` für Wandmonitor und Tablet
- **Eigener DNS für ntp-gui** – DNS-over-TLS/-HTTPS oder feste Server, damit eine DNS-Umschreibung im LAN keine Schleife baut
- **Diagnose ohne Datenleck** – Log-Seite, Ereignisprotokoll und ein Diagnosepaket mit Vorschau; ein zentraler Datenschutzfilter sorgt dafür, dass sich aus dem Paket kein Standort ablesen lässt. Hochgeladen wird nichts
- **Fällt nicht um** – stirbt gpsd oder ptp4l (Kabel gezogen, Karte weg), startet der Supervisor nur diesen Dienst neu; NTP läuft weiter
- **Dashboard ohne Ballast** – reines Python aus der Distribution, kein npm, kein pip; Diagramme in eigenem SVG
- **Monitoring eingebaut** – versionierte JSON-API `/api/v1` mit API-Schlüsseln (nur lesen / verwalten), Prometheus-`/metrics` und `/healthz`; Verlauf über 30 Tage (SQLite), übersteht Neustarts; fertiges Grafana-Dashboard, Alarmregeln und Anleitungen für Home Assistant, Homepage, Glance und Uptime Kuma
- **Nachprüfbare Lieferkette** – SBOM, Schwachstellen-Bericht und Herkunftsnachweis zu jedem Release
- **Getestet** – 854 Unittests und ein 173-Punkte-Integrationstest gegen das gebaute Image in der CI

## Auf einen Blick

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/dashboard-dark.png">
  <img alt="Übersicht von ntp-gui: Hinweise zum aktuellen Zustand, Kennzahlen und Verlaufsdiagramme" src="docs/screenshots/dashboard-light.png">
</picture>

Elf Seiten: **Übersicht** (Hinweise, Kennzahlen, Verlauf, Zustand der Dienste), **Zeitquellen**
(jede Quelle mit Zustand *und Grund* – ausgewählt, kombiniert, nicht kombiniert, Falseticker …),
**GPS** (Himmelskarte, Signalstärken, Kalibrierassistent), **PTP** (Voraussetzungs-Check,
Netzwerkkarten, Port-Zustand), **Uhrqualität** (Temperatur und Frequenz, Schaltsekunden),
**Hardware** (was diese Hardware kann und was dafür fehlt), **Clients** (wer fragt, wie oft,
wie genau seine Uhr geht – mit Detailseite je Gerät –, Snippets für DHCP-Server und
Betriebssysteme, Zeitserver erzwingen), **Diagnose** (Log, Ereignisse, Diagnosepaket),
**Benachrichtigungen** (Kanäle und Zustellstand), **Einstellungen** (mit API-Schlüsseln, DNS
und Update-Hinweis) und **Hilfe** (Glossar und Entscheidungshilfe). Dazu die
**Vollbild-Uhr** unter `/clock`.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/sources-dark.png">
  <img alt="Zeitquellen-Seite: GPS mit Zustand „nicht kombiniert“ und Grund „Unsicherheit zu groß“, zwei Server ausgewählt bzw. kombiniert" src="docs/screenshots/sources-light.png">
</picture>

## So funktioniert's

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/graphics/architecture-dark.svg">
  <img alt="Architektur: Internet-NTP, GPS und PTP speisen chronyd im Container, der die Zeit per NTP ins LAN verteilt" src="docs/graphics/architecture-light.svg">
</picture>

chronyd im Container sammelt die Zeit aus allen verfügbaren Quellen, wählt die beste und
stellt damit die Uhr. Ein GPS-Empfänger kommt über `gpsd` dazu, PTP über `ptp4l`. Die
Clients im LAN fragen per NTP auf Port 123 – welche Adresse sie fragen sollen, erfahren
sie beim Verbindungsaufbau per DHCP.

| Komponente | Zweck |
|---|---|
| `chronyd` | NTP-Server für das LAN (Port 123/udp) und NTP-Client zu den Upstream-Quellen |
| `gpsd` | Optional: USB-/serieller GPS-Empfänger als Stratum-0-Referenz, inkl. PPS |
| `ptp4l` / `phc2sys` | PTP (IEEE 1588) als Grandmaster oder Slave, optional zuschaltbar |
| `dnsfwd` | Optional: kleiner DNS-Weiterleiter auf 127.0.0.1 für ntp-gui selbst (DoT/DoH/feste Server), siehe [DNS für ntp-gui](#dns-für-ntp-gui-gegen-schleifen-durch-dns-umschreibung) |
| Dashboard | Status, Offset-Verlauf, Zeitquellen, Clients, GPS-Fix, PTP-Zustand, aktive Konfiguration |
| `/metrics` | Prometheus-Endpunkt (Offset, Stratum, Quellen, Paketzähler, GPS, PTP) |
| `/healthz` | Health-Check für Docker/Kubernetes (ohne Login erreichbar) |

## Was ist möglich?

Jede Stufe baut auf der vorigen auf. Für die meisten Heimnetze reicht die zweite Zeile.

| Aufbau | Genauigkeit im LAN | Hardware | Wann sinnvoll |
|---|---|---|---|
| **NTP aus dem Internet** | 1–50 ms | keine | Standard. Reicht für PCs, Server, Smart-Home, Logs und Zertifikate – bei stabiler Festnetz-/Glasfaserleitung. |
| **+ NTS** | wie oben | keine | Gleiche Genauigkeit, aber gegen gefälschte Zeit abgesichert. Empfehlenswert. |
| **+ USB-GPS ohne PPS** | 1–10 ms | ~15 € (z. B. VK-162) | *Nicht* genauer als gutes Festnetz-NTP. Lohnt bei Mobilfunk/LTE/5G, Starlink, häufigen Ausfällen, Netzen ohne Internet oder als unabhängige Kontrolle. Einmal kalibrieren. |
| **+ GPS mit PPS** | < 1 µs | ~30–60 € (GPS-HAT oder Modul an GPIO) | Tausendfach genauer. Für Messaufbauten, Audio/Video über IP und als Basis für PTP. |
| **+ PTP** | < 1 µs im LAN | NIC mit Hardware-Zeitstempeln (z. B. Intel i210) | Nur mit GPS+PPS als Referenz und Clients, die PTP sprechen. AES67 (Dante nur im AES67-Modus), Labor, Lernen. |

**Kurz zu den Begriffen:**

- **NTP** (Network Time Protocol) – der Standard, den jedes Gerät spricht. Der Client fragt,
  der Server antwortet mit Zeitstempeln; aus Hin- und Rückweg errechnet der Client seine
  Abweichung. Genauigkeit begrenzt durch schwankende Laufzeiten im Netz.
- **Stratum** – Abstand zur Referenzuhr. Ein GPS ist Stratum 0, der Server daran Stratum 1,
  wer von ihm lernt Stratum 2 usw. Kleiner ist nicht automatisch genauer, aber kürzer.
- **NTS** (Network Time Security, RFC 8915) – NTP mit TLS-Schlüsselaustausch und signierten
  Paketen. Schützt gegen gefälschte Antworten, nicht gegen Ungenauigkeit.
- **GPS/GNSS** – Satelliten tragen Atomuhren; der Empfänger kennt daraus die Zeit. Über USB
  kommt sie aber als Textzeile (NMEA) mit Puffer-Verzögerung an – daher die Millisekunden.
- **PPS** (Pulse Per Second) – ein elektrischer Impuls exakt zum Sekundenwechsel, an einem
  GPIO-Pin oder einer seriellen Steuerleitung. Erst er macht GPS mikrosekundengenau.
- **PTP** (Precision Time Protocol, IEEE 1588) – Zeitverteilung, bei der die *Netzwerkkarte*
  die Pakete stempelt. Erreicht Nanosekunden, braucht aber passende Hardware auf beiden
  Seiten und taugt nur so viel wie die Referenz dahinter.

Alle Begriffe erklärt das Dashboard auch selbst: auf der Seite **Hilfe** und per ⓘ neben jedem Wert.

## Schnellstart

```bash
docker compose up -d
# Dashboard: http://<host>:8080
```

Alle weiteren Optionen (GPS, PPS, PTP, NTS-Server, Hotplug) stehen zum Einkommentieren in
[`docker-compose.all-in-one.yml`](docker-compose.all-in-one.yml) – siehe
[Alles in einem](#alles-in-einem).

Oder ohne Compose:

```bash
docker run -d --name ntp-gui \
  -p 123:123/udp -p 8080:8080 \
  --cap-add SYS_TIME \
  -e TZ=Europe/Berlin \
  -e NTP_POOLS=de.pool.ntp.org \
  -e ALLOW_NETWORKS=192.168.0.0/16 \
  ghcr.io/congp20/ntp-gui:latest
```

Prüfen, ob der Server antwortet (von einem Client aus – `chronyc -h` funktioniert
hier nicht, weil der Kommando-Port des Containers bewusst deaktiviert ist):

```bash
ntpdate -q <host>                                      # oder
chronyd -Q -t 5 "server <host> iburst maxsamples 1"    # oder im Container:
docker exec ntp-gui chronyc tracking
```

### Warum `--cap-add SYS_TIME`?

Ohne diese Capability darf `chronyd` die Uhr nicht stellen. Der Container erkennt das
beim Start selbst und startet chronyd dann automatisch mit `-x`: er verteilt weiterhin
Zeit, diszipliniert aber die Uhr nicht mehr – die Genauigkeit hängt dann allein am Host.
Für einen echten Zeitserver also `SYS_TIME` setzen.

**Wichtig:** Container teilen sich die Uhr mit dem Host. Ein Container mit `SYS_TIME`
stellt damit die Uhr des *Hosts*. Deshalb gehört dieser Dienst in eine eigene VM oder auf
einen dedizierten Host – nicht auf einen Docker-Host, auf dem noch anderes läuft.

## Alles in einem

Für alles, was über den Schnellstart hinausgeht, gibt es **eine** Datei mit allen
Optionen: [`docker-compose.all-in-one.yml`](docker-compose.all-in-one.yml). Aktiv ist darin
nur, was jeder braucht – NTP aus dem Internet (mit NTS abgesichert), Zeitserver für alle
privaten Netze, Host-Netzwerk, Healthcheck, Log-Begrenzung. Alles Weitere steht als
auskommentierter Block mit Erklärung darunter: was er tut, wann du ihn brauchst, welche
Zeilen dazugehören.

```bash
mkdir ntp-gui && cd ntp-gui
curl -fsSLo docker-compose.yml \
  https://raw.githubusercontent.com/ConGp20/ntp-gui/main/docker-compose.all-in-one.yml
docker compose up -d
# Dashboard: http://<host>:8080  ->  Seite „Hardware“
```

1. **Kopieren und starten** – so wie sie ist, läuft die Datei auf jedem Linux-Host.
2. **Seite „Hardware“ öffnen** – sie erkennt Empfänger, PPS, PTP-Karten und fehlende
   Rechte und nennt die Blöcke, die du einkommentieren musst, mit fertigem Ausschnitt.
3. **Einkommentieren** – Optionszeilen sind eingerückt und beginnen mit `#` und **zwei**
   Leerzeichen (`      #  - NET_ADMIN`); genau diese drei Zeichen löschen, alles davor
   stehen lassen, dann stimmt die Einrückung. Erklärungen haben nur ein Leerzeichen nach
   `#` und bleiben stehen. Die Regel ist mechanisch: Keine andere Zeile der Datei hat dieses
   Muster, selbst `sed -E 's/^( +)#  /\1/'` über die ganze Datei ergibt gültiges YAML.
4. **`docker compose up -d`** – Geräte, Capabilities und Mounts übernimmt Docker nur beim
   Erzeugen des Containers; ein reiner Neustart reicht dafür nicht.

Die Blöcke: Bridge-Netzwerk als Alternative (ohne PTP), Geräte einzeln durchreichen
(USB-GPS, Pi-UART, PPS, PTP-Uhr), `NET_ADMIN`/`NET_RAW` für PTP (`NET_RAW` braucht auch die
passive Messung der Client-Uhren – in Docker ist es ohnehin Standard), GPS, PTP mit Profil und
phc2sys, NTS-Server hinter einem Reverse Proxy, zwei Server im Verbund (`LOCAL_ORPHAN`),
Dashboard-Passwort, `WEB_READONLY`, anderer Dashboard-Port und **Hotplug**.

Umgebungsvariablen bleiben dabei **Startwerte**: Was du später im Dashboard speicherst, hat
Vorrang. Die Compose-Datei musst du nur für das anfassen, was Docker selbst regelt.

### Hotplug: GPS einstecken, wann du willst

Ein Eintrag unter `devices:` hat zwei Haken: Fehlt das Gerät beim Start, bricht
`docker compose up` mit „error gathering device information“ ab, und ein später
eingestecktes Gerät sieht der Container nie – Docker vergibt Geräte nur beim Erzeugen.
Der Hotplug-Block hängt deshalb stattdessen `/dev` des Hosts ein und erlaubt per
`device_cgroup_rules` nur die Gerätetypen, die ntp-gui braucht:

| Regel | Geräte |
|---|---|
| `c 166:* rwm` | `ttyACM*` – USB-GPS wie VK-162/u-blox |
| `c 188:* rwm` | `ttyUSB*` – GPS hinter USB-Seriell-Adapter (CP210x, FTDI, PL2303) |
| `c 204:* rwm` | `ttyAMA*` – UART des Raspberry Pi (GPS-HAT; Pi 5, Pi 3/4 nur mit `disable-bt`) |
| `c ${PPS_MAJOR:-136}:* rwm` | `/dev/ppsN` – PPS-Signal |
| `c ${PTP_MAJOR:-0}:* rwm` | `/dev/ptpN` – PTP-Hardwareuhr der Netzwerkkarte |
| `c 4:* rwm` (optional) | `ttyS*` – z. B. Mini-UART am Pi 3/4 ohne `disable-bt` (auch wenn `/dev/serial0` darauf zeigt); gibt auch die virtuellen Konsolen frei |

PPS und PTP bekommen ihre Gerätenummer (Major) vom Kernel erst beim Booten, sie
unterscheidet sich je System. Die Hardware-Seite zeigt sie an; du schreibst sie in eine
`.env` neben der Compose-Datei (`PPS_MAJOR=245`, `PTP_MAJOR=246`). Ohne `.env` greifen
Ersatzwerte, die nichts zusätzlich freigeben – der Container startet, nur PPS/PTP bleiben
gesperrt. Bewusst **nie** `c *:* rwm`: mit eingehängtem `/dev` wäre dann z. B. auch
`/dev/watchdog` offen, und schon das Öffnen kann den Host neu starten. Ein konfiguriertes,
aber fehlendes Gerät sucht der Container alle 30 Sekunden und übernimmt es, sobald es da
ist. Gilt nur für Linux-Hosts – Docker Desktop (macOS/Windows) reicht keine USB-Geräte durch.

## Hardware-Check

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/hardware-dark.png">
  <img alt="Hardware-Seite: Was diese Hardware kann – NTP-Server geht, USB-GPS nicht angeschlossen, Hardware-PTP nicht möglich wegen virtueller Netzwerkkarte" src="docs/screenshots/hardware-light.png">
</picture>

Die Seite **Hardware** beantwortet die Frage „Was kann *diese* Hardware von dem, was ntp-gui
kann?“ – ohne dass du `dmesg`, `ethtool` und `/proc` selbst lesen musst. Sie liest nur
(sysfs, `/proc`, `/dev`, die Geräteliste von gpsd, chrony-Tracking); serielle Geräte öffnet
sie nicht, weil schon das Schließen über die DTR-Leitung manche Boards zurücksetzt.

| Bereich | Was erkannt wird |
|---|---|
| **GPS-Empfänger** | Über USB-ID (z. B. `1546:01a7` = u-blox 7), die Geräteliste von gpsd und die Anschlussart: USB-Modem (`ttyACM`), USB-Seriell-Adapter (`ttyUSB`) oder UART (`ttyAMA`/`ttyS`). Daraus folgt, ob PPS überhaupt möglich ist. |
| **PPS** | Weg des Impulses – GPIO (`pps-gpio`, ~1 µs), DCD-Leitung am UART (~5 µs), DCD über USB (~1 ms) oder gar keiner – und ob **gerade Impulse ankommen** (live, keine Impulse, noch nie). |
| **PTP** | Je Netzwerkkarte: Treiber, Hardware-Zeitstempel (`ethtool -T`), eigene PTP-Uhr, ob sie im Container nutzbar ist; virtuelle Karten werden als solche erkannt. |
| **Plattform** | Raspberry-Pi-Modell, VM und Hypervisor, Docker Desktop/WSL, Netzwerkmodus (Host/Bridge). |
| **Container-Rechte** | `SYS_TIME`, `NET_ADMIN`, `NET_RAW`, ob `/dev` eingehängt ist, Major-Nummern für PPS/PTP. |
| **RTC** | Hat das System eine Echtzeituhr – und wie weit liegt sie daneben? Ohne RTC startet ein Pi mit falscher Zeit. |

Darunter steht eine **Matrix**: NTP-Server, Uhr stellen, NTS, USB-GPS, GPS + PPS, PTP mit
Hardware- bzw. Software-Zeitstempeln, PTP→NTP-Brücke und GPS→PTP-Grandmaster – jeweils mit
*geht*, *geht mit Änderung*, *eingeschränkt*, *geht nicht* oder *unklar*, der erreichbaren
Genauigkeit und bei „geht mit Änderung“ dem fertigen Ausschnitt für Compose-Datei, `.env`
oder Boot-Konfiguration.

**Beispiel VK-162:** erkannt als u-blox 7 an `ttyACM0`, also USB-Modem. Die Matrix zeigt
„USB-GPS: geht (1–10 ms nach Kalibrierung)“ und „GPS + PPS: geht nicht“ – über USB-CDC
kommt kein Sekundenimpuls beim Rechner an, die Leitung trägt nur die Datenzeilen. Wer
Mikrosekunden will, braucht einen Empfänger mit PPS-Pin an einem GPIO oder einer echten
seriellen Schnittstelle.

Die Prüfung läuft im Hintergrund kurz nach dem Start und dann alle 5 Minuten; ihre
Ergebnisse erscheinen auch im Hinweis-Kasten der Übersicht und unter `/metrics`.
`/api/hardware?refresh=1` erzwingt eine neue Prüfung.

## Einstellungen im Dashboard

Alles Wesentliche lässt sich unter **Einstellungen** ändern – Zeitquellen (mit Vorlagen für
PTB, Cloudflare, Netnod und pool.ntp.org), Zugriff aus dem LAN, NTS, GPS, PTP und das
Dashboard selbst. Jedes Feld zeigt, woher sein Wert kommt:

| Herkunft | Bedeutung |
|---|---|
| **Dashboard** | im GUI gespeichert – hat Vorrang |
| **Umgebung** | aus der Compose-Datei bzw. `-e …` |
| **Standard** | eingebauter Standardwert |

Umgebungsvariablen funktionieren also weiter, sind aber nur noch **Startwerte**. Ein Klick
auf „zurücksetzen“ entfernt den Dashboard-Wert wieder. Nach dem Speichern startet der
Container die Zeitdienste mit der neuen Konfiguration neu (wenige Sekunden, chrony behält
dabei seine Messwerte); Felder mit „wirkt sofort“ brauchen gar keinen Neustart.

- Gespeichert wird in `/var/lib/chrony/ntp-gui/settings.json` (Rechte `0600`). Damit das eine
  Neuerstellung des Containers übersteht, muss `/var/lib/chrony` auf einem **Volume** liegen –
  die mitgelieferten Compose-Dateien tun das; das Dashboard warnt, wenn nicht.
- Ein **Passwort** fürs Dashboard lässt sich direkt dort setzen (gespeichert als PBKDF2-Hash).
  `WEB_USER`/`WEB_PASSWORD` aus der Umgebung haben Vorrang.
- `WEB_READONLY=true` sperrt alle Änderungen – das Dashboard zeigt dann nur an.
- **Exportieren/Importieren** sichert die Dashboard-Werte als JSON (ohne Passwort).
- Eine gemountete `/config/chrony.conf` bzw. `/config/ptp4l.conf` ersetzt die erzeugte
  Konfiguration weiterhin komplett.

Änderungen per API sind gegen CSRF geschützt: sie brauchen den Header `X-NTP-GUI: 1`, JSON
als Inhalt und – falls der Browser einen `Origin` mitschickt – denselben Host. Für Skripte
gibt es [API-Schlüssel](#api-schlüssel); mit ihnen entfällt der Header.

## Per DHCP verteilen (Option 42)

Der Zeitserver nützt nur etwas, wenn die Clients ihn kennen. DHCP Option 42 (`ntp-servers`)
verteilt die Adresse automatisch, der Client fragt danach direkt bei ntp-gui an:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/graphics/dhcp-flow-dark.svg">
  <img alt="Ablauf: DHCP-Offer und -Ack enthalten Option 42 mit der Adresse von ntp-gui, danach fragt der Client per NTP an" src="docs/graphics/dhcp-flow-light.svg">
</picture>

Die Option wird im DHCP-Server eingetragen. Beispiele mit der Server-IP `192.168.1.10`:

**ISC dhcpd** (`/etc/dhcp/dhcpd.conf`)
```
option ntp-servers 192.168.1.10;
```

**Kea DHCPv4** (`kea-dhcp4.conf`)
```json
"option-data": [
  { "name": "ntp-servers", "data": "192.168.1.10" }
]
```

**dnsmasq**
```
dhcp-option=42,192.168.1.10
```

**OPNsense / pfSense**
Services → DHCP Server → (Interface) → *NTP Server 1* = `192.168.1.10`

**MikroTik RouterOS**
```
/ip dhcp-server network set [find] ntp-server=192.168.1.10
```

**UniFi**
Settings → Networks → (Netzwerk) → DHCP → *NTP Server* = `192.168.1.10`

**Windows Server DHCP**
Bereichsoptionen → *042 NTP-Server* → `192.168.1.10`

**FRITZ!Box**
Die FRITZ!Box verteilt Option 42 nicht frei konfigurierbar. Dort entweder Heimnetz →
Netzwerk → Netzwerkeinstellungen → *Zeitserver* setzen (sofern das Modell es anbietet),
oder die Clients direkt konfigurieren.

Für IPv6 ist Option 42 nicht zuständig – dort verteilt man NTP über DHCPv6 Option 56
(`OPTION_NTP_SERVER`) bzw. über den Router Advertisement Daemon.

## Zeitserver erzwingen

Option 42 ist nur ein Angebot. Viele Geräte ignorieren es und fragen fest eingebaute
Namen: Windows `time.windows.com`, Apple `time.apple.com`, Android `time.android.com`,
Sonos, Fire TV, Router, IoT-Geräte meist `pool.ntp.org`. Das ist nicht nur unschön: Ohne
Internet gehen diese Uhren falsch, und auf der Seite **Clients** tauchen sie gar nicht auf.
Die Seite **Clients → Zeitserver erzwingen** liefert dafür fertige Anleitungen – mit der
Adresse deines Servers schon eingesetzt – und eine Prüfung.

Es gibt zwei Wege, beide zusammen sind am gründlichsten:

| Weg | Wie | Erreicht | Erreicht nicht |
|---|---|---|---|
| **DNS-Umschreibung** | Der DNS-Server im LAN beantwortet `time.windows.com` & Co. mit der Adresse von ntp-gui | Geräte, die einen Namen fragen und deinen DNS-Server nutzen | fest eingetragene IP-Adressen, Geräte mit eigenem DNS (DNS-over-HTTPS, `8.8.8.8` fest) |
| **Firewall-Umleitung** (DNAT) | Der Router leitet jedes NTP-Paket (UDP 123), das ins Internet will, auf ntp-gui um | wirklich jedes Gerät | – |

**Unterstützte Systeme:** DNS – AdGuard Home, Pi-hole, dnsmasq, Unbound; Firewall –
OPNsense/pfSense, MikroTik, OpenWrt, nftables (Linux) und UniFi. Die Namensliste deckt
Windows/Xbox, Apple, Google/Android, Amazon, die Linux-Distributionen, OpenWrt/pfSense/OPNsense,
Ubiquiti, Sonos, die FRITZ!Box als Client, VMware, NIST und `*.pool.ntp.org` ab. Eigene
Namen (etwa den fest eingetragenen Server einer Kamera) trägst du unter **Einstellungen →
Weitere Namen für „Zeitserver erzwingen“** ein (`ENFORCE_HOSTNAMES`).

Worauf die Anleitungen achten – und warum:

- **ntp-gui selbst ist ausgenommen.** Sonst landen auch die Anfragen von ntp-gui an seine
  eigenen Quellen wieder bei ntp-gui – eine Schleife, die Uhr hätte keine echte Quelle mehr.
  Bei der Firewall heißt das: eine Ausnahme für die Adresse des Servers. Beim DNS: Der
  ntp-gui-Host bekommt einen anderen DNS-Server oder ist in AdGuard/Pi-hole von der Regel
  ausgenommen (AdGuard: `client=~<IP>`).
- **Hairpin.** Stehen Gerät und ntp-gui im selben Netz, geht die Antwort von ntp-gui direkt
  ans Gerät – am Router vorbei, mit dem falschen Absender, und das Gerät verwirft sie. Die
  Firewall-Anleitungen enthalten dafür eine Masquerade-/SNAT-Regel. Nachteil: ntp-gui sieht
  diese Geräte dann alle unter der Adresse des Routers. Sauberer ist ein eigenes VLAN für
  ntp-gui.
- **NTS-Namen werden nie umgeschrieben.** Ein NTS-Client prüft per TLS-Zertifikat, dass er
  wirklich mit `time.cloudflare.com` oder `ptbtime1.ptb.de` spricht. Biegst du den Namen um,
  scheitert die Prüfung, und das Gerät bekommt *gar keine* Zeit mehr. Deshalb fehlen
  `time.cloudflare.com`, `nts.netnod.se`, `ptbtime1–4.ptb.de`, `nts.time.nl` und
  `ntp.zeitgitter.net` absichtlich – und eignen sich umgekehrt gut als Quellen für ntp-gui
  selbst, weil sie nie zu dir zurückgebogen werden. Ebenso nie umgeschrieben: `fritz.box`.
- **Samsung- und LG-Fernseher** holen die Zeit per HTTPS vom Hersteller, nicht per NTP. Eine
  Umschreibung würde dort nur die Uhr kaputtmachen; sie stehen darum nicht auf der Liste.
- **Anderer NTP-Port als 123?** DNS biegt nur die Adresse um, nicht den Port – dann hilft nur
  die Firewall-Umleitung.

Der Knopf **Prüfen** löst die Namen über den DNS-Server des Containers auf, schickt je eine
NTP-Anfrage an sie und an zwei öffentliche Server und vergleicht die Antworten mit diesem
Server. Ergebnis je Name: *DNS-Umschreibung wirkt*, *teilweise* (meist fehlt die
AAAA-Sperre für IPv6), *nicht umgeschrieben* oder *keine Antwort*. Wird die Anfrage von
ntp-gui an einen öffentlichen Server zu ntp-gui selbst zurückgeleitet, meldet die Prüfung
eine **Schleife**, ebenso, wenn eine eigene Zeitquelle per DNS auf ntp-gui zeigt. Gesendet
wird nur auf deinen Klick, höchstens einmal je 30 Sekunden, und nur NTP-Anfragen – keine
Daten über deine Instanz. Ob ein *Gerät* wirklich umgeleitet wird, kann der Server nicht von
innen sehen; dafür zeigt die Seite einen Selbsttest für Windows, macOS und Linux.

### DNS für ntp-gui (gegen Schleifen durch DNS-Umschreibung)

Schreibt dein DNS-Server im LAN (AdGuard Home, Pi-hole, dnsmasq) Zeitserver-Namen auf ntp-gui um
und nutzt ntp-gui denselben DNS, fragt chronyd für `pool.ntp.org` sich selbst. Abhilfe:
ntp-gui eigene DNS-Server geben – im Dashboard unter **Einstellungen → DNS für ntp-gui** oder
per Umgebungsvariable:

```yaml
environment:
  DNS_MODE: dot                      # system (Standard) | servers | dot | doh
  DNS_DOT: "dns.quad9.net one.one.one.one"
  # DNS_SERVERS: "9.9.9.9 149.112.112.112"          # Modus servers (nur IP-Adressen)
  # DNS_DOH: "https://dns.quad9.net/dns-query"      # Modus doh
  # DNS_PIN: "dns.quad9.net=9.9.9.9"                # optional: feste Adressen für DoT/DoH
  # DNS_FALLBACK: "false"                           # kein Rückfall auf den System-DNS
```

ntp-gui startet dann einen kleinen Weiterleiter **nur auf 127.0.0.1** im Container und trägt
ihn in `/etc/resolv.conf` ein (das Original wird gesichert und beim Zurückschalten, Beenden
und nach einem Absturz zurückgeschrieben). chronyd, NTS und die Prüfung „Zeitserver erzwingen“
nutzen ab da deine Server. DNS-over-TLS (853/tcp) und DNS-over-HTTPS (443/tcp) sind
verschlüsselt, prüfen das Zertifikat und sind auch von einer DNS-Umleitung per Firewall
(Port 53) nicht betroffen. Antwortet keiner deiner Server, fragt ntp-gui den ursprünglichen
DNS (abschaltbar mit `DNS_FALLBACK=false`) und meldet das als Ereignis „DNS“. Den Zustand
zeigen **Einstellungen → DNS für ntp-gui**, die Kachel **Dienste** der Übersicht und
`/api/v1/dns`.

Ist das Dateisystem schreibgeschützt (`read_only: true`), setz zusätzlich `dns: 127.0.0.1`
beim Dienst in der Compose-Datei. Dann gibt es keinen System-DNS mehr, der die Namen von
DoT/DoH-Servern auflösen kann: Trag die Server unter „Feste Adressen für DoT/DoH“ ein
(`DNS_PIN=dns.quad9.net=9.9.9.9`) oder nutze den Modus „Eigene DNS-Server“ mit IP-Adressen.

Die Firewall-Anleitungen unter **Zeitserver erzwingen** enthalten außerdem eine optionale
**DNS-Umleitung per Firewall** (Port 53 auf AdGuard/Pi-hole) – mit Pflicht-Ausnahme für
ntp-gui und den DNS-Server selbst.

### Wie genau gehen meine Clients?

Die Seite **Clients** zeigt je Gerät, wie weit seine Uhr danebenliegt – **rein passiv**: Jede
NTP-Anfrage trägt die Uhrzeit des Clients beim Absenden, der Kernel stempelt sie beim
Empfang mit der Zeit dieses Servers. Die Differenz ist die Abweichung der Client-Uhr (plus
die Laufzeit im LAN, meist unter 1 ms). Positiv heißt: die Uhr des Geräts geht vor. An die
Geräte wird dabei nichts gesendet – nur auf deinen Klick „Aktiv nachmessen“ (siehe unten).

| Zustand | Bedeutung |
|---|---|
| **messbar** | Der Client schreibt seine echte Uhrzeit in die Anfrage – das tun die meisten einfachen Clients (SNTP), etwa Windows, systemd-timesyncd, klassisches ntpd und viele IoT-Geräte |
| **nicht messbar (verschleiert)** | chrony, OpenNTPD, NTPsec und NTS-Clients schreiben absichtlich eine Zufallszahl, damit Dritte ihre Uhr nicht auslesen können – gutes Verhalten, kein Fehler |
| **nicht messbar (ohne Zeitstempel)** | Der Client sendet gar keine Uhrzeit mit |
| **Uhr liegt mehr als einen Tag daneben** | gleichbleibend absurde Werte, z. B. 1970 nach einem Batterietausch – die Uhr ist wirklich falsch |

Voraussetzungen:

- **`CAP_NET_RAW`** – der Container liest NTP-Pakete über einen Paket-Socket mit; ein Filter
  im Kernel lässt nur UDP an den NTP-Port durch. In Docker ist `NET_RAW` Standard; wer
  Capabilities mit `cap_drop: [ALL]` entfernt, ergänzt `cap_add: [NET_RAW]`.
- **Host-Netzwerk** (`network_mode: host`, wie in der All-in-one-Datei) – nur ohne NAT sieht
  der Container die echten Client-Adressen. Hinter der Docker-Bridge erscheinen alle Geräte
  unter einer Adresse.

**Datenschutz:** Die Messwerte bleiben auf dieser Instanz (in `ntp-gui.db`). Ins
Diagnosepaket kommt die Client-Liste nur, wenn du es ankreuzt – und dann mit Pseudonymen
(`client-07`) statt Adressen. Abschalten: `CLIENTMON=false` oder in den Einstellungen
(wirkt ohne Neustart). API: `/api/clients/offsets`.

### Ein Gerät im Detail

Ein Klick auf ein Gerät in der Liste unter **Clients** öffnet seine eigene Seite
(`#/clients/192.168.1.23`).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/clients-detail-dark.png">
  <img alt="Detailseite eines Clients: Abweichung über die Zeit, Abstand der Anfragen, vermutete Software und Gerätedaten" src="docs/screenshots/clients-detail-light.png">
</picture>

Dort siehst du:

- wie die Uhr des Geräts in den letzten 7 Tagen lag: Sägezahn = läuft weg und wird
  nachgestellt, Sprung = stellt selten nach;
- wie oft das Gerät fragt (tatsächlicher Abstand und das Poll-Feld aus der Anfrage);
- ob es messbar ist, und wenn nicht, warum;
- welche Software vermutlich fragt (Windows, systemd-timesyncd, chrony/NTPsec, ntpd,
  ESP32/IoT, Apple), mit Begründung und klar als **Vermutung** markiert;
- seinen Namen aus dem DNS – nur wenn du `CLIENTS_RDNS=true` setzt, nur für private Adressen
  und nur, wenn kein beteiligter DNS-Server öffentlich ist; nie über DoT/DoH;
- seine MAC-Adresse, nur wenn das Gerät im selben Netz steht. Den Hersteller zeigt ntp-gui nur,
  wenn eine OUI-Liste vorliegt, z. B. als Datei `/config/oui.txt` aus
  https://standards-oui.ieee.org/oui/oui.txt. MAC-Adressen verlassen die Instanz nie.

Du kannst jedem Gerät einen **eigenen Namen und eine Notiz** geben. Beides bleibt auf der
Instanz. Gespeicherte Ereignisse nennen nur die Adresse, den Namen setzt erst die Anzeige ein;
ins Diagnosepaket und in Benachrichtigungen gelangt nie ein Name, Notizen werden nie exportiert.

**Aktiv nachmessen** schickt genau eine NTP-Anfrage an das Gerät. Router, NAS und manche
Kameras sind selbst Zeitserver und antworten; dann siehst du ihre Uhr, auch wenn sie ihre
Sendezeit verschleiern. Die meisten Geräte antworten nicht, das ist normal. Das geht nur bei
bekannten Geräten mit privater Adresse (nicht fe80::), pro Gerät höchstens alle 30 s.

Der **Netzüberblick** auf der Clients-Seite zeigt die Verteilung der Abweichungen, die Geräte
mit der größten Abweichung, verstummte Geräte und Geräte, die öfter als alle 8 s fragen.

**Alarm:** Mit `CLIENTS_ALARM_MS=1000` (oder in den Einstellungen unter LAN → Erweitert)
meldet ntp-gui das Ereignis „Uhr von … weicht um … ab“, sobald ein Gerät zweimal in Folge mehr
als eine Sekunde danebenliegt. Mit einem [Benachrichtigungskanal](#benachrichtigungen) für die
Art „Clients“ landet die Meldung z. B. auf dem Handy.

## NTS – abgesicherte Zeit

Klassisches NTP ist unverschlüsselt und unsigniert: Wer im Pfad sitzt, kann eine falsche
Uhrzeit unterschieben – und mit falscher Zeit scheitern Zertifikate, 2FA-Codes und Logs.
**NTS** (RFC 8915) holt per TLS (TCP-Port **4460**) Schlüssel ab und signiert danach jedes
NTP-Paket. Die Genauigkeit bleibt gleich.

Einschalten: in den Einstellungen bei einer Quelle den Haken **NTS** setzen – oder eine
der Vorlagen nehmen. Per Umgebung:

```yaml
environment:
  NTP_NTS_SERVERS: "ptbtime1.ptb.de,ptbtime2.ptb.de,nts.netnod.se,time.cloudflare.com"
```

Öffentliche NTS-Server: `ptbtime1/2/3.ptb.de` (PTB, Braunschweig), `time.cloudflare.com`,
`nts.netnod.se`, `ntp.zeitgitter.net`, `nts.time.nl`. Auf der Seite **Zeitquellen** zeigt
jede Quelle, ob ihre Antworten authentifiziert sind, wie viele Cookies vorrätig sind und
wann der letzte Schlüsselaustausch war.

**Henne-Ei-Problem:** Für TLS muss die Uhr ungefähr stimmen – ein Raspberry Pi ohne
Echtzeituhr startet aber mit falscher Zeit. Deshalb ist `nocerttimecheck 1` voreingestellt
(„Zertifikatszeit beim Start nicht prüfen“): Beim allerersten Abgleich wird die
Gültigkeitszeit des Zertifikats nicht geprüft, danach normal.

### NTS-Server für das LAN

ntp-gui kann NTS auch selbst anbieten. Sinnvoll ist das nur, wenn die Clients NTS können
(chrony ≥ 4, NTPsec) und dem Zertifikat vertrauen – für Windows, macOS und die meisten
Geräte bleibt es bei normalem NTP.

1. Zertifikat (am besten die volle Kette, `fullchain`) und Schlüssel einhängen – nach
   `/config/nts.crt` und `/config/nts.key` (Standard) oder unter `/certs` bzw.
   `/etc/letsencrypt`. **Andere Pfade lehnt ntp-gui ab:** Die Dateien werden in ein
   Verzeichnis kopiert, das chronyd lesen darf; ein freier Pfad würde erlauben, z. B.
   `/etc/shadow` dorthin zu kopieren.
2. `NTS_SERVER=true` setzen (oder im Dashboard unter NTS einschalten) und Port `4460/tcp`
   erreichbar machen.
3. `NTS_SERVER_NAME` auf den Namen setzen, unter dem die Clients den Server erreichen. Er
   muss im Zertifikat stehen (ohne Reverse Proxy ist das derselbe Name wie für NTS-KE).

Beim Start prüft ntp-gui das Paar (PEM-Format, höchstens 1 MB, Schlüssel passt zum
Zertifikat) und legt Kopien für chronyd an (`root:_chrony`, `0640` – chronyd darf lesen, aber
nicht schreiben). Passt das Paar nicht – typisch mitten in einer Erneuerung –, bleiben die
letzten gültigen Kopien aktiv; gibt es keine, bleibt der NTS-Server aus, statt chronyd am
Start zu hindern. Die Seite **Zeitquellen** zeigt Name, Aussteller, Restlaufzeit und ob der
Name im Zertifikat steht.

**Erneuerung ohne Handarbeit:** chrony liest Zertifikate nur beim Start. Deshalb prüft der
Container jede Minute, ob sich Zertifikat oder Schlüssel geändert haben. Bleibt die Änderung
10 Sekunden stabil (damit beide Dateien geschrieben sind), schreibt er die Konfiguration neu
und startet nur chronyd neu – gpsd, ptp4l und phc2sys laufen weiter. Im Log steht dann
`[nts] Zertifikat erneuert – chronyd lädt neu`. Scheitert das Neuschreiben, läuft der alte
chronyd weiter, und der Status zeigt den Fehler.

### NTS hinter einem Reverse Proxy

Läuft im Netz schon ein Reverse Proxy mit Let's-Encrypt-Zertifikaten (Nginx Proxy Manager,
Zoraxy, Traefik, nginx, HAProxy), kann ntp-gui dessen Zertifikat mitbenutzen. Zwei Dinge
sind dabei anders als bei einer Webseite:

**Nur TLS-Passthrough, kein Terminieren.** Beim NTS-Schlüsselaustausch (NTS-KE, TCP 4460)
leiten Client und Server die Schlüssel für die NTP-Pakete aus der TLS-Sitzung selbst ab
(RFC 8915, TLS-Exporter). Entschlüsselt der Proxy die Verbindung, kennt *er* die Schlüssel,
chronyd aber nicht – die Pakete danach lassen sich nicht prüfen. Der Proxy muss den
TCP-Strom deshalb unverändert durchreichen (Stream/TCP-Modus), und chronyd braucht das
Zertifikat selbst: Du hängst den Zertifikatsordner des Proxys schreibgeschützt ein.

**UDP 123 geht direkt.** Nach dem Schlüsselaustausch schickt der Client seine NTP-Pakete
(UDP) an die Adresse, mit der er den Schlüsselaustausch gemacht hat – also an den Proxy,
der UDP meist gar nicht weiterreicht. `NTS_SERVER_NAME` setzt in chrony `ntsntpserver`:
Der Server nennt dem Client dann diesen Namen, und die NTP-Pakete gehen dorthin. Es geht um
zwei Namen:

- Der Name, unter dem die Clients den **Proxy** ansprechen (NTS-KE, TCP 4460), muss im
  **Zertifikat** stehen – nur er wird per TLS geprüft.
- `NTS_SERVER_NAME` muss auf den **Host von ntp-gui** zeigen (NTP, UDP 123). Für ihn prüft
  niemand ein Zertifikat.

Laufen Proxy und ntp-gui auf demselben Host, ist es derselbe Name, und beides ist mit einem
Eintrag erfüllt.

Außerdem: chronyd sieht hinter dem Proxy nur dessen IP-Adresse und beantwortet NTS-KE nur
aus Netzen in `ALLOW_NETWORKS`. Mit den Standardwerten (alle privaten Netze, inklusive
Docker-Bridges in `172.16.0.0/12`) passt das.

Der übliche Aufbau – Proxy und ntp-gui auf demselben Host. Der Proxy belegt außen 4460,
chronyd lauscht deshalb auf 4461 (`NTS_SERVER_PORT`):

```
Client ──TCP 4460 (TLS, NTS-KE)──▶ Reverse Proxy ──TCP 4461, unverändert──▶ chronyd (ntp-gui)
Client ──UDP 123 (NTP mit NTS)────────────────────────────────────────────▶ chronyd (ntp-gui)
```

In der [All-in-one-Datei](docker-compose.all-in-one.yml) ist das der Block
„[OPTION NTS-Server hinter Reverse Proxy]“:

```yaml
volumes:
  - /opt/npm/letsencrypt:/certs:ro            # Zertifikatsordner des Proxys
environment:
  NTS_SERVER: "true"
  NTS_SERVER_CERT: "/certs/live/npm-1/fullchain.pem"
  NTS_SERVER_KEY: "/certs/live/npm-1/privkey.pem"
  NTS_SERVER_NAME: "zeit.example.com"
  NTS_SERVER_PORT: "4461"
```

#### Nginx Proxy Manager

1. Unter **SSL Certificates** ein Let's-Encrypt-Zertifikat für `zeit.example.com` anlegen
   (aus dem LAN heraus mit DNS-Challenge).
2. Herausfinden, in welchem Ordner es liegt: NPM legt je Zertifikat `live/npm-N/` an.
   Diese Schleife zeigt je Ordner die Namen im Zertifikat (sie funktioniert auch mit
   DNS-Challenge, deren `renewal/*.conf` keinen Domainnamen enthält):
   ```bash
   for d in /opt/npm/letsencrypt/live/npm-*/; do
     echo "$d: $(openssl x509 -noout -ext subjectAltName -in "$d/cert.pem" | tail -1)"
   done
   ```
3. Den **ganzen** `letsencrypt`-Ordner nach `/certs` einhängen, nicht nur `live/npm-N` –
   die Dateien dort sind Verweise auf `../../archive/`.
4. Unter **Streams → Add Stream**: Incoming Port `4460`, Forward Host = IP des Hosts,
   Forward Port `4461`, *TCP Forwarding* an, *UDP Forwarding* aus. **Kein** SSL-Zertifikat
   am Stream auswählen – das würde TLS terminieren.
5. Im Compose von NPM den Port `4460:4460` veröffentlichen (siehe unten).

**Für alle Proxys gilt:** Läuft der Proxy selbst in Docker mit Bridge-Netzwerk, muss
sein Compose den äußeren NTS-Port veröffentlichen (`4460:4460/tcp`), sonst kommt keine
Verbindung an. Läuft ntp-gui mit Bridge-Netzwerk statt Host-Netzwerk, folgt dessen
Port-Mapping `NTS_SERVER_PORT` (bei `4461` also `4461:4461/tcp`).

#### Zoraxy

1. Das Zertifikat für `zeit.example.com` in Zoraxy anlegen (ACME oder hochgeladen). Zoraxy
   speichert es als `<domain>.pem` und `<domain>.key` im Ordner `conf/certs`.
2. Diesen Ordner nach `/certs` einhängen und `NTS_SERVER_CERT=/certs/zeit.example.com.pem`,
   `NTS_SERVER_KEY=/certs/zeit.example.com.key` setzen.
3. Unter **Stream Proxy** eine Regel anlegen: Listening Port `4460`, Proxy Target
   `<host-ip>:4461`, nur TCP.

#### Traefik

Traefik leitet per SNI weiter, ohne zu entschlüsseln (`passthrough: true`). Seine eigenen
Zertifikate liegen allerdings in `acme.json`; für ntp-gui brauchst du PEM-Dateien – z. B. von
certbot oder per [traefik-certs-dumper](https://github.com/ldez/traefik-certs-dumper).

```yaml
# statische Konfiguration
entryPoints:
  nts:
    address: ":4460"

# dynamische Konfiguration (File-Provider)
tcp:
  routers:
    nts:
      entryPoints: [nts]
      rule: "HostSNI(`zeit.example.com`)"
      service: ntp-gui-nts
      tls:
        passthrough: true
  services:
    ntp-gui-nts:
      loadBalancer:
        servers:
          - address: "192.168.1.10:4461"
```

#### nginx (stream)

```nginx
stream {
    map $ssl_preread_server_name $nts_backend {
        zeit.example.com  192.168.1.10:4461;
        default           "";    # ohne passenden SNI-Namen: Verbindung wird abgewiesen
    }
    server {
        listen 4460;
        ssl_preread on;          # liest nur den SNI-Namen, entschlüsselt nichts
        proxy_pass $nts_backend;
    }
}
```

Mit certbot liegen die Zertifikate unter `/etc/letsencrypt`; den Ordner genauso nach
`/etc/letsencrypt:ro` einhängen und `…/live/zeit.example.com/fullchain.pem` bzw.
`privkey.pem` eintragen.

#### HAProxy

```
frontend nts
    bind :4460
    mode tcp
    tcp-request inspect-delay 5s
    tcp-request content accept if { req_ssl_hello_type 1 }
    use_backend ntp_gui_nts if { req_ssl_sni -i zeit.example.com }

backend ntp_gui_nts
    mode tcp
    server ntpgui 192.168.1.10:4461 check
```

#### Clients einrichten und prüfen

```
# chrony.conf auf dem Client
server zeit.example.com iburst nts
# nur wenn der Proxy außen NICHT auf 4460 lauscht:
# server zeit.example.com iburst nts ntsport 4461
```

```bash
# Liefert der Proxy das richtige Zertifikat durch?
openssl s_client -connect zeit.example.com:4460 -servername zeit.example.com -alpn ntske/1 </dev/null \
  | openssl x509 -noout -subject -issuer -dates
# Auf dem Client: Mode „NTS“, KeyID und Cookies > 0
chronyc -N authdata
```

## Stratum 1 mit GPS

Mit einem GPS-Empfänger wird der Container unabhängig vom Internet: `gpsd` liest den
Empfänger, chrony nutzt ihn als Referenzuhr und liefert die Zeit als Stratum 1 ins LAN.

Ein **VK-162** (u-blox 7, ~15 €) ist dafür der einfachste Einstieg: einstecken, er meldet
sich als `/dev/ttyACM0`, kein Treiber nötig. Antenne ans Fenster oder nach draußen –
ohne Himmelssicht gibt es keinen Fix.

```bash
dmesg | grep -i -E "ttyACM|ttyUSB|u-blox"   # welches Gerät ist es?
docker compose -f docker-compose.gps.yml up -d
```

**Auf einem Raspberry Pi** gibt es eine eigene Vorlage mit Host-Netzwerk und den nötigen
Vorbereitungen im Kopfkommentar (Zeitdienst des Pi abschalten, Gerät finden):
[`docker-compose.pi-gps.yml`](docker-compose.pi-gps.yml).

```bash
docker compose -f docker-compose.pi-gps.yml up -d
```

Oder direkt:

```bash
docker run -d --name ntp-gui \
  -p 123:123/udp -p 8080:8080 \
  --cap-add SYS_TIME \
  --device /dev/ttyACM0 \
  -e GPS_ENABLE=true -e GPS_DEVICE=/dev/ttyACM0 \
  -e ALLOW_NETWORKS=192.168.0.0/16 \
  ghcr.io/congp20/ntp-gui:latest
```

Das Gerät **muss** per `--device` bzw. `devices:` durchgereicht werden – ein Container
sieht `/dev/ttyACM0` sonst nicht. Steckt der Empfänger nicht immer (oder soll er sich
später einstecken lassen), nimm den Hotplug-Block der
[All-in-one-Datei](#hotplug-gps-einstecken-wann-du-willst). Welche Variante passt, zeigt
die Seite **Hardware**.

### Wie genau wird das?

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/graphics/accuracy-dark.svg">
  <img alt="Typische Genauigkeit: Internet-NTP 1–50 ms, USB-GPS 1–10 ms, GPS mit PPS 0,1–1 µs, PTP mit Hardware-Zeitstempeln 20 ns–1 µs" src="docs/graphics/accuracy-light.svg">
</picture>

Die Bremse beim USB-Empfänger ist nicht das GPS, sondern der Weg: die Zeit kommt als
NMEA-Textzeile, gepuffert und mit schwankender Verzögerung. **Ohne PPS ist ein USB-GPS
deshalb nicht genauer als NTP über eine gute Festnetzleitung** – beides landet im
einstelligen Millisekundenbereich. Sein Wert liegt woanders:

- **Unabhängigkeit** – die Zeit stimmt auch ohne Internet (Ausfall, abgeschottetes Netz).
- **Schlechte Uplinks** – über Mobilfunk/LTE/5G, Starlink oder Satellit schwanken die
  Laufzeiten um zig Millisekunden; dort ist das USB-GPS klar besser als Internet-NTP.
- **Kontrolle** – eine zweite, unabhängige Meinung, die gefälschte oder falsche
  Internetzeit als Falseticker entlarvt.

Mehr Genauigkeit bringt erst ein **PPS-Signal**.

Wer die Mikrosekunden-Klasse will, braucht einen Empfänger mit PPS-Ausgang. Zum Vergleich
Jeff Geerlings [time-pi](https://github.com/geerlingguy/time-pi): ein Raspberry Pi 5 mit
TimeHAT (Intel-i226-Netzwerkkarte mit eigener PTP-Uhr) und einem u-blox ZED-F9T. Dort geht
der PPS-Impuls direkt in die Netzwerkkarte und `ts2phc` stellt deren PTP-Uhr danach – der
genaueste Weg zum PTP-Grandmaster. ntp-gui geht einen anderen Weg: chrony stellt die
**Systemuhr** nach GPS + PPS (`GPS_PPS_DEVICE`), und `phc2sys` kopiert sie im
Grandmaster-Betrieb auf die Netzwerkkarte (`PTP_MODE=master`). Das reicht für
Mikrosekunden, kostet gegenüber `ts2phc` aber einen Zwischenschritt. `ts2phc` (PPS direkt
in die Netzwerkkarte) unterstützt ntp-gui nicht.

### Warum steht das GPS auf „nicht kombiniert“ – und der Offset bei +57 ms?

Typisches Bild nach ein paar Stunden mit USB-GPS: Die Internetquellen sind *ausgewählt*
bzw. *kombiniert*, das GPS steht mit einem konstanten Offset von z. B. **+57 ms** daneben
und wird nicht genutzt. Das ist kein Fehler, sondern zwei Einstellungen, die ab Werk
bewusst vorsichtig sind:

1. **Offset** – der Empfänger meldet die Zeit immer um denselben Betrag zu spät
   (NMEA-Zeile + serielle Übertragung + USB-Puffer, typisch 20–150 ms). Dieser Wert ist je
   Empfänger, Firmware und Baudrate konstant – er wird nicht besser, wenn man wartet,
   sondern muss einmal eingetragen werden.
2. **Delay** – sagt chrony, wie unsicher die GPS-Zeit ist. Mit dem Standard `0.2` s gilt
   das GPS als „± 100 ms“ und verliert gegen jede Internetquelle mit ± 5 ms
   (*Unsicherheit zu groß*). Mit falschem Offset *und* kleinem Delay wäre es dagegen ein
   **Falseticker**: es widerspricht den anderen und wird verworfen.

Erst beides zusammen – richtiger Offset, passender Delay – macht das GPS konkurrenzfähig.
Bei funktionierendem Internet ist das optional; wichtig wird es, wenn das GPS bei einem
Ausfall übernehmen soll.

### GPS kalibrieren – im Dashboard

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/gps-calibration-dark.png">
  <img alt="GPS-Kalibrierassistent: gemessene Verspätung +56,99 ms, vorgeschlagener Offset 0,057 s und Delay 0,005 s, Diagramm der Differenz GPS minus Netzwerk" src="docs/screenshots/gps-calibration-light.png">
</picture>

Der Assistent auf der Seite **GPS** vergleicht laufend jede GPS-Messung mit den gerade
genutzten Netzwerkquellen (Median der Differenz, robuste Streuung) und schlägt vor:

- **Offset** = bisheriger Offset + gemessene Verspätung,
- **Delay** = etwa die sechsfache Streuung (mindestens 5 ms, höchstens 0,2 s),
- **Rolle**: automatisch, bevorzugt (`prefer`) oder nur beobachten (`noselect`).

Vorgehen: GPS mit Internetquellen **einige Stunden** mitlaufen lassen (ab 30 Minuten gibt es
einen vorläufigen Wert), dann **Vorschlag übernehmen**. chrony startet neu, die Abweichung im
Diagramm pendelt danach um 0 und das GPS wird *kombiniert* oder *ausgewählt*. Neu
kalibrieren nur nach einem Wechsel von Empfänger, USB-Port, Baudrate oder Firmware.

Ohne Dashboard geht es auch per Umgebung (`GPS_OFFSET`, `GPS_DELAY`, `GPS_SELECT`); den
Offset liest man dann mit `chronyc sourcestats` ab (Spalte *Offset* der Zeile `GPS`). Den
Vorschlag gibt es auch per API: `/api/gps/calibration?window=21600` (Zeitfenster in
Sekunden, `?seconds=` geht ebenso; ohne Angabe die letzten 24 h, `window=0` den ganzen Verlauf).

### GPS automatisch kalibrieren

Die Verspätung eines USB-GPS ist fest, aber nicht für immer: Firmware, USB-Port oder Baudrate
ändern sie. Damit du nicht daran denken musst, misst ntp-gui laufend weiter und kann den
Offset selbst nachstellen. Einstellung **GPS → Automatische Kalibrierung** (`GPS_AUTOCAL`):

| Modus | Was passiert |
|---|---|
| `off` | nichts – kein Vorschlag, keine Änderung |
| `suggest` (Standard) | Die Seite **GPS** zeigt einen Vorschlag, sobald er belastbar ist. Du übernimmst ihn per Klick. |
| `auto` | ntp-gui stellt den Offset selbst nach – behutsam, nach festen Regeln, mit Eintrag im Ereignisprotokoll |

Die Regeln sind bewusst vorsichtig – lieber eine Änderung zu wenig als eine falsche:

- **Genug Messdauer:** erst nach `GPS_AUTOCAL_MIN_HOURS` (Standard 6 h) gemeinsamer Messung
  von GPS und Netzwerkquellen. Mehrere Stunden glätten Tagesschwankungen der Netzlaufzeit.
  Nach jeder Offset-Änderung (auch von Hand) beginnt die Messung neu.
- **Vertrauenswürdige Referenz:** mindestens zwei genutzte Netzwerkquellen oder eine genutzte
  NTS-Quelle. Eine einzelne ungeschützte Quelle könnte selbst danebenliegen. Ohne
  Netzwerkquelle (Internet weg) passiert nichts.
- **Nur echte Abweichungen:** mindestens 1 ms und deutlich größer als die Messunsicherheit.
  Eine Korrektur in die Gegenrichtung der letzten braucht die doppelte Schwelle – so pendelt
  der Offset nicht hin und her.
- **Kleine Schritte:** höchstens eine Änderung je 24 h, jeweils höchstens
  `GPS_AUTOCAL_MAX_STEP_MS` (Standard 5 ms). Größere Abweichungen werden über mehrere Tage
  abgebaut. Den Delay verkleinert ntp-gui erst beim letzten Schritt – ein kleiner Delay
  macht das GPS für chrony attraktiver, das soll erst mit stimmendem Offset passieren.
- **Im Zweifel ein Mensch:** Streut die Messung über 25 ms oder liegt sie über 0,5 s daneben,
  stimmt etwas Grundsätzliches nicht (falsches Gerät, wackelige Leitung). Dann gibt es nur
  einen Vorschlag.

**Rücknahme:** Jede automatische Änderung steht mit Grund in der Tabelle auf der Seite **GPS**
und im Ereignisprotokoll. **Rückgängig** stellt den vorigen Offset wieder her
(`POST /api/gps/autocal/rollback`). Hast du den Offset seitdem von Hand geändert, verweigert
ntp-gui die Rücknahme, statt deine Änderung zu überschreiben. Eine übernommene Änderung
startet chronyd kurz neu. Mit `WEB_READONLY=true` ändert auch die Automatik nichts.

**Kein Schritt auf unbestätigter Grundlage:** Bevor die Automatik erneut stellt, prüft sie, ob
die letzte Änderung wirklich wirkt – der Offset in der laufenden `chrony.conf` muss stimmen und
das Neuladen erfolgreich gewesen sein. Ist das nicht belegbar (z. B. Neuladen fehlgeschlagen),
passiert nichts weiter, und der Grund steht auf der Seite **GPS**. Gemessen wird erst ab dem
Zeitpunkt, an dem die Änderung tatsächlich aktiv wurde.

### PPS zusätzlich nutzen

Empfänger mit PPS-Ausgang (GPS-HAT, Modul an einem GPIO, USB-Adapter mit DCD-Leitung)
liefern eine Sekundenflanke, die um Größenordnungen genauer ist als die NMEA-Sätze.

**GPS-HAT am Raspberry Pi vorbereiten:**

1. **Serielle Konsole abschalten.** Sonst schreiben Kernel und Login-Prompt auf die
   GPS-Leitung, und gpsd liest Unsinn. `sudo raspi-config` → *Interface Options* →
   *Serial Port* → Login-Shell über seriell: **Nein**, serielle Hardware: **Ja**. Das
   entfernt `console=serial0,115200` aus `/boot/firmware/cmdline.txt` (von Hand geht es
   auch).
2. **UART und PPS-Pin** in `/boot/firmware/config.txt` freischalten:
   ```
   enable_uart=1
   dtoverlay=pps-gpio,gpiopin=18
   ```
3. **Nur Pi 3/4:** Dort liegt auf den Header-Pins 8/10 standardmäßig der Mini-UART
   (`/dev/ttyS0`), dessen Takt an der CPU-Frequenz hängt; der gute UART (`/dev/ttyAMA0`)
   gehört Bluetooth. Mit
   ```
   dtoverlay=disable-bt
   ```
   in `config.txt` und `sudo systemctl disable hciuart` wechselt der Header auf
   `/dev/ttyAMA0` (Bluetooth ist dann aus). Beim **Pi 5** ist der Header-UART ohnehin
   `/dev/ttyAMA0`.
4. Neu starten.

Am einfachsten nimmst du danach **`/dev/serial0`**: Ist der UART wie oben eingeschaltet
(`enable_uart=1`), zeigt der Symlink auf den UART an den Header-Pins. Prüfe es mit
`ls -l /dev/serial0` – beim Pi 5 sollte dort `ttyAMA0` stehen; steht `ttyAMA10`, ist es der
Debug-Anschluss zwischen den HDMI-Buchsen und `enable_uart=1` fehlt noch. Docker löst ihn
beim Durchreichen auf:

```yaml
devices:
  - /dev/serial0:/dev/serial0
  - /dev/pps0:/dev/pps0
environment:
  GPS_ENABLE: "true"
  GPS_DEVICE: "/dev/serial0"
  GPS_PPS_DEVICE: "/dev/pps0"
```

Mit dem Hotplug-Block (`/dev:/dev`) braucht der Container die Regel für das echte Gerät:
`c 204:* rwm` für `ttyAMA0`, für den Mini-UART `ttyS0` zusätzlich `c 4:* rwm`.

chrony bekommt dann zwei Refclocks: `GPS` liefert die grobe Zeit (welche Sekunde),
`PPS` die exakte Flanke (`lock GPS`). Der VK-162 hat **kein** PPS. Ob Impulse wirklich
ankommen, zeigt die Seite **Hardware** live („Impulse kommen regelmäßig an“).

### Wenn der Refclock nicht anspringt

`chronyc sources` zeigt den GPS-Refclock als `#? GPS` (keine Samples) statt `#* GPS`:

| Symptom | Ursache |
|---|---|
| Dashboard: „gpsd antwortet nicht" | Gerät nicht durchgereicht (`--device`) oder falscher Pfad |
| GPS-Fix bleibt „kein Fix" | Antenne ohne Himmelssicht; ein Kaltstart dauert bis zu 15 Minuten |
| Fix vorhanden, Refclock trotzdem `#?` | gpsd schreibt in ein anderes SHM-Segment → `GPS_SHM_UNIT=2` probieren |
| PPS-Zeile fehlt in der chrony.conf | `GPS_PPS_DEVICE` zeigt auf ein Gerät, das im Container nicht existiert – der Container überspringt sie bewusst, weil chronyd sonst gar nicht startet |
| Offset konstant einige zehn bis hundert ms | normal bei USB – Kalibrierassistent auf der GPS-Seite |
| Zustand „Falseticker“ | Offset nicht kalibriert, aber Delay schon verkleinert – erst kalibrieren |

Ein Detail für Tests: **gpsd akzeptiert keine PTY- oder TCP-Quellen als Zeitreferenz**
(`ntpshm_alloc: sourcetype ... not using for NTP`). Ein per `socat` simulierter Empfänger
liefert also Position und Satelliten, aber niemals Samples für chrony – dafür braucht es
ein echtes serielles bzw. USB-Gerät.

## Uhrqualität: Temperatur, Schaltsekunden, Vollbild-Uhr

Die Seite **Uhrqualität** zeigt, was die Uhr deines Servers langfristig beeinflusst:

- **Temperatur und Frequenz:** Der Quarz der Systemuhr läuft je nach Temperatur etwas schneller
  oder langsamer. ntp-gui speichert zu jedem Messpunkt die Temperatur und zeigt sie als
  Streudiagramm gegen chronys Frequenzfehler. Sensoren werden automatisch gefunden (Raspberry Pi
  `cpu-thermal`, PC `x86_pkg_temp`/`k10temp`/`coretemp`, DS18B20 am 1-Wire-Bus); welchen ntp-gui
  nutzt, legst du mit `TEMP_SENSOR` fest (`auto`, `off` oder eine Kennung aus dem Hardware-Check,
  z. B. `w1:28-0316a2794bff`). Für eine Aussage braucht es 1–3 Tage mit Tag-/Nacht-Wechsel. In
  VMs gibt es meist keinen Sensor. Einen Temperaturausgleich schlägt ntp-gui erst ab 1.5 vor.
- **Schaltsekunden:** TAI−UTC, letzte Schaltsekunde und wie lange die `leap-seconds.list` im
  Image noch gilt – für die Datei, die chrony wirklich liest. Läuft sie in weniger als 60 Tagen
  ab, meldet ntp-gui „Image zu alt“ – dann `docker compose pull && docker compose up -d`.
- **Vollbild-Uhr:** `http://<server>:8080/clock` (Uhr-Symbol oben rechts im Dashboard) zeigt
  eine große, mit dem Server abgeglichene Uhr (Ortszeit, UTC, Datum, Kalenderwoche, Status) –
  ideal für Wandmonitor oder altes Tablet. Rotlicht-Modus und Vollbild (Taste F) inklusive. Der
  Abgleich läuft wie bei NTP mit vier Zeitstempeln; die Uhr des Tablets ist egal.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/clock-dark.png">
  <img alt="Vollbild-Uhr: große Ortszeit, UTC, Datum, Kalenderwoche und Statusband" src="docs/screenshots/clock-light.png">
</picture>

Mit `CLOCK_PUBLIC=true` sind `/clock` und `/api/v1/time` ohne Anmeldung erreichbar (nur Zeit,
Ampel, Genauigkeit und Art der Quelle – keine Namen, Adressen oder Einstellungen). Auch dann
antwortet ntp-gui ohne Anmeldung nur über IP-Adressen, einteilige oder lokale Namen (`*.local`,
`*.lan`, `*.home.arpa`, `*.internal`) und `WEB_ALLOWED_HOSTS` – Schutz vor DNS-Rebinding. Für
einen Wandmonitor, der den Server über einen eigenen DNS-Namen aufruft, diesen Namen in
`WEB_ALLOWED_HOSTS` eintragen. Nicht einschalten, wenn das Dashboard aus dem Internet
erreichbar ist.

Neue API-Endpunkte (lesend): `/api/v1/temperature`, `/api/v1/leap`, `/api/v1/time`. Metriken:
`ntpgui_temperature_celsius`, `ntpgui_leapseconds_list_days_left`, `ntpgui_tai_utc_offset_seconds`.

## Benachrichtigungen

Auf der Seite **Benachrichtigungen** legst du Kanäle an. Jeder Kanal hat eigene Regeln: ab
welcher Stufe (Warnung, Kritisch …) und für welche Arten (GPS, PPS, Dienste, Zeitquellen,
Clients, DNS …) er Nachrichten bekommt. **Ohne angelegten Kanal verlässt nichts den Server.**
Die Kachel **Dienste** der Übersicht zeigt, ob die Zustellung klappt.

| Kanal | Adresse | Thema/Schlüssel | Token |
|---|---|---|---|
| ntfy | `https://ntfy.sh` oder dein ntfy-Server (`https://ntfy.sh/mein-thema` geht auch) | Thema (z. B. `zeitserver-8f3k`) | optional (`tk_…`) |
| Gotify | `http://gotify.lan` | – | App-Token (Pflicht) |
| Webhook | beliebige URL, z. B. Home-Assistant-Webhook | – | optional: Schlüssel für die Signatur |
| Apprise-API | `http://apprise:8000` | Schlüssel einer gespeicherten Konfiguration | oder direkt Apprise-URLs |

- **Entprellen:** dieselbe Meldung höchstens einmal je N Minuten; „behoben“ kommt mit Dauer,
  „Kritisch“ immer sofort.
- **Wiederholung:** nach 30 s, 2 min und 10 min, danach verworfen (steht im Ereignisprotokoll).
- **Limit:** standardmäßig höchstens 30 Nachrichten je Stunde und Kanal.
- **Link:** Mit `NOTIFY_DASHBOARD_URL=http://zeitserver.lan:8080/` enthält jede Nachricht einen
  Link auf die passende Seite.

Für ntfy, Gotify und Apprise nur die Server-Adresse eintragen (ohne `?…`).

**Sicherheit:** Kanäle anlegen darf nur, wer das Verwaltungsrecht hat (Passwort oder
API-Schlüssel „lesen und verwalten“). Damit kann nur ein Admin den Server Anfragen an beliebige
Adressen schicken lassen (SSRF) – und Admins können die Zeitversorgung ohnehin umstellen.
Erlaubt sind nur `http`/`https`. Weiterleitungen werden nicht befolgt, Proxys aus der Umgebung
nicht benutzt, Gesamtfrist 10 s, Antwort höchstens 64 KiB. Tokens gehen nur über `https://`
hinaus oder über `http://` an Adressen im eigenen Netz (private IP, `*.lan`, `*.local`,
`*.home.arpa`, Name ohne Punkt wie `apprise`). Änderst du Ziel oder Art eines Kanals, musst du
das Token neu eingeben. Tokens liegen in der Datenbank im Volume, werden im Dashboard und in der
API nie wieder angezeigt und landen nie im Diagnosepaket; Adressen mit Pfad zeigen Dashboard
und API nur gekürzt. Jede Nachricht läuft durch den Datenschutzfilter: keine Koordinaten, keine
öffentlichen IP-Adressen, keine eigenen Hostnamen, keine Client-Namen.

**Webhook-Format:** `POST` mit JSON-Feldern `source` („ntp-gui“), `version` (1), `title`,
`text`, `level` (info/warn/crit), `kind`, `time` (Unix-Zeit), `resolved`, `duration_s` (bei
„behoben“), optional `link`, `suppressed`, `event_id` und `test`. Ist ein Signatur-Schlüssel
gesetzt, kommt der Header `X-NTPGUI-Signature: sha256=<hex>` mit: HMAC-SHA256 über die
unveränderten Bytes des Bodys.

Testvektor: Schlüssel `geheim`, Body `{"source":"ntp-gui","test":true}` →

```bash
printf '%s' '{"source":"ntp-gui","test":true}' | openssl dgst -sha256 -hmac geheim
# sha256=aa6b045120327114063405a2160f1f0e2257424dfb0c0a0728d2881de0104c6e
```

**E-Mail, Telegram, Matrix & Co. über Apprise** (optionaler Zusatz-Container in der
Compose-Datei):

```yaml
services:
  ntp-gui:
    # … wie bisher …
  # apprise:                        # optional: leitet Benachrichtigungen weiter
  #   image: caronc/apprise:latest
  #   restart: unless-stopped
  #   # kein ports: nötig – ntp-gui erreicht ihn im Compose-Netz als http://apprise:8000
  #   volumes:
  #     - apprise-config:/config
# volumes:
#   apprise-config:
```

In der Apprise-Oberfläche unter einem Schlüssel wie `ntp` die Ziele speichern (z. B.
`mailto://user:pass@mail.example.org`, `tgram://bottoken/chatid`). In ntp-gui dann einen Kanal
„Apprise-API“ mit Adresse `http://apprise:8000` und Schlüssel `ntp` anlegen. So liegen
E-Mail-Passwörter nur bei Apprise. Läuft ntp-gui mit `network_mode: host`, erreicht es den
Apprise-Container nicht über den Dienstnamen – dann Apprise einen Port geben
(`ports: ["127.0.0.1:8000:8000"]`) und `http://127.0.0.1:8000` eintragen.

Zustand für Monitoring (Lese-Schlüssel genügt): `GET /api/v1/notify/status` – je Kanal nur
Kennung, Art und Zustellstand.

## Diagnose & Fehlersuche

Die Seite **Diagnose** bündelt alles, was du für die Fehlersuche brauchst – ohne
`docker logs` und ohne Shell im Container.

**Log.** Der Supervisor schreibt seine Ausgabe zusätzlich nach `/run/ntp-gui/ntp-gui.log`
(ab 2 MB wird sie zu `ntp-gui.log.1`; `docker logs` bekommt weiter alles). Die Seite zeigt die
letzten Zeilen, filtert nach Text und nach *nur Warnungen* / *nur Fehler*. Das Log bleibt auf
dem Server und wird darum nicht gefiltert. Abschalten lässt sich die Kopie mit
`NTPGUI_LOGTEE=0`.

**Ereignisprotokoll.** Was passiert ist, in einer Zeitleiste: Neustarts und Ausfälle von
Diensten, angewendete Einstellungen (nur die Namen der Felder, nie die Werte), Wechsel der
ausgewählten Zeitquelle, GPS-Fix verloren/wieder da, PPS-Impulse ausgeblieben/wieder da,
GPS-Gerät abgezogen/neu angesteckt, Zertifikatswechsel, Kalibrierung. Ein Zustand zählt erst
als gewechselt, wenn er zweimal hintereinander gemessen wurde – ein kurzes Flackern erzeugt
kein Ereignis. Gespeichert in `ntp-gui.db` für 90 Tage (höchstens 50 000 Einträge); API:
`/api/events?since=&kinds=&level=`.

**Diagnosepaket.** Ein Klick erzeugt ein `.tar.gz` für einen Fehlerbericht: Version und
Plattform, die erzeugte `chrony.conf`/`ptp4l.conf`, die Ausgaben von `chronyc` (tracking,
sources, sourcestats, selectdata, ntpdata, serverstats, activity, authdata), GPS- und
PTP-Zustand, Hardware-Check, Dienste, die Ereignisse der letzten 7 Tage, die letzten 2000
Log-Zeilen, die Einstellungen ohne Zugangsdaten und vom Verlauf der letzten 24 h nur
Kennzahlen. Die Client-Liste und eine Aufzeichnung kommen nur hinein, wenn du sie ankreuzt.
**Vorschau** zeigt vorher genau den Inhalt, der im Paket landet, und was der Filter entfernt
hat. Das Paket wird **nur heruntergeladen – hochgeladen wird nichts**. Ob und wo du es
teilst, entscheidest du.

### Was der Datenschutzfilter entfernt – und warum

Alles, was die Instanz verlässt, läuft durch **einen** Filter (`app/egress.py`). Sein Ziel:
Aus dem Paket darf sich **kein Standort ablesen lassen** und kein Gerät wiedererkennen.
Ein GPS-Zeitserver kennt seine Position auf wenige Meter genau – das gehört in keinen
Fehlerbericht.

| Entfernt / ersetzt | Warum |
|---|---|
| Koordinaten, Höhe – auch in NMEA-Sätzen, gpsd-Meldungen und freiem Text | verraten den Standort direkt |
| Geschwindigkeit, Kurs, Steigrate, **Azimut und Elevation der Satelliten** | Aus den Satellitenwinkeln zu einer bekannten Uhrzeit lässt sich die Position zurückrechnen |
| **Liste der einzelnen Satelliten** (Nummern) | Welche Satelliten zu einer Uhrzeit sichtbar sind, grenzt die Region ein. Übrig bleiben Summen je System: gesehen, genutzt, mittlere und höchste Signalstärke |
| **Laufzeiten** zu Servern (Root/Peer delay, Fehlerschranken, RTT – auch in Aufzeichnungen) → auf 10 ms gerundet | Viele genaue Laufzeiten zu bekannten Servern erlauben eine grobe Ortung |
| Seriennummern (USB, DMI, `/dev/serial/by-id/…`, `iSerial`, `S/N`), lange Hex-Kennungen (machine-id, Container-ID) | machen ein Gerät eindeutig wiedererkennbar |
| MAC-Adressen und PTP-Clock-IDs (aus der MAC gebildet) | ebenso; außerdem verrät der Herstellerteil die Hardware |
| Öffentliche IP-Adressen (auch in chrony-Referenz-IDs und Reverse-DNS-Namen wie `ip-1-2-3-4`) → `<öffentliche-IP>` | verorten den Anschluss bis auf Stadt oder Provider |
| Private Adressen → stabile Pseudonyme `client-07` | Im Paket bleibt erkennbar, *dass* es dasselbe Gerät ist, aber nicht welches |
| Eigene Hostnamen, Domains, per Reverse-DNS aufgelöste Gerätenamen von Clients und Quellen, Zertifikatsangaben (Name, Ort, Organisation), E-Mail-Adressen, Zugangsdaten | Eine eigene Domain oder ein Gerätename führt direkt zu dir |
| Eigener Dashboard-Titel, Zeitzonen-Namen (nur der UTC-Versatz bleibt) | Titel und Zeitzone engen den Ort ein |

Lesbar bleiben die bekannten öffentlichen Zeitserver (PTB, Cloudflare, Netnod,
`*.pool.ntp.org` …), Netzbereiche wie `192.168.0.0/16`, Gerätenamen wie `ttyACM0` und
Dateinamen wie `chrony.conf` – ohne sie wäre der Bericht nutzlos.

Nach dem Filtern prüfen **zwei Schlussprüfungen** den Inhalt und jede Datei im Paket: eine
mit den Regeln des Filters (was der Filter noch ändern würde, ist ein Fund) und eine davon
unabhängige, bewusst einfache Suche auf den fertigen Bytes. In Log und Aufzeichnung wird eine
beanstandete Zeile durch `[Zeile entfernt – Datenschutz]` ersetzt – so kann niemand den Export
blockieren, indem er seltsamen Text ins Log schreibt. Findet danach noch eine Prüfung etwas,
wird **gar nichts** exportiert – die Fehlermeldung nennt nur Art und Stelle des Fundes, nie
den Inhalt. Im Paket liegt eine
`MANIFEST.txt`, die auf Deutsch auflistet, was drin ist und was aus welchem Grund wie oft
entfernt wurde.

### Aufzeichnung für Entwickler

Manche Fehler zeigen sich nur mit genau deiner Hardware. Dafür kann ntp-gui für eine Weile
mitschneiden, was es von `chronyc`, `pmc`, `ethtool` und gpsd zu sehen bekommt
(**Diagnose → Aufzeichnung**, 1 bis 60 Minuten, höchstens 20 MB; die letzten drei
Aufzeichnungen bleiben unter `/run/ntp-gui`). Ins Diagnosepaket kommt sie nur, wenn du es
ankreuzt – gefiltert wie alles andere, also ohne Position und Satellitenwinkel.

Entwickler spielen eine Aufzeichnung ohne echte Hardware wieder ab:

```bash
NTPGUI_REPLAY=/pfad/recording.jsonl NTPGUI_REPLAY_SPEED=10 …   # Dashboard zeigt die aufgezeichneten Daten
python3 app/providers.py replay-info /pfad/recording.jsonl      # Inhalt einer Aufzeichnung
```

## Konfiguration

Alle Werte lassen sich **im Dashboard** einstellen (siehe [Einstellungen im Dashboard](#einstellungen-im-dashboard));
die Umgebungsvariablen unten setzen die Startwerte. Daraus entsteht beim Start bzw. nach
dem Speichern eine `chrony.conf`, die unter `/api/config` einsehbar ist.

### NTP

| Variable | Default | Bedeutung |
|---|---|---|
| `NTP_POOLS` | `pool.ntp.org` | Pools, kommagetrennt |
| `NTP_SERVERS` | – | Einzelne Server, kommagetrennt |
| `NTP_NTS_SERVERS` | – | Server mit NTS, kommagetrennt (z. B. `ptbtime1.ptb.de`) |
| `NTP_PEERS` | – | Symmetrische Peers (z. B. ein zweiter Zeitserver im Cluster) |
| `NTP_MINSOURCES` | `1` | So viele Quellen müssen übereinstimmen, bevor die Uhr gestellt wird |
| `NTP_SERVER_OPTIONS` | `iburst` | Optionen hinter jedem Server/Pool (z. B. `iburst minpoll 4`) |
| `NTP_POOL_MAXSOURCES` | `4` | Quellen je Pool |
| `ALLOW_NETWORKS` | alle privaten Netze | Wer die Zeit abfragen darf |
| `DENY_NETWORKS` | – | Ausnahmen dazu |
| `SERVE_UNSYNCED` | `true` | Zeit auch ohne Uplink ausliefern (Inselbetrieb) |
| `LOCAL_STRATUM` | `10` | Stratum im Inselbetrieb |
| `LOCAL_ORPHAN` | `false` | Orphan-Modus: zwei ntp-gui-Server, die sich gegenseitig als Quelle haben, einigen sich ohne Internet auf **eine** Inselzeit (der mit der kleinsten Referenz-ID gibt sie vor). Wirkt nur mit `SERVE_UNSYNCED` |
| `NTP_RATELIMIT` | `false` | Anfragen je Client begrenzen (`ratelimit`) |
| `LEAPSECLIST` | `/usr/share/zoneinfo/leap-seconds.list` | Schaltsekunden-Liste der IERS aus tzdata (`leapseclist`); eigene Liste unter `/config/` möglich, leer schaltet die Ankündigung ab |
| `LEAPSECTZ` | – | Nur für eigene Images mit `right/`-Zeitzonen (`leapsectz`). Bis 1.3.0 Standard `right/UTC`; fehlt die Zone, gilt die Liste |
| `NTS_NOCERTTIMECHECK` | `true` | Zertifikatszeit beim ersten NTS-Abgleich nicht prüfen |
| `NTS_SERVER` | `false` | Selbst NTS-Server sein, siehe [NTS-Server für das LAN](#nts-server-für-das-lan) |
| `NTS_SERVER_CERT` / `NTS_SERVER_KEY` | `/config/nts.crt` / `/config/nts.key` | Zertifikat (PEM, am besten fullchain) und Schlüssel. Nur Pfade unter `/config`, `/certs` oder `/etc/letsencrypt` |
| `NTS_SERVER_NAME` | – | Name, unter dem Clients den Server erreichen; muss im Zertifikat stehen. Wird als `ntsntpserver` an die Clients gegeben – wichtig hinter einem Reverse Proxy |
| `NTS_SERVER_PORT` | `4460` | TCP-Port für NTS-KE (`ntsport`). Nur ändern, wenn ein Proxy außen 4460 belegt |
| `NTP_PORT` | `123` | NTP-Port |
| `BIND_ADDRESS` | – | Auf eine Adresse beschränken |
| `NTP_HW_TIMESTAMP` | `false` | Hardware-Zeitstempel für NTP (`hwtimestamp`) |
| `NTP_HW_TIMESTAMP_INTERFACE` | `*` | Interface dafür; `*` = alle, die es können |
| `DISABLE_CLOCK_CONTROL` | `auto` | `true` erzwingt `-x` (Uhr wird nie gestellt). Bei `auto` und bei `false` prüft der Container `CAP_SYS_TIME` und ergänzt `-x` nur, wenn die Capability fehlt |
| `MAKESTEP` | `1.0 3` | `makestep`-Parameter |
| `MAXUPDATESKEW` | `100.0` | `maxupdateskew` in ppm |
| `EXTRA_CHRONY_CONF` | – | Beliebige zusätzliche Zeilen (`\n` als Trenner) |
| `CHRONY_LOG` | – | Inhalt einer `log`-Zeile, z. B. `measurements statistics tracking` (Logs unter `/var/log/chrony`) |
| `CLIENTLOGLIMIT` | `10000000` | Speicher (Bytes) für die Client-Liste von chronyd |
| `CUSTOM_CHRONY_CONF` | `/config/chrony.conf` | Pfad einer eigenen chrony.conf, die – falls vorhanden – die erzeugte ersetzt |

Reicht das nicht, mountet man eine eigene Datei nach `/config/chrony.conf` – die wird dann
unverändert übernommen und alle NTP-Variablen ignoriert.

### GPS

| Variable | Default | Bedeutung |
|---|---|---|
| `GPS_ENABLE` | `false` | gpsd starten und Refclock in die chrony.conf schreiben |
| `GPS_DEVICE` | `/dev/ttyACM0` | Gerätepfad des Empfängers |
| `GPS_SPEED` | – | Feste Baudrate (nur bei seriellen Empfängern nötig) |
| `GPS_OFFSET` | `0.0` | Konstanter Zeitversatz in Sekunden (Kalibrierung) |
| `GPS_SELECT` | `auto` | Rolle in chrony: `auto`, `prefer` oder `noselect` |
| `GPS_REFID` | `GPS` | Name des Refclocks in `chronyc sources` |
| `GPS_SHM_UNIT` | `0` | SHM-Segment, über das gpsd die Zeit übergibt |
| `GPS_POLL` / `GPS_FILTER` | `3` / `3` | Poll-Intervall (2^n s) und Medianfilter |
| `GPS_DELAY` / `GPS_PRECISION` | `0.2` / `1e-1` | Angenommene Verzögerung und Auflösung |
| `GPS_PPS_DEVICE` | – | PPS-Gerät, z. B. `/dev/pps0` |
| `GPS_PPS_POLL` | `3` | Poll-Intervall des PPS-Refclocks (2^n s) |
| `GPS_PPS_OPTIONS` | – | Zusätzliche Optionen für die PPS-Refclock-Zeile |
| `GPS_PPS_SHM` | `false` | PPS stattdessen über gpsd (SHM-Segment `GPS_PPS_SHM_UNIT`, Standard `1`) |
| `GPS_WAIT_SECONDS` | `10` | So lange auf das Gerät warten (USB taucht nach dem Boot verzögert auf) |
| `GPS_SHOW_POSITION` | `false` | Koordinaten im Dashboard anzeigen |
| `GPS_AUTOCAL` | `suggest` | Automatische Kalibrierung: `off`, `suggest` (vorschlagen) oder `auto`, siehe [GPS automatisch kalibrieren](#gps-automatisch-kalibrieren) |
| `GPS_AUTOCAL_MAX_STEP_MS` | `5.0` | Größter automatischer Kalibrierschritt in ms (0,1–50) |
| `GPS_AUTOCAL_MIN_HOURS` | `6.0` | Mindest-Messdauer in Stunden, bevor vorgeschlagen oder geändert wird (0,5–168) |
| `GPS_REFCLOCK_OPTIONS` | – | Zusätzliche chrony-Refclock-Optionen |
| `GPS_OPTIONS` | – | Zusätzliche Argumente für gpsd (Wortliste, z. B. `-b` für nur lesen) |
| `GPSD_HOST` / `GPSD_PORT` | `127.0.0.1` / `2947` | Wo das Dashboard gpsd abfragt |

### PTP

PTP lohnt sich nur, wenn alle Voraussetzungen erfüllt sind – sonst ist NTP genauso gut:

| Voraussetzung | Warum |
|---|---|
| **Gute Referenz** – GPS **mit PPS** | PTP verteilt nur so genau, wie die Quelle ist. Mit Internet-NTP als Quelle verteilt man Millisekunden-Fehler auf Nanosekunden genau. |
| **NIC mit Hardware-Zeitstempeln** | z. B. Intel i210/i211/i225/i226, Raspberry Pi 5/CM4. Virtuelle NICs (virtio, Hyper-V, VMware) haben keine – in VMs nur Software-PTP. |
| **Host-Netzwerk** (`network_mode: host`) | PTP braucht Multicast und die echte Netzwerkkarte; über die Docker-Bridge geht es nicht. |
| **`NET_ADMIN`, `NET_RAW`** und `/dev/ptp0` | um Hardware-Zeitstempel einzuschalten und die PTP-Uhr der Karte zu lesen. |
| **Netzwerk** | Jeder einfache Switch kostet Mikrosekunden. Für Nanosekunden: PTP-fähige Switches (Transparent/Boundary Clock) oder direkte Verbindung. |
| **Clients, die PTP sprechen** | Linux (linuxptp), viele Audio-/Video- und Netzwerkgeräte. Windows nur eingeschränkt, macOS nicht – die bleiben bei NTP. |

Die Seite **PTP** im Dashboard prüft das live: Host-Netzwerk, Interface, Hardware-Zeitstempel
(`ethtool -T`) und PTP-Uhr je Netzwerkkarte. Von Hand:

```bash
ethtool -T eth0   # "hardware-transmit"/"hardware-receive" und "PTP Hardware Clock: 0"
```

```bash
docker compose -f docker-compose.ptp.yml up -d
```

| Variable | Default | Bedeutung |
|---|---|---|
| `PTP_ENABLE` | `false` | ptp4l starten |
| `PTP_INTERFACE` | – | Interface, z. B. `eth0` (Pflicht, wenn aktiviert) |
| `PTP_MODE` | `auto` | `auto` (BMCA entscheidet), `master` (Grandmaster), `slave` |
| `PTP_PROFILE` | `default` | `default` (IEEE 1588), `aes67` (Audio über IP) oder `gptp` (IEEE 802.1AS) – siehe unten |
| `PTP_DOMAIN` | `0` | PTP-Domain |
| `PTP_TRANSPORT` | `UDPv4` | `UDPv4`, `UDPv6` oder `L2` |
| `PTP_TIME_STAMPING` | `hardware` | `hardware` oder `software` |
| `PTP_DELAY_MECHANISM` | `E2E` | `E2E`, `P2P` oder `Auto` |
| `PTP_PRIORITY1` / `PTP_PRIORITY2` | `128` | BMCA-Priorität (kleiner = eher Grandmaster) |
| `PTP_CLOCK_CLASS` | `248` | Startwert der Uhrqualität; als Grandmaster setzt ntp-gui sie danach selbst (siehe unten) |
| `PTP_LOG_SYNC_INTERVAL` | `-3` | Sync-Intervall als 2^n s (−3 = 8 pro Sekunde) |
| `PTP_LOG_ANNOUNCE_INTERVAL` | `1` | Announce-Intervall als 2^n s |
| `PTP_ANNOUNCE_RECEIPT_TIMEOUT` | `3` | So viele Announce-Intervalle ohne Nachricht, bis der Grandmaster als weg gilt |
| `PTP_LOG_MIN_DELAY_REQ_INTERVAL` | `-3` | Delay-Request-Intervall als 2^n s |
| `PTP_SUMMARY_INTERVAL` | `4` | Wie oft ptp4l Kennzahlen ins Log schreibt (2^n s) |
| `PHC2SYS_ENABLE` | `false` | Systemuhr und PTP-Hardwareuhr koppeln |
| `PHC2SYS_OPTIONS` | automatisch | Leer = passend zur Rolle: Grandmaster `-a -rr -m`, sonst `-a -r -m`. Der alte Standard `-a -r -m` (bis 1.1.0) gilt als Grandmaster ebenfalls als „automatisch“ und wird zu `-a -rr -m` (HINWEIS im Log). Andere eigene Optionen, mit denen phc2sys als Grandmaster die Systemuhr stellen würde, laufen wie angegeben, erzeugen aber eine WARNUNG im Log und im Dashboard |
| `PHC_REFCLOCK` | – | PTP-Uhr als chrony-Referenz, z. B. `/dev/ptp0` (PTP→NTP-Brücke). **Nur als PTP-Slave** (`PTP_MODE` `slave` oder `auto`), nicht mit `master`: Dort stellt phc2sys die PTP-Uhr nach der Systemuhr, chrony bekäme seine eigene Zeit zurück. ntp-gui lässt die Refclock-Zeile dann weg und schreibt eine WARNUNG ins Log |
| `PHC_REFCLOCK_OPTIONS` | `poll 0 dpoll -2 offset 0 stratum 1` | Optionen der PHC-Refclock-Zeile |
| `EXTRA_PTP4L_CONF` | – | Zusätzliche Zeilen im `[global]`-Abschnitt |
| `CUSTOM_PTP4L_CONF` | `/config/ptp4l.conf` | Pfad einer eigenen ptp4l.conf, die – falls vorhanden – die erzeugte ersetzt |
| `PTP_UTC_OFFSET` | `37` | Expertenwert, nur per Umgebung: TAI−UTC in Sekunden (0–100), den ein Grandmaster als `currentUtcOffset` ankündigt; weicht er von 37 ab, steht er auch als `utc_offset` in der ptp4l.conf. Erst nach einer neuen Schaltsekunde ändern |
| `PTP_HOLDOVER_SECONDS` | `900` | Expertenwert, nur per Umgebung: So lange (0–86400 s, `0` = kein Holdover) kündigt ein Grandmaster nach dem letzten stabilen GPS+PPS-Lock noch `clockClass 7` (Holdover) an |
| `PTP_TX_TIMESTAMP_TIMEOUT` | `10` | Expertenwert, nur per Umgebung: Wartezeit in ms (1–10000) auf den Sende-Zeitstempel der Karte (ptp4l `tx_timestamp_timeout`). Erhöhen, wenn ptp4l „timed out while polling for tx timestamp“ meldet |
| `PTP_UDS_ADDRESS` | `/var/run/ptp4l` | Expertenwert, nur per Umgebung: Management-Socket von ptp4l (`uds_address`; phc2sys bekommt ihn per `-z`, pmc per `-s`). Nur ein absoluter Pfad ohne Leer- und Sonderzeichen |

Ungültige Expertenwerte (außerhalb des Bereichs, kein gültiger Pfad) ersetzt ntp-gui durch den
Standard und schreibt eine WARNUNG ins Log.

Auch hier lässt sich alternativ eine eigene `/config/ptp4l.conf` mounten.

**Wer stellt welche Uhr?** Auf einem Rechner mit PTP gibt es zwei Uhren: die Systemuhr und
die PTP-Hardwareuhr (PHC) der Netzwerkkarte. `phc2sys` verbindet sie – die Richtung hängt
von der Rolle ab, und es darf immer nur **ein** Regler an der Systemuhr drehen:

| Rolle | phc2sys | chronyd | Zeitfluss |
|---|---|---|---|
| **Grandmaster** (`master`) | `-a -rr` | regelt weiter | GPS/NTP → chronyd → Systemuhr → phc2sys → PHC → ptp4l → PTP-Clients |
| **Slave** (`slave`, `auto`) | `-a -r` | läuft mit `-x` | PTP-Grandmaster → ptp4l → PHC → phc2sys → Systemuhr → chronyd → NTP-Clients |

In der Rolle `auto` behandelt ntp-gui den Container wie einen Slave. Das Dashboard warnt
deshalb, wenn `auto` mit Software-Zeitstempeln läuft oder phc2sys dabei die Systemuhr stellt:
Soll der Container GPS-/NTP-Zeit per PTP verteilen, `PTP_MODE=master` wählen.

**Grandmaster mit GPS:** chronyd stellt die Systemuhr nach GPS + PPS, `phc2sys -a -rr`
überträgt sie auf die Netzwerkkarte, ptp4l verteilt sie. Damit die Clients wissen, wie gut
diese Zeit ist, passt ntp-gui die Angaben im PTP-Announce laufend an den Zustand von chrony
an (`GRANDMASTER_SETTINGS_NP`): Mit stabilem GPS + PPS kündigt der Grandmaster
`clockClass 6` und `timeSource GPS` an. Nur mit NMEA (USB-GPS ohne PPS) meldet er zwar
`timeSource GPS`, bleibt aber bei `clockClass 248` mit grober `clockAccuracy`. Fällt
GPS + PPS weg, während chrony synchron bleibt, meldet er noch `PTP_HOLDOVER_SECONDS` lang
(Standard 900 s) `clockClass 7` (Holdover: die Uhr läuft mit der gelernten Frequenz weiter),
danach wieder 248. Hat chrony nur Internet-NTP als Quelle, kündigt er `timeSource NTP`
(`0x50`) mit `clockClass 248` an; ohne Synchronisation 248 und „interner Oszillator“. Ohne
eingeschaltetes phc2sys läuft die PHC frei – das Dashboard warnt dann.

**Profile:**

| Profil | Wofür | Was es setzt |
|---|---|---|
| `default` | IEEE 1588 Standard, Labor, Linux-Clients | nichts |
| `aes67` | Audio über IP: AES67, Ravenna, **Dante nur im AES67-Modus** | UDPv4, E2E, Sync 2^−3 s, Announce 2^1 s, Timeout 3, DSCP 46 |
| `gptp` | IEEE 802.1AS (AVB/TSN, Automotive) | Layer 2, P2P, Priorität 248, Announce 2^0 s und weitere Werte aus linuxptp `gPTP.cfg` |

Ein Profil setzt nur Felder, die noch auf ihrem Standard stehen – was du ausdrücklich
änderst, gewinnt. Der wirksame Wert gilt überall: Mit `gptp` nutzt ptp4l Layer 2, auch wenn
`PTP_TRANSPORT` auf dem Standard `UDPv4` steht – die PTP-Seite zeigt dann `L2`, und die
Hardware-Prüfung verlangt `NET_RAW`.

**PTP → NTP-Brücke:** Läuft der Container als PTP-Slave, kann chrony die PTP-Hardwareuhr
direkt als Referenz benutzen und die Zeit als ganz normaler NTP-Server ins LAN geben:

```yaml
environment:
  PTP_ENABLE: "true"
  PTP_INTERFACE: "eth0"
  PTP_MODE: "slave"
  PHC_REFCLOCK: "/dev/ptp0"       # chrony: refclock PHC /dev/ptp0
  PHC2SYS_ENABLE: "true"
```

In dieser Kombination stellt **phc2sys** die Systemuhr (`-a -r`), und chronyd läuft
automatisch mit `-x` – zwei Regler auf derselben Uhr würden sich sonst gegenseitig die
Frequenzkorrekturen überschreiben. chronyd bleibt dabei voller NTP-Server; der
PHC-Refclock dient ihm als Referenz für Stratum und Statistik.

### Web

| Variable | Default | Bedeutung |
|---|---|---|
| `WEB_PORT` / `WEB_BIND` | `8080` / `0.0.0.0` | Adresse des Dashboards |
| `WEB_TITLE` | `NTP / PTP Time Server` | Überschrift |
| `WEB_USER` / `WEB_PASSWORD` | – | Beide gesetzt ⇒ HTTP Basic Auth (alternativ Passwort im Dashboard setzen) |
| `WEB_ALLOWED_HOSTS` | – | Weitere Namen, unter denen das Dashboard **ohne Passwort** antworten darf, kommagetrennt; `*.example.org` für alle Unternamen, `*` schaltet die Prüfung ab. Siehe [Schutz vor DNS-Rebinding](#schutz-vor-dns-rebinding) |
| `WEB_READONLY` | `false` | Einstellungen im Dashboard sperren |
| `WEB_REFRESH_SECONDS` | `5` | Aktualisierungsintervall im Browser |
| `HISTORY_INTERVAL` | `10` | Messintervall des Verlaufs in Sekunden |
| `HISTORY_DAYS` | `30` | So viele Tage hält der Verlauf (SQLite, `ntp-gui.db`; 1–3650). Neue Punkte werden gesammelt und alle 5 Minuten sowie beim Stoppen geschrieben – das schont SD-Karten |
| `HISTORY_SIZE` | – | Nur wenn gesetzt: harte Obergrenze an Messpunkten (wie bis 1.2, z. B. `8640` = 24 h bei 10 s) |
| `WEB_ACCESS_LOG` | `false` | Zugriffe protokollieren |
| `NOTIFY_DASHBOARD_URL` | – | Adresse des Dashboards für Links in [Benachrichtigungen](#benachrichtigungen) (nur `http`/`https`, ohne Benutzer/Passwort) |
| `TEMP_SENSOR` | `auto` | Temperatursensor für die Seite [Uhrqualität](#uhrqualität-temperatur-schaltsekunden-vollbild-uhr) (`auto`, `off` oder Kennung aus dem Hardware-Check) |
| `CLOCK_PUBLIC` | `false` | `true` = `/clock` und `/api/v1/time` ohne Anmeldung (nur Zeit und Status, Schutz vor DNS-Rebinding bleibt). Nicht einschalten, wenn das Dashboard aus dem Internet erreichbar ist |
| `UPDATE_CHECK` | `false` | Einmal am Tag bei GitHub nach einer neuen Version fragen, siehe [Update-Hinweis](#update-hinweis-opt-in) |

Nur per Umgebung (sie betreffen den Start selbst oder sind Expertenwerte): `WEB_PORT`,
`WEB_BIND`, `WEB_READONLY`, `WEB_USER`/`WEB_PASSWORD`, `WEB_ALLOWED_HOSTS`, `WEB_ACCESS_LOG`, `HISTORY_SIZE`,
`HISTORY_DAYS`, `NTPGUI_LOGTEE`, `NTPGUI_REPLAY`/`NTPGUI_REPLAY_SPEED`,
`DISABLE_CLOCK_CONTROL`, `EXTRA_CHRONY_CONF`, `EXTRA_PTP4L_CONF`, `CHRONY_LOG`,
`CLIENTLOGLIMIT`, `MAXUPDATESKEW`, `CUSTOM_CHRONY_CONF`, `CUSTOM_PTP4L_CONF`, `GPS_OPTIONS`,
`GPS_SHM_UNIT`, `GPS_PPS_SHM_UNIT`, `GPS_WAIT_SECONDS`, `GPSD_HOST`/`GPSD_PORT`,
`PHC_REFCLOCK_OPTIONS`, `PTP_UTC_OFFSET`, `PTP_HOLDOVER_SECONDS`, `PTP_TX_TIMESTAMP_TIMEOUT`,
`PTP_UDS_ADDRESS`.

### Clients, Diagnose und Entwicklung

| Variable | Default | Bedeutung |
|---|---|---|
| `CLIENTMON` | `true` | Uhren der Clients passiv messen, siehe [Wie genau gehen meine Clients?](#wie-genau-gehen-meine-clients) |
| `CLIENTS_ALARM_MS` | `0` | Ereignis, wenn eine Client-Uhr mehr als so viele Millisekunden abweicht (0 = aus), siehe [Ein Gerät im Detail](#ein-gerät-im-detail) |
| `CLIENTS_RDNS` | `false` | Namen der Clients per Reverse-DNS nachschlagen – nur private Adressen, nur wenn kein beteiligter DNS-Server öffentlich ist, nie über DoT/DoH |
| `ENFORCE_HOSTNAMES` | – | Weitere Zeitserver-Namen für die Anleitungen unter [Zeitserver erzwingen](#zeitserver-erzwingen), kommagetrennt (nur DNS-Namen, höchstens 50) |
| `NTPGUI_LOGTEE` | `1` | `0` schaltet die Log-Kopie für die Seite **Diagnose** ab |
| `NTPGUI_REPLAY` | – | Nur für Entwicklung/Demo: Aufzeichnung (`.jsonl`) statt echter Dienste abspielen |
| `NTPGUI_REPLAY_SPEED` | `1` | Tempo der Wiedergabe |

Der Healthcheck (Dockerfile und alle Compose-Dateien) liest `WEB_PORT` selbst; bei einem
anderen Port musst du ihn nicht anpassen.

Das Dashboard hat **keine Verschlüsselung**. Für Zugriff über unsichere Netze einen
Reverse Proxy mit TLS davorsetzen und `WEB_USER`/`WEB_PASSWORD` verwenden.

#### Schutz vor DNS-Rebinding

Ohne Passwort könnte sonst jede Webseite, die du im Browser öffnest, ihren eigenen Namen kurz
auf die LAN-Adresse von ntp-gui zeigen lassen und dann Log, Status und GPS-Position lesen
(„DNS-Rebinding“). Darum beantwortet ntp-gui **ohne Passwort** nur Anfragen an:

- IP-Adressen (`http://192.168.1.10:8080`), `localhost` und `*.localhost`,
- den eigenen Hostnamen des Containers und einteilige Namen (`http://raspberrypi:8080`) –
  solche Namen kann kein öffentliches DNS liefern,
- lokale Endungen: `*.local`, `*.lan`, `*.home.arpa`, `*.internal`, `*.home`, `*.corp`,
  `*.localdomain`, `*.intranet`, `*.private`, `*.speedport.ip`,
- den NTS-Namen (`NTS_SERVER_NAME`) und alles aus `WEB_ALLOWED_HOSTS`.

Jeder andere Name bekommt `403` mit einer Erklärung; im Log steht er einmal (bereinigt).
**`*.fritz.box` ist absichtlich nicht dabei:** `.box` ist eine echte, öffentlich vergebene
Endung. Öffnest du das Dashboard als `ntp.fritz.box`, trage `WEB_ALLOWED_HOSTS=*.fritz.box`
ein oder setze ein Passwort. Mit Passwort oder API-Schlüssel gilt jeder Name – die Anmeldung
schützt dann. `/healthz` antwortet immer.

### DNS für ntp-gui

| Variable | Default | Bedeutung |
|---|---|---|
| `DNS_MODE` | `system` | `system` (wie bisher), `servers` (klassisches DNS an feste IPs), `dot` (DNS-over-TLS), `doh` (DNS-over-HTTPS), siehe [DNS für ntp-gui](#dns-für-ntp-gui-gegen-schleifen-durch-dns-umschreibung) |
| `DNS_SERVERS` | – | Modus `servers`: IP-Adressen (optional `:port`), leerzeichen- oder kommagetrennt; keine Namen, kein Loopback auf Port 53 |
| `DNS_DOT` | – | Modus `dot`: Servernamen (optional `:port`, Standard 853) |
| `DNS_DOH` | – | Modus `doh`: `https://`-Adressen, ohne Benutzer/Passwort |
| `DNS_PIN` | – | Feste Adressen für DoT/DoH-Namen (`name=IP`), nötig bei `dns: 127.0.0.1` |
| `DNS_FALLBACK` | `true` | Antwortet keiner der eigenen Server, den ursprünglichen DNS des Containers fragen |

### Was im Container unter welchem Benutzer läuft

| Prozess | Benutzer | Warum |
|---|---|---|
| `chronyd` | `_chrony` | legt Privilegien nach dem Start selbst ab |
| `gpsd` | `gpsd` | ebenso |
| `ptp4l` / `phc2sys` | root | brauchen `CAP_NET_ADMIN` für Hardware-Zeitstempel |
| Dashboard (`python3`) | root | ruft `chronyc` und `pmc` auf, deren Sockets root bzw. `_chrony` gehören |

Das Dashboard schreibt nur nach `/var/lib/chrony/ntp-gui` (Einstellungen, die Datenbank
`ntp-gui.db` mit Verlauf, Ereignissen, Client-Messwerten und API-Schlüssel-Hashes,
`autocal.json`, `instance-id`) und nach `/run/ntp-gui` (Log, Aufzeichnungen), führt keine Shell-Kommandos aus (alle Aufrufe nutzen feste
Argumentlisten) und prüft jeden Wert gegen eine Positivliste, bevor er in eine
Konfigurationsdatei gelangt. Trotzdem gilt: der Container ist für das eigene
LAN gedacht, nicht für das offene Internet. Wer ihn exponiert, gehört hinter einen Reverse
Proxy mit TLS und Authentifizierung.

`/healthz` ist **bewusst ohne Login** erreichbar, damit der Docker-Healthcheck funktioniert.
Der Endpunkt verrät nur, ob chronyd antwortet.

### Dienste und Neustarts

Ein Supervisor im Container startet und überwacht alle Dienste. Er unterscheidet:

- **chronyd und das Dashboard** sind der Kern. Fällt einer aus, beendet sich der Container
  mit Exit-Code 1 – die Restart-Policy (`restart: unless-stopped`) startet ihn dann neu.
- **gpsd, ptp4l und phc2sys** sind optional. Fällt einer aus (Empfänger abgezogen,
  Netzwerkkarte weg), startet der Supervisor nur diesen Dienst neu – nach 5 s, 15 s, 60 s
  und danach alle 5 Minuten. Lief ein Dienst 10 Minuten stabil, beginnt die Pause wieder bei
  5 s. NTP läuft währenddessen weiter.
- **Fehlt ein konfiguriertes Gerät**, wartet der Supervisor darauf und prüft alle
  30 Sekunden; taucht es auf (oder wird es ersetzt), übernimmt er es automatisch. Das klappt
  nur, wenn `/dev` eingehängt ist (Hotplug-Block der All-in-one-Datei).

Die Übersicht zeigt den Zustand in der Karte **Dienste** (läuft, wird neu gestartet, ausgefallen,
aus) mit Anzahl der Neustarts; ein ausgefallener Dienst erscheint auch im Hinweis-Kasten.
Für Prometheus gibt es `ntpgui_service_up`, `ntpgui_service_enabled` (1 = soll laut
Einstellungen laufen) und `ntpgui_service_restarts_total`. Der mitgelieferte Alarm
`NtpGuiServiceDown` meldet nur eingeschaltete Dienste, die nicht laufen.

## Endpunkte

| Pfad | Inhalt |
|---|---|
| `/` | Dashboard |
| `/api/status` | Kompletter Zustand als JSON, inkl. Hinweisen (`insights`) |
| `/api/history?range=3600&points=600` | Verlauf (System, Quellen, GPS, PTP), ausgedünnt |
| `/api/config` | Aktive `chrony.conf` / `ptp4l.conf` |
| `/api/settings` | Einstellungen mit Schema, Wert und Herkunft; `POST` speichert |
| `/api/settings/reset`, `/import`, `/export` | Dashboard-Werte zurücksetzen, importieren (auch Sicherungen älterer Versionen), sichern |
| `/api/settings/notes` | Hinweise der Einstellungs-Migration; `POST /api/settings/notes/ack` markiert sie als gelesen |
| `/api/auth` | `POST`: Dashboard-Passwort setzen oder entfernen |
| `/api/reload` | Stand des letzten Dienst-Neustarts; `POST` löst einen aus |
| `/api/devices` | Serielle/PPS-/PTP-Geräte, Netzwerkkarten, PTP-Voraussetzungen |
| `/api/hardware` | Hardware-Check (Empfänger, PPS, PTP, Plattform, Rechte, RTC, Matrix). Zwischengespeichert; `?refresh=1` prüft neu |
| `/api/gps/calibration?window=21600` | Kalibriervorschlag für das GPS über die letzten n Sekunden (`?seconds=` geht ebenso; ohne: letzte 24 h, `window=0`: ganzer Verlauf) |
| `/api/gps/autocal` | Automatische GPS-Kalibrierung: Modus, Entscheidung, letzte Änderungen; `POST /api/gps/autocal/rollback` nimmt die letzte zurück |
| `/api/logs?lines=500&q=&level=warn` | Container-Log (lokal, ungefiltert) |
| `/api/events?since=&kinds=&level=` | Ereignisprotokoll (Quellenwechsel, Fix verloren, PPS, Neustarts, Änderungen) |
| `/api/diagnostics/preview`, `/bundle` | Diagnosepaket: Vorschau bzw. `.tar.gz` – gefiltert, ohne Standort und Kennungen, wird nie hochgeladen |
| `/api/recording` | Aufzeichnung der Datenquellen; `POST {"seconds": 300}` startet, `{"action": "stop"}` stoppt |
| `/api/enforce/snippets`, `/api/enforce/check` | Zeitserver erzwingen: Anleitungen (DNS/Firewall) und Prüfung |
| `/api/clients/offsets` | Passiv gemessene Abweichung der Client-Uhren (mit eigenen Namen) |
| `/api/clients/overview`, `/api/clients/detail?ip=&range=` | Netzüberblick bzw. Verlauf und Gerätedaten eines Clients; `POST /api/clients/meta` (Name, Notiz) und `/api/clients/probe` (Aktiv nachmessen) mit Verwaltungsrecht |
| `/api/notify/status` | Zustellstand je Benachrichtigungskanal (ohne Namen, Adressen, Tokens); `/api/notify`, `POST /api/notify/channels`, `/channels/delete`, `/test` mit Verwaltungsrecht |
| `/api/dns` | DNS für ntp-gui: Modus, Zustand des Weiterleiters, Server, resolv.conf |
| `/api/temperature`, `/api/leap` | Temperatur und Frequenz bzw. Schaltsekunden-Liste (Seite Uhrqualität) |
| `/api/v1/time` | Serverzeit mit Zeitstempeln für die Vollbild-Uhr `/clock` |
| `/api/update` | Zustand des Update-Hinweises (ohne Netzzugriff, wenn ausgeschaltet) |
| `/api/apikeys` (Alias `/api/keys`) | API-Schlüssel auflisten, `POST` legt an, `/api/apikeys/revoke` widerruft (nur mit Benutzer/Passwort) |
| `/api/v1/instance` | Zufällige Instanz-Kennung; `POST /api/instance/rotate` erzeugt eine neue (nur mit Benutzer/Passwort) |
| `/api/v1/…` | Versionierte, stabile API (Alias der Pfade oben); `GET /api/v1` beschreibt alle Endpunkte samt nötigem Recht, siehe [API & Automatisierung](#api--automatisierung) |
| `/metrics` | Prometheus (u. a. Offset, max. Fehler, Quellen, GPS, PTP, `ntpgui_service_*`, `ntpgui_hardware_capability`, `ntpgui_pps_live`, `ntpgui_nts_server_cert_days_left`, Temperatur, Schaltsekunden-Liste, `ntpgui_info`) |
| `/clock` | Vollbild-Uhr (mit `CLOCK_PUBLIC=true` ohne Login) |
| `/healthz` | `200`, solange chronyd antwortet (ohne Login) |

## API & Automatisierung

**`/api/v1`** ist die versionierte, stabile Schnittstelle für Skripte, Home Assistant & Co.:
Jeder Pfad oben ist dort ohne `/api` erreichbar (`/api/v1/status`, `/api/v1/history`,
`/api/v1/events` …). Innerhalb von 1.x ändern sich diese Pfade und ihre Felder nicht
inkompatibel. `GET /api/v1` liefert die Liste aller Endpunkte samt Methode, Beschreibung und
nötigem Recht. Die bisherigen `/api/…`-Pfade funktionieren weiter.

### API-Schlüssel

Statt das Dashboard-Passwort in Skripte zu schreiben, legst du unter **Einstellungen →
API-Schlüssel** eigene Schlüssel an – je Anwendung einer, so kannst du jeden einzeln
widerrufen.

| Recht | Darf |
|---|---|
| **nur lesen** (`read`) | alle `GET`-Endpunkte, auch `/metrics` und das Diagnosepaket |
| **lesen und verwalten** (`admin`) | zusätzlich Änderungen per `POST` (Einstellungen, Neustart, Kalibrierung zurücknehmen, Aufzeichnung) |
| nur mit Benutzer und Passwort | Passwort ändern, API-Schlüssel anlegen/widerrufen, Instanz-Kennung neu erzeugen |

Die letzte Zeile ist Absicht: Kein Schlüssel – auch kein `admin`-Schlüssel – kann das Passwort
ändern oder sich neue Schlüssel ausstellen. Wird einer entwendet, reicht Widerrufen.

Der Schlüssel hat die Form `ntpg_…` und wird **nur einmal** angezeigt; gespeichert wird nur
ein SHA-256-Hash. Ein langsames Verfahren wie PBKDF2 bringt bei 144 Bit Zufall nichts und
würde jede Anfrage mit einem erfundenen `ntpg_…` teuer machen; Schlüssel aus 1.3-Vorabversionen
(PBKDF2) werden beim nächsten Gebrauch umgestellt. Im Ereignisprotokoll steht nur die Kennung
eines Schlüssels, nie sein frei gewählter Name. Er geht als `Authorization: Bearer` mit und gilt immer mit seinem Recht –
auch wenn kein Dashboard-Passwort gesetzt ist; ein Lese-Schlüssel kann also nie schreiben.
Mit Schlüssel entfällt der CSRF-Header `X-NTP-GUI` (den Schlüssel schickt kein Browser von
sich aus mit), `POST` braucht weiter `Content-Type: application/json`.

```bash
TOKEN=ntpg_…   # aus Einstellungen → API-Schlüssel

# Zustand lesen (Recht „nur lesen“)
curl -s -H "Authorization: Bearer $TOKEN" http://<host>:8080/api/v1/status

# Ereignisse der letzten Stunde, nur Warnungen und Schlimmeres
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://<host>:8080/api/v1/events?since=$(( $(date +%s) - 3600 ))&level=warn"

# Dienste neu starten (Recht „lesen und verwalten“)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{}' http://<host>:8080/api/v1/reload
```

Ein falscher oder widerrufener Schlüssel ergibt `401`, ein zu schwaches Recht `403` mit
dem nötigen Recht in `scope_required`.

### Prometheus

Ist ein Dashboard-Passwort gesetzt, braucht auch `/metrics` eine Anmeldung. Gib Prometheus
dafür einen Schlüssel mit Recht **nur lesen**:

```yaml
scrape_configs:
  - job_name: ntp-gui
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/ntp-gui.token   # enthält nur ntpg_…
    static_configs:
      - targets: ["192.168.1.10:8080"]
```

### Grafana, Home Assistant & Co.

Fertig zum Importieren bzw. Abschreiben:

- **Grafana:** [`docs/grafana/ntp-gui.json`](docs/grafana/ntp-gui.json) – Variablen für
  Datenquelle und Instanz; Offset, max. Fehler, Frequenz, Stratum, Quellen, Clients, Anfragen,
  GPS, Temperatur, Schaltsekunden-Liste, NTS-Zertifikat. Anleitung und Metrik-Tabelle:
  [`docs/integrationen/grafana-prometheus.md`](docs/integrationen/grafana-prometheus.md).
- **Prometheus-Alarme:** [`docs/prometheus/alerts.yml`](docs/prometheus/alerts.yml) – nicht
  synchron, Abweichung zu groß, keine nutzbare Quelle, GPS ohne Fix, PPS weg, Dienst gestört,
  NTS-Zertifikat und Schaltsekunden-Liste laufen ab, neue Version.
- **Home Assistant:** [`docs/integrationen/home-assistant.md`](docs/integrationen/home-assistant.md)
  – REST- und Template-Sensoren, Binärsensoren, Automations-Beispiel.
- **Homepage und Glance:** [`docs/integrationen/homepage-glance.md`](docs/integrationen/homepage-glance.md).
- **Uptime Kuma:** [`docs/integrationen/uptime-kuma.md`](docs/integrationen/uptime-kuma.md).

Der API-Schlüssel reist über HTTP im Klartext. Nutze `https://` über einen Reverse Proxy oder
ein vertrauenswürdiges Netz und gib jeder Integration einen eigenen Lese-Schlüssel.

### Instanz-Kennung

`/api/v1/instance` liefert eine zufällige Kennung (UUID), die beim ersten Start entsteht. Sie
enthält nichts über Hardware oder Standort und hilft künftigen, freiwilligen Diensten, Werte
derselben Instanz zuzuordnen. **Einstellungen → Neu erzeugen** ersetzt sie jederzeit
(`POST /api/instance/rotate`, nur mit Passwort).

## Update-Hinweise

Beim Update musst du nichts von Hand umbauen:

- **Einstellungen tragen eine Schema-Version.** Beim ersten Start einer neuen Version bringt
  ntp-gui die gespeicherten Einstellungen einmalig auf den neuen Stand. Was dabei geändert
  wurde, steht als Karte **oben auf der Einstellungsseite** – mit Begründung; „Gelesen“
  blendet sie aus (`/api/settings/notes`). Beispiel 1.3: Ein gespeicherter Pfad für
  Zertifikat/Schlüssel des NTS-Servers außerhalb von `/config`, `/certs` oder
  `/etc/letsencrypt` (seit 1.2.0 nicht mehr erlaubt) wird entfernt, statt bei jedem Start als
  „ungültig“ gemeldet zu werden.
  Beispiel 1.3.1: Das Image basiert jetzt auf Debian 13 „trixie“; dort gibt es die Zeitzone
  `right/UTC` nicht mehr. Ein gespeichertes `LEAPSECTZ=right/UTC` wird entfernt, chrony liest
  die Schaltsekunden aus `/usr/share/zoneinfo/leap-seconds.list`. Steht `LEAPSECTZ` in deiner
  Compose-Datei, kannst du die Zeile löschen.
- **Sicherungen aus älteren Versionen** lassen sich importieren; sie durchlaufen dieselben
  Schritte. Eine Datei aus einer *neueren* Version bleibt unangetastet.
- **Liegt `/var/lib/chrony` schreibgeschützt**, gelten die Änderungen nur im Speicher; die
  Hinweise erscheinen trotzdem.
- **Verlauf:** Ein vorhandenes `history.json.gz` (bis 1.2) wird beim ersten Start in
  `ntp-gui.db` übernommen und als `history.json.gz.migrated` aufbewahrt. Kann die Datenbank
  nicht geöffnet werden, arbeitet der Verlauf wie in 1.2 weiter.

### Update-Hinweis (opt-in)

Ausgeschaltet (Standard) fragt ntp-gui nirgends nach. Unter **Einstellungen → Dashboard →
Update-Hinweis** oder mit `UPDATE_CHECK=true` fragt es einmal am Tag zu einer zufälligen
Uhrzeit `https://api.github.com/repos/ConGp20/ntp-gui/releases/latest` und vergleicht die
Version lokal. Ist eine neuere da, erscheint oben ein Banner (pro Version ausblendbar) und in
der Übersicht ein Hinweis mit Release-Titel und Link zu den Release-Notizen – markiert mit
**„Achtung beim Update“**, wenn der Release-Text `BREAKING` oder „Achtung“ enthält. ntp-gui lädt
nichts herunter und aktualisiert sich nicht selbst; dafür eignen sich Diun oder What's up
Docker (Watchtower ist archiviert).

Datenschutz, ehrlich gesagt: GitHub sieht dabei einmal am Tag deine öffentliche IP-Adresse
(grob ortbar) und dass dort vermutlich ntp-gui läuft. Die Anfrage ist fest verdrahtet:
User-Agent nur „ntp-gui“, ohne Version oder Kennung, keine Daten der Instanz, keine
Weiterleitungen, höchstens 20 s, Antwort höchstens 512 KiB. Zustand: `/api/v1/update`,
Metriken `ntpgui_update_available` und `ntpgui_update_check_last_success_timestamp_seconds`.

## Entwicklung

```bash
python3 -m unittest discover -s tests -v     # 854 Tests: Parser, Einstellungen, Config, Kalibrierung, Hardware, NTS, Datenschutzfilter, API, Benachrichtigungen, DNS, Clients, Uhrqualität
docker build -t ntp-gui:test .
tests/container-test.sh ntp-gui:test         # Integrationstest gegen das gebaute Image
```

Der Integrationstest (173 Prüfungen) startet echte Container und prüft das, was Unittests
nicht abdecken: Erkennung von fehlendem `CAP_SYS_TIME`, Healthcheck, alle Endpunkte,
Basic-Auth, gemountete Konfiguration, Verhalten ohne GPS-/PTP-Hardware, Neustart eines
abgestürzten gpsd, eine echte NTP-Abfrage über das Netz, Einstellungen speichern samt
Neustart der Dienste und Persistenz über eine Neuerstellung, CSRF-Schutz, `WEB_READONLY`,
den NTS-Server mit selbst signiertem Zertifikat samt Zertifikatswechsel wie bei Certbot, die
Log-Seite, das Diagnosepaket (gültiges Archiv mit `MANIFEST.txt`, ohne Koordinaten,
Satellitenwinkel, MAC, öffentliche IP und ohne Adresse oder Namen des Containers),
API-Schlüssel, den Schutz vor DNS-Rebinding (fremder Host-Name → 403, `WEB_ALLOWED_HOSTS`, mit
Login jeder Name), den DNS-Weiterleiter, Benachrichtigungen, Client-Verlauf und -Detail,
Schaltsekunden, Vollbild-Uhr, den abgeschalteten Update-Hinweis und die Exit-Codes beim Stoppen. Dieselbe Datei läuft in der CI gegen das gebaute Image.

Lokal ohne Container starten (setzt installiertes `chrony` voraus; als root, und der
System-chronyd sollte gestoppt sein). `CHRONY_CONF` auf einen Scratch-Pfad zeigen
lassen – der Entrypoint überschreibt die Datei, die dort liegt:

```bash
APP_DIR=$PWD/app CHRONY_CONF=/tmp/ntp-gui-chrony.conf NTP_PORT=10123 WEB_PORT=8080 \
  DISABLE_CLOCK_CONTROL=true bash docker/entrypoint.sh
```

Die Tests decken die Ausgabeformate von `chronyc`, `pmc` und `gpsd` ab – dort stecken die
Fallstricke: `reach` ist auch im CSV-Modus **oktal**, `activity` liefert eine einzige
CSV-Zeile, „nie gehört“ ist `4294967295` und `pmc` antwortet nur, wenn die **Domain**
übereinstimmt, und gpsd liefert die Satellitenliste nur in manchen Zyklen mit.

## Bekannte Einschränkungen

* Der Verlauf reicht standardmäßig 30 Tage zurück (`HISTORY_DAYS`). Für längere Zeiträume
  `/metrics` mit Prometheus abgreifen.
* Die passive Messung der Client-Uhren sieht echte Client-Adressen nur mit Host-Netzwerk,
  und Clients wie chrony oder NTS-Clients verschleiern ihre Uhrzeit absichtlich (nicht messbar).
* Nach dem Speichern starten chronyd, gpsd und ptp4l kurz neu, nach einer
  Zertifikatserneuerung beim NTS-Server nur chronyd; für einige Sekunden antwortet der
  NTP-Server dann nicht.
* `chronyc clients` zählt nur, solange das Client-Log Platz hat (`CLIENTLOGLIMIT`).
* Das Dashboard bringt kein TLS mit – für Zugriffe außerhalb des vertrauenswürdigen Netzes
  gehört ein Reverse Proxy davor.
* PTP braucht das Host-Netzwerk; über eine Docker-Bridge funktioniert es nicht.
* `ts2phc` (PPS direkt in die PTP-Uhr der Netzwerkkarte) wird nicht unterstützt; der
  Grandmaster-Betrieb geht immer über die Systemuhr (chrony → phc2sys).
* Hotplug und `device_cgroup_rules` gibt es nur auf Linux-Hosts, nicht mit Docker Desktop.
* Entprellung und offene Probleme der Benachrichtigungen sowie der Zustand des Client-Alarms
  liegen nur im Speicher: Nach einem Neustart des Containers gibt es für ein noch offenes Problem
  keine „behoben“-Meldung, und ein noch falsch gehender Client meldet sich einmal neu.
* Ohne OUI-Liste im Image zeigt die Client-Detailseite keinen Hersteller (eigene Datei unter
  `/config/oui.txt` möglich).
* Ohne IPv6 im Docker-Netz meldet chronyd „Could not open … socket on [::]“ – harmlos,
  IPv4 funktioniert.

## Release

Veröffentlicht wird über GitHub Actions: im Repo unter **Actions → Release → Run workflow**
die Version eintragen (z. B. `1.2.0`) und starten. Der Workflow

1. lehnt Versionen ab, die kein SemVer sind oder deren Tag schon existiert,
2. führt Unittests und den Integrationstest gegen das frisch gebaute Image aus,
3. baut das Image für `linux/amd64` und `linux/arm64` und pusht es nach
   `ghcr.io/<owner>/ntp-gui` mit den Tags `1.0.0`, `1.0` und `latest`,
4. erzeugt für beide Architekturen eine SBOM (SPDX, syft) und einen Schwachstellen-Bericht
   (Grype) aus dem hochgeladenen Digest und bricht bei einer **kritischen Lücke mit verfügbarer
   Korrektur** ab (Lücken ohne Korrektur stehen nur im Bericht),
5. legt einen Herkunftsnachweis (SLSA Build Provenance) in der Registry ab und prüft ihn –
   nur bei einem **öffentlichen** Repository; GitHub bietet das für private Repositories
   eines Nutzers nicht an, dann läuft der Release ohne Nachweis weiter,
6. setzt erst danach die Image-Tags, den Git-Tag `v1.0.0` und das GitHub-Release an – mit
   `ntp-gui-<version>-<arch>.spdx.json` und `ntp-gui-<version>-<arch>-vulnerabilities.txt`.

Alle Actions sind per Commit-SHA festgenagelt, das Basis-Image per Digest; Dependabot schlägt
Updates vor. Ein Release-Build läuft ohne Cache, zieht also immer aktuelle Debian-Pakete.

**Herkunft prüfen** (GitHub-CLI, sobald das Repository öffentlich ist):

```bash
gh attestation verify oci://ghcr.io/congp20/ntp-gui:1.4.0 -R ConGp20/ntp-gui
```

Scheitert ein Schritt, entsteht kein halber Release. Bei einem privaten Repository
ist auch das Image zunächst privat (`docker login ghcr.io` nötig); die Sichtbarkeit
lässt sich in den Package-Einstellungen auf GitHub ändern.

## Mitmachen

ntp-gui ist ein Community-Projekt. Was geplant ist, steht in der [Roadmap](ROADMAP.md);
wie du mithelfen kannst – auch ohne Programmieren, etwa mit einem Hardware-Bericht für die
Kompatibilitätsliste –, steht in [CONTRIBUTING.md](CONTRIBUTING.md).

## Lizenz

[MIT](LICENSE)
