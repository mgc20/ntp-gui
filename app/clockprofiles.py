"""Benannte Profile der Vollbild-Uhr (/clock?p=name) – Prüfung, feste Voreinstellungen, öffentlicher Lesepfad.

Ein Profil ist eine dünne Schicht über dem Link: genau die Adressparameter der Uhr (PARAMS, dieselbe Tabelle
wie PARAM_SCHEMA in app/static/js/clockkit.js – tests/test_uhr_profile.py vergleicht beide), dazu ein Titel.
Gespeichert wird es als Einstellung „clock_profiles“ (settings.py, Konverter clean_profiles), geschrieben nur
über die Einstellungen-API mit Anmeldung und CSRF-Schutz, gesichert mit den übrigen Einstellungen (backup.py).

Gelesen wird über GET /api/v1/clock/profile?p=<name> – mit „Vollbild-Uhr ohne Anmeldung“ auch ohne Login. Die
Antwort enthält nur Allowlist-Felder (public_profile). Werte sind die rohen Zeichenketten aus der Adresse; die
Uhr prüft sie beim Lesen noch einmal mit demselben Schema. Standortangaben kennt die Tabelle nicht.

Nur Standardbibliothek, ohne Seiteneffekte beim Import.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import unicodedata
from typing import Any

import textsafe

NAME_RE = re.compile(r"^[a-z0-9-]{1,32}\Z")
MAX_PROFILES = 20
TITLE_MAX = 40
MAX_LEN = 64          # wie MAX_LEN in clockkit.js: längere Werte verwirft die Uhr

DESIGNS = ("digital", "studio", "bahnhof", "nixie", "flip", "wort")
LAYOUTS = ("auto", "normal", "banner", "column", "strip", "tile")
SHOW_ITEMS = ("time", "seconds", "date", "weekday", "week", "utc", "tz", "status", "countdown")
LOOKS = ("studio", "contrast", "warm", "terminal", "paper", "pastel")
PALETTE = ("amber", "red", "green", "cyan", "white", "ice", "yellow", "orange", "blue", "violet", "pink", "lime")
STUDIO_COLORS = ("amber", "red", "green", "cyan", "white", "ice")

# name → (Typ, Angaben). Typen wie in clockkit.js: enum, flag, int, zone, label, time, duration, intlist, list, color.
PARAMS: dict[str, tuple[str, dict]] = {
    "design": ("enum", {"values": DESIGNS}),
    "kiosk": ("flag", {}),
    "eink": ("flag", {}),
    "tz": ("zone", {}),
    "lead": ("int", {"min": 0, "max": 200}),
    "maxerr": ("int", {"min": 10, "max": 1000}),
    "layout": ("enum", {"values": LAYOUTS}),
    "safe": ("int", {"min": 0, "max": 10}),
    "bg": ("enum", {"values": ("black", "transparent")}),
    "scale": ("int", {"min": 50, "max": 200}),
    "show": ("list", {"values": SHOW_ITEMS}),
    "weight": ("enum", {"values": ("thin", "regular", "bold")}),
    "shift": ("int", {"min": 0, "max": 2}),
    "color": ("enum", {"values": STUDIO_COLORS}),
    "sub": ("enum", {"values": ("utc", "tz2", "date", "off")}),
    "seconds": ("enum", {"values": ("ring", "digits", "both")}),
    "h12": ("flag", {}),
    "face": ("enum", {"values": ("sans", "mono", "seg")}),
    "colon": ("enum", {"values": ("steady", "blink")}),
    "lz": ("flag", {}),
    "date": ("enum", {"values": ("long", "short", "iso", "off")}),
    "look": ("enum", {"values": LOOKS}),
    "accent": ("color", {}),
    "until": ("time", {}),
    "timer": ("duration", {}),
    "after": ("enum", {"values": ("up", "stop")}),
    "warn": ("intlist", {"min": 1, "max": 3600, "max_items": 3}),
    "beep": ("int", {"min": 0, "max": 60}),
    "label": ("label", {"len": 24}),
    "cd": ("enum", {"values": ("below", "main")}),
    "lock": ("flag", {}),
}

# Fest eingebaute Voreinstellungen (nicht editierbar, Namen reserviert). Im Studio-, Kachel- und Kiosk-Betrieb
# ohne Spielereien; Pixel-Shift gegen Einbrennen bei Dauerbetrieb.
PRESETS: dict[str, dict[str, Any]] = {
    "studio": {"title": "Studio", "params": {"design": "studio", "look": "studio", "color": "amber",
                                             "seconds": "both", "sub": "utc", "shift": "1", "kiosk": "1"}},
    "tile": {"title": "Multiviewer-Kachel", "params": {"layout": "tile", "design": "digital", "face": "seg",
                                                       "bg": "black", "safe": "5", "lock": "1"}},
    "banner": {"title": "Banner", "params": {"layout": "banner", "design": "digital", "face": "seg",
                                             "look": "studio", "kiosk": "1"}},
    "kitchen": {"title": "Küche", "params": {"design": "flip", "look": "warm", "timer": "10m",
                                             "date": "short"}},
    "workshop": {"title": "Werkstatt", "params": {"design": "digital", "face": "seg", "look": "contrast",
                                                  "weight": "bold", "scale": "120"}},
    "night": {"title": "Nacht", "params": {"design": "digital", "look": "warm", "weight": "thin",
                                           "show": "time", "scale": "80", "shift": "2"}},
    "nerd": {"title": "Nerd", "params": {"design": "digital", "face": "mono", "look": "terminal",
                                         "date": "iso", "show": "time,seconds,date,week,utc,status"}},
}

_FLAGS = {"1", "0", "true", "false"}
_INT_RE = re.compile(r"^[0-9]{1,6}\Z")
_ZONE_RE = re.compile(r"^[A-Za-z0-9_+\-/]+\Z")
_HEX6_RE = re.compile(r"^[0-9a-fA-F]{6}\Z")
_DAILY_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?\Z")
_ISO_RE = re.compile(r"^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):([0-5][0-9])"
                     r"(?::([0-5][0-9]))?\Z")
_DURATION_RE = re.compile(r"^(?:([0-9]{1,2})h)?(?:([0-9]{1,4})m)?(?:([0-9]{1,5})s)?\Z")
_LABEL_EXTRA = set(" .,:!?+-/()#&'")
MAX_TIMER_S = 24 * 3600


class ProfileError(ValueError):
    """Ungültiges Profil – settings.py macht daraus eine ValidationError."""


def _label_ok(text: str, limit: int) -> bool:
    if not text or len(text) > limit or text.strip() != text:
        return False
    return all(ch in _LABEL_EXTRA or unicodedata.category(ch)[0] in "LN" for ch in text)


@functools.lru_cache(maxsize=1)
def _zones() -> frozenset:
    try:
        import zoneinfo
        return frozenset(z.lower() for z in zoneinfo.available_timezones())
    except Exception:
        return frozenset()


def _zone_ok(text: str) -> bool:
    if not _ZONE_RE.match(text):
        return False
    zones = _zones()
    if not zones:
        return True   # ohne Zeitzonendatenbank prüft die Uhr selbst (Intl)
    return text.upper() == "UTC" or text.lower() in zones


def _time_ok(text: str) -> bool:
    if _DAILY_RE.match(text):
        return True
    match = _ISO_RE.match(text)
    if not match:
        return False
    import datetime
    try:
        datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


def _duration_ok(text: str) -> bool:
    match = _DURATION_RE.match(text)
    if not text or not match or not any(match.groups()):
        return False
    seconds = (int(match.group(1) or 0) * 60 + int(match.group(2) or 0)) * 60 + int(match.group(3) or 0)
    return 0 < seconds <= MAX_TIMER_S


def check_value(name: str, raw: Any) -> str:
    """Einen Parameterwert prüfen; liefert die Zeichenkette, wie sie in die Adresse gehört, sonst ProfileError."""
    spec = PARAMS.get(name)
    if spec is None:
        raise ProfileError(f"unbekannter Parameter „{str(name)[:32]}“")
    kind, info = spec
    if isinstance(raw, bool):
        raw = "1" if raw else "0"
    elif isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str):
        raise ProfileError(f"{name}: Text erwartet")
    text = unicodedata.normalize("NFC", raw) if kind == "label" else raw
    ok = False
    if len(text) <= MAX_LEN:
        if kind == "enum":
            ok = text in info["values"]
        elif kind == "flag":
            ok = text in _FLAGS
        elif kind == "int":
            ok = bool(_INT_RE.match(text)) and info["min"] <= int(text) <= info["max"]
        elif kind == "zone":
            ok = _zone_ok(text)
        elif kind == "label":
            ok = _label_ok(text, info["len"])
        elif kind == "time":
            ok = _time_ok(text)
        elif kind == "duration":
            ok = _duration_ok(text)
        elif kind == "intlist":
            items = text.split(",")
            ok = 0 < len(items) <= info["max_items"] and all(_INT_RE.match(i) for i in items)
            ok = ok and all(info["min"] <= int(i) <= info["max"] for i in items) and len(set(items)) == len(items)
        elif kind == "list":
            items = text.split(",")
            ok = bool(items) and all(i in info["values"] for i in items) and len(set(items)) == len(items)
        elif kind == "color":
            ok = text in PALETTE or bool(_HEX6_RE.match(text))
            text = text.lower() if ok and text not in PALETTE else text
    if not ok:
        raise ProfileError(f"{name}: unzulässiger Wert")
    return text


def clean_title(raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ProfileError("Titel: Text erwartet")
    text = textsafe.clean(raw, 0)
    if len(text) > TITLE_MAX:
        raise ProfileError(f"Titel: höchstens {TITLE_MAX} Zeichen")
    return text


def clean_profile(raw: Any) -> dict:
    """{"title": …, "params": {name: wert}} – fremde Felder und unbekannte Parameter werden abgewiesen."""
    if not isinstance(raw, dict):
        raise ProfileError("Profil: Objekt erwartet")
    extra = set(raw) - {"title", "params"}
    if extra:
        raise ProfileError(f"unbekanntes Feld „{str(sorted(extra)[0])[:32]}“")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise ProfileError("params: Objekt erwartet")
    clean = {}
    for name in PARAMS:   # feste Reihenfolge wie in der Adresse
        if name in params and params[name] not in (None, ""):
            clean[name] = check_value(name, params[name])
    unknown = [name for name in params if name not in PARAMS]
    if unknown:
        raise ProfileError(f"unbekannter Parameter „{str(unknown[0])[:32]}“")
    return {"title": clean_title(raw.get("title")), "params": clean}


def check_name(name: Any) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ProfileError("Profilname: 1–32 Zeichen aus a–z, 0–9 und Bindestrich")
    if name in PRESETS:
        raise ProfileError(f"„{name}“ ist eine feste Voreinstellung")
    return name


def clean_profiles(value: Any) -> dict:
    """Alle gespeicherten Profile prüfen (Konverter der Einstellung clock_profiles)."""
    if value in (None, "", {}):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ProfileError("Profile: JSON-Objekt erwartet") from None
    if not isinstance(value, dict):
        raise ProfileError("Profile: Objekt erwartet")
    if len(value) > MAX_PROFILES:
        raise ProfileError(f"höchstens {MAX_PROFILES} Profile")
    out = {}
    for name in sorted(value, key=str):
        try:
            out[check_name(name)] = clean_profile(value[name])
        except ProfileError as exc:
            raise ProfileError(f"{str(name)[:32]}: {exc}") from None
    return out


def revision(stored: Any) -> str:
    """Kennung des Profilstands für /api/v1/time (profiles_rev): ändert sich mit jedem gespeicherten Unterschied."""
    try:
        text = json.dumps(stored or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def public_profile(name: Any, stored: Any) -> dict | None:
    """Antwort von GET /api/v1/clock/profile: nur name, title, params (geprüft) und builtin – sonst None."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    if name in PRESETS:
        entry, builtin = PRESETS[name], True
    else:
        entry, builtin = (stored or {}).get(name) if isinstance(stored, dict) else None, False
    if not isinstance(entry, dict):
        return None
    params = {}
    for key, value in (entry.get("params") or {}).items():
        try:
            params[key] = check_value(key, value)
        except ProfileError:
            continue   # nie etwas außerhalb der Allowlist ausliefern
    try:
        title = clean_title(entry.get("title"))
    except ProfileError:
        title = ""
    return {"name": name, "title": title, "params": params, "builtin": builtin}


def presets_public() -> list[dict]:
    """Die festen Voreinstellungen (für das Dashboard)."""
    return [public_profile(name, None) for name in PRESETS]
