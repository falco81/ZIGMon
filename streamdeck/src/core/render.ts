/**
 * The keys, drawn as 144x144 SVG in ZIGMon's dashboard style: a dark panel, one accent colour
 * per kind of thing, a stroke icon in a tinted tile, the state big, the name and room small.
 * Only plain SVG (rect, circle, path, text, linear gradients) - what Stream Deck's renderer draws.
 * Every piece of text passes through esc(); colours and icons come from our own tables only.
 */
import { P } from "./palette.js";
import { arcPath, esc, fit, fitSize, fitSizeK, grow, growAll, icon, mixLine, n, nameLines, ONE, rect, roleAttr, svgDoc, text, textWidth, wrap2, type NameFit, type TextRole, type TextScale } from "./svg.js";
import { seriesScale, type Quantity } from "./scale.js";
import { graph, type Face, type Info } from "./themes.js";

/**
 * (1.1) What the Classic look is asked beyond 1.0: which information to show, an accent colour
 * and how long names are laid out. Left out (as for every key set up before 1.1), Classic
 * draws exactly what 1.0 drew.
 */
export interface ClassicOpts {
  info?: Info;
  accent?: string;
  fit?: NameFit;
  /** (1.3) The colour an off key is drawn in (its tile, icon, dot, edge); none = grey, as before. */
  offAccent?: string;
  /** (1.3) The size of each kind of text; none = as before. */
  ts?: TextScale;
}
const SHOW_ALL: Info = { icon: true, name: true, room: true, state: true, detail: true, mode: true, graph: true, battery: true, scale: false, target: false };

/** (1.3) How far a size may grow where Classic has fixed places: the role's own limit on its size. */
const CAPF: Record<TextRole, number> = { value: 1.4, name: 1.45, room: 1.5, detail: 1.5, mode: 1.5, unit: 1.6, badge: 1.4 };
/** A size in its role at these factors, held to `cap` px (else the role's own limit). */
export function sized(t: TextScale, role: TextRole, size: number, cap?: number): number {
  return grow(size, t[role], cap ?? size * CAPF[role]);
}
/** Candidate sizes alike. */
export function sizedAll(t: TextScale, role: TextRole, sizes: number[], cap?: number): number[] {
  return growAll(sizes, t[role], (z) => cap ?? z * CAPF[role]);
}
/** fitSize over candidates in their role's size (smaller, never bigger than that times the size at 100 %). */
export function fitSized(t: TextScale, role: TextRole, text: string, sizes: number[], maxW: number, weight: number, cap?: number): { text: string; size: number } {
  return fitSizeK(text, sizes, t[role], maxW, weight, (z) => cap ?? z * CAPF[role]);
}
/** The largest size whose capitals stay below `top`, on a baseline at y. */
const roomAbove = (y: number, top: number): number => (y - top) / 0.74;

export const KEY = 144;
const MONO = "Cascadia Mono, Consolas, JetBrains Mono, DejaVu Sans Mono, monospace";

export interface Look {
  accent: string;
  icon: string;
}

/** The accent and icon of a kind of item; the item's own dashboard icon name wins when we know it. */
export function lookFor(kind: string, iconName?: string, on?: boolean | null): Look {
  const by: Record<string, Look> = {
    light: { accent: P.warn, icon: on ? "bulbOn" : "bulb" },
    dimmer: { accent: P.warn, icon: on ? "bulbOn" : "bulb" },
    socket: { accent: P.ok, icon: "plug" },
    switch: { accent: P.ok, icon: "power" },
    thermostat: { accent: P.orange, icon: "thermostat" },
    cover: { accent: P.purple, icon: "blinds" },
    scene: { accent: P.purple, icon: "scene" },
    sequence: { accent: P.purple, icon: "sequence" },
    group: { accent: P.purple, icon: "layers" },
    rule: { accent: P.pink, icon: "rule" },
    schedule: { accent: P.pink, icon: "clock" },
    message: { accent: P.info, icon: "message" },
    system: { accent: P.crit, icon: "gear" },
    sensor: { accent: P.water, icon: "sensor" },
    reading: { accent: P.water, icon: "gauge" },
    status: { accent: P.ok, icon: "heart" },
    lock: { accent: P.purple, icon: on ? "unlock" : "lock" },   // (1.3) an ESP32 gateway's lock; on = unlocked
  };
  const l = by[kind] ?? { accent: P.info, icon: "sensor" };
  // keep the light's own on/off bulb; otherwise prefer the dashboard's icon for the item
  if (iconName && kind !== "light" && kind !== "dimmer" && kind !== "lock") return { accent: l.accent, icon: iconName };
  return l;
}

/** The accent a reading gets from what it measures. */
export function readingAccent(key: string, unit: string): { accent: string; icon: string } {
  const k = (key + " " + unit).toLowerCase();
  if (/temp|°c|°f|°/.test(k)) return { accent: P.orange, icon: "thermo" };
  if (/humid|%rh|moist|water|leak/.test(k)) return { accent: P.water, icon: "drop" };
  if (/power|watt|\bw\b|kwh|energy|current|volt|\ba\b|\bv\b/.test(k)) return { accent: P.warn, icon: "bolt" };
  if (/batt/.test(k)) return { accent: P.purple, icon: "battery" };
  if (/co2|voc|pm|air|ppm/.test(k)) return { accent: P.ok, icon: "leaf" };
  if (/lux|illum|light/.test(k)) return { accent: P.warn, icon: "sun" };
  if (/press|hpa/.test(k)) return { accent: P.info, icon: "gauge" };
  if (/wind/.test(k)) return { accent: P.info, icon: "wind" };
  return { accent: P.water, icon: "gauge" };
}

const BG_DEFS =
  `<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${P.panel2}"/><stop offset="1" stop-color="${P.bg}"/></linearGradient>`;

/** The frame every key is drawn in: the panel and its fine line; `glow` tints the top with the accent.
 * (1.3) `edge`: the fine line in that colour instead (an off key's Off colour), when there is no glow. */
export function keySvg(body: string, glow?: string, extraDefs = "", edge?: string): string {
  const defs = BG_DEFS
    + (glow ? `<linearGradient id="glow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${glow}" stop-opacity="0.26"/><stop offset="0.6" stop-color="${glow}" stop-opacity="0"/></linearGradient>` : "")
    + extraDefs;
  return svgDoc(KEY, KEY,
    `<rect width="144" height="144" fill="url(#bg)"/>`
    + (glow ? `<rect width="144" height="144" fill="url(#glow)"/>` : "")
    + `<rect x="3" y="3" width="138" height="138" rx="20" fill="none" stroke="${glow ?? edge ?? P.line}" stroke-opacity="${glow ? 0.55 : edge ? 0.45 : 1}" stroke-width="2"/>`
    + body, defs);
}

/** The icon tile at the top left: tinted with the accent when active. */
function tile(iconName: string, accent: string, active: boolean, x = 14, y = 14, size = 46, off?: string): string {
  // (1.3) off, in the user's Off colour: tinted like a lit tile, only fainter
  if (!active && off) {
    return rect(x, y, size, size, 14, off, `fill-opacity="0.1" stroke="${off}" stroke-opacity="0.45" stroke-width="1.5"`)
      + icon(iconName, x + (size - 28) / 2, y + (size - 28) / 2, 28, off, 1.9);
  }
  return rect(x, y, size, size, 14, active ? accent : P.panel, `fill-opacity="${active ? 0.18 : 1}" stroke="${active ? accent : P.line}" stroke-opacity="${active ? 0.5 : 1}" stroke-width="1.5"`)
    + icon(iconName, x + (size - 28) / 2, y + (size - 28) / 2, 28, active ? accent : P.dim, 1.9);
}

/** A small badge at the top right: battery, offline, lock, hold. */
function badges(o: { online?: boolean; battery?: number | null; hold?: boolean; allowed?: boolean; taken?: boolean }, showBattery = true): string {
  let x = 128;
  let out = "";
  const put = (name: string, colour: string) => {
    out += icon(name, x - 18, 15, 18, colour, 2);
    x -= 22;
  };
  if (o.allowed === false) put("lock", P.crit);
  if (o.online === false) put("wifiOff", P.crit);
  if (showBattery && o.battery !== undefined && o.battery !== null && o.battery <= 20) put("battery", o.battery <= 10 ? P.crit : P.warn);
  if (o.hold) put("hand", P.dim);
  if (o.taken) put("person", P.warn);
  return out;
}

function nameAndRoom(name: string, room: string | null, show: boolean, fitMode?: NameFit, showName = true, t: TextScale = ONE): string {
  const rs = sized(t, "room", 12.5), ns = sized(t, "name", 16);
  // (1.3) a bigger room lifts the name over it; a much bigger name keeps to one line
  const lift = (rs - 12.5) * 0.76;
  const one = ns > 16 * 1.25;
  const roomText = () => text(14, 132, fit(room!, rs, 118, 500), { size: rs, weight: 500, fill: P.dim, role: "room" });
  if (!showName) return room && show ? roomText() : "";
  if (fitMode && fitMode !== "cut") {
    const nl = nameLines(name, fitMode, ns, 118, 650, room && show || one ? 1 : 2);
    let o2 = "";
    const base = room && show ? 114 - lift : 128;
    nl.lines.forEach((l, i) => (o2 += text(14, base - (nl.lines.length - 1 - i) * nl.size * 1.12, l, { size: nl.size, weight: 650, fill: P.text, role: "name" })));
    if (room && show) o2 += roomText();
    return o2;
  }
  const lines = room && show || one ? [fit(name, ns, 118, 650)] : wrap2(name, ns, 118, 650);
  let out = "";
  if (room && show) {
    out += text(14, 114 - lift, lines[0]!, { size: ns, weight: 650, fill: P.text, role: "name" });
    out += roomText();
  } else if (lines.length === 2) {
    out += text(14, 113 - (ns - 16) * 1.12, lines[0]!, { size: ns, weight: 650, fill: P.text, role: "name" });
    out += text(14, 131, lines[1]!, { size: ns, weight: 650, fill: P.text, role: "name" });
  } else {
    out += text(14, 128, lines[0]!, { size: ns, weight: 650, fill: P.text, role: "name" });
  }
  return out;
}

// ------------------------------------------------------------------ Control

export interface ControlModel {
  name: string;
  room: string | null;
  showRoom: boolean;
  kind: string;
  icon: string;
  on: boolean | null;
  valueText: string;
  online: boolean;
  battery: number | null;
  hold: boolean;
  allowed: boolean;
  /** (1.2) Taken over by hand. */
  taken?: boolean;
}

export function controlBody(m: ControlModel, o: ClassicOpts = {}): { body: string; glow?: string; edge?: string } {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  const l0 = lookFor(m.kind, m.icon, m.on);
  const look = { ...l0, accent: o.accent ?? l0.accent };
  const active = m.on === true && m.online;
  const word = !m.online ? "Offline" : m.on === true ? "On" : m.on === false ? "Off" : m.valueText || "—";
  const value = i.detail && m.on !== null && m.valueText && m.online ? m.valueText : "";
  const off = !active && m.online ? o.offAccent : undefined;
  let body = (i.icon ? tile(look.icon, look.accent, active, 14, 14, 46, off) : "") + badges({ online: m.online, battery: m.battery, hold: m.hold, allowed: m.allowed, taken: m.taken }, i.battery);
  // the state: a pill with a dot, then the value if there is one
  if (i.state || value) {
    const both = !!value && i.state;
    const wrole: TextRole = i.state ? "value" : "detail";
    // (1.3) bigger words sit a little lower, into the room over the name
    // (where the name over the foot begins, at its size now: two lines unless the room is under it)
    const nz = sized(T, "name", 16), withRoom = !!(m.room && m.showRoom && i.room);
    const nameTop = !i.name ? 132 - sized(T, "room", 12.5) * 0.74 : withRoom ? 114 - (sized(T, "room", 12.5) - 12.5) * 0.76 - nz * 0.74 : nz > 20 ? 128 - nz * 0.74 : 113 - (nz - 16) * 1.12 - nz * 0.74;
    const shift = T[wrole] > 1 ? Math.max(0, Math.min(8, (T[wrole] - 1) * 16, nameTop - 4 - (both ? 84 : 90))) : 0;
    const wy = (both ? 84 : 90) + shift;
    const wordFit = fitSized(T, wrole, i.state ? word : value, [26, 22, 18], T[wrole] === 1 ? 116 : 104, 750, i.icon ? roomAbove(wy, 62) : undefined);
    const cy = (both ? 76 : 82) + (shift ? shift - (wordFit.size - 26) * 0.3 : 0);
    body += `<circle cx="20" cy="${n(cy)}" r="5" fill="${active ? look.accent : !m.online ? P.crit : off ?? P.muted}"/>`;
    body += text(32, wy, wordFit.text, { size: wordFit.size, weight: 750, fill: active ? P.text : P.dim, role: wrole });
    const ds = sized(T, "detail", 15, 19);
    const dx = 32 + Math.min(70, wordFit.text.length * wordFit.size * 0.62) + 6;
    if (both) body += text(dx, wy, fit(value, ds, T.detail === 1 && shift === 0 ? 60 : Math.max(24, Math.min(60, 140 - dx)), 600), { size: ds, weight: 600, fill: active ? look.accent : off ?? P.muted, role: "detail" });
  }
  body += nameAndRoom(m.name, m.room, m.showRoom && i.room, o.fit, i.name, T);
  return { body, glow: active ? look.accent : undefined, edge: off };
}

export function renderControl(m: ControlModel, o: ClassicOpts = {}): string {
  const b = controlBody(m, o);
  return keySvg(b.body, b.glow, "", b.edge);
}

// ------------------------------------------------------------------ Reading

export interface ReadingModel {
  label: string;
  value: string;
  unit: string;
  colour: string;
  accent: string;
  icon: string;
  trend: "up" | "down" | "flat" | null;
  history: number[];
  online: boolean;
  /** (1.3) A word under the value for what has no number: a scene's "2/3 as set", a rule's "enabled". */
  note?: string;
  /** (1.3) For a thing that is on or off: whether it is - the looks draw it lit. */
  lit?: boolean;
  /** (1.3) What the value measures, for an honest scale under its history (scale.ts). */
  scale?: Quantity;
  /** (1.3) Where the value stands in its true range (an attribute's min / max, a percentage); null without one. */
  level?: number | null;
}

/**
 * A sparkline of the last values, filled underneath - (1.3) on an honest scale (scale.ts): the
 * quantity's range, from 0, or a sensible span for its unit; 1.0 stretched it from min to max.
 */
export function sparkline(values: number[], x: number, y: number, w: number, h: number, colour: string, id: string, q?: Quantity | null): { defs: string; body: string } {
  const v = values.filter((a) => Number.isFinite(a)).slice(-40);
  if (v.length < 2) {
    return { defs: "", body: `<path d="M ${n(x)} ${n(y + h - 1)} H ${n(x + w)}" stroke="${P.line}" stroke-width="2" stroke-linecap="round" stroke-dasharray="2 5"/>` };
  }
  const { lo, hi } = seriesScale(v, q);
  const pts = v.map((a, i) => [x + (i / (v.length - 1)) * w, y + h - ((a - lo) / (hi - lo)) * (h - 4) - 2] as const);
  const line = pts.map((p, i) => (i ? "L " : "M ") + n(p[0]) + " " + n(p[1])).join(" ");
  const area = line + ` L ${n(x + w)} ${n(y + h)} L ${n(x)} ${n(y + h)} Z`;
  const last = pts[pts.length - 1]!;
  return {
    defs: `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${colour}" stop-opacity="0.38"/><stop offset="1" stop-color="${colour}" stop-opacity="0"/></linearGradient>`,
    body: `<path d="${area}" fill="url(#${id})"/>`
      + `<path d="${line}" fill="none" stroke="${colour}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>`
      + `<circle cx="${n(last[0])}" cy="${n(last[1])}" r="3.6" fill="${colour}" stroke="${P.bg}" stroke-width="1.5"/>`,
  };
}

export function renderReading(m: ReadingModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  if (!i.detail) m = { ...m, trend: null };
  let body = i.icon ? icon(m.icon, 14, 14, 20, m.accent, 2) : "";
  const ls = sized(T, "name", 13.5, 18), ly = 29 + (ls - 13.5) * 0.6;
  if (i.name) body += text(i.icon ? 40 : 14, ly, fit(m.label, ls, (m.trend && m.online ? 66 : 92) + (i.icon ? 0 : 26), 600), { size: ls, weight: 600, fill: P.dim, role: "name" });
  const v = m.online ? m.value || "—" : "Offline";
  const us = sized(T, "unit", 16), uk = us / 16;
  const vf = fitSized(T, "value", v, [44, 38, 32, 26, 20], m.unit ? 118 - 26 * uk : 118, 750, roomAbove(82, i.name ? ly + 6 : 14));
  const unit = m.unit && m.online ? `<tspan dx="4" font-size="${us}" font-weight="600" fill="${P.dim}" letter-spacing="0"${roleAttr("unit")}>${esc(fit(m.unit, us, 40 * uk, 600))}</tspan>` : "";
  if (i.state) body += text(14, 82, vf.text, { size: vf.size, weight: 750, fill: m.online ? m.colour : P.crit, spacing: -0.5, role: "value" }).replace(/<\/text>$/, unit + "</text>");
  if (m.trend && m.online) {
    const t = m.trend === "up" ? "trendUp" : m.trend === "down" ? "trendDown" : "trendFlat";
    body += icon(t, 110, 13, 20, m.trend === "flat" ? P.muted : m.colour, 2.2);
  }
  if (m.note && m.online && i.detail) {
    const ns = sized(T, "detail", 14);
    body += text(14, 116 + (ns - 14) * 0.5, fit(m.note, ns, 116, 600), { size: ns, weight: 600, fill: P.dim, role: "detail" });
    return keySvg(body);
  }
  if (!i.graph) return keySvg(body);
  if (i.scale) {
    const g = graph(seriesFace(m.history, null, m.scale), i, 14, 98, 116, 30, m.colour, CLASSIC_INK, "spark", T.detail);
    return keySvg(body + g.body, undefined, g.defs);
  }
  const sp = sparkline(m.history, 14, 98, 116, 30, m.colour, "spark", m.scale);
  body += sp.body;
  return keySvg(body, undefined, sp.defs);
}

const CLASSIC_INK = { bg: P.bg, bg2: P.panel2, line: P.line, text: P.text, dim: P.dim, muted: P.muted, crit: P.crit, warn: P.warn, badge: P.bg };
export function seriesFace(series: number[], target: number | null, scale?: Quantity | null): Face {
  return {
    kind: "reading", name: "", room: null, icon: "", accent: P.info, active: false, state: "", unit: "", stateColour: null, detail: "", mode: "",
    level: null, series, target, online: true, allowed: true, hold: false, battery: null, scale: scale ?? null,
  };
}

// ------------------------------------------------------------------ Thermostat

export interface ThermoModel {
  name: string;
  current: number | null;
  target: number | null;
  unit: string;
  mode: string;
  heating: boolean;
  min: number;
  max: number;
  online: boolean;
  hold: boolean;
  allowed: boolean;
  /** (1.1) The measured temperature over the graph's span, and the thermometer it comes from. */
  history?: number[];
  source?: string;
  /** (1.1) A heated room: its mode is what matters, so the name gives way to it. */
  modeFirst?: boolean;
}

export function fmtTemp(v: number | null): string {
  if (v === null) return "—";
  return (Math.round(v * 10) / 10).toFixed(1);
}

export function renderThermostat(m: ThermoModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  const graphed = !!o.info && i.graph && (m.history?.length ?? 0) >= 2;
  const heat = o.accent ?? P.orange;
  const cx = 72, cy = 70, r = 50;
  const span = Math.max(0.5, m.max - m.min);
  const f = (v: number | null) => (v === null ? 0 : Math.max(0, Math.min(1, (v - m.min) / span)));
  const a0 = -135, a1 = 135;
  const off = !m.heating && m.online ? o.offAccent : undefined;
  const accent = m.heating ? heat : off ?? P.info;
  let body = `<path d="${arcPath(cx, cy, r, a0, a1)}" fill="none" stroke="${P.line}" stroke-width="9" stroke-linecap="round"/>`;
  if (m.target !== null && m.online) {
    body += `<path d="${arcPath(cx, cy, r, a0, a0 + (a1 - a0) * f(m.target))}" fill="none" stroke="url(#arc)" stroke-width="9" stroke-linecap="round"/>`;
    const ang = ((a0 + (a1 - a0) * f(m.target) - 90) * Math.PI) / 180;
    body += `<circle cx="${n(cx + r * Math.cos(ang))}" cy="${n(cy + r * Math.sin(ang))}" r="7.5" fill="${P.text}" stroke="${accent}" stroke-width="3"/>`;
  }
  if (m.current !== null && m.online) {
    const ang = ((a0 + (a1 - a0) * f(m.current) - 90) * Math.PI) / 180;
    body += `<circle cx="${n(cx + (r - 15) * Math.cos(ang))}" cy="${n(cy + (r - 15) * Math.sin(ang))}" r="2.6" fill="${P.dim}"/>`;
  }
  if (i.icon) body += m.heating ? icon("flame", 62, 26, 20, heat, 2) : icon("thermo", 62, 26, 20, off ?? P.muted, 2);
  const big = m.online ? fmtTemp(m.current) : "Offline";
  const bf = fitSized(T, "value", big, [34, 28, 22], 86, 750, roomAbove(80, i.icon ? 48 : 22));
  if (i.state) body += text(cx, 80, bf.text, { size: bf.size, weight: 750, fill: m.online ? P.text : P.crit, anchor: "middle", spacing: -0.5, role: "value" });
  const ds = sized(T, "detail", 14, 19);
  if (m.online && i.detail) {
    const d = "→ " + fmtTemp(m.target) + (m.unit ? " " + m.unit : "");
    body += text(cx, 99 + (ds - 14) * 0.6, T.detail === 1 ? d : fit(d, ds, 124, 700), { size: ds, weight: 700, fill: accent, anchor: "middle", role: "detail" });
  }
  let gdefs = "";
  if (graphed) {
    const g = graph(seriesFace(m.history!, m.target, { unit: m.unit }), i, 34, 104, 76, 14, m.heating ? heat : off ?? P.water, CLASSIC_INK, "hist", T.detail);
    body += g.body;
    gdefs = g.defs;
  }
  // (1.3) the name and the mode, each in its own size
  const nz = sized(T, "name", 13), mz = sized(T, "mode", 13);
  const nm = i.name ? m.name : "", md = i.mode ? m.mode : "";
  let bottom: [string, TextRole][] = nm && md ? [[nm, "name"], [" · " + md, "mode"]] : nm ? [[nm, "name"]] : md ? [[md, "mode"]] : [];
  if (m.modeFirst && i.name && i.mode && m.mode) {
    const room = 124 - textWidth(" · " + m.mode, mz, 600);
    // too little left for the name: the mode alone ("By hand until 14:30")
    bottom = room < 48 ? [[m.mode, "mode"]] : [[fit(m.name, nz, room, 600), "name"], [" · " + m.mode, "mode"]];
  }
  if (bottom.length) body += mixLine(cx, 134, bottom, [13], 124, { weight: 600, fill: P.dim, anchor: "middle" }, T, (z) => z * CAPF.name).svg;
  body += badges({ hold: m.hold, allowed: m.allowed });
  const defs = `<linearGradient id="arc" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="${off ?? P.info}"/><stop offset="1" stop-color="${m.heating ? heat : off ?? P.water}"/></linearGradient>` + gdefs;
  return keySvg(body, m.heating && m.online ? heat : undefined, defs, off);
}

// ------------------------------------------------------------------ Dimmer / light

export interface DimmerModel {
  name: string;
  room: string | null;
  showRoom: boolean;
  on: boolean | null;
  level: number | null; // 0..1
  levelText: string;
  online: boolean;
  hold: boolean;
  allowed: boolean;
  /** (1.3) Taken over by hand: rules and schedules leave it alone. */
  taken?: boolean;
}

export function renderDimmer(m: DimmerModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  const A = o.accent ?? P.warn;
  const active = m.on === true && m.online;
  let body = "";
  if (active && i.icon) {
    // a soft halo around the bulb, stronger the brighter it is
    const op = 0.12 + 0.3 * (m.level ?? 1);
    body += `<circle cx="37" cy="37" r="30" fill="url(#halo)" fill-opacity="${n(op * 2.4)}"/>`;
  }
  const off = !active && m.online ? o.offAccent : undefined;
  if (i.icon) body += tile(active ? "bulbOn" : "bulb", A, active, 14, 14, 46, off);
  body += badges({ online: m.online, hold: m.hold, allowed: m.allowed, taken: m.taken });
  const big = !m.online ? "Offline" : m.on === false ? "Off" : m.levelText || (m.on ? "On" : "—");
  const bf = fitSized(T, "value", big, [32, 26, 20], 120, 750, roomAbove(88, i.icon ? 62 : 14));
  if (i.state) body += text(14, 88, bf.text, { size: bf.size, weight: 750, fill: active ? P.text : P.dim, role: "value" });
  // the level bar
  const w = 116;
  if (i.graph) {
    body += rect(14, 97, w, 7, 3.5, P.line);
    if (m.level !== null && m.online) body += rect(14, 97, Math.max(7, w * m.level), 7, 3.5, active ? "url(#lvl)" : off ?? P.muted);
  }
  const nmName = i.name ? m.name : "", nmRoom = m.room && m.showRoom && i.room ? m.room : "";
  const nm = [nmName, nmRoom].filter(Boolean).join(" · ");
  if (nm) {
    // (1.3) the name and the room in one size while theirs agree; else each its own, on one line
    const role: TextRole = nmName ? "name" : "room";
    const tagged = (svg: string) => (nmName && nmRoom && roleAttr(role) ? svg.replace(roleAttr(role), ' data-role="name room"') : svg);
    if (nmName && nmRoom && T.name !== T.room) {
      body += mixLine(14, 129, [[nmName, "name"], [" · " + nmRoom, "room"]], [14.5], 118, { weight: 650, fill: P.text }, T, (z) => z * CAPF.name).svg;
    } else if (o.fit && o.fit !== "cut") {
      const z = sized(T, role, 14.5);
      const nl = nameLines(nm, o.fit, z, 118, 650, z > 14.5 * 1.25 ? 1 : 2);
      nl.lines.forEach((l, k) => (body += tagged(text(14, 129 - (nl.lines.length - 1 - k) * nl.size * 1.1 + (nl.lines.length > 1 ? 6 : 0), l, { size: nl.size, weight: 650, fill: P.text, role }))));
    } else body += tagged(text(14, 129, fit(nm, sized(T, role, 14.5), 118, 650), { size: sized(T, role, 14.5), weight: 650, fill: P.text, role }));
  }
  const defs = `<radialGradient id="halo"><stop offset="0" stop-color="${A}" stop-opacity="0.55"/><stop offset="1" stop-color="${A}" stop-opacity="0"/></radialGradient>`
    + `<linearGradient id="lvl" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${o.accent ?? P.orange}"/><stop offset="1" stop-color="${o.accent ?? "#F2CC60"}"/></linearGradient>`;
  return keySvg(body, active ? A : undefined, defs, off);
}

// ------------------------------------------------------------------ Blinds

export interface BlindsModel {
  name: string;
  room: string | null;
  showRoom: boolean;
  position: number | null; // 0 closed .. 100 open
  moving: "up" | "down" | null;
  online: boolean;
  hold: boolean;
  allowed: boolean;
}

/** A window with its blind let down to the position; (1.3) with no position known (or offline), an empty frame - 1.0 drew it half down. */
export function blindsArt(x: number, y: number, w: number, h: number, position: number | null, accent: string): string {
  let s = rect(x, y, w, h, 6, P.bg, `stroke="${P.line}" stroke-width="2"`);
  if (position === null) return s + `<path d="M ${n(x - 3)} ${n(y + 1)} H ${n(x + w + 3)}" stroke="${P.dim}" stroke-width="3" stroke-linecap="round"/>`;
  const open = Math.max(0, Math.min(1, position / 100));
  // the sky behind
  s += rect(x + 4, y + 4, w - 8, h - 8, 3, "url(#sky)");
  const cover = (h - 8) * (1 - open);
  if (cover > 0.5) {
    s += rect(x + 4, y + 4, w - 8, cover, 2, accent, `fill-opacity="0.85"`);
    for (let ly = y + 4 + 6; ly < y + 4 + cover - 2; ly += 6) {
      s += `<path d="M ${n(x + 6)} ${n(ly)} H ${n(x + w - 6)}" stroke="${P.bg}" stroke-opacity="0.45" stroke-width="1.2"/>`;
    }
  }
  s += `<path d="M ${n(x - 3)} ${n(y + 1)} H ${n(x + w + 3)}" stroke="${P.dim}" stroke-width="3" stroke-linecap="round"/>`;
  return s;
}

export function renderBlinds(m: BlindsModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  const accent = o.accent ?? P.purple;
  const off = m.online && !m.moving && m.position !== null && m.position <= 0.5 ? o.offAccent : undefined;
  let body = `<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1F3A5F"/><stop offset="1" stop-color="#2D4F6E"/></linearGradient></defs>`;
  if (i.graph) body += blindsArt(84, 18, 44, 64, m.online ? m.position : null, off ?? accent);
  if (i.icon) body += icon(m.moving === "up" ? "up" : m.moving === "down" ? "down" : "blinds", 14, 16, 24, m.moving ? accent : off ?? P.dim, 2);
  const big = !m.online ? "Offline" : m.position === null ? "—" : m.position >= 99.5 ? "Open" : m.position <= 0.5 ? "Closed" : Math.round(m.position) + "%";
  const bf = fitSized(T, "value", big, [30, 24, 18], i.graph ? 70 : 116, 750, roomAbove(76, i.icon ? 42 : 14));
  if (i.state) body += text(14, 76, bf.text, { size: bf.size, weight: 750, fill: m.online ? P.text : P.crit, role: "value" });
  const ms = sized(T, "detail", 12.5, 17);
  if (m.moving && i.detail) {
    const w = m.moving === "up" ? "Opening…" : "Closing…";
    body += text(14, 96 + (ms - 12.5) * 0.5, T.detail === 1 ? w : fit(w, ms, i.graph ? 70 : 116, 600), { size: ms, weight: 600, fill: accent, role: "detail" });
  }
  body += nameAndRoom(m.name, m.room, m.showRoom && i.room, o.fit, i.name, T).replace(/y="113"/, 'y="115"');
  body += badges({ hold: m.hold, allowed: m.allowed });
  return keySvg(body, m.moving ? accent : undefined, "", off);
}

// ------------------------------------------------------------------ Scene

export interface SceneModel {
  name: string;
  room: string | null;
  kind: string;
  icon: string;
  flash: "ok" | "fail" | null;
  hold: boolean;
  allowed: boolean;
  /** (1.3) A scene's state: everything as it leaves it (true), not (false), nothing to tell (null). */
  on?: boolean | null;
}

export function renderScene(m: SceneModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  const look = lookFor(m.kind, m.icon);
  const accent = m.flash === "fail" ? P.crit : m.flash === "ok" ? P.ok : o.accent ?? look.accent;
  const lit = !m.flash && m.on === true;
  let body = `<circle cx="72" cy="56" r="34" fill="${accent}" fill-opacity="${m.flash ? 0.22 : lit ? 0.32 : 0.13}" stroke="${accent}" stroke-opacity="${lit ? 0.95 : 0.55}" stroke-width="${lit ? 3 : 2}"/>`;
  if (m.flash === "ok") body += icon("check", 52, 36, 40, P.ok, 2.4);
  else if (m.flash === "fail") body += icon("close", 52, 36, 40, P.crit, 2.4);
  else if (i.icon) body += icon(look.icon, 52, 36, 40, accent, 1.9);
  if (!m.flash && i.state) body += `<circle cx="98" cy="82" r="11" fill="${lit ? accent : P.bg}" stroke="${accent}" stroke-width="1.8"/>` + icon(lit ? "check" : "play", 92.2, 76.2, 11.6, lit ? P.bg : accent, 2);
  if (!i.name) {
    const rz = sized(T, "room", 13);
    if (m.room && i.room) body += text(72, 128, fit(m.room, rz, 124, 500), { size: rz, weight: 500, fill: P.dim, anchor: "middle", role: "room" });
    body += badges({ hold: m.hold, allowed: m.allowed });
    return keySvg(body, m.flash || lit ? accent : undefined);
  }
  const ns = sized(T, "name", 15.5), rs = sized(T, "room", 12, 15);
  const two = ns <= 15.5 * 1.25;
  const nl = o.fit && o.fit !== "cut" ? nameLines(m.name, o.fit, ns, 124, 650, two ? 2 : 1) : null;
  const lines = nl ? nl.lines : two ? wrap2(m.name, ns, 124, 650) : [fit(m.name, ns, 124, 650)];
  // (1.3) drawn at the size the lines were made for (at 100 % as before: the name's own size)
  const lz = T.name === 1 || !nl ? ns : nl.size;
  if (lines.length === 2) {
    body += text(72, 117 - (ns - 15.5) * 1.16, lines[0]!, { size: lz, weight: 650, fill: P.text, anchor: "middle", role: "name" });
    body += text(72, 135, lines[1]!, { size: lz, weight: 650, fill: P.text, anchor: "middle", role: "name" });
  } else {
    body += text(72, 121 - (m.room && i.room ? (rs - 12) * 0.76 : 0), lines[0]!, { size: lz, weight: 650, fill: P.text, anchor: "middle", role: "name" });
    if (m.room && i.room) body += text(72, 137, fit(m.room, rs, 124, 500), { size: rs, weight: 500, fill: P.dim, anchor: "middle", role: "room" });
  }
  body += badges({ hold: m.hold, allowed: m.allowed });
  return keySvg(body, m.flash || lit ? accent : undefined);
}

// ------------------------------------------------------------------ ZIGMon status

export interface StatusModel {
  label: string;
  value: string;
  detail: string;
  level: "ok" | "warn" | "crit" | "unknown";
  icon: string;
}

export function renderStatus(m: StatusModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const T = o.ts ?? ONE;
  const c = m.level === "ok" ? o.accent ?? P.ok : m.level === "warn" ? P.warn : m.level === "crit" ? P.crit : P.muted;
  let body = i.icon ? icon(m.icon, 14, 14, 26, c, 2) : "";
  body += `<circle cx="122" cy="24" r="6" fill="${c}"/>`;
  if (m.level === "crit") body += `<circle cx="122" cy="24" r="10.5" fill="none" stroke="${c}" stroke-opacity="0.45" stroke-width="2"/>`;
  const vf = fitSized(T, "value", m.value, [44, 36, 28, 22], 118, 750, roomAbove(90, i.icon ? 44 : 14));
  if (i.state) body += text(14, 90, vf.text, { size: vf.size, weight: 750, fill: m.level === "unknown" ? P.dim : P.text, spacing: -0.5, role: "value" });
  const ds = sized(T, "detail", 12.5, 16), ns = sized(T, "name", 14, 18);
  if (i.detail) body += text(14, 113 + (ds - 12.5) * 0.3 - (ns - 14) * 0.5, fit(m.detail, ds, 118, 500), { size: ds, weight: 500, fill: c, role: "detail" });
  if (i.name) body += text(14, 132, o.fit && o.fit !== "cut" ? nameLines(m.label, "fit", ns, 118, 650, 1).lines[0]! : fit(m.label, ns, 118, 650), { size: ns, weight: 650, fill: P.dim, role: "name" });
  return keySvg(body, m.level === "crit" || m.level === "warn" ? c : undefined);
}

// ------------------------------------------------------------------ notices: setup, offline, pairing...

export interface NoticeModel {
  icon: string;
  title: string;
  lines: string[];
  tone: "info" | "warn" | "crit" | "muted" | "ok";
}

export function renderNotice(m: NoticeModel): string {
  const c = m.tone === "info" ? P.info : m.tone === "warn" ? P.warn : m.tone === "crit" ? P.crit : m.tone === "ok" ? P.ok : P.dim;
  let body = `<circle cx="72" cy="44" r="24" fill="${c}" fill-opacity="0.13" stroke="${c}" stroke-opacity="0.45" stroke-width="1.6"/>`;
  body += icon(m.icon, 58, 30, 28, c, 2);
  body += text(72, 92, fit(m.title, 17, 126, 700), { size: 17, weight: 700, fill: P.text, anchor: "middle" });
  m.lines.slice(0, 2).forEach((l, i) => {
    body += text(72, 112 + i * 17, fit(l, 13, 128, 500), { size: 13, weight: 500, fill: P.dim, anchor: "middle" });
  });
  return keySvg(body);
}

/** Pairing: the code, big, on every ZIGMon key - the same code ZIGMon shows to approve. */
export function renderPair(code: string): string {
  const [a, b] = code.includes("-") ? code.split("-") : [code.slice(0, 3), code.slice(3)];
  let body = text(72, 30, "PAIR WITH ZIGMON", { size: 11.5, weight: 700, fill: P.info, anchor: "middle", spacing: 1.2 });
  body += rect(16, 40, 112, 88, 16, P.bg, `stroke="${P.info}" stroke-opacity="0.5" stroke-width="1.6"`);
  body += text(72, 79, a ?? "", { size: 34, weight: 800, fill: P.text, anchor: "middle", family: MONO, spacing: 3 });
  body += text(72, 116, b ?? "", { size: 34, weight: 800, fill: P.text, anchor: "middle", family: MONO, spacing: 3 });
  return keySvg(body, P.info);
}

// ------------------------------------------------------------------ hold to confirm

/** The press-and-hold ring over a key: the key dims, the ring fills from the top. */
export function renderHold(base: string, progress: number, accent: string): string {
  const p = Math.max(0, Math.min(1, progress));
  const inner = base.replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");
  let o = `<g>${inner}</g><rect width="144" height="144" fill="${P.bg}" fill-opacity="0.96"/>`;
  o += `<circle cx="72" cy="66" r="40" fill="none" stroke="${P.line}" stroke-width="9"/>`;
  if (p > 0) o += p >= 1
    ? `<circle cx="72" cy="66" r="40" fill="none" stroke="${accent}" stroke-width="9"/>`
    : `<path d="${arcPath(72, 66, 40, 0, 360 * p)}" fill="none" stroke="${accent}" stroke-width="9" stroke-linecap="round"/>`;
  o += p >= 1 ? icon("check", 56, 50, 32, accent, 2.6) : icon("hand", 58, 52, 28, P.text, 1.9);
  o += text(72, 130, p >= 1 ? "Confirmed" : "Keep holding…", { size: 14, weight: 700, fill: p >= 1 ? accent : P.text, anchor: "middle" });
  return svgDoc(KEY, KEY, o);
}

/** A short word over the key after a refused press ("Hold to confirm", "Not allowed"...). */
export function renderToast(base: string, title: string, line: string, tone: "warn" | "crit" | "ok"): string {
  const c = tone === "warn" ? P.warn : tone === "crit" ? P.crit : P.ok;
  const inner = base.replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");
  let o = `<g>${inner}</g><rect width="144" height="144" fill="${P.bg}" fill-opacity="0.95"/>`;
  o += `<rect x="3" y="3" width="138" height="138" rx="20" fill="none" stroke="${c}" stroke-width="2.5"/>`;
  o += icon(tone === "ok" ? "check" : tone === "warn" ? "hand" : "alert", 56, 22, 32, c, 2.2);
  const lines = wrap2(title, 16, 124, 700);
  lines.forEach((l, i) => (o += text(72, 82 + i * 19, l, { size: 16, weight: 700, fill: P.text, anchor: "middle" })));
  if (line) o += text(72, 82 + lines.length * 19 + 6, fit(line, 12, 128, 500), { size: 12, weight: 500, fill: P.dim, anchor: "middle" });
  return svgDoc(KEY, KEY, o);
}

export { esc };
