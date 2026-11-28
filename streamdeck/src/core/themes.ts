/**
 * (1.1) The looks a key can be given. Classic is the 1.0 drawing (render.ts, unchanged); every
 * other look draws a Face - what any action has to say, in the same words - in its own style.
 * Every look honours the same choices of what is shown (Info), the accent colour, the label and
 * how long names are laid out, and keeps offline, locked and hold readable.
 * Colours come only from palette.ts; every piece of text goes through esc() (svg.ts text()).
 */
import { ACCENTS, P, X } from "./palette.js";
import { arcPath, fit, fitSize, icon, n, nameLines, rect, svgDoc, text, type NameFit } from "./svg.js";

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

const LOOKS: Record<string, (f: Face, o: LookOpts) => string> = {
  minimal, bigvalue, fill: solid, neon, ring, split, glass, label, dot, light, contrast,
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
