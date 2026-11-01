// Erklärungen zur Seite „Diagnose“: Log, Ereignisse, Diagnosepaket, Aufzeichnung.
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in
// HELP_GROUP_DIAGNOSE, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_DIAGNOSE = {
  diag_page: {
    title: "Diagnose",
    text: "Alles für die Fehlersuche an einem Ort: das Log des Containers, die wichtigsten Ereignisse und ein "
      + "**Diagnosepaket**, das du jemandem geben kannst, der dir hilft. Nichts davon verlässt das Gerät von "
      + "selbst – du lädst das Paket herunter und entscheidest, wem du es gibst.",
  },
  diag_log: {
    title: "Log",
    text: "Die Ausgaben von Supervisor, chronyd, gpsd, phc2sys und Dashboard – dasselbe wie `docker logs`, "
      + "zusätzlich in `/run/ntp-gui/ntp-gui.log` gespeichert (höchstens 2 MB plus eine ältere Datei). "
      + "Das Kürzel in eckigen Klammern sagt, wer schreibt: `[chrony]`, `[gps]`, `[ptp]`, `[main]` "
      + "(Supervisor), `[web]` (Dashboard). Nach einem Neustart des Containers beginnt das Log neu.",
  },
  diag_log_filter: {
    title: "Log filtern",
    text: "Zeigt nur Zeilen, die diesen Text enthalten (Groß-/Kleinschreibung egal). Praktisch: `gpsd`, "
      + "`Neustart`, eine Gerätedatei wie `ttyACM0` oder eine Quelle.",
  },
  diag_log_problems: {
    title: "Nur Warnungen und Fehler",
    text: "Blendet normale Meldungen aus. Als **Warnung** gilt z. B. ein fehlendes Gerät oder eine "
      + "Zeitüberschreitung, als **Fehler** ein abgestürzter Dienst oder eine ungültige Konfiguration. "
      + "Die Einstufung ist eine grobe Textsuche – im Zweifel lohnt der Blick ins ganze Log.",
  },
  diag_log_auto: {
    title: "Automatisch aktualisieren",
    text: "Lädt das Log alle 5 Sekunden neu, solange diese Seite offen ist. Zum Lesen älterer Zeilen "
      + "ausschalten, damit nichts verrutscht.",
  },
  diag_log_level: {
    title: "Einstufung der Zeilen",
    text: "Rot: Fehler (Dienst ausgefallen, Konfiguration ungültig). Gelb: Warnung (Gerät fehlt, Zeitüberschreitung, "
      + "Dienst startet neu). Ohne Farbe: normaler Betrieb.",
  },
  diag_events: {
    title: "Ereignisse",
    text: "Die wichtigen Momente im Betrieb, ohne das Rauschen des Logs: Dienst-Neustarts, übernommene "
      + "Einstellungen, Wechsel der Zeitquelle, GPS-Fix verloren oder wieder da, PPS-Impulse weg, "
      + "Zertifikat erneuert, Kalibrierung. Sie bleiben über Neustarts hinweg gespeichert – so siehst du, "
      + "**wann** ein Problem anfing.",
  },
  diag_event_kind: {
    title: "Art des Ereignisses",
    text: "**Dienst** (Neustart/Ausfall), **Neuladen** (Einstellungen übernommen, Gerät eingesteckt), "
      + "**Einstellungen**, **Quelle** (chrony hat eine andere Zeitquelle gewählt), **GPS** (Fix, Gerät), "
      + "**PPS** (Impulse), **Kalibrierung**, **Zertifikat** (NTS), **Schaltsekunde**, **Start**.",
  },
  diag_event_level: {
    title: "Gewicht",
    text: "Info: normaler Vorgang. Warnung: etwas läuft schlechter als möglich (z. B. GPS-Fix weg, Dienst "
      + "neu gestartet). Kritisch: der Zeitdienst ist betroffen (Pflichtdienst ausgefallen).",
  },
  diag_bundle: {
    title: "Diagnosepaket",
    text: "Ein Archiv (`.tar.gz`) mit allem, was für eine Fehlersuche nötig ist: Version und Plattform, die "
      + "erzeugte chrony- und ptp4l-Konfiguration, chronyc-Ausgaben, GPS- und PTP-Status, Hardware-Check, "
      + "Dienste, Ereignisse, Log, Einstellungen und Kennzahlen des Verlaufs. Eine Datei `MANIFEST.txt` "
      + "erklärt, was drin ist und was entfernt wurde. Das Paket wird **nur heruntergeladen**, nicht hochgeladen.",
  },
  diag_privacy: {
    title: "Datenschutzfilter",
    text: "Bevor etwas das Gerät verlassen kann, läuft es durch einen zentralen Filter. Ziel: Aus dem Paket lässt "
      + "sich **kein Standort** bestimmen und **kein Gerät** wiedererkennen. Entfernt werden Koordinaten, Höhe, "
      + "Geschwindigkeit, Satellitenwinkel, Seriennummern, MAC-Adressen, öffentliche IP-Adressen, eigene "
      + "Domains und Zertifikatsnamen, Zeitzonennamen und Passwörter. Eine Schlussprüfung bricht den Export ab, "
      + "falls doch noch etwas durchrutscht.",
  },
  diag_include_clients: {
    title: "Client-Liste einschließen",
    text: "Standardmäßig enthält das Paket nur die **Anzahl** der Clients. Eingeschaltet kommt die Liste dazu – "
      + "mit Pseudonymen wie `client-01` statt Adressen, aber mit Paketzahlen und Abfrageintervallen. Nützlich, "
      + "wenn einzelne Geräte keine Zeit bekommen.",
  },
  diag_include_recording: {
    title: "Aufzeichnung einschließen",
    text: "Hängt die zuletzt gemachte Aufzeichnung der Datenquellen an (siehe unten), ebenfalls gefiltert. "
      + "Damit kann jemand dein Problem auf seinem Rechner nachstellen.",
  },
  diag_preview: {
    title: "Vorschau",
    text: "Zeigt **genau** das, was im Paket stehen würde – Abschnitt für Abschnitt, schon gefiltert. Schau "
      + "ruhig hinein, bevor du etwas herunterlädst oder weitergibst.",
  },
  diag_removed: {
    title: "Entfernt oder ersetzt",
    text: "Was der Filter in diesem Paket gefunden und entfernt bzw. ersetzt hat, mit Anzahl und Grund. "
      + "Ersetzte Werte erkennst du an Platzhaltern wie `<öffentliche-IP>`, `<hostname-1>` oder `<entfernt>`.",
  },
  diag_pseudonyms: {
    title: "Pseudonyme",
    text: "Private Adressen und eigene Namen werden durch stabile Platzhalter ersetzt (`client-01`, `<hostname-1>`): "
      + "Innerhalb eines Pakets steht derselbe Platzhalter immer für dasselbe Gerät, damit Zusammenhänge "
      + "erkennbar bleiben. Zurückrechnen lässt er sich nicht, und im nächsten Paket ist die Zuordnung neu.",
  },
  diag_sections: {
    title: "Abschnitte",
    text: "Jeder Abschnitt wird eine eigene Datei im Paket. Sehr große Abschnitte (z. B. ein langes Log) werden "
      + "gekürzt – dann bleibt das Ende, weil dort meist das Interessante steht.",
  },
  diag_download: {
    title: "Herunterladen",
    text: "Erzeugt das Paket neu (mit dem aktuellen Stand) und speichert es im Browser. Es wird nirgendwohin "
      + "geschickt. Für ein GitHub-Issue kannst du die Datei einfach anhängen.",
  },
  diag_recording: {
    title: "Aufzeichnung",
    text: "Schneidet für einige Minuten mit, was ntp-gui von chronyc, gpsd, pmc und ethtool liest. Wofür? "
      + "Entwickler können damit dein Problem **genau so** auf ihrem Rechner abspielen, ohne deine Hardware – "
      + "und neue Funktionen gegen echte Daten testen. Die Aufzeichnung bleibt auf dem Gerät, bis du sie ins "
      + "Diagnosepaket aufnimmst; dabei läuft sie durch denselben Datenschutzfilter.",
  },
  diag_recording_duration: {
    title: "Dauer",
    text: "1 bis 60 Minuten. Für die meisten Probleme reichen 5 Minuten; wenn ein Fehler nur ab und zu auftritt, "
      + "so lange aufzeichnen, dass er mindestens einmal drin ist. Die Aufzeichnung kostet kaum Leistung.",
  },
  diag_recording_status: {
    title: "Zustand der Aufzeichnung",
    text: "Läuft gerade eine Aufzeichnung, siehst du, bis wann. Danach bleibt die Datei liegen, bis eine neue "
      + "Aufzeichnung sie ersetzt oder der Container neu startet.",
  },
  diag_recording_entries: {
    title: "Einträge",
    text: "Wie viele Antworten der Datenquellen (je chronyc-Befehl, gpsd-Meldung …) bisher aufgezeichnet wurden.",
  },
  diag_recording_size: {
    title: "Größe",
    text: "Größe der Aufzeichnungsdatei auf dem Gerät, vor dem Filtern.",
  },
  diag_no_upload: {
    title: "Nichts wird hochgeladen",
    text: "ntp-gui schickt weder Log noch Diagnosepaket noch Aufzeichnung irgendwohin. Alles, was die Instanz "
      + "verlässt, geht über deinen Browser – und nur, wenn du auf „Herunterladen“ klickst.",
  },
};

export const HELP_GROUP_DIAGNOSE = {
  title: "Diagnose",
  keys: [
    "diag_page", "diag_log", "diag_log_filter", "diag_log_problems", "diag_log_auto", "diag_log_level",
    "diag_events", "diag_event_kind", "diag_event_level", "diag_bundle", "diag_privacy",
    "diag_include_clients", "diag_include_recording", "diag_preview", "diag_removed", "diag_pseudonyms",
    "diag_sections", "diag_download", "diag_recording", "diag_recording_duration", "diag_recording_status",
    "diag_recording_entries", "diag_recording_size", "diag_no_upload",
  ],
};
