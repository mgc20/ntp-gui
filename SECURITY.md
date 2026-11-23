# Sicherheit

## Lücke melden

Bitte **nicht** über ein öffentliches Issue, eine Diskussion oder einen Pull Request.

Melde sie vertraulich über **GitHub Private Vulnerability Reporting**:
[Sicherheitslücke melden](https://github.com/mgc20/ntp-gui/security/advisories/new)
(Reiter **Security** → **Report a vulnerability**).

Hilfreich sind:

- betroffene Version (z. B. `1.5.4`, steht im Dashboard unten und am Image-Tag),
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

Korrekturen gibt es für die **jeweils neueste Minor-Version** (aktuell 1.5.x). Aktualisiere
bitte zuerst auf das neueste Image (`ghcr.io/mgc20/ntp-gui:latest`) und prüfe, ob die Lücke
dort noch besteht.

## Abgrenzung

- **Lücken in chrony, gpsd, linuxptp oder Debian-Paketen** bitte direkt bei diesen Projekten
  melden. Neue Paketstände kommen mit dem nächsten Release (er baut ohne Cache mit aktuellen
  Paketen).
- **Das Dashboard gehört ins LAN**, nicht ungeschützt ins Internet. Dass es ohne gesetztes
  Verwaltungspasswort im LAN lesbar und änderbar ist, ist so gewollt und keine Lücke. Für Server,
  die aus dem Internet erreichbar sind, gibt es `WEB_REQUIRE_AUTH=true` (ohne Zugang gesperrt), siehe
  README → „Anmeldung und Zugang“.
- **NTP für alle Adressen** (`ALLOW_NETWORKS=all`) ist eine bewusste Entscheidung des Betreibers.
  ntp-gui setzt dann strengere Standards (Ratelimit, kein Inselbetrieb) und weist darauf hin; eine
  Firewall davor ersetzt das nicht. Siehe README → „Öffentlich erreichbarer Zeitserver“.
- **PTP hat keine Authentifizierung** (Eigenschaft von IEEE 1588, nicht von ntp-gui). Wer im
  selben Netzsegment Pakete senden kann, kann sich als Grandmaster ausgeben. PTP gehört deshalb in
  ein vertrauenswürdiges Netz; das ist keine meldepflichtige Lücke.
