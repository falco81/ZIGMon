/**
 * The keys, drawn as 144x144 SVG in ZIGMon's dashboard style: a dark panel, one accent colour
 * per kind of thing, a stroke icon in a tinted tile, the state big, the name and room small.
 * Only plain SVG (rect, circle, path, text, linear gradients) - what Stream Deck's renderer draws.
 * Every piece of text passes through esc(); colours and icons come from our own tables only.
 */
import { P } from "./palette.js";
import { arcPath, esc, fit, fitSize, icon, n, nameLines, rect, svgDoc, text, textWidth, wrap2, type NameFit } from "./svg.js";
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
}
const SHOW_ALL: Info = { icon: true, name: true, room: true, state: true, detail: true, mode: true, graph: true, battery: true, scale: false, target: false };

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
  };
  const l = by[kind] ?? { accent: P.info, icon: "sensor" };
  // keep the light's own on/off bulb; otherwise prefer the dashboard's icon for the item
  if (iconName && kind !== "light" && kind !== "dimmer") return { accent: l.accent, icon: iconName };
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

/** The frame every key is drawn in: the panel and its fine line; `glow` tints the top with the accent. */
export function keySvg(body: string, glow?: string, extraDefs = ""): string {
  const defs = BG_DEFS
    + (glow ? `<linearGradient id="glow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${glow}" stop-opacity="0.26"/><stop offset="0.6" stop-color="${glow}" stop-opacity="0"/></linearGradient>` : "")
    + extraDefs;
  return svgDoc(KEY, KEY,
    `<rect width="144" height="144" fill="url(#bg)"/>`
    + (glow ? `<rect width="144" height="144" fill="url(#glow)"/>` : "")
    + `<rect x="3" y="3" width="138" height="138" rx="20" fill="none" stroke="${glow ?? P.line}" stroke-opacity="${glow ? 0.55 : 1}" stroke-width="2"/>`
    + body, defs);
}

/** The icon tile at the top left: tinted with the accent when active. */
function tile(iconName: string, accent: string, active: boolean, x = 14, y = 14, size = 46): string {
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

function nameAndRoom(name: string, room: string | null, show: boolean, fitMode?: NameFit, showName = true): string {
  if (!showName) return room && show ? text(14, 132, fit(room, 12.5, 118, 500), { size: 12.5, weight: 500, fill: P.dim }) : "";
  if (fitMode && fitMode !== "cut") {
    const nl = nameLines(name, fitMode, 16, 118, 650, room && show ? 1 : 2);
    let o2 = "";
    const base = room && show ? 114 : 128;
    nl.lines.forEach((l, i) => (o2 += text(14, base - (nl.lines.length - 1 - i) * nl.size * 1.12, l, { size: nl.size, weight: 650, fill: P.text })));
    if (room && show) o2 += text(14, 132, fit(room, 12.5, 118, 500), { size: 12.5, weight: 500, fill: P.dim });
    return o2;
  }
  const lines = room && show ? [fit(name, 16, 118, 650)] : wrap2(name, 16, 118, 650);
  let out = "";
  if (room && show) {
    out += text(14, 114, lines[0]!, { size: 16, weight: 650, fill: P.text });
    out += text(14, 132, fit(room, 12.5, 118, 500), { size: 12.5, weight: 500, fill: P.dim });
  } else if (lines.length === 2) {
    out += text(14, 113, lines[0]!, { size: 16, weight: 650, fill: P.text });
    out += text(14, 131, lines[1]!, { size: 16, weight: 650, fill: P.text });
  } else {
    out += text(14, 128, lines[0]!, { size: 16, weight: 650, fill: P.text });
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

export function controlBody(m: ControlModel, o: ClassicOpts = {}): { body: string; glow?: string } {
  const i = o.info ?? SHOW_ALL;
  const l0 = lookFor(m.kind, m.icon, m.on);
  const look = { ...l0, accent: o.accent ?? l0.accent };
  const active = m.on === true && m.online;
  const word = !m.online ? "Offline" : m.on === true ? "On" : m.on === false ? "Off" : m.valueText || "—";
  const value = i.detail && m.on !== null && m.valueText && m.online ? m.valueText : "";
  let body = (i.icon ? tile(look.icon, look.accent, active) : "") + badges({ online: m.online, battery: m.battery, hold: m.hold, allowed: m.allowed, taken: m.taken }, i.battery);
  // the state: a pill with a dot, then the value if there is one
  if (i.state || value) {
    const both = !!value && i.state;
    const wordFit = fitSize(i.state ? word : value, [26, 22, 18], 116, 750);
    body += `<circle cx="20" cy="${both ? 76 : 82}" r="5" fill="${active ? look.accent : !m.online ? P.crit : P.muted}"/>`;
    body += text(32, both ? 84 : 90, wordFit.text, { size: wordFit.size, weight: 750, fill: active ? P.text : P.dim });
    if (both) body += text(32 + Math.min(70, wordFit.text.length * wordFit.size * 0.62) + 6, 84, fit(value, 15, 60, 600), { size: 15, weight: 600, fill: active ? look.accent : P.muted });
  }
  body += nameAndRoom(m.name, m.room, m.showRoom && i.room, o.fit, i.name);
  return { body, glow: active ? look.accent : undefined };
}

export function renderControl(m: ControlModel, o: ClassicOpts = {}): string {
  const b = controlBody(m, o);
  return keySvg(b.body, b.glow);
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
}

/** A sparkline of the last values, filled underneath. */
export function sparkline(values: number[], x: number, y: number, w: number, h: number, colour: string, id: string): { defs: string; body: string } {
  const v = values.filter((a) => Number.isFinite(a)).slice(-40);
  if (v.length < 2) {
    return { defs: "", body: `<path d="M ${n(x)} ${n(y + h - 1)} H ${n(x + w)}" stroke="${P.line}" stroke-width="2" stroke-linecap="round" stroke-dasharray="2 5"/>` };
  }
  let lo = Math.min(...v), hi = Math.max(...v);
  if (hi - lo < 1e-9) {
    lo -= 1;
    hi += 1;
  }
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
  if (!i.detail) m = { ...m, trend: null };
  let body = i.icon ? icon(m.icon, 14, 14, 20, m.accent, 2) : "";
  if (i.name) body += text(i.icon ? 40 : 14, 29, fit(m.label, 13.5, (m.trend && m.online ? 66 : 92) + (i.icon ? 0 : 26), 600), { size: 13.5, weight: 600, fill: P.dim });
  const v = m.online ? m.value || "—" : "Offline";
  const vf = fitSize(v, [44, 38, 32, 26, 20], m.unit ? 92 : 118, 750);
  const unit = m.unit && m.online ? `<tspan dx="4" font-size="16" font-weight="600" fill="${P.dim}" letter-spacing="0">${esc(fit(m.unit, 16, 40, 600))}</tspan>` : "";
  if (i.state) body += text(14, 82, vf.text, { size: vf.size, weight: 750, fill: m.online ? m.colour : P.crit, spacing: -0.5 }).replace(/<\/text>$/, unit + "</text>");
  if (m.trend && m.online) {
    const t = m.trend === "up" ? "trendUp" : m.trend === "down" ? "trendDown" : "trendFlat";
    body += icon(t, 110, 13, 20, m.trend === "flat" ? P.muted : m.colour, 2.2);
  }
  if (!i.graph) return keySvg(body);
  if (i.scale) {
    const g = graph(seriesFace(m.history, null), i, 14, 98, 116, 30, m.colour, CLASSIC_INK, "spark");
    return keySvg(body + g.body, undefined, g.defs);
  }
  const sp = sparkline(m.history, 14, 98, 116, 30, m.colour, "spark");
  body += sp.body;
  return keySvg(body, undefined, sp.defs);
}

const CLASSIC_INK = { bg: P.bg, bg2: P.panel2, line: P.line, text: P.text, dim: P.dim, muted: P.muted, crit: P.crit, warn: P.warn, badge: P.bg };
function seriesFace(series: number[], target: number | null): Face {
  return {
    kind: "reading", name: "", room: null, icon: "", accent: P.info, active: false, state: "", unit: "", stateColour: null, detail: "", mode: "",
    level: null, series, target, online: true, allowed: true, hold: false, battery: null,
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
  const graphed = !!o.info && i.graph && (m.history?.length ?? 0) >= 2;
  const heat = o.accent ?? P.orange;
  const cx = 72, cy = 70, r = 50;
  const span = Math.max(0.5, m.max - m.min);
  const f = (v: number | null) => (v === null ? 0 : Math.max(0, Math.min(1, (v - m.min) / span)));
  const a0 = -135, a1 = 135;
  const accent = m.heating ? heat : P.info;
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
  if (i.icon) body += m.heating ? icon("flame", 62, 26, 20, heat, 2) : icon("thermo", 62, 26, 20, P.muted, 2);
  const big = m.online ? fmtTemp(m.current) : "Offline";
  const bf = fitSize(big, [34, 28, 22], 86, 750);
  if (i.state) body += text(cx, 80, bf.text, { size: bf.size, weight: 750, fill: m.online ? P.text : P.crit, anchor: "middle", spacing: -0.5 });
  if (m.online && i.detail) body += text(cx, 99, "→ " + fmtTemp(m.target) + (m.unit ? " " + m.unit : ""), { size: 14, weight: 700, fill: accent, anchor: "middle" });
  let gdefs = "";
  if (graphed) {
    const g = graph(seriesFace(m.history!, m.target), i, 34, 104, 76, 14, m.heating ? heat : P.water, CLASSIC_INK, "hist");
    body += g.body;
    gdefs = g.defs;
  }
  let bottom = [i.name ? m.name : "", i.mode ? m.mode : ""].filter(Boolean).join(" · ");
  if (m.modeFirst && i.name && i.mode && m.mode) {
    const room = 124 - textWidth(" · " + m.mode, 13, 600);
    // too little left for the name: the mode alone ("By hand until 14:30")
    bottom = room < 48 ? m.mode : fit(m.name, 13, room, 600) + " · " + m.mode;
  }
  if (bottom) body += text(cx, 134, fit(bottom, 13, 124, 600), { size: 13, weight: 600, fill: P.dim, anchor: "middle" });
  body += badges({ hold: m.hold, allowed: m.allowed });
  const defs = `<linearGradient id="arc" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="${P.info}"/><stop offset="1" stop-color="${m.heating ? heat : P.water}"/></linearGradient>` + gdefs;
  return keySvg(body, m.heating && m.online ? heat : undefined, defs);
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
}

export function renderDimmer(m: DimmerModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const A = o.accent ?? P.warn;
  const active = m.on === true && m.online;
  let body = "";
  if (active && i.icon) {
    // a soft halo around the bulb, stronger the brighter it is
    const op = 0.12 + 0.3 * (m.level ?? 1);
    body += `<circle cx="37" cy="37" r="30" fill="url(#halo)" fill-opacity="${n(op * 2.4)}"/>`;
  }
  if (i.icon) body += tile(active ? "bulbOn" : "bulb", A, active);
  body += badges({ online: m.online, hold: m.hold, allowed: m.allowed });
  const big = !m.online ? "Offline" : m.on === false ? "Off" : m.levelText || (m.on ? "On" : "—");
  const bf = fitSize(big, [32, 26, 20], 120, 750);
  if (i.state) body += text(14, 88, bf.text, { size: bf.size, weight: 750, fill: active ? P.text : P.dim });
  // the level bar
  const w = 116;
  if (i.graph) {
    body += rect(14, 97, w, 7, 3.5, P.line);
    if (m.level !== null && m.online) body += rect(14, 97, Math.max(7, w * m.level), 7, 3.5, active ? "url(#lvl)" : P.muted);
  }
  const nm = [i.name ? m.name : "", m.room && m.showRoom && i.room ? m.room : ""].filter(Boolean).join(" · ");
  if (nm) {
    if (o.fit && o.fit !== "cut") {
      const nl = nameLines(nm, o.fit, 14.5, 118, 650, 2);
      nl.lines.forEach((l, k) => (body += text(14, 129 - (nl.lines.length - 1 - k) * nl.size * 1.1 + (nl.lines.length > 1 ? 6 : 0), l, { size: nl.size, weight: 650, fill: P.text })));
    } else body += text(14, 129, fit(nm, 14.5, 118, 650), { size: 14.5, weight: 650, fill: P.text });
  }
  const defs = `<radialGradient id="halo"><stop offset="0" stop-color="${A}" stop-opacity="0.55"/><stop offset="1" stop-color="${A}" stop-opacity="0"/></radialGradient>`
    + `<linearGradient id="lvl" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${o.accent ?? P.orange}"/><stop offset="1" stop-color="${o.accent ?? "#F2CC60"}"/></linearGradient>`;
  return keySvg(body, active ? A : undefined, defs);
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

/** A window with its blind let down to the position. */
export function blindsArt(x: number, y: number, w: number, h: number, position: number | null, accent: string): string {
  const open = position === null ? 0.5 : Math.max(0, Math.min(1, position / 100));
  let s = rect(x, y, w, h, 6, P.bg, `stroke="${P.line}" stroke-width="2"`);
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
  const accent = o.accent ?? P.purple;
  let body = `<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1F3A5F"/><stop offset="1" stop-color="#2D4F6E"/></linearGradient></defs>`;
  if (i.graph) body += blindsArt(84, 18, 44, 64, m.online ? m.position : null, accent);
  if (i.icon) body += icon(m.moving === "up" ? "up" : m.moving === "down" ? "down" : "blinds", 14, 16, 24, m.moving ? accent : P.dim, 2);
  const big = !m.online ? "Offline" : m.position === null ? "—" : m.position >= 99.5 ? "Open" : m.position <= 0.5 ? "Closed" : Math.round(m.position) + "%";
  const bf = fitSize(big, [30, 24, 18], i.graph ? 70 : 116, 750);
  if (i.state) body += text(14, 76, bf.text, { size: bf.size, weight: 750, fill: m.online ? P.text : P.crit });
  if (m.moving && i.detail) body += text(14, 96, m.moving === "up" ? "Opening…" : "Closing…", { size: 12.5, weight: 600, fill: accent });
  body += nameAndRoom(m.name, m.room, m.showRoom && i.room, o.fit, i.name).replace(/y="113"/, 'y="115"');
  body += badges({ hold: m.hold, allowed: m.allowed });
  return keySvg(body, m.moving ? accent : undefined);
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
}

export function renderScene(m: SceneModel, o: ClassicOpts = {}): string {
  const i = o.info ?? SHOW_ALL;
  const look = lookFor(m.kind, m.icon);
  const accent = m.flash === "fail" ? P.crit : m.flash === "ok" ? P.ok : o.accent ?? look.accent;
  let body = `<circle cx="72" cy="56" r="34" fill="${accent}" fill-opacity="${m.flash ? 0.22 : 0.13}" stroke="${accent}" stroke-opacity="0.55" stroke-width="2"/>`;
  if (m.flash === "ok") body += icon("check", 52, 36, 40, P.ok, 2.4);
  else if (m.flash === "fail") body += icon("close", 52, 36, 40, P.crit, 2.4);
  else if (i.icon) body += icon(look.icon, 52, 36, 40, accent, 1.9);
  if (!m.flash && i.state) body += `<circle cx="98" cy="82" r="11" fill="${P.bg}" stroke="${accent}" stroke-width="1.8"/>` + icon("play", 92.2, 76.2, 11.6, accent, 2);
  if (!i.name) {
    if (m.room && i.room) body += text(72, 128, fit(m.room, 13, 124, 500), { size: 13, weight: 500, fill: P.dim, anchor: "middle" });
    body += badges({ hold: m.hold, allowed: m.allowed });
    return keySvg(body, m.flash ? accent : undefined);
  }
  const lines = o.fit && o.fit !== "cut" ? nameLines(m.name, o.fit, 15.5, 124, 650, 2).lines : wrap2(m.name, 15.5, 124, 650);
  if (lines.length === 2) {
    body += text(72, 117, lines[0]!, { size: 15.5, weight: 650, fill: P.text, anchor: "middle" });
    body += text(72, 135, lines[1]!, { size: 15.5, weight: 650, fill: P.text, anchor: "middle" });
  } else {
    body += text(72, 121, lines[0]!, { size: 15.5, weight: 650, fill: P.text, anchor: "middle" });
    if (m.room && i.room) body += text(72, 137, fit(m.room, 12, 124, 500), { size: 12, weight: 500, fill: P.dim, anchor: "middle" });
  }
  body += badges({ hold: m.hold, allowed: m.allowed });
  return keySvg(body, m.flash ? accent : undefined);
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
  const c = m.level === "ok" ? o.accent ?? P.ok : m.level === "warn" ? P.warn : m.level === "crit" ? P.crit : P.muted;
  let body = i.icon ? icon(m.icon, 14, 14, 26, c, 2) : "";
  body += `<circle cx="122" cy="24" r="6" fill="${c}"/>`;
  if (m.level === "crit") body += `<circle cx="122" cy="24" r="10.5" fill="none" stroke="${c}" stroke-opacity="0.45" stroke-width="2"/>`;
  const vf = fitSize(m.value, [44, 36, 28, 22], 118, 750);
  if (i.state) body += text(14, 90, vf.text, { size: vf.size, weight: 750, fill: m.level === "unknown" ? P.dim : P.text, spacing: -0.5 });
  if (i.detail) body += text(14, 113, fit(m.detail, 12.5, 118, 500), { size: 12.5, weight: 500, fill: c });
  if (i.name) body += text(14, 132, o.fit && o.fit !== "cut" ? nameLines(m.label, "fit", 14, 118, 650, 1).lines[0]! : fit(m.label, 14, 118, 650), { size: 14, weight: 650, fill: P.dim });
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
