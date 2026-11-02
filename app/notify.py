"""Benachrichtigungen: Ereignisse → Webhook, ntfy, Gotify, Apprise-API.

Ablauf
------
Ein eigener Thread („notify-router“) liest neue Ereignisse aus der Datenbank
(events.after_id) – sofort, wenn events.emit() ihn weckt, sonst alle 2 s (die
Supervisor-Ereignisse kommen per events.ingest_supervisor). Je Kanal prüft ein
ChannelRouter Filter, Entprellen und Problem/behoben-Paare und legt fertige
Meldungen in die Warteschlange des Kanals. Jeder Kanal hat einen eigenen
Sende-Thread mit begrenzter Warteschlange: Ein hängendes Ziel (Timeout 10 s,
drei Wiederholungen) hält weder die anderen Kanäle noch Messung oder
HTTP-Server auf.

Regeln je Kanal
---------------
* Filter: Mindeststufe (info/warn/crit) und Arten (leer = alle). Arten sind
  frei erweiterbar (Muster [a-z][a-z0-9_]*) – neue Ereignisquellen wie „Client-Uhr
  weicht ab“ brauchen hier keine Änderung.
* Schlüssel zum Entprellen: Art + Betreff (data.subject/service/device/client,
  sonst leer). Gleicher Schlüssel höchstens einmal je N Minuten.
* Problem (warn/crit) und „behoben“ (ein info-Ereignis mit demselben Schlüssel,
  solange das Problem offen ist) gehören zusammen: „GPS-Fix wieder da – Dauer 40 min“.
  Ein Problem, das wegen Entprellens zurückgehalten wurde, wird nachgeholt, wenn
  es am Ende der Sperrzeit noch besteht – der letzte Stand kommt also immer an.
  Steigt die Stufe (warn → crit), geht das sofort hinaus.
* Wiederholung nach 30 s, 2 min, 10 min; danach verworfen und lokal als
  Ereignis (Art „notify“) vermerkt. Ereignisse der Art „notify“ werden nie
  verschickt (keine Schleife zwischen zwei kaputten Kanälen).
* Ratenlimit je Kanal (Standard 30 je Stunde, gleitend).

Datenschutz
-----------
Jede Meldung läuft durch egress.notify_message (Zweck „notify“): nur die Felder
der Positivliste, Texte gefiltert (Koordinaten, öffentliche IPs, eigene
Hostnamen …), danach check_no_leaks und backstop. Ereignisdaten (data) gehen nie
hinaus. Ziele: nur http/https, keine Weiterleitungen, keine Proxys, Antwort
höchstens 64 KiB. Tokens stehen in SQLite (Datei 600), werden in UI/API nur als
„gesetzt“ gezeigt und landen nie in Ereignissen oder im Diagnosepaket.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Callable

import egress
import events
import settings
import store

CHANNEL_TYPES = ("webhook", "ntfy", "gotify", "apprise")
TYPE_LABELS = {"webhook": "Webhook (JSON)", "ntfy": "ntfy", "gotify": "Gotify", "apprise": "Apprise-API"}
LEVELS = events.LEVELS
LEVEL_LABELS = {"info": "Info", "warn": "Warnung", "crit": "Kritisch"}
KIND_LABELS = {
    "service": "Dienste", "reload": "Neuladen", "settings": "Einstellungen", "source": "Zeitquellen",
    "gps": "GPS", "pps": "PPS", "calibration": "Kalibrierung", "cert": "Zertifikat",
    "leap": "Schaltsekunde", "startup": "Start", "clients": "Clients", "api": "API", "dns": "DNS für ntp-gui",
    "other": "Sonstiges",
}
# Seite im Dashboard, auf die der Link einer Meldung zeigt.
KIND_PAGES = {"gps": "gps", "pps": "gps", "calibration": "gps", "source": "quellen", "clients": "clients",
              "service": "diagnose", "reload": "diagnose", "cert": "einstellungen", "settings": "einstellungen",
              "leap": "quellen", "dns": "einstellungen"}

MAX_CHANNELS = 10
QUEUE_MAX = 50                     # Meldungen je Kanal; bei Überlauf fällt die älteste weg
RETRY_DELAYS = (30.0, 120.0, 600.0)
TIMEOUT = 10.0
MAX_RESPONSE = 64 * 1024
POLL_SECONDS = 2.0
BATCH = 200
BACKLOG_SECONDS = 300.0            # nach einem Neustart: ältere, noch nicht verschickte Ereignisse verwerfen
DEFAULT_DEBOUNCE_MIN = 15
DEFAULT_RATE_PER_HOUR = 30
KNOWN_NAMES_TTL = 600.0

_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,64}$")
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ID_RE = re.compile(r"^[a-z0-9]{8,16}$")
_SECRET_RE = re.compile(r"^[\x21-\x7e]{1,512}$")           # Token: druckbar, ohne Leerzeichen
_APPRISE_URLS_RE = re.compile(r"^[\x20-\x7e]{1,2000}$")   # Apprise-URLs: mehrere, durch Leerzeichen/Komma

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS notify_channels (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        url TEXT NOT NULL,
        topic TEXT NOT NULL DEFAULT '',
        secret TEXT NOT NULL DEFAULT '',
        min_level TEXT NOT NULL DEFAULT 'warn',
        kinds TEXT NOT NULL DEFAULT '[]',
        debounce_min INTEGER NOT NULL DEFAULT 15,
        rate_per_hour INTEGER NOT NULL DEFAULT 30,
        resolved INTEGER NOT NULL DEFAULT 1,
        created REAL NOT NULL,
        updated REAL NOT NULL,
        last_attempt REAL,
        last_ok REAL,
        last_error TEXT,
        last_error_t REAL,
        sent INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        dropped INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS notify_meta (key TEXT PRIMARY KEY, value TEXT);
    """,
]

_READY: dict[str, Any] = {"db": None}
_DB_LOCK = threading.Lock()


def _ensure() -> None:
    db = store.path()
    if _READY["db"] != db:
        store.migrate("notify", _SCHEMA)
        _READY["db"] = db


class NotifyError(ValueError):
    """Eingabe für einen Kanal ist ungültig (→ HTTP 422 mit deutscher Meldung)."""


# ---------------------------------------------------------------------------
# Kanäle: prüfen, speichern, maskiert ausgeben
# ---------------------------------------------------------------------------

_COLUMNS = ("id", "name", "type", "enabled", "url", "topic", "secret", "min_level", "kinds", "debounce_min",
            "rate_per_hour", "resolved", "created", "updated", "last_attempt", "last_ok", "last_error",
            "last_error_t", "sent", "failed", "dropped")


def _row(values: tuple) -> dict:
    item = dict(zip(_COLUMNS, values))
    try:
        kinds = json.loads(item["kinds"] or "[]")
    except ValueError:
        kinds = []
    item["kinds"] = [k for k in kinds if isinstance(k, str) and _KIND_RE.match(k)]
    item["enabled"] = bool(item["enabled"])
    item["resolved"] = bool(item["resolved"])
    return item


def _load_all() -> list[dict]:
    _ensure()
    rows = store.query("SELECT " + ", ".join(_COLUMNS) + " FROM notify_channels ORDER BY created, id")
    return [_row(r) for r in rows]


def _int_in(value: Any, low: int, high: int, what: str) -> int:
    if isinstance(value, bool):
        raise NotifyError(f"{what}: Zahl erwartet")
    try:
        number = int(str(value).strip()) if not isinstance(value, int) else value
    except (TypeError, ValueError):
        raise NotifyError(f"{what}: Zahl erwartet") from None
    if not low <= number <= high:
        raise NotifyError(f"{what}: {low} bis {high}")
    return number


def validate(data: dict, existing: dict | None = None) -> dict:
    """Eingabe aus dem Dashboard → gespeicherte Felder. Positivliste je Feld, wirft NotifyError.

    secret: fehlt oder None → bisheriges behalten; "" → löschen; sonst ersetzen."""
    if not isinstance(data, dict):
        raise NotifyError("JSON-Objekt erwartet")
    base = dict(existing or {})
    out: dict[str, Any] = {}
    name = " ".join(str(data.get("name", base.get("name", ""))).split())
    if not _NAME_RE.match(name):
        raise NotifyError("Name: 1 bis 64 Zeichen, ohne Steuerzeichen")
    out["name"] = name
    kind = str(data.get("type", base.get("type", ""))).strip()
    if kind not in CHANNEL_TYPES:
        raise NotifyError("Art des Kanals: " + ", ".join(CHANNEL_TYPES))
    out["type"] = kind
    url = str(data.get("url", base.get("url", ""))).strip()
    if not settings.http_url_ok(url):
        raise NotifyError("Adresse: http:// oder https:// mit Hostname bzw. IP, ohne Leerzeichen und ohne "
                          "Benutzer/Passwort in der Adresse (dafür gibt es das Token-Feld)")
    out["url"] = url
    topic = str(data.get("topic", base.get("topic", "")) or "").strip()
    if kind == "ntfy" and not _TOPIC_RE.match(topic):
        raise NotifyError("Thema (ntfy): 1 bis 64 Zeichen aus Buchstaben, Ziffern, _ und -")
    if kind == "apprise" and topic and not _TOPIC_RE.match(topic):
        raise NotifyError("Schlüssel (Apprise): 1 bis 64 Zeichen aus Buchstaben, Ziffern, _ und -")
    out["topic"] = topic if kind in ("ntfy", "apprise") else ""
    if "secret" in data and data["secret"] is not None:
        secret = str(data["secret"]).strip()
    else:
        secret = str(base.get("secret") or "")
    if secret:
        pattern = _APPRISE_URLS_RE if kind == "apprise" else _SECRET_RE
        if not pattern.match(secret):
            raise NotifyError("Token: druckbare Zeichen ohne Leerzeichen, höchstens 512"
                              if kind != "apprise" else "Apprise-URLs: höchstens 2000 druckbare Zeichen")
    if kind == "gotify" and not secret:
        raise NotifyError("Gotify braucht das App-Token")
    if kind == "apprise" and not topic and not secret:
        raise NotifyError("Apprise braucht einen Schlüssel (gespeicherte Konfiguration) oder Apprise-URLs")
    out["secret"] = secret
    level = str(data.get("min_level", base.get("min_level", "warn"))).strip()
    if level not in LEVELS:
        raise NotifyError("Mindeststufe: info, warn oder crit")
    out["min_level"] = level
    kinds = data.get("kinds", base.get("kinds", []))
    if isinstance(kinds, str):
        kinds = [k for k in re.split(r"[\s,]+", kinds) if k]
    if not isinstance(kinds, list) or len(kinds) > 40:
        raise NotifyError("Arten: Liste erwartet")
    clean = []
    for item in kinds:
        text = str(item).strip()
        if not _KIND_RE.match(text):
            raise NotifyError(f"Unbekannte Art „{text[:32]}“")
        if text not in clean:
            clean.append(text)
    out["kinds"] = clean
    out["debounce_min"] = _int_in(data.get("debounce_min", base.get("debounce_min", DEFAULT_DEBOUNCE_MIN)),
                                  0, 1440, "Entprellen")
    out["rate_per_hour"] = _int_in(data.get("rate_per_hour", base.get("rate_per_hour", DEFAULT_RATE_PER_HOUR)),
                                   1, 600, "Höchstens je Stunde")
    for key, default in (("enabled", True), ("resolved", True)):
        value = data.get(key, base.get(key, default))
        try:
            out[key] = settings._as_bool(value)
        except settings.ValidationError as exc:
            raise NotifyError(f"{key}: {exc}") from None
    return out


def public(channel: dict, queued: int = 0) -> dict:
    """Kanal für UI/API: Geheimnis nur als „gesetzt“."""
    return {
        "id": channel["id"], "name": channel["name"], "type": channel["type"],
        "type_label": TYPE_LABELS.get(channel["type"], channel["type"]),
        "enabled": channel["enabled"], "url": channel["url"], "topic": channel["topic"],
        "secret_set": bool(channel.get("secret")), "min_level": channel["min_level"],
        "kinds": list(channel["kinds"]), "debounce_min": channel["debounce_min"],
        "rate_per_hour": channel["rate_per_hour"], "resolved": channel["resolved"],
        "created": channel["created"], "updated": channel["updated"],
        "status": status_of(channel, queued),
    }


def status_of(channel: dict, queued: int = 0) -> dict:
    """Letzter Zustellstand – ohne Adresse und Token (auch für Lese-Schlüssel)."""
    last_ok, last_err_t = channel.get("last_ok"), channel.get("last_error_t")
    state = "never"
    if last_ok and (not last_err_t or last_ok >= last_err_t):
        state = "ok"
    elif last_err_t:
        state = "error"
    if not channel.get("enabled"):
        state = "off"
    return {"state": state, "last_attempt": channel.get("last_attempt"), "last_ok": last_ok,
            "last_error": channel.get("last_error"),
            "last_error_t": last_err_t, "sent": channel.get("sent", 0), "failed": channel.get("failed", 0),
            "dropped": channel.get("dropped", 0), "queued": queued}


def list_channels() -> list[dict]:
    try:
        rows = _load_all()
    except Exception:
        return []
    return [public(c, NOTIFIER.queued(c["id"])) for c in rows]


def get_channel(channel_id: str) -> dict | None:
    for channel in _load_all():
        if channel["id"] == channel_id:
            return channel
    return None


def save_channel(data: dict) -> dict:
    """Anlegen (ohne id) oder ändern (mit id). Gibt den öffentlichen Kanal zurück."""
    with _DB_LOCK:
        channel_id = str(data.get("id") or "").strip()
        now = time.time()
        if channel_id:
            if not _ID_RE.match(channel_id):
                raise NotifyError("Diesen Kanal gibt es nicht (mehr)")
            existing = get_channel(channel_id)
            if existing is None:
                raise NotifyError("Diesen Kanal gibt es nicht (mehr)")
            clean = validate(data, existing)
            with store.transaction() as conn:
                conn.execute("UPDATE notify_channels SET name=?, type=?, enabled=?, url=?, topic=?, secret=?, "
                             "min_level=?, kinds=?, debounce_min=?, rate_per_hour=?, resolved=?, updated=? "
                             "WHERE id=?",
                             (clean["name"], clean["type"], int(clean["enabled"]), clean["url"], clean["topic"],
                              clean["secret"], clean["min_level"], json.dumps(clean["kinds"]),
                              clean["debounce_min"], clean["rate_per_hour"], int(clean["resolved"]), now,
                              channel_id))
            title = "Benachrichtigungskanal geändert"
        else:
            if len(_load_all()) >= MAX_CHANNELS:
                raise NotifyError(f"Höchstens {MAX_CHANNELS} Kanäle")
            clean = validate(data)
            channel_id = secrets.token_hex(5)
            with store.transaction() as conn:
                conn.execute("INSERT INTO notify_channels(id, name, type, enabled, url, topic, secret, min_level, "
                             "kinds, debounce_min, rate_per_hour, resolved, created, updated) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (channel_id, clean["name"], clean["type"], int(clean["enabled"]), clean["url"],
                              clean["topic"], clean["secret"], clean["min_level"], json.dumps(clean["kinds"]),
                              clean["debounce_min"], clean["rate_per_hour"], int(clean["resolved"]), now, now))
            title = "Benachrichtigungskanal angelegt"
    # Nur Kennung und Art ins Protokoll – nie Adresse oder Token.
    events.emit("settings", "info", f"{title}: {channel_id}", {"channel": channel_id, "type": clean["type"]})
    NOTIFIER.reload()
    channel = get_channel(channel_id)
    return public(channel, NOTIFIER.queued(channel_id))


def delete_channel(channel_id: str) -> bool:
    channel_id = str(channel_id or "")
    if not _ID_RE.match(channel_id):
        return False
    with _DB_LOCK:
        _ensure()
        removed = store.execute("DELETE FROM notify_channels WHERE id=?", (channel_id,))
    if removed:
        events.emit("settings", "info", f"Benachrichtigungskanal gelöscht: {channel_id}", {"channel": channel_id})
        NOTIFIER.reload()
    return bool(removed)


def _record(channel_id: str, ok: bool, error: str | None = None, dropped: int = 0, attempt: bool = True) -> None:
    now = time.time()
    try:
        _ensure()
        if attempt and ok:
            store.execute("UPDATE notify_channels SET last_attempt=?, last_ok=?, sent=sent+1 WHERE id=?",
                          (now, now, channel_id))
        elif attempt:
            store.execute("UPDATE notify_channels SET last_attempt=?, last_error=?, last_error_t=?, "
                          "failed=failed+1 WHERE id=?", (now, (error or "Fehler")[:200], now, channel_id))
        if dropped:
            store.execute("UPDATE notify_channels SET dropped=dropped+? WHERE id=?", (int(dropped), channel_id))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Regeln: Filter, Entprellen, Problem/behoben
# ---------------------------------------------------------------------------

def subject_key(event: dict) -> str:
    """Art + Betreff. Betreff aus den Ereignisdaten (Dienst, Gerät, Client …), sonst leer."""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    subject = ""
    for key in ("subject", "service", "device", "client"):
        value = data.get(key)
        if isinstance(value, (str, int)) and str(value):
            subject = str(value)[:80]
            break
    return f"{event.get('kind') or 'other'}:{subject}"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    days, hours = divmod(hours, 24)
    return f"{days} Tage {hours} h" if hours else f"{days} Tage"


def _level_rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


class ChannelRouter:
    """Regeln eines Kanals. Reine Logik mit eingespeister Uhr – offer() und tick() geben Meldungen zurück."""

    def __init__(self, channel: dict, clock: Callable[[], float] = time.time) -> None:
        self.channel = channel
        self.clock = clock
        self.state: dict[str, dict] = {}

    def configure(self, channel: dict) -> None:
        self.channel = channel

    def _matches(self, event: dict) -> bool:
        kinds = self.channel.get("kinds") or []
        if kinds and event.get("kind") not in kinds:
            return False
        return _level_rank(event.get("level")) >= _level_rank(self.channel.get("min_level", "warn"))

    def _window(self) -> float:
        return max(0, int(self.channel.get("debounce_min", DEFAULT_DEBOUNCE_MIN))) * 60.0

    @staticmethod
    def _message(event: dict, title: str, **extra) -> dict:
        msg = {"title": title, "level": event.get("level") or "info", "kind": event.get("kind") or "other",
               "time": event.get("t") or time.time(), "event_id": event.get("id"), "resolved": False}
        msg.update(extra)
        return msg

    def offer(self, event: dict) -> list[dict]:
        if event.get("kind") == "notify":
            return []
        now = self.clock()
        key = subject_key(event)
        st = self.state.setdefault(key, {"open_since": None, "notified": None, "last_sent": None,
                                         "pending": None, "suppressed": 0})
        level = event.get("level") or "info"
        problem = level in ("warn", "crit")
        if not problem and st["open_since"] is not None:
            # „behoben“: gehört zum offenen Problem – auch unterhalb der Mindeststufe.
            out = []
            if st["notified"] and self.channel.get("resolved", True):
                duration = max(0.0, (event.get("t") or now) - st["open_since"])
                title = f"{event.get('title') or 'Behoben'} – Dauer {fmt_duration(duration)}"
                out.append(self._message(event, title, resolved=True, level="info", duration_s=int(duration),
                                         suppressed=st["suppressed"]))
            st.update(open_since=None, notified=None, pending=None, suppressed=0)
            return out
        if not self._matches(event):
            return []
        window = self._window()
        recent = st["last_sent"] is not None and now - st["last_sent"] < window
        if problem:
            if st["open_since"] is None:
                st["open_since"] = event.get("t") or now
            elif st["notified"]:
                if _level_rank(level) > _level_rank(st["notified"]):
                    st["notified"], st["last_sent"] = level, now  # Stufe steigt: sofort
                    return [self._message(event, event.get("title") or "", suppressed=st["suppressed"])]
                st["suppressed"] += 1
                return []
            if recent:
                st["pending"] = event
                st["suppressed"] += 1
                return []
            st["notified"], st["last_sent"], st["pending"] = level, now, None
            return [self._message(event, event.get("title") or "")]
        if recent:
            st["suppressed"] += 1
            return []
        st["last_sent"] = now
        return [self._message(event, event.get("title") or "")]

    def tick(self) -> list[dict]:
        """Zurückgehaltene Probleme nachholen, deren Sperrzeit abgelaufen ist und die noch bestehen."""
        now = self.clock()
        out = []
        window = self._window()
        for st in self.state.values():
            pending = st["pending"]
            if pending is None or st["open_since"] is None:
                continue
            if st["last_sent"] is not None and now - st["last_sent"] < window:
                continue
            since = fmt_duration(now - st["open_since"])
            out.append(self._message(pending, f"{pending.get('title') or ''} (besteht seit {since})",
                                     suppressed=st["suppressed"]))
            st.update(pending=None, notified=pending.get("level") or "warn", last_sent=now, suppressed=0)
        # Aufräumen: geschlossene Schlüssel ohne Sperrzeit vergessen (Speicher bleibt klein).
        for key in [k for k, s in self.state.items() if s["open_since"] is None and s["pending"] is None
                    and (s["last_sent"] is None or now - s["last_sent"] >= window)]:
            del self.state[key]
        return out


# ---------------------------------------------------------------------------
# Text der Meldung
# ---------------------------------------------------------------------------

def _link(kind: str, base: str | None = None) -> str | None:
    if base is None:
        try:
            base = settings.values().get("notify_dashboard_url") or ""
        except Exception:
            base = ""
    if not base or not settings.http_url_ok(base):
        return None
    root = base.split("#", 1)[0]
    if not root.endswith("/"):
        root += "/"
    return f"{root}#/{KIND_PAGES.get(kind, '')}"


def _body(msg: dict) -> str:
    stamp = time.strftime("%d.%m. %H:%M", time.localtime(float(msg.get("time") or time.time())))
    if msg.get("test"):
        return "Wenn du das liest, kommt dieser Kanal an. Echte Meldungen sehen genauso aus."
    kind = KIND_LABELS.get(msg.get("kind"), msg.get("kind") or "")
    if msg.get("resolved"):
        text = f"Behoben · {kind} · {stamp} Uhr"
    else:
        text = f"{LEVEL_LABELS.get(msg.get('level'), 'Info')} · {kind} · {stamp} Uhr"
    if msg.get("suppressed"):
        text += f" · {msg['suppressed']} gleiche Meldungen zusammengefasst"
    return text


_KNOWN: dict[str, Any] = {"t": 0.0, "names": [], "values": {}}


def _known() -> tuple[list, dict]:
    """Eigene Namen/Titel für den Filter (wie im Diagnosepaket), 10 min zwischengespeichert."""
    now = time.monotonic()
    if now - _KNOWN["t"] > KNOWN_NAMES_TTL:
        try:
            import diagnostics  # spät: schwer, und nur hier gebraucht
            cfg = settings.values()
            _KNOWN["names"] = diagnostics._known_names(cfg)
            title = str(cfg.get("web_title") or "").strip()
            _KNOWN["values"] = {"titel": [title] if title and title not in egress.DEFAULT_TITLES else [],
                                "name": diagnostics._client_names()}
        except Exception:
            _KNOWN["names"], _KNOWN["values"] = [], {}
        _KNOWN["t"] = now
    return _KNOWN["names"], _KNOWN["values"]


def outgoing(msg: dict, link_base: str | None = None) -> dict:
    """Meldung → gefilterte Felder für den Versand (egress, Zweck „notify“) + Link. Wirft egress.NotifyLeak."""
    names, values = _known()
    draft = dict(msg)
    draft["text"] = _body(msg)
    clean = egress.notify_message(draft, names, values)
    link = _link(clean.get("kind", ""), link_base)
    if link:
        clean["link"] = link  # selbst eingetragen und geprüft (http_url_ok) – wird nicht gefiltert
    return clean


# ---------------------------------------------------------------------------
# Versand
# ---------------------------------------------------------------------------

class DeliveryError(Exception):
    """Zustellung gescheitert – Text ist kurz, deutsch und enthält weder Adresse noch Token."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen nie folgen: urllib würde sonst still an ein anderes Ziel senden."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise DeliveryError(f"Weiterleitung abgelehnt (HTTP {code}) – trag die Zieladresse direkt ein")


def _opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                    _NoRedirect(), urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener  # ohne ProxyHandler, FileHandler, FTPHandler, DataHandler


PRIORITY_NTFY = {"info": 3, "warn": 4, "crit": 5}
PRIORITY_GOTIFY = {"info": 2, "warn": 5, "crit": 8}
APPRISE_TYPES = {"info": "info", "warn": "warning", "crit": "failure"}
NTFY_TAGS = {"info": ["information_source"], "warn": ["warning"], "crit": ["rotating_light"]}


def signature(secret: str, body: bytes) -> str:
    """Webhook-Signatur: "sha256=" + HMAC-SHA256(secret, body) als Hex."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def build_request(channel: dict, clean: dict, version: str = "") -> tuple[str, bytes, dict]:
    """(URL, Body, Header) für einen Kanal – nur aus den gefilterten Feldern."""
    level = "info" if clean.get("resolved") else clean.get("level", "info")
    title = clean.get("title", "")
    if clean.get("test"):
        title = "Testnachricht von ntp-gui"
    headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": f"ntp-gui/{version or '1'}"}
    url = channel["url"]
    secret = channel.get("secret") or ""
    kind = channel["type"]
    if kind == "webhook":
        payload = {"source": "ntp-gui", "version": 1, **{k: clean[k] for k in sorted(clean)}}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["X-NTPGUI-Event"] = "test" if clean.get("test") else clean.get("kind", "other")
        if secret:
            headers["X-NTPGUI-Signature"] = signature(secret, body)
        return url, body, headers
    if kind == "ntfy":
        tags = ["white_check_mark"] if clean.get("resolved") else NTFY_TAGS.get(level, [])
        payload = {"topic": channel["topic"], "title": title, "message": clean.get("text", ""),
                   "priority": PRIORITY_NTFY.get(level, 3), "tags": tags}
        if clean.get("link"):
            payload["click"] = clean["link"]
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return url.rstrip("/"), json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers
    if kind == "gotify":
        payload = {"title": title, "message": clean.get("text", ""), "priority": PRIORITY_GOTIFY.get(level, 2)}
        if clean.get("link"):
            payload["extras"] = {"client::notification": {"click": {"url": clean["link"]}}}
        headers["X-Gotify-Key"] = secret
        return url.rstrip("/") + "/message", json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers
    if kind == "apprise":
        text = clean.get("text", "")
        if clean.get("link"):
            text += "\n" + clean["link"]
        payload = {"title": title, "body": text,
                   "type": "success" if clean.get("resolved") else APPRISE_TYPES.get(level, "info")}
        target = url.rstrip("/") + "/notify/"
        if channel.get("topic"):
            target += channel["topic"]
        elif secret:
            payload["urls"] = secret
        return target, json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers
    raise DeliveryError("Unbekannte Kanalart")


def _describe(exc: BaseException) -> str:
    if isinstance(exc, DeliveryError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if 300 <= exc.code < 400:
            return f"Weiterleitung abgelehnt (HTTP {exc.code}) – trag die Zieladresse direkt ein"
        if exc.code in (401, 403):
            return f"Ziel lehnt ab (HTTP {exc.code}) – Token prüfen"
        return f"Ziel antwortet mit HTTP {exc.code}"
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return f"Zeitüberschreitung ({int(TIMEOUT)} s)"
    if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError):
        return "TLS-Fehler (Zertifikat ungültig oder nicht vertrauenswürdig)"
    if isinstance(reason, ConnectionRefusedError):
        return "Verbindung abgelehnt – läuft der Dienst, stimmt der Port?"
    if isinstance(reason, socket.gaierror):
        return "Name nicht auflösbar – Adresse prüfen"
    if isinstance(reason, OSError):
        return "Netzwerkfehler – Ziel nicht erreichbar"
    if isinstance(exc, http.client.HTTPException):
        return "Ungültige Antwort vom Ziel"
    return "Zustellung fehlgeschlagen"


def deliver(channel: dict, clean: dict, version: str = "", opener=None) -> None:
    """Eine Meldung zustellen. Wirft DeliveryError mit kurzem deutschem Text."""
    url, body, headers = build_request(channel, clean, version)
    if not settings.http_url_ok(url, max_len=400):
        raise DeliveryError("Adresse ungültig")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with (opener or _opener()).open(request, timeout=TIMEOUT) as response:
            response.read(MAX_RESPONSE)  # begrenzt lesen, Inhalt wird nicht gebraucht
            code = getattr(response, "status", 200)
    except DeliveryError:
        raise
    except Exception as exc:  # noqa: BLE001 – alles wird zu einer kurzen Meldung
        raise DeliveryError(_describe(exc)) from None
    if not 200 <= code < 300:
        raise DeliveryError(f"Ziel antwortet mit HTTP {code}")


# ---------------------------------------------------------------------------
# Threads: Router + ein Sender je Kanal
# ---------------------------------------------------------------------------

def _label(channel: dict) -> str:
    """Kanal im Ereignisprotokoll: Kennung + Art – nie der frei gewählte Name, nie Adresse oder Token
    (das Protokoll landet gefiltert im Diagnosepaket; ein Name wie „Handy von Max“ hat dort nichts verloren)."""
    return f"{channel['id']} ({TYPE_LABELS.get(channel['type'], channel['type'])})"


class _Sender:
    """Warteschlange und Thread eines Kanals."""

    def __init__(self, notifier: "Notifier", channel: dict) -> None:
        self.notifier = notifier
        self.channel = channel
        self.queue: deque = deque()
        self.cond = threading.Condition()
        self.sent_times: deque = deque()
        self.stopped = False
        self.limit_noted = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"notify-{channel['id']}")
        self.thread.start()

    def put(self, msg: dict) -> None:
        with self.cond:
            if len(self.queue) >= QUEUE_MAX:
                self.queue.popleft()
                _record(self.channel["id"], True, dropped=1, attempt=False)
            msg.setdefault("attempt", 0)
            msg.setdefault("due", 0.0)
            self.queue.append(msg)
            self.cond.notify()

    def stop(self) -> None:
        with self.cond:
            self.stopped = True
            self.cond.notify()

    def _next(self) -> dict | None:
        with self.cond:
            while not self.stopped:
                now = time.monotonic()
                due = [m for m in self.queue if m["due"] <= now]
                if due:
                    msg = due[0]
                    self.queue.remove(msg)
                    return msg
                wait = min((m["due"] for m in self.queue), default=now + 60) - now
                self.cond.wait(timeout=max(0.05, min(wait, 60)))
            return None

    def _rate_ok(self) -> bool:
        now = time.monotonic()
        while self.sent_times and now - self.sent_times[0] > 3600:
            self.sent_times.popleft()
        return len(self.sent_times) < int(self.channel.get("rate_per_hour") or DEFAULT_RATE_PER_HOUR)

    def _run(self) -> None:
        while True:
            msg = self._next()
            if msg is None:
                return
            channel = self.channel
            if not msg.get("attempt") and not self._rate_ok():
                _record(channel["id"], True, dropped=1, attempt=False)
                if time.monotonic() - self.limit_noted > 3600:
                    self.limit_noted = time.monotonic()
                    events.emit("notify", "warn", f"Benachrichtigungen über Kanal {_label(channel)} gedrosselt: "
                                f"mehr als {channel['rate_per_hour']} je Stunde",
                                {"channel": channel["id"], "reason": "rate"})
                continue
            try:
                clean = outgoing(msg)
            except egress.NotifyLeak as exc:
                _record(channel["id"], False, str(exc))
                events.emit("notify", "warn", f"Benachrichtigung über Kanal {_label(channel)} zurückgehalten: {exc}",
                            {"channel": channel["id"], "reason": "filter"})
                continue
            if not msg.get("attempt"):
                self.sent_times.append(time.monotonic())
            try:
                self.notifier.deliver(channel, clean)
            except DeliveryError as exc:
                _record(channel["id"], False, str(exc))
                attempt = int(msg.get("attempt", 0))
                if attempt < len(RETRY_DELAYS) and not self.stopped:
                    msg["attempt"] = attempt + 1
                    msg["due"] = time.monotonic() + RETRY_DELAYS[attempt]
                    with self.cond:
                        self.queue.append(msg)
                else:
                    _record(channel["id"], True, dropped=1, attempt=False)
                    events.emit("notify", "warn", f"Benachrichtigung über Kanal {_label(channel)} verworfen "
                                f"nach {len(RETRY_DELAYS) + 1} Versuchen: {exc}",
                                {"channel": channel["id"], "reason": "retries"})
                continue
            _record(channel["id"], True)

    def queued(self) -> int:
        with self.cond:
            return len(self.queue)


class Notifier:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.wake_event = threading.Event()
        self.routers: dict[str, ChannelRouter] = {}
        self.senders: dict[str, _Sender] = {}
        self.thread: threading.Thread | None = None
        self.last_id = 0
        self.saved_id = 0
        self.saved_at = 0.0
        self.version = ""
        self.deliver_fn = deliver
        self._dirty = True
        self.batch_full = False
        self.stopped = False

    # --- Steuerung -------------------------------------------------------------
    def start(self, version: str = "") -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.version = version
            events.add_listener(self.wake)
            self.thread = threading.Thread(target=self._run, daemon=True, name="notify-router")
            self.thread.start()

    def wake(self) -> None:
        self.wake_event.set()

    def stop(self) -> None:
        """Router und Sender beenden (Tests, Herunterfahren)."""
        self.stopped = True
        self.wake_event.set()
        with self.lock:
            for sender in self.senders.values():
                sender.stop()

    def reload(self) -> None:
        self._dirty = True
        self.wake_event.set()

    def deliver(self, channel: dict, clean: dict) -> None:
        self.deliver_fn(channel, clean, self.version)

    def queued(self, channel_id: str) -> int:
        sender = self.senders.get(channel_id)
        return sender.queued() if sender else 0

    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    # --- Kanäle --------------------------------------------------------------
    def _sync_channels(self) -> None:
        try:
            channels = [c for c in _load_all() if c["enabled"]]
        except Exception:
            return
        with self.lock:
            wanted = {c["id"]: c for c in channels}
            for cid in list(self.senders):
                if cid not in wanted:
                    self.senders.pop(cid).stop()
                    self.routers.pop(cid, None)
            for cid, channel in wanted.items():
                if cid in self.senders:
                    self.senders[cid].channel = channel
                    self.routers[cid].configure(channel)
                else:
                    self.routers[cid] = ChannelRouter(channel)
                    self.senders[cid] = _Sender(self, channel)
            self._dirty = False

    # --- Ereignisse ------------------------------------------------------------
    def _load_position(self) -> None:
        try:
            _ensure()
            rows = store.query("SELECT value FROM notify_meta WHERE key='last_id'")
            saved = int(rows[0][0]) if rows else None
        except Exception:
            saved = None
        current = events.max_id()
        self.last_id = current if saved is None or saved > current else saved
        self.saved_id = self.last_id

    def _save_position(self, force: bool = False) -> None:
        if self.last_id == self.saved_id or (not force and time.monotonic() - self.saved_at < 10):
            return
        try:
            store.execute("INSERT INTO notify_meta(key, value) VALUES('last_id', ?) ON CONFLICT(key) "
                          "DO UPDATE SET value=excluded.value", (str(self.last_id),))
            self.saved_id, self.saved_at = self.last_id, time.monotonic()
        except Exception:
            pass

    def process(self, now: float | None = None) -> int:
        """Ein Durchgang: neue Ereignisse verteilen, Zurückgehaltenes nachholen. Gibt die Zahl Meldungen zurück
        (self.batch_full sagt, ob noch mehr Ereignisse warten)."""
        if self._dirty:
            self._sync_channels()
        now = time.time() if now is None else now
        count = 0
        batch = events.after_id(self.last_id, BATCH)
        self.batch_full = len(batch) >= BATCH
        with self.lock:
            routers = list(self.routers.items())
        for event in batch:
            self.last_id = max(self.last_id, int(event["id"]))
            if now - float(event.get("t") or now) > BACKLOG_SECONDS:
                continue  # zu alt (z. B. nach einem Neustart) – nicht nachträglich alarmieren
            for cid, router in routers:
                for msg in router.offer(event):
                    self.senders[cid].put(msg)
                    count += 1
        for cid, router in routers:
            for msg in router.tick():
                self.senders[cid].put(msg)
                count += 1
        self._save_position()
        return count

    def _run(self) -> None:
        self._load_position()
        while not self.stopped:
            self.wake_event.wait(POLL_SECONDS)
            self.wake_event.clear()
            if self.stopped:
                return
            try:
                self.process()
                while self.batch_full:
                    self.process()
            except Exception as exc:  # nie sterben: Benachrichtigungen sind nie kritisch
                print(f"[notify] Fehler im Verteiler: {type(exc).__name__}", flush=True)


NOTIFIER = Notifier()


def start(version: str = "") -> None:
    NOTIFIER.start(version)


def send_test(channel_id: str) -> dict:
    """Testnachricht sofort und ohne Wiederholung senden (Knopf im Dashboard)."""
    channel = get_channel(str(channel_id or ""))
    if channel is None:
        raise NotifyError("Diesen Kanal gibt es nicht (mehr)")
    msg = {"title": "Testnachricht von ntp-gui", "level": "info", "kind": "notify", "time": time.time(),
           "test": True}
    try:
        clean = outgoing(msg)
        NOTIFIER.deliver(channel, clean)
    except (DeliveryError, egress.NotifyLeak) as exc:
        _record(channel["id"], False, str(exc))
        return {"ok": False, "error": str(exc), "status": status_of(get_channel(channel["id"]) or channel)}
    _record(channel["id"], True)
    return {"ok": True, "status": status_of(get_channel(channel["id"]) or channel)}


def api_config() -> dict:
    """GET /api/notify (nur Verwaltungsrecht): Kanäle maskiert + Auswahllisten."""
    try:
        link = settings.values().get("notify_dashboard_url") or ""
    except Exception:
        link = ""
    return {
        "channels": list_channels(),
        "types": [{"value": t, "label": TYPE_LABELS[t]} for t in CHANNEL_TYPES],
        "levels": [{"value": lv, "label": LEVEL_LABELS[lv]} for lv in LEVELS],
        "kinds": [{"value": k, "label": KIND_LABELS.get(k, k)} for k in events.KINDS if k != "notify"],
        "defaults": {"min_level": "warn", "debounce_min": DEFAULT_DEBOUNCE_MIN,
                     "rate_per_hour": DEFAULT_RATE_PER_HOUR, "resolved": True},
        "limits": {"channels": MAX_CHANNELS, "retry_seconds": list(RETRY_DELAYS), "timeout": TIMEOUT},
        "dashboard_url": link,
        "running": NOTIFIER.running(),
    }


def api_status() -> dict:
    """GET /api/notify/status (Leserecht): nur Name, Art und Zustellstand – keine Adressen, keine Tokens."""
    out = []
    try:
        rows = _load_all()
    except Exception:
        rows = []
    for channel in rows:
        out.append({"id": channel["id"], "name": channel["name"], "type": channel["type"],
                    "enabled": channel["enabled"], "status": status_of(channel, NOTIFIER.queued(channel["id"]))})
    return {"channels": out, "running": NOTIFIER.running()}


# Für Tests: Zustand zurücksetzen.
def _reset_for_tests() -> None:
    global NOTIFIER
    NOTIFIER.stop()
    events._LISTENERS[:] = [cb for cb in events._LISTENERS if cb != NOTIFIER.wake]
    NOTIFIER = Notifier()
    _READY["db"] = None
    _KNOWN["t"] = 0.0
