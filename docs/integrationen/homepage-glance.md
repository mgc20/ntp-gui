# ntp-gui auf Homepage und Glance

Beide Startseiten lesen JSON-Schnittstellen per „Custom API“-Widget. ntp-gui liefert alles
Nötige unter `/api/v1/status`; ein API-Schlüssel mit Recht **nur lesen** genügt
(**Einstellungen → Dashboard & Zugang → API-Schlüssel**). Ohne Dashboard-Passwort geht es auch ohne Schlüssel.

Der Schlüssel steht in der Widget-Konfiguration – leg ihn als Umgebungsvariable bzw. Secret
ab, nicht im Klartext in einem Repository.

> **Der Schlüssel reist im Klartext.** ntp-gui spricht selbst nur HTTP. Bei `http://` kann jeder
> im selben Netz den `Authorization`-Header mitlesen – und ein Lese-Schlüssel zeigt in
> `/api/v1/status` Client-Adressen, Quellennamen und Einstellungen. Darum: entweder per
> `https://` über einen Reverse-Proxy (Caddy, Traefik, nginx) abfragen oder nur innerhalb
> eines vertrauenswürdigen Netzsegments. Und für jede Integration einen eigenen Lese-Schlüssel
> anlegen – dann widerrufst du bei Bedarf genau den einen.
>
> Die Beispiele unten nutzen `http://zeitserver.lan:8080` der Kürze halber. Mit Proxy wird daraus
> z. B. `https://zeitserver.example.lan`.

## Homepage (gethomepage.dev)

`services.yaml`:

```yaml
- Infrastruktur:
    - Zeitserver:
        icon: mdi-clock-check-outline
        href: http://zeitserver.lan:8080/
        description: chrony + GPS
        siteMonitor: http://zeitserver.lan:8080/healthz
        widget:
          type: customapi
          url: http://zeitserver.lan:8080/api/v1/status
          refreshInterval: 30000
          headers:
            Authorization: Bearer {{HOMEPAGE_VAR_NTPGUI_KEY}}
          mappings:
            - field:
                tracking: synchronised
              label: Synchron
              remap:
                - value: true
                  to: ja
                - any: true
                  to: NEIN
            - field:
                tracking: stratum
              label: Stratum
              format: number
            - field:
                tracking: system_time_offset
              label: Abweichung
              format: float
              scale: 1000000
              suffix: " µs"
            - field: client_count
              label: Clients
              format: number
```

`HOMEPAGE_VAR_NTPGUI_KEY=ntpg_…` als Umgebungsvariable im Homepage-Container setzen.
Homepage zeigt höchstens vier Felder pro Widget; statt `client_count` passt z. B. auch
`gps.satellites_used` (Satelliten) oder `tracking.ref_name` (Referenz).

`siteMonitor` auf `/healthz` färbt die Kachel rot, wenn chrony nicht antwortet – `/healthz`
braucht keine Anmeldung.

## Glance

`glance.yml`, Abschnitt `widgets`:

```yaml
- type: custom-api
  title: Zeitserver
  title-url: http://zeitserver.lan:8080/
  cache: 1m
  url: http://zeitserver.lan:8080/api/v1/status
  headers:
    Authorization: Bearer ${NTPGUI_KEY}
  template: |
    <div class="flex justify-between text-center">
      <div>
        {{ if .JSON.Bool "tracking.synchronised" }}
          <div class="color-positive size-h3">synchron</div>
        {{ else }}
          <div class="color-negative size-h3">NICHT synchron</div>
        {{ end }}
        <div class="size-h6">ZUSTAND</div>
      </div>
      <div>
        <div class="color-highlight size-h3">{{ .JSON.Int "tracking.stratum" }}</div>
        <div class="size-h6">STRATUM</div>
      </div>
      <div>
        <div class="color-highlight size-h3">{{ printf "%.6f" (.JSON.Float "tracking.system_time_offset") }} s</div>
        <div class="size-h6">ABWEICHUNG</div>
      </div>
      <div>
        <div class="color-highlight size-h3">{{ .JSON.Int "client_count" }}</div>
        <div class="size-h6">CLIENTS</div>
      </div>
    </div>
    <div class="size-h6 color-subdue margin-top-10">Referenz: {{ .JSON.String "tracking.ref_name" }}</div>
```

`NTPGUI_KEY=ntpg_…` als Umgebungsvariable im Glance-Container setzen (Glance ersetzt
`${…}` in der Konfiguration).

## Homarr und andere

Alles mit einem generischen JSON-Widget funktioniert genauso: `GET /api/v1/status` mit
`Authorization: Bearer ntpg_…`. Die wichtigsten Felder:

| Feld | Bedeutung |
|---|---|
| `tracking.synchronised` | `true`, wenn chrony mit einer Quelle synchron ist |
| `tracking.stratum` | 1 = direkt an GPS/PPS, 2 = eine NTP-Stufe dahinter |
| `tracking.system_time_offset` | Abweichung der Systemuhr in Sekunden |
| `tracking.ref_name` | aktuelle Referenz (z. B. `PPS`, `ptbtime1.ptb.de`) |
| `client_count` | bekannte NTP-Clients |
| `gps.satellites_used` | benutzte Satelliten (nur mit GPS) |
| `update.available` | `true`, wenn der Update-Hinweis eine neuere Version kennt |
| `insights` | Liste der Hinweise mit `level` (`info`, `warn`, `crit`) und `title` |

Für eine kleine Anzeige ohne die großen Listen (Quellen, Clients) reicht `/api/v1/time`
(`synchronised`, `accuracy`, `stratum`, `source_kind`).
