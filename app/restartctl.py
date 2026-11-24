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
    in der Zeit nichts weiter (es wartet, bis der Neustart belegt ist); GPS-Seite und Übersicht zeigen
    die Wartezeit (waiting()).
  * Vorrang für eine größere Fehlerschranke: Sie schützt davor, das GPS für genauer zu halten, als es
    ist (schlechter werdender Empfang). Eine Anforderung mit grow=True darf darum über die Grenze hinaus
    noch GROW_RESERVE weitere Plätze in 24 h nutzen; alles, was gerade wartet, geht mit.
  * Mitgenommen: Startet chronyd inzwischen aus einem anderen Grund neu (du speicherst, Zertifikat,
    Hotplug), erzeugt der Supervisor die Konfiguration dabei neu – die wartende Änderung ist damit aktiv
    und zählt nicht zur Obergrenze. Verglichen wird mit der LETZTEN Anforderung: Endete jener Neustart
    weniger als TAKE_ALONG_MARGIN danach, könnte er die Konfiguration noch davor erzeugt haben – dann
    folgt sicherheitshalber ein eigener. Zusätzlich wird nachgesehen, ob der Wert wirklich in der
    laufenden chrony.conf steht (verify); fehlt er, bleibt die Anforderung stehen und es folgt ein
    eigener Neustart.
  * Zurückgenommen oder überschrieben: Mit der Anforderung merkt sich der Koordinator den angeforderten
    Wert (wanted: Offset bzw. Delay in s). Steht in den Einstellungen inzwischen ein anderer Wert (du hast
    „Rückgängig“ gewählt, auf Standard zurückgesetzt oder eine Sicherung zurückgespielt – das startet
    chronyd ohnehin sofort neu), ist die Anforderung erledigt: Ereignis „verworfen“, kein „übernommen“,
    kein eigener Neustart.
  * Holdover-Test: Läuft ein Test, wartet die Änderung (Zustand „holdover“, ein Ereignis, nichts
    gezählt); nach dem Test noch COLLECT_SECONDS, damit ein Neustart des Tests sie mitnehmen kann, dann
    ein eigener. Das Anwenden selbst geht weiter über holdover.reload_or_defer – beginnt der Test genau
    in dem Moment, gilt dasselbe.
Jede Entscheidung (angewandt, Tagesgrenze, mitgenommen, zurückgestellt, nicht anforderbar) ist ein
Ereignis der Art „reload“. Der Zustand steht in DATA_DIR/neustarts.json (überlebt einen Neustart von ntp-gui), in
/api/status („restarts“), auf der Übersicht (Kachel Dienste) und in /metrics.

Datenschutz: gespeichert werden nur Zeitpunkte, feste Namen der Automatiken und die angeforderten
Zahlenwerte (Offset bzw. Delay in Sekunden).
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
GROW_RESERVE = 4            # zusätzliche Plätze in 24 h nur für eine größere GPS-Fehlerschranke
MAX_LOG = 20                # gemerkte Neustarts (für die Anzeige „zuletzt“)

# Feste Namen – nur diese werden angenommen (keine freien Texte in Zustand, Ereignis oder Metrik).
LABELS = {
    "autocal": "GPS-Kalibrierung (Offset)",
    "gps_bound": "GPS-Fehlerschranke",
}
SCOPES = ("chronyd", "all")   # nur chronyd neu laden bzw. alle Zeitdienste
HELD = ("limit", "retry", "holdover")


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


def _default_busy() -> bool:
    import holdover
    return holdover.TEST.running()


def _default_verify(who: str) -> bool | None:
    """Steht die gespeicherte Änderung in der laufenden chrony.conf? None = nicht prüfbar."""
    import autocal
    import gpsquality
    import settings
    cfg = settings.values()
    if not cfg.get("gps_enable"):
        return None
    if who == "autocal":
        return autocal.offset_running(cfg)
    if who == "gps_bound":
        return gpsquality.bound_running(cfg)
    return None


def _default_wanted(who: str) -> float | None:
    """Der Wert, den die Einstellungen für diese Automatik gerade vorgeben (Offset bzw. Delay in s).
    None = nicht bestimmbar (dann keine Prüfung auf Rücknahme)."""
    import autocal
    import gpsquality
    import settings
    cfg = settings.values()
    if not cfg.get("gps_enable"):
        return None
    if who == "autocal":
        return _num(autocal._cfg_float(cfg, "gps_offset", 0.0))
    if who == "gps_bound":
        try:
            return _num(float(gpsquality.refclock_values(cfg)["delay"]))
        except Exception:
            return None
    return None


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-9, abs(b) * 1e-6)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") else None


class Coordinator:
    """Sammelt automatische Neustart-Wünsche und wendet sie gemeinsam an (Obergrenze je Tag)."""

    def __init__(self, path: Callable[[], str] | None = None, wall: Callable[[], float] = time.time,
                 emit: Callable[..., Any] | None = None, gate: Callable[[Callable[[], Any]], bool] | None = None,
                 started: Callable[[], float | None] | None = None, busy: Callable[[], bool] | None = None,
                 verify: Callable[[str], bool | None] | None = None,
                 wanted: Callable[[str], float | None] | None = None) -> None:
        self.lock = threading.RLock()
        self._path = path or _default_path
        self.wall = wall
        self._emit_fn = emit or _default_emit
        self._gate = gate or _default_gate
        self._started = started or _default_started
        self._busy = busy or _default_busy
        self._verify = verify or _default_verify
        self._wanted = wanted or _default_wanted
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
                since = _num(pending.get("since"))
                last = _num(pending.get("last"))
                state["pending"] = {
                    "since": since, "last": since if last is None else max(since, last), "who": who,
                    "held": pending.get("held") if pending.get("held") in HELD else None,
                    "next_try": _num(pending.get("next_try")), "grow": pending.get("grow") is True,
                    "checked": _num(pending.get("checked")),
                }
                want = pending.get("want") if isinstance(pending.get("want"), dict) else {}
                want = {k: _num(v) for k, v in want.items() if k in who}
                if any(v is not None for v in want.values()):
                    state["pending"]["want"] = {k: v for k, v in want.items() if v is not None}
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

    def _busy_now(self) -> bool:
        try:
            return bool(self._busy())
        except Exception:
            return False

    def _arrived(self, who: str) -> bool | None:
        try:
            result = self._verify(who)
        except Exception:
            return None
        return result if isinstance(result, bool) else None

    def _current(self, who: str) -> float | None:
        try:
            return _num(self._wanted(who))
        except Exception:
            return None

    def _superseded(self, pending: dict, who: str) -> bool:
        """Steht in den Einstellungen inzwischen ein anderer Wert als der angeforderte?"""
        want = (pending.get("want") or {}).get(who)
        if want is None:
            return False
        now_value = self._current(who)
        return now_value is not None and not _same(now_value, want)

    def _drop_superseded(self, state: dict, pending: dict, names: list[str]) -> list[str]:
        """Zurückgenommene bzw. überschriebene Anforderungen verwerfen. Rückgabe: was noch wartet."""
        gone = [n for n in names if self._superseded(pending, n)]
        if not gone:
            return names
        rest = [n for n in names if n not in gone]
        self._emit("info", f"Wartende automatische Änderung verworfen: {', '.join(LABELS[n] for n in gone)} – "
                           "inzwischen von Hand geändert oder zurückgenommen, kein eigener Neustart nötig",
                   {"who": gone, "decision": "superseded"})
        if not rest:
            state["pending"] = None
        else:
            pending["who"] = {n: pending["who"][n] for n in rest}
            pending["want"] = {n: v for n, v in (pending.get("want") or {}).items() if n in rest}
            if "gps_bound" not in rest:
                pending["grow"] = False
        self._save(state)
        return rest

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
    def request(self, who: str, scope: str = "chronyd", grow: bool = False) -> bool:
        """Eine Automatik hat gespeichert und braucht einen Neustart. True = vorgemerkt (der Neustart
        folgt gesammelt). Unbekannte Namen werden abgelehnt (False). grow: die GPS-Fehlerschranke wird
        größer (Vorrang, siehe GROW_RESERVE)."""
        if who not in LABELS or scope not in SCOPES:
            return False
        with self.lock:
            now = self.wall()
            state = self._load()
            pending = state.get("pending")
            if not pending:
                pending = {"since": now, "last": now, "who": {}, "held": None, "next_try": None,
                           "grow": False, "checked": None}
            pending["last"] = max(now, pending.get("last") or now)
            if pending["who"].get(who) != "all":
                pending["who"][who] = scope
            want = self._current(who)                  # der angeforderte Wert (steht schon in den Einstellungen)
            wants = {k: v for k, v in (pending.get("want") or {}).items() if k != who}
            if want is not None:
                wants[who] = want
            pending["want"] = wants
            if grow and who == "gps_bound":
                pending["grow"] = True
                if pending.get("held") == "limit":      # wartet an der Tagesgrenze: gleich neu bewerten
                    pending["next_try"] = None
            state["pending"] = pending
            self._save(state)
            return True

    def trigger_for(self, who: str, scope: str = "chronyd", grow: bool = False) -> Callable[[], bool]:
        """Als trigger_reload für eine Automatik (autocal, gpsquality)."""
        return lambda: self.request(who, scope, grow)

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
                pending.update(since=now, last=now, next_try=None)
                since = now
                self._save(state)
            last = pending.get("last") or since
            if last > now + CLOCK_SLACK:
                pending["last"] = last = now
                self._save(state)
            started = _num(self._started())
            if started is not None and started >= last + TAKE_ALONG_MARGIN and started != pending.get("checked"):
                names = self._drop_superseded(state, pending, names)
                if not names:
                    return {"decision": "superseded", "who": []}
                labels = [LABELS[n] for n in names]
                missing = [n for n in names if self._arrived(n) is False]
                taken = [n for n in names if n not in missing]
                if taken:
                    self._emit("info", "Automatische Änderung mit dem letzten Neustart von chronyd übernommen: "
                                       f"{', '.join(LABELS[n] for n in taken)} – kein eigener Neustart nötig",
                               {"who": taken, "decision": "taken_along"})
                if not missing:
                    state["pending"] = None
                    self._save(state)
                    return {"decision": "taken_along", "who": names}
                # Der Neustart hat seine Konfiguration noch vor dieser Änderung erzeugt: eigener Neustart.
                pending["who"] = {n: pending["who"][n] for n in missing}
                pending["want"] = {n: v for n, v in (pending.get("want") or {}).items() if n in missing}
                pending["checked"] = started
                if "gps_bound" not in missing:
                    pending["grow"] = False
                self._save(state)
                names = missing
                labels = [LABELS[n] for n in names]
                self._emit("info", f"Der letzte Neustart von chronyd hat {', '.join(labels)} noch nicht übernommen "
                                   "– es folgt ein eigener Neustart",
                           {"who": names, "decision": "not_taken_along"})
            if now - since < COLLECT_SECONDS:
                return {"decision": "collect", "who": names}
            if self._busy_now():
                return self._hold_for_holdover(state, pending, names, labels)
            if pending.get("held") == "holdover":
                # Test vorbei: kurz warten – ein Neustart nach dem Test nimmt die Änderung mit.
                pending.update(held=None, next_try=now + COLLECT_SECONDS)
                self._save(state)
                return {"decision": "wait", "who": names, "held": None}
            next_try = pending.get("next_try")
            if next_try is not None and now < next_try and next_try - now <= DAY:
                return {"decision": "wait", "who": names, "held": pending.get("held")}
            names = self._drop_superseded(state, pending, names)     # vor Tagesgrenze und eigenem Neustart
            if not names:
                return {"decision": "superseded", "who": []}
            labels = [LABELS[n] for n in names]
            recent = self._recent(state["auto"], now)
            grow = bool(pending.get("grow"))
            beyond = len(recent) >= MAX_PER_DAY
            if beyond and not (grow and len(recent) < MAX_PER_DAY + GROW_RESERVE):
                ceiling = MAX_PER_DAY + GROW_RESERVE if grow else MAX_PER_DAY
                free_at = sorted(recent)[len(recent) - ceiling] + DAY
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
            if ok and self._busy_now():
                # Gerade eben hat ein Holdover-Test begonnen: reload_or_defer hat nur vorgemerkt, chronyd
                # startet erst nach dem Test neu (vom Test ausgelöst) – nichts zählen, nichts „neu gestartet“.
                return self._hold_for_holdover(state, pending, names, labels)
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
            if beyond:
                late = " (größere GPS-Fehlerschranke hat Vorrang vor der Tagesgrenze)"
            self._emit("info", f"{what} für automatische Änderungen neu gestartet{late}: {', '.join(labels)} "
                               f"({count} von {MAX_PER_DAY} in 24 h)",
                       {"who": names, "decision": "applied", "scope": scope, "auto_24h": count,
                        "limit": MAX_PER_DAY, "grow": grow})
            return {"decision": "applied", "who": names, "scope": scope}

    def _hold_for_holdover(self, state: dict, pending: dict, names: list[str], labels: list[str]) -> dict:
        first = pending.get("held") != "holdover"
        pending.update(held="holdover", next_try=None)
        self._save(state)
        if first:
            self._emit("info", f"Neustart von chronyd für {', '.join(labels)} zurückgestellt: Holdover-Test läuft – "
                               "folgt nach dem Test (bis dahin gilt die bisherige Einstellung)",
                       {"who": names, "decision": "deferred"})
        return {"decision": "deferred", "who": names}

    # --- Anzeige -----------------------------------------------------------------------------------
    def waiting(self, who: str, now: float | None = None) -> dict[str, Any] | None:
        """Wartet eine gespeicherte Änderung von `who` noch auf ihren Neustart? {"state", "next_try"} oder None."""
        with self.lock:
            now = self.wall() if now is None else now
            state = self._load()
        pending = state.get("pending")
        if not pending or who not in pending["who"]:
            return None
        held = pending.get("held")
        next_try = pending.get("next_try")
        if next_try is None and not held:
            next_try = max(pending["since"] + COLLECT_SECONDS, now)
        return {"state": held or "collecting", "next_try": next_try}

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
            "grow_reserve": GROW_RESERVE, "state": "idle", "pending": [], "pending_ids": [], "next_try": None,
        }
        if pending:
            ids = sorted(pending["who"])
            out["pending"] = [LABELS[n] for n in ids]
            out["pending_ids"] = ids
            out["state"] = pending.get("held") or "collecting"
            out["next_try"] = pending.get("next_try") if pending.get("next_try") is not None or pending.get("held") \
                else pending["since"] + COLLECT_SECONDS
        if self.last_error:
            out["error"] = self.last_error
        return out


COORD = Coordinator()


def trigger_for(who: str, scope: str = "chronyd", grow: bool = False) -> Callable[[], bool]:
    return COORD.trigger_for(who, scope, grow)


def waiting(who: str) -> dict[str, Any] | None:
    """Wirft nie (Anzeige)."""
    try:
        return COORD.waiting(who)
    except Exception:
        return None


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
        return {"auto_24h": None, "limit": MAX_PER_DAY, "state": "unknown", "pending": [], "pending_ids": []}
