"""API-Schlüssel für Skripte, Home Assistant, Prometheus & Co.

Ein Schlüssel hat einen Namen und ein Recht:

  read   – GET auf /api/* und /metrics (Werte lesen, nichts ändern)
  admin  – zusätzlich POST (Einstellungen ändern, Dienste neu laden)

Format: "ntpg_" + 32 URL-sichere Zeichen. Die ersten 8 Zeichen nach dem
Präfix sind die öffentliche Kennung (id, steht in der Liste), die übrigen 24
(144 Bit Zufall) das Geheimnis. Gespeichert wird nur ein gesalzener
PBKDF2-Hash des ganzen Schlüssels – wie beim Passwort. Den Klartext gibt es
genau einmal, bei create().

Weil PBKDF2 auf einem Pi spürbar Zeit kostet, merkt sich verify() geprüfte
Schlüssel kurz im Speicher – nur als HMAC mit einem Zufallswert dieses
Prozesses, nie im Klartext. revoke() leert den Merker sofort.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from typing import Any

import settings
import store

PREFIX = "ntpg_"
SCOPES = ("read", "admin")
SCOPE_LABELS = {"read": "nur lesen", "admin": "lesen und verwalten"}
MAX_KEYS = 50
CACHE_SECONDS = 60.0
LAST_USED_EVERY = 60.0  # last_used höchstens einmal pro Minute schreiben (SD-Karte)

_TOKEN_RE = re.compile(r"^ntpg_([A-Za-z0-9_-]{8})([A-Za-z0-9_-]{24})$")
_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,64}$")

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        scope TEXT NOT NULL,
        hash TEXT NOT NULL,
        created REAL NOT NULL,
        last_used REAL
    )
    """,
]

_LOCK = threading.Lock()
_CACHE: dict[bytes, tuple[float, dict | None]] = {}
_CACHE_KEY = secrets.token_bytes(32)
_LAST_WRITE: dict[str, float] = {}
_READY: dict[str, Any] = {"db": None}


def _ensure() -> None:
    db = store.path()
    if _READY["db"] != db:
        store.migrate("apikeys", _SCHEMA)
        _READY["db"] = db
        clear_cache()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _validate(name: Any, scope: Any) -> tuple[str, str]:
    name = " ".join(str(name if name is not None else "").split())
    if not _NAME_RE.match(name):
        raise settings.ValidationError("Name: 1–64 Zeichen, ohne Steuerzeichen")
    scope = str(scope or "").strip()
    if scope not in SCOPES:
        raise settings.ValidationError("Recht: „read“ (nur lesen) oder „admin“ (lesen und verwalten)")
    return name, scope


def create(name: str, scope: str) -> tuple[str, str]:
    """Legt einen Schlüssel an. Gibt (id, Klartext-Schlüssel) zurück – nur dieses eine Mal."""
    name, scope = _validate(name, scope)
    _ensure()
    with store.transaction() as conn:
        count = conn.execute("SELECT count(*) FROM api_keys").fetchone()[0]
        if count >= MAX_KEYS:
            raise settings.ValidationError(f"Höchstens {MAX_KEYS} Schlüssel – bitte alte widerrufen")
        while True:
            body = secrets.token_urlsafe(24)  # 32 Zeichen
            key_id, token = body[:8], PREFIX + body
            if not conn.execute("SELECT 1 FROM api_keys WHERE id=?", (key_id,)).fetchone():
                break
        conn.execute("INSERT INTO api_keys(id, name, scope, hash, created) VALUES(?, ?, ?, ?, ?)",
                     (key_id, name, scope, settings.hash_password(token), time.time()))
    _event("API-Schlüssel angelegt", key_id, name, scope)
    return key_id, token


def list() -> list[dict]:  # noqa: A001 – Name laut Schnittstelle
    """Alle Schlüssel ohne Geheimnisse: id, name, scope, created, last_used."""
    _ensure()
    rows = store.query("SELECT id, name, scope, created, last_used FROM api_keys ORDER BY created")
    return [{"id": i, "name": n, "scope": s, "scope_label": SCOPE_LABELS.get(s, s),
             "created": c, "last_used": u} for i, n, s, c, u in rows]


def revoke(key_id: str) -> bool:
    """Widerruft (löscht) einen Schlüssel. True, wenn es ihn gab."""
    _ensure()
    rows = store.query("SELECT name, scope FROM api_keys WHERE id=?", (str(key_id),))
    removed = store.execute("DELETE FROM api_keys WHERE id=?", (str(key_id),)) > 0
    clear_cache()
    if removed and rows:
        _event("API-Schlüssel widerrufen", str(key_id), rows[0][0], rows[0][1])
    return removed


def verify(token: str) -> dict | None:
    """Prüft einen Schlüssel. {"id","name","scope"} oder None. Wirft nie."""
    try:
        if not isinstance(token, str):
            return None
        token = token.strip()
        match = _TOKEN_RE.match(token)
        if not match:
            return None
        digest = hmac.new(_CACHE_KEY, token.encode(), hashlib.sha256).digest()
        now = time.monotonic()
        with _LOCK:
            cached = _CACHE.get(digest)
        if cached and cached[0] > now:
            result = cached[1]
        else:
            result = _verify_slow(match.group(1), token)
            with _LOCK:
                if len(_CACHE) > 1000:
                    _CACHE.clear()
                _CACHE[digest] = (now + CACHE_SECONDS, result)
        if result:
            _touch(result["id"])
            return dict(result)
        return None
    except Exception:
        return None


def _verify_slow(key_id: str, token: str) -> dict | None:
    _ensure()
    rows = store.query("SELECT id, name, scope, hash FROM api_keys WHERE id=?", (key_id,))
    if not rows:
        # Gleiche Rechenzeit wie bei einem existierenden Schlüssel.
        if _READY.get("dummy") is None:
            _READY["dummy"] = settings.hash_password(secrets.token_urlsafe(16))
        settings.verify_password(token, _READY["dummy"])
        return None
    ident, name, scope, encoded = rows[0]
    if not settings.verify_password(token, encoded) or scope not in SCOPES:
        return None
    return {"id": ident, "name": name, "scope": scope}


def _touch(key_id: str) -> None:
    now = time.time()
    with _LOCK:
        if now - _LAST_WRITE.get(key_id, 0.0) < LAST_USED_EVERY:
            return
        _LAST_WRITE[key_id] = now
    try:
        store.execute("UPDATE api_keys SET last_used=? WHERE id=?", (now, key_id))
    except Exception:
        pass


def allows(scope: str, method: str) -> bool:
    """Darf ein Schlüssel mit diesem Recht die HTTP-Methode nutzen?"""
    method = str(method or "").upper()
    if method in {"GET", "HEAD"}:
        return scope in SCOPES
    return scope == "admin"


def _event(title: str, key_id: str, name: str, scope: str) -> None:
    try:
        import events
        events.emit("settings", "info", f"{title}: {name}",
                    {"id": key_id, "scope": scope}, source="web")
    except Exception:
        pass
