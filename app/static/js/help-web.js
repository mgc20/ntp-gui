// Erklärungen zu HTTPS per Reverse Proxy, vertrauenswürdigen Proxys und der Sprache des Dashboards.
// Wird in help.js in HELP übernommen; die Schlüssel stehen gesammelt in HELP_GROUP_WEB.
export const HELP_WEB = {
  https_proxy: {
    title: "HTTPS fürs Dashboard",
    text: "ntp-gui spricht selbst nur HTTP – mit Absicht: Eigenes TLS im Python-Server hätte Fallstricke "
      + "(ein langsamer Handshake blockiert, Zertifikatswechsel), und die meisten Heimnetze haben schon einen "
      + "Reverse Proxy. Ohne HTTPS gehen Passwort (Basic-Auth) und API-Schlüssel **lesbar** durchs Netz. "
      + "Anleitung mit fertigem Compose-Beispiel für Caddy als eigenen Stack: `docs/integrationen/https.md` – "
      + "Caddy holt sich das Zertifikat selbst: im LAN von seiner eigenen Zertifizierungsstelle (`--internal-certs`, "
      + "deren Root-Zertifikat du einmal auf deinen Geräten als vertrauenswürdig einträgst), mit öffentlichem Namen "
      + "per Let's Encrypt. Dazu `WEB_BIND=127.0.0.1`, damit das Dashboard nur noch über den Proxy erreichbar ist, "
      + "und `TRUSTED_PROXIES=127.0.0.1/32,::1/128`. Nginx Proxy Manager, Zoraxy und Traefik gehen genauso – "
      + "ebenfalls in `docs/integrationen/https.md`. Wichtig bei allen: den Host-Kopf unverändert weitergeben, "
      + "sonst lehnt ntp-gui das Speichern ab (Schutz gegen fremde Seiten). Öffnest du das Dashboard über einen "
      + "Namen, der nicht auf .lan, .local, .home.arpa o. Ä. endet, und ohne Passwort, trag ihn unter "
      + "**Erlaubte Namen** ein (oder in `WEB_ALLOWED_HOSTS`). Kommt ein Passwort oder Schlüssel per einfachem HTTP aus dem Netz an, zeigt die "
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
      + "Proxy im Host-Netzwerk auf demselben Rechner: `127.0.0.1/32,::1/128`. Proxy auf einem anderen Gerät: "
      + "dessen feste LAN-Adresse, z. B. `192.168.1.2/32` – nicht das ganze Netz, sonst könnte jedes Gerät im LAN "
      + "eine falsche Adresse vorgeben. Einträge breiter als `/24` (IPv4) bzw. `/64` (IPv6) speichert ntp-gui, "
      + "warnt aber beim Speichern und mit einem Hinweis in der Übersicht. "
      + "**Per Klick eintragen:** Kommen Anfragen mit Proxy-Köpfen von einer Adresse, die hier fehlt, nennt der "
      + "Hinweis „Reverse Proxy erkannt, aber nicht eingetragen“ diese Adresse und bietet „Als vertrauenswürdigen "
      + "Proxy eintragen“ an (nur mit Admin-Recht, mit Rückfrage). Eingetragen wird genau die Adresse, die ntp-gui "
      + "selbst als Gegenstelle gesehen hat – als `/32` bzw. `/128`, nie ein Netz. Läuft der Proxy in Docker mit "
      + "wechselnder Adresse, trag besser eine feste ein (eigenes Netz mit `ipv4_address`).",
  },
  allowed_hosts: {
    title: "Erlaubte Namen (Schutz vor DNS-Rebinding)",
    text: "**Was ist DNS-Rebinding?** Eine fremde Webseite, die du im Browser öffnest, lässt ihren eigenen Namen "
      + "(z. B. `boese.example`) für einen Moment auf die Adresse deines Zeitservers im LAN zeigen. Der Browser "
      + "glaubt, er spreche noch mit derselben Seite, und lässt sie die Antworten lesen – Log, Status, Quellen und "
      + "GPS-Position. Das Einzige, woran ntp-gui das erkennt: Im Kopf `Host` steht der fremde Name. "
      + "Darum beantwortet ntp-gui **ohne Passwort** nur Namen, die es kennt: IP-Adressen, `localhost`, den eigenen "
      + "Hostnamen, einteilige Namen (`raspberrypi`), lokale Endungen (`.lan`, `.local`, `.home.arpa`, `.internal` …), "
      + "den NTS-Namen und die Namen hier. Andere Namen bekommen „Zugriff abgelehnt“. "
      + "Eintragen: einen Namen pro Zeile, z. B. `zeit.example.org`; `*.example.org` erlaubt alle Unternamen "
      + "(und `example.org` selbst). Nicht erlaubt: `*` allein, ganze Endungen (`*.com`, `*.co.uk`), Wildcards auf "
      + "DynDNS- und Hosting-Domains (`*.duckdns.org`, `*.myfritz.net`, `*.github.io` – dort kann sich jeder einen "
      + "Namen holen; trag nur deinen eigenen ein, z. B. `meinzeit.duckdns.org`), IP-Adressen (die gehen "
      + "immer) und Ports. Den Schutz **ganz** abschalten geht nur bewusst mit `WEB_ALLOWED_HOSTS=*` in der "
      + "Compose-Datei. Namen aus `WEB_ALLOWED_HOSTS` gelten zusätzlich; sie stehen unter dem Feld und lassen "
      + "sich nur in der Compose-Datei ändern. "
      + "Mit Passwort ist die Liste egal – dann schützt die Anmeldung, und jeder Name geht. Die Vollbild-Uhr "
      + "`/clock` mit „Vollbild-Uhr ohne Anmeldung“ antwortet ohnehin über jeden Namen. Wirkt sofort, ohne Neustart. "
      + "Tipp: Wurdest du schon abgelehnt, öffne das Dashboard über die IP-Adresse und trag den Namen hier ein.",
  },
  ui_language: {
    title: "Sprache des Dashboards",
    text: "Deutsch oder Englisch – gilt nur in **diesem Browser** (gespeichert im Browser, nicht auf dem Server); "
      + "jeder, der das Dashboard öffnet, wählt selbst. Ohne Wahl gilt immer Deutsch – Englisch ist noch eine Beta und gilt nur, wenn du es ausdrücklich wählst. "
      + "Oben rechts schaltet der Knopf „DE/EN“ dasselbe um. "
      + "Ehrlich zum Stand: Übersetzt sind Navigation, Kopfzeile, das Statusband der Übersicht und die "
      + "Abschnitte der Einstellungen. Alles andere, die ⓘ-Erklärungen und Texte vom Server (Hinweise, Ereignisse, "
      + "Benachrichtigungen) sind vorerst deutsch; fehlt eine englische Übersetzung, steht der deutsche Text da. "
      + "Zahlen behalten das deutsche Format (Komma). Mithelfen: siehe CONTRIBUTING.md („Übersetzen“).",
  },
};

export const HELP_GROUP_WEB = {
  title: "HTTPS, Proxy und Sprache",
  keys: ["https_proxy", "trusted_proxies", "allowed_hosts", "ui_language"],
};
