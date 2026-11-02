"""Schaltsekunden-Übersicht aus leap-seconds.list (IERS/IETF-Format).

Die Datei kommt mit dem Debian-Paket tzdata ins Image; chrony liest sie über
`leapseclist`. Sie nennt jede Schaltsekunde seit 1972 mit dem dann gültigen
Abstand TAI−UTC, wann sie zuletzt aktualisiert wurde („#$“), bis wann sie gilt
(„#@“, halbjährlich nach IERS Bulletin C) und eine SHA-1-Prüfsumme („#h“).

Format (alle Zeiten in Sekunden seit 1900-01-01 00:00 UTC, „NTP-Zeit“):
    #$  3992312697                letzte Aktualisierung
    #@  4023129600                Ablaufdatum
    2272060800  10  # 1 Jan 1972  ab diesem Zeitpunkt gilt TAI−UTC = 10 s
    #h  a9bad145 84c31c70 758402aa b37bfd54 5923836a

Prüfsumme: SHA-1 über die aneinandergehängten Zahlen der „#$“- und „#@“-Zeile
und der ersten beiden Felder jeder Datenzeile – ohne Leerraum und Kommentare.
Die fünf 32-Bit-Wörter stehen hexadezimal ohne führende Nullen in der Datei,
darum wird wortweise als Zahl verglichen.

Warum das wichtig ist: Läuft die Liste ab, weiß chrony nichts mehr über
künftige Schaltsekunden – das Image ist dann zu alt. ntp-gui lädt die Datei
bewusst nicht selbst nach (keine ausgehende Verbindung), sondern meldet
rechtzeitig (60 Tage vorher), dass ein Update fällig ist.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any, Callable

NTP_UNIX_OFFSET = 2_208_988_800   # Sekunden von 1900-01-01 bis 1970-01-01
DEFAULT_PATH = "/usr/share/zoneinfo/leap-seconds.list"
WARN_DAYS = 60
REMIND_SECONDS = 7 * 86400        # Ereignis höchstens einmal pro Woche wiederholen
MAX_BYTES = 256 * 1024


class LeapFileError(ValueError):
    """Datei unlesbar oder nicht im erwarteten Format."""


def parse(text: str) -> dict[str, Any]:
    """Zerlegt den Dateiinhalt. Wirft LeapFileError, wenn wesentliche Teile fehlen."""
    updated = expires = None
    hash_words: list[int] | None = None
    entries: list[tuple[int, int]] = []
    digits: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#$"):
            value = line[2:].split()
            if value and value[0].isdigit():
                updated = int(value[0])
                digits.append(value[0])
            continue
        if line.startswith("#@"):
            value = line[2:].split()
            if value and value[0].isdigit():
                expires = int(value[0])
                digits.append(value[0])
            continue
        if line.startswith("#h"):
            try:
                hash_words = [int(word, 16) for word in line[2:].split()]
            except ValueError:
                hash_words = []
            continue
        if line.startswith("#"):
            continue
        fields = line.split("#", 1)[0].split()
        if len(fields) < 2 or not fields[0].isdigit() or not fields[1].lstrip("-").isdigit():
            raise LeapFileError(f"Unerwartete Zeile: {line[:60]}")
        entries.append((int(fields[0]), int(fields[1])))
        digits += fields[:2]
    if not entries:
        raise LeapFileError("Keine Schaltsekunden-Einträge gefunden")
    if expires is None:
        raise LeapFileError("Ablaufdatum („#@“) fehlt")
    hash_ok = None
    if hash_words is not None:
        digest = hashlib.sha1("".join(digits).encode("ascii")).hexdigest()
        expected = [int(digest[i:i + 8], 16) for i in range(0, 40, 8)]
        hash_ok = hash_words == expected
    entries.sort()
    return {"updated": updated, "expires": expires, "entries": entries, "hash_ok": hash_ok}


def to_unix(ntp_seconds: int | None) -> int | None:
    return None if ntp_seconds is None else int(ntp_seconds) - NTP_UNIX_OFFSET


def _date(unix: int | None) -> str | None:
    return None if unix is None else time.strftime("%Y-%m-%d", time.gmtime(unix))


def evaluate(parsed: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """Kennzahlen zum Zeitpunkt now: TAI−UTC, letzte/nächste Schaltsekunde, Ablauf."""
    now = time.time() if now is None else float(now)
    entries = [(to_unix(t), d) for t, d in parsed["entries"]]
    past = [(t, d) for t, d in entries if t is not None and t <= now]
    future = [(t, d) for t, d in entries if t is not None and t > now]
    expires = to_unix(parsed["expires"])
    days_left = (expires - now) / 86400.0 if expires is not None else None
    out: dict[str, Any] = {
        "tai_utc": past[-1][1] if past else None,
        "leap_count": max(0, len(past) - 1),   # der erste Eintrag (1972: 10 s) ist keine Schaltsekunde
        "updated": to_unix(parsed["updated"]),
        "updated_date": _date(to_unix(parsed["updated"])),
        "expires": expires,
        "expires_date": _date(expires),
        "days_left": None if days_left is None else int(days_left // 1),
        "expired": days_left is not None and days_left < 0,
        "hash_ok": parsed["hash_ok"],
        "entries": len(entries),
        "last_leap": None, "last_leap_date": None, "last_leap_delta": None,
        "next_leap": None, "next_leap_date": None, "next_leap_delta": None,
    }
    if len(past) >= 2:
        # Der Eintrag nennt den Beginn des neuen Abstands (1.1.2017 00:00 UTC);
        # die Schaltsekunde selbst ist 23:59:60 des Vortags.
        out.update(last_leap=past[-1][0], last_leap_date=_date(past[-1][0]),
                   last_leap_delta=past[-1][1] - past[-2][1])
    if future:
        prev = past[-1][1] if past else future[0][1]
        out.update(next_leap=future[0][0], next_leap_date=_date(future[0][0]),
                   next_leap_delta=future[0][1] - prev)
    level, reason = "ok", None
    if parsed["hash_ok"] is False:
        level, reason = "warn", "hash"
    elif out["expired"]:
        level, reason = "warn", "expired"
    elif days_left is not None and days_left < WARN_DAYS:
        level, reason = "warn", "expiring"
    out["level"], out["reason"] = level, reason
    return out


_CACHE: dict[str, Any] = {"key": None, "parsed": None, "error": None}
_CACHE_LOCK = threading.Lock()


def _load(path: str) -> tuple[dict | None, str | None]:
    try:
        st = os.stat(path)
    except OSError as exc:
        return None, f"Datei nicht lesbar ({exc.strerror or exc})"
    key = (path, st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        if _CACHE["key"] == key:
            return _CACHE["parsed"], _CACHE["error"]
    parsed, error = None, None
    try:
        if st.st_size > MAX_BYTES:
            raise LeapFileError("Datei ist unerwartet groß")
        with open(path, encoding="ascii", errors="replace") as handle:
            parsed = parse(handle.read(MAX_BYTES))
    except (OSError, LeapFileError) as exc:
        error = str(exc)
    with _CACHE_LOCK:
        _CACHE.update(key=key, parsed=parsed, error=error)
    return parsed, error


def file_path(cfg: dict | None) -> str:
    path = str((cfg or {}).get("leapseclist") or "").strip()
    return path or DEFAULT_PATH


def status(cfg: dict | None = None, tracking: dict | None = None, now: float | None = None,
           path: str | None = None) -> dict[str, Any]:
    """Alles für die Seite und /api/leap. Wirft nie."""
    path = path or file_path(cfg)
    out: dict[str, Any] = {"path": path, "available": False, "error": None,
                           "configured": bool((cfg or {}).get("leapseclist")),
                           "leapsectz": str((cfg or {}).get("leapsectz") or "") or None,
                           "chrony_leap": (tracking or {}).get("leap_status") or None,
                           "warn_days": WARN_DAYS, "level": "unknown", "reason": None}
    parsed, error = _load(path)
    if parsed is None:
        out.update(error=error, level="warn", reason="missing")
        return out
    out.update(evaluate(parsed, now), available=True)
    return out


def insights(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Hinweis für die Übersicht, wenn die Liste bald abläuft, abgelaufen oder verändert ist."""
    reason = info.get("reason")
    if info.get("level") != "warn" or reason not in {"expiring", "expired", "hash"}:
        return []
    if reason == "hash":
        title = "Schaltsekunden-Liste: Prüfsumme stimmt nicht"
        text = (f"Die Prüfsumme in {info.get('path')} passt nicht zum Inhalt – die Datei ist beschädigt oder "
                "von Hand verändert. chrony liest sie trotzdem; verlass dich aber nicht auf die Angaben. Ein "
                "aktuelles Image (oder das Paket tzdata) bringt eine saubere Datei mit.")
    elif reason == "expired":
        title = "Schaltsekunden-Liste abgelaufen – Image zu alt"
        text = (f"Die Liste galt nur bis {info.get('expires_date')}. Danach weiß chrony nicht, ob eine "
                "Schaltsekunde angekündigt ist, und gibt sie nicht an die Clients weiter. Spiel ein "
                "aktuelles Image ein (docker compose pull && docker compose up -d) – es bringt eine neue "
                "Liste aus dem Paket tzdata mit.")
    else:
        title = f"Schaltsekunden-Liste läuft in {info.get('days_left')} Tagen ab – Image zu alt"
        text = (f"Die Liste gilt bis {info.get('expires_date')}. Das IERS verlängert sie jedes halbe Jahr "
                "(Bulletin C); ein aktuelles Image bringt die neue Fassung mit. Update einspielen: "
                "docker compose pull && docker compose up -d. ntp-gui lädt die Datei bewusst nicht selbst "
                "aus dem Internet.")
    return [{"level": "warn", "key": "leap_list", "title": title, "text": text, "action": "uhrqualitaet"}]


class Watch:
    """Schreibt das Ereignis leap/warn – einmal je Zustand, danach höchstens wöchentlich.

    Beim ersten Aufruf nach einem Neustart wird im Protokoll nachgesehen, ob
    das Ereignis in der letzten Woche schon geschrieben wurde – sonst gäbe es bei
    jedem Neustart des Containers eine neue Benachrichtigung.
    """

    def __init__(self, emit: Callable[..., Any], recent: Callable[[float], list[dict]]) -> None:
        self._emit = emit
        self._recent = recent
        self._sent: dict[str, float] = {}
        self._loaded = False

    def check(self, info: dict[str, Any], now: float | None = None) -> bool:
        now = time.time() if now is None else now
        items = insights(info)
        if not items:
            return False
        key = f"{info.get('reason')}:{info.get('expires')}"
        if not self._loaded:
            self._loaded = True
            try:
                for event in self._recent(now - REMIND_SECONDS):
                    data = event.get("data") or {}
                    if isinstance(data, dict) and data.get("key"):
                        self._sent[str(data["key"])] = max(self._sent.get(str(data["key"]), 0), event.get("t") or 0)
            except Exception:
                pass
        if now - self._sent.get(key, 0) < REMIND_SECONDS:
            return False
        self._sent[key] = now
        self._emit("leap", "warn", items[0]["title"],
                   {"key": key, "expires": info.get("expires_date"), "days_left": info.get("days_left"),
                    "reason": info.get("reason")})
        return True
