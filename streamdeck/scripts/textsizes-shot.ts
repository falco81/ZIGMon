/**
 * (1.3) A picture of the text sizes, for looking at (not part of the build): the Look card's
 * "Text sizes" group in the inspector, and a few keys with the value and the name at 70, 100 and 150 %.
 *   node out/scripts/textsizes-shot.js <output.png>
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { catalogMessage } from "../src/core/piapi.js";
import { parseItem } from "../src/core/protocol.js";
import { esc } from "../src/core/svg.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { extendedItems, MockSurface, sampleItems } from "../test/fake-zigmon.js";
import { sheetHub } from "./sheet.js";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const outPng = process.argv[2] ?? join(root, "out", "shots", "text-sizes.png");
const outDir = dirname(outPng);
mkdirSync(outDir, { recursive: true });

const items = [...sampleItems(), ...extendedItems()].map((r) => parseItem(r));
const hubOf = (defaults?: Record<string, number>) => {
  const h = sheetHub(items) as unknown as Record<string, unknown>;
  h.textDefaults = () => defaults ?? null;
  return h as unknown as ReturnType<typeof sheetHub>;
};
const keySvg = (kind: ActionKind, settings: Record<string, unknown>) => {
  const s = new MockSurface("Keypad", "XL-1");
  const v = new ActionView(kind, hubOf(), s, settings);
  v.draw(true);
  v.dispose();
  return s.svg;
};
const img = (svg: string) => `<img class="k" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">`;

const KEYS: [string, ActionKind, Record<string, unknown>][] = [
  ["Control · Classic", "control", { item: "Lampa" }],
  ["Reading · Big value", "reading", { item: "read:0xe5:temperature", theme: "bigvalue" }],
  ["Thermostat · Gauge", "thermostat", { item: "zb:0xc3:trv", theme: "gauge" }],
  ["Dimmer · Tile", "dimmer", { item: "zb:0xb2:light", theme: "tile" }],
  ["House power · Huge", "power", { theme: "huge" }],
  ["Room · Classic", "room", { item: "room:r2" }],
  ["Light · Name bar", "control", { item: "zb:0xa1:state_l1", theme: "namebar" }],
  ["Thermostat · Stacked", "thermostat", { item: "zb:0xc3:trv", theme: "stacked" }],
];
const COLS: [string, Record<string, unknown>][] = [
  ["value 70 %", { textValue: 70 }], ["100 %", {}], ["value 150 %", { textValue: 150 }],
  ["name 70 %", { textName: 70 }], ["name 150 %", { textName: 150 }], ["both 150 %", { textValue: 150, textName: 150 }],
];
let table = `<table><tr><th></th>${COLS.map(([c]) => `<th>${esc(c)}</th>`).join("")}</tr>`;
for (const [title, kind, s] of KEYS) table += `<tr><td class="lab">${esc(title)}</td>${COLS.map(([, x]) => `<td>${img(keySvg(kind, { ...s, ...x }))}</td>`).join("")}</tr>`;
table += "</table>";

const { chromium } = require("playwright");
const browser = await chromium.launch();
try {
  // the inspector: a Control key with sizes of its own, and the type's default for the name
  const kind: ActionKind = "control";
  const settings = { item: "Lampa", theme: "bigvalue", textValue: 150, textDetail: 80 };
  const defaults = { textName: 120 };
  const hub = hubOf(defaults);
  const v = new ActionView(kind, hub, new MockSurface("Keypad", "XL-1"), settings);
  const msgs = [{ t: "status", status: hub.status() }, catalogMessage(hub, kind), { t: "textDefaults", kind, sizes: defaults },
    { t: "preview", image: v.previewImage(), looks: v.previewSet(), facts: v.facts() }];
  v.dispose();
  const pg = await browser.newPage({ viewport: { width: 350, height: 900 }, deviceScaleFactor: 2 });
  await pg.addInitScript((init: { msgs: unknown[] }) => {
    class MockWS {
      readyState = 1;
      onopen: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      constructor() {
        setTimeout(() => this.onopen?.(), 5);
      }
      send(raw: string) {
        const m = JSON.parse(raw);
        if (m.event === "sendToPlugin" && m.payload?.t === "hello") {
          for (const p of init.msgs) setTimeout(() => this.onmessage?.({ data: JSON.stringify({ event: "sendToPropertyInspector", payload: p }) }), 5);
        }
      }
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = MockWS;
  }, { msgs });
  await pg.goto(pathToFileURL(join(root, "com.zigmon.streamdeck.sdPlugin", "ui", kind + ".html")).href);
  await pg.evaluate(([st, k]: [Record<string, unknown>, string]) => {
    (window as unknown as { connectElgatoStreamDeckSocket: (...a: string[]) => void }).connectElgatoStreamDeckSocket(
      "1", "PI", "registerPropertyInspector", "{}", JSON.stringify({ action: "com.zigmon.streamdeck." + k, device: "XL-1", payload: { settings: st } }));
  }, [settings, kind] as [Record<string, unknown>, string]);
  await pg.waitForTimeout(300);
  const piPng = join(outDir, "text-sizes-pi.png");
  // the group with the card round it
  const box = await pg.evaluate(() => {
    const t = document.querySelector(".tsz")!.getBoundingClientRect(), c = document.querySelector(".look-card")!.getBoundingClientRect();
    return { x: c.left, y: t.top - 12, width: c.width, height: t.height + 24 };
  });
  await pg.screenshot({ path: piPng, clip: box, fullPage: true });
  await pg.close();

  const page = `<!doctype html><html><head><meta charset="utf-8"><style>
    body{background:#0D1117;color:#E6E9EF;font:13px "Segoe UI",Inter,sans-serif;margin:24px} h1{font-size:18px;margin:0 0 14px} h2{font-size:13px;color:#8B94A3;margin:0 0 8px;font-weight:600}
    .row{display:flex;gap:28px;align-items:flex-start} .pi img{width:350px;border-radius:12px;box-shadow:0 0 0 1px #262C37}
    table{border-collapse:separate;border-spacing:8px 6px} th{font-size:11.5px;color:#8B94A3;font-weight:600} td.lab{font-size:12px;color:#8B94A3;text-align:right;padding-right:6px}
    img.k{width:112px;height:112px;border-radius:14px;display:block}
    </style></head><body><h1>ZIGMon for Stream Deck 1.3 - text sizes (${THEMES.length} looks and Classic)</h1><div class="row">
    <div class="pi"><h2>Inspector · Look · Text sizes (Control, value 150 %, detail 80 %, name from the type's default 120 %)</h2><img src="${pathToFileURL(piPng).href}"></div>
    <div><h2>Keys: the value and the name at 70 / 100 / 150 %</h2>${table}</div></div></body></html>`;
  const html = join(outDir, "text-sizes.html");
  writeFileSync(html, page);
  const p2 = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
  await p2.goto(pathToFileURL(html).href);
  await p2.waitForTimeout(300);
  await p2.screenshot({ path: outPng, fullPage: true });
  await p2.close();
} finally {
  await browser.close();
}
console.log("text sizes: " + outPng);
