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
#
# Rechte (1.9): Nur der Supervisor läuft als root. Dashboard und DNS-Weiterleiter laufen als
# eigener Benutzer ntpgui (setpriv, ohne Capabilities außer den unten genannten, no-new-privs),
# chronyd gibt seine Rechte selbst an _chrony ab (behält nur SYS_TIME und NET_BIND_SERVICE
# für den NTP-Port), gpsd an gpsd. ptp4l und phc2sys bleiben root (Hardware-Zeitstempel, PHC). Das Dashboard schreibt nur in sein
# Datenverzeichnis und in ${REQUEST_DIR}; ${RUN_DIR} selbst gehört dem Supervisor. Neustarts
# fordert es ausschließlich über die festen Dateien reload.request und reload-chronyd.request an.
set -euo pipefail

# Gesetzt = vom Benutzer vorgegeben; sonst weicht der Supervisor bei schreibgeschütztem Root auf /run aus.
CHRONY_CONF_GIVEN="${CHRONY_CONF:+1}"
PTP4L_CONF_GIVEN="${PTP4L_CONF:+1}"
PTP_LOG_GIVEN="${PTP_LOG_FILE:+1}"
CHRONY_CONF="${CHRONY_CONF:-/etc/chrony/chrony.conf}"
PTP4L_CONF="${PTP4L_CONF:-/etc/linuxptp/ptp4l.conf}"
PTP_LOG_FILE="${PTP_LOG_FILE:-/var/log/ptp4l.log}"
APP_DIR="${APP_DIR:-/app}"
RUN_DIR="${NTPGUI_RUN_DIR:-/run/ntp-gui}"
# Anforderungen und Zustand von Dashboard und DNS-Weiterleiter (gehört dem Benutzer APP_USER).
REQUEST_DIR="${NTPGUI_REQUEST_DIR:-${RUN_DIR}/web}"
DATA_DIR="${NTPGUI_DATA_DIR:-/var/lib/chrony/ntp-gui}"
APP_USER="ntpgui"
export CHRONY_CONF PTP4L_CONF PTP_LOG_FILE NTPGUI_RUN_DIR="$RUN_DIR" NTPGUI_REQUEST_DIR="$REQUEST_DIR"

WEB_PID=""        # Dashboard, "pid=comm"
RELOAD_REQUESTED=0
CHRONYD_RELOAD_REQUESTED=0   # reload-chronyd.request: nur chronyd neu laden

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
now() { printf '%(%s)T' -1; }   # Wanduhr – nur für Zeitstempel (Ereignisse, JSON, Holdover-Frist)
# Monotone Sekunden (/proc/uptime, CLOCK_BOOTTIME) für alle Fristen und Abstände: Ein Sprung der
# Systemzeit darf Hotplug-Prüfung, NTS-Zertifikat-Prüfung und Dienst-Neustarts nicht aussetzen.
# Nicht die bash-Variable SECONDS – die rechnet bash aus der Wanduhr (gettimeofday) und springt mit.
mono() {
  local up _
  if read -r up _ 2>/dev/null < /proc/uptime && [[ "$up" =~ ^[0-9]+ ]]; then
    printf '%s' "${BASH_REMATCH[0]}"
  else
    now
  fi
}

# Wie mono, setzt aber MONO direkt – ohne Subshell. Im Watchdog darf keine Runde einen Prozess brauchen:
# Lässt sich gerade keiner starten (Prozessgrenze erreicht), gibt bash nach rund 15 s auf und beendet das
# ganze Skript (PID 1) – kein '|| …' fängt das ab.
set_mono() {
  local up _
  if { read -r up _ < /proc/uptime; } 2>/dev/null && [[ "$up" =~ ^[0-9]+ ]]; then
    MONO="${BASH_REMATCH[0]}"
  else
    printf -v MONO '%(%s)T' -1
  fi
}

# Warten ohne Prozess: 'read -t' auf eine Pipe, in die niemand schreibt (beide Enden hält nur diese Shell,
# es entsteht keine Datei). open_pause einmal beim Start – dort ist der Prozess für '<(:)' unkritisch;
# klappt das nicht, wartet pause wie bisher mit sleep.
PAUSE_FD=""
open_pause() {
  exec {PAUSE_FD}<> <(:) 2>/dev/null || PAUSE_FD=""
}
pause() {  # pause <sekunden>
  if [[ -n "$PAUSE_FD" ]]; then
    read -r -t "$1" -u "$PAUSE_FD" _ 2>/dev/null || true
  else
    sleep "$1" & wait $! 2>/dev/null || true
  fi
}

is_true() {
  case "${1,,}" in 1|true|yes|on) return 0 ;; *) return 1 ;; esac
}

# cap_has <bit> -> 0, wenn diese Shell die Capability hat (CapEff, bzw. CapPrm mit „prm“ als
# zweitem Argument). Nur Bordmittel, ohne Unterprozess. Bits: CHOWN 0, DAC_OVERRIDE 1, FOWNER 3,
# KILL 5, SETGID 6, SETUID 7, SETPCAP 8, NET_BIND_SERVICE 10, NET_RAW 13, SYS_TIME 25.
CAP_STATUS_FILE="/proc/self/status"
cap_has() {
  local want="CapEff:" key value
  [[ "${2:-}" == prm ]] && want="CapPrm:"
  while read -r key value; do
    if [[ "$key" == "$want" ]]; then
      [[ "$value" =~ ^[0-9a-fA-F]{1,16}$ ]] || return 1
      (( (16#$value >> $1) & 1 ))
      return
    fi
  done < "$CAP_STATUS_FILE" 2>/dev/null
  return 1
}

# CAP_SYS_TIME fehlt: chronyd darf die Uhr nicht stellen und muss mit -x laufen.
has_sys_time() { cap_has 25; }

# Einträge sind "pid=comm": der Watchdog prüft beides, damit ein recycelter PID
# nicht als lebender Dienst durchgeht.
spawn() {  # spawn <name> <cmd...>  -> setzt SPAWNED
  local name="$1" comm; shift
  comm=$(basename "$1")
  log "$name" "starte: $*"
  "$@" &
  SPAWNED="$!=${comm:0:15}"
  wait_exec "$!" "${comm:0:15}"
}

# Dashboard und DNS-Weiterleiter ohne root starten. app_drop <caps> setzt APP_DROP auf den
# setpriv-Aufruf: Benutzer APP_USER (Gruppen samt _chrony für den Kommando-Socket von chronyd),
# no-new-privs, keine Capabilities außer den genannten (z. B. "net_raw,net_bind_service"), die
# der Container auch hat. Ohne SETUID/SETGID (oder ohne den Benutzer) bleibt APP_DROP leer – dann
# laufen beide wie bis 1.8 als root, mit deutlicher Warnung beim Start (APP_DROP_OFF).
APP_DROP=()
APP_DROP_OFF=""   # Grund, warum nicht gewechselt wird (leer = Wechsel möglich)
app_drop() {  # app_drop <cap,cap,...>
  local cap bit list="" sep=""
  APP_DROP=()
  [[ -z "$APP_DROP_OFF" ]] || return 0
  for cap in ${1//,/ }; do
    case "$cap" in
      net_raw) bit=13 ;;
      net_bind_service) bit=10 ;;
      *) continue ;;
    esac
    cap_has "$bit" prm || continue
    list+="${sep}+${cap}"; sep=","
  done
  APP_DROP=(setpriv "--reuid=${APP_USER}" "--regid=${APP_USER}" --init-groups --no-new-privs
            "--inh-caps=-all${list:+,$list}" "--ambient-caps=-all${list:+,$list}")
  # Die Begrenzungsmenge verkleinern geht nur mit CAP_SETPCAP; ohne genügen no-new-privs und das
  # Image ohne SUID-Programme.
  if cap_has 8; then APP_DROP+=("--bounding-set=-all${list:+,$list}"); fi
  APP_DROP+=(--)
}

# spawn_app <name> <caps> <cmd...> -> wie spawn, aber als APP_USER (siehe app_drop)
spawn_app() {
  local name="$1" comm; app_drop "$2"; shift 2
  comm=$(basename "$1")
  log "$name" "starte${APP_DROP[*]:+ als ${APP_USER}}: $*"
  "${APP_DROP[@]}" "$@" &
  SPAWNED="$!=${comm:0:15}"
  wait_exec "$!" "${comm:0:15}"
}

# Direkt nach "cmd &" trägt das Kind bis zu seinem exec noch den Namen dieser Shell in
# /proc/PID/comm (bei spawn_app danach kurz „setpriv“). Ein service_alive in diesem Fenster
# hielte den eben gestarteten Dienst für tot (reload_chronyd ließe den alten chronyd laufen,
# der Watchdog meldete „unerwartet beendet“). wait_exec wartet höchstens ~1 s, bis das exec
# geschehen ist – mit <comm> bis genau dieser Name erscheint.
wait_exec() {  # wait_exec <pid> [comm]
  local pid="$1" want="${2:-}" own="" now="" i
  { read -r own < "/proc/$$/comm"; } 2>/dev/null || return 0
  for (( i = 0; i < 100; i++ )); do
    now=""
    { read -r now < "/proc/${pid}/comm"; } 2>/dev/null || true
    if [[ -n "$want" ]]; then
      [[ "$now" == "$want" || ( "$now" != "$own" && "$now" != setpriv ) ]] && return 0
    elif [[ "$now" != "$own" ]]; then
      return 0
    fi
    sleep 0.01 || true
  done
  return 0
}

# proc_ended <pid> -> 0, wenn der Prozess beendet ist (Zombie oder verschwunden). Ohne Unterprozess.
proc_ended() {
  local stat="" st
  { read -r stat < "/proc/$1/stat"; } 2>/dev/null || return 0
  st="${stat##*) }"
  [[ "${st:0:1}" == Z ]]
}

# stop_pid <eintrag> <name> -> beendet einen Dienst: SIGTERM, höchstens STOP_GRACE s warten, dann
# SIGKILL. Kehrt immer zurück: Scheitert das Signal (ohne CAP_KILL darf root keine Prozesse anderer
# Benutzer wie _chrony beenden), meldet es das laut und gibt 1 zurück, statt ewig zu warten.
STOP_GRACE=10
stop_pid() {
  local entry="$1" name="$2" pid="${1%%=*}" i
  [[ -n "$pid" ]] || return 0
  if service_alive "$entry"; then
    kill "$pid" 2>/dev/null || true
    for (( i = 0; i < ${STOP_GRACE:-10} * 10; i++ )); do
      proc_ended "$pid" && break
      sleep 0.1 || true
    done
    if ! proc_ended "$pid"; then
      log main "WARNUNG: ${name} (PID ${pid}) endet nicht auf SIGTERM – sende SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
      for (( i = 0; i < 30; i++ )); do
        proc_ended "$pid" && break
        sleep 0.1 || true
      done
    fi
    if ! proc_ended "$pid"; then
      log main "FEHLER: ${name} (PID ${pid}) lässt sich nicht beenden. Fehlt dem Container CAP_KILL" \
               "(cap_drop: ALL ohne cap_add: KILL)? Dann ist kein Neustart der Dienste möglich."
      "${EMIT_EVENT:-:}" service crit "Dienst ${name} lässt sich nicht beenden – fehlt CAP_KILL?" service="$name"
      return 1
    fi
  fi
  # Nur einen beendeten Prozess abräumen – ein fremder PID mit anderem Namen ließe 'wait' blockieren.
  if proc_ended "$pid"; then wait "$pid" 2>/dev/null || true; fi
  return 0
}

# Lebt der Dienst noch? Liest /proc nur mit Shell-Bordmitteln (read, Umleitung) – ohne Subshell und ohne
# externes Programm. Lässt sich gerade kein Prozess starten (Prozessgrenze des Containers erreicht), hielte
# eine fehlgeschlagene Prüfung sonst einen laufenden Pflichtdienst für tot und stoppte den Container.
service_alive() {
  local pid="${1%%=*}" comm="${1#*=}" actual="" own=""
  [[ -n "$pid" ]] || return 1
  if ! { read -r actual < "/proc/${pid}/comm"; } 2>/dev/null; then
    [[ -d "/proc/${pid}" ]] || return 1
    return 0  # Prozess besteht, nur das Lesen scheiterte: nicht als Ausfall werten
  fi
  { read -r own < "/proc/$$/comm"; } 2>/dev/null || true
  if [[ "$actual" != "$comm" && -n "$own" && ( "$actual" == "$own" || "$actual" == setpriv ) ]]; then
    wait_exec "$pid" "$comm"  # gerade erst gestartet: exec abwarten statt „tot“ zu melden
    { read -r actual < "/proc/${pid}/comm"; } 2>/dev/null || return 1
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
# stopped), restarts, last_exit, since (Unix-Zeit des letzten Zustandswechsels), next_retry
# (Unix-Zeit, aus der monotonen Frist SVC_NEXT umgerechnet).
write_services() {
  local name sep="" out entry pid optional t m retry
  t=$(now)
  m=$(mono)
  out="{\"time\": ${t}, \"services\": {"
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
    retry=null
    if [[ "${SVC_STATE[$name]:-}" == restarting && -n "${SVC_NEXT[$name]:-}" ]]; then
      retry=$(( t + SVC_NEXT[$name] - m ))
    fi
    out+=", \"next_retry\": ${retry}"
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
  if [[ "$2" == running ]]; then SVC_STARTED[$1]="$(mono)"; fi
  write_services
}

read_config_error() {  # ohne Subshell; fehlt die Datei, bleibt CONFIG_ERROR leer
  CONFIG_ERROR=""
  if [[ -f "${RUN_DIR}/config-error" ]]; then
    IFS= read -r CONFIG_ERROR < "${RUN_DIR}/config-error" || true
    CONFIG_ERROR="${CONFIG_ERROR//[\"\\]/\'}"
    CONFIG_ERROR="${CONFIG_ERROR:0:200}"
  fi
}

device_id() {  # Inode + Major/Minor des Knotens (folgt by-id-Links), leer wenn weg
  stat -L -c '%i:%t:%T' "$1" 2>/dev/null || true
}

# --- Konfiguration erzeugen ---------------------------------------------------
# apply_config [--start]: --start erlaubt confgen, bei einer von chronyd abgelehnten gespeicherten
# Einstellung ohne diesen Wert zu starten (statt dass jeder Start scheitert) – nie ohne schützende
# Einstellungen wie erlaubte/gesperrte Netze oder Ratelimit (dann kein Start).
CONFIG_ERROR=""   # Grund der letzten Ablehnung (confgen schreibt ihn nach RUN_DIR/config-error)
apply_config() {
  local out
  CONFIG_ERROR=""
  if ! out=$(python3 "${APP_DIR}/confgen.py" apply "$@"); then
    read_config_error
    log config "FEHLER: Konfiguration konnte nicht erzeugt werden – bisherige bleibt aktiv."
    return 1
  fi
  read_config_error
  eval "$out"
  # confgen läuft als root und kann settings.json migrieren – das Dashboard muss sie weiter schreiben dürfen.
  if [[ -z "$APP_DROP_OFF" && -n "${APP_USER:-}" ]] && (( EUID == 0 )); then data_dir_to_app; fi
  HOTPLUG_PATHS="${NTPGUI_HOTPLUG_PATHS:-}"
  NTS_WATCH="${NTPGUI_NTS_WATCH:-}"
  NTS_CERT_SIG="$(file_signature $NTS_WATCH)"
  NTS_CERT_PENDING=""
  NTS_CERT_DEFERRED=0   # chronyd startet danach ohnehin neu und lädt das aktuelle Zertifikat
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
check_nts_cert() {  # check_nts_cert <jetzt, monoton> -> 0 = neu laden
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
  # umask 007: Den Kommando-Socket legt chronyd mit dieser Maske an – so kann ihn das Dashboard
  # (Gruppe _chrony) nutzen; das Verzeichnis (0770) hält alle anderen fern.
  umask 0007
  spawn chrony /usr/sbin/chronyd "${chronyd_args[@]}"
  umask 0022
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
  ptp_socket_for_app
}

# Den Management-Socket von ptp4l (gehört root, 0660) für die Gruppe ntpgui öffnen: Das Dashboard
# liest darüber den Zustand und meldet als Grandmaster die GPS-Güte. Kurz im Hintergrund, bis
# ptp4l den Socket angelegt hat (höchstens ~10 s).
ptp_socket_for_app() {
  local uds="${NTPGUI_PTP_UDS:-/var/run/ptp4l}"
  [[ -z "$APP_DROP_OFF" ]] || return 0
  (
    local i
    for (( i = 0; i < 40; i++ )); do
      if [[ -S "$uds" && ! -L "$uds" ]]; then
        chgrp "$APP_USER" "$uds" 2>/dev/null && chmod 0660 "$uds" 2>/dev/null
        exit 0
      fi
      sleep 0.25
    done
  ) &
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
  rm -f "${REQUEST_DIR}/dnsfwd.ready"
  resolv_for_app
  # Port 53: im Docker-Netz ohne Capability, mit Host-Netzwerk braucht es NET_BIND_SERVICE.
  spawn_app dns net_bind_service python3 "${APP_DIR}/dnsfwd.py" serve
  SVC_ENTRY[dnsfwd]="$SPAWNED"
  set_state dnsfwd running
  for (( i = 0; i < 30; i++ )); do
    [[ -s "${REQUEST_DIR}/dnsfwd.ready" ]] && return 0
    service_alive "${SVC_ENTRY[dnsfwd]}" || return 0
    sleep 0.1
  done
  log dns "WARNUNG: Weiterleiter meldet sich nicht – chronyd startet trotzdem."
}

# Original-resolv.conf zurück, falls sie noch auf den Weiterleiter zeigt
# (Modus „system“, Absturz, Neustart des Containers ohne Neuerstellen).
dns_restore() {
  grep -q '^# ntp-gui: dnsfwd' "$RESOLV_CONF" 2>/dev/null || return 0
  # Wie der Weiterleiter selbst ohne root: Die Sicherung liegt im Datenverzeichnis des Dashboards.
  app_drop ""
  "${APP_DROP[@]}" python3 "${APP_DIR}/dnsfwd.py" restore || true
}

# resolv.conf für den Weiterleiter (APP_USER) beschreibbar machen: Docker bindet sie als eigene
# Datei je Container ein. Schreibgeschützt (read_only) bleibt sie, wie sie ist – dnsfwd fällt dann
# sauber auf den System-DNS zurück und nennt die Abhilfe „dns: 127.0.0.1“.
resolv_for_app() {
  [[ -z "$APP_DROP_OFF" && -f "$RESOLV_CONF" && ! -L "$RESOLV_CONF" ]] || return 0
  { chgrp "$APP_USER" "$RESOLV_CONF" && chmod 0664 "$RESOLV_CONF"; } 2>/dev/null || true
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
  NEXT_HOTPLUG=$(( $(mono) + HOTPLUG_EVERY ))
}

# stop_services [shutdown] -> beendet die Zeitdienste; 1 = ein Dienst ließ sich nicht beenden (fehlt
# CAP_KILL?), dann darf er nicht doppelt starten. Beim Neuladen (ohne „shutdown“) prüft „kill -0“
# vorher, ob jeder laufende Dienst ein Signal annimmt. Verweigert einer, bleibt alles, wie es ist:
# Nichts wird beendet, nichts blockiert den Watchdog. Scheitert das Beenden trotzdem, starten die
# schon beendeten Dienste sofort wieder. resolv.conf kommt nur zurück, wenn dnsfwd wirklich beendet ist.
stop_services() {
  local mode="${1:-reload}" name entry rc=0 refused="" stopped=" "
  if [[ "$mode" != shutdown ]]; then
    for name in phc2sys ptp4l gpsd chronyd dnsfwd; do
      entry="${SVC_ENTRY[$name]:-}"
      if [[ -n "$entry" ]] && service_alive "$entry" && ! kill -0 "${entry%%=*}" 2>/dev/null; then
        refused+=" ${name}"
      fi
    done
    if [[ -n "$refused" ]]; then
      log main "FEHLER: Signal an${refused} verweigert – fehlt dem Container CAP_KILL (cap_drop: ALL ohne" \
               "cap_add: KILL)? Alle Dienste laufen unverändert weiter."
      "${EMIT_EVENT:-:}" service crit "Dienste lassen sich nicht beenden (${refused# }) – fehlt CAP_KILL?" \
        service="${refused# }"
      return 1
    fi
  fi
  for name in phc2sys ptp4l gpsd chronyd dnsfwd; do
    entry="${SVC_ENTRY[$name]:-}"
    if [[ -n "$entry" ]] && service_alive "$entry"; then kill "${entry%%=*}" 2>/dev/null || true; fi
  done
  for name in phc2sys ptp4l gpsd chronyd dnsfwd; do
    entry="${SVC_ENTRY[$name]:-}"
    if [[ -n "$entry" ]] && ! stop_pid "$entry" "$name"; then rc=1; continue; fi
    [[ -z "$entry" ]] || stopped+="${name} "
    SVC_ENTRY[$name]=""
    SVC_STATE[$name]=stopped
  done
  # dnsfwd schreibt resolv.conf beim Beenden selbst zurück; nach einem SIGKILL nicht.
  if [[ -z "${SVC_ENTRY[dnsfwd]:-}" ]]; then dns_restore; fi
  if (( rc )) && [[ "$mode" != shutdown ]]; then
    for name in dnsfwd chronyd gpsd ptp4l phc2sys; do
      [[ "$stopped" == *" ${name} "* ]] || continue
      log main "Starte '${name}' wieder – der Neustart der übrigen Dienste ist gescheitert."
      "start_${name}" || true
    done
  fi
  write_services
  return "$rc"
}

reload_services() {
  log main "Einstellungen geändert – Zeitdienste werden neu gestartet …"
  write_status running "Zeitdienste werden neu gestartet"
  # Erst die neue Konfiguration erzeugen (confgen ersetzt die Dateien nur, wenn alle gelingen).
  # Scheitert das, laufen die Dienste ohne Neustart mit den bisherigen Einstellungen weiter.
  if ! apply_config; then
    write_status error "Konfiguration fehlerhaft – bisherige Einstellungen weiter aktiv${CONFIG_ERROR:+ (chronyd: ${CONFIG_ERROR})}"
    "${EMIT_EVENT:-:}" reload warn "Konfiguration fehlerhaft – bisherige Einstellungen bleiben aktiv${CONFIG_ERROR:+ (chronyd: ${CONFIG_ERROR})}" result=error
    return 0
  fi
  if ! stop_services; then
    # Ein Dienst läuft noch (Signal verweigert): nicht doppelt starten. Der Watchdog behält die übrigen.
    write_status error "Zeitdienste lassen sich nicht neu starten – fehlt dem Container CAP_KILL?"
    "${EMIT_EVENT:-:}" reload crit "Neustart der Zeitdienste gescheitert – ein Dienst ließ sich nicht beenden (fehlt CAP_KILL?)" result=error
    return 0
  fi
  local name
  for name in gpsd ptp4l phc2sys dnsfwd; do SVC_RESTARTS[$name]=0; SVC_EXIT[$name]=""; done
  start_services
  write_status done "Neue Einstellungen aktiv"
  log main "Neustart abgeschlossen."
  "${EMIT_EVENT:-:}" reload info "Neue Einstellungen aktiv – Zeitdienste neu gestartet" result=done
}

# Nur chronyd neu laden: confgen schreibt alle Dateien neu (beim erneuerten NTS-Zertifikat auch die
# Kopien von Zertifikat und Schlüssel), aber nur chronyd startet neu. gpsd, ptp4l, phc2sys und dnsfwd
# laufen weiter, damit GPS/PPS nicht neu einrasten, PTP nicht ausfällt und der DNS-Weiterleiter nicht
# neu beginnt. reload_chronyd [cert|settings] – „settings“: Anforderung reload-chronyd.request
# (automatische GPS-Fehlerschranke und Kalibrierung, die nur chrony.conf ändern).
reload_chronyd() {
  local entry why="${1:-cert}"
  write_status running "chronyd wird neu gestartet"
  if ! apply_config; then
    if [[ "$why" == settings ]]; then
      write_status error "Konfiguration fehlerhaft – bisherige Einstellungen weiter aktiv${CONFIG_ERROR:+ (chronyd: ${CONFIG_ERROR})}"
      "${EMIT_EVENT:-:}" reload warn "Konfiguration fehlerhaft – bisherige Einstellungen bleiben aktiv${CONFIG_ERROR:+ (chronyd: ${CONFIG_ERROR})}" result=error
    else
      write_status error "Konfiguration fehlerhaft – chronyd läuft mit dem bisherigen Zertifikat weiter"
      "${EMIT_EVENT:-:}" cert warn "Zertifikat erneuert, aber Konfiguration fehlerhaft – chronyd behält das alte" result=error
    fi
    return 0
  fi
  entry="${SVC_ENTRY[chronyd]:-}"
  # Signal verweigert (kill -0 prüft nur): gar nicht erst versuchen, statt STOP_GRACE s zu warten.
  if [[ -n "$entry" ]] && service_alive "$entry" && ! kill -0 "${entry%%=*}" 2>/dev/null; then
    log main "FEHLER: Signal an chronyd verweigert – fehlt dem Container CAP_KILL? chronyd läuft unverändert weiter."
    write_status error "chronyd lässt sich nicht neu starten – fehlt dem Container CAP_KILL?"
    return 0
  fi
  if [[ -n "$entry" ]] && ! stop_pid "$entry" chronyd; then
    # Der alte chronyd läuft weiter (Signal verweigert) – ein zweiter fände seine Ports belegt.
    write_status error "chronyd lässt sich nicht neu starten – fehlt dem Container CAP_KILL?"
    return 0
  fi
  SVC_ENTRY[chronyd]=""
  start_chronyd
  log main "chronyd neu gestartet."
  if [[ "$why" == settings ]]; then
    write_status done "Neue Einstellungen aktiv"
    "${EMIT_EVENT:-:}" reload info "Neue Einstellungen aktiv – nur chronyd neu gestartet" result=done scope=chronyd
  else
    write_status done "Zertifikat neu geladen"
    "${EMIT_EVENT:-:}" cert info "NTS-Zertifikat erneuert – chronyd hat es neu geladen" result=done
  fi
}

# Anforderungen des Dashboards abarbeiten (Hauptschleife, alle 2 s): reload.request startet alle
# Zeitdienste neu, reload-chronyd.request nur chronyd. Liegen beide an, genügt der volle Neustart.
process_reload_requests() {
  local req="${REQUEST_DIR:-$RUN_DIR}"
  # Neuladen: Das Dashboard legt reload.request an (kein SIGHUP mehr – ein Signal mitten in einem
  # „$( … )“ brachte den bash-Parser durcheinander und beendete den Container). Datei zuerst
  # löschen: Kommt während des Neuladens eine neue Anforderung, folgt ein weiterer Durchgang.
  if [[ -e "${req}/reload.request" || -L "${req}/reload.request" ]]; then
    # Zuerst „running“ vermerken, dann die Anforderung löschen: Ein Holdover-Test, der genau jetzt
    # startet, sieht so immer eins von beiden und wartet (holdover.reload_busy).
    write_status running "Neustart angefordert"
    rm -f "${req}/reload.request"
    RELOAD_REQUESTED=1
  fi
  if [[ -e "${req}/reload-chronyd.request" || -L "${req}/reload-chronyd.request" ]]; then
    write_status running "Neustart von chronyd angefordert"
    rm -f "${req}/reload-chronyd.request"
    CHRONYD_RELOAD_REQUESTED=1
  fi
  if (( RELOAD_REQUESTED )); then
    RELOAD_REQUESTED=0
    CHRONYD_RELOAD_REQUESTED=0   # der volle Neustart lädt chronyd mit
    reload_services
  elif (( CHRONYD_RELOAD_REQUESTED )); then
    CHRONYD_RELOAD_REQUESTED=0
    reload_chronyd settings
  fi
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
  local stopped=0 jobs_left
  stop_services shutdown || stopped=1
  if [[ -n "$WEB_PID" ]]; then stop_pid "$WEB_PID" web || stopped=1; fi
  # Nur auf die eigenen Hintergrundjobs warten: Ein 'wait' ohne Argument wartet in
  # bash 5.2 auch auf die Prozess-Substitution des Log-Tees – und die endet erst
  # nach uns (Container hinge dann bis zum SIGKILL). Ließ sich ein Dienst nicht beenden, gar nicht warten.
  jobs_left=$(jobs -p)
  if [[ -n "$jobs_left" ]] && (( ! stopped )); then
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
  t=$(mono)   # Laufzeit und nächste Frist nach monotoner Uhr
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

# hold_active -> 0 = REQUEST_DIR/reload.hold nennt eine Zeit in der Zukunft (Holdover-Test läuft).
# Das Verzeichnis gehört dem Dashboard: rootsafe.py öffnet ohne Links zu folgen und ohne zu blockieren
# und liest nur aus einer gewöhnlichen Datei (eine Pipe an dieser Stelle hält den Watchdog nicht auf).
hold_active() {
  local hold_until="" file="${REQUEST_DIR:-$RUN_DIR}/reload.hold"
  [[ -e "$file" || -L "$file" ]] || return 1
  hold_until="$(python3 "${APP_DIR}/rootsafe.py" hold "$file" 2>/dev/null)" || hold_until=""
  hold_until="${hold_until%%$'\n'*}"
  [[ "$hold_until" =~ ^[0-9]{1,12}$ ]] && (( 10#$hold_until >= $(now) ))
}

# reload_held <grund> [stufe] [hinweis] -> 0 = automatischen Neustart zurückstellen (Holdover-Test
# läuft). Je Grund und Test ein Ereignis.
reload_held() {
  if ! hold_active; then
    RELOAD_HOLD_NOTED=""
    return 1
  fi
  if [[ "$RELOAD_HOLD_NOTED" != *"|$1|"* ]]; then
    RELOAD_HOLD_NOTED+="|$1|"
    log main "$1 – zurückgestellt bis zum Ende des Holdover-Tests.${3:+ $3}"
    "${EMIT_EVENT:-:}" reload "${2:-info}" "$1 – zurückgestellt bis zum Ende des Holdover-Tests${3:+. $3}" reason=holdover
  fi
  return 0
}

# Geräte, die beim Start fehlten, aufgetaucht? GPS-Empfänger ab- und wieder
# angesteckt (neuer Geräteknoten)? Dann Konfiguration neu erzeugen – wie SIGHUP.
check_hotplug() {
  local path id
  for path in $HOTPLUG_PATHS; do
    if [[ -e "$path" ]]; then
      # Zurückgestellt: nur das Neuladen auslassen – die Prüfung „GPS-Gerät verschwunden“ unten läuft weiter.
      if reload_held "Gerät ${path} ist jetzt vorhanden – Neustart der Zeitdienste"; then break; fi
      write_status running "Gerät ${path} ist jetzt vorhanden"
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
      write_status running "GPS-Gerät neu angesteckt"
      log gps "${NTPGUI_GPS_DEVICE} wurde neu angesteckt – Konfiguration wird neu geladen."
      "${EMIT_EVENT:-:}" gps info "GPS-Gerät ${NTPGUI_GPS_DEVICE} wurde neu angesteckt" \
        reason=hotplug device="$NTPGUI_GPS_DEVICE"
      reload_services
    fi
  fi
  return 0
}

# --- Vorbereitung ------------------------------------------------------------
# Schreibgeschütztes Root-Dateisystem (read_only: true): erzeugte Konfiguration und ptp4l-Log nach
# /run (tmpfs), sofern der Pfad nicht ausdrücklich gesetzt ist. So startet der Container ohne
# zusätzliche Variablen; nötig sind nur tmpfs für /run, /tmp und /var/log (siehe docker-compose.vps.yml).
use_run_when_readonly() {
  local conf_dir="/run/ntp-gui-conf" moved=""
  if [[ -z "$CHRONY_CONF_GIVEN" && ! -w "${CHRONY_CONF%/*}" ]]; then
    CHRONY_CONF="${conf_dir}/chrony.conf"; moved+=" chrony.conf"
  fi
  if [[ -z "$PTP4L_CONF_GIVEN" && ! -w "${PTP4L_CONF%/*}" ]]; then
    PTP4L_CONF="${conf_dir}/ptp4l.conf"; moved+=" ptp4l.conf"
  fi
  if [[ -z "$PTP_LOG_GIVEN" && ! -w "${PTP_LOG_FILE%/*}" ]]; then
    PTP_LOG_FILE="${conf_dir}/ptp4l.log"; moved+=" ptp4l.log"
  fi
  [[ -n "$moved" ]] || return 0
  mkdir -p "$conf_dir"
  chmod 0755 "$conf_dir"
  export CHRONY_CONF PTP4L_CONF PTP_LOG_FILE
  log main "Dateisystem schreibgeschützt – erzeugte Dateien liegen unter ${conf_dir}:${moved}"
}

# Datenverzeichnis dem Benutzer APP_USER übergeben: einmalig nach dem Update von 1.8 (bisher gehörte
# es root), danach nur, falls root (confgen) etwas angelegt hat. Das Verzeichnis gehört dem Dashboard,
# darum übernimmt rootsafe.py nur Verzeichnisse und Dateien mit genau einem Namen, über den geöffneten
# Deskriptor und ohne Links zu folgen. Dateien mit weiteren Namen (Hardlinks) bleiben unverändert.
data_dir_to_app() {  # data_dir_to_app [announce]
  local skipped
  [[ -d "$DATA_DIR" && ! -L "$DATA_DIR" ]] || return 0
  chown -h "${APP_USER}:${APP_USER}" "$DATA_DIR" 2>/dev/null || true
  chmod 0700 "$DATA_DIR" 2>/dev/null || true
  [[ -n "$(find "$DATA_DIR" -mindepth 1 ! -user "$APP_USER" \( -type d -o -type f \) -print -quit 2>/dev/null)" ]] \
    || return 0
  [[ "${1:-}" == announce ]] && log main "Datenverzeichnis ${DATA_DIR} wird dem Benutzer ${APP_USER} übergeben …"
  if ! skipped="$(python3 "${APP_DIR}/rootsafe.py" chown "$DATA_DIR" "$APP_USER")"; then
    log main "WARNUNG: Datenverzeichnis nicht vollständig übernommen – Speichern kann scheitern."
  elif [[ -n "$skipped" ]]; then
    log main "WARNUNG: Dateien mit mehreren Namen (Hardlinks) im Datenverzeichnis bleiben unverändert:" \
             "${skipped//$'\n'/, }"
  fi
  return 0
}

# REQUEST_DIR beim Start vorbereiten: Nur die festen Anforderungen von vor dem Start (und
# angefangene *.tmp, alte pmc-Sockets) entfernen – Aufzeichnungen der Datenquellen und der Zustand
# des DNS-Weiterleiters bleiben über einen Neustart des Containers erhalten. Ist der Pfad ein Link
# oder kein Verzeichnis, wird er ersetzt. prepare_request_dir [benutzer]
prepare_request_dir() {
  local owner="${1:-}"
  if [[ -L "$REQUEST_DIR" ]] || [[ -e "$REQUEST_DIR" && ! -d "$REQUEST_DIR" ]]; then
    rm -f "$REQUEST_DIR"
  fi
  mkdir -p "$REQUEST_DIR"
  rm -f "${REQUEST_DIR}/reload.request" "${REQUEST_DIR}/reload-chronyd.request" "${REQUEST_DIR}/reload.hold" \
        "${REQUEST_DIR}"/*.tmp "${REQUEST_DIR}"/pmc-* 2>/dev/null || true
  if [[ -n "$owner" ]]; then
    chown -h "${owner}:${owner}" "$REQUEST_DIR"
    # Reste eines Laufs als root: Das Dashboard könnte sie nicht ersetzen. Entfernen statt
    # übernehmen – das Verzeichnis gehört dem Dashboard.
    find "$REQUEST_DIR" -mindepth 1 -maxdepth 1 ! -user "$owner" ! -type d -delete 2>/dev/null || true
  fi
  chmod 0750 "$REQUEST_DIR"
}

# Passwortdatei (WEB_PASSWORD_FILE) für das Dashboard bereitstellen: Ein Docker-Secret gehört oft root
# bzw. dem Benutzer auf dem Host und ist für ntpgui nicht lesbar – Kopie unter RUN_DIR, nur für die
# Gruppe ntpgui lesbar. Der Watchdog erneuert die Kopie, wenn sich das Original ändert
# (refresh_web_password), damit ein Passwortwechsel ohne Neustart des Containers wirkt.
WEB_PASSWORD_FILE_APP=""
WEB_PASSWORD_SIG=""
copy_web_password() {  # copy_web_password [leer] -> 0 = Kopie geschrieben („leer“: Dashboard gesperrt)
  local dir="${RUN_DIR}/secrets" tmp
  if [[ "${1:-}" != leer ]]; then
    [[ -n "${WEB_PASSWORD_FILE:-}" && -f "$WEB_PASSWORD_FILE" && -r "$WEB_PASSWORD_FILE" ]] || return 1
  fi
  mkdir -p "$dir"
  chmod 0750 "$dir"
  chgrp "$APP_USER" "$dir"
  tmp="${dir}/web_password.tmp"
  WEB_PASSWORD_SIG="$(file_signature "$WEB_PASSWORD_FILE")"
  if [[ "${1:-}" == leer ]]; then : > "$tmp"; else head -c 8192 -- "$WEB_PASSWORD_FILE" > "$tmp"; fi \
     && chgrp "$APP_USER" "$tmp" && chmod 0440 "$tmp" && mv -f "$tmp" "${dir}/web_password" \
     && { WEB_PASSWORD_FILE_APP="${dir}/web_password"; return 0; }
  rm -f "$tmp" 2>/dev/null || true
  return 1
}

# Original der Passwortdatei geändert? Dann die Kopie erneuern. Ist das Original nicht mehr lesbar,
# wird die Kopie leer – wie bei einer unlesbaren WEB_PASSWORD_FILE ist das Dashboard dann gesperrt.
refresh_web_password() {
  [[ -n "$WEB_PASSWORD_FILE_APP" ]] || return 0
  [[ "$(file_signature "$WEB_PASSWORD_FILE")" != "$WEB_PASSWORD_SIG" ]] || return 0
  if copy_web_password; then
    log main "Passwortdatei geändert – das Dashboard nutzt jetzt das neue Passwort."
    "${EMIT_EVENT:-:}" access info "Passwortdatei geändert – neues Passwort aktiv" reason=password_file
  elif copy_web_password leer; then
    log main "WARNUNG: Passwortdatei ${WEB_PASSWORD_FILE} nicht mehr lesbar – Dashboard gesperrt."
    "${EMIT_EVENT:-:}" access warn "Passwortdatei nicht mehr lesbar – Dashboard gesperrt" reason=password_file
  else
    log main "WARNUNG: Kopie der Passwortdatei nicht zu erneuern."
  fi
}

# Benutzer für Dashboard und DNS-Weiterleiter vorbereiten: Verzeichnisse, Übernahme des
# Datenverzeichnisses (bis 1.8 gehörte es root), Passwortdatei. Geht das nicht, bleibt alles wie
# bisher (root) – mit deutlicher Warnung.
prepare_app_user() {
  if (( EUID != 0 )); then
    APP_DROP_OFF="der Container läuft nicht als root"
  elif ! id -u "$APP_USER" >/dev/null 2>&1; then
    APP_DROP_OFF="Benutzer ${APP_USER} fehlt im Image"
  elif ! command -v setpriv >/dev/null 2>&1; then
    APP_DROP_OFF="setpriv fehlt im Image"
  elif ! cap_has 7 || ! cap_has 6; then
    APP_DROP_OFF="CAP_SETUID/CAP_SETGID fehlen (cap_add: [SETUID, SETGID])"
  fi
  if ! mkdir -p "$DATA_DIR" 2>/dev/null; then
    log main "FEHLER: Datenverzeichnis ${DATA_DIR} nicht erreichbar. Fehlt dem Container CAP_DAC_OVERRIDE" \
             "(cap_drop: ALL ohne cap_add: DAC_OVERRIDE)? Ohne sie kann der Supervisor die Verzeichnisse" \
             "von chronyd und Dashboard nicht öffnen."
    exit 1
  fi
  if [[ -n "$APP_DROP_OFF" ]]; then
    prepare_request_dir
    if (( EUID == 0 )); then
      log main "WARNUNG: Dashboard und DNS-Weiterleiter laufen als root, weil ${APP_DROP_OFF}."
      "${EMIT_EVENT:-:}" service warn "Dashboard läuft als root – ${APP_DROP_OFF}" reason=privileges
    fi
    return 0
  fi
  prepare_request_dir "$APP_USER"
  data_dir_to_app announce
  copy_web_password || true
}

start_logtee
mkdir -p /var/run/chrony /var/lib/chrony "$RUN_DIR"
use_run_when_readonly
mkdir -p /var/log/chrony /etc/linuxptp 2>/dev/null || true
echo "$$" > "${RUN_DIR}/supervisor.pid"
write_status idle "bereit"
if (( EUID == 0 )) && ! cap_has 1; then
  log main "WARNUNG: CAP_DAC_OVERRIDE fehlt – der Supervisor erreicht die Verzeichnisse von chronyd und"
  log main "         Dashboard nicht. Bei cap_drop: [ALL] gehört DAC_OVERRIDE zu cap_add."
fi
prepare_app_user   # entfernt Anforderungen von vor dem Start
if ! cap_has 5; then
  log main "WARNUNG: CAP_KILL fehlt – der Supervisor kann chronyd und das Dashboard nicht beenden."
  log main "         Speichern mit Neustart der Dienste scheitert dann. Bei cap_drop: [ALL] gehört KILL zu cap_add."
  "$EMIT_EVENT" service warn "CAP_KILL fehlt – Neustart der Zeitdienste nicht möglich" reason=capabilities
fi

# chronyd legt seine Rechte ab; gehören die Verzeichnisse root, schaltet er
# still den Kommando-Socket ab und das Dashboard sieht nichts mehr. Das
# Datenverzeichnis des Dashboards gehört dem Benutzer ntpgui (prepare_app_user).
CHRONY_USER=""
for candidate in _chrony chrony; do
  if id -u "$candidate" >/dev/null 2>&1; then CHRONY_USER="$candidate"; break; fi
done
if [[ -n "$CHRONY_USER" ]]; then
  chown -R "${CHRONY_USER}:${CHRONY_USER}" /var/run/chrony
  chown -R "${CHRONY_USER}:${CHRONY_USER}" /var/log/chrony 2>/dev/null || true
  chown "${CHRONY_USER}:${CHRONY_USER}" /var/lib/chrony
  find /var/lib/chrony -mindepth 1 -maxdepth 1 ! -name ntp-gui \
    -exec chown -R "${CHRONY_USER}:${CHRONY_USER}" {} + 2>/dev/null || true
fi
# 0770: Das Dashboard (Gruppe _chrony) erreicht den Kommando-Socket, sonst niemand.
chmod 770 /var/run/chrony

rm -f "${RUN_DIR}/config-error"
apply_config --start || { log main "Ohne gültige Konfiguration kein Start."; exit 1; }
START_CONFIG_ERROR="$CONFIG_ERROR"   # gesetzt: gespeicherte Einstellungen abgelehnt, Start ohne sie
start_services

# Dashboard ohne root. NET_RAW nur für die Client-Messung, NET_BIND_SERVICE nur für Ports unter 1024.
WEB_CAPS=""
[[ "${NTPGUI_CLIENTMON:-1}" == 1 ]] && WEB_CAPS+="net_raw,"
[[ "${WEB_PORT:-8080}" =~ ^[0-9]+$ ]] && (( 10#${WEB_PORT:-8080} < 1024 )) && WEB_CAPS+="net_bind_service"
if [[ -n "${WEB_PASSWORD_FILE_APP:-}" ]]; then
  WEB_PASSWORD_FILE="$WEB_PASSWORD_FILE_APP" spawn_app web "$WEB_CAPS" python3 "${APP_DIR}/server.py"
else
  spawn_app web "$WEB_CAPS" python3 "${APP_DIR}/server.py"
fi
WEB_PID="$SPAWNED"
SVC_ENTRY[web]="$WEB_PID"
set_state web running
# Version steht an einer Stelle: als Standard in server.py (der Release-Workflow prüft, dass sie zur Release-Version passt).
NTPGUI_VERSION="${NTPGUI_VERSION:-$(sed -n 's/^VERSION = os\.environ\.get("NTPGUI_VERSION", "\([^"]*\)").*/\1/p' "${APP_DIR}/server.py" 2>/dev/null)}"
"$EMIT_EVENT" startup info "ntp-gui gestartet" version="${NTPGUI_VERSION:-}"
if [[ -n "$START_CONFIG_ERROR" ]]; then
  write_status error "Gespeicherte Einstellung von chronyd abgelehnt (${START_CONFIG_ERROR}) – Start ohne sie"
  "$EMIT_EVENT" reload warn "Gespeicherte Einstellung von chronyd abgelehnt – gestartet ohne diesen Wert, Details im Container-Log (chronyd: ${START_CONFIG_ERROR})" result=error
fi

# --- Watchdog ------------------------------------------------------------------
open_pause
# Statt 'wait -n': bash 5.2 übersieht damit Kinder, die vor dem Aufruf gestorben
# sind. Der Watchdog erkennt jeden toten Dienst, auch beim Start.
while true; do
  process_reload_requests
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
  set_mono   # Fristen (SVC_NEXT, NEXT_HOTPLUG, NEXT_NTS_CERT) nach monotoner Uhr
  for name in gpsd ptp4l phc2sys dnsfwd; do
    case "${SVC_STATE[$name]:-stopped}" in
      running)
        if ! service_alive "${SVC_ENTRY[$name]:-}"; then schedule_restart "$name"; fi ;;
      restarting)
        if (( MONO >= ${SVC_NEXT[$name]:-0} )); then restart_service "$name"; fi ;;
    esac
  done
  if (( MONO >= NEXT_HOTPLUG )); then
    NEXT_HOTPLUG=$(( MONO + HOTPLUG_EVERY ))
    check_hotplug
    refresh_web_password
    # ptp4l schreibt sein Log unbegrenzt; ab 5 MB auf die letzten 256 KB kürzen (stat ist ein eigener
    # Prozess – darum nur alle HOTPLUG_EVERY Sekunden, nicht in jeder Runde).
    # In-place (cat >), damit der O_APPEND-Deskriptor von ptp4l gültig bleibt.
    if [[ -f "$PTP_LOG_FILE" ]] && (( $(stat -c %s "$PTP_LOG_FILE" 2>/dev/null || echo 0) > 5242880 )); then
      tail -c 262144 "$PTP_LOG_FILE" > "${PTP_LOG_FILE}.tmp" 2>/dev/null \
        && cat "${PTP_LOG_FILE}.tmp" > "$PTP_LOG_FILE" \
        && rm -f "${PTP_LOG_FILE}.tmp" \
        && log ptp "Log auf die letzten 256 KB gekürzt" || true
    fi
  fi
  if (( MONO >= NEXT_NTS_CERT )) && check_nts_cert "$MONO"; then
    NTS_CERT_DEFERRED=1
  fi
  if [[ -n "$RELOAD_HOLD_NOTED" ]] && ! hold_active; then RELOAD_HOLD_NOTED=""; fi
  # Zertifikat: als Warnung – bis zum Ende bietet chronyd das bisherige an (wurde der Schlüssel
  # kompromittiert oder ist das alte abgelaufen, den Test abbrechen).
  if (( NTS_CERT_DEFERRED )) && ! reload_held "NTS-Zertifikat erneuert – Neustart von chronyd" warn \
       "Bis dahin bietet chronyd das bisherige Zertifikat an – brich den Test ab, wenn das neue sofort gelten soll"; then
    NTS_CERT_DEFERRED=0
    log nts "Zertifikat erneuert – chronyd lädt neu"
    reload_chronyd
  fi
  # Ohne neuen Prozess warten; ein (manuelles) SIGHUP wirkt spätestens nach dieser Pause.
  pause 2
done
