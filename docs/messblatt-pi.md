# Messblatt: Abnahmen auf dem Raspberry Pi 4

Einige Zusagen lassen sich nur auf echter Hardware prüfen. Die CI misst sie nicht, der Rundgang
(`tests/ui/`) auch nicht: Er läuft auf einem schnellen Rechner mit erfundenem `chronyc`. Dieses
Blatt beschreibt, wie du die vier Werte auf einem Pi 4 misst und wo du sie einträgst.

Trag nur Werte ein, die du selbst gemessen hast. Ein leeres Feld heißt „noch nicht gemessen“. Bei
„bestanden?“ schreibst du **ja** oder **nein**. Eine Schätzung oder ein Wert von einem anderen Gerät
gehört nicht in die Tabelle.

| Zusage | Grenze | Abschnitt |
|---|---|---|
| Studiouhr im Chromium-Kiosk, Design Studio | < 10 % CPU | [1](#1-studiouhr-im-chromium-kiosk-cpu) |
| Studiouhr im Chromium-Kiosk, Design Digital | < 3 % CPU | [1](#1-studiouhr-im-chromium-kiosk-cpu) |
| Ton auf der Sekunde im Kiosk | ±5 ms um die volle Sekunde (ohne Laufzeit des Lautsprechers) | [2](#2-ton-auf-der-sekunde) |
| Sicherung mit 30 Tagen Verlauf | < 10 s, andere Anfragen laufen weiter | [3](#3-sicherung-mit-30-tagen-verlauf) |
| Übersicht | < 500 ms Serverzeit | [4](#4-übersicht-serverzeit) |

## Angaben zum Aufbau

Einmal je Messreihe ausfüllen. Alle Befehle laufen auf dem Pi, wenn nicht anders angegeben.

| Feld | Befehl | Eintrag |
|---|---|---|
| Datum der Messung | – | |
| ntp-gui-Version | `curl -s http://127.0.0.1:8080/api/v1/status \| grep -o '"version": *"[^"]*"'` (mit Passwort: Schlüssel wie in Abschnitt 4) | |
| Modell | `tr -d '\0' < /proc/device-tree/model` | |
| Arbeitsspeicher | `free -h \| awk '/^Mem/ {print $2}'` | |
| Betriebssystem | `. /etc/os-release && echo "$PRETTY_NAME"` | |
| Kernel | `uname -r` | |
| Chromium-Version | `chromium --version \|\| chromium-browser --version` | |
| Grafik (Wayland/X11) | `echo "$XDG_SESSION_TYPE"` | |
| Auflösung des Bildschirms | `wlr-randr \|\| xrandr --current \| head -3` | |
| Kühlung / Gehäuse | – | |
| Temperatur vor der Messung | `cat /sys/class/thermal/thermal_zone0/temp` (Milligrad) | |
| Drosselung | `vcgencmd get_throttled` (0x0 = keine) | |
| Läuft ntp-gui auf demselben Pi? | – | |

Vor jeder CPU-Messung: Pi mindestens 10 min laufen lassen, keine anderen Fenster offen, kein
Update im Hintergrund (`pgrep -a apt; pgrep -a unattended`).

## 1. Studiouhr im Chromium-Kiosk (CPU)

**Grenze:** Design Studio < 10 %, Design Digital < 3 %. Gemeint ist die Summe aller
Chromium-Prozesse in Prozent **eines** Kerns (wie `top` sie zeigt), gemittelt über 60 s,
1080p-Bildschirm, Ruhebetrieb (keine Bedienung, kein Countdown, kein Prüfbild).

Kiosk starten (je Design einmal, vorher alle Chromium-Fenster schließen):

```sh
# Design Studio (Profil studio: kiosk=1, fun=0)
chromium --kiosk --noerrdialogs --disable-session-crashed-bubble --disable-infobars \
  --check-for-update-interval=31536000 "http://zeitserver.lan:8080/clock?p=studio" &

# Design Digital
chromium --kiosk --noerrdialogs --disable-session-crashed-bubble --disable-infobars \
  --check-for-update-interval=31536000 "http://zeitserver.lan:8080/clock?design=digital&kiosk=1" &
```

Heißt das Programm bei dir `chromium-browser`, nimm diesen Namen. Ersetze `zeitserver.lan:8080`
durch die Adresse deines Servers.

Nach dem Start 2 min warten, dann per SSH auf dem Pi messen (der Kiosk bleibt ungestört):

```sh
# CPU-Zeit aller Chromium-Prozesse über 60 s, in Prozent eines Kerns
ticks() { awk '{ sub(/^[0-9]+ \([^)]*\) /, ""); s += $12 + $13 } END { print s + 0 }' \
  $(pgrep -f 'chrom(e|ium)' | sed 's|.*|/proc/&/stat|') 2>/dev/null; }
a=$(ticks); sleep 60; b=$(ticks)
awk -v a="$a" -v b="$b" -v hz="$(getconf CLK_TCK)" 'BEGIN { printf "%.1f %%\n", (b - a) * 100 / (60 * hz) }'
```

Dreimal hintereinander messen. Zur Gegenprobe: `top -b -d 60 -n 2 | grep -i chrom` (zweiter Block).

| Design | Lauf 1 | Lauf 2 | Lauf 3 | Mittel | Grenze | bestanden? |
|---|---|---|---|---|---|---|
| Studio (`?p=studio`) | | | | | < 10 % | |
| Digital (`?design=digital&kiosk=1`) | | | | | < 3 % | |

Bemerkungen (z. B. Bildschirm, Hardwarebeschleunigung laut `chrome://gpu`):

## 2. Ton auf der Sekunde

**Grenze:** Der Klick beginnt innerhalb von ±5 ms um die volle Sekunde. Die Laufzeit des
Lautsprechers (Bluetooth, HDMI-Fernseher) zählt nicht mit; miss deshalb über Kopfhörer- bzw.
Analogausgang oder zieh eine bekannte Laufzeit ab.

Du brauchst eine Bezugssekunde, die nicht vom Browser kommt. Am einfachsten ist die PPS-LED des
GPS-Empfängers am Zeitserver (sie blinkt zur vollen Sekunde) oder ein Funkuhr-/GPS-Sekundenton.

1. Kiosk mit `http://zeitserver.lan:8080/clock?p=studio` (oder dem Design deiner Wahl) starten,
   einmal tippen bzw. klicken und im Panel **Ton** den Sekundenton einschalten (Browser spielen
   Ton erst nach einer Bedienung).
2. Prüfen, dass die Uhr synchron ist: Zustandszeile ohne „frei“ bzw. „ungewiss“.
3. Mit einem Handy oder einer Kamera bei mindestens 120 Bildern/s (Zeitlupe) die PPS-LED aufnehmen
   und den Ton gleichzeitig aufzeichnen. Lautsprecher dicht an das Mikrofon, damit die Schalllaufzeit
   (≈ 3 ms je Meter) klein bleibt; den Abstand notieren.
4. Am Rechner Tonspur und Bild Bild für Bild ansehen (z. B. Audacity für den Ton, ein Videoprogramm
   mit Einzelbildschritt für die LED) und je Sekunde den Abstand zwischen Aufleuchten der LED und
   Beginn des Klicks bestimmen. Bei 120 Bildern/s ist die Auflösung etwa 8 ms; für die Grenze von
   ±5 ms also 240 Bilder/s nehmen oder über viele Sekunden mitteln.
5. Mindestens 20 Sekunden auswerten.

| Feld | Eintrag |
|---|---|
| Bezug (PPS-LED, Funkuhr, …) | |
| Aufnahmegerät, Bilder/s | |
| Abstand Lautsprecher–Mikrofon (m) | |
| Ausgang (Klinke, HDMI, USB) | |
| Ausgewertete Sekunden | |
| Mittelwert Klick minus Bezug (ms) | |
| kleinster / größter Wert (ms) | |
| Grenze | ±5 ms |
| bestanden? | |

## 3. Sicherung mit 30 Tagen Verlauf

**Grenze:** Eine neue Sicherung mit 30 Tagen Verlauf ist nach weniger als 10 s fertig
heruntergeladen. Andere Anfragen laufen währenddessen weiter.

Voraussetzung: Der Server läuft seit mindestens 30 Tagen mit `HISTORY_DAYS` ≥ 30 (Standard 30), und
im Dashboard zeigt **Verlauf → 30 Tage** Daten über den ganzen Zeitraum. Größe der Datenbank:

```sh
docker exec ntp-gui ls -l /var/lib/chrony/ntp-gui/ntp-gui.db
```

Ist ein Passwort gesetzt, braucht die Sicherung einen API-Schlüssel mit dem Recht „lesen und
verwalten“. Leg ihn in den Einstellungen unter **API-Schlüssel** an und widerruf ihn nach der Messung.
Den Schlüssel nur in die Shell geben, nicht in dieses Blatt.

```sh
read -rs KEY   # Schlüssel ntpg_… einfügen, Enter (ohne Passwort: einfach Enter)
BASE=http://127.0.0.1:8080
AUTH=(); [ -n "$KEY" ] && AUTH=(-H "Authorization: Bearer $KEY")

# Gegenprobe im Hintergrund: jede Sekunde /healthz, Antwortzeit in Sekunden
( for i in $(seq 1 30); do curl -s -o /dev/null -w '%{time_total}\n' "$BASE/healthz"; sleep 1; done ) > healthz.txt &

# Sicherung messen (Datei wird verworfen; sie enthält Client-Adressen, nicht weitergeben)
curl -s -o /dev/null "${AUTH[@]}" \
  -w 'HTTP %{http_code}, %{size_download} Bytes, %{time_total} s\n' "$BASE/api/v1/backup"

wait; sort -n healthz.txt | tail -1   # langsamste /healthz-Antwort währenddessen
unset KEY
```

Dreimal messen, zwischen den Läufen 1 min Pause (eine Sicherung gleichzeitig; eine zweite
Anfrage bekommt sonst eine Absage).

| Feld | Lauf 1 | Lauf 2 | Lauf 3 |
|---|---|---|---|
| Größe von `ntp-gui.db` | | | |
| Größe der Sicherung (Bytes) | | | |
| Dauer der Sicherung (s) | | | |
| langsamste `/healthz`-Antwort währenddessen (s) | | | |

| Grenze | bestanden? |
|---|---|
| jede Sicherung < 10 s, `/healthz` immer < 1 s | |

## 4. Übersicht (Serverzeit)

**Grenze:** Die Anfragen, die die Übersicht beim Öffnen stellt, beantwortet der Server zusammen in
weniger als 500 ms. Gemessen wird die Zeit bis zum ersten Byte (`time_starttransfer`) direkt auf dem
Pi über 127.0.0.1, also ohne Netz und ohne Browser. Bedingung wie in Abschnitt 3: 30 Tage Verlauf
vorhanden.

Ist ein Passwort gesetzt, brauchst du einen API-Schlüssel mit dem Recht „nur lesen“ (danach widerrufen):

```sh
read -rs KEY   # Schlüssel ntpg_… einfügen, Enter (ohne Passwort: einfach Enter)
BASE=http://127.0.0.1:8080
AUTH=(); [ -n "$KEY" ] && AUTH=(-H "Authorization: Bearer $KEY")
PATHS="status history?range=3600&points=600 timeline timeline/markers?range=2678400 clients/offsets events?limit=5 setup"
for run in 1 2 3 4 5 6 7 8 9 10; do
  sum=0; max=0
  for p in $PATHS; do
    s=$(curl -s -o /dev/null "${AUTH[@]}" -w '%{time_starttransfer}' "$BASE/api/v1/$p")
    sum=$(awk -v a="$sum" -v b="$s" 'BEGIN { print a + b }')
    max=$(awk -v a="$max" -v b="$s" 'BEGIN { print (b > a) ? b : a }')
  done
  echo "Lauf $run: Summe ${sum} s, langsamste ${max} s"
  sleep 5
done
unset KEY
```

Die Liste entspricht den Abrufen der Übersicht in `app/static/js/app.js`, `pages/overview.js` und
`timeline.js` (Verlauf mit dem Standardzeitraum 1 h). Ändert sich das Frontend, die Liste anpassen.
Die Summe ist strenger als die Wirklichkeit, weil der Browser die Abrufe gleichzeitig stellt.

| Feld | Eintrag |
|---|---|
| Summe, Median der 10 Läufe (ms) | |
| Summe, größter Wert (ms) | |
| langsamster Einzelabruf und sein Pfad | |
| Grenze | Median der Summe < 500 ms |
| bestanden? | |

## Ablage

Ein ausgefülltes Blatt gehört zu genau einem Release. Halte darin keine Adressen, Gerätenamen,
Seriennummern oder Standorte fest, und keine Schlüssel. Fotos und Videos aus Abschnitt 2 bleiben
bei dir.
