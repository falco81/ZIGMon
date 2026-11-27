/**
 * Writes the plugin's drawn assets from the same code that draws the keys:
 *   com.zigmon.streamdeck.sdPlugin/layouts/*.json   (touch-strip layouts, from core/layouts.ts)
 *   com.zigmon.streamdeck.sdPlugin/imgs/**.svg      (category, action list, key and encoder icons)
 *   com.zigmon.streamdeck.sdPlugin/imgs/plugin/marketplace.svg (source of the PNG plugin icon)
 * Run by build.sh (compiled to out/scripts/gen-assets.js); the output is committed.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { iconMarkup } from "../src/core/icons.js";
import { LAYOUTS } from "../src/core/layouts.js";
import { P } from "../src/core/palette.js";
import { keySvg } from "../src/core/render.js";
import { icon, rect, svgDoc, text } from "../src/core/svg.js";

const here = dirname(fileURLToPath(import.meta.url));
// out/scripts -> streamdeck/
const root = join(here, "..", "..");
const sd = join(root, "com.zigmon.streamdeck.sdPlugin");

function write(rel: string, content: string): void {
  const p = join(sd, rel);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, content);
}

export const ACTIONS: { id: string; icon: string; accent: string; title: string; line: string }[] = [
  { id: "control", icon: "power", accent: P.ok, title: "Control", line: "any item" },
  { id: "reading", icon: "gauge", accent: P.water, title: "Reading", line: "value & trend" },
  { id: "thermostat", icon: "thermostat", accent: P.orange, title: "Thermostat", line: "setpoint" },
  { id: "dimmer", icon: "bulbOn", accent: P.warn, title: "Light", line: "brightness" },
  { id: "blinds", icon: "blinds", accent: P.purple, title: "Blinds", line: "position" },
  { id: "scene", icon: "scene", accent: P.purple, title: "Scene", line: "run it" },
  { id: "status", icon: "heart", accent: P.ok, title: "ZIGMon", line: "status" },
];

/** A plain stroke icon in a w x h box (action list 20, category 28): light strokes, no fill, as Stream Deck shows them. */
function monoIcon(name: string, size: number, stroke = "#FFFFFF"): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${iconMarkup(name)}</svg>`;
}

/** The key as it looks in the actions list and before it is set up. */
function keyImage(a: (typeof ACTIONS)[number]): string {
  let body = `<circle cx="72" cy="58" r="34" fill="${a.accent}" fill-opacity="0.15" stroke="${a.accent}" stroke-opacity="0.5" stroke-width="2"/>`;
  body += icon(a.icon, 50, 36, 44, a.accent, 1.9);
  body += text(72, 118, a.title, { size: 17, weight: 700, fill: P.text, anchor: "middle" });
  body += text(72, 135, a.line, { size: 12.5, weight: 500, fill: P.dim, anchor: "middle" });
  // shown at 72 x 72 and 144 x 144: the same drawing
  return keySvg(body).replace('width="144" height="144"', 'width="72" height="72"');
}

/** The dial's icon on the Stream Deck + (72 x 72). */
function encoderIcon(a: (typeof ACTIONS)[number]): string {
  const body = rect(4, 4, 64, 64, 18, a.accent, `fill-opacity="0.16" stroke="${a.accent}" stroke-opacity="0.55" stroke-width="2"`)
    + icon(a.icon, 18, 18, 36, a.accent, 1.9);
  return svgDoc(72, 72, body);
}

/** The plugin's own picture: four keys of a deck, one of them ZIGMon's mark. */
export function pluginIcon(size: number): string {
  const s = size / 256;
  const keys: [number, number, string, string, boolean][] = [
    [36, 36, "zigmon", P.info, true],
    [136, 36, "bulbOn", P.warn, false],
    [36, 136, "thermostat", P.orange, false],
    [136, 136, "blinds", P.purple, false],
  ];
  let body = `<rect x="6" y="6" width="244" height="244" rx="54" fill="url(#bg)" stroke="${P.line}" stroke-width="4"/>`;
  for (const [x, y, ic, c, lit] of keys) {
    body += rect(x, y, 84, 84, 22, lit ? c : P.panel, `fill-opacity="${lit ? 0.22 : 1}" stroke="${c}" stroke-opacity="${lit ? 0.9 : 0.4}" stroke-width="3"`);
    body += icon(ic, x + 18, y + 18, 48, c, lit ? 2.2 : 1.9);
  }
  const defs = `<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${P.panel2}"/><stop offset="1" stop-color="${P.bg}"/></linearGradient>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 256 256"><defs>${defs}</defs><g transform="scale(${s === 1 ? 1 : 1})">${body}</g></svg>`;
}

export function main(): void {
  for (const [name, layout] of Object.entries(LAYOUTS)) write(`layouts/${name}.json`, JSON.stringify(layout, null, 2) + "\n");
  write("imgs/plugin/category.svg", monoIcon("zigmon", 28));
  write("imgs/plugin/marketplace.svg", pluginIcon(256));
  for (const a of ACTIONS) {
    write(`imgs/actions/${a.id}/icon.svg`, monoIcon(a.icon, 20));
    write(`imgs/actions/${a.id}/key.svg`, keyImage(a));
    write(`imgs/actions/${a.id}/encoder.svg`, encoderIcon(a));
  }
  console.log("assets: " + Object.keys(LAYOUTS).length + " layouts, " + ACTIONS.length * 3 + 2 + " images");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
