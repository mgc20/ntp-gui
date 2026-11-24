#!/usr/bin/env bash
# Rundgang für die CI (Job „Oberfläche“ in .github/workflows/ci.yml) – lokal mit denselben Parametern:
#   tests/ui/ci.sh [Port] [Ausgabeordner]          (Standard 18300 und ${TMPDIR:-/tmp}/ntpgui-ui-ci)
#
# Führt nacheinander die Varianten aus TOUR_CI_VARIANTS aus (Standard: alle aus CI_VARIANTS unten). Jede
# Variante startet über rundgang.sh einen eigenen Testserver mit frischem Datenverzeichnis. Fehlendes
# Playwright ist ein Fehler, kein stilles Überspringen. Je Variante landen im Ausgabeordner:
#   <variante>.json (Ausgabe von tour.js), <variante>.err (Fehlerausgabe), <variante>-server.log und,
#   Bildschirmfotos unter <variante>-fotos/ – nur bei routen, statusband und hilfe; die übrigen Varianten
#   haben keine Fotofunktion und liefern nur JSON und Protokolle.
# Rückgabecode 0, wenn alle Varianten ohne Befund durchliefen, sonst 1.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-18300}"
OUT="${2:-${TMPDIR:-/tmp}/ntpgui-ui-ci}"
# Höchstdauer je Variante in Sekunden (eine hängende Seite soll nicht den ganzen Job aufbrauchen). timeout
# schickt TERM an rundgang.sh samt Testserver; reagiert danach nichts innerhalb von 30 s, folgt KILL (-k).
LIMIT="${TOUR_CI_LIMIT:-900}"

# Variante → Umgebung für tour.js. Die Studiouhr-Prüfungen in Echtzeit (Long Tasks, Bildschleife) und die
# großen Flächenmatrizen der Uhr bleiben lokal: Sie dauern lange und hängen von der Rechenleistung ab.
CI_VARIANTS="routen seiten zeitleiste statusband hilfe korrekturen uhr"
env_for() {
  case "$1" in
    routen) echo "TOUR_ROUTES_ONLY=1 TOUR_SHOTS=$OUT/routen-fotos" ;;   # Assistent, Navigation, Einstellungen, Routen
    hilfe) echo "TOUR_HELP_ONLY=1 TOUR_SHOTS=$OUT/hilfe-fotos" ;;
    zeitleiste) echo "TOUR_TIMELINE_ONLY=1" ;;
    statusband) echo "TOUR_HERO_ONLY=1 TOUR_HERO_SHOTS=$OUT/statusband-fotos" ;;
    seiten) echo "TOUR_PAGES_ONLY=1" ;;
    korrekturen) echo "TOUR_FIXES_ONLY=1" ;;
    uhr) echo "TOUR_CLOCK_BASIC_ONLY=1" ;;   # Designs, Kiosk, E-Ink, Allowlist – ohne Studiouhr-Matrizen
    *) return 1 ;;
  esac
}

mkdir -p "$OUT"
failed=()
for variant in ${TOUR_CI_VARIANTS:-$CI_VARIANTS}; do
  if ! settings="$(env_for "$variant")"; then
    echo "Unbekannte Variante: $variant" >&2
    failed+=("$variant")
    continue
  fi
  for pair in $settings; do
    case "$pair" in TOUR_SHOTS=*|TOUR_HERO_SHOTS=*) mkdir -p "${pair#*=}" ;; esac
  done
  start=$SECONDS
  # shellcheck disable=SC2086 – $settings ist eine Liste NAME=WERT ohne Leerzeichen in den Werten
  env TOUR_REQUIRE_PLAYWRIGHT=1 TOUR_SERVER_LOG="$OUT/$variant-server.log" $settings \
    timeout -k 30 -s TERM "$LIMIT" "$HERE/rundgang.sh" "$PORT" >"$OUT/$variant.json" 2>"$OUT/$variant.err"
  rc=$?
  echo "$variant: Rückgabecode $rc nach $((SECONDS - start)) s"
  if [ "$rc" -ne 0 ]; then
    failed+=("$variant")
    # Befund gleich ins Protokoll, damit er ohne Artefakt lesbar ist.
    head -c 4000 "$OUT/$variant.json"
    tail -n 20 "$OUT/$variant.err"
  fi
done

if [ "${#failed[@]}" -gt 0 ]; then
  echo "Befund in: ${failed[*]} – Einzelheiten unter $OUT" >&2
  exit 1
fi
echo "Rundgang ohne Befund."
