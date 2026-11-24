// Erklärungen für den Dauerbetrieb (1.11): wer meldet was, Bereitschaftsprüfung /readyz und die
// Betriebsmetriken in /metrics. Der Zeitwächter-Ping hat seine Texte in help-notify.js, steht auf der
// Hilfe aber hier (HELP_GROUP_BETRIEB). Wird in help.js in HELP übernommen.
export const HELP_BETRIEB = {
  ops_overview: {
    title: "Betrieb im Blick: was wofür",
    text: "Für den Dauerbetrieb gibt es mehrere Bausteine, die sich ergänzen. **Benachrichtigungen** melden "
      + "Ereignisse (GPS weg, Quelle gewechselt, Dienst ausgefallen) an deine Kanäle – aber nur, solange ntp-gui "
      + "selbst läuft. Der **Zeitwächter-Ping** dreht das um: Ein eigener Wächter (Uptime Kuma, Healthchecks) "
      + "schlägt Alarm, wenn der Ping ausbleibt – auch bei Stromausfall oder gestopptem Container. `/healthz` "
      + "sagt nur, ob chronyd antwortet (für den Docker-Healthcheck), `/readyz`, ob dieser Server gerade Zeit "
      + "verteilen sollte (keepalived, Load-Balancer). `/metrics` liefert Zahlen für Prometheus und Grafana. "
      + "Bekommt ein einzelnes Gerät keine Zeit, hilft die **Fehlersuche** auf der Seite Clients. Was etwas "
      + "hinausschickt (Benachrichtigungen, Zeitwächter-Ping), ist aus, bis du es einrichtest, und geht nur an "
      + "Ziele, die du selbst einträgst.",
  },
  readyz: {
    title: "Bereitschaft (/readyz)",
    text: "`/readyz` antwortet mit **200**, wenn chronyd antwortet, synchronisiert ist (kein Inselbetrieb), gerade "
      + "eine Quelle ausgewählt hat (kein Holdover, kein laufender Holdover-Test) und die Fehlerschranke "
      + "– |Offset| + Root-Dispersion + halber Root-Delay, wie chrony sie rechnet – **unter der Fehlergrenze** "
      + "liegt. Sonst kommt **503**. Die Antwort enthält nur Wahrheitswerte (`chrony`, `synchronised`, "
      + "`source_selected`, `within_limit`), keine Messwerte, und braucht keine Anmeldung. Die Grenze stellst du "
      + "unter **System → Einstellungen → Dashboard & Zugang** (erweitert) ein oder per `READY_MAX_ERROR_MS`: "
      + "Standard 100 ms passt zu Internet-NTP, mit GPS und PPS eher 1 ms. Einen Holdover sieht ntp-gui in der "
      + "regelmäßigen Messung – bis dahin kann ein Messintervall vergehen. `/healthz` bleibt der Lebenszeichen-Test "
      + "für Docker und meldet nur, ob chronyd antwortet. Für keepalived nimmst du `/readyz`, damit ein Server "
      + "ohne Zeitquelle die virtuelle Adresse abgibt.",
  },
  metrics_ops: {
    title: "Betriebsmetriken in /metrics",
    text: "Neben den Messwerten der Uhr, der Quellen, von GPS und PTP stehen in `/metrics` Summen für den "
      + "Betrieb. **Clients**: `ntpgui_clients_monitored`, `ntpgui_clients_quality` (Anzahl je Gütestufe), "
      + "`ntpgui_clients_silent` und die Alarmzähler, je Gruppe `ntpgui_client_group_…` (Kennung wie `g3`, Namen "
      + "nur per Schalter). **Alarmweg**: `ntpgui_notify_channels`, `…_enabled`, `…_failing`, "
      + "`ntpgui_notify_deliveries_total` und `ntpgui_notify_dropped_total`. **Sicherung**: "
      + "`ntpgui_backup_nightly_…` (an, Alter, fehlgeschlagen, gespeichert). **Ereignisse**: "
      + "`ntpgui_events_total` je Art und Stufe. **Holdover-Test**: `ntpgui_holdover_last_…` (Ergebnis, Dauer, "
      + "Abweichung, Drift). **GPS-Automatik**: `ntpgui_gps_autocal_…`. **Zeitwächter-Ping**: "
      + "`ntpgui_heartbeat_…` (an, Fehlversuche in Folge, letzter Erfolg, kritisch gemeldet). Fällt ein Teil aus, "
      + "fehlt nur dieser – `/metrics` bleibt erreichbar. Fertige Alarmregeln liegen im Repository unter "
      + "`docs/prometheus/alerts.yml`, ein Grafana-Dashboard unter `docs/grafana/ntp-gui.json`.",
  },
};

export const HELP_GROUP_BETRIEB = {
  id: "betrieb",
  title: "Betrieb und Überwachung",
  keys: ["ops_overview", "heartbeat", "heartbeat_mode", "heartbeat_status", "readyz", "metrics_ops"],
  see: ["troubleshoot", "metrics_privacy", "notify", "diag_page"],
};
