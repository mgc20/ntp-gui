"""Bremse für Anmeldeversuche (Benutzer/Passwort): je Quelladresse, gesamt und für die CPU.

Jede Passwortprüfung kostet Rechenzeit (PBKDF2). Ohne Bremse ließe sich ein Passwort beliebig schnell
durchprobieren, und viele gleichzeitige Fehlversuche lasten die CPU aus. Darum:

- Je Quelle (IPv4-Adresse bzw. IPv6-/64-Netz) sind FREE_FAILURES Fehlversuche frei. Danach muss die
  Quelle warten: 2 s, 4 s, 8 s … höchstens MAX_BLOCK. Eine Anmeldung von dort wird in dieser Zeit gar
  nicht erst geprüft (Antwort 429 mit Retry-After). Nach WINDOW ohne neuen Fehlversuch ist alles vergessen.
- Prüfungen werden vorab reserviert (reserve/release, atomar unter einer Sperre): Laufende Prüfungen einer
  Quelle zählen wie Fehlversuche. Auch viele gleichzeitige Anfragen bekommen so zusammen nicht mehr als
  FREE_FAILURES Prüfungen, bevor die Bremse greift.
- Gesamt: Mehr als GLOBAL_LIMIT Fehlversuche in GLOBAL_WINDOW aus allen Quellen zusammen bremsen alle
  ungeprüften Anmeldungen für GLOBAL_BLOCK – außer aus Quellen, von denen in den letzten KNOWN_GOOD_SECONDS
  eine Anmeldung gelang. Diese Ausnahme übersteht Neustarts (persist(): nur HMAC-Werte der Quellschlüssel
  mit einem Zufallswert der Installation, keine Adressen im Klartext). Ein schon geprüfter, gültiger
  Zugang (Merker in server.AUTH_CACHE) ist nie betroffen.
- Höchstens CONCURRENT Passwortprüfungen laufen gleichzeitig (Semaphore).
- Ein gerade abgelehnter, identischer Anmeldekopf wird NEGATIVE_SECONDS lang ohne neue Prüfung abgelehnt.
  Derselbe falsche Anmeldekopf zählt innerhalb von WINDOW nur einmal als Fehlversuch (ein offener Tab mit
  altem Passwort fragt regelmäßig nach – das ist kein neuer Rateversuch).

Die Quelladresse kommt aus webtransport.resolve(): Proxy-Köpfe zählen nur von TRUSTED_PROXIES.

Fehlversuche landen gedrosselt im Ereignisprotokoll (Art „access“, ohne Adresse) und im Server-Log (mit
Adresse – dort kann z. B. fail2ban sie auswerten).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
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
KNOWN_GOOD_SECONDS = 30 * 86400.0
KNOWN_GOOD_REFRESH = 86400.0   # Datei höchstens einmal am Tag je Quelle neu schreiben
CONCURRENT = 2
SLOT_WAIT = 5.0
BUSY_RETRY = 1.0          # Wartezeit, wenn schon genug Prüfungen dieser Quelle laufen
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
    def __init__(self, clock=time.monotonic, wall=time.time) -> None:
        self.clock = clock
        self.wall = wall
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(CONCURRENT)
        self._sources: dict[str, dict] = {}       # Schlüssel → {"count", "last", "until"}
        self._recent: deque = deque()             # Zeitpunkte der Fehlversuche (gesamt)
        self._global_until = 0.0
        self._known_good: dict[str, float] = {}   # HMAC des Schlüssels → gültig bis (Wanduhr)
        self._negative: dict[str, float] = {}     # Hash des Anmeldekopfs → abgelehnt bis
        self._counted: dict[str, float] = {}      # Hash des Anmeldekopfs → als Fehlversuch gezählt bis
        self._busy: dict[str, int] = {}           # Schlüssel → laufende (reservierte) Prüfungen
        self._busy_total = 0
        self._salt = secrets.token_bytes(32)
        self._store: str | None = None
        self._last_event = -1e18
        self._pending_events = 0

    # --- Abfragen ----------------------------------------------------------
    def retry_after(self, key: str) -> float:
        """Sekunden, die diese Quelle noch warten muss (0 = darf prüfen lassen)."""
        now = self.clock()
        with self._lock:
            return self._wait_locked(key, now)

    def _good_locked(self, key: str) -> bool:
        return self._known_good.get(self._mark(key), 0.0) > self.wall()

    def _wait_locked(self, key: str, now: float) -> float:
        entry = self._sources.get(key)
        wait = max(0.0, (entry or {}).get("until", 0.0) - now)
        if self._global_until > now and not self._good_locked(key):
            wait = max(wait, self._global_until - now)
        return wait

    def reserve(self, key: str) -> float:
        """Eine Prüfung für diese Quelle anmelden – atomar mit der Abfrage der Bremse.

        0 = reserviert (danach unbedingt release()), sonst die Wartezeit in Sekunden. Laufende Prüfungen
        zählen wie Fehlversuche: Sind schon so viele unterwegs, dass sie zusammen mit den gezählten
        Fehlversuchen die freien Versuche aufbrauchen, muss die Anfrage warten.
        """
        now = self.clock()
        with self._lock:
            wait = self._wait_locked(key, now)
            if wait > 0:
                return wait
            entry = self._sources.get(key)
            count = entry["count"] if entry and now - entry["last"] <= WINDOW else 0
            busy = self._busy.get(key, 0)
            if busy and count + busy >= FREE_FAILURES:
                return BUSY_RETRY
            while self._recent and now - self._recent[0] > GLOBAL_WINDOW:
                self._recent.popleft()
            if self._busy_total and len(self._recent) + self._busy_total > GLOBAL_LIMIT \
                    and not self._good_locked(key):
                return BUSY_RETRY
            self._busy[key] = busy + 1
            self._busy_total += 1
            return 0.0

    def release(self, key: str) -> None:
        with self._lock:
            busy = self._busy.get(key, 0)
            if busy <= 1:
                self._busy.pop(key, None)
            else:
                self._busy[key] = busy - 1
            if busy:
                self._busy_total -= 1

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
        counted: False, wenn genau dieser Anmeldekopf in WINDOW schon gezählt wurde (dann ändert sich nichts
        außer dem Negativ-Merker; kein Log, kein Ereignis).
        """
        now = self.clock()
        digest = hashlib.sha256(header.encode("utf-8", "replace")).hexdigest() if header else None
        with self._lock:
            self._prune(now)
            if digest:
                self._negative[digest] = now + NEGATIVE_SECONDS
                if self._counted.get(digest, 0.0) > now:
                    entry = self._sources.get(key) or {}
                    return {"count": entry.get("count", 0), "blocked_for": 0.0, "started": False,
                            "report": False, "reported": 0, "counted": False}
                self._counted[digest] = now + WINDOW
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
            self._pending_events += 1
            report = now - self._last_event >= EVENT_EVERY
            reported = self._pending_events
            if report:
                self._last_event = now
                self._pending_events = 0
            return {"count": entry["count"], "blocked_for": blocked,
                    "started": entry["count"] == FREE_FAILURES, "report": report, "reported": reported,
                    "counted": True}

    def success(self, key: str) -> None:
        wall = self.wall()
        with self._lock:
            self._sources.pop(key, None)
            mark = self._mark(key)
            fresh = self._known_good.get(mark, 0.0) - wall < KNOWN_GOOD_SECONDS - KNOWN_GOOD_REFRESH
            self._known_good[mark] = wall + KNOWN_GOOD_SECONDS
            if len(self._known_good) > MAX_SOURCES:
                keep = sorted((v, k) for k, v in self._known_good.items() if v > wall)[-MAX_SOURCES // 2:]
                self._known_good = {k: v for v, k in keep}
            if fresh:
                self._save_locked()

    # --- Bekannte Quellen über Neustarts ------------------------------------
    def _mark(self, key: str) -> str:
        return hmac.new(self._salt, key.encode("utf-8", "replace"), hashlib.sha256).hexdigest()

    def persist(self, path: str) -> None:
        """Bekannte Quellen in `path` halten (JSON, 0600): Zufallswert + HMAC-Werte mit Ablauf, keine Adressen."""
        wall = self.wall()
        data: dict = {}
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
        with self._lock:
            self._store = path
            try:
                salt = bytes.fromhex(str(data.get("salt", "")))
            except ValueError:
                salt = b""
            entries = data.get("known") if isinstance(data.get("known"), dict) else {}
            if len(salt) == 32:
                self._salt = salt
                self._known_good = {str(k): float(v) for k, v in list(entries.items())[:MAX_SOURCES]
                                    if isinstance(v, (int, float)) and wall < v <= wall + KNOWN_GOOD_SECONDS}
            else:
                self._known_good = {}
                self._save_locked()

    def _save_locked(self) -> None:
        if not self._store:
            return
        tmp = f"{self._store}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"salt": self._salt.hex(), "known": self._known_good}, handle)
            os.replace(tmp, self._store)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

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
            self._counted.clear()
            self._busy.clear()
            self._busy_total = 0
            self._store = None
            self._last_event = -1e18
            self._pending_events = 0

    def _prune(self, now: float) -> None:
        if len(self._negative) > MAX_SOURCES:
            self._negative = {k: v for k, v in self._negative.items() if v > now}
        if len(self._counted) > MAX_SOURCES:
            self._counted = {k: v for k, v in self._counted.items() if v > now}
            if len(self._counted) > MAX_SOURCES:
                keep = sorted((v, k) for k, v in self._counted.items())[-MAX_SOURCES // 2:]
                self._counted = {k: v for v, k in keep}
        if len(self._sources) > MAX_SOURCES:
            self._sources = {k: e for k, e in self._sources.items()
                             if e.get("until", 0.0) > now or now - e["last"] <= WINDOW}
            if len(self._sources) > MAX_SOURCES:  # immer noch zu viele: die ältesten vergessen
                keep = sorted(self._sources.items(), key=lambda item: item[1]["last"])[-MAX_SOURCES // 2:]
                self._sources = dict(keep)


GUARD = Guard()
