"""PTP (IEEE 1588) status, read from ptp4l through its management socket."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

PMC = shutil.which("pmc") or "/usr/sbin/pmc"
PTP4L_LOG = os.environ.get("PTP_LOG_FILE", "/var/log/ptp4l.log")

# Datasets we query, and the fields we lift out of each of them.
_DATASETS = {
    "DEFAULT_DATA_SET": ["clockIdentity", "domainNumber", "numberPorts", "slaveOnly", "clockClass", "clockAccuracy"],
    "CURRENT_DATA_SET": ["stepsRemoved", "offsetFromMaster", "meanPathDelay"],
    "PARENT_DATA_SET": ["parentPortIdentity", "grandmasterIdentity", "gm.ClockClass", "gm.ClockAccuracy", "gm.OffsetScaledLogVariance", "grandmasterPriority1", "grandmasterPriority2"],
    "PORT_DATA_SET": ["portIdentity", "portState", "logSyncInterval", "logMinDelayReqInterval"],
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


def enabled() -> bool:
    return os.environ.get("PTP_ENABLE", "false").strip().lower() in {"1", "true", "yes", "on"}


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
    domain = os.environ.get("PTP_DOMAIN", "0").strip() or "0"
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


def log_tail(lines: int = 40) -> list[str]:
    try:
        with open(PTP4L_LOG, "r", errors="replace") as handle:
            return handle.read().splitlines()[-lines:]
    except OSError:
        return []


def status() -> dict[str, Any]:
    """Aggregated PTP state; ``running`` is False when ptp4l is not answering."""
    if not enabled():
        return {"enabled": False, "running": False}

    state: dict[str, Any] = {
        "enabled": True,
        "interface": os.environ.get("PTP_INTERFACE", ""),
        "mode": os.environ.get("PTP_MODE", "auto"),
        "transport": os.environ.get("PTP_TRANSPORT", "UDPv4"),
        "domain": os.environ.get("PTP_DOMAIN", "0"),
    }

    answered = False
    for dataset, fields in _DATASETS.items():
        values = _query(dataset)
        if values:
            answered = True
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
    return state
