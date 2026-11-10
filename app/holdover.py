"""Echter Holdover-Test (1.5, Thema 8): Wie lange hält die Uhr ohne Zeitquelle?

Ablauf: Auf Knopfdruck (admin, opt-in) wählt ntp-gui GPS/PPS und – standardmäßig – auch alle
Netzquellen per `chronyc selectopts <quelle> +noselect` ab. chrony stellt die Uhr dann nicht
mehr nach; sie läuft mit der zuletzt gelernten Frequenz frei. Die Netzquellen werden aber
weiter **gemessen**: Sie dienen als Messreferenz, ohne die Zeit zu beeinflussen. ntp-gui
speichert jede Minute den Median ihrer Offsets und zieht davon den Wert beim Start ab – das ist
der Zeitfehler, den die Uhr in der Zeit aufgebaut hat. Gerechnet wird je Referenz (Offset jetzt −
Offset beim Start) und davon der Median über die Referenzen, die gerade erreichbar sind – fällt
eine aus oder kommt eine zurück, springt der Wert so nicht um die Streuung zwischen den Servern. Nach N Stunden (1–24, Standard 2) werden
alle Quellen automatisch wieder auswählbar. Ergebnis: „Die Uhr hält 3,2 ms in 2 h“ auf der
Seite Uhrqualität, mit Drift in ppm.

Ohne Netzquellen-Option wird nur GPS/PPS abgewählt – dann regelt das Netz weiter, und der Test
zeigt, wie gut es ohne GPS geht (kein Freilauf). Sein Ergebnis heißt darum nicht „Die Uhr hält …“,
sondern „Ohne GPS/PPS: Abweichung … (das Netz regelt weiter)“.

Sicherheit (alles umkehrbar, mit Zeitlimit, Ereignis und Zustand in SQLite):
  * kein Start ohne mindestens zwei erreichbare Messreferenzen (Netzquellen)
  * automatischer Abbruch, wenn |Zeitfehler| die Grenze überschreitet (Standard 10 ms)
  * Abbruch-Knopf; Abbruch, wenn chronyd neu startet (der Schalter ist dann weg – der Test
    wäre verfälscht; alle Quellen sind danach ohnehin wieder auswählbar)
  * Neustart von ntp-gui: der Zustand mit Endzeit steht in SQLite, beim nächsten Durchgang wird
    weitergemessen bzw. nach Ablauf sofort zurückgestellt
  * eine GPS-Sperre (gnssguard) bleibt beim Zurückstellen bestehen (selectctl: Halter)
  * nimmt chrony während des Tests eine neue Quelle auf (z. B. Ersatz für ein unerreichbares
    Pool-Mitglied – die ist auswählbar und würde die Uhr wieder stellen), wird sie sofort mit
    abgewählt (Ereignis); geht das nicht, endet der Test als „ungültig“
Clients bekommen während des Tests eine ungenauere Zeit – darauf weist die Oberfläche hin.

Automatiken warten (1.5.3): Jeder Neustart von chronyd bräche den Test ab (Rückmeldung: die
automatische Anpassung der GPS-Fehlerschranke beendete einen 6-h-Test nach 4 h 35 min). Darum
stellen gpsquality (Schranke) und autocal (Offset) ihre Änderung zurück, solange ein Test läuft
(`defer`), und holen sie nach dessen Ende im nächsten Durchgang nach (`resume`). Der Supervisor
stellt Neustarts nach Gerätewechsel (Hotplug) und erneuertem NTS-Zertifikat zurück, solange
RUN_DIR/reload.hold eine Zeit in der Zukunft nennt (alle 10 s um HOLD_TTL verlängert – stirbt das
Dashboard, läuft die Sperre von selbst ab). Was du selbst speicherst, startet chronyd weiter sofort
neu (und bricht den Test ab); die Oberfläche fragt vorher nach.

Teststart (Prüfbefund): `start` setzt zuerst die Sperre und lehnt ab, solange ein Neustart angefordert ist
(reload.request) oder läuft (reload.json „running“, schreibt der Supervisor vor dem Löschen der
Anforderung). Automatiken lösen ihren Neustart über `reload_or_defer` aus – unter derselben Sperre wie
der Start geprüft; hat der Test eben begonnen, folgt der Neustart nach dessen Ende. Ein neuer Test
startet frühestens RESTART_PAUSE nach dem letzten und erst, wenn Zurückgestelltes geprüft ist
(höchstens RESUME_WAIT, danach wird es in den neuen Test übernommen).

Ereignisse, die der Test selbst verursacht (keine Quelle mehr ausgewählt, Quellenwechsel,
„Schleife beendet – Quelle antwortet nicht“, „GPS-Sperre ausgelassen: keine andere Quelle“),
macht `event_filter` während des Tests und kurz danach (EVENT_GRACE) zu „info“ ohne
Benachrichtigung, mit dem Vermerk „(Holdover-Test)“. Beim Test nur ohne GPS nur Wechsel von oder zu
einem Testziel – „keine Zeitquelle mehr“ ist dann ein echter Ausfall des Netzes. „GPS-Sperre
ausgelassen“ nur, solange der Test läuft (gnssguard meldet es danach erneut).
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any, Callable

import numfmt
import selectctl
import store

OWNER = "holdover"
HOURS_MIN, HOURS_MAX, HOURS_DEFAULT = 1.0, 24.0, 2.0
LIMIT_MIN_MS, LIMIT_MAX_MS, LIMIT_DEFAULT_MS = 1.0, 1000.0, 10.0
MIN_REFS = 2
POINT_EVERY = 60.0
KEEP_RESULTS = 20
CHART_POINTS = 300
DEFER_TEXT = "zurückgestellt bis zum Ende des Holdover-Tests"
HOLD_FILE = "reload.hold"       # für den Supervisor: automatische Neustarts zurückstellen bis …
HOLD_TTL = 120.0                # … jetzt + so viel; der Test verlängert alle ~10 s
EVENT_GRACE = 900.0             # so lange nach dem Ende zählen Quellenwechsel noch zum Test
RESTART_PAUSE = 10.0            # neuer Test frühestens so lange nach dem Ende (Supervisor holt Neustarts nach)
RESUME_WAIT = 300.0             # so lange wartet ein neuer Start, bis Automatiken Zurückgestelltes geprüft haben
RELOAD_RUNNING_MAX = 120.0      # „running“ in reload.json gilt höchstens so lange (sonst veraltet)
SETTLE = 0.5                    # nach dem Setzen der Sperre: so lange auf einen schon begonnenen Neustart achten
_RELOAD: dict[str, Any] = {"fn": None}   # Neustart der Zeitdienste (server.trigger_reload), siehe configure

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS holdover_state (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS holdover_points (t REAL NOT NULL, dev REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS holdover_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started REAL NOT NULL,
        json TEXT NOT NULL
    );
    """,
]
_READY: dict[str, Any] = {"for": None}


class HoldoverError(ValueError):
    def __init__(self, message: str, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


def _ensure() -> None:
    key = store.path()
    if _READY["for"] != key:
        store.migrate("holdover", _SCHEMA)
        _READY["for"] = key


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return None
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def fmt_ms(seconds: float) -> str:
    value = abs(seconds) * 1000.0
    return f"{numfmt.number(value, 0 if value >= 100 else 1 if value >= 1 else 2, group=False)} ms"


def fmt_span(seconds: float) -> str:
    minutes = max(0, int(round(seconds / 60.0)))
    if minutes < 60:
        return f"{max(1, minutes)} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def slope_ppm(points: list[tuple[float, float]]) -> float | None:
    """Gangabweichung aus dem Verlauf des Zeitfehlers (Gerade, kleinste Quadrate) in ppm."""
    if len(points) < 3:
        return None
    n = len(points)
    mt = sum(t for t, _ in points) / n
    md = sum(d for _, d in points) / n
    var = sum((t - mt) ** 2 for t, _ in points)
    if var <= 0:
        return None
    return sum((t - mt) * (d - md) for t, d in points) / var * 1e6


def references(sources: list[dict] | None, names: list[str] | None = None) -> dict[str, float]:
    """Erreichbare Netzquellen mit Offset – die Messreferenzen."""
    out = {}
    for src in sources or []:
        if not isinstance(src, dict) or src.get("mode") not in {"^", "="}:
            continue
        # Abgewählte Quellen (noselect) zeigt chrony 4.6 in „sources“ mit Zustand „?“ – gemessen
        # werden sie trotzdem. Erreichbar heißt deshalb: Erreichbarkeitsregister ≠ 0.
        if src.get("state") == "x" or not src.get("reach"):
            continue
        offset = _num(src.get("offset"))
        name = src.get("name")
        if offset is None or not name or (names is not None and name not in names):
            continue
        out[str(name)] = offset
    return out


def _default_emit(kind: str, level: str, title: str, data: dict) -> None:
    import events
    events.emit(kind, level, title, data)


def _hold_path() -> str:
    return os.path.join(os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui"), HOLD_FILE)


def configure(trigger_reload: Callable[[], bool] | None = None) -> None:
    """server.py: womit ein zurückgestellter Neustart nach dem Test ausgelöst wird."""
    _RELOAD["fn"] = trigger_reload


def reload_busy(now: float | None = None) -> str:
    """Steht ein Neustart der Zeitdienste an oder läuft er gerade? Dann Grund, sonst ""."""
    run_dir = os.path.dirname(_hold_path())
    if any(os.path.exists(os.path.join(run_dir, name)) for name in ("reload.request", "reload-chronyd.request")):
        return "Ein Neustart der Zeitdienste ist angefordert"
    try:
        with open(os.path.join(run_dir, "reload.json"), encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        return ""
    if not isinstance(info, dict) or info.get("state") != "running":
        return ""
    since = _num(info.get("time"))
    now = time.time() if now is None else now
    if since is not None and abs(now - since) <= RELOAD_RUNNING_MAX:
        return "Die Zeitdienste starten gerade neu"
    return ""


def _write_hold(until: float | None) -> None:
    """Sperre für automatische Neustarts im Supervisor setzen (until: Unix-Zeit) bzw. aufheben (None)."""
    path = _hold_path()
    try:
        if until is None:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write(f"{int(until)}\n")
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def _settle() -> None:
    """Kurz warten, damit ein Supervisor-Durchgang, der die Sperre knapp verpasst hat, seinen Neustart
    schon in reload.json vermerkt (nur mit Supervisor – in Tests und der Entwicklung nicht)."""
    if os.path.exists(os.path.join(os.path.dirname(_hold_path()), "supervisor.pid")):
        time.sleep(SETTLE)


class HoldoverTest:
    def __init__(self, emit: Callable[..., Any] | None = None, wall: Callable[[], float] = time.time,
                 hold: Callable[[float | None], None] | None = None,
                 mono: Callable[[], float] | None = None) -> None:
        self._emit_fn = emit
        self.wall = wall
        # 1.5.4: Die Frist läuft auf der monotonen Uhr – ein Sprung der Wanduhr (makestep nach dem
        # Test, ein falsch gestelltes RTC) verlängert oder verkürzt den Test nicht. Tests, die nur die
        # Wanduhr vorgeben, bekommen sie auch als monotone Uhr.
        self.mono = mono or (time.monotonic if wall is time.time else wall)
        self._mono_key: tuple[float, float] | None = None
        self._mono_deadline = 0.0
        self._hold = hold or _write_hold
        self.lock = threading.RLock()
        self._state: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.busy: Callable[[], str] = reload_busy   # Tests: lambda: ""
        self.settle: Callable[[], None] = _settle
        # Bestätigt dieser Prozess den laufenden Test (start oder ein Durchgang, der chronyd noch mit
        # der Abwahl sah)? Nach einem Neustart des Containers kommt „active“ aus SQLite zurück, obwohl
        # chronyd neu gestartet ist – bis zum ersten Durchgang keine „zurückgestellt“-Ereignisse.
        self._confirmed = False
        self._noted: set[str] = set()

    def _emit(self, level: str, title: str, data: dict) -> None:
        # Ein Test, den du selbst gestartet hast: steht im Protokoll und auf der Seite, geht aber
        # nicht als Benachrichtigung hinaus (sonst bliebe „abgebrochen“ dort als offenes Problem).
        data = dict(data, subject="holdover", notify=False, resolves=False)
        try:
            (self._emit_fn or _default_emit)("source", level, title, data)
        except Exception:
            pass

    # --- Zustand ---------------------------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        if self._state is None:
            state: dict[str, Any] = {}
            try:
                _ensure()
                rows = store.query("SELECT json FROM holdover_state WHERE id = 1")
                state = json.loads(rows[0][0]) if rows else {}
            except Exception as exc:
                self.last_error = f"Zustand nicht lesbar: {exc}"
            if not isinstance(state, dict):
                state = {}
            state["changed"] = [n for n in state.get("changed") or [] if selectctl.valid_name(n)]
            self._state = state
            state["targets"] = [n for n in state.get("targets") or [] if selectctl.valid_name(n)]
            if state.get("active"):
                selectctl.register(OWNER, state["targets"] or state["changed"], state["changed"])
            elif state.get("release_pending"):
                selectctl.register(OWNER, state["changed"], state["changed"])
        return self._state

    def _save(self) -> None:
        _ensure()
        store.execute("INSERT INTO holdover_state(id, json) VALUES(1, ?) "
                      "ON CONFLICT(id) DO UPDATE SET json = excluded.json",
                      (json.dumps(self.state(), separators=(",", ":")),))

    def remaining(self, state: dict | None = None) -> float:
        """Sekunden bis zum Ende des laufenden Tests – auf der monotonen Uhr.

        Gespeichert (und angezeigt) wird die Frist als Wanduhrzeit. Kennt dieser Prozess den Test
        noch nicht (Start oder Neustart des Containers), rechnet er die Restzeit einmal aus der
        Wanduhr um – nie länger als die ganze Testdauer, nie negativ. Danach zählt nur noch die
        monotone Uhr."""
        state = self.state() if state is None else state
        deadline = float(state.get("deadline") or 0.0)
        started = float(state.get("started") or deadline)
        key = (started, deadline)
        if self._mono_key != key:
            total = max(0.0, deadline - started)
            left = min(max(0.0, deadline - self.wall()), total)
            self._mono_key, self._mono_deadline = key, self.mono() + left
        return self._mono_deadline - self.mono()

    def _points(self) -> list[tuple[float, float]]:
        try:
            _ensure()
            return [(float(t), float(d)) for t, d in store.query("SELECT t, dev FROM holdover_points ORDER BY t")]
        except Exception:
            return []

    # --- Vorprüfung ------------------------------------------------------------------------------
    def check(self, select: dict[str, dict], sources: list[dict] | None, include_network: bool = True) -> dict[str, Any]:
        refs = references(sources)
        listed = [s for s in sources or [] if isinstance(s, dict) and s.get("name") in select]
        refclocks = [s["name"] for s in listed if s.get("mode") == "#"]
        network = [s["name"] for s in listed if s.get("mode") in {"^", "="}]
        out = {"references": len(refs), "refclocks": refclocks, "network": len(network), "ok": True, "reason": ""}
        if not select:
            out.update(ok=False, reason="chronyd antwortet nicht.")
        elif len(refs) < MIN_REFS:
            out.update(ok=False, reason=f"Kein Test ohne mindestens {MIN_REFS} erreichbare Netzquellen als "
                                        f"Messreferenz – gerade erreichbar: {len(refs)}.")
        elif not include_network and not refclocks:
            out.update(ok=False, reason="Ohne GPS/PPS gibt es nichts abzuschalten – für einen echten Holdover "
                                        "„auch Netzquellen abschalten“ wählen.")
        return out

    # --- Start / Ende ------------------------------------------------------------------------------
    @staticmethod
    def _parse(data: dict) -> tuple[float, bool, float]:
        try:
            hours = float(data.get("hours", HOURS_DEFAULT))
            limit = float(data.get("limit_ms", LIMIT_DEFAULT_MS))
        except (TypeError, ValueError):
            raise HoldoverError("hours und limit_ms müssen Zahlen sein") from None
        if not math.isfinite(hours) or not HOURS_MIN <= hours <= HOURS_MAX:
            raise HoldoverError(f"Dauer muss zwischen {HOURS_MIN:.0f} und {HOURS_MAX:.0f} Stunden liegen")
        if not math.isfinite(limit) or not LIMIT_MIN_MS <= limit <= LIMIT_MAX_MS:
            raise HoldoverError(f"Grenze muss zwischen {LIMIT_MIN_MS:.0f} und {LIMIT_MAX_MS:.0f} ms liegen")
        include = data.get("include_network", True)
        if not isinstance(include, bool):
            raise HoldoverError("include_network muss true oder false sein")
        return hours, include, limit

    def start(self, data: dict, select: dict[str, dict] | None = None,
              sources: list[dict] | None = None) -> dict[str, Any]:
        hours, include, limit = self._parse(data or {})
        with self.lock:
            previous = self.state()
            if previous.get("active"):
                raise HoldoverError("Es läuft schon ein Holdover-Test.", conflict=True)
            ended = _num(previous.get("last_result"))
            since_end = None if ended is None else self.wall() - ended
            pending = [p for p in previous.get("resume") or [] if isinstance(p, str)]
            if since_end is not None and 0.0 <= since_end < RESTART_PAUSE:
                raise HoldoverError("Der letzte Holdover-Test ist gerade erst zu Ende – zurückgestellte Neustarts "
                                    "laufen noch. In ein paar Sekunden erneut versuchen.", conflict=True)
            if pending and since_end is not None and 0.0 <= since_end < RESUME_WAIT:
                raise HoldoverError("Zurückgestellte Änderungen aus dem letzten Holdover-Test werden gerade "
                                    "nachgeholt – in ein paar Minuten erneut versuchen.", conflict=True)
            # Erst die Sperre für den Supervisor, dann prüfen, ob schon ein Neustart angefordert ist oder
            # läuft – sonst bräche er den Test nach wenigen Sekunden ab.
            self._hold(time.time() + HOLD_TTL)
            try:
                self.settle()
                busy = self.busy()
            except Exception:
                busy = ""
            if busy:
                self._hold(None)
                raise HoldoverError(f"{busy} – den Holdover-Test bitte in ein paar Sekunden starten.", conflict=True)
            try:
                return self._start(hours, include, limit, select, sources, pending)
            except Exception:
                if not self.state().get("active"):
                    self._hold(None)
                raise

    def _start(self, hours: float, include: bool, limit: float, select: dict[str, dict] | None,
               sources: list[dict] | None, pending: list[str]) -> dict[str, Any]:
        port = selectctl.port()
        select = selectctl.by_name(port.selectdata()) if select is None else select
        sources = port.sources() if sources is None else sources
        check = self.check(select, sources, include)
        if not check["ok"]:
            raise HoldoverError(check["reason"], conflict=True)
        targets = [s["name"] for s in sources if isinstance(s, dict) and s.get("name") in select
                   and (s.get("mode") == "#" or (include and s.get("mode") in {"^", "="}))]
        refs = references(sources)
        try:
            changed = selectctl.hold(OWNER, targets, select)
        except selectctl.SelectError as exc:
            selectctl.forget(OWNER)
            raise HoldoverError(f"chronyc selectopts ging nicht: {exc}", conflict=True) from exc
        # selectctl merkt sich: Ziele = targets, selbst abgewählt = changed – zurückgestellt wird nur das.
        now = self.wall()
        self._state = {"active": True, "started": now, "deadline": now + hours * 3600.0, "hours": hours,
                       "include_network": include, "limit_ms": limit, "targets": targets, "changed": changed,
                       "refs": sorted(refs), "start_offset": _median(list(refs.values())),
                       "start_offsets": dict(refs),
                       "last_dev": 0.0, "max_abs": 0.0, "last_point": now}
        if pending:   # noch nicht geprüft (Automatik aus?) – nach diesem Test erneut anbieten
            self._state["resume"] = pending
        self._confirmed = True
        self._noted = set()
        _ensure()
        with store.transaction() as conn:
            conn.execute("DELETE FROM holdover_points")
            conn.execute("INSERT INTO holdover_points(t, dev) VALUES(?, 0)", (now,))
        self._save()
        self._refresh_hold()
        what = "GPS/PPS und alle Netzquellen" if include else "GPS/PPS"
        self._emit("info", f"Holdover-Test gestartet: {fmt_span(hours * 3600)} ohne {what} – chrony misst "
                           "weiter, stellt die Uhr aber nicht. Clients bekommen in der Zeit eine ungenauere Zeit.",
                   {"hours": hours, "include_network": include, "limit_ms": limit, "targets": len(targets),
                    "references": len(refs)})
        return self.status()

    def _finish(self, outcome: str, select: dict[str, dict] | None, why: str = "") -> dict[str, Any]:
        state = self.state()
        released, failed = selectctl.release(OWNER, select)
        now = self.wall()
        points = self._points()
        duration = max(0.0, now - float(state.get("started") or now))
        dev = float(state.get("last_dev") or 0.0)
        limit = float(state.get("limit_ms") or LIMIT_DEFAULT_MS) / 1000.0
        network = state.get("include_network") is not False
        if outcome == "done" and not network:
            # Nur GPS/PPS abgewählt: Das Netz hat die Uhr weiter gestellt – kein Freilauf, also auch
            # keine Aussage „die Uhr hält …“.
            sentence = (f"Ohne GPS/PPS: Abweichung {fmt_ms(dev)} in {fmt_span(duration)} – das Netz hat "
                        "die Uhr weiter geregelt (kein Freilauf)")
        elif outcome == "done":
            sentence = f"Die Uhr hält {fmt_ms(dev)} in {fmt_span(duration)}"
        elif outcome == "limit":
            sentence = (f"Grenze von {fmt_ms(limit)} nach {fmt_span(duration)} erreicht – die Uhr hält "
                        f"{fmt_ms(limit)} nur etwa {fmt_span(duration)}")
        elif outcome == "invalid":
            sentence = f"Test nach {fmt_span(duration)} ungültig – {why or 'eine neue Quelle ließ sich nicht abwählen'}"
        elif outcome == "restart":
            sentence = f"chronyd wurde neu gestartet – Test nach {fmt_span(duration)} abgebrochen, bis dahin {fmt_ms(dev)}"
        else:
            sentence = f"Abgebrochen nach {fmt_span(duration)} – bis dahin {fmt_ms(dev)}"
        result = {"started": state.get("started"), "ended": now, "planned_hours": state.get("hours"),
                  "duration_s": round(duration), "outcome": outcome, "deviation_ms": round(dev * 1000.0, 3),
                  "max_abs_ms": round(float(state.get("max_abs") or 0.0) * 1000.0, 3),
                  "drift_ppm": None, "limit_ms": state.get("limit_ms"),
                  "include_network": state.get("include_network"), "references": len(state.get("refs") or []),
                  "sentence": sentence, "why": why}
        ppm = slope_ppm(points)
        if ppm is not None:
            result["drift_ppm"] = round(ppm, 3)
        step = max(1, len(points) // CHART_POINTS)
        result["points"] = [[round(t), round(d * 1000.0, 3)] for t, d in points[::step]]
        try:
            _ensure()
            with store.transaction() as conn:
                conn.execute("INSERT INTO holdover_runs(started, json) VALUES(?, ?)",
                             (float(state.get("started") or now), json.dumps(result, separators=(",", ":"))))
                conn.execute("DELETE FROM holdover_runs WHERE id NOT IN "
                             "(SELECT id FROM holdover_runs ORDER BY id DESC LIMIT ?)", (KEEP_RESULTS,))
                conn.execute("DELETE FROM holdover_points")
        except Exception as exc:
            self.last_error = f"Ergebnis nicht gespeichert: {exc}"
        deferred = state.get("deferred") if isinstance(state.get("deferred"), dict) else {}
        reload_due = bool(state.get("reload_deferred"))
        carried = [p for p in state.get("resume") or [] if isinstance(p, str)]
        self._state = {"active": False, "changed": failed, "last_result": now,
                       "resume": sorted(set(deferred) | set(carried)),
                       "last_include_network": network, "last_targets": list(state.get("targets") or [])}
        self._noted = set()
        try:
            self._hold(None)
        except Exception:
            pass
        if reload_due:
            # Eine Automatik hatte gespeichert, als der Test gerade begann – ihr Neustart folgt jetzt.
            try:
                fn = _RELOAD.get("fn")
                if fn:
                    fn()
            except Exception:
                pass
        if failed:
            # Freigabe noch offen (chronyd antwortet nicht) – beim nächsten Durchgang erneut.
            self._state.update(release_pending=True)
            selectctl.register(OWNER, failed, failed)
        self._save()
        level = "info" if outcome in {"done", "aborted"} else "warn"
        title = {"done": "Holdover-Test beendet", "limit": "Holdover-Test abgebrochen (Grenze)",
                 "invalid": "Holdover-Test ungültig",
                 "restart": "Holdover-Test abgebrochen (chronyd neu gestartet)",
                 "aborted": "Holdover-Test abgebrochen"}[outcome]
        later = (f" Zurückgestellt, wird jetzt erneut geprüft: {'; '.join(str(v) for v in deferred.values())}."
                 if deferred else "")
        if reload_due:
            later += " Ein zurückgestellter Neustart der Zeitdienste folgt jetzt."
        self._emit(level, (f"{title}: {sentence}. Alle Quellen sind wieder auswählbar."
                           if not failed else f"{title}: {sentence}. Freigabe wird erneut versucht.") + later,
                   {"outcome": outcome, "deviation_ms": result["deviation_ms"], "duration_s": result["duration_s"],
                    "drift_ppm": result["drift_ppm"], "released": len(released),
                    "resumed": sorted(deferred)})
        return result

    def abort(self, select: dict[str, dict] | None = None) -> dict[str, Any]:
        with self.lock:
            if not self.state().get("active"):
                raise HoldoverError("Es läuft kein Holdover-Test.", conflict=True)
            self._finish("aborted", select, "von Hand")
            return self.status()

    def tick(self, cfg: dict, select: dict[str, dict] | None, sources: list[dict] | None = None) -> dict | None:
        """Ein Durchgang (eigener Thread, ~10 s): messen, Grenze/Ende/Neustart prüfen. Wirft nie."""
        with self.lock:
            try:
                return self._tick(select, sources)
            except Exception as exc:
                self.last_error = str(exc)
                return None

    def _tick(self, select: dict[str, dict] | None, sources: list[dict] | None) -> dict | None:
        state = self.state()
        if state.get("release_pending") and select:
            _released, failed = selectctl.release(OWNER, select)
            if not failed:
                state.pop("release_pending", None)
                state["changed"] = []
                self._save()
            return None
        if not state.get("active"):
            try:
                self._hold(None)     # übrig gebliebene Sperre (Absturz) – der Supervisor darf wieder
            except Exception:
                pass
            if select and selectctl.held(OWNER):
                # Haltertabelle sagt „hält noch“, der Test läuft aber nicht (Absturz zwischen zwei
                # Schreibvorgängen): freigeben, sonst bliebe eine Quelle dauerhaft abgewählt.
                released, _failed = selectctl.release(OWNER, select)
                if released:
                    self._emit("info", f"Holdover-Test: übrig gebliebene Abwahl aufgehoben ({', '.join(released)})",
                               {"released": len(released)})
            return None
        self._refresh_hold()
        if not select:
            # chronyd antwortet gerade nicht – Neustart erkennt der nächste Durchgang. Die Frist gilt
            # trotzdem: sonst bliebe die Sperre für Automatiken bei einem hängenden chronyd ewig stehen.
            if self.remaining(state) <= 0:
                return self._finish("done", {}, "chronyd antwortete zum Ende nicht")
            return None
        if selectctl.lost(OWNER, state.get("changed") or [], select):
            return self._finish("restart", select, "chronyd hat die Abwahl beim Neustart vergessen")
        self._confirmed = True
        sources = selectctl.port().sources() if sources is None else sources
        invalid = self._new_sources(state, select, sources)
        if invalid:
            return self._finish("invalid", select, invalid)
        now = self.wall()
        start_offsets = state.get("start_offsets")
        if isinstance(start_offsets, dict) and start_offsets:
            # Je Referenz: Offset jetzt − Offset beim Start; davon der Median über die, die gerade
            # erreichbar sind. Zu wenige gemeinsame Referenzen → dieser Durchgang zählt nicht.
            now_refs = references(sources)
            deltas = [off - float(start_offsets[name]) for name, off in now_refs.items()
                      if _num(start_offsets.get(name)) is not None]
            state["measured"] = len(deltas)
            dev = _median(deltas) if len(deltas) >= MIN_REFS else None
        else:   # Zustand aus einer Vorabversion ohne Werte je Referenz
            refs = references(sources, state.get("refs")) or references(sources)
            state["measured"] = len(refs)
            start = _num(state.get("start_offset"))
            dev = _median(list(refs.values())) - start if refs and start is not None else None
        if dev is not None:
            state["last_dev"] = dev
            state["max_abs"] = max(float(state.get("max_abs") or 0.0), abs(dev))
            if now - float(state.get("last_point") or 0.0) >= POINT_EVERY:
                state["last_point"] = now
                try:
                    _ensure()
                    store.execute("INSERT INTO holdover_points(t, dev) VALUES(?, ?)", (now, dev))
                except Exception as exc:
                    self.last_error = str(exc)
            self._save()
            if abs(dev) * 1000.0 > float(state.get("limit_ms") or LIMIT_DEFAULT_MS):
                return self._finish("limit", select, f"|Zeitfehler| {fmt_ms(dev)} über der Grenze")
        if self.remaining(state) <= 0:
            return self._finish("done", select)
        return None

    def _new_sources(self, state: dict, select: dict[str, dict], sources: list[dict] | None) -> str:
        """Quellen, die chrony erst während des Tests aufgenommen hat, mit abwählen.

        Gibt einen Grund zurück, wenn das nicht geht (Test ungültig), sonst ""."""
        include = state.get("include_network") is not False
        targets = list(state.get("targets") or [])
        new = []
        for src in sources or []:
            if not isinstance(src, dict):
                continue
            name = src.get("name")
            if not name or name in targets or name not in select or selectctl.effective_noselect(select[name]):
                continue
            if src.get("mode") == "#" or (include and src.get("mode") in {"^", "="}):
                new.append(str(name))
        if not new:
            return ""
        bad = [n for n in new if not selectctl.valid_name(n)]
        if bad:
            return f"neue Quelle mit unerwartetem Namen ({len(bad)}) – nicht abwählbar"
        try:
            changed = selectctl.hold(OWNER, new, select)
        except selectctl.SelectError as exc:
            return f"neue Quelle {', '.join(new)} ließ sich nicht abwählen ({exc})"
        state["targets"] = targets + new
        state["changed"] = list(state.get("changed") or []) + [n for n in changed if n not in (state.get("changed") or [])]
        self._save()
        self._emit("info", f"Holdover-Test: neue Quelle {', '.join(new)} mit abgewählt – chrony hat sie während "
                           "des Tests aufgenommen (z. B. Ersatz für ein Pool-Mitglied)", {"targets": len(new)})
        return ""

    # --- Automatiken warten ------------------------------------------------------------------------
    def _refresh_hold(self) -> None:
        # Echte Uhr: der Supervisor vergleicht mit date +%s. Nie länger als bis kurz nach der Frist.
        try:
            left = self.remaining()
            self._hold(time.time() + min(HOLD_TTL, max(0.0, left) + HOLD_TTL))
        except Exception:
            pass

    def _peek(self) -> dict[str, Any]:
        """Zustand ohne auf die Sperre zu warten (der Test-Thread hält sie auch während chronyc-Aufrufen).
        Ein Lesen der Referenz ist atomar; nur beim allerersten Mal wird geladen."""
        state = self._state
        if state is None:
            with self.lock:
                state = self.state()
        return state

    def running(self) -> bool:
        return bool(self._peek().get("active"))

    def defer(self, who: str, what: str) -> bool:
        """Eine Automatik (who) will chronyd neu starten, um `what` zu übernehmen. True: Test läuft –
        zurückstellen (ein Ereignis je Automatik und Test); nach dem Ende liefert resume(who) True."""
        with self.lock:
            state = self.state()
            if not state.get("active"):
                return False
            deferred = state.get("deferred") if isinstance(state.get("deferred"), dict) else {}
            first = who not in deferred
            if deferred.get(who) != what:
                deferred[who] = what
                state["deferred"] = deferred
                try:
                    self._save()
                except Exception as exc:
                    self.last_error = str(exc)
            if self._confirmed and (first or who not in self._noted):
                self._noted.add(who)
                self._emit("info", f"{what} – {DEFER_TEXT}: Ein Neustart von chronyd bräche den Test ab. "
                                   "Wird danach automatisch erneut geprüft.", {"deferred": who})
            return True

    def reload_or_defer(self, trigger: Callable[[], Any] | None) -> bool:
        """Neustart für eine Automatik, die schon gespeichert hat: Unter der Sperre noch einmal prüfen –
        läuft inzwischen ein Test (gerade eben gestartet), folgt der Neustart erst nach dessen Ende.
        True = ausgelöst oder fest vorgemerkt."""
        with self.lock:
            state = self.state()
            if state.get("active"):
                if not state.get("reload_deferred"):
                    state["reload_deferred"] = True
                    try:
                        self._save()
                    except Exception as exc:
                        self.last_error = str(exc)
                    if self._confirmed:
                        self._emit("info", f"Neustart der Zeitdienste – {DEFER_TEXT}: Ein Neustart von chronyd "
                                           "bräche den Test ab.", {"deferred": "reload"})
                return True
            return bool(trigger()) if trigger else False

    def resume(self, who: str) -> bool:
        """True genau einmal nach dem Ende eines Tests, während dessen `who` zurückgestellt war."""
        with self.lock:
            state = self.state()
            pending = state.get("resume") if isinstance(state.get("resume"), list) else []
            if state.get("active") or who not in pending:
                return False
            state["resume"] = [p for p in pending if p != who]
            try:
                self._save()
            except Exception as exc:
                self.last_error = str(exc)
            return True

    def caused_by_test(self, data: dict | None = None) -> bool:
        """Erklärt der laufende (oder gerade beendete) Test dieses Quellen-Ereignis?

        Mit Netzquellen abgewählt: jeder Quellenwechsel. Nur GPS/PPS abgewählt: nur Wechsel von oder zu
        einem Testziel – „keine Zeitquelle mehr“ nie, denn dann fiel das Netz wirklich aus."""
        state = self._peek()
        if state.get("active"):
            network = state.get("include_network") is not False
            targets = state.get("targets") or []
        else:
            ended = _num(state.get("last_result"))
            if ended is None or not 0.0 <= self.wall() - ended <= EVENT_GRACE:
                return False
            network = state.get("last_include_network") is not False
            targets = state.get("last_targets") or []
        if data is None or network:
            return True
        if not isinstance(data, dict) or "to" not in data or data.get("to") is None:
            return False
        names = {str(data.get("from") or ""), str(data.get("to") or "")}
        return bool(names & {str(t) for t in targets})

    # --- Anzeige ---------------------------------------------------------------------------------
    def results(self) -> list[dict]:
        try:
            _ensure()
            rows = store.query("SELECT id, json FROM holdover_runs ORDER BY id DESC LIMIT ?", (KEEP_RESULTS,))
        except Exception:
            return []
        out = []
        for ident, raw in rows:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                item["id"] = ident
                out.append(item)
        return out

    def freeze_intervals(self) -> list[tuple[float, float]]:
        """Zeiträume (start, ende) mit eingefrorener Frequenz: Holdover-Tests mit Netzquellen abgewählt –
        chronyd führte die Frequenz dabei nicht nach (Diagnosepaket 2306, Allan-Abweichung). Ein laufender
        Test zählt bis jetzt. Tests nur mit GPS/PPS abgewählt zählen nicht: Dort regelte das Netz weiter."""
        out: list[tuple[float, float]] = []
        for item in self.results():
            start, end = _num(item.get("started")), _num(item.get("ended"))
            if item.get("include_network") is False or start is None or end is None or end < start:
                continue
            out.append((start, end))
        state = self._peek()
        start = _num(state.get("started"))
        if state.get("active") and state.get("include_network") is not False and start is not None:
            out.append((start, max(start, self.wall())))
        return sorted(out)

    def status(self, select: dict[str, dict] | None = None, sources: list[dict] | None = None) -> dict[str, Any]:
        with self.lock:
            state = self.state()
            out: dict[str, Any] = {"active": bool(state.get("active")), "results": self.results(),
                                   "defaults": {"hours": HOURS_DEFAULT, "limit_ms": LIMIT_DEFAULT_MS,
                                                "hours_min": HOURS_MIN, "hours_max": HOURS_MAX,
                                                "limit_min_ms": LIMIT_MIN_MS, "limit_max_ms": LIMIT_MAX_MS,
                                                "min_references": MIN_REFS},
                                   "error": self.last_error}
            if state.get("active"):
                now = self.wall()
                points = self._points()
                step = max(1, len(points) // CHART_POINTS)
                out["run"] = {
                    "started": state.get("started"), "deadline": state.get("deadline"), "hours": state.get("hours"),
                    "elapsed_s": round(max(0.0, now - float(state.get("started") or now))),
                    "remaining_s": round(max(0.0, self.remaining(state))),
                    "include_network": state.get("include_network"), "limit_ms": state.get("limit_ms"),
                    "targets": len(state.get("targets") or []), "references": len(state.get("refs") or []),
                    "measured": state.get("measured"),
                    "deferred": [str(v) for v in (state.get("deferred") or {}).values()]
                    if isinstance(state.get("deferred"), dict) else [],
                    "deviation_ms": round(float(state.get("last_dev") or 0.0) * 1000.0, 3),
                    "max_abs_ms": round(float(state.get("max_abs") or 0.0) * 1000.0, 3),
                    "drift_ppm": None if slope_ppm(points) is None else round(slope_ppm(points), 3),
                    "points": [[round(t), round(d * 1000.0, 3)] for t, d in points[::step]],
                }
            elif select is not None:
                out["check"] = self.check(select, sources)
            return out


TEST = HoldoverTest()


def defer(who: str, what: str) -> bool:
    """Für Automatiken (gpsquality, autocal): True = Holdover-Test läuft, Neustart zurückstellen. Wirft nie."""
    try:
        return TEST.defer(who, what)
    except Exception:
        return False


def reload_or_defer(trigger: Callable[[], Any] | None) -> bool:
    """Für Automatiken nach dem Speichern: neu starten – oder, wenn gerade ein Test begonnen hat, danach."""
    try:
        return TEST.reload_or_defer(trigger)
    except Exception:
        return bool(trigger()) if trigger else False


def resume(who: str) -> bool:
    """Für Automatiken: True einmal nach dem Test, wenn `who` zurückgestellt war → jetzt prüfen. Wirft nie."""
    try:
        return TEST.resume(who)
    except Exception:
        return False


# Ereignisse, die ein Holdover-Test selbst auslöst (Kennzeichen in data.subject bzw. Art):
TEST_SUBJECTS = {"gps-sperre-ausgelassen"}
NOTE = " (Holdover-Test)"


def event_filter(kind: str, level: str, title: str, data: dict | None) -> tuple[str, str, dict | None]:
    """events.add_filter: Folgen des Tests (Quelle abgewählt/gewechselt, keine Quelle, Schleife „antwortet
    nicht“, GPS-Sperre ausgelassen) während des Tests und EVENT_GRACE danach als „info“ ohne
    Benachrichtigung. Eine erkannte Schleife (crit) bleibt, was sie ist. Wirft nie."""
    try:
        info = data if isinstance(data, dict) else {}
        if info.get("subject") == "holdover" or info.get("holdover_test"):
            return level, title, data
        if str(info.get("subject") or "") in TEST_SUBJECTS:
            ours = TEST.running()   # nur solange der Test läuft – danach zählt der Hinweis wieder
        else:
            ours = kind == "source" and level != "crit" and TEST.caused_by_test(info)
        if not ours:
            return level, title, data
        out = dict(info, notify=False, holdover_test=True)
        if level != "info":
            out["original_level"] = level
        return "info", (title if title.endswith(NOTE) else title + NOTE), out
    except Exception:
        return level, title, data


def action(data: dict) -> dict[str, Any]:
    """POST /api/holdover: {"action": "start", "hours": 2, "include_network": true, "limit_ms": 10} | {"action": "abort"}."""
    what = str((data or {}).get("action") or "")
    if what == "start":
        return TEST.start(data)
    if what == "abort":
        return TEST.abort()
    raise HoldoverError("action muss „start“ oder „abort“ sein")


def api_status() -> dict[str, Any]:
    port = selectctl.port()
    try:
        select = selectctl.by_name(port.selectdata())
        sources = port.sources()
    except Exception:
        select, sources = {}, []
    return TEST.status(select, sources)


def insights(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Hinweis in der Übersicht, solange ein Holdover-Test läuft (Clients bekommen ungenauere Zeit)."""
    run = status.get("run") if status.get("active") else None
    if not run:
        return []
    remaining = fmt_span(float(run.get("remaining_s") or 0))
    return [{"level": "warn", "key": "holdover_running", "action": "uhrqualitaet", "title": "Holdover-Test läuft",
             "text": f"chrony stellt die Uhr gerade nicht nach (noch {remaining}, Zeitfehler bisher "
                     f"{fmt_ms(float(run.get('deviation_ms') or 0) / 1000.0)}). Clients bekommen in der Zeit eine "
                     "ungenauere Zeit. Abbrechen auf der Seite Uhrqualität."}]
