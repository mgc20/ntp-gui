"""PTP (IEEE 1588) status, read from ptp4l through its management socket."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

import providers

PMC = providers.binary("pmc")
PTP4L_LOG = os.environ.get("PTP_LOG_FILE", "/var/log/ptp4l.log")

# Datasets we query, and the fields we lift out of each of them.
_DATASETS = {
    "DEFAULT_DATA_SET": ["clockIdentity", "domainNumber", "numberPorts", "slaveOnly", "clockClass", "clockAccuracy"],
    "CURRENT_DATA_SET": ["stepsRemoved", "offsetFromMaster", "meanPathDelay"],
    "PARENT_DATA_SET": ["parentPortIdentity", "grandmasterIdentity", "gm.ClockClass", "gm.ClockAccuracy", "gm.OffsetScaledLogVariance", "grandmasterPriority1", "grandmasterPriority2"],
    "PORT_DATA_SET": ["portIdentity", "portState", "logSyncInterval", "logMinDelayReqInterval",
                      "peerMeanPathDelay", "logAnnounceInterval", "announceReceiptTimeout",
                      "delayMechanism", "versionNumber"],
    "TIME_STATUS_NP": ["master_offset", "gmPresent", "gmIdentity"],
    "TIME_PROPERTIES_DATA_SET": ["currentUtcOffset", "currentUtcOffsetValid", "timeTraceable",
                                 "frequencyTraceable", "ptpTimescale", "timeSource"],
}

_NUMERIC_FIELDS = {
    "domainNumber", "numberPorts", "clockClass", "stepsRemoved", "offsetFromMaster",
    "meanPathDelay", "master_offset", "gm.ClockClass", "grandmasterPriority1",
    "grandmasterPriority2", "currentUtcOffset", "logSyncInterval", "logMinDelayReqInterval",
}

PORT_STATES = {
    "MASTER": "Grandmaster / Master",
    "SLAVE": "Slave (synchronisiert)",
    "LISTENING": "Listening",
    "UNCALIBRATED": "Uncalibrated",
    "PASSIVE": "Passive",
    "FAULTY": "Faulty",
    "DISABLED": "Disabled",
    "PRE_MASTER": "Pre-Master",
    "INITIALIZING": "Initializing",
}


def _cfg() -> dict:
    import settings  # spät importieren: ptp.py bleibt ohne settings testbar
    return settings.values()


def enabled() -> bool:
    return bool(_cfg()["ptp_enable"])


# Zusammenfassungen von ptp4l -m, z. B.
#   "rms   12 max   30 freq  -1234 +/-   5 delay   456 +/-   3"   (Slave, summary_interval)
#   "master offset    -12 s2 freq   +100 path delay    456"       (Slave, jede Sync-Nachricht)
_SUMMARY_RE = re.compile(
    r"rms\s+(?P<rms>-?\d+)\s+max\s+(?P<max>-?\d+)\s+freq\s+(?P<freq>[-+]?\d+)"
    r"(?:\s+\+/-\s+(?P<freq_dev>\d+))?(?:\s+delay\s+(?P<delay>-?\d+)(?:\s+\+/-\s+(?P<delay_dev>\d+))?)?")
_OFFSET_RE = re.compile(
    r"master offset\s+(?P<offset>-?\d+)\s+s(?P<servo>\d)\s+freq\s+(?P<freq>[-+]?\d+)"
    r"(?:\s+path delay\s+(?P<delay>-?\d+))?")
_STATE_RE = re.compile(r"port \d+ \([^)]*\): (?P<old>[A-Z_]+) to (?P<new>[A-Z_]+) on (?P<event>[A-Z_]+)")


def parse_log_metrics(lines: list[str]) -> dict[str, Any]:
    """Letzte Kennzahlen und Zustandswechsel aus dem ptp4l-Log."""
    result: dict[str, Any] = {"transitions": []}
    for line in lines:
        match = _SUMMARY_RE.search(line)
        if match:
            result["rms_ns"] = int(match.group("rms"))
            result["max_ns"] = int(match.group("max"))
            result["freq_ppb"] = int(match.group("freq"))
            if match.group("delay"):
                result["path_delay_ns"] = int(match.group("delay"))
            continue
        match = _OFFSET_RE.search(line)
        if match:
            result["last_offset_ns"] = int(match.group("offset"))
            result["servo_state"] = "s" + match.group("servo")
            result["freq_ppb"] = int(match.group("freq"))
            if match.group("delay"):
                result["path_delay_ns"] = int(match.group("delay"))
            continue
        match = _STATE_RE.search(line)
        if match:
            result["transitions"].append({"from": match.group("old"), "to": match.group("new"),
                                          "event": match.group("event")})
    result["transitions"] = result["transitions"][-8:]
    return result


def parse_pmc_output(text: str) -> dict[str, str]:
    """Extract the ``key value`` pairs from a pmc management response."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("sending:") or "RESPONSE MANAGEMENT" in line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts[0], parts[1].strip()
        if key.endswith(":"):
            key = key[:-1]
        values.setdefault(key, value)
    return values


def _coerce(key: str, value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    if key in _NUMERIC_FIELDS:
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value
    return value


def _pmc_base(cfg: dict) -> list[str]:
    import settings
    socket = settings.ptp_uds_address()
    # The domain must match ptp4l's, otherwise the daemon silently ignores the
    # management message and pmc returns nothing but its "sending:" line. The
    # same holds for transportSpecific in the gPTP (802.1AS) profile.
    args = [PMC, "-u", "-b", "0", "-d", str(cfg["ptp_domain"]), "-s", socket]
    if cfg.get("ptp_profile") == "gptp":
        args += ["-t", "1"]
    return args


def _query(dataset: str, timeout: float = 3.0) -> dict[str, str]:
    base = _pmc_base(_cfg())
    try:
        result = providers.call("pmc", [*base[1:], f"GET {dataset}"], timeout, binary_path=base[0])
    except providers.ProviderError:
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    return parse_pmc_output(result.stdout)


def log_tail(lines: int = 40, max_bytes: int = 65536) -> list[str]:
    """Last lines of the ptp4l log, reading only the file's tail.

    The log grows for the container's whole lifetime (the supervisor caps it,
    but between rotations it can be large), so never read it in full.
    """
    try:
        with open(PTP4L_LOG, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    tail = chunk.splitlines()
    # Der erste Eintrag kann mitten in einer Zeile beginnen - weglassen.
    if size > max_bytes and tail:
        tail = tail[1:]
    return tail[-lines:]


_CACHE: dict[str, Any] = {}
_CACHE_TIME = 0.0
try:
    _CACHE_TTL = max(0.0, float(os.environ.get("PTP_CACHE_TTL", "4")))
except ValueError:
    _CACHE_TTL = 4.0
_LOCK = threading.Lock()


def status() -> dict[str, Any]:
    """Aggregated PTP state; ``running`` is False when ptp4l is not answering."""
    if not enabled():
        return {"enabled": False, "running": False}

    with _LOCK:
        if _CACHE and time.time() - _CACHE_TIME < _CACHE_TTL:
            return dict(_CACHE)
        state = _collect()
        _CACHE.clear()
        _CACHE.update(state)
        globals()["_CACHE_TIME"] = time.time()
        return dict(state)


def _effective_transport(cfg: dict) -> str:
    """Transport, mit dem ptp4l wirklich läuft (Profil gptp setzt L2)."""
    import settings
    return settings.ptp_profile_values(cfg)[0]["ptp_transport"]


def _collect() -> dict[str, Any]:
    cfg = _cfg()
    state: dict[str, Any] = {
        "enabled": True,
        "interface": cfg["ptp_interface"],
        "mode": cfg["ptp_mode"],
        "transport": _effective_transport(cfg),
        "time_stamping": cfg["ptp_time_stamping"],
        "domain": str(cfg["ptp_domain"]),
        "phc2sys": bool(cfg["phc2sys_enable"]),
    }

    # Probe one dataset first: if ptp4l is gone, five more timeouts would only
    # stall the dashboard.
    answered = False
    for index, (dataset, fields) in enumerate(_DATASETS.items()):
        values = _query(dataset)
        if values:
            answered = True
        elif index == 0 and not answered:
            break
        for field in fields:
            if field in values:
                state[field] = _coerce(field, values[field])

    state["running"] = answered
    port_state = state.get("portState")
    state["port_state_label"] = PORT_STATES.get(port_state, port_state)
    state["synchronised"] = port_state in {"SLAVE", "MASTER", "GRAND_MASTER"}
    state["is_grandmaster"] = port_state in {"MASTER", "GRAND_MASTER"} and not state.get("gmPresent")
    # offsetFromMaster / master_offset are reported in nanoseconds. As the
    # grandmaster we are the reference, so there is no offset to report.
    offset = state.get("master_offset")
    if offset is None:
        offset = state.get("offsetFromMaster")
    state["offset_ns"] = None if state["is_grandmaster"] else offset
    state["log"] = log_tail()
    state["log_metrics"] = parse_log_metrics(log_tail(lines=400))
    return state


# ---------------------------------------------------------------------------
# Grandmaster: angekündigte Uhrqualität nach dem Zustand von chrony
# ---------------------------------------------------------------------------
#
# IEEE 1588-2008/2019, Tabellen 5–7 (clockClass, clockAccuracy, timeSource):
#   clockClass 6   = an eine primäre Referenz (z. B. GNSS) gekoppelt
#   clockClass 7   = war an primärer Referenz, jetzt Holdover innerhalb der Spezifikation
#   clockClass 248 = Standard (keine Aussage über Rückführbarkeit)
#   timeSource 0x20 GNSS, 0x40 PTP, 0x50 NTP, 0x90 OTHER, 0xA0 INTERNAL_OSCILLATOR
#   clockAccuracy 0x20 = 25 ns … 0x31 = > 10 s, 0xFE = unbekannt
# Gesetzt wird per "pmc SET GRANDMASTER_SETTINGS_NP" (linuxptp pmc_common.c:
# 11 Werte in fester Reihenfolge). Die clockClass aus ptp4l.conf bleibt der
# Startwert, bis die erste Auswertung hier greift.

TIME_SOURCE = {"gnss": 0x20, "ptp": 0x40, "ntp": 0x50, "other": 0x90, "internal": 0xA0}

# (Obergrenze in Sekunden, clockAccuracy-Code)
_ACCURACY_STEPS = [
    (25e-9, 0x20), (100e-9, 0x21), (250e-9, 0x22), (1e-6, 0x23), (2.5e-6, 0x24),
    (10e-6, 0x25), (25e-6, 0x26), (100e-6, 0x27), (250e-6, 0x28), (1e-3, 0x29),
    (2.5e-3, 0x2A), (10e-3, 0x2B), (25e-3, 0x2C), (100e-3, 0x2D), (250e-3, 0x2E),
    (1.0, 0x2F), (10.0, 0x30),
]
ACCURACY_UNKNOWN = 0xFE


def accuracy_code(error_seconds: float | None) -> int:
    """Kleinster clockAccuracy-Code, dessen Schranke den Fehler abdeckt."""
    if error_seconds is None or error_seconds != error_seconds or error_seconds < 0:
        return ACCURACY_UNKNOWN
    for limit, code in _ACCURACY_STEPS:
        if error_seconds <= limit:
            return code
    return 0x31


def _estimated_error(tracking: dict) -> float | None:
    """Fehlerschranke der Systemuhr wie bei chrony: |Offset| + Dispersion + Delay/2."""
    try:
        return (abs(float(tracking.get("system_time_offset") or 0.0))
                + float(tracking["root_dispersion"]) + float(tracking["root_delay"]) / 2)
    except (KeyError, TypeError, ValueError):
        return None


def grandmaster_properties(tracking: dict, sources: list, *, gps_refid: str = "GPS",
                           utc_offset: int = 37, holdover_age: float | None = None,
                           holdover_limit: float = 900.0) -> dict | None:
    """Reine Entscheidung: welche Zeiteigenschaften ein Grandmaster ankündigt.

    tracking/sources wie chrony.tracking()/chrony.detailed_sources(). holdover_age
    = Sekunden seit dem letzten stabilen GPS+PPS-Lock (None = nie). Gibt None
    zurück, wenn chrony nicht antwortet – dann bleibt alles, wie es ist.
    """
    if not tracking:
        return None
    leap = str(tracking.get("leap_status") or "")
    synced = leap and leap != "Not synchronised" and (tracking.get("stratum") or 16) < 16
    selected = next((s for s in sources or [] if s.get("state") == "*"), None)
    props = {
        "clockClass": 248, "clockAccuracy": ACCURACY_UNKNOWN, "offsetScaledLogVariance": 0xFFFF,
        "currentUtcOffset": int(utc_offset), "leap61": 1 if leap == "Insert second" else 0,
        "leap59": 1 if leap == "Delete second" else 0, "currentUtcOffsetValid": 0,
        "ptpTimescale": 1, "timeTraceable": 0, "frequencyTraceable": 0,
        "timeSource": TIME_SOURCE["internal"], "reason": "unsynced",
    }
    if not synced or selected is None:
        # Frei laufend oder nur "local stratum": Zeit ist nicht rückführbar.
        props["leap61"] = props["leap59"] = 0
        return props

    props.update(clockAccuracy=accuracy_code(_estimated_error(tracking)),
                 currentUtcOffsetValid=1, timeTraceable=1, frequencyTraceable=1)
    name = str(selected.get("name") or "")
    if selected.get("mode") == "#":
        if name == "PPS":
            stable = selected.get("reach") == 0o377  # die letzten 8 Abfragen alle erfolgreich
            props.update(timeSource=TIME_SOURCE["gnss"],
                         clockClass=6 if stable else 248,
                         reason="gps_pps" if stable else "gps_pps_settling")
            if stable:
                return props
        elif name == gps_refid:
            # Nur NMEA (z. B. USB-GPS ohne PPS): rückführbar, aber auf ms genau –
            # die schlechtere Genauigkeit steckt in clockAccuracy, Klasse bleibt 248.
            props.update(timeSource=TIME_SOURCE["gnss"], reason="gps_nmea")
        elif name.startswith("PHC"):
            props.update(timeSource=TIME_SOURCE["ptp"], reason="ptp")
        else:
            props.update(timeSource=TIME_SOURCE["other"], reason="refclock")
    else:
        props.update(timeSource=TIME_SOURCE["ntp"], reason="ntp")

    if holdover_age is not None and holdover_age < holdover_limit:
        # Gerade noch GPS+PPS gehabt: Holdover. Die Uhr läuft mit der eben
        # gelernten Frequenz weiter und ist noch eine Weile so gut wie vorher.
        props.update(clockClass=7, timeSource=TIME_SOURCE["gnss"], reason="holdover")
    return props


_GM_FIELDS = ("clockClass", "clockAccuracy", "offsetScaledLogVariance", "currentUtcOffset",
              "leap61", "leap59", "currentUtcOffsetValid", "ptpTimescale", "timeTraceable",
              "frequencyTraceable", "timeSource")
_HEX_FIELDS = {"clockAccuracy", "offsetScaledLogVariance", "timeSource"}


def grandmaster_command(props: dict) -> str:
    parts = ["SET GRANDMASTER_SETTINGS_NP"]
    for key in _GM_FIELDS:
        value = int(props[key])
        parts.append(f"{key} {value:#x}" if key in _HEX_FIELDS else f"{key} {value}")
    return " ".join(parts)


# sent=-inf: noch nie gesendet (monotonic() zählt ab Systemstart, 0.0 sperrte die ersten 5 s).
_GM_STATE: dict[str, Any] = {"key": None, "accuracy": None, "sent": float("-inf"), "failed": 0.0,
                             "last_locked": None, "logged_error": False}
_GM_MIN_GAP = 5.0          # nie öfter als alle 5 s senden
_GM_ACCURACY_GAP = 60.0    # reine Genauigkeitsänderungen höchstens minütlich
_GM_REFRESH = 300.0        # sonst alle 5 min auffrischen (ptp4l kann neu gestartet sein)
_GM_RETRY = 30.0           # nach einem Fehler

_REASON_TEXT = {
    "gps_pps": "an GPS+PPS gekoppelt", "gps_pps_settling": "PPS noch nicht stabil",
    "gps_nmea": "GPS ohne PPS", "ntp": "über NTP synchronisiert", "ptp": "über PTP-Uhr",
    "refclock": "Referenzuhr", "holdover": "Holdover nach GPS-Verlust",
    "unsynced": "nicht synchronisiert",
}


def utc_offset() -> int:
    """PTP_UTC_OFFSET: angekündigter currentUtcOffset (TAI−UTC) in s, 0–100, Standard 37."""
    import settings
    return int(settings.env_number("PTP_UTC_OFFSET", 37, 0, 100, integer=True))


def holdover_seconds() -> float:
    """PTP_HOLDOVER_SECONDS: so lange nach dem letzten GPS+PPS-Lock gilt clockClass 7,
    0–86400 s (0 = kein Holdover), Standard 900."""
    import settings
    return float(settings.env_number("PTP_HOLDOVER_SECONDS", 900, 0, 86400))


def update_grandmaster(cfg: dict, tracking: dict, sources: list) -> None:
    """Als Grandmaster clockClass, timeSource usw. an den Zustand von chrony anpassen.

    Wird vom Messthread des Dashboards bei jeder Messung aufgerufen. Sendet nur,
    wenn sich etwas geändert hat (oder zur Auffrischung), und wirft nie.
    """
    try:
        _update_grandmaster(cfg, tracking, sources, time.monotonic())
    except Exception as exc:  # darf den Messthread nie stören
        if not _GM_STATE["logged_error"]:
            print(f"[ptp] Grandmaster-Daten nicht gesetzt: {exc}", flush=True)
            _GM_STATE["logged_error"] = True


def _update_grandmaster(cfg: dict, tracking: dict, sources: list, now: float) -> None:
    if not (cfg.get("ptp_enable") and cfg.get("ptp_interface") and cfg.get("ptp_mode") == "master"):
        _GM_STATE.update(key=None, accuracy=None, sent=float("-inf"))
        return
    last_locked = _GM_STATE["last_locked"]
    props = grandmaster_properties(
        tracking, sources, gps_refid=str(cfg.get("gps_refid") or "GPS"),
        utc_offset=utc_offset(),
        holdover_age=None if last_locked is None else now - last_locked,
        holdover_limit=holdover_seconds())
    if props is None:
        return
    if props["reason"] == "gps_pps":
        _GM_STATE["last_locked"] = now
    # Die Identität des ptp4l-Prozesses gehört zum Schlüssel: Ein neu gestarteter
    # ptp4l (Speichern, Hotplug, Absturz) beginnt wieder mit den Werten aus
    # ptp4l.conf (clockClass 248) und muss die Daten sofort neu bekommen.
    key = (*(props[k] for k in _GM_FIELDS if k != "clockAccuracy"), _ptp4l_identity())
    since = now - _GM_STATE["sent"]
    if _GM_STATE["failed"] and now - _GM_STATE["failed"] < _GM_RETRY:
        return
    if since < _GM_MIN_GAP:
        return
    if key == _GM_STATE["key"]:
        accuracy_due = props["clockAccuracy"] != _GM_STATE["accuracy"] and since >= _GM_ACCURACY_GAP
        if not accuracy_due and since < _GM_REFRESH:
            return
    if not _send_grandmaster(cfg, props):
        _GM_STATE["failed"] = now
        return
    if key != _GM_STATE["key"]:
        print(f"[ptp] Grandmaster kündigt an: clockClass {props['clockClass']}, "
              f"timeSource {props['timeSource']:#04x}, clockAccuracy {props['clockAccuracy']:#04x} "
              f"({_REASON_TEXT.get(props['reason'], props['reason'])})", flush=True)
    _GM_STATE.update(key=key, accuracy=props["clockAccuracy"], sent=now, failed=0.0,
                     logged_error=False)
    with _LOCK:  # Statusanzeige sofort neu lesen lassen
        _CACHE.clear()


def _ptp4l_identity() -> str | None:
    """Kennung des laufenden ptp4l: PID + Startzeit aus services.json des Supervisors,
    sonst PID + Startzeit (Jiffies) aus /proc. None, wenn keiner gefunden wird."""
    run_dir = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
    try:
        with open(os.path.join(run_dir, "services.json"), encoding="utf-8") as handle:
            entry = (json.load(handle).get("services") or {}).get("ptp4l") or {}
        if entry.get("state") == "running" and entry.get("pid"):
            return f"svc:{entry['pid']}:{entry.get('since')}"
    except (OSError, ValueError, AttributeError):
        pass
    return _proc_identity("ptp4l")


def _proc_identity(comm: str) -> str | None:
    found = []
    try:
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return None
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
                stat = handle.read()
        except OSError:
            continue
        name = stat[stat.find("(") + 1:stat.rfind(")")]
        if name != comm:
            continue
        fields = stat[stat.rfind(")") + 2:].split()
        # fields[0] = Zustand (Feld 3), fields[19] = starttime (Feld 22)
        if len(fields) > 19 and fields[0] != "Z":
            found.append(f"proc:{pid}:{fields[19]}")
    return ",".join(sorted(found)) or None


def _send_grandmaster(cfg: dict, props: dict) -> bool:
    base = _pmc_base(cfg)
    try:
        proc = providers.call("pmc", [*base[1:], grandmaster_command(props)], 3.0,
                              binary_path=base[0])
    except (providers.ProviderError, OSError) as exc:
        reason = str(exc)
    else:
        if proc.returncode == 0 and "RESPONSE MANAGEMENT GRANDMASTER_SETTINGS_NP" in proc.stdout:
            return True
        lines = [line.strip() for line in (proc.stderr + "\n" + proc.stdout).splitlines()
                 if line.strip() and not line.startswith("sending:")]
        reason = lines[-1] if lines else "ptp4l antwortet nicht"
    if not _GM_STATE["logged_error"]:
        print(f"[ptp] Grandmaster-Daten nicht gesetzt ({reason}) – neuer Versuch alle "
              f"{int(_GM_RETRY)} s.", flush=True)
        _GM_STATE["logged_error"] = True
    return False
