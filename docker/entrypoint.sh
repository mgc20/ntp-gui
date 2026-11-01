#!/usr/bin/env bash
# Startet und überwacht chronyd, gpsd, ptp4l, phc2sys und das Dashboard.
#
# Die Konfiguration erzeugt /app/confgen.py aus den Einstellungen (Dashboard >
# Umgebungsvariable > Standard). Ein SIGHUP – ausgelöst vom Dashboard nach dem
# Speichern – erzeugt die Konfiguration neu und startet nur die Zeitdienste
# neu; Container und Dashboard laufen weiter.
set -euo pipefail

CHRONY_CONF="${CHRONY_CONF:-/etc/chrony/chrony.conf}"
PTP4L_CONF="${PTP4L_CONF:-/etc/linuxptp/ptp4l.conf}"
PTP_LOG_FILE="${PTP_LOG_FILE:-/var/log/ptp4l.log}"
APP_DIR="${APP_DIR:-/app}"
RUN_DIR="${NTPGUI_RUN_DIR:-/run/ntp-gui}"
export CHRONY_CONF PTP4L_CONF PTP_LOG_FILE NTPGUI_RUN_DIR="$RUN_DIR"

SERVICE_PIDS=()   # Zeitdienste, Einträge "pid=comm"
WEB_PID=""        # Dashboard, "pid=comm"
RELOAD_REQUESTED=0

log() { printf '[%s] %s\n' "$1" "${*:2}"; }

is_true() {
  case "${1,,}" in 1|true|yes|on) return 0 ;; *) return 1 ;; esac
}

# CAP_SYS_TIME ist Bit 25 der effektiven Capabilities. Ohne darf chronyd die
# Uhr nicht stellen und muss mit -x laufen.
has_sys_time() {
  local caps
  caps=$(awk '/^CapEff:/ {print $2}' /proc/self/status 2>/dev/null || echo 0)
  python3 -c "
import sys
try:
    caps = int('${caps:-0}', 16)
except ValueError:
    sys.exit(1)
sys.exit(0 if (caps >> 25) & 1 else 1)" 2>/dev/null
}

# Einträge sind "pid=comm": der Watchdog prüft beides, damit ein recycelter PID
# nicht als lebender Dienst durchgeht.
spawn() {  # spawn <name> <cmd...>  -> setzt SPAWNED
  local name="$1" comm; shift
  comm=$(basename "$1")
  log "$name" "starte: $*"
  "$@" &
  SPAWNED="$!=${comm:0:15}"
}

service_alive() {
  local pid="${1%%=*}" comm="${1#*=}" actual
  actual=$(cat "/proc/${pid}/comm" 2>/dev/null) || return 1
  [[ "$actual" == "$comm" ]]
}

write_status() {  # write_status <state> <message>
  mkdir -p "$RUN_DIR"
  printf '{"state": "%s", "message": "%s", "time": %s}\n' \
    "$1" "${2//\"/\'}" "$(date +%s)" > "${RUN_DIR}/reload.json.tmp"
  mv -f "${RUN_DIR}/reload.json.tmp" "${RUN_DIR}/reload.json"
}

# --- Konfiguration erzeugen und Zeitdienste starten -------------------------
apply_config() {
  local out
  if ! out=$(python3 "${APP_DIR}/confgen.py" apply); then
    log config "FEHLER: Konfiguration konnte nicht erzeugt werden – bisherige bleibt aktiv."
    return 1
  fi
  eval "$out"
}

start_services() {
  local chronyd_args=(-d -r -f "$CHRONY_CONF")
  if is_true "${DISABLE_CLOCK_CONTROL:-auto}"; then
    chronyd_args+=(-x)
    log chrony "Uhrensteuerung deaktiviert (DISABLE_CLOCK_CONTROL)"
  elif ! has_sys_time; then
    chronyd_args+=(-x)
    log chrony "WARNUNG: CAP_SYS_TIME fehlt – chronyd läuft mit -x und stellt die Uhr nicht."
    log chrony "         Für einen echten Zeitserver den Container mit 'cap_add: [SYS_TIME]' starten."
  elif [[ "${NTPGUI_PHC2SYS_START:-0}" == 1 ]]; then
    # Zwei Regler auf derselben Uhr (phc2sys -r und chronyd) würden sich
    # gegenseitig die Korrekturen überschreiben: phc2sys stellt die Uhr,
    # chronyd liefert nur aus.
    chronyd_args+=(-x)
    log chrony "phc2sys steuert die Systemuhr – chronyd läuft mit -x und liefert nur aus."
  fi
  rm -f /run/chrony/chronyd.pid /var/run/chrony/chronyd.pid
  spawn chrony /usr/sbin/chronyd "${chronyd_args[@]}"
  SERVICE_PIDS=("$SPAWNED")

  if [[ "${NTPGUI_GPS_START:-0}" == 1 ]]; then
    local gpsd_args=(-N -n)
    [[ -n "${NTPGUI_GPS_SPEED:-}" ]] && gpsd_args+=(-s "$NTPGUI_GPS_SPEED")
    # shellcheck disable=SC2206  # GPS_OPTIONS ist bewusst eine Wortliste
    [[ -n "${GPS_OPTIONS:-}" ]] && gpsd_args+=(${GPS_OPTIONS})
    # -n: gpsd liest den Empfänger auch ohne Client – sonst bekommt chrony nie Zeit.
    spawn gps /usr/sbin/gpsd "${gpsd_args[@]}" "$NTPGUI_GPS_DEVICE"
    SERVICE_PIDS+=("$SPAWNED")
  fi

  if [[ "${NTPGUI_PTP_START:-0}" == 1 ]]; then
    : >"$PTP_LOG_FILE"
    log ptp "ptp4l auf ${NTPGUI_PTP_INTERFACE} (Domain ${NTPGUI_PTP_DOMAIN}, Modus ${NTPGUI_PTP_MODE})"
    /usr/sbin/ptp4l -f "$PTP4L_CONF" -i "$NTPGUI_PTP_INTERFACE" -m >>"$PTP_LOG_FILE" 2>&1 &
    SERVICE_PIDS+=("$!=ptp4l")
    if [[ "${NTPGUI_PHC2SYS_START:-0}" == 1 ]]; then
      sleep 2
      # shellcheck disable=SC2086  # Optionen sind eine geprüfte Wortliste
      spawn phc2sys /usr/sbin/phc2sys $NTPGUI_PHC2SYS_OPTIONS
      SERVICE_PIDS+=("$SPAWNED")
    fi
  fi
}

stop_services() {
  local entry
  for entry in "${SERVICE_PIDS[@]:-}"; do
    [[ -n "$entry" ]] && kill "${entry%%=*}" 2>/dev/null || true
  done
  for entry in "${SERVICE_PIDS[@]:-}"; do
    [[ -n "$entry" ]] && wait "${entry%%=*}" 2>/dev/null || true
  done
  SERVICE_PIDS=()
}

reload_services() {
  log main "Einstellungen geändert – Zeitdienste werden neu gestartet …"
  write_status running "Zeitdienste werden neu gestartet"
  stop_services
  if apply_config; then
    start_services
    write_status done "Neue Einstellungen aktiv"
    log main "Neustart abgeschlossen."
  else
    start_services
    write_status error "Konfiguration fehlerhaft – bisherige Einstellungen weiter aktiv"
  fi
}

shutdown() {
  # Exit-Code 0 nur beim geordneten Stoppen; ein weggestorbener Dienst muss
  # auch mit restart=on-failure einen Neustart auslösen.
  local code="${1:-0}"
  log main "beende Dienste …"
  stop_services
  [[ -n "$WEB_PID" ]] && kill "${WEB_PID%%=*}" 2>/dev/null || true
  wait 2>/dev/null || true
  exit "$code"
}
trap 'shutdown 0' SIGTERM SIGINT
trap 'RELOAD_REQUESTED=1' SIGHUP

# --- Vorbereitung ------------------------------------------------------------
mkdir -p /var/run/chrony /var/lib/chrony /var/log/chrony /etc/linuxptp "$RUN_DIR"
echo "$$" > "${RUN_DIR}/supervisor.pid"
write_status idle "bereit"

# chronyd legt seine Rechte ab; gehören die Verzeichnisse root, schaltet er
# still den Kommando-Socket ab und das Dashboard sieht nichts mehr. Das
# Einstellungsverzeichnis des Dashboards bleibt root vorbehalten.
CHRONY_USER=""
for candidate in _chrony chrony; do
  if id -u "$candidate" >/dev/null 2>&1; then CHRONY_USER="$candidate"; break; fi
done
if [[ -n "$CHRONY_USER" ]]; then
  chown -R "${CHRONY_USER}:${CHRONY_USER}" /var/run/chrony /var/log/chrony
  chown "${CHRONY_USER}:${CHRONY_USER}" /var/lib/chrony
  find /var/lib/chrony -mindepth 1 -maxdepth 1 ! -name ntp-gui \
    -exec chown -R "${CHRONY_USER}:${CHRONY_USER}" {} + 2>/dev/null || true
fi
chmod 750 /var/run/chrony

apply_config || { log main "Ohne gültige Konfiguration kein Start."; exit 1; }
start_services

spawn web python3 "${APP_DIR}/server.py"
WEB_PID="$SPAWNED"

# --- Watchdog ------------------------------------------------------------------
# Statt 'wait -n': bash 5.2 übersieht damit Kinder, die vor dem Aufruf gestorben
# sind. Der Watchdog erkennt jeden toten Dienst, auch beim Start.
while true; do
  if (( RELOAD_REQUESTED )); then
    RELOAD_REQUESTED=0
    reload_services
  fi
  for entry in "${SERVICE_PIDS[@]}" "$WEB_PID"; do
    if ! service_alive "$entry"; then
      log main "Dienst '${entry#*=}' (PID ${entry%%=*}) wurde unerwartet beendet – Container wird gestoppt"
      write_status error "Dienst ${entry#*=} ausgefallen"
      shutdown 1
    fi
  done
  # ptp4l schreibt sein Log unbegrenzt; ab 5 MB auf die letzten 256 KB kürzen.
  # In-place (cat >), damit der O_APPEND-Deskriptor von ptp4l gültig bleibt.
  if [[ -f "$PTP_LOG_FILE" ]] && (( $(stat -c %s "$PTP_LOG_FILE" 2>/dev/null || echo 0) > 5242880 )); then
    tail -c 262144 "$PTP_LOG_FILE" > "${PTP_LOG_FILE}.tmp" 2>/dev/null \
      && cat "${PTP_LOG_FILE}.tmp" > "$PTP_LOG_FILE" \
      && rm -f "${PTP_LOG_FILE}.tmp" \
      && log ptp "Log auf die letzten 256 KB gekürzt" || true
  fi
  # 'wait' auf ein Hintergrund-sleep, damit ein SIGHUP sofort wirkt.
  sleep 2 & wait $! 2>/dev/null || true
done
