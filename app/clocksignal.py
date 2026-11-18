"""On-Air/REC-Signal der Vollbild-Uhr (/clock) – Zustand, Prüfung der Anfrage, Rate-Limit.

Ein einziger Zustand aus einer festen Liste (STATES), wahlweise mit Ablaufzeit (ttl in Sekunden): Danach steht er
wieder auf „off“. Gesetzt wird er über POST /api/v1/clock/signal (server.py: Anmeldung mit Pflicht-Kopf oder
API-Schlüssel mit dem Recht „clock“), gelesen über /api/v1/time als „signal“ und „signal_rev“. Bildschirme mit
signal=1 fragen im Sekundentakt ab und zeigen einen Rahmen mit Text – eine gespiegelte Anzeige, kein Tally.

Der Zustand steht nur im Speicher dieses Prozesses: nicht in den Einstellungen, nicht in der Sicherung; nach einem
Neustart ist er „off“. Öffentlich lesbar sind nur der Zustand (fester Wert) und signal_rev, eine Kennung ohne Inhalt,
die sich mit jedem Wechsel ändert (auch wenn nur die
Ablaufzeit neu gesetzt wird).

Nur Standardbibliothek, ohne Seiteneffekte beim Import.
"""

from __future__ import annotations

import collections
import hashlib
import secrets
import threading
import time
from typing import Any, Callable

STATES = ("off", "on_air", "rec")
TTL_MAX = 86400            # s – längste Ablaufzeit (ein Tag)
RATE_PER_SECOND = 10       # Anfragen je Sekunde und Schlüssel bzw. Anmeldung
RATE_BUCKETS_MAX = 200     # so viele Zähler höchstens (mehr Schlüssel gibt es nicht)
FIELDS = ("state", "ttl")


class SignalError(ValueError):
    """Ungültige Anfrage – server.py antwortet mit 400."""


def parse(data: Any) -> tuple[str, int | None]:
    """Body von POST /api/v1/clock/signal prüfen: {"state": "on_air"|"rec"|"off", "ttl": Sekunden (optional)}."""
    if not isinstance(data, dict):
        raise SignalError("JSON-Objekt erwartet")
    extra = sorted(str(key) for key in data if key not in FIELDS)
    if extra:
        raise SignalError(f"unbekanntes Feld „{extra[0][:32]}“ – erlaubt sind state und ttl")
    state = data.get("state")
    if not isinstance(state, str) or state not in STATES:
        raise SignalError("state muss „on_air“, „rec“ oder „off“ sein")
    ttl = data.get("ttl")
    if ttl is None:
        return state, None
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= TTL_MAX:
        raise SignalError(f"ttl: ganze Sekunden von 1 bis {TTL_MAX}")
    return state, (None if state == "off" else ttl)


class Signal:
    """Der Zustand. Alle Methoden sind threadsicher; clock ist eine monotone Uhr (Tests setzen eine eigene)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "off"
        self._expires: float | None = None
        self._by: Any = None                    # wer die laufende Ablaufzeit gesetzt hat (nur für das Protokoll)
        self._count = 0
        self._nonce = secrets.token_bytes(16)   # je Prozess neu: Nach einem Neustart ändert sich signal_rev sicher
        self._rev = self._make_rev()

    def _make_rev(self) -> str:
        return hashlib.sha256(self._nonce + str(self._count).encode()).hexdigest()[:12]

    def _change(self, state: str, expires: float | None, by: Any = None) -> None:
        self._state, self._expires = state, expires
        self._by = by if expires is not None else None
        self._count += 1
        self._rev = self._make_rev()

    def _expire(self, now: float) -> tuple[bool, Any]:
        if self._expires is not None and now >= self._expires:
            by = self._by
            self._change("off", None)
            return True, by
        return False, None

    def read(self) -> dict:
        """{"signal", "signal_rev", "expired", "expired_by"} – expired: Die Ablaufzeit hat gerade eben auf „off“
        gestellt; expired_by: das by, mit dem diese Ablaufzeit gesetzt wurde."""
        with self._lock:
            expired, by = self._expire(self._clock())
            return {"signal": self._state, "signal_rev": self._rev, "expired": expired, "expired_by": by}

    def set(self, state: str, ttl: int | None = None, by: Any = None) -> dict:
        """Zustand setzen. {"signal", "signal_rev", "expires_in", "changed", "ttl_changed", "expired", "expired_by"} –
        changed: anderer Zustand als vorher; ttl_changed: derselbe Zustand, aber eine andere Ablaufzeit (neu gesetzt,
        verlängert, verkürzt oder aufgehoben); expired: Die Ablaufzeit war schon um und hat unmittelbar vor diesem
        Setzen auf „off“ gestellt (das hat noch niemand gemeldet bekommen – der Aufrufer trägt es ins Protokoll ein).
        by: beliebige Angabe, wer setzt; sie wird mit der Ablaufzeit gemerkt und kommt beim Ablauf als expired_by
        zurück – nach außen (read über /api/v1/time) gibt server.py sie nie weiter."""
        if state not in STATES:
            raise SignalError("unzulässiger Zustand")
        with self._lock:
            now = self._clock()
            expired, expired_by = self._expire(now)
            expires = now + ttl if ttl and state != "off" else None
            changed = state != self._state
            ttl_changed = not changed and expires != self._expires
            if changed or ttl_changed:
                self._change(state, expires, by)   # derselbe Zustand mit neuer Ablaufzeit: neuer Stand, kein Wechsel
            return {"signal": self._state, "signal_rev": self._rev,
                    "expires_in": ttl if expires is not None else None, "changed": changed,
                    "ttl_changed": ttl_changed, "expired": expired, "expired_by": expired_by}


class RateLimit:
    """Höchstens rate Anfragen je Sekunde und Kennung: gleitendes Fenster über die Zeitpunkte der angenommenen
    Anfragen – in keiner Sekunde, wo immer sie beginnt, kommen mehr als rate durch."""

    WINDOW = 1.0   # s

    def __init__(self, rate: int = RATE_PER_SECOND, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate = rate
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, collections.deque] = {}

    def allow(self, ident: str) -> bool:
        with self._lock:
            now = self._clock()
            seen = self._buckets.get(ident)
            if seen is None:
                if len(self._buckets) >= RATE_BUCKETS_MAX:
                    self._buckets.clear()
                seen = self._buckets[ident] = collections.deque()
            while seen and now - seen[0] >= self.WINDOW:
                seen.popleft()
            if len(seen) >= self.rate:
                return False
            seen.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
