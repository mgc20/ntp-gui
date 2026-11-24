// Erklärungen zur Seite „Benachrichtigungen“. Wird in help.js in HELP übernommen; die Schlüssel
// stehen gesammelt in HELP_GROUP_NOTIFY, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_NOTIFY = {
  notify: {
    title: "Benachrichtigungen",
    text: "ntp-gui schickt dir eine Nachricht, wenn etwas passiert, das du sonst erst beim nächsten Blick ins Dashboard "
      + "merken würdest: GPS-Fix verloren, PPS ausgeblieben, Dienst abgestürzt, keine Zeitquelle mehr. Grundlage ist das "
      + "Ereignisprotokoll (Seite „Diagnose“) – jede Regel sagt, **welche Ereignisse** (Stufe und Art) an **welchen Kanal** "
      + "gehen. Ohne angelegten Kanal verlässt nichts den Server. Jede Nachricht läuft durch den Datenschutzfilter "
      + "(Zweck „notify“): nur Titel, Stufe, Art und Zeit, keine Ereignisdaten, keine Koordinaten, keine öffentlichen "
      + "IP-Adressen, keine eigenen Hostnamen. Findet die Schlussprüfung trotzdem etwas, wird die Nachricht nicht gesendet "
      + "und das steht im Ereignisprotokoll.",
  },
  notify_channel: {
    title: "Kanal",
    text: "Ein Ziel für Nachrichten mit eigenen Regeln. Du kannst mehrere anlegen (höchstens 10), z. B. „Handy“ nur für "
      + "Kritisches und „Home Assistant“ für alles ab Warnung. Jeder Kanal hat einen eigenen Versand-Thread mit eigener "
      + "Warteschlange: Hängt ein Ziel, warten nur dessen Nachrichten – Messung, Dashboard und die anderen Kanäle laufen "
      + "weiter. Kanäle anlegen und ändern darf nur, wer das Verwaltungsrecht hat.",
  },
  notify_types: {
    title: "Kanalarten",
    text: "**ntfy**: Push aufs Handy über ntfy.sh oder einen eigenen ntfy-Server – am schnellsten eingerichtet. "
      + "**Gotify**: selbst gehosteter Push-Dienst, braucht ein App-Token. **Webhook**: ein JSON-POST an eine beliebige "
      + "Adresse, z. B. eine Home-Assistant-Automation oder Node-RED; optional mit HMAC-Signatur. **Apprise-API**: ein "
      + "kleiner Zusatz-Container, der an E-Mail, Telegram, Matrix, Signal, Slack und über 100 weitere Dienste weiterleitet – "
      + "so braucht ntp-gui selbst keine Zugangsdaten für E-Mail & Co. und keine zusätzlichen Bibliotheken.",
  },
  notify_target: {
    title: "Adresse",
    text: "Wohin die Nachricht geht – nur `http://` oder `https://`, ohne Benutzer und Passwort in der Adresse (dafür gibt es "
      + "das Token-Feld, das maskiert wird). ntp-gui folgt **keiner Weiterleitung**: Antwortet das Ziel mit 301/302, gilt das "
      + "als Fehler. Sonst könnte ein Ziel die Nachricht unbemerkt woandershin umlenken. Proxys aus der Umgebung werden nicht "
      + "benutzt. Bei ntfy kommt das **Thema** dazu (auf ntfy.sh ist der Themenname wie ein Passwort: schwer zu raten wählen), "
      + "bei Apprise der **Schlüssel** einer in der Apprise-API gespeicherten Konfiguration. Für ntfy, Gotify und Apprise nur "
      + "die **Server-Adresse** ohne `?…` – „https://ntfy.sh/mein-thema“ geht auch, das Thema wird dann herausgelöst (ntfy "
      + "nimmt JSON nur an der Wurzel an). Steckt in der Adresse selbst ein Schlüssel (Home-Assistant-Webhook-ID, Discord- oder "
      + "Slack-Token im Pfad), zeigen Dashboard und API den Pfad nur gekürzt als „/…“; beim Bearbeiten leer lassen behält ihn. "
      + "**Gesperrte Ziele:** link-local (`169.254.x.x`, `fe80::`, dort antworten bei Cloud-Anbietern die Metadaten-Dienste) "
      + "und der Server selbst (`127.0.0.1`, `localhost`). Geprüft wird die Adresse, zu der der Name aufgelöst wird. Ein "
      + "Dienst auf demselben Rechner (z. B. Apprise bei `network_mode: host`) geht mit `OUTBOUND_TARGETS=loopback` in der "
      + "Compose-Datei; `OUTBOUND_TARGETS=public` erlaubt nur öffentliche Ziele (Server im Internet).",
  },
  notify_secret: {
    title: "Token",
    text: "Zugangsdaten des Ziels: ntfy-Token, Gotify-App-Token, der Schlüssel für die Webhook-Signatur oder Apprise-URLs. "
      + "Gespeichert in der Datenbank im Volume (nur für den Dienst lesbar). Das Dashboard und die API zeigen es **nie** wieder "
      + "an, nur „gesetzt“ – Feld leer lassen behält es, „entfernen“ löscht es. Es steht nie im Ereignisprotokoll und nie im "
      + "Diagnosepaket. **Änderst du Art oder Ziel** (Schema, Host, Port), musst du das Token neu eingeben: Sonst könnte jemand "
      + "mit Schreibrecht die Adresse auf seinen eigenen Server umbiegen und bekäme das gespeicherte Token zugeschickt. "
      + "Ein Token geht nur über `https://` hinaus – oder über `http://` an eine Adresse im eigenen Netz (private IP, "
      + "`*.lan`, `*.local`, `*.home.arpa`, ein Name ohne Punkt wie `apprise`), sonst läge es im Klartext im Internet. "
      + "Beim Senden zählt die aufgelöste Adresse: Zeigt der Name ins Internet, geht über `http://` nichts hinaus.",
  },
  notify_filter: {
    title: "Filter: Stufe und Arten",
    text: "**Stufe**: „ab Warnung“ schickt Warnungen und Kritisches, „nur Kritisch“ nur Ausfälle, „alles ab Info“ auch "
      + "Quellenwechsel und Neustarts (das wird schnell viel). **Arten**: GPS, PPS, Dienste, Zeitquellen, Zertifikat … Keine "
      + "markiert heißt **alle** – auch Arten, die künftige Versionen dazubringen. Eine „behoben“-Nachricht kommt immer, "
      + "wenn das Problem vorher gemeldet wurde, auch wenn sie selbst nur Stufe Info hat.",
  },
  notify_debounce: {
    title: "Entprellen",
    text: "Bei schwachem Empfang kann der GPS-Fix im Minutentakt kommen und gehen. Damit dein Handy nicht ständig vibriert, "
      + "geht dieselbe Meldung (gleiche Art und gleicher Betreff, also gleiches Gerät oder gleicher Dienst) höchstens einmal je "
      + "eingestellter Zeit hinaus. Was dazwischen passiert, wird gezählt („5 gleiche Meldungen zusammengefasst“). Besteht ein "
      + "zurückgehaltenes Problem am Ende der Sperrzeit noch, kommt es nach („besteht seit 15 min“) – der letzte Stand kommt "
      + "also immer an. Wird ein Problem schlimmer (Warnung → Kritisch), geht das sofort hinaus; ein **Kritisch** wartet nie "
      + "hinter einer Warnung und auch nicht, wenn zuletzt „behoben“ gemeldet wurde – sonst stünde bei dir „alles gut“, während "
      + "gerade ein Pflichtdienst ausfällt und der Container endet.",
  },
  notify_rate: {
    title: "Höchstens je Stunde",
    text: "Obergrenze je Kanal über die letzten 60 Minuten. Schutz vor einer Flut, wenn etwas grundsätzlich schiefgeht – und vor "
      + "der Sperre durch den Dienst (ntfy.sh drosselt selbst). Was darüber liegt, wird verworfen und gezählt; einmal je Stunde "
      + "steht ein Hinweis im Ereignisprotokoll.",
  },
  notify_resolved: {
    title: "„Behoben“ melden",
    text: "Wenn ein gemeldetes Problem vorbei ist, kommt eine zweite Nachricht mit der Dauer, z. B. „GPS-Fix wieder da – Dauer "
      + "40 min“. So weißt du, ob du noch etwas tun musst, und siehst, wie lange der Server ohne GPS lief. Als „behoben“ zählen "
      + "nur echte Gegenstücke (GPS-Fix wieder da, PPS wieder da, Dienst läuft wieder, Zertifikat erneuert, Client-Uhr wieder "
      + "im Rahmen …) – ein beliebiges Info-Ereignis derselben Art, etwa ein neuer Kalibriervorschlag, schließt kein Problem. "
      + "Ausschalten, wenn dich nur der Anfang interessiert.",
  },
  notify_enabled: {
    title: "Aktiv",
    text: "Ein ausgeschalteter Kanal bleibt mit allen Angaben gespeichert, bekommt aber keine Nachrichten. Praktisch für den Urlaub "
      + "oder während du am Gerät bastelst. Die Testnachricht funktioniert trotzdem.",
  },
  notify_status: {
    title: "Zustellstand",
    text: "**zugestellt**: Die letzte Nachricht hat das Ziel mit 2xx angenommen. **Fehler**: Der letzte Versuch ist gescheitert – "
      + "der Grund steht darunter. **noch nichts gesendet**: Kanal neu oder bisher kein passendes Ereignis – schick eine "
      + "Testnachricht. Der Zustand ist auch für Lese-Schlüssel abrufbar (`GET /api/v1/notify/status`) – dort nur mit Kennung "
      + "und Art, ohne Namen, Adresse und Token: Lese-Schlüssel stecken oft in Widgets, und ein Name wie „Handy von Max“ hat "
      + "dort nichts verloren.",
  },
  notify_error: {
    title: "Letzter Fehler",
    text: "Kurz und ohne Adresse: **Ziel nicht erreichbar oder nicht erlaubt** (Dienst läuft nicht, Port falsch, keine "
      + "gültige HTTP-Antwort oder ein gesperrtes Ziel – bewusst eine Meldung für alles), **Name nicht auflösbar** (Tippfehler, "
      + "DNS), **Zeitüberschreitung** (alles zusammen – Namensauflösung, Verbindung, Antwort – höchstens 10 s; auch ein Ziel, "
      + "das die Antwort nur tröpfchenweise schickt, hält den Versand nicht länger auf), **HTTP 401/403** (Token falsch), **Weiterleitung abgelehnt** (Adresse zeigt auf "
      + "eine Umleitung – trag das endgültige Ziel ein, oft fehlt nur `https://` oder ein `/` am Ende), **TLS-Fehler** "
      + "(Zertifikat abgelaufen oder selbst signiert). Der Test-Knopf geht höchstens fünfmal je Minute und je Kanal alle "
      + "5 Sekunden.",
  },
  notify_counts: {
    title: "Gesendet, fehlgeschlagen, verworfen",
    text: "Zähler seit dem Anlegen. **Fehlgeschlagen** zählt jeden einzelnen Versuch, **verworfen** jede Nachricht, die nie ankam: "
      + "nach allen Wiederholungen, wegen des Stundenlimits oder weil die Warteschlange (50 je Kanal) voll war.",
  },
  notify_retry: {
    title: "Wiederholung",
    text: "Klappt die Zustellung nicht, versucht ntp-gui es nach 30 s, 2 min und 10 min noch einmal. Danach wird die Nachricht "
      + "verworfen und ein Ereignis der Art „Benachrichtigung“ ins Protokoll geschrieben. Diese Ereignisse selbst werden nie "
      + "verschickt – sonst könnten sich zwei kaputte Kanäle gegenseitig beschäftigen.",
  },
  notify_link: {
    title: "Link zum Dashboard",
    text: "Ist unter System → Einstellungen → Dashboard & Zugang → Erweitert die **Adresse des Dashboards** eingetragen (`NOTIFY_DASHBOARD_URL`), hängt jede "
      + "Nachricht einen Link auf die passende Seite an (GPS, Quellen, Diagnose …). Der Link wird nicht gefiltert, weil du ihn "
      + "selbst einträgst – nimm eine Adresse, die die Empfänger sehen dürfen (z. B. den Namen im LAN).",
  },
  notify_webhook: {
    title: "Webhook: Format und Signatur",
    text: "POST mit `Content-Type: application/json` und Feldern `source` („ntp-gui“), `version` (1), `title`, `text`, `level` "
      + "(info/warn/crit), `kind`, `time` (Unix-Zeit), `resolved`, bei „behoben“ `duration_s`, optional `link`, `suppressed`, "
      + "`event_id`, bei der Testnachricht `test: true`. Mit Signatur-Schlüssel kommt der Header `X-NTPGUI-Signature: "
      + "sha256=<hex>` – HMAC-SHA256 über die **unveränderten Bytes** des Bodys. Prüfbeispiel: Schlüssel `geheim`, Body "
      + "`{\"source\":\"ntp-gui\",\"test\":true}` ergibt `sha256=aa6b045120327114063405a2160f1f0e2257424dfb0c0a0728d2881de0104c6e` "
      + "(nachrechnen: `printf '%s' '<body>' | openssl dgst -sha256 -hmac geheim`).",
  },
  notify_apprise: {
    title: "Apprise-API als Zusatz-Container",
    text: "In die Compose-Datei neben ntp-gui: `apprise: { image: caronc/apprise:latest, restart: unless-stopped }` (Port nur "
      + "intern, kein `ports:` nötig). In der Apprise-Oberfläche (oder per `POST /add/ntp`) unter einem Schlüssel wie `ntp` deine "
      + "Ziele speichern, z. B. `mailto://user:pass@mail.example.org` oder `tgram://bottoken/chatid`. Hier dann Adresse "
      + "`http://apprise:8000` und Schlüssel `ntp` eintragen. So liegen E-Mail-Passwörter nur bei Apprise.",
  },
  heartbeat: {
    title: "Zeitwächter-Ping",
    text: "Die Benachrichtigungen laufen im selben Prozess wie alles andere: Ist der Rechner aus, der Container weg oder der "
      + "Strom ausgefallen, kann ntp-gui nichts mehr melden. Dafür gibt es den Zeitwächter-Ping. Trag unter **System → Einstellungen → "
      + "Dashboard & Zugang** die Adresse deines eigenen Wächters ein – **Uptime Kuma** (Monitor-Typ „Push“, Adresse "
      + "`http://kuma.lan:3001/api/push/<token>`) oder **Healthchecks** (selbst gehostet oder `https://hc-ping.com/<uuid>`). "
      + "ntp-gui ruft sie dann regelmäßig auf; bleibt der Aufruf aus, schlägt der Wächter Alarm. Gesendet wird nur eine "
      + "GET-Anfrage ohne Inhalt mit dem User-Agent `ntp-gui` (Zweck „heartbeat“ im Datenschutzfilter, leere Feldliste) – "
      + "keine Messwerte, keine Namen. Weiterleitungen werden nicht befolgt, nach 5 s ist Schluss, und das Ziel wird nach der "
      + "Namensauflösung geprüft wie bei den Benachrichtigungen (keine Metadaten-Dienste, Loopback nur mit "
      + "`OUTBOUND_TARGETS=loopback`). **Datenschutz:** Ein Wächter im Internet sieht deine öffentliche IP-Adresse (grob "
      + "ortbar) und wie oft der Ping kommt – am besten läuft er im eigenen Netz. Die Adresse enthält den Schlüssel des "
      + "Wächters: Sicherungen lassen sie weg, Lese-Schlüssel und das Diagnosepaket sehen sie nicht, über `http://` geht sie "
      + "nur an Adressen im eigenen Netz. Ohne Adresse ist der Ping aus.",
  },
  heartbeat_mode: {
    title: "Zeitwächter-Ping: Art und Intervall",
    text: "Bei gutem Zustand geht immer `GET <adresse>` hinaus. Kritisch heißt: Die Übersicht zeigt einen roten Hinweis (z. B. "
      + "chronyd antwortet nicht, Pflichtdienst ausgefallen). Dann je nach Art: **Healthchecks** ruft `<adresse>/fail` auf, "
      + "**Uptime Kuma Push** setzt `status=down` (und `msg=kritisch`) statt `status=up`, **nur Lebenszeichen** sendet gar "
      + "nichts – das passt für jeden Wächter, der nur das Ausbleiben bemerkt. **Automatisch** erkennt Uptime-Kuma-Adressen "
      + "am Pfad `/api/push/…` und behandelt alle anderen wie Healthchecks. Das Intervall (30 bis 3600 s, Standard 60 s) "
      + "sollte etwas kürzer sein als die Frist im Wächter – z. B. 60 s bei Uptime Kuma „Heartbeat Interval“ 90 s.",
  },
  heartbeat_status: {
    title: "Zeitwächter-Ping: letztes Ergebnis",
    text: "**Letzter Ping** zeigt, was zuletzt gemeldet wurde (gut, kritisch oder bei „nur Lebenszeichen“: nichts gesendet) "
      + "und ob es angekommen ist. **Zuletzt angekommen**: letzte Antwort mit HTTP 2xx. Scheitert der Ping dreimal in Folge, "
      + "steht ein Ereignis der Art „Zeitwächter-Ping“ im Protokoll (und geht an deine Benachrichtigungskanäle, wenn sie "
      + "diese Art zulassen); kommt er wieder an, folgt „wieder erreichbar“. **Jetzt senden** schickt sofort einen Ping mit "
      + "dem echten Zustand (höchstens alle 10 s). Die Zieladresse steht hier nur gekürzt.",
  },
};

export const HELP_GROUP_NOTIFY = {
  title: "Benachrichtigungen",
  keys: ["notify", "notify_channel", "notify_types", "notify_target", "notify_secret", "notify_filter", "notify_debounce",
    "notify_rate", "notify_resolved", "notify_enabled", "notify_status", "notify_error", "notify_counts", "notify_retry",
    "notify_link", "notify_webhook", "notify_apprise", "heartbeat", "heartbeat_mode", "heartbeat_status"],
};
