# Zeitserver auf einem VPS

Diese Anleitung bringt ntp-gui auf einen Server im Internet (VPS, Root-Server): NTP für alle, das
Dashboard nur über HTTPS mit Anmeldung. Grundlage ist die Vorlage
[`docker-compose.vps.yml`](../../docker-compose.vps.yml). Ab 1.9 ist dieser Betrieb mit dieser
Anleitung unterstützt (siehe [SECURITY.md](../../SECURITY.md)).

**Was die Vorlage anders macht als die LAN-Vorlagen:**

| Punkt | Wert | Warum |
|---|---|---|
| Netzwerk | `network_mode: host` | chrony sieht die echten Absender: „Erlaubte Netze“ und Ratelimit greifen je Client. |
| NTP | `ALLOW_NETWORKS: "all"`, `NTP_RATELIMIT: "streng"`, `SERVE_UNSYNCED: "false"` | Öffentlich, aber gebremst; kein Inselbetrieb – Clients weichen bei einem Ausfall auf andere Server aus. |
| Dashboard | `WEB_BIND: "127.0.0.1"`, `WEB_REQUIRE_AUTH: "true"`, Passwort als Docker-Secret | Nur über den Reverse Proxy (oder einen SSH-Tunnel), ohne Zugang gesperrt. |
| Proxy | `TRUSTED_PROXIES: "127.0.0.1/32,::1/128"` | Nur dem Proxy auf diesem Rechner werden `X-Forwarded-*`-Köpfe geglaubt. |
| Client-Messung | `CLIENTMON: "false"`, kein `NET_RAW` | Die Uhren fremder Geräte werden nicht beobachtet. |
| Härtung | `read_only`, `cap_drop: [ALL]` + nötige Capabilities, `no-new-privileges`, Grenzen für Prozesse, Speicher, CPU und Log | Nur der Supervisor ist root; das Dashboard läuft als Benutzer `ntpgui` ohne Capabilities. |

Belegt auf dem Host: `123/udp` (NTP), `127.0.0.1:8080` (Dashboard) und – nur mit NTS-Server –
`4460/tcp`. Der Reverse Proxy belegt `80/tcp` und `443/tcp`.

## 1. Firewall

Mit `network_mode: host` gelten die Regeln der Host-Firewall ganz normal (anders als bei
Portfreigaben im Bridge-Netz, die Docker an der Firewall vorbei einrichtet). Offen sein müssen nur:

| Port | wofür |
|---|---|
| `22/tcp` | SSH – wenn möglich nur von deinen eigenen Adressen |
| `123/udp` | NTP |
| `80/tcp`, `443/tcp` | Caddy (Let's Encrypt und Dashboard über HTTPS) – entfällt mit Cloudflare Tunnel |
| `4460/tcp` | nur mit NTS-Server (Schlüsselaustausch) |

`8080` bleibt zu – das Dashboard lauscht ohnehin nur auf `127.0.0.1`.

Beispiel mit `ufw`:

```sh
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 123/udp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# nur mit NTS-Server:
# sudo ufw allow 4460/tcp
sudo ufw enable
```

Das NTP-Ratelimit begrenzt, wie oft eine Adresse Antworten bekommt, nicht wie viele
TCP-Verbindungen sie gleichzeitig offen hält. Für `4460/tcp` (und gern auch `443/tcp`) begrenzt du
die gleichzeitigen Verbindungen je Adresse deshalb in der Firewall, z. B. mit nftables:

```nft
table inet ntpgui_limits {
  set conn4 { type ipv4_addr; size 65535; flags dynamic; }
  set conn6 { type ipv6_addr; size 65535; flags dynamic; }
  chain input {
    type filter hook input priority filter - 1; policy accept;
    tcp dport { 443, 4460 } ct state new add @conn4 { ip saddr ct count over 16 } drop
    tcp dport { 443, 4460 } ct state new add @conn6 { ip6 saddr ct count over 16 } drop
  }
}
```

(z. B. als `/etc/nftables.d/ntpgui-limits.nft`, geladen mit `sudo nft -f …`; 16 gleichzeitige
Verbindungen je Adresse reichen für Browser und NTS-Clients.)

## 2. Passwort anlegen und starten

Im Ordner mit der Vorlage (dem geklonten Repository oder einer Kopie der Datei):

```sh
umask 077
openssl rand -base64 18 > web_password.txt
docker compose -f docker-compose.vps.yml up -d
docker compose -f docker-compose.vps.yml logs -f
```

Das Passwort liegt nur in `web_password.txt`; der Container liest es als Docker-Secret. Der
Benutzer heißt `admin` (`WEB_USER`). Ohne gültige Passwortdatei bleibt das Dashboard gesperrt und
zeigt nur einen Einrichtungshinweis – NTP läuft trotzdem.

Passwort ändern: Neues Passwort **in dieselbe Datei** schreiben, also ihren Inhalt überschreiben:

```sh
openssl rand -base64 18 > web_password.txt
```

Der Container übernimmt die Änderung innerhalb von etwa 30 Sekunden ohne Neustart, das alte
Passwort gilt dann nicht mehr. Prüfe das im Log: Dort steht „Passwortdatei geändert“. Docker
hängt das Secret als einzelne Datei ein. Ersetzt du die Datei, statt sie zu überschreiben (`mv`,
`sed -i`, viele Editoren und Werkzeuge wie Ansible legen eine neue Datei an), sieht der Container
weiter den alten Inhalt und **das alte Passwort bleibt gültig**. Dann hilft nur
`docker compose -f docker-compose.vps.yml up -d --force-recreate`. Wird die Datei unlesbar,
sperrt sich das Dashboard.

Mit `WEB_REQUIRE_AUTH=true` gilt ein schwaches Passwort aus der Umgebung oder der Datei (kürzer als
12 Zeichen, ein bekannter Beispielwert, gleich dem Benutzernamen) als nicht gesetzt: Das Dashboard
bleibt gesperrt, das Log nennt den Grund.

Ein erster Blick ohne Proxy geht per SSH-Tunnel:

```sh
ssh -L 8080:127.0.0.1:8080 du@dein-vps
# dann im Browser: http://127.0.0.1:8080
```

**Version festhalten:** Statt `:latest` besser `ghcr.io/mgc20/ntp-gui:1.10` (nur Fehlerbehebungen
innerhalb von 1.10.x) eintragen.

**DNS-Modi des Dashboards:** Das Root-Dateisystem ist schreibgeschützt, der Container kann
`/etc/resolv.conf` nicht umstellen. Willst du unter **Einstellungen → DNS für ntp-gui** eigene
Server, DoT oder DoH nutzen, ergänze in der Vorlage `dns: [127.0.0.1]`.

## 3. HTTPS mit Caddy und Let's Encrypt

Voraussetzung: ein DNS-Name, der auf den VPS zeigt (A- und ggf. AAAA-Eintrag), z. B.
`zeit.example.com`. Caddy holt das Zertifikat selbst bei Let's Encrypt und erneuert es.

Ein eigener Ordner, z. B. `~/caddy`, mit zwei Dateien:

`~/caddy/Caddyfile`:

```caddyfile
{
	admin off
}

zeit.example.com {
	reverse_proxy 127.0.0.1:8080
	header Strict-Transport-Security "max-age=31536000"
}
```

`~/caddy/docker-compose.yml`:

```yaml
services:
  caddy:
    image: caddy:2.10.2
    container_name: caddy
    restart: unless-stopped
    network_mode: host            # erreicht ntp-gui unter 127.0.0.1:8080
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE          # Ports 80 und 443
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./data:/data              # Zertifikate (auch für NTS, siehe unten)
      - ./config:/config
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

```sh
cd ~/caddy && docker compose up -d
```

Danach ist das Dashboard unter `https://zeit.example.com` erreichbar. Caddy reicht den Host-Kopf
unverändert weiter und setzt `X-Forwarded-For` selbst; die Vorlage glaubt diesen Köpfen nur von
`127.0.0.1`/`::1`. Mehr zu Reverse Proxys allgemein: [https.md](https.md).

## 4. Alternative: Cloudflare Tunnel mit Access

Statt Ports 80/443 zu öffnen, kannst du das Dashboard über einen Cloudflare Tunnel erreichbar machen
und mit **Cloudflare Access** schützen (Anmeldung per E-Mail-Code oder deinem Login-Anbieter, bevor
überhaupt eine Anfrage beim VPS ankommt):

1. Im Cloudflare-Dashboard unter **Zero Trust → Networks → Tunnels** einen Tunnel anlegen und
   `cloudflared` auf dem VPS mit dem angezeigten Token starten.
2. Als öffentlichen Hostnamen z. B. `zeit.example.com` eintragen, Dienst `http://127.0.0.1:8080`.
3. Unter **Access → Applications** eine Anwendung für diesen Hostnamen anlegen und eine Regel, die
   nur dich zulässt.
4. In der Firewall `80/tcp` und `443/tcp` geschlossen lassen.

`WEB_REQUIRE_AUTH` und das Passwort bleiben trotzdem gesetzt – zwei Schlösser sind besser als eins.

**Ehrliche Grenze:** Ein Cloudflare Tunnel transportiert nur Web-Verkehr. **NTP (UDP 123) geht
nicht durch Cloudflare**, ebenso wenig der NTS-Schlüsselaustausch (TCP 4460), denn chronyd muss
die TLS-Verbindung selbst abschließen. Beides erreichen die Clients direkt über die Adresse des
VPS; `123/udp` (und ggf. `4460/tcp`) bleiben in der Firewall offen, und die Adresse des Servers ist
damit ohnehin öffentlich. Ein Zertifikat für NTS bekommst du über den Tunnel nicht – dafür brauchst
du Caddy (Abschnitt 3) oder certbot mit DNS-Challenge.

## 5. NTS-Server mit dem Zertifikat von Caddy

chronyd braucht für NTS ein Zertifikat für den Namen, unter dem die Clients den Server ansprechen.
Das von Caddy passt, wenn es derselbe Name ist. In `docker-compose.vps.yml`:

```yaml
    volumes:
      - chrony-data:/var/lib/chrony
      - ~/caddy/data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/zeit.example.com:/certs:ro
    environment:
      NTS_SERVER: "true"
      NTS_SERVER_NAME: "zeit.example.com"
      NTS_SERVER_CERT: "/certs/zeit.example.com.crt"
      NTS_SERVER_KEY: "/certs/zeit.example.com.key"
```

Dann `4460/tcp` in der Firewall öffnen (mit Verbindungsgrenze, Abschnitt 1) und neu erzeugen:
`docker compose -f docker-compose.vps.yml up -d`. Erneuert Caddy das Zertifikat, bemerkt ntp-gui
das binnen einer Minute und startet nur chronyd neu. Die Seite **Zeitquellen** zeigt Name,
Aussteller und Restlaufzeit. Test von außen:

```sh
chronyd -Q -t 3 "server zeit.example.com iburst nts maxsamples 1"
```

## 6. Updates

- **Image:** Release-Hinweise lesen (CHANGELOG), dann
  `docker compose -f docker-compose.vps.yml pull && docker compose -f docker-compose.vps.yml up -d`.
  Mit festgehaltener Minor-Version (`:1.10`) kommen so nur Fehlerbehebungen.
- **Herkunft prüfen (optional):** Jedes Release-Image hat einen Herkunftsnachweis:
  `gh attestation verify oci://ghcr.io/mgc20/ntp-gui:1.10 --owner mgc20`.
- **Host:** Sicherheitsupdates des Betriebssystems automatisch einspielen (Debian/Ubuntu:
  `unattended-upgrades`), Docker und Caddy-Image regelmäßig aktualisieren.
- **Update-Hinweis im Dashboard:** standardmäßig aus; wer ihn will, schaltet ihn unter
  **Einstellungen** ein (fragt dann nur die Release-Liste ab).

## 7. Sicherung

- **Im Dashboard:** **System → Einstellungen → Sichern → Sicherung herunterladen**. Enthält
  Einstellungen, Verlauf und Ereignisse – kein Passwort, keine API-Schlüssel, keine NTS-Schlüssel
  (siehe README → „Sichern und wiederherstellen“). Die nächtliche Sicherung (Standard aus) legt
  Kopien im Volume ab; gegen den Verlust des VPS hilft nur eine heruntergeladene Kopie.
- **Was du zusätzlich aufhebst:** `web_password.txt` (oder setzt nach einer Wiederherstellung ein
  neues Passwort), `~/caddy/Caddyfile` und deine Änderungen an `docker-compose.vps.yml`.
- Die Sicherung enthält Client-Adressen und Servernamen: privat aufbewahren, nicht teilen.

## Was diese Anleitung nicht abdeckt

- **Dashboard direkt im Internet** (ohne Proxy, ohne `WEB_BIND=127.0.0.1`): nicht vorgesehen.
- **Schutz gegen große Überlastungsangriffe:** Ratelimit und Verbindungsgrenzen bremsen einzelne
  Absender; gegen verteilte Angriffe hilft nur der Anbieter des VPS.
- **Zeitgenauigkeit:** Ein VPS teilt die Uhr mit dem Host des Anbieters. `SYS_TIME` stellt die Uhr
  der virtuellen Maschine; manche Anbieter erlauben das nicht – dann läuft chronyd mit `-x` und
  verteilt nur die Zeit der VM (Hinweis im Log).
