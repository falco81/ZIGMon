/**
 * 1.3: text sizes - each kind of text on a key (the value, the name, the room, the detail, the mode,
 * the unit, the badge) in its own size, 50-200 % per key, and as the default of an action type.
 * Unset (100 %), every key draws byte for byte as before; set, only that kind of text changes size,
 * and nothing runs off the key at 50 % or 200 % in any look of any action.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import { Hub } from "../src/core/hub.js";
import { NodeTransport } from "../src/core/http.js";
import { LAYOUTS } from "../src/core/layouts.js";
import { handlePi, textDefaultsMessage } from "../src/core/piapi.js";
import { FakeProtector } from "../src/core/secrets.js";
import { cleanTextSize, normalizeAction, normalizeGlobal, TEXT_KEYS, textScaleOf } from "../src/core/settings.js";
import { grow, growAll, mixLine, ONE, tagRoles, TEXT_ROLES, type TextRole } from "../src/core/svg.js";
import { ALL_INFO, renderLook, THEMES, type Face } from "../src/core/themes.js";
import { renderControl } from "../src/core/render.js";
import { ActionView } from "../src/core/views.js";
import { MemoryStore, MockSurface } from "./fake-zigmon.js";
import { CORPUS_SETTINGS, corpus, corpusHub, drawCase, type CorpusCase } from "./sizes-corpus.js";
import { overflow, roleSizes } from "./sizes-check.js";
import { wellFormed } from "./xml.js";

const cleanups: (() => unknown)[] = [];
after(() => {
  tagRoles(false);
  for (const c of cleanups.reverse()) c();
});

const all = (v: number) => Object.fromEntries(Object.values(TEXT_KEYS).map((k) => [k, v]));
const KEY_OF = (r: TextRole) => TEXT_KEYS[r]!;

describe("text sizes (1.3): the settings", () => {
  it("normalizeAction: whole multiples of 5 from 50 to 200, per kind of text; 100 is not kept", () => {
    for (const r of TEXT_ROLES) {
      const k = KEY_OF(r);
      for (const v of [50, 55, 95, 105, 150, 195, 200]) assert.deepEqual(normalizeAction({ [k]: v }), { [k]: v }, k + " " + v);
      for (const bad of [100, 45, 0, -50, 205, 300, 52, 99, 150.5, 1e9, NaN, Infinity, "150", "", null, true, [150], { v: 150 }]) {
        assert.deepEqual(normalizeAction({ [k]: bad }), {}, k + " " + JSON.stringify(bad));
      }
    }
    assert.deepEqual(normalizeAction({ textValue: 150, textName: 70, textRoom: 100, textDetail: 55, textMode: 200, textUnit: 60, textBadge: 120, textFoo: 150 }),
      { textValue: 150, textName: 70, textDetail: 55, textMode: 200, textUnit: 60, textBadge: 120 });
    assert.equal(cleanTextSize(100), undefined);
    assert.equal(cleanTextSize(125), 125);
  });

  it("the factors: the key's own size, else its type's default, else 100 %", () => {
    assert.deepEqual(textScaleOf({}), { ...ONE });
    assert.equal(textScaleOf({ textValue: 150 }).value, 1.5);
    assert.equal(textScaleOf({}, { textValue: 150 }).value, 1.5);
    assert.equal(textScaleOf({ textValue: 70 }, { textValue: 150 }).value, 0.7);
    assert.equal(textScaleOf({ textValue: 100 }, { textValue: 150 }).value, 1.5, "100 is not stored, so the default holds");
    assert.equal(textScaleOf({}, { textValue: 33 }).value, 1, "a bad default is no default");
  });

  it("normalizeGlobal: defaults only for known action types, only good sizes, empty ones dropped", () => {
    const g = normalizeGlobal({ textSizes: { control: { textValue: 150, textName: 100, textMode: 7 }, reading: { textValue: 100 }, bogus: { textValue: 150 }, __proto__: { textValue: 150 }, sms: [1], room: { textBadge: 60 } } });
    assert.deepEqual(g.textSizes, { control: { textValue: 150 }, room: { textBadge: 60 } });
    assert.equal(normalizeGlobal({ textSizes: "x" }).textSizes, undefined);
    assert.equal(normalizeGlobal({ textSizes: { control: {} } }).textSizes, undefined);
  });

  it("the size helpers: a factor of 1 gives the very same numbers (and arrays)", () => {
    const l = [44, 38, 32];
    assert.equal(growAll(l, 1), l);
    assert.equal(grow(13.5, 1, 2), 13.5);
    assert.equal(grow(10, 2, 15), 15, "held to its cap");
    assert.equal(grow(10, 0.5, 15), 5);
    assert.deepEqual(growAll([30, 20], 2), [60, 40, 30, 20], "bigger keeps the sizes at 100 % as fallbacks");
    // a line of two roles: one text while they agree, each its own size when not
    const one = mixLine(0, 10, [["→ 22.0°", "detail"], [" · Comfort", "mode"]], [13], 120, { weight: 700, fill: "#fff" }, ONE).svg;
    assert.ok(!one.includes("<tspan"));
    const two = mixLine(0, 10, [["→ 22.0°", "detail"], [" · Comfort", "mode"]], [13], 200, { weight: 700, fill: "#fff" }, { ...ONE, mode: 1.5 }).svg;
    assert.match(two, /<tspan font-size="19\.5">/);
  });
});

describe("text sizes (1.3): unset, nothing changes", () => {
  it("every look x action x state x setting draws byte for byte the same with every size at 100 % (or a default of 100 %)", () => {
    let n = 0;
    const hundreds = all(100);
    for (const c of corpus(undefined, [CORPUS_SETTINGS[0]!, CORPUS_SETTINGS[3]!], ["as-is", "offline", "locked"])) {
      const a = drawCase(c);
      assert.deepEqual(drawCase(c, hundreds), a, c.name);
      assert.deepEqual(drawCase(c, {}, () => hundreds), a, c.name + " (type default 100 %)");
      n++;
    }
    assert.ok(n > 10000, "drawn " + n);
  });

  it("a look given the factors of 100 % explicitly draws as one given none", () => {
    const f: Face = {
      kind: "thermostat", name: "Bedroom radiator", room: "Bedroom", icon: "heat", accent: "#F0883E", active: true, state: "21.5", unit: "°C", stateColour: null,
      detail: "→ 22.0 °C", mode: "Comfort", level: 0.6, series: [20, 21, 21.5], target: 22, online: true, allowed: true, hold: false, battery: null, badge: 3,
    };
    for (const t of THEMES) if (t.id !== "classic") assert.equal(renderLook(t.id, f, { info: ALL_INFO, fit: "fit", ts: { ...ONE } }), renderLook(t.id, f, { info: ALL_INFO, fit: "fit" }), t.id);
    const m = { name: "Lampa", room: "Obývák", showRoom: true, kind: "socket", icon: "plug", on: true, valueText: "42 W", online: true, battery: null, hold: false, allowed: true };
    assert.equal(renderControl(m, { ts: { ...ONE } }), renderControl(m));
  });
});

/** The cases the role checks go through: every look, every action on each item it takes, as it is. */
function roleCases(): CorpusCase[] {
  return [...corpus(undefined, [CORPUS_SETTINGS[0]!, CORPUS_SETTINGS[2]!], ["as-is"])];
}

describe("text sizes (1.3): each kind of text alone", () => {
  it("a role's size changes that role's text; the others stay (outside the lines they share), but for a rare size step where they give or take room", () => {
    tagRoles(true);
    const grew = new Map<string, number>(), shrank = new Map<string, number>();
    const moved: string[] = [];
    let checks = 0;
    try {
      for (const c of roleCases()) {
        const base = roleSizes(drawCase(c).svg);
        for (const r of TEXT_ROLES) {
          for (const v of [150, 50]) {
            const sc = roleSizes(drawCase(c, { [KEY_OF(r)]: v }).svg);
            const where = `${c.name} ${r}=${v}`;
            const own = (l: typeof base) => l.filter((e) => e.role === r).map((e) => e.size);
            // what is not the role, nor in a text the role is part of (a value gives way to a bigger unit beside it)
            const others = (l: typeof base, role: string) => l.filter((e) => e.role === role && !e.shared.includes(r) && !(r === "unit" && role === "value")).map((e) => e.size);
            for (const o of TEXT_ROLES) {
              if (o === r) continue;
              const b = others(base, o), s = others(sc, o);
              if (!s.length || !b.length) continue;
              const was = Math.max(...b), now = Math.max(...s);
              checks++;
              if (Math.abs(now - was) > 0.01) moved.push(`${where}: ${o} ${was} -> ${now}`);
              // bigger, the others never grow (they may give way); smaller, they never shrink (they may take the room it leaves) -
              // but a look that fits its words to the room left moves them a size step at most, now and then
              if (v > 100) assert.ok(now <= was * 1.2 + 0.01, `${where}: ${o} got bigger (${was} -> ${now})`);
              else assert.ok(now >= was * 0.8 - 0.01, `${where}: ${o} got smaller (${was} -> ${now})`);
            }
            const b = own(base), s = own(sc);
            if (!b.length || !s.length) continue;
            if (v === 50) {
              assert.ok(Math.max(...s) < Math.max(...b), `${where}: not smaller (${Math.max(...b)} -> ${Math.max(...s)})`);
              shrank.set(r, (shrank.get(r) ?? 0) + 1);
            } else {
              // (where its place is full it may give way a little, as it does at 100 %)
              assert.ok(Math.max(...s) >= Math.max(...b) * 0.9 - 0.01, `${where}: smaller at 150 % (${Math.max(...b)} -> ${Math.max(...s)})`);
              if (Math.max(...s) > Math.max(...b) + 0.01) grew.set(r, (grew.get(r) ?? 0) + 1);
            }
          }
        }
      }
    } finally {
      tagRoles(false);
    }
    assert.ok(moved.length <= checks * 0.01, `the others moved in ${moved.length} of ${checks}: ${moved.slice(0, 5).join("; ")}`);
    for (const r of TEXT_ROLES) {
      assert.ok((grew.get(r) ?? 0) > 20, r + " grew in " + (grew.get(r) ?? 0) + " cases");
      assert.ok((shrank.get(r) ?? 0) > 20, r + " shrank in " + (shrank.get(r) ?? 0) + " cases");
    }
  });

  it("Computed takes the sizes as Reading does (value, unit, name, detail), and its type's default", () => {
    const cs = [...corpus(["classic", "bigvalue"], [{}], ["as-is"])].filter((c) => (c.kind as string) === "computed");
    assert.ok(cs.length >= 4, "computed cases: " + cs.length);
    tagRoles(true);
    try {
      for (const c of cs) {
        const base = roleSizes(drawCase(c).svg);
        assert.ok(base.some((e) => e.role === "value") && base.some((e) => e.role === "name"), c.name);
        for (const r of ["value", "name"] as const) {
          const big = roleSizes(drawCase(c, { [KEY_OF(r)]: 50 }).svg).filter((e) => e.role === r).map((e) => e.size);
          assert.ok(Math.max(...big) < Math.max(...base.filter((e) => e.role === r).map((e) => e.size)), c.name + " " + r);
        }
        assert.equal(drawCase(c, {}, (k) => (k === "computed" ? { textValue: 50 } : null)).svg, drawCase(c, { textValue: 50 }).svg, c.name + " default");
      }
    } finally {
      tagRoles(false);
    }
    assert.deepEqual(normalizeGlobal({ textSizes: { computed: { textUnit: 150 } } }).textSizes, { computed: { textUnit: 150 } });
  });

  it("tagging is for the tests only: off, no role is written", () => {
    const c = roleCases()[0]!;
    assert.ok(!drawCase(c, all(150)).svg.includes("data-role"));
  });
});

describe("text sizes (1.3): nothing off the key", () => {
  for (const v of [200, 50]) {
    it(`at ${v} %: every look and Classic, every action, state and setting - no text runs off the 144 px key (beyond what 100 % did)`, () => {
      let n = 0;
      for (const c of corpus(undefined, undefined, ["as-is", "offline", "flip"])) {
        const base = overflow(drawCase(c).svg).px;
        const d = drawCase(c, all(v));
        if (n % 97 === 0) wellFormed(d.svg);
        const o = overflow(d.svg);
        assert.ok(o.px <= Math.max(base, 3), `${c.name}: ${o.what} (off by ${o.px.toFixed(1)} px)`);
        n++;
      }
      assert.ok(n > 30000, "drawn " + n);
    });
  }

  it("the touch strip: each text in its role's size, never taller than its place; back to 100 %, the layout's sizes once", () => {
    const c = [...corpus(["classic"], [{}], ["as-is"])].find((x) => x.kind === "thermostat")!;
    const s = new MockSurface("Encoder", "D");
    const v = new ActionView("thermostat", corpusHub(c.items), s, { ...c.settings, textValue: 200, textMode: 50 });
    v.draw(true);
    const fb = s.feedbacks.at(-1) as Record<string, { font?: { size: number; weight: number } }>;
    const L = Object.fromEntries(LAYOUTS.thermostat!.items.map((x) => [x.key, x]));
    assert.equal(fb.value!.font!.size, L.value!.rect[3], "held to its height");
    assert.equal(fb.mode!.font!.size, Math.round(L.mode!.font!.size * 0.5));
    assert.equal(fb.name!.font!.size, L.name!.font!.size);
    v.setSettings({ ...c.settings });
    const back = s.feedbacks.at(-1) as Record<string, { font?: { size: number } }>;
    assert.equal(back.value!.font!.size, L.value!.font!.size, "the layout's own size sent back");
    v.draw(true);
    assert.equal((s.feedbacks.at(-1) as Record<string, { font?: unknown }>).value!.font, undefined, "then nothing more");
    v.dispose();
    const plain = new MockSurface("Encoder", "D");
    const pv = new ActionView("thermostat", corpusHub(c.items), plain, c.settings);
    pv.draw(true);
    assert.ok(!JSON.stringify(plain.feedbacks).includes('"font"'), "never set: no font at all");
    pv.dispose();
  });
});

describe("text sizes (1.3): the default of an action type", () => {
  it("kept in the global settings, used by every key of the type without sizes of its own; a key's own size wins; cleared again", async () => {
    const store = new MemoryStore();
    const hub = new Hub({ store, protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => [], computer: () => "PC" });
    cleanups.push(() => hub.stop());
    await hub.start();
    const c = [...corpus(["bigvalue"], [{}], ["as-is"])].find((x) => x.kind === "reading")!;
    const preview = () => "data:image/svg+xml;base64,AA==";
    const r = await handlePi(hub, "reading", { t: "textDefaults", sizes: { textValue: 150, textName: 100, textUnit: 33, bogus: 1 } }, preview);
    assert.deepEqual(r[0], { t: "textDefaults", kind: "reading", sizes: { textValue: 150 } });
    assert.equal(r[1]?.t, "preview", "the inspector gets the key again");
    assert.deepEqual((store.value as { textSizes?: unknown }).textSizes, { reading: { textValue: 150 } }, "saved");
    assert.deepEqual(normalizeGlobal(store.value).textSizes, { reading: { textValue: 150 } });
    assert.deepEqual(hub.textDefaults("reading"), { textValue: 150 });
    assert.equal(hub.textDefaults("control"), null, "only that type");
    const defaults = (k: string) => hub.textDefaults(k);
    // a key of the type draws as if it had the size itself; its own size wins
    assert.equal(drawCase(c, {}, defaults).svg, drawCase(c, { textValue: 150 }).svg);
    assert.notEqual(drawCase(c, {}, defaults).svg, drawCase(c).svg);
    assert.equal(drawCase(c, { textValue: 70 }, defaults).svg, drawCase(c, { textValue: 70 }).svg);
    // the keys are drawn again at once
    let redrawn = 0;
    hub.watch({ ids: () => [], refresh: () => void redrawn++ });
    await hub.setTextDefaults("reading", { textValue: 160 });
    assert.ok(redrawn > 0);
    assert.deepEqual(textDefaultsMessage(hub, "reading"), { t: "textDefaults", kind: "reading", sizes: { textValue: 160 } });
    // hello says what they are; an empty set clears them
    assert.ok((await handlePi(hub, "reading", { t: "hello" })).some((m) => m.t === "textDefaults"));
    await handlePi(hub, "reading", { t: "textDefaults", sizes: {} });
    assert.equal(hub.textDefaults("reading"), null);
    assert.equal((store.value as { textSizes?: unknown }).textSizes, undefined);
    await hub.setTextDefaults("nonsense", { textValue: 150 });
    assert.equal(hub.textDefaults("nonsense"), null);
  });
});
