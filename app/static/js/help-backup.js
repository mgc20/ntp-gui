// Erklärungen zu „Sichern und wiederherstellen“ (System → Einstellungen → Sichern, 1.6). Wird in help.js in HELP
// übernommen; die Schlüssel stehen gesammelt in HELP_GROUP_BACKUP, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_BACKUP = {
  backup: {
    title: "Sichern und wiederherstellen",
    text: "Eine Datei mit allem, was du sonst bei einer neuen SD-Karte oder einem neuen Container verlierst: "
      + "Einstellungen, Verlauf der Messwerte, Ereignisprotokoll, Geräte mit eigenen Namen, Gruppen und Regeln, "
      + "die GPS-Kalibrierung und die Benachrichtigungskanäle. **Nicht** drin: GPS-Position, Satellitenwinkel, "
      + "Passwort, API-Schlüssel, Tokens der Kanäle sowie NTS-Schlüssel und -Zertifikate. Die Sicherung ist ein "
      + "**Download** – ntp-gui lädt sie nirgendwohin hoch.",
  },
  backup_privacy: {
    title: "Wer die Datei sehen darf",
    text: "Die Sicherung enthält Daten über Geräte in deinem Netz: Adressen, eigene Namen und Notizen, wann ein "
      + "Gerät nach der Zeit gefragt hat, dazu Servernamen und Netze aus den Einstellungen. Darum **nicht "
      + "öffentlich teilen** (nicht in ein Issue, nicht in ein Forum). Für Fehlerberichte gibt es das gefilterte "
      + "**Diagnosepaket** auf der Seite „Diagnose“. Der Dateiname enthält nur Datum und Uhrzeit, nicht den "
      + "Namen dieses Servers.",
  },
  backup_contents: {
    title: "Was gesichert wird",
    text: "Genau festgelegte Tabellen und Spalten (eine **Positivliste**): Verlauf (Rohwerte und 5-Minuten-Mittel), "
      + "Ereignisse, Geräte und ihre Messpunkte, eigene Namen und Notizen, Gruppen, Regeln, Stundenwerte der "
      + "Clients, Benachrichtigungskanäle ohne Token. Die Datenbank wird dafür **neu angelegt** und nur mit diesen "
      + "Werten gefüllt – eine Kopie der ganzen Datei enthielte in ihren freien Seiten noch gelöschte Werte. "
      + "Neue Spalten späterer Versionen kommen erst hinein, wenn sie ausdrücklich freigegeben sind.",
  },
  backup_excluded: {
    title: "Was nie in die Sicherung kommt",
    text: "**Position** (gelernte GPS-Position, Höhe, Satellitenwinkel aus Antennentests und Störungserkennung) – "
      + "daraus ließe sich dein Standort bestimmen. **Geheimnisse**: Passwort-Hash, API-Schlüssel, Tokens der "
      + "Benachrichtigungskanäle, ntfy-Themen, Apprise-Schlüssel, Webhook-Adressen mit Pfad (dort steckt oft eine geheime "
      + "Kennung), DNS-over-HTTPS- und DNS-over-TLS-Server sowie feste DNS-Adressen (können eine Konto-Kennung enthalten, "
      + "z. B. bei NextDNS), NTS-Schlüssel und -Zertifikate. Ohne zusätzliche Software "
      + "gäbe es keine gute Verschlüsselung der Datei – darum bleiben Geheimnisse draußen und werden nach dem "
      + "Wiederherstellen neu eingegeben. Die Vorschau nennt sie einzeln.",
  },
  backup_restore: {
    title: "Wiederherstellen",
    text: "Zwei Schritte: Datei wählen → ntp-gui prüft sie und zeigt eine **Vorschau** (es wird noch nichts "
      + "geändert) → **Übernehmen**. Geprüft werden Größe (höchstens 200 MiB), nur die vier bekannten Dateien, "
      + "keine Links oder Pfade, Prüfsummen und Version. Sicherungen einer **neueren** ntp-gui-Version werden "
      + "abgelehnt, ältere umgewandelt. Vor dem Übernehmen sichert ntp-gui den jetzigen Stand automatisch im "
      + "Datenverzeichnis (Ordner `sicherungen`). Übernommen werden Einstellungen, Verlauf, Ereignisse, Geräte, "
      + "Namen, Gruppen, Regeln, Kalibrierung und Kanäle – sie **ersetzen** den jetzigen Stand. Jede Zeile wird dabei "
      + "noch einmal gefiltert wie beim Erstellen (keine Position, keine Geheimnisse, nur gültige Adressen). API-Schlüssel, "
      + "Passwort und GPS-Zustand bleiben, wie sie sind. **Alles oder nichts:** Geht etwas schief, bleibt der bisherige "
      + "Stand. Die Zeitdienste starten nur neu, wenn sich Einstellungen ändern, die das brauchen. Die hochgeladene "
      + "Datei bleibt höchstens 15 Minuten liegen.",
  },
  backup_created: {
    title: "Sicherung vom",
    text: "Zeitpunkt, zu dem die Sicherung erstellt wurde, und die ntp-gui-Version, die sie geschrieben hat. Nach dem "
      + "Übernehmen steht „Wiederhergestellt aus Sicherung vom …“ im Ereignisprotokoll.",
  },
  backup_history: {
    title: "Verlauf in der Sicherung",
    text: "Zeitspanne vom ältesten bis zum neuesten Messpunkt (Diagramme der Übersicht, Kalibrierung, Allan-Abweichung) "
      + "und die Zahl der Rohpunkte. Der Verlauf ersetzt den jetzigen bis zum Zeitpunkt der Sicherung. Messpunkte, die "
      + "hier **nach** diesem Zeitpunkt entstanden sind – auch die seit dem Hochladen –, bleiben erhalten; so entsteht "
      + "keine Lücke.",
  },
  backup_devices: {
    title: "Geräte in der Sicherung",
    text: "Clients, die nach der Zeit gefragt haben (mit ihren Messpunkten der letzten 7 Tage und Stundenwerten), "
      + "und wie viele davon einen eigenen Namen haben.",
  },
  backup_groups: {
    title: "Gruppen und Regeln",
    text: "Eigene Client-Gruppen (Netz und Name) und Regeln je Gerät (stumm, erwartete Abfragen, eigene "
      + "Schwellen). Jede Zeile wird beim Übernehmen wie bei einer Eingabe im Dashboard geprüft; ungültige "
      + "fallen weg.",
  },
  backup_events: {
    title: "Ereignisse in der Sicherung",
    text: "Einträge des Ereignisprotokolls. Daten zu einer Position oder zu Satelliten sind aus den Einträgen "
      + "entfernt. Übernommene alte Ereignisse lösen keine Benachrichtigungen aus.",
  },
  backup_calibration: {
    title: "Kalibrierung in der Sicherung",
    text: "Datum der letzten Änderung im Protokoll der GPS-Kalibrierung und der gespeicherte GPS-Offset. Gesichert "
      + "werden Protokoll und Messstand der automatischen Kalibrierung – eine Messung über viele Stunden muss "
      + "nach dem Wiederherstellen nicht neu beginnen. Jeder Eintrag wird auf Zahlen und Aufbau geprüft; was nicht "
      + "passt (z. B. Text statt Zahl), wird verworfen und hier genannt.",
  },
  backup_channels: {
    title: "Benachrichtigungskanäle",
    text: "Kanäle mit Name, Art, Ziel-Server und Filtern – **ohne** Token, ohne den geheimen Teil einer "
      + "Webhook-Adresse, ohne ntfy-Thema (wer das Thema eines öffentlichen ntfy-Servers kennt, liest mit) und ohne "
      + "Apprise-Schlüssel. Jeder Kanal wird wie bei einer Eingabe geprüft. Gibt es ihn hier schon (gleiche Kennung, "
      + "gleiche Art, gleicher Server), behält er seine jetzigen Tokens und seinen Zustand aus der Sicherung. **Alle "
      + "anderen kommen ausgeschaltet** – prüfe Ziel und Token unter System → Benachrichtigungen und schalte "
      + "sie dort ein. Kanäle, die es nur hier gibt und die nicht in der Sicherung stehen, werden **gelöscht** – samt "
      + "Token; auch die automatische Sicherung davor enthält keine Tokens. Steht ein Kanal mit gleicher Kennung, "
      + "aber anderer Art oder anderem Server in der Sicherung, **ersetzt** ihn die Fassung aus der Sicherung – sein "
      + "jetziger Server und Token gehen dabei verloren. Die Vorschau nennt je Kanal Art, Server, „neu“ oder "
      + "„vorhanden“, was neu einzugeben ist und welche Kanäle wegfallen oder ersetzt werden.",
  },
  backup_settings: {
    title: "Einstellungen in der Sicherung",
    text: "Die im Dashboard gespeicherten Werte. Sie ersetzen die jetzigen; Werte aus der Compose-Datei gelten "
      + "danach wie gewohnt als Startwerte. Ändert sich etwas an Zeitquellen, GPS, PTP oder Netz, starten die "
      + "Zeitdienste danach neu (wenige Sekunden). Ungültige Werte werden übersprungen und hier genannt.",
  },
  backup_reenter: {
    title: "Bitte neu eingeben",
    text: "Was absichtlich nicht in der Sicherung steht und nach dem Übernehmen fehlt: Tokens, ntfy-Themen, "
      + "Apprise-Schlüssel und vollständige Adressen neuer Benachrichtigungskanäle, DNS-over-HTTPS- und "
      + "DNS-over-TLS-Server und feste DNS-Adressen. Was hier schon eingetragen ist, bleibt erhalten.",
  },
  backup_security: {
    title: "Sicherheitsrelevante Einstellungen",
    text: "Einstellungen, die Zugang und Erreichbarkeit betreffen oder Daten hinausschicken: Lausch-Adresse, erlaubte "
      + "Netze, vertrauenswürdige Proxys, erlaubte Namen, Vollbild-Uhr ohne Anmeldung, LAN-Adressen in Nachrichten, "
      + "Update-Hinweis, Zeit- und DNS-Server. Ändert die Sicherung eine davon, steht sie hier mit altem und neuem "
      + "Wert. Stammt die Datei nicht sicher von dir, übernimm sie nicht.",
  },
  backup_busy: {
    title: "Während der Übernahme",
    text: "Der Austausch läuft in einem Zug, damit nie ein halber Stand entsteht. Solange warten andere Zugriffe auf "
      + "die Datenbank – das Dashboard reagiert einige Sekunden lang nicht (bei viel Verlauf auf einem Raspberry Pi "
      + "auch länger). Danach ist alles sofort sichtbar, auch die Geräte der laufenden Client-Messung.",
  },
  backup_stored: {
    title: "Gespeicherte Sicherungen",
    text: "Sicherungen im Datenverzeichnis (`/var/lib/chrony/ntp-gui/sicherungen`): automatisch vor jeder "
      + "Wiederherstellung (die letzten 5) und – mit dem Schalter „Nächtliche Sicherung“ – jede Nacht (die "
      + "letzten 7). Sie liegen auf derselben Karte wie die Daten; gegen einen Kartendefekt hilft nur eine "
      + "heruntergeladene Kopie.",
  },
  backup_nightly: {
    title: "Nächtliche Sicherung",
    text: "Gegen 3 Uhr (Ortszeit des Servers) legt ntp-gui eine Sicherung im Datenverzeichnis ab und behält die "
      + "letzten 7 Nächte. Inhalt wie beim Herunterladen. Standard: aus – jede Sicherung schreibt einige MB auf "
      + "die SD-Karte. Nichts wird hochgeladen.",
  },
};

export const HELP_GROUP_BACKUP = {
  title: "Sichern und wiederherstellen",
  keys: ["backup", "backup_privacy", "backup_contents", "backup_excluded", "backup_restore", "backup_created",
    "backup_history", "backup_devices", "backup_groups", "backup_events", "backup_calibration", "backup_channels",
    "backup_settings", "backup_security", "backup_reenter", "backup_busy", "backup_stored", "backup_nightly"],
};
