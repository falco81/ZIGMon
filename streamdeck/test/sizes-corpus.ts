/**
 * (1.3) The corpus the text sizes are checked on: every action, on every item it takes, in a few
 * states, in every look, with a few of the other settings - drawn on a key and on a dial.
 */
import { createHash } from "node:crypto";
import type { Hub } from "../src/core/hub.js";
import { NEW_KINDS } from "../src/core/kinds.js";
import { parseItem, type Item } from "../src/core/protocol.js";
import { THEMES } from "../src/core/themes.js";
import { ActionView, fits, type ActionKind } from "../src/core/views.js";
import * as fake from "./fake-zigmon.js";
import { extendedItems, MockSurface, sampleItems, type FakeItem } from "./fake-zigmon.js";

/** A fixed clock, so a countdown draws the same every time. */
export const CORPUS_NOW = 1_800_000_000;

export function corpusHub(items: Item[], defaults?: (kind: string) => Record<string, number> | null): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [1, 3, 2, 5, 4],
    series: (id: string) => (id === "house:power" ? [400, 900, 1500, 2200, 1800, 1842] : null), supports: () => true,
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined, allItems: () => [...map.values()], allRooms: () => [],
    command: async () => ({ ok: true, said: "", state: null }),
    ...(defaults ? { textDefaults: defaults } : {}),
  } as unknown as Hub;
}

export const CORPUS_KINDS: ActionKind[] = ["control", "reading", "thermostat", "dimmer", "blinds", "scene", "status", ...NEW_KINDS, "computed" as unknown as ActionKind];

/** The other settings each key is drawn with. */
export const CORPUS_SETTINGS: Record<string, unknown>[] = [
  {}, { showName: false, showDetail: false }, { nameFit: "wrap", label: "Light-Loznice-Main-Long" }, { accent: "#12AB34", accentOff: "coral", showGraph: true, showScale: true },
];

/** The new actions' own choices (their item comes from these). */
const OWN: Partial<Record<ActionKind, Record<string, unknown>[]>> = {
  sms: [{ smsMode: "last" }, { smsMode: "compose", smsTo: ["group:Family"] }, { smsMode: "status" }],
  timer: [{ item: "Lampa", minutes: 15 }],
};

function raws(): FakeItem[] {
  // (and the computed values, where the fake ZIGMon has them)
  const calc = (fake as unknown as { calcItems?: () => FakeItem[] }).calcItems?.() ?? [];
  return [...sampleItems(), ...extendedItems(CORPUS_NOW), ...calc];
}

function variantOf(r: FakeItem, v: string): Item {
  const c = JSON.parse(JSON.stringify(r)) as FakeItem & { state: Record<string, unknown> };
  if (v === "offline") c.state.online = false;
  if (v === "locked") c.allowed = false;
  if (v === "hold") c.hold = true;
  if (v === "flip" && typeof c.state.on === "boolean") c.state.on = !c.state.on;
  return parseItem(c);
}

export interface CorpusCase { name: string; kind: ActionKind; items: Item[]; settings: Record<string, unknown>; theme: string }

/** Every case: the kind, the items the hub knows, the key's settings (the look among them). */
export function* corpus(themes: readonly string[] = THEMES.map((t) => t.id), settingsList = CORPUS_SETTINGS, variants = ["as-is", "offline", "locked", "hold", "flip"]): Generator<CorpusCase> {
  const base = raws();
  for (const kind of CORPUS_KINDS) {
    const owns = OWN[kind] ?? ((NEW_KINDS as readonly string[]).includes(kind) ? [{}] : null);
    const targets: Record<string, unknown>[] = owns ?? base.map((r) => parseItem(r)).filter((i) => fits(kind, i)).map((i) => ({ item: i.id }));
    for (const own of targets) {
      for (const v of variants) {
        const items = base.map((r) => variantOf(r, v));
        for (const theme of themes) {
          for (const [si, s] of settingsList.entries()) {
            yield { name: `${kind}/${JSON.stringify(own)}/${v}/${theme}/${si}`, kind, items, settings: { ...own, ...s, ...(theme === "classic" ? {} : { theme }) }, theme };
          }
        }
      }
    }
  }
}

/** The key's SVG and the dial's feedback for one case, with extra settings on top. */
export function drawCase(c: CorpusCase, extra: Record<string, unknown> = {}, defaults?: (kind: string) => Record<string, number> | null): { svg: string; feedback: string } {
  const realNow = Date.now;
  Date.now = () => CORPUS_NOW * 1000;
  try {
    const hub = corpusHub(c.items, defaults);
    const key = new MockSurface("Keypad", "D");
    const kv = new ActionView(c.kind, hub, key, { ...c.settings, ...extra });
    kv.draw(true);
    kv.dispose();
    const dial = new MockSurface("Encoder", "D");
    const dv = new ActionView(c.kind, hub, dial, { ...c.settings, ...extra });
    dv.draw(true);
    dv.dispose();
    return { svg: key.svg, feedback: JSON.stringify(dial.feedbacks.at(-1)) };
  } finally {
    Date.now = realNow;
  }
}

export function hashCase(c: CorpusCase, extra: Record<string, unknown> = {}, defaults?: (kind: string) => Record<string, number> | null): string {
  const d = drawCase(c, extra, defaults);
  return createHash("sha256").update(d.svg).update("\n").update(d.feedback).digest("hex");
}
