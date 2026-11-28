/**
 * (1.3) A contact sheet of the ten new actions, for looking at (not part of the build): each in
 * Classic and six other looks, lit and unlit, from real states; their touch strips; the special
 * states (an older ZIGMon, no desktop app, a hold, offline); and their property inspectors.
 *   node out/scripts/sheet.js <output dir>      (shots.js calls it too)
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { Hub, Status } from "../src/core/hub.js";
import { LAYOUTS } from "../src/core/layouts.js";
import { catalogMessage } from "../src/core/piapi.js";
import { parseItem, type Item } from "../src/core/protocol.js";
import { renderHold, renderToast } from "../src/core/render.js";
import { esc, fit } from "../src/core/svg.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { extendedItems, MockSurface, sampleItems, type FakeItem } from "../test/fake-zigmon.js";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");

/** The touch strip as Stream Deck composes it from a layout and a feedback payload. */
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
      const txt = fit(String(v.value ?? ""), size, w, weight);
      const al = it.alignment ?? "center";
      const tx = al === "left" ? x : al === "right" ? x + w : x + w / 2;
      s += `<text x="${tx}" y="${y + h / 2 + size * 0.36}" font-family="Segoe UI, Inter, sans-serif" font-size="${size}" font-weight="${weight}" fill="${esc(String(v.color ?? it.color ?? "#fff"))}" text-anchor="${al === "left" ? "start" : al === "right" ? "end" : "middle"}">${esc(txt)}</text>`;
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" fill="#000"/>${s}</svg>`;
}

const LAYOUT_OF: Record<string, string> = { power: "power", timer: "timer", room: "room" };

/** A stand-in hub over fixed items (patched per variant), as a ZIGMon 5.59.4 would show them. */
export function sheetHub(items: Item[], o: { features?: string[]; phase?: string; command?: Hub["command"] } = {}): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  const features = o.features ?? ["extended", "timer", "summaries-5.59.4"];
  const status: Status = {
    phase: (o.phase ?? "online") as Status["phase"], message: "", plugin: "1.3.0", address: "https://zigmon.local", house: "Chalupa", zigmon: features.length ? "5.59.4" : "5.59.3", features,
    install: { name: "OFFICE-PC", hint: "x9", caps: { view: { on: true, all: true, targets: [], hold: false }, switch: { on: true, all: true, targets: [], hold: false }, climate: { on: true, all: true, targets: [], hold: false }, status: { on: true, all: true, targets: [], hold: false }, system: { on: true, all: false, targets: ["status:security", "status:sms"], hold: true }, sms: { on: true, all: true, targets: [], hold: false } } },
    decks: [{ id: "XL-1", name: "Office XL", type: 2, cols: 8, rows: 4, approved: true }], pair: null, cert: null, pinned: null, update: null,
    updating: { state: "idle", message: "" }, retryInMs: null, items: items.length,
  };
  const power = [520, 480, 450, 610, 1900, 2400, 2100, 900, 760, 1300, 1700, 2600, 3100, 2200, 1400, 1100, 980, 1500, 1842];
  return {
    currentPhase: o.phase ?? "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [], series: (id: string) => (id === "house:power" ? power : null),
    supports: (f: string) => features.includes(f), deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
    command: o.command ?? (async () => ({ ok: true, said: "", state: null })), allItems: () => [...map.values()], allRooms: () => [{ id: "2", name: "Ložnice" }], status: () => status,
  } as unknown as Hub;
}

function patched(base: FakeItem[], id: string, patch: Record<string, unknown>): Item[] {
  return base.map((r) => {
    if (r.id !== id) return parseItem(r);
    const c = JSON.parse(JSON.stringify(r)) as FakeItem;
    const { attrs, ...rest } = patch as { attrs?: Record<string, unknown> };
    c.state = { ...c.state, ...rest, attrs: { ...(c.state.attrs as object), ...(attrs ?? {}) } };
    return parseItem(c);
  });
}

type Row = { title: string; kind: ActionKind; settings: Record<string, unknown>; id: string; on: Record<string, unknown>; off: Record<string, unknown> };

export function rows(now = Math.floor(Date.now() / 1000)): Row[] {
  return [
    { title: "House power", kind: "power", settings: {}, id: "house:power", on: {}, off: { value: 0, value_text: "0 W", attrs: { power: 0, kwh_today: 0.4 } } },
    { title: "Network security", kind: "security", settings: {}, id: "status:security", on: {}, off: { value: 0, on: true, attrs: { alerts: 0, alerts_24h: 0, level: "ok" } } },
    { title: "Heating everywhere", kind: "heatgroup", settings: {}, id: "heat:group:all", on: {}, off: { on: false, value_text: "eco", attrs: { mode: "eco", calling: 0 } } },
    { title: "Away / Home", kind: "away", settings: {}, id: "house:away", on: { on: true, value_text: "away", attrs: { away: true, lights_on: 0, rooms_heating: 0 } }, off: {} },
    { title: "Windows & doors", kind: "openings", settings: {}, id: "house:openings", on: {}, off: { on: true, value: 0, attrs: { open: 0, names: [], heating_loss: false } } },
    { title: "Batteries", kind: "batteries", settings: {}, id: "house:batteries", on: {}, off: { on: true, value: 64, attrs: { level: "ok", below_20: 0, below_10: 0, lowest_name: "Okno", lowest_pct: 64 } } },
    { title: "Zigbee network", kind: "zigbee", settings: {}, id: "status:zigbee", on: {}, off: { on: true, value: 24, attrs: { level: "ok", online_n: 24, offline_n: 0 } } },
    { title: "Timer", kind: "timer", settings: { item: "Lampa", minutes: 30 }, id: "Lampa", on: { on: true, attrs: { off_at: now + 1234 } }, off: { on: false } },
    { title: "Room", kind: "room", settings: { item: "room:r2" }, id: "room:r2", on: {}, off: { on: false, attrs: { calling: false, switches_on: 0, heat_mode: "eco", heat_target: 18 } } },
    { title: "SMS · latest", kind: "sms", settings: { smsMode: "last" }, id: "sms:last", on: {}, off: { attrs: { unread: 0 } } },
    { title: "SMS · write", kind: "sms", settings: { smsMode: "compose", smsTo: ["group:Family", "+420777123456"] }, id: "sms:compose", on: { attrs: { unread: 2 } }, off: {} },
    { title: "SMS · status", kind: "sms", settings: { smsMode: "status" }, id: "status:sms", on: { attrs: { muted_until: now + 3600 } }, off: {} },
  ];
}

export const SHEET_LOOKS = ["neon", "light", "huge", "lcd", "tile", "aurora"];

export async function newActionsSheet(out: string): Promise<string> {
  mkdirSync(out, { recursive: true });
  const base = [...sampleItems(), ...extendedItems()];
  const img = (svg: string, cls = "") => `<img class="${cls}" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">`;
  const keyOf = (kind: ActionKind, items: Item[], settings: Record<string, unknown>, ctl: "Keypad" | "Encoder" = "Keypad", hubOpts = {}) => {
    const s = new MockSurface(ctl, "XL-1");
    const v = new ActionView(kind, sheetHub(items, hubOpts), s, settings);
    v.draw(true);
    v.dispose();
    return { s, v };
  };
  let html = "";
  // ---------------------------------------------------------------- the keys
  html += `<h2>The ten new actions - Classic, then ${SHEET_LOOKS.length} other looks; each lit, then unlit (real states)</h2><table class="keys"><tr><th></th><th colspan="2">Classic</th>${SHEET_LOOKS.map((l) => `<th colspan="2">${THEMES.find((t) => t.id === l)!.name}</th>`).join("")}</tr>`;
  const stripRows: string[] = [];
  for (const r of rows()) {
    const on = patched(base, r.id, r.on), off = patched(base, r.id, r.off);
    let tr = `<tr><td class="lab">${esc(r.title)}</td>`;
    for (const look of ["classic", ...SHEET_LOOKS]) {
      for (const items of [on, off]) tr += `<td>${img(keyOf(r.kind, items, { ...r.settings, theme: look === "classic" ? undefined : look }).s.svg, "k")}</td>`;
    }
    html += tr + "</tr>";
    const layout = LAYOUT_OF[r.kind] ?? "summary";
    const strip = (items: Item[], theme?: string) => stripSvg(layout, keyOf(r.kind, items, { ...r.settings, theme }, "Encoder").s.feedbacks.at(-1) as Record<string, unknown>);
    stripRows.push(`<div class="sr"><div class="lab">${esc(r.title)}</div>${img(strip(on), "s")}${img(strip(off), "s")}${img(strip(on, "glass"), "s")}${img(strip(off, "light"), "s")}</div>`);
  }
  html += "</table>";
  // ---------------------------------------------------------------- the strips
  html += `<h2>Stream Deck + touch strips - Classic lit, Classic unlit, Glass lit, Light unlit</h2><div class="strips">${stripRows.join("")}</div>`;
  // ---------------------------------------------------------------- special states
  const all = base.map((r) => parseItem(r));
  const special: [string, string][] = [];
  special.push(["ZIGMon before 5.59.4", keyOf("power", all, {}, "Keypad", { features: [] }).s.svg]);
  const sec = keyOf("security", all, {}).s.svg;
  special.push(["held: acknowledge", renderHold(sec, 0.6, "#F85149")]);
  special.push(["SMS: no desktop app (409)", renderToast(keyOf("sms", all, {}).s.svg, "Desktop app not running", "link one in ZIGMon", "warn")]);
  const offline = patched(base, "house:openings", { online: false });
  special.push(["offline", keyOf("openings", offline, {}).s.svg]);
  const noSys = base.map((r) => (r.id === "status:security" ? parseItem({ ...r, act: { ack: { cap: "system", allowed: false, hold: true } } }) : parseItem(r)));
  special.push(["watch only (no System)", keyOf("security", noSys, {}).s.svg]);
  special.push(["Timer: dial set 45 min", (() => {
    const s = new MockSurface("Keypad", "XL-1");
    const v = new ActionView("timer", sheetHub(patched(base, "Lampa", { on: false })), s, { item: "Lampa", minutes: 45 });
    v.draw(true);
    v.dispose();
    return s.svg;
  })()]);
  special.push(["Control: Timer press, running", keyOf("control", patched(base, "Lampa", { on: true, attrs: { off_at: Math.floor(Date.now() / 1000) + 754 } }), { item: "Lampa", press: "timer", minutes: 15 }).s.svg]);
  special.push(["own colours (rose / slate)", keyOf("heatgroup", patched(base, "heat:group:all", {}), { accent: "rose", accentOff: "slate" }).s.svg]);
  special.push(["own colours, off", keyOf("heatgroup", patched(base, "heat:group:all", { on: false, attrs: { calling: 0 } }), { accent: "rose", accentOff: "slate" }).s.svg]);
  special.push(["long label, Shrink to fit", keyOf("openings", all, { label: "Okna a dveře v celém domě", nameFit: "fit" }).s.svg]);
  special.push(["icon only", keyOf("zigbee", all, { showName: false, showState: false, showDetail: false, showGraph: false, showMode: false }).s.svg]);
  special.push(["Room dial: 2nd member", (() => {
    const s = new MockSurface("Encoder", "PLUS-1");
    const v = new ActionView("room", sheetHub(all), s, { item: "room:r2" });
    v.rotate(1);
    v.draw(true);
    v.dispose();
    return stripSvg("room", s.feedbacks.at(-1) as Record<string, unknown>);
  })()]);
  html += `<h2>Special states</h2><div class="special">${special.map(([t, svg]) => `<figure>${img(svg, svg.includes('width="200"') ? "s" : "k")}<figcaption>${esc(t)}</figcaption></figure>`).join("")}</div>`;
  // ---------------------------------------------------------------- every look, for one
  html += `<h2>All 42 looks - Windows &amp; doors (open, heat escaping)</h2><div class="all">${THEMES.map((t) => img(keyOf("openings", all, { theme: t.id === "classic" ? undefined : t.id }).s.svg, "m")).join("")}</div>`;
  html += `<h2>All 42 looks - Timer (running)</h2><div class="all">${THEMES.map((t) => img(keyOf("timer", patched(base, "Lampa", { on: true, attrs: { off_at: Math.floor(Date.now() / 1000) + 1234 } }), { item: "Lampa", minutes: 30, theme: t.id === "classic" ? undefined : t.id }).s.svg, "m")).join("")}</div>`;

  const page = `<!doctype html><html><head><meta charset="utf-8"><style>
    body{margin:0;background:radial-gradient(120% 80% at 50% 0%,#1b222c,#07090c);font-family:Inter,Segoe UI,sans-serif;color:#8B94A3;padding:26px 30px;width:1960px}
    h1{font-size:20px;color:#E6E9EF;margin:0 0 4px} h2{font-size:14px;font-weight:600;color:#E6E9EF;margin:26px 0 12px;letter-spacing:.02em}
    table.keys{border-spacing:6px 6px} th{font-size:11.5px;font-weight:600;color:#8B94A3;text-align:center}
    td.lab,.lab{font-size:12.5px;color:#C9D1D9;font-weight:600;width:128px;text-align:right;padding-right:6px}
    img.k{width:96px;height:96px;border-radius:13px;box-shadow:0 0 0 2px #050607,0 3px 8px rgba(0,0,0,.6);display:block}
    img.m{width:72px;height:72px;border-radius:10px;box-shadow:0 0 0 2px #050607;margin:0 6px 6px 0}
    img.s{width:200px;height:100px;border-radius:8px;box-shadow:0 0 0 2px #050607;margin-right:10px}
    .strips{display:grid;grid-template-columns:1fr 1fr;gap:10px 30px} .sr{display:flex;align-items:center}
    .special{display:flex;flex-wrap:wrap;gap:16px} figure{margin:0;text-align:center} figcaption{font-size:11.5px;margin-top:6px;max-width:200px}
    .special img.k{width:120px;height:120px} .pis{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap} .pis img{width:300px;border-radius:10px;box-shadow:0 0 0 1px #262C37}
    </style></head><body><h1>ZIGMon for Stream Deck 1.3 - the new actions (ZIGMon 5.59.4)</h1>${html}<!--PIS--></body></html>`;
  const file = join(out, "new-actions-sheet.html");
  writeFileSync(file, page);

  const { chromium } = require("playwright");
  const browser = await chromium.launch();
  try {
    // the property inspectors of a few of them, at Stream Deck's 350 px
    const ui = join(root, "com.zigmon.streamdeck.sdPlugin", "ui");
    const pis: [string, ActionKind, Record<string, unknown>][] = [
      ["pi-new-away", "away", { awayOff: ["Lampa", "zb:0xa1:state_l1"] }],
      ["pi-new-security", "security", {}],
      ["pi-new-timer", "timer", { item: "Lampa", minutes: 45 }],
      ["pi-new-sms", "sms", { smsMode: "compose", smsTo: ["group:Family", "+420777123456"] }],
      ["pi-new-openings", "openings", {}],
      ["pi-new-heat", "heatgroup", { press: "set:eco" }],
    ];
    const shots: string[] = [];
    for (const [name, kind, settings] of pis) {
      const hub = sheetHub(all);
      const s = new MockSurface("Keypad", "XL-1");
      const v = new ActionView(kind, hub, s, settings);
      const msgs = [{ t: "status", status: hub.status() }, catalogMessage(hub, kind), { t: "preview", image: v.previewImage(), looks: v.previewSet(), facts: v.facts() }];
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
      await pg.goto(pathToFileURL(join(ui, kind + ".html")).href);
      await pg.evaluate(([st, k]: [Record<string, unknown>, string]) => {
        (window as unknown as { connectElgatoStreamDeckSocket: (...a: string[]) => void }).connectElgatoStreamDeckSocket(
          "1", "PI", "registerPropertyInspector", "{}", JSON.stringify({ action: "com.zigmon.streamdeck." + k, device: "XL-1", payload: { settings: st } }));
      }, [settings, kind] as [Record<string, unknown>, string]);
      await pg.waitForTimeout(300);
      // the parts that are new: the item, "Now" and the options (the Look card is the same as every action's)
      await pg.evaluate(() => {
        const cards = Array.from(document.querySelectorAll<HTMLElement>(".card"));
        for (const c of cards) if (c.classList.contains("look-card")) c.style.display = "none";
        const first = cards[0];
        if (first && !first.querySelector(".picked, .note, .chips") && cards.length > 2) first.style.display = "none";
      });
      const p = join(out, name + ".png");
      await pg.screenshot({ path: p, fullPage: true });
      await pg.close();
      shots.push(`<figure><img src="${pathToFileURL(p).href}"><figcaption>${esc(name.replace("pi-new-", "inspector: "))}</figcaption></figure>`);
    }
    writeFileSync(file, page.replace("<!--PIS-->", `<h2>The new inspector sections (Look card left out: it is every action's)</h2><div class="pis">${shots.join("")}</div>`));
    const pg = await browser.newPage({ viewport: { width: 1700, height: 900 }, deviceScaleFactor: 1 });
    await pg.goto(pathToFileURL(file).href);
    await pg.waitForTimeout(400);
    const png = join(out, "new-actions-sheet.png");
    await pg.screenshot({ path: png, fullPage: true });
    await pg.close();
    return png;
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  console.log("sheet: " + (await newActionsSheet(process.argv[2] ?? join(root, "out", "shots"))));
}
