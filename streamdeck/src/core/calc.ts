/**
 * (1.3, ZIGMon 5.59.4) Computed values (PROTOCOL-CALC.md): the functions, metrics and scopes of
 * `calc:<fn>:<metric>:<scope>`, read strictly, and the inspector's builder - What, How and Where
 * mapped onto an item the catalogue really has, the impossible choices disabled, and the Popular
 * presets. Shared by the plugin and the property inspector (no Node, no SDK here).
 */
import { P } from "./palette.js";

export const CALC_FNS = ["sum", "avg", "min", "max", "count", "on", "off", "pct_on", "spread"] as const;
export type CalcFn = (typeof CALC_FNS)[number];

export const CALC_METRICS = [
  "power", "energy_today", "energy_total", "temperature", "humidity", "pressure", "illuminance", "co2", "battery", "linkquality",
  "state", "open", "online",
] as const;
export type CalcMetric = (typeof CALC_METRICS)[number];

export const CALC_KINDS = ["light", "socket", "switch", "dimmer", "thermostat", "sensor", "cover"] as const;
export type CalcKind = (typeof CALC_KINDS)[number];

export type CalcPlace = "all" | "inside" | "outside";
export const CALC_PLACES: readonly CalcPlace[] = ["all", "inside", "outside"];

/** A scope: everything, inside or outside, or a kind and/or a room (by its id) of the whole house. */
export interface CalcScope {
  place: CalcPlace;
  kind: CalcKind | null;
  room: string | null;
}

/** An item's `calc` block, as parsed. */
export interface CalcInfo {
  fn: CalcFn;
  metric: CalcMetric;
  scope: string;
  members: number;
  unit: string;
}

/** The yes/no metrics and the functions each of them has. */
const ON_OFF: Readonly<Partial<Record<CalcMetric, readonly CalcFn[]>>> = {
  state: ["on", "off", "pct_on", "count"],
  open: ["count", "on"],
  online: ["count", "on", "off"],
};

/** Whether a function makes sense of a metric at all: on / off / % on only of what is on or off, and that only so. */
export function fnFits(fn: CalcFn, metric: CalcMetric): boolean {
  const only = ON_OFF[metric];
  if (only) return only.includes(fn);
  return fn !== "on" && fn !== "off" && fn !== "pct_on";
}

const ROOM_ID = "[A-Za-z0-9_.-]{1,60}";
const SCOPE_RE = new RegExp(`^(?:(all|inside|outside)|kind=(${CALC_KINDS.join("|")})|room=(${ROOM_ID})(?:,kind=(${CALC_KINDS.join("|")}))?)$`);

/** A scope as ZIGMon writes it, or null for anything else. */
export function parseScope(s: unknown): CalcScope | null {
  if (typeof s !== "string" || s.length > 90) return null;
  const m = SCOPE_RE.exec(s);
  if (!m) return null;
  if (m[1]) return { place: m[1] as CalcPlace, kind: null, room: null };
  if (m[2]) return { place: "all", kind: m[2] as CalcKind, room: null };
  return { place: "all", kind: (m[4] as CalcKind | undefined) ?? null, room: m[3]! };
}

/** The scope back as ZIGMon writes it. */
export function scopeText(sc: CalcScope): string {
  if (sc.room) return "room=" + sc.room + (sc.kind ? ",kind=" + sc.kind : "");
  if (sc.kind) return "kind=" + sc.kind;
  return sc.place;
}

/** An id `calc:<fn>:<metric>:<scope>`, read strictly; null for anything else. */
export function parseCalcId(id: unknown): { fn: CalcFn; metric: CalcMetric; scope: CalcScope } | null {
  if (typeof id !== "string" || !id.startsWith("calc:") || id.length > 160) return null;
  const [, fn, metric, ...rest] = id.split(":");
  const scope = parseScope(rest.join(":"));
  if (!scope || !(CALC_FNS as readonly string[]).includes(fn ?? "") || !(CALC_METRICS as readonly string[]).includes(metric ?? "")) return null;
  if (!fnFits(fn as CalcFn, metric as CalcMetric)) return null;
  return { fn: fn as CalcFn, metric: metric as CalcMetric, scope };
}

export function calcId(fn: CalcFn, metric: CalcMetric, sc: CalcScope): string {
  return `calc:${fn}:${metric}:${scopeText(sc)}`;
}

/**
 * The item's `calc` block, strictly: a function and a metric this plugin knows and that go
 * together, a scope as the contract has them, the same three as the item's id, a whole count of
 * members (at most 100 000) and a short unit. Anything else: null, and the item is not offered.
 */
export function parseCalc(v: unknown, id: string): CalcInfo | null {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  const fn = o.fn, metric = o.metric, scope = o.scope;
  if (typeof fn !== "string" || typeof metric !== "string" || typeof scope !== "string") return null;
  const fromId = parseCalcId(id);
  const sc = parseScope(scope);
  if (!fromId || !sc || fromId.fn !== fn || fromId.metric !== metric || scopeText(fromId.scope) !== scopeText(sc)) return null;
  const members = typeof o.members === "number" && Number.isSafeInteger(o.members) && o.members >= 0 ? Math.min(o.members, 100_000) : 0;
  const unit = typeof o.unit === "string" ? o.unit.replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿]/g, "").trim().slice(0, 8) : "";
  return { fn: fromId.fn, metric: fromId.metric, scope: scopeText(sc), members, unit };
}

/** At most this many computed items are taken from a catalogue (ZIGMon rings at most 300; the rest is room to spare). */
export const CALC_MOST = 2000;

// ------------------------------------------------------------------ words and looks

export const METRIC_WORDS: Readonly<Record<CalcMetric, { word: string; icon: string; accent: string }>> = {
  power: { word: "Power", icon: "bolt", accent: P.warn },
  energy_today: { word: "Energy today", icon: "sun", accent: P.warn },
  energy_total: { word: "Energy total", icon: "energy", accent: P.orange },
  temperature: { word: "Temperature", icon: "thermo", accent: P.orange },
  humidity: { word: "Humidity", icon: "drop", accent: P.water },
  pressure: { word: "Pressure", icon: "gauge", accent: P.info },
  illuminance: { word: "Light level", icon: "sun", accent: P.warn },
  co2: { word: "CO₂", icon: "leaf", accent: P.ok },
  battery: { word: "Battery", icon: "battery", accent: P.purple },
  linkquality: { word: "Signal", icon: "wifi", accent: P.info },
  state: { word: "On / off", icon: "power", accent: P.ok },
  open: { word: "Open", icon: "windowOpen", accent: P.water },
  online: { word: "Online", icon: "mesh", accent: P.info },
};

export const FN_WORDS: Readonly<Record<CalcFn, { word: string; icon: string }>> = {
  sum: { word: "Sum", icon: "sigma" },
  avg: { word: "Average", icon: "trendFlat" },
  min: { word: "Min", icon: "down" },
  max: { word: "Max", icon: "up" },
  count: { word: "Count", icon: "grid" },
  on: { word: "On", icon: "power" },
  off: { word: "Off", icon: "power" },
  pct_on: { word: "% on", icon: "dial" },
  spread: { word: "Spread", icon: "layers" },
};

/** A function's word for a metric: of a contact, On is Open; of a device, On is Online. */
export function fnWord(fn: CalcFn, metric: CalcMetric | null): string {
  if (metric === "open" && fn === "on") return "Open";
  if (metric === "online" && fn === "on") return "Online";
  if (metric === "online" && fn === "off") return "Offline";
  return FN_WORDS[fn].word;
}

export const KIND_WORDS: Readonly<Record<CalcKind, { word: string; icon: string }>> = {
  light: { word: "Lights", icon: "bulbOn" },
  socket: { word: "Sockets", icon: "socket" },
  switch: { word: "Switches", icon: "switch" },
  dimmer: { word: "Dimmers", icon: "dimmer" },
  thermostat: { word: "Thermostats", icon: "thermostat" },
  sensor: { word: "Sensors", icon: "sensor" },
  cover: { word: "Blinds", icon: "blinds" },
};

export const PLACE_WORDS: Readonly<Record<CalcPlace, { word: string; icon: string }>> = {
  all: { word: "All", icon: "home" },
  inside: { word: "Inside", icon: "sofa" },
  outside: { word: "Outside", icon: "leaf" },
};

/**
 * The key's icon and colour: the metric's, so a Computed key looks like the Reading of the same
 * thing. A count of things that are on or open is lit in the metric's colour too.
 */
export function calcLook(c: Pick<CalcInfo, "fn" | "metric"> | undefined): { accent: string; icon: string } {
  if (!c) return { accent: P.info, icon: "sigma" };
  const m = METRIC_WORDS[c.metric];
  return { accent: m.accent, icon: c.metric === "state" && c.fn !== "count" ? "bulbOn" : m.icon };
}

// ------------------------------------------------------------------ the builder

/** One computed item the builder may pick. */
export interface CalcEntry {
  id: string;
  fn: CalcFn;
  metric: CalcMetric;
  scope: CalcScope;
  name: string;
  /** The room's name, for a room scope. */
  room: string | null;
}

/** The builder's choice: What, How and Where. */
export interface CalcChoice {
  metric: CalcMetric | null;
  fn: CalcFn | null;
  place: CalcPlace;
  kind: CalcKind | null;
  room: string | null;
}

export const NO_CHOICE: CalcChoice = { metric: null, fn: null, place: "all", kind: null, room: null };

/** The computed items among what the catalogue gave (by id; the block's own fields must agree, as parsed). */
export function calcEntries(items: readonly { id: string; name: string; room: string | null; calc?: unknown }[]): CalcEntry[] {
  const out: CalcEntry[] = [];
  const seen = new Set<string>();
  for (const it of items) {
    if (out.length >= CALC_MOST) break;
    const p = parseCalcId(it.id);
    if (!p || !it.calc || seen.has(it.id)) continue;
    seen.add(it.id);
    out.push({ id: it.id, fn: p.fn, metric: p.metric, scope: p.scope, name: it.name, room: p.scope.room ? it.room ?? p.scope.room : null });
  }
  return out;
}

/** The choice that is this item. */
export function choiceOf(e: Pick<CalcEntry, "fn" | "metric" | "scope">): CalcChoice {
  return { metric: e.metric, fn: e.fn, place: e.scope.place, kind: e.scope.kind, room: e.scope.room };
}

function sameScope(a: CalcScope, c: CalcChoice): boolean {
  return a.place === c.place && a.kind === c.kind && a.room === c.room;
}

/** The item a complete choice is, or null when the catalogue has no such item. */
export function resolveChoice(entries: readonly CalcEntry[], c: CalcChoice): CalcEntry | null {
  if (!c.metric || !c.fn) return null;
  return entries.find((e) => e.metric === c.metric && e.fn === c.fn && sameScope(e.scope, c)) ?? null;
}

/** What a metric is mostly wanted for, when a function has to be picked for it. */
export const DEFAULT_FN: Readonly<Record<CalcMetric, CalcFn>> = {
  power: "sum", energy_today: "sum", energy_total: "sum", temperature: "avg", humidity: "avg", pressure: "avg", illuminance: "avg",
  co2: "max", battery: "min", linkquality: "min", state: "on", open: "on", online: "off",
};

type Field = "metric" | "fn" | "place" | "kind" | "room";

/**
 * The choice after one of its parts is changed: that part (and those above it: What, then How)
 * kept, the rest moved to the nearest item the catalogue has - the same function and place where
 * it can, else the metric's usual function and the whole house. The result is always an item
 * that exists, unless nothing at all fits what was picked (then the choice comes back as it was).
 */
export function pick(entries: readonly CalcEntry[], c: CalcChoice, patch: Partial<CalcChoice>): CalcChoice {
  const want: CalcChoice = { ...c, ...patch };
  // Inside / Outside are of the whole house; a kind or a room is of All
  if (patch.place !== undefined) {
    want.kind = null;
    want.room = null;
  }
  if ((patch.kind !== undefined && patch.kind !== null) || (patch.room !== undefined && patch.room !== null)) want.place = "all";
  const fixed: Field[] = ["metric"];
  if ("fn" in patch || "place" in patch || "kind" in patch || "room" in patch) fixed.push("fn");
  if ("place" in patch) fixed.push("place", "kind", "room");
  if ("kind" in patch) fixed.push("kind");
  if ("room" in patch) fixed.push("room");
  const field = (e: CalcEntry, f: Field) => (f === "metric" ? e.metric : f === "fn" ? e.fn : f === "place" ? e.scope.place : f === "kind" ? e.scope.kind : e.scope.room);
  const cands = entries.filter((e) => fixed.every((f) => field(e, f) === want[f]));
  if (!cands.length) return c;
  let best = cands[0]!, bestScore = -1;
  // the same function first, else the usual one; then the place, kind and room picked; then the widest scope
  const wide = (sc: CalcScope) => (sc.kind && sc.room ? 0 : sc.room ? 0.25 : sc.kind ? 0.5 : sc.place === "all" ? 1 : 0.75);
  for (const e of cands) {
    const s = (e.fn === want.fn ? 32 : 0) + (e.fn === DEFAULT_FN[e.metric] ? 16 : 0)
      + (want.place !== "all" && e.scope.place === want.place ? 8 : 0) + (want.kind && e.scope.kind === want.kind ? 4 : 0)
      + (want.room && e.scope.room === want.room ? 2 : 0) + wide(e.scope);
    if (s > bestScore) {
      best = e;
      bestScore = s;
    }
  }
  return choiceOf(best);
}

export interface Opt<T> {
  id: T;
  enabled: boolean;
}

/** What the builder shows: each choice, and whether the catalogue has anything for it given what is picked above it. */
export interface BuilderView {
  metrics: Opt<CalcMetric>[];
  fns: Opt<CalcFn>[];
  places: Opt<CalcPlace>[];
  kinds: Opt<CalcKind | null>[];
  rooms: (Opt<string | null> & { name: string })[];
  item: CalcEntry | null;
}

export function builderView(entries: readonly CalcEntry[], c: CalcChoice): BuilderView {
  const ofMetric = entries.filter((e) => e.metric === c.metric);
  const ofFn = ofMetric.filter((e) => e.fn === c.fn);
  const roomNames = new Map<string, string>();
  for (const e of entries) if (e.scope.room && !roomNames.has(e.scope.room)) roomNames.set(e.scope.room, e.room || e.scope.room);
  const fns = CALC_FNS.filter((f) => !c.metric || fnFits(f, c.metric));
  const plain = (e: CalcEntry) => !e.scope.kind && !e.scope.room;
  return {
    metrics: CALC_METRICS.map((m) => ({ id: m, enabled: entries.some((e) => e.metric === m) })),
    fns: fns.map((f) => ({ id: f, enabled: ofMetric.some((e) => e.fn === f) })),
    places: CALC_PLACES.map((p) => ({ id: p, enabled: ofFn.some((e) => plain(e) && e.scope.place === p) })),
    kinds: [
      { id: null, enabled: ofFn.some((e) => !e.scope.kind && (c.room ? e.scope.room === c.room : plain(e))) },
      ...CALC_KINDS.map((k) => ({ id: k, enabled: ofFn.some((e) => e.scope.kind === k) })),
    ],
    rooms: [
      { id: null, name: "Any room", enabled: ofFn.some((e) => !e.scope.room && (c.kind ? e.scope.kind === c.kind : plain(e))) },
      ...[...roomNames.entries()].sort((a, b) => a[1].localeCompare(b[1])).map(([id, name]) => ({ id, name, enabled: ofFn.some((e) => e.scope.room === id) })),
    ],
    item: resolveChoice(entries, c),
  };
}

// ------------------------------------------------------------------ Popular

export interface CalcPreset {
  key: string;
  name: string;
  icon: string;
  /** The items it is, the first the catalogue has. */
  ids: string[];
}

export const CALC_PRESETS: readonly CalcPreset[] = [
  { key: "power", name: "Total power", icon: "bolt", ids: ["calc:sum:power:all"] },
  { key: "lights_w", name: "Power of lights", icon: "bulbOn", ids: ["calc:sum:power:kind=light"] },
  { key: "sockets_w", name: "Power of sockets", icon: "socket", ids: ["calc:sum:power:kind=socket"] },
  { key: "lights_on", name: "Lights on", icon: "bulbOn", ids: ["calc:on:state:kind=light"] },
  { key: "temp_in", name: "Average inside", icon: "thermo", ids: ["calc:avg:temperature:inside", "calc:avg:temperature:all"] },
  { key: "coldest", name: "Coldest room", icon: "snow", ids: ["calc:min:temperature:inside", "calc:min:temperature:all"] },
  { key: "open", name: "Windows open", icon: "windowOpen", ids: ["calc:on:open:all"] },
  { key: "offline", name: "Devices offline", icon: "wifiOff", ids: ["calc:off:online:all"] },
  { key: "battery", name: "Lowest battery", icon: "batteryLow", ids: ["calc:min:battery:all"] },
  { key: "energy", name: "Energy today", icon: "sun", ids: ["calc:sum:energy_today:all"] },
];

/** The item a preset is here, or null when the catalogue has none of its items. */
export function presetId(entries: readonly { id: string }[], p: CalcPreset): string | null {
  const have = new Set(entries.map((e) => e.id));
  return p.ids.find((id) => have.has(id)) ?? null;
}

/** What hello's features must say for a Computed key. */
export const CALC_NEEDS = ["extended", "calc"] as const;

/** "Lights · Obývák", "Inside", "The whole house": where a computed value is taken. */
export function scopeWords(sc: CalcScope, roomName: string | null): string {
  const parts: string[] = [];
  if (sc.kind) parts.push(KIND_WORDS[sc.kind].word);
  if (sc.room) parts.push(roomName || sc.room);
  if (parts.length) return parts.join(" · ");
  return sc.place === "inside" ? "Inside" : sc.place === "outside" ? "Outside" : "The whole house";
}

/** The inspector's "Now" of a Computed key: the value, what it is of, how many had one, and the extremes by name. */
export function calcFacts(
  it: { id: string; room: string | null; calc?: CalcInfo },
  st: { valueText: string; value: number | null; attrs: Record<string, unknown>; online: boolean },
): [string, string][] {
  const c = it.calc;
  const p = parseCalcId(it.id);
  if (!c || !p) return [];
  const n = (k: string) => {
    const x = st.attrs[k];
    return typeof x === "number" && Number.isFinite(x) ? Math.round(x) : null;
  };
  const s = (k: string) => {
    const x = st.attrs[k];
    return typeof x === "string" ? x.slice(0, 60) : "";
  };
  const rows: [string, string][] = [
    ["Now", st.online ? st.valueText || (st.value !== null ? String(st.value) : "—") : "no value yet"],
    ["Computes", fnWord(p.fn, p.metric) + " · " + METRIC_WORDS[p.metric].word],
    ["Over", scopeWords(p.scope, it.room)],
  ];
  const members = n("members") ?? c.members;
  const known = n("known");
  rows.push(["Members", known !== null && known !== members ? `${known} of ${members} with a value` : String(members)]);
  if (s("min_of")) rows.push(["Lowest", s("min_of")]);
  if (s("max_of")) rows.push(["Highest", s("max_of")]);
  return rows;
}
