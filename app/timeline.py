"""„Heute“-Zeitleiste (1.6, T7): Zustandsband, Ereignismarker und Tagesbericht.

„Was war um 03:12?“ ist die häufigste Frage nach einem Alarm. Verlauf (history.py) und
Ereignisprotokoll (events.py) liegen schon vor – dieses Modul legt sie übereinander:

* **Zustand je Messpunkt** (sample_state): „synchron“, „Warnung“, „Fehler“ oder „Holdover“ aus dem
  Offset der Systemuhr und der Frage, ob chrony gerade einer Quelle folgt (Zustand „*“).
  - Fehler: chronyd hat keinen Offset geliefert, oder |Offset| ≥ 50 ms (die rote Schwelle der
    Übersicht),
  - Holdover: keine Quelle ausgewählt – die Uhr läuft mit der zuletzt gelernten Frequenz frei,
  - Warnung: |Offset| ≥ 5 ms (die gelbe Schwelle der Übersicht),
  - sonst synchron.
* **Zustandsband** (build): 24 h in Fenstern zu 5 Minuten (BUCKET), **vorverdichtet** – die Zähler je
  Zustand stehen in der 5-Minuten-Vorverdichtung des Verlaufs (samples_5m, Feld „z“, siehe
  history._store_bucket). Gelesen werden höchstens 288 Zeilen plus der Puffer der letzten Minuten,
  nie der Rohverlauf; so bleibt die Antwort auch mit 30 Tagen Verlauf auf einem Pi weit unter 500 ms.
  Ein Fenster bekommt den schlimmsten Zustand, der mindestens ein Viertel seiner Messpunkte
  ausmacht (Fehler vor Holdover vor Warnung) – ein einzelner Ausreißer färbt nicht 5 Minuten rot.
* **Ereignismarker** (markers): Quellenwechsel, GPS-Ausfall, Neustart, Pi-Spannung und übrige
  Warnungen aus dem Ereignisprotokoll – nur Zeit, Art, Stufe und Titel, nie die Daten dahinter.
* **Tagesbericht** (daily_report): gestern (00–24 Uhr Ortszeit des Servers) aus dem Rohverlauf, **im
  Hintergrund** gerechnet (die Messschleife wärmt ihn vor, warm_report; höchstens eine Rechnung gleichzeitig)
  und für den Rest des Tages zwischengespeichert. /api/timeline wartet nie länger als REPORT_WAIT darauf –
  fehlt er noch, steht dort „pending“. Jeder Messpunkt zählt mit der Zeit bis zum nächsten (höchstens
  MAX_STEP), der letzte bis Mitternacht.
* **Zeitpunkt** (moment): „so sah es um 03:12 aus“ – Quelle, Offset, Fehlerschranke und die
  **Anzahl** der Satelliten aus dem nächstgelegenen Messpunkt. Keine Satellitenwinkel, keine
  Position, kein Rauschabstand: Die stehen gar nicht im Verlauf, und hier wird ausdrücklich nur
  eine feste Liste von Feldern weitergegeben (MOMENT_KEYS).

Alles bleibt lokal: keine neue Verbindung nach außen, nichts wird verschickt (die tägliche
Nachricht über Kanäle kommt frühestens mit 1.6.1, opt-in).
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Any, Iterable

import events
import store

BUCKET = 300                 # s – muss history.ROLLUP_SECONDS entsprechen (Test prüft das)
BUCKETS = 288                # 24 h
WARN_OFFSET = 0.005          # s – gelbe Schwelle der Übersicht (OFFSET_BANDS in overview.js)
CRIT_OFFSET = 0.05           # s – rote Schwelle
MAX_STEP = 600.0             # s – ein Messpunkt zählt höchstens so lange (größter Verlaufstakt)
MAX_MARKERS = 2000
MARKER_RANGE_MAX = 31 * 86400
REPORT_TTL = 600.0           # s (monoton) – so lange gilt ein Tagesbericht, der kurz nach Mitternacht entstand
REPORT_SETTLE = 900.0        # s nach Mitternacht – danach ist gestern abgeschlossen, der Bericht gilt den Tag über
REPORT_WAIT = 0.25           # s – so lange wartet /api/timeline höchstens auf einen fehlenden Tagesbericht

STATES = {"good": "g", "warn": "w", "crit": "c", "holdover": "h"}
CODES = {code: name for name, code in STATES.items()}
NO_DATA = "n"
MARKER_GROUPS = ("source", "gps", "restart", "pi", "warn")
# Felder eines Messpunkts, die /api/timeline/at herausgibt – sonst nichts.
MOMENT_KEYS = ("t", "state", "source", "offset", "bound", "stratum", "satellites")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def selected_source(sample: dict) -> str | None:
    """Name der Quelle, der chrony in diesem Messpunkt folgt („*“), sonst None."""
    for name, values in (sample.get("sources") or {}).items():
        if isinstance(values, dict) and values.get("s") == "*":
            return str(name)
    return None


def sample_state(sample: dict) -> str:
    """good | warn | crit | holdover für einen Messpunkt (siehe Modul-Doku)."""
    offset = sample.get("offset") if isinstance(sample, dict) else None
    if not _num(offset) or abs(offset) >= CRIT_OFFSET:
        return "crit"
    if selected_source(sample) is None:
        return "holdover"
    if abs(offset) >= WARN_OFFSET:
        return "warn"
    return "good"


def state_counts(samples: Iterable[dict]) -> dict[str, int]:
    """Zähler je Zustand ({"g": 28, "h": 2}) – so steht es in der Vorverdichtung (Feld „z“)."""
    counts: dict[str, int] = {}
    for sample in samples:
        if isinstance(sample, dict):
            code = STATES[sample_state(sample)]
            counts[code] = counts.get(code, 0) + 1
    return counts


def bucket_state(counts: dict | None) -> str:
    """Kennbuchstabe eines Fensters: schlimmster Zustand mit mindestens einem Viertel der Punkte."""
    if not isinstance(counts, dict):
        return NO_DATA
    clean = {k: int(v) for k, v in counts.items() if k in CODES and _num(v) and v > 0}
    total = sum(clean.values())
    if not total:
        return NO_DATA
    for code in ("c", "h", "w"):
        if clean.get(code, 0) * 4 >= total:
            return code
    return "g"


def runs(states: str, start: float, bucket: int = BUCKET) -> list[dict]:
    """Zusammenhängende Abschnitte gleichen Zustands: [{"state", "from", "to"}] (to exklusiv)."""
    out: list[dict] = []
    for i, code in enumerate(states):
        if out and out[-1]["code"] == code:
            out[-1]["to"] = start + (i + 1) * bucket
        else:
            out.append({"code": code, "from": start + i * bucket, "to": start + (i + 1) * bucket})
    return [{"state": CODES.get(r["code"], "none"), "from": r["from"], "to": r["to"]} for r in out]


# ---------------------------------------------------------------------------
# Ereignismarker
# ---------------------------------------------------------------------------

def marker_group(kind: str, level: str, title: str = "", data: dict | None = None) -> str | None:
    """Art des Markers oder None (kein Marker – z. B. gespeicherte Einstellungen, reine Infos)."""
    kind = str(kind or "")
    level = str(level or "info")
    data = data if isinstance(data, dict) else {}
    if kind == "source":
        return "source"
    if kind in ("gps", "pps") and (level != "info" or str(title).startswith("GPS-Fix verloren")):
        return "gps"
    if kind == "startup":
        return "restart"
    if kind == "service" and level != "info":
        return "restart"
    if kind == "reload" and data.get("result") == "done":
        return "restart"
    if kind == "pi" and level != "info":
        return "pi"
    if level in ("warn", "crit"):
        return "warn"
    return None


# Dieselbe Regel wie marker_group – als SQL, damit LIMIT nur echte Marker zählt (sonst drängen viele neuere
# Infos ohne Marker, etwa „GPS-Fehlerschranke angepasst“, die Marker aus dem Zeitraum). Kaputtes JSON im
# Datenfeld zählt wie ein leeres (CASE statt AND: SQLite wertet json_extract sonst auch bei json_valid = 0 aus).
_GPS_LOST = "GPS-Fix verloren"
_MARKER_SQL = (
    "(kind = 'source' OR kind = 'startup' OR level IN ('warn', 'crit')"
    " OR (kind IN ('gps', 'pps') AND (level <> 'info' OR substr(title, 1, length(:lost)) = :lost))"
    " OR (kind IN ('service', 'pi') AND level <> 'info')"
    " OR (kind = 'reload' AND CASE WHEN json_valid(data) THEN json_extract(data, '$.result') END = 'done'))")


def marker_page(since: float, until: float, limit: int = MAX_MARKERS, titles=None) -> tuple[list[dict], bool]:
    """Die neuesten `limit` Marker im Zeitraum, älteste zuerst: ({id, t, group, level, title}, abgeschnitten).
    abgeschnitten = es gibt im Zeitraum noch ältere Marker. Wirft nie.
    titles: optional Funktion(liste) → liste mit display_title (eigene Gerätenamen, server.py)."""
    limit = max(1, min(int(limit), 5000))
    try:
        events._ensure()
        rows = store.query(
            "SELECT id, t, kind, level, title, data FROM events WHERE t >= :since AND t <= :until "
            f"AND {_MARKER_SQL} ORDER BY t DESC, id DESC LIMIT :n",
            {"since": float(since), "until": float(until), "lost": _GPS_LOST, "n": limit + 1})
    except Exception:
        return [], False
    truncated = len(rows) > limit
    out = []
    for ident, t, kind, level, title, data in rows[:limit]:
        try:
            parsed = json.loads(data) if data else None
        except ValueError:
            parsed = None
        group = marker_group(kind, level, title, parsed)
        if group:
            out.append({"id": ident, "t": t, "kind": kind, "group": group, "level": level, "title": title,
                        "data": parsed})
    if titles:
        try:
            out = titles(out)
        except Exception:
            pass
    clean = []
    for item in reversed(out):
        clean.append({"id": item["id"], "t": item["t"], "group": item["group"], "level": item["level"],
                      "title": item.get("display_title") or item["title"]})
    return clean, truncated


def markers(since: float, until: float, limit: int = MAX_MARKERS, titles=None) -> list[dict]:
    """Wie marker_page, nur die Liste."""
    return marker_page(since, until, limit, titles)[0]


# ---------------------------------------------------------------------------
# Tagesbericht
# ---------------------------------------------------------------------------

def day_bounds(now: float | None = None, days_back: int = 1) -> tuple[float, float]:
    """(Beginn, Ende) des Tages vor `days_back` Tagen in Ortszeit des Servers (sommerzeitrichtig)."""
    now = time.time() if now is None else float(now)
    lt = time.localtime(now)
    end = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    start = end
    for _ in range(max(1, int(days_back))):
        end = start
        prev = time.localtime(start - 43200)
        start = time.mktime((prev.tm_year, prev.tm_mon, prev.tm_mday, 0, 0, 0, 0, 0, -1))
    return start, end


def daily_report(hist, start: float, end: float) -> dict[str, Any]:
    """Kennzahlen eines Tages [start, end) aus dem Rohverlauf (siehe Modul-Doku)."""
    day = time.strftime("%Y-%m-%d", time.localtime(start + 1))
    report: dict[str, Any] = {"day": day, "start": start, "end": end, "samples": 0, "covered_s": 0.0,
                              "synced_pct": None, "worst_offset": None, "devices": None,
                              "gps_hours": None, "pi_state": None}
    rows = hist.report_rows(start, end)
    if not rows:
        return report
    covered = synced = gps_s = 0.0
    has_gps = False
    worst = devices = pi = None
    for i, (t, offset, selected, clients, gps_obj, gps_mode, pi_state) in enumerate(rows):
        following = rows[i + 1][0] if i + 1 < len(rows) else end
        weight = min(max(float(following) - float(t), 0.0), MAX_STEP)
        covered += weight
        if _num(offset):
            if selected and abs(offset) < CRIT_OFFSET:
                synced += weight
            worst = abs(offset) if worst is None else max(worst, abs(offset))
        if _num(clients):
            devices = int(clients) if devices is None else max(devices, int(clients))
        if gps_obj:
            has_gps = True
            if _num(gps_mode) and gps_mode >= 2:
                gps_s += weight
        if _num(pi_state):
            pi = int(pi_state) if pi is None else max(pi, int(pi_state))
    report.update(samples=len(rows), covered_s=covered,
                  synced_pct=100.0 * synced / covered if covered > 0 else None,
                  worst_offset=worst, devices=devices,
                  gps_hours=gps_s / 3600.0 if has_gps else None, pi_state=pi)
    return report


_REPORT_LOCK = threading.Lock()
_REPORT: dict[str, Any] = {"key": None, "at": 0.0, "value": None, "final": False, "gen": 0}
_REPORT_JOBS: dict[Any, threading.Event] = {}


def _report_job(hist, now: float) -> threading.Event | None:
    """Tagesbericht für den Vortag von `now` im Hintergrund rechnen, falls nötig – höchstens eine Rechnung je
    Tag gleichzeitig (single flight). None: Der zwischengespeicherte Bericht gilt noch."""
    start, end = day_bounds(now)
    key = (id(hist), start)
    with _REPORT_LOCK:
        if _REPORT["key"] == key and (_REPORT["final"] or 0 <= time.monotonic() - _REPORT["at"] < REPORT_TTL):
            return None
        job = _REPORT_JOBS.get(key)
        if job is not None:
            return job
        job = _REPORT_JOBS[key] = threading.Event()
        gen = _REPORT["gen"]
    # Abgeschlossen: Der Tag ist so lange vorbei, dass auch der Puffer der letzten Minuten geschrieben ist.
    final = now >= end + REPORT_SETTLE

    def run() -> None:
        try:
            value = daily_report(hist, start, end)
        except Exception:
            value = None
        with _REPORT_LOCK:
            if _REPORT["gen"] == gen:  # sonst gerechnet aus dem Verlauf vor invalidate_report()
                _REPORT.update(key=key, at=time.monotonic(), value=value, final=final and value is not None)
            if _REPORT_JOBS.get(key) is job:
                del _REPORT_JOBS[key]
        job.set()

    try:
        threading.Thread(target=run, name="tagesbericht", daemon=True).start()
    except Exception:
        with _REPORT_LOCK:
            if _REPORT_JOBS.get(key) is job:
                del _REPORT_JOBS[key]
        job.set()
    return job


def invalidate_report() -> None:
    """Der Verlauf wurde ausgetauscht (Wiederherstellung): Bericht verwerfen, auch einen abgeschlossenen, und
    Rechnungen, die gerade laufen, nicht mehr eintragen. Wartet nicht, wirft nie."""
    with _REPORT_LOCK:
        _REPORT.update(key=None, at=0.0, value=None, final=False, gen=_REPORT["gen"] + 1)
        _REPORT_JOBS.clear()


def cached_report(hist, now: float | None = None, wait: float | None = None) -> dict[str, Any] | None:
    """Tagesbericht für gestern aus dem Zwischenspeicher. Fehlt er (erster Abruf, nach Mitternacht), wird er im
    Hintergrund gerechnet; gewartet wird höchstens `wait` Sekunden (Standard REPORT_WAIT), sonst kommt
    {"day", "start", "end", "pending": True}. Ein älterer Bericht desselben Tages gilt weiter, während er neu
    gerechnet wird. Wirft nie."""
    now = time.time() if now is None else float(now)
    start, end = day_bounds(now)
    key = (id(hist), start)
    job = _report_job(hist, now)
    with _REPORT_LOCK:
        have = _REPORT["key"] == key
    if job is not None and not have:
        job.wait(max(0.0, REPORT_WAIT if wait is None else float(wait)))
    with _REPORT_LOCK:
        if _REPORT["key"] == key:
            return _REPORT["value"]
    return {"day": time.strftime("%Y-%m-%d", time.localtime(start + 1)), "start": start, "end": end,
            "pending": True}


def warm_report(hist) -> None:
    """Aus der Messschleife (server.collector): Bericht für gestern vorab rechnen, ohne zu warten. Wirft nie."""
    try:
        _report_job(hist, time.time())
    except Exception:
        pass


def wait_report(timeout: float) -> bool:
    """Für Tests: warten, bis keine Rechnung mehr läuft."""
    deadline = time.monotonic() + timeout
    while True:
        with _REPORT_LOCK:
            jobs = list(_REPORT_JOBS.values())
        if not jobs:
            return True
        left = deadline - time.monotonic()
        if left <= 0 or not jobs[0].wait(left):
            return False


def reset_cache() -> None:
    wait_report(5.0)
    with _REPORT_LOCK:
        _REPORT.update(key=None, at=0.0, value=None, final=False)


# ---------------------------------------------------------------------------
# Antworten der API
# ---------------------------------------------------------------------------

def build(hist, now: float | None = None, titles=None) -> dict[str, Any]:
    """/api/timeline: Zustandsband der letzten 24 h, Marker darin und Tagesbericht für gestern."""
    now = time.time() if now is None else float(now)
    end_b = int(now) // BUCKET
    start_b = end_b - BUCKETS + 1
    start = start_b * BUCKET
    try:
        counts = hist.band_counts(start, (end_b + 1) * BUCKET - 1)
    except Exception:
        counts = {}
    states = "".join(bucket_state(counts.get(b)) for b in range(start_b, end_b + 1))
    marks, truncated = marker_page(start, now, titles=titles)
    for mark in marks:
        mark["b"] = min(BUCKETS - 1, max(0, int(mark["t"]) // BUCKET - start_b))
    return {"now": now, "start": start, "end": (end_b + 1) * BUCKET, "bucket": BUCKET, "states": states,
            "runs": runs(states, start), "markers": marks, "markers_truncated": truncated, "report": cached_report(hist, now),
            "thresholds": {"warn": WARN_OFFSET, "crit": CRIT_OFFSET}}


def chart_markers(range_s: float | None, now: float | None = None, titles=None) -> dict[str, Any]:
    """/api/timeline/markers: Marker der letzten `range_s` Sekunden für die Diagramme."""
    now = time.time() if now is None else float(now)
    try:
        span = float(range_s) if range_s is not None else 86400.0
    except (TypeError, ValueError):
        span = 86400.0
    if not math.isfinite(span) or span <= 0:
        span = 86400.0
    span = min(span, MARKER_RANGE_MAX)
    marks, truncated = marker_page(now - span, now, titles=titles)
    return {"since": now - span, "until": now, "groups": list(MARKER_GROUPS), "markers": marks,
            "truncated": truncated}


def moment(hist, at: float, titles=None) -> dict[str, Any]:
    """/api/timeline/at: nächstgelegener Messpunkt (höchstens 2 Fenster entfernt) und Marker daneben."""
    sample = None
    try:
        sample = hist.nearest(float(at), 2 * BUCKET)
    except Exception:
        sample = None
    near = markers(at - BUCKET, at + BUCKET, limit=20, titles=titles)
    return {"t": at, "sample": summarize(sample) if sample else None, "events": near}


def summarize(sample: dict) -> dict[str, Any]:
    """Nur die Felder aus MOMENT_KEYS – Satelliten als Anzahl, nie Winkel oder Position."""
    delay, dispersion = sample.get("root_delay"), sample.get("root_dispersion")
    gps = sample.get("gps") if isinstance(sample.get("gps"), dict) else None
    satellites = None
    if gps is not None:
        used, seen = gps.get("used"), gps.get("seen")
        satellites = {"used": int(round(used)) if _num(used) else None,
                      "seen": int(round(seen)) if _num(seen) else None}
    out = {
        "t": sample.get("t"),
        "state": sample_state(sample),
        "source": selected_source(sample),
        "offset": sample.get("offset") if _num(sample.get("offset")) else None,
        "bound": delay / 2 + dispersion if _num(delay) and _num(dispersion) else None,
        "stratum": sample.get("stratum") if _num(sample.get("stratum")) else None,
        "satellites": satellites,
    }
    assert tuple(out) == MOMENT_KEYS
    return out
