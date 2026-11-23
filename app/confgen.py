"""Erzeugt chrony.conf und ptp4l.conf aus den effektiven Einstellungen.

Wird vom Entrypoint beim Start und bei jedem Neuladen aufgerufen:

    eval "$(python3 /app/confgen.py apply)"

`apply` schreibt die Konfigurationsdateien und gibt Shell-Zuweisungen für die
Werte aus, die der Supervisor zum Starten der Dienste braucht. Warnungen
gehen auf stderr und landen so im Container-Log.
"""

from __future__ import annotations

import contextlib
import difflib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dnsfwd  # noqa: E402
import numfmt  # noqa: E402
import settings  # noqa: E402

CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")
CUSTOM_CHRONY = os.environ.get("CUSTOM_CHRONY_CONF", "/config/chrony.conf")
CUSTOM_PTP4L = os.environ.get("CUSTOM_PTP4L_CONF", "/config/ptp4l.conf")
NTS_DUMPDIR = "/var/lib/chrony"
# Private Kopien von Zertifikat und Schlüssel für chronyd (siehe prepare_nts_files).
NTS_CERT_DIR = os.environ.get("NTPGUI_NTS_CERT_DIR", "/var/lib/chrony/nts-certs")
NTS_DEFAULT_PORT = 4460
NTS_MAX_FILE = 1024 * 1024  # PEM-Ketten sind wenige KB; alles darüber ist kein Zertifikat


def _log(area: str, message: str) -> None:
    print(f"[{area}] {message}", file=sys.stderr, flush=True)


def _num(value) -> str:
    """Zahl ohne überflüssige Nachkommastellen, wie chrony sie erwartet."""
    if isinstance(value, float):
        text = f"{value:.9f}".rstrip("0").rstrip(".")
        return text if text not in {"", "-0"} else "0"
    return str(value)


_EXTRA_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\"}


def _unescape_extra(text: str) -> str:
    """EXTRA_*_CONF: „\\n“ wird zum Zeilenumbruch („\\t“ Tab, „\\\\“ Backslash).

    Nur diese Folgen – alles andere bleibt, wie es dasteht, auch Umlaute und andere Backslashes.
    """
    return re.sub(r"\\([nt\\])", lambda m: _EXTRA_ESCAPES[m.group(1)], text)


def gps_refclock_values(cfg: dict) -> dict:
    """delay/precision der GPS-Zeile (gpsquality.refclock_values); bei jedem Fehler die Einstellungen."""
    try:
        import gpsquality
        return gpsquality.refclock_values(cfg)
    except Exception as exc:  # die Konfiguration muss immer entstehen
        _log("gps", f"HINWEIS: Fehlerschranke nicht gelesen ({exc}) – Einstellungen gelten.")
        return {"delay": float(cfg["gps_delay"]), "precision": float(cfg["gps_precision"]), "source": "manual"}


def gps_device_ok(cfg: dict) -> bool:
    return bool(cfg["gps_enable"]) and os.path.exists(cfg["gps_device"])


ZONEINFO = "/usr/share/zoneinfo"


def _zone_inside(tz: str) -> bool:
    """Liegt die Zeitzone wirklich unter ZONEINFO (kein absoluter Pfad, kein „..“)?"""
    if not tz or tz.startswith("/") or any(part in {"", ".", ".."} for part in tz.split("/")):
        return False
    return os.path.normpath(os.path.join(ZONEINFO, tz)).startswith(ZONEINFO + "/")


def leap_directive(cfg: dict, warn=_log, exists=os.path.exists) -> str | None:
    """Woher chrony Schaltsekunden kennt. Eine gesetzte, vorhandene Zeitzone hat
    Vorrang (eigene Images); sonst die Liste aus tzdata (Debian trixie)."""
    tz = cfg.get("leapsectz") or ""
    if tz and not _zone_inside(tz):
        warn("ntp", "WARNUNG: LEAPSECTZ ist kein Name einer Zeitzone unter /usr/share/zoneinfo – "
                    "wird ignoriert, Schaltsekunden kommen aus der Liste.")
        tz = ""
    if tz:
        if exists(os.path.join(ZONEINFO, tz)):
            return f"leapsectz {tz}"
        warn("ntp", f"HINWEIS: Zeitzone {tz} gibt es in diesem Image nicht – Schaltsekunden "
                    "kommen aus der Liste. LEAPSECTZ kann aus der Compose-Datei entfernt werden.")
    path = cfg.get("leapseclist") or ""
    if path:
        if exists(path):
            return f"leapseclist {path}"
        warn("ntp", f"WARNUNG: {path} fehlt – chrony kennt keine bevorstehenden Schaltsekunden.")
    return None


# Experten-Variablen, die als Wert in chrony.conf landen (ohne Dashboard-Feld). Jede wird geprüft;
# ein ungültiger Wert fällt mit Warnung (expert_env_warnings) auf den Standard zurück – so kann auch ein
# Tippfehler oder ein Zeilenumbruch in der Compose-Datei keine weitere Direktive erzeugen.
# Ausnahme PHC_REFCLOCK_OPTIONS: Dort stehen Werte wie „tai“ oder „offset -37“, ohne die die PHC-Zeit
# falsch übernommen würde – ein ungültiger Wert verhindert den Start statt still zu entfallen.
CHRONY_LOG_WORDS = ("measurements", "statistics", "tracking", "rtc", "refclocks", "tempcomp",
                    "rawmeasurements", "selection")
PHC_REFCLOCK_DEFAULT = "poll 0 dpoll -2 offset 0 stratum 1"
# Zusätzlich zu den Refclock-Optionen des Dashboards: „local“ (chrony.conf(5), refclock). Treiberoptionen
# des PHC-Treibers (nocrossts, extpps, pin …) gehören an den Gerätepfad, nicht in die Optionen.
PHC_EXTRA_OPTIONS = {"local": 0}


def _env_int(env: dict, name: str, default: int, low: int, high: int, notes: list[str]) -> int:
    raw = str(env.get(name) or "").strip()
    if raw and (not re.fullmatch(r"[0-9]{1,10}", raw) or not low <= int(raw) <= high):
        notes.append(f"WARNUNG {name}: {raw[:40]!r} ist ungültig (erlaubt {low}–{high}, ganze Zahl) "
                     f"– verwende {default}")
        return default
    return int(raw) if raw else default


def chrony_env_values(env: dict) -> tuple[dict, list[str]]:
    """Geprüfte Werte von GPS_SHM_UNIT, GPS_PPS_SHM_UNIT, MAXUPDATESKEW, CLIENTLOGLIMIT, CHRONY_LOG und
    PHC_REFCLOCK_OPTIONS – plus Warnungen für alles, was durch den Standard ersetzt wurde."""
    notes: list[str] = []
    out = {
        "gps_shm_unit": _env_int(env, "GPS_SHM_UNIT", 0, 0, 255, notes),
        "gps_pps_shm_unit": _env_int(env, "GPS_PPS_SHM_UNIT", 1, 0, 255, notes),
        "clientloglimit": str(_env_int(env, "CLIENTLOGLIMIT", CLIENTLOGLIMIT_DEFAULT, 0, 2 ** 31 - 1, notes)),
    }
    raw = str(env.get("MAXUPDATESKEW") or "").strip()
    out["maxupdateskew"] = "100.0"
    if raw:
        if re.fullmatch(r"[0-9]{1,7}(\.[0-9]{1,6})?", raw) and 0 < float(raw) <= 1000000:
            out["maxupdateskew"] = raw
        else:
            notes.append(f"WARNUNG MAXUPDATESKEW: {raw[:40]!r} ist ungültig (Zahl über 0 bis 1000000) "
                         "– verwende 100.0")
    words = str(env.get("CHRONY_LOG") or "").split()
    unknown = [w for w in words if w not in CHRONY_LOG_WORDS]
    if unknown:
        notes.append(f"WARNUNG CHRONY_LOG: {' '.join(unknown)[:60]!r} kennt chrony nicht (erlaubt: "
                     f"{', '.join(CHRONY_LOG_WORDS)}) – unbekannte Wörter entfallen")
    out["chrony_log"] = " ".join(dict.fromkeys(w for w in words if w in CHRONY_LOG_WORDS))
    raw = env.get("PHC_REFCLOCK_OPTIONS")
    out["phc_options"] = PHC_REFCLOCK_DEFAULT
    out["phc_error"] = None
    if raw is not None:
        try:
            out["phc_options"] = settings._check_options(
                raw, {**settings.REFCLOCK_OPTIONS, **PHC_EXTRA_OPTIONS}, "PHC-Refclock",
                settings.REFCLOCK_INTEGER_OPTIONS)
        except settings.ValidationError as exc:
            out["phc_options"] = None
            out["phc_error"] = (f"PHC_REFCLOCK_OPTIONS: {exc} – bitte in der Compose-Datei korrigieren; "
                                "ohne gültigen Wert startet der PHC-Refclock nicht")
            notes.append(f"FEHLER {out['phc_error']}")
    return out, notes


# Speicher für das Client-Log von chronyd (Ratelimit, Client-Liste): 2 MiB reichen für etwa 16 000
# gleichzeitig bekannte Adressen. Mehr kostet auf einem öffentlich erreichbaren Server nur Speicher.
CLIENTLOGLIMIT_DEFAULT = 2097152

# Ratelimit je Stufe (settings.RATELIMIT_LEVELS), chrony.conf(5): interval = log2 des mittleren
# Mindestabstands in Sekunden, burst = erlaubter Stoß, leak 2 = jede vierte gebremste Anfrage wird
# trotzdem beantwortet. „schonend“ bremst nur Überflutung; Geräte hinter einer gemeinsamen Adresse
# teilen sich die Grenze (Dauerbetrieb etwa 250 Geräte bei 64 s, gleichzeitiger Neustart deutlich weniger).
RATELIMIT_LINES = {
    "schonend": ("ratelimit interval -2 burst 32 leak 2", "ntsratelimit interval 0 burst 16 leak 2"),
    "streng": ("ratelimit interval 1 burst 16 leak 2", "ntsratelimit interval 3 burst 8 leak 2"),
}


def exposure_warnings(cfg: dict) -> list[str]:
    """Log-Hinweise, wenn der Zeitserver auch öffentlichen Adressen antwortet (ALLOW_NETWORKS)."""
    public = settings.public_networks(cfg.get("allow_networks"))
    if not public:
        return []
    notes = [f"WARNUNG: Der Zeitserver antwortet auch öffentlichen Adressen ({', '.join(public)[:80]}). "
             "Das ist nur richtig, wenn eine Firewall davor sitzt oder der Server bewusst öffentlich ist."]
    level = cfg.get("ntp_ratelimit")
    if level == "aus":
        notes.append("WARNUNG: Ratelimit ist aus – jede Adresse bekommt beliebig viele Antworten. "
                     "Für einen öffentlich erreichbaren Server NTP_RATELIMIT=streng setzen.")
    elif level == "schonend":
        notes.append("HINWEIS: Ratelimit steht auf „schonend“ (nur Überflutung). Für einen öffentlich erreichbaren "
                     "Server ist „streng“ besser.")
    if cfg.get("serve_unsynced"):
        notes.append("WARNUNG: Inselbetrieb ist an – fallen alle Quellen aus, bekommen auch Clients aus dem "
                     "Internet die frei laufende Uhr als gültige Zeit. Für einen öffentlichen Server "
                     "SERVE_UNSYNCED=false setzen.")
    return notes


# Zeichen, die in einer erzeugten Zeile nie vorkommen dürfen: Steuerzeichen (außer Tab) und alles, was
# ein Leser als Zeilenende verstehen könnte. Jede Zeile wird vor dem Schreiben geprüft (_guard_lines).
_LINE_BREAKERS = re.compile("[\x00-\x08\x0a-\x1f\x7f\x85\u2028\u2029]")


class UnsafeConfig(ValueError):
    """Eine erzeugte Konfigurationszeile enthält ein Steuerzeichen – es wird nichts geschrieben."""


class InvalidEnvValue(UnsafeConfig):
    """Ein Wert aus der Umgebung, ohne den chrony.conf nicht korrekt wäre, ist ungültig – es wird nichts
    geschrieben (z. B. PHC_REFCLOCK_OPTIONS)."""


def _guard_lines(lines: list[str], what: str) -> None:
    for line in lines:
        if _LINE_BREAKERS.search(line):
            raise UnsafeConfig(f"{what}: Steuerzeichen in einer erzeugten Zeile – Konfiguration abgelehnt")


def render_chrony(cfg: dict, env: dict | None = None, warn=_log,
                  nts_files: tuple[str, str] | None = None) -> str:
    """chrony.conf als Text. nts_files: (Zertifikat, Schlüssel), die chronyd lesen
    soll – Standard sind die konfigurierten Pfade (apply() übergibt die Kopien)."""
    env = os.environ if env is None else env
    env_values, _notes = chrony_env_values(env)  # Warnungen meldet expert_env_warnings
    lines = [
        "# Generiert von ntp-gui – Änderungen gehen beim nächsten Speichern verloren.",
        "# Einstellen im Dashboard oder per Umgebungsvariable; für eine komplett",
        "# eigene Konfiguration /config/chrony.conf mounten.",
        "",
    ]

    common = cfg["ntp_source_options"]
    uses_nts = False
    for source in cfg["ntp_sources"]:
        parts = [source["type"], source["host"]]
        if common:
            parts.append(common)
        if source["options"]:
            parts.append(source["options"])
        if source["type"] == "pool":
            parts.append(f"maxsources {cfg['ntp_pool_maxsources']}")
        if source["nts"]:
            parts.append("nts")
            uses_nts = True
        if source["prefer"]:
            parts.append("prefer")
        if source["noselect"]:
            parts.append("noselect")
        lines.append(" ".join(_dedupe(" ".join(parts).split())))

    if cfg["gps_enable"] and not gps_device_ok(cfg):
        warn("gps", f"WARNUNG: GPS-Refclock wird übersprungen, {cfg['gps_device']} fehlt.")
    elif cfg["gps_enable"]:
        # Ohne PPS (1.5, E16): ehrliche Fehlerschranke aus der gemessenen Streuung, damit
        # chrony gute Netzquellen vorzieht und das GPS als Rückfallebene nimmt.
        clock = gps_refclock_values(cfg)
        if clock["source"] in {"measured", "default"}:
            lines.append(f"# GPS ohne PPS: Rückfallebene, Fehlerschranke ± {numfmt.number(clock['delay'] / 2 * 1000)} ms "
                         + ("(gemessen)" if clock["source"] == "measured" else "(Standard, noch nicht gemessen)"))
        parts = [
            f"refclock SHM {env_values['gps_shm_unit']} refid {cfg['gps_refid']}",
            f"offset {_num(float(cfg['gps_offset']))} delay {_num(float(clock['delay']))}",
            f"precision {_num(float(clock['precision']))} poll {cfg['gps_poll']}",
            f"filter {cfg['gps_filter']}",
        ]
        if cfg["gps_select"] in {"prefer", "noselect"}:
            parts.append(cfg["gps_select"])
        if cfg["gps_refclock_options"]:
            parts.append(cfg["gps_refclock_options"])
        lines.append(" ".join(_dedupe(" ".join(parts).split())))
        pps = cfg["gps_pps_device"]
        pps_poll = cfg["gps_pps_poll"]
        pps_extra = cfg["gps_pps_options"]
        if pps and os.path.exists(pps):
            lines.append(f"refclock PPS {pps} lock {cfg['gps_refid']} refid PPS poll {pps_poll}"
                         + (f" {pps_extra}" if pps_extra else ""))
        elif pps:
            # chronyd bricht mit "Could not open" ab und der Container startet in
            # einer Schleife neu - lieber ohne PPS starten und warnen.
            warn("gps", f"WARNUNG: {pps} existiert nicht – PPS-Refclock wird übersprungen.")
        elif cfg["gps_pps_shm"]:
            unit = env_values["gps_pps_shm_unit"]
            lines.append(f"refclock SHM {unit} refid PPS precision 1e-7 lock {cfg['gps_refid']} "
                         f"poll {pps_poll}" + (f" {pps_extra}" if pps_extra else ""))

    phc = cfg["phc_refclock"]
    if phc and cfg.get("ptp_mode") == "master" and phc2sys_plan(cfg, env)["start"]:
        # Als Grandmaster kopiert phc2sys die Systemuhr in die PHC. Ein PHC-Refclock
        # würde chronyd seine eigene Zeit zurückliefern (Zeitschleife) und könnte mit
        # stratum 1 und winzigem Jitter sogar GPS/NTP verdrängen.
        warn("ptp", f"WARNUNG: PHC-Refclock {phc} wird übersprungen – als PTP-Grandmaster "
                    "stellt phc2sys die PTP-Uhr nach der Systemuhr, chrony bekäme seine eigene "
                    "Zeit zurück. PHC_REFCLOCK nur als PTP-Slave verwenden.")
    elif phc:
        if os.path.exists(phc):
            if env_values["phc_error"]:
                # Kein stiller Rückfall auf den Standard: ohne „tai“/„offset“ käme eine falsche Zeit heraus.
                raise InvalidEnvValue(env_values["phc_error"])
            options = env_values["phc_options"]
            lines.append(f"refclock PHC {phc} {options}".rstrip())
        else:
            warn("ptp", f"WARNUNG: {phc} existiert nicht – PHC-Refclock wird übersprungen.")

    lines += [
        "",
        "driftfile /var/lib/chrony/chrony.drift",
        # Messhistorie über Neustarts retten (chronyd -r lädt sie wieder).
        "dumpdir /var/lib/chrony",
        f"makestep {cfg['makestep']}",
        f"maxupdateskew {env_values['maxupdateskew']}",
        f"minsources {cfg['ntp_minsources']}",
        "logdir /var/log/chrony",
    ]
    if env_values["chrony_log"]:
        lines.append(f"log {env_values['chrony_log']}")
    leap = leap_directive(cfg, warn)
    if leap:
        lines.append(leap)
    lines += [
        f"clientloglimit {env_values['clientloglimit']}",
        "bindcmdaddress /var/run/chrony/chronyd.sock",
        "cmdport 0",
        f"port {cfg['ntp_port']}",
    ]
    if cfg["bind_address"]:
        lines.append(f"bindaddress {cfg['bind_address']}")
    if cfg["ntp_hw_timestamp"]:
        lines.append(f"hwtimestamp {cfg['ntp_hw_timestamp_interface'] or '*'}")
    limits = RATELIMIT_LINES.get(cfg["ntp_ratelimit"])
    if limits:
        lines.append(limits[0])

    if uses_nts or cfg["nts_server_enable"]:
        lines += ["", f"ntsdumpdir {NTS_DUMPDIR}"]
        if uses_nts and cfg["nts_nocerttimecheck"]:
            lines.append("nocerttimecheck 1")
    if cfg["nts_server_enable"]:
        if nts_files is None:
            cert, key = cfg["nts_server_cert"], cfg["nts_server_key"]
            if os.path.exists(cert) and os.path.exists(key):
                nts_files = (cert, key)
            else:
                warn("nts", f"WARNUNG: NTS-Server aktiviert, aber {cert} oder {key} fehlt – "
                            "NTS-Server bleibt aus.")
        if nts_files:
            lines += [f"ntsservercert {nts_files[0]}", f"ntsserverkey {nts_files[1]}"]
            # chrony.conf(5) 4.3, ntsport: TCP-Port des NTS-KE-Dienstes, Standard 4460.
            if int(cfg.get("nts_server_port") or NTS_DEFAULT_PORT) != NTS_DEFAULT_PORT:
                lines.append(f"ntsport {int(cfg['nts_server_port'])}")
            # Schlüsselaustausch (TLS) je Adresse begrenzen – dieselbe Stufe wie das NTP-Ratelimit.
            if limits:
                lines.append(limits[1])
            # chrony.conf(5) 4.3, ntsntpserver: Name/Adresse des NTP-Servers, den der
            # NTS-KE-Server den Clients nennt. Ohne ihn schicken Clients NTP an die
            # Adresse der NTS-KE-Verbindung – hinter einem TCP-Proxy also an den Proxy.
            # (ntsrotate 0 ist nur nötig, wenn NTP auf einem ANDEREN chronyd läuft; hier
            # beantwortet derselbe chronyd beides.)
            if cfg.get("nts_server_name"):
                lines.append(f"ntsntpserver {cfg['nts_server_name']}")

    lines.append("")
    lines += [f"allow {net}" for net in cfg["allow_networks"]]
    lines += [f"deny {net}" for net in cfg["deny_networks"]]

    if cfg["serve_unsynced"]:
        lines += ["", "# Auch ohne erreichbare Quelle Zeit ausliefern (Inselbetrieb)."]
        if cfg["local_orphan"]:
            # Orphan-Modus (chrony.conf(5), Direktive local): Von mehreren Servern mit
            # gleichem local stratum, die sich gegenseitig abfragen, liefert nur der mit
            # der kleinsten Referenz-ID die eigene Zeit, die anderen folgen ihm.
            lines += ["# Orphan: Verbund mehrerer Server einigt sich auf eine Inselzeit.",
                      f"local stratum {cfg['local_stratum']} orphan"]
        else:
            lines.append(f"local stratum {cfg['local_stratum']}")
    elif cfg["local_orphan"]:
        warn("chrony", "HINWEIS: Orphan-Modus ist eingeschaltet, wirkt aber nur zusammen mit "
                       "„Auch ohne Quelle Zeit ausliefern“ (SERVE_UNSYNCED) – bleibt aus.")

    # Jede erzeugte Zeile ist genau eine Zeile – erst danach kommt der bewusst freie EXTRA_CHRONY_CONF.
    _guard_lines(lines, "chrony.conf")
    extra = env.get("EXTRA_CHRONY_CONF", "")
    if extra:
        lines += ["", "# EXTRA_CHRONY_CONF", _unescape_extra(extra)]
    return "\n".join(lines) + "\n"


# PTP-Profile und ihre effektiven Werte stehen in settings, damit Dashboard
# (Statusanzeige, Hardware-Check) und confgen dieselben Werte sehen.
PTP_PROFILES = settings.PTP_PROFILES
ptp_profile_values = settings.ptp_profile_values


def ptp_tx_timestamp_timeout(env: dict) -> int:
    """PTP_TX_TIMESTAMP_TIMEOUT in ms (ptp4l tx_timestamp_timeout), 1–10000, Standard 10."""
    return int(settings.env_number("PTP_TX_TIMESTAMP_TIMEOUT", 10, 1, 10000, env, integer=True))


def render_ptp4l(cfg: dict, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    cfg, profile_extra = ptp_profile_values(cfg)
    mode = cfg["ptp_mode"]
    slave_only = 1 if mode == "slave" else 0
    master_only = 1 if mode == "master" else 0
    extra = env.get("EXTRA_PTP4L_CONF", "")
    body = f"""# Generiert von ntp-gui (Profil: {cfg.get('ptp_profile') or 'default'}).
[global]
domainNumber            {cfg['ptp_domain']}
clientOnly              {slave_only}
serverOnly              {master_only}
priority1               {cfg['ptp_priority1']}
priority2               {cfg['ptp_priority2']}
clockClass              {cfg['ptp_clock_class']}
delay_mechanism         {cfg['ptp_delay_mechanism']}
network_transport       {cfg['ptp_transport']}
time_stamping           {cfg['ptp_time_stamping']}
tx_timestamp_timeout    {ptp_tx_timestamp_timeout(env)}
logSyncInterval         {cfg['ptp_log_sync_interval']}
logMinDelayReqInterval  {cfg['ptp_log_min_delay_req_interval']}
logAnnounceInterval     {cfg['ptp_log_announce_interval']}
announceReceiptTimeout  {cfg['ptp_announce_receipt_timeout']}
summary_interval        {cfg['ptp_summary_interval']}
uds_address             {settings.ptp_uds_address(env)}
"""
    utc_offset = int(settings.env_number("PTP_UTC_OFFSET", 37, 0, 100, env, integer=True))
    if utc_offset != 37:
        # Startwert bis zur ersten Grandmaster-Meldung (ptp.utc_offset nutzt dieselbe Variable).
        body += f"utc_offset              {utc_offset}\n"
    for key, value in profile_extra.items():
        body += f"{key:<23} {value}\n"
    # Die Werte oben kommen aus geprüften Einstellungen; trotzdem darf keiner eine Zeile umbrechen.
    _guard_lines([str(v) for k, v in cfg.items() if k.startswith("ptp_")]
                 + [f"{k} {v}" for k, v in profile_extra.items()] + [settings.ptp_uds_address(env)], "ptp4l.conf")
    if extra:
        body += _unescape_extra(extra) + "\n"
    body += f"\n[{cfg['ptp_interface'] or 'eth0'}]\n"
    return body


# --- phc2sys: Richtung und Zusammenspiel mit chronyd -------------------------
#
# Aus phc2sys(8) (linuxptp, Quelle phc2sys.8 im Upstream-Repository):
#   -a   "Read the clocks to synchronize from running ptp4l and follow changes in
#         the port states, adjusting the synchronization direction automatically.
#         The system clock is not synchronized, unless the -r option is also
#         specified."
#   -r   "... to also synchronize the system clock ... By default, the system clock
#         is not considered as a possible time source. If you want the system clock
#         to be eligible to become a time source, specify the -r option twice."
#   -c   "Specify the time sink ... The default is CLOCK_REALTIME (the system clock)."
#   Beispiel: "phc2sys -a -rr" – "when the host becomes the domain server,
#         synchronize time in the domain to its system clock."
#   Der UTC-Abstand (TAI-UTC, derzeit 37 s) kommt dabei aus currentUtcOffset von
#   ptp4l ("assuming the system clock is keeping time in UTC and all used PHCs
#   keep time in TAI") – ein "-O 0" würde PTP-Clients um 37 s verschieben.
#
# Grandmaster: chronyd regelt die Systemuhr (GPS/NTP), phc2sys -a -rr kopiert sie
# in die PHC der Master-Ports. Slave: phc2sys -a -r stellt die Systemuhr nach der
# PHC; chronyd darf dann nicht mitregeln (-x), sonst kämpfen zwei Regler.

PHC2SYS_AUTO = {"master": "-a -rr -m", "slave": "-a -r -m", "auto": "-a -r -m"}
# Bis 1.1.0 dokumentierter Standard von PHC2SYS_OPTIONS (siehe phc2sys_plan).
PHC2SYS_LEGACY_DEFAULT = "-a -r -m"


def phc2sys_writes_realtime(options: str) -> bool:
    """Kann phc2sys mit diesen Optionen die Systemuhr (CLOCK_REALTIME) stellen?"""
    tokens = options.split()
    if "-a" in tokens:
        # Ein einzelnes -r: Systemuhr ist nur Ziel. -rr (oder -r -r): sie darf
        # auch Quelle sein – im Grandmaster-Betrieb die gewünschte Richtung.
        r_count = tokens.count("-r") + 2 * tokens.count("-rr")
        if r_count == 1:
            return True
        sinks = [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t == "-c"]
        return "CLOCK_REALTIME" in sinks
    # Manuelle Konfiguration: Senke ist -c, Standard CLOCK_REALTIME.
    sinks = [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t == "-c"]
    return not sinks or "CLOCK_REALTIME" in sinks


def phc2sys_plan(cfg: dict, env: dict | None = None) -> dict:
    """Entscheidet, ob/wie phc2sys läuft und ob chronyd mit -x laufen muss.

    Rückgabe: {"start": bool, "options": str, "nocontrol": bool, "notes": [..]}
    """
    env = {} if env is None else env
    notes: list[str] = []
    ptp_on = bool(cfg["ptp_enable"]) and bool(cfg["ptp_interface"])
    mode = cfg["ptp_mode"]
    software = cfg["ptp_time_stamping"] == "software"
    plan = {"start": False, "options": "", "nocontrol": False, "notes": notes}
    if not ptp_on:
        return plan
    if software:
        # Ohne Hardware-Zeitstempel arbeitet ptp4l direkt mit der Systemuhr: als
        # Slave stellt ptp4l sie selbst, als Master verteilt es sie direkt.
        if cfg["phc2sys_enable"]:
            notes.append("phc2sys wird nicht gestartet: Mit Software-Zeitstempeln gibt es keine "
                         "PTP-Uhr auf der Karte, ptp4l nutzt direkt die Systemuhr.")
        if mode == "slave":
            plan["nocontrol"] = True
            notes.append("PTP-Slave mit Software-Zeitstempeln: ptp4l stellt die Systemuhr, "
                         "chronyd läuft mit -x und liefert nur aus.")
        elif mode == "auto":
            notes.append("HINWEIS: Rolle „automatisch“ mit Software-Zeitstempeln – wird dieser "
                         "Server PTP-Slave, stellen ptp4l und chronyd dieselbe Uhr. Rolle fest "
                         "auf „Grandmaster“ oder „Slave“ stellen.")
        return plan
    if not cfg["phc2sys_enable"]:
        if mode == "master":
            notes.append("WARNUNG: PTP-Grandmaster mit Hardware-Zeitstempeln, aber phc2sys ist aus – "
                         "die PTP-Uhr der Karte läuft frei und ptp4l verteilt NICHT die Zeit von "
                         "chrony/GPS. „Systemuhr und PTP-Uhr koppeln (phc2sys)“ einschalten.")
        return plan
    custom = " ".join((cfg.get("phc2sys_options") or "").split())
    if custom == PHC2SYS_LEGACY_DEFAULT and mode == "master":
        # 1.1.0 hat "-a -r -m" als Standard dokumentiert; viele Compose-Dateien
        # setzen es noch ausdrücklich. Als Grandmaster würde phc2sys damit die
        # Systemuhr nach der frei laufenden Kartenuhr stellen (und chronyd -x) –
        # deshalb gilt genau dieser Wert als „automatisch“.
        notes.append(f"HINWEIS: PHC2SYS_OPTIONS=\"{PHC2SYS_LEGACY_DEFAULT}\" ist der alte Standard "
                     f"und wird als Grandmaster durch „automatisch“ ({PHC2SYS_AUTO['master']}) "
                     "ersetzt. Die Variable kann entfallen.")
        custom = ""
    options = custom or PHC2SYS_AUTO.get(mode, PHC2SYS_AUTO["slave"])
    tokens = options.split()
    if "-a" in tokens:
        # -a holt die Uhren per Management-Nachricht von ptp4l: Domain,
        # UDS-Pfad und transportSpecific müssen zu ptp4l passen.
        if "-n" not in tokens and int(cfg["ptp_domain"]) != 0:
            tokens += ["-n", str(cfg["ptp_domain"])]
        uds = settings.ptp_uds_address(env)
        if "-z" not in tokens and uds != settings.PTP_UDS_DEFAULT:
            tokens += ["-z", uds]
        if cfg.get("ptp_profile") == "gptp":
            tokens.append("--transportSpecific=1")
    options = " ".join(tokens)
    plan.update(start=True, options=options, nocontrol=phc2sys_writes_realtime(options))
    if not custom and mode == "auto":
        notes.append("HINWEIS: Rolle „automatisch“: phc2sys stellt die Systemuhr nach PTP (-a -r) "
                     "und chronyd läuft mit -x. Soll dieser Server GPS-/NTP-Zeit per PTP "
                     "verteilen, die Rolle „Grandmaster“ wählen – erst dann überträgt phc2sys "
                     "die Systemuhr auf die Karte (-a -rr).")
    if custom and mode == "master" and plan["nocontrol"]:
        notes.append(f"WARNUNG: Eigene phc2sys-Optionen „{custom}“ als PTP-Grandmaster: Damit "
                     "stellt phc2sys die Systemuhr nach der Kartenuhr, chronyd läuft mit -x und "
                     "GPS/NTP werden nicht mehr genutzt. phc2sys-Optionen leer lassen "
                     f"(automatisch) oder „{PHC2SYS_AUTO['master']}“ eintragen.")
    if custom and "-a" in tokens and ("-rr" in tokens or tokens.count("-r") >= 2):
        if mode != "master":
            notes.append("HINWEIS: Eigene phc2sys-Optionen mit -rr außerhalb der Grandmaster-Rolle: "
                         "Wird der Port Slave, stellt phc2sys die Systemuhr, während chronyd sie "
                         "ebenfalls regelt.")
    return plan


def _dedupe(tokens: list[str]) -> list[str]:
    """Entfernt doppelte Schalter-Optionen (z. B. zweimal iburst)."""
    flags = {name for name, args in settings.SOURCE_OPTIONS.items() if args == 0}
    flags |= {name for name, args in settings.REFCLOCK_OPTIONS.items() if args == 0}
    out, seen = [], set()
    for token in tokens:
        if token in flags:
            if token in seen:
                continue
            seen.add(token)
        out.append(token)
    return out


def hotplug_paths(cfg: dict) -> list[str]:
    """Konfigurierte, aber (noch) fehlende Geräte, auf die der Supervisor wartet.

    Taucht eines davon auf (USB-GPS eingesteckt, PPS-Overlay geladen), lädt der
    Supervisor die Konfiguration neu, damit die Quelle ohne Neustart dazukommt.
    """
    paths = []
    if cfg["gps_enable"]:
        for path in (cfg["gps_device"], cfg["gps_pps_device"]):
            if path and not os.path.exists(path) and path not in paths:
                paths.append(path)
    if cfg["phc_refclock"] and not os.path.exists(cfg["phc_refclock"]):
        paths.append(cfg["phc_refclock"])
    # Nur Pfade, die die Validierung (/dev/…, keine Leerzeichen) bestanden haben.
    return [p for p in paths if p.startswith("/dev/") and " " not in p]


# --- NTS-Server: Zertifikat für chronyd bereitstellen ----------------------------
# chrony liest Zertifikat und Schlüssel ERST NACH dem Ablegen der Root-Rechte:
# In main.c (4.3) kommt NKS_Initialise() nach SYS_DropRoot(), und die
# NTS-KE-Helfer rufen es in run_helper() ebenfalls erst nach SYS_DropRoot() auf
# (nts_ke_server.c). chrony.conf(5) 4.3 zu ntsservercert/ntsserverkey: „The file
# needs to be readable by the user under which chronyd is running after dropping
# root privileges.“ Zertifikate eines Reverse Proxys (NPM: privkey.pem 0600 root)
# kann _chrony deshalb nicht lesen. Lösung: bei jedem Start/Neuladen eine Kopie
# in NTS_CERT_DIR anlegen, die _chrony nur lesen darf (root:_chrony 0640,
# Verzeichnis 0750). Nur lesen, weil chronyd (ab 4.4) sonst „Having write access
# to …“ meldet: ein Dienst, der seinen Schlüssel ändern kann, ist unnötig riskant.
# Außerdem: „The files are loaded only once. chronyd needs to be restarted in
# order to load a renewed certificate.“ – das übernimmt der Entrypoint-Watchdog.


def _chrony_ids() -> tuple[int, int] | None:
    try:
        import pwd
    except ImportError:  # pragma: no cover - nur Nicht-Unix
        return None
    for name in ("_chrony", "chrony"):
        try:
            entry = pwd.getpwnam(name)
            return entry.pw_uid, entry.pw_gid
        except KeyError:
            continue
    return None


def _read_limited(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(NTS_MAX_FILE + 1)
    if len(data) > NTS_MAX_FILE:
        raise ValueError("größer als 1 MB – das ist kein PEM-Zertifikat")
    return data


def _public_key(args: list[str], data: bytes) -> bytes | None:
    """Öffentlicher Schlüssel per openssl (Eingabe über stdin); None = nicht prüfbar."""
    openssl = shutil.which("openssl")
    if not openssl:
        return None
    try:
        proc = subprocess.run([openssl, *args], input=data, capture_output=True,
                              timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else b""


def nts_pair_matches(cert: bytes, key: bytes) -> bool | None:
    """Gehört der Schlüssel zum Zertifikat? None, wenn openssl fehlt."""
    cert_pub = _public_key(["x509", "-noout", "-pubkey"], cert)
    key_pub = _public_key(["pkey", "-pubout"], key)
    if cert_pub is None or key_pub is None:
        return None
    return bool(cert_pub) and cert_pub == key_pub


def _install_private(path: str, data: bytes, ids: tuple[int, int] | None, secret: bool = False) -> None:
    """Zertifikat: root:_chrony 0640. Schlüssel (secret): _chrony:_chrony 0400 – das Dashboard ist für
    den Kommando-Socket in der Gruppe _chrony und soll den Schlüssel nicht lesen können; chronyd
    warnt bei einer für ihn beschreibbaren Schlüsseldatei."""
    mode = 0o400 if secret else 0o640
    owner = (ids[0] if secret else 0, ids[1]) if ids else None
    try:
        with open(path, "rb") as handle:
            if handle.read(NTS_MAX_FILE + 1) == data:
                if owner and os.geteuid() == 0:
                    os.chown(path, *owner)
                os.chmod(path, mode)
                return
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".ntpgui-")
    try:
        os.fchmod(fd, mode)
        if owner and os.geteuid() == 0:
            os.fchown(fd, *owner)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def prepare_nts_files(cfg: dict, target_dir: str | None = None, warn=_log,
                      ids: tuple[int, int] | None | bool = True, dry_run: bool = False) -> tuple[str, str] | None:
    """Kopiert Zertifikat + Schlüssel für chronyd; liefert die Pfade für chrony.conf.

    None = NTS-Server bleibt aus (Dateien fehlen/ungültig). Schlägt nur das Kopieren
    fehl (z. B. ohne Root), werden die Originalpfade verwendet. dry_run (Vorschau):
    alles prüfen, nichts kopieren – Ergebnis wie nach einem gelungenen Kopieren.
    """
    if not cfg.get("nts_server_enable"):
        return None
    target_dir = target_dir or NTS_CERT_DIR
    if ids is True:
        ids = _chrony_ids()
    cert, key = cfg["nts_server_cert"], cfg["nts_server_key"]
    copy_cert = os.path.join(target_dir, "server.crt")
    copy_key = os.path.join(target_dir, "server.key")
    have_copies = os.path.isfile(copy_cert) and os.path.isfile(copy_key)

    if not (os.path.isfile(cert) and os.path.isfile(key)):
        warn("nts", f"WARNUNG: NTS-Server aktiviert, aber {cert} oder {key} fehlt – "
                    "NTS-Server bleibt aus.")
        return None
    for path in (cert, key):
        real = os.path.realpath(path)
        if real != path and not settings.cert_path_allowed(real):
            warn("nts", f"WARNUNG: {path} zeigt auf {real} – außerhalb von /config, /certs und "
                        "/etc/letsencrypt. Aus Sicherheitsgründen bleibt der NTS-Server aus.")
            return None
    try:
        cert_data, key_data = _read_limited(cert), _read_limited(key)
    except (OSError, ValueError) as exc:
        warn("nts", f"WARNUNG: Zertifikat/Schlüssel nicht lesbar ({exc}) – NTS-Server bleibt aus.")
        return None
    if b"-----BEGIN CERTIFICATE-----" not in cert_data:
        warn("nts", f"WARNUNG: {cert} ist kein PEM-Zertifikat – NTS-Server bleibt aus.")
        return None
    if b"PRIVATE KEY-----" not in key_data:
        warn("nts", f"WARNUNG: {key} ist kein PEM-Schlüssel – NTS-Server bleibt aus.")
        return None
    if nts_pair_matches(cert_data, key_data) is False:
        # Typisch mitten in einer Erneuerung (Zertifikat schon neu, Schlüssel noch alt).
        # Ein unpassendes Paar ließe chronyd beim Start scheitern.
        if have_copies:
            warn("nts", "WARNUNG: Zertifikat und Schlüssel passen (noch) nicht zusammen – "
                        "chronyd nutzt weiter das zuletzt gültige Paar.")
            return copy_cert, copy_key
        warn("nts", "WARNUNG: Zertifikat und Schlüssel passen nicht zusammen – "
                    "NTS-Server bleibt aus.")
        return None
    if dry_run:
        return copy_cert, copy_key
    try:
        os.makedirs(target_dir, mode=0o750, exist_ok=True)
        os.chmod(target_dir, 0o750)
        if ids and os.geteuid() == 0:
            os.chown(target_dir, 0, ids[1])
        _install_private(copy_cert, cert_data, ids or None)
        _install_private(copy_key, key_data, ids or None, secret=True)
    except OSError as exc:
        warn("nts", f"WARNUNG: Kopie nach {target_dir} fehlgeschlagen ({exc}) – chronyd liest "
                    "die Originale und braucht dafür selbst Leserechte.")
        return cert, key
    return copy_cert, copy_key


def nts_watch_paths(cfg: dict) -> list[str]:
    """Dateien, deren Änderung (Zertifikatserneuerung) chronyd neu laden muss."""
    if not cfg.get("nts_server_enable") or os.path.isfile(CUSTOM_CHRONY):
        return []
    return [p for p in (cfg.get("nts_server_cert"), cfg.get("nts_server_key")) if p]


# Experten-Variablen ohne Dashboard-Feld: (Name, Standard, Minimum, Maximum, ganzzahlig)
EXPERT_NUMBERS = [
    ("PTP_TX_TIMESTAMP_TIMEOUT", 10, 1, 10000, True),
    ("PTP_UTC_OFFSET", 37, 0, 100, True),
    ("PTP_HOLDOVER_SECONDS", 900, 0, 86400, False),
]


def expert_env_warnings(env: dict) -> list[str]:
    """Warnungen für ungültige Experten-Variablen (die dann auf den Standard fallen)."""
    notes = []
    for name, default, low, high, integer in EXPERT_NUMBERS:
        raw = (env.get(name) or "").strip()
        if raw and settings.env_number(name, None, low, high, env, integer=integer) is None:
            notes.append(f"WARNUNG {name}: {raw!r} ist ungültig (erlaubt {low}–{high}"
                         f"{', ganze Zahl' if integer else ''}) – verwende {default}")
    notes += chrony_env_values(env)[1]
    import netguard
    outbound = netguard.mode_warning(env)
    if outbound:
        notes.append(f"WARNUNG {outbound}")
    raw = (env.get("PTP_UDS_ADDRESS") or "").strip()
    if raw and settings.ptp_uds_address(env) != raw:
        notes.append(f"WARNUNG PTP_UDS_ADDRESS: {raw!r} ist kein gültiger absoluter Pfad – "
                     f"verwende {settings.PTP_UDS_DEFAULT}")
    return notes


def _stage(path: str, content: str) -> str:
    """Schreibt content in eine Tempdatei neben path und liefert ihren Namen (noch nicht umbenannt).
    Scheitert das Schreiben, verschwindet die Tempdatei wieder."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ntpgui-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(tmp, 0o644)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return tmp


def _write(path: str, content: str) -> None:
    os.replace(_stage(path, content), path)


def _write_all(files: list[tuple[str, str]]) -> None:
    """Alle Dateien erst vollständig in Tempdateien schreiben, dann umbenennen. Scheitert eine,
    bleibt jede Zieldatei unverändert und keine Tempdatei liegen."""
    staged: list[tuple[str, str]] = []
    try:
        for path, content in files:
            staged.append((_stage(path, content), path))
        while staged:
            tmp, path = staged[0]
            os.replace(tmp, path)
            staged.pop(0)
    finally:
        for tmp, _ in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _wait_for(path: str, seconds: int) -> bool:
    for _ in range(max(0, seconds)):
        if os.path.exists(path):
            return True
        time.sleep(1)
    return os.path.exists(path)


def planned_files(cfg: dict, env: dict, nts_files: tuple[str, str] | tuple = (), log=_log) -> list[tuple[str, str]]:
    """(Pfad, Inhalt) der Dateien, die apply() schreibt – genau so, ohne zu schreiben.
    apply() und die Vorschau im Dashboard (preview) nutzen beide diese Funktion."""
    files = []
    if os.path.isfile(CUSTOM_CHRONY):
        log("chrony", f"verwende gemountete {CUSTOM_CHRONY}")
        with open(CUSTOM_CHRONY, encoding="utf-8") as handle:
            files.append((CHRONY_CONF, handle.read()))
    else:
        files.append((CHRONY_CONF, render_chrony(cfg, env, warn=log, nts_files=nts_files)))

    ptp_on = bool(cfg["ptp_enable"]) and bool(cfg["ptp_interface"])
    if cfg["ptp_enable"] and not cfg["ptp_interface"]:
        log("ptp", "WARNUNG: PTP ist aktiviert, aber kein Interface gewählt – PTP wird nicht gestartet.")
    if ptp_on:
        if os.path.isfile(CUSTOM_PTP4L):
            log("ptp", f"verwende gemountete {CUSTOM_PTP4L}")
            with open(CUSTOM_PTP4L, encoding="utf-8") as handle:
                files.append((PTP4L_CONF, handle.read()))
        else:
            files.append((PTP4L_CONF, render_ptp4l(cfg, env)))
    return files


# --- Vorschau im Dashboard (1.6, T2): was Speichern in die Dateien schriebe ---------------------------
# Rechnet mit den ungespeicherten Werten genau wie apply(), schreibt aber nichts, kopiert keine
# NTS-Dateien, wartet nicht auf Geräte und startet keinen Dienst. Ergebnis je Datei: Zeilen-Diff
# (difflib.unified_diff) gegen die jetzt geschriebene Datei. Geheimnisse stehen in den erzeugten
# Dateien nicht (Passwort, API-Schlüssel, Tokens und DoH-Adressen landen nie in chrony.conf/ptp4l.conf;
# NTS-Zertifikat und -Schlüssel nur als Pfad). Frei eingetragene Zeilen (EXTRA_CHRONY_CONF,
# EXTRA_PTP4L_CONF, gemountete Dateien) werden trotzdem vorsichtshalber geschwärzt (redact_config).
PREVIEW_MAX_FILE = 1024 * 1024
PREVIEW_MAX_LINES = 2000
REDACTED = "••••"
_SECRET_WORD = re.compile(r"(?i)(password|passwd|passphrase|secret|token|psk|api[_-]?key|credential|bearer)")
_URL_USERINFO = re.compile(r"(?i)\b(https?://)[^/\s@]+@")
_URL_PATH = re.compile(r"(?i)\b(https?://[^/\s?#]+)[/?#]\S*")


def redact_config(text: str) -> str:
    """Schwärzt in Konfigurationstext alles, was nach einem Geheimnis aussieht: den Wert einer Zeile,
    deren Direktive oder Wert nach Passwort/Token/Secret klingt, Zugangsdaten und Pfade in URLs
    (DoH-Pfade tragen Konto-Kennungen). Pfade zu Dateien (ntsserverkey /…) bleiben stehen."""
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped and not stripped.startswith(("#", ";", "[")) and _SECRET_WORD.search(stripped):
            indent = line[:len(line) - len(stripped)]
            head = re.split(r"[\s=:]", stripped, maxsplit=1)[0]
            line = f"{indent}{head} {REDACTED}" if head and head != stripped else f"{indent}{REDACTED}"
        line = _URL_PATH.sub(lambda m: f"{m.group(1)}/{REDACTED}", _URL_USERINFO.sub(rf"\1{REDACTED}@", line))
        out.append(line)
    return "\n".join(out)


def _current(path: str) -> str | None:
    """Die jetzt geschriebene Datei (None = gibt es noch nicht)."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(PREVIEW_MAX_FILE + 1)
    except FileNotFoundError:
        return None
    except OSError:
        return ""
    return data[:PREVIEW_MAX_FILE].decode("utf-8", "replace")


def preview_files(changes: dict, defaults=None, env: dict | None = None) -> tuple[dict, list[str]]:
    """({Pfad: Inhalt}, Hinweise) – was apply() mit diesen ungespeicherten Werten schriebe."""
    env = dict(os.environ if env is None else env)
    cfg = settings.preview_values(changes, defaults, env)
    notes: list[str] = []

    def note(_area: str, message: str) -> None:
        if message not in notes:
            notes.append(message)

    nts = prepare_nts_files(cfg, warn=note, ids=None, dry_run=True) or ()
    return dict(planned_files(cfg, env, nts_files=nts, log=note)), notes


def preview(changes: dict, defaults=None, env: dict | None = None) -> dict:
    """Vorschau fürs Dashboard: je Datei Zustand und Zeilen-Diff (geschwärzt, siehe redact_config)."""
    try:
        planned, notes = preview_files(changes, defaults, env)
    except UnsafeConfig as exc:
        return {"files": [], "notes": [str(exc)]}
    if CHRONY_CONF in planned and not os.path.isfile(CUSTOM_CHRONY):
        problem = check_chrony(planned[CHRONY_CONF])
        if problem:
            notes.insert(0, f"FEHLER: chronyd würde diese Konfiguration ablehnen ({problem}) – beim Speichern "
                            "bliebe die bisherige aktiv.")
    out = []
    for path, name, custom in ((CHRONY_CONF, "chrony.conf", CUSTOM_CHRONY), (PTP4L_CONF, "ptp4l.conf", CUSTOM_PTP4L)):
        entry: dict = {"name": name, "diff": [], "truncated": False}
        if path not in planned:
            entry["status"] = "unused"
            out.append(entry)
            continue
        current = _current(path)
        diff = list(difflib.unified_diff(
            redact_config(current or "").splitlines(), redact_config(planned[path]).splitlines(),
            fromfile=f"{name} (jetzt)", tofile=f"{name} (nach dem Speichern)", lineterm=""))
        entry["status"] = "custom" if os.path.isfile(custom) else "new" if current is None else "changed" if diff else "same"
        entry["truncated"] = len(diff) > PREVIEW_MAX_LINES
        entry["diff"] = diff[:PREVIEW_MAX_LINES]
        out.append(entry)
    return {"files": out, "notes": notes[:20]}


# --- chronyd prüft die neue chrony.conf, bevor sie die alte ersetzt ---------------------------------------
# „chronyd -p“ liest die Konfiguration, gibt sie aus und endet; eine Zeile, die chronyd nicht versteht,
# endet dort mit „Fatal error“ und Exit-Code 1 – genau wie beim echten Start. So bleibt bei einer
# abgelehnten Einstellung die bisherige Datei stehen, statt dass chronyd beim Neustart abbricht und den
# Container mitnimmt. Ohne chronyd (Tests, Entwicklung) entfällt die Prüfung.
CHRONYD_BIN = os.environ.get("NTPGUI_CHRONYD", "/usr/sbin/chronyd")
CHECK_TIMEOUT = 20
CONFIG_ERROR_FILE = "config-error"   # im RUN_DIR des Supervisors: Grund der letzten Ablehnung


class ConfigRejected(RuntimeError):
    """chronyd lehnt die erzeugte Konfiguration ab – es wurde nichts ersetzt."""


def _one_line(text: str, limit: int = 200) -> str:
    text = " ".join(str(text).split())
    text = "".join(c if c.isprintable() and c not in '"\\$`' else "'" for c in text)
    return text[:limit]


def check_chrony(content: str, binary: str | None = None) -> str | None:
    """None, wenn chronyd die Konfiguration annimmt (oder nicht prüfen kann); sonst der Grund."""
    binary = binary or CHRONYD_BIN
    if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
        return None
    fd, tmp = tempfile.mkstemp(prefix="ntpgui-pruefung-", suffix=".conf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            proc = subprocess.run([binary, "-p", "-f", tmp], capture_output=True, timeout=CHECK_TIMEOUT,
                                  check=False)
        except subprocess.TimeoutExpired:
            _log("chrony", "HINWEIS: Prüfung der Konfiguration dauerte zu lange – ohne Prüfung weiter.")
            return None
        except OSError as exc:
            _log("chrony", f"HINWEIS: Konfiguration nicht prüfbar ({exc}) – ohne Prüfung weiter.")
            return None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
    if proc.returncode == 0:
        return None
    err = proc.stderr.decode("utf-8", "replace")
    match = re.search(r"Fatal error\s*:\s*(.+)", err)
    reason = match.group(1) if match else (err.strip().splitlines() or [f"Exit-Code {proc.returncode}"])[-1]
    reason = reason.replace(f" in file {tmp}", "").replace(tmp, "chrony.conf")
    return _one_line(reason) or f"Exit-Code {proc.returncode}"


def _config_error_path(env: dict) -> str | None:
    run_dir = env.get("NTPGUI_RUN_DIR")
    return os.path.join(run_dir, CONFIG_ERROR_FILE) if run_dir else None


def _note_config_error(env: dict, reason: str | None) -> None:
    """Grund der Ablehnung für den Supervisor (Status/Ereignis) ablegen – oder entfernen."""
    path = _config_error_path(env)
    if not path:
        return
    with contextlib.suppress(OSError):
        if reason:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(_one_line(reason) + "\n")
        else:
            os.unlink(path)


def _rejected(files: list[tuple[str, str]]) -> str | None:
    content = dict(files).get(CHRONY_CONF)
    return check_chrony(content) if content is not None else None


def _quiet(*_args, **_kwargs) -> None:
    return None


def _problem(cfg: dict, env: dict) -> str | None:
    """Wie apply prüfen, aber still und ohne etwas zu kopieren: None, wenn chronyd annimmt."""
    try:
        nts = prepare_nts_files(cfg, warn=_quiet, ids=None, dry_run=True) or ()
        return _rejected(planned_files(cfg, env, nts_files=nts, log=_quiet))
    except UnsafeConfig as exc:
        return str(exc)


def check_saved(saved: dict, env: dict | None = None) -> str | None:
    """Würde chronyd die Konfiguration mit diesen gespeicherten Werten ablehnen? Dann der Grund – aber nur,
    wenn es an diesen Werten liegt: Lehnt chronyd schon die bisherige Konfiguration ab (Ursache in der
    Umgebung, z. B. EXTRA_CHRONY_CONF), ist das kein Grund, eine Änderung im Dashboard abzuweisen."""
    env = dict(os.environ if env is None else env)
    if os.path.isfile(CUSTOM_CHRONY) or not (os.path.isfile(CHRONYD_BIN) and os.access(CHRONYD_BIN, os.X_OK)):
        return None
    cfg = {key: entry["value"] for key, entry in settings.effective(env, saved=saved).items()}
    problem = _problem(cfg, env)
    if problem is None or _problem(settings.values(env), env) is not None:
        return None
    return problem


def check_changes(changes: dict, defaults=None, env: dict | None = None) -> str | None:
    """check_saved für ungespeicherte Änderungen aus dem Dashboard (vor settings.save)."""
    env = dict(os.environ if env is None else env)
    return check_saved(settings.saved_after(changes, defaults, env), env)


# Gespeicherte Einstellungen, die den Zeitserver einschränken. Ein Start ohne sie liefe weniger geschützt
# als eingestellt – lieber gar nicht starten (siehe _start_fallback).
PROTECTIVE_SETTINGS = ("bind_address", "allow_networks", "deny_networks", "ntp_ratelimit")


def emergency_values(cfg: dict, env: dict) -> dict:
    """Werte für den Notbetrieb bei nicht lesbarer settings.json: Die dort gespeicherten schützenden
    Einstellungen sind unbekannt, also nicht lockerer werden als eingestellt sein könnte. Erlaubte Netze nur
    aus der Umgebung (sonst keinem Client antworten), Ratelimit „streng“; Bind-Adresse und gesperrte Netze
    gelten wie in der Umgebung."""
    cfg = dict(cfg)
    cfg["ntp_ratelimit"] = "streng"
    if "ALLOW_NETWORKS" not in env:
        cfg["allow_networks"] = []
    return cfg


def _start_fallback(env: dict, problem: str) -> dict:
    """Beim Start lehnt chronyd die Konfiguration ab. Ursache finden und nur dann ohne den schuldigen
    gespeicherten Wert starten, wenn dabei keine schützende Einstellung wegfällt. Sonst ConfigRejected."""
    defaults_only = {key: entry["value"] for key, entry in settings.effective(env, saved={}).items()}
    if _problem(defaults_only, env) is not None:
        # Auch ohne Dashboard-Werte abgelehnt: Die Ursache steht in der Umgebung (Compose-Datei).
        cause = "der Compose-Datei (Umgebungsvariablen)"
        if env.get("EXTRA_CHRONY_CONF") and _problem(
                settings.values(env), {k: v for k, v in env.items() if k != "EXTRA_CHRONY_CONF"}) is None:
            cause = "EXTRA_CHRONY_CONF"
        _log("chrony", f"FEHLER: Die Ursache liegt in {cause}, nicht im Dashboard – bitte dort korrigieren.")
        raise ConfigRejected(problem)
    saved = settings.saved_values()
    droppable = [key for key in saved if key not in PROTECTIVE_SETTINGS]
    # Erst einen einzelnen schuldigen Wert suchen, dann alle nicht schützenden zusammen weglassen.
    attempts = [[key] for key in droppable] + ([droppable] if len(droppable) > 1 else [])
    for dropped in attempts:
        rest = {key: value for key, value in saved.items() if key not in dropped}
        cfg = {key: entry["value"] for key, entry in settings.effective(env, saved=rest).items()}
        if _problem(cfg, env) is None:
            names = ", ".join(settings.FIELDS.get(key, {}).get("label", key) for key in dropped)
            _log("chrony", f"WARNUNG: Start ohne die gespeicherte Einstellung „{names}“ (dort gilt Umgebung bzw. "
                           "Standard). Korrigiere sie im Dashboard und speichere erneut.")
            return cfg
    _log("chrony", "FEHLER: Die Ablehnung betrifft schützende Einstellungen (Bind-Adresse, erlaubte bzw. "
                   "gesperrte Netze, Ratelimit). Ohne sie liefe der Zeitserver weniger geschützt als eingestellt "
                   "– kein Start. Korrigiere den Wert in settings.json im Datenverzeichnis.")
    raise ConfigRejected(problem)


def apply(env: dict | None = None, fallback: bool = False) -> dict:
    """Schreibt die Konfiguration und liefert die Werte für den Supervisor.

    Lehnt chronyd die neue chrony.conf ab, wirft apply ConfigRejected und ersetzt nichts. fallback (beim
    Start des Containers): dann ohne den schuldigen im Dashboard gespeicherten Wert erzeugen – ein
    gespeicherter Fehler soll nicht jeden weiteren Start verhindern; schützende Einstellungen fallen dabei
    nie weg (_start_fallback)."""
    env = dict(os.environ if env is None else env)
    unreadable = settings.load_error()
    cfg = settings.values(env)
    if unreadable:
        cfg = emergency_values(cfg, env)
        # Den Grund selbst meldet settings beim Lesen (einmal je Prozess).
        _log("chrony", "WARNUNG: Notbetrieb, bis settings.json wieder lesbar ist – die dort gespeicherten "
                       "schützenden Einstellungen (Bind-Adresse, erlaubte bzw. gesperrte Netze, Ratelimit) sind "
                       "nicht bekannt. Der Zeitserver antwortet nur Netzen aus ALLOW_NETWORKS "
                       f"({', '.join(cfg['allow_networks']) or 'nicht gesetzt: keinem Client'}), "
                       "mit Ratelimit „streng“. Sonst gelten Umgebung und Standardwerte.")
    for key, entry in settings.effective(env).items():
        if entry["error"]:
            _log("config", f"WARNUNG {key}: {entry['error']} – verwende {entry['value']!r}")

    for note in expert_env_warnings(env):
        _log("config", note)
    for note in exposure_warnings(cfg):
        _log("chrony", note)

    try:
        wait = int(env.get("GPS_WAIT_SECONDS", "10") or 10)
    except ValueError:
        wait = 10
    if cfg["gps_enable"] and not _wait_for(cfg["gps_device"], wait):
        _log("gps", f"WARNUNG: {cfg['gps_device']} nicht gefunden.")
    if cfg["gps_pps_device"]:
        _wait_for(cfg["gps_pps_device"], wait)

    # Erst beide Dateien vollständig erzeugen, dann gemeinsam ersetzen: Scheitert ptp4l.conf,
    # darf chrony.conf nicht schon neu sein (der Supervisor meldet dann „bisherige Einstellungen aktiv“).
    try:
        files = planned_files(cfg, env, nts_files=prepare_nts_files(cfg) or ())
        problem = _rejected(files)
    except UnsafeConfig as exc:
        files, problem = [], str(exc)
    if problem:
        _log("chrony", f"FEHLER: chronyd lehnt die neue Konfiguration ab: {problem}")
        _note_config_error(env, problem)
        if not fallback:
            raise ConfigRejected(problem)
        cfg = _start_fallback(env, problem)
        if unreadable:
            cfg = emergency_values(cfg, env)
        files = planned_files(cfg, env, nts_files=prepare_nts_files(cfg) or ())
        second = _rejected(files)
        if second:
            _log("chrony", f"FEHLER: auch ohne den gespeicherten Wert abgelehnt: {second}")
            raise ConfigRejected(second)
    else:
        _note_config_error(env, None)
    ptp_on = bool(cfg["ptp_enable"]) and bool(cfg["ptp_interface"])
    # Erst ALLES berechnen, was noch werfen kann (phc2sys-Plan, DNS-Modus, Pfade, Warnungen),
    # und erst danach die Dateien ersetzen. Wirft ein Schritt, bleiben chrony.conf/ptp4l.conf
    # unverändert und passen weiter zu den laufenden Diensten und ihren NTPGUI_*-Variablen.
    phc = phc2sys_plan(cfg, env)
    dns_notes = list(dnsfwd.config_warnings(cfg))
    result = {
        "NTPGUI_DNS_MODE": dnsfwd.effective_mode(cfg),
        "NTPGUI_GPS_START": "1" if gps_device_ok(cfg) else "0",
        "NTPGUI_GPS_ENABLE": "1" if cfg["gps_enable"] else "0",
        "NTPGUI_HOTPLUG_PATHS": " ".join(hotplug_paths(cfg)),
        "NTPGUI_GPS_DEVICE": cfg["gps_device"],
        "NTPGUI_GPS_SPEED": cfg["gps_speed"],
        "NTPGUI_PTP_START": "1" if ptp_on else "0",
        "NTPGUI_PTP_INTERFACE": cfg["ptp_interface"],
        "NTPGUI_PTP_MODE": cfg["ptp_mode"],
        "NTPGUI_PTP_DOMAIN": str(cfg["ptp_domain"]),
        "NTPGUI_PTP_UDS": settings.ptp_uds_address(env),
        "NTPGUI_PHC2SYS_START": "1" if phc["start"] else "0",
        "NTPGUI_PHC2SYS_OPTIONS": phc["options"],
        "NTPGUI_CHRONY_NOCONTROL": "1" if phc["nocontrol"] else "0",
        "NTPGUI_NTS_WATCH": " ".join(nts_watch_paths(cfg)),
        # Client-Messung beim Start an? Nur dann bekommt das Dashboard CAP_NET_RAW (Mitlesen).
        "NTPGUI_CLIENTMON": "1" if cfg.get("clientmon_enable") else "0",
    }

    # Letzter Schritt vor dem return. Restfall (bewusst nicht gelöst): _write_all benennt zwei
    # Dateien nacheinander um. Scheitert die zweite Umbenennung (z. B. Dateisystem fällt weg),
    # ist chrony.conf schon neu und ptp4l.conf noch alt. Ein echtes gemeinsames Ersetzen gäbe es
    # nur über ein Verzeichnis + Symlink-Tausch; das lohnt den Umbau nicht.
    _write_all(files)
    _log("chrony", f"Konfiguration geschrieben nach {CHRONY_CONF}")

    for note in phc["notes"]:
        _log("ptp", note)
    if phc["start"]:
        direction = ("Systemuhr → PTP-Uhr" if not phc["nocontrol"] else "PTP-Uhr → Systemuhr")
        _log("ptp", f"phc2sys {phc['options']} ({direction}, chronyd "
                    f"{'mit -x' if phc['nocontrol'] else 'regelt weiter'})")
    for note in dns_notes:
        _log("dns", note)
    return result


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "apply"
    if command == "apply":
        try:
            # stdout trägt nur die Shell-Zuweisungen für den Entrypoint (eval); Meldungen aus den Modulen
            # gehören ins Log.
            with contextlib.redirect_stdout(sys.stderr):
                values = apply(fallback="--start" in argv[2:])
        except (ConfigRejected, UnsafeConfig):
            return 1  # Grund steht schon im Log und in RUN_DIR/config-error
        for key, value in values.items():
            print(f"{key}={shlex.quote(value)}")
        return 0
    if command == "print":
        print(render_chrony(settings.values()), end="")
        return 0
    print("Aufruf: confgen.py apply [--start]|print", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
