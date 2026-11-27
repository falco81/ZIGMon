import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import type { Hub } from "../src/core/hub.js";
import { LAYOUTS } from "../src/core/layouts.js";
import { parseItem, type Item } from "../src/core/protocol.js";
import {
  renderBlinds, renderControl, renderDimmer, renderHold, renderNotice, renderPair, renderReading, renderScene, renderStatus, renderThermostat, renderToast,
} from "../src/core/render.js";
import { esc, fit, textWidth } from "../src/core/svg.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { MockSurface } from "./fake-zigmon.js";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const sd = join(here, "..", "..", "com.zigmon.streamdeck.sdPlugin");

/** A strict little XML checker: balanced tags, quoted attributes, no raw < or stray & in text. */
export function wellFormed(xml: string): void {
  const stack: string[] = [];
  const re = /<(\/?)([A-Za-z][\w:.-]*)((?:\s+[\w:.-]+="[^"<]*")*)\s*(\/?)>/y;
  let i = 0;
  const text = (t: string) => {
    if (t.includes(">") && false) return;
    assert.ok(!/&(?!(amp|lt|gt|quot|#39|#\d+);)/.test(t), "a stray & in: " + t.slice(0, 60));
  };
  while (i < xml.length) {
    const lt = xml.indexOf("<", i);
    if (lt < 0) {
      text(xml.slice(i));
      break;
    }
    text(xml.slice(i, lt));
    re.lastIndex = lt;
    const m = re.exec(xml);
    assert.ok(m, "malformed tag at " + lt + ": " + xml.slice(lt, lt + 80));
    for (const a of m[3]!.matchAll(/="([^"]*)"/g)) text(a[1]!);
    if (m[1]) assert.equal(stack.pop(), m[2], "closing " + m[2]);
    else if (!m[4]) stack.push(m[2]!);
    i = re.lastIndex;
  }
  assert.deepEqual(stack, [], "unclosed tags");
  assert.ok(xml.startsWith("<svg"), "an svg document");
}

const EVIL = '<script>alert(1)</script> & "q" \'s\' \u202e]]>';

function evilItem(kind: string, extra: Record<string, unknown> = {}): Item {
  return parseItem({
    id: "evil:" + kind, name: EVIL, room: EVIL, kind, icon: '"/><script>', cap: "switch", actions: ["toggle", "run", "set", "open", "close", "stop"], allowed: true, hold: false,
    attrs: [
      { key: "brightness", type: "number", unit: '<u>&', min: 0, max: 100, step: 1 },
      { key: "current_heating_setpoint", type: "number", unit: "°C", min: 5, max: 30, step: 0.5 },
      { key: "position", type: "number", unit: "%", min: 0, max: 100 },
      { key: "system_mode", type: "enum", values: [EVIL, "heat"] },
    ],
    state: { on: true, value: 21, value_text: EVIL, attrs: { brightness: 40, current_heating_setpoint: 22, position: 30, system_mode: EVIL, running_state: EVIL }, online: true },
    ...extra,
  });
}

/** A hub stand-in with the few things views read. */
function stubHub(items: Item[], phase = "online"): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: phase, pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [1, 3, 2, 5, 4],
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined, command: async () => ({ ok: true, said: "", state: null }),
  } as unknown as Hub;
}

const svgOf = (uri: string) => Buffer.from(uri.split(",")[1] ?? "", "base64").toString("utf8");

describe("SVG rendering", () => {
  it("every key renderer makes well-formed SVG and escapes everything", () => {
    const base = renderControl({ name: EVIL, room: EVIL, showRoom: true, kind: "socket", icon: "plug", on: true, valueText: EVIL, online: true, battery: 5, hold: true, allowed: false });
    const all = [
      base,
      renderControl({ name: EVIL, room: null, showRoom: false, kind: EVIL, icon: EVIL, on: null, valueText: EVIL, online: false, battery: null, hold: false, allowed: true }),
      renderReading({ label: EVIL, value: EVIL, unit: EVIL, colour: "#F85149", accent: "#39C5CF", icon: "drop", trend: "up", history: [1, 2, NaN, 3], online: true }),
      renderReading({ label: EVIL, value: "", unit: "", colour: "#F85149", accent: "#39C5CF", icon: "drop", trend: null, history: [], online: false }),
      renderThermostat({ name: EVIL, current: 20.4, target: 99, unit: EVIL, mode: EVIL, heating: true, min: 5, max: 30, online: true, hold: true, allowed: true }),
      renderDimmer({ name: EVIL, room: EVIL, showRoom: true, on: true, level: 1.5, levelText: EVIL, online: true, hold: false, allowed: true }),
      renderBlinds({ name: EVIL, room: EVIL, showRoom: true, position: 140, moving: "down", online: true, hold: false, allowed: true }),
      renderScene({ name: EVIL, room: EVIL, kind: "scene", icon: EVIL, flash: "fail", hold: true, allowed: true }),
      renderStatus({ label: EVIL, value: EVIL, detail: EVIL, level: "crit", icon: EVIL }),
      renderNotice({ icon: EVIL, title: EVIL, lines: [EVIL, EVIL, EVIL], tone: "warn" }),
      renderPair("K7Q-4PX"),
      renderHold(base, 0.5, "#3FB950"),
      renderHold(base, 1, "#3FB950"),
      renderToast(base, EVIL, EVIL, "crit"),
    ];
    for (const s of all) {
      wellFormed(s);
      assert.ok(!s.includes("<script"), "no markup from the server");
      assert.ok(!s.includes("\u202e"), "no bidi overrides");
      assert.match(s, /width="144" height="144"/);
    }
  });

  it("every action, as a key and as a dial, draws safely from hostile data", () => {
    const kinds: [ActionKind, string][] = [["control", "socket"], ["reading", "reading"], ["thermostat", "thermostat"], ["dimmer", "dimmer"], ["blinds", "cover"], ["scene", "scene"], ["status", "status"]];
    for (const [k, itemKind] of kinds) {
      const it = evilItem(itemKind);
      const hub = stubHub([it]);
      const key = new MockSurface("Keypad", "D");
      new ActionView(k, hub, key, { item: it.id, label: EVIL }).draw(true);
      wellFormed(key.svg);
      assert.ok(!key.svg.includes("<script"));
      const dial = new MockSurface("Encoder", "D");
      new ActionView(k, hub, dial, { item: it.id, label: EVIL }).draw(true);
      const fb = dial.feedbacks.at(-1)!;
      const layout = LAYOUTS[k === "scene" || k === "status" ? "control" : k]!;
      const keys = new Set(layout.items.map((x) => x.key));
      for (const [name, v] of Object.entries(fb)) {
        assert.ok(keys.has(name), k + ": feedback key " + name + " is in the layout");
        const val = typeof v === "object" && v !== null ? (v as { value?: unknown }).value : v;
        if (typeof val === "string" && val.startsWith("data:image/svg+xml")) {
          const svg = svgOf(val);
          wellFormed(svg);
          assert.ok(!svg.includes("<script"));
        }
      }
    }
  });

  it("notices on keys and dials for every phase", () => {
    for (const phase of ["setup", "unpaired", "pairing", "cert", "off", "revoked", "denied", "connecting", "offline"]) {
      const s = new MockSurface("Keypad", "D");
      new ActionView("control", stubHub([], phase), s, {}).draw(true);
      wellFormed(s.svg);
      const d = new MockSurface("Encoder", "D");
      new ActionView("thermostat", stubHub([], phase), d, {}).draw(true);
      for (const k of Object.keys(d.feedbacks.at(-1)!)) assert.ok(LAYOUTS.thermostat!.items.some((x) => x.key === k));
    }
  });

  it("escapes and fits text", () => {
    assert.equal(esc(`<a href="x">&'</a>`), "&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;");
    const f = fit("A very long name of a lamp in the living room", 16, 100);
    assert.ok(f.endsWith("…") && textWidth(f, 16) <= 100);
    assert.equal(fit("Short", 16, 100), "Short");
  });
});

describe("touch-strip layouts", () => {
  it("are the generated ones and valid against @elgato/schemas", () => {
    const Ajv = require("ajv");
    const schema = JSON.parse(readFileSync(require.resolve("@elgato/schemas/streamdeck/plugins/layout.json"), "utf8"));
    const ajv = new Ajv({ strict: false, allErrors: true });
    const validate = ajv.compile(schema);
    for (const [name, layout] of Object.entries(LAYOUTS)) {
      const file = JSON.parse(readFileSync(join(sd, "layouts", name + ".json"), "utf8"));
      assert.deepEqual(file, JSON.parse(JSON.stringify(layout)), name + ".json is up to date (run gen-assets)");
      assert.ok(validate(file), name + ": " + JSON.stringify(validate.errors));
      for (const it of layout.items) {
        const [x, y, w, h] = it.rect;
        assert.ok(x + w <= 200 && y + h <= 100, name + "/" + it.key + " fits the 200x100 strip");
      }
    }
  });

  it("the manifest names every layout, icon and inspector that exists", () => {
    const m = JSON.parse(readFileSync(join(sd, "manifest.json"), "utf8"));
    assert.equal(m.UUID, "com.zigmon.streamdeck");
    assert.equal(m.Version, "1.0.0.0");
    assert.equal(m.SDKVersion, 3);
    assert.equal(m.Nodejs.Version, "24");
    assert.equal(m.Actions.length, 7);
    for (const a of m.Actions) {
      readFileSync(join(sd, a.PropertyInspectorPath));
      readFileSync(join(sd, a.Icon + ".svg"));
      readFileSync(join(sd, a.States[0].Image + ".svg"));
      if (a.Encoder) {
        readFileSync(join(sd, a.Encoder.layout));
        readFileSync(join(sd, a.Encoder.Icon + ".svg"));
      }
    }
    readFileSync(join(sd, "imgs/plugin/marketplace.png"));
    readFileSync(join(sd, "imgs/plugin/marketplace@2x.png"));
  });
});
