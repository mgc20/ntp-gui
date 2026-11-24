# Zeitwächter-Ping: ntp-gui meldet sich bei deinem eigenen Wächter

Die Benachrichtigungen von ntp-gui laufen im selben Container wie alles andere. Ist der Rechner
aus, der Container weg oder der Strom ausgefallen, kann ntp-gui nichts mehr melden. Der
**Zeitwächter-Ping** schließt diese Lücke: ntp-gui ruft regelmäßig eine Adresse deines eigenen
Wächters auf. Bleibt der Aufruf aus, schlägt der Wächter Alarm.

Passende Wächter: **Uptime Kuma** (Monitor-Typ „Push“) und **Healthchecks** (selbst gehostet oder
healthchecks.io) sowie alles, was dieselbe Form versteht. Der Ping ist **standardmäßig aus**; ohne
eingetragene Adresse baut ntp-gui keine Verbindung auf und fragt auch kein DNS.

## Was gesendet wird

| Zustand | Healthchecks | Uptime Kuma Push | nur Lebenszeichen |
|---|---|---|---|
| gut | `GET <adresse>` | `GET <adresse>?status=up&msg=OK` | `GET <adresse>` |
| kritisch | `GET <adresse>/fail` | `GET <adresse>?status=down&msg=kritisch` | nichts |

- **Kritisch** heißt: Die Übersicht zeigt einen roten Hinweis – z. B. „chronyd antwortet nicht“
  oder ein Pflichtdienst (gpsd, ptp4l) ist ausgefallen. Lässt sich der Zustand nicht ermitteln,
  meldet der Ping ebenfalls „kritisch“.
- Nur eine **GET-Anfrage ohne Inhalt**, User-Agent `ntp-gui` ohne Version. Keine Messwerte, keine
  Namen, keine Kennung der Instanz. Im Datenschutzfilter ist das der Zweck `heartbeat` mit leerer
  Feldliste (`app/egress.py`, `heartbeat_request`).
- Weiterleitungen werden nicht befolgt, nach 5 s ist Schluss, die Antwort wird nur kurz gelesen.
- Das Ziel wird **nach der Namensauflösung** geprüft wie bei den Benachrichtigungen: nie
  Link-local- oder Metadaten-Adressen, Loopback nur mit `OUTBOUND_TARGETS=loopback`, mit
  `OUTBOUND_TARGETS=public` nur öffentliche Ziele.
- Die Adresse enthält den Schlüssel deines Wächters (Push-Token, UUID). Über `http://` geht sie
  darum nur an Adressen im eigenen Netz (`*.lan`, `*.local`, private IP-Adressen …), ins Internet
  nur über `https://`.

## Einrichten

**System → Einstellungen → Dashboard & Zugang**:

| Einstellung | Bedeutung |
|---|---|
| **Zeitwächter-Ping (Adresse)** | Adresse des Wächters, leer = aus |
| **Zeitwächter-Ping: Intervall** (Erweitert) | 30 bis 3600 s, Standard 60 s |
| **Zeitwächter-Ping: Art** (Erweitert) | Automatisch (Standard), Healthchecks, Uptime Kuma Push, nur Lebenszeichen |

„Automatisch“ erkennt Uptime-Kuma-Adressen am Pfad `/api/push/<token>`; jede andere Adresse wird
wie Healthchecks behandelt (`/fail` bei kritischem Zustand). Kennt dein Wächter nur das Ausbleiben
eines Aufrufs, wähle **nur Lebenszeichen**.

Zustand, letztes Ergebnis und den Knopf **Jetzt senden** (sofort ein Ping mit dem echten Zustand,
höchstens alle 10 s) findest du auf der Seite **Benachrichtigungen**, eine Kurzfassung auch in den
Einstellungen. Scheitert der Ping dreimal in Folge, steht ein Ereignis der Art „Zeitwächter-Ping“
im Protokoll (und geht an deine Benachrichtigungskanäle, wenn sie diese Art zulassen); kommt er
wieder an, folgt „wieder erreichbar“.

### Uptime Kuma

1. **Neuer Monitor → Monitor-Typ „Push“.** Uptime Kuma zeigt eine Push-URL wie
   `http://kuma.lan:3001/api/push/AbCdEf1234?status=up&msg=OK&ping=`.
2. **Heartbeat Interval** etwas länger als das Intervall in ntp-gui, z. B. 90 s bei 60 s;
   **Retries** 1 oder 2.
3. Die Push-URL in ntp-gui eintragen – mit oder ohne den Teil ab `?`. ntp-gui setzt `status`
   und `msg` selbst und lässt `ping` weg.
4. **Jetzt senden** auf der Seite Benachrichtigungen; der Monitor wird grün.

Läuft Uptime Kuma auf demselben Rechner mit `network_mode: host`, ist die Adresse
`http://127.0.0.1:3001/…` – dafür braucht es `OUTBOUND_TARGETS=loopback` in der Compose-Datei.
Ein eigener Kuma-Container im selben Docker-Netz (`http://uptime-kuma:3001/…`) geht ohne.

### Healthchecks

1. **Add Check**, „Period“ 1 Minute, „Grace Time“ 2 Minuten (bei Intervall 60 s).
2. Die Ping-URL eintragen, z. B. `https://hc-ping.com/<uuid>` oder bei einer eigenen Instanz
   `http://healthchecks.lan:8000/ping/<uuid>`.
3. **Jetzt senden** – der Check wird „up“. Bei kritischem Zustand ruft ntp-gui `<uuid>/fail` auf,
   Healthchecks meldet dann sofort „down“.

## Datenschutz

Der Wächter sieht bei jedem Ping die Adresse, von der er kommt, und wie oft er kommt. Läuft er im
Internet (healthchecks.io, eine Kuma-Instanz beim Hoster), ist das deine **öffentliche IP-Adresse** –
grob ortbar per GeoIP. Am besten läuft der Wächter deshalb im eigenen Netz; Uptime Kuma braucht nur
einen kleinen Container. Wer den Ausfall des ganzen Standorts (Strom, Internet) bemerken will,
braucht allerdings einen Wächter außerhalb – dann bewusst und mit `https://`.

Die Adresse wird wie ein Geheimnis behandelt:

- **Sicherung** (herunterladen und nächtlich): ohne die Adresse; beim Wiederherstellen bleibt die
  vorhandene stehen, sonst nennt die Vorschau sie unter „neu eingeben“.
- **Einstellungen exportieren:** mit Verwaltungsrecht vollständig (wie die DoH-Adressen), mit einem
  Lese-Schlüssel nur gekürzt (`https://hc-ping.com/…`); ein gekürzter Wert wird beim Import
  übersprungen.
- **Lese-Schlüssel, `/api/status`, Seite Benachrichtigungen:** nie die volle Adresse – nur Schema,
  Host und Port.
- **Diagnosepaket:** nur „gesetzt“.

Prometheus-Metriken gibt es für den Ping bewusst nicht; den Zustand zeigt der Wächter selbst.
