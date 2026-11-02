"""GPS status, read from gpsd over its JSON protocol on localhost:2947.

Talking to gpsd directly keeps the image free of the gpsd-clients package and
avoids spawning a process per poll. Results are cached because every browser
refresh would otherwise open a socket and wait for the next TPV/SKY report.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import providers

FIX_MODES = {0: "unbekannt", 1: "kein Fix", 2: "2D-Fix", 3: "3D-Fix"}

_CACHE: dict[str, Any] = {}
_CACHE_TIME = 0.0
try:
    _CACHE_TTL = max(0.0, float(os.environ.get("GPS_CACHE_TTL", "5")))
except ValueError:
    _CACHE_TTL = 5.0
_LOCK = threading.Lock()
# 1.5: letzte 3D-Position nur für die Störungserkennung (gnssguard: Positionssprung). Liegt nur
# im Speicher, steht nie in status()/API/Diagnosepaket – dort gilt weiter gps_show_position.
_POSITION: dict[str, Any] = {}


GNSS_SYSTEMS = {0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou", 4: "IMES", 5: "QZSS",
                6: "GLONASS", 7: "NavIC"}


def _setting(key: str):
    import settings  # spät importieren: gps.py bleibt ohne settings testbar
    return settings.values()[key]


def enabled() -> bool:
    return bool(_setting("gps_enable"))


def show_position() -> bool:
    return bool(_setting("gps_show_position"))


def _system_for(sat: dict) -> str:
    """Satellitensystem aus gnssid, sonst aus der klassischen NMEA-PRN-Nummerierung."""
    if isinstance(sat.get("gnssid"), int):
        return GNSS_SYSTEMS.get(sat["gnssid"], "?")
    prn = sat.get("PRN")
    if not isinstance(prn, int):
        return "?"
    if 1 <= prn <= 32:
        return "GPS"
    if 33 <= prn <= 64 or 120 <= prn <= 158:
        return "SBAS"
    if 65 <= prn <= 96:
        return "GLONASS"
    if 201 <= prn <= 237 or 401 <= prn <= 437:
        return "BeiDou"
    if 301 <= prn <= 336:
        return "Galileo"
    return "?"


def _sky_is_detailed(report: dict[str, Any] | None) -> bool:
    return bool(report) and ("satellites" in report or report.get("nSat") is not None)


def _gpsd_address() -> tuple[str, int]:
    host = os.environ.get("GPSD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("GPSD_PORT", "2947"))
    except ValueError:
        port = 2947
    return host, port


def poll_gpsd(timeout: float = 4.0) -> dict[str, Any]:
    """Collect one VERSION/TPV/SKY set from gpsd. Returns {} when unreachable."""
    host, port = _gpsd_address()
    reports: dict[str, Any] = {}
    try:
        with providers.gpsd_lines(host, port, '?WATCH={"enable":true,"json":true}', timeout) as lines:
            for line in lines:
                try:
                    report = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(report, dict):
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


def parse_devices(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Die DEVICES-Meldung von gpsd: welche Geräte gpsd kennt und was es darüber weiß.

    subtype/subtype1 enthalten bei u-blox den Inhalt von MON-VER (Firmware,
    Hardware-Generation, Modulname), activated ist gesetzt, sobald gpsd den Port
    öffnen konnte.
    """
    result = []
    for dev in (report or {}).get("devices") or []:
        if not isinstance(dev, dict):
            continue
        flags = dev.get("flags")
        result.append({
            "path": dev.get("path") or "",
            "driver": dev.get("driver") or "",
            "subtype": dev.get("subtype") or "",
            "subtype1": dev.get("subtype1") or "",
            "activated": dev.get("activated"),
            "bps": dev.get("bps") if isinstance(dev.get("bps"), int) else None,
            "flags": flags if isinstance(flags, int) else None,
            "native": dev.get("native") if isinstance(dev.get("native"), int) else None,
        })
    return result


def parse_reports(reports: dict[str, Any]) -> dict[str, Any]:
    """Turn raw gpsd reports into the flat structure the dashboard renders."""
    state: dict[str, Any] = {"running": bool(reports)}
    version = reports.get("VERSION") or {}
    if version:
        state["gpsd_release"] = version.get("release")

    state["devices"] = parse_devices(reports.get("DEVICES"))
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
    sky_list = []
    for sat in satellites:
        sky_list.append({
            "prn": sat.get("PRN"), "system": _system_for(sat), "svid": sat.get("svid"),
            "elevation": sat.get("el"), "azimuth": sat.get("az"), "snr": sat.get("ss"),
            "used": bool(sat.get("used")), "health": sat.get("health"),
        })
    sky_list.sort(key=lambda s: (not s["used"], -(s["snr"] or 0)))
    state["satellites"] = sky_list
    systems: dict[str, dict] = {}
    for sat in sky_list:
        entry = systems.setdefault(sat["system"], {"seen": 0, "used": 0})
        entry["seen"] += 1
        entry["used"] += 1 if sat["used"] else 0
    state["systems"] = systems
    for key in ("gdop", "tdop", "xdop", "ydop"):
        if sky.get(key) is not None:
            state[key] = sky[key]
    for key in ("eph", "epv", "speed"):
        if tpv.get(key) is not None:
            state[key] = tpv[key]
    if tpv.get("leapseconds") is not None:
        state["leapseconds"] = tpv["leapseconds"]
    # Signal strengths of the satellites actually used for the fix.
    snrs = [sat.get("ss") for sat in satellites if sat.get("used") and sat.get("ss") is not None]
    if snrs:
        state["snr_avg"] = round(sum(snrs) / len(snrs), 1)
        state["snr_max"] = max(snrs)
    # 1.5: Median der vier stärksten empfangenen Satelliten – Grundlage der Empfangsbewertung.
    import gpsquality  # spät: gps.py bleibt ohne Datenbank testbar
    top4 = gpsquality.cn0_top4(satellites)
    if top4 is not None:
        state["cn0_top4"] = top4
    return state


def status() -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    if not enabled():
        return {"enabled": False, "running": False}

    with _LOCK:
        if _CACHE and time.time() - _CACHE_TIME < _CACHE_TTL:
            return dict(_CACHE)
        reports = poll_gpsd()
        _remember_position(reports.get("TPV"))
        state = parse_reports(reports)
        state["enabled"] = True
        state.setdefault("device", _setting("gps_device"))
        # Only claim PPS when the device is actually there - the entrypoint skips
        # the refclock for a missing device, so reporting it would be a lie.
        pps_device = (_setting("gps_pps_device") or "").strip()
        if pps_device and not os.path.exists(pps_device):
            state["pps"] = ""
            state["pps_missing"] = pps_device
        elif pps_device:
            state["pps"] = pps_device
        elif _setting("gps_pps_shm"):
            state["pps"] = "gpsd (SHM 1)"
        else:
            state["pps"] = ""
        _CACHE = state
        _CACHE_TIME = time.time()
        return dict(state)


def _remember_position(tpv: Any) -> None:
    """Merkt sich lat/lon/eph eines 3D-Fix (monotone Zeit) – nur für private_position()."""
    if not isinstance(tpv, dict) or tpv.get("mode") != 3:
        return
    lat, lon, eph = tpv.get("lat"), tpv.get("lon"), tpv.get("eph")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
        return
    _POSITION.clear()
    _POSITION.update(lat=float(lat), lon=float(lon), mono=time.monotonic(),
                     eph=float(eph) if isinstance(eph, (int, float)) and not isinstance(eph, bool) else None)


def private_position(max_age: float = 30.0) -> tuple[float, float, float | None] | None:
    """(lat, lon, eph) des letzten 3D-Fix, höchstens max_age s alt – oder None.

    Nur für gnssguard (Positionssprung). Der Wert verlässt diesen Prozess nie: kein Ereignis,
    keine API, kein Diagnosepaket – gespeichert wird höchstens die Abweichung in Metern."""
    pos = dict(_POSITION)
    if not pos or time.monotonic() - pos["mono"] > max_age:
        return None
    return pos["lat"], pos["lon"], pos["eph"]


def summarize_pps(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Wertet gesammelte PPS-/TOFF-Meldungen aus.

    TOFF enthält für jede NMEA-Zeitmeldung die Systemzeit beim Empfang (clock)
    und die gemeldete GPS-Zeit (real). clock - real ist die Verspätung der
    NMEA-Zeit – ein zweiter Messweg neben dem Kalibrier-Assistenten.
    """
    pps = [m for m in messages if m.get("class") == "PPS"]
    toff = [m for m in messages if m.get("class") == "TOFF"]
    latencies = []
    for msg in toff:
        try:
            clock = float(msg["clock_sec"]) + float(msg.get("clock_nsec", 0)) / 1e9
            real = float(msg["real_sec"]) + float(msg.get("real_nsec", 0)) / 1e9
        except (KeyError, TypeError, ValueError):
            continue
        latencies.append((clock - real) * 1000.0)
    return {
        "seen": bool(pps),
        "pps_count": len(pps),
        "pps_devices": sorted({str(m.get("device") or "") for m in pps} - {""}),
        "toff_count": len(toff),
        "toff_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
    }


def probe_pps(timeout: float = 2.5) -> dict[str, Any]:
    """Lauscht kurz mit „pps“:true an gpsd und sammelt PPS- und TOFF-Meldungen.

    Ergebnis: reachable (gpsd erreichbar), seen (mindestens ein PPS), die
    gemittelte NMEA-Verspätung aus TOFF und die DEVICES-Liste.
    """
    host, port = _gpsd_address()
    messages: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    reachable = False
    try:
        with providers.gpsd_lines(host, port, '?WATCH={"enable":true,"json":true,"pps":true}',
                                  timeout) as lines:
            reachable = True
            for line in lines:
                try:
                    report = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(report, dict):
                    continue
                kind = report.get("class")
                if kind in {"PPS", "TOFF"}:
                    messages.append(report)
                elif kind == "DEVICES":
                    devices = parse_devices(report)
    except OSError:
        pass
    result = summarize_pps(messages)
    result["reachable"] = reachable
    result["devices"] = devices
    return result
