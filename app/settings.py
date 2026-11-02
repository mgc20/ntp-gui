"""Einstellungen: Schema, Validierung, Speicherung.

Jede Einstellung hat einen Standardwert, optional eine Umgebungsvariable und
optional einen Wert, der im Dashboard gespeichert wurde. Vorrang:

    im Dashboard gespeichert  >  Umgebungsvariable  >  Standardwert

Damit bleiben bestehende Compose-Dateien gültig (Env = Startwerte), und was
im Dashboard eingestellt wird, gewinnt. Gespeichert wird als JSON im Volume
von chrony (/var/lib/chrony), das in allen Compose-Vorlagen ohnehin
persistent ist.

Alles, was hier hereinkommt, landet später in chrony.conf/ptp4l.conf. Die
Validierung ist deshalb streng: keine Zeilenumbrüche, nur erlaubte Zeichen,
Optionen nur aus einer Positivliste. Ein Wert, der die Prüfung nicht besteht,
wird abgelehnt statt "repariert".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import tempfile
import threading
import time
from typing import Any, Callable

DATA_DIR = os.environ.get("NTPGUI_DATA_DIR", "/var/lib/chrony/ntp-gui")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Abschnitte in der Reihenfolge, in der das Dashboard sie zeigt.
SECTIONS = [
    ("ntp", "Zeitquellen (NTP)", "Woher dieser Server selbst seine Zeit bezieht."),
    ("lan", "Zeitserver für das LAN", "Wer diesen Server fragen darf und wie er antwortet."),
    ("nts", "NTS (Network Time Security)", "Kryptografisch abgesicherte Zeit – als Client und optional als Server."),
    ("dns", "DNS für ntp-gui", "Über welche DNS-Server ntp-gui selbst die Namen seiner Zeitquellen auflöst – "
            "gegen Schleifen, wenn der DNS im LAN Zeitserver-Namen auf ntp-gui umschreibt."),
    ("gps", "GPS / GNSS", "Ein GPS-Empfänger als eigene Referenzuhr (Stratum 0)."),
    ("ptp", "PTP (IEEE 1588)", "Präzisionszeit über das Netzwerk – braucht passende Hardware."),
    ("web", "Dashboard", "Darstellung, Verlauf und Zugriffsschutz."),
]

# Welche Dienste eine Änderung neu starten muss.
RESTART_SERVICES = "services"  # chronyd, gpsd, ptp4l, phc2sys
RESTART_NONE = "none"          # wirkt sofort im Dashboard


class ValidationError(ValueError):
    """Ein Wert hat die Prüfung nicht bestanden."""


# ---------------------------------------------------------------------------
# Validatoren
# ---------------------------------------------------------------------------

_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
                      r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$")
_DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9._/:+-]{1,200}$")
_IFACE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,15}$")
_SAFE_TEXT_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,120}$")
_REFID_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?([eE]-?\d+)?$")

# chrony-Optionen für server/pool/peer, die im Dashboard erlaubt sind.
# Wert = Anzahl erwarteter Zahlenargumente.
SOURCE_OPTIONS = {
    "iburst": 0, "burst": 0, "prefer": 0, "noselect": 0, "trust": 0, "require": 0,
    "nts": 0, "xleave": 0, "auto_offline": 0, "offline": 0, "copy": 0,
    "minpoll": 1, "maxpoll": 1, "presend": 1, "minstratum": 1, "polltarget": 1,
    "version": 1, "port": 1, "ntsport": 1, "maxdelay": 1, "maxdelayratio": 1,
    "maxdelaydevratio": 1, "mindelay": 1, "asymmetry": 1, "offset": 1, "filter": 1,
    "maxsamples": 1, "minsamples": 1, "maxsources": 1, "certset": 1,
}
# chrony-Optionen für refclock-Zeilen.
REFCLOCK_OPTIONS = {
    "noselect": 0, "prefer": 0, "trust": 0, "require": 0, "tai": 0, "pps": 0,
    "poll": 1, "dpoll": 1, "refid": 1, "lock": 1, "rate": 1, "minsamples": 1,
    "maxsamples": 1, "offset": 1, "delay": 1, "precision": 1, "maxdispersion": 1,
    "stratum": 1, "width": 1, "filter": 1, "maxlockage": 1,
}
# phc2sys-Kommandozeile: Schalter -> Anzahl Argumente.
# "-rr" ist die Kurzform von "-r -r" (Systemuhr darf auch QUELLE sein, siehe
# phc2sys(8)); als eigenes Wort erlaubt, weil man es so üblicherweise schreibt.
PHC2SYS_FLAGS = {
    "-a": 0, "-r": 0, "-rr": 0, "-m": 0, "-q": 0, "-z": 1, "-s": 1, "-c": 1, "-d": 1,
    "-O": 1, "-n": 1, "-N": 1, "-R": 1, "-L": 1, "-u": 1, "-w": 0, "-t": 1,
    "-E": 1, "-P": 1, "-I": 1, "-S": 1, "-F": 1, "-M": 1, "-C": 1, "-l": 1,
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ja"}:
        return True
    if text in {"0", "false", "no", "off", "nein", ""}:
        return False
    raise ValidationError(f"„{value}“ ist kein Ja/Nein-Wert")


def _as_number(kind: type, minimum=None, maximum=None) -> Callable[[Any], Any]:
    def convert(value: Any):
        if isinstance(value, bool):
            raise ValidationError("Zahl erwartet")
        try:
            number = kind(str(value).strip()) if not isinstance(value, (int, float)) else kind(value)
        except (TypeError, ValueError):
            raise ValidationError(f"„{value}“ ist keine gültige Zahl") from None
        if kind is float and (number != number or number in (float("inf"), float("-inf"))):
            raise ValidationError("Zahl erwartet")
        if minimum is not None and number < minimum:
            raise ValidationError(f"Mindestens {minimum}")
        if maximum is not None and number > maximum:
            raise ValidationError(f"Höchstens {maximum}")
        return number
    return convert


def _as_choice(*choices: str) -> Callable[[Any], str]:
    def convert(value: Any) -> str:
        text = str(value).strip()
        if text not in choices:
            raise ValidationError(f"Erlaubt: {', '.join(choices)}")
        return text
    return convert


def _as_text(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not _SAFE_TEXT_RE.match(text):
        raise ValidationError("Steuerzeichen oder zu lang (max. 120 Zeichen)")
    return text


def _as_device(optional: bool = True) -> Callable[[Any], str]:
    def convert(value: Any) -> str:
        text = str(value if value is not None else "").strip()
        if not text and optional:
            return ""
        if not _DEVICE_RE.match(text) or ".." in text:
            raise ValidationError("Gerätepfad muss mit /dev/ beginnen, z. B. /dev/ttyACM0")
        return text
    return convert


def _as_interface(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if text and not _IFACE_RE.match(text):
        raise ValidationError("Ungültiger Interface-Name, z. B. eth0 oder enp1s0")
    return text


def _as_host(value: Any) -> str:
    text = str(value).strip()
    try:
        ipaddress.ip_address(text)
        return text
    except ValueError:
        pass
    if not _HOST_RE.match(text):
        raise ValidationError(f"„{text}“ ist kein gültiger Hostname oder keine IP-Adresse")
    return text


# Erlaubte Orte für Zertifikat/Schlüssel des NTS-Servers. /config ist das
# Konfigurations-Volume, /certs der empfohlene Mount für Zertifikate eines
# Reverse Proxys (z. B. NPM: /data/letsencrypt bzw. /etc/letsencrypt, Zoraxy:
# conf/certs), /etc/letsencrypt für den direkten Certbot-Mount. Die Dateien
# werden für chronyd kopiert (siehe confgen.prepare_nts_files) – deshalb darf
# hier nicht jeder Pfad stehen, sonst ließe sich über das Dashboard z. B.
# /etc/shadow in ein für _chrony lesbares Verzeichnis kopieren.
NTS_CERT_ROOTS = ("/config/", "/certs/", "/etc/letsencrypt/")
_CERT_PATH_RE = re.compile(r"^/[A-Za-z0-9._@+,~/-]{1,250}$")


def cert_path_allowed(path: str) -> bool:
    """Absolut, unter NTS_CERT_ROOTS, ohne '..', ohne Leer-/Steuerzeichen."""
    if not isinstance(path, str) or not _CERT_PATH_RE.match(path):
        return False
    parts = path.split("/")
    if any(part in {"..", "."} for part in parts) or "//" in path or path.endswith("/"):
        return False
    return any(path.startswith(root) and len(path) > len(root) for root in NTS_CERT_ROOTS)


def _as_cert_path(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not cert_path_allowed(text):
        raise ValidationError(
            "Absoluter Pfad unter " + ", ".join(r.rstrip("/") for r in NTS_CERT_ROOTS)
            + " erwartet, ohne Leerzeichen und ohne „..“, z. B. /certs/live/npm-1/fullchain.pem")
    return text


def _as_public_name(value: Any) -> str:
    """Öffentlicher Name des NTP-Servers für ntsntpserver; leer = keiner."""
    text = str(value if value is not None else "").strip().rstrip(".").lower()
    if not text:
        return ""
    return _as_host(text)


_URL_PATH_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
_URL_PORT_RE = re.compile(r"^\d{1,5}$")


def http_url_ok(text: str, max_len: int = 300) -> bool:
    """http(s)-URL ohne Zugangsdaten, Leer- und Steuerzeichen, mit gültigem Host.

    Für Ziele ausgehender Verbindungen (Benachrichtigungen) und Links. Zugangsdaten
    in der URL („user:pass@“) sind verboten: Sie würden unmaskiert in der Oberfläche
    stehen – dafür gibt es eigene, maskierte Felder.
    """
    if not isinstance(text, str) or not text or len(text) > max_len:
        return False
    match = re.match(r"^(https?)://([^/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$", text)
    if not match:
        return False
    netloc, path = match.group(2), match.group(3)
    query, fragment = (match.group(4) or "")[1:], (match.group(5) or "")[1:]
    if "@" in netloc:
        return False
    if netloc.startswith("["):
        host, _, rest = netloc[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ("" if not rest else None)
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return False
    else:
        host, _, port = netloc.partition(":")
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            if not _HOST_RE.match(host):
                return False
    if port is None or (port and not (_URL_PORT_RE.match(port) and 0 < int(port) < 65536)):
        return False
    return all(_URL_PATH_RE.match(part) for part in (path, query, fragment))


def _as_link_url(value: Any) -> str:
    """Leer oder http(s)-URL (Adresse des Dashboards für Links in Benachrichtigungen)."""
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if not http_url_ok(text):
        raise ValidationError("http:// oder https:// mit Hostname bzw. IP, ohne Leerzeichen und ohne "
                              "Benutzer/Passwort, z. B. http://zeitserver.lan:8080/")
    return text


MAX_HOSTNAMES = 50


def _as_host_list(value: Any) -> list[str]:
    """Liste von DNS-Namen (keine IP-Adressen), klein geschrieben, ohne Dubletten."""
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value or ""))
    names: list[str] = []
    for item in items:
        text = str(item if item is not None else "").strip().rstrip(".").lower()
        if not text:
            continue
        try:
            ipaddress.ip_address(text)
        except ValueError:
            pass
        else:
            raise ValidationError(f"„{text}“ ist eine IP-Adresse – hier sind nur Namen sinnvoll, "
                                  "weil DNS-Umschreibung nur Namen umleiten kann")
        if not _HOST_RE.match(text) or "." not in text:
            raise ValidationError(f"„{text}“ ist kein gültiger Hostname (z. B. time.example.com)")
        if text not in names:
            names.append(text)
    if len(names) > MAX_HOSTNAMES:
        raise ValidationError(f"Höchstens {MAX_HOSTNAMES} Namen")
    return names


MAX_DNS_SERVERS = 8
_DNS_PORT_RE = re.compile(r"^\d{1,5}$")


def _list_items(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value or ""))
    return [str(item if item is not None else "").strip() for item in items if str(item or "").strip()]


def _dns_port(text: str) -> int:
    if not _DNS_PORT_RE.match(text) or not 0 < int(text) < 65536:
        raise ValidationError(f"„{text}“ ist kein gültiger Port")
    return int(text)


def _as_dns_servers(value: Any) -> list[str]:
    """DNS-Server als IP-Adresse, optional mit Port: 9.9.9.9, 9.9.9.9:5353, [2620:fe::fe]:53."""
    out: list[str] = []
    for item in _list_items(value):
        text, port = item, 53
        if item.startswith("["):
            host, _, rest = item[1:].partition("]")
            if rest and not rest.startswith(":"):
                raise ValidationError(f"„{item}“: IPv6 mit Port als [Adresse]:Port schreiben")
            text, port = host, (_dns_port(rest[1:]) if rest else 53)
        elif item.count(":") == 1:
            text, _, raw_port = item.partition(":")
            port = _dns_port(raw_port)
        try:
            addr = ipaddress.ip_address(text)
        except ValueError:
            raise ValidationError(f"„{item}“ ist keine IP-Adresse – hier nur Adressen, z. B. 9.9.9.9 "
                                  "(Namen bräuchten selbst wieder DNS)") from None
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped  # ::ffff:127.0.0.1 ist 127.0.0.1
        if addr.is_unspecified or addr.is_multicast:
            raise ValidationError(f"„{item}“ ist keine Unicast-Adresse")
        if addr.is_loopback and port == 53:
            raise ValidationError(f"„{item}“ zeigt auf den Weiterleiter von ntp-gui selbst (Loopback, Port 53) "
                                  "– das wäre eine Schleife")
        norm = str(addr) if port == 53 else (f"[{addr}]:{port}" if addr.version == 6 else f"{addr}:{port}")
        if norm not in out:
            out.append(norm)
    if len(out) > MAX_DNS_SERVERS:
        raise ValidationError(f"Höchstens {MAX_DNS_SERVERS} Server")
    return out


def _as_dot_servers(value: Any) -> list[str]:
    """DNS-over-TLS-Server als Name[:Port], z. B. dns.quad9.net oder one.one.one.one:853."""
    out: list[str] = []
    for item in _list_items(value):
        host, port = item.lower().rstrip("."), None
        if host.startswith("["):
            inner, _, rest = host[1:].partition("]")
            host, port = inner, (_dns_port(rest[1:]) if rest.startswith(":") else None)
        elif host.count(":") == 1:
            host, _, raw_port = host.partition(":")
            port = _dns_port(raw_port)
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            if not _HOST_RE.match(host) or "." not in host:
                raise ValidationError(f"„{item}“ ist kein gültiger Servername, z. B. dns.quad9.net") from None
            norm = host
        else:
            norm = f"[{addr}]" if addr.version == 6 else str(addr)
        if port and port != 853:
            norm = f"{norm}:{port}"
        if norm not in out:
            out.append(norm)
    if len(out) > MAX_DNS_SERVERS:
        raise ValidationError(f"Höchstens {MAX_DNS_SERVERS} Server")
    return out


def _as_doh_urls(value: Any) -> list[str]:
    """DNS-over-HTTPS-Adressen (RFC 8484), nur https://, z. B. https://dns.quad9.net/dns-query."""
    out: list[str] = []
    for item in _list_items(value):
        text = item[:-len("{?dns}")] if item.endswith("{?dns}") else item
        if not text.lower().startswith("https://") or not http_url_ok(text):
            raise ValidationError(f"„{item}“: https:// mit Servername und Pfad erwartet, ohne Benutzer/Passwort, "
                                  "z. B. https://dns.quad9.net/dns-query")
        if "#" in text:
            raise ValidationError(f"„{item}“: kein #-Anteil erlaubt")
        if text not in out:
            out.append(text)
    if len(out) > MAX_DNS_SERVERS:
        raise ValidationError(f"Höchstens {MAX_DNS_SERVERS} Server")
    return out


def _as_dns_pins(value: Any) -> list[str]:
    """Feste Adressen für DoT/DoH-Server: name=IP, z. B. dns.quad9.net=9.9.9.9."""
    out: list[str] = []
    for item in _list_items(value):
        name, sep, ip = item.partition("=")
        name = name.strip().lower().rstrip(".")
        if not sep or not _HOST_RE.match(name) or "." not in name:
            raise ValidationError(f"„{item}“: Format Name=IP, z. B. dns.quad9.net=9.9.9.9")
        try:
            addr = ipaddress.ip_address(ip.strip().strip("[]"))
        except ValueError:
            raise ValidationError(f"„{item}“: „{ip}“ ist keine IP-Adresse") from None
        if addr.is_unspecified or addr.is_multicast or addr.is_loopback:
            raise ValidationError(f"„{item}“: keine brauchbare Adresse")
        norm = f"{name}={addr}"
        if norm not in out:
            out.append(norm)
    if len(out) > 2 * MAX_DNS_SERVERS:
        raise ValidationError(f"Höchstens {2 * MAX_DNS_SERVERS} Einträge")
    return out


def _as_network_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value or ""))
    networks = []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        if item.lower() == "all":
            networks.append("all")
            continue
        try:
            networks.append(str(ipaddress.ip_network(item, strict=False)))
        except ValueError:
            raise ValidationError(f"„{item}“ ist kein Netz, z. B. 192.168.0.0/16") from None
    return networks


def _check_options(text: str, allowed: dict[str, int], what: str) -> str:
    tokens = str(text or "").split()
    index = 0
    while index < len(tokens):
        word = tokens[index]
        if word not in allowed:
            raise ValidationError(f"Unbekannte {what}-Option „{word}“")
        for offset in range(1, allowed[word] + 1):
            if index + offset >= len(tokens):
                raise ValidationError(f"„{word}“ braucht einen Wert")
            argument = tokens[index + offset]
            if word in {"refid", "lock"}:
                if not _REFID_RE.match(argument):
                    raise ValidationError(f"Ungültiger Wert für {word}")
            elif not _NUMBER_RE.match(argument):
                raise ValidationError(f"„{word}“ erwartet eine Zahl")
        index += allowed[word] + 1
    return " ".join(tokens)


def _as_source_options(value: Any) -> str:
    return _check_options(value, SOURCE_OPTIONS, "Quellen")


def _as_refclock_options(value: Any) -> str:
    return _check_options(value, REFCLOCK_OPTIONS, "Refclock")


def _as_pps_options(value: Any) -> str:
    """Wie refclock-Optionen, aber ohne die Werte, die ntp-gui selbst setzt."""
    text = _as_refclock_options(value)
    tokens = text.split()
    for word in ("refid", "lock", "poll"):
        if word in tokens:
            raise ValidationError(f"„{word}“ setzt ntp-gui selbst – bitte weglassen")
    return text


def _as_phc2sys_options(value: Any) -> str:
    tokens = str(value or "").split()
    index = 0
    while index < len(tokens):
        flag = tokens[index]
        if flag not in PHC2SYS_FLAGS:
            raise ValidationError(f"Unbekannter phc2sys-Schalter „{flag}“")
        for offset in range(1, PHC2SYS_FLAGS[flag] + 1):
            if index + offset >= len(tokens):
                raise ValidationError(f"„{flag}“ braucht einen Wert")
            argument = tokens[index + offset]
            if not re.match(r"^[A-Za-z0-9._/:-]{1,64}$", argument):
                raise ValidationError(f"Ungültiger Wert für {flag}")
        index += PHC2SYS_FLAGS[flag] + 1
    return " ".join(tokens)


def _as_makestep(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not re.match(r"^\d+(\.\d+)?\s-?\d+$", text):
        raise ValidationError("Format: Schwelle in Sekunden und Anzahl, z. B. „1.0 3“")
    return text


def _as_timezone(value: Any) -> str:
    text = str(value or "").strip()
    if text and not re.match(r"^[A-Za-z0-9_+/-]{1,64}$", text):
        raise ValidationError("Ungültige Zeitzone")
    return text


LEAPSECLIST_DEFAULT = "/usr/share/zoneinfo/leap-seconds.list"
LEAPSECLIST_ROOTS = ("/usr/share/zoneinfo/", "/config/")


def _as_leapseclist(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if (not re.match(r"^/[A-Za-z0-9_./+-]{1,200}$", text) or ".." in text
            or not text.startswith(LEAPSECLIST_ROOTS)):
        raise ValidationError("Pfad muss unter /usr/share/zoneinfo/ oder /config/ liegen")
    return text


_TEMP_SENSOR_RE = re.compile(r"^(auto|off|thermal:[A-Za-z0-9_.+-]{1,40}(:\d{1,2})?"
                             r"|hwmon:[A-Za-z0-9_.+-]{1,40}:temp\d{1,2}(:\d{1,2})?"
                             r"|w1:28-[0-9a-f]{12})$")


def _as_temp_sensor(value: Any) -> str:
    """„auto“, „off“ oder eine Kennung aus thermal.discover() – nie ein Pfad."""
    text = str(value if value is not None else "").strip() or "auto"
    if not _TEMP_SENSOR_RE.match(text):
        raise ValidationError("„auto“, „off“ oder eine Sensor-Kennung aus dem Hardware-Check "
                              "(z. B. thermal:cpu-thermal, hwmon:k10temp:temp1, w1:28-…)")
    return text


SOURCE_TYPES = ("server", "pool", "peer")


def _as_sources(value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise ValidationError("Liste von Zeitquellen erwartet")
    sources, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValidationError("Ungültiger Eintrag in der Quellenliste")
        host = str(raw.get("host", "")).strip()
        if not host:
            continue
        kind = str(raw.get("type", "server")).strip()
        if kind not in SOURCE_TYPES:
            raise ValidationError(f"Typ muss server, pool oder peer sein (bei {host})")
        entry = {
            "type": kind,
            "host": _as_host(host),
            "nts": _as_bool(raw.get("nts", False)),
            "prefer": _as_bool(raw.get("prefer", False)),
            "noselect": _as_bool(raw.get("noselect", False)),
            "options": _as_source_options(raw.get("options", "")),
        }
        if entry["prefer"] and entry["noselect"]:
            raise ValidationError(f"{host}: „bevorzugen“ und „nur beobachten“ schließen sich aus")
        if entry["nts"] and kind == "peer":
            raise ValidationError(f"{host}: NTS gibt es nur für server und pool")
        key = (kind, entry["host"].lower())
        if key in seen:
            raise ValidationError(f"{host} steht doppelt in der Liste")
        seen.add(key)
        sources.append(entry)
    if len(sources) > 32:
        raise ValidationError("Höchstens 32 Zeitquellen")
    return sources


def _env_sources(env: dict[str, str]) -> list[dict] | None:
    """Baut die Quellenliste aus den bisherigen Variablen NTP_POOLS/SERVERS/PEERS."""
    names = ("NTP_POOLS", "NTP_SERVERS", "NTP_PEERS", "NTP_NTS_SERVERS")
    if not any(name in env for name in names):
        return None
    sources = []
    for name, kind, nts in (("NTP_POOLS", "pool", False), ("NTP_SERVERS", "server", False),
                            ("NTP_NTS_SERVERS", "server", True), ("NTP_PEERS", "peer", False)):
        for host in re.split(r"[,\s]+", env.get(name, "") or ""):
            if host.strip():
                sources.append({"type": kind, "host": host.strip(), "nts": nts,
                                "prefer": False, "noselect": False, "options": ""})
    return sources


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

PRIVATE_NETWORKS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                    "fc00::/7", "fe80::/10"]


def _field(key, section, label, kind, default, convert, *, env=None, help="", options=None,
           advanced=False, restart=RESTART_SERVICES, unit=None, placeholder=None):
    return {
        "key": key, "section": section, "label": label, "type": kind, "default": default,
        "convert": convert, "env": env, "help": help, "options": options,
        "advanced": advanced, "restart": restart, "unit": unit, "placeholder": placeholder,
    }


SCHEMA: list[dict] = [
    # --- NTP-Quellen -------------------------------------------------------
    _field("ntp_sources", "ntp", "Zeitquellen", "sources",
           [{"type": "pool", "host": "pool.ntp.org", "nts": False, "prefer": False,
             "noselect": False, "options": ""}],
           _as_sources, env=None,
           help="Server, von denen dieser Zeitserver selbst die Zeit holt. „pool“ steht für "
                "mehrere Server hinter einem Namen (z. B. de.pool.ntp.org), „server“ für genau "
                "einen. Mit NTS werden die Antworten kryptografisch geprüft. „Bevorzugen“ macht "
                "eine Quelle zur ersten Wahl, „nur beobachten“ zeigt sie an, ohne sie zu nutzen."),
    _field("ntp_source_options", "ntp", "Optionen für alle Quellen", "text", "iburst",
           _as_source_options, env="NTP_SERVER_OPTIONS", advanced=True,
           help="chrony-Optionen, die an jede Quelle angehängt werden. „iburst“ schickt beim "
                "Start vier schnelle Anfragen, damit die erste Synchronisation Sekunden statt "
                "Minuten dauert."),
    _field("ntp_pool_maxsources", "ntp", "Server je Pool", "int", 4,
           _as_number(int, 1, 16), env="NTP_POOL_MAXSOURCES", advanced=True,
           help="Wie viele Server chrony aus einem Pool-Namen gleichzeitig nutzt."),
    _field("ntp_minsources", "ntp", "Mindestens übereinstimmende Quellen", "int", 1,
           _as_number(int, 1, 8), env="NTP_MINSOURCES",
           help="Erst wenn so viele Quellen dieselbe Zeit nennen, stellt chrony die Uhr. "
                "2 oder 3 schützt davor, dass eine einzelne falsche Quelle die Zeit verbiegt – "
                "braucht dann aber auch so viele erreichbare Quellen."),
    _field("makestep", "ntp", "Uhr springen lassen", "text", "1.0 3", _as_makestep,
           env="MAKESTEP", advanced=True,
           help="Normalerweise wird die Uhr sanft nachgeregelt. Ist sie beim Start um mehr als "
                "die Schwelle (Sekunden) daneben, darf chrony in den ersten N Messungen "
                "springen. Wichtig für Geräte ohne Echtzeituhr wie den Raspberry Pi."),
    _field("leapseclist", "ntp", "Schaltsekunden-Liste", "text", LEAPSECLIST_DEFAULT,
           _as_leapseclist, env="LEAPSECLIST", advanced=True,
           help="Woher chrony bevorstehende Schaltsekunden kennt: die Liste der IERS aus dem "
                "Paket tzdata. Standard ist richtig; leer schaltet die Ankündigung ab."),
    _field("leapsectz", "ntp", "Schaltsekunden-Zeitzone (alt)", "text", "", _as_timezone,
           env="LEAPSECTZ", advanced=True,
           help="Nur für eigene Images mit „right/“-Zeitzonen. Leer lassen – seit 1.3.1 "
                "gilt die Schaltsekunden-Liste. Ist die Zone im Image nicht vorhanden, wird "
                "die Liste genommen."),

    # --- LAN-Server --------------------------------------------------------
    _field("allow_networks", "lan", "Erlaubte Netze", "networks", PRIVATE_NETWORKS,
           _as_network_list, env="ALLOW_NETWORKS",
           help="Nur Geräte aus diesen Netzen bekommen eine Antwort. Standard: alle privaten "
                "Netze (10.x, 172.16–31.x, 192.168.x, IPv6 ULA und Link-Local). „all“ erlaubt "
                "jedem – nur sinnvoll, wenn eine Firewall davor sitzt."),
    _field("deny_networks", "lan", "Ausgenommene Netze", "networks", [], _as_network_list,
           env="DENY_NETWORKS", advanced=True,
           help="Netze innerhalb der erlaubten, die trotzdem keine Antwort bekommen, z. B. ein "
                "Gäste-WLAN."),
    _field("serve_unsynced", "lan", "Auch ohne Quelle Zeit ausliefern", "bool", True, _as_bool,
           env="SERVE_UNSYNCED",
           help="Inselbetrieb: Ist keine Quelle erreichbar, liefert der Server trotzdem die "
                "eigene Uhrzeit aus (mit hohem Stratum, damit Clients sie als zweite Wahl "
                "erkennen). Hält das LAN einheitlich, auch wenn das Internet ausfällt."),
    _field("local_stratum", "lan", "Stratum im Inselbetrieb", "int", 10,
           _as_number(int, 1, 15), env="LOCAL_STRATUM", advanced=True,
           help="Wie „weit weg“ von einer echten Referenz sich der Server im Inselbetrieb "
                "ausgibt. 10 ist üblich und sorgt dafür, dass echte Server Vorrang behalten."),
    _field("local_orphan", "lan", "Orphan-Modus (zwei Server im Verbund)", "bool", False, _as_bool,
           env="LOCAL_ORPHAN", advanced=True,
           help="Für zwei (oder mehr) ntp-gui-Server, die sich gegenseitig als Quelle eingetragen "
                "haben (Typ „peer“ oder „server“). Fällt das Internet aus, einigen sie sich so auf "
                "EINE gemeinsame Inselzeit, statt dass jeder seine eigene ausliefert: Es übernimmt "
                "der Server mit der kleinsten Referenz-ID, der andere folgt ihm. Hängt „orphan“ an "
                "die Zeile „local stratum …“ an und wirkt deshalb nur zusammen mit „Auch ohne "
                "Quelle Zeit ausliefern“. Beide Server brauchen dasselbe Stratum im Inselbetrieb."),
    _field("ntp_ratelimit", "lan", "Anfragen begrenzen", "bool", False, _as_bool,
           env="NTP_RATELIMIT", advanced=True,
           help="Begrenzt, wie oft ein einzelner Client fragen darf. Schützt vor fehlerhaften "
                "Geräten, die im Sekundentakt fragen. Im Heimnetz meist unnötig."),
    _field("ntp_port", "lan", "NTP-Port", "int", 123, _as_number(int, 1, 65535),
           env="NTP_PORT", advanced=True,
           help="Standard ist 123. Nur ändern, wenn Clients einen anderen Port erwarten."),
    _field("bind_address", "lan", "Nur auf dieser Adresse lauschen", "text", "", _as_text,
           env="BIND_ADDRESS", advanced=True, placeholder="alle Adressen",
           help="Leer lassen, um auf allen Adressen des Hosts zu antworten."),
    _field("ntp_hw_timestamp", "lan", "Hardware-Zeitstempel für NTP", "bool", False, _as_bool,
           env="NTP_HW_TIMESTAMP", advanced=True,
           help="Lässt die Netzwerkkarte die Zeitstempel der NTP-Pakete setzen statt des "
                "Kernels. Bringt nur mit Host-Netzwerk und einer NIC mit Hardware-Zeitstempeln "
                "etwas (siehe PTP-Seite)."),
    _field("ntp_hw_timestamp_interface", "lan", "Interface für Hardware-Zeitstempel", "text", "*",
           lambda v: "*" if str(v).strip() in {"", "*"} else _as_interface(v),
           env="NTP_HW_TIMESTAMP_INTERFACE", advanced=True,
           help="„*“ für alle Interfaces, die es können."),
    _field("clientmon_enable", "lan", "Uhren der Clients beobachten", "bool", True, _as_bool,
           env="CLIENTMON", restart=RESTART_NONE,
           help="Schätzt aus den NTP-Anfragen, wie weit die Uhr jedes Geräts im LAN "
                "danebenliegt – rein passiv, es wird nichts an die Geräte gesendet. So siehst "
                "du, welche Geräte deinen Server wirklich nutzen und ob ihre Uhr stimmt. Die "
                "Werte bleiben auf dieser Instanz. Wirkt ohne Neustart."),
    _field("clients_alarm_ms", "lan", "Alarm, wenn eine Client-Uhr abweicht", "int", 0,
           _as_number(int, 0, 86_400_000), env="CLIENTS_ALARM_MS", restart=RESTART_NONE,
           advanced=True, unit="ms", placeholder="0 = aus",
           help="Ab dieser Abweichung (in Millisekunden) schreibt ntp-gui ein Ereignis „Uhr von … "
                "weicht um … ab“ – das kann eine Benachrichtigung auslösen. Zählt erst, wenn zwei "
                "Messungen hintereinander darüber liegen; „wieder im Rahmen“ meldet es erst unter "
                "der Hälfte der Schwelle, damit ein Gerät an der Grenze nicht ständig hin und her "
                "meldet. 0 = aus. Sinnvoll sind etwa 1000 ms (Uhr geht eine Sekunde falsch)."),
    _field("clients_rdns", "lan", "Namen der Clients per DNS nachschlagen", "bool", False, _as_bool,
           env="CLIENTS_RDNS", restart=RESTART_NONE, advanced=True,
           help="Zeigt auf der Detailseite eines Geräts seinen Namen aus dem DNS (Reverse-DNS, "
                "z. B. „nas.fritz.box“). Standard: aus – die Frage verrät die Adresse deines Geräts "
                "an den DNS-Server. Eingeschaltet fragt ntp-gui nur nach privaten LAN-Adressen, nur "
                "beim Öffnen der Detailseite und nur, wenn jeder DNS-Server, über den die Frage gehen "
                "kann, selbst eine private Adresse hat (System-DNS aus /etc/resolv.conf bzw. eigene "
                "Server samt Rückfall). Bei DoT/DoH oder einem öffentlichen Server (Docker trägt z. B. "
                "8.8.8.8 ein) wird nicht gefragt. Ein lokaler Zwischen-Resolver (127.0.0.53, "
                "127.0.0.11) zählt als privat – wohin er weiterfragt, kann ntp-gui nicht sehen. "
                "Der Name bleibt auf dieser Instanz."),
    _field("enforce_hostnames", "lan", "Weitere Namen für „Zeitserver erzwingen“", "hostlist",
           [], _as_host_list, env="ENFORCE_HOSTNAMES", restart=RESTART_NONE, advanced=True,
           placeholder="z. B. time.example.com",
           help="Zusätzliche Zeitserver-Namen, die die Anleitungen zum Erzwingen (DNS-"
                "Umschreibung in AdGuard, Pi-hole, dnsmasq) auf diesen Server umleiten sollen – "
                "etwa der fest eingetragene Server einer Kamera oder eines Fernsehers. Die "
                "üblichen Namen (pool.ntp.org, time.windows.com, time.apple.com …) sind schon "
                "enthalten. Mehrere Namen mit Komma oder Zeilenumbruch trennen."),

    # --- NTS ---------------------------------------------------------------
    _field("nts_nocerttimecheck", "nts", "Zertifikatszeit beim Start nicht prüfen", "bool", True,
           _as_bool, env="NTS_NOCERTTIMECHECK",
           help="NTS prüft TLS-Zertifikate – dafür muss die Uhr ungefähr stimmen. Ein "
                "Raspberry Pi ohne Echtzeituhr startet aber mit falscher Zeit. Diese Option "
                "erlaubt beim allerersten Abgleich eine Ausnahme. Danach wird normal geprüft."),
    _field("nts_server_enable", "nts", "NTS-Server für das LAN anbieten", "bool", False, _as_bool,
           env="NTS_SERVER", advanced=True,
           help="Bietet NTS auch den eigenen Clients an. Braucht ein TLS-Zertifikat, dem die "
                "Clients vertrauen, und Clients, die NTS sprechen (chrony, NTPsec – Windows "
                "und macOS können es nicht). Port 4460/tcp muss erreichbar sein."),
    _field("nts_server_cert", "nts", "Zertifikat (PEM)", "text", "/config/nts.crt", _as_cert_path,
           env="NTS_SERVER_CERT", advanced=True,
           help="Pfad zum Zertifikat im Container – unter /config, /certs oder /etc/letsencrypt. "
                "Am besten die volle Kette (fullchain), damit Clients auch das Zwischenzertifikat "
                "bekommen. Zertifikate eines Reverse Proxys lassen sich direkt nutzen: den "
                "Zertifikatsordner von Nginx Proxy Manager (z. B. …/letsencrypt/live/npm-1/"
                "fullchain.pem) oder Zoraxy (conf/certs/<domain>.pem) schreibgeschützt nach "
                "/certs mounten. Ändert sich die Datei (Erneuerung), startet chronyd automatisch "
                "neu, weil chrony Zertifikate nur beim Start liest."),
    _field("nts_server_key", "nts", "Privater Schlüssel (PEM)", "text", "/config/nts.key", _as_cert_path,
           env="NTS_SERVER_KEY", advanced=True,
           help="Pfad zum zugehörigen privaten Schlüssel, z. B. …/live/npm-1/privkey.pem (NPM) "
                "oder conf/certs/<domain>.key (Zoraxy). ntp-gui kopiert Zertifikat und Schlüssel "
                "beim Start in ein Verzeichnis, das nur chronyd lesen darf – die Originale dürfen "
                "also root gehören."),
    _field("nts_server_name", "nts", "Öffentlicher Name des Servers", "text", "", _as_public_name,
           env="NTS_SERVER_NAME", advanced=True, placeholder="kein eigener Name",
           help="Der Name, unter dem Clients diesen Server erreichen, z. B. time.example.com – "
                "er muss im Zertifikat stehen. Gesetzt teilt chrony ihn den Clients nach dem "
                "Schlüsselaustausch mit (ntsntpserver), und sie schicken ihre NTP-Pakete an "
                "diesen Namen. Wichtig hinter einem Reverse Proxy: Ohne Namen gehen die "
                "NTP-Pakete an die Adresse, mit der der Schlüsselaustausch lief – also an den "
                "Proxy, der UDP 123 meist gar nicht weiterreicht."),
    _field("nts_server_port", "nts", "NTS-KE-Port (TCP)", "int", 4460, _as_number(int, 1, 65535),
           env="NTS_SERVER_PORT", advanced=True,
           help="Auf diesem TCP-Port nimmt chrony den TLS-Schlüsselaustausch (NTS-KE) an. "
                "Standard ist 4460 – Clients erwarten ihn dort. Nur ändern, wenn ein Reverse "
                "Proxy außen 4460 annimmt und intern an einen anderen Port weiterreicht."),

    # --- DNS für ntp-gui ----------------------------------------------------
    _field("dns_mode", "dns", "DNS für ntp-gui", "select", "system",
           _as_choice("system", "servers", "dot", "doh"), env="DNS_MODE",
           options=[("system", "System-DNS des Containers (Standard)"),
                    ("servers", "Eigene DNS-Server (klassisches DNS)"),
                    ("dot", "DNS-over-TLS (DoT)"), ("doh", "DNS-over-HTTPS (DoH)")],
           help="Woher ntp-gui selbst Namen wie pool.ntp.org auflöst. „System-DNS“ ändert nichts. "
                "Die anderen Modi starten einen kleinen Weiterleiter auf 127.0.0.1 im Container und "
                "stellen /etc/resolv.conf darauf um – chronyd, NTS und die Prüfung „Zeitserver erzwingen“ "
                "fragen dann deine Server statt des DNS im LAN. Wichtig, wenn AdGuard Home oder Pi-hole "
                "Zeitserver-Namen auf ntp-gui umschreibt: Sonst fragt chronyd sich selbst. DoT und DoH "
                "laufen verschlüsselt über 853/tcp bzw. 443/tcp und sind damit auch von einer "
                "DNS-Umleitung per Firewall (Port 53) nicht betroffen. Steht in der Compose-Datei "
                "„dns: 127.0.0.1“, gibt es keinen System-DNS mehr: Dann bei DoT/DoH die Server unter "
                "„Feste Adressen“ eintragen oder „Eigene DNS-Server“ mit IP-Adressen nehmen."),
    _field("dns_servers", "dns", "DNS-Server (IP-Adressen)", "hostlist", [], _as_dns_servers,
           env="DNS_SERVERS", placeholder="z. B. 9.9.9.9 oder 1.1.1.1",
           help="Für den Modus „Eigene DNS-Server“: IP-Adressen, optional mit Port (9.9.9.9:53, "
                "[2620:fe::fe]:53). Nur Adressen, keine Namen – die bräuchten selbst wieder DNS. "
                "Der Reihe nach gefragt; antwortet einer nicht, kommt der nächste dran. Achtung: "
                "Leitet die Firewall Port 53 auf AdGuard/Pi-hole um, braucht ntp-gui dort eine Ausnahme "
                "– oder du nimmst DoT/DoH."),
    _field("dns_dot", "dns", "DNS-over-TLS-Server", "hostlist", [], _as_dot_servers,
           env="DNS_DOT", placeholder="z. B. dns.quad9.net",
           help="Für den Modus DoT: Servername, optional mit Port (Standard 853), z. B. dns.quad9.net, "
                "one.one.one.one oder dns.digitale-gesellschaft.ch. Das Zertifikat wird gegen die "
                "Zertifizierungsstellen des Systems und den Namen geprüft. Die Adresse des Servers "
                "ermittelt ntp-gui über den System-DNS – oder du trägst sie unter „Feste Adressen“ "
                "ein. Pflicht bei „dns: 127.0.0.1“ in der Compose-Datei: Dann fragte der System-DNS "
                "wieder ntp-gui selbst, und der Name bliebe unauflösbar."),
    _field("dns_doh", "dns", "DNS-over-HTTPS-Adressen", "hostlist", [], _as_doh_urls,
           env="DNS_DOH", placeholder="z. B. https://dns.quad9.net/dns-query",
           help="Für den Modus DoH: vollständige https-Adresse nach RFC 8484, z. B. "
                "https://dns.quad9.net/dns-query oder https://cloudflare-dns.com/dns-query. ntp-gui "
                "schickt die Anfrage per POST, folgt keiner Weiterleitung und nutzt keinen Proxy. Steht "
                "im Pfad eine Konto-Kennung (z. B. NextDNS), zeigen Status, Ereignisse, Diagnose und "
                "API-Schlüssel mit Leserecht nur den Servernamen. Bei „dns: 127.0.0.1“ in der "
                "Compose-Datei den Servernamen unter „Feste Adressen“ eintragen – sonst ist er "
                "nicht auflösbar."),
    _field("dns_pin", "dns", "Feste Adressen für DoT/DoH", "hostlist", [], _as_dns_pins,
           env="DNS_PIN", advanced=True, placeholder="z. B. dns.quad9.net=9.9.9.9",
           help="Optional, je Zeile Name=IP, z. B. dns.quad9.net=9.9.9.9. Dann fragt ntp-gui für den "
                "Verbindungsaufbau keinen System-DNS – sinnvoll, wenn der DNS im LAN unzuverlässig ist "
                "oder selbst umgeleitet wird. Das Zertifikat wird weiter gegen den Namen geprüft."),
    _field("dns_fallback", "dns", "Rückfall auf den System-DNS", "bool", True, _as_bool,
           env="DNS_FALLBACK", advanced=True,
           help="Antwortet keiner deiner Server, fragt ntp-gui den ursprünglichen DNS des Containers "
                "und meldet das als Ereignis – lieber eine Antwort mit Schleifenrisiko als gar keine "
                "Zeitquelle. Aus: Dann bleibt die Anfrage unbeantwortet, und nichts geht unverschlüsselt "
                "hinaus – sinnvoll, wenn DoT/DoH aus Datenschutzgründen gewählt ist."),

    # --- GPS ---------------------------------------------------------------
    _field("gps_enable", "gps", "GPS verwenden", "bool", False, _as_bool, env="GPS_ENABLE",
           help="Startet gpsd und trägt den Empfänger als Referenzuhr in chrony ein."),
    _field("gps_device", "gps", "Gerät", "device", "/dev/ttyACM0", _as_device(optional=False),
           env="GPS_DEVICE",
           help="Der serielle Port des Empfängers. USB-Empfänger wie der VK-162 erscheinen als "
                "/dev/ttyACM0, am Raspberry-Pi-UART meist /dev/ttyAMA0. Das Gerät muss per "
                "„devices:“ in den Container gereicht werden."),
    _field("gps_offset", "gps", "Offset (Korrektur)", "float", 0.0, _as_number(float, -2.0, 2.0),
           env="GPS_OFFSET", unit="s",
           help="Gleicht die feste Verspätung aus, mit der ein Empfänger die Zeit meldet. Bei "
                "USB-Empfängern typisch 0,02–0,15 s. Den richtigen Wert misst der "
                "Kalibrier-Assistent auf der GPS-Seite."),
    _field("gps_delay", "gps", "Angenommene Unsicherheit (Delay)", "float", 0.2,
           _as_number(float, 0.0001, 1.0), env="GPS_DELAY", unit="s",
           help="Wie stark chrony dem GPS misstraut. 0,2 s ist vorsichtig für unkalibrierte "
                "Empfänger. Je kleiner, desto eher wird das GPS gegenüber Internet-Servern "
                "gewählt. Nach der Kalibrierung schlägt der Assistent einen passenden Wert vor."),
    _field("gps_select", "gps", "Rolle bei der Quellenauswahl", "select", "auto",
           _as_choice("auto", "prefer", "noselect"), env="GPS_SELECT",
           options=[("auto", "automatisch – chrony entscheidet"),
                    ("prefer", "bevorzugen – GPS ist erste Wahl"),
                    ("noselect", "nur beobachten – nie zur Synchronisation")],
           help="„Bevorzugen“ macht das GPS zur Hauptquelle, solange es plausibel ist. "
                "„Nur beobachten“ ist praktisch zum Kalibrieren."),
    _field("gps_pps_device", "gps", "PPS-Gerät", "device", "", _as_device(optional=True),
           env="GPS_PPS_DEVICE", placeholder="kein PPS",
           help="Ein echter Sekundenimpuls (z. B. /dev/pps0 über GPIO am Raspberry Pi). "
                "Macht die Zeit tausendfach genauer. Der VK-162 hat keinen PPS-Ausgang."),
    _field("gps_pps_poll", "gps", "PPS-Abfrageintervall (2^n s)", "int", 3,
           _as_number(int, -4, 6), env="GPS_PPS_POLL", advanced=True,
           help="Wie oft chrony die gesammelten PPS-Pulse auswertet: 3 bedeutet alle 8 Sekunden "
                "(aus 8 Pulsen). Kleiner reagiert schneller, größer glättet stärker."),
    _field("gps_pps_options", "gps", "Weitere PPS-Optionen", "text", "", _as_pps_options,
           env="GPS_PPS_OPTIONS", advanced=True,
           help="Zusätzliche chrony-Optionen für die PPS-Zeile, z. B. „prefer“, „trust“ oder "
                "„offset 0.0000025“ (Laufzeit des Antennenkabels/Pegelwandlers). Gilt für ein "
                "/dev/pps-Gerät und für PPS über gpsd. Erlaubt sind nur bekannte refclock-Optionen."),
    _field("gps_pps_shm", "gps", "PPS über gpsd", "bool", False, _as_bool, env="GPS_PPS_SHM",
           advanced=True,
           help="Nutzt den PPS, den gpsd selbst erkennt (z. B. über die DCD-Leitung eines "
                "seriellen Adapters), statt eines /dev/pps-Geräts."),
    _field("gps_speed", "gps", "Baudrate", "text", "", lambda v: _check_digits(v),
           env="GPS_SPEED", advanced=True, placeholder="automatisch",
           help="Nur für serielle Empfänger mit fester Geschwindigkeit nötig. USB-Empfänger "
                "erkennt gpsd selbst."),
    _field("gps_poll", "gps", "Abfrageintervall (2^n s)", "int", 3, _as_number(int, -4, 6),
           env="GPS_POLL", advanced=True,
           help="Wie oft chrony die GPS-Zeit übernimmt: 3 bedeutet alle 8 Sekunden."),
    _field("gps_filter", "gps", "Medianfilter", "int", 3, _as_number(int, 0, 64),
           env="GPS_FILTER", advanced=True,
           help="Aus so vielen Rohwerten nimmt chrony den Median – glättet USB-Ausreißer."),
    _field("gps_precision", "gps", "Auflösung", "float", 0.1, _as_number(float, 1e-9, 1.0),
           env="GPS_PRECISION", unit="s", advanced=True,
           help="Wie fein die NMEA-Zeitangabe ist. 0,1 s ist vorsichtig; kalibriert passt 0,001."),
    _field("gps_refid", "gps", "Name in der Quellenliste", "text", "GPS",
           lambda v: _check_refid(v), env="GPS_REFID", advanced=True,
           help="Bis zu vier Zeichen, z. B. GPS oder NMEA."),
    _field("gps_refclock_options", "gps", "Weitere Refclock-Optionen", "text", "",
           _as_refclock_options, env="GPS_REFCLOCK_OPTIONS", advanced=True,
           help="Zusätzliche chrony-Optionen für die GPS-Zeile, z. B. „trust“."),
    _field("gps_show_position", "gps", "Position anzeigen", "bool", False, _as_bool,
           env="GPS_SHOW_POSITION", restart=RESTART_NONE,
           help="Zeigt Koordinaten im Dashboard und in der API. Standardmäßig aus, weil die "
                "Position den Standort verrät."),
    _field("gps_autocal", "gps", "Automatische Kalibrierung", "select", "suggest",
           _as_choice("off", "suggest", "auto"), env="GPS_AUTOCAL", restart=RESTART_NONE,
           options=[("off", "aus – nichts vorschlagen, nichts ändern"),
                    ("suggest", "vorschlagen – du entscheidest per Klick"),
                    ("auto", "automatisch – behutsam selbst nachstellen")],
           help="USB-GPS-Empfänger liefern die Zeit (NMEA) mit einer festen Verspätung von "
                "typisch 20–150 ms. ntp-gui misst sie laufend gegen deine Netzwerkquellen. "
                "„Vorschlagen“ zeigt dir den passenden Offset, du übernimmst ihn selbst. "
                "„Automatisch“ stellt ihn nach, aber nur in kleinen Schritten, nur nach genug "
                "Messdauer und mit Eintrag im Ereignisprotokoll – jede Änderung lässt sich "
                "dort zurücknehmen. Wirkt ohne Neustart; erst das Übernehmen eines neuen "
                "Offsets startet chronyd neu."),
    _field("gps_autocal_max_step_ms", "gps", "Größter Kalibrierschritt", "float", 5.0,
           _as_number(float, 0.1, 50.0), env="GPS_AUTOCAL_MAX_STEP_MS", unit="ms",
           restart=RESTART_NONE, advanced=True,
           help="So weit darf die automatische Kalibrierung den Offset auf einmal "
                "verschieben. Kleine Schritte sind sicherer: Liegt eine Messung daneben "
                "(z. B. weil eine Netzwerkquelle selbst falsch geht), richtet sie wenig "
                "Schaden an und wird beim nächsten Durchgang korrigiert."),
    _field("gps_autocal_min_hours", "gps", "Mindest-Messdauer vor dem Kalibrieren", "float", 6.0,
           _as_number(float, 0.5, 168.0), env="GPS_AUTOCAL_MIN_HOURS", unit="h",
           restart=RESTART_NONE, advanced=True,
           help="Wie lange GPS und Netzwerkquellen gemeinsam gemessen haben müssen, bevor "
                "ein Offset vorgeschlagen oder übernommen wird. Mehrere Stunden glätten "
                "Tagesschwankungen der Netzlaufzeit – darum ist das Ergebnis dann belastbar."),

    # --- PTP ---------------------------------------------------------------
    _field("ptp_enable", "ptp", "PTP verwenden", "bool", False, _as_bool, env="PTP_ENABLE",
           help="Startet ptp4l. Setzt Host-Netzwerk voraus (network_mode: host) und für echte "
                "Präzision eine Netzwerkkarte mit Hardware-Zeitstempeln – die PTP-Seite prüft das."),
    _field("ptp_interface", "ptp", "Netzwerk-Interface", "interface", "", _as_interface,
           env="PTP_INTERFACE",
           help="Das Interface, über das PTP läuft, z. B. eth0 oder enp1s0."),
    _field("ptp_mode", "ptp", "Rolle", "select", "auto", _as_choice("auto", "master", "slave"),
           env="PTP_MODE",
           options=[("auto", "automatisch – der beste Takt im Netz wird Grandmaster"),
                    ("master", "Grandmaster – dieser Server gibt den Takt vor"),
                    ("slave", "Slave – übernimmt die Zeit eines anderen Grandmasters")],
           help="Mit GPS ist „Grandmaster“ richtig: chrony stellt die Systemuhr nach GPS, "
                "phc2sys überträgt sie auf die PTP-Uhr der Netzwerkkarte und ptp4l verteilt sie. "
                "„Slave“ passt, wenn es im Netz schon einen besseren Grandmaster gibt – dann "
                "stellt phc2sys umgekehrt die Systemuhr nach PTP. „Automatisch“ verhält sich "
                "beim Uhrenstellen wie „Slave“; wer GPS-Zeit per PTP verteilen will, wählt "
                "deshalb ausdrücklich „Grandmaster“."),
    _field("ptp_profile", "ptp", "Profil", "select", "default",
           _as_choice("default", "aes67", "gptp"), env="PTP_PROFILE",
           options=[("default", "Standard (IEEE 1588 Default-Profil)"),
                    ("aes67", "AES67 / Ravenna (Audio über IP, Media-Profil)"),
                    ("gptp", "gPTP / IEEE 802.1AS (AVB/TSN, Automotive)")],
           help="Ein Profil legt passende Grundwerte fest, damit dieser Server mit bestimmten "
                "Geräten zusammenspielt. Felder, die du selbst änderst, haben Vorrang. AES67: "
                "UDPv4, End-to-End, 8 Sync/s, Announce alle 2 s und DSCP 46 (EF) für die "
                "Pakete. gPTP: Ethernet direkt (L2), Peer-to-Peer, transportSpecific 1, "
                "Priority 248 und die übrigen Werte aus linuxptp configs/gPTP.cfg – alle "
                "Switches im Weg müssen 802.1AS beherrschen."),
    _field("ptp_domain", "ptp", "Domain", "int", 0, _as_number(int, 0, 255), env="PTP_DOMAIN",
           help="Getrennte PTP-Netze im selben LAN. Alle Teilnehmer brauchen dieselbe Domain; "
                "0 ist der Standard."),
    _field("ptp_transport", "ptp", "Transport", "select", "UDPv4",
           _as_choice("UDPv4", "UDPv6", "L2"), env="PTP_TRANSPORT",
           options=[("UDPv4", "UDP über IPv4 (Standard)"), ("UDPv6", "UDP über IPv6"),
                    ("L2", "Ethernet direkt (Layer 2)")],
           help="Alle Teilnehmer müssen denselben Transport nutzen. UDPv4 funktioniert fast "
                "überall."),
    _field("ptp_time_stamping", "ptp", "Zeitstempel", "select", "hardware",
           _as_choice("hardware", "software"), env="PTP_TIME_STAMPING",
           options=[("hardware", "Hardware – Nanosekunden, braucht passende NIC"),
                    ("software", "Software – funktioniert überall, Mikrosekunden")],
           help="Mit Software-Zeitstempeln läuft PTP auf jeder Karte, ist dann aber nicht "
                "genauer als gutes NTP."),
    _field("ptp_delay_mechanism", "ptp", "Laufzeitmessung", "select", "E2E",
           _as_choice("E2E", "P2P", "Auto"), env="PTP_DELAY_MECHANISM", advanced=True,
           options=[("E2E", "End-to-End (Standard)"), ("P2P", "Peer-to-Peer"),
                    ("Auto", "automatisch")],
           help="E2E passt für normale Netze. P2P nur, wenn alle Switches es unterstützen."),
    _field("ptp_priority1", "ptp", "Priority 1", "int", 128, _as_number(int, 0, 255),
           env="PTP_PRIORITY1", advanced=True,
           help="Kleinere Zahl = eher Grandmaster. Zum Erzwingen z. B. 100 setzen."),
    _field("ptp_priority2", "ptp", "Priority 2", "int", 128, _as_number(int, 0, 255),
           env="PTP_PRIORITY2", advanced=True,
           help="Gleichstandsentscheidung nach Priority 1."),
    _field("ptp_clock_class", "ptp", "Clock Class", "int", 248, _as_number(int, 0, 255),
           env="PTP_CLOCK_CLASS", advanced=True,
           help="Wie gut der eigene Takt ist (IEEE 1588): 6 = an eine primäre Referenz wie GPS "
                "gekoppelt, 7 = gerade Holdover (Referenz verloren, läuft noch genau weiter), 248 = "
                "Standard/unbekannt. Dieser Wert gilt beim Start von ptp4l. Als Grandmaster führt "
                "ntp-gui die Angabe danach selbst nach dem Zustand von chrony nach: 6 erst, wenn "
                "chrony stabil an GPS mit PPS hängt, 7 für eine Weile nach dem Verlust, sonst 248."),
    _field("ptp_log_sync_interval", "ptp", "Sync-Intervall (2^n s)", "int", -3,
           _as_number(int, -7, 4), env="PTP_LOG_SYNC_INTERVAL", advanced=True,
           help="-3 bedeutet 8 Sync-Nachrichten pro Sekunde."),
    _field("ptp_log_announce_interval", "ptp", "Announce-Intervall (2^n s)", "int", 1,
           _as_number(int, -3, 4), env="PTP_LOG_ANNOUNCE_INTERVAL", advanced=True,
           help="Wie oft der Grandmaster sich ankündigt: 1 bedeutet alle 2 Sekunden. Alle "
                "Teilnehmer sollten denselben Wert nutzen, sonst halten Slaves den Master "
                "fälschlich für weg."),
    _field("ptp_announce_receipt_timeout", "ptp", "Announce-Timeout (Anzahl)", "int", 3,
           _as_number(int, 2, 10), env="PTP_ANNOUNCE_RECEIPT_TIMEOUT", advanced=True,
           help="Nach so vielen verpassten Announce-Nachrichten gilt der Master als ausgefallen "
                "und die Auswahl beginnt neu."),
    _field("ptp_log_min_delay_req_interval", "ptp", "Delay-Request-Intervall (2^n s)", "int", -3,
           _as_number(int, -7, 6), env="PTP_LOG_MIN_DELAY_REQ_INTERVAL", advanced=True,
           help="Wie oft Slaves die Laufzeit zum Master messen dürfen (-3 = 8 pro Sekunde). "
                "Als Master gibt dieser Server den Wert an die Slaves weiter."),
    _field("ptp_summary_interval", "ptp", "Log-Zusammenfassung (2^n s)", "int", 4,
           _as_number(int, 0, 10), env="PTP_SUMMARY_INTERVAL", advanced=True,
           help="Wie oft ptp4l eine Zusammenfassung ins Log schreibt (4 = alle 16 s)."),
    _field("phc2sys_enable", "ptp", "Systemuhr und PTP-Uhr koppeln (phc2sys)", "bool", False,
           _as_bool, env="PHC2SYS_ENABLE",
           help="Verbindet die Systemuhr mit der PTP-Uhr (PHC) der Netzwerkkarte – nötig bei "
                "Hardware-Zeitstempeln, in beide Richtungen: Als Grandmaster überträgt phc2sys "
                "die von chrony per GPS/NTP gestellte Systemuhr auf die Karte (sonst verteilt "
                "ptp4l eine frei laufende Kartenuhr); chrony stellt weiter die Systemuhr. Als "
                "Slave überträgt phc2sys die PTP-Zeit auf die Systemuhr; dann stellt phc2sys die "
                "Uhr, und chrony liefert sie nur noch aus (läuft mit -x). Bei Software-"
                "Zeitstempeln gibt es keine Kartenuhr – dann wird phc2sys nicht gestartet."),
    _field("phc2sys_options", "ptp", "phc2sys-Optionen", "text", "", _as_phc2sys_options,
           env="PHC2SYS_OPTIONS", advanced=True, placeholder="automatisch nach Rolle",
           help="Leer lassen = automatisch passend zur Rolle: Grandmaster „-a -rr -m“ (Systemuhr "
                "ist Quelle, die Karte folgt ihr; den UTC-Abstand von 37 s holt phc2sys aus "
                "ptp4l), Slave und Automatisch „-a -r -m“ (Karte ist Quelle, die Systemuhr folgt). "
                "Eigene Optionen ersetzen das. chrony läuft dann mit -x, sobald phc2sys die "
                "Systemuhr stellen kann („-r“ ohne „-rr“, „-c CLOCK_REALTIME“ oder -s ohne -c)."),
    _field("phc_refclock", "ptp", "PTP-Hardwareuhr als chrony-Quelle", "device", "",
           _as_device(optional=True), env="PHC_REFCLOCK", placeholder="aus",
           help="PTP-zu-NTP-Brücke: chrony nutzt die PTP-Uhr der Netzwerkkarte (z. B. "
                "/dev/ptp0) als Referenz und verteilt diese Zeit per NTP an Geräte ohne PTP."),

    # --- Dashboard ---------------------------------------------------------
    _field("web_title", "web", "Titel", "text", "NTP / PTP Time Server", _as_text,
           env="WEB_TITLE", restart=RESTART_NONE, help="Überschrift im Dashboard."),
    _field("web_refresh_seconds", "web", "Aktualisierung", "float", 5.0,
           _as_number(float, 1.0, 300.0), env="WEB_REFRESH_SECONDS", unit="s",
           restart=RESTART_NONE, help="Wie oft das Dashboard neue Werte holt."),
    _field("notify_dashboard_url", "web", "Adresse des Dashboards (für Links)", "text", "",
           _as_link_url, env="NOTIFY_DASHBOARD_URL", restart=RESTART_NONE, advanced=True,
           placeholder="z. B. http://zeitserver.lan:8080/",
           help="Wenn gesetzt, hängt jede Benachrichtigung einen Link auf die passende Seite dieses "
                "Dashboards an – ein Tipp auf dem Handy führt direkt zur GPS- oder Quellen-Seite. "
                "Leer = kein Link. Der Link wird nicht gefiltert, weil du ihn selbst einträgst; trag "
                "deshalb nur eine Adresse ein, die die Empfänger sehen dürfen."),
    _field("history_interval", "web", "Messintervall für Diagramme", "float", 10.0,
           _as_number(float, 2.0, 600.0), env="HISTORY_INTERVAL", unit="s",
           restart=RESTART_NONE, advanced=True,
           help="Alle wie viele Sekunden ein Messpunkt für die Verlaufsdiagramme entsteht."),
    _field("temp_sensor", "web", "Temperatursensor", "text", "auto", _as_temp_sensor,
           env="TEMP_SENSOR", restart=RESTART_NONE, advanced=True, placeholder="auto",
           help="Welcher Sensor zu jedem Messpunkt die Temperatur liefert (Seite „Uhrqualität“). "
                "„auto“ nimmt den Chip neben dem Quarz (Raspberry Pi: cpu-thermal, PC: x86_pkg_temp, "
                "k10temp, coretemp), sonst einen DS18B20 am 1-Wire-Bus. „off“ schaltet die Aufzeichnung "
                "ab. Die möglichen Kennungen listet der Hardware-Check. Wirkt ohne Neustart."),
    _field("clock_public", "web", "Vollbild-Uhr ohne Anmeldung", "bool", False, _as_bool,
           env="CLOCK_PUBLIC", restart=RESTART_NONE, advanced=True,
           help="Macht /clock und /api/v1/time auch ohne Passwort erreichbar – praktisch für einen "
                "Wandmonitor oder ein altes Tablet. Sichtbar werden nur Uhrzeit, Ampel, Genauigkeit "
                "und die Art der Quelle (GPS, NTP …), keine Einstellungen, Namen oder Adressen. "
                "Aus = die Uhr ist wie das Dashboard geschützt. Ohne Anmeldung gilt der Schutz vor "
                "DNS-Rebinding: nur IP-Adressen, lokale Namen und WEB_ALLOWED_HOSTS. Wirkt ohne Neustart."),
    _field("update_check", "web", "Update-Hinweis (fragt GitHub)", "bool", False, _as_bool,
           env="UPDATE_CHECK", restart=RESTART_NONE,
           help="Fragt einmal am Tag zu einer zufälligen Uhrzeit bei GitHub nach der neuesten "
                "ntp-gui-Version und zeigt „Neue Version x.y.z verfügbar“ samt Link zu den "
                "Release-Notizen. Gesendet wird nur eine feste Anfrage mit dem User-Agent „ntp-gui“ – "
                "ohne Version, ohne Kennung, ohne Daten dieser Instanz. Ehrlich gesagt: GitHub sieht "
                "dabei einmal am Tag deine öffentliche IP-Adresse (grob ortbar) und dass hier "
                "vermutlich ntp-gui läuft. Darum ist der Hinweis aus, bis du ihn einschaltest. Kein "
                "Download, kein automatisches Update. Wirkt ohne Neustart."),
]


def _check_digits(value: Any) -> str:
    text = str(value or "").strip()
    if text and not re.match(r"^\d{3,7}$", text):
        raise ValidationError("Baudrate als Zahl, z. B. 9600")
    return text


def _check_refid(value: Any) -> str:
    text = str(value or "").strip()
    if not _REFID_RE.match(text):
        raise ValidationError("1–4 Buchstaben oder Ziffern")
    return text


FIELDS = {field["key"]: field for field in SCHEMA}


# PTP-Profile. Werte nur dort, wo das Feld im Dashboard noch auf seinem
# Standard steht – was der Nutzer ausdrücklich ändert, gewinnt.
#
# gptp: IEEE 802.1AS, Werte aus linuxptp configs/gPTP.cfg (Upstream-Repository
#   richardcochran/linuxptp, "802.1AS example configuration containing those
#   attributes which differ from the defaults").
# aes67: AES67-2018 Anhang A (Media-Profil): Domain 0, Delay-Request-Response
#   (E2E) über UDP/IPv4-Multicast, logSyncInterval -3 (Standard), logAnnounceInterval
#   1, announceReceiptTimeout 3; QoS-Klasse "Clock" = DSCP 46 (EF).
PTP_PROFILES: dict[str, dict] = {
    "default": {"fields": {}, "extra": {}},
    "aes67": {
        "fields": {"ptp_transport": "UDPv4", "ptp_delay_mechanism": "E2E",
                   "ptp_log_sync_interval": -3, "ptp_log_announce_interval": 1,
                   "ptp_announce_receipt_timeout": 3},
        "extra": {"dscp_event": "46", "dscp_general": "46"},
    },
    "gptp": {
        "fields": {"ptp_transport": "L2", "ptp_delay_mechanism": "P2P",
                   "ptp_priority1": 248, "ptp_priority2": 248,
                   "ptp_log_sync_interval": -3, "ptp_log_announce_interval": 0},
        "extra": {"gmCapable": "1", "syncReceiptTimeout": "3",
                  "neighborPropDelayThresh": "800", "min_neighbor_prop_delay": "-20000000",
                  "assume_two_step": "1", "path_trace_enabled": "1", "follow_up_info": "1",
                  "transportSpecific": "0x1", "ptp_dst_mac": "01:80:C2:00:00:0E"},
    },
}


def ptp_profile_values(cfg: dict) -> tuple[dict, dict]:
    """Effektive PTP-Werte nach Profil: (Felder, zusätzliche ptp4l-Zeilen)."""
    profile = PTP_PROFILES.get(cfg.get("ptp_profile") or "default", PTP_PROFILES["default"])
    out = dict(cfg)
    for key, value in profile["fields"].items():
        field = FIELDS.get(key)
        if field is not None and cfg.get(key, field["default"]) == field["default"]:
            out[key] = value
    return out, dict(profile["extra"])


PTP_UDS_DEFAULT = "/var/run/ptp4l"
_UDS_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,100}$")


def ptp_uds_address(env: dict | None = None) -> str:
    """PTP_UDS_ADDRESS: Management-Socket von ptp4l (ptp4l.conf uds_address,
    phc2sys -z, pmc -s). Nur ein absoluter Pfad ohne Leer-/Sonderzeichen, sonst
    der Standard – der Wert landet ungequotet in ptp4l.conf und der phc2sys-Zeile."""
    env = os.environ if env is None else env
    value = (env.get("PTP_UDS_ADDRESS") or "").strip()
    if value and _UDS_RE.match(value) and ".." not in value.split("/"):
        return value
    return PTP_UDS_DEFAULT


def env_number(name: str, default: float, low: float, high: float,
               env: dict | None = None, integer: bool = False) -> float:
    """Zahl aus einer Umgebungsvariable; leer, ungültig oder außerhalb
    [low, high] ergibt den Standard."""
    env = os.environ if env is None else env
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        return default
    if value != value or not low <= value <= high:  # NaN oder außerhalb
        return default
    return value


# Nur per Umgebungsvariable – im Dashboard sichtbar, aber nicht änderbar.
ENV_ONLY = [
    ("WEB_PORT", "Port des Dashboards"),
    ("WEB_BIND", "Adresse des Dashboards"),
    ("DISABLE_CLOCK_CONTROL", "Uhrensteuerung abschalten"),
    ("EXTRA_CHRONY_CONF", "Zusätzliche chrony-Zeilen"),
    ("EXTRA_PTP4L_CONF", "Zusätzliche ptp4l-Zeilen"),
    ("CLIENTLOGLIMIT", "Speicher für die Client-Liste"),
    ("WEB_READONLY", "Einstellungen im Dashboard sperren"),
]


# ---------------------------------------------------------------------------
# Laden, Speichern, effektive Werte
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()  # reentrant: save() ruft values() unter der Sperre
_CACHE: dict[str, Any] = {"mtime": None, "data": None}


def _load_file() -> dict:
    try:
        stat = os.stat(SETTINGS_FILE)
    except OSError:
        return {}
    if _CACHE["mtime"] == stat.st_mtime_ns and _CACHE["data"] is not None:
        return _CACHE["data"]
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if data and _schema_of(data) < SCHEMA_VERSION:
        with _LOCK:
            data, notes = migrate_data(data)
            try:
                _write_file(data)
                stat = os.stat(SETTINGS_FILE)
            except OSError as exc:
                # Nur lesbares Volume: Migration gilt im Speicher, Hinweis bleibt sichtbar.
                print(f"[web] Einstellungen migriert, aber nicht gespeichert: {exc}", flush=True)
            for note in notes:
                print(f"[web] Update der Einstellungen: {note['title']}", flush=True)
    _CACHE.update(mtime=stat.st_mtime_ns, data=data)
    return data


def _write_file(data: dict) -> None:
    data = dict(data)
    data.setdefault("schema", SCHEMA_VERSION)
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, SETTINGS_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _CACHE.update(mtime=None, data=None)


def _env_value(field: dict, env: dict[str, str]):
    """Wert aus der Umgebung – oder None, wenn die Variable nicht gesetzt ist."""
    if field["key"] == "ntp_sources":
        sources = _env_sources(env)
        return None if sources is None else _as_sources(sources)
    name = field["env"]
    if not name or name not in env:
        return None
    raw = env[name]
    if field["type"] == "networks" and not str(raw).strip():
        return []
    return field["convert"](raw)


def effective(env: dict[str, str] | None = None) -> dict[str, dict]:
    """Alle Einstellungen mit Wert und Herkunft: gui > env > default.

    Ein ungültiger Env-Wert fällt auf den Standard zurück und wird als Fehler
    gemeldet, statt den Start zu verhindern.
    """
    env = dict(os.environ if env is None else env)
    with _LOCK:
        saved = dict(_load_file().get("values", {}))
    result = {}
    for field in SCHEMA:
        key = field["key"]
        entry = {"value": field["default"], "source": "default", "error": None, "env": None}
        try:
            env_value = _env_value(field, env)
        except ValidationError as exc:
            env_value = None
            entry["error"] = f"Umgebungsvariable ungültig: {exc}"
        if env_value is not None:
            entry.update(value=env_value, source="env", env=env_value)
        if key in saved:
            try:
                entry.update(value=field["convert"](saved[key]), source="gui")
            except ValidationError as exc:
                entry["error"] = f"Gespeicherter Wert ungültig: {exc}"
        result[key] = entry
    return result


def values(env: dict[str, str] | None = None) -> dict[str, Any]:
    return {key: entry["value"] for key, entry in effective(env).items()}


def validate(changes: dict[str, Any]) -> dict[str, Any]:
    """Prüft eingehende Änderungen. Wirft ValidationError mit Feldbezug."""
    clean = {}
    errors = {}
    for key, raw in changes.items():
        field = FIELDS.get(key)
        if field is None:
            errors[key] = "Unbekannte Einstellung"
            continue
        try:
            clean[key] = field["convert"](raw)
        except ValidationError as exc:
            errors[key] = str(exc)
    if errors:
        error = ValidationError("; ".join(f"{FIELDS.get(k, {}).get('label', k)}: {v}" for k, v in errors.items()))
        error.fields = errors  # type: ignore[attr-defined]
        raise error
    return clean


def save(changes: dict[str, Any]) -> dict[str, Any]:
    """Speichert geprüfte Änderungen. Gibt zurück, welche Dienste neu starten müssen."""
    clean = validate(changes)
    with _LOCK:
        data = dict(_load_file())
        stored = dict(data.get("values", {}))
        before = values()
        stored.update(clean)
        data["values"] = stored
        _write_file(data)
    after = values()
    changed = [key for key in clean if before.get(key) != after.get(key)]
    restart = any(FIELDS[key]["restart"] == RESTART_SERVICES for key in changed)
    return {"changed": changed, "restart": restart}


def reset(keys: list[str]) -> dict[str, Any]:
    """Entfernt im Dashboard gespeicherte Werte – es gilt wieder Env bzw. Standard."""
    unknown = [key for key in keys if key not in FIELDS]
    if unknown:
        raise ValidationError(f"Unbekannte Einstellung: {', '.join(unknown)}")
    with _LOCK:
        data = dict(_load_file())
        stored = dict(data.get("values", {}))
        before = values()
        for key in keys:
            stored.pop(key, None)
        data["values"] = stored
        _write_file(data)
    after = values()
    changed = [key for key in keys if before.get(key) != after.get(key)]
    restart = any(FIELDS[key]["restart"] == RESTART_SERVICES for key in changed)
    return {"changed": changed, "restart": restart}


# Werte, die keine Geheimnisse sind, aber Konto-Kennungen enthalten können (NextDNS-ID im
# DoH-Pfad): API-Schlüssel mit Leserecht sehen sie nur gekürzt.
MASKED_FOR_READ = ("dns_doh",)


def _mask_value(key: str, value: Any) -> Any:
    if key == "dns_doh" and isinstance(value, list):
        import dnsfwd
        return [dnsfwd.doh_label(str(item)) for item in value]
    return value


def public_schema(masked: bool = False) -> dict:
    """Schema + aktuelle Werte für das Dashboard (ohne Funktionen und Geheimnisse).
    masked=True (API-Schlüssel mit Leserecht): MASKED_FOR_READ nur gekürzt."""
    eff = effective()
    fields = []
    for field in SCHEMA:
        entry = eff[field["key"]]
        if masked and field["key"] in MASKED_FOR_READ:
            entry = dict(entry, value=_mask_value(field["key"], entry["value"]),
                         env=_mask_value(field["key"], entry["env"]) if entry["env"] is not None else None,
                         error="Wert ungültig (Einzelheiten nur mit Admin-Recht)" if entry["error"] else None)
        fields.append({
            "key": field["key"], "section": field["section"], "label": field["label"],
            "type": field["type"], "help": field["help"], "advanced": field["advanced"],
            "restart": field["restart"], "unit": field["unit"],
            "placeholder": field["placeholder"], "env": field["env"],
            "options": [{"value": v, "label": l} for v, l in (field["options"] or [])],
            "default": field["default"], "value": entry["value"], "source": entry["source"],
            "env_value": entry["env"], "error": entry["error"],
        })
    env_only = [{"name": name, "label": label, "set": name in os.environ,
                 "value": ("••••" if "PASSWORD" in name else os.environ.get(name, ""))}
                for name, label in ENV_ONLY]
    return {
        "sections": [{"key": k, "label": l, "description": d} for k, l, d in SECTIONS],
        "fields": fields,
        "env_only": env_only,
        "storage": storage_info(),
    }


def storage_info() -> dict:
    """Wo gespeichert wird und ob es einen Neustart des Containers übersteht."""
    persistent = _is_mounted(os.path.dirname(DATA_DIR.rstrip("/")) or DATA_DIR)
    return {"path": SETTINGS_FILE, "persistent": persistent,
            "exists": os.path.exists(SETTINGS_FILE)}


def _is_mounted(path: str) -> bool:
    """True, wenn path (oder ein Elternverzeichnis unterhalb von /) ein Mount ist."""
    path = os.path.realpath(path)
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            mounts = [line.split()[4] for line in handle if len(line.split()) > 4]
    except OSError:
        return True  # unbekannt – nicht fälschlich warnen
    while path not in ("", "/"):
        if path in mounts:
            return True
        path = os.path.dirname(path)
    return False


# ---------------------------------------------------------------------------
# Passwort für das Dashboard
# ---------------------------------------------------------------------------

_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ROUNDS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, digest = encoded.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                   base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def stored_credentials() -> dict | None:
    with _LOCK:
        auth = _load_file().get("auth")
    if isinstance(auth, dict) and auth.get("user") and auth.get("hash"):
        return {"user": str(auth["user"]), "hash": str(auth["hash"])}
    return None


def set_credentials(user: str, password: str | None) -> None:
    """Setzt (oder mit password=None: entfernt) den Dashboard-Zugang."""
    with _LOCK:
        data = dict(_load_file())
        if password is None:
            data.pop("auth", None)
        else:
            user = str(user or "").strip()
            if not re.match(r"^[A-Za-z0-9._@-]{1,64}$", user):
                raise ValidationError("Benutzername: 1–64 Zeichen, nur Buchstaben, Ziffern und ._@-")
            if len(password) < 8:
                raise ValidationError("Passwort: mindestens 8 Zeichen")
            data["auth"] = {"user": user, "hash": hash_password(password)}
        _write_file(data)


def export_values(masked: bool = False) -> dict:
    """Die im Dashboard gespeicherten Werte (ohne Passwort) – zum Sichern. masked=True (API-Schlüssel
    mit Leserecht): MASKED_FOR_READ gekürzt und unter „masked“ vermerkt – beim Import übersprungen."""
    with _LOCK:
        values = dict(_load_file().get("values", {}))
    out: dict[str, Any] = {"schema": SCHEMA_VERSION, "values": values}
    if masked:
        hidden = [key for key in MASKED_FOR_READ if key in values]
        for key in hidden:
            values[key] = _mask_value(key, values[key])
        if hidden:
            out["masked"] = hidden
    return out


# ---------------------------------------------------------------------------
# Versionierte Einstellungen: Schema-Nummer + Migrationen
# ---------------------------------------------------------------------------
#
# settings.json trägt "schema": N. Fehlt die Nummer, stammt die Datei aus
# 1.2.x oder älter (= Schema 1). Jede Migration bringt die Daten von N-1 auf N,
# ändert sie direkt und gibt Hinweise zurück, die das Dashboard unter „Was sich
# beim Update geändert hat“ zeigt (migration_notes()). Migrationen werden nie
# nachträglich geändert, nur neue angehängt – sonst liefen Installationen, die
# schon migriert sind, in einen anderen Zustand als frische.
#
# Neue Migration: Funktion _migrate_<N-1>_<N>(data) -> list[dict] schreiben,
# in MIGRATIONS eintragen, SCHEMA_VERSION erhöhen, Test ergänzen.

SCHEMA_VERSION = 3
MAX_NOTES = 50


def _schema_of(data: dict) -> int:
    try:
        return max(1, int(data.get("schema", 1)))
    except (TypeError, ValueError):
        return 1


def _note(note_id: str, schema: int, title: str, text: str, keys: list[str] | None = None) -> dict:
    return {"id": note_id, "schema": schema, "title": title, "text": text,
            "keys": keys or [], "t": int(time.time()), "seen": False}


def _migrate_1_2(data: dict) -> list[dict]:
    """1.2.0 erlaubt Zertifikat/Schlüssel des NTS-Servers nur unter NTS_CERT_ROOTS.

    Ältere Versionen haben jeden Pfad gespeichert. So ein Wert würde jetzt bei
    jedem Laden als „ungültig“ gemeldet und durch den Standard ersetzt – die
    Migration räumt ihn sauber weg und erklärt, warum.
    """
    stored = data.get("values")
    if not isinstance(stored, dict):
        return []
    notes = []
    for key, what in (("nts_server_cert", "Zertifikat"), ("nts_server_key", "Schlüssel")):
        if key not in stored:
            continue
        raw = stored[key]
        if isinstance(raw, str) and cert_path_allowed(raw.strip()):
            continue
        del stored[key]
        notes.append(_note(
            f"2-{key}", 2, f"NTS-{what}: Pfad zurückgesetzt",
            f"Der gespeicherte Pfad für das {what} des NTS-Servers lag außerhalb der "
            f"erlaubten Ordner ({', '.join(r.rstrip('/') for r in NTS_CERT_ROOTS)}). "
            "Seit 1.2.0 nimmt ntp-gui nur noch Dateien von dort, weil die Datei für chronyd "
            "kopiert wird – ein beliebiger Pfad hätte sonst z. B. Systemdateien lesbar machen "
            "können. Es gilt wieder der Standard bzw. die Umgebungsvariable. Bitte das "
            "Zertifikat nach /certs (schreibgeschützt) mounten und den Pfad neu eintragen.",
            [key]))
    return notes


def _migrate_2_3(data: dict) -> list[dict]:
    """1.3.1 (Debian trixie): Schaltsekunden kommen aus leap-seconds.list.

    trixie liefert „right/UTC“ nur noch im Paket tzdata-legacy. Ein gespeichertes
    LEAPSECTZ=right/UTC (bis 1.3.0 der Standard) würde ins Leere zeigen.
    """
    stored = data.get("values")
    if not isinstance(stored, dict) or "leapsectz" not in stored:
        return []
    value = str(stored.get("leapsectz") or "").strip()
    if value not in ("", "right/UTC"):
        return []
    del stored["leapsectz"]
    if not value:
        return []
    return [_note(
        "3-leapsectz", 3, "Schaltsekunden: jetzt über die Liste",
        "Bisher hat chrony bevorstehende Schaltsekunden aus der Zeitzone „right/UTC“ gelesen. "
        "Seit 1.3.1 basiert das Image auf Debian 13 „trixie“, und dort gibt es diese Zone nicht "
        "mehr. ntp-gui nutzt stattdessen die offizielle Schaltsekunden-Liste "
        f"({LEAPSECLIST_DEFAULT}). Du musst nichts tun – das Ergebnis ist dasselbe.",
        ["leapsectz", "leapseclist"])]


MIGRATIONS: dict[int, Callable[[dict], list[dict]]] = {
    2: _migrate_1_2,
    3: _migrate_2_3,
}


def migrate_data(data: dict) -> tuple[dict, list[dict]]:
    """Bringt Dateiinhalt (oder einen Export) auf SCHEMA_VERSION. Gibt (Daten, neue Hinweise)."""
    data = json.loads(json.dumps(data))  # tiefe Kopie, nur JSON-Typen
    current = _schema_of(data)
    notes: list[dict] = []
    if current > SCHEMA_VERSION:
        # Datei einer neueren Version (Downgrade): nicht anfassen, nur lesen.
        return data, notes
    for target in range(current + 1, SCHEMA_VERSION + 1):
        step = MIGRATIONS.get(target)
        if step is not None:
            notes += step(data)
        data["schema"] = target
    data["schema"] = max(current, SCHEMA_VERSION)
    if notes and "values" in data:
        stored = [n for n in data.get("migration_notes", []) if isinstance(n, dict)]
        data["migration_notes"] = (stored + notes)[-MAX_NOTES:]
    return data, notes


def migrate_import(exported: dict) -> tuple[dict, list[str]]:
    """Für /api/settings/import: Werte eines (auch älteren) Exports migrieren.

    Gibt (Werte, Hinweistexte) zurück. Ein Export ohne "schema" stammt aus 1.2.x.
    """
    if not isinstance(exported, dict) or not isinstance(exported.get("values"), dict):
        raise ValidationError("Datei enthält keine Einstellungen")
    if _schema_of(exported) > SCHEMA_VERSION:
        raise ValidationError("Die Datei stammt aus einer neueren Version von ntp-gui – "
                              "bitte zuerst aktualisieren")
    data, notes = migrate_data({"schema": exported.get("schema", 1),
                                "values": exported["values"]})
    return data["values"], [n["text"] for n in notes]


def schema_version() -> int:
    """Schema der gespeicherten Datei (SCHEMA_VERSION, wenn es noch keine gibt)."""
    with _LOCK:
        data = _load_file()
    return _schema_of(data) if data else SCHEMA_VERSION


def migration_notes(include_seen: bool = True) -> list[dict]:
    """Hinweise „Was sich beim Update geändert hat“, neueste zuletzt."""
    with _LOCK:
        notes = _load_file().get("migration_notes", [])
    return [dict(n) for n in notes if isinstance(n, dict)
            and (include_seen or not n.get("seen"))]


def ack_migration_notes() -> int:
    """Markiert alle Hinweise als gelesen. Gibt die Zahl neu markierter zurück."""
    with _LOCK:
        data = dict(_load_file())
        notes = [dict(n) for n in data.get("migration_notes", []) if isinstance(n, dict)]
        fresh = [n for n in notes if not n.get("seen")]
        if not fresh:
            return 0
        for note in notes:
            note["seen"] = True
        data["migration_notes"] = notes
        _write_file(data)
    return len(fresh)
