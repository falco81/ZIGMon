import { randomBytes } from "node:crypto";
import { normalizePin, type Pins } from "./tls.js";

/**
 * The plugin's global settings, kept by the Stream Deck app. The key itself is only ever
 * stored as a DPAPI blob (`tokenBlob`); everything else here is not secret.
 */
export interface GlobalSettings {
  [k: string]: string | number | boolean | Pins | null | undefined;
  /** The dashboard address as the user typed it (normalised). */
  address?: string;
  /** Random 32 hex, made once per installation. */
  install?: string;
  /** "dpapi:<base64>" - the deck key, encrypted for this Windows user. */
  tokenBlob?: string;
  /** host:port -> SHA-256 of a certificate the user chose to trust. */
  pins?: Pins;
}

export function normalizeGlobal(raw: unknown): GlobalSettings {
  const o = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const g: GlobalSettings = {};
  if (typeof o.address === "string" && o.address.length <= 300) g.address = o.address;
  if (typeof o.install === "string" && /^[0-9a-f]{32}$/.test(o.install)) g.install = o.install;
  if (typeof o.tokenBlob === "string" && /^(dpapi|fake):[A-Za-z0-9+/=]{8,4096}$/.test(o.tokenBlob)) g.tokenBlob = o.tokenBlob;
  const pins: Pins = {};
  if (o.pins && typeof o.pins === "object" && !Array.isArray(o.pins)) {
    for (const [k, v] of Object.entries(o.pins as Record<string, unknown>)) {
      const n = normalizePin(v);
      if (n && /^[a-z0-9.:[\]-]{1,300}$/.test(k)) pins[k] = n;
    }
  }
  g.pins = pins;
  return g;
}

export function newInstallId(): string {
  return randomBytes(16).toString("hex");
}

/** What each action keeps in its own settings (written by its property inspector). */
export interface ActionSettings {
  [k: string]: string | number | boolean | null | undefined;
  item?: string;
  /** Control: what a press does (toggle/on/off/run/open/close/stop). Blinds: push. Thermostat: push. */
  press?: string;
  /** Dial step for one tick (dimmer %, thermostat °C, blinds %). */
  step?: number;
  /** Reading: a label instead of the item's name. */
  label?: string;
  /** Reading thresholds: outside them the value turns amber / red. */
  warnBelow?: number | null;
  warnAbove?: number | null;
  critBelow?: number | null;
  critAbove?: number | null;
  /** Reading: decimals to show (-1 = as ZIGMon formats it). */
  decimals?: number;
  /** Show the room on the key. */
  showRoom?: boolean;
}

const PRESS = ["toggle", "on", "off", "run", "open", "close", "stop", "cycle", "mode", "preset", "boost", "openclose"];

function finiteOrNull(v: unknown): number | null {
  if (v === "" || v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function normalizeAction(raw: unknown): ActionSettings {
  const o = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const s: ActionSettings = {};
  if (typeof o.item === "string" && o.item.length > 0 && o.item.length <= 160) s.item = o.item;
  if (typeof o.press === "string" && PRESS.includes(o.press)) s.press = o.press;
  const step = finiteOrNull(o.step);
  if (step !== null && step > 0 && step <= 1000) s.step = step;
  if (typeof o.label === "string") s.label = o.label.slice(0, 40);
  for (const k of ["warnBelow", "warnAbove", "critBelow", "critAbove"] as const) {
    const n = finiteOrNull(o[k]);
    if (n !== null) s[k] = n;
  }
  const d = finiteOrNull(o.decimals);
  if (d !== null && d >= -1 && d <= 3) s.decimals = Math.round(d);
  if (typeof o.showRoom === "boolean") s.showRoom = o.showRoom;
  return s;
}
