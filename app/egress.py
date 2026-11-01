"""Zentraler Datenschutzfilter für alles, was die Instanz verlässt.

Diagnosepaket, Aufzeichnungen und alles, was mit der Community geteilt wird,
laufen durch dieses Modul. Ziel: Aus einem Export darf sich **kein Standort**
bestimmen lassen und keine Kennung des Geräts oder seiner Clients.

Entfernt bzw. ersetzt werden:

* Koordinaten, Höhe, Bewegung (lat/lon/alt…, speed/track/climb) – auch als
  Zahlenpaar im Freitext, in NMEA-Sätzen und in rohen gpsd-JSON-Zeilen;
* Satellitenwinkel (Azimut/Elevation) – PRN, System, Signalstärke und
  „benutzt“ bleiben;
* Seriennummern (USB, DMI, Teile von /dev/serial/by-id), MAC-Adressen und die
  daraus abgeleiteten PTP-Uhr-IDs;
* öffentliche IP-Adressen (→ ``<öffentliche-IP>``), auch als chrony-RefID;
  private, Link-Local- und CGNAT-Adressen → stabile Pseudonyme ``client-01`` …
  (Loopback, Multicast und private Netzbereiche wie ``192.168.0.0/16`` bleiben);
* eigene Host- und Domainnamen (→ ``<hostname-1>`` …) – nur bekannte
  öffentliche Zeitdienste (PTB, Cloudflare, Netnod, NTP Pool …) bleiben lesbar;
* Zertifikatsnamen, E-Mail-Adressen, Zugangsdaten, frei gewählter Titel;
* Zeitzonennamen (``Europe/Berlin`` verrät die Region) – nur der UTC-Versatz
  bleibt.

Für ``purpose="community"`` werden zusätzlich Laufzeiten (Delay) auf 10 ms
gerundet: ein Satz genauer Laufzeiten zu bekannten Servern erlaubt sonst eine
grobe Ortung.

``check_no_leaks`` ist die letzte Schranke vor jedem Export: Findet sie etwas,
muss der Export abbrechen.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
from typing import Any

PURPOSES = ("diagnostics", "recording", "community")

PUBLIC_IP = "<öffentliche-IP>"
REMOVED = "<entfernt>"

# Kategorien im Bericht → deutsche Erklärung (MANIFEST, Vorschau im Dashboard).
CATEGORIES: dict[str, str] = {
    "position": "Koordinaten, Höhe und Positionsfehler (auch in NMEA-Sätzen und im Freitext) – "
                "sie verraten direkt, wo das Gerät steht.",
    "bewegung": "Geschwindigkeit, Kurs und Steigrate des GPS – zusammen mit der Zeit ein Bewegungsprofil.",
    "satellitenwinkel": "Azimut und Elevation der Satelliten – aus den Winkeln zu einer festen Zeit "
                        "lässt sich der Standort zurückrechnen.",
    "seriennummer": "Seriennummern (USB, Mainboard/DMI, /dev/serial/by-id) – eindeutige Kennung deiner Hardware.",
    "mac": "MAC-Adressen – eindeutige Kennung deiner Netzwerkkarten.",
    "uhr_id": "PTP-Uhr-IDs – sie werden aus der MAC-Adresse gebildet.",
    "oeffentliche_ip": "Öffentliche IP-Adressen – sie verraten Anschluss und ungefähren Ort.",
    "private_ip": "Private IP-Adressen (LAN) – durch stabile Pseudonyme wie client-01 ersetzt, damit "
                  "Zusammenhänge erkennbar bleiben, aber keine Geräte.",
    "hostname": "Eigene Host- und Domainnamen – ersetzt durch <hostname-1> usw. Bekannte öffentliche "
                "Zeitserver (PTB, Cloudflare, Netnod, NTP Pool …) bleiben lesbar.",
    "e_mail": "E-Mail-Adressen.",
    "zertifikat": "Namen im NTS-Zertifikat (Common Name, alternative Namen, Aussteller) – das ist deine Domain.",
    "zeitzone": "Zeitzonennamen („Kontinent/Stadt“ oder ihre Kürzel) – sie verraten die Region; nur der UTC-Versatz bleibt.",
    "zugangsdaten": "Passwörter, Hashes und Schlüssel.",
    "titel": "Der frei wählbare Titel des Dashboards – er enthält oft einen Ort oder Namen.",
    "refid": "chrony-Referenz-IDs, die eine IP-Adresse kodieren.",
    "gpsd_rohdaten": "Rohdaten-Meldungen von gpsd (RTCM, Subframes, Lage …) mit Positions- oder Stationsdaten.",
    "latenz_gerundet": "Laufzeiten zu Servern auf 10 ms gerundet – viele genaue Laufzeiten erlauben eine grobe Ortung.",
}

# ---------------------------------------------------------------------------
# Bekannte, unbedenkliche Namen
# ---------------------------------------------------------------------------

# Öffentliche Zeitdienste: Name bleibt, damit Diagnosen lesbar bleiben.
PUBLIC_TIME_HOSTS = {
    "ptbtime1.ptb.de", "ptbtime2.ptb.de", "ptbtime3.ptb.de", "ptbtime4.ptb.de",
    "time.cloudflare.com", "nts.netnod.se", "time.google.com", "time1.google.com",
    "time2.google.com", "time3.google.com", "time4.google.com", "time.windows.com",
    "time.apple.com", "time.euro.apple.com", "time.asia.apple.com", "time.aws.com",
    "time.nist.gov", "time.facebook.com", "time1.facebook.com", "time2.facebook.com",
    "time3.facebook.com", "time4.facebook.com", "time5.facebook.com", "ntp.se", "nts.ntp.se",
    "time.nl", "nts.time.nl", "ntppool1.time.nl", "ntppool2.time.nl", "ntp.ripe.net",
    "nts.sth1.ntp.se", "nts.sth2.ntp.se", "ntp1.glypnod.com", "ntp2.glypnod.com",
    "pool.ntp.org", "ntp.org", "ntppool.org",
}
PUBLIC_TIME_SUFFIXES = (".pool.ntp.org", ".nts.netnod.se", ".netnod.se", ".nist.gov", ".ntp.se")
# Hersteller- und Projektdomains, die in Gerätenamen, Logs oder Links auftauchen.
HARMLESS_DOMAINS = {
    "u-blox.com", "www.u-blox.com", "github.com", "chrony-project.org", "gpsd.io",
    "linuxptp.sourceforge.net", "letsencrypt.org", "example.com", "example.org", "example.net",
    "localhost.localdomain",
}

KNOWN_CAS = ("let's encrypt", "zerossl", "google trust services", "digicert", "sectigo",
             "buypass", "globalsign", "isrg", "actalis", "ssl.com", "certum", "entrust")

DEFAULT_TITLES = {"", "NTP / PTP Time Server"}

# ISO-3166-Länderdomains (ohne die, die sich mit Dateiendungen beißen).
_CCTLDS = set("""
ac ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bm bn bo br bs
bt bw by bz ca cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg er
es et eu fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr
ht hu id ie il im iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls
lt lu lv ly ma mc me mg mh ml mm mn mo mp mq mr mt mu mv mw mx my mz na nc ne nf ng ni nl no np
nr nu nz om pa pe pf pg ph pk pl pn pr pt pw qa re ro ru rw sa sb sc sd se sg si sj sk sl sm sn
sr ss st su sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug uk uy uz va vc ve
vg vi vn vu wf ws ye yt za zm zw
""".split())
_GTLDS = set("""
com net org info biz io dev app cloud online site xyz top tech shop store blog page name pro mobi
asia gmbh berlin hamburg bayern koeln cologne ruhr saarland nrw wien tirol swiss
london nyc paris amsterdam brussels vlaanderen bzh cymru wales scot eus gal barcelona madrid
quebec tokyo osaka sydney melbourne istanbul moscow gov edu mil int arpa
local lan home internal intranet localdomain box corp private
""".split())
TLDS = _CCTLDS | _GTLDS

# ---------------------------------------------------------------------------
# Schlüssel strukturierter Daten
# ---------------------------------------------------------------------------


def _norm(key: Any) -> str:
    return re.sub(r"[\s_\-.]", "", str(key)).lower()


POSITION_KEYS = {
    "lat", "lon", "lng", "long", "latitude", "longitude", "alt", "althae", "altmsl", "altitude",
    "geoidsep", "undulation", "ecefx", "ecefy", "ecefz", "ecefvx", "ecefvy", "ecefvz", "ecefpacc",
    "ecefvacc", "reln", "rele", "reld", "position", "location", "coordinates", "coords", "latlon",
    "latlng", "geo", "geolocation", "epx", "epy", "epv", "eph", "dgpssta", "basestation",
    "antennaposition",
}
MOTION_KEYS = {"speed", "track", "climb", "heading", "course", "magtrack", "magvar", "veln", "vele",
               "veld", "eps", "epd", "epc", "velocity", "yaw", "pitch", "roll"}
ANGLE_KEYS = {"az", "el", "azimuth", "elevation", "elev", "azim"}
SERIAL_KEYS = {"serial", "serialnumber", "serialno", "productserial", "boardserial", "chassisserial",
               "productuuid", "iserial", "idserial", "idserialshort", "machineid", "bootid", "uuid"}
MAC_KEYS = {"mac", "macaddr", "macaddress", "hwaddr", "permaddr", "lladdr", "ether"}
SECRET_KEYS = {"password", "passwd", "hash", "secret", "token", "apikey", "auth", "credentials",
               "privatekey", "cookie", "authorization"}
CERT_KEYS = {"subject", "commonname", "cn", "altnames", "san", "subjectaltname", "names", "certnames"}
ISSUER_KEYS = {"issuer", "certissuer", "issuercn"}
HOST_KEYS = {"hostname", "host", "fqdn", "nodename", "servername", "ntsservername", "domain"}
TZ_KEYS = {"timezone", "tz", "timezonename", "zone", "tzname", "localtimezone"}
TITLE_KEYS = {"webtitle"}
DELAY_KEYS = {"delay", "rootdelay", "peerdelay", "rtt", "latency", "roundtrip", "roundtripdelay",
              "delayms", "rttms", "latencyms", "meandelay"}
CLOCK_ID_KEYS = {"clockidentity", "grandmasteridentity", "parentportidentity", "portidentity",
                 "gmidentity"}
REFID_KEYS = {"refid", "referenceid"}

# gpsd: was je Meldungsklasse bleiben darf.
GPSD_ALLOWED = {
    "TPV": {"class", "device", "mode", "status", "time", "ept", "leapseconds", "tag"},
    "SKY": {"class", "device", "time", "tag", "nSat", "uSat", "gdop", "hdop", "pdop", "tdop", "vdop",
            "xdop", "ydop", "satellites", "prRes", "qual"},
    "GST": {"class", "device", "time", "tag", "rms"},
    "PPS": None, "TOFF": None, "VERSION": None, "DEVICES": None, "DEVICE": None, "WATCH": None,
    "ERROR": None, "POLL": None, "OSC": None,
}
GPSD_SAT_ALLOWED = {"PRN", "gnssid", "svid", "sigid", "freqid", "ss", "used", "health"}
GPSD_DROP = {"RAW", "RTCM2", "RTCM3", "AIS", "SUBFRAME", "IMU", "ATT", "NAV", "GGA", "RMC"}

# ---------------------------------------------------------------------------
# Muster für Freitext
# ---------------------------------------------------------------------------

_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:.-])(?:[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}"
                     r"|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})(?![0-9A-Fa-f:.-])")
# PTP-Uhr-ID: 001122.fffe.334455 (ptp4l) oder 00:11:22:ff:fe:33:44:55
_CLOCK_ID_RE = re.compile(r"(?<![0-9A-Fa-f.:])(?:[0-9A-Fa-f]{6}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{6}"
                          r"|(?:[0-9A-Fa-f]{2}:){7}[0-9A-Fa-f]{2})(?:-\d+)?(?![0-9A-Fa-f.:])")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?![\w-])")
_IPV4_RE = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})"
                      r"(/\d{1,2})?(?!\d|\.\d)")
_IPV6_RE = re.compile(r"(?<![\w.%])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?::\d{1,3}(?:\.\d{1,3}){3})?)"
                      r"(%[\w.-]+)?(/\d{1,3})?(?![\w:%]|\.\d)")
_DOMAIN_RE = re.compile(r"(?<![\w@-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+([A-Za-z]{2,24}))\.?"
                        r"(?![\w-]|\.[A-Za-z0-9])")
_ZONE_RE = re.compile(r"\b(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific"
                      r"|Brazil|Canada|Chile|Mexico|US)/[A-Za-z][A-Za-z_+-]*(?:/[A-Za-z][A-Za-z_+-]*)?")
_ZONE_ABBR_RE = re.compile(r"(?<![\w/])(?:CET|CEST|MEZ|MESZ|EET|EEST|WET|WEST|BST|IST|GMT\+\d+|EST|EDT|CST|CDT"
                           r"|MST|MDT|PST|PDT|AKST|AKDT|HST|AEST|AEDT|ACST|ACDT|AWST|NZST|NZDT|JST|KST|MSK"
                           r"|HKT|SGT)(?![\w/])")
# Zwei Dezimalzahlen mit ≥ 4 Nachkommastellen dicht beieinander (48.137154, 11.576124)
_NUM = r"[-+]?\d{1,3}\.\d{4,}"
_COORD_PAIR_RE = re.compile(r"(?<![\w.])(" + _NUM + r")(?:\s*°)?(?:\s*[NSns](?!\w))?\s*[,;/ \t]\s*"
                            r"(?:lon\w*\s*[:=]?\s*)?(" + _NUM + r")(?:\s*°)?(?:\s*[EWOew](?!\w))?(?![\d.])")
# 48°08'13.8"N 11°34'34.0"E bzw. 48°08.230'N
_COORD_DMS_RE = re.compile(r"\d{1,3}\s*°\s*\d{1,2}(?:[.,]\d+)?\s*['′](?:\s*\d{1,2}(?:[.,]\d+)?\s*(?:\"|″|''))?"
                           r"\s*[NSEWO]")
# 48.137154° N
_COORD_DEG_RE = re.compile(r"[-+]?\d{1,3}\.\d{3,}\s*°\s*[NSEWO]\b")
# NMEA-Format ddmm.mmmm,N,dddmm.mmmm,E
_COORD_NMEA_RE = re.compile(r"\d{4}\.\d+\s*,\s*[NS]\s*,\s*\d{5}\.\d+\s*,\s*[EW]")
# key=value / "key": value im Freitext
_KV_POS_RE = re.compile(r"(?i)(?<![\w])([\"']?)(lat|lon|lng|latitude|longitude|alt|althae|altmsl|altitude|geoidsep"
                        r"|ecef[xyz]|azimuth|elevation|az|el)\1(\s*[:=]\s*)"
                        r"([\"']?)[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?\4"
                        r"|(?<![\w])([\"']?)(speed|track|climb|heading)\5(\s*[:=]\s*)"
                        r"([\"']?)[-+]?\d+\.\d+(?:e[-+]?\d+)?\8")
_NMEA_RE = re.compile(r"\$(?:G[PNLABQ]|BD|QZ|PQ)(GGA|RMC|GLL|GNS|VTG|GSV|GST|HDT|THS|RMB|RMA|DTM)\b[^\s\"']*")
_BYID_RE = re.compile(r"(?<![\w-])((?:usb|usbv2|pci|ata|nvme|scsi)-[A-Za-z0-9._+:,-]*?)"
                      r"(-if\d+(?:-port\d+)?)(?![\w])")
_SERIAL_KV_RE = re.compile(r"(?i)\b(serial(?:[ _-]?(?:number|no|nr))?|product_serial|board_serial|chassis_serial"
                           r"|product_uuid|iSerial|ID_SERIAL(?:_SHORT)?|Seriennummer)(\s*[:=]\s*\"?)"
                           r"(?!<seriennr>)([A-Za-z0-9][\w.:-]{2,})")
_REFID_CTX_RE = re.compile(r"(Reference ID\s*:\s*|\()([0-9A-Fa-f]{8})(?=\)|\s|$)")


def _is_serial_token(token: str) -> bool:
    """Sieht der letzte Teil eines by-id-Namens wie eine Seriennummer aus?"""
    if not token or token.startswith("<"):
        return False
    if re.fullmatch(r"[0-9A-Fa-f]{8,}", token):
        return True
    if len(token) >= 4 and re.search(r"\d", token) and re.fullmatch(r"[A-Za-z0-9.]+", token):
        return True
    return False


def _mac_identifies(mac: str) -> bool:
    """Gruppen-/Multicast-Adressen (z. B. PTP 01:1B:19:00:00:00) und 00:… kennzeichnen kein Gerät."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(digits) != 12 or set(digits) == {"0"}:
        return False
    return not int(digits[:2], 16) & 1


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _coord_pair_ok(a: str, b: str) -> bool:
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    if _decimals(a.lstrip("+-")) < 4 or _decimals(b.lstrip("+-")) < 4:
        return False
    if not (-90 <= x <= 90 and -180 <= y <= 180):
        return False
    return abs(x) >= 1 or abs(y) >= 1


def _float_is_coordlike(value: Any) -> bool:
    return isinstance(value, float) and _decimals(repr(abs(value))) >= 4 and "e" not in repr(value)


def _ip_kind(text: str) -> str | None:
    """'keep' | 'private' | 'public' | None (keine IP)."""
    try:
        addr = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
        return "keep"
    if isinstance(addr, ipaddress.IPv4Address) and str(addr) == "255.255.255.255":
        return "keep"
    if addr.is_global:
        return "public"
    return "private"


def _network_kind(addr: str, prefix: str) -> str | None:
    """Für CIDR: private/lokale Netzbereiche bleiben (Konfiguration, kein Gerät)."""
    try:
        net = ipaddress.ip_network(addr + prefix, strict=False)
    except ValueError:
        return None
    host = ipaddress.ip_address(addr.split("%", 1)[0])
    if net.prefixlen < net.max_prefixlen and host == net.network_address:
        return "public" if net.is_global else "keep"
    return None


def _host_allowed(name: str) -> bool:
    n = name.lower().rstrip(".")
    if n in PUBLIC_TIME_HOSTS or n in HARMLESS_DOMAINS or n in {"localhost", "localhost.localdomain"}:
        return True
    return n.endswith(PUBLIC_TIME_SUFFIXES)


def _refid_harmless(hex8: str) -> bool:
    """Refclock-RefIDs wie 47505300 ('GPS') sind Namen, keine Adressen."""
    raw = bytes.fromhex(hex8)
    text = raw.rstrip(b"\0")
    if text and all(65 <= c <= 90 or 48 <= c <= 57 for c in text) and 65 <= text[0] <= 90:
        return True
    kind = _ip_kind(str(ipaddress.IPv4Address(raw)))
    return kind == "keep"


# ---------------------------------------------------------------------------
# Der Filter
# ---------------------------------------------------------------------------


class Sanitizer:
    """Ein Filterlauf: Pseudonyme bleiben über alle Abschnitte eines Exports stabil."""

    def __init__(self, purpose: str = "diagnostics", known_names=()) -> None:
        if purpose not in PURPOSES:
            raise ValueError(f"unbekannter Zweck: {purpose}")
        self.purpose = purpose
        self.removed: dict[str, int] = {}
        self._ips: dict[str, str] = {}
        self._hosts: dict[str, str] = {}
        self._clock_ids: dict[str, str] = {}
        self._lock = threading.RLock()
        names = sorted({str(n).strip().rstrip(".") for n in known_names if n and len(str(n).strip()) >= 3
                        and not _host_allowed(str(n)) and _ip_kind(str(n).strip()) is None},
                       key=len, reverse=True)
        self._names_re = (re.compile(r"(?i)(?<![\w.-])(" + "|".join(re.escape(n) for n in names)
                                     + r")(?![\w-]|\.[A-Za-z0-9])") if names else None)

    # --- Bericht --------------------------------------------------------------
    def count(self, category: str, n: int = 1) -> None:
        self.removed[category] = self.removed.get(category, 0) + n

    def report(self) -> dict:
        return {"removed": dict(sorted(self.removed.items())),
                "pseudonyms": len(self._ips) + len(self._hosts) + len(self._clock_ids)}

    # --- Pseudonyme -----------------------------------------------------------
    def ip_pseudonym(self, ip: str) -> str:
        key = ip.split("%", 1)[0].lower()
        with self._lock:
            if key not in self._ips:
                self._ips[key] = f"client-{len(self._ips) + 1:02d}"
            return self._ips[key]

    def host_pseudonym(self, name: str) -> str:
        key = name.lower().rstrip(".")
        with self._lock:
            if key not in self._hosts:
                self._hosts[key] = f"<hostname-{len(self._hosts) + 1}>"
            return self._hosts[key]

    def clock_pseudonym(self, ident: str) -> str:
        key = ident.lower()
        with self._lock:
            if key not in self._clock_ids:
                self._clock_ids[key] = f"<uhr-id-{len(self._clock_ids) + 1}>"
            return self._clock_ids[key]

    # --- einzelne Werte ---------------------------------------------------------
    def _ip(self, text: str) -> str:
        kind = _ip_kind(text)
        if kind == "public":
            self.count("oeffentliche_ip")
            return PUBLIC_IP
        if kind == "private":
            self.count("private_ip")
            return self.ip_pseudonym(text)
        return text

    def host_value(self, value: str) -> str:
        """Wert eines Hostnamen-Felds (auch einteilige Namen wie 'nas')."""
        v = value.strip()
        if not v or v.startswith("<"):
            return value
        if _ip_kind(v.strip("[]")) is not None:
            return self._ip(v.strip("[]"))
        if _host_allowed(v) or v.lower() in {"localhost", "auto", "*"}:
            return value
        if re.fullmatch(r"[A-Za-z0-9._-]{1,253}", v):
            self.count("hostname")
            return self.host_pseudonym(v)
        return self.text(value)

    # --- Freitext -----------------------------------------------------------------
    def text(self, text: Any) -> Any:
        if not isinstance(text, str) or not text:
            return text
        if "\n" in text:
            return "\n".join(self._line(line) for line in text.split("\n"))
        return self._line(text)

    def _line(self, line: str) -> str:
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}") and len(stripped) < 1_000_000:
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                clean = self.obj(parsed)
                indent = line[:len(line) - len(line.lstrip())]
                return indent + json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        return self._plain(line)

    def _sub(self, pattern: re.Pattern, category: str, repl, text: str) -> str:
        def wrapped(match: re.Match) -> str:
            out = repl(match) if callable(repl) else repl
            if category and out != match.group(0):
                self.count(category)
            return out
        return pattern.sub(wrapped, text)

    def _plain(self, s: str) -> str:
        s = self._sub(_NMEA_RE, "position", lambda m: m.group(0)[:6] + "," + REMOVED, s)
        s = self._sub(_COORD_NMEA_RE, "position", "<koordinaten>", s)
        s = self._sub(_COORD_DMS_RE, "position", "<koordinaten>", s)
        s = self._sub(_COORD_DEG_RE, "position", "<koordinaten>", s)
        s = self._sub(_COORD_PAIR_RE, "position",
                      lambda m: "<koordinaten>" if _coord_pair_ok(m.group(1), m.group(2)) else m.group(0), s)
        s = self._sub(_KV_POS_RE, None, self._kv_pos, s)
        s = self._sub(_EMAIL_RE, "e_mail", "<e-mail>", s)
        s = self._sub(_BYID_RE, "seriennummer", self._byid, s)
        s = self._sub(_SERIAL_KV_RE, "seriennummer", lambda m: m.group(1) + m.group(2) + "<seriennr>", s)
        s = self._sub(_CLOCK_ID_RE, "uhr_id", self._clock_id, s)
        s = self._sub(_MAC_RE, "mac", lambda m: "<mac>" if _mac_identifies(m.group(0)) else m.group(0), s)
        s = self._sub(_ZONE_RE, "zeitzone", "<zeitzone>", s)
        s = self._sub(_ZONE_ABBR_RE, "zeitzone", "<zeitzone>", s)
        s = self._sub(_REFID_CTX_RE, "refid", self._refid, s)
        s = _IPV6_RE.sub(self._ipv6, s)  # zuerst: ::ffff:1.2.3.4 ist eine Adresse
        s = _IPV4_RE.sub(self._ipv4, s)
        s = self._sub(_DOMAIN_RE, "hostname", self._domain, s)
        if self._names_re is not None:
            s = self._sub(self._names_re, "hostname", lambda m: self.host_pseudonym(m.group(1)), s)
        return s

    def _kv_pos(self, m: re.Match) -> str:
        if m.group(2) is None:  # Bewegung (zweite Alternative)
            self.count("bewegung")
            return m.group(5) + m.group(6) + m.group(5) + m.group(7) + REMOVED
        key = m.group(2).lower()
        self.count("satellitenwinkel" if key in {"az", "el", "azimuth", "elevation"} else "position")
        return m.group(1) + m.group(2) + m.group(1) + m.group(3) + REMOVED

    def _clock_id(self, m: re.Match) -> str:
        ident, dash, port = m.group(0).partition("-")
        if not re.search(r"[1-9A-Fa-f]", ident):
            return m.group(0)  # 000000.0000.000000 = "keine Uhr"
        return self.clock_pseudonym(ident) + dash + port

    def _byid(self, m: re.Match) -> str:
        body, suffix = m.group(1), m.group(2)
        head, sep, last = body.rpartition("_")
        if sep and _is_serial_token(last):
            return f"{head}_<seriennr>{suffix}"
        return m.group(0)

    def _refid(self, m: re.Match) -> str:
        if _refid_harmless(m.group(2)):
            return m.group(0)
        return m.group(1) + "<refid>"

    def _ipv4(self, m: re.Match) -> str:
        addr, prefix = m.group(1), m.group(2) or ""
        if prefix:
            kind = _network_kind(addr, prefix)
            if kind == "keep":
                return m.group(0)
            if kind == "public":
                self.count("oeffentliche_ip")
                return PUBLIC_IP + prefix
        return self._ip(addr) + prefix

    def _ipv6(self, m: re.Match) -> str:
        addr, scope, prefix = m.group(1), m.group(2) or "", m.group(3) or ""
        if _ip_kind(addr) is None:
            return m.group(0)
        if prefix:
            kind = _network_kind(addr, prefix)
            if kind == "keep":
                return m.group(0)
            if kind == "public":
                self.count("oeffentliche_ip")
                return PUBLIC_IP + prefix
        out = self._ip(addr)
        return out + (scope if out == addr else "") + prefix

    def _domain(self, m: re.Match) -> str:
        name, tld = m.group(1), m.group(2).lower()
        if tld not in TLDS or _host_allowed(name):
            return m.group(0)
        # Dateinamen wie "chrony.conf" haben keine echte Endung; "nts.de" schon.
        return self.host_pseudonym(name) + m.group(0)[len(name):]

    # --- strukturierte Daten --------------------------------------------------------
    def obj(self, value: Any, key: Any = None, parent: dict | None = None) -> Any:
        if isinstance(value, dict):
            return self._dict(value)
        if isinstance(value, (list, tuple)):
            if (len(value) in (2, 3) and all(isinstance(v, float) for v in value[:2])
                    and _float_is_coordlike(value[0]) and _float_is_coordlike(value[1])
                    and _coord_pair_ok(repr(value[0]), repr(value[1]))):
                self.count("position")
                return "<koordinaten>"
            return [self.obj(v, key, parent) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def _dict(self, d: dict) -> dict:
        cls = d.get("class") if isinstance(d.get("class"), str) else None
        if cls in GPSD_DROP:
            self.count("gpsd_rohdaten")
            keep = {"class": cls, "entfernt": "Rohdaten mit möglichen Positionsangaben"}
            if isinstance(d.get("time"), str):
                keep["time"] = d["time"]
            return keep
        allowed = GPSD_ALLOWED.get(cls) if cls else None
        gps_like = bool(cls) or "mode" in d or "has_fix" in d or "satellites_used" in d
        out: dict = {}
        for raw_key, value in d.items():
            nk = _norm(raw_key)
            if allowed is not None and raw_key not in allowed:
                self._count_dropped_key(nk, default="position")
                continue
            if cls == "SKY" and raw_key == "satellites" and isinstance(value, list):
                out[raw_key] = [self._gpsd_sat(s) for s in value]
                continue
            result = self._value(raw_key, nk, value, gps_like)
            if result is _DROP:
                continue
            new_key = self.text(raw_key) if isinstance(raw_key, str) else raw_key
            n = 2
            base = new_key
            while new_key in out:  # zwei Adressen → gleicher Platzhalter: nichts überschreiben
                new_key = f"{base} ({n})"
                n += 1
            out[new_key] = result
        return out

    def _count_dropped_key(self, nk: str, default: str) -> None:
        if nk in ANGLE_KEYS:
            self.count("satellitenwinkel")
        elif nk in MOTION_KEYS:
            self.count("bewegung")
        else:
            self.count(default)

    def _gpsd_sat(self, sat: Any) -> Any:
        if not isinstance(sat, dict):
            return sat
        out = {}
        for k, v in sat.items():
            if k in GPSD_SAT_ALLOWED:
                out[k] = self.obj(v)
            else:
                self._count_dropped_key(_norm(k), default="satellitenwinkel")
        return out

    def _value(self, raw_key: Any, nk: str, value: Any, gps_like: bool) -> Any:
        scalar = not isinstance(value, (dict, list, tuple))
        if nk in POSITION_KEYS and (scalar or nk in {"position", "location", "coordinates", "coords",
                                                       "latlon", "latlng", "geo", "geolocation"}):
            if value is not None:
                self.count("position")
            return _DROP
        if nk in ANGLE_KEYS and scalar:
            if value is not None:
                self.count("satellitenwinkel")
            return _DROP
        if nk in MOTION_KEYS and scalar and (gps_like or isinstance(value, float)):
            if value is not None:
                self.count("bewegung")
            return _DROP
        if nk in SERIAL_KEYS and scalar:
            if value not in (None, ""):
                self.count("seriennummer")
            return _DROP
        if nk in MAC_KEYS and scalar:
            if value not in (None, ""):
                self.count("mac")
            return _DROP
        if nk in SECRET_KEYS:
            if value not in (None, "", {}):
                self.count("zugangsdaten")
            return _DROP
        if nk in TITLE_KEYS and isinstance(value, str):
            if value.strip() in DEFAULT_TITLES:
                return value
            self.count("titel")
            return "<titel>"
        if nk in CERT_KEYS and value not in (None, "", []):
            if isinstance(value, list):
                self.count("zertifikat", len(value))
                return ["<zertifikatsname>" for _ in value]
            if scalar:
                self.count("zertifikat")
                return "<zertifikatsname>"
        if nk in ISSUER_KEYS and isinstance(value, str) and value:
            if any(ca in value.lower() for ca in KNOWN_CAS):
                return self.text(value)
            self.count("zertifikat")
            return "<aussteller>"
        if nk in HOST_KEYS and isinstance(value, str):
            return self.host_value(value)
        if nk in TZ_KEYS and isinstance(value, str):
            v = value.strip()
            if re.fullmatch(r"(?:UTC|GMT|Z)?(?:[+-]\d{1,2}(?::?\d{2})?)?", v):
                return value
            self.count("zeitzone")
            return "<zeitzone>"
        if nk in REFID_KEYS and isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{8}", value):
            if _refid_harmless(value):
                return value
            self.count("refid")
            return "<refid>"
        if nk in CLOCK_ID_KEYS and isinstance(value, str) and value:
            self.count("uhr_id")
            return self.clock_pseudonym(value)
        if (self.purpose == "community" and nk in DELAY_KEYS and isinstance(value, (int, float))
                and not isinstance(value, bool)):
            rounded = round(value / 10) * 10 if nk.endswith("ms") else round(round(value / 0.01) * 0.01, 2)
            if rounded != value:
                self.count("latenz_gerundet")
            return rounded
        return self.obj(value, raw_key)


_DROP = object()

# ---------------------------------------------------------------------------
# Öffentliche Schnittstelle
# ---------------------------------------------------------------------------


def sanitize(obj: Any, purpose: str, sanitizer: Sanitizer | None = None, known_names=()) -> tuple[Any, dict]:
    """Strukturierte Daten filtern → (sauberes Objekt, Bericht).

    ``sanitizer`` erlaubt, mehrere Teile mit denselben Pseudonymen zu filtern;
    ``known_names`` sind eigene Namen (Hostname, NTS-Name …), die überall im
    Text ersetzt werden – auch ohne Punkt.
    """
    s = sanitizer or Sanitizer(purpose, known_names)
    clean = s.obj(obj)
    return clean, s.report()


def sanitize_text(text: str, purpose: str, sanitizer: Sanitizer | None = None, known_names=()) -> tuple[str, dict]:
    """Freitext (Logs, Aufzeichnungen, Konfigurationsdateien) filtern."""
    s = sanitizer or Sanitizer(purpose, known_names)
    return s.text(text if isinstance(text, str) else str(text)), s.report()


# --- Schlussprüfung --------------------------------------------------------------

_LEAK_KEYS_POSITION = {"lat", "lon", "lng", "latitude", "longitude", "alt", "althae", "altmsl", "altitude",
                       "geoidsep", "ecefx", "ecefy", "ecefz"}
_LEAK_KEYS_ANGLE = {"az", "el", "azimuth", "elevation"}
_LEAK_KEYS_SERIAL = {"productserial", "boardserial", "chassisserial", "productuuid", "serialnumber",
                     "serial", "iserial", "machineid"}


def _finding(kind: str, path: str, text: str) -> dict:
    return {"kind": kind, "path": path or "$", "text": text[:80]}


def _text_findings(text: str, path: str) -> list[dict]:
    found = []
    for pattern, kind in ((_COORD_NMEA_RE, "position"), (_COORD_DMS_RE, "position"),
                          (_COORD_DEG_RE, "position"), (_NMEA_RE, "position"),
                          (_EMAIL_RE, "e_mail"),
                          (_ZONE_RE, "zeitzone"),
                          (_ZONE_ABBR_RE, "zeitzone")):
        for m in pattern.finditer(text):
            if pattern is _NMEA_RE and m.group(0).endswith(REMOVED):
                continue
            found.append(_finding(kind, path, m.group(0)))
    for m in _CLOCK_ID_RE.finditer(text):
        if re.search(r"[1-9A-Fa-f]", m.group(0).partition("-")[0]):
            found.append(_finding("uhr_id", path, m.group(0)))
    for m in _MAC_RE.finditer(text):
        if _mac_identifies(m.group(0)):
            found.append(_finding("mac", path, m.group(0)))
    for m in _KV_POS_RE.finditer(text):
        found.append(_finding("position", path, m.group(0)))
    for m in _COORD_PAIR_RE.finditer(text):
        if _coord_pair_ok(m.group(1), m.group(2)):
            found.append(_finding("position", path, m.group(0)))
    for m in _BYID_RE.finditer(text):
        head, sep, last = m.group(1).rpartition("_")
        if sep and _is_serial_token(last):
            found.append(_finding("seriennummer", path, m.group(0)))
    for m in _SERIAL_KV_RE.finditer(text):
        found.append(_finding("seriennummer", path, m.group(0)))
    for m in _REFID_CTX_RE.finditer(text):
        if not _refid_harmless(m.group(2)):
            found.append(_finding("refid", path, m.group(0)))
    for m in _IPV4_RE.finditer(text):
        if m.group(2) and _network_kind(m.group(1), m.group(2)) == "keep":
            continue
        kind = _ip_kind(m.group(1))
        if kind == "public":
            found.append(_finding("oeffentliche_ip", path, m.group(0)))
        elif kind == "private":
            found.append(_finding("private_ip", path, m.group(0)))
    for m in _IPV6_RE.finditer(text):
        if m.group(3) and _network_kind(m.group(1), m.group(3)) == "keep":
            continue
        kind = _ip_kind(m.group(1))
        if kind in ("public", "private"):
            found.append(_finding("oeffentliche_ip" if kind == "public" else "private_ip", path, m.group(0)))
    return found


def _walk(value: Any, path: str, found: list[dict], parent_gps: bool = False) -> None:
    if isinstance(value, dict):
        gps_like = isinstance(value.get("class"), str) or "mode" in value or "has_fix" in value
        for key, sub in value.items():
            nk = _norm(key)
            sub_path = f"{path}.{key}" if path else str(key)
            scalar = not isinstance(sub, (dict, list, tuple))
            if isinstance(key, str):
                found.extend(_text_findings(key, sub_path))
            if sub is not None and scalar:
                if nk in _LEAK_KEYS_POSITION:
                    found.append(_finding("position", sub_path, f"{key}={sub!r}"))
                elif nk in _LEAK_KEYS_ANGLE:
                    found.append(_finding("satellitenwinkel", sub_path, f"{key}={sub!r}"))
                elif nk in {"speed", "track", "climb"} and (gps_like or isinstance(sub, float)):
                    found.append(_finding("bewegung", sub_path, f"{key}={sub!r}"))
                elif nk in _LEAK_KEYS_SERIAL and sub != "":
                    found.append(_finding("seriennummer", sub_path, f"{key}=…"))
                elif nk in MAC_KEYS and sub != "":
                    found.append(_finding("mac", sub_path, f"{key}=…"))
                elif nk in TZ_KEYS and isinstance(sub, str) and "/" in sub:
                    found.append(_finding("zeitzone", sub_path, sub))
            _walk(sub, sub_path, found, gps_like)
    elif isinstance(value, (list, tuple)):
        if (len(value) in (2, 3) and all(isinstance(v, float) for v in value[:2])
                and _float_is_coordlike(value[0]) and _float_is_coordlike(value[1])
                and _coord_pair_ok(repr(value[0]), repr(value[1]))):
            found.append(_finding("position", path, repr(list(value))))
        for i, sub in enumerate(value):
            _walk(sub, f"{path}[{i}]", found, parent_gps)
    elif isinstance(value, str):
        found.extend(_text_findings(value, path))


def check_no_leaks(obj_or_text: Any) -> list[dict]:
    """Letzte Schranke vor jedem Export: Liste der Funde (leer = sauber).

    Jeder Fund ist {"kind", "path", "text"}; ein nicht-leeres Ergebnis heißt:
    Export abbrechen. Rohe JSON-Zeilen im Text (gpsd, Aufzeichnung) werden
    geparst und wie strukturierte Daten geprüft.
    """
    found: list[dict] = []
    if isinstance(obj_or_text, (bytes, bytearray)):
        obj_or_text = obj_or_text.decode("utf-8", errors="replace")
    if isinstance(obj_or_text, str):
        for number, line in enumerate(obj_or_text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    _walk(parsed, f"Zeile {number}", found)
                    continue
            found.extend(_text_findings(line, f"Zeile {number}"))
        return found
    _walk(obj_or_text, "", found)
    return found
