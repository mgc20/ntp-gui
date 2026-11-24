"""Zeitwächter-Ping (opt-in, Standard aus): ein Lebenszeichen an einen eigenen Wächter.

ntp-gui kann seinen eigenen Ausfall nicht melden – ist der Rechner weg, schweigen auch die
Benachrichtigungen. Ein Wächter von außen (Healthchecks, Uptime Kuma mit Monitor-Typ „Push“) merkt
es trotzdem: Er erwartet regelmäßig eine Anfrage und schlägt Alarm, wenn sie ausbleibt.

Eingeschaltet (Einstellung heartbeat_url gesetzt) schickt ntp-gui alle heartbeat_interval Sekunden

* bei gutem Zustand ``GET <url>`` und
* bei kritischem Zustand (ein Hinweis der Stufe „kritisch“ in der Übersicht, z. B. chronyd antwortet
  nicht) je nach Art (heartbeat_mode): Healthchecks ``GET <url>/fail``, Uptime Kuma
  ``GET <url>?status=down&msg=kritisch``, „silent“ gar nichts.

„Kritisch“ gilt erst, wenn der Zustand mindestens DOWN_HOLD Sekunden anhält (zwei Auswertungen im
Abstand von DOWN_HOLD). Ein kurzer roter Hinweis – Neuladen der Zeitdienste nach einer Einstellung,
Dienst-Neustart, Start des Containers – meldet so noch kein „ausgefallen“; bis dahin geht weiter „gut“
hinaus. Hält er an, wird die zweite Auswertung vorgezogen (nicht erst beim nächsten Intervall).

Die Anfrage baut egress.heartbeat_request (Zweck „heartbeat“, leere Feldliste): kein Body, nur der
User-Agent „ntp-gui“ ohne Version. Gesendet wird wie bei den Benachrichtigungen: Zielprüfung nach der
Namensauflösung (netguard), keine Weiterleitungen, keine Proxys aus der Umgebung, Gesamtfrist TIMEOUT,
Antwort höchstens MAX_RESPONSE Byte. Eine Adresse mit Pfad oder Abfrage (dort steckt der Schlüssel des
Wächters) geht über http:// nur an Adressen im eigenen Netz.

Ohne Adresse: keine Verbindung, keine DNS-Abfrage (tests/test_heartbeat.py mit Socket-Attrappe).
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import egress
import notify
import settings
import textsafe

TIMEOUT = 5.0                 # Sekunden für alles: Namensauflösung, Verbindung, TLS, Antwort
MAX_RESPONSE = 4096
DEFAULT_INTERVAL = 60
MIN_INTERVAL = 30
MAX_INTERVAL = 3600
TICK = 2.0
FAIL_EVENT_AFTER = 3          # so viele Fehlschläge hintereinander, dann ein Ereignis (nicht bei jedem)
TEST_GAP = 10.0               # „Jetzt senden“ höchstens alle 10 s
DOWN_HOLD = 120.0             # so lange muss „kritisch“ anhalten, bevor der Ping es meldet
MODE_LABELS = {"auto": "automatisch erkennen", "healthchecks": "Healthchecks (…/fail)",
               "kuma": "Uptime Kuma Push (?status=down)", "silent": "nur Lebenszeichen (bei kritisch schweigen)"}


class PingError(Exception):
    """Ping gescheitert – kurzer deutscher Text ohne Adresse."""


class TestRateLimited(Exception):
    """„Jetzt senden“ zu schnell hintereinander."""


class TestBusy(Exception):
    """„Jetzt senden“, während gerade ein Ping unterwegs ist – dieser Klick hat nichts gesendet."""


# ---------------------------------------------------------------------------
# Eingabe prüfen (Einstellung heartbeat_url)
# ---------------------------------------------------------------------------

def validate_url(text: Any) -> str:
    """Leer (aus) oder eine erlaubte Wächter-Adresse. Wirft ValueError mit kurzer Begründung."""
    url = str(text if text is not None else "").strip()
    if not url:
        return ""
    if not settings.http_url_ok(url, max_len=400):
        raise ValueError("http:// oder https:// mit Hostname bzw. IP, ohne Leerzeichen und ohne Benutzer/Passwort, "
                         "z. B. https://hc-ping.com/<uuid> oder http://kuma.lan:3001/api/push/<token>")
    blocked = notify._blocked_literal(url)
    if blocked:
        raise ValueError(blocked)
    scheme, host, _port = notify._origin(url)
    if scheme == "http" and notify.url_hidden(url) and not notify.local_host(host):
        raise ValueError("Über http:// nur an eine Adresse im eigenen Netz (z. B. http://kuma.lan:3001/…) – in "
                         "der Adresse steckt der Schlüssel deines Wächters. Sonst bitte https:// verwenden.")
    return url


def mask_url(url: str) -> str:
    """Adresse für Anzeige und Lesezugriff: Schema, Host und Port – Pfad und Abfrage nur als „/…“."""
    try:
        return notify.display_url(str(url or "")) if url else ""
    except ValueError:
        return "…"


# ---------------------------------------------------------------------------
# Senden
# ---------------------------------------------------------------------------

def _timeout_text(seconds: float) -> str:
    return f"Zeitüberschreitung ({int(seconds)} s)"


def _describe(exc: BaseException) -> str:
    text = notify._describe(exc)
    return text.replace("Token prüfen", "Adresse des Wächters prüfen") if text.endswith("Token prüfen") else text


def send(base_url: str, state: str, mode: str = "auto", timeout: float = TIMEOUT) -> str | None:
    """Eine Anfrage an den Wächter. Gibt zurück, was gesendet wurde („up“, „fail“) oder None (nichts zu
    senden). Wirft PingError (kurz, deutsch, ohne Adresse)."""
    try:
        built = egress.heartbeat_request(base_url, state, mode)
    except egress.HeartbeatRejected as exc:
        raise PingError(str(exc)) from None
    if built is None:
        return None
    url, headers = built
    if not settings.http_url_ok(url, max_len=420):
        raise PingError("Adresse ungültig")
    blocked = notify._blocked_literal(url)
    if blocked:
        raise PingError(blocked)
    plain_secret = urllib.parse.urlsplit(url).scheme.lower() == "http" and notify.url_hidden(url)
    deadline = notify._Deadline(timeout, local_only=plain_secret)
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = notify._opener(deadline)
    opener.addheaders = []  # kein „Python-urllib/3.x“
    try:
        with opener.open(request, timeout=timeout) as response:
            code = getattr(response, "status", 200)
            got = 0
            while got < MAX_RESPONSE and not deadline.fired:  # begrenzt lesen, Inhalt wird nicht gebraucht
                chunk = response.read(min(1024, MAX_RESPONSE - got))
                if not chunk:
                    break
                got += len(chunk)
        if deadline.fired:
            raise PingError(_timeout_text(timeout))
    except PingError:
        raise
    except (notify.DeliveryError, urllib.error.URLError) as exc:
        reason = exc if isinstance(exc, notify.DeliveryError) else getattr(exc, "reason", None)
        if not isinstance(reason, notify.DeliveryError):
            deadline_text = _timeout_text(timeout) if deadline.fired else _describe(exc)
            raise PingError(deadline_text) from None
        text = str(reason)
        if text.startswith("Token über http://"):
            text = ("Über http:// geht die Wächter-Adresse nur an Adressen im eigenen Netz – dieser Name zeigt "
                    "nicht ins eigene Netz. Bitte https:// verwenden.")
        raise PingError(text) from None
    except Exception as exc:  # noqa: BLE001 – alles wird zu einer kurzen Meldung
        raise PingError(_timeout_text(timeout) if deadline.fired else _describe(exc)) from None
    finally:
        deadline.close()
    if not 200 <= code < 300:
        raise PingError(f"Wächter antwortet mit HTTP {code}")
    return "fail" if state == "down" else "up"


# ---------------------------------------------------------------------------
# Zeitplan und Zustand
# ---------------------------------------------------------------------------

def config_from_settings() -> dict:
    values = settings.values()
    return {"url": str(values.get("heartbeat_url") or ""),
            "interval": values.get("heartbeat_interval", DEFAULT_INTERVAL),
            "mode": str(values.get("heartbeat_mode") or "auto")}


class Pinger:
    """Takt + Ergebnis. tick() ist billig: ohne Adresse oder vor Ablauf des Intervalls passiert nichts."""

    def __init__(self, config: Callable[[], dict] = config_from_settings,
                 state: Callable[[], str] | None = None, *, sender: Callable[..., str | None] = send,
                 emit: Callable[..., None] | None = None, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self.config = config
        self.state = state or (lambda: "up")
        self.sender = sender
        self.emit = emit
        self.clock = clock
        self.wall = wall
        self.lock = threading.Lock()
        self.busy = False
        self.target: tuple | None = None   # (url, mode) des letzten Versuchs – Wechsel = neu anfangen
        self.last_mono: float | None = None
        self.last_test: float | None = None
        self.crit_since: float | None = None  # seit wann (monotonic) die Auswertung ununterbrochen „kritisch“ ist
        self.result: dict = self._blank()

    @staticmethod
    def _blank() -> dict:
        return {"last_attempt": None, "last_ok": None, "last_state": None, "last_sent": None,
                "error": None, "failures": 0, "alarmed": False, "held": False}

    def _config(self) -> dict | None:
        try:
            cfg = self.config()
        except Exception:
            return None
        url = str(cfg.get("url") or "").strip()
        if not url:
            return None
        try:
            interval = int(cfg.get("interval") or DEFAULT_INTERVAL)
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        mode = cfg.get("mode") if cfg.get("mode") in egress.HEARTBEAT_MODES else "auto"
        return {"url": url, "interval": min(MAX_INTERVAL, max(MIN_INTERVAL, interval)), "mode": mode}

    def _current_state(self) -> str:
        try:
            value = self.state()
        except Exception:  # Zustand nicht ermittelbar: lieber „kritisch“ melden als still „gut“
            return "down"
        return value if value in egress.HEARTBEAT_STATES else "down"

    def _held_state(self) -> tuple[str, bool]:
        """Zustand mit Haltezeit: „down“ erst nach DOWN_HOLD s ununterbrochen kritisch. (Zustand, zurückgehalten)"""
        raw = self._current_state()
        now = self.clock()
        with self.lock:
            if raw != "down":
                self.crit_since = None
                return raw, False
            if self.crit_since is None:
                self.crit_since = now
            if now - self.crit_since >= DOWN_HOLD:
                return "down", False
            return "up", True

    def due(self, cfg: dict | None = None) -> bool:
        cfg = self._config() if cfg is None else cfg
        if cfg is None:
            return False
        if self.target != (cfg["url"], cfg["mode"]) or self.last_mono is None:
            return True
        now = self.clock()
        if self.result.get("held") and self.crit_since is not None and now - self.crit_since >= DOWN_HOLD:
            return True  # kritisch hält an: jetzt nachprüfen, nicht erst beim nächsten Intervall
        return now - self.last_mono >= cfg["interval"]

    def tick(self, force: bool = False) -> bool:
        """Pingt, wenn eingeschaltet und fällig (force: sofort). True, wenn eine Anfrage versucht wurde."""
        cfg = self._config()
        with self.lock:
            if cfg is None:
                if self.target is not None:
                    self.target, self.last_mono, self.result = None, None, self._blank()
                    self.crit_since = None
                return False
            if self.busy or not (force or self.due(cfg)):
                return False
            if self.target != (cfg["url"], cfg["mode"]):
                self.result = self._blank()  # neue Adresse: alter Fehlerzähler gilt nicht mehr
            self.target = (cfg["url"], cfg["mode"])
            self.last_mono = self.clock()
            self.busy = True
        try:
            self._run(cfg)
        finally:
            with self.lock:
                self.busy = False
        return True

    def _run(self, cfg: dict) -> None:
        state, held = self._held_state()
        now = self.wall()
        error, sent = None, None
        try:
            sent = self.sender(cfg["url"], state, cfg["mode"])
        except PingError as exc:
            error = textsafe.clean(exc, 200)
        except Exception:  # noqa: BLE001 – nie den Thread verlieren
            error = "Ping fehlgeschlagen"
        event = None
        with self.lock:
            res = self.result
            res.update(last_attempt=now, last_state=state, last_sent=sent, error=error, held=held)
            if error is None and sent is None:
                pass  # nichts gesendet („nur Lebenszeichen“ bei kritisch): kein Erfolg, kein Fehlschlag
            elif error is None:
                res["last_ok"] = now
                if res["alarmed"]:
                    event = ("info", "Zeitwächter wieder erreichbar", True)
                res.update(failures=0, alarmed=False)
            else:
                res["failures"] += 1
                if res["failures"] >= FAIL_EVENT_AFTER and not res["alarmed"]:
                    res["alarmed"] = True
                    event = ("warn", f"Zeitwächter nicht erreichbar: {error}", False)
        if event and self.emit:
            level, title, resolves = event
            # Betreff fest, nie die Adresse (sie enthält den Schlüssel des Wächters).
            self.emit("heartbeat", level, title, {"subject": "heartbeat", "resolves": resolves}, "heartbeat")

    def test(self) -> dict:
        """„Jetzt senden“ im Dashboard: sofort ein Ping mit dem echten Zustand (gebremst)."""
        if self._config() is None:
            raise PingError("Keine Wächter-Adresse eingetragen")
        now = self.clock()
        with self.lock:
            if self.last_test is not None and now - self.last_test < TEST_GAP:
                raise TestRateLimited(f"Bitte {int(TEST_GAP)} s warten, bevor du erneut sendest.")
            previous = self.last_test
            self.last_test = now
        if not self.tick(force=True):
            with self.lock:
                if self.last_test == now:
                    self.last_test = previous  # dieser Klick hat nichts gesendet: Bremse nicht verbrauchen
            raise TestBusy("Ein Ping läuft gerade – gleich nochmal versuchen.")
        return self.status()

    def status(self, full: bool = False) -> dict:
        """Zustand für Dashboard und API. Die Adresse nur gekürzt und nur mit full (Verwaltungsrecht)."""
        cfg = self._config()
        with self.lock:
            res = dict(self.result) if cfg is not None else self._blank()
            last = self.last_mono
        out: dict[str, Any] = {
            "enabled": cfg is not None,
            "interval": cfg["interval"] if cfg else None,
            "mode": cfg["mode"] if cfg else None,
            "flavor": egress.heartbeat_flavor(cfg["url"], cfg["mode"]) if cfg else None,
            "last_attempt": res["last_attempt"], "last_ok": res["last_ok"], "last_state": res["last_state"],
            "last_sent": res["last_sent"], "error": res["error"], "failures": res["failures"],
            "held": bool(res.get("held")),
            "next": (self.wall() + max(0.0, cfg["interval"] - (self.clock() - last)))
            if cfg and last is not None else None,
        }
        if full:
            out["url"] = mask_url(cfg["url"]) if cfg else ""
        return out


# ---------------------------------------------------------------------------
# Thread
# ---------------------------------------------------------------------------

PINGER: Pinger | None = None
_START_LOCK = threading.Lock()


def _emit(*args) -> None:
    try:
        import events
        events.emit(*args)
    except Exception:
        pass


def pinger(state: Callable[[], str] | None = None) -> Pinger:
    global PINGER
    with _START_LOCK:
        if PINGER is None:
            PINGER = Pinger(state=state, emit=_emit)
        elif state is not None:
            PINGER.state = state
        return PINGER


def run(ping: Pinger, stop: threading.Event | None = None, interval: float = TICK) -> None:
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            ping.tick()
        except Exception as exc:  # nie den Thread verlieren
            print(f"[web] Zeitwächter-Ping: {exc}", flush=True)
        stop.wait(interval)


def start(state: Callable[[], str]) -> threading.Thread:
    """Thread starten. Ohne Adresse liest er nur alle TICK s die Einstellung – ohne Netz."""
    thread = threading.Thread(target=run, args=(pinger(state),), daemon=True, name="heartbeat")
    thread.start()
    return thread


def status(full: bool = False) -> dict:
    return pinger().status(full)

