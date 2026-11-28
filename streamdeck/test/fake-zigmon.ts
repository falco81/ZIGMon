/**
 * A small fake ZIGMon for the tests and the screenshots: the deck API of contract v1 on
 * Node's http/https, with its checks in the contract's order (enabled, token, install, deck
 * approved, allowed, hold, value). Tokens here are throwaway test values.
 */
import { createHash, randomBytes } from "node:crypto";
import * as http from "node:http";
import * as https from "node:https";
import type { AddressInfo } from "node:net";

export interface FakeItem {
  id: string;
  name: string;
  room: string | null;
  kind: string;
  icon: string;
  cap: string;
  actions: string[];
  attrs: Record<string, unknown>[];
  allowed: boolean;
  hold: boolean;
  state: Record<string, unknown>;
  /** (5.59.4, extended catalogue only) */
  act?: Record<string, { cap: string; allowed: boolean; hold: boolean }>;
  members?: string[];
  /** (5.59.4, PROTOCOL-CALC.md) a computed value's block */
  calc?: Record<string, unknown>;
}

export interface Seen {
  do: string;
  method: string;
  headers: http.IncomingHttpHeaders;
  query: URLSearchParams;
  body: unknown;
}

const CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

export function sampleItems(): FakeItem[] {
  const st = (o: Record<string, unknown>) => ({ on: null, value: null, value_text: "", attrs: {}, online: true, battery: null, at: 1700000000, ...o });
  return [
    { id: "Lampa", name: "Lampa obývák", room: "Obývák", kind: "socket", icon: "plug", cap: "switch", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: false, state: st({ on: true, value_text: "42 W" }) },
    { id: "zb:0xa1:state_l1", name: "Kitchen light", room: "Kitchen", kind: "light", icon: "light", cap: "switch", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: false, state: st({ on: false }) },
    {
      id: "zb:0xb2:light", name: "Desk lamp", room: "Office", kind: "dimmer", icon: "light", cap: "dim", actions: ["toggle", "on", "off", "set"],
      attrs: [{ key: "brightness", label: "Brightness", type: "number", unit: "%", min: 0, max: 100, step: 1 }], allowed: true, hold: false,
      state: st({ on: true, attrs: { brightness: 70 } }),
    },
    {
      id: "zb:0xc3:trv", name: "Bedroom radiator", room: "Bedroom", kind: "thermostat", icon: "heat", cap: "climate", actions: ["set"],
      attrs: [
        { key: "current_heating_setpoint", label: "Setpoint", type: "number", unit: "°C", min: 5, max: 30, step: 0.5 },
        { key: "system_mode", label: "Mode", type: "enum", values: ["off", "heat", "auto"] },
        { key: "preset", label: "Preset", type: "enum", values: ["comfort", "eco", "boost"] },
      ],
      allowed: true, hold: false,
      state: st({ value: 20.4, value_text: "20.4 °C", attrs: { current_heating_setpoint: 21.5, system_mode: "heat", preset: "comfort", running_state: "heat" } }),
    },
    {
      id: "zb:0xd4:cover", name: "Living room blinds", room: "Obývák", kind: "cover", icon: "cover", cap: "cover", actions: ["open", "close", "stop", "set"],
      attrs: [{ key: "position", label: "Position", type: "number", unit: "%", min: 0, max: 100, step: 1 }], allowed: true, hold: false,
      state: st({ value: 60, attrs: { position: 60 } }),
    },
    { id: "scene:3", name: "Movie night", room: "Obývák", kind: "scene", icon: "scene", cap: "scenes", actions: ["run"], attrs: [], allowed: true, hold: false, state: st({}) },
    { id: "seq:1", name: "Good morning", room: null, kind: "sequence", icon: "seq", cap: "scenes", actions: ["run"], attrs: [], allowed: true, hold: false, state: st({}) },
    { id: "sys:reboot", name: "Restart ZIGMon", room: null, kind: "system", icon: "reboot", cap: "system", actions: ["run"], attrs: [], allowed: true, hold: true, state: st({}) },
    { id: "rule:7", name: "Night mode rule", room: null, kind: "rule", icon: "rule", cap: "automations", actions: ["toggle", "on", "off"], attrs: [], allowed: false, hold: false, state: st({ on: true }) },
    { id: "Garage", name: "Garage door relay", room: "Garage", kind: "switch", icon: "", cap: "switch", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: true, state: st({ on: false }) },
    { id: "read:0xe5:temperature", name: "Outdoor temperature", room: "Garden", kind: "reading", icon: "thermo", cap: "view", actions: [], attrs: [{ key: "temperature", label: "Temperature", type: "number", unit: "°C" }], allowed: true, hold: false, state: st({ value: 7.3, value_text: "7.3 °C" }) },
    { id: "read:0xe5:humidity", name: "Outdoor humidity", room: "Garden", kind: "reading", icon: "drop", cap: "view", actions: [], attrs: [{ key: "humidity", label: "Humidity", type: "number", unit: "%" }], allowed: true, hold: false, state: st({ value: 81, value_text: "81 %" }) },
    { id: "read:0xf6:power", name: "Heat pump power", room: "Technical room", kind: "reading", icon: "bolt", cap: "view", actions: [], attrs: [{ key: "power", label: "Power", type: "number", unit: "W" }], allowed: true, hold: false, state: st({ value: 1840, value_text: "1840 W" }) },
    { id: "read:0xa7:co2", name: "Office CO₂", room: "Office", kind: "reading", icon: "", cap: "view", actions: [], attrs: [{ key: "co2", label: "CO2", type: "number", unit: "ppm" }], allowed: true, hold: false, state: st({ value: 1320, value_text: "1320 ppm" }) },
    { id: "status:alerts", name: "Alerts", room: null, kind: "status", icon: "bell", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ value: 2, value_text: "2 open alerts" }) },
    { id: "status:blocked", name: "Blocked addresses", room: null, kind: "status", icon: "wall", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ value: 0, value_text: "" }) },
    { id: "status:proxy", name: "Proxy", room: null, kind: "status", icon: "globe", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ on: true, value_text: "Running" }) },
    { id: "status:health", name: "Health", room: null, kind: "status", icon: "heart", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ on: true, value_text: "OK" }) },
    { id: "status:gateway", name: "Gateway", room: null, kind: "status", icon: "router", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ on: false, online: true, value_text: "Not answering" }) },
  ];
}

/**
 * (5.59.4) The summaries of PROTOCOL-5.59.4.md as an extended catalogue has them, and the deck SMS keys of
 * windows/PROTOCOL-SMS.md 3. Only an extended question sees these; `timer` is in the switches' actions only then.
 */
export function extendedItems(now = Math.floor(Date.now() / 1000)): FakeItem[] {
  const st = (o: Record<string, unknown>) => ({ on: null, value: null, value_text: "", attrs: {}, online: true, battery: null, at: null, ...o });
  const sys = (a: string[]) => Object.fromEntries(a.map((x) => [x, { cap: "system", allowed: true, hold: true }]));
  return [
    {
      id: "house:power", name: "House power", room: null, kind: "power", icon: "bolt", cap: "view", actions: [],
      attrs: [{ key: "power", label: "Power", type: "number", unit: "W", min: 0, max: null }], allowed: true, hold: false,
      state: st({ value: 1842.5, value_text: "1842.5 W", attrs: { power: 1842.5, kwh_today: 12.4, sockets_w: 1702.5, lights_w: 140, sockets_on: 4, lights_on: 3 } }),
    },
    {
      id: "status:security", name: "Network security", room: null, kind: "security", icon: "shield", cap: "status", actions: ["ack"], attrs: [], allowed: true, hold: false,
      act: sys(["ack"]),
      state: st({ on: false, value: 2, value_text: "2 standing", attrs: { level: "crit", alerts: 2, alerts_24h: 1, blocked: 14, blocked_24h: 37, guarding: true, latest: "Suricata: … scanned … from … (…), call …456 at 12:30:45", latest_at: now - 600 } }),
    },
    {
      id: "heat:group:all", name: "Heating in every room", room: null, kind: "heatgroup", icon: "heat", cap: "climate", actions: ["set"],
      attrs: [{ key: "mode", label: "Mode", type: "enum", values: ["plan", "comfort", "eco", "night", "max", "off", "manual"] }], allowed: true, hold: false,
      state: st({ on: true, value: "mixed", value_text: "mixed", attrs: { mode: "mixed", rooms: 4, calling: 1, min_temperature: 18.5, max_temperature: 21.0 } }),
    },
    {
      id: "house:away", name: "Away / Home", room: null, kind: "away", icon: "home", cap: "climate", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: false,
      state: st({ on: false, value_text: "home", attrs: { away: false, away_now: false, lights_on: 3, sockets_on: 2, rooms_heating: 1 } }),
    },
    {
      id: "house:openings", name: "Windows and doors", room: null, kind: "openings", icon: "contact", cap: "view", actions: [], attrs: [], allowed: true, hold: false,
      state: st({ on: false, value: 2, value_text: "2 open", attrs: { open: 2, sensors: 6, names: ["Okno ložnice", "Balkónové dveře"], heating_loss: true } }),
    },
    {
      id: "house:batteries", name: "Batteries", room: null, kind: "batteries", icon: "battery", cap: "view", actions: [], attrs: [], allowed: true, hold: false,
      state: st({ on: false, value: 5, value_text: "5 %", attrs: { level: "crit", below_20: 2, below_10: 1, lowest_name: "Dveře", lowest_pct: 5 } }),
    },
    {
      id: "status:zigbee", name: "Zigbee network", room: null, kind: "zigbee", icon: "router", cap: "status", actions: [], attrs: [], allowed: true, hold: false,
      state: st({ on: false, value: 23, value_text: "23 online, 1 offline", attrs: { level: "warn", online_n: 23, offline_n: 1, dropped_name: "Hlavice", dropped_at: now - 3000 } }),
    },
    {
      id: "room:r2", name: "Ložnice", room: "Ložnice", kind: "room", icon: "room", cap: "view", actions: [], attrs: [], allowed: true, hold: false,
      members: ["Lampa", "zb:0xa1:state_l1", "zb:0xc3:trv", "read:0xe5:temperature", "Garage"],
      state: st({ on: true, value: 20.5, value_text: "20.5 °C", attrs: { temperature: 20.5, humidity: 48, switches_on: 1, switches: 3, lights_on: 0, lights: 1, heated: true, heat_mode: "comfort", heat_target: 21, calling: true, members_n: 5 } }),
    },
    {
      id: "status:sms", name: "Text messages", room: null, kind: "sms", icon: "message", cap: "status", actions: ["mute", "unmute"], attrs: [], allowed: true, hold: false,
      act: sys(["mute", "unmute"]),
      state: st({ on: true, value: 3, value_text: "3 today", attrs: { level: "ok", modem_online: true, today: 3, last_from: "…123", last_person: "Jana", last_text: "Ahoj, router … is down", last_at: now - 900, muted_until: null } }),
    },
    {
      id: "sms:last", name: "Latest SMS", room: null, kind: "sms", icon: "message", cap: "sms", actions: ["run"], attrs: [], allowed: true, hold: false,
      state: st({ value: 3, value_text: "3 today", attrs: { last_from: "Jana Nováková", last_at: now - 900, unread: 2 } }),
    },
    {
      id: "sms:compose", name: "New SMS", room: null, kind: "sms", icon: "message", cap: "sms", actions: ["run"], attrs: [], allowed: true, hold: false,
      state: st({ value: 3, value_text: "3 today", attrs: { last_from: "…123", last_at: now - 900, unread: 0 } }),
    },
  ];
}

/**
 * (5.59.4, PROTOCOL-CALC.md) Values computed over the house, as an extended catalogue of a ZIGMon whose
 * hello says "calc" has them, in the server's own shape (test/review5594_calc.py): the attr with its
 * label and type, bounds null where unknown, a count's unit null, min_of / max_of null unless an
 * extreme. Rooms: r1 Obývák, r2 Ložnice, r3 Kitchen. No pressure or light level here.
 */
export function calcItems(): FakeItem[] {
  const UNIT: Record<string, string> = {
    power: "W", energy_today: "kWh", energy_total: "kWh", temperature: "°C", room_temperature: "°C", humidity: "%", co2: "ppm", battery: "%", linkquality: "",
  };
  const ICON: Record<string, string> = {
    power: "bolt", energy_today: "bolt", energy_total: "bolt", temperature: "thermo", room_temperature: "thermo", humidity: "drop", co2: "leaf", battery: "battery",
    battery_low: "battery", linkquality: "wifi", state: "bulbOn", open: "windowOpen", online: "mesh",
  };
  const ROOMS: Record<string, string> = { r1: "Obývák", r2: "Ložnice", r3: "Kitchen" };
  const c = (fn: string, metric: string, scope: string, name: string, value: number | null, members: number, o: { known?: number; min_of?: string; max_of?: string } = {}): FakeItem => {
    const counts = ["count", "on", "off"].includes(fn);
    const unit = fn === "pct_on" ? "%" : counts ? null : UNIT[metric] || null;
    const room = /^room=(r\d)/.exec(scope)?.[1];
    // the honest scale as the server gives it: % 0-100, a count 0..members, signal 0-255, from 0 for power, energy and a spread
    const [min, max] = unit === "%" ? [0, 100] : counts ? [0, members] : metric === "linkquality" ? [0, 255]
      : fn === "spread" || metric === "power" || metric.startsWith("energy") ? [0, null] : [null, null];
    const text = value === null ? "" : (Number.isInteger(value) ? String(value) : value.toFixed(1)) + (unit ? " " + unit : "");
    return {
      id: `calc:${fn}:${metric}:${scope}`, name, room: room ? ROOMS[room]! : null, kind: "calc", icon: ICON[metric] ?? "gauge", cap: "view", actions: [],
      attrs: [{ key: "value", label: name.split(" · ")[0], type: "number", unit, min, max }],
      allowed: true, hold: false,
      state: { on: null, value, value_text: text, online: value !== null, battery: null, at: null,
        attrs: { value, members, known: o.known ?? (value === null ? 0 : members), min_of: o.min_of ?? null, max_of: o.max_of ?? null } },
      calc: { fn, metric, scope, members, unit },
    };
  };
  return [
    c("sum", "power", "all", "Power · all", 412.5, 9, { known: 8 }),
    c("sum", "power", "kind=light", "Power · lights", 64, 4),
    c("sum", "power", "kind=socket", "Power · sockets", 348.5, 5, { known: 4 }),
    c("sum", "power", "room=r1", "Power · Obývák", 186, 3),
    c("sum", "power", "room=r1,kind=light", "Power · lights in Obývák", 42, 2),
    c("sum", "power", "room=r3", "Power · Kitchen", 120, 2),
    c("avg", "power", "kind=socket", "Average power · sockets", 87.1, 5, { known: 4 }),
    c("max", "power", "all", "Highest power · all", 1840, 9, { max_of: "Heat pump" }),
    c("sum", "energy_today", "all", "Energy today · all", 12.4, 6),
    c("sum", "energy_today", "kind=socket", "Energy today · sockets", 11.1, 5),
    c("sum", "energy_total", "all", "Energy total · all", 1843.2, 6),
    c("avg", "temperature", "inside", "Average temperature · inside", 21.3, 4),
    c("avg", "temperature", "all", "Average temperature · all", 17.5, 5),
    c("avg", "temperature", "outside", "Average temperature · outside", 7.3, 1),
    c("avg", "temperature", "room=r2", "Average temperature · Ložnice", 19.4, 2),
    c("min", "temperature", "inside", "Lowest temperature · inside", 18.5, 4, { min_of: "Ložnice" }),
    c("max", "temperature", "inside", "Highest temperature · inside", 23.1, 4, { max_of: "Obývák" }),
    c("min", "temperature", "all", "Lowest temperature · all", 7.3, 5, { min_of: "Outdoor temperature" }),
    c("spread", "temperature", "inside", "Temperature spread · inside", 4.6, 4, { min_of: "Ložnice", max_of: "Obývák" }),
    c("min", "room_temperature", "inside", "Coldest room · inside", 19.4, 3, { min_of: "Ložnice" }),
    c("max", "room_temperature", "inside", "Warmest room · inside", 23.1, 3, { max_of: "Obývák" }),
    c("avg", "room_temperature", "inside", "Average room temperature · inside", 21.2, 3),
    c("spread", "room_temperature", "inside", "Room temperature spread · inside", 3.7, 3, { min_of: "Ložnice", max_of: "Obývák" }),
    c("avg", "humidity", "inside", "Average humidity · inside", 48, 3),
    c("max", "humidity", "inside", "Highest humidity · inside", 61, 3, { max_of: "Koupelna" }),
    c("max", "co2", "inside", "Highest CO2 · inside", 1320, 2, { max_of: "Office CO₂" }),
    c("min", "battery", "all", "Lowest battery · all", 5, 11, { min_of: "Dveře" }),
    c("avg", "battery", "all", "Average battery · all", 71, 11),
    c("on", "battery_low", "all", "Low batteries · all", 2, 11),
    c("pct_on", "battery_low", "all", "Low batteries (%) · all", 18, 11),
    c("min", "linkquality", "all", "Weakest signal · all", 38, 24, { min_of: "Hlavice" }),
    c("on", "state", "kind=light", "Lights on · all", 3, 4),
    c("off", "state", "kind=light", "Lights off · all", 1, 4),
    c("pct_on", "state", "kind=light", "Lights on (%) · all", 75, 4),
    c("count", "state", "kind=light", "Lights (count) · all", 4, 4),
    c("on", "state", "kind=socket", "Sockets on · all", 2, 5),
    c("on", "state", "room=r1", "Things on · Obývák", 2, 3),
    c("on", "state", "room=r1,kind=light", "Lights on · Obývák", 1, 2),
    c("on", "open", "all", "Windows open · all", 2, 6),
    c("count", "open", "all", "Window sensors · all", 6, 6),
    c("off", "online", "all", "Devices offline · all", 1, 24),
    c("on", "online", "all", "Devices online · all", 23, 24),
    c("count", "online", "all", "Devices (count) · all", 24, 24),
  ];
}

/** `ids` as ZIGMon reads them: comma-separated, a `kind=` piece glued back onto the `calc:…:room=…` before it (PROTOCOL-CALC.md). */
export function splitIds(s: string): string[] {
  const out: string[] = [];
  for (const p of s.split(",")) {
    if (p.startsWith("kind=") && out.length && /^calc:[^:]+:[^:]+:room=[^,]+$/.test(out[out.length - 1]!)) out[out.length - 1] += "," + p;
    else out.push(p);
  }
  return out;
}

/** (PROTOCOL-SMS.md 3) An address book as the extended catalogue carries it: names and groups, no numbers. */
export function sampleBook(): { sms_contacts: { id: string; name: string; group: string | null; favourite: boolean }[]; sms_groups: string[] } {
  return {
    sms_contacts: [
      { id: "c_5f2a9e", name: "Jana Nováková", group: "Family", favourite: true },
      { id: "c_77b0c1", name: "Petr Novák", group: "Family", favourite: true },
      { id: "c_0a1b2c", name: "Eliška Dvořáková", group: "Family", favourite: false },
      { id: "c_9d8e7f", name: "Martin Svoboda", group: "Work", favourite: true },
      { id: "c_31c4d5", name: "Office reception", group: "Work", favourite: false },
      { id: "c_e6f708", name: "Tomáš Černý", group: "Neighbours", favourite: false },
      { id: "c_12ab34", name: "Lucie Horáková", group: null, favourite: false },
      { id: "c_56cd78", name: "Plumber - Karel", group: null, favourite: false },
    ],
    sms_groups: ["Family", "Neighbours", "Work"],
  };
}

export class FakeZigmon {
  enabled = true;
  items: FakeItem[] = sampleItems();
  /** (5.59.4) hello's features; [] = a ZIGMon before 5.59.4, which knows nothing of `extended`. */
  features: string[] = [];
  /** (5.59.4) The summaries, seen only by an extended question (or by naming them in ids). */
  extended: FakeItem[] = extendedItems();
  /** (5.59.4) The computed values, in an extended catalogue when hello's features say "calc" too. */
  calc: FakeItem[] = calcItems();
  /** (PROTOCOL-SMS.md 3) whether a desktop app linked to this Stream Deck is running. */
  desktopApp = false;
  /** (PROTOCOL-SMS.md 3) whether the linked app's key may (false: 409 not_allowed). */
  desktopAppMay = true;
  /** (PROTOCOL-SMS.md 3) the address book an extended catalogue carries (null: none, as without the cap sms). */
  smsBook: { sms_contacts: unknown[]; sms_groups: unknown[] } | null = sampleBook();
  /** Every question's road and whether it asked for the summaries. */
  asked: { do: string; method: string; extended: boolean }[] = [];
  boot = 1732700000;
  /** As a ZIGMon newer than 5.59.0, which sends a reading's recent values when asked (false: as 5.59.0). */
  withHistory = true;
  historyAsks: { ids: string[]; span: number; points: number }[] = [];
  seq = 100;
  changes: { seq: number; id: string }[] = [];
  /** sha256(token) -> install */
  tokens = new Map<string, { install: string; revoked: boolean; decks: Map<string, boolean> }>();
  pairs = new Map<string, { secret: string; code: string; install: string; expires: number; state: string; token?: string; decks: { id: string }[] }>();
  seen: Seen[] = [];
  commands: Record<string, unknown>[] = [];
  autoApprove = false;
  pairWaitMs = 300;
  waitMs = 400;
  plugin: { version: string } | null = null;
  update: Record<string, unknown> | null = null;
  download: Buffer | null = null;
  redirectEverything = false;
  private server: http.Server | https.Server | null = null;
  private waiters = new Set<() => void>();

  port = 0;

  constructor(private readonly tls?: { key: string; cert: string }) {}

  async start(port: number): Promise<void> {
    const handler = (req: http.IncomingMessage, res: http.ServerResponse) => void this.handle(req, res);
    this.server = this.tls ? https.createServer({ key: this.tls.key, cert: this.tls.cert }, handler) : http.createServer(handler);
    await new Promise<void>((resolve, reject) => {
      this.server!.once("error", reject);
      this.server!.listen(port, "127.0.0.1", () => resolve());
    });
    this.port = (this.server.address() as AddressInfo).port;
  }

  async stop(): Promise<void> {
    for (const w of this.waiters) w();
    if (!this.server) return;
    this.server.closeAllConnections?.();
    await new Promise<void>((r) => this.server!.close(() => r()));
  }

  /** Approve every pending request (as the administrator would, with all its decks). */
  approveAll(): void {
    for (const [id, p] of this.pairs) if (p.state === "pending") this.approve(id);
  }

  approve(pairId: string): string {
    const p = this.pairs.get(pairId)!;
    const token = "zsd_" + randomBytes(30).toString("base64url").slice(0, 40);
    p.state = "approved";
    p.token = token;
    this.tokens.set(sha(token), { install: p.install, revoked: false, decks: new Map(p.decks.map((d) => [d.id, true])) });
    this.wake();
    return token;
  }

  deny(pairId: string): void {
    this.pairs.get(pairId)!.state = "denied";
    this.wake();
  }

  revokeAll(): void {
    for (const t of this.tokens.values()) t.revoked = true;
    this.wake();
  }

  setState(id: string, patch: Record<string, unknown>): void {
    const it = [...this.items, ...this.extended, ...this.calc].find((i) => i.id === id)!;
    const attrs: Record<string, unknown> = { ...(it.state.attrs as object), ...((patch.attrs as object) ?? {}) };
    for (const [k, v] of Object.entries(attrs)) if (v === undefined) delete attrs[k];
    it.state = { ...it.state, ...patch, attrs };
    this.seq++;
    this.changes.push({ seq: this.seq, id });
    this.wake();
  }

  private wake(): void {
    for (const w of [...this.waiters]) w();
  }

  private hold(ms: number, until: () => boolean): Promise<void> {
    return new Promise((resolve) => {
      if (until()) return resolve();
      const done = () => {
        clearTimeout(t);
        this.waiters.delete(check);
        resolve();
      };
      const check = () => {
        if (until()) done();
      };
      const t = setTimeout(done, ms);
      this.waiters.add(check);
    });
  }

  private async handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const u = new URL(req.url ?? "/", "http://x");
    const send = (status: number, body: unknown, headers: Record<string, string> = {}) => {
      const b = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
      res.writeHead(status, { "Content-Type": Buffer.isBuffer(body) ? "application/octet-stream" : "application/json", "Content-Length": String(b.length), ...headers });
      res.end(b);
    };
    const chunks: Buffer[] = [];
    for await (const c of req) chunks.push(c as Buffer);
    let body: unknown = null;
    if (chunks.length) try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { body = "bad"; }
    const what = u.searchParams.get("do") ?? "";
    this.seen.push({ do: what, method: req.method ?? "", headers: req.headers, query: u.searchParams, body });
    if (this.redirectEverything) return send(302, {}, { Location: "https://elsewhere.example/" });
    if (u.pathname !== "/index.php" || u.searchParams.get("api") !== "deck") return send(404, { ok: false, error: "not found" });
    if (!this.enabled) return send(403, { ok: false, error: "Stream Deck control is switched off in ZIGMon", off: true });

    if (what === "pair") {
      const b = body as Record<string, unknown>;
      const pair = randomBytes(12).toString("hex");
      const secret = "zsp_" + randomBytes(30).toString("base64url").slice(0, 40);
      let code = "";
      for (let i = 0; i < 6; i++) code += CODE_CHARS[randomBytes(1)[0]! % CODE_CHARS.length];
      const expires = Math.floor(Date.now() / 1000) + 900;
      this.pairs.set(pair, { secret, code, install: String(b.install), expires, state: "pending", decks: (b.decks as { id: string }[]) ?? [] });
      if (this.autoApprove) setTimeout(() => this.approve(pair), 150);
      return send(200, { ok: true, pair, secret, code: code.slice(0, 3) + "-" + code.slice(3), expires });
    }
    if (what === "pair_wait") {
      const secret = req.headers["x-zigmon-deck-pair"];
      const entry = [...this.pairs.entries()].find(([, p]) => p.secret === secret);
      if (!entry) return send(401, { ok: false, error: "unknown pairing request" });
      const [, p] = entry;
      await this.hold(this.pairWaitMs, () => p.state !== "pending");
      if (p.state === "approved" && p.token) {
        const token = p.token;
        p.state = "done";
        return send(200, { ok: true, state: "approved", token, install: { id: p.install, name: "OFFICE-PC", caps: {}, hint: token.slice(-2) } });
      }
      return send(200, { ok: true, state: p.state === "done" ? "expired" : p.state });
    }

    // everything else needs the key
    const tok = String(req.headers["x-zigmon-deck"] ?? "");
    const inst = String(req.headers["x-zigmon-deck-install"] ?? "");
    const t = this.tokens.get(sha(tok));
    if (!t) return send(401, { ok: false, error: "This Stream Deck is not known to ZIGMon" });
    if (t.revoked) return send(401, { ok: false, error: "This Stream Deck was disconnected in ZIGMon", revoked: true });
    if (t.install !== inst) return send(401, { ok: false, error: "This Stream Deck is not known to ZIGMon" });
    for (const id of (u.searchParams.get("decks") ?? "").split(",").filter(Boolean)) if (!t.decks.has(id)) t.decks.set(id, false);

    const b0 = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
    // (5.59.4) asked through the relay as a POST body, or straight with ?extended=1
    const ext = this.features.includes("extended") && (b0.extended === true || u.searchParams.get("extended") === "1");
    this.asked.push({ do: what, method: req.method ?? "", extended: b0.extended === true || u.searchParams.get("extended") === "1" });
    const switchActions = (i: FakeItem) => (ext && i.cap === "switch" && i.actions.includes("toggle") ? [...i.actions, "timer"] : i.actions);
    const item = (i: FakeItem) => {
      const o: Record<string, unknown> = { ...i, actions: switchActions(i) };
      if (!ext) {
        delete o.act;
        delete o.members;
      }
      return o;
    };
    const all = () => [...this.items, ...(this.features.includes("extended") ? this.extended : []), ...(this.features.includes("extended") && this.features.includes("calc") ? this.calc : [])];
    switch (what) {
      case "hello":
        return send(200, {
          ok: true, api: 1, server: "zigmon", version: this.features.length ? "5.59.4" : "5.59.0", house: "Chalupa", boot: this.boot, seq: this.seq,
          ...(this.features.length ? { features: this.features } : {}),
          install: { id: t.install, name: "OFFICE-PC", hint: "x9", caps: { view: { on: true, all: true, targets: [] }, switch: { on: true, all: false, targets: ["Lampa", "Garage"], hold: true }, dim: { on: true, all: true, targets: [], hold: false }, climate: { on: true, all: true, targets: [], hold: false }, status: { on: true } } },
          decks: [...t.decks.entries()].map(([id, approved]) => ({ id, type: 2, name: "Deck", approved })),
          plugin: this.plugin,
        });
      case "catalog":
        return send(200, {
          ok: true, boot: this.boot, seq: this.seq, rooms: [{ id: "1", name: "Obývák" }, { id: "2", name: "Kitchen" }], items: (ext ? all() : this.items).map(item),
          // (PROTOCOL-SMS.md 3) the address book, only in the extended catalogue of an installation with the cap sms
          ...(ext && this.features.includes("sms") && this.smsBook ? this.smsBook : {}),
        });
      case "state": {
        const b = (body && typeof body === "object" ? body : {}) as { ids?: string; history?: { span?: number; points?: number } };
        const ids = splitIds(u.searchParams.get("ids") ?? b.ids ?? "");
        const items: Record<string, unknown> = {};
        for (const i of all()) if (ids.includes(i.id)) items[i.id] = i.state;
        if (!b.history || !this.withHistory) return send(200, { ok: true, boot: this.boot, seq: this.seq, items });
        // as a ZIGMon newer than 5.59.0: the readings' recent values, thinned
        this.historyAsks.push({ ids, span: Number(b.history.span), points: Number(b.history.points) });
        const history: Record<string, unknown> = {};
        const now = Math.floor(Date.now() / 1000);
        for (const i of all()) {
          if (!ids.includes(i.id) || (i.kind !== "reading" && i.kind !== "thermostat" && i.kind !== "power" && i.kind !== "calc")) continue;
          const v = Number((i.state as Record<string, unknown>).value ?? 20);
          const n = Math.min(48, Number(b.history.points) || 48), span = Number(b.history.span) || 86400;
          history[i.id] = { span, points: Array.from({ length: n }, (_, k) => [now - span + Math.round((k * span) / n), Math.round((v + Math.sin(k / 4) * 2) * 100) / 100]) };
        }
        return send(200, { ok: true, boot: this.boot, seq: this.seq, items, history });
      }
      case "wait": {
        const after = Number(u.searchParams.get("after") ?? b0.after);
        const boot = u.searchParams.get("boot") ?? (b0.boot === undefined ? null : String(b0.boot));
        if (String(this.boot) !== boot) return send(200, { ok: true, boot: this.boot, seq: this.seq, reset: true, changes: [] });
        const idq = u.searchParams.get("ids") ?? (typeof b0.ids === "string" ? b0.ids : null);
        const ids = idq === null ? undefined : splitIds(idq);
        const summary = new Set([...this.extended, ...this.calc].map((i) => i.id));
        const relevant = () => this.changes.filter((c) => c.seq > after && (ids ? ids.includes(c.id) : ext || !summary.has(c.id)));
        await this.hold(this.waitMs, () => relevant().length > 0 || t.revoked);
        if (t.revoked) return send(401, { ok: false, error: "revoked", revoked: true });
        const latest = new Map<string, number>();
        for (const c of relevant()) latest.set(c.id, c.seq);
        return send(200, {
          ok: true, boot: this.boot, seq: this.seq, reset: false,
          changes: [...latest.entries()].map(([id, seq]) => ({ seq, id, state: all().find((i) => i.id === id)!.state })),
        });
      }
      case "do": {
        const b = (body ?? {}) as Record<string, unknown>;
        this.commands.push(b);
        const deck = String(b.deck ?? "");
        if (!t.decks.get(deck)) {
          t.decks.set(deck, false);
          return send(403, { ok: false, error: "This Stream Deck is not approved in ZIGMon yet", deck_pending: true });
        }
        const it = all().find((i) => i.id === b.id);
        if (!it) return send(404, { ok: false, error: "No such item" });
        const a = String(b.action);
        // (5.59.4) an action with a capability of its own: its own grant, and always held
        const g = it.act?.[a];
        if (g ? !g.allowed : !it.allowed) return send(403, g ? { ok: false, error: "Not allowed for this Stream Deck", allowed: false, cap: g.cap } : { ok: false, error: "Not allowed for this Stream Deck" });
        if ((g ? g.hold : it.hold) && !(typeof b.held_ms === "number" && b.held_ms >= 1500)) return send(409, { ok: false, error: "Hold the key to confirm", hold: true });
        const timerOk = a === "timer" && it.cap === "switch" && it.actions.includes("toggle");
        if (!it.actions.includes(a) && !timerOk) return send(400, { ok: false, error: "That item cannot " + a });
        const s = it.state as Record<string, unknown>;
        const attrsOf = () => ({ ...(s.attrs as Record<string, unknown>) });
        if (a === "timer") {
          if (typeof b.minutes !== "number" || !Number.isInteger(b.minutes) || b.minutes < 1 || b.minutes > 720) return send(400, { ok: false, error: "minutes must be 1-720" });
          this.setState(it.id, { on: true, attrs: { off_at: Math.ceil(Date.now() / 1000) + b.minutes * 60 } });
        } else if (a === "ack") {
          const n = Number((s.attrs as Record<string, unknown>).alerts ?? 0);
          if (n <= 0) return send(409, { ok: false, error: "there is no alert standing", nothing: true });
          this.setState(it.id, { value: n - 1, on: n - 1 === 0, attrs: { alerts: n - 1, level: n - 1 ? "crit" : "ok" } });
        } else if (a === "mute") {
          if (typeof b.minutes !== "number" || !Number.isInteger(b.minutes) || b.minutes < 15 || b.minutes > 240) return send(400, { ok: false, error: "minutes must be 15-240" });
          this.setState(it.id, { attrs: { muted_until: Math.floor(Date.now() / 1000) + b.minutes * 60 } });
        } else if (a === "unmute") this.setState(it.id, { attrs: { muted_until: null } });
        else if (a === "run" && it.cap === "sms") {
          if (b.to !== undefined) {
            if (!Array.isArray(b.to) || b.to.length > 20) return send(400, { ok: false, error: "to must be a list of at most 20" });
            const ids = new Set(((this.smsBook?.sms_contacts ?? []) as { id: string }[]).map((c) => "contact:" + c.id));
            const groups = ((this.smsBook?.sms_groups ?? []) as string[]).map((g) => "group:" + g.toLowerCase());
            const bad = (b.to as unknown[]).filter((x) => typeof x !== "string" || (x.startsWith("contact:") ? !ids.has(x) : x.startsWith("group:") ? !groups.includes(x.toLowerCase()) : !/^\+?\d{3,20}$/.test(x)));
            if (bad.length) return send(400, { ok: false, error: bad[0] + " is not a contact, a group or a phone number here" + (bad.length > 1 ? " (and " + (bad.length - 1) + " more)" : ""), bad_to: bad });
          }
          if (!this.desktopApp) return send(409, { ok: false, error: "no desktop app linked to this Stream Deck is running", apps: 0, no_app: true });
          if (!this.desktopAppMay) return send(409, { ok: false, error: "the desktop app linked to this Stream Deck may not " + (it.id === "sms:last" ? "read" : "send") + " SMS", apps: 1, not_allowed: true });
          this.setState(it.id, {});
        } else if (a === "toggle" && it.id === "house:away") {
          const away = !(s.attrs as Record<string, unknown>).away;
          this.setState(it.id, { on: away, value_text: away ? "away" : "home", attrs: { away } });
        } else if (a === "toggle") this.setState(it.id, { on: !s.on, attrs: s.on ? { ...attrsOf(), off_at: undefined } : {} });
        else if (a === "on" || a === "off") this.setState(it.id, { on: a === "on", ...(a === "off" ? { attrs: { off_at: undefined } } : {}) });
        else if (a === "set") {
          const attr = it.attrs.find((x) => x.key === b.attr);
          if (!attr) return send(400, { ok: false, error: "no such attribute" });
          if (attr.type === "number") {
            const cur = Number((s.attrs as Record<string, unknown>)[attr.key as string] ?? 0);
            let v = typeof b.delta === "number" ? cur + b.delta : Number(b.value);
            if (!Number.isFinite(v)) return send(400, { ok: false, error: "not a number" });
            const step = Number(attr.step ?? 1);
            v = Math.min(Number(attr.max ?? Infinity), Math.max(Number(attr.min ?? -Infinity), Math.round(v / step) * step));
            this.setState(it.id, { attrs: { [attr.key as string]: v } });
          } else if (attr.type === "enum") {
            if (!(attr.values as string[]).includes(String(b.value))) return send(400, { ok: false, error: "not one of its values" });
            this.setState(it.id, { attrs: { [attr.key as string]: b.value } });
          } else this.setState(it.id, { attrs: { [attr.key as string]: b.value } });
        } else this.setState(it.id, {});
        return send(200, { ok: true, said: a + " " + it.name, state: it.state });
      }
      case "update":
        return send(200, this.update ?? { ok: true, available: false });
      case "download":
        return this.download ? send(200, this.download, { "Content-Disposition": 'attachment; filename="ZIGMon.streamDeckPlugin"' }) : send(404, { ok: false, error: "none" });
      default:
        return send(400, { ok: false, error: "unknown do" });
    }
  }
}

function sha(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

/** A Store keeping the global settings in memory, as Stream Deck would. */
export class MemoryStore {
  saved: Record<string, unknown>[] = [];
  constructor(public value: Record<string, unknown> = {}) {}
  async load(): Promise<unknown> {
    return JSON.parse(JSON.stringify(this.value));
  }
  async save(g: Record<string, unknown>): Promise<void> {
    this.value = JSON.parse(JSON.stringify(g));
    this.saved.push(this.value);
  }
}

/** A mock Stream Deck key or dial: keeps what was drawn on it. */
export class MockSurface {
  images: string[] = [];
  feedbacks: Record<string, unknown>[] = [];
  alerts = 0;
  oks = 0;
  triggers: unknown[] = [];
  constructor(readonly controller: "Keypad" | "Encoder", readonly deckId: string) {}
  setImage(i: string): void {
    this.images.push(i);
  }
  setFeedback(f: Record<string, unknown>): void {
    this.feedbacks.push(f);
  }
  setTriggerDescription(d: unknown): void {
    this.triggers.push(d);
  }
  showAlert(): void {
    this.alerts++;
  }
  showOk(): void {
    this.oks++;
  }
  /** The last key image as SVG text. */
  get svg(): string {
    const last = this.images[this.images.length - 1] ?? "";
    const b64 = last.split(",")[1] ?? "";
    return Buffer.from(b64, "base64").toString("utf8");
  }
}

export async function until(cond: () => boolean, ms = 5000, what = "condition"): Promise<void> {
  const end = Date.now() + ms;
  while (!cond()) {
    if (Date.now() > end) throw new Error("timed out waiting for " + what);
    await new Promise((r) => setTimeout(r, 15));
  }
}
