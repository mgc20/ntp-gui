"""Gemeinsamer Datenspeicher: eine SQLite-Datei im Datenverzeichnis.

Verlauf, Ereignisprotokoll und API-Schlüssel liegen in DATA_DIR/ntp-gui.db.
SQLite gehört zur Python-Standardbibliothek – keine neue Abhängigkeit, keine
Wolke, eine einzige Datei, die mit dem Volume gesichert wird.

Nutzung:

    conn = store.connect()                 # gemeinsame Verbindung (WAL-Modus)
    store.migrate("events", [SQL_V1, SQL_V2])
    with store.transaction() as db:        # serialisiert + commit/rollback
        db.execute("INSERT ...", params)
    rows = store.query("SELECT ...", params)

Eine Verbindung pro Datei wird von allen Threads geteilt
(check_same_thread=False). sqlite3-Verbindungen sind nicht für gleichzeitige
Nutzung gedacht – jede Nutzung läuft deshalb unter der Sperre der Datei
(lock()/transaction()/execute()/query()).

Warum WAL: Leser blockieren den Schreiber nicht, und synchronous=NORMAL
schreibt deutlich seltener auf die SD-Karte eines Raspberry Pi als der
Standard – ein Stromausfall kann höchstens die letzten Transaktionen kosten,
nie die Datei beschädigen.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from typing import Any, Iterable, Iterator

DB_NAME = "ntp-gui.db"

# Für Tests oder Sonderfälle: fester Ordner statt settings.DATA_DIR.
DATA_DIR: str | None = None

_REGISTRY_LOCK = threading.Lock()
_CONNECTIONS: dict[str, sqlite3.Connection] = {}
_LOCKS: dict[str, threading.RLock] = {}


def data_dir() -> str:
    if DATA_DIR:
        return DATA_DIR
    try:
        import settings  # spät importiert: folgt Änderungen an settings.DATA_DIR (Tests)
        return settings.DATA_DIR
    except Exception:
        return os.environ.get("NTPGUI_DATA_DIR", "/var/lib/chrony/ntp-gui")


def path() -> str:
    """Pfad der Datenbank: DATA_DIR/ntp-gui.db."""
    return os.path.join(data_dir(), DB_NAME)


def _key(db_path: str | None) -> str:
    return os.path.abspath(db_path or path())


def lock(db_path: str | None = None) -> threading.RLock:
    """Die Sperre, unter der jede Nutzung der Verbindung zu db_path läuft."""
    key = _key(db_path)
    with _REGISTRY_LOCK:
        return _LOCKS.setdefault(key, threading.RLock())


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Gemeinsame Verbindung (eine je Datei). Wirft sqlite3.Error/OSError, wenn es nicht geht."""
    key = _key(db_path)
    with _REGISTRY_LOCK:
        conn = _CONNECTIONS.get(key)
        if conn is not None:
            return conn
        directory = os.path.dirname(key)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        new_file = not os.path.exists(key)
        conn = sqlite3.connect(key, timeout=10.0, check_same_thread=False,
                               isolation_level=None)  # Autocommit; Transaktionen explizit
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                         "name TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        except sqlite3.Error:
            conn.close()
            raise
        if new_file:
            # Enthält API-Schlüssel-Hashes und Client-Daten: nur für den Dienst lesbar.
            for suffix in ("", "-wal", "-shm"):
                with contextlib.suppress(OSError):
                    os.chmod(key + suffix, 0o600)
        _CONNECTIONS[key] = conn
        _LOCKS.setdefault(key, threading.RLock())
        return conn


@contextlib.contextmanager
def transaction(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Serialisierte Schreib-Transaktion: commit am Ende, rollback bei Fehler."""
    conn = connect(db_path)
    with lock(db_path):
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def execute(sql: str, params: Iterable[Any] | dict = (), db_path: str | None = None) -> int:
    """Einzelne Anweisung unter der Sperre; gibt rowcount (bzw. lastrowid bei INSERT) zurück."""
    conn = connect(db_path)
    with lock(db_path):
        cur = conn.execute(sql, params)
        if sql.lstrip().upper().startswith("INSERT"):
            return int(cur.lastrowid or 0)
        return cur.rowcount


def query(sql: str, params: Iterable[Any] | dict = (), db_path: str | None = None) -> list[tuple]:
    conn = connect(db_path)
    with lock(db_path):
        return conn.execute(sql, params).fetchall()


def migrate(name: str, steps: list[str], db_path: str | None = None) -> int:
    """Wendet die noch fehlenden Schritte für `name` an. Gibt die Zahl neuer Schritte zurück.

    steps[i] bringt das Schema von Version i auf i+1 (ein SQL-Text, darf mehrere
    Anweisungen enthalten). Schritte werden nie geändert, nur angehängt.
    """
    conn = connect(db_path)
    with lock(db_path):
        row = conn.execute("SELECT version FROM schema_migrations WHERE name=?", (name,)).fetchone()
        current = int(row[0]) if row else 0
        applied = 0
        for version in range(current, len(steps)):
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _split_sql(steps[version]):
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations(name, version) VALUES(?, ?) "
                             "ON CONFLICT(name) DO UPDATE SET version=excluded.version",
                             (name, version + 1))
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            applied += 1
        return applied


def schema_version(name: str, db_path: str | None = None) -> int:
    rows = query("SELECT version FROM schema_migrations WHERE name=?", (name,), db_path)
    return int(rows[0][0]) if rows else 0


def _split_sql(script: str) -> list[str]:
    """Zerlegt ein Skript in Anweisungen (sqlite3.complete_statement achtet auf Strings)."""
    statements, buffer = [], ""
    for part in script.split(";"):
        buffer += part + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip().strip(";").strip():
                statements.append(buffer.strip())
            buffer = ""
    rest = buffer.rstrip(";").strip()
    if rest:
        statements.append(rest)
    return statements


def close(db_path: str | None = None) -> None:
    """Schließt die Verbindung (Tests, Beenden). Nächstes connect() öffnet neu."""
    key = _key(db_path)
    with _REGISTRY_LOCK:
        conn = _CONNECTIONS.pop(key, None)
        lk = _LOCKS.get(key)
    if conn is not None:
        with lk or contextlib.nullcontext():
            with contextlib.suppress(sqlite3.Error):
                conn.close()


def close_all() -> None:
    with _REGISTRY_LOCK:
        keys = list(_CONNECTIONS)
    for key in keys:
        close(key)
