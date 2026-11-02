"""Zentraler Datenschutzfilter für alles, was die Instanz verlässt.

Diagnosepaket, Aufzeichnungen und alles, was mit der Community geteilt wird,
laufen durch dieses Modul. Ziel: Aus einem Export darf sich **kein Standort**
bestimmen lassen und keine Kennung des Geräts oder seiner Clients.

Entfernt bzw. ersetzt werden:

* Koordinaten, Höhe, Bewegung (lat/lon/alt…, speed/track/climb) – auch als
  Zahlenpaar im Freitext, in NMEA-Sätzen und in rohen gpsd-JSON-Zeilen;
* Satellitenwinkel (Azimut/Elevation) und die Liste der einzelnen Satelliten
  (PRN) – es bleiben nur Summen je System (gesehen, benutzt, Signalstärke);
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

Hostnamen werden umgekehrt behandelt: **jeder** Name mit Punkt und
alphabetischer Endung wird ersetzt – außer bekannten öffentlichen Zeitdiensten
und Dateinamen (chrony.conf, server.py …). Was die Konfiguration kennt
(eigene Namen, Titel, Seriennummern, Interface-Namen), wird zusätzlich exakt
gesucht und ersetzt.

Laufzeiten (Delay, Fehlerschranken von chrony) werden für **jeden** Zweck auf
10 ms gerundet – auch in chronyc-Ausgaben und Aufzeichnungen: ein Satz genauer
Laufzeiten zu bekannten Servern erlaubt sonst eine grobe Ortung.

Zwei unabhängige Schranken vor jedem Export: ``check_no_leaks`` (nutzt die
Muster des Filters; zusätzlich gilt: Was der Filter an der Ausgabe noch ändern
würde, ist ein Fund – die Ausgabe muss ein Fixpunkt sein) und ``backstop`` – eine eigene, bewusst einfache Suche auf
den fertigen Bytes (bekannte Namen, 12 Hex-Zeichen, Koordinatenpaare,
Namen mit Punkt), die **nicht** auf die Muster des Filters zurückgreift. Findet
eine von beiden etwas, muss der Export abbrechen.
"""

from __future__ import annotations

import ipaddress
import json
import re
import sys
import threading
from typing import Any

# Zwecke: wofür etwas die Instanz verlässt. "notify" (Benachrichtigungen, 1.4) hat zusätzlich eine
# eigene Feldliste (NOTIFY_FIELDS) – nur diese Felder einer Meldung gehen überhaupt hinaus.
# "update_check" (Update-Hinweis, 1.4) schickt gar keine Daten: eine feste GET-Anfrage mit festen
# Kopfzeilen (update_check_request) – ohne Version, ohne Kennung.
PURPOSES = ("diagnostics", "recording", "community", "notify", "update_check")

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
    "kennung": "Kennungen aus 12 Hex-Zeichen und UUIDs (MAC ohne Trenner, Container-ID, Geräte-UUID).",
    "schnittstelle": "Selbst vergebene Namen von Netzwerk-Interfaces – sie können Namen oder Orte enthalten.",
    "name": "Frei gewählte Namen (z. B. von API-Schlüsseln).",
    "satellitenliste": "Die Liste der einzelnen Satelliten (PRN) – welche Satelliten zu einer Zeit sichtbar sind, "
                       "grenzt die Region ein; es bleiben nur Summen je System (gesehen, benutzt, Signalstärke).",
    "zeile_entfernt": "Ganze Log-Zeilen, die die Schlussprüfung beanstandet hat – lieber eine Zeile weniger als "
                      "ein abgebrochener Export.",
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
    # Namen aus der „Zeitserver erzwingen“-Liste (enforce.py) – Werkseinstellungen von Geräten.
    "ntp.ubuntu.com", "time.amazon.com", "time.android.com", "time-ios.apple.com",
    "time-macos.apple.com", "ntp.zeitgitter.net", "time.cloudflare.com", "fritz.box",
    "time.euro.apple.com", "time.asia.apple.com",
}
PUBLIC_TIME_SUFFIXES = (".pool.ntp.org", ".nts.netnod.se", ".netnod.se", ".nist.gov", ".ntp.se")

# Dateiendungen: "chrony.conf" ist eine Datei, kein Host. Endungen, die zugleich
# echte Domainendungen sind (py, sh, md …), gelten nur bei genau zwei Teilen
# ("server.py") als Datei – "ntp.mein-dorf.py" ist ein Host.
FILE_EXTENSIONS = set("""
conf cfg log json jsonl txt js mjs cjs css html htm pem crt cer csr der p12 pfx sock socket service timer
target mount gz tgz xz bz2 zst tar db sqlite sqlite3 wal shm pid lock tmp bak old orig new yml yaml toml
ini xml csv tsv svg png jpg jpeg gif ico webp woff woff2 ttf otf ko dtb dtbo img iso deb rpm whl env
list rules asc sig out err pyc pyi ts tsx map patch diff migrated jsonc cnf keys drift
""".split())
# Endungen, die zugleich echte Domainendungen sind: nur als Datei, wenn ein "/" davor steht, der
# Name einen Unterstrich hat oder ein bekannter Dateiname des Projekts ist ("server.py") –
# "kowalski.pl" ist ein Host, "/usr/lib/foo.so" eine Datei.
AMBIGUOUS_EXTENSIONS = {"py", "sh", "md", "so", "pl", "rs", "ps", "pm", "cc", "in", "am", "ac", "zip",
                        "key", "mov", "go", "rb", "lua", "new", "pub", "target"}
FILE_EXTENSIONS -= AMBIGUOUS_EXTENSIONS


def _project_stems() -> set[str]:
    import os
    stems = {"help", "index", "notes", "docs", "entrypoint", "container-test", "setup", "install", "readme", "changelog", "main", "run", "test",
             "tests", "conftest", "manage", "start", "stop", "build", "healthcheck", "supervisor", "license"}
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (here, os.path.join(here, "static"), os.path.join(here, "static", "js"),
                   os.path.join(here, "static", "js", "pages"), os.path.join(here, ".."),
                   os.path.join(here, "..", "docker"), os.path.join(here, "..", "tests"),
                   os.path.join(here, "..", "scripts")):
        try:
            stems.update(name.rsplit(".", 1)[0].lower() for name in os.listdir(folder) if "." in name)
        except OSError:
            pass
    return stems


PROJECT_STEMS = _project_stems()
# Hersteller- und Projektdomains, die in Gerätenamen, Logs oder Links auftauchen.
HARMLESS_DOMAINS = {
    "u-blox.com", "www.u-blox.com", "github.com", "chrony-project.org", "gpsd.io",
    "linuxptp.sourceforge.net", "letsencrypt.org", "example.com", "example.org", "example.net",
    "localhost.localdomain",
}

KNOWN_CAS = ("let's encrypt", "zerossl", "google trust services", "digicert", "sectigo",
             "buypass", "globalsign", "isrg", "actalis", "ssl.com", "certum", "entrust")

DEFAULT_TITLES = {"", "NTP / PTP Time Server"}


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
               "productuuid", "iserial", "idserial", "idserialshort", "machineid", "bootid", "uuid",
               "uniqueid", "chipid", "cpuserial", "hwserial", "iserialnumber", "seriennummer"}
MAC_KEYS = {"mac", "macaddr", "macaddress", "hwaddr", "permaddr", "lladdr", "ether"}
SECRET_KEYS = {"password", "passwd", "hash", "secret", "token", "apikey", "auth", "credentials",
               "privatekey", "cookie", "authorization"}
CERT_KEYS = {"subject", "commonname", "cn", "altnames", "san", "subjectaltname", "names", "certnames",
             "dnsnames", "subjectcn", "subjectdn"}
# Teile, die einen Schlüssel als Zertifikatsnamen kennzeichnen (subject_cn, cert_san …)
CERT_TOKENS = {"subject", "cn", "san"}
ISSUER_KEYS = {"issuer", "certissuer", "issuercn"}
HOST_KEYS = {"hostname", "host", "fqdn", "nodename", "servername", "ntsservername", "domain",
             "hostnames", "hosts", "domains"}
# Schlüssel, unter denen eine Adresse auch ein (per Reverse-DNS aufgelöster) Name sein kann.
ADDRESS_KEYS = {"address", "addr", "remote", "peer", "peeraddress", "remoteaddress", "clientaddress"}
TZ_KEYS = {"timezone", "tz", "timezonename", "zone", "tzname", "localtimezone"}
TITLE_KEYS = {"webtitle"}
# Schlüsselteile, unter denen ein Wert ein Geheimnis ist (web_password, pw, smtp_pass …)
SECRET_TOKENS = {"password", "passwort", "passwd", "pass", "pw", "pwd", "secret", "secrets"}
DELAY_KEYS = {"delay", "rootdelay", "peerdelay", "rtt", "latency", "roundtrip", "roundtripdelay",
              "delayms", "rttms", "latencyms", "meandelay"}
CLOCK_ID_KEYS = {"clockidentity", "grandmasteridentity", "parentportidentity", "portidentity",
                 "gmidentity"}
REFID_KEYS = {"refid", "referenceid", "reference", "ref"}
NAME_KEYS = {"apikeyname", "keyname"}
# Laufzeit-ähnliche Werte: Fehlerschranke und Auswahlintervall von chrony enthalten die halbe Laufzeit.
DELAY_KEYS |= {"error", "estimatederror", "intervallow", "intervalhigh", "rootdistance"}

# Schlüssel werden zusätzlich in Teile zerlegt (lat_deg, latitudeE7, az_deg, pos.x …):
# enthält ein Teil eines dieser Wörter, fliegt der Wert raus – auch wenn er kein Skalar ist.
POSITION_TOKENS = {"lat", "lon", "lng", "latitude", "longitude", "alt", "altitude", "ecef", "breite",
                   "laenge", "länge", "hoehe", "höhe", "coords", "coordinates", "koordinaten", "geo",
                   "position", "location", "standort", "breitengrad", "laengengrad", "längengrad", "mlat",
                   "mlon", "lati", "longi", "locality", "city", "stadt", "ort", "street", "strasse", "straße",
                   "postalcode", "postcode", "plz"}
# Schlüssel, unter denen Zahlenreihen Satellitenpositionen sein können (sats, skyview …)
SKY_TOKENS = {"sat", "sats", "satellites", "satelliten", "sky", "skyview", "skyplot"}
ANGLE_TOKENS = {"az", "el", "azimuth", "azimut", "elevation", "elev", "azim"}
# Laufzeit-Schlüssel nach Teilen (delay_us, round_trip_time, rtt_ms …) und ihre Einheit
DELAY_TOKENS = {"delay", "rtt", "latency", "roundtrip", "ping", "laufzeit", "latenz"}
UNIT_SECONDS = {"s": 1.0, "sec": 1.0, "seconds": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}
# Schlüssel, unter denen ein nackter 12-Hex-Wert eine MAC ist.
MAC_LIKE_TOKENS = {"mac", "address", "addr", "iface", "interface", "ifname", "hwaddr", "ether", "lladdr",
                   "permaddr", "bssid"}
_TOKEN_SPLIT_RE = re.compile(r"[\s_\-.]+|(?<=[a-zäöü])(?=[A-ZÄÖÜ])|(?<=[A-Za-z])(?=\d)(?<!e)")


def key_tokens(key: Any) -> set[str]:
    """'latitude_e7' → {latitude, e7}; 'altHAE' → {alt, hae}; 'az-deg' → {az, deg}."""
    text = str(key)
    parts = [p for p in _TOKEN_SPLIT_RE.split(text) if p]
    return {p.lower() for p in parts}


def _key_kind(key: Any) -> str | None:
    """'position' | 'satellitenwinkel' | None – nach Teilen des Schlüssels."""
    tokens = key_tokens(key)
    if tokens & ANGLE_TOKENS:
        return "satellitenwinkel"
    if tokens & POSITION_TOKENS:
        return "position"
    return None

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

# MAC mit Trennern: 00:11:22:33:44:55, 00-11-…, 00.11.…, 0011.2233.4455, 001122-334455 und
# „00 11 22 33 44 55“ (nur genau sechs Gruppen, nicht mitten in einem Hex-Dump).
_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:-])(?<![0-9A-Fa-f]\.)(?:[0-9A-Fa-f]{2}([:.-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}"
                     r"|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}"
                     r"|(?<![0-9A-Fa-f] )[0-9A-Fa-f]{2}(?: [0-9A-Fa-f]{2}){5}(?! [0-9A-Fa-f]{1,2}(?![^\W_])))"
                     r"(?![0-9A-Fa-f:-])(?!\.[0-9A-Fa-f])")
# PTP-Uhr-ID: 001122.fffe.334455 (ptp4l) oder 00:11:22:ff:fe:33:44:55 / 00-11-22-ff-fe-33-44-55
_CLOCK_ID_RE = re.compile(r"(?<![0-9A-Fa-f.:-])(?:[0-9A-Fa-f]{6}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{6}"
                          r"|(?:[0-9A-Fa-f]{2}:){7}[0-9A-Fa-f]{2}|(?:[0-9A-Fa-f]{2}-){7}[0-9A-Fa-f]{2})"
                          r"(?:-\d+)?(?![0-9A-Fa-f.:])")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?![\w-])")
_IPV4_RE = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})"
                      r"(/\d{1,2})?(?!\d|\.\d)")
_IPV6_RE = re.compile(r"(?<![\w.%])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?::\d{1,3}(?:\.\d{1,3}){3})?)"
                      r"(%[\w.-]+)?(/\d{1,3})?(?![\w:%]|\.\d)")
# chronyc kürzt lange Namen im Klartext mit ">" ab: "2a01:4f8:c17:5c1b:1234:5678:9a>"
_IPV6_TRUNC_RE = re.compile(r"(?<![\w:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7})>")
# Namen mit Punkt; Labels auch mit Umlauten (IDN), letzte Stelle nur Buchstaben.
# Labels ohne Längengrenze – genau wie die Schlussprüfung, sonst bliebe ein überlanger Name stehen
# und der ganze Export bräche ab. Auch nach einem einzelnen Punkt am Wortanfang (" .mueller.de").
_LABEL = r"[^\W_](?:[^\W_]|-)*"
_DOMAIN_RE = re.compile(r"(?<![^\W_])(?<![@-])(?<![^\W_-]\.)((?:" + _LABEL + r"\.)+([^\W\d_]{2,}))\.?"
                        r"(?![^\W_])(?!-)(?!\.[^\W_])")
# Ideografische Punkte (zeit。mueller。de) sind für Resolver normale Punkte.
_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})
_ZONE_RE = re.compile(r"\b(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific"
                      r"|Brazil|Canada|Chile|Mexico|US)/[A-Za-z][A-Za-z_+-]*(?:/[A-Za-z][A-Za-z_+-]*)?")
# Kürzel; "GST" fehlt absichtlich (gpsd-Meldungsklasse).
_ZONE_ABBR_RE = re.compile(r"(?<![\w/])(?:CET|CEST|MEZ|MESZ|OEZ|OESZ|WEZ|WESZ|EET|EEST|WET|WEST|BST|IST|GMT\+\d+"
                           r"|EST|EDT|CST|CDT|MST|MDT|PST|PDT|AKST|AKDT|HST|AEST|AEDT|ACST|ACDT|AWST|NZST|NZDT"
                           r"|JST|KST|MSK|HKT|SGT|CAT|WAT|EAT|SAST|WIB|WITA|WIT|PKT|ICT|BRT|BRST|ART|CLT|CLST"
                           r"|COT|PET|VET|UYT|PYT|BOT|ECT|NPT|AFT|IRST|IRDT|AST|ADT|NST|NDT|PHT|MYT|BDT|AZT"
                           r"|GET|AMT|SAMT|YEKT|OMST|NOVT|KRAT|IRKT|YAKT|VLAT|MAGT|PETT|TRT|ChST)(?![\w/])")
# POSIX-TZ mit Sommerzeitregel (TZ=CET-1CEST,M3.5.0,M10.5.0/3) – die Regel verrät die Region.
_POSIX_TZ_RE = re.compile(r"(?<![\w<])(?:[A-Za-z]{3,6}|<[+-]?[\w]{1,6}>)[+-]?\d{1,2}(?::\d{2}){0,2}(?:[A-Za-z]{3,6}|<[+-]?\w{1,6}>)"
                          r"(?:[+-]?\d{1,2}(?::\d{2}){0,2})?,(?:M\d{1,2}\.\d\.\d|J?\d{1,3})(?:/[+-]?\d{1,3}(?::\d{2}){0,2})?"
                          r",(?:M\d{1,2}\.\d\.\d|J?\d{1,3})(?:/[+-]?\d{1,3}(?::\d{2}){0,2})?")
# Ausgeschriebene Zonennamen: „W. Europe Standard Time“ (Windows), „Mitteleuropäische Sommerzeit“
_ZONE_WORDS_RE = re.compile(r"(?i)\b(?:[A-Z][\w.]*\.?\s+){1,4}(?:standard|daylight|summer)\s+time\b"
                            r"|\b(?:central|eastern|western|pacific|mountain|atlantic|alaska|hawaii(?:-aleutian)?)"
                            r"(?:\s+european)?\s+(?:standard\s+|daylight\s+|summer\s+)?time\b"
                            r"|\b(?:mittel|west|ost|nord|süd)?europäische\s+(?:sommer|normal|standard)?zeit\b"
                            r"|\bmitteleuropäische\s+zeit\b")
# „Zeitzone: Berlin“, „zone: Berlin“, „timezone=Vienna“, „Time zone: Europe/Berlin (CET, +0100)“
_ZONE_LABEL_RE = re.compile(r"(?i)\b(time\s?zone|zeitzone|zone|tz)([ \t]*[:=][ \t]*|(?<=one)[ \t]+)([\"']?)"
                            r"(?!<)(?!(?:UTC|GMT|Z)?[+-]?\d)(?!(?:UTC|GMT|Z)\b)"
                            # Füllwörter nach „timezone“ sind kein Wert („Using right/UTC timezone to obtain …“)
                            r"(?!(?:to|is|for|of|from|the|set|not|and|in|on|with|data|database|file|files|info"
                            r"|changed|offset|unknown|none|auf|ist|für|von|nicht|wird|und|mit|daten|datei)\b)"
                            r"([A-Za-z][A-Za-z_+/-]*)")
# Koordinaten mit Bezeichnung: lat=…, "Latitude 48.1", Breite: 48,1, latE7=…, az 123, el 45,
# Lat.: 48.1, mlat=48.1 (OSM-Link), lat%3D48.1 (URL-kodiert), CFG-TMODE-LAT,481371540 …
_POS_LABELS = (r"breitengrad|l(?:ä|ae)ngengrad|latitude|longitude|lati|longi|mlat|mlon|lat|lon|lng|altitude|althae"
               r"|altmsl|alt|geoidsep|ecef[_-]?[xyz]|breite|l(?:ä|ae)nge|h(?:ö|oe)he|azimuth|azimut|azim"
               r"|elevation|elev|az|el")
_KV_POS_RE = re.compile(r"(?i)(?:(?<![^\W_])|(?<=%26)|(?<=%3[fF])|(?<=%2[cC]))(?P<q>[\"']?)(?P<label>(?:" + _POS_LABELS
                        + r")(?:[_-]?(?:e7|deg|degrees|grad|rad|dd|m|msl|hae|wgs84))?)(?P<dot>\.?)(?P=q)"
                        r"(?P<sep>[ \t]*(?:[:=,]|%3[dDaA])[ \t]*|[ \t]+)(?P<vq>[\"']?)[-+]?\d+(?:[.,]\d+)?(?:e[-+]?\d+)?"
                        r"(?:\s*°)?(?:\s?[NSEWO](?![^\W_]))?(?P=vq)"
                        r"|(?<![\w])(?P<mq>[\"']?)(?P<motion>speed|track|climb|heading)(?P=mq)(?P<msep>\s*[:=]\s*)"
                        r"(?P<mvq>[\"']?)[-+]?\d+\.\d+(?:e[-+]?\d+)?(?P=mvq)")
# x=11.576124 y=48.137154 – nur, wenn die Werte zusammen eine Koordinate ergeben
_XY_RE = re.compile(r"(?i)(?<![^\W_])(x\s*[:=]\s*)([-+]?\d{1,3}[.,]\d+)(\s*[,;]?\s*y\s*[:=]\s*)([-+]?\d{1,3}[.,]\d+)"
                    r"(?![\d])")
# 48°08'13.8"N 11°34'34.0"E, 48°08.230'N, 48 deg 8' 13.75" N, 48d08m13.8sN, 48 8 13.75 N
_COORD_DMS_RE = re.compile(r"(?<![\w.])\d{1,3}\s*(?:°|deg\b|grad\b)\s*\d{1,2}(?:[.,]\d+)?\s*(?:['′]|min\b)?"
                           r"(?:\s*\d{1,2}(?:[.,]\d+)?\s*(?:\"|″|''|sec\b|s\b)?)?\s*[NSEWO](?![^\W_])"
                           r"|(?<![\w.])\d{1,3}d\s*\d{1,2}(?:[.,]\d+)?m(?:\s*\d{1,2}(?:[.,]\d+)?s)?\s*[NSEWO](?![^\W_])"
                           r"|(?<![\w.:])\d{1,3}\s+\d{1,2}\s+\d{1,2}[.,]\d+\s*[NSEWO](?![^\W_])")
# Geocaching-Format mit Halbkugel davor: N 48° 08.229 E 011° 34.567, N48 08.229 E011 34.567
_COORD_HEMI_RE = re.compile(r"(?<![^\W_])[NS]\s*\d{1,2}(?:\s*°\s*|\s+)\d{1,2}[.,]\d{2,}['′]?\s*[,;/]?\s*"
                            r"[EWO]\s*\d{1,3}(?:\s*°\s*|\s+)\d{1,2}[.,]\d{2,}['′]?"
                            r"|(?<![^\W_])[NSEWO]\s*\d{1,3}\s*°\s*\d{1,2}[.,]\d{2,}")
# 48.137154° N
_COORD_DEG_RE = re.compile(r"[-+]?\d{1,3}[.,]\d{3,}\s*°\s*[NSEWO]\b")
# NMEA-Format ddmm.mmmm,N,dddmm.mmmm,E – auch ohne Kommas: 4808.2292N 01134.5674E
_COORD_NMEA_RE = re.compile(r"(?<![^\W_])\d{4}\.\d+\s*,?\s*[NS]\s*[,;/ ]?\s*\d{5}\.\d+\s*,?\s*[EWO](?![^\W_])")
# ECEF-Tripel mit Bezeichnung (x=4177612.1 y=… z=…) oder ohne – erkannt am Betrag ≈ Erdradius.
# Auch in cm/mm (u-blox: 417761212 cm) – _ecef_ok prüft alle drei Maßstäbe.
_ECEF_RE = re.compile(r"(?i)(?<![^\W_])(?:[\"']?(?:ecef[_-]?)?x[\"']?\s*[:=]\s*)?([-+]?\d{4,10}(?:\.\d+)?)\s*(?:c?m\b)?\s*[,;/ ]\s*"
                      r"(?:[\"']?(?:ecef[_-]?)?y[\"']?\s*[:=]\s*)?([-+]?\d{4,10}(?:\.\d+)?)\s*(?:c?m\b)?\s*[,;/ ]\s*"
                      r"(?:[\"']?(?:ecef[_-]?)?z[\"']?\s*[:=]\s*)?([-+]?\d{4,10}(?:\.\d+)?)(?:\s*c?m\b)?(?![\d.])")
# Ganzzahlige Koordinaten in 1e-7 Grad ohne Bezeichnung: 481371540,115761240
_E7_PAIR_RE = re.compile(r"(?<![\w.,:-])([-+]?\d{8,10})\s*[,;/ ]\s*([-+]?\d{8,10})(?![\w.,])")
# Zahlen-Token für Koordinatenpaare: optional Halbkugel davor/danach, Dezimalpunkt oder -komma.
_COORD_TOKEN_RE = re.compile(r"(?:(?<![^\W_])|(?<=%2[cCbB])|(?<=%20))(?<![.%])(?:([NSEWO])\s?)?([-+]?\d{1,3}(?:\.\d+(?!\d|\.\d)|,\d+(?!\d|,\d)"
                             r"|(?![\d]|[.,]\d)))(\s*°)?(?:\s?([NSEWO])(?![^\W_]))?")
_HAS_DECIMALS_RE = re.compile(r"\d[.,]\d{3}")
_COORD_GAP_RE = re.compile(r"\s*(?:[,;/|&]|%2[cC]|%3[bB]|%20|\+|(?<=\s)-(?=\s)|(?<=\s)(?:und|and)(?=\s))?\s*")
# Maidenhead-Locator (nur mit Bezeichnung – „JN58“ allein ist zu kurz zum Erkennen) und Plus Codes
_LOCATOR_RE = re.compile(r"(?i)\b(locator|maidenhead|qth|grid(?:square)?)(\s*[:=]?\s*)[A-R]{2}\d{2}(?:[A-X]{2}(?:\d{2})?)?\b")
_PLUSCODE_RE = re.compile(r"(?<![\w+])[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3}(?![\w+])")
# Titel als Schlüssel/Wert im Freitext (WEB_TITLE=…), auch wenn er nicht bekannt ist
_TITLE_KV_RE = re.compile(r"(?i)\b(web_title)(\s*[:=]\s*)(?!<titel>)(\S.*)$")
# Lange Hex-Kennungen (machine-id, boot_id, Container-ID, Hashes): ≥ 16 Zeichen, mit Buchstabe und Ziffer
_HEXLONG_RE = re.compile(r"(?<![0-9A-Fa-f.])(?=[0-9A-Fa-f]*[A-Fa-f])(?=[0-9A-Fa-f]*\d)[0-9A-Fa-f]{16,}(?![0-9A-Fa-f])")
# IP-Adresse mit Bindestrichen in Reverse-DNS-Namen: ip-91-184-211-161
_IP_DASHED_RE = re.compile(r"(?<![\w.-])((?:[A-Za-z]{1,12}-)?)((?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:-(?:25[0-5]|2[0-4]\d"
                           r"|1\d\d|[1-9]?\d)){3})(?![\w-])")
# Zugangsdaten im Text: "Authorization: Bearer …", API-Schlüssel "ntpg_…"
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)(\s+)(?!<)[A-Za-z0-9._~+/=-]{8,}")
_APITOKEN_RE = re.compile(r"(?<![\w])ntpg_[A-Za-z0-9_-]{8,}")
# Zertifikats-DN: subject=C = DE, ST = Bayern, L = Ort, O = Verein, CN = …  oder /C=DE/L=Ort/…
_DN_KEYS = r"CN|C|ST|L|O|OU|street|postalCode|emailAddress|serialNumber|DC|UID|givenName|SN|title"
_DN_PART_RE = re.compile(r"(?<![\w])(" + _DN_KEYS + r")(\s*=\s*)((?:(?!\s*[,/+;]\s*(?:" + _DN_KEYS
                         + r")\s*=)[^\n,/;])+)")
_DN_CONTEXT_RE = re.compile(r"(?i)\b(subject|issuer|aussteller|inhaber)\b")
# Satellitentabellen von cgps/gpsmon ("  5  288  62  45  Y") und Winkelpaare ("288° 62°")
_SAT_ROW_RE = re.compile(r"^(\s*\d{1,3}\s+)(\d{1,3})(\s+)(-?\d{1,2})(\s+\d{1,2}(?:\.\d)?\s+[YN]\s*)$")
_SAT_DEG_RE = re.compile(r"(?<![\w.])(\d{1,3})(\s*°\s+)(-?\d{1,2})(\s*°)(?!\s*\d)")
_UUID_RE = re.compile(r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
                      r"(?![0-9A-Fa-f-])")
# MAC im Interface-Namen (systemd: enx/wlx/wwx + MAC)
_IFACE_MAC_RE = re.compile(r"(?i)(?<![^\W_])(en|wl|ww)x([0-9a-f]{12})(?![0-9a-f])")
# EUI-64 ohne Punkte (PTP-Uhr-ID 001b21fffeaabbcc)
_EUI64_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{6}[fF][fF][fF][eE][0-9A-Fa-f]{6}(?![0-9A-Fa-f])")
# Jede für sich stehende Folge aus genau 12 Hex-Zeichen (MAC ohne Trenner, Container-ID …);
# nicht direkt nach einem Punkt (Nachkommastellen).
HEX12_PATTERN = r"(?<![0-9A-Fa-f.])[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
_HEX12_RE = re.compile(HEX12_PATTERN)
HEX12_HARMLESS = {"000000000000", "ffffffffffff"}
# chrony-Laufzeiten im Klartext: "Root delay      : 0.012345678 seconds", "Peer delay : …"
# Laufzeiten mit Bezeichnung: "Root delay : 0.012345678 seconds", "delay=0.023", "RTT: 23.4 ms" (auch 1.2e-02)
_DELAY_KV_RE = re.compile(r"(?i)\b((?:root\s+|peer\s+|mean\s+)?(?:delay|rtt|latency|laufzeit|latenz|antwortzeit"
                          r"|round[ -]?trip(?:[ -]?time)?|root\s+distance))(\s*[:=]\s*)"
                          r"([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)(\s*(?:ns|us|µs|ms|seconds?|sec|s)\b)?")
# Zeilen, in denen jede Zahl mit Zeiteinheit eine Laufzeit sein kann ("antwortet in 23.456 ms")
_DELAY_CONTEXT_RE = re.compile(r"(?i)\b(?:delay|rtt|latency|laufzeit|latenz|antwort|ping|round.?trip)")
_DELAY_UNIT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s*)(ns|us|µs|ms)\b|(?<![\w.])(\d+\.\d{3,})(\s*)(seconds?|sec|s)\b")
# chronyc sources: Fehlerschranke "+/-   11ms" einer NTP-Quelle (Zeile beginnt mit ^ oder =)
_SOURCE_ERR_RE = re.compile(r"(\+/-\s*)(\d+(?:\.\d+)?)(ns|us|ms|s)\b")
_NMEA_TYPES = r"(GGA|RMC|GLL|GNS|VTG|GSV|GST|HDT|THS|RMB|RMA|DTM)"
_NMEA_RE = re.compile(r"\$(?:G[PNLABQI]|BD|QZ|PQ)" + _NMEA_TYPES + r"\b[^\s\"']*"
                      r"|(?<![\w$])(?:G[PNLABQI]|BD|QZ|PQ)" + _NMEA_TYPES + r",[^\s\"']*"
                      r"|\$?PUBX,0[0-4],[^\s\"']*")
_BYID_RE = re.compile(r"(?<![\w-])((?:usb|usbv2|pci|ata|nvme|scsi)-[A-Za-z0-9._+:,-]*?)"
                      r"(-if\d+(?:-port\d+)?)(?![\w])")
_SERIAL_LABELS = (r"serial(?:[ _-]?(?:number|no\.?|nr\.?))?|product_serial|board_serial|chassis_serial|product_uuid"
                  r"|iSerial(?:Number)?|ID_SERIAL(?:_SHORT)?|Seriennummer|Serien-?nr\.?|Serien-?nummer"
                  r"|(?-i:SN|S/N)")
_SERIAL_KV_RE = re.compile(r"(?i)(?<![\w/])(" + _SERIAL_LABELS + r")(\s*[:=]\s*\"?)"
                           r"(?!<seriennr>)([A-Za-z0-9][\w.:-]{2,})")
# „serial 1234ABCD9876“, „Serial Number 0042A7F1“, lsusb: „iSerial  3 1234ABCD“ – ohne : oder =.
# Nur Wörter mit Ziffer und ≥ 6 Zeichen, damit „serial port“ oder „serial ttyAMA0“ bleiben.
_SERIAL_WS_RE = re.compile(r"(?i)(?<![\w/])(iSerial\s+\d+|" + _SERIAL_LABELS + r")(\s+)"
                           r"(?!<seriennr>)(?!tty)(?=[A-Za-z0-9.-]*\d)([A-Za-z0-9][A-Za-z0-9.-]{5,})(?![\w:/])")
_REFID_CTX_RE = re.compile(r"((?i:Reference ID|ref[ _-]?id)\s*[:=]?\s*|\()([0-9A-Fa-f]{8})(?=\)|\s|,|$)"
                           r"|^()([0-9A-Fa-f]{8})(?=,[^,\n]*,\d{1,2},\d{9,}\.\d+,)")


def _is_serial_token(token: str) -> bool:
    """Sieht der letzte Teil eines by-id-Namens wie eine Seriennummer aus?"""
    if not token or token.startswith("<"):
        return False
    if re.fullmatch(r"[0-9A-Fa-f]{8,}", token):
        return True
    if len(token) >= 4 and re.search(r"\d", token) and re.fullmatch(r"[A-Za-z0-9.]+", token):
        return True
    return bool(re.fullmatch(r"[A-Z0-9]{8,}", token))  # FTDI/u-blox-Seriennummern auch ohne Ziffer


def _split_clock_port(text: str) -> tuple[str, str, str]:
    """'001122.fffe.334455-1' → ('001122.fffe.334455', '-', '1'); auch für 00-11-…-55-1."""
    if re.match(r"[0-9A-Fa-f]{2}-", text):
        ident, rest = text[:23], text[23:]
        return ident, rest[:1], rest[1:]
    return text.partition("-")


def _mac_identifies(mac: str) -> bool:
    """Gruppen-/Multicast-Adressen (z. B. PTP 01:1B:19:00:00:00) und 00:… kennzeichnen kein Gerät."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(digits) != 12 or set(digits) == {"0"}:
        return False
    return not int(digits[:2], 16) & 1


def _decimals(text: str) -> int:
    for sep in (".", ","):
        if sep in text:
            return len(text.split(sep, 1)[1])
    return 0


def _significant_decimals(text: str) -> int:
    """Nachkommastellen ohne Nullen am Ende: '4.000000000' → 0, '48.1370' → 3."""
    for sep in (".", ","):
        if sep in text:
            return len(text.split(sep, 1)[1].rstrip("0"))
    return 0


def _to_float(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _coord_pair_ok(a: str, b: str, min_decimals: int = 4) -> bool:
    x, y = _to_float(a), _to_float(b)
    if x is None or y is None:
        return False
    if (_significant_decimals(a.lstrip("+-")) < min_decimals
            or _significant_decimals(b.lstrip("+-")) < min_decimals):
        return False
    if not ((-90 <= x <= 90 and -180 <= y <= 180) or (-90 <= y <= 90 and -180 <= x <= 180)):
        return False
    return abs(x) >= 1 or abs(y) >= 1


def coord_pair_spans(line: str) -> list[tuple[int, int]]:
    """Stellen (Anfang, Ende) von Koordinatenpaaren in einer Zeile.

    Zwei Zahlen gelten als Paar, wenn zwischen ihnen nur ein Trenner steht
    (Leerzeichen , ; / | %2C …) und sie im Bereich ±90/±180 liegen. Nötige
    Nachkommastellen: 4 – oder 3, wenn eine Halbkugel (N/S/E/W/O) oder ° dabei
    ist oder das Paar (mit höchstens einer dritten Zahl, der Höhe) für sich steht.
    In langen Zahlenreihen (chronyc -c) reichen 3 Stellen nicht.
    """
    if not _HAS_DECIMALS_RE.search(line):
        return []
    tokens = [m for m in _COORD_TOKEN_RE.finditer(line) if m.group(2)]
    if len(tokens) < 2:
        return []
    # zusammenhängende Läufe (nur Trenner dazwischen)
    runs: list[list[re.Match]] = [[tokens[0]]]
    for prev, cur in zip(tokens, tokens[1:]):
        if _COORD_GAP_RE.fullmatch(line, prev.end(), cur.start()):
            runs[-1].append(cur)
        else:
            runs.append([cur])
    spans = []
    for run in runs:
        marks = [bool(t.group(1) or t.group(3) or t.group(4)) for t in run]
        for i, j in pair_indices([t.group(2) for t in run], marks):
            spans.append((run[i].start(), run[j].end()))
    return spans


def pair_indices(texts: list[str], marks: list[bool] | None = None, extra: int = 0) -> list[tuple[int, int]]:
    """Indizes (i, i+1) der Koordinatenpaare in einer Zahlenreihe (Texte wie im Export).

    Nötig sind 4 Nachkommastellen – oder 3, wenn eine Halbkugel/° dabei ist, die Reihe kurz ist
    (≤ 3 Zahlen) oder die Nachbarn links und rechts weniger als 3 Stellen haben
    ("fix 3 48.137 11.576 519.3 12"). Gleiche Regel für Freitext, strukturierte Daten und
    (unabhängig nachgebaut) die Schlussprüfung.
    """
    marks = marks or [False] * len(texts)
    short = len(texts) <= 3
    out = []
    i = 0
    while i < len(texts) - 1:
        a, b = texts[i], texts[i + 1]
        low_left = i == 0 or _significant_decimals(texts[i - 1]) < 3
        low_right = i + 2 >= len(texts) or _significant_decimals(texts[i + 2]) < 3
        need = (3 if (marks[i] or marks[i + 1] or short or (low_left and low_right)) else 4) + extra
        if _coord_pair_ok(a, b, need):
            out.append((i, i + 1))
            i += 2
        else:
            i += 1
    return out


def _ecef_ok(*values: str) -> bool:
    """Liegt (x, y, z) auf der Erdoberfläche – in Metern, Zentimetern oder Millimetern?"""
    try:
        x, y, z = (float(v) for v in values)
    except ValueError:
        return False
    r = (x * x + y * y + z * z) ** 0.5
    return any(6.30e6 <= r * scale <= 6.42e6 for scale in (1.0, 0.01, 0.001))


def _e7_ok(a: str, b: str) -> bool:
    """481371540,115761240 → 48.137154, 11.576124 (Grad × 1e7)."""
    try:
        x, y = int(a) / 1e7, int(b) / 1e7
    except ValueError:
        return False
    in_range = (abs(x) <= 90 and abs(y) <= 180) or (abs(y) <= 90 and abs(x) <= 180)
    return in_range and (abs(x) >= 1 or abs(y) >= 1)


def _number_text(value: Any) -> str | None:
    """Zahl oder Zahl als Text → Text wie im JSON-Export (sonst None)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"\s*[-+]?\d+(?:[.,]\d+)?\s*", value):
        return value.strip()
    return None


def structured_pairs(values: list, keyed: bool = False) -> list[tuple[int, int]]:
    """Koordinatenpaare unter benachbarten Zahlen eines Dicts (Reihenfolge der Werte) oder einer Liste.

    Eine Reihe sind direkt aufeinanderfolgende Zahlen (oder Zahlen als Text); alles andere trennt.
    In Dicts (keyed) ist eine Stelle mehr nötig: {"frequency_ppm": -12.345, "skew_ppm": 0.012} ist
    keine Koordinate, GPS-Werte haben 6 und mehr Stellen.
    """
    out: list[tuple[int, int]] = []
    run: list[tuple[int, str]] = []

    def flush() -> None:
        if len(run) >= 2:
            for i, j in pair_indices([t for _, t in run], extra=1 if keyed else 0):
                out.append((run[i][0], run[j][0]))
        run.clear()

    for index, value in enumerate(values):
        text = _number_text(value)
        if text is None:
            flush()
        else:
            run.append((index, text))
    flush()
    return out


def _is_coord_list(value: Any) -> bool:
    """[48.137, 11.576] oder ["48.137154", "11.576124"] (optional mit Höhe)."""
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        return False
    texts = []
    for v in value[:2]:
        if isinstance(v, float):
            if "e" in repr(v):
                return False
            texts.append(repr(v))
        elif isinstance(v, str) and re.fullmatch(r"\s*[-+]?\d{1,3}[.,]\d+\s*", v):
            texts.append(v.strip())
        else:
            return False
    return _coord_pair_ok(texts[0], texts[1], 3)


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


def is_public_host(name: str) -> bool:
    """Bekannter öffentlicher Zeitdienst oder Projektdomain (bleibt im Export lesbar)."""
    return _host_allowed(name)


def _host_allowed(name: str) -> bool:
    n = name.lower().rstrip(".")
    if n in PUBLIC_TIME_HOSTS or n in HARMLESS_DOMAINS or n in {"localhost", "localhost.localdomain"}:
        return True
    return n.endswith(PUBLIC_TIME_SUFFIXES)


def name_is_allowed(name: str, before: str = "") -> bool:
    """Darf ein Name mit Punkt im Export stehen bleiben?

    Nur bekannte öffentliche Zeitdienste/Projektdomains, Dateinamen und
    Bezeichner aus Programmcode (json.decoder.JSONDecodeError). Alles andere ist
    ein möglicher eigener Hostname – egal welche Endung.
    """
    raw = name.rstrip(".")
    n = raw.lower()
    if _host_allowed(n):
        return True
    labels = n.split(".")
    last = labels[-1]
    if last in FILE_EXTENSIONS:
        return True
    if last in AMBIGUOUS_EXTENSIONS:
        # "/usr/lib/foo.so", "test_x.py", "server.py", "chrony.conf.new" – aber nicht "kowalski.pl"
        if before in ("/", "\\", "_") or (len(labels) >= 3 and labels[-2] in FILE_EXTENSIONS):
            return True
        if len(labels) == 2 and ("_" in labels[0] or labels[0] in PROJECT_STEMS):
            return True
        return False
    # CamelCase in der letzten Stelle gibt es bei Domainendungen nicht (JSONDecodeError) –
    # nur bei längeren Namen, ".dE" ist eine Domain.
    tail = raw.split(".")[-1]
    return len(tail) >= 4 and bool(re.search(r"[a-z][A-Z]", tail))


_GENERIC_IFACE_RE = re.compile(
    r"(?:lo|(?:eth|wlan|usb|bond|tun|tap|wg|ppp|can|ib|team|vlan|dummy|docker|virbr|lxcbr|br|eno|ens|enp|wlp|wls)\d*"
    r"|(?:en|wl|ww|ib|sl)(?:o\d+|s\d+|p\d+s\d+|P\d+p\d+s\d+|b\d+|u\d+(?:u\d+)*(?:c\d+)?(?:i\d+)?)"
    r"(?:f\d+)?(?:d\d+)?(?:n\w+)?|veth[0-9a-f]{1,8}|br-[0-9a-f]{12}|end\d+|eth\d+-\w+)(?:\.\d+)?")


def interface_is_generic(name: str) -> bool:
    """eth0, enp3s0, wlan0, end0 … verraten nichts; „lan-mueller“ oder enx<MAC> schon."""
    return bool(_GENERIC_IFACE_RE.fullmatch(str(name or "").strip()))


def serial_is_specific(serial: str) -> bool:
    """Taugt eine gelesene Seriennummer zur exakten Suche? (nicht zu kurz, kein Platzhalter)"""
    v = str(serial or "").strip()
    if len(v) < 6 or len(v) > 64:
        return False
    if re.fullmatch(r"[0\s.:-]+|[fF]+|(?i:none|n/a|default string|to be filled by o\.e\.m\.|not specified"
                    r"|system serial number|0123456789(?:abcdef)?|123456789)", v):
        return False
    if re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d", v):  # PCI-Adresse (USB-Root-Hub)
        return False
    return True


def _refid_harmless(hex8: str) -> bool:
    """Refclock-RefIDs wie 47505300 ('GPS') sind Namen, keine Adressen."""
    raw = bytes.fromhex(hex8)
    text = raw.rstrip(b"\0")
    if text and all(65 <= c <= 90 or 48 <= c <= 57 for c in text) and 65 <= text[0] <= 90:
        return True
    # Nur Loopback/0.0.0.0 sind unbedenklich. Bei IPv6-Quellen ist die RefID ein Hash der
    # Adresse und landet oft im Multicast-/Reservebereich (z. B. E41BC59B) – kein „keep“.
    addr = ipaddress.IPv4Address(raw)
    return addr.is_loopback or addr.is_unspecified


# ---------------------------------------------------------------------------
# Der Filter
# ---------------------------------------------------------------------------


# Einzelne Zahl oder UTC-Zeitstempel (gpsd "time", Aufzeichnung) – die allgemeinen Regeln des
# Filters ändern sie nie (test_diagnostics prüft das gegen den vollen Filter). Bekannte Werte aus
# der Konfiguration (eine rein numerische Seriennummer, ein Hostname „4711“) können aber genau so
# aussehen – deshalb gilt der Schnellweg nur, wenn keins dieser Muster trifft (Sanitizer._plain).
_PLAIN_SAFE_RE = re.compile(r"[-+]?\d{1,11}(?:\.\d{1,11})?(?:[eE][-+]?\d{1,3})?"
                            r"|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")
PLAIN_CACHE_SIZE = 200_000     # Zeilen je Filterlauf
PLAIN_CACHE_MAX_LINE = 8192    # längere Zeilen werden nicht zwischengespeichert
PLAIN_CACHE_BYTES = 16 * 1024 * 1024   # Speicher je Filterlauf (Raspberry Pi)


class LineMemo:
    """Zwischenspeicher für Ergebnisse je Zeile, nach Speicher begrenzt.

    Ist die Grenze erreicht, wird einfach nichts Neues mehr gemerkt – das Ergebnis ist mit
    und ohne Eintrag dasselbe, nur langsamer. Größe grob: Schlüssel (wie Python ihn ablegt,
    nicht-Latin-1-Text also bis 4 Byte je Zeichen) plus Wert.
    """

    def __init__(self, max_bytes: int, max_key_chars: int = PLAIN_CACHE_MAX_LINE,
                 max_entries: int | None = None) -> None:
        self.max_bytes = max_bytes
        self.max_key_chars = max_key_chars
        self.max_entries = max_entries
        self.bytes = 0
        self._data: dict = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str):
        return self._data.get(key)

    def put(self, key: str, value, value_bytes: int = 0) -> None:
        if len(key) > self.max_key_chars:
            return
        size = sys.getsizeof(key) + 64 + value_bytes
        with self._lock:
            if key in self._data or self.bytes + size > self.max_bytes:
                return
            if self.max_entries is not None and len(self._data) >= self.max_entries:
                return
            self._data[key] = value
            self.bytes += size

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.bytes = 0


def _tuple_bytes(value) -> int:
    """Grobe Größe eines (verschachtelten) Tupels aus Strings für LineMemo."""
    if isinstance(value, tuple):
        return sys.getsizeof(value) + sum(_tuple_bytes(v) for v in value)
    return sys.getsizeof(value)


class Sanitizer:
    """Ein Filterlauf: Pseudonyme bleiben über alle Abschnitte eines Exports stabil."""

    def __init__(self, purpose: str = "diagnostics", known_names=(), known: dict | None = None) -> None:
        """known_names: eigene Host-/Domainnamen. known: {Kategorie: [Werte]} für exakte Suche –
        Kategorien "titel", "seriennummer", "schnittstelle", "name", "hostname"."""
        if purpose not in PURPOSES:
            raise ValueError(f"unbekannter Zweck: {purpose}")
        self.purpose = purpose
        self.removed: dict[str, int] = {}
        self._ips: dict[str, str] = {}
        self._hosts: dict[str, str] = {}
        self._clock_ids: dict[str, str] = {}
        self._ifaces: dict[str, str] = {}
        self._lock = threading.RLock()
        # Gleiche Zeilen kommen in Aufzeichnungen tausendfach vor („Leap status : Normal“).
        # Das Ergebnis hängt nur von der Zeile und den (stabilen) Pseudonymen ab.
        self._plain_cache = LineMemo(PLAIN_CACHE_BYTES, PLAIN_CACHE_MAX_LINE, PLAIN_CACHE_SIZE)
        known = dict(known or {})
        all_names = list(known_names) + list(known.pop("hostname", []) or [])
        names = sorted({str(n).strip().rstrip(".") for n in all_names if n and len(str(n).strip()) >= 3
                        and not _host_allowed(str(n)) and _ip_kind(str(n).strip().strip("[]")) is None},
                       key=len, reverse=True)
        self._names = names
        self._names_re = (re.compile(r"(?i)(?<![\w.<-])(" + "|".join(re.escape(n) for n in names)
                                     + r")(?![\w>-]|\.[A-Za-z0-9])") if names else None)
        tokens: dict[str, str] = {}
        for category, values in known.items():
            for value in values or ():
                v = " ".join(str(value or "").split())
                if category == "titel" and (v in DEFAULT_TITLES or len(v) < 3):
                    continue
                if category == "seriennummer" and not serial_is_specific(v):
                    continue
                if category == "schnittstelle" and (len(v) < 3 or interface_is_generic(v)):
                    continue
                if category == "name" and len(v) < 4:
                    continue
                if v and v.lower() not in tokens:
                    tokens[v.lower()] = category
        self._tokens = tokens
        ordered = sorted(tokens, key=len, reverse=True)
        self._tokens_re = (re.compile(r"(?i)(?<![^\W_])(" + "|".join(re.escape(t).replace("\\ ", r"\s+") for t in ordered)
                                      + r")(?![^\W_])") if ordered else None)

    def backstop_known(self) -> dict:
        """Was die Schlussprüfung (backstop) exakt suchen soll."""
        return {"names": list(self._names), "tokens": list(self._tokens)}

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
        if ident.startswith("<"):
            return ident  # schon ein Pseudonym
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
        if not v or v.startswith("<") or re.fullmatch(r"client-\d{2,}", v):
            return value  # leer oder schon ein Pseudonym
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
        if (_PLAIN_SAFE_RE.fullmatch(s)  # Zahl oder ISO-Zeitstempel: nichts zu filtern …
                and not (self._tokens_re is not None and self._tokens_re.search(s))
                and not (self._names_re is not None and self._names_re.search(s))):
            return s  # … außer sie ist selbst ein bekannter Wert oder Name
        if len(s) > PLAIN_CACHE_MAX_LINE:
            return self._plain_uncached(s)
        hit = self._plain_cache.get(s)
        if hit is not None:
            out, delta = hit
            for category, n in delta:  # Zählung wie beim ersten Mal (MANIFEST)
                self.count(category, n)
            return out
        before = dict(self.removed)
        out = self._plain_uncached(s)
        delta = tuple((k, v - before.get(k, 0)) for k, v in self.removed.items() if v != before.get(k, 0))
        self._plain_cache.put(s, (out, delta), sys.getsizeof(out) + 64 * len(delta))
        return out

    def _plain_uncached(self, s: str) -> str:
        s = s.translate(_DOTS)
        s = self._sub(_NMEA_RE, "position", lambda m: m.group(0).split(",", 1)[0] + "," + REMOVED, s)
        if self._tokens_re is not None:  # Titel, Seriennummern, Interface-Namen aus der Konfiguration
            s = self._sub(self._tokens_re, None, self._token, s)
        s = self._round_delay_text(s)
        s = self._dn(s)
        s = self._sub(_POSIX_TZ_RE, "zeitzone", "<zeitzone>", s)
        s = self._sub(_ZONE_WORDS_RE, "zeitzone", "<zeitzone>", s)
        s = self._sub(_COORD_NMEA_RE, "position", "<koordinaten>", s)
        s = self._sub(_COORD_HEMI_RE, "position", "<koordinaten>", s)
        s = self._sub(_COORD_DMS_RE, "position", "<koordinaten>", s)
        s = self._sub(_COORD_DEG_RE, "position", "<koordinaten>", s)
        s = self._sub(_ECEF_RE, "position",
                      lambda m: "<koordinaten>" if _ecef_ok(*m.group(1, 2, 3)) else m.group(0), s)
        s = self._sub(_E7_PAIR_RE, "position",
                      lambda m: "<koordinaten>" if _e7_ok(m.group(1), m.group(2)) else m.group(0), s)
        s = self._coord_pairs(s)
        s = self._sub(_XY_RE, "position", lambda m: (
            m.group(1) + REMOVED + m.group(3) + REMOVED if _coord_pair_ok(m.group(2), m.group(4), 3)
            else m.group(0)), s)
        s = self._sub(_KV_POS_RE, None, self._kv_pos, s)
        s = self._sub(_SAT_ROW_RE, "satellitenwinkel",
                      lambda m: m.group(1) + REMOVED + m.group(3) + REMOVED + m.group(5), s)
        s = self._sub(_SAT_DEG_RE, "satellitenwinkel",
                      lambda m: REMOVED + m.group(2) + REMOVED + m.group(4), s)
        s = self._sub(_LOCATOR_RE, "position", lambda m: m.group(1) + m.group(2) + "<koordinaten>", s)
        s = self._sub(_PLUSCODE_RE, "position", "<koordinaten>", s)
        s = self._sub(_TITLE_KV_RE, "titel", lambda m: m.group(1) + m.group(2) + (
            m.group(3) if m.group(3).strip().strip("\"'") in DEFAULT_TITLES else "<titel>"), s)
        s = self._sub(_BEARER_RE, "zugangsdaten", lambda m: m.group(1) + m.group(2) + "<entfernt>", s)
        s = self._sub(_APITOKEN_RE, "zugangsdaten", "ntpg_<entfernt>", s)
        s = self._sub(_EMAIL_RE, "e_mail", "<e-mail>", s)
        s = self._sub(_BYID_RE, "seriennummer", self._byid, s)
        s = self._sub(_SERIAL_KV_RE, "seriennummer", lambda m: m.group(1) + m.group(2) + "<seriennr>", s)
        s = self._sub(_SERIAL_WS_RE, "seriennummer", lambda m: m.group(1) + m.group(2) + "<seriennr>", s)
        s = self._sub(_UUID_RE, "kennung", "<uuid>", s)
        s = self._sub(_CLOCK_ID_RE, "uhr_id", self._clock_id, s)
        s = self._sub(_EUI64_RE, "uhr_id", lambda m: self.clock_pseudonym(m.group(0)), s)
        s = self._sub(_MAC_RE, "mac", lambda m: "<mac>" if _mac_identifies(m.group(0)) else m.group(0), s)
        s = self._sub(_IFACE_MAC_RE, "mac", lambda m: m.group(1) + "x<mac>", s)
        s = self._sub(_HEX12_RE, "kennung",
                      lambda m: m.group(0) if m.group(0).lower() in HEX12_HARMLESS else "<kennung>", s)
        s = self._sub(_HEXLONG_RE, "kennung", "<kennung>", s)
        s = self._sub(_ZONE_RE, "zeitzone", "<zeitzone>", s)
        s = self._sub(_ZONE_ABBR_RE, "zeitzone", "<zeitzone>", s)
        s = self._sub(_ZONE_LABEL_RE, "zeitzone", lambda m: m.group(1) + m.group(2) + m.group(3) + "<zeitzone>", s)
        s = self._sub(_REFID_CTX_RE, "refid", self._refid, s)
        s = _IPV6_TRUNC_RE.sub(self._ipv6_truncated, s)
        s = _IPV6_RE.sub(self._ipv6, s)  # zuerst: ::ffff:1.2.3.4 ist eine Adresse
        s = _IPV4_RE.sub(self._ipv4, s)
        s = _IP_DASHED_RE.sub(self._ip_dashed, s)
        s = self._sub(_DOMAIN_RE, "hostname", self._domain, s)
        if self._names_re is not None:
            s = self._sub(self._names_re, "hostname", lambda m: self.host_pseudonym(m.group(1)), s)
        return s

    def _dn(self, s: str) -> str:
        """Teile eines Zertifikats-DN (Land, Ort, Organisation …) – nur in DN-Zeilen, bekannte CAs bleiben."""
        parts = list(_DN_PART_RE.finditer(s))
        if not parts or (len(parts) < 2 and not _DN_CONTEXT_RE.search(s)):
            return s
        if any(ca in s.lower() for ca in KNOWN_CAS):
            return s
        return self._sub(_DN_PART_RE, "zertifikat", lambda m: (
            m.group(0) if m.group(3).strip().startswith("<") else m.group(1) + m.group(2) + "<zertifikatsname>"), s)

    def _ip_dashed(self, m: re.Match) -> str:
        kind = _ip_kind(m.group(2).replace("-", "."))
        if kind in (None, "keep"):
            return m.group(0)
        return self._ip(m.group(2).replace("-", "."))

    def _token(self, m: re.Match) -> str:
        category = self._tokens.get(" ".join(m.group(1).split()).lower(), "titel")
        self.count(category)
        if category == "titel":
            return "<titel>"
        if category == "seriennummer":
            return "<seriennr>"
        if category == "name":
            return "<name>"
        key = m.group(1).lower()
        with self._lock:
            if key not in self._ifaces:
                self._ifaces[key] = f"<schnittstelle-{len(self._ifaces) + 1}>"
            return self._ifaces[key]

    def _coord_pairs(self, s: str) -> str:
        # Bis nichts mehr gefunden wird: Nach dem Ersetzen sind die Reihen kürzer, und für kurze
        # Reihen gilt die strengere Regel (3 Stellen) – die Schlussprüfung sieht das Ergebnis.
        for _ in range(8):
            spans = coord_pair_spans(s)
            if not spans:
                return s
            out, last = [], 0
            for start, end in spans:
                out.append(s[last:start])
                out.append("<koordinaten>")
                self.count("position")
                last = end
            out.append(s[last:])
            s = "".join(out)
        return s

    # --- Laufzeiten -------------------------------------------------------------
    def round_delay(self, value: Any) -> Any:
        """Sekunden → auf 0,01 s gerundet (Zahl bleibt Zahl)."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        rounded = round(round(value / 0.01) * 0.01, 2)
        if rounded != value:
            self.count("latenz_gerundet")
            return rounded
        return value

    def _round_seconds_text(self, text: str) -> str:
        value = _to_float(text)
        if value is None:
            return text
        rounded = round(round(value / 0.01) * 0.01, 2)
        if rounded != value:
            self.count("latenz_gerundet")
        return f"{rounded:.2f}"  # immer zwei Stellen: so sieht man, dass gerundet wurde

    def _round_unit_text(self, text: str, unit: str) -> str:
        """Zahl in einer Zeiteinheit auf 10 ms runden; Einheit bleibt (23.456 ms → 20, 23456 us → 20000)."""
        unit = unit.strip().lower()
        factor = UNIT_SECONDS.get(unit, UNIT_SECONDS.get(unit.rstrip("s"), 1.0)) if unit else 1.0
        if factor >= 1.0:
            return self._round_seconds_text(text)
        value = _to_float(text)
        if value is None:
            return text
        step = 0.01 / factor
        rounded = int(round(value / step) * step)
        if rounded != value:
            self.count("latenz_gerundet")
        return str(rounded)

    def _round_delay_text(self, line: str) -> str:
        line = _DELAY_KV_RE.sub(lambda m: m.group(1) + m.group(2) + self._round_unit_text(m.group(3), m.group(4) or "")
                                + (m.group(4) or ""), line)
        if _DELAY_CONTEXT_RE.search(line):
            line = _DELAY_UNIT_RE.sub(self._round_unit_match, line)
        stripped = line.lstrip()
        if stripped[:1] in {"^", "="} and "+/-" in line:
            line = _SOURCE_ERR_RE.sub(self._round_source_error, line)
        return line

    def _round_unit_match(self, m: re.Match) -> str:
        if m.group(1) is not None:
            return self._round_unit_text(m.group(1), m.group(3)) + m.group(2) + m.group(3)
        return self._round_seconds_text(m.group(4)) + m.group(5) + m.group(6)

    def _round_source_error(self, m: re.Match) -> str:
        factor = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}[m.group(3)]
        seconds = float(m.group(2)) * factor
        ms = int(round(seconds / 0.01)) * 10
        out = f"{ms}ms"
        if out != m.group(2) + m.group(3):
            self.count("latenz_gerundet")
        return m.group(1) + out.rjust(len(m.group(2) + m.group(3)))

    def chronyc(self, args, text: Any) -> Any:
        """Ausgabe eines chronyc-Aufrufs filtern – im CSV-Modus mit RefID-, Namens- und Laufzeit-Spalten."""
        if not isinstance(text, str):
            return self.obj(text)
        argv = [str(a) for a in (args or [])]
        if "-c" in argv:
            command = next((a for a in argv if a in CHRONYC_CSV_COMMANDS), "")
            text = "\n".join(self._csv_row(command, row) for row in text.split("\n"))
        return self.text(text)

    def _source_name(self, name: str) -> str:
        """Name/IP-Spalte: Refclocks (GPS, PPS …) bleiben, alles andere wie ein Hostname."""
        if not name or re.fullmatch(r"[A-Z0-9]{1,4}", name) or name.startswith("<"):
            return name
        return self.host_value(name)

    def _csv_row(self, command: str, row: str) -> str:
        if not row or row.lstrip().startswith("#"):
            return row
        parts = row.split(",")
        idx: list[int] = []
        if command == "tracking" and len(parts) >= 13:
            idx = [10]                                   # root delay
            if re.fullmatch(r"[0-9A-Fa-f]{8}", parts[0]) and not _refid_harmless(parts[0]):
                self.count("refid")
                parts[0] = "<refid>"
                parts[1] = self.host_value(parts[1]) if parts[1] else parts[1]
        elif command == "sources" and len(parts) >= 10 and parts[0] in {"^", "="}:
            idx = [9]                                    # Fehlerschranke
            parts[2] = self._source_name(parts[2])
        elif command == "selectdata" and len(parts) >= 8 and not re.fullmatch(r"[A-Z0-9]{1,4}", parts[1]):
            idx = [len(parts) - 3, len(parts) - 2]       # Auswahlintervall (keine Refclock)
            parts[1] = self._source_name(parts[1])
        elif command == "ntpdata" and len(parts) >= 30:
            idx = [13, 19]                               # root delay, peer delay
        elif command in ("sourcestats", "authdata") and len(parts) >= 4:
            parts[0] = self._source_name(parts[0])
        elif command == "clients" and len(parts) >= 5:
            parts[0] = self.host_value(parts[0]) if parts[0] else parts[0]
        for i in idx:
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", parts[i]):
                parts[i] = self._round_seconds_text(parts[i])
        return ",".join(parts)

    def _kv_pos(self, m: re.Match) -> str:
        if m.group("label") is None:  # Bewegung (zweite Alternative)
            self.count("bewegung")
            return m.group("mq") + m.group("motion") + m.group("mq") + m.group("msep") + REMOVED
        key = m.group("label").lower()
        self.count("satellitenwinkel" if re.match(r"az|el", key) else "position")
        return m.group("q") + m.group("label") + m.group("dot") + m.group("q") + m.group("sep") + REMOVED

    def _clock_id(self, m: re.Match) -> str:
        ident, dash, port = _split_clock_port(m.group(0))
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
        head, hex8 = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
        if _refid_harmless(hex8):
            return m.group(0)
        return head + "<refid>"

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
            # 2a01:4f8:c17:5c1b:1234:5678:9abc – abgeschnitten, aber eindeutig eine Adresse
            if (addr.count(":") >= 4 and "::" not in addr and re.fullmatch(r"[0-9A-Fa-f:]+", addr)
                    and any(len(g) > 2 for g in addr.split(":"))):  # nicht ff:ff:ff:ff:ff:ff (MAC)
                return self._ipv6_partial(addr) + prefix
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

    def _ipv6_truncated(self, m: re.Match) -> str:
        """Von chronyc gekürzte IPv6 ("2a01:4f8:c17:5c1b:1234:5678:9a>"): Art am Präfix erkennen."""
        token = m.group(1)
        if token.count(":") < 3:
            return m.group(0)
        return self._ipv6_partial(token) + ">"

    def _ipv6_partial(self, token: str) -> str:
        """Unvollständige IPv6 (gekürzt oder abgeschnitten) → Platzhalter nach Art des Präfixes."""
        groups = token.split(":")
        kind = None
        for cut in (len(groups), len(groups) - 1):  # letzte Gruppe ist evtl. angeschnitten
            head = ":".join(groups[:cut]).rstrip(":")
            if not head:
                continue
            candidate = head + ("::" if cut < 8 and "::" not in head else "")
            kind = _ip_kind(candidate)
            if kind is None and "::" in head:
                kind = _ip_kind(head + (":0" if not head.endswith(":") else "0"))
            if kind is not None:
                break
        if kind == "keep":
            return token
        if kind == "private":
            self.count("private_ip")
            return self.ip_pseudonym(token)
        self.count("oeffentliche_ip")  # unklar → wie öffentlich behandeln
        return PUBLIC_IP

    def _domain(self, m: re.Match) -> str:
        name = m.group(1)
        start = m.start(1)
        if name_is_allowed(name, m.string[start - 1] if start else ""):
            return m.group(0)
        # Jeder andere Name mit Punkt – egal welche Endung (.us, .club, .rocks …).
        return self.host_pseudonym(name) + m.group(0)[len(name):]

    # --- strukturierte Daten --------------------------------------------------------
    def obj(self, value: Any, key: Any = None, parent: dict | None = None) -> Any:
        if isinstance(value, dict):
            return self._dict(value)
        if isinstance(value, (list, tuple)):
            if _is_coord_list(value):
                self.count("position")
                return "<koordinaten>"
            if _is_satellite_table(value):
                self.count("satellitenwinkel", 2 * len(value))
                return [[row[0], REMOVED, REMOVED, *[self.obj(v) for v in row[3:]]] for row in value]
            if _is_satellite_list(value):
                return self._satellite_summary(value)
            out = [self.obj(v, key, parent) for v in value]
            return self._scrub_pairs(out)
        if isinstance(value, str):
            return self.text(value)
        return value

    def _scrub_pairs(self, container: Any) -> Any:
        """Benachbarte Zahlen, die eine Koordinate ergeben ({"x": 11.576124, "y": 48.137154},
        [519.3, 48.137154, 11.576124]) → "<koordinaten>". Bis zum Fixpunkt (siehe _coord_pairs)."""
        for _ in range(8):
            values = list(container.values()) if isinstance(container, dict) else container
            pairs = structured_pairs(values, keyed=isinstance(container, dict))
            if not pairs:
                return container
            hit = {i for pair in pairs for i in pair}
            self.count("position", len(pairs))
            if isinstance(container, dict):
                container = {k: ("<koordinaten>" if i in hit else v) for i, (k, v) in enumerate(container.items())}
            else:
                container = ["<koordinaten>" if i in hit else v for i, v in enumerate(container)]
        return container

    def _satellite_summary(self, sats: list) -> dict:
        """Satellitenliste → nur Summen je System (gesehen, benutzt, Signalstärke Mittel/Max)."""
        self.count("satellitenliste", len(sats))
        systems: dict[str, dict] = {}
        for sat in sats:
            if not isinstance(sat, dict):
                continue
            system = sat.get("system")
            if not isinstance(system, str) or not system:
                system = GNSS_NAMES.get(sat.get("gnssid"), "unbekannt") if isinstance(sat.get("gnssid"), int) \
                    else "unbekannt"
            entry = systems.setdefault(system, {"gesehen": 0, "benutzt": 0, "_ss": []})
            entry["gesehen"] += 1
            for k in sat:
                if _norm(k) in ANGLE_KEYS and sat[k] is not None:
                    self.count("satellitenwinkel")
            entry["benutzt"] += 1 if sat.get("used") else 0
            ss = sat.get("ss", sat.get("snr"))
            if isinstance(ss, (int, float)) and not isinstance(ss, bool):
                entry["_ss"].append(ss)
        for entry in systems.values():
            ss = entry.pop("_ss")
            if ss:
                entry["snr_mittel"] = round(sum(ss) / len(ss))
                entry["snr_max"] = round(max(ss))
        return {"je_system": systems}

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
        chronyc_args = (d.get("args") if d.get("kind") == "chronyc" and isinstance(d.get("args"), list)
                        else None)
        ecef_keys = _ecef_keys(d)
        # chrony-Datensätze: Client-Adresse bzw. Name einer NTP-Quelle kann ein Reverse-DNS-Name sein.
        name_keys: set = set()
        if "address" in d and ("ntp_packets" in d or "cmd_packets" in d):
            name_keys.add("address")
        if d.get("mode") in ("^", "=") and isinstance(d.get("name"), str):
            name_keys.add("name")
        if isinstance(d.get("ref_name"), str) and not re.fullmatch(r"[A-Z0-9]{1,4}", d["ref_name"]):
            name_keys.add("ref_name")
        has_host = any(_norm(k) in HOST_KEYS | ADDRESS_KEYS | {"server", "remote", "name"} for k in d)
        out: dict = {}
        for raw_key, value in d.items():
            if raw_key in ecef_keys:
                self.count("position")
                continue
            if chronyc_args is not None and raw_key == "out" and isinstance(value, str):
                out[raw_key] = self.chronyc(chronyc_args, value)
                continue
            nk = _norm(raw_key)
            if allowed is not None and raw_key not in allowed:
                self._count_dropped_key(nk, default="position")
                continue
            if cls == "SKY" and raw_key == "satellites" and isinstance(value, list):
                out[raw_key] = self._satellite_summary(value) if value else value
                continue
            if raw_key in name_keys and isinstance(value, str):
                out[raw_key] = self.host_value(value)
                continue
            result = self._value(raw_key, nk, value, gps_like, has_host)
            if result is _DROP:
                continue
            new_key = self.text(raw_key) if isinstance(raw_key, str) else raw_key
            n = 2
            base = new_key
            while new_key in out:  # zwei Adressen → gleicher Platzhalter: nichts überschreiben
                new_key = f"{base} ({n})"
                n += 1
            out[new_key] = result
        return self._scrub_pairs(out)

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

    def _leaves(self, value: Any, fn) -> Any:
        """fn auf jeden Text-Wert darunter anwenden (Listen und Dicts eingeschlossen)."""
        if isinstance(value, dict):
            return {k: self._leaves(v, fn) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._leaves(v, fn) for v in value]
        if isinstance(value, str) and value:
            return fn(value)
        return value

    def _cert_leaf(self, value: str) -> str:
        self.count("zertifikat")
        return "<zertifikatsname>"

    def _issuer_leaf(self, value: str) -> str:
        if any(ca in value.lower() for ca in KNOWN_CAS) or re.fullmatch(r"[A-Z]{1,2}\d{1,2}", value.strip()):
            return self.text(value)  # Let's Encrypt, R3, E5 …
        self.count("zertifikat")
        return "<aussteller>"

    def _tz_leaf(self, value: str) -> str:
        if re.fullmatch(r"(?:UTC|GMT|Z)?(?:[+-]\d{1,2}(?::?\d{2})?)?", value.strip()):
            return value
        self.count("zeitzone")
        return "<zeitzone>"

    def _value(self, raw_key: Any, nk: str, value: Any, gps_like: bool, has_host: bool = False) -> Any:
        scalar = not isinstance(value, (dict, list, tuple))
        tokens = key_tokens(raw_key)
        is_cert = nk in CERT_KEYS or (bool(tokens & CERT_TOKENS) and nk not in ISSUER_KEYS
                                      and not tokens & {"issuer"})
        if is_cert and value not in (None, "", [], {}):
            return self._leaves(value, self._cert_leaf)
        kind = None if is_cert else _key_kind(raw_key)
        if kind is not None:
            if value not in (None, "", [], {}):
                self.count(kind)
            return _DROP
        if nk in NAME_KEYS and isinstance(value, str) and value:
            self.count("name")
            return "<name>"
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
        if nk in SERIAL_KEYS or nk == "sn" or _serial_like_key(raw_key):
            if value not in (None, "", [], {}):
                self.count("seriennummer")
            return _DROP
        if isinstance(value, dict) and _compass_keys(value):
            self.count("position")
            return {k: v for k, v in self._dict(value).items() if k not in _compass_keys(value)}
        if nk in MAC_KEYS and scalar:
            if value not in (None, ""):
                self.count("mac")
            return _DROP
        if (isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{12}", value.strip())
                and tokens & MAC_LIKE_TOKENS and value.strip().lower() not in HEX12_HARMLESS):
            self.count("mac")  # nackte MAC unter "address", "iface" …
            return "<mac>"
        if nk in SECRET_KEYS or tokens & SECRET_TOKENS:
            if value not in (None, "", {}):
                self.count("zugangsdaten")
            return _DROP
        if nk in TITLE_KEYS and isinstance(value, str):
            if value.strip() in DEFAULT_TITLES:
                return value
            self.count("titel")
            return "<titel>"
        if nk in TITLE_KEYS and not scalar:
            return self._leaves(value, lambda v: v if v.strip() in DEFAULT_TITLES else self._count_ret("titel", "<titel>"))
        if (nk in ISSUER_KEYS or "issuer" in tokens) and value not in (None, "", [], {}):
            return self._leaves(value, self._issuer_leaf)
        if nk in HOST_KEYS and isinstance(value, str):
            return self.host_value(value)
        if nk in HOST_KEYS and isinstance(value, (list, tuple)):
            return [self.host_value(v) if isinstance(v, str) else self.obj(v) for v in value]
        if nk in ADDRESS_KEYS and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,253}", value.strip()) \
                and re.search(r"[A-Za-z]", value):
            return self.host_value(value)
        if nk in TZ_KEYS and value not in (None, "", [], {}) and not isinstance(value, (int, float, bool)):
            return self._leaves(value, self._tz_leaf)
        if nk in REFID_KEYS and isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{8}", value):
            if _refid_harmless(value):
                return value
            self.count("refid")
            return "<refid>"
        if nk in REFID_KEYS and isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2 ** 32:
            if _refid_harmless(f"{value:08X}"):
                return value
            self.count("refid")
            return "<refid>"
        if nk in CLOCK_ID_KEYS and isinstance(value, str) and value:
            self.count("uhr_id")
            return self.clock_pseudonym(value)
        if tokens & SKY_TOKENS and isinstance(value, (list, tuple, dict)):
            return self._sky(value)
        factor = _delay_factor(raw_key, nk, tokens, has_host)
        if factor is not None:  # für jeden Zweck – auch Kennzahlen ({"min", "max", …}) darunter
            return self._round_delays(value, factor)
        return self.obj(value, raw_key)

    def _sky(self, value: Any) -> Any:
        """Unter sats/skyview: jede kurze Zahlenreihe [prn?, az, el] verliert ihre Winkel."""
        if isinstance(value, dict):
            return {k: self._sky(v) for k, v in self._dict(value).items()}
        if isinstance(value, (list, tuple)):
            if _is_satellite_table(value) or _is_satellite_list(value):
                return self.obj(value)
            nums = [v for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if 2 <= len(value) <= 6 and len(nums) == len(value):
                self.count("satellitenwinkel", 2)
                return [value[0], REMOVED, REMOVED, *value[3:]] if len(value) >= 3 else [REMOVED, REMOVED]
            return [self._sky(v) for v in value]
        return self.obj(value)

    def _count_ret(self, category: str, out: str) -> str:
        self.count(category)
        return out

    def _round_delays(self, value: Any, factor: float) -> Any:
        """Laufzeit in Einheit factor (Sekunden je Einheit) auf 10 ms runden – Zahlen und Zahlen-Texte."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if factor >= 1.0:
                return self.round_delay(value)
            step = 0.01 / factor
            rounded = round(value / step) * step
            rounded = int(rounded) if float(rounded).is_integer() else rounded
            if rounded != value:
                self.count("latenz_gerundet")
                return rounded
            return value
        if isinstance(value, str) and re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?\s*", value):
            unit = {1.0: "s", 1e-3: "ms", 1e-6: "us", 1e-9: "ns"}.get(factor, "s")
            return self._round_unit_text(value.strip(), unit)
        if isinstance(value, dict):
            return {k: (v if _norm(k) in {"n", "count", "samples"} else self._round_delays(v, factor))
                    for k, v in self._dict(value).items()}
        if isinstance(value, (list, tuple)):
            return [self._round_delays(v, factor) for v in value]
        return self.obj(value)


GNSS_NAMES = {0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou", 4: "IMES", 5: "QZSS", 6: "GLONASS", 7: "NavIC"}


def _delay_factor(raw_key: Any, nk: str, tokens: set, has_host: bool) -> float | None:
    """Ist der Schlüssel eine Laufzeit? → Sekunden je Einheit (1, 1e-3 …), sonst None."""
    unit = next((UNIT_SECONDS[t] for t in tokens if t in UNIT_SECONDS), None)
    if nk in DELAY_KEYS:
        return 1e-3 if nk.endswith("ms") else (unit or 1.0)
    if tokens & DELAY_TOKENS or {"round", "trip"} <= tokens:
        return unit or 1.0
    # {"host": "ptbtime1.ptb.de", "time_ms": 23.456} – Antwortzeit zu einem Server
    if has_host and unit is not None and tokens <= {"time", "ms", "us", "ns", "s", "response", "antwort",
                                                   "antwortzeit", "dauer", "duration"}:
        return unit
    return None


def _is_satellite_list(value: Any) -> bool:
    """[{"PRN": 5, "ss": 40, …}, …] – Liste einzelner Satelliten (mit oder ohne Winkel)."""
    if not isinstance(value, (list, tuple)) or not value:
        return False
    return all(isinstance(v, dict) and any(_norm(k) in {"prn", "svid"} for k in v) for v in value)


_DROP = object()
CHRONYC_CSV_COMMANDS = {"tracking", "sources", "sourcestats", "selectdata", "ntpdata", "authdata", "clients",
                        "serverstats", "activity"}


def _serial_like_key(key: Any) -> bool:
    """serial_no_x, iSerialNumber … – aber nicht serial_port/serial_device (Schnittstellen)."""
    tokens = key_tokens(key)
    return "serial" in tokens and not tokens & {"port", "ports", "device", "devices", "dev", "tty", "console",
                                                  "baud", "speed", "path", "paths"}


_COMPASS = {"n", "e", "s", "w", "o", "north", "east", "south", "west", "nord", "ost", "süd", "sued"}


def _compass_keys(d: dict) -> set:
    """{"n": 48.137154, "e": 11.576124} – Himmelsrichtungen mit Koordinatenwerten."""
    found = [k for k, v in d.items() if str(k).lower() in _COMPASS and isinstance(v, (int, float, str))
             and not isinstance(v, bool)]
    if len(found) < 2:
        return set()
    values = [str(d[k]) for k in found[:2]]
    return set(found) if _coord_pair_ok(values[0], values[1], 3) else set()


def _is_satellite_table(value: Any) -> bool:
    """[[prn, az, el, ss, …], …] – Satelliten als Zahlenreihen ohne Schlüssel."""
    if not isinstance(value, (list, tuple)) or len(value) < 1:
        return False
    for row in value:
        if not isinstance(row, (list, tuple)) or not 4 <= len(row) <= 6:
            return False
        prn, az, el = row[0], row[1], row[2]
        if not all(isinstance(v, (int, float, str)) for v in row[3:]):
            return False
        if isinstance(az, str) or isinstance(el, str) or not isinstance(az, (int, float)) \
                or not isinstance(el, (int, float)):
            return False
        if isinstance(prn, str):  # "G05", "GPS5" – PRN mit System
            if not re.fullmatch(r"[A-Za-z]{0,7}\d{1,3}", prn):
                return False
        elif isinstance(prn, bool) or not isinstance(prn, int) or not 1 <= prn <= 400:
            return False
        if isinstance(az, bool) or isinstance(el, bool) or not (0 <= az <= 360 and -90 <= el <= 90):
            return False
    return True


def _ecef_keys(d: dict) -> set:
    """Schlüssel x/y/z (o. ä.), deren Werte zusammen einen Punkt auf der Erdoberfläche ergeben."""
    found = {}
    for key, value in d.items():
        t = str(key).lower().replace("ecef", "").strip("_-. ")
        if t in {"x", "y", "z"} and isinstance(value, (int, float)) and not isinstance(value, bool):
            found[t] = key
    if len(found) == 3 and _ecef_ok(*(str(d[found[c]]) for c in "xyz")):
        return set(found.values())
    return set()

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


# Gleiche Zeilen prüft check_no_leaks nur einmal (Aufzeichnungen und Logs durchlaufen die
# Prüfung mehrfach). Die Funde hängen nur von der Zeile ab – Pfade werden je Aufruf neu gesetzt.
# Nach Speicher begrenzt; diagnostics leert die Speicher nach jedem Paket (clear_check_caches).
CHECK_CACHE_BYTES = 8 * 1024 * 1024
JSON_CACHE_MAX_LINE = 64 * 1024     # längere JSON-Zeilen werden jedes Mal neu geprüft
_TEXT_MEMO = LineMemo(CHECK_CACHE_BYTES, PLAIN_CACHE_MAX_LINE)
_JSON_MEMO = LineMemo(CHECK_CACHE_BYTES, JSON_CACHE_MAX_LINE)
_NOT_OBJECT = object()  # Merker im Zwischenspeicher: Zeile ist kein JSON-Objekt


def clear_check_caches() -> None:
    _TEXT_MEMO.clear()
    _JSON_MEMO.clear()


def _text_findings(text: str, path: str) -> list[dict]:
    if len(text) > PLAIN_CACHE_MAX_LINE:
        return _text_findings_uncached(text, path)
    return [{"kind": kind, "path": path or "$", "text": snippet}
            for kind, snippet in _text_findings_cached(text)]


def _text_findings_cached(text: str) -> tuple:
    hit = _TEXT_MEMO.get(text)
    if hit is None:
        hit = tuple((f["kind"], f["text"]) for f in _text_findings_uncached(text, ""))
        _TEXT_MEMO.put(text, hit, _tuple_bytes(hit))
    return hit


def _text_findings_uncached(text: str, path: str) -> list[dict]:
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
        if re.search(r"[1-9A-Fa-f]", _split_clock_port(m.group(0))[0]):
            found.append(_finding("uhr_id", path, m.group(0)))
    for m in _MAC_RE.finditer(text):
        if _mac_identifies(m.group(0)):
            found.append(_finding("mac", path, m.group(0)))
    for m in _KV_POS_RE.finditer(text):
        found.append(_finding("position", path, m.group(0)))
    for start, end in coord_pair_spans(text):
        found.append(_finding("position", path, text[start:end]))
    for m in _ECEF_RE.finditer(text):
        if _ecef_ok(*m.group(1, 2, 3)):
            found.append(_finding("position", path, m.group(0)))
    for m in _IFACE_MAC_RE.finditer(text):
        found.append(_finding("mac", path, m.group(0)))
    for m in _IPV6_TRUNC_RE.finditer(text):
        if m.group(1).count(":") >= 3:
            found.append(_finding("oeffentliche_ip", path, m.group(0)))
    for m in _ZONE_LABEL_RE.finditer(text):
        found.append(_finding("zeitzone", path, m.group(0)))
    for m in _BYID_RE.finditer(text):
        head, sep, last = m.group(1).rpartition("_")
        if sep and _is_serial_token(last):
            found.append(_finding("seriennummer", path, m.group(0)))
    for m in _SERIAL_KV_RE.finditer(text):
        found.append(_finding("seriennummer", path, m.group(0)))
    for m in _SERIAL_WS_RE.finditer(text):
        found.append(_finding("seriennummer", path, m.group(0)))
    for m in _REFID_CTX_RE.finditer(text):
        if not _refid_harmless(m.group(2) or m.group(4)):
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
    if not found:
        found.extend(_probe_findings(text, path))
    return found


def _probe_findings(text: str, path: str) -> list[dict]:
    """Alles, was der Filter an dieser Zeile noch ändern würde, ist ein Fund.

    Die Ausgabe des Filters ist ein Fixpunkt (ein zweiter Lauf ändert nichts). Damit prüft
    check_no_leaks automatisch jede Regel des Filters – auch neue – ohne eigene Liste.
    """
    if not text or not re.search(r"[0-9A-Za-z]", text):
        return []
    probe = Sanitizer("diagnostics")
    clean = probe._plain(text)
    if clean == text:
        return []
    kind = next(iter(probe.removed), "filter")
    i = next((n for n, (a, b) in enumerate(zip(text, clean)) if a != b), min(len(text), len(clean)))
    return [_finding(kind, path, text[max(0, i - 10):i + 60])]


def _walk(value: Any, path: str, found: list[dict], parent_gps: bool = False) -> None:
    if isinstance(value, dict):
        gps_like = isinstance(value.get("class"), str) or "mode" in value or "has_fix" in value
        for key, sub in value.items():
            nk = _norm(key)
            sub_path = f"{path}.{key}" if path else str(key)
            scalar = not isinstance(sub, (dict, list, tuple))
            if isinstance(key, str):
                found.extend(_text_findings(key, sub_path))
            kind = None if nk in CERT_KEYS else _key_kind(key)
            if kind is not None and sub not in (None, "", [], {}):
                found.append(_finding(kind, sub_path, f"{key}=…"))
                continue
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
        if _is_coord_list(value):
            found.append(_finding("position", path, repr(list(value))))
        if _is_satellite_table(value):
            found.append(_finding("satellitenwinkel", path, "[[prn, az, el, …], …]"))
        for i, sub in enumerate(value):
            _walk(sub, f"{path}[{i}]", found, parent_gps)
    elif isinstance(value, str):
        for number, line in enumerate(value.split("\n"), 1):  # wie der Filter: zeilenweise
            # JSON-Zeile (Aufzeichnung, gpsd): wie Sanitizer._line geparst prüfen – sonst
            # stünden die Zeilen eines eingebetteten chronyc-Texts auf einer Zeile.
            hits = _json_line_findings(line, f"{path} Zeile {number}" if path else f"Zeile {number}",
                                       max_len=1_000_000)  # wie Sanitizer._line
            if hits is None:
                found.extend(_text_findings(line, path))
            else:
                found.extend(hits)


_ROOT = "\0"  # Platzhalter-Pfad für zwischengespeicherte Funde


def _json_line_findings(line: str, sub_path: str, max_len: int | None = None) -> list[dict] | None:
    """Funde einer JSON-Objekt-Zeile (None: keine solche Zeile). Gleiche Zeilen werden nur
    einmal geprüft – Aufzeichnungen durchlaufen die Prüfung sonst mehrfach komplett.

    max_len: längere Zeilen gelten als Text (wie in _walk/Sanitizer._line). check_no_leaks auf
    einem Text setzt keine Grenze – dort wird jede JSON-Zeile geparst, egal wie lang."""
    stripped = line.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    if max_len is not None and len(stripped) >= max_len:
        return None
    if len(stripped) > JSON_CACHE_MAX_LINE:
        hits = _json_line_findings_uncached(stripped)
    else:
        hits = _JSON_MEMO.get(stripped)
        if hits is None:
            hits = _json_line_findings_uncached(stripped)
            _JSON_MEMO.put(stripped, _NOT_OBJECT if hits is None else hits, _tuple_bytes(hits or ()))
        elif hits is _NOT_OBJECT:
            hits = None
    if hits is None:
        return None
    return [{"kind": kind, "path": sub_path + where[len(_ROOT):] if where.startswith(_ROOT) else where,
             "text": text} for kind, where, text in hits]


def _json_line_findings_uncached(stripped: str) -> tuple | None:
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    found: list[dict] = []
    _walk(parsed, _ROOT, found)
    if not found:
        found.extend(_struct_probe(parsed, _ROOT))
    return tuple((f["kind"], f["path"], f["text"]) for f in found)


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
            hits = _json_line_findings(line, f"Zeile {number}")  # ohne Längengrenze: jede JSON-Zeile
            if hits is None:
                found.extend(_text_findings(line, f"Zeile {number}"))
            else:
                found.extend(hits)
        return found
    _walk(obj_or_text, "", found)
    if not found:
        found.extend(_struct_probe(obj_or_text, ""))
    return found


def _struct_probe(value: Any, path: str) -> list[dict]:
    """Strukturierte Daten: Würde der Filter noch etwas ändern? → Fund mit Pfad der ersten Abweichung."""
    probe = Sanitizer("diagnostics")
    try:
        clean = probe.obj(value)
    except Exception:  # pragma: no cover – ein Prüfer darf nicht abstürzen
        return [_finding("filter", path, "Prüfung fehlgeschlagen")]
    if _same(clean, value):
        return []
    where, text = _first_difference(value, clean, path)
    return [_finding(next(iter(probe.removed), "filter"), where, text)]


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b or (isinstance(a, (int, float)) and not isinstance(a, bool)
                                              and isinstance(b, (int, float)) and not isinstance(b, bool) and a == b)


def _first_difference(old: Any, new: Any, path: str) -> tuple[str, str]:
    if isinstance(old, dict) and isinstance(new, dict):
        for k in old:
            if k not in new:
                return (f"{path}.{k}" if path else str(k)), f"{k}=…"
            if not _same(old[k], new[k]):
                return _first_difference(old[k], new[k], f"{path}.{k}" if path else str(k))
        return path or "$", "Schlüssel geändert"
    if isinstance(old, (list, tuple)) and isinstance(new, (list, tuple)) and len(old) == len(new):
        for i, (a, b) in enumerate(zip(old, new)):
            if not _same(a, b):
                return _first_difference(a, b, f"{path}[{i}]")
    return path or "$", repr(old)[:80]


# --- Unabhängige Schlussprüfung ------------------------------------------------------
#
# Bewusst eigene, einfache Muster – NICHT die des Filters oben. Was der Filter
# übersieht, soll hier trotzdem auffallen. Geprüft werden die fertigen Bytes,
# genau so, wie sie das Gerät verlassen würden.

_BS_HEX12 = re.compile(r"(?<![0-9a-fA-F.])([0-9a-fA-F]{12})(?![0-9a-fA-F])")
_BS_HEXLONG = re.compile(r"(?<![0-9a-fA-F.])(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*[0-9])[0-9a-fA-F]{16,}(?![0-9a-fA-F])")
_BS_MAC_SEP = re.compile(r"(?<![0-9a-fA-F:-])(?<![0-9a-fA-F]\.)(?:[0-9a-fA-F]{2}([:.-])[0-9a-fA-F]{2}(?:\1[0-9a-fA-F]{2}){4}"
                         r"|[0-9a-fA-F]{6}-[0-9a-fA-F]{6}"
                         r"|(?<![0-9a-fA-F] )[0-9a-fA-F]{2}(?: [0-9a-fA-F]{2}){5}(?! [0-9a-fA-F]{1,2}(?![^\W_])))"
                         r"(?![0-9a-fA-F:-])(?!\.[0-9a-fA-F])")
_BS_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_BS_DOTTED = re.compile(r"[^\W_](?:[^\W_]|-)*(?:\.[^\W_](?:[^\W_]|-)*)+")
_BS_NMEA = re.compile(r"\d{4}\.\d+\s*,?\s*[NS]\W{0,3}\d{5}\.\d+\s*,?\s*[EWO]")
# NMEA-Sätze mit Position oder Satellitenwinkeln, die nicht schon "<entfernt>" sind
_BS_NMEA_SENTENCE = re.compile(r"(?:\$|(?<![\w$]))(?:G[PNLABQI]|BD|QZ|PQ)(?:GGA|RMC|GLL|GNS|GSV),(?!<entfernt>)"
                               r"|\$PUBX,0[0-4],(?!<entfernt>)")
_BS_TRUNC_V6 = re.compile(r"[0-9a-fA-F:]{6,}(?:%[\w.-]*)?>")
_BS_LABELLED = re.compile(r"(?i)(?<![^\W_])(?:lat|latitude|lon|lng|longitude|breite|länge|laenge|höhe|hoehe|alt|altitude"
                          r"|azimuth|azimut|azim|elevation|elev|az|el|breitengrad|längengrad|laengengrad|lati|longi|mlat|mlon)"
                          r"(?:[_-]?(?:e7|deg))?\.?[\"']?(?:[ \t]*(?:[:=,]|%3[dDaA])[ \t]*|[ \t]+)[\"']?[-+]?\d")
# Grad/Minuten(/Sekunden) mit Halbkugel: 48°08'13.8"N, 48 deg 8' 13.75" N, 48d08m13.8sN, 48 8 13.75 N,
# N 48° 08.229 (Geocaching)
_BS_DMS = re.compile(r"(?<![\w.])\d{1,3}\s*(?:°|deg\b)\s*\d{1,2}(?:[.,]\d+)?\s*(?:['′]|min\b)?"
                     r"(?:\s*\d{1,2}(?:[.,]\d+)?\s*(?:\"|″|''|sec\b|s\b)?)?\s*[NSEWO](?![^\W_])"
                     r"|(?<![\w.])\d{1,3}d\s*\d{1,2}(?:[.,]\d+)?m(?:\s*\d{1,2}(?:[.,]\d+)?s)?\s*[NSEWO](?![^\W_])"
                     r"|(?<![\w.:])\d{1,3}\s+\d{1,2}\s+\d{1,2}[.,]\d+\s*[NSEWO](?![^\W_])"
                     r"|(?<![^\W_])[NSEWO]\s*\d{1,3}\s*°\s*\d{1,2}[.,]\d{2,}"
                     r"|(?<![^\W_])[NS]\s*\d{1,2}\s+\d{1,2}[.,]\d{2,}['′]?\s*[,;/]?\s*[EWO]\s*\d{1,3}\s+\d{1,2}[.,]\d{2,}")
_BS_E7 = re.compile(r"(?<![\w.,:-])([-+]?\d{8,10})\s*[,;/ ]\s*([-+]?\d{8,10})(?![\w.,])")
_BS_SAT_ROW = re.compile(r"^\s*\d{1,3}\s+\d{1,3}\s+-?\d{1,2}\s+\d{1,2}(?:\.\d)?\s+[YN]\s*$"
                         r"|(?<![\w.])\d{1,3}\s*°\s+-?\d{1,2}\s*°(?!\s*\d)")
_BS_SAT_LIST = re.compile(r"\\?\"(?:prn|PRN|svid)\\?\"\s*:")
_BS_ZONE = re.compile(r"\b(?:Europe|America|Asia|Africa|Australia|Pacific|Atlantic|Indian|Antarctica)/[A-Z][a-z]"
                      r"|(?<![\w<])[A-Za-z]{3,6}[+-]?\d{1,2}(?::\d{2}){0,2}[A-Za-z]{3,6}(?:[+-]?\d{1,2}(?::\d{2}){0,2})?"
                      r",(?:M\d{1,2}\.\d\.\d|J?\d{1,3})(?:/[+-]?\d{1,3}(?::\d{2}){0,2})?,(?:M\d{1,2}\.\d\.\d|J?\d{1,3})"
                      r"|(?i:\b(?:mittel|west|ost|nord|süd)?europäische\s+(?:sommer|normal|standard)?zeit\b)"
                      r"|(?i:\b[A-Z][\w.]*\.?\s+(?:standard|daylight|summer)\s+time\b)")
# Laufzeiten: mit Bezeichnung ungerundet (mehr als 2 Stellen) oder als ms-Wert, der kein Vielfaches von 10 ist
_BS_DELAY = re.compile(r"(?i)\b(?:delay|rtt|latency|laufzeit|latenz|antwortzeit|round[ -]?trip(?:[ -]?time)?"
                       r"|root\s+distance)\s*[:=]\s*[-+]?\d+\.\d{3,}")
_BS_DELAY_CONTEXT = re.compile(r"(?i)\b(?:delay|rtt|latency|laufzeit|latenz|antwort|ping|round.?trip)")
_BS_DELAY_MS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(ns|us|µs|ms)\b|(?<![\w.])\d+\.\d{3,}\s*(?:seconds?|sec|s)\b")
_BS_SERIAL = re.compile(r"(?<![\w/])(?:(?i:serial(?:[ _-]?(?:number|no\.?|nr\.?))?|iserial(?:number)?|seriennummer"
                        r"|serien-?nr\.?|serien-?nummer)|S/N|SN)(?:\s*[:=]\s*\"?|\s+)(?!<)(?!tty)"
                        r"(?=[A-Za-z0-9.-]*\d)[A-Za-z0-9][A-Za-z0-9.-]{5,}(?![\w:/])")
_BS_DN_PART = re.compile(r"(?<![\w])(?:CN|C|ST|L|O|OU|street|postalCode|emailAddress)\s*=\s*(\S?)")
_BS_DN_VALUE = re.compile(r"(?<![\w])(?:C|ST|L|O|OU|street|postalCode)\s*=\s*(?!<)[^\s,/<]")
_BS_CLOCK_ID = re.compile(r"(?<![0-9a-fA-F.:-])(?:[0-9a-fA-F]{6}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{6}"
                          r"|[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){7})(?![0-9a-fA-F.:])")
_BS_REFID_LABEL = re.compile(r"(?i)\bref[ _-]?id\s*[:=]?\s*([0-9a-f]{8})(?=\)|\s|,|$)")
_BS_XY = re.compile(r"(?i)(?<![^\W_])x\s*[:=]\s*([-+]?\d{1,3}[.,]\d{3,})\s*[,;]?\s*y\s*[:=]\s*([-+]?\d{1,3}[.,]\d{3,})(?![\d])")
_BS_CSV_REFID = re.compile(r"^([0-9A-Fa-f]{8}),[^,\n]*,\d{1,2},\d{9,}\.\d+,")
_BS_IP_DASHED = re.compile(r"(?<![\w.-])(?:[A-Za-z]{1,12}-)?(\d{1,3}(?:-\d{1,3}){3})(?![\w-])")
_BS_TOKEN = re.compile(r"(?<![\w])ntpg_[A-Za-z0-9_-]{8,}|(?i:\bbearer\s+(?!<)[A-Za-z0-9._~+/=-]{8,})")
_BS_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})
# Platzhalter, die dieser Filter selbst schreibt – nur sie sind als "eigene" Werte erlaubt.
BACKSTOP_ALLOWED_HEX: set[str] = set(HEX12_HARMLESS)


def _bs_is_number_char(c: str) -> bool:
    return c.isdigit() or c in ".,"


def _bs_numbers(line: str) -> list[tuple[int, int, str]]:
    """Alle Zahlen einer Zeile, die nicht Teil eines Worts/einer Adresse sind."""
    out = []
    for m in _BS_NUMBER.finditer(line):
        start, end = m.start(), m.end()
        before = line[start - 1] if start else " "
        after = line[end] if end < len(line) else " "
        if before in "NSEWO" and start >= 2 and (line[start - 2].isalnum() or line[start - 2] == "_"):
            continue  # "SN12.3" – kein Halbkugel-Buchstabe
        if line[max(0, start - 3):start] in {"%2C", "%2c", "%3B", "%3b", "%20"}:
            before = " "
        if (before.isalnum() and before not in "NSEWO") or before == "." or before == "_":
            continue
        if after.isalnum() and after not in "NSEWOm" or after == "_":
            continue
        if after == "." and end + 1 < len(line) and line[end + 1].isdigit():
            continue  # 192.168.1.5 o. ä.
        out.append((start, end, m.group(0)))
    return out


def _bs_decimals(text: str) -> int:
    """Stellen nach dem Komma, ohne Nullen am Ende (echte Koordinaten enden nicht auf 000000)."""
    t = text.lstrip("+-").replace(",", ".")
    return len(t.split(".", 1)[1].rstrip("0")) if "." in t else 0


def _bs_float_pairs(line: str) -> list[str]:
    if not re.search(r"\d[.,]\d\d\d", line):
        return []
    nums = _bs_numbers(line)
    hits = []
    # Läufe: Zahlen, zwischen denen höchstens Trenner/Halbkugel/° stehen
    groups: list[list[tuple[int, int, str]]] = []
    for item in nums:
        if groups:
            gap = line[groups[-1][-1][1]:item[0]]
            if re.fullmatch(r"[\s,;/|°NSEWO+&]*|\s*%2[cC]\s*|\s*%3[bB]\s*|%20|\s+(?:-|und|and)\s+", gap):
                groups[-1].append(item)
                continue
        groups.append([item])
    for group in groups:
        for k, (a, b) in enumerate(zip(group, group[1:])):
            gap = line[a[1]:b[0]]
            marked = (bool(re.search(r"°|(?<![^\W_])[NSEWO](?![^\W_])", gap))
                      or bool(re.search(r"(?<![^\W_])[NSEWO]\s?$", line[:a[0]]))
                      or bool(re.match(r"\s*°|\s?[NSEWO](?![^\W_])", line[b[1]:])))
            # Nachbarn mit weniger als 3 Stellen (fix 3 48.137 11.576 519.3 12): auch dann 3 Stellen
            low_left = k == 0 or _bs_decimals(group[k - 1][2]) < 3
            low_right = k + 2 >= len(group) or _bs_decimals(group[k + 2][2]) < 3
            need = 3 if (len(group) <= 3 or marked or (low_left and low_right)) else 4
            if min(_bs_decimals(a[2]), _bs_decimals(b[2])) < need:
                continue
            try:
                x, y = float(a[2].replace(",", ".")), float(b[2].replace(",", "."))
            except ValueError:
                continue
            in_range = (abs(x) <= 90 and abs(y) <= 180) or (abs(y) <= 90 and abs(x) <= 180)
            if in_range and (abs(x) >= 1 or abs(y) >= 1):
                hits.append(line[a[0]:b[1]])
    return hits


_BS_ECEF_GAP = re.compile(r"(?i)\s*(?:c?m\b)?\s*[,;/ ]\s*(?:[\"']?(?:ecef[_-]?)?[yz][\"']?\s*[:=]\s*)?")


def _bs_ecef(line: str) -> list[str]:
    """Drei direkt aufeinanderfolgende große Zahlen mit Betrag ≈ Erdradius (m, cm oder mm)."""
    if not re.search(r"\d{4}", line):
        return []
    big = [m for m in re.finditer(r"(?<![\d.])[-+]?\d{4,10}(?:\.\d+)?(?![\d.])", line)]
    hits = []
    for a, b, c in zip(big, big[1:], big[2:]):
        if not (_BS_ECEF_GAP.fullmatch(line, a.end(), b.start()) and _BS_ECEF_GAP.fullmatch(line, b.end(), c.start())):
            continue
        try:
            r = (float(a.group(0)) ** 2 + float(b.group(0)) ** 2 + float(c.group(0)) ** 2) ** 0.5
        except ValueError:
            continue
        if any(6.30e6 <= r * scale <= 6.42e6 for scale in (1.0, 0.01, 0.001)):
            hits.append(line[a.start():c.end()])
    return hits


def _bs_e7(line: str) -> list[str]:
    hits = []
    for m in _BS_E7.finditer(line):
        x, y = int(m.group(1)) / 1e7, int(m.group(2)) / 1e7
        if ((abs(x) <= 90 and abs(y) <= 180) or (abs(y) <= 90 and abs(x) <= 180)) and (abs(x) >= 1 or abs(y) >= 1):
            hits.append(m.group(0))
    return hits


_BS_JSON_NUM = re.compile(r"(?<=[:\[,])(\"?)([-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)\1(?=[,\]\}])")
_BS_JSON_GAP = re.compile(r",(?:\"(?:[^\"\\]|\\.)*\":)?")


def _bs_json_pairs(line: str) -> list[str]:
    """Kompaktes JSON: benachbarte Zahlen in einem Objekt/einer Liste ({"x":11.57,"y":48.13}, [519.3,48.13,11.57])."""
    if not re.search(r"\d[.,]\d\d\d", line):
        return []
    nums = list(_BS_JSON_NUM.finditer(line))
    groups: list[list[re.Match]] = []
    for m in nums:
        if groups and _BS_JSON_GAP.fullmatch(line, groups[-1][-1].end(), m.start()):
            groups[-1].append(m)
        else:
            groups.append([m])
    hits = []
    for group in groups:
        texts = [m.group(2) for m in group]
        k = 0
        while k < len(texts) - 1:
            low_left = k == 0 or _bs_decimals(texts[k - 1]) < 3
            low_right = k + 2 >= len(texts) or _bs_decimals(texts[k + 2]) < 3
            need = 3 if (len(texts) <= 3 or (low_left and low_right)) else 4
            if '":' in line[group[k].end():group[k + 1].start()]:
                need += 1  # Werte eines Objekts – wie im Filter eine Stelle mehr
            a, b = texts[k], texts[k + 1]
            ok = False
            if "e" not in (a + b).lower() and min(_bs_decimals(a), _bs_decimals(b)) >= need:
                x, y = float(a.replace(",", ".")), float(b.replace(",", "."))
                ok = (((abs(x) <= 90 and abs(y) <= 180) or (abs(y) <= 90 and abs(x) <= 180))
                      and (abs(x) >= 1 or abs(y) >= 1))
            if ok:
                hits.append(line[group[k].start():group[k + 1].end()])
                k += 2
            else:
                k += 1
    return hits


def _bs_dotted_allowed(name: str, before: str = "") -> bool:
    n = name.lower().rstrip(".")
    if n in PUBLIC_TIME_HOSTS or n in HARMLESS_DOMAINS or n.endswith(PUBLIC_TIME_SUFFIXES):
        return True
    parts = n.split(".")
    last = parts[-1]
    if not last.isalpha() or len(last) < 2:
        return True  # Versionsnummern, IPs, "z.B" – keine Hostnamen
    if last in FILE_EXTENSIONS:
        return True
    if last in AMBIGUOUS_EXTENSIONS:
        return (before in ("/", "\\", "_") or (len(parts) >= 3 and parts[-2] in FILE_EXTENSIONS)
                or (len(parts) == 2 and ("_" in parts[0] or parts[0] in PROJECT_STEMS)))
    tail = name.rstrip(".").rsplit(".", 1)[-1]
    return len(tail) >= 4 and bool(re.search(r"[a-z][A-Z]", tail))


def _bs_segments(line: str) -> list[str]:
    """Zeile in Abschnitte an "\\n" (Zeilenumbruch in JSON-Text) – der Filter arbeitet je Textzeile."""
    return line.split("\\n") if "\\n" in line else [line]


def _bs_delay(line: str) -> list[str]:
    hits = [m.group(0) for m in _BS_DELAY.finditer(line)]
    for segment in _bs_segments(line):
        hits.extend(_bs_delay_units(segment))
    return hits


def _bs_delay_units(line: str) -> list[str]:
    hits = []
    if _BS_DELAY_CONTEXT.search(line):
        for m in _BS_DELAY_MS.finditer(line):
            if m.group(1) is None:
                hits.append(m.group(0))
                continue
            step = {"ms": 10, "us": 10_000, "µs": 10_000, "ns": 10_000_000}[m.group(2)]
            value = float(m.group(1))
            if value % step:
                hits.append(m.group(0))
    return hits


def _bs_known_res(known: dict | None) -> list[tuple[re.Pattern, str]]:
    known = known or {}
    out = []
    for value in known.get("names", []) or []:
        v = str(value).strip()
        if len(v) >= 3:
            out.append((re.compile(r"(?i)(?:(?<![\w.<-])|(?<=\\[nrt]))" + re.escape(v) + r"(?![\w>-]|\.[A-Za-z0-9])"),
                        "bekannter_name"))
    for value in known.get("tokens", []) or []:
        v = " ".join(str(value).split())
        if len(v) >= 3:
            body = r"\s+".join(re.escape(part) for part in v.split(" "))
            out.append((re.compile(r"(?i)(?:(?<![^\W_])|(?<=\\[nrt]))" + body + r"(?![^\W_])"), "bekannter_wert"))
    return out


def backstop_compact_json(bytes_by_file: dict) -> list[dict]:
    """Schlussprüfung für kompakt gerendertes JSON (eine Zeile je Abschnitt): nur Zahlenpaare in Listen
    und Objekten. Die übrigen Prüfungen sind zeilenweise gedacht und laufen auf der eingerückten Datei."""
    findings: list[dict] = []
    for filename, data in (bytes_by_file or {}).items():
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
        for hit in _bs_json_pairs(text):
            findings.append(_finding("koordinaten", filename, hit))
        for m in _BS_SAT_LIST.finditer(text):
            findings.append(_finding("satellitenliste", filename, m.group(0)))
    return findings


def backstop(bytes_by_file: dict, known: dict | None = None, memo: "BackstopMemo | None" = None) -> list[dict]:
    """Unabhängige Schlussprüfung auf den fertigen Bytes. Leere Liste = sauber.

    Sucht (ohne die Muster des Filters):
      * exakt alles, was die Konfiguration kennt (Hostnamen, Titel, Seriennummern, Interfaces);
      * jede für sich stehende Folge aus 12 Hex-Zeichen und jede MAC mit Trennern;
      * Zahlenpaare im Bereich ±90/±180 mit ≥ 3 Nachkommastellen dicht beieinander,
        NMEA-Koordinaten und ECEF-Tripel;
      * Werte hinter lat/lon/Breite/Länge/az/el …, Zonennamen (Europe/…), ungerundete
        chrony-Laufzeiten;
      * von chronyc gekürzte IPv6-Adressen ("2a01:4f8:…>");
      * jeden Namen mit Punkt, der nicht auf der Positivliste steht.

    memo: Zwischenspeicher für einen Exportlauf (gleiche Zeilen, gleiche bekannte Werte – die
    Funde einer Zeile hängen nur von ihr und von known ab). Passt known nicht, wird er nicht benutzt.
    """
    patterns = _bs_known_res(known)
    if memo is not None and memo.tag != _bs_known_tag(known):
        memo = None
    findings: list[dict] = []
    for filename, data in (bytes_by_file or {}).items():
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
        for number, line in enumerate(text.split("\n"), 1):
            hits = memo.get(line) if memo is not None else None
            if hits is None:
                hits = tuple(_bs_line(line, patterns))
                if memo is not None:
                    memo.put(line, hits, _tuple_bytes(hits))
            if hits:
                where = f"{filename}: Zeile {number}"
                findings.extend(_finding(kind, where, hit) for kind, hit in hits)
    return findings


def _bs_known_tag(known: dict | None) -> str:
    return json.dumps(known or {}, sort_keys=True, ensure_ascii=False, default=str)


class BackstopMemo(LineMemo):
    """Zwischenspeicher für backstop() innerhalb eines Exports (gleiche bekannte Werte)."""

    def __init__(self, known: dict | None, max_bytes: int = CHECK_CACHE_BYTES) -> None:
        super().__init__(max_bytes, PLAIN_CACHE_MAX_LINE)
        self.tag = _bs_known_tag(known)


def _bs_line(line: str, patterns: list[tuple[re.Pattern, str]]) -> list[tuple[str, str]]:
    """Funde einer Zeile als (Art, Text) – Text wie _finding auf 80 Zeichen gekürzt."""
    hits: list[tuple[str, str]] = []
    line = line.translate(_BS_DOTS)
    for pattern, kind in patterns:
        for m in pattern.finditer(line):
            hits.append((kind, m.group(0)))
    for m in _BS_HEX12.finditer(line):
        if m.group(1).lower() not in BACKSTOP_ALLOWED_HEX:
            hits.append(("hex12", m.group(0)))
    for m in _BS_MAC_SEP.finditer(line):
        digits = re.sub(r"[:-]", "", m.group(0))
        if not int(digits[:2], 16) & 1 and digits.strip("0"):
            hits.append(("mac", m.group(0)))
    for hit in _bs_float_pairs(line) + _bs_ecef(line) + _bs_e7(line) + _bs_json_pairs(line):
        hits.append(("koordinaten", hit))
    for m in _BS_HEXLONG.finditer(line):
        hits.append(("kennung", m.group(0)))
    for pattern, kind in ((_BS_DMS, "koordinaten"), (_BS_NMEA_SENTENCE, "koordinaten"),
                          (_BS_SAT_ROW, "satellitenwinkel"), (_BS_SAT_LIST, "satellitenliste"),
                          (_BS_SERIAL, "seriennummer"), (_BS_TOKEN, "zugangsdaten")):
        for m in pattern.finditer(line):
            hits.append((kind, m.group(0)))
    for hit in _bs_delay(line):
        hits.append(("laufzeit", hit))
    for segment in _bs_segments(line):
        dn_parts = _BS_DN_PART.findall(segment)
        if len(dn_parts) >= 2 and not any(ca in segment.lower() for ca in KNOWN_CAS):
            for m in _BS_DN_VALUE.finditer(segment):
                hits.append(("zertifikat", m.group(0)))
    for m in _BS_CLOCK_ID.finditer(line):
        if re.search(r"[1-9a-fA-F]", m.group(0)):
            hits.append(("uhr_id", m.group(0)))
    for m in _BS_REFID_LABEL.finditer(line):
        if not _refid_harmless(m.group(1)):
            hits.append(("refid", m.group(0)))
    for m in _BS_XY.finditer(line):
        x, y = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        if ((abs(x) <= 180 and abs(y) <= 90) or (abs(x) <= 90 and abs(y) <= 180)) and max(abs(x), abs(y)) >= 1:
            hits.append(("koordinaten", m.group(0)))
    m = _BS_CSV_REFID.match(line)
    if m and not _refid_harmless(m.group(1)):
        hits.append(("refid", m.group(0)))
    for m in _BS_IP_DASHED.finditer(line):
        octets = m.group(1).split("-")
        if all(int(o) <= 255 and (o == "0" or not o.startswith("0")) for o in octets):
            if _ip_kind(".".join(octets)) in ("public", "private"):
                hits.append(("ip", m.group(0)))
    for m in _BS_NMEA.finditer(line):
        hits.append(("koordinaten", m.group(0)))
    for pattern, kind in ((_BS_LABELLED, "koordinaten"), (_BS_ZONE, "zeitzone")):
        for m in pattern.finditer(line):
            hits.append((kind, m.group(0)))
    for m in _BS_TRUNC_V6.finditer(line):
        if m.group(0).count(":") >= 3:
            hits.append(("ipv6_gekuerzt", m.group(0)))
    for m in _BS_DOTTED.finditer(line):
        start = m.start()
        before = line[start - 1] if start else ""
        if before in "@-" and before or before.isalnum():
            continue
        if before == "." and start >= 2 and (line[start - 2].isalnum() or line[start - 2] in "-_"):
            continue
        if not _bs_dotted_allowed(m.group(0), before):
            hits.append(("name_mit_punkt", m.group(0)))
    return [(kind, text[:80]) for kind, text in hits]


# --- Benachrichtigungen (Zweck "notify") ---------------------------------------------

# Positivliste: Feld → Typ. Alles andere einer Meldung (Ereignisdaten mit Gerätepfaden,
# Quellen, Werten …) bleibt zu Hause. Texte laufen durch den Filter, danach beide Schranken.
NOTIFY_FIELDS: dict[str, type] = {
    "title": str, "text": str, "level": str, "kind": str, "time": float, "resolved": bool,
    "duration_s": int, "test": bool, "event_id": int, "suppressed": int,
}
NOTIFY_LEVELS = ("info", "warn", "crit")
NOTIFY_MAX_TEXT = 400
_NOTIFY_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class NotifyLeak(ValueError):
    """Die Schlussprüfung hat in einer Benachrichtigung etwas gefunden – nicht senden."""

    def __init__(self, findings: list[dict]) -> None:
        kinds = sorted({str(f.get("kind")) for f in findings})
        super().__init__("Filter hat die Nachricht zurückgehalten (" + ", ".join(kinds) + ")")
        self.findings = findings


def _written_pair_ok(a: str, b: str) -> bool:
    """Wie _coord_pair_ok, aber mit GESCHRIEBENEN Nachkommastellen (mindestens 2, Nullen am Ende zählen)."""
    x, y = _to_float(a), _to_float(b)
    if x is None or y is None or _decimals(a.lstrip("+-")) < 2 or _decimals(b.lstrip("+-")) < 2:
        return False
    if not ((-90 <= x <= 90 and -180 <= y <= 180) or (-90 <= y <= 90 and -180 <= x <= 180)):
        return False
    return abs(x) >= 1 or abs(y) >= 1


def notify_coord_spans(line: str) -> list[tuple[int, int]]:
    """Koordinatenpaare im kurzen Freitext einer Benachrichtigung – strenger als coord_pair_spans.

    Dort zählen signifikante Stellen (für Zahlenreihen aus chronyc gedacht), so dass „52.5200, 13.4050“
    (≈ 10 m genau geschrieben) als zwei Stellen durchginge. Ein Ereignistitel ist keine Messreihe: Hier
    reichen zwei geschriebene Nachkommastellen je Zahl (≈ 1 km) – ein falscher Treffer kostet nur eine Zahl."""
    tokens = [m for m in _COORD_TOKEN_RE.finditer(line) if m.group(2)]
    spans = []
    i = 0
    while i < len(tokens) - 1:
        a, b = tokens[i], tokens[i + 1]
        if _COORD_GAP_RE.fullmatch(line, a.end(), b.start()) and _written_pair_ok(a.group(2), b.group(2)):
            spans.append((a.start(), b.end()))
            i += 2
        else:
            i += 1
    return spans


def _notify_coords(text: str, sanitizer: "Sanitizer") -> str:
    spans = notify_coord_spans(text)
    if not spans:
        return text
    out, last = [], 0
    for start, end in spans:
        out.append(text[last:start])
        out.append("<koordinaten>")
        sanitizer.count("position")
        last = end
    out.append(text[last:])
    return "".join(out)


def notify_message(message: dict, known_names=(), known: dict | None = None) -> dict:
    """Meldung → was hinausgehen darf: nur NOTIFY_FIELDS, Texte gefiltert, Schranken geprüft.

    Wirft NotifyLeak, wenn check_no_leaks oder backstop danach noch etwas finden."""
    sanitizer = Sanitizer("notify", known_names, known)
    out: dict[str, Any] = {}
    for key, kind in NOTIFY_FIELDS.items():
        if key not in (message or {}):
            continue
        value = message[key]
        if value is None:
            continue
        if kind is str:
            text = " ".join(str(value).split())[:NOTIFY_MAX_TEXT]
            if key == "level":
                text = text if text in NOTIFY_LEVELS else "info"
            elif key == "kind":
                text = text if _NOTIFY_KIND_RE.match(text) else "other"
            else:
                text = _notify_coords(sanitizer.text(text), sanitizer)
            out[key] = text
        elif kind is bool:
            out[key] = bool(value)
        elif kind is int:
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                continue
        elif kind is float:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number == number and abs(number) < 1e12:
                out[key] = round(number, 3)
    findings = check_no_leaks(out)
    if not findings:
        rendered = json.dumps(out, ensure_ascii=False, indent=1)
        findings = backstop({"nachricht": rendered.encode("utf-8")}, sanitizer.backstop_known())
    if findings:
        raise NotifyLeak(findings)
    return out


# --- Benachrichtigung zu EINEM Gerät (1.5, Clients 3, Entscheidung F5) ----------------

# Platzhalter für das Gerät im Titel – Großbuchstaben ohne Hex-Muster, damit der Filter ihn stehen lässt.
DEVICE_PLACEHOLDER = "GERAETXPLATZHALTER"
DEVICE_UNNAMED = "Gerät ohne Namen"
# Nur diese Bereiche gelten als LAN-Adresse (wie clientinfo.LAN_NETWORKS): 6to4, Teredo und andere
# „nicht globale“ Sonderbereiche tragen öffentliche Adressen in sich und bleiben Pseudonym.
_LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
    "fc00::/7", "fe80::/10"))


def lan_address(text: Any) -> str | None:
    """Normalisierte private LAN-Adresse – oder None (öffentlich, Sonderbereich, keine IP)."""
    try:
        addr = ipaddress.ip_address(str(text or "").strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if any(addr.version == net.version and addr in net for net in _LAN_NETWORKS):
        return str(addr)
    return None


def notify_device_message(message: dict, known_names=(), known: dict | None = None,
                          device_name: str = "", lan_ip: str | None = None) -> dict:
    """Wie notify_message, aber für eine Meldung über EIN Gerät (Clients 3).

    Im Titel steht DEVICE_PLACEHOLDER statt der Adresse. Eingesetzt wird der eigene Name des Geräts –
    selbst gefiltert, nur ohne diesen einen Namen in der Namensliste (ein Name mit Hostname, öffentlicher
    IP oder dem Namen eines ANDEREN Geräts wird also trotzdem bereinigt) – sonst „Gerät ohne Namen“.
    Die LAN-Adresse nur, wenn lan_ip gesetzt ist (Schalter „LAN-Adressen in Nachrichten“) und wirklich
    privat ist. Die Schlussprüfung läuft über die fertige Meldung; nur die erlaubte Adresse wird dafür
    durch ein neutrales Wort ersetzt. Wirft NotifyLeak wie notify_message."""
    known = {k: list(v or ()) for k, v in (known or {}).items()}
    name = " ".join(str(device_name or "").split())[:64]
    if name:
        known["name"] = [n for n in known.get("name", []) if " ".join(str(n).split()).lower() != name.lower()]
    out = notify_message(message, known_names, known)
    label = ""
    if name:
        cleaner = Sanitizer("notify", known_names, known)
        label = " ".join(_notify_coords(cleaner.text(name), cleaner).split())
    allowed = lan_address(lan_ip) if lan_ip else None
    if label and allowed:
        text = f"{label} ({allowed})"
    else:
        text = label or allowed or DEVICE_UNNAMED
    for key in ("title", "text"):
        if isinstance(out.get(key), str) and DEVICE_PLACEHOLDER in out[key]:
            out[key] = out[key].replace(DEVICE_PLACEHOLDER, text)[:NOTIFY_MAX_TEXT]
    probe = {k: (v.replace(allowed, "LAN-Adresse") if allowed and isinstance(v, str) else v) for k, v in out.items()}
    findings = check_no_leaks(probe)
    if not findings:
        rendered = json.dumps(probe, ensure_ascii=False, indent=1)
        findings = backstop({"nachricht": rendered.encode("utf-8")}, Sanitizer("notify", known_names, known).backstop_known())
    if findings:
        raise NotifyLeak(findings)
    return out


# --- Update-Hinweis (Zweck "update_check") -------------------------------------------

# Die einzige Anfrage des Update-Hinweises: fest verdrahtet, ohne Daten der Instanz. Der
# User-Agent nennt bewusst weder Version noch Kennung – GitHub sieht so nur „irgendein
# ntp-gui“ und die öffentliche IP-Adresse (die lässt sich technisch nicht verbergen).
UPDATE_CHECK_URL = "https://api.github.com/repos/ConGp20/ntp-gui/releases/latest"
UPDATE_CHECK_HEADERS: dict[str, str] = {
    "User-Agent": "ntp-gui",
    "Accept": "application/vnd.github+json",
}


class UpdateCheckRejected(ValueError):
    """Die Update-Anfrage weicht von der festen Form ab – nicht senden."""


def _render_update_request(url: str, headers: dict) -> str:
    return "\n".join([url] + [f"{name}: {value}" for name, value in headers.items()])


def _update_findings(text: str) -> set:
    found = {(f["kind"], f["text"]) for f in check_no_leaks(text)}
    found |= {(f["kind"], f["text"]) for f in backstop({"update_check": text.encode("utf-8")})}
    return found


def update_check_request(url: str = UPDATE_CHECK_URL, headers: dict | None = None) -> tuple[str, dict]:
    """(URL, Kopfzeilen) für den Update-Hinweis – nur die feste Form geht hinaus.

    Wer später eine Version, eine Instanz-ID, einen Hostnamen, einen Ortsnamen oder einen
    anderen Host ergänzt, bekommt hier UpdateCheckRejected statt einer Anfrage: Kopfzeilen
    müssen exakt UPDATE_CHECK_HEADERS sein (Namen und Werte), nur die eine URL, keine
    Abfrageparameter. Zweite Schicht: check_no_leaks und backstop über die fertige Anfrage."""
    headers = dict(UPDATE_CHECK_HEADERS if headers is None else headers)
    if url != UPDATE_CHECK_URL:
        raise UpdateCheckRejected("Update-Hinweis: nur die feste GitHub-Adresse ist erlaubt")
    if set(headers) - set(UPDATE_CHECK_HEADERS):
        raise UpdateCheckRejected("Update-Hinweis: unbekannte Kopfzeile")
    if headers.get("User-Agent") != "ntp-gui":
        raise UpdateCheckRejected("Update-Hinweis: User-Agent muss „ntp-gui“ ohne Version sein")
    for name, value in headers.items():
        if value != UPDATE_CHECK_HEADERS[name]:
            raise UpdateCheckRejected("Update-Hinweis: Kopfzeile weicht vom festen Wert ab")
    # Was die zentralen Prüfungen schon in der festen Form melden („vnd.github“ sieht aus wie ein
    # Hostname), ist erlaubt – jeder weitere Fund stoppt die Anfrage (bei jedem Aufruf neu gerechnet,
    # damit eine geänderte Konfiguration den Vergleich nicht verschiebt).
    baseline = _update_findings(_render_update_request(UPDATE_CHECK_URL, UPDATE_CHECK_HEADERS))
    if _update_findings(_render_update_request(url, headers)) - baseline:
        raise UpdateCheckRejected("Update-Hinweis: die Filterprüfung findet Daten der Instanz")
    return url, headers
