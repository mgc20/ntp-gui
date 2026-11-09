"""Zeitserver erzwingen: Namensliste, Anleitungen (Snippets) und Prüfung.

Viele Geräte ignorieren DHCP Option 42 und fragen fest eingebaute Namen
(time.windows.com, time.apple.com, pool.ntp.org …). Zwei Wege bringen sie
trotzdem zu ntp-gui:

  * DNS-Umschreibung: Der DNS-Server im LAN (AdGuard Home, Pi-hole, dnsmasq,
    Unbound) beantwortet diese Namen mit der Adresse von ntp-gui.
  * Firewall-Umleitung (DNAT): Der Router leitet jedes NTP-Paket (UDP 123),
    das ins Internet will, auf ntp-gui um – auch bei fest eingetragenen IPs.

Dieses Modul ist bewusst ohne Seiteneffekte beim Import. Die Snippet-
Generatoren sind reine Funktionen (Server-IP + Namen → Text). check() schickt
nur auf ausdrücklichen Klick ein paar NTP-Anfragen nach außen (ausgehend, kein
Upload von Daten) und ist auf eine Prüfung je 30 s begrenzt.

Namen in KNOWN_TIME_HOSTS sind geprüft (Herstellerdoku bzw. bekannte
Standardwerte und tatsächlich auflösbar). Recherche-Stand 2026-11:
  * Samsung- und LG-Fernseher holen die Zeit per HTTP(S) von Herstellerservern
    (z. B. time.samsungcloudsolution.com, lgtvsdp.com) statt per NTP – eine
    Umschreibung auf einen NTP-Server würde dort nur die Zeit kaputtmachen.
    Deshalb stehen sie in NOT_NTP, nicht in der Liste.
  * FRITZ!Box: Werkseinstellung ist 2.europe.pool.ntp.org (ältere FRITZ!OS:
    0.europe.pool.ntp.org) – beides über *.pool.ntp.org abgedeckt. „ntp.fritz.box“
    gibt es nicht; „fritz.box“ ist die Box selbst und darf nie umgeschrieben werden.
  * Sonos: [0-3].sonostime.pool.ntp.org (Community-Mitschnitte, Hersteller-Zone im Pool).
  * Synology DSM, NVIDIA Shield & Co. nutzen Standardnamen (pool.ntp.org,
    time.google.com, time.android.com), die bereits enthalten sind.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import struct
import threading
import time
from typing import Any, Callable

IP_PLACEHOLDER = "<IP-des-Servers>"
NTP_EPOCH_OFFSET = 2208988800  # 1900-01-01 → 1970-01-01

_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$")


def _n(prefix: str, suffix: str, count: int = 4) -> list[str]:
    """_n("", "debian.pool.ntp.org") → 0.debian… bis 3.debian…"""
    return [f"{prefix}{i}.{suffix}" for i in range(count)]


# (Kennung, Anzeige, Namen, Hinweis)
VENDORS: list[tuple[str, str, list[str], str]] = [
    ("windows", "Windows / Xbox", ["time.windows.com"], "Standard von Windows (w32time) und Xbox."),
    ("apple", "Apple (macOS, iOS, tvOS, HomePod)",
     ["time.apple.com", "time.euro.apple.com", "time.asia.apple.com", "time-ios.apple.com",
      "time-macos.apple.com"], "Je nach Gerät und Region einer dieser Namen."),
    ("google", "Google (Android, ChromeOS, Nest)",
     ["time.google.com", "time1.google.com", "time2.google.com", "time3.google.com", "time4.google.com",
      "time.android.com"],
     "Android fragt time.android.com; Google verschmiert Schaltsekunden („leap smear“) – "
     "auch deshalb lohnt es sich, diese Geräte auf deinen Server zu holen."),
    ("amazon", "Amazon (Echo, Fire TV, Kindle, AWS)",
     ["time.aws.com", "time.amazon.com"] + _n("", "amazon.pool.ntp.org"),
     "Echo- und Fire-Geräte nutzen die Amazon-Zone im NTP-Pool."),
    ("ubuntu", "Ubuntu", ["ntp.ubuntu.com"] + _n("", "ubuntu.pool.ntp.org"),
     "systemd-timesyncd bzw. chrony unter Ubuntu."),
    ("debian", "Debian, Raspberry Pi OS", _n("", "debian.pool.ntp.org"), ""),
    ("fedora", "Fedora, CentOS, RHEL",
     _n("", "fedora.pool.ntp.org") + _n("", "centos.pool.ntp.org") + _n("", "rhel.pool.ntp.org"), ""),
    ("other-linux", "Arch, openSUSE, Gentoo, NixOS",
     _n("", "arch.pool.ntp.org") + _n("", "opensuse.pool.ntp.org") + _n("", "gentoo.pool.ntp.org")
     + _n("", "nixos.pool.ntp.org"), ""),
    ("openwrt", "OpenWrt, pfSense, OPNsense",
     _n("", "openwrt.pool.ntp.org") + _n("", "pfsense.pool.ntp.org") + _n("", "opnsense.pool.ntp.org"),
     "Router und Firewalls – nur relevant, wenn sie nicht selbst die Umleitung machen."),
    ("ubiquiti", "Ubiquiti (UniFi, EdgeRouter)", _n("", "ubnt.pool.ntp.org"), ""),
    ("sonos", "Sonos", _n("", "sonostime.pool.ntp.org"),
     "Aus Mitschnitten der Community; Sonos dokumentiert die Namen nicht offiziell."),
    ("fritzbox", "FRITZ!Box (als Client)", ["2.europe.pool.ntp.org", "0.europe.pool.ntp.org"],
     "Werkseinstellung der FRITZ!Box; ältere FRITZ!OS-Versionen nutzen 0.europe.pool.ntp.org."),
    ("pool", "NTP-Pool (viele IoT-Geräte, Linux, Router)",
     ["pool.ntp.org"] + _n("", "pool.ntp.org") + ["de.pool.ntp.org"] + _n("", "de.pool.ntp.org")
     + ["europe.pool.ntp.org"] + _n("", "europe.pool.ntp.org") + _n("", "android.pool.ntp.org"),
     "Standard sehr vieler Geräte (ESP-Firmware, Kameras, NAS wie Synology, Linux)."),
    ("vmware", "VMware", _n("", "vmware.pool.ntp.org"), ""),
    ("nist", "NIST (USA)", ["time.nist.gov"], "In vielen Geräten aus den USA fest eingetragen."),
]

KNOWN_TIME_HOSTS: list[dict] = []
_seen: set[str] = set()
for _vid, _label, _hosts, _note in VENDORS:
    for _host in _hosts:
        if _host not in _seen:
            _seen.add(_host)
            KNOWN_TIME_HOSTS.append({"host": _host, "vendor": _vid, "label": _label})
del _seen

NTS_REASON = ("NTS-Server: Der Client prüft per TLS-Zertifikat, dass er wirklich mit diesem Server spricht. "
              "Eine Umschreibung auf ntp-gui scheitert an dieser Prüfung – das Gerät hätte dann gar keine "
              "Zeit mehr. Wer NTS nutzt, hat sich bewusst für einen bestimmten Server entschieden.")

NEVER_REWRITE: dict[str, str] = {
    "time.cloudflare.com": NTS_REASON + " Cloudflare beantwortet unter diesem Namen außerdem HTTPS.",
    "nts.netnod.se": NTS_REASON,
    "sth1.nts.netnod.se": NTS_REASON,
    "sth2.nts.netnod.se": NTS_REASON,
    "ptbtime1.ptb.de": NTS_REASON + " (PTB, Braunschweig – die gesetzliche Zeit in Deutschland)",
    "ptbtime2.ptb.de": NTS_REASON + " (PTB)",
    "ptbtime3.ptb.de": NTS_REASON + " (PTB)",
    "ptbtime4.ptb.de": NTS_REASON + " (PTB)",
    "nts.time.nl": NTS_REASON,
    "ntp.zeitgitter.net": NTS_REASON,
    "fritz.box": "Das ist die FRITZ!Box selbst (Weboberfläche, DNS, Telefonie). Eine Umschreibung legt "
                 "die Box lahm. Zeigen deine Geräte auf fritz.box, stelle stattdessen die FRITZ!Box auf "
                 "ntp-gui als Zeitquelle um.",
}

# Geräte, die ihre Zeit nicht per NTP holen – Umschreiben hilft nicht, sondern schadet.
NOT_NTP: list[dict] = [
    {"label": "Samsung-Fernseher (Tizen)",
     "text": "holen die Uhrzeit per HTTPS von time.samsungcloudsolution.com. Das ist kein NTP – eine "
             "DNS-Umschreibung auf ntp-gui würde die Uhr des Fernsehers nicht stellen, sondern die "
             "Abfrage scheitern lassen. Bei Samsung-Signage-Displays lässt sich NTP im Menü einstellen."},
    {"label": "LG-Fernseher (webOS)",
     "text": "beziehen die Zeit über einen Hersteller-Dienst (lgtvsdp.com) per HTTP und ignorieren den "
             "NTP-Server aus DHCP. Auch hier hilft keine Umschreibung."},
]


def is_never_rewrite(host: str) -> str | None:
    """Grund, warum `host` nie umgeschrieben werden darf – oder None."""
    host = str(host or "").strip().rstrip(".").lower()
    if host in NEVER_REWRITE:
        return NEVER_REWRITE[host]
    if host.startswith("nts.") or ".nts." in host:
        return NTS_REASON
    if host.endswith(".fritz.box"):
        return NEVER_REWRITE["fritz.box"]
    # Eine Zone, unter der ein geschützter Name liegt (z. B. „cloudflare.com“), würde ihn mitnehmen.
    for protected in NEVER_REWRITE:
        if protected.endswith("." + host):
            return f"Darunter liegt {protected}. " + NEVER_REWRITE[protected]
    return None


def merged_hostnames(extra: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Bekannte Namen + eigene Namen aus den Einstellungen.

    Rückgabe: (Namen [{host, vendor, label}], übersprungen [{host, reason}]).
    """
    hosts = [dict(item) for item in KNOWN_TIME_HOSTS]
    known = {item["host"] for item in hosts}
    skipped = []
    for raw in extra or []:
        host = str(raw or "").strip().rstrip(".").lower()
        if not host or host in known:
            continue
        if not _HOST_RE.match(host):
            skipped.append({"host": host[:80], "reason": "Kein gültiger Hostname."})
            continue
        reason = is_never_rewrite(host)
        if reason:
            skipped.append({"host": host, "reason": reason})
            continue
        known.add(host)
        hosts.append({"host": host, "vendor": "custom", "label": "Eigene Namen (Einstellungen)"})
    return hosts, skipped


def collapse_zones(hosts: list[str]) -> list[str]:
    """Entfernt Namen, deren übergeordnete Zone schon in der Liste steht.

    Für Systeme, die Subdomains mit umschreiben (dnsmasq address=/…/, AdGuard ||…^,
    Unbound redirect): pool.ntp.org deckt 0.pool.ntp.org, de.pool.ntp.org … ab.
    Eine Zone wird nur genutzt, wenn darunter kein geschützter Name liegt.
    """
    names = sorted({h.lower() for h in hosts}, key=lambda h: (h.count("."), h))
    zones: list[str] = []
    for host in names:
        if any(host.endswith("." + zone) for zone in zones):
            continue
        zones.append(host)
    return sorted(zones, key=_sort_key)


def _sort_key(host: str) -> tuple:
    return tuple(reversed(host.split(".")))


# ---------------------------------------------------------------------------
# Eingaben prüfen
# ---------------------------------------------------------------------------

def clean_server_ip(value: Any) -> str | None:
    """Gültige Unicast-Adresse, unter der Geräte im LAN ntp-gui erreichen – sonst None.

    Nie eine Adresse erfinden: Loopback, 0.0.0.0, Multicast und das Docker-
    Standardnetz (172.17.0.0/16) sind von anderen Geräten aus nicht erreichbar.
    """
    text = str(value or "").strip().strip("[]")
    if not text or len(text) > 64:
        return None
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast or addr.is_reserved:
        return None
    if addr.version == 4 and addr in ipaddress.ip_network("172.17.0.0/16"):
        return None
    return str(addr)


def _port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 123
    return port if 1 <= port <= 65535 else 123


# ---------------------------------------------------------------------------
# Snippets
# ---------------------------------------------------------------------------

def _block(title: str, code: str, lang: str = "text") -> dict:
    return {"title": title, "code": code, "lang": lang}


def _rr(ip: str) -> str:
    return "AAAA" if ":" in ip else "A"


def snip_adguard(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    zones = collapse_zones(hosts)
    # Ausnahme für ntp-gui selbst: sonst fragt chronyd beim Upstream-Pool sich selbst.
    client = f",client=~{ip}" if ip else ""
    rules = "\n".join(f"||{zone}^$dnsrewrite={target}{client}" for zone in zones)
    rewrites = "\n".join(f"{zone}  →  {target}" for zone in zones)
    ntp_ip = ip or IP_PLACEHOLDER
    # Ausnahme für ntp-gui als eigene Regel – passt zu jeder Umschreibung, auch der Liste
    # „DNS-Umschreibungen“ (die selbst keine Ausnahme kennt) und Regeln aus anderen Listen.
    exception = "\n".join(f"@@||{zone}^$dnsrewrite,client={ntp_ip}" for zone in zones)
    cname_zone = "time.lan"
    cname = ("! Variante „ein Ziel“: alle Zeitserver-Namen zeigen auf einen eigenen Namen …\n"
             + "\n".join(f"||{zone}^$dnsrewrite={cname_zone}{client}" for zone in zones)
             + f"\n! … und nur dieser Name hat die Adresse (Filter → DNS-Umschreibungen):\n"
             + f"! {cname_zone}  →  {target}")
    notes = [
        "Die Regeln mit `||name^` gelten auch für alle Subdomains – `||pool.ntp.org^` erfasst "
        "0.pool.ntp.org, de.pool.ntp.org und alle Hersteller-Zonen.",
        "AdGuard beantwortet für umgeschriebene Namen nur passende Anfragen: AAAA-Anfragen (IPv6) "
        "bekommen eine leere Antwort. So weichen Geräte nicht über IPv6 zum echten Server aus.",
    ]
    if ip:
        notes.append(f"`client=~{ip}` nimmt ntp-gui selbst aus. Sonst würde chronyd seine eigenen "
                     "Zeitquellen (z. B. pool.ntp.org) bei sich selbst suchen.")
    else:
        notes.append("Trage die Adresse von ntp-gui ein und ergänze `,client=~<IP-des-Servers>`, damit "
                     "ntp-gui selbst die echten Server erreicht.")
    notes += [
        "**Ausnahme für ntp-gui, zwei Wege:** (1) die Ausnahmeregeln `@@…$dnsrewrite,client=<IP>` – sie "
        "heben die `$dnsrewrite`-Regeln für diese eine Adresse auf, auch solche aus anderen Listen; "
        "(2) „Client-spezifische Regel“: ntp-gui unter Einstellungen → Client-Einstellungen als eigenen "
        "Client anlegen (Kennung: seine IP) und dort die Filterung für ihn ausschalten – das nimmt ihn je "
        "nach Version auch von den Einträgen unter „DNS-Umschreibungen“ aus. Ob es greift, zeigt die "
        "Prüfung unten. Am einfachsten ist DoT/DoH unter „DNS für ntp-gui“: Dann fragt ntp-gui AdGuard gar nicht.",
        "**Variante „ein Ziel“ (CNAME-Stil):** `||time.amazon.com^$dnsrewrite=time.lan` plus eine "
        "Umschreibung `time.lan → <IP>`. Vorteil: Ändert sich die Adresse von ntp-gui, passt du nur einen "
        "Eintrag an. Grenzen: NTS-Namen nie so umschreiben (das Zertifikat passt dann nicht, das Gerät "
        "bekommt gar keine Zeit); Geräte mit „Privatem DNS“/DNS-over-HTTPS fragen AdGuard nicht und "
        "umgehen jede Umschreibung; für IPv6 entweder einen AAAA-Eintrag für time.lan anlegen oder "
        "prüfen, dass AAAA-Anfragen leer bleiben – sonst weichen Geräte über IPv6 zum echten Server aus. "
        "Die Ausnahme für ntp-gui gilt auch hier.",
        "**Ob die Ausnahme greift**, zeigt die Prüfung unten: Bei „Eigene Quellen“ darf keine Zeile "
        "„Schleife“ stehen. Fehlt die Ausnahme, schreibt ntp-gui zusätzlich das Ereignis „… zeigt auf "
        "dich selbst – vermutlich DNS-Umschreibung ohne Ausnahme für ntp-gui“.",
    ]
    if port != 123:
        notes.append(f"Achtung: ntp-gui lauscht auf Port {port}. DNS kann nur die Adresse umbiegen, nicht "
                     "den Port – Geräte fragen weiter Port 123. Nutze dann die Firewall-Umleitung.")
    return {
        "kind": "dns",
        "intro": "AdGuard Home → Filter → Benutzerdefinierte Filterregeln: Regeln einfügen und "
                 "„Anwenden“. Die Liste unter Filter → DNS-Umschreibungen ist die Alternative per "
                 "Klick, kennt aber selbst keine Ausnahme für ntp-gui – dafür gibt es die Ausnahmeregeln "
                 "(oder einen eigenen Client für ntp-gui).",
        "blocks": [_block("Benutzerdefinierte Filterregeln", rules),
                   _block("Ausnahme für ntp-gui (zusätzlich, für $dnsrewrite-Regeln)", exception),
                   _block("Alternative: DNS-Umschreibungen (je Zeile ein Eintrag)", rewrites),
                   _block("Variante „ein Ziel“: CNAME-Stil über time.lan", cname)],
        "notes": notes,
    }


def _dnsmasq_lines(target: str, zones: list[str]) -> str:
    lines = []
    for zone in zones:
        lines.append(f"address=/{zone}/{target}")
    # local=/…/ verhindert, dass AAAA-Anfragen (dnsmasq ≥ 2.86) zum echten DNS gehen.
    lines.append("# AAAA-Anfragen nicht weiterreichen (sonst weichen Geräte über IPv6 aus):")
    lines += [f"local=/{zone}/" for zone in zones]
    return "\n".join(lines)


def snip_dnsmasq(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    zones = collapse_zones(hosts)
    return {
        "kind": "dns",
        "intro": "Datei z. B. /etc/dnsmasq.d/ntp-gui.conf anlegen und dnsmasq neu starten "
                 "(`sudo systemctl restart dnsmasq`).",
        "blocks": [_block("/etc/dnsmasq.d/ntp-gui.conf", "# ntp-gui: Zeitserver erzwingen\n"
                          + _dnsmasq_lines(target, zones))],
        "notes": _dns_common_notes(ip, port) + [
            "`address=/name/` gilt auch für alle Subdomains, deshalb reicht pool.ntp.org für alle Pool-Namen.",
        ],
    }


def snip_pihole(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    zones = collapse_zones(hosts)
    toml_lines = ",\n".join(f'    "{line}"' for line in _dnsmasq_lines(target, zones).splitlines()
                            if not line.startswith("#"))
    exact = sorted({h.lower() for h in hosts}, key=_sort_key)
    hosts_lines = ",\n".join(f'    "{target} {h}"' for h in exact)
    return {
        "kind": "dns",
        "intro": "Pi-hole v6: Einstellungen → All settings → Miscellaneous → misc.dnsmasq_lines "
                 "(Expertenmodus) – oder direkt in /etc/pihole/pihole.toml. Die dnsmasq-Zeilen erfassen "
                 "auch Subdomains und blockieren den IPv6-Umweg. Pi-hole v5: dieselben Zeilen als "
                 "/etc/dnsmasq.d/05-ntp-gui.conf, danach `pihole restartdns`.",
        "blocks": [
            _block("pihole.toml – [misc] dnsmasq_lines (empfohlen)", "[misc]\n  dnsmasq_lines = [\n"
                   + toml_lines + "\n  ]", "toml"),
            _block("Pi-hole v5: /etc/dnsmasq.d/05-ntp-gui.conf", _dnsmasq_lines(target, zones)),
            _block("Alternative: pihole.toml – [dns] hosts (nur exakte Namen)", "[dns]\n  hosts = [\n"
                   + hosts_lines + "\n  ]", "toml"),
        ],
        "notes": _dns_common_notes(ip, port) + [
            "Die Variante `dns.hosts` (bzw. „Local DNS Records“ in der Oberfläche) kennt keine "
            "Subdomains und lässt AAAA-Anfragen durch – Geräte mit IPv6 erreichen dann weiter den echten Server.",
            "Pi-hole v6 liest /etc/dnsmasq.d nur, wenn misc.etc_dnsmasq_d eingeschaltet ist – "
            "misc.dnsmasq_lines braucht das nicht. Nach dem Speichern startet der DNS-Dienst neu.",
        ],
    }


def snip_unbound(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    zones = collapse_zones(hosts)
    rr = _rr(ip) if ip else "A"
    lines = ["server:"]
    for zone in zones:
        lines.append(f'    local-zone: "{zone}." redirect')
        lines.append(f'    local-data: "{zone}. 300 IN {rr} {target}"')
    return {
        "kind": "dns",
        "intro": "In unbound.conf (oder /etc/unbound/unbound.conf.d/ntp-gui.conf) einfügen und "
                 "`sudo unbound-control reload` bzw. Neustart. OPNsense: Dienste → Unbound DNS → "
                 "Overrides kann nur exakte Namen; die Zeilen gehören dort unter "
                 "/usr/local/etc/unbound.opnsense.d/ntp-gui.conf.",
        "blocks": [_block("unbound.conf", "\n".join(lines))],
        "notes": _dns_common_notes(ip, port) + [
            "`redirect` gilt für die Zone samt allen Subdomains; Anfragen nach anderen Typen (z. B. AAAA) "
            "bekommen eine leere Antwort – genau richtig.",
        ],
    }


def _dns_common_notes(ip: str | None, port: int) -> list[str]:
    notes = [
        "Wichtig: ntp-gui selbst darf diese Umschreibung nicht sehen, sonst sucht chronyd seine Quellen "
        "(z. B. pool.ntp.org) bei sich selbst. Am einfachsten: unter System → Einstellungen → Quellen → "
        "„DNS für ntp-gui“ "
        "eigene Server eintragen (DoT/DoH). Sonst nimm ntp-gui im DNS-Server aus (Client-Gruppe ohne "
        "diese Regeln) oder nutze als Quellen Namen, die nicht umgeschrieben werden – etwa die "
        "NTS-Server ptbtime1.ptb.de oder time.cloudflare.com.",
        "Geräte mit fester IP-Adresse statt Namen oder mit eigenem DNS (DNS-over-HTTPS, Google-DNS "
        "fest eingetragen) erreichst du so nicht – dafür ist die Firewall-Umleitung da.",
    ]
    if not ip:
        notes.insert(0, "Die Adresse von ntp-gui ist unbekannt – ersetze <IP-des-Servers> durch die "
                        "LAN-Adresse des Hosts.")
    if port != 123:
        notes.append(f"Achtung: ntp-gui lauscht auf Port {port}. DNS kann nur die Adresse umbiegen, nicht "
                     "den Port – nutze dann die Firewall-Umleitung.")
    return notes


HAIRPIN = (
    "Hairpin-Problem: Stehen Gerät und ntp-gui im selben Netz, geht die Antwort von ntp-gui direkt "
    "an das Gerät – am Router vorbei. Das Gerät hat aber den echten Server gefragt und erwartet die "
    "Antwort von dessen Adresse; die Antwort von ntp-gui verwirft es. Abhilfe: Der Router setzt bei "
    "umgeleiteten Paketen seine eigene Adresse als Absender (Masquerade/SNAT). Dann läuft auch die "
    "Antwort über den Router und wird richtig zurückübersetzt. Nachteil: ntp-gui sieht diese Geräte "
    "dann alle unter der Adresse des Routers. Sauberer ist ein eigenes Netz (VLAN) für ntp-gui – dann "
    "gibt es kein Hairpin-Problem."
)

EXCLUDE = ("Die Ausnahme für ntp-gui selbst ist Pflicht: Ohne sie würden auch die Anfragen von "
           "ntp-gui an seine eigenen Zeitquellen zu ntp-gui zurückgeleitet – eine Schleife, die Uhr "
           "hätte keine echte Quelle mehr.")


def snip_opnsense(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    steps = (
        "1. Firewall → Aliase → Hinzufügen: Name „ntpgui“, Typ Host(s), Inhalt {ip}.\n"
        "2. Firewall → NAT → Portweiterleitung (pfSense: Firewall → NAT → Port Forward) → Hinzufügen:\n"
        "   Schnittstelle:      LAN (für jedes Client-Netz eine eigene Regel)\n"
        "   TCP/IP-Version:     IPv4\n"
        "   Protokoll:          UDP\n"
        "   Quelle:             „Umkehren“ angehakt, Einzelner Host/Alias: ntpgui\n"
        "   Ziel:               „Umkehren“ angehakt, Einzelner Host/Alias: ntpgui\n"
        "   Zielport:           NTP (123)\n"
        "   Umleitungsziel-IP:  ntpgui\n"
        "   Umleitungsziel-Port: {port}\n"
        "   Beschreibung:       ntp-gui: NTP umleiten\n"
        "   NAT-Reflexion:      deaktivieren\n"
        "   Filterregel-Zuordnung: Zugehörige Filterregel hinzufügen (bzw. „Pass“)\n"
        "3. Speichern → Änderungen übernehmen.\n"
        "4. Nur wenn Geräte im selben Netz wie ntp-gui umgeleitet werden (Hairpin):\n"
        "   Firewall → NAT → Ausgehend: Modus „Hybrid“, dann Hinzufügen:\n"
        "   Schnittstelle: LAN, Protokoll: UDP, Quelle: LAN-Netz, Ziel: ntpgui, Zielport: {port},\n"
        "   Übersetzung: Schnittstellenadresse."
    ).format(ip=target, port=port)
    return {
        "kind": "nat",
        "intro": "Portweiterleitung auf der LAN-Seite: Jedes NTP-Paket, das ins Internet will, landet "
                 "bei ntp-gui – auch von Geräten mit fest eingetragener Server-IP.",
        "blocks": [_block("OPNsense / pfSense – Schritte", steps)],
        "notes": [EXCLUDE, HAIRPIN,
                  "Firewall-Umleitung betrifft nur IPv4. Hat dein Netz IPv6, sperre ausgehendes UDP 123 über "
                  "IPv6 für Clients oder leite es ebenfalls um (NPTv6/DNAT mit IPv6-Adresse von ntp-gui).",
                  "NTS-Anfragen (TCP 4460 für den Schlüsselaustausch) werden nicht umgeleitet – NTS-Clients "
                  "bemerken eine Umleitung von UDP 123 und verwerfen die Antworten. Das ist gewollt."],
    }


def snip_mikrotik(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    code = (
        f"/ip firewall address-list add list=ntpgui address={target} comment=\"ntp-gui\"\n"
        "/ip firewall nat add chain=dstnat in-interface-list=LAN protocol=udp dst-port=123 \\\n"
        "    src-address-list=!ntpgui dst-address-list=!ntpgui \\\n"
        f"    action=dst-nat to-addresses={target} to-ports={port} comment=\"ntp-gui: NTP umleiten\"\n"
        "# Hairpin: nur nötig, wenn Clients im selben Netz wie ntp-gui umgeleitet werden\n"
        f"/ip firewall nat add chain=srcnat protocol=udp dst-address={target} dst-port={port} \\\n"
        "    connection-nat-state=dstnat action=masquerade comment=\"ntp-gui: Hairpin\""
    )
    return {
        "kind": "nat",
        "intro": "RouterOS-Terminal (Winbox → New Terminal). `in-interface-list=LAN` setzt die "
                 "Standard-Interface-Liste voraus; sonst `in-interface=bridge` angeben.",
        "blocks": [_block("RouterOS 7", code)],
        "notes": [EXCLUDE, HAIRPIN,
                  "Die Hairpin-Regel greift dank `connection-nat-state=dstnat` nur bei umgeleiteten "
                  "Paketen – Geräte, die ntp-gui direkt fragen, behalten ihre Adresse.",
                  "Die NAT-Regeln müssen vor einer allgemeinen masquerade-/dst-nat-Regel stehen "
                  "(`place-before=0` oder in Winbox nach oben ziehen)."],
    }


def snip_openwrt(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    code = (
        "uci add firewall redirect\n"
        "uci set firewall.@redirect[-1].name='ntp-gui NTP umleiten'\n"
        "uci set firewall.@redirect[-1].target='DNAT'\n"
        "uci set firewall.@redirect[-1].family='ipv4'\n"
        "uci set firewall.@redirect[-1].src='lan'\n"
        "uci set firewall.@redirect[-1].proto='udp'\n"
        "uci set firewall.@redirect[-1].src_dport='123'\n"
        f"uci set firewall.@redirect[-1].src_ip='!{target}'\n"
        f"uci set firewall.@redirect[-1].src_dip='!{target}'\n"
        f"uci set firewall.@redirect[-1].dest_ip='{target}'\n"
        f"uci set firewall.@redirect[-1].dest_port='{port}'\n"
        "uci set firewall.@redirect[-1].reflection='0'\n"
        "# Hairpin: nur nötig, wenn ntp-gui im LAN steht, aus dem umgeleitet wird\n"
        "uci add firewall nat\n"
        "uci set firewall.@nat[-1].name='ntp-gui Hairpin'\n"
        "uci set firewall.@nat[-1].family='ipv4'\n"
        "uci set firewall.@nat[-1].src='lan'\n"
        "uci set firewall.@nat[-1].proto='udp'\n"
        f"uci set firewall.@nat[-1].dest_ip='{target}'\n"
        f"uci set firewall.@nat[-1].dest_port='{port}'\n"
        "uci set firewall.@nat[-1].target='MASQUERADE'\n"
        "uci commit firewall\n"
        "service firewall restart"
    )
    return {
        "kind": "nat",
        "intro": "Per SSH auf dem OpenWrt-Router (ab 22.03 mit fw4/nftables). In LuCI: Netzwerk → "
                 "Firewall → Portweiterleitungen bzw. NAT-Regeln.",
        "blocks": [_block("OpenWrt (uci)", code)],
        "notes": [EXCLUDE, HAIRPIN,
                  "Die Hairpin-Regel maskiert alle NTP-Pakete aus dem LAN an ntp-gui – also auch "
                  "Geräte, die ntp-gui direkt fragen, sofern ihr Weg über den Router führt. Steht "
                  "ntp-gui im selben Netz, betrifft das nur umgeleitete Pakete."],
    }


def snip_nftables(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    code = (
        "# /etc/nftables.d/ntp-gui.nft – LAN-Interface anpassen\n"
        "define LAN_IF = \"<LAN-Interface>\"\n"
        f"define NTPGUI = {target}\n\n"
        "table ip ntpgui {\n"
        "  chain prerouting {\n"
        "    type nat hook prerouting priority dstnat; policy accept;\n"
        "    iifname $LAN_IF ip saddr != $NTPGUI ip daddr != $NTPGUI udp dport 123 \\\n"
        f"      dnat to $NTPGUI:{port} comment \"ntp-gui: NTP umleiten\"\n"
        "  }\n"
        "  chain postrouting {\n"
        "    type nat hook postrouting priority srcnat; policy accept;\n"
        "    # Hairpin: nur umgeleitete Pakete, die ins selbe Netz zurückgehen\n"
        f"    oifname $LAN_IF ct status dnat ip daddr $NTPGUI udp dport {port} masquerade\n"
        "  }\n"
        "}"
    )
    return {
        "kind": "nat",
        "intro": "Für einen Linux-Router mit nftables. Laden mit `sudo nft -f /etc/nftables.d/ntp-gui.nft`; "
                 "dauerhaft per include in /etc/nftables.conf. Läuft ntp-gui auf dem Router selbst, "
                 f"ersetze die dnat-Zeile durch `redirect to :{port}`.",
        "blocks": [_block("nftables", code, "nft")],
        "notes": [EXCLUDE, HAIRPIN,
                  "Das Forwarding (net.ipv4.ip_forward=1) und eine Filterregel, die das Paket zu "
                  "ntp-gui durchlässt, setzt das voraus."],
    }


def snip_unifi(ip: str | None, hosts: list[str], port: int = 123) -> dict:
    target = ip or IP_PLACEHOLDER
    steps = (
        "UniFi Network 9.4 und neuer:\n"
        "  Einstellungen → Policy Table → Create New Policy → NAT\n"
        "UniFi Network 9.3:\n"
        "  Einstellungen → Policy Engine → NAT → Create New\n\n"
        "Regel 1 – Destination NAT:\n"
        "  Typ:            Destination NAT\n"
        "  Interface/Netz: dein Client-Netz (LAN bzw. VLAN)\n"
        "  Protokoll:      UDP\n"
        "  Quelle:         alle – aber ntp-gui ausnehmen (falls angeboten: „Exclude“ "
        f"bzw. Quelle ≠ {target})\n"
        f"  Ziel:           Port 123, Adresse ≠ {target}\n"
        f"  Übersetzte IP:  {target}\n"
        f"  Übersetzter Port: {port}\n\n"
        "Regel 2 – nur für Hairpin (Client und ntp-gui im selben Netz):\n"
        "  Typ: Source NAT / Masquerade, Protokoll UDP,\n"
        f"  Ziel {target} Port {port}, Übersetzung: Adresse des Gateways"
    )
    return {
        "kind": "nat",
        "intro": "Eigene NAT-Regeln (DNAT) gibt es in der Oberfläche erst ab UniFi Network 9.3 "
                 "(Policy Engine), ab 9.4 im Policy Table. Die Feldnamen ändern sich zwischen den "
                 "Versionen leicht – halte dich an die Bedeutung.",
        "blocks": [_block("UniFi Network – Schritte", steps)],
        "notes": [
            EXCLUDE,
            "**Ob die Ausnahme greift**, zeigt die Prüfung unten: „ntp-gui selbst → öffentliche Server“ muss "
            "„erreicht echten Server“ zeigen, und bei „Eigene Quellen“ darf keine Schleife stehen. Fehlt "
            "die Ausnahme, schreibt ntp-gui außerdem laufend das Ereignis „… zeigt auf dich selbst – "
            "vermutlich NAT-Umleitung ohne Ausnahme für ntp-gui“.",
            "Mit AdGuard **und** UniFi-Umleitung (beides zusammen ist üblich) braucht ntp-gui **zwei** "
            "Ausnahmen: im DNS (oder DoT/DoH unter „DNS für ntp-gui“) und in der NAT-Regel. Fehlt eine, "
            "nennt das Ereignis, welche.",
            "Bietet deine Version keine Ausnahme für die Quelle, lege ntp-gui in ein eigenes Netz (VLAN) "
            "und wende die Regel nur auf die Client-Netze an – dann kann ntp-gui sich nicht selbst treffen, "
            "und das Hairpin-Problem entfällt.",
            "Ältere Versionen (vor 9.3) haben keine DNAT-Regeln in der Oberfläche. Dann bleibt die "
            "DNS-Umschreibung (AdGuard Home oder Pi-hole als DNS-Server im DHCP eintragen) oder ein "
            "anderer Router vor/nach dem UniFi-Gateway. Selbst eingespielte iptables-Regeln überleben "
            "Neustarts und Updates nicht.",
            HAIRPIN,
        ],
    }


# ---------------------------------------------------------------------------
# DNS-Umleitung per Firewall (Port 53 → AdGuard Home / Pi-hole), ab 1.4
# ---------------------------------------------------------------------------

DNS_PLACEHOLDER = "<IP-des-DNS-Servers>"

DNS_REDIRECT_NOTES = [
    "**DNS-Umleitung per Firewall** (optional): Manche Geräte fragen fest eingetragene DNS-Server wie "
    "8.8.8.8 und umgehen so die DNS-Umschreibung. Die Regel oben leitet jede DNS-Anfrage (Port 53) aus "
    "dem LAN auf deinen AdGuard Home bzw. Pi-hole um.",
    "Die Ausnahme für ntp-gui ist dabei **Pflicht**: Nutzt ntp-gui unter „DNS für ntp-gui“ eigene "
    "DNS-Server mit klassischem DNS (Port 53), landete seine Anfrage sonst wieder bei AdGuard/Pi-hole – "
    "und damit bei der Umschreibung auf sich selbst. Die Modi **DNS-over-TLS** (853/tcp) und "
    "**DNS-over-HTTPS** (443/tcp) betrifft eine Umleitung von Port 53 nicht.",
    "Den DNS-Server selbst ebenfalls ausnehmen – sonst kommen seine eigenen Anfragen an die "
    "Upstream-Server wieder bei ihm an. Steht er im selben Netz wie die Geräte, gilt das Hairpin-Problem "
    "wie bei NTP (Masquerade/SNAT für umgeleitete Pakete an den DNS-Server).",
    "Nur IPv4. Geräte mit DNS-over-HTTPS (Browser, Android „Privates DNS“) erreicht keine Port-53-Regel.",
]


def _dns_redirect_unifi(ip: str, dns: str) -> str:
    return (
        "Regel 3 – DNS-Umleitung (optional, Destination NAT):\n"
        "  Interface/Netz: dein Client-Netz (LAN bzw. VLAN)\n"
        "  Protokoll:      TCP/UDP\n"
        f"  Quelle:         alle – aber ntp-gui ({ip}) und den DNS-Server ({dns}) ausnehmen\n"
        f"  Ziel:           Port 53, Adresse ≠ {dns}\n"
        f"  Übersetzte IP:  {dns}\n"
        "  Übersetzter Port: 53"
    )


def _dns_redirect_opnsense(ip: str, dns: str) -> str:
    return (
        f"1. Firewall → Aliase → Hinzufügen: Name „dnsausnahme“, Typ Host(s), Inhalt {ip} und {dns}.\n"
        "2. Firewall → NAT → Portweiterleitung → Hinzufügen:\n"
        "   Schnittstelle:      LAN\n"
        "   Protokoll:          TCP/UDP\n"
        "   Quelle:             „Umkehren“ angehakt, Einzelner Host/Alias: dnsausnahme\n"
        f"   Ziel:               „Umkehren“ angehakt, Einzelner Host: {dns}\n"
        "   Zielport:           DNS (53)\n"
        f"   Umleitungsziel-IP:  {dns}\n"
        "   Umleitungsziel-Port: 53\n"
        "   Beschreibung:       DNS auf AdGuard/Pi-hole umleiten (ntp-gui ausgenommen)\n"
        "   Filterregel-Zuordnung: Zugehörige Filterregel hinzufügen (bzw. „Pass“)"
    )


def _dns_redirect_mikrotik(ip: str, dns: str) -> str:
    lines = [f"/ip firewall address-list add list=dnsausnahme address={ip} comment=\"ntp-gui\"",
             f"/ip firewall address-list add list=dnsausnahme address={dns} comment=\"DNS-Server selbst\""]
    for proto in ("udp", "tcp"):
        lines.append(f"/ip firewall nat add chain=dstnat in-interface-list=LAN protocol={proto} dst-port=53 \\\n"
                     f"    src-address-list=!dnsausnahme dst-address=!{dns} \\\n"
                     f"    action=dst-nat to-addresses={dns} to-ports=53 comment=\"DNS umleiten ({proto})\"")
    return "\n".join(lines)


def _dns_redirect_openwrt(ip: str, dns: str) -> str:
    return (
        "uci set firewall.dnsausnahme=ipset\n"
        "uci set firewall.dnsausnahme.name='dnsausnahme'\n"
        "uci set firewall.dnsausnahme.family='ipv4'\n"
        "uci add_list firewall.dnsausnahme.match='src_ip'\n"
        f"uci add_list firewall.dnsausnahme.entry='{ip}'\n"
        f"uci add_list firewall.dnsausnahme.entry='{dns}'\n"
        "uci add firewall redirect\n"
        "uci set firewall.@redirect[-1].name='DNS auf AdGuard/Pi-hole'\n"
        "uci set firewall.@redirect[-1].target='DNAT'\n"
        "uci set firewall.@redirect[-1].family='ipv4'\n"
        "uci set firewall.@redirect[-1].src='lan'\n"
        "uci set firewall.@redirect[-1].proto='tcp udp'\n"
        "uci set firewall.@redirect[-1].src_dport='53'\n"
        "uci set firewall.@redirect[-1].ipset='!dnsausnahme'\n"
        f"uci set firewall.@redirect[-1].src_dip='!{dns}'\n"
        f"uci set firewall.@redirect[-1].dest_ip='{dns}'\n"
        "uci set firewall.@redirect[-1].dest_port='53'\n"
        "uci commit firewall\n"
        "service firewall restart"
    )


def _dns_redirect_nftables(ip: str, dns: str) -> str:
    return (
        "# /etc/nftables.d/ntp-gui-dns.nft – LAN-Interface anpassen\n"
        "define LAN_IF = \"<LAN-Interface>\"\n"
        f"define NTPGUI = {ip}\n"
        f"define DNS_SERVER = {dns}\n\n"
        "table ip ntpgui_dns {\n"
        "  chain prerouting {\n"
        "    type nat hook prerouting priority dstnat; policy accept;\n"
        "    iifname $LAN_IF ip saddr != { $NTPGUI, $DNS_SERVER } ip daddr != $DNS_SERVER \\\n"
        "      meta l4proto { udp, tcp } th dport 53 dnat to $DNS_SERVER:53 comment \"DNS umleiten\"\n"
        "  }\n"
        "}"
    )


DNS_REDIRECTS: dict[str, Callable[[str, str], str]] = {
    "unifi": _dns_redirect_unifi, "opnsense": _dns_redirect_opnsense, "mikrotik": _dns_redirect_mikrotik,
    "openwrt": _dns_redirect_openwrt, "nftables": _dns_redirect_nftables,
}


def dns_redirect(system: str, ip: str | None, dns_ip: str | None) -> tuple[dict, list[str]] | None:
    """Zusatzblock „DNS-Umleitung per Firewall“ für ein NAT-System – mit Ausnahme für ntp-gui."""
    func = DNS_REDIRECTS.get(system)
    if not func:
        return None
    code = func(ip or IP_PLACEHOLDER, dns_ip or DNS_PLACEHOLDER)
    return _block("Optional: DNS-Umleitung per Firewall (Port 53 → AdGuard/Pi-hole)", code), list(DNS_REDIRECT_NOTES)


SYSTEMS: list[tuple[str, str, Callable[..., dict]]] = [
    ("adguard", "AdGuard Home", snip_adguard),
    ("pihole", "Pi-hole", snip_pihole),
    ("dnsmasq", "dnsmasq", snip_dnsmasq),
    ("unbound", "Unbound", snip_unbound),
    ("opnsense", "OPNsense / pfSense", snip_opnsense),
    ("mikrotik", "MikroTik", snip_mikrotik),
    ("openwrt", "OpenWrt", snip_openwrt),
    ("nftables", "nftables (Linux)", snip_nftables),
    ("unifi", "UniFi", snip_unifi),
]
SYSTEM_IDS = [s[0] for s in SYSTEMS]

EXPLAIN = [
    {"title": "DNS-Umschreibung oder Firewall-Umleitung?",
     "text": "Die **DNS-Umschreibung** ist einfach und sauber: Der DNS-Server im LAN antwortet auf "
             "time.windows.com & Co. mit der Adresse von ntp-gui. Sie erreicht aber nur Geräte, die "
             "einen Namen fragen und deinen DNS-Server nutzen. Die **Firewall-Umleitung** (DNAT) fängt "
             "jedes NTP-Paket ab, das ins Internet will – auch fest eingetragene IP-Adressen. Beides "
             "zusammen ist am gründlichsten."},
    {"title": "Hairpin – wenn Gerät und ntp-gui im selben Netz stehen", "text": HAIRPIN},
    {"title": "Nie umschreiben: NTS-Server", "text": NTS_REASON
     + " Deshalb fehlen time.cloudflare.com, nts.netnod.se, ptbtime1–4.ptb.de, nts.time.nl und "
       "ntp.zeitgitter.net absichtlich in der Liste – und eignen sich umgekehrt gut als Quellen für "
       "ntp-gui selbst, weil sie nie zu dir zurückgebogen werden."},
    {"title": "Schleife vermeiden", "text": EXCLUDE},
]


def snippets(system: str, server_ip: Any = None, extra_hosts: list[str] | None = None,
             ntp_port: Any = 123, dns_ip: Any = None) -> dict:
    """Antwort für GET /api/enforce/snippets?system=…&ip=…&dns_ip=…"""
    ip = clean_server_ip(server_ip)
    dns = clean_server_ip(dns_ip)
    port = _port(ntp_port)
    hosts, skipped = merged_hostnames(extra_hosts)
    names = [h["host"] for h in hosts]
    result: dict[str, Any] = {
        "server_ip": ip,
        "placeholder": IP_PLACEHOLDER,
        "ntp_port": port,
        "systems": [{"id": sid, "title": title, "kind": func(None, [], 123)["kind"]}
                    for sid, title, func in SYSTEMS],
        "hostnames": hosts,
        "skipped": skipped,
        "never_rewrite": [{"host": h, "reason": r} for h, r in NEVER_REWRITE.items()],
        "not_ntp": NOT_NTP,
        "explain": EXPLAIN,
    }
    wanted = SYSTEM_IDS if system in (None, "", "all") else [system]
    out = []
    for sid, title, func in SYSTEMS:
        if sid in wanted:
            item = func(ip, names, port)
            extra = dns_redirect(sid, ip, dns)
            if extra:
                item["blocks"].append(extra[0])
                item["notes"] = list(item["notes"]) + extra[1]
            item.update(id=sid, title=title)
            out.append(item)
    if not out:
        result["error"] = f"Unbekanntes System. Möglich: {', '.join(SYSTEM_IDS)}"
    result["snippets"] = out
    return result


# ---------------------------------------------------------------------------
# NTP-Abfrage (SNTP, Modus 3)
# ---------------------------------------------------------------------------

def build_request() -> tuple[bytes, bytes]:
    """48-Byte-Anfrage; Sendezeitstempel zufällig (verrät nicht unsere Uhr, dient als Nonce)."""
    nonce = os.urandom(8)
    return b"\x23" + bytes(39) + nonce, nonce


def _ts(raw: bytes) -> float:
    sec, frac = struct.unpack("!II", raw)
    return sec + frac / 2**32


def parse_reply(data: bytes, nonce: bytes | None = None) -> dict | None:
    """Wertet eine NTP-Antwort aus (Modus 4). None bei ungültigem Paket."""
    if len(data) < 48:
        return None
    lvm, stratum, poll, precision = struct.unpack("!BBbb", data[:4])
    mode = lvm & 7
    if mode not in (4, 5):
        return None
    if nonce is not None and data[24:32] != nonce:
        return None
    root_delay, root_disp = struct.unpack("!iI", data[4:12])
    refid_raw = data[12:16]
    if stratum == 0:
        refid = "KoD:" + refid_raw.decode("ascii", "replace").strip("\x00")
    elif stratum == 1:
        refid = refid_raw.decode("ascii", "replace").strip("\x00 ")
    else:
        refid = refid_raw.hex().upper()
    return {
        "leap": lvm >> 6, "version": (lvm >> 3) & 7, "mode": mode, "stratum": stratum,
        "poll": poll, "precision": precision,
        "root_delay": root_delay / 65536.0, "root_dispersion": root_disp / 65536.0,
        "ref_id": refid_raw.hex().upper(), "ref_label": refid,
        "ref_time": _ts(data[16:24]) - NTP_EPOCH_OFFSET if data[16:24] != bytes(8) else None,
        "tx_time": _ts(data[40:48]) - NTP_EPOCH_OFFSET,
    }


def probe_many(targets: list[tuple[str, int]], timeout: float = 1.0) -> dict[tuple[str, int], dict | None]:
    """Fragt mehrere NTP-Server gleichzeitig (ein Socket je Ziel, ein select)."""
    import select
    pending: dict[socket.socket, tuple[tuple[str, int], bytes, float]] = {}
    results: dict[tuple[str, int], dict | None] = {t: None for t in targets}
    for target in dict.fromkeys(targets):
        host, port = target
        try:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.setblocking(False)
            packet, nonce = build_request()
            sock.sendto(packet, (host, port))
            pending[sock] = (target, nonce, time.monotonic())
        except OSError:
            continue
    deadline = time.monotonic() + timeout
    try:
        while pending:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            ready, _, _ = select.select(list(pending), [], [], left)
            for sock in ready:
                target, nonce, sent = pending[sock]
                try:
                    data, addr = sock.recvfrom(512)
                except OSError:
                    data, addr = b"", None
                reply = parse_reply(data, nonce) if data else None
                if reply is None and data:
                    continue  # fremdes Paket – weiter warten
                if reply is not None:
                    reply["rtt"] = time.monotonic() - sent
                results[target] = reply
                sock.close()
                del pending[sock]
    finally:
        for sock in pending:
            sock.close()
    return results


def _resolve(hosts: list[str], timeout: float) -> dict[str, list[str] | str]:
    """getaddrinfo parallel in Threads; Ergebnis je Name: Adressliste oder Fehlertext."""
    out: dict[str, list[str] | str] = {h: "Zeitüberschreitung bei der DNS-Abfrage" for h in hosts}

    def work(host: str) -> None:
        try:
            infos = socket.getaddrinfo(host, 123, type=socket.SOCK_DGRAM)
            addrs = []
            for info in infos:
                addr = info[4][0]
                if addr not in addrs:
                    addrs.append(addr)
            out[host] = addrs
        except socket.gaierror as exc:
            out[host] = f"Name nicht auflösbar ({exc.strerror or exc})"
        except Exception as exc:  # noqa: BLE001 – nie den Request scheitern lassen
            out[host] = f"DNS-Fehler: {exc}"

    threads = [threading.Thread(target=work, args=(h,), daemon=True, name="enforce-dns") for h in hosts]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return dict(out)


# Öffentliche NTP-Server mit fester Adresse (2026-11 geprüft: time1.google.com → 216.239.35.0,
# Cloudflare-Anycast 162.159.200.1; beide beantworten einfache NTP-Anfragen).
PUBLIC_PROBES = [("216.239.35.0", "Google (time1.google.com)"),
                 ("162.159.200.1", "Cloudflare")]

TEST_HOSTS = ["time.windows.com", "time.apple.com", "time.google.com", "time.android.com",
              "pool.ntp.org", "2.europe.pool.ntp.org", "ntp.ubuntu.com", "0.amazon.pool.ntp.org"]
MAX_TEST_HOSTS = 12


def same_server(reply: dict | None, ours: dict | None) -> bool:
    """Stammt die Antwort von unserem chronyd? Vergleich von Stratum, Referenz-ID und -zeit."""
    if not reply or not ours:
        return False
    if reply.get("stratum") != ours.get("stratum") or reply.get("ref_id") != ours.get("ref_id"):
        return False
    a, b = reply.get("ref_time"), ours.get("ref_time")
    if a is None or b is None:
        return False
    if abs(a - b) > 0.002:
        return False
    # Root-Delay ist bei uns fest bis zur nächsten Messung; ±1 ms Toleranz für Rundung.
    rd_a, rd_b = reply.get("root_delay"), ours.get("root_delay")
    return rd_a is None or rd_b is None or abs(rd_a - rd_b) < 0.001


def ours_from_tracking(tracking: dict | None) -> dict | None:
    """Erwartete Antwortfelder unseres chronyd aus `chronyc tracking`."""
    if not tracking or tracking.get("stratum") is None:
        return None
    return {"stratum": tracking.get("stratum"), "ref_id": str(tracking.get("ref_id") or "").upper(),
            "ref_time": tracking.get("ref_time"), "root_delay": tracking.get("root_delay")}


_CHECK_LOCK = threading.Lock()
_LAST: dict[str, Any] = {"time": 0.0, "mono": 0.0, "result": None}  # nur mit result gültig
MIN_INTERVAL = 30.0


def check(server_ips: list[str], hostnames: list[str] | None = None, ntp_port: int = 123,
          tracking: dict | None = None, source_hosts: list[str] | None = None,
          *, force: bool = False, now: Callable[[], float] = time.time,
          clock: Callable[[], float] = time.monotonic,
          resolver: Callable[..., dict] | None = None,
          prober: Callable[..., dict] | None = None,
          sources: list[dict] | None = None, resolver_info: dict | None = None) -> dict:
    """Prüft, ob DNS-Umschreibung und Firewall-Umleitung wirken (höchstens alle 30 s).

    server_ips: Adressen, unter denen ntp-gui erreichbar ist (eigene Interfaces + Browser-Adresse).
    tracking:   Ergebnis von chrony.tracking() als Vergleich.
    source_hosts: Namen der eigenen Zeitquellen (Schleifen-Erkennung).
    sources:    eigene Quellen als [{"host", "nts"}] (Name oder feste IP) für die Kette
                „Name → Resolver → Adresse → Antwort“ (1.5); ohne: aus source_hosts.
    resolver_info: welcher Resolver ntp-gui gerade auflöst (resolver_label()).
    now liefert die angezeigte Uhrzeit, clock (monotonic) misst den Abstand – ein Sprung der
    Systemuhr (Pi ohne RTC, chrony stellt die Uhr) verlängert die Sperre nicht.
    """
    with _CHECK_LOCK:
        t = now()
        mono = clock()
        if not force and _LAST["result"] is not None and mono - _LAST["mono"] < MIN_INTERVAL:
            cached = dict(_LAST["result"])
            cached["cached"] = True
            cached["retry_after"] = round(MIN_INTERVAL - (mono - _LAST["mono"]), 1)
            return cached
        result = _run_check(server_ips, hostnames, _port(ntp_port), tracking, source_hosts or [],
                            resolver or _resolve, prober or probe_many, sources, resolver_info)
        result["time"] = t
        result["cached"] = False
        _LAST.update(time=t, mono=mono, result=result)
        return result


def _reset_rate_limit() -> None:
    with _CHECK_LOCK:
        _LAST.update(time=0.0, mono=0.0, result=None)


def _run_check(server_ips, hostnames, port, tracking, source_hosts, resolver, prober,
               own_sources=None, resolver_info=None) -> dict:
    started = time.monotonic()
    ours_ips = set()
    for ip in server_ips or []:
        try:
            ours_ips.add(str(ipaddress.ip_address(str(ip).strip("[]"))))
        except ValueError:
            continue
    tests = []
    for host in list(TEST_HOSTS) + list(hostnames or []):
        host = str(host).strip().lower().rstrip(".")
        if host and _HOST_RE.match(host) and host not in tests and not is_never_rewrite(host):
            tests.append(host)
    tests = tests[:MAX_TEST_HOSTS]
    sources = []
    for host in source_hosts:
        host = str(host).strip().lower().rstrip(".")
        if host and _HOST_RE.match(host) and host not in sources:
            sources.append(host)
    sources = sources[:8]
    chain_entries = _chain_entries(own_sources, sources)
    for entry in chain_entries:
        if entry["by"] == "name" and entry["host"] not in sources:
            sources.append(entry["host"])

    resolved = resolver(list(dict.fromkeys(tests + sources)), 1.2)

    # NTP-Ziele: unser eigener chronyd (lokal), je Name die erste Adresse, öffentliche Fest-IPs.
    targets: list[tuple[str, int]] = [("127.0.0.1", port)]
    for host in tests:
        addrs = resolved.get(host)
        if isinstance(addrs, list) and addrs:
            first = next((a for a in addrs if ":" not in a), addrs[0])
            targets.append((first, port if first in ours_ips else 123))
    targets += [(ip, 123) for ip, _label in PUBLIC_PROBES]
    chain_targets = {}
    for entry in chain_entries:
        addr = _chain_address(entry, resolved)
        if addr:
            chain_targets[entry["host"]] = addr
            targets.append((addr, 123))
    remaining = max(0.3, min(1.2, 2.8 - (time.monotonic() - started)))
    replies = prober(targets, remaining)

    ours = replies.get(("127.0.0.1", port)) or ours_from_tracking(tracking)
    ours_note = None
    if not ours:
        ours_note = ("Eigener chronyd liefert keine Vergleichswerte – der Abgleich per NTP-Antwort ist "
                     "nicht möglich, nur die DNS-Prüfung.")

    rows = []
    for host in tests:
        addrs = resolved.get(host)
        row: dict[str, Any] = {"host": host, "addresses": addrs if isinstance(addrs, list) else []}
        if not isinstance(addrs, list):
            row.update(level="warn", state="dns_error", verdict=str(addrs))
            rows.append(row)
            continue
        if not addrs:
            row.update(level="warn", state="dns_error", verdict="Keine Adresse erhalten.")
            rows.append(row)
            continue
        to_us = [a for a in addrs if a in ours_ips]
        first = next((a for a in addrs if ":" not in a), addrs[0])
        reply = replies.get((first, port if first in ours_ips else 123))
        row["resolves_to_us"] = bool(to_us)
        row["reply"] = _slim(reply)
        if to_us and len(to_us) == len(addrs):
            row.update(level="good", state="dns_rewrite",
                       verdict="DNS-Umschreibung wirkt: Der Name zeigt auf diesen Server.")
        elif to_us:
            row.update(level="warn", state="dns_partial",
                       verdict="Der Name zeigt teils auf diesen Server, teils woandershin – vermutlich "
                               "fehlt die IPv6-Sperre (AAAA). Geräte mit IPv6 erreichen dann den echten Server.")
        elif same_server(reply, ours):
            row.update(level="good", state="answered_by_us",
                       verdict=f"Der Name zeigt auf {first}, dort antwortet aber dieser Server – "
                               "DNS-Umschreibung auf eine Adresse, die der Container nicht als eigene "
                               "kennt (z. B. Host-IP im Bridge-Netz). Wirkt.")
        elif reply is None:
            row.update(level="info", state="no_reply",
                       verdict="Nicht umgeschrieben; der echte Server antwortet nicht. Vermutlich sperrt "
                               "die Firewall NTP nach außen – dann müssen Geräte deinen Server kennen.")
        else:
            row.update(level="warn", state="not_redirected",
                       verdict="Nicht umgeschrieben: Der Name zeigt auf den echten Server. Prüfe die "
                               "DNS-Regeln – und ob ntp-gui überhaupt deinen DNS-Server nutzt.")
        rows.append(row)

    public = []
    for ip, label in PUBLIC_PROBES:
        reply = replies.get((ip, 123))
        entry: dict[str, Any] = {"ip": ip, "label": label, "reply": _slim(reply)}
        if reply is None:
            entry.update(level="info", state="no_reply",
                         verdict="Keine Antwort. Entweder sperrt die Firewall NTP nach außen, oder dieser "
                                 "Host hat kein Internet. Für ntp-gui selbst wäre das ein Problem: Es braucht "
                                 "Zugriff auf seine Zeitquellen.")
        elif same_server(reply, ours):
            entry.update(level="crit", state="loop",
                         verdict="Schleife! Die Anfrage von ntp-gui an einen öffentlichen Server wurde zu "
                                 "ntp-gui selbst zurückgeleitet. In der Firewall-Umleitung fehlt die Ausnahme "
                                 "für ntp-gui – trag die Adresse dieses Hosts als Ausnahme ein.")
        else:
            entry.update(level="good", state="direct",
                         verdict="ntp-gui erreicht den echten Server – die Ausnahme in der Firewall greift "
                                 "(oder es gibt keine Umleitung). Ob Geräte umgeleitet werden, kann nur ein "
                                 "Test auf einem Gerät zeigen (siehe Selbsttest).")
        public.append(entry)

    loops = []
    for host in sources:
        addrs = resolved.get(host)
        if isinstance(addrs, list) and any(a in ours_ips for a in addrs):
            loops.append({"host": host, "level": "crit", "cause": "dns",
                          "verdict": f"Die eigene Zeitquelle {host} zeigt per DNS auf ntp-gui selbst. "
                                     "chronyd fragt dann sich selbst. Nimm den ntp-gui-Host von der "
                                     "DNS-Umschreibung aus oder nutze andere Quellen (z. B. ptbtime1.ptb.de)."})
    upstream = [_chain_row(entry, resolved, chain_targets.get(entry["host"]), replies, ours, ours_ips,
                           resolver_info) for entry in chain_entries]
    looped = {l["host"] for l in loops}
    for row in upstream:
        if row["state"] in ("self_reply", "self_address") and row["host"] not in looped:
            loops.append({"host": row["host"], "level": "crit", "cause": row.get("cause"),
                          "verdict": row["verdict"]})
            looped.add(row["host"])

    levels = ([r["level"] for r in rows] + [p["level"] for p in public] + [l["level"] for l in loops]
              + [u["level"] for u in upstream])
    if "crit" in levels:
        overall, summary = "crit", "Es gibt eine Schleife – ntp-gui erreicht seine eigenen Quellen nicht."
    elif any(r["state"] in ("dns_rewrite", "answered_by_us") for r in rows):
        n = sum(r["state"] in ("dns_rewrite", "answered_by_us") for r in rows)
        overall = "good" if n == len(rows) else "warn"
        summary = f"{n} von {len(rows)} geprüften Namen landen bei diesem Server."
    else:
        overall = "info"
        summary = ("Keine DNS-Umschreibung erkannt. Mit Firewall-Umleitung ist das normal – ob sie wirkt, "
                   "zeigt der Selbsttest auf einem Gerät oder die Client-Liste.")
    return {
        "level": overall, "summary": summary, "hosts": rows, "public": public, "loops": loops,
        "upstream": upstream, "resolver": resolver_info or {"label": "System-DNS des Containers"},
        "ours": _slim(ours), "ours_note": ours_note, "server_ips": sorted(ours_ips),
        "resolver_note": "Geprüft mit dem DNS-Server, den dieser Container nutzt. Nutzen deine Geräte "
                         "einen anderen (z. B. Pi-hole per DHCP, ntp-gui aber den Router), kann das "
                         "Ergebnis abweichen.",
        "duration": round(time.monotonic() - started, 2),
    }


def _chain_entries(own_sources: list[dict] | None, names: list[str]) -> list[dict]:
    """Eigene Quellen für die Upstream-Kette: [{"host", "by": name|ip, "nts"}], höchstens 8."""
    out: list[dict] = []
    seen: set[str] = set()
    raw = own_sources if own_sources is not None else [{"host": h} for h in names]
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        host = str(entry.get("host") or "").strip().lower().rstrip(".")
        if not host or host in seen:
            continue
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
            host, by = str(ip), "ip"
        except ValueError:
            if not _HOST_RE.match(host):
                continue
            by = "name"
        seen.add(host)
        out.append({"host": host, "by": by, "nts": bool(entry.get("nts"))})
    return out[:8]


def _chain_address(entry: dict, resolved: dict) -> str | None:
    if entry["by"] == "ip":
        return entry["host"]
    addrs = resolved.get(entry["host"])
    if isinstance(addrs, list) and addrs:
        return next((a for a in addrs if ":" not in a), addrs[0])
    return None


def resolver_label(dns: dict | None) -> dict:
    """Welcher Resolver ntp-gui gerade Namen auflöst – für die Kette im Selbsttest.
    Keine Pfade von DoH-Adressen (Konto-Kennungen): die Upstream-Labels sind schon gekürzt."""
    dns = dns or {}
    effective = dns.get("effective_mode") or "system"
    if effective == "system":
        return {"mode": "system", "label": "System-DNS des Containers",
                "note": "Schreibt dieser DNS Zeitserver-Namen um, landet ntp-gui bei sich selbst."}
    labels = [str(u.get("label")) for u in dns.get("upstreams") or [] if u.get("label")]
    text = f"{dns.get('effective_label') or effective}" + (f": {', '.join(labels[:4])}" if labels else "")
    note = None
    if dns.get("state") == "fallback":
        note = "Gerade Rückfall auf den System-DNS – die eigenen Server antworten nicht."
    elif dns.get("state") in ("down", "failing"):
        note = "Der Weiterleiter läuft nicht oder bekommt keine Antwort."
    return {"mode": effective, "label": text, "state": dns.get("state"), "note": note}


def _chain_row(entry, resolved, addr, replies, ours, ours_ips, resolver_info) -> dict:
    """Eine Zeile „Name → Resolver → Adresse → Antwort“ mit Urteil."""
    import loopguard
    host = entry["host"]
    row: dict[str, Any] = {"host": host, "by": entry["by"], "nts": entry["nts"],
                           "resolver": (resolver_info or {}).get("label") if entry["by"] == "name" else None,
                           "addresses": [], "address": addr, "reply": None}
    if entry["by"] == "name":
        addrs = resolved.get(host)
        if not isinstance(addrs, list) or not addrs:
            row.update(level="warn", state="dns_error",
                       verdict=(str(addrs) if isinstance(addrs, str) else "Keine Adresse erhalten.")
                       + " chronyd kann diese Quelle dann nicht nutzen.")
            return row
        row["addresses"] = addrs
    reply = replies.get((addr, 123)) if addr else None
    row["reply"] = _slim(reply)
    ip = loopguard._ip(addr)

    def own(text: str | None) -> bool:
        cand = loopguard._ip(text)
        return bool(text) and (text in ours_ips or (cand is not None and (str(cand) in ours_ips or cand.is_loopback)))
    # Alle Adressen des Namens prüfen (wie die Schleifen-Liste): AdGuard kann nur AAAA auf
    # ntp-gui umschreiben, während A echt bleibt – chronyd nimmt dann je nach Netz die eigene.
    own_hits = [a for a in (row["addresses"] or [addr]) if own(a)]
    if own(addr) or own_hits:
        cause = "dns" if entry["by"] == "name" else "self_ip"
        verdict = loopguard.sentence(host if entry["by"] == "name" else None, addr, cause) + "."
        if own_hits and not own(addr):
            fam = lambda a: "IPv6" if ":" in a else "IPv4"  # noqa: E731
            hit_fams = sorted({fam(a) for a in own_hits})
            other = sorted({fam(a) for a in row["addresses"] if not own(a)})
            verdict += (f" Betroffen ist die {'/'.join(hit_fams)}-Antwort des Namens"
                        + (f"; die {'/'.join(other)}-Antwort zeigt auf einen fremden Server" if other else "")
                        + " – chronyd kann je nach Netz die eigene Adresse nehmen.")
        row.update(level="crit", state="self_address", cause=cause, verdict=verdict)
        return row
    if reply is not None and ours and loopguard.fingerprint_match(reply, ours):
        cause = ("dns" if entry["by"] == "name" and ip is not None and (ip.is_private or ip.is_link_local)
                 else "nat")
        row.update(level="crit", state="self_reply", cause=cause,
                   verdict=loopguard.sentence(host if entry["by"] == "name" else None, addr, cause)
                   + (". Die Adresse ist richtig, aber die Antwort kommt von diesem Server." if cause == "nat"
                      else ". Die Adresse liegt im LAN und wird zu diesem Server weitergeleitet."))
        return row
    if reply is None:
        row.update(level="warn", state="no_reply",
                   verdict="Keine Antwort von dieser Adresse. Sperrt die Firewall NTP nach außen, oder ist der "
                           "Server weg? chronyd bekommt von dieser Quelle dann auch nichts.")
        return row
    label = reply.get("ref_label") or reply.get("ref_id") or "?"
    row.update(level="good", state="foreign",
               verdict=f"Ein fremder Server antwortet (Stratum {reply.get('stratum')}, Referenz {label}) – "
                       "keine Schleife.")
    return row


def _slim(reply: dict | None) -> dict | None:
    if not reply:
        return None
    return {k: reply.get(k) for k in ("stratum", "ref_id", "ref_label", "ref_time", "root_delay",
                                       "root_dispersion", "rtt") if k in reply}


def source_hosts_from(cfg: dict) -> list[str]:
    """Namen der eigenen Zeitquellen aus den Einstellungen (ntp_sources)."""
    hosts = []
    for entry in cfg.get("ntp_sources") or []:
        host = str((entry or {}).get("host") or "")
        try:
            ipaddress.ip_address(host)
            continue
        except ValueError:
            pass
        if host:
            hosts.append(host)
    return hosts


def rewritten_sources(source_hosts: list[str], extra: list[str] | None = None) -> list[str]:
    """Eigene Quellen, die unter die Namen der Umschreib-Anleitungen fallen (pool.ntp.org,
    de.pool.ntp.org, time.windows.com …) – schreibt der DNS im LAN sie um und fragt ntp-gui
    denselben DNS, landet chronyd bei sich selbst."""
    hosts, _skipped = merged_hostnames(extra)
    zones = collapse_zones([h["host"] for h in hosts])
    out = []
    for raw in source_hosts or []:
        host = str(raw or "").strip().rstrip(".").lower()
        if host and host not in out and any(host == z or host.endswith("." + z) for z in zones):
            out.append(host)
    return out


def last_loops() -> list[dict]:
    """Schleifen aus der letzten Prüfung (check), ohne neu zu prüfen."""
    with _CHECK_LOCK:
        result = _LAST["result"]
    return list((result or {}).get("loops") or [])


def check_ran() -> bool:
    with _CHECK_LOCK:
        return _LAST["result"] is not None


def api_snippets(query: dict, cfg: dict) -> dict:
    """GET /api/enforce/snippets – query: system, ip, dns_ip (AdGuard/Pi-hole für die DNS-Umleitung)."""
    return snippets(query.get("system") or "all", query.get("ip"), cfg.get("enforce_hostnames") or [],
                    cfg.get("ntp_port", 123), query.get("dns_ip"))


def api_check(query: dict, cfg: dict, own_addresses: list[str], tracking: dict | None,
              dns: dict | None = None) -> dict:
    """GET /api/enforce/check – query: ip (Adresse aus Sicht des Browsers)."""
    ips = list(own_addresses or [])
    extra = clean_server_ip(query.get("ip"))
    if extra:
        ips.append(extra)
    return check(ips, cfg.get("enforce_hostnames") or [], cfg.get("ntp_port", 123), tracking,
                 source_hosts_from(cfg), sources=[e for e in cfg.get("ntp_sources") or [] if isinstance(e, dict)],
                 resolver_info=resolver_label(dns))
