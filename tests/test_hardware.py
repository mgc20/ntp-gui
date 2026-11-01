"""Hardware-Check gegen einen falschen /sys-, /proc- und /dev-Baum."""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import devices  # noqa: E402
import gps  # noqa: E402
import hardware  # noqa: E402

CAP_DEFAULT = "00000000a80425fb"          # Docker-Standard
CAP_TIME_ADMIN = "00000000aa0435fb"       # + SYS_TIME + NET_ADMIN
CAP_FULL = "000001ffffffffff"             # privilegiert (cap_last_cap 40)

ETHTOOL_I210 = """Time stamping parameters for enp3s0:
Capabilities:
\thardware-transmit
\tsoftware-transmit
\thardware-receive
\tsoftware-receive
\tsoftware-system-clock
\thardware-raw-clock
PTP Hardware Clock: 0
Hardware Transmit Timestamp Modes:
\toff
\ton
"""
ETHTOOL_SOFT = """Time stamping parameters for eth0:
Capabilities:
\tsoftware-transmit
\tsoftware-receive
\tsoftware-system-clock
PTP Hardware Clock: none
Hardware Transmit Timestamp Modes: none
"""
ETHTOOL_PI5 = ETHTOOL_I210.replace("enp3s0", "eth0")

PROC_DEVICES = """Character devices:
  1 mem
  4 /dev/vc/0
  4 tty
  5 /dev/tty
166 ttyACM
188 ttyUSB
204 ttyAMA
245 pps
246 ptp
249 rtc

Block devices:
  8 sd
"""
MOUNTINFO_TMPFS = ("600 590 0:60 / / rw,relatime - overlay overlay rw\n"
                   "601 600 0:62 / /dev rw,nosuid - tmpfs tmpfs rw,size=65536k,mode=755\n")
MOUNTINFO_HOSTDEV = ("600 590 0:60 / / rw,relatime - overlay overlay rw\n"
                     "601 600 0:5 / /dev rw,nosuid,relatime - devtmpfs udev rw,size=4000000k\n")

GPSD_UBLOX7 = {"class": "DEVICE", "path": "/dev/ttyACM0", "driver": "u-blox",
               "subtype": "SW 1.00 (59842),HW 00070000", "activated": "2026-11-01T10:00:00.000Z",
               "flags": 1, "native": 1, "bps": 9600}
GPSD_F9T = {"class": "DEVICE", "path": "/dev/ttyAMA0", "driver": "u-blox",
            "subtype": "SW EXT CORE 1.00 (f10c36),HW 00190000",
            "subtype1": "ROM BASE 0x118B2060,FWVER=TIM 2.20,PROTVER=29.20,MOD=ZED-F9T,GPS;GLO;GAL;BDS",
            "activated": "2026-11-01T10:00:00.000Z", "flags": 1, "native": 1, "bps": 38400}


class FakeHost:
    """Baut einen minimalen sysfs/proc/dev-Baum in einem Temp-Ordner."""

    def __init__(self, base: str):
        self.base = base
        self.sys = os.path.join(base, "sys")
        self.proc = os.path.join(base, "proc")
        self.dev = os.path.join(base, "dev")
        self.root = os.path.join(base, "root")
        for d in (self.sys, self.proc, self.dev, self.root):
            os.makedirs(d)
        self.ethtool: dict[str, str] = {}
        self.caps(CAP_TIME_ADMIN)
        self.write("proc/sys/kernel/cap_last_cap", "40\n")
        self.write("proc/devices", PROC_DEVICES)
        self.write("proc/self/mountinfo", MOUNTINFO_TMPFS)
        self.write("proc/cpuinfo", "processor\t: 0\nflags\t\t: fpu vme sse sse2\n")
        self.write("proc/sys/kernel/osrelease", "6.1.0-28-amd64\n")
        self.write("proc/modules", "")
        self.write("root/.dockerenv", "")
        os.makedirs(os.path.join(self.sys, "class", "net"))

    def write(self, rel: str, text: str) -> str:
        path = os.path.join(self.base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def link(self, target: str, rel: str) -> None:
        path = os.path.join(self.base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.symlink(target, path)

    def caps(self, cap_eff: str, seccomp: str = "2") -> None:
        self.write("proc/self/status", f"Name:\tpython3\nCapPrm:\t{cap_eff}\nCapEff:\t{cap_eff}\n"
                                       f"Seccomp:\t{seccomp}\n")

    def driver(self, devdir: str, name: str, bus: str = "usb") -> None:
        drv = os.path.join(self.sys, "bus", bus, "drivers", name)
        os.makedirs(drv, exist_ok=True)
        os.symlink(drv, os.path.join(devdir, "driver"))

    def usb_tty(self, tty: str, driver: str, vid: str, pid: str, manufacturer: str, product: str,
                speed: str = "12", node: bool = True, by_id: str | None = None, major: int = 166) -> None:
        usbdev = os.path.join(self.sys, "devices", "pci0000:00", "0000:00:14.0", "usb1", "1-1")
        os.makedirs(usbdev, exist_ok=True)
        for key, value in (("idVendor", vid), ("idProduct", pid), ("manufacturer", manufacturer),
                           ("product", product), ("speed", speed)):
            with open(os.path.join(usbdev, key), "w", encoding="utf-8") as handle:
                handle.write(value + "\n")
        iface = os.path.join(usbdev, "1-1:1.0")
        os.makedirs(iface, exist_ok=True)
        if tty.startswith("ttyACM"):
            ttydev = iface
        else:
            ttydev = os.path.join(iface, tty)
            os.makedirs(ttydev, exist_ok=True)
        self.driver(ttydev, driver, "usb" if driver == "cdc_acm" else "usb-serial")
        cls = os.path.join(self.sys, "class", "tty", tty)
        os.makedirs(cls, exist_ok=True)
        os.symlink(ttydev, os.path.join(cls, "device"))
        self.write(f"sys/class/tty/{tty}/dev", f"{major}:0\n")
        if node:
            self.write(f"dev/{tty}", "")
        if by_id:
            self.link(f"../../{tty}", f"dev/serial/by-id/{by_id}")

    def uart_tty(self, tty: str, driver: str, node: bool = True, type_: str = "1") -> None:
        dev = os.path.join(self.sys, "devices", "platform", f"{tty}.serial")
        os.makedirs(dev, exist_ok=True)
        self.driver(dev, driver, "amba")
        cls = os.path.join(self.sys, "class", "tty", tty)
        os.makedirs(cls, exist_ok=True)
        os.symlink(dev, os.path.join(cls, "device"))
        self.write(f"sys/class/tty/{tty}/type", type_ + "\n")
        self.write(f"sys/class/tty/{tty}/dev", "204:64\n")
        if node:
            self.write(f"dev/{tty}", "")

    def pps(self, n: int, name: str, path: str = "", assert_: str = "0.000000000#0",
            node: bool = True, major: int = 245) -> None:
        for key, value in (("name", name), ("path", path), ("assert", assert_),
                           ("dev", f"{major}:{n}"), ("mode", "0x1133")):
            self.write(f"sys/class/pps/pps{n}/{key}", value + "\n")
        if node:
            self.write(f"dev/pps{n}", "")

    def set_assert(self, n: int, value: str) -> None:
        self.write(f"sys/class/pps/pps{n}/assert", value + "\n")

    def ptp(self, n: int, clock_name: str, ext: int = 0, pins: int = 0, node: bool = True) -> None:
        for key, value in (("clock_name", clock_name), ("max_adjustment", "999999999"),
                           ("n_external_timestamps", str(ext)), ("n_periodic_outputs", str(ext)),
                           ("n_pins", str(pins)), ("pps_available", "1"), ("dev", f"246:{n}")):
            self.write(f"sys/class/ptp/ptp{n}/{key}", value + "\n")
        if node:
            self.write(f"dev/ptp{n}", "")

    def nic(self, name: str, driver: str | None, phc: int | None = None, ethtool: str | None = None,
            virtio: bool = False) -> None:
        net = os.path.join(self.sys, "class", "net", name)
        os.makedirs(net)
        self.write(f"sys/class/net/{name}/operstate", "up\n")
        self.write(f"sys/class/net/{name}/ifindex", "2\n")
        self.write(f"sys/class/net/{name}/iflink", "2\n")
        if driver:
            sub = f"virtio0" if virtio else f"0000:03:00.0-{name}"
            dev = os.path.join(self.sys, "devices", "pci0000:00", sub)
            os.makedirs(dev)
            self.driver(dev, driver, "virtio" if virtio else "pci")
            os.symlink(dev, os.path.join(net, "device"))
            if phc is not None:
                os.makedirs(os.path.join(dev, "ptp", f"ptp{phc}"))
        if ethtool is not None:
            self.ethtool[name] = ethtool

    def bridge_nic(self) -> None:
        net = os.path.join(self.sys, "class", "net", "eth0")
        os.makedirs(net)
        self.write("sys/class/net/eth0/ifindex", "11\n")
        self.write("sys/class/net/eth0/iflink", "12\n")
        self.write("sys/class/net/eth0/operstate", "up\n")
        os.makedirs(os.path.join(self.sys, "class", "net", "lo"))
        self.ethtool["eth0"] = ETHTOOL_SOFT

    def pi(self, model: str = "Raspberry Pi 5 Model B Rev 1.0") -> None:
        self.write("proc/device-tree/model", model + "\x00")
        self.write("proc/cpuinfo", "processor\t: 0\nBogoMIPS\t: 108.00\nFeatures\t: fp asimd\n")


def base_cfg(**over):
    cfg = {
        "ntp_sources": [{"type": "pool", "host": "pool.ntp.org", "nts": False}],
        "nts_nocerttimecheck": True, "nts_server_enable": False,
        "nts_server_cert": "/config/nts.crt", "nts_server_key": "/config/nts.key",
        "gps_enable": False, "gps_device": "/dev/ttyACM0", "gps_pps_device": "", "gps_pps_shm": False,
        "ptp_enable": False, "ptp_interface": "", "ptp_mode": "auto", "ptp_time_stamping": "hardware",
        "ptp_transport": "UDPv4", "ptp_clock_class": 248, "phc2sys_enable": False, "phc_refclock": "",
    }
    cfg.update(over)
    return cfg


class HardwareTestCase(unittest.TestCase):
    ENV = ("NTPGUI_SYS_ROOT", "NTPGUI_PROC_ROOT", "NTPGUI_DEV_ROOT", "NTPGUI_ROOT", "NTPGUI_SYS_NET")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.host = FakeHost(self.tmp)
        self.saved_env = {k: os.environ.get(k) for k in self.ENV}
        os.environ["NTPGUI_SYS_ROOT"] = self.host.sys
        os.environ["NTPGUI_PROC_ROOT"] = self.host.proc
        os.environ["NTPGUI_DEV_ROOT"] = self.host.dev
        os.environ["NTPGUI_ROOT"] = self.host.root
        os.environ.pop("NTPGUI_SYS_NET", None)
        self.saved = {name: getattr(hardware, name) for name in
                      ("_sleep", "_monotonic", "_now", "_machine", "_gps_status", "_tracking",
                       "_probe_gpsd", "_try_open", "_chronyd")}
        self.saved_ethtool = devices._ethtool
        devices._ethtool = lambda name: self.host.ethtool.get(name)
        self.clock = [1000.0]
        self.sleeps = []
        self.on_sleep = None

        def fake_sleep(seconds):
            self.sleeps.append(seconds)
            self.clock[0] += seconds
            if self.on_sleep:
                self.on_sleep()

        hardware._sleep = fake_sleep
        hardware._monotonic = lambda: self.clock[0]
        hardware._now = lambda: 1793527200.0
        hardware._machine = lambda: "x86_64"
        self.gps_status = {}
        self.tracking = {"synchronised": True}
        self.probe = None
        hardware._gps_status = lambda cfg: self.gps_status
        hardware._tracking = lambda: self.tracking
        hardware._probe_gpsd = lambda timeout: self.probe
        hardware._chronyd = lambda: {"pid": 42, "clock_control": True}
        hardware._PPS_CACHE.clear()
        hardware._REPORT = None
        hardware._GPSD_PROBE = None

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(hardware, name, value)
        devices._ethtool = self.saved_ethtool
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        hardware._PPS_CACHE.clear()
        hardware._REPORT = None
        hardware._GPSD_PROBE = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_report(self, cfg):
        return hardware.report(cfg, refresh=True)

    @staticmethod
    def row(rep, key):
        return next(r for r in rep["matrix"] if r["key"] == key)

    # -- Fixtures ----------------------------------------------------------
    def vk162(self, node=True):
        self.host.usb_tty("ttyACM0", "cdc_acm", "1546", "01a7", "u-blox AG - www.u-blox.com",
                          "u-blox 7 - GPS/GNSS Receiver", node=node,
                          by_id="usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00")

    def pi5_pps(self, live=True, never=False):
        self.host.pi()
        self.host.uart_tty("ttyAMA0", "uart-pl011")
        self.host.pps(0, "pps@12.-1", assert_="0.000000000#0" if never else "1793527199.000000312#4710")
        if live and not never:
            self.on_sleep = lambda: self.host.set_assert(0, "1793527200.000000280#4711")


class TestContract(HardwareTestCase):
    def test_all_keys_present(self):
        rep = self.run_report(base_cfg())
        for key in ("generated", "platform", "permissions", "gps", "pps", "ptp", "rtc", "majors",
                    "matrix", "warnings"):
            self.assertIn(key, rep)
        for key in ("container", "docker_desktop", "wsl", "arch", "hypervisor", "dmi", "board", "summary"):
            self.assertIn(key, rep["platform"])
        for key in ("cap_eff", "privileged", "sys_time", "net_admin", "net_raw", "sys_nice",
                    "network", "dev_mounted", "modules"):
            self.assertIn(key, rep["permissions"])
        self.assertEqual([r["key"] for r in rep["matrix"]],
                         ["ntp_server", "clock_control", "nts", "gps_usb", "gps_pps", "ptp_hw",
                          "ptp_sw", "ptp_to_ntp", "gps_to_ptp"])
        for row in rep["matrix"]:
            self.assertEqual(set(row), {"key", "title", "status", "text", "fix", "accuracy", "active"})
            self.assertIn(row["status"], {"ok", "limited", "change", "no", "unknown"})
        self.assertEqual(rep["platform"]["container"], "docker")
        json.dumps(rep)  # muss serialisierbar sein

    def test_no_private_keys_leak(self):
        self.vk162()
        self.pi5_pps()
        self.host.ptp(0, "gem-ptp-timer")
        rep = self.run_report(base_cfg())
        for item in rep["gps"]["receivers"] + rep["pps"] + rep["ptp"]["clocks"]:
            self.assertFalse([k for k in item if k.startswith("_")])

    def test_cache(self):
        first = hardware.report(base_cfg())
        self.clock[0] += 5
        self.assertIs(hardware.report(base_cfg()), first)
        self.clock[0] += 40
        self.assertIsNot(hardware.report(base_cfg()), first)
        self.assertIsNot(hardware.report(base_cfg(), refresh=True), first)

    def test_majors(self):
        rep = self.run_report(base_cfg())
        self.assertEqual(rep["majors"], {"pps": 245, "ptp": 246})
        self.assertEqual(hardware.parse_proc_devices(PROC_DEVICES)["ttyACM"], 166)


class TestPermissions(HardwareTestCase):
    def test_docker_default_caps(self):
        self.host.caps(CAP_DEFAULT)
        rep = self.run_report(base_cfg())
        perms = rep["permissions"]
        self.assertEqual(perms["cap_eff"], CAP_DEFAULT)
        self.assertFalse(perms["sys_time"])
        self.assertFalse(perms["net_admin"])
        self.assertTrue(perms["net_raw"])
        self.assertFalse(perms["privileged"])
        row = self.row(rep, "clock_control")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], "cap_add:\n  - SYS_TIME")

    def test_time_and_admin(self):
        self.host.caps(CAP_TIME_ADMIN)
        perms = self.run_report(base_cfg())["permissions"]
        self.assertTrue(perms["sys_time"] and perms["net_admin"] and perms["net_raw"])
        self.assertFalse(perms["sys_nice"])
        self.assertEqual(self.row(self.run_report(base_cfg()), "clock_control")["status"], "ok")

    def test_privileged(self):
        self.host.caps(CAP_FULL, seccomp="0")
        rep = self.run_report(base_cfg())
        self.assertTrue(rep["permissions"]["privileged"])
        self.assertIn("privilegiert", rep["platform"]["summary"])
        self.assertTrue(any("privilegiert" in w for w in rep["warnings"]))
        # volle Rechte, aber Seccomp aktiv → nicht privilegiert
        self.host.caps(CAP_FULL, seccomp="2")
        self.assertFalse(self.run_report(base_cfg())["permissions"]["privileged"])

    def test_dev_mounted(self):
        self.assertFalse(self.run_report(base_cfg())["permissions"]["dev_mounted"])
        self.host.write("proc/self/mountinfo", MOUNTINFO_HOSTDEV)
        self.assertTrue(self.run_report(base_cfg())["permissions"]["dev_mounted"])

    def test_dev_mounted_by_id(self):
        self.vk162()
        self.assertTrue(self.run_report(base_cfg())["permissions"]["dev_mounted"])

    def test_modules(self):
        self.host.write("proc/modules", "pps_gpio 12288 0 - Live 0x0\ncdc_acm 32768 0 - Live 0x0\n")
        os.makedirs(os.path.join(self.host.sys, "module", "pps_core"))
        mods = self.run_report(base_cfg())["permissions"]["modules"]
        self.assertTrue(mods["pps_gpio"] and mods["cdc_acm"] and mods["pps_core"])
        self.assertFalse(mods["ftdi_sio"])

    def test_readiness_capability(self):
        self.host.caps(CAP_DEFAULT)
        check = next(c for c in devices.ptp_readiness(base_cfg()) if c["key"] == "capability")
        self.assertIs(check["ok"], False)
        self.assertIn("NET_ADMIN", check["detail"])
        self.host.caps(CAP_TIME_ADMIN)
        check = next(c for c in devices.ptp_readiness(base_cfg()) if c["key"] == "capability")
        self.assertIs(check["ok"], True)

    def test_parse_cap(self):
        self.assertEqual(devices.parse_cap_hex("aa0435fb") - devices.parse_cap_hex("a80425fb"),
                         (1 << 25) + (1 << 12))
        self.assertIsNone(devices.parse_cap_hex("zz"))


class TestNetwork(HardwareTestCase):
    def test_bridge(self):
        self.host.bridge_nic()
        rep = self.run_report(base_cfg(ptp_enable=True))
        self.assertEqual(rep["permissions"]["network"], "bridge")
        hw = self.row(rep, "ptp_hw")
        self.assertEqual(hw["status"], "change")
        self.assertEqual(hw["fix"], "network_mode: host")
        self.assertIn("NAT", self.row(rep, "ntp_server")["text"])
        check = next(c for c in devices.ptp_readiness(base_cfg()) if c["key"] == "host_network")
        self.assertIs(check["ok"], False)
        insights = hardware.cached_insights(base_cfg(ptp_enable=True))
        self.assertEqual([i["key"] for i in insights], ["hw_ptp_hw"])
        self.assertEqual(insights[0]["action"], "hardware")

    def test_host_with_docker0(self):
        self.host.nic("eth0", "igb", phc=0, ethtool=ETHTOOL_I210)
        os.makedirs(os.path.join(self.host.sys, "class", "net", "docker0"))
        self.assertEqual(devices.network_mode(), "host")


class TestGpsReceivers(HardwareTestCase):
    def test_vk162(self):
        self.vk162()
        self.gps_status = {"running": True, "devices": gps.parse_devices({"devices": [GPSD_UBLOX7]})}
        rep = self.run_report(base_cfg(gps_enable=True))
        (rec,) = rep["gps"]["receivers"]
        self.assertEqual(rec["tty"], "ttyACM0")
        self.assertEqual(rec["tty_driver"], "cdc_acm")
        self.assertEqual(rec["usb"]["vid"], "1546")
        self.assertEqual(rec["usb"]["pid"], "01a7")
        self.assertEqual(rec["usb"]["speed_mbit"], 12)
        self.assertEqual(rec["gpsd"]["generation"], "u-blox 7")
        self.assertFalse(rec["gpsd"]["timing"])
        self.assertTrue(rec["gpsd"]["activated"])
        self.assertEqual(rec["gpsd"]["bps"], 9600)
        self.assertEqual(rec["interface"], "USB (CDC-ACM)")
        self.assertEqual(rec["pps_path"], "none")
        self.assertIn("VK-162", rec["product"])
        self.assertTrue(rec["stable_path"].startswith("/dev/serial/by-id/usb-u-blox"))
        self.assertTrue(rec["configured"] and rec["in_container"] and rec["usable"])
        self.assertEqual(rec["tone"], "warn")
        self.assertIn("kein PPS möglich", rec["verdict"])
        self.assertEqual(self.row(rep, "gps_usb")["status"], "ok")
        pps = self.row(rep, "gps_pps")
        self.assertEqual(pps["status"], "no")
        self.assertIn("USB-Modem-Gerät", pps["text"])
        self.assertEqual(hardware.cached_insights(base_cfg(gps_enable=True)), [])

    def test_vk162_by_id_config(self):
        self.vk162()
        cfg = base_cfg(gps_device="/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00")
        rec = self.run_report(cfg)["gps"]["receivers"][0]
        self.assertTrue(rec["configured"])

    def test_vk162_not_in_container(self):
        self.vk162(node=False)
        rep = self.run_report(base_cfg(gps_enable=True))
        rec = rep["gps"]["receivers"][0]
        self.assertTrue(rec["host_present"])
        self.assertFalse(rec["in_container"])
        self.assertFalse(rec["usable"])
        row = self.row(rep, "gps_usb")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], "devices:\n  - /dev/ttyACM0:/dev/ttyACM0")
        self.assertIn("einkommentieren", row["text"])
        insights = hardware.cached_insights(base_cfg(gps_enable=True))
        self.assertEqual(insights[0]["level"], "crit")
        self.assertEqual(insights[0]["key"], "hw_gps_usb")
        # GPS aus → kein Hinweis
        self.assertEqual(hardware.cached_insights(base_cfg(gps_enable=False)), [])

    def test_gps_disabled(self):
        self.vk162()
        row = self.row(self.run_report(base_cfg()), "gps_usb")
        self.assertEqual(row["status"], "change")
        self.assertIn("GPS_ENABLE", row["fix"])
        self.assertFalse(row["active"])

    def test_gpsd_cannot_open(self):
        self.vk162()
        dev = dict(GPSD_UBLOX7)
        dev.pop("activated")
        self.gps_status = {"running": True, "devices": gps.parse_devices({"devices": [dev]})}
        rep = self.run_report(base_cfg(gps_enable=True))
        row = self.row(rep, "gps_usb")
        # by-id sichtbar → /dev des Hosts eingehängt: belegt ODER cgroup-Regel fehlt
        self.assertEqual(row["status"], "change")
        self.assertIn("ModemManager", row["text"])
        self.assertEqual(row["fix"], 'device_cgroup_rules:\n  - "c 166:* rwm"')

    def test_gpsd_cannot_open_single_device(self):
        self.host.usb_tty("ttyACM0", "cdc_acm", "1546", "01a7", "u-blox AG - www.u-blox.com",
                          "u-blox 7 - GPS/GNSS Receiver")
        dev = dict(GPSD_UBLOX7)
        dev.pop("activated")
        self.gps_status = {"running": True, "devices": gps.parse_devices({"devices": [dev]})}
        row = self.row(self.run_report(base_cfg(gps_enable=True)), "gps_usb")
        self.assertEqual(row["status"], "no")
        self.assertIn("ModemManager", row["text"])

    def test_ftdi(self):
        self.host.usb_tty("ttyUSB0", "ftdi_sio", "0403", "6001", "FTDI", "FT232R USB UART", major=188)
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="/dev/ttyUSB0"))
        (rec,) = rep["gps"]["receivers"]
        self.assertEqual(rec["tty_driver"], "ftdi_sio")
        self.assertEqual(rec["interface"], "USB-Seriell (FTDI)")
        self.assertEqual(rec["pps_path"], "dcd_usb")
        self.assertIn("DCD", rec["verdict"])
        self.assertEqual(self.row(rep, "gps_pps")["status"], "no")

    def test_ftdi_with_gpsd_pps(self):
        self.host.usb_tty("ttyUSB0", "ftdi_sio", "0403", "6001", "FTDI", "FT232R USB UART", major=188)
        self.probe = {"seen": True, "pps_devices": ["/dev/ttyUSB0"], "toff_latency_ms": 78.4,
                      "devices": [], "reachable": True}
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="/dev/ttyUSB0"))
        self.assertEqual(rep["gps"]["gpsd_pps"], {"seen": True, "toff_latency_ms": 78.4})
        rec = rep["gps"]["receivers"][0]
        self.assertEqual(rec["tone"], "good")
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "limited")
        self.assertEqual(row["fix"], 'environment:\n  GPS_PPS_SHM: "true"')
        self.assertEqual(row["accuracy"], "~1 ms")

    def test_gpsd_details_f9t(self):
        details = hardware.gpsd_details(GPSD_F9T)
        self.assertEqual(details["module"], "ZED-F9T")
        self.assertEqual(details["generation"], "u-blox F9/M9")
        self.assertTrue(details["timing"])
        self.assertFalse(hardware.gpsd_details({"subtype1": "MOD=NEO-M8N-0"})["timing"])
        self.assertTrue(hardware.gpsd_details({"subtype1": "MOD=LEA-M8T-0"})["timing"])
        self.assertIsNone(hardware.gpsd_details(None))

    def test_ttys_placeholder_skipped(self):
        self.host.uart_tty("ttyS1", "serial8250", type_="0")
        self.assertEqual(self.run_report(base_cfg())["gps"]["receivers"], [])


class TestPps(HardwareTestCase):
    def test_parse_assert(self):
        self.assertEqual(hardware.parse_pps_assert("1170026870.983207967#8"), (1170026870, 983207967, 8))
        self.assertEqual(hardware.parse_pps_assert("0.000000000#0"), (0, 0, 0))
        self.assertIsNone(hardware.parse_pps_assert(""))

    def test_pi5_gpio_live(self):
        self.pi5_pps()
        self.gps_status = {"running": True, "devices": gps.parse_devices({"devices": [GPSD_F9T]})}
        cfg = base_cfg(gps_enable=True, gps_device="/dev/ttyAMA0", gps_pps_device="/dev/pps0")
        rep = self.run_report(cfg)
        self.assertEqual(rep["platform"]["board"]["family"], "pi5")
        self.assertTrue(rep["platform"]["board"]["ptp_expected"])
        self.assertTrue(rep["platform"]["summary"].startswith("Raspberry Pi 5 Model B · Docker"))
        (pps,) = rep["pps"]
        self.assertEqual(pps["kind"], "gpio")
        self.assertEqual(pps["state"], "live")
        self.assertAlmostEqual(pps["rate_hz"], 0.83, places=2)
        self.assertEqual(pps["assert"]["seq"], 4711)
        self.assertAlmostEqual(pps["phase_us"], 0.3, places=1)
        self.assertTrue(pps["configured"] and pps["usable"])
        rec = rep["gps"]["receivers"][0]
        self.assertEqual(rec["tty"], "ttyAMA0")
        self.assertEqual(rec["pps_path"], "gpio")
        self.assertEqual(rec["tone"], "good")
        self.assertIn("Timing-Modul (ZED-F9T)", rec["verdict"])
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["accuracy"], "~1 µs")
        self.assertEqual(self.sleeps, [hardware.PPS_SAMPLE_SECONDS])

    def test_cached_pulse_reading_avoids_second_pause(self):
        self.pi5_pps()
        cfg = base_cfg(gps_enable=True, gps_device="/dev/ttyAMA0", gps_pps_device="/dev/pps0")
        self.run_report(cfg)
        self.clock[0] += 5
        self.host.set_assert(0, "1793527205.000000280#4716")
        rep = self.run_report(cfg)
        self.assertEqual(len(self.sleeps), 1)
        self.assertEqual(rep["pps"][0]["state"], "live")
        self.assertAlmostEqual(rep["pps"][0]["rate_hz"], 1.0)

    def test_pi5_gpio_stale(self):
        self.pi5_pps(live=False)
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="/dev/ttyAMA0",
                                       gps_pps_device="/dev/pps0"))
        self.assertEqual(rep["pps"][0]["state"], "stale")
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "no")
        self.assertIn("keine Impulse", row["text"])
        insights = hardware.cached_insights(base_cfg(gps_enable=True, gps_pps_device="/dev/pps0"))
        self.assertIn("hw_gps_pps", [i["key"] for i in insights])

    def test_pi5_gpio_never(self):
        self.pi5_pps(never=True)
        rep = self.run_report(base_cfg(gps_enable=True, gps_pps_device="/dev/pps0"))
        self.assertEqual(rep["pps"][0]["state"], "never")
        self.assertEqual(self.sleeps, [])  # nie ein Impuls → kein Warten nötig
        self.assertIn("noch nie", self.row(rep, "gps_pps")["text"])

    def test_pps_not_configured(self):
        self.pi5_pps()
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="/dev/ttyAMA0"))
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], "environment:\n  GPS_PPS_DEVICE: /dev/pps0")

    def test_pps_auto(self):
        self.pi5_pps()
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="auto", gps_pps_device="auto"))
        self.assertTrue(rep["pps"][0]["configured"])
        self.assertTrue(rep["gps"]["receivers"][0]["configured"])
        self.assertEqual(self.row(rep, "gps_pps")["status"], "ok")

    def test_pps_not_in_container(self):
        self.host.pi()
        self.host.pps(0, "pps@12.-1", assert_="1793527199.000000312#4710", node=False)
        self.on_sleep = lambda: self.host.set_assert(0, "1793527200.000000280#4711")
        rep = self.run_report(base_cfg(gps_enable=True, gps_pps_device="/dev/pps0"))
        self.assertFalse(rep["pps"][0]["in_container"])
        self.assertIsNone(rep["pps"][0]["usable"])
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], "devices:\n  - /dev/pps0:/dev/pps0")

    def test_pps_eperm_with_host_dev(self):
        self.pi5_pps()
        self.host.write("proc/self/mountinfo", MOUNTINFO_HOSTDEV)
        hardware._try_open = lambda path: (False, "EPERM")
        rep = self.run_report(base_cfg(gps_enable=True, gps_pps_device="/dev/pps0"))
        self.assertTrue(rep["permissions"]["dev_mounted"])
        self.assertIn("EPERM", rep["pps"][0]["error"])
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], 'device_cgroup_rules:\n  - "c 245:* rwm"')
        self.assertIn("PPS_MAJOR=245", row["text"])

    def test_pi_usb_only(self):
        self.host.pi("Raspberry Pi 4 Model B Rev 1.5")
        self.vk162()
        rep = self.run_report(base_cfg(gps_enable=True))
        self.assertEqual(rep["platform"]["board"]["family"], "pi4")
        row = self.row(rep, "gps_pps")
        self.assertEqual(row["status"], "no")
        self.assertIn("dtoverlay=pps-gpio,gpiopin=18", row["fix"])
        self.assertIn("Modul mit PPS-Ausgang an GPIO", self.run_report(base_cfg())["gps"]["receivers"][0]["verdict"])

    def test_pi_uart_without_pps(self):
        self.host.pi()
        self.host.uart_tty("ttyAMA0", "uart-pl011")
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="/dev/ttyAMA0"))
        self.assertEqual(rep["gps"]["receivers"][0]["pps_path"], "possible_gpio")
        self.assertEqual(self.row(rep, "gps_pps")["status"], "change")

    def test_ldisc_kind(self):
        self.host.uart_tty("ttyS0", "serial8250")
        self.host.pps(0, "serial0", path="/dev/ttyS0", assert_="1793527199.000000312#10")
        self.on_sleep = lambda: self.host.set_assert(0, "1793527200.000000300#11")
        rep = self.run_report(base_cfg(gps_enable=True, gps_device="/dev/ttyS0", gps_pps_device="/dev/pps0"))
        self.assertEqual(rep["pps"][0]["kind"], "ldisc")
        self.assertEqual(rep["gps"]["receivers"][0]["pps_path"], "dcd_uart")
        self.assertEqual(self.row(rep, "gps_pps")["status"], "ok")


class TestPtp(HardwareTestCase):
    def i210(self):
        self.host.nic("enp3s0", "igb", phc=0, ethtool=ETHTOOL_I210)
        self.host.ptp(0, "e4:5f:01:00:00:01", ext=2, pins=4)

    def test_i210_ok(self):
        self.i210()
        rep = self.run_report(base_cfg(ptp_enable=True, ptp_interface="enp3s0"))
        (clock,) = rep["ptp"]["clocks"]
        self.assertEqual(clock["interface"], "enp3s0")
        self.assertEqual(clock["kind"], "nic")
        self.assertEqual(clock["n_external_timestamps"], 2)
        self.assertTrue(clock["usable"])
        nic = rep["ptp"]["interfaces"][0]
        self.assertEqual(nic["nic_class"], "good")
        self.assertFalse(nic["passthrough"])
        self.assertEqual(self.row(rep, "ptp_hw")["status"], "ok")
        bridge = self.row(rep, "ptp_to_ntp")
        self.assertEqual(bridge["status"], "ok")
        self.assertIn("PHC_REFCLOCK: /dev/ptp0", bridge["fix"])
        self.assertEqual(hardware.cached_insights(base_cfg(ptp_enable=True)), [])

    def test_i210_missing_net_admin(self):
        self.i210()
        self.host.caps(CAP_DEFAULT)
        rep = self.run_report(base_cfg(ptp_enable=True, ptp_interface="enp3s0"))
        row = self.row(rep, "ptp_hw")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], "cap_add:\n  - NET_ADMIN\n  - NET_RAW")
        self.assertEqual(self.row(rep, "ptp_to_ntp")["status"], "change")

    def test_phc_not_in_container(self):
        self.host.nic("enp3s0", "igb", phc=0, ethtool=ETHTOOL_I210)
        self.host.ptp(0, "e4:5f:01:00:00:01", node=False)
        row = self.row(self.run_report(base_cfg()), "ptp_hw")
        self.assertEqual(row["status"], "change")
        self.assertEqual(row["fix"], "devices:\n  - /dev/ptp0:/dev/ptp0")

    def test_phc_eperm(self):
        self.i210()
        hardware._try_open = lambda path: (False, "EPERM")
        row = self.row(self.run_report(base_cfg()), "ptp_hw")
        self.assertEqual(row["fix"], 'device_cgroup_rules:\n  - "c 246:* rwm"')

    def test_gm_with_usb_gps_is_limited(self):
        self.i210()
        self.vk162()
        self.gps_status = {"running": True, "devices": gps.parse_devices({"devices": [GPSD_UBLOX7]})}
        cfg = base_cfg(gps_enable=True, ptp_enable=True, ptp_mode="master", ptp_interface="enp3s0")
        rep = self.run_report(cfg)
        gm = self.row(rep, "gps_to_ptp")
        self.assertEqual(gm["status"], "limited")
        self.assertIn("ts2phc", gm["text"])
        self.assertTrue(gm["active"])
        insights = hardware.cached_insights(cfg)
        self.assertEqual([(i["level"], i["key"]) for i in insights], [("info", "hw_gps_to_ptp")])

    def test_gm_with_pps_ok(self):
        self.host.pi()
        self.host.nic("eth0", "macb", phc=0, ethtool=ETHTOOL_PI5)
        self.host.ptp(0, "gem-ptp-timer")
        self.host.uart_tty("ttyAMA0", "uart-pl011")
        self.host.pps(0, "pps@12.-1", assert_="1793527199.000000312#4710")
        self.on_sleep = lambda: self.host.set_assert(0, "1793527200.000000280#4711")
        cfg = base_cfg(gps_enable=True, gps_device="/dev/ttyAMA0", gps_pps_device="/dev/pps0",
                       ptp_enable=True, ptp_mode="master", ptp_interface="eth0")
        rep = self.run_report(cfg)
        self.assertEqual(self.row(rep, "ptp_hw")["status"], "ok")
        gm = self.row(rep, "gps_to_ptp")
        self.assertEqual(gm["status"], "ok")
        self.assertIn("-a -rr", gm["text"])
        self.assertIn("PHC2SYS_ENABLE", gm["fix"])

    def test_kvm_virtio(self):
        self.host.write("proc/cpuinfo", "processor\t: 0\nflags\t\t: fpu sse2 hypervisor\n")
        self.host.write("sys/class/dmi/id/sys_vendor", "QEMU\n")
        self.host.write("sys/class/dmi/id/product_name", "Standard PC (Q35 + ICH9, 2009)\n")
        self.host.nic("eth0", "virtio_net", ethtool=ETHTOOL_SOFT, virtio=True)
        self.host.ptp(0, "KVM virtual PTP")
        rep = self.run_report(base_cfg(ptp_enable=True, ptp_interface="eth0"))
        self.assertEqual(rep["platform"]["hypervisor"], "KVM/QEMU")
        self.assertTrue(rep["platform"]["summary"].startswith("VM (KVM/QEMU)"))
        self.assertEqual(rep["ptp"]["clocks"][0]["kind"], "vm")
        self.assertEqual(rep["ptp"]["interfaces"][0]["nic_class"], "virtual")
        row = self.row(rep, "ptp_hw")
        self.assertEqual(row["status"], "no")
        self.assertIn("PCI-Passthrough", row["text"])
        self.assertEqual(self.row(rep, "ptp_sw")["status"], "ok")
        self.assertEqual(self.row(rep, "ptp_to_ntp")["status"], "limited")

    def test_classify(self):
        def cls(driver, hv=None, **extra):
            nic = {"driver": driver, "physical": True, "virtual_nic": False, "ethtool": True,
                   "ptp_hardware": False, "phc": None}
            nic.update(extra)
            return hardware.classify_nic(nic, hv, {})
        self.assertEqual(cls("e1000e", hv="KVM/QEMU")[0], "virtual")
        self.assertEqual(cls("e1000e", ptp_hardware=True)[0], "limited")
        self.assertEqual(cls("r8169")[0], "none")
        self.assertEqual(cls("bcmgenet")[0], "none")
        self.assertEqual(cls("igb", hv="KVM/QEMU", ptp_hardware=True), (
            "good", cls("igb", hv="KVM/QEMU", ptp_hardware=True)[1], True))
        self.assertIn("Passthrough", cls("igb", hv="KVM/QEMU", ptp_hardware=True)[1])
        nic = {"driver": "bcmgenet", "physical": True, "ethtool": True, "ptp_hardware": True,
               "phc": "/dev/ptp0"}
        self.assertEqual(hardware.classify_nic(nic, None, {"ptp0": "bcm_phy_ptp"})[0], "good")


class TestRtcAndNts(HardwareTestCase):
    def test_no_rtc(self):
        rep = self.run_report(base_cfg())
        self.assertFalse(rep["rtc"]["present"])
        self.assertEqual(self.row(rep, "nts")["status"], "ok")
        row = self.row(self.run_report(base_cfg(nts_nocerttimecheck=False)), "nts")
        self.assertEqual(row["status"], "change")
        self.assertIn("NTS_NOCERTTIMECHECK", row["fix"])

    def test_rtc_drift(self):
        self.host.write("sys/class/rtc/rtc0/name", "rpi-rtc soc:rpi_rtc\n")
        self.host.write("sys/class/rtc/rtc0/since_epoch", str(1793527200 - 3600) + "\n")
        self.host.write("sys/class/rtc/rtc0/hctosys", "1\n")
        rep = self.run_report(base_cfg())
        self.assertEqual(rep["rtc"]["drift_seconds"], -3600.0)
        self.assertTrue(rep["rtc"]["hctosys"])
        self.assertEqual(self.row(rep, "nts")["status"], "limited")


class TestReviewFixes(HardwareTestCase):
    def test_dev_mounted_only_in_container(self):
        self.vk162()
        self.host.write("proc/self/mountinfo", MOUNTINFO_HOSTDEV)
        self.assertTrue(self.run_report(base_cfg())["permissions"]["dev_mounted"])
        os.unlink(os.path.join(self.host.root, ".dockerenv"))
        rep = self.run_report(base_cfg())
        self.assertIsNone(rep["platform"]["container"])
        self.assertFalse(rep["permissions"]["dev_mounted"])

    def test_nts_row_names_configured_directory(self):
        cfg = base_cfg(nts_server_enable=True, nts_server_cert="/certs/npm-3/fullchain.pem",
                       nts_server_key="/certs/npm-3/privkey.pem")
        row = self.row(self.run_report(cfg), "nts")
        self.assertEqual(row["status"], "change")
        self.assertIn("/certs/npm-3", row["text"])
        self.assertNotIn("./config", row["text"])
        self.assertEqual(row["fix"], "volumes:\n  - <Ordner auf dem Host>:/certs/npm-3:ro")
        row = self.row(self.run_report(base_cfg(nts_server_enable=True)), "nts")
        self.assertEqual(row["fix"], "volumes:\n  - ./config:/config:ro")

    def test_no_duplicate_nts_server_insight(self):
        cfg = base_cfg(nts_server_enable=True, nts_server_cert="/certs/none/c.pem",
                       nts_server_key="/certs/none/k.pem")
        self.run_report(cfg)
        self.assertNotIn("hw_nts", [i["key"] for i in hardware.cached_insights(cfg)])
        # Andere NTS-Gründe (fehlende RTC für NTS-Quellen) bleiben ein Hinweis.
        cfg = base_cfg(nts_nocerttimecheck=False,
                       ntp_sources=[{"type": "server", "host": "nts.example", "nts": True}])
        self.run_report(cfg)
        self.assertIn("hw_nts", [i["key"] for i in hardware.cached_insights(cfg)])

    def test_capability_uses_profile_transport(self):
        self.host.caps(f"{int(CAP_TIME_ADMIN, 16) & ~(1 << 13):016x}")  # NET_ADMIN, ohne NET_RAW
        check = next(c for c in devices.ptp_readiness(base_cfg(ptp_profile="gptp"))
                     if c["key"] == "capability")
        self.assertIs(check["ok"], False)
        self.assertIn("NET_RAW", check["detail"])
        check = next(c for c in devices.ptp_readiness(base_cfg(ptp_profile="aes67"))
                     if c["key"] == "capability")
        self.assertIs(check["ok"], True)


class TestGpsModule(unittest.TestCase):
    def test_devices_in_reports(self):
        state = gps.parse_reports({"DEVICES": {"class": "DEVICES", "devices": [GPSD_F9T]}})
        (dev,) = state["devices"]
        self.assertEqual(dev["path"], "/dev/ttyAMA0")
        self.assertIn("MOD=ZED-F9T", dev["subtype1"])
        self.assertEqual(dev["bps"], 38400)
        self.assertEqual(dev["flags"], 1)
        self.assertEqual(state["driver"], "u-blox")

    def test_summarize_pps(self):
        msgs = [{"class": "PPS", "device": "/dev/ttyUSB0"},
                {"class": "TOFF", "real_sec": 100, "real_nsec": 0, "clock_sec": 100, "clock_nsec": 80000000},
                {"class": "TOFF", "real_sec": 101, "real_nsec": 0, "clock_sec": 101, "clock_nsec": 76000000}]
        result = gps.summarize_pps(msgs)
        self.assertTrue(result["seen"])
        self.assertEqual(result["pps_devices"], ["/dev/ttyUSB0"])
        self.assertAlmostEqual(result["toff_latency_ms"], 78.0)

    def test_probe_pps_against_fake_gpsd(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        received = []

        def serve():
            conn, _ = server.accept()
            with conn:
                received.append(conn.recv(1024))
                lines = [{"class": "VERSION", "release": "3.25"},
                         {"class": "DEVICES", "devices": [GPSD_UBLOX7]},
                         {"class": "TOFF", "device": "/dev/ttyACM0", "real_sec": 5, "real_nsec": 0,
                          "clock_sec": 5, "clock_nsec": 50000000},
                         {"class": "PPS", "device": "/dev/pps0", "real_sec": 6, "real_nsec": 0,
                          "clock_sec": 6, "clock_nsec": 100}]
                conn.sendall(b"".join(json.dumps(line).encode() + b"\n" for line in lines))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        old = os.environ.get("GPSD_PORT")
        os.environ["GPSD_PORT"] = str(port)
        try:
            result = gps.probe_pps(timeout=0.5)
        finally:
            if old is None:
                os.environ.pop("GPSD_PORT", None)
            else:
                os.environ["GPSD_PORT"] = old
            server.close()
        thread.join(1)
        self.assertIn(b'"pps":true', received[0])
        self.assertTrue(result["reachable"] and result["seen"])
        self.assertAlmostEqual(result["toff_latency_ms"], 50.0)
        self.assertEqual(result["devices"][0]["driver"], "u-blox")

    def test_probe_unreachable(self):
        old = os.environ.get("GPSD_PORT")
        os.environ["GPSD_PORT"] = "1"
        try:
            result = gps.probe_pps(timeout=0.2)
        finally:
            if old is None:
                os.environ.pop("GPSD_PORT", None)
            else:
                os.environ["GPSD_PORT"] = old
        self.assertFalse(result["reachable"] or result["seen"])


class TestInsightsWithoutReport(unittest.TestCase):
    def test_empty(self):
        saved = hardware._REPORT
        hardware._REPORT = None
        try:
            self.assertEqual(hardware.cached_insights({"gps_enable": True}), [])
        finally:
            hardware._REPORT = saved


if __name__ == "__main__":
    unittest.main()


class TestTtyAcmWithoutDriverLink(HardwareTestCase):
    """Regression: VK-162 wurde ohne lesbaren Treiber-Link als USB-Seriell/DCD eingestuft."""

    def test_ttyacm_is_never_dcd(self):
        self.host.usb_tty("ttyACM0", "", "1546", "01a7", "u-blox AG - www.u-blox.com",
                          "u-blox 7 - GPS/GNSS Receiver")
        rep = self.run_report(base_cfg(gps_enable=True))
        rec = rep["gps"]["receivers"][0]
        self.assertEqual(rec["pps_path"], "none")
        self.assertIn("kein PPS möglich", rec["verdict"])
        self.assertNotEqual(self.row(rep, "gps_pps")["status"], "limited")

    def test_pi_usb_stick_fix_is_marked_as_other_hardware(self):
        self.host.pi()
        self.host.usb_tty("ttyACM0", "cdc_acm", "1546", "01a7", "u-blox AG - www.u-blox.com",
                          "u-blox 7 - GPS/GNSS Receiver")
        row = self.row(self.run_report(base_cfg(gps_enable=True)), "gps_pps")
        self.assertEqual(row["status"], "no")
        if row["fix"]:
            self.assertIn("nicht mit einem USB-Stick", row["fix"])
