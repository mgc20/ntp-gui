"""Erzeugt chrony.conf und ptp4l.conf aus den effektiven Einstellungen.

Wird vom Entrypoint beim Start und bei jedem Neuladen aufgerufen:

    eval "$(python3 /app/confgen.py apply)"

`apply` schreibt die Konfigurationsdateien und gibt Shell-Zuweisungen für die
Werte aus, die der Supervisor zum Starten der Dienste braucht. Warnungen
gehen auf stderr und landen so im Container-Log.
"""

from __future__ import annotations

import os
import shlex
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import settings  # noqa: E402

CHRONY_CONF = os.environ.get("CHRONY_CONF", "/etc/chrony/chrony.conf")
PTP4L_CONF = os.environ.get("PTP4L_CONF", "/etc/linuxptp/ptp4l.conf")
CUSTOM_CHRONY = os.environ.get("CUSTOM_CHRONY_CONF", "/config/chrony.conf")
CUSTOM_PTP4L = os.environ.get("CUSTOM_PTP4L_CONF", "/config/ptp4l.conf")
NTS_DUMPDIR = "/var/lib/chrony"


def _log(area: str, message: str) -> None:
    print(f"[{area}] {message}", file=sys.stderr, flush=True)


def _num(value) -> str:
    """Zahl ohne überflüssige Nachkommastellen, wie chrony sie erwartet."""
    if isinstance(value, float):
        text = f"{value:.9f}".rstrip("0").rstrip(".")
        return text if text not in {"", "-0"} else "0"
    return str(value)


def gps_device_ok(cfg: dict) -> bool:
    return bool(cfg["gps_enable"]) and os.path.exists(cfg["gps_device"])


def render_chrony(cfg: dict, env: dict | None = None, warn=_log) -> str:
    env = os.environ if env is None else env
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
        parts = [
            f"refclock SHM {int(env.get('GPS_SHM_UNIT', '0') or 0)} refid {cfg['gps_refid']}",
            f"offset {_num(float(cfg['gps_offset']))} delay {_num(float(cfg['gps_delay']))}",
            f"precision {_num(float(cfg['gps_precision']))} poll {cfg['gps_poll']}",
            f"filter {cfg['gps_filter']}",
        ]
        if cfg["gps_select"] in {"prefer", "noselect"}:
            parts.append(cfg["gps_select"])
        if cfg["gps_refclock_options"]:
            parts.append(cfg["gps_refclock_options"])
        lines.append(" ".join(_dedupe(" ".join(parts).split())))
        pps = cfg["gps_pps_device"]
        pps_poll = env.get("GPS_PPS_POLL", "3") or "3"
        pps_extra = env.get("GPS_PPS_OPTIONS", "")
        if pps and os.path.exists(pps):
            lines.append(f"refclock PPS {pps} lock {cfg['gps_refid']} refid PPS poll {pps_poll}"
                         + (f" {pps_extra}" if pps_extra else ""))
        elif pps:
            # chronyd bricht mit "Could not open" ab und der Container startet in
            # einer Schleife neu - lieber ohne PPS starten und warnen.
            warn("gps", f"WARNUNG: {pps} existiert nicht – PPS-Refclock wird übersprungen.")
        elif cfg["gps_pps_shm"]:
            unit = env.get("GPS_PPS_SHM_UNIT", "1") or "1"
            lines.append(f"refclock SHM {unit} refid PPS precision 1e-7 lock {cfg['gps_refid']} "
                         f"poll {pps_poll}" + (f" {pps_extra}" if pps_extra else ""))

    phc = cfg["phc_refclock"]
    if phc:
        if os.path.exists(phc):
            options = env.get("PHC_REFCLOCK_OPTIONS", "poll 0 dpoll -2 offset 0 stratum 1")
            lines.append(f"refclock PHC {phc} {options}".rstrip())
        else:
            warn("ptp", f"WARNUNG: {phc} existiert nicht – PHC-Refclock wird übersprungen.")

    lines += [
        "",
        "driftfile /var/lib/chrony/chrony.drift",
        # Messhistorie über Neustarts retten (chronyd -r lädt sie wieder).
        "dumpdir /var/lib/chrony",
        f"makestep {cfg['makestep']}",
        f"maxupdateskew {env.get('MAXUPDATESKEW', '100.0') or '100.0'}",
        f"minsources {cfg['ntp_minsources']}",
        "logdir /var/log/chrony",
    ]
    if env.get("CHRONY_LOG"):
        lines.append(f"log {env['CHRONY_LOG']}")
    if cfg["leapsectz"]:
        lines.append(f"leapsectz {cfg['leapsectz']}")
    lines += [
        f"clientloglimit {env.get('CLIENTLOGLIMIT', '10000000') or '10000000'}",
        "bindcmdaddress /var/run/chrony/chronyd.sock",
        "cmdport 0",
        f"port {cfg['ntp_port']}",
    ]
    if cfg["bind_address"]:
        lines.append(f"bindaddress {cfg['bind_address']}")
    if cfg["ntp_hw_timestamp"]:
        lines.append(f"hwtimestamp {cfg['ntp_hw_timestamp_interface'] or '*'}")
    if cfg["ntp_ratelimit"]:
        lines.append("ratelimit interval 1 burst 16 leak 2")

    if uses_nts or cfg["nts_server_enable"]:
        lines += ["", f"ntsdumpdir {NTS_DUMPDIR}"]
        if uses_nts and cfg["nts_nocerttimecheck"]:
            lines.append("nocerttimecheck 1")
    if cfg["nts_server_enable"]:
        cert, key = cfg["nts_server_cert"], cfg["nts_server_key"]
        if os.path.exists(cert) and os.path.exists(key):
            lines += [f"ntsservercert {cert}", f"ntsserverkey {key}"]
        else:
            warn("nts", f"WARNUNG: NTS-Server aktiviert, aber {cert} oder {key} fehlt – "
                        "NTS-Server bleibt aus.")

    lines.append("")
    lines += [f"allow {net}" for net in cfg["allow_networks"]]
    lines += [f"deny {net}" for net in cfg["deny_networks"]]

    if cfg["serve_unsynced"]:
        lines += ["", "# Auch ohne erreichbare Quelle Zeit ausliefern (Inselbetrieb).",
                  f"local stratum {cfg['local_stratum']}"]

    extra = env.get("EXTRA_CHRONY_CONF", "")
    if extra:
        lines += ["", "# EXTRA_CHRONY_CONF", extra.encode().decode("unicode_escape")]
    return "\n".join(lines) + "\n"


def render_ptp4l(cfg: dict, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    mode = cfg["ptp_mode"]
    slave_only = 1 if mode == "slave" else 0
    master_only = 1 if mode == "master" else 0
    extra = env.get("EXTRA_PTP4L_CONF", "")
    body = f"""# Generiert von ntp-gui.
[global]
domainNumber            {cfg['ptp_domain']}
slaveOnly               {slave_only}
masterOnly              {master_only}
priority1               {cfg['ptp_priority1']}
priority2               {cfg['ptp_priority2']}
clockClass              {cfg['ptp_clock_class']}
delay_mechanism         {cfg['ptp_delay_mechanism']}
network_transport       {cfg['ptp_transport']}
time_stamping           {cfg['ptp_time_stamping']}
tx_timestamp_timeout    {env.get('PTP_TX_TIMESTAMP_TIMEOUT', '10') or '10'}
logSyncInterval         {cfg['ptp_log_sync_interval']}
logMinDelayReqInterval  {env.get('PTP_LOG_MIN_DELAY_REQ_INTERVAL', '-3') or '-3'}
logAnnounceInterval     {env.get('PTP_LOG_ANNOUNCE_INTERVAL', '1') or '1'}
announceReceiptTimeout  {env.get('PTP_ANNOUNCE_RECEIPT_TIMEOUT', '3') or '3'}
summary_interval        {cfg['ptp_summary_interval']}
uds_address             {env.get('PTP_UDS_ADDRESS', '/var/run/ptp4l') or '/var/run/ptp4l'}
"""
    if extra:
        body += extra.encode().decode("unicode_escape") + "\n"
    body += f"\n[{cfg['ptp_interface'] or 'eth0'}]\n"
    return body


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


def _write(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ntpgui-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _wait_for(path: str, seconds: int) -> bool:
    for _ in range(max(0, seconds)):
        if os.path.exists(path):
            return True
        time.sleep(1)
    return os.path.exists(path)


def apply(env: dict | None = None) -> dict:
    """Schreibt die Konfiguration und liefert die Werte für den Supervisor."""
    env = dict(os.environ if env is None else env)
    cfg = settings.values(env)
    for key, entry in settings.effective(env).items():
        if entry["error"]:
            _log("config", f"WARNUNG {key}: {entry['error']} – verwende {entry['value']!r}")

    try:
        wait = int(env.get("GPS_WAIT_SECONDS", "10") or 10)
    except ValueError:
        wait = 10
    if cfg["gps_enable"] and not _wait_for(cfg["gps_device"], wait):
        _log("gps", f"WARNUNG: {cfg['gps_device']} nicht gefunden.")
    if cfg["gps_pps_device"]:
        _wait_for(cfg["gps_pps_device"], wait)

    if os.path.isfile(CUSTOM_CHRONY):
        _log("chrony", f"verwende gemountete {CUSTOM_CHRONY}")
        with open(CUSTOM_CHRONY, encoding="utf-8") as handle:
            _write(CHRONY_CONF, handle.read())
    else:
        _write(CHRONY_CONF, render_chrony(cfg, env))
    _log("chrony", f"Konfiguration geschrieben nach {CHRONY_CONF}")

    ptp_on = bool(cfg["ptp_enable"]) and bool(cfg["ptp_interface"])
    if cfg["ptp_enable"] and not cfg["ptp_interface"]:
        _log("ptp", "WARNUNG: PTP ist aktiviert, aber kein Interface gewählt – PTP wird nicht gestartet.")
    if ptp_on:
        if os.path.isfile(CUSTOM_PTP4L):
            _log("ptp", f"verwende gemountete {CUSTOM_PTP4L}")
            with open(CUSTOM_PTP4L, encoding="utf-8") as handle:
                _write(PTP4L_CONF, handle.read())
        else:
            _write(PTP4L_CONF, render_ptp4l(cfg, env))

    return {
        "NTPGUI_GPS_START": "1" if gps_device_ok(cfg) else "0",
        "NTPGUI_GPS_DEVICE": cfg["gps_device"],
        "NTPGUI_GPS_SPEED": cfg["gps_speed"],
        "NTPGUI_PTP_START": "1" if ptp_on else "0",
        "NTPGUI_PTP_INTERFACE": cfg["ptp_interface"],
        "NTPGUI_PTP_MODE": cfg["ptp_mode"],
        "NTPGUI_PTP_DOMAIN": str(cfg["ptp_domain"]),
        "NTPGUI_PHC2SYS_START": "1" if ptp_on and cfg["phc2sys_enable"] else "0",
        "NTPGUI_PHC2SYS_OPTIONS": cfg["phc2sys_options"],
    }


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "apply"
    if command == "apply":
        for key, value in apply().items():
            print(f"{key}={shlex.quote(value)}")
        return 0
    if command == "print":
        print(render_chrony(settings.values()), end="")
        return 0
    print("Aufruf: confgen.py apply|print", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
