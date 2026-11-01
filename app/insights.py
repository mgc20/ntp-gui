"""Hinweise im Klartext: was gerade los ist und was man tun kann.

Jeder Hinweis: level (ok|info|warn|crit), title, text, optional action
(Seite im Dashboard, auf die verlinkt wird). Die Regeln arbeiten nur auf den
Daten, die /api/status ohnehin liefert – dadurch sind sie leicht testbar.
"""

from __future__ import annotations

from typing import Any


def _ms(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    value = abs(seconds)
    if value >= 1:
        return f"{seconds:.2f} s"
    if value >= 1e-3:
        return f"{seconds * 1e3:.1f} ms"
    return f"{seconds * 1e6:.0f} µs"


NTS_CERT_WARN_DAYS = 14


def nts_server_insights(nts: dict[str, Any]) -> list[dict[str, Any]]:
    """Eigener NTS-Server: fehlende/unlesbare Dateien und ablaufendes Zertifikat."""
    if not nts.get("enabled"):
        return []
    out: list[dict[str, Any]] = []

    def add(level, title, text, key):
        out.append({"level": level, "title": title, "text": text, "action": "settings", "key": key})

    missing = [path for path, ok in ((nts.get("cert"), nts.get("cert_exists")),
                                     (nts.get("key"), nts.get("key_exists"))) if not ok]
    unreadable = [path for path, exists, ok in (
        (nts.get("cert"), nts.get("cert_exists"), nts.get("cert_readable")),
        (nts.get("key"), nts.get("key_exists"), nts.get("key_readable", True))) if exists and not ok]
    if missing:
        add("warn", "NTS-Server ohne Zertifikat",
            f"Der NTS-Server ist eingeschaltet, aber {' und '.join(p or '(kein Pfad)' for p in missing)} "
            "fehlt. chrony startet den NTS-Server deshalb nicht – normales NTP läuft weiter. Zertifikat "
            "und Schlüssel nach /config legen (Volume) oder die Pfade in den Einstellungen anpassen.",
            "nts_server_files")
    elif unreadable:
        add("warn", "NTS-Zertifikat nicht lesbar",
            f"{' und '.join(unreadable)} existiert, lässt sich aber nicht lesen. Meist stimmen die "
            "Dateirechte nicht: Die Dateien müssen für den Container lesbar sein (z. B. chmod 640 "
            "und passende Gruppe).", "nts_server_files")
    days = nts.get("days_left")
    if isinstance(days, (int, float)):
        if days < 0:
            add("crit", "NTS-Zertifikat abgelaufen",
                f"Das Zertifikat des NTS-Servers ist seit {abs(days):.0f} Tagen abgelaufen. Clients "
                "lehnen den Schlüsselaustausch ab und bekommen keine abgesicherte Zeit mehr. Ein neues "
                "Zertifikat ablegen; nach dem Speichern bzw. Neustart lädt chrony es.",
                "nts_cert_expired")
        elif days < NTS_CERT_WARN_DAYS:
            add("warn", "NTS-Zertifikat läuft bald ab",
                f"Das Zertifikat des NTS-Servers ist nur noch {days:.0f} Tage gültig. Danach lehnen "
                "die Clients den Schlüsselaustausch ab. Rechtzeitig erneuern – chrony lädt es beim "
                "nächsten Neustart der Zeitdienste.", "nts_cert_expiring")
    return out


def build(status: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(level, title, text, action=None, key=None):
        out.append({"level": level, "title": title, "text": text, "action": action,
                    "key": key or title})

    tracking = status.get("tracking") or {}
    sources = status.get("sources") or []
    system = status.get("system") or {}

    if not status.get("chrony_running"):
        add("crit", "chronyd antwortet nicht",
            "Der Zeitdienst läuft nicht oder startet gerade neu. Ohne ihn bekommen die Clients "
            "keine Zeit. Das Container-Log nennt den Grund.", key="chrony_down")
        return out

    if system.get("clock_control") is False:
        add("warn", "Die Systemuhr wird nicht geregelt",
            "chronyd läuft mit „-x“: Es fehlt die Berechtigung SYS_TIME oder die Uhrensteuerung "
            "wurde abgeschaltet. Der Server verteilt dann die Uhrzeit des Hosts, ohne sie zu "
            "korrigieren. Abhilfe: „cap_add: [SYS_TIME]“ in der Compose-Datei.",
            key="no_clock_control")

    if tracking.get("synchronised"):
        ref = next((s for s in sources if s.get("state") == "*"), None)
        name = (ref or {}).get("hostname") or (ref or {}).get("name") or tracking.get("ref_name")
        add("ok", f"Synchron mit {name}",
            f"Stratum {tracking.get('stratum')}: Die Systemuhr folgt {name}, aktuelle "
            f"Abweichung {_ms(tracking.get('system_time_offset'))}. "
            f"Clients im LAN bekommen Stratum {tracking.get('stratum')}.", key="synced")
    elif tracking.get("local_reference"):
        add("warn", "Inselbetrieb – keine Quelle erreichbar",
            "Keine Zeitquelle ist gerade nutzbar. Der Server liefert seine eigene Uhrzeit mit "
            f"Stratum {tracking.get('stratum')} aus, damit das LAN einheitlich bleibt. Prüfe die "
            "Internetverbindung, die Quellen und – falls vorhanden – das GPS.",
            action="sources", key="island")
    else:
        add("warn", "Noch nicht synchron",
            "chrony sammelt gerade Messwerte. Das dauert nach einem Start einige Sekunden bis "
            "wenige Minuten.", key="syncing")

    network = [s for s in sources if s.get("mode") in {"^", "="}]
    unreachable = [s for s in network if not s.get("reach")]
    for source in unreachable:
        name = source.get("hostname") or source.get("name")
        add("warn", f"{name} antwortet nicht",
            "Die letzten acht Anfragen an diese Quelle blieben ohne Antwort. Ursachen: Name nicht "
            "auflösbar, Port 123/udp nach außen gesperrt, Server außer Betrieb.",
            action="sources", key=f"unreach:{source.get('name')}")
    usable = len([s for s in sources if s.get("reach")])
    if cfg.get("ntp_minsources", 1) > 1 and usable < cfg["ntp_minsources"]:
        add("warn", "Zu wenige Quellen für die Mindestanzahl",
            f"Eingestellt sind mindestens {cfg['ntp_minsources']} übereinstimmende Quellen, "
            f"erreichbar sind {usable}. chrony stellt die Uhr dann nicht.",
            action="settings", key="minsources")

    for source in network:
        auth = source.get("auth") or {}
        if auth.get("mode") == "NTS":
            name = source.get("hostname") or source.get("name")
            if not source.get("authenticated") and (auth.get("nak") or not auth.get("cookies")):
                add("warn", f"NTS mit {name} klappt nicht",
                    "Der Schlüsselaustausch (TCP-Port 4460) ist fehlgeschlagen oder liefert keine "
                    "Cookies. Häufige Ursachen: Port 4460 nach außen gesperrt, Uhr beim Start so "
                    "falsch, dass das TLS-Zertifikat abgelehnt wird, Server ohne NTS.",
                    action="sources", key=f"nts:{source.get('name')}")

    out.extend(nts_server_insights(status.get("nts_server") or {}))

    gps = status.get("gps") or {}
    if gps.get("enabled"):
        refclock = next((s for s in sources if s.get("mode") == "#"
                         and s.get("name") == cfg.get("gps_refid")), None)
        if not gps.get("running"):
            add("crit", "gpsd antwortet nicht",
                "Der GPS-Dienst läuft nicht. Ist der Empfänger per „devices:“ in den Container "
                "gereicht und der Pfad in den Einstellungen richtig?",
                action="gps", key="gpsd_down")
        elif not gps.get("has_fix"):
            add("warn", "GPS hat noch keinen Fix",
                f"{gps.get('satellites_seen', 0)} Satelliten in Sicht, {gps.get('satellites_used', 0)} "
                "genutzt. Für einen Fix braucht der Empfänger mindestens vier, mit freier Sicht "
                "zum Himmel. Nach einem Kaltstart kann das bis zu 15 Minuten dauern.",
                action="gps", key="gps_nofix")
        elif refclock:
            state = refclock.get("select_state")
            offset = refclock.get("offset")
            if state == "falseticker":
                add("warn", "GPS widerspricht den anderen Quellen",
                    f"Die GPS-Zeit weicht um {_ms(offset)} von den Netzwerkquellen ab. Das ist "
                    "fast immer die feste Verspätung des USB-Empfängers. Lösung: GPS kalibrieren.",
                    action="gps", key="gps_falseticker")
            elif state in {"large_distance", "distance"}:
                add("info", "GPS wird nur beobachtet, nicht genutzt",
                    f"chrony bewertet das GPS als zu unsicher: Die angenommene Unsicherheit "
                    f"(Delay {cfg.get('gps_delay')} s) ist viel größer als die der "
                    f"Netzwerkquellen. Mit Internet ist das unkritisch. Soll das GPS mitzählen, "
                    f"im Kalibrier-Assistenten Offset und Delay übernehmen.",
                    action="gps", key="gps_distance")
            elif state in {"best", "combined"}:
                add("ok", "GPS wird genutzt",
                    f"Das GPS fließt in die Zeit ein (Abweichung {_ms(offset)}).", key="gps_used")
            if abs(offset or 0) > 0.02 and state in {"best", "combined", "not_combined"}:
                add("info", "GPS-Offset noch nicht kalibriert",
                    f"Das GPS liegt {_ms(offset)} neben der Systemzeit. Der Assistent auf der "
                    "GPS-Seite misst den richtigen Korrekturwert.", action="gps", key="gps_uncal")

    ptp = status.get("ptp") or {}
    if ptp.get("enabled") and not ptp.get("running"):
        add("crit", "ptp4l antwortet nicht",
            "PTP ist eingeschaltet, aber ptp4l läuft nicht oder antwortet nicht. Die PTP-Seite "
            "prüft die Voraussetzungen.", action="ptp", key="ptp_down")

    ui = status.get("ui") or {}
    if not (ui.get("storage") or {}).get("persistent", True):
        add("warn", "Einstellungen gehen beim Neuerstellen verloren",
            "/var/lib/chrony liegt nicht auf einem Volume. Im Dashboard gespeicherte "
            "Einstellungen und der Verlauf verschwinden, wenn der Container neu erstellt wird. "
            "In der Compose-Datei ein Volume für /var/lib/chrony anlegen.", key="storage")
    if not (ui.get("auth") or {}).get("enabled") and not ui.get("readonly"):
        add("info", "Dashboard ohne Passwort",
            "Jeder im LAN kann die Einstellungen ändern. Ein Passwort lässt sich unter "
            "Einstellungen → Dashboard setzen.", action="settings", key="no_auth")

    if status.get("client_count") == 0 and tracking.get("synchronised"):
        add("info", "Noch keine Clients",
            "Bisher hat kein Gerät nach der Zeit gefragt. Verteile die Adresse dieses Servers "
            "per DHCP Option 42 – die Clients-Seite zeigt, wie.", action="clients",
            key="no_clients")
    return out
