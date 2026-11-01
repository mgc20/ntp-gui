# Entscheidungsrahmen

Stand: 01.11.2026

Dieser Rahmen macht die Grundsätze des Maintainers prüfbar. Er ersetzt keine Abwägung im
Einzelfall – der Maintainer möchte ausdrücklich **möglichst viel Funktion** –, aber er sorgt dafür,
dass jede Funktion dieselben Fragen beantwortet, bevor Code entsteht.

## 1. Die Grundsätze

1. **Größter Nutzen für die Community.** Was viele Installationen sofort nutzen, kommt vor dem,
   was wenige Spezialisten brauchen. Erklärwert zählt mit: ntp-gui ist ein Zeitserver, der sich
   selbst erklärt.
2. **Überschaubarer Aufwand für einen Maintainer.** Bezahlt wird nicht nur das Bauen, sondern
   vor allem die **Pflege**: Tests, ⓘ-Texte, README, Fehlerberichte, Sicherheitsupdates – über Jahre.
3. **Sicherheit durch Einfachheit.** Weniger Code, weniger Abhängigkeiten, weniger offene
   Ports, weniger Rechte. Was nicht da ist, kann nicht angegriffen werden.
4. **Open Source wiederverwenden.** Bewährte Projekte tragen ihre eigene Pflege und ihre eigenen
   Sicherheitsupdates. Das spart Aufwand und erhöht die Sicherheit – *wenn* das Projekt gepflegt
   ist und nicht mehr mitbringt, als gebraucht wird.
5. **Datenschutz.** Alles, was die Instanz verlässt, ist **opt-in**, **nur ausgehend**, läuft
   durch den **zentralen Filter** (`app/egress.py`: `sanitize` → `check_no_leaks`) und erlaubt
   **keine Ortsbestimmung**. Vor jedem Export gibt es eine Vorschau.

## 2. Bewertung (fünf Fragen)

| Kriterium | Skala | Leitfrage |
|---|---|---|
| **Nutzen** | 1–3 (★) | Wie viele Installationen profitieren, wie sehr? Löst es ein Problem, das heute in Issues/Foren auftaucht? |
| **Aufwand** | 1–3 (◆) | Bauen *und* zwei Jahre pflegen, inkl. Tests, Erklärtexte, Doku. Wie gut ist es automatisch testbar (Replay, Container-Test)? |
| **Risiko** | 1–3 (R) | Neue Angriffsfläche (Port, Parser für fremde Eingaben, Rechte), Schreibzugriff auf Hardware oder Uhr, ausgehende Daten |
| **OSS-Wiederverwendung** | ja / teilweise / nein | Erledigt ein gepflegtes Projekt den schwierigen Teil? |
| **Datenschutz-Relevanz** | keine / 🔒 | Verlässt etwas die Instanz? Wenn ja: welcher Zweck im Filter, welche Felder, welche Vorschau? |

**Faustformel für die Reihenfolge:** `Nutzen × 2 − Aufwand − Risiko`, plus 1 bei „OSS: ja“.
Das ist eine Sortierhilfe, kein Urteil. Beispiel: Benachrichtigungen 3·2 − 1 − 2 + 1 = **4**,
u-blox schreiben 2·2 − 3 − 3 + 1 = **−1** → später und behutsam.

**Wert ≥ 3:** nächste Version. **1–2:** einplanen, wenn Fundamente stehen. **≤ 0:** nur mit
gutem Grund (z. B. viele Nachfragen) und dann in kleinster Form (nur lesen, nur Doku, experimentell).

## 3. Faustregeln

| Regel | Bedeutung | Ausnahme |
|---|---|---|
| **Debian-Paket vor pip vor Eigenbau** | Ein Paket aus Debian bekommt Sicherheitsupdates über das Image, ohne unser Zutun. pip-Pakete pinnen und überwachen wir selbst. Eigenbau pflegen wir ganz allein. | Eigenbau, wenn er sehr klein ist (≲ 50 Zeilen, stdlib) und das Paket viel mehr mitbrächte als nötig (z. B. Webhook statt Apprise). |
| **Standardbibliothek vor Fremdpaket** | Das Dashboard ist heute reine Python-stdlib. Jede neue Python-Abhängigkeit braucht eine Begründung. | Protokollcode, der fremde Eingaben parst (z. B. MQTT), ist im bewährten Paket sicherer als im eigenen. |
| **Optionaler Sidecar statt im Image** | Was nur ein Teil der Nutzer braucht und viele Abhängigkeiten hat, läuft als eigener, offizieller Container daneben (Apprise-API, Caddy, keepalived). ntp-gui spricht ihn über eine schmale Schnittstelle an (HTTP, Healthcheck). | Wenn es ohne Sidecar gar nicht ginge und das Paket klein ist (z. B. `python3-gps` für `ubxtool`). |
| **Lesend vor schreibend** | Erst anzeigen und erklären, dann vorschlagen, erst zuletzt automatisch ändern – immer umkehrbar (Muster der GPS-Kalibrierung: aus / vorschlagen / automatisch). | – |
| **Opt-in** | Alles, was nach außen spricht oder Hardware bzw. Uhr beeinflusst, ist standardmäßig aus. | Rein lokale Anzeigen dürfen standardmäßig an sein. |
| **Eine Tür nach draußen** | Jede ausgehende Verbindung läuft über *ein* Modul mit Filter, Timeout, Größenlimit, ohne automatische Weiterleitungen, und taucht in der Übersicht „ausgehende Verbindungen“ auf. Kein Modul öffnet eigene Sockets nach außen. | – |
| **Kein eingehender Port für Dienste** | Keine Instanz muss für einen Community-Dienst erreichbar sein. | Der NTP/NTS-Server selbst (das ist der Zweck). |
| **Eine Quelle der Wahrheit** | chrony entscheidet über die Zeit, gpsd über GPS, ptp4l über PTP. ntp-gui liest, erklärt und schreibt Konfiguration – es rechnet nicht selbst an der Uhr. | – |
| **Testbar oder nicht gebaut** | Jede Funktion braucht einen automatischen Test (Unit, Replay-Aufzeichnung aus 1.3 oder Container-Test). Hardwareabhängiges ohne Testmöglichkeit kommt nur als „experimentell“. | – |
| **Erklären gehört dazu** | Jede neue Anzeige bekommt eine ⓘ-Erklärung; ehrliche Grenzen stehen darin. | – |

## 4. Wann „nein“ (oder „nicht jetzt“)

- Die Funktion braucht einen **eingehenden Port** oder einen **Dienst des Maintainers**, damit die Instanz funktioniert.
- Sie erlaubt – auch indirekt, durch Kombination – eine **Ortsbestimmung** oder dauerhafte Wiedererkennung einer Instanz.
- Sie zieht eine **große Abhängigkeitskette** ins Image (Faustwert: > 5 MB oder > 3 neue Pakete) für einen Nutzen, den nur wenige haben → Sidecar oder Doku.
- Das Fremdprojekt ist **nicht mehr gepflegt** oder hat einen Bus-Faktor von 1 *und* wäre schwer zu ersetzen.
  Beispiel: Watchtower wurde am 17.12.2025 archiviert – Empfehlungen in der Doku müssen bei jedem
  Release kurz gegengeprüft werden (Archiv-Status, letztes Release).
- Sie **schreibt auf Hardware oder die Uhr**, ohne dass es einen Weg zurück gibt.
- Sie ist **nicht testbar** und nicht klar als experimentell abgrenzbar.
- Sie dupliziert, was ein Werkzeug des Nutzers schon gut kann (Prometheus/Alertmanager, Diun/WUD, Reverse Proxy) → Doku statt Code.

„Nein“ heißt selten „nie“. Oft lautet die Antwort: **als Doku**, **als Sidecar** oder **nur lesend**.

## 5. Entscheidungen festhalten (kurz-ADR)

Entscheidungen mit Folgen für Abhängigkeiten, Sicherheit oder Datenschutz bekommen einen Eintrag –
entweder als Abschnitt im jeweiligen Konzeptdokument oder als Datei `docs/konzept/adr/NNNN-titel.md`.
Fünf bis fünfzehn Zeilen genügen.

```markdown
# NNNN – <Entscheidung in einem Satz>

- Stand: JJJJ-MM-TT · Status: vorgeschlagen | entschieden | abgelöst durch NNNN
- Bewertung: Nutzen ★★ · Aufwand ◆ · Risiko R1 · OSS: ja · 🔒 nein

## Kontext
Welches Problem, für wen? Was gibt es schon?

## Entscheidung
Was wir tun – und was ausdrücklich nicht.

## Abwägung
Optionen mit je einem Satz Pro/Contra. Warum diese?

## Folgen
Neue Pakete, neue Rechte, neue Tests, Doku. Wann überprüfen wir die Entscheidung?
```

## 6. Beispiele aus dem Projekt

### 6.1 chrony statt eigener NTP-Implementierung
- **Kontext:** Ein Zeitserver braucht NTP-Server, NTS, Quellenauswahl, Regelung der Uhr, PPS- und GPS-Anbindung.
- **Entscheidung:** chrony macht all das; ntp-gui erzeugt nur die Konfiguration (`confgen.py`) und liest `chronyc` aus.
- **Abwägung:** Eigene NTP-Logik wäre die riskanteste denkbare Stelle (öffentlicher UDP-Port, Kryptografie, Zeitregelung). chrony ist Debian-Standard, hat NTS, `ratelimit`, beantwortet kein Mode 7 und ist sehr aktiv gepflegt.
- **Folge:** Neue Fähigkeiten zuerst in chrony suchen – z. B. `tempcomp` (Temperaturausgleich), `selectopts` (Quelle zur Laufzeit sperren, ab 4.4), `leapseclist` (ab 4.6). Bewertung: Nutzen ★★★ · Aufwand ◆ · R1 · OSS ja.

### 6.2 Webserver aus der Python-Standardbibliothek
- **Kontext:** Das Dashboard braucht HTTP, JSON-API, Anmeldung.
- **Entscheidung:** `http.server` (`ThreadingHTTPServer`), keine Frameworks, keine pip-Pakete.
- **Abwägung:** Flask/FastAPI wären bequemer, bringen aber eine Abhängigkeitskette, die wir pinnen und überwachen müssten. Das Dashboard ist für das LAN gedacht; für Internet-Exposition gibt es die Reverse-Proxy-Anleitung aus 1.2. Nachteil: Routing, Sicherheits-Header und Größenlimits bauen wir selbst – das ist überschaubar und getestet.
- **Folge:** Neue Funktionen dürfen „nur stdlib“ nur mit Begründung verlassen (z. B. MQTT, siehe [version-1.4.md](version-1.4.md#22-mqtt-und-home-assistant)). HTTPS bleibt opt-in über `ssl` oder Reverse Proxy.

### 6.3 GitHub-Issues für die Hardware-Kompatibilitätsliste
- **Kontext:** Die Community soll Hardware-Erfahrungen teilen; daraus entstehen Start-Offsets für GPS-Empfänger.
- **Entscheidung:** Der Bericht wird lokal erzeugt, gefiltert und in der Vorschau gezeigt. Der **Browser** öffnet ein vorausgefülltes Issue-Formular; eine GitHub Action prüft, der Maintainer gibt per Label frei.
- **Abwägung:** Ein eigener Upload-Server wäre anonymer, aber Server-Code, Betrieb, Spam-Abwehr und Datenschutzerklärung. GitHub kostet nichts und hat Moderation eingebaut. Nachteil: Der Bericht hängt öffentlich am GitHub-Konto des Nutzers – das steht in der Vorschau.
- **Folge:** Die Instanz baut selbst **keine** Verbindung auf. Bewertung: ★★★ · ◆ · R1 · OSS ja · 🔒.

### 6.4 Kein eigenes NTP-Relay bzw. keine eigene Zeitquelle in der Cloud
- **Kontext:** Idee: Instanzen holen Zeit über einen Dienst des Projekts oder melden sich dort an.
- **Entscheidung:** Nein. Instanzen nutzen öffentliche Quellen (PTB, Netnod, Cloudflare, Pool) direkt. Das Projekt trägt stattdessen *eigene Server zum NTP Pool* bei.
- **Abwägung:** Ein Relay schafft einen zentralen Ausfallpunkt, eine Datenspur aller Instanzen und Betriebsaufwand – ohne Gewinn an Genauigkeit.
- **Folge:** Community-Dienste sind immer *zusätzlich* und freiwillig; ntp-gui funktioniert ohne sie vollständig.

### 6.5 SQLite als Datenspeicher (1.3)
- **Kontext:** Ereignisse, Verlauf, versionierte Einstellungen, API-Schlüssel.
- **Entscheidung:** SQLite über das Python-Modul `sqlite3` (stdlib), eine Datei unter `/config`.
- **Abwägung:** JSON-Dateien skalieren nicht für Verlauf und brauchen eigenes Locking. Eine Zeitreihen-DB (InfluxDB, Prometheus) wäre ein weiterer Dienst. SQLite ist in der stdlib, transaktionssicher, mit `sqlite3`-CLI inspizierbar und sehr gut gepflegt.
- **Folge:** Migrationen sind versioniert; Allan-Abweichung und Temperatur-Fit in 1.4 lesen ihre Daten von hier.

### 6.6 Benachrichtigungen: eigener Webhook statt Apprise im Image
- **Kontext:** Nutzer wollen Alarme auf Handy, Matrix, Telegram, E-Mail.
- **Entscheidung:** Webhook, ntfy, Gotify und E-Mail mit stdlib (je 20–40 Zeilen). Für die über 100 weiteren Dienste: Doku zum **Apprise-API-Container als Sidecar**, angesprochen über den Webhook.
- **Abwägung:** Apprise (BSD-2, sehr aktiv) bringt requests, urllib3, requests-oauthlib, click, markdown, PyYAML mit. Im Image wäre das für die meisten Nutzer Ballast mit eigener CVE-Historie. Als Sidecar bekommt, wer es will, die volle Vielfalt.
- **Folge:** ★★★ · ◆ · R2 · OSS teilweise · 🔒 (Ereignistexte laufen durch den Filter).

## 7. Offene Fragen

1. **OSS-Bonus bei „teilweise“:** Die Faustformel gibt +1 nur bei „OSS: ja“; das Beispiel
   Benachrichtigungen (6.6, „OSS teilweise“) rechnet trotzdem +1. Festlegen: +1 nur bei „ja“
   (dann Wert 3) oder +0,5 bei „teilweise“?
2. **Pflegekosten sichtbar machen:** Soll jede ADR eine Zeile „Was passiert, wenn das
   Fremdprojekt eingestellt wird?“ bekommen (Ausstiegsplan)? Kostet zwei Minuten, hätte bei
   Watchtower und Promtail geholfen.
