// SVG-Zifferblätter der Studiouhr (A4): Design studio (Kranz aus 60 Punkten, 12 Stundenmarken, 7-Segment-Ziffern)
// und digital mit face=seg. Ohne Schriftdatei: Jede Ziffer ist ein <use> auf das selbst gezeichnete Symbol #seg7
// in clock.html; welche Segmente leuchten, bestimmt allein die Klasse (d-0 … d-9, d-blank) über CSS-Variablen.
// Inaktive Segmente bleiben schwach sichtbar. Je Sekunde ändern sich nur Klassen – keine Animation, kein Zeitgeber.
import { svgEl } from "./util.js";
import { segClass, ringLit } from "./clockkit.js";

const SEG_W = 50;     // viewBox des Symbols #seg7: 50 × 90
const SEG_H = 90;

function digitUse(x, y, width, extra = "") {
  const height = (width / SEG_W) * SEG_H;
  return svgEl("use", { href: "#seg7", x, y, width, height, class: segClass(" ", extra) });
}

/** Klasse einer Ziffer nur bei Änderung setzen (ein Klassenwechsel je geänderter Stelle). */
export function setDigit(node, ch) {
  const extra = node.classList.contains("is-sec") ? "is-sec" : "";
  const cls = segClass(ch, extra);
  if (node.getAttribute("class") !== cls) node.setAttribute("class", cls);
}

function colon(svg, cx, top, bottom, size, extra = "") {
  const group = svgEl("g", { class: extra ? `seg-colon ${extra}` : "seg-colon" });
  group.append(svgEl("rect", { x: cx - size / 2, y: top, width: size, height: size }),
    svgEl("rect", { x: cx - size / 2, y: bottom, width: size, height: size }));
  svg.append(group);
  return group;
}

/**
 * Digitale 7-Segment-Zeile HH:MM:SS (bzw. HH:MM bei E-Ink) mit optionalem AM/PM rechts.
 * Liefert { svg, digits: [use …], ampm }.
 */
export function buildSegRow(face, { count = 6, h12 = false } = {}) {
  const gap = 6;
  const colonW = 20;
  const digits = [];
  let x = 0;
  const parts = [];
  for (let i = 0; i < count; i += 1) {
    if (i && i % 2 === 0) {
      parts.push({ colon: x + colonW / 2, sec: i >= 4 });
      x += colonW;
    } else if (i) {
      x += gap;
    }
    parts.push({ digit: x, sec: i >= 4 });
    x += SEG_W;
  }
  const width = x + (h12 ? 44 : 0);
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${SEG_H}`, class: "seg-row", "aria-hidden": "true", focusable: "false",
    preserveAspectRatio: "xMidYMid meet" });
  for (const part of parts) {
    if (part.digit !== undefined) {
      const use = digitUse(part.digit, 0, SEG_W, part.sec ? "is-sec" : "");
      svg.append(use);
      digits.push(use);
    } else {
      colon(svg, part.colon, 24, 58, 8, part.sec ? "is-sec" : "");
    }
  }
  let ampm = null;
  if (h12) {
    ampm = svgEl("text", { x: width - 2, y: 26, class: "seg-ampm", "text-anchor": "end" });
    svg.append(ampm);
  }
  face.append(svg);
  return { svg, digits, ampm };
}

/**
 * Design studio: viewBox 200 × 200. Außen 12 Stundenmarken, innen 60 Sekundenpunkte (Punkt 0 oben), in der Mitte
 * HH:MM, darunter die Sekunden als kleinere Ziffern und eine Zeile (UTC, Zweitzone oder Datum).
 * Liefert { svg, ring, dots, digits (HHMM), secGroup, secDigits (SS), sub, ampm }.
 */
export function buildStudio(face, { seconds = "both", sub = "utc", h12 = false } = {}) {
  const svg = svgEl("svg", { viewBox: "0 0 200 200", class: "st", "aria-hidden": "true", focusable: "false",
    preserveAspectRatio: "xMidYMid meet" });
  const marks = svgEl("g", { class: "st-marks" });
  for (let i = 0; i < 12; i += 1) {
    const angle = (i * 30 * Math.PI) / 180;
    marks.append(svgEl("circle", { cx: round(100 + 96 * Math.sin(angle)), cy: round(100 - 96 * Math.cos(angle)), r: 3,
      class: "st-mark" }));
  }
  svg.append(marks);
  const ring = svgEl("g", { class: "st-ring" });
  const dots = [];
  for (let i = 0; i < 60; i += 1) {
    const angle = (i * 6 * Math.PI) / 180;
    const dot = svgEl("circle", { cx: round(100 + 87 * Math.sin(angle)), cy: round(100 - 87 * Math.cos(angle)), r: 2.6,
      class: "st-dot" });
    ring.append(dot);
    dots.push(dot);
  }
  if (seconds === "digits") ring.setAttribute("class", "st-ring is-off");
  svg.append(ring);
  // HH:MM: vier Ziffern 24 × 43,2, Doppelpunkt in der Mitte (x = 100).
  const digits = [41, 70, 106, 135].map((x) => digitUse(x, 64, 24));
  svg.append(...digits);
  colon(svg, 100, 74, 92, 4.5);
  const secDigits = [84.5, 101.5].map((x) => digitUse(x, 116, 14, "is-sec"));
  const secGroup = svgEl("g", { class: seconds === "ring" ? "st-secs is-off" : "st-secs" });
  secGroup.append(...secDigits);
  svg.append(secGroup);
  const subText = svgEl("text", { x: 100, y: 160, class: sub === "off" ? "st-sub is-off" : "st-sub", "text-anchor": "middle" });
  svg.append(subText);
  let ampm = null;
  if (h12) {
    ampm = svgEl("text", { x: 100, y: 56, class: "st-ampm", "text-anchor": "middle" });
    svg.append(ampm);
  }
  face.append(svg);
  return { svg, ring, dots, digits, secGroup, secDigits, sub: subText, ampm };
}

/** Kranz auf Sekunde `second` stellen: Nur Punkte, deren Zustand wechselt, bekommen eine neue Klasse. */
export function setRing(dots, second) {
  dots.forEach((dot, index) => dot.classList.toggle("on", ringLit(index, second)));
}

function round(v) {
  return Math.round(v * 100) / 100;
}
