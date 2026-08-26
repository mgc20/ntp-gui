"""GPS status, read from gpsd over its JSON protocol on localhost:2947.

Talking to gpsd directly keeps the image free of the gpsd-clients package and
avoids spawning a process per poll. Results are cached because every browser
refresh would otherwise open a socket and wait for the next TPV/SKY report.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any

FIX_MODES = {0: "unbekannt", 1: "kein Fix", 2: "2D-Fix", 3: "3D-Fix"}

_CACHE: dict[str, Any] = {}
_CACHE_TIME = 0.0
try:
    _CACHE_TTL = max(0.0, float(os.environ.get("GPS_CACHE_TTL", "5")))
except ValueError:
    _CACHE_TTL = 5.0
_LOCK = threading.Lock()


def enabled() -> bool:
    return os.environ.get("GPS_ENABLE", "false").strip().lower() in {"1", "true", "yes", "on"}


def show_position() -> bool:
    return os.environ.get("GPS_SHOW_POSITION", "false").strip().lower() in {"1", "true", "yes", "on"}


def _sky_is_detailed(report: dict[str, Any] | None) -> bool:
    return bool(report) and ("satellites" in report or report.get("nSat") is not None)


def poll_gpsd(timeout: float = 4.0) -> dict[str, Any]:
    """Collect one VERSION/TPV/SKY set from gpsd. Returns {} when unreachable."""
    host = os.environ.get("GPSD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("GPSD_PORT", "2947"))
    except ValueError:
        port = 2947
    reports: dict[str, Any] = {}
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            buffer = b""
            while time.monotonic() < deadline:
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    if not line.strip():
                        continue
                    try:
                        report = json.loads(line)
                    except ValueError:
                        continue
                    kind = report.get("class")
                    if kind not in {"VERSION", "TPV", "SKY", "DEVICES"}:
                        continue
                    # gpsd only carries the satellite list in some SKY cycles;
                    # never let a bare SKY overwrite one that has the details.
                    if kind == "SKY" and _sky_is_detailed(reports.get("SKY")) and not _sky_is_detailed(report):
                        continue
                    reports[kind] = report
                # A fix report plus a detailed satellite report is all we need.
                if "TPV" in reports and _sky_is_detailed(reports.get("SKY")):
                    return reports
    except OSError:
        return reports
    return reports


def parse_reports(reports: dict[str, Any]) -> dict[str, Any]:
    """Turn raw gpsd reports into the flat structure the dashboard renders."""
    state: dict[str, Any] = {"running": bool(reports)}
    version = reports.get("VERSION") or {}
    if version:
        state["gpsd_release"] = version.get("release")

    devices = (reports.get("DEVICES") or {}).get("devices") or []
    if devices:
        state["device"] = devices[0].get("path")
        state["driver"] = devices[0].get("driver")
        if devices[0].get("bps"):
            state["baud"] = devices[0]["bps"]

    tpv = reports.get("TPV") or {}
    mode = tpv.get("mode", 0)
    state["mode"] = mode
    state["mode_label"] = FIX_MODES.get(mode, str(mode))
    state["has_fix"] = mode >= 2
    state["time"] = tpv.get("time")
    if tpv.get("ept") is not None:
        state["time_error"] = tpv["ept"]
    if not state.get("device") and tpv.get("device"):
        state["device"] = tpv["device"]
    if show_position():
        for key in ("lat", "lon", "alt", "altHAE"):
            if tpv.get(key) is not None:
                state[key] = tpv[key]

    sky = reports.get("SKY") or {}
    satellites = sky.get("satellites") or []
    used = sky.get("uSat")
    if used is None:
        used = sum(1 for sat in satellites if sat.get("used"))
    seen = sky.get("nSat")
    if seen is None:
        seen = len(satellites)
    # A SKY report without the satellite list still tells us how many are used.
    state["satellites_used"] = used
    state["satellites_seen"] = max(seen, used or 0)
    for key in ("hdop", "pdop", "vdop"):
        if sky.get(key) is not None:
            state[key] = sky[key]
    # Signal strengths of the satellites actually used for the fix.
    snrs = [sat.get("ss") for sat in satellites if sat.get("used") and sat.get("ss") is not None]
    if snrs:
        state["snr_avg"] = round(sum(snrs) / len(snrs), 1)
        state["snr_max"] = max(snrs)
    return state


def status() -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    if not enabled():
        return {"enabled": False, "running": False}

    with _LOCK:
        if _CACHE and time.time() - _CACHE_TIME < _CACHE_TTL:
            return dict(_CACHE)
        state = parse_reports(poll_gpsd())
        state["enabled"] = True
        state.setdefault("device", os.environ.get("GPS_DEVICE", ""))
        # Only claim PPS when the device is actually there - the entrypoint skips
        # the refclock for a missing device, so reporting it would be a lie.
        pps_device = os.environ.get("GPS_PPS_DEVICE", "").strip()
        if pps_device and not os.path.exists(pps_device):
            state["pps"] = ""
            state["pps_missing"] = pps_device
        elif pps_device:
            state["pps"] = pps_device
        elif os.environ.get("GPS_PPS_SHM", "false").lower() in {"1", "true", "yes", "on"}:
            state["pps"] = "gpsd (SHM 1)"
        else:
            state["pps"] = ""
        _CACHE = state
        _CACHE_TIME = time.time()
        return dict(state)
