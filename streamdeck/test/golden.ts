/**
 * The 1.0.0 look, pinned: every action drawn for the sample items in every state with the
 * settings 1.0.0 knew. classic-golden.json holds the SHA-256 of each drawing as 1.0.0 made it;
 * the Classic look of later versions must draw exactly the same for the same settings.
 */
import { createHash } from "node:crypto";
import type { Hub } from "../src/core/hub.js";
import { parseItem, type Item } from "../src/core/protocol.js";
import { ActionView, fits, type ActionKind } from "../src/core/views.js";
import { MockSurface, sampleItems } from "./fake-zigmon.js";

export function goldenHub(items: Item[]): Hub {
  const map = new Map(items.map((i) => [i.id, i]));
  return {
    currentPhase: "online", pairCode: null, currentMessage: "",
    item: (id: string) => map.get(id), state: (id: string) => map.get(id)?.state, history: () => [1, 3, 2, 5, 4],
    deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined, command: async () => ({ ok: true, said: "", state: null }),
  } as unknown as Hub;
}

const KINDS: ActionKind[] = ["control", "reading", "thermostat", "dimmer", "blinds", "scene", "status"];
const OLD_SETTINGS: Record<string, unknown>[] = [{}, { showRoom: false }, { label: "Custom" }, { decimals: 1, warnAbove: 5, critAbove: 1000 }, { press: "on", step: 5 }];

export function goldenCases(): { name: string; hash: string }[] {
  const out: { name: string; hash: string }[] = [];
  for (const raw of sampleItems()) {
    for (const variant of ["as-is", "offline", "locked", "hold"]) {
      const r = JSON.parse(JSON.stringify(raw)) as Record<string, unknown> & { state: Record<string, unknown> };
      if (variant === "offline") r.state.online = false;
      if (variant === "locked") r.allowed = false;
      if (variant === "hold") r.hold = true;
      const it = parseItem(r);
      for (const kind of KINDS) {
        if (!fits(kind, it)) continue;
        // (1.3) a Reading takes what is on or off as well; 1.0 drew only these
        if (kind === "reading" && !(it.state.value !== null || it.kind === "reading" || it.kind === "sensor" || it.attrs.some((a) => a.type === "number"))) continue;
        OLD_SETTINGS.forEach((s, si) => {
          const hub = goldenHub([it]);
          const key = new MockSurface("Keypad", "D");
          new ActionView(kind, hub, key, { ...s, item: it.id }).draw(true);
          const dial = new MockSurface("Encoder", "D");
          new ActionView(kind, hub, dial, { ...s, item: it.id }).draw(true);
          const h = createHash("sha256").update(key.svg).update("\n").update(JSON.stringify(dial.feedbacks.at(-1))).digest("hex");
          out.push({ name: `${kind}/${it.id}/${variant}/${si}`, hash: h });
        });
      }
    }
  }
  return out;
}
