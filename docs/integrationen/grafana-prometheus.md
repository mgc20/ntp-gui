# Grafana-Dashboard und Prometheus-Alarme

ntp-gui liefert unter `/metrics` Prometheus-Metriken (`ntpgui_*`). Dazu gibt es zwei fertige
Dateien:

- [`docs/grafana/ntp-gui.json`](../grafana/ntp-gui.json) – Dashboard mit Offset, max. Fehler,
  Frequenz, Stratum, Quellen, Clients, Anfragen, GPS-Empfang, Temperatur, Schaltsekunden-
  Liste, NTS-Zertifikat und Update-Hinweis, dazu (ab 1.11) Zeilen „Clients und Betrieb“:
  Client-Uhrgüte, Abweichung je Client-Gruppe, Benachrichtigungen, nächtliche Sicherung,
  Ereignisse, Holdover-Test, GPS-Automatik und Zeitwächter-Ping;
- [`docs/prometheus/alerts.yml`](../prometheus/alerts.yml) – Alarmregeln: chronyd antwortet
  nicht, nicht synchron, keine nutzbare Quelle, Abweichung bzw. Fehlerschranke zu groß, GPS
  ohne Fix > 10 min, PPS weg, Dienst ausgefallen, NTS-Zertifikat läuft ab, Schaltsekunden-Liste
  läuft ab, neue Version verfügbar; ab 1.11 außerdem Client-Uhren außer Toleranz, Client-Gruppe
  fragt nicht mehr, Benachrichtigungskanal stellt nicht zu bzw. Warteschlange hängt, nächtliche
  Sicherung fehlt oder ist alt, kritisches Ereignis, Holdover-Test gescheitert, GPS-Automatik
  wartet auf dich, Zeitwächter-Ping scheitert.

Ein Test (`tests/test_integrations.py`) prüft, dass jede Metrik aus beiden Dateien wirklich im
`/metrics`-Output steht – Dashboard und Regeln veralten also nicht still.

## 1. Prometheus

Ist ein Dashboard-Passwort gesetzt, braucht `/metrics` einen API-Schlüssel mit Recht
**nur lesen** (**Einstellungen → Dashboard & Zugang → API-Schlüssel**):

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
| `ntpgui_gps_running`, `ntpgui_gps_fix_mode`, `ntpgui_gps_hdop`, `ntpgui_gps_snr_avg_db` | gpsd erreichbar, Fix-Art, HDOP als Stufe (1, 2, 5, 10, 20), mittlere Signalstärke (nur mit GPS) |
| `ntpgui_gps_error_bound_seconds` | Fehlerschranke, mit der chrony das GPS rechnet (ohne PPS gemessen, ab 1.5) |
| `ntpgui_gps_reception_level`, `ntpgui_gps_unstable` | Empfang über 24 h (0 gut, 1 mäßig, 2 schwach) bzw. 1 = Fix flattert („unstet“) |
| `ntpgui_gnss_stage`, `ntpgui_gps_locked` | GNSS-Störungserkennung (0 unauffällig … 3 Störung) bzw. 1 = GPS gesperrt |
| `ntpgui_source_loops` | Zeitquellen, die auf ntp-gui selbst zeigen (DNS-/NAT-Schleife) |
| `ntpgui_holdover_test_running` | 1 = Holdover-Test läuft (Clients bekommen ungenauere Zeit) |
| `ntpgui_pps_live{device=…}` | 1 = PPS-Pulse kommen an |
| `ntpgui_temperature_celsius` | Temperatur des gewählten Sensors |
| `ntpgui_pi_undervoltage` | 1 = Raspberry Pi meldet gerade Unterspannung (nur auf dem Pi) |
| `ntpgui_pi_throttled` | 1 = Raspberry Pi drosselt gerade den Takt (nur auf dem Pi, mit Firmware-Bitfeld) |
| `ntpgui_leapseconds_list_days_left` | Tage bis zum Ablauf der Schaltsekunden-Liste |
| `ntpgui_nts_server_cert_days_left` | Tage bis zum Ablauf des NTS-Zertifikats |
| `ntpgui_update_available` | 1 = neuere Version auf GitHub (nur mit Update-Hinweis) |
| `ntpgui_info{version=…}` | installierte Version |
| `ntpgui_clients_monitored` | Geräte in der passiven Client-Messung |
| `ntpgui_clients_quality{grade=…}` | Geräte je Uhrgüte: `very_good` (ab 85), `good` (ab 70), `moderate` (ab 50), `poor`, `unrated` |
| `ntpgui_clients_silent` | Geräte, die nicht mehr fragen (deutlich länger als üblich oder über 24 h) |
| `ntpgui_clients_offset_alarm`, `ntpgui_clients_silent_alarm` | Geräte mit offenem Abweichungs- bzw. Stille-Alarm |
| `ntpgui_client_group_*{group_id=…,group=…}` | je Client-Gruppe: Geräte (`_devices`), aktiv in 24 h (`_active`), still (`_silent`), messbar (`_measured`), Median der Abweichung (`_median_offset_seconds`), Anteil „gut“ (`_good_ratio`), Median der Uhrgüte (`_quality_median`); `group_id="none"` = ohne Gruppe |
| `ntpgui_notify_channels{type=…}`, `_channels_enabled`, `_channels_failing`, `_queue` | Benachrichtigungskanäle je Art (webhook, ntfy, gotify, apprise): angelegt, eingeschaltet, letzter Versuch fehlgeschlagen, wartende Meldungen |
| `ntpgui_notify_deliveries_total{type=…,result=ok\|failed}`, `ntpgui_notify_dropped_total{type=…}` | Zustellversuche bzw. verworfene Meldungen seit dem Start |
| `ntpgui_notify_running` | 1 = Versand läuft |
| `ntpgui_backup_nightly_enabled`, `_stored`, `_age_seconds`, `_failed` | nächtliche Sicherung: an, Anzahl, Alter der jüngsten (fehlt ohne Sicherung), 1 = letzter Versuch seit dem Start fehlgeschlagen |
| `ntpgui_events_total{kind=…,level=…}` | ins Ereignisprotokoll geschriebene Ereignisse je Art und Stufe (`info`, `warn`, `crit`) seit dem Start |
| `ntpgui_holdover_last_result{outcome=…}` | Ergebnis des letzten Holdover-Tests (`done`, `limit`, `invalid`, `restart`, `aborted`); dazu `_last_deviation_seconds`, `_last_duration_seconds`, `_last_drift_ppm`, `_last_end_timestamp_seconds`, `_last_free_running` |
| `ntpgui_gps_autocal_mode{mode=…}`, `ntpgui_gps_autocal_phase{phase=…}` | GPS-Automatik: Modus (`off`, `suggest`, `auto`) und Phase der letzten stündlichen Prüfung; dazu `_active_changes`, `_last_change_timestamp_seconds` und `ntpgui_gps_offset_seconds` (nur mit GPS) |
| `ntpgui_heartbeat_enabled`, `_consecutive_failures`, `_last_success_timestamp_seconds`, `_reported_down` | Zeitwächter-Ping: eingerichtet, Fehlschläge in Folge, letzter Erfolg, 1 = zuletzt „kritisch“ gemeldet |

## Datenschutz in den Metriken

`/metrics` enthält nur Summen und feste Werte: keine Client-Adressen, keine Gerätenamen, keine
Namen oder Adressen von Benachrichtigungskanälen, keine Adresse des Zeitwächters und keine
Dateinamen. Die einzigen frei vergebenen Texte sind die Namen deiner Client-Gruppen (Label
`group`). Wer sie in einem zentralen Monitoring nicht sehen will, schaltet unter
**Einstellungen → Dashboard & Zugang → Gruppennamen in /metrics** (erweitert) bzw. mit
`METRICS_GROUP_NAMES=false` ab; dann bleibt nur die Kennung (`group_id`, z. B. `g3`).

Satellitenzahlen stehen ab 1.11 nicht mehr in `/metrics` (`ntpgui_gps_satellites_used` und
`ntpgui_gps_satellites_seen` entfallen), HDOP nur noch als Stufe (1, 2, 5, 10, 20): Als
Zeitreihe markiert jeder Sprung den Auf- oder Untergang eines Satelliten und grenzt so die
Region ein. Für den Empfang taugt `ntpgui_gps_reception_level`; die genauen Zahlen zeigt das
Dashboard weiterhin auf der GPS-Seite.

Die Zähler (`*_total`) gelten seit dem Start des Containers und beginnen nach einem Neustart
bei 0 – Prometheus erkennt das in `rate()` und `increase()` von selbst.
