/**
 * The messages between the property inspectors and the plugin (sendToPlugin /
 * sendToPropertyInspector). The inspectors never talk to ZIGMon themselves and never see
 * the key: they ask the plugin, which answers with what may be shown.
 */
import type { Hub } from "./hub.js";
import { fits, type ActionKind } from "./views.js";

export type PiRequest =
  | { t: "hello" }
  | { t: "catalog" }
  | { t: "preview" }
  | { t: "connect"; address: string }
  | { t: "cancel" }
  | { t: "pin"; fingerprint: string }
  | { t: "unpin" }
  | { t: "disconnect" }
  | { t: "retry" }
  | { t: "update" }
  /** (1.3) This action type's default text sizes ({ textValue: 150, ... }; {} clears them). */
  | { t: "textDefaults"; sizes: Record<string, number> };

export type PiReply = Record<string, unknown> & { t: string };

export function statusMessage(hub: Hub): PiReply {
  return { t: "status", status: hub.status() as unknown as Record<string, unknown> };
}

export function catalogMessage(hub: Hub, kind: ActionKind): PiReply {
  const items = hub.allItems().filter((i) => fits(kind, i)).map((i) => {
    const st = hub.state(i.id) ?? i.state;
    return {
      id: i.id, name: i.name, room: i.room, kind: i.kind, icon: i.icon, cap: i.cap, allowed: i.allowed, hold: i.hold,
      actions: i.actions, attrs: i.attrs, valueText: st.valueText, on: st.on, online: st.online, ...(i.act ? { act: i.act } : {}),
      // (1.3) a computed value: what over what, for the Computed builder
      ...(i.calc ? { calc: { ...i.calc } } : {}),
    };
  });
  const msg: PiReply = { t: "catalog", kind, rooms: hub.allRooms().map((r) => r.name), items, phase: hub.currentPhase };
  // (1.3) Away / Home: the switches it may turn off as well, each under its own capability
  if (kind === "away") msg.extras = awayChoices(hub);
  // (1.3) SMS, Write new: ZIGMon's contacts and groups for the picker (no numbers), or null when it sent none
  if (kind === "sms") {
    const b = hub.smsBook();
    msg.sms = b ? { contacts: b.contacts.map((c) => ({ ...c })), groups: [...b.groups] } : null;
  }
  return msg;
}

/** (1.3) What an Away key may switch off with it: whatever can be switched off, but the summaries and Away itself. */
export function awayChoices(hub: Hub): Record<string, unknown>[] {
  return hub.allItems().filter((i) => i.actions.includes("off") && (i.cap === "switch" || i.cap === "dim") && fits("control", i)).slice(0, 500).map((i) => ({
    id: i.id, name: i.name, room: i.room, kind: i.kind, icon: i.icon, cap: i.cap, allowed: i.allowed, hold: i.hold,
  }));
}

/** (1.3) The text sizes every key of this action type draws with unless it sets its own. */
export function textDefaultsMessage(hub: Hub, kind: ActionKind): PiReply {
  return { t: "textDefaults", kind, sizes: hub.textDefaults(kind) ?? {} };
}

/** What a preview function gives: the key as it is, and (1.1) the Look section's pictures. */
export type Preview = () => string | { image: string; looks?: unknown; facts?: unknown } | null;

export function previewMessage(preview?: Preview): PiReply[] {
  const p = preview?.();
  if (!p) return [];
  if (typeof p === "string") return [{ t: "preview", image: p }];
  return [{ t: "preview", image: p.image, ...(p.looks ? { looks: p.looks } : {}), ...(p.facts ? { facts: p.facts } : {}) }];
}

export async function handlePi(hub: Hub, kind: ActionKind, raw: unknown, preview?: Preview): Promise<PiReply[]> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  const m = raw as Record<string, unknown>;
  switch (m.t) {
    case "hello":
      return [statusMessage(hub), catalogMessage(hub, kind), textDefaultsMessage(hub, kind), ...previewMessage(preview)];
    case "preview":
      return previewMessage(preview);
    case "catalog":
      return [catalogMessage(hub, kind)];
    case "connect": {
      const r = await hub.connect(typeof m.address === "string" ? m.address : "");
      return [{ t: "connect", ok: r.ok, error: r.error ?? "" }, statusMessage(hub)];
    }
    case "cancel":
      hub.cancelPairing();
      return [statusMessage(hub)];
    case "pin": {
      const r = await hub.pinCertificate(typeof m.fingerprint === "string" ? m.fingerprint : "");
      return [{ t: "pin", ok: r.ok, error: r.error ?? "" }, statusMessage(hub)];
    }
    case "unpin":
      await hub.unpin();
      return [statusMessage(hub)];
    case "disconnect":
      await hub.disconnect();
      return [statusMessage(hub), catalogMessage(hub, kind)];
    case "retry":
      hub.retryNow();
      return [statusMessage(hub)];
    case "update":
      void hub.installUpdate();
      return [statusMessage(hub)];
    case "textDefaults": {
      const sizes = m.sizes && typeof m.sizes === "object" && !Array.isArray(m.sizes) ? (m.sizes as Record<string, unknown>) : {};
      await hub.setTextDefaults(kind, sizes);
      return [textDefaultsMessage(hub, kind), ...previewMessage(preview)];
    }
    default:
      return [];
  }
}
