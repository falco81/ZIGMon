/**
 * Screenshots of what the plugin draws, for looking at (not part of the build):
 * a Stream Deck XL page, a Stream Deck + with its touch strip, the special states, and every
 * property inspector at 350 px - all from the real code, driven against the fake ZIGMon.
 *   node out/scripts/shots.js <output dir>   (and, since 1.3, new-actions-sheet.png: scripts/sheet.ts)
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { NodeTransport } from "../src/core/http.js";
import { Hub } from "../src/core/hub.js";
import { LAYOUTS, type Layout } from "../src/core/layouts.js";
import { P } from "../src/core/palette.js";
import { catalogMessage, statusMessage } from "../src/core/piapi.js";
import { renderHold, renderToast } from "../src/core/render.js";
import { FakeProtector } from "../src/core/secrets.js";
import { esc, fit } from "../src/core/svg.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { parseItem } from "../src/core/protocol.js";
import { parseSmsBook, type SmsBook } from "../src/core/smsbook.js";
import { extendedItems, FakeZigmon, MemoryStore, MockSurface, sampleBook, sampleItems, until } from "../test/fake-zigmon.js";
import { newActionsSheet } from "./sheet.js";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const out = process.argv[2] ?? join(root, "out", "shots");
mkdirSync(out, { recursive: true });

const DECKS = [
  { id: "XL-1", type: 2, name: "Office XL", cols: 8, rows: 4 },
  { id: "PLUS-1", type: 7, name: "Stream Deck +", cols: 4, rows: 2 },
];

/** The touch strip as Stream Deck would compose it from a layout and a feedback payload. */
export function stripSvg(layout: Layout, fb: Record<string, unknown>): string {
  let s = "";
  for (const it of [...layout.items].sort((a, b) => (a.zOrder ?? 0) - (b.zOrder ?? 0))) {
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

function svgOf(uri: string): string {
  return Buffer.from(uri.split(",")[1] ?? "", "base64").toString("utf8");
}

async function main(): Promise<void> {
  const fake = new FakeZigmon();
  await fake.start(20311);
  const store = new MemoryStore();
  const hub = new Hub({
    store, protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => DECKS, computer: () => "OFFICE-PC",
  });
  await hub.start();
  const pageMsgs: Record<string, unknown[]> = {};
  const kinds: ActionKind[] = ["control", "reading", "thermostat", "dimmer", "blinds", "scene", "status"];

  pageMsgs.setup = [statusMessage(hub), catalogMessage(hub, "control")];
  const pairKey = new MockSurface("Keypad", "XL-1");
  const pv = new ActionView("control", hub, pairKey, { item: "Lampa" });
  hub.watch(pv);
  await hub.connect("http://localhost:" + fake.port);
  await until(() => hub.pairCode !== null, 5000, "a code");
  pv.draw(true);
  const pairSvg = pairKey.svg;
  pageMsgs.pairing = [statusMessage(hub), catalogMessage(hub, "control")];
  fake.approveAll();
  await until(() => hub.currentPhase === "online" && hub.allItems().length > 0, 8000, "online");
  hub.unwatch(pv);
  // a little history for the sparklines: watched first, then the values arrive one by one by the long poll
  for (const id of ["read:0xe5:temperature", "read:0xf6:power", "read:0xa7:co2", "read:0xe5:humidity"]) hub.watch(new ActionView("reading", hub, new MockSurface("Keypad", "XL-1"), { item: id }));
  await new Promise((r) => setTimeout(r, 600));
  const series: [string, number[], (v: number) => string][] = [
    ["read:0xe5:temperature", [5.2, 5.0, 5.6, 6.1, 6.4, 6.0, 6.8, 7.1, 6.9, 7.3], (v) => v.toFixed(1) + " °C"],
    ["read:0xf6:power", [900, 1210, 1500, 1980, 2100, 1700, 1650, 1840], (v) => v + " W"],
    ["read:0xa7:co2", [640, 700, 880, 950, 1100, 1240, 1320], (v) => v + " ppm"],
    ["read:0xe5:humidity", [88, 86, 86, 84, 83, 82, 81], (v) => v + " %"],
  ];
  for (let i = 0; i < 10; i++) {
    for (const [id, vals, txt] of series) if (vals[i] !== undefined) fake.setState(id, { value: vals[i], value_text: txt(vals[i]!), at: 1700000000 + i });
    await new Promise((r) => setTimeout(r, 120));
  }

  type K = [ActionKind, Record<string, unknown>];
  const xl: (K | "pair" | "hold" | "toast" | "notapproved" | "offline" | "choose")[] = [
    ["control", { item: "Lampa" }], ["control", { item: "zb:0xa1:state_l1" }], ["dimmer", { item: "zb:0xb2:light" }], ["thermostat", { item: "zb:0xc3:trv" }],
    ["blinds", { item: "zb:0xd4:cover" }], ["scene", { item: "scene:3" }], ["scene", { item: "seq:1" }], ["status", { item: "status:alerts" }],
    ["reading", { item: "read:0xe5:temperature" }], ["reading", { item: "read:0xe5:humidity" }], ["reading", { item: "read:0xf6:power", warnAbove: 1500, critAbove: 2500 }],
    ["reading", { item: "read:0xa7:co2", label: "CO₂ office", warnAbove: 1000, critAbove: 1500 }],
    ["control", { item: "Garage" }], ["scene", { item: "sys:reboot" }], ["control", { item: "rule:7" }], ["status", { item: "status:blocked" }],
    ["status", { item: "status:proxy" }], ["status", { item: "status:health" }], ["status", { item: "status:gateway" }], ["control", { item: "Lampa", showRoom: false }],
    "hold", "toast", "pair", "notapproved", "offline", "choose",
    ["dimmer", { item: "zb:0xb2:light" }], ["thermostat", { item: "zb:0xc3:trv" }], ["blinds", { item: "zb:0xd4:cover" }], ["scene", { item: "scene:3" }],
    ["control", { item: "zb:0xa1:state_l1" }], ["reading", { item: "read:0xe5:temperature", decimals: 1 }],
  ];
  const views: { v: ActionView; s: MockSurface }[] = [];
  const make = (kind: ActionKind, settings: Record<string, unknown>, ctl: "Keypad" | "Encoder", deck: string) => {
    const s = new MockSurface(ctl, deck);
    const v = new ActionView(kind, hub, s, settings);
    hub.watch(v);
    views.push({ v, s });
    return { v, s };
  };
  const tiles: string[] = [];
  const garage = make("control", { item: "Garage" }, "Keypad", "XL-1");
  await new Promise((r) => setTimeout(r, 400));
  garage.v.draw(true);
  const garageSvg = garage.s.svg;
  for (const k of xl) {
    if (k === "pair") tiles.push(pairSvg);
    else if (k === "hold") tiles.push(renderHold(garageSvg, 0.62, P.ok));
    else if (k === "toast") tiles.push(renderToast(garageSvg, "Hold to confirm", "keep it pressed 1.5 s", "warn"));
    else if (k === "notapproved" || k === "offline" || k === "choose") {
      // drawn by a throwaway hub-less view: patch the phase/approval through a small stub
      const stub = Object.create(hub) as Hub;
      Object.defineProperty(stub, "currentPhase", { get: () => (k === "offline" ? "offline" : "online") });
      Object.defineProperty(stub, "pairCode", { get: () => null });
      stub.deckIsApproved = () => (k === "notapproved" ? false : true);
      const s = new MockSurface("Keypad", "XL-2");
      new ActionView("control", stub, s, k === "choose" ? {} : { item: "Lampa" }).draw(true);
      tiles.push(s.svg);
    } else {
      const { v, s } = make(k[0], k[1], "Keypad", "XL-1");
      v.draw(true);
      tiles.push(s.svg);
    }
  }
  await new Promise((r) => setTimeout(r, 300));

  // the Stream Deck +: 8 keys, 4 dials
  const plusKeys: K[] = [
    ["control", { item: "Lampa" }], ["scene", { item: "scene:3" }], ["status", { item: "status:alerts" }], ["reading", { item: "read:0xf6:power", warnAbove: 1500 }],
    ["control", { item: "zb:0xa1:state_l1" }], ["blinds", { item: "zb:0xd4:cover" }], ["thermostat", { item: "zb:0xc3:trv" }], ["dimmer", { item: "zb:0xb2:light" }],
  ];
  const plusTiles = plusKeys.map(([k, s]) => {
    const m = make(k, s, "Keypad", "PLUS-1");
    m.v.draw(true);
    return m.s.svg;
  });
  const dialSets: [ActionKind, Record<string, unknown>, string][][] = [
    [["thermostat", { item: "zb:0xc3:trv" }, "thermostat"], ["dimmer", { item: "zb:0xb2:light" }, "dimmer"], ["blinds", { item: "zb:0xd4:cover" }, "blinds"], ["reading", { item: "read:0xe5:temperature" }, "reading"]],
    [["control", { item: "Lampa" }, "control"], ["reading", { item: "read:0xa7:co2", label: "CO₂ office", warnAbove: 1000, critAbove: 1500 }, "reading"], ["status", { item: "status:alerts" }, "control"], ["scene", { item: "scene:3" }, "control"]],
  ];
  const strips: string[][] = [];
  for (const set of dialSets) {
    const row: string[] = [];
    for (const [k, s, layout] of set) {
      const m = make(k, s, "Encoder", "PLUS-1");
      m.v.draw(true);
      row.push(stripSvg(LAYOUTS[layout]!, m.s.feedbacks[m.s.feedbacks.length - 1] as Record<string, unknown>));
    }
    strips.push(row);
  }
  // a dial being turned: the dimmer at once shows the new value
  const turning = make("dimmer", { item: "zb:0xb2:light" }, "Encoder", "PLUS-1");
  turning.v.rotate(-6);
  const turned = stripSvg(LAYOUTS.dimmer!, turning.s.feedbacks[turning.s.feedbacks.length - 1] as Record<string, unknown>);

  for (const k of kinds) pageMsgs["online-" + k] = [statusMessage(hub), catalogMessage(hub, k)];
  const previews: Record<string, string> = {};
  for (const [k, s] of [["control", { item: "Lampa" }], ["reading", { item: "read:0xe5:temperature" }], ["thermostat", { item: "zb:0xc3:trv" }], ["dimmer", { item: "zb:0xb2:light" }], ["blinds", { item: "zb:0xd4:cover" }], ["scene", { item: "scene:3" }], ["status", { item: "status:alerts" }]] as [ActionKind, Record<string, unknown>][]) {
    previews[k] = new ActionView(k, hub, new MockSurface("Keypad", "XL-1"), s).previewImage();
  }
  const onlineStatus = statusMessage(hub);
  const st = onlineStatus.status as Record<string, unknown>;
  const decksApproved = (st.decks as { id: string; approved: boolean | null }[]).map((d) => ({ ...d, approved: d.id === "PLUS-1" ? false : d.approved }));
  const statusOpen = { t: "status", status: { ...st, decks: decksApproved } };
  const statusUpdate = { t: "status", status: { ...st, update: { version: "1.1.0" } } };
  const statusCert = {
    t: "status", status: {
      ...st, phase: "cert", message: "This computer does not trust the server's certificate.",
      cert: { scope: "zigmon.local:443", verdict: "untrusted", fingerprint: "3A:7F:C2:19:84:5D:0E:B1:66:A9:23:F4:7C:08:D2:55:91:BE:4A:3C:E7:60:1F:9D:2B:C8:75:04:AE:3E:69:D0", subject: "zigmon.local", issuer: "zigmon.local", validTo: "Nov 27 10:00:00 2027 GMT" },
    },
  };
  const statusOffline = { t: "status", status: { ...st, phase: "offline", message: "nothing answers at that address (connection refused)", retryInMs: 8000 } };
  const statusOff = { t: "status", status: { ...st, phase: "off", message: "Stream Deck control is switched off in ZIGMon (Settings → Stream Deck)." } };
  // (1.3) the SMS key's recipient picker: a 5.59.4 with the cap sms and its address book, and one without the book
  const smsItems = [...sampleItems(), ...extendedItems()].map((r) => parseItem(r));
  const smsHub = (book: SmsBook | null) => {
    const stub = Object.create(hub) as Hub;
    const byId = new Map(smsItems.map((i) => [i.id, i]));
    stub.allItems = () => smsItems;
    stub.allRooms = () => [];
    stub.item = (id) => (id ? byId.get(id) : undefined);
    stub.state = (id) => (id ? byId.get(id)?.state : undefined);
    stub.smsBook = () => book;
    stub.supports = () => true;
    Object.defineProperty(stub, "currentPhase", { get: () => "online" });
    Object.defineProperty(stub, "pairCode", { get: () => null });
    stub.deckIsApproved = () => true;
    return stub;
  };
  const statusSms = { t: "status", status: { ...st, zigmon: "5.59.4", features: ["extended", "timer", "summaries-5.59.4", "sms"], install: { ...(st.install as object), caps: { ...((st.install as { caps: object }).caps), sms: { on: true, all: true, targets: [] } } } } };
  const smsTo = ["contact:c_5f2a9e", "group:Work", "+420777123456", "contact:c_00ff00"];
  const smsSettings = { smsMode: "compose", smsTo };
  const smsPreview = (book: SmsBook | null) => ({ t: "preview", image: new ActionView("sms", smsHub(book), new MockSurface("Keypad", "XL-1"), smsSettings).previewImage() });
  const smsBook = parseSmsBook(sampleBook());
  const smsMsgs = [statusSms, catalogMessage(smsHub(smsBook), "sms"), smsPreview(smsBook)];
  const smsNoBook = [statusSms, catalogMessage(smsHub(null), "sms"), smsPreview(null)];

  // ---------------------------------------------------------------- pages
  const deckPage = (title: string, inner: string, w: number) => `<!doctype html><html><head><meta charset="utf-8"><style>
    body{margin:0;background:radial-gradient(120% 120% at 50% 0%,#1b222c,#07090c);font-family:Inter,sans-serif;color:#8B94A3;padding:28px;width:${w}px}
    h1{font-size:15px;font-weight:600;margin:0 0 14px;color:#E6E9EF;letter-spacing:.02em}
    .deck{background:linear-gradient(#1a1d22,#0e1013);border-radius:28px;padding:26px;box-shadow:0 20px 60px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.06);display:inline-block}
    .grid{display:grid;gap:18px}
    .grid img{width:118px;height:118px;border-radius:16px;box-shadow:0 0 0 2px #050607,0 4px 10px rgba(0,0,0,.6)}
    .strip{display:flex;margin-top:18px;border-radius:10px;overflow:hidden;box-shadow:0 0 0 2px #050607}
    .strip img{width:200px;height:100px;display:block}
    .dials{display:flex;justify-content:space-around;margin-top:18px}
    .dial{width:64px;height:64px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#3a3f47,#15171b 70%);box-shadow:0 4px 10px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,255,255,.12)}
    .cap{font-size:12px;margin:8px 0 22px}
    </style></head><body><h1>${title}</h1>${inner}</body></html>`;
  const img = (svg: string, cls = "") => `<img class="${cls}" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">`;
  writeFileSync(join(out, "xl.html"), deckPage("Stream Deck XL — 32 keys", `<div class="deck"><div class="grid" style="grid-template-columns:repeat(8,118px)">${tiles.map((t) => img(t)).join("")}</div></div>`, 1300));
  const plusInner = (row: string[]) => `<div class="deck"><div class="grid" style="grid-template-columns:repeat(4,118px);gap:18px 64px;padding:0 30px">${plusTiles.map((t) => img(t)).join("")}</div>`
    + `<div class="strip">${row.map((t) => img(t)).join("")}</div><div class="dials">${"<div class=dial></div>".repeat(4)}</div></div>`;
  writeFileSync(join(out, "plus.html"), deckPage("Stream Deck + — 8 keys, 4 dials, touch strip", plusInner(strips[0]!) + `<div class="cap">thermostat · light · blinds · reading</div>` + plusInner(strips[1]!) + `<div class="cap">control · reading with thresholds · ZIGMon status · scene</div>`
    + `<div class="strip" style="display:inline-flex">${img(turned)}</div><div class="cap">a dial being turned (shown at once, sent as one delta)</div>`, 900));
  const big = tiles.slice(0, 8).concat(tiles.slice(20, 24)).map((t) => img(t)).join("");
  writeFileSync(join(out, "keys-2x.html"), deckPage("Keys at full 144 px", `<div class="grid" style="grid-template-columns:repeat(6,144px)">${big.replace(/<img class=""/g, '<img style="width:144px;height:144px;border-radius:18px"')}</div>`, 1000));

  const { chromium } = require("playwright");
  const browser = await chromium.launch();
  try {
    for (const [name, w] of [["xl", 1360], ["plus", 960], ["keys-2x", 1060]] as const) {
      const page = await browser.newPage({ viewport: { width: w, height: 600 }, deviceScaleFactor: 1 });
      await page.goto(pathToFileURL(join(out, name + ".html")).href);
      await page.waitForTimeout(200);
      await page.screenshot({ path: join(out, name + ".png"), fullPage: true });
      await page.close();
    }
    // the property inspectors
    const ui = join(root, "com.zigmon.streamdeck.sdPlugin", "ui");
    const pis: [string, ActionKind, unknown[], Record<string, unknown>, string?][] = [
      ["pi-setup", "control", pageMsgs.setup!, {}],
      ["pi-pairing", "control", pageMsgs.pairing!, {}],
      ["pi-cert", "control", [statusCert], {}],
      ["pi-offline", "reading", [statusOffline], { item: "read:0xe5:temperature" }],
      ["pi-off", "control", [statusOff], {}],
      ["pi-control-picker", "control", pageMsgs["online-control"]!, {}],
      ["pi-control-search", "control", pageMsgs["online-control"]!, {}, "search"],
      ["pi-control", "control", [...pageMsgs["online-control"]!, { t: "preview", image: previews.control }], { item: "Lampa", press: "toggle" }],
      ["pi-connection", "control", [statusOpen, pageMsgs["online-control"]![1], { t: "preview", image: previews.control }], { item: "Garage" }, "open"],
      ["pi-update", "scene", [statusUpdate, pageMsgs["online-scene"]![1], { t: "preview", image: previews.scene }], { item: "scene:3" }],
      ["pi-reading", "reading", [...pageMsgs["online-reading"]!, { t: "preview", image: previews.reading }], { item: "read:0xe5:temperature", warnBelow: 0, critBelow: -10, decimals: 1 }],
      ["pi-thermostat", "thermostat", [...pageMsgs["online-thermostat"]!, { t: "preview", image: previews.thermostat }], { item: "zb:0xc3:trv" }],
      ["pi-dimmer", "dimmer", [...pageMsgs["online-dimmer"]!, { t: "preview", image: previews.dimmer }], { item: "zb:0xb2:light", step: 10 }],
      ["pi-blinds", "blinds", [...pageMsgs["online-blinds"]!, { t: "preview", image: previews.blinds }], { item: "zb:0xd4:cover" }],
      ["pi-scene", "scene", pageMsgs["online-scene"]!, {}],
      ["pi-status", "status", [...pageMsgs["online-status"]!, { t: "preview", image: previews.status }], { item: "status:alerts" }],
      ["pi-sms-picker", "sms" as ActionKind, smsMsgs, smsSettings],
      ["pi-sms-search", "sms" as ActionKind, smsMsgs, smsSettings, "smsSearch"],
      ["pi-sms-nobook", "sms" as ActionKind, smsNoBook, smsSettings],
    ];
    // node out/scripts/shots.js <dir> <name prefix>: only those inspectors (and no sheet)
    const only = process.argv[3];
    for (const [name, kind, msgs, settings, extra] of pis) {
      if (only && !name.startsWith(only)) continue;
      const page = await browser.newPage({ viewport: { width: 350, height: 640 }, deviceScaleFactor: 2 });
      await page.addInitScript((init: { msgs: unknown[] }) => {
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
      await page.goto(pathToFileURL(join(ui, kind + ".html")).href);
      await page.evaluate(([s, k]: [Record<string, unknown>, string]) => {
        (window as unknown as { connectElgatoStreamDeckSocket: (...a: string[]) => void }).connectElgatoStreamDeckSocket(
          "1", "PI", "registerPropertyInspector", "{}", JSON.stringify({ action: "com.zigmon.streamdeck." + k, device: "XL-1", payload: { settings: s } }));
      }, [settings, kind] as [Record<string, unknown>, string]);
      await page.waitForTimeout(250);
      if (extra === "search") {
        await page.fill('input[type="search"]', "lam");
        await page.waitForTimeout(100);
      }
      if (extra === "smsSearch") {
        await page.fill('input[data-key="smsSearch"]', "nov");
        await page.waitForTimeout(100);
      }
      if (extra === "open") {
        await page.click(".head.collapse");
        await page.waitForTimeout(100);
      }
      await page.screenshot({ path: join(out, name + ".png"), fullPage: true });
      await page.close();
    }
  } finally {
    await browser.close();
    hub.stop();
    await fake.stop();
  }
  // (1.3) the ten new actions on a sheet of their own
  if (process.argv[3]) return void console.log("screenshots in " + out);
  console.log("new actions: " + (await newActionsSheet(out)));
  console.log("screenshots in " + out);
}

await main();
