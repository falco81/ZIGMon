/**
 * (1.2) "By hand" on a switch's key, and "Next mode" pressed round to a mode.
 * Every check here fails on 1.1.0.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import type { Hub } from "../src/core/hub.js";
import { parseItem, parseState, type Item } from "../src/core/protocol.js";
import { normalizeAction } from "../src/core/settings.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, CYCLE_SETTLE_MS, type ActionKind } from "../src/core/views.js";
import { MockSurface, sampleItems, until } from "./fake-zigmon.js";

const cleanups: (() => unknown)[] = [];
after(async () => {
  for (const c of cleanups.reverse()) await c();
});

interface Sent { id: string; action: string; attr?: string; value?: unknown; by_hand?: boolean }
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function stubHub(items: Item[], sent: Sent[]): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [], series: () => null,
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
    command: async (c: Sent) => {
      sent.push(c);
      return { ok: true, said: "", state: null };
    },
  } as unknown as Hub;
}

function key(kind: ActionKind, item: Item, settings: Record<string, unknown>, sent: Sent[] = []): { v: ActionView; s: MockSurface } {
  const s = new MockSurface("Keypad", "D");
  const v = new ActionView(kind, stubHub([item], sent), s, { item: item.id, ...settings });
  v.draw(true);
  cleanups.push(() => v.dispose());
  return { v, s };
}

function lamp(held: boolean): Item {
  const r = JSON.parse(JSON.stringify(sampleItems().find((i) => i.id === "Lampa")!)) as Record<string, unknown> & { state: Record<string, unknown> };
  r.state.held = held;
  return parseItem(r);
}

function room(mode: string): Item {
  return parseItem({
    id: "heat:room:r2", name: "Heating in Loznice", room: "Loznice", kind: "thermostat", icon: "heat", cap: "climate", actions: ["set", "toggle", "on", "off"],
    allowed: true, hold: false,
    attrs: [{ key: "mode", label: "Mode", type: "enum", values: ["plan", "comfort", "eco", "night", "max", "off", "manual"] }],
    state: { on: true, value: null, value_text: mode, attrs: { mode, level: mode, temperature: 24.6, target: 5, why: mode, by_hand: false } },
  });
}

describe("By hand", () => {
  it("is a setting of its own, kept", () => {
    assert.equal(normalizeAction({ byHand: true }).byHand, true);
    assert.equal(normalizeAction({ byHand: "yes" }).byHand, undefined);
  });

  it("a press of a key set to By hand says so; one not set to it does not", async () => {
    const sent: Sent[] = [];
    const a = key("control", lamp(false), { byHand: true, press: "toggle" }, sent);
    a.v.keyDown();
    a.v.keyUp();
    const b = key("control", lamp(false), { press: "on" }, sent);
    b.v.keyDown();
    b.v.keyUp();
    await until(() => sent.length >= 2, 2000, "two commands");
    assert.deepEqual(sent[0], { deck: "D", id: "Lampa", action: "toggle", by_hand: true });
    assert.deepEqual(sent[1], { deck: "D", id: "Lampa", action: "on" });
  });

  it("(1.3) the Light action has it too: its press says so, and its key shows it taken over", async () => {
    const sent: Sent[] = [];
    const a = key("dimmer", lamp(false), { byHand: true }, sent);
    a.v.keyDown();
    a.v.keyUp();
    const b = key("dimmer", lamp(false), {}, sent);
    b.v.keyDown();
    b.v.keyUp();
    await until(() => sent.length >= 2, 2000, "two commands");
    assert.equal(sent[0]!.by_hand, true);
    assert.equal(sent[1]!.by_hand, undefined);
    const plain = key("dimmer", lamp(false), {}).s.images.at(-1);
    const held = key("dimmer", lamp(true), {}).s.images.at(-1);
    assert.notEqual(plain, held, "the Classic Light key does not show it is taken over");
  });

  it("ZIGMon's word that it is taken over is read and drawn in every look", () => {
    assert.equal(parseState({ held: true }).held, true);
    assert.equal(parseState({ held: "yes" }).held, false);
    assert.equal(parseState({}).held, false);
    for (const t of THEMES) {
      const free = key("control", lamp(false), { theme: t.id }).s.svg;
      const held = key("control", lamp(true), { theme: t.id }).s.svg;
      assert.notEqual(free, held, t.id + ": taken over looks the same as not");
    }
  });
});

describe("Next mode pressed round", () => {
  it("steps on the key at once and sends only the mode it stops on", async () => {
    const sent: Sent[] = [];
    const k = key("thermostat", room("off"), { press: "mode" }, sent);
    for (let i = 0; i < 4; i++) {          // off -> manual -> plan -> comfort -> eco
      k.v.keyDown();
      k.v.keyUp();
      await sleep(150);
    }
    assert.ok(k.s.svg.includes("Eco"), "the key does not show where the presses got to");
    assert.deepEqual(sent, [], "a mode was sent on the way round");
    await until(() => sent.length >= 1, CYCLE_SETTLE_MS + 2000, "the mode stopped on");
    await sleep(200);
    assert.deepEqual(sent, [{ deck: "D", id: "heat:room:r2", action: "set", attr: "mode", value: "eco" }]);
  });

  it("a key held to confirm still sends each confirmed press", async () => {
    const sent: Sent[] = [];
    const k = key("thermostat", room("off"), { press: "mode", hold: true }, sent);
    k.v.keyDown();
    await sleep(1700);
    k.v.keyUp();
    await until(() => sent.length >= 1, 1000, "the confirmed press");
    assert.equal(sent[0]!.value, "manual");
  });

  it("a mode set outright is sent at once", async () => {
    const sent: Sent[] = [];
    const k = key("thermostat", room("off"), { press: "set:max" }, sent);
    k.v.keyDown();
    k.v.keyUp();
    await until(() => sent.length >= 1, 500, "set:max at once");
    assert.equal(sent[0]!.value, "max");
  });
});
