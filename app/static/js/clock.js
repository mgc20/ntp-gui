// Vollbild-Uhr (/clock): große Uhrzeit, abgeglichen mit der Serveruhr statt der Browseruhr.
//
// Die Browseruhr eines Tablets kann Sekunden danebenliegen. Darum misst die Seite den Versatz
// zum Server mit vier Zeitstempeln (clocksync.js) – fünf Messungen, die mit der kleinsten
// Laufzeit gewinnt – und zeigt Serverzeit an. Alle 60 s wird neu gemessen, alle 5 s der
// Zustand abgefragt (mit ?signal=1 jede Sekunde). Antwortet der Server 10 s lang nicht, wird die Ampel grau.
//
// 1.6 (T6) „Uhr-Werkstatt“: vier Designs (Bahnhofsuhr, Nixie, Klappzahlen, Wortuhr) neben der
// digitalen Anzeige, Kiosk (?kiosk=1), E-Ink (?eink=1), zweite Zeitzone (?tz=), Ton auf der Sekunde
// und „Wie falsch geht dein Gerät?“. Die reinen Rechnungen stehen in clockkit.js. Bewegung macht CSS
// (Sekundenzeiger, Klappen, Glühen); JS stellt nur einmal je Sekunde (E-Ink: je Minute) die Anzeige.
// Der gemessene Versatz der Browseruhr bleibt im Browser: nicht gespeichert, nicht gesendet.
//
// Studiouhr (Etappe A1): Die Anzeige rechnet mit einem Anker aus der besten Messung und der monotonen
// Uhr performance.now() (kit.anchoredNow), nicht mit Date.now() + Versatz. Verstellt das Gerät seine Uhr,
// springt die Anzeige nicht mit. Neu gemessen wird beim Zurückkommen (visibilitychange), wenn ein Takt
// mehr als 2 s zu spät kommt, und wenn Geräteuhr und performance.now() seit dem Anker um mehr als 2 s
// auseinanderlaufen (kit.wallJump: Standby auf Plattformen, deren monotone Uhr im Schlaf steht, oder verstellte
// Geräteuhr). Bis zum neuen Anker gilt die Anzeige dann als unsicher, ohne Schranke. Die Fehlerschranke (kit.errorBound) bestimmt data-sync am Root
// (ok|free|degraded|none, sichtbar als Text mit Symbol) und graut Stellen aus, die sie nicht trägt.
// ?lead=0..200 lässt die Anzeige so viele ms vorlaufen (Bildprozessor im Fernseher); der Ton bleibt exakt.
//
// Studiouhr A3/A4: Die Bühne (.clock-stage um main, container-type: size) wählt ihr Layout aus ihrer eigenen Größe
// (kit.resolveLayout, gesetzt als data-layout per ResizeObserver; ?layout= übersteuert). Sicherheitsrand (?safe=),
// Größe (?scale=), Schriftstärke (?weight=), Hintergrund (?bg=), sichtbare Elemente (?show=) und Pixel-Shift (?shift=,
// acht Klassen im 2-min-Takt) kommen nur über data-Attribute, Klassen und CSSOM-Variablen – nie über style-Attribute.
// Design studio und digital mit face=seg zeichnen 7-Segment-Ziffern als SVG (clockfaces.js). Themen (?look=) stehen
// in clock.css, Akzent- und Ziffernfarbe (?accent=, ?color=) setzt clock.js nach Kontrastprüfung (≥ 4,5:1) per
// documentElement.style.setProperty. Bewegung gibt es nur als Klassenwechsel je Sekunde.
//
// Studiouhr A5: Countdown und Count-up (clockcount.js). ?until= rechnet auf der korrigierten Serverzeit in der
// Zeitzone des Servers (zone aus /api/v1/time) – alle Bildschirme zeigen dasselbe, ohne Steuerkanal. ?timer= und die
// Stoppuhr (Leertaste ohne Ziel) laufen lokal als Zustandsautomat auf performance.now(). Farbstufen (?warn=) immer mit
// Symbol und Text, ?beep= über denselben Tonweg wie „Ton auf der Sekunde“ (kit.audioClock, kit.scheduleTone).
// Tastenkürzel F, D, L, U, T, O, Leertaste/R, +/−, A und ? (Übersicht); ?lock=1 schaltet sie ab.
//
// Studiouhr A6: Panel „Anpassen“ (Formular aus dem Schema, clocklink.js). Übernommen wird in den localStorage; der
// Stand gilt, wenn /clock ohne Parameter aufgerufen wird. ?p=name lädt ein Profil vom Server (GET
// /api/v1/clock/profile, Rangfolge Profil < Adresse). /api/v1/time meldet profiles_rev: Ändert sich der Wert, holt
// die Seite ihr Profil beim nächsten Abgleich neu und lädt sich neu, wenn sich daran etwas geändert hat. Scheitert
// der Abruf (Netz, 5xx, 401), versucht sie es mit wachsendem Abstand (5 s bis 60 s) erneut und lädt sich nach dem
// ersten Erfolg neu; bis dahin läuft die Standarduhr, nicht der im Panel gemerkte Stand.
//
// Studiouhr B1: Design tc (clocktc.js) zeigt die Tageszeit als Timecode HH:MM:SS mit Feinstelle – Zehntel als Standard,
// Frames nur mit ?sub=frames oder Taste T, bei 29,97/59,94 fps in Drop-Frame-Zählweise. Gerechnet wird in der Zeitzone
// des Servers. Nur hier läuft eine Bildschleife (rAF in tcLoop), und nur solange eine Feinstelle sichtbar ist; alles andere bleibt
// im Sekundentakt. Die Kopfzeile „Anzeige-Timecode – nicht genlocked“ steht immer da. Trägt die Fehlerschranke die
// Feinstelle nicht oder rundet der Browser seine Zeitgeber grob, wird sie grau (mit Text), über ?maxerr= verschwindet
// sie. E-Ink zeigt keine Feinstelle, bei „weniger Bewegung“ gibt es höchstens Zehntel.
//
// Studiouhr B2: Weltzeit (clockworld.js). ?tz= nennt bis zu sechs Zonen (kommagetrennt oder mehrfach), ?tzl= Kurznamen
// dazu. Eine Zone steht wie bisher als zweite Zeitzone in der Zeile unter der Uhr; ab zwei Zonen gibt es eine Leiste
// (#world) mit Uhrzeit, Abweichung zur großen Zeit, Tageswechsel und Tag/Nacht-Symbol (mit Text-Alternative), mit
// ?layout=world ein Raster als Hauptinhalt. Gezeichnet wird einmal je Minute. Die Leiste belegt je Layout höchstens
// world.worldLines Zeilen; Zonen, die nicht passen, blendet trimWorld aus („+2“), im Streifen und in der Kachel fehlt sie
// ganz. Das Raster wird wie die Zeit eingepasst (--world-fit); würde die Schrift dabei kleiner als 12 px, stehen die
// Zellen einzeilig, auf Flächen, die höher als breit sind, als eine Spalte; danach fallen Zonen vom Ende her weg
// (fitGrid). Passt keine einzige, steht die Uhr im automatischen Layout (fitTime); ebenso, wenn ?show= die Weltzeit
// nicht nennt. Wo unter der Uhr Höhe frei ist, wächst die Leiste (growBar, --world-grow). Mit ?h12=1 stehen auch die
// Zonen zwölfstündig mit AM/PM.
//
// Studiouhr B3: Statuszeile. /api/v1/time meldet ptp_state (fester Wert) und holdover (mit Dauer); das Band zeigt beides
// als Marke mit Symbol und Text (kit.statusChips – nur feste Werte, nie Text aus der Antwort), ?show= ohne „status“
// blendet sie aus. In der Kachel (?layout=tile, ohne Kopfzeile und Band) steht der Titel des Profils oben links, ein
// Holdover als Symbol neben dem Zustandssymbol, der Countdown mit dem Symbol seiner Stufe.
//
// Studiouhr B5: Prüfbild ?test=sync zum Einmessen von ?lead=. Eine Fläche wechselt genau zur vollen Sekunde der
// angezeigten Zeit zwischen hell und dunkel (ein Wechsel je Sekunde, eigener Zeitgeber auf die Sekundengrenze), dazu
// auf Wunsch ein Klick auf der wahren Sekunde über denselben Tonweg wie „Ton auf der Sekunde“. Es startet nur mit dem
// Parameter in der Adresse (kit.testMode liest window.location, nie Profil oder gemerkten Stand), nicht bei „weniger
// Bewegung“ und nicht auf E-Ink (dann nur ein Hinweistext). Der Warnhinweis steht immer da, Esc beendet – auch mit lock=1.
// /clock?test=sync misst die Anzeige ein, die der Bildschirm sonst zeigt: Der gemerkte Stand bleibt die Grundlage, ein
// dort eingemessener Vorlauf wird beim Beenden gemerkt (sonst steht er als lead= in der Adresse). Solange das Prüfbild
// die Bühne verdeckt, ist die Uhr dahinter inert und ihre Tastenkürzel ruhen (nur Hilfe, Vollbild und Esc).
//
// Studiouhr B4: On-Air/REC-Signal. /api/v1/time meldet signal (off, on_air, rec) und signal_rev. Nur mit ?signal=1 (Adresse
// oder Profil) zeigt dieser Bildschirm das zentrale Signal und fragt dafür jede Sekunde ab, sonst bleibt es bei 5 s.
// Gezeigt wird ein Rahmen um die ganze Seite und ein Balken mit Symbol und Text über der Bühne (kit.signalView) – ohne
// Blinken, nie nur als Farbe. Die Taste O schaltet ein lokales „On Air“ nur auf diesem Gerät (nichts wird gesendet);
// das zentrale Signal geht vor. Antwortet der Server nicht mehr, bleibt der letzte Zustand stehen und ist als ungewiss
// markiert. Es ist eine gespiegelte Anzeige mit bis zu etwa 1 s Verzögerung, kein Tally.
//
// Studiouhr C1: Spielereien (clockextras.js). Panel „Timer“ mit Eieruhr (Schnellwahl, eigene Dauer, „+1 min“ am
// Countdown, deutliches Ende, Ton am Ende nur nach Klick), Pomodoro (?pomo=, ?pause=; Arbeit und Pause wechseln von selbst,
// Zähler), eigene Countdowns (bis zu fünf im localStorage, öffnen als /clock?until=…&label=…) und eingebaute (?goal=:
// Neujahr, Zeitumstellung, Unixzeit 2 000 000 000, NTP-Ära 2036 – auf der Serverzeit wie ?until=). Nachtmodus: gedimmt
// (data-mode="night", --night per CSSOM) bzw. mit ?dimred=1 im Rotlicht, nach Uhrzeit (?dim=22-6) und von Hand (Knopf
// „Nacht“, Taste N; gilt bis zum nächsten Wechsel des Zeitplans). Die Knöpfe gibt es nur, wo jemand davorsitzt
// (fx.funControls): nicht mit fun=0, lock=1, im Kiosk, in der Kachel und in einer OBS-Browserquelle (window.obsstudio).
// Timer-Stände bleiben im Browser; es gibt keinen neuen Weg zum Server.
//
// Studiouhr C2: Design binary (Lämpchen, ?bin=bcd|plain) und Zusätze unter der Uhr, alle Standard aus und nur mit ?show=
// (moon, nerd, progress; fx.mergeShow trennt sie von den Grundelementen): Mondphase (rein rechnerisch, Klick spiegelt sie
// für die Südhalbkugel, nur localStorage), Nerd-Zeile (Unix, TAI und GPS mit tai_utc aus /api/v1/time, MJD, Tag im Jahr,
// ISO-Woche, hex, römisch) und Fortschrittsbalken (?bars=). Nie mit fun=0, im Kiosk, in Kachel und Streifen
// (fx.extrasShown); im Banner ohne Platz fallen sie weg (checkExtrasRoom). Mond und Kalender-
// Balken ändern sich einmal je Minute, Nerd-Zeile und Eieruhr-Balken im Sekundentakt – ohne eigenen Zeitgeber.
//
// Bewusst ohne app.js/ui.js: Die Seite muss auch ohne Anmeldung (clock_public) laufen und
// lädt deshalb nur Dateien, die keine Inhalte aus Konfiguration oder Status enthalten
// (clocksync.js, clockkit.js, clocktc.js, clockworld.js, util.js, i18n.js und die Sprachkataloge).
import { fromResponse, best, isoWeek, hms, fmtAccuracy, sourceText } from "./clocksync.js";
import { initI18n, t, language } from "./i18n.js";
import { svgEl } from "./util.js";
import * as kit from "./clockkit.js";
import * as faces from "./clockfaces.js";
import * as cd from "./clockcount.js";
import * as link from "./clocklink.js";
import * as tc from "./clocktc.js";
import * as world from "./clockworld.js";
import * as fx from "./clockextras.js";
import { copyText } from "./util.js";

const BURST = 5;
const BURST_GAP_MS = 250;
const RESYNC_MS = 60_000;
const STALE_MS = kit.STALE_MS;
const FRAME_SAMPLES = 6;
const TIMEOUT_MS = 4_000;
const IDLE_MS = 4_000;
const DESIGN_KEY = "ntp-gui-clock-design";
const HINT_MS = 2_000;
const TC_GONE_MS = 3000;   // so lange bleibt der Platz einer ausgeblendeten Timecode-Feinstelle frei, dann rückt die Zeit zur Mitte
const WORLD_FIT_OK = 0.6;   // Leiste der Weltzeit: so weit darf sie die Zeit ohne Vergleich verkleinern
const WORLD_FIT_SHARE = 0.7;   // sonst mindestens dieser Anteil der Größe, die die Zeit ohne Leiste hätte
const WORLD_MIN_PX = 12;   // Raster der Weltzeit: kleinste Schrift; darunter erst einzeilige Zellen, dann weniger Zonen
const GRAIN_STEP_MS = 1;   // Abstand der Messwerte, mit denen das Raster von performance.now() bestimmt wird
// Art des Countdowns: absolutes Ziel (?until=, synchron auf allen Bildschirmen), lokaler Timer (?timer=) oder
// Stoppuhr (ohne beides, Start mit der Leertaste).

const $ = (id) => document.getElementById(id);
const root = document.documentElement;
const ZONES = kit.supportedZones();
const PROFILE = link.profileFromSearch(window.location.search);
// Startwerte aus der Adresse bzw. dem gemerkten Stand; ein Profil (?p=) kommt in start() dazu (Object.assign).
const params = kit.parseParams(link.effectiveQuery({ search: window.location.search, stored: store(link.STORE_KEY) || "",
  zones: ZONES }), ZONES);
// OBS Studio legt in seiner Browserquelle window.obsstudio an: Dort sieht niemand Knöpfe, also keine Bedienung.
const OBS = typeof window.obsstudio === "object" && window.obsstudio !== null;
const reducedMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
const state = {
  sync: null,          // beste Messung der letzten Runde {offset, rtt, accuracy, at, perf}
  anchor: null,        // { server, perf } aus dieser Messung – Grundlage der Anzeige
  frameMs: kit.FRAME_MS,
  planned: null,       // { perf, delay } des nächsten Takts (Lücke erkennen)
  bursting: false,
  jumped: false,       // Geräteuhr und monotone Uhr seit dem Anker auseinander: unsicher bis zum nächsten Anker
  syncKey: "",
  bandSync: "",        // Zustand der Zeitbasis beim letzten Zeichnen des Bands
  status: null,        // letzte Antwort von /api/v1/time
  lastOk: 0,           // performance.now() der letzten erfolgreichen Antwort
  error: "",
  wake: null,
  wakeText: "",
  design: kit.DEFAULT_DESIGN,
  face: null,          // Teile des aktuellen Designs
  tone: null,          // { ctx, mode, last, exact }
  tickTimer: null,
  layout: "",          // aufgelöstes Layout der Bühne (data-layout)
  stage: { width: 0, height: 0 },
  shift: -1,           // aktuelle Pixel-Shift-Klasse
  minuteKey: "",       // für die Auto-Anpassung der Zeitbreite einmal je Minute
  chrome: 0,           // Höhe von Kopfzeile und Band, solange sie im Streifen ausgeblendet sind (is-compact)
  timer: null,         // lokaler Timer bzw. Stoppuhr (cd.timerNew …), null: keiner
  timerTimer: null,
  tenths: false,       // Taste T: Zehntel bei Stoppuhr und Timer
  utcBig: false,       // Taste U: UTC als große Zeit
  cdPrev: NaN,         // Restsekunden der letzten Anzeige (Ansagen an Schwellen)
  cdZone: undefined,   // Zeitzone, in der ?until= zuletzt gerechnet wurde (undefined: noch keine)
  cdShape: "",         // Breite und Art der Countdown-Anzeige (bei Änderung neu einpassen)
  cdTone: null,        // { ctx, lastK, target, oscs } für ?beep= (oscs: geplante, noch nicht verklungene Töne)
  hintTimer: null,
  keysReturn: null,    // Element mit dem Fokus vor dem Öffnen der Kürzel-Übersicht
  profile: null,       // geladenes Profil (?p=) { name, title, params, profiles_rev }
  profileKey: "",      // Inhalt des Profils beim Laden (Vergleich nach einer Änderung von profiles_rev)
  profileRev: null,    // zuletzt gesehenes profiles_rev
  profileShow: null,   // ?show= des Profils allein (fx.mergeShow)
  profileBusy: false,
  profileError: "",
  profileTries: 0,     // gescheiterte Abrufe in Folge (Abstand des nächsten Versuchs)
  profileRetryAt: 0,   // performance.now(), ab dem der nächste Versuch kommt
  customRaw: null,     // Rohwerte im Panel „Anpassen“
  ready: false,        // Start abgeschlossen (Profil geladen): erst dann wirken Tastenkürzel
  tcSub: null,         // Taste T im Design tc: "tenths" | "frames" (null: es gilt ?sub=)
  tcRaf: 0,            // laufende rAF-Anfrage der Feinstelle (0: keine)
  tcLevel: "off",      // Zustand der Feinstelle beim letzten Sekundentakt (sure | unsure | off)
  tcOffset: null,      // { minute, zone, offset } – Abstand der Server-Zeitzone zu UTC, je Minute neu bestimmt
  tcShape: "",         // Aufbau der Timecode-Zeile (bei Änderung neu einpassen)
  tcOffAt: null,       // performance.now(), seit dem die Feinstelle wegen der Schranke ausgeblendet ist (null: sichtbar)
  grain: undefined,    // Raster von performance.now() in ms (undefined: noch nicht gemessen, null: unbekannt)
  grainBusy: false,
  picked: "normal",    // gewähltes Layout (Automatik oder ?layout=); layout: das gerade gezeichnete
  test: null,          // Prüfbild ?test=sync: { mode: run|reduced|eink, timer, tone: { ctx, last } | null, leadChanged }
  chipKey: "",         // Marken der Statuszeile beim letzten Zeichnen (PTP, Holdover)
  world: null,         // Weltzeit: { mode, key, cells, more, maxLines, shown, dense } (null: keine Zonen)
  worldKey: "",        // Minute, Sprache und Bezugszeit der letzten Zeichnung
  signalLocal: false,  // Taste O: lokales „On Air“ (nur dieses Gerät, nicht gemerkt, nicht gesendet)
  signalKey: "",       // Zustand des Signals beim letzten Zeichnen
  polling: false,      // eine Zustandsabfrage läuft noch (Sekundentakt: keine zweite daneben)
  headHeight: 0,       // Höhe der Kopfzeile, zuletzt ohne Signal gemessen (signalSpace)
  pomo: null,          // Pomodoro (fx.pomoNew …) zum lokalen Timer, null: Eieruhr bzw. Stoppuhr
  eggMs: null,         // Dauer der im Panel gewählten Eieruhr (null: ?timer= aus der Adresse)
  endTone: false,      // „Ton am Ende“ (nur nach Klick, nicht gemerkt)
  ended: false,        // Eieruhr abgelaufen: deutliches Ende (data-cd-end)
  nightOverride: null, // Nachtmodus von Hand (Knopf, Taste N): true/false bis zum nächsten Wechsel des Zeitplans
  nightPrev: null,     // Zeitplan beim letzten Takt (true/false, null: kein ?dim=)
  nightKey: "",        // zuletzt angewandter Nachtmodus
  own: [],             // eigene Countdowns (fx.ownList aus dem localStorage)
  extraWish: [],       // Zusätze aus ?show= (moon, nerd, progress), fx.splitShow
  extrasKey: "",       // sichtbare Zusätze und Balken beim letzten Zeichnen (Wechsel: neu einpassen)
  extrasHeight: 0,     // Höhe der Zusätze beim letzten Einpassen der Zeit
  extrasNoRoom: false, // Zusätze passten nicht in die Bühne (checkExtrasRoom) – bis zur nächsten Größenänderung aus
  extrasAt: null,      // Tag, Zone und Stunde der Anzeige beim letzten Zeichnen der Zusätze (renderExtras)
  extrasRefit: { second: -1, count: 0 },   // Neu-Einpassen durch watchExtras in dieser Sekunde
  moonKey: "",         // Minute, Halbkugel und Sprache der letzten Mond-Zeichnung
  barsKey: "",         // Minute und Sprache der letzten Zeichnung der Kalender-Balken
  bars: [],            // [{ kind, node, fill, value }] der Fortschrittsbalken
  nerd: null,          // { [key]: Wertknoten } der Nerd-Zeile
  south: false,        // Mond wie auf der Südhalbkugel (nur dieser Browser, localStorage)
};
/** Bedienung: Start/Anhalten am Countdown (actions) und die Spielereien (fun) – nach dem Profil neu bestimmt. */
let CONTROLS = { actions: true, fun: true };
let COUNT_MODE = "watch";
function initCountMode() {
  COUNT_MODE = params.until || params.goal ? "until" : (params.timer || params.pomo ? "timer" : "watch");
  // ?pomo= geht ?timer= vor: Der Timer läuft dann die Phasen des Pomodoro ab.
  state.pomo = COUNT_MODE === "timer" && params.pomo ? fx.pomoNew(params.pomo, params.pause) : null;
  state.timer = COUNT_MODE === "timer" ? cd.timerNew(state.pomo ? fx.pomoPhaseMs(state.pomo) : params.timer) : null;
  if ((params.until || params.goal) && (params.timer || params.pomo)) console.info("/clock: Ziel und timer/pomo zugleich – es gilt das Ziel");
  if (params.ignored.length) console.info(`/clock: unzulässige Werte ignoriert (${params.ignored.join(", ")})`);
}

// Nur schreiben, was sich wirklich ändert: Das Band und #tone-status sind aria-live-Regionen (sonst sagt der
// Screenreader denselben Satz immer wieder an), und E-Ink aktualisiert sonst bei jeder Zuweisung.
function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}
function setAttr(node, name, value) {
  if (node.getAttribute(name) !== value) node.setAttribute(name, value);
}
function setHidden(node, hidden) {
  if (node.hidden !== hidden) node.hidden = hidden;
}

/**
 * Lesen (ohne value): gespeicherter Text oder null. Schreiben: true, wenn der Wert danach wirklich im Speicher steht –
 * false bei gesperrtem Speicher (privates Fenster, gesperrte Website-Daten, volles Kontingent). Wirft nie.
 */
function store(key, value) {
  try {
    if (value === undefined) return window.localStorage.getItem(key);
    window.localStorage.setItem(key, value);
    return window.localStorage.getItem(key) === value;
  } catch (error) { /* privates Fenster – dann eben ohne Merken */ }
  return value === undefined ? null : false;
}

// --- Messung -------------------------------------------------------------------
async function sample() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  // Datumsbasis aus Date.now(), Dauer aus performance.now() (feiner als 1 ms).
  const wall0 = Date.now();
  const perf0 = performance.now();
  try {
    const response = await fetch("/api/v1/time", {
      cache: "no-store", credentials: "same-origin", signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    const perf3 = performance.now();
    if (!response.ok) throw new Error(response.status === 401 ? t("clock.err_login") : `HTTP ${response.status}`);
    const payload = await response.json();
    const measured = fromResponse(wall0, payload, wall0 + (perf3 - perf0));
    if (measured) measured.perf = perf3;   // für den Anker: t3 auf der monotonen Uhr
    state.status = payload;
    checkProfileRev(payload.profiles_rev);
    state.lastOk = performance.now();
    state.error = "";
    return measured;
  } catch (error) {
    state.error = error.name === "AbortError" ? t("clock.err_timeout") : error.message;
    return null;
  } finally {
    clearTimeout(timer);
  }
}

const wait = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

async function burst() {
  if (state.bursting) return;
  state.bursting = true;
  const results = [];
  try {
    for (let i = 0; i < BURST; i += 1) {
      const m = await sample();
      if (m) results.push(m);
      if (i < BURST - 1) await wait(BURST_GAP_MS);
    }
  } finally {
    state.bursting = false;
  }
  const winner = best(results);
  const anchor = kit.anchorFrom(winner);
  if (winner && anchor) {
    state.sync = winner;
    state.anchor = anchor;
    state.jumped = false;
    // Neuer Anker: die Restzeit kann springen (erster Anker nach der Gerätezeit) – das ist kein erlebter Übergang.
    state.cdPrev = NaN;
    // Sofort mit dem neuen Versatz zeichnen und den Takt neu ausrichten – E-Ink wartete sonst bis zur
    // nächsten (falsch berechneten) Minute. Der Sekundenzeiger setzt neu an.
    clearTimeout(state.tickTimer);
    tick();
    restartSweep();
    flashTick();   // Prüfbild: Wechsel auf die Sekundengrenze des neuen Ankers legen
  }
  renderBandLive();
  renderDevice();
  renderSignal();
}

async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    await sample();
  } finally {
    state.polling = false;
  }
  renderBandLive();
  renderSignal();
}

// --- On-Air/REC-Signal ----------------------------------------------------------------------------
/**
 * Rahmen und Balken des Signals. Nur feste Zustände (kit.signalView), Text aus dem Sprachkatalog – nie Text aus der
 * Antwort. Der Balken steht über der Bühne; sie wird dadurch kleiner und passt sich selbst neu ein (ResizeObserver).
 */
function renderSignal() {
  const view = kit.signalView({ enabled: params.signal, central: state.status ? state.status.signal : "off",
    local: state.signalLocal, sinceOkMs: state.lastOk ? performance.now() - state.lastOk : Infinity });
  // Das zentrale Signal übernimmt: Ein lokales „On Air“ ist damit erledigt und kommt nach dem zentralen „Aus“ nicht wieder.
  if (view.state !== "off" && !view.local) state.signalLocal = false;
  const key = `${view.state}|${view.local ? 1 : 0}|${view.stale ? 1 : 0}|${language()}`;
  if (key === state.signalKey) return;
  const before = state.signalKey.split("|")[0];
  state.signalKey = key;
  const on = view.state !== "off";
  const node = $("signal");
  const body = document.body;
  setAttr(node, "data-signal", view.state);
  setAttr(body, "data-signal", view.state);
  if (view.stale) setAttr(body, "data-signal-stale", "1");
  else body.removeAttribute("data-signal-stale");
  setText($("signal-text"), on ? t(`clock.signal.${view.state}`) : "");
  setText($("signal-note"), view.local ? t("clock.signal_local") : (view.stale ? t("clock.signal_stale") : ""));
  // Kurzfassung für schmale Flächen (clock.css zeigt je nach Breite nur eine der beiden).
  setText($("signal-note-short"), view.local ? t("clock.signal_local") : (view.stale ? t("clock.signal_stale_short") : ""));
  setHidden(node, !on);
  body.classList.toggle("has-signal", on);
  // Wechsel einmal für den Screenreader ansagen (nicht den Anfangszustand „aus“ und nicht die Sprachumschaltung).
  if (before !== view.state && (before || on)) say(t(`clock.signal_say.${view.state}`));
}

/** Taste O: lokales „On Air“ an oder aus – nur auf diesem Gerät. Zeigt der Bildschirm das zentrale Signal, wirkt sie nicht. */
function toggleSignal() {
  const next = kit.signalToggle({ enabled: params.signal, central: state.status ? state.status.signal : "off",
    local: state.signalLocal });
  state.signalLocal = next.local;
  renderSignal();
  hint(t(next.blocked ? "clock.hint_signal_central" : (next.local ? "clock.hint_signal_on" : "clock.hint_signal_off")));
}

// --- Profil (?p=name) ---------------------------------------------------------------------------
/** Profil vom Server holen: { name, title, params, profiles_rev } oder null (Fehlertext in state.profileError). */
async function fetchProfile() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(`/api/v1/clock/profile?p=${encodeURIComponent(PROFILE)}`, {
      cache: "no-store", credentials: "same-origin", signal: controller.signal, headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      state.profileError = response.status === 404 ? "missing" : (response.status === 401 ? "login" : "error");
      return null;
    }
    const data = await response.json();
    state.profileError = "";
    return data && typeof data === "object" && data.params && typeof data.params === "object" ? data : null;
  } catch (error) {
    state.profileError = "error";
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** Vergleichswert eines Profils: nur das, was die Anzeige bestimmt. */
function profileKey(profile) {
  if (!profile) return "";
  return JSON.stringify({ title: profile.title || "", query: link.layerQuery(link.rawParams(profile.params, ZONES)) });
}

/**
 * profiles_rev aus /api/v1/time: Ändert er sich, das Profil neu holen und die Seite neu laden, wenn sich das eigene
 * Profil geändert hat (ein anderes Profil zu speichern lässt diesen Bildschirm in Ruhe).
 */
function checkProfileRev(rev) {
  const step = link.profileStep({ name: PROFILE, loaded: Boolean(state.profile), error: state.profileError,
    seenRev: state.profileRev, rev, busy: state.profileBusy, now: performance.now(), retryAt: state.profileRetryAt });
  if (step === "adopt") { state.profileRev = rev; return; }
  if (step === "retry") { retryProfile(); return; }
  if (step !== "refetch") return;
  state.profileBusy = true;
  fetchProfile().then((profile) => {
    state.profileBusy = false;
    if (!profile && state.profileError !== "missing") return;   // Netzfehler: beim nächsten Abgleich noch einmal
    state.profileRev = rev;
    if (profileKey(profile) !== state.profileKey) window.location.reload();
  });
}

/** Abruf nach einem Fehlschlag wiederholen; gelingt er, mit dem Profil neu laden (alle Startwerte hängen daran). */
function retryProfile() {
  state.profileBusy = true;
  fetchProfile().then((profile) => {
    state.profileBusy = false;
    if (profile) { window.location.reload(); return; }
    noteProfileFailure();
    renderProfileTitle();
  });
}

function noteProfileFailure() {
  state.profileRetryAt = performance.now() + link.profileRetryDelay(state.profileTries);
  state.profileTries += 1;
}

/** Titel des Profils (oder ein Hinweis, warum es fehlt) in der Kopfzeile und im Fenstertitel. */
function renderProfileTitle() {
  const node = $("clock-title");
  if (!PROFILE) return;
  const key = link.presetTitleKey(state.profile);
  const preset = key ? t(key) : "";
  const title = state.profile ? ((preset && preset !== key ? preset : "") || state.profile.title || "") : "";
  const error = state.profileError ? t(`clock.profile_${state.profileError}`, { name: PROFILE }) : "";
  setText(node, error || title);
  node.classList.toggle("is-error", Boolean(error));
  node.hidden = !(error || title);
  // Kachel (?layout=tile): Dort fehlt die Kopfzeile, der Titel steht als Zeile in der Bühne (CSS zeigt ihn nur dort).
  const tile = $("tile-title");
  const changed = tile.textContent !== (error || title) || tile.hidden !== node.hidden;
  setText(tile, error || title);
  tile.classList.toggle("is-error", Boolean(error));
  setHidden(tile, node.hidden);
  document.body.classList.toggle("has-tile-title", !tile.hidden);   // hält in der Kachel oben eine Zeile frei (CSS)
  if (changed && params.layout === "tile") fitTime();
  document.title = title ? `${title} · ${t("clock.page_title")}` : t("clock.page_title");
}

/**
 * Band nach einer Messung oder Abfrage zeichnen. E-Ink: nur zum Minutenwechsel (tick) – außer das Band zeigt
 * noch „verbinde …“, dann einmal sofort, damit es nicht bis zur nächsten Minute leer bleibt.
 */
function renderBandLive() {
  if (params.eink && $("band").dataset.state !== "unknown") return;
  renderBand();
}

// Serverzeit aus Anker + performance.now(); vor dem ersten Abgleich die Gerätezeit (Zustand „none“).
const trueMs = (perf = performance.now()) => kit.anchoredNow(state.anchor, perf, Date.now());
// Angezeigte Zeit: mit Vorlauf (?lead=) für die Verzögerung des Bildschirms. Ton und Abgleich ohne Vorlauf.
const serverMs = () => trueMs() + params.lead;

/** Fehlerschranke und Zustand jetzt: { state, bound, sinceOk }. */
function syncInfo() {
  const perf = performance.now();
  const s = state.status || {};
  const sinceOk = state.lastOk ? perf - state.lastOk : Infinity;
  const bound = state.anchor && !state.jumped ? kit.errorBound({
    serverAccMs: typeof s.accuracy === "number" ? s.accuracy * 1000 : NaN,
    rttMs: state.sync.rtt, ageMs: perf - state.anchor.perf, frameMs: state.frameMs,
  }) : null;
  const serverSynced = !state.status || (s.running !== false && s.synchronised !== false);
  return { state: kit.syncState({ anchored: Boolean(state.anchor), sinceOkMs: sinceOk, boundMs: bound,
    maxerrMs: params.maxerr, serverSynced, jumped: state.jumped }), bound, sinceOk };
}

/** data-sync, ausgegraute Stellen und die Zeile unter der Uhr (Text + Symbol, nie nur Farbe). Liefert syncInfo(). */
function renderSync() {
  const info = syncInfo();
  // E-Ink: nur zum Minutenwechsel oder bei neuem Zustand neu zeichnen (jede Änderung lässt das Display blinken).
  if (params.eink) {
    const key = `${info.state}|${Math.floor(serverMs() / 60_000)}`;
    if (key === state.syncKey) return info;
    state.syncKey = key;
  }
  const fine = kit.fineDigits(info.bound, { maxerrMs: params.maxerr });
  setAttr(root, "data-sync", info.state);
  setAttr(root, "data-seconds", info.state === "none" ? "unsure" : fine.seconds);
  const acc = info.bound === null ? "" : fmtAccuracy(info.bound);
  let text;
  if (info.state === "none") text = t("clock.sync_none");
  else if (info.state === "free") text = t("clock.sync_free", { since: kit.fmtAge(info.sinceOk), acc: acc || "?" });
  else if (info.state === "degraded" && state.jumped) text = t("clock.sync_jump");
  else if (info.state === "degraded") text = acc ? t("clock.sync_degraded", { acc }) : t("clock.sync_degraded_unknown");
  else text = t("clock.sync_ok", { acc });
  if (params.lead) text += ` · ${t("clock.sync_lead", { ms: params.lead })}`;
  const node = $("clock-sync");
  setAttr(node, "data-sync", info.state);
  setText($("clock-sync-icon"), { ok: "✓", free: "○", degraded: "!", none: "–" }[info.state]);
  setText($("clock-sync-text"), text);
  return info;
}

/** Dauer einer Bildauffrischung einmal messen (sechs Bilder, Median); sonst gilt kit.FRAME_MS. */
function measureFrame() {
  if (params.eink || document.visibilityState !== "visible" || typeof window.requestAnimationFrame !== "function") return;
  const stamps = [];
  const step = (stamp) => {
    stamps.push(stamp);
    if (stamps.length < FRAME_SAMPLES) window.requestAnimationFrame(step);
    else state.frameMs = kit.frameFromStamps(stamps);
  };
  window.requestAnimationFrame(step);
}

// --- Anzeige ---------------------------------------------------------------------
const pad = (n) => String(n).padStart(2, "0");
const DATE_FMT = new Map();
// Datumszeile nach ?date= (long, short, iso) und ?show= (ohne „weekday“ kein Wochentag, nur „weekday“: nur er).
const DATE_STYLES = {
  long: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
  plain: { day: "numeric", month: "long", year: "numeric" },
  weekday: { weekday: "long" },
  short: { day: "2-digit", month: "2-digit", year: "numeric" },
};
function dateText(now, style = dateStyle()) {
  if (style === "iso") return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  if (style === "off") return "";
  const tag = language() === "en" ? "en-GB" : "de-DE";
  const key = `${tag}|${style}`;
  if (!DATE_FMT.has(key)) DATE_FMT.set(key, new Intl.DateTimeFormat(tag, DATE_STYLES[style] || DATE_STYLES.long));
  return DATE_FMT.get(key).format(now);
}
function dateStyle() {
  if (params.date !== "long") return params.date;
  if (!params.show) return "long";
  const date = params.show.includes("date");
  const weekday = params.show.includes("weekday");
  if (date && weekday) return "long";
  if (weekday) return "weekday";
  return date ? "plain" : "off";
}
/** Uhrzeit einer Zone als Text: „HH:MM“, mit ?h12=1 wie die große Zeit „HH:MM PM“. */
function zoneClock(row) {
  return row.ampm ? `${row.time} ${row.ampm}` : row.time;
}
/** Uhrzeit der ersten Zone aus ?tz= (zweite Zeitzone, Design studio mit ?sub=tz2). */
function zoneTime(now) {
  return zoneClock(world.worldRow(now.getTime(), { zone: params.tz[0], label: "" }, 0, undefined, { h12: params.h12 }));
}

function tick() {
  // Kam dieser Takt mehr als 2 s zu spät (Standby, gedrosselter Tab), gleich neu abgleichen.
  const perf = performance.now();
  if (state.planned && kit.tickGap(state.planned.perf, perf, state.planned.delay)) burst();
  // Geräteuhr gegen die monotone Uhr seit dem Anker: Standby (monotone Uhr stand) oder verstellte Uhr. Die Anzeige
  // bleibt am Anker (springt nicht mit), gilt aber bis zum neuen Anker als unsicher; sofort neu messen.
  if (!state.jumped && kit.wallJump(state.anchor, perf, Date.now())) {
    state.jumped = true;
    burst();
  }
  const nowMs = serverMs();
  const now = new Date(nowMs);
  render(now);
  renderNight();
  const remaining = renderCountdown(nowMs);
  const info = renderSync();
  // Zustandswechsel der Zeitbasis auch im Band (aria-live) ansagen – nicht nur in der Zeile unter der Uhr.
  if (info.state !== state.bandSync) renderBandLive();
  // Ampel wird grau, sobald 10 s keine Antwort kam – auch ohne neue Antwort prüfen.
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  document.body.classList.toggle("is-stale", stale && Boolean(state.status));
  if (state.status && (stale || $("band").dataset.state === "stale" || params.eink)) renderBand();
  renderSignal();   // auch ohne neue Antwort: Nach 10 s ohne Server gilt das zentrale Signal als ungewiss
  if (state.tone) toneTick(trueMs());
  testTone();
  // Nächster Schritt genau zur vollen Sekunde der angezeigten Zeit (E-Ink: zur vollen Minute, bei laufendem Countdown
  // oder Timer auch zu dessen Minutensprüngen und genau auf dem Ziel).
  const later = serverMs();
  const delay = params.eink ? cd.einkDelay(later, remaining - (later - nowMs)) : 1000 - (((later % 1000) + 1000) % 1000) + 5;
  state.planned = { perf: performance.now(), delay };
  state.tickTimer = setTimeout(tick, delay);
}

function render(now) {
  // Taste U: UTC als große Zeit, die Ortszeit steht dann in der Zeile darunter.
  const utc = state.utcBig;
  const h = utc ? now.getUTCHours() : now.getHours();
  const m = utc ? now.getUTCMinutes() : now.getMinutes();
  const s = utc ? now.getUTCSeconds() : now.getSeconds();
  // Stunden, Minuten und Sekunden getrennt: Die Sekunden können allein grau werden (data-seconds), der Doppelpunkt
  // allein blinken (?colon=blink: ein Attributwechsel je Sekunde).
  const hour = kit.hourText(h, { h12: params.h12, lz: params.lz });
  setText($("local-h"), hour.text.trimStart());
  setText($("local-m"), pad(m));
  setText($("local-s"), params.eink ? "" : pad(s));
  setHidden($("local-sec"), params.eink);
  // Mit führendem Leerzeichen: Der Screenreader liest „6:02:08 PM“ statt „6:02:08PM“ (der Abstand kommt aus dem Leerzeichen).
  setText($("local-ampm"), hour.ampm ? ` ${hour.ampm}` : "");
  setHidden($("local-ampm"), !hour.ampm);
  if (params.colon === "blink" && !params.eink) setAttr(root, "data-colon", s % 2 ? "off" : "on");
  const stamp = params.eink ? new Date(Math.floor(now.getTime() / 60_000) * 60_000) : now;
  setAttr($("local-time"), "datetime", stamp.toISOString());
  setText($("local-label"), utc ? "UTC" : t("clock.local"));
  // Design tc mit anderer Zeitzone des Servers: Datum, Woche und (nach Taste U) die Nebenzeile gehören zur Zone des
  // Timecodes, nicht zu der des Browsers – sonst stünde unter der Zeit ein Datum, das nicht zu ihr gehört.
  const foreign = tcForeignOffset(now.getTime());
  const zoned = foreign === null ? null : tc.zoneDay(now.getTime(), foreign);
  const day = zoned ? new Date(zoned.y, zoned.mo - 1, zoned.d, 12) : now;
  const other = zoned && utc ? hms(new Date(now.getTime() + foreign), true) : hms(now, !utc);
  setText($("utc-label"), utc ? (zoned ? kit.zoneLabel(tcZone()) : t("clock.local")) : "UTC");
  setText($("utc-time"), params.eink ? other.slice(0, 5) : other);
  setText($("local-date"), dateText(day));
  const { week } = isoWeek(day);
  setText($("iso-week"), t("clock.week", { week }));
  const redrawn = renderWorld(now.getTime());
  renderFace(now, h, m, s);
  // Zusätze im selben Tag wie Datum und KW (Design tc mit Zone des Servers: dort), römisch die Stunde der Anzeige.
  const shown = zoned ? new Date(now.getTime() + foreign) : null;
  renderExtras(now.getTime(), { day, offset: zoned ? foreign : null,
    h: shown ? shown.getUTCHours() : h, m: shown ? shown.getUTCMinutes() : m });
  renderShift(now.getTime());
  renderEgg(now.getTime());
  const minuteKey = `${h}:${m}|${language()}|${foreign}`;
  if (minuteKey !== state.minuteKey || redrawn) {
    state.minuteKey = minuteKey;
    fitTime();
  }
}

// --- Designs -----------------------------------------------------------------------
function textTime() {
  return state.design === "digital" && params.face !== "seg";
}

function buildFace() {
  const face = $("face");
  if (openInfo && face.contains(openInfo.button)) closeInfo();
  face.replaceChildren();
  const seg = state.design === "digital" && params.face === "seg";
  face.className = `clock-face face-${seg ? "seg" : state.design}`;
  const text = textTime();
  face.hidden = text;
  $("local-time").hidden = !text;
  state.face = { design: state.design, key: "" };
  if (text) return;
  // Das Timecode-Design enthält einen Knopf (ⓘ): dann Gruppe statt Bild, die Ziffern selbst sind aria-hidden.
  face.setAttribute("role", state.design === "tc" ? "group" : "img");
  if (seg) Object.assign(state.face, faces.buildSegRow(face, { count: digitCount(), h12: params.h12 }), { seg: true });
  else if (state.design === "studio") {
    Object.assign(state.face, faces.buildStudio(face, { seconds: params.seconds, sub: tc.studioSub(params.sub), h12: params.h12 }));
    // E-Ink rechnet nur einmal je Minute: weder Kranz noch Sekundenziffern.
    if (params.eink) for (const part of [state.face.ring, state.face.secGroup]) part.classList.add("is-off");
  } else if (state.design === "bahnhof") buildBahnhof(face);
  else if (state.design === "nixie") buildNixie(face);
  else if (state.design === "flip") buildFlip(face);
  else if (state.design === "wort") buildWort(face);
  else if (state.design === "tc") buildTc(face);
  else if (state.design === "binary") buildBinary(face);
}

// Ohne Sekunden (E-Ink, ?show= ohne „seconds“) nur HH:MM.
function digitCount() { return params.eink || (params.show && !params.show.includes("seconds")) ? 4 : 6; }

function buildBahnhof(face) {
  // Eigenes, schlichtes Zifferblatt: Striche statt Zahlen, Balkenzeiger, Sekundenzeiger mit offenem Ring.
  const svg = svgEl("svg", { viewBox: "0 0 200 200", class: "bh", "aria-hidden": "true", focusable: "false" });
  svg.append(svgEl("circle", { cx: 100, cy: 100, r: 97, class: "bh-face" }));
  for (let i = 0; i < 60; i += 1) {
    const hour = i % 5 === 0;
    svg.append(svgEl("line", { x1: 100, y1: 9, x2: 100, y2: hour ? 27 : 15, class: hour ? "bh-tick bh-tick-hour" : "bh-tick",
      transform: `rotate(${i * 6} 100 100)` }));
  }
  const hour = svgEl("rect", { x: 95, y: 46, width: 10, height: 66, rx: 1.5, class: "bh-hour" });
  const minute = svgEl("rect", { x: 96.5, y: 15, width: 7, height: 97, rx: 1.5, class: "bh-minute" });
  const second = svgEl("g", { class: "bh-second" });
  second.append(svgEl("line", { x1: 100, y1: 130, x2: 100, y2: 40, class: "bh-second-line" }),
    svgEl("circle", { cx: 100, cy: 33, r: 7, class: "bh-second-ring" }));
  svg.append(hour, minute, second, svgEl("circle", { cx: 100, cy: 100, r: 3.5, class: "bh-cap" }));
  if (params.eink) second.hidden = true;
  face.append(svg);
  Object.assign(state.face, { svg, hour, minute, second, sweep: false });
}

function setAngle(node, angle) {
  setAttr(node, "transform", `rotate(${Math.round(angle * 100) / 100} 100 100)`);
}

function sweepWanted() {
  return state.design === "bahnhof" && !params.eink && !reducedMotion.matches;
}

/** Sekundenzeiger als CSS-Animation (60 s, Halt auf der 12) auf die Phase der Serverminute setzen. */
function restartSweep() {
  const face = state.face;
  if (!face || face.design !== "bahnhof" || !face.second) return;
  if (!face.sweep && !sweepWanted()) return;   // läuft nicht und soll nicht laufen (E-Ink, ruhig)
  const node = face.second;
  node.classList.remove("is-sweep");
  if (!sweepWanted()) { face.sweep = false; return; }
  node.removeAttribute("transform");
  const phase = (((serverMs() % 60_000) + 60_000) % 60_000) / 1000;
  void node.getBoundingClientRect();   // Animation wirklich neu starten
  node.style.animationDelay = `-${Math.round(phase * 1000) / 1000}s`;
  node.classList.add("is-sweep");
  face.sweep = true;
}

function renderBahnhof(h, m, s, ms) {
  const face = state.face;
  const angles = kit.handAngles(h, m, s, ms, { step: true });
  setAngle(face.hour, angles.hour);
  setAngle(face.minute, angles.minute);
  setAttr(face.svg, "data-hour", String(angles.hour));
  setAttr(face.svg, "data-minute", String(angles.minute));
  if (sweepWanted()) {
    // Zur vollen Minute (Zeiger steht ohnehin auf der 12) neu ansetzen – so läuft er nie weg.
    if (!face.sweep || s === 0) restartSweep();
  } else {
    if (face.sweep) restartSweep();
    if (!params.eink) setAngle(face.second, angles.second);
  }
}

function buildNixie(face) {
  const tubes = [];
  for (let i = 0; i < digitCount(); i += 1) {
    if (i && i % 2 === 0) face.append(Object.assign(document.createElement("span"), { className: "nixie-sep", textContent: "·" }));
    const tube = document.createElement("span");
    tube.className = i >= 4 ? "nixie-tube is-sec" : "nixie-tube";
    tube.setAttribute("aria-hidden", "true");
    const numerals = [];
    for (let n = 0; n < 10; n += 1) {
      const numeral = document.createElement("span");
      numeral.className = "nixie-n";
      numeral.textContent = String(n);
      tube.append(numeral);
      numerals.push(numeral);
    }
    face.append(tube);
    tubes.push({ tube, numerals });
  }
  state.face.tubes = tubes;
}

function renderNixie(digits) {
  state.face.tubes.forEach(({ tube, numerals }, index) => {
    const digit = digits[index];
    if (tube.dataset.digit === digit) return;
    tube.dataset.digit = digit;
    numerals.forEach((node, n) => node.classList.toggle("on", String(n) === digit));
  });
}

function buildFlip(face) {
  const cards = [];
  for (let i = 0; i < digitCount(); i += 1) {
    if (i && i % 2 === 0) face.append(Object.assign(document.createElement("span"), { className: "flip-sep", textContent: ":" }));
    const card = document.createElement("span");
    card.className = i >= 4 ? "flip-card is-sec" : "flip-card";
    card.setAttribute("aria-hidden", "true");
    const digit = document.createElement("span");
    digit.className = "flip-digit";
    card.append(digit);
    face.append(card);
    cards.push({ card, digit });
  }
  Object.assign(state.face, { cards, digits: "" });
}

function renderFlip(digits) {
  const face = state.face;
  kit.flipDigits(face.digits, digits).forEach(({ digit, changed }, index) => {
    const { card, digit: node } = face.cards[index];
    if (node.textContent === digit) return;
    node.textContent = digit;
    card.dataset.digit = digit;
    if (changed) {
      // Zwei gleiche Animationen im Wechsel – so startet CSS sie bei jedem Wechsel neu.
      const next = card.classList.contains("flip-a") ? "flip-b" : "flip-a";
      card.classList.remove("flip-a", "flip-b");
      card.classList.add(next);
    }
  });
  face.digits = digits;
}

function buildWort(face) {
  const text = document.createElement("p");
  text.className = "wort-text";
  const dots = document.createElement("span");
  dots.className = "wort-dots";
  dots.setAttribute("aria-hidden", "true");
  const dotNodes = [];
  for (let i = 0; i < 4; i += 1) {
    const dot = document.createElement("span");
    dot.className = "wort-dot";
    dots.append(dot);
    dotNodes.push(dot);
  }
  face.append(text, dots);
  Object.assign(state.face, { text, dots: dotNodes });
}

function renderWort(h, m) {
  const face = state.face;
  const result = kit.wordClock(h, m, language());
  face.text.replaceChildren(...result.words.map((word, i) => {
    const span = document.createElement("span");
    span.className = "wort-word";
    span.textContent = i ? ` ${word}` : word;
    return span;
  }));
  face.text.dataset.time = `${pad(h)}:${pad(m)}`;
  face.dots.forEach((dot, i) => dot.classList.toggle("on", i < result.dots));
}

function renderFace(now, h, m, s) {
  if (!state.face || state.face.design !== state.design) buildFace();
  const face = state.face;
  if (state.design === "tc") { renderTc(now.getTime()); return; }
  const minuteKey = `${pad(h)}:${pad(m)}|${language()}`;
  if (face.key !== minuteKey) {
    face.key = minuteKey;
    $("face").setAttribute("aria-label", faceLabel(h, m));
  }
  const digits = kit.timeDigits(h, m, s, !params.eink);
  if (face.seg) renderSeg(h, m, s);
  else if (state.design === "studio") renderStudio(now, h, m, s);
  else if (state.design === "bahnhof") renderBahnhof(h, m, s, now.getMilliseconds());
  else if (state.design === "nixie") renderNixie(digits);
  else if (state.design === "flip") renderFlip(digits);
  else if (state.design === "wort" && face.text.dataset.key !== minuteKey) {
    face.text.dataset.key = minuteKey;
    renderWort(h, m);
  } else if (state.design === "binary") renderBinary(h, m, s);
  setAttr($("face"), "data-time", params.eink ? `${pad(h)}:${pad(m)}` : `${pad(h)}:${pad(m)}:${pad(s)}`);
}

/** Zeit des Zifferblatts für den Screenreader: wie angezeigt, mit ?h12=1 also „6:02 PM“ statt „18:02 Uhr“. */
function faceLabel(h, m) {
  if (!params.h12) return t("clock.face_label", { time: `${pad(h)}:${pad(m)}` });
  const hour = kit.hourText(h, { h12: true, lz: params.lz });
  return `${hour.text.trimStart()}:${pad(m)} ${hour.ampm}`;
}

/** 7-Segment-Zeile (digital, face=seg): nur geänderte Stellen bekommen eine neue Klasse. */
function renderSeg(h, m, s) {
  const face = state.face;
  const hour = kit.hourText(h, { h12: params.h12, lz: params.lz });
  const chars = `${hour.text}${pad(m)}${pad(s)}`;
  face.digits.forEach((node, index) => faces.setDigit(node, chars[index]));
  if (face.ampm) setText(face.ampm, hour.ampm);
}

/** Design studio: HH:MM, Sekunden als Ziffern und/oder Kranz, Zeile darunter nach ?sub=. */
function renderStudio(now, h, m, s) {
  const face = state.face;
  const hour = kit.hourText(h, { h12: params.h12, lz: params.lz });
  const chars = `${hour.text}${pad(m)}`;
  face.digits.forEach((node, index) => faces.setDigit(node, chars[index]));
  if (!params.eink) {
    face.secDigits.forEach((node, index) => faces.setDigit(node, pad(s)[index]));
    faces.setRing(face.dots, s);
  }
  if (face.ampm) setText(face.ampm, hour.ampm);
  const line = tc.studioSub(params.sub);   // tenths/frames gehören zum Design tc: hier die Standardzeile
  let sub = "";
  if (state.utcBig && (line === "utc" || (line === "tz2" && !params.tz))) sub = `${t("clock.local")} ${hms(now).slice(0, 5)}`;
  else if (line === "utc" || (line === "tz2" && !params.tz)) sub = `UTC ${hms(now, true).slice(0, 5)}`;
  else if (line === "tz2") sub = `${world.worldEntries(params.tz, params.tzl)[0].label} ${zoneTime(now)}`;
  else if (line === "date") sub = dateText(now, "short");
  setText(face.sub, sub);
}

// --- Design binary (Studiouhr C2) ---------------------------------------------------------------------------------
// Lämpchen als SVG (Kreise mit Klasse on), darunter bzw. daneben die Dezimalwerte zum Ablesen. ?bin=bcd: je Ziffer eine
// Spalte mit den Gewichten 8-4-2-1 von oben; ?bin=plain: Stunde, Minute und Sekunde je als Zeile mit 32 … 1 von links.
// Je Sekunde wechseln nur Klassen der Lämpchen, deren Zustand sich ändert – keine Animation, kein Zeitgeber.
const BIN_STEP = 22;   // Abstand der Lämpchen (viewBox-Einheiten)
const BIN_R = 8;

function buildBinary(face) {
  const seconds = digitCount() === 6;
  const plain = params.bin === "plain";
  const sample = fx.binaryLamps(0, 0, 0, { mode: params.bin, seconds });
  const text = (x, y, value, cls, anchor = "middle") => {
    const node = svgEl("text", { x, y, class: cls, "text-anchor": anchor });
    node.textContent = value;
    return node;
  };
  const lamps = [];
  const values = [];
  let svg;
  if (plain) {
    // Zeilen: links die Einheit (h, min, s), oben die Gewichte, rechts der Wert.
    const left = 34;
    const width = left + 6 * BIN_STEP + 40;
    const height = 18 + sample.groups.length * BIN_STEP + 4;
    svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "bin bin-plain", "aria-hidden": "true", focusable: "false",
      preserveAspectRatio: "xMidYMid meet" });
    [32, 16, 8, 4, 2, 1].forEach((w, i) => svg.append(text(left + i * BIN_STEP + BIN_STEP / 2, 12, String(w), "bin-weight")));
    sample.groups.forEach((group, row) => {
      const cy = 18 + row * BIN_STEP + BIN_STEP / 2;
      const sec = row === 2;
      svg.append(text(left - 8, cy + 4, ["h", "min", "s"][row], "bin-unit", "end"));
      const offset = 6 - group.bits.length;
      lamps.push(group.bits.map((bit, i) => {
        const lamp = svgEl("circle", { cx: left + (offset + i) * BIN_STEP + BIN_STEP / 2, cy, r: BIN_R,
          class: sec ? "bin-lamp is-sec" : "bin-lamp" });
        svg.append(lamp);
        return lamp;
      }));
      const value = text(width - 4, cy + 5, "", sec ? "bin-value is-sec" : "bin-value", "end");
      svg.append(value);
      values.push(value);
    });
  } else {
    // Spalten: links die Gewichte, unter jeder Spalte ihre Ziffer; zwischen Stunde, Minute und Sekunde etwas Abstand.
    const left = 18;
    const gap = 10;
    const cols = sample.groups.length;
    const colX = (i) => left + i * BIN_STEP + Math.floor(i / 2) * gap + BIN_STEP / 2;
    const width = colX(cols - 1) + BIN_STEP / 2 + 2;
    const height = 4 * BIN_STEP + 22;
    svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: `bin bin-bcd bin-cols-${cols}`, "aria-hidden": "true",
      focusable: "false", preserveAspectRatio: "xMidYMid meet" });
    [8, 4, 2, 1].forEach((w, row) => svg.append(text(8, row * BIN_STEP + BIN_STEP / 2 + 4, String(w), "bin-weight")));
    sample.groups.forEach((group, i) => {
      const sec = i >= 4;
      const offset = 4 - group.bits.length;
      lamps.push(group.bits.map((bit, row) => {
        const lamp = svgEl("circle", { cx: colX(i), cy: (offset + row) * BIN_STEP + BIN_STEP / 2, r: BIN_R,
          class: sec ? "bin-lamp is-sec" : "bin-lamp" });
        svg.append(lamp);
        return lamp;
      }));
      const value = text(colX(i), 4 * BIN_STEP + 17, "", sec ? "bin-value is-sec" : "bin-value");
      svg.append(value);
      values.push(value);
    });
  }
  let ampm = null;
  if (params.h12) {
    // AM/PM in der freien Ecke: bei plain oben links (über den Einheiten), bei bcd unten links (neben den Ziffern).
    ampm = svgEl("text", { x: 1, y: plain ? 12 : 4 * BIN_STEP + 17, class: "bin-ampm" });
    svg.append(ampm);
  }
  face.append(svg);
  Object.assign(state.face, { svg, lamps, values, ampm, seconds });
}

function renderBinary(h, m, s) {
  const face = state.face;
  const hour = kit.hourText(h, { h12: params.h12, lz: true });
  const lit = fx.binaryLamps(params.h12 ? Number(hour.text) : h, m, s, { mode: params.bin, seconds: face.seconds });
  if (!lit) return;
  lit.groups.forEach((group, i) => {
    group.bits.forEach((bit, row) => {
      const lamp = face.lamps[i][row];
      if (lamp.classList.contains("on") !== bit.on) lamp.classList.toggle("on", bit.on);
    });
    setText(face.values[i], params.bin === "plain" ? pad(group.value) : String(group.value));
  });
  if (face.ampm) setText(face.ampm, hour.ampm);
}

// --- Design tc: Timecode-Anzeige (Studiouhr B1) ------------------------------------------------
/** Zeile HH:MM:SS mit Feinstelle, darüber die feste Kopfzeile mit ⓘ, darunter Bildrate und Zustand der Feinstelle. */
function buildTc(face) {
  const span = (cls, text = "") => Object.assign(document.createElement("span"), { className: cls, textContent: text });
  const head = document.createElement("p");
  head.className = "tc-head";
  const label = span("tc-label", t("clock.tc_label"));
  // Kurzer Grund für eine graue oder fehlende Feinstelle: sichtbar, wo die Zeile unter der Zeit keinen Platz hat (CSS).
  const why = span("tc-why");
  head.append(label, why, " ", infoButton("clock.tc_info_title", "clock.tc_info"));
  const row = document.createElement("div");
  row.className = "tc-row";
  row.setAttribute("aria-hidden", "true");
  const hh = span("tc-d", "--");
  const mm = span("tc-d", "--");
  const ss = span("tc-d", "--");
  const secs = span("tc-secs");
  const fine = span("tc-fine");
  const sep = span("tc-sep");
  const ff = span("tc-d");
  fine.append(sep, ff);
  secs.append(span("tc-sep", ":"), ss, fine);
  row.append(hh, span("tc-sep", ":"), mm, secs);
  const note = document.createElement("p");
  note.className = "tc-note";
  face.append(head, row, note);
  Object.assign(state.face, { tc: true, head, row, label, why, hh, mm, ss, secs, fine, sep, ff, note });
  state.tcShape = "";
  state.tcOffAt = null;
  measureGrain();
}

/** Feinstelle jetzt: frames nur auf Wunsch (?sub=frames, Taste T), nie bei E-Ink oder „weniger Bewegung“. */
function tcMode() {
  const seconds = !(params.show && !params.show.includes("seconds"));
  return tc.fineMode(state.tcSub || params.sub, { eink: params.eink, reduced: reducedMotion.matches, seconds });
}

/** Zeitzone des Timecodes: die des Servers (zone aus /api/v1/time), sonst die des Browsers (null). */
function tcZone() {
  return state.status ? cd.usableZone(state.status.zone) : null;
}

/** Design tc, Zone des Servers weicht von der des Browsers ab: ihr Abstand zu UTC (ms) für Datum und Woche; sonst null. */
function tcForeignOffset(ms) {
  if (state.design !== "tc") return null;
  const zone = tcZone();
  return zone && zone !== browserZone() ? cd.zoneOffset(ms, zone) : null;
}

/** Tageszeit (ms seit Mitternacht) in der Zone des Servers; Taste U: UTC. Der Abstand zu UTC wird je Minute neu bestimmt. */
function tcDayMs(ms) {
  if (state.utcBig) return tc.dayMs(ms, 0);
  const zone = tcZone();
  const minute = Math.floor(ms / 60_000);
  if (!state.tcOffset || state.tcOffset.minute !== minute || state.tcOffset.zone !== zone) {
    state.tcOffset = { minute, zone, offset: cd.zoneOffset(ms, zone) };
  }
  return tc.dayMs(ms, state.tcOffset.offset);
}

/** Ziffern schreiben – nur, was sich geändert hat. Aus dem Sekundentakt und, solange die Feinstelle läuft, je Bild. */
function paintTc(ms, mode) {
  const face = state.face;
  const view = tc.tcView(tcDayMs(ms), params.fps, mode);
  setText(face.hh, view.hh);
  setText(face.mm, view.mm);
  if (!params.eink) setText(face.ss, view.ss);
  if (mode !== "off") {
    setText(face.sep, view.sep === "." && language() !== "en" ? "," : view.sep);
    setText(face.ff, view.fine);
  }
  return view;
}

/** Bildrate als Text: „25 fps“, „29,97 fps Drop-Frame“. */
function tcRateText() {
  const rate = tc.tcRate(params.fps);
  const fps = language() === "en" ? rate.fps : rate.fps.replace(".", ",");
  return t(rate.drop ? "clock.tc_rate_df" : "clock.tc_rate", { fps });
}

/** Sekundentakt des Designs tc: Ziffern, Zustand der Feinstelle (grau/aus, immer auch als Text), Zeile darunter. */
function renderTc(ms) {
  const face = state.face;
  const mode = tcMode();
  const info = syncInfo();
  const level = tc.fineLevel({ mode, boundMs: info.state === "none" ? null : info.bound, grainMs: state.grain,
    fps: params.fps, maxerrMs: params.maxerr });
  state.tcLevel = level.level;
  // Ausgeblendete Feinstelle: Sekunden aus der Wanduhr (tc.paintMode), nicht aus der Drop-Frame-Framenummer.
  const view = paintTc(ms, tc.paintMode(mode, level.level));
  setHidden(face.secs, params.eink);
  setHidden(face.fine, mode === "off");
  // Der Platz der Feinstelle bleibt zunächst frei (kein Springen bei kurzem Ausfall); bleibt sie länger aus, rückt die
  // Zeit in die Mitte.
  const offNow = mode !== "off" && level.level === "off";
  if (!offNow) state.tcOffAt = null;
  else if (state.tcOffAt === null) state.tcOffAt = performance.now();
  const gone = offNow && performance.now() - state.tcOffAt >= TC_GONE_MS;
  face.fine.classList.toggle("is-gone", gone);
  setAttr(face.fine, "data-level", level.level);
  setAttr(face.fine, "data-mode", mode);
  setText(face.label, t("clock.tc_label"));
  const wanted = state.tcSub || params.sub;
  const parts = [tcRateText()];
  if (mode !== "off") parts.push(t(mode === "frames" ? "clock.tc_fine_frames" : "clock.tc_fine_tenths"));
  const zone = tcZone();
  if (state.utcBig) parts.push("UTC");
  else if (zone && zone !== browserZone()) parts.push(kit.zoneLabel(zone));
  const limit = fmtAccuracy(level.limit).replace("± ", "");
  let why = "";
  if (level.reason === "grain") {
    parts.push(Number.isFinite(state.grain) ? t("clock.tc_grain", { grain: fmtAccuracy(state.grain).replace("± ", "") })
      : t("clock.tc_grain_unknown"));
    why = t("clock.tc_why_grain");
  } else if (level.level === "off" && level.reason === "bound") {
    parts.push(t("clock.tc_fine_off"));
    why = t("clock.tc_why_off");
  } else if (level.reason === "bound") {
    parts.push(t(mode === "frames" ? "clock.tc_unsure_frames" : "clock.tc_unsure_tenths", { acc: fmtAccuracy(info.bound), limit }));
    why = t(mode === "frames" ? "clock.tc_why_frames" : "clock.tc_why_tenths");
  }
  setText(face.why, why ? ` · ${why}` : "");
  if (wanted === "frames" && mode === "tenths") parts.push(t("clock.tc_reduced"));
  setText(face.note, parts.join(" · "));
  const text = params.eink ? view.text.slice(0, 5) : (level.level === "off" ? view.text.slice(0, 8) : view.text);
  setAttr($("face"), "data-time", text);
  const minuteKey = `${view.hh}:${view.mm}|${language()}`;
  if (face.key !== minuteKey) {
    face.key = minuteKey;
    $("face").setAttribute("aria-label", `${t("clock.tc_label")}: ${t("clock.face_label", { time: `${view.hh}:${view.mm}` })}`);
  }
  // Andere Breite (Feinstelle an/aus, Zehntel/Frames, längere Zeile darunter): neu einpassen.
  const shape = `${mode}|${gone}|${params.eink}|${face.note.textContent.length}|${face.why.textContent.length}|${state.layout}`;
  if (shape !== state.tcShape) {
    state.tcShape = shape;
    fitTime();
  }
  tcLoop();
}

/** Läuft die Feinstelle gerade? Nur im Design tc, sichtbar und von der Schranke getragen (grau zählt mit). */
function tcRunning() {
  return state.design === "tc" && Boolean(state.face && state.face.tc) && state.tcLevel !== "off" && tcMode() !== "off"
    && !countdownMain() && document.visibilityState === "visible";
}

/** Bildschleife (rAF) nur für die Feinstelle: startet aus dem Sekundentakt und hört von selbst auf. */
function tcLoop() {
  if (state.tcRaf || !tcRunning() || typeof window.requestAnimationFrame !== "function") return;
  const step = () => {
    state.tcRaf = 0;
    if (!tcRunning()) return;
    paintTc(serverMs(), tcMode());
    state.tcRaf = window.requestAnimationFrame(step);
  };
  state.tcRaf = window.requestAnimationFrame(step);
}

/**
 * Raster von performance.now() einmal bestimmen (tc.timerGrain): Messwerte im Abstand von GRAIN_STEP_MS, nur solange
 * die Seite sichtbar ist (im Hintergrund drosselt der Browser die Zeitgeber, das sähe wie ein grobes Raster aus).
 */
function measureGrain() {
  if (state.grain !== undefined || state.grainBusy || params.eink || document.visibilityState !== "visible") return;
  state.grainBusy = true;
  const samples = [];
  const step = () => {
    if (document.visibilityState !== "visible") { state.grainBusy = false; return; }
    samples.push(performance.now());
    if (!tc.grainDone(samples)) { setTimeout(step, GRAIN_STEP_MS); return; }
    state.grainBusy = false;
    state.grain = tc.timerGrain(samples);
    if (state.design === "tc" && state.face && state.face.tc) renderTc(serverMs());
  };
  step();
}

/**
 * Taste T im Design tc: Zehntel ↔ Frames; mit ?sub=off im Dreierwechsel auch wieder zurück zu „aus“ (tc.nextFine).
 * Frames gibt es nicht bei E-Ink und „weniger Bewegung“, ohne Sekunden (?show=) gibt es keine Feinstelle – dann sagt
 * der Hinweis das, statt einen Wechsel zu melden, der nicht stattfindet.
 */
function toggleTcFine() {
  if (params.eink) { hint(t("clock.hint_tc_eink")); return; }
  if (params.show && !params.show.includes("seconds")) { hint(t("clock.hint_tc_noseconds")); return; }
  const want = tc.nextFine(state.tcSub || params.sub, params.sub);
  state.tcSub = want;
  renderTc(serverMs());
  if (want === "off") hint(t("clock.hint_tc_off"));
  else if (want === "frames" && tcMode() === "tenths") hint(t("clock.hint_tc_reduced"));
  else hint(t(want === "frames" ? "clock.hint_tc_frames" : "clock.hint_tc_tenths"));
}

function setDesign(design, remember) {
  state.design = kit.safeDesign(design);
  $("design").value = state.design;
  root.dataset.design = state.design;
  if (remember) {
    store(DESIGN_KEY, state.design);
    // Steht ?design= in der Adresse, passt sie sich an – sonst gälte beim Neuladen wieder das alte.
    const url = new URL(window.location.href);
    if (url.searchParams.has("design")) {
      url.searchParams.set("design", state.design);
      window.history.replaceState(null, "", url);
    }
    // Ebenso der im Panel „Anpassen“ gemerkte Stand: Er gilt beim Start vor DESIGN_KEY – aber nur, wenn diese Adresse
    // ihn überhaupt anwendet (/clock ohne Parameter). Ein Profil- oder Link-Bildschirm lässt ihn unberührt.
    const stored = link.storedApplies(window.location.search) ? store(link.STORE_KEY) : null;
    if (stored) {
      const next = link.storedWith(stored, "design", state.design, ZONES);
      if (next) store(link.STORE_KEY, next);
      else removeStored(link.STORE_KEY);
    }
  }
  buildFace();
  render(new Date(serverMs()));
  restartSweep();
  fitTime();
}

// --- Weltzeit (Studiouhr B2) -------------------------------------------------------------------
/** Abstand der groß gezeigten Zeit zu UTC (ms): Ortszeit des Geräts, im Design tc die Zone des Servers, nach Taste U 0. */
function worldRef(ms) {
  if (state.utcBig) return 0;
  const foreign = tcForeignOffset(ms);
  return foreign === null ? -new Date(ms).getTimezoneOffset() * 60_000 : foreign;
}

/** Zellen der Leiste bzw. des Rasters anlegen: je Zone Kurzname, Uhrzeit, Abweichung, Tageswechsel, Tag/Nacht. */
function buildWorld(mode, entries) {
  const span = (cls) => Object.assign(document.createElement("span"), { className: cls });
  const cells = entries.map((entry) => {
    const cell = span("wz");
    cell.setAttribute("role", "listitem");
    cell.dataset.zone = entry.zone;
    const label = span("wz-label");
    label.textContent = entry.label;   // Kurzname aus der Adresse: nur als Text
    const time = document.createElement("time");
    time.className = "wz-time";
    const hm = span("wz-hm");
    const ampm = span("wz-ampm");   // nur mit ?h12=1 gefüllt
    time.append(hm, ampm);
    const meta = span("wz-meta");
    const delta = span("wz-delta");
    const day = span("wz-day");
    const sun = span("wz-sun");
    sun.setAttribute("role", "img");
    meta.append(delta, day, sun);
    cell.append(label, time, meta);
    return { cell, time: hm, ampm, delta, day, sun };
  });
  const more = span("wz-more");
  more.setAttribute("role", "listitem");
  more.hidden = true;
  $("world").replaceChildren(...cells.map((item) => item.cell), more);
  state.world = { mode, key: `${mode}|${JSON.stringify(entries)}`, cells, more, maxLines: 0, shown: cells.length, dense: false };
}

/**
 * Weltzeit zeichnen: eine Zone als zweite Zeitzone (#tz2), mehrere als Leiste, mit ?layout=world als Raster. Nur neu,
 * wenn sich Minute, Sprache, Bezugszeit, Layout oder Bühne geändert haben; liefert dann true (die Größen können sich
 * geändert haben).
 */
function renderWorld(ms) {
  const node = $("world");
  const stage = $("clock-stage");
  // state.picked: das gewählte Layout. state.layout kann davon abweichen, wenn das Raster nicht passt (fitTime).
  const mode = world.worldMode(params.tz ? params.tz.length : 0, state.picked, world.worldAllowed(params.show));
  const entries = world.worldEntries(params.tz, params.tzl, { fallback: mode === "grid" });
  const single = mode === "single";
  const clock12 = { h12: params.h12 };
  setHidden($("tz2"), !single);
  if (single) {
    setText($("tz2-label"), entries[0].label);
    setText($("tz2-time"), zoneClock(world.worldRow(ms, entries[0], 0, undefined, clock12)));
  }
  if (mode !== "bar" && mode !== "grid") {
    if (state.world) { node.replaceChildren(); state.world = null; }
    setHidden(node, true);
    stage.removeAttribute("data-world");
    stage.removeAttribute("data-world-flow");
    stage.removeAttribute("data-world-dense");
    state.worldKey = "";
    return false;
  }
  if (!state.world || state.world.key !== `${mode}|${JSON.stringify(entries)}`) {
    buildWorld(mode, entries);
    state.worldKey = "";
  }
  const w = state.world;
  const ref = worldRef(ms);
  const grid = world.worldGrid(entries.length, state.stage.width, state.stage.height);
  const key = `${Math.floor(ms / 60_000)}|${language()}|${ref}|${state.picked}|${mode === "grid" ? grid.flow : Math.round(state.stage.width)}x${Math.round(state.stage.height)}`;
  if (key === state.worldKey) return false;
  state.worldKey = key;
  w.maxLines = mode === "bar" ? world.worldLines(state.picked, state.stage.height, entries.length, state.stage.width) : entries.length;
  if (mode === "grid") {
    setAttr(stage, "data-world-flow", grid.flow);   // Spalten, Zeilen, Dichte und die Stufe „eine Spalte“ setzt fitGrid
  } else {
    stage.removeAttribute("data-world-flow");
    stage.removeAttribute("data-world-dense");
  }
  const words = { day: t("clock.world_day"), days: t("clock.world_days") };
  const refName = state.utcBig ? "UTC" : (tcForeignOffset(ms) === null ? t("clock.local") : kit.zoneLabel(tcZone()));
  world.worldView(ms, entries, ref, undefined, clock12).forEach((row, index) => {
    const item = w.cells[index];
    setText(item.time, row.time);
    setText(item.ampm, row.ampm ? ` ${row.ampm}` : "");   // mit Leerzeichen wie bei der großen Zeit (Screenreader)
    setText(item.delta, row.delta);
    setAttr(item.delta, "title", t("clock.world_delta_title", { ref: refName }));
    setText(item.day, world.dayShiftText(row.day, words));
    setText(item.sun, row.night ? world.MOON : world.SUN);
    const phase = t(row.night ? "clock.world_night" : "clock.world_daytime");
    setAttr(item.sun, "aria-label", phase);
    setAttr(item.sun, "title", phase);
    setAttr(item.cell, "data-day", String(row.day));
    setAttr(item.cell, "data-night", row.night ? "1" : "0");
  });
  setAttr(node, "aria-label", t("clock.world_label"));
  return true;
}

/** Sichtbare Teile der Leiste (Zellen und „+2“) mit ihren Rechtecken. */
function worldBoxes() {
  return [...$("world").children].filter((child) => !child.hidden).map((child) => child.getBoundingClientRect());
}

/** Zeilen, die die sichtbaren Teile der Leiste gerade belegen (world.lineCount: „+2“ zählt nicht als eigene Zeile). */
function worldLineCount() {
  return world.lineCount(worldBoxes());
}

/** Nur die ersten `shown` Zonen zeigen; „+2“ nennt, wie viele fehlen. 0: Leiste bzw. Raster verschwinden ganz. */
function showWorld(shown) {
  const w = state.world;
  w.cells.forEach((item, index) => setHidden(item.cell, index >= shown));
  const rest = w.cells.length - shown;
  setHidden(w.more, !(rest && shown));
  if (rest && shown) {
    setText(w.more, `+${rest}`);
    const label = t("clock.world_more", { count: rest });   // Einzahl und Mehrzahl aus dem Katalog
    setAttr(w.more, "aria-label", label);
    setAttr(w.more, "title", label);
  }
  setHidden($("world"), shown === 0);
  setAttr($("clock-stage"), "data-world", shown ? w.mode : "off");
  w.shown = shown;
}

/**
 * Leiste auf höchstens maxLines Zeilen kürzen: Zonen vom Ende her ausblenden, bis es passt. 0 Zeilen (oder nichts
 * passt): Die Leiste verschwindet ganz. Nur im Modus „bar“.
 */
function trimWorld(maxLines) {
  const w = state.world;
  if (!w || w.mode !== "bar") return;
  let shown = maxLines > 0 ? w.cells.length : 0;
  showWorld(shown);
  while (shown > 0 && worldLineCount() > maxLines) {
    shown -= 1;
    showWorld(shown);
  }
}

/**
 * Liegt die Leiste ganz in der Bühne? Geprüft wird jede sichtbare Zelle, nicht nur die Box der Leiste: Eine Zelle
 * bricht nicht um und kann breiter sein als die Leiste (Banner: höchstens 45 % der Breite).
 */
function worldInside() {
  const stage = $("clock-stage").getBoundingClientRect();
  return [$("world").getBoundingClientRect(), ...worldBoxes()].every((box) => box.left >= stage.left - 0.5
    && box.right <= stage.right + 0.5 && box.top >= stage.top - 0.5 && box.bottom <= stage.bottom + 0.5);
}

/** Steht main als Zeile (Streifen, Layout world im Banner-Format)? */
function rowMain(main) {
  const style = window.getComputedStyle(main);
  return style.display === "flex" && style.flexDirection === "row";
}

/** Fläche für das Raster (Layout world): main ohne die übrigen Zeilen bzw. Spalten, mit 4 % Luft. */
function worldAvail(main) {
  const node = $("world");
  const style = window.getComputedStyle(main);
  const row = rowMain(main);
  let rest = 0;
  let items = 0;
  for (const child of main.children) {
    if (child.hidden) continue;
    const cs = window.getComputedStyle(child);
    const box = child.getBoundingClientRect();
    if (cs.display === "none" || cs.position === "absolute" || (!box.width && !box.height)) continue;
    items += 1;
    if (child === node) continue;
    rest += row ? box.width : box.height + (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0);
  }
  const own = window.getComputedStyle(node);
  const gaps = Math.max(0, items - 1) * (parseFloat(row ? style.columnGap : style.rowGap) || 0);
  if (row) return { width: Math.max(1, main.clientWidth * 0.96 - rest - gaps), height: Math.max(1, main.clientHeight * 0.96) };
  return { width: Math.max(1, main.clientWidth * 0.96),
    height: Math.max(1, main.clientHeight * 0.96 - rest - gaps - (parseFloat(own.marginTop) || 0) - (parseFloat(own.marginBottom) || 0)) };
}

/**
 * Raster einpassen (--world-fit), gemessen mit der Zeit in ihrer Grundgröße. Liefert, ob es danach passt (die Fläche
 * hat schon 4 % Luft, darum zählt 1 % Überstand aus der Rundung der Anpassung noch als passend).
 */
function fitWorld(main) {
  const node = $("world");
  root.style.setProperty("--fit", "1");
  const measure = () => {
    const box = node.getBoundingClientRect();
    return box.width && box.height ? { needed: { width: box.width, height: box.height }, available: worldAvail(main) } : null;
  };
  const factor = kit.fitConverge((fit) => {
    root.style.setProperty("--world-fit", String(fit));
    return measure();
  }, { rounds: 6 });
  root.style.setProperty("--world-fit", String(factor));
  const got = measure();
  return !got || (got.needed.width <= got.available.width * 1.01 && got.needed.height <= got.available.height * 1.01);
}

/** Kleinste Schrift im Raster (px): Kurzname und Zeile mit Abweichung. */
function worldSmallest() {
  const w = state.world;
  let size = Infinity;
  for (const item of w.cells.slice(0, Math.max(1, w.shown))) {
    for (const part of [item.cell.firstElementChild, item.delta, ...(item.ampm.textContent ? [item.ampm] : [])]) size = Math.min(size, parseFloat(window.getComputedStyle(part).fontSize) || 0);
  }
  return size;
}

/**
 * Raster des Layouts world einpassen, danach bekommt die Zeit den Rest (fitOnce). Stufen (world.worldSteps): alle Zonen
 * mit Kurzname, Uhrzeit und Abweichung übereinander; wird die Schrift dabei kleiner als WORLD_MIN_PX, einzeilige Zellen
 * (data-world-dense); auf Flächen, die höher als breit sind, jeweils auch als eine Spalte; reicht das nicht, fallen
 * Zonen vom Ende her weg („+2“), zuletzt das ganze Raster (fitTime zeigt die Uhr dann im automatischen Layout).
 */
function fitGrid(main) {
  const w = state.world;
  const node = $("world");
  const stage = $("clock-stage");
  const total = w.cells.length;
  for (const step of world.worldSteps(total, state.stage.width, state.stage.height)) {
    const grid = world.worldGrid(step.shown + (step.shown < total ? 1 : 0), state.stage.width, state.stage.height, { list: step.list });
    node.style.setProperty("--world-cols", String(grid.cols));
    node.style.setProperty("--world-rows", String(grid.rows));
    setAttr(stage, "data-world-flow", grid.flow);
    if (step.dense) setAttr(stage, "data-world-dense", "1");
    else stage.removeAttribute("data-world-dense");
    w.dense = step.dense;
    showWorld(step.shown);
    if (fitWorld(main) && worldSmallest() >= WORLD_MIN_PX - 0.05) return;
  }
  showWorld(0);
}

// --- Osterei: Schaltsekunde ------------------------------------------------------------
function renderEgg(nowMs) {
  const status = state.status || {};
  const kind = state.status ? kit.leapEgg(nowMs, status.leap, status.leap_next) : null;
  const node = $("leap-egg");
  if (!kind) { node.hidden = true; return; }
  const text = t(`clock.egg_${kind}`);
  if (node.textContent !== text) node.textContent = text;
  node.hidden = false;
}

// --- Zustandsband ------------------------------------------------------------------
function renderBand() {
  const band = $("band");
  const s = state.status;
  const stale = !state.lastOk || performance.now() - state.lastOk > STALE_MS;
  const display = syncInfo().state;
  state.bandSync = display;
  let tone; let main; const detail = [];
  if (!s) {
    tone = "unknown";
    main = state.error ? t("clock.no_connection", { error: state.error }) : t("clock.connecting");
  } else if (stale) {
    tone = "stale";
    const ago = Math.round((performance.now() - state.lastOk) / 1000);
    main = t("clock.no_connection_since", { seconds: ago });
    detail.push(t("clock.stale_detail"));
  } else {
    tone = ["good", "warn", "crit"].includes(s.level) ? s.level : "warn";
    if (!s.running) main = t("clock.chrony_down");
    else if (!s.synchronised) main = s.source_kind ? t("clock.unsynced_kind", { kind: s.source_kind }) : t("clock.unsynced");
    else main = t("clock.synced", { state: t(`clock.state.${tone}`), source: sourceText(s.source_kind, s.source) });
    // Server synchron, Anzeige aber unsicher (Schranke über maxerr, Uhrsprung): nicht als grünes „synchron“ melden.
    if (display === "degraded") {
      if (tone === "good") tone = "warn";
      main = t("clock.band_unsure", { server: main });
    }
    if (typeof s.accuracy === "number") detail.push(t("clock.server_acc", { acc: fmtAccuracy(s.accuracy * 1000) }));
    if (s.leap && s.leap !== "Normal" && s.leap !== "Not synchronised") detail.push(t("clock.leap_announced", { leap: s.leap }));
  }
  if (state.sync) detail.push(t("clock.match_acc", { acc: fmtAccuracy(state.sync.accuracy), rtt: fmtAccuracy(state.sync.rtt).replace("± ", "") }));
  renderChips(Boolean(s) && !stale);
  setAttr(band, "data-state", tone);
  setText($("band-main"), main);
  setText($("band-detail"), detail.join(" · "));
  setText($("band-wake"), state.wakeText);
  setAttr(band, "title", t("clock.band_title"));
}

/**
 * Marken für PTP und Holdover im Band (Symbol und Text) und das Holdover-Symbol für Kachel und Streifen. live: Es gibt
 * eine aktuelle Antwort des Servers – sonst ist der Zustand unbekannt und es steht nichts da.
 */
function renderChips(live) {
  const chips = live ? kit.statusChips(state.status) : { ptp: null, holdover: null };
  const ptpChip = $("chip-ptp");
  setHidden(ptpChip, !chips.ptp);
  if (chips.ptp) {
    setAttr(ptpChip, "data-state", chips.ptp.state);
    setAttr(ptpChip, "data-level", chips.ptp.level);
    setText($("chip-ptp-icon"), chips.ptp.icon);
    setText($("chip-ptp-text"), t(`clock.ptp_state.${chips.ptp.state}`));
    setAttr(ptpChip, "title", t("clock.ptp_title"));
  }
  const hold = chips.holdover;
  const holdText = hold ? (hold.span ? t("clock.holdover_since", { since: hold.span }) : t("clock.holdover")) : "";
  setHidden($("chip-hold"), !hold);
  // Im Band (Live-Region) steht die Dauer in einem eigenen Element mit aria-live="off": Sie ändert sich jede Minute
  // und würde sonst während eines langen Holdovers jede Minute angesagt. Angesagt wird nur, dass er beginnt und endet.
  setText($("chip-hold-text"), hold ? t("clock.holdover") : "");
  setText($("chip-hold-since"), hold && hold.span ? t("clock.holdover_span", { since: hold.span }) : "");
  if (hold) setAttr($("chip-hold"), "title", t("clock.holdover_title"));
  setHidden($("band-status"), !(chips.ptp || hold));
  setHidden($("clock-hold"), !hold);
  setText($("clock-hold-text"), holdText);
  // Im Streifen steht das Symbol in der Zeile der Uhr: kommt oder geht es, die Zeit neu einpassen.
  const key = hold ? "hold" : "";
  if (key !== state.chipKey) {
    state.chipKey = key;
    if (state.face) fitTime();
  }
}

// --- ⓘ (klein, ohne ui.js – siehe Kopf) --------------------------------------------------
let openInfo = null;
function closeInfo(focus = false) {
  if (!openInfo) return;
  const { button, node } = openInfo;
  node.remove();
  button.setAttribute("aria-expanded", "false");
  openInfo = null;
  if (focus) button.focus();
}

function infoButton(titleKey, textKey) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "info";
  button.setAttribute("aria-expanded", "false");
  const glyph = document.createElement("span");
  glyph.className = "info-glyph";
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = "i";
  button.append(glyph);
  const label = () => button.setAttribute("aria-label", t("clock.info_label", { title: t(titleKey) }));
  label();
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (openInfo && openInfo.button === button) { closeInfo(); return; }
    closeInfo();
    const node = document.createElement("div");
    node.className = "popover clock-popover";
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-label", t(titleKey));
    const title = document.createElement("strong");
    title.className = "popover-title";
    title.textContent = t(titleKey);
    const text = document.createElement("p");
    text.textContent = t(textKey);
    node.append(title, text);
    document.body.append(node);
    const rect = button.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    node.style.width = `${width}px`;
    node.style.left = `${Math.min(window.innerWidth - width - 12, Math.max(12, rect.left + rect.width / 2 - width / 2)) + window.scrollX}px`;
    const below = rect.bottom + 8 + node.offsetHeight < window.innerHeight;
    node.style.top = `${(below ? rect.bottom + 8 : Math.max(8, rect.top - node.offsetHeight - 8)) + window.scrollY}px`;
    button.setAttribute("aria-expanded", "true");
    openInfo = { button, node };
  });
  button.relabel = label;
  return button;
}
document.addEventListener("click", (event) => {
  if (openInfo && !openInfo.node.contains(event.target)) closeInfo();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (openInfo) { closeInfo(true); return; }
  // Prüfbild: Esc beendet es – auch mit lock=1 (dort sind alle anderen Tasten aus). Eine offene Kürzel-Übersicht
  // schließt zuerst (onKey).
  if (state.test && $("keys").hidden) { event.preventDefault(); stopTest(); }
});
window.addEventListener("resize", () => closeInfo());

// --- Panels: Ton und „Mein Gerät“ ----------------------------------------------------------
function togglePanel(buttonId, panelId, open) {
  const panel = $(panelId);
  const show = open === undefined ? panel.hidden : open;
  panel.hidden = !show;
  $(buttonId).setAttribute("aria-expanded", show ? "true" : "false");
  // Mit offenem Panel bekommt die Bühne eine Mindesthöhe (sonst drückte das Panel sie auf null zusammen).
  document.body.classList.toggle("has-panel", ["tone-panel", "device-panel", "custom-panel", "timer-panel"].some((id) => !$(id).hidden));
  return show;
}

// --- Panel „Anpassen“ (Link-Baukasten auf der Uhr) --------------------------------------------
/**
 * Rohwerte, mit denen die Seite läuft (Adresse, Profil oder gemerkter Stand) – Ausgangspunkt des Formulars. Ohne die
 * Parameter, die nur aus der Adresse wirken (Prüfbild test=sync): Das Formular hat kein Feld dafür, „Link kopieren“
 * nähme sie sonst unsichtbar mit.
 */
function currentRaw() {
  const search = window.location.search;
  const query = state.profile ? link.effectiveQuery({ search, profile: state.profile.params, zones: ZONES })
    : link.effectiveQuery({ search, stored: store(link.STORE_KEY) || "", zones: ZONES });
  return link.profileParams(link.rawParams(query, ZONES));
}

function customStatus(text) {
  setText($("custom-status"), text);
}

function openCustom() {
  if (!togglePanel("mode-custom", "custom-panel")) return;
  state.customRaw = currentRaw();
  const form = link.buildForm({ values: state.customRaw, prefix: "custom", zones: ZONES, exclude: link.STORE_SKIP,
    excludeValues: link.STORE_SKIP_VALUES, onChange: () => customStatus("") });
  $("custom-form").replaceChildren(form);
  setHidden($("custom-url-note"), link.storedApplies(window.location.search));
  customStatus("");
}

function applyCustom() {
  const query = link.storedQuery(link.buildQuery(state.customRaw || {}, ZONES), ZONES);   // ohne kiosk/lock/layout=tile
  if (query) store(link.STORE_KEY, query);
  else removeStored(link.STORE_KEY);
  window.location.assign("/clock");
}

function resetCustom() {
  removeStored(link.STORE_KEY);
  window.location.assign("/clock");
}

async function copyCustom() {
  const href = `${window.location.origin}${link.clockHref(link.buildQuery(state.customRaw || {}, ZONES))}`;
  customStatus(await copyText(href) ? t("clock.custom_copied") : t("clock.custom_copy_failed", { link: href }));
}

function removeStored(key) {
  try { window.localStorage.removeItem(key); } catch (error) { /* privates Fenster */ }
}

// --- Ton auf der Sekunde ---------------------------------------------------------------
function toneStatus(text) {
  setText($("tone-status"), text);   // aria-live: denselben Satz nicht jede Sekunde neu ansagen lassen
}

function toneAccuracyText() {
  if (!state.sync) return t("clock.tone_unsynced");
  // Abgleich (± halbe RTT) plus Raster der Audiozeit (mit Ausgabezeitstempel ≈ 1 ms, sonst ≈ 3 ms).
  const extra = state.tone && state.tone.exact ? 1 : 3;
  return t("clock.tone_running", { acc: fmtAccuracy(state.sync.accuracy + extra) });
}

async function startTone(mode) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) { toneStatus(t("clock.tone_unsupported")); return; }
  if (!state.tone) {
    let ctx;
    try { ctx = new Ctx({ latencyHint: "interactive" }); } catch (error) { toneStatus(t("clock.tone_unsupported")); return; }
    state.tone = { ctx, mode, last: -Infinity, exact: false };
  }
  state.tone.mode = mode;
  state.tone.last = -Infinity;
  try { await state.tone.ctx.resume(); } catch (error) { /* bleibt stumm, Anzeige läuft trotzdem */ }
  $("tone-seconds").setAttribute("aria-pressed", mode === "seconds" ? "true" : "false");
  $("tone-countdown").setAttribute("aria-pressed", mode === "countdown" ? "true" : "false");
  toneTick(trueMs());
}

function stopTone() {
  if (state.tone) {
    state.tone.ctx.close().catch(() => {});
    state.tone = null;
  }
  $("tone-seconds").setAttribute("aria-pressed", "false");
  $("tone-countdown").setAttribute("aria-pressed", "false");
  $("tone-count").hidden = true;
  toneStatus(t("clock.tone_stopped"));
}

function toneTick(nowMs) {
  const tone = state.tone;
  if (!tone) return;
  const { ctx } = tone;
  if (ctx.state === "running") {
    // Serverzeit zum selben performance.now() übergeben (Versatz 0): Der Ton folgt dem Anker, nicht Date.now().
    const perf = performance.now();
    const clock = kit.audioClock(ctx, perf, trueMs(perf), 0);
    tone.exact = clock.exact;
    for (const planned of kit.planTones(clock, { mode: tone.mode, afterSecond: tone.last, horizonMs: 1500 })) {
      tone.last = planned.second;
      if (planned.at > ctx.currentTime + 0.005) kit.scheduleTone(ctx, planned);
    }
  }
  const count = $("tone-count");
  if (tone.mode === "countdown") {
    const value = kit.countdownValue(nowMs);
    const into = Math.floor(nowMs / 1000) % 60;
    count.textContent = value === null ? t("clock.countdown_wait", { seconds: 60 - kit.COUNTDOWN_SECONDS - into })
      : (value === 0 ? t("clock.countdown_now") : String(value));
    count.dataset.value = value === null ? "" : String(value);
    count.hidden = false;
  } else {
    count.hidden = true;
  }
  toneStatus(ctx.state === "running" ? toneAccuracyText() : t("clock.tone_blocked"));
}

// --- „Wie falsch geht dein Gerät?“ ---------------------------------------------------------
function renderDevice() {
  if ($("device-panel").hidden) return;
  const node = $("device-value");
  const drift = state.sync ? kit.deviceDrift(state.sync.offset, state.sync.accuracy) : null;
  if (!drift) {
    node.dataset.tone = "unknown";
    $("device-text").textContent = t("clock.device_measuring");
    $("device-line").textContent = t("clock.device_line_unknown");
    return;
  }
  node.dataset.tone = drift.tone;
  if (drift.dir === "uncertain") {
    $("device-text").textContent = t("clock.device_uncertain");
    $("device-line").textContent = t("clock.device_line_uncertain", { acc: fmtAccuracy(state.sync.accuracy) });
    return;
  }
  $("device-text").textContent = drift.dir === "exact" ? t("clock.device_exact")
    : t(drift.dir === "behind" ? "clock.device_behind" : "clock.device_ahead", { value: kit.fmtDrift(drift.abs) });
  $("device-line").textContent = t(`clock.device_line_${drift.tone}`, { acc: fmtAccuracy(state.sync.accuracy) });
}

// --- Bildschirm wach halten ---------------------------------------------------------
async function keepAwake() {
  if (!("wakeLock" in navigator)) {
    state.wakeText = window.isSecureContext ? "" : t("clock.wake_https");
    renderBandLive();
    return;
  }
  try {
    state.wake = await navigator.wakeLock.request("screen");
    state.wakeText = t("clock.wake_on");
    state.wake.addEventListener("release", () => { state.wakeText = ""; renderBandLive(); });
  } catch (error) {
    state.wakeText = "";
  }
  renderBandLive();
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    keepAwake();
    restartSweep();
    if (state.design === "tc" && state.face && state.face.tc) { measureGrain(); tcLoop(); }
    burst();   // nach dem Aufwachen (Tablet im Standby) sofort neu abgleichen
  }
  // Im Hintergrund drosselt der Browser die Zeitgeber: Töne eines laufenden Countdowns jetzt bis zum Ziel vorausplanen.
  if (document.hidden && state.cdTone) renderCountdown();
});

// --- Countdown, Count-up, Timer (Studiouhr A5) -------------------------------------------------
const CD_ICONS = { none: "▷", warn: "△", alert: "▲", final: "■", over: "+", done: "■", watch: "◷", paused: "‖" };

/** Gibt es gerade etwas zu zählen? ?until= und ?timer= immer, die Stoppuhr erst nach dem ersten Start. */
function countdownActive() {
  return COUNT_MODE !== "watch" || state.timer !== null;
}
function countdownMain() {
  return params.cd === "main" && countdownActive();
}

/** Zeitzone für ?until=: die des Servers (zone aus /api/v1/time); fehlt sie, die des Browsers; undefined: noch offen. */
function countZone() {
  return cd.untilZone(state.status, { failed: Boolean(state.error), waitedMs: performance.now(), anchored: Boolean(state.anchor) });
}
function browserZone() {
  try { return new Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (error) { return null; }
}

/**
 * Beschriftung ohne ?label=: „bis 20:15“ (ISO: „bis 2026-12-31 23:59“), mit Zone, wenn sie von der des Browsers abweicht.
 * Eingebaute Ziele (?goal=): „bis Neujahr“ usw.
 */
function untilLabel(zone) {
  if (!params.until) return t(`clock.goal_label.${params.goal}`);
  const u = params.until;
  const clock = `${pad(u.h)}:${pad(u.m)}${u.s ? `:${pad(u.s)}` : ""}`;
  const time = u.kind === "iso" ? `${u.y}-${pad(u.mo)}-${pad(u.d)} ${clock}` : clock;
  if (zone && zone !== browserZone()) return t("clock.cd_until_zone", { time, zone: kit.zoneLabel(zone) });
  return t("clock.cd_until", { time });
}

/** Zehntel anhängen (Taste T, nur lokale Timer): „−00:04,3“ bzw. „+00:00:01,2“ – abgerundet auf der echten Restzeit. */
function withTenths(view, remainingMs) {
  const decimal = language() === "en" ? "." : ",";
  const ms = Math.abs(remainingMs);
  if (view.phase === "before") {
    return `${cd.MINUS}${cd.fmtSpan(Math.floor(ms / 1000), { dayUnit: t("clock.cd_day") })}${decimal}${Math.floor((ms % 1000) / 100)}`;
  }
  if (view.phase === "over") {
    return `+${cd.fmtSpan(Math.floor(ms / 1000), { hours: true, dayUnit: t("clock.cd_day") })}${decimal}${Math.floor((ms % 1000) / 100)}`;
  }
  return view.text;
}

function levelText(view) {
  if (["warn", "alert", "final"].includes(view.level)) return t("clock.cd_below", { limit: cd.fmtLimit(view.limit) });
  if (view.level === "over") return t("clock.cd_over");
  if (view.level === "done") return t("clock.cd_done");
  return "";
}

/**
 * Countdown-Zeile zeichnen (aus tick je Sekunde, bei laufendem lokalen Timer zusätzlich zu dessen eigenen Wechseln).
 * nowMs: angezeigte Serverzeit (mit ?lead=). Alles nur per textContent, Klassen und data-Attributen.
 * Liefert die Restzeit (ms) bis zum Ziel, solange es näher rückt (?until=, laufender Timer), sonst NaN – für den
 * E-Ink-Takt.
 */
function renderCountdown(nowMs = serverMs()) {
  const node = $("cd");
  const active = countdownActive();
  setHidden(node, !active);
  if (active) setAttr(root, "data-cd", params.cd);
  else root.removeAttribute("data-cd");
  if (!active) {
    if (state.ended) { state.ended = false; delete root.dataset.cdEnd; }
    return NaN;
  }
  const opts = { after: params.after, warn: params.warn, dayUnit: t("clock.cd_day"), coarse: params.eink };
  const tenths = state.tenths && !params.eink;
  let view;
  let label;
  let status = "";
  let toneTarget = NaN;
  let remaining = NaN;
  if (COUNT_MODE === "until") {
    const zone = countZone();
    // Andere Zone als bisher (erste Antwort des Servers): Restzeit springt – das ist kein erlebter Übergang, also
    // weder eine Schwelle ansagen noch Töne aus der alten Planung behalten.
    if (zone !== state.cdZone) {
      state.cdZone = zone;
      state.cdPrev = NaN;
      stopCountdownTones();
    }
    if (zone === undefined) {
      view = cd.countdownView(NaN, opts);   // „--:--“ ohne Stufe, bis die Zone des Servers bekannt ist
      label = params.label || untilLabel(null);
    } else {
      // ?until= geht vor; sonst ein eingebautes Ziel (?goal=, gleiche Rechenbasis). Ohne Zeitumstellung in Sicht: NaN.
      const target = params.until ? cd.untilTarget(params.until, nowMs, zone) : fx.goalTarget(params.goal, nowMs, zone);
      remaining = target - nowMs;
      view = cd.countdownView(remaining, opts);
      label = params.label || untilLabel(zone);
      if (!Number.isFinite(target)) status = t("clock.goal_none");
      else toneTarget = target;   // absolute Serverzeit: der Ton fällt auf das Ziel, die Anzeige läuft um ?lead= vor
    }
  } else {
    const perf = performance.now();
    advancePomo(perf);
    const read = cd.timerRead(state.timer, perf);
    if (read.remaining === null) {
      view = { phase: "watch", level: "none", seconds: NaN,
        text: cd.stopwatchText(read.elapsed, { tenths, decimal: language() === "en" ? "." : ",", dayUnit: opts.dayUnit }) };
      label = params.label || t("clock.cd_stopwatch");
    } else {
      // Eieruhr aus dem Panel und Pomodoro: nur Farbstufen, die unterwegs erreicht werden – eine 3-min-Eieruhr ist nicht
      // von Anfang an „unter 5 min“ gelb.
      const local = state.pomo || state.eggMs ? { ...opts, warn: localWarn(state.timer.duration) } : opts;
      view = cd.countdownView(read.remaining, local);
      if (tenths) view = { ...view, text: withTenths(view, read.remaining) };
      label = params.label || timerLabel(read);
      if (read.state === "running") {
        toneTarget = trueMs(perf) + read.remaining;
        remaining = read.remaining;
      }
    }
    // Mit ?lock=1 fehlen Kürzel und Start-Knopf: dann nicht „Leertaste oder Start“ versprechen.
    // Ohne Knöpfe (Kiosk, OBS) bleibt nur die Leertaste.
    const keysOnly = !params.lock && (!CONTROLS.actions || params.kiosk);
    if (read.state === "idle") status = keysOnly ? t("clock.cd_idle_keys") : t(params.lock ? "clock.cd_locked" : "clock.cd_idle");
    else if (read.state === "paused") status = t("clock.cd_paused");
    else if (state.pomo && state.pomo.done) status = t("clock.pomo_done", { count: state.pomo.done });
    // Eieruhr abgelaufen: deutlich (Rahmen, „Zeit ist um!“), ohne Blinken. Pomodoro wechselt stattdessen die Phase.
    const ended = !state.pomo && fx.timerEnded(read);
    if (ended) status = t("clock.cd_end");
    if (ended !== state.ended) {
      state.ended = ended;
      if (ended) root.dataset.cdEnd = "1";
      else delete root.dataset.cdEnd;
    }
    const button = read.state === "running" ? "clock.cd_stop" : (read.state === "paused" ? "clock.cd_resume" : "clock.cd_start");
    setText($("cd-toggle"), t(button));
    setHidden($("cd-actions"), Boolean(params.lock) || !CONTROLS.actions);
    setHidden($("cd-plus"), read.remaining === null || Boolean(state.pomo));
  }
  const paused = state.timer && state.timer.state === "paused";
  setAttr(node, "data-level", view.level);
  setAttr(node, "data-phase", view.phase);
  setText($("cd-icon"), CD_ICONS[paused ? "paused" : (view.phase === "watch" ? "watch" : view.level)] || "");
  setText($("cd-label"), label);
  setText($("cd-time"), view.text);
  setText($("cd-state"), status || levelText(view));
  setText($("cd-now"), params.eink ? hms(new Date(nowMs)).slice(0, 5) : hms(new Date(nowMs)));
  // Screenreader: nur an Schwellen (1 min, 10 s, Ziel), nie jede Sekunde.
  const step = cd.announceStep(state.cdPrev, view.seconds);
  state.cdPrev = view.seconds;
  if (step !== null) say(step === 0 ? t("clock.say_target") : t("clock.say_left", { limit: cd.fmtLimit(step) }));
  if (Number.isFinite(toneTarget)) countdownTones(toneTarget);
  // Neue Breite (−MM:SS → −HH:MM:SS) oder Art: Zeit neu einpassen, damit nichts umbricht.
  const shape = `${params.cd}|${view.phase}|${view.text.length}|${label}|${state.layout}`;
  if (shape !== state.cdShape) {
    state.cdShape = shape;
    fitTime();
  }
  return remaining;
}

/** Audiouhr für ?beep= anlegen bzw. fortsetzen (gesture: bei einer Bedienung). Liefert den Zustand oder null. */
function countdownAudio(gesture) {
  if (!(beepCount() > 0) || params.eink) return null;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  if (!state.cdTone) {
    try { state.cdTone = { ctx: new Ctx({ latencyHint: "interactive" }), lastK: Infinity, target: NaN, oscs: [] }; } catch (error) { return null; }
  }
  if (gesture && state.cdTone.ctx.state !== "running") state.cdTone.ctx.resume().catch(() => {});
  return state.cdTone;
}

/**
 * Wie viele Sekunden vor dem Ziel gepiept wird: ?beep=, sonst bei „Ton am Ende“ (Panel Timer, nur lokale Timer)
 * fx.END_BEEPS. 0: kein Ton.
 */
function beepCount() {
  if (params.beep > 0) return params.beep;
  return state.endTone && COUNT_MODE !== "until" ? fx.END_BEEPS : 0;
}

/** Piep in den letzten ?beep= Sekunden vor dem Ziel (Serverzeit), langer Ton auf dem Ziel. */
function countdownTones(target) {
  const tone = countdownAudio(false);
  if (!tone || tone.ctx.state !== "running") return;
  const perf = performance.now();
  // Pomodoro: Die nächste Phase beginnt genau auf dem alten Ziel – dessen langer Ton darf ausklingen.
  const passed = state.pomo && Number.isFinite(tone.target) && tone.target <= trueMs(perf) && target > tone.target;
  if (passed) tone.lastK = Infinity;
  else if (!Number.isFinite(tone.target) || Math.abs(tone.target - target) > 1500) stopCountdownTones();   // neues Ziel
  tone.target = target;
  const clock = kit.audioClock(tone.ctx, perf, trueMs(perf), 0);
  const horizonMs = cd.toneHorizonMs(document.hidden);
  for (const planned of cd.planCountdownTones(clock, target, beepCount(), { lastK: tone.lastK, horizonMs })) {
    tone.lastK = planned.k;
    if (planned.at > tone.ctx.currentTime + 0.005) {
      const osc = kit.scheduleTone(tone.ctx, planned);
      tone.oscs.push(osc);
      osc.addEventListener("ended", () => { tone.oscs = tone.oscs.filter((item) => item !== osc); });
    }
  }
}

/** Geplante Countdown-Töne verwerfen (Anhalten, Zurücksetzen, neues Ziel): Was schon im Voraus geplant ist, verstummt. */
function stopCountdownTones() {
  if (!state.cdTone) return;
  state.cdTone.oscs = kit.stopTones(state.cdTone.oscs);
  state.cdTone.lastK = Infinity;
  state.cdTone.target = NaN;
}

/** Eigener Takt eines laufenden lokalen Timers: genau zum nächsten Wechsel der Anzeige (Zehntel: alle 100 ms). */
function scheduleTimer() {
  clearTimeout(state.timerTimer);
  if (!state.timer || state.timer.state !== "running" || params.eink) return;
  const read = cd.timerRead(state.timer, performance.now());
  state.timerTimer = setTimeout(() => { renderCountdown(); scheduleTimer(); }, cd.timerDelay(read, state.tenths ? 100 : 1000));
}

/** Beschriftung eines lokalen Timers: Pomodoro mit Runde und Phase, sonst „Timer 05:00“ (Dauer der Eieruhr). */
function timerLabel(read) {
  if (state.pomo) return t(`clock.pomo_${state.pomo.phase}`, { round: state.pomo.round });
  const duration = state.timer && state.timer.duration !== null ? state.timer.duration : params.timer;
  return t("clock.cd_timer", { time: cd.fmtSpan(Math.round((state.eggMs || params.timer || duration || read.elapsed) / 1000)) });
}

/**
 * Farbstufen (?warn=) für eine Eieruhr bzw. Pomodoro-Phase der Dauer duration: Schwellen ab der Dauer fallen weg (NaN,
 * cd.countdownView überspringt sie), die übrigen behalten ihre Stufe.
 */
function localWarn(duration) {
  return params.warn.map((limit) => (limit * 1000 < duration ? limit : NaN));
}

/** Pomodoro: Ist die Phase um, beginnt die nächste genau an ihrem Ende (fx.pomoAdvance) – mit Ansage und Hinweis. */
function advancePomo(perf) {
  if (!state.pomo) return;
  const next = fx.pomoAdvance(state.pomo, state.timer, perf);
  if (!next.steps) return;
  state.pomo = next.pomo;
  state.timer = next.timer;
  state.cdPrev = NaN;   // neue Phase: keine Schwelle aus der alten ansagen
  const text = t(`clock.pomo_say_${state.pomo.phase === "work" ? "work" : state.pomo.phase}`, { round: state.pomo.round });
  say(text);
  hint(text);
}

/** Leertaste/Start: lokalen Timer starten oder anhalten; ohne Ziel startet die Stoppuhr. ?until= lässt sich nicht anhalten. */
function toggleTimer() {
  if (COUNT_MODE === "until") { hint(t("clock.hint_no_timer")); return; }
  if (!state.timer) state.timer = cd.timerNew(null);
  state.timer = cd.timerToggle(state.timer, performance.now());
  stopCountdownTones();
  state.cdPrev = NaN;
  renderCountdown();
  scheduleTimer();
  einkRetick();
}

/** R: zurücksetzen; die Stoppuhr verschwindet dann wieder. */
function resetTimer() {
  if (COUNT_MODE === "until") { hint(t("clock.hint_no_timer")); return; }
  // Eieruhr aus dem Panel: zurück auf ihre gewählte Dauer (nicht auf die mit „+1 min“ verlängerte); Pomodoro: Runde 1.
  if (state.pomo) state.pomo = fx.pomoReset(state.pomo);
  if (COUNT_MODE !== "timer") state.timer = null;
  else state.timer = cd.timerNew(state.pomo ? fx.pomoPhaseMs(state.pomo) : (state.eggMs || params.timer));
  state.cdPrev = NaN;
  stopCountdownTones();
  clearTimeout(state.timerTimer);
  renderCountdown();
  fitTime();
  einkRetick();
}

/** E-Ink hat keinen eigenen Timer-Takt: nach Start/Anhalten/Zurücksetzen den Minutentakt neu auf den Timer ausrichten. */
function einkRetick() {
  if (!params.eink) return;
  clearTimeout(state.tickTimer);
  tick();
}

// --- Spielereien C1: Eieruhr, Pomodoro, eigene Countdowns (Panel „Timer“) -----------------------------------------
function timerStatus(text) {
  setText($("timer-status"), text);
}

/** Lokalen Timer neu aufsetzen und gleich starten: Eieruhr (ms) oder Pomodoro (pomo). ?until=/?goal= bleiben unberührt. */
function startLocal(duration, pomo = null) {
  if (COUNT_MODE === "until") { hint(t("clock.hint_no_timer")); return false; }
  COUNT_MODE = "timer";
  state.pomo = pomo;
  state.eggMs = pomo ? null : duration;
  state.timer = cd.timerToggle(cd.timerNew(pomo ? fx.pomoPhaseMs(pomo) : duration), performance.now());
  state.cdPrev = NaN;
  state.cdShape = "";
  stopCountdownTones();
  countdownAudio(true);   // Klick: Ton am Ende darf jetzt starten
  renderCountdown();
  scheduleTimer();
  fitTime();
  einkRetick();
  return true;
}

function startEgg(ms) {
  if (startLocal(ms)) timerStatus(t("clock.egg_started", { time: cd.fmtSpan(ms / 1000) }));
}

function startEggInput() {
  const ms = fx.parseEggInput($("egg-input").value);
  if (ms === null) {
    $("egg-input").setAttribute("aria-invalid", "true");
    timerStatus(t("clock.egg_bad"));
    return;
  }
  $("egg-input").setAttribute("aria-invalid", "false");
  startEgg(ms);
}

function startPomo() {
  const pomo = fx.pomoNew(params.pomo, params.pause);
  if (startLocal(null, pomo)) timerStatus(t("clock.pomo_started", { work: cd.fmtLimit(pomo.work / 1000) }));
}

/** „+1 min“ an der Eieruhr: vor dem Ende eine Minute mehr, danach eine Minute ab jetzt. */
function plusMinute() {
  if (!state.timer || state.timer.duration === null || state.pomo) return;
  state.timer = fx.timerAdd(state.timer, fx.EGG_PLUS_MS, performance.now());
  state.cdPrev = NaN;
  stopCountdownTones();
  renderCountdown();
  scheduleTimer();
  einkRetick();
  hint(t("clock.hint_plus"));
}

/** „Ton am Ende“: Der Klick ist die Bedienung, nach der der Browser die Audiouhr starten lässt. */
function toggleEndTone() {
  state.endTone = $("timer-tone").checked;
  if (!state.endTone) {
    stopCountdownTones();
    timerStatus(t("clock.timer_tone_off"));
    return;
  }
  const tone = countdownAudio(true);
  timerStatus(t(tone ? "clock.timer_tone_on" : "clock.tone_unsupported"));
  if (tone && tone.ctx.state !== "running") {
    tone.ctx.resume().then(() => timerStatus(t("clock.timer_tone_on")), () => timerStatus(t("clock.timer_tone_blocked")));
  }
}

/** Panel „Timer“: Schnellwahl, Pomodoro-Zeile, eigene und eingebaute Countdowns – Texte nur per textContent. */
function renderTimerPanel() {
  const blocked = COUNT_MODE === "until";
  setHidden($("timer-blocked"), !blocked);
  const presets = $("egg-presets");
  presets.replaceChildren(...fx.EGG_PRESETS.map((minutes) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "clock-tool";
    button.textContent = t("clock.egg_min", { n: minutes });
    button.disabled = blocked;
    button.addEventListener("click", () => startEgg(minutes * 60_000));
    return button;
  }));
  for (const id of ["egg-start", "pomo-start", "egg-input", "timer-tone"]) $(id).disabled = blocked;
  $("egg-input").placeholder = t("clock.egg_own_hint");
  $("own-until").placeholder = t("clock.own_until_hint");
  const pomo = fx.pomoNew(params.pomo, params.pause);
  setText($("pomo-line"), t("clock.pomo_line", { work: cd.fmtLimit(pomo.work / 1000), brk: cd.fmtLimit(pomo.brk / 1000),
    long: cd.fmtLimit(pomo.long / 1000) }));
  $("timer-tone").checked = state.endTone;
  renderOwn();
  $("goal-list").replaceChildren(...kit.GOALS.map((goal) => {
    const item = document.createElement("li");
    const a = document.createElement("a");
    a.href = link.clockHref(link.buildQuery({ goal }, ZONES));
    a.textContent = t(`clock.goal_name.${goal}`);
    item.append(a);
    return item;
  }));
}

/** Liste der eigenen Countdowns: Link /clock?until=…&label=… und „Entfernen“. */
function renderOwn() {
  const list = $("own-list");
  if (!state.own.length) {
    const empty = document.createElement("li");
    empty.className = "clock-panel-note";
    empty.textContent = t("clock.own_none");
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...state.own.map((own, index) => {
    const item = document.createElement("li");
    const a = document.createElement("a");
    a.href = link.clockHref(link.buildQuery({ until: own.until, label: own.label }, ZONES));
    a.textContent = t("clock.own_open", { label: own.label, until: own.until.replace("T", " ") });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "clock-tool";
    remove.textContent = t("clock.own_delete");
    remove.setAttribute("aria-label", t("clock.own_delete_label", { label: own.label }));
    remove.addEventListener("click", () => {
      saveOwn(fx.ownRemove(state.own, index));
      timerStatus(t("clock.own_removed"));
      (list.querySelector("button") || $("own-label")).focus();
    });
    item.append(a, " ", remove);
    return item;
  }));
}

/** Liste übernehmen und merken. false: Der Browser lässt kein Speichern zu – die Liste gilt nur bis zum Neuladen. */
function saveOwn(list) {
  state.own = list;
  const text = fx.ownText(list);
  let saved = true;
  if (text) saved = store(fx.OWN_KEY, text);
  else removeStored(fx.OWN_KEY);
  renderOwn();
  return saved;
}

function addOwn() {
  const result = fx.ownAdd(state.own, { label: $("own-label").value, until: $("own-until").value });
  for (const id of ["own-label", "own-until"]) $(id).setAttribute("aria-invalid", result.ok ? "false" : "true");
  if (!result.ok) { timerStatus(t("clock.own_bad")); return; }
  $("own-label").value = "";
  $("own-until").value = "";
  timerStatus(t(saveOwn(result.list) ? "clock.own_saved" : "clock.own_unsaved"));
}

function openTimerPanel() {
  if (togglePanel("mode-timer", "timer-panel")) renderTimerPanel();
}

// --- Nachtmodus (C1): gedimmt bzw. Rotlicht, nach Uhrzeit (?dim=) und von Hand -------------------------------------
/**
 * Zustand jetzt: Zeitplan nach der vollen Stunde in der Ortszeit dieses Geräts (nach der Serverzeit gestellt), von Hand
 * umgeschaltet bis zum nächsten Wechsel. Bewusst nicht die groß angezeigte Zone (UTC groß, Design tc in der Zone des
 * Servers): Der Nachtmodus richtet sich nach dem Raum, in dem der Bildschirm steht.
 */
function nightNow() {
  const scheduled = fx.nightScheduled(params.dim, fx.nightHour(serverMs()));
  state.nightOverride = fx.nightOverride({ scheduled, prev: state.nightPrev, override: state.nightOverride });
  state.nightPrev = scheduled;
  return fx.nightView({ scheduled, override: state.nightOverride, red: params.dimred, level: params.dimlevel, eink: params.eink });
}

/** Je Takt: Nur wenn sich der Nachtmodus ändert, Farben und Helligkeit neu setzen. */
function renderNight() {
  const night = nightNow();
  const key = night.on ? `${night.mode}|${night.level}` : "";
  if (key !== state.nightKey) applyModes();
}

function toggleNight() {
  if (!CONTROLS.fun) return;
  state.nightOverride = !nightNow().on;
  applyModes();
  hint(t(state.nightOverride ? "clock.hint_night_on" : "clock.hint_night_off"));
}

// --- Zusätze C2: Mondphase, Nerd-Zeile, Fortschrittsbalken (?show=moon,nerd,progress) ----------------------------
// Standard aus; nie mit fun=0, im Kiosk, in Kachel und Streifen (fx.extrasShown). Gerechnet wird alles hier im Browser
// (clockextras.js). Der Mond und die Kalender-Balken ändern sich einmal je Minute, die Nerd-Zeile und der Balken einer
// Eieruhr im Sekundentakt – nur Text, Attribute und eine CSSOM-Variable je Balken, kein eigener Zeitgeber.
const SOUTH_KEY = "ntp-gui-clock-south";
// hex und roman nur auf Bühnen ab 700 px Höhe und nicht im Banner (clock.css, @container): Dort bräche die Zeile zu oft um.
const NERD_KEYS = ["unix", "hex", "tai", "gps", "mjd", "doy", "iso", "roman"];

/** Hat die Uhr eine Eieruhr bzw. Pomodoro-Phase mit Dauer (für den Balken „timer“)? */
function timerBarAvailable() {
  return COUNT_MODE === "timer" && Boolean(state.timer) && state.timer.duration !== null;
}

/**
 * Zusätze zeichnen. at: { day (Datum der Anzeige als Date, Tag im Jahr und ISO-Woche), offset (ms: Abstand der Zone des
 * angezeigten Datums zu UTC, null: Ortszeit des Geräts – für die Kalender-Balken), h, m (angezeigte Stunde und Minute) }.
 * Ohne at: wie beim letzten Zeichnen.
 */
function renderExtras(nowMs, at = state.extrasAt) {
  state.extrasAt = at;
  // Im Banner mit Countdown unter der Uhr oder Leiste der Weltzeit nur auf höheren Bühnen (fx.extrasShown, crowded).
  const crowded = (countdownActive() && params.cd === "below") || Boolean(state.world && state.world.mode === "bar");
  const shown = state.extrasNoRoom ? [] : fx.extrasShown({ extras: state.extraWish, fun: params.fun, kiosk: params.kiosk,
    layout: state.layout, eink: params.eink, height: state.stage.height, crowded });
  const bars = shown.includes("progress") ? fx.barsFor(params.bars, timerBarAvailable()) : [];
  const key = `${shown.join(",")}|${bars.join(",")}`;
  if (key !== state.extrasKey) {
    state.extrasKey = key;
    setHidden($("extras"), !shown.length);
    setHidden($("moon-box"), !shown.includes("moon"));
    setHidden($("nerd"), !shown.includes("nerd"));
    setHidden($("bars"), !bars.length);
    buildNerd(shown.includes("nerd"));
    buildBars(bars);
    state.moonKey = "";
    state.barsKey = "";
    if (shown.length) {
      renderMoon(nowMs);
      renderNerd(nowMs);
      renderBars(nowMs);
    }
    // Die Zeit bekommt den Rest der Höhe (restHeight). Vor dem ersten Layout nicht: observeStage passt ohnehin ein.
    if (state.face && state.layout) fitTime();
    return;
  }
  if (!shown.length) return;
  const moonDrawn = renderMoon(nowMs);
  renderNerd(nowMs);
  const barsDrawn = renderBars(nowMs);
  // Ändert sich die Höhe der Zusätze (TAI kommt mit der ersten Antwort des Servers, neuer Mondtext, Sprachwechsel), passt
  // watchExtras die Zeit neu ein. Ohne ResizeObserver (alte Engines) wird hier einmal je Minute verglichen.
  if (!EXTRAS_OBSERVED && (moonDrawn || barsDrawn) && state.face) {
    const height = $("extras").offsetHeight;
    if (height !== state.extrasHeight) fitTime();
  }
}

/** Höchstens so oft je Sekunde passt watchExtras neu ein (Schutz gegen ein Hin und Her von Umbruch und Einpassen). */
const EXTRAS_REFITS = 3;
const EXTRAS_OBSERVED = typeof window.ResizeObserver === "function";

/**
 * Höhe der Zusätze beobachten: Wird die Zeile höher oder niedriger als beim letzten Einpassen (etwa weil die Nerd-Zeile
 * mit TAI und GPS umbricht, sobald tai_utc da ist), die Zeit sofort neu einpassen – nicht erst zur nächsten Minute.
 */
function watchExtras() {
  if (!EXTRAS_OBSERVED) return;
  const observer = new window.ResizeObserver(() => {
    if ($("extras").hidden || !state.face || !state.layout) return;
    const height = $("extras").offsetHeight;
    const second = Math.floor(performance.now() / 1000);
    if (state.extrasRefit.second !== second) state.extrasRefit = { second, count: 0 };
    if (height === state.extrasHeight || state.extrasRefit.count >= EXTRAS_REFITS) { checkExtrasRoom(); return; }
    state.extrasRefit.count += 1;
    fitTime();
  });
  // Im Banner teilen sich Countdown, Datum, Zeile mit Zustand, Weltzeit-Leiste und Zusätze die rechte Spalte: Wächst
  // eins davon oder ändert sich die Bühne (nach observeStage angelegt, also nach applyLayout gemeldet), neu prüfen.
  for (const node of [$("clock-stage"), ...$("clock-main").children]) observer.observe(node);
}

/** Mond zeichnen, wenn eine neue Minute, die andere Halbkugel oder eine andere Sprache gilt; true, wenn neu gezeichnet. */
function renderMoon(nowMs) {
  if ($("moon-box").hidden) return false;
  const minute = Math.floor(nowMs / 60_000);
  const key = `${minute}|${state.south}|${language()}`;
  if (key === state.moonKey) return false;
  state.moonKey = key;
  const phase = fx.moonPhase(nowMs);
  if (!phase) return false;
  setAttr($("moon-lit"), "d", fx.moonPath(phase.angle, { r: 49, south: state.south }));
  const name = t(`clock.moon.${phase.key}`);
  const pct = Math.round(phase.illum * 100);
  setText($("moon-text"), t("clock.moon_text", { name, pct }));
  const full = fx.nextMoonPhase(nowMs, 180);
  const fresh = fx.nextMoonPhase(nowMs, 0);
  // Tag und Monat als Zahlen (kein eigener Intl-Formatierer nur für den Titel).
  const day = (ms) => { const d = new Date(ms); return t("clock.moon_date", { d: d.getDate(), m: d.getMonth() + 1 }); };
  const next = full < fresh ? t("clock.moon_next_full", { date: day(full) }) : t("clock.moon_next_new", { date: day(fresh) });
  const title = `${t("clock.moon_title", { name, pct })} ${next} ${t(state.south ? "clock.moon_click_north" : "clock.moon_click_south")}`;
  setAttr($("moon"), "title", title);
  setAttr($("moon"), "aria-label", title);
  setAttr($("moon"), "aria-pressed", state.south ? "true" : "false");
  $("moon").disabled = !CONTROLS.fun;   // wie Timer und Nacht: nicht mit lock=1, im Kiosk, in OBS und auf E-Ink
  return true;
}

function toggleSouth() {
  if (!CONTROLS.fun) return;
  state.south = !state.south;
  store(SOUTH_KEY, state.south ? "1" : "0");
  renderMoon(serverMs());
  hint(t(state.south ? "clock.hint_moon_south" : "clock.hint_moon_north"));
}

/** Nerd-Zeile aufbauen: je Angabe eine Beschriftung und ein Wert (nur textContent). */
function buildNerd(on) {
  const line = $("nerd");
  line.replaceChildren();
  state.nerd = null;
  if (!on) return;
  state.nerd = {};
  for (const key of NERD_KEYS) {
    const item = document.createElement("span");
    item.className = "clock-nerd-item";
    const label = document.createElement("span");
    label.className = "clock-nerd-label";
    label.dataset.key = key;
    item.dataset.key = key;
    label.textContent = t(`clock.nerd.${key}`);
    const value = document.createElement("span");
    value.className = "clock-nerd-value";
    item.append(label, " ", value);
    line.append(item);
    state.nerd[key] = value;
  }
}

function renderNerd(nowMs) {
  if (!state.nerd) return;
  const status = state.status || {};
  const v = fx.nerdValues(nowMs, status.tai_utc);
  if (!v) return;
  const at = state.extrasAt || {};
  const day = at.day instanceof Date ? at.day : new Date(nowMs);   // derselbe Tag wie Datum und KW der Anzeige
  const dec = language() === "en" ? "." : ",";
  const iso = isoWeek(day);
  const weekday = day.getDay() || 7;
  const offset = fx.taiUtc(status.tai_utc);
  setText(state.nerd.unix, String(v.unix));
  setText(state.nerd.hex, v.hex || "–");
  setText(state.nerd.tai, v.taiMs === null ? "–" : `${fx.hmsOf(v.taiMs)} (+${offset} s)`);
  setText(state.nerd.gps, v.gps === null ? "–" : t("clock.nerd_gps", { week: v.gps.week, sow: v.gps.sow }));
  setText(state.nerd.mjd, v.mjd.toFixed(3).replace(".", dec));
  setText(state.nerd.doy, String(fx.dayOfYear(day.getFullYear(), day.getMonth() + 1, day.getDate())));
  setText(state.nerd.iso, `${iso.year}-W${pad(iso.week)}-${weekday}`);
  setText(state.nerd.roman, fx.romanTime(at.h, at.m) || "–");
}

/** Fortschrittsbalken aufbauen: role=progressbar mit Wert und Text, Füllung über die CSSOM-Variable --bar. */
function buildBars(kinds) {
  const box = $("bars");
  box.replaceChildren();
  state.bars = kinds.map((kind) => {
    const node = document.createElement("div");
    node.className = "clock-prog-item";
    node.dataset.kind = kind;
    node.setAttribute("role", "progressbar");
    node.setAttribute("aria-valuemin", "0");
    node.setAttribute("aria-valuemax", "100");
    const label = document.createElement("span");
    label.className = "clock-prog-label";
    const track = document.createElement("span");
    track.className = "clock-prog-track";
    track.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.className = "clock-prog-fill";
    track.append(fill);
    const value = document.createElement("span");
    value.className = "clock-prog-value";
    node.append(label, track, value);
    box.append(node);
    return { kind, node, label, fill, value, pct: null };
  });
}

/** Balken stellen: Kalender einmal je Minute, die Eieruhr im Takt. true, wenn die Kalender-Balken neu gezeichnet wurden. */
function renderBars(nowMs) {
  if (!state.bars.length) return false;
  const minute = `${Math.floor(nowMs / 60_000)}|${language()}`;
  const calendar = minute !== state.barsKey;
  state.barsKey = minute;
  for (const bar of state.bars) {
    if (bar.kind !== "timer" && !calendar) continue;
    const fraction = bar.kind === "timer" ? fx.timerProgress(state.timer, performance.now())
      : (fx.periodProgress(bar.kind, nowMs, (state.extrasAt || {}).offset ?? null) || {}).fraction;
    const pct = fx.percentOf(fraction);
    const name = bar.kind === "timer" && state.pomo ? t(`clock.bar.pomo_${state.pomo.phase}`) : t(`clock.bar.${bar.kind}`);
    setText(bar.label, name);
    if (pct === bar.pct && !calendar) continue;
    bar.pct = pct;
    const text = pct === null ? "–" : t("clock.bar_value", { pct });
    setText(bar.value, text);
    setAttr(bar.node, "aria-valuenow", String(pct ?? 0));
    setAttr(bar.node, "aria-valuetext", bar.kind === "timer" ? `${name}: ${text}` : t(`clock.bar_say.${bar.kind}`, { pct: pct ?? 0 }));
    setAttr(bar.node, "title", bar.kind === "timer" ? `${name}: ${text}` : t(`clock.bar_say.${bar.kind}`, { pct: pct ?? 0 }));
    bar.fill.style.setProperty("--bar", String(Math.round((fraction ?? 0) * 1000) / 1000));
  }
  return calendar;
}

// --- Prüfbild ?test=sync (Studiouhr B5) --------------------------------------------------------
/** Prüfbild starten, wenn die Adresse es ausdrücklich nennt. Bei „weniger Bewegung“ und auf E-Ink nur der Hinweistext. */
function startTest() {
  const mode = kit.testMode(window.location.search, { reduced: reducedMotion.matches, eink: params.eink });
  if (mode === "off" || state.test) return;
  state.test = { mode, timer: null, tone: null, leadChanged: false };
  const run = mode === "run";
  setAttr($("sync-test"), "data-mode", mode);
  setHidden($("sync-test-warn"), !run);
  setHidden($("sync-test-flash"), !run);
  setHidden($("sync-test-tone"), !run);
  setHidden($("sync-test-less"), !run || params.lock);
  setHidden($("sync-test-more"), !run || params.lock);
  $("sync-test").hidden = false;
  coverStage(true);
  renderTest();
  flashTick();
}

/** Die Uhr hinter dem Prüfbild aus Tab-Folge und Vorlesebaum nehmen (inert) bzw. wieder freigeben. */
function coverStage(covered) {
  const main = $("clock-main");
  main.inert = covered;
  if (covered) main.setAttribute("aria-hidden", "true");
  else main.removeAttribute("aria-hidden");
}

/** Texte des Prüfbilds: Erklärung bzw. Grund, warum es nicht läuft, Vorlauf, Zustand des Klicks. */
function renderTest(status = "") {
  const test = state.test;
  if (!test) return;
  // lock=1 sperrt Pfeiltasten und Knöpfe für den Vorlauf: Dann fordert der Text auch nicht dazu auf.
  const noteKey = test.mode === "run" ? (params.lock ? "clock.test_note_locked" : "clock.test_note") : `clock.test_${test.mode}`;
  setText($("sync-test-note"), t(noteKey));
  setText($("sync-test-lead"), test.mode === "run" ? t("clock.test_lead", { ms: params.lead }) : "");
  $("sync-test-tone").setAttribute("aria-pressed", test.tone ? "true" : "false");
  $("sync-test-less").disabled = params.lead <= 0;
  $("sync-test-more").disabled = params.lead >= kit.LEAD_MAX_MS;
  let text = status;
  if (!text && test.tone) text = t(test.tone.ctx.state === "running" ? "clock.test_tone_on" : "clock.test_tone_blocked");
  setText($("sync-test-status"), text);
}

/** Fläche des Prüfbilds stellen und den nächsten Wechsel genau auf die volle Sekunde der angezeigten Zeit legen. */
function flashTick() {
  const test = state.test;
  if (!test || test.mode !== "run") return;
  clearTimeout(test.timer);
  const step = kit.flashStep(serverMs());
  if (!step) return;
  setAttr($("sync-test-flash"), "data-on", step.on ? "1" : "0");
  setText($("sync-test-sec"), pad(((step.second % 60) + 60) % 60));
  test.timer = setTimeout(flashTick, step.delay);
}

/** Klick des Prüfbilds: auf jeder vollen Sekunde der wahren Serverzeit (ohne Vorlauf), geplant wie „Ton auf der Sekunde“. */
function testTone() {
  const tone = state.test && state.test.tone;
  if (!tone || tone.ctx.state !== "running") return;
  const perf = performance.now();
  const clock = kit.audioClock(tone.ctx, perf, trueMs(perf), 0);
  for (const planned of kit.planTones(clock, { mode: "click", afterSecond: tone.last, horizonMs: 1500 })) {
    tone.last = planned.second;
    if (planned.at > tone.ctx.currentTime + 0.005) kit.scheduleTone(tone.ctx, planned);
  }
}

async function toggleTestTone() {
  const test = state.test;
  if (!test || test.mode !== "run") return;
  if (test.tone) {
    test.tone.ctx.close().catch(() => {});
    test.tone = null;
    renderTest();
    return;
  }
  const Ctx = window.AudioContext || window.webkitAudioContext;
  let ctx = null;
  try { ctx = Ctx ? new Ctx({ latencyHint: "interactive" }) : null; } catch (error) { ctx = null; }
  if (!ctx) { renderTest(t("clock.tone_unsupported")); return; }
  test.tone = { ctx, last: -Infinity };
  try { await ctx.resume(); } catch (error) { /* bleibt stumm, die Fläche läuft trotzdem */ }
  if (state.test !== test || test.tone === null) { ctx.close().catch(() => {}); return; }   // inzwischen beendet
  testTone();
  renderTest();
}

/** Vorlauf im Prüfbild ändern (±10 ms): wirkt sofort auf Anzeige und Fläche; der Klick bleibt auf der wahren Sekunde. */
function changeLead(dir) {
  const test = state.test;
  if (!test || test.mode !== "run" || params.lock) return;
  const next = kit.leadStep(params.lead, dir);
  if (next === params.lead) return;
  params.lead = next;
  test.leadChanged = true;
  state.syncKey = "";
  clearTimeout(state.tickTimer);
  tick();
  flashTick();
  renderTest();
}

/**
 * Prüfbild beenden (Esc, Knopf): Zeitgeber und Klick aus, test= aus der Adresse nehmen (ein Neuladen startet es nicht
 * wieder) und einen hier eingemessenen Vorlauf festhalten: Gilt für diese Adresse der gemerkte Stand (Panel
 * „Anpassen“), kommt er dort hinein – als lead= in der Adresse verdrängte er den Stand; sonst steht er als lead= in der
 * Adresse. keep: nur anhalten, Adresse bleibt.
 */
function stopTest(keep = false) {
  const test = state.test;
  if (!test) return;
  clearTimeout(test.timer);
  if (test.tone) test.tone.ctx.close().catch(() => {});
  state.test = null;
  $("sync-test").hidden = true;
  coverStage(false);
  if (keep) return;
  let remembered = false;
  if (test.leadChanged && link.storedApplies(window.location.search)) {
    const stored = link.storedQuery(store(link.STORE_KEY) || "", ZONES);
    if (stored) {
      const next = link.storedSet(stored, "lead", params.lead, ZONES);
      if (next) store(link.STORE_KEY, next);
      else removeStored(link.STORE_KEY);
      remembered = true;
    }
  }
  try {
    const search = link.testDoneSearch(window.location.search, test.leadChanged && !remembered ? params.lead : null);
    window.history.replaceState(null, "", `${window.location.pathname}${search}`);
  } catch (error) { /* Adresse bleibt – das Prüfbild ist trotzdem aus */ }
  hint(remembered ? t("clock.test_ended_stored", { ms: params.lead }) : t("clock.test_ended"));
}

$("sync-test-tone").addEventListener("click", toggleTestTone);
$("sync-test-less").addEventListener("click", () => changeLead(-1));
$("sync-test-more").addEventListener("click", () => changeLead(1));
$("sync-test-stop").addEventListener("click", () => stopTest());
// Pfeiltasten im Prüfbild: Vorlauf ändern (nicht mit lock=1, nicht in Eingabefeldern).
document.addEventListener("keydown", (event) => {
  if (!state.test || state.test.mode !== "run" || params.lock || event.ctrlKey || event.altKey || event.metaKey) return;
  const target = event.target instanceof Element ? event.target : null;
  if (target && target.closest("select, input, textarea")) return;
  const dir = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[event.key];
  if (!dir) return;
  event.preventDefault();
  changeLead(dir);
});
// Wechselt die Systemeinstellung „weniger Bewegung“, gilt sie sofort: Die Fläche hält an bzw. der Hinweis verschwindet.
if (typeof reducedMotion.addEventListener === "function") {
  reducedMotion.addEventListener("change", () => {
    if (!state.test) return;
    const leadChanged = state.test.leadChanged;   // der Neustart darf einen schon eingemessenen Vorlauf nicht vergessen
    stopTest(true);
    startTest();
    if (state.test) state.test.leadChanged = leadChanged;
  });
}

// --- Tastenkürzel, Hinweis, Ansage ------------------------------------------------------------
/** Kurzer sichtbarer Hinweis nach einem Kürzel (2 s, role=status). */
function hint(text) {
  const node = $("clock-hint");
  setText(node, text);
  node.hidden = false;
  clearTimeout(state.hintTimer);
  state.hintTimer = setTimeout(() => { node.hidden = true; }, HINT_MS);
}

/** Text einmal über die Live-Region ansagen (Screenreader; keine Sprachausgabe des Browsers). */
function say(text) {
  const node = $("clock-live");
  node.textContent = "";
  setTimeout(() => { node.textContent = text; }, 60);
}

/** Übersicht der Kürzel öffnen/schließen. Beim Schließen kehrt der Fokus dorthin zurück, wo er vorher war. */
function showKeys(open) {
  const node = $("keys");
  const show = open === undefined ? node.hidden : open;
  if (show === !node.hidden) { wake(); return; }
  if (show) {
    const before = document.activeElement;
    state.keysReturn = before instanceof HTMLElement && before !== document.body && !node.contains(before) ? before : null;
  }
  node.hidden = !show;
  if (show) $("keys-close").focus();
  else {
    const back = state.keysReturn && state.keysReturn.isConnected ? state.keysReturn : $("clock-main");
    state.keysReturn = null;
    back.focus({ preventScroll: true });
  }
  wake();
}

/** Tab bleibt in der offenen Übersicht (aria-modal): vom letzten zum ersten Element und umgekehrt. */
function trapKeys(event) {
  if (event.key !== "Tab") return;
  const node = $("keys");
  const items = [...node.querySelectorAll("button, [href], [tabindex]:not([tabindex='-1'])")].filter((el) => !el.disabled);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (event.shiftKey ? (active === first || !node.contains(active)) : (active === last || !node.contains(active))) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
}

function nextDesign() {
  const list = kit.DESIGNS;
  setDesign(list[(list.indexOf(state.design) + 1) % list.length], true);
  hint(t("clock.hint_design", { name: t(`clock.design.${state.design}`) }));
}

function nextLayout() {
  const list = kit.LAYOUTS;
  params.layout = list[(list.indexOf(params.layout) + 1) % list.length];
  root.dataset.layoutMode = params.layout;
  document.body.classList.toggle("is-tile", params.layout === "tile");
  root.style.setProperty("--safe", String(kit.safeMargin(params)));
  const stage = $("clock-stage");
  applyLayout(stage.clientWidth, stage.clientHeight);
  hint(t("clock.hint_layout", { name: t(`clock.layout_name.${params.layout}`) }));
}

function changeScale(delta) {
  params.scale = Math.max(50, Math.min(200, params.scale + delta));
  root.style.setProperty("--clock-scale", String(params.scale / 100));
  fitTime();
  hint(t("clock.hint_scale", { value: params.scale }));
}

function toggleUtc() {
  state.utcBig = !state.utcBig;
  state.minuteKey = "";
  state.worldKey = "";
  state.tcOffset = null;
  if (state.face) state.face.key = "";
  if (state.face && state.face.text) state.face.text.dataset.key = "";
  render(new Date(serverMs()));
  hint(t(state.utcBig ? "clock.hint_utc" : "clock.hint_local"));
}

function toggleTenths() {
  // Im Design tc schaltet T die Feinstelle des Timecodes – außer der Countdown ist die Hauptanzeige (?cd=main): Dann
  // ist der Timecode nicht zu sehen, und T gilt wie überall den Zehnteln von Timer und Stoppuhr.
  if (state.design === "tc" && !countdownMain()) { toggleTcFine(); return; }
  state.tenths = !state.tenths;
  renderCountdown();
  scheduleTimer();
  hint(t(state.tenths ? "clock.hint_tenths_on" : "clock.hint_tenths_off"));
}

function announceTime() {
  const now = new Date(serverMs());
  // Design tc: die Zeit, die groß zu sehen ist (Zone des Servers).
  const zoned = state.design === "tc" && !state.utcBig ? tc.tcView(tcDayMs(now.getTime()), params.fps, "off") : null;
  const h = zoned ? Number(zoned.hh) : (state.utcBig ? now.getUTCHours() : now.getHours());
  const m = zoned ? Number(zoned.mm) : (state.utcBig ? now.getUTCMinutes() : now.getMinutes());
  say(state.utcBig ? `UTC ${pad(h)}:${pad(m)}` : t("clock.say_time", { time: `${pad(h)}:${pad(m)}` }));
}

/** Tastenkürzel ohne Strg/Alt/Cmd; nicht in Eingabefeldern, mit ?lock=1 gar nicht. */
function onKey(event) {
  if (!state.ready || params.lock || event.ctrlKey || event.altKey || event.metaKey || event.repeat) return;
  const target = event.target instanceof Element ? event.target : null;
  if (target && target.closest("select, input, textarea")) return;
  const key = event.key;
  if (key === "Escape") {
    if (!$("keys").hidden) showKeys(false);
    return;
  }
  // Prüfbild: Die Uhr dahinter ist verdeckt. Stoppuhr, Design, Layout und Größe änderten sich sonst unbemerkt – es
  // bleiben nur Hilfe und Vollbild (Esc beendet das Prüfbild, die Pfeiltasten stellen den Vorlauf: eigene Listener).
  if (state.test && key !== "?" && key.toLowerCase() !== "f") return;
  if (key === " " || key === "Spacebar") {
    if (target && target.closest("button, a")) return;   // dort löst die Leertaste den Knopf aus
    event.preventDefault();
    toggleTimer();
    return;
  }
  const actions = {
    f: toggleFullscreen, d: nextDesign, l: nextLayout, u: toggleUtc, t: toggleTenths, r: resetTimer, a: announceTime,
    o: toggleSignal, n: toggleNight,
    "+": () => changeScale(10), "-": () => changeScale(-10), "−": () => changeScale(-10), "?": () => showKeys(),
  };
  const action = actions[key.length === 1 ? key.toLowerCase() : key];
  if (action) {
    event.preventDefault();
    action();
  }
}

// --- Darstellung: hell/dunkel, Rotlicht, E-Ink, Kiosk, Vollbild ------------------------------
function applyModes() {
  const red = store("ntp-gui-clock-red") === "1";
  const night = nightNow();
  // Ein Thema (?look=) bringt sein eigenes Hell/Dunkel mit, ?bg=black ist immer dunkel; Rotlicht und E-Ink übersteuern.
  // Der Nachtmodus ist immer dunkel und geht dem Rotlicht-Knopf vor (mit ?dimred=1 ist er selbst Rotlicht).
  const scheme = kit.colorScheme({ eink: params.eink, look: params.look, bg: params.bg, stored: store("ntp-gui-clock-theme") });
  root.dataset.theme = night.on ? "dark" : scheme.scheme;
  if (params.eink) root.dataset.mode = "eink";
  else if (night.on) root.dataset.mode = night.mode;
  else if (red) root.dataset.mode = "red";
  else delete root.dataset.mode;
  // Helligkeit des Nachtmodus (?dimlevel=, 0,2–0,8) per CSSOM: Deckkraft von Leiste, Bühne und Band.
  if (night.on) {
    root.dataset.night = "1";
    root.style.setProperty("--night", String(night.level));
  } else {
    delete root.dataset.night;
    root.style.removeProperty("--night");
  }
  state.nightKey = night.on ? `${night.mode}|${night.level}` : "";
  // Beschriftung = Aktion („Dunkel“ im hellen Modus), daher kein aria-pressed: „Dunkel, gedrückt“ wäre falsch.
  $("mode-theme").textContent = scheme.scheme === "light" ? t("clock.theme_dark") : t("clock.theme_light");
  $("mode-red").setAttribute("aria-pressed", red ? "true" : "false");
  $("mode-night").setAttribute("aria-pressed", night.on ? "true" : "false");
  $("mode-theme").disabled = red || scheme.locked || night.on;
  $("mode-red").disabled = params.eink || night.on;
  applyColors();
}

/**
 * Akzent- (?accent=) und Ziffernfarbe (?color=, Design studio) per CSSOM – kein style-Attribut im Markup, daher
 * unter der strengen CSP erlaubt. Reicht der Kontrast zum Hintergrund nicht (≥ 4,5:1), gilt die nächste Stufe, die
 * trägt (kit.ensureContrast). Rotlicht und E-Ink haben feste Farben: dann nichts setzen.
 */
function applyColors() {
  const style = root.style;
  if (root.dataset.mode) {
    style.removeProperty("--accent");
    style.removeProperty("--studio-ink");
    return;
  }
  const bg = kit.colorBackground({ look: params.look, bg: params.bg, theme: root.dataset.theme });
  const accent = params.accent ? kit.ensureContrast(kit.colorValue(params.accent), bg) : null;
  if (accent) style.setProperty("--accent", accent.hex);
  else style.removeProperty("--accent");
  const ink = kit.ensureContrast(kit.PALETTE[params.color] || kit.PALETTE.amber, bg);
  if (ink) style.setProperty("--studio-ink", ink.hex);
}

// --- Layout-Engine: Bühne, Sicherheitsrand, Größe, Pixel-Shift ---------------------------------------
/** Feste Einstellungen aus der Adresse: data-Attribute am Root und CSSOM-Variablen (nur Zahlen aus dem Schema). */
function applyDisplayParams() {
  const style = root.style;
  style.setProperty("--safe", String(kit.safeMargin(params)));
  style.setProperty("--clock-scale", String(params.scale / 100));
  style.setProperty("--fit", "1");
  if (params.show) root.dataset.show = params.show.join(" ");
  if (params.weight) root.dataset.weight = params.weight;
  if (params.bg) root.dataset.bg = params.bg;
  if (params.look) root.dataset.look = params.look;
  if (params.face !== "sans") root.dataset.face = params.face;
  if (params.date === "off") root.dataset.date = "off";
  if (params.colon === "blink" && !params.eink) root.dataset.colon = "on";
  root.dataset.layoutMode = params.layout;
  // Multiviewer-Kachel ausdrücklich gewählt: ohne Kopfzeile, Band und Mauszeiger (bei automatischer Kachel bleiben
  // sie, sonst wüchse die Bühne und das Layout spränge zurück).
  document.body.classList.toggle("is-tile", params.layout === "tile");
}

/**
 * data-layout der Bühne aus ihrer Größe (oder ?layout=), danach die Zeitbreite anpassen. Wählt die Automatik den
 * Streifen, fallen Kopfzeile und Band weg (body.is-compact, kit.chromeLayout); entschieden wird dann mit der Höhe,
 * die die Bühne mit beiden hätte, damit das Layout nicht hin- und herspringt.
 */
function applyLayout(width, height) {
  if (!state.stage || state.stage.width !== width || state.stage.height !== height) state.extrasNoRoom = false;
  state.stage = { width, height };
  const stage = $("clock-stage");
  const body = document.body;
  const compact = body.classList.contains("is-compact");
  // ?show= ohne „tz“ lässt keine Weltzeit zu: Das Layout world hätte keinen Inhalt, es gilt die Automatik.
  const want = params.layout === "world" && !world.worldAllowed(params.show) ? "auto" : params.layout;
  // On-Air-Signal: Rahmen und Balken nehmen der Bühne Platz. Gewählt wird mit der Fläche, die sie ohne Signal hätte –
  // sonst spränge das Layout beim Schalten.
  const taken = signalSpace();
  const pick = kit.chromeLayout(want, width + taken.width, height + taken.height, compact ? state.chrome : 0);
  const wantCompact = pick.compact && !body.classList.contains("has-panel");
  if (wantCompact !== compact) {
    // Höhe von Kopfzeile und Band allein – ohne Rahmen und Balken des Signals, die schon in taken stecken.
    if (wantCompact) state.chrome = Math.max(0, document.documentElement.clientHeight - height - taken.height);
    body.classList.toggle("is-compact", wantCompact);   // der ResizeObserver meldet danach die neue Bühnengröße
  }
  state.picked = pick.layout;
  stageLayout(pick.layout);
  if (state.face) renderWorld(serverMs());   // Leiste oder Raster gehören zum Layout und zur Größe der Bühne
  fitTime();
}

/**
 * Platz in px, den das On-Air-Signal der Bühne nimmt: Rahmen links und rechts, Rahmen oben und unten plus Balken. Bei
 * sehr wenig Höhe weicht die Kopfzeile dem Balken (clock.css) – ihre zuletzt gemessene Höhe zählt dann dagegen.
 */
function signalSpace() {
  const body = document.body;
  const head = $("clock-back").parentElement;
  if (!body.classList.contains("has-signal")) {
    state.headHeight = head.offsetHeight;
    return { width: 0, height: 0 };
  }
  const border = parseFloat(window.getComputedStyle(body).borderTopWidth) || 0;
  const gone = head.offsetHeight === 0 && !body.matches(".is-compact, .is-tile, .is-kiosk") ? state.headHeight : 0;
  return { width: 2 * border, height: 2 * border + $("signal").offsetHeight - gone };
}

/** data-layout (und data-stack) der Bühne setzen; state.layout ist das Layout, das gerade gezeichnet wird. */
function stageLayout(layout) {
  const stage = $("clock-stage");
  state.layout = layout;
  setAttr(stage, "data-layout", layout);
  if (kit.stackedTime(layout, state.stage.width, state.stage.height)) setAttr(stage, "data-stack", "1");
  else stage.removeAttribute("data-stack");
}

function observeStage() {
  const stage = $("clock-stage");
  const measure = () => applyLayout(stage.clientWidth, stage.clientHeight);
  if (typeof window.ResizeObserver === "function") {
    new window.ResizeObserver((entries) => {
      const box = entries[entries.length - 1].contentRect;
      applyLayout(box.width, box.height);
    }).observe(stage);
  } else {
    window.addEventListener("resize", measure);
  }
  measure();
}

/** Was eingepasst wird: der Countdown als Hauptanzeige (?cd=main), sonst die Textzeit oder das Zifferblatt. */
function fitNode() {
  if (countdownMain()) return $("cd");
  return textTime() ? $("local-time") : $("face");
}

/** Größe der sichtbaren Zeit (Text oder Zifferblatt) ohne Rand: Vereinigung der Kinder-Rechtecke. */
function timeBox() {
  const node = fitNode();
  if (!node || node.hidden) return null;
  // Design tc: nur die Ziffernzeile – Kopfzeile und Zeile darunter schrumpfen nicht mit (Mindestgröße 12 px) und
  // brechen um; ihr Platz wird in fitTime von der Fläche abgezogen (tcFixed).
  const parts = node.id === "local-time" ? [node] : (state.face && state.face.tc && node.id === "face" ? [state.face.row] : [...node.children]);
  let left = Infinity; let right = -Infinity; let top = Infinity; let bottom = -Infinity;
  for (const part of parts) {
    const box = part.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    left = Math.min(left, box.left); right = Math.max(right, box.right);
    top = Math.min(top, box.top); bottom = Math.max(bottom, box.bottom);
  }
  return Number.isFinite(left) ? { width: right - left, height: bottom - top } : null;
}

/**
 * Auto-Anpassung: Die Zeit muss ohne Umbruch in den sicheren Bereich passen. --fit = 1 setzen, messen, dann so weit
 * verkleinern, dass Breite und Höhe mit 4 % Luft (Pixel-Shift) in main passen – mehrmals, bis es passt
 * (kit.fitConverge). Bei Größen-, Layout- und Designwechsel und einmal je Minute (Stundenbreite ohne führende Null).
 * Im Banner bekommt die Spalte mit Datum, UTC und Zustand vorher ihre natürliche Breite (höchstens 45 %, CSS), die
 * Zeit nur den Rest – sonst drückte eine große Zeit (?scale=200) die Spalte auf wenige Pixel zusammen.
 */
function fitTime() {
  fitTimeOnly();
  checkExtrasRoom();
}

/**
 * Ragen die Zusätze nach dem Einpassen aus der Bühne (die rechte Spalte im Banner wächst nicht mit der Zeit: Countdown,
 * Datum, Zeile, Weltzeit-Leiste und Zusätze untereinander), fallen sie weg, bis sich die Größe der Bühne ändert.
 */
function checkExtrasRoom() {
  const box = $("extras");
  // Nur im Banner: In den anderen Layouts bekommt die Zeit den Rest der Höhe (restHeight), die Zusätze passen immer.
  if (state.extrasNoRoom || box.hidden || !state.face || state.layout !== "banner") return;
  const stage = $("clock-stage").getBoundingClientRect();
  const rect = box.getBoundingClientRect();
  if (!rect.height || (rect.bottom <= stage.bottom + 1 && rect.top >= stage.top - 1 && rect.right <= stage.right + 1
    && rect.left >= stage.left - 1)) return;
  state.extrasNoRoom = true;
  renderExtras(serverMs());   // blendet aus und passt die Zeit neu ein
}

function fitTimeOnly() {
  const main = $("clock-main");
  // Vor dem ersten Layout (Start: setDesign vor observeStage) nicht messen – observeStage passt gleich danach ein.
  if (!main || !state.face || !state.layout) return;
  state.extrasHeight = $("extras").offsetHeight;   // Zusätze (C2): bei geänderter Höhe passt renderExtras neu ein
  const w = state.world;
  if (w && w.mode === "grid") {
    stageLayout("world");
    fitGrid(main);
    if (w.shown) { fitOnce(main); return; }
    // Kein Platz für eine einzige Zone: ohne Raster bliebe im Layout world nur eine kleine Uhr auf leerer Fläche –
    // dann die Uhr im Layout, das die Automatik für diese Fläche wählt.
    stageLayout(kit.resolveLayout(state.stage.width, state.stage.height));
  }
  const bar = Boolean(w) && w.mode === "bar";
  root.style.setProperty("--world-grow", "1");
  if (bar) trimWorld(Infinity);   // erst alle Zonen: Die Infospalte im Banner misst ihre natürliche Breite
  if (state.layout === "banner") root.style.setProperty("--info-w", `${infoWidth()}px`);
  if (!bar) { fitOnce(main); return; }
  // Leiste der Weltzeit: höchstens maxLines Zeilen. Sie darf nicht aus der Bühne ragen und die Zeit nicht erdrücken –
  // sonst eine Zeile weniger, zuletzt ganz ohne Leiste.
  trimWorld(w.maxLines);
  let factor = fitOnce(main);
  if (!w.shown) return;
  if (factor >= WORLD_FIT_OK && worldInside()) { growBar(main, factor, w.maxLines); return; }
  const lines = worldLineCount();
  trimWorld(0);
  const base = fitOnce(main);
  for (let keep = lines; keep > 0; keep -= 1) {
    trimWorld(keep);
    factor = fitOnce(main);
    if (w.shown && factor >= WORLD_FIT_SHARE * base && worldInside()) { growBar(main, factor, keep); return; }
  }
  trimWorld(0);
  fitOnce(main);
}

/**
 * Leiste vergrößern, wo Höhe frei ist (--world-grow, Stufen aus world.barGrowSteps): nur, wenn dieselben Zonen in
 * höchstens `lines` Zeilen (im Layout normal eine mehr) in der Bühne bleiben und die Zeit dafür nicht kleiner wird.
 * Sonst bleibt alles, wie es ist.
 */
function growBar(main, factor, lines) {
  const w = state.world;
  const time = timeBox();
  const font = parseFloat(window.getComputedStyle($("world")).fontSize) || 0;
  // Unter der Uhr ist die Höhe frei: Größer darf eine Zeile mehr kosten – aber nur, wenn keine Zone fehlt (sonst
  // gehörte die Zeile den fehlenden Zonen, und die Zeilenzahl ist dort bewusst begrenzt).
  const extra = state.layout === "normal" && w.shown === w.cells.length ? 1 : 0;
  for (const grow of world.barGrowSteps(time ? time.height : 0, font)) {
    root.style.setProperty("--world-grow", String(grow));
    if (worldLineCount() <= lines + extra && fitOnce(main) >= factor - 0.004 && worldInside()) return;
  }
  root.style.setProperty("--world-grow", "1");
  fitOnce(main);
}

/** Ein Durchgang der Auto-Anpassung für die Zeit; setzt --fit und liefert den Faktor. */
function fitOnce(main) {
  const factor = kit.fitConverge((fit) => {
    root.style.setProperty("--fit", String(fit));
    const box = timeBox();
    const fixed = tcFixed();
    return box ? { needed: box, available: { width: Math.max(1, timeWidth(main) * 0.96 - fixed.width),
      height: Math.max(1, main.clientHeight * 0.96 - restHeight(main) - fixed.height) } } : null;
  });
  root.style.setProperty("--fit", String(factor));
  return factor;
}

/**
 * Design tc: Platz, den Kopfzeile und Zeile unter der Zeit neben der Ziffernzeile brauchen – Höhe, wenn sie über und
 * unter ihr stehen, Breite, wenn die Kopfzeile im Streifen links daneben steht. Sonst 0.
 */
function tcFixed() {
  const fixed = { width: 0, height: 0 };
  const face = state.face;
  if (!face || !face.tc || fitNode() !== $("face")) return fixed;
  const style = window.getComputedStyle($("face"));
  const column = style.flexDirection === "column";
  let items = 1;
  for (const node of [face.head, face.note]) {
    const box = node.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    items += 1;
    if (column) fixed.height += box.height;
    else fixed.width += box.width;
  }
  const gap = (items - 1) * (parseFloat(column ? style.rowGap : style.columnGap) || 0);
  if (column) fixed.height += gap;
  else fixed.width += gap;
  return fixed;
}

/** Natürliche Breite der Infospalte im Banner: mit kleinster Zeit messen, dann hat die Spalte Platz für ihren Inhalt. */
function infoWidth() {
  root.style.setProperty("--fit", "0.1");
  let width = 0;
  for (const node of document.querySelectorAll("#clock-main > .clock-date, #clock-main > .clock-sub, #clock-main > .clock-world, :root[data-cd=below] #clock-main > .clock-cd")) {
    width = Math.max(width, node.getBoundingClientRect().width);
  }
  return Math.ceil(width);
}

/**
 * Höhe der übrigen Zeilen in main (Beschriftung, Datum, Zeile mit UTC und Zustand), wenn sie untereinander stehen
 * (normal, column): Die Zeit bekommt nur den Rest, sonst schöbe ein großes Zifferblatt (?scale=200) sie aus dem Bild.
 */
function restHeight(main) {
  const box = window.getComputedStyle(main);
  if (box.display !== "flex" || box.flexDirection !== "column") return 0;
  const time = fitNode();
  let rest = 0;
  let items = 0;
  for (const node of main.children) {
    if (node.hidden) continue;
    const style = window.getComputedStyle(node);
    if (style.display === "none" || style.position === "absolute") continue;
    items += 1;
    if (node === time) continue;
    rest += node.getBoundingClientRect().height + (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0);
  }
  // Kachel mit Titel: Die oben frei gehaltene Zeile (padding-top) steht der Zeit nicht zur Verfügung.
  if (document.body.classList.contains("has-tile-title")) rest += parseFloat(box.paddingTop) || 0;
  return rest + Math.max(0, items - 1) * (parseFloat(box.rowGap) || 0);   // Abstand zwischen den Zeilen (gap aus app.css)
}

/**
 * Breite für die Zeit: main, im Banner ohne die Infospalte und den Spaltenabstand (aufgelöste Grid-Spalten), im Streifen
 * ohne die übrigen Teile der Zeile (Countdown, Zustandssymbol) samt Abständen.
 */
function timeWidth(main) {
  if (state.layout === "strip" || (state.layout === "world" && rowMain(main))) {
    const time = fitNode();
    const style = window.getComputedStyle(main);
    let rest = 0;
    let items = 0;
    for (const node of main.children) {
      const box = node.getBoundingClientRect();
      if (node.hidden || (!box.width && !box.height) || window.getComputedStyle(node).position === "absolute") continue;
      items += 1;
      if (node !== time) rest += box.width;
    }
    return Math.max(0, main.clientWidth - rest - Math.max(0, items - 1) * (parseFloat(style.columnGap) || 0));
  }
  if (state.layout !== "banner") return main.clientWidth;
  const style = window.getComputedStyle(main);
  const columns = style.gridTemplateColumns.split(" ").map(parseFloat);
  const info = columns.length > 1 && Number.isFinite(columns[1]) ? columns[1] : 0;
  const gap = parseFloat(style.columnGap) || 0;
  return Math.max(0, main.clientWidth - info - (info ? gap : 0));
}

/** Pixel-Shift gegen Einbrennen: alle 2 min eine der Klassen shift-0 … shift-7 an main (Stufe über data-shift). */
function renderShift(nowMs) {
  const level = kit.shiftLevel(params, state.design);
  setAttr(root, "data-shift", String(level));
  const index = level ? kit.shiftIndex(nowMs) : -1;
  if (index === state.shift) return;
  const main = $("clock-main");
  if (state.shift >= 0) main.classList.remove(`shift-${state.shift}`);
  if (index >= 0) main.classList.add(`shift-${index}`);
  state.shift = index;
}

$("mode-theme").addEventListener("click", () => {
  store("ntp-gui-clock-theme", root.dataset.theme === "dark" ? "light" : "dark");
  applyModes();
});
$("mode-red").addEventListener("click", () => {
  store("ntp-gui-clock-red", root.dataset.mode === "red" ? "0" : "1");
  applyModes();
});
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.().catch(() => {});
}
$("mode-full").addEventListener("click", toggleFullscreen);
if (!document.documentElement.requestFullscreen) $("mode-full").hidden = true;
document.addEventListener("keydown", onKey);
$("design").addEventListener("change", (event) => setDesign(event.target.value, true));
$("mode-tone").addEventListener("click", () => {
  togglePanel("mode-tone", "tone-panel");
});
$("mode-device").addEventListener("click", () => {
  if (togglePanel("mode-device", "device-panel")) renderDevice();
});
$("mode-custom").addEventListener("click", openCustom);
$("custom-apply").addEventListener("click", applyCustom);
$("custom-copy").addEventListener("click", copyCustom);
$("custom-reset").addEventListener("click", resetCustom);
$("tone-seconds").addEventListener("click", () => startTone("seconds"));
$("tone-countdown").addEventListener("click", () => startTone("countdown"));
$("tone-off").addEventListener("click", stopTone);
$("cd-toggle").addEventListener("click", () => toggleTimer());
$("cd-reset").addEventListener("click", () => resetTimer());
$("cd-plus").addEventListener("click", plusMinute);
$("mode-timer").addEventListener("click", openTimerPanel);
$("mode-night").addEventListener("click", toggleNight);
$("moon").addEventListener("click", toggleSouth);
$("egg-start").addEventListener("click", startEggInput);
$("egg-input").addEventListener("keydown", (event) => { if (event.key === "Enter") startEggInput(); });
$("pomo-start").addEventListener("click", startPomo);
$("timer-tone").addEventListener("change", toggleEndTone);
$("own-save").addEventListener("click", addOwn);
for (const id of ["own-label", "own-until"]) $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") addOwn(); });
$("keys-close").addEventListener("click", () => showKeys(false));
$("keys").addEventListener("keydown", trapKeys);
reducedMotion.addEventListener?.("change", () => {
  restartSweep();
  if (state.design === "tc" && state.face && state.face.tc) renderTc(serverMs());
});

// Leiste ausblenden, wenn sich nichts bewegt (Wandmonitor); Tippen/Bewegen holt sie zurück.
let idleTimer = null;
function mayHide() {
  // Offene Panels bleiben bedienbar: dann nicht ausblenden. Erst beim Ablauf prüfen – wake() läuft bei
  // pointerdown/keydown, also bevor der Klick das Panel öffnet. Liegt der Tastaturfokus in der Leiste, bleibt
  // sie ebenfalls sichtbar (nach einem Mausklick nicht, sonst bliebe sie am Wandmonitor für immer stehen).
  if (["tone-panel", "device-panel", "custom-panel", "timer-panel", "keys"].some((id) => !$(id).hidden)) return false;
  const focus = document.activeElement;
  return !(focus && focus.closest(".clock-bar") && focus.matches(":focus-visible"));
}
function wake() {
  document.body.classList.remove("is-idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (mayHide()) document.body.classList.add("is-idle"); }, IDLE_MS);
}
for (const type of ["pointermove", "pointerdown", "keydown", "focusin"]) document.addEventListener(type, wake, { passive: true });
// ?beep=: Browser spielen Töne erst nach einer Bedienung – bei der ersten Berührung oder Taste die Audiouhr starten.
for (const type of ["pointerdown", "keydown"]) document.addEventListener(type, () => countdownAudio(true), { passive: true });

function relabel() {
  applyModes();
  if (params.lock) $("mode-full").title = t("clock.full_title_locked");
  for (const button of document.querySelectorAll(".clock-panel button.info, .tc-head button.info, #moon-info button.info")) button.relabel?.();
  for (const label of document.querySelectorAll(".clock-nerd-label")) label.textContent = t(`clock.nerd.${label.dataset.key}`);
  if (state.face) state.face.key = "";
  if (state.face && state.face.text) state.face.text.dataset.key = "";
  state.minuteKey = "";
  state.worldKey = "";
  state.moonKey = "";   // Mond und Balken neu beschriften (Texte kamen vor dem Sprachkatalog)
  state.barsKey = "";
  for (const bar of state.bars) bar.pct = null;
  render(new Date(serverMs()));
  state.syncKey = "";
  renderSync();
  renderBand();
  renderDevice();
  state.cdShape = "";
  renderCountdown();
  renderProfileTitle();
  renderTest();
  if (!$("timer-panel").hidden) renderTimerPanel();
  state.signalKey = `${state.signalKey.split("|")[0]}|`;   // Texte neu, ohne den Zustand noch einmal anzusagen
  renderSignal();
}

// --- Start ------------------------------------------------------------------------------
/** Profil (?p=) laden und über die Startwerte legen: Profil < Adresse. Ohne Profil sofort. */
async function loadProfile() {
  if (!PROFILE) return;
  const profile = await fetchProfile();
  if (!profile) { if (state.profileError !== "missing") noteProfileFailure(); return; }
  state.profile = profile;
  state.profileKey = profileKey(profile);
  state.profileRev = typeof profile.profiles_rev === "string" ? profile.profiles_rev : null;
  Object.assign(params, kit.parseParams(link.effectiveQuery({ search: window.location.search, profile: profile.params,
    zones: ZONES }), ZONES));
  // Grundauswahl des Profils allein: Nennt die Adresse nur Zusätze (show=moon), bleibt sie (fx.mergeShow).
  state.profileShow = kit.parseParams(link.effectiveQuery({ profile: profile.params, zones: ZONES }), ZONES).show;
}

async function start() {
  const i18nReady = initI18n();
  await loadProfile();
  // Zusätze (Mond, Nerd-Zeile, Balken) gehören nicht zu data-show: Nennt ?show= nur sie, bleibt die Uhr wie sonst –
  // mit Profil wie im Profil.
  const split = fx.mergeShow(params.show, state.profileShow);
  params.show = split.base;
  state.extraWish = split.extras;
  state.south = store(SOUTH_KEY) === "1";
  initCountMode();
  // Bedienung erst nach dem Profil festlegen: fun=0, lock=1, Kiosk und Kachel können von dort kommen.
  CONTROLS = fx.funControls({ fun: params.fun, kiosk: params.kiosk, lock: params.lock, layout: params.layout, obs: OBS,
    eink: params.eink });
  if (OBS) document.body.classList.add("is-obs");
  $("mode-timer").hidden = !CONTROLS.fun;
  $("mode-night").hidden = !CONTROLS.fun;
  // Ohne Spielereien tut N nichts (Nachtmodus dann nur nach Zeitplan): auch nicht in der Kürzel-Übersicht nennen.
  $("keys-n-key").hidden = !CONTROLS.fun;
  $("keys-n").hidden = !CONTROLS.fun;
  state.own = fx.ownList(store(fx.OWN_KEY) || "");
  $("timer-info").append(infoButton("clock.timer_info_title", "clock.timer_info"));
  if (params.kiosk) document.body.classList.add("is-kiosk");
  if (params.eink) document.body.classList.add("is-eink");
  if (params.eink) $("mode-tone").hidden = true;   // E-Ink rechnet nur einmal je Minute
  if (params.lock) document.body.classList.add("is-locked");
  $("mode-custom").hidden = Boolean(params.lock);   // lock=1: keine lokale Bedienung, auch kein Anpassen
  // lock=1 schaltet die Tasten ab: Der Vollbild-Knopf verspricht dann keine Taste F (Titel auch in relabel()).
  if (params.lock) $("mode-full").dataset.i18nTitle = "clock.full_title_locked";
  $("tone-info").append(infoButton("clock.tone_info_title", "clock.tone_info"));
  $("device-info").append(infoButton("clock.device_info_title", "clock.device_info"));
  if (CONTROLS.actions) $("moon-info").append(infoButton("clock.moon_info_title", "clock.moon_info"));
  applyDisplayParams();
  applyModes();
  setDesign(params.design || store(DESIGN_KEY), false);
  observeStage();
  watchExtras();
  wake();
  countdownAudio(false);
  tick();
  startTest();
  measureFrame();
  keepAwake();
  burst();
  setInterval(burst, RESYNC_MS);
  setInterval(poll, kit.pollInterval(params));   // mit ?signal=1 jede Sekunde, sonst alle 5 s
  state.ready = true;
  i18nReady.then(relabel, () => {});
}
start();
