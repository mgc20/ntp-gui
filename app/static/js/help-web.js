// Erklärungen zu HTTPS per Reverse Proxy, vertrauenswürdigen Proxys und der Sprache des Dashboards.
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in HELP_GROUP_WEB.
export const HELP_WEB = {
  https_proxy: {
    title: "HTTPS fürs Dashboard",
    text: "ntp-gui spricht selbst nur HTTP – mit Absicht: Eigenes TLS im Python-Server hätte Fallstricke "
      + "(ein langsamer Handshake blockiert, Zertifikatswechsel), und die meisten Heimnetze haben schon einen "
      + "Reverse Proxy. Ohne HTTPS gehen Passwort (Basic-Auth) und API-Schlüssel **lesbar** durchs Netz. "
      + "Fertige Vorlage: der auskommentierte Block **[OPTION HTTPS mit Caddy]** in `docker-compose.all-in-one.yml` – "
      + "Caddy holt sich das Zertifikat selbst: im LAN von seiner eigenen Zertifizierungsstelle (`--internal-certs`, "
      + "deren Root-Zertifikat du einmal auf deinen Geräten als vertrauenswürdig einträgst), mit öffentlichem Namen "
      + "per Let's Encrypt. Dazu `WEB_BIND=127.0.0.1`, damit das Dashboard nur noch über den Proxy erreichbar ist, "
      + "und `TRUSTED_PROXIES=127.0.0.1/32,::1/128`. Nginx Proxy Manager, Zoraxy und Traefik gehen genauso – die "
      + "Anleitung steht in `docs/integrationen/https.md`. Wichtig bei allen: den Host-Kopf unverändert weitergeben, "
      + "sonst lehnt ntp-gui das Speichern ab (Schutz gegen fremde Seiten). Öffnest du das Dashboard über einen "
      + "Namen, der nicht auf .lan, .local, .home.arpa o. Ä. endet, und ohne Passwort, trag ihn in "
      + "`WEB_ALLOWED_HOSTS` ein. Kommt ein Passwort oder Schlüssel per einfachem HTTP aus dem Netz an, zeigt die "
      + "Übersicht einen Hinweis (Aufrufe vom Rechner selbst über 127.0.0.1 zählen nicht).",
  },
  trusted_proxies: {
    title: "Vertrauenswürdige Proxys (TRUSTED_PROXIES)",
    text: "Hinter einem Reverse Proxy sieht ntp-gui als Gegenstelle nur den Proxy. Die Adresse des Browsers schreibt der "
      + "Proxy in den Kopf `X-Forwarded-For`, das Protokoll (http/https) in `X-Forwarded-Proto`. Diese Köpfe kann aber "
      + "**jeder** mitschicken. Darum glaubt ntp-gui sie nur Gegenstellen, die hier stehen – Standard: niemandem. "
      + "Mehrere Proxys hintereinander: alle eintragen; ntp-gui liest `X-Forwarded-For` von rechts und nimmt die erste "
      + "Adresse, die kein eingetragener Proxy ist. „all“ und `0.0.0.0/0` lehnt die Prüfung ab. "
      + "Wofür es gut ist: Das Zugriffsprotokoll (`WEB_ACCESS_LOG`) nennt den Browser statt des Proxys, und der "
      + "HTTPS-Hinweis erkennt, ob der Browser verschlüsselt verbunden ist. Wofür **nicht**: Anmeldung, Schutz vor "
      + "DNS-Rebinding und die Prüfung der Herkunft beim Speichern hängen nie an diesen Köpfen. "
      + "Caddy im Host-Netzwerk auf demselben Rechner: `127.0.0.1/32,::1/128`. Proxy auf einem anderen Gerät: "
      + "dessen feste LAN-Adresse, z. B. `192.168.1.2/32` – nicht das ganze Netz, sonst könnte jedes Gerät im LAN "
      + "eine falsche Adresse vorgeben.",
  },
  ui_language: {
    title: "Sprache des Dashboards",
    text: "Deutsch oder Englisch – gilt nur in **diesem Browser** (gespeichert im Browser, nicht auf dem Server); "
      + "jeder, der das Dashboard öffnet, wählt selbst. Ohne Wahl gilt die Sprache des Browsers, sonst Deutsch. "
      + "Oben rechts schaltet der Knopf „DE/EN“ dasselbe um. "
      + "Ehrlich zum Stand (1.5.0): Übersetzt sind Navigation, Kopfzeile, das Statusband der Übersicht und die "
      + "Abschnitte der Einstellungen. Alles andere, die ⓘ-Erklärungen und Texte vom Server (Hinweise, Ereignisse, "
      + "Benachrichtigungen) sind vorerst deutsch; fehlt eine englische Übersetzung, steht der deutsche Text da. "
      + "Zahlen behalten das deutsche Format (Komma). Mithelfen: siehe CONTRIBUTING.md („Übersetzen“).",
  },
};

export const HELP_GROUP_WEB = {
  title: "HTTPS, Proxy und Sprache",
  keys: ["https_proxy", "trusted_proxies", "ui_language"],
};
