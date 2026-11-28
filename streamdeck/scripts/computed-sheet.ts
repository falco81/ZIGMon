/**
 * (1.3) A contact sheet of the Computed action, for looking at (not part of the build): its
 * inspector's builder (Popular, What, How, Where, the item and its live value), and Computed keys
 * of real items in Classic and several other looks, their touch strips, and an older ZIGMon.
 *   node out/scripts/computed-sheet.js <output png>
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { LAYOUTS } from "../src/core/layouts.js";
import { catalogMessage } from "../src/core/piapi.js";
import type { Hub } from "../src/core/hub.js";
import { parseItem } from "../src/core/protocol.js";
import { esc, fit } from "../src/core/svg.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView } from "../src/core/views.js";
import { calcItems, extendedItems, MockSurface, sampleItems } from "../test/fake-zigmon.js";
import { sheetHub } from "./sheet.js";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const png = process.argv[2] ?? join(root, "out", "shots", "computed.png");
const dir = dirname(png);
mkdirSync(dir, { recursive: true });

const items = [...sampleItems(), ...extendedItems(), ...calcItems()].map((r) => parseItem(r));
const FEATURES = ["extended", "timer", "summaries-5.59.4", "calc"];
/** A day of each value, so the graphs have something to say. */
function seriesOf(id: string): number[] | null {
  const it = items.find((i) => i.id === id);
  const v = it?.state.value;
  if (typeof v !== "number") return null;
  return Array.from({ length: 36 }, (_, k) => {
    const w = Math.sin(k / 5) * 0.18 + Math.sin(k / 2.3) * 0.06 + (k - 35) * 0.004;
    return Math.max(0, v * (1 + w));
  }).concat([v]);
}
function hubFor(features = FEATURES): Hub {
  return { ...sheetHub(items, { features }), series: (id: string) => seriesOf(id), history: (id: string) => seriesOf(id) ?? [] } as unknown as Hub;
}

function stripSvg(layout: string, fb: Record<string, unknown>): string {
  let s = "";
  for (const it of [...LAYOUTS[layout]!.items].sort((a, b) => (a.zOrder ?? 0) - (b.zOrder ?? 0))) {
    const f = fb[it.key];
    const v = f && typeof f === "object" ? (f as Record<string, unknown>) : { value: f };
    const [x, y, w, h] = it.rect;
    if (it.type === "pixmap") {
      if (typeof v.value === "string" && v.value.startsWith("data:")) s += `<image href="${esc(v.value)}" x="${x}" y="${y}" width="${w}" height="${h}"/>`;
    } else if (it.type === "text") {
      const size = it.font?.size ?? 16, weight = it.font?.weight ?? 500;
      const al = it.alignment ?? "center";
      const tx = al === "left" ? x : al === "right" ? x + w : x + w / 2;
      s += `<text x="${tx}" y="${y + h / 2 + size * 0.36}" font-family="Segoe UI, Inter, sans-serif" font-size="${size}" font-weight="${weight}" fill="${esc(String(v.color ?? it.color ?? "#fff"))}" text-anchor="${al === "left" ? "start" : al === "right" ? "end" : "middle"}">${esc(fit(String(v.value ?? ""), size, w, weight))}</text>`;
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" fill="#000"/>${s}</svg>`;
}

const img = (svg: string, cls = "") => `<img class="${cls}" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">`;
function key(settings: Record<string, unknown>, ctl: "Keypad" | "Encoder" = "Keypad", features?: string[]): MockSurface {
  const s = new MockSurface(ctl, "XL-1");
  const v = new ActionView("computed", hubFor(features), s, settings);
  v.draw(true);
  v.dispose();
  return s;
}

const ROWS: [string, Record<string, unknown>][] = [
  ["Total power", { item: "calc:sum:power:all", warnAbove: 2000, critAbove: 3000 }],
  ["Power of lights", { item: "calc:sum:power:kind=light" }],
  ["Lights on", { item: "calc:on:state:kind=light" }],
  ["Average inside", { item: "calc:avg:temperature:inside", decimals: 1 }],
  ["Coldest room", { item: "calc:min:room_temperature:inside", warnBelow: 19, critBelow: 16 }],
  ["Windows open", { item: "calc:on:open:all", label: "Windows open" }],
  ["Devices offline", { item: "calc:off:online:all", warnAbove: 1 }],
  ["Low batteries", { item: "calc:on:battery_low:all", warnAbove: 1, critAbove: 4 }],
  ["Energy today", { item: "calc:sum:energy_today:all" }],
];
const LOOKS = ["classic", "bigvalue", "neon", "light", "huge", "gauge", "lcd", "aurora", "namebar"].filter((l) => THEMES.some((t) => t.id === l));

let html = `<table class="keys"><tr><th></th>${LOOKS.map((l) => `<th>${esc(THEMES.find((t) => t.id === l)!.name)}</th>`).join("")}</tr>`;
for (const [title, s] of ROWS) {
  html += `<tr><td class="lab">${esc(title)}</td>${LOOKS.map((l) => `<td>${img(key({ ...s, theme: l === "classic" ? undefined : l }).svg, "k")}</td>`).join("")}</tr>`;
}
html += "</table>";
const strips = ROWS.slice(0, 4).map(([, s]) => img(stripSvg("reading", key(s, "Encoder").feedbacks.at(-1) as Record<string, unknown>), "s")).join("")
  + ROWS.slice(0, 2).map(([, s]) => img(stripSvg("reading", key({ ...s, theme: "glass" }, "Encoder").feedbacks.at(-1) as Record<string, unknown>), "s")).join("");
const special: [string, string][] = [
  ["ZIGMon before 5.59.4", key({ item: "calc:sum:power:all" }, "Keypad", ["extended", "timer"]).svg],
  ["nothing chosen yet", key({}).svg],
  ["Total power, red above 300 W", key({ item: "calc:sum:power:all", critAbove: 300 }).svg],
  ["icon only", key({ item: "calc:on:state:kind=light", showName: false, showState: false, showDetail: false, showGraph: false }).svg],
];

async function main(): Promise<void> {
  const { chromium } = require("playwright");
  const browser = await chromium.launch();
  const shots: string[] = [];
  try {
    const ui = join(root, "com.zigmon.streamdeck.sdPlugin", "ui");
    const pis: [string, Record<string, unknown>, string][] = [
      ["calc-pi-lights", { item: "calc:sum:power:kind=light" }, "Power of lights picked: only lights and sockets have a power sum; Ložnice has none"],
      ["calc-pi-coldest", { item: "calc:min:temperature:inside" }, "Lowest temperature inside: no Sum of a temperature, no Min outside (one thermometer)"],
    ];
    for (const [name, settings, cap] of pis) {
      const hub = hubFor();
      const s = new MockSurface("Keypad", "XL-1");
      const v = new ActionView("computed", hub, s, settings);
      const msgs = [{ t: "status", status: (hub as unknown as { status: () => unknown }).status() }, catalogMessage(hub, "computed"), { t: "preview", image: v.previewImage(), looks: v.previewSet(), facts: v.facts() }];
      v.dispose();
      const pg = await browser.newPage({ viewport: { width: 350, height: 640 }, deviceScaleFactor: 2 });
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
      await pg.goto(pathToFileURL(join(ui, "computed.html")).href);
      await pg.evaluate((st: Record<string, unknown>) => {
        (window as unknown as { connectElgatoStreamDeckSocket: (...a: string[]) => void }).connectElgatoStreamDeckSocket(
          "1", "PI", "registerPropertyInspector", "{}", JSON.stringify({ action: "com.zigmon.streamdeck.computed", device: "XL-1", payload: { settings: st } }));
      }, settings);
      await pg.waitForTimeout(300);
      // the builder and Now (the connection, the Look and the options are every Reading's)
      await pg.evaluate(() => {
        for (const c of Array.from(document.querySelectorAll<HTMLElement>(".card"))) if (!c.classList.contains("builder") && !c.querySelector("dl.kv")) c.style.display = "none";
      });
      const p = join(dir, name + ".png");
      await pg.screenshot({ path: p, fullPage: true });
      await pg.close();
      shots.push(`<figure><img class="pi" src="${pathToFileURL(p).href}"><figcaption>${esc(cap)}</figcaption></figure>`);
    }
    const page = `<!doctype html><html><head><meta charset="utf-8"><style>
      body{margin:0;background:radial-gradient(120% 80% at 50% 0%,#1b222c,#07090c);font-family:Inter,Segoe UI,sans-serif;color:#8B94A3;padding:24px 28px;width:1640px}
      h1{font-size:20px;color:#E6E9EF;margin:0 0 4px} h2{font-size:14px;font-weight:600;color:#E6E9EF;margin:22px 0 10px}
      .wrap{display:flex;gap:28px;align-items:flex-start} .pis{display:flex;gap:14px} figure{margin:0} figcaption{font-size:11.5px;margin-top:6px;max-width:300px}
      img.pi{width:300px;border-radius:10px;box-shadow:0 0 0 1px #262C37}
      table.keys{border-spacing:5px 5px} th{font-size:11px;font-weight:600;color:#8B94A3}
      td.lab{font-size:12px;color:#C9D1D9;font-weight:600;text-align:right;padding-right:6px;width:104px}
      img.k{width:84px;height:84px;border-radius:12px;box-shadow:0 0 0 2px #050607,0 3px 8px rgba(0,0,0,.6);display:block}
      img.s{width:200px;height:100px;border-radius:8px;box-shadow:0 0 0 2px #050607;margin:0 10px 10px 0}
      .special{display:flex;gap:16px} .special img.k{width:110px;height:110px}
      </style></head><body><h1>ZIGMon for Stream Deck 1.3 - Computed (ZIGMon 5.59.4)</h1>
      <div class="wrap"><div><h2>The inspector's builder</h2><div class="pis">${shots.join("")}</div></div>
      <div><h2>Computed keys - Classic and ${LOOKS.length - 1} other looks (the fake ZIGMon's items)</h2>${html}
      <h2>Stream Deck + strips - Classic, then Glass</h2><div>${strips}</div>
      <h2>Special states</h2><div class="special">${special.map(([t, svg]) => `<figure>${img(svg, "k")}<figcaption>${esc(t)}</figcaption></figure>`).join("")}</div></div></div></body></html>`;
    const file = join(dir, "computed-sheet.html");
    writeFileSync(file, page);
    const pg = await browser.newPage({ viewport: { width: 1700, height: 900 }, deviceScaleFactor: 1 });
    await pg.goto(pathToFileURL(file).href);
    await pg.waitForTimeout(400);
    await pg.screenshot({ path: png, fullPage: true });
    await pg.close();
  } finally {
    await browser.close();
  }
  console.log("computed sheet: " + png);
}

await main();
