# Bereitschaft prüfen: `/readyz` für keepalived, Docker und Uptime-Monitore

`/healthz` meldet nur, ob chronyd antwortet. Ein Zeitserver ohne Zeitquelle ist damit „gesund“ –
für einen Healthcheck, der den Container am Leben hält, ist das richtig. Wer aber entscheiden will,
ob dieser Server **jetzt Zeit verteilen soll** (virtuelle IP mit keepalived, Load-Balancer,
Alarm im Monitoring), nimmt die strenge Variante `/readyz`.

## Was `/readyz` meldet

| Status | Körper | Bedeutung |
|---|---|---|
| `200` | `{"status": "ready", "chrony": true, "synchronised": true, "source_selected": true, "within_limit": true}` | chrony ist synchronisiert, hat gerade eine Quelle ausgewählt (kein Holdover) und die Fehlerschranke liegt unter der Grenze |
| `503` | `{"status": "not_ready", "chrony": …, "synchronised": …, "source_selected": …, "within_limit": …}` | eine der Bedingungen fehlt |

- **chrony**: chronyd antwortet.
- **synchronised**: Stratum unter 16, Schaltsekunden-Status gültig und **kein** Inselbetrieb (`local`).
- **source_selected**: chrony hat gerade eine Quelle ausgewählt. Fallen alle Quellen aus, nennt chrony
  noch eine Weile dieselbe Referenz und dasselbe Stratum (Holdover) – `synchronised` bleibt dann
  wahr, die Fehlerschranke wächst nur um wenige Mikrosekunden je Sekunde. Deshalb meldet `/readyz`
  im Holdover sofort `503`, auch während eines Holdover-Tests. Die Erkennung stammt aus der
  regelmäßigen Messung („Messintervall für Diagramme“, Standard 10 s); bis sie den Ausfall sieht,
  kann es also ein Intervall dauern.
- **within_limit**: Fehlerschranke `|Offset| + Root-Dispersion + Root-Delay/2` (so rechnet chrony den
  höchsten möglichen Fehler der Systemuhr) liegt **unter** der Grenze.

Die Grenze stellst du unter **Einstellungen → Dashboard & Zugang → Bereitschaft (/readyz): Fehlergrenze**
(erweitert) ein, oder per Umgebungsvariable `READY_MAX_ERROR_MS` (0,001 bis 10000, Standard `100`).
Anhaltspunkte:

| Zeitquelle | sinnvolle Grenze |
|---|---|
| Internet-NTP (Pool, PTB, Cloudflare) | `100` (Standard) oder `50` |
| NTP im eigenen Netz, Stratum 1 nebenan | `10` |
| GPS mit PPS | `1` |

`/readyz` ist wie `/healthz` **ohne Anmeldung** und für jeden Host-Namen erreichbar, auch mit
`WEB_REQUIRE_AUTH=true` ohne eingerichteten Zugang. Die Antwort enthält nur Wahrheitswerte –
keine Messwerte, keine Quellen, keine Grenze. chronyd wird dafür höchstens alle 2 Sekunden gefragt,
egal wie viele Anfragen kommen. `/healthz` bleibt unverändert.

Auf einem Server im Internet (siehe [vps.md](vps.md)) ist `/readyz` damit wie `/healthz` offen: Wer
den Port erreicht, erfährt, ob der Server synchron ist – mehr nicht. Wer das nicht möchte, gibt den
Pfad im Reverse Proxy nicht nach außen frei und fragt ihn nur lokal oder im eigenen Netz ab.

## keepalived (`track_script`)

keepalived läuft auf dem **Host** (oder als eigener Container mit `network_mode: host` und
`NET_ADMIN`), nicht im ntp-gui-Image. Auf beiden Zeitservern:

```conf
# /etc/keepalived/keepalived.conf
global_defs {
    enable_script_security
    script_user nobody
}

vrrp_script ntp_ready {
    script "/usr/bin/curl -fsS -o /dev/null --max-time 3 http://127.0.0.1:8080/readyz"
    interval 10        # alle 10 s prüfen
    timeout 5
    fall 3             # erst nach 3 Fehlschlägen (30 s) als „nicht bereit“ werten
    rise 2             # nach 2 Erfolgen wieder bereit
}

vrrp_instance NTP {
    state BACKUP
    interface eth0
    virtual_router_id 123
    priority 150       # zweiter Server: 100
    advert_int 1
    virtual_ipaddress {
        192.168.1.123/24
    }
    track_script {
        ntp_ready
    }
}
```

`curl -f` endet bei `503` mit einem Fehler – keepalived nimmt dem Server dann die virtuelle
Adresse (bzw. bei `weight` die Priorität) und der andere übernimmt. Ohne `curl` geht auch
`wget -q -O /dev/null -T 3 http://127.0.0.1:8080/readyz`.

Damit Geräte über die virtuelle Adresse NTS sprechen können, muss das NTS-Zertifikat **beider**
Server den Namen der virtuellen Adresse tragen. Nach einem Neustart braucht chrony einige Minuten
bis zur Synchronisation – in dieser Zeit bleibt die virtuelle Adresse beim anderen Server, genau
das ist gewollt.

## Docker-Healthcheck

Der eingebaute Healthcheck nutzt `/healthz` und sollte das auch weiter tun: Ein Container, der nur
noch keine Zeitquelle hat, ist nicht kaputt. Willst du dennoch, dass Docker (oder Swarm, Traefik)
den Container als `unhealthy` führt, solange er nicht synchron ist, ersetze den Healthcheck in
deiner Compose-Datei:

```yaml
    healthcheck:
      test: ["CMD", "python3", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('WEB_PORT','8080')+'/readyz',timeout=4)"]
      interval: 30s
      timeout: 5s
      start_period: 10m   # chrony braucht nach dem Start einige Minuten
      retries: 3
```

`urlopen` wirft bei `503` einen Fehler, der Healthcheck schlägt dann fehl. Docker startet einen
`unhealthy` Container von sich aus **nicht** neu – ein Neustart hilft einem Zeitserver ohne
Zeitquelle auch nicht.

## Uptime Kuma und andere Monitore

| Feld | Wert |
|---|---|
| Monitor-Typ | **HTTP(s)** |
| URL | `http://zeitserver.lan:8080/readyz` |
| Akzeptierte Statuscodes | `200-299` (Standard) |
| Intervall | 60 s |
| Wiederholungen | 3 (kurze Aussetzer nach einem Neustart der Zeitdienste lösen keinen Alarm aus) |

Der Statuscode genügt; als **HTTP(s) – Keyword** taugt das Stichwort `"ready"` (mit
Anführungszeichen – `"not_ready"` enthält es so nicht). Anders als die JSON-Abfrage auf
`/api/v1/time` braucht `/readyz` keinen API-Schlüssel. Healthchecks, Gatus, Zabbix, Nagios
(`check_http -u /readyz -e 200`) und Load-Balancer (HAProxy `option httpchk GET /readyz`)
funktionieren genauso.
