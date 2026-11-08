"""Ereignisprotokoll: was wann passiert ist (Quellenwechsel, Fix verloren, Neustarts …).

emit() schreibt ein Ereignis in die SQLite-Datenbank (store.py). Es wirft nie –
ein volles Dateisystem darf keinen Messwert und keine Anfrage kosten. Klappt
das Schreiben nicht, landet das Ereignis in einem kleinen Puffer im Speicher
und wird beim nächsten erfolgreichen Schreiben nachgetragen.

Der Supervisor (docker/entrypoint.sh, Shell) hängt seine Ereignisse als
JSON-Zeilen an RUN_DIR/events.jsonl an; ingest_supervisor() liest nur die
neuen Zeilen und merkt sich die Leseposition (samt Inode, damit ein neu
angelegtes oder gekürztes File erkannt wird) in der Datenbank.

Aufbewahrung: 90 Tage und höchstens 50 000 Einträge – geprüft bei jedem
200. Schreiben, damit nicht jedes emit() eine DELETE-Abfrage kostet. Nach
Alter wird nur gelöscht, wenn die Systemzeit plausibel ist (clock_plausible):
chrony meldet nicht „Not synchronised“ und |Systemzeit-Offset| <= 1 s –
Inselbetrieb (local reference) zählt als plausibel. Den chrony-Wert liefert
der Status-Abruf des Servers über note_tracking(); prune() fragt chronyc nie
selbst (es läuft unter _LOCK). Ohne Wert gilt „unbekannt“: aufräumen, außer
es träfe alle Zeilen. Die Größenobergrenze gilt immer.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from typing import Any

import store

KINDS = ("service", "reload", "settings", "source", "gps", "pps", "calibration", "cert",
         "leap", "startup", "clients", "api", "notify", "dns", "update", "other")
LEVELS = ("info", "warn", "crit")

RETENTION_DAYS = 90
MAX_ROWS = 50_000
PRUNE_EVERY = 200
MAX_TITLE = 300
MAX_DATA = 8_000  # Bytes JSON je Ereignis

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        t REAL NOT NULL,
        kind TEXT NOT NULL,
        level TEXT NOT NULL,
        title TEXT NOT NULL,
        data TEXT,
        source TEXT NOT NULL DEFAULT 'web'
    );
    CREATE INDEX IF NOT EXISTS events_t ON events(t);
    CREATE INDEX IF NOT EXISTS events_kind_t ON events(kind, t);
    CREATE TABLE IF NOT EXISTS events_meta (key TEXT PRIMARY KEY, value TEXT);
    """,
]

_LOCK = threading.Lock()
CLOCK_MAX_OFFSET = 1.0     # s – |Systemzeit − chrony-Zeit|, darüber gilt die Uhr als unplausibel
CLOCK_STATE_TTL = 1800.0   # s (monoton) – älterer chrony-Wert gilt als unbekannt (Verlaufstakt bis 600 s)
CLOCK_RECENT = 300.0       # s – so frische Zeilen zählen bei „träfe alle Zeilen“ nicht mit
PRUNE_PAUSED_TITLE = "Aufräumen ausgesetzt: Systemzeit unplausibel"

_STATE: dict[str, Any] = {"ready_for": None, "since_prune": 0}
# plausible: True/False/None (unbekannt), at: monotone Zeit des Werts, noted: Hinweis geschrieben,
# held: wegen „träfe alle Zeilen“ ausgesetzt – bleibt so, bis chrony wieder einen Wert liefert
_CLOCK: dict[str, Any] = {"plausible": None, "at": None, "noted": False, "held": False}
_PENDING: deque = deque(maxlen=500)
_LISTENERS: list = []  # werden nach jedem erfolgreichen Schreiben aufgerufen (z. B. notify.wake)
_FILTERS: list = []    # (kind, level, title, data) -> (level, title, data), z. B. holdover.event_filter


def add_filter(callback) -> None:
    """callback(kind, level, title, data) -> (level, title, data) vor dem Schreiben – darf Stufe, Titel
    und Daten anpassen (z. B. Folgen eines laufenden Holdover-Tests als „info“). Fehler werden ignoriert."""
    if callback not in _FILTERS:
        _FILTERS.append(callback)


def remove_filter(callback) -> None:
    if callback in _FILTERS:
        _FILTERS.remove(callback)


def _filtered(kind: Any, level: Any, title: Any, data: Any) -> tuple:
    for callback in list(_FILTERS):
        try:
            level, title, data = callback(kind, level, title, data)
        except Exception:
            pass
    return level, title, data


def add_listener(callback) -> None:
    """callback() nach jedem gespeicherten Ereignis – muss sofort zurückkehren und darf nicht werfen."""
    if callback not in _LISTENERS:
        _LISTENERS.append(callback)


def _notify_listeners() -> None:
    for callback in list(_LISTENERS):
        try:
            callback()
        except Exception:
            pass


def _ensure() -> None:
    db = store.path()
    if _STATE["ready_for"] != db:
        store.migrate("events", _SCHEMA)
        _STATE["ready_for"] = db
        _STATE["since_prune"] = PRUNE_EVERY  # beim ersten Schreiben einmal aufräumen


def _clean(kind: Any, level: Any, title: Any, data: Any, source: Any, t: Any = None) -> tuple:
    kind = str(kind or "other")[:32]
    level = str(level or "info")
    if level not in LEVELS:
        level = "info"
    title = " ".join(str(title or "").split())[:MAX_TITLE]
    payload = None
    if data is not None:
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            payload = json.dumps({"value": str(data)}, ensure_ascii=False)
        if len(payload.encode("utf-8")) > MAX_DATA:
            payload = json.dumps({"truncated": True}, ensure_ascii=False)
    try:
        stamp = float(t) if t is not None else time.time()
    except (TypeError, ValueError):
        stamp = time.time()
    return (stamp, kind, level, title, payload, str(source or "web")[:32])


def _write(rows: list[tuple]) -> None:
    _ensure()
    with store.transaction() as conn:
        conn.executemany("INSERT INTO events(t, kind, level, title, data, source) "
                         "VALUES (?, ?, ?, ?, ?, ?)", rows)
    _STATE["since_prune"] += len(rows)
    if _STATE["since_prune"] >= PRUNE_EVERY:
        prune()


def emit(kind: str, level: str, title: str, data: dict | None = None,
         source: str = "web") -> None:
    """Ein Ereignis festhalten. Wirft nie."""
    try:
        level, title, data = _filtered(kind, level, title, data)
        row = _clean(kind, level, title, data, source)
    except Exception:
        return
    with _LOCK:
        rows = list(_PENDING) + [row]
        try:
            _write(rows)
            _PENDING.clear()
        except Exception:
            _PENDING.append(row)
            return
    _notify_listeners()


def clock_from_tracking(tracking: dict | None) -> bool | None:
    """Plausibilität aus chrony.tracking(): False bei „Leap status: Not synchronised“ oder
    |Systemzeit-Offset| > CLOCK_MAX_OFFSET, sonst True – auch im Inselbetrieb (local reference).
    None (unbekannt), wenn chronyc nichts geliefert hat."""
    if not tracking:
        return None
    leap = " ".join(str(tracking.get("leap_status") or "").lower().split())
    if not leap:
        return None
    if leap in ("not synchronised", "not synchronized"):
        return False
    offset = tracking.get("system_time_offset")
    if isinstance(offset, (int, float)) and not isinstance(offset, bool) and abs(offset) > CLOCK_MAX_OFFSET:
        return False
    return True


def note_tracking(tracking: dict | None) -> None:
    """Setter für den Zwischenspeicher – vom Status-Abruf des Servers aufrufen (außerhalb von _LOCK)."""
    state = clock_from_tracking(tracking)
    _CLOCK.update(plausible=state, at=time.monotonic())
    if state is not None:
        _CLOCK["held"] = False


def clock_state() -> bool | None:
    """Zuletzt gemeldete Plausibilität; None, wenn es keinen oder nur einen veralteten Wert gibt."""
    at = _CLOCK["at"]
    if at is None or not 0 <= time.monotonic() - at <= CLOCK_STATE_TTL:
        return None
    return _CLOCK["plausible"]


def note_prune_paused() -> None:
    """Einmal je Vorfall das Ereignis „Aufräumen ausgesetzt“ schreiben – direkt, ohne emit(),
    weil prune() auch unter _LOCK aus emit() heraus läuft. Aufrufen, wenn clock_plausible()
    False war und das Aufräumen nach Alter tatsächlich etwas gelöscht hätte."""
    if _CLOCK["noted"]:
        return
    _CLOCK["noted"] = True
    try:
        _ensure()
        row = _clean("other", "warn", PRUNE_PAUSED_TITLE,
                     {"hint": "Alte Einträge werden erst wieder nach Alter gelöscht, wenn chrony "
                              "nicht „Not synchronised“ meldet und die Systemzeit höchstens 1 s "
                              "abweicht. Die Größenobergrenze gilt weiter."}, "web")
        with store.transaction() as conn:
            conn.execute("INSERT INTO events(t, kind, level, title, data, source) "
                         "VALUES (?, ?, ?, ?, ?, ?)", row)
    except Exception:
        pass


def clock_plausible(due: int = 0, older: int = 0) -> bool:
    """Darf nach Alter (Wanduhr) aufgeräumt werden? Ruft nie chronyc auf.

    Mit Wert von chrony: dessen Urteil (clock_state). Ohne Wert („unbekannt“): ja – außer das
    Aufräumen träfe alle Zeilen (`due` >= `older` > 0; `older` = Zeilen älter als CLOCK_RECENT,
    damit das gerade Geschriebene nicht zählt). Dann aussetzen, bis chrony wieder einen Wert
    liefert. Ist die Uhr wieder plausibel, darf ein späterer Vorfall erneut gemeldet werden."""
    state = clock_state()
    if state is None:
        if due and older and due >= older:
            _CLOCK["held"] = True
        ok = not _CLOCK["held"]
    else:
        ok = bool(state)
    if ok:
        _CLOCK["noted"] = False
    return ok


def prune(now: float | None = None) -> int:
    """Alte Einträge löschen (90 Tage / 50 000 Zeilen). Gibt die Zahl gelöschter zurück.
    Nach Alter nur bei plausibler Systemzeit (clock_plausible), die Zeilengrenze immer."""
    try:
        _ensure()
        now = time.time() if now is None else now
        cutoff = now - RETENTION_DAYS * 86400
        removed = 0
        due, older = store.query("SELECT sum(t < ?), sum(t < ?) FROM events",
                                 (cutoff, now - CLOCK_RECENT))[0]
        age_ok = clock_plausible(due or 0, older or 0)
        if not age_ok and due:
            note_prune_paused()
        with store.transaction() as conn:
            if age_ok:
                removed += conn.execute("DELETE FROM events WHERE t < ?", (cutoff,)).rowcount
            removed += conn.execute(
                "DELETE FROM events WHERE id <= (SELECT max(id) FROM events) - ?",
                (MAX_ROWS,)).rowcount
        _STATE["since_prune"] = 0
        return removed
    except Exception:
        return 0


def query(since: float | None = None, until: float | None = None,
          kinds: list[str] | str | None = None, level: str | None = None,
          limit: int = 500) -> list[dict]:
    """Ereignisse, neueste zuerst. level = Mindeststufe (warn → warn + crit)."""
    where, params = [], []
    if since is not None:
        where.append("t >= ?")
        params.append(float(since))
    if until is not None:
        where.append("t <= ?")
        params.append(float(until))
    if kinds:
        kinds = [k for k in (kinds.split(",") if isinstance(kinds, str) else kinds) if k]
        if kinds:
            where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
            params += [str(k) for k in kinds]
    if level in LEVELS:
        allowed = LEVELS[LEVELS.index(level):]
        where.append("level IN (%s)" % ",".join("?" * len(allowed)))
        params += list(allowed)
    try:
        limit = max(1, min(int(limit), 5000))
    except (TypeError, ValueError):
        limit = 500
    sql = "SELECT id, t, kind, level, title, data, source FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t DESC, id DESC LIMIT ?"
    params.append(limit)
    try:
        _ensure()
        rows = store.query(sql, params)
    except Exception:
        return []
    out = []
    for ident, t, kind, lvl, title, data, source in rows:
        try:
            parsed = json.loads(data) if data else None
        except ValueError:
            parsed = None
        out.append({"id": ident, "t": t, "kind": kind, "level": lvl, "title": title,
                    "data": parsed, "source": source})
    return out


def after_id(last_id: int, limit: int = 200) -> list[dict]:
    """Ereignisse mit id > last_id, älteste zuerst (für Abonnenten wie notify.py)."""
    try:
        _ensure()
        rows = store.query("SELECT id, t, kind, level, title, data, source FROM events "
                           "WHERE id > ? ORDER BY id LIMIT ?", (int(last_id), max(1, min(int(limit), 1000))))
    except Exception:
        return []
    out = []
    for ident, t, kind, lvl, title, data, source in rows:
        try:
            parsed = json.loads(data) if data else None
        except ValueError:
            parsed = None
        out.append({"id": ident, "t": t, "kind": kind, "level": lvl, "title": title,
                    "data": parsed, "source": source})
    return out


def max_id() -> int:
    try:
        _ensure()
        return int(store.query("SELECT coalesce(max(id), 0) FROM events")[0][0])
    except Exception:
        return 0


def count() -> int:
    try:
        _ensure()
        return int(store.query("SELECT count(*) FROM events")[0][0])
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Supervisor-Ereignisse aus RUN_DIR/events.jsonl
# ---------------------------------------------------------------------------

_INGEST_LOCK = threading.Lock()
MAX_INGEST_BYTES = 1_000_000  # je Aufruf; der Rest folgt beim nächsten


def _meta_get(key: str) -> str | None:
    rows = store.query("SELECT value FROM events_meta WHERE key=?", (key,))
    return rows[0][0] if rows else None


FINGERPRINT_BYTES = 256


def _fingerprint(handle, length: int) -> str | None:
    """sha1 der ersten `length` Bytes (None, wenn die Datei kürzer ist)."""
    handle.seek(0)
    head = handle.read(length)
    if len(head) < length:
        return None
    return hashlib.sha1(head).hexdigest()


def _same_file(handle, st, saved: dict) -> bool:
    """Ist das dieselbe Datei wie beim letzten Lesen? Inode allein reicht nicht:
    tmpfs (RUN_DIR) nummeriert Inodes je Mount neu, ext4 vergibt freie wieder."""
    if saved.get("inode") != st.st_ino:
        return False
    offset = saved.get("offset")
    if not isinstance(offset, int) or offset < 0 or offset > st.st_size:
        return False
    fp, length = saved.get("fp"), saved.get("fp_len")
    if fp is None or not isinstance(length, int) or length < 0:
        return True  # Zustand einer Vorabversion ohne Fingerabdruck: wie bisher nur Inode
    return _fingerprint(handle, length) == fp


def _parse_lines(chunk: bytes) -> list[tuple]:
    rows = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        rows.append(_clean(item.get("kind"), item.get("level"), item.get("title"),
                           data if isinstance(data, dict) else None, "supervisor",
                           item.get("t")))
    return rows


def _rest_of_rotated(path: str, saved: dict) -> list[tuple]:
    """Nach einer Rotation (events.jsonl → .1): die seit dem letzten Lesen noch
    in die alte Datei geschriebenen Zeilen übernehmen."""
    if not saved:
        return []
    try:
        with open(path + ".1", "rb") as handle:
            st = os.fstat(handle.fileno())
            if not _same_file(handle, st, saved):
                return []
            handle.seek(int(saved["offset"]))
            # Die alte Datei ist abgeschlossen: auch eine letzte Zeile ohne \n zählt.
            return _parse_lines(handle.read(2 * MAX_INGEST_BYTES))
    except (OSError, ValueError, TypeError, KeyError):
        return []


def ingest_supervisor(path: str) -> int:
    """Liest neue Zeilen aus events.jsonl ein. Gibt die Zahl übernommener Ereignisse zurück.

    Die Leseposition gilt nur für dieselbe Datei: Inode, Größe und ein
    Fingerabdruck der ersten 256 Bytes (sha1) müssen passen, sonst wird von
    vorn gelesen. Wurde die Datei rotiert, wird zuerst der Rest von .1 gelesen.
    """
    with _INGEST_LOCK:
        try:
            _ensure()
        except Exception:
            return 0
        key = "ingest:" + os.path.abspath(path)
        try:
            saved = json.loads(_meta_get(key) or "{}")
        except Exception:
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        rows: list[tuple] = []
        try:
            with open(path, "rb") as handle:
                st = os.fstat(handle.fileno())
                if _same_file(handle, st, saved):
                    offset = int(saved["offset"])
                else:
                    rows.extend(_rest_of_rotated(path, saved))
                    offset = 0
                if offset == st.st_size and not rows:
                    return 0
                fp_len = min(FINGERPRINT_BYTES, st.st_size)
                fp = _fingerprint(handle, fp_len)
                handle.seek(offset)
                chunk = handle.read(MAX_INGEST_BYTES)
        except OSError:
            return 0
        end = chunk.rfind(b"\n")
        if end < 0:
            # Unvollständige Zeile: warten – außer sie ist absurd lang, dann überspringen.
            if len(chunk) >= MAX_INGEST_BYTES:
                offset += len(chunk)
            chunk = b""
        else:
            chunk = chunk[:end + 1]
        rows.extend(_parse_lines(chunk))
        new_offset = offset + len(chunk)
        state = {"inode": st.st_ino, "offset": new_offset, "size": st.st_size,
                 "fp": fp, "fp_len": fp_len}
        try:
            with store.transaction() as conn:
                if rows:
                    conn.executemany("INSERT INTO events(t, kind, level, title, data, source) "
                                     "VALUES (?, ?, ?, ?, ?, ?)", rows)
                conn.execute("INSERT INTO events_meta(key, value) VALUES(?, ?) ON CONFLICT(key) "
                             "DO UPDATE SET value=excluded.value", (key, json.dumps(state)))
        except Exception:
            return 0
        _STATE["since_prune"] += len(rows)
        if _STATE["since_prune"] >= PRUNE_EVERY:
            prune()
        if rows:
            _notify_listeners()
        return len(rows)
