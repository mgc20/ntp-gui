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
  Verwaltungspasswort im LAN lesbar ist, ist so gewollt und keine Lücke.
