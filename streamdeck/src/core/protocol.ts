/**
 * The deck API of ZIGMon (contract v1), parsed strictly: every answer is checked field by
 * field, text is cleaned and shortened, and anything unexpected becomes a ProtocolError.
 * Nothing the server sends is trusted to be well-formed; the renderers escape it again.
 */

export class ProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProtocolError";
  }
}

export const CAPS = ["view", "switch", "dim", "climate", "cover", "scenes", "automations", "messages", "system", "status"] as const;
export type Cap = (typeof CAPS)[number];

export const KINDS = [
  "socket", "light", "switch", "dimmer", "thermostat", "cover", "scene", "sequence", "group",
  "rule", "schedule", "message", "system", "sensor", "reading", "status",
] as const;
export type Kind = (typeof KINDS)[number];

export const ACTIONS = ["toggle", "on", "off", "run", "set", "open", "close", "stop", "step"] as const;
export type ItemAction = (typeof ACTIONS)[number];

export interface CapGrant {
  on: boolean;
  all: boolean;
  targets: string[];
  hold: boolean;
}
export type Caps = Partial<Record<Cap, CapGrant>>;

export interface Attr {
  key: string;
  label: string;
  type: "number" | "enum" | "bool" | "text";
  unit: string;
  min: number | null;
  max: number | null;
  step: number | null;
  values: string[];
}

export interface ItemState {
  on: boolean | null;
  value: number | null;
  valueText: string;
  attrs: Record<string, number | string | boolean | null>;
  online: boolean;
  battery: number | null;
  at: number | null;
}

export interface Item {
  id: string;
  name: string;
  room: string | null;
  kind: Kind | "other";
  icon: string;
  cap: Cap;
  actions: ItemAction[];
  attrs: Attr[];
  allowed: boolean;
  hold: boolean;
  state: ItemState;
}

export interface Room {
  id: string;
  name: string;
}

export interface DeckStatus {
  id: string;
  type: number;
  name: string;
  approved: boolean;
}

export interface Install {
  id: string;
  name: string;
  caps: Caps;
  hint: string;
}

export interface Hello {
  api: number;
  version: string;
  house: string;
  boot: string;
  seq: number;
  install: Install;
  decks: DeckStatus[];
  plugin: { version: string } | null;
}

export interface Catalog {
  boot: string;
  seq: number;
  rooms: Room[];
  items: Item[];
}

export interface StateAnswer {
  boot: string;
  seq: number;
  items: Map<string, ItemState>;
  /** (for Stream Deck 1.1) The recent values of readings and thermostats, when they were asked for. */
  history: Map<string, Series>;
}

/** A thinned series ZIGMon keeps for an item: [unix seconds, value], oldest first. */
export interface Series {
  span: number;
  points: [number, number][];
}

export function parseSeries(v: unknown): Series | null {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  const span = num(o.span);
  if (span === null || span <= 0 || span > 31 * 86400 || !Array.isArray(o.points)) return null;
  const points: [number, number][] = [];
  for (const p of o.points.slice(-200)) {
    if (!Array.isArray(p) || p.length < 2) continue;
    const t = num(p[0]), x = num(p[1]);
    if (t === null || x === null || Math.abs(x) > 1e9) continue;
    if (points.length && t < points[points.length - 1]![0]) continue;
    points.push([t, x]);
  }
  return { span, points };
}

export interface Change {
  seq: number;
  id: string;
  state: ItemState;
}

export interface WaitAnswer {
  boot: string;
  seq: number;
  reset: boolean;
  changes: Change[];
}

export interface PairStart {
  pair: string;
  secret: string;
  code: string;
  expires: number;
}

export type PairWaitState = "pending" | "approved" | "denied" | "expired";
export interface PairWait {
  state: PairWaitState;
  token: string | null;
  install: Install | null;
}

export interface DoAnswer {
  said: string;
  state: ItemState | null;
}

export interface UpdateAnswer {
  available: boolean;
  version: string;
  size: number;
  sha256: string;
  manifest: Buffer;
  sig: Buffer;
}

// ---------------------------------------------------------------- text

/** Printable text only: control characters, bidi overrides and other invisibles removed, trimmed, cut at max. */
export function cleanText(v: unknown, max: number): string {
  if (typeof v !== "string" && typeof v !== "number") return "";
  let s = String(v)
    .replace(/[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\ufff9-\ufffb]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if ([...s].length > max) s = [...s].slice(0, Math.max(0, max - 1)).join("").trimEnd() + "…";
  return s;
}

const ID_RE = /^[^\u0000-\u001f\u007f]{1,160}$/;
const TOKEN_RE = /^zsd_[A-Za-z0-9_-]{20,80}$/;
const SECRET_RE = /^zsp_[A-Za-z0-9_-]{20,80}$/;
const PAIR_RE = /^[0-9a-f]{24}$/;
const CODE_RE = /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{3}-?[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{3}$/;

export function isToken(s: unknown): s is string {
  return typeof s === "string" && TOKEN_RE.test(s);
}

function obj(v: unknown, what: string): Record<string, unknown> {
  if (v === null || typeof v !== "object" || Array.isArray(v)) throw new ProtocolError(what + " is not an object");
  return v as Record<string, unknown>;
}
function arr(v: unknown, what: string, max: number): unknown[] {
  if (v === undefined || v === null) return [];
  if (!Array.isArray(v)) throw new ProtocolError(what + " is not a list");
  return v.slice(0, max);
}
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function int(v: unknown, what: string): number {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < 0) throw new ProtocolError(what + " is not a number");
  return v;
}
function bool(v: unknown): boolean {
  return v === true;
}
function str(v: unknown, max: number): string {
  return cleanText(v, max);
}
function bootOf(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string" && /^[A-Za-z0-9._:-]{1,64}$/.test(v)) return v;
  throw new ProtocolError("boot is missing");
}

/** Every answer must be a JSON object with ok:true; an error answer becomes an ApiError by the caller. */
export function okObject(v: unknown): Record<string, unknown> {
  const o = obj(v, "the answer");
  if (o.ok !== true) throw new ProtocolError(cleanText(o.error, 200) || "ZIGMon refused");
  return o;
}

export function parseId(v: unknown): string {
  if (typeof v !== "string" || !ID_RE.test(v)) throw new ProtocolError("an item has no id");
  return v;
}

export function parseCaps(v: unknown): Caps {
  const out: Caps = {};
  if (v === null || typeof v !== "object" || Array.isArray(v)) return out;
  const o = v as Record<string, unknown>;
  for (const c of CAPS) {
    const g = o[c];
    if (g === null || typeof g !== "object" || Array.isArray(g)) continue;
    const gg = g as Record<string, unknown>;
    out[c] = {
      on: bool(gg.on),
      all: bool(gg.all),
      targets: arr(gg.targets, "targets", 2000).filter((t): t is string => typeof t === "string" && ID_RE.test(t)),
      hold: bool(gg.hold),
    };
  }
  return out;
}

export function parseInstall(v: unknown): Install {
  const o = obj(v, "install");
  const id = typeof o.id === "string" && /^[0-9a-f]{32}$/.test(o.id) ? o.id : "";
  return { id, name: str(o.name, 60), caps: parseCaps(o.caps), hint: str(o.hint, 8) };
}

function parseAttrValue(v: unknown): number | string | boolean | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "boolean") return v;
  if (typeof v === "string") return cleanText(v, 60);
  return null;
}

export function parseState(v: unknown): ItemState {
  const o = v === null || typeof v !== "object" || Array.isArray(v) ? {} : (v as Record<string, unknown>);
  const attrs: Record<string, number | string | boolean | null> = {};
  if (o.attrs && typeof o.attrs === "object" && !Array.isArray(o.attrs)) {
    let n = 0;
    for (const [k, val] of Object.entries(o.attrs as Record<string, unknown>)) {
      if (n++ >= 40) break;
      if (!/^[A-Za-z0-9_.:-]{1,64}$/.test(k)) continue;
      attrs[k] = parseAttrValue(val);
    }
  }
  const battery = num(o.battery);
  return {
    on: o.on === true ? true : o.on === false ? false : null,
    value: num(o.value),
    valueText: str(o.value_text, 40),
    attrs,
    online: o.online !== false,
    battery: battery === null ? null : Math.max(0, Math.min(100, Math.round(battery))),
    at: num(o.at),
  };
}

export function parseAttr(v: unknown): Attr | null {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  if (typeof o.key !== "string" || !/^[A-Za-z0-9_.:-]{1,64}$/.test(o.key)) return null;
  const type = o.type === "number" || o.type === "enum" || o.type === "bool" ? o.type : "text";
  const values = arr(o.values, "values", 40).filter((x): x is string => typeof x === "string").map((x) => cleanText(x, 40)).filter(Boolean);
  let min = num(o.min), max = num(o.max);
  if (min !== null && max !== null && min > max) [min, max] = [max, min];
  const step = num(o.step);
  return {
    key: o.key,
    label: str(o.label, 40) || o.key,
    type,
    unit: str(o.unit, 8),
    min,
    max,
    step: step !== null && step > 0 ? step : null,
    values,
  };
}

export function parseItem(v: unknown): Item {
  const o = obj(v, "an item");
  const id = parseId(o.id);
  const kind = (KINDS as readonly string[]).includes(o.kind as string) ? (o.kind as Kind) : "other";
  const cap = (CAPS as readonly string[]).includes(o.cap as string) ? (o.cap as Cap) : "view";
  const actions = arr(o.actions, "actions", 12).filter((a): a is ItemAction => (ACTIONS as readonly string[]).includes(a as string));
  const attrs = arr(o.attrs, "attrs", 24).map(parseAttr).filter((a): a is Attr => a !== null);
  return {
    id,
    name: str(o.name, 80) || id,
    room: o.room === null || o.room === undefined ? null : str(o.room, 60) || null,
    kind,
    icon: typeof o.icon === "string" ? o.icon.slice(0, 40) : "",
    cap,
    actions: [...new Set(actions)],
    attrs,
    allowed: bool(o.allowed),
    hold: bool(o.hold),
    state: parseState(o.state),
  };
}

export function parseHello(v: unknown): Hello {
  const o = okObject(v);
  if (o.server !== "zigmon") throw new ProtocolError("this is not a ZIGMon server");
  const api = int(o.api, "api");
  if (api !== 1) throw new ProtocolError("ZIGMon speaks deck API " + api + "; this plugin knows 1");
  const decks = arr(o.decks, "decks", 32).map((d) => {
    const dd = obj(d, "a deck");
    return {
      id: typeof dd.id === "string" ? dd.id.slice(0, 80) : "",
      type: typeof dd.type === "number" && Number.isInteger(dd.type) ? dd.type : -1,
      name: str(dd.name, 60),
      approved: bool(dd.approved),
    };
  }).filter((d) => d.id.length > 0);
  let plugin: { version: string } | null = null;
  if (o.plugin && typeof o.plugin === "object" && !Array.isArray(o.plugin)) {
    const pv = (o.plugin as Record<string, unknown>).version;
    if (typeof pv === "string" && /^\d{1,9}(\.\d{1,9}){0,3}$/.test(pv)) plugin = { version: pv };
  }
  return {
    api,
    version: str(o.version, 24),
    house: str(o.house, 60),
    boot: bootOf(o.boot),
    seq: int(o.seq, "seq"),
    install: parseInstall(o.install),
    decks,
    plugin,
  };
}

export function parseCatalog(v: unknown): Catalog {
  const o = okObject(v);
  const rooms = arr(o.rooms, "rooms", 500).map((r) => {
    const rr = obj(r, "a room");
    return { id: str(rr.id, 60), name: str(rr.name, 60) };
  }).filter((r) => r.name.length > 0);
  const seen = new Set<string>();
  const items: Item[] = [];
  for (const raw of arr(o.items, "items", 5000)) {
    let it: Item;
    try {
      it = parseItem(raw);
    } catch {
      continue; // one bad item does not hide the rest
    }
    if (seen.has(it.id)) continue;
    seen.add(it.id);
    items.push(it);
  }
  return { boot: bootOf(o.boot), seq: int(o.seq, "seq"), rooms, items };
}

export function parseStateAnswer(v: unknown): StateAnswer {
  const o = okObject(v);
  const items = new Map<string, ItemState>();
  if (o.items && typeof o.items === "object" && !Array.isArray(o.items)) {
    for (const [id, st] of Object.entries(o.items as Record<string, unknown>)) {
      if (!ID_RE.test(id)) continue;
      items.set(id, parseState(st));
    }
  }
  const history = new Map<string, Series>();
  if (o.history && typeof o.history === "object" && !Array.isArray(o.history)) {
    for (const [id, se] of Object.entries(o.history as Record<string, unknown>).slice(0, 64)) {
      const x = ID_RE.test(id) ? parseSeries(se) : null;
      if (x) history.set(id, x);
    }
  }
  return { boot: bootOf(o.boot), seq: int(o.seq, "seq"), items, history };
}

export function parseWait(v: unknown): WaitAnswer {
  const o = okObject(v);
  const changes: Change[] = [];
  for (const c of arr(o.changes, "changes", 200)) {
    if (c === null || typeof c !== "object" || Array.isArray(c)) continue;
    const cc = c as Record<string, unknown>;
    if (typeof cc.id !== "string" || !ID_RE.test(cc.id)) continue;
    changes.push({ seq: typeof cc.seq === "number" ? cc.seq : 0, id: cc.id, state: parseState(cc.state) });
  }
  return { boot: bootOf(o.boot), seq: int(o.seq, "seq"), reset: bool(o.reset), changes };
}

export function formatCode(code: string): string {
  const c = code.replace("-", "");
  return c.slice(0, 3) + "-" + c.slice(3);
}

export function parsePairStart(v: unknown): PairStart {
  const o = okObject(v);
  if (typeof o.pair !== "string" || !PAIR_RE.test(o.pair)) throw new ProtocolError("the pairing answer has no request id");
  if (typeof o.secret !== "string" || !SECRET_RE.test(o.secret)) throw new ProtocolError("the pairing answer has no secret");
  if (typeof o.code !== "string" || !CODE_RE.test(o.code)) throw new ProtocolError("the pairing answer has no code");
  const expires = num(o.expires);
  if (expires === null || expires <= 0) throw new ProtocolError("the pairing answer has no expiry");
  return { pair: o.pair, secret: o.secret, code: formatCode(o.code), expires };
}

export function parsePairWait(v: unknown): PairWait {
  const o = obj(v, "the answer");
  const state = o.state;
  if (state !== "pending" && state !== "approved" && state !== "denied" && state !== "expired") {
    if (o.ok === false) throw new ProtocolError(cleanText(o.error, 200) || "ZIGMon refused");
    throw new ProtocolError("the pairing state is unknown");
  }
  if (state === "approved") {
    if (!isToken(o.token)) throw new ProtocolError("ZIGMon approved but sent no key");
    return { state, token: o.token, install: o.install ? parseInstall(o.install) : null };
  }
  return { state, token: null, install: null };
}

export function parseDo(v: unknown): DoAnswer {
  const o = okObject(v);
  return { said: str(o.said, 120), state: o.state && typeof o.state === "object" ? parseState(o.state) : null };
}

export function parseUpdate(v: unknown): UpdateAnswer {
  const o = okObject(v);
  const available = bool(o.available);
  if (!available) return { available, version: "", size: 0, sha256: "", manifest: Buffer.alloc(0), sig: Buffer.alloc(0) };
  const b64 = (x: unknown, what: string, max: number): Buffer => {
    if (typeof x !== "string" || x.length > max * 2 || !/^[A-Za-z0-9+/=_-]*$/.test(x)) throw new ProtocolError("the update has no " + what);
    return Buffer.from(x, "base64");
  };
  return {
    available,
    version: typeof o.version === "string" ? o.version.slice(0, 24) : "",
    size: typeof o.size === "number" && Number.isSafeInteger(o.size) ? o.size : -1,
    sha256: typeof o.sha256 === "string" ? o.sha256.slice(0, 64).toLowerCase() : "",
    manifest: b64(o.manifest, "manifest", 4096),
    sig: b64(o.sig, "signature", 128),
  };
}
