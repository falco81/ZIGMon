/**
 * 1.3 (ZIGMon 5.59.4): Computed (PROTOCOL-CALC.md) - the calc block parsed strictly, which items fit,
 * the builder's What / How / Where mapped onto items that exist and the impossible ones disabled,
 * Popular, a computed value drawn exactly as the Reading it is (Classic, the looks, the strip), and
 * the key and catalogue of a ZIGMon that does not compute.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import {
  builderView, CALC_MOST, CALC_PRESETS, calcEntries, calcFacts, calcId, calcLook, choiceOf, fnFits, fnWord, NO_CHOICE, parseCalc, parseCalcId, parseScope, pick,
  presetId, resolveChoice, scopeText, type CalcChoice,
} from "../src/core/calc.js";
import { Hub as RealHub, type Hub } from "../src/core/hub.js";
import { NodeTransport } from "../src/core/http.js";
import { hasIcon } from "../src/core/icons.js";
import { parseCatalog, parseHello, parseItem, type Item } from "../src/core/protocol.js";
import { catalogMessage } from "../src/core/piapi.js";
import { FakeProtector } from "../src/core/secrets.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, fits, type ActionKind } from "../src/core/views.js";
import { calcItems, extendedItems, FakeZigmon, MemoryStore, MockSurface, sampleItems, until, type FakeItem } from "./fake-zigmon.js";
import { wellFormed } from "./xml.js";

const EVIL = '<script>alert(1)</script> & "q" \'s\' ‮]]>';
const cleanups: (() => unknown)[] = [];
after(async () => {
  for (const c of cleanups.reverse()) await c();
});

const raw = (): FakeItem[] => [...sampleItems(), ...extendedItems(), ...calcItems()];
const all = (): Item[] => raw().map((r) => parseItem(r));
const calcOf = (id: string) => calcItems().find((i) => i.id === id)!;

function stubHub(items: Item[], features = ["extended", "timer", "calc"]): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [380, 420, 400, 395, 412.5],
    series: () => null, supports: (f: string) => features.includes(f),
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
    allItems: () => [...map.values()], allRooms: () => [],
    command: async () => ({ ok: true, said: "", state: null }),
  } as unknown as Hub;
}

function view(kind: ActionKind, items: Item[], settings: Record<string, unknown>, features?: string[], ctl: "Keypad" | "Encoder" = "Keypad") {
  const s = new MockSurface(ctl, "D");
  const v = new ActionView(kind, stubHub(items, features), s, settings);
  v.draw(true);
  cleanups.push(() => v.dispose());
  return { v, s };
}

const texts = (svg: string) => [...svg.matchAll(/<text\b[^>]*>(.*?)<\/text>/gs)].map((m) => m[1]!.replace(/<[^>]+>/g, ""));

/** A Reading item with the same name, value and unit as a computed one (its key word "power", so the same bolt). */
function twin(c: FakeItem): FakeItem {
  return { ...c, id: "read:twin:power", kind: "reading", calc: undefined, attrs: [{ ...(c.attrs[0] as object), key: "power" }] };
}

// ------------------------------------------------------------------ parsing

describe("Computed: the protocol", () => {
  it("ids and scopes, strictly", () => {
    assert.deepEqual(parseCalcId("calc:sum:power:all"), { fn: "sum", metric: "power", scope: { place: "all", kind: null, room: null } });
    assert.deepEqual(parseCalcId("calc:avg:temperature:room=r2,kind=thermostat")?.scope, { place: "all", kind: "thermostat", room: "r2" });
    assert.deepEqual(parseScope("kind=light"), { place: "all", kind: "light", room: null });
    assert.deepEqual(parseScope("outside"), { place: "outside", kind: null, room: null });
    for (const bad of ["calc:sum:power", "calc:sum:power:", "calc:total:power:all", "calc:sum:watts:all", "calc:sum:power:kind=lamp", "calc:sum:power:room=",
      "calc:sum:power:room=a b", "calc:sum:power:room=r1,kind=", "calc:sum:power:kind=light,room=r1", "calc:on:temperature:all", "calc:avg:state:all",
      "calc:off:open:all", "calc:sum:power:all ", "read:sum:power:all", "calc:sum:power:room=" + "x".repeat(61), 7, null]) {
      assert.equal(parseCalcId(bad), null, String(bad));
    }
    for (const s of ["all", "inside", "outside", "kind=socket", "room=r1", "room=r1,kind=light"]) assert.equal(scopeText(parseScope(s)!), s);
    assert.equal(calcId("pct_on", "state", { place: "all", kind: "light", room: "r9" }), "calc:pct_on:state:room=r9,kind=light");
    assert.ok(fnFits("on", "state") && fnFits("count", "open") && fnFits("off", "online") && fnFits("spread", "temperature"));
    assert.ok(!fnFits("pct_on", "open") && !fnFits("avg", "online") && !fnFits("on", "power"));
    // the server side's two: the rooms' temperatures (extremes, mean, spread) and low batteries (on, % on)
    assert.ok(fnFits("min", "room_temperature") && fnFits("spread", "room_temperature") && !fnFits("sum", "room_temperature") && !fnFits("count", "room_temperature"));
    assert.ok(fnFits("on", "battery_low") && fnFits("pct_on", "battery_low") && !fnFits("off", "battery_low") && !fnFits("min", "battery_low"));
    assert.equal(parseCalcId("calc:on:room_temperature:inside"), null);
    assert.equal(parseCalcId("calc:avg:battery_low:all"), null);
    assert.deepEqual(parseCalcId("calc:min:room_temperature:inside")?.scope, { place: "inside", kind: null, room: null });
  });

  it("the calc block: as the contract has it, agreeing with the id, members and unit capped; else none", () => {
    const it = parseItem(calcOf("calc:sum:power:all"));
    assert.equal(it.kind, "calc");
    assert.deepEqual(it.calc, { fn: "sum", metric: "power", scope: "all", members: 9, unit: "W" });
    assert.deepEqual(it.attrs[0], { key: "value", label: "Power", type: "number", unit: "W", min: 0, max: null, step: null, values: [] });
    // a count's unit is null in the server's shape: none, and 0..members
    const lit = parseItem(calcOf("calc:on:state:kind=light"));
    assert.deepEqual([lit.calc!.unit, lit.attrs[0]!.unit, lit.attrs[0]!.min, lit.attrs[0]!.max], ["", "", 0, 4]);
    // min_of / max_of null unless an extreme; both for a spread
    assert.equal(it.state.attrs.min_of, null);
    const sp = parseItem(calcOf("calc:spread:room_temperature:inside")).state.attrs;
    assert.deepEqual([sp.min_of, sp.max_of], ["Ložnice", "Obývák"]);
    assert.equal(it.state.value, 412.5);
    assert.equal(it.state.attrs.known, 8);
    const base = calcOf("calc:min:temperature:inside");
    const block = (c: Record<string, unknown>, id = base.id) => parseItem({ ...base, id, calc: { ...base.calc, ...c } }).calc;
    assert.equal(block({ fn: "max" }), undefined, "not the id's function");
    assert.equal(block({ metric: "humidity" }), undefined, "not the id's metric");
    assert.equal(block({ scope: "all" }), undefined, "not the id's scope");
    assert.equal(block({ scope: "<x>" }), undefined);
    assert.equal(block({ fn: 3 }), undefined);
    assert.equal(parseItem({ ...base, calc: "sum" }).calc, undefined);
    assert.equal(parseItem({ ...base, calc: null }).calc, undefined);
    assert.equal(parseItem({ ...base, kind: "reading" }).calc, undefined, "only an item of kind calc");
    assert.equal(block({}, "calc:min:temperature:everywhere"), undefined);
    assert.equal(block({ members: -3 })!.members, 0);
    assert.equal(block({ members: 1.5 })!.members, 0);
    assert.equal(block({ members: 9e9 })!.members, 100_000);
    assert.equal(block({ unit: "°C‮\u0000 and far too long" })!.unit, "°C and f");
    // the extremes by name: cleaned and at most 60
    const st = parseItem({ ...base, state: { ...base.state, attrs: { min_of: EVIL + "x".repeat(80), known: 4 } } }).state;
    assert.ok([...(st.attrs.min_of as string)].length <= 60 && !/[‮]/.test(st.attrs.min_of as string));
  });

  it("hello's \"calc\"; at most CALC_MOST computed values from a catalogue, the rest kept", () => {
    const h = parseHello({ ok: true, api: 1, server: "zigmon", version: "5.59.4", house: "H", boot: 1, seq: 1, install: { id: "0123456789abcdef0123456789abcdef", name: "PC", caps: {} }, decks: [], features: ["extended", "calc"] });
    assert.deepEqual(h.features, ["extended", "calc"]);
    const many = Array.from({ length: CALC_MOST + 50 }, (_, k) => ({ ...calcOf("calc:sum:power:room=r1"), id: `calc:sum:power:room=r${k}`, calc: { fn: "sum", metric: "power", scope: `room=r${k}`, members: 1, unit: "W" } }));
    const cat = parseCatalog({ ok: true, boot: 1, seq: 1, rooms: [], items: [...many, ...sampleItems()] });
    assert.equal(cat.items.filter((i) => i.kind === "calc").length, CALC_MOST);
    assert.equal(cat.items.filter((i) => i.kind !== "calc").length, sampleItems().length);
  });
});

// ------------------------------------------------------------------ fits

describe("Computed: which items fit", () => {
  it("a computed value is Computed's alone; Computed takes nothing else", () => {
    const items = all();
    const calc = items.filter((i) => i.kind === "calc");
    assert.equal(calc.length, calcItems().length);
    for (const i of items) {
      assert.equal(fits("computed", i), i.kind === "calc", i.id);
      if (i.kind === "calc") for (const k of ["reading", "control", "thermostat", "scene", "status", "power", "timer"] as ActionKind[]) assert.ok(!fits(k, i), k + " " + i.id);
    }
    // a calc item whose block did not parse is no one's
    assert.ok(!fits("computed", parseItem({ ...calcOf("calc:sum:power:all"), calc: { fn: "avg", metric: "power", scope: "all" } })));
    // the inspector gets them with their block, and nothing else
    const m = catalogMessage(stubHub(items), "computed");
    const sent = m.items as { id: string; calc?: { fn: string } }[];
    assert.equal(sent.length, calc.length);
    assert.ok(sent.every((x) => x.id.startsWith("calc:") && x.calc && x.calc.fn));
    assert.ok(!(catalogMessage(stubHub(items), "reading").items as { id: string }[]).some((x) => x.id.startsWith("calc:")));
  });
});

// ------------------------------------------------------------------ the builder

describe("Computed: the builder", () => {
  const entries = calcEntries(all());
  const idOf = (c: CalcChoice) => resolveChoice(entries, c)?.id ?? null;

  it("What, then How, then Where: always an item that exists, the nearest to what was there", () => {
    let c = pick(entries, NO_CHOICE, { metric: "power" });
    assert.equal(idOf(c), "calc:sum:power:all", "the metric's usual function, of the whole house");
    c = pick(entries, c, { kind: "light" });
    assert.equal(idOf(c), "calc:sum:power:kind=light");
    c = pick(entries, c, { room: "r1" });
    assert.equal(idOf(c), "calc:sum:power:room=r1,kind=light", "the kind kept");
    c = pick(entries, c, { kind: "socket" });
    assert.equal(idOf(c), "calc:sum:power:kind=socket", "no sockets in Obývák computed: the room goes, the kind stays");
    c = pick(entries, c, { kind: null });
    assert.equal(idOf(c), "calc:sum:power:all");
    c = pick(entries, c, { room: "r3" });
    assert.equal(idOf(c), "calc:sum:power:room=r3");
    c = pick(entries, c, { fn: "avg" });
    assert.equal(idOf(c), "calc:avg:power:kind=socket", "the only average of power there is");
    c = pick(entries, c, { metric: "temperature" });
    assert.equal(idOf(c), "calc:avg:temperature:all", "average kept; sockets have no temperature, so the whole house");
    c = pick(entries, c, { place: "inside" });
    assert.equal(idOf(c), "calc:avg:temperature:inside");
    c = pick(entries, c, { fn: "min" });
    assert.equal(idOf(c), "calc:min:temperature:inside", "inside kept");
    c = pick(entries, c, { fn: "spread" });
    assert.equal(idOf(c), "calc:spread:temperature:inside");
    c = pick(entries, c, { metric: "state" });
    assert.equal(idOf(c), "calc:on:state:kind=light", "On / off: how many are on");
    c = pick(entries, c, { fn: "pct_on" });
    assert.equal(idOf(c), "calc:pct_on:state:kind=light");
    c = pick(entries, c, { metric: "online" });
    assert.equal(idOf(c), "calc:off:online:all");
    // every item there is can be reached, and choiceOf maps back to its id
    for (const e of entries) assert.equal(idOf(choiceOf(e)), e.id);
  });

  it("impossible choices are disabled, and picking one changes nothing", () => {
    let c = pick(entries, NO_CHOICE, { metric: "temperature" });
    let v = builderView(entries, c);
    const on = <T>(xs: { id: T; enabled: boolean }[]) => xs.filter((x) => x.enabled).map((x) => x.id);
    const off = <T>(xs: { id: T; enabled: boolean }[]) => xs.filter((x) => !x.enabled).map((x) => x.id);
    assert.deepEqual(off(v.metrics), ["pressure", "illuminance"], "nothing reports them here");
    assert.deepEqual(v.fns.map((f) => f.id), ["sum", "avg", "min", "max", "count", "spread"], "no on / off / % on of a temperature");
    assert.deepEqual(on(v.fns), ["avg", "min", "max", "spread"]);
    assert.deepEqual(on(v.places), ["all", "inside", "outside"]);
    assert.deepEqual(on(v.kinds), [null]);
    assert.deepEqual(on(v.rooms), [null, "r2"]);
    c = pick(entries, c, { fn: "min" });
    v = builderView(entries, c);
    assert.deepEqual(on(v.places), ["all", "inside"], "no coldest outside: one thermometer");
    assert.deepEqual(pick(entries, c, { place: "outside" }), c);
    assert.deepEqual(pick(entries, c, { fn: "sum" }), c, "no sum of temperatures");
    assert.deepEqual(pick(entries, c, { metric: "pressure" }), c);
    v = builderView(entries, pick(entries, NO_CHOICE, { metric: "power" }));
    assert.deepEqual(on(v.kinds), [null, "light", "socket"]);
    assert.deepEqual(v.rooms.map((r) => [r.id, r.name, r.enabled]), [[null, "Any room", true], ["r3", "Kitchen", true], ["r2", "Ložnice", false], ["r1", "Obývák", true]]);
    v = builderView(entries, pick(entries, NO_CHOICE, { metric: "state" }));
    assert.deepEqual(v.fns.map((f) => f.id), ["count", "on", "off", "pct_on"]);
    assert.deepEqual(builderView(entries, pick(entries, NO_CHOICE, { metric: "open" })).fns.map((f) => f.id), ["count", "on"]);
    assert.equal(v.item?.id, "calc:on:state:kind=light");
    // the rooms' temperatures: inside only; low batteries: Low and % low
    v = builderView(entries, pick(entries, NO_CHOICE, { metric: "room_temperature" }));
    assert.equal(v.item?.id, "calc:min:room_temperature:inside");
    assert.deepEqual(v.fns.map((f) => [f.id, f.enabled]), [["avg", true], ["min", true], ["max", true], ["spread", true]]);
    assert.deepEqual(on(v.places), ["inside"]);
    v = builderView(entries, pick(entries, NO_CHOICE, { metric: "battery_low" }));
    assert.equal(v.item?.id, "calc:on:battery_low:all");
    assert.deepEqual(v.fns.map((f) => fnWord(f.id, "battery_low")), ["Low", "% low"]);
    // nothing chosen yet: no item, every metric there is offered
    assert.equal(builderView(entries, NO_CHOICE).item, null);
    assert.equal(builderView([], NO_CHOICE).metrics.filter((m) => m.enabled).length, 0);
  });

  it("only what the catalogue has: no item is made up", () => {
    const few = calcEntries(all().filter((i) => i.id === "calc:avg:temperature:room=r2" || i.id === "calc:on:open:all"));
    const c = pick(few, NO_CHOICE, { metric: "temperature" });
    assert.equal(resolveChoice(few, c)?.id, "calc:avg:temperature:room=r2", "the room's average, there being no other");
    assert.equal(resolveChoice(few, pick(few, NO_CHOICE, { metric: "power" })), null);
    // an item without its block, or an id that is not a computed one, is not offered
    assert.equal(calcEntries([{ id: "calc:sum:power:all", name: "x", room: null }]).length, 0);
    assert.equal(calcEntries([{ id: "Lampa", name: "x", room: null, calc: {} }]).length, 0);
  });

  it("Popular: the ten, each one click to an item there is", () => {
    const got = Object.fromEntries(CALC_PRESETS.map((p) => [p.key, presetId(entries, p)]));
    assert.deepEqual(got, {
      power: "calc:sum:power:all", lights_w: "calc:sum:power:kind=light", sockets_w: "calc:sum:power:kind=socket", lights_on: "calc:on:state:kind=light",
      temp_in: "calc:avg:temperature:inside", coldest: "calc:min:room_temperature:inside", open: "calc:on:open:all", offline: "calc:off:online:all",
      battery: "calc:on:battery_low:all", energy: "calc:sum:energy_today:all",
    });
    for (const p of CALC_PRESETS) assert.ok(hasIcon(p.icon), p.icon);
    // a house with no inside: the coldest of all; none at all: nothing to click
    const noRooms = entries.filter((e) => e.metric !== "room_temperature");
    assert.equal(presetId(noRooms, CALC_PRESETS.find((p) => p.key === "coldest")!), "calc:min:temperature:inside");
    const noInside = entries.filter((e) => e.scope.place !== "inside");
    assert.equal(presetId(noInside, CALC_PRESETS.find((p) => p.key === "coldest")!), "calc:min:temperature:all");
    assert.equal(presetId([], CALC_PRESETS[0]!), null);
  });

  it("Now: the value, what over what, how many had one, the extreme by name", () => {
    const it = all().find((i) => i.id === "calc:min:temperature:inside")!;
    assert.deepEqual(calcFacts(it, it.state), [["Now", "18.5 °C"], ["Computes", "Min · Temperature"], ["Over", "Inside"], ["Members", "4"], ["Lowest", "Ložnice"]]);
    const p = all().find((i) => i.id === "calc:sum:power:all")!;
    assert.deepEqual(calcFacts(p, p.state)[3], ["Members", "8 of 9 with a value"]);
    const r = all().find((i) => i.id === "calc:sum:power:room=r1,kind=light")!;
    assert.equal(calcFacts(r, r.state)[2]![1], "Lights · Obývák");
    assert.deepEqual(view("computed", all(), { item: "calc:off:online:all" }).v.facts()![1], ["Computes", "Offline · Online"]);
  });
});

// ------------------------------------------------------------------ drawn as a Reading

describe("Computed: drawn as the Reading it is", () => {
  it("Classic and every look: the very key a Reading of the same value draws", () => {
    const c = calcOf("calc:sum:power:all");
    const items = [...all(), parseItem(twin(c))];
    for (const s of [{}, { theme: "classic", decimals: 0 }, { warnAbove: 300, critAbove: 400 }, { showGraph: false }, { label: "Dům" }, { span: 3600, showScale: true }]) {
      for (const t of THEMES) {
        const settings = { ...s, ...(t.id === "classic" ? {} : { theme: t.id }) };
        const a = view("computed", items, { ...settings, item: c.id }).s.svg;
        const b = view("reading", items, { ...settings, item: "read:twin:power" }).s.svg;
        assert.equal(a, b, t.id + " " + JSON.stringify(s));
        wellFormed(a);
      }
    }
    // and the dial's strip
    const fa = view("computed", items, { item: c.id }, undefined, "Encoder").s.feedbacks.at(-1);
    const fb = view("reading", items, { item: "read:twin:power" }, undefined, "Encoder").s.feedbacks.at(-1);
    assert.deepEqual(fa, fb);
  });

  it("the value with its unit, the name, the trend, the thresholds and decimals", () => {
    const t = texts(view("computed", all(), { item: "calc:sum:power:all" }).s.svg).join(" ");
    assert.match(t, /Power ·/, "the name, cut to fit beside the trend as a Reading's");
    assert.match(t, /412\.5\s*W/);
    assert.match(texts(view("computed", all(), { item: "calc:sum:power:all", decimals: 0 }).s.svg).join(" "), /413\s*W/);
    // the thresholds, on the average inside (21.3 °C)
    const T = "calc:avg:temperature:inside";
    const red = view("computed", all(), { item: T, critAbove: 21 }).v.readingModel();
    const amber = view("computed", all(), { item: T, warnAbove: 21, critAbove: 30 }).v.readingModel();
    const blue = view("computed", all(), { item: T, warnBelow: 22, critBelow: 15 }).v.readingModel();
    const calm = view("computed", all(), { item: T, warnAbove: 30 }).v.readingModel();
    assert.equal(calm.colour, calm.accent);
    assert.notEqual(red.colour, calm.colour);
    assert.notEqual(amber.colour, calm.colour);
    assert.notEqual(red.colour, amber.colour);
    assert.equal(blue.colour, amber.colour);
    // 21.3 °C after a history in the hundreds falls; 380 → 412.5 W is steady on a graph from 0
    assert.equal(view("computed", all(), { item: "calc:sum:power:all" }).v.readingModel().trend, "flat");
    assert.equal(view("computed", all(), { item: "calc:avg:temperature:inside" }).v.readingModel().trend, "down");
    // the honest scale: the calc attr's min / max (from 0 for power, 0..members for a count, 0..100 for a %), none where null
    const pw = view("computed", all(), { item: "calc:sum:power:all" }).v.readingModel();
    assert.deepEqual([pw.scale?.min, pw.scale?.max, pw.level], [0, null, null]);
    const cnt = view("computed", all(), { item: "calc:on:state:kind=light" }).v.readingModel();
    assert.deepEqual([cnt.scale?.min, cnt.scale?.max, cnt.level], [0, 4, 0.75]);
    const lq = view("computed", all(), { item: "calc:min:linkquality:all" }).v.readingModel();
    assert.deepEqual([lq.scale?.min, lq.scale?.max], [0, 255]);
    const pct = view("computed", all(), { item: "calc:pct_on:state:kind=light" }).v.readingModel();
    assert.deepEqual([pct.scale?.min, pct.scale?.max, pct.level], [0, 100, 0.75]);
    const avg = view("computed", all(), { item: "calc:avg:temperature:inside" }).v.readingModel();
    assert.deepEqual([avg.scale?.min ?? null, avg.scale?.max ?? null, avg.level], [null, null, null]);
    // a count has no unit; a temperature is drawn with its thermometer, in its colour
    const lights = view("computed", all(), { item: "calc:on:state:kind=light" }).v.readingModel();
    assert.deepEqual([lights.value, lights.unit], ["3", ""]);
    const cold = view("computed", all(), { item: "calc:min:temperature:inside" }).v.readingModel();
    assert.deepEqual([cold.icon, cold.accent, cold.unit], ["thermo", calcLook({ fn: "min", metric: "temperature" }).accent, "°C"]);
    // nothing known: as a Reading with no value
    const none = all().map((i) => (i.id === "calc:avg:humidity:inside" ? { ...i, state: { ...i.state, value: null, valueText: "", online: false } } : i));
    assert.equal(view("computed", none, { item: "calc:avg:humidity:inside" }).v.readingModel().online, false);
    // a Computed key only shows: a press asks again, nothing is sent
    assert.deepEqual(view("computed", all(), { item: "calc:sum:power:all" }, undefined, "Encoder").s.triggers.at(-1), { push: "Refresh", touch: "Refresh" });
    // the graph is asked for, over the span chosen
    assert.deepEqual(view("computed", all(), { item: "calc:sum:power:all", span: 3600 }).v.series(), [{ id: "calc:sum:power:all", span: 3600 }]);
  });

  it("a sample of looks: well formed, the name and value in every one, nothing of the server's text unescaped", () => {
    const evil = raw().map((r) => (r.id === "calc:max:co2:inside" ? { ...r, name: EVIL, state: { ...r.state, value_text: EVIL } } : r)).map((r) => parseItem(r));
    for (const t of THEMES.filter((_, k) => k % 3 === 0)) {
      const svg = view("computed", all(), { item: "calc:avg:temperature:inside", theme: t.id }).s.svg;
      wellFormed(svg);
      const words = texts(svg).join(" ");
      assert.match(words, /21\.3/, t.id);
      const e = view("computed", evil, { item: "calc:max:co2:inside", theme: t.id }).s.svg;
      wellFormed(e);
      assert.ok(!e.includes("<script"), t.id);
    }
  });
});

// ------------------------------------------------------------------ a ZIGMon that does not compute

describe("Computed: a ZIGMon before 5.59.4, or one that does not compute", () => {
  it("the key and the strip say it needs 5.59.4; the preview and Now have nothing", () => {
    for (const f of [[], ["extended", "timer"]]) {
      const { v, s } = view("computed", all(), { item: "calc:sum:power:all" }, f);
      assert.match(texts(s.svg).join(" "), /Needs ZIGMon.*5\.59\.4/, JSON.stringify(f));
      assert.equal(v.previewSet(), null);
      assert.equal(v.facts(), null);
      assert.match(JSON.stringify(view("computed", all(), { item: "calc:sum:power:all" }, f, "Encoder").s.feedbacks.at(-1)), /5\.59\.4/);
    }
    assert.doesNotMatch(view("computed", all(), { item: "calc:sum:power:all" }).s.svg, /5\.59\.4/);
    assert.match(texts(view("computed", all(), {}).s.svg).join(" "), /Pick a value/);
    assert.match(texts(view("computed", all(), { item: "calc:sum:power:room=r2" }).s.svg).join(" "), /Not found/);
    // a Reading does not care
    assert.doesNotMatch(view("reading", all(), { item: "read:0xe5:temperature" }, []).s.svg, /5\.59\.4/);
  });

  it("end to end: computed values only from a ZIGMon whose hello says calc, with their graph", async () => {
    const connect = async (features: string[]) => {
      const fake = new FakeZigmon();
      fake.features = features;
      fake.autoApprove = true;
      fake.waitMs = 200;
      await fake.start(0);
      const hub = new RealHub({
        store: new MemoryStore(), protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => [{ id: "D1", type: 7, name: "+", cols: 4, rows: 2 }],
        computer: () => "PC", minBackoffMs: 50, maxBackoffMs: 200,
      });
      cleanups.push(async () => {
        hub.stop();
        await fake.stop();
      });
      await hub.start();
      await hub.connect("http://localhost:" + fake.port);
      await until(() => hub.currentPhase === "online" && hub.allItems().length > 0, 8000, "online");
      return { fake, hub };
    };
    const old = await connect(["extended", "timer"]);
    assert.equal(old.hub.allItems().filter((i) => i.kind === "calc").length, 0);
    const s0 = new MockSurface("Keypad", "D1");
    const v0 = new ActionView("computed", old.hub, s0, { item: "calc:sum:power:all" });
    cleanups.push(() => v0.dispose());
    v0.draw(true);
    assert.match(s0.svg, /5\.59\.4/);

    const { fake, hub } = await connect(["extended", "timer", "calc"]);
    assert.equal(hub.allItems().filter((i) => i.kind === "calc" && i.calc).length, calcItems().length);
    const s = new MockSurface("Keypad", "D1");
    const v = new ActionView("computed", hub, s, { item: "calc:sum:power:all" });
    hub.watch(v);
    cleanups.push(() => v.dispose());
    await until(() => fake.historyAsks.some((a) => a.ids.includes("calc:sum:power:all")), 3000, "its graph asked for");
    fake.setState("calc:sum:power:all", { value: 977, value_text: "977 W" });
    await until(() => texts(s.svg).join(" ").includes("977"), 3000, "the new total");
    // a room+kind id keeps its comma in ids: ZIGMon glues it back
    const s2 = new MockSurface("Keypad", "D1");
    const v2 = new ActionView("computed", hub, s2, { item: "calc:sum:power:room=r1,kind=light", label: "Obývák lights" });
    hub.watch(v2);
    cleanups.push(() => v2.dispose());
    await until(() => fake.historyAsks.some((a) => a.ids.includes("calc:sum:power:room=r1,kind=light")), 3000, "the room+kind id asked whole");
    fake.setState("calc:sum:power:room=r1,kind=light", { value: 77, value_text: "77 W" });
    await until(() => texts(s2.svg).join(" ").includes("77"), 3000, "the room's lights");
  });
});
