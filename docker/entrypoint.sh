#!/usr/bin/env bash
# Generates the chrony/ptp4l configuration from environment variables and
# supervises chronyd, ptp4l, phc2sys and the dashboard in one container.
set -euo pipefail

CHRONY_CONF="${CHRONY_CONF:-/etc/chrony/chrony.conf}"
PTP4L_CONF="${PTP4L_CONF:-/etc/linuxptp/ptp4l.conf}"
PTP_LOG_FILE="${PTP_LOG_FILE:-/var/log/ptp4l.log}"
APP_DIR="${APP_DIR:-/app}"
PIDS=()

log() { printf '[%s] %s\n' "$1" "${*:2}"; }

is_true() {
  case "${1,,}" in 1|true|yes|on) return 0 ;; *) return 1 ;; esac
}

# CAP_SYS_TIME is bit 25 of the effective capability set. Without it chronyd
# cannot discipline the clock and must be started with -x.
has_sys_time() {
  local caps
  caps=$(awk '/^CapEff:/ {print $2}' /proc/self/status 2>/dev/null || echo 0)
  python3 -c "import sys; sys.exit(0 if (int('${caps:-0}', 16) >> 25) & 1 else 1)"
}

# Beim Booten koennen USB-/PPS-Geraete spaeter auftauchen als der Container.
wait_for_device() {
  local path="$1" seconds="${2:-10}"
  [[ -z "$path" ]] && return 1
  for _ in $(seq 1 "$seconds"); do
    [[ -e "$path" ]] && return 0
    sleep 1
  done
  [[ -e "$path" ]]
}

split_list() {
  # comma or whitespace separated -> one entry per line
  tr ',' '\n' <<<"${1:-}" | tr -s ' \t' '\n' | sed '/^$/d'
}

write_chrony_conf() {
  if [[ -f /config/chrony.conf ]]; then
    log chrony "verwende gemountete /config/chrony.conf"
    install -m 0644 /config/chrony.conf "$CHRONY_CONF"
    return
  fi

  local conf
  conf=$(mktemp)
  {
    echo "# Generiert von ntp-gui beim Containerstart – Änderungen gehen verloren."
    echo "# Für eine eigene Konfiguration /config/chrony.conf mounten."
    echo

    local options="${NTP_SERVER_OPTIONS:-iburst}"
    while read -r pool; do
      [[ -n "$pool" ]] && echo "pool ${pool} ${options} maxsources ${NTP_POOL_MAXSOURCES:-4}"
    done < <(split_list "${NTP_POOLS:-}")

    while read -r server; do
      [[ -n "$server" ]] && echo "server ${server} ${options}"
    done < <(split_list "${NTP_SERVERS:-}")

    while read -r peer; do
      [[ -n "$peer" ]] && echo "peer ${peer} ${options}"
    done < <(split_list "${NTP_PEERS:-}")

    if is_true "${GPS_ENABLE:-false}"; then
      # gpsd hands the GPS time to chrony through a shared memory segment.
      echo "refclock SHM ${GPS_SHM_UNIT:-0} refid ${GPS_REFID:-GPS}" \
           "offset ${GPS_OFFSET:-0.0} delay ${GPS_DELAY:-0.2}" \
           "precision ${GPS_PRECISION:-1e-1} poll ${GPS_POLL:-3}" \
           "filter ${GPS_FILTER:-3} ${GPS_REFCLOCK_OPTIONS:-}"
      if [[ -n "${GPS_PPS_DEVICE:-}" ]] && [[ -e "${GPS_PPS_DEVICE}" ]]; then
        # A real 1PPS signal: nanosecond edges, disciplined by the GPS refclock.
        echo "refclock PPS ${GPS_PPS_DEVICE} lock ${GPS_REFID:-GPS} refid PPS" \
             "poll ${GPS_PPS_POLL:-3} ${GPS_PPS_OPTIONS:-}"
      elif [[ -n "${GPS_PPS_DEVICE:-}" ]]; then
        # chronyd would abort with "Could not open" and restart-loop the container.
        log gps "WARNUNG: ${GPS_PPS_DEVICE} existiert nicht – PPS-Refclock wird übersprungen." >&2
        log gps "         Gerät mit '--device ${GPS_PPS_DEVICE}' durchreichen." >&2
      elif is_true "${GPS_PPS_SHM:-false}"; then
        echo "refclock SHM ${GPS_PPS_SHM_UNIT:-1} refid PPS precision 1e-7" \
             "lock ${GPS_REFID:-GPS} poll ${GPS_PPS_POLL:-3} ${GPS_PPS_OPTIONS:-}"
      fi
    fi

    if [[ -n "${PHC_REFCLOCK:-}" ]]; then
      if [[ -e "${PHC_REFCLOCK}" ]]; then
        # Use the NIC's PTP hardware clock as a reference (PTP -> NTP bridge).
        echo "refclock PHC ${PHC_REFCLOCK} ${PHC_REFCLOCK_OPTIONS:-poll 0 dpoll -2 offset 0 stratum 1}"
      else
        log ptp "WARNUNG: ${PHC_REFCLOCK} existiert nicht – PHC-Refclock wird übersprungen." >&2
      fi
    fi

    echo
    echo "driftfile /var/lib/chrony/chrony.drift"
    echo "makestep ${MAKESTEP:-1.0 3}"
    echo "maxupdateskew ${MAXUPDATESKEW:-100.0}"
    echo "logdir /var/log/chrony"
    [[ -n "${CHRONY_LOG:-}" ]] && echo "log ${CHRONY_LOG}"
    echo "leapsectz ${LEAPSECTZ:-right/UTC}"
    echo "clientloglimit ${CLIENTLOGLIMIT:-10000000}"
    echo "bindcmdaddress /var/run/chrony/chronyd.sock"
    echo "cmdport 0"
    echo "port ${NTP_PORT:-123}"
    [[ -n "${BIND_ADDRESS:-}" ]] && echo "bindaddress ${BIND_ADDRESS}"

    if is_true "${NTP_HW_TIMESTAMP:-false}"; then
      echo "hwtimestamp ${NTP_HW_TIMESTAMP_INTERFACE:-*}"
    fi

    echo
    while read -r network; do
      [[ -n "$network" ]] && echo "allow ${network}"
    done < <(split_list "${ALLOW_NETWORKS:-}")
    while read -r network; do
      [[ -n "$network" ]] && echo "deny ${network}"
    done < <(split_list "${DENY_NETWORKS:-}")

    if is_true "${SERVE_UNSYNCED:-true}"; then
      echo
      echo "# Auch ohne erreichbare Uplink-Quelle Zeit ausliefern (Inselbetrieb)."
      echo "local stratum ${LOCAL_STRATUM:-10}"
    fi

    if [[ -n "${EXTRA_CHRONY_CONF:-}" ]]; then
      echo
      echo "# EXTRA_CHRONY_CONF"
      printf '%b\n' "${EXTRA_CHRONY_CONF}"
    fi
  } >"$conf"

  install -m 0644 "$conf" "$CHRONY_CONF"
  rm -f "$conf"
}

write_ptp4l_conf() {
  if [[ -f /config/ptp4l.conf ]]; then
    log ptp "verwende gemountete /config/ptp4l.conf"
    install -m 0644 /config/ptp4l.conf "$PTP4L_CONF"
    return
  fi

  local slave_only=0 master_only=0
  case "${PTP_MODE:-auto}" in
    slave|client) slave_only=1 ;;
    master|grandmaster|server) master_only=1 ;;
  esac

  local delay_mechanism="${PTP_DELAY_MECHANISM:-E2E}"
  local network_transport="${PTP_TRANSPORT:-UDPv4}"

  cat >"$PTP4L_CONF" <<EOF
# Generiert von ntp-gui beim Containerstart.
[global]
domainNumber            ${PTP_DOMAIN:-0}
slaveOnly               ${slave_only}
masterOnly              ${master_only}
priority1               ${PTP_PRIORITY1:-128}
priority2               ${PTP_PRIORITY2:-128}
clockClass              ${PTP_CLOCK_CLASS:-248}
delay_mechanism         ${delay_mechanism}
network_transport       ${network_transport}
time_stamping           ${PTP_TIME_STAMPING:-hardware}
tx_timestamp_timeout    ${PTP_TX_TIMESTAMP_TIMEOUT:-10}
logSyncInterval         ${PTP_LOG_SYNC_INTERVAL:--3}
logMinDelayReqInterval  ${PTP_LOG_MIN_DELAY_REQ_INTERVAL:--3}
logAnnounceInterval     ${PTP_LOG_ANNOUNCE_INTERVAL:-1}
announceReceiptTimeout  ${PTP_ANNOUNCE_RECEIPT_TIMEOUT:-3}
summary_interval        ${PTP_SUMMARY_INTERVAL:-4}
uds_address             ${PTP_UDS_ADDRESS:-/var/run/ptp4l}
${EXTRA_PTP4L_CONF:-}

[${PTP_INTERFACE:-eth0}]
EOF
}

start() {
  local name="$1"; shift
  log "$name" "starte: $*"
  "$@" &
  PIDS+=("$!")
}

shutdown() {
  log main "beende Dienste …"
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 0
}
trap shutdown SIGTERM SIGINT

mkdir -p /var/run/chrony /var/lib/chrony /var/log/chrony /etc/linuxptp

# chronyd drops privileges to its own user; if the runtime directories belong to
# root it silently disables the command socket and the dashboard goes blind.
CHRONY_USER=""
for candidate in _chrony chrony; do
  if id -u "$candidate" >/dev/null 2>&1; then CHRONY_USER="$candidate"; break; fi
done
if [[ -n "$CHRONY_USER" ]]; then
  chown -R "${CHRONY_USER}:${CHRONY_USER}" /var/run/chrony /var/lib/chrony /var/log/chrony
fi
chmod 750 /var/run/chrony

if is_true "${GPS_ENABLE:-false}"; then
  GPS_DEVICE="${GPS_DEVICE:-/dev/ttyACM0}"
  wait_for_device "$GPS_DEVICE" "${GPS_WAIT_SECONDS:-10}" \
    || log gps "WARNUNG: ${GPS_DEVICE} nicht gefunden."
  [[ -n "${GPS_PPS_DEVICE:-}" ]] && wait_for_device "$GPS_PPS_DEVICE" "${GPS_WAIT_SECONDS:-10}" || true
fi

write_chrony_conf
log chrony "Konfiguration geschrieben nach ${CHRONY_CONF}"

CHRONYD_ARGS=(-d -f "$CHRONY_CONF")
if is_true "${DISABLE_CLOCK_CONTROL:-auto}"; then
  CHRONYD_ARGS+=(-x)
  log chrony "Uhrensteuerung deaktiviert (DISABLE_CLOCK_CONTROL)"
elif ! has_sys_time; then
  CHRONYD_ARGS+=(-x)
  log chrony "WARNUNG: CAP_SYS_TIME fehlt – chronyd läuft mit -x und stellt die Uhr nicht."
  log chrony "         Für einen echten Zeitserver den Container mit 'cap_add: [SYS_TIME]' starten."
fi
start chrony /usr/sbin/chronyd "${CHRONYD_ARGS[@]}"

if is_true "${GPS_ENABLE:-false}"; then
  if [[ ! -e "$GPS_DEVICE" ]]; then
    log gps "WARNUNG: ${GPS_DEVICE} existiert nicht – gpsd wird nicht gestartet."
    log gps "         Den Container mit '--device ${GPS_DEVICE}' bzw. 'devices:' starten."
  else
    GPSD_ARGS=(-N -n)
    [[ -n "${GPS_SPEED:-}" ]] && GPSD_ARGS+=(-s "${GPS_SPEED}")
    [[ -n "${GPS_OPTIONS:-}" ]] && GPSD_ARGS+=(${GPS_OPTIONS})
    # -n: gpsd liest den Empfänger auch ohne verbundenen Client. Ohne das
    # bekommt chrony niemals Zeitstempel.
    start gps /usr/sbin/gpsd "${GPSD_ARGS[@]}" "$GPS_DEVICE"
  fi
fi

if is_true "${PTP_ENABLE:-false}"; then
  if [[ -z "${PTP_INTERFACE:-}" ]]; then
    log ptp "WARNUNG: PTP_ENABLE=true, aber PTP_INTERFACE ist leer – PTP wird nicht gestartet."
  else
    write_ptp4l_conf
    : >"$PTP_LOG_FILE"
    log ptp "ptp4l auf ${PTP_INTERFACE} (Domain ${PTP_DOMAIN:-0}, Modus ${PTP_MODE:-auto})"
    /usr/sbin/ptp4l -f "$PTP4L_CONF" -i "${PTP_INTERFACE}" -m >>"$PTP_LOG_FILE" 2>&1 &
    PIDS+=("$!")

    if is_true "${PHC2SYS_ENABLE:-false}"; then
      sleep 2
      start phc2sys /usr/sbin/phc2sys ${PHC2SYS_OPTIONS:--a -r -m}
    fi
  fi
fi

export PTP_LOG_FILE CHRONY_CONF
start web python3 "${APP_DIR}/server.py"

# Exit as soon as any supervised process dies so the container restarts cleanly.
wait -n
log main "ein Dienst wurde beendet – Container wird gestoppt"
shutdown
