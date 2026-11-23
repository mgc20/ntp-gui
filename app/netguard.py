"""Erlaubte Ziele für ausgehende Verbindungen (Benachrichtigungen, DNS-Weiterleiter).

ntp-gui verbindet sich nur dorthin, wohin ein Admin es schickt. Trotzdem gehören manche Adressen nie
zu einem sinnvollen Ziel: Link-local (169.254.0.0/16, fe80::/10 – dort antworten bei Cloud-Anbietern
die Metadaten-Dienste), die bekannten Metadaten-Adressen außerhalb davon, „dieses Netz“ (0.0.0.0/8),
Multicast und reservierte Bereiche. Loopback (der Container bzw. bei network_mode: host der Rechner
selbst) ist für Benachrichtigungen standardmäßig gesperrt.

OUTBOUND_TARGETS (nur per Umgebung, damit es niemand über das Dashboard abschalten kann):
  lan       (Standard) öffentliche und private Adressen (Heimnetz, Docker-Netz) – kein Loopback
  loopback  wie lan, dazu Loopback (z. B. Apprise unter http://127.0.0.1:8000 bei network_mode: host)
  public    nur öffentliche Adressen (Server im Internet, VPS)

Geprüft wird die tatsächlich verwendete Adresse NACH der Namensauflösung (notify._Deadline.connect),
dazu Adressen in IPv6-Hüllen (::ffff:a.b.c.d, 6to4, NAT64) nach dem Auspacken.
"""

from __future__ import annotations

import ipaddress
import os

MODES = ("lan", "loopback", "public")
DEFAULT_MODE = "lan"

# Immer gesperrt, egal in welchem Modus.
_ALWAYS_BLOCKED = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8",            # „dieses Netz“ – 0.0.0.0 erreicht unter Linux den eigenen Rechner
    "169.254.0.0/16",       # Link-local, Cloud-Metadaten (169.254.169.254, 169.254.170.2 …)
    "100.100.100.200/32",   # Metadaten-Dienst eines Cloud-Anbieters (liegt im CGNAT-Bereich)
    "224.0.0.0/4",          # Multicast
    "240.0.0.0/4",          # reserviert, inkl. 255.255.255.255
    "::/128",               # unspezifiziert
    "fe80::/10",            # Link-local
    "fd00:ec2::254/128",    # Metadaten-Dienst (IPv6)
    "ff00::/8",             # Multicast
))
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def mode(env: dict | None = None) -> str:
    """Wert von OUTBOUND_TARGETS; Unbekanntes gilt als Standard (lan)."""
    env = os.environ if env is None else env
    value = str(env.get("OUTBOUND_TARGETS") or "").strip().lower()
    return value if value in MODES else DEFAULT_MODE


def mode_warning(env: dict | None = None) -> str | None:
    env = os.environ if env is None else env
    raw = str(env.get("OUTBOUND_TARGETS") or "").strip()
    if raw and raw.lower() not in MODES:
        return (f"OUTBOUND_TARGETS={raw!r} ist unbekannt (erlaubt: {', '.join(MODES)}) – "
                f"verwende {DEFAULT_MODE}")
    return None


def unwrap(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """IPv4-Adresse in einer IPv6-Hülle (mapped, 6to4, NAT64) auspacken; sonst unverändert."""
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def parse(text: str):
    """IP-Adresse ohne Scope-ID (fe80::1%eth0 → None); None, wenn es keine Adresse ist."""
    text = str(text or "").strip().strip("[]")
    if not text or "%" in text:
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def blocked_always(ip) -> bool:
    """Link-local, Metadaten, Multicast, reserviert – nie ein Ziel."""
    ip = unwrap(ip)
    return any(ip.version == net.version and ip in net for net in _ALWAYS_BLOCKED)


def reason(ip, purpose: str = "notify", env: dict | None = None) -> str | None:
    """Warum diese Adresse kein Ziel sein darf – None, wenn sie erlaubt ist.

    purpose „notify“: Loopback nur mit OUTBOUND_TARGETS=loopback. purpose „dns“: Loopback ist im LAN
    üblich (lokaler Resolver auf dem Rechner) und nur im Modus public gesperrt."""
    ip = unwrap(ip)
    current = mode(env)
    if blocked_always(ip):
        return "link-local, Metadaten-Dienst oder reservierte Adresse"
    if ip.is_loopback:
        if current == "public" or (purpose == "notify" and current != "loopback"):
            return "Loopback (der Server selbst)"
        return None
    if current == "public" and not ip.is_global:
        return "private Adresse (OUTBOUND_TARGETS=public erlaubt nur öffentliche Ziele)"
    return None


def local_address(ip) -> bool:
    """Privat oder Loopback – dorthin darf ein Token auch über http:// gehen."""
    ip = unwrap(ip)
    return ip.is_loopback or (ip.is_private and not blocked_always(ip))
