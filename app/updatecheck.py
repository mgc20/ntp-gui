"""Update-Hinweis (opt-in, Standard aus): gibt es eine neuere ntp-gui-Version?

Eingeschaltet fragt ntp-gui **höchstens einmal am Tag** zu einer zufälligen Uhrzeit
``GET https://api.github.com/repos/mgc20/ntp-gui/releases/latest`` – mit dem festen
User-Agent ``ntp-gui`` ohne Version und Kennung (egress.update_check_request, Zweck
„update_check“). Der Vergleich mit der eigenen Version passiert lokal. Ergebnis: ein
Hinweis „Neue Version x.y.z verfügbar“ mit Link zum Release und – wenn der Release-Text
„BREAKING“ oder „Achtung“ enthält – der Markierung „Achtung beim Update“.

Bewusst nicht:

* kein Download, kein automatisches Update. Wer das automatisieren will, nimmt Diun
  oder What's up Docker (WUD) – nicht Watchtower (seit 17.12.2025 archiviert);
* keine Weiterleitungen (eigener Handler), keine Proxys aus der Umgebung, Timeout 10 s,
  Antwort höchstens 512 KiB;
* keine Links oder Texte ungeprüft aus der Antwort: Der Link zum Release wird aus der
  geprüften Versionsnummer gebaut, Titel und Hinweiszeile werden gekürzt und von
  Steuerzeichen befreit (das Dashboard zeigt sie ohnehin nur als Text).

Datenschutz ehrlich: GitHub sieht dabei einmal am Tag die öffentliche IP-Adresse
(grob ortbar per GeoIP) und dass dort vermutlich ntp-gui läuft. Das lässt sich
technisch nicht vermeiden – darum ist der Hinweis aus, bis du ihn einschaltest.

Ausgeschaltet: kein Thread-Zugriff aufs Netz, keine DNS-Abfrage, nichts
(Test: tests/test_updatecheck.py mit Socket-Attrappe).
"""

from __future__ import annotations

import calendar
import http.client
import json
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

import egress

DAY = 86400
TICK = 60.0
TIMEOUT = 10.0
# Obergrenze für die ganze Anfrage (DNS + Verbindung + TLS + Lesen). TIMEOUT gilt je Socket-Schritt,
# getaddrinfo() hat gar keinen – ein toter DNS-Server hielte den Abruf sonst beliebig lange auf.
DEADLINE = 20.0
MAX_RESPONSE = 512 * 1024
MAX_TITLE = 120
MAX_NOTE = 300
REPO_URL = "https://github.com/mgc20/ntp-gui"
RELEASES_URL = REPO_URL + "/releases"
CHANGELOG_URL = REPO_URL + "/blob/main/CHANGELOG.md"
# Markierung im Release-Text für „Achtung beim Update“ (Umbenennungen, Handarbeit nötig …).
MARKER_RE = re.compile(r"\bBREAKING\b|\b[Aa]chtung\b|⚠")
_VERSION_RE = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z.-]{1,40}))?$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_MARKDOWN_RE = re.compile(r"[*_`#>]+")

AUTOMATION_NOTE = ("Automatisch aktualisieren kann ntp-gui sich nicht – mit Absicht. Wer das will, nimmt "
                   "Diun (meldet neue Images) oder What's up Docker (WUD); Watchtower ist seit Dezember 2025 "
                   "archiviert.")


class UpdateError(Exception):
    """Prüfung gescheitert – kurzer deutscher Text ohne Adresse."""


# ---------------------------------------------------------------------------
# Versionen und Antwort
# ---------------------------------------------------------------------------

def parse_version(text: Any) -> tuple | None:
    """'1.4.0', 'v1.4.0', '1.4.0-rc.1' → Vergleichsschlüssel (SemVer-Reihenfolge), sonst None."""
    match = _VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    if pre is None:
        return int(major), int(minor), int(patch), 1, ()
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return int(major), int(minor), int(patch), 0, parts


def plain_version(text: Any) -> str | None:
    """Geprüfte Versionsnummer ohne führendes v (nur Ziffern, Punkte, Bindestrich-Zusatz)."""
    text = str(text or "").strip()
    return text[1:] if text[:1] == "v" and parse_version(text) else (text if parse_version(text) else None)


def is_newer(latest: Any, current: Any) -> bool | None:
    """True, wenn latest neuer als current ist; None, wenn eine der beiden keine Version ist."""
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return None
    return a > b


def _clean_text(value: Any, limit: int) -> str:
    text = _CONTROL_RE.sub(" ", str(value or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _published(value: Any) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError, OverflowError):
        return None


def attention_note(body: str) -> str | None:
    """Erste Zeile des Release-Texts mit Markierung – gekürzt, ohne Markdown-Zeichen."""
    for line in str(body or "").splitlines():
        if MARKER_RE.search(line):
            note = _clean_text(_MARKDOWN_RE.sub("", line), MAX_NOTE)
            return note or "Achtung beim Update"
    return None


def parse_release(raw: bytes) -> dict:
    """Antwort von /releases/latest → geprüfte Felder. Wirft UpdateError."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise UpdateError("Antwort von GitHub ist kein gültiges JSON") from None
    if not isinstance(data, dict):
        raise UpdateError("Antwort von GitHub hat ein unerwartetes Format")
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("GitHub meldet eine Vorabversion als neueste – wird ignoriert")
    version = plain_version(data.get("tag_name"))
    if not version:
        raise UpdateError("Release ohne gültige Versionsnummer")
    body = data.get("body") if isinstance(data.get("body"), str) else ""
    body = body[:200_000]
    note = attention_note(body)
    title = _clean_text(data.get("name"), MAX_TITLE) or f"ntp-gui {version}"
    return {
        "version": version,
        "title": title,
        # Nie den Link aus der Antwort übernehmen: aus der geprüften Version gebaut.
        "url": f"{RELEASES_URL}/tag/v{version}",
        "published": _published(data.get("published_at")),
        "attention": note is not None,
        "attention_note": note,
    }


# ---------------------------------------------------------------------------
# Netz
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen nie folgen – sonst ginge die Anfrage still an ein anderes Ziel."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise UpdateError(f"Weiterleitung abgelehnt (HTTP {code})")


def _opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    opener.addheaders = []  # kein „Python-urllib/3.x“ – nur die festen Kopfzeilen aus egress
    for handler in (urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect(),
                    urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener  # ohne ProxyHandler, HTTPHandler (nur https), FileHandler, FTPHandler, DataHandler


def _describe(exc: BaseException) -> str:
    if isinstance(exc, UpdateError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403 or exc.code == 429:
            return f"GitHub begrenzt gerade die Anfragen (HTTP {exc.code}) – morgen klappt es wieder"
        if exc.code == 404:
            return "GitHub kennt (noch) kein Release (HTTP 404)"
        return f"GitHub antwortet mit HTTP {exc.code}"
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return f"Zeitüberschreitung ({int(TIMEOUT)} s)"
    if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError):
        return "TLS-Fehler (Zertifikat nicht vertrauenswürdig – Systemzeit oder CA-Zertifikate prüfen)"
    if isinstance(reason, socket.gaierror):
        return "api.github.com nicht auflösbar – DNS prüfen"
    if isinstance(reason, OSError):
        return "GitHub nicht erreichbar – Internetzugang des Containers prüfen"
    if isinstance(exc, http.client.HTTPException):
        return "Ungültige Antwort von GitHub"
    return "Prüfung fehlgeschlagen"


def fetch(opener=None) -> bytes:
    """Die eine Anfrage – feste URL und Kopfzeilen aus egress. Wirft UpdateError."""
    url, headers = egress.update_check_request()
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with (opener or _opener()).open(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE + 1)
            code = getattr(response, "status", 200)
    except UpdateError:
        raise
    except Exception as exc:  # noqa: BLE001 – alles wird zu einer kurzen Meldung
        raise UpdateError(_describe(exc)) from None
    if not 200 <= code < 300:
        raise UpdateError(f"GitHub antwortet mit HTTP {code}")
    if len(raw) > MAX_RESPONSE:
        raise UpdateError("Antwort von GitHub ist zu groß")
    return raw


# ---------------------------------------------------------------------------
# Zustand (SQLite) und Zeitplan
# ---------------------------------------------------------------------------

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS update_check (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)",
]


class Store:
    """Ein JSON-Datensatz in ntp-gui.db; fällt bei Fehlern auf den Arbeitsspeicher zurück."""

    def __init__(self) -> None:
        self.memory: dict = {}
        self.ready_for: str | None = None

    def load(self) -> dict:
        try:
            import store
            self._ensure(store)
            rows = store.query("SELECT data FROM update_check WHERE id=1")
            if rows:
                data = json.loads(rows[0][0])
                if isinstance(data, dict):
                    self.memory = data
        except Exception:
            pass
        return dict(self.memory)

    def save(self, data: dict) -> None:
        self.memory = dict(data)
        try:
            import store
            self._ensure(store)
            store.execute("INSERT INTO update_check(id, data) VALUES(1, ?) "
                          "ON CONFLICT(id) DO UPDATE SET data=excluded.data", (json.dumps(data),))
        except Exception:
            pass

    def _ensure(self, store) -> None:
        path = store.path()
        if self.ready_for != path:
            store.migrate("update_check", _SCHEMA)
            self.ready_for = path


def _day(t: float) -> int:
    return int(t // DAY)


class Checker:
    """Zeitplan + Prüfung. tick() ist billig und fragt nur, wenn eingeschaltet und fällig."""

    def __init__(self, version: str, enabled: Callable[[], bool], *, fetcher: Callable[[], bytes] = fetch,
                 state: Store | None = None, rng: random.Random | None = None,
                 emit: Callable[..., None] | None = None, deadline: float = DEADLINE) -> None:
        self.version = version
        self.enabled = enabled
        self.fetcher = fetcher
        self.state = state or Store()
        self.rng = rng or random.SystemRandom()
        self.emit = emit
        self.deadline = deadline
        self.slots: dict[int, float] = {}
        # Schützt nur den Zustand – nie während der Netzanfrage gehalten, sonst warteten
        # /api/status und /metrics auf GitHub.
        self.lock = threading.Lock()
        self.busy = False
        self.data: dict | None = None

    def _data(self) -> dict:
        if self.data is None:
            self.data = self.state.load()
        return self.data

    def slot(self, day: int) -> float:
        """Zufällige Uhrzeit (Sekunden nach 00:00 UTC) für diesen Tag – einmal gewürfelt."""
        if day not in self.slots:
            self.slots = {d: s for d, s in self.slots.items() if d >= day - 1}
            self.slots[day] = self.rng.uniform(0, DAY - 1)
        return self.slots[day]

    def is_enabled(self) -> bool:
        try:
            return bool(self.enabled())
        except Exception:
            return False

    def next_check(self, now: float) -> float | None:
        if not self.is_enabled():
            return None
        today = _day(now)
        last = self._data().get("last_attempt")
        day = today + 1 if isinstance(last, (int, float)) and _day(last) >= today else today
        return max(now, day * DAY + self.slot(day))

    def due(self, now: float) -> bool:
        if not self.is_enabled():
            return False
        last = self._data().get("last_attempt")
        today = _day(now)
        if isinstance(last, (int, float)) and _day(last) >= today:
            return False  # heute schon gefragt (auch bei Fehler: höchstens eine Anfrage am Tag)
        return now >= today * DAY + self.slot(today)

    def tick(self, now: float | None = None) -> bool:
        """Prüft, wenn fällig. True, wenn eine Anfrage gestellt wurde."""
        now = time.time() if now is None else now
        with self.lock:
            if self.busy or not self.due(now):
                return False
            self.busy = True
        try:
            self.check(now)
        finally:
            with self.lock:
                self.busy = False
        return True

    def _fetch(self) -> bytes:
        """fetcher() mit Gesamtfrist: läuft in einem eigenen Thread; hängt er, wird er aufgegeben."""
        box: dict = {}

        def work() -> None:
            try:
                box["raw"] = self.fetcher()
            except BaseException as exc:  # noqa: BLE001 – wird im aufrufenden Thread ausgewertet
                box["exc"] = exc

        worker = threading.Thread(target=work, daemon=True, name="update-fetch")
        worker.start()
        worker.join(self.deadline)
        if worker.is_alive():
            raise UpdateError(f"Zeitüberschreitung ({int(self.deadline)} s) – GitHub antwortet nicht rechtzeitig")
        if "exc" in box:
            raise box["exc"]
        return box["raw"]

    def check(self, now: float) -> dict:
        # 1. Versuch vermerken (kurz unter der Sperre) – auch ein Absturz zählt als „heute gefragt“.
        with self.lock:
            data = self._data()
            data["last_attempt"] = now
            self.state.save(data)
        # 2. Netz ohne Sperre.
        latest = None
        error = None
        try:
            latest = parse_release(self._fetch())
        except UpdateError as exc:
            error = str(exc)
        except Exception:  # noqa: BLE001 – nie den Thread verlieren
            error = "Prüfung fehlgeschlagen"
        # 3. Ergebnis speichern (kurz unter der Sperre), Ereignis danach.
        event = None
        with self.lock:
            data = self._data()
            if latest is None:
                data["error"] = error
            else:
                data.update(error=None, last_success=now, latest=latest)
                newer = is_newer(latest["version"], self.version)
                if newer and data.get("announced") != latest["version"]:
                    data["announced"] = latest["version"]
                    event = latest
            self.state.save(data)
            result = dict(data)
        if event and self.emit:
            # Eigene Art „update“ mit Betreff je Version: kein offenes Problem, das ein späteres
            # Ereignis „beheben“ oder unterdrücken könnte (notify.STANDALONE_KINDS).
            self.emit("update", "warn" if event["attention"] else "info",
                      f"Neue Version {event['version']} verfügbar"
                      + (" – Achtung beim Update" if event["attention"] else ""),
                      {"subject": f"update:{event['version']}", "resolves": False,
                       "version": event["version"], "current": self.version}, "update")
        return result

    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self.lock:
            data = dict(self._data())
            enabled = self.is_enabled()
            latest = data.get("latest") if isinstance(data.get("latest"), dict) else None
            newer = is_newer(latest["version"], self.version) if latest else None
            return {
                "enabled": enabled,
                "current": self.version,
                "current_valid": parse_version(self.version) is not None,
                "latest": latest if enabled else None,
                "available": bool(enabled and newer),
                "attention": bool(enabled and newer and latest and latest.get("attention")),
                "last_attempt": data.get("last_attempt") if enabled else None,
                "last_success": data.get("last_success") if enabled else None,
                "error": data.get("error") if enabled else None,
                "next_check": self.next_check(now),
                "releases_url": RELEASES_URL,
                "changelog_url": CHANGELOG_URL,
                "automation": AUTOMATION_NOTE,
            }


def insights(status: dict) -> list[dict]:
    """Hinweis für die Übersicht – nur, wenn eingeschaltet und wirklich neuer."""
    if not status.get("available"):
        return []
    latest = status.get("latest") or {}
    version = latest.get("version", "?")
    text = (f"Installiert ist {status.get('current')}, auf GitHub gibt es {version} („{latest.get('title', '')}“). "
            "Was neu ist, steht im Changelog und im Release. ")
    if latest.get("attention"):
        text += (f"Achtung beim Update: {latest.get('attention_note') or 'der Release-Text nennt Punkte, die du vorher lesen solltest'}. "
                 "Lies die Release-Notizen, bevor du das Image tauschst. ")
    text += ("Aktualisieren: neues Image ziehen und den Container neu erstellen (docker compose pull && docker compose up -d) – "
             "Einstellungen und Verlauf liegen im Volume. " + AUTOMATION_NOTE)
    return [{
        # Immer „info“: Ein Update ändert nichts an der Zeit – die Ampel und das Zählbadge bleiben ruhig.
        "level": "info",
        "key": "update_available",
        "title": f"Neue Version {version} verfügbar" + (" – Achtung beim Update" if latest.get("attention") else ""),
        "text": text,
        "action": "settings",
        "link": latest.get("url") or RELEASES_URL,
    }]


# ---------------------------------------------------------------------------
# Thread
# ---------------------------------------------------------------------------

CHECKER: Checker | None = None
_START_LOCK = threading.Lock()


def _enabled_from_settings() -> bool:
    import settings
    return bool(settings.values().get("update_check"))


def _emit(*args) -> None:
    try:
        import events
        events.emit(*args)
    except Exception:
        pass


def checker(version: str = "") -> Checker:
    global CHECKER
    with _START_LOCK:
        if CHECKER is None:
            CHECKER = Checker(version, _enabled_from_settings, emit=_emit)
        elif version:
            CHECKER.version = version
        return CHECKER


def run(check: Checker, stop: threading.Event | None = None, interval: float = TICK) -> None:
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            check.tick()
        except Exception as exc:  # nie den Thread verlieren
            print(f"[web] Update-Hinweis nicht geprüft: {exc}", flush=True)
        stop.wait(interval)


def start(version: str) -> threading.Thread:
    """Thread starten. Ausgeschaltet prüft er nur einmal pro Minute die Einstellung – ohne Netz."""
    thread = threading.Thread(target=run, args=(checker(version),), daemon=True, name="update-check")
    thread.start()
    return thread


def status() -> dict:
    return checker().status()
