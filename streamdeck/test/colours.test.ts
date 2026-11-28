/**
 * 1.3: more named colours, a colour of the user's own (#RRGGBB), and an Off colour beside the
 * On one - in every look, in Classic and on the touch strip; unset, nothing changes.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import type { Hub } from "../src/core/hub.js";
import { cleanHex, hexToHsv, hsvToHex } from "../src/core/colour.js";
import { ACCENTS, ALLOWED_COLOURS, colourOf, P, X } from "../src/core/palette.js";
import { parseItem, type Item } from "../src/core/protocol.js";
import { ACCENT_IDS, normalizeAction } from "../src/core/settings.js";
import { thermoFeedback } from "../src/core/strip.js";
import { ALL_INFO, THEMES } from "../src/core/themes.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { MockSurface, sampleItems } from "./fake-zigmon.js";
import { wellFormed } from "./xml.js";

const ON = "#12AB34";
const OFF = "#C0FFEE";

const cleanups: (() => unknown)[] = [];
after(() => {
  for (const c of cleanups.reverse()) c();
});

function stubHub(items: Item[]): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [1, 3, 2, 5, 4], series: () => null,
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
    command: async () => ({ ok: true, said: "", state: null }),
  } as unknown as Hub;
}

/** A sample item switched on, off (a blind closed, a thermostat idle) or offline. */
function variant(id: string, v: "on" | "off" | "offline"): Item {
  const r = JSON.parse(JSON.stringify(sampleItems().find((i) => i.id === id)!)) as Record<string, unknown> & { state: Record<string, unknown> };
  const a = (r.state.attrs ?? {}) as Record<string, unknown>;
  if (v === "on") {
    r.state.on = true;
    if ("position" in a) {
      a.position = 100;
      r.state.value = 100;
    }
  }
  if (v === "off") {
    r.state.on = false;
    if (a.running_state) a.running_state = "idle";
    if ("position" in a) {
      a.position = 0;
      r.state.value = 0;
    }
  }
  if (v === "offline") r.state.online = false;
  return parseItem(r);
}

function draw(kind: ActionKind, item: Item, settings: Record<string, unknown>, ctl: "Keypad" | "Encoder" = "Keypad"): MockSurface {
  const s = new MockSurface(ctl, "D");
  const v = new ActionView(kind, stubHub([item]), s, { item: item.id, ...settings });
  v.draw(true);
  cleanups.push(() => v.dispose());
  return s;
}

const svgOf = (uri: string) => Buffer.from(uri.split(",")[1] ?? "", "base64").toString("utf8");

/** Every colour drawn is ours - or one the user set in this key's own settings, and nothing else. */
function ownColours(svg: string, where: string, mine: string[]): void {
  const allowed = new Set(mine.map((c) => c.toUpperCase()));
  for (const m of svg.matchAll(/(?:fill|stroke|stop-color|color)="([^"]*)"/g)) {
    const c = m[1]!;
    if (c === "none" || /^url\(#[A-Za-z0-9_-]+\)$/.test(c)) continue;
    assert.ok(ALLOWED_COLOURS.has(c.toUpperCase()) || allowed.has(c.toUpperCase()), where + ": a colour not from our table nor the user's: " + c);
  }
}

/** The pictures and colours of a strip's feedback, as one string to look through. */
function stripText(fb: Record<string, unknown>): string {
  return Object.values(fb).map((v) => {
    if (typeof v === "string") return v.startsWith("data:image/svg+xml") ? svgOf(v) : v;
    const o = v as { value?: unknown; color?: string };
    return (typeof o.value === "string" && o.value.startsWith("data:image/svg+xml") ? svgOf(o.value) : "") + " color=" + (o.color ?? "");
  }).join("\n");
}

const SWITCHED: [ActionKind, string][] = [["control", "Lampa"], ["dimmer", "zb:0xb2:light"], ["thermostat", "zb:0xc3:trv"], ["blinds", "zb:0xd4:cover"]];

describe("colours (1.3)", () => {
  it("about two dozen named colours; the first ten exactly as 1.1 had them; the settings know each", () => {
    assert.deepEqual([...ACCENT_IDS], Object.keys(ACCENTS));
    assert.ok(ACCENT_IDS.length >= 22 && ACCENT_IDS.length <= 28, String(ACCENT_IDS.length));
    const first: Record<string, string> = {
      blue: P.info, green: P.ok, amber: P.warn, red: P.crit, purple: P.purple, orange: P.orange, teal: P.water, pink: P.pink, yellow: X.yellow, silver: X.silver,
    };
    assert.deepEqual(Object.keys(ACCENTS).slice(0, 10), Object.keys(first));
    for (const [id, c] of Object.entries(first)) assert.equal(ACCENTS[id]!.colour, c, id);
    const colours = Object.values(ACCENTS).map((a) => a.colour.toUpperCase());
    assert.equal(new Set(colours).size, colours.length, "no two the same");
    assert.equal(new Set(Object.values(ACCENTS).map((a) => a.name)).size, colours.length, "no two names the same");
    for (const c of colours) {
      assert.match(c, /^#[0-9A-F]{6}$/);
      assert.ok(ALLOWED_COLOURS.has(c), c + " is drawable");
    }
  });

  it("normalizeAction: a name, or exactly #RRGGBB (uppercased) - for the On and the Off colour alike", () => {
    for (const id of ACCENT_IDS) assert.deepEqual(normalizeAction({ accent: id, accentOff: id }), { accent: id, accentOff: id }, id);
    assert.deepEqual(normalizeAction({ accent: "#a1b2c3", accentOff: "#00ff7F" }), { accent: "#A1B2C3", accentOff: "#00FF7F" });
    for (const bad of ["#abc", "#ABCDEF0", "ABCDEF", "#ABCDEG", " #ABCDEF", "#ABCDEF ", "#ABCDEF\n", "rgb(1,2,3)", "url(#x)", "#ABCDEF;fill:red", "Blue", "constructor", "__proto__",
      "toString", 0xabcdef, true, null, ["#ABCDEF"], { c: "#ABCDEF" }, ""]) {
      assert.deepEqual(normalizeAction({ accent: bad, accentOff: bad }), {}, JSON.stringify(bad));
    }
    assert.deepEqual(normalizeAction({ accentOff: "#ffffff" }), { accentOff: "#FFFFFF" }, "an Off colour without an On one");
    assert.equal(colourOf("constructor"), undefined);
    assert.equal(colourOf("#abcdef"), "#ABCDEF");
    assert.equal(colourOf("coral"), ACCENTS.coral!.colour);
  });

  it("the picker's sums: hue, saturation and value to #RRGGBB and back", () => {
    assert.equal(hsvToHex({ h: 0, s: 1, v: 1 }), "#FF0000");
    assert.equal(hsvToHex({ h: 120, s: 1, v: 1 }), "#00FF00");
    assert.equal(hsvToHex({ h: 240, s: 1, v: 0.5 }), "#000080");
    assert.equal(hsvToHex({ h: 360, s: 0, v: 1 }), "#FFFFFF");
    assert.equal(hsvToHex({ h: -30, s: 2, v: -1 }), "#000000", "out of range is clamped");
    for (const c of [...Object.values(ACCENTS).map((a) => a.colour), "#000000", "#7F7F7F", "#0A0B0C", "#FEDCBA"]) {
      assert.equal(hsvToHex(hexToHsv(c)), c.toUpperCase(), c);
      assert.equal(cleanHex(hsvToHex(hexToHsv(c))), c.toUpperCase());
    }
    assert.equal(hexToHsv("#808080", 200).h, 200, "a grey keeps the hue it was given");
  });

  it("an Off colour shows in every look (and Classic) when the key is off, and never when it is on", () => {
    for (const t of THEMES) {
      for (const [kind, id] of SWITCHED) {
        const where = `${t.id}/${kind}`;
        // the sample radiator always reads as heating (its setpoint's name says "heating"), so it is
        // switched on and off as the inspector's preview does it
        const pair = (settings: Record<string, unknown>) => {
          const s = new MockSurface("Keypad", "D");
          const v = new ActionView(kind, stubHub([variant(id, "on")]), s, { item: id, ...settings });
          cleanups.push(() => v.dispose());
          const p = v.previewSet()!;
          return { on: svgOf(p.on), off: svgOf(p.off) };
        };
        const drawn = (v: "on" | "off", settings: Record<string, unknown>) => kind === "thermostat" ? pair(settings)[v] : draw(kind, variant(id, v), settings).svg;
        const off = drawn("off", { theme: t.id, accent: ON, accentOff: OFF });
        wellFormed(off);
        ownColours(off, where + "/off", [ON, OFF]);
        assert.ok(off.includes(OFF), where + ": the Off colour on an off key");
        const on = drawn("on", { theme: t.id, accent: ON, accentOff: OFF });
        ownColours(on, where + "/on", [ON, OFF]);
        assert.ok(!on.includes(OFF), where + ": no Off colour on an on key");
        // (High contrast is black and white only; Classic draws a blind wide open, and still, without its colour - as 1.0 did)
        if (t.id !== "contrast" && !(t.id === "classic" && kind === "blinds")) assert.ok(on.includes(ON), where + ": the On colour on an on key");
        if (t.id !== "classic") {
          assert.equal(on, drawn("on", { theme: t.id, accent: ON }), where + ": on, the Off colour changes nothing");
        }
        // offline stays offline: red, not the Off colour
        assert.ok(!draw(kind, variant(id, "offline"), { theme: t.id, accentOff: OFF }).svg.includes(OFF), where + ": offline");
      }
      // a named Off colour too
      assert.ok(draw("control", variant("Lampa", "off"), { theme: t.id, accentOff: "coral" }).svg.includes(ACCENTS.coral!.colour), t.id + ": a named Off colour");
    }
  });

  it("unset, or set to something not allowed, the keys draw exactly as before", () => {
    for (const t of THEMES) {
      for (const [kind, id] of [...SWITCHED, ["reading", "read:0xe5:temperature"], ["scene", "scene:3"], ["status", "status:alerts"]] as [ActionKind, string][]) {
        for (const v of ["on", "off", "offline"] as const) {
          const base = draw(kind, variant(id, v), { theme: t.id }).svg;
          for (const bad of ["#12345", "#GGGGGG", "url(#x)", "Coral"]) {
            assert.equal(draw(kind, variant(id, v), { theme: t.id, accentOff: bad, accent: bad }).svg, base, `${t.id}/${kind}/${v}: ${bad}`);
          }
        }
      }
    }
  });

  it("a colour of the user's own passes the colour check - and only that one", () => {
    for (const t of THEMES) {
      for (const [kind, id] of [...SWITCHED, ["reading", "read:0xe5:temperature"], ["scene", "scene:3"], ["status", "status:alerts"]] as [ActionKind, string][]) {
        for (const v of ["on", "off"] as const) {
          const svg = draw(kind, variant(id, v), { theme: t.id, accent: "#abcdef", accentOff: "#fedcba" }).svg;
          ownColours(svg, `${t.id}/${kind}/${v}`, ["#ABCDEF", "#FEDCBA"]);
          assert.ok(!svg.includes("#abcdef") && !svg.includes("#fedcba"), "kept uppercased");
          if (/#ABCDEF|#FEDCBA/.test(svg)) {
            assert.throws(() => ownColours(svg.replace(/#ABCDEF|#FEDCBA/g, "#ABCDEE"), "x", ["#ABCDEF", "#FEDCBA"]), /not from our table/,
              "a colour that is neither ours nor the user's fails the check");
          }
        }
      }
    }
  });

  it("the touch strip takes the Off colour where its layout allows; unset, it is as before", () => {
    // the radiator idle and heating (the sample one always reads as heating)
    const idle = { name: "R", current: 20, target: 21, unit: "°C", mode: "", heating: false, min: 5, max: 30, online: true, hold: false, allowed: true, history: [1, 2, 3] };
    const plainIdle = thermoFeedback(idle, undefined, ALL_INFO);
    assert.deepEqual(thermoFeedback(idle, undefined, ALL_INFO, undefined), plainIdle);
    assert.ok(stripText(thermoFeedback(idle, undefined, ALL_INFO, OFF)).includes(OFF));
    assert.ok(!stripText(thermoFeedback({ ...idle, heating: true }, undefined, ALL_INFO, OFF)).includes(OFF));
    for (const t of THEMES) {
      for (const [kind, id] of SWITCHED.filter(([k]) => k !== "thermostat")) {
        const where = `${t.id}/${kind}`;
        const off = draw(kind, variant(id, "off"), { theme: t.id, accentOff: OFF }, "Encoder").feedbacks.at(-1)!;
        const s = stripText(off);
        ownColours(s, where, [OFF]);
        assert.ok(s.includes(OFF), where + ": the Off colour on the strip");
        const on = stripText(draw(kind, variant(id, "on"), { theme: t.id, accentOff: OFF }, "Encoder").feedbacks.at(-1)!);
        assert.ok(!on.includes(OFF), where + ": none when on");
        const plain = draw(kind, variant(id, "off"), { theme: t.id }, "Encoder").feedbacks.at(-1)!;
        assert.equal(JSON.stringify(draw(kind, variant(id, "off"), { theme: t.id, accentOff: "nope" }, "Encoder").feedbacks.at(-1)!), JSON.stringify(plain), where);
      }
    }
  });

  it("the inspector's preview shows the Off colour on its Off picture", () => {
    const s = new MockSurface("Keypad", "D");
    const v = new ActionView("control", stubHub([variant("Lampa", "on")]), s, { item: "Lampa", theme: "pill", accent: ON, accentOff: OFF });
    cleanups.push(() => v.dispose());
    const p = v.previewSet()!;
    assert.ok(svgOf(p.off).includes(OFF) && !svgOf(p.on).includes(OFF));
    assert.ok(svgOf(p.on).includes(ON));
  });
});
