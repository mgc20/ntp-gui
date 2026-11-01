#!/usr/bin/env bash
# Integrationstest gegen ein gebautes Image.
#
#   docker build -t ntp-gui:test .
#   tests/container-test.sh ntp-gui:test
#
# Prüft das Laufzeitverhalten, das sich mit Unittests nicht abbilden lässt:
# Capability-Erkennung, Healthcheck, Basic-Auth, gemountete Konfiguration,
# Verhalten ohne GPS-/PTP-Hardware, Einstellungen über die API samt Neustart
# der Dienste, Neustart optionaler Dienste (gpsd/ptp4l/phc2sys) samt
# services.json, Geräte-Hotplug, PTP-Grandmaster-Richtung, NTS-Server mit
# eigenem Namen samt automatischem Neuladen nach Zertifikatswechsel und
# sauberes Stoppen. Ab 1.3: Log-Seite, Diagnosepaket ohne Standort-/Kennungsdaten,
# Ereignisprotokoll, API-Schlüssel (read/admin), /api/v1, Übernahme des alten
# Verlaufs (history.json.gz → SQLite) und passive Client-Messung im Bridge-Netz.
set -uo pipefail

IMAGE="${1:-ntp-gui:test}"
PREFIX="ntpgui-it-$$"
CFG_DIR="$(mktemp -d)"
NTS_DIR="$(mktemp -d)"
DIAG_DIR="$(mktemp -d)"
PASS=0
FAIL=0

cleanup() {
  docker rm -f "${PREFIX}-a" "${PREFIX}-b" "${PREFIX}-c" "${PREFIX}-d" "${PREFIX}-e" "${PREFIX}-f" \
    "${PREFIX}-g" "${PREFIX}-h" "${PREFIX}-i" "${PREFIX}-j" >/dev/null 2>&1
  docker rm -f "${PREFIX}-k" >/dev/null 2>&1
  docker volume rm "${PREFIX}-data" "${PREFIX}-hist" >/dev/null 2>&1
  rm -rf "$CFG_DIR" "$NTS_DIR" "$DIAG_DIR"
}
trap cleanup EXIT

ok()   { PASS=$((PASS + 1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }
check() { # check <Beschreibung> <erwartet> <tatsächlich>
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (erwartet: $2, war: $3)"; fi
}
contains() { # contains <Beschreibung> <Text> <Suchbegriff>
  if grep -qF -e "$3" <<<"$2"; then ok "$1"; else bad "$1 (»$3« fehlt)"; fi
}
http() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }

# svc <container> <dienst> <feld> -> Wert aus /run/ntp-gui/services.json
svc() {
  docker exec "$1" python3 -c "import json,sys; print(json.load(open('/run/ntp-gui/services.json'))['services'][sys.argv[1]][sys.argv[2]])" "$2" "$3" 2>/dev/null
}
wait_svc() { # wait_svc <container> <dienst> <feld> <wert> <sekunden>
  local i
  for ((i = 0; i < $5; i++)); do
    [[ "$(svc "$1" "$2" "$3")" == "$4" ]] && return 0
    sleep 1
  done
  return 1
}

wait_for_health() { # wait_for_health <url> <sekunden>
  local url="$1" limit="${2:-60}" i
  for ((i = 0; i < limit; i++)); do
    [[ "$(http "$url")" == "200" ]] && return 0
    sleep 1
  done
  return 1
}

echo "Image: $IMAGE"
echo
echo "1) Start ohne CAP_SYS_TIME"
docker run -d --name "${PREFIX}-a" -p 18080:8080 \
  -e NTP_PORT=10123 -e NTP_POOLS="" -e NTP_SERVERS="" -e ALLOW_NETWORKS="0.0.0.0/0" \
  "$IMAGE" >/dev/null
if wait_for_health http://127.0.0.1:18080/healthz 90; then ok "healthz wird gesund"; else bad "healthz bleibt ungesund"; fi
LOGS=$(docker logs "${PREFIX}-a" 2>&1)
contains "Fehlende Capability wird erkannt" "$LOGS" "CAP_SYS_TIME fehlt"
CMDLINE=$(docker exec "${PREFIX}-a" sh -c 'ps -o args= -C chronyd | head -1')
contains "chronyd läuft mit -x" "$CMDLINE" "-x"
# 1.3.1 (Debian trixie): Schaltsekunden aus leap-seconds.list, nicht aus right/UTC.
CONF_A=$(docker exec "${PREFIX}-a" cat /etc/chrony/chrony.conf)
contains "chrony.conf nutzt leapseclist" "$CONF_A" "leapseclist /usr/share/zoneinfo/leap-seconds.list"
check "Schaltsekunden-Liste im Image" 0 "$(docker exec "${PREFIX}-a" sh -c 'grep -q "^[0-9]" /usr/share/zoneinfo/leap-seconds.list; echo $?')"
check "chronyd akzeptiert die Konfiguration" 0 "$(docker exec "${PREFIX}-a" sh -c 'chronyd -p -f /etc/chrony/chrony.conf >/dev/null 2>&1; echo $?')"
check "Dashboard antwortet"        200 "$(http http://127.0.0.1:18080/)"
check "Stylesheet wird geliefert"  200 "$(http http://127.0.0.1:18080/static/app.css)"
check "API antwortet"              200 "$(http http://127.0.0.1:18080/api/status)"
check "Verlauf antwortet"          200 "$(http http://127.0.0.1:18080/api/history)"
check "Konfiguration abrufbar"     200 "$(http http://127.0.0.1:18080/api/config)"
check "Metriken antworten"         200 "$(http http://127.0.0.1:18080/metrics)"
check "Unbekannte Route -> 404"    404 "$(http http://127.0.0.1:18080/gibtsnicht)"
check "Kein Ausbruch aus /static"  404 "$(curl -s -o /dev/null -w '%{http_code}' --path-as-is http://127.0.0.1:18080/static/../server.py)"

STATUS=$(curl -s --max-time 10 http://127.0.0.1:18080/api/status)
if python3 -c "
import json, sys
d = json.loads(sys.argv[1])
assert d['chrony_running'], 'chronyd antwortet nicht'
assert d['tracking'].get('stratum') is not None, 'kein Stratum'
assert 'system' in d and 'sources' in d and 'gps' in d and 'ptp' in d, 'Felder fehlen'
" "$STATUS" 2>/dev/null; then ok "API liefert vollständigen Status"; else bad "API-Status unvollständig"; fi
contains "Metrik ntpgui_up vorhanden" "$(curl -s http://127.0.0.1:18080/metrics)" "ntpgui_up 1"

echo
echo "1b) Log, Ereignisse, Diagnosepaket, Client-Messung (1.3)"
LOGJSON=$(curl -s --max-time 10 'http://127.0.0.1:18080/api/logs?lines=500')
if python3 -c "
import json, sys
d = json.loads(sys.argv[1])
assert d['available'], 'Logdatei fehlt'
texts = [l['text'] for l in d['lines']]
assert any(t.startswith('[') and '] starte: ' in t for t in texts), 'keine Supervisor-Zeilen'
assert any('chronyd' in t for t in texts), 'chronyd fehlt im Log'
" "$LOGJSON" 2>/dev/null; then ok "/api/logs liefert Zeilen des Supervisors"; else bad "/api/logs ohne Supervisor-Zeilen"; fi
contains "Log-Filter nach Text" "$(curl -s 'http://127.0.0.1:18080/api/logs?q=Dashboard&lines=5')" '"source": "web"'
STARTUP=""
for _ in $(seq 1 20); do
  STARTUP=$(curl -s --max-time 5 'http://127.0.0.1:18080/api/events?kinds=startup' \
    | python3 -c "import json,sys; print(sum(1 for e in json.load(sys.stdin)['events'] if e['source']=='supervisor'))" 2>/dev/null)
  [[ "$STARTUP" =~ ^[1-9] ]] && break
  sleep 1
done
if [[ "$STARTUP" =~ ^[1-9] ]]; then ok "Ereignisprotokoll enthält den Start (vom Supervisor)"; else bad "Start-Ereignis fehlt (${STARTUP:-keins})"; fi
HDRS=$(curl -s --max-time 30 -D - -o "$DIAG_DIR/paket.tar.gz" 'http://127.0.0.1:18080/api/diagnostics/bundle?clients=1')
contains "Diagnosepaket als Download" "$HDRS" 'attachment; filename="ntp-gui-diagnose-'
if tar -tzf "$DIAG_DIR/paket.tar.gz" >"$DIAG_DIR/liste.txt" 2>/dev/null; then ok "Diagnosepaket ist ein gültiges tar.gz"; else bad "Diagnosepaket ist kein gültiges tar.gz"; fi
contains "Diagnosepaket enthält MANIFEST.txt" "$(cat "$DIAG_DIR/liste.txt")" "/MANIFEST.txt"
mkdir -p "$DIAG_DIR/x" && tar -xzf "$DIAG_DIR/paket.tar.gz" -C "$DIAG_DIR/x" 2>/dev/null
CIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${PREFIX}-a")
CMAC=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}' "${PREFIX}-a")
CHOST=$(docker exec "${PREFIX}-a" hostname)
LEAKS=$(python3 - "$DIAG_DIR/x" "$CIP" "$CMAC" "$CHOST" <<'PY'
import ipaddress, os, re, sys
root, ip, mac, host = sys.argv[1:5]
found = []
for dp, _, files in os.walk(root):
    for name in files:
        text = open(os.path.join(dp, name), encoding="utf-8", errors="replace").read()
        for needle in (ip, mac, host):
            if needle and needle.lower() in text.lower():
                found.append(f"{name}: {needle}")
        if re.search(r'"(lat|lon|alt|azimuth|elevation|az|el)"\s*:\s*-?\d', text):
            found.append(f"{name}: Koordinaten/Satellitenwinkel")
        for m in re.finditer(r"(?<![\w.:])(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}(?![\w:])", text):
            if int(m.group(0)[:2], 16) & 1 == 0 and m.group(0) not in ("00:00:00:00:00:00",):
                found.append(f"{name}: MAC {m.group(0)}")
        for m in re.finditer(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])", text):
            try:
                addr = ipaddress.ip_address(m.group(1))
            except ValueError:
                continue
            if addr.is_global:
                found.append(f"{name}: öffentliche IP {addr}")
print("; ".join(found[:10]))
PY
)
check "Diagnosepaket ohne Koordinaten, MAC, öffentliche/eigene IP, Hostname" "" "$LEAKS"
PREVIEW=$(curl -s --max-time 30 'http://127.0.0.1:18080/api/diagnostics/preview')
contains "Vorschau zeigt, was entfernt wurde" "$PREVIEW" '"removed"'
CM=$(curl -s --max-time 10 http://127.0.0.1:18080/api/clients/offsets)
if python3 -c "
import json, sys
d = json.loads(sys.argv[1])
assert isinstance(d['available'], bool)
assert d['available'] or (d.get('reason') or '').strip(), 'nicht verfügbar, aber ohne Begründung'
if d['available']:
    assert d['running'] and d['port'] == 10123, d
" "$CM" 2>/dev/null; then ok "Client-Messung meldet Zustand im Bridge-Netz verständlich (available=$(python3 -c "import json,sys;print(json.loads(sys.argv[1])['available'])" "$CM" 2>/dev/null))"
else bad "Client-Messung: unklare Antwort ($CM)"; fi

echo
echo "1c) Schutz vor DNS-Rebinding (ohne Passwort)"
A=http://127.0.0.1:18080
check "Fremder Host-Name: Dashboard 403"   403 "$(http -H 'Host: attacker.example' "$A/")"
check "Fremder Host-Name: API 403"         403 "$(http -H 'Host: attacker.example:18080' "$A/api/status")"
check ".fritz.box ist nicht automatisch lokal" 403 "$(http -H 'Host: pi.fritz.box' "$A/api/status")"
check "healthz mit fremdem Host bleibt offen" 200 "$(http -H 'Host: attacker.example' "$A/healthz")"
check "Container-IP als Host erlaubt"     200 "$(http -H "Host: $CIP:8080" "$A/api/status")"
check "localhost als Host erlaubt"        200 "$(http -H 'Host: localhost:18080' "$A/api/status")"
check "*.local als Host erlaubt"          200 "$(http -H 'Host: zeitserver.local' "$A/api/status")"
contains "403 erklärt WEB_ALLOWED_HOSTS"  "$(curl -s -H 'Host: attacker.example' "$A/api/status")" "WEB_ALLOWED_HOSTS"
# Ein überlanger Host-Name landet (bereinigt) im Log – der Export darf daran nicht scheitern.
LONGHOST="$(printf 'a%.0s' $(seq 1 64)).attacker.de"
check "Überlanger Host-Name abgewiesen"   403 "$(http -H "Host: $LONGHOST" "$A/api/status")"
for _ in $(seq 1 10); do
  grep -qF "<ungültig>" <<<"$(docker exec "${PREFIX}-a" tail -n 50 /run/ntp-gui/ntp-gui.log 2>/dev/null)" && break
  sleep 1
done
contains "Log nennt den abgewiesenen Namen nur bereinigt" "$(docker exec "${PREFIX}-a" tail -n 50 /run/ntp-gui/ntp-gui.log 2>/dev/null)" "<ungültig>"
check "Diagnose-Vorschau trotz fremdem Log-Eintrag" 200 "$(http --max-time 30 "$A/api/diagnostics/preview")"

echo
echo "2) NTP-Dienst im Netz"
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${PREFIX}-a")
if command -v chronyd >/dev/null 2>&1; then
  QUERY=$(timeout 25 chronyd -Q -t 15 "server $IP port 10123 iburst maxsamples 1" 2>&1)
  contains "Container beantwortet NTP-Anfragen" "$QUERY" "System clock wrong by"
else
  echo "  – chronyd auf dem Host nicht vorhanden, NTP-Abfrage übersprungen"
fi

echo
echo "3) Gemountete Konfiguration und Basic-Auth"
cat > "$CFG_DIR/chrony.conf" <<CONF
local stratum 7
allow 0.0.0.0/0
port 10124
bindcmdaddress /var/run/chrony/chronyd.sock
cmdport 0
CONF
docker run -d --name "${PREFIX}-b" -p 18081:8080 -v "$CFG_DIR:/config:ro" \
  -e WEB_USER=admin -e WEB_PASSWORD='S3hr geheim' "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18081/healthz 90 || true
contains "Eigene Konfiguration wird übernommen" "$(docker logs "${PREFIX}-b" 2>&1)" "verwende gemountete /config/chrony.conf"
STRATUM=$(curl -s -u 'admin:S3hr geheim' http://127.0.0.1:18081/api/status | python3 -c "import json,sys; print(json.load(sys.stdin)['tracking'].get('stratum'))" 2>/dev/null)
check "Stratum aus eigener Konfiguration" 7 "$STRATUM"
check "Ohne Login abgewiesen"   401 "$(http http://127.0.0.1:18081/api/status)"
check "Falsches Passwort abgewiesen" 401 "$(http -u admin:falsch http://127.0.0.1:18081/api/status)"
check "Mit Login erlaubt"       200 "$(http -u 'admin:S3hr geheim' http://127.0.0.1:18081/api/status)"
check "healthz bleibt offen"    200 "$(http http://127.0.0.1:18081/healthz)"
check "Mit Login gilt jeder Host-Name" 200 "$(http -u 'admin:S3hr geheim' -H 'Host: attacker.example' http://127.0.0.1:18081/api/status)"
check "Fremder Host ohne Login: 401" 401 "$(http -H 'Host: attacker.example' http://127.0.0.1:18081/api/status)"

echo
echo "3b) API-Schlüssel und /api/v1"
B=http://127.0.0.1:18081
LOGIN=(-u 'admin:S3hr geheim' -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1')
token_of() { python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null; }
READ_KEY=$(curl -s --max-time 15 "${LOGIN[@]}" -d '{"name":"Monitoring","scope":"read"}' "$B/api/apikeys" | token_of)
ADMIN_KEY=$(curl -s --max-time 15 "${LOGIN[@]}" -d '{"name":"Automatisierung","scope":"admin"}' "$B/api/apikeys" | token_of)
if [[ "$READ_KEY" == ntpg_* && "$ADMIN_KEY" == ntpg_* ]]; then ok "Schlüssel werden angelegt"; else bad "Schlüssel nicht angelegt"; fi
JSON=(-H 'Content-Type: application/json')
check "read-Schlüssel: GET erlaubt"            200 "$(http -H "Authorization: Bearer $READ_KEY" "$B/api/v1/status")"
check "read-Schlüssel: /metrics erlaubt"       200 "$(http -H "Authorization: Bearer $READ_KEY" "$B/metrics")"
check "read-Schlüssel: POST abgewiesen"        403 "$(http -X POST -H "Authorization: Bearer $READ_KEY" "${JSON[@]}" -d '{"values":{"web_title":"x"}}' "$B/api/v1/settings")"
check "admin-Schlüssel: POST erlaubt (ohne X-NTP-GUI)" 200 "$(http -X POST -H "Authorization: Bearer $ADMIN_KEY" "${JSON[@]}" -d '{"values":{"web_refresh_seconds":7}}' "$B/api/v1/settings")"
check "admin-Schlüssel: keine Schlüssel ausstellen" 403 "$(http -X POST -H "Authorization: Bearer $ADMIN_KEY" "${JSON[@]}" -d '{"name":"x","scope":"admin"}' "$B/api/apikeys")"
check "admin-Schlüssel: Passwort nicht änderbar" 403 "$(http -X POST -H "Authorization: Bearer $ADMIN_KEY" "${JSON[@]}" -d '{"clear":true}' "$B/api/auth")"
check "Falscher Schlüssel abgewiesen"         401 "$(http -H 'Authorization: Bearer ntpg_AAAAAAAAbbbbbbbbbbbbbbbbbbbbbbbb' "$B/api/v1/status")"
KEY_ID=${READ_KEY:5:8}
check "Schlüssel widerrufen" 200 "$(http -X POST "${LOGIN[@]}" -d "{\"id\":\"$KEY_ID\"}" "$B/api/apikeys/revoke")"
check "Widerrufener Schlüssel abgewiesen"     401 "$(http -H "Authorization: Bearer $READ_KEY" "$B/api/v1/status")"
SAME=$(python3 -c "
import json, sys
a, b = json.loads(sys.argv[1]), json.loads(sys.argv[2])
print(sorted(a) == sorted(b))" "$(curl -s -u 'admin:S3hr geheim' "$B/api/status")" "$(curl -s -H "Authorization: Bearer $ADMIN_KEY" "$B/api/v1/status")" 2>/dev/null)
check "/api/v1/status hat dieselben Schlüssel wie /api/status" True "$SAME"
contains "GET /api/v1 beschreibt die Endpunkte" "$(curl -s -u 'admin:S3hr geheim' "$B/api/v1")" '"path": "/api/v1/status"'
contains "Instanz-Kennung abrufbar" "$(curl -s -H "Authorization: Bearer $ADMIN_KEY" "$B/api/v1/instance")" '"instance_id"'

echo
echo "4) GPS und PTP aktiviert, aber keine Hardware vorhanden"
docker run -d --name "${PREFIX}-c" -p 18082:8080 \
  -e GPS_ENABLE=true -e GPS_DEVICE=/dev/ttyACM0 -e GPS_WAIT_SECONDS=2 \
  -e PTP_ENABLE=true -e NTP_PORT=10125 -e NTP_POOLS="" \
  -e WEB_ALLOWED_HOSTS="zeit.example.org, *.fritz.box" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18082/healthz 90 || true
check "WEB_ALLOWED_HOSTS: eingetragener Name erlaubt" 200 "$(http -H 'Host: zeit.example.org' http://127.0.0.1:18082/api/status)"
check "WEB_ALLOWED_HOSTS: *.fritz.box erlaubt" 200 "$(http -H 'Host: pi.fritz.box' http://127.0.0.1:18082/api/status)"
check "WEB_ALLOWED_HOSTS: anderer Name weiter 403" 403 "$(http -H 'Host: attacker.example' http://127.0.0.1:18082/api/status)"
LOGS=$(docker logs "${PREFIX}-c" 2>&1)
contains "Warnung wegen fehlendem GPS-Gerät" "$LOGS" "/dev/ttyACM0 nicht gefunden"
contains "Warnung wegen fehlendem PTP-Interface" "$LOGS" "kein Interface gewählt"
check "Container läuft trotzdem" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-c")"
REFCLOCKS=$(docker exec "${PREFIX}-c" sh -c 'grep -c refclock /etc/chrony/chrony.conf || true')
check "Keine tote Refclock-Zeile" 0 "$REFCLOCKS"

echo
echo "5) Dienst stirbt beim Start (wait -n hätte das übersehen)"
docker run -d --name "${PREFIX}-d" \
  -e EXTRA_CHRONY_CONF="diese zeile versteht chronyd nicht" \
  -e NTP_PORT=10126 -e NTP_POOLS="" "$IMAGE" >/dev/null
DEAD=0
for _ in $(seq 1 30); do
  if [[ "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-d")" == "exited" ]]; then DEAD=1; break; fi
  sleep 1
done
if [[ "$DEAD" == 1 ]]; then ok "Container beendet sich, statt kaputt weiterzulaufen"; else bad "Container läuft trotz totem chronyd weiter"; fi
check "Exit-Code signalisiert Fehler" 1 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-d")"
contains "Watchdog meldet den toten Dienst" "$(docker logs "${PREFIX}-d" 2>&1)" "unerwartet beendet"
docker rm -f "${PREFIX}-d" >/dev/null 2>&1

echo
echo "6) Einstellungen über das Dashboard"
docker volume create "${PREFIX}-data" >/dev/null
docker run -d --name "${PREFIX}-e" -p 18083:8080 -v "${PREFIX}-data:/var/lib/chrony" \
  -e NTP_PORT=10127 -e NTP_POOLS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18083/healthz 90 || true
API=http://127.0.0.1:18083/api/settings
post() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$@"; }
check "Einstellungen abrufbar" 200 "$(http "$API")"
check "POST ohne CSRF-Header abgewiesen" 403 "$(post -H 'Content-Type: application/json' -d '{"changes":{"web_title":"x"}}' "$API")"
check "POST von fremder Origin abgewiesen" 403 "$(post -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' -H 'Origin: http://evil.example' -d '{"changes":{"web_title":"x"}}' "$API")"
check "Ungültiger Wert abgewiesen" 422 "$(post -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' -d '{"changes":{"allow_networks":["10.0.0.0/8\ncmdallow"]}}' "$API")"
RESULT=$(curl -s --max-time 10 -X POST -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' \
  -d '{"changes":{"local_stratum":8,"web_title":"IT-Uhr"}}' "$API")
contains "Speichern löst Neustart aus" "$RESULT" '"reload_triggered": true'
STATE=""
for _ in $(seq 1 40); do
  STATE=$(curl -s --max-time 5 http://127.0.0.1:18083/api/reload | python3 -c "import json,sys; print(json.load(sys.stdin).get('state'))" 2>/dev/null)
  [[ "$STATE" == "done" || "$STATE" == "error" ]] && break
  sleep 1
done
check "Dienste neu gestartet" done "$STATE"
check "Erzeugte chrony.conf ist gültig" 0 "$(docker exec "${PREFIX}-e" sh -c 'chronyd -p -f /etc/chrony/chrony.conf >/dev/null 2>&1; echo $?')"
contains "chrony.conf enthält neuen Wert" "$(docker exec "${PREFIX}-e" cat /etc/chrony/chrony.conf)" "local stratum 8"
STRATUM=""
for _ in $(seq 1 20); do
  STRATUM=$(curl -s http://127.0.0.1:18083/api/status | python3 -c "import json,sys; print(json.load(sys.stdin)['tracking'].get('stratum'))" 2>/dev/null)
  [[ "$STRATUM" == "8" ]] && break
  sleep 1
done
check "chronyd nutzt neuen Wert" 8 "$STRATUM"
check "Container läuft nach Neustart" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-e")"
PERMS=$(docker exec "${PREFIX}-e" stat -c '%a' /var/lib/chrony/ntp-gui/settings.json)
check "settings.json nur für root lesbar" 600 "$PERMS"
docker rm -f "${PREFIX}-e" >/dev/null 2>&1
docker run -d --name "${PREFIX}-f" -p 18084:8080 -v "${PREFIX}-data:/var/lib/chrony" \
  -e NTP_PORT=10128 -e NTP_POOLS="" -e WEB_READONLY=true "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18084/healthz 90 || true
contains "Einstellungen überleben Neuerstellung" "$(docker exec "${PREFIX}-f" cat /etc/chrony/chrony.conf)" "local stratum 8"
check "WEB_READONLY sperrt Änderungen" 403 "$(post -H 'Content-Type: application/json' -H 'X-NTP-GUI: 1' -d '{"changes":{"web_title":"x"}}' http://127.0.0.1:18084/api/settings)"
docker rm -f "${PREFIX}-f" >/dev/null 2>&1

echo
echo "8) Optionaler Dienst stirbt – Container läuft weiter"
# /dev/null besteht die Geräteprüfung und gpsd läuft darauf (liest nur nichts).
docker run -d --name "${PREFIX}-g" -p 18085:8080 \
  -e GPS_ENABLE=true -e GPS_DEVICE=/dev/null -e NTP_PORT=10129 -e NTP_POOLS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18085/healthz 90 || true
# Ältere gpsd-Versionen (Debian: 3.22) beenden sich auf /dev/null von selbst; der
# Supervisor startet sie dann mit Backoff neu. Deshalb erst auf "running" warten
# (deckt den 60-s-Backoff ab) und den Zähler vor dem Abschießen merken.
if wait_svc "${PREFIX}-g" gpsd state running 75; then ok "gpsd läuft laut services.json"; else bad "gpsd läuft nicht (state: $(svc "${PREFIX}-g" gpsd state))"; fi
BEFORE=$(svc "${PREFIX}-g" gpsd restarts); BEFORE=${BEFORE:-0}
docker exec "${PREFIX}-g" pkill -x gpsd >/dev/null 2>&1
RESTARTED=0
for _ in $(seq 1 30); do
  NOW_R=$(svc "${PREFIX}-g" gpsd restarts)
  if [[ "$NOW_R" =~ ^[0-9]+$ ]] && (( NOW_R > BEFORE )); then RESTARTED=1; break; fi
  sleep 1
done
if (( RESTARTED )); then ok "gpsd wird neu gestartet"; else bad "gpsd wurde nicht neu gestartet"; fi
check "Container läuft nach gpsd-Ausfall weiter" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-g")"
if wait_svc "${PREFIX}-g" gpsd state running 75; then ok "gpsd läuft wieder"; else bad "gpsd läuft nicht wieder (state: $(svc "${PREFIX}-g" gpsd state))"; fi
contains "Watchdog meldet Neustart statt Stopp" "$(docker logs "${PREFIX}-g" 2>&1)" "NTP läuft weiter"
RESTART_EVENT=""
for _ in $(seq 1 20); do
  RESTART_EVENT=$(curl -s --max-time 5 'http://127.0.0.1:18085/api/events?kinds=service' \
    | python3 -c "import json,sys; print(sum(1 for e in json.load(sys.stdin)['events'] if 'gpsd' in e['title'] and 'beendet' in e['title']))" 2>/dev/null)
  [[ "$RESTART_EVENT" =~ ^[1-9] ]] && break
  sleep 1
done
if [[ "$RESTART_EVENT" =~ ^[1-9] ]]; then ok "Ereignisprotokoll enthält den Neustart von gpsd"; else bad "Neustart-Ereignis fehlt (${RESTART_EVENT:-keins})"; fi
check "chronyd unberührt" 0 "$(svc "${PREFIX}-g" chronyd restarts)"
docker rm -f "${PREFIX}-g" >/dev/null 2>&1

echo
echo "9) GPS-Gerät wird nachträglich eingesteckt (Hotplug)"
# /dev/shm/... besteht die /dev/-Prüfung und lässt sich ohne mknod anlegen.
docker run -d --name "${PREFIX}-h" -p 18086:8080 -e GPS_ENABLE=true -e GPS_DEVICE=/dev/shm/gps \
  -e GPS_WAIT_SECONDS=1 -e NTP_PORT=10130 -e NTP_POOLS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18086/healthz 90 || true
check "gpsd wartet auf das Gerät" stopped "$(svc "${PREFIX}-h" gpsd state)"
docker exec "${PREFIX}-h" touch /dev/shm/gps
if wait_svc "${PREFIX}-h" gpsd state running 60; then ok "gpsd startet nach dem Einstecken"; else bad "Hotplug nicht erkannt"; fi
check "GPS-Refclock nach Hotplug eingetragen" 1 "$(docker exec "${PREFIX}-h" sh -c 'grep -c "refclock SHM" /etc/chrony/chrony.conf')"
docker rm -f "${PREFIX}-h" >/dev/null 2>&1

echo
echo "10) PTP-Grandmaster: Richtung von phc2sys, ptp4l-Ausfall"
# Die veth-Karte im Container kann keine Hardware-Zeitstempel: ptp4l bricht ab
# und wird mit Backoff neu gestartet, NTP und Dashboard laufen weiter.
docker run -d --name "${PREFIX}-i" -p 18087:8080 -e PTP_ENABLE=true -e PTP_INTERFACE=eth0 \
  -e PTP_MODE=master -e PHC2SYS_ENABLE=true -e NTP_PORT=10131 -e NTP_POOLS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18087/healthz 90 || true
CMDLINE=$(docker exec "${PREFIX}-i" sh -c 'ps -o args= -C phc2sys | head -1')
contains "Grandmaster: phc2sys überträgt die Systemuhr (-a -rr)" "$CMDLINE" "-a -rr"
contains "Grandmaster: chronyd regelt weiter" "$(docker logs "${PREFIX}-i" 2>&1)" "chronyd regelt weiter"
if wait_svc "${PREFIX}-i" ptp4l last_exit 255 30 || [[ "$(svc "${PREFIX}-i" ptp4l state)" == restarting ]]; then
  ok "ptp4l-Ausfall wird in services.json gemeldet"
else
  bad "ptp4l-Ausfall fehlt in services.json (state: $(svc "${PREFIX}-i" ptp4l state))"
fi
check "Container läuft trotz ptp4l-Ausfall" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-i")"
check "Dashboard antwortet trotz ptp4l-Ausfall" 200 "$(http http://127.0.0.1:18087/api/status)"
docker rm -f "${PREFIX}-i" >/dev/null 2>&1

echo
echo "11) All-in-one-Start mit Host-Netzwerk, ohne Hardware"
HOSTNET="${PREFIX}-host"
if docker run -d --name "$HOSTNET" --network host -e WEB_PORT=18188 -e NTP_PORT=10132 -e NTP_POOLS="" \
     -e GPS_ENABLE=true -e GPS_DEVICE=/dev/ttyACM-fehlt -e GPS_PPS_DEVICE=/dev/pps-fehlt \
     -e GPS_WAIT_SECONDS=1 -e PTP_ENABLE=false -e NTS_NOCERTTIMECHECK=true "$IMAGE" >/dev/null 2>&1 \
   && wait_for_health http://127.0.0.1:18188/healthz 60; then
  ok "Start mit network_mode host ohne GPS/PPS/PTP-Hardware"
  contains "Fehlende Geräte werden beobachtet" "$(docker logs "$HOSTNET" 2>&1)" "Warte auf Geräte"
  check "Container läuft" running "$(docker inspect -f '{{.State.Status}}' "$HOSTNET")"
else
  echo "  – Host-Netzwerk hier nicht erreichbar, Prüfung übersprungen"
fi
docker rm -f "$HOSTNET" >/dev/null 2>&1

echo
echo "12) NTS-Server mit eigenem Namen, Zertifikat wird erneuert"
# Selbst signiertes Zertifikat für den Namen, unter dem die Clients den Server
# erreichen (z. B. hinter einem Reverse Proxy).
NTS_NAME=zeit.example.test
make_cert() { # make_cert <Seriennummer>
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 30 \
    -subj "/CN=${NTS_NAME}" -addext "subjectAltName=DNS:${NTS_NAME}" -set_serial "$1" \
    -keyout "$NTS_DIR/new.key" -out "$NTS_DIR/new.crt" >/dev/null 2>&1
  # Wie Certbot: neue Dateien schreiben und dann ersetzen.
  mv -f "$NTS_DIR/new.key" "$NTS_DIR/nts.key" && mv -f "$NTS_DIR/new.crt" "$NTS_DIR/nts.crt"
}
# served_serial <container> -> Seriennummer des Zertifikats, das chronyd per NTS-KE ausliefert
# chronyd nimmt NTS-KE nur aus den erlaubten Netzen an (allow), 127.0.0.1 gehört
# nicht dazu – deshalb über die Container-Adresse im Docker-Netz verbinden.
served_serial() {
  local ip
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1")
  docker exec "$1" sh -c "openssl s_client -connect ${ip}:4460 -servername ${NTS_NAME} -alpn ntske/1 \
    </dev/null 2>/dev/null | openssl x509 -noout -serial 2>/dev/null" | sed 's/^serial=//'
}
if make_cert 0x1001; then
  docker run -d --name "${PREFIX}-j" -p 18089:8080 -v "$NTS_DIR:/certs:ro" \
    -e NTS_SERVER=true -e NTS_SERVER_CERT=/certs/nts.crt -e NTS_SERVER_KEY=/certs/nts.key \
    -e NTS_SERVER_NAME="$NTS_NAME" -e NTP_PORT=10133 -e NTP_POOLS="" -e NTP_SERVERS="" "$IMAGE" >/dev/null
  wait_for_health http://127.0.0.1:18089/healthz 90 || true
  CONF=$(docker exec "${PREFIX}-j" cat /etc/chrony/chrony.conf)
  contains "chrony.conf nennt den Servernamen" "$CONF" "ntsntpserver ${NTS_NAME}"
  contains "chrony.conf nutzt die lesbare Kopie" "$CONF" "ntsservercert /var/lib/chrony/nts-certs/server.crt"
  check "chronyd akzeptiert die Konfiguration" 0 "$(docker exec "${PREFIX}-j" sh -c 'chronyd -p -f /etc/chrony/chrony.conf >/dev/null 2>&1; echo $?')"
  check "Kopie für _chrony nur lesbar (root:_chrony 640)" "root:_chrony 640" "$(docker exec "${PREFIX}-j" stat -c '%U:%G %a' /var/lib/chrony/nts-certs/server.key)"
  if grep -qF "Having write access" <<<"$(docker logs "${PREFIX}-j" 2>&1)"; then bad "chronyd meldet Schreibzugriff auf Schlüssel"
  else ok "chronyd meldet keinen Schreibzugriff auf Schlüssel"; fi
  SERIAL=""
  for ((i = 0; i < 30; i++)); do SERIAL=$(served_serial "${PREFIX}-j"); [[ -n "$SERIAL" ]] && break; sleep 1; done
  check "NTS-KE liefert das Zertifikat aus" 1001 "$SERIAL"
  MATCH=$(curl -s --max-time 10 http://127.0.0.1:18089/api/status \
    | python3 -c 'import json,sys; n=json.load(sys.stdin)["nts_server"]; print(n.get("name"), n.get("name_matches_cert"), n.get("cert_self_signed"))' 2>/dev/null)
  check "/api/status: Name passt zum Zertifikat" "${NTS_NAME} True True" "$MATCH"
  # svc_pids <container> -> "dienst=pid" je laufendem Dienst laut services.json
  svc_pids() {
    docker exec "$1" cat /run/ntp-gui/services.json 2>/dev/null | python3 -c 'import json,sys
s=json.load(sys.stdin)["services"]
print(" ".join(f"{n}={v.get('"'"'pid'"'"')}" for n, v in sorted(s.items()) if v.get("state") == "running"))' 2>/dev/null
  }
  PIDS_BEFORE=$(svc_pids "${PREFIX}-j")
  make_cert 0x1002
  RELOADED=""
  for ((i = 0; i < 120; i++)); do
    if grep -qF "Zertifikat erneuert" <<<"$(docker logs "${PREFIX}-j" 2>&1)" \
       && [[ "$(served_serial "${PREFIX}-j")" == 1002 ]]; then RELOADED=1; break; fi
    sleep 1
  done
  if [[ -n "$RELOADED" ]]; then ok "Erneuertes Zertifikat wird ohne Neustart des Containers geladen ($i s)"
  else bad "Erneuertes Zertifikat nicht geladen (ausgeliefert: $(served_serial "${PREFIX}-j"))"; fi
  # Nur chronyd darf neu starten; alle anderen Dienste behalten ihre PID.
  PIDS_AFTER=$(svc_pids "${PREFIX}-j")
  OTHERS_BEFORE=$(tr ' ' '\n' <<<"$PIDS_BEFORE" | grep -v '^chronyd=' | sort | tr '\n' ' ')
  OTHERS_AFTER=$(tr ' ' '\n' <<<"$PIDS_AFTER" | grep -v '^chronyd=' | sort | tr '\n' ' ')
  if [[ "$PIDS_BEFORE" == *chronyd=* && "$PIDS_AFTER" == *chronyd=* \
        && "$(grep -o 'chronyd=[0-9]*' <<<"$PIDS_BEFORE")" != "$(grep -o 'chronyd=[0-9]*' <<<"$PIDS_AFTER")" \
        && "$OTHERS_BEFORE" == "$OTHERS_AFTER" ]]; then
    ok "Erneuerung startet nur chronyd neu (übrige Dienste: ${OTHERS_AFTER:-keine})"
  else bad "Erneuerung startet nicht nur chronyd neu (vorher: $PIDS_BEFORE, nachher: $PIDS_AFTER)"; fi
  check "Container läuft nach dem Neuladen" running "$(docker inspect -f '{{.State.Status}}' "${PREFIX}-j")"
else
  echo "  – openssl fehlt auf dem Host, Prüfung übersprungen"
fi
docker rm -f "${PREFIX}-j" >/dev/null 2>&1

echo
echo "12b) Verlauf aus 1.2 (history.json.gz) wird übernommen"
docker volume create "${PREFIX}-hist" >/dev/null
docker run --rm -v "${PREFIX}-hist:/var/lib/chrony" --entrypoint python3 "$IMAGE" -c "
import gzip, json, os, time
os.makedirs('/var/lib/chrony/ntp-gui', exist_ok=True)
now = int(time.time())
samples = [{'t': now - 10 * (300 - i), 'offset': 1e-5 * (i % 7), 'stratum': 2, 'sources': {}} for i in range(300)]
with gzip.open('/var/lib/chrony/ntp-gui/history.json.gz', 'wt') as h:
    json.dump(samples, h)
" >/dev/null 2>&1
docker run -d --name "${PREFIX}-k" -p 18090:8080 -v "${PREFIX}-hist:/var/lib/chrony" \
  -e NTP_PORT=10134 -e NTP_POOLS="" -e NTP_SERVERS="" "$IMAGE" >/dev/null
wait_for_health http://127.0.0.1:18090/healthz 90 || true
COUNT=$(curl -s --max-time 10 'http://127.0.0.1:18090/api/history?range=0&points=3000' \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['samples']))" 2>/dev/null)
if [[ "$COUNT" =~ ^[0-9]+$ ]] && (( COUNT >= 300 )); then ok "Alter Verlauf ist da ($COUNT Punkte)"; else bad "Alter Verlauf fehlt (${COUNT:-?} Punkte)"; fi
FILES=$(docker exec "${PREFIX}-k" ls /var/lib/chrony/ntp-gui)
contains "Alte Datei als .migrated aufbewahrt" "$FILES" "history.json.gz.migrated"
contains "SQLite-Datenbank angelegt" "$FILES" "ntp-gui.db"
docker rm -f "${PREFIX}-k" >/dev/null 2>&1

echo
echo "13) Sauberes Stoppen"
docker stop -t 15 "${PREFIX}-c" >/dev/null
check "Exit-Code bei SIGTERM" 0 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-c")"
docker exec "${PREFIX}-a" pkill -x chronyd >/dev/null 2>&1
sleep 5
check "Exit-Code, wenn ein Dienst stirbt" 1 "$(docker inspect -f '{{.State.ExitCode}}' "${PREFIX}-a")"

echo
echo "------------------------------------------------------------"
printf 'Bestanden: %d   Fehlgeschlagen: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
