import { randomBytes } from "node:crypto";
import { cleanHex } from "./colour.js";
import { cleanRecipient } from "./kinds.js";
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
  [k: string]: string | number | boolean | null | undefined | string[];
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
  /** (1.1) The look (themes.ts THEMES); none = Classic, as 1.0 drew. */
  theme?: string;
  /** (1.1) An accent colour by name (palette.ts ACCENTS); none = Auto, the item's own.
   * (1.3) Also the user's own colour, "#RRGGBB" (kept uppercased). It is the On colour. */
  accent?: string;
  /** (1.3) The Off colour: what an off key is drawn in, the same values as accent; none = the look's own off style. */
  accentOff?: string;
  /** (1.1) Long names: cut (one line, as 1.0), fit (smaller, then two lines) or wrap (two lines). */
  nameFit?: string;
  /** (1.1) What the key shows - each on unless switched off (room: showRoom above). */
  showIcon?: boolean;
  showName?: boolean;
  showState?: boolean;
  showDetail?: boolean;
  showMode?: boolean;
  showGraph?: boolean;
  showBattery?: boolean;
  /** (1.1) The graph: its span in seconds, min/max labels, the target as a dashed line. */
  span?: number;
  showScale?: boolean;
  showTarget?: boolean;
  /** (1.1) Hold the key / dial 1.5 s before it acts, even where ZIGMon does not ask for it. */
  hold?: boolean;
  /** (1.3) Next mode / Next preset goes round only these (a comma list of the item's own values); none = all. */
  cycleOnly?: string;
  /** (1.2) "By hand", as ZIGMon's buttons have it: a press that leaves it on takes it over - rules and
   * schedules leave it alone - and one that leaves it off gives it back. */
  byHand?: boolean;
  /** (1.3) Timer (and a Control key's Timer press): on for this many minutes, 1-720. */
  minutes?: number;
  /** (1.3) Away / Home: the switches turned off too when going Away, each by its own capability. */
  awayOff?: string[];
  /** (1.3) SMS: what the key is - the latest SMS, a new one, or the SMS status. */
  smsMode?: string;
  /** (1.3) SMS, Write new: whom to (numbers, group:<name>, contact:<id>), at most 20. */
  smsTo?: string[];
  /** (1.3) SMS status: how long a held press hushes the alerts, 15-240 minutes. */
  muteMinutes?: number;
}

/** (1.3) The SMS key's modes, and the item each one is. */
export const SMS_MODES = ["last", "compose", "status"] as const;
/** (1.3) The Timer's ready choices of minutes (any whole number 1-720 may be typed). */
export const TIMER_MINUTES = [5, 10, 15, 30, 60, 120] as const;
export const TIMER_MOST = 720;
/** (1.3) The hush a held SMS status key sets. */
export const MUTE_MINUTES = [15, 30, 60, 120, 240] as const;
export const AWAY_MOST = 20;
export const SMS_TO_MOST = 20;


/** The modes of a heated room, as the dashboard names them; a press may set one outright. */
export const ROOM_MODES = ["plan", "comfort", "eco", "night", "max", "off", "manual"] as const;
const PRESS = ["toggle", "on", "off", "run", "open", "close", "stop", "unlock", "lock", "refresh", "press", "cycle", "mode", "preset", "boost", "openclose", "details",
  ...ROOM_MODES.map((m) => "set:" + m),
  // (1.3) a Control key on a switch: on for `minutes`, a press again cancels it
  "timer"];
export const THEME_IDS = ["classic", "minimal", "bigvalue", "fill", "neon", "ring", "split", "glass", "label", "dot", "light", "contrast",
  "huge", "pill", "orb", "tile", "gauge", "bars", "wave", "aurora", "outline", "mono",
  "diagonal", "hex", "stripe", "switch", "lcd", "dial", "ticket", "bubble", "frame", "shadow", "line", "tube", "stamp", "pastel", "carbon", "grid", "tab", "rise", "spot", "button",
  // (1.3) the name-first looks
  "namebar", "caption", "led", "tworows", "plate", "ticker", "card", "halves", "stacked", "corner", "lined", "terminal", "marquee", "widget", "sign", "note", "pass", "glow"] as const;
export const ACCENT_IDS = ["blue", "green", "amber", "red", "purple", "orange", "teal", "pink", "yellow", "silver",
  "indigo", "sky", "cyan", "mint", "lime", "gold", "peach", "coral", "rose", "magenta", "lavender", "brown", "slate", "white"] as const;

/** (1.3) A colour setting: one of ACCENT_IDS, or exactly "#RRGGBB" (uppercased); anything else is dropped. */
export function cleanColourSetting(v: unknown): string | undefined {
  if (typeof v !== "string") return undefined;
  if ((ACCENT_IDS as readonly string[]).includes(v)) return v;
  return cleanHex(v) ?? undefined;
}
export const NAME_FITS = ["cut", "fit", "wrap"] as const;
export const SPANS = [3600, 6 * 3600, 24 * 3600, 7 * 86400] as const;
export const LABEL_MOST = 40;
const SHOW = ["showIcon", "showName", "showState", "showDetail", "showMode", "showGraph", "showBattery", "showScale", "showTarget", "hold", "byHand"] as const;

/** (1.3) The values Next mode / Next preset goes round: at most 16 distinct words of the item's own values. */
export function cleanCycleOnly(v: unknown): string {
  if (typeof v !== "string" || v.length > 400) return "";
  const out: string[] = [];
  for (const t of v.split(",")) {
    const w = t.trim();
    if (/^[A-Za-z0-9_+-]{1,24}$/.test(w) && !out.includes(w) && out.length < 16) out.push(w);
  }
  return out.join(",");
}

/** A label as the user typed it: no control or direction characters, spaces folded, at most LABEL_MOST characters. */
export function cleanLabel(v: unknown): string {
  if (typeof v !== "string") return "";
  const t = v.replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩﻿￾￿]/g, " ").replace(/\s+/g, " ").trim();
  return [...t].slice(0, LABEL_MOST).join("").trim();
}

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
  const only = cleanCycleOnly(o.cycleOnly);
  if (only) s.cycleOnly = only;
  const label = cleanLabel(o.label);
  if (label) s.label = label;
  for (const k of ["warnBelow", "warnAbove", "critBelow", "critAbove"] as const) {
    const n = finiteOrNull(o[k]);
    if (n !== null) s[k] = n;
  }
  const d = finiteOrNull(o.decimals);
  if (d !== null && d >= -1 && d <= 3) s.decimals = Math.round(d);
  if (typeof o.showRoom === "boolean") s.showRoom = o.showRoom;
  if (typeof o.theme === "string" && (THEME_IDS as readonly string[]).includes(o.theme) && o.theme !== "classic") s.theme = o.theme;
  const accent = cleanColourSetting(o.accent);
  if (accent) s.accent = accent;
  const accentOff = cleanColourSetting(o.accentOff);
  if (accentOff) s.accentOff = accentOff;
  if (typeof o.nameFit === "string" && (NAME_FITS as readonly string[]).includes(o.nameFit)) s.nameFit = o.nameFit;
  for (const k of SHOW) if (typeof o[k] === "boolean") s[k] = o[k] as boolean;
  const span = finiteOrNull(o.span);
  if (span !== null && (SPANS as readonly number[]).includes(span)) s.span = span;
  // (1.3) the new actions' own choices
  const min = finiteOrNull(o.minutes);
  if (min !== null && Number.isInteger(min) && min >= 1 && min <= TIMER_MOST) s.minutes = min;
  if (Array.isArray(o.awayOff)) {
    const ids = [...new Set(o.awayOff.filter((x): x is string => typeof x === "string" && x.length > 0 && x.length <= 160 && !/[\u0000-\u001f\u007f]/.test(x)))];
    if (ids.length) s.awayOff = ids.slice(0, AWAY_MOST);
  }
  if (typeof o.smsMode === "string" && (SMS_MODES as readonly string[]).includes(o.smsMode)) s.smsMode = o.smsMode;
  if (Array.isArray(o.smsTo)) {
    const to = [...new Set(o.smsTo.map(cleanRecipient).filter((x): x is string => x !== null))];
    if (to.length) s.smsTo = to.slice(0, SMS_TO_MOST);
  }
  const mute = finiteOrNull(o.muteMinutes);
  if (mute !== null && (MUTE_MINUTES as readonly number[]).includes(mute)) s.muteMinutes = mute;
  return s;
}
