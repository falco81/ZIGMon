/**
 * (1.3) Honest graphics: every bar, column, sparkline, wave, fill, ring, arc, gauge, dial, tube,
 * segment meter and grid of lamps stands for a real number on a real scale - the value the key
 * shows - and a key that shows a word (a room's mode) draws none of them.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import type { Hub } from "../src/core/hub.js";
import { P } from "../src/core/palette.js";
import { parseItem, type Item } from "../src/core/protocol.js";
import { levelIn, readingLevel, seriesScale } from "../src/core/scale.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { MockSurface } from "./fake-zigmon.js";

const cleanups: (() => unknown)[] = [];
after(() => cleanups.forEach((c) => c()));

const st = (o: Record<string, unknown>) => ({ on: null, value: null, value_text: "", attrs: {}, online: true, battery: null, at: 1700000000, ...o });

function hubOf(items: Item[], series: Record<string, number[]> = {}): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: (id: string) => series[id] ?? [],
    series: (id: string) => series[id] ?? null, deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
    command: async () => ({ ok: true, said: "", state: null }),
  } as unknown as Hub;
}

function draw(kind: ActionKind, item: Item, settings: Record<string, unknown>, series: Record<string, number[]> = {}): { svg: string; v: ActionView } {
  const s = new MockSurface("Keypad", "D");
  const v = new ActionView(kind, hubOf([item], series), s, { item: item.id, ...settings });
  v.draw(true);
  cleanups.push(() => v.dispose());
  return { svg: s.svg, v };
}

// ------------------------------------------------------------------ small SVG readers

type El = Record<string, string>;
/** Every element of a tag with its attributes. */
function els(svg: string, tag: string): El[] {
  return [...svg.matchAll(new RegExp(`<${tag}\\b([^>]*?)/?>`, "g"))].map((m) => Object.fromEntries([...m[1]!.matchAll(/([\w:-]+)="([^"]*)"/g)].map((a) => [a[1]!, a[2]!])));
}
const num = (e: El, k: string) => Number(e[k]);
/** The points of a path's M / L commands. */
function points(d: string): [number, number][] {
  return [...d.matchAll(/[ML] (-?[\d.]+) (-?[\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
}
/** An arc path's sweep in degrees, from its start and end around (cx, cy). */
function sweep(d: string, cx: number, cy: number): number {
  const m = /M (-?[\d.]+) (-?[\d.]+) A [\d.]+ [\d.]+ 0 (\d) 1 (-?[\d.]+) (-?[\d.]+)/.exec(d);
  assert.ok(m, "an arc: " + d);
  const ang = (x: number, y: number) => (Math.atan2(x - cx, -(y - cy)) * 180) / Math.PI;
  let s = ang(Number(m[4]), Number(m[5])) - ang(Number(m[1]), Number(m[2]));
  while (s < 0) s += 360;
  if (m[3] === "1" && s < 180) s += 360;
  return s;
}
/** The angle (0 at the top, clockwise) of a point around (cx, cy). */
const angleOf = (x: number, y: number, cx: number, cy: number) => (Math.atan2(x - cx, -(y - cy)) * 180) / Math.PI;
const near = (a: number, b: number, tol: number, what: string) => assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} is not ${b} ± ${tol}`);

// ------------------------------------------------------------------ the items

/** A heated room as ZIGMon describes it: its state is its mode, a word. */
function roomItem(attrs: Record<string, unknown> = {}): Item {
  return parseItem({
    id: "heat:room:r2", name: "Heating in Loznice", room: "Loznice", kind: "thermostat", icon: "heat", cap: "climate", actions: ["set", "toggle", "on", "off"], allowed: true, hold: false,
    attrs: [
      { key: "mode", label: "Mode", type: "enum", values: ["plan", "comfort", "eco", "night", "max", "off", "manual"] },
      { key: "target", label: "Wanted temperature", type: "number", unit: "°C", min: 5, max: 30, step: 0.5, via: "heat:temp:r2" },
    ],
    state: { on: true, value: null, value_text: "max", online: true, battery: null, attrs: { mode: "max", calling: true, temperature: 24.6, target: 35, why: "max", by_hand: false, hold_until: null, ...attrs } },
  });
}
const temp = (v: number) => parseItem({
  id: "read:t1:temperature", name: "Living room", room: "Obývák", kind: "reading", icon: "thermo", cap: "view", actions: [], allowed: true, hold: false,
  attrs: [{ key: "temperature", label: "Temperature", type: "number", unit: "°C" }], state: st({ value: v, value_text: v + " °C" }),
});
const rawDimmer = {
  id: "zb:0xb9:light", name: "Desk lamp", room: "Office", kind: "dimmer", icon: "light", cap: "dim", actions: ["toggle", "on", "off", "set"], allowed: true, hold: false,
  attrs: [{ key: "brightness", label: "Brightness", type: "number", unit: "", min: 0, max: 254, step: 1 }], state: st({ on: true, attrs: { brightness: 127 } }),
};
const dimmer = parseItem(rawDimmer);
const trv = (current: number, setpoint: number) => parseItem({
  id: "zb:0xc9:trv", name: "Bedroom radiator", room: "Bedroom", kind: "thermostat", icon: "heat", cap: "climate", actions: ["set"], allowed: true, hold: false,
  attrs: [{ key: "current_heating_setpoint", label: "Setpoint", type: "number", unit: "°C", min: 5, max: 30, step: 0.5 }],
  state: st({ value: current, value_text: current + " °C", attrs: { current_heating_setpoint: setpoint, running_state: "heat" } }),
});
const battery = parseItem({
  id: "read:b1:battery", name: "Door sensor", room: "Hall", kind: "reading", icon: "battery", cap: "view", actions: [], allowed: true, hold: false,
  attrs: [{ key: "battery", label: "Battery", type: "number", unit: "%", min: 0, max: 100 }], state: st({ value: 40, value_text: "40 %" }),
});

const LOOKS = THEMES.map((t) => t.id);

describe("honest scales (scale.ts)", () => {
  it("a series is drawn on its range, from 0, or on a sensible span for its unit - never min to max", () => {
    assert.deepEqual(seriesScale([21.5, 21.52, 21.49], { unit: "°C" }), { lo: 21.505 - 2, hi: 21.505 + 2 });
    assert.deepEqual(seriesScale([900, 1800, 1500], { unit: "W" }), { lo: 0, hi: 1800 });
    assert.deepEqual(seriesScale([40, 42], { unit: "%" }), { lo: 0, hi: 100 });
    assert.deepEqual(seriesScale([47, 48], { unit: "%RH" }), { lo: 42.5, hi: 52.5 });
    assert.deepEqual(seriesScale([1012, 1013], { unit: "hPa" }), { lo: 1007.5, hi: 1017.5 });
    assert.deepEqual(seriesScale([60, 61], { unit: "%", min: 0, max: 100 }), { lo: 0, hi: 100 });
    assert.deepEqual(seriesScale([17, 25], { unit: "°C" }), { lo: 17, hi: 25 }, "a real change wider than the span keeps its own");
    assert.deepEqual(seriesScale([20, 21], { unit: "°C" }, [25]), { lo: 20, hi: 25 }, "the target stays inside");
  });

  it("a level only from a real range", () => {
    assert.equal(levelIn(127, 0, 254), 0.5);
    assert.equal(levelIn(21, null, 30), null);
    assert.equal(readingLevel(40, { unit: "%" }), 0.4);
    assert.equal(readingLevel(21.5, { unit: "°C" }), null);
  });
});

describe("a key that says a word draws no magnitude", () => {
  const cases: [string, ActionKind, Item, Record<string, unknown>][] = [
    ["Reading on a heated room (its mode)", "reading", roomItem(), {}],
    ["Thermostat on a room with no thermometer", "thermostat", roomItem({ temperature: null }), { showGraph: true }],
  ];
  for (const [what, kind, item, settings] of cases) {
    it(what + ": no series, no level, the same drawing whatever the room's history", () => {
      for (const t of LOOKS) {
        const quiet = draw(kind, item, { theme: t, ...settings });
        const f = quiet.v.face();
        assert.deepEqual(f.series, [], t + ": no series under a word");
        assert.equal(f.level, null, t + ": no level under a word");
        if (kind === "reading") assert.equal(f.unit, "", t + ": no unit after a word");
        for (const h of [[24.1, 24.9, 24.3, 24.6], [10, 30, 15, 28, 12]]) {
          assert.equal(draw(kind, item, { theme: t, ...settings }, { "heat:room:r2": h }).svg, quiet.svg, t + ": the room's history changes nothing");
        }
        // no partial arc: an arc is the track, or whole (on)
        if (t === "gauge") {
          const arcs = els(quiet.svg, "path").filter((p) => p["stroke-width"] === "12" && p.d!.includes(" A "));
          for (const a of arcs) near(sweep(a.d!, 72, 70), 270, 0.5, "gauge: a whole arc or none");
        }
        if (t === "bars") assert.equal(els(quiet.svg, "rect").filter((r) => r.fill === P.panel2).length, 0, "bars: no columns");
      }
    });
  }
});

describe("a flat series draws flat, a change draws its size", () => {
  const flat = { "read:t1:temperature": [21.5, 21.52, 21.49, 21.51, 21.5, 21.52, 21.49, 21.5] };
  const rising = { "read:t1:temperature": [17, 17.8, 18.9, 19.6, 20.4, 21.2, 21.9, 22.5] };

  it("the Bars look's columns", () => {
    const heights = (series: Record<string, number[]>) => {
      const svg = draw("reading", temp(21.5), { theme: "bars" }, series).svg;
      const cols = els(svg, "rect").filter((r) => r.fill !== P.panel2 && Number(r.width) < 14 && Number(r.y) > 60);
      assert.ok(cols.length >= 8, "a column per value");
      return cols.map((r) => num(r, "height"));
    };
    const f = heights(flat);
    near(Math.max(...f) - Math.min(...f), 0, 0.5, "flat columns");
    assert.ok(Math.max(...f) < 24, "and not stretched to the top: " + f);
    const r = heights(rising);
    assert.ok(Math.max(...r) - Math.min(...r) > 15, "a rise of 5.5 °C shows");
  });

  for (const t of ["classic", "bigvalue", "huge", "aurora", "glass", "stamp", "neon"]) {
    it(t + ": the sparkline", () => {
      const line = (series: Record<string, number[]>, extra: Record<string, unknown> = {}) => {
        const svg = draw("reading", temp(21.5), { theme: t, ...extra }, series).svg;
        const p = els(svg, "path").find((e) => e.fill === "none" && /^M [\d.-]+ [\d.-]+ L /.test(e.d ?? "") && points(e.d!).length >= 8);
        assert.ok(p, t + ": a sparkline");
        return points(p.d!).map((q) => q[1]);
      };
      const extra = t === "neon" ? { showState: false } : {};
      const f = line(flat, extra);
      near(Math.max(...f) - Math.min(...f), 0, 1, t + ": flat");
      const r = line(rising, extra);
      assert.ok(Math.max(...r) - Math.min(...r) > 8, t + ": a rise shows");
    });
  }

  it("showScale states the scale the graph is drawn on", () => {
    const svg = draw("reading", temp(21.5), { theme: "bigvalue", showScale: true }, flat).svg;
    const labels = els(svg, "text").filter((e) => e["text-anchor"] === "end" && e["font-size"] === "9.5");
    const words = [...svg.matchAll(/font-size="9.5"[^>]*>([^<]+)</g)].map((m) => Number(m[1]));
    assert.equal(labels.length, 2);
    assert.deepEqual(words, [23.5, 19.5], "4 °C round the data");
    // the last value sits where those labels put it: graph at y 110, 22 high
    const p = els(svg, "path").find((e) => e.fill === "none" && /^M [\d.-]+ [\d.-]+ L /.test(e.d ?? ""))!;
    const y = points(p.d!).at(-1)![1];
    near(y, 110 + 22 - ((21.5 - 19.505) / 4) * 18 - 2, 0.1, "the last point on that scale");
    // the house's power stands on 0
    const cl = draw("reading", parseItem({ id: "read:p", name: "Pump", room: null, kind: "reading", icon: "bolt", cap: "view", actions: [], allowed: true, hold: false,
      attrs: [{ key: "power", label: "Power", type: "number", unit: "W" }], state: st({ value: 1840, value_text: "1840 W" }) }), { theme: "classic", showScale: true }, { "read:p": [900, 1500, 1840] }).svg;
    assert.deepEqual([...cl.matchAll(/font-size="9.5"[^>]*>([^<]+)</g)].map((m) => m[1]), ["1840", "0"]);
  });
});

describe("levels from real ranges", () => {
  /** Where each look draws a level: what it measures, given the expected level. */
  function measure(t: string, svg: string, full?: string): number | null {
    const rects = els(svg, "rect");
    switch (t) {
      case "gauge": {
        const a = els(svg, "path").filter((p) => p["stroke-width"] === "12" && p.d!.includes(" A "));
        return a.length < 2 ? 0 : sweep(a[1]!.d!, 72, 70) / 270;
      }
      case "ring": case "orb": {
        const sw = t === "ring" ? "8" : "3.5";
        const c = els(svg, "circle").find((e) => e["stroke-width"] === sw && e.fill === "none")!;
        const a = els(svg, "path").find((p) => p["stroke-width"] === sw && p.d!.includes(" A "));
        return a ? sweep(a.d!, num(c, "cx"), num(c, "cy")) / 360 : null;
      }
      case "dial": {
        const k = els(svg, "circle").find((e) => e.fill === "url(#knob)")!;
        const p = els(svg, "circle").find((e) => e.r === "2.6")!;
        return (angleOf(num(p, "cx"), num(p, "cy"), num(k, "cx"), num(k, "cy")) + 135) / 270;
      }
      case "wave": {
        const w = els(svg, "path").find((p) => p.fill === "url(#water)");
        return w ? (144 - Number(/^M -10 (-?[\d.]+)/.exec(w.d!)![1])) / 140 : 0;
      }
      case "tube": {
        const r = rects.find((e) => e.x === "110" && e.width === "10");
        return r ? (num(r, "height") - 8) / 52 : 0;
      }
      case "grid":
        return els(svg, "circle").filter((e) => e.r === "5" && e["fill-opacity"] === "0.6").length / 64;
      case "bars":
        return rects.filter((e) => e.fill === P.warn && num(e, "y") > 60).length / 6;
      case "lcd":
        return rects.filter((e) => e.width === "8.4" && e.fill === P.warn).length / 10;
      case "stripe":
        return num(rects.find((e) => e.x === "0" && e.width === "16" && e.height !== "144")!, "height") / 144;
      case "tile": {
        const v = rects.filter((e) => e.width === "6");
        return num(v[1]!, "height") / num(v[0]!, "height");
      }
      case "rise": {
        const sun = els(svg, "circle").find((e) => e.r === "96")!;
        return (144 - (num(sun, "cy") - 96) - 12) / 38;
      }
      case "marquee":
        return els(svg, "circle").filter((e) => e.r === "2.6" && e.fill === P.warn).length / 34;
      case "line":
        return num(rects.find((e) => e.x === "14" && e.height === "4")!, "width") / 116;
      case "classic": {
        const r = rects.find((e) => e.y === "97" && e.fill === "url(#lvl)");
        return r ? num(r, "width") / 116 : null;
      }
      default: {
        // a bar: a track and a fill on it, from the same corner and as high
        for (const a of rects) {
          for (const b of rects) {
            if (a === b || a.x !== b.x || a.y !== b.y || a.height !== b.height || num(b, "width") >= num(a, "width") || num(a, "width") < 20) continue;
            return num(b, "width") / num(a, "width");
          }
        }
        // no track: against the same key at a full level - a bar along the name, the pill, the badge, a rule
        return full ? againstFull(svg, full) : null;
      }
    }
  }

  /** A bar with no track of its own: its length here over its length on the same key at a full level. */
  function againstFull(svg: string, full: string): number | null {
    const key = (e: El) => JSON.stringify(e);
    const fullRects = els(full, "rect"), seen = new Set(fullRects.map(key));
    for (const r of els(svg, "rect").filter((e) => !seen.has(key(e)))) {
      const w = fullRects.find((e) => e.x === r.x && e.y === r.y && e.height === r.height && e.fill === r.fill && e.width !== r.width);
      if (w) return num(r, "width") / num(w, "width");
      const h = fullRects.find((e) => e.x === r.x && e.width === r.width && e.fill === r.fill && Math.abs(num(e, "y") + num(e, "height") - num(r, "y") - num(r, "height")) < 0.01);
      if (h) return num(r, "height") / num(h, "height");
    }
    const hp = (svg: string) => els(svg, "path").map((e) => /^M (-?[\d.]+) (-?[\d.]+) H (-?[\d.]+)$/.exec(e.d ?? "")).filter((m) => m) as RegExpExecArray[];
    const fp = hp(full);
    for (const m of hp(svg)) {
      const o = fp.find((q) => q[1] === m[1] && q[2] === m[2] && q[3] !== m[3]);
      if (o) return (Number(m[3]) - Number(m[1])) / (Number(o[3]) - Number(o[1]));
    }
    return null;
  }

  /** The looks that draw a level, and how finely (the step of their meter). */
  const LEVEL_LOOKS: [string, number][] = [
    ["classic", 0.01], ["gauge", 0.01], ["ring", 0.01], ["orb", 0.01], ["dial", 0.01], ["wave", 0.01], ["tube", 0.01], ["grid", 1 / 16], ["bars", 1 / 12],
    ["lcd", 0.05], ["stripe", 0.01], ["tile", 0.01], ["rise", 0.01], ["huge", 0.01], ["pill", 0.01], ["aurora", 0.01], ["mono", 0.01], ["hex", 0.01], ["bubble", 0.01],
    ["shadow", 0.01], ["tab", 0.01], ["spot", 0.01], ["pastel", 0.01], ["stamp", 0.01], ["label", 0.01], ["carbon", 0.01], ["line", 0.01], ["minimal", 0.06],
    ["neon", 0.04], ["glass", 0.01], ["dot", 0.01], ["bigvalue", 0.01], ["light", 0.01], ["fill", 0.01],
    // the name-first looks
    ["lined", 0.01], ["marquee", 1 / 68], ...["namebar", "caption", "led", "tworows", "plate", "ticker", "card", "halves", "stacked", "corner", "terminal", "widget", "sign", "note", "pass", "glow"]
      .map((t) => [t, 0.02] as [string, number]),
  ];

  it("brightness 127 of 254 is a 50 % level in every look that draws one", () => {
    const wrong: string[] = [];
    const bright = parseItem({ ...JSON.parse(JSON.stringify(rawDimmer)), state: st({ on: true, attrs: { brightness: 254 } }) });
    for (const [t, tol] of LEVEL_LOOKS) {
      const { svg, v } = draw("dimmer", dimmer, { theme: t });
      assert.equal(v.face().level, 0.5);
      const got = measure(t, svg, draw("dimmer", bright, { theme: t }).svg);
      if (got === null || Math.abs(got - 0.5) > tol) wrong.push(t + "=" + got);
    }
    assert.deepEqual(wrong, [], "every look draws brightness 127/254 at 50 %");
  });

  it("a battery at 40 % is a 40 % level", () => {
    for (const t of ["gauge", "ring", "orb", "dial", "tube", "stripe", "huge", "pill", "aurora"]) {
      const { svg, v } = draw("reading", battery, { theme: t });
      assert.equal(v.face().level, 0.4, t);
      near(measure(t, svg)!, 0.4, 0.01, t);
    }
  });

  it("a thermostat at 21 °C in 5..30 stands at (21-5)/25 on its arc, its target marked where it is", () => {
    const want = (21 - 5) / 25;
    for (const t of ["gauge", "ring", "orb", "dial", "tube", "wave", "stripe"]) {
      const { svg, v } = draw("thermostat", trv(21, 25), { theme: t, showGraph: true });
      assert.equal(v.face().level, want, t);
      near(measure(t, svg)!, want, 0.01, t);
    }
    // the target's notch on the gauge, at (25-5)/25
    const g = draw("thermostat", trv(21, 25), { theme: "gauge", showGraph: true }).svg;
    const mark = els(g, "path").find((p) => p["data-mark"] !== undefined)!;
    near(Number(mark["data-mark"]), -135 + 270 * ((25 - 5) / 25), 0.01, "the target's notch");
    // Classic's arc is the set point (it says "→ 21.0"): at (21-5)/25 too
    const cl = draw("thermostat", trv(19, 21), { theme: "classic" }).svg;
    const arc = els(cl, "path").find((p) => p.stroke === "url(#arc)")!;
    near(sweep(arc.d!, 72, 70) / 270, want, 0.01, "classic");
  });

  it("a number without a range fills nothing: no full gauge under 1840 W, no level from its history", () => {
    const pump = parseItem({ id: "read:p", name: "Pump", room: null, kind: "reading", icon: "bolt", cap: "view", actions: [], allowed: true, hold: false,
      attrs: [{ key: "power", label: "Power", type: "number", unit: "W" }], state: st({ value: 1840, value_text: "1840 W" }) });
    for (const t of ["gauge", "ring", "wave", "tube", "dial", "grid", "rise", "marquee", "lined"]) {
      const { svg, v } = draw("reading", pump, { theme: t, critAbove: 1000 }, { "read:p": [200, 1900, 1840] });
      assert.equal(v.face().level, null, t);
      assert.ok(v.face().active, t + ": lit (past its threshold)");
      const m = measure(t, svg);
      assert.ok(m === null || m < 0.01 || (t === "rise" && Math.abs(m) < 0.01), t + ": nothing filled, got " + m);
    }
  });
});
