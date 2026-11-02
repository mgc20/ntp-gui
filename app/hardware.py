"""Hardware-Check: Was kann diese Hardware von dem, was ntp-gui kann?

Liest nur: sysfs, /proc, /dev, die gpsd-Geräteliste und chrony-Tracking. Es
werden keine TTYs geöffnet (ein close() kann über HUPCL die DTR-Leitung fallen
lassen und manche Boards zurücksetzen). /dev/ppsN und /dev/ptpN werden zum Test
kurz lesend geöffnet und sofort geschlossen – das ist harmlos.

Wichtig im Container: /sys/class/{tty,pps,ptp,rtc} zeigen die Geräte des
HOSTS, auch wenn sie nicht in den Container gereicht wurden. Daraus folgt die
häufigste Diagnose „am Host vorhanden, im Container fehlt …“. /sys/class/net
zeigt dagegen nur den Netz-Namespace des Containers.

Wurzelpfade für Tests: NTPGUI_SYS_ROOT, NTPGUI_PROC_ROOT, NTPGUI_DEV_ROOT und
NTPGUI_ROOT (für /.dockerenv und /run/.containerenv).
"""

from __future__ import annotations

import errno
import glob
import os
import platform
import re
import threading
import time
from typing import Any

import devices
from devices import (CAP_NET_ADMIN, CAP_NET_RAW, CAP_SYS_NICE, CAP_SYS_TIME, dev_path,
                     dev_root, proc_root, sys_root)

CACHE_TTL = 30.0
PPS_SAMPLE_SECONDS = 1.2
PPS_CACHE_MAX_AGE = 30.0
GPSD_PROBE_TTL = 60.0
GPSD_PROBE_SECONDS = 1.5

_LOCK = threading.Lock()
_REPORT: dict[str, Any] | None = None
_REPORT_TIME = 0.0
_PPS_CACHE: dict[str, dict[str, Any]] = {}
_GPSD_PROBE: dict[str, Any] | None = None
_GPSD_PROBE_TIME = 0.0

MODULES = ("pps_gpio", "pps_ldisc", "pps_core", "ptp", "ptp_kvm", "cdc_acm", "cp210x",
           "ftdi_sio", "pl2303", "ch341")

USB_SERIAL_DRIVERS = {"ftdi_sio": "FTDI", "cp210x": "CP210x", "pl2303": "PL2303",
                      "ch341-uart": "CH340/CH341", "ch341": "CH340/CH341"}
UART_DRIVERS = {"uart-pl011", "serial8250", "dw-apb-uart", "bcm2835-aux-uart", "8250",
                "serial", "pl011", "sc16is7xx", "meson_uart", "imx-uart", "tegra-uart",
                "fsl-lpuart", "omap8250", "mxs-auart", "sunxi-uart"}

KNOWN_USB = {
    "1546:01a5": "u-blox 5",
    "1546:01a6": "u-blox 6",
    "1546:01a7": "u-blox 7 (z. B. VK-162/VK-172)",
    "1546:01a8": "u-blox M8",
    "1546:01a9": "u-blox F9/M9",
    "091e:0003": "Garmin USB-GPS",
    "067b:2303": "PL2303-Adapter (z. B. BU-353S4, Navisys GR-701W)",
    "067b:23a3": "PL2303-Adapter",
    "10c4:ea60": "CP210x-Adapter",
    "0403:6001": "FTDI-Adapter (FT232R)",
    "0403:6015": "FTDI-Adapter (FT231X)",
    "1a86:7523": "CH340-Adapter",
}
UBLOX_GENERATIONS = {
    "00040005": "u-blox 5", "00040007": "u-blox 6", "00070000": "u-blox 7",
    "00080000": "u-blox M8", "00190000": "u-blox F9/M9", "000A0000": "u-blox M10",
}

NIC_GOOD = {"igb", "igc", "ixgbe", "i40e", "ice", "mlx5_core", "mlx4_en", "bnxt_en", "sfc",
            "lan743x", "macb", "atlantic", "tsnep", "am65-cpsw-nuss", "cpsw"}
NIC_IF_ETHTOOL = {"stmmac", "st_gmac", "dwmac-rk", "dwmac-sun8i", "rk_gmac-dwmac",
                  "stmmaceth", "fec", "dwc-eth-dwmac", "intel-eth-pci", "mvpp2", "mvneta"}
NIC_LIMITED = {"e1000e", "tg3"}
NIC_NONE = {"r8169", "r8125", "r8152", "ax88179_178a", "lan78xx", "smsc95xx", "e1000",
            "brcmfmac", "iwlwifi", "mt7921e", "mt7921u", "mt76x2u", "rtw88_pci", "rtw89_pci",
            "ath9k", "ath10k_pci", "ath11k_pci", "asix", "cdc_ether", "r8188eu"}
NIC_VIRTUAL = {"virtio_net", "hv_netvsc", "vmxnet3", "xen-netfront", "vif", "veth", "bridge",
               "macvlan", "ipvlan", "tun", "wireguard", "igbvf", "ixgbevf", "iavf", "ena",
               "gve", "netvsc"}
GOOD_NICS_TEXT = "Intel i210/i211/i225/i226/i350/X550, Raspberry Pi 5, CM4 oder CM5"

PPS_GPIO_NAME = re.compile(r"^pps(@[0-9a-fA-F]+)?\.-?\d+$|^pps-gpio")


# ---------------------------------------------------------------------------
# Kleine Leser (alle Pfade über die umbiegbaren Wurzeln)
# ---------------------------------------------------------------------------

def _sys(*parts: str) -> str:
    return os.path.join(sys_root(), *parts)


def _proc(*parts: str) -> str:
    return os.path.join(proc_root(), *parts)


def _root(*parts: str) -> str:
    return os.path.join(os.environ.get("NTPGUI_ROOT", "/"), *parts)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().replace("\x00", "").strip()
    except OSError:
        return ""


def _read_int(path: str) -> int | None:
    try:
        return int(_read(path))
    except ValueError:
        return None


def _basename_link(path: str) -> str:
    return os.path.basename(os.path.realpath(path)) if os.path.exists(path) else ""


def _machine() -> str:
    return platform.machine()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _monotonic() -> float:
    return time.monotonic()


def _now() -> float:
    return time.time()


def parse_pps_assert(text: str) -> tuple[int, int, int] | None:
    """„1170026870.983207967#8“ → (sec, nsec, seq); None bei unlesbarem Wert."""
    match = re.match(r"^\s*(\d+)\.(\d+)#(\d+)\s*$", text or "")
    if not match:
        return None
    frac = match.group(2)
    nsec = int((frac + "000000000")[:9])
    return int(match.group(1)), nsec, int(match.group(3))


def parse_proc_devices(text: str) -> dict[str, int]:
    """Zeichengeräte aus /proc/devices: Name → Major (pps/ptp sind dynamisch)."""
    majors: dict[str, int] = {}
    in_char = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Character devices"):
            in_char = True
            continue
        if line.startswith("Block devices"):
            break
        if in_char:
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit():
                majors.setdefault(parts[1], int(parts[0]))
    return majors


def parse_mountinfo_dev(text: str) -> bool:
    """Ist /dev ein devtmpfs des Hosts (bind-gemountet)? Docker selbst nimmt tmpfs."""
    for line in text.splitlines():
        left, sep, right = line.partition(" - ")
        if not sep:
            continue
        fields = left.split()
        fs = right.split()
        if len(fields) >= 5 and fields[4] == "/dev" and fs and fs[0] == "devtmpfs":
            return True
    return False


def _device_major(cls: str, name: str) -> int | None:
    dev = _read(_sys("class", cls, name, "dev"))
    if ":" in dev:
        try:
            return int(dev.split(":")[0])
        except ValueError:
            return None
    return None


def _try_open(path: str) -> tuple[bool | None, str | None]:
    """Öffnet ein PPS-/PTP-Gerät kurz lesend. (usable, Fehlercode)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        return False, errno.errorcode.get(exc.errno or 0, str(exc.errno))
    os.close(fd)
    return True, None


def _open_error_text(code: str | None, dev: str) -> str | None:
    if not code:
        return None
    if code == "EPERM":
        return (f"EPERM: Öffnen von {dev} verweigert – im Container fehlt die Freigabe der "
                "Gerätenummer (device_cgroup_rules).")
    if code == "EACCES":
        return f"EACCES: keine Leserechte für {dev}."
    if code == "ENOENT":
        return f"ENOENT: {dev} fehlt im Container."
    if code == "EBUSY":
        return f"EBUSY: {dev} ist belegt."
    return f"{code}: {dev} lässt sich nicht öffnen."


# ---------------------------------------------------------------------------
# Plattform und Rechte
# ---------------------------------------------------------------------------

def _board(model: str) -> dict[str, Any]:
    family = None
    if re.search(r"Raspberry Pi 5", model):
        family = "pi5"
    elif re.search(r"Compute Module 5", model):
        family = "cm5"
    elif re.search(r"Compute Module 4", model):
        family = "cm4"
    elif re.search(r"Raspberry Pi 4", model):
        family = "pi4"
    elif re.search(r"Raspberry Pi 3", model):
        family = "pi3"
    elif re.search(r"Zero 2", model):
        family = "pi-zero2"
    elif "Raspberry Pi" in model:
        family = "pi-other"
    ptp = {"pi5": True, "cm5": True, "cm4": True, "pi4": False, "pi3": False,
           "pi-zero2": False, "pi-other": False}.get(family or "")
    rtc = {"pi5": True, "cm5": True, "cm4": None, "pi4": False, "pi3": False,
           "pi-zero2": False, "pi-other": False}.get(family or "")
    return {"model": model, "family": family, "ptp_expected": ptp, "rtc_expected": rtc}


def _hypervisor(cpuinfo: str, dmi: dict[str, str]) -> str | None:
    vendor = dmi.get("sys_vendor", "")
    product = dmi.get("product_name", "")
    bios = dmi.get("bios_vendor", "")
    flagged = any(line.startswith("flags") and " hypervisor" in line
                  for line in cpuinfo.splitlines())
    if "Proxmox" in bios:
        return "Proxmox (KVM/QEMU)"
    if vendor.startswith("QEMU") or "KVM" in product or "QEMU" in product:
        return "KVM/QEMU"
    if vendor.startswith("VMware"):
        return "VMware"
    if vendor.startswith("Microsoft") and "Virtual" in product:
        return "Hyper-V"
    if vendor.startswith("innotek") or "VirtualBox" in product:
        return "VirtualBox"
    if vendor.startswith("Xen") or _read(_sys("hypervisor", "type")) == "xen":
        return "Xen"
    if vendor.startswith(("Amazon EC2",)) and flagged:
        return "Amazon EC2"
    if flagged:
        return "VM (unbekannter Hypervisor)"
    return None


def platform_info(network: str, privileged: bool) -> dict[str, Any]:
    if os.path.exists(_root(".dockerenv")):
        container = "docker"
    elif os.path.exists(_root("run", ".containerenv")):
        container = "podman"
    else:
        cgroup = _read(_proc("1", "cgroup"))
        container = "docker" if "docker" in cgroup else "podman" if "libpod" in cgroup else None
    osrelease = _read(_proc("sys", "kernel", "osrelease"))
    docker_desktop = "linuxkit" in osrelease.lower()
    wsl = "microsoft" in osrelease.lower() or "wsl" in osrelease.lower()
    dmi = {key: _read(_sys("class", "dmi", "id", key))
           for key in ("sys_vendor", "product_name", "bios_vendor")}
    cpuinfo = _read(_proc("cpuinfo"))
    model = _read(_proc("device-tree", "model")) or _read(_sys("firmware", "devicetree", "base", "model"))
    if not model:
        match = re.search(r"^Model\s*:\s*(.+)$", cpuinfo, re.M)
        model = match.group(1).strip() if match else ""
    board = _board(model)
    hypervisor = _hypervisor(cpuinfo, dmi)
    parts = []
    if board["family"]:
        parts.append(re.sub(r"\s+Rev\s+\S+$", "", model))
    elif hypervisor:
        parts.append(hypervisor if hypervisor.startswith("VM") else f"VM ({hypervisor})")
    elif dmi["product_name"] and dmi["product_name"] not in {"To Be Filled By O.E.M.",
                                                             "System Product Name", "Default string"}:
        parts.append(f"{dmi['sys_vendor']} {dmi['product_name']}".strip())
    elif model:
        parts.append(model)
    else:
        parts.append(f"{_machine() or 'unbekannt'}-Rechner")
    if docker_desktop:
        parts.append("Docker Desktop")
    elif wsl:
        parts.append("WSL2")
    parts.append({"docker": "Docker", "podman": "Podman"}.get(container or "", "ohne Container"))
    parts.append({"host": "Host-Netz", "bridge": "Bridge-Netz"}.get(network, "Netz unbekannt"))
    if privileged:
        parts.append("privilegiert")
    return {
        "container": container, "docker_desktop": docker_desktop, "wsl": wsl,
        "arch": _machine(), "hypervisor": hypervisor,
        "dmi": {"sys_vendor": dmi["sys_vendor"], "product_name": dmi["product_name"]},
        "board": board, "summary": " · ".join(parts),
    }


def _modules() -> dict[str, bool]:
    loaded = set()
    for line in _read(_proc("modules")).splitlines():
        if line.split():
            loaded.add(line.split()[0])
    return {name: name in loaded or os.path.isdir(_sys("module", name)) for name in MODULES}


def permissions_info() -> dict[str, Any]:
    caps = devices.cap_eff()
    last_cap = _read_int(_proc("sys", "kernel", "cap_last_cap")) or 40
    seccomp = devices.proc_status_field("Seccomp")
    privileged = bool(caps is not None and caps == (1 << (last_cap + 1)) - 1 and seccomp in {"0", ""})
    by_id = os.path.isdir(os.path.join(dev_root(), "serial", "by-id"))
    dev_mounted = parse_mountinfo_dev(_read(_proc("self", "mountinfo"))) or by_id

    def bit(n: int) -> bool:
        return bool(devices.has_cap(n, caps)) if caps is not None else False

    return {
        "cap_eff": f"{caps:016x}" if caps is not None else "",
        "privileged": privileged,
        "sys_time": bit(CAP_SYS_TIME), "net_admin": bit(CAP_NET_ADMIN),
        "net_raw": bit(CAP_NET_RAW), "sys_nice": bit(CAP_SYS_NICE),
        "network": devices.network_mode(), "dev_mounted": dev_mounted,
        "modules": _modules(),
    }


# ---------------------------------------------------------------------------
# GPS-Empfänger
# ---------------------------------------------------------------------------

def gpsd_details(dev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not dev:
        return None
    subtype = str(dev.get("subtype") or "")
    subtype1 = str(dev.get("subtype1") or "")
    generation = None
    match = re.search(r"HW\s+([0-9A-Fa-f]{8})", subtype)
    if match:
        generation = UBLOX_GENERATIONS.get(match.group(1).upper())
    match = re.search(r"MOD=([A-Za-z0-9-]+)", subtype1 + "," + subtype)
    module = match.group(1) if match else None
    timing = bool(module and re.match(r"^[A-Z]+-[A-Z0-9]*T(-|$)", module)) or "FWVER=TIM" in subtype1
    bps = dev.get("bps")
    return {
        "driver": str(dev.get("driver") or ""), "subtype": subtype,
        "generation": generation, "module": module, "timing": timing,
        "activated": bool(dev.get("activated")),
        "bps": bps if isinstance(bps, int) else None,
    }


def _usb_info(tty_dev: str) -> dict[str, Any] | None:
    path = tty_dev
    for _ in range(5):
        if os.path.exists(os.path.join(path, "idVendor")):
            speed = _read(os.path.join(path, "speed"))
            try:
                speed_mbit = int(float(speed)) if speed else None
            except ValueError:
                speed_mbit = None
            return {"vid": _read(os.path.join(path, "idVendor")).lower(),
                    "pid": _read(os.path.join(path, "idProduct")).lower(),
                    "manufacturer": _read(os.path.join(path, "manufacturer")),
                    "product": _read(os.path.join(path, "product")),
                    "speed_mbit": speed_mbit}
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None


def _interface_label(driver: str, usb: dict | None) -> str:
    if driver == "cdc_acm":
        return "USB (CDC-ACM)"
    if driver in USB_SERIAL_DRIVERS:
        return f"USB-Seriell ({USB_SERIAL_DRIVERS[driver]})"
    if usb:
        return f"USB ({driver or 'Treiber unbekannt'})"
    if driver in UART_DRIVERS or driver:
        return "UART"
    return "seriell"


def _by_id_map() -> dict[str, str]:
    result = {}
    for link in sorted(glob.glob(os.path.join(dev_root(), "serial", "by-id", "*"))):
        result.setdefault(os.path.basename(os.path.realpath(link)), devices.public_dev(link))
    return result


def _resolve_tty(path: str) -> str:
    """Konfigurierter Pfad (auch by-id-Link) → TTY-Name wie ttyACM0."""
    if not path:
        return ""
    local = dev_path(path)
    real = os.path.realpath(local) if os.path.exists(local) else local
    return os.path.basename(real)


def _tty_candidates(cfg: dict, gpsd_paths: set[str], ldisc_paths: set[str], is_pi: bool) -> list[str]:
    base = _sys("class", "tty")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    configured = _resolve_tty(str(cfg.get("gps_device") or ""))
    result = []
    for name in names:
        if not re.match(r"^(ttyACM\d+|ttyUSB\d+|ttyAMA\d+|ttyS\d+|ttyAML\d+|ttyTHS\d+|ttymxc\d+|serial\d+)$", name):
            continue
        if not os.path.exists(os.path.join(base, name, "device")):
            continue
        if name.startswith(("ttyACM", "ttyUSB")):
            result.append(name)
            continue
        wanted = name == configured or name in gpsd_paths or name in ldisc_paths
        if name.startswith("ttyS") and _read(os.path.join(base, name, "type")) == "0" and not wanted:
            continue  # 8250-Platzhalter ohne echte Hardware
        if wanted or (is_pi and name in {"ttyAMA0", "ttyS0"}):
            result.append(name)
    return result


def _receiver_product(usb: dict | None, gpsd: dict | None, tty: str) -> tuple[str, bool]:
    """(Produkttext, sieht nach GPS aus)."""
    known = KNOWN_USB.get(f"{usb['vid']}:{usb['pid']}") if usb else None
    gps_like = bool(gpsd) or bool(usb and usb["vid"] == "1546") or bool(
        usb and re.search(r"GPS|GNSS", f"{usb['product']} {usb['manufacturer']}", re.I))
    if gpsd and gpsd.get("module"):
        return f"u-blox {gpsd['module']}" if gpsd.get("generation") else gpsd["module"], True
    if gpsd and gpsd.get("generation"):
        if known and known.startswith(gpsd["generation"]):
            return known, True
        return gpsd["generation"], True
    if known and usb and usb["vid"] in {"1546", "091e"}:
        return known, True
    if usb and usb.get("product"):
        return usb["product"], gps_like
    if known:
        return known, gps_like
    if gpsd and gpsd.get("driver"):
        return f"{gpsd['driver']}-Empfänger", True
    return f"Gerät an {tty}", gps_like


def receivers_info(cfg: dict, platform_: dict, perms: dict, pps_list: list[dict],
                   gps_status: dict, gpsd_pps: dict | None) -> list[dict[str, Any]]:
    gpsd_devs = {}
    for dev in (gps_status or {}).get("devices") or []:
        name = _resolve_tty(dev.get("path") or "")
        if name:
            gpsd_devs[name] = dev
    ldisc = {os.path.basename(p["path"]): p for p in pps_list if p["kind"] == "ldisc" and p["path"]}
    gpio = [p for p in pps_list if p["kind"] == "gpio"]
    is_pi = bool(platform_["board"]["family"])
    names = _tty_candidates(cfg, set(gpsd_devs), set(ldisc), is_pi)
    by_id = _by_id_map()
    pps_seen_on = {os.path.basename(d) for d in (gpsd_pps or {}).get("pps_devices") or []}
    gps_on = bool(cfg.get("gps_enable"))
    configured_raw = str(cfg.get("gps_device") or "").strip()
    configured_tty = "" if configured_raw.lower() == "auto" else _resolve_tty(configured_raw)
    result = []
    for name in names:
        base = _sys("class", "tty", name)
        tty_dev = os.path.realpath(os.path.join(base, "device"))
        driver = _basename_link(os.path.join(tty_dev, "driver"))
        usb = _usb_info(tty_dev) if name.startswith(("ttyACM", "ttyUSB")) or driver in USB_SERIAL_DRIVERS else None
        local = os.path.join(dev_root(), name)
        in_container = os.path.exists(local)
        gpsd = gpsd_details(gpsd_devs.get(name))
        if gpsd and gpsd["activated"]:
            usable: bool | None = True
        elif not in_container:
            usable = False
        elif not os.access(local, os.R_OK | os.W_OK):
            usable = False
        elif gpsd and gps_status.get("running") and not gpsd["activated"]:
            usable = False
        elif perms["dev_mounted"] and not perms["privileged"]:
            usable = None  # /dev eingehängt: ob die cgroup-Regel passt, zeigt erst gpsd
        else:
            usable = True
        product, gps_like = _receiver_product(usb, gpsd, name)
        gps_like = gps_like or (gps_on and name == configured_tty) or name in pps_seen_on
        interface = _interface_label(driver, usb)
        # PPS-Weg: entscheidet die Anbindung, nicht die Chip-Generation.
        live_gpio = next((p for p in gpio if p["state"] == "live"), None)
        if driver == "cdc_acm" or name.startswith("ttyACM"):
            # ttyACM* legt ausschließlich cdc_acm an (USB-Modem-Klasse): Über diese Anbindung
            # kommt kein PPS beim Rechner an – auch dann nicht, wenn sich der Treiber-Link in
            # /sys nicht lesen lässt (sonst landete der Stick fälschlich bei „USB-Seriell/DCD“).
            # Das gilt auch, wenn eine PPS-Leitungsdisziplin daranhängt: gpsd hängt sie beim
            # Öffnen selbst an jede serielle Schnittstelle (/dev/pps0 „acm0“) – Impulse kommen
            # darüber bei einem USB-Stick trotzdem nie an (Fehlerbericht VK-162, 1.3.2).
            pps_path = "none"
        elif name in ldisc:
            pps_path = "dcd_usb" if (usb or driver in USB_SERIAL_DRIVERS) else "dcd_uart"
        elif driver in USB_SERIAL_DRIVERS or usb:
            pps_path = "dcd_usb"
        elif gpio:
            pps_path = "gpio"
        elif name in pps_seen_on:
            pps_path = "dcd_uart"
        elif is_pi:
            pps_path = "possible_gpio"
        else:
            pps_path = "unknown"
        pps_dev = ldisc.get(name) or (live_gpio or (gpio[0] if gpio else None))
        accuracy = {
            "none": "1–10 ms nach Kalibrierung",
            "dcd_usb": "~1 ms mit PPS über DCD, sonst 1–10 ms",
            "dcd_uart": "~1–5 µs",
            "gpio": "~1 µs",
            "possible_gpio": "1–10 ms (mit PPS-Pin an GPIO: ~1 µs)",
            "unknown": "1–10 ms ohne PPS",
        }[pps_path]
        tone = "info"
        chip = USB_SERIAL_DRIVERS.get(driver, driver or "?")
        if not gps_like and not gpsd:
            verdict = (f"Serielles Gerät an {name} ({product}, {interface}) – ob ein GPS-Empfänger "
                       "dranhängt, zeigt gpsd, sobald GPS eingeschaltet ist.")
        elif pps_path == "none":
            tip = ("Modul mit PPS-Ausgang an GPIO" if is_pi else
                   "Empfänger mit PPS an einer echten seriellen Schnittstelle (DCD) oder eine PCIe-Timecard")
            verdict = (f"Dein Empfänger: {product} – USB, kein PPS möglich → Genauigkeit 1–10 ms; "
                       f"für µs: {tip}.")
            tone = "warn"
        elif pps_path == "dcd_usb":
            if name in pps_seen_on or (name in ldisc and ldisc[name]["state"] == "live"):
                verdict = (f"Dein Empfänger: {product} über USB-Seriell-Adapter ({chip}): PPS über die "
                           "DCD-Leitung erkannt → ~1 ms (USB-Takt). "
                           + ("„PPS über gpsd“ ist eingeschaltet." if cfg.get("gps_pps_shm")
                              else "„PPS über gpsd“ einschalten."))
                tone = "good"
            elif gpsd_pps is None or not gps_on:
                verdict = (f"Dein Empfänger: {product} über USB-Seriell-Adapter ({chip}). PPS nur, wenn "
                           "das Board den Impuls auf DCD legt – ob gpsd einen sieht, zeigt sich mit "
                           "eingeschaltetem GPS. Ohne PPS: 1–10 ms.")
            else:
                verdict = (f"Dein Empfänger: {product} über USB-Seriell-Adapter ({chip}). PPS nur, wenn "
                           "das Board den Impuls auf DCD legt – gpsd hat bisher keinen gesehen. "
                           "Ohne PPS: 1–10 ms.")
                tone = "warn"
        elif pps_path == "gpio":
            pps_name = pps_dev["dev"] if pps_dev else "/dev/pps0"
            if live_gpio:
                verdict = (f"Dein Empfänger: {product} am {interface} mit PPS an GPIO ({pps_name}) → "
                           "~1 µs. Stratum 1 in Bestform.")
                tone = "good"
            else:
                verdict = (f"Dein Empfänger: {product} am {interface}. Die PPS-Quelle {pps_name} (GPIO) "
                           "ist da, liefert aber keine Impulse – Fix abwarten, Pin und Overlay prüfen.")
                tone = "warn"
        elif pps_path == "dcd_uart":
            pps_name = ldisc[name]["dev"] if name in ldisc else "gpsd"
            live = (name in ldisc and ldisc[name]["state"] == "live") or name in pps_seen_on
            verdict = (f"Dein Empfänger: {product} an der seriellen Schnittstelle {name} mit PPS über "
                       f"die DCD-Leitung ({pps_name}) → ~1–5 µs."
                       + ("" if live else " Bisher kamen aber keine Impulse an."))
            tone = "good" if live else "warn"
        elif pps_path == "possible_gpio":
            verdict = ("Empfänger am Pi-UART. Hat dein HAT einen PPS-Pin (meist GPIO18 oder GPIO4), "
                       "schalte ihn mit „dtoverlay=pps-gpio,gpiopin=<n>“ frei.")
        else:
            verdict = (f"Empfänger an der seriellen Schnittstelle {name} ({driver or 'Treiber unbekannt'}). "
                       "NMEA ergibt 1–10 ms; PPS ginge über die DCD-Leitung („PPS über gpsd“).")
        if gpsd and gpsd["timing"]:
            verdict += (f" Timing-Modul ({gpsd['module'] or 'u-blox TIM'}) – ideal für PPS; im Stand "
                        "mit bekannter Position genauer.")
        result.append({
            "tty": name, "dev": f"/dev/{name}", "stable_path": by_id.get(name, ""),
            "host_present": True, "in_container": in_container, "usable": usable,
            "tty_driver": driver, "usb": usb, "gpsd": gpsd, "configured": False,
            "product": product, "interface": interface, "pps_path": pps_path,
            "accuracy": accuracy, "verdict": verdict, "tone": tone,
            "_gps_like": gps_like or bool(gpsd), "_major": _device_major("tty", name),
        })
    if configured_raw.lower() == "auto":
        chosen = next((r for r in result if r["_gps_like"]), result[0] if result else None)
        if chosen:
            chosen["configured"] = True
    elif configured_tty:
        for rec in result:
            if rec["tty"] == configured_tty:
                rec["configured"] = True
    if any(r["_gps_like"] for r in result):
        # Gibt es einen erkannten GPS-Empfänger, verwirrt eine leere Pi-UART (ttyS0 = Mini-UART für
        # Bluetooth/Konsole) als zweite „Empfänger“-Karte nur („PPS über GPIO möglich“). Gelistet bleibt
        # sie, wenn sie eingetragen ist, gpsd sie kennt oder nach GPS aussieht – und ohne anderen
        # Empfänger weiterhin als Hinweis für HAT-Besitzer.
        result = [r for r in result if r["_gps_like"] or r["configured"] or r["gpsd"]]
    order = {"ttyACM": 0, "ttyUSB": 1}
    result.sort(key=lambda r: (not r["configured"], not r["_gps_like"],
                               order.get(r["tty"][:6], 2), r["tty"]))
    return result


# ---------------------------------------------------------------------------
# PPS
# ---------------------------------------------------------------------------

def _pps_kind(name: str, path: str) -> str:
    if path:
        return "ldisc"
    if re.match(r"^ptp\d+$", name):
        return "phc"
    if PPS_GPIO_NAME.match(name):
        return "gpio"
    return "unknown"


def _read_pps_sources() -> list[dict[str, Any]]:
    base = _sys("class", "pps")
    try:
        names = sorted(os.listdir(base), key=lambda n: (len(n), n))
    except OSError:
        return []
    result = []
    for name in names:
        if not re.match(r"^pps\d+$", name):
            continue
        src_name = _read(os.path.join(base, name, "name"))
        path = _read(os.path.join(base, name, "path"))
        result.append({"sysname": name, "dev": f"/dev/{name}", "name": src_name, "path": path,
                       "kind": _pps_kind(src_name, path),
                       "assert_raw": _read(os.path.join(base, name, "assert"))})
    return result


def _evaluate_pulses(a: dict, b: dict) -> tuple[str, float | None]:
    if b["seq"] == 0:
        return "never", None
    dt = b["t"] - a["t"]
    dseq = b["seq"] - a["seq"]
    if dt <= 0 or dseq < 0:
        return "unknown", None
    if dseq == 0:
        return "stale", 0.0
    return "live", round(dseq / dt, 2)


def _sample_pps(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Impulsrate je PPS-Quelle. Höchstens eine Pause von PPS_SAMPLE_SECONDS.

    Die letzte Lesung je Gerät bleibt im Speicher; liegt sie 1–30 s zurück,
    reicht der Vergleich mit ihr und es wird nicht gewartet.
    """
    t1 = _monotonic()
    readings = {}
    for src in sources:
        parsed = parse_pps_assert(src["assert_raw"])
        if parsed:
            readings[src["sysname"]] = {"t": t1, "sec": parsed[0], "nsec": parsed[1], "seq": parsed[2]}
    results: dict[str, dict[str, Any]] = {}
    pending = []
    for name, cur in readings.items():
        prev = _PPS_CACHE.get(name)
        age = t1 - prev["t"] if prev else None
        if cur["seq"] == 0:
            results[name] = {"state": "never", "rate_hz": None}
            _PPS_CACHE[name] = dict(cur, result=results[name])
        elif prev and 1.0 <= age <= PPS_CACHE_MAX_AGE:
            state, rate = _evaluate_pulses(prev, cur)
            results[name] = {"state": state, "rate_hz": rate}
            _PPS_CACHE[name] = dict(cur, result=results[name])
        elif prev and age is not None and 0 <= age < 1.0 and prev.get("result"):
            results[name] = dict(prev["result"])
        else:
            pending.append(name)
    if pending:
        _sleep(PPS_SAMPLE_SECONDS)
        t2 = _monotonic()
        for src in sources:
            if src["sysname"] not in pending:
                continue
            parsed = parse_pps_assert(_read(_sys("class", "pps", src["sysname"], "assert")))
            if not parsed:
                results[src["sysname"]] = {"state": "unknown", "rate_hz": None}
                continue
            cur = {"t": t2, "sec": parsed[0], "nsec": parsed[1], "seq": parsed[2]}
            src["assert_raw"] = f"{parsed[0]}.{parsed[1]:09d}#{parsed[2]}"
            state, rate = _evaluate_pulses(readings[src["sysname"]], cur)
            results[src["sysname"]] = {"state": state, "rate_hz": rate}
            _PPS_CACHE[src["sysname"]] = dict(cur, result=results[src["sysname"]])
    return results


def pps_info(cfg: dict, tracking: dict) -> list[dict[str, Any]]:
    sources = _read_pps_sources()
    samples = _sample_pps(sources)
    configured_dev = str(cfg.get("gps_pps_device") or "").strip()
    configured_name = "" if configured_dev.lower() == "auto" else _resolve_tty(configured_dev)
    synced = bool((tracking or {}).get("synchronised"))
    result = []
    for src in sources:
        local = os.path.join(dev_root(), src["sysname"])
        in_container = os.path.exists(local)
        usable, code = _try_open(local) if in_container else (None, None)
        parsed = parse_pps_assert(src["assert_raw"])
        sample = samples.get(src["sysname"], {"state": "unknown", "rate_hz": None})
        phase = None
        if parsed and synced and sample["state"] == "live":
            nsec = parsed[1]
            phase = round((nsec if nsec < 500_000_000 else nsec - 1_000_000_000) / 1000.0, 1)
        if configured_dev.lower() == "auto":
            configured = src["kind"] in {"gpio", "ldisc"} and not any(
                r["configured"] for r in result)
        else:
            configured = bool(configured_name) and configured_name == src["sysname"]
        result.append({
            "dev": src["dev"], "name": src["name"], "path": src["path"], "kind": src["kind"],
            "host_present": True, "in_container": in_container, "usable": usable,
            "error": _open_error_text(code, src["dev"]),
            "assert": {"sec": parsed[0], "nsec": parsed[1], "seq": parsed[2]} if parsed else None,
            "rate_hz": sample["rate_hz"], "state": sample["state"], "phase_us": phase,
            "configured": configured,
            "_code": code, "_major": _device_major("pps", src["sysname"]),
        })
    return result


# ---------------------------------------------------------------------------
# PTP
# ---------------------------------------------------------------------------

def classify_nic(nic: dict[str, Any], hypervisor: str | None,
                 clock_names: dict[str, str]) -> tuple[str, str, bool]:
    """(nic_class, Hinweis, passthrough). Der Treiber begründet, ethtool entscheidet."""
    driver = nic.get("driver") or ""
    ethtool = bool(nic.get("ethtool"))
    hw = bool(nic.get("ptp_hardware"))
    phc_name = clock_names.get(os.path.basename(nic.get("phc") or ""), "")
    if not nic.get("physical") or nic.get("virtual_nic") or driver in NIC_VIRTUAL:
        cls = "virtual"
        note = (f"Virtuelle Netzwerkkarte ({driver or 'ohne Treiber'}) – keine Hardware-Zeitstempel. "
                "Echtes PTP nur mit einer Karte per PCI-Passthrough.")
    elif driver in {"e1000", "e1000e"} and hypervisor:
        cls = "virtual"
        note = (f"Vom Hypervisor nachgebildete Intel-Karte ({driver}) – keine echten "
                "Hardware-Zeitstempel.")
    elif nic.get("wireless"):
        cls = "none"
        note = "WLAN kann keine PTP-Hardware-Zeitstempel. PTP braucht ein Kabel."
    elif driver == "bcmgenet":
        if phc_name == "bcm_phy_ptp" or hw:
            cls, note = "good", "Compute Module 4: Hardware-Zeitstempel über die PHY (bcm_phy_ptp)."
        else:
            cls, note = "none", ("bcmgenet ohne PTP-fähige PHY (Raspberry Pi 4) – nur "
                                 "Software-Zeitstempel.")
    elif driver in NIC_GOOD:
        if ethtool and not hw:
            cls, note = "limited", (f"Der Treiber {driver} kann PTP, ethtool meldet aber keine "
                                    "Hardware-Zeitstempel (Kernel zu alt oder Funktion aus?).")
        else:
            cls, note = "good", f"{driver}: Hardware-Zeitstempel und PTP-Uhr – gut für PTP."
    elif driver in NIC_IF_ETHTOOL:
        if hw:
            cls, note = "good", f"{driver}: laut ethtool mit Hardware-Zeitstempeln."
        elif ethtool:
            cls, note = "none", f"{driver}: laut ethtool ohne Hardware-Zeitstempel."
        else:
            cls, note = "unknown", f"{driver}: je nach Board mit oder ohne PTP – ethtool fehlt."
    elif driver in NIC_LIMITED:
        if ethtool and not hw:
            cls, note = "none", f"{driver}: laut ethtool ohne Hardware-Zeitstempel."
        else:
            cls, note = "limited", (
                f"{driver} (z. B. Intel I217/I218/I219) hat eine PTP-Uhr, es gibt aber Berichte über "
                "falsche Taktfrequenz und Zeitstempel, die unter Last ausfallen. Funktioniert oft, "
                "für verlässliches PTP besser eine i210/i226.")
    elif driver in NIC_NONE:
        cls, note = "none", f"{driver}: keine Hardware-Zeitstempel – nur Software-PTP."
    elif hw:
        cls, note = "good", f"{driver or 'Karte'}: laut ethtool mit Hardware-Zeitstempeln."
    elif ethtool:
        cls, note = "none", f"{driver or 'Karte'}: laut ethtool ohne Hardware-Zeitstempel."
    else:
        cls, note = "unknown", "ethtool fehlt – Fähigkeiten nicht prüfbar."
    passthrough = cls == "good" and bool(hypervisor)
    if passthrough:
        note += " PCI-Passthrough erkannt – Hardware-PTP möglich."
    return cls, note, passthrough


def ptp_info(platform_: dict) -> dict[str, Any]:
    nics = devices.interfaces()
    base = _sys("class", "ptp")
    try:
        names = sorted((n for n in os.listdir(base) if re.match(r"^ptp\d+$", n)),
                       key=lambda n: int(n[3:]))
    except OSError:
        names = []
    clock_names = {n: _read(os.path.join(base, n, "clock_name")) for n in names}
    phc_to_if = {}
    for nic in nics:
        if nic.get("phc"):
            phc_to_if.setdefault(os.path.basename(nic["phc"]), nic["name"])
    for link in glob.glob(os.path.join(devices.sys_net(), "*", "device", "ptp", "ptp*")):
        phc_to_if.setdefault(os.path.basename(link), link.split(os.sep)[-4])
    clocks = []
    for name in names:
        d = os.path.join(base, name)
        clock_name = clock_names[name]
        low = clock_name.lower()
        iface = phc_to_if.get(name)
        if "kvm" in low or "hyperv" in low or "vmclock" in low or "vmw" in low:
            kind = "vm"
        elif iface:
            kind = "nic"
        else:
            kind = "unknown"
        local = os.path.join(dev_root(), name)
        in_container = os.path.exists(local)
        usable, code = _try_open(local) if in_container else (None, None)
        pps = _read_int(os.path.join(d, "pps_available"))
        clocks.append({
            "dev": f"/dev/{name}", "clock_name": clock_name, "interface": iface,
            "max_adjustment": _read_int(os.path.join(d, "max_adjustment")),
            "n_external_timestamps": _read_int(os.path.join(d, "n_external_timestamps")),
            "n_periodic_outputs": _read_int(os.path.join(d, "n_periodic_outputs")),
            "n_pins": _read_int(os.path.join(d, "n_pins")),
            "pps_available": bool(pps) if pps is not None else None,
            "kind": kind, "in_container": in_container, "usable": usable,
            "error": _open_error_text(code, f"/dev/{name}"),
            "_code": code, "_major": _device_major("ptp", name),
        })
    for nic in nics:
        cls, note, passthrough = classify_nic(nic, platform_["hypervisor"], clock_names)
        nic.update(nic_class=cls, nic_note=note, passthrough=passthrough)
    return {"clocks": clocks, "interfaces": nics}


# ---------------------------------------------------------------------------
# RTC
# ---------------------------------------------------------------------------

def rtc_info() -> dict[str, Any]:
    base = _sys("class", "rtc", "rtc0")
    if not os.path.isdir(base):
        return {"present": False, "name": "", "drift_seconds": None, "hctosys": None}
    since = _read_int(os.path.join(base, "since_epoch"))
    hctosys = _read_int(os.path.join(base, "hctosys"))
    return {
        "present": True, "name": _read(os.path.join(base, "name")),
        "drift_seconds": round(since - _now(), 1) if since is not None else None,
        "hctosys": bool(hctosys) if hctosys is not None else None,
    }


# ---------------------------------------------------------------------------
# Matrix: Was diese Hardware kann
# ---------------------------------------------------------------------------

def _row(key: str, title: str, status: str, text: str, fix: str | None = None,
         accuracy: str | None = None, active: bool = False) -> dict[str, Any]:
    return {"key": key, "title": title, "status": status, "text": text, "fix": fix,
            "accuracy": accuracy, "active": bool(active)}


def _fix_devices(dev: str) -> tuple[str, str]:
    return (f"Im Compose unter „devices:“ die Zeile „- {dev}:{dev}“ einkommentieren (oder ergänzen) "
            "und den Container neu erzeugen (docker compose up -d) – Geräte gibt Docker nur beim "
            "Erzeugen weiter.",
            f"devices:\n  - {dev}:{dev}")


def _fix_cgroup(dev: str, major: int | None, env_name: str | None = None) -> tuple[str, str]:
    num = str(major) if major is not None else "<Major aus /proc/devices>"
    text = (f"{dev} ist im Container sichtbar, aber das Öffnen wird verweigert (EPERM): Für die "
            f"Gerätenummer {num} fehlt die Freigabe. Im Compose unter „device_cgroup_rules:“ die "
            f"Zeile „- \"c {num}:* rwm\"“ ergänzen")
    if env_name and major is not None:
        text += (f" (nutzt deine Compose-Datei dort ${{{env_name}}}, genügt „{env_name}={major}“ "
                 "in der .env)")
    text += f". Alternativ das Gerät einzeln unter „devices:“ eintragen: - {dev}:{dev}."
    return text, f'device_cgroup_rules:\n  - "c {num}:* rwm"'


def _access_problem(item: dict, env_name: str | None = None) -> tuple[str, str] | None:
    """Fehlt ein Gerät im Container oder darf es nicht geöffnet werden? (Text, Fix)."""
    if not item["in_container"]:
        return _fix_devices(item["dev"])
    if item.get("usable") is False and item.get("_code") == "EPERM":
        return _fix_cgroup(item["dev"], item.get("_major"), env_name)
    if item.get("usable") is False and item.get("_code"):
        return (item.get("error") or f"{item['dev']} lässt sich nicht öffnen.", "")
    return None


def _env_fix(**pairs: str) -> str:
    return "environment:\n" + "\n".join(f"  {k}: {v}" for k, v in pairs.items())


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "Impulse"
    if 0.8 <= rate <= 1.2:
        return "1 Impuls/s"
    return f"{rate:g} Impulse/s"


def build_matrix(cfg: dict, rep: dict, ctx: dict) -> tuple[list[dict], list[str]]:
    plat, perms = rep["platform"], rep["permissions"]
    receivers, pps_list = rep["gps"]["receivers"], rep["pps"]
    nics, clocks = rep["ptp"]["interfaces"], rep["ptp"]["clocks"]
    rtc = rep["rtc"]
    gps_status = ctx.get("gps_status") or {}
    tracking = ctx.get("tracking") or {}
    chronyd = ctx.get("chronyd") or {}
    gpsd_pps = rep["gps"]["gpsd_pps"]
    desktop = plat["docker_desktop"] or plat["wsl"]
    host_net = perms["network"] == "host"
    is_pi = bool(plat["board"]["family"])
    gps_on = bool(cfg.get("gps_enable"))
    ptp_on = bool(cfg.get("ptp_enable"))
    ptp_mode = cfg.get("ptp_mode") or "auto"
    warnings: list[str] = []
    rows: list[dict] = []

    # --- NTP-Server ----------------------------------------------------------
    if chronyd.get("pid") or tracking:
        if perms["network"] == "bridge":
            rows.append(_row("ntp_server", "NTP-Server", "ok",
                             "Liefert Zeit an Clients auf Port 123/udp. Im Bridge-Netz erscheinen die "
                             "Clients wegen NAT mit der Docker-Adresse; für echte Client-IPs "
                             "„network_mode: host“.", "network_mode: host", active=True))
        else:
            rows.append(_row("ntp_server", "NTP-Server", "ok",
                             "Liefert Zeit an Clients auf Port 123/udp.", active=True))
    else:
        rows.append(_row("ntp_server", "NTP-Server", "unknown",
                         "chronyd antwortet gerade nicht – das Container-Log nennt den Grund.",
                         active=True))

    # --- Uhr stellen ---------------------------------------------------------
    disabled = str(os.environ.get("DISABLE_CLOCK_CONTROL", "")).strip().lower() in {
        "1", "true", "yes", "on", "ja"}
    if desktop:
        rows.append(_row("clock_control", "Uhr stellen", "limited",
                         "Docker Desktop/WSL2: chrony stellt nur die Uhr der Docker-VM, nicht die von "
                         "Windows/macOS. Als Zeitserver fürs LAN taugt das nur eingeschränkt.",
                         active=True))
    elif not perms["sys_time"]:
        rows.append(_row("clock_control", "Uhr stellen", "change",
                         "Es fehlt das Recht SYS_TIME – chrony liefert dann nur aus und stellt die Uhr "
                         "nicht. Im Compose unter „cap_add:“ die Zeile „- SYS_TIME“ ergänzen.",
                         "cap_add:\n  - SYS_TIME", active=True))
    elif disabled:
        rows.append(_row("clock_control", "Uhr stellen", "limited",
                         "Die Uhrensteuerung ist mit DISABLE_CLOCK_CONTROL abgeschaltet: chrony liefert "
                         "die Zeit des Hosts aus, ohne sie zu korrigieren.", active=True))
    elif ptp_on and cfg.get("phc2sys_enable") and ptp_mode == "slave":
        rows.append(_row("clock_control", "Uhr stellen", "ok",
                         "phc2sys stellt die Systemuhr nach der PTP-Uhr (PTP-Slave), chrony läuft mit -x "
                         "und liefert nur aus.", active=True))
    elif chronyd.get("clock_control") is False:
        rows.append(_row("clock_control", "Uhr stellen", "limited",
                         "SYS_TIME ist vorhanden, chronyd läuft aber mit -x und stellt die Uhr nicht "
                         "(Uhrensteuerung abgeschaltet oder phc2sys regelt).", active=True))
    else:
        text = "chrony darf die Systemuhr stellen (SYS_TIME vorhanden)."
        if ptp_on and cfg.get("phc2sys_enable") and ptp_mode == "master":
            text += " phc2sys überträgt sie als Grandmaster auf die PTP-Uhr der Karte."
        rows.append(_row("clock_control", "Uhr stellen", "ok", text, active=True))

    # --- NTS -----------------------------------------------------------------
    nts_active = any(s.get("nts") for s in cfg.get("ntp_sources") or []) or bool(cfg.get("nts_server_enable"))
    synced = bool(tracking.get("synchronised"))
    if cfg.get("nts_server_enable") and not all(
            os.access(str(cfg.get(k) or ""), os.R_OK) for k in ("nts_server_cert", "nts_server_key")):
        cert, key = cfg.get("nts_server_cert") or "", cfg.get("nts_server_key") or ""
        cert_dir = os.path.dirname(cert) or "/config"
        if cert_dir == "/config":
            where = "Lege nts.crt und nts.key in ./config und hänge den Ordner ein."
            mount = "volumes:\n  - ./config:/config:ro"
        else:
            where = (f"Hänge den Ordner mit Zertifikat und Schlüssel lesbar als {cert_dir} in den "
                     "Container ein (Pfad auf dem Host anpassen).")
            mount = f"volumes:\n  - <Ordner auf dem Host>:{cert_dir}:ro"
        rows.append(_row("nts", "NTS", "change",
                         f"NTS-Server ist eingeschaltet, aber Zertifikat ({cert}) oder Schlüssel ({key}) "
                         f"sind im Container nicht lesbar. {where}", mount, active=nts_active))
        rows[-1]["cause"] = "nts_server_files"
    elif not rtc["present"] and not cfg.get("nts_nocerttimecheck"):
        rows.append(_row("nts", "NTS", "change",
                         "Ohne Echtzeituhr startet das Gerät mit falscher Zeit; NTS scheitert dann an der "
                         "Zertifikatsprüfung. „Zertifikatszeit beim Start nicht prüfen“ einschalten "
                         "(NTS_NOCERTTIMECHECK=true) oder RTC-Modul/Akku nachrüsten.",
                         _env_fix(NTS_NOCERTTIMECHECK='"true"'), active=nts_active))
    elif not rtc["present"]:
        rows.append(_row("nts", "NTS", "ok",
                         "NTS als Client geht. Keine Echtzeituhr – „Zertifikatszeit beim Start nicht "
                         "prüfen“ bleibt an (so eingestellt).", active=nts_active))
    elif synced and rtc["drift_seconds"] is not None and abs(rtc["drift_seconds"]) > 120:
        hint = " (Pi 5: Akku an J5 fehlt?)" if plat["board"]["family"] in {"pi5", "cm5"} else ""
        rows.append(_row("nts", "NTS", "limited",
                         f"Die Echtzeituhr ({rtc['name'] or 'rtc0'}) geht um {abs(rtc['drift_seconds']):.0f} s "
                         f"falsch{hint}. Nach einem Neustart ohne Netz stimmt die Zeit dann nicht, und NTS "
                         "braucht „Zertifikatszeit beim Start nicht prüfen“.", active=nts_active))
    else:
        rows.append(_row("nts", "NTS", "ok",
                         f"NTS als Client geht; die Echtzeituhr ({rtc['name'] or 'rtc0'}) hält die Zeit "
                         "auch über einen Neustart.", active=nts_active))

    # --- GPS (NMEA) ----------------------------------------------------------
    main = next((r for r in receivers if r["configured"] and r["_gps_like"]), None) \
        or next((r for r in receivers if r["_gps_like"]), None) \
        or next((r for r in receivers if r["configured"]), None)
    title_usb = "USB-GPS (Millisekunden)"
    if main is None:
        text = "Kein GPS-Empfänger angeschlossen."
        if desktop:
            text += " Unter Docker Desktop/WSL2 kommen USB-Geräte ohnehin nicht im Container an."
        elif receivers:
            text = ("Kein GPS-Empfänger erkannt. Serielle Ports sind da ("
                    + ", ".join(r["dev"] for r in receivers)
                    + ") – ob ein Empfänger dranhängt, zeigt gpsd nach dem Einschalten von GPS.")
        rows.append(_row("gps_usb", title_usb, "no" if not receivers else "unknown", text,
                         _env_fix(GPS_ENABLE='"true"', GPS_DEVICE=receivers[0]["dev"]) if receivers else None,
                         active=gps_on))
    else:
        label = f"{main['product']} an {main['dev']}"
        problem = _access_problem(main)
        if problem:
            text, fix = problem
            rows.append(_row("gps_usb", title_usb, "change",
                             f"Empfänger am Host erkannt ({label}), aber nicht nutzbar im Container. {text}",
                             fix or None, active=gps_on))
        elif main["usable"] is False and perms["dev_mounted"] and not perms["privileged"] \
                and not (main["gpsd"] or {}).get("activated"):
            major = main["_major"] if main["_major"] is not None else "<Major>"
            rows.append(_row("gps_usb", title_usb, "change",
                             f"gpsd kann {main['dev']} nicht öffnen. Zwei mögliche Gründe: Der Port ist am "
                             "Host belegt (gpsd oder ModemManager: sudo systemctl disable --now gpsd.socket "
                             "gpsd ModemManager) – oder, weil /dev des Hosts eingehängt ist, fehlt die "
                             f"Freigabe der Gerätenummer: im Compose unter „device_cgroup_rules:“ die Zeile "
                             f"„- \"c {major}:* rwm\"“ ergänzen.",
                             f'device_cgroup_rules:\n  - "c {major}:* rwm"', active=gps_on))
        elif not gps_on:
            rows.append(_row("gps_usb", title_usb, "change",
                             f"Empfänger {label} ist im Container. GPS in den Einstellungen einschalten "
                             "(oder per Umgebungsvariable).",
                             _env_fix(GPS_ENABLE='"true"', GPS_DEVICE=main["stable_path"] or main["dev"]),
                             accuracy="1–10 ms", active=False))
        elif not main["configured"]:
            rows.append(_row("gps_usb", title_usb, "change",
                             f"In den Einstellungen steht „{cfg.get('gps_device')}“, der Empfänger hängt "
                             f"aber an {main['dev']}. GPS-Gerät umstellen.",
                             _env_fix(GPS_DEVICE=main["stable_path"] or main["dev"]),
                             accuracy="1–10 ms", active=True))
        elif not gps_status.get("running"):
            rows.append(_row("gps_usb", title_usb, "no",
                             "gpsd antwortet nicht – das Container-Log nennt den Grund (Gerät belegt, "
                             "falscher Pfad?).", active=True))
        elif main["gpsd"] is not None and not main["gpsd"]["activated"]:
            rows.append(_row("gps_usb", title_usb, "no",
                             f"gpsd kann {main['dev']} nicht öffnen (belegt durch gpsd oder ModemManager am "
                             "Host?). Am Host: sudo systemctl disable --now gpsd.socket gpsd ModemManager",
                             active=True))
        else:
            rows.append(_row("gps_usb", title_usb, "ok",
                             f"Empfänger {label} ({main['interface']}) liefert Zeit über NMEA – "
                             "Genauigkeit 1–10 ms nach Kalibrierung (GPS-Seite → „GPS kalibrieren“).",
                             accuracy="1–10 ms", active=True))

    # --- GPS + PPS -----------------------------------------------------------
    title_pps = "GPS + PPS (Mikrosekunden)"
    pps_active = gps_on and bool(cfg.get("gps_pps_device") or cfg.get("gps_pps_shm"))
    # PPS-Leitungsdisziplin an einem USB-CDC-Gerät (ttyACM): legt gpsd selbst an, liefert nie Impulse.
    acm_ldisc = [p for p in pps_list if p["kind"] == "ldisc"
                 and os.path.basename(p.get("path") or "").startswith("ttyACM")]
    kernel_pps = [p for p in pps_list if p["kind"] in {"gpio", "ldisc"} and p not in acm_ldisc]
    kernel_pps.sort(key=lambda p: (not p["configured"], p["state"] != "live", p["dev"]))
    src = kernel_pps[0] if kernel_pps else None
    dcd_usb = next((r for r in receivers if r["pps_path"] == "dcd_usb"), None)
    uart_dcd = next((r for r in receivers if r["pps_path"] in {"dcd_uart", "unknown"}
                     and r["tty"] not in {os.path.basename(p["path"]) for p in kernel_pps}), None)
    gpio_overlay = ("# NUR mit einem GPS-Modul/HAT, dessen PPS-Pin an GPIO18 angeschlossen ist –\n"
                    "# nicht mit einem USB-Stick. /dev/pps0 entsteht erst durch dieses Overlay;\n"
                    "# vorher lässt „devices:“ den Containerstart scheitern. Das Overlay lädt beim\n"
                    "# Booten zuerst und bekommt /dev/pps0; ein /dev/pps*, das gpsd an einem USB-\n"
                    "# Empfänger anlegt, rückt dann eine Nummer weiter und bleibt ungenutzt.\n"
                    "# /boot/firmware/config.txt (am Host), danach neu starten:\n"
                    "dtoverlay=pps-gpio,gpiopin=18\n\n"
                    "# im Compose:\ndevices:\n  - /dev/pps0:/dev/pps0\n"
                    "environment:\n  GPS_PPS_DEVICE: /dev/pps0")
    if src:
        how = "GPIO" if src["kind"] == "gpio" else f"DCD ({src['path']})"
        acc = "~1 µs" if src["kind"] == "gpio" else "~1–5 µs"
        problem = _access_problem(src, "PPS_MAJOR")
        if problem and src["state"] == "never":
            # Am Host noch nie ein Impuls: Einbinden in den Container brächte nichts.
            pin = " (GPIO18?)" if src["kind"] == "gpio" else ""
            rows.append(_row("gps_pps", title_pps, "no",
                             f"{src['dev']} ({src['name']}) gibt es am Host, er hat dort aber noch nie einen "
                             f"Impuls gezählt – Einbinden in den Container bringt deshalb nichts. Erst "
                             f"Fix abwarten, Kabel/Pin prüfen{pin}.", None, acc, pps_active))
        elif problem:
            rows.append(_row("gps_pps", title_pps, "change",
                             f"PPS-Quelle {src['dev']} ({src['name']}) am Host erkannt"
                             + (f", {_fmt_rate(src['rate_hz'])}" if src["state"] == "live" else "")
                             + f". {problem[0]}", problem[1] or None, acc, pps_active))
        elif src["state"] in {"stale", "never"}:
            pin = " (GPIO18?)" if src["kind"] == "gpio" else ""
            what = "noch nie einen Impuls gesehen" if src["state"] == "never" else "keine Impulse mehr"
            rows.append(_row("gps_pps", title_pps, "no",
                             f"{src['dev']} vorhanden, aber {what} – Fix abwarten, Kabel/Pin prüfen{pin}.",
                             None, acc, pps_active))
        elif not src["configured"]:
            rows.append(_row("gps_pps", title_pps, "change",
                             f"{src['dev']} liefert {_fmt_rate(src['rate_hz'])} über {how}, ist aber nicht "
                             f"eingetragen. In den Einstellungen „PPS-Gerät“ auf {src['dev']} setzen.",
                             _env_fix(GPS_PPS_DEVICE=src["dev"]), acc, pps_active))
        elif not gps_on:
            rows.append(_row("gps_pps", title_pps, "change",
                             f"{src['dev']} liefert {_fmt_rate(src['rate_hz'])}, GPS ist aber aus. PPS "
                             "braucht GPS (NMEA) für die volle Sekunde – GPS einschalten.",
                             _env_fix(GPS_ENABLE='"true"'), acc, False))
        elif src["state"] == "live":
            rows.append(_row("gps_pps", title_pps, "ok",
                             f"PPS aktiv über {how} ({src['dev']}, {_fmt_rate(src['rate_hz'])}) – "
                             f"Genauigkeit {acc}.", None, acc, pps_active))
        else:
            rows.append(_row("gps_pps", title_pps, "unknown",
                             f"{src['dev']} ist eingetragen, die Impulse ließen sich nicht lesen.",
                             None, acc, pps_active))
    elif dcd_usb:
        if gpsd_pps.get("seen"):
            fix = None if cfg.get("gps_pps_shm") else _env_fix(GPS_PPS_SHM='"true"')
            rows.append(_row("gps_pps", title_pps, "limited",
                             "PPS über USB-Seriell (DCD) erkannt: ~1 ms – besser als NMEA, aber kein µs."
                             + ("" if cfg.get("gps_pps_shm") else " „PPS über gpsd“ einschalten."),
                             fix, "~1 ms", pps_active))
        elif not gps_on:
            rows.append(_row("gps_pps", title_pps, "unknown",
                             f"{dcd_usb['product']} hängt an einem USB-Seriell-Adapter: PPS ginge über DCD "
                             "(~1 ms), wenn das Board den Impuls dorthin legt. Das zeigt sich erst mit "
                             "eingeschaltetem GPS.", None, "~1 ms", False))
        else:
            rows.append(_row("gps_pps", title_pps, "no",
                             f"{dcd_usb['product']} über USB-Seriell-Adapter: gpsd hat keinen PPS auf der "
                             "DCD-Leitung gesehen – das Board führt den Impuls wohl nicht heraus. Für µs: "
                             + ("Modul mit PPS an GPIO." if is_pi else "Empfänger mit PPS an DCD einer "
                                "echten seriellen Schnittstelle oder PCIe-Timecard."),
                             gpio_overlay if is_pi else None, None, pps_active))
    elif uart_dcd and not is_pi and gpsd_pps.get("seen"):
        fix = None if cfg.get("gps_pps_shm") else _env_fix(GPS_PPS_SHM='"true"')
        rows.append(_row("gps_pps", title_pps, "ok" if cfg.get("gps_pps_shm") else "change",
                         f"gpsd sieht PPS an der seriellen Schnittstelle {uart_dcd['dev']} (DCD) → "
                         "~5–10 µs." + ("" if cfg.get("gps_pps_shm") else " „PPS über gpsd“ einschalten."),
                         fix, "~5–10 µs", pps_active))
    elif is_pi:
        on_uart = next((r for r in receivers if r["pps_path"] == "possible_gpio"
                        and (r["configured"] or r["_gps_like"])), None)
        usb_only = main is not None and main["pps_path"] == "none"
        if on_uart and not usb_only:
            rows.append(_row("gps_pps", title_pps, "change",
                             "Empfänger am Pi-UART, aber keine PPS-Quelle. Hat dein HAT/Modul einen PPS-Pin "
                             "(meist GPIO18 oder GPIO4): in /boot/firmware/config.txt "
                             "„dtoverlay=pps-gpio,gpiopin=18“ eintragen, neu starten, dann "
                             "/dev/pps0 in den Container geben.", gpio_overlay, "~1 µs", pps_active))
        elif usb_only:
            rows.append(_row("gps_pps", title_pps, "no",
                             f"Dein Empfänger ({main['product']}, USB-Modem-Gerät) kann keinen PPS an den "
                             "Rechner liefern. Für µs: Modul mit PPS-Ausgang an GPIO18 "
                             "(z. B. GPS-HAT), dann „dtoverlay=pps-gpio,gpiopin=18“.",
                             gpio_overlay, None, pps_active))
        else:
            rows.append(_row("gps_pps", title_pps, "no",
                             "Keine PPS-Quelle. Am Raspberry Pi geht µs mit einem GPS-Modul oder HAT mit "
                             "PPS-Ausgang an GPIO18 und „dtoverlay=pps-gpio,gpiopin=18“.",
                             gpio_overlay, None, pps_active))
    elif main is not None and main["pps_path"] == "none":
        rows.append(_row("gps_pps", title_pps, "no",
                         f"Dein Empfänger ({main['product']}, USB-Modem-Gerät) kann keinen PPS an den "
                         "Rechner liefern. Für µs: Modul mit PPS-Ausgang an der DCD-Leitung einer echten "
                         "seriellen Schnittstelle oder eine PCIe-Timecard.", None, None, pps_active))
    elif uart_dcd:
        rows.append(_row("gps_pps", title_pps, "unknown" if not gps_on else "no",
                         f"Serielle Schnittstelle {uart_dcd['dev']}: PPS ginge über die DCD-Leitung "
                         "(„PPS über gpsd“), gpsd hat aber "
                         + ("noch nicht geprüft (GPS ist aus)." if not gps_on else "keinen Impuls gesehen."),
                         None, "~5–10 µs", pps_active))
    else:
        rows.append(_row("gps_pps", title_pps, "no",
                         "Kein PPS-Eingang. Möglich mit RS-232-Karte (DCD) oder einer PCIe-Timecard.",
                         None, None, pps_active))
    gps_pps_row = rows[-1]

    if acm_ldisc:
        names = ", ".join(f"{p['dev']} ({p['name']})" for p in acm_ldisc)
        ttys = ", ".join(sorted({p["path"] for p in acm_ldisc}))
        for row in rows:
            if row["key"] == "gps_pps":
                row["text"] += (f" Hinweis: {names} hat gpsd selbst an {ttys} angelegt. Ein USB-Empfänger wie "
                                "dieser liefert darüber nie einen Impuls – diese Zeile also nicht unter "
                                "„devices:“ eintragen.")
                break

    # --- PTP mit Hardware-Zeitstempeln ---------------------------------------
    title_hw = "PTP mit Hardware-Zeitstempeln"
    hw_active = ptp_on and cfg.get("ptp_time_stamping", "hardware") == "hardware"
    cap_fix = "cap_add:\n  - NET_ADMIN\n  - NET_RAW"
    good = [n for n in nics if n.get("ptp_hardware") or n.get("nic_class") == "good"]
    good.sort(key=lambda n: (n["name"] != cfg.get("ptp_interface"), n.get("nic_class") != "good",
                             not n.get("ptp_hardware"), n["name"]))
    chosen_if = next((n for n in nics if n["name"] == cfg.get("ptp_interface")), None)
    ptp_note = ""
    if any((c["n_external_timestamps"] or 0) > 0 or (c["n_pins"] or 0) > 0 for c in clocks
           if c["kind"] == "nic"):
        ptp_note = (" Profi-Option: PPS direkt an den SDP-Pin der Karte (ts2phc) – wird von ntp-gui "
                    "nicht unterstützt.")
    if desktop:
        rows.append(_row("ptp_hw", title_hw, "no",
                         "Docker Desktop/WSL2: Der Container sieht keine echte Netzwerkkarte.",
                         active=hw_active))
    elif perms["network"] == "bridge":
        rows.append(_row("ptp_hw", title_hw, "change",
                         "Der Container läuft im Bridge-Netz und sieht nur ein virtuelles Interface. PTP "
                         "braucht „network_mode: host“ (Multicast und die echte Karte).",
                         "network_mode: host", active=hw_active))
    elif not good:
        physical = [n for n in nics if n.get("nic_class") != "virtual"]
        if not nics:
            rows.append(_row("ptp_hw", title_hw, "unknown", "Keine Netzwerkkarte sichtbar.",
                             active=hw_active))
        elif not physical:
            names = ", ".join(f"{n['name']}: {n.get('driver') or 'virtuell'}" for n in nics)
            rows.append(_row("ptp_hw", title_hw, "no",
                             f"Virtuelle Netzwerkkarte ({names}) – Hardware-PTP nur per PCI-Passthrough "
                             "einer echten Karte in die VM.", active=hw_active))
        elif all(n.get("nic_class") == "unknown" for n in physical):
            rows.append(_row("ptp_hw", title_hw, "unknown",
                             "ethtool fehlt – ob die Karte Hardware-Zeitstempel kann, lässt sich nicht "
                             "prüfen.", active=hw_active))
        else:
            names = ", ".join(f"{n['name']}: {n.get('driver') or '?'}" for n in physical)
            rows.append(_row("ptp_hw", title_hw, "no",
                             f"Keine Netzwerkkarte mit Hardware-Zeitstempeln ({names}). Geeignet: "
                             f"{GOOD_NICS_TEXT}.", active=hw_active))
    else:
        nic = good[0]
        phc = next((c for c in clocks if c["dev"] == nic.get("phc")), None)
        label = f"{nic['name']} ({nic.get('driver') or '?'})"
        if not perms["net_admin"]:
            rows.append(_row("ptp_hw", title_hw, "change",
                             f"{label} kann Hardware-Zeitstempel, aber es fehlt NET_ADMIN. Im Compose unter "
                             "„cap_add:“ die Zeilen „- NET_ADMIN“ und „- NET_RAW“ einkommentieren.",
                             cap_fix, "< 1 µs", hw_active))
        elif phc and _access_problem(phc, "PTP_MAJOR"):
            text, fix = _access_problem(phc, "PTP_MAJOR")  # type: ignore[misc]
            rows.append(_row("ptp_hw", title_hw, "change",
                             f"{label} hat die PTP-Uhr {phc['dev']}. {text}", fix or None, "< 1 µs",
                             hw_active))
        elif not phc and nic.get("phc"):
            text, fix = _fix_devices(nic["phc"])
            rows.append(_row("ptp_hw", title_hw, "change", f"{label}: {text}", fix, "< 1 µs", hw_active))
        elif chosen_if is not None and chosen_if is not nic and ptp_on:
            rows.append(_row("ptp_hw", title_hw, "change",
                             f"In den Einstellungen ist {chosen_if['name']} gewählt, das kann keine "
                             f"Hardware-Zeitstempel. {label} kann es – Interface umstellen.",
                             _env_fix(PTP_INTERFACE=nic["name"]), "< 1 µs", hw_active))
        elif nic.get("nic_class") == "limited":
            rows.append(_row("ptp_hw", title_hw, "limited", f"{label}: {nic.get('nic_note')}{ptp_note}",
                             None, "~1 µs", hw_active))
        else:
            extra = " (PCI-Passthrough)" if nic.get("passthrough") else ""
            clock_text = f"die PTP-Uhr {nic['phc']}" if nic.get("phc") else "eine PTP-Uhr"
            rows.append(_row("ptp_hw", title_hw, "ok",
                             f"{label}{extra} hat Hardware-Zeitstempel und {clock_text} – "
                             f"Genauigkeit unter 1 µs (je nach Switch).{ptp_note}",
                             None if (not ptp_on or chosen_if is nic) else _env_fix(PTP_INTERFACE=nic["name"]),
                             "< 1 µs", hw_active))
    hw_row = rows[-1]

    # --- PTP mit Software-Zeitstempeln ---------------------------------------
    sw_active = ptp_on and cfg.get("ptp_time_stamping") == "software"
    sw_nics = [n for n in nics if n.get("software") or not n.get("ethtool")]
    if desktop:
        rows.append(_row("ptp_sw", "PTP mit Software-Zeitstempeln", "no",
                         "Docker Desktop/WSL2: kein Zugriff auf das echte Netz.", active=sw_active))
    elif perms["network"] == "bridge":
        rows.append(_row("ptp_sw", "PTP mit Software-Zeitstempeln", "change",
                         "PTP braucht „network_mode: host“ – im Bridge-Netz kommt Multicast nicht an.",
                         "network_mode: host", active=sw_active))
    elif sw_nics:
        rows.append(_row("ptp_sw", "PTP mit Software-Zeitstempeln", "ok",
                         f"Geht auf {', '.join(n['name'] for n in sw_nics)}, aber nicht genauer als gutes "
                         "NTP (µs bis ms).", None, "10 µs – 1 ms", sw_active))
    else:
        rows.append(_row("ptp_sw", "PTP mit Software-Zeitstempeln", "unknown",
                         "Keine passende Netzwerkkarte sichtbar.", active=sw_active))
    sw_row = rows[-1]

    # --- PTP → NTP -----------------------------------------------------------
    bridge_active = ptp_on and (bool(cfg.get("phc_refclock")) or ptp_mode == "slave")
    title_bridge = "PTP→NTP-Brücke (Slave, PHC als chrony-Quelle)"
    if hw_row["status"] in {"ok", "limited"}:
        nic = good[0]
        rows.append(_row("ptp_to_ntp", title_bridge, "ok",
                         f"Geht: ptp4l als Slave auf {nic['name']}, chrony nutzt {nic.get('phc')} als "
                         "Referenzuhr und verteilt die PTP-Zeit per NTP an Geräte ohne PTP.",
                         _env_fix(PTP_ENABLE='"true"', PTP_MODE="slave", PTP_INTERFACE=nic["name"],
                                  PHC_REFCLOCK=nic.get("phc") or "/dev/ptp0"),
                         hw_row["accuracy"], bridge_active))
    elif hw_row["status"] == "change":
        rows.append(_row("ptp_to_ntp", title_bridge, "change",
                         "Geht, sobald „PTP mit Hardware-Zeitstempeln“ eingerichtet ist (siehe dort).",
                         hw_row["fix"], "< 1 µs", bridge_active))
    elif sw_row["status"] == "ok":
        rows.append(_row("ptp_to_ntp", title_bridge, "limited",
                         "Ohne PTP-Hardwareuhr gibt es kein /dev/ptp für chrony; ptp4l müsste die "
                         "Systemuhr direkt stellen (phc2sys entfällt) – nicht genauer als NTP.",
                         None, "10 µs – 1 ms", bridge_active))
    else:
        rows.append(_row("ptp_to_ntp", title_bridge, "no",
                         "Geht nicht: weder Hardware- noch Software-PTP ist hier möglich (siehe oben).",
                         active=bridge_active))

    # --- GPS → PTP -----------------------------------------------------------
    gm_active = ptp_on and gps_on and ptp_mode in {"master", "auto"}
    title_gm = "GPS→PTP-Grandmaster"
    gm_fix = _env_fix(GPS_ENABLE='"true"', PTP_ENABLE='"true"', PTP_MODE="master",
                      PTP_INTERFACE=good[0]["name"] if good else "eth0", PHC2SYS_ENABLE='"true"')
    gps_ok = rows[[r["key"] for r in rows].index("gps_usb")]
    if hw_row["status"] in {"ok", "limited"}:
        if gps_pps_row["status"] == "ok":
            rows.append(_row("gps_to_ptp", title_gm, "ok",
                             "Geht: chrony stellt die Systemuhr per GPS+PPS, phc2sys (-a -rr) überträgt sie "
                             "auf die PTP-Uhr der Karte, ptp4l verteilt sie. Clock Class 6 erst nach "
                             f"stabilem PPS-Lock setzen.{ptp_note}", gm_fix, gps_pps_row["accuracy"],
                             gm_active))
        elif gps_pps_row["status"] == "change":
            rows.append(_row("gps_to_ptp", title_gm, "change",
                             "Geht, sobald „GPS + PPS“ eingerichtet ist (siehe dort). Danach: PTP als "
                             f"Grandmaster mit phc2sys.{ptp_note}", gps_pps_row["fix"], "~1 µs", gm_active))
        elif gps_pps_row["status"] == "limited":
            rows.append(_row("gps_to_ptp", title_gm, "limited",
                             "Möglich, aber PPS kommt nur über USB-Seriell (~1 ms) – PTP verteilt dann eine "
                             f"auf etwa 1 ms genaue Zeit.{ptp_note}", gm_fix, "~1 ms", gm_active))
        elif gps_ok["status"] in {"ok", "change"} and main is not None:
            rows.append(_row("gps_to_ptp", title_gm, "limited",
                             "Technisch möglich, aber wenig sinnvoll: Ohne PPS ist die GPS-Zeit nur auf "
                             "Millisekunden genau, PTP würde sie nanosekundengenau verteilen. Für einen "
                             f"echten Grandmaster braucht es GPS mit PPS.{ptp_note}",
                             None, "1–10 ms", gm_active))
        else:
            rows.append(_row("gps_to_ptp", title_gm, "no",
                             "Kein GPS-Empfänger mit PPS – siehe „GPS + PPS“. Ohne GPS verteilt ein "
                             f"Grandmaster nur die NTP-Zeit (Clock Class 248).{ptp_note}",
                             None, None, gm_active))
    elif hw_row["status"] == "change":
        rows.append(_row("gps_to_ptp", title_gm, "change",
                         "Zuerst „PTP mit Hardware-Zeitstempeln“ einrichten (siehe dort), dann GPS mit PPS.",
                         hw_row["fix"], None, gm_active))
    else:
        rows.append(_row("gps_to_ptp", title_gm, "no",
                         "Geht nicht: Es fehlt eine Netzwerkkarte mit Hardware-Zeitstempeln (siehe „PTP "
                         "mit Hardware-Zeitstempeln“).", None, None, gm_active))

    # --- Warnungen -----------------------------------------------------------
    if perms["privileged"]:
        warnings.append("Der Container läuft privilegiert: gut für den ersten Hardware-Check, für den "
                        "Dauerbetrieb besser gezielt cap_add/devices verwenden.")
    if desktop:
        warnings.append("Docker Desktop/WSL2 erkannt: USB, PPS und PTP sind dort praktisch nicht nutzbar.")
    if nics and not any(n.get("ethtool") for n in nics):
        warnings.append("ethtool fehlt – Hardware-Zeitstempel der Netzwerkkarten sind nicht prüfbar.")
    if synced and rtc["present"] and rtc["drift_seconds"] is not None and abs(rtc["drift_seconds"]) > 120:
        warnings.append(f"Die Echtzeituhr weicht um {abs(rtc['drift_seconds']):.0f} s ab.")
    if ptp_on and cfg.get("ptp_clock_class") == 6 and gps_pps_row["status"] != "ok":
        warnings.append("PTP Clock Class 6 („an GPS gekoppelt“) ist gesetzt, aber GPS+PPS läuft nicht – "
                        "Clients vertrauen dann einer ungenauen Zeit. 248 setzen, bis PPS stabil ist.")
    if gps_on and main is not None and main["tty_driver"] == "ftdi_sio" and gpsd_pps.get("seen"):
        warnings.append("FTDI-Adapter: Der latency_timer (Standard 16 ms) kann PPS über DCD verzögern; "
                        "am Host auf 1 setzen (/sys/bus/usb-serial/devices/<tty>/latency_timer).")
    return rows, warnings


# ---------------------------------------------------------------------------
# Zusammenbau, Cache, Hinweise
# ---------------------------------------------------------------------------

def _chronyd() -> dict[str, Any]:
    base = proc_root()
    try:
        entries = os.listdir(base)
    except OSError:
        return {}
    for entry in entries:
        if not entry.isdigit():
            continue
        if _read(os.path.join(base, entry, "comm")) != "chronyd":
            continue
        try:
            with open(os.path.join(base, entry, "cmdline"), "rb") as handle:
                args = handle.read().split(b"\0")
        except OSError:
            continue
        return {"pid": int(entry), "clock_control": b"-x" not in args}
    return {}


def _gps_status(cfg: dict) -> dict[str, Any]:
    if not cfg.get("gps_enable"):
        return {}
    try:
        import gps
        return gps.status()
    except Exception:  # noqa: BLE001 – der Check darf nie an gpsd scheitern
        return {}


def _tracking() -> dict[str, Any]:
    try:
        import chrony
        return chrony.tracking() or {}
    except Exception:  # noqa: BLE001
        return {}


def _probe_gpsd(timeout: float) -> dict[str, Any] | None:
    try:
        import gps
        return gps.probe_pps(timeout)
    except Exception:  # noqa: BLE001
        return None


def _temperature(cfg: dict) -> dict[str, Any]:
    """Temperatursensoren für die Seite „Uhrqualität“ (1.4: nur messen). Wirft nie."""
    try:
        import thermal
        thermal.MONITOR.sensors(refresh=True)
        return thermal.MONITOR.status(cfg.get("temp_sensor"))
    except Exception as exc:  # pragma: no cover – sysfs seltsam
        return {"available": False, "reason": "error", "error": str(exc), "candidates": []}


def build_report(cfg: dict, ctx: dict) -> dict[str, Any]:
    """Baut den Bericht. ctx: gps_status, tracking, chronyd, gpsd_probe (oder None)."""
    perms = permissions_info()
    plat = platform_info(perms["network"], perms["privileged"])
    # Ohne Container gibt es kein "/dev vom Host eingehängt": /dev/serial/by-id und
    # ein devtmpfs gibt es auf jedem Host – sonst folgen falsche cgroup-Ratschläge.
    perms["dev_mounted"] = bool(perms["dev_mounted"] and plat["container"])
    pps = pps_info(cfg, ctx.get("tracking") or {})
    probe = ctx.get("gpsd_probe")
    gps_status = dict(ctx.get("gps_status") or {})
    if not gps_status.get("devices") and probe and probe.get("devices"):
        gps_status["devices"] = probe["devices"]
    receivers = receivers_info(cfg, plat, perms, pps, gps_status, probe)
    majors = parse_proc_devices(_read(_proc("devices")))
    rep: dict[str, Any] = {
        "generated": _now(),
        "platform": plat,
        "permissions": perms,
        "gps": {"receivers": receivers,
                "gpsd_pps": {"seen": bool(probe and probe.get("seen")),
                             "toff_latency_ms": (probe or {}).get("toff_latency_ms")}},
        "pps": pps,
        "ptp": ptp_info(plat),
        "rtc": rtc_info(),
        "temperature": _temperature(cfg),
        "majors": {"pps": majors.get("pps"), "ptp": majors.get("ptp")},
    }
    rep["matrix"], rep["warnings"] = build_matrix(cfg, rep, ctx)
    for group in (rep["gps"]["receivers"], rep["pps"], rep["ptp"]["clocks"]):
        for item in group:
            for key in [k for k in item if k.startswith("_")]:
                del item[key]
    return rep


def report(cfg: dict, refresh: bool = False) -> dict[str, Any]:
    global _REPORT, _REPORT_TIME, _GPSD_PROBE, _GPSD_PROBE_TIME
    with _LOCK:
        if not refresh and _REPORT is not None and _monotonic() - _REPORT_TIME < CACHE_TTL:
            return _REPORT
        probe_box: dict[str, Any] = {}
        thread = None
        if cfg.get("gps_enable"):
            if refresh or _GPSD_PROBE is None or _monotonic() - _GPSD_PROBE_TIME > GPSD_PROBE_TTL:
                # parallel zur PPS-Pause, damit insgesamt nur einmal gewartet wird
                thread = threading.Thread(
                    target=lambda: probe_box.update(result=_probe_gpsd(GPSD_PROBE_SECONDS)), daemon=True)
                thread.start()
            else:
                probe_box["result"] = _GPSD_PROBE
        ctx = {"gps_status": _gps_status(cfg), "tracking": _tracking(), "chronyd": _chronyd()}
        # PPS wird in build_report gesampelt; die gpsd-Abfrage läuft solange parallel.
        sources = _read_pps_sources()
        _sample_pps(sources)
        if thread is not None:
            thread.join(GPSD_PROBE_SECONDS + 1.0)
            if probe_box.get("result") is not None:
                _GPSD_PROBE, _GPSD_PROBE_TIME = probe_box["result"], _monotonic()
        ctx["gpsd_probe"] = probe_box.get("result")
        rep = build_report(cfg, ctx)
        _REPORT, _REPORT_TIME = rep, _monotonic()
        return rep


def cached_report() -> dict[str, Any] | None:
    """Der zuletzt erzeugte Bericht oder None – blockiert nie (für /metrics)."""
    return _REPORT


INSIGHT_KEYS = ("gps_usb", "gps_pps", "ptp_hw", "ptp_sw", "ptp_to_ntp", "gps_to_ptp", "nts")


def cached_insights(cfg: dict) -> list[dict[str, Any]]:
    """Hinweise aus dem zuletzt erzeugten Bericht – blockiert nie, [] ohne Bericht.

    Warnungen nur für Funktionen, die in den Einstellungen eingeschaltet sind.
    """
    rep = _REPORT
    if not rep:
        return []
    out: list[dict[str, Any]] = []
    rows = {row["key"]: row for row in rep.get("matrix") or []}

    def add(level, title, text, action, key):
        out.append({"level": level, "title": title, "text": text, "action": action, "key": key})

    gps_on = bool(cfg.get("gps_enable"))
    ptp_on = bool(cfg.get("ptp_enable"))
    usb = rows.get("gps_usb")
    if usb and gps_on and usb["status"] in {"change", "no"}:
        receiver_missing = usb["status"] == "change" and "nicht nutzbar im Container" in usb["text"]
        add("crit" if receiver_missing else "warn", "GPS-Empfänger nicht nutzbar", usb["text"],
            "hardware", "hw_gps_usb")
    pps = rows.get("gps_pps")
    if pps and gps_on and (cfg.get("gps_pps_device") or cfg.get("gps_pps_shm")) \
            and pps["status"] in {"change", "no"}:
        add("warn", "PPS eingestellt, aber nicht wirksam", pps["text"], "hardware", "hw_gps_pps")
    hw = rows.get("ptp_hw")
    if hw and ptp_on and cfg.get("ptp_time_stamping", "hardware") == "hardware" \
            and hw["status"] in {"change", "no"}:
        add("warn", "PTP: Hardware-Zeitstempel nicht verfügbar", hw["text"], "hardware", "hw_ptp_hw")
    sw = rows.get("ptp_sw")
    if sw and ptp_on and cfg.get("ptp_time_stamping") == "software" and sw["status"] in {"change", "no"}:
        add("warn", "PTP: so nicht lauffähig", sw["text"], "hardware", "hw_ptp_sw")
    gm = rows.get("gps_to_ptp")
    if gm and gm["active"] and ptp_on and gps_on and cfg.get("ptp_mode") == "master":
        if gm["status"] == "limited":
            add("info", "Grandmaster mit ungenauer GPS-Zeit", gm["text"], "hardware", "hw_gps_to_ptp")
        elif gm["status"] in {"change", "no"}:
            add("warn", "Grandmaster ohne GPS+PPS", gm["text"], "hardware", "hw_gps_to_ptp")
    nts = rows.get("nts")
    # Fehlende/unlesbare Server-Zertifikate meldet schon insights.nts_server_insights.
    if nts and nts["active"] and nts["status"] == "change" \
            and not (cfg.get("nts_server_enable") and nts.get("cause") == "nts_server_files"):
        add("warn", "NTS: Einstellung prüfen", nts["text"], "hardware", "hw_nts")
    return out
