"""Bremse für Anmeldeversuche (Benutzer/Passwort): je Quelladresse, gesamt und für die CPU.

Jede Passwortprüfung kostet Rechenzeit (PBKDF2). Ohne Bremse ließe sich ein Passwort beliebig schnell
durchprobieren, und viele gleichzeitige Fehlversuche lasten die CPU aus. Darum:

- Je Quelle (IPv4-Adresse bzw. IPv6-/64-Netz) sind FREE_FAILURES Fehlversuche frei. Danach muss die
  Quelle warten: 2 s, 4 s, 8 s … höchstens MAX_BLOCK. Eine Anmeldung von dort wird in dieser Zeit gar
  nicht erst geprüft (Antwort 429 mit Retry-After). Nach WINDOW ohne neuen Fehlversuch ist alles vergessen.
- Gesamt: Mehr als GLOBAL_LIMIT Fehlversuche in GLOBAL_WINDOW aus allen Quellen zusammen bremsen alle
  ungeprüften Anmeldungen für GLOBAL_BLOCK – außer aus Quellen, von denen in den letzten 24 h eine
  Anmeldung gelang. Ein schon geprüfter, gültiger Zugang (Merker in server.AUTH_CACHE) ist nie betroffen.
- Höchstens CONCURRENT Passwortprüfungen laufen gleichzeitig (Semaphore).
- Ein gerade abgelehnter, identischer Anmeldekopf wird NEGATIVE_SECONDS lang ohne neue Prüfung abgelehnt.

Die Quelladresse kommt aus webtransport.resolve(): Proxy-Köpfe zählen nur von TRUSTED_PROXIES.

Fehlversuche landen gedrosselt im Ereignisprotokoll (Art „access“, ohne Adresse) und im Server-Log (mit
Adresse – dort kann z. B. fail2ban sie auswerten).
"""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from collections import deque
from contextlib import contextmanager

FREE_FAILURES = 5
WINDOW = 600.0
MAX_BLOCK = 900.0
GLOBAL_LIMIT = 30
GLOBAL_WINDOW = 60.0
GLOBAL_BLOCK = 60.0
KNOWN_GOOD_SECONDS = 24 * 3600.0
CONCURRENT = 2
SLOT_WAIT = 5.0
NEGATIVE_SECONDS = 10.0
EVENT_EVERY = 60.0
MAX_SOURCES = 4096


def source_key(address: str) -> str:
    """Zählschlüssel einer Adresse: IPv4 einzeln, IPv6 je /64 (ein Anschluss hat meist ein ganzes /64)."""
    text = str(address or "").strip()
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return text[:64] or "?"
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class Guard:
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(CONCURRENT)
        self._sources: dict[str, dict] = {}       # Schlüssel → {"count", "last", "until"}
        self._recent: deque = deque()             # Zeitpunkte der Fehlversuche (gesamt)
        self._global_until = 0.0
        self._known_good: dict[str, float] = {}   # Schlüssel → gültig bis
        self._negative: dict[str, float] = {}     # Hash des Anmeldekopfs → abgelehnt bis
        self._last_event = -1e18
        self._pending_events = 0

    # --- Abfragen ----------------------------------------------------------
    def retry_after(self, key: str) -> float:
        """Sekunden, die diese Quelle noch warten muss (0 = darf prüfen lassen)."""
        now = self.clock()
        with self._lock:
            entry = self._sources.get(key)
            wait = max(0.0, (entry or {}).get("until", 0.0) - now)
            if self._global_until > now and self._known_good.get(key, 0.0) <= now:
                wait = max(wait, self._global_until - now)
        return wait

    def is_negative(self, header: str) -> bool:
        digest = hashlib.sha256(header.encode("utf-8", "replace")).hexdigest()
        now = self.clock()
        with self._lock:
            return self._negative.get(digest, 0.0) > now

    def blocked_sources(self) -> int:
        now = self.clock()
        with self._lock:
            return sum(1 for e in self._sources.values() if e.get("until", 0.0) > now)

    # --- Ergebnisse --------------------------------------------------------
    def failure(self, key: str, header: str | None = None) -> dict:
        """Fehlversuch festhalten. Rückgabe: {"count", "blocked_for", "started", "report"}.

        started: diese Quelle ist mit diesem Versuch gerade in die Bremse gelaufen.
        report: jetzt ein (zusammenfassendes) Ereignis schreiben; "reported" zählt die Versuche seit dem letzten.
        """
        now = self.clock()
        with self._lock:
            self._prune(now)
            entry = self._sources.get(key)
            if entry is None or now - entry["last"] > WINDOW:
                entry = {"count": 0, "last": now, "until": 0.0}
                self._sources[key] = entry
            entry["count"] += 1
            entry["last"] = now
            blocked = 0.0
            if entry["count"] >= FREE_FAILURES:
                blocked = min(MAX_BLOCK, 2.0 ** (entry["count"] - FREE_FAILURES + 1))
                entry["until"] = now + blocked
            self._recent.append(now)
            while self._recent and now - self._recent[0] > GLOBAL_WINDOW:
                self._recent.popleft()
            if len(self._recent) > GLOBAL_LIMIT and self._global_until <= now:
                self._global_until = now + GLOBAL_BLOCK
            if header:
                digest = hashlib.sha256(header.encode("utf-8", "replace")).hexdigest()
                self._negative[digest] = now + NEGATIVE_SECONDS
            self._pending_events += 1
            report = now - self._last_event >= EVENT_EVERY
            reported = self._pending_events
            if report:
                self._last_event = now
                self._pending_events = 0
            return {"count": entry["count"], "blocked_for": blocked,
                    "started": entry["count"] == FREE_FAILURES, "report": report, "reported": reported}

    def success(self, key: str) -> None:
        now = self.clock()
        with self._lock:
            self._sources.pop(key, None)
            self._known_good[key] = now + KNOWN_GOOD_SECONDS
            if len(self._known_good) > MAX_SOURCES:
                self._known_good = {k: v for k, v in self._known_good.items() if v > now}

    @contextmanager
    def slot(self):
        """Platz für eine teure Prüfung; yield False, wenn zu lange keiner frei wurde."""
        got = self._slots.acquire(timeout=SLOT_WAIT)
        try:
            yield got
        finally:
            if got:
                self._slots.release()

    def clear(self) -> None:
        with self._lock:
            self._sources.clear()
            self._recent.clear()
            self._global_until = 0.0
            self._known_good.clear()
            self._negative.clear()
            self._last_event = -1e18
            self._pending_events = 0

    def _prune(self, now: float) -> None:
        if len(self._negative) > MAX_SOURCES:
            self._negative = {k: v for k, v in self._negative.items() if v > now}
        if len(self._sources) > MAX_SOURCES:
            self._sources = {k: e for k, e in self._sources.items()
                             if e.get("until", 0.0) > now or now - e["last"] <= WINDOW}
            if len(self._sources) > MAX_SOURCES:  # immer noch zu viele: die ältesten vergessen
                keep = sorted(self._sources.items(), key=lambda item: item[1]["last"])[-MAX_SOURCES // 2:]
                self._sources = dict(keep)


GUARD = Guard()
