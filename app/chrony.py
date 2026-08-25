"""Thin wrapper around chronyc that turns its output into JSON-friendly dicts.

We use chronyc's CSV mode (-c) wherever it is available because the field order
is stable across chrony releases, and fall back to parsing the human readable
"Name : value" output for reports whose column set changes between versions
(serverstats being the prominent example).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

CHRONYC = shutil.which("chronyc") or "/usr/bin/chronyc"

# chronyc -c tracking, in field order.
_TRACKING_FIELDS = [
    ("ref_id", str),
    ("ref_name", str),
    ("stratum", int),
    ("ref_time", float),
    ("system_time_offset", float),
    ("last_offset", float),
    ("rms_offset", float),
    ("frequency_ppm", float),
    ("residual_frequency_ppm", float),
    ("skew_ppm", float),
    ("root_delay", float),
    ("root_dispersion", float),
    ("update_interval", float),
    ("leap_status", str),
]

# chronyc -c sources, in field order.
_SOURCE_FIELDS = [
    ("mode", str),
    ("state", str),
    ("name", str),
    ("stratum", int),
    ("poll", int),
    ("reach", "octal"),
    ("last_rx", int),
    ("offset", float),
    ("original_offset", float),
    ("error", float),
]

# chronyc -c sourcestats, in field order.
_SOURCESTAT_FIELDS = [
    ("name", str),
    ("samples", int),
    ("runs", int),
    ("span", int),
    ("frequency_ppm", float),
    ("frequency_skew_ppm", float),
    ("offset", float),
    ("std_dev", float),
]

# chronyc -c clients, in field order.
_CLIENT_FIELDS = [
    ("address", str),
    ("ntp_packets", int),
    ("ntp_dropped", int),
    ("ntp_interval", float),
    ("ntp_interval_limit", float),
    ("ntp_last_rx", int),
    ("cmd_packets", int),
    ("cmd_dropped", int),
    ("cmd_interval", float),
    ("cmd_last_rx", int),
]

MODE_LABELS = {"^": "server", "=": "peer", "#": "local"}
STATE_LABELS = {
    "*": "synced",
    "+": "combined",
    "-": "excluded",
    "?": "unreachable",
    "x": "falseticker",
    "~": "variable",
}


class ChronyError(RuntimeError):
    """chronyd could not be queried."""


def run(*args: str, timeout: float = 5.0) -> str:
    """Run chronyc with the given arguments and return stdout."""
    try:
        proc = subprocess.run(
            [CHRONYC, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # chronyc missing entirely
        raise ChronyError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ChronyError(f"chronyc {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise ChronyError(message or f"chronyc {' '.join(args)} failed")
    return proc.stdout


def _coerce(value: str, kind) -> Any:
    value = value.strip()
    if kind is str:
        return value
    if kind == "octal":
        # chronyc prints the reachability register in octal (e.g. 377 = 8/8).
        try:
            return int(value, 8)
        except ValueError:
            return None
    try:
        return kind(value)
    except ValueError:
        return None


def _parse_csv_row(row: str, fields: list[tuple[str, Any]]) -> dict[str, Any]:
    parts = row.split(",")
    record: dict[str, Any] = {}
    for index, (name, kind) in enumerate(fields):
        record[name] = _coerce(parts[index], kind) if index < len(parts) else None
    return record


def _csv_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def parse_tracking(text: str) -> dict[str, Any]:
    rows = _csv_rows(text)
    if not rows:
        return {}
    record = _parse_csv_row(rows[0], _TRACKING_FIELDS)
    leap = (record.get("leap_status") or "").lower()
    # 7F7F0101 (127.127.1.1) is chrony's reference id for "local" mode, i.e. the
    # server hands out its own unsynchronised clock. That is a valid island-mode
    # state, but it must not be reported as synchronised to an upstream source.
    record["local_reference"] = record.get("ref_id") == "7F7F0101" or not record.get("ref_name")
    record["synchronised"] = bool(
        record.get("stratum")
        and record["stratum"] < 16
        and leap in {"normal", "insert second", "delete second"}
        and not record["local_reference"]
    )
    return record


def parse_sources(text: str) -> list[dict[str, Any]]:
    sources = []
    for row in _csv_rows(text):
        record = _parse_csv_row(row, _SOURCE_FIELDS)
        record["mode_label"] = MODE_LABELS.get(record.get("mode"), record.get("mode"))
        record["state_label"] = STATE_LABELS.get(record.get("state"), record.get("state"))
        reach = record.get("reach")
        # reach is an octal register of the last 8 polls; show it as a percentage.
        record["reach_percent"] = round(bin(reach).count("1") / 8 * 100) if isinstance(reach, int) else None
        # chrony reports "never heard from" as an unsigned -1.
        if record.get("last_rx") == 0xFFFFFFFF:
            record["last_rx"] = None
        sources.append(record)
    return sources


def parse_sourcestats(text: str) -> list[dict[str, Any]]:
    return [_parse_csv_row(row, _SOURCESTAT_FIELDS) for row in _csv_rows(text)]


def parse_clients(text: str) -> list[dict[str, Any]]:
    clients = []
    for row in _csv_rows(text):
        record = _parse_csv_row(row, _CLIENT_FIELDS)
        if not record.get("address"):
            continue
        for field in ("ntp_last_rx", "cmd_last_rx"):
            if record.get(field) == 0xFFFFFFFF:
                record[field] = None
        # An interval of 127 is chrony's "-" placeholder in the client report.
        for field in ("ntp_interval", "ntp_interval_limit", "cmd_interval"):
            if record.get(field) == 127:
                record[field] = None
        clients.append(record)
    return clients


def parse_activity(text: str) -> dict[str, Any]:
    """chronyc -c activity returns five counters on a single comma separated line."""
    fields = [field for row in _csv_rows(text) for field in row.split(",")]
    values = [int(v) for v in fields if v.strip().lstrip("-").isdigit()]
    keys = ["online", "offline", "burst_online", "burst_offline", "unresolved"]
    activity = dict(zip(keys, values))
    activity["total"] = sum(activity.get(k, 0) for k in ("online", "offline", "burst_online", "burst_offline"))
    return activity


def parse_serverstats(text: str) -> dict[str, Any]:
    """serverstats gains fields with every chrony release, so parse it by label."""
    stats: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        key = label.strip().lower()
        for char in " -/":
            key = key.replace(char, "_")
        value = value.strip()
        try:
            stats[key] = int(value)
        except ValueError:
            try:
                stats[key] = float(value)
            except ValueError:
                stats[key] = value
    return stats


def _safe(func, *args, default):
    try:
        return func(*args)
    except ChronyError:
        return default


def tracking() -> dict[str, Any]:
    return _safe(lambda: parse_tracking(run("-c", "tracking")), default={})


def sources() -> list[dict[str, Any]]:
    return _safe(lambda: parse_sources(run("-c", "sources")), default=[])


def sourcestats() -> list[dict[str, Any]]:
    return _safe(lambda: parse_sourcestats(run("-c", "sourcestats")), default=[])


def clients() -> list[dict[str, Any]]:
    return _safe(lambda: parse_clients(run("-c", "clients")), default=[])


def activity() -> dict[str, Any]:
    return _safe(lambda: parse_activity(run("-c", "activity")), default={})


def serverstats() -> dict[str, Any]:
    return _safe(lambda: parse_serverstats(run("serverstats")), default={})


def merged_sources() -> list[dict[str, Any]]:
    """sources + sourcestats joined on the source name."""
    stats = {row["name"]: row for row in sourcestats() if row.get("name")}
    merged = []
    for source in sources():
        extra = stats.get(source.get("name"), {})
        merged.append(
            {
                **source,
                "samples": extra.get("samples"),
                "span": extra.get("span"),
                "std_dev": extra.get("std_dev"),
                "frequency_skew_ppm": extra.get("frequency_skew_ppm"),
            }
        )
    return merged
