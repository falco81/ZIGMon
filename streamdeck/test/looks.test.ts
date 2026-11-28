/**
 * 1.1: the looks, the information shown, the accent, the label, long names, hold to confirm per
 * key, a heated room's key, and the graphs from ZIGMon's own history.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { after, describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import type { Hub } from "../src/core/hub.js";
import { Hub as RealHub } from "../src/core/hub.js";
import { NodeTransport } from "../src/core/http.js";
import { LAYOUTS } from "../src/core/layouts.js";
import { ACCENTS, ALLOWED_COLOURS } from "../src/core/palette.js";
import { parseItem, parseStateAnswer, type Item } from "../src/core/protocol.js";
import { FakeProtector } from "../src/core/secrets.js";
import { cleanLabel, LABEL_MOST, normalizeAction } from "../src/core/settings.js";
import { nameLines, smartWrap } from "../src/core/svg.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, clockOf, type ActionKind } from "../src/core/views.js";
import { FakeZigmon, MemoryStore, MockSurface, sampleItems, until } from "./fake-zigmon.js";
import { goldenCases } from "./golden.js";
import { wellFormed } from "./xml.js";
import { ICONS } from "../src/core/icons.js";

const here = dirname(fileURLToPath(import.meta.url));
const EVIL = '<script>alert(1)</script> & "q" \'s\' ‮]]>';
const KINDS: [ActionKind, string][] = [
  ["control", "Lampa"], ["control", "Garage"], ["reading", "read:0xe5:temperature"], ["thermostat", "zb:0xc3:trv"], ["dimmer", "zb:0xb2:light"],
  ["blinds", "zb:0xd4:cover"], ["scene", "scene:3"], ["status", "status:alerts"], ["status", "status:gateway"],
];
const INFO_KEYS = ["showIcon", "showName", "showRoom", "showState", "showDetail", "showMode", "showGraph", "showBattery"];

const cleanups: (() => unknown)[] = [];
after(async () => {
  for (const c of cleanups.reverse()) await c();
});

interface Sent { id: string; action: string; attr?: string; value?: unknown; delta?: number; held_ms?: number }

function stubHub(items: Item[], sent: Sent[] = [], series?: (id: string, span: number) => number[] | null): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [1, 3, 2, 5, 4],
    series: series ?? (() => null),
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
    command: async (c: Sent) => {
      sent.push(c);
      return { ok: true, said: "", state: null };
    },
  } as unknown as Hub;
}

function variant(id: string, v: string): Item {
  const r = JSON.parse(JSON.stringify(sampleItems().find((i) => i.id === id)!)) as Record<string, unknown> & { state: Record<string, unknown> };
  if (v === "on") r.state.on = true;
  if (v === "off") {
    r.state.on = false;
    const a = r.state.attrs as Record<string, unknown>;
    if (a.running_state) a.running_state = "idle";
  }
  if (v === "offline") r.state.online = false;
  if (v === "locked") r.allowed = false;
  if (v === "hold") r.hold = true;
  if (v === "evil") {
    r.name = EVIL;
    r.room = EVIL;
    r.state.value_text = EVIL;
  }
  return parseItem(r);
}

const svgOf = (uri: string) => Buffer.from(uri.split(",")[1] ?? "", "base64").toString("utf8");

/** Every colour in a drawing is one of ours; no other way of naming a colour is used. */
function ownColours(svg: string, where: string): void {
  for (const m of svg.matchAll(/(?:fill|stroke|stop-color|color)="([^"]*)"/g)) {
    const c = m[1]!;
    if (c === "none" || /^url\(#[A-Za-z0-9_-]+\)$/.test(c)) continue;
    assert.ok(ALLOWED_COLOURS.has(c.toUpperCase()), where + ": a colour not from our table: " + c);
  }
}

function key(kind: ActionKind, item: Item, settings: Record<string, unknown>, sent: Sent[] = []): { v: ActionView; s: MockSurface } {
  const s = new MockSurface("Keypad", "D");
  const v = new ActionView(kind, stubHub([item], sent), s, { item: item.id, ...settings });
  v.draw(true);
  cleanups.push(() => v.dispose());
  return { v, s };
}

describe("looks", () => {
  it("there are at least ten besides Classic, each drawn differently", () => {
    assert.ok(THEMES.length >= 11 && THEMES[0]!.id === "classic");
    const it = variant("Lampa", "on");
    const seen = new Set<string>();
    for (const t of THEMES) seen.add(key("control", it, { theme: t.id }).s.svg);
    assert.equal(seen.size, THEMES.length, "every look draws its own key");
  });

  it("every look x every action x every state x every choice of information: valid SVG, our colours, escaped text", () => {
    const infos: Record<string, unknown>[] = [{}, Object.fromEntries(INFO_KEYS.map((k) => [k, k === "showIcon"]))];
    for (const k of INFO_KEYS) infos.push({ [k]: false });
    infos.push({ showGraph: true, showScale: true, showTarget: true, span: 3600 }, { nameFit: "wrap" }, { nameFit: "fit", label: "Light-Loznice-Main" }, { accent: "pink" });
    let n = 0;
    for (const t of THEMES) {
      for (const [kind, id] of KINDS) {
        for (const st of ["on", "off", "offline", "locked", "hold", "evil"]) {
          const item = variant(id, st);
          for (const info of infos) {
            const { s } = key(kind, item, { theme: t.id, label: st === "evil" ? EVIL : undefined, ...info });
            const where = `${t.id}/${kind}/${id}/${st}/${JSON.stringify(info)}`;
            wellFormed(s.svg);
            assert.match(s.svg, /width="144" height="144"/, where);
            assert.ok(!s.svg.includes("<script") && !s.svg.includes("‮"), where + ": server text unescaped");
            ownColours(s.svg, where);
            if (st === "offline" && kind !== "scene" && kind !== "status" && (info as { showState?: boolean }).showState !== false && !("showIcon" in info && Object.keys(info).length > 1)) {
              assert.match(s.svg, /Offline|OFFLINE/, where + ": offline is said");
            }
            if (st === "locked" && kind !== "status" && !(t.id === "classic" && kind === "reading")) assert.ok(s.svg.includes(LOCK), where + ": the lock badge");
            n++;
          }
        }
      }
    }
    assert.ok(n > 6000, "drawn " + n);
  });

  it("the hand shows whenever a hold applies - ZIGMon's or this key's own - in every look", () => {
    for (const t of THEMES) {
      for (const [kind, id] of KINDS) {
        if (kind === "reading" || kind === "status") continue;
        assert.ok(key(kind, variant(id, "hold"), { theme: t.id }).s.svg.includes(HAND), t.id + "/" + kind + ": ZIGMon's hold");
        assert.ok(key(kind, variant(id, "on"), { theme: t.id, hold: true }).s.svg.includes(HAND), t.id + "/" + kind + ": the key's own hold");
        if (id !== "Garage") assert.ok(!key(kind, variant(id, "on"), { theme: t.id }).s.svg.includes(HAND), t.id + "/" + kind + ": no hold, no hand");
      }
    }
  });

  it("on and off look different in every look", () => {
    for (const t of THEMES) {
      for (const [kind, id] of [["control", "Lampa"], ["dimmer", "zb:0xb2:light"], ["thermostat", "zb:0xc3:trv"], ["blinds", "zb:0xd4:cover"]] as const) {
        const it = variant(id, "on");
        const { v } = key(kind, it, { theme: t.id });
        const p = v.previewSet()!;
        assert.notEqual(p.on, p.off, t.id + "/" + kind);
        wellFormed(svgOf(p.on));
        wellFormed(svgOf(p.off));
        assert.equal(p.themes.length, THEMES.length);
      }
    }
  });

  it("Classic draws exactly what 1.0 drew for the settings 1.0 knew", () => {
    const want = JSON.parse(readFileSync(join(here, "..", "..", "test", "classic-golden.json"), "utf8")) as Record<string, string>;
    const got = goldenCases();
    assert.equal(got.length, Object.keys(want).length);
    let compared = 0;
    for (const c of got) {
      // a label was the Reading's alone in 1.0 (its inspector had no such field elsewhere)
      if (c.name.endsWith("/2") && !c.name.startsWith("reading/")) continue;
      assert.equal(c.hash, want[c.name], c.name);
      compared++;
    }
    assert.ok(compared > 450);
  });

  it("a hidden piece is not drawn, and an icon-only key shows the icon and nothing else", () => {
    const it = variant("Lampa", "on");
    for (const t of THEMES) {
      const named = key("control", it, { theme: t.id, label: "Distinct label" }).s.svg;
      assert.match(named, /Distinct label|Distinct|label/, t.id);
      const none = key("control", it, { theme: t.id, label: "Distinct label", showName: false }).s.svg;
      assert.ok(!none.includes("Distinct"), t.id + ": the name hidden");
      const iconOnly = key("control", it, { theme: t.id, label: "Distinct label", ...Object.fromEntries(INFO_KEYS.map((k) => [k, k === "showIcon"])) }).s.svg;
      assert.ok(!/Distinct|Obývák|42 W|>On</.test(iconOnly), t.id + ": icon only: " + iconOnly.slice(0, 200));
      assert.ok(iconOnly.includes("<g transform"), t.id + ": the icon is there");
    }
    const noRoom = key("control", it, { showRoom: false, showDetail: false }).s.svg;
    assert.ok(!noRoom.includes("Obývák") && !noRoom.includes("42 W"));
  });

  it("the accent is one of ours, by name", () => {
    for (const [name, a] of Object.entries(ACCENTS)) {
      assert.ok(key("control", variant("Lampa", "on"), { theme: "fill", accent: name }).s.svg.includes(a.colour), name);
      assert.ok(key("control", variant("Lampa", "on"), { accent: name }).s.svg.includes(a.colour), "classic " + name);
    }
    assert.ok(!key("control", variant("Lampa", "on"), { accent: "#123456" }).s.svg.includes("#123456"));
  });

  it("long names: shrunk or wrapped, not cut", () => {
    assert.deepEqual(smartWrap("Light-Loznice-Main", 16, 118, 650), ["Light-Loznice-", "Main"]);
    const f = nameLines("Light-Loznice-Main", "fit", 16, 118, 650, 2);
    assert.ok(f.lines.join("") === "Light-Loznice-Main", JSON.stringify(f));
    assert.deepEqual(nameLines("Light-Loznice-Main", "wrap", 16, 118, 650, 2).lines, ["Light-Loznice-", "Main"]);
    assert.ok(nameLines("Light-Loznice-Main", "cut", 16, 60, 650).lines[0]!.endsWith("…"));
    const it = parseItem({ ...sampleItems()[0]!, name: "Light-Loznice-Main", room: null });
    assert.match(key("control", it, { nameFit: "wrap" }).s.svg, />Light-Loznice-<\/text>.*>Main<\/text>/s);
    for (const t of THEMES.filter((x) => x.id !== "classic" && x.id !== "label")) {
      const svg = key("control", it, { theme: t.id }).s.svg;
      assert.ok(!/Light-Loznic…|Light-Lozn…/.test(svg), t.id + " cut the name");
    }
  });
});

const LOCK = ICONS.lock!;
const HAND = ICONS.hand!;

describe("settings 1.1", () => {
  it("keeps only known looks, accents by name, a clean short label, booleans and the spans", () => {
    const s = normalizeAction({
      theme: "neon", accent: "teal", nameFit: "wrap", label: "  Lamp\u0000 ‮ in   hall ", showName: false, showGraph: "false", span: 21600, hold: true, showScale: 1,
    });
    assert.deepEqual(s, { theme: "neon", accent: "teal", nameFit: "wrap", label: "Lamp in hall", showName: false, span: 21600, hold: true });
    assert.deepEqual(normalizeAction({ theme: "classic" }), {}, "classic is the default, not stored");
    assert.deepEqual(normalizeAction({ theme: "matrix", accent: "#FF0000", nameFit: "tiny", span: 1234, hold: "yes" }), {});
    assert.deepEqual(normalizeAction({ accent: "url(#x)" }), {});
    assert.equal(normalizeAction({ label: "x".repeat(200) }).label, "x".repeat(LABEL_MOST));
    assert.equal(normalizeAction({ label: "\u0007‏ " }).label, undefined);
    assert.equal(cleanLabel("😀".repeat(50)).length, LABEL_MOST * 2, "40 characters, not 40 UTF-16 units");
    assert.equal(normalizeAction({ press: "set:comfort" }).press, "set:comfort");
    assert.equal(normalizeAction({ press: "set:explode" }).press, undefined);
    assert.equal(normalizeAction({ press: "details" }).press, "details");
  });

  it("a label is escaped wherever it is drawn", () => {
    for (const t of THEMES) {
      for (const [kind, id] of KINDS) {
        const svg = key(kind, variant(id, "on"), { theme: t.id, label: '<b onload="x">&amp;' }).s.svg;
        wellFormed(svg);
        assert.ok(!svg.includes("<b ") && !svg.includes('onload="x"'), t.id + "/" + kind);
      }
    }
  });
});

describe("hold to confirm on this key", () => {
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  it("a short press does nothing and says so; a 1.5 s hold acts, with the time held", async () => {
    const sent: Sent[] = [];
    const { v, s } = key("control", variant("Lampa", "on"), { hold: true }, sent);
    v.keyDown();
    await sleep(200);
    v.keyUp();
    await sleep(50);
    assert.deepEqual(sent, [], "nothing sent on a short press");
    assert.match(s.svg, /Hold to confirm/);
    v.keyDown();
    await sleep(700);
    assert.match(s.svg, /Keep holding/, "the ring fills");
    await sleep(1000);
    v.keyUp();
    await sleep(50);
    const got = sent as Sent[];
    assert.equal(got.length, 1);
    assert.equal(got[0]!.action, "toggle");
    assert.ok((got[0]!.held_ms ?? 0) >= 1500);
  });

  it("without the switch a press acts at once; ZIGMon's hold cannot be switched off here", async () => {
    const sent: Sent[] = [];
    const a = key("control", variant("Lampa", "on"), {}, sent);
    a.v.keyDown();
    a.v.keyUp();
    await sleep(30);
    assert.equal(sent.length, 1);
    const b = key("control", variant("Lampa", "hold"), { hold: false }, sent);
    assert.ok(b.v.needsHold(variant("Lampa", "hold")));
    b.v.keyDown();
    await sleep(150);
    b.v.keyUp();
    await sleep(30);
    assert.equal(sent.length, 1, "a short press on an item ZIGMon holds does nothing");
  });

  it("a dial's push and touch hold too; a reading has no hold", async () => {
    const sent: Sent[] = [];
    const s = new MockSurface("Encoder", "D");
    const v = new ActionView("dimmer", stubHub([variant("zb:0xb2:light", "on")], sent), s, { item: "zb:0xb2:light", hold: true });
    cleanups.push(() => v.dispose());
    v.touch(false);
    v.dialDown();
    await sleep(100);
    v.dialUp();
    await sleep(30);
    assert.deepEqual(sent, []);
    assert.equal(new ActionView("reading", stubHub([variant("read:0xe5:temperature", "on")]), new MockSurface("Keypad", "D"), { item: "read:0xe5:temperature", hold: true })
      .needsHold(variant("read:0xe5:temperature", "on")), false);
  });
});

/** A heated room's key, as a ZIGMon newer than 5.59.0 describes it. */
function roomItem(attrs: Record<string, unknown>): Item {
  return parseItem({
    id: "heat:room:r2", name: "Heating in Loznice", room: "Loznice", kind: "thermostat", icon: "heat", cap: "climate", actions: ["set", "toggle", "on", "off"],
    allowed: true, hold: false,
    attrs: [
      { key: "mode", label: "Mode", type: "enum", values: ["plan", "comfort", "eco", "night", "max", "off", "manual"] },
      { key: "target", label: "Wanted temperature", type: "number", unit: "°C", min: 5, max: 30, step: 0.5, via: "heat:temp:r2" },
    ],
    state: {
      on: true, value: null, value_text: "max",
      attrs: { mode: "max", level: "max", calling: true, temperature: 24.6, target: 35, why: "max", by_hand: false, hold_until: null, thermometer: "Temp-Loznice", ...attrs },
    },
  });
}

describe("a heated room", () => {
  it("shows its target and its mode in the dashboard's words (1.0 drew → —)", () => {
    for (const t of THEMES) {
      const svg = key("thermostat", roomItem({}), { theme: t.id }).s.svg;
      assert.match(svg, /35\.0/, t.id + ": the target");
      assert.match(svg, /Max/, t.id + ": the mode");
      assert.ok(!svg.includes("→ —"), t.id);
    }
    const until = Math.floor(Date.now() / 1000) + 3600;
    const svg = key("thermostat", roomItem({ by_hand: true, hold_until: until, why: "by hand", target: 22.5 }), {}).s.svg;
    assert.ok(svg.includes("By hand until " + clockOf(until)), svg);
  });

  it("a press sets one mode, or goes round all of them, Plan and By hand included; the dial sets it by hand", async () => {
    const sent: Sent[] = [];
    key("thermostat", roomItem({}), { press: "set:comfort" }, sent).v.keyDown();
    const cyc = key("thermostat", roomItem({ mode: "off" }), { press: "mode" }, sent);
    cyc.v.keyDown();
    const dial = new ActionView("thermostat", stubHub([roomItem({ target: 22 })], sent), new MockSurface("Encoder", "D"), { item: "heat:room:r2" });
    cleanups.push(() => dial.dispose());
    dial.rotate(-2);
    await until(() => sent.length >= 3, 2000, "three commands");
    assert.deepEqual(sent[0], { deck: "D", id: "heat:room:r2", action: "set", attr: "mode", value: "comfort" });
    assert.deepEqual(sent[1], { deck: "D", id: "heat:room:r2", action: "set", attr: "mode", value: "manual" }, "after Off comes By hand");
    assert.equal(sent[2]!.attr, "target");
    assert.equal(sent[2]!.delta, -1);
  });

  it("a press can show the details for a moment instead", async () => {
    const sent: Sent[] = [];
    const k = key("thermostat", roomItem({}), { press: "details" }, sent);
    k.v.keyDown();
    k.v.keyUp();
    for (const w of ["Max", "35.0 °C", "24.6 °C", "Temp-Loznice", "THERMOMETER"]) assert.ok(k.s.svg.includes(w), w);
    assert.deepEqual(sent, []);
    const d = new MockSurface("Encoder", "D");
    const dv = new ActionView("thermostat", stubHub([roomItem({})]), d, { item: "heat:room:r2", press: "details" });
    cleanups.push(() => dv.dispose());
    dv.dialDown();
    assert.equal((d.feedbacks.at(-1)!.value as { value: string }).value, "Max");
  });
});

describe("graphs from ZIGMon's history", () => {
  it("the state answer carries the series, cleaned", () => {
    const a = parseStateAnswer({
      ok: true, boot: 1, seq: 2, items: {},
      history: { "read:x:t": { span: 86400, points: [[1, 2], [3, "x"], [2, 5], [4, Infinity], [5, 6], [0, 9]] }, "bad id\n": { span: 1, points: [] }, n: { span: -1, points: [] } },
    });
    assert.deepEqual(a.history.get("read:x:t"), { span: 86400, points: [[1, 2], [2, 5], [5, 6]] }, "numbers only, oldest first");
    assert.equal(a.history.size, 1);
  });

  it("a reading draws ZIGMon's series at once, on the key and on the strip, and asks again for another span", async () => {
    const fake = new FakeZigmon();
    fake.autoApprove = true;
    await fake.start(20325);
    cleanups.push(() => fake.stop());
    const hub = new RealHub({
      store: new MemoryStore(), protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => [{ id: "XL-1", type: 2, name: "XL", cols: 8, rows: 4 }],
      computer: () => "PC", minBackoffMs: 50, maxBackoffMs: 200,
    });
    cleanups.push(() => hub.stop());
    await hub.start();
    const s = new MockSurface("Keypad", "XL-1");
    const v = new ActionView("reading", hub, s, { item: "read:0xe5:temperature" });
    hub.watch(v);
    const d = new MockSurface("Encoder", "XL-1");
    const dv = new ActionView("thermostat", hub, d, { item: "zb:0xc3:trv", showGraph: true, theme: "glass" });
    hub.watch(dv);
    cleanups.push(() => { v.dispose(); dv.dispose(); });
    await hub.connect("http://localhost:" + fake.port);
    await until(() => (hub.series("read:0xe5:temperature", 86400)?.length ?? 0) >= 40, 5000, "the series");
    const ask = fake.historyAsks.find((a) => a.ids.includes("read:0xe5:temperature"))!;
    assert.equal(ask.span, 86400);
    assert.equal(ask.points, 48);
    await until(() => (s.svg.match(/ L /g)?.length ?? 0) >= 40, 3000, "a line of 48 points on the key");
    await until(() => {
      const art = d.feedbacks.at(-1)?.art;
      return typeof art === "string" && (svgOf(art).match(/ L /g)?.length ?? 0) >= 40;
    }, 3000, "the graph on the strip");
    // another span: asked again
    v.setSettings({ item: "read:0xe5:temperature", span: 3600 });
    await until(() => fake.historyAsks.some((a) => a.span === 3600), 3000, "asked for an hour");
    await until(() => (hub.series("read:0xe5:temperature", 3600)?.length ?? 0) >= 40, 3000, "the hour's series");
  });

  it("an older ZIGMon sends none: the key keeps its own few values", async () => {
    const fake = new FakeZigmon();
    fake.autoApprove = true;
    fake.withHistory = false;
    await fake.start(20326);
    cleanups.push(() => fake.stop());
    const hub = new RealHub({
      store: new MemoryStore(), protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => [{ id: "XL-1", type: 2, name: "XL", cols: 8, rows: 4 }],
      computer: () => "PC", minBackoffMs: 50, maxBackoffMs: 200,
    });
    cleanups.push(() => hub.stop());
    await hub.start();
    const v = new ActionView("reading", hub, new MockSurface("Keypad", "XL-1"), { item: "read:0xe5:temperature" });
    hub.watch(v);
    cleanups.push(() => v.dispose());
    await hub.connect("http://localhost:" + fake.port);
    await until(() => hub.currentPhase === "online", 5000, "online");
    await until(() => fake.seen.some((x) => x.do === "state" && x.method === "POST"), 3000, "asked");
    assert.equal(hub.series("read:0xe5:temperature", 86400), null);
  });
});

describe("the touch strip in every look", () => {
  it("only the layout's keys, our colours, valid pictures - and Classic puts the colours back", () => {
    for (const t of THEMES) {
      for (const [kind, id] of KINDS) {
        for (const st of ["on", "off", "offline", "locked"]) {
          const s = new MockSurface("Encoder", "D");
          const v = new ActionView(kind, stubHub([variant(id, st)]), s, { item: id, theme: t.id, accent: "teal", showName: st !== "off" });
          v.draw(true);
          const fb = s.feedbacks.at(-1)!;
          const layout = LAYOUTS[kind === "scene" || kind === "status" ? "control" : kind]!;
          const keys = new Set(layout.items.map((x) => x.key));
          for (const [name, val] of Object.entries(fb)) {
            assert.ok(keys.has(name), t.id + "/" + kind + ": " + name);
            const o = typeof val === "object" && val !== null ? (val as { value?: unknown; color?: string }) : { value: val };
            if (o.color) assert.ok(ALLOWED_COLOURS.has(o.color.toUpperCase()), t.id + "/" + kind + ": colour " + o.color);
            if (typeof o.value === "string" && o.value.startsWith("data:image/svg+xml")) {
              const svg = svgOf(o.value);
              wellFormed(svg);
              ownColours(svg, t.id + "/" + kind + "/" + name);
            }
          }
          if (t.id !== "classic") {
            v.setSettings({ item: id });
            const back = s.feedbacks.at(-1)!;
            assert.equal(typeof back.bg, "string", t.id + "/" + kind + ": the paper taken away");
          }
          v.dispose();
        }
      }
    }
  });
});
