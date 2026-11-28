/**
 * 1.3 (ZIGMon 5.59.4): the ten new actions - the protocol additions parsed strictly, which items
 * fit which action, what every press, turn and touch sends, Classic and every look drawn safely
 * and within the key, the colours, the 409 of the SMS keys, an older ZIGMon, and that the
 * summaries are asked for only of a ZIGMon that offers them.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import { CYCLE_SETTLE_MS } from "../src/core/views.js";
import { HOLD_MS } from "../src/core/hold.js";
import type { Command } from "../src/core/client.js";
import { Hub as RealHub, type CommandResult, type Hub } from "../src/core/hub.js";
import { NodeTransport } from "../src/core/http.js";
import { cleanRecipient, countdown, itemFor, NEW_KINDS, stepMinutes, type NewKind } from "../src/core/kinds.js";
import { LAYOUTS } from "../src/core/layouts.js";
import { ACCENTS, ALLOWED_COLOURS, P } from "../src/core/palette.js";
import { parseCatalog, parseHello, parseItem, parseState, type Item } from "../src/core/protocol.js";
import { FakeProtector } from "../src/core/secrets.js";
import { normalizeAction } from "../src/core/settings.js";
import { textWidth } from "../src/core/svg.js";
import { THEMES } from "../src/core/themes.js";
import { catalogMessage } from "../src/core/piapi.js";
import { ActionView, fits, type ActionKind } from "../src/core/views.js";
import { extendedItems, FakeZigmon, MemoryStore, MockSurface, sampleItems, until, type FakeItem } from "./fake-zigmon.js";
import { wellFormed } from "./xml.js";

const EVIL = '<script>alert(1)</script> & "q" \'s\' ‮]]>';
const NOW = Math.floor(Date.now() / 1000);
const cleanups: (() => unknown)[] = [];
after(async () => {
  for (const c of cleanups.reverse()) await c();
});

const raw = (): FakeItem[] => [...sampleItems(), ...extendedItems(NOW)];
const all = (): Item[] => raw().map((r) => parseItem(r));

/** One item's state patched (attrs merged), the rest as they are. */
function patched(id: string, patch: Record<string, unknown>, extra: Partial<FakeItem> = {}): Item[] {
  return raw().map((r) => {
    if (r.id !== id) return parseItem(r);
    const c = JSON.parse(JSON.stringify(r)) as FakeItem;
    const { attrs, ...rest } = patch as { attrs?: Record<string, unknown> };
    c.state = { ...c.state, ...rest, attrs: { ...(c.state.attrs as object), ...(attrs ?? {}) } };
    return parseItem({ ...c, ...extra });
  });
}

interface Sent extends Omit<Command, "deck"> { deck?: string }

function stubHub(items: Item[], o: { features?: string[]; sent?: Sent[]; answer?: (c: Sent) => CommandResult; resub?: () => void } = {}): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  const features = o.features ?? ["extended", "timer", "summaries-5.59.4"];
  const power = [400, 900, 1500, 2200, 1800, 1842];
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [1, 3, 2],
    series: (id: string) => (id === "house:power" ? power : null), supports: (f: string) => features.includes(f),
    deckIsApproved: () => true, resubscribe: o.resub ?? (() => undefined), retryNow: () => undefined,
    allItems: () => [...map.values()], allRooms: () => [],
    command: async (c: Sent) => {
      o.sent?.push(c);
      return o.answer ? o.answer(c) : { ok: true, said: "", state: null };
    },
  } as unknown as Hub;
}

function view(kind: ActionKind, items: Item[], settings: Record<string, unknown>, o: Parameters<typeof stubHub>[1] = {}, ctl: "Keypad" | "Encoder" = "Keypad") {
  const s = new MockSurface(ctl, "D");
  const v = new ActionView(kind, stubHub(items, o), s, settings);
  v.draw(true);
  cleanups.push(() => v.dispose());
  return { v, s };
}

/** The settings each new action is drawn with in these tests. */
const SETTINGS: Record<NewKind, Record<string, unknown>[]> = {
  power: [{}], security: [{}], heatgroup: [{}], away: [{}], openings: [{}], batteries: [{}], zigbee: [{}],
  timer: [{ item: "Lampa" }], room: [{ item: "room:r2" }], sms: [{ smsMode: "last" }, { smsMode: "compose", smsTo: ["group:Family"] }, { smsMode: "status" }],
};
const ID_OF = (k: NewKind, s: Record<string, unknown>) => itemFor(k, s)!;

/** On and off as each one has it (the off one quiet: nothing open, nothing low, at home...). */
const OFF: Record<string, Record<string, unknown>> = {
  "house:power": { value: 0, attrs: { power: 0 } }, "status:security": { value: 0, attrs: { alerts: 0 } }, "heat:group:all": { attrs: { calling: 0, mode: "eco" } },
  "house:away": {}, "house:openings": { value: 0, attrs: { open: 0, names: [], heating_loss: false } }, "house:batteries": { attrs: { below_20: 0, below_10: 0, lowest_pct: 60, level: "ok" } },
  "status:zigbee": { attrs: { offline_n: 0, level: "ok" } }, Lampa: { on: false }, "room:r2": { on: false, attrs: { calling: false } }, "sms:last": { attrs: { unread: 0 } },
  "sms:compose": {}, "status:sms": {},
};
const ON: Record<string, Record<string, unknown>> = {
  "house:openings": { attrs: { heating_loss: false } },
  "house:away": { on: true, attrs: { away: true } }, Lampa: { on: true, attrs: { off_at: NOW + 754 } }, "status:sms": { attrs: { muted_until: NOW + 3600 } },
  "sms:compose": { attrs: { unread: 3 } },
};
const variants = (id: string): [string, Item[]][] => [
  ["on", patched(id, ON[id] ?? {})], ["off", patched(id, OFF[id] ?? {})], ["offline", patched(id, { online: false })],
  ["evil", patched(id, { value_text: EVIL, attrs: { names: [EVIL, EVIL], lowest_name: EVIL, dropped_name: EVIL, last_from: EVIL, last_person: EVIL, latest: EVIL } }, { name: EVIL, room: EVIL })],
  ["locked", patched(id, {}, { allowed: false, act: { ack: { cap: "system", allowed: false, hold: true }, mute: { cap: "system", allowed: false, hold: true }, unmute: { cap: "system", allowed: false, hold: true } } })],
];

const svgOf = (uri: string) => Buffer.from(uri.split(",")[1] ?? "", "base64").toString("utf8");
const texts = (svg: string) => [...svg.matchAll(/<text\b[^>]*>(.*?)<\/text>/gs)].map((m) => m[1]!.replace(/<[^>]+>/g, ""));

function ownColours(svg: string, where: string, extra: string[] = []): void {
  for (const m of svg.matchAll(/(?:fill|stroke|stop-color|color)="([^"]*)"/g)) {
    const c = m[1]!;
    if (c === "none" || /^url\(#[A-Za-z0-9_-]+\)$/.test(c)) continue;
    assert.ok(ALLOWED_COLOURS.has(c.toUpperCase()) || extra.includes(c.toUpperCase()), where + ": a colour not from our table: " + c);
  }
}

/**
 * No text runs off the key: every <text> outside a transformed group, measured as svg.ts measures it
 * (its tspan unit included), lies within the 144 px key, give or take `tol`.
 */
function withinKey(svg: string, where: string, tol = 3): void {
  // pieces of text inside a transformed group are placed by the transform: leave them out
  const flat = svg.replace(/<g [^>]*transform="[^"]*"[^>]*>(?:(?!<\/g>).)*?<text[\s\S]*?<\/g>/g, "");
  for (const m of flat.matchAll(/<text ([^>]*)>(.*?)<\/text>/gs)) {
    const a = m[1]!;
    const num = (k: string) => Number(new RegExp(`(?:^| )${k}="([\\d.-]+)"`).exec(a)?.[1] ?? NaN);
    const x = num("x"), size = num("font-size"), weight = num("font-weight") || 600;
    if (!Number.isFinite(x) || !Number.isFinite(size)) continue;
    const anchor = /text-anchor="(\w+)"/.exec(a)?.[1] ?? "start";
    const body = m[2]!;
    const main = body.replace(/<tspan[\s\S]*$/, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
    let w = textWidth(main, size, weight);
    for (const t of body.matchAll(/<tspan[^>]*font-size="([\d.]+)"[^>]*>(.*?)<\/tspan>/g)) w += textWidth(t[2]!, Number(t[1]), 600) + 4;
    const spacing = Number(/letter-spacing="([\d.-]+)"/.exec(a)?.[1] ?? 0);
    w += spacing * [...main].length;
    const left = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
    assert.ok(left >= -tol && left + w <= 144 + tol, `${where}: "${main}" runs off the key (${Math.round(left)}..${Math.round(left + w)})`);
  }
}

// ------------------------------------------------------------------ parsing

describe("1.3 protocol: the additions of ZIGMon 5.59.4, strictly", () => {
  const hello = {
    ok: true, api: 1, server: "zigmon", version: "5.59.4", house: "H", boot: 1, seq: 1, install: { id: "0123456789abcdef0123456789abcdef", name: "PC", caps: { sms: { on: true, all: true, targets: [] } } },
    decks: [], features: ["extended", "timer", "summaries-5.59.4", "BAD feature", 7, "x".repeat(80), "extended"],
  };

  it("hello: features read and cleaned; none from an older ZIGMon; the sms capability", () => {
    const h = parseHello(hello);
    assert.deepEqual(h.features, ["extended", "timer", "summaries-5.59.4"]);
    assert.deepEqual(parseHello({ ...hello, features: undefined }).features, []);
    assert.deepEqual(parseHello({ ...hello, features: "extended" }).features, []);
    assert.equal(parseHello({ ...hello, features: Array.from({ length: 40 }, (_, i) => "f" + i) }).features.length, 16);
    assert.equal(h.install.caps.sms?.on, true);
  });

  it("every summary item parses with its kind, actions, act and members", () => {
    const c = parseCatalog({ ok: true, boot: 1, seq: 1, items: raw() });
    const by = new Map(c.items.map((i) => [i.id, i]));
    for (const [id, kind] of [["house:power", "power"], ["status:security", "security"], ["heat:group:all", "heatgroup"], ["house:away", "away"], ["house:openings", "openings"],
      ["house:batteries", "batteries"], ["status:zigbee", "zigbee"], ["room:r2", "room"], ["status:sms", "sms"], ["sms:last", "sms"], ["sms:compose", "sms"]]) {
      assert.equal(by.get(id!)?.kind, kind, id);
    }
    assert.deepEqual(by.get("status:security")!.actions, ["ack"]);
    assert.deepEqual(by.get("status:security")!.act, { ack: { cap: "system", allowed: true, hold: true } });
    assert.deepEqual(by.get("status:sms")!.actions, ["mute", "unmute"]);
    assert.equal(by.get("sms:last")!.cap, "sms");
    assert.deepEqual(by.get("room:r2")!.members, ["Lampa", "zb:0xa1:state_l1", "zb:0xc3:trv", "read:0xe5:temperature", "Garage"]);
    assert.deepEqual(by.get("house:openings")!.state.attrs.names, ["Okno ložnice", "Balkónové dveře"]);
  });

  it("act, members, names and long texts are validated and capped", () => {
    const it = parseItem({
      id: "x", name: "X", kind: "security", cap: "status", actions: ["ack", "explode", "timer"],
      act: { ack: { cap: "system", allowed: 1, hold: true }, bogus: { cap: "system" }, mute: { cap: "root", allowed: true }, unmute: "yes" },
      members: ["a", "a", 5, "", "b\u0000c", ...Array.from({ length: 300 }, (_, i) => "m" + i)],
      state: { attrs: { names: ["ok", 5, null, "y".repeat(90), "a", "b", "c", "d", "e"], latest: "z".repeat(300), last_text: "w".repeat(300), other: "v".repeat(300), nested: { a: 1 } } },
    });
    assert.deepEqual(it.actions, ["ack", "timer"]);
    assert.deepEqual(it.act, { ack: { cap: "system", allowed: false, hold: true } });
    assert.ok(it.members!.length <= 200 && it.members![0] === "a" && it.members!.filter((m) => m === "a").length === 1);
    assert.ok(!it.members!.some((m) => /\u0000/.test(m) || m === ""));
    const names = it.state.attrs.names as string[];
    assert.ok(names.length <= 6 && names.every((n) => typeof n === "string" && [...n].length <= 40));
    assert.equal([...(it.state.attrs.latest as string)].length, 120);
    assert.equal([...(it.state.attrs.last_text as string)].length, 80);
    assert.equal([...(it.state.attrs.other as string)].length, 60);
    assert.equal(it.state.attrs.nested, null);
    assert.equal(parseItem({ id: "y", act: [1, 2] }).act, undefined);
    // members that are not a list make the item malformed (a catalogue drops it, as with actions)
    assert.throws(() => parseItem({ id: "y", members: "a,b" }));
    assert.throws(() => parseItem({ id: "y", members: { a: 1 } }));
    assert.equal(parseCatalog({ ok: true, boot: 1, seq: 1, items: [{ id: "y", members: "a,b" }, { id: "z" }] }).items.length, 1);
  });

  it("a switch's off_at reads like any number; text never carries markup through", () => {
    const st = parseState({ on: true, attrs: { off_at: 1795875978, names: [EVIL] } });
    assert.equal(st.attrs.off_at, 1795875978);
    assert.ok(!(st.attrs.names as string[])[0]!.includes("‮"));
  });
});

// ------------------------------------------------------------------ fits, settings, little sums

describe("1.3 fits, settings and the small sums", () => {
  it("each new action is offered exactly its items; Control is not offered the summaries", () => {
    const items = all();
    const want: Record<NewKind, string[]> = {
      power: ["house:power"], security: ["status:security"], heatgroup: ["heat:group:all"], away: ["house:away"], openings: ["house:openings"], batteries: ["house:batteries"],
      zigbee: ["status:zigbee"], timer: ["Lampa", "zb:0xa1:state_l1", "Garage"], room: ["room:r2"], sms: ["status:sms", "sms:last", "sms:compose"],
    };
    for (const k of NEW_KINDS) assert.deepEqual(items.filter((i) => fits(k, i)).map((i) => i.id).sort(), [...want[k]].sort(), k);
    const control = items.filter((i) => fits("control", i)).map((i) => i.id);
    for (const id of ["status:security", "heat:group:all", "room:r2", "sms:last", "status:sms", "house:power"]) assert.ok(!control.includes(id), id);
    assert.ok(control.includes("house:away"), "Away is a switch: Control may toggle it");
  });

  it("settings: minutes 1-720, Away's switches, SMS mode, recipients and the hush", () => {
    const s = normalizeAction({ minutes: 45, awayOff: ["Lampa", "Lampa", 5, "", "x".repeat(200)], smsMode: "compose", smsTo: ["+420 777 123 456", "group:Family", "group:", "contact:c_5f2a9e", "<b>", "12"], muteMinutes: 60, press: "timer" });
    assert.equal(s.minutes, 45);
    assert.deepEqual(s.awayOff, ["Lampa"]);
    assert.equal(s.smsMode, "compose");
    assert.deepEqual(s.smsTo, ["+420777123456", "group:Family", "contact:c_5f2a9e"]);
    assert.equal(s.muteMinutes, 60);
    assert.equal(s.press, "timer");
    for (const bad of [0, 721, 1.5, "x"]) assert.equal(normalizeAction({ minutes: bad }).minutes, undefined, String(bad));
    assert.equal(normalizeAction({ muteMinutes: 61 }).muteMinutes, undefined);
    assert.equal(normalizeAction({ smsMode: "spam" }).smsMode, undefined);
    assert.equal(normalizeAction({ smsTo: Array.from({ length: 40 }, (_, i) => "+42077712" + String(i).padStart(4, "0")) }).smsTo!.length, 20);
    assert.equal(cleanRecipient("group:a,b"), null);
  });

  it("the ladder of minutes, the countdown, and the item each action shows", () => {
    assert.equal(stepMinutes(30, 1), 40);
    assert.equal(stepMinutes(30, -1), 25);
    assert.equal(stepMinutes(7, 1), 10);
    assert.equal(stepMinutes(7, -1), 5);
    assert.equal(stepMinutes(720, 5), 720);
    assert.equal(stepMinutes(1, -3), 1);
    assert.equal(countdown(754), "12:34");
    assert.equal(countdown(3723), "1:02:03");
    assert.equal(itemFor("power", { item: "other" }), "house:power");
    assert.equal(itemFor("sms", {}), "sms:last");
    assert.equal(itemFor("sms", { smsMode: "status" }), "status:sms");
    assert.equal(itemFor("timer", { item: "Lampa" }), "Lampa");
  });
});

// ------------------------------------------------------------------ drawing

describe("1.3 keys: Classic and every look, every state", () => {
  it("valid SVG, our colours, escaped text, nothing off the key - Classic strictly, every look", () => {
    let n = 0;
    for (const k of NEW_KINDS) {
      for (const s of SETTINGS[k]) {
        for (const [st, items] of variants(ID_OF(k, s))) {
          for (const t of THEMES) {
            for (const info of [{}, { showName: false, showDetail: false }, { nameFit: "wrap", label: "Light-Loznice-Main-Long" }]) {
              const where = `${t.id}/${k}/${JSON.stringify(s)}/${st}/${JSON.stringify(info)}`;
              const { s: key } = view(k, items, { ...s, ...info, theme: t.id === "classic" ? undefined : t.id, label: st === "evil" ? EVIL : (info as { label?: string }).label });
              wellFormed(key.svg);
              assert.match(key.svg, /width="144" height="144"/, where);
              assert.ok(!key.svg.includes("<script") && !key.svg.includes("‮"), where + ": server text unescaped");
              ownColours(key.svg, where);
              if (t.id === "classic") withinKey(key.svg, where);
              if (st === "offline" && (info as { showState?: boolean }).showState !== false) assert.match(key.svg, /Offline|OFFLINE/, where);
              n++;
            }
          }
        }
      }
    }
    assert.ok(n > 6000, "drawn " + n);
  });

  it("the clear looks keep the big words inside the key too", () => {
    for (const k of NEW_KINDS) {
      for (const s of SETTINGS[k]) {
        for (const [st, items] of variants(ID_OF(k, s)).slice(0, 3)) {
          for (const t of ["huge", "pill", "tile", "bars", "aurora", "outline", "mono", "pastel", "button", "spot"]) {
            withinKey(view(k, items, { ...s, theme: t }).s.svg, `${t}/${k}/${st}`, 8);
          }
        }
      }
    }
  });

  it("lit and unlit differ in every look; the inspector's pictures and words are there", () => {
    for (const k of NEW_KINDS) {
      for (const s of SETTINGS[k]) {
        const id = ID_OF(k, s);
        for (const t of THEMES) {
          const on = view(k, patched(id, ON[id] ?? {}), { ...s, theme: t.id === "classic" ? undefined : t.id }).s.svg;
          const off = view(k, patched(id, OFF[id] ?? {}), { ...s, theme: t.id === "classic" ? undefined : t.id }).s.svg;
          assert.notEqual(on, off, `${t.id}/${k}/${id}`);
        }
        const p = view(k, all(), s).v.previewSet()!;
        assert.equal(p.themes.length, THEMES.length);
        assert.notEqual(p.on, p.off, k);
        assert.equal(p.words.length, 2);
      }
    }
  });

  it("the On colour and the Off colour, by name or the user's own, in Classic and every look", () => {
    for (const k of NEW_KINDS) {
      for (const s of SETTINGS[k]) {
        const id = ID_OF(k, s);
        for (const t of THEMES) {
          const theme = t.id === "classic" ? undefined : t.id;
          const on = view(k, patched(id, ON[id] ?? {}), { ...s, theme, accent: "rose", accentOff: "#12AB34" }).s.svg;
          const off = view(k, patched(id, OFF[id] ?? {}), { ...s, theme, accent: "rose", accentOff: "#12AB34" }).s.svg;
          // (High contrast is black and white only, as for every action)
          if (t.id !== "contrast") assert.ok(on.includes(ACCENTS.rose!.colour), `${t.id}/${k}/${id}: the On colour`);
          assert.ok(off.includes("#12AB34"), `${t.id}/${k}/${id}: the Off colour`);
          assert.ok(!on.includes("#12AB34") || k === "room" || k === "sms" || k === "openings", `${t.id}/${k}/${id}: no Off colour on a lit key`);
          ownColours(off, `${t.id}/${k}`, ["#12AB34"]);
          ownColours(on, `${t.id}/${k}`, ["#12AB34"]);
        }
        // a bad colour is dropped, the key drawn as with none
        assert.equal(view(k, all(), { ...s, accent: "#12345G" }).s.svg, view(k, all(), s).s.svg);
      }
    }
  });

  it("each piece switched off disappears; icon only shows the icon", () => {
    for (const k of NEW_KINDS) {
      for (const s of SETTINGS[k]) {
        const id = ID_OF(k, s);
        for (const t of THEMES) {
          const theme = t.id === "classic" ? undefined : t.id;
          const named = view(k, all(), { ...s, theme, label: "Distinct label" }).s.svg;
          assert.match(named, /Distinct|label/, `${t.id}/${k}: the label`);
          const none = view(k, all(), { ...s, theme, label: "Distinct label", showName: false }).s.svg;
          assert.ok(!none.includes("Distinct"), `${t.id}/${k}: the name hidden`);
          const only = view(k, all(), { ...s, theme, label: "Distinct label", showName: false, showRoom: false, showState: false, showDetail: false, showMode: false, showGraph: false }).s.svg;
          assert.ok(!/Distinct/.test(only), `${t.id}/${k}: icon only`);
          assert.ok(only.includes("<g transform"), `${t.id}/${k}/${id}: the icon is there`);
        }
      }
    }
  });

  it("an unread count is a badge in every look", () => {
    for (const t of THEMES) {
      const svg = view("sms", patched("sms:last", { attrs: { unread: 7 } }), { theme: t.id === "classic" ? undefined : t.id }).s.svg;
      assert.ok(texts(svg).includes("7"), t.id + ": the unread count");
    }
  });

  it("what matters is said: the numbers, the names, the modes", () => {
    const words = (k: ActionKind, items: Item[], s: Record<string, unknown> = {}) => texts(view(k, items, s).s.svg).join(" | ");
    assert.match(words("power", all()), /1\.84.*kW|kW/);
    assert.match(words("power", all()), /12\.4 kWh/);
    assert.match(words("security", all()), /2.*alerts/);
    assert.match(words("security", patched("status:security", OFF["status:security"]!)), /Quiet/);
    assert.match(words("heatgroup", all()), /1\/4/);
    assert.match(words("heatgroup", all()), /Mixed/);
    assert.match(words("heatgroup", patched("heat:group:all", { attrs: { mode: "comfort" } })), /Comfort/);
    assert.match(words("heatgroup", all()), /18\.5–21\.0°/);
    assert.match(words("away", all()), /Home/);
    assert.match(words("away", patched("house:away", ON["house:away"]!)), /Away/);
    assert.match(words("openings", all()), /Okno ložnice/);
    assert.match(words("batteries", all()), /Dveře 5 %/);
    assert.match(words("zigbee", all()), /Hlavice dropped/);
    assert.match(words("timer", patched("Lampa", { on: true, attrs: { off_at: Math.floor(Date.now() / 1000) + 754 } }), { item: "Lampa" }), /12:3[234]/);
    assert.match(words("timer", patched("Lampa", { on: false }), { item: "Lampa", minutes: 45 }), /45/);
    assert.match(words("room", all(), { item: "room:r2" }), /20\.5/);
    assert.match(words("room", all(), { item: "room:r2" }), /Comfort → 21°/);
    assert.match(words("sms", all()), /Jana Nováková/);
    assert.match(words("sms", all(), { smsMode: "compose", smsTo: ["group:Family", "+420777123456"] }), /to Family, …456/);
    assert.match(words("sms", patched("status:sms", ON["status:sms"]!), { smsMode: "status" }), /Muted/);
    // heat escaping: red
    assert.ok(view("openings", all(), {}).s.svg.includes(P.crit));
    assert.ok(!view("openings", patched("house:openings", { attrs: { heating_loss: false } }), { accent: "teal" }).s.svg.includes(P.crit));
  });
});

// ------------------------------------------------------------------ the strips

describe("1.3 dials: their own strips", () => {
  const LAYOUT: Record<NewKind, string> = { power: "power", security: "summary", heatgroup: "summary", away: "summary", openings: "summary", batteries: "summary", zigbee: "summary", timer: "timer", room: "room", sms: "summary" };
  it("only the layout's keys, valid pictures, our colours - in Classic and every look, every state", () => {
    for (const k of NEW_KINDS) {
      const keys = new Set(LAYOUTS[LAYOUT[k]]!.items.map((x) => x.key));
      for (const s of SETTINGS[k]) {
        for (const [st, items] of variants(ID_OF(k, s))) {
          for (const t of THEMES) {
            const { s: dial } = view(k, items, { ...s, theme: t.id === "classic" ? undefined : t.id }, {}, "Encoder");
            const fb = dial.feedbacks.at(-1)!;
            for (const [name, v] of Object.entries(fb)) {
              assert.ok(keys.has(name), `${k}/${t.id}: ${name} is in the layout`);
              const val = typeof v === "object" && v !== null ? (v as { value?: unknown; color?: string }).value : v;
              const col = typeof v === "object" && v !== null ? (v as { color?: string }).color : undefined;
              if (col) assert.ok(ALLOWED_COLOURS.has(col.toUpperCase()), `${k}/${t.id}/${st}: ${name} colour ${col}`);
              if (typeof val === "string" && val.startsWith("data:image/svg+xml")) {
                const svg = svgOf(val);
                wellFormed(svg);
                ownColours(svg, `${k}/${t.id}/${st}/${name}`);
                assert.ok(!svg.includes("<script"));
              } else if (typeof val === "string") assert.ok(!val.includes("‮"));
            }
          }
        }
      }
    }
  });

  it("the layouts fit the strip and are the generated ones' shape", () => {
    for (const name of ["power", "summary", "timer", "room"]) {
      for (const it of LAYOUTS[name]!.items) {
        const [x, y, w, h] = it.rect;
        assert.ok(x >= 0 && y >= 0 && x + w <= 200 && y + h <= 100, name + "/" + it.key);
      }
    }
  });

  it("the strips say it: power's span, the timer's minutes, the room's member", () => {
    const val = (fb: Record<string, unknown>, k: string) => (fb[k] as { value: string }).value;
    const p = view("power", all(), {}, {}, "Encoder");
    assert.equal(val(p.s.feedbacks.at(-1)!, "span"), "24 h");
    p.v.rotate(1);
    assert.equal(val(p.s.feedbacks.at(-1)!, "span"), "7 d");
    const t = view("timer", patched("Lampa", { on: false }), { item: "Lampa" }, {}, "Encoder");
    assert.equal(val(t.s.feedbacks.at(-1)!, "value"), "30 min");
    t.v.rotate(2);
    assert.equal(val(t.s.feedbacks.at(-1)!, "value"), "45 min");
    const r = view("room", all(), { item: "room:r2" }, {}, "Encoder");
    assert.equal(val(r.s.feedbacks.at(-1)!, "name"), "Lampa obývák");
    assert.match(val(r.s.feedbacks.at(-1)!, "top"), /Ložnice · 20\.5 °C · 48 %/);
    r.v.rotate(1);
    assert.equal(val(r.s.feedbacks.at(-1)!, "name"), "Kitchen light");
    r.v.rotate(-2);
    assert.equal(val(r.s.feedbacks.at(-1)!, "name"), "Garage door relay");
    assert.deepEqual(r.v.ids(), ["room:r2", "Garage"], "the dial watches the member it shows");
  });
});

// ------------------------------------------------------------------ what presses, turns and touches send

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A press held for `ms` (a hold fires on its own once HOLD_MS has passed). */
async function press(v: ActionView, ms = 0, dial = false): Promise<void> {
  if (dial) v.dialDown();
  else v.keyDown();
  if (ms) await tick(ms);
  if (dial) v.dialUp();
  else v.keyUp();
  await tick(30);
}

describe("1.3 commands", () => {
  it("the summaries that only tell send nothing; a press asks again", async () => {
    for (const k of ["power", "openings", "batteries", "zigbee"] as const) {
      const sent: Sent[] = [];
      let asked = 0;
      const { v, s } = view(k, all(), {}, { sent, resub: () => asked++ });
      await press(v);
      v.touch(false);
      assert.equal(sent.length, 0, k);
      assert.ok(asked >= 2, k + ": refreshed");
      assert.equal(s.oks, 0, k + ": (1.3) never the green tick over the key");
    }
    const sent: Sent[] = [];
    const r = view("room", all(), { item: "room:r2" }, { sent });
    await press(r.v);
    assert.equal(sent.length, 0, "a Room key only looks");
  });

  it("House power: a turn steps the span the graph is asked for", () => {
    const { v } = view("power", all(), {}, {}, "Encoder");
    assert.deepEqual(v.series(), [{ id: "house:power", span: 86400 }]);
    v.rotate(-1);
    assert.deepEqual(v.series(), [{ id: "house:power", span: 21600 }]);
    v.rotate(-5);
    assert.deepEqual(v.series(), [{ id: "house:power", span: 3600 }]);
    assert.deepEqual(view("power", all(), { span: 604800 }).v.series(), [{ id: "house:power", span: 604800 }]);
    assert.deepEqual(view("power", all(), { showGraph: false }).v.series(), []);
  });

  it("Network security: a held press acknowledges; a short one does not; without System, none", async () => {
    const sent: Sent[] = [];
    const { v } = view("security", all(), {}, { sent });
    await press(v, 200);
    assert.equal(sent.length, 0, "a short press");
    await press(v, HOLD_MS + 150);
    assert.equal(sent.length, 1);
    assert.equal(sent[0]!.id, "status:security");
    assert.equal(sent[0]!.action, "ack");
    assert.ok(sent[0]!.held_ms! >= HOLD_MS);
    const none: Sent[] = [];
    const locked = patched("status:security", {}, { act: { ack: { cap: "system", allowed: false, hold: true } } });
    const l = view("security", locked, {}, { sent: none });
    await press(l.v);
    assert.equal(none.length, 0);
    assert.match(l.s.svg, /Not allowed/);
    assert.match(l.s.svg, /System/);
  });

  it("Network security: acknowledged with nothing standing (the flag nothing) says no alert", async () => {
    const { v, s } = view("security", all(), {}, { answer: () => ({ ok: false, why: "nothing", message: "there is no alert standing" }) });
    await press(v, HOLD_MS + 150);
    await tick(400);
    assert.match(s.svg, /No alert/);
  });

  it("Heating: Next mode steps at once and is sent once it stops; one mode for all at once; the dial steps", async () => {
    const sent: Sent[] = [];
    const { v, s } = view("heatgroup", all(), {}, { sent });
    await press(v);
    await press(v);
    assert.equal(sent.length, 0, "not yet");
    assert.match(s.svg, /Comfort/, "shown at once: from Mixed, Plan, then Comfort");
    await tick(CYCLE_SETTLE_MS + 100);
    assert.deepEqual(sent.map((c) => [c.id, c.action, c.attr, c.value]), [["heat:group:all", "set", "mode", "comfort"]]);
    const set: Sent[] = [];
    const e = view("heatgroup", all(), { press: "set:eco" }, { sent: set });
    await press(e.v);
    assert.deepEqual(set.map((c) => [c.action, c.attr, c.value]), [["set", "mode", "eco"]]);
    const dial: Sent[] = [];
    const d = view("heatgroup", patched("heat:group:all", { attrs: { mode: "eco" } }), {}, { sent: dial }, "Encoder");
    d.v.rotate(2);
    await tick(CYCLE_SETTLE_MS + 100);
    assert.deepEqual(dial.map((c) => c.value), ["max"]);
    const held: Sent[] = [];
    const h = view("heatgroup", patched("heat:group:all", {}, { hold: true }), {}, { sent: held });
    await press(h.v, HOLD_MS + 150);
    assert.deepEqual(held.map((c) => [c.value, (c.held_ms ?? 0) >= HOLD_MS]), [["plan", true]], "held: each confirmed press is sent");
  });

  it("Away: toggles, then switches off the chosen ones it may, each by its own command", async () => {
    const sent: Sent[] = [];
    const items = patched("zb:0xa1:state_l1", {}, { allowed: false });
    const { v, s } = view("away", items, { awayOff: ["Lampa", "zb:0xa1:state_l1", "nope"] }, {
      sent, answer: (c) => ({ ok: true, said: "", state: c.id === "house:away" ? parseItem({ id: "house:away", state: { on: true, attrs: { away: true } } }).state : null }),
    });
    await press(v);
    await tick(80);
    assert.deepEqual(sent.map((c) => [c.id, c.action]), [["house:away", "toggle"], ["Lampa", "off"]]);
    assert.match(s.svg, /Away/);
    // coming home turns nothing on
    const back: Sent[] = [];
    const h = view("away", patched("house:away", ON["house:away"]!), { awayOff: ["Lampa"] }, { sent: back, answer: () => ({ ok: true, said: "", state: parseItem({ id: "house:away", state: { on: false, attrs: { away: false } } }).state }) });
    await press(h.v);
    await tick(80);
    assert.deepEqual(back.map((c) => [c.id, c.action]), [["house:away", "toggle"]]);
    // a chosen switch that needs a hold makes going away need one; its own command carries the time held
    const held: Sent[] = [];
    const g = view("away", all(), { awayOff: ["Garage"] }, { sent: held, answer: (c) => ({ ok: true, said: "", state: c.id === "house:away" ? parseItem({ id: "house:away", state: { on: true, attrs: { away: true } } }).state : null }) });
    await press(g.v, 200);
    assert.equal(held.length, 0, "a short press");
    await press(g.v, HOLD_MS + 150);
    await tick(80);
    assert.deepEqual(held.map((c) => [c.id, c.action, (c.held_ms ?? 0) >= HOLD_MS]), [["house:away", "toggle", true], ["Garage", "off", true]]);
  });

  it("Timer: on for the minutes, again turns it off; the dial sets the minutes and its push starts; By hand", async () => {
    const sent: Sent[] = [];
    const { v } = view("timer", patched("Lampa", { on: false }), { item: "Lampa", minutes: 15 }, { sent });
    await press(v);
    assert.deepEqual(sent.map((c) => [c.id, c.action, c.minutes]), [["Lampa", "timer", 15]]);
    const off: Sent[] = [];
    const r = view("timer", patched("Lampa", ON.Lampa!), { item: "Lampa" }, { sent: off });
    await press(r.v);
    assert.deepEqual(off.map((c) => [c.id, c.action]), [["Lampa", "off"]]);
    const d: Sent[] = [];
    const dial = view("timer", patched("Lampa", { on: false }), { item: "Lampa" }, { sent: d }, "Encoder");
    dial.v.rotate(3);
    await press(dial.v, 0, true);
    dial.v.touch(false);
    await tick(30);
    assert.deepEqual(d.map((c) => c.minutes), [60, 60]);
    const bh: Sent[] = [];
    await press(view("timer", patched("Lampa", { on: false }), { item: "Lampa", byHand: true }, { sent: bh }).v);
    assert.deepEqual(bh.map((c) => [c.action, c.minutes, c.by_hand]), [["timer", 30, true]]);
    // a switch that needs a hold: the timer too
    const g: Sent[] = [];
    const gv = view("timer", all(), { item: "Garage" }, { sent: g });
    await press(gv.v, 200);
    assert.equal(g.length, 0);
    await press(gv.v, HOLD_MS + 150);
    assert.deepEqual(g.map((c) => [c.action, (c.held_ms ?? 0) >= HOLD_MS]), [["timer", true]]);
  });

  it("Timer: counts down on the key every second", async () => {
    const { s } = view("timer", patched("Lampa", { on: true, attrs: { off_at: NOW + 120 } }), { item: "Lampa" });
    const before = s.images.length;
    await tick(1150);
    assert.ok(s.images.length > before, "redrawn as the seconds go");
  });

  it("Control: a Timer press, when the switch has one", async () => {
    const sent: Sent[] = [];
    const items = all().map((i) => (i.id === "Lampa" ? { ...i, actions: [...i.actions, "timer" as const] } : i));
    const { v } = view("control", items, { item: "Lampa", press: "timer", minutes: 120 }, { sent });
    await press(v);
    assert.deepEqual(sent.map((c) => [c.action, c.minutes]), [["timer", 120]]);
    // a switch without the action (an older catalogue): the press does what it always did
    const old: Sent[] = [];
    await press(view("control", all(), { item: "Lampa", press: "timer" }, { sent: old }).v);
    assert.deepEqual(old.map((c) => c.action), ["toggle"]);
  });

  it("Room: the dial scrolls the members and a push switches the one shown, by its own rules", async () => {
    const sent: Sent[] = [];
    const { v, s } = view("room", all(), { item: "room:r2" }, { sent }, "Encoder");
    await press(v, 0, true);
    assert.deepEqual(sent.map((c) => [c.id, c.action]), [["Lampa", "toggle"]]);
    v.rotate(2);
    await press(v, 0, true);
    assert.equal(sent.length, 1, "a thermostat has nothing to push");
    assert.match(JSON.stringify(s.feedbacks.at(-1)), /Nothing here/);
    v.rotate(2);
    await press(v, 200, true);
    assert.equal(sent.length, 1, "Garage needs a hold");
    await press(v, HOLD_MS + 150, true);
    assert.deepEqual(sent.at(-1)!.id, "Garage");
    assert.ok(sent.at(-1)!.held_ms! >= HOLD_MS);
    const locked = all().map((i) => (i.id === "Lampa" ? { ...i, allowed: false } : i));
    const none: Sent[] = [];
    await press(view("room", locked, { item: "room:r2" }, { sent: none }, "Encoder").v, 0, true);
    assert.equal(none.length, 0);
  });

  it("SMS: Show latest and Write new ask the desktop app; Status mutes and unmutes, held", async () => {
    const sent: Sent[] = [];
    await press(view("sms", all(), {}, { sent }).v);
    await press(view("sms", all(), { smsMode: "compose" }, { sent }).v);
    await press(view("sms", all(), { smsMode: "compose", smsTo: ["group:Family", "+420777123456"] }, { sent }).v);
    assert.deepEqual(sent.map((c) => [c.id, c.action, c.to]), [["sms:last", "run", undefined], ["sms:compose", "run", undefined], ["sms:compose", "run", ["group:Family", "+420777123456"]]]);
    const m: Sent[] = [];
    const st = view("sms", all(), { smsMode: "status", muteMinutes: 120 }, { sent: m });
    await press(st.v, 200);
    assert.equal(m.length, 0, "held: a short press does nothing");
    await press(st.v, HOLD_MS + 150);
    assert.deepEqual(m.map((c) => [c.id, c.action, c.minutes]), [["status:sms", "mute", 120]]);
    const u: Sent[] = [];
    await press(view("sms", patched("status:sms", ON["status:sms"]!), { smsMode: "status" }, { sent: u }).v, HOLD_MS + 150);
    assert.deepEqual(u.map((c) => [c.action, c.minutes]), [["unmute", undefined]]);
  });

  it("SMS: 409 - no desktop app linked is running - says so on the key and the strip", async () => {
    const answer = (): CommandResult => ({ ok: false, why: "noapp", message: "no desktop app linked to this Stream Deck is running" });
    const k = view("sms", all(), {}, { answer });
    await press(k.v);
    await tick(20);
    assert.match(texts(k.s.svg).join(" "), /Desktop app not.*running/);
    assert.match(texts(k.s.svg).join(" "), /link one in ZIGMon/);
    assert.ok(k.s.alerts >= 1);
    const d = view("sms", all(), { smsMode: "compose" }, { answer }, "Encoder");
    await press(d.v, 0, true);
    await tick(20);
    assert.match(JSON.stringify(d.s.feedbacks.at(-1)), /Desktop app not running/);
  });
});

// ------------------------------------------------------------------ an older ZIGMon

describe("1.3 with a ZIGMon before 5.59.4", () => {
  it("every new action says it needs 5.59.4 - key, strip and inspector - and sends nothing", async () => {
    for (const k of NEW_KINDS) {
      const sent: Sent[] = [];
      const s = SETTINGS[k][0]!;
      const { v, s: key } = view(k, all(), s, { features: [], sent });
      assert.match(texts(key.svg).join(" "), /Needs ZIGMon.*5\.59\.4/, k);
      await press(v);
      v.touch(false);
      v.rotate(1);
      assert.equal(sent.length, 0, k);
      const dial = view(k, all(), s, { features: [] }, "Encoder");
      assert.match(JSON.stringify(dial.s.feedbacks.at(-1)), /5\.59\.4/, k);
      assert.equal(v.previewSet(), null);
      assert.equal(v.facts(), null);
    }
    // the Timer also needs "timer"
    assert.match(view("timer", all(), { item: "Lampa" }, { features: ["extended"] }).s.svg, /5\.59\.4/);
    // the old actions do not care
    assert.doesNotMatch(view("control", all(), { item: "Lampa" }, { features: [] }).s.svg, /5\.59\.4/);
  });
});

// ------------------------------------------------------------------ the inspector

describe("1.3 inspector", () => {
  it("Now: every window open, the whole latest alert, the room's items", () => {
    const f = (k: ActionKind, s: Record<string, unknown> = {}) => view(k, all(), s).v.facts()!;
    assert.deepEqual(f("openings").filter((r) => r[0] === "·").map((r) => r[1]), ["Okno ložnice", "Balkónové dveře"]);
    assert.match(f("security").find((r) => r[0] === "Latest alert")![1], /Suricata/);
    assert.deepEqual(f("room", { item: "room:r2" }).filter((r) => r[0] === "·").map((r) => r[1]), ["Lampa obývák", "Kitchen light", "Bedroom radiator", "Outdoor temperature", "Garage door relay"]);
    for (const k of NEW_KINDS) assert.ok(f(k, SETTINGS[k][0]).length > 0, k);
  });

  it("Away's choices: what can be switched off, with its lock or hand", () => {
    const m = catalogMessage(stubHub(all()), "away");
    const ids = (m.extras as { id: string }[]).map((x) => x.id);
    assert.ok(ids.includes("Lampa") && ids.includes("Garage") && ids.includes("zb:0xb2:light"));
    assert.ok(!ids.includes("house:away") && !ids.includes("rule:7") && !ids.includes("scene:3"));
    assert.equal(catalogMessage(stubHub(all()), "control").extras, undefined);
    const sec = (catalogMessage(stubHub(all()), "security").items as { id: string; act?: unknown }[])[0]!;
    assert.deepEqual(sec.act, { ack: { cap: "system", allowed: true, hold: true } });
  });
});

// ------------------------------------------------------------------ end to end: asked only when offered

describe("1.3 end to end against a fake ZIGMon", () => {
  async function connect(features: string[]) {
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
  }

  it("an older ZIGMon is never asked for the summaries: plain GETs, no new items, and the new keys say so", async () => {
    const { fake, hub } = await connect([]);
    const s = new MockSurface("Keypad", "D1");
    const v = new ActionView("power", hub, s, {});
    hub.watch(v);
    cleanups.push(() => v.dispose());
    await until(() => fake.asked.some((a) => a.do === "wait"), 3000, "a wait");
    v.draw(true);
    assert.ok(fake.asked.every((a) => !a.extended), JSON.stringify(fake.asked));
    assert.ok(fake.asked.filter((a) => a.do === "catalog" || a.do === "wait").every((a) => a.method === "GET"));
    assert.equal(hub.item("house:power"), undefined);
    assert.equal(hub.supports("extended"), false);
    assert.match(s.svg, /5\.59\.4/);
    assert.deepEqual(hub.status().features, []);
  });

  it("a 5.59.4 is asked by POST with extended: catalogue, state, wait; acts, timers and the 409 of SMS", async () => {
    const { fake, hub } = await connect(["extended", "timer", "summaries-5.59.4"]);
    const s = new MockSurface("Keypad", "D1");
    const v = new ActionView("security", hub, s, {});
    hub.watch(v);
    cleanups.push(() => v.dispose());
    await until(() => fake.asked.some((a) => a.do === "wait" && a.extended), 3000, "an extended wait");
    for (const a of fake.asked.filter((x) => x.do === "catalog" || x.do === "wait" || x.do === "state")) assert.ok(a.extended && a.method === "POST", JSON.stringify(a));
    assert.ok(hub.item("house:power") && hub.item("room:r2")?.members?.length === 5);
    assert.ok(hub.item("Lampa")!.actions.includes("timer"));
    assert.deepEqual(hub.status().features, ["extended", "timer", "summaries-5.59.4"]);
    // a summary changing reaches the key through the extended wait
    fake.setState("status:security", { value: 5, attrs: { alerts: 5 } });
    await until(() => texts(s.svg).some((t) => t.startsWith("5")), 3000, "the new count");
    // acknowledge: held, under system
    const r0 = await hub.command({ deck: "D1", id: "status:security", action: "ack" });
    assert.equal(r0.ok, false);
    assert.equal(!r0.ok && r0.why, "hold");
    const r1 = await hub.command({ deck: "D1", id: "status:security", action: "ack", held_ms: 1600 });
    assert.ok(r1.ok);
    // a timer
    const r2 = await hub.command({ deck: "D1", id: "Lampa", action: "timer", minutes: 30 });
    assert.ok(r2.ok && typeof r2.state?.attrs.off_at === "number");
    // SMS: no desktop app linked is running
    const r3 = await hub.command({ deck: "D1", id: "sms:last", action: "run" });
    assert.equal(!r3.ok && r3.why, "noapp");
    fake.desktopApp = true;
    assert.ok((await hub.command({ deck: "D1", id: "sms:compose", action: "run", to: ["group:Family"] })).ok);
    assert.deepEqual(fake.commands.at(-1)!.to, ["group:Family"]);
    // system not granted: only that action is refused, the item is still seen
    fake.extended.find((i) => i.id === "status:sms")!.act = { mute: { cap: "system", allowed: false, hold: true }, unmute: { cap: "system", allowed: false, hold: true } };
    const r4 = await hub.command({ deck: "D1", id: "status:sms", action: "mute", minutes: 60, held_ms: 1600 });
    assert.equal(!r4.ok && r4.why, "denied");
    assert.equal(hub.item("status:sms")!.allowed, true);
    assert.equal(hub.item("status:sms")!.act!.mute!.allowed, false);
  });
});
