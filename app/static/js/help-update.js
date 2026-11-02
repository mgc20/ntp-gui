// Erklärungen zum Update-Hinweis (Einstellungen → Dashboard, Banner oben). Wird in help.js in HELP
// übernommen; die Schlüssel stehen gesammelt in HELP_GROUP_UPDATE, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_UPDATE = {
  update_check: {
    title: "Update-Hinweis",
    text: "Eingeschaltet fragt ntp-gui **einmal am Tag** zu einer zufälligen Uhrzeit bei GitHub nach, welche Version "
      + "die neueste ist (`api.github.com/repos/ConGp20/ntp-gui/releases/latest`), und vergleicht sie hier im Container "
      + "mit der installierten. Ist eine neuere da, erscheint oben ein Banner und in der Übersicht ein Hinweis mit Link "
      + "zu den Release-Notizen. Die zufällige Uhrzeit verteilt die Anfragen vieler Installationen über den Tag; ist sie "
      + "beim Einschalten für heute schon vorbei, kommt die erste Prüfung innerhalb einer Minute. "
      + "**Was GitHub sieht – ehrlich:** einmal am Tag deine öffentliche IP-Adresse (per GeoIP grob ortbar, meist "
      + "Stadt oder Region) und dass dort vermutlich ntp-gui läuft. Mehr nicht: Die Anfrage ist fest verdrahtet, "
      + "der User-Agent heißt nur „ntp-gui“ – ohne Version, ohne Kennung, ohne Daten dieser Instanz. Der Datenschutzfilter "
      + "(Zweck „update_check“) lässt nichts anderes hinaus. Weiterleitungen werden nicht befolgt, nach 10 s wird "
      + "abgebrochen, die Antwort ist auf 512 KiB begrenzt. Darum ist der Hinweis **aus**, bis du ihn einschaltest. "
      + "**Kein Download, kein automatisches Update** – du entscheidest, wann du das Image tauschst.",
  },
  update_banner: {
    title: "Neue Version verfügbar",
    text: "GitHub nennt eine neuere ntp-gui-Version als die installierte. Aktualisieren: neues Image ziehen und den "
      + "Container neu erstellen (`docker compose pull && docker compose up -d`). Einstellungen, Verlauf und "
      + "Ereignisse liegen im Volume und bleiben erhalten; Änderungen an gespeicherten Einstellungen nennt die "
      + "Einstellungsseite danach unter „Was sich beim Update geändert hat“. „✕“ blendet das Banner für diese Version "
      + "in diesem Browser aus. "
      + "Wer Updates automatisch gemeldet oder eingespielt haben will, nimmt **Diun** (meldet neue Image-Tags per "
      + "E-Mail, ntfy, Gotify …) oder **What's up Docker (WUD)**. Watchtower ist seit Dezember 2025 archiviert und bekommt "
      + "keine Fehlerbehebungen mehr – dafür nicht mehr einsetzen.",
  },
  update_attention: {
    title: "Achtung beim Update",
    text: "Der Release-Text enthält „BREAKING“ oder „Achtung“: Bei dieser Version musst du vor oder nach dem Update etwas "
      + "selbst tun oder prüfen – z. B. eine umbenannte Umgebungsvariable, ein geändertes Volume oder ein neuer Port. "
      + "Die erste markierte Zeile steht im Hinweis; lies vor dem Tausch des Images die vollständigen Release-Notizen.",
  },
  update_current: {
    title: "Installierte Version",
    text: "Die Version dieses Containers (aus dem Image). „unbekannt“ bei selbst gebauten Images ohne Versionsnummer – "
      + "dann kann der Update-Hinweis nicht vergleichen und zeigt nur die neueste Version an.",
  },
  update_latest: {
    title: "Neueste Version auf GitHub",
    text: "Was GitHub bei der letzten erfolgreichen Prüfung als neuestes Release nannte, mit Titel. Vorabversionen "
      + "(Release Candidates) zählen nicht. Der Link führt immer zu `github.com/ConGp20/ntp-gui/releases` – er wird "
      + "aus der Versionsnummer gebaut, nie aus der Antwort übernommen.",
  },
  update_last: {
    title: "Letzte Prüfung",
    text: "Wann ntp-gui zuletzt gefragt hat und ob es geklappt hat. Scheitert eine Prüfung (kein Internet, DNS, "
      + "GitHub-Limit), wird es erst am nächsten Tag wieder versucht – nie öfter als einmal am Tag.",
  },
  update_next: {
    title: "Nächste Prüfung",
    text: "Die für heute bzw. morgen ausgewürfelte Uhrzeit. Nach einem Neustart des Containers wird neu gewürfelt; "
      + "eine schon erledigte Prüfung des Tages zählt trotzdem.",
  },
};

export const HELP_GROUP_UPDATE = {
  title: "Update-Hinweis",
  keys: ["update_check", "update_banner", "update_attention", "update_current", "update_latest", "update_last",
    "update_next"],
};
