"""Prometheus-Metriken zum Betrieb (1.11): Client-Güte und Gruppen, Benachrichtigungen, nächtliche
Sicherung, Ereignisse, Holdover-Test, GPS-Automatik und Zeitwächter-Ping.

Jede Funktion liefert Zeilen (Name, Wert, Hilfetext, Art, Labels) – server.build_metrics() schreibt sie
mit HELP/TYPE ins Textformat. Die Bausteine sind rein (Eingaben werden übergeben), collect() holt die
Daten aus den Modulen und lässt einen fehlerhaften Teil einfach weg.

Datenschutz: Labels tragen nur feste Werte (Güte-Stufe, Kanal-Art, Stufe, Phase …) und – nur wenn
metrics_group_names eingeschaltet ist (Standard aus) – die selbst vergebenen Gruppennamen. Nie Client-Adressen, Gerätenamen, Kanal-Namen
oder -Adressen, nie Dateinamen. /metrics liest nur Zwischenstände und rechnet nichts Teures neu.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable

Row = tuple[str, Any, str, str, str]

GRADE_KEYS = ("very_good", "good", "moderate", "poor", "unrated")
HOLDOVER_OUTCOMES = ("done", "limit", "invalid", "restart", "aborted")
EVENT_LEVELS = ("info", "warn", "crit")


def escape_label(value: Any) -> str:
    """Prometheus: Backslash, Anführungszeichen und Zeilenumbruch maskieren."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**pairs: Any) -> str:
    return "{" + ",".join(f'{key}="{escape_label(value)}"' for key, value in pairs.items()) + "}"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def grade_key(score: Any) -> str:
    """Uhrgüte 0–100 → feste Stufe (Schwellen wie clients3.grade)."""
    score = _num(score)
    if score is None:
        return "unrated"
    if score >= 85:
        return "very_good"
    if score >= 70:
        return "good"
    if score >= 50:
        return "moderate"
    return "poor"


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def client_rows(clients: dict[str, dict], qualities: dict[str, dict], silent: Callable[[dict, float], Any],
                offset_alarms: int, silent_alarms: int, view: dict | None, names: bool,
                now: float | None = None, listening: float | None = None) -> list[Row]:
    """Summen über die passiv gemessenen Geräte und je Gruppe. view: clients3.view(…, by="group").
    listening: wie lange die Messung schon mithört (clientmon.listening_seconds) – Alarme auf „Gruppe fragt
    nicht mehr“ brauchen das, denn nach einer Pause ist jedes gespeicherte „zuletzt gesehen“ alt."""
    now = time.time() if now is None else now
    rows: list[Row] = []
    entries = {ip: e for ip, e in (clients or {}).items() if isinstance(e, dict)}
    rows.append(("ntpgui_clients_monitored", len(entries),
                 "Devices seen by the passive client measurement", "gauge", ""))
    listening = _num(listening)
    if listening is not None:
        rows.append(("ntpgui_clients_listening_seconds", round(listening),
                     "Seconds the passive client measurement has been listening without a break", "gauge", ""))
    grades = dict.fromkeys(GRADE_KEYS, 0)
    for ip in entries:
        grades[grade_key((qualities.get(ip) or {}).get("score"))] += 1
    for key in GRADE_KEYS:
        rows.append(("ntpgui_clients_quality", grades[key],
                     "Devices per clock quality grade (very_good >= 85, good >= 70, moderate >= 50, poor, unrated)",
                     "gauge", _labels(grade=key)))
    quiet = 0
    for entry in entries.values():
        try:
            quiet += 1 if silent(entry, now) else 0
        except Exception:
            continue
    rows.append(("ntpgui_clients_silent", quiet,
                 "Devices that stopped asking for time (much longer than their usual interval, or over 24 h)",
                 "gauge", ""))
    rows.append(("ntpgui_clients_offset_alarm", offset_alarms,
                 "Devices with an open offset alarm (global client threshold or own rule)", "gauge", ""))
    rows.append(("ntpgui_clients_silent_alarm", silent_alarms,
                 "Devices with an open silence alarm (own rule)", "gauge", ""))
    rows.extend(group_rows(view, names))
    return rows


GROUP_METRICS = (
    ("ntpgui_client_group_devices", "total", "Devices per client group"),
    ("ntpgui_client_group_active", "active", "Devices per client group that asked within 24 h"),
    ("ntpgui_client_group_silent", "silent", "Silent devices per client group"),
    ("ntpgui_client_group_measured", "measured", "Devices per client group with a measurable offset"),
    ("ntpgui_client_group_median_offset_seconds", "median_offset",
     "Median absolute clock offset of the measured devices per client group"),
    ("ntpgui_client_group_good_ratio", "good_share",
     "Share of measured devices per client group within the good offset limit (0-1)"),
    ("ntpgui_client_group_quality_median", "score_median", "Median clock quality score per client group (0-100)"),
)


def group_rows(view: dict | None, names: bool) -> list[Row]:
    """Je Gruppe ein Satz Zahlen. Label group_id (g<Kennung> bzw. none für „ohne Gruppe“), dazu group mit dem
    Namen, wenn names an ist. Nie Mitglieder, nie das schlechteste Gerät."""
    buckets = [b for b in (view or {}).get("groups") or [] if isinstance(b, dict)]
    labelled = []
    for bucket in buckets:
        key = str(bucket.get("key") or "")
        if key != "none" and not (key.startswith("g") and key[1:].isdigit()):
            continue   # nur Gruppen nach Netz – andere Sichten (VLAN, Software) gehören nicht hierher
        pairs: dict[str, Any] = {"group_id": key}
        if names:
            pairs["group"] = "" if key == "none" else str(bucket.get("label") or "")
        labelled.append((_labels(**pairs), bucket))
    rows: list[Row] = []
    for name, field, help_text in GROUP_METRICS:
        for labels, bucket in labelled:
            value = _num(bucket.get(field))
            if value is not None:
                rows.append((name, value, help_text, "gauge", labels))
    return rows


# ---------------------------------------------------------------------------
# Benachrichtigungen, Sicherung, Ereignisse
# ---------------------------------------------------------------------------

def notify_rows(summary: dict[str, dict], running: bool | None) -> list[Row]:
    """Je Kanal-Art (feste Liste): Kanäle, fehlschlagende Kanäle, Warteschlange, Zustellungen seit dem Start."""
    rows: list[Row] = []
    if running is not None:
        rows.append(("ntpgui_notify_running", 1 if running else 0,
                     "1 when the notification dispatcher runs", "gauge", ""))
    kinds = sorted(summary or {})
    spec = (
        ("ntpgui_notify_channels", "channels", "Configured notification channels per type", "gauge"),
        ("ntpgui_notify_channels_enabled", "enabled", "Enabled notification channels per type", "gauge"),
        ("ntpgui_notify_channels_failing", "failing",
         "Enabled channels per type whose last delivery attempt failed", "gauge"),
        ("ntpgui_notify_queue", "queued", "Messages waiting for delivery or retry per channel type", "gauge"),
        ("ntpgui_notify_dropped_total", "dropped",
         "Messages dropped (rate limit, full queue, retries exhausted) per channel type since start", "counter"),
    )
    for name, field, help_text, kind in spec:
        for channel_type in kinds:
            rows.append((name, int((summary[channel_type] or {}).get(field) or 0), help_text, kind,
                         _labels(type=channel_type)))
    for channel_type in kinds:
        for result in ("ok", "failed"):
            rows.append(("ntpgui_notify_deliveries_total", int((summary[channel_type] or {}).get(result) or 0),
                         "Delivery attempts per channel type and result since start", "counter",
                         _labels(type=channel_type, result=result)))
    return rows


def backup_rows(info: dict) -> list[Row]:
    rows: list[Row] = [("ntpgui_backup_nightly_enabled", 1 if info.get("enabled") else 0,
                        "1 when the nightly backup is switched on", "gauge", "")]
    if not info.get("enabled"):
        return rows
    rows.append(("ntpgui_backup_nightly_stored", int(info.get("stored") or 0),
                 "Nightly backups kept in the data directory", "gauge", ""))
    age = _num(info.get("age"))
    if age is not None:
        rows.append(("ntpgui_backup_nightly_age_seconds", round(age, 1),
                     "Age of the newest nightly backup (absent while there is none)", "gauge", ""))
    rows.append(("ntpgui_backup_nightly_failed", 1 if info.get("failed") else 0,
                 "1 when the last nightly backup attempt since start failed", "gauge", ""))
    return rows


def event_rows(counts: dict[tuple[str, str], int], kinds: Iterable[str]) -> list[Row]:
    """ntpgui_events_total{kind,level}: alle festen Arten × Stufen, auch mit 0 (Zähler ab Start)."""
    rows: list[Row] = []
    for kind in kinds:
        for level in EVENT_LEVELS:
            rows.append(("ntpgui_events_total", int(counts.get((kind, level), 0)),
                         "Events written to the event log per kind and level since start", "counter",
                         _labels(kind=kind, level=level)))
    return rows


# ---------------------------------------------------------------------------
# Holdover, GPS-Automatik, Zeitwächter-Ping
# ---------------------------------------------------------------------------

def holdover_rows(last: dict | None) -> list[Row]:
    """Ergebnis des letzten abgeschlossenen Holdover-Tests (fehlt, solange es keinen gab)."""
    if not isinstance(last, dict) or last.get("outcome") not in HOLDOVER_OUTCOMES:
        return []
    rows: list[Row] = []
    for outcome in HOLDOVER_OUTCOMES:
        rows.append(("ntpgui_holdover_last_result", 1 if last.get("outcome") == outcome else 0,
                     "Outcome of the last holdover test (done, limit, invalid, restart, aborted)", "gauge",
                     _labels(outcome=outcome)))
    dev = _num(last.get("deviation_ms"))
    if dev is not None:
        rows.append(("ntpgui_holdover_last_deviation_seconds", dev / 1000.0,
                     "Clock deviation at the end of the last holdover test", "gauge", ""))
    duration = _num(last.get("duration_s"))
    if duration is not None:
        rows.append(("ntpgui_holdover_last_duration_seconds", duration,
                     "Duration of the last holdover test", "gauge", ""))
    drift = _num(last.get("drift_ppm"))
    if drift is not None:
        rows.append(("ntpgui_holdover_last_drift_ppm", drift, "Drift measured in the last holdover test",
                     "gauge", ""))
    ended = _num(last.get("ended"))
    if ended is not None:
        rows.append(("ntpgui_holdover_last_end_timestamp_seconds", round(ended),
                     "Unix time when the last holdover test ended", "gauge", ""))
    rows.append(("ntpgui_holdover_last_free_running", 0 if last.get("include_network") is False else 1,
                 "1 when the last holdover test deselected network sources too (real free run)", "gauge", ""))
    return rows


def autocal_rows(state: dict | None, modes: Iterable[str], phases: Iterable[str],
                 offset: Any = None) -> list[Row]:
    if not isinstance(state, dict):
        return []
    rows: list[Row] = []
    for mode in modes:
        rows.append(("ntpgui_gps_autocal_mode", 1 if state.get("mode") == mode else 0,
                     "GPS auto calibration mode (off, suggest, auto)", "gauge", _labels(mode=mode)))
    for phase in phases:
        rows.append(("ntpgui_gps_autocal_phase", 1 if state.get("phase") == phase else 0,
                     "GPS auto calibration phase (from the last hourly check)", "gauge", _labels(phase=phase)))
    rows.append(("ntpgui_gps_autocal_active_changes", int(state.get("active_changes") or 0),
                 "Automatic offset changes that can still be rolled back", "gauge", ""))
    last = _num(state.get("last_change"))
    if last is not None:
        rows.append(("ntpgui_gps_autocal_last_change_timestamp_seconds", round(last),
                     "Unix time of the last automatic offset change or rollback", "gauge", ""))
    offset = _num(offset)
    if offset is not None:
        rows.append(("ntpgui_gps_offset_seconds", offset, "Configured GPS offset (chrony refclock offset)",
                     "gauge", ""))
    return rows


def heartbeat_rows(status: dict | None) -> list[Row]:
    """Zeitwächter-Ping: nur Schalter, Fehlschläge in Folge, letzter Erfolg und gemeldeter Zustand –
    nie die Adresse."""
    if not isinstance(status, dict):
        return []
    rows: list[Row] = [("ntpgui_heartbeat_enabled", 1 if status.get("enabled") else 0,
                        "1 when the heartbeat ping to an own monitor is configured", "gauge", "")]
    if not status.get("enabled"):
        return rows
    rows.append(("ntpgui_heartbeat_consecutive_failures", int(status.get("failures") or 0),
                 "Heartbeat pings that failed in a row", "gauge", ""))
    last_ok = _num(status.get("last_ok"))
    if last_ok is not None:
        rows.append(("ntpgui_heartbeat_last_success_timestamp_seconds", round(last_ok),
                     "Unix time of the last heartbeat ping the monitor accepted", "gauge", ""))
    if status.get("last_state") in ("up", "down"):
        rows.append(("ntpgui_heartbeat_reported_down", 1 if status.get("last_state") == "down" else 0,
                     "1 when the last heartbeat reported a critical state", "gauge", ""))
    return rows


# ---------------------------------------------------------------------------
# Zusammentragen
# ---------------------------------------------------------------------------

def _part(rows: list[Row], fn: Callable[[], list[Row]]) -> None:
    try:
        rows.extend(fn())
    except Exception as exc:  # ein kaputter Teil darf /metrics nie verhindern
        print(f"[web] Metriken unvollständig: {type(exc).__name__}: {exc}", flush=True)


def collect(cfg: dict, state_watch: Any = None) -> list[Row]:
    """Alle Betriebsmetriken. state_watch: server.STATE_WATCH (offene Alarme der allgemeinen Client-Schwelle)."""
    import autocal
    import backup
    import clientinfo
    import clientmon
    import clients3
    import events
    import heartbeat
    import holdover
    import notify

    rows: list[Row] = []

    def clients_part() -> list[Row]:
        status = clientmon.status()
        if not status.get("available"):
            return []
        snap = clientmon.private_snapshot()
        rule_map = clients3.rules()
        open_offset = {ip for ip, r in rule_map.items() if ((r or {}).get("state") or {}).get("offset")}
        open_silent = {ip for ip, r in rule_map.items() if ((r or {}).get("state") or {}).get("silent")}
        if state_watch is not None:
            try:
                open_offset |= set(state_watch.client_alarm_ips())
            except Exception:
                pass
        qualities = clients3.quality_all()
        view = clients3.view(snap, "group", {}, rule_map, qualities, now=time.time())
        return client_rows(snap, qualities, clientinfo.silent_reason, len(open_offset),
                           len(open_silent), view, bool(cfg.get("metrics_group_names", False)),
                           listening=clientmon.listening_seconds())

    _part(rows, clients_part)
    _part(rows, lambda: notify_rows(notify.metrics_summary(), notify.NOTIFIER.running()))
    _part(rows, lambda: backup_rows(backup.nightly_metrics(bool(cfg.get("backup_nightly")))))
    _part(rows, lambda: event_rows(events.counts(), events.KINDS))
    _part(rows, lambda: holdover_rows(holdover.TEST.last_result()))
    if cfg.get("gps_enable"):
        _part(rows, lambda: autocal_rows(autocal.metrics_state(cfg), tuple(autocal.MODE_LABELS),
                                         autocal.PHASE_KEYS, cfg.get("gps_offset")))
    _part(rows, lambda: heartbeat_rows(heartbeat.status()))
    return rows
