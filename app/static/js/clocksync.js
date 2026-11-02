// Abgleich der Browseruhr mit dem Server – dieselbe Rechnung wie NTP (vier Zeitstempel).
//
//   t0  Browser schickt die Anfrage       (Browseruhr)
//   t1  Server empfängt sie               (Serveruhr)
//   t2  Server schickt die Antwort        (Serveruhr)
//   t3  Browser hat die Antwort           (Browseruhr)
//
// Versatz  θ = ((t1 − t0) + (t2 − t3)) / 2   – so viel geht die Browseruhr nach
// Laufzeit δ = (t3 − t0) − (t2 − t1)         – Hin- und Rückweg ohne Bearbeitungszeit
//
// θ stimmt exakt, wenn Hin- und Rückweg gleich lang sind. Im schlimmsten Fall (alles
// auf einem Weg) liegt er um δ/2 daneben – daher „Genauigkeit ± RTT/2“. Von mehreren
// Messungen gewinnt die mit der kleinsten Laufzeit: Sie hatte am wenigsten Wartezeit
// in Puffern und damit die kleinste mögliche Unsymmetrie.
//
// Alle Werte in Millisekunden. Kein DOM – so lässt sich das Modul mit Node testen.

/** Eine Messung aus vier Zeitstempeln (ms). Liefert null bei Unsinn. */
export function measure(t0, t1, t2, t3) {
  if (![t0, t1, t2, t3].every((v) => typeof v === "number" && Number.isFinite(v))) return null;
  let rtt = (t3 - t0) - (t2 - t1);
  if (!(t3 >= t0) || !(t2 >= t1) || rtt < -2) return null;
  rtt = Math.max(0, rtt);   // Rundung der Browseruhr (1 ms) im lokalen Netz
  return { offset: ((t1 - t0) + (t2 - t3)) / 2, rtt, accuracy: rtt / 2, at: t3 };
}

/** Beste Messung (kleinste Laufzeit) oder null. */
export function best(samples) {
  let winner = null;
  for (const s of samples || []) if (s && (!winner || s.rtt < winner.rtt)) winner = s;
  return winner;
}

/** Antwort von /api/v1/time (Sekunden) + Browserzeiten (ms) → Messung. */
export function fromResponse(t0, payload, t3) {
  if (!payload || typeof payload.t1 !== "number" || typeof payload.t2 !== "number") return null;
  return measure(t0, payload.t1 * 1000, payload.t2 * 1000, t3);
}

const pad = (n, w = 2) => String(n).padStart(w, "0");

/** ISO-Kalenderwoche (Montag = Wochenanfang, Woche 1 enthält den ersten Donnerstag). */
export function isoWeek(date, utc = false) {
  const y = utc ? date.getUTCFullYear() : date.getFullYear();
  const m = utc ? date.getUTCMonth() : date.getMonth();
  const d = utc ? date.getUTCDate() : date.getDate();
  const day = new Date(Date.UTC(y, m, d));
  const weekday = day.getUTCDay() || 7;
  day.setUTCDate(day.getUTCDate() + 4 - weekday);   // Donnerstag derselben Woche
  const yearStart = new Date(Date.UTC(day.getUTCFullYear(), 0, 1));
  return { week: Math.ceil(((day - yearStart) / 86400000 + 1) / 7), year: day.getUTCFullYear() };
}

/** „14:03:27“ */
export function hms(date, utc = false) {
  return utc
    ? `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
    : `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** Genauigkeit lesbar: „± 4 ms“, „± 0,8 ms“, „± 1,2 s“. */
export function fmtAccuracy(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "–";
  const v = Math.abs(ms);
  if (v >= 1000) return `± ${(v / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} s`;
  if (v >= 10) return `± ${Math.round(v)} ms`;
  if (v >= 1) return `± ${v.toLocaleString("de-DE", { maximumFractionDigits: 1 })} ms`;
  if (v >= 0.001) return `± ${Math.max(1, Math.round(v * 1000))} µs`;
  return "± < 1 µs";
}
