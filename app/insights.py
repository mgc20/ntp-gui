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
            f"{'fehlen' if len(missing) > 1 else 'fehlt'}. chrony startet den NTS-Server deshalb nicht – normales NTP läuft weiter. Zertifikat "
            "und Schlüssel nach /config legen (Volume) oder die Pfade in den Einstellungen anpassen.",
            "nts_server_files")
    elif unreadable:
        add("warn", "NTS-Zertifikat nicht lesbar",
            f"{' und '.join(unreadable)} "
            f"{'existieren, lassen sich' if len(unreadable) > 1 else 'existiert, lässt sich'} "
            "aber nicht lesen. Meist stimmen die "
            "Dateirechte nicht: Die Dateien müssen für den Container lesbar sein (z. B. chmod 640 "
            "und passende Gruppe).", "nts_server_files")
    name = nts.get("name") or ""
    if name and nts.get("name_matches_cert") is False:
        cert_names = ", ".join(nts.get("names") or []) or "keine"
        add("warn", "Zertifikat passt nicht zum Namen",
            f"Zertifikat passt nicht zum Namen {name}: Es gilt nur für {cert_names}. Clients, die "
            f"„{name}“ ansprechen, brechen den TLS-Schlüsselaustausch (NTS-KE) ab, weil sie den "
            "Namen gegen das Zertifikat prüfen. Ein Zertifikat für diesen Namen (oder ein "
            "passendes Wildcard-Zertifikat) eintragen oder den öffentlichen Namen korrigieren.",
            "nts_name_mismatch")
    # Nur, wenn der Status das Feld überhaupt kennt (chrony.nts_server_status ab 1.2.0)
    # und sonst alles stimmt – ein fehlendes Zertifikat ist dann wichtiger.
    elif "name" in nts and not name and not missing and not unreadable:
        add("info", "NTS-Server ohne öffentlichen Namen",
            "Es ist kein öffentlicher Name eingetragen. Nach dem Schlüsselaustausch schicken "
            "die Clients ihre NTP-Pakete dann an dieselbe Adresse wie den Schlüsselaustausch. "
            "Im LAN ohne Umweg passt das. Läuft NTS-KE (TCP 4460) aber über einen Reverse "
            "Proxy wie Nginx Proxy Manager oder Zoraxy, landen die NTP-Pakete (UDP 123) beim "
            "Proxy, der sie meist nicht weiterreicht. Dann den öffentlichen Namen setzen – "
            "chrony nennt ihn den Clients per „ntsntpserver“ – und UDP 123 direkt (Portfreigabe "
            "im Router) an diesen Server leiten.", "nts_no_name")
    days = nts.get("days_left")
    if isinstance(days, (int, float)):
        if days < 0:
            add("crit", "NTS-Zertifikat abgelaufen",
                f"Das Zertifikat des NTS-Servers ist seit {abs(days):.0f} Tagen abgelaufen. Clients "
                "lehnen den Schlüsselaustausch ab und bekommen keine abgesicherte Zeit mehr. Ein neues "
                "Zertifikat ablegen – ntp-gui bemerkt die geänderte Datei innerhalb von etwa einer "
                "Minute und startet chronyd neu, damit er es lädt.",
                "nts_cert_expired")
        elif days < NTS_CERT_WARN_DAYS:
            add("warn", "NTS-Zertifikat läuft bald ab",
                f"Das Zertifikat des NTS-Servers ist nur noch {days:.0f} Tage gültig. Danach lehnen "
                "die Clients den Schlüsselaustausch ab. Rechtzeitig erneuern – sobald sich die Datei "
                "ändert, startet ntp-gui chronyd automatisch neu (chrony liest Zertifikate nur "
                "beim Start).", "nts_cert_expiring")
    return out


def ptp_role_insights(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """PTP-Rolle passt nicht zu phc2sys/Zeitstempeln: die Warnungen, die confgen
    sonst nur ins Container-Log schreibt."""
    if not (cfg.get("ptp_enable") and cfg.get("ptp_interface")):
        return []
    import confgen  # spät importieren: insights bleibt ohne confgen testbar
    import settings
    full = {key: field["default"] for key, field in settings.FIELDS.items()}
    full.update(cfg)
    mode = full.get("ptp_mode")
    software = full.get("ptp_time_stamping") == "software"
    plan = confgen.phc2sys_plan(full, {})
    out: list[dict[str, Any]] = []

    def add(title, text, key):
        out.append({"level": "warn", "title": title, "text": text, "action": "settings", "key": key})

    if mode == "master" and not software and not full.get("phc2sys_enable"):
        add("PTP-Grandmaster verteilt eine frei laufende Uhr",
            "Dieser Server ist PTP-Grandmaster mit Hardware-Zeitstempeln, aber phc2sys ist aus. "
            "ptp4l verteilt dann die Uhr der Netzwerkkarte, und die läuft frei – NICHT die Zeit "
            "von chrony/GPS. Schalte in den Einstellungen „Systemuhr und PTP-Uhr koppeln "
            "(phc2sys)“ ein (PHC2SYS_ENABLE=true).", "ptp_gm_free_running")
    elif mode == "master" and plan["start"] and plan["nocontrol"]:
        add("PTP-Grandmaster folgt der Kartenuhr",
            f"Mit den eigenen phc2sys-Optionen „{full.get('phc2sys_options')}“ stellt phc2sys die "
            "Systemuhr nach der frei laufenden Uhr der Netzwerkkarte, chronyd läuft mit -x und "
            "GPS/NTP werden nicht genutzt. Lass die phc2sys-Optionen leer (automatisch) oder "
            f"trage „{confgen.PHC2SYS_AUTO['master']}“ ein.", "ptp_gm_phc2sys_options")
    elif mode == "auto" and software:
        add("PTP-Rolle „automatisch“ mit Software-Zeitstempeln",
            "Wird dieser Server PTP-Slave, stellen ptp4l und chronyd dieselbe Systemuhr und "
            "überschreiben sich gegenseitig. Stelle die Rolle fest auf „Grandmaster“ (verteilt "
            "die Zeit von chrony) oder „Slave“ (chronyd liefert nur aus).", "ptp_auto_software")
    elif mode == "auto" and plan["start"] and plan["nocontrol"]:
        add("PTP-Rolle „automatisch“ mit phc2sys",
            "phc2sys stellt die Systemuhr nach PTP und chronyd läuft deshalb mit -x. Gewinnt "
            "dieser Server die PTP-Wahl und wird selbst Grandmaster, regelt niemand mehr die "
            "Systemuhr – NTP und PTP verteilen dann eine driftende Zeit. Stelle die Rolle fest "
            "auf „Grandmaster“ oder „Slave“.", "ptp_auto_phc2sys")
    return out


DNS_MODE_HINT = ("Stell unter System → Einstellungen → Quellen → „DNS für ntp-gui“ eigene Server ein – "
                 "am robustesten "
                 "DNS-over-TLS oder DNS-over-HTTPS, weil die auch eine Umleitung von Port 53 nicht "
                 "trifft. Alternativ nimmst du ntp-gui im DNS-Server von der Umschreibung aus.")


def _own_loop_sources(sources: list[dict], own: list[str]) -> list[str]:
    """Quellen mit Namen, deren Adresse eine eigene ist (chrony fragt sich selbst)."""
    import ipaddress
    mine = set()
    for addr in own or []:
        try:
            mine.add(ipaddress.ip_address(str(addr).split("%")[0]))
        except ValueError:
            continue
    out = []
    for source in sources or []:
        if source.get("mode") not in {"^", "="} or not source.get("hostname"):
            continue
        try:
            ip = ipaddress.ip_address(str(source.get("name") or ""))
        except ValueError:
            continue
        if ip in mine or ip.is_loopback:
            out.append(str(source["hostname"]))
    return out


def dns_insights(dns: dict[str, Any], cfg: dict[str, Any], sources: list[dict] | None = None,
                 own_addresses: list[str] | None = None, enforce_loops: list[dict] | None = None,
                 enforce_used: bool = False) -> list[dict[str, Any]]:
    """DNS für ntp-gui: Zustand des Weiterleiters und Schleifen durch DNS-Umschreibung."""
    out: list[dict[str, Any]] = []

    def add(level, title, text, key):
        out.append({"level": level, "title": title, "text": text, "action": "settings", "key": key})

    dns = dns or {}
    mode = dns.get("mode") or cfg.get("dns_mode") or "system"
    if mode == "system":
        loops = list(dict.fromkeys(_own_loop_sources(sources or [], own_addresses or [])
                                   + [str(l.get("host")) for l in enforce_loops or []
                                      if l.get("host") and l.get("cause", "dns") == "dns"]))
        if loops:
            add("warn", "Schleife durch DNS-Umschreibung",
                f"{', '.join(loops)} zeigt per DNS auf ntp-gui selbst – chronyd fragt dann sich selbst und "
                "hat keine echte Quelle. Ursache ist fast immer eine DNS-Umschreibung (AdGuard Home, "
                "Pi-hole, dnsmasq) ohne Ausnahme für ntp-gui. " + DNS_MODE_HINT, "dns_loop")
        elif enforce_used:
            import enforce
            hosts = [str(s.get("host")) for s in cfg.get("ntp_sources") or [] if s.get("host")]
            risky = enforce.rewritten_sources(hosts, cfg.get("enforce_hostnames") or [])
            if risky:
                add("info", "Schleifengefahr durch DNS-Umschreibung",
                    f"Deine Quelle{'n' if len(risky) > 1 else ''} {', '.join(risky)} "
                    f"{'stehen' if len(risky) > 1 else 'steht'} auch in der Liste „Zeitserver erzwingen“. "
                    "Schreibt dein DNS-Server diese Namen auf ntp-gui um und nutzt ntp-gui denselben DNS, "
                    "fragt chronyd sich selbst. " + DNS_MODE_HINT, "dns_loop_risk")
        return out

    if dns.get("effective_mode") == "system":
        add("warn", "DNS-Modus ohne Server",
            f"Eingestellt ist „{dns.get('mode_label') or mode}“, aber es ist kein Server eingetragen. "
            "ntp-gui nutzt deshalb weiter den System-DNS. Trag unter System → Einstellungen → Quellen → "
            "„DNS für ntp-gui“ "
            "mindestens einen Server ein.", "dns_no_servers")
        return out
    if dns.get("error"):
        add("warn", "DNS-Weiterleiter startet nicht",
            f"{dns['error']}. ntp-gui nutzt so lange den System-DNS.", "dns_error")
    resolv = dns.get("resolv") or {}
    if resolv.get("state") == "readonly":
        add("warn", "resolv.conf ist schreibgeschützt",
            "Der DNS-Weiterleiter läuft, aber /etc/resolv.conf lässt sich nicht auf ihn umstellen "
            "(z. B. „read_only: true“). chronyd fragt deshalb weiter den System-DNS. Abhilfe: in der "
            "Compose-Datei beim Dienst „dns: 127.0.0.1“ eintragen – dann zeigt Docker selbst auf den "
            "Weiterleiter. Wichtig dabei: Dann gibt es keinen System-DNS mehr, der die Namen der "
            "DoT/DoH-Server auflösen könnte. Trag sie unter „Feste Adressen für DoT/DoH“ ein "
            "(z. B. dns.quad9.net=9.9.9.9) oder nimm den Modus „Eigene DNS-Server“ mit IP-Adressen.",
            "dns_resolv_readonly")
    elif resolv.get("state") == "error" or (resolv.get("state") == "local" and resolv.get("message")):
        add("warn", "resolv.conf-Problem", f"{resolv.get('message')}.", "dns_resolv_error")
    stats = dns.get("stats") or {}
    loop_recent = _recent(stats.get("loop_last"), dns.get("time"))
    unpinned = [str(u.get("host")) for u in dns.get("upstreams") or []
                if u.get("host") and u.get("pinned") is False
                and (u.get("bootstrap_failed") or loop_recent)]
    if mode in ("dot", "doh") and unpinned:
        add("warn", "Adresse des DoT/DoH-Servers nicht ermittelbar",
            f"ntp-gui kann die Adresse von {', '.join(dict.fromkeys(unpinned))} nicht über den "
            "System-DNS herausfinden – typisch bei „dns: 127.0.0.1“ in der Compose-Datei, weil der "
            "System-DNS dann wieder ntp-gui selbst ist. Trag die Adresse unter System → Einstellungen → "
            "Quellen → „DNS für ntp-gui“ → Erweitert → „Feste Adressen für DoT/DoH“ ein, "
            "z. B. dns.quad9.net=9.9.9.9. "
            "Das Zertifikat wird weiter gegen den Namen geprüft.", "dns_pin_needed")
    if dns.get("nts_note"):
        add("info", "NTS hängt an einem einzigen DNS-Server", str(dns["nts_note"]), "dns_nts_single")
    state = dns.get("state")
    if state == "fallback":
        add("warn", "Eigene DNS-Server nicht erreichbar",
            "Keiner der eingetragenen DNS-Server hat zuletzt geantwortet. ntp-gui fragt deshalb den "
            "ursprünglichen DNS des Containers"
            + (" – unverschlüsselt" if mode in ("dot", "doh") else "")
            + ". Schreibt der Zeitserver-Namen um, droht wieder eine Schleife. Prüfe Adressen, "
            "Firewall (853/tcp für DoT, 443/tcp für DoH) und die Uhrzeit (TLS-Zertifikate).", "dns_fallback")
    elif state == "failing":
        add("crit", "Keine Namensauflösung",
            "Weder die eigenen DNS-Server noch der System-DNS antworten. chronyd kann Namen wie "
            "pool.ntp.org nicht auflösen; Quellen mit fester IP-Adresse laufen weiter.", "dns_failing")
    if loop_recent:
        add("warn", "System-DNS fragt ntp-gui zurück",
            "Anfragen, die ntp-gui weitergab, kamen in den letzten 10 Minuten bei ntp-gui selbst wieder "
            "an (z. B. Docker-DNS mit „dns: 127.0.0.1“). Sie werden abgebrochen statt zu kreisen. Der "
            "Rückfall auf den System-DNS hilft hier nicht – sorge dafür, dass die eigenen Server "
            "erreichbar sind, und trag bei DoT/DoH feste Adressen ein.", "dns_loop_fallback")
    return out


def _recent(when: Any, now: Any = None, window: float = 600.0) -> bool:
    """Liegt der Zeitpunkt (Unix-Sekunden) höchstens window Sekunden zurück?"""
    import time
    if not isinstance(when, (int, float)) or isinstance(when, bool):
        return False
    ref = now if isinstance(now, (int, float)) and not isinstance(now, bool) else time.time()
    return ref - when <= window


AUTOCAL_FIXING = {"measure", "correct", "follow", "step_wait"}


def _autocal_corrects() -> bool:
    """Misst oder korrigiert die automatische Kalibrierung gerade (letzte stündliche Entscheidung)?"""
    try:
        import autocal
        if autocal._readonly():
            return False
        phase = (autocal.load().get("last_decision") or {}).get("phase")
    except Exception:
        return False
    return phase in AUTOCAL_FIXING


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return "gut einer Minute" if seconds >= 60 else "wenigen Sekunden"
    if seconds < 3600:
        return f"{seconds // 60} min"
    hours, rest = divmod(seconds // 60, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


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
            # 1.5.4: Ohne PPS ist das GPS die Rückfallebene – tragen die Netzquellen, ist ein fehlender
            # Fix nur eine Info. Gab es vor kurzem noch einen Fix (schwacher Empfang drinnen), sagt der
            # Hinweis das, statt „noch keinen Fix“ wie nach einem Kaltstart.
            summary = status.get("gps_summary") or {}
            net_ok = any(s.get("mode") in {"^", "="} and s.get("state") in {"*", "+"} for s in sources)
            level = "info" if net_ok and not gps.get("pps") else "warn"
            seen = f"{gps.get('satellites_seen', 0)} Satelliten in Sicht, {gps.get('satellites_used', 0)} genutzt."
            last_fix = summary.get("last_fix_s")
            recent = summary.get("weak") or (isinstance(last_fix, (int, float)) and last_fix < 3600)
            carry = (" Die Netzquellen tragen die Zeit – das GPS ist nur die Rückfallebene."
                     if net_ok else " Gerade trägt keine Netzquelle – dann zählt das GPS.")
            if recent:
                ago = f" Den letzten Fix gab es vor {_ago(last_fix)}." if isinstance(last_fix, (int, float)) else ""
                add(level, "GPS gerade ohne Fix – schwacher Empfang, kommt und geht",
                    f"{seen}{ago} Drinnen oder am Fenster kommt und geht der Fix.{carry} Besserer Platz "
                    "für die Antenne: GPS-Seite → Antennen-Test.",
                    action="gps", key="gps_nofix")
            else:
                add(level, "GPS hat noch keinen Fix",
                    f"{seen} Für einen Fix braucht der Empfänger mindestens vier, mit freier Sicht "
                    f"zum Himmel. Nach einem Kaltstart kann das bis zu 15 Minuten dauern.{carry}",
                    action="gps", key="gps_nofix")
        elif refclock:
            state = refclock.get("select_state")
            offset = refclock.get("offset")
            # Modus „automatisch“ (Standard ab 1.5.2): ntp-gui kalibriert selbst – kein Klick nötig.
            auto = cfg.get("gps_autocal") == "auto"
            if state == "falseticker":
                # Nur Entwarnung, wenn die Automatik gerade wirklich misst oder korrigiert – nicht bei einer
                # Sperre (GNSS-Störung), „bitte prüfen“, WEB_READONLY oder wenn sie kalibriert zu haben meint.
                fixing = auto and _autocal_corrects()
                add("info" if fixing else "warn", "GPS widerspricht den anderen Quellen",
                    f"Die GPS-Zeit weicht um {_ms(offset)} von den Netzwerkquellen ab. Das ist "
                    "fast immer die feste Verspätung des USB-Empfängers. "
                    + ("Die automatische Kalibrierung misst und korrigiert sie selbst – du musst nichts tun; "
                       "den Stand zeigt die GPS-Seite unter „GPS kalibrieren“."
                       if fixing else "Lösung: GPS kalibrieren – den Stand der Automatik zeigt die GPS-Seite."
                       if auto else "Lösung: GPS kalibrieren."),
                    action="gps", key="gps_falseticker")
            elif state in {"large_distance", "distance"}:
                add("info", "GPS wird nur beobachtet, nicht genutzt",
                    "chrony bewertet das GPS als zu unsicher: Die angenommene Unsicherheit "
                    "ist viel größer als die der Netzwerkquellen. Mit Internet ist das unkritisch"
                    + (" und ohne PPS so gewollt: Das GPS ist die Rückfallebene und springt ein, wenn das "
                       "Internet ausfällt. Offset und Fehlerschranke stellt ntp-gui selbst nach."
                       if auto else ". Soll das GPS mitzählen, im Kalibrier-Assistenten Offset und Delay "
                       "übernehmen."),
                    action="gps", key="gps_distance")
            elif state in {"best", "combined"}:
                add("ok", "GPS wird genutzt",
                    f"Das GPS fließt in die Zeit ein (Abweichung {_ms(offset)}).", key="gps_used")
            if abs(offset or 0) > 0.02 and state in {"best", "combined", "not_combined"}:
                add("info", "GPS-Offset noch nicht kalibriert",
                    f"Das GPS liegt {_ms(offset)} neben der Systemzeit. "
                    + ("Die automatische Kalibrierung misst den richtigen Korrekturwert und stellt ihn selbst "
                       "ein – den Stand zeigt die GPS-Seite." if auto else
                       "Der Assistent auf der GPS-Seite misst den richtigen Korrekturwert."),
                    action="gps", key="gps_uncal")

    ptp = status.get("ptp") or {}
    if ptp.get("enabled") and not ptp.get("running"):
        add("crit", "ptp4l antwortet nicht",
            "PTP ist eingeschaltet, aber ptp4l läuft nicht oder antwortet nicht. Die PTP-Seite "
            "prüft die Voraussetzungen.", action="ptp", key="ptp_down")
    out.extend(ptp_role_insights(cfg))

    ui = status.get("ui") or {}
    if not (ui.get("storage") or {}).get("persistent", True):
        add("warn", "Einstellungen gehen beim Neuerstellen verloren",
            "/var/lib/chrony liegt nicht auf einem Volume. Im Dashboard gespeicherte "
            "Einstellungen und der Verlauf verschwinden, wenn der Container neu erstellt wird. "
            "In der Compose-Datei ein Volume für /var/lib/chrony anlegen.", key="storage")
    if not (ui.get("auth") or {}).get("enabled") and not ui.get("readonly"):
        add("info", "Dashboard ohne Passwort",
            "Jeder im LAN kann die Einstellungen ändern. Ein Passwort lässt sich unter "
            "System → Einstellungen → Dashboard & Zugang setzen.", action="settings", key="no_auth")

    if status.get("client_count") == 0 and tracking.get("synchronised"):
        add("info", "Noch keine Clients",
            "Bisher hat kein Gerät nach der Zeit gefragt. Verteile die Adresse dieses Servers "
            "per DHCP Option 42 – die Clients-Seite zeigt, wie.", action="clients",
            key="no_clients")
    return out
