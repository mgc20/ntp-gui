#!/usr/bin/env bash
# Startet und überwacht chronyd, gpsd, ptp4l, phc2sys und das Dashboard.
#
# Die Konfiguration erzeugt /app/confgen.py aus den Einstellungen (Dashboard >
# Umgebungsvariable > Standard). Nach dem Speichern legt das Dashboard
# RUN_DIR/reload.request an (ein manuelles SIGHUP wirkt genauso): Die
# Konfiguration wird neu erzeugt, nur die Zeitdienste starten neu; Container
# und Dashboard laufen weiter.
#
# chronyd und das Dashboard sind Pflicht: Stirbt einer davon, endet der
# Container mit Exit 1, damit Docker ihn neu startet. gpsd, ptp4l und phc2sys
# sind optional: Fallen sie aus, startet der Supervisor sie mit wachsender
# Pause neu (5 s, 15 s, 60 s, dann alle 5 min) – NTP läuft derweil weiter.
# Ebenso optional ist dnsfwd (DNS für ntp-gui, ab 1.4): ein Weiterleiter auf
# 127.0.0.1:53, auf den /etc/resolv.conf zeigt, solange er läuft. Stirbt er,
# kommt sofort die Original-resolv.conf zurück, damit Namen weiter auflösbar sind.
# Der Zustand jedes Dienstes steht in ${RUN_DIR}/services.json.
#
# Alle Ausgaben (Supervisor und Dienste) laufen zusätzlich durch logtee.py nach
# ${RUN_DIR}/ntp-gui.log (Log-Seite, Diagnosepaket); `docker logs` zeigt weiter
# alles. Wichtige Ereignisse (Neustarts, Neuladen, Zertifikat, Hotplug, Start)
# hängt der Supervisor als JSON-Zeilen an ${RUN_DIR}/events.jsonl an.
set -euo pipefail

CHRONY_CONF="${CHRONY_CONF:-/etc/chrony/chrony.conf}"
PTP4L_CONF="${PTP4L_CONF:-/etc/linuxptp/ptp4l.conf}"
PTP_LOG_FILE="${PTP_LOG_FILE:-/var/log/ptp4l.log}"
APP_DIR="${APP_DIR:-/app}"
RUN_DIR="${NTPGUI_RUN_DIR:-/run/ntp-gui}"
export CHRONY_CONF PTP4L_CONF PTP_LOG_FILE NTPGUI_RUN_DIR="$RUN_DIR"

WEB_PID=""        # Dashboard, "pid=comm"
RELOAD_REQUESTED=0

SERVICES=(chronyd gpsd ptp4l phc2sys dnsfwd web)
OPTIONAL_SERVICES=" gpsd ptp4l phc2sys dnsfwd "
RESOLV_CONF="${NTPGUI_RESOLV_CONF:-/etc/resolv.conf}"
BACKOFF=(5 15 60 300)   # Pause vor dem 1., 2., 3. und jedem weiteren Neustart
STABLE_AFTER=600        # lief ein Dienst so lange, beginnt der Backoff wieder bei 5 s
HOTPLUG_EVERY=30        # Sekunden zwischen zwei Prüfungen auf neue/ersetzte Geräte
NTS_CERT_EVERY=60       # Sekunden zwischen zwei Prüfungen auf ein erneuertes NTS-Zertifikat
NTS_CERT_SETTLE=10      # so lange muss eine Änderung stabil sein (Zertifikat + Schlüssel)
declare -A SVC_ENTRY=() SVC_STATE=() SVC_RESTARTS=() SVC_EXIT=() SVC_SINCE=() \
           SVC_NEXT=() SVC_STARTED=() SVC_FAILS=() SVC_NOTE=()
# Soll der Dienst laut Einstellungen laufen? „stopped“ bei false ist Absicht (GPS/PTP aus,
# DNS-Modus system) – /metrics meldet das als ntpgui_service_enabled 0, damit kein Alarm feuert.
declare -A SVC_ON=([chronyd]=true [web]=true)
HOTPLUG_PATHS=""        # konfigurierte, aber fehlende Geräte (von confgen)
GPS_DEV_ID=""           # Identität des Geräteknotens, den gpsd liest
GPS_DEV_GONE=0
NEXT_HOTPLUG=0
NTS_WATCH=""            # Zertifikat + Schlüssel des NTS-Servers (von confgen)
NTS_CERT_SIG=""         # Stand beim letzten (Neu-)Laden von chronyd
NTS_CERT_PENDING=""     # erkannte Änderung, die noch auf Stabilität wartet
NEXT_NTS_CERT=0
NTS_CERT_DEFERRED=0     # erneuertes Zertifikat wartet auf das Ende eines Holdover-Tests
# 1.5.3: Läuft ein Holdover-Test, nennt das Dashboard in RUN_DIR/reload.hold eine Unix-Zeit (alle
# ~10 s verlängert). Bis dahin startet der Supervisor chronyd nicht von sich aus neu (Hotplug,
# NTS-Zertifikat) – sonst bräche der Test ab. Was du speicherst (reload.request), wirkt weiter sofort.
RELOAD_HOLD_NOTED=""    # schon gemeldete Zurückstellungen (je Grund ein Ereignis)

LOGTEE_PID=""     # logtee.py (Prozess-Substitution), siehe start_logtee
LOG_OUT_FD=""
LOG_ERR_FD=""
EVENTS_MAX=1048576  # events.jsonl ab 1 MB nach events.jsonl.1 verschieben
# Ereignisse werden über diese Variable gemeldet: Die Unittests laden einzelne
# Funktionen ohne emit_event – dort ist sie leer und der Aufruf ein ':'.
EMIT_EVENT=emit_event

log() { printf '[%s] %s\n' "$1" "${*:2}"; }
now() { printf '%(%s)T' -1; }

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
  wait_exec "$!"
}

# Direkt nach "cmd &" trägt das Kind bis zu seinem exec noch den Namen dieser Shell in
# /proc/PID/comm. Ein service_alive in diesem Fenster hielte den eben gestarteten Dienst für
# tot (reload_chronyd ließe den alten chronyd laufen, der Watchdog meldete „unerwartet
# beendet“). wait_exec wartet höchstens ~1 s, bis das exec geschehen ist.
wait_exec() {  # wait_exec <pid>
  local pid="$1" own i
  own=$(cat "/proc/$$/comm" 2>/dev/null) || return 0
  for (( i = 0; i < 100; i++ )); do
    [[ "$(cat "/proc/${pid}/comm" 2>/dev/null)" != "$own" ]] && return 0
    sleep 0.01
  done
  return 0
}

service_alive() {
  local pid="${1%%=*}" comm="${1#*=}" actual
  [[ -n "$pid" ]] || return 1
  actual=$(cat "/proc/${pid}/comm" 2>/dev/null) || return 1
  if [[ "$actual" != "$comm" && "$actual" == "$(cat "/proc/$$/comm" 2>/dev/null)" ]]; then
    wait_exec "$pid"  # gerade erst gestartet: exec abwarten statt „tot“ zu melden
    actual=$(cat "/proc/${pid}/comm" 2>/dev/null) || return 1
  fi
  [[ "$actual" == "$comm" ]]
}

write_status() {  # write_status <state> <message>
  mkdir -p "$RUN_DIR"
  printf '{"state": "%s", "message": "%s", "time": %s}\n' \
    "$1" "${2//\"/\'}" "$(now)" > "${RUN_DIR}/reload.json.tmp"
  mv -f "${RUN_DIR}/reload.json.tmp" "${RUN_DIR}/reload.json"
}

json_str() {  # json_str <text> -> JSON-String samt Anführungszeichen
  local t="$1"
  t=${t//\\/\\\\}
  t=${t//\"/\\\"}
  t=${t//[$'\x01'-$'\x1f'$'\x7f']/ }
  printf '"%s"' "$t"
}

# emit_event <kind> <level> <titel> [schlüssel=wert ...]
# Hängt eine Zeile {"t","kind","level","title","data"} an ${RUN_DIR}/events.jsonl
# an (liest das Dashboard über events.ingest_supervisor). Ganze Zahlen landen
# als Zahl in data, alles andere als String. Schlägt nie fehl.
emit_event() {
  local kind="$1" level="$2" title="$3" pair key value data="" sep="" file size
  shift 3 || return 0
  for pair in "$@"; do
    key="${pair%%=*}"
    value="${pair#*=}"
    [[ "$pair" == *=* && -n "$key" ]] || continue
    if [[ "$value" =~ ^-?[0-9]{1,15}$ ]]; then
      data+="${sep}$(json_str "$key"): ${value}"
    else
      data+="${sep}$(json_str "$key"): $(json_str "$value")"
    fi
    sep=", "
  done
  file="${RUN_DIR}/events.jsonl"
  {
    mkdir -p "$RUN_DIR"
    size=$(stat -c %s "$file" 2>/dev/null || echo 0)
    if (( size > EVENTS_MAX )); then mv -f "$file" "${file}.1"; fi
    printf '{"t": %s, "kind": %s, "level": %s, "title": %s, "data": {%s}}\n' \
      "$(now)" "$(json_str "$kind")" "$(json_str "$level")" "$(json_str "$title")" "$data" >> "$file"
  } 2>/dev/null || true
  return 0
}

# Ausgabe zusätzlich nach ${RUN_DIR}/ntp-gui.log (logtee.py, mit Rotation).
# Endet der tee – egal mit welchem Exit-Code, auch 0 nach einem Lesefehler –,
# übernimmt cat: Der Supervisor darf nie an einer kaputten Pipe sterben (als
# PID 1 ignoriert er SIGPIPE, dann scheitert printf mit EPIPE und set -e endet). Die ursprünglichen Deskriptoren bleiben gesichert,
# damit stop_logtee beim Beenden die letzten Zeilen noch ins Container-Log bringt.
start_logtee() {
  [[ "${NTPGUI_LOGTEE:-1}" == 1 && -f "${APP_DIR}/logtee.py" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  mkdir -p "$RUN_DIR" 2>/dev/null || return 0
  exec {LOG_OUT_FD}>&1 {LOG_ERR_FD}>&2
  exec > >(python3 -u "${APP_DIR}/logtee.py" "${RUN_DIR}/ntp-gui.log"; exec cat) 2>&1
  LOGTEE_PID=$!
  # Ein 'wait' ohne Argument wartet auch auf die Prozess-Substitution (bash 5.2
  # sogar unabhängig von $!) – und der tee endet erst nach uns. Deshalb wartet
  # shutdown nur auf 'jobs -p'; $! wird trotzdem neu belegt.
  true & wait "$!" 2>/dev/null || true
}

# Beim Beenden: stdout/stderr zurück auf das Container-Log, damit der tee EOF
# sieht, und kurz warten, bis er alles ausgegeben hat (sonst gehen mit dem Ende
# von PID 1 die letzten Zeilen verloren).
stop_logtee() {
  local i st
  [[ -n "$LOGTEE_PID" ]] || return 0
  exec 1>&"$LOG_OUT_FD" 2>&"$LOG_ERR_FD"
  for (( i = 0; i < 30; i++ )); do
    st=""
    # Klammern: Die Umleitung von stderr muss auch den Fehler des Öffnens
    # (Prozess schon abgeräumt) schlucken – sonst steht er bei jedem Stopp im Log.
    { read -r _ _ st _ < "/proc/${LOGTEE_PID}/stat"; } 2>/dev/null || break
    [[ "$st" == Z ]] && break
    sleep 0.1
  done
  LOGTEE_PID=""
  return 0
}

# ${RUN_DIR}/services.json – je Dienst: state (running | restarting | failed |
# stopped), restarts, last_exit, since (Unix-Zeit des letzten Zustandswechsels).
write_services() {
  local name sep="" out entry pid optional
  out="{\"time\": $(now), \"services\": {"
  for name in "${SERVICES[@]}"; do
    entry="${SVC_ENTRY[$name]:-}"
    pid="${entry%%=*}"
    optional=false
    [[ "$OPTIONAL_SERVICES" == *" $name "* ]] && optional=true
    out+="${sep}$(json_str "$name"): {\"state\": $(json_str "${SVC_STATE[$name]:-stopped}")"
    out+=", \"restarts\": ${SVC_RESTARTS[$name]:-0}"
    out+=", \"last_exit\": ${SVC_EXIT[$name]:-null}"
    out+=", \"since\": ${SVC_SINCE[$name]:-null}"
    out+=", \"pid\": ${pid:-null}"
    out+=", \"optional\": ${optional}"
    out+=", \"enabled\": ${SVC_ON[$name]:-false}"
    out+=", \"next_retry\": $([[ "${SVC_STATE[$name]:-}" == restarting ]] && echo "${SVC_NEXT[$name]:-null}" || echo null)"
    out+=", \"message\": $(json_str "${SVC_NOTE[$name]:-}")}"
    sep=", "
  done
  out+="}}"
  mkdir -p "$RUN_DIR"
  if printf '%s\n' "$out" > "${RUN_DIR}/services.json.tmp"; then
    mv -f "${RUN_DIR}/services.json.tmp" "${RUN_DIR}/services.json" || true
  fi
}

set_state() {  # set_state <dienst> <zustand> [meldung]
  SVC_STATE[$1]="$2"
  SVC_SINCE[$1]="$(now)"
  SVC_NOTE[$1]="${3:-}"
  if [[ "$2" == running ]]; then SVC_STARTED[$1]="${SVC_SINCE[$1]}"; fi
  write_services
}

device_id() {  # Inode + Major/Minor des Knotens (folgt by-id-Links), leer wenn weg
  stat -L -c '%i:%t:%T' "$1" 2>/dev/null || true
}

# --- Konfiguration erzeugen ---------------------------------------------------
apply_config() {
  local out
  if ! out=$(python3 "${APP_DIR}/confgen.py" apply); then
    log config "FEHLER: Konfiguration konnte nicht erzeugt werden – bisherige bleibt aktiv."
    return 1
  fi
  eval "$out"
  HOTPLUG_PATHS="${NTPGUI_HOTPLUG_PATHS:-}"
  NTS_WATCH="${NTPGUI_NTS_WATCH:-}"
  NTS_CERT_SIG="$(file_signature $NTS_WATCH)"
  NTS_CERT_PENDING=""
}

# mtime, Größe und Inode jeder Datei (stat -L folgt Symlinks wie live/ → archive/
# bei Let's Encrypt). Fehlende Dateien zählen als "-", damit auch Verschwinden
# und Wiederkehren auffallen.
file_signature() {  # file_signature <pfad...> -> eine Zeile
  local path sig=""
  for path in "$@"; do
    sig+="$(stat -L -c '%Y:%s:%i' "$path" 2>/dev/null || echo -);"
  done
  printf '%s' "$sig"
}

# chrony liest Zertifikat und Schlüssel nur beim Start (chrony.conf(5),
# ntsservercert: "The files are loaded only once. chronyd needs to be restarted
# in order to load a renewed certificate."). Erneuert der Reverse Proxy oder
# Certbot das Zertifikat, startet der Watchdog nur chronyd neu (reload_chronyd) –
# gpsd, ptp4l und phc2sys laufen weiter. Die Änderung
# muss NTS_CERT_SETTLE Sekunden stabil sein, damit nicht zwischen dem Schreiben
# von Zertifikat und Schlüssel neu geladen wird.
check_nts_cert() {  # check_nts_cert <jetzt> -> 0 = neu laden
  local t="$1" sig
  [[ -n "$NTS_WATCH" ]] || return 1
  sig="$(file_signature $NTS_WATCH)"
  if [[ "$sig" == "$NTS_CERT_SIG" ]]; then
    NTS_CERT_PENDING=""
    NEXT_NTS_CERT=$(( t + NTS_CERT_EVERY ))
    return 1
  fi
  if [[ "$sig" != "$NTS_CERT_PENDING" ]]; then
    NTS_CERT_PENDING="$sig"
    NEXT_NTS_CERT=$(( t + NTS_CERT_SETTLE ))
    return 1
  fi
  # Schon hier übernehmen: Scheitert das Neuladen, nicht jede Minute erneut versuchen.
  NTS_CERT_SIG="$sig"
  NTS_CERT_PENDING=""
  NEXT_NTS_CERT=$(( t + NTS_CERT_EVERY ))
  return 0
}

# --- Einzelne Dienste starten ---------------------------------------------------
start_chronyd() {
  local chronyd_args=(-d -r -f "$CHRONY_CONF")
  if is_true "${DISABLE_CLOCK_CONTROL:-auto}"; then
    chronyd_args+=(-x)
    log chrony "Uhrensteuerung deaktiviert (DISABLE_CLOCK_CONTROL)"
  elif ! has_sys_time; then
    chronyd_args+=(-x)
    log chrony "WARNUNG: CAP_SYS_TIME fehlt – chronyd läuft mit -x und stellt die Uhr nicht."
    log chrony "         Für einen echten Zeitserver den Container mit 'cap_add: [SYS_TIME]' starten."
  elif [[ "${NTPGUI_CHRONY_NOCONTROL:-0}" == 1 ]]; then
    # confgen entscheidet: Stellt phc2sys (oder ptp4l mit Software-Zeitstempeln
    # als Slave) die Systemuhr, würden sich zwei Regler die Korrekturen
    # überschreiben. Als Grandmaster bleibt chronyd dagegen der Regler.
    chronyd_args+=(-x)
    log chrony "PTP steuert die Systemuhr – chronyd läuft mit -x und liefert nur aus."
  fi
  rm -f /run/chrony/chronyd.pid /var/run/chrony/chronyd.pid
  spawn chrony /usr/sbin/chronyd "${chronyd_args[@]}"
  SVC_ENTRY[chronyd]="$SPAWNED"
  set_state chronyd running
  reapply_noselect
}

# GPS-Sperre (1.5): Laufzeitschalter „selectopts +noselect“ überleben keinen Neustart von
# chronyd. Das Dashboard (selectctl.py) führt deshalb DATA_DIR/noselect.list mit den gesperrten
# Quellen; hier werden sie direkt nach dem Start wieder abgewählt – bevor chronyd die erste
# GPS-Messung hat und das gesperrte GPS auswählen (oder die Uhr per makestep darauf stellen)
# könnte. Kurz im Hintergrund, bis chronyd Befehle annimmt (höchstens ~10 s).
reapply_noselect() {
  local file="${NTPGUI_DATA_DIR:-/var/lib/chrony/ntp-gui}/noselect.list" name names=()
  [[ -s "$file" ]] || return 0
  while IFS= read -r name || [[ -n "$name" ]]; do
    # Nur Namen wie in selectctl.NAME_RE – nichts anderes landet auf der Kommandozeile.
    [[ "$name" =~ ^[A-Za-z0-9_.:%-]{1,64}$ ]] && names+=("$name")
  done < "$file"
  (( ${#names[@]} )) || return 0
  (
    local i
    for (( i = 0; i < 40; i++ )); do
      if chronyc -n tracking >/dev/null 2>&1; then
        for name in "${names[@]}"; do
          if chronyc selectopts "$name" +noselect >/dev/null 2>&1; then
            log chrony "GPS-Sperre: ${name} nach dem Start von chronyd wieder abgewählt"
          fi
        done
        exit 0
      fi
      sleep 0.25
    done
    log chrony "WARNUNG: GPS-Sperre nicht erneuert – chronyd nimmt keine Befehle an (das Dashboard versucht es weiter)"
  ) &
}

start_gpsd() {
  local gpsd_args=(-N -n)
  if [[ ! -e "$NTPGUI_GPS_DEVICE" ]]; then
    log gps "WARNUNG: ${NTPGUI_GPS_DEVICE} fehlt – gpsd wartet, bis das Gerät wieder da ist."
    SVC_ENTRY[gpsd]=""
    set_state gpsd failed "Gerät ${NTPGUI_GPS_DEVICE} fehlt"
    "${EMIT_EVENT:-:}" gps warn "GPS-Gerät ${NTPGUI_GPS_DEVICE} fehlt – gpsd wartet" device="$NTPGUI_GPS_DEVICE"
    case " $HOTPLUG_PATHS " in *" $NTPGUI_GPS_DEVICE "*) ;; *) HOTPLUG_PATHS="${HOTPLUG_PATHS:+$HOTPLUG_PATHS }$NTPGUI_GPS_DEVICE" ;; esac
    return 0
  fi
  if [[ -n "${NTPGUI_GPS_SPEED:-}" ]]; then gpsd_args+=(-s "$NTPGUI_GPS_SPEED"); fi
  # shellcheck disable=SC2206  # GPS_OPTIONS ist bewusst eine Wortliste
  if [[ -n "${GPS_OPTIONS:-}" ]]; then gpsd_args+=(${GPS_OPTIONS}); fi
  # -n: gpsd liest den Empfänger auch ohne Client – sonst bekommt chrony nie Zeit.
  spawn gps /usr/sbin/gpsd "${gpsd_args[@]}" "$NTPGUI_GPS_DEVICE"
  SVC_ENTRY[gpsd]="$SPAWNED"
  GPS_DEV_ID="$(device_id "$NTPGUI_GPS_DEVICE")"
  GPS_DEV_GONE=0
  set_state gpsd running
}

start_ptp4l() {
  log ptp "ptp4l auf ${NTPGUI_PTP_INTERFACE} (Domain ${NTPGUI_PTP_DOMAIN}, Modus ${NTPGUI_PTP_MODE})"
  /usr/sbin/ptp4l -f "$PTP4L_CONF" -i "$NTPGUI_PTP_INTERFACE" -m >>"$PTP_LOG_FILE" 2>&1 &
  SVC_ENTRY[ptp4l]="$!=ptp4l"
  wait_exec "$!"
  set_state ptp4l running
}

start_phc2sys() {
  # shellcheck disable=SC2086  # Optionen sind eine geprüfte Wortliste
  spawn phc2sys /usr/sbin/phc2sys $NTPGUI_PHC2SYS_OPTIONS
  SVC_ENTRY[phc2sys]="$SPAWNED"
  set_state phc2sys running
}

# DNS für ntp-gui: Weiterleiter starten und kurz warten, bis er lauscht und
# resolv.conf umgestellt hat – dann löst chronyd seine Quellen schon beim Start
# über ihn auf.
start_dnsfwd() {
  local i
  rm -f "${RUN_DIR}/dnsfwd.ready"
  spawn dns python3 "${APP_DIR}/dnsfwd.py" serve
  SVC_ENTRY[dnsfwd]="$SPAWNED"
  set_state dnsfwd running
  for (( i = 0; i < 30; i++ )); do
    [[ -s "${RUN_DIR}/dnsfwd.ready" ]] && return 0
    service_alive "${SVC_ENTRY[dnsfwd]}" || return 0
    sleep 0.1
  done
  log dns "WARNUNG: Weiterleiter meldet sich nicht – chronyd startet trotzdem."
}

# Original-resolv.conf zurück, falls sie noch auf den Weiterleiter zeigt
# (Modus „system“, Absturz, Neustart des Containers ohne Neuerstellen).
dns_restore() {
  grep -q '^# ntp-gui: dnsfwd' "$RESOLV_CONF" 2>/dev/null || return 0
  python3 "${APP_DIR}/dnsfwd.py" restore || true
}

start_services() {
  local name
  for name in gpsd ptp4l phc2sys dnsfwd; do
    SVC_ENTRY[$name]=""
    SVC_FAILS[$name]=0
    SVC_ON[$name]=false
  done
  [[ "${NTPGUI_DNS_MODE:-system}" != system ]] && SVC_ON[dnsfwd]=true
  [[ "${NTPGUI_GPS_ENABLE:-0}" == 1 ]] && SVC_ON[gpsd]=true
  if [[ "${NTPGUI_PTP_START:-0}" == 1 ]]; then
    SVC_ON[ptp4l]=true
    [[ "${NTPGUI_PHC2SYS_START:-0}" == 1 ]] && SVC_ON[phc2sys]=true
  fi
  if [[ "${NTPGUI_DNS_MODE:-system}" != system ]]; then
    start_dnsfwd
  else
    dns_restore
    set_state dnsfwd stopped "System-DNS (Modus system)"
  fi
  start_chronyd

  if [[ "${NTPGUI_GPS_START:-0}" == 1 ]]; then
    start_gpsd
  elif [[ "${NTPGUI_GPS_ENABLE:-0}" == 1 ]]; then
    set_state gpsd stopped "Gerät ${NTPGUI_GPS_DEVICE:-?} fehlt – wird alle ${HOTPLUG_EVERY} s gesucht"
  else
    set_state gpsd stopped "GPS ist aus"
  fi

  if [[ "${NTPGUI_PTP_START:-0}" == 1 ]]; then
    : >"$PTP_LOG_FILE"
    start_ptp4l
    if [[ "${NTPGUI_PHC2SYS_START:-0}" == 1 ]]; then
      sleep 2
      start_phc2sys
    else
      set_state phc2sys stopped "phc2sys ist aus"
    fi
  else
    set_state ptp4l stopped "PTP ist aus"
    set_state phc2sys stopped "PTP ist aus"
  fi
  if [[ -n "$HOTPLUG_PATHS" ]]; then
    log main "Warte auf Geräte (Prüfung alle ${HOTPLUG_EVERY} s): ${HOTPLUG_PATHS}"
  fi
  NEXT_HOTPLUG=$(( $(now) + HOTPLUG_EVERY ))
}

stop_services() {
  local name entry
  for name in phc2sys ptp4l gpsd chronyd dnsfwd; do
    entry="${SVC_ENTRY[$name]:-}"
    if [[ -n "$entry" ]] && service_alive "$entry"; then kill "${entry%%=*}" 2>/dev/null || true; fi
  done
  for name in phc2sys ptp4l gpsd chronyd dnsfwd; do
    entry="${SVC_ENTRY[$name]:-}"
    if [[ -n "$entry" ]]; then wait "${entry%%=*}" 2>/dev/null || true; fi
    SVC_ENTRY[$name]=""
    SVC_STATE[$name]=stopped
  done
  # dnsfwd schreibt resolv.conf beim Beenden selbst zurück; nach einem SIGKILL nicht.
  dns_restore
  write_services
}

reload_services() {
  log main "Einstellungen geändert – Zeitdienste werden neu gestartet …"
  write_status running "Zeitdienste werden neu gestartet"
  stop_services
  local name
  for name in gpsd ptp4l phc2sys dnsfwd; do SVC_RESTARTS[$name]=0; SVC_EXIT[$name]=""; done
  if apply_config; then
    start_services
    write_status done "Neue Einstellungen aktiv"
    log main "Neustart abgeschlossen."
    "${EMIT_EVENT:-:}" reload info "Neue Einstellungen aktiv – Zeitdienste neu gestartet" result=done
  else
    start_services
    write_status error "Konfiguration fehlerhaft – bisherige Einstellungen weiter aktiv"
    "${EMIT_EVENT:-:}" reload warn "Konfiguration fehlerhaft – bisherige Einstellungen bleiben aktiv" result=error
  fi
}

# Nur chronyd neu laden (erneuertes NTS-Zertifikat): confgen legt die Kopien von
# Zertifikat und Schlüssel neu an und schreibt chrony.conf; gpsd, ptp4l und
# phc2sys laufen weiter, damit GPS/PPS nicht neu einrasten und PTP nicht ausfällt.
reload_chronyd() {
  local entry
  write_status running "chronyd wird neu gestartet"
  if ! apply_config; then
    write_status error "Konfiguration fehlerhaft – chronyd läuft mit dem bisherigen Zertifikat weiter"
    "${EMIT_EVENT:-:}" cert warn "Zertifikat erneuert, aber Konfiguration fehlerhaft – chronyd behält das alte" result=error
    return 0
  fi
  entry="${SVC_ENTRY[chronyd]:-}"
  if [[ -n "$entry" ]] && service_alive "$entry"; then
    kill "${entry%%=*}" 2>/dev/null || true
    wait "${entry%%=*}" 2>/dev/null || true
  fi
  SVC_ENTRY[chronyd]=""
  start_chronyd
  write_status done "Zertifikat neu geladen"
  log main "chronyd neu gestartet."
  "${EMIT_EVENT:-:}" cert info "NTS-Zertifikat erneuert – chronyd hat es neu geladen" result=done
}

shutdown() {
  # Exit-Code 0 nur beim geordneten Stoppen; ein weggestorbener Dienst muss
  # auch mit restart=on-failure einen Neustart auslösen.
  local code="${1:-0}"
  log main "beende Dienste …"
  if (( code == 0 )); then
    "${EMIT_EVENT:-:}" service info "Container wird beendet" exit="$code"
  else
    "${EMIT_EVENT:-:}" service crit "Container wird wegen eines ausgefallenen Pflichtdienstes beendet" exit="$code"
  fi
  stop_services
  [[ -n "$WEB_PID" ]] && kill "${WEB_PID%%=*}" 2>/dev/null || true
  # Nur auf die eigenen Hintergrundjobs warten: Ein 'wait' ohne Argument wartet in
  # bash 5.2 auch auf die Prozess-Substitution des Log-Tees – und die endet erst
  # nach uns (Container hinge dann bis zum SIGKILL).
  local jobs_left
  jobs_left=$(jobs -p)
  if [[ -n "$jobs_left" ]]; then
    # shellcheck disable=SC2086
    wait $jobs_left 2>/dev/null || true
  fi
  SVC_STATE[web]=stopped
  write_services
  exit "$code"
}
trap 'shutdown 0' SIGTERM SIGINT
trap 'stop_logtee' EXIT
trap 'RELOAD_REQUESTED=1' SIGHUP

# --- Watchdog-Bausteine -----------------------------------------------------------
# Ein optionaler Dienst ist ausgefallen: Exit-Code merken, Neustart planen.
schedule_restart() {  # schedule_restart <dienst>
  local name="$1" entry="${SVC_ENTRY[$1]}" code=0 t ran delay fails pid stat st ppid
  pid="${entry%%=*}"
  # 'wait' blockiert, solange das Kind lebt. Passt nur comm nicht (z. B. direkt
  # nach fork, vor exec), ist der Dienst nicht tot: nicht warten, nächste Runde
  # erneut prüfen. Nur ein beendetes Kind (Zombie) oder ein fremder/verschwundener
  # PID geht weiter – dann kehrt 'wait' sofort zurück.
  if [[ -n "$pid" ]] && stat=$(cat "/proc/${pid}/stat" 2>/dev/null); then
    read -r st ppid _ <<<"${stat##*) }"
    if [[ "$st" != Z && "$ppid" == "$$" ]]; then
      return 0
    fi
  fi
  wait "$pid" 2>/dev/null || code=$?
  t=$(now)
  ran=$(( t - ${SVC_STARTED[$name]:-$t} ))
  fails=${SVC_FAILS[$name]:-0}
  if (( ran >= STABLE_AFTER )); then fails=0; fi
  delay=${BACKOFF[$(( fails < ${#BACKOFF[@]} ? fails : ${#BACKOFF[@]} - 1 ))]}
  SVC_FAILS[$name]=$(( fails + 1 ))
  SVC_EXIT[$name]=$code
  SVC_NEXT[$name]=$(( t + delay ))
  SVC_ENTRY[$name]=""
  # Ohne Weiterleiter darf resolv.conf nicht auf 127.0.0.1 zeigen – sonst löst nichts mehr auf.
  if [[ "$name" == dnsfwd ]]; then "${DNS_RESTORE:-dns_restore}"; fi
  log main "Dienst '${name}' (PID ${entry%%=*}) wurde unerwartet beendet (Exit ${code}) –" \
           "Neustart in ${delay} s; NTP läuft weiter."
  set_state "$name" restarting "beendet mit Exit ${code}, neuer Versuch in ${delay} s"
  "${EMIT_EVENT:-:}" service warn "Dienst ${name} unerwartet beendet (Exit ${code}) – Neustart in ${delay} s" \
    service="$name" exit="$code" delay="$delay"
}

restart_service() {  # restart_service <dienst>
  local name="$1"
  SVC_RESTARTS[$name]=$(( ${SVC_RESTARTS[$name]:-0} + 1 ))
  log main "Starte '${name}' neu (Versuch ${SVC_RESTARTS[$name]})"
  "start_${name}"
  if [[ "${SVC_STATE[$name]:-}" == running ]]; then
    "${EMIT_EVENT:-:}" service info "Dienst ${name} läuft wieder (Versuch ${SVC_RESTARTS[$name]})" \
      service="$name" attempt="${SVC_RESTARTS[$name]}"
  fi
}

# reload_held <grund> -> 0 = automatischen Neustart zurückstellen (Holdover-Test läuft).
reload_held() {
  local hold_until=""
  if [[ -f "${RUN_DIR}/reload.hold" ]]; then
    read -r hold_until < "${RUN_DIR}/reload.hold" 2>/dev/null || hold_until=""
  fi
  if [[ ! "$hold_until" =~ ^[0-9]{1,12}$ ]] || (( hold_until < $(now) )); then
    RELOAD_HOLD_NOTED=""
    return 1
  fi
  if [[ "$RELOAD_HOLD_NOTED" != *"|$1|"* ]]; then
    RELOAD_HOLD_NOTED+="|$1|"
    log main "$1 – zurückgestellt bis zum Ende des Holdover-Tests."
    "${EMIT_EVENT:-:}" reload info "$1 – zurückgestellt bis zum Ende des Holdover-Tests" reason=holdover
  fi
  return 0
}

# Geräte, die beim Start fehlten, aufgetaucht? GPS-Empfänger ab- und wieder
# angesteckt (neuer Geräteknoten)? Dann Konfiguration neu erzeugen – wie SIGHUP.
check_hotplug() {
  local path id
  for path in $HOTPLUG_PATHS; do
    if [[ -e "$path" ]]; then
      if reload_held "Gerät ${path} ist jetzt vorhanden – Neustart der Zeitdienste"; then return 0; fi
      log main "Gerät ${path} ist jetzt vorhanden – Konfiguration wird neu geladen."
      "${EMIT_EVENT:-:}" reload info "Gerät ${path} ist jetzt vorhanden – Konfiguration wird neu geladen" \
        reason=hotplug device="$path"
      reload_services
      return 0
    fi
  done
  if [[ "${SVC_STATE[gpsd]:-}" == running && -n "${NTPGUI_GPS_DEVICE:-}" ]]; then
    id="$(device_id "$NTPGUI_GPS_DEVICE")"
    if [[ -z "$id" ]]; then
      if (( ! GPS_DEV_GONE )); then
        log gps "WARNUNG: ${NTPGUI_GPS_DEVICE} ist verschwunden (abgezogen?) – warte auf Rückkehr."
        "${EMIT_EVENT:-:}" gps warn "GPS-Gerät ${NTPGUI_GPS_DEVICE} ist verschwunden (abgezogen?)" \
          reason=hotplug device="$NTPGUI_GPS_DEVICE"
        GPS_DEV_GONE=1
      fi
    elif [[ "$id" != "$GPS_DEV_ID" ]]; then
      if reload_held "GPS-Gerät ${NTPGUI_GPS_DEVICE} neu angesteckt – Neustart der Zeitdienste"; then return 0; fi
      log gps "${NTPGUI_GPS_DEVICE} wurde neu angesteckt – Konfiguration wird neu geladen."
      "${EMIT_EVENT:-:}" gps info "GPS-Gerät ${NTPGUI_GPS_DEVICE} wurde neu angesteckt" \
        reason=hotplug device="$NTPGUI_GPS_DEVICE"
      reload_services
    fi
  fi
  return 0
}

# --- Vorbereitung ------------------------------------------------------------
start_logtee
mkdir -p /var/run/chrony /var/lib/chrony /var/log/chrony /etc/linuxptp "$RUN_DIR"
echo "$$" > "${RUN_DIR}/supervisor.pid"
rm -f "${RUN_DIR}/reload.request"  # Anforderung von vor dem Start ist erledigt
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
SVC_ENTRY[web]="$WEB_PID"
set_state web running
# Version steht an einer Stelle: als Standard in server.py (Release-Workflow kann sie per Env setzen).
NTPGUI_VERSION="${NTPGUI_VERSION:-$(sed -n 's/^VERSION = os\.environ\.get("NTPGUI_VERSION", "\([^"]*\)").*/\1/p' "${APP_DIR}/server.py" 2>/dev/null)}"
"$EMIT_EVENT" startup info "ntp-gui gestartet" version="${NTPGUI_VERSION:-}"

# --- Watchdog ------------------------------------------------------------------
# Statt 'wait -n': bash 5.2 übersieht damit Kinder, die vor dem Aufruf gestorben
# sind. Der Watchdog erkennt jeden toten Dienst, auch beim Start.
while true; do
  # Neuladen: Das Dashboard legt reload.request an (kein SIGHUP mehr – ein Signal mitten in einem
  # „$( … )“ brachte den bash-Parser durcheinander und beendete den Container). Datei zuerst
  # löschen: Kommt während des Neuladens eine neue Anforderung, folgt ein weiterer Durchgang.
  if [[ -e "${RUN_DIR}/reload.request" ]]; then
    rm -f "${RUN_DIR}/reload.request"
    RELOAD_REQUESTED=1
  fi
  if (( RELOAD_REQUESTED )); then
    RELOAD_REQUESTED=0
    reload_services
  fi
  for name in chronyd web; do
    entry="${SVC_ENTRY[$name]:-}"
    if ! service_alive "$entry"; then
      log main "Dienst '${name}' (PID ${entry%%=*}) wurde unerwartet beendet – Container wird gestoppt"
      "$EMIT_EVENT" service crit "Pflichtdienst ${name} ausgefallen" service="$name"
      write_status error "Dienst ${name} ausgefallen"
      SVC_ENTRY[$name]=""
      set_state "$name" failed "unerwartet beendet"
      shutdown 1
    fi
  done
  NOW=$(now)
  for name in gpsd ptp4l phc2sys dnsfwd; do
    case "${SVC_STATE[$name]:-stopped}" in
      running)
        if ! service_alive "${SVC_ENTRY[$name]:-}"; then schedule_restart "$name"; fi ;;
      restarting)
        if (( NOW >= ${SVC_NEXT[$name]:-0} )); then restart_service "$name"; fi ;;
    esac
  done
  if (( NOW >= NEXT_HOTPLUG )); then
    NEXT_HOTPLUG=$(( NOW + HOTPLUG_EVERY ))
    check_hotplug
  fi
  if (( NOW >= NEXT_NTS_CERT )) && check_nts_cert "$NOW"; then
    NTS_CERT_DEFERRED=1
  fi
  if (( NTS_CERT_DEFERRED )) && ! reload_held "NTS-Zertifikat erneuert – Neustart von chronyd"; then
    NTS_CERT_DEFERRED=0
    log nts "Zertifikat erneuert – chronyd lädt neu"
    reload_chronyd
  fi
  # ptp4l schreibt sein Log unbegrenzt; ab 5 MB auf die letzten 256 KB kürzen.
  # In-place (cat >), damit der O_APPEND-Deskriptor von ptp4l gültig bleibt.
  if [[ -f "$PTP_LOG_FILE" ]] && (( $(stat -c %s "$PTP_LOG_FILE" 2>/dev/null || echo 0) > 5242880 )); then
    tail -c 262144 "$PTP_LOG_FILE" > "${PTP_LOG_FILE}.tmp" 2>/dev/null \
      && cat "${PTP_LOG_FILE}.tmp" > "$PTP_LOG_FILE" \
      && rm -f "${PTP_LOG_FILE}.tmp" \
      && log ptp "Log auf die letzten 256 KB gekürzt" || true
  fi
  # 'wait' auf ein Hintergrund-sleep, damit ein (manuelles) SIGHUP sofort wirkt.
  sleep 2 & wait $! 2>/dev/null || true
done
