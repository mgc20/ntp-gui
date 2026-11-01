"""PTP (IEEE 1588) status, read from ptp4l through its management socket."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any

PMC = shutil.which("pmc") or "/usr/sbin/pmc"
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
    "TIME_PROPERTIES_DATA_SET": ["currentUtcOffset", "timeTraceable", "frequencyTraceable", "ptpTimescale"],
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


def _query(dataset: str, timeout: float = 3.0) -> dict[str, str]:
    socket = os.environ.get("PTP_UDS_ADDRESS", "/var/run/ptp4l")
    # The domain must match ptp4l's, otherwise the daemon silently ignores the
    # management message and pmc returns nothing but its "sending:" line.
    domain = str(_cfg()["ptp_domain"])
    try:
        proc = subprocess.run(
            [PMC, "-u", "-b", "0", "-d", domain, "-s", socket, f"GET {dataset}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    return parse_pmc_output(proc.stdout)


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


def _collect() -> dict[str, Any]:
    cfg = _cfg()
    state: dict[str, Any] = {
        "enabled": True,
        "interface": cfg["ptp_interface"],
        "mode": cfg["ptp_mode"],
        "transport": cfg["ptp_transport"],
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
