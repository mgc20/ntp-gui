# Grafana-Dashboard und Prometheus-Alarme

ntp-gui liefert unter `/metrics` Prometheus-Metriken (`ntpgui_*`). Dazu gibt es zwei fertige
Dateien:

- [`docs/grafana/ntp-gui.json`](../grafana/ntp-gui.json) – Dashboard mit Offset, max. Fehler,
  Frequenz, Stratum, Quellen, Clients, Anfragen, GPS-Satelliten, Temperatur, Schaltsekunden-
  Liste, NTS-Zertifikat und Update-Hinweis;
- [`docs/prometheus/alerts.yml`](../prometheus/alerts.yml) – Alarmregeln: chronyd antwortet
  nicht, nicht synchron, keine nutzbare Quelle, Abweichung bzw. Fehlerschranke zu groß, GPS
  ohne Fix > 10 min, PPS weg, Dienst ausgefallen, NTS-Zertifikat läuft ab, Schaltsekunden-Liste
  läuft ab, neue Version verfügbar.

Ein Test (`tests/test_integrations.py`) prüft, dass jede Metrik aus beiden Dateien wirklich im
`/metrics`-Output steht – Dashboard und Regeln veralten also nicht still.

## 1. Prometheus

Ist ein Dashboard-Passwort gesetzt, braucht `/metrics` einen API-Schlüssel mit Recht
**nur lesen** (**Einstellungen → API-Schlüssel**):

```yaml
# prometheus.yml
rule_files:
  - /etc/prometheus/rules/ntp-gui-alerts.yml   # = docs/prometheus/alerts.yml

scrape_configs:
  - job_name: ntp-gui
    scrape_interval: 30s
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/ntp-gui.key   # enthält nur: ntpg_…
    static_configs:
      - targets: ["zeitserver.lan:8080"]
```

Prometheus schickt den Schlüssel bei jedem Abruf mit – über `http://` im Klartext, für jeden im
selben Netz lesbar. Darum einen eigenen Lese-Schlüssel nur für Prometheus anlegen und entweder
über einen Reverse-Proxy mit TLS abfragen (`scheme: https` im Scrape-Job) oder nur innerhalb eines
vertrauenswürdigen Netzsegments.

`NtpGuiServiceDown` meldet nur Dienste, die laut Einstellungen laufen sollen
(`ntpgui_service_enabled == 1`): gpsd bei ausgeschaltetem GPS, ptp4l/phc2sys ohne PTP und dnsfwd
im DNS-Modus „system“ sind absichtlich gestoppt und lösen keinen Alarm aus.

Die Schwellen in `alerts.yml` sind Vorschläge für GPS bzw. gute LAN-Quellen (Abweichung 10 ms,
Fehlerschranke 100 ms). Wer nur über Internet-NTP synchronisiert, setzt die Abweichung eher
auf 50 ms. Prüfen: `promtool check rules alerts.yml`.

## 2. Grafana

**Dashboards → New → Import**, `ntp-gui.json` hochladen und eine Prometheus-Datenquelle
wählen. Oben im Dashboard:

- **Datenquelle** – welche Prometheus-Instanz;
- **Instanz** – ein oder mehrere Zeitserver (`label_values(ntpgui_up, instance)`); mit „All“
  liegen mehrere Server übereinander, z. B. zum Vergleich zweier GPS-Empfänger.

Panels, die zu ausgeschalteten Funktionen gehören (GPS, NTS-Server, Temperatur, Update-Hinweis),
bleiben leer – die Metriken gibt es nur, wenn die Funktion an ist.

## Metriken für eigene Panels

| Metrik | Bedeutung |
|---|---|
| `ntpgui_synchronised` | 1 = synchron |
| `ntpgui_system_time_offset_seconds` | Abweichung der Systemuhr |
| `ntpgui_max_error_seconds` | Fehlerschranke: \|Offset\| + Root Dispersion + Root Delay/2 |
| `ntpgui_frequency_ppm`, `ntpgui_skew_ppm` | Gangfehler des Quarzes und seine Unsicherheit |
| `ntpgui_stratum` | Stratum |
| `ntpgui_sources`, `ntpgui_sources_usable` | bekannte bzw. genutzte Quellen |
| `ntpgui_source_*{source=…}` | Offset, Erreichbarkeit, Jitter, Auswahl je Quelle |
| `ntpgui_clients`, `ntpgui_ntp_packets_received_total` | Clients und beantwortete Anfragen |
| `ntpgui_gps_*` | Fix-Art, Satelliten, HDOP, Signalstärke (nur mit GPS) |
| `ntpgui_pps_live{device=…}` | 1 = PPS-Pulse kommen an |
| `ntpgui_temperature_celsius` | Temperatur des gewählten Sensors |
| `ntpgui_leapseconds_list_days_left` | Tage bis zum Ablauf der Schaltsekunden-Liste |
| `ntpgui_nts_server_cert_days_left` | Tage bis zum Ablauf des NTS-Zertifikats |
| `ntpgui_update_available` | 1 = neuere Version auf GitHub (nur mit Update-Hinweis) |
| `ntpgui_info{version=…}` | installierte Version |
