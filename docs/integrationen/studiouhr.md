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
  nur Uhrzeit, Ampel, Genauigkeit, die Art der Quelle (GPS, PTP, NTP), die Zeitzone des Servers
  (für Countdowns) und die Anzeigewerte und Titel der Profile. Namen und Adressen der Quellen, Einstellungen und alle anderen Seiten bleiben geschützt.
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

Fest eingebaute Profile: `studio`, `tile`, `banner`, `kitchen`, `workshop`, `night` und `nerd`,
z. B. `/clock?p=tile`.

## OBS Studio

1. **Quellen → + → Browser**.
2. **URL:** der kopierte Link, z. B. `http://zeitserver.lan:8080/clock?p=tile&bg=transparent`.
3. **Breite und Höhe:** so groß, wie die Uhr im Bild stehen soll, z. B. 480 × 270 für eine
   Kachel oder 1920 × 200 für ein Banner. Die Uhr richtet sich nach der Fläche, nicht nach dem
   Fenster.
4. „Benutzerdefiniertes CSS“ leer lassen. Mit `bg=transparent` ist der Hintergrund schon durchsichtig.
5. „Quelle herunterfahren, wenn nicht sichtbar“ aus lassen: Sonst gleicht sich die Uhr nach jedem
   Szenenwechsel neu ab.

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
