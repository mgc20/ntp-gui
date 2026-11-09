# HTTPS fürs Dashboard – per Reverse Proxy

ntp-gui spricht selbst nur HTTP. Das ist Absicht (Entscheidung E5): TLS im Python-Server hätte
Fallstricke – ein hängender Handshake blockiert, Zertifikate müssten erneuert und nachgeladen
werden –, und in vielen Heimnetzen läuft ohnehin schon ein Reverse Proxy, der das besser kann.

**Warum überhaupt HTTPS?** Mit Passwort schickt der Browser bei jeder Anfrage Benutzer und
Passwort mit (Basic-Auth, nur Base64 – kein Schutz). Ein API-Schlüssel steht im Klartext im Kopf
`Authorization`. Über HTTP kann jedes Gerät auf dem Weg mitlesen: ein WLAN-Teilnehmer, ein Switch
mit Spiegelport, ein gekapertes Smart-Home-Gerät. Kommt ein Passwort oder Schlüssel per HTTP aus dem
Netz an, zeigt die Übersicht deshalb den Hinweis **„Dashboard über unverschlüsseltes HTTP mit
Anmeldung“**. Aufrufe vom Rechner selbst (127.0.0.1, z. B. der Healthcheck) zählen nicht.

Ohne Passwort und ohne API-Schlüssel gibt es nichts mitzulesen – dann ist HTTPS nett, aber nicht
nötig.

## Was für alle Proxys gilt

| Punkt | Warum |
|---|---|
| **Host-Kopf unverändert weitergeben** (Standard bei Caddy, NPM, Zoraxy, Traefik) | ntp-gui vergleicht beim Speichern die Herkunft (`Origin`) mit dem Host. Schreibt der Proxy den Host um, lehnt ntp-gui jede Änderung ab („Anfrage abgelehnt (nur aus dem Dashboard heraus)“). Bei reinem nginx selbst eintragen: `proxy_set_header Host $host;` – nginx schickt sonst den Namen aus `proxy_pass` (z. B. `127.0.0.1:8080`). |
| **`WEB_BIND=127.0.0.1`**, wenn der Proxy auf demselben Host läuft | Dann ist das Dashboard nur noch über HTTPS erreichbar, nicht mehr nebenher über `http://host:8080`. Läuft der Proxy auf einem anderen Gerät, `WEB_BIND` lassen und Port 8080 per Firewall nur für den Proxy öffnen. |
| **`TRUSTED_PROXIES`** = Adresse des Proxys | Nur dann glaubt ntp-gui `X-Forwarded-For` und `X-Forwarded-Proto`: Das Zugriffsprotokoll (`WEB_ACCESS_LOG=true`) nennt den Browser statt des Proxys, und der HTTPS-Hinweis erkennt den verschlüsselten Weg. Standard ist leer – **niemandem trauen**, sonst könnte jeder Browser eine falsche Adresse vorgeben. Nie ein ganzes Netz eintragen, nur den Proxy (`/32` bzw. `/128`). Über Anmeldung und Zugriff entscheiden die Köpfe nie. |
| **Erlaubte Namen** bzw. **`WEB_ALLOWED_HOSTS`**, wenn ohne Passwort | Ohne Passwort beantwortet ntp-gui nur IP-Adressen, einteilige Namen und lokale Endungen (`.lan`, `.local`, `.home.arpa`, `.internal` …) – Schutz vor DNS-Rebinding. Ein Name wie `zeit.example.com` muss dann unter **Einstellungen → Dashboard & Zugang → Erlaubte Namen** oder in `WEB_ALLOWED_HOSTS` stehen (beide gelten). Mit Passwort gilt jeder Name. Die Vollbild-Uhr `/clock` mit „Vollbild-Uhr ohne Anmeldung“ antwortet über jeden Namen. |

`TRUSTED_PROXIES` lässt sich auch im Dashboard setzen: **Einstellungen → Dashboard & Zugang → Erweitert →
Vertrauenswürdige Proxys**. Einfacher (ab 1.5.4): Kommen Anfragen mit Proxy-Köpfen von einer Adresse,
die dort fehlt, zeigt die Übersicht „Reverse Proxy erkannt, aber nicht eingetragen“ (bzw. als Warnung
„Anmeldung unverschlüsselt über nicht eingetragenen Proxy“, wenn der Proxy auf einem anderen Gerät läuft) mit dem Knopf
**„Als vertrauenswürdigen Proxy eintragen (…/32)“**. Er trägt genau die Adresse ein, die ntp-gui als
Gegenstelle gesehen hat (nur mit Admin-Recht, mit Rückfrage). Einträge breiter als /24 bzw. /64 warnt
ntp-gui an.

## Variante A: Caddy als eigener Stack (fertiges Beispiel)

Caddy steht bewusst **nicht** in den Compose-Vorlagen von ntp-gui, sondern läuft als eigener Stack
daneben – in einem eigenen Ordner, mit eigenem `docker compose up -d`. So bleiben die Vorlagen
schlank, und Caddy lässt sich unabhängig von ntp-gui aktualisieren oder durch einen anderen Proxy
ersetzen.

1. **Bei ntp-gui** zwei Zeilen setzen (in `docker-compose.all-in-one.yml` der Block
   **[OPTION Reverse Proxy auf diesem Rechner]**, sonst unter `environment:` ergänzen) und ntp-gui
   mit `docker compose up -d` neu erzeugen:

   ```yaml
         WEB_BIND: "127.0.0.1"                    # Dashboard nur noch über den Proxy
         TRUSTED_PROXIES: "127.0.0.1/32,::1/128"  # nur Caddy auf diesem Rechner glauben
   ```

2. **Caddy** in einem eigenen Ordner anlegen, z. B. `~/caddy/docker-compose.yml`, den Namen
   `zeitserver.lan` anpassen (DNS-Eintrag im Router/AdGuard/Pi-hole oder die feste IP-Adresse des
   Hosts) und dort `docker compose up -d`. Fertig ist `https://zeitserver.lan`.

<!-- compose-caddy: tests/container-test.sh prüft dieses Beispiel als eigenständige Compose-Datei -->
```yaml
# ~/caddy/docker-compose.yml – eigener Stack neben ntp-gui
services:
  caddy:
    image: caddy:2.10.2
    container_name: ntp-gui-caddy
    restart: unless-stopped
    network_mode: host          # erreicht ntp-gui unter 127.0.0.1:8080
    command: ["caddy", "reverse-proxy", "--from", "https://zeitserver.lan", "--to", "127.0.0.1:8080", "--internal-certs"]
    volumes:
      - caddy-data:/data        # Zertifikate und Caddys eigene Zertifizierungsstelle

volumes:
  caddy-data:
```

Hat ntp-gui einen anderen Port (`WEB_PORT`), `127.0.0.1:8080` anpassen. Endet der Name nicht auf
`.lan`, `.local`, `.home.arpa`, `.internal` o. Ä. und ist kein Passwort gesetzt, ihn zusätzlich
unter **Einstellungen → Dashboard & Zugang → Erlaubte Namen** (oder in `WEB_ALLOWED_HOSTS`)
eintragen – Schutz vor DNS-Rebinding.

Caddy setzt `X-Forwarded-For` und `X-Forwarded-Proto` selbst und überschreibt, was ein Browser
mitschickt. Caddy belegt auf dem Host 443/tcp und 80/tcp (Umleitung auf HTTPS). Ist Port 80 schon
belegt (Pi-hole, AdGuard Home), `"--disable-redirects"` an die Liste hängen.

### Zertifikat im LAN: `--internal-certs` (Standard im Beispiel)

Caddy betreibt eine eigene kleine Zertifizierungsstelle und stellt sich das Zertifikat selbst aus –
ohne Internet, ohne öffentlichen Namen, auch für eine IP-Adresse (`--from https://192.168.1.10`).
Browser kennen diese Stelle zunächst nicht und warnen. Einmal pro Gerät ihr Root-Zertifikat als
vertrauenswürdig eintragen (Befehle im Ordner des Caddy-Stacks):

```sh
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
openssl x509 -in caddy-root.crt -noout -subject -fingerprint -sha256   # Fingerabdruck notieren
```

| Gerät | Eintragen |
|---|---|
| Windows | Doppelklick → „Zertifikat installieren“ → Lokaler Computer → „Vertrauenswürdige Stammzertifizierungsstellen“ |
| macOS | Doppelklick → Schlüsselbund „System“ → Zertifikat öffnen → „Vertrauen: Immer vertrauen“ |
| Linux (Debian/Ubuntu) | `sudo cp caddy-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`; Firefox: Einstellungen → Zertifikate → Importieren |
| iOS/iPadOS | Datei per AirDrop/Mail öffnen → Profil installieren → Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → einschalten |
| Android | Einstellungen → Sicherheit → Verschlüsselung & Anmeldedaten → Zertifikat installieren → CA-Zertifikat |

Den Fingerabdruck auf dem Gerät mit dem notierten vergleichen. Das Root-Zertifikat gilt rund zehn
Jahre; die Zertifikate für das Dashboard erneuert Caddy von selbst. Das Volume `caddy-data` nicht
löschen – sonst entsteht eine neue Zertifizierungsstelle und alle Geräte müssen sie neu eintragen.
Der private Schlüssel der Stelle liegt in diesem Volume: Wer ihn hat, kann für deine Geräte
beliebige Seiten fälschen. Das Volume darum nicht weitergeben (das Diagnosepaket von ntp-gui
enthält es nie).

### Öffentliches Zertifikat: Let's Encrypt

Hat der Host einen öffentlichen Namen, dessen Ports 80 und 443 aus dem Internet hierher führen,
`"--internal-certs"` weglassen – Caddy holt dann ein Let's-Encrypt-Zertifikat. Für ein reines
LAN-Dashboard ist das selten sinnvoll: Das Dashboard gehört nicht ins Internet.

**Öffentlicher Name ohne offene Ports (DNS-Challenge):** Caddy beweist den Besitz der Domain über
einen TXT-Eintrag. Dafür braucht es ein Caddy-Image mit dem Modul deines DNS-Anbieters (z. B.
`caddy-dns/cloudflare`, gebaut mit `xcaddy`) und eine Caddyfile statt `command:`:

```caddyfile
zeit.example.com {
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	reverse_proxy 127.0.0.1:8080
}
```

Im Compose-Dienst dann `command:` entfernen, die Datei mit `- ./Caddyfile:/etc/caddy/Caddyfile:ro`
einhängen und `CF_API_TOKEN` als Umgebungsvariable setzen (Token nur mit Recht „DNS bearbeiten“ für
diese eine Zone). Der Name muss im LAN auf den Host zeigen (DNS-Umschreibung im Router, AdGuard
oder Pi-hole) – und ohne Passwort unter „Erlaubte Namen“ bzw. in `WEB_ALLOWED_HOSTS` stehen.

**Mehrere Namen** (z. B. Name und IP): ebenfalls per Caddyfile, Namen mit Komma trennen:

```caddyfile
zeitserver.lan, 192.168.1.10 {
	tls internal
	reverse_proxy 127.0.0.1:8080
}
```

### ntp-gui im Bridge-Netzwerk

Läuft ntp-gui ausnahmsweise nicht im Host-Netzwerk, beide Stacks in ein gemeinsames Docker-Netz
stellen (`docker network create proxy`, in beiden Compose-Dateien unter `networks:` als
`external: true` eintragen), bei Caddy `network_mode: host` weglassen, `ports: ["443:443", "80:80"]`
setzen und `--to ntp-gui:8080`. `WEB_BIND` bleibt dann `0.0.0.0` (nur den Port 8080 nicht nach
außen veröffentlichen), und `TRUSTED_PROXIES` ist die Adresse von Caddy in diesem Netz – am
einfachsten das Netz mit fester Adresse anlegen (`--subnet`, bei Caddy `ipv4_address`) und genau
diese `/32` eintragen.

## Variante B: vorhandener Proxy

### Nginx Proxy Manager (NPM)

1. **Proxy Hosts → Add Proxy Host:** Domain `zeitserver.lan` (oder dein Name), Scheme `http`,
   Forward Hostname/IP = Adresse des ntp-gui-Hosts, Port `8080`.
2. **SSL:** ein vorhandenes Zertifikat wählen oder „Request a new SSL Certificate“ (Let's Encrypt,
   für LAN-Namen per DNS-Challenge). „Force SSL“ einschalten.
3. NPM setzt `X-Forwarded-For` und `X-Forwarded-Proto` und gibt den Host unverändert weiter.
   Eigene Regeln unter „Advanced“ (`location`-Blöcke mit `proxy_pass`) brauchen
   `proxy_set_header Host $host;`, sonst kommt der Name aus `proxy_pass` an.
4. In ntp-gui `TRUSTED_PROXIES` = Adresse des NPM-Hosts, z. B. `192.168.1.2/32`. Läuft NPM auf
   demselben Host mit eigenem Bridge-Netz, kommt die Anfrage aus dessen Docker-Netz (z. B.
   `172.18.0.2/32` – die genaue Adresse steht im Zugriffsprotokoll von ntp-gui mit
   `WEB_ACCESS_LOG=true`, solange `TRUSTED_PROXIES` leer ist). Dem NPM-Container dafür eine feste
   Adresse geben, sonst wechselt sie beim Neuerstellen.

> **Strecke Proxy → ntp-gui ist unverschlüsselt.** Läuft der Proxy auf einem anderen Gerät, ist nur
> der Weg Browser → Proxy HTTPS. Von dort gehen Passwort bzw. API-Schlüssel per einfachem HTTP durchs
> LAN zu ntp-gui – jedes Gerät auf dieser Strecke kann mitlesen; die Firewall-Regel „Port 8080 nur
> für den Proxy“ verhindert das nicht. Besser den Proxy auf demselben Host betreiben
> (`WEB_BIND=127.0.0.1`), sonst die Strecke auf ein abgetrenntes, vertrauenswürdiges Netz legen.
> ntp-gui zeigt dafür den Hinweis „Strecke Proxy → ntp-gui ist unverschlüsselt“.

### Zoraxy

1. **HTTP Proxy → Neuer Proxy-Eintrag:** Matching Keyword = dein Name, Target = `ntp-gui-host:8080`,
   „Proxy Target require TLS“ **aus**.
2. Zertifikat unter **TLS / SSL certificates** (ACME oder eigenes) und TLS für den Eingang
   einschalten.
3. Zoraxy setzt `X-Forwarded-For`, `X-Forwarded-Proto` und `X-Real-Ip`; ntp-gui wertet die ersten
   beiden aus. `TRUSTED_PROXIES` = Adresse des Zoraxy-Hosts.

> **Strecke Proxy → ntp-gui ist unverschlüsselt.** Läuft der Proxy auf einem anderen Gerät, ist nur
> der Weg Browser → Proxy HTTPS. Von dort gehen Passwort bzw. API-Schlüssel per einfachem HTTP durchs
> LAN zu ntp-gui – jedes Gerät auf dieser Strecke kann mitlesen; die Firewall-Regel „Port 8080 nur
> für den Proxy“ verhindert das nicht. Besser den Proxy auf demselben Host betreiben
> (`WEB_BIND=127.0.0.1`), sonst die Strecke auf ein abgetrenntes, vertrauenswürdiges Netz legen.
> ntp-gui zeigt dafür den Hinweis „Strecke Proxy → ntp-gui ist unverschlüsselt“.

### Traefik

Für ntp-gui im Host-Netzwerk eine Datei-Konfiguration (dynamic config):

```yaml
http:
  routers:
    ntp-gui:
      rule: "Host(`zeitserver.lan`)"
      entryPoints: [websecure]
      service: ntp-gui
      tls: {}            # oder certResolver: le
  services:
    ntp-gui:
      loadBalancer:
        servers:
          - url: "http://192.168.1.10:8080"
```

Traefik überschreibt `X-Forwarded-*` aus dem Internet, solange `forwardedHeaders.trustedIPs` am
Entrypoint nicht gesetzt ist, und gibt den Host unverändert weiter. `TRUSTED_PROXIES` = Adresse des
Traefik-Hosts.

> **Strecke Proxy → ntp-gui ist unverschlüsselt.** Läuft der Proxy auf einem anderen Gerät, ist nur
> der Weg Browser → Proxy HTTPS. Von dort gehen Passwort bzw. API-Schlüssel per einfachem HTTP durchs
> LAN zu ntp-gui – jedes Gerät auf dieser Strecke kann mitlesen; die Firewall-Regel „Port 8080 nur
> für den Proxy“ verhindert das nicht. Besser den Proxy auf demselben Host betreiben
> (`WEB_BIND=127.0.0.1`), sonst die Strecke auf ein abgetrenntes, vertrauenswürdiges Netz legen.
> ntp-gui zeigt dafür den Hinweis „Strecke Proxy → ntp-gui ist unverschlüsselt“.

## Prüfen

1. `https://zeitserver.lan` öffnen – das Schloss im Browser zeigt das Zertifikat.
2. `http://<host>:8080` sollte mit `WEB_BIND=127.0.0.1` **nicht** mehr antworten.
3. Mit `WEB_ACCESS_LOG=true` nennt das Container-Log die Adresse deines Rechners, nicht
   `127.0.0.1` – dann stimmt `TRUSTED_PROXIES`.
4. Die HTTPS-Hinweise der Übersicht verschwinden sofort, wenn du `TRUSTED_PROXIES` im Dashboard
   änderst, und „Reverse Proxy erkannt, aber nicht eingetragen“ auch mit der ersten Anfrage über
   den eingetragenen Proxy. „Dashboard über unverschlüsseltes HTTP“ bleibt nach einem letzten
   HTTP-Zugriff noch eine Stunde stehen, wenn danach nur noch HTTPS kam – sonst 24 Stunden.
5. **Hinweis bleibt trotz Proxy?** „Dashboard über unverschlüsseltes HTTP“ nennt seit 1.5.1, *wer*
   ungeschützt kam und *warum* – mit Adresse, Art (Passwort/API-Schlüssel) und „zuletzt vor …“:
   - **„direkt per HTTP“** – dieses Gerät ruft `http://<host>:8080` selbst auf: ein altes
     Lesezeichen, die Home-Assistant-Integration, ein Homepage- oder Uptime-Kuma-Widget, ein Skript.
     Auf die HTTPS-Adresse umstellen (oder `WEB_BIND=127.0.0.1`, wenn der Proxy auf demselben Host läuft).
   - **„über den eingetragenen Proxy …, aber der Browser sprach mit ihm nur HTTP“** – beim Proxy die
     Umleitung auf HTTPS („Force SSL“) einschalten.
   - **„über …, das Proxy-Köpfe schickt, aber nicht in TRUSTED_PROXIES steht“** – Adresse eintragen.

   - **„direkt per HTTP (eingetragener Proxy, aber ohne jeden Proxy-Kopf)“** – die Anfrage kam vom
     eingetragenen Proxy, aber ohne `X-Forwarded-For`/`-Proto`: Entweder reicht der Proxy die Köpfe
     nicht weiter (Einstellung siehe unten), oder ein Programm auf dem Proxy-Gerät ruft
     `http://<host>:8080` direkt auf.

   Schickt ein **eingetragener** Proxy zwar `X-Forwarded-For` oder nur `X-Real-IP`, aber weder
   `X-Forwarded-Proto` noch `Forwarded: proto=…` (oder einen unbekannten Wert), kann ntp-gui nicht
   erkennen, ob der Browser HTTPS benutzt. Dafür gibt es den eigenen Hinweis „Eingetragener Proxy
   meldet nicht, ob HTTPS benutzt wurde“; er nennt, welche Köpfe der Proxy tatsächlich schickt.
   Läuft der Proxy auf einem anderen Gerät, erscheint zusätzlich „Strecke Proxy → ntp-gui ist
   unverschlüsselt“ – diese Strecke ist dann in jedem Fall HTTP.
   Caddy, NPM, Zoraxy und Traefik setzen den Kopf von selbst; fehlt er, entfernt ihn meist eine
   eigene Regel. Nginx/NPM („Advanced“): `proxy_set_header X-Forwarded-Proto $scheme;` (dazu `proxy_set_header Host $host;`), HAProxy:
   `http-request set-header X-Forwarded-Proto https if { ssl_fc }`, Apache: nur im
   `<VirtualHost *:443>` `RequestHeader set X-Forwarded-Proto "expr=%{REQUEST_SCHEME}"` – nie
   pauschal `https`, sonst gilt auch ein HTTP-Zugriff als geschützt und die Warnung verschwindet
   zu Unrecht.

   Die Adressen stehen nur in der angemeldeten Übersicht – Hinweise gehen weder in
   Benachrichtigungen noch ins Diagnosepaket.

**Ausstiegsplan (E9):** Wird Caddy eingestellt, tut es jeder andere Reverse Proxy aus Variante B –
ntp-gui hängt an keinem bestimmten.
