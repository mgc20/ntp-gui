# Entscheidungen

Getroffene Entscheidungen zu den offenen Fragen aus den Konzeptdokumenten. Neue
Entscheidungen werden unten angehängt (kurz: Frage, Entscheidung, Begründung, Datum).
Format und Bewertung: siehe [entscheidungsrahmen.md](entscheidungsrahmen.md).

## 2026-11-01

| # | Frage | Entscheidung | Begründung |
|---|---|---|---|
| E1 | Basis-Image | **Umstieg auf Debian 13 „trixie“ als 1.3.1**, direkt nach 1.3.0 | bookworm hat seit 12.07.2026 nur noch LTS-Sicherheitsupdates; trixie bringt chrony 4.6, gpsd 3.25, linuxptp 4.2. Künftige Debian-Versionen zeitnah übernehmen. |
| E2 | Schaltsekunden unter trixie | **Direkt auf `leapseclist /usr/share/zoneinfo/leap-seconds.list`**, `LEAPSECTZ` wird automatisch migriert | trixie hat kein `right/UTC` mehr; ohne Umstellung hätte chrony still keine Schaltsekunden-Daten. Der Container-Test prüft das. |
| E3 | Umfang 1.4 | **Schlanke 1.4** (~6–8 Wochen), danach 1.4.x / 1.5 in kurzen Abständen | Häufige, kleine Releases sind für einen Maintainer besser beherrschbar. |
| E4 | Home Assistant | **Zuerst Dokumentation (REST-Sensor)**, MQTT erst auf Nachfrage | keine neue Abhängigkeit, nichts geht nach draußen |
| E5 | HTTPS fürs Dashboard | **Nur Reverse Proxy dokumentieren** (NPM, Zoraxy, Traefik, Caddy) | Eigenbau hätte Fallstricke (Handshake blockiert den Server, Zertifikatswechsel); Proxys sind meist schon vorhanden. |
| E6 | E-Mail-Benachrichtigung | **Über Apprise-API** (optionaler Zusatzcontainer), kein eigener SMTP-Kanal | deckt E-Mail, Telegram, Matrix, Gotify u. v. m. ab, ohne eigenen Code |
| E7 | Uhr-Vollbildansicht ohne Login | **Als Option, standardmäßig aus** | nützlich für Rack-Monitore; nur lesend, ohne Konfigurationsdaten |
| E8 | Bewertungsformel | **„OSS teilweise“ zählt +0,5** | spiegelt den geringeren, aber vorhandenen Nutzen von Wiederverwendung |
| E9 | Ausstiegsplan | **Jede Entscheidung für ein Fremdprojekt nennt in einer Zeile, was passiert, wenn es eingestellt wird** | Beispiel Watchtower (2025 archiviert) |
| E10 | Öffentliche Community-Dienste (Impressum, VPS-Kosten) | **Nicht grundsätzlich ausgeschlossen** – wird je Stufe entschieden | Bis dahin: Stufen ohne eigenen öffentlichen Server zuerst (Hardware-Liste über GitHub). |
| E11 | Sprache des Server-Tests | **Go mit bewährter NTS-Bibliothek** (gepinnt und mitgeliefert) | eigener NTS-Client wäre riskant und aufwendig |
| E12 | Schwarm Stufe A | **Ohne Laufzeitwerte** | mehrere Laufzeiten würden die Region verraten |
| E13 | Schwarm Stufe B (regional) | **Frühestens nach einem Jahr Stufe A neu bewerten** | Datenschutz und Datenqualität erst mit Erfahrung beurteilbar |
| E14 | Website-Hosting | **GitHub Pages für statische Teile**, eigener VPS nur für den Messpunkt | minimaler Betrieb, kein eigener Webserver für Inhalte |

## 2026-11-02

Antworten des Maintainers auf die offenen Fragen aus [version-1.5.md](version-1.5.md#5-offene-fragen-an-den-maintainer).

| # | Frage | Entscheidung | Begründung |
|---|---|---|---|
| E15 | F1 – Schnitt 1.5 | **Schlankes 1.5.0, danach nach und nach 1.5.x** | wie E3 – kurze Abstände, jedes Release für sich fertig |
| E16 | F4 – GPS ohne PPS standardmäßig „nur beobachten“? | **Nein.** GPS ohne PPS bleibt Zeitquelle, aber als **Rückfallebene**: ntp-gui gibt ihm eine ehrliche Fehlerschranke (aus der gemessenen Streuung, z. B. ± 60 ms), sodass chrony gute Internetquellen vorzieht und GPS automatisch nimmt, wenn das Internet schlecht oder weg ist (Mobilfunk, Störung, Insel). „Nur beobachten“ bleibt eine Wahl im Dashboard, kein Standard und kein automatischer Vorschlag. | Einwand des Maintainers: Bei Mobilfunk-Internet (große Laufzeitschwankungen, Ausfälle) ist das GPS oft die bessere oder einzige Quelle. Fehlerhaft war nicht die Rolle, sondern die zu kleine Fehlerschranke (`delay 0.03` bei ± 60 ms Streuung) – dadurch wählte chrony das GPS zeitweise als Referenz, obwohl gute NTS-Quellen da waren. |
| E17 | F12 – VPS für Community-Dienste | **Start mit einem VPS**, ein zweiter ist möglich, aber nicht eingeplant | genug für Website + Server-Test; ein zweiter Standort erst, wenn der Betrieb ruhig läuft |
| E18 | F16 – Abstimmung mit ntp-tester.eu | **Eigene Lösung bauen, ohne Abhängigkeit.** Eine freundliche Kontaktaufnahme ist möglich, aber keine Voraussetzung. | Die Frage war nicht „bauen oder nicht“, sondern ob man sich vorher abstimmt. Ziel bleibt eine eigene Website mit mehr Möglichkeiten (Server-Test, Erklärseiten, Anbindung an ntp-gui). |

## 2026-11-04

| # | Frage | Entscheidung | Begründung |
|---|---|---|---|
| E19 | GPS-Automatik standardmäßig an? | **Ja, ab 1.5.2 ist `GPS_AUTOCAL=auto` der Standard.** Wer „vorschlagen“ oder „aus“ ausdrücklich gespeichert hat oder `GPS_AUTOCAL` setzt, behält es; alle anderen bekommen „automatisch“ (ein Hinweis unter „Was sich beim Update geändert hat“, wenn GPS an ist). Ohne Zutun heißt: Die Messung beginnt von selbst neu nach einer Offset-Änderung, einem anderen Empfänger (Gerät, Name, PPS) und „Neu lernen“ bei den GNSS-Störungen; die Fehlerschranke wartet auf die Korrektur, statt vorher einen eigenen Neustart von chronyd auszulösen. **Grenzen:** Bei einer GNSS-Warnung/-Störung im Messzeitraum entscheidet ein Mensch (die GPS-Seite sagt, was zu tun ist); mit PPS oder Rolle „bevorzugen“ bleibt es bei höchstens 5 ms je 24 h; mit weniger als zwei NTS-Quellen gibt es keinen Schritt in einem Zug; nach einer Rücknahme 24 h Pause; ein Tausch des Empfängers am selben Gerätepfad wird erst über das gleitende 24-h-Fenster (bis etwa einen Tag) oder mit „Neu lernen“ erkannt. | Wunsch des Maintainers: „eine Automatik, die funktioniert und mehr oder weniger ohne Zutun läuft“. „Vorschlagen“ verlangte von jeder Installation einen Klick, den die meisten nie machen – das GPS blieb dann mit ± 100 ms unkalibriert. Die Sicherheitsregeln (Störungssperre, kleine Schritte mit PPS, Rücknahme, Protokoll) stammen aus 1.5.1 und bleiben unverändert; eine Simulation über drei Tage (VK-162: +51 ms, ± 4 ms Tagesgang, Fix-Flattern, fünf NTS-Quellen) zeigt: Korrektur nach 7 h, Rest nach 31 h, zwei Neustarts von chronyd, keine Warnung, kein Pendeln, Fehlerschranke ± 16 ms. |
