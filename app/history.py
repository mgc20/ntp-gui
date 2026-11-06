"""Verlauf der Messwerte für die Diagramme – in SQLite, mit Rückfall auf .json.gz.

Ein Messpunkt enthält die Systemuhr (tracking), den Offset jeder Quelle, den
Zähler der beantworteten Anfragen sowie GPS- und PTP-Werte. Ab 1.4 dazu „temp“:
die Temperatur des gewählten Sensors in °C (thermal.py), falls es einen gibt. Weil
ein Messpunkt als JSON gespeichert wird, braucht das neue Feld keine Migration –
ältere Punkte haben es einfach nicht, die Verdichtung (Mittelwert je Fenster)
behandelt es wie die übrigen Zahlen.

Speicher (ab 1.3): Tabelle samples(t INTEGER PRIMARY KEY, json TEXT) in
DATA_DIR/ntp-gui.db (store.py). Neue Messpunkte sammeln sich im Speicher und
werden alle FLUSH_SECONDS (5 min), beim Beenden und bei save(force=True) in
einer Transaktion geschrieben – so bleibt die Schreiblast auf der SD-Karte
eines Raspberry Pi klein; ein Absturz kostet höchstens die letzten Minuten.
Abfragen sehen trotzdem sofort alle Punkte (Datenbank + Puffer).

Aufbewahrung:
  * HISTORY_DAYS (Standard 30): Messpunkte, die mehr als so viele Tage älter
    sind als der neueste, werden gelöscht. Bezug ist der neueste Messpunkt,
    nicht die Uhr – ein Pi ohne Echtzeituhr, der mit falschem Datum startet,
    löscht so nicht versehentlich den ganzen Verlauf. Umgekehrt zählt als
    „neuester“ höchstens jetzt + FUTURE_SLACK: Ein einzelner Messpunkt mit
    Zeitstempel in der Zukunft (falsches Datum von Hand, Quelle stellt die Uhr
    vor, importierte Datei) löscht sonst bei jedem Schreiben den ganzen
    Verlauf. Solche Punkte werden gar nicht erst gespeichert (auch nicht bei der
    Übernahme der .json.gz); bereits vorhandene bleiben liegen, zählen aber
    nicht als „neuester“.
  * HISTORY_SIZE (wie in 1.2: Anzahl Messpunkte) bleibt eine OBERGRENZE, wenn
    die Variable gesetzt ist. Ist sie nicht gesetzt, übergibt server.py den
    alten Standard 8640 – der wird hier als „keine Obergrenze, nur Tage“
    gedeutet, sonst bliebe es bei 24 Stunden. Wer HISTORY_SIZE ausdrücklich
    setzt, behält genau das Verhalten von 1.2.

Diagramme über 30 Tage (≈ 260 000 Punkte bei 10 s) werden in SQL nach
Zeitfenstern verdichtet (json_extract/json_each + GROUP BY), statt alle
Punkte in Python zu laden.

Erster Start mit 1.3: eine vorhandene history.json.gz wird vollständig
übernommen und danach in history.json.gz.migrated umbenannt.

Rückfall: Lässt sich SQLite nicht öffnen (Datei beschädigt, Volume nur
lesbar, sqlite3 fehlt), arbeitet der Verlauf wie in 1.2 im Speicher
(höchstens HISTORY_SIZE bzw. 8640 Punkte) und sichert als .json.gz. Das
Dashboard läuft also weiter, nur mit kürzerem Verlauf; stats() meldet den
Modus, damit die Diagnose es zeigen kann.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import threading
import time
from collections import deque
from typing import Any

try:
    import sqlite3
except ImportError:  # pragma: no cover – Python ohne sqlite3
    sqlite3 = None  # type: ignore[assignment]

import gpsquality
import store

_NUMERIC_TOP = ("offset", "rms", "freq", "skew", "root_delay", "root_dispersion",
                "stratum", "served", "clients", "temp")
_GROUPS = ("gps", "ptp")

LEGACY_SIZE = 8640          # Standard von HISTORY_SIZE in 1.2 (24 h bei 10 s)
DEFAULT_DAYS = 30.0
FLUSH_SECONDS = 300.0
MAX_PENDING = 5000          # Puffer, falls die Datenbank zeitweise nicht schreibbar ist
FUTURE_SLACK = 86400.0      # Messpunkte mehr als 1 Tag in der Zukunft werden verworfen

ROLLUP_SECONDS = 300        # Vorverdichtung: ein Punkt je 5 Minuten
RAW_LIMIT = 30_000          # mehr Rohpunkte → aus der Vorverdichtung lesen

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS samples (t INTEGER PRIMARY KEY, json TEXT NOT NULL)",
    # b = t // ROLLUP_SECONDS; t = Zeit des letzten Punkts im Fenster; json = gemittelter Punkt.
    "CREATE TABLE IF NOT EXISTS samples_5m (b INTEGER PRIMARY KEY, t INTEGER NOT NULL, "
    "json TEXT NOT NULL); CREATE INDEX IF NOT EXISTS samples_5m_t ON samples_5m(t)",
]


def retention_days(env: dict | None = None) -> float:
    env = os.environ if env is None else env
    try:
        days = float(str(env.get("HISTORY_DAYS", DEFAULT_DAYS)).strip())
    except ValueError:
        return DEFAULT_DAYS
    if not math.isfinite(days):
        return DEFAULT_DAYS
    return min(3650.0, max(1.0, days))


def effective_size(size: int | None, env: dict | None = None) -> int | None:
    """Obergrenze an Messpunkten oder None (nur Tage zählen). Siehe Modul-Doku."""
    env = os.environ if env is None else env
    if size is None:
        return None
    if int(size) == LEGACY_SIZE and "HISTORY_SIZE" not in env:
        return None
    return max(2, int(size))


def _valid(sample: Any) -> bool:
    return isinstance(sample, dict) and isinstance(sample.get("t"), (int, float)) \
        and not isinstance(sample.get("t"), bool) and math.isfinite(sample["t"])


def _latest_allowed(now: float | None = None) -> float:
    """Spätester Zeitstempel, der noch als Gegenwart gilt."""
    return (time.time() if now is None else now) + FUTURE_SLACK


def _storable(sample: Any, now: float | None = None) -> bool:
    return _valid(sample) and sample["t"] <= _latest_allowed(now)


SNAPSHOT_CHUNK = 6 * 3600  # snapshot(): so viele Sekunden Verlauf je Griff nach dem Lock


class History:
    def __init__(self, size: int | None, path: str | None = None, days: float | None = None,
                 db_path: str | None = None) -> None:
        self.size = effective_size(size)
        self.days = float(days) if days else retention_days()
        self.path = path
        self._lock = threading.RLock()
        self._last_save = time.time()
        self._pending: list[dict] = []
        self.error: str | None = None
        self.db_path: str | None = None
        self.backend = "memory"
        if path and sqlite3 is not None:
            candidate = db_path or os.path.join(os.path.dirname(os.path.abspath(path)), store.DB_NAME)
            try:
                store.migrate("history", _SCHEMA, candidate)
                self.db_path, self.backend = candidate, "sqlite"
            except Exception as exc:  # Rückfall wie 1.2
                self.error = f"SQLite nicht nutzbar ({exc}) – Verlauf nur im Speicher"
                print(f"[web] {self.error}", flush=True)
        self._samples: deque[dict] = deque(maxlen=self.size or LEGACY_SIZE)

    # --- Hilfen ---------------------------------------------------------------
    @property
    def _sql(self) -> bool:
        return self.backend == "sqlite"

    def _db(self, sql: str, params: Any = ()) -> list[tuple]:
        return store.query(sql, params, self.db_path)

    def _pending_json(self) -> str:
        return _dumps([s for s in self._pending if _valid(s)])

    # --- schreiben -----------------------------------------------------------
    def add(self, sample: dict) -> None:
        sample.setdefault("t", int(time.time()))
        if not _storable(sample):
            return  # Zeitstempel weit in der Zukunft – würde den Verlauf verdrängen
        with self._lock:
            if self._sql:
                self._pending.append(sample)
                if len(self._pending) >= MAX_PENDING:
                    if not self._flush():
                        del self._pending[:len(self._pending) - MAX_PENDING]
            else:
                self._samples.append(sample)

    def resize(self, size: int | None) -> None:
        with self._lock:
            self.size = None if size is None else max(2, int(size))
            if self._samples.maxlen != (self.size or LEGACY_SIZE):
                self._samples = deque(self._samples, maxlen=self.size or LEGACY_SIZE)

    def _flush(self) -> bool:
        """Puffer in die Datenbank schreiben und aufräumen. Aufruf unter self._lock."""
        if not self._sql:
            return False
        latest = _latest_allowed()
        rows = [(int(s["t"]), _dumps(s))
                for s in self._pending if _valid(s) and s["t"] <= latest]
        try:
            with store.transaction(self.db_path) as conn:
                if rows:
                    conn.executemany("INSERT OR REPLACE INTO samples(t, json) VALUES(?, ?)", rows)
                newest = conn.execute("SELECT max(t) FROM samples").fetchone()[0]
                if newest is not None:
                    newest = min(newest, latest)
                    conn.execute("DELETE FROM samples WHERE t < ?", (newest - self.days * 86400,))
                if self.size:
                    conn.execute("DELETE FROM samples WHERE t < (SELECT t FROM samples "
                                 "ORDER BY t DESC LIMIT 1 OFFSET ?)", (self.size - 1,))
                _update_rollup(conn, {t // ROLLUP_SECONDS for t, _ in rows})
                conn.execute("DELETE FROM samples_5m WHERE b < coalesce("
                             "(SELECT min(t) FROM samples) / ?, b)", (ROLLUP_SECONDS,))
        except Exception as exc:
            self.error = f"Verlauf nicht gespeichert: {exc}"
            return False
        self._pending = []
        self.error = None
        return True

    # --- lesen ---------------------------------------------------------------
    def _bounds(self) -> tuple[float | None, float | None]:
        """(älteste erlaubte Zeit, neueste Zeit) nach Tagen und Obergrenze."""
        rows = self._db("SELECT max(t) FROM samples")
        newest = rows[0][0]
        pend = [s["t"] for s in self._pending if _valid(s)]
        if pend:
            newest = max(pend) if newest is None else max(newest, max(pend))
        if newest is None:
            return None, None
        newest = min(newest, _latest_allowed())
        lower = newest - self.days * 86400
        if self.size:
            extra = len(set(pend))
            if extra >= self.size:
                lower = max(lower, sorted(set(pend))[-self.size])
            else:
                row = self._db("SELECT t FROM samples ORDER BY t DESC LIMIT 1 OFFSET ?",
                               (self.size - extra - 1,))
                if row:
                    lower = max(lower, row[0][0])
        # Auf den tatsächlich ältesten Punkt im Fenster hochziehen: davon hängt die
        # Breite der Verdichtungsfenster ab.
        first = self._db("SELECT min(t) FROM samples WHERE t >= ?", (lower,))[0][0]
        candidates = [t for t in pend if t >= lower] + ([first] if first is not None else [])
        if candidates:
            lower = max(lower, min(candidates))
        return lower, newest

    def _raw_rows(self, lower: float, upper: float) -> list[str]:
        """JSON-Texte der Punkte im Fenster (unter self._lock aufrufen)."""
        rows = self._db(_cte("samples") + "SELECT j FROM d ORDER BY t",
                        {"lo": lower, "hi": upper, "p": self._pending_json()})
        return [text for (text,) in rows]

    @staticmethod
    def _decode(texts: list[str]) -> list[dict]:
        """JSON dekodieren – bewusst AUSSERHALB von self._lock (bei 60 000 Punkten
        dauert das auf einem Pi Sekunden, add() der Messschleife soll nicht warten)."""
        out = []
        for text in texts:
            try:
                out.append(json.loads(text))
            except (TypeError, ValueError):
                continue
        return out

    def _rows(self, lower: float, upper: float) -> list[dict]:
        return self._decode(self._raw_rows(lower, upper))

    def _snapshot_texts(self, since: float | None) -> list[str]:
        """Rohtexte ab since – in Abschnitten von SNAPSHOT_CHUNK Sekunden, jeder unter self._lock
        für sich. So wartet add() der Messschleife höchstens einen Abschnitt lang, auch wenn
        jemand Tage des Verlaufs liest (1.5.4: vorher die ganze Abfrage lang)."""
        with self._lock:
            lower, newest = self._bounds()
        if newest is None:
            return []
        if since is not None:
            lower = max(lower, since)
        texts: list[str] = []
        lo = lower
        while lo <= newest:
            # t ist ganzzahlig: [lo, hi] und danach hi + 1 – keine Lücke, nichts doppelt.
            hi = min(newest, math.floor(lo) + SNAPSHOT_CHUNK - 1)
            with self._lock:
                texts += self._raw_rows(lo, hi)
            lo = math.floor(hi) + 1
            time.sleep(0)  # wartende Threads (add()) kommen zwischen zwei Abschnitten dran
        return texts

    def snapshot(self, since: float | None = None) -> list[dict]:
        texts = None
        if self._sql:
            try:
                texts = self._snapshot_texts(since)
            except Exception as exc:
                self.error = f"Verlauf nicht lesbar: {exc}"
                with self._lock:
                    data = list(self._pending)
        else:
            with self._lock:
                data = list(self._samples)
        if texts is not None:
            return self._decode(texts)
        if data:
            latest = _latest_allowed()
            data = [s for s in data if s.get("t", 0) <= latest]
        if data:
            cutoff = data[-1].get("t", 0) - self.days * 86400
            data = [s for s in data if s.get("t", 0) >= cutoff]
        if since is not None:
            data = [s for s in data if s.get("t", 0) >= since]
        return data

    def series(self, key: str, since: float | None = None) -> list[tuple[int, float]]:
        """(t, Wert) einer Zahl auf oberster Ebene (z. B. „freq“), zeitlich sortiert – ohne die
        Messpunkte als JSON zu dekodieren (1.5.4, Allan-Abweichung: 30 Tage ≈ 260 000 Punkte).
        In SQL wie snapshot() abschnittsweise, damit add() nicht lange wartet."""
        assert key in _NUMERIC_TOP
        out: list[tuple[int, float]] = []
        if self._sql:
            try:
                with self._lock:
                    lower, newest = self._bounds()
                if newest is None:
                    return []
                if since is not None:
                    lower = max(lower, since)
                expr = _num_expr("j", "$." + key)
                lo = lower
                while lo <= newest:
                    hi = min(newest, math.floor(lo) + SNAPSHOT_CHUNK - 1)
                    with self._lock:
                        rows = self._db(_cte("samples") + f"SELECT t, {expr} FROM d ORDER BY t",
                                        {"lo": lo, "hi": hi, "p": self._pending_json()})
                    out += [(int(t), float(v)) for t, v in rows if v is not None]
                    lo = math.floor(hi) + 1
                    time.sleep(0)
                return out
            except Exception as exc:
                # Nicht still [] liefern – sonst zeigt die Seite „noch kein Verlauf“ statt des Fehlers.
                self.error = f"Verlauf nicht lesbar: {exc}"
                raise
        for sample in self.snapshot(since):
            value = sample.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                out.append((int(sample.get("t", 0)), float(value)))
        return out

    def query(self, seconds: float | None = None, points: int = 600) -> list[dict]:
        """Ausschnitt der letzten `seconds` Sekunden, auf höchstens `points` verdichtet."""
        if self._sql:
            with self._lock:
                try:
                    texts, result = self._query_sql(seconds, points)
                except Exception as exc:
                    self.error = f"Verlauf nicht lesbar: {exc}"
                    texts, result = None, None
            if texts is not None:
                return self._decode(texts)
            if result is not None:
                return result
        data = self.snapshot()
        if seconds and data:
            cutoff = data[-1]["t"] - seconds
            data = [s for s in data if s["t"] >= cutoff]
        return downsample(data, points)

    def _query_sql(self, seconds: float | None, points: int) -> tuple[list[str] | None, list[dict] | None]:
        """(Rohtexte zum Dekodieren außerhalb der Sperre, None) oder (None, fertige Punkte)."""
        lower, newest = self._bounds()
        if newest is None:
            return None, []
        if seconds:
            lower = max(lower, newest - seconds)
        params = {"lo": lower, "hi": newest, "p": self._pending_json()}
        width = max(1, math.ceil((newest - lower + 1) / max(1, points)))
        table = "samples_5m"
        if width < ROLLUP_SECONDS:
            count = self._db(_cte("samples") + "SELECT count(*) FROM d", params)[0][0]
            if points <= 0 or count <= points:
                return self._raw_rows(lower, newest), None
            if count <= RAW_LIMIT:
                table = "samples"
        if table == "samples_5m":
            # Grob genug für die Vorverdichtung: ~8640 statt ~260 000 Zeilen für 30 Tage.
            # Fenster beginnen an der 5-Minuten-Grenze, damit jede 5-Minuten-Zeile
            # vollständig in genau ein Fenster fällt.
            width = max(ROLLUP_SECONDS, math.ceil(width / ROLLUP_SECONDS) * ROLLUP_SECONDS)
            params["lo"] = (int(lower) // ROLLUP_SECONDS) * ROLLUP_SECONDS
        params["w"] = width
        return None, _aggregate(self._db, table, params)

    def stats(self) -> dict:
        """Zustand für Diagnose/Statusseite (ohne Messwerte)."""
        info = {"backend": self.backend, "days": self.days, "size": self.size,
                "pending": len(self._pending), "error": self.error, "rows": None,
                "oldest": None, "newest": None}
        with self._lock:
            try:
                if self._sql:
                    count, oldest, newest = self._db("SELECT count(*), min(t), max(t) FROM samples")[0]
                else:
                    count = len(self._samples)
                    oldest = self._samples[0]["t"] if self._samples else None
                    newest = self._samples[-1]["t"] if self._samples else None
                info.update(rows=count, oldest=oldest, newest=newest)
            except Exception as exc:
                info["error"] = str(exc)
        return info

    # --- sichern -------------------------------------------------------------
    def load(self) -> int:
        """Startet den Verlauf: übernimmt ggf. history.json.gz. Gibt die Zahl der Punkte zurück."""
        if self._sql:
            with self._lock:
                self._migrate_gzip()
                try:
                    _backfill_rollup(self.db_path)
                    self._flush()  # wendet Aufbewahrung/Obergrenze an
                    return int(self._db("SELECT count(*) FROM samples")[0][0])
                except Exception:
                    return 0
        data = _read_gzip(self.path)
        with self._lock:
            for sample in [s for s in data if _storable(s)][-self._samples.maxlen:]:
                if _valid(sample):
                    self._samples.append(sample)
            return len(self._samples)

    def _migrate_gzip(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        latest = _latest_allowed()
        data = [s for s in _read_gzip(self.path) if _valid(s)]
        skipped = sum(1 for s in data if s["t"] > latest)
        rows = [(int(s["t"]), _dumps(s)) for s in data if s["t"] <= latest]
        if skipped:
            print(f"[web] Verlauf: {skipped} Messpunkt(e) mit Zeitstempel in der Zukunft "
                  "nicht übernommen", flush=True)
        try:
            with store.transaction(self.db_path) as conn:
                conn.executemany("INSERT OR IGNORE INTO samples(t, json) VALUES(?, ?)", rows)
            os.replace(self.path, self.path + ".migrated")
            print(f"[web] Verlauf aus {os.path.basename(self.path)} übernommen: {len(rows)} "
                  f"Messpunkte (alte Datei: {os.path.basename(self.path)}.migrated)", flush=True)
        except Exception as exc:
            self.error = f"Alter Verlauf nicht übernommen: {exc}"

    def save(self, force: bool = False, every: float = 3600.0) -> bool:
        """SQLite: Puffer schreiben (alle FLUSH_SECONDS oder force). Sonst .json.gz wie in 1.2."""
        now = time.time()
        if self._sql:
            with self._lock:
                if not force and now - self._last_save < min(every, FLUSH_SECONDS):
                    return False
                ok = self._flush()
                if ok:
                    self._last_save = now
                return ok
        if not self.path:
            return False
        if not force and now - self._last_save < every:
            return False
        data = self.snapshot()
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            tmp = self.path + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
                json.dump(data, handle, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            return False
        self._last_save = now
        return True


def _finite(value: Any) -> Any:
    """NaN/Inf → None (SQLite-JSON kennt sie nicht), Unbekanntes → Text."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return json.dumps(_finite(value), separators=(",", ":"), allow_nan=False)


def _read_gzip(path: str | None) -> list:
    if not path or not os.path.exists(path):
        return []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, EOFError):
        return []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Verdichten in SQL
# ---------------------------------------------------------------------------

# d(t, j): Messpunkte im Fenster [lo, hi] aus Datenbank UND Puffer (:p, JSON-Liste);
# ein Punkt im Puffer ersetzt einen gleichen Zeitstempel aus der Datenbank.
# Bei samples_5m stehen Fenster-Mittelwerte statt Rohpunkten in d (der Puffer
# bleibt roh – er umfasst höchstens die letzten FLUSH_SECONDS).
def _cte(table: str) -> str:
    assert table in {"samples", "samples_5m"}
    return f"""
WITH pend(t, j) AS (
    SELECT CAST(json_extract(value, '$.t') AS INTEGER), value FROM json_each(:p)
), d(t, j) AS (
    SELECT t, json FROM {table}
     WHERE t >= :lo AND t <= :hi AND t NOT IN (SELECT t FROM pend)
    UNION ALL
    SELECT t, j FROM pend WHERE t >= :lo AND t <= :hi
)
"""


def _update_rollup(conn, buckets: set[int]) -> None:
    """Berechnet die 5-Minuten-Punkte der genannten Fenster aus den Rohdaten neu."""
    for b in sorted(buckets):
        rows = conn.execute("SELECT json FROM samples WHERE t >= ? AND t < ? ORDER BY t",
                            (b * ROLLUP_SECONDS, (b + 1) * ROLLUP_SECONDS)).fetchall()
        _store_bucket(conn, b, rows)


def _store_bucket(conn, b: int, rows: list[tuple]) -> None:
    chunk = []
    for (text,) in rows:
        try:
            chunk.append(json.loads(text))
        except ValueError:
            continue
    if not chunk:
        conn.execute("DELETE FROM samples_5m WHERE b = ?", (b,))
        return
    merged = downsample(chunk, 1)[0]
    conn.execute("INSERT OR REPLACE INTO samples_5m(b, t, json) VALUES(?, ?, ?)",
                 (b, int(merged["t"]), _dumps(merged)))


def _backfill_rollup(db_path: str | None) -> int:
    """Ergänzt fehlende 5-Minuten-Punkte (nach Übernahme der .json.gz). Gibt die Zahl zurück."""
    missing = [row[0] for row in store.query(
        "SELECT DISTINCT t / ? FROM samples EXCEPT SELECT b FROM samples_5m",
        (ROLLUP_SECONDS,), db_path)]
    for start in range(0, len(missing), 500):
        with store.transaction(db_path) as conn:
            _update_rollup(conn, set(missing[start:start + 500]))
    return len(missing)


def _num_expr(doc: str, path: str) -> str:
    return (f"CASE WHEN json_type({doc}, '{path}') IN ('integer', 'real') "
            f"THEN json_extract({doc}, '{path}') END")


def _aggregate(db, table: str, params: dict) -> list[dict]:
    cte = _cte(table)
    bucket = "CAST((d.t - :lo) / :w AS INTEGER)"
    avgs = ", ".join(f"avg({_num_expr('d.j', '$.' + key)})" for key in _NUMERIC_TOP)
    # Genau ein max(): die übrigen „nackten“ Spalten stammen aus dem neuesten Punkt
    # des Fensters (SQLite-Garantie) – Zählerstand „served“ = letzter Wert.
    top = db(cte + f"SELECT {bucket} AS b, max(d.t), json_extract(d.j, '$.served'), {avgs} "
                    f"FROM d GROUP BY b ORDER BY b", params)
    out: dict[int, dict] = {}
    for row in top:
        merged: dict[str, Any] = {"t": row[1]}
        for key, value in zip(_NUMERIC_TOP, row[3:]):
            if value is not None:
                merged[key] = value
        if row[2] is not None:
            merged["served"] = row[2]
        out[row[0]] = merged
    sources = db(cte + f"SELECT {bucket} AS b, e.key, max(d.t), "
                        "json_extract(e.value, '$.s'), json_extract(e.value, '$.k'), "
                        f"avg({_num_expr('e.value', '$.o')}) "
                        "FROM d, json_each(d.j, '$.sources') e "
                        "WHERE e.type = 'object' GROUP BY b, e.key", params)
    for b, name, _t, state, mode, offset in sources:
        if b in out:
            out[b].setdefault("sources", {})[name] = {"o": offset, "s": state, "k": mode}
    for group in _GROUPS:
        rows = db(cte + f"SELECT {bucket} AS b, e.key, "
                         "avg(CASE WHEN e.type IN ('integer', 'real') THEN e.value END) "
                         f"FROM d, json_each(d.j, '$.{group}') e GROUP BY b, e.key", params)
        for b, key, value in rows:
            if b in out:
                out[b].setdefault(group, {})[key] = value
    return [out[b] for b in sorted(out)]


# ---------------------------------------------------------------------------
# Verdichten in Python (Rückfall ohne SQLite, kleine Mengen)
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float | None:
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
              and math.isfinite(v)]
    return sum(values) / len(values) if values else None


def downsample(data: list[dict], points: int) -> list[dict]:
    """Mittelt numerische Werte in gleich großen Zeitfenstern; Zustände: letzter Wert."""
    if points <= 0 or len(data) <= points:
        return data
    bucket = math.ceil(len(data) / points)
    out = []
    for start in range(0, len(data), bucket):
        chunk = data[start:start + bucket]
        merged: dict[str, Any] = {"t": chunk[-1]["t"]}
        for key in _NUMERIC_TOP:
            value = _mean([s.get(key) for s in chunk])
            if value is not None:
                merged[key] = value
        # Zählerstände: letzter Wert, nicht Mittel (sonst stimmt die Rate nicht).
        if "served" in chunk[-1]:
            merged["served"] = chunk[-1]["served"]
        sources: dict[str, dict] = {}
        for sample in chunk:
            for name, values in (sample.get("sources") or {}).items():
                sources.setdefault(name, {"o": [], "s": None, "k": None})
                sources[name]["o"].append(values.get("o"))
                sources[name]["s"] = values.get("s", sources[name]["s"])
                sources[name]["k"] = values.get("k", sources[name]["k"])
        if sources:
            merged["sources"] = {name: {"o": _mean(v["o"]), "s": v["s"], "k": v["k"]}
                                 for name, v in sources.items()}
        for group in ("gps", "ptp"):
            keys = {k for s in chunk for k in (s.get(group) or {})}
            if keys:
                merged[group] = {k: _mean([(s.get(group) or {}).get(k) for s in chunk])
                                 for k in keys}
        out.append(merged)
    return out


# ---------------------------------------------------------------------------
# GPS-Kalibrierung
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


GPS_UNMEASURED_STATES = frozenset({"?", "x", "~"})


def gps_measured(gps: Any) -> bool:
    """Ist dieser GPS-Wert eines Messpunkts wirklich gemessen?

    chrony meldet für eine Refclock ohne Daten weiter einen Offset (0 ns) –
    mit Zustand „?“ (nicht erreichbar) und Reach 0. „x“ (Falschgeber) und „~“
    (zu unruhig) taugen ebenfalls nicht als Messwert. Ältere Messpunkte haben
    keinen Reach-Wert („r“), dann entscheidet nur der Zustand.
    """
    if not isinstance(gps, dict):
        return False
    offset = gps.get("o")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
        return False
    if gps.get("s") in GPS_UNMEASURED_STATES:
        return False
    reach = gps.get("r", gps.get("reach"))
    if isinstance(reach, (int, float)) and not isinstance(reach, bool) and reach == 0:
        return False
    return True


def _gps_has_data(gps: Any) -> bool:
    """Weicher als gps_measured(): nur „keine Daten“ („?“, Reach 0) fällt heraus.

    Für die Fehlerschranke zählen auch „x“ (Falschgeber) und „~“ (zu unruhig) – das sind
    genau die Momente, in denen die NMEA-Zeit weiter danebenliegt als ihre Schranke. Ließe
    man sie weg, sähe die Messung nur die braven Werte, und jede kleinere Schranke machte
    noch mehr Ausreißer zu „x“ – die Schranke schrumpfte sich selbst klein."""
    if not isinstance(gps, dict):
        return False
    offset = gps.get("o")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
        return False
    if gps.get("s") == "?":
        return False
    reach = gps.get("r", gps.get("reach"))
    if isinstance(reach, (int, float)) and not isinstance(reach, bool) and reach == 0:
        return False
    return True


def _net_offsets(sources: dict, gps_name: str, states: set[str]) -> list[float]:
    return [v.get("o") for name, v in sources.items()
            if name != gps_name and isinstance(v, dict) and v.get("s") in states
            and v.get("k") != "#"
            and isinstance(v.get("o"), (int, float)) and not isinstance(v.get("o"), bool)
            and math.isfinite(v.get("o"))]


CONSENSUS_SOURCES = 2   # „x“-Werte zählen für den Offset, wenn so viele genutzte Netzquellen dagegenstehen


def calibration_usable(sources: dict, gps_name: str) -> bool:
    """Taugt der GPS-Wert dieses Messpunkts für die Offset-Kalibrierung?

    Wie gps_measured(), aber ein „x“ (Falschgeber) zählt mit, wenn mindestens CONSENSUS_SOURCES
    genutzte Netzquellen („*“/„+“) im selben Messpunkt den Vergleich liefern (1.5.1). Genau dann
    ist das GPS ja wegen eines bleibenden Versatzes „x“ – ließe man diese Werte weg, hätte der
    Kalibrier-Assistent keine Daten, bis die Fehlerschranke über den Versatz gewachsen ist. Der
    Median bleibt robust gegen einzelne Ausreißer; „~“ (zu unruhig) zählt weiter nicht."""
    gps = (sources or {}).get(gps_name)
    if gps_measured(gps):
        return True
    if not isinstance(gps, dict) or gps.get("s") != "x" or not _gps_has_data(gps):
        return False
    return len(_net_offsets(sources, gps_name, {"*", "+"})) >= CONSENSUS_SOURCES


def gps_differences(samples: list[dict], gps_name: str, for_bound: bool = False,
                    consensus_x: bool = False) -> tuple[list[float], list[float]]:
    """Differenzen GPS − Mittel der genutzten Netzwerkquellen („*“/„+“) je Messpunkt.

    Grundlage für den Kalibrier-Assistenten (Median = Verspätung) und für die ehrliche
    Fehlerschranke des GPS ohne PPS (gpsquality.measure, Streuung).

    for_bound=True (Fehlerschranke, Delay-Vorschlag): GPS-Werte mit „x“/„~“ zählen mit
    (siehe _gps_has_data). Gibt es keine genutzte Netzquelle – etwa weil chrony gerade das
    GPS gewählt hat und die Netzquellen darum als „-“ führt –, dienen die übrigen
    erreichbaren Netzquellen („-“) als Vergleich. Sonst fiele die Messung genau dann aus,
    wenn das GPS gewinnt, und die (kleine) Schranke bliebe eingefroren.

    consensus_x=True (Offset-Kalibrierung): „x“ zählt mit, wenn ≥ 2 genutzte Netzquellen
    dagegenstehen (siehe calibration_usable)."""
    diffs, times = [], []
    valid = _gps_has_data if for_bound else gps_measured
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sources = sample.get("sources") or {}
        gps = sources.get(gps_name)
        if not (valid(gps) or (consensus_x and calibration_usable(sources, gps_name))):
            continue  # GPS ohne Daten („?“, Reach 0 …) – sonst zählte 0 − Netz als Verspätung
        reference = _net_offsets(sources, gps_name, {"*", "+"})
        if not reference and for_bound:
            reference = _net_offsets(sources, gps_name, {"-"})
        if not reference:
            continue
        diffs.append(gps["o"] - sum(reference) / len(reference))
        times.append(sample["t"])
    return diffs, times


def _half_shift(diffs: list[float], times: list[float]) -> float | None:
    """Median der zweiten minus Median der ersten Hälfte des Messzeitraums (Sprung im Fenster?)."""
    if len(diffs) < 20 or not times:
        return None
    middle = (times[0] + times[-1]) / 2
    first = [d for d, t in zip(diffs, times) if t <= middle]
    second = [d for d, t in zip(diffs, times) if t > middle]
    if len(first) < 10 or len(second) < 10:
        return None
    return _median(second) - _median(first)


def calibrate(samples: list[dict], gps_name: str, current_offset: float,
              current_delay: float) -> dict[str, Any]:
    """Vergleicht den GPS-Offset mit den aktiven Netzwerkquellen.

    Alle Offsets sind relativ zur Systemuhr. Die Differenz GPS − Netz ist
    deshalb unabhängig davon, welche Quelle die Uhr gerade regelt, genau die
    Verspätung des GPS. Die Refclock-Option „offset“ verschiebt die GPS-Zeit
    um ihren Wert nach vorn: neuer Offset = aktueller Offset + gemessene
    Differenz.
    """
    diffs, times = gps_differences(samples, gps_name, consensus_x=True)

    result: dict[str, Any] = {
        "samples": len(diffs), "current_offset": current_offset,
        "current_delay": current_delay, "duration_seconds": (times[-1] - times[0]) if times else 0,
    }
    if len(diffs) < 10:
        result.update(status="insufficient",
                      message="Noch zu wenige gemeinsame Messungen. Es braucht GPS-Werte und "
                              "mindestens eine aktive Netzwerkquelle gleichzeitig.")
        return result

    median = _median(diffs)
    # Robuste Streuung: MAD skaliert auf die Standardabweichung einer Normalverteilung.
    mad = _median([abs(d - median) for d in diffs]) * 1.4826
    # Delay ab 1.5 (E16): nie kleiner als die gemessene Streuung. Gerechnet um den Median
    # (nach dem Übernehmen des Offsets liegt das GPS dort), mit 95-%-Quantil statt nur MAD –
    # sonst übersieht ein kleiner MAD die Ausreißer von ± 60 ms, und chrony hielte das GPS
    # für genauer als gute NTS-Quellen.
    # Für die Streuung zählen auch die Werte, die chrony als „x“/„~“ verworfen hat (siehe
    # gps_differences(for_bound=True)) – sonst wäre der Vorschlag zu klein.
    all_diffs, _ = gps_differences(samples, gps_name, for_bound=True)
    honest = gpsquality.spread([d - median for d in (all_diffs or diffs)]) or {}
    result.update(
        bias=median, spread=mad, spread_p95=honest.get("p95_abs"),
        suggested_offset=round(current_offset + median, 4),
        suggested_delay=honest.get("delay", gpsquality.DEFAULT_DELAY),
        suggested_precision=honest.get("precision"),
        series=[{"t": t, "d": d} for t, d in zip(times[-600:], diffs[-600:])],
        half_shift=_half_shift(diffs, times),
    )
    if result["duration_seconds"] < 1800:
        result.update(status="preliminary",
                      message="Vorläufiger Wert. Für einen belastbaren Offset mindestens 30 "
                              "Minuten, besser einige Stunden messen lassen.")
    elif abs(median) < max(0.5 * mad, 0.0005):
        result.update(status="calibrated",
                      message="Das GPS ist bereits gut kalibriert – die Abweichung liegt im "
                              "Rauschen.")
    else:
        result.update(status="ready",
                      message="Genug Messungen für einen belastbaren Vorschlag.")
    return result
