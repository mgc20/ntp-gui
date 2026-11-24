"""Neustart-Koordinator (1.12): ein Weg für alle automatischen Neustarts von chronyd.

Wer startet chronyd heute von selbst neu (Stand 1.11, geprüft im Code)?
  * autocal (GPS-Offset): höchstens eine Änderung je 24 h; ohne PPS gibt es den Schritt in einem Zug
    ohne 24-h-Pause, die nächste Änderung braucht dann aber wieder ≥ 6 h Messung.
  * gpsquality (Fehlerschranke ohne PPS): größer höchstens einmal je Stunde, kleiner höchstens alle 12 h.
  * Supervisor: erneuertes NTS-Zertifikat (alle paar Wochen) und Gerätewechsel (Hotplug) – das sind
    Ereignisse von außen, keine Regelkreise; sie bleiben im Supervisor und beachten reload.hold.
  * Nach einem Holdover-Test der zurückgestellte Neustart (holdover.reload_or_defer).
Die GPS-Sperre (gnssguard) und der Holdover-Test schalten Quellen zur Laufzeit (selectopts) und
starten chronyd nie neu. Einstellungen, Sicherung zurückspielen, „Rückgängig“ und „Auf Standard
zurücksetzen“ löst ein Mensch aus – sie laufen weiter direkt und sofort (keine Verhaltensänderung).

Jede Automatik hat eigene Pausen, aber nichts begrenzte die Summe: Wächst die Schranke bei schlechter
werdendem Empfang stündlich und korrigiert autocal dazwischen, sind mehrere Neustarts am Tag möglich –
jeder kostet chronyd den Regelzustand und Clients einige Minuten ungenauere Zeit. Darum gehen die
Automatiken jetzt hier durch:

  * Sammeln: Eine Anforderung (request) wartet COLLECT_SECONDS; was in der Zeit dazukommt, übernimmt
    derselbe Neustart.
  * Obergrenze: höchstens MAX_PER_DAY automatische Neustarts in 24 h (gleitend). Darüber wartet die
    Änderung, bis wieder einer frei ist (Ereignis „Tagesgrenze erreicht“, einmal je Wartezeit). Die
    Einstellung ist dann schon gespeichert; chronyd nutzt bis dahin die bisherige. autocal verstellt
    in der Zeit nichts weiter (es wartet, bis der Neustart belegt ist).
  * Mitgenommen: Startet chronyd inzwischen aus einem anderen Grund neu (du speicherst, Zertifikat,
    Hotplug), erzeugt der Supervisor die Konfiguration dabei neu – die wartende Änderung ist damit aktiv
    und zählt nicht zur Obergrenze. Endete jener Neustart weniger als TAKE_ALONG_MARGIN nach der
    Anforderung, könnte er die Konfiguration noch davor erzeugt haben – dann folgt sicherheitshalber
    ein eigener.
  * Holdover-Test: Auch das gesammelte Anwenden prüft holdover.reload_or_defer – läuft ein Test,
    folgt der Neustart nach dessen Ende.
Jede Entscheidung (angewandt, Tagesgrenze, mitgenommen, nicht anforderbar) ist ein Ereignis der Art
„reload“. Der Zustand steht in DATA_DIR/neustarts.json (überlebt einen Neustart von ntp-gui), in
/api/status („restarts“), auf der Übersicht (Kachel Dienste) und in /metrics.

Datenschutz: gespeichert werden nur Zeitpunkte und feste Namen der Automatiken.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any, Callable

STATE_FILE = "neustarts.json"
STATE_VERSION = 1
DAY = 86400.0
COLLECT_SECONDS = 120.0     # so lange werden Anforderungen gesammelt
MAX_PER_DAY = 4             # automatische Neustarts von chronyd in 24 h (gleitend)
RETRY_SECONDS = 600.0       # Anforderung gescheitert (kein Supervisor?): neuer Versuch nach …
CLOCK_SLACK = 300.0         # Zeitpunkte so weit in der Zukunft gelten noch (Uhr leicht zurückgestellt)
TAKE_ALONG_MARGIN = 30.0    # ein anderer Neustart nimmt die Änderung nur mit, wenn er so lange danach endete
MAX_LOG = 20                # gemerkte Neustarts (für die Anzeige „zuletzt“)

# Feste Namen – nur diese werden angenommen (keine freien Texte in Zustand, Ereignis oder Metrik).
LABELS = {
    "autocal": "GPS-Kalibrierung (Offset)",
    "gps_bound": "GPS-Fehlerschranke",
}
SCOPES = ("chronyd", "all")   # nur chronyd neu laden bzw. alle Zeitdienste


def _default_path() -> str:
    import settings
    return os.path.join(settings.DATA_DIR, STATE_FILE)


def _default_emit(kind: str, level: str, title: str, data: dict) -> None:
    import events
    events.emit(kind, level, title, data, source="neustart")


def _default_gate(trigger: Callable[[], Any]) -> bool:
    import holdover
    return holdover.reload_or_defer(trigger)


def _default_started() -> float | None:
    import gpsquality
    return gpsquality.chronyd_started()


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") else None


class Coordinator:
    """Sammelt automatische Neustart-Wünsche und wendet sie gemeinsam an (Obergrenze je Tag)."""

    def __init__(self, path: Callable[[], str] | None = None, wall: Callable[[], float] = time.time,
                 emit: Callable[..., Any] | None = None, gate: Callable[[Callable[[], Any]], bool] | None = None,
                 started: Callable[[], float | None] | None = None) -> None:
        self.lock = threading.RLock()
        self._path = path or _default_path
        self.wall = wall
        self._emit_fn = emit or _default_emit
        self._gate = gate or _default_gate
        self._started = started or _default_started
        self.triggers: dict[str, Callable[[], bool] | None] = {"chronyd": None, "all": None}
        self.last_error: str | None = None

    def configure(self, chronyd: Callable[[], bool] | None = None, full: Callable[[], bool] | None = None) -> None:
        """server.py: womit chronyd (bzw. alle Zeitdienste) wirklich neu gestartet wird."""
        self.triggers = {"chronyd": chronyd, "all": full}

    # --- Zustand ---------------------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self._path(), encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            raw = None
        state: dict[str, Any] = {"v": STATE_VERSION, "auto": [], "pending": None}
        if not isinstance(raw, dict) or raw.get("v") != STATE_VERSION:
            return state
        auto = raw.get("auto") if isinstance(raw.get("auto"), list) else []
        state["auto"] = [t for t in (_num(x) for x in auto) if t is not None][-MAX_LOG:]
        pending = raw.get("pending")
        if isinstance(pending, dict) and _num(pending.get("since")) is not None:
            who = pending.get("who") if isinstance(pending.get("who"), dict) else {}
            who = {k: (v if v in SCOPES else "chronyd") for k, v in who.items() if k in LABELS}
            if who:
                state["pending"] = {
                    "since": _num(pending.get("since")), "who": who,
                    "held": pending.get("held") if pending.get("held") in ("limit", "retry") else None,
                    "next_try": _num(pending.get("next_try")),
                }
        return state

    def _save(self, state: dict) -> None:
        file = self._path()
        folder = os.path.dirname(file) or "."
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".neustarts-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, ensure_ascii=False, sort_keys=True)
                    handle.write("\n")
                os.chmod(tmp, 0o600)
                os.replace(tmp, file)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self.last_error = None
        except OSError as exc:
            self.last_error = f"Zustand nicht gespeichert ({type(exc).__name__})"

    def _emit(self, level: str, title: str, data: dict) -> None:
        try:
            self._emit_fn("reload", level, title, data)
        except Exception:  # Ereignisse sind nie kritisch
            pass

    @staticmethod
    def _recent(auto: list[float], now: float) -> list[float]:
        """Automatische Neustarts der letzten 24 h. Liegt ein Zeitpunkt in der Zukunft (Uhr zurückgestellt,
        Pi ohne RTC), zählt er weiter mit – bis einen Tag voraus; das ist die vorsichtige Richtung."""
        return [t for t in auto if now - DAY < t <= now + DAY]

    # --- Automatiken -------------------------------------------------------------------------------
    def request(self, who: str, scope: str = "chronyd") -> bool:
        """Eine Automatik hat gespeichert und braucht einen Neustart. True = vorgemerkt (der Neustart
        folgt gesammelt). Unbekannte Namen werden abgelehnt (False)."""
        if who not in LABELS or scope not in SCOPES:
            return False
        with self.lock:
            now = self.wall()
            state = self._load()
            pending = state.get("pending")
            if not pending:
                pending = {"since": now, "who": {}, "held": None, "next_try": None}
            if pending["who"].get(who) != "all":
                pending["who"][who] = scope
            state["pending"] = pending
            self._save(state)
            return True

    def trigger_for(self, who: str, scope: str = "chronyd") -> Callable[[], bool]:
        """Als trigger_reload für eine Automatik (autocal, gpsquality)."""
        return lambda: self.request(who, scope)

    # --- Takt --------------------------------------------------------------------------------------
    def tick(self, now: float | None = None) -> dict | None:
        """Aus der Messschleife (alle ~10 s): Fälliges anwenden. Rückgabe: was entschieden wurde (Tests)."""
        with self.lock:
            now = self.wall() if now is None else now
            state = self._load()
            pending = state.get("pending")
            if not pending:
                return None
            names = sorted(pending["who"])
            labels = [LABELS[n] for n in names]
            since = pending["since"]
            if since > now + CLOCK_SLACK:      # Uhr deutlich zurückgestellt: ab jetzt sammeln
                pending["since"] = since = now
                pending["next_try"] = None
                self._save(state)
            started = _num(self._started())
            if started is not None and started >= since + TAKE_ALONG_MARGIN:
                state["pending"] = None
                self._save(state)
                self._emit("info", f"Automatische Änderung mit dem letzten Neustart von chronyd übernommen: "
                                   f"{', '.join(labels)} – kein eigener Neustart nötig",
                           {"who": names, "decision": "taken_along"})
                return {"decision": "taken_along", "who": names}
            if now - since < COLLECT_SECONDS:
                return {"decision": "collect", "who": names}
            next_try = pending.get("next_try")
            if next_try is not None and now < next_try and next_try - now <= DAY:
                return {"decision": "wait", "who": names, "held": pending.get("held")}
            recent = self._recent(state["auto"], now)
            if len(recent) >= MAX_PER_DAY:
                free_at = min(recent) + DAY
                first = pending.get("held") != "limit"
                pending.update(held="limit", next_try=free_at)
                self._save(state)
                if first:
                    hours = max(0.0, free_at - now) / 3600.0
                    self._emit("warn", f"Tagesgrenze automatischer Neustarts erreicht ({MAX_PER_DAY} in 24 h): "
                                       f"{', '.join(labels)} wartet noch etwa {hours:.0f} h – bis dahin gilt "
                                       "die bisherige Einstellung",
                               {"who": names, "decision": "limit", "auto_24h": len(recent), "limit": MAX_PER_DAY,
                                "free_at": round(free_at)})
                return {"decision": "limit", "who": names, "free_at": free_at}
            scope = "all" if "all" in pending["who"].values() else "chronyd"
            trigger = self.triggers.get(scope) or self.triggers.get("chronyd")
            try:
                ok = bool(self._gate(trigger)) if trigger else False
            except Exception:
                ok = False
            if not ok:
                first = pending.get("held") != "retry"
                pending.update(held="retry", next_try=now + RETRY_SECONDS)
                self._save(state)
                if first:
                    self._emit("warn", f"Neustart von chronyd für {', '.join(labels)} ließ sich nicht anfordern – "
                                       "neuer Versuch in 10 Minuten",
                               {"who": names, "decision": "failed"})
                return {"decision": "failed", "who": names}
            state["auto"] = (state["auto"] + [now])[-MAX_LOG:]
            state["pending"] = None
            self._save(state)
            count = len(self._recent(state["auto"], now))
            what = "Zeitdienste" if scope == "all" else "chronyd"
            late = " (nach Tagesgrenze nachgeholt)" if pending.get("held") == "limit" else ""
            self._emit("info", f"{what} für automatische Änderungen neu gestartet{late}: {', '.join(labels)} "
                               f"({count} von {MAX_PER_DAY} in 24 h)",
                       {"who": names, "decision": "applied", "scope": scope, "auto_24h": count,
                        "limit": MAX_PER_DAY})
            return {"decision": "applied", "who": names, "scope": scope}

    # --- Anzeige -----------------------------------------------------------------------------------
    def status(self, now: float | None = None) -> dict[str, Any]:
        """Für /api/status und /metrics: nur Zahlen, Zeitpunkte und feste Namen."""
        with self.lock:
            now = self.wall() if now is None else now
            state = self._load()
        recent = self._recent(state["auto"], now)
        pending = state.get("pending")
        out: dict[str, Any] = {
            "auto_24h": len(recent), "limit": MAX_PER_DAY, "collect_s": COLLECT_SECONDS,
            "last": max(state["auto"]) if state["auto"] else None,
            "state": "idle", "pending": [], "next_try": None,
        }
        if pending:
            out["pending"] = [LABELS[n] for n in sorted(pending["who"])]
            out["state"] = pending.get("held") or "collecting"
            out["next_try"] = pending.get("next_try") if pending.get("held") else pending["since"] + COLLECT_SECONDS
        if self.last_error:
            out["error"] = self.last_error
        return out


COORD = Coordinator()


def trigger_for(who: str, scope: str = "chronyd") -> Callable[[], bool]:
    return COORD.trigger_for(who, scope)


def tick() -> dict | None:
    """Wirft nie (Messschleife)."""
    try:
        return COORD.tick()
    except Exception:
        return None


def status() -> dict[str, Any]:
    try:
        return COORD.status()
    except Exception:
        return {"auto_24h": None, "limit": MAX_PER_DAY, "state": "unknown", "pending": []}
