// Erklärungen zu API-Schlüsseln, der versionierten API, der Instanz-Kennung und den
// Update-Hinweisen der Einstellungen. Wird in help.js in HELP übernommen; die Schlüssel
// stehen gesammelt in HELP_GROUP_API, damit sie auf der Hilfe-Seite erscheinen.
export const HELP_API = {
  api_keys: {
    title: "API-Schlüssel",
    text: "Ein Schlüssel für Skripte und Programme wie Home Assistant, Prometheus oder ein eigenes "
      + "Monitoring – damit die nicht dein Dashboard-Passwort kennen müssen. Mitschicken als Header "
      + "`Authorization: Bearer ntpg_…`. Jeder Schlüssel hat einen Namen, damit du später weißt, wer ihn "
      + "benutzt, und lässt sich einzeln widerrufen, ohne dass sich für die anderen etwas ändert. "
      + "Gespeichert wird nur ein Hash (wie beim Passwort) – den Schlüssel selbst siehst du **genau einmal**, "
      + "direkt nach dem Anlegen. Solange kein Passwort gesetzt ist, ist das Dashboard ohnehin offen; "
      + "Schlüssel werden erst mit Passwort wirklich gebraucht.",
  },
  api_key_scope: {
    title: "Recht eines Schlüssels",
    text: "**nur lesen**: alle Werte abfragen (GET auf `/api/v1/…` und `/metrics`), aber nichts ändern – "
      + "das reicht für Monitoring und Diagramme. **lesen und verwalten**: zusätzlich Einstellungen ändern "
      + "und die Zeitdienste neu starten. Gib einem Programm nur so viel Recht, wie es braucht: Gerät ein "
      + "Lese-Schlüssel in falsche Hände, kann damit niemand deine Zeitversorgung verstellen. Passwort und "
      + "Schlüssel selbst lassen sich mit **keinem** Schlüssel verwalten, nur mit Benutzer und Passwort – so "
      + "reicht Widerrufen, um einen entwendeten Schlüssel loszuwerden.",
  },
  api_key_token: {
    title: "Neuer Schlüssel",
    text: "Kopiere ihn jetzt in dein Programm oder einen Passwort-Manager. ntp-gui speichert ihn nicht im "
      + "Klartext und kann ihn dir später nicht noch einmal zeigen. Verloren? Einfach widerrufen und einen "
      + "neuen anlegen.",
  },
  api_key_used: {
    title: "Zuletzt benutzt",
    text: "Wann der Schlüssel zuletzt erfolgreich verwendet wurde (auf etwa eine Minute genau – öfter wird "
      + "nicht gespeichert, um die SD-Karte zu schonen). Ein Schlüssel, der seit Monaten nicht benutzt "
      + "wurde, gehört wahrscheinlich zu einem Programm, das es nicht mehr gibt: widerrufen.",
  },
  api_v1: {
    title: "Versionierte API (/api/v1)",
    text: "Für Skripte gibt es eine stabile Schnittstelle unter `/api/v1`. Was dort steht, ändert sich innerhalb "
      + "von v1 nur so, dass bestehende Skripte weiterlaufen: Es kommen höchstens neue Felder hinzu, nichts "
      + "wird umbenannt oder entfernt. `GET /api/v1` beschreibt alle Endpunkte mit dem nötigen Recht.",
  },
  instance_id: {
    title: "Instanz-Kennung",
    text: "Eine zufällige Kennung dieser Installation. Sie ist bewusst **nicht** aus der Hardware abgeleitet "
      + "(keine MAC-Adresse, keine Seriennummer) und verrät deshalb nichts über dein Gerät oder deinen Ort. "
      + "Sie verlässt die Instanz nie von selbst. „Neu erzeugen“ zieht eine neue – danach lässt sich nichts, "
      + "was du künftig freiwillig teilst, mit früher Geteiltem verknüpfen.",
  },
  settings_notes: {
    title: "Was sich beim Update geändert hat",
    text: "Neue Versionen von ntp-gui bringen deine gespeicherten Einstellungen beim ersten Start automatisch "
      + "auf den neuen Stand. Musste dabei ein Wert geändert oder entfernt werden, steht hier, welcher und "
      + "**warum** – damit nichts stillschweigend anders ist als vorher. „Gelesen“ blendet die Hinweise aus.",
  },
};

export const HELP_GROUP_API = {
  title: "API, Schlüssel und Updates",
  keys: ["api_keys", "api_key_scope", "api_key_token", "api_key_used", "api_v1", "instance_id", "settings_notes"],
};
