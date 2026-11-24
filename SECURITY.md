# Sicherheit

## Lücke melden

Bitte **nicht** über ein öffentliches Issue, eine Diskussion oder einen Pull Request.

Melde sie vertraulich über **GitHub Private Vulnerability Reporting**:
[Sicherheitslücke melden](https://github.com/mgc20/ntp-gui/security/advisories/new)
(Reiter **Security** → **Report a vulnerability**).

Hilfreich sind:

- betroffene Version (z. B. `1.11.0`, steht im Dashboard unten und am Image-Tag),
- was ein Angreifer tun kann und unter welchen Voraussetzungen (z. B. aus dem LAN, mit oder ohne
  Verwaltungspasswort),
- Schritte zum Nachstellen oder ein kleiner Beweis,
- wenn möglich ein Vorschlag zur Behebung.

Häng keine Diagnosepakete, Logs oder Screenshots mit privaten Daten an. Falls doch nötig: Nimm
die gefilterte Fassung aus dem Dashboard (Seite **Diagnose**) und schau dir die Vorschau an.

## Was dann passiert

ntp-gui wird von einer Person in der Freizeit gepflegt. Ziel, aber kein Versprechen:

- Eingangsbestätigung innerhalb von 7 Tagen,
- Einschätzung und Plan innerhalb von 14 Tagen,
- Korrektur als Patch-Release über den normalen Release-Weg (Image mit SBOM, Schwachstellen-Bericht
  und Herkunftsnachweis), danach ein veröffentlichtes Security Advisory, auf Wunsch mit
  Nennung.

## Unterstützte Versionen

Korrekturen gibt es für die **jeweils neueste Minor-Version** (aktuell 1.11.x). Aktualisiere
bitte zuerst auf das neueste Image (`ghcr.io/mgc20/ntp-gui:latest`) und prüfe, ob die Lücke
dort noch besteht.

## Unterstützte Betriebsarten

- **Im eigenen LAN** mit einer der Compose-Vorlagen (`docker-compose.yml`, `…gps.yml`, `…pi-gps.yml`,
  `…ptp.yml`, `…all-in-one.yml`).
- **Auf einem Server im Internet (VPS)** mit [`docker-compose.vps.yml`](docker-compose.vps.yml) und der
  Anleitung [docs/integrationen/vps.md](docs/integrationen/vps.md): Dashboard nur über einen Reverse
  Proxy mit HTTPS (oder Cloudflare Tunnel mit Access) und mit `WEB_REQUIRE_AUTH=true`, Container
  gehärtet (schreibgeschütztes Root-Dateisystem, nur die nötigen Capabilities, `no-new-privileges`).
  Lücken, die in dieser Betriebsart ausnutzbar sind, nehmen wir mit hoher Priorität an.

Im Container laufen ab 1.9 außer dem Supervisor nur `ptp4l`/`phc2sys` (bei PTP) als root.
Dashboard und DNS-Weiterleiter laufen als eigener Benutzer `ntpgui` mit höchstens `NET_RAW`
(Client-Messung) bzw. `NET_BIND_SERVICE` (Port 53 oder ein Dashboard-Port unter 1024), chronyd
behält nur `SYS_TIME` (und `NET_BIND_SERVICE` für den NTP-Port). Wer die Vorlagen ändert und dem
Container mehr Rechte gibt (z. B. `privileged: true`), betreibt ihn außerhalb dieser Annahmen.

## Abgrenzung

- **Lücken in chrony, gpsd, linuxptp oder Debian-Paketen** bitte direkt bei diesen Projekten
  melden. Neue Paketstände kommen mit dem nächsten Release (er baut ohne Cache mit aktuellen
  Paketen).
- **Das Dashboard gehört ins LAN oder hinter einen Reverse Proxy**, nicht ungeschützt ins Internet.
  Dass es ohne gesetztes Verwaltungspasswort im LAN lesbar und änderbar ist, ist so gewollt und keine
  Lücke. Für Server, die aus dem Internet erreichbar sind, gibt es `WEB_REQUIRE_AUTH=true` (ohne Zugang
  gesperrt), siehe README → „Anmeldung und Zugang“ und die VPS-Anleitung. Ein Dashboard, das ohne
  Passwort direkt aus dem Internet erreichbar ist, ist kein unterstützter Betrieb.
- **Überlastung durch viele Absender (verteilte Angriffe)** auf NTP oder das Dashboard ist keine
  meldepflichtige Lücke; Ratelimit und Verbindungsgrenzen bremsen einzelne Absender, gegen verteilte
  Angriffe hilft nur der Netzbetreiber. Lässt sich der Dienst dagegen von **einem** Absender mit
  wenig Aufwand lahmlegen, melde das bitte.
- **Was der Betreiber per Umgebungsvariable** (z. B. `EXTRA_CHRONY_CONF`) **oder ein angemeldeter
  Verwalter im Dashboard einstellen kann** (z. B. eigene Zeitquellen), ist keine Rechteausweitung.
- **NTP für alle Adressen** (`ALLOW_NETWORKS=all`) ist eine bewusste Entscheidung des Betreibers.
  ntp-gui setzt dann strengere Standards (Ratelimit, kein Inselbetrieb) und weist darauf hin; eine
  Firewall davor ersetzt das nicht. Siehe README → „Öffentlich erreichbarer Zeitserver“.
- **PTP hat keine Authentifizierung** (Eigenschaft von IEEE 1588, nicht von ntp-gui). Wer im
  selben Netzsegment Pakete senden kann, kann sich als Grandmaster ausgeben. PTP gehört deshalb in
  ein vertrauenswürdiges Netz; das ist keine meldepflichtige Lücke.
