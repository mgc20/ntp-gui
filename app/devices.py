"""Erkennt Geräte und Fähigkeiten: serielle Ports, PPS, PTP-Uhren, Netzwerkkarten.

Liefert die Auswahllisten für das Dashboard und die Voraussetzungsprüfung für
PTP. Alles hier ist lesend und schnell; ethtool wird nur aufgerufen, wenn es
vorhanden ist.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from typing import Any

ETHTOOL = shutil.which("ethtool")
SYS_NET = os.environ.get("NTPGUI_SYS_NET", "/sys/class/net")


def _describe_serial(path: str) -> str:
    base = os.path.basename(path)
    if base.startswith("ttyACM"):
        return "USB-Modem-Gerät (typisch für u-blox-Empfänger wie VK-162)"
    if base.startswith("ttyUSB"):
        return "USB-Seriell-Adapter (z. B. GPS mit CP210x/FTDI)"
    if base.startswith(("ttyAMA", "ttyS0", "serial")):
        return "eingebauter UART (z. B. GPS-HAT am Raspberry Pi)"
    return "serieller Port"


def serial_devices() -> list[dict[str, str]]:
    found = []
    by_id = {}
    for link in glob.glob("/dev/serial/by-id/*"):
        by_id[os.path.realpath(link)] = link
    patterns = ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/ttyAMA*", "/dev/serial0", "/dev/ttyS0"]
    seen = set()
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            found.append({"path": path, "description": _describe_serial(path),
                          "stable_path": by_id.get(real, "")})
    return found


def pps_devices() -> list[dict[str, str]]:
    result = []
    for path in sorted(glob.glob("/dev/pps*")):
        name = ""
        try:
            with open(f"/sys/class/pps/{os.path.basename(path)}/name", encoding="utf-8") as handle:
                name = handle.read().strip()
        except OSError:
            pass
        result.append({"path": path, "description": name or "PPS-Quelle"})
    return result


def ptp_clocks() -> list[dict[str, str]]:
    result = []
    for path in sorted(glob.glob("/dev/ptp[0-9]*")):
        name = ""
        try:
            with open(f"/sys/class/ptp/{os.path.basename(path)}/clock_name", encoding="utf-8") as handle:
                name = handle.read().strip()
        except OSError:
            pass
        result.append({"path": path, "description": name or "PTP-Hardwareuhr"})
    return result


def parse_ethtool_t(text: str) -> dict[str, Any]:
    caps = set()
    phc = None
    in_caps = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Capabilities:"):
            in_caps = True
            continue
        match = re.match(r"(PTP Hardware Clock|Hardware timestamp provider index):\s*(\S+)", line)
        if match:
            in_caps = False
            phc = None if match.group(2) in {"none", "-1"} else match.group(2)
            continue
        if in_caps and raw.startswith(("\t", " ")):
            caps.add(line.split()[0])
        elif in_caps:
            in_caps = False
    return {
        "hardware_tx": "hardware-transmit" in caps,
        "hardware_rx": "hardware-receive" in caps,
        "hardware_clock": "hardware-raw-clock" in caps,
        "software": "software-transmit" in caps or "software-receive" in caps,
        "phc_index": phc,
    }


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def interfaces() -> list[dict[str, Any]]:
    result = []
    try:
        names = sorted(os.listdir(SYS_NET))
    except OSError:
        return result
    for name in names:
        if name == "lo" or name.startswith(("veth", "docker", "br-", "ifb", "virbr")):
            continue
        base = os.path.join(SYS_NET, name)
        device_link = os.path.realpath(os.path.join(base, "device")) if os.path.exists(
            os.path.join(base, "device")) else ""
        info: dict[str, Any] = {
            "name": name,
            "physical": bool(device_link),
            "virtual_nic": "virtio" in device_link or "vmbus" in device_link,
            "operstate": _read(os.path.join(base, "operstate")),
            "speed_mbit": _read(os.path.join(base, "speed")) or None,
            "driver": os.path.basename(os.path.realpath(os.path.join(base, "device", "driver")))
            if device_link else "",
        }
        ptp_dirs = glob.glob(os.path.join(base, "device", "ptp", "ptp*"))
        info["phc"] = f"/dev/{os.path.basename(ptp_dirs[0])}" if ptp_dirs else None
        if ETHTOOL:
            try:
                proc = subprocess.run([ETHTOOL, "-T", name], capture_output=True, text=True,
                                      timeout=3, check=False)
                caps = parse_ethtool_t(proc.stdout)
                info.update(caps)
                if caps["phc_index"] is not None and not info["phc"]:
                    info["phc"] = f"/dev/ptp{caps['phc_index']}"
            except (OSError, subprocess.TimeoutExpired):
                pass
        info["ptp_hardware"] = bool(info.get("hardware_tx") and info.get("hardware_rx") and info["phc"])
        result.append(info)
    return result


def ptp_readiness(cfg: dict) -> list[dict[str, Any]]:
    """Prüfliste für PTP – jeder Punkt mit Ergebnis und verständlicher Erklärung."""
    nics = interfaces()
    by_name = {nic["name"]: nic for nic in nics}
    chosen = by_name.get(cfg.get("ptp_interface") or "")
    physical = [nic for nic in nics if nic["physical"] and not nic["virtual_nic"]]
    checks = []

    host_net = any(nic["physical"] for nic in nics)
    checks.append({
        "key": "host_network", "ok": host_net,
        "title": "Container im Host-Netzwerk",
        "detail": ("Der Container sieht die Netzwerkkarten des Hosts."
                   if host_net else
                   "Der Container sieht nur ein virtuelles Docker-Interface. PTP braucht "
                   "„network_mode: host“, weil es Multicast und die echte Netzwerkkarte nutzt."),
    })
    checks.append({
        "key": "interface", "ok": bool(chosen),
        "title": "Interface gewählt und vorhanden",
        "detail": (f"{chosen['name']} ({chosen['driver'] or 'Treiber unbekannt'}, "
                   f"{chosen['operstate'] or 'Zustand unbekannt'})" if chosen else
                   "In den Einstellungen ein Interface wählen, über das PTP laufen soll."),
    })
    if chosen:
        hw = chosen.get("ptp_hardware")
        if chosen.get("virtual_nic"):
            detail = ("Das ist eine virtuelle Netzwerkkarte (VM). Virtuelle Karten haben keine "
                      "Hardware-Zeitstempel – PTP läuft hier höchstens mit Software-Zeitstempeln "
                      "und ist dann nicht genauer als NTP. Für echtes PTP: Container auf echter "
                      "Hardware oder die Karte per PCI-Passthrough an die VM geben.")
        elif hw:
            detail = (f"Die Karte setzt Zeitstempel selbst und hat eine PTP-Hardwareuhr "
                      f"({chosen['phc']}). Das ist die Voraussetzung für Genauigkeit im "
                      f"Nanosekundenbereich.")
        elif ETHTOOL is None:
            detail = "ethtool fehlt im Container – Fähigkeiten können nicht geprüft werden."
        else:
            detail = ("Laut „ethtool -T“ kann diese Karte keine Hardware-Zeitstempel. PTP geht "
                      "dann nur mit „Zeitstempel: Software“. Gute Karten fürs Homelab: Intel "
                      "i210, i211, i225, i226, X550; Raspberry Pi CM4/CM5.")
        checks.append({"key": "hardware_timestamps", "ok": bool(hw),
                       "warn": not hw and cfg.get("ptp_time_stamping") == "software",
                       "title": "Hardware-Zeitstempel (ethtool -T)", "detail": detail})
        phc = chosen.get("phc")
        checks.append({
            "key": "phc_device", "ok": bool(phc and os.path.exists(phc)),
            "title": "PTP-Hardwareuhr im Container",
            "detail": (f"{phc} ist im Container vorhanden." if phc and os.path.exists(phc) else
                       f"Die Karte hat {phc}, aber das Gerät fehlt im Container – unter "
                       f"„devices:“ eintragen: - {phc}:{phc}" if phc else
                       "Keine PTP-Hardwareuhr an dieser Karte."),
        })
    elif physical:
        candidates = [n["name"] for n in physical if n.get("ptp_hardware")]
        if candidates:
            checks.append({"key": "candidates", "ok": True, "title": "Geeignete Karten gefunden",
                           "detail": "Mit Hardware-Zeitstempeln: " + ", ".join(candidates)})
    checks.append({
        "key": "capability", "ok": None,
        "title": "Rechte: NET_ADMIN",
        "detail": "ptp4l schaltet Hardware-Zeitstempel ein und braucht dafür "
                  "„cap_add: [NET_ADMIN, NET_RAW]“. Fehlen sie, meldet das PTP-Log "
                  "„ioctl SIOCSHWTSTAMP failed“.",
    })
    checks.append({
        "key": "network", "ok": None,
        "title": "Netzwerk zwischen den Teilnehmern",
        "detail": "Jeder Switch dazwischen verzögert Pakete unterschiedlich lang. Einfache "
                  "Switches funktionieren, kosten aber Genauigkeit (Mikrosekunden). Für "
                  "Nanosekunden braucht es Switches mit PTP-Unterstützung (Transparent oder "
                  "Boundary Clock) – oder eine direkte Verbindung.",
    })
    checks.append({
        "key": "clients", "ok": None,
        "title": "Clients, die PTP sprechen",
        "detail": "Linux mit linuxptp (ptp4l + phc2sys) und viele Netzwerkgeräte können es. "
                  "Windows nur eingeschränkt, macOS gar nicht – diese Geräte bleiben bei NTP, "
                  "das dieser Server parallel anbietet.",
    })
    return checks


def summary(cfg: dict) -> dict[str, Any]:
    return {
        "serial": serial_devices(),
        "pps": pps_devices(),
        "ptp_clocks": ptp_clocks(),
        "interfaces": interfaces(),
        "ptp_checks": ptp_readiness(cfg),
        "ethtool": bool(ETHTOOL),
    }
