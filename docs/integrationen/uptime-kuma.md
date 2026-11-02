# ntp-gui mit Uptime Kuma überwachen

Drei Monitore, von einfach bis gründlich. Zusammen merkst du, ob der Container läuft, ob chrony
synchron ist und ob der NTP-Port im Netz wirklich antwortet.

## 1. HTTP-Monitor mit Stichwort auf `/healthz`

`/healthz` braucht keine Anmeldung und antwortet mit `200 {"status": "ok", "chrony": true}`,
solange chronyd Auskunft gibt – sonst mit `503` und `"degraded"`.

| Feld | Wert |
|---|---|
| Monitor-Typ | **HTTP(s) – Keyword** |
| URL | `http://zeitserver.lan:8080/healthz` |
| Keyword | `"ok"` |
| Intervall | 60 s |
| Wiederholungen | 2 (ein kurzer Neustart der Zeitdienste löst dann keinen Alarm aus) |

Das ist derselbe Check, den Docker als Healthcheck nutzt. Er sagt: Dashboard und chronyd
leben. Er sagt **nicht**, ob die Zeit stimmt.

## 2. JSON-Abfrage: ist die Zeit synchron?

`/api/v1/time` ist klein und meldet `synchronised`. Mit einem Lese-Schlüssel
(**Einstellungen → API-Schlüssel**, Recht **nur lesen**):

| Feld | Wert |
|---|---|
| Monitor-Typ | **HTTP(s) – Json Query** |
| URL | `http://zeitserver.lan:8080/api/v1/time` |
| Json Query | `synchronised` |
| Erwarteter Wert | `true` |
| Header (unter „Headers“) | `{"Authorization": "Bearer ntpg_…"}` |
| Intervall | 60 s, Wiederholungen 5 (nach einem Neustart braucht chrony ein paar Minuten) |

Ist „Vollbild-Uhr ohne Anmeldung“ eingeschaltet, geht `/api/v1/time` auch ohne Schlüssel.
Wer zusätzlich die Genauigkeit überwachen will: Json Query `accuracy < 0.01` (Sekunden),
erwarteter Wert `true` – sofern deine Uptime-Kuma-Version Ausdrücke (JSONata) auswertet.

## 3. NTP-Monitor: antwortet UDP 123?

Die beiden HTTP-Monitore prüfen das Dashboard, nicht den NTP-Dienst selbst. Eine falsche
Portfreigabe, eine Firewall oder ein belegter Port 123 fallen nur auf, wenn wirklich eine
NTP-Anfrage gestellt wird.

**Mit NTP-Monitor (neuere Uptime-Kuma-Versionen, laut Projekt ab 2.5):** Monitor-Typ **NTP**,
Host `zeitserver.lan`, Port `123`. Uptime Kuma stellt dann eine echte NTP-Anfrage.

**Ohne NTP-Monitor – Push von einem anderen Rechner:** Monitor-Typ **Push** anlegen, die
Push-URL kopieren und auf einem Linux-Rechner im LAN per Cron prüfen lassen (Paket
`ntpsec-ntpdate` bringt `ntpdig` mit):

```bash
# crontab -e   – jede Minute eine NTP-Anfrage, nur bei Antwort ein „up“ an Uptime Kuma
* * * * * ntpdig -t 3 zeitserver.lan >/dev/null 2>&1 && curl -fsS -m 10 "https://kuma.lan/api/push/DEIN_TOKEN?status=up&msg=NTP%20ok" >/dev/null
```

Bleibt der Push aus, meldet Uptime Kuma den Monitor nach dem eingestellten Intervall als
ausgefallen.

## Und von innen?

ntp-gui kann Probleme auch selbst melden (Seite **Benachrichtigungen**: ntfy, Gotify, Webhook,
Apprise). Uptime Kuma ergänzt das von außen: Ist der ganze Rechner weg, kann ntp-gui nichts
mehr senden – Uptime Kuma merkt es trotzdem.
