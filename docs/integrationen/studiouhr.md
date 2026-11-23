# Studiouhr: /clock als Browserquelle und im Kiosk

Die Vollbild-Uhr unter `/clock` läuft in jedem Browser, auch als Browserquelle in OBS, vMix oder
CasparCG und im Chromium-Kiosk auf einem Raspberry Pi. Sie gleicht sich selbst mit dem Server ab
und zeigt immer, wie weit du ihr trauen kannst. Mehrere Bildschirme zeigen dasselbe, ohne dass sie
miteinander reden müssen.

Den Link stellst du am einfachsten im Dashboard zusammen: **Uhr & Hardware → Anzeigen**. Dort gibt
es das Formular, „Link kopieren“, eine Vorschau in fester Größe und die Profile.

## Anmeldung: Profil-Link oder „ohne Anmeldung“

Browserquellen haben meist kein Passwortfeld. Zwei Wege:

- **Uhr ohne Anmeldung** (Einstellung `clock_public`, Standard aus). Einschalten unter
  **Uhr & Hardware → Anzeigen → Uhr ohne Anmeldung** oder per `CLOCK_PUBLIC=true`. Öffentlich werden
  nur Uhrzeit, Ampel, Genauigkeit, die Art der Quelle (GPS, PTP, NTP), der Zustand von PTP als fester Wert,
  ein Holdover mit Dauer, die Zeitzone des Servers
  (für Countdowns), der Zustand des On-Air-Signals (nur `off`, `on_air` oder `rec`) und die Anzeigewerte und Titel der Profile. Namen und Adressen der Quellen, Einstellungen und alle anderen Seiten bleiben geschützt.
  Nicht einschalten, wenn das Dashboard aus dem Internet erreichbar ist.
- **Cookie bzw. Anmeldung in der Quelle:** OBS und vMix speichern die Anmeldung, wenn du die Seite
  einmal über „Interagieren“ öffnest und dich anmeldest.

Einbetten in eine fremde Seite (iframe) geht bewusst nicht: Die Uhr sendet `frame-ancestors 'none'`.
Browserquellen laden die Adresse direkt, dafür braucht es kein iframe.

## Gute Grundeinstellung für Studio und Multiviewer

```
http://zeitserver.lan:8080/clock?layout=tile&bg=transparent&design=digital&face=seg&lock=1
```

| Parameter | Wirkung |
|---|---|
| `layout=tile` | keine Kopfzeile, kein Band, kein Mauszeiger, die Zeit so groß wie möglich |
| `bg=transparent` | durchsichtiger Hintergrund zum Keyen (OBS, vMix); `bg=black` für reines Schwarz |
| `safe=5` | Sicherheitsrand in Prozent (Title-Safe, Overscan), in der Kachel Standard 5 |
| `lock=1` | keine Tastenkürzel, Design, Ton und Anpassen ausgeblendet (Vollbild, Hell/Dunkel, Rotlicht und „Mein Gerät“ bleiben) |
| `lead=40` | Anzeige 40 ms vorlaufen lassen, wenn der Bildschirm das Bild verzögert |
| `p=regie` | ein im Dashboard gespeichertes Profil laden (Parameter in der Adresse gehen vor) |
| `fun=0` | keine Spielereien: Knöpfe „Timer“ (Eieruhr, Pomodoro), „Nacht“ und „Spiel“ fehlen, ebenso Zeitzeichen, Mondphase, Nerd-Zeile, Fortschrittsbalken und Ostereier (in `studio`, `tile` und `banner` gesetzt; im Kiosk, mit `lock=1` und in OBS gilt dasselbe) |
| `eggs=0` | keine Ostereier und kein Konfetti (13:37, Neujahr, Schaltsekunden-Tag, Zeitumstellung, Konami-Code), Timer und Spiel bleiben. Ohne Ostereier – also auch mit `fun=0`, in `studio`, `tile`, `banner`, im Kiosk, mit `lock=1`, in OBS, auf E-Ink sowie in den Layouts Kachel und Streifen – fehlt auch die Schaltsekunden-Zeile über der Uhr („Heute Nacht gibt es eine Schaltsekunde …“); die Ankündigung im Band bleibt |

Fest eingebaute Profile: `studio`, `tile`, `banner`, `kitchen`, `workshop`, `night` und `nerd`,
z. B. `/clock?p=tile`.

In der Kachel fehlen Kopfzeile und Band. Dafür steht dort:

- der **Titel des Profils** oben links (bei `p=regie` der Titel, den du im Dashboard vergeben hast),
- der **Zustand als Symbol** oben rechts: ✓ abgeglichen, ○ frei laufend, ! unsicher, – nicht abgeglichen; läuft
  die Serveruhr im Holdover, steht daneben ein „H“ im gestrichelten Kreis,
- ein **Countdown** (`until=20:15`) unter der Zeit mit dem Symbol seiner Stufe, mit `cd=main` als Hauptanzeige.

## Statuszeile: Quelle, PTP und Holdover

Das Band unten zeigt, wie es dem Server geht, immer als Symbol mit Text:

| Anzeige | Bedeutung |
|---|---|
| „synchron · GPS + PPS“ | Ampel und Art der Quelle (GPS, PTP, NTP) |
| „PTP eingerastet“ | der Server folgt einem PTP-Grandmaster |
| „PTP Grandmaster“ | der Server ist selbst Grandmaster |
| „PTP sucht“, „PTP passiv“ | noch kein Abgleich bzw. ein anderer Port ist aktiv |
| „PTP gestört“, „PTP antwortet nicht“ | Port im Fehlerzustand bzw. der PTP-Dienst läuft nicht |
| „Holdover seit 12 min“ | die Serveruhr hat gerade keine Referenz und läuft mit der zuletzt gelernten Frequenz weiter |
| „Server ± 0,4 ms · Abgleich ± 2 ms“ | Genauigkeit der Serveruhr und der Messung dieser Seite |

Ist PTP ausgeschaltet, steht dazu nichts da. `show=` steuert die Zeile: Fehlt `status` in der Liste
(z. B. `show=time,seconds,date`), verschwinden die Marken für PTP und Holdover und die Zustandszeile
unter der Uhr. Öffentlich (ohne Anmeldung) nennt die Uhr nur Arten und Zustände – nie Namen oder
Adressen von Quellen, keine Grandmaster-Kennung und keine Netzwerkschnittstelle.

## Prüfbild: Bildverzögerung einmessen

Fernseher und Bildprozessoren zeigen das Bild oft 20 bis 150 ms zu spät. Mit `lead=` läuft die
Anzeige so viele Millisekunden vor. Den Wert misst du mit dem Prüfbild ein:

```
http://zeitserver.lan:8080/clock?test=sync
```

| Parameter | Wirkung |
|---|---|
| `test=sync` | Prüfbild: Eine Fläche wechselt genau zur vollen Sekunde zwischen hell und dunkel, dazu auf Wunsch ein Klick |
| `lead=40` | Startwert für den Vorlauf in ms (0 bis 200) |

1. Öffne die Adresse auf dem Bildschirm, den du einmessen willst, und schalte **Ton-Klick** ein. Der
   Klick fällt auf die wahre Sekunde, die Fläche läuft um den Vorlauf voraus. Zeigt der Bildschirm
   sonst einen Link oder ein Profil, häng `test=sync` an genau diese Adresse an
   (`/clock?p=regie&test=sync`). Hast du die Uhr über das Panel „Anpassen“ eingerichtet, reicht
   `/clock?test=sync`: Der gemerkte Stand samt Vorlauf bleibt die Grundlage.
2. Siehst du den Wechsel nach dem Klick, erhöhe den Vorlauf mit **→** oder **↑** (je 10 ms), sonst
   senke ihn mit **←** oder **↓**, bis beides zusammenfällt. Genauer geht es mit einer Kamera, die
   Bildschirm und Lautsprecher zusammen aufnimmt.
3. **Esc** beendet das Prüfbild und schreibt den Wert als `lead=` in die Adresse. Trag ihn in deinen
   Link oder dein Profil ein. Mit einem Profil in der Adresse steht auch ein eingemessener Wert 0
   ausdrücklich als `lead=0` da, sonst gälte wieder der Vorlauf des Profils. Dasselbe gilt, wenn die
   Adresse außer `lead=` nichts zur Anzeige nennt: `lead=0` bleibt stehen, sonst gälte der gemerkte
   Stand mit seinem Vorlauf. Gilt der gemerkte Stand aus dem Panel „Anpassen“, wird der Wert dort
   gemerkt und die Adresse bleibt `/clock`.

Wichtig:

- Die Fläche wechselt einmal je Sekunde, nie schneller. Trotzdem: **nicht ins Sendebild und nicht vor
  Publikum zeigen.** Der Warnhinweis steht die ganze Zeit über der Fläche.
- Das Prüfbild startet nur, wenn `test=sync` ausdrücklich in der Adresse steht. In einem Profil
  wird der Wert nicht gespeichert, das Panel „Anpassen“ merkt ihn sich nicht.
- Wünscht dein System weniger Bewegung (`prefers-reduced-motion`), startet es nicht; du siehst dann
  nur einen Hinweis. Auf E-Ink gibt es kein Prüfbild.
- Solange das Prüfbild die Uhr verdeckt, ruhen ihre Tastenkürzel (Stoppuhr, Design, Layout, Größe).
  Es bleiben **F** (Vollbild), **?** (Hilfe), die Pfeiltasten und **Esc**.
- Mit `lock=1` lässt sich der Vorlauf im Prüfbild nicht stellen. Ändere dann `lead=` im Link.
- Bluetooth-Lautsprecher verzögern den Klick um 100 bis 300 ms. Miss mit Kabel oder dem eingebauten
  Lautsprecher.

## Timecode-Anzeige

```
http://zeitserver.lan:8080/clock?design=tc&fps=25&layout=tile&bg=black
```

| Parameter | Wirkung |
|---|---|
| `design=tc` | Tageszeit des Servers als `HH:MM:SS` mit Feinstelle, in der Zeitzone des Servers |
| `fps=24\|25\|30\|50\|60\|29.97\|59.94` | Bildrate, Standard 25; 29.97 und 59.94 zählen Drop-Frame (`;` vor den Frames) |
| `sub=tenths\|frames\|off` | Feinstelle: Zehntel (Standard), Frames nur auf ausdrücklichen Wunsch, oder keine |
| `maxerr=100` | über dieser Fehlerschranke (ms) verschwindet die Feinstelle |

Über der Zeit steht immer „Anzeige-Timecode – nicht genlocked“. Die Anzeige hat kein
Hausreferenzsignal (Black Burst, Tri-Level), und der Monitor zeichnet in seinem eigenen Takt: Ein
60-Hz-Monitor zeigt 25 oder 50 Bilder pro Sekunde nicht gleichmäßig. Rechne mit ± 1 bis 2 Frames.
Die Feinstelle wird grau, wenn die Fehlerschranke größer ist als ein halbes Frame (bei Zehnteln
50 ms) oder der Browser seine Zeitgeber grob rundet; der Grund steht unter der Zeit. Ein
Drop-Frame-Tag ist 86,4 ms kürzer als ein Kalendertag: Kurz vor Mitternacht bleibt die Anzeige so
lange auf dem letzten Frame stehen. Für Schnitt, Aufzeichnung und Synchronisation gehört echter
Timecode aus einem LTC- oder VITC-Generator ins Signal.

## Weltzeit

```
http://zeitserver.lan:8080/clock?layout=world&tz=Europe/London,America/New_York,Asia/Tokyo&tzl=LON,NYC,TYO&kiosk=1
```

| Parameter | Wirkung |
|---|---|
| `tz=Europe/London,Asia/Tokyo` | bis zu sechs Zeitzonen, mit Komma getrennt oder als `tz=…&tz=…`; eine einzelne Zone steht wie bisher als zweite Zeitzone unter der Uhr |
| `tzl=LON,TYO` | Kurznamen in derselben Reihenfolge, je bis 16 Zeichen (Buchstaben, Ziffern, Leerzeichen, Punkt, Bindestrich); leer: Ortsname der Zone. Nennt die Adresse andere Zonen als das Profil, aber keine Kurznamen, gelten die Kurznamen des Profils nicht weiter |
| `layout=world` | die Zonen als Raster und Hauptinhalt: drei Spalten auf 16:9, eine Zeile je Zone im Hochformat, alle nebeneinander ab 3:1 |

Je Zone zeigt die Uhr die Uhrzeit, die Abweichung zur großen Zeit („+6 h“, „+5:30 h“), einen
Tageswechsel („+1 Tag“, „−1 Tag“) und Tag oder Nacht als Symbol. Tag heißt 6 bis 18 Uhr in der
Zone: Einen Standort kennt die Uhr nicht, den Sonnenstand rechnet sie nicht. Die Abweichung wird für
jeden Zeitpunkt neu bestimmt und stimmt darum auch in den Wochen, in denen Europa und Nordamerika
nicht gleichzeitig umgestellt haben. Ohne `layout=world` steht ab zwei Zonen eine Leiste unter der
Uhr (im Banner in der rechten Spalte). Zonen, die nicht auf die Fläche passen, blendet die Uhr aus
und nennt ihre Zahl („+2“); im Streifen und in der Kachel fehlt die Leiste ganz. Ist ein Name
unbekannt oder doppelt, gilt die ganze Liste nicht; Leerzeichen nach dem Komma stören nicht. Mit
`h12=1` stehen auch die Zonen zwölfstündig mit AM/PM.

Die Leiste ist eine Nebenzeile: Sie wächst zwar, wo unter der Uhr Höhe frei ist, bleibt aber klein
gegenüber der großen Zeit. Für Bildwände und große Abstände nimm `layout=world` – dort sind die
Zonen der Hauptinhalt. Passt im Layout `world` keine einzige Zone auf die Fläche oder blendet
`show=` die Weltzeit aus (Liste ohne `tz`), zeigt die Uhr sich im automatischen Layout.

## On Air und REC

Ein roter Rahmen um die ganze Uhr und ein Balken mit „ON AIR“ oder „REC“. Der Zustand steht immer als
Text mit Symbol da, nie nur als Farbe, und nichts blinkt. REC hat einen doppelten Rahmen und ein
eigenes Symbol.

```
http://zeitserver.lan:8080/clock?p=studio&signal=1
```

| Parameter | Wirkung |
|---|---|
| `signal=1` | dieser Bildschirm zeigt das zentrale On-Air/REC-Signal und fragt dafür jede Sekunde ab (sonst alle 5 s) |

Drei Wege, das Signal zu schalten:

- **Taste O** auf der Uhr: „On Air“ nur auf diesem einen Gerät. Nichts wird gesendet, der Balken sagt
  „nur dieses Gerät“. Mit `lock=1` ist die Taste aus. Zeigt der Bildschirm gerade das zentrale Signal,
  wirkt die Taste nicht (ein Hinweis sagt das); ein vorher lokal geschaltetes „On Air“ endet, sobald das
  zentrale Signal übernimmt.
- **Dashboard:** **Uhr & Hardware → Anzeigen → On-Air-Signal**. Knöpfe „ON AIR“, „REC“ und „Aus“,
  dazu auf Wunsch eine Ablaufzeit, nach der sich das Signal selbst ausschaltet.
- **API:** `POST /api/v1/clock/signal`, siehe unten. So schaltest du es vom Stream Deck oder
  Bildmischer aus.

Das zentrale Signal zeigen nur Bildschirme mit `signal=1` im Link oder Profil. Alle anderen bleiben,
wie sie sind, und fragen weiter alle 5 s ab. Das zentrale Signal geht vor dem lokalen.

Ehrlich gesagt: Das ist eine **gespiegelte Anzeige** mit bis zu etwa 1 s Verzögerung, **kein Tally**
am Bildmischer. Antwortet der Server länger als 10 s nicht, bleibt der letzte Zustand stehen; der
Rahmen ist dann gestrichelt und der Balken sagt „Stand ungewiss“. Der Zustand steht nur im
Arbeitsspeicher des Servers: Nach einem Neustart ist er aus, in der Sicherung steht er nicht.

### Signal per API setzen

Lege im Dashboard unter **Einstellungen → Dashboard & Zugang → API-Schlüssel** einen Schlüssel mit
dem Recht **nur On-Air-Signal der Uhr** an. Dieser Schlüssel darf nur das: Er liest nichts und ändert
sonst nichts. Gerät er in falsche Hände, kann damit niemand deine Zeitversorgung verstellen.

```bash
TOKEN=ntpg_…   # Platzhalter: dein Schlüssel mit dem Recht „nur On-Air-Signal der Uhr“

# ON AIR, bleibt bis zum Ausschalten
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"state": "on_air"}' http://zeitserver.lan:8080/api/v1/clock/signal

# REC, schaltet sich nach zwei Stunden selbst aus
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"state": "rec", "ttl": 7200}' http://zeitserver.lan:8080/api/v1/clock/signal

# Aus
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"state": "off"}' http://zeitserver.lan:8080/api/v1/clock/signal
```

| Feld | Werte |
|---|---|
| `state` | `on_air`, `rec` oder `off` – nichts anderes, kein eigener Text |
| `ttl` | optional: Sekunden von 1 bis 86400, danach steht das Signal wieder auf `off` |

Die Antwort nennt `signal`, `signal_rev` und `expires_in`. Dieselben Felder `signal` und `signal_rev`
stehen in `/api/v1/time`; `signal_rev` ändert sich mit jedem Wechsel und mit jeder neu gesetzten Ablaufzeit.

| Antwort | Bedeutung |
|---|---|
| `200` | gesetzt |
| `400` | Wert außerhalb der Liste, unbekanntes Feld oder `ttl` außerhalb von 1 bis 86400 |
| `401` | kein oder ein ungültiger Schlüssel |
| `403` | der Schlüssel hat nicht das Recht `clock` (oder `admin`), oder `WEB_READONLY` ist gesetzt |
| `429` | mehr als 10 Anfragen je Sekunde mit diesem Schlüssel; nach 1 s noch einmal versuchen |

Im Ereignisprotokoll steht jeder Wechsel mit der Kennung des Schlüssels, ohne seinen Namen und ohne
die Adresse des Aufrufers. Das gilt auch, wenn bei gleichem Zustand nur die Ablaufzeit gesetzt,
geändert oder aufgehoben wird; geht das Signal nach der Ablaufzeit aus, nennt der Eintrag, wer sie
gesetzt hat. Die ersten zehn Wechsel stehen sofort da. Schaltet jemand danach weiter in schneller
Folge, kommt höchstens ein Eintrag je Minute dazu: der letzte Stand mit der Zahl der übersprungenen
Wechsel und den Kennungen der beteiligten Schlüssel. Vom Signal bleiben die neuesten 2000 Einträge;
andere Ereignisse verdrängt es nicht.

## OBS Studio

1. **Quellen → + → Browser**.
2. **URL:** der kopierte Link, z. B. `http://zeitserver.lan:8080/clock?p=tile&bg=transparent`.
3. **Breite und Höhe:** so groß, wie die Uhr im Bild stehen soll, z. B. 480 × 270 für eine
   Kachel oder 1920 × 200 für ein Banner. Die Uhr richtet sich nach der Fläche, nicht nach dem
   Fenster.
4. „Benutzerdefiniertes CSS“ leer lassen. Mit `bg=transparent` ist der Hintergrund schon durchsichtig.
5. „Quelle herunterfahren, wenn nicht sichtbar“ aus lassen: Sonst gleicht sich die Uhr nach jedem
   Szenenwechsel neu ab.

In einer OBS-Browserquelle erkennt die Uhr OBS selbst: Kopfzeile, Panels und die Knöpfe am Countdown (Start, +1 min,
Zurücksetzen) fehlen dort immer, auch ohne `lock=1`. Ein Timer (`timer=5m`) startet über „Interagieren“ mit der
Leertaste.

## vMix

1. **Add Input → Web Browser**.
2. **URL:** der kopierte Link, **Width/Height** wie bei OBS (z. B. 1920 × 1080 für Vollbild oder
   480 × 270 für eine Kachel).
3. Für einen durchsichtigen Hintergrund `bg=transparent` in den Link schreiben; vMix keyt den
   Alphakanal der Browserquelle direkt.

## CasparCG

CasparCG zeigt Webseiten als HTML-Producer:

```
PLAY 1-20 [HTML] "http://zeitserver.lan:8080/clock?p=tile&bg=transparent"
```

Die Größe ist die des Kanals (z. B. 1920 × 1080). Für eine kleine Uhr im Bild nimm `layout=tile`
und verkleinere den Layer mit `MIXER 1-20 FILL`. Ältere CasparCG-Versionen bringen einen älteren
Chromium mit: Dann gelten die einfacheren Größenregeln ohne Container-Einheiten, die Uhr bleibt aber
lesbar.

## Bitfocus Companion (Stream Deck, Bildmischer)

Companion bindet die Uhr über sein allgemeines HTTP-Modul an, ohne eigenes Protokoll auf dem
Zeitserver:

1. In Companion **Connections → Add connection → Generic: HTTP Requests** anlegen. Als **Base URL**
   die Adresse des Zeitservers eintragen, z. B. `http://zeitserver.lan:8080`.
2. Im Dashboard unter **Einstellungen → Dashboard & Zugang → API-Schlüssel** einen Schlüssel mit
   dem Recht **nur lesen** anlegen und in der
   Verbindung als Kopfzeile hinterlegen: `Authorization: Bearer ntpg_…`. Mit „Uhr ohne Anmeldung“
   antwortet `/api/v1/time` auch ohne Schlüssel. Den Schlüssel nie in die Adresse schreiben.
3. Eine Taste oder einen Trigger mit der Aktion **GET** auf `/api/v1/time` anlegen und die Antwort
   als JSON in eine Variable legen (Option „JSON Response Data Variable“). Für die Abfrage reicht
   ein Intervall von 5 s.

Aus der Antwort kannst du Tasten einfärben oder beschriften:

| Feld | Werte | Idee für die Taste |
|---|---|---|
| `synchronised` | `true`, `false` | grün bzw. rot |
| `level` | `good`, `warn`, `crit` | Ampelfarbe |
| `source_kind` | `GPS`, `GPS + PPS`, `PTP`, `NTP` … | Beschriftung |
| `ptp_state` | `off`, `down`, `master`, `locked`, `acquiring`, `passive`, `fault`, `unknown` | Warnfarbe bei `fault` und `down` |
| `holdover` | `true`, `false`, `null` (unbekannt) | Warnfarbe, solange die Serveruhr ohne Referenz läuft |
| `holdover_seconds` | Sekunden oder `null` | Dauer in der Beschriftung |
| `accuracy` | Sekunden | Genauigkeit der Serveruhr |
| `signal` | `off`, `on_air`, `rec` | Taste rot, solange das On-Air-Signal an ist |

Ein Ausdruck in Companion dafür: `jsonpath($(custom:zeit), '$.ptp_state')`.

### On Air per Taste schalten

Für das On-Air-Signal (siehe „On Air und REC“) legst du eine **zweite Verbindung** mit einem eigenen
Schlüssel an – so braucht die Taste kein Leserecht und der Lese-Schlüssel kein Schreibrecht:

1. Im Dashboard einen API-Schlüssel mit dem Recht **nur On-Air-Signal der Uhr** anlegen.
2. In Companion eine weitere Verbindung **Generic: HTTP Requests** mit derselben Base URL anlegen.
3. Eine Taste mit der Aktion **POST** anlegen:
   - **URI:** `/api/v1/clock/signal`
   - **Body:** `{"state": "on_air"}` (für die Aus-Taste `{"state": "off"}`, für Aufnahme `{"state": "rec"}`)
   - **Header:** `{"Authorization": "Bearer ntpg_…", "Content-Type": "application/json"}`
     (`ntpg_…` ist ein Platzhalter für deinen Schlüssel)
4. Am Bildmischer löst du dieselbe Aktion über einen Trigger aus, etwa wenn dein Programmbus auf
   Sendung geht. ntp-gui selbst spricht kein ATEM-, TSL- oder GPIO-Protokoll; das übernimmt Companion.

Die Bildschirme mit `signal=1` zeigen den Wechsel nach höchstens etwa 1 s.

Die Namen der Felder in Companion hängen von der Version des Moduls ab; es genügt jedes Modul, das
eine Adresse per GET oder POST aufruft und JSON lesen kann. Was die Bildschirme sonst zeigen, stellst
du nicht über Companion um, sondern über ein Profil (siehe „Viele Bildschirme zentral umstellen“).

## Raspberry Pi als Wanduhr (Chromium-Kiosk)

```
chromium-browser --kiosk --noerrdialogs --disable-session-crashed-bubble \
  --disable-infobars --check-for-update-interval=31536000 \
  "http://zeitserver.lan:8080/clock?p=studio"
```

- Mit `kiosk=1` (im Profil `studio` schon gesetzt) verschwinden Kopfzeile und Mauszeiger.
- Gegen Einbrennen verschiebt `shift=1` (fein) oder `shift=2` die Anzeige alle 2 min um wenige Pixel.
- Fällt der Server aus, läuft die Uhr frei weiter und sagt das unten in der Zustandszeile.

## Viele Bildschirme zentral umstellen

1. Im Dashboard unter **Anzeigen** die Uhr zusammenstellen, z. B. Countdown bis 20:15 mit
   Beschriftung „bis ON AIR“.
2. **Als Profil speichern** unter einem Namen wie `regie`.
3. Alle Bildschirme rufen `/clock?p=regie` auf.

Speicherst du das Profil neu, laden die Bildschirme es beim nächsten Abgleich (spätestens nach 5 s)
und zeigen den neuen Stand. Der Countdown rechnet auf der abgeglichenen Serverzeit, alle Bildschirme
zählen also gleich. Profile kommen mit in die Sicherung.
