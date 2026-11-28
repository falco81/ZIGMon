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
import { ActionView, CYCLE_SETTLE_MS, fits, type ActionKind } from "../src/core/views.js";
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

describe("(1.3) a thermostat heats when it says so", () => {
  function head(running: string): Item {
    const r = JSON.parse(JSON.stringify(sampleItems().find((i) => (i.state.attrs as Record<string, unknown>)?.running_state !== undefined)!)) as Record<string, unknown> & { state: { attrs: Record<string, unknown> } };
    r.state.attrs.running_state = running;
    return parseItem(r);
  }
  it("a head with a set point but idle does not heat; one running heat does", () => {
    assert.equal(key("thermostat", head("idle"), {}).v.thermoModel().heating, false);
    assert.equal(key("thermostat", head("heat"), {}).v.thermoModel().heating, true);
  });
  it("a room heats when it calls for heat", () => {
    const calling = (c: boolean) => {
      const r = room("comfort");
      return parseItem({ ...JSON.parse(JSON.stringify(r)), state: { on: null, value: 21, value_text: "21 °C", attrs: { mode: "comfort", target: 22, temperature: 21, calling: c } } });
    };
    assert.equal(key("thermostat", calling(true), {}).v.thermoModel().heating, true);
    assert.equal(key("thermostat", calling(false), {}).v.thermoModel().heating, false);
  });
});

describe("(1.3) a scene's state, on its keys and on a Reading", () => {
  function scene(on: boolean | null, actions = ["run", "toggle", "on", "off"]): Item {
    return parseItem({
      id: "scene:9", name: "Movie night", room: "Obývák", kind: "scene", icon: "scene", cap: "scenes", actions, attrs: [], allowed: true, hold: false,
      state: { on, value: null, value_text: on === null ? null : on ? "on" : "off", attrs: { members: 3, as_set: on ? 3 : 1 }, online: true },
    });
  }
  it("a Scene key draws on and off differently, and as before when ZIGMon says nothing", () => {
    const on = key("scene", scene(true), {}).s.images.at(-1);
    const off = key("scene", scene(false), {}).s.images.at(-1);
    const old = key("scene", scene(null, ["run"]), {}).s.images.at(-1);
    assert.notEqual(on, off);
    assert.equal(off, old, "an off scene is not drawn as 1.2 drew a scene");
    for (const t of THEMES.slice(1)) {
      const a = key("scene", scene(true), { theme: t.id }).v.face();
      assert.equal(a.state, "On", t.id);
      assert.equal(a.active, true, t.id);
    }
  });
  it("a press runs it unless Toggle / On / Off is chosen; Control on a scene runs it too unless chosen", async () => {
    const sent: Sent[] = [];
    for (const [kind, press] of [["scene", undefined], ["scene", "toggle"], ["scene", "off"], ["control", undefined], ["control", "toggle"]] as const) {
      const k = key(kind, scene(true), press ? { press } : {}, sent);
      k.v.keyDown();
      k.v.keyUp();
    }
    await until(() => sent.length >= 5, 3000, "five commands");
    assert.deepEqual(sent.map((c) => c.action), ["run", "toggle", "off", "run", "toggle"]);
  });
  it("a Reading takes a scene and says its state and how much is as it leaves it", () => {
    const m = key("reading", scene(true), {}).v.readingModel();
    assert.equal(m.value, "On");
    assert.equal(m.note, "3/3 as set");
    assert.equal(fits("reading", scene(true)), true, "a Reading does not offer a scene");
    assert.equal(key("reading", scene(false), {}).v.readingModel().value, "Off");
    const img = key("reading", scene(false), {}).s.svg;
    assert.ok(img.includes("1/3 as set"), "the Classic Reading does not say it");
  });
});

describe("(1.3) a lock of an ESP32 gateway", () => {
  function lockItem(value: "locked" | "unlocked"): Item {
    return parseItem({
      id: "esp:a1b2c3d4e5f6:yeelock.front", name: "Front drawer", room: null, kind: "lock", icon: "lock", cap: "locks",
      actions: ["open", "unlock", "lock", "refresh"], attrs: [], allowed: true, hold: true,
      state: { on: value === "unlocked", value: null, value_text: value, attrs: { battery: 87 }, online: true, battery: 87 },
    });
  }
  it("is read with its own cap, kind and actions, and drawn locked or unlocked", () => {
    const it0 = lockItem("locked");
    assert.equal(it0.cap, "locks");
    assert.equal(it0.kind, "lock");
    assert.deepEqual(it0.actions, ["open", "unlock", "lock", "refresh"]);
    assert.notEqual(key("control", lockItem("locked"), {}).s.svg, key("control", lockItem("unlocked"), {}).s.svg);
  });
  it("a press sends the chosen action, held as ZIGMon asks", async () => {
    const sent: Sent[] = [];
    const k = key("control", lockItem("locked"), { press: "unlock" }, sent);
    assert.equal(k.v.face().hold, true);
    k.v.keyDown();
    await sleep(1700);
    k.v.keyUp();
    await until(() => sent.length >= 1, 3000, "the unlock");
    assert.equal(sent[0]!.action, "unlock");
  });
});

describe("(1.3) Next mode goes round only the chosen ones", () => {
  it("the ring", async () => {
    const { nextInRing } = await import("../src/core/views.js");
    const all = ["plan", "comfort", "eco", "night", "max", "off", "manual"];
    assert.equal(nextInRing(all, "comfort"), "eco", "with nothing chosen it is as before");
    assert.equal(nextInRing(all, "comfort", "comfort,max,off"), "max");
    assert.equal(nextInRing(all, "max", "comfort,max,off"), "off");
    assert.equal(nextInRing(all, "off", "comfort,max,off"), "comfort");
    assert.equal(nextInRing(all, "eco", "comfort,max,off"), "max", "from one not chosen: the next chosen after it");
    assert.equal(nextInRing(all, "", "comfort,max"), "comfort");
    assert.equal(nextInRing(all, "plan", "nonsense"), "comfort", "nothing of the item's chosen: all of them");
    assert.equal(nextInRing(all, "max", "max"), "max");
  });
  it("is kept clean", () => {
    assert.equal(normalizeAction({ cycleOnly: "comfort, max,off,max" }).cycleOnly, "comfort,max,off");
    assert.equal(normalizeAction({ cycleOnly: "a b,<x>" }).cycleOnly, undefined);
    assert.equal(normalizeAction({ cycleOnly: 3 }).cycleOnly, undefined);
  });
  it("a room key presses round the chosen modes, sent once it stops", async () => {
    const sent: Sent[] = [];
    const k = key("thermostat", room("comfort"), { press: "mode", cycleOnly: "comfort,max,off" }, sent);
    for (let n = 0; n < 2; n++) {
      k.v.keyDown();
      k.v.keyUp();
    }
    await sleep(CYCLE_SETTLE_MS + 400);
    assert.equal(sent.at(-1)?.value, "off", "comfort -> max -> off");
  });
});
