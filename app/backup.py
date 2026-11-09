"""Sicherung und Wiederherstellung (1.6, Thema T5) – alles außer Position und Geheimnissen.

GET /api/backup liefert eine .tar.gz mit genau diesen Teilen:

  manifest.json       Format, ntp-gui-Version, Schema-Versionen, Teile mit Größe und SHA-256
  einstellungen.json  die im Dashboard gespeicherten Werte – ohne Passwort-Hash und ohne
                      Werte, die Geheimnisse enthalten können (SECRET_SETTINGS)
  kalibrierung.json   Zustand und Protokoll der GPS-Kalibrierung (autocal.json), Schlüssel
                      mit Position/Winkel/Geheimnis entfernt
  daten.sqlite        ein Abzug der Datenbank als NEUE, leere Datei, in die nur die Tabellen
                      und Spalten aus ALLOWLIST per INSERT … SELECT kopiert werden

Warum ein neuer Abzug statt einer Kopie von ntp-gui.db: In den freien Seiten einer SQLite-Datei
stehen gelöschte Werte weiter (alte GPS-Zustände, API-Schlüssel-Hashes, Satellitenwinkel aus
Antennentests). Die neue Datei enthält nur, was ausdrücklich auf der Allowlist steht – auch
Spalten, die eine spätere Version hinzufügt, erst nach ausdrücklicher Freigabe hier.

Nie in der Sicherung (Entscheidung F4): gelernte GPS-Position, Satellitenwinkel (Tabellen
gnss_state, gps_bound, antenna_tests, holdover_*), API-Schlüssel (api_keys), Passwort-Hash,
Kanal-Tokens (notify_channels.secret), ntfy-Themen (auf öffentlichen Servern das einzige
Zugangsmerkmal), Adressen mit Pfad (dort stecken oft Webhook-IDs – gespeichert wird dann nur
Schema://Host:Port), DNS-over-HTTPS-Adressen (Konto-Kennung im Pfad), NTS-Schlüssel und
-Zertifikate (liegen nicht in DATA_DIR und werden nie gelesen). Die Vorschau beim
Wiederherstellen nennt, was neu einzugeben ist.

Wiederherstellen in zwei Schritten (stage_upload → preview → apply):
  * Upload höchstens MAX_UPLOAD Bytes (eigenes Limit statt MAX_BODY) in einen privaten
    Ordner unter DATA_DIR; dort bleibt er höchstens PENDING_TTL Sekunden.
  * Prüfung ohne tar.extract(): nur bekannte Dateinamen, nur reguläre Dateien (keine Links,
    Gerätedateien, Ordner), kein absoluter Pfad, kein „..“, dazu tarfile.data_filter als zweite
    Meinung; Größe je Teil und entpackt insgesamt begrenzt (Gzip-Bombe), PAX-/Langname-Köpfe
    höchstens 64 KiB; Prüfsummen aus dem Manifest; Format- und Schema-Version höchstens die
    eigene (ältere werden migriert, neuere abgelehnt); die Datenbank muss genau das Schema der
    Allowlist haben (keine Views, Trigger, Indizes, fremden Tabellen).
  * apply: erst eine Sicherung des jetzigen Stands nach DATA_DIR/sicherungen, dann alles oder nichts:
    Einstellungen und Kalibrierung als geprüfte temporäre Dateien, dann die Datenbank in EINER
    Transaktion auf der gemeinsamen Verbindung (store.lock): je Tabelle DELETE + INSERT … SELECT aus
    der angehängten Sicherung – mit denselben Filtern wie beim Erstellen (Messpunkt-Allowlist,
    Position/Winkel/Geheimnisse, gültige IP-Adressen, feste Muster), denn das Manifest ist nicht
    signiert. Direkt vor dem COMMIT, noch in der Transaktion, werden die Dateien per os.replace
    eingesetzt; scheitert das oder das COMMIT, kommen die alten Dateien zurück und die Transaktion wird
    verworfen. Scheitert erst danach etwas, wird die eben geschriebene automatische Sicherung
    zurückgespielt – die Kanäle dabei aus ihren vor dem Austausch festgehaltenen Zeilen (mit Tokens).
  * Messpunkte nur bis zum Zeitpunkt der Sicherung (manifest.created, höchstens MAX_CREATED_AHEAD in der
    Zukunft) und bis jetzt + FUTURE_TOL; Texte und Quellnamen in Messpunkten ohne Koordinaten.
  * Kanäle gehen durch notify.validate. Vorhandene (gleiche ID, Art, Schema://Host:Port) behalten
    ihre Tokens von hier, alle anderen kommen ausgeschaltet.

Warum die laufende Datenbank nicht durch eine Datei ersetzt wird: Alle Threads teilen sich eine
offene Verbindung (store.py) im WAL-Modus. Eine Datei darunter auszutauschen ließe -wal/-shm
zur alten Datei passen (Beschädigung), offene Verbindungen sähen die alte Datei weiter, und
Tabellen außerhalb der Sicherung (API-Schlüssel, GNSS-Zustand) gingen verloren. Über die
Verbindung selbst ist der Austausch atomar (Transaktion), wartet sauber auf laufende Schreiber
(dieselbe Sperre wie alle anderen) und lässt alles außerhalb der Allowlist unberührt.

Nur Standardbibliothek. Nichts geht hinaus: Die Sicherung ist ein Download.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
import urllib.parse
import zlib
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable

import egress
import settings
import store

FORMAT = "ntp-gui-sicherung"
FORMAT_VERSION = 1
DUMP_SCHEMA = 1              # Version der Allowlist (Tabellen und Spalten in daten.sqlite)

MANIFEST = "manifest.json"
SETTINGS_PART = "einstellungen.json"
AUTOCAL_PART = "kalibrierung.json"
DB_PART = "daten.sqlite"
PARTS = (MANIFEST, SETTINGS_PART, AUTOCAL_PART, DB_PART)

MAX_UPLOAD = 200 * 1024 * 1024          # Upload (komprimiert)
PART_LIMITS = {MANIFEST: 1024 * 1024, SETTINGS_PART: 4 * 1024 * 1024, AUTOCAL_PART: 8 * 1024 * 1024,
               DB_PART: 1024 * 1024 * 1024}
MAX_UNPACKED = sum(PART_LIMITS.values()) + 1024 * 1024   # entpackt insgesamt, mit Tar-Köpfen
MAX_META_HEADER = 64 * 1024              # PAX-Kopf / GNU-Langname
PENDING_TTL = 15 * 60.0                  # so lange bleibt ein geprüfter Upload liegen
CHUNK = 64 * 1024
COMPRESS_LEVEL = 3                       # gzip: auf dem Pi deutlich schneller als 9, kaum größer

BACKUP_DIR = "sicherungen"               # unter DATA_DIR
STAGING_DIR = ".wiederherstellen"        # unter DATA_DIR, privat (0700)
AUTO_PREFIX = "vor-wiederherstellung-"
NIGHTLY_PREFIX = "nacht-"
KEEP_AUTO = 5
KEEP_NIGHTLY = 7
NIGHTLY_HOUR = 3                         # Ortszeit des Servers
_STORED_RE = re.compile(r"^(?:vor-wiederherstellung|nacht)-\d{8}(?:-\d{6})?\.tar\.gz$")

# Einstellungen, die Geheimnisse enthalten können – nie sichern: DoH-Pfad, DoT-Name und feste Adressen
# tragen bei NextDNS die persönliche Konto-Kennung (<id>.dns.nextdns.io). Beim Wiederherstellen bleibt
# der jetzige Wert stehen; fehlt er, nennt die Vorschau ihn unter „neu eingeben“.
SECRET_SETTINGS = frozenset(settings.MASKED_FOR_READ) | {"dns_dot", "dns_pin"}

# Einstellungen, deren Änderung Zugang, Erreichbarkeit oder ausgehende Verbindungen betrifft – die
# Vorschau nennt sie einzeln mit altem und neuem Wert (ein präpariertes Archiv soll nichts still ändern).
SECURITY_SETTINGS = ("bind_address", "allow_networks", "deny_networks", "trusted_proxies", "web_allowed_hosts",
                     "clock_public", "notify_lan_addresses", "notify_dashboard_url", "update_check",
                     "clients_rdns", "nts_server_enable", "ntp_sources", "dns_mode", "dns_servers")
MAX_META_HEADERS = 32                    # PAX-/Langname-Köpfe je Archiv (sonst Rekursion in tarfile)
# Zeitpunkt der Sicherung (manifest.created, nicht signiert): höchstens so weit in der Zukunft, sonst
# abgelehnt. Messpunkte übernimmt das Einspielen nur bis created und bis jetzt + FUTURE_TOL – Messpunkte
# aus der Zukunft blieben sonst stehen, auch nach dem Zurückspielen der automatischen Sicherung.
MAX_CREATED_AHEAD = 86400.0
FUTURE_TOL = 600.0


class RestoreError(ValueError):
    """Sicherung abgelehnt (Text für die Oberfläche). Es wurde nichts geschrieben."""


class BackupError(RuntimeError):
    """Sicherung ließ sich nicht erstellen."""


# ---------------------------------------------------------------------------
# Filter für JSON-Inhalte (zweite Linie hinter der Spalten-Allowlist)
# ---------------------------------------------------------------------------

# Jedes Feld, das der Verlauf schreibt (history._NUMERIC_TOP, _GROUPS, „sources“, „z“), muss hier stehen –
# sonst verliert die Sicherung es still (test_backup.HistoryFieldsTest prüft das). 1.6: „pi_state“ (Zahl)
# und „z“ (Zähler je Zustand in samples_5m, Schlüssel wie timeline.CODES).
_SAMPLE_TOP = frozenset({"t", "offset", "rms", "freq", "skew", "root_delay", "root_dispersion", "stratum",
                         "served", "clients", "temp", "pi_state", "sources", "gps", "ptp", "z"})
_SAMPLE_GPS = frozenset({"used", "seen", "hdop", "snr", "mode", "cn4"})
_SAMPLE_PTP = frozenset({"offset_ns", "delay_ns", "freq_ppb", "rms_ns"})
_SAMPLE_SOURCE = frozenset({"o", "s", "k", "j"})
_SAMPLE_Z = frozenset({"g", "w", "c", "h"})
_SAMPLE_GROUPS = {"gps": _SAMPLE_GPS, "ptp": _SAMPLE_PTP, "z": _SAMPLE_Z}


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, str)) or (
        isinstance(value, (int, float)) and math.isfinite(value))


_TEXT_MAX = 64          # Textwerte in Messpunkten: kurze Kennungen („*“, „+“, „#“)
_NAME_MAX = 255        # Quellnamen: Hostname, IP-Adresse, Referenzuhr


def _text_ok(value: Any, limit: int = _TEXT_MAX) -> bool:
    """Text in einem Messpunkt: kurz und ohne Koordinaten (sonst kämen Positionen über Textfelder durch)."""
    return not isinstance(value, str) or (len(value) <= limit and scrub_text(value) == value)


def _clean_text(value: Any, limit: int = _TEXT_MAX) -> Any:
    return scrub_text(value)[:limit] if isinstance(value, str) else value


def _sample_ok(data: Any) -> bool:
    """Hat der Messpunkt nur Felder der Allowlist und nur Texte ohne Koordinaten (dann bleibt der Text,
    wie er ist)?"""
    if not isinstance(data, dict) or not set(data) <= _SAMPLE_TOP:
        return False
    for key, value in data.items():
        if key == "sources":
            if not isinstance(value, dict) or not all(
                    _text_ok(name, _NAME_MAX) and isinstance(v, dict) and set(v) <= _SAMPLE_SOURCE
                    and all(_scalar(x) and _text_ok(x) for x in v.values())
                    for name, v in value.items()):
                return False
        elif key in _SAMPLE_GROUPS:
            if not isinstance(value, dict) or not set(value) <= _SAMPLE_GROUPS[key] or not all(
                    _scalar(x) and _text_ok(x) for x in value.values()):
                return False
        elif not _scalar(value) or not _text_ok(value):
            return False
    return True


def sample_json(text: Any) -> str | None:
    """Messpunkt (samples/samples_5m) auf die Felder der Allowlist kürzen, Koordinaten aus Texten und
    Quellnamen entfernen. None = ungültig."""
    if not isinstance(text, str):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if _sample_ok(data):
        return text
    if not isinstance(data, dict):
        return None
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key not in _SAMPLE_TOP:
            continue
        if key == "sources" and isinstance(value, dict):
            out[key] = {_clean_text(str(name), _NAME_MAX): {k: _clean_text(v) for k, v in entry.items()
                                                            if k in _SAMPLE_SOURCE and _scalar(v)}
                        for name, entry in value.items() if isinstance(entry, dict)}
        elif key in _SAMPLE_GROUPS and isinstance(value, dict):
            allowed = _SAMPLE_GROUPS[key]
            out[key] = {k: _clean_text(v) for k, v in value.items() if k in allowed and _scalar(v)}
        elif key != "sources" and key not in _SAMPLE_GROUPS and _scalar(value):
            out[key] = _clean_text(value)
    return json.dumps(out, separators=(",", ":"))


_DROP_TOKENS = (egress.POSITION_TOKENS | egress.ANGLE_TOKENS | egress.SKY_TOKENS
                | egress.SECRET_TOKENS | {"token", "apikey", "hash", "cookie", "authorization"})
_DROP_KEYS = egress.POSITION_KEYS | egress.ANGLE_KEYS | egress.SECRET_KEYS


def _drop_key(key: Any) -> bool:
    text = str(key)
    return (re.sub(r"[\s_\-.]", "", text).lower() in _DROP_KEYS) or bool(egress.key_tokens(text) & _DROP_TOKENS)


def _fine(value: Any) -> bool:
    """Zahl mit mehr als drei Nachkommastellen (Koordinaten aus dem GPS haben fünf bis sieben; Messwerte,
    die hier in Listen stehen – etwa die Abfrageabstände der Clients –, sind auf drei gerundet)."""
    return abs(value * 1000.0 - round(value * 1000.0)) > 1e-6 * max(1.0, abs(value))


def _coord_list(value: Any) -> bool:
    """Liste wie [48.137154, 11.576124] oder [Breite, Länge, Höhe]: zwei bis drei Zahlen, die ersten beiden
    im Bereich von Breite (1–90) und Länge (1–180), nicht ganzzahlig, mindestens eine fein aufgelöst.
    Kleine Werte (Abweichungen, Frequenzen in Sekunden) und Zeitstempel fallen nie darunter."""
    if not isinstance(value, (list, tuple)) or not 2 <= len(value) <= 3:
        return False
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value):
        return False
    lat, lon = value[0], value[1]
    return (1.0 <= abs(lat) <= 90.0 and 1.0 <= abs(lon) <= 180.0 and lat != int(lat) and lon != int(lon)
            and (_fine(lat) or _fine(lon)))


def scrub(value: Any) -> Any:
    """Schlüssel mit Position, Winkeln, Satellitenlisten und Geheimnissen entfernen; Koordinatenpaare
    in Texten ersetzen, Koordinatenlisten ([Breite, Länge(, Höhe)]) unter jedem Schlüssel verwerfen."""
    if _coord_list(value):
        return None
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not _drop_key(k) and not _coord_list(v)}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value if not _coord_list(v)]
    if isinstance(value, str):
        return scrub_text(value)
    return value


# Koordinaten in anderer Schreibweise als dem Dezimalpaar: Grad/Minuten/Sekunden (auch mit der Halbkugel
# davor), NMEA, „48.137154° N“. Die Muster stammen aus egress; das letzte erfasst jede Angabe mit Grad und
# Minuten (48°08', 11° 34' 34.0") – in Ereignistexten ist das immer ein Ort.
_TEXT_COORD_RES = (egress._COORD_NMEA_RE, egress._COORD_HEMI_RE, egress._COORD_DMS_RE, egress._COORD_DEG_RE,
                   re.compile(r"\d{1,3}\s*°\s*\d{1,2}(?:[.,]\d+)?\s*['′](?:\s*\d{1,2}(?:[.,]\d+)?\s*(?:\"|″|''))?"))


def scrub_text(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    spans = egress.coord_pair_spans(text)
    for start, end in reversed(spans):
        text = text[:start] + "[Position entfernt]" + text[end:]
    if any(c.isdigit() for c in text):
        for pattern in _TEXT_COORD_RES:
            text = pattern.sub("[Position entfernt]", text)
    return text


def scrub_json(text: Any) -> Any:
    """JSON-Text durch scrub(); kein JSON → None (Spalte wird leer)."""
    if text is None:
        return None
    if not isinstance(text, str):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    clean = scrub(data)
    return text if clean == data else json.dumps(clean, separators=(",", ":"), ensure_ascii=False)


def _url_cut(url: Any) -> int:
    try:
        import notify
        return int(bool(notify.url_hidden(str(url or ""))))
    except Exception:
        return 1


def _url_origin(url: Any) -> str:
    """Adresse ohne Pfad/Abfrage, wenn dort Zugangsdaten stehen können (wie notify.display_url)."""
    text = str(url or "")
    if not _url_cut(text):
        return text
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}" if parts.scheme and host else ""
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Allowlist: Tabellen und Spalten von daten.sqlite
# ---------------------------------------------------------------------------
#
# Je Spalte: (Name im Abzug, Typ, Ausdruck über der Quelltabelle). Der Ausdruck darf die
# Funktionen ntpg_sample/ntpg_scrub/ntpg_text/ntpg_url/ntpg_url_cut benutzen. Neue Spalten
# kommen erst hinein, wenn sie hier stehen (DUMP_SCHEMA erhöhen, Migration ergänzen).

# Schnellweg (30 Tage Verlauf ≈ 260 000 Messpunkte, auf dem Pi in wenigen Sekunden): Die Form eines
# Messpunkts – der Text ohne Zahlen und true/false/null – wiederholt sich fast immer. Das Urteil von
# _sample_ok() gilt für alle Texte derselben Form und wird gemerkt. Ohne Backslash im Text sind JSON-Strings
# genau "[^"]*"; der Ausdruck nimmt jeden String als Ganzes (Gruppe 1, bleibt stehen) und entfernt nur
# Zahlen und Literale außerhalb davon. Schlüssel, Quellnamen und Textwerte stehen also unverändert in der
# Form – gleiche Form heißt gleiche Schlüssel, gleiche Texte und nur skalare Werte an denselben Stellen,
# darum gleiches Urteil (Zahlen und Literale prüft _sample_ok() nur auf „skalar“).
_VALUE_RE = re.compile(r'("[^"]*")|-?\d[\d.eE+-]*|true|false|null')
_SHAPES: dict[str, bool] = {}
_SHAPES_MAX = 2048


def sample_fast(text: Any) -> str | None:
    """Wie sample_json(); erwartet gültiges JSON (SQL prüft vorher json_valid)."""
    if not isinstance(text, str) or "\\" in text:
        return sample_json(text)
    shape = _VALUE_RE.sub(r"\1", text)
    verdict = _SHAPES.get(shape)
    if verdict is None:
        try:
            verdict = _sample_ok(json.loads(text))
        except ValueError:
            verdict = False
        if len(_SHAPES) >= _SHAPES_MAX:
            _SHAPES.clear()
        _SHAPES[shape] = verdict
    return text if verdict else sample_json(text)


SAMPLE_SQL = "CASE WHEN json_valid(r.json) THEN ntpg_sample(r.json) END"

ALLOWLIST: dict[str, dict[str, Any]] = {
    "samples": {"part": "history", "columns": [
        ("t", "INTEGER", "t"), ("json", "TEXT", SAMPLE_SQL)]},
    "samples_5m": {"part": "history", "columns": [
        ("b", "INTEGER", "b"), ("t", "INTEGER", "t"), ("json", "TEXT", SAMPLE_SQL)]},
    "events": {"part": "events", "order": "id", "columns": [
        ("t", "REAL", "t"), ("kind", "TEXT", "kind"), ("level", "TEXT", "level"),
        ("title", "TEXT", "ntpg_text(title)"), ("data", "TEXT", "ntpg_scrub(data)"),
        ("source", "TEXT", "source")]},
    "clientmon_clients": {"part": "clients", "columns": [
        ("ip", "TEXT", "ip"), ("data", "TEXT", "ntpg_scrub(data)"), ("updated", "REAL", "updated")]},
    "clientmon_samples": {"part": "clients", "order": "rowid", "columns": [
        ("ip", "TEXT", "ip"), ("t", "REAL", "t"), ("offset", "REAL", "offset"), ("poll", "INTEGER", "poll"),
        ("version", "INTEGER", "version"), ("interval", "REAL", "interval")]},
    "clientmon_meta": {"part": "names", "columns": [
        ("ip", "TEXT", "ip"), ("name", "TEXT", "name"), ("note", "TEXT", "note"), ("updated", "REAL", "updated")]},
    "client_groups": {"part": "groups", "columns": [
        ("id", "INTEGER", "id"), ("name", "TEXT", "name"), ("network", "TEXT", "network"),
        ("updated", "REAL", "updated")]},
    "client_rules": {"part": "rules", "columns": [
        ("ip", "TEXT", "ip"), ("silent_h", "REAL", "silent_h"), ("offset_ms", "REAL", "offset_ms"),
        ("offset_min", "INTEGER", "offset_min"), ("mute", "INTEGER", "mute"), ("expect", "TEXT", "expect"),
        ("state", "TEXT", "ntpg_scrub(state)"), ("updated", "REAL", "updated")]},
    "client_hourly": {"part": "clients", "columns": [
        ("ip", "TEXT", "ip"), ("hour", "INTEGER", "hour"), ("n", "INTEGER", "n"), ("med", "REAL", "med"),
        ("p95", "REAL", "p95"), ("lo", "REAL", "lo"), ("hi", "REAL", "hi")]},
    "client_inventory": {"part": "clients", "columns": [
        ("key", "TEXT", "key"), ("first_seen", "REAL", "first_seen")]},
    "notify_channels": {"part": "channels", "columns": [
        ("id", "TEXT", "id"), ("name", "TEXT", "name"), ("type", "TEXT", "type"), ("enabled", "INTEGER", "enabled"),
        ("url", "TEXT", "ntpg_url(url)"), ("url_cut", "INTEGER", "ntpg_url_cut(url)"),
        # ntfy: Wer das Thema kennt, liest und sendet mit (öffentliche Server) – es zählt als Geheimnis.
        # Apprise: Der Schlüssel öffnet die gespeicherte Konfiguration samt Zugangsdaten (/get/<key>).
        ("topic", "TEXT", "CASE WHEN type IN ('ntfy', 'apprise') THEN '' ELSE topic END"),
        ("topic_cut", "INTEGER", "CASE WHEN type IN ('ntfy', 'apprise') AND coalesce(topic, '') <> '' "
                                 "THEN 1 ELSE 0 END"),
        ("secret_set", "INTEGER", "CASE WHEN coalesce(secret, '') <> '' THEN 1 ELSE 0 END"),
        ("min_level", "TEXT", "min_level"), ("kinds", "TEXT", "kinds"), ("debounce_min", "INTEGER", "debounce_min"),
        ("rate_per_hour", "INTEGER", "rate_per_hour"), ("resolved", "INTEGER", "resolved"),
        ("created", "REAL", "created"), ("updated", "REAL", "updated")]},
}

# Migrationen eines älteren Abzugs auf DUMP_SCHEMA: {Zielversion: fn(conn)} – wie store.migrate nur
# anhängen, nie ändern. Version 1 ist die erste.
DUMP_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {}


def allowlist_schema() -> dict[str, list[tuple[str, str]]]:
    """{Tabelle: [(Spalte, Typ), …]} – so muss daten.sqlite aussehen (Test und Prüfung)."""
    return {table: [(name, kind) for name, kind, _expr in spec["columns"]] for table, spec in ALLOWLIST.items()}


def create_sql(table: str) -> str:
    """Genau dieser Text steht für jede Tabelle in sqlite_master von daten.sqlite (Prüfung beim Einspielen:
    kein WITHOUT ROWID, keine COLLATE-, DEFAULT-, CHECK- oder GENERATED-Zusätze)."""
    cols = ", ".join(f'"{name}" {kind}' for name, kind, _expr in ALLOWLIST[table]["columns"])
    return f'CREATE TABLE "{table}" ({cols})'


def _register(conn: sqlite3.Connection) -> None:
    conn.create_function("ntpg_sample", 1, sample_fast, deterministic=True)
    conn.create_function("ntpg_scrub", 1, scrub_json, deterministic=True)
    conn.create_function("ntpg_text", 1, scrub_text, deterministic=True)
    conn.create_function("ntpg_url", 1, _url_origin, deterministic=True)
    conn.create_function("ntpg_url_cut", 1, _url_cut, deterministic=True)
    conn.create_function("ntpg_ip", 1, _clean_ip, deterministic=True)
    conn.create_function("ntpg_word", 1, _word, deterministic=True)
    conn.create_function("ntpg_invkey", 1, _inventory_key, deterministic=True)


_WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAC_KEY_RE = re.compile(r"^mac:[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


def _word(value: Any) -> int:
    """Art/Herkunft eines Ereignisses: festes Muster (kleine Buchstaben, Ziffern, _ und -)."""
    return int(isinstance(value, str) and bool(_WORD_RE.match(value)))


def _clean_ip(value: Any) -> str | None:
    import clientinfo
    return clientinfo.clean_ip(value) if isinstance(value, str) else None


def _inventory_key(value: Any) -> str | None:
    """Schlüssel des Geräte-Inventars: „mac:aa:bb:…“ oder „ip:<IPv4>“ (clients3.inventory_key)."""
    if not isinstance(value, str):
        return None
    if _MAC_KEY_RE.match(value):
        return value
    if value.startswith("ip:"):
        addr = _clean_ip(value[3:])
        if addr is not None and ":" not in addr:
            return "ip:" + addr
    return None


def _uri(path: str, mode: str) -> str:
    return "file:" + urllib.parse.quote(os.path.abspath(path)) + f"?mode={mode}"


def _ensure_live_tables() -> None:
    """Tabellen der Allowlist in der laufenden Datenbank anlegen (Migrationen der Module)."""
    import clients3
    import events
    import history
    import notify
    store.migrate("history", history._SCHEMA)
    events._ensure()
    clients3._migrate(store)
    notify._ensure()


# ---------------------------------------------------------------------------
# Sicherung erstellen
# ---------------------------------------------------------------------------

_FLUSHERS: list[Callable[[], Any]] = []
_CREATE_LOCK = threading.Lock()


def add_flusher(callback: Callable[[], Any]) -> None:
    """Vor jeder Sicherung aufrufen (z. B. Verlauf aus dem Speicher schreiben). Fehler werden ignoriert."""
    if callback not in _FLUSHERS:
        _FLUSHERS.append(callback)


def _flush() -> None:
    for callback in list(_FLUSHERS):
        try:
            callback()
        except Exception:
            pass


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_dump(dest: str, source: str | None = None) -> dict[str, int]:
    """Neue Datei dest mit den Tabellen der Allowlist aus der Datenbank source. Gibt Zeilen je Tabelle."""
    source = source or store.path()
    if os.path.exists(dest):
        os.unlink(dest)
    conn = sqlite3.connect(_uri(dest, "rwc"), uri=True, isolation_level=None)
    counts: dict[str, int] = {}
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA secure_delete=ON")
        _register(conn)
        for table in ALLOWLIST:
            conn.execute(create_sql(table))
        if os.path.exists(source):
            conn.execute("ATTACH DATABASE ? AS src", (_uri(source, "ro"),))
            present = {row[0] for row in conn.execute("SELECT name FROM src.sqlite_master WHERE type='table'")}
            present_cols = {t: {row[1] for row in conn.execute(f'PRAGMA src.table_info("{t}")')}
                            for t in ALLOWLIST if t in present}
            conn.execute("BEGIN")  # ein Lesestand für alle Tabellen
            try:
                for table, spec in ALLOWLIST.items():
                    if table not in present:
                        counts[table] = 0
                        continue
                    names = ", ".join(f'"{name}"' for name, _kind, _expr in spec["columns"])
                    exprs = ", ".join(expr if _source_cols(expr) <= present_cols[table] else "NULL"
                                      for _name, _kind, expr in spec["columns"])
                    order = spec.get("order", "rowid")
                    cur = conn.execute(f'INSERT INTO main."{table}" ({names}) SELECT {exprs} '
                                       f'FROM src."{table}" AS r ORDER BY r.{order}')
                    counts[table] = cur.rowcount
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("DETACH DATABASE src")
        else:
            counts = {table: 0 for table in ALLOWLIST}
        # Eine neue Datei mit nur INSERTs hat keine freien Seiten; falls doch (SQLite-Interna), dicht packen.
        if conn.execute("PRAGMA freelist_count").fetchone()[0]:
            conn.execute("VACUUM")
    finally:
        conn.close()
    with contextlib.suppress(OSError):
        os.chmod(dest, 0o600)
    return counts


_IDENT_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\b")
_SQL_WORDS = {"ntpg_sample", "ntpg_scrub", "ntpg_text", "ntpg_url", "ntpg_url_cut", "case", "when", "then",
              "else", "end", "coalesce", "null", "json_valid", "r", "in"}  # „type“ ist eine echte Spalte


def _source_cols(expr: str) -> set[str]:
    """Spalten der Quelltabelle, die ein Ausdruck liest (ältere Datenbanken kennen manche nicht)."""
    text = re.sub(r"'[^']*'", "", expr)
    return {m for m in _IDENT_RE.findall(text) if m not in _SQL_WORDS}


def settings_part() -> dict:
    exported = settings.export_values()
    values = dict(exported.get("values") or {})
    omitted = sorted(k for k in values if k in SECRET_SETTINGS)
    for key in omitted:
        values.pop(key, None)
    return {"schema": exported.get("schema", settings.SCHEMA_VERSION), "values": values, "omitted": omitted}


def autocal_part() -> dict:
    import autocal
    with autocal._LOCK:
        state = autocal.load()
    return scrub(state)


def create(dest: str, version: str = "") -> dict:
    """Schreibt eine Sicherung nach dest (.tar.gz). Gibt das Manifest zurück."""
    with _CREATE_LOCK:
        _flush()
        with contextlib.suppress(Exception):
            # Die gemeinsame Verbindung hält -wal/-shm offen: Nur dann lässt sich eine WAL-Datenbank
            # nebenher schreibgeschützt (mode=ro) lesen.
            if os.path.exists(store.path()):
                store.connect()
        folder = os.path.dirname(os.path.abspath(dest))
        os.makedirs(folder, mode=0o700, exist_ok=True)
        work = tempfile.mkdtemp(prefix=".sicherung-", dir=folder)
        try:
            os.chmod(work, 0o700)
            created = time.time()
            files = {DB_PART: os.path.join(work, DB_PART), SETTINGS_PART: os.path.join(work, SETTINGS_PART),
                     AUTOCAL_PART: os.path.join(work, AUTOCAL_PART)}
            counts = write_dump(files[DB_PART])
            for name, content in ((SETTINGS_PART, settings_part()), (AUTOCAL_PART, autocal_part())):
                with open(files[name], "w", encoding="utf-8") as handle:
                    json.dump(content, handle, indent=2, ensure_ascii=False, sort_keys=True)
                    handle.write("\n")
            manifest = {
                "format": FORMAT, "format_version": FORMAT_VERSION, "ntp_gui_version": str(version or ""),
                "created": round(created, 3),
                "schema": {"dump": DUMP_SCHEMA, "settings": settings.SCHEMA_VERSION},
                "parts": [{"name": name, "size": os.path.getsize(path), "sha256": _sha256(path)}
                          for name, path in files.items()],
                "rows": counts,
                "excluded": ["GPS-Position", "Satellitenwinkel", "API-Schlüssel", "Passwort",
                             "Kanal-Tokens", "NTS-Schlüssel und -Zertifikate"],
            }
            files_order = [(MANIFEST, None)] + list(files.items())
            tmp = dest + ".tmp"
            with open(tmp, "wb") as raw:
                os.chmod(tmp, 0o600)
                with tarfile.open(fileobj=raw, mode="w:gz", format=tarfile.PAX_FORMAT,
                                  compresslevel=COMPRESS_LEVEL) as tar:
                    for name, path in files_order:
                        if path is None:
                            data = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
                            _add(tar, name, io.BytesIO(data), len(data), created)
                        else:
                            with open(path, "rb") as handle:
                                _add(tar, name, handle, os.path.getsize(path), created)
            os.replace(tmp, dest)
            return manifest
        finally:
            shutil.rmtree(work, ignore_errors=True)
            with contextlib.suppress(OSError):
                os.unlink(dest + ".tmp")


def _add(tar: tarfile.TarFile, name: str, handle, size: int, mtime: float) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = size, int(mtime), 0o600
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, handle)


def file_name(created: float | None = None) -> str:
    """Dateiname für den Download – ohne Hostnamen der Instanz."""
    return time.strftime("ntp-gui-sicherung-%Y%m%d-%H%M.tar.gz", time.localtime(created or time.time()))


# ---------------------------------------------------------------------------
# Gespeicherte Sicherungen im Datenverzeichnis (vor Wiederherstellung, nachts)
# ---------------------------------------------------------------------------

def backup_dir() -> str:
    return os.path.join(settings.DATA_DIR, BACKUP_DIR)


def _rotate(prefix: str, keep: int) -> None:
    try:
        names = sorted(n for n in os.listdir(backup_dir()) if n.startswith(prefix) and _STORED_RE.match(n))
    except OSError:
        return
    for name in names[:-keep] if keep > 0 else names:
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(backup_dir(), name))


def save_local(prefix: str, keep: int, version: str = "", now: float | None = None) -> str:
    """Sicherung nach DATA_DIR/sicherungen/<prefix><Zeit>.tar.gz; ältere über keep hinaus weg."""
    now = time.time() if now is None else now
    stamp = time.strftime("%Y%m%d" if prefix == NIGHTLY_PREFIX else "%Y%m%d-%H%M%S", time.localtime(now))
    name = f"{prefix}{stamp}.tar.gz"
    os.makedirs(backup_dir(), mode=0o700, exist_ok=True)
    create(os.path.join(backup_dir(), name), version)
    _rotate(prefix, keep)
    return name


def stored() -> list[dict]:
    """Gespeicherte Sicherungen, neueste zuerst."""
    out = []
    try:
        names = os.listdir(backup_dir())
    except OSError:
        return []
    for name in names:
        if not _STORED_RE.match(name):
            continue
        path = os.path.join(backup_dir(), name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "size": stat.st_size, "t": stat.st_mtime,
                    "kind": "nightly" if name.startswith(NIGHTLY_PREFIX) else "auto"})
    return sorted(out, key=lambda item: item["t"], reverse=True)


def stored_path(name: str) -> str | None:
    """Pfad einer gespeicherten Sicherung – nur Namen nach festem Muster, nie ein Pfad aus der Anfrage."""
    if not isinstance(name, str) or not _STORED_RE.match(name):
        return None
    path = os.path.join(backup_dir(), name)
    return path if os.path.isfile(path) and not os.path.islink(path) else None


def nightly_due(enabled: bool, now: float | None = None) -> bool:
    if not enabled:
        return False
    now = time.time() if now is None else now
    local = time.localtime(now)
    if local.tm_hour != NIGHTLY_HOUR:
        return False
    name = time.strftime(f"{NIGHTLY_PREFIX}%Y%m%d.tar.gz", local)
    return not os.path.exists(os.path.join(backup_dir(), name))


def nightly_runner(cfg: Callable[[], dict], version: str = "", stop: threading.Event | None = None,
                   interval: float = 600.0) -> None:
    """Thread: einmal je Nacht (gegen NIGHTLY_HOUR) sichern, wenn backup_nightly an ist."""
    stop = stop or threading.Event()
    while not stop.wait(interval):
        try:
            cleanup_staging()
            cleanup_downloads()
            if nightly_due(bool(cfg().get("backup_nightly"))):
                save_local(NIGHTLY_PREFIX, KEEP_NIGHTLY, version)
        except Exception as exc:  # nie sterben
            print(f"[backup] Nächtliche Sicherung fehlgeschlagen: {type(exc).__name__}: {exc}", flush=True)


# ---------------------------------------------------------------------------
# Wiederherstellen: hochladen und prüfen
# ---------------------------------------------------------------------------

_PENDING: dict[str, dict] = {}
_ACTIVE: set[str] = set()   # Ordner, die gerade geprüft oder übernommen werden – nie aufräumen
_PENDING_LOCK = threading.RLock()
_APPLY_LOCK = threading.Lock()
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def staging_root() -> str:
    return os.path.join(settings.DATA_DIR, STAGING_DIR)


def cleanup_staging(now: float | None = None, keep: str | None = None) -> None:
    """Abgelaufene oder verwaiste Uploads löschen (auch nach einem Neustart)."""
    now = time.monotonic() if now is None else now
    with _PENDING_LOCK:
        for token, entry in list(_PENDING.items()):
            if token != keep and entry["expires"] <= now:
                _PENDING.pop(token, None)
                shutil.rmtree(entry["dir"], ignore_errors=True)
        known = {os.path.basename(e["dir"]) for e in _PENDING.values()} | _ACTIVE
        try:
            names = os.listdir(staging_root())
        except OSError:
            return
        for name in names:
            if name not in known:
                shutil.rmtree(os.path.join(staging_root(), name), ignore_errors=True)


DOWNLOAD_DIR = ".herunterladen"         # unter DATA_DIR: Sicherung für GET /api/backup, danach gelöscht


def download_path() -> str:
    """Pfad für eine Sicherung, die gleich heruntergeladen wird (eigener Ordner, eindeutiger Name)."""
    folder = os.path.join(settings.DATA_DIR, DOWNLOAD_DIR)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    return os.path.join(folder, f"sicherung-{secrets.token_hex(8)}.tar.gz")


def cleanup_downloads(max_age: float = 3600.0) -> None:
    """Reste abgebrochener Downloads (Wanduhr-Alter; nur Dateien dieses Ordners)."""
    folder = os.path.join(settings.DATA_DIR, DOWNLOAD_DIR)
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    now = time.time()
    for entry in entries:
        with contextlib.suppress(OSError):
            if now - entry.stat(follow_symlinks=False).st_mtime > max_age:
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.unlink(entry.path)


def discard(token: str | None = None) -> None:
    with _PENDING_LOCK:
        tokens = [token] if token else list(_PENDING)
        for item in tokens:
            entry = _PENDING.pop(item, None)
            if entry:
                shutil.rmtree(entry["dir"], ignore_errors=True)


class _Limited(io.RawIOBase):
    """Liest höchstens limit Bytes aus dem entpackten Strom – danach Fehler (Gzip-Bombe)."""

    def __init__(self, inner, limit: int) -> None:
        self.inner, self.left = inner, limit

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        want = len(buffer)
        data = self.inner.read(min(want, self.left + 1))
        if len(data) > self.left:
            raise RestoreError("Die Sicherung entpackt sich zu mehr als erlaubt (Schutz vor einer "
                               "„Gzip-Bombe“) – das ist keine Sicherung von ntp-gui.")
        self.left -= len(data)
        buffer[:len(data)] = data
        return len(data)


_META_TYPES = {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK,
               tarfile.SOLARIS_XHDTYPE}


class _SafeTarInfo(tarfile.TarInfo):
    """Lehnt übergroße PAX-/Langname-Köpfe ab, bevor tarfile sie in den Speicher liest."""

    def _proc_member(self, tar):  # noqa: D401 – überschreibt tarfile-Interna (seit Python 2 stabil)
        if self.type in _META_TYPES:
            if self.size > MAX_META_HEADER:
                raise RestoreError("Die Sicherung enthält einen übergroßen Kopfeintrag – abgelehnt.")
            # tarfile liest verkettete Köpfe rekursiv – viele kleine liefen in einen RecursionError.
            count = getattr(tar, "_ntpg_meta", 0) + 1
            tar._ntpg_meta = count
            if count > MAX_META_HEADERS:
                raise RestoreError("Die Sicherung enthält zu viele Kopfeinträge – abgelehnt.")
        return super()._proc_member(tar)


def _show(name: str) -> str:
    text = "".join(c if c.isprintable() else "?" for c in str(name))
    return text if len(text) <= 60 else text[:57] + "…"


def _check_member(member: tarfile.TarInfo, workdir: str, seen: dict) -> None:
    name = member.name
    path = PurePosixPath(name)
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or "\\" in name or ".." in path.parts \
            or "\x00" in name:
        raise RestoreError(f"Die Sicherung enthält einen unzulässigen Pfad („{_show(name)}“) – abgelehnt. "
                           "Erlaubt sind nur die vier bekannten Dateien ohne Ordner.")
    if member.issym() or member.islnk():
        raise RestoreError(f"Die Sicherung enthält einen Link („{_show(name)}“) – abgelehnt.")
    if member.ischr() or member.isblk() or member.isfifo():
        raise RestoreError(f"Die Sicherung enthält eine Gerätedatei („{_show(name)}“) – abgelehnt.")
    if not member.isreg():
        raise RestoreError(f"Die Sicherung enthält etwas anderes als eine Datei („{_show(name)}“) – abgelehnt.")
    if name not in PARTS:
        raise RestoreError(f"Unbekannte Datei „{_show(name)}“ in der Sicherung – abgelehnt. Erwartet: "
                           + ", ".join(PARTS) + ".")
    if name in seen:
        raise RestoreError(f"„{name}“ steht doppelt in der Sicherung – abgelehnt.")
    if member.size > PART_LIMITS[name]:
        raise RestoreError(f"„{name}“ ist zu groß ({member.size // (1024 * 1024)} MiB, erlaubt "
                           f"{PART_LIMITS[name] // (1024 * 1024)} MiB) – abgelehnt.")
    try:
        tarfile.data_filter(member, workdir)  # zweite Meinung: Pfade, Links, Gerätedateien, Rechte
    except tarfile.FilterError as exc:
        raise RestoreError(f"Die Sicherung enthält einen unzulässigen Eintrag („{_show(name)}“: "
                           f"{type(exc).__name__}) – abgelehnt.") from None


def unpack(archive: str, workdir: str) -> dict[str, str]:
    """Prüft das Archiv und schreibt die Teile nach workdir (feste Namen). Gibt {Teil: SHA-256}."""
    hashes: dict[str, str] = {}
    try:
        with open(archive, "rb") as raw:
            gz = gzip.GzipFile(fileobj=raw, mode="rb")
            limited = io.BufferedReader(_Limited(gz, MAX_UNPACKED), CHUNK)
            with tarfile.open(fileobj=limited, mode="r|", tarinfo=_SafeTarInfo) as tar:
                for member in tar:
                    _check_member(member, workdir, hashes)
                    source = tar.extractfile(member)
                    if source is None:
                        raise RestoreError(f"„{member.name}“ lässt sich nicht lesen – abgelehnt.")
                    digest, written = hashlib.sha256(), 0
                    target = os.path.join(workdir, member.name)
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(fd, "wb") as out:
                        for chunk in iter(lambda: source.read(CHUNK), b""):
                            written += len(chunk)
                            if written > PART_LIMITS[member.name]:
                                raise RestoreError(f"„{member.name}“ ist zu groß – abgelehnt.")
                            digest.update(chunk)
                            out.write(chunk)
                    if written != member.size:
                        raise RestoreError(f"„{member.name}“ ist unvollständig – die Datei ist beschädigt.")
                    hashes[member.name] = digest.hexdigest()
    except RestoreError:
        raise
    except (tarfile.TarError, EOFError, OSError, zlib.error, gzip.BadGzipFile, RecursionError, MemoryError,
            ValueError, UnicodeError) as exc:
        raise RestoreError("Das ist keine lesbare Sicherung von ntp-gui (kein gültiges .tar.gz oder "
                           f"beschädigt: {type(exc).__name__}).") from None
    missing = [name for name in PARTS if name not in hashes]
    if missing:
        raise RestoreError("In der Sicherung fehlt " + ", ".join(missing) + " – abgelehnt.")
    return hashes


def _read_json(path: str, what: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        raise RestoreError(f"{what} in der Sicherung ist kein gültiges JSON – abgelehnt.") from None


def check_manifest(manifest: Any, hashes: dict[str, str], workdir: str) -> dict:
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise RestoreError("Die Datei ist keine Sicherung von ntp-gui (manifest.json passt nicht).")
    try:
        fmt = int(manifest.get("format_version"))
        schema = manifest.get("schema") or {}
        dump_schema, settings_schema = int(schema.get("dump")), int(schema.get("settings"))
    except (TypeError, ValueError, AttributeError):
        raise RestoreError("manifest.json ist unvollständig (Versionen fehlen) – abgelehnt.") from None
    if fmt > FORMAT_VERSION or dump_schema > DUMP_SCHEMA or settings_schema > settings.SCHEMA_VERSION:
        origin = manifest.get("ntp_gui_version")
        raise RestoreError("Die Sicherung stammt aus einer neueren Version von ntp-gui"
                           + (f" ({_show(origin)})" if origin else "")
                           + " – bitte zuerst ntp-gui aktualisieren, dann wiederherstellen.")
    if fmt < 1 or dump_schema < 1 or settings_schema < 1:
        raise RestoreError("manifest.json nennt ungültige Versionen – abgelehnt.")
    parts = manifest.get("parts")
    if not isinstance(parts, list):
        raise RestoreError("manifest.json nennt die Teile nicht – abgelehnt.")
    listed = {}
    for item in parts:
        if not isinstance(item, dict) or item.get("name") not in PARTS or item.get("name") == MANIFEST:
            raise RestoreError("manifest.json nennt einen unbekannten Teil – abgelehnt.")
        listed[item["name"]] = item
    if set(listed) != set(PARTS) - {MANIFEST}:
        raise RestoreError("manifest.json passt nicht zu den Dateien der Sicherung – abgelehnt.")
    for name, item in listed.items():
        expected = str(item.get("sha256") or "").lower()
        if not secrets.compare_digest(expected, hashes[name]):
            raise RestoreError(f"Prüfsumme von „{name}“ stimmt nicht – die Datei ist beschädigt oder wurde "
                               "verändert. Abgelehnt.")
        if item.get("size") != os.path.getsize(os.path.join(workdir, name)):
            raise RestoreError(f"Größe von „{name}“ stimmt nicht mit manifest.json überein – abgelehnt.")
    try:
        created = float(manifest.get("created"))
    except (TypeError, ValueError):
        created = float("nan")
    if not math.isfinite(created):
        raise RestoreError("manifest.json nennt keinen gültigen Zeitpunkt – abgelehnt.")
    if created > time.time() + MAX_CREATED_AHEAD:
        raise RestoreError("manifest.json nennt einen Zeitpunkt in der Zukunft – abgelehnt (stimmt die Uhrzeit "
                           "dieses Geräts?).")
    return {"format_version": fmt, "dump": dump_schema, "settings": settings_schema, "created": created,
            "version": str(manifest.get("ntp_gui_version") or "")[:40]}


def _open_dump(path: str, readonly: bool = True) -> sqlite3.Connection:
    with open(path, "rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise RestoreError("daten.sqlite ist keine SQLite-Datenbank – abgelehnt.")
    try:
        conn = sqlite3.connect(_uri(path, "ro" if readonly else "rw"), uri=True, isolation_level=None)
    except sqlite3.Error:
        raise RestoreError("daten.sqlite lässt sich nicht öffnen – abgelehnt.") from None
    with contextlib.suppress(Exception):
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)  # Python ≥ 3.12
    with contextlib.suppress(Exception):
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
    try:
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA cell_size_check=ON")
    except sqlite3.Error:
        conn.close()
        raise RestoreError("daten.sqlite lässt sich nicht öffnen – abgelehnt.") from None
    return conn


def check_dump(path: str, dump_schema: int) -> None:
    """Migriert einen älteren Abzug und prüft: Schema genau wie die Allowlist, Datei unbeschädigt.

    Verglichen wird der CREATE-Text in sqlite_master wörtlich mit create_sql() – so fallen WITHOUT ROWID,
    COLLATE, DEFAULT, CHECK und generierte Spalten auf, die PRAGMA table_info nicht oder nur halb zeigt.
    Eine Migration in DUMP_MIGRATIONS muss die Tabellen darum genau so neu anlegen."""
    if dump_schema < DUMP_SCHEMA:
        conn = _open_dump(path, readonly=False)
        try:
            for target in range(dump_schema + 1, DUMP_SCHEMA + 1):
                step = DUMP_MIGRATIONS.get(target)
                if step is not None:
                    step(conn)
        except sqlite3.Error:
            raise RestoreError("Die ältere Sicherung ließ sich nicht umwandeln – abgelehnt.") from None
        finally:
            conn.close()
    conn = _open_dump(path)
    try:
        _check_dump_schema(conn)
    except sqlite3.Error as exc:
        print(f"[backup] daten.sqlite abgelehnt: {type(exc).__name__}: {exc}", flush=True)
        raise RestoreError("daten.sqlite hat ein unerwartetes Schema oder ist beschädigt – abgelehnt.") from None
    finally:
        conn.close()


def _check_dump_schema(conn: sqlite3.Connection) -> None:
    objects = conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    expected = allowlist_schema()
    for kind, name, _sql in objects:
        if kind != "table" or name not in expected:
            raise RestoreError(f"daten.sqlite enthält mehr als erlaubt ({_show(kind)} „{_show(name)}“) – "
                               "abgelehnt.")
    if {name for _kind, name, _sql in objects} != set(expected):
        raise RestoreError("daten.sqlite hat nicht die erwarteten Tabellen – abgelehnt.")
    for table, columns in expected.items():
        # table_xinfo zeigt auch versteckte und generierte Spalten (hidden ≠ 0).
        found = [(row[1], str(row[2]).upper(), row[3], row[4], row[5], row[6])
                 for row in conn.execute(f'PRAGMA table_xinfo("{table}")')]
        if len(found) != len(columns) or found != [(name, kind, 0, None, 0, 0) for name, kind in columns]:
            raise RestoreError(f"Tabelle „{table}“ in daten.sqlite hat andere Spalten als erwartet – "
                               "abgelehnt.")
    for _kind, name, sql in objects:
        if sql != create_sql(name):
            raise RestoreError(f"Tabelle „{name}“ in daten.sqlite ist anders angelegt als erwartet – abgelehnt.")
    try:
        result = conn.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error:
        result = [("Fehler",)]
    if result != [("ok",)]:
        raise RestoreError("daten.sqlite ist beschädigt (Integritätsprüfung) – abgelehnt.")


def _count(conn: sqlite3.Connection, sql: str, params: Iterable | dict = ()) -> Any:
    try:
        return conn.execute(sql, params if isinstance(params, dict) else tuple(params)).fetchone()[0]
    except sqlite3.Error:
        return None


def _label(key: str) -> str:
    return str(settings.FIELDS.get(key, {}).get("label") or key)


def _settings_plan(data: Any) -> dict:
    """Welche Einstellungen übernommen würden, welche übersprungen werden – und ob danach Neustart."""
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        raise RestoreError("einstellungen.json enthält keine Einstellungen – abgelehnt.")
    try:
        values, notes = settings.migrate_import({"schema": data.get("schema", 1), "values": data["values"]})
    except settings.ValidationError as exc:
        raise RestoreError(str(exc)) from None
    clean, skipped = {}, []
    for key, raw in values.items():
        if key in SECRET_SETTINGS or key not in settings.FIELDS:
            skipped.append({"key": str(key)[:64], "label": _label(str(key)), "why": "unbekannt"})
            continue
        try:
            clean[key] = settings.validate({key: raw})[key]
        except settings.ValidationError as exc:
            skipped.append({"key": key, "label": _label(key), "why": str(exc)[:200]})
    omitted = [k for k in (data.get("omitted") or []) if isinstance(k, str) and k in settings.FIELDS]
    current = settings.export_values().get("values") or {}
    reenter = [{"key": k, "label": _label(k)} for k in sorted(set(omitted) | (SECRET_SETTINGS & set(values)))
               if k not in current]
    kept = [{"key": k, "label": _label(k)} for k in sorted(set(omitted)) if k in current]
    restart = any(settings.FIELDS[k]["restart"] == settings.RESTART_SERVICES and clean.get(k) != current.get(k)
                  for k in set(clean) | {k for k in current if k not in SECRET_SETTINGS})
    return {"values": clean, "skipped": skipped, "reenter": reenter, "kept": kept, "restart": restart,
            "notes": [str(n)[:500] for n in notes], "security": _security_changes(clean, current)}


def _fmt_setting(value: Any) -> str:
    if isinstance(value, bool):
        return "an" if value else "aus"
    if value is None or value == "" or value == []:
        return "leer"
    if isinstance(value, list):
        text = ", ".join(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                         for v in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = "".join(c if c.isprintable() else "?" for c in text)
    return text if len(text) <= 120 else text[:117] + "…"


def _security_changes(clean: dict, current: dict) -> list[dict]:
    """Sicherheitsrelevante Einstellungen, die sich beim Übernehmen ändern (alt → neu)."""
    try:
        effective = settings.values()
    except Exception:
        effective = {}
    out = []
    for key in SECURITY_SETTINGS:
        if key not in settings.FIELDS or (key not in clean and key not in current):
            continue
        before = current.get(key, effective.get(key))
        if key in clean and clean[key] == before:
            continue
        after = _fmt_setting(clean[key]) if key in clean else "Standard bzw. Wert aus der Compose-Datei"
        out.append({"key": key, "label": _label(key), "before": _fmt_setting(before), "after": after})
    return out


_CHANGE_KIND_RE = re.compile(r"^[a-z_]{1,16}$")


def _int_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10 ** 9


def _clean_change(change: Any) -> dict | None:
    """Ein Protokolleintrag der Kalibrierung – nur bekannte Felder mit passendem Typ, sonst None."""
    if not isinstance(change, dict) or not _int_id(change.get("id")):
        return None
    kind = change.get("kind")
    if not isinstance(kind, str) or not _CHANGE_KIND_RE.match(kind):
        return None
    out: dict[str, Any] = {"id": change["id"], "kind": kind}
    for key in ("t", "old_offset", "new_offset"):
        if not _real(change.get(key)):
            return None
        out[key] = change[key]
    for key in ("old_delay", "new_delay", "bias_ms", "step_ms", "rolled_back"):
        if key in change:
            if change[key] is not None and not _real(change[key]):
                return None
            out[key] = change[key]
    for key in ("bound_adopted", "bound_reset", "reload_triggered"):
        if key in change:
            if not isinstance(change[key], bool):
                return None
            out[key] = change[key]
    if "reason" in change:
        if not isinstance(change["reason"], str) or len(change["reason"]) > 2000:
            return None
        out["reason"] = change["reason"]
    if "undoes" in change:
        undoes = change["undoes"]
        if not isinstance(undoes, list) or len(undoes) > autocal_max_log() or not all(map(_int_id, undoes)):
            return None
        out["undoes"] = list(undoes)
    return out


def autocal_max_log() -> int:
    import autocal
    return autocal.MAX_LOG


def _clean_observed(value: Any) -> tuple[Any, bool]:
    if value is None:
        return None, True
    if not isinstance(value, dict) or not _real(value.get("offset")) or not _real(value.get("since")):
        return None, False
    out = {"offset": value["offset"], "since": value["since"]}
    fp = value.get("fp")
    if fp is not None and (not isinstance(fp, str) or len(fp) > 2000):
        return None, False
    out["fp"] = fp
    if "first" in value:
        if not isinstance(value["first"], bool):
            return None, False
        out["first"] = value["first"]
    if "why" in value:
        if value["why"] not in ("device", "relearn"):
            return None, False
        out["why"] = value["why"]
    return out, True


def _clean_pair(value: Any, keys: tuple[str, str], first_int: bool = False) -> tuple[Any, bool]:
    """pending {change_id, t} bzw. last_suggestion {offset, t}."""
    if value is None:
        return None, True
    if not isinstance(value, dict):
        return None, False
    first, second = keys
    ok_first = _int_id(value.get(first)) if first_int else _real(value.get(first))
    if not ok_first or not _real(value.get(second)):
        return None, False
    return {first: value[first], second: value[second]}, True


def _autocal_plan(data: Any) -> dict:
    """kalibrierung.json typgerecht prüfen: Ungültiges fällt weg und steht in der Vorschau (dropped).
    Sonst brächte ein präpariertes Archiv die Kalibrierung dauerhaft zum Absturz (z. B. Text statt Zahl)."""
    import autocal
    if not isinstance(data, dict):
        raise RestoreError("kalibrierung.json ist kein JSON-Objekt – abgelehnt.")
    data = scrub(data)
    state = autocal._empty()
    dropped: list[str] = []
    raw_changes = data.get("changes")
    if raw_changes is not None and not isinstance(raw_changes, list):
        dropped.append("Protokoll der Änderungen (keine Liste)")
        raw_changes = []
    changes = []
    seen: set[int] = set()
    for number, change in enumerate(raw_changes or [], start=1):
        clean = _clean_change(change)
        if clean is None or clean["id"] in seen:
            dropped.append(f"Protokolleintrag {number} (ungültige Werte)")
            continue
        seen.add(clean["id"])
        changes.append(clean)
    state["changes"] = changes[-autocal.MAX_LOG:]
    observed, ok = _clean_observed(data.get("observed"))
    state["observed"] = observed
    if not ok:
        dropped.append("Messstand der automatischen Kalibrierung")
    for key, keys, first_int, what in (("pending", ("change_id", "t"), True, "Offene Prüfung nach einer Änderung"),
                                        ("last_suggestion", ("offset", "t"), False, "Letzter Vorschlag")):
        state[key], ok = _clean_pair(data.get(key), keys, first_int)
        if not ok:
            dropped.append(what)
    for key, what in (("last_tick", "Zeitpunkt der letzten Prüfung"),
                      ("no_fast", "Sperre für die Korrektur in einem Schritt")):
        value = data.get(key)
        if value is not None and not _real(value):
            dropped.append(what)
            value = None
        state[key] = value
    # Die letzte Entscheidung ist nur ein Zwischenstand – sie wird nach dem Übernehmen neu berechnet.
    state["last_decision"] = None
    times = [c["t"] for c in state["changes"]]
    return {"state": state, "last_change": max(times) if times else None, "changes": len(state["changes"]),
            "dropped": dropped}


_CHANNEL_SOURCE = ("id, name, type, enabled, url, url_cut, topic, topic_cut, secret_set, min_level, kinds, "
                   "debounce_min, rate_per_hour, resolved, created, updated")
_CHANNEL_TARGET = ("id, name, type, enabled, url, topic, secret, min_level, kinds, debounce_min, rate_per_hour, "
                   "resolved, created, updated")
_PLACEHOLDER = "platzhalter-wiederherstellen"   # nur für notify.validate, wird nie gespeichert


def _host_of(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        return _show(host + (f":{parts.port}" if parts.port else ""))
    except ValueError:
        return "?"


def _join_and(items: list[str]) -> str:
    return ", ".join(items[:-1]) + (" und " if len(items) > 1 else "") + items[-1] if items else ""


def _same_channel(current: dict | None, kind, url) -> bool:
    """Gilt der Kanal von hier als derselbe wie der aus der Sicherung (gleiche Art, gleiches Ziel)?"""
    import notify
    return bool(current and isinstance(url, str) and current.get("type") == kind
                and notify._origin(str(current.get("url") or "")) == notify._origin(url))


def _channels_plan(rows: list[tuple], existing: dict[str, dict]) -> tuple[list[tuple], list[dict]]:
    """Kanäle aus der Sicherung → (Zeilen für notify_channels, Beschreibung für die Vorschau).

    Jeder Kanal geht durch notify.validate. Gibt es ihn schon (gleiche ID, gleiche Art, gleiches Ziel
    Schema://Host:Port), behält er Token, Thema/Schlüssel und die vollständige Adresse von hier und seinen
    Zustand aus der Sicherung. Alle anderen kommen ausgeschaltet – ein präpariertes Archiv kann so keinen
    aktiven Kanal zu einem fremden Server anlegen."""
    import notify
    out_rows: list[tuple] = []
    items: list[dict] = []
    for row in rows:
        if len(out_rows) >= notify.MAX_CHANNELS:
            break
        (cid, name, kind, enabled, url, url_cut, topic, topic_cut, secret_set, min_level, kinds, debounce_min,
         rate_per_hour, resolved, created, updated) = row
        item = {"name": _show(name), "type": notify.TYPE_LABELS.get(kind, _show(kind)),
                "host": _host_of(url) if isinstance(url, str) else "?", "known": False, "enabled": False,
                "switched_off": False, "reenter": "", "dropped": None}
        items.append(item)
        try:
            parsed = json.loads(kinds) if isinstance(kinds, str) else None
        except ValueError:
            parsed = None
        if not isinstance(cid, str) or not notify._ID_RE.match(cid) or not _real(created) or not _real(updated) \
                or not isinstance(parsed, list) or not isinstance(url, str) or not isinstance(topic, str) \
                or any(r[0] == cid for r in out_rows):
            item["dropped"] = "ungültige Angaben"
            continue
        current = existing.get(cid)
        match = _same_channel(current, kind, url)
        data = {"name": name, "type": kind, "min_level": min_level, "kinds": parsed,
                "debounce_min": debounce_min, "rate_per_hour": rate_per_hour, "resolved": bool(resolved)}
        missing = []
        if match:
            data.update(url=current["url"], topic=current.get("topic") or "", secret=current.get("secret") or "")
        else:
            data.update(url=url, topic=_PLACEHOLDER if topic_cut else topic,
                        secret=_PLACEHOLDER if secret_set else "")
            if secret_set:
                missing.append("Token" if kind != "apprise" else "Apprise-URLs")
            if url_cut:
                missing.append("vollständige Adresse")
            if topic_cut:
                missing.append("Thema" if kind == "ntfy" else "Schlüssel")
        try:
            clean = notify.validate(data)
        except notify.NotifyError as exc:
            item["dropped"] = _show(str(exc))[:200]
            continue
        on = bool(match and isinstance(enabled, int) and enabled)
        item.update(known=match, enabled=on, switched_off=not on, reenter=_join_and(missing))
        topic_out = "" if clean["topic"] == _PLACEHOLDER else clean["topic"]
        secret_out = "" if clean["secret"] == _PLACEHOLDER else clean["secret"]
        out_rows.append((cid, clean["name"], clean["type"], int(on), clean["url"], topic_out, secret_out,
                         clean["min_level"], json.dumps(clean["kinds"]), clean["debounce_min"],
                         clean["rate_per_hour"], int(clean["resolved"]), created, updated))
    return out_rows, items


def _live_channels(conn: sqlite3.Connection | None = None) -> dict[str, dict]:
    sql = "SELECT id, type, url, topic, secret, name FROM notify_channels ORDER BY rowid"
    try:
        rows = conn.execute(sql).fetchall() if conn is not None else store.query(sql)
    except sqlite3.Error:
        return {}
    return {r[0]: {"type": r[1], "url": r[2], "topic": r[3], "secret": r[4], "name": r[5]} for r in rows}


def _removed_channels(kept: list[tuple], existing: dict[str, dict]) -> list[dict]:
    """Kanäle von hier, die beim Übernehmen wegfallen (ihre Kennung steht nicht unter den übernommenen) –
    samt Token, Thema und vollständiger Adresse; auch die automatische Sicherung davor enthält diese nicht."""
    import notify
    ids = {row[0] for row in kept}
    return [{"name": _show(ch.get("name")), "type": notify.TYPE_LABELS.get(ch.get("type"), _show(ch.get("type"))),
             "host": _host_of(ch.get("url")) if isinstance(ch.get("url"), str) else "?",
             "secret": bool(ch.get("secret") or ch.get("topic") or notify.url_hidden(str(ch.get("url") or "")))}
            for cid, ch in existing.items() if cid not in ids]


def _replaced_channels(kept: list[tuple], existing: dict[str, dict]) -> list[dict]:
    """Kanäle von hier, deren Kennung zwar in der Sicherung steht, die dort aber eine andere Art oder einen
    anderen Server haben: Die Fassung aus der Sicherung ersetzt sie, ihr jetziges Ziel und ihr Token gehen
    verloren – auch die automatische Sicherung davor enthält den Token nicht."""
    import notify
    out = []
    for row in kept:
        current = existing.get(row[0])
        if current is None or _same_channel(current, row[2], row[4]):
            continue
        out.append({"name": _show(current.get("name")),
                    "type": notify.TYPE_LABELS.get(current.get("type"), _show(current.get("type"))),
                    "host": _host_of(current.get("url")) if isinstance(current.get("url"), str) else "?",
                    "new_type": notify.TYPE_LABELS.get(row[2], _show(row[2])),
                    "new_host": _host_of(row[4]) if isinstance(row[4], str) else "?",
                    "secret": bool(current.get("secret") or current.get("topic")
                                   or notify.url_hidden(str(current.get("url") or "")))})
    return out


def _history_limits(created: float, now: float | None = None) -> dict[str, float]:
    return {"created": float(created), "latest": (time.time() if now is None else now) + FUTURE_TOL}


_HISTORY_OK = "typeof(t) = 'integer' AND t <= :created AND t <= :latest"


def _summary(workdir: str, info: dict, settings_plan: dict, autocal_plan: dict) -> dict:
    conn = _open_dump(os.path.join(workdir, DB_PART))
    limits = _history_limits(info["created"])
    try:
        first = _count(conn, f"SELECT min(t) FROM (SELECT min(t) AS t FROM samples WHERE {_HISTORY_OK} UNION ALL "
                             f"SELECT min(t) FROM samples_5m WHERE {_HISTORY_OK})", limits)
        last = _count(conn, f"SELECT max(t) FROM (SELECT max(t) AS t FROM samples WHERE {_HISTORY_OK} UNION ALL "
                            f"SELECT max(t) FROM samples_5m WHERE {_HISTORY_OK})", limits)
        usable = {table: _count(conn, f'SELECT count(*) FROM "{table}" WHERE {_HISTORY_OK}', limits) or 0
                  for table in ("samples", "samples_5m")}
        channels = conn.execute(f"SELECT {_CHANNEL_SOURCE} FROM notify_channels ORDER BY rowid").fetchall()
        rows = {table: _count(conn, f'SELECT count(*) FROM "{table}"') or 0 for table in ALLOWLIST}
        named = _count(conn, "SELECT count(*) FROM clientmon_meta WHERE name <> ''") or 0
    finally:
        conn.close()
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (first, last))
    days = round(max(0.0, (last - first) / 86400.0), 1) if numeric else 0.0
    live = _live_channels()
    kept, items = _channels_plan(channels, live)  # Vorschau: liest nur, legt nichts an
    reenter_channels = [{"name": i["name"], "type": i["type"], "what": i["reenter"]}
                        for i in items if i["reenter"] and not i["dropped"]]
    devices = rows["clientmon_clients"]
    # Messpunkte nach dem Zeitpunkt der Sicherung oder in der Zukunft übernimmt apply nicht – die Vorschau
    # zählt nur, was übernommen wird, und nennt den Rest (präpariertes Manifest, falsch gehende Uhr).
    skipped = sum(rows[t] - usable[t] for t in usable)
    return {
        "created": info["created"], "version": info["version"],
        "schema": {"dump": info["dump"], "settings": info["settings"], "migrated":
                   info["dump"] < DUMP_SCHEMA or info["settings"] < settings.SCHEMA_VERSION},
        "history": {"days": days, "first": first if numeric else None, "last": last if numeric else None,
                    "samples": usable["samples"], "rollup": usable["samples_5m"], "skipped": skipped,
                    "warning": (f"{skipped} Messpunkte liegen nach dem Zeitpunkt der Sicherung oder in der "
                                "Zukunft und werden nicht übernommen." if skipped else "")},
        "devices": devices, "names": named, "groups": rows["client_groups"], "rules": rows["client_rules"],
        "client_samples": rows["clientmon_samples"], "events": rows["events"],
        "calibration": {"last_change": autocal_plan["last_change"], "changes": autocal_plan["changes"],
                        "dropped": autocal_plan["dropped"],
                        "gps_offset": settings_plan["values"].get("gps_offset"),
                        "gps_delay": settings_plan["values"].get("gps_delay")},
        "channels": {"count": len([i for i in items if not i["dropped"]]), "items": items,
                     "reenter": reenter_channels, "removed": _removed_channels(kept, live),
                     "replaced": _replaced_channels(kept, live)},
        "settings": {"count": len(settings_plan["values"]), "skipped": settings_plan["skipped"],
                     "reenter": settings_plan["reenter"], "kept": settings_plan["kept"],
                     "restart": settings_plan["restart"], "notes": settings_plan["notes"],
                     "security": settings_plan["security"]},
    }


def stage_upload(stream, length: int) -> dict:
    """Upload lesen (genau length Bytes), prüfen, Vorschau liefern. Bei Fehler: nichts bleibt liegen."""
    if length <= 0:
        raise RestoreError("Keine Datei hochgeladen.")
    if length > MAX_UPLOAD:
        raise RestoreError(f"Die Datei ist zu groß (höchstens {MAX_UPLOAD // (1024 * 1024)} MiB).")
    cleanup_staging()
    discard()  # immer nur ein offener Upload – älterer verfällt
    root = staging_root()
    os.makedirs(root, mode=0o700, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(root, 0o700)
    with _PENDING_LOCK:
        workdir = tempfile.mkdtemp(prefix="upload-", dir=root)
        _ACTIVE.add(os.path.basename(workdir))
    try:
        archive = os.path.join(workdir, "upload.tar.gz")
        left = length
        with open(archive, "wb") as out:
            while left > 0:
                chunk = stream.read(min(CHUNK, left))
                if not chunk:
                    raise RestoreError("Upload unvollständig – bitte noch einmal versuchen.")
                out.write(chunk)
                left -= len(chunk)
        parts = os.path.join(workdir, "teile")
        os.mkdir(parts, 0o700)
        hashes = unpack(archive, parts)
        os.unlink(archive)
        info = check_manifest(_read_json(os.path.join(parts, MANIFEST), "manifest.json"), hashes, parts)
        check_dump(os.path.join(parts, DB_PART), info["dump"])
        settings_plan = _settings_plan(_read_json(os.path.join(parts, SETTINGS_PART), "einstellungen.json"))
        autocal_plan = _autocal_plan(_read_json(os.path.join(parts, AUTOCAL_PART), "kalibrierung.json"))
        preview = _summary(parts, info, settings_plan, autocal_plan)
    except BaseException:
        with _PENDING_LOCK:
            _ACTIVE.discard(os.path.basename(workdir))
            shutil.rmtree(workdir, ignore_errors=True)
        raise
    token = secrets.token_urlsafe(24)
    with _PENDING_LOCK:
        _PENDING[token] = {"dir": workdir, "parts": parts, "expires": time.monotonic() + PENDING_TTL,
                           "info": info, "settings": settings_plan, "autocal": autocal_plan, "preview": preview}
        _ACTIVE.discard(os.path.basename(workdir))
    return {"token": token, "expires_in": int(PENDING_TTL), "preview": preview}


# ---------------------------------------------------------------------------
# Wiederherstellen: übernehmen
# ---------------------------------------------------------------------------

def _valid_meta(row: tuple) -> tuple | None:
    import clientinfo
    ip, name, note, updated = row
    addr = clientinfo.clean_ip(ip)
    if addr is None or not _real(updated):
        return None
    try:
        name, note = clientinfo.clean_name(name), clientinfo.clean_note(note)
    except clientinfo.MetaError:
        return None
    return (addr, name, note, updated) if (name or note) else None


def _valid_group(row: tuple) -> tuple | None:
    import clients3
    group_id, name, network, updated = row
    if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id < 1 or not _real(updated):
        return None
    try:
        return (group_id, clients3.clean_group_name(name), clients3.clean_network(network), updated)
    except clients3.Clients3Error:
        return None


def _valid_rule(row: tuple) -> tuple | None:
    import clientinfo
    ip, silent_h, offset_ms, offset_min, mute, expect, state, updated = row
    addr = clientinfo.clean_ip(ip)
    if addr is None or not _real(updated):
        return None
    if any(v is not None and not _real(v) for v in (silent_h, offset_ms)):
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (offset_min, mute)):
        return None
    if not isinstance(expect, str) or len(expect) > 64 or not re.match(r"^[a-z0-9_-]*$", expect):
        return None
    try:
        parsed = json.loads(state) if isinstance(state, str) else None
    except ValueError:
        parsed = None
    # Derselbe Filter wie beim Erstellen (ntpg_scrub) und dieselbe Grenze wie bei events.data – das Manifest
    # ist nicht signiert. Ein ungültiger oder übergroßer Alarmzustand fängt leer an; die Regel selbst bleibt.
    state = json.dumps(scrub(parsed) if isinstance(parsed, dict) else {}, separators=(",", ":"), ensure_ascii=False)
    if len(state) > 8000:
        state = "{}"
    return (addr, silent_h, offset_ms, offset_min, mute, expect, state, updated)


def _real(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


_NUM = "typeof({0}) IN ('real', 'integer') AND abs({0}) < 1e13"
_NUM_OR_NULL = "({0} IS NULL OR (typeof({0}) IN ('real', 'integer') AND abs({0}) < 1e13))"
_INT_OR_NULL = "typeof({0}) IN ('null', 'integer')"
# Große Tabellen: in SQL kopieren (schnell). Dieselben Filter wie beim Erstellen (ntpg_*: Messpunkt-
# Allowlist, Position/Winkel/Geheimnisse aus JSON und Texten, normalisierte IP-Adressen), dazu Prüfung je
# Zeile in der WHERE-Klausel. Das Manifest ist nicht signiert – wer daten.sqlite verändert und die Prüfsumme
# anpasst, kommt durch die Prüfsummen; die Filter hier gelten trotzdem.
# (Zielspalten, Ausdrücke über bak.<Tabelle>, Bedingung, Spalten, die nicht NULL sein dürfen)
_SQL_COPY = {
    "samples": ("t, json", "t, ntpg_sample(json)", _HISTORY_OK + " AND json_valid(json)", ("json",)),
    "samples_5m": ("b, t, json", "b, t, ntpg_sample(json)",
                   "typeof(b) = 'integer' AND " + _HISTORY_OK + " AND json_valid(json)", ("json",)),
    "events": ("t, kind, level, title, data, source",
               "t, kind, level, ntpg_text(substr(title, 1, 300)), ntpg_scrub(data), source",
               _NUM.format("t") + " AND ntpg_word(kind) AND level IN ('info', 'warn', 'crit') "
               "AND typeof(title) = 'text' AND ntpg_word(source) "
               "AND (data IS NULL OR (json_valid(data) AND length(data) <= 8000))", ("title",)),
    "clientmon_clients": ("ip, data, updated", "ntpg_ip(ip), ntpg_scrub(data), updated",
                          "typeof(ip) = 'text' AND json_valid(data) AND json_type(data) = 'object' AND "
                          + _NUM.format("updated"), ("ip", "data")),
    "clientmon_samples": ("ip, t, offset, poll, version, interval", "ntpg_ip(ip), t, offset, poll, version, interval",
                          "typeof(ip) = 'text' AND " + _NUM.format("t") + " AND " + _NUM_OR_NULL.format("offset")
                          + " AND " + _INT_OR_NULL.format("poll") + " AND " + _INT_OR_NULL.format("version")
                          + " AND " + _NUM_OR_NULL.format("interval"), ("ip",)),
    "client_hourly": ("ip, hour, n, med, p95, lo, hi", "ntpg_ip(ip), hour, n, med, p95, lo, hi",
                      "typeof(ip) = 'text' AND typeof(hour) = 'integer' AND typeof(n) = 'integer' AND "
                      + " AND ".join(_NUM_OR_NULL.format(c) for c in ("med", "p95", "lo", "hi")), ("ip",)),
    "client_inventory": ("key, first_seen", "ntpg_invkey(key), first_seen",
                         "typeof(key) = 'text' AND " + _NUM.format("first_seen"), ("key",)),
}
# Kleine Tabellen: in Python mit den Prüfungen der Module (Namen, Netze, Kanäle).
_PY_COPY = {
    "clientmon_meta": ("ip, name, note, updated", _valid_meta),
    "client_groups": ("id, name, network, updated", _valid_group),
    "client_rules": ("ip, silent_h, offset_ms, offset_min, mute, expect, state, updated", _valid_rule),
}
_PY_SOURCE = {
    "clientmon_meta": "ip, name, note, updated",
    "client_groups": "id, name, network, updated",
    "client_rules": "ip, silent_h, offset_ms, offset_min, mute, expect, state, updated",
}
# Verlauf: Messpunkte nach dem Erstellen der Sicherung (t > created) bleiben stehen – die Sicherung
# kennt sie nicht, und so entsteht keine Lücke (auch nicht für die seit dem Hochladen gespeicherten).
_KEEP_NEWER = ("samples", "samples_5m")
# Reihenfolge: Clients vor ihren Messpunkten (Aufräumen löscht verwaiste Messpunkte).
RESTORE_ORDER = ("samples", "samples_5m", "events", "clientmon_clients", "clientmon_samples", "clientmon_meta",
                 "client_groups", "client_rules", "client_hourly", "client_inventory", "notify_channels")
assert set(RESTORE_ORDER) == set(ALLOWLIST) == set(_SQL_COPY) | set(_PY_COPY) | {"notify_channels"}


def _channel_rows(conn: sqlite3.Connection) -> list[dict]:
    """Alle Zeilen von notify_channels mit allen Spalten (auch secret, topic, vollständige url, enabled)."""
    cur = conn.execute("SELECT * FROM main.notify_channels ORDER BY rowid")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _put_channel_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """notify_channels genau aus festgehaltenen Zeilen füllen (Zurückspielen: Tokens bleiben erhalten)."""
    live = {row[1] for row in conn.execute("PRAGMA main.table_info(notify_channels)")}
    for row in rows:
        cols = [c for c in row if c in live]
        names = ", ".join('"' + c + '"' for c in cols)
        marks = ", ".join("?" * len(cols))
        conn.execute(f'INSERT OR REPLACE INTO main."notify_channels" ({names}) VALUES ({marks})',
                     [row[c] for c in cols])
    return len(rows)


def _detach_leftover(conn: sqlite3.Connection) -> None:
    """Ein von einem früheren Lauf hängen gebliebenes „bak“ abhängen (sonst scheitert jedes ATTACH)."""
    if any(row[1] == "bak" for row in conn.execute("PRAGMA database_list")):
        conn.execute("DETACH DATABASE bak")


def restore_database(dump: str, created: float, after_commit: Callable[[int], None] | None = None,
                     before_commit: Callable[[], Callable[[], None]] | None = None,
                     keep: dict | None = None, channels: list[dict] | None = None) -> dict[str, int]:
    """Ersetzt die Tabellen der Allowlist in der laufenden Datenbank durch die aus dump. Atomar.

    keep: bekommt unter „channels“ die vollständigen Kanalzeilen von vor dem Austausch (in derselben
    Transaktion gelesen) – damit lässt sich der Stand nach einem Fehler samt Tokens zurückspielen.
    channels: statt der Kanäle aus dump genau diese Zeilen einsetzen (Zurückspielen).
    before_commit() läuft in der Transaktion direkt vor dem COMMIT (Dateien einsetzen) und gibt eine
    Rücknahme zurück; scheitert danach noch etwas vor dem COMMIT, wird sie aufgerufen.
    after_commit(max_event_id) läuft direkt nach dem COMMIT noch unter store.lock – bevor irgendein anderer
    Thread den neuen Stand sieht (Benachrichtigungen, laufende Client-Messung). Danach wird die WAL-Datei
    zurückgesetzt: Sie wüchse sonst dauerhaft auf die Größe der Datenbank.

    Jede Ausnahme, nachdem sich etwas geändert hat (nach dem COMMIT oder bei gescheiterter Rücknahme),
    kommt als _AfterCommit – der Aufrufer spielt dann die automatische Sicherung zurück."""
    _ensure_live_tables()
    conn = store.connect()
    counts: dict[str, int] = {}
    params = _history_limits(created)
    with store.lock():
        _register(conn)
        _detach_leftover(conn)
        conn.execute("ATTACH DATABASE ? AS bak", (os.path.abspath(dump),))
        committed = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            undo: Callable[[], None] | None = None
            try:
                existing = _live_channels(conn)
                if keep is not None:
                    keep["channels"] = _channel_rows(conn)
                for table in RESTORE_ORDER:
                    if table in _KEEP_NEWER:
                        conn.execute(f'DELETE FROM main."{table}" WHERE t <= :created', params)
                    else:
                        conn.execute(f'DELETE FROM main."{table}"')
                    if table in _SQL_COPY:
                        target, select, where, not_null = _SQL_COPY[table]
                        names = [c.strip() for c in target.split(",")]
                        inner = ", ".join(f'{expr} AS "{name}"' for expr, name in zip(_split_exprs(select), names))
                        keep_rows = " AND ".join(f'"{c}" IS NOT NULL' for c in not_null) or "1"
                        cur = conn.execute(
                            f'INSERT OR IGNORE INTO main."{table}" ({target}) SELECT {target} FROM '
                            f'(SELECT {inner} FROM bak."{table}" WHERE {where} ORDER BY rowid) WHERE {keep_rows}',
                            params if ":created" in where else ())
                        counts[table] = max(0, cur.rowcount)
                    elif table == "notify_channels":
                        if channels is not None:
                            counts[table] = _put_channel_rows(conn, channels)
                            continue
                        rows = conn.execute(f'SELECT {_CHANNEL_SOURCE} FROM bak."notify_channels" '
                                            'ORDER BY rowid').fetchall()
                        clean, _items = _channels_plan(rows, existing)
                        marks = ", ".join("?" * len(_CHANNEL_TARGET.split(",")))
                        conn.executemany(f'INSERT OR IGNORE INTO main."notify_channels" ({_CHANNEL_TARGET}) '
                                         f'VALUES ({marks})', clean)
                        counts[table] = len(clean)
                    else:
                        target, check = _PY_COPY[table]
                        rows = conn.execute(f'SELECT {_PY_SOURCE[table]} FROM bak."{table}" ORDER BY rowid').fetchall()
                        clean = [r for r in (check(row) for row in rows) if r is not None]
                        marks = ", ".join("?" * len(target.split(",")))
                        conn.executemany(f'INSERT OR IGNORE INTO main."{table}" ({target}) VALUES ({marks})', clean)
                        counts[table] = len(clean)
                max_event = int(conn.execute("SELECT coalesce(max(id), 0) FROM main.events").fetchone()[0])
                if before_commit is not None:
                    undo = before_commit()
                conn.execute("COMMIT")
                committed = True
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                if undo is not None:
                    try:
                        undo()
                    except Exception as exc:
                        raise _AfterCommit() from exc
                raise
            if after_commit is not None:
                after_commit(max_event)
        except _AfterCommit:
            raise
        except Exception as exc:
            if committed:
                raise _AfterCommit() from exc
            raise
        finally:
            try:
                conn.execute("DETACH DATABASE bak")
            except sqlite3.Error as exc:
                # Kein Fehler des Austauschs (der Stand ist vollständig); das nächste ATTACH hängt es ab.
                _log("Sicherung nach dem Wiederherstellen nicht abgehängt", exc)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
    return counts


def _split_exprs(select: str) -> list[str]:
    """„a, f(b, 1), c“ → [a, f(b, 1), c] (Kommas nur außerhalb von Klammern)."""
    out, depth, current = [], 0, ""
    for char in select:
        if char == "," and depth == 0:
            out.append(current.strip())
            current = ""
            continue
        depth += char == "("
        depth -= char == ")"
        current += char
    out.append(current.strip())
    return out


def _on_commit(max_event: int) -> None:
    """Direkt nach dem COMMIT, noch unter store.lock: Alte Ereignisse lösen keine Meldungen aus, und die
    laufende Client-Messung übernimmt die Geräte aus der Datenbank (sonst überschriebe ihr nächstes
    Speichern die wiederhergestellten Zeilen mit dem Stand im Speicher)."""
    try:
        import notify
        notify.NOTIFIER.skip_to(max_event)
    except Exception as exc:  # noqa: BLE001 – nie den Austausch abbrechen
        _log("Benachrichtigungen nicht weitergestellt", exc)
    try:
        import clientmon
        clientmon.reload_from_store()
    except Exception as exc:  # noqa: BLE001
        _log("Client-Messung nicht neu geladen", exc)


def _log(what: str, exc: BaseException) -> None:
    print(f"[backup] {what}: {type(exc).__name__}: {exc}", flush=True)


def _after_restore() -> None:
    """Zwischenspeicher der Module verwerfen, Kanäle neu laden."""
    with contextlib.suppress(Exception):
        import clientinfo
        clientinfo._META_CACHE.update(t=0.0, data=None)
    with contextlib.suppress(Exception):
        import clients3
        clients3._drop_group_cache()
        clients3._drop_rule_cache()
        clients3._QUALITY_CACHE.update(t=None, data=None)
        clients3._forget_names()
        clients3.INVENTORY.reset()
    with contextlib.suppress(Exception):
        import notify
        notify.NOTIFIER.reload()
    with contextlib.suppress(Exception):
        import timeline
        timeline.invalidate_report()  # sonst bliebe der Tagesbericht von vor dem Einspielen bis Mitternacht


class _AfterCommit(Exception):
    """Es hat sich schon etwas geändert (Datenbank ausgetauscht oder Dateien eingesetzt), danach ging etwas
    schief – der vorherige Stand muss aus der automatischen Sicherung zurückgespielt werden."""


def _autocal_tmp() -> str:
    return os.path.join(settings.DATA_DIR, ".autocal-wiederherstellen.json")


def _keep_old(dest: str) -> str | None:
    """Kopie der jetzigen Datei neben ihr (für die Rücknahme); None, wenn es sie nicht gibt."""
    if not os.path.exists(dest):
        return None
    fd, copy = tempfile.mkstemp(dir=os.path.dirname(dest) or ".", prefix=".alt-wiederherstellen-")
    os.close(fd)
    try:
        shutil.copy2(dest, copy)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(copy)
        raise
    return copy


class _FileSwap:
    """Kalibrierung und Einstellungen einsetzen – noch in der Datenbank-Transaktion, vor dem COMMIT. Scheitert
    das (oder danach das COMMIT), setzt undo() die alten Dateien zurück: Kein Fehler beim Einsetzen der
    Dateien führt so mehr zu einem Stand nach dem COMMIT, der zurückgespielt werden müsste."""

    def __init__(self, cal_tmp: str, staged: dict) -> None:
        self.cal_tmp, self.staged = cal_tmp, staged
        self.done: list[tuple[str, str | None]] = []   # (Ziel, Kopie des alten Stands)
        self.copies: list[str] = []
        self.result: dict = {}

    def __call__(self) -> Callable[[], None]:
        import autocal
        try:
            for dest, install in ((autocal.path(), self._autocal), (settings.SETTINGS_FILE, self._settings)):
                old = _keep_old(dest)
                if old:
                    self.copies.append(old)
                install()
                self.done.append((dest, old))
        except BaseException:
            try:
                self.undo()
            except Exception as exc:
                raise _AfterCommit() from exc
            raise
        return self.undo

    def _autocal(self) -> None:
        import autocal
        with autocal._LOCK:
            os.replace(self.cal_tmp, autocal.path())

    def _settings(self) -> None:
        self.result = settings.commit_replace(self.staged)

    def undo(self) -> None:
        import autocal
        while self.done:
            dest, old = self.done.pop()
            lock = autocal._LOCK if dest == autocal.path() else contextlib.nullcontext()
            with lock:
                if old is None:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(dest)
                elif dest == settings.SETTINGS_FILE:
                    settings.commit_replace({"tmp": old})
                else:
                    os.replace(old, dest)

    def cleanup(self) -> None:
        for copy in self.copies:
            with contextlib.suppress(OSError):
                os.unlink(copy)


def _install(parts: str, created: float, settings_plan: dict, autocal_state: dict, keep: dict | None = None,
             channels: list[dict] | None = None) -> tuple[dict, dict]:
    """Alles oder nichts: Einstellungen und Kalibrierung zuerst als geprüfte temporäre Dateien schreiben,
    dann in EINER Datenbank-Transaktion die Tabellen tauschen und direkt vor dem COMMIT die Dateien per
    os.replace einsetzen (bei einem Fehler davor oder beim COMMIT kommen die alten Dateien zurück).
    Jeder Fehler vor dem COMMIT lässt alles, wie es war; ein Fehler danach wirft _AfterCommit."""
    import autocal
    staged = settings.stage_replace(settings_plan["values"], keep=SECRET_SETTINGS)
    cal_tmp = _autocal_tmp()
    swap = _FileSwap(cal_tmp, staged)
    try:
        autocal.save(autocal_state, cal_tmp)
        # Sperren in derselben Reihenfolge wie autocal.tick (autocal._LOCK, darin store.lock über events.emit):
        # _FileSwap setzt autocal.json unter store.lock ein – ohne die äußere Sperre hier drohte ein Deadlock.
        with autocal._LOCK:
            counts = restore_database(os.path.join(parts, DB_PART), created, _on_commit, before_commit=swap,
                                      keep=keep, channels=channels)
    finally:
        settings.discard_staged(staged)
        with contextlib.suppress(OSError):
            os.unlink(cal_tmp)
        swap.cleanup()
    return counts, swap.result


def _channels_now() -> list[dict] | None:
    try:
        with store.lock():
            return _channel_rows(store.connect())
    except sqlite3.Error:
        return None


def _rollback(before: str, channels: list[dict] | None) -> bool:
    """Den eben automatisch gesicherten Stand zurückspielen (nach einem Fehler nach dem COMMIT). Die Kanäle
    kommen aus den vor dem Austausch festgehaltenen Zeilen (mit Tokens, Themen, Adressen, Ein/Aus) – die
    automatische Sicherung enthält keine Geheimnisse. Gibt zurück, ob die Kanäle danach genau wie vorher sind."""
    path = stored_path(before)
    if path is None:
        raise RestoreError("automatische Sicherung fehlt")
    os.makedirs(staging_root(), mode=0o700, exist_ok=True)
    with _PENDING_LOCK:
        workdir = tempfile.mkdtemp(prefix="zurueck-", dir=staging_root())
        _ACTIVE.add(os.path.basename(workdir))
    try:
        hashes = unpack(path, workdir)
        info = check_manifest(_read_json(os.path.join(workdir, MANIFEST), "manifest.json"), hashes, workdir)
        check_dump(os.path.join(workdir, DB_PART), info["dump"])
        plan = _settings_plan(_read_json(os.path.join(workdir, SETTINGS_PART), "einstellungen.json"))
        cal = _autocal_plan(_read_json(os.path.join(workdir, AUTOCAL_PART), "kalibrierung.json"))
        _install(workdir, info["created"], plan, cal["state"], channels=channels)
    finally:
        with _PENDING_LOCK:
            _ACTIVE.discard(os.path.basename(workdir))
            shutil.rmtree(workdir, ignore_errors=True)
        _after_restore()
    return channels is not None and _channels_now() == channels


def apply(token: Any, version: str = "", emit: Callable | None = None) -> dict:
    """Übernimmt eine geprüfte Sicherung. Vorher: Sicherung des jetzigen Stands ins Datenverzeichnis.
    Fehlertexte für die Oberfläche sind fest formuliert; Einzelheiten stehen nur im Log."""
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        raise RestoreError("Keine gültige Vorschau – bitte die Sicherung noch einmal auswählen.")
    with _APPLY_LOCK:
        cleanup_staging()
        with _PENDING_LOCK:
            entry = _PENDING.pop(token, None)
            if entry is not None:
                _ACTIVE.add(os.path.basename(entry["dir"]))
        if entry is None:
            raise RestoreError("Die Vorschau ist abgelaufen oder wurde schon übernommen – bitte die Sicherung "
                               "noch einmal auswählen.")
        plan = entry["settings"]
        created = entry["info"]["created"]
        try:
            try:
                before = save_local(AUTO_PREFIX, KEEP_AUTO, version)
            except Exception as exc:
                _log("Sicherung vor dem Wiederherstellen fehlgeschlagen", exc)
                raise RestoreError("Der jetzige Stand ließ sich nicht sichern (Details im Log) – darum wurde "
                                   "nichts überschrieben.") from None
            keep: dict = {}
            try:
                counts, result = _install(entry["parts"], created, plan, entry["autocal"]["state"], keep=keep)
            except _AfterCommit as exc:
                _log("Fehler nach dem Austausch der Datenbank", exc.__cause__ or exc)
                try:
                    same = _rollback(before, keep.get("channels"))
                except Exception as again:  # noqa: BLE001
                    _log("Zurückspielen der automatischen Sicherung fehlgeschlagen", again)
                    raise RestoreError(
                        "Die Sicherung ließ sich nur teilweise übernehmen, und der vorherige Stand ließ sich nicht "
                        f"automatisch zurückspielen. Er liegt als „{before}“ im Ordner „sicherungen“ – lade ihn "
                        "unter „Gespeicherte Sicherungen“ herunter und spiele ihn wieder ein. Details im Log.") from None
                if not same:
                    raise RestoreError(
                        "Die Sicherung ließ sich nicht vollständig übernehmen (Details im Log). Der vorherige Stand "
                        "wurde aus der automatischen Sicherung zurückgespielt, die Benachrichtigungskanäle aber "
                        "nicht vollständig – bitte dort Tokens, Themen und Adressen prüfen.") from None
                raise RestoreError("Die Sicherung ließ sich nicht vollständig übernehmen (Details im Log). Der "
                                   "vorherige Stand wurde aus der automatischen Sicherung zurückgespielt – es gilt "
                                   "alles wie vorher.") from None
            except RestoreError:
                raise
            except Exception as exc:
                _log("Wiederherstellen fehlgeschlagen, nichts geändert", exc)
                raise RestoreError("Die Sicherung ließ sich nicht übernehmen (Details im Log) – nichts wurde "
                                   f"geändert, der bisherige Stand gilt weiter (zusätzlich gesichert als {before}).") \
                    from None
        finally:
            with _PENDING_LOCK:
                _ACTIVE.discard(os.path.basename(entry["dir"]))
                shutil.rmtree(entry["dir"], ignore_errors=True)
            _after_restore()
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(created))
        if emit is not None:
            emit("settings", "info", f"Wiederhergestellt aus Sicherung vom {when}",
                 {"created": created, "rows": counts, "before": before,
                  "settings_changed": len(result.get("changed") or []), "restart": bool(result.get("restart"))})
        preview = entry["preview"]
        reenter = [f"Einstellung „{item['label']}“" for item in plan["reenter"]]
        reenter += [f"Kanal „{item['name']}“: {item['what']}" for item in preview["channels"]["reenter"]]
        return {"ok": True, "created": created, "rows": counts, "before": before,
                "changed": result.get("changed") or [], "restart": bool(result.get("restart")),
                "reenter": reenter, "notes": plan["notes"]}
