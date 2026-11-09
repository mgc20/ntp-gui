# ntp-gui in Home Assistant

Home Assistant liest den Zustand des Zeitservers über die REST-Schnittstelle `/api/v1/status` –
ohne Zusatz-Integration, ohne MQTT, ohne dass ntp-gui irgendetwas nach außen schickt. Home
Assistant fragt, ntp-gui antwortet. Eine einzige Anfrage pro Minute füllt alle Sensoren.

## 1. API-Schlüssel anlegen

Im Dashboard unter **Einstellungen → Dashboard & Zugang → API-Schlüssel** einen Schlüssel mit Recht **nur lesen**
anlegen, z. B. „Home Assistant“. Er wird nur einmal angezeigt (`ntpg_…`). Ein Lese-Schlüssel
kann nichts ändern – geht er verloren, widerrufst du ihn einfach.

In `secrets.yaml` von Home Assistant:

```yaml
ntpgui_auth: "Bearer ntpg_DEIN_SCHLUESSEL"
```

> Ohne Dashboard-Passwort geht es auch ohne Schlüssel. Mit Schlüssel bleibt die Konfiguration
> aber gültig, wenn du später ein Passwort setzt.

> **Der Schlüssel reist im Klartext.** ntp-gui spricht selbst nur HTTP. Bei `http://` kann jeder
> im selben Netz den `Authorization`-Header mitlesen – und ein Lese-Schlüssel zeigt in
> `/api/v1/status` Client-Adressen, Quellennamen und Einstellungen. Darum: entweder per
> `https://` über einen Reverse-Proxy (Caddy, Traefik, nginx) abfragen oder nur innerhalb
> eines vertrauenswürdigen Netzsegments. Und für jede Integration einen eigenen Lese-Schlüssel
> anlegen – dann widerrufst du bei Bedarf genau den einen.

## 2. REST-Sensoren (configuration.yaml)

```yaml
rest:
  - resource: http://zeitserver.lan:8080/api/v1/status
    headers:
      Authorization: !secret ntpgui_auth
    scan_interval: 60
    timeout: 10
    # Mit Reverse-Proxy (empfohlen, Schlüssel verschlüsselt):
    #   resource: https://zeitserver.example.lan/api/v1/status
    #   verify_ssl: true
    sensor:
      - name: "Zeitserver Abweichung"
        unique_id: ntpgui_offset
        # chrony liefert Sekunden – für die Anzeige in Mikrosekunden
        value_template: "{{ ((value_json.tracking.system_time_offset | float(0)) * 1000000) | round(1) }}"
        unit_of_measurement: "µs"
        state_class: measurement
        icon: mdi:clock-time-four-outline

      - name: "Zeitserver Stratum"
        unique_id: ntpgui_stratum
        value_template: "{{ value_json.tracking.stratum | int(16) }}"
        state_class: measurement
        icon: mdi:layers-triple-outline

      - name: "Zeitserver max. Fehler"
        unique_id: ntpgui_max_error
        # |Offset| + Root Dispersion + Root Delay / 2 – die ehrliche Fehlerschranke
        value_template: >-
          {% set t = value_json.tracking %}
          {{ (((t.system_time_offset | float(0)) | abs + (t.root_dispersion | float(0))
              + (t.root_delay | float(0)) / 2) * 1000) | round(3) }}
        unit_of_measurement: "ms"
        state_class: measurement

      - name: "Zeitserver Frequenz"
        unique_id: ntpgui_frequency
        value_template: "{{ value_json.tracking.frequency_ppm | float(0) | round(3) }}"
        unit_of_measurement: "ppm"
        state_class: measurement

      - name: "Zeitserver Referenz"
        unique_id: ntpgui_reference
        value_template: "{{ value_json.tracking.ref_name | default('keine') }}"

      - name: "Zeitserver Clients"
        unique_id: ntpgui_clients
        value_template: "{{ value_json.client_count | int(0) }}"
        state_class: measurement
        icon: mdi:lan

      - name: "Zeitserver GPS-Satelliten"
        unique_id: ntpgui_gps_sats
        value_template: "{{ value_json.gps.satellites_used | default(0) | int(0) }}"
        state_class: measurement
        icon: mdi:satellite-variant

      - name: "Zeitserver Hinweise"
        unique_id: ntpgui_warnings
        # Anzahl der Warnungen und Störungen, wie das Badge im Dashboard
        value_template: >-
          {{ value_json.insights | selectattr('level', 'in', ['warn', 'crit']) | list | count }}
        state_class: measurement
        icon: mdi:alert-circle-outline

    binary_sensor:
      - name: "Zeitserver synchron"
        unique_id: ntpgui_synchronised
        value_template: "{{ value_json.tracking.synchronised | default(false) }}"
        device_class: connectivity

      - name: "Zeitserver GPS-Fix"
        unique_id: ntpgui_gps_fix
        # gpsd-Modus 2 = 2D-Fix, 3 = 3D-Fix
        value_template: "{{ (value_json.gps.mode | default(0) | int(0)) >= 2 }}"
        device_class: connectivity

      - name: "Zeitserver Update verfügbar"
        unique_id: ntpgui_update
        # nur mit eingeschaltetem Update-Hinweis (Einstellungen → Dashboard & Zugang)
        value_template: "{{ value_json.update.available | default(false) }}"
        device_class: update
```

Adresse und Port (`zeitserver.lan:8080`) an deine Installation anpassen. Hast du kein GPS,
lass die beiden GPS-Sensoren weg.

## 3. Template-Sensoren

Aus den REST-Sensoren lassen sich lesbare Zustände bauen – etwa für eine Karte oder eine
Sprachansage:

```yaml
template:
  - sensor:
      - name: "Zeitserver Zustand"
        unique_id: ntpgui_state
        state: >-
          {% if is_state('binary_sensor.zeitserver_synchron', 'off') %}
            nicht synchron
          {% elif states('sensor.zeitserver_stratum') | int(16) == 1 %}
            Stratum 1 ({{ states('sensor.zeitserver_referenz') }})
          {% else %}
            synchron, Stratum {{ states('sensor.zeitserver_stratum') }}
          {% endif %}
        icon: mdi:clock-check-outline

      - name: "Zeitserver Genauigkeit"
        unique_id: ntpgui_quality
        # grob wie die Ampel der Vollbild-Uhr: unter 1 ms sehr gut, unter 100 ms brauchbar
        state: >-
          {% set e = states('sensor.zeitserver_max_fehler') | float(999) %}
          {{ 'sehr gut' if e < 1 else ('gut' if e < 10 else ('brauchbar' if e < 100 else 'schlecht')) }}

  - binary_sensor:
      - name: "Zeitserver Abweichung zu groß"
        unique_id: ntpgui_offset_problem
        # 10 ms: für GPS/LAN viel. Nur über Internet-NTP eher 50 ms nehmen.
        state: "{{ (states('sensor.zeitserver_abweichung') | float(0)) | abs > 10000 }}"
        device_class: problem
        delay_on: "00:10:00"
```

## 4. Automation: Bescheid geben, wenn die Zeit wegläuft

```yaml
automation:
  - alias: "Zeitserver nicht synchron"
    trigger:
      - platform: state
        entity_id: binary_sensor.zeitserver_synchron
        to: "off"
        for: "00:10:00"
    action:
      - service: notify.notify
        data:
          title: "Zeitserver"
          message: "Seit 10 Minuten nicht synchron – Dashboard → Quellen prüfen."
```

ntp-gui kann solche Meldungen auch selbst schicken (Seite **Benachrichtigungen**, z. B. als
Webhook direkt an eine Home-Assistant-Automation). Die REST-Sensoren lohnen sich trotzdem: Du
bekommst Verlaufskurven in Home Assistant und kannst Zustände kombinieren.

## Gut zu wissen

- **Leichter geht's mit `/api/v1/time`:** Für einen einzelnen Sensor (Uhrzeit, `synchronised`,
  `accuracy` in Sekunden, `stratum`, `source_kind`) reicht dieser kleine Endpunkt. Er ist
  ohne Anmeldung erreichbar, wenn „Vollbild-Uhr ohne Anmeldung“ eingeschaltet ist.
- **`/api/v1` bleibt stabil:** Innerhalb von 1.x kommen höchstens Felder hinzu, nichts wird
  umbenannt. `GET /api/v1` listet alle Endpunkte.
- **Einheiten:** Alle Zeiten in der API sind Sekunden (`system_time_offset`, `root_delay` …),
  Frequenzen in ppm.
- **Kein MQTT nötig:** ntp-gui baut keine Verbindung zu Home Assistant auf. Fällt Home
  Assistant aus, merkt der Zeitserver davon nichts.
