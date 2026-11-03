// Erklärungen zur automatischen GPS-Kalibrierung (Karte „GPS kalibrieren“ auf der GPS-Seite).
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in
// HELP_GROUP_AUTOCAL, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_AUTOCAL = {
  autocal_mode: {
    title: "Automatische Kalibrierung",
    text: "Ein USB-GPS meldet die Zeit mit einer festen Verspätung. ntp-gui misst sie laufend gegen deine "
      + "Netzwerkquellen. **Aus**: nichts passiert, der Assistent oben bleibt nutzbar. **Vorschlagen**: du "
      + "siehst einen passenden Offset, sobald die Messung belastbar ist, und übernimmst ihn selbst. "
      + "**Automatisch**: ntp-gui stellt den Offset behutsam selbst nach – höchstens einmal am Tag, in kleinen "
      + "Schritten, nur mit vertrauenswürdigem Vergleich, und jede Änderung lässt sich zurücknehmen. "
      + "Umstellen kannst du das in den Einstellungen unter GPS.",
  },
  autocal_decision: {
    title: "Aktuelle Entscheidung",
    text: "Was die Kalibrierung gerade tun würde und **warum**. Sie prüft der Reihe nach: genug Messdauer seit "
      + "der letzten Änderung? Vertrauenswürdige Netzwerkquellen als Vergleich? Ist die Abweichung größer "
      + "als das Messrauschen? Ist die letzte automatische Änderung mindestens 24 h her? Erst wenn alles "
      + "passt, wird vorgeschlagen bzw. geändert. Neu geprüft wird einmal pro Stunde.",
  },
  autocal_bias: {
    title: "Gemessene Abweichung",
    text: "Um so viel liegt das GPS im Median neben den genutzten Netzwerkquellen – gemessen nur seit der "
      + "letzten Offset-Änderung (plus 15 Minuten Einschwingzeit), damit alte und neue Werte sich nicht "
      + "mischen. Positiv heißt: das GPS ist zu spät, der Offset muss größer werden.",
  },
  autocal_threshold: {
    title: "Schwelle",
    text: "Kleinere Abweichungen werden ignoriert, weil sie im Rauschen der Messung liegen könnten. Die "
      + "Schwelle ist mindestens **1 ms** und sonst dreimal der Standardfehler des Medians – gerechnet mit "
      + "höchstens einer unabhängigen Messung pro 10 Minuten, weil aufeinanderfolgende Werte stark "
      + "zusammenhängen. Würde eine Korrektur die letzte automatische Änderung umkehren, gilt eine Woche "
      + "lang die **doppelte** Schwelle – so pendelt der Offset nicht hin und her.",
  },
  autocal_reference: {
    title: "Vergleichsquellen",
    text: "Gegen wen das GPS gemessen wird. Nötig sind im Messzeitraum mindestens **zwei** genutzte "
      + "Netzwerkquellen (ausgewählt oder kombiniert) oder eine mit **NTS** – eine einzelne Quelle ohne "
      + "Absicherung könnte selbst falsch gehen, und dann wäre auch die Kalibrierung falsch. Ist gerade gar "
      + "keine Netzwerkquelle nutzbar (Internet weg), ist das GPS die einzige Quelle: Dann ändert sich nichts.",
  },
  autocal_window: {
    title: "Messung zählt seit / ab",
    text: "Ab diesem Zeitpunkt zählen die Messwerte. Jede Änderung des Offsets – automatisch, per "
      + "Rücknahme oder von Hand – startet die Messung neu, weil die alten Werte zum alten Offset gehören. "
      + "Nach einer Änderung und nach dem Start wartet sie zuerst etwa 15 Minuten, bis chrony eingeschwungen ist; solange steht hier "
      + "„zählt **ab**“ mit einem Zeitpunkt in der Zukunft. "
      + "Bevor etwas vorgeschlagen oder geändert wird, muss die eingestellte Mindest-Messdauer erreicht sein.",
  },
  autocal_next: {
    title: "Nächste mögliche Änderung",
    text: "Frühester Zeitpunkt für die nächste automatische Änderung: mindestens 24 h nach der letzten "
      + "Änderung oder Rücknahme und erst, wenn seit dem Neustart der Messung die Mindest-Messdauer "
      + "vergangen ist. Ob dann wirklich geändert wird, entscheidet die Messung. Ohne PPS (GPS als "
      + "Rückfallebene) entfällt die 24-h-Pause für einen deutlichen Versatz – siehe „Größter Schritt“.",
  },
  autocal_step: {
    title: "Größter Schritt",
    text: "So weit darf eine automatische Änderung den Offset höchstens verschieben (Einstellung „Größter "
      + "Kalibrierschritt“). Größere Abweichungen werden in mehreren Schritten über mehrere Tage abgebaut. "
      + "Liegt eine Messung einmal daneben, richtet ein kleiner Schritt wenig Schaden an. Den kleineren "
      + "Delay-Vorschlag übernimmt die Automatik erst mit dem letzten Schritt – vorher würde ein kleiner "
      + "Delay chrony zu einem noch falschen GPS locken. **Ausnahme ohne PPS:** Ist das GPS die "
      + "Rückfallebene (Fehlerschranke „gemessen“, Rolle nicht „bevorzugen“) und liegt es deutlich daneben "
      + "(mindestens 10 ms und dreimal die Schwelle), gemessen über mindestens 6 h gegen mindestens zwei "
      + "NTS-Quellen, korrigiert die Automatik den ganzen Versatz in einem Schritt. Solange die Netzquellen "
      + "besser sind, stellt chrony die Uhr ohnehin nicht nach dem GPS – mit 5 ms je Tag bräuchte ein Versatz "
      + "von 50 ms (etwa nach „Offset zurücksetzen“) sonst zehn Tage. Mit PPS bleibt es bei kleinen Schritten.",
  },
  autocal_changes: {
    title: "Letzte automatische Änderungen",
    text: "Jede Änderung, die die Automatik vorgenommen hat, mit altem und neuem Offset und Begründung – "
      + "auch Rücknahmen. Dieselben Einträge stehen im Ereignisprotokoll. Gespeichert in `autocal.json` im "
      + "Datenverzeichnis; es stehen nur Offsets, Zeiten und Begründungen darin, keine Quellen oder Orte.",
  },
  autocal_rollback: {
    title: "Rückgängig",
    text: "Stellt den Offset (und ggf. den Delay) auf den Wert vor der letzten automatischen Änderung "
      + "zurück; chrony startet dafür kurz neu. Danach wartet die Automatik wieder mindestens 24 h. Soll "
      + "sie gar nicht mehr ändern, stell den Modus auf „vorschlagen“. Wurde der Offset seitdem von Hand "
      + "geändert, geht Rückgängig nicht – sonst würde es deine Änderung überschreiben.",
  },
};

export const HELP_GROUP_AUTOCAL = {
  title: "Automatische GPS-Kalibrierung",
  keys: ["autocal_mode", "autocal_decision", "autocal_bias", "autocal_threshold", "autocal_reference",
    "autocal_window", "autocal_next", "autocal_step", "autocal_changes", "autocal_rollback"],
};
