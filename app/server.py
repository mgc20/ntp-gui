"""HTTP-Server für Dashboard und API – nur Python-Standardbibliothek.

Lesend: Status, Verlauf, Konfiguration, Geräte, Metriken.
Schreibend (POST): Einstellungen, Passwort, Neustart der Zeitdienste.
Versionierte API: /api/v1/<pfad> ist ein Alias der bisherigen Pfade (apiv1.py).

Schutz der schreibenden Routen:
  * ist ein Zugang gesetzt (Env oder Dashboard), gilt Basic-Auth für alles
    außer /healthz und /readyz – oder ein API-Schlüssel („Authorization: Bearer ntpg_…“)
    mit dem Recht, das apiv1.required_scope() für den Pfad verlangt;
  * ein mitgeschickter API-Schlüssel gilt immer mit seinem Recht, auch wenn
    kein Passwort gesetzt ist – ein „read“-Schlüssel kann nie schreiben;
  * WEB_READONLY=true sperrt alle Änderungen;
  * gegen Cross-Site-Requests (Browser mit Basic-Auth): nur JSON, Pflicht-Header
    X-NTP-GUI, und ein mitgeschickter Origin muss zum Host passen. Mit
    API-Schlüssel entfällt X-NTP-GUI – den Schlüssel schickt kein Browser von
    sich aus mit;
  * gegen DNS-Rebinding (eine fremde Webseite lässt ihren Namen auf die
    LAN-Adresse zeigen und liest dann Log, Status und Position): ohne Passwort
    werden nur Anfragen an IP-Adressen, localhost, den eigenen Hostnamen,
    lokale Namen (*.local, *.lan, *.home.arpa, *.internal …), den
    NTS-Namen, WEB_ALLOWED_HOSTS und die „Erlaubten Namen“ aus dem Dashboard
    beantwortet (host_allowed). Mit Passwort schützt die Anmeldung, dann gilt
    jeder Name. /healthz und /readyz sind immer offen (nur Wahrheitswerte);
  * clock_public: /clock, /api/v1/time und ihre vier statischen Dateien
    antworten ohne Anmeldung und für jeden Host-Namen – der Inhalt ist bewusst
    öffentlich (Uhrzeit, Ampel, Genauigkeit, Art der Quelle). Den Quellennamen
    gibt es nur angemeldet oder ohne Passwort über einen erlaubten Namen; über
    einen fremden Namen kommt immer die öffentliche Antwort.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import html
import ipaddress
import json
import math
import os
import re
import signal
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import allan
import apikeys
import authguard
import apiv1
import autocal
import backup
import gnssguard
import gpsquality
import holdover
import loopguard
import chrony
import clientinfo
import clockprofiles
import clocksignal
import clientmon
import clients3
import devices
import diagnostics
import dnsfwd
import egress
import enforce
import events
import gps
import hardware
import heartbeat
import history as historymod
import insights
import instance
import leap
import notify
import opsmetrics
import onboarding  # vor dem eigenen Code: merkt sich, ob das Datenverzeichnis schon Daten hatte
import providers
import ptp
import settings
import confgen
import statewatch
import pistate
import thermal
import timeline
import troubleshoot
import updatecheck
import webtransport

STATIC_DIR = Path(__file__).with_name("static")
CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")
RUN_DIR = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
START_MONO = time.monotonic()  # Laufzeit nach monotoner Uhr – ein Uhrsprung verfälscht sie nicht
MAX_BODY = 64 * 1024
VERSION = os.environ.get("NTPGUI_VERSION", "1.11.0")
EVENTS_INTERVAL = 5.0          # so oft liest der Server die Supervisor-Ereignisse ein
CALIBRATION_DEFAULT_WINDOW = 86400.0  # /api/gps/calibration ohne window: letzte 24 h
CALIBRATION_MAX_WINDOW = 7 * 86400.0  # … und höchstens 7 Tage (0 = „so viel wie möglich“ = 7 Tage)


def calibration_window(raw) -> float | None:
    """window/seconds aus der Anfrage → Sekunden (1 … 7 Tage); None bei Unsinn (NaN, negativ, kein Wert).
    1.5.4: window=0 hieß „gesamter Verlauf“ – über 30 Tage SQLite 14 s und 1 GB, alle 15 s."""
    if raw in (None, ""):
        return CALIBRATION_DEFAULT_WINDOW
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value < 0:
        return None
    if value == 0:
        return CALIBRATION_MAX_WINDOW  # ältere Dashboards: „gesamter Verlauf“
    return min(value, CALIBRATION_MAX_WINDOW)



def env_number(name: str, default, kind=float, minimum=None):
    """Zahl aus der Umgebung, die den Container nie abstürzen lässt.

    Ein Tippfehler in der Compose-Datei darf keine Neustartschleife auslösen:
    ein unbrauchbarer Wert fällt auf den Standard zurück.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = kind(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[web] {name}={raw!r} ist keine Zahl – verwende {default}", flush=True)
        return default
    if minimum is not None and value < minimum:
        print(f"[web] {name}={value} ist zu klein – verwende {minimum}", flush=True)
        return minimum
    return value


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 24 h bei 10 s Abstand. Komprimiert gesichert sind das wenige MB.
HISTORY_SIZE = env_number("HISTORY_SIZE", 8640, int, minimum=2)
HISTORY = historymod.History(HISTORY_SIZE, os.path.join(settings.DATA_DIR, "history.json.gz"))
# 1.5.4: Allan-Abweichung der Systemuhr aus der Frequenz im ganzen Verlauf, 10 min zwischengespeichert.
# Nur die letzten 30 Tage laden – bei großem HISTORY_DAYS sonst Speicher im GB-Bereich.
# Ohne die Holdover-Tests (Frequenz eingefroren, täuscht Stabilität vor).
ALLAN = allan.Cache(lambda: HISTORY.series("freq", since=time.time() - allan.MAX_SPAN),
                    exclude=lambda: holdover.TEST.freeze_intervals())

# 1.6 (T5): Vor jeder Sicherung den Verlauf und die Client-Messpunkte aus dem Speicher schreiben.
backup.add_flusher(lambda: HISTORY.save(force=True))
backup.add_flusher(lambda: clientmon._MONITOR.flush_samples(prune=False) if clientmon._MONITOR else None)
UPLOAD_READ_DEADLINE = 900.0  # Upload einer Sicherung (bis 200 MiB) – statt REQUEST_READ_DEADLINE

# Endpunkte von 1.3, die auch unter /api/v1 erreichbar sind (Recht je Endpunkt).
apiv1.endpoint("GET", "/logs", "/api/logs", "read",
               "Die letzten Zeilen des Container-Logs (lokal, ungefiltert).",
               ["available", "file", "total", "truncated", "lines"],
               {"lines": "Anzahl (1–5000, Standard 500)", "q": "Text, der vorkommen muss",
                "level": "warn oder crit: nur Warnungen/Fehler"})
apiv1.endpoint("GET", "/diagnostics/preview", "/api/diagnostics/preview", "read",
               "Vorschau des Diagnosepakets – genau das, was beim Herunterladen drinstünde, gefiltert.",
               ["ok", "generated", "filename", "sections", "removed", "content", "reuse"],
               {"clients": "1 = Client-Liste einschließen (pseudonymisiert)",
                "recording": "1 = letzte Aufzeichnung einschließen (gefiltert)",
                "async": "1 = im Hintergrund bauen: Antwort nach höchstens 10 s, fertig oder 202 mit job "
                         "(429, wenn schon zwei Bauten laufen)",
                "job": "Stand eines Auftrags abfragen (202 = läuft noch)"})
apiv1.endpoint("GET", "/diagnostics/bundle", "/api/diagnostics/bundle", "read",
               "Diagnosepaket als tar.gz (gefiltert, mit MANIFEST.txt). Wird nie hochgeladen.", [],
               {"clients": "wie bei der Vorschau", "recording": "wie bei der Vorschau",
                "reuse": "Merker „reuse“ einer Vorschau: genau dieses Paket sofort (gleiche Schalter und "
                         "Einstellungen, höchstens 10 min alt – auch wenn die Aufzeichnung gewachsen ist); "
                         "gilt er nicht mehr: 409. Ohne Merker wird neu gebaut."})
apiv1.endpoint("GET", "/backup", "/api/backup", "admin",
               "Sicherung als tar.gz: Einstellungen, Verlauf, Ereignisse, Clients mit Namen, Gruppen und "
               "Regeln, Kalibrierung, Kanäle – ohne Position, Passwort, Tokens und API-Schlüssel. Wird nie "
               "hochgeladen.", [],
               {"name": "statt einer neuen Sicherung eine gespeicherte aus /backup/list herunterladen"})
apiv1.endpoint("GET", "/backup/list", "/api/backup/list", "admin",
               "Im Datenverzeichnis gespeicherte Sicherungen (vor einer Wiederherstellung, nächtlich).",
               ["backups", "nightly"])
apiv1.endpoint("POST", "/restore/preview", "/api/restore/preview", "admin",
               "Sicherung hochladen (Body: die .tar.gz, Content-Type application/gzip, höchstens 200 MiB) und "
               "prüfen. Antwort: Vorschau und Merker „token“ (15 min gültig). Schreibt nichts.",
               ["token", "expires_in", "preview"])
apiv1.endpoint("POST", "/restore/apply", "/api/restore/apply", "admin",
               "Geprüfte Sicherung übernehmen ({\"token\": …}). Sichert vorher den jetzigen Stand ins "
               "Datenverzeichnis.", ["ok", "created", "rows", "before", "changed", "restart", "reenter"])
apiv1.endpoint("POST", "/restore/cancel", "/api/restore/cancel", "admin",
               "Hochgeladene Sicherung verwerfen ({\"token\": …}).", ["ok"])
apiv1.endpoint("GET", "/recording", "/api/recording", "read",
               "Zustand der Aufzeichnung der Datenquellen.", ["active", "ends", "entries", "size", "available"])
apiv1.endpoint("POST", "/recording", "/api/recording", "admin",
               "Aufzeichnung starten ({\"seconds\": 300}) oder beenden ({\"action\": \"stop\"}).",
               ["active", "ends", "entries", "size", "available"])
apiv1.endpoint("GET", "/enforce/snippets", "/api/enforce/snippets", "read",
               "Anleitungen, um Zeitserver per DNS oder Firewall auf diesen Server umzuleiten.",
               ["server_ip", "systems", "hostnames", "snippets"],
               {"system": "adguard, pihole, dnsmasq, unbound, opnsense, mikrotik, openwrt, nftables, unifi oder all",
                "ip": "Adresse dieses Servers aus Sicht der Clients",
                "dns_ip": "Adresse von AdGuard Home/Pi-hole für die optionale DNS-Umleitung per Firewall"})
apiv1.endpoint("GET", "/enforce/check", "/api/enforce/check", "read",
               "Prüft, ob die Umleitung wirkt (höchstens alle 30 s). „upstream“ zeigt für jede eigene Quelle die "
               "Kette Name → Resolver → Adresse → Antwort und erkennt Schleifen (DNS-Umschreibung, NAT-Umleitung).",
               ["level", "summary", "hosts", "public", "loops", "upstream", "resolver"],
               {"ip": "Adresse dieses Servers aus Sicht der Clients"})
apiv1.endpoint("GET", "/dns", "/api/dns", "read",
               "DNS für ntp-gui: eingestellter Modus, Zustand des Weiterleiters auf 127.0.0.1, eigene "
               "Server mit letzter Antwort bzw. letztem Fehler, Rückfall auf den System-DNS, resolv.conf. "
               "DoH-Adressen nur mit Servername (der Pfad kann eine Konto-Kennung enthalten).",
               ["mode", "effective_mode", "running", "state", "upstreams", "resolv", "stats", "last_success",
                "reachable", "upstream_count", "nts_note"])
apiv1.endpoint("GET", "/clients/offsets", "/api/clients/offsets", "read",
               "Passiv gemessene Abweichung der Client-Uhren, dazu eigene Namen der Geräte (names).",
               ["available", "running", "reason", "clients", "names"])
apiv1.endpoint("GET", "/clients/overview", "/api/clients/overview", "read",
               "Netzüberblick: Histogramm der Abweichungen, schlechteste Geräte, verstummte und "
               "auffällig oft fragende Geräte.",
               ["histogram", "measured", "unmeasurable", "total", "worst", "silent", "chatty"])
apiv1.endpoint("GET", "/clients/detail", "/api/clients/detail", "read",
               "Ein Client im Detail: Verlauf der Abweichung (7 Tage), Poll und Abstand, Zustand mit Grund, "
               "vermutete Software, Reverse-DNS, MAC/Hersteller (nur im selben Netz), eigener Name und Notiz.",
               ["address", "entry", "samples", "name", "note", "rdns", "mac", "software", "measurable_reason"],
               {"ip": "Adresse des Clients (Pflicht)", "range": "Zeitraum in Sekunden (Standard 7 Tage)"})
apiv1.endpoint("POST", "/clients/meta", "/api/clients/meta", "admin",
               "Eigenen Namen und Notiz eines Clients setzen. Body: {\"ip\": …, \"name\": …, \"note\": …} "
               "(weglassen = unverändert, \"\" = löschen). Bleibt lokal; beim Export pseudonymisiert.",
               ["ip", "name", "note"])
apiv1.endpoint("POST", "/clients/probe", "/api/clients/probe", "admin",
               "Aktiv nachmessen: eine NTP-Anfrage an einen bekannten Client im LAN (2 s Zeitlimit; je Gerät "
               "alle 30 s, insgesamt 10 pro Minute). Body: {\"ip\": …}.",
               ["ip", "answered", "offset", "rtt", "stratum", "text"])
apiv1.endpoint("GET", "/clients/troubleshoot", "/api/clients/troubleshoot", "read",
               "Fehlersuche „Mein Gerät bekommt keine Zeit“: feste Prüfliste für eine IP-Adresse (erlaubte Netze, "
               "lauscht der Dienst, Server synchron, Netzmodus, Anfragen gesehen, Begrenzung, Uhr des Geräts) und "
               "genau ein Befund mit nächstem Schritt. Rein lesend, keine Namensauflösung, keine Messung.",
               ["address", "lan", "known", "probe_allowed", "checks", "verdict"],
               {"ip": "IPv4- oder IPv6-Adresse des Geräts (Pflicht, kein Name)"})
apiv1.endpoint("GET", "/clients/groups", "/api/clients/groups", "read",
               "Clients 3: Geräte nach Gruppe (eigene Netze, spezifischstes Netz gewinnt), VLAN oder Software – je "
               "Gruppe Anzahl, aktive, messbare, Median-Abweichung, Anteil „gut“ (< 10 ms), Hinweis bei leerer Gruppe; "
               "bei by=group Vorschläge aus gesehenen /24- und /64-Netzen.",
               ["by", "groups", "total", "defined", "suggestions"], {"by": "group (Standard), vlan oder software"})
apiv1.endpoint("POST", "/clients/groups", "/api/clients/groups", "admin",
               "Gruppe anlegen (ohne id) oder ändern (mit id). Body: {\"name\": …, \"network\": \"10.0.30.0/24\"}.",
               ["id", "name", "network"])
apiv1.endpoint("POST", "/clients/groups/delete", "/api/clients/groups/delete", "admin",
               "Gruppe löschen. Body: {\"id\": …}.", ["ok"])
apiv1.endpoint("GET", "/clients/quality", "/api/clients/quality", "read",
               "Uhrgüte je Gerät (0–100 aus Abweichung, Stabilität, Regelmäßigkeit, Messbarkeit) und die "
               "schlechtesten Uhren im Haus.", ["scores", "worst", "rated", "total"])
apiv1.endpoint("GET", "/clients/rules", "/api/clients/rules", "read",
               "Regeln je Gerät: Stunden ohne Anfrage, eigene Schwelle (ms, Minuten), stumm, erwartete Software, "
               "dazu offene Alarme und der Lernstand von „neues Gerät“.", ["rules", "inventory"])
apiv1.endpoint("POST", "/clients/rules", "/api/clients/rules", "admin",
               "Regeln eines Geräts setzen. Body: {\"ip\": …, \"silent_h\": 6, \"offset_ms\": 500, "
               "\"offset_min\": 10, \"mute\": false, \"expect\": \"windows\"} (null/\"\" = aus).",
               ["ip", "silent_h", "offset_ms", "offset_min", "mute", "expect"])
apiv1.endpoint("GET", "/clients/pass", "/api/clients/pass", "read",
               "Gerätepass: alles Wichtige zu einem Gerät für die Druckseite (lokal). Mit share=1 nur eine "
               "gefilterte Textkopie zum Weitergeben (Adressen als Pseudonym, eigene Namen ersetzt, ohne Notiz).",
               ["address", "name", "group", "software", "entry", "week", "daily", "month", "quality", "nts",
                "recommendations"], {"ip": "Adresse des Clients (Pflicht)", "share": "1 = gefilterte Textkopie"})
apiv1.endpoint("GET", "/notify", "/api/notify", "admin",
               "Benachrichtigungen: Kanäle mit Filtern und Zustellstand. Tokens nur als „gesetzt“ "
               "(secret_set), nie im Klartext; Adressen mit Pfad/Abfrage nur gekürzt (url_hidden). heartbeat: "
               "Zustand des Zeitwächter-Pings (Adresse nur gekürzt).", ["channels", "types", "levels", "kinds",
                                                                       "defaults", "limits", "dashboard_url",
                                                                       "running", "heartbeat"])
apiv1.endpoint("GET", "/notify/status", "/api/notify/status", "read",
               "Zustellstand je Benachrichtigungskanal (Kennung, Art, zuletzt gesendet, letzter Fehler) – "
               "ohne Namen, Adressen und Tokens.", ["channels", "running"])
apiv1.endpoint("POST", "/notify/channels", "/api/notify/channels", "admin",
               "Benachrichtigungskanal anlegen (ohne id) oder ändern (mit id). Body: name, type "
               "(webhook|ntfy|gotify|apprise), url (beim Ändern weglassen = behalten), topic, secret "
               "(weglassen = behalten, nur bei gleichem Ziel und gleicher Art; \"\" = löschen), "
               "min_level, kinds, debounce_min, rate_per_hour, resolved, enabled.", ["channel"])
apiv1.endpoint("POST", "/notify/channels/delete", "/api/notify/channels/delete", "admin",
               "Benachrichtigungskanal löschen. Body: {\"id\": …}.", ["ok"])
apiv1.endpoint("POST", "/notify/test", "/api/notify/test", "admin",
               "Testnachricht sofort über einen Kanal senden (ohne Wiederholung). Body: {\"id\": …}.",
               ["ok", "error", "status"])
apiv1.endpoint("POST", "/notify/heartbeat/test", "/api/notify/heartbeat/test", "admin",
               "Zeitwächter-Ping sofort senden – mit dem echten Zustand (gut/kritisch, „kritisch“ erst nach "
               "2 min Haltezeit), höchstens alle 10 s. ok nur, wenn etwas angekommen ist; note, wenn bei "
               "„nur Lebenszeichen“ nichts gesendet wurde; 409, solange gerade ein Ping läuft. Body: {}.",
               ["ok", "error", "note", "heartbeat"])
apiv1.endpoint("GET", "/gps/autocal", "/api/gps/autocal", "read",
               "Automatische GPS-Kalibrierung: Modus, aktuelle Entscheidung, letzte Änderungen.",
               ["mode", "decision", "changes", "rollback"], {"fresh": "0 = letzte gespeicherte Entscheidung"})
apiv1.endpoint("POST", "/gps/autocal/rollback", "/api/gps/autocal/rollback", "admin",
               "Letzte automatische Änderung(en) zurücknehmen. Body: {\"steps\": 1}.",
               ["ok", "restored_offset", "restored_delay", "reload_triggered", "change"])

apiv1.endpoint("GET", "/loops", "/api/loops", "read",
               "Schleifen-Erkennung je Zeitquelle: Quellen, über die chronyd sich selbst fragt (DNS-Umschreibung "
               "oder NAT-Umleitung ohne Ausnahme für ntp-gui), mit Ursache, Belegen und Abhilfe. Geprüft im Takt "
               "des halben kleinsten Poll-Intervalls, bestätigt nach zwei Prüfungen.",
               ["loops", "checked", "interval_s", "confirm", "level"])
apiv1.endpoint("GET", "/gps/quality", "/api/gps/quality", "read",
               "GPS ohne PPS und schwacher Empfang: Empfangsbewertung über 24 h (Ampel, Satz, Gründe, Fix-Anteil, "
               "Fix-Wechsel je Stunde, Median-C/N0 der vier stärksten Satelliten, genutzte Satelliten), Zustand "
               "des Fix (stetig/unstet), Rolle des GPS (Rückfallebene, Referenz, nur beobachten) und die "
               "Fehlerschranke, die chrony für das GPS verwendet. Ohne Position und Satellitenwinkel.",
               ["enabled", "available", "assessment", "stability", "role", "bound"])
apiv1.endpoint("POST", "/gps/bound", "/api/gps/bound", "admin",
               "Gemessene Fehlerschranke des GPS auf den vorsichtigen Standard (± 100 ms) zurücksetzen. "
               "Body: {\"action\": \"reset\"}. Startet die Zeitdienste neu, Eintrag im Ereignisprotokoll.",
               ["ok", "reload_triggered", "delay"])
apiv1.endpoint("GET", "/gps/antenna", "/api/gps/antenna", "read",
               "Antennen-Test: laufende Messung, gespeicherte Messungen (Fix-Anteil, C/N0 der vier stärksten, "
               "Satelliten) und der Vergleich zweier Messungen. Bleibt lokal, ohne Satellitenwinkel.",
               ["test", "results", "comparison", "default_seconds"],
               {"a": "id der ersten Messung (Standard: vorletzte)", "b": "id der zweiten (Standard: letzte)"})
apiv1.endpoint("POST", "/gps/antenna", "/api/gps/antenna", "admin",
               "Antennen-Test steuern. Body: {\"action\": \"start\", \"label\": \"Fensterbank\", \"seconds\": 300} "
               "(60–900 s), {\"action\": \"stop\"} oder {\"action\": \"delete\", \"id\": …}.",
               ["test", "results", "comparison", "default_seconds"])

apiv1.endpoint("GET", "/gnss", "/api/gnss", "read",
               "GNSS-Störungserkennung: Stufe (ok, hinweis, warnung, stoerung), Signale (C/N0-Einbruch, gleichmäßige "
               "Signale, Falseticker, Zeitabweichung zu den NTS-Quellen, Positionssprung in Metern) und die GPS-Sperre. "
               "Ohne Koordinaten und Satellitenwinkel.",
               ["enabled", "mode", "stage", "stage_label", "signals", "time", "position", "cn0", "lock"])
apiv1.endpoint("POST", "/gnss", "/api/gnss", "admin",
               "GPS-Sperre von Hand: {\"action\": \"lock\"} bzw. {\"action\": \"unlock\"} (chronyc selectopts), "
               "{\"action\": \"relearn\"} lernt Referenzposition und Zeitabstand neu. Jede Aktion steht im "
               "Ereignisprotokoll.", ["stage", "lock"])
apiv1.endpoint("GET", "/holdover", "/api/holdover", "read",
               "Echter Holdover-Test: läuft einer (Fortschritt, Zeitfehler gegen die Messreferenzen), Vorprüfung "
               "und die letzten Ergebnisse („Die Uhr hält X ms in Y h“).",
               ["active", "run", "check", "results", "defaults"])
apiv1.endpoint("POST", "/holdover", "/api/holdover", "admin",
               "Holdover-Test starten oder abbrechen. Body: {\"action\": \"start\", \"hours\": 2, "
               "\"include_network\": true, \"limit_ms\": 10} (1–24 h, 1–1000 ms) oder {\"action\": \"abort\"}. "
               "Wählt die Quellen per chronyc selectopts ab und stellt sie danach automatisch zurück.",
               ["active", "run", "results"])

apiv1.endpoint("GET", "/temperature", "/api/temperature", "read",
               "Temperatur und Frequenz: gewählter Sensor, gefundene Sensoren, Paare (Zeit, °C, ppm) aus dem "
               "Verlauf und Kennzahlen (Dauer, Spanne, Korrelation). 1.4 misst nur – kein Temperaturausgleich.",
               ["available", "setting", "reason", "sensor", "celsius", "candidates", "pairs", "summary"],
               {"range": "Zeitraum in Sekunden (Standard 7 Tage, höchstens 30 Tage)",
                "points": "Höchstzahl der Paare, 100–3000 (Standard 1500)"})
apiv1.endpoint("GET", "/clockquality/allan", "/api/clockquality/allan", "read",
               "Allan-Abweichung (überlappend) der Systemuhr aus der Frequenz, die chrony im ganzen Verlauf "
               "für den Quarz gelernt hat: je τ (s, log-gestuft bis ¼ der Messdauer) Wert als Bruchteil "
               "(1e-9 = 1 ppb), 68-%-Bereich (lo, hi), unabhängige Paare n und „short“ (τ unter 15 min: zeigt "
               "vor allem chronys Nachführung). Dazu Einordnung (summary) und Datenbasis (tau0, span, "
               "coverage). 10 min zwischengespeichert.",
               ["available", "reason", "source", "unit", "tau0", "span", "samples", "coverage", "points",
                "summary", "short_tau", "resolution", "cached"])
apiv1.endpoint("GET", "/leap", "/api/leap", "read",
               "Schaltsekunden: TAI−UTC, letzte (und ggf. angekündigte) Schaltsekunde, Ablaufdatum und "
               "Prüfsumme der leap-seconds.list, Leap-Status von chrony.",
               ["available", "path", "tai_utc", "last_leap_date", "next_leap_date", "expires_date", "days_left",
                "expired", "hash_ok", "level", "reason", "chrony_leap"])
apiv1.endpoint("GET", "/time", None, "read",
               "Zeit für die Vollbild-Uhr (/clock): Empfangs- (t1) und Sendezeit (t2) des Servers in Unix-Sekunden "
               "für den Abgleich mit vier Zeitstempeln, dazu Synchronstatus, Genauigkeit, Art der Quelle und das "
               "Datum der nächsten angekündigten Schaltsekunde (leap_next, öffentlich aus der leap-seconds.list). "
               "Mit „Vollbild-Uhr ohne Anmeldung“ (clock_public) ohne Login und über jeden Host-Namen erreichbar – "
               "dann ohne Quellennamen. profiles_rev ändert sich, sobald ein Uhr-Profil gespeichert wird. "
               "ptp_state nennt nur den Zustand von PTP (off, down, master, locked, acquiring, passive, fault, "
               "unknown) – nie Grandmaster-Kennung oder Schnittstelle. holdover: Die Serveruhr läuft ohne "
               "Referenz weiter (true/false, null = unbekannt), holdover_seconds: seit wie vielen Sekunden. "
               "signal ist das On-Air/REC-Signal (off, on_air, rec – gesetzt über POST /api/v1/clock/signal), "
               "signal_rev ändert sich mit jedem Wechsel. tai_utc ist der heute gültige Abstand TAI−UTC in "
               "Sekunden (öffentlich aus der leap-seconds.list, null ohne lesbare Liste) – für die Nerd-Zeile.",
               ["t1", "t2", "synchronised", "level", "accuracy", "stratum", "leap", "leap_next", "tai_utc",
                "source_kind", "source", "public", "zone", "profiles_rev", "ptp_state", "holdover", "holdover_seconds",
                "signal", "signal_rev"])
apiv1.endpoint("GET", "/clock/profile", None, "read",
               "Ein Profil der Vollbild-Uhr (/clock?p=name): feste Voreinstellung oder im Dashboard gespeichert. "
               "Nur Anzeigewerte der Uhr (params, Zeichenketten wie in der Adresse) und Titel. Mit „Vollbild-Uhr "
               "ohne Anmeldung“ (clock_public) ohne Login lesbar, sonst mit Leserecht.",
               ["name", "title", "params", "builtin", "profiles_rev"],
               {"p": "Profilname, 1–32 Zeichen aus a–z, 0–9 und Bindestrich (ohne p: Namen der Voreinstellungen)"})

# 1.6 (T3): Willkommens-Assistent – Zustand, Prüfpunkte und Checkliste; Schreiben nur mit Verwaltungsrecht.
apiv1.endpoint("GET", "/setup", "/api/setup", "read",
               "Willkommens-Assistent: Erststart oder Update, ob die Einrichtung abgeschlossen ist, Prüfpunkte aus "
               "dem Hardware-Check (Volume, SYS_TIME, GPS, Pi-Zustand) je mit einer Abhilfe und die Checkliste der "
               "Übersicht. Liest nur.",
               ["install", "done", "auto_open", "hint", "readonly", "can_write", "checks", "checklist", "sources",
                "gps", "clients", "notify"])
apiv1.endpoint("POST", "/setup", "/api/setup", "admin",
               "Zustand des Assistenten ändern. Body: {\"action\": \"done\"} (Einrichtung abgeschlossen), \"never\" "
               "(abgeschlossen, auch die Checkliste nicht mehr zeigen), "
               "\"close_hint\" (Hinweis „Einrichtung prüfen“ schließen), \"close_checklist\" (Checkliste schließen) "
               "oder \"reset\" (wieder anzeigen). Ändert keine Einstellungen.",
               ["install", "done", "hint_closed", "checklist_closed"])

apiv1.endpoint("GET", "/update", "/api/update", "read",
               "Update-Hinweis (opt-in, Einstellung update_check): installierte und neueste Version auf GitHub, "
               "ob ein Update da ist, Markierung „Achtung beim Update“, Zeitpunkt der letzten und nächsten "
               "Prüfung. Ausgeschaltet ohne jede Anfrage nach außen.",
               ["enabled", "current", "current_valid", "latest", "available", "attention", "last_attempt",
                "last_success", "error", "next_check", "releases_url", "changelog_url", "automation"])

# Ohne Anmeldung erreichbar, wenn „Vollbild-Uhr ohne Anmeldung“ an ist: nur die Uhrseite, ihre
# statischen Dateien (kein Inhalt aus der Konfiguration) und /api/v1/time.
# 1.6 (T6): Designs, Ton und Sprache brauchen clockkit.js, util.js und i18n.js samt Sprachkatalogen –
# alles feste Texte und Code, nichts aus Konfiguration oder Status.
# Studiouhr A6: Profile lesen (/api/v1/clock/profile, nur Allowlist-Felder) und der Link-Baukasten (clocklink.js).
# Studiouhr B1: Rechnungen der Timecode-Anzeige (clocktc.js) – nur Code.
# Studiouhr C: Spielereien (clockextras.js: Eieruhr, Pomodoro, eingebaute Countdowns, Nachtmodus) – nur Code.
CLOCK_PUBLIC_PATHS = {"/clock", "/api/v1/time", "/api/v1/clock/profile", "/static/app.css", "/static/clock.css",
                      "/static/js/clock.js", "/static/js/clocksync.js", "/static/js/clockkit.js",
                      "/static/js/clockfaces.js", "/static/js/clockcount.js", "/static/js/clocklink.js",
                      "/static/js/clocktc.js", "/static/js/clockworld.js", "/static/js/clockextras.js",
                      "/static/js/util.js", "/static/js/i18n.js", "/static/i18n/de.json", "/static/i18n/en.json"}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",  # Sprachkataloge (static/i18n)
}


# ---------------------------------------------------------------------------
# Datensammlung
# ---------------------------------------------------------------------------

def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def collect_sample() -> dict:
    tracking = chrony.tracking()
    events.note_tracking(tracking)  # B4: Plausibilität fürs Aufräumen – außerhalb von events._LOCK
    stats = chrony.serverstats()
    sample: dict = {
        "t": int(time.time()),
        "offset": tracking.get("system_time_offset"),
        "rms": tracking.get("rms_offset"),
        "freq": tracking.get("frequency_ppm"),
        "skew": tracking.get("skew_ppm"),
        "root_delay": tracking.get("root_delay"),
        "root_dispersion": tracking.get("root_dispersion"),
        "stratum": tracking.get("stratum"),
        "served": stats.get("ntp_packets_received"),
        "clients": len(chrony.clients()),
        "sources": {},
    }
    for source in chrony.merged_sources():
        name = source.get("name")
        if name:
            sample["sources"][name] = {"o": source.get("offset"), "s": source.get("state"),
                                       "k": source.get("mode"), "j": source.get("std_dev")}
    try:
        temp = thermal.MONITOR.sample(settings.values().get("temp_sensor"))
    except Exception:  # Sensor weg – der Messpunkt entsteht trotzdem
        temp = None
    if temp is not None:
        sample["temp"] = temp
    # 1.6 (T4): Unterspannung/Drosselung am Pi – entprellte Ereignisse, ein Feld im Verlauf; wirft nie.
    pi_value = pistate.severity(pistate.MONITOR.sample(events.emit))
    if pi_value is not None:
        sample["pi_state"] = pi_value
    if gps.enabled():
        g = gps.status()
        sample["gps"] = {"used": _num(g.get("satellites_used")), "seen": _num(g.get("satellites_seen")),
                         "hdop": _num(g.get("hdop")), "snr": _num(g.get("snr_avg")),
                         "mode": _num(g.get("mode")), "cn4": _num(g.get("cn0_top4"))}
    if ptp.enabled():
        p = ptp.status()
        metrics = p.get("log_metrics") or {}
        sample["ptp"] = {
            "offset_ns": _num(p.get("offset_ns")),
            "delay_ns": _num(p.get("meanPathDelay")) or _num(metrics.get("path_delay_ns")),
            "freq_ppb": _num(metrics.get("freq_ppb")),
            "rms_ns": _num(metrics.get("rms_ns")),
        }
    return sample


# Erkennt Quellenwechsel, GPS-Fix verloren/wieder da und PPS-Ausfälle → Ereignisprotokoll.
# 1.5.4: Schwacher Empfang laut 24-h-Bewertung gilt gleich nach dem Start – keine Einzelmeldungen.
STATE_WATCH = statewatch.StateWatcher(events.emit, weak_reception=lambda: gpsquality.reception_weak(HISTORY))


def collector() -> None:
    restored = HISTORY.load()
    if restored:
        print(f"[web] Verlauf wiederhergestellt: {restored} Messpunkte", flush=True)
    while True:
        try:
            sample = collect_sample()
            HISTORY.add(sample)
            HISTORY.save()
            timeline.warm_report(HISTORY)  # Tagesbericht für gestern im Hintergrund, einmal am Tag; wirft nie
            STATE_WATCH.sample(sample)
            client_alarms()
            clients3.tick(settings.values(), events.emit)  # Regeln je Gerät, Inventar, Stundenwerte; wirft nie
            gpsquality.note_offset(settings.values())  # Offset-Änderung merken (Schranke, Kalibrierung)
            autocal.maybe_tick()   # höchstens einmal pro Stunde, wirft nie
            gpsquality.maybe_tick(settings.values)  # Fehlerschranke GPS ohne PPS, stündlich, wirft nie
        except Exception as exc:  # ein Messfehler darf den Thread nie beenden
            print(f"[web] Messung fehlgeschlagen: {exc}", flush=True)
        tracking, sources = None, None
        try:
            # Als PTP-Grandmaster die angekündigte Uhrqualität an den Zustand von chrony anpassen.
            tracking, sources = chrony.tracking(), chrony.detailed_sources()
            ptp.update_grandmaster(settings.values(), tracking, sources)
        except Exception as exc:
            print(f"[web] Grandmaster-Daten nicht gesetzt: {exc}", flush=True)
        note_clock_extra(tracking, sources)   # PTP-Zustand und Holdover für die Statuszeile von /clock; wirft nie
        try:
            interval = float(settings.values()["history_interval"])
        except Exception:
            interval = 10.0
        time.sleep(max(2.0, interval))


# 1.5: Schleifen-Erkennung je Quelle (DNS-Umschreibung / NAT-Umleitung ohne Ausnahme für ntp-gui).
LOOP_GUARD = loopguard.LoopGuard(events.emit, prober=enforce.probe_many, tracker=chrony.tracking)


def host_addresses() -> list[str]:
    """Eigene Adressen: alle Interfaces (/proc/net, je Namensraum) plus die Adressen des Hostnamens."""
    out: list[str] = loopguard.interface_addresses()
    try:
        for _family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
            if sockaddr[0] not in out:
                out.append(sockaddr[0])
    except (socket.gaierror, UnicodeError):
        pass
    return out


def loop_check() -> None:
    """Schleifen-Prüfung im Takt des halben kleinsten Poll-Intervalls (wirft nie)."""
    try:
        if not LOOP_GUARD.due():
            return
        cfg = settings.values()
        LOOP_GUARD.check(chrony.detailed_sources(), chrony.tracking(), host_addresses(), cfg.get("ntp_port", 123))
    except Exception as exc:  # die Prüfung darf die Messung nie aufhalten
        print(f"[web] Schleifen-Prüfung fehlgeschlagen: {exc}", flush=True)


def loop_guard_runner(stop: threading.Event | None = None) -> None:
    """Eigener Takt für die Schleifen-Prüfung (halbes kleinstes Poll-Intervall, 10–60 s) –
    unabhängig vom Verlaufs-Takt (history_interval bis 600 s), damit „≤ 2 Poll-Intervalle“ gilt."""
    stop = stop or threading.Event()
    while not stop.is_set():
        loop_check()
        stop.wait(min(loopguard.MAX_INTERVAL, max(1.0, LOOP_GUARD.seconds_until_due())))


CLIENT_ALARMS_KEY = "client_alarms"   # notify_meta: Adressen mit offenem Client-Alarm (überlebt Neustart)
_CLIENT_ALARMS: dict = {"loaded": False, "saved": None}


def _client_alarms_persist(restamp: bool = False) -> None:
    """Offene Client-Alarme sichern bzw. nach dem Start einmal übernehmen (notify_meta, mit Zeitstempel:
    nach mehr als notify.STATE_MAX_AGE ohne Dashboard gelten sie nicht mehr)."""
    saved = _CLIENT_ALARMS["saved"]
    if saved is None:
        saved = _CLIENT_ALARMS["saved"] = notify.SavedState(CLIENT_ALARMS_KEY)
    if not _CLIENT_ALARMS["loaded"]:
        _CLIENT_ALARMS["loaded"] = True
        try:
            STATE_WATCH.restore_client_alarms(saved.load() or [])
        except (ValueError, TypeError, RecursionError):
            pass
        return
    saved.save(STATE_WATCH.client_alarm_ips(), restamp=restamp)


def client_alarms() -> None:
    """Alarm-Schwelle für Client-Uhren (clients_alarm_ms) prüfen – Ereignis „clients“."""
    try:
        if not _CLIENT_ALARMS["loaded"]:
            _client_alarms_persist()
        threshold = settings.values().get("clients_alarm_ms") or 0
        if not threshold:
            STATE_WATCH.clients({}, 0)
            _client_alarms_persist()
            return
        # Titel nur mit der Adresse (egress pseudonymisiert sie): Ein eigener Name im gespeicherten
        # Titel bliebe nach Umbenennen/Löschen 90 Tage stehen und ginge dann ungefiltert hinaus.
        # Den Namen setzt erst die Anzeige ein (/api/events → display_title).
        # 1.5: Geräte mit eigener Schwelle prüft clients3 (Regeln je Gerät); stumme bleiben lokal.
        rule_map = clients3.rules()
        STATE_WATCH.clients(clients3.global_alarm_filter(clientmon.status()["clients"], rule_map), threshold,
                            fmt=clientinfo.fmt_offset,
                            data_for=lambda ip: {"notify": False} if (rule_map.get(ip) or {}).get("mute") else {},
                            handover=clients3.own_threshold_ips(rule_map))
        _client_alarms_persist()
    except Exception as exc:  # ein Alarm darf die Messung nie aufhalten
        print(f"[web] Alarm für Client-Uhren nicht geprüft: {exc}", flush=True)


LEAP_WATCH = leap.Watch(events.emit, lambda since: events.query(since=since, kinds=["leap"], limit=50))


def leap_check() -> None:
    """Ereignis leap/warn, wenn die Schaltsekunden-Liste bald abläuft (wirft nie)."""
    try:
        LEAP_WATCH.check(leap.status(settings.values()))
    except Exception as exc:
        print(f"[web] Schaltsekunden-Liste nicht geprüft: {exc}", flush=True)


HARDWARE_FIRST_DELAY = 5.0
HARDWARE_INTERVAL = 300.0


def hardware_refresher(stop: threading.Event | None = None) -> None:
    """Erzeugt den Hardware-Bericht im Hintergrund, damit Hinweise und Metriken
    Daten haben, ohne dass eine Anfrage auf die PPS-Probe (≈ 1 s) wartet."""
    stop = stop or threading.Event()
    if stop.wait(HARDWARE_FIRST_DELAY):
        return
    while True:
        try:
            STATE_WATCH.hardware(hardware.report(settings.values(), refresh=True))
        except Exception as exc:  # die Prüfung darf das Dashboard nie stören
            print(f"[web] Hardware-Prüfung fehlgeschlagen: {exc}", flush=True)
        leap_check()
        if stop.wait(HARDWARE_INTERVAL):
            return


def events_ingester(stop: threading.Event | None = None, interval: float = EVENTS_INTERVAL) -> None:
    """Übernimmt die Ereignisse des Supervisors (RUN_DIR/events.jsonl) und des DNS-Weiterleiters
    (events.jsonl in NTPGUI_REQUEST_DIR, wenn der ohne root läuft) ins Protokoll."""
    stop = stop or threading.Event()
    paths = [os.path.join(RUN_DIR, "events.jsonl")]
    request_dir = os.environ.get("NTPGUI_REQUEST_DIR")
    if request_dir and os.path.abspath(request_dir) != os.path.abspath(RUN_DIR):
        paths.append(os.path.join(request_dir, "events.jsonl"))
    while True:
        for path in paths:
            try:
                events.ingest_supervisor(path)
            except Exception as exc:  # nie den Thread verlieren
                print(f"[web] Ereignisse des Supervisors nicht gelesen: {exc}", flush=True)
        if stop.wait(interval):
            return


def recording_status() -> dict:
    """Zustand der Aufzeichnung für die Diagnose-Seite – ohne vollen Dateipfad."""
    raw = providers.status()
    out = {key: raw.get(key) for key in ("active", "until", "started", "bytes", "entries", "stopped",
                                         "reason", "max_seconds", "max_bytes", "replay")}
    path = raw.get("path")
    out["file"] = os.path.basename(path) if path else None
    out["available"] = bool(path and os.path.isfile(path))
    out["ends"] = raw.get("until")     # Namen, die pages/diagnose.js liest
    out["size"] = raw.get("bytes")
    return out


def clock_control() -> dict:
    """Läuft chronyd mit -x? Liest die Kommandozeile aus /proc."""
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm", encoding="utf-8") as handle:
                if handle.read().strip() != "chronyd":
                    continue
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                args = handle.read().split(b"\0")
        except OSError:
            continue
        return {"clock_control": b"-x" not in args, "chronyd_pid": int(entry)}
    return {"clock_control": None, "chronyd_pid": None}


_IANA_NAME = re.compile(r"^(UTC|[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){1,2})$")


def iana_timezone(env: dict | None = None, localtime: str = "/etc/localtime",
                  timezone_file: str = "/etc/timezone") -> str | None:
    """IANA-Name der Zeitzone des Servers: TZ-Variable, sonst /etc/timezone, sonst das Ziel des Links
    /etc/localtime (…/zoneinfo/Europe/Berlin). None, wenn nichts davon einen gültigen Namen liefert
    (POSIX-Angaben wie „CET-1CEST,M3.5.0,M10.5.0/3“ kennt Intl nicht)."""
    env = os.environ if env is None else env

    def ok(name: Any) -> str | None:
        name = str(name or "").strip().lstrip(":")
        if name.startswith("posix/") or name.startswith("right/"):
            name = name.split("/", 1)[1]
        return name if _IANA_NAME.match(name) and ".." not in name else None
    tz = env.get("TZ")
    if tz:
        tz = str(tz).lstrip(":")
        if "/zoneinfo/" in tz:
            tz = tz.split("/zoneinfo/", 1)[1]
        return ok(tz)
    try:
        with open(timezone_file, encoding="utf-8") as handle:
            name = ok(handle.readline())
        if name:
            return name
    except OSError:
        pass
    try:
        target = os.path.realpath(localtime)
    except OSError:
        return None
    if "/zoneinfo/" in target:
        return ok(target.split("/zoneinfo/", 1)[1])
    return None


def chrony_client_row(addr: str | None) -> dict | None:
    """Zeile aus „chronyc clients“ zu einer (bereinigten) Adresse – für Detailseite und Gerätepass."""
    if addr is None:
        return None
    return next((c for c in chrony.clients() if clientinfo.clean_ip(c.get("address")) == addr), None)


def troubleshoot_view(ip) -> dict:
    """Fehlersuche für eine Adresse: sammelt nur Lokales (chronyc, eigene Messung, /proc) – nichts geht ins Netz."""
    addr = troubleshoot.clean_target(ip)
    cfg = settings.values()
    rows = chrony.clients()
    row = next((c for c in rows if clientinfo.clean_ip(c.get("address")) == addr), None)
    mon = clientmon.status()
    others = [c.get("address") for c in rows if (c.get("ntp_packets") or 0) > 0] + list(mon.get("clients") or {})
    return troubleshoot.run(addr, cfg, tracking=chrony.tracking(), chrony_row=row, entry=clientmon.client(addr),
                            listeners=troubleshoot.udp_listeners(int(cfg["ntp_port"])),
                            net_mode=devices.network_mode(), gateway=clientmon.default_gateway(),
                            others=[a for a in others if a])


def system_info(cfg: dict) -> dict:
    info = {
        "hostname": socket.gethostname(),
        "time": time.time(),
        "timezone": time.strftime("%Z"),
        # Abstand zu UTC in Sekunden: Die Abkürzung oben („CEST“) kennt Intl im Browser nicht – damit
        # zeigt die Kopfzeile die Uhrzeit des Servers statt der des Browsers.
        "utc_offset": time.localtime().tm_gmtoff,
        # IANA-Name der Zeitzone („Europe/Berlin“), falls bekannt: Damit formatiert der Browser jedes
        # Ereignis sommerzeitrichtig; utc_offset gilt nur für jetzt und bleibt der Rückfall.
        "tz_name": iana_timezone(),
        "uptime_seconds": int(time.monotonic() - START_MONO),
        "title": cfg["web_title"],
        "refresh_seconds": cfg["web_refresh_seconds"],
        "ntp_port": cfg["ntp_port"],
        "version": VERSION,
        "addresses": [],
    }
    info.update(clock_control())
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            info["host_uptime_seconds"] = int(float(handle.read().split()[0]))
    except OSError:
        pass
    try:
        for _family, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
            if sockaddr[0] not in info["addresses"]:
                info["addresses"].append(sockaddr[0])
    except socket.gaierror:
        pass
    return info


def reload_status() -> dict:
    try:
        with open(os.path.join(RUN_DIR, "reload.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"state": "unknown"}


SERVICE_LABELS = {"chronyd": "chronyd (NTP)", "gpsd": "gpsd (GPS)", "ptp4l": "ptp4l (PTP)",
                  "phc2sys": "phc2sys (PTP-Uhr ↔ Systemuhr)", "dnsfwd": "dnsfwd (DNS für ntp-gui)",
                  "web": "Dashboard"}
SERVICE_STATES = {"running", "restarting", "failed", "stopped"}


def services_status() -> dict:
    """Zustand der Dienste aus RUN_DIR/services.json (schreibt der Supervisor).

    Fehlt die Datei oder ist sie kaputt (z. B. Dashboard ohne Supervisor
    gestartet), gibt es ein leeres Ergebnis – das Dashboard läuft trotzdem.
    """
    try:
        with open(os.path.join(RUN_DIR, "services.json"), encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    entries = raw.get("services") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        state = entry.get("state")
        restarts = entry.get("restarts")
        out[str(name)] = {
            "state": state if state in SERVICE_STATES else "unknown",
            "restarts": restarts if isinstance(restarts, int) and not isinstance(restarts, bool) else 0,
            "last_exit": entry.get("last_exit") if isinstance(entry.get("last_exit"), int) else None,
            "since": entry.get("since") if isinstance(entry.get("since"), (int, float)) else None,
            "pid": entry.get("pid") if isinstance(entry.get("pid"), int) else None,
            "optional": entry.get("optional") is True,
            # Soll laut Einstellungen laufen? Ältere services.json ohne das Feld: „stopped“ = absichtlich aus.
            "enabled": (entry["enabled"] if isinstance(entry.get("enabled"), bool)
                        else state in SERVICE_STATES and state != "stopped"),
            "next_retry": entry.get("next_retry") if isinstance(entry.get("next_retry"), (int, float)) else None,
            "message": str(entry.get("message") or ""),
            "label": SERVICE_LABELS.get(str(name), str(name)),
        }
    return out


# Hinweis-Schlüssel → Schlüssel, deren Anwesenheit ihn überflüssig macht (gleiche
# Ursache, schon ausführlicher gemeldet). Explizit statt Textvergleich.
INSIGHT_SUPPRESSED_BY = {
    # Läuft gpsd nicht, meldet "gpsd antwortet nicht" das Problem bereits; der
    # Hardware-Hinweis zum Empfänger wäre ein zweiter Eintrag für dieselbe Ursache.
    "hw_gps_usb": {"gpsd_down"},
}


def combine_insights(*lists: list[dict]) -> list[dict]:
    """Hinweislisten zusammenführen: doppelte Schlüssel und unterdrückte Hinweise
    (INSIGHT_SUPPRESSED_BY) entfernen, Reihenfolge beibehalten."""
    merged = [item for items in lists for item in items]
    keys = {item.get("key") for item in merged}
    out, seen = [], set()
    for item in merged:
        key = item.get("key")
        if (key is not None and key in seen) or INSIGHT_SUPPRESSED_BY.get(key, set()) & keys:
            continue
        seen.add(key)
        out.append(item)
    return out


def service_insights(services: dict, now: float | None = None) -> list[dict]:
    """Hinweise zu ausgefallenen Diensten (nur die optionalen startet der Supervisor neu)."""
    now = time.time() if now is None else now
    out: list[dict] = []
    for name, svc in services.items():
        label = svc.get("label") or name
        note = f" Letzte Meldung: {svc['message']}" if svc.get("message") else ""
        exit_text = f" (Exit-Code {svc['last_exit']})" if svc.get("last_exit") is not None else ""
        if name == "dnsfwd" and svc.get("state") in ("restarting", "failed"):
            out.append({
                "level": "warn", "key": f"service_{name}",
                "title": f"{label} ist ausgefallen" + (" und wird neu gestartet" if svc.get("state") == "restarting" else ""),
                "text": f"Der DNS-Weiterleiter hat sich beendet{exit_text}.{note} Bis er wieder läuft, zeigt "
                        "/etc/resolv.conf auf den ursprünglichen DNS des Containers – Namen lösen sich weiter "
                        "auf, aber ohne deine eigenen Server. Das Container-Log nennt den Grund (z. B. Port 53 "
                        "belegt).",
                "action": "settings",
            })
            continue
        if svc.get("state") == "restarting":
            attempt = (svc.get("restarts") or 0) + 1  # restarts = bisherige Neustarts, dieser ist der nächste
            retry = svc.get("next_retry")
            wait = f" Nächster Versuch in etwa {max(0, int(retry - now))} s." if isinstance(retry, (int, float)) else ""
            out.append({
                "level": "warn", "key": f"service_{name}",
                "title": f"{label} ist ausgefallen und wird neu gestartet (Versuch {attempt})",
                "text": f"Der Dienst hat sich beendet{exit_text}. Der Supervisor startet ihn mit wachsender "
                        "Pause neu, damit ein dauerhaft fehlendes Gerät nicht den Container blockiert – "
                        f"die übrigen Zeitdienste laufen weiter.{wait or note} Häufige Ursache: das Gerät "
                        "(GPS-Empfänger, Netzwerkkarte) ist abgesteckt oder im Container nicht freigegeben.",
                "action": "hardware",
            })
        elif svc.get("state") == "failed":
            out.append({
                "level": "crit", "key": f"service_{name}",
                "title": f"{label} läuft nicht",
                "text": f"Der Dienst ist eingeschaltet, läuft aber nicht{exit_text}.{note} Fehlt ein Gerät, "
                        "startet der Supervisor den Dienst von selbst, sobald es wieder auftaucht (Prüfung "
                        "alle 30 s). Prüfe auf der Hardware-Seite, ob das Gerät im Container sichtbar ist; "
                        "nach dem Speichern der Einstellungen startet der Supervisor die Dienste neu.",
                "action": "hardware",
            })
    return out


RELOAD_REQUEST = "reload.request"
RELOAD_CHRONYD_REQUEST = "reload-chronyd.request"


def trigger_reload() -> bool:
    """Bittet den Supervisor, die Zeitdienste neu zu starten: Anforderungsdatei in RUN_DIR, die
    seine Hauptschleife alle 2 s prüft.

    Früher per SIGHUP. Traf das Signal die bash genau beim Auswerten eines „$( … )“ (z. B. während
    ein Dienst gerade startete), verlor ihr Parser den Faden („trap: unexpected EOF while looking
    for matching `)'“) – und der Supervisor samt Container beendete sich. Eine Datei kann das nicht.
    """
    return _request_reload(RELOAD_REQUEST)


def trigger_reload_chronyd() -> bool:
    """Nur chronyd neu laden (Konfiguration neu erzeugen, nur chronyd neu starten): für Änderungen, die nur
    chrony.conf betreffen – die automatische GPS-Fehlerschranke und der automatisch kalibrierte Offset.
    gpsd, ptp4l, phc2sys und dnsfwd laufen weiter: Der GPS-Fix muss nicht neu einrasten, und der
    DNS-Weiterleiter meldet einen bekannten Ausfall nicht bei jeder Anpassung erneut."""
    return _request_reload(RELOAD_CHRONYD_REQUEST)


def _request_reload(name: str) -> bool:
    supervisor = os.path.join(RUN_DIR, "supervisor.pid")
    if not os.path.exists(supervisor):
        return False  # kein Supervisor (Entwicklung, Tests) – niemand würde die Datei lesen
    # Nur in das eigene Verzeichnis (NTPGUI_REQUEST_DIR): RUN_DIR gehört dem Supervisor (root).
    path = os.path.join(os.environ.get("NTPGUI_REQUEST_DIR") or RUN_DIR, name)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write(f"{time.time():.3f}\n")
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


MAX_PASSWORD_FILE = 4096


def env_credentials() -> dict:
    """Zugang aus der Umgebung: WEB_USER und WEB_PASSWORD bzw. WEB_PASSWORD_FILE (z. B. Docker Secret).

    Rückgabe: user, password (beide "" = nicht gesetzt), error (Text, wenn die Angaben unvollständig oder
    unlesbar sind – dann gilt fail-closed, siehe auth_info), defaulted_user (nur ein Passwort gesetzt:
    Benutzer „admin“), from_file.
    """
    user = os.environ.get("WEB_USER", "").strip()
    password = os.environ.get("WEB_PASSWORD", "")
    path = os.environ.get("WEB_PASSWORD_FILE", "").strip()
    out = {"user": "", "password": "", "error": None, "defaulted_user": False, "from_file": bool(path)}
    if path:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(MAX_PASSWORD_FILE + 1)
            if len(raw) > MAX_PASSWORD_FILE:
                raise ValueError("zu groß")
            password = raw.decode("utf-8").rstrip("\r\n")
        except (OSError, ValueError, UnicodeDecodeError):
            out["error"] = "WEB_PASSWORD_FILE ist gesetzt, die Datei aber nicht lesbar"
            return out
        if not password:
            out["error"] = "WEB_PASSWORD_FILE ist gesetzt, die Datei aber leer"
            return out
    if password and not user:
        user = "admin"
        out["defaulted_user"] = True
    if user and not password:
        out["error"] = "WEB_USER ist gesetzt, aber kein WEB_PASSWORD bzw. WEB_PASSWORD_FILE"
        return out
    weak = settings.password_weakness(password, user) if password and require_auth() else None
    if weak:
        # Mit WEB_REQUIRE_AUTH (VPS) gilt ein schwaches Passwort aus der Umgebung als nicht gesetzt – wie im
        # Dashboard, das solche Passwörter ablehnt. Ohne WEB_REQUIRE_AUTH bleibt es bei der Warnung.
        out["error"] = (f"Das Passwort aus der Umgebung ist zu schwach ({weak}) und gilt mit WEB_REQUIRE_AUTH=true "
                        f"nicht – mindestens {settings.RECOMMENDED_LENGTH} Zeichen, kein Beispielwert, nicht gleich "
                        "dem Benutzernamen")
        return out
    out["user"], out["password"] = user, password
    return out


def require_auth() -> bool:
    """WEB_REQUIRE_AUTH=true: ohne Zugang (Passwort) bleibt das Dashboard gesperrt (VPS-Betrieb)."""
    return env_flag("WEB_REQUIRE_AUTH")


def auth_info() -> dict:
    """Stand der Anmeldung: enabled, source ("env"|"gui"|None), user, locked (+ reason), weak (nur env).

    locked: kein Zugang gesetzt, aber einer verlangt (WEB_REQUIRE_AUTH) oder die Angaben aus der Umgebung
    sind unvollständig/unlesbar – dann ist das Dashboard gesperrt statt offen (fail-closed).
    """
    env = env_credentials()
    if env["user"] and env["password"]:
        # gui_overridden: Ein im Dashboard gesetztes Passwort gilt nicht, solange eines aus der Umgebung gesetzt
        # ist (ab 1.9 genügt dafür WEB_PASSWORD allein) – Start-Log und Einstellungsseite sagen es.
        return {"enabled": True, "source": "env", "user": env["user"], "locked": False,
                "weak": bool(settings.password_weakness(env["password"], env["user"])),
                "gui_overridden": bool(settings.stored_credentials())}
    broken = settings.load_error()
    if broken:
        # settings.json nicht lesbar: Ein dort gesetztes Passwort wäre still weg – gesperrt statt offen.
        return {"enabled": False, "source": None, "user": None, "locked": True, "reason": broken,
                "code": "settings_unreadable"}
    stored = settings.stored_credentials()
    if stored:
        return {"enabled": True, "source": "gui", "user": stored["user"], "locked": False}
    if env["error"]:
        return {"enabled": False, "source": None, "user": None, "locked": True, "reason": env["error"]}
    if require_auth():
        return {"enabled": False, "source": None, "user": None, "locked": True,
                "reason": "WEB_REQUIRE_AUTH=true ist gesetzt, aber noch kein Zugang"}
    return {"enabled": False, "source": None, "user": None, "locked": False}


def auth_public(info: dict, ident: dict | None) -> dict:
    """auth_info() für eine Antwort: den Benutzernamen nur für eine Anmeldung mit Benutzer/Passwort – ein
    API-Schlüssel (auch „read“) braucht ihn nicht. login: diese Anfrage kam mit Benutzer/Passwort."""
    kind = (ident or {}).get("kind")
    out = {k: v for k, v in info.items() if k != "user" or kind == "basic"}
    out["login"] = kind == "basic"
    return out


def build_status() -> dict:
    cfg = settings.values()
    tracking = chrony.tracking()
    clients = chrony.clients()
    status = {
        "system": system_info(cfg),
        "tracking": tracking,
        "sources": chrony.detailed_sources(),
        "activity": chrony.activity(),
        "serverstats": chrony.serverstats(),
        "clients": clients,
        "client_count": len(clients),
        "ptp": ptp.status(),
        "gps": gps.status(),
        "nts_server": chrony.nts_server_status(cfg),
        "services": services_status(),
        "dns": dnsfwd.api_status(cfg),
        "chrony_running": bool(tracking),
        "update": _update_status(),
        "config": {key: cfg[key] for key in (
            "gps_enable", "gps_device", "gps_offset", "gps_delay", "gps_select", "gps_refid", "gps_bound_mode",
            "gps_pps_device", "ptp_enable", "ptp_interface", "ptp_mode", "ptp_time_stamping",
            "ntp_minsources", "serve_unsynced", "allow_networks", "ntp_port", "phc2sys_enable",
            "phc_refclock")},
        "ui": {
            "readonly": env_flag("WEB_READONLY"),
            "auth": auth_public(auth_info(), None),  # Benutzername ergänzt der Handler nur für Basic
            "storage": settings.storage_info(),
            "reload": reload_status(),
            # 1.6 (T3): Assistent von selbst öffnen (Erststart) bzw. Hinweis „Einrichtung prüfen“ (Update).
            "setup": onboarding.brief(env_flag("WEB_READONLY")),
        },
    }
    # GPS-Seite: wirklich aktiver PPS-Refclock und der Delay, den chrony nutzt (gemessen/Standard).
    status["config"]["gps_bound"] = gpsquality.status_hint(cfg)
    # Übersicht: Rolle des GPS, Empfangsampel (24 h) und „unstet“ in einer Kurzfassung.
    try:
        status["gps_summary"] = gpsquality.overview(cfg, HISTORY, status["sources"], STATE_WATCH.gps_stability())
    except Exception:
        status["gps_summary"] = None
    leap_info = leap.status(cfg, tracking)
    status["leap"] = _leap_summary(leap_info)
    # 1.5.3: Einstellungsseite fragt nach, bevor Speichern chronyd neu startet (bräche den Test ab).
    try:
        status["holdover_active"] = holdover.TEST.running()
    except Exception:
        status["holdover_active"] = False
    status["notify"] = _notify_summary()
    status["heartbeat"] = _heartbeat_status()
    status["insights"] = combine_insights(insights.build(status, cfg),
                                          insights.exposure_insights(cfg, clients, clientmon.default_gateway(),
                                                                     devices.network_mode()),
                                          loopguard.insights(LOOP_GUARD.loops()),
                                          insights.dns_insights(status["dns"], cfg, status["sources"],
                                                                status["system"].get("addresses") or [],
                                                                enforce.last_loops(),
                                                                bool(cfg.get("enforce_hostnames"))
                                                                or enforce.check_ran()),
                                          service_insights(status["services"]),
                                          hardware.cached_insights(cfg),
                                          leap.insights(leap_info),
                                          updatecheck.insights(status["update"]),
                                          gpsquality.insights(status.get("gps_summary")),
                                          gnssguard.insights(gnssguard.GUARD.status(cfg)),
                                          holdover.insights(holdover.TEST.status()),
                                          webtransport.WATCH.insights(cfg.get("trusted_proxies")))
    global _last_insights
    _last_insights = (time.monotonic(), status["insights"])
    return status


# Diagnosepaket: die zuletzt angezeigten Hinweise (das Dashboard fragt den Status alle paar
# Sekunden ab). Ist die Liste älter, wird der Status einmal neu gebaut.
HINTS_MAX_AGE = 60.0
_last_insights: tuple[float, list] | None = None


def current_insights() -> list:
    cached = _last_insights
    if cached and time.monotonic() - cached[0] <= HINTS_MAX_AGE:
        return cached[1]
    return build_status()["insights"]


diagnostics.set_hints_source(current_insights)


def _leap_summary(info: dict) -> dict:
    """Kurzfassung der Schaltsekunden-Liste für die Übersicht (volle Angaben: /api/leap)."""
    return {key: info.get(key) for key in ("available", "source", "level", "reason", "days_left", "expired",
                                            "expires_date", "tai_utc")}


def _heartbeat_status(full: bool = False) -> dict:
    """Zeitwächter-Ping für Übersicht und Benachrichtigungsseite (wirft nie). Ohne full keine Adresse."""
    try:
        return heartbeat.status(full)
    except Exception:
        return {"enabled": False}


def heartbeat_state() -> str:
    """„down“, sobald die Übersicht einen kritischen Hinweis zeigt (wie die rote Ampel), sonst „up“."""
    items = current_insights()
    return "down" if any(isinstance(i, dict) and i.get("level") == "crit" for i in items or []) else "up"


def _notify_summary() -> dict:
    """Kanäle und Zustellstand für die Übersicht – nur Zähler, keine Namen, Adressen oder Tokens."""
    try:
        channels = notify.api_status().get("channels") or []
    except Exception:
        channels = []
    enabled = [c for c in channels if c.get("enabled")]
    failing = [c for c in enabled if (c.get("status") or {}).get("state") == "error"]
    return {"channels": len(channels), "enabled": len(enabled), "failing": len(failing)}


def setup_payload(readonly: bool, can_write: bool) -> dict:
    """GET /api/setup (1.6, T3): Prüfpunkte aus dem Hardware-Check (zwischengespeichert, 30 s) und Checkliste."""
    cfg = settings.values()
    try:
        report = hardware.report(cfg)
    except Exception:  # der Assistent darf am Hardware-Check nie scheitern
        report = None
    try:
        channels = len(notify.list_channels())
    except Exception:
        channels = 0
    return onboarding.summary(cfg, report, settings.storage_info(), chrony.tracking(), len(chrony.clients()),
                              channels, readonly, can_write)


def _update_status() -> dict:
    """Update-Hinweis (wirft nie; ausgeschaltet nur {"enabled": False, …} ohne Netz)."""
    try:
        return updatecheck.checker(VERSION).status()
    except Exception:
        return {"enabled": False, "available": False}


# ---------------------------------------------------------------------------
# Vollbild-Uhr und Temperatur
# ---------------------------------------------------------------------------

# Refids, die als Art der Quelle öffentlich gezeigt werden dürfen (eigene Refids sind Einstellungen).
KNOWN_REFIDS = {"GPS": "GPS", "PPS": "GPS + PPS", "NMEA": "GPS", "GNSS": "GNSS", "PHC": "PTP", "PTP": "PTP",
                "SHM0": "GPS", "SHM1": "GPS + PPS", "DCF": "DCF77"}
# chrony vergibt ohne „refid“ den Treibernamen plus Nummer (PHC0, PHC1 …) – so schreibt confgen den PHC-Refclock.
_DRIVER_REFID = re.compile(r"^(PHC|SHM|PPS|SOCK)(\d+)$")
_DRIVER_KIND = {"PHC": "PTP", "SHM": "GPS", "PPS": "GPS + PPS", "SOCK": "GPS"}


def source_kind(ref: str, cfg: dict | None = None) -> str:
    """Art einer Stratum-1-Quelle aus ihrer Refid – nie die Refid selbst (eigene Namen sind Einstellungen)."""
    ref = str(ref or "").strip().upper()
    if ref in KNOWN_REFIDS:
        return KNOWN_REFIDS[ref]
    match = _DRIVER_REFID.match(ref)
    if match:
        return _DRIVER_KIND[match.group(1)]
    gps_refid = str((cfg or {}).get("gps_refid") or "").strip().upper()
    if gps_refid and ref == gps_refid:
        return "GPS"   # confgen: refclock SHM … refid <gps_refid>; PPS hat immer die Refid „PPS“
    return "Referenzuhr"


# Studiouhr B3: Zustand von PTP als fester Wert. Aus dem Status von ptp4l wird nur der Zustand des Ports gelesen –
# Kennungen (Grandmaster, Uhr, Port), Schnittstelle und Domäne kommen hier nie vor.
PTP_STATES = ("off", "down", "master", "locked", "acquiring", "passive", "fault", "unknown")
_PTP_PORT_STATES = {"SLAVE": "locked", "MASTER": "master", "GRAND_MASTER": "master", "LISTENING": "acquiring",
                    "UNCALIBRATED": "acquiring", "PRE_MASTER": "acquiring", "INITIALIZING": "acquiring",
                    "PASSIVE": "passive", "FAULTY": "fault", "DISABLED": "fault"}
HOLDOVER_REF_MAX = 366 * 86400.0   # ältere „letzte Korrektur“ ist keine Angabe (Uhr stand beim Start auf 1970)
CLOCK_EXTRA_MAX_AGE = 300.0        # so alt darf die letzte Beobachtung des Messthreads sein, sonst „unbekannt“
# t: letzte Beobachtung (PTP), lost_t: letzte Beobachtung mit einer Aussage zum Holdover (lost, since).
_CLOCK_EXTRA: dict = {"t": None, "ptp_state": "unknown", "lost": None, "since": None, "lost_t": None}
_CLOCK_EXTRA_LOCK = threading.Lock()


def ptp_state(status) -> str:
    """Zustand von PTP für /clock: einer der Werte aus PTP_STATES, sonst nichts aus ptp.status()."""
    if not isinstance(status, dict):
        return "unknown"
    if not status.get("enabled"):
        return "off"
    if not status.get("running"):
        return "down"
    port = status.get("portState")
    return _PTP_PORT_STATES.get(port, "unknown") if isinstance(port, str) else "unknown"


def reference_lost(tracking, sources, test_active: bool = False, was_lost: bool = False) -> bool | None:
    """Läuft die Serveruhr ohne Referenz weiter (Holdover)? chronyd läuft, aber: der Holdover-Test hat die Quellen
    abgewählt, chrony gibt nur noch die eigene Uhr weiter (Inselbetrieb), oder es nennt zwar noch eine Referenz,
    hat aber keine Quelle mehr ausgewählt. None: keine Aussage – chronyc antwortete nicht (kein tracking, keine
    Quellenliste). was_lost: Zuletzt lief ein Holdover. Er endet erst, wenn wieder eine Quelle ausgewählt ist –
    auch wenn chrony die Referenz inzwischen ganz aufgegeben hat („nicht synchronisiert“). Ohne vorherigen
    Holdover ist „nicht synchronisiert“ keiner: Die Uhr war seit dem Start nie abgeglichen."""
    if not isinstance(tracking, dict) or not tracking:
        return None
    if test_active or tracking.get("local_reference"):
        return True
    if not isinstance(sources, (list, tuple)) or not sources:
        return None
    if any(isinstance(src, dict) and src.get("state") == "*" for src in sources):
        return False
    return bool(tracking.get("synchronised")) or bool(was_lost)


def note_clock_extra(tracking, sources, mono: float | None = None, wall: float | None = None) -> None:
    """Beobachtung des Messthreads merken: Zustand von PTP und Beginn des Holdovers. /api/v1/time liest nur diesen
    Stand (clock_extra) und startet dafür selbst keinen Prozess. Der Beginn ist die letzte Korrektur der Uhr
    (ref_time), solange chrony sie noch nennt, sonst der Moment der ersten Beobachtung. Wirft nie."""
    try:
        mono = time.monotonic() if mono is None else mono
        wall = time.time() if wall is None else wall
        try:
            state = ptp_state(ptp.status())
        except Exception:
            state = "unknown"
        try:
            test_active = holdover.TEST.running()
        except Exception:
            test_active = False
        with _CLOCK_EXTRA_LOCK:
            lost = reference_lost(tracking, sources, test_active, was_lost=_CLOCK_EXTRA["lost"] is True)
            _CLOCK_EXTRA.update(t=mono, ptp_state=state)
            if lost is None:
                return   # keine Aussage: Der letzte Stand bleibt (samt Beginn) und altert über lost_t
            since = _CLOCK_EXTRA["since"] if lost else None
            if lost and since is None:
                ref = tracking.get("ref_time")
                age = wall - ref if _num(ref) is not None and tracking.get("synchronised") else 0.0
                since = mono - (age if 0.0 < age < HOLDOVER_REF_MAX else 0.0)
            _CLOCK_EXTRA.update(lost=lost, since=since, lost_t=mono)
    except Exception as exc:
        print(f"[web] Zustand für die Uhr nicht bestimmt: {exc}", flush=True)


def clock_extra(mono: float | None = None, interval=None) -> dict:
    """Letzter Stand aus note_clock_extra: {"ptp_state", "holdover", "holdover_seconds"}; zu alt oder nie
    beobachtet: unbekannt. Antwortet chronyc einzelne Male nicht, gilt beim Holdover der letzte Stand weiter, bis
    auch er zu alt ist. Ist PTP ausgeschaltet, steht das sofort da (nur eine Einstellung, kein Prozess).
    interval: Messintervall (history_interval) – bei langen Intervallen gilt der Stand drei Messungen lang."""
    mono = time.monotonic() if mono is None else mono
    with _CLOCK_EXTRA_LOCK:
        seen = dict(_CLOCK_EXTRA)
    max_age = max(CLOCK_EXTRA_MAX_AGE, 3.0 * interval) if _num(interval) is not None and 0 < interval <= 3600 else CLOCK_EXTRA_MAX_AGE
    fresh = seen["t"] is not None and 0.0 <= mono - seen["t"] <= max_age
    out = {"ptp_state": seen["ptp_state"] if fresh else "unknown", "holdover": None, "holdover_seconds": None}
    try:
        if not ptp.enabled():
            out["ptp_state"] = "off"
    except Exception:
        pass
    known = seen["lost_t"] is not None and 0.0 <= mono - seen["lost_t"] <= max_age
    if known and isinstance(seen["lost"], bool):
        out["holdover"] = seen["lost"]
        if seen["lost"] and seen["since"] is not None:
            out["holdover_seconds"] = max(0, int(mono - seen["since"]))
    return out


def clock_status(tracking: dict, cfg: dict | None = None, extra: dict | None = None) -> dict:
    """Ampel und Quelle für /clock – ohne Namen, Adressen oder Einstellungen. extra (clock_extra): Zustand von PTP
    und Holdover; übernommen werden nur feste Werte, Wahrheitswert und Sekunden."""
    running = bool(tracking)
    synced = bool(tracking.get("synchronised"))
    delay, disp = tracking.get("root_delay"), tracking.get("root_dispersion")
    accuracy = None
    if isinstance(delay, (int, float)) and isinstance(disp, (int, float)):
        offset = tracking.get("system_time_offset")
        accuracy = abs(delay) / 2 + abs(disp) + (abs(offset) if isinstance(offset, (int, float)) else 0.0)
    stratum = tracking.get("stratum") if isinstance(tracking.get("stratum"), int) else None
    if not running:
        kind, level = None, "crit"
    elif tracking.get("local_reference"):
        kind, level = "lokal (Inselbetrieb)", "warn"
    elif not synced:
        kind, level = None, "warn"
    else:
        kind = source_kind(tracking.get("ref_name"), cfg) if stratum == 1 else "NTP"
        level = "good" if accuracy is None or accuracy < 0.1 else "warn"
    extra = extra if isinstance(extra, dict) else {}
    state = extra.get("ptp_state")
    hold = extra.get("holdover") if running and isinstance(extra.get("holdover"), bool) else None
    seconds = extra.get("holdover_seconds")
    seconds = int(seconds) if hold and _num(seconds) is not None and 0 <= seconds < 1e9 else None
    return {"synchronised": synced, "running": running, "level": level, "accuracy": accuracy,
            "stratum": stratum, "leap": tracking.get("leap_status") or None, "source_kind": kind,
            "ptp_state": state if isinstance(state, str) and state in PTP_STATES else "unknown",
            "holdover": hold, "holdover_seconds": seconds}


CLOCK_CACHE_SECONDS = 1.0
_CLOCK_CACHE: dict = {"t": None, "tracking": None}
_CLOCK_CACHE_LOCK = threading.Lock()


def _clock_tracking() -> dict:
    """chronyc tracking für /api/v1/time, höchstens einmal je Sekunde.

    Viele Wanduhren (je 5 Anfragen pro Abgleich plus Status alle 5 s) und – mit
    clock_public – Anfragen ohne Anmeldung sollen nicht je einen chronyc-Prozess
    starten. t1/t2 bleiben pro Anfrage; nur der Status ist bis zu 1 s alt.
    """
    with _CLOCK_CACHE_LOCK:
        now = time.monotonic()
        if _CLOCK_CACHE["t"] is not None and now - _CLOCK_CACHE["t"] < CLOCK_CACHE_SECONDS:
            return _CLOCK_CACHE["tracking"]
        tracking = chrony.tracking()
        _CLOCK_CACHE.update(t=time.monotonic(), tracking=tracking)
        return tracking


_HEALTHZ_CACHE: dict = {"t": None, "tracking": None}
_HEALTHZ_LOCK = threading.Lock()


def _healthz_tracking() -> dict:
    """chronyc tracking für /healthz, höchstens einmal je HEALTHZ_CACHE_SECONDS.

    /healthz ist auch ohne Anmeldung erreichbar – viele Anfragen sollen nicht je einen chronyc-Prozess starten.
    Wer gleichzeitig fragt, wartet auf dieselbe Abfrage (Sperre), statt eine eigene zu starten.
    """
    with _HEALTHZ_LOCK:
        now = time.monotonic()
        if _HEALTHZ_CACHE["t"] is not None and now - _HEALTHZ_CACHE["t"] < HEALTHZ_CACHE_SECONDS:
            return _HEALTHZ_CACHE["tracking"]
        tracking = chrony.tracking()
        _HEALTHZ_CACHE.update(t=time.monotonic(), tracking=tracking)
        return tracking


READY_MAX_ERROR_DEFAULT_MS = 100.0


def ready_limit_ms() -> float:
    """Grenze der Fehlerschranke für /readyz in Millisekunden (Einstellung ready_max_error_ms bzw.
    READY_MAX_ERROR_MS). Sind die Einstellungen nicht lesbar, gilt die Umgebungsvariable oder der Standard –
    /readyz darf daran nie scheitern."""
    try:
        value = settings.values().get("ready_max_error_ms")
    except Exception:
        value = settings.env_number("READY_MAX_ERROR_MS", READY_MAX_ERROR_DEFAULT_MS, 0.001, 10000.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 10000:
        return READY_MAX_ERROR_DEFAULT_MS
    return float(value)


def readiness(tracking: dict, limit_ms: float, holdover: bool | None = None) -> dict:
    """Strenge Bereitschaft für /readyz: bereit nur, wenn chronyd antwortet, synchronisiert ist (kein
    Inselbetrieb, Stratum unter 16), gerade eine Quelle ausgewählt hat (kein Holdover, kein Holdover-Test) und
    die Fehlerschranke (|Offset| + Root-Dispersion + Root-Delay/2, wie chrony sie rechnet) unter der Grenze
    liegt. Fehlt einer der drei Werte oder ist er nicht lesbar, ist der Server nicht bereit.
    holdover: aus ready_holdover() – True: keine Quelle ausgewählt; None: keine Aussage, zählt nicht dagegen.
    Die Antwort enthält nur Wahrheitswerte – keine Zahlen, keine Quellen, keine Grenze."""
    running = bool(tracking)
    synced = bool(running and tracking.get("synchronised"))
    selected = synced and holdover is not True
    within = False
    if synced:
        try:
            parts = [float(tracking[key]) for key in ("system_time_offset", "root_dispersion", "root_delay")]
            error = abs(parts[0]) + abs(parts[1]) + abs(parts[2]) / 2
            within = math.isfinite(error) and error * 1000.0 < limit_ms
        except (KeyError, TypeError, ValueError):
            within = False
    ready = running and synced and selected and within
    return {"status": "ready" if ready else "not_ready", "chrony": running,
            "synchronised": synced, "source_selected": selected, "within_limit": within}


def ready_holdover() -> bool | None:
    """Holdover für /readyz: True, solange ein Holdover-Test läuft oder der Messthread zuletzt gesehen hat, dass
    chrony keine Quelle mehr ausgewählt hat (clock_extra); None ohne frische Aussage. Startet keinen Prozess und
    wirft nie."""
    try:
        if holdover.TEST.running():
            return True
    except Exception:
        pass
    try:
        try:
            interval = settings.values().get("history_interval")
        except Exception:
            interval = None
        value = clock_extra(interval=interval).get("holdover")
    except Exception:
        return None
    return value if isinstance(value, bool) else None


def _clock_leap(cfg: dict) -> dict:
    """Schaltsekunden-Angaben für /clock: {"leap_next", "tai_utc"} – öffentliche Information aus der
    leap-seconds.list (IERS Bulletin C), kein Pfad, keine Einstellung. Nie ein Fehler: im Zweifel None.

    leap_next: Datum der nächsten angekündigten Schaltsekunde (Beginn des neuen TAI−UTC, „2017-01-01“) – die Uhr
    zeigt damit am 30.6./31.12. ein kleines Banner. tai_utc: der heute gültige Abstand TAI−UTC in ganzen Sekunden
    (10 … 100) – die Nerd-Zeile rechnet damit TAI und GPS-Zeit, statt ihn fest einzubauen.
    """
    out = {"leap_next": None, "tai_utc": None}
    try:
        info = leap.status(cfg)
    except Exception:
        return out
    if not info.get("available"):
        return out
    value = info.get("next_leap_date")
    if isinstance(value, str) and len(value) == 10:
        out["leap_next"] = value
    tai = info.get("tai_utc")
    if isinstance(tai, int) and not isinstance(tai, bool) and 10 <= tai <= 100:
        out["tai_utc"] = tai
    return out


def _clock_leap_next(cfg: dict) -> str | None:
    """Datum der nächsten angekündigten Schaltsekunde für /clock (siehe _clock_leap)."""
    return _clock_leap(cfg)["leap_next"]


def _clock_tai_utc(cfg: dict) -> int | None:
    """TAI−UTC in Sekunden für /clock (siehe _clock_leap)."""
    return _clock_leap(cfg)["tai_utc"]


_CLOCK_ZONE: dict = {"t": None, "zone": None}


def _clock_zone() -> str | None:
    """IANA-Name der Zeitzone des Servers für /clock (höchstens einmal je Minute gelesen).

    Countdown-Ziele wie ?until=20:15 gelten in dieser Zone – so zeigen alle Bildschirme dasselbe Ziel, egal welche
    Zeitzone das Anzeigegerät hat. Nur ein Name wie „Europe/Berlin“ oder None, nie ein Pfad.
    """
    with _CLOCK_CACHE_LOCK:
        now = time.monotonic()
        if _CLOCK_ZONE["t"] is None or now - _CLOCK_ZONE["t"] >= 60.0:
            _CLOCK_ZONE.update(t=now, zone=iana_timezone())
        return _CLOCK_ZONE["zone"]


# Studiouhr B4: On-Air/REC-Signal. Nur im Speicher (clocksignal.py) – nach einem Neustart „off“, nie in der Sicherung.
CLOCK_SIGNAL = clocksignal.Signal()
CLOCK_SIGNAL_RATE = clocksignal.RateLimit()
BACKUP_DOWNLOAD_SLOT = threading.BoundedSemaphore(1)   # GET /api/backup: eine neue Sicherung gleichzeitig
SIGNAL_TITLES = {"off": "aus", "on_air": "ON AIR", "rec": "REC"}
SIGNAL_AUDIT_TITLE = "On-Air-Signal der Uhr:"
# Einträge ins Ereignisprotokoll: Die ersten SIGNAL_AUDIT_BURST stehen sofort da (ein Abend mit vielen Wechseln), danach
# kommt je SIGNAL_AUDIT_SECONDS ein Platz nach. Wer im Sekundentakt schaltet, erzeugt also höchstens einen Eintrag je
# Minute (wie last_used der API-Schlüssel) – das Protokoll und die SD-Karte bleiben in Ruhe. Zusätzlich hält events.py
# nur die neuesten SIGNAL_AUDIT_ROWS dieser Einträge: Sie verdrängen nie andere Ereignisse aus dem Protokoll.
SIGNAL_AUDIT_BURST = 10
SIGNAL_AUDIT_SECONDS = 60.0
SIGNAL_AUDIT_ROWS = 2_000
SIGNAL_AUDIT_KEYS_MAX = 8    # so viele Schlüsselkennungen übersprungener Wechsel nennt ein Nachtrag höchstens
_SIGNAL_AUDIT: dict = {"t": None, "tokens": SIGNAL_AUDIT_BURST, "pending": None, "skipped": 0, "keys": []}
_SIGNAL_AUDIT_LOCK = threading.Lock()
events.set_quota("settings", SIGNAL_AUDIT_TITLE, SIGNAL_AUDIT_ROWS)
for _title in statewatch.CLIENT_EVENT_TITLES:  # von außen auslösbar: verdrängt nie andere Ereignisse
    events.set_quota("clients", _title, statewatch.CLIENT_EVENT_ROWS)
_SIGNAL_TIMERS: dict = {"audit": None, "expiry": None}
_SIGNAL_TIMERS_LOCK = threading.Lock()


def _signal_timer(name: str, delay: float | None, action=None) -> None:
    """Einen der beiden Zeitgeber des Signals neu stellen (delay None: nur abstellen). Daemon-Threads – sie halten
    das Beenden nie auf."""
    def run() -> None:
        with _SIGNAL_TIMERS_LOCK:
            if _SIGNAL_TIMERS.get(name) is timer:
                _SIGNAL_TIMERS[name] = None
        try:
            action()
        except Exception:
            pass

    with _SIGNAL_TIMERS_LOCK:
        old = _SIGNAL_TIMERS.get(name)
        if old is not None:
            old.cancel()
        _SIGNAL_TIMERS[name] = None
        if delay is None:
            return
        timer = threading.Timer(max(0.0, delay), run)
        timer.daemon = True
        _SIGNAL_TIMERS[name] = timer
        timer.start()


def signal_audit(entry: dict | None = None, mono: float | None = None) -> None:
    """Wechsel des On-Air-Signals ins Ereignisprotokoll: Zustand, Ablaufzeit und – bei einem API-Schlüssel – dessen
    Kennung. Keine Adresse des Aufrufers. Gedrosselt mit einem Vorrat: SIGNAL_AUDIT_BURST Einträge sofort, danach
    einer je SIGNAL_AUDIT_SECONDS. Ist der Vorrat leer, wird nur der letzte Stand nachgetragen, sobald wieder ein
    Platz frei ist – mit der Zahl der übersprungenen Wechsel (skipped) und den Kennungen der Schlüssel, die dabei
    geschaltet haben (api_keys). Dafür läuft ein Zeitgeber, der diese Funktion ohne entry aufruft – auch wenn gerade
    kein Bildschirm abfragt."""
    mono = time.monotonic() if mono is None else mono
    with _SIGNAL_AUDIT_LOCK:
        audit = _SIGNAL_AUDIT
        if audit["t"] is None or mono < audit["t"]:
            audit.update(t=mono, tokens=SIGNAL_AUDIT_BURST)
        else:
            gained = int((mono - audit["t"]) // SIGNAL_AUDIT_SECONDS)
            if gained > 0:
                audit["tokens"] = min(SIGNAL_AUDIT_BURST, audit["tokens"] + gained)
                audit["t"] = mono if audit["tokens"] >= SIGNAL_AUDIT_BURST else audit["t"] + gained * SIGNAL_AUDIT_SECONDS
            elif audit["tokens"] >= SIGNAL_AUDIT_BURST:
                audit["t"] = mono   # voller Vorrat: Die Wartezeit auf den nächsten Platz beginnt mit dem ersten Eintrag
        if entry is not None:
            old = audit["pending"]
            if old is not None:
                audit["skipped"] += 1
                key = old.get("api_key")
                if key is not None and key not in audit["keys"] and len(audit["keys"]) < SIGNAL_AUDIT_KEYS_MAX:
                    audit["keys"].append(key)
            audit["pending"] = entry
        if audit["pending"] is None:
            return
        if audit["tokens"] <= 0:
            _signal_timer("audit", SIGNAL_AUDIT_SECONDS - (mono - audit["t"]) + 0.02, signal_audit)
            return
        entry, skipped, keys = audit["pending"], audit["skipped"], audit["keys"]
        audit.update(tokens=audit["tokens"] - 1, pending=None, skipped=0, keys=[])
    state = entry.get("state")
    data = {"state": state}
    for key in ("ttl", "api_key", "reason", "set_by"):
        if entry.get(key) is not None:
            data[key] = entry[key]
    if skipped:
        data["skipped"] = skipped
        others = [key for key in keys if key != entry.get("api_key")]
        if others:
            data["api_keys"] = others
    title = f"{SIGNAL_AUDIT_TITLE} {SIGNAL_TITLES.get(state, 'aus')}"
    if entry.get("reason") == "ttl_changed":
        title += " – Ablaufzeit geändert" if entry.get("ttl") else " – Ablaufzeit aufgehoben"
    try:
        events.emit("settings", "info", title, data, source=entry.get("source") or "web")
    except Exception:
        pass  # das Protokoll darf das Signal nie aufhalten


def signal_expired_entry(by: Any = None) -> dict:
    """Protokolleintrag „aus, weil die Ablaufzeit um ist“ – mit dem Vermerk, wer diese Ablaufzeit gesetzt hat
    (set_by: „api“ oder „web“, bei einem API-Schlüssel dessen Kennung)."""
    entry = {"state": "off", "reason": "ttl", "source": "system"}
    if isinstance(by, dict):
        entry["set_by"] = by.get("source")
        entry["api_key"] = by.get("api_key")
    return entry


def clock_signal() -> dict:
    """{"signal", "signal_rev"} für /api/v1/time – nur der feste Wert und die Kennung des Stands."""
    try:
        now = CLOCK_SIGNAL.read()
        signal_audit(signal_expired_entry(now.get("expired_by")) if now["expired"] else None)
        return {"signal": now["signal"], "signal_rev": now["signal_rev"]}
    except Exception:
        return {"signal": "off", "signal_rev": ""}


def time_payload(received: float, public: bool) -> dict:
    """Antwort von /api/v1/time. t2 wird so spät wie möglich genommen."""
    tracking = _clock_tracking()
    try:
        cfg = settings.values()
    except Exception:
        cfg = {}
    out = clock_status(tracking, cfg, clock_extra(interval=cfg.get("history_interval")))
    out.update(_clock_leap(cfg))   # leap_next und tai_utc
    out["zone"] = _clock_zone()
    out["profiles_rev"] = clockprofiles.revision(cfg.get("clock_profiles"))
    out.update(clock_signal())
    out.update(t1=received, public=public,
               source=None if public else (str(tracking.get("ref_name") or "") or None))
    out["t2"] = time.time()
    return out


def profile_payload(name) -> tuple[dict, HTTPStatus]:
    """GET /api/v1/clock/profile?p=…: (Antwort, Status). Nur Allowlist-Felder, unbekannt → 404, Name ungültig → 400.
    Ohne p nur die Namen der festen Voreinstellungen (nie die Namen gespeicherter Profile)."""
    if name is None or name == "":
        return {"presets": list(clockprofiles.PRESETS)}, HTTPStatus.OK
    if not isinstance(name, str) or not clockprofiles.NAME_RE.fullmatch(name):
        return {"error": "Profilname: 1–32 Zeichen aus a–z, 0–9 und Bindestrich"}, HTTPStatus.BAD_REQUEST
    try:
        stored = settings.values().get("clock_profiles") or {}
    except Exception:
        stored = {}
    profile = clockprofiles.public_profile(name, stored)
    if profile is None:
        return {"error": "Profil nicht gefunden"}, HTTPStatus.NOT_FOUND
    profile["profiles_rev"] = clockprofiles.revision(stored)
    return profile, HTTPStatus.OK


TEMPERATURE_DEFAULT_RANGE = 7 * 86400.0


def temperature_payload(query: dict) -> dict:
    seconds = env_like(query.get("range"), TEMPERATURE_DEFAULT_RANGE)
    seconds = max(3600.0, min(seconds, 30 * 86400.0))
    points = int(max(100, min(env_like(query.get("points"), 1500), 3000)))
    out = thermal.MONITOR.status(settings.values().get("temp_sensor"))
    pairs = thermal.pairs_from_samples(HISTORY.query(seconds, points))
    out.update(pairs=pairs, summary=thermal.summarize(pairs), range=seconds)
    return out


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------

def _metric(lines: list[str], name: str, value, help_text: str, kind: str = "gauge", labels: str = "") -> None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    if not any(line.startswith(f"# TYPE {name} ") for line in lines):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
    lines.append(f"{name}{labels} {value}")


def _escape_label(value) -> str:
    """Prometheus label values escape backslash, quote and newline."""
    return opsmetrics.escape_label(value)


def build_metrics() -> str:
    tracking = chrony.tracking()
    lines: list[str] = []
    _metric(lines, "ntpgui_up", 1 if tracking else 0, "1 when chronyd answers")
    _metric(lines, "ntpgui_stratum", tracking.get("stratum"), "Stratum reported by chronyd")
    _metric(lines, "ntpgui_system_time_offset_seconds", tracking.get("system_time_offset"), "System clock offset")
    _metric(lines, "ntpgui_last_offset_seconds", tracking.get("last_offset"), "Last measured offset")
    _metric(lines, "ntpgui_rms_offset_seconds", tracking.get("rms_offset"), "Long term RMS offset")
    _metric(lines, "ntpgui_frequency_ppm", tracking.get("frequency_ppm"), "Clock frequency error")
    _metric(lines, "ntpgui_skew_ppm", tracking.get("skew_ppm"), "Estimated frequency error bound")
    _metric(lines, "ntpgui_root_delay_seconds", tracking.get("root_delay"), "Root delay")
    _metric(lines, "ntpgui_root_dispersion_seconds", tracking.get("root_dispersion"), "Root dispersion")
    _metric(lines, "ntpgui_synchronised", 1 if tracking.get("synchronised") else 0, "1 when the clock is synchronised")
    _metric(lines, "ntpgui_max_error_seconds", clock_status(tracking)["accuracy"] if tracking else None,
            "Maximum error bound of the system clock: |offset| + root dispersion + root delay / 2")
    lines.append("# HELP ntpgui_info Build information (value is always 1)")
    lines.append("# TYPE ntpgui_info gauge")
    lines.append('ntpgui_info{version="%s"} 1' % _escape_label(VERSION))

    sources = chrony.detailed_sources()
    _metric(lines, "ntpgui_sources", len(sources), "Configured time sources known to chronyd")
    _metric(lines, "ntpgui_sources_usable", sum(1 for s in sources if s.get("state") in {"*", "+"}),
            "Sources currently used by chronyd (selected or combined)")
    labelled = [('{source="%s",mode="%s"}' % (_escape_label(source.get("name", "")),
                                               _escape_label(source.get("mode_label", ""))), source)
                for source in sources]
    # Je Metrik ein zusammenhängender Block über alle Quellen (Textformat: eine Familie am Stück).
    per_source = (
        ("ntpgui_source_offset_seconds", lambda s: s.get("offset"), "Offset per source"),
        ("ntpgui_source_stratum", lambda s: s.get("stratum"), "Stratum per source"),
        ("ntpgui_source_reach_percent", lambda s: s.get("reach_percent"), "Reachability per source"),
        ("ntpgui_source_jitter_seconds", lambda s: s.get("std_dev"), "Standard deviation per source"),
        ("ntpgui_source_selected", lambda s: 1 if s.get("state") == "*" else 0, "1 for the selected source"),
        ("ntpgui_source_combined", lambda s: 1 if s.get("state") in {"*", "+"} else 0, "1 when the source is used"),
        ("ntpgui_source_authenticated", lambda s: 1 if s.get("authenticated") else 0, "1 when NTS-authenticated"),
    )
    for name, value_of, help_text in per_source:
        for labels, source in labelled:
            _metric(lines, name, value_of(source), help_text, labels=labels)

    stats = chrony.serverstats()
    _metric(lines, "ntpgui_ntp_packets_received_total", stats.get("ntp_packets_received"), "NTP packets served", kind="counter")
    _metric(lines, "ntpgui_ntp_packets_dropped_total", stats.get("ntp_packets_dropped"), "NTP packets dropped", kind="counter")
    _metric(lines, "ntpgui_nts_ke_connections_accepted_total", stats.get("nts_ke_connections_accepted"), "NTS-KE connections accepted", kind="counter")
    _metric(lines, "ntpgui_clients", len(chrony.clients()), "Known NTP clients")

    gps_state = gps.status()
    if gps_state.get("enabled"):
        _metric(lines, "ntpgui_gps_running", 1 if gps_state.get("running") else 0, "1 when gpsd answers")
        _metric(lines, "ntpgui_gps_fix_mode", gps_state.get("mode"), "gpsd fix mode (0-3)")
        # Keine Satellitenzahlen und HDOP nur als Stufe: Als Zeitreihe markiert jeder Sprung den Auf- oder
        # Untergang eines Satelliten und grenzt so die Region ein (wie in der Aufzeichnung des Diagnosepakets).
        _metric(lines, "ntpgui_gps_hdop", egress.hdop_step(gps_state.get("hdop")),
                "Horizontal dilution of precision as step (upper bound 1, 2, 5, 10 or 20)")
        # Signalstärke nur als stärkster Wert: Der Mittelwert springt, wenn ein schwacher Satellit tief am
        # Horizont dazukommt oder untergeht – dieselbe Spur wie die Satellitenzahl.
        _metric(lines, "ntpgui_gps_snr_max_db", gps_state.get("snr_max"), "Strongest SNR of used satellites")
        _gps15_metrics(lines)

    ptp_state = ptp.status()
    if ptp_state.get("enabled"):
        _metric(lines, "ntpgui_ptp_running", 1 if ptp_state.get("running") else 0, "1 when ptp4l answers")
        offset = ptp_state.get("offset_ns")
        delay = ptp_state.get("meanPathDelay")
        _metric(lines, "ntpgui_ptp_offset_seconds", offset / 1e9 if isinstance(offset, (int, float)) else None, "PTP offset from master")
        _metric(lines, "ntpgui_ptp_mean_path_delay_seconds", delay / 1e9 if isinstance(delay, (int, float)) else None, "PTP mean path delay")
        _metric(lines, "ntpgui_ptp_steps_removed", ptp_state.get("stepsRemoved"), "Steps removed from the grandmaster")

    services = [('{service="%s"}' % _escape_label(name), svc) for name, svc in services_status().items()]
    # Je Metrik ein zusammenhängender Block (Prometheus-Textformat).
    for labels, svc in services:
        _metric(lines, "ntpgui_service_up", 1 if svc["state"] == "running" else 0,
                "1 when the supervised service is running", labels=labels)
    for labels, svc in services:
        _metric(lines, "ntpgui_service_enabled", 1 if svc.get("enabled", True) else 0,
                "1 when the service should run per settings (0 = switched off on purpose, e.g. GPS/PTP off)",
                labels=labels)
    for labels, svc in services:
        _metric(lines, "ntpgui_service_restarts_total", svc["restarts"],
                "Restarts of the service by the supervisor", kind="counter", labels=labels)

    nts = chrony.nts_server_status(settings.values(), stats)
    if nts.get("enabled"):
        _metric(lines, "ntpgui_nts_server_cert_days_left", nts.get("days_left"),
                "Days until the NTS server certificate expires")

    pi = pistate.MONITOR.metrics_state()
    if pi is not None:
        uv, thr = pi.get("undervoltage") or {}, pi.get("throttled") or {}
        if uv.get("now") is not None:
            _metric(lines, "ntpgui_pi_undervoltage", 1 if uv["now"] else 0,
                    "1 when the Raspberry Pi reports under-voltage right now (firmware/hwmon, last history sample)")
        if thr.get("now") is not None:
            _metric(lines, "ntpgui_pi_throttled", 1 if thr["now"] else 0,
                    "1 when the Raspberry Pi firmware throttles the CPU right now (last history sample)")
    last = thermal.MONITOR.last
    if isinstance(last.get("t"), (int, float)) and time.time() - last["t"] < 900:
        _metric(lines, "ntpgui_temperature_celsius", last.get("celsius"),
                "Temperature of the selected sensor (Uhrqualitaet, last history sample)")
    leap_info = leap.status(settings.values(), tracking)
    if leap_info.get("available") and leap_info.get("source") == "list":
        # Nur die Datei, die chrony wirklich liest – sonst meldet die Metrik ein Ablaufdatum ohne Bedeutung.
        _metric(lines, "ntpgui_leapseconds_list_days_left", leap_info.get("days_left"),
                "Days until leap-seconds.list expires (negative = expired)")
        _metric(lines, "ntpgui_tai_utc_offset_seconds", leap_info.get("tai_utc"), "TAI-UTC from leap-seconds.list")

    upd = _update_status()
    if upd.get("enabled") and upd.get("last_success"):
        _metric(lines, "ntpgui_update_available", 1 if upd.get("available") else 0,
                "1 when GitHub lists a newer ntp-gui release (opt-in update check)")
        _metric(lines, "ntpgui_update_check_last_success_timestamp_seconds", upd.get("last_success"),
                "Unix time of the last successful update check")

    loops = LOOP_GUARD.loops()
    _metric(lines, "ntpgui_source_loops", len(loops),
            "Own time sources that point back to ntp-gui (DNS rewrite / NAT redirect without exception)")
    try:
        running = 1 if holdover.TEST.state().get("active") else 0
    except Exception:
        running = None
    _metric(lines, "ntpgui_holdover_test_running", running,
            "1 while a holdover test runs (sources deselected on purpose, clients get less accurate time)")
    _hardware_metrics(lines)
    for name, value, help_text, kind, labels in opsmetrics.collect(settings.values(), STATE_WATCH):
        _metric(lines, name, value, help_text, kind=kind, labels=labels)
    return "\n".join(lines) + "\n"


GNSS_STAGE_VALUE = {"ok": 0, "hinweis": 1, "warnung": 2, "stoerung": 3}
RECEPTION_VALUE = {"green": 0, "yellow": 1, "red": 2}


def _gps15_metrics(lines: list[str]) -> None:
    """1.5: Fehlerschranke ohne PPS, Empfangsampel, „unstet“, GNSS-Stufe und GPS-Sperre."""
    cfg = settings.values()
    try:
        hint = gpsquality.status_hint(cfg)
        delay = hint.get("delay")
        _metric(lines, "ntpgui_gps_error_bound_seconds", delay / 2 if isinstance(delay, (int, float)) else None,
                "Error bound chrony assumes for the GPS refclock (delay/2; measured spread without PPS)")
    except Exception:
        pass
    try:
        summary = gpsquality.overview(cfg, HISTORY, None, STATE_WATCH.gps_stability()) or {}
        _metric(lines, "ntpgui_gps_reception_level", RECEPTION_VALUE.get(summary.get("level")),
                "GPS reception over 24 h: 0 good, 1 moderate, 2 weak (absent while unknown)")
        _metric(lines, "ntpgui_gps_unstable", 1 if summary.get("stability") == "unstet" else 0,
                "1 while the GPS fix flaps (state unstet)")
    except Exception:
        pass
    try:
        with gnssguard.GUARD.lock:
            stage = gnssguard.GUARD.stage
            locked = gnssguard.GUARD.lock_status().get("locked")
        _metric(lines, "ntpgui_gnss_stage", GNSS_STAGE_VALUE.get(stage),
                "GNSS interference detection: 0 normal, 1 hint, 2 warning, 3 disturbance")
        _metric(lines, "ntpgui_gps_locked", 1 if locked else 0,
                "1 while ntp-gui keeps the GPS deselected (chronyc selectopts +noselect)")
    except Exception:
        pass


def _hardware_metrics(lines: list[str]) -> None:
    """Nur aus dem zwischengespeicherten Hardware-Bericht – /metrics wartet nie auf PPS-Proben."""
    getter = getattr(hardware, "cached_report", None)
    try:
        rep = getter() if callable(getter) else getattr(hardware, "_REPORT", None)
    except Exception:  # Bericht kaputt → Metriken ohne Hardwareteil
        return
    if not isinstance(rep, dict):
        return
    for pps in rep.get("pps") or []:
        if isinstance(pps, dict) and pps.get("dev"):
            _metric(lines, "ntpgui_pps_live", 1 if pps.get("state") == "live" else 0,
                    "1 when pulses arrive on the PPS device", labels='{device="%s"}' % _escape_label(pps["dev"]))
    for row in rep.get("matrix") or []:
        if isinstance(row, dict) and row.get("key") and row.get("status"):
            labels = '{key="%s",status="%s"}' % (_escape_label(row["key"]), _escape_label(row["status"]))
            _metric(lines, "ntpgui_hardware_capability", 1, "Result of the hardware check per capability",
                    labels=labels)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class AuthCache:
    """PBKDF2 kostet auf einem Pi spürbar Zeit – geprüfte Zugänge kurz merken."""

    def __init__(self, clock=time.monotonic) -> None:
        self._ok: dict[str, float] = {}  # Schlüssel → gültig bis (monotonic: Uhrsprünge zählen nicht)
        self._lock = threading.Lock()
        self._generation = 0  # erhöht bei jedem clear()
        self.clock = clock

    def generation(self) -> int:
        """Stand vor einer Prüfung – remember() merkt nur, wenn seitdem kein clear() lief."""
        with self._lock:
            return self._generation

    def known(self, header: str) -> bool:
        key = hashlib.sha256(header.encode()).hexdigest()
        with self._lock:
            return self._ok.get(key, 0) > self.clock()

    def remember(self, header: str, generation: int | None = None) -> None:
        key = hashlib.sha256(header.encode()).hexdigest()
        now = self.clock()
        with self._lock:
            if generation is not None and generation != self._generation:
                return  # Passwort inzwischen geändert: Prüfung mit dem alten Stand nicht merken
            self._ok = {k: v for k, v in self._ok.items() if v > now}
            self._ok[key] = now + 300

    def forget(self, header: str) -> None:
        key = hashlib.sha256(header.encode()).hexdigest()
        with self._lock:
            self._ok.pop(key, None)

    def check(self, header: str, verify) -> bool:
        if self.known(header):
            return True
        if verify():
            self.remember(header)
            return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._ok.clear()
            self._generation += 1


AUTH_CACHE = AuthCache()


def auth_cache_key(header: str, info: dict) -> str:
    """Schlüssel für AUTH_CACHE. Bei WEB_PASSWORD_FILE gehört der Stand der Datei dazu: Ändert sich das
    Passwort in der Datei, gilt ein gemerkter Zugang mit dem alten nicht weiter."""
    key = header + "|" + str(info.get("source"))
    path = os.environ.get("WEB_PASSWORD_FILE", "").strip()
    if info.get("source") == "env" and path:
        try:
            st = os.stat(path)
            key += f"|{st.st_ino}:{st.st_size}:{st.st_mtime_ns}"
        except OSError:
            key += "|-"
    return key


class SingleFlight:
    """Gleiche Prüfungen bündeln: Kommt derselbe Anmeldekopf mehrmals gleichzeitig (Seite mit mehreren
    Abrufen), prüft nur die erste Anfrage; die übrigen warten auf deren Ergebnis statt selbst zu prüfen."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, dict] = {}

    def do(self, key: str, fn, timeout: float):
        """Ergebnis von fn() – für Wartende das der laufenden Prüfung; None, wenn sie zu lange dauert."""
        digest = hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()
        with self._lock:
            call = self._calls.get(digest)
            leader = call is None
            if leader:
                call = {"done": threading.Event(), "result": None}
                self._calls[digest] = call
        if not leader:
            return call["result"] if call["done"].wait(timeout) else None
        try:
            call["result"] = fn()
        finally:
            with self._lock:
                self._calls.pop(digest, None)
            call["done"].set()
        return call["result"]


AUTH_FLIGHT = SingleFlight()


# --- Schutz vor DNS-Rebinding -------------------------------------------------

# Namen, die keine fremde Webseite für sich auf eine LAN-Adresse zeigen lassen
# kann: reservierte bzw. nie öffentlich vergebene Endungen. Bewusst NICHT dabei:
# ".fritz.box" – ".box" ist eine echte, öffentlich vergebene Endung (fritz.box war
# schon fremd registriert). Wer das Dashboard über name.fritz.box öffnet, trägt
# WEB_ALLOWED_HOSTS=*.fritz.box ein oder setzt ein Passwort.
LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa", ".internal", ".home", ".corp",
                       ".localdomain", ".intranet", ".private", ".speedport.ip")
_REJECTED_HOSTS: set[str] = set()
_REJECTED_LOCK = threading.Lock()


def _host_name(header: str) -> str:
    """Host-Header → Name ohne Port, klein, ohne Schlusspunkt ('[::1]:80' → '::1')."""
    host = (header or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def safe_host_for_log(host: str) -> str:
    """Host-Header für Log und Fehlermeldung: nur [a-z0-9.-:], Labels ≤ 63 Zeichen, sonst „<ungültig>“.

    Der Wert kommt ungeprüft von außen; ein überlanger oder seltsamer Name im Log würde sonst
    später das Diagnosepaket stören (Schlussprüfung).
    """
    host = (host or "").strip().lower()
    if not host or len(host) > 253 or not re.fullmatch(r"[a-z0-9.:-]+", host):
        return "<ungültig>"
    if any(len(label) > 63 for label in host.split(".")):
        return "<ungültig>"
    return host


def _env_allowed_hosts() -> list[str]:
    return settings.env_allowed_hosts()


def _matches_allowed(host: str, entries) -> bool:
    """Name gegen Einträge „name“ bzw. „*.domain“ (Domain selbst eingeschlossen)."""
    for entry in entries:
        entry = str(entry or "").strip().lower().rstrip(".")
        if not entry or entry == "*":
            continue  # „*“ zählt nur aus der Umgebung (host_allowed)
        if entry.startswith("*."):
            if host.endswith(entry[1:]) or host == entry[2:]:
                return True
        elif host == entry:
            return True
    return False


def host_allowed(header: str | None, nts_name: str = "", extra=None) -> bool:
    """Darf eine Anfrage mit diesem Host-Header ohne Anmeldung beantwortet werden?

    extra: „Erlaubte Namen“ aus dem Dashboard (settings web_allowed_hosts) – gelten
    zusätzlich zu WEB_ALLOWED_HOSTS. Kein DNS je Anfrage, nur Textvergleiche.
    """
    if header is None or not header.strip():
        return True  # HTTP/1.0 ohne Host – das schickt kein Browser
    host = _host_name(header)
    allowed = _env_allowed_hosts()
    if "*" in allowed:
        return True
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        pass
    if not host or "." not in host:
        return True  # einteilige Namen (raspberrypi, localhost) löst kein öffentliches DNS auf
    if host.endswith(LOCAL_HOST_SUFFIXES):
        return True
    if nts_name and host == str(nts_name).strip().lower().rstrip("."):
        return True
    if _matches_allowed(host, allowed) or _matches_allowed(host, extra or ()):
        return True
    # Gemerkte eigene Namen: kein Rückwärts-DNS je Anfrage (ein fremder Host-Kopf hätte sonst
    # jedes Mal einen Handler-Thread für die Dauer der DNS-Abfrage blockiert).
    return host in diagnostics.own_hostnames(wait=1.0)


def host_rejection_text(host: str) -> str:
    return (f"Zugriff über den Namen „{host}“ abgelehnt. Ohne Passwort beantwortet ntp-gui nur Anfragen "
            "an IP-Adressen, localhost, den eigenen Hostnamen, einteilige Namen, lokale Namen (*.local, "
            "*.lan, *.home.arpa, *.internal) und erlaubte Namen. Das schützt vor DNS-Rebinding: Sonst könnte "
            "jede Webseite, die du besuchst, über einen eigenen Namen Log, Status und Position aus deinem "
            "Netz lesen. Abhilfe: den Namen erlauben – im Dashboard unter System → Einstellungen → "
            "Dashboard & Zugang → „Erlaubte Namen“ (über die IP-Adresse öffnen) oder per Umgebungsvariable "
            f"WEB_ALLOWED_HOSTS={host} (mehrere mit Komma, „*.example.org“ für alle Unternamen) – oder "
            "im Dashboard bzw. per WEB_USER/WEB_PASSWORD ein Passwort setzen, dann gilt jeder Name. "
            "Die Vollbild-Uhr /clock ist mit „Vollbild-Uhr ohne Anmeldung“ über jeden Namen erreichbar.")


# 1.5.4: Fristen je Verbindung. Ohne sie hielt ein Client, der Content-Length ankündigt und weniger
# schickt, oder eine still offene Keep-alive-Verbindung einen Thread für immer.
# Leerlauf zwischen Anfragen und Frist je Socket-Vorgang. Länger als die Verbindungs-Pools gängiger
# Reverse Proxys (Caddy 2 min, nginx keepalive_timeout 60 s): Schließt ntp-gui eine Verbindung, die der
# Proxy gerade wiederverwendet, bekommt der Browser ein 502 – bei POST ohne neuen Versuch.
REQUEST_IDLE_TIMEOUT = 125.0
REQUEST_READ_DEADLINE = 60.0  # Anfragezeile + Köpfe + Body zusammen, ab dem ersten Byte der Anfrage
WRITE_CHUNK = 64 * 1024       # Antwort in Stücken: die Socket-Frist gilt je sendall(), nicht je Antwort


class _Reaper:
    """Schließt Verbindungen, die ihre Anfrage nicht in REQUEST_READ_DEADLINE zu Ende schicken.

    Die Socket-Frist allein hilft nicht gegen Tröpfeln (alle 29 s ein Byte). Ein Thread für alle
    Verbindungen, gestartet beim ersten Gebrauch; armiert wird nur, solange gelesen wird – eine
    lange Antwort (Diagnosepaket) läuft ohne Frist."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._due: dict[object, float] = {}
        self._reaped: set[int] = set()
        self._thread: threading.Thread | None = None

    def arm(self, conn, seconds: float) -> None:
        with self._lock:
            self._due[conn] = time.monotonic() + seconds
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="http-reaper")
                self._thread.start()

    def disarm(self, conn) -> bool:
        """Frist aufheben. Gibt zurück, ob sie die Verbindung schon geschlossen hatte – Prüfen und
        Aufheben in einem Schritt, sonst könnte die Frist genau dazwischen zuschlagen."""
        with self._lock:
            self._due.pop(conn, None)
            reaped = id(conn) in self._reaped
            self._reaped.discard(id(conn))
            return reaped

    def was_reaped(self, conn) -> bool:
        """Hat die Frist diese Verbindung geschlossen? Dann ist, was gelesen wurde, unvollständig –
        auch wenn das Ende der Köpfe danach wie eine Leerzeile aussieht."""
        with self._lock:
            return id(conn) in self._reaped

    def reap(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            late = [conn for conn, due in self._due.items() if due <= now]
            for conn in late:
                self._due.pop(conn, None)
                self._reaped.add(id(conn))
        for conn in late:
            try:
                conn.shutdown(socket.SHUT_RDWR)  # wartendes recv() kehrt sofort zurück
            except OSError:
                pass
        return len(late)

    def _run(self) -> None:
        while True:
            time.sleep(1.0)
            try:
                self.reap()
            except Exception:
                pass


REAPER = _Reaper()


# Content-Security-Policy: nur eigene Skripte, Stylesheets und Verbindungen. Inline-Skripte,
# on…-Attribute und style-Attribute sind gesperrt (el() setzt Stile per CSSOM, das bleibt erlaubt);
# data: nur für Bilder (Favicon). Gilt für jede Antwort, auch für JSON und Fehlerseiten.
# Trusted Types: Das Frontend setzt Inhalte nur als Text bzw. per DOM-Knoten – HTML-Senken wie innerHTML sind damit
# auch künftig gesperrt (Tiefenverteidigung gegen eingeschleustes Markup).
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
       "require-trusted-types-for 'script'; trusted-types 'none'")
# Gerätezugriffe, die weder Dashboard noch Uhr brauchen, gar nicht erst anbieten. Vollbild, Wachhalten des
# Bildschirms, Ton und Zwischenablage nutzt die Uhr bzw. das Dashboard – die bleiben erlaubt.
PERMISSIONS_POLICY = ("accelerometer=(), camera=(), display-capture=(), geolocation=(), gyroscope=(), hid=(), "
                      "magnetometer=(), microphone=(), midi=(), payment=(), serial=(), usb=()")
# Abmelden bei Basic-Auth: Die Seite ruft diesen Pfad mit dem Benutzer LOGOUT_USER auf; die Antwort 200 bringt
# den Browser dazu, diese (wertlosen) Angaben statt der echten zu merken. Der Pfad prüft nichts und gibt nichts preis.
LOGOUT_PATH = "/logout"
LOGOUT_USER = "abgemeldet"
HSTS_VALUE = "max-age=31536000"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": PERMISSIONS_POLICY,
}

# GET-Routen, die spürbar Arbeit machen (Sicherung bauen, Diagnose sammeln, Hardware neu prüfen). Ein Browser
# schickt GETs auch für fremde Seiten (<img>, Links) samt gemerkter Anmeldung mit – diese Routen nehmen darum nur
# Aufrufe aus dem Dashboard selbst, direkt eingegebene Adressen und Werkzeuge ohne Sec-Fetch-Site an.
COSTLY_GET_PATHS = frozenset({"/api/backup", "/api/diagnostics/preview", "/api/diagnostics/bundle"})
# Gilt eine Sec-Fetch-Site-Angabe als „aus dem Dashboard“? „none“: Adresszeile, Lesezeichen, Download-Manager.
SAME_ORIGIN_FETCH = frozenset({"same-origin", "none"})

# Höchstzahl gleichzeitig offener Verbindungen zum Dashboard. Jede Verbindung belegt einen Thread; ohne Grenze
# könnten viele offen gehaltene Verbindungen Speicher und Prozessgrenze (pids-limit) des Containers aufbrauchen.
# Darüber hinaus wird eine neue Verbindung sofort geschlossen, ohne Thread.
MAX_CONNECTIONS_DEFAULT = 200


# Darüber hinaus darf eine einzelne Quelladresse (IPv6: ein /64-Netz) nur einen Teil der Plätze belegen – sonst
# sperrte ein einzelnes Gerät mit offen gehaltenen leeren Verbindungen alle anderen aus. Ausgenommen sind die
# eigene Maschine (Loopback) und eingetragene vertrauenswürdige Proxys.
def per_source_limit(max_connections: int) -> int:
    return max(8, max_connections // 8)


# So viele Plätze bleiben Verbindungen von der eigenen Maschine vorbehalten (Docker-Healthcheck auf /healthz).
def local_reserve(max_connections: int) -> int:
    return min(4, max_connections // 4)


# Ist mehr als dieser Anteil belegt, bekommt eine Verbindung ohne Anfrage nur noch diese kurze Frist (statt
# REQUEST_IDLE_TIMEOUT), bevor sie geschlossen wird – Loopback und vertrauenswürdige Proxys ausgenommen.
BUSY_SHARE = 0.75
BUSY_IDLE_TIMEOUT = 10.0
# Jede Verbindung belegt einen Thread und damit einen Platz der Prozessgrenze (pids-limit) des Containers.
# So viele Plätze bleiben dort für Watchdog, Zeitdienste, chronyc und Healthcheck frei.
PIDS_RESERVE = 64
PIDS_MAX_FILES = ("/sys/fs/cgroup/pids.max", "/sys/fs/cgroup/pids/pids.max")


def pids_capped_connections(max_connections: int, files=PIDS_MAX_FILES) -> tuple[int, str]:
    """max_connections passend zur Prozessgrenze des Containers – mit Hinweis, falls gekürzt."""
    for name in files:
        try:
            with open(name, encoding="ascii") as fh:
                text = fh.read().strip()
        except (OSError, ValueError):
            continue
        if not text.isdigit():
            return max_connections, ""  # „max“: keine Grenze
        cap = max(8, int(text) - PIDS_RESERVE)
        if cap < max_connections:
            return cap, (f"[web] Hinweis: Prozessgrenze des Containers ist {text} – höchstens {cap} gleichzeitige "
                         f"Verbindungen statt {max_connections}, damit Platz für die Zeitdienste bleibt. "
                         "Setze pids-limit deutlich über WEB_MAX_CONNECTIONS + 64.")
        return max_connections, ""
    return max_connections, ""


def _is_local_peer(address) -> bool:
    return address is not None and address.is_loopback


def _source_key(address) -> str:
    if address is None:
        return "?"
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)
# /healthz fragt chronyd höchstens so oft (Docker-Healthcheck, Überwachung) – nie ein chronyc-Prozess je Anfrage.
HEALTHZ_CACHE_SECONDS = 2.0


class Handler(BaseHTTPRequestHandler):
    server_version = "ntp-gui"
    sys_version = ""  # keine Python-Version im Server-Kopf
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_IDLE_TIMEOUT  # StreamRequestHandler.setup(): settimeout() auf der Verbindung

    def version_string(self) -> str:
        return self.server_version

    def handle_one_request(self) -> None:
        # Leerlauf (bis REQUEST_IDLE_TIMEOUT) ohne Frist abwarten; die Lesefrist beginnt erst mit dem
        # ersten Byte – sonst schlösse sie still offene Keep-alive-Verbindungen schon nach 60 s.
        # Bei hoher Auslastung wartet eine Verbindung ohne Anfrage nur kurz – leere Verbindungen halten so
        # keinen Platz bis REQUEST_IDLE_TIMEOUT.
        busy = getattr(self.server, "busy_for", None)
        short = bool(busy and busy(self.request))
        try:
            if short:
                self.connection.settimeout(BUSY_IDLE_TIMEOUT)
            if not self.rfile.peek(1):
                self.close_connection = True  # Gegenstelle hat geschlossen
                return
            if short:
                self.connection.settimeout(self.timeout)
        except OSError:
            self.close_connection = True  # Leerlauf zu lang oder Verbindung weg
            return
        REAPER.arm(self.connection, REQUEST_READ_DEADLINE)
        try:
            super().handle_one_request()
        finally:
            REAPER.disarm(self.connection)

    def parse_request(self) -> bool:
        self._body_unread = False
        ok = super().parse_request()
        if not ok:
            return ok
        if not (self.headers.get("Content-Length") or "").strip("0 "):
            reaped = REAPER.disarm(self.connection)  # kein Body: die Anfrage ist vollständig gelesen
        else:
            reaped = REAPER.was_reaped(self.connection)
            # Bis _read_json ihn liest, gilt der Body als ungelesen: Jede Antwort davor (GET/HEAD,
            # 405, 401 …) schließt die Verbindung – sonst liefe er als nächste Anfrage (CL.0-Desync).
            self._body_unread = True
        if reaped:
            self.close_connection = True
            return False  # Frist abgelaufen: Köpfe abgeschnitten – nicht ausführen
        lengths = [v.strip() for v in self.headers.get_all("Content-Length") or []]
        if lengths and (not all(v.isascii() and v.isdigit() for v in lengths)
                        or len({int(v) for v in lengths}) > 1):
            # Widersprüchliche oder ungültige Längen: headers.get() sähe nur den ersten Kopf – bei
            # „0“ vor „N“ liefen die N Bytes sonst als nächste Anfrage. Ablehnen (RFC 9112, 6.3).
            self._body_unread = True
            self._error(HTTPStatus.BAD_REQUEST, "Ungültige oder widersprüchliche Content-Length.")
            return False
        if self.headers.get_all("Transfer-Encoding"):
            # Nicht unterstützt: Der Body hätte sonst als leer gegolten und die Chunk-Bytes als
            # nächste Anfrage. Ablehnen und schließen (RFC 9112, 6.1).
            self._body_unread = True
            self._error(HTTPStatus.NOT_IMPLEMENTED,
                        "Transfer-Encoding wird nicht unterstützt – sende den Inhalt mit Content-Length.")
            return False
        return ok

    # --- Helfer --------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        if env_flag("WEB_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def _transport(self) -> dict:
        """Echte Gegenstelle und Protokoll – Proxy-Köpfe nur von TRUSTED_PROXIES (webtransport)."""
        try:
            trusted = webtransport.parse_networks(settings.values().get("trusted_proxies"))
        except Exception:
            trusted = []
        return webtransport.resolve(self.client_address[0] if self.client_address else "", self.headers, trusted)

    def address_string(self) -> str:
        # Zugriffsprotokoll: hinter einem eingetragenen Proxy die Adresse des Browsers.
        try:
            return self._transport()["client"]
        except Exception:
            return super().address_string()

    def _via_https(self) -> bool:
        try:
            info = self._transport()
        except Exception:
            return False
        return bool(info.get("proxied") and info.get("scheme") == "https")

    def _logout_probe(self) -> None:
        """LOGOUT_PATH: prüft nichts und gibt nichts preis.

        Im Browser (Accept: text/html) die Seite „Abgemeldet“. Für den Abruf aus der Seite: 200 nur für den
        Platzhalter-Benutzer LOGOUT_USER, ganz ohne Angaben 401 mit Basic-Aufforderung (damit der Browser die
        Platzhalter-Angaben überhaupt schickt), mit anderen Angaben 401 ohne Aufforderung (kein Anmeldedialog).
        """
        if "text/html" in self.headers.get("Accept", ""):
            body = ("<!doctype html><html lang=\"de\"><meta charset=\"utf-8\">"
                    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                    "<title>Abgemeldet</title><body><h1>Abgemeldet</h1>"
                    "<p>Du bist vom Dashboard abgemeldet. Fragt der Browser beim nächsten Aufruf nicht nach dem "
                    "Passwort, schließ alle Fenster des Browsers.</p>"
                    "<p><a href=\"/\">Wieder anmelden</a></p></body></html>\n")
            self._send(HTTPStatus.OK, body.encode("utf-8"), "text/html; charset=utf-8", {"Cache-Control": "no-store"})
            return
        header = self.headers.get("Authorization", "")
        user = None
        if header.startswith("Basic "):
            try:
                user = base64.b64decode(header[6:], validate=True).decode("utf-8").partition(":")[0]
            except Exception:
                user = ""
        if user == LOGOUT_USER:
            self._send_json({"ok": True, "logged_out": True})
        elif user is None:
            self._send_json({"ok": False, "logged_out": False}, HTTPStatus.UNAUTHORIZED,
                            {"WWW-Authenticate": 'Basic realm="ntp-gui", charset="UTF-8"'})
        else:
            self._send_json({"ok": False, "logged_out": False}, HTTPStatus.UNAUTHORIZED)

    def _set_auth(self, data: dict) -> None:
        """POST /api/auth: Zugang setzen, ändern oder entfernen.

        Besteht schon ein Zugang, ist das bisherige Passwort nötig (current_password) – derselbe Schutz wie bei
        der Anmeldung (Bremse je Quelle). Jede Änderung landet im Ereignisprotokoll (Art „access“, Stufe warn).
        """
        info = auth_info()
        if info["source"] == "env":
            raise settings.ValidationError("Der Zugang ist per WEB_USER/WEB_PASSWORD festgelegt "
                                           "und lässt sich hier nicht ändern.")
        clear = bool(data.get("clear"))
        if info["enabled"]:
            if clear and require_auth():
                raise settings.ValidationError("WEB_REQUIRE_AUTH=true ist gesetzt – den Zugang kannst du "
                                               "ändern, aber nicht entfernen.")
            key = self._client_key()
            wait = authguard.GUARD.reserve(key)
            if wait > 0:
                self._auth_retry = wait
                self._deny_auth()
                return
            try:
                stored = settings.stored_credentials()
                current = str(data.get("current_password") or "")
                with authguard.GUARD.slot() as got:
                    if not got:
                        self._auth_retry = 2.0
                        self._deny_auth()
                        return
                    ok = bool(stored and current and settings.verify_password(current, stored["hash"]))
                if not ok:
                    self._auth_retry = 0.0
                    self._auth_failed(key)
            finally:
                authguard.GUARD.release(key)
            if not ok:
                if self._auth_retry > 0:
                    self._deny_auth()
                    return
                self._error(HTTPStatus.FORBIDDEN, "Das bisherige Passwort stimmt nicht.",
                            fields={"current_password": "Bitte das bisherige Passwort eingeben"})
                return
        if not info["enabled"]:
            apikeys.prepare()  # Migration vor dem ersten Passwort: markiert Schlüssel aus der Zeit ohne Zugang
        if clear:
            if info["enabled"]:
                settings.set_credentials("", None)
                events.emit("access", "warn", "Zugang zum Dashboard entfernt – Dashboard ohne Passwort",
                            {}, source="web")
        else:
            settings.set_credentials(str(data.get("user", "")), str(data.get("password", "")))
            events.emit("access", "warn", "Passwort des Dashboards geändert" if info["enabled"]
                        else "Zugang zum Dashboard eingerichtet", {}, source="web")
        AUTH_CACHE.clear()
        out = {"ok": True, "auth": auth_public(auth_info(), {"kind": "basic"})}
        if not clear:
            # Ohne Passwort konnte jeder im Netz Schlüssel anlegen – zur Prüfung zeigen (behalten/widerrufen).
            out["open_keys"] = apikeys.open_mode_keys()
        self._send_json(out)

    def _note_transport(self, ident: dict) -> None:
        try:
            # Nur Passwort und Verwaltungsschlüssel dürfen eine Adresse für „per Klick eintragen“
            # vorschlagen – ein Lese-Schlüssel könnte sich sonst als Proxy nach vorn drängen.
            can_admin = ident.get("kind") == "basic" or ident.get("scope") == "admin"
            webtransport.WATCH.note(self._transport(), ident.get("kind"), can_admin=can_admin)
        except Exception:
            pass  # nur für einen Hinweis – nie eine Anfrage daran scheitern lassen

    def send_response(self, code, message=None) -> None:
        # Hier statt in _send: auch die Fehlerseiten von http.server (send_error) bekommen die Köpfe.
        super().send_response(code, message)
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        if self._via_https():
            # Nur, wenn die Anfrage nachweislich per HTTPS kam (vertrauenswürdiger Proxy) – über reines HTTP
            # wäre der Kopf wirkungslos bzw. könnte ein Dashboard ohne Proxy unerreichbar machen.
            self.send_header("Strict-Transport-Security", HSTS_VALUE)
        if getattr(self, "_body_unread", False):
            # Antwort vor dem Lesen des Bodys: ankündigen und danach schließen (setzt close_connection).
            self._body_unread = False
            self.send_header("Connection", "close")

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self._write_body(body)

    def _write_body(self, body: bytes) -> None:
        """In Stücken schreiben: Seit Python 3.5 gilt die Socket-Frist für ein ganzes sendall() – ein
        großes Diagnosepaket über eine langsame Mobil- oder VPN-Verbindung brach sonst nach der Frist
        still ab. Je Stück bleibt die Frist: Wer gar nichts mehr liest, hält keinen Thread fest."""
        view = memoryview(body)
        for start in range(0, len(view), WRITE_CHUNK):
            self.wfile.write(view[start:start + WRITE_CHUNK])

    def _send_file(self, path: str, content_type: str, extra_headers: dict | None = None) -> None:
        """Datei in Stücken senden (Sicherungen können groß sein – nicht ganz in den Speicher laden)."""
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command == "HEAD":
                return
            for chunk in iter(lambda: handle.read(WRITE_CHUNK), b""):
                self.wfile.write(chunk)

    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK, extra: dict | None = None) -> None:
        body = json.dumps(payload, default=str).encode()
        headers = {"Cache-Control": "no-store"}
        headers.update(extra or {})
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _error(self, status: HTTPStatus, message: str, **extra) -> None:
        self._send_json({"error": message, **extra}, status)

    def _identity(self) -> dict | None:
        """Wer fragt? {"kind": "open"|"basic"|"key", "scope"?} oder None (abgelehnt).

        Ein API-Schlüssel gilt immer mit seinem Recht – auch ohne gesetztes
        Passwort. Sonst: ohne Passwort ist alles offen, mit Passwort Basic-Auth.
        """
        self._auth_retry = 0.0  # Handler lebt bei Keep-Alive über mehrere Anfragen
        info = auth_info()
        if info.get("locked"):
            return {"kind": "locked"}  # Zugang verlangt, aber keiner eingerichtet: nichts geht (auch kein Schlüssel)
        header = self.headers.get("Authorization", "")
        if header[:7].lower() == "bearer ":
            key = apikeys.verify(header[7:].strip())
            return {"kind": "key", "scope": key["scope"], "id": key["id"]} if key else None
        if not info["enabled"]:
            return {"kind": "open"}
        return {"kind": "basic"} if self._authorised(info) else None

    def _deny_locked(self) -> None:
        """WEB_REQUIRE_AUTH ohne Zugang bzw. unvollständige Angaben in der Umgebung: Einrichtungs-Meldung (503)."""
        self.close_connection = True
        info = auth_info()
        reason = info.get("reason") or "Noch kein Zugang eingerichtet"
        if info.get("code") == "settings_unreadable":
            code, heading = "settings_unreadable", "Einstellungen nicht lesbar"
            text = (f"{reason}. Mit WEB_USER und WEB_PASSWORD in der Compose-Datei ist das Dashboard trotzdem "
                    "mit Anmeldung erreichbar (Speichern bleibt gesperrt). /healthz und /readyz bleiben erreichbar.")
        else:
            code, heading = "auth_setup_required", "Einrichtung nötig"
            text = (f"{reason}. Das Dashboard bleibt gesperrt, bis ein Zugang gesetzt ist: in der Compose-Datei "
                    "WEB_USER und WEB_PASSWORD (oder WEB_PASSWORD_FILE für ein Docker Secret) eintragen und den "
                    "Container neu erstellen. /healthz und /readyz bleiben erreichbar.")
        path = urlparse(self.path).path
        if path.startswith("/api") or path == "/metrics" or "json" in self.headers.get("Accept", ""):
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, text, reason=code)
            return
        body = (f"<!doctype html><html lang=\"de\"><meta charset=\"utf-8\"><title>{heading}</title>"
                f"<body><h1>{heading}</h1><p>{html.escape(text)}</p></body></html>\n")
        self._send(HTTPStatus.SERVICE_UNAVAILABLE, body.encode("utf-8"), "text/html; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _host_known(self) -> bool:
        """Host-Kopf bekannt/lokal/erlaubt (host_allowed) – ohne selbst zu antworten."""
        try:
            cfg = settings.values()
        except Exception:
            cfg = {}
        nts_name = str(cfg.get("nts_server_name") or "")
        extra = cfg.get("web_allowed_hosts") or []
        return host_allowed(self.headers.get("Host"), nts_name, extra if isinstance(extra, list) else [])

    def _host_ok(self, ident: dict) -> bool:
        """DNS-Rebinding: ohne Anmeldung nur bekannte/lokale Namen. Antwortet selbst mit 403."""
        if ident.get("kind") != "open":
            return True  # Passwort oder API-Schlüssel schützen
        if self._host_known():
            return True
        header = self.headers.get("Host")
        host = safe_host_for_log(_host_name(header or ""))
        with _REJECTED_LOCK:
            first = host not in _REJECTED_HOSTS and len(_REJECTED_HOSTS) < 1000
            if first:
                _REJECTED_HOSTS.add(host)
        if first:
            print(f"[web] Anfrage für unbekannten Host-Namen „{host}“ abgelehnt (Schutz vor DNS-Rebinding) – "
                  "erlauben unter System → Einstellungen → Dashboard & Zugang → „Erlaubte Namen“, "
                  "mit WEB_ALLOWED_HOSTS "
                  "oder ein Passwort setzen.", flush=True)
        text = host_rejection_text(host)
        self.close_connection = True  # ein evtl. POST-Body bleibt ungelesen
        path = urlparse(self.path).path
        if path.startswith("/api") or path == "/metrics" or "json" in self.headers.get("Accept", ""):
            self._error(HTTPStatus.FORBIDDEN, text, reason="host_not_allowed")
        else:
            body = ("<!doctype html><html lang=\"de\"><meta charset=\"utf-8\"><title>Zugriff abgelehnt</title>"
                    "<body>"
                    f"<h1>Zugriff abgelehnt</h1><p>{html.escape(text)}</p></body></html>\n")
            self._send(HTTPStatus.FORBIDDEN, body.encode("utf-8"), "text/html; charset=utf-8",
                       {"Cache-Control": "no-store"})
        return False

    def _read_only_key(self) -> bool:
        """Anfrage mit einem API-Schlüssel ohne Admin-Recht (sieht z. B. den DoH-Pfad nur gekürzt)."""
        ident = getattr(self, "_ident", None) or {}
        return ident.get("kind") == "key" and ident.get("scope") != "admin"

    def _scope_ok(self, ident: dict, method: str, path: str) -> bool:
        """Darf diese Identität die Methode auf dem Pfad nutzen (apiv1.required_scope)?"""
        if ident["kind"] != "key":
            return True
        needed = apiv1.required_scope(method, path)
        if needed == "session":
            return False  # Zugang und Schlüssel nur mit Benutzer/Passwort verwalten
        if needed == "clock" or ident["scope"] == "clock":
            # Das On-Air-Signal setzt ein Schlüssel mit Recht „clock“ (oder „admin“). Umgekehrt darf ein
            # „clock“-Schlüssel nichts anderes – weder lesen noch schreiben.
            return needed == "clock" and ident["scope"] in ("clock", "admin")
        if needed == "admin" and ident["scope"] != "admin":
            return False
        return apikeys.allows(ident["scope"], method)

    def _deny_scope(self, ident: dict, method: str, path: str) -> None:
        needed = apiv1.required_scope(method, path)
        if needed == "session":
            text = ("Das geht nur mit Benutzer und Passwort, nicht mit einem API-Schlüssel – "
                    "so kann ein entwendeter Schlüssel weder das Passwort ändern noch neue Schlüssel ausstellen.")
        elif ident.get("scope") == "clock":
            text = ("Dieser API-Schlüssel hat das Recht „clock“ und darf nur das On-Air-Signal der Uhr setzen "
                    "(POST /api/v1/clock/signal).")
        else:
            text = (f"Dieser API-Schlüssel hat das Recht „{ident.get('scope')}“; hier ist "
                    f"„{needed}“ nötig.")
        self._error(HTTPStatus.FORBIDDEN, text, scope_required=needed)

    def _client_key(self) -> str:
        """Zählschlüssel für die Anmeldebremse: echte Adresse (Proxy-Köpfe nur von TRUSTED_PROXIES)."""
        try:
            info = self._transport()
            if info.get("forward_conflict"):
                return authguard.conflict_key(info["peer"])
            return authguard.source_key(info["client"])
        except Exception:
            return authguard.source_key(self.client_address[0] if self.client_address else "")

    def _client_text(self) -> str:
        try:
            info = self._transport()
            conflict = info.get("forward_conflict")
            if conflict:
                # Welche Angabe vom Proxy stammt, ist unklar: beide nennen, keine als Absender.
                return (f"unklarer Adresse (Proxy {safe_host_for_log(info['peer'])}: X-Forwarded-For "
                        f"{safe_host_for_log(conflict[0])}, X-Real-IP {safe_host_for_log(conflict[1])})")
            return safe_host_for_log(info["client"])
        except Exception:
            return "?"

    def _authorised(self, info: dict | None = None) -> bool:
        """Basic-Anmeldung prüfen – mit Merker für gültige Zugänge und Bremse vor der teuren Prüfung.

        Ist die Quelle gerade gebremst, steht in self._auth_retry die Wartezeit (→ 429 in _deny_auth).
        Der Platzhalter-Benutzer nach dem Abmelden (LOGOUT_USER) und die Wiederholung eines gerade
        abgelehnten Anmeldekopfs werden ohne Prüfung und ohne neuen Fehlversuch abgewiesen.
        """
        self._auth_retry = 0.0
        info = info or auth_info()
        if not info["enabled"]:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        except Exception:
            return False
        user, _, password = decoded.partition(":")
        if user == LOGOUT_USER and info.get("user") != LOGOUT_USER:
            return False  # abgemeldeter Browser: nur erneut fragen, kein Fehlversuch
        cache_key = auth_cache_key(header, info)
        if AUTH_CACHE.known(cache_key):
            return True  # schon geprüft und gültig: nie gebremst
        key = self._client_key()
        if authguard.GUARD.is_negative(cache_key):
            self._auth_retry = authguard.GUARD.retry_after(key)
            return False
        outcome = AUTH_FLIGHT.do(cache_key + "|" + key,
                                 lambda: self._verify_login(info, user, password, key, cache_key),
                                 authguard.SLOT_WAIT + 30.0)
        if outcome is None:
            self._auth_retry = 2.0
            return False
        ok, retry = outcome
        self._auth_retry = retry
        return ok

    def _verify_login(self, info: dict, user: str, password: str, key: str, cache_key: str) -> tuple[bool, float]:
        """Eine Prüfung: Platz bei der Bremse reservieren, Passwort prüfen, Ergebnis festhalten."""
        wait = authguard.GUARD.reserve(key)
        if wait > 0:
            return False, wait
        try:
            with authguard.GUARD.slot() as got:
                if not got:
                    return False, 2.0  # zu viele Prüfungen gleichzeitig
                if AUTH_CACHE.known(cache_key):
                    return True, 0.0  # inzwischen von einer anderen Anfrage geprüft
                generation = AUTH_CACHE.generation()
                ok = self._check_password(info, user, password)
            if ok:
                AUTH_CACHE.remember(cache_key, generation)
                authguard.GUARD.success(key)
                return True, 0.0
            self._auth_retry = 0.0
            self._auth_failed(key, cache_key)  # zählen, bevor die Reservierung frei wird
            return False, self._auth_retry
        finally:
            authguard.GUARD.release(key)

    @staticmethod
    def _check_password(info: dict, user: str, password: str) -> bool:
        if info["source"] == "env":
            env = env_credentials()
            ok_user = hmac.compare_digest(user.encode(), env["user"].encode())
            ok_pass = hmac.compare_digest(password.encode(), env["password"].encode())
            return bool(ok_user & ok_pass)
        stored = settings.stored_credentials()
        if not stored:
            return False
        ok = bool(hmac.compare_digest(user.encode(), stored["user"].encode())
                  & settings.verify_password(password, stored["hash"]))
        if ok and settings.needs_rehash(stored["hash"]):
            try:
                settings.upgrade_hash(stored["user"], password, stored["hash"])
            except Exception as exc:  # die Anmeldung gilt trotzdem
                print(f"[web] Passwort-Hash nicht aktualisiert: {type(exc).__name__}", flush=True)
        return ok

    def _auth_failed(self, key: str, cache_key: str | None = None) -> None:
        """Fehlversuch zählen, ins Log (mit Adresse) und gedrosselt ins Ereignisprotokoll (ohne Adresse)."""
        result = authguard.GUARD.failure(key, cache_key)
        if not result.get("counted", True):
            return  # derselbe falsche Anmeldekopf wie zuvor (z. B. offener Tab mit altem Passwort)
        client = self._client_text()
        if result["blocked_for"]:
            self._auth_retry = result["blocked_for"]
        line = f"[web] Anmeldung fehlgeschlagen von {client} ({result['count']}. Fehlversuch)"
        if result["started"]:
            line += f" – Quelle für {int(result['blocked_for'])} s gebremst"
        print(line, flush=True)
        if result["report"]:
            events.emit("access", "warn", "Anmeldung fehlgeschlagen",
                        {"attempts": result["reported"], "blocked_sources": authguard.GUARD.blocked_sources()},
                        source="web")

    def _deny_auth(self) -> None:
        retry = float(getattr(self, "_auth_retry", 0.0) or 0.0)
        if retry > 0:
            seconds = max(1, int(retry + 0.999))
            self.close_connection = True
            text = (f"Zu viele fehlgeschlagene Anmeldungen – bitte in {seconds} s erneut versuchen.")
            self._send_json({"error": text, "retry_after": seconds}, HTTPStatus.TOO_MANY_REQUESTS,
                            {"Retry-After": str(seconds)})
            return
        if self.headers.get("Authorization", "")[:7].lower() == "bearer ":
            # Kein Basic-Dialog im Browser für ein Skript mit falschem Schlüssel.
            self._send_json({"error": "API-Schlüssel ungültig oder widerrufen"}, HTTPStatus.UNAUTHORIZED,
                            {"WWW-Authenticate": 'Bearer realm="ntp-gui"'})
            return
        self._send(HTTPStatus.UNAUTHORIZED, b"authentication required\n", "text/plain; charset=utf-8",
                   {"WWW-Authenticate": 'Basic realm="ntp-gui", charset="UTF-8"'})

    @staticmethod
    def _api_path(raw: str) -> tuple[str, bool]:
        """Normalisiert den Pfad: /api/v1/<x> → bisheriger Pfad, /api/keys → /api/apikeys.

        Gibt (Pfad, ist_v1_index) zurück. Unbekannte /api/v1/-Pfade bleiben, wie sie
        sind (→ 404).
        """
        path = urlparse(raw).path.rstrip("/") or "/"
        if apiv1.is_index(path):
            return path, True
        legacy = apiv1.resolve(path)
        if legacy:
            path = legacy
        if path == "/api/keys" or path.startswith("/api/keys/"):
            path = "/api/apikeys" + path[len("/api/keys"):]
        return path, False

    def _serve_static(self, name: str) -> None:
        try:
            # Steuerzeichen und überlange Namen gibt es unter static/ nicht – gar nicht erst ans Dateisystem.
            if len(name) > 200 or any(ord(c) < 32 for c in name):
                raise ValueError("ungültiger Name")
            path = (STATIC_DIR / name).resolve()
            found = path.is_file() and STATIC_DIR.resolve() in path.parents
        except (OSError, ValueError):
            found = False
        if not found:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, path.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    def _internal_error(self, where: str, exc: BaseException) -> None:
        """Unerwarteter Fehler: Einzelheiten nur ins Log, an den Client eine allgemeine Meldung (keine Pfade)."""
        print(f"[web] Fehler bei {self.command} {where}: {type(exc).__name__}: {exc}", flush=True)
        self.close_connection = True
        try:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Interner Fehler – Einzelheiten stehen im Log.")
        except OSError:
            pass

    def _cross_site_get(self, ident: dict, path: str) -> bool:
        """Teure GET-Route, angestoßen von einer fremden Seite? (Bearer-Schlüssel hängt kein Browser von sich aus an.)"""
        if not self._costly_get(path):
            return False
        if ident.get("kind") == "key":
            return False
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        return bool(site) and site not in SAME_ORIGIN_FETCH

    def _costly_get(self, path: str) -> bool:
        """GET-Route, die spürbar Arbeit macht (Sicherung, Diagnose, Hardware neu prüfen)?"""
        return path in COSTLY_GET_PATHS or (path == "/api/hardware"
                                            and self._query().get("refresh") in {"1", "true"})

    def _query(self) -> dict:
        return {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}

    # --- GET -----------------------------------------------------------------
    def do_HEAD(self) -> None:
        path, _ = self._api_path(self.path)
        if self._costly_get(path):
            # Nur Köpfe, aber dieselbe Arbeit wie ein Download – dafür gibt es GET.
            self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"", "text/plain; charset=utf-8", {"Allow": "GET"})
            return
        self.do_GET()

    def do_GET(self) -> None:
        received = time.time()   # t1 für /api/v1/time – so früh wie möglich
        path, index = self._api_path(self.path)
        if path in CLOCK_PUBLIC_PATHS and self._clock_public() and not auth_info().get("locked"):
            # Wer gültig angemeldet ist, bekommt die volle Antwort (mit Quellennamen); sonst die
            # öffentliche – nie 401 und für jeden Host-Namen (kein 403): Die öffentliche Antwort
            # enthält nur Zeit, Ampel, Genauigkeit und Art der Quelle, nichts, was DNS-Rebinding
            # lohnen würde. Ohne Passwort gibt es den Quellennamen nur über einen erlaubten Namen.
            ident = self._identity()
            full = (ident is not None and ident.get("kind") != "open"
                    and self._scope_ok(ident, "GET", path))
            open_known = (ident or {}).get("kind") == "open" and self._host_known()
            try:
                self._route_clock(path, received, public=not (full or open_known))
            except BrokenPipeError:
                pass
            return
        if path == "/healthz":
            healthy = bool(_healthz_tracking())
            self._send_json({"status": "ok" if healthy else "degraded", "chrony": healthy},
                            HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == "/readyz":
            # Strenge Variante für keepalived, Load-Balancer und Uptime-Monitore: wie /healthz ohne Anmeldung
            # und für jeden Host-Namen, die Antwort enthält nur Wahrheitswerte.
            state = readiness(_healthz_tracking(), ready_limit_ms(), ready_holdover())
            self._send_json(state, HTTPStatus.OK if state["status"] == "ready" else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == LOGOUT_PATH:
            self._logout_probe()
            return
        ident = self._identity()
        if ident is None:
            self._deny_auth()
            return
        if ident["kind"] == "locked":
            self._deny_locked()
            return
        if not self._host_ok(ident):
            return
        if not self._scope_ok(ident, "GET", path):
            self._deny_scope(ident, "GET", path)
            return
        if self._cross_site_get(ident, path):
            self._error(HTTPStatus.FORBIDDEN, "Anfrage abgelehnt (nur aus dem Dashboard heraus)")
            return
        self._ident = ident
        self._note_transport(ident)
        try:
            if index:
                self._send_json(apiv1.describe())
            else:
                self._route_get(path, received)
        except BrokenPipeError:
            pass
        except Exception as exc:  # nie wegen eines Parserfehlers ausfallen
            self._internal_error(path, exc)

    @staticmethod
    def _clock_public() -> bool:
        try:
            return bool(settings.values().get("clock_public"))
        except Exception:
            return False

    def _route_clock(self, path: str, received: float, public: bool) -> None:
        """/clock, ihre statischen Dateien und /api/v1/time."""
        if path == "/api/v1/time":
            self._send_json(time_payload(received, public))
        elif path == "/api/v1/clock/profile":
            self._send_json(*profile_payload(self._query().get("p")))
        elif path == "/clock":
            self._serve_static("clock.html")
        else:
            self._serve_static(path[len("/static/"):])

    def _route_get(self, path: str, received: float | None = None) -> None:
        query = self._query()
        if path in ("/clock", "/api/v1/time", "/api/v1/clock/profile"):
            self._route_clock(path, received or time.time(), public=False)
        elif path == "/":
            self._serve_static("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/status":
            status = build_status()
            if isinstance(status.get("ui"), dict):
                status["ui"]["auth"] = auth_public(auth_info(), getattr(self, "_ident", None))
            if self._read_only_key() or env_flag("WEB_READONLY"):
                # Knöpfe „per Klick beheben“ nur für den, der sie auch drücken darf (Admin).
                status["insights"] = [{k: v for k, v in item.items() if k != "fixes"}
                                      if isinstance(item, dict) else item for item in status["insights"]]
            self._send_json(status)
        elif path == "/api/history":
            seconds = env_like(query.get("range"), 3600.0)
            points = int(env_like(query.get("points"), 600))
            samples = HISTORY.query(seconds if seconds > 0 else None, max(10, min(points, 3000)))
            self._send_json({"samples": samples,
                             "interval": settings.values()["history_interval"]})
        elif path == "/api/config":
            files = []
            for name, file_path in (("chrony.conf", CHRONY_CONF), ("ptp4l.conf", PTP4L_CONF)):
                try:
                    files.append({"name": name, "path": file_path,
                                  "content": Path(file_path).read_text()})
                except OSError:
                    continue
            primary = files[0] if files else {"path": CHRONY_CONF, "content": f"# {CHRONY_CONF} nicht lesbar"}
            self._send_json({"path": primary["path"], "content": primary["content"], "files": files})
        elif path == "/api/settings":
            schema = settings.public_schema(masked=self._read_only_key())
            schema["readonly"] = env_flag("WEB_READONLY")
            schema["auth"] = auth_public(auth_info(), getattr(self, "_ident", None))
            schema["reload"] = reload_status()
            schema["schema_version"] = settings.SCHEMA_VERSION
            schema["notes"] = settings.migration_notes(include_seen=False)
            self._send_json(schema)
        elif path == "/api/settings/notes":
            self._send_json({"schema": settings.schema_version(), "notes": settings.migration_notes()})
        elif path == "/api/backup":
            self._send_backup(query)
        elif path == "/api/backup/list":
            self._send_json({"backups": backup.stored(), "nightly": bool(settings.values().get("backup_nightly")),
                             "keep_nightly": backup.KEEP_NIGHTLY, "keep_auto": backup.KEEP_AUTO})
        elif path == "/api/settings/export":
            body = json.dumps(settings.export_values(masked=self._read_only_key()), indent=2,
                              ensure_ascii=False).encode()
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="ntp-gui-einstellungen.json"',
                        "Cache-Control": "no-store"})
        elif path == "/api/reload":
            self._send_json(reload_status())
        elif path == "/api/devices":
            self._send_json(devices.summary(settings.values()))
        elif path == "/api/hardware":
            refresh = query.get("refresh") in {"1", "true"}
            self._send_json(hardware.report(settings.values(), refresh=refresh))
        elif path == "/api/gps/calibration":
            cfg = settings.values()
            # Ohne window die letzten 24 h: über 30 Tage SQLite-Verlauf dauert es sonst Sekunden.
            window = calibration_window(query.get("window", query.get("seconds")))
            if window is None:
                self._error(HTTPStatus.BAD_REQUEST, "window muss eine Zahl ≥ 0 sein (Sekunden, höchstens "
                            f"{int(CALIBRATION_MAX_WINDOW)})")
                return
            since = time.time() - window
            # Nur Messpunkte seit der letzten Offset-Änderung: davor lief ein anderer Offset.
            not_before = gpsquality.offset_not_before(cfg)
            if not_before is not None and not_before > since:
                since = not_before
            result = historymod.calibrate(HISTORY.snapshot(since), cfg["gps_refid"],
                                          float(cfg["gps_offset"]), float(cfg["gps_delay"]))
            result["since_offset_change"] = not_before
            # Im Modus „gemessen“ gilt nicht gps_delay, sondern die gemessene Schranke.
            self._send_json(gpsquality.annotate_calibration(result, cfg))
        elif path == "/api/gps/autocal":
            self._send_json(autocal.api_status(settings.values(), fresh=query.get("fresh") != "0"))
        elif path == "/api/gps/quality":
            cfg = settings.values()
            sources = chrony.detailed_sources() if cfg.get("gps_enable") else None
            self._send_json(gpsquality.api_status(cfg, HISTORY, sources, STATE_WATCH.gps_stability()))
        elif path == "/api/gps/antenna":
            self._send_json(gpsquality.antenna_status(query.get("a"), query.get("b")))
        elif path == "/api/gnss":
            self._send_json(gnssguard.GUARD.status(settings.values()))
        elif path == "/api/holdover":
            self._send_json(holdover.api_status())
        elif path == "/api/timeline":
            # 1.6 (T7): Zustandsband 24 h, Marker darin, Tagesbericht für gestern – vorverdichtet (timeline.py).
            self._send_json(timeline.build(HISTORY, titles=clientinfo.with_display_titles))
        elif path == "/api/timeline/markers":
            self._send_json(timeline.chart_markers(env_like(query.get("range"), 86400.0),
                                                   titles=clientinfo.with_display_titles))
        elif path == "/api/timeline/at":
            at = env_like(query.get("t"), float("nan"))
            if not math.isfinite(at):
                self._send_json({"error": "t fehlt (Unix-Zeit)"}, HTTPStatus.BAD_REQUEST)
            else:
                self._send_json(timeline.moment(HISTORY, at, titles=clientinfo.with_display_titles))
        elif path == "/api/events":
            limit = int(env_like(query.get("limit"), 500))
            since = env_like(query.get("since"), 0.0) or None
            until = env_like(query.get("until"), 0.0) or None
            level = query.get("level") if query.get("level") in events.LEVELS else None
            rows = events.query(since=since, until=until, kinds=query.get("kinds") or None,
                                level=level, limit=max(1, min(limit, 5000)))
            self._send_json({"events": clientinfo.with_display_titles(rows)})
        elif path == "/api/logs":
            level = query.get("level") if query.get("level") in {"warn", "crit"} else ""
            self._send_json(diagnostics.logs(int(env_like(query.get("lines"), 500)),
                                             str(query.get("q") or ""), level))
        elif path == "/api/diagnostics/preview":
            # ?async=1 (die Seite): Bau im Hintergrund, Antwort spätestens nach JOB_WAIT – fertig
            # oder 202 mit Auftragsnummer; ?job=… fragt den Stand ab. Ohne beides wie bisher
            # (API: die Anfrage wartet, bis die Vorschau fertig ist).
            try:
                job_id = str(query.get("job") or "")
                if not job_id and str(query.get("async") or "") == "1":
                    job_id = diagnostics.start_job(settings.values(), self._diag_options(query))
                if job_id:
                    view = diagnostics.job_result(job_id, wait=diagnostics.JOB_WAIT)
                    if view is None:
                        self._send_json({"ok": False, "error": "Diese Vorschau ist nicht mehr bekannt – bitte "
                                         "neu starten."}, HTTPStatus.NOT_FOUND)
                    elif view.get("pending"):
                        self._send_json(view, HTTPStatus.ACCEPTED)
                    else:
                        self._send_json(view)
                    return
                self._send_json(diagnostics.preview_locked(settings.values(), self._diag_options(query)))
            except diagnostics.BusyError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.TOO_MANY_REQUESTS)
            except (diagnostics.LeakError, RuntimeError) as exc:
                self._leak_error(exc)
        elif path == "/api/diagnostics/bundle":
            try:
                body, filename = diagnostics.bundle_locked(settings.values(), self._diag_options(query),
                                                           reuse=str(query.get("reuse") or "") or None)
            except diagnostics.StaleError as exc:
                self._send_json({"ok": False, "stale": True, "error": str(exc)}, HTTPStatus.CONFLICT)
                return
            except (diagnostics.LeakError, RuntimeError) as exc:
                self._leak_error(exc)
                return
            # Name aus dem Zeitpunkt des Pakets (wie Ordner und MANIFEST darin), nicht des Downloads.
            self._send(HTTPStatus.OK, body, "application/gzip",
                       {"Content-Disposition": f'attachment; filename="{filename}"',
                        "Cache-Control": "no-store"})
        elif path == "/api/recording":
            self._send_json(recording_status())
        elif path == "/api/temperature":
            self._send_json(temperature_payload(query))
        elif path == "/api/leap":
            self._send_json(leap.status(settings.values(), chrony.tracking()))
        elif path == "/api/clockquality/allan":
            self._send_json(ALLAN.get())
        elif path == "/api/enforce/snippets":
            self._send_json(enforce.api_snippets(query, settings.values()))
        elif path == "/api/enforce/check":
            cfg = settings.values()
            self._send_json(enforce.api_check(query, cfg, system_info(cfg)["addresses"], chrony.tracking(),
                                              dnsfwd.api_status(cfg)))
        elif path == "/api/loops":
            self._send_json(LOOP_GUARD.status())
        elif path == "/api/dns":
            self._send_json(dnsfwd.api_status(settings.values()))
        elif path == "/api/clients/offsets":
            payload = clientmon.status()
            payload["names"] = clientinfo.names()
            self._send_json(payload)
        elif path == "/api/clients/overview":
            self._send_json(clientinfo.overview(clientmon.status()["clients"], clientinfo.all_meta()))
        elif path == "/api/clients/detail":
            seconds = env_like(query.get("range"), float(clientmon.SAMPLE_RETENTION))
            seconds = max(60.0, min(seconds, float(clientmon.SAMPLE_RETENTION)))
            try:
                # Auch Geräte, die nur chronyd kennt, haben eine Detailseite (die Liste verlinkt jedes).
                row = chrony_client_row(clientinfo.clean_ip(query.get("ip")))
                result = clientinfo.detail(query.get("ip"), settings.values(), time.time() - seconds,
                                           chrony_row=row)
            except clientinfo.MetaError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if result is None:
                self._error(HTTPStatus.NOT_FOUND, "Dieses Gerät ist (noch) nicht bekannt.")
                return
            try:
                result.update(clients3.detail_extras(result["address"], result, settings.values()))
            except Exception as exc:  # noqa: BLE001 – Clients 3 ist ein Zusatz zur Detailseite
                print(f"[web] Uhrgüte/Regeln für die Detailseite fehlgeschlagen: {exc}", flush=True)
            self._send_json(result)
        elif path == "/api/clients/troubleshoot":
            try:
                result = troubleshoot_view(query.get("ip"))
            except troubleshoot.InputError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result)
        elif path == "/api/clients/groups":
            status = clientmon.status()
            # Wie Detailseite und Uhrgüte: private Einträge (MAC, Kopffelder) – sonst fiele die
            # Software-Vermutung schwächer aus als auf der Detailseite. Ohne Messung: gespeicherter Stand.
            snap = clientmon.private_snapshot()
            self._send_json(clients3.view(snap, str(query.get("by") or "group"), clientinfo.all_meta(),
                                          clients3.rules(), clients3.quality_all(), now=time.time(),
                                          monitor_since=status.get("since"), running=bool(status.get("running"))))
        elif path == "/api/clients/quality":
            self._send_json(clients3.quality_overview(clients3.quality_all()))
        elif path == "/api/clients/rules":
            self._send_json({"rules": {ip: clients3.public_rule(r) for ip, r in clients3.rules().items()},
                             "inventory": clients3.INVENTORY.status()})
        elif path == "/api/clients/pass":
            addr = clientinfo.clean_ip(query.get("ip"))
            if addr is None:
                self._error(HTTPStatus.BAD_REQUEST, "Ungültige IP-Adresse.")
                return
            cfg = settings.values()
            data = clients3.device_pass(addr, cfg, chrony_row=chrony_client_row(addr))
            if data is None:
                self._error(HTTPStatus.NOT_FOUND, "Dieses Gerät ist (noch) nicht bekannt.")
                return
            if str(query.get("share") or "") == "1":
                try:
                    self._send_json(clients3.shared_pass(data, cfg))
                except clients3.PassLeak as exc:
                    self._error(HTTPStatus.CONFLICT, str(exc))
                return
            self._send_json(data)
        elif path == "/api/notify":
            payload = notify.api_config()
            payload["heartbeat"] = _heartbeat_status(full=True)
            self._send_json(payload)
        elif path == "/api/notify/status":
            self._send_json(notify.api_status())
        elif path == "/api/apikeys":
            self._send_json({"keys": apikeys.list(), "auth_enabled": auth_info()["enabled"]})
        elif path == "/api/v1/instance":
            self._send_json(instance.info())
        elif path == "/api/setup":
            self._send_json(setup_payload(readonly=env_flag("WEB_READONLY"), can_write=not self._read_only_key()))
        elif path == "/api/update":
            self._send_json(updatecheck.checker(VERSION).status())
        elif path == "/metrics":
            self._send(HTTPStatus.OK, build_metrics().encode(), "text/plain; version=0.0.4; charset=utf-8")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def _diag_options(self, query: dict) -> dict:
        options = diagnostics.options_from_query(query)
        options.update(version=VERSION, uptime_seconds=int(time.monotonic() - START_MONO),
                       chrony_conf=CHRONY_CONF,
                       history=HISTORY.snapshot(time.time() - 86400))
        try:
            options["allan"] = allan.compact(ALLAN.get(wait=False))  # nicht auf eine laufende Rechnung warten
        except Exception:  # nie das Paket deswegen verlieren
            options["allan"] = None
        return options

    def _send_backup(self, query: dict) -> None:
        """GET /api/backup: neue Sicherung (oder mit name= eine gespeicherte) als Download."""
        headers = {"Cache-Control": "no-store"}  # nosniff kommt mit SECURITY_HEADERS
        name = query.get("name")
        if name is not None:
            path = backup.stored_path(name)
            if path is None:
                self._error(HTTPStatus.NOT_FOUND, "Diese gespeicherte Sicherung gibt es nicht (mehr).")
                return
            headers["Content-Disposition"] = f'attachment; filename="ntp-gui-{name}"'
            self._send_file(path, "application/gzip", headers)
            return
        # Nur eine neue Sicherung gleichzeitig: Jede legt bis zur Auslieferung eine volle Kopie im
        # Datenverzeichnis ab – viele langsam gelesene Downloads füllten sonst den Speicher.
        if not BACKUP_DOWNLOAD_SLOT.acquire(blocking=False):
            self._error(HTTPStatus.TOO_MANY_REQUESTS,
                        "Es wird gerade schon eine Sicherung erstellt oder heruntergeladen – bitte warten.")
            return
        try:
            dest = backup.download_path()
            try:
                manifest = backup.create(dest, VERSION)
                headers["Content-Disposition"] = f'attachment; filename="{backup.file_name(manifest["created"])}"'
                self._send_file(dest, "application/gzip", headers)
            finally:
                try:
                    os.unlink(dest)
                except OSError:
                    pass
        finally:
            BACKUP_DOWNLOAD_SLOT.release()

    def _csrf_upload_ok(self, ident: dict | None) -> bool:
        """Wie _csrf_ok, aber für den Upload einer Sicherung (Body ist die .tar.gz, kein JSON).
        Schutz vor fremden Seiten: Pflicht-Kopf X-NTP-GUI (erzwingt eine CORS-Vorabfrage, die
        niemand beantwortet) und ein mitgeschickter Origin muss zum Host passen."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in ("application/gzip", "application/x-gzip", "application/octet-stream"):
            return False
        if ident is not None and ident.get("kind") == "key":
            return True
        if self.headers.get("X-NTP-GUI") != "1":
            return False
        origin = self.headers.get("Origin")
        return not origin or urlparse(origin).netloc == self.headers.get("Host", "")

    def _restore_preview(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        self.close_connection = True  # nach einem Upload immer neu verbinden (Body evtl. ungelesen)
        if length > backup.MAX_UPLOAD:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        f"Die Datei ist zu groß (höchstens {backup.MAX_UPLOAD // (1024 * 1024)} MiB).")
            return
        if length <= 0:
            self._error(HTTPStatus.BAD_REQUEST, "Keine Datei hochgeladen.")
            return
        REAPER.arm(self.connection, UPLOAD_READ_DEADLINE)
        try:
            result = backup.stage_upload(self.rfile, length)
        except backup.RestoreError as exc:
            if not REAPER.disarm(self.connection):  # Frist abgelaufen: Verbindung ist schon zu
                status = (HTTPStatus.CONFLICT if isinstance(exc, backup.RestoreBusy)
                          else HTTPStatus.UNPROCESSABLE_ENTITY)
                self._error(status, str(exc), written=False)
            return
        if REAPER.disarm(self.connection):
            backup.discard(result["token"])
            return
        self._send_json(result)

    def _leak_error(self, exc: Exception) -> None:
        # Nur Art und Fundstelle – den gefundenen Text selbst nicht noch einmal ausgeben.
        leaks = [{"kind": f.get("kind"), "path": f.get("path")} for f in getattr(exc, "findings", [])]
        self._send_json({"ok": False, "error": str(exc), "leaks": leaks}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # --- POST ----------------------------------------------------------------
    def _csrf_ok(self, ident: dict | None = None) -> bool:
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return False
        if ident is not None and ident.get("kind") == "key":
            # Einen Bearer-Schlüssel hängt kein Browser von sich aus an eine fremde Anfrage.
            return True
        if self.headers.get("X-NTP-GUI") != "1":
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if urlparse(origin).netloc != host:
                return False
        return True

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            raise ValueError("Anfrage zu groß")
        raw = self.rfile.read(length) if length else b"{}"
        reaped = REAPER.disarm(self.connection)
        if len(raw) < length or reaped:
            self.close_connection = True
            raise ValueError("Anfrage unvollständig")
        self._body_unread = False
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except RecursionError:
            raise ValueError("JSON zu tief verschachtelt") from None
        if not isinstance(data, dict):
            raise ValueError("JSON-Objekt erwartet")
        return data

    def do_POST(self) -> None:
        path, index = self._api_path(self.path)
        ident = self._identity()
        if ident is None:
            self.close_connection = True  # Body bleibt ungelesen – nicht als nächste Anfrage deuten
            self._deny_auth()
            return
        if ident["kind"] == "locked":
            self._deny_locked()
            return
        if not self._host_ok(ident):
            return
        self._note_transport(ident)
        if index:
            self._error(HTTPStatus.METHOD_NOT_ALLOWED, "GET /api/v1 beschreibt die API; hier gibt es nichts zu senden")
            return
        if not self._scope_ok(ident, "POST", path):
            self.close_connection = True
            self._deny_scope(ident, "POST", path)
            return
        upload = path == "/api/restore/preview"
        if not (self._csrf_upload_ok(ident) if upload else self._csrf_ok(ident)):
            self.close_connection = True  # ein evtl. Body bleibt ungelesen
            self._error(HTTPStatus.FORBIDDEN, "Anfrage abgelehnt (nur aus dem Dashboard heraus)")
            return
        if env_flag("WEB_READONLY"):
            self.close_connection = True
            self._error(HTTPStatus.FORBIDDEN, "Einstellungen sind gesperrt (WEB_READONLY)")
            return
        if upload:
            try:
                self._restore_preview()
            except BrokenPipeError:
                pass
            except Exception as exc:
                # Kein roher Ausnahmetext an die Seite – Einzelheiten nur ins Log.
                print(f"[backup] Prüfung der Sicherung fehlgeschlagen: {type(exc).__name__}: {exc}", flush=True)
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                            "Die Sicherung ließ sich nicht prüfen (Details im Log) – es wurde nichts geändert.")
            return
        try:
            data = self._read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            try:
                self._error(HTTPStatus.BAD_REQUEST, f"Ungültige Anfrage: {exc}")
            except OSError:
                pass  # Verbindung nach Fristablauf schon geschlossen
            return
        try:
            self._route_post(path, data, ident)
        except settings.ValidationError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc),
                        fields=getattr(exc, "fields", {}))
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._internal_error(path, exc)

    def _after_change(self, result: dict) -> dict:
        changed = result.get("changed")
        if isinstance(changed, (list, dict, set, tuple)) and "trusted_proxies" in changed:
            # Neue Proxy-Liste gilt sofort – alte HTTPS-Hinweise beruhten auf der alten.
            webtransport.WATCH.reset()
        reloaded = trigger_reload() if result.get("restart") else False
        result["reload_triggered"] = reloaded
        if result.get("restart") and not reloaded:
            result["reload_note"] = ("Gespeichert. Der Neustart der Zeitdienste konnte nicht "
                                     "ausgelöst werden – bitte den Container neu starten.")
        return result

    @staticmethod
    def _settings_event(title: str, result: dict, ident: dict) -> None:
        """Nur die Schlüssel ins Protokoll, nie die Werte (Hostnamen, Pfade …)."""
        changed = result.get("changed")
        keys = sorted(changed) if isinstance(changed, (list, dict, set, tuple)) else []
        if not keys:
            return
        data = {"keys": keys[:50], "restart": bool(result.get("restart"))}
        if ident.get("kind") == "key":
            data["api_key"] = ident.get("id")
        events.emit("settings", "info", f"{title}: {', '.join(keys[:8])}{' …' if len(keys) > 8 else ''}",
                    data, source="api" if ident.get("kind") == "key" else "web")

    def _clock_signal(self, data: dict, ident: dict) -> None:
        """POST /api/v1/clock/signal: On-Air/REC-Signal setzen. Rate-Limit je Schlüssel (alle Anmeldungen teilen sich
        einen Zähler), nur feste Werte; ins Protokoll kommt der Wechsel ohne Adresse des Aufrufers."""
        by_key = ident.get("kind") == "key"
        if not CLOCK_SIGNAL_RATE.allow(f"key:{ident.get('id')}" if by_key else "session"):
            self._send_json({"error": f"Zu viele Anfragen – höchstens {CLOCK_SIGNAL_RATE.rate} je Sekunde."},
                            HTTPStatus.TOO_MANY_REQUESTS, {"Retry-After": "1"})
            return
        try:
            state, ttl = clocksignal.parse(data)
        except clocksignal.SignalError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), states=list(clocksignal.STATES))
            return
        by = {"source": "api" if by_key else "web", "api_key": ident.get("id") if by_key else None}
        result = CLOCK_SIGNAL.set(state, ttl, by)
        # Mit Ablaufzeit: Ein Zeitgeber liest den Zustand, sobald sie um ist – so steht „aus“ auch dann rechtzeitig
        # im Protokoll, wenn kein Bildschirm abfragt. Ohne Ablaufzeit wird er abgestellt.
        _signal_timer("expiry", result["expires_in"] + 0.05 if result["expires_in"] else None, clock_signal)
        expired_by = result.pop("expired_by")
        if result.pop("expired"):   # war schon abgelaufen, aber noch nicht eingetragen
            signal_audit(signal_expired_entry(expired_by))
        changed, ttl_changed = result.pop("changed"), result.pop("ttl_changed")
        if changed or ttl_changed:
            # Auch derselbe Zustand mit anderer Ablaufzeit steht im Protokoll: Wer eine Ablaufzeit setzt, verkürzt
            # oder aufhebt, bestimmt, wann das Signal ausgeht.
            signal_audit({"state": state, "ttl": result["expires_in"], **by,
                          "reason": None if changed else "ttl_changed"})
        self._send_json(result)

    def _trust_proxy(self, data: dict, ident: dict) -> None:
        """1.5.4: „Als vertrauenswürdigen Proxy eintragen“ aus dem HTTPS-Hinweis.

        Die Anfrage nennt nur die Kennung des Hinweises; die Adresse kommt aus der eigenen Liste
        beobachteter Proxys (webtransport.WATCH) – nie aus der Anfrage. Eingetragen wird genau diese
        eine Adresse (/32 bzw. /128), kein Netz."""
        peer = webtransport.WATCH.untrusted_peer(str(data.get("id") or ""))
        if peer is None:
            self._error(HTTPStatus.CONFLICT, "Diesen Proxy hat ntp-gui in den letzten 24 Stunden nicht (mehr) "
                        "gesehen – lade die Übersicht neu.")
            return
        network = webtransport.TransportWatch.host_network(peer)
        current = [str(item) for item in (settings.values().get("trusted_proxies") or [])]
        if any(webtransport.parse_ip(peer) in net for net in webtransport.parse_networks(current)):
            webtransport.WATCH.reset()
            self._send_json({"changed": [], "restart": False, "network": network, "already": True,
                             "trusted_proxies": current})
            return
        result = settings.save({"trusted_proxies": current + [network]})
        self._settings_event("Vertrauenswürdigen Proxy eingetragen", result, ident)
        result = self._after_change(result)
        webtransport.WATCH.reset()  # auch, wenn sich nichts geändert hat: die Lage beginnt neu
        result["network"] = network
        result["trusted_proxies"] = settings.values().get("trusted_proxies")
        self._send_json(result)

    @staticmethod
    def _chrony_accepts(changes: dict, defaults=None) -> None:
        """Vor dem Speichern: Lehnte chronyd die Konfiguration mit diesen Werten ab, wird nichts gespeichert
        (sonst stünde der Wert in settings.json und gälte beim nächsten Start)."""
        problem = confgen.check_changes(changes, defaults)
        if problem:
            raise settings.ValidationError(f"chronyd würde diese Konfiguration ablehnen ({problem}) – nichts "
                                           "gespeichert, die bisherige Einstellung bleibt.")

    def _route_post(self, path: str, data: dict, ident: dict | None = None) -> None:
        ident = ident or {"kind": "open"}
        if path in {"/api/settings", "/api/settings/preview"}:
            # „changes“ (Dashboard) oder „values“ (so beschreibt es /api/v1); „defaults“: Schlüssel, die
            # auf ihren Standard zurückgehen („zurücksetzen“ im Dashboard, wirkt erst mit dem Speichern).
            changes = data.get("changes", data.get("values"))
            defaults = data.get("defaults")
            if changes is None and defaults:
                changes = {}
            if not isinstance(changes, dict) or not (changes or defaults):
                raise settings.ValidationError("Keine Änderungen übergeben")
            if path == "/api/settings/preview":
                # Prüft wie Speichern, rendert mit confgen – schreibt nichts, startet nichts neu.
                # Kein Pfad aus der Anfrage: verglichen wird mit den Dateien, die confgen selbst schreibt.
                self._send_json(confgen.preview(changes, defaults))
                return
            self._chrony_accepts(changes, defaults)
            result = settings.save(changes, defaults)
            self._settings_event("Einstellungen geändert", result, ident)
            self._send_json(self._after_change(result))
        elif path == "/api/settings/reset":
            keys = data.get("keys")
            if not isinstance(keys, list) or not keys:
                raise settings.ValidationError("Keine Einstellungen zum Zurücksetzen übergeben")
            result = settings.reset([str(k) for k in keys])
            self._settings_event("Einstellungen zurückgesetzt", result, ident)
            self._send_json(self._after_change(result))
        elif path == "/api/settings/import":
            values = data.get("values")
            if not isinstance(values, dict):
                raise settings.ValidationError("Datei enthält keine Einstellungen")
            # Export mit Leserecht: gekürzte Werte (z. B. DoH-Pfad) nicht über die echten schreiben.
            masked = data.get("masked")
            values = {k: v for k, v in values.items()
                      if not (isinstance(masked, list) and k in masked)}
            # Auch Sicherungen älterer Versionen: erst auf das aktuelle Schema bringen.
            values, notes = settings.migrate_import({"schema": data.get("schema", 1), "values": values})
            if values:
                self._chrony_accepts(values)
            result = settings.save(values) if values else {"changed": [], "restart": False}
            self._settings_event("Einstellungen importiert", result, ident)
            result = self._after_change(result)
            result["notes"] = notes
            self._send_json(result)
        elif path == "/api/restore/apply":
            try:
                result = backup.apply(data.get("token"), VERSION, emit=events.emit)
            except backup.RestoreError as exc:
                self._error(HTTPStatus.CONFLICT, str(exc))
                return
            self._settings_event("Einstellungen wiederhergestellt", result, ident)
            onboarding.restored()  # Sicherung auf frischer Installation: „Einrichtung prüfen“ statt Assistent
            self._send_json(self._after_change(result))
        elif path == "/api/restore/cancel":
            token = data.get("token")
            backup.discard(token if isinstance(token, str) and token else "-")
            self._send_json({"ok": True})
        elif path == "/api/settings/notes/ack":
            self._send_json({"acknowledged": settings.ack_migration_notes()})
        elif path == "/api/gps/autocal/rollback":
            try:
                self._send_json(autocal.rollback(data.get("steps", 1), cfg=settings.values()))
            except autocal.AutocalError as exc:
                self._error(HTTPStatus.CONFLICT, str(exc))
        elif path in {"/api/gps/antenna", "/api/gps/bound"}:
            try:
                if path == "/api/gps/antenna":
                    self._send_json(gpsquality.antenna_action(data))
                elif data.get("action") == "reset":
                    self._send_json(gpsquality.reset(settings.values()))
                else:
                    self._error(HTTPStatus.BAD_REQUEST, "action muss „reset“ sein")
            except gpsquality.QualityError as exc:
                self._error(HTTPStatus.CONFLICT if exc.conflict else HTTPStatus.BAD_REQUEST, str(exc))
        elif path == "/api/gnss":
            try:
                self._send_json(gnssguard.GUARD.action(settings.values(), data))
            except gnssguard.GuardError as exc:
                self._error(HTTPStatus.CONFLICT if exc.conflict else HTTPStatus.BAD_REQUEST, str(exc))
        elif path == "/api/holdover":
            try:
                self._send_json(holdover.action(data))
            except holdover.HoldoverError as exc:
                self._error(HTTPStatus.CONFLICT if exc.conflict else HTTPStatus.BAD_REQUEST, str(exc))
        elif path == "/api/recording":
            action = "stop" if data.get("stop") else str(data.get("action", "start"))
            if action == "stop":
                providers.stop()
                self._send_json(recording_status())
            elif action == "start":
                try:
                    providers.start_recording(data.get("seconds", 300))
                except ValueError as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc))
                    return
                events.emit("settings", "info", "Aufzeichnung der Datenquellen gestartet",
                            {"seconds": data.get("seconds", 300)})
                self._send_json(recording_status())
            else:
                self._error(HTTPStatus.BAD_REQUEST, "action muss „start“ oder „stop“ sein")
        elif path == "/api/clients/meta":
            try:
                result = clientinfo.set_meta(data.get("ip"), data.get("name"), data.get("note"))
            except clientinfo.MetaError as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
                return
            self._send_json(result)
        elif path == "/api/clients/probe":
            try:
                self._send_json(clientinfo.probe(data.get("ip"), lambda ip: clientmon.client(ip) is not None))
            except clientinfo.ProbeLimited as exc:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc), retry_after=round(exc.retry_after))
            except clientinfo.MetaError as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
        elif path in ("/api/clients/groups", "/api/clients/groups/delete", "/api/clients/rules"):
            try:
                if path == "/api/clients/groups":
                    self._send_json(clients3.save_group(data))
                elif path == "/api/clients/groups/delete":
                    if not clients3.delete_group(data.get("id")):
                        self._error(HTTPStatus.NOT_FOUND, "Diese Gruppe gibt es nicht (mehr).")
                        return
                    self._send_json({"ok": True})
                else:
                    self._send_json(clients3.save_rule(data.get("ip"), data, emit=events.emit))
            except clients3.Clients3Error as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
        elif path == "/api/notify/channels":
            try:
                self._send_json({"channel": notify.save_channel(data)})
            except notify.NotifyError as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
        elif path == "/api/notify/channels/delete":
            if not notify.delete_channel(str(data.get("id", ""))):
                self._error(HTTPStatus.NOT_FOUND, "Diesen Kanal gibt es nicht (mehr)")
                return
            self._send_json({"ok": True})
        elif path == "/api/notify/test":
            try:
                self._send_json(notify.send_test(str(data.get("id", ""))))
            except notify.TestRateLimited as exc:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
            except notify.NotifyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
        elif path == "/api/notify/heartbeat/test":
            try:
                result = heartbeat.pinger(heartbeat_state).test()
            except heartbeat.TestRateLimited as exc:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
                return
            except heartbeat.TestBusy as exc:
                self._error(HTTPStatus.CONFLICT, str(exc))
                return
            except heartbeat.PingError as exc:
                self._error(HTTPStatus.CONFLICT, str(exc))
                return
            result = dict(result, url=heartbeat.mask_url(settings.values().get("heartbeat_url") or ""))
            # ok nur, wenn wirklich etwas angekommen ist – „nur Lebenszeichen“ bei kritisch sendet nichts.
            delivered = result.get("error") is None and result.get("last_sent") is not None
            note = "Zustand kritisch – nichts gesendet (Art: nur Lebenszeichen)" \
                if result.get("error") is None and result.get("last_sent") is None else None
            self._send_json({"ok": delivered, "error": result.get("error"), "note": note, "heartbeat": result})
        elif path == "/api/v1/clock/signal":
            self._clock_signal(data, ident)
        elif path == "/api/apikeys":
            key_id, token = apikeys.create(data.get("name"), data.get("scope"),
                                           open_mode=ident.get("kind") == "open")
            entry = next((k for k in apikeys.list() if k["id"] == key_id), {})
            self._send_json({"id": key_id, "token": token, "name": entry.get("name"),
                             "scope": entry.get("scope"), "scope_label": entry.get("scope_label")})
        elif path == "/api/apikeys/revoke":
            if not apikeys.revoke(str(data.get("id", ""))):
                self._error(HTTPStatus.NOT_FOUND, "Diesen Schlüssel gibt es nicht (mehr)")
                return
            self._send_json({"ok": True})
        elif path == "/api/instance/rotate":
            instance.rotate()  # schreibt selbst ein Ereignis
            self._send_json(instance.info())
        elif path == "/api/auth":
            self._set_auth(data)
        elif path == "/api/auth/logout":
            # Basic-Auth kennt kein Abmelden: Die Seite bringt den Browser über LOGOUT_PATH dazu, die Angaben zu
            # vergessen. Der Server streicht nur seinen Merker; derselbe Kopf bleibt gültig, bis das Passwort
            # geändert wird.
            header = self.headers.get("Authorization", "")
            info = auth_info()
            AUTH_CACHE.forget(auth_cache_key(header, info))
            self._send_json({"ok": True, "probe": LOGOUT_PATH, "probe_user": LOGOUT_USER})
        elif path == "/api/apikeys/keep":
            if ident.get("kind") != "basic":
                # Behalten bestätigt die Prüfung beim ersten Passwort – das darf nur, wer es kennt.
                self._error(HTTPStatus.FORBIDDEN, "Schlüssel behalten geht nur mit Anmeldung (Passwort)")
                return
            if not apikeys.keep(str(data.get("id", ""))):
                self._error(HTTPStatus.NOT_FOUND, "Diesen Schlüssel gibt es nicht (mehr)")
                return
            self._send_json({"ok": True})
        elif path == "/api/web/proxies/trust":
            self._trust_proxy(data, ident)
        elif path == "/api/setup":
            try:
                result = onboarding.action(data.get("action"))
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({k: result.get(k) for k in ("install", "done", "hint_closed", "checklist_closed")})
        elif path == "/api/reload":
            self._send_json({"reload_triggered": trigger_reload()})
        else:
            self._error(HTTPStatus.NOT_FOUND, "Unbekannte Aktion")


def env_like(raw, default: float) -> float:
    """Zahl aus einem Abfrage- oder Umgebungswert; leer, ungültig oder nicht endlich (nan, inf) → default."""
    try:
        value = float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


# Netzfehler einer einzelnen Verbindung: Gegenstelle weg, Route weg (WLAN-Gerät schläft), Zeitüberschreitung.
QUIET_ERRNOS = frozenset(getattr(errno, name) for name in (
    "ECONNRESET", "EPIPE", "ECONNABORTED", "ETIMEDOUT", "EHOSTUNREACH", "ENETUNREACH", "ENETDOWN", "EHOSTDOWN")
    if hasattr(errno, name))


def quiet_network_error(exc: BaseException | None) -> bool:
    """Abbruch durch das Netz (kein Programmfehler)? Dann kein Traceback ins Log."""
    if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError,
                        socket.timeout)):
        return True
    return isinstance(exc, OSError) and exc.errno in QUIET_ERRNOS


class QuietHTTPServer(ThreadingHTTPServer):
    """Browser, die eine Verbindung mittendrin abbrechen (Tab zu, Reload, Handy im Standby),
    sind Alltag und kein Fehler. Ohne das hier schreibt socketserver für jeden Abbruch einen
    vollständigen Traceback ins Log – mehrere Threads gleichzeitig und ineinander verschränkt.
    Dazu zählen auch „No route to host“ und Co.: ein Gerät, das mitten in der Antwort das WLAN
    verlässt. Alles andere wird weiter vollständig protokolliert."""

    def handle_error(self, request, client_address):
        if quiet_network_error(sys.exc_info()[1]):
            return
        super().handle_error(request, client_address)

    max_connections = MAX_CONNECTIONS_DEFAULT

    def __init__(self, *args, **kwargs):
        self._conn_lock = threading.Lock()
        self._conns: dict = {}           # Socket -> (Quellschlüssel oder None, ausgenommen?)
        self._per_source: dict[str, int] = {}
        self.active_connections = 0
        self.rejected_connections = 0
        super().__init__(*args, **kwargs)

    def _classify(self, client_address) -> tuple[str | None, bool]:
        """(Schlüssel für die Grenze je Quelle oder None, von der eigenen Maschine?)"""
        address = webtransport.parse_ip(client_address[0] if client_address else "")
        if _is_local_peer(address):
            return None, True
        try:
            trusted = webtransport.parse_networks(settings.values().get("trusted_proxies"))
        except Exception:
            trusted = []
        if address is not None and any(address.version == net.version and address in net for net in trusted):
            return None, False
        return _source_key(address), False

    def _admit(self, request, client_address) -> bool:
        key, local = self._classify(client_address)
        limit = self.max_connections if local else self.max_connections - local_reserve(self.max_connections)
        with self._conn_lock:
            if self.active_connections >= limit:
                return False
            if key is not None and self._per_source.get(key, 0) >= per_source_limit(self.max_connections):
                return False
            self.active_connections += 1
            if key is not None:
                self._per_source[key] = self._per_source.get(key, 0) + 1
            self._conns[request] = (key, local or key is None)
        return True

    def _release(self, request) -> None:
        with self._conn_lock:
            entry = self._conns.pop(request, None)
            if entry is None:
                return
            self.active_connections -= 1
            key = entry[0]
            if key is not None:
                left = self._per_source.get(key, 0) - 1
                if left > 0:
                    self._per_source[key] = left
                else:
                    self._per_source.pop(key, None)

    def busy_for(self, request) -> bool:
        """Soll diese Verbindung nur die kurze Frist bis zur ersten Anfrage bekommen?"""
        with self._conn_lock:
            entry = self._conns.get(request)
            return (entry is not None and not entry[1]
                    and self.active_connections > self.max_connections * BUSY_SHARE)

    def process_request(self, request, client_address):
        # Ein Thread je Verbindung, aber höchstens max_connections zugleich und je Quelle nur ein Teil davon.
        # Ist kein Platz frei, wird die neue Verbindung sofort geschlossen – ohne Thread, ohne Antwort (eine
        # Antwort kostete wieder Zeit und Speicher).
        if not self._admit(request, client_address):
            self.rejected_connections += 1
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except RuntimeError:
            # Thread ließ sich nicht starten (Prozessgrenze erreicht): Platz freigeben, Verbindung schließen –
            # der Server selbst läuft weiter.
            self._release(request)
            self.rejected_connections += 1
            self.shutdown_request(request)
        except BaseException:
            self._release(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release(request)

    def server_activate(self):
        # Lauschender Socket nicht blockierend: select() meldet eine wartende Verbindung, der Client
        # bricht sie aber vor accept() ab (RST) – ein blockierendes accept() wartete dann bis zur
        # nächsten Verbindung, und shutdown() hinge so lange. So liefert accept() BlockingIOError,
        # das socketserver still übergeht. Angenommene Verbindungen bleiben blockierend (mit Timeout).
        super().server_activate()
        self.socket.setblocking(False)


class QuietHTTPServer6(QuietHTTPServer):
    """Dasselbe für eine IPv6-Adresse in WEB_BIND. „::“ nimmt auch IPv4 an: IPV6_V6ONLY wird
    ausdrücklich auf 0 gesetzt (wie http.server.DualStackServer), sonst entschiede die Sysctl
    net.ipv6.bindv6only des Hosts, ob IPv4 und der Docker-Healthcheck noch durchkommen."""
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (OSError, AttributeError):
            pass  # Plattform ohne IPV6_V6ONLY: Standard des Systems gilt
        super().server_bind()


def make_server(bind: str, port: int) -> QuietHTTPServer:
    """Server für WEB_BIND (IPv4 oder IPv6, auch in [ ]) – mit verständlicher Meldung, falls das scheitert."""
    bind = bind.strip().strip("[]")
    cls = QuietHTTPServer6 if ":" in bind else QuietHTTPServer
    try:
        return cls((bind, port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            hint = "Port belegt – WEB_PORT anpassen oder den belegenden Dienst beenden."
        elif exc.errno in (errno.EACCES, errno.EPERM):
            hint = ("Port unter 1024 braucht CAP_NET_BIND_SERVICE oder einen höheren WEB_PORT "
                    "(z. B. 8080).")
        else:
            hint = "WEB_BIND prüfen (gibt es die Adresse auf diesem Host, ist IPv6 aktiv?)."
        raise SystemExit(f"[web] {bind}:{port} nicht nutzbar ({exc}). {hint}") from None


def _binds_everywhere(bind: str) -> bool:
    return bind.strip().strip("[]") in {"0.0.0.0", "::", ""}


def startup_auth_warnings(bind: str) -> list[str]:
    """Hinweise zur Anmeldung beim Start: gesperrt, offen auf allen Adressen, schwaches Passwort, Angaben unklar."""
    out: list[str] = []
    env = env_credentials()
    info = auth_info()
    if env["from_file"] and os.environ.get("WEB_PASSWORD"):
        out.append("[web] Hinweis: WEB_PASSWORD und WEB_PASSWORD_FILE sind gesetzt – es gilt WEB_PASSWORD_FILE.")
    if env["defaulted_user"]:
        out.append("[web] Hinweis: Nur ein Passwort aus der Umgebung, kein WEB_USER – Benutzername ist „admin“.")
    if info.get("code") == "settings_unreadable":
        out.append(f"[web] WARNUNG: {info['reason']}. Das Dashboard bleibt GESPERRT (nur /healthz und /readyz antworten); "
                   "mit WEB_USER und WEB_PASSWORD ist es mit Anmeldung erreichbar, Speichern bleibt gesperrt.")
    elif env["error"]:
        if info["enabled"]:
            out.append(f"[web] WARNUNG: {env['error']} – es gilt das im Dashboard gesetzte Passwort.")
        else:
            out.append(f"[web] WARNUNG: {env['error']}. Das Dashboard bleibt GESPERRT (nur /healthz und /readyz antworten), "
                       "bis WEB_USER und WEB_PASSWORD (oder WEB_PASSWORD_FILE) vollständig gesetzt sind.")
    elif info.get("locked"):
        out.append("[web] WARNUNG: WEB_REQUIRE_AUTH=true, aber kein Zugang gesetzt. Das Dashboard bleibt GESPERRT "
                   "(nur /healthz und /readyz antworten). WEB_USER und WEB_PASSWORD (oder WEB_PASSWORD_FILE) setzen und den "
                   "Container neu erstellen.")
    elif not info["enabled"] and _binds_everywhere(bind):
        out.append("[web] WARNUNG: Dashboard OHNE PASSWORT auf allen Adressen (WEB_BIND=" + (bind or "0.0.0.0") + "). "
                   "Jeder, der Port und Adresse erreicht, kann alles ändern, ein eigenes Passwort setzen und "
                   "API-Schlüssel anlegen. Im eigenen LAN ist das so gewollt; ist der Server aus dem Internet "
                   "erreichbar (VPS), WEB_REQUIRE_AUTH=true und WEB_USER/WEB_PASSWORD setzen.")
    if info.get("gui_overridden"):
        out.append("[web] WARNUNG: Im Dashboard ist ein eigenes Passwort gesetzt, es gilt aber nicht, solange "
                   "WEB_PASSWORD bzw. WEB_PASSWORD_FILE gesetzt ist – angemeldet wird mit Benutzer "
                   f"„{env['user']}“ und dem Passwort aus der Umgebung. Soll das Dashboard-Passwort gelten, "
                   "entferne WEB_PASSWORD (und WEB_USER) aus der Compose-Datei.")
    if info.get("source") == "env":
        weak = settings.password_weakness(env["password"], env["user"])
        if weak:
            out.append(f"[web] WARNUNG: Das Passwort aus der Umgebung ist schwach ({weak}). Empfohlen: mindestens "
                       f"{settings.RECOMMENDED_LENGTH} Zeichen, kein Beispielwert.")
    return out


def main() -> None:
    port = env_number("WEB_PORT", 8080, int, minimum=1)
    bind = os.environ.get("WEB_BIND", "0.0.0.0")
    for line in startup_auth_warnings(bind):
        print(line, flush=True)

    for entry in settings.env_allowed_hosts():
        if entry.startswith("*.") and settings.shared_suffix(entry[2:]):
            print(f"[web] WARNUNG: WEB_ALLOWED_HOSTS enthält „{entry}“ – das gibt auch fremde Namen "
                  f"unter {entry[2:]} frei (DNS-Rebinding möglich). Besser nur den eigenen Namen "
                  f"eintragen, z. B. meinzeit.{entry[2:]}", flush=True)
    # 1.6 (T3): Erststart oder Update festschreiben, bevor irgendetwas anderes ins Datenverzeichnis schreibt.
    onboarding.remember()
    # 1.9: Bekannte Quellen für die Anmeldebremse über Neustarts halten (nur HMAC-Werte, keine Adressen).
    authguard.GUARD.persist(os.path.join(settings.DATA_DIR, ".anmeldung-bekannt.json"))
    try:
        apikeys.prepare()  # Migration jetzt: Schlüssel aus der Zeit ohne Passwort markieren
    except Exception as exc:
        print(f"[web] API-Schlüssel: Datenbank nicht vorbereitet ({type(exc).__name__})", flush=True)
    # 1.5.3: Folgen eines laufenden Holdover-Tests (keine Quelle ausgewählt …) nur als „info“, ohne Meldung.
    events.add_filter(holdover.event_filter)
    holdover.configure(trigger_reload=trigger_reload)
    # Schranke und Offset stehen nur in chrony.conf: nur chronyd neu laden (gpsd und dnsfwd laufen weiter).
    autocal.configure(history=HISTORY, trigger_reload=trigger_reload_chronyd)
    gpsquality.configure(history=HISTORY, trigger_reload=trigger_reload_chronyd,
                         net_distance=lambda: gpsquality.nts_distance(chrony.detailed_sources()))
    threading.Thread(target=collector, daemon=True, name="collector").start()
    threading.Thread(target=loop_guard_runner, daemon=True, name="loopguard").start()
    threading.Thread(target=hardware_refresher, daemon=True, name="hardware").start()
    # 1.5: GNSS-Störungen, GPS-Sperre und Holdover-Test im festen 10-s-Takt (eigener Thread).
    threading.Thread(target=gnssguard.run, args=(settings.values,), daemon=True, name="gnssguard").start()
    threading.Thread(target=events_ingester, daemon=True, name="events").start()
    backup.cleanup_staging()  # Reste eines abgebrochenen Uploads vom letzten Lauf
    backup.cleanup_downloads(0.0)
    # 1.6: nächtliche Sicherung ins Datenverzeichnis (Schalter backup_nightly, Standard aus).
    threading.Thread(target=backup.nightly_runner, args=(settings.values, VERSION), daemon=True,
                     name="backup").start()
    notify.start(VERSION)  # eigener Thread je Kanal; ohne angelegte Kanäle geht nichts hinaus
    updatecheck.start(VERSION)  # opt-in; ausgeschaltet keine Anfrage nach außen
    heartbeat.start(heartbeat_state)  # opt-in (heartbeat_url); ohne Adresse keine Verbindung
    diagnostics.own_hostnames()  # eigenen FQDN schon jetzt im Hintergrund auflösen (Host-Prüfung)
    # Folgt clientmon_enable/ntp_port ohne Neustart.
    threading.Thread(target=clientmon.watch, args=(settings.values,), daemon=True, name="clientmon-watch").start()

    def save_and_exit(*_):
        clientmon.stop()
        HISTORY.save(force=True)
        notify.flush()  # Position der verteilten Ereignisse – sonst kommt Zugestelltes nach dem Neustart doppelt
        if _CLIENT_ALARMS["loaded"]:
            _client_alarms_persist(restamp=True)
        heartbeat.flush()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, save_and_exit)

    wanted = env_number("WEB_MAX_CONNECTIONS", MAX_CONNECTIONS_DEFAULT, int, minimum=8)
    QuietHTTPServer.max_connections, pids_note = pids_capped_connections(wanted)
    if pids_note:
        print(pids_note, flush=True)
    server = make_server(bind, port)
    server.daemon_threads = True
    info = auth_info()
    note = {"env": "mit Basic-Auth (Umgebungsvariable)", "gui": "mit Passwort aus dem Dashboard",
            None: "GESPERRT – kein Zugang eingerichtet" if info.get("locked") else "ohne Passwort"}[info["source"]]
    shown = f"[{bind.strip().strip('[]')}]" if ":" in bind else bind
    print(f"[web] Dashboard auf http://{shown}:{port} ({note})", flush=True)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        clientmon.stop()
        HISTORY.save(force=True)
        server.server_close()


if __name__ == "__main__":
    main()
