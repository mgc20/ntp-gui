"""Automatische GPS-Kalibrierung: aus / vorschlagen / automatisch – behutsam, umkehrbar.

Ein USB-GPS meldet die Zeit (NMEA) mit einer festen Verspätung. history.calibrate()
misst sie als Median der Differenz GPS − Netzwerkquellen. Dieses Modul entscheidet,
ob daraus ein Vorschlag wird oder – im Modus „automatisch“ – eine Änderung von
gps_offset, und führt ein Änderungsprotokoll mit Rücknahme.

Aufbau:
  * decide(cfg, calibration_result, last_change, now) – reine Funktion, keine
    Seiteneffekte, vollständig getestet. Sie bekommt alles, was sie braucht, im
    Kalibrierergebnis; die Angaben zu den Vergleichsquellen stehen dort unter
    "reference" (siehe reference_stats() und summarize_sources()).
  * tick(cfg, now) – holt Messung und Quellen über austauschbare Funktionen
    (configure()), ruft decide() auf, speichert ggf. die Einstellung, löst den
    Neustart der Zeitdienste aus, schreibt ein Ereignis und das Protokoll.
  * rollback(steps) – nimmt die letzten automatischen Änderungen zurück.
  * api_status(cfg, now) – alles für GET /api/gps/autocal.

Regeln (bewusst vorsichtig – lieber eine Änderung zu wenig als eine falsche):
  1. Nur mit Status "ready" von calibrate() und mindestens gps_autocal_min_hours
     gemeinsamer Messdauer. Die Messung zählt erst ab SETTLE_SECONDS nach der
     letzten Offset-Änderung (egal ob automatisch oder von Hand) – sonst mischte
     der Median Werte vor und nach der Änderung.
  2. Vertrauenswürdige Netzreferenz: im Messzeitraum im Median mindestens zwei
     genutzte (ausgewählt „*“ oder kombiniert „+“) Netzwerkquellen ODER jetzt
     mindestens eine genutzte NTS-authentifizierte Quelle. Eine einzelne
     unauthentifizierte Quelle könnte selbst danebenliegen.
  3. Ist gerade keine Netzwerkquelle nutzbar (Internet weg, GPS die einzige
     Quelle), passiert nichts – ohne Vergleich gibt es nichts zu messen.
  4. Schwelle mit Hysterese: |Abweichung| ≥ max(1 ms, 3 · Streuung / √n_eff).
     n_eff = Zahl der *unabhängigen* Messungen: aufeinanderfolgende Werte im
     10-s-Takt hängen stark zusammen (Netzlaufzeit ändert sich langsam), darum
     zählt höchstens eine Messung je 10 Minuten. Zeigt die neue Korrektur in die
     Gegenrichtung der letzten automatischen Änderung (innerhalb von 7 Tagen),
     gilt die doppelte Schwelle – so pendelt der Offset nicht hin und her.
  5. Streuung über 25 ms oder Abweichung über 0,5 s: nichts automatisch ändern,
     nur vorschlagen – da stimmt etwas Grundsätzliches nicht (falsches Gerät,
     stark schwankende Leitung), das soll ein Mensch ansehen.
  6. Höchstens eine automatische Änderung je 24 h (auch eine Rücknahme startet
     die 24 h neu), Schrittweite höchstens gps_autocal_max_step_ms. Größere
     Abweichungen werden über mehrere Tage in Schritten abgebaut.
  7. Wirksamkeit: Vor jeder weiteren Änderung muss belegt sein, dass die letzte
     automatische Änderung (oder Rücknahme) wirklich läuft – laut
     RUN_DIR/reload.json (Neuladen „done“ nach der Änderung) bzw. laut dem
     Offset in der GPS-Refclock-Zeile von CHRONY_CONF. Ist das Neuladen
     gescheitert oder nicht belegbar, wird nichts weiter verstellt – sonst
     stiege der gespeicherte Offset Tag für Tag, während chronyd den alten
     weiterbenutzt. Die Messung zählt erst ab dem Zeitpunkt, an dem die
     Änderung nachweislich aktiv wurde.
  8. Delay: Beim letzten Schritt (Rest unter der Schwelle) wird der Delay-
     Vorschlag aus calibrate() übernommen; vorher wird der Delay nie verkleinert
     (höchstens vergrößert) – ein kleiner Delay macht das GPS chrony gegenüber
     attraktiver, das soll erst mit stimmendem Offset passieren.

Datenschutz: Protokoll und Ereignisse enthalten nur Offsets, Zeiten und
Begründungen – keine Position, keine Quellnamen, keine Adressen.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from typing import Any, Callable

import settings

STATE_FILE = "autocal.json"
STATE_VERSION = 1
MAX_LOG = 100                  # so viele Protokolleinträge bleiben erhalten

DAY = 86400.0
AUTO_INTERVAL = DAY            # höchstens eine automatische Änderung je 24 h
TICK_INTERVAL = 3600.0         # maybe_tick(): Prüfung einmal pro Stunde
SETTLE_SECONDS = 900.0         # nach einer Offset-Änderung: Neustart + Medianfilter abwarten
MIN_THRESHOLD = 0.001          # 1 ms – darunter lohnt sich keine Änderung
SIGMA = 3.0                    # Abweichung muss 3 Standardfehler groß sein
INDEPENDENT_SECONDS = 600.0    # eine unabhängige Messung je 10 min
REVERSAL_FACTOR = 2.0          # Gegenrichtung braucht doppelte Schwelle …
REVERSAL_HORIZON = 7 * DAY     # … solange die letzte Änderung jünger ist als 7 Tage
MAX_SPREAD = 0.025             # darüber nur noch Vorschläge
MAX_AUTO_BIAS = 0.5            # darüber nur noch Vorschläge
OFFSET_LIMITS = (-2.0, 2.0)    # Wertebereich von gps_offset in settings.py
OFFSET_EPS = 5e-5              # Offsets gelten als gleich (Rundung auf 0,1 ms)
CAL_CACHE_SECONDS = 300.0      # api_status(fresh=True): Messung höchstens so lange wiederverwenden

MODE_LABELS = {"off": "aus", "suggest": "vorschlagen", "auto": "automatisch"}
MODE_TEXTS = {
    "off": "Es wird nichts vorgeschlagen und nichts geändert. Den Kalibrier-Assistenten oben kannst "
           "du trotzdem jederzeit von Hand nutzen.",
    "suggest": "ntp-gui misst laufend und zeigt dir, sobald die Messung belastbar ist, einen "
               "passenden Offset. Übernehmen musst du ihn selbst – nichts ändert sich von allein.",
    "auto": "ntp-gui stellt den Offset selbst nach – aber nur nach genug Messdauer, nur mit "
            "vertrauenswürdigen Netzwerkquellen als Vergleich, höchstens einmal am Tag und in "
            "kleinen Schritten. Jede Änderung steht unten und im Ereignisprotokoll und lässt sich "
            "zurücknehmen.",
}

_LOCK = threading.RLock()


class AutocalError(ValueError):
    """Rücknahme nicht möglich – die Meldung ist für Menschen gedacht (deutsch)."""


# ---------------------------------------------------------------------------
# Kleine Helfer
# ---------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _ms(seconds: float) -> str:
    """Sekunden als „12,3 ms“ (deutsches Komma)."""
    return f"{seconds * 1000:.1f}".replace(".", ",") + " ms"


def _signed_ms(seconds: float) -> str:
    return ("+" if seconds > 0 else "") + _ms(seconds)


def _hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f}".replace(".", ",") + " h"


def _when(t: float) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(t))


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _mode(cfg: dict) -> str:
    mode = cfg.get("gps_autocal")
    return mode if mode in MODE_LABELS else "off"


def _cfg_float(cfg: dict, key: str, default: float) -> float:
    value = _num(cfg.get(key))
    return default if value is None else value


# ---------------------------------------------------------------------------
# Vergleichsquellen
# ---------------------------------------------------------------------------

_NETWORK_MODES = {"^", "="}
_USED_STATES = {"*", "+"}


def reference_stats(samples: list[dict], gps_name: str) -> dict:
    """Wie viele genutzte Netzwerkquellen hatte jede Messung im Zeitfenster?

    Gezählt wie in history.calibrate(): Quellen außer dem GPS mit Zustand „*“
    oder „+“, die keine Refclock („#“) sind. Nur Messungen mit GPS-Wert zählen.
    """
    counts = []
    for sample in samples or []:
        sources = sample.get("sources") or {}
        gps = sources.get(gps_name)
        if not _gps_measured(gps):
            continue
        counts.append(sum(1 for name, v in sources.items()
                          if name != gps_name and isinstance(v, dict) and v.get("s") in _USED_STATES
                          and v.get("k") != "#" and _num(v.get("o")) is not None))
    with_ref = [c for c in counts if c > 0]
    return {
        "window_samples": len(with_ref),
        "window_median": _median(with_ref) if with_ref else 0,
        "window_min": min(with_ref) if with_ref else 0,
    }


def _gps_measured(gps: Any) -> bool:
    """Wie history.gps_measured() – GPS-Wert wirklich gemessen (nicht „?“, „x“, „~“, Reach 0)."""
    import history as historymod
    return historymod.gps_measured(gps)


def _is_nts(source: dict) -> bool:
    if source.get("authenticated") is True:
        return True
    auth = source.get("auth")
    return isinstance(auth, dict) and str(auth.get("mode", "")).upper() == "NTS"


def summarize_sources(sources: list[dict] | None, gps_name: str) -> dict:
    """Aktuelle Lage aus chrony.detailed_sources(): genutzte Netz- und NTS-Quellen."""
    network = nts = 0
    gps_used = False
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        used = source.get("state") in _USED_STATES
        if source.get("mode") in _NETWORK_MODES:
            if used:
                network += 1
                if _is_nts(source):
                    nts += 1
        elif source.get("name") == gps_name and used:
            gps_used = True
    return {"current_network": network, "current_nts": nts, "gps_used": gps_used}


# ---------------------------------------------------------------------------
# Entscheidung (rein)
# ---------------------------------------------------------------------------

def threshold(spread: float, samples: int, duration: float) -> float:
    """Mindestabweichung für eine Änderung (s), siehe Modulbeschreibung Punkt 4."""
    n_eff = max(1.0, min(float(samples), duration / INDEPENDENT_SECONDS))
    return max(MIN_THRESHOLD, SIGMA * max(0.0, spread) / math.sqrt(n_eff))


def _result(action: str, reason: str, cfg: dict, **extra) -> dict:
    out = {"action": action, "reason": reason, "mode": _mode(cfg),
           "new_offset": None, "new_delay": None, "step_ms": None}
    out.update(extra)
    return out


def decide(cfg: dict, calibration_result: dict | None, last_change: dict | None,
           now: float) -> dict:
    """Entscheidet über Vorschlag oder automatische Änderung. Keine Seiteneffekte.

    calibration_result: Ausgabe von history.calibrate() plus "reference" mit
      window_median (Median der genutzten Netzwerkquellen je Messung),
      current_network, current_nts (aktuell genutzte Netz-/NTS-Quellen).
    last_change: letzter Protokolleintrag einer automatischen Änderung oder
      Rücknahme ({"t", "kind", "old_offset", "new_offset"}) oder None.

    Rückgabe: {"action": "none"|"suggest"|"apply", "reason", "new_offset",
      "new_delay", "step_ms", ...} plus Messwerte (bias_ms, threshold_ms,
      target_offset, next_change_at) für die Anzeige.
    """
    mode = _mode(cfg)
    if mode == "off":
        return _result("none", "Die automatische Kalibrierung ist ausgeschaltet.", cfg)
    if not cfg.get("gps_enable"):
        return _result("none", "Das GPS ist nicht eingeschaltet – es gibt nichts zu kalibrieren.", cfg)
    cal = calibration_result if isinstance(calibration_result, dict) else {}
    status = cal.get("status")
    duration = _num(cal.get("duration_seconds")) or 0.0
    min_hours = _cfg_float(cfg, "gps_autocal_min_hours", 6.0)
    base = {"duration_seconds": duration, "min_seconds": min_hours * 3600}

    if status == "insufficient" or status is None:
        return _result("none", "Noch zu wenige gemeinsame Messungen von GPS und Netzwerkquellen. "
                       "Es braucht GPS-Werte und gleichzeitig mindestens eine genutzte Netzwerkquelle.",
                       cfg, **base)
    if status == "preliminary":
        return _result("none", f"Erst {_hours(duration)} gemessen – für einen belastbaren Wert "
                       f"wartet ntp-gui mindestens {_hours(min_hours * 3600)}.", cfg, **base)

    bias = _num(cal.get("bias"))
    spread = _num(cal.get("spread"))
    samples = int(_num(cal.get("samples")) or 0)
    current = _num(cal.get("current_offset"))
    if current is None:
        current = _cfg_float(cfg, "gps_offset", 0.0)
    current_delay = _num(cal.get("current_delay"))
    if current_delay is None:
        current_delay = _cfg_float(cfg, "gps_delay", 0.2)
    suggested_delay = _num(cal.get("suggested_delay"))
    if suggested_delay is None:
        suggested_delay = current_delay
    if bias is not None:
        base["bias_ms"] = round(bias * 1000, 3)
    if spread is not None:
        base["spread_ms"] = round(spread * 1000, 3)

    if status == "calibrated":
        return _result("none", "Das GPS ist gut kalibriert – die Abweichung liegt im Rauschen.",
                       cfg, **base)
    if status != "ready" or bias is None or spread is None:
        return _result("none", "Das Kalibrierergebnis ist unvollständig – es wird nichts geändert.",
                       cfg, **base)
    if duration < min_hours * 3600:
        return _result("none", f"Erst {_hours(duration)} von {_hours(min_hours * 3600)} Mindest-"
                       "Messdauer seit der letzten Änderung – mehrere Stunden glätten Tages"
                       "schwankungen der Netzlaufzeit.", cfg, **base)

    # --- Vergleichsquellen -------------------------------------------------
    ref = cal.get("reference") if isinstance(cal.get("reference"), dict) else {}
    current_network = _num(ref.get("current_network"))
    current_nts = _num(ref.get("current_nts")) or 0
    window_median = _num(ref.get("window_median"))
    base["reference"] = {"current_network": current_network, "current_nts": current_nts,
                         "window_median": window_median}
    if current_network is None:
        return _result("none", "Keine Angaben zu den Netzwerkquellen – ohne geprüften Vergleich "
                       "wird nichts geändert.", cfg, **base)
    if current_network < 1:
        return _result("none", "Gerade ist keine Netzwerkquelle nutzbar – das GPS ist die einzige "
                       "Quelle (Internet weg?). Ohne Vergleich lässt sich die Verspätung nicht "
                       "messen, darum bleibt alles, wie es ist.", cfg, **base)
    window_count = window_median if window_median is not None else current_network
    if window_count < 2 and current_nts < 1:
        return _result("none", "Als Vergleich diente nur eine einzige Netzwerkquelle ohne NTS. "
                       "Geht genau diese falsch, wäre auch die Kalibrierung falsch – nötig sind "
                       "mindestens zwei genutzte Netzwerkquellen oder eine mit NTS.", cfg, **base)

    # --- Schwelle mit Hysterese ---------------------------------------------
    thr = threshold(spread, samples, duration)
    last_t = _num((last_change or {}).get("t"))
    reversal = False
    if last_change and last_change.get("kind", "auto") == "auto" and last_t is not None \
            and now - last_t < REVERSAL_HORIZON:
        old, new = _num(last_change.get("old_offset")), _num(last_change.get("new_offset"))
        if old is not None and new is not None and (new - old) * bias < 0:
            thr *= REVERSAL_FACTOR
            reversal = True
    target = round(current + bias, 4)
    base.update(threshold_ms=round(thr * 1000, 3), target_offset=target)
    if abs(bias) < thr:
        extra = " (doppelte Schwelle, weil die Korrektur die letzte Änderung umkehren würde)" \
            if reversal else ""
        return _result("none", f"Die Abweichung von {_signed_ms(bias)} liegt unter der Schwelle von "
                       f"{_ms(thr)}{extra} – keine Änderung nötig.", cfg, **base)
    if not (OFFSET_LIMITS[0] <= target <= OFFSET_LIMITS[1]):
        return _result("none", f"Der rechnerische Offset {target} s läge außerhalb des erlaubten "
                       "Bereichs von −2 bis 2 s. Prüfe Gerät und Einstellungen.", cfg, **base)

    full_step_ms = round((target - current) * 1000, 3)
    suggestion = _result("suggest", "", cfg, new_offset=target, new_delay=round(suggested_delay, 4),
                         step_ms=full_step_ms, **base)
    if mode == "suggest":
        suggestion["reason"] = (f"Das GPS liegt {_signed_ms(bias)} neben den Netzwerkquellen. "
                                f"Vorschlag: Offset {target} s – übernimm ihn mit „Vorschlag übernehmen“.")
        return suggestion

    # --- Modus „automatisch“ -------------------------------------------------
    if spread > MAX_SPREAD:
        suggestion["reason"] = (f"Die Messwerte streuen um {_ms(spread)} – zu unruhig für eine "
                                "automatische Änderung. Vorschlag zum Prüfen: Offset "
                                f"{target} s.")
        return suggestion
    if abs(bias) > MAX_AUTO_BIAS:
        suggestion["reason"] = (f"Eine Abweichung von {_signed_ms(bias)} ist für einen USB-Empfänger "
                                "ungewöhnlich groß (falsches Gerät? falsche Zeitzone im Empfänger?). "
                                f"Automatisch wird nichts geändert; Vorschlag zum Prüfen: {target} s.")
        return suggestion
    if last_t is not None and now - last_t < AUTO_INTERVAL:
        next_at = last_t + AUTO_INTERVAL
        return _result("none", f"Abweichung {_signed_ms(bias)}. Die letzte automatische Änderung ist "
                       f"keine 24 h her – die nächste ist frühestens am {_when(next_at)} möglich.",
                       cfg, next_change_at=next_at, **base)

    max_step = max(0.0001, _cfg_float(cfg, "gps_autocal_max_step_ms", 5.0) / 1000)
    step = math.copysign(min(abs(bias), max_step), bias)
    new_offset = round(current + step, 4)
    if abs(new_offset - current) < OFFSET_EPS:
        return _result("none", "Der Schritt wäre kleiner als 0,1 ms – keine Änderung.", cfg, **base)
    remaining = target - new_offset
    final = abs(remaining) < thr
    new_delay = suggested_delay if final else max(current_delay, suggested_delay)
    if final:
        reason = (f"Das GPS lag {_signed_ms(bias)} neben {int(window_count)} Netzwerkquelle(n) "
                  f"(Messung über {_hours(duration)}). Offset {current} s → {new_offset} s.")
    else:
        reason = (f"Das GPS lag {_signed_ms(bias)} neben {int(window_count)} Netzwerkquelle(n). "
                  f"Erster Teilschritt von höchstens {_ms(max_step)}: Offset {current} s → "
                  f"{new_offset} s; der Rest folgt frühestens in 24 h nach neuer Messung.")
    return _result("apply", reason, cfg, new_offset=new_offset, new_delay=round(new_delay, 4),
                   step_ms=round((new_offset - current) * 1000, 3), final_step=final,
                   next_change_at=now + AUTO_INTERVAL, **base)


# ---------------------------------------------------------------------------
# Zustand (DATA_DIR/autocal.json)
# ---------------------------------------------------------------------------

def path() -> str:
    return os.path.join(settings.DATA_DIR, STATE_FILE)


def _empty() -> dict:
    return {"version": STATE_VERSION, "changes": [], "observed": None, "last_decision": None,
            "last_tick": None, "last_suggestion": None, "pending": None}


def load(file: str | None = None) -> dict:
    try:
        with open(file or path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    state = _empty()
    state.update({k: v for k, v in data.items() if k in state})
    if not isinstance(state["changes"], list):
        state["changes"] = []
    state["changes"] = [c for c in state["changes"] if isinstance(c, dict)]
    return state


def save(state: dict, file: str | None = None) -> None:
    """Atomar schreiben: temporäre Datei im selben Ordner, dann os.replace()."""
    file = file or path()
    folder = os.path.dirname(file) or "."
    os.makedirs(folder, mode=0o700, exist_ok=True)
    state = dict(state)
    state["changes"] = list(state.get("changes") or [])[-MAX_LOG:]
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".autocal-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _last_auto_event(state: dict) -> dict | None:
    """Letzte automatische Änderung oder Rücknahme (für 24-h-Sperre und Hysterese)."""
    for change in reversed(state.get("changes") or []):
        if change.get("kind") in {"auto", "rollback"}:
            return change
    return None


def _active_auto(state: dict) -> list[dict]:
    return [c for c in state.get("changes") or [] if c.get("kind") == "auto" and not c.get("rolled_back")]


def _observe(state: dict, offset: float, now: float) -> dict:
    """Merkt sich den Offset; ändert er sich (auch von Hand), beginnt die Messung neu."""
    observed = state.get("observed")
    if not isinstance(observed, dict) or _num(observed.get("offset")) is None \
            or _num(observed.get("since")) is None:
        observed = {"offset": offset, "since": now, "first": True}
        state["observed"] = observed
    elif abs(float(observed["offset"]) - offset) > OFFSET_EPS:
        observed = {"offset": offset, "since": now}
        state["observed"] = observed
    return observed


# ---------------------------------------------------------------------------
# Ist die letzte Änderung wirklich aktiv?
# ---------------------------------------------------------------------------

def _run_dir() -> str:
    return os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")


def _chrony_conf() -> str:
    return os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")


def conf_offset(text: str, refid: str) -> float | None:
    """Offset aus der Refclock-Zeile mit dieser refid (wie confgen sie schreibt) oder None."""
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) < 2 or parts[0] != "refclock":
            continue
        options = parts[3:] if len(parts) > 3 else []
        values = {}
        for key, value in zip(options, options[1:]):
            values.setdefault(key, value)
        if values.get("refid") != refid:
            continue
        try:
            value = float(values.get("offset", "0"))
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    return None


def _read_reload() -> dict | None:
    try:
        with open(os.path.join(_run_dir(), "reload.json"), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def check_active(cfg: dict, change: dict | None) -> dict:
    """Läuft der eingestellte gps_offset wirklich? Rückgabe {"active", "reason", "since"}.

    active: True (belegt), False (belegt NICHT aktiv: alte Konfiguration oder
    Neuladen fehlgeschlagen), None (nicht belegbar – z. B. ohne Supervisor).
    change: letzte automatische Änderung/Rücknahme ({"t", ...}) oder None.
    since: ab wann die Änderung aktiv ist (Zeit aus reload.json), sonst None.
    """
    want = _cfg_float(cfg, "gps_offset", 0.0)
    refid = str(cfg.get("gps_refid") or "GPS")
    running = None
    try:
        with open(_chrony_conf(), encoding="utf-8") as handle:
            running = conf_offset(handle.read(), refid)
    except (OSError, UnicodeDecodeError):
        running = None
    if running is not None and abs(running - want) > OFFSET_EPS:
        return {"active": False, "since": None,
                "reason": f"In der laufenden chrony-Konfiguration steht noch Offset {running} s "
                          f"statt {want} s."}
    t = _num((change or {}).get("t"))
    if t is None:
        return {"active": True, "since": None, "reason": ""}
    reload = _read_reload() or {}
    state, when = reload.get("state"), _num(reload.get("time"))
    fresh = when is not None and when >= t - 1  # Sekundenauflösung im Supervisor
    if fresh and state == "error":
        return {"active": False, "since": None,
                "reason": "Das Neuladen der Zeitdienste ist fehlgeschlagen (" +
                          str(reload.get("message") or "Konfiguration fehlerhaft") + ")."}
    if fresh and state == "running":
        return {"active": None, "since": None, "reason": "Die Zeitdienste werden gerade neu gestartet."}
    if fresh and state in {"done", "idle"}:
        return {"active": True, "since": when, "reason": ""}
    if running is not None:
        return {"active": True, "since": None, "reason": ""}
    return {"active": None, "since": None,
            "reason": "Es ist nicht belegbar, dass die Zeitdienste seit der Änderung neu geladen "
                      "wurden (kein Supervisor?)."}


# ---------------------------------------------------------------------------
# Abhängigkeiten (vom Server gesetzt, in Tests ersetzt)
# ---------------------------------------------------------------------------

_DEPS: dict[str, Callable | None] = {
    "get_calibration": None,   # (window_seconds) -> calibrate()-Ergebnis inkl. "reference"
    "get_sources": None,       # () -> chrony.detailed_sources()
    "save_settings": None,     # (changes) -> {"changed", "restart"}
    "trigger_reload": None,    # () -> bool
    "emit_event": None,        # (kind, level, title, data) -> None
    "check_active": None,      # (cfg, last_change) -> {"active", "reason", "since"}
}


def configure(history=None, **callables) -> None:
    """Setzt die Funktionen, über die autocal mit dem Rest spricht.

    history: ein history.History – daraus wird get_calibration gebaut.
    Weitere Schlüssel: get_calibration, get_sources, save_settings,
    trigger_reload, emit_event (siehe _DEPS).
    """
    if history is not None and "get_calibration" not in callables:
        callables["get_calibration"] = make_calibration_getter(history)
    unknown = set(callables) - set(_DEPS)
    if unknown:
        raise TypeError(f"Unbekannte Abhängigkeit: {', '.join(sorted(unknown))}")
    _DEPS.update(callables)


def make_calibration_getter(history, cfg_getter: Callable[[], dict] | None = None):
    """Baut get_calibration(window_seconds) aus einem history.History."""
    import history as historymod

    def get(window_seconds: float) -> dict:
        cfg = (cfg_getter or settings.values)()
        refid = cfg.get("gps_refid") or "GPS"
        samples = history.snapshot(time.time() - window_seconds if window_seconds > 0 else None)
        result = historymod.calibrate(samples, refid, float(cfg.get("gps_offset") or 0.0),
                                      float(cfg.get("gps_delay") or 0.2))
        result.pop("series", None)
        result["reference"] = reference_stats(samples, refid)
        return result
    return get


def _deps(overrides: dict | None = None) -> dict:
    deps = dict(_DEPS)
    deps.update(overrides or {})
    if deps["get_sources"] is None:
        def _sources():
            import chrony
            return chrony.detailed_sources()
        deps["get_sources"] = _sources
    if deps["save_settings"] is None:
        deps["save_settings"] = settings.save
    if deps["emit_event"] is None:
        def _emit(kind, level, title, data=None):
            import events
            events.emit(kind, level, title, data, source="autocal")
        deps["emit_event"] = _emit
    if deps["trigger_reload"] is None:
        deps["trigger_reload"] = lambda: False
    if deps["check_active"] is None:
        deps["check_active"] = check_active
    return deps


def _emit(deps: dict, kind: str, level: str, title: str, data: dict) -> None:
    try:
        deps["emit_event"](kind, level, title, data)
    except Exception:  # Ereignisse sind nett, aber nie kritisch
        pass


def _readonly() -> bool:
    return os.environ.get("WEB_READONLY", "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Auswertung, tick, Rücknahme
# ---------------------------------------------------------------------------

def _window(cfg: dict, observed: dict, now: float) -> float:
    min_seconds = _cfg_float(cfg, "gps_autocal_min_hours", 6.0) * 3600
    cap = max(DAY, 2 * min_seconds)
    return max(0.0, min(cap, now - float(observed["since"]) - SETTLE_SECONDS))


_NOT_ACTIVE = ("Die letzte Änderung ist noch nicht aktiv (Neuladen fehlgeschlagen?) – es wird "
               "nichts weiter verstellt.")


def _verify(cfg: dict, state: dict, deps: dict, now: float) -> dict:
    """Prüft, ob der eingestellte Offset läuft; ändert ggf. state["observed"]/["pending"].

    Wurde eine Änderung erst später aktiv (Neuladen verzögert, Container später
    neu gestartet), zählt die Messung ab diesem Zeitpunkt – davor lief noch der
    alte Offset und hätte den Median verfälscht.
    """
    last = _last_auto_event(state)
    try:
        check = dict(deps["check_active"](cfg, last) or {})
    except Exception as exc:
        check = {"active": None, "reason": f"Prüfung nicht möglich: {exc}"}
    pending = state.get("pending")
    if check.get("active") is True and isinstance(pending, dict):
        observed = state.get("observed") or {}
        since = _num(check.get("since"))
        if since is not None and _num(observed.get("since")) is not None \
                and abs(float(observed.get("offset", 0.0)) - _cfg_float(cfg, "gps_offset", 0.0)) <= OFFSET_EPS:
            observed["since"] = max(float(observed["since"]), min(since, now))
            state["observed"] = observed
        state["pending"] = None
    return check


def _evaluate(cfg: dict, now: float, state: dict, deps: dict, cached: bool = False) -> dict:
    """Messung holen und entscheiden – ändert nur state["observed"]/["pending"], sonst nichts."""
    offset = _cfg_float(cfg, "gps_offset", 0.0)
    observed = _observe(state, offset, now)
    active = None
    if _mode(cfg) != "off" and cfg.get("gps_enable"):
        active = _verify(cfg, state, deps, now)
        observed = state["observed"]
    window = _window(cfg, observed, now)
    info = {"window_seconds": window, "measuring_since": float(observed["since"]) + SETTLE_SECONDS}
    if _mode(cfg) == "off" or not cfg.get("gps_enable"):
        decision = decide(cfg, None, None, now)
    elif active is not None and active.get("active") is not True:
        reason = _NOT_ACTIVE
        if active.get("reason"):
            reason += " " + str(active["reason"])
        decision = _result("none", reason, cfg, not_active=True)
    elif window < 60 and observed.get("first"):
        decision = _result("none", "Die automatische Kalibrierung hat gerade zu messen begonnen. "
                           "Erste Entscheidung nach der Mindest-Messdauer.", cfg)
    elif window < 60:
        decision = _result("none", "Der Offset wurde gerade geändert. Die Messung beginnt "
                           f"{int(SETTLE_SECONDS // 60)} Minuten danach neu, damit chrony und der "
                           "Medianfilter sich einschwingen.", cfg)
    else:
        try:
            getter = deps["get_calibration"]
            if getter and cached:
                getter = _cached_getter(getter, cfg, now)
            cal = dict(getter(window) or {}) if getter else {}
        except Exception as exc:
            cal = {"status": "insufficient", "error": str(exc)}
        duration = _num(cal.get("duration_seconds"))
        if duration is not None and duration > window:
            cal["duration_seconds"] = window  # nie mehr Messdauer als das Fenster hergibt
        reference = dict(cal.get("reference") or {})
        try:
            reference.update(summarize_sources(deps["get_sources"](), cfg.get("gps_refid") or "GPS"))
        except Exception:
            pass  # ohne Quelleninfo verweigert decide() die Änderung
        cal["reference"] = reference
        decision = decide(cfg, cal, _last_auto_event(state), now)
    if decision["action"] == "apply" and _readonly():
        decision.update(action="suggest", reason=decision["reason"] + " Nicht übernommen: Die "
                        "Einstellungen sind gesperrt (WEB_READONLY).")
    decision.update(info)
    return decision


def tick(cfg: dict, now: float | None = None, deps: dict | None = None,
         file: str | None = None) -> dict:
    """Einmal prüfen und ggf. handeln. Gibt die Entscheidung zurück; wirft nie."""
    now = time.time() if now is None else now
    deps = _deps(deps)
    with _LOCK:
        state = load(file)
        decision = _evaluate(cfg, now, state, deps)
        if decision["action"] == "apply":
            decision = _apply(cfg, decision, state, deps, now)
        elif decision["action"] == "suggest":
            last = state.get("last_suggestion") or {}
            if _num(last.get("offset")) is None \
                    or abs(float(last["offset"]) - decision["new_offset"]) >= MIN_THRESHOLD:
                state["last_suggestion"] = {"offset": decision["new_offset"], "t": now}
                _emit(deps, "calibration", "info",
                      f"GPS-Kalibrierung: neuer Vorschlag {decision['new_offset']} s",
                      {"new_offset": decision["new_offset"], "new_delay": decision["new_delay"],
                       "bias_ms": decision.get("bias_ms"), "reason": decision["reason"]})
        state["last_decision"] = dict(decision, t=now)
        state["last_tick"] = now
        try:
            save(state, file)
        except OSError as exc:
            decision["error"] = f"Protokoll nicht gespeichert: {exc}"
    return decision


def _apply(cfg: dict, decision: dict, state: dict, deps: dict, now: float) -> dict:
    old_offset = _cfg_float(cfg, "gps_offset", 0.0)
    old_delay = _cfg_float(cfg, "gps_delay", 0.2)
    changes = {"gps_offset": decision["new_offset"]}
    if decision.get("new_delay") is not None and abs(decision["new_delay"] - old_delay) > 1e-9:
        changes["gps_delay"] = decision["new_delay"]
    try:
        result = deps["save_settings"](changes) or {}
    except Exception as exc:
        decision.update(action="none", error=str(exc),
                        reason=f"Die Änderung ließ sich nicht speichern: {exc}")
        _emit(deps, "calibration", "warn", "GPS-Kalibrierung: Änderung nicht gespeichert",
              {"error": str(exc)})
        return decision
    reloaded = False
    if result.get("restart"):
        try:
            reloaded = bool(deps["trigger_reload"]())
        except Exception:
            reloaded = False
        if not reloaded:
            decision["reason"] += (" Achtung: Die Zeitdienste ließen sich nicht neu starten – der neue "
                                   "Offset ist erst nach einem Neustart aktiv; bis dahin wird nichts "
                                   "weiter verstellt.")
    entry = {
        "id": _next_id(state), "t": now, "kind": "auto",
        "old_offset": old_offset, "new_offset": decision["new_offset"],
        "old_delay": old_delay, "new_delay": changes.get("gps_delay", old_delay),
        "bias_ms": decision.get("bias_ms"), "step_ms": decision.get("step_ms"),
        "reason": decision["reason"], "rolled_back": None,
    }
    state["changes"].append(entry)
    # Die Messung beginnt neu; als „aktiv“ gilt die Änderung erst, wenn _verify()
    # es belegt (pending) – bis dahin keine weitere Änderung.
    state["observed"] = {"offset": decision["new_offset"], "since": now}
    state["pending"] = {"change_id": entry["id"], "t": now}
    entry["reload_triggered"] = reloaded
    decision["reload_triggered"] = reloaded
    decision["change_id"] = entry["id"]
    _emit(deps, "calibration", "info",
          f"GPS-Offset automatisch angepasst: {old_offset} s → {decision['new_offset']} s",
          {"old_offset": old_offset, "new_offset": decision["new_offset"],
           "old_delay": old_delay, "new_delay": entry["new_delay"],
           "bias_ms": decision.get("bias_ms"), "step_ms": decision.get("step_ms"),
           "reason": decision["reason"]})
    return decision


def _next_id(state: dict) -> int:
    return 1 + max([int(c.get("id") or 0) for c in state.get("changes") or []] + [0])


_LAST_TICK = {"t": None}


def maybe_tick(cfg: dict | None = None, now: float | None = None) -> dict | None:
    """Für die Messschleife: führt tick() höchstens einmal pro TICK_INTERVAL aus.

    Der Zeitpunkt des letzten Durchgangs steht auch in autocal.json, damit ein
    Neustart des Dashboards nicht sofort eine weitere Prüfung auslöst.
    """
    now = time.time() if now is None else now
    last = _LAST_TICK["t"]
    if last is None:
        last = _num(load().get("last_tick"))
        # Systemuhr zurückgesprungen (Pi ohne RTC)? Dann nicht ewig warten.
        if last is not None and last > now:
            last = None
        _LAST_TICK["t"] = last if last is not None else now - TICK_INTERVAL
        last = _LAST_TICK["t"]
    if now - last < TICK_INTERVAL and now >= last:
        return None
    _LAST_TICK["t"] = now
    try:
        return tick(cfg if cfg is not None else settings.values(), now)
    except Exception as exc:  # die Messschleife darf nie stehen bleiben
        print(f"[web] Automatische Kalibrierung fehlgeschlagen: {exc}", flush=True)
        return None


def rollback(steps: int = 1, cfg: dict | None = None, now: float | None = None,
             deps: dict | None = None, file: str | None = None) -> dict:
    """Nimmt die letzten `steps` automatischen Änderungen zurück.

    Wirft AutocalError mit deutscher Meldung, wenn das nicht geht: keine
    Änderung vorhanden, zu viele Schritte, oder der Offset wurde seitdem von
    Hand geändert (dann würde die Rücknahme deine Änderung überschreiben).
    """
    now = time.time() if now is None else now
    deps = _deps(deps)
    cfg = cfg if cfg is not None else settings.values()
    try:
        steps = int(steps)
    except (TypeError, ValueError):
        raise AutocalError("Die Zahl der Schritte muss eine ganze Zahl sein.") from None
    with _LOCK:
        state = load(file)
        active = _active_auto(state)
        if not active:
            raise AutocalError("Es gibt keine automatische Änderung, die sich zurücknehmen lässt.")
        if steps < 1 or steps > len(active):
            raise AutocalError(f"Es lassen sich 1 bis {len(active)} Änderung(en) zurücknehmen.")
        undo = active[-steps:]
        current = _cfg_float(cfg, "gps_offset", 0.0)
        if abs(current - float(undo[-1]["new_offset"])) > OFFSET_EPS:
            raise AutocalError(f"Der Offset steht inzwischen auf {current} s statt auf "
                               f"{undo[-1]['new_offset']} s – er wurde seitdem von Hand geändert. "
                               "Eine Rücknahme würde deine Änderung überschreiben; stelle den Wert "
                               "bei Bedarf in den Einstellungen ein.")
        restore_offset = float(undo[0]["old_offset"])
        restore_delay = _num(undo[0].get("old_delay"))
        current_delay = _cfg_float(cfg, "gps_delay", 0.2)
        changes: dict[str, Any] = {"gps_offset": restore_offset}
        if restore_delay is not None and abs(restore_delay - current_delay) > 1e-9:
            changes["gps_delay"] = restore_delay
        result = deps["save_settings"](changes) or {}
        reloaded = False
        if result.get("restart"):
            try:
                reloaded = bool(deps["trigger_reload"]())
            except Exception:
                reloaded = False
        for change in undo:
            change["rolled_back"] = now
        entry = {
            "id": _next_id(state), "t": now, "kind": "rollback",
            "old_offset": current, "new_offset": restore_offset,
            "old_delay": current_delay, "new_delay": changes.get("gps_delay", current_delay),
            "reason": f"{steps} automatische Änderung(en) zurückgenommen.",
            "undoes": [c.get("id") for c in undo], "rolled_back": None,
        }
        state["changes"].append(entry)
        state["observed"] = {"offset": restore_offset, "since": now}
        state["pending"] = {"change_id": entry["id"], "t": now}
        state["last_suggestion"] = None
        save(state, file)
    _emit(deps, "calibration", "warn",
          f"GPS-Kalibrierung zurückgenommen: {current} s → {restore_offset} s",
          {"old_offset": current, "new_offset": restore_offset, "steps": steps})
    return {"ok": True, "restored_offset": restore_offset,
            "restored_delay": changes.get("gps_delay", current_delay),
            "reload_triggered": reloaded, "change": entry}


# ---------------------------------------------------------------------------
# Anzeige (GET /api/gps/autocal)
# ---------------------------------------------------------------------------

_CAL_CACHE: dict[str, Any] = {"key": None, "t": None, "window": None, "result": None}


def _cached_getter(getter: Callable, cfg: dict, now: float) -> Callable:
    """get_calibration mit kurzem Zwischenspeicher für die Anzeige.

    Eine Auswertung liest bis zu 14 Tage Verlauf (Sekunden auf einem Pi) und
    hält dabei die Sperre des Verlaufs; die Seite fragt jede Minute. tick()
    nutzt den Zwischenspeicher nie.
    """
    key = (id(getter), cfg.get("gps_refid"), cfg.get("gps_offset"), cfg.get("gps_delay"))

    def get(window: float) -> dict:
        c = _CAL_CACHE
        t = _num(c.get("t"))
        if c.get("key") == key and t is not None and 0 <= now - t < CAL_CACHE_SECONDS \
                and abs(float(c.get("window") or 0.0) - window) <= CAL_CACHE_SECONDS * 2:
            return dict(c["result"])
        result = dict(getter(window) or {})
        c.update(key=key, t=now, window=window, result=dict(result))
        return result
    return get


def api_status(cfg: dict | None = None, now: float | None = None, fresh: bool = False,
               deps: dict | None = None, file: str | None = None) -> dict:
    """Alles für die Kalibrierkarte.

    Standard: die von tick() (stündlich) gespeicherte Entscheidung – billig.
    fresh=True rechnet neu (ohne etwas zu ändern), nutzt aber eine höchstens
    CAL_CACHE_SECONDS alte Messung erneut. Ohne gespeicherte Entscheidung
    (noch kein tick) wird ebenfalls gerechnet.
    """
    now = time.time() if now is None else now
    cfg = cfg if cfg is not None else settings.values()
    with _LOCK:
        state = load(file)
    mode = _mode(cfg)
    decision = state.get("last_decision")
    if fresh or not isinstance(decision, dict):
        try:
            decision = dict(_evaluate(cfg, now, state, _deps(deps), cached=True), t=now)
        except Exception as exc:
            decision = {"action": "none", "reason": f"Prüfung fehlgeschlagen: {exc}", "t": now}
    last_auto = _last_auto_event(state)
    next_change_at = None
    if mode == "auto":
        next_change_at = now
        if last_auto and _num(last_auto.get("t")) is not None:
            next_change_at = max(now, float(last_auto["t"]) + AUTO_INTERVAL)
        observed = state.get("observed") or {}
        if _num(observed.get("since")) is not None:
            min_seconds = _cfg_float(cfg, "gps_autocal_min_hours", 6.0) * 3600
            next_change_at = max(next_change_at, float(observed["since"]) + SETTLE_SECONDS + min_seconds)
    active = _active_auto(state)
    current = _cfg_float(cfg, "gps_offset", 0.0)
    rollback_info = {"possible": False, "reason": "Es gibt keine automatische Änderung zum Zurücknehmen."}
    if active:
        newest = active[-1]
        if abs(current - float(newest["new_offset"])) > OFFSET_EPS:
            rollback_info = {"possible": False, "change_id": newest.get("id"),
                             "reason": "Der Offset wurde seit der letzten automatischen Änderung von "
                                       "Hand geändert – zurücknehmen würde das überschreiben."}
        else:
            rollback_info = {"possible": True, "change_id": newest.get("id"),
                             "restores_offset": newest.get("old_offset"),
                             "available_steps": len(active)}
    last_tick = _num(state.get("last_tick"))
    return {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "mode_text": MODE_TEXTS[mode],
        "gps_enabled": bool(cfg.get("gps_enable")),
        "max_step_ms": _cfg_float(cfg, "gps_autocal_max_step_ms", 5.0),
        "min_hours": _cfg_float(cfg, "gps_autocal_min_hours", 6.0),
        "current_offset": current,
        "current_delay": _cfg_float(cfg, "gps_delay", 0.2),
        "decision": decision,
        "next_change_at": next_change_at,
        "last_tick": last_tick,
        "next_tick_at": (last_tick + TICK_INTERVAL) if last_tick is not None else None,
        "changes": list(reversed(state.get("changes") or []))[:20],
        "rollback": rollback_info,
        "readonly": _readonly(),
    }
