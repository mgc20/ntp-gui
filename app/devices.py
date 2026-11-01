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

# Wurzelpfade lassen sich für Tests umbiegen (falscher /sys-, /proc-, /dev-Baum).
CAP_NET_ADMIN = 12
CAP_NET_RAW = 13
CAP_SYS_ADMIN = 21
CAP_SYS_NICE = 23
CAP_SYS_TIME = 25


def sys_root() -> str:
    return os.environ.get("NTPGUI_SYS_ROOT", "/sys")


def proc_root() -> str:
    return os.environ.get("NTPGUI_PROC_ROOT", "/proc")


def dev_root() -> str:
    return os.environ.get("NTPGUI_DEV_ROOT", "/dev")


def sys_net() -> str:
    return os.environ.get("NTPGUI_SYS_NET") or os.path.join(sys_root(), "class", "net")


def dev_path(path: str) -> str:
    """Übersetzt einen Pfad wie /dev/ptp0 in den (für Tests umbiegbaren) /dev-Baum."""
    if path == "/dev" or path.startswith("/dev/"):
        return os.path.join(dev_root(), path[5:]) if len(path) > 5 else dev_root()
    return path


def public_dev(path: str) -> str:
    """Gegenstück zu dev_path(): Pfad im umgebogenen Baum wieder als /dev/... zeigen."""
    root = dev_root().rstrip("/") or "/"
    if root != "/dev" and (path == root or path.startswith(root + "/")):
        return "/dev" + path[len(root):]
    return path


def parse_cap_hex(text: str) -> int | None:
    try:
        return int(text.strip(), 16)
    except (ValueError, AttributeError):
        return None


def proc_status_field(name: str) -> str:
    """Ein Feld aus /proc/self/status, z. B. CapEff oder Seccomp."""
    try:
        with open(os.path.join(proc_root(), "self", "status"), encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key == name:
                    return value.strip()
    except OSError:
        pass
    return ""


def cap_eff() -> int | None:
    return parse_cap_hex(proc_status_field("CapEff"))


def has_cap(bit: int, caps: int | None = None) -> bool | None:
    caps = cap_eff() if caps is None else caps
    if caps is None:
        return None
    return bool(caps >> bit & 1)


def network_mode() -> str:
    """host | bridge | unknown – anhand dessen, was im Netz-Namespace sichtbar ist.

    Im Host-Netz sieht der Container docker0 oder echte Karten (mit „device“-Link).
    Im Bridge-Netz gibt es nur lo und ein veth-Ende ohne „device“-Link, dessen
    iflink auf die Gegenstelle im Host zeigt (macvlan/ipvlan ebenso: kein Host-Netz).
    """
    base = sys_net()
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return "unknown"
    names = [n for n in names if n != "lo"]
    if not names:
        return "unknown"
    if any(n == "docker0" or n.startswith("br-") for n in names):
        return "host"
    if any(os.path.exists(os.path.join(base, n, "device")) for n in names):
        return "host"
    for name in names:
        iflink, ifindex = _read(os.path.join(base, name, "iflink")), _read(os.path.join(base, name, "ifindex"))
        if iflink and ifindex and iflink != ifindex:
            return "bridge"
    return "unknown"


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
    for link in glob.glob(os.path.join(dev_root(), "serial", "by-id", "*")):
        by_id[os.path.realpath(link)] = public_dev(link)
    patterns = ["ttyACM*", "ttyUSB*", "ttyAMA*", "serial0", "ttyS0"]
    seen = set()
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.join(dev_root(), pattern))):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            shown = public_dev(path)
            found.append({"path": shown, "description": _describe_serial(shown),
                          "stable_path": by_id.get(real, "")})
    return found


def pps_devices() -> list[dict[str, str]]:
    result = []
    for path in sorted(glob.glob(os.path.join(dev_root(), "pps*"))):
        name = _read(os.path.join(sys_root(), "class", "pps", os.path.basename(path), "name"))
        result.append({"path": public_dev(path), "description": name or "PPS-Quelle"})
    return result


def ptp_clocks() -> list[dict[str, str]]:
    result = []
    for path in sorted(glob.glob(os.path.join(dev_root(), "ptp[0-9]*"))):
        name = _read(os.path.join(sys_root(), "class", "ptp", os.path.basename(path), "clock_name"))
        result.append({"path": public_dev(path), "description": name or "PTP-Hardwareuhr"})
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


def _ethtool(name: str) -> str | None:
    """Ausgabe von „ethtool -T <name>“ oder None, wenn ethtool fehlt/scheitert."""
    if not ETHTOOL:
        return None
    try:
        proc = subprocess.run([ETHTOOL, "-T", name], capture_output=True, text=True,
                              timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout


def interfaces() -> list[dict[str, Any]]:
    result = []
    base_dir = sys_net()
    try:
        names = sorted(os.listdir(base_dir))
    except OSError:
        return result
    for name in names:
        if name == "lo" or name.startswith(("veth", "docker", "br-", "ifb", "virbr")):
            continue
        base = os.path.join(base_dir, name)
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
            "wireless": os.path.exists(os.path.join(base, "wireless"))
            or os.path.exists(os.path.join(base, "phy80211")),
        }
        ptp_dirs = sorted(glob.glob(os.path.join(base, "device", "ptp", "ptp*")))
        info["phc"] = f"/dev/{os.path.basename(ptp_dirs[0])}" if ptp_dirs else None
        output = _ethtool(name)
        info["ethtool"] = output is not None
        if output is not None:
            caps = parse_ethtool_t(output)
            info.update(caps)
            if caps["phc_index"] is not None and not info["phc"]:
                info["phc"] = f"/dev/ptp{caps['phc_index']}"
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

    mode = network_mode()
    host_net = {"host": True, "bridge": False}.get(mode)
    checks.append({
        "key": "host_network", "ok": host_net,
        "title": "Container im Host-Netzwerk",
        "detail": ("Der Container sieht die Netzwerkkarten des Hosts."
                   if host_net else
                   "Der Container sieht nur ein virtuelles Docker-Interface. PTP braucht "
                   "„network_mode: host“, weil es Multicast und die echte Netzwerkkarte nutzt."
                   if host_net is False else
                   "Nicht sicher erkennbar, ob der Container im Host-Netz läuft. Für PTP muss "
                   "in der Compose-Datei „network_mode: host“ stehen."),
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
        elif not chosen.get("ethtool"):
            detail = "ethtool fehlt im Container – Fähigkeiten können nicht geprüft werden."
        else:
            detail = ("Laut „ethtool -T“ kann diese Karte keine Hardware-Zeitstempel. PTP geht "
                      "dann nur mit „Zeitstempel: Software“. Gute Karten fürs Homelab: Intel "
                      "i210, i211, i225, i226, X550; Raspberry Pi CM4/CM5.")
        checks.append({"key": "hardware_timestamps", "ok": bool(hw),
                       "warn": not hw and cfg.get("ptp_time_stamping") == "software",
                       "title": "Hardware-Zeitstempel (ethtool -T)", "detail": detail})
        phc = chosen.get("phc")
        phc_there = bool(phc and os.path.exists(dev_path(phc)))
        checks.append({
            "key": "phc_device", "ok": phc_there,
            "title": "PTP-Hardwareuhr im Container",
            "detail": (f"{phc} ist im Container vorhanden." if phc_there else
                       f"Die Karte hat {phc}, aber das Gerät fehlt im Container – unter "
                       f"„devices:“ eintragen: - {phc}:{phc}" if phc else
                       "Keine PTP-Hardwareuhr an dieser Karte."),
        })
    elif physical:
        candidates = [n["name"] for n in physical if n.get("ptp_hardware")]
        if candidates:
            checks.append({"key": "candidates", "ok": True, "title": "Geeignete Karten gefunden",
                           "detail": "Mit Hardware-Zeitstempeln: " + ", ".join(candidates)})
    caps = cap_eff()
    net_admin, net_raw = has_cap(CAP_NET_ADMIN, caps), has_cap(CAP_NET_RAW, caps)
    # Effektiver Transport nach Profil (gPTP läuft immer über L2/Raw-Socket).
    import settings  # spät importieren: devices.py bleibt ohne settings testbar
    need_raw = settings.ptp_profile_values(cfg)[0].get("ptp_transport") == "L2"
    if caps is None:
        cap_ok, cap_detail = None, ("Die Rechte des Containers sind nicht lesbar. ptp4l braucht "
                                    "„cap_add: [NET_ADMIN, NET_RAW]“.")
    elif net_admin and (net_raw or not need_raw):
        cap_ok, cap_detail = True, ("NET_ADMIN ist vorhanden: ptp4l darf die Hardware-Zeitstempel "
                                    "der Karte einschalten."
                                    + ("" if net_raw else " NET_RAW fehlt, das braucht nur "
                                       "der Transport „Ethernet direkt (L2)“."))
    else:
        missing = [n for n, ok in (("NET_ADMIN", net_admin), ("NET_RAW", net_raw)) if not ok]
        cap_ok, cap_detail = False, (
            f"Es fehlt {' und '.join(missing)}. ptp4l schaltet Hardware-Zeitstempel ein und "
            "braucht dafür in der Compose-Datei unter „cap_add:“ die Zeilen „- NET_ADMIN“ und "
            "„- NET_RAW“. Ohne sie meldet das PTP-Log „ioctl SIOCSHWTSTAMP failed“.")
    checks.append({
        "key": "capability", "ok": cap_ok,
        "title": "Rechte: NET_ADMIN",
        "detail": cap_detail,
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
