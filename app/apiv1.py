"""Versionierte API /api/v1 – eine stabile Schnittstelle für Skripte und Integrationen.

/api/v1/<pfad> ist ein Alias der bisherigen Pfade (/api/v1/status == /api/status).
Die alten Pfade bleiben, weil das Dashboard sie nutzt; Skripte sollten /api/v1
verwenden: Was hier steht, ändert sich innerhalb von v1 nur abwärtskompatibel
(neue Schlüssel ja, umbenannte oder entfernte nein).

server.py nutzt:
    legacy = apiv1.resolve(path)        # "/api/v1/status" -> "/api/status", sonst None
    scope = apiv1.required_scope(method, legacy_or_path)
    apiv1.describe()                    # Beschreibung für GET /api/v1

Rechte (scope):
    public   – ohne Anmeldung (/healthz)
    read     – Anmeldung oder API-Schlüssel mit Recht „read“ oder „admin“
    admin    – Anmeldung oder API-Schlüssel mit Recht „admin“
    session  – nur mit Anmeldung (Benutzer/Passwort), nie per API-Schlüssel:
               Zugang und Schlüssel selbst verwalten. So kann ein entwendeter
               Schlüssel weder das Passwort ändern noch sich neue Schlüssel
               ausstellen – Widerrufen reicht, um ihn loszuwerden.
"""

from __future__ import annotations

from typing import Any

PREFIX = "/api/v1"
VERSION = "1"

# (Methode, v1-Pfad, bisheriger Pfad oder None = nur v1, Recht, Beschreibung, Antwortschlüssel)
ENDPOINTS: list[dict[str, Any]] = []


def endpoint(method: str, path: str, legacy: str | None, scope: str, description: str,
             keys: list[str] | None = None, query: dict[str, str] | None = None) -> None:
    """Trägt einen Endpunkt ein (auch für andere Module, die eigene Endpunkte mitbringen)."""
    assert path.startswith("/") and scope in {"public", "read", "admin", "session"}
    method = method.upper()
    for entry in ENDPOINTS:
        if entry["method"] == method and entry["path"] == path:
            ENDPOINTS.remove(entry)
            break
    ENDPOINTS.append({"method": method, "path": path, "legacy": legacy, "scope": scope,
                      "description": description, "response_keys": keys or [],
                      "query": query or {}})


# --- Lesen ----------------------------------------------------------------------
endpoint("GET", "/status", "/api/status", "read",
         "Gesamtzustand: Systemuhr, Quellen, Clients, GPS, PTP, Dienste und Hinweise – "
         "dieselben Daten wie die Übersicht im Dashboard.",
         ["system", "tracking", "sources", "activity", "serverstats", "clients", "client_count",
          "ptp", "gps", "gps_summary", "nts_server", "services", "chrony_running", "update", "config", "ui",
          "insights"])
endpoint("GET", "/history", "/api/history", "read",
         "Verlauf der Messwerte für Diagramme, auf höchstens „points“ Punkte verdichtet.",
         ["samples", "interval"],
         {"range": "Zeitraum in Sekunden (Standard 3600, 0 = alles)",
          "points": "Höchstzahl der Punkte, 10–3000 (Standard 600)"})
endpoint("GET", "/config", "/api/config", "read",
         "Die erzeugten Konfigurationsdateien (chrony.conf, ptp4l.conf) im Klartext.",
         ["path", "content", "files"])
endpoint("GET", "/settings", "/api/settings", "read",
         "Alle Einstellungen mit Wert, Herkunft (Dashboard, Umgebung, Standard) und Erklärung.",
         ["sections", "fields", "env_only", "storage", "readonly", "auth", "reload"])
endpoint("GET", "/settings/export", "/api/settings/export", "read",
         "Die im Dashboard gespeicherten Einstellungen als Datei zum Sichern (ohne Passwort).",
         ["schema", "values"])
endpoint("GET", "/settings/notes", "/api/settings/notes", "read",
         "Was sich beim Update an deinen Einstellungen geändert hat (Migrationshinweise).",
         ["schema", "notes"])
endpoint("GET", "/reload", "/api/reload", "read",
         "Stand des letzten Neustarts der Zeitdienste nach einer Änderung.",
         ["state"])
endpoint("GET", "/devices", "/api/devices", "read",
         "Gefundene Geräte: serielle Schnittstellen, PPS, PTP-Uhren, Netzwerkkarten.",
         ["serial", "pps", "ptp_clocks", "interfaces", "ptp_checks", "ethtool"])
endpoint("GET", "/hardware", "/api/hardware", "read",
         "Hardware-Check: was diese Maschine für genaue Zeit kann und was fehlt.",
         [], {"refresh": "1 = neu prüfen statt Zwischenstand"})
endpoint("GET", "/gps/calibration", "/api/gps/calibration", "read",
         "Messung der GPS-Verspätung gegen die Netzwerkquellen mit Vorschlag für Offset/Delay.",
         ["samples", "current_offset", "current_delay", "duration_seconds", "status", "message",
          "bias", "spread", "suggested_offset", "suggested_delay", "series"],
         {"window": "nur die letzten so vielen Sekunden auswerten"})
endpoint("GET", "/events", "/api/events", "read",
         "Ereignisprotokoll (Quellenwechsel, Fix verloren, Neustarts, Änderungen), neueste zuerst. "
         "Client-Alarme tragen im Titel nur die Adresse; display_title nennt den aktuellen eigenen Namen.",
         ["events"],
         {"since": "ab Unix-Zeit", "until": "bis Unix-Zeit", "kinds": "Arten, mit Komma getrennt",
          "level": "Mindeststufe: info, warn oder crit", "limit": "höchstens so viele (1–5000)"})
endpoint("GET", "/instance", None, "read",
         "Zufällige Kennung dieser Instanz (nicht aus der Hardware abgeleitet).",
         ["instance_id", "since", "note"])
endpoint("GET", "/metrics", "/metrics", "read",
         "Messwerte im Prometheus-Textformat (kein JSON).", [])

# --- Ändern -------------------------------------------------------------------
endpoint("POST", "/settings", "/api/settings", "admin",
         "Einstellungen ändern. Body: {\"values\": {schlüssel: wert}}. Startet bei Bedarf die "
         "Zeitdienste neu.", ["changed", "restart", "reload_triggered"])
endpoint("POST", "/settings/reset", "/api/settings/reset", "admin",
         "Im Dashboard gespeicherte Werte entfernen. Body: {\"keys\": [...]}.",
         ["changed", "restart", "reload_triggered"])
endpoint("POST", "/settings/import", "/api/settings/import", "admin",
         "Gesicherte Einstellungen einspielen (Format wie /settings/export, auch ältere Versionen).",
         ["changed", "restart", "reload_triggered"])
endpoint("POST", "/settings/notes/ack", "/api/settings/notes/ack", "admin",
         "Update-Hinweise als gelesen markieren.", ["acknowledged"])
endpoint("POST", "/reload", "/api/reload", "admin",
         "Zeitdienste neu laden (Konfiguration neu erzeugen und Dienste neu starten).",
         ["reload_triggered"])

# --- Nur mit Anmeldung (nie per API-Schlüssel) -----------------------------------
endpoint("POST", "/auth", "/api/auth", "session",
         "Benutzer und Passwort des Dashboards setzen oder entfernen.", ["ok", "auth"])
endpoint("GET", "/apikeys", "/api/apikeys", "session",
         "API-Schlüssel auflisten (Name, Recht, zuletzt benutzt – nie das Geheimnis).", ["keys"])
endpoint("POST", "/apikeys", "/api/apikeys", "session",
         "API-Schlüssel anlegen. Body: {\"name\": …, \"scope\": \"read\"|\"admin\"}. Der Schlüssel "
         "steht nur in dieser einen Antwort.", ["id", "token", "name", "scope"])
endpoint("POST", "/apikeys/revoke", "/api/apikeys/revoke", "session",
         "API-Schlüssel widerrufen. Body: {\"id\": …}.", ["ok"])
endpoint("POST", "/instance/rotate", "/api/instance/rotate", "session",
         "Neue zufällige Instanz-Kennung erzeugen.", ["instance_id", "since", "note"])

# --- Öffentlich ---------------------------------------------------------------
endpoint("GET", "/healthz", "/healthz", "public",
         "Lebenszeichen für Docker/Monitoring: läuft chronyd?", ["status", "chrony"])


def _normalise(path: str) -> str:
    path = (path or "").split("?", 1)[0]
    return path.rstrip("/") or "/"


def resolve(path: str) -> str | None:
    """/api/v1/<x> → bisheriger Pfad. Nur-v1-Endpunkte → derselbe v1-Pfad. Sonst None.

    "/api/v1" selbst gibt None zurück – dafür ist describe() da (is_index()).
    """
    path = _normalise(path)
    if not path.startswith(PREFIX + "/"):
        return None
    sub = path[len(PREFIX):]
    for entry in ENDPOINTS:
        if entry["path"] == sub:
            return entry["legacy"] or path
    return None


def is_index(path: str) -> bool:
    return _normalise(path) == PREFIX


def required_scope(method: str, path: str) -> str:
    """Nötiges Recht für Methode + Pfad (v1- oder bisheriger Pfad).

    Unbekannte Pfade: GET/HEAD → read, alles andere → admin. Pfade, die mit
    /api/apikeys oder /api/auth beginnen, sind immer „session“ – auch künftige.
    """
    method = "GET" if str(method).upper() == "HEAD" else str(method).upper()
    path = _normalise(path)
    if path == PREFIX:
        return "read"
    legacy = resolve(path) or path
    sub = path[len(PREFIX):] if path.startswith(PREFIX + "/") else None
    for entry in ENDPOINTS:
        if entry["method"] != method:
            continue
        if (sub is not None and entry["path"] == sub) or entry["legacy"] == legacy:
            return entry["scope"]
    if any(legacy == p or legacy.startswith(p + "/") for p in ("/api/apikeys", "/api/auth")):
        return "session"
    return "read" if method == "GET" else "admin"


def describe() -> dict:
    """JSON-Beschreibung aller v1-Endpunkte für GET /api/v1."""
    return {
        "version": VERSION,
        "base": PREFIX,
        "auth": {
            "basic": "Benutzer und Passwort des Dashboards (HTTP Basic) – darf alles.",
            "bearer": "Header „Authorization: Bearer ntpg_…“ mit einem API-Schlüssel aus "
                      "Einstellungen → Dashboard. Recht „read“: nur GET. Recht „admin“: auch "
                      "POST, aber nicht „session“-Endpunkte.",
            "csrf": "Mit API-Schlüssel ist kein X-NTP-GUI-Header nötig; POST braucht "
                    "Content-Type: application/json.",
            "note": "Ist kein Passwort gesetzt, ist das Dashboard offen und Schlüssel werden "
                    "nicht gebraucht.",
        },
        "stability": "Innerhalb von v1 kommen höchstens neue Felder hinzu; nichts wird "
                     "umbenannt oder entfernt.",
        "endpoints": [{"method": e["method"], "path": PREFIX + e["path"], "scope": e["scope"],
                       "description": e["description"], "response_keys": list(e["response_keys"]),
                       "query": dict(e["query"])}
                      for e in ENDPOINTS],
    }
