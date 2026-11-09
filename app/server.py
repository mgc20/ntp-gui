"""HTTP-Server für Dashboard und API – nur Python-Standardbibliothek.

Lesend: Status, Verlauf, Konfiguration, Geräte, Metriken.
Schreibend (POST): Einstellungen, Passwort, Neustart der Zeitdienste.
Versionierte API: /api/v1/<pfad> ist ein Alias der bisherigen Pfade (apiv1.py).

Schutz der schreibenden Routen:
  * ist ein Zugang gesetzt (Env oder Dashboard), gilt Basic-Auth für alles
    außer /healthz – oder ein API-Schlüssel („Authorization: Bearer ntpg_…“)
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
    jeder Name. /healthz ist immer offen;
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
import apiv1
import autocal
import backup
import gnssguard
import gpsquality
import holdover
import loopguard
import chrony
import clientinfo
import clientmon
import clients3
import devices
import diagnostics
import dnsfwd
import enforce
import events
import gps
import hardware
import history as historymod
import insights
import instance
import leap
import notify
import onboarding  # vor dem eigenen Code: merkt sich, ob das Datenverzeichnis schon Daten hatte
import providers
import ptp
import settings
import confgen
import statewatch
import pistate
import thermal
import timeline
import updatecheck
import webtransport

STATIC_DIR = Path(__file__).with_name("static")
CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")
RUN_DIR = os.environ.get("NTPGUI_RUN_DIR", "/run/ntp-gui")
START_MONO = time.monotonic()  # Laufzeit nach monotoner Uhr – ein Uhrsprung verfälscht sie nicht
MAX_BODY = 64 * 1024
VERSION = os.environ.get("NTPGUI_VERSION", "1.6.1")
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
ALLAN = allan.Cache(lambda: HISTORY.series("freq", since=time.time() - allan.MAX_SPAN))

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
               "(secret_set), nie im Klartext; Adressen mit Pfad/Abfrage nur gekürzt (url_hidden).", ["channels", "types", "levels", "kinds", "defaults", "limits",
                                                 "dashboard_url", "running"])
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
               "dann ohne Quellennamen.",
               ["t1", "t2", "synchronised", "level", "accuracy", "stratum", "leap", "leap_next", "source_kind",
                "source", "public"])

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
CLOCK_PUBLIC_PATHS = {"/clock", "/api/v1/time", "/static/app.css", "/static/clock.css",
                      "/static/js/clock.js", "/static/js/clocksync.js", "/static/js/clockkit.js",
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
        try:
            # Als PTP-Grandmaster die angekündigte Uhrqualität an den Zustand von chrony anpassen.
            ptp.update_grandmaster(settings.values(), chrony.tracking(), chrony.detailed_sources())
        except Exception as exc:
            print(f"[web] Grandmaster-Daten nicht gesetzt: {exc}", flush=True)
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


def client_alarms() -> None:
    """Alarm-Schwelle für Client-Uhren (clients_alarm_ms) prüfen – Ereignis „clients“."""
    try:
        threshold = settings.values().get("clients_alarm_ms") or 0
        if not threshold:
            STATE_WATCH.clients({}, 0)
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
    """Übernimmt die Ereignisse des Supervisors (RUN_DIR/events.jsonl) ins Protokoll."""
    stop = stop or threading.Event()
    path = os.path.join(RUN_DIR, "events.jsonl")
    while True:
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
    DNS-Weiterleiter meldet einen bekannten Ausfall nicht bei jeder Anpassung erneut (Diagnose 1.6.0)."""
    return _request_reload(RELOAD_CHRONYD_REQUEST)


def _request_reload(name: str) -> bool:
    supervisor = os.path.join(RUN_DIR, "supervisor.pid")
    if not os.path.exists(supervisor):
        return False  # kein Supervisor (Entwicklung, Tests) – niemand würde die Datei lesen
    path = os.path.join(RUN_DIR, name)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write(f"{time.time():.3f}\n")
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def auth_info() -> dict:
    if os.environ.get("WEB_USER") and os.environ.get("WEB_PASSWORD"):
        return {"enabled": True, "source": "env", "user": os.environ["WEB_USER"]}
    stored = settings.stored_credentials()
    if stored:
        return {"enabled": True, "source": "gui", "user": stored["user"]}
    return {"enabled": False, "source": None, "user": None}


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
            "auth": auth_info(),
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
    status["insights"] = combine_insights(insights.build(status, cfg),
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


def clock_status(tracking: dict, cfg: dict | None = None) -> dict:
    """Ampel und Quelle für /clock – ohne Namen, Adressen oder Einstellungen."""
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
    return {"synchronised": synced, "running": running, "level": level, "accuracy": accuracy,
            "stratum": stratum, "leap": tracking.get("leap_status") or None, "source_kind": kind}


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


def _clock_leap_next(cfg: dict) -> str | None:
    """Datum der nächsten angekündigten Schaltsekunde (Beginn des neuen TAI−UTC, „2017-01-01“) für /clock.

    Öffentliche Information aus der leap-seconds.list (IERS Bulletin C) – kein Pfad, keine Einstellung.
    Die Uhr zeigt damit am 30.6./31.12. ein kleines Banner. Nie ein Fehler: im Zweifel None.
    """
    try:
        info = leap.status(cfg)
    except Exception:
        return None
    value = info.get("next_leap_date") if info.get("available") else None
    return value if isinstance(value, str) and len(value) == 10 else None


def time_payload(received: float, public: bool) -> dict:
    """Antwort von /api/v1/time. t2 wird so spät wie möglich genommen."""
    tracking = _clock_tracking()
    try:
        cfg = settings.values()
    except Exception:
        cfg = {}
    out = clock_status(tracking, cfg)
    out["leap_next"] = _clock_leap_next(cfg)
    out.update(t1=received, public=public,
               source=None if public else (str(tracking.get("ref_name") or "") or None))
    out["t2"] = time.time()
    return out


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
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


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
    for source in sources:
        labels = '{source="%s",mode="%s"}' % (
            _escape_label(source.get("name", "")), _escape_label(source.get("mode_label", "")))
        _metric(lines, "ntpgui_source_offset_seconds", source.get("offset"), "Offset per source", labels=labels)
        _metric(lines, "ntpgui_source_stratum", source.get("stratum"), "Stratum per source", labels=labels)
        _metric(lines, "ntpgui_source_reach_percent", source.get("reach_percent"), "Reachability per source", labels=labels)
        _metric(lines, "ntpgui_source_jitter_seconds", source.get("std_dev"), "Standard deviation per source", labels=labels)
        _metric(lines, "ntpgui_source_selected", 1 if source.get("state") == "*" else 0, "1 for the selected source", labels=labels)
        _metric(lines, "ntpgui_source_combined", 1 if source.get("state") in {"*", "+"} else 0, "1 when the source is used", labels=labels)
        _metric(lines, "ntpgui_source_authenticated", 1 if source.get("authenticated") else 0, "1 when NTS-authenticated", labels=labels)

    stats = chrony.serverstats()
    _metric(lines, "ntpgui_ntp_packets_received_total", stats.get("ntp_packets_received"), "NTP packets served", kind="counter")
    _metric(lines, "ntpgui_ntp_packets_dropped_total", stats.get("ntp_packets_dropped"), "NTP packets dropped", kind="counter")
    _metric(lines, "ntpgui_nts_ke_connections_accepted_total", stats.get("nts_ke_connections_accepted"), "NTS-KE connections accepted", kind="counter")
    _metric(lines, "ntpgui_clients", len(chrony.clients()), "Known NTP clients")

    gps_state = gps.status()
    if gps_state.get("enabled"):
        _metric(lines, "ntpgui_gps_running", 1 if gps_state.get("running") else 0, "1 when gpsd answers")
        _metric(lines, "ntpgui_gps_fix_mode", gps_state.get("mode"), "gpsd fix mode (0-3)")
        _metric(lines, "ntpgui_gps_satellites_used", gps_state.get("satellites_used"), "Satellites used for the fix")
        _metric(lines, "ntpgui_gps_satellites_seen", gps_state.get("satellites_seen"), "Satellites in view")
        _metric(lines, "ntpgui_gps_hdop", gps_state.get("hdop"), "Horizontal dilution of precision")
        _metric(lines, "ntpgui_gps_snr_avg_db", gps_state.get("snr_avg"), "Average SNR of used satellites")
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
        self.clock = clock

    def check(self, header: str, verify) -> bool:
        key = hashlib.sha256(header.encode()).hexdigest()
        now = self.clock()
        with self._lock:
            if self._ok.get(key, 0) > now:
                return True
        if verify():
            with self._lock:
                self._ok = {k: v for k, v in self._ok.items() if v > now}
                self._ok[key] = now + 300
            return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._ok.clear()


AUTH_CACHE = AuthCache()


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
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CSP,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ntp-gui"
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_IDLE_TIMEOUT  # StreamRequestHandler.setup(): settimeout() auf der Verbindung

    def handle_one_request(self) -> None:
        # Leerlauf (bis REQUEST_IDLE_TIMEOUT) ohne Frist abwarten; die Lesefrist beginnt erst mit dem
        # ersten Byte – sonst schlösse sie still offene Keep-alive-Verbindungen schon nach 60 s.
        try:
            if not self.rfile.peek(1):
                self.close_connection = True  # Gegenstelle hat geschlossen
                return
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
        header = self.headers.get("Authorization", "")
        if header[:7].lower() == "bearer ":
            key = apikeys.verify(header[7:].strip())
            return {"kind": "key", "scope": key["scope"], "id": key["id"]} if key else None
        if not auth_info()["enabled"]:
            return {"kind": "open"}
        return {"kind": "basic"} if self._authorised() else None

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
        if needed == "admin" and ident["scope"] != "admin":
            return False
        return apikeys.allows(ident["scope"], method)

    def _deny_scope(self, ident: dict, method: str, path: str) -> None:
        needed = apiv1.required_scope(method, path)
        if needed == "session":
            text = ("Das geht nur mit Benutzer und Passwort, nicht mit einem API-Schlüssel – "
                    "so kann ein entwendeter Schlüssel weder das Passwort ändern noch neue Schlüssel ausstellen.")
        else:
            text = (f"Dieser API-Schlüssel hat das Recht „{ident.get('scope')}“; hier ist "
                    f"„{needed}“ nötig.")
        self._error(HTTPStatus.FORBIDDEN, text, scope_required=needed)

    def _authorised(self) -> bool:
        info = auth_info()
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

        def verify() -> bool:
            if info["source"] == "env":
                ok_user = hmac.compare_digest(user.encode(), os.environ["WEB_USER"].encode())
                ok_pass = hmac.compare_digest(password.encode(), os.environ["WEB_PASSWORD"].encode())
                return ok_user & ok_pass
            stored = settings.stored_credentials()
            if not stored:
                return False
            return (hmac.compare_digest(user.encode(), stored["user"].encode())
                    & settings.verify_password(password, stored["hash"]))

        return AUTH_CACHE.check(header + "|" + str(info["source"]), verify)

    def _deny_auth(self) -> None:
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
        path = (STATIC_DIR / name).resolve()
        if not path.is_file() or STATIC_DIR.resolve() not in path.parents:
            self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, path.read_bytes(), content_type, {"Cache-Control": "no-cache"})

    def _query(self) -> dict:
        return {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}

    # --- GET -----------------------------------------------------------------
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        received = time.time()   # t1 für /api/v1/time – so früh wie möglich
        path, index = self._api_path(self.path)
        if path in CLOCK_PUBLIC_PATHS and self._clock_public():
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
            healthy = bool(chrony.tracking())
            self._send_json({"status": "ok" if healthy else "degraded", "chrony": healthy},
                            HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        ident = self._identity()
        if ident is None:
            self._deny_auth()
            return
        if not self._host_ok(ident):
            return
        if not self._scope_ok(ident, "GET", path):
            self._deny_scope(ident, "GET", path)
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
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

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
        elif path == "/clock":
            self._serve_static("clock.html")
        else:
            self._serve_static(path[len("/static/"):])

    def _route_get(self, path: str, received: float | None = None) -> None:
        query = self._query()
        if path in ("/clock", "/api/v1/time"):
            self._route_clock(path, received or time.time(), public=False)
        elif path == "/":
            self._serve_static("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/status":
            status = build_status()
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
            schema["auth"] = auth_info()
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
            self._send_json(notify.api_config())
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
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        name = query.get("name")
        if name is not None:
            path = backup.stored_path(name)
            if path is None:
                self._error(HTTPStatus.NOT_FOUND, "Diese gespeicherte Sicherung gibt es nicht (mehr).")
                return
            headers["Content-Disposition"] = f'attachment; filename="ntp-gui-{name}"'
            self._send_file(path, "application/gzip", headers)
            return
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
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc), written=False)
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
        data = json.loads(raw.decode("utf-8") or "{}")
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
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

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
            except notify.NotifyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
        elif path == "/api/apikeys":
            key_id, token = apikeys.create(data.get("name"), data.get("scope"))
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
            if auth_info()["source"] == "env":
                raise settings.ValidationError("Der Zugang ist per WEB_USER/WEB_PASSWORD festgelegt "
                                               "und lässt sich hier nicht ändern.")
            if data.get("clear"):
                settings.set_credentials("", None)
            else:
                settings.set_credentials(str(data.get("user", "")), str(data.get("password", "")))
            AUTH_CACHE.clear()
            self._send_json({"ok": True, "auth": auth_info()})
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


def main() -> None:
    port = env_number("WEB_PORT", 8080, int, minimum=1)
    bind = os.environ.get("WEB_BIND", "0.0.0.0")
    if bool(os.environ.get("WEB_USER", "").strip()) != bool(os.environ.get("WEB_PASSWORD", "")):
        print("[web] WARNUNG: WEB_USER und WEB_PASSWORD müssen beide gesetzt sein – "
              "das Dashboard läuft ohne Authentifizierung.", flush=True)

    for entry in settings.env_allowed_hosts():
        if entry.startswith("*.") and settings.shared_suffix(entry[2:]):
            print(f"[web] WARNUNG: WEB_ALLOWED_HOSTS enthält „{entry}“ – das gibt auch fremde Namen "
                  f"unter {entry[2:]} frei (DNS-Rebinding möglich). Besser nur den eigenen Namen "
                  f"eintragen, z. B. meinzeit.{entry[2:]}", flush=True)
    # 1.6 (T3): Erststart oder Update festschreiben, bevor irgendetwas anderes ins Datenverzeichnis schreibt.
    onboarding.remember()
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
    diagnostics.own_hostnames()  # eigenen FQDN schon jetzt im Hintergrund auflösen (Host-Prüfung)
    # Folgt clientmon_enable/ntp_port ohne Neustart.
    threading.Thread(target=clientmon.watch, args=(settings.values,), daemon=True, name="clientmon-watch").start()

    def save_and_exit(*_):
        clientmon.stop()
        HISTORY.save(force=True)
        notify.flush()  # Position der verteilten Ereignisse – sonst kommt Zugestelltes nach dem Neustart doppelt
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, save_and_exit)

    server = make_server(bind, port)
    server.daemon_threads = True
    note = {"env": "mit Basic-Auth (Umgebungsvariable)", "gui": "mit Passwort aus dem Dashboard",
            None: "ohne Passwort"}[auth_info()["source"]]
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
