/**
 * (1.1) The looks a key can be given. Classic is the 1.0 drawing (render.ts, unchanged); every
 * other look draws a Face - what any action has to say, in the same words - in its own style.
 * Every look honours the same choices of what is shown (Info), the accent colour, the label and
 * how long names are laid out, and keeps offline, locked and hold readable.
 * Colours come only from palette.ts; every piece of text goes through esc() (svg.ts text()).
 */
import { ACCENTS, P, X } from "./palette.js";
import { arcPath, fit, fitSize, icon, n, nameLines, rect, svgDoc, text, textWidth, type NameFit } from "./svg.js";

export const THEMES: readonly { id: string; name: string; hint: string }[] = [
  { id: "classic", name: "Classic", hint: "ZIGMon's dashboard tile" },
  { id: "minimal", name: "Minimal", hint: "a big icon, little else" },
  { id: "bigvalue", name: "Big value", hint: "the value, as big as it fits" },
  { id: "fill", name: "Solid fill", hint: "the whole key lights up" },
  { id: "neon", name: "Neon", hint: "a glowing outline" },
  { id: "ring", name: "Ring gauge", hint: "a ring that fills" },
  { id: "split", name: "Two-tone", hint: "a coloured band over a dark one" },
  { id: "glass", name: "Glass", hint: "a frosted pane with a glow" },
  { id: "label", name: "Bold label", hint: "the name, big" },
  { id: "dot", name: "Status dot", hint: "a lamp and clean type" },
  { id: "light", name: "Light", hint: "bright paper, dark ink" },
  { id: "contrast", name: "High contrast", hint: "black and white, thick lines" },
  // (1.2) the clear looks: one thing big, at most one small line
  { id: "huge", name: "Huge", hint: "the value fills the key" },
  { id: "pill", name: "Pill", hint: "the state in a big pill" },
  { id: "orb", name: "Orb", hint: "a sphere that glows when on" },
  { id: "tile", name: "Tile", hint: "an app tile and one word" },
  { id: "gauge", name: "Gauge", hint: "a thick arc, the number inside" },
  { id: "bars", name: "Bars", hint: "a big number over chunky bars" },
  { id: "wave", name: "Wave", hint: "fills up like water" },
  { id: "aurora", name: "Aurora", hint: "a glowing gradient, white type" },
  { id: "outline", name: "Outline", hint: "a thick border when on" },
  { id: "mono", name: "Mono", hint: "one colour, a giant icon" },
];

export interface Info {
  icon: boolean;
  name: boolean;
  room: boolean;
  /** The state or main value: On / Off, 21.5, 42 %, Open. */
  state: boolean;
  /** The second value: power, brightness, the target, the position, the trend. */
  detail: boolean;
  /** A thermostat's mode or preset (Comfort, By hand until 14:30...). */
  mode: boolean;
  /** The graph: history, level bar, gauge. */
  graph: boolean;
  battery: boolean;
  /** The graph's min / max, and a thermostat's target as a dashed line. */
  scale: boolean;
  target: boolean;
}

export const ALL_INFO: Info = { icon: true, name: true, room: true, state: true, detail: true, mode: true, graph: true, battery: true, scale: false, target: true };

export interface Face {
  kind: string;
  name: string;
  room: string | null;
  icon: string;
  accent: string;
  /** On, heating, open, done - drawn lit. */
  active: boolean;
  state: string;
  unit: string;
  /** A colour the state must have (a reading past its threshold, a status level). */
  stateColour: string | null;
  detail: string;
  mode: string;
  /** 0..1 - a brightness, a position, a target within its range. */
  level: number | null;
  /** History, oldest first, and the value to draw dashed across it. */
  series: number[];
  target: number | null;
  online: boolean;
  allowed: boolean;
  hold: boolean;
  battery: number | null;
  /** (1.2) Taken over by hand: rules and schedules leave it alone. */
  taken?: boolean;
}

export interface LookOpts {
  info: Info;
  fit: NameFit;
}

/** The ink of a look: its paper and the colours written on it. */
interface Ink {
  bg: string;
  bg2: string;
  line: string;
  text: string;
  dim: string;
  muted: string;
  crit: string;
  warn: string;
  badge: string;
}
const DARK: Ink = { bg: P.bg, bg2: P.panel2, line: P.line, text: P.text, dim: P.dim, muted: P.muted, crit: P.crit, warn: P.warn, badge: P.bg };
const PAPER: Ink = { bg: X.paper, bg2: X.white, line: X.paperLine, text: X.ink, dim: X.inkDim, muted: X.inkMuted, crit: X.inkCrit, warn: X.inkWarn, badge: X.white };
const HC: Ink = { bg: X.black, bg2: X.black, line: X.white, text: X.white, dim: X.white, muted: X.hcGrey, crit: X.hcRed, warn: X.hcYellow, badge: X.black };

export function accentColour(name: string | undefined, auto: string): string {
  return (name && ACCENTS[name]?.colour) || auto;
}

// ------------------------------------------------------------------ shared pieces

/** The badges at the top right: lock, offline, low battery, hold - each on a disc of the look's paper. */
function badges(f: Face, info: Info, ink: Ink, y = 13, backdrop = false): string {
  let x = 128;
  let out = "";
  const put = (name: string, c: string) => {
    if (backdrop) out += `<circle cx="${n(x - 9)}" cy="${n(y + 9)}" r="12.5" fill="${ink.badge}" fill-opacity="0.85"/>`;
    out += icon(name, x - 18, y, 18, c, 2.1);
    x -= backdrop ? 26 : 22;
  };
  if (!f.allowed) put("lock", ink.crit);
  if (!f.online) put("wifiOff", ink.crit);
  if (info.battery && f.battery !== null && f.battery <= 20) put("battery", f.battery <= 10 ? ink.crit : ink.warn);
  if (f.hold) put("hand", backdrop ? ink.text : ink.dim);
  if (f.taken) put("person", ink.warn);
  return out;
}

function stateText(f: Face): string {
  if (!f.online) return "Offline";
  return f.state || "—";
}

/** The name (and room) block, bottom-up from `bottom`. Returns the svg and the top it reached. */
function nameBlock(f: Face, o: LookOpts, x: number, bottom: number, maxW: number, ink: Ink, size = 15.5, anchor: "start" | "middle" = "start", lines = 2, nameColour?: string): { svg: string; top: number } {
  let svg = "";
  let y = bottom;
  if (o.info.room && f.room) {
    svg += text(x, y, fit(f.room, size * 0.8, maxW, 500), { size: size * 0.8, weight: 500, fill: ink.dim, anchor });
    y -= size * 1.12;
    lines = 1;
  }
  if (o.info.name && f.name) {
    const nl = nameLines(f.name, o.fit, size, maxW, 650, lines);
    for (let i = nl.lines.length - 1; i >= 0; i--) {
      svg += text(x, y, nl.lines[i]!, { size: nl.size, weight: 650, fill: nameColour ?? ink.text, anchor });
      y -= nl.size * 1.14;
    }
  }
  return { svg, top: y };
}

/** The graph: the history (with its target dashed and min / max when asked), else a level bar. */
export function graph(f: Face, info: Info, x: number, y: number, w: number, h: number, colour: string, ink: Ink, id: string): { defs: string; body: string } {
  const v = f.series.filter((a) => Number.isFinite(a)).slice(-96);
  if (v.length >= 2) {
    const tgt = info.target && f.target !== null && Number.isFinite(f.target) ? f.target : null;
    let lo = Math.min(...v), hi = Math.max(...v);
    if (tgt !== null) {
      lo = Math.min(lo, tgt);
      hi = Math.max(hi, tgt);
    }
    if (hi - lo < 1e-9) {
      lo -= 1;
      hi += 1;
    }
    const lw = info.scale ? 26 : 0;
    const gw = w - lw;
    const Y = (a: number) => y + h - ((a - lo) / (hi - lo)) * (h - 4) - 2;
    const pts = v.map((a, i) => [x + (i / (v.length - 1)) * gw, Y(a)] as const);
    const line = pts.map((p, i) => (i ? "L " : "M ") + n(p[0]) + " " + n(p[1])).join(" ");
    const area = line + ` L ${n(x + gw)} ${n(y + h)} L ${n(x)} ${n(y + h)} Z`;
    const last = pts[pts.length - 1]!;
    let body = `<path d="${area}" fill="url(#${id})"/>`
      + `<path d="${line}" fill="none" stroke="${colour}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`;
    if (tgt !== null) body += `<path d="M ${n(x)} ${n(Y(tgt))} H ${n(x + gw)}" stroke="${ink.dim}" stroke-width="1.4" stroke-dasharray="4 3"/>`;
    body += `<circle cx="${n(last[0])}" cy="${n(last[1])}" r="3.2" fill="${colour}" stroke="${ink.bg}" stroke-width="1.4"/>`;
    if (info.scale) {
      const fmt = (a: number) => (Math.abs(a) >= 100 ? String(Math.round(a)) : String(Math.round(a * 10) / 10));
      body += text(x + w, y + 8, fmt(hi), { size: 9.5, weight: 600, fill: ink.dim, anchor: "end" });
      body += text(x + w, y + h, fmt(lo), { size: 9.5, weight: 600, fill: ink.dim, anchor: "end" });
    }
    return {
      defs: `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${colour}" stop-opacity="0.34"/><stop offset="1" stop-color="${colour}" stop-opacity="0"/></linearGradient>`,
      body,
    };
  }
  if (f.level !== null && f.kind !== "reading") {
    const r = Math.min(4, h / 2);
    return { defs: "", body: rect(x, y + h / 2 - r, w, 2 * r, r, ink.line) + (f.online ? rect(x, y + h / 2 - r, Math.max(2 * r, w * Math.max(0, Math.min(1, f.level))), 2 * r, r, f.active ? colour : ink.muted) : "") };
  }
  if (f.kind === "reading" || f.kind === "thermostat") {
    return { defs: "", body: `<path d="M ${n(x)} ${n(y + h - 1)} H ${n(x + w)}" stroke="${ink.line}" stroke-width="2" stroke-linecap="round" stroke-dasharray="2 5"/>` };
  }
  return { defs: "", body: "" };
}

/** The value with its unit as a smaller tspan, sized to fit. */
function value(f: Face, x: number, y: number, maxW: number, sizes: number[], fill: string, ink: Ink, anchor: "start" | "middle" | "end" = "start", weight = 750): string {
  const v = stateText(f);
  const unit = f.unit && f.online ? f.unit : "";
  const vf = fitSize(v, sizes, unit ? maxW - Math.min(40, unit.length * 9) : maxW, weight);
  const u = unit ? `<tspan dx="3" font-size="${n(Math.max(11, vf.size * 0.42))}" font-weight="600" fill="${ink.dim}">${escText(fit(unit, 14, 40, 600))}</tspan>` : "";
  return text(x, y, vf.text, { size: vf.size, weight, fill: f.online ? fill : ink.crit, anchor, spacing: -0.4 }).replace(/<\/text>$/, u + "</text>");
}

function escText(s: string): string {
  return text(0, 0, s, { size: 1, fill: P.text }).replace(/^<text[^>]*>/, "").replace(/<\/text>$/, "");
}

/** The second line under the state: the detail, then the mode, as far as each is shown. */
function subline(f: Face, info: Info): string {
  if (!f.online) return "";
  return [info.detail ? f.detail : "", info.mode ? f.mode : ""].filter(Boolean).join(" · ");
}

function frame(ink: Ink, stroke: string, op = 1, w = 2, rx = 20): string {
  return `<rect x="3" y="3" width="138" height="138" rx="${rx}" fill="none" stroke="${stroke}" stroke-opacity="${n(op)}" stroke-width="${n(w)}"/>`;
}

function doc(body: string, defs = ""): string {
  return svgDoc(144, 144, body, defs);
}

const grad = (id: string, a: string, oa: number, b: string, ob: number, x2 = 0, y2 = 1) =>
  `<linearGradient id="${id}" x1="0" y1="0" x2="${x2}" y2="${y2}"><stop offset="0" stop-color="${a}" stop-opacity="${n(oa)}"/><stop offset="1" stop-color="${b}" stop-opacity="${n(ob)}"/></linearGradient>`;

// ------------------------------------------------------------------ the looks

/** Minimal: a big icon on black, a soft disc behind it when lit; a line of state, the name small. */
function minimal(f: Face, o: LookOpts): string {
  const ink = DARK, i = o.info;
  const c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  let body = rect(0, 0, 144, 144, 0, X.night);
  let defs = "";
  let bottom = 138;
  if (i.name && f.name) {
    const nl = nameLines(f.name, o.fit, 13, 128, 600, 1);
    body += text(72, 136, nl.lines[0]!, { size: nl.size, weight: 600, fill: ink.dim, anchor: "middle" });
    bottom = 120;
  }
  if (i.graph && f.series.length >= 2) {
    const g = graph(f, i, 24, bottom - 18, 96, 18, f.stateColour ?? c, ink, "mg");
    body += g.body;
    defs += g.defs;
    bottom -= 24;
  } else if (i.graph && f.level !== null && f.kind !== "reading") {
    body += graph(f, i, 40, bottom - 4, 64, 4, c, ink, "mg").body;
    bottom -= 10;
  }
  if (i.state || (i.detail && f.detail) || (i.mode && f.mode)) {
    const w = i.state ? stateText(f) + (f.unit && f.online ? " " + f.unit : "") : subline(f, i);
    const big = !i.icon;
    if (!big && i.state && subline(f, i)) {
      // the detail and the mode small under the state, the icon a little smaller for them
      body += text(72, bottom - 1, fit(subline(f, i), 11, 128, 600), { size: 11, weight: 600, fill: ink.dim, anchor: "middle" });
      bottom -= 14;
    }
    const fs = fitSize(w, big ? [40, 32, 26, 20] : [17, 15, 13], 124, 700);
    body += text(72, bottom - 3, fs.text, { size: fs.size, weight: 700, fill: !f.online ? ink.crit : f.stateColour ?? (lit ? c : ink.dim), anchor: "middle" });
    bottom -= fs.size + 6;
    if (big && i.state && subline(f, i)) {
      body += text(72, bottom - 2, fit(subline(f, i), 12.5, 124, 500), { size: 12.5, weight: 500, fill: ink.dim, anchor: "middle" });
      bottom -= 18;
    }
  }
  if (i.icon) {
    const sz = Math.max(26, Math.min(78, bottom - 22));
    const cy = (8 + bottom) / 2;
    if (lit) body += `<circle cx="72" cy="${n(cy)}" r="${n(sz * 0.74)}" fill="${c}" fill-opacity="0.16"/>`;
    body += icon(f.icon, 72 - sz / 2, cy - sz / 2, sz, lit ? c : !f.online ? ink.crit : ink.muted, 1.8);
  }
  body += badges(f, i, ink);
  return doc(body, defs);
}

/** Big value: the state as large as it fits, the name small on top, the detail and the graph under it. */
function bigvalue(f: Face, o: LookOpts): string {
  const ink = DARK, i = o.info, c = f.accent;
  let b = rect(0, 0, 144, 144, 0, "url(#bg)") + frame(ink, f.active ? c : ink.line, f.active ? 0.7 : 1);
  let x0 = 14;
  if (i.icon) {
    b += icon(f.icon, 13, 13, 20, f.active ? c : ink.dim, 2);
    x0 = 39;
  }
  if (i.name && f.name) {
    const nl = nameLines(f.name, o.fit, 13, 128 - x0 - (f.hold || !f.online || !f.allowed ? 26 : 0), 650, 1);
    b += text(x0, 29, nl.lines[0]!, { size: nl.size, weight: 650, fill: ink.dim });
  }
  const hasGraph = i.graph && (f.series.length >= 2 || f.level !== null || f.kind === "reading");
  const sub = subline(f, i);
  const vy = hasGraph ? (sub ? 76 : 84) : sub ? 88 : 96;
  if (i.state) b += value(f, 72, vy, 124, [54, 46, 38, 30, 24, 19], f.stateColour ?? (f.active ? c : ink.text), ink, "middle", 800);
  if (sub) b += text(72, vy + 20, fit(sub, 13.5, 126, 600), { size: 13.5, weight: 600, fill: f.active ? c : ink.dim, anchor: "middle" });
  let defs = grad("bg", P.panel2, 1, P.bg, 1);
  if (hasGraph) {
    const g = graph(f, i, 14, 110, 116, 22, f.stateColour ?? c, ink, "g");
    b += g.body;
    defs += g.defs;
  } else if (i.room && f.room) b += text(72, 132, fit(f.room, 12, 124, 500), { size: 12, weight: 500, fill: ink.muted, anchor: "middle" });
  b += badges(f, i, ink);
  return doc(b, defs);
}

/** Solid fill: lit, the whole key is the accent and the words are dark on it; unlit, a dark panel. */
function solid(f: Face, o: LookOpts): string {
  const i = o.info, c = f.accent;
  const lit = f.active && f.online;
  const ink: Ink = lit ? { ...DARK, text: P.bg, dim: P.panel2, muted: P.panel2, line: P.bg, badge: P.bg } : DARK;
  let defs = lit ? grad("fill", c, 1, c, 0.72, 1, 1) : grad("fill", P.panel2, 1, P.bg, 1);
  let b = `<rect width="144" height="144" rx="0" fill="url(#fill)"/>`;
  b += lit ? `<rect x="3" y="3" width="138" height="138" rx="20" fill="none" stroke="${X.white}" stroke-opacity="0.35" stroke-width="2"/>` : frame(DARK, P.line);
  if (i.icon) {
    b += `<circle cx="36" cy="36" r="23" fill="${lit ? P.bg : P.panel}" fill-opacity="${lit ? 0.16 : 1}" stroke="${lit ? P.bg : P.line}" stroke-opacity="${lit ? 0.25 : 1}" stroke-width="1.5"/>`;
    b += icon(f.icon, 22, 22, 28, lit ? P.bg : f.online ? P.dim : P.crit, 2);
  }
  const sub = subline(f, i);
  let y = 86;
  if (i.state) {
    b += value(f, 14, sub ? 82 : 88, 120, [30, 26, 22, 18], lit ? P.bg : f.stateColour ?? P.dim, ink, "start", 800);
    y = sub ? 82 : 88;
  }
  if (sub) b += text(14, y + 17, fit(sub, 13, 120, 650), { size: 13, weight: 650, fill: lit ? P.panel2 : f.active ? c : P.muted });
  const nb = nameBlock(f, o, 14, 133, 118, ink, 14.5, "start", i.state || sub ? 1 : 2);
  b += nb.svg;
  if (i.graph && f.level !== null && f.series.length < 2) {
    const g = graph(f, i, 76, 34, 54, 6, lit ? P.bg : c, ink, "g");
    b += g.body;
  } else if (i.graph && f.series.length >= 2) {
    const g = graph(f, i, 68, 24, 62, 26, lit ? P.bg : c, ink, "g");
    b += g.body;
    defs += g.defs;
  }
  b += badges(f, i, ink, 13, true);
  return doc(b, defs);
}

/** Neon: a glowing outline in the accent on near-black; unlit, a faint one. */
function neon(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) {
    b += `<rect x="7" y="7" width="130" height="130" rx="22" fill="none" stroke="${c}" stroke-opacity="0.10" stroke-width="12"/>`;
    b += `<rect x="7" y="7" width="130" height="130" rx="22" fill="none" stroke="${c}" stroke-opacity="0.22" stroke-width="6"/>`;
    b += `<rect x="7" y="7" width="130" height="130" rx="22" fill="none" stroke="${c}" stroke-width="2.4"/>`;
  } else b += `<rect x="7" y="7" width="130" height="130" rx="22" fill="none" stroke="${f.online ? P.muted : P.crit}" stroke-opacity="${f.online ? 0.55 : 0.8}" stroke-width="1.6" stroke-dasharray="${f.online ? "0" : "6 5"}"/>`;
  const texts = (i.state ? 1 : 0) + (i.name ? 1 : 0);
  const sz = texts ? 34 : 56;
  const cy = texts ? 42 : 72;
  if (i.icon) {
    if (lit) b += icon(f.icon, 72 - sz / 2, cy - sz / 2, sz, c, 5.5).replace('stroke-width="5.5"', 'stroke-width="5.5" stroke-opacity="0.18"');
    b += icon(f.icon, 72 - sz / 2, cy - sz / 2, sz, lit ? c : P.muted, 1.9);
  }
  let y = i.icon ? 84 : 66;
  if (i.state) {
    if (lit) b += value(f, 72, y, 116, [26, 22, 18, 15], c, ink, "middle").replace(/fill="([^"]+)"/, 'fill="$1" fill-opacity="0.25" stroke="' + c + '" stroke-opacity="0.25" stroke-width="3"');
    b += value(f, 72, y, 116, [26, 22, 18, 15], f.stateColour ?? (lit ? c : P.dim), ink, "middle");
    y += 18;
  }
  const sub = subline(f, i);
  if (sub) {
    b += text(72, y, fit(sub, 12, 116, 600), { size: 12, weight: 600, fill: lit ? P.text : P.muted, anchor: "middle" });
    y += 14;
  }
  const nb = nameBlock(f, sub ? { ...o, info: { ...i, room: false } } : o, 72, 128, 112, ink, 13.5, "middle", 1, lit ? P.text : P.dim);
  if (nb.top > y - 8 || !i.state) b += nb.svg;
  let defs = "";
  if (i.graph && f.series.length >= 2 && !i.state) {
    const g = graph(f, i, 24, 92, 96, 18, c, ink, "g");
    b += g.body;
    defs = g.defs;
  } else if (i.graph && f.level !== null) b += graph(f, i, 30, 134, 84, 3, c, ink, "g").body;
  b += badges(f, i, ink, 15);
  return doc(b, defs);
}

/** Ring gauge: a ring that fills with the level (whole when on), the icon and value inside it. */
function ring(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const named = (i.name && f.name) || (i.room && f.room);
  const cx = 72, cy = named ? 60 : 72, r = named ? 40 : 52;
  let b = rect(0, 0, 144, 144, 0, "url(#bg)") + frame(ink, P.line);
  b += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${P.line}" stroke-width="8"/>`;
  const lv = i.graph && f.level !== null ? Math.max(0, Math.min(1, f.level)) : lit ? 1 : 0;
  if (f.online && lv > 0) b += lv >= 1 ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${c}" stroke-width="8"/>`
    : `<path d="${arcPath(cx, cy, r, 0, 360 * lv)}" fill="none" stroke="${c}" stroke-width="8" stroke-linecap="round"/>`;
  if (lit) b += `<circle cx="${cx}" cy="${cy}" r="${r - 9}" fill="${c}" fill-opacity="0.1"/>`;
  const st = i.state;
  if (i.icon) {
    const s = st ? 22 : 38;
    b += icon(f.icon, cx - s / 2, st ? cy - 30 : cy - s / 2, s, lit ? c : P.dim, 2);
  }
  if (st) {
    b += value(f, cx, i.icon ? cy + 10 : cy + 7, r * 1.55, named ? [24, 20, 16, 13] : [30, 26, 20, 16], f.stateColour ?? (lit ? P.text : P.dim), ink, "middle");
    const sub = i.detail && f.online ? f.detail : "";
    if (sub) b += text(cx, cy + (i.icon ? 25 : 24), fit(sub, 10.5, r * 1.45, 600), { size: 10.5, weight: 600, fill: lit ? c : P.muted, anchor: "middle" });
  }
  const modeLine = i.mode && f.online ? f.mode : "";
  if (modeLine && named) b += text(72, cy + r + 15, fit(modeLine, 11, 124, 700), { size: 11, weight: 700, fill: lit ? c : P.dim, anchor: "middle" });
  else if (modeLine) b += text(cx, cy + r - 8, fit(modeLine, 10, r * 1.2, 700), { size: 10, weight: 700, fill: lit ? c : P.dim, anchor: "middle" });
  if (named) b += nameBlock(f, modeLine ? { ...o, info: { ...i, room: false } } : o, 72, 136, 124, ink, modeLine ? 12 : 13.5, "middle", 1).svg;
  b += badges(f, i, ink, 10);
  return doc(b, grad("bg", P.panel2, 1, P.bg, 1));
}

/** Two-tone: the top a band in the accent (lit) with the icon and the state, the bottom dark with the name. */
function split(f: Face, o: LookOpts): string {
  const i = o.info, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const band = i.name || i.room ? 66 : 144;
  let b = rect(0, 0, 144, 144, 0, P.bg);
  b += band >= 144 ? rect(0, 0, 144, 144, 0, lit ? "url(#band)" : P.panel2)
    : `<path d="M 0 0 H 144 V ${band} H 0 Z" fill="${lit ? "url(#band)" : P.panel2}"/>` + `<path d="M 0 ${band} H 144" stroke="${lit ? c : P.line}" stroke-width="2"/>`;
  const on = lit ? P.bg : P.dim;
  if (i.icon) b += icon(f.icon, 13, band >= 144 ? 14 : 14, band >= 144 ? 34 : 30, lit ? P.bg : f.online ? P.dim : P.crit, 2);
  if (i.state) {
    const ink: Ink = lit ? { ...DARK, dim: P.panel2, crit: P.bg } : DARK;
    b += value(f, 131, band >= 144 ? 96 : 56, i.icon ? 80 : 118, band >= 144 ? [40, 32, 26, 20] : [24, 20, 16, 13], f.stateColour && !lit ? f.stateColour : on, ink, "end", 800);
  }
  const sub = subline(f, i);
  let defs = grad("band", c, 1, c, 0.78, 1, 1);
  const ink = DARK;
  if (band < 144) {
    const nb = nameBlock(f, o, 14, sub || i.graph ? 118 : 132, 118, ink, 15, "start", sub || i.graph ? 1 : 2);
    b += nb.svg;
    if (sub) b += text(14, 135, fit(sub, 12.5, 118, 600), { size: 12.5, weight: 600, fill: lit ? c : P.muted });
    else if (i.graph) {
      const g = graph(f, i, 14, 124, 116, 12, c, ink, "g");
      b += g.body;
      defs += g.defs;
    }
  } else if (sub) b += text(131, 118, fit(sub, 13, 118, 600), { size: 13, weight: 600, fill: lit ? P.panel2 : P.muted, anchor: "end" });
  b += frame(ink, lit ? c : P.line, lit ? 0.5 : 1);
  b += badges(f, i, lit && band >= 144 ? { ...DARK, badge: P.bg } : DARK, band >= 144 ? 13 : 13, lit);
  return doc(b, defs);
}

/** Glass: a frosted pane over a glow of the accent, a bright edge and a sheen across the top. */
function glass(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  let defs = `<radialGradient id="orb" cx="0.3" cy="0.3" r="0.8"><stop offset="0" stop-color="${c}" stop-opacity="${lit ? 0.75 : 0.18}"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></radialGradient>`
    + grad("sheen", X.white, 0.16, X.white, 0) + grad("bg", P.panel2, 1, X.night, 1, 1, 1);
  let b = rect(0, 0, 144, 144, 0, "url(#bg)");
  b += `<circle cx="40" cy="40" r="70" fill="url(#orb)"/>`;
  b += rect(8, 8, 128, 128, 22, X.white, `fill-opacity="${lit ? 0.07 : 0.04}" stroke="${X.white}" stroke-opacity="${lit ? 0.3 : 0.14}" stroke-width="1.4"`);
  b += `<path d="M 30 8 H 114 A 22 22 0 0 1 136 30 V 52 C 96 40 52 44 8 60 V 30 A 22 22 0 0 1 30 8 Z" fill="url(#sheen)"/>`;
  if (i.icon) b += icon(f.icon, 20, 20, 30, lit ? X.white : f.online ? P.dim : P.crit, 2);
  const sub = subline(f, i);
  if (i.state) b += value(f, 128, 58, i.icon ? 70 : 110, [26, 22, 18, 14], f.stateColour ?? (lit ? X.white : P.dim), ink, "end", 750);
  if (sub) b += text(128, 74, fit(sub, 12, 108, 600), { size: 12, weight: 600, fill: lit ? c : P.muted, anchor: "end" });
  if (i.graph && (f.series.length >= 2 || f.level !== null)) {
    const g = graph(f, i, 20, 80, 104, 14, lit ? c : P.muted, ink, "g");
    b += g.body;
    defs += g.defs;
  }
  b += nameBlock(f, o, 20, 126, 106, ink, 14.5, "start", 2, lit ? X.white : P.text).svg;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

/** Bold label: the name, big, set like a sign; the state as a bar under it that fills with the level. */
function label(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  let b = rect(0, 0, 144, 144, 0, P.bg) + frame(ink, lit ? c : P.line, lit ? 0.6 : 1);
  if (i.icon) b += icon(f.icon, 14, 14, 20, lit ? c : P.dim, 2.1);
  const words = i.name && f.name ? f.name : i.room && f.room ? f.room : i.state ? stateText(f) : "";
  const nl = nameLines(words, o.fit === "cut" ? "cut" : "fit", 25, 124, 800, 3);
  const lines = nl.lines.length > 2 ? nl.lines.slice(0, 2) : nl.lines;
  let y = 74 - (lines.length - 1) * nl.size * 0.55;
  for (const l of lines) {
    b += text(72, y, l, { size: nl.size, weight: 800, fill: lit ? P.text : P.dim, anchor: "middle", spacing: -0.3 });
    y += nl.size * 1.08;
  }
  const lv = i.graph && f.level !== null ? Math.max(0, Math.min(1, f.level)) : lit ? 1 : 0;
  b += rect(36, 102, 72, 5, 2.5, P.line);
  if (lv > 0 && f.online) b += rect(36, 102, Math.max(5, 72 * lv), 5, 2.5, c);
  const sub = subline(f, i);
  if (i.state) {
    const st = stateText(f) + (f.unit && f.online ? " " + f.unit : "");
    b += text(72, sub ? 122 : 127, fit(st, 13, 124, 700), { size: 13, weight: 700, fill: !f.online ? P.crit : f.stateColour ?? (lit ? c : P.muted), anchor: "middle" });
    if (sub) b += text(72, 137, fit(sub, 11, 124, 600), { size: 11, weight: 600, fill: P.muted, anchor: "middle" });
  } else if (sub) b += text(72, 127, fit(sub, 12.5, 124, 600), { size: 12.5, weight: 600, fill: P.muted, anchor: "middle" });
  b += badges(f, i, ink);
  return doc(b);
}

/** Status dot: a lamp at the top left - lit, hollow or red - with the state beside it in clean type. */
function dot(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.accent;
  const lit = f.active && f.online;
  const lamp = !f.online ? P.crit : f.stateColour ?? (lit ? c : P.muted);
  let b = rect(0, 0, 144, 144, 0, P.panel) + frame(ink, P.line, 1, 1.5, 18);
  if (lit || !f.online) b += `<circle cx="25" cy="27" r="14" fill="${lamp}" fill-opacity="0.18"/>`;
  b += lit || !f.online || f.stateColour ? `<circle cx="25" cy="27" r="8" fill="${lamp}"/>` : `<circle cx="25" cy="27" r="7" fill="none" stroke="${lamp}" stroke-width="2.4"/>`;
  const nb = (!f.allowed ? 1 : 0) + (!f.online ? 1 : 0) + (f.hold ? 1 : 0) + (i.battery && f.battery !== null && f.battery <= 20 ? 1 : 0);
  if (i.state) b += value(f, 42, 35, 86 - nb * 22, [22, 19, 16, 13], lit || !f.online ? P.text : f.stateColour ?? P.dim, ink, "start", 700);
  const det = i.detail && f.online ? f.detail : "", md = i.mode && f.online ? f.mode : "";
  if (det) b += text(42, 53, fit(det, 12.5, i.icon ? 56 : 88, 600), { size: 12.5, weight: 600, fill: lit ? c : P.muted });
  if (md) b += text(42, det ? 68 : 53, fit(md, 11.5, i.icon ? 56 : 88, 700), { size: 11.5, weight: 700, fill: P.dim });
  if (i.icon) b += icon(f.icon, 100, 44, 30, lit ? c : P.muted, 1.9);
  let defs = "";
  if (i.graph && (f.series.length >= 2 || f.level !== null)) {
    const g = graph(f, i, 14, md && det ? 74 : 70, 76, md && det ? 12 : 14, lamp, ink, "g");
    b += g.body;
    defs = g.defs;
  }
  b += nameBlock(f, o, 14, 131, 118, ink, 15, "start", 2).svg;
  b += badges(f, i, ink, 12);
  return doc(b, defs);
}

/** Light: the Classic layout on bright paper with dark ink - for decks beside a bright screen. */
function light(f: Face, o: LookOpts): string {
  const i = o.info, ink = PAPER, c = f.online ? f.accent : X.inkCrit;
  const lit = f.active && f.online;
  let defs = grad("bg", X.white, 1, X.paper2, 1) + (lit ? grad("glow", c, 0.3, c, 0) : "");
  let b = rect(0, 0, 144, 144, 0, "url(#bg)") + (lit ? `<rect width="144" height="72" fill="url(#glow)"/>` : "");
  b += frame(ink, lit ? c : X.paperLine, 1, 2);
  if (i.icon) {
    b += rect(14, 14, 44, 44, 13, lit ? c : X.white, `fill-opacity="${lit ? 0.2 : 1}" stroke="${lit ? c : X.paperLine}" stroke-width="1.5"`);
    b += icon(f.icon, 22, 22, 28, lit ? X.ink : f.online ? X.inkDim : X.inkCrit, 2);
  }
  const sub = subline(f, i);
  if (i.state) b += value(f, 14, sub ? 82 : 88, 118, [28, 24, 20, 16], f.stateColour ? f.stateColour : lit ? X.ink : X.inkDim, ink, "start", 800);
  if (sub) b += text(14, 99, fit(sub, 13, 118, 650), { size: 13, weight: 650, fill: lit ? X.ink : X.inkMuted });
  if (i.graph && (f.series.length >= 2 || (f.level !== null && f.kind !== "control"))) {
    const g = graph(f, i, 66, 22, 64, 26, c, ink, "g");
    b += g.body;
    defs += g.defs;
  }
  b += nameBlock(f, o, 14, 133, 118, ink, 14.5, "start", i.state || sub ? 1 : 2).svg;
  b += badges(f, i, ink, 13, true);
  return doc(b, defs);
}

/** High contrast: black and white with thick lines; lit, the key turns white with black words. */
function contrast(f: Face, o: LookOpts): string {
  const i = o.info;
  const lit = f.active && f.online;
  const ink: Ink = lit ? { ...HC, bg: X.white, text: X.black, dim: X.black, muted: X.black, line: X.black, badge: X.white, crit: P.bg } : HC;
  let b = rect(0, 0, 144, 144, 0, lit ? X.white : X.black);
  b += `<rect x="4" y="4" width="136" height="136" rx="16" fill="none" stroke="${!f.online ? X.hcRed : lit ? X.black : X.white}" stroke-width="5"${f.online ? "" : ' stroke-dasharray="10 6"'}/>`;
  if (i.icon) b += icon(f.icon, 16, 16, 34, lit ? X.black : X.white, 2.8);
  const sub = subline(f, i);
  if (i.state) {
    const t = stateText(f).toUpperCase();
    const vf = fitSize(t + (f.unit && f.online ? " " + f.unit : ""), [30, 26, 22, 18, 15], 116, 900);
    b += text(16, sub ? 86 : 92, vf.text, { size: vf.size, weight: 900, fill: !f.online ? X.hcRed : lit ? X.black : f.stateColour ? X.hcYellow : X.white });
  }
  if (sub) b += text(16, 104, fit(sub, 13.5, 114, 800), { size: 13.5, weight: 800, fill: lit ? X.black : X.hcYellow });
  if (i.graph && (f.series.length >= 2 || f.level !== null)) {
    const g = graph(f, i, 64, 24, 64, 22, lit ? X.black : X.hcYellow, ink, "g");
    b += g.body.replace(/url\(#g\)/, lit ? X.white : X.black);
  }
  b += nameBlock(f, sub && i.state ? { ...o, info: { ...i, room: false } } : o, 16, 131, 114, ink, 15, "start", i.state || sub ? 1 : 2, lit ? X.black : X.white).svg.replace(/font-weight="650"/g, 'font-weight="800"');
  b += badges(f, i, ink, 14, true);
  return doc(b);
}

// ------------------------------------------------------------------ (1.2) the clear looks
//
// Ten looks that say one thing big - the state or the value - and at most one small line
// with it (the name, else the room). A thermostat adds its target and mode and a moving blind
// says so; the power, the trend and the rest stay off these keys even when they are shown
// elsewhere. Every piece still goes when its choice is switched off, and the graph is drawn
// only where it fits without clutter: a level as a bar, an arc or a fill, a sparkline, columns.

/** The one small line: the name, else the room. */
function caption(f: Face, o: LookOpts, x: number, y: number, maxW: number, size: number, fill: string, anchor: "start" | "middle" = "middle", weight = 650, opacity?: number): string {
  const i = o.info;
  const t = i.name && f.name ? f.name : i.room && f.room ? f.room : "";
  if (!t) return "";
  const nl = nameLines(t, o.fit, size, maxW, weight, 1);
  return text(x, y, nl.lines[0]!, { size: nl.size, weight, fill, anchor, opacity });
}

/** What is essential besides the state: a thermostat's target and mode, a blind on its way. */
function tag(f: Face, i: Info): string {
  if (!f.online || !i.state) return "";
  if (f.kind === "thermostat") {
    // "→ 22.0 °C" said as "→ 22.0°": the unit is already by the big value
    const d = i.detail ? f.detail.replace(/\s*°[CF]$/, "°") : "";
    return [d, i.mode ? f.mode : ""].filter(Boolean).join(" · ");
  }
  if (f.kind === "blinds") return i.detail ? f.detail : "";
  return "";
}

/** The tag in one line, a little smaller before it is cut. */
function tagText(x: number, y: number, t: string, maxW: number, size: number, fill: string, anchor: "start" | "middle" = "start", opacity?: number): string {
  const s = fitSize(t, [size, size * 0.9, size * 0.8], maxW, 700);
  return text(x, y, s.text, { size: s.size, weight: 700, fill, anchor, opacity });
}

interface Big { words: string; unit: string; size: number }

/** The big words: the state and its unit (with the state hidden, the detail and the mode, smaller). Size 0: nothing to say. */
function bigWords(f: Face, i: Info, sizes: number[], maxW: number, weight = 800, upper = false): Big {
  if (!i.state) {
    const s = subline(f, i);
    if (!s) return { words: "", unit: "", size: 0 };
    const t = fitSize(s, sizes.map((a) => Math.round(a * 0.55)), maxW, weight);
    return { words: t.text, unit: "", size: t.size };
  }
  const v = upper ? stateText(f).toUpperCase() : stateText(f);
  const unit = f.unit && f.online ? f.unit : "";
  const room = unit ? maxW - Math.min(44, textWidth(unit, Math.max(11, sizes[0]! * 0.42), 650) + 4) : maxW;
  const vf = fitSize(v, sizes, room, weight);
  return { words: vf.text, unit, size: vf.size };
}

/** Draws the big words: the unit a smaller tspan, offline in red. */
function drawBig(b: Big, f: Face, x: number, y: number, fill: string, unitFill: string, anchor: "start" | "middle" | "end", extra = "", spacing = -0.6): string {
  if (!b.size) return "";
  const u = b.unit ? `<tspan dx="3" font-size="${n(Math.max(11, b.size * 0.42))}" font-weight="650" fill="${unitFill}">${escText(fit(b.unit, 14, 44, 650))}</tspan>` : "";
  const t = text(x, y, b.words, { size: b.size, weight: 800, fill: f.online ? fill : P.crit, anchor, spacing });
  return (extra ? t.replace("<text ", "<text " + extra + " ") : t).replace(/<\/text>$/, u + "</text>");
}

/** The level a look may draw: the item's own (a brightness, a position, a target), else where a reading stands in its history. */
function levelOf(f: Face, i: Info): number | null {
  if (!i.graph || !f.online) return null;
  if (f.level !== null && f.kind !== "reading") return Math.max(0, Math.min(1, f.level));
  const v = f.series.filter((a) => Number.isFinite(a));
  if (f.kind === "reading" && v.length >= 2) {
    const lo = Math.min(...v), hi = Math.max(...v);
    return hi - lo < 1e-9 ? 0.5 : (v[v.length - 1]! - lo) / (hi - lo);
  }
  return null;
}

/** A colour of ours that sits well beside the accent in a gradient. */
function companion(c: string): string {
  const m: Record<string, string> = {
    [P.info]: P.purple, [P.ok]: P.water, [P.warn]: P.orange, [P.crit]: P.pink, [P.purple]: P.pink, [P.orange]: P.crit,
    [P.water]: P.info, [P.pink]: P.purple, [X.yellow]: P.orange, [X.silver]: P.info, [P.dim]: P.muted,
  };
  return m[c] ?? P.purple;
}

const radial = (id: string, stops: [number, string, number][], cx = 0.5, cy = 0.5, r = 0.5) =>
  `<radialGradient id="${id}" cx="${n(cx)}" cy="${n(cy)}" r="${n(r)}">` + stops.map(([o, c, a]) => `<stop offset="${n(o)}" stop-color="${c}" stop-opacity="${n(a)}"/>`).join("") + `</radialGradient>`;

/** Nothing but the icon is to be shown: it is drawn big, in the middle. */
const iconAlone = (f: Face, o: LookOpts) => o.info.icon && !o.info.state && !subline(f, o.info) && !(o.info.name && f.name) && !(o.info.room && f.room);

/** Huge: the value fills the key, a soft glow rising under it when lit, the name small at the foot. */
function huge(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const glow = f.stateColour ?? c;
  let defs = radial("glow", [[0, glow, 0.5], [1, glow, 0]], 0.5, 1, 0.8);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) b += `<rect width="144" height="144" fill="url(#glow)"/>`;
  const cap = caption(f, o, 72, 134, 124, 14, lit ? P.text : P.dim);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 32, 32, 80, lit ? c : P.muted, 2);
  else if (i.icon) b += icon(f.icon, 14, 14, 22, lit ? c : f.online ? P.muted : P.crit, 2.2);
  const lv = levelOf(f, i);
  if (i.graph && f.online && f.series.length >= 2) {
    const g = graph(f, { ...i, scale: false }, -2, 58, 148, 56, glow, ink, "g");
    b += `<g opacity="${lit ? 0.5 : 0.32}">${g.body}</g>`;
    defs += g.defs;
  } else if (lv !== null) b += rect(0, 140, 144, 4, 0, P.line) + rect(0, 140, Math.max(4, 144 * lv), 4, 0, lit ? c : P.muted);
  const bottom = (cap ? 114 : 136) - (tg ? 18 : 0);
  const big = bigWords(f, i, [80, 72, 64, 56, 48, 42, 36, 30, 26], 130);
  const top = i.icon ? 40 : 12;
  const vy = (top + bottom) / 2 + big.size * 0.36;
  b += drawBig(big, f, 72, vy, f.stateColour ?? (lit ? c : P.dim), lit ? P.text : P.muted, "middle");
  if (tg) b += tagText(72, bottom + 14, tg, 128, 14, lit ? c : P.dim, "middle");
  b += cap;
  b += badges(f, i, ink);
  return doc(b, defs);
}

/** Pill: the state in a big rounded pill - filled with the accent when lit, an empty outline when not. */
function pill(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = lit && f.stateColour ? f.stateColour : c;
  const defs = grad("bg", P.panel2, 1, P.bg, 1) + grad("pill", base, 1, base, 0.8, 1, 1) + grad("sheen", X.white, 0.34, X.white, 0);
  let b = rect(0, 0, 144, 144, 0, "url(#bg)");
  if (iconAlone(f, o)) return doc(b + icon(f.icon, 36, 36, 72, lit ? c : P.muted, 2) + badges(f, i, ink, 12, true), defs);
  const cap = caption(f, o, 72, 134, 124, 14, P.dim);
  const tg = tag(f, i);
  const lv = levelOf(f, i);
  const big = bigWords(f, i, [36, 32, 28, 24, 20, 17], 104);
  const below = tg ? 22 : lv !== null ? 16 : 0;
  const room = (cap ? 116 : 136) - 10;
  const tight = (i.icon ? 40 : 0) + 56 + below > room;
  const ph = tight ? 48 : 56;
  const pillH = big.size ? ph : 0;
  const iconH = i.icon ? (tight ? 32 : 40) : 0;
  const is = big.size ? (tight ? 24 : 30) : 44;
  const top = 10 + Math.max(0, (room - iconH - pillH - below) / 2);
  const py = top + iconH;
  if (i.icon) b += icon(f.icon, 72 - is / 2, big.size ? py - is - 6 : top + 4, is, lit ? c : f.online ? P.dim : P.crit, 2.2);
  if (big.size) {
    if (lit) {
      b += `<rect x="10" y="${n(py + 4)}" width="124" height="${ph}" rx="${ph / 2}" fill="${base}" fill-opacity="0.25"/>`;
      b += `<rect x="10" y="${n(py)}" width="124" height="${ph}" rx="${ph / 2}" fill="url(#pill)"/>`;
      b += `<rect x="20" y="${n(py + 3)}" width="104" height="${ph / 2 - 4}" rx="${(ph / 2 - 4) / 2}" fill="url(#sheen)"/>`;
    } else b += `<rect x="11" y="${n(py + 1)}" width="122" height="${ph - 2}" rx="${(ph - 2) / 2}" fill="${P.panel}" stroke="${f.online ? P.line : P.crit}" stroke-width="2.5"${f.online ? "" : ' stroke-dasharray="7 5"'}/>`;
    b += drawBig(big, f, 72, py + ph / 2 + big.size * 0.35, lit ? P.bg : f.stateColour ?? P.dim, lit ? P.panel2 : P.muted, "middle", "", -0.4);
  }
  const y = py + pillH;
  if (tg) b += tagText(72, y + 19, tg, 124, 13, lit ? c : P.dim, "middle");
  else if (lv !== null) b += rect(40, y + 9, 64, 5, 2.5, P.line) + rect(40, y + 9, Math.max(5, 64 * lv), 5, 2.5, lit ? c : P.muted);
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

/** Orb: a glowing sphere, lit from inside when on, a dark glass ball when off; the state under it. */
function orb(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = lit && f.stateColour ? f.stateColour : c;
  const cap = caption(f, o, 72, 136, 124, 13, P.dim);
  const tg = tag(f, i);
  const big = bigWords(f, i, [32, 28, 24, 20, 16], 124);
  const lv = levelOf(f, i);
  const ringR = lv !== null ? 7 : 0;
  const below = (big.size ? big.size + 6 : 0) + (tg ? 16 : 0);
  const room = (cap ? 120 : 138) - 8;
  const r = Math.max(22, Math.min(46, (room - below - 2 * ringR - 6) / 2));
  const cy = 8 + ringR + r + Math.max(0, (room - below - 2 * ringR - 2 * r) / 2);
  const defs = radial("halo", [[0, base, 0.5], [0.55, base, 0.14], [1, base, 0]])
    + (lit ? radial("ball", [[0, X.white, 1], [0.3, base, 1], [1, base, 0.55]], 0.36, 0.3, 0.75)
      : radial("ball", [[0, P.panel2, 1], [0.7, P.panel, 1], [1, X.night, 1]], 0.36, 0.3, 0.8))
    + grad("spec", X.white, 0.55, X.white, 0);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) b += `<circle cx="72" cy="${n(cy)}" r="${n(r * 1.75)}" fill="url(#halo)"/>`;
  b += `<circle cx="72" cy="${n(cy)}" r="${n(r)}" fill="url(#ball)"${lit ? "" : ` stroke="${f.online ? P.line : P.crit}" stroke-width="2"${f.online ? "" : ' stroke-dasharray="5 4"'}`}/>`;
  b += `<ellipse cx="${n(72 - r * 0.22)}" cy="${n(cy - r * 0.55)}" rx="${n(r * 0.5)}" ry="${n(r * 0.26)}" fill="url(#spec)"${lit ? "" : ' opacity="0.35"'}/>`;
  if (lv !== null) {
    b += `<circle cx="72" cy="${n(cy)}" r="${n(r + ringR)}" fill="none" stroke="${P.line}" stroke-width="3.5"/>`;
    if (lv > 0) b += `<path d="${arcPath(72, cy, r + ringR, 0, 360 * lv)}" fill="none" stroke="${lit ? base : P.muted}" stroke-width="3.5" stroke-linecap="round"/>`;
  }
  if (i.icon) {
    const s = r * 1.05;
    b += icon(f.icon, 72 - s / 2, cy - s / 2, s, lit ? P.bg : f.online ? P.muted : P.crit, 2.3);
  }
  let y = cy + r + ringR;
  if (big.size) {
    y += big.size + 4;
    b += drawBig(big, f, 72, y, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "middle");
  }
  if (tg) b += tagText(72, y + 16, tg, 124, 12.5, lit ? base : P.dim, "middle");
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

/** Tile: an app-icon tile - filled with the accent when lit - and the state in one big word under it. */
function tile(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = lit && f.stateColour ? f.stateColour : c;
  const defs = grad("tile", base, 1, base, 0.72, 1, 1) + grad("sheen", X.white, 0.3, X.white, 0);
  let b = rect(0, 0, 144, 144, 0, P.bg);
  const dash = f.online ? "" : ' stroke-dasharray="6 4"';
  if (iconAlone(f, o)) {
    b += lit ? rect(28, 28, 88, 88, 26, "url(#tile)") : rect(28, 28, 88, 88, 26, P.panel2, `stroke="${f.online ? P.line : P.crit}" stroke-width="2"${dash}`);
    b += icon(f.icon, 44, 44, 56, lit ? P.bg : f.online ? P.dim : P.crit, 2.2);
    return doc(b + badges(f, i, ink, 12, true), defs);
  }
  const cap = caption(f, o, 14, 134, 118, 14, P.dim, "start");
  const tg = tag(f, i);
  const big = bigWords(f, i, [42, 36, 30, 26, 22, 18], 118);
  const lv = levelOf(f, i);
  const t = cap && tg ? 54 : cap || tg ? 62 : 68;
  if (i.icon) {
    b += lit ? rect(14, 12, t, t, t * 0.29, "url(#tile)") + rect(19, 14, t - 10, t * 0.4, t * 0.2, "url(#sheen)")
      : rect(14, 12, t, t, t * 0.29, P.panel2, `stroke="${f.online ? P.line : P.crit}" stroke-width="2"${dash}`);
    const s = t * 0.58;
    b += icon(f.icon, 14 + (t - s) / 2, 12 + (t - s) / 2, s, lit ? P.bg : f.online ? P.dim : P.crit, 2.3);
  }
  if (lv !== null) {
    // the level: a slim upright bar beside the tile, or a bar across the top without one
    const h = Math.max(6, t * lv);
    b += i.icon ? rect(14 + t + 9, 12, 6, t, 3, P.line) + rect(14 + t + 9, 12 + t - h, 6, h, 3, lit ? base : P.muted)
      : rect(14, 18, 116, 6, 3, P.line) + rect(14, 18, Math.max(6, 116 * lv), 6, 3, lit ? base : P.muted);
  }
  const by = (cap ? 114 : 132) - (tg ? 18 : 0);
  b += drawBig(big, f, 12, by, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "start");
  if (tg) b += tagText(14, by + 18, tg, 118, 13, lit ? base : P.dim);
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

/** Gauge: a thick 270° arc that fills with the level (whole when lit), the big number in its middle. */
function gauge(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = f.stateColour && lit ? f.stateColour : c;
  const cx = 72, cy = 70, r = 50, a0 = -135, a1 = 135;
  const defs = `<linearGradient id="arc" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="${companion(base)}" stop-opacity="1"/><stop offset="1" stop-color="${base}" stop-opacity="1"/></linearGradient>`
    + radial("glow", [[0, base, 0.24], [1, base, 0]]);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) b += `<circle cx="${cx}" cy="${cy}" r="64" fill="url(#glow)"/>`;
  b += `<path d="${arcPath(cx, cy, r, a0, a1)}" fill="none" stroke="${f.online ? P.line : P.crit}" stroke-opacity="${f.online ? 1 : 0.4}" stroke-width="12" stroke-linecap="round"/>`;
  const lv = levelOf(f, i) ?? (lit ? 1 : 0);
  if (f.online && lv > 0.005) {
    const end = a0 + (a1 - a0) * lv;
    b += `<path d="${arcPath(cx, cy, r, a0, end)}" fill="none" stroke="${lit ? "url(#arc)" : P.muted}" stroke-width="12" stroke-linecap="round"/>`;
    const rad = ((end - 90) * Math.PI) / 180;
    b += `<circle cx="${n(cx + r * Math.cos(rad))}" cy="${n(cy + r * Math.sin(rad))}" r="3.6" fill="${X.white}" fill-opacity="${lit ? 0.95 : 0.5}"/>`;
  }
  const tg = tag(f, i);
  const big = bigWords(f, i, [40, 36, 32, 28, 24, 20], 86);
  if (!big.size && i.icon) b += icon(f.icon, cx - 22, cy - 22, 44, lit ? base : f.online ? P.muted : P.crit, 2.1);
  else {
    if (i.icon) b += icon(f.icon, cx - 11, 36, 22, lit ? base : f.online ? P.muted : P.crit, 2.2);
    b += drawBig(big, f, cx, i.icon ? 88 : 82, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "middle");
  }
  // the target and the mode in the gap under the arc, the name below them
  if (tg) b += tagText(cx, 125, tg, 120, 13, lit ? base : P.dim, "middle");
  b += caption(f, o, 72, tg ? 140 : 136, 120, tg ? 12 : 13.5, lit ? P.text : P.dim);
  b += badges(f, i, ink, 10, true);
  return doc(b, defs);
}

/** Bars: the big number over chunky bars - the level as a meter, a reading's recent values as columns. */
function bars(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = f.stateColour ?? c;
  const defs = grad("glow", base, 0, base, 0.18);
  let b = rect(0, 0, 144, 144, 0, P.bg);
  if (lit) b += `<rect width="144" height="144" fill="url(#glow)"/>`;
  if (iconAlone(f, o)) return doc(b + icon(f.icon, 36, 36, 72, lit ? c : P.muted, 2) + badges(f, i, ink), defs);
  if (i.icon) b += icon(f.icon, 13, 12, 22, lit ? c : f.online ? P.muted : P.crit, 2.2);
  const cap = caption(f, o, 72, 136, 124, 13.5, P.dim);
  const foot = cap ? 118 : 132;
  // the bars: the recent values, else the level, else none
  const v = f.series.filter((a) => Number.isFinite(a)).slice(-9);
  const lv = levelOf(f, i);
  let cols: { h: number; on: boolean; last: boolean }[] = [];
  if (i.graph && f.online && v.length >= 2) {
    const lo = Math.min(...v), hi = Math.max(...v);
    cols = v.map((a, k) => ({ h: hi - lo < 1e-9 ? 0.5 : (a - lo) / (hi - lo), on: true, last: k === v.length - 1 }));
  } else if (lv !== null) {
    const k = lv <= 0 ? 0 : Math.max(1, Math.round(lv * 6));
    cols = [0, 1, 2, 3, 4, 5].map((j) => ({ h: (j + 1) / 6, on: j < k, last: false }));
  }
  const tg = tag(f, i);
  const has = cols.length > 0;
  const big = bigWords(f, i, has ? [48, 44, 38, 32, 26, 22] : [60, 54, 48, 42, 36, 30, 24], 124);
  const barH = has ? (tg ? 24 : 30) : 0;
  const vy = has ? foot - barH - (tg ? 30 : 12) : foot - (tg ? 30 : 22) + (cap ? 0 : -6);
  b += drawBig(big, f, 72, vy, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "middle");
  if (tg) b += tagText(72, vy + 18, tg, 124, 13, lit ? c : P.dim, "middle");
  if (has) {
    const top = foot - barH, gap = cols.length > 6 ? 4 : 6;
    const w = (116 - gap * (cols.length - 1)) / cols.length;
    cols.forEach((col, k) => {
      const h = 5 + (barH - 5) * col.h;
      const x = 14 + k * (w + gap);
      b += rect(x, top, w, barH, Math.min(4, w / 3), P.panel2);
      if (col.on) b += rect(x, foot - h, w, h, Math.min(4, w / 3), lit || col.last ? base : P.muted, col.last || lv !== null || v.length < 2 ? "" : 'fill-opacity="0.55"');
    });
  } else if (!tg && big.size && f.online && i.graph) {
    // nothing to measure: one fat bar says on or off
    b += rect(52, vy + 12, 40, 7, 3.5, lit ? base : P.line);
  }
  b += cap;
  b += badges(f, i, ink, 11);
  return doc(b, defs);
}

/** Wave: the key fills with the accent like water - to the level, or two thirds when on - big white words over it. */
function wave(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = f.stateColour && lit ? f.stateColour : c;
  const lv = !f.online ? 0 : levelOf(f, i) ?? (lit ? 0.64 : 0);
  const defs = grad("water", base, 0.95, base, 0.6) + grad("back", base, 0.5, base, 0.22);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lv > 0.003) {
    const y = 144 - Math.max(8, lv * 140);
    const w = (dy: number, flip: number) => {
      let d = `M -10 ${n(y + dy)}`;
      for (let k = 0; k < 4; k++) {
        const x = -10 + k * 42;
        d += ` Q ${n(x + 10.5)} ${n(y + dy + (k % 2 === flip ? -5 : 5))} ${n(x + 21)} ${n(y + dy)} T ${n(x + 42)} ${n(y + dy)}`;
      }
      return d + " L 160 160 L -10 160 Z";
    };
    // unlit, grey water - but a reading keeps its colour, dimmed: its value is never "off"
    const calm = f.kind === "reading" && f.stateColour ? f.stateColour : null;
    b += `<path d="${w(-4, 1)}" fill="${lit ? "url(#back)" : calm ?? P.panel2}"${!lit && calm ? ' fill-opacity="0.1"' : ""}/>`;
    b += `<path d="${w(0, 0)}" fill="${lit ? "url(#water)" : calm ?? P.line}"${!lit && calm ? ' fill-opacity="0.2"' : ""}/>`;
  }
  const cap = caption(f, o, 72, 134, 124, 14, lit ? X.white : P.dim, "middle", 700, lit ? 0.92 : undefined);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 36, 22, 72, lit ? X.white : P.muted, 2);
  else if (i.icon) b += icon(f.icon, 14, 14, 24, lit && lv > 0.82 ? X.white : lit ? c : f.online ? P.muted : P.crit, 2.2);
  const big = bigWords(f, i, [54, 48, 42, 36, 30, 24], 124);
  const vy = (tg ? 76 : 84) + (cap ? 0 : 6);
  if (big.size && lit) b += drawBig(big, f, 73.5, vy + 2, X.night, X.night, "middle", 'fill-opacity="0.3"');
  b += drawBig(big, f, 72, vy, lit ? X.white : f.stateColour ?? P.dim, lit ? X.white : P.muted, "middle");
  if (tg) b += tagText(72, vy + 21, tg, 124, 13.5, lit ? X.white : P.dim, "middle");
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

/** Aurora: lit, a gradient of the accent and its neighbour with soft light in it and big white words; unlit, dusk. */
function aurora(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = f.stateColour && lit ? f.stateColour : c;
  let defs = lit ? grad("sky", base, 1, companion(base), 1, 1, 1) : grad("sky", P.panel2, 1, X.night, 1, 1, 1);
  defs += radial("a1", [[0, X.white, lit ? 0.4 : 0.06], [1, X.white, 0]]) + radial("a2", [[0, lit ? X.night : base, lit ? 0.42 : 0.24], [1, lit ? X.night : base, 0]]);
  let b = rect(0, 0, 144, 144, 0, "url(#sky)");
  b += `<ellipse cx="26" cy="16" rx="92" ry="56" fill="url(#a1)"/><ellipse cx="130" cy="140" rx="96" ry="72" fill="url(#a2)"/>`;
  const cap = caption(f, o, 72, 132, 124, 14.5, lit ? X.white : P.dim, "middle", 700, lit ? 0.92 : undefined);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 36, 36, 72, lit ? X.white : P.muted, 2);
  else if (i.icon) b += icon(f.icon, 14, 14, 26, lit ? X.white : f.online ? P.muted : P.crit, 2.2);
  const lv = levelOf(f, i);
  const spark = i.graph && f.online && f.series.length >= 2 && !tg;
  const big = bigWords(f, i, [54, 48, 42, 36, 30, 24], 126);
  const vy = (tg || spark ? 80 : 88) + (cap ? 0 : 8);
  b += drawBig(big, f, 72, vy, lit ? X.white : f.stateColour ?? P.dim, lit ? X.white : P.muted, "middle");
  if (tg) b += tagText(72, vy + 20, tg, 124, 13.5, lit ? X.white : P.dim, "middle", lit ? 0.92 : undefined);
  if (spark) {
    const g = graph(f, { ...i, scale: false, target: false }, 24, 92, 96, 18, lit ? X.white : P.muted, lit ? { ...ink, bg: base } : ink, "g");
    b += `<g opacity="0.85">${g.body}</g>`;
    defs += g.defs;
  } else if (lv !== null) b += rect(36, 140, 72, 4, 2, lit ? X.white : P.line, lit ? 'fill-opacity="0.3"' : "") + rect(36, 140, Math.max(4, 72 * lv), 4, 2, lit ? X.white : P.muted);
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

/** Outline: a thick accent border when lit (going round as far as the level), a faint line when off. */
function outline(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = f.stateColour && lit ? f.stateColour : c;
  let b = rect(0, 0, 144, 144, 0, X.night);
  const box = `x="8" y="8" width="128" height="128" rx="26"`;
  const per = 4 * 128 - 8 * 26 + 2 * Math.PI * 26;
  const lv = levelOf(f, i);
  if (lit) {
    b += `<rect ${box} fill="${base}" fill-opacity="0.08"/>`;
    if (lv !== null && lv < 0.995) {
      b += `<rect ${box} fill="none" stroke="${base}" stroke-opacity="0.22" stroke-width="9"/>`;
      b += `<rect ${box} fill="none" stroke="${base}" stroke-width="9" stroke-dasharray="${n(Math.max(1, per * lv))} ${n(per)}"/>`;
    } else b += `<rect ${box} fill="none" stroke="${base}" stroke-width="9"/>`;
  } else {
    b += `<rect ${box} fill="none" stroke="${f.online ? P.line : P.crit}" stroke-width="3"${f.online ? "" : ' stroke-dasharray="8 6"'}/>`;
    if (lv !== null && lv > 0) b += `<rect ${box} fill="none" stroke="${P.muted}" stroke-width="3" stroke-dasharray="${n(Math.max(1, per * lv))} ${n(per)}"/>`;
  }
  const cap = caption(f, o, 72, 118, 104, 14, lit ? P.text : P.dim);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 38, 38, 68, lit ? base : P.muted, 2);
  else if (i.icon) b += icon(f.icon, 60, 22, 24, lit ? base : f.online ? P.muted : P.crit, 2.2);
  const big = bigWords(f, i, [46, 40, 34, 28, 24, 20], 106);
  const top = i.icon ? 48 : 20, bottom = (cap ? 100 : 124) - (tg ? 16 : 0);
  const vy = (top + bottom) / 2 + big.size * 0.36;
  b += drawBig(big, f, 72, vy, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "middle");
  if (tg) b += tagText(72, bottom + 12, tg, 104, 12.5, lit ? base : P.dim, "middle");
  b += cap;
  b += badges(f, i, ink, 13, true);
  return doc(b);
}

/** Mono: one colour only - a giant icon and the state in spaced capitals; lit, the key is tinted with it. */
function mono(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK;
  const lit = f.active && f.online;
  const m = !f.online ? P.crit : f.stateColour ?? (lit ? f.accent : P.muted);
  const defs = radial("tint", [[0, m, 0.3], [1, m, 0]], 0.5, 0.36, 0.6);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) b += rect(0, 0, 144, 144, 0, m, 'fill-opacity="0.1"') + `<rect width="144" height="144" fill="url(#tint)"/>`;
  const cap = caption(f, o, 72, 134, 124, 12.5, m, "middle", 650, lit ? 0.75 : 0.85);
  const tg = tag(f, i);
  const big = bigWords(f, i, [30, 26, 22, 18, 15], 124, 800, true);
  const lower = (cap ? 116 : 136) - (big.size ? big.size + 8 : 0) - (tg ? 16 : 0);
  if (i.icon) {
    const s = Math.max(30, Math.min(84, lower - 16));
    b += icon(f.icon, 72 - s / 2, (8 + lower) / 2 - s / 2, s, m, lit ? 2.1 : 1.7);
  }
  const y = i.icon ? lower + big.size + 4 : (cap ? 66 : 76) + big.size * 0.36 - (tg ? 8 : 0);
  b += drawBig(big, f, 72, y, m, m, "middle", "", 1.6);
  if (tg) b += tagText(72, y + 17, tg, 124, 12, m, "middle", 0.85);
  const lv = levelOf(f, i);
  if (lv !== null) b += rect(0, 141, 144, 3, 0, m, 'fill-opacity="0.25"') + rect(0, 141, Math.max(3, 144 * lv), 3, 0, m);
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

const LOOKS: Record<string, (f: Face, o: LookOpts) => string> = {
  minimal, bigvalue, fill: solid, neon, ring, split, glass, label, dot, light, contrast,
  huge, pill, orb, tile, gauge, bars, wave, aurora, outline, mono,
};

/** A key in one of the looks (not Classic, which render.ts draws as 1.0 did). */
export function renderLook(theme: string, f: Face, o: LookOpts): string {
  const draw = LOOKS[theme] ?? bigvalue;
  const i = o.info;
  // nothing at all would be a blank key: the icon at least
  const info = i.icon || i.name || i.state || i.room || i.detail || i.mode || i.graph ? i : { ...i, icon: true };
  return draw(f, { ...o, info });
}

/** The short card a press can show on a thermostat: its mode, the target, what it measures and where. */
export function renderDetails(title: string, rows: [string, string][], accent: string): string {
  let b = rect(0, 0, 144, 144, 0, P.bg) + `<rect x="3" y="3" width="138" height="138" rx="20" fill="${P.panel}" stroke="${accent}" stroke-width="2.2"/>`;
  b += text(72, 26, fit(title, 13.5, 124, 700), { size: 13.5, weight: 700, fill: P.text, anchor: "middle" });
  b += `<path d="M 16 35 H 128" stroke="${P.line}" stroke-width="1.5"/>`;
  rows.slice(0, 4).forEach(([k, v], j) => {
    const y = 56 + j * 25;
    b += text(16, y - 9, fit(k, 9.5, 112, 700).toUpperCase(), { size: 9.5, weight: 700, fill: P.muted, spacing: 0.6 });
    b += text(16, y + 6, fit(v || "—", 14, 114, 700), { size: 14, weight: 700, fill: j === 0 ? accent : P.text });
  });
  return svgDoc(144, 144, b);
}
