/**
 * (1.3, ZIGMon 5.59.4) The ten new actions: their names, the item each one shows, and what they
 * need of ZIGMon. Shared by the plugin and the property inspector (no Node, no SDK here).
 */

export const NEW_KINDS = ["power", "security", "heatgroup", "away", "openings", "batteries", "zigbee", "timer", "room", "sms"] as const;
export type NewKind = (typeof NEW_KINDS)[number];

export function isNewKind(k: string): k is NewKind {
  return (NEW_KINDS as readonly string[]).includes(k);
}

/** The house's own summaries: one each, so the key needs no item picked. */
export const FIXED_ITEM: Readonly<Partial<Record<NewKind, string>>> = {
  power: "house:power",
  security: "status:security",
  heatgroup: "heat:group:all",
  away: "house:away",
  openings: "house:openings",
  batteries: "house:batteries",
  zigbee: "status:zigbee",
};

/** The SMS key's three modes and the item each one is (PROTOCOL-5.59.4.md 10, windows/PROTOCOL-SMS.md 3). */
export const SMS_ITEM: Readonly<Record<string, string>> = { last: "sms:last", compose: "sms:compose", status: "status:sms" };

/** The item a new action shows: its fixed summary, the SMS mode's item, else the one picked. */
export function itemFor(kind: string, settings: { item?: unknown; smsMode?: unknown }): string | undefined {
  const fixed = FIXED_ITEM[kind as NewKind];
  if (fixed) return fixed;
  if (kind === "sms") return SMS_ITEM[typeof settings.smsMode === "string" && settings.smsMode in SMS_ITEM ? settings.smsMode : "last"];
  return typeof settings.item === "string" && settings.item ? settings.item : undefined;
}

/** What hello's features must say for each: the summaries ask for "extended"; the Timer sends `timer`. */
export function needs(kind: NewKind): string[] {
  return kind === "timer" ? ["extended", "timer"] : ["extended"];
}

/** The version that brought them, as the keys and the inspector say it. */
export const NEEDS_ZIGMON = "5.59.4";

/** How each is called, and its line in the action list. */
export const NEW_TITLES: Readonly<Record<NewKind, { name: string; line: string; icon: string }>> = {
  power: { name: "House power", line: "watts now", icon: "bolt" },
  security: { name: "Network security", line: "alerts", icon: "shieldOk" },
  heatgroup: { name: "Heating", line: "every room", icon: "flame" },
  away: { name: "Away / Home", line: "the house", icon: "suitcase" },
  openings: { name: "Windows & doors", line: "open", icon: "windowOpen" },
  batteries: { name: "Batteries", line: "low", icon: "batteryLow" },
  zigbee: { name: "Zigbee network", line: "online", icon: "mesh" },
  timer: { name: "Timer", line: "on for…", icon: "stopwatch" },
  room: { name: "Room", line: "at a glance", icon: "sofa" },
  sms: { name: "SMS", line: "messages", icon: "message" },
};

/** The dial's span steps on House power (seconds), as the graphs elsewhere have them. */
export const POWER_SPANS = [3600, 21600, 86400, 604800] as const;
export function spanWord(s: number): string {
  return s === 3600 ? "1 h" : s === 21600 ? "6 h" : s === 604800 ? "7 d" : "24 h";
}

/** The Timer dial's ladder of minutes. */
export const MINUTE_LADDER = [1, 2, 3, 5, 10, 15, 20, 25, 30, 40, 45, 60, 75, 90, 120, 150, 180, 240, 300, 360, 480, 600, 720] as const;

/** One step along the ladder from `m` (a minute count off the ladder snaps to the next one that way). */
export function stepMinutes(m: number, ticks: number): number {
  const L = MINUTE_LADDER as readonly number[];
  if (ticks === 0) return m;
  if (ticks > 0) {
    const up = L.filter((x) => x > m);
    return up.length ? up[Math.min(up.length, ticks) - 1]! : L[L.length - 1]!;
  }
  const down = L.filter((x) => x < m);
  return down.length ? down[Math.max(0, down.length + ticks)]! : L[0]!;
}

/** "12:34", "1:02:03" - a countdown, from seconds. */
export function countdown(sec: number): string {
  const s = Math.max(0, Math.ceil(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

/** "45 min", "2 h", "1 h 30" - a length of time, from minutes. */
export function minutesWord(m: number): string {
  if (m < 60) return m + " min";
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} h ${r}` : `${h} h`;
}

/** (1.3) One recipient as the user typed it: a phone number, group:<name> or contact:<id>; else null. */
export function cleanRecipient(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿]/g, " ").replace(/\s+/g, " ").trim();
  if (/^contact:c_[0-9a-f]{6,12}$/.test(t)) return t;
  const g = /^group:\s*(.+)$/i.exec(t);
  if (g) {
    const name = g[1]!.trim();
    return name && [...name].length <= 40 && !/[,;<>"]/.test(name) ? "group:" + name : null;
  }
  const num = t.replace(/[\s().-]/g, "");
  return /^\+?[0-9]{3,20}$/.test(num) ? num : null;
}
