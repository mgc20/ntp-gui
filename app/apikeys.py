"""API-Schlüssel für Skripte, Home Assistant, Prometheus & Co.

Ein Schlüssel hat einen Namen und ein Recht:

  read   – GET auf /api/* und /metrics (Werte lesen, nichts ändern)
  admin  – zusätzlich POST (Einstellungen ändern, Dienste neu laden)

Format: "ntpg_" + 32 URL-sichere Zeichen. Die ersten 8 Zeichen nach dem
Präfix sind die öffentliche Kennung (id, steht in der Liste), die übrigen 24
(144 Bit Zufall) das Geheimnis. Gespeichert wird nur ein SHA-256-Hash des
ganzen Schlüssels ("sha256$<hex>"). Ein langsames Verfahren wie PBKDF2 ist
hier unnötig – bei 144 Bit Zufall hilft Durchprobieren nicht – und wäre eine
Einladung, die CPU mit erfundenen Schlüsseln auszulasten (jede Anfrage mit
"ntpg_…" würde ohne Anmeldung 200 000 PBKDF2-Runden kosten).

Ältere Einträge (1.3-Vorabversionen) tragen noch einen PBKDF2-Hash. Sie
werden weiter geprüft und beim nächsten erfolgreichen Gebrauch auf SHA-256
umgestellt.

verify() merkt sich geprüfte Schlüssel kurz im Speicher – nur als HMAC mit
einem Zufallswert dieses Prozesses, nie im Klartext. revoke() leert den
Merker sofort; ein Generationszähler verhindert, dass eine gerade laufende
Prüfung den widerrufenen Schlüssel danach wieder hineinschreibt.
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

HASH_SCHEME = "sha256"

_LOCK = threading.Lock()
_CACHE: dict[bytes, tuple[float, dict | None]] = {}
_GENERATION = [0]  # erhöht bei jedem clear_cache()
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
        _GENERATION[0] += 1


def hash_token(token: str) -> str:
    """Gespeicherte Form eines Schlüssels: "sha256$<64 Hex-Zeichen>"."""
    return f"{HASH_SCHEME}${hashlib.sha256(token.encode('utf-8')).hexdigest()}"


def _token_matches(token: str, encoded: str) -> tuple[bool, bool]:
    """(passt, sollte neu gehasht werden)."""
    encoded = str(encoded or "")
    if encoded.startswith(HASH_SCHEME + "$"):
        return hmac.compare_digest(hash_token(token).encode(), encoded.encode()), False
    if encoded.startswith("pbkdf2_sha256$"):
        return settings.verify_password(token, encoded), True
    return False, False


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
                     (key_id, name, scope, hash_token(token), time.time()))
    _event("API-Schlüssel angelegt", key_id, scope)
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
    rows = store.query("SELECT scope FROM api_keys WHERE id=?", (str(key_id),))
    removed = store.execute("DELETE FROM api_keys WHERE id=?", (str(key_id),)) > 0
    clear_cache()
    if removed and rows:
        _event("API-Schlüssel widerrufen", str(key_id), rows[0][0])
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
            generation = _GENERATION[0]
        if cached and cached[0] > now:
            result = cached[1]
        else:
            result = _verify_slow(match.group(1), token)
            with _LOCK:
                # Nur merken, wenn inzwischen kein revoke()/clear_cache() lief –
                # sonst wäre ein gerade widerrufener Schlüssel noch 60 s gültig.
                if _GENERATION[0] == generation:
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
        # Gleicher (billiger) Vergleich wie bei einem existierenden Schlüssel.
        if _READY.get("dummy") is None:
            _READY["dummy"] = hash_token(PREFIX + secrets.token_urlsafe(24))
        _token_matches(token, _READY["dummy"])
        return None
    ident, name, scope, encoded = rows[0]
    ok, rehash = _token_matches(token, encoded)
    if not ok or scope not in SCOPES:
        return None
    if rehash:
        try:  # Altbestand (PBKDF2) → SHA-256, nur wenn der Eintrag unverändert ist
            store.execute("UPDATE api_keys SET hash=? WHERE id=? AND hash=?",
                          (hash_token(token), ident, encoded))
        except Exception:
            pass
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


def _event(title: str, key_id: str, scope: str) -> None:
    # Nur die Kennung – der frei gewählte Name („HA Familie Schmidt, Lindenweg 7“)
    # hat im Ereignisprotokoll (und damit im Diagnosepaket) nichts verloren.
    try:
        import events
        events.emit("settings", "info", f"{title}: {key_id}",
                    {"id": key_id, "scope": scope}, source="web")
    except Exception:
        pass
