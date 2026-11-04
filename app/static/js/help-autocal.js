// Erklärungen zur automatischen GPS-Kalibrierung (Karte „GPS kalibrieren“ auf der GPS-Seite).
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in
// HELP_GROUP_AUTOCAL, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_AUTOCAL = {
  autocal_mode: {
    title: "Automatische Kalibrierung",
    text: "Ein USB-GPS meldet die Zeit mit einer festen Verspätung. ntp-gui misst sie laufend gegen deine "
      + "Netzwerkquellen. **Automatisch** (Standard ab 1.5.2, du musst nichts tun): ntp-gui stellt den Offset selbst "
      + "nach, immer im selben Ablauf: **messen** (mindestens "
      + "6 h) → einen deutlichen Versatz **einmal korrigieren** (ohne PPS in einem Schritt, mit PPS in Schritten "
      + "von höchstens 5 ms je Tag) → danach nur noch **kleinen Drifts folgen**, jeweils erst nach einer ganzen "
      + "24-h-Messung. Nur mit vertrauenswürdigem Vergleich, nie während einer GNSS-Störung, und jede Änderung "
      + "lässt sich zurücknehmen. Ein anderer Empfänger (Gerät in den Einstellungen) oder „Neu lernen“ bei den "
      + "GNSS-Störungen startet die Messung von selbst neu. Wo sie gerade steht, zeigt „Phase“. **Vorschlagen**: du "
      + "siehst einen passenden Offset, sobald die Messung belastbar ist, und übernimmst ihn selbst. **Aus**: nichts "
      + "passiert, der Assistent oben bleibt nutzbar. Umstellen kannst du das in den Einstellungen unter GPS.",
  },
  autocal_phase: {
    title: "Phase",
    text: "Wo die automatische Kalibrierung gerade steht: **misst** (seit der letzten Offset-Änderung, mit "
      + "Fortschritt), **korrigiert bei nächster Prüfung** (die stündliche Prüfung stellt den Offset um), "
      + "**kalibriert – folgt nur kleinen Drifts** (alles gut; kleine Abweichungen werden erst nach einer "
      + "ganzen 24-h-Messung nachgezogen, damit Tagesschwankungen der Netzlaufzeit den Offset nicht hin- und "
      + "herschieben), **gesperrt wegen GNSS-Störung** (hier entscheidest du: Empfänger oder Antenne gewechselt → "
      + "„Neu lernen“ bei den GNSS-Störungen; sonst Antenne und Umgebung prüfen), **wartet** (z. B. "
      + "keine Netzwerkquelle als Vergleich) oder **bitte prüfen** (Messung zu ungewöhnlich für eine Automatik).",
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
    title: "Nächster Schritt",
    text: "Wann die Automatik frühestens wieder etwas tun kann – passend zur Phase: Ende der Mindest-"
      + "Messdauer, die nächste stündliche Prüfung (Korrektur steht an), das Ende der 24-h-Messung für eine "
      + "kleine Drift oder 24 h nach dem letzten Teilschritt. Ob dann wirklich geändert wird, entscheidet die "
      + "Messung. Ist das GPS kalibriert oder gesperrt, steht hier nichts – dann steht nichts an.",
  },
  autocal_step: {
    title: "Größter Schritt",
    text: "So weit darf eine automatische Änderung den Offset höchstens verschieben (Einstellung „Größter "
      + "Kalibrierschritt“). Mit PPS werden größere Abweichungen in mehreren Schritten über mehrere Tage abgebaut. "
      + "Liegt eine Messung einmal daneben, richtet ein kleiner Schritt wenig Schaden an. Den kleineren "
      + "Delay-Vorschlag übernimmt die Automatik erst mit dem letzten Schritt – vorher würde ein kleiner "
      + "Delay chrony zu einem noch falschen GPS locken. **Ausnahme ohne PPS:** Ist das GPS die "
      + "Rückfallebene (Fehlerschranke „gemessen“, Rolle nicht „bevorzugen“) und liegt es deutlich daneben "
      + "(mindestens 10 ms und dreimal die Schwelle), gemessen über mindestens 6 h gegen mindestens zwei "
      + "NTS-Quellen (ohne NTS: über 12 h gegen mindestens drei Netzquellen), korrigiert die Automatik den ganzen "
      + "Versatz in einem Schritt; fehlen die Quellen nur kurz, wartet sie damit bis zu 24 h, statt vorher einen "
      + "Teilschritt zu machen. Nach „Neu lernen“ bei den GNSS-Störungen kommt dieser Schritt erst nach einer "
      + "ganzen 24-h-Messung ohne Störung. Solange die Netzquellen "
      + "besser sind, stellt chrony die Uhr ohnehin nicht nach dem GPS – mit 5 ms je Tag bräuchte ein Versatz "
      + "von 50 ms (etwa nach „Offset zurücksetzen“) sonst zehn Tage. Mit PPS bleibt es bei kleinen Schritten. "
      + "Dafür zählen auch Messwerte, in denen chrony das GPS als Falseticker („x“) verwirft, sofern mindestens zwei "
      + "genutzte Netzquellen dagegenstehen – sonst gäbe es genau dann keine Daten. Einen Sprung im Messzeitraum "
      + "(erste und zweite Hälfte liegen deutlich auseinander) korrigiert sie nicht in einem Zug. **Bei einer "
      + "GNSS-Störung nie:** Meldet die Störungserkennung gerade eine Warnung oder Störung, hält die GPS-Sperre "
      + "oder gab es im Messzeitraum eine Warnung oder Störung, ändert die Automatik nichts – sonst würde eine "
      + "Fälschung, die die Zeit gleichbleibend verschiebt, einfach „eingerechnet“.",
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
      + "zurück, ohne PPS auch die mitgesetzte Fehlerschranke (auf den vorsichtigen Standard); chrony startet "
      + "dafür einmal kurz neu. Danach wartet die Automatik wieder mindestens 24 h und korrigiert auch einen "
      + "deutlichen Versatz nie mehr in einem Zug, nur noch in kleinen Schritten – bis du den Offset von Hand "
      + "änderst, einen anderen Empfänger einstellst oder „Neu lernen“ drückst. Soll "
      + "sie gar nicht mehr ändern, stell den Modus auf „vorschlagen“. Wurde der Offset seitdem von Hand "
      + "geändert, geht Rückgängig nicht – sonst würde es deine Änderung überschreiben.",
  },
};

export const HELP_GROUP_AUTOCAL = {
  title: "Automatische GPS-Kalibrierung",
  keys: ["autocal_mode", "autocal_phase", "autocal_decision", "autocal_bias", "autocal_threshold", "autocal_reference",
    "autocal_window", "autocal_next", "autocal_step", "autocal_changes", "autocal_rollback"],
};
