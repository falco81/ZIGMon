/**
 * (1.1) The looks a key can be given. Classic is the 1.0 drawing (render.ts, unchanged); every
 * other look draws a Face - what any action has to say, in the same words - in its own style.
 * Every look honours the same choices of what is shown (Info), the accent colour, the label and
 * how long names are laid out, and keeps offline, locked and hold readable.
 * Colours come only from palette.ts; every piece of text goes through esc() (svg.ts text()).
 */
import { colourOf, P, X } from "./palette.js";
import { seriesScale, type Quantity } from "./scale.js";
import {
  arcPath, fit, fitSize, fitSizeK, grow, growAll, smallerThan, icon, mixLine, n, nameLines, ONE, pairParts, rect, roleAttr, svgDoc, text, textWidth, type NameFit, type Part, type TextRole, type TextScale,
} from "./svg.js";

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
  // (1.3) twenty more, as clear, each with its own shape
  { id: "diagonal", name: "Diagonal", hint: "a coloured corner, the value across" },
  { id: "hex", name: "Hex", hint: "a hexagon plate" },
  { id: "stripe", name: "Stripe", hint: "a side stripe that fills" },
  { id: "switch", name: "Switch", hint: "a toggle switch over the value" },
  { id: "lcd", name: "LCD", hint: "a retro screen" },
  { id: "dial", name: "Dial", hint: "a knob with a ring of ticks" },
  { id: "ticket", name: "Ticket", hint: "a ticket with a coloured stub" },
  { id: "bubble", name: "Bubble", hint: "the state in a speech bubble" },
  { id: "frame", name: "Frame", hint: "corner brackets when on" },
  { id: "shadow", name: "Shadow", hint: "a card with a coloured shadow" },
  { id: "line", name: "Line", hint: "the value over one line" },
  { id: "tube", name: "Tube", hint: "a thermometer tube that fills" },
  { id: "stamp", name: "Stamp", hint: "a giant faint icon behind the value" },
  { id: "pastel", name: "Pastel", hint: "soft colour, dark type" },
  { id: "carbon", name: "Carbon", hint: "carbon weave and a light strip" },
  { id: "grid", name: "Grid", hint: "a grid of lamps that fills" },
  { id: "tab", name: "Tab", hint: "a folder with the name on its tab" },
  { id: "rise", name: "Rise", hint: "a sun rising with the level" },
  { id: "spot", name: "Spot", hint: "a spotlight on the value" },
  { id: "button", name: "Button", hint: "a real key, pressed when on" },
  // (1.3) eighteen name-first looks: the name big and whole, the status right with it
  { id: "namebar", name: "Name bar", hint: "the name on a coloured band, the status under it" },
  { id: "caption", name: "Caption", hint: "the name centred, the status in a pill" },
  { id: "led", name: "LED", hint: "the name, a lit lamp and the status" },
  { id: "tworows", name: "Two rows", hint: "the name and the status split by a line" },
  { id: "plate", name: "Plate", hint: "an engraved nameplate with a status window" },
  { id: "ticker", name: "Ticker", hint: "the name over a status strip" },
  { id: "card", name: "Card", hint: "an icon tile, the name and the status beside it" },
  { id: "halves", name: "Halves", hint: "the name on top, the status on a coloured half" },
  { id: "stacked", name: "Stacked", hint: "the name, the status, a tiny icon" },
  { id: "corner", name: "Corner", hint: "the name big, the status in a corner badge" },
  { id: "lined", name: "Lined", hint: "the name underlined in the accent when on" },
  { id: "terminal", name: "Terminal", hint: "a console: the name, then > status" },
  { id: "marquee", name: "Marquee", hint: "the name in a ring of bulbs" },
  { id: "widget", name: "Widget", hint: "a phone widget, the name at its foot" },
  { id: "sign", name: "Sign", hint: "a road sign with the name on it" },
  { id: "note", name: "Note", hint: "an index card, the status highlighted" },
  { id: "pass", name: "Pass", hint: "a lanyard pass, the name big" },
  { id: "glow", name: "Glow", hint: "the name itself glows when on" },
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
  /**
   * 0..1 - where the shown value stands in its true range: a brightness, a position, a battery, a
   * thermostat's temperature within its set point's range. Null without a real range (scale.ts).
   */
  level: number | null;
  /** History of the shown value - the same quantity - oldest first, and the value to draw dashed across it. Empty when the state is a word. */
  series: number[];
  target: number | null;
  /** (1.3) What the series measures, for an honest scale (scale.ts); none: from its unit alone. */
  scale?: Quantity | null;
  /** (1.3) The target on the level's scale (0..1): a thermostat's set point, marked on its arc. */
  mark?: number | null;
  online: boolean;
  allowed: boolean;
  hold: boolean;
  battery: number | null;
  /** (1.2) Taken over by hand: rules and schedules leave it alone. */
  taken?: boolean;
  /** (1.3) The colour an off key is drawn in, when the user chose one; none = the look's own off style. */
  offAccent?: string | null;
  /** (1.3) An unread count (the SMS keys): a small pill at the top right. */
  badge?: number | null;
}

/** (1.3) The new actions say one more short thing under the big words in the clear looks: their detail. */
const TAGGED = new Set(["power", "security", "heatgroup", "away", "openings", "batteries", "zigbee", "timer", "room", "sms"]);

export interface LookOpts {
  info: Info;
  fit: NameFit;
  /** (1.3) The size of each kind of text; none = as before. */
  ts?: TextScale;
}

/** (1.3) The text sizes of the key being drawn (renderLook sets them; drawing is synchronous). */
let T: TextScale = ONE;
/** How far a size may grow where a look has fixed places: the role's own limit on its size. */
const CAPF: Record<TextRole, number> = { value: 1.4, name: 1.45, room: 1.5, detail: 1.5, mode: 1.5, unit: 1.6, badge: 1.4 };
/** A size in its role, held to `cap` px (else to the role's own limit; null: as big as asked). */
const S = (role: TextRole, size: number, cap?: number | null): number => grow(size, T[role], cap === null ? undefined : cap ?? size * CAPF[role]);
/** Candidate sizes in their role, alike. */
const SS = (role: TextRole, sizes: number[], cap?: number | null): number[] =>
  growAll(sizes, T[role], (s) => (cap === null ? undefined : cap ?? s * CAPF[role]));
/** The room a fixed baseline leaves for big text under `top`: the largest size whose capitals stay below it. */
const room = (y: number, top: number): number => (y - top) / 0.74;
/** (1.3) Some text is drawn bigger than at 100 %: what is near it may have to give way. */
const bigger = (): boolean => T.value > 1 || T.name > 1 || T.room > 1 || T.detail > 1 || T.mode > 1 || T.unit > 1 || T.badge > 1;
/** How much taller a size grew (0 at 100 %). */
const dz = (z: number, base: number): number => z - base;

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
  return colourOf(name) || auto;
}

/** (1.3) Where a look draws an unlit key in its grey (`grey`): the user's Off colour instead, if one is set. */
function offInk(f: Face, grey: string): string {
  return f.offAccent && f.online && !f.active ? f.offAccent : grey;
}

/** (1.3) An Off colour applies to this key now (it is online, unlit, and one is set). */
const offLit = (f: Face): boolean => !!f.offAccent && f.online && !f.active;

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
  const ns = S("name", size);
  if (ns > size * 1.25) lines = 1;
  if (o.info.room && f.room) {
    const rs = S("room", size * 0.8);
    svg += text(x, y, fit(f.room, rs, maxW, 500), { size: rs, weight: 500, fill: ink.dim, anchor, role: "room" });
    y -= size * 1.12 + dz(ns, size) * 0.76 + dz(rs, size * 0.8) * 0.2;
    lines = 1;
  }
  if (o.info.name && f.name) {
    const nl = nameLines(f.name, o.fit, ns, maxW, 650, lines);
    for (let i = nl.lines.length - 1; i >= 0; i--) {
      svg += text(x, y, nl.lines[i]!, { size: nl.size, weight: 650, fill: nameColour ?? ink.text, anchor, role: "name" });
      y -= nl.size * 1.14;
    }
  }
  return { svg, top: y };
}

/** The graph: the history (with its target dashed and min / max when asked), else a level bar. */
export function graph(f: Face, info: Info, x: number, y: number, w: number, h: number, colour: string, ink: Ink, id: string, labelK = T.detail): { defs: string; body: string } {
  const v = f.series.filter((a) => Number.isFinite(a)).slice(-96);
  if (v.length >= 2) {
    const tgt = info.target && f.target !== null && Number.isFinite(f.target) ? f.target : null;
    // (1.3) an honest scale: the quantity's own range, from 0, or a sensible span - never min to max
    const { lo, hi } = seriesScale(v, f.scale ?? { unit: f.unit }, tgt !== null ? [tgt] : []);
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
      // as far as the two labels stay apart in the graph's height
      const ls = grow(9.5, labelK, Math.min(9.5 * 1.2, 9.5 + Math.max(0, h - 22)));
      body += text(x + w, y + 8 + dz(ls, 9.5) * 0.7, fmt(hi), { size: ls, weight: 600, fill: ink.dim, anchor: "end", role: "detail" });
      body += text(x + w, y + h, fmt(lo), { size: ls, weight: 600, fill: ink.dim, anchor: "end", role: "detail" });
    }
    return {
      defs: `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${colour}" stop-opacity="0.34"/><stop offset="1" stop-color="${colour}" stop-opacity="0"/></linearGradient>`,
      body,
    };
  }
  if (f.level !== null) {
    const r = Math.min(4, h / 2);
    return { defs: "", body: rect(x, y + h / 2 - r, w, 2 * r, r, ink.line) + (f.online ? rect(x, y + h / 2 - r, Math.max(2 * r, w * Math.max(0, Math.min(1, f.level))), 2 * r, r, f.active ? colour : ink.muted) : "") };
  }
  if (f.kind === "reading" || f.kind === "thermostat") {
    return { defs: "", body: `<path d="M ${n(x)} ${n(y + h - 1)} H ${n(x + w)}" stroke="${ink.line}" stroke-width="2" stroke-linecap="round" stroke-dasharray="2 5"/>` };
  }
  return { defs: "", body: "" };
}

/** The value with its unit as a smaller tspan, sized to fit. */
/**
 * (1.3) The value and its unit at other sizes than 100 %: the largest of `cands` with which both
 * fit maxW - the unit at its own size (`uz`), else back at its size by the value's (`uz0`) - else the
 * smallest, cut. Returns the value's words and size and the unit's size.
 */
function fitWithUnit(v: string, cands: number[], unit: string, uz0: number, uz: number, maxW: number, weight: number, uweight: number, dx: number): { text: string; size: number; usize: number } {
  if (!unit) {
    const f = fitSize(v, cands, maxW, weight);
    return { text: f.text, size: f.size, usize: uz };
  }
  for (const u of uz > uz0 ? [uz, uz0] : [uz]) {
    const uw = textWidth(unit, u, uweight) + dx;
    for (const c of cands) if (textWidth(v, c, weight) + uw <= maxW) return { text: v, size: c, usize: u };
  }
  const c = cands[cands.length - 1]!, u = Math.min(uz, uz0);
  return { text: fit(v, c, Math.max(20, maxW - textWidth(unit, u, uweight) - dx), weight), size: c, usize: u };
}

function value(f: Face, x: number, y: number, maxW: number, sizes: number[], fill: string, ink: Ink, anchor: "start" | "middle" | "end" = "start", weight = 750, cap?: number | null): string {
  const v = stateText(f);
  const unit = f.unit && f.online ? f.unit : "";
  const uk = T.unit === 1 ? 1 : S("unit", 14) / 14;
  const room0 = unit ? maxW - Math.min(40, unit.length * 9) : maxW;
  let vf = fitSize(v, sizes, room0, weight);
  // the unit's size from the value as it would be at 100 %: the value's own size leaves it be
  const uz0 = Math.max(11, vf.size * 0.42);
  let uz = uz0;
  const ut = unit ? fit(unit, 14 * uk, 40 * uk, 600) : "";
  if (T.value !== 1 || uk !== 1) {
    const r = fitWithUnit(v, T.value < 1 ? smallerThan(SS("value", sizes), vf.size * T.value) : SS("value", sizes, cap), ut, uz0, uz0 * uk, maxW, weight, 600, 3);
    // (never smaller than at 100 % for being asked to be bigger: as at 100 %, then)
    if (!(T.value > 1 && r.size < vf.size)) {
      vf = { text: r.text, size: r.size };
      uz = r.usize;
    }
  }
  const u = unit ? `<tspan dx="3" font-size="${n(uz)}" font-weight="600" fill="${ink.dim}"${roleAttr("unit")}>${escText(ut)}</tspan>` : "";
  return text(x, y, vf.text, { size: vf.size, weight, fill: f.online ? fill : ink.crit, anchor, spacing: -0.4, role: "value" }).replace(/<\/text>$/, u + "</text>");
}

function escText(s: string): string {
  return text(0, 0, s, { size: 1, fill: P.text }).replace(/^<text[^>]*>/, "").replace(/<\/text>$/, "");
}

/** The second line under the state: the detail, then the mode, as far as each is shown. */
function subline(f: Face, info: Info): string {
  if (!f.online) return "";
  return [info.detail ? f.detail : "", info.mode ? f.mode : ""].filter(Boolean).join(" · ");
}

/** (1.3) The pieces of the subline: the detail and the mode, as far as each is shown. */
function subParts(f: Face, info: Info): Part[] {
  if (!f.online) return [];
  return pairParts(info.detail ? f.detail : "", info.mode ? f.mode : "");
}

/** The size the subline is drawn at, at its biggest piece (for what is laid out round it). */
function partsSize(parts: Part[], size: number): number {
  return parts.reduce((z, p) => Math.max(z, S(p[1], size)), 0) || size;
}

/** (1.3) The subline drawn in one line at `size`, its pieces each in their own size, fitted to maxW. */
function subText(f: Face, info: Info, x: number, y: number, size: number, maxW: number, o: { weight: number; fill: string; anchor?: "start" | "middle" | "end"; opacity?: number }): string {
  return mixLine(x, y, subParts(f, info), [size], maxW, o, T, (z) => z * CAPF.detail).svg;
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
    const ns = S("name", 13);
    const nl = nameLines(f.name, o.fit, ns, 128, 600, 1);
    body += text(72, 136, nl.lines[0]!, { size: nl.size, weight: 600, fill: ink.dim, anchor: "middle", role: "name" });
    bottom = 120 - dz(ns, 13) * 0.76;
  }
  if (i.graph && f.series.length >= 2) {
    const g = graph(f, i, 24, bottom - 18, 96, 18, f.stateColour ?? c, ink, "mg");
    body += g.body;
    defs += g.defs;
    bottom -= 24;
  } else if (i.graph && f.level !== null) {
    body += graph(f, i, 40, bottom - 4, 64, 4, c, ink, "mg").body;
    bottom -= 10;
  }
  if (i.state || (i.detail && f.detail) || (i.mode && f.mode)) {
    const w: Part[] = i.state ? [[stateText(f), "value"], [f.unit && f.online ? " " + f.unit : "", "unit"]] : subParts(f, i).length ? subParts(f, i) : [["", "detail"]];
    const big = !i.icon;
    if (!big && i.state && subline(f, i)) {
      // the detail and the mode small under the state, the icon a little smaller for them
      body += subText(f, i, 72, bottom - 1, 11, 128, { weight: 600, fill: ink.dim, anchor: "middle" });
      bottom -= 14 + dz(partsSize(subParts(f, i), 11), 11) * 0.76;
    }
    const fs = mixLine(72, bottom - 3, w, big ? [40, 32, 26, 20] : [17, 15, 13], 124, { weight: 700, fill: !f.online ? ink.crit : f.stateColour ?? (lit ? c : offInk(f, ink.dim)), anchor: "middle" }, T,
      (z) => z * CAPF.value);
    body += fs.svg;
    bottom -= fs.size + 6;
    if (big && i.state && subline(f, i)) {
      body += subText(f, i, 72, bottom - 2, 12.5, 124, { weight: 500, fill: ink.dim, anchor: "middle" });
      bottom -= 18 + dz(partsSize(subParts(f, i), 12.5), 12.5) * 0.76;
    }
  }
  if (i.icon) {
    const sz = Math.max(26, Math.min(78, bottom - 22));
    const cy = (8 + bottom) / 2;
    if (lit) body += `<circle cx="72" cy="${n(cy)}" r="${n(sz * 0.74)}" fill="${c}" fill-opacity="0.16"/>`;
    if (offLit(f)) body += `<circle cx="72" cy="${n(cy)}" r="${n(sz * 0.74)}" fill="${f.offAccent}" fill-opacity="0.1"/>`;
    body += icon(f.icon, 72 - sz / 2, cy - sz / 2, sz, lit ? c : !f.online ? ink.crit : offInk(f, ink.muted), 1.8);
  }
  body += badges(f, i, ink);
  return doc(body, defs);
}

/** Big value: the state as large as it fits, the name small on top, the detail and the graph under it. */
function bigvalue(f: Face, o: LookOpts): string {
  const ink = DARK, i = o.info, c = f.accent;
  let b = rect(0, 0, 144, 144, 0, "url(#bg)") + frame(ink, f.active ? c : offInk(f, ink.line), f.active || offLit(f) ? 0.7 : 1);
  let x0 = 14;
  if (i.icon) {
    b += icon(f.icon, 13, 13, 20, f.active ? c : offInk(f, ink.dim), 2);
    x0 = 39;
  }
  let nameFoot = 0;
  if (i.name && f.name) {
    const ns = S("name", 13, 18);
    const nl = nameLines(f.name, o.fit, ns, 128 - x0 - (f.hold || !f.online || !f.allowed ? 26 : 0) - (T.name !== 1 && f.badge ? 30 : 0), 650, 1);
    nameFoot = dz(ns, 13) * 0.6;
    b += text(x0, 29 + nameFoot, nl.lines[0]!, { size: nl.size, weight: 650, fill: ink.dim, role: "name" });
  }
  const hasGraph = i.graph && (f.series.length >= 2 || f.level !== null || f.kind === "reading");
  const sub = subline(f, i);
  const vy = hasGraph ? (sub ? 76 : 84) : sub ? 88 : 96;
  if (i.state) b += value(f, 72, vy, 124, [54, 46, 38, 30, 24, 19], f.stateColour ?? (f.active ? c : offInk(f, ink.text)), ink, "middle", 800, room(vy, (i.name && f.name ? 36 : 14) + nameFoot));
  if (sub) b += subText(f, i, 72, vy + 20 + dz(partsSize(subParts(f, i), 13.5), 13.5) * 0.5, 13.5, 126, { weight: 600, fill: f.active ? c : ink.dim, anchor: "middle" });
  let defs = grad("bg", P.panel2, 1, P.bg, 1);
  if (hasGraph) {
    const g = graph(f, i, 14, 110, 116, 22, f.stateColour ?? c, ink, "g");
    b += g.body;
    defs += g.defs;
  } else if (i.room && f.room) b += text(72, 132, fit(f.room, S("room", 12), 124, 500), { size: S("room", 12), weight: 500, fill: ink.muted, anchor: "middle", role: "room" });
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
  b += lit ? `<rect x="3" y="3" width="138" height="138" rx="20" fill="none" stroke="${X.white}" stroke-opacity="0.35" stroke-width="2"/>` : frame(DARK, offInk(f, P.line));
  if (i.icon) {
    b += `<circle cx="36" cy="36" r="23" fill="${lit ? P.bg : P.panel}" fill-opacity="${lit ? 0.16 : 1}" stroke="${lit ? P.bg : offInk(f, P.line)}" stroke-opacity="${lit ? 0.25 : 1}" stroke-width="1.5"/>`;
    b += icon(f.icon, 22, 22, 28, lit ? P.bg : f.online ? offInk(f, P.dim) : P.crit, 2);
  }
  const sub = subline(f, i);
  let y = 86;
  const nb = nameBlock(f, o, 14, 133, 118, ink, 14.5, "start", i.state || sub ? 1 : 2);
  // (1.3) a taller name block lifts the value and the line under it
  const zs = partsSize(subParts(f, i), 13);
  let sy = (i.state ? (sub ? 82 : 88) : 86) + 17 + dz(zs, 13) * 0.6;
  const lift = T === ONE ? 0 : Math.max(0, (sub ? sy : (sub ? 82 : 88)) - (nb.top + 2));
  if (i.state) {
    y = (sub ? 82 : 88) - lift;
    b += value(f, 14, y, 120, [30, 26, 22, 18], lit ? P.bg : f.stateColour ?? offInk(f, P.dim), ink, "start", 800, room(y, i.icon ? 60 : 14));
  }
  sy -= lift;
  if (sub) b += subText(f, i, 14, sy, 13, 120, { weight: 650, fill: lit ? P.panel2 : f.active ? c : P.muted });
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
  } else b += `<rect x="7" y="7" width="130" height="130" rx="22" fill="none" stroke="${f.online ? offInk(f, P.muted) : P.crit}" stroke-opacity="${f.online ? 0.55 : 0.8}" stroke-width="1.6" stroke-dasharray="${f.online ? "0" : "6 5"}"/>`;
  const texts = (i.state ? 1 : 0) + (i.name ? 1 : 0);
  const sz = texts ? 34 : 56;
  const cy = texts ? 42 : 72;
  if (i.icon) {
    if (lit) b += icon(f.icon, 72 - sz / 2, cy - sz / 2, sz, c, 5.5).replace('stroke-width="5.5"', 'stroke-width="5.5" stroke-opacity="0.18"');
    b += icon(f.icon, 72 - sz / 2, cy - sz / 2, sz, lit ? c : offInk(f, P.muted), 1.9);
  }
  let y = i.icon ? 84 : 66;
  if (i.state) {
    const cap = room(y, i.icon ? cy + sz / 2 + 2 : 14);
    if (lit) b += value(f, 72, y, 116, [26, 22, 18, 15], c, ink, "middle", 750, cap).replace(/fill="([^"]+)"/, 'fill="$1" fill-opacity="0.25" stroke="' + c + '" stroke-opacity="0.25" stroke-width="3"');
    b += value(f, 72, y, 116, [26, 22, 18, 15], f.stateColour ?? (lit ? c : offInk(f, P.dim)), ink, "middle", 750, cap);
    y += 18;
  }
  const sub = subline(f, i);
  if (sub) {
    const zs = partsSize(subParts(f, i), 12);
    y += dz(zs, 12) * 0.76;
    b += subText(f, i, 72, y, 12, 116, { weight: 600, fill: lit ? P.text : P.muted, anchor: "middle" });
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
  b += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${offInk(f, P.line)}"${offLit(f) ? ' stroke-opacity="0.45"' : ""} stroke-width="8"/>`;
  const lv = i.graph && f.level !== null ? Math.max(0, Math.min(1, f.level)) : onFill(f, lit);
  if (f.online && lv > 0) b += lv >= 1 ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${c}" stroke-width="8"/>`
    : `<path d="${arcPath(cx, cy, r, 0, 360 * lv)}" fill="none" stroke="${c}" stroke-width="8" stroke-linecap="round"/>`;
  const mk = f.level !== null ? markOf(f, i) : null;
  if (mk !== null) b += notch(cx, cy, r, 360 * mk, 7, X.white, P.bg);
  if (lit) b += `<circle cx="${cx}" cy="${cy}" r="${r - 9}" fill="${c}" fill-opacity="0.1"/>`;
  const st = i.state;
  if (i.icon) {
    const s = st ? 22 : 38;
    b += icon(f.icon, cx - s / 2, st ? cy - 30 : cy - s / 2, s, lit ? c : offInk(f, P.dim), 2);
  }
  if (st) {
    const vy = i.icon ? cy + 10 : cy + 7;
    b += value(f, cx, vy, r * 1.55, named ? [24, 20, 16, 13] : [30, 26, 20, 16], f.stateColour ?? (lit ? P.text : offInk(f, P.dim)), ink, "middle", 750, room(vy, i.icon ? cy - 7 : cy - r + 12));
    const sub = i.detail && f.online ? f.detail : "";
    const ds = S("detail", 10.5, 13);
    if (sub) b += text(cx, cy + (i.icon ? 25 : 24) + dz(ds, 10.5) * 0.5, fit(sub, ds, r * 1.45, 600), { size: ds, weight: 600, fill: lit ? c : P.muted, anchor: "middle", role: "detail" });
  }
  const modeLine = i.mode && f.online ? f.mode : "";
  const ms = S("mode", named ? 11 : 10, named ? 14 : 12);
  if (modeLine && named) b += text(72, cy + r + 15 + dz(ms, 11) * 0.5, fit(modeLine, ms, 124, 700), { size: ms, weight: 700, fill: lit ? c : P.dim, anchor: "middle", role: "mode" });
  else if (modeLine) b += text(cx, cy + r - 8, fit(modeLine, ms, r * 1.2, 700), { size: ms, weight: 700, fill: lit ? c : P.dim, anchor: "middle", role: "mode" });
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
    : `<path d="M 0 0 H 144 V ${band} H 0 Z" fill="${lit ? "url(#band)" : P.panel2}"/>` + `<path d="M 0 ${band} H 144" stroke="${lit ? c : offInk(f, P.line)}" stroke-width="2"/>`;
  if (offLit(f)) b += band >= 144 ? rect(0, 0, 144, 144, 0, f.offAccent!, 'fill-opacity="0.14"') : `<path d="M 0 0 H 144 V ${band} H 0 Z" fill="${f.offAccent}" fill-opacity="0.14"/>`;
  const on = lit ? P.bg : offInk(f, P.dim);
  if (i.icon) b += icon(f.icon, 13, band >= 144 ? 14 : 14, band >= 144 ? 34 : 30, lit ? P.bg : f.online ? offInk(f, P.dim) : P.crit, 2);
  if (i.state) {
    const ink: Ink = lit ? { ...DARK, dim: P.panel2, crit: P.bg } : DARK;
    b += value(f, 131, band >= 144 ? 96 : 56, i.icon ? 80 : 118, band >= 144 ? [40, 32, 26, 20] : [24, 20, 16, 13], f.stateColour && !lit ? f.stateColour : on, ink, "end", 800,
      band >= 144 ? room(96, f.badge ? 36 : 14) : room(56, f.badge ? 34 : 10));
  }
  const sub = subline(f, i);
  let defs = grad("band", c, 1, c, 0.78, 1, 1);
  const ink = DARK;
  if (band < 144) {
    const nb = nameBlock(f, o, 14, (sub || i.graph ? 118 : 132) - (sub ? dz(partsSize(subParts(f, i), 12.5), 12.5) * 0.76 : 0), 118, ink, 15, "start", sub || i.graph ? 1 : 2);
    b += nb.svg;
    if (sub) b += subText(f, i, 14, 135, 12.5, 118, { weight: 600, fill: lit ? c : P.muted });
    else if (i.graph) {
      const g = graph(f, i, 14, 124, 116, 12, c, ink, "g");
      b += g.body;
      defs += g.defs;
    }
  } else if (sub) b += subText(f, i, 131, 118 + dz(partsSize(subParts(f, i), 13), 13) * 0.6, 13, 118, { weight: 600, fill: lit ? P.panel2 : P.muted, anchor: "end" });
  b += frame(ink, lit ? c : offInk(f, P.line), lit || offLit(f) ? 0.5 : 1);
  b += badges(f, i, lit && band >= 144 ? { ...DARK, badge: P.bg } : DARK, band >= 144 ? 13 : 13, lit);
  return doc(b, defs);
}

/** Glass: a frosted pane over a glow of the accent, a bright edge and a sheen across the top. */
function glass(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const oc = lit ? c : offInk(f, c);
  let defs = `<radialGradient id="orb" cx="0.3" cy="0.3" r="0.8"><stop offset="0" stop-color="${oc}" stop-opacity="${lit ? 0.75 : offLit(f) ? 0.4 : 0.18}"/><stop offset="1" stop-color="${oc}" stop-opacity="0"/></radialGradient>`
    + grad("sheen", X.white, 0.16, X.white, 0) + grad("bg", P.panel2, 1, X.night, 1, 1, 1);
  let b = rect(0, 0, 144, 144, 0, "url(#bg)");
  b += `<circle cx="40" cy="40" r="70" fill="url(#orb)"/>`;
  b += rect(8, 8, 128, 128, 22, X.white, `fill-opacity="${lit ? 0.07 : 0.04}" stroke="${X.white}" stroke-opacity="${lit ? 0.3 : 0.14}" stroke-width="1.4"`);
  b += `<path d="M 30 8 H 114 A 22 22 0 0 1 136 30 V 52 C 96 40 52 44 8 60 V 30 A 22 22 0 0 1 30 8 Z" fill="url(#sheen)"/>`;
  if (i.icon) b += icon(f.icon, 20, 20, 30, lit ? X.white : f.online ? offInk(f, P.dim) : P.crit, 2);
  const sub = subline(f, i);
  if (i.state) b += value(f, 128, 58, i.icon ? 70 : 110, [26, 22, 18, 14], f.stateColour ?? (lit ? X.white : offInk(f, P.dim)), ink, "end", 750, room(58, f.badge ? 34 : 14));
  if (sub) b += subText(f, i, 128, 74 + dz(partsSize(subParts(f, i), 12), 12) * 0.5, 12, 108, { weight: 600, fill: lit ? c : P.muted, anchor: "end" });
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
  let b = rect(0, 0, 144, 144, 0, P.bg) + frame(ink, lit ? c : offInk(f, P.line), lit || offLit(f) ? 0.6 : 1);
  if (i.icon) b += icon(f.icon, 14, 14, 20, lit ? c : offInk(f, P.dim), 2.1);
  const wrole: TextRole = i.name && f.name ? "name" : i.room && f.room ? "room" : "value";
  const words = i.name && f.name ? f.name : i.room && f.room ? f.room : i.state ? stateText(f) : "";
  const nl = nameLines(words, o.fit === "cut" ? "cut" : "fit", S(wrole, 25, 30), 124, 800, 3);
  const lines = nl.lines.length > 2 ? nl.lines.slice(0, 2) : nl.lines;
  let y = 74 - (lines.length - 1) * nl.size * 0.55;
  for (const l of lines) {
    b += text(72, y, l, { size: nl.size, weight: 800, fill: lit ? P.text : P.dim, anchor: "middle", spacing: -0.3, role: wrole });
    y += nl.size * 1.08;
  }
  const lv = i.graph && f.level !== null ? Math.max(0, Math.min(1, f.level)) : onFill(f, lit);
  b += rect(36, 102, 72, 5, 2.5, offInk(f, P.line), offLit(f) ? 'fill-opacity="0.5"' : "");
  if (lv > 0 && f.online) b += rect(36, 102, Math.max(5, 72 * lv), 5, 2.5, c);
  const sub = subline(f, i);
  if (i.state) {
    const st: Part[] = [[stateText(f), "value"], [f.unit && f.online ? " " + f.unit : "", "unit"]];
    const zs = sub ? partsSize(subParts(f, i), 11) : 11;
    const sy = 137 + Math.min(4, dz(zs, 11) * 0.3);
    b += mixLine(72, (sub ? 122 : 127) + (sub ? dz(zs, 11) * 0.6 : 0), st, [13], 124, { weight: 700, fill: !f.online ? P.crit : f.stateColour ?? (lit ? c : offInk(f, P.muted)), anchor: "middle" }, T,
      (z) => z * 1.5).svg;
    if (sub) b += subText(f, i, 72, sy, 11, 124, { weight: 600, fill: P.muted, anchor: "middle" });
  } else if (sub) b += subText(f, i, 72, 127, 12.5, 124, { weight: 600, fill: P.muted, anchor: "middle" });
  b += badges(f, i, ink);
  return doc(b);
}

/** Status dot: a lamp at the top left - lit, hollow or red - with the state beside it in clean type. */
function dot(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.accent;
  const lit = f.active && f.online;
  const lamp = !f.online ? P.crit : f.stateColour ?? (lit ? c : offInk(f, P.muted));
  let b = rect(0, 0, 144, 144, 0, P.panel) + frame(ink, P.line, 1, 1.5, 18);
  if (lit || !f.online) b += `<circle cx="25" cy="27" r="14" fill="${lamp}" fill-opacity="0.18"/>`;
  b += lit || !f.online || f.stateColour ? `<circle cx="25" cy="27" r="8" fill="${lamp}"/>` : `<circle cx="25" cy="27" r="7" fill="none" stroke="${lamp}" stroke-width="2.4"/>`;
  const nb = (!f.allowed ? 1 : 0) + (!f.online ? 1 : 0) + (f.hold ? 1 : 0) + (i.battery && f.battery !== null && f.battery <= 20 ? 1 : 0);
  const vz = i.state ? grow(22, T.value, 28) : 22;
  if (i.state) b += value(f, 42, 35 + dz(vz, 22) * 0.6, 86 - nb * 22 - ((T.value !== 1 || T.unit !== 1) && f.badge ? 30 : 0), [22, 19, 16, 13], lit || !f.online ? P.text : f.stateColour ?? P.dim, ink, "start", 700, 28);
  const det = i.detail && f.online ? f.detail : "", md = i.mode && f.online ? f.mode : "";
  const dsz = S("detail", 12.5, 16), msz = S("mode", 11.5, 15);
  const dy = 53 + dz(vz, 22) * 0.6 + dz(dsz, 12.5) * 0.6;
  if (det) b += text(42, dy, fit(det, dsz, i.icon ? 56 : 88, 600), { size: dsz, weight: 600, fill: lit ? c : P.muted, role: "detail" });
  if (md) b += text(42, det ? dy + 15 + dz(msz, 11.5) * 0.8 : 53 + dz(vz, 22) * 0.6 + dz(msz, 11.5) * 0.6, fit(md, msz, i.icon ? 56 : 88, 700), { size: msz, weight: 700, fill: P.dim, role: "mode" });
  if (i.icon) b += icon(f.icon, 100, 44, 30, lit ? c : offInk(f, P.muted), 1.9);
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
  b += frame(ink, lit ? c : offInk(f, X.paperLine), 1, 2);
  if (i.icon) {
    b += rect(14, 14, 44, 44, 13, lit ? c : offInk(f, X.white), `fill-opacity="${lit ? 0.2 : offLit(f) ? 0.12 : 1}" stroke="${lit ? c : offInk(f, X.paperLine)}" stroke-width="1.5"`);
    b += icon(f.icon, 22, 22, 28, lit ? X.ink : f.online ? offInk(f, X.inkDim) : X.inkCrit, 2);
  }
  const sub = subline(f, i);
  const nb = nameBlock(f, o, 14, 133, 118, ink, 14.5, "start", i.state || sub ? 1 : 2);
  // (1.3) a taller name block lifts the value and the line under it
  const sy0 = 99 + dz(partsSize(subParts(f, i), 13), 13) * 0.6;
  const lift = T === ONE ? 0 : Math.max(0, (sub ? sy0 : sub ? 82 : 88) - (nb.top + 2));
  if (i.state) b += value(f, 14, (sub ? 82 : 88) - lift, 118, [28, 24, 20, 16], f.stateColour ? f.stateColour : lit ? X.ink : X.inkDim, ink, "start", 800, room((sub ? 82 : 88) - lift, i.icon ? 61 : 14));
  if (sub) b += subText(f, i, 14, sy0 - lift, 13, 118, { weight: 650, fill: lit ? X.ink : X.inkMuted });
  if (i.graph && (f.series.length >= 2 || (f.level !== null && f.kind !== "control"))) {
    const g = graph(f, i, 66, 22, 64, 26, c, ink, "g");
    b += g.body;
    defs += g.defs;
  }
  b += nb.svg;
  b += badges(f, i, ink, 13, true);
  return doc(b, defs);
}

/** High contrast: black and white with thick lines; lit, the key turns white with black words. */
function contrast(f: Face, o: LookOpts): string {
  const i = o.info;
  const lit = f.active && f.online;
  const ink: Ink = lit ? { ...HC, bg: X.white, text: X.black, dim: X.black, muted: X.black, line: X.black, badge: X.white, crit: P.bg } : HC;
  let b = rect(0, 0, 144, 144, 0, lit ? X.white : X.black);
  b += `<rect x="4" y="4" width="136" height="136" rx="16" fill="none" stroke="${!f.online ? X.hcRed : lit ? X.black : offInk(f, X.white)}" stroke-width="5"${f.online ? "" : ' stroke-dasharray="10 6"'}/>`;
  if (i.icon) b += icon(f.icon, 16, 16, 34, lit ? X.black : offInk(f, X.white), 2.8);
  const sub = subline(f, i);
  if (i.state) {
    const t = stateText(f).toUpperCase();
    const vy = sub ? 86 : 92;
    const top = i.icon ? 54 : 14;
    b += mixLine(16, vy, [[t, "value"], [f.unit && f.online ? " " + f.unit : "", "unit"]], [30, 26, 22, 18, 15], 116,
      { weight: 900, fill: !f.online ? X.hcRed : lit ? X.black : f.stateColour ? X.hcYellow : offInk(f, X.white) }, T, () => room(vy, top)).svg;
  }
  if (sub) b += subText(f, i, 16, 104 + dz(partsSize(subParts(f, i), 13.5), 13.5) * 0.6, 13.5, 114, { weight: 800, fill: lit ? X.black : X.hcYellow });
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
function caption(f: Face, o: LookOpts, x: number, y: number, maxW: number, size: number, fill: string, anchor: "start" | "middle" | "end" = "middle", weight = 650, opacity?: number): string {
  const i = o.info;
  const role: TextRole = i.name && f.name ? "name" : "room";
  const t = i.name && f.name ? f.name : i.room && f.room ? f.room : "";
  if (!t) return "";
  const nl = nameLines(t, o.fit, S(role, size), maxW, weight, 1);
  return text(x, y, nl.lines[0]!, { size: nl.size, weight, fill, anchor, opacity, role });
}

/** (1.3) How much the caption grew (what is laid out above it moves up as much). */
function capLift(f: Face, o: LookOpts, size: number): number {
  const i = o.info;
  const role: TextRole = i.name && f.name ? "name" : "room";
  return i.name && f.name || i.room && f.room ? dz(S(role, size), size) * 0.76 : 0;
}

/** (1.3) A tag: its words, and its pieces (a detail and / or a mode) for their sizes. */
interface Tag { s: string; parts: Part[] }

function mkTag(d: string, m: string): Tag | "" {
  const parts = pairParts(d, m);
  return parts.length ? { s: parts.map((p) => p[0]).join(""), parts } : "";
}

/** What is essential besides the state: a thermostat's target and mode, a blind on its way. */
function tag(f: Face, i: Info): Tag | "" {
  if (!f.online || !i.state) return "";
  if (f.kind === "thermostat") {
    // "→ 22.0 °C" said as "→ 22.0°": the unit is already by the big value
    const d = i.detail ? f.detail.replace(/\s*°[CF]$/, "°") : "";
    return mkTag(d, i.mode ? f.mode : "");
  }
  if (f.kind === "blinds") return mkTag(i.detail ? f.detail : "", "");
  if (TAGGED.has(f.kind)) return i.detail ? mkTag(f.detail, "") : mkTag("", i.mode ? f.mode : "");
  return "";
}

/** The tag's size as drawn (its biggest piece), for what is laid out under or round it. */
function tagSize(t: Tag | "", size: number): number {
  return t ? partsSize(t.parts, size) : size;
}

/** (1.3) How much taller the tag grew, for what sits above it. */
function tagLift(t: Tag | "", size: number): number {
  return t ? dz(tagSize(t, size), size) * 0.76 : 0;
}

/** The tag in one line, a little smaller before it is cut. */
function tagText(x: number, y: number, t: Tag, maxW: number, size: number, fill: string, anchor: "start" | "middle" | "end" = "start", opacity?: number): string {
  return mixLine(x, y, t.parts, [size, size * 0.9, size * 0.8], maxW, { weight: 700, fill, anchor, opacity }, T, (z) => z * CAPF.detail).svg;
}

interface Big {
  words: string;
  unit: string;
  size: number;
  /** (1.3) The unit's size, and what the words are (the value; with the state hidden, the detail or the mode). */
  usize: number;
  role: TextRole;
  /** (1.3) The detail and the mode as their own pieces, when they differ in size (the state hidden). */
  svgParts?: Part[];
  /** (tests) the roles one text holds, when it holds several */
  multi?: string;
  cands?: number[];
  maxW?: number;
}

/**
 * The big words: the state and its unit (with the state hidden, the detail and the mode, smaller). Size 0: nothing to say.
 * (1.3) `band`: the sizes the layout has room for, of those the value's factor makes (the base sizes are what the unit goes by).
 */
function bigWords(f: Face, i: Info, sizes: number[], maxW: number, weight = 800, upper = false, band?: (s: number) => boolean, cap?: number | null, grown?: (s: number) => boolean): Big {
  const within = (l: number[]) => {
    if (!band) return l;
    const ok = l.filter(band);
    return ok.length ? ok : [l[l.length - 1]!];
  };
  const base = within(sizes);
  if (!i.state) {
    const parts = subParts(f, i);
    if (!parts.length) return { words: "", unit: "", size: 0, usize: 0, role: "detail" };
    const s = parts.map((p) => p[0]).join("");
    const role = parts[0]![1];
    const cands = base.map((a) => Math.round(a * 0.55));
    if (parts.every((p) => T[p[1]] === T[role])) {
      // as big as the value's own sizes, at most
      const t = fitSizeK(s, cands, T[role], maxW, weight, (z) => z / 0.55);
      return { words: t.text, unit: "", size: t.size, usize: 0, role, ...(parts.length > 1 ? { multi: parts.map((p) => p[1]).join(" ") } : {}) };
    }
    return { words: s, unit: "", size: partsSize(parts, cands[0]!), usize: 0, role, svgParts: parts, cands, maxW };
  }
  const v = upper ? stateText(f).toUpperCase() : stateText(f);
  const unit = f.unit && f.online ? f.unit : "";
  const uk = T.unit === 1 ? 1 : S("unit", 14) / 14;
  const room0 = unit ? maxW - Math.min(44, textWidth(unit, Math.max(11, base[0]! * 0.42), 650) + 4) : maxW;
  // bigger, as far as the place has room - and never smaller than at 100 %
  const b0 = T.value > 1 && grown ? fitSize(v, base, room0, weight).size : 0;
  const scaled0 = T.value === 1 ? base : within(SS("value", sizes, cap)).filter((s) => !grown || grown(s) || s <= b0);
  const scaled = T.value < 1 && scaled0.length ? smallerThan(scaled0, fitSize(v, base, room0, weight).size * T.value) : scaled0;
  if (T.value === 1 && uk === 1) {
    const vf = fitSize(v, base, room0, weight);
    return { words: vf.text, unit, size: vf.size, usize: Math.max(11, vf.size * 0.42), role: "value" };
  }
  const f0 = fitSize(v, base, room0, weight);
  const uz0 = Math.max(11, f0.size * 0.42);
  const r = fitWithUnit(v, scaled.length ? scaled : base, unit ? fit(unit, 14 * uk, 44 * uk, 650) : "", uz0, uz0 * uk, maxW, weight, 650, 3);
  // never smaller than at 100 % for being asked to be bigger: as at 100 %, then
  if (T.value > 1 && r.size < f0.size) return { words: f0.text, unit, size: f0.size, usize: uz0, role: "value" };
  return { words: r.text, unit, size: r.size, usize: r.usize, role: "value" };
}

/** Draws the big words: the unit a smaller tspan, offline in red. */
function drawBig(b: Big, f: Face, x: number, y: number, fill: string, unitFill: string, anchor: "start" | "middle" | "end", extra = "", spacing = -0.6): string {
  if (!b.size) return "";
  if (b.svgParts) {
    const t = mixLine(x, y, b.svgParts, b.cands!, b.maxW!, { weight: 800, fill: f.online ? fill : P.crit, anchor, spacing }, T, (z) => z / 0.55).svg;
    return extra ? t.replace("<text ", "<text " + extra + " ") : t;
  }
  const uk = T.unit === 1 ? 1 : S("unit", 14) / 14;
  const u = b.unit ? `<tspan dx="3" font-size="${n(b.usize)}" font-weight="650" fill="${unitFill}"${roleAttr("unit")}>${escText(fit(b.unit, 14 * uk, 44 * uk, 650))}</tspan>` : "";
  let t = text(x, y, b.words, { size: b.size, weight: 800, fill: f.online ? fill : P.crit, anchor, spacing, role: b.role });
  if (b.multi && roleAttr(b.role)) t = t.replace(roleAttr(b.role), ` data-role="${b.multi}"`);
  return (extra ? t.replace("<text ", "<text " + extra + " ") : t).replace(/<\/text>$/, u + "</text>");
}

/**
 * The level a look may draw: the item's own, in its true range (a brightness, a position, a battery,
 * a thermostat's temperature) - (1.3) never where a reading stands between the lowest and highest
 * of its history, which drew a random-looking level. None: the look shows on / off, or nothing.
 */
function levelOf(f: Face, i: Info): number | null {
  if (!i.graph || !f.online || f.level === null || !Number.isFinite(f.level)) return null;
  return Math.max(0, Math.min(1, f.level));
}

/**
 * (1.3) How far a look fills with no level: whole when on (a switch, a mode word) - but never under
 * a number, where a whole ring or tube would read as its maximum (1.84 kW drawn as a full gauge).
 */
function onFill(f: Face, on: boolean): number {
  return on && !/^[-+−]?\d/.test(f.state) ? 1 : 0;
}

/** (1.3) The target's place on the level's scale, to mark on an arc - when the level and the target are shown. */
function markOf(f: Face, i: Info): number | null {
  if (!i.graph || !i.target || !f.online || f.mark === null || f.mark === undefined || !Number.isFinite(f.mark)) return null;
  return Math.max(0, Math.min(1, f.mark));
}

/** (1.3) A notch across an arc at angle `a` (degrees, 0 at the top): where the target stands. */
function notch(cx: number, cy: number, r: number, a: number, w: number, colour: string, bg: string): string {
  const rad = ((a - 90) * Math.PI) / 180;
  const c = Math.cos(rad), s = Math.sin(rad);
  const d = `M ${n(cx + (r - w) * c)} ${n(cy + (r - w) * s)} L ${n(cx + (r + w) * c)} ${n(cy + (r + w) * s)}`;
  return `<path d="${d}" stroke="${bg}" stroke-width="5" stroke-linecap="round"/><path d="${d}" stroke="${colour}" stroke-width="2.4" stroke-linecap="round" data-mark="${n(a)}"/>`;
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
  if (iconAlone(f, o)) b += icon(f.icon, 32, 32, 80, lit ? c : offInk(f, P.muted), 2);
  else if (i.icon) b += icon(f.icon, 14, 14, 22, lit ? c : f.online ? offInk(f, P.muted) : P.crit, 2.2);
  const lv = levelOf(f, i);
  if (i.graph && f.online && f.series.length >= 2) {
    const g = graph(f, { ...i, scale: false }, -2, 58, 148, 56, glow, ink, "g");
    b += `<g opacity="${lit ? 0.5 : 0.32}">${g.body}</g>`;
    defs += g.defs;
  } else if (lv !== null) b += rect(0, 140, 144, 4, 0, P.line) + rect(0, 140, Math.max(4, 144 * lv), 4, 0, lit ? c : offInk(f, P.muted));
  const bottom = (cap ? 114 - capLift(f, o, 14) : 136) - (tg ? 18 + tagLift(tg, 14) : 0);
  const top = i.icon ? 40 : 12;
  const big = bigWords(f, i, [80, 72, 64, 56, 48, 42, 36, 30, 26], 130, 800, false, undefined, null, (z) => z * 0.72 <= bottom - top);
  const vy = (top + bottom) / 2 + big.size * 0.36;
  b += drawBig(big, f, 72, vy, f.stateColour ?? (lit ? c : offInk(f, P.dim)), lit ? P.text : P.muted, "middle");
  if (tg) b += tagText(72, bottom + 14 + tagLift(tg, 14), tg, 128, 14, lit ? c : P.dim, "middle");
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
  if (iconAlone(f, o)) return doc(b + icon(f.icon, 36, 36, 72, lit ? c : offInk(f, P.muted), 2) + badges(f, i, ink, 12, true), defs);
  const cap = caption(f, o, 72, 134, 124, 14, P.dim);
  const tg = tag(f, i);
  const lv = levelOf(f, i);
  const below = tg ? 22 + tagLift(tg, 13) : lv !== null ? 16 : 0;
  const room = (cap ? 116 - capLift(f, o, 14) : 136) - 10;
  // (1.3) bigger words make the pill taller, as far as the key has room
  const big0 = T.value === 1 ? null : bigWords(f, i, [36, 32, 28, 24, 20, 17], 104);
  const grownBy = big0 && big0.size > 36 ? Math.min(big0.size - 36, Math.max(0, room - (i.icon ? 32 : 0) - 48 - below - 10) / 0.72) : 0;
  const big = bigWords(f, i, [36, 32, 28, 24, 20, 17], 104, 800, false, undefined, null, (z) => z <= 36 + grownBy);
  const tight = (i.icon ? 40 : 0) + 56 + (big.size > 36 ? (big.size - 36) * 0.72 : 0) + below > room;
  const ph = (tight ? 48 : 56) + (big.size > 36 ? (big.size - 36) * 0.72 : 0);
  const pillH = big.size ? ph : 0;
  const iconH = i.icon ? (tight ? 32 : 40) : 0;
  const is = big.size ? (tight ? 24 : 30) : 44;
  const top = 10 + Math.max(0, (room - iconH - pillH - below) / 2);
  const py = top + iconH;
  if (i.icon) b += icon(f.icon, 72 - is / 2, big.size ? py - is - 6 : top + 4, is, lit ? c : f.online ? offInk(f, P.dim) : P.crit, 2.2);
  if (big.size) {
    if (lit) {
      b += `<rect x="10" y="${n(py + 4)}" width="124" height="${ph}" rx="${ph / 2}" fill="${base}" fill-opacity="0.25"/>`;
      b += `<rect x="10" y="${n(py)}" width="124" height="${ph}" rx="${ph / 2}" fill="url(#pill)"/>`;
      b += `<rect x="20" y="${n(py + 3)}" width="104" height="${ph / 2 - 4}" rx="${(ph / 2 - 4) / 2}" fill="url(#sheen)"/>`;
    } else b += `<rect x="11" y="${n(py + 1)}" width="122" height="${ph - 2}" rx="${(ph - 2) / 2}" fill="${P.panel}" stroke="${f.online ? offInk(f, P.line) : P.crit}" stroke-width="2.5"${f.online ? "" : ' stroke-dasharray="7 5"'}/>`;
    b += drawBig(big, f, 72, py + ph / 2 + big.size * 0.35, lit ? P.bg : f.stateColour ?? offInk(f, P.dim), lit ? P.panel2 : P.muted, "middle", "", -0.4);
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
  const lv = levelOf(f, i);
  const ringR = lv !== null ? 7 : 0;
  const room = (cap ? 120 - capLift(f, o, 13) : 138) - 8;
  const tagH = tg ? 16 + tagLift(tg, 12.5) : 0;
  // (1.3) the words no bigger than leaves the sphere its smallest
  const big = bigWords(f, i, [32, 28, 24, 20, 16], 124, 800, false, undefined, 46, (z) => z + 6 + tagH <= room - 2 * ringR - 50);
  const below = (big.size ? big.size + 6 : 0) + tagH;
  const r = Math.max(22, Math.min(46, (room - below - 2 * ringR - 6) / 2));
  const cy = 8 + ringR + r + Math.max(0, (room - below - 2 * ringR - 2 * r) / 2);
  const defs = radial("halo", [[0, base, 0.5], [0.55, base, 0.14], [1, base, 0]])
    + (lit ? radial("ball", [[0, X.white, 1], [0.3, base, 1], [1, base, 0.55]], 0.36, 0.3, 0.75)
      : radial("ball", [[0, P.panel2, 1], [0.7, P.panel, 1], [1, X.night, 1]], 0.36, 0.3, 0.8))
    + grad("spec", X.white, 0.55, X.white, 0);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) b += `<circle cx="72" cy="${n(cy)}" r="${n(r * 1.75)}" fill="url(#halo)"/>`;
  b += `<circle cx="72" cy="${n(cy)}" r="${n(r)}" fill="url(#ball)"${lit ? "" : ` stroke="${f.online ? offInk(f, P.line) : P.crit}" stroke-width="2"${f.online ? "" : ' stroke-dasharray="5 4"'}`}/>`;
  b += `<ellipse cx="${n(72 - r * 0.22)}" cy="${n(cy - r * 0.55)}" rx="${n(r * 0.5)}" ry="${n(r * 0.26)}" fill="url(#spec)"${lit ? "" : ' opacity="0.35"'}/>`;
  if (lv !== null) {
    b += `<circle cx="72" cy="${n(cy)}" r="${n(r + ringR)}" fill="none" stroke="${P.line}" stroke-width="3.5"/>`;
    if (lv > 0) b += `<path d="${arcPath(72, cy, r + ringR, 0, 360 * lv)}" fill="none" stroke="${lit ? base : P.muted}" stroke-width="3.5" stroke-linecap="round"/>`;
    const mk = markOf(f, i);
    if (mk !== null) b += notch(72, cy, r + ringR, 360 * mk, 5, X.white, X.night);
  }
  if (i.icon) {
    const s = r * 1.05;
    b += icon(f.icon, 72 - s / 2, cy - s / 2, s, lit ? P.bg : f.online ? offInk(f, P.muted) : P.crit, 2.3);
  }
  let y = cy + r + ringR;
  if (big.size) {
    y += big.size + 4;
    b += drawBig(big, f, 72, y, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "middle");
  }
  if (tg) b += tagText(72, y + 16 + tagLift(tg, 12.5), tg, 124, 12.5, lit ? base : P.dim, "middle");
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
    b += lit ? rect(28, 28, 88, 88, 26, "url(#tile)") : rect(28, 28, 88, 88, 26, P.panel2, `stroke="${f.online ? offInk(f, P.line) : P.crit}" stroke-width="2"${dash}`);
    b += icon(f.icon, 44, 44, 56, lit ? P.bg : f.online ? offInk(f, P.dim) : P.crit, 2.2);
    return doc(b + badges(f, i, ink, 12, true), defs);
  }
  const cap = caption(f, o, 14, 134, 118, 14, P.dim, "start");
  const tg = tag(f, i);
  const lv = levelOf(f, i);
  const t = cap && tg ? 54 : cap || tg ? 62 : 68;
  const by0 = (cap ? 114 - capLift(f, o, 14) : 132) - (tg ? 18 + tagLift(tg, 13) : 0);
  const big = bigWords(f, i, [42, 36, 30, 26, 22, 18], 118, 800, false, undefined, null, (z) => z * 0.72 <= by0 - (i.icon || lv !== null ? 12 + t + 4 : 12));
  if (i.icon) {
    b += lit ? rect(14, 12, t, t, t * 0.29, "url(#tile)") + rect(19, 14, t - 10, t * 0.4, t * 0.2, "url(#sheen)")
      : rect(14, 12, t, t, t * 0.29, P.panel2, `stroke="${f.online ? offInk(f, P.line) : P.crit}" stroke-width="2"${dash}`);
    const s = t * 0.58;
    b += icon(f.icon, 14 + (t - s) / 2, 12 + (t - s) / 2, s, lit ? P.bg : f.online ? offInk(f, P.dim) : P.crit, 2.3);
  }
  if (lv !== null) {
    // the level: a slim upright bar beside the tile, or a bar across the top without one
    const h = Math.max(6, t * lv);
    b += i.icon ? rect(14 + t + 9, 12, 6, t, 3, P.line) + rect(14 + t + 9, 12 + t - h, 6, h, 3, lit ? base : P.muted)
      : rect(14, 18, 116, 6, 3, P.line) + rect(14, 18, Math.max(6, 116 * lv), 6, 3, lit ? base : P.muted);
  }
  const by = by0;
  b += drawBig(big, f, 12, by, f.stateColour ?? (lit ? P.text : P.dim), P.muted, "start");
  if (tg) b += tagText(14, by + 18 + tagLift(tg, 13), tg, 118, 13, lit ? base : P.dim);
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
  const lv = levelOf(f, i) ?? onFill(f, lit);
  if (f.online && lv > 0.005) {
    const end = a0 + (a1 - a0) * lv;
    b += `<path d="${arcPath(cx, cy, r, a0, end)}" fill="none" stroke="${lit ? "url(#arc)" : offInk(f, P.muted)}" stroke-width="12" stroke-linecap="round"/>`;
    const rad = ((end - 90) * Math.PI) / 180;
    b += `<circle cx="${n(cx + r * Math.cos(rad))}" cy="${n(cy + r * Math.sin(rad))}" r="3.6" fill="${X.white}" fill-opacity="${lit ? 0.95 : 0.5}"/>`;
  }
  const mk = markOf(f, i);
  if (mk !== null) b += notch(cx, cy, r, a0 + (a1 - a0) * mk, 9, X.white, X.night);
  const tg = tag(f, i);
  const big = bigWords(f, i, [40, 36, 32, 28, 24, 20], 86, 800, false, undefined, null, (z) => z * 0.72 <= (i.icon ? 88 - 60 : 82 - 26) + 6);
  if (!big.size && i.icon) b += icon(f.icon, cx - 22, cy - 22, 44, lit ? base : f.online ? offInk(f, P.muted) : P.crit, 2.1);
  else {
    if (i.icon) b += icon(f.icon, cx - 11, 36, 22, lit ? base : f.online ? offInk(f, P.muted) : P.crit, 2.2);
    b += drawBig(big, f, cx, i.icon ? 88 : 82, f.stateColour ?? (lit ? P.text : offInk(f, P.dim)), P.muted, "middle");
  }
  // the target and the mode in the gap under the arc, the name below them
  if (tg) b += tagText(cx, 125 - capLift(f, o, 12) * (tg ? 1 : 0), tg, 120, 13, lit ? base : P.dim, "middle");
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
  if (iconAlone(f, o)) return doc(b + icon(f.icon, 36, 36, 72, lit ? c : offInk(f, P.muted), 2) + badges(f, i, ink), defs);
  if (i.icon) b += icon(f.icon, 13, 12, 22, lit ? c : f.online ? offInk(f, P.muted) : P.crit, 2.2);
  const cap = caption(f, o, 72, 136, 124, 13.5, P.dim);
  const foot = cap ? 118 - capLift(f, o, 13.5) : 132;
  // the bars: the recent values, else the level, else none
  const v = f.series.filter((a) => Number.isFinite(a)).slice(-9);
  const lv = levelOf(f, i);
  let cols: { h: number; on: boolean; last: boolean }[] = [];
  if (i.graph && f.online && v.length >= 2) {
    // (1.3) on the same honest scale as the sparklines: a flat series stands as flat columns
    const { lo, hi } = seriesScale(v, f.scale ?? { unit: f.unit });
    cols = v.map((a, k) => ({ h: Math.max(0, Math.min(1, (a - lo) / (hi - lo))), on: true, last: k === v.length - 1 }));
  } else if (lv !== null) {
    const k = lv <= 0 ? 0 : Math.max(1, Math.round(lv * 6));
    cols = [0, 1, 2, 3, 4, 5].map((j) => ({ h: (j + 1) / 6, on: j < k, last: false }));
  }
  const tg = tag(f, i);
  const has = cols.length > 0;
  const barH = has ? (tg ? 24 : 30) : 0;
  const vy = has ? foot - barH - (tg ? 30 + tagLift(tg, 13) : 12) : foot - (tg ? 30 + tagLift(tg, 13) : 22) + (cap ? 0 : -6);
  const big = bigWords(f, i, has ? [48, 44, 38, 32, 26, 22] : [60, 54, 48, 42, 36, 30, 24], 124, 800, false, undefined, null, (z) => z * 0.72 <= vy - (i.icon ? 38 : 12));
  b += drawBig(big, f, 72, vy, f.stateColour ?? (lit ? P.text : offInk(f, P.dim)), P.muted, "middle");
  if (tg) b += tagText(72, vy + 18 + tagLift(tg, 13), tg, 124, 13, lit ? c : P.dim, "middle");
  if (has) {
    const top = foot - barH, gap = cols.length > 6 ? 4 : 6;
    const w = (116 - gap * (cols.length - 1)) / cols.length;
    cols.forEach((col, k) => {
      const h = 5 + (barH - 5) * col.h;
      const x = 14 + k * (w + gap);
      b += rect(x, top, w, barH, Math.min(4, w / 3), P.panel2);
      if (col.on) b += rect(x, foot - h, w, h, Math.min(4, w / 3), lit || col.last ? base : offInk(f, P.muted), col.last || lv !== null || v.length < 2 ? "" : 'fill-opacity="0.55"');
    });
  } else if (!tg && big.size && f.online && i.graph) {
    // nothing to measure: one fat bar says on or off
    b += rect(52, vy + 12, 40, 7, 3.5, lit ? base : offInk(f, P.line));
  }
  b += cap;
  b += badges(f, i, ink, 11);
  return doc(b, defs);
}

/** Wave: the key fills with the accent like water - to the level, or (1.3) to the brim when on with no level - big white words over it. */
function wave(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK, c = f.online ? f.accent : P.crit;
  const lit = f.active && f.online;
  const base = f.stateColour && lit ? f.stateColour : c;
  const lv = !f.online ? 0 : levelOf(f, i) ?? onFill(f, lit);
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
    b += `<path d="${w(0, 0)}" fill="${lit ? "url(#water)" : calm ?? offInk(f, P.line)}"${!lit && calm ? ' fill-opacity="0.2"' : !calm && offLit(f) ? ' fill-opacity="0.35"' : ""}/>`;
  }
  const cap = caption(f, o, 72, 134, 124, 14, lit ? X.white : P.dim, "middle", 700, lit ? 0.92 : undefined);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 36, 22, 72, lit ? X.white : offInk(f, P.muted), 2);
  else if (i.icon) b += icon(f.icon, 14, 14, 24, lit && lv > 0.82 ? X.white : lit ? c : f.online ? offInk(f, P.muted) : P.crit, 2.2);
  const vy = (tg ? 76 : 84) + (cap ? 0 : 6) - (tg ? tagLift(tg, 13.5) : 0) - capLift(f, o, 14);
  const big = bigWords(f, i, [54, 48, 42, 36, 30, 24], 124, 800, false, undefined, null, (z) => z * 0.72 <= vy - (i.icon ? 42 : 12));
  if (big.size && lit) b += drawBig(big, f, 73.5, vy + 2, X.night, X.night, "middle", 'fill-opacity="0.3"');
  b += drawBig(big, f, 72, vy, lit ? X.white : f.stateColour ?? offInk(f, P.dim), lit ? X.white : P.muted, "middle");
  if (tg) b += tagText(72, vy + 21 + tagLift(tg, 13.5), tg, 124, 13.5, lit ? X.white : P.dim, "middle");
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
  defs += radial("a1", [[0, X.white, lit ? 0.4 : 0.06], [1, X.white, 0]]) + radial("a2", [[0, lit ? X.night : offInk(f, base), lit ? 0.42 : 0.24], [1, lit ? X.night : offInk(f, base), 0]]);
  let b = rect(0, 0, 144, 144, 0, "url(#sky)");
  b += `<ellipse cx="26" cy="16" rx="92" ry="56" fill="url(#a1)"/><ellipse cx="130" cy="140" rx="96" ry="72" fill="url(#a2)"/>`;
  const cap = caption(f, o, 72, 132, 124, 14.5, lit ? X.white : P.dim, "middle", 700, lit ? 0.92 : undefined);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 36, 36, 72, lit ? X.white : offInk(f, P.muted), 2);
  else if (i.icon) b += icon(f.icon, 14, 14, 26, lit ? X.white : f.online ? offInk(f, P.muted) : P.crit, 2.2);
  const lv = levelOf(f, i);
  const spark = i.graph && f.online && f.series.length >= 2 && !tg;
  const vy = (tg || spark ? 80 : 88) + (cap ? 0 : 8) - (tg ? tagLift(tg, 13.5) : 0) - capLift(f, o, 14.5);
  const big = bigWords(f, i, [54, 48, 42, 36, 30, 24], 126, 800, false, undefined, null, (z) => z * 0.72 <= vy - (i.icon ? 44 : 12));
  b += drawBig(big, f, 72, vy, lit ? X.white : f.stateColour ?? offInk(f, P.dim), lit ? X.white : P.muted, "middle");
  if (tg) b += tagText(72, vy + 20 + tagLift(tg, 13.5), tg, 124, 13.5, lit ? X.white : P.dim, "middle", lit ? 0.92 : undefined);
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
    b += `<rect ${box} fill="none" stroke="${f.online ? offInk(f, P.line) : P.crit}" stroke-width="3"${f.online ? "" : ' stroke-dasharray="8 6"'}/>`;
    if (lv !== null && lv > 0) b += `<rect ${box} fill="none" stroke="${offInk(f, P.muted)}" stroke-width="3" stroke-dasharray="${n(Math.max(1, per * lv))} ${n(per)}"/>`;
  }
  const cap = caption(f, o, 72, 118, 104, 14, lit ? P.text : P.dim);
  const tg = tag(f, i);
  if (iconAlone(f, o)) b += icon(f.icon, 38, 38, 68, lit ? base : offInk(f, P.muted), 2);
  else if (i.icon) b += icon(f.icon, 60, 22, 24, lit ? base : f.online ? offInk(f, P.muted) : P.crit, 2.2);
  const top = i.icon ? 48 : 20, bottom = (cap ? 100 - capLift(f, o, 14) : 124) - (tg ? 16 + tagLift(tg, 12.5) : 0);
  const big = bigWords(f, i, [46, 40, 34, 28, 24, 20], 106, 800, false, undefined, null, (z) => z * 0.72 <= bottom - top);
  const vy = (top + bottom) / 2 + big.size * 0.36;
  b += drawBig(big, f, 72, vy, f.stateColour ?? (lit ? P.text : offInk(f, P.dim)), P.muted, "middle");
  if (tg) b += tagText(72, bottom + 12 + tagLift(tg, 12.5), tg, 104, 12.5, lit ? base : P.dim, "middle");
  b += cap;
  b += badges(f, i, ink, 13, true);
  return doc(b);
}

/** Mono: one colour only - a giant icon and the state in spaced capitals; lit, the key is tinted with it. */
function mono(f: Face, o: LookOpts): string {
  const i = o.info, ink = DARK;
  const lit = f.active && f.online;
  const m = !f.online ? P.crit : f.stateColour ?? (lit ? f.accent : offInk(f, P.muted));
  const defs = radial("tint", [[0, m, 0.3], [1, m, 0]], 0.5, 0.36, 0.6);
  let b = rect(0, 0, 144, 144, 0, X.night);
  if (lit) b += rect(0, 0, 144, 144, 0, m, 'fill-opacity="0.1"') + `<rect width="144" height="144" fill="url(#tint)"/>`;
  const cap = caption(f, o, 72, 134, 124, 12.5, m, "middle", 650, lit ? 0.75 : 0.85);
  const tg = tag(f, i);
  const big = bigWords(f, i, [30, 26, 22, 18, 15], 124, 800, true, undefined, 46);
  const lower = (cap ? 116 - capLift(f, o, 12.5) : 136) - (big.size ? big.size + 8 : 0) - (tg ? 16 + tagLift(tg, 12) : 0);
  if (i.icon) {
    const s = Math.max(30, Math.min(84, lower - 16));
    b += icon(f.icon, 72 - s / 2, (8 + lower) / 2 - s / 2, s, m, lit ? 2.1 : 1.7);
  }
  const y = i.icon ? lower + big.size + 4 : (cap ? 66 : 76) + big.size * 0.36 - (tg ? 8 : 0);
  b += drawBig(big, f, 72, y, m, m, "middle", "", 1.6);
  if (tg) b += tagText(72, y + 17 + tagLift(tg, 12), tg, 124, 12, m, "middle", 0.85);
  const lv = levelOf(f, i);
  if (lv !== null) b += rect(0, 141, 144, 3, 0, m, 'fill-opacity="0.25"') + rect(0, 141, Math.max(3, 144 * lv), 3, 0, m);
  b += cap;
  b += badges(f, i, ink, 12, true);
  return doc(b, defs);
}

// ------------------------------------------------------------------ (1.3) twenty more looks
//
// Twenty more in the spirit of the clear looks - the state big, at most one small line (the
// name, else the room), a thermostat's target and mode and a moving blind's tag - each with its
// own shape. Where a look would draw an off key grey, it uses the Face's offAccent when the
// user chose one; offline stays red.

/** What every one of them works out first. */
interface Bits {
  i: Info;
  lit: boolean;
  /** The accent, red when offline. */
  c: string;
  /** The lit colour: a reading's or a status's own colour, else the accent. */
  base: string;
  /** The off colour the user chose, for an off key that is online; else null. */
  off: string | null;
  tg: Tag | "";
  lv: number | null;
  alone: boolean;
}

function bits(f: Face, o: LookOpts): Bits {
  const lit = f.active && f.online;
  const c = f.online ? f.accent : P.crit;
  return {
    i: o.info, lit, c, base: lit && f.stateColour ? f.stateColour : c, off: !f.active && f.online && f.offAccent ? f.offAccent : null,
    tg: tag(f, o.info), lv: levelOf(f, o.info), alone: iconAlone(f, o),
  };
}

/** The big words for a band `band` high: no size so big that the words and the tag leave it. */
function fitBig(f: Face, i: Info, sizes: number[], maxW: number, band: number, tg: Tag | "", tagSz = 13, upper = false): Big {
  const th = tg ? tagSize(tg, tagSz) + 7 : 0;
  // (1.3) bigger words as far as the band has room for them, no further
  return bigWords(f, i, sizes, maxW, 800, upper, (s) => s * 0.72 + th <= band, null);
}

/** The big words and the tag under them in the band top..bottom: centred in it, or sat on its foot. */
function words(f: Face, big: Big, tg: Tag | "", x: number, top: number, bottom: number, anchor: "start" | "middle" | "end", fill: string, unitFill: string, tagFill: string, tagW: number,
  tagSz = 13, extra = "", foot = false): { svg: string; end: number } {
  if (!big.size) return { svg: "", end: top };
  const capH = big.size * 0.72;
  const th = tg ? tagSize(tg, tagSz) + 7 : 0;
  let vy = (foot ? Math.max(top, bottom - capH - th) : top + Math.max(0, (bottom - top - capH - th) / 2)) + capH;
  // (1.3) bigger text than the band holds: it rises rather than run into what is under the band
  if (T !== ONE) vy = Math.min(vy, bottom - th);
  let svg = drawBig(big, f, x, vy, fill, unitFill, anchor, extra);
  if (tg) svg += tagText(x, vy + th, tg, tagW, tagSz, tagFill, anchor);
  return { svg, end: vy + th };
}

/** The colour of an off key's grey piece: the user's off colour, else the grey. */
const greyOr = (b: Bits, grey: string) => b.off ?? grey;

/** The words' colour: a reading's own, else white lit, the off colour or grey off. */
const ink = (f: Face, b: Bits, litInk: string = P.text, grey: string = P.dim) => f.stateColour ?? (b.lit ? litInk : b.off ?? grey);

/** The icon's colour: lit, offline, off. */
const iconInk = (f: Face, b: Bits, litInk: string, grey: string = P.muted) => (b.lit ? litInk : !f.online ? P.crit : b.off ?? grey);

/** A dark edge round every piece of text, so it reads over a busy paper. */
const edged = (svg: string, c: string, w: number) => svg.replace(/<text /g, `<text stroke="${c}" stroke-width="${n(w)}" stroke-linejoin="round" paint-order="stroke" `);

const MONO = "Consolas, Menlo, Courier New, monospace";

/** Diagonal: a coloured corner cut across the key with the icon in it, the value set to the right below it. */
function diagonal(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const defs = grad("tri", b.base, 1, b.base, 0.74, 1, 1);
  const T = b.alone ? 144 : i.icon ? 86 : 58;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  s += `<path d="M 0 0 H ${T} L 0 ${T} Z" fill="${b.lit ? "url(#tri)" : greyOr(b, P.panel2)}"${!b.lit && b.off ? ' fill-opacity="0.3"' : ""}/>`;
  s += `<path d="M ${T} 0 L 0 ${T}" stroke="${f.online ? (b.lit ? b.base : greyOr(b, P.line)) : P.crit}" stroke-width="2.5"${f.online ? "" : ' stroke-dasharray="6 5"'}/>`;
  if (b.lv !== null && b.lv > 0.01) s += `<path d="M 0 ${T} L ${n(T * b.lv)} ${n(T - T * b.lv)}" stroke="${b.lit ? X.white : greyOr(b, P.muted)}" stroke-width="5" stroke-linecap="round"/>`;
  const ic = b.lit ? P.bg : !f.online ? P.crit : b.off ?? P.dim;
  if (b.alone) return doc(s + icon(f.icon, 14, 14, 56, ic, 2.2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 11, 11, 30, ic, 2.2);
  const cap = caption(f, o, 132, 134, 120, 14, P.dim, "end");
  const top = i.icon ? 56 : 36, bottom = cap ? 114 - capLift(f, o, 14) : 134;
  const big = fitBig(f, i, [56, 50, 44, 38, 32, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 132, top, bottom, "end", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 120).svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Hex: a hexagon plate - filled with the accent when lit, an outline when off - the value on it. */
function hex(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const cap = b.alone ? "" : caption(f, o, 72, 136, 124, 13.5, P.dim);
  const R = cap ? 62 : 66, cx = 72, cy = cap ? 63 : 72, h = (R * Math.sqrt(3)) / 2;
  const pts = [[cx - R, cy], [cx - R / 2, cy - h], [cx + R / 2, cy - h], [cx + R, cy], [cx + R / 2, cy + h], [cx - R / 2, cy + h]];
  const d = "M " + pts.map((p) => n(p[0]!) + " " + n(p[1]!)).join(" L ") + " Z";
  const defs = grad("hx", b.base, 1, b.base, 0.72, 1, 1);
  let s = rect(0, 0, 144, 144, 0, X.night);
  if (b.lit) s += `<path d="${d}" fill="url(#hx)"/><path d="${d}" fill="none" stroke="${X.white}" stroke-opacity="0.25" stroke-width="2" stroke-linejoin="round"/>`;
  else s += `<path d="${d}" fill="${P.panel}" stroke="${f.online ? greyOr(b, P.line) : P.crit}" stroke-width="${b.off ? 3.5 : 2.5}" stroke-linejoin="round"${f.online ? "" : ' stroke-dasharray="7 5"'}/>`;
  const ic = b.lit ? P.bg : !f.online ? P.crit : b.off ?? P.muted;
  if (b.alone) return doc(s + icon(f.icon, cx - 30, cy - 30, 60, ic, 2.2) + badges(f, i, DARK, 10, true), defs);
  if (i.icon) s += icon(f.icon, cx - 11, cy - h + 11, 22, ic, 2.2);
  const showLv = b.lv !== null && !b.tg;
  const top = cy - h + (i.icon ? 38 : 14), bottom = cy + h - (showLv ? 20 : 10);
  const big = fitBig(f, i, [46, 42, 38, 34, 30, 28, 24], 100, bottom - top, b.tg);
  s += words(f, big, b.tg, cx, top, bottom, "middle", b.lit ? P.bg : ink(f, b), b.lit ? P.panel2 : P.muted, b.lit ? P.bg : greyOr(b, P.dim), 96).svg;
  if (showLv) {
    const y = cy + h - 14;
    s += rect(cx - 30, y, 60, 5, 2.5, b.lit ? P.bg : P.line, b.lit ? 'fill-opacity="0.25"' : "") + rect(cx - 30, y, Math.max(5, 60 * b.lv!), 5, 2.5, b.lit ? P.bg : greyOr(b, P.muted));
  }
  s += cap;
  s += badges(f, i, DARK, 10, true);
  return doc(s, defs);
}

/** Stripe: a stripe down the left edge that fills with the level (whole when lit), the words beside it. */
function stripe(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const W = 16;
  const fillTo = b.lv ?? onFill(f, b.lit || !!b.off);
  const defs = grad("st", b.base, 0.75, b.base, 1);
  let s = rect(0, 0, 144, 144, 0, P.bg) + rect(0, 0, W, 144, 0, f.online ? P.panel2 : P.crit, f.online ? "" : 'fill-opacity="0.35"');
  if (f.online && fillTo > 0.003) s += rect(0, 144 - 144 * fillTo, W, 144 * fillTo, 0, b.lit ? "url(#st)" : greyOr(b, P.muted));
  if (b.lit) s += rect(W, 0, 3, 144, 0, b.base, 'fill-opacity="0.3"');
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 44, 38, 68, ic, 2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 30, 14, 24, ic, 2.2);
  const cap = caption(f, o, 28, 134, 110, 14, P.dim, "start");
  const top = i.icon ? 46 : 16, bottom = cap ? 114 - capLift(f, o, 14) : 134;
  const big = fitBig(f, i, [54, 48, 42, 36, 32, 28, 24], 104, bottom - top, b.tg);
  s += words(f, big, b.tg, 29, top, bottom, "start", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 104).svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Switch: a toggle switch - the knob right and the track lit when on, the knob at the level for a dimmer - the value under it. */
function toggle(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const pos = b.lit ? b.lv ?? 1 : f.kind === "reading" && b.lv !== null ? b.lv : 0;
  const [tx, ty, tw, th] = b.alone ? [14, 44, 116, 56] : [12, 14, 84, 44];
  const r = th / 2, kr = r - 4;
  const kx = tx + r + (tw - 2 * r) * pos, ky = ty + r;
  const defs = grad("tr", b.base, 0.8, b.base, 1, 1, 0);
  let s = rect(0, 0, 144, 144, 0, P.bg);
  if (b.lit) s += rect(tx, ty + 3, tw, th, r, b.base, 'fill-opacity="0.2"');
  s += rect(tx, ty, tw, th, r, b.lit ? "url(#tr)" : !f.online ? P.panel2 : b.off ?? P.line,
    !f.online ? `stroke="${P.crit}" stroke-width="2" stroke-dasharray="6 4"` : !b.lit && b.off ? 'fill-opacity="0.35"' : "");
  s += `<circle cx="${n(kx)}" cy="${n(ky + 1.5)}" r="${n(kr)}" fill="${X.night}" fill-opacity="0.35"/>`;
  s += `<circle cx="${n(kx)}" cy="${n(ky)}" r="${n(kr)}" fill="${b.lit ? X.white : !f.online ? P.muted : b.off ?? P.dim}"/>`;
  const is = kr * 1.15;
  if (i.icon) s += icon(f.icon, kx - is / 2, ky - is / 2, is, b.lit ? b.base : P.bg, 2.2);
  if (b.alone) return doc(s + badges(f, i, DARK, 12, true), defs);
  const cap = caption(f, o, 14, 134, 118, 14, P.dim, "start");
  const top = ty + th + 8, bottom = cap ? 114 - capLift(f, o, 14) : 134;
  const big = fitBig(f, i, [52, 46, 40, 36, 32, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 13, top, bottom, "start", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 120).svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** LCD: a retro screen - glowing in the accent when on, dark when off - the value in capitals of a fixed width. */
function lcd(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const cap = b.alone ? "" : caption(f, o, 72, 134, 124, 12.5, P.dim, "middle", 700);
  const sb = cap ? 114 - capLift(f, o, 12.5) : 134;
  const defs = radial("scr", [[0, b.base, 0.3], [1, b.base, 0.08]], 0.5, 0.45, 0.75)
    + `<pattern id="sl" width="4" height="3" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="${X.black}" fill-opacity="0.35"/></pattern>`;
  let s = rect(0, 0, 144, 144, 0, P.panel2);
  s += rect(9, 9, 126, sb - 9, 9, X.night, `stroke="${f.online ? (b.lit ? b.base : greyOr(b, P.line)) : P.crit}" stroke-width="2"${f.online ? "" : ' stroke-dasharray="6 4"'}`);
  if (b.lit) s += rect(10, 10, 124, sb - 11, 8, "url(#scr)");
  else if (b.off) s += rect(10, 10, 124, sb - 11, 8, b.off, 'fill-opacity="0.08"');
  const col = b.lit ? b.base : f.stateColour ?? b.off ?? P.muted;
  const ic = b.lit ? b.base : !f.online ? P.crit : col;
  if (b.alone) s += icon(f.icon, 38, 32, 68, ic, 2);
  else {
    if (i.icon) s += icon(f.icon, 18, 17, 20, ic, 2.2);
    const showLv = b.lv !== null && !b.tg;
    const top = i.icon ? 40 : 18, bottom = sb - (showLv ? 22 : 10);
    const big = fitBig(f, i, [48, 42, 38, 34, 30, 28, 24], 110, bottom - top, b.tg, 13, true);
    const w = words(f, big, b.tg, 72, top, bottom, "middle", col, col, col, 112);
    const glow = b.lit ? words(f, big, b.tg, 72, top, bottom, "middle", col, col, col, 112, 13, `stroke="${b.base}" stroke-opacity="0.3" stroke-width="5" stroke-linejoin="round"`).svg.match(/^<text[\s\S]*?<\/text>/)?.[0] ?? "" : "";
    s += (glow + w.svg).replace(/font-family="[^"]*"/g, `font-family="${MONO}"`);
    if (showLv) {
      const on = Math.round(b.lv! * 10);
      for (let k = 0; k < 10; k++) s += rect(17 + k * 11.2, sb - 16, 8.4, 6, 1, k < on ? (b.lit ? b.base : greyOr(b, P.muted)) : P.panel2);
    }
  }
  s += `<rect x="10" y="10" width="124" height="${n(sb - 11)}" rx="8" fill="url(#sl)"/>`;
  s += cap;
  s += badges(f, i, DARK, 14, true);
  return doc(s, defs);
}

/** Dial: a knob in a ring of ticks lit as far as the level (all of them when on), the value under it. */
function dial(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const cap = b.alone ? "" : caption(f, o, 72, 136, 124, 13.5, P.dim);
  const bottom = cap ? 120 - capLift(f, o, 13.5) : 138;
  const big: Big = b.alone ? { words: "", unit: "", size: 0, usize: 0, role: "value" } : fitBig(f, i, [44, 40, 36, 32, 28, 24], 124, b.tg ? 44 : 50, b.tg);
  const need = big.size ? big.size * 0.72 + (b.tg ? 20 : 0) : 0;
  const tTop = bottom - need - 6;
  const Ro = b.alone ? 60 : Math.max(26, Math.min(44, (tTop - 10) / 2));
  const cx = 72, cy = b.alone ? 72 : 6 + Ro + Math.max(0, (tTop - 10 - 2 * Ro) / 2);
  const shown = b.lv ?? onFill(f, b.lit);
  let s = rect(0, 0, 144, 144, 0, X.night);
  const defs = radial("knob", [[0, P.panel2, 1], [1, P.bg, 1]], 0.4, 0.35, 0.7);
  for (let k = 0; k <= 24; k++) {
    const a = ((-135 + (270 * k) / 24 - 90) * Math.PI) / 180;
    const on = f.online && shown > 0.005 && k / 24 <= shown + 0.001;
    const r0 = Ro - (k % 6 === 0 ? 10 : 7);
    s += `<path d="M ${n(cx + r0 * Math.cos(a))} ${n(cy + r0 * Math.sin(a))} L ${n(cx + Ro * Math.cos(a))} ${n(cy + Ro * Math.sin(a))}" stroke="${on ? (b.lit ? b.base : greyOr(b, P.muted)) : !f.online ? P.crit : b.off && !b.lv ? b.off : P.line}" stroke-width="3" stroke-linecap="round"${!f.online || (!on && b.off && !b.lv) ? ' stroke-opacity="0.45"' : ""}/>`;
  }
  const mk = b.lv !== null ? markOf(f, i) : null;
  if (mk !== null) s += notch(cx, cy, Ro - 5, -135 + 270 * mk, 7, X.white, X.night);
  const kr = Ro - 14;
  if (b.lit) s +=`<circle cx="${cx}" cy="${n(cy)}" r="${n(kr + 3)}" fill="${b.base}" fill-opacity="0.18"/>`;
  s += `<circle cx="${cx}" cy="${n(cy)}" r="${n(kr)}" fill="url(#knob)" stroke="${b.lit ? b.base : !f.online ? P.crit : greyOr(b, P.line)}" stroke-width="1.6"/>`;
  const pa = ((-135 + 270 * shown - 90) * Math.PI) / 180;
  s += `<circle cx="${n(cx + (kr - 5) * Math.cos(pa))}" cy="${n(cy + (kr - 5) * Math.sin(pa))}" r="2.6" fill="${b.lit ? b.base : greyOr(b, P.muted)}"/>`;
  if (i.icon) {
    const is = kr * 0.95;
    s += icon(f.icon, cx - is / 2, cy - is / 2, is, iconInk(f, b, b.base), 2.2);
  }
  s += words(f, big, b.tg, 72, tTop, bottom, "middle", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 124).svg;
  s += cap;
  s += badges(f, i, DARK, 10, true);
  return doc(s, defs);
}

/** Ticket: a ticket with notches and a torn line - its stub in the accent when on, holding the icon - the value on the rest. */
function ticket(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const py = 50;
  const defs = grad("stub", b.base, 1, b.base, 0.78, 1, 1);
  let s = rect(0, 0, 144, 144, 0, X.night);
  s += rect(6, 8, 132, 128, 12, P.panel2, f.online ? (b.lit ? `stroke="${b.base}" stroke-opacity="0.6" stroke-width="1.5"` : "") : `stroke="${P.crit}" stroke-width="2" stroke-dasharray="6 4"`);
  s += `<path d="M 6 ${py} V 20 A 12 12 0 0 1 18 8 H 126 A 12 12 0 0 1 138 20 V ${py} Z" fill="${b.lit ? "url(#stub)" : !f.online ? P.panel : b.off ?? P.line}"${!b.lit && b.off ? ' fill-opacity="0.4"' : ""}/>`;
  s += `<circle cx="6" cy="${py}" r="8" fill="${X.night}"/><circle cx="138" cy="${py}" r="8" fill="${X.night}"/>`;
  s += `<path d="M 18 ${py} H 126" stroke="${X.night}" stroke-width="2" stroke-dasharray="4 4"/>`;
  const showLv = b.lv !== null && !b.tg;
  if (showLv && b.lv! > 0.01) s += `<path d="M 18 ${py} H ${n(18 + 108 * b.lv!)}" stroke="${b.lit ? X.white : greyOr(b, P.muted)}" stroke-width="3" stroke-dasharray="4 4"/>`;
  const ic = b.lit ? P.bg : !f.online ? P.crit : b.off ?? P.dim;
  if (b.alone) return doc(s + icon(f.icon, 46, 62, 52, iconInk(f, b, b.base), 2) + badges(f, i, DARK, 13, true), defs);
  if (i.icon) s += icon(f.icon, 17, 16, 26, ic, 2.2);
  const cap = caption(f, o, 72, 127, 120, 13.5, P.dim);
  const top = py + 8, bottom = cap ? 110 - capLift(f, o, 13.5) : 128;
  const big = fitBig(f, i, [48, 42, 38, 34, 30, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 72, top, bottom, "middle", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 120).svg;
  s += cap;
  s += badges(f, i, DARK, 13, true);
  return doc(s, defs);
}

/** Bubble: the state in a speech bubble - filled when on - and the name beside its tail. */
function bubble(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const cap = b.alone ? "" : caption(f, o, 40, 128, 96, 13.5, P.dim, "start");
  const y1 = cap ? 100 - capLift(f, o, 13.5) : 112, x0 = 8, y0 = 8, x1 = 136, r = 22;
  const d = `M ${x0 + r} ${y0} H ${x1 - r} A ${r} ${r} 0 0 1 ${x1} ${y0 + r} V ${y1 - r} A ${r} ${r} 0 0 1 ${x1 - r} ${y1} H 42 L 18 ${y1 + 18} L 26 ${y1} H ${x0 + r} A ${r} ${r} 0 0 1 ${x0} ${y1 - r} V ${y0 + r} A ${r} ${r} 0 0 1 ${x0 + r} ${y0} Z`;
  const defs = grad("bub", b.base, 1, b.base, 0.76, 1, 1);
  let s = rect(0, 0, 144, 144, 0, P.bg);
  s += b.lit ? `<path d="${d}" fill="url(#bub)"/>`
    : `<path d="${d}" fill="${P.panel2}" stroke="${f.online ? greyOr(b, P.line) : P.crit}" stroke-width="${b.off ? 3 : 2}" stroke-linejoin="round"${f.online ? "" : ' stroke-dasharray="7 5"'}/>`;
  const ic = b.lit ? P.bg : !f.online ? P.crit : b.off ?? P.muted;
  if (b.alone) return doc(s + icon(f.icon, 42, 30, 60, ic, 2.2) + badges(f, i, DARK, 14, true), defs);
  if (i.icon) s += icon(f.icon, 20, 18, 22, ic, 2.2);
  const showLv = b.lv !== null && !b.tg;
  const top = i.icon ? 42 : 18, bottom = y1 - (showLv ? 20 : 8);
  const big = fitBig(f, i, [46, 42, 38, 34, 30, 28, 24], 112, bottom - top, b.tg);
  s += words(f, big, b.tg, 72, top, bottom, "middle", b.lit ? P.bg : ink(f, b), b.lit ? P.panel2 : P.muted, b.lit ? P.bg : greyOr(b, P.dim), 110).svg;
  if (showLv) s += rect(34, y1 - 15, 76, 5, 2.5, b.lit ? P.bg : P.line, b.lit ? 'fill-opacity="0.25"' : "") + rect(34, y1 - 15, Math.max(5, 76 * b.lv!), 5, 2.5, b.lit ? P.bg : greyOr(b, P.muted));
  s += cap;
  s += badges(f, i, DARK, 14, true);
  return doc(s, defs);
}

/** Frame: corner brackets round the words - thick in the accent when on, thin when off - the level along the foot. */
function brackets(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.night);
  if (b.lit) s += rect(10, 10, 124, 124, 14, b.base, 'fill-opacity="0.07"');
  const col = b.lit ? b.base : !f.online ? P.crit : b.off ?? P.muted;
  const w = b.lit ? 6 : b.off ? 4 : 3, L = 28, a = 10, z = 134, q = 8;
  const arms = [
    `M ${a} ${a + L} V ${a + q} Q ${a} ${a} ${a + q} ${a} H ${a + L}`, `M ${z - L} ${a} H ${z - q} Q ${z} ${a} ${z} ${a + q} V ${a + L}`,
    `M ${z} ${z - L} V ${z - q} Q ${z} ${z} ${z - q} ${z} H ${z - L}`, `M ${a + L} ${z} H ${a + q} Q ${a} ${z} ${a} ${z - q} V ${z - L}`,
  ];
  s += `<path d="${arms.join(" ")}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"${f.online ? "" : ' stroke-dasharray="7 5"'}/>`;
  const showLv = b.lv !== null && !b.tg;
  if (showLv) s += `<path d="M 48 ${z} H 96" stroke="${P.line}" stroke-width="3" stroke-linecap="round"/>` + (b.lv! > 0.01 ? `<path d="M 48 ${z} H ${n(48 + 48 * b.lv!)}" stroke="${b.lit ? b.base : greyOr(b, P.muted)}" stroke-width="3" stroke-linecap="round"/>` : "");
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 38, 38, 68, ic, 2) + badges(f, i, DARK, 14, true));
  if (i.icon) s += icon(f.icon, 60, 20, 24, ic, 2.2);
  const cap = caption(f, o, 72, 122, 108, 13.5, b.lit ? P.text : P.dim);
  const top = i.icon ? 50 : 22, bottom = cap ? 104 - capLift(f, o, 13.5) : 124;
  const big = fitBig(f, i, [46, 42, 38, 34, 30, 28, 24], 108, bottom - top, b.tg);
  s += words(f, big, b.tg, 72, top, bottom, "middle", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 108).svg;
  s += cap;
  s += badges(f, i, DARK, 14, true);
  return doc(s);
}

/** Shadow: a card with a hard shadow under it - in the accent when on, a grey line when off. */
function shadow(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  s += rect(18, 18, 118, 118, 16, f.online ? (b.lit ? b.base : b.off ?? P.line) : P.crit, f.online ? "" : 'fill-opacity="0.35"');
  s += rect(8, 8, 118, 118, 16, P.panel2, `stroke="${f.online ? (b.lit ? b.base : greyOr(b, P.line)) : P.crit}" stroke-width="2"${f.online ? "" : ' stroke-dasharray="6 4"'}`);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 34, 34, 66, ic, 2) + badges(f, i, DARK, 14, true));
  if (i.icon) s += icon(f.icon, 20, 20, 24, ic, 2.2);
  const cap = caption(f, o, 20, 115, 100, 13.5, P.dim, "start");
  const showLv = b.lv !== null && !b.tg;
  const bar = cap ? 98 : 110;
  const top = i.icon ? 50 : 22, bottom = (cap ? 98 - capLift(f, o, 13.5) : 116) - (showLv ? 8 : 0);
  const big = fitBig(f, i, [46, 42, 38, 34, 30, 28, 24], 100, bottom - top, b.tg);
  s += words(f, big, b.tg, 19, top, bottom, "start", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 100).svg;
  if (showLv) s += rect(20, bar, 94, 4, 2, P.line) + rect(20, bar, Math.max(4, 94 * b.lv!), 4, 2, b.lit ? b.base : greyOr(b, P.muted));
  s += cap;
  s += badges(f, i, DARK, 14, true);
  return doc(s);
}

/** Line: nothing but the value standing on one line - the accent's, as long as the level, when on. */
function line(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.night);
  const ic = iconInk(f, b, b.base);
  if (b.alone) {
    s += icon(f.icon, 38, 28, 68, ic, 2) + rect(30, 112, 84, 4, 2, b.lit ? b.base : !f.online ? P.crit : b.off ?? P.line);
    return doc(s + badges(f, i, DARK, 12, true));
  }
  if (i.icon) s += icon(f.icon, 14, 14, 22, ic, 2.2);
  const cap = caption(f, o, 14, 134, 120, 14, P.dim, "start");
  const uy = cap ? 104 - capLift(f, o, 14) : 122;
  const top = i.icon ? 44 : 16, bottom = uy - 10;
  const big = fitBig(f, i, [56, 50, 44, 38, 32, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 13, top, bottom, "start", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 120, 13, "", true).svg;
  s += rect(14, uy, 116, b.off ? 3 : 2, 1, !f.online ? P.crit : b.off ?? P.line);
  const len = b.lv ?? onFill(f, b.lit);
  if (f.online && len > 0.005) s += rect(14, uy - 1, Math.max(4, 116 * len), 4, 2, b.lit ? b.base : greyOr(b, P.muted));
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s);
}

/** Tube: a thermometer tube at the side, filled as far as the level ((1.3) full when on with no level), the value beside it. */
function tube(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const tx = 106, tw = 18, t0 = b.alone ? 20 : 40, t1 = b.alone ? 104 : 96, by = t1 + 10, br = 12;
  const h = b.lv ?? onFill(f, b.lit);
  const col = b.lit ? b.base : !f.online ? P.crit : b.off ?? (b.lv !== null ? P.muted : P.line);
  let s = rect(0, 0, 144, 144, 0, P.bg);
  s += rect(tx, t0, tw, t1 - t0 + 6, tw / 2, P.panel2, `stroke="${P.line}" stroke-width="1.5"`);
  s += `<circle cx="${tx + tw / 2}" cy="${by}" r="${br + 1.5}" fill="${P.panel2}" stroke="${P.line}" stroke-width="1.5"/>`;
  if (f.online && h > 0.003) s += rect(tx + 4, t0 + 4 + (t1 - t0 - 4) * (1 - h), tw - 8, (t1 - t0 - 4) * h + 8, (tw - 8) / 2, col);
  s += `<circle cx="${tx + tw / 2}" cy="${by}" r="${br - 2}" fill="${col}"${f.online ? "" : ' fill-opacity="0.5"'}/>`;
  for (let k = 1; k <= 4; k++) s += `<path d="M ${tx - 8} ${n(t0 + ((t1 - t0) * k) / 5)} H ${tx - 3}" stroke="${P.line}" stroke-width="2" stroke-linecap="round"/>`;
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 14, 42, 60, ic, 2) + badges(f, i, DARK, 12, true));
  if (i.icon) s += icon(f.icon, 14, 14, 22, ic, 2.2);
  const cap = caption(f, o, 13, 136, 120, 14, P.dim, "start");
  const top = i.icon ? 44 : 16, bottom = cap ? 116 - capLift(f, o, 14) : 134;
  const big = fitBig(f, i, [48, 42, 38, 34, 30, 28, 24], 88, bottom - top, b.tg);
  s += words(f, big, b.tg, 12, top, bottom, "start", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 88).svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s);
}

/** Stamp: the icon giant and faint, cut off by the edge - in the accent when on - with the value over it. */
function stamp(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  if (b.alone) return doc(s + icon(f.icon, 30, 30, 84, iconInk(f, b, b.base), 2) + badges(f, i, DARK, 12, true));
  if (i.icon) s += `<g opacity="${b.lit ? 0.32 : !f.online ? 0.22 : b.off ? 0.3 : 1}">${icon(f.icon, 50, 40, 112, b.lit ? b.base : !f.online ? P.crit : b.off ?? P.panel2, 2.6)}</g>`;
  let defs = "";
  if (i.graph && f.online && f.series.length >= 2) {
    // a reading's history, faint, across the foot behind the words
    const g = graph(f, { ...i, scale: false }, -2, 84, 148, 34, f.stateColour ?? b.c, DARK, "g");
    s += `<g opacity="0.4">${g.body}</g>`;
    defs = g.defs;
  }
  // the mark at the top: as long as the level, when there is one
  if (b.lv !== null) s += rect(14, 16, 88, 6, 3, P.panel2) + rect(14, 16, Math.max(6, 88 * b.lv), 6, 3, b.lit ? b.base : b.off ?? P.muted);
  else s += rect(14, 16, 26, 6, 3, b.lit ? b.base : !f.online ? P.crit : b.off ?? P.line);
  const cap = caption(f, o, 14, 134, 120, 14, b.lit ? P.text : P.dim, "start");
  const top = 30, bottom = cap ? 114 - capLift(f, o, 14) : 134;
  const big = fitBig(f, i, [56, 50, 44, 38, 32, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 13, top, bottom, "start", ink(f, b), P.dim, b.lit ? b.base : greyOr(b, P.dim), 120).svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Pastel: a soft wash of the accent on white paper with dark type; off, plain grey paper. */
function pastel(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.white);
  s += b.lit ? rect(0, 0, 144, 144, 0, b.base, 'fill-opacity="0.32"') : b.off ? rect(0, 0, 144, 144, 0, b.off, 'fill-opacity="0.2"') : rect(0, 0, 144, 144, 0, X.paper2);
  s += `<circle cx="126" cy="8" r="56" fill="${X.white}" fill-opacity="${b.lit ? 0.4 : 0.55}"/>`;
  if (!f.online) s += `<rect x="3" y="3" width="138" height="138" rx="20" fill="none" stroke="${X.inkCrit}" stroke-width="2.5" stroke-dasharray="7 5"/>`;
  const ic = b.lit ? X.ink : !f.online ? X.inkCrit : b.off ?? X.inkMuted;
  if (b.alone) return doc(s + `<circle cx="72" cy="72" r="46" fill="${X.white}"/>` + icon(f.icon, 44, 44, 56, ic, 2.2) + badges(f, i, PAPER, 12, true));
  if (i.icon) s += `<circle cx="33" cy="33" r="20" fill="${X.white}"/>` + icon(f.icon, 21, 21, 24, ic, 2.2);
  const cap = caption(f, o, 14, 134, 120, 14, X.inkDim, "start");
  const top = i.icon ? 62 : 18, bottom = cap ? 114 - capLift(f, o, 14) : 132;
  const big = fitBig(f, i, [50, 44, 40, 36, 32, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 13, top, bottom, "start", b.lit ? X.ink : f.stateColour ?? (b.off ? X.ink : X.inkDim), X.inkDim, b.lit ? X.ink : X.inkDim, 120).svg;
  if (b.lv !== null) s += rect(0, 140, 144, 4, 0, X.paperLine) + rect(0, 140, Math.max(4, 144 * b.lv), 4, 0, b.lit ? b.base : b.off ?? X.inkMuted);
  s += cap;
  s += badges(f, i, PAPER, 12, true);
  return doc(s);
}

/** Carbon: a carbon weave with a light strip along the foot - lit in the accent as far as the level - and slanted type. */
function carbon(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const defs = `<pattern id="cf" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="${P.bg}"/><rect width="4" height="4" fill="${P.panel2}"/><rect x="4" y="4" width="4" height="4" fill="${P.panel2}"/></pattern>`
    + grad("sh", X.white, 0.12, X.white, 0);
  let s = `<rect width="144" height="144" fill="url(#cf)"/><rect width="144" height="72" fill="url(#sh)"/>`;
  const len = b.lv ?? onFill(f, b.lit || !!b.off);
  s += rect(14, 130, 116, 6, 3, X.night);
  if (b.lit && len > 0.005) s += rect(10, 126, Math.max(14, 116 * len + 8), 14, 7, b.base, 'fill-opacity="0.25"');
  if (len > 0.005 && f.online) s += rect(14, 130, Math.max(6, 116 * len), 6, 3, b.lit ? b.base : greyOr(b, P.muted));
  if (!f.online) s += rect(14, 130, 116, 6, 3, P.crit, 'fill-opacity="0.6"');
  const ic = iconInk(f, b, b.base, P.dim);
  if (b.alone) return doc(s + icon(f.icon, 36, 28, 72, ic, 2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 14, 14, 22, ic, 2.2);
  const cap = caption(f, o, 14, 120, 120, 13.5, P.dim, "start");
  const top = i.icon ? 44 : 16, bottom = cap ? 102 - capLift(f, o, 13.5) : 120;
  const big = fitBig(f, i, [52, 46, 40, 36, 32, 28, 24], 118, bottom - top, b.tg);
  s += words(f, big, b.tg, 13, top, bottom, "start", ink(f, b, X.white), P.dim, b.lit ? b.base : greyOr(b, P.dim), 118, 13, 'font-style="italic"').svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Grid: a grid of lamps that light row by row as far as the level (all of them when on), the words edged over them. */
function grid(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const shown = b.lv ?? onFill(f, b.lit);
  // (1.3) as many rows as the level has eighths (one at least for any level) - it lit one too many
  const rows = shown > 0.005 ? Math.max(1, Math.round(shown * 8)) : 0;
  let s = rect(0, 0, 144, 144, 0, X.night);
  for (let r = 0; r < 8; r++) {
    const on = f.online && 7 - r < rows;
    for (let k = 0; k < 8; k++) {
      const fill = on ? (b.lit ? b.base : greyOr(b, P.muted)) : !f.online && (r + k) % 3 === 0 ? P.crit : b.off ?? P.panel2;
      const op = on ? (b.lit ? 0.6 : 0.55) : !f.online ? 0.35 : b.off ? 0.3 : 1;
      s += `<circle cx="${16 + k * 16}" cy="${16 + r * 16}" r="5" fill="${fill}"${op < 1 ? ` fill-opacity="${n(op)}"` : ""}/>`;
    }
  }
  // on with no lamps to light (a number with no range): the icon says it in the accent
  const ic = iconInk(f, b, b.lit && rows > 0 ? X.white : b.base);
  if (b.alone) return doc(s + `<circle cx="72" cy="72" r="40" fill="${X.night}" fill-opacity="0.8"/>` + icon(f.icon, 44, 44, 56, ic, 2.2) + badges(f, i, DARK, 12, true));
  if (i.icon) s += `<circle cx="26" cy="26" r="16" fill="${X.night}" fill-opacity="0.85"/>` + icon(f.icon, 15, 15, 22, ic, 2.2);
  const cap = caption(f, o, 72, 134, 124, 14, b.lit ? P.text : P.dim, "middle", 700);
  const top = i.icon ? 44 : 14, bottom = cap ? 114 - capLift(f, o, 14) : 132;
  const big = fitBig(f, i, [52, 46, 40, 36, 32, 28, 24], 124, bottom - top, b.tg);
  s += edged(words(f, big, b.tg, 72, top, bottom, "middle", ink(f, b, X.white), b.lit ? P.text : P.muted, b.lit ? X.white : greyOr(b, P.dim), 124).svg + cap, X.night, 6);
  s += badges(f, i, DARK, 12, true);
  return doc(s);
}

/** Tab: a folder with the name on its tab - the tab in the accent when on - and the value in the folder. */
function tab(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const t = b.alone ? "" : i.name && f.name ? f.name : i.room && f.room ? f.room : "";
  const trole: TextRole = i.name && f.name ? "name" : "room";
  const nl0 = t ? nameLines(t, o.fit, S(trole, 13.5, 17), 100 - (T[trole] > 1 && f.badge ? 34 : 0), 700, 1) : null;
  // (bigger, beside the unread pill: never smaller than at 100 %)
  const nl = nl0 && T[trole] > 1 && f.badge && nl0.size < 13.5 ? nameLines(t, o.fit, 13.5, 100, 700, 1) : nl0;
  // the tab's right end: past the name, at most the folder's edge
  const tw = Math.min(116, nl ? Math.max(40, textWidth(nl.lines[0]!, nl.size, 700) + 22) : 40);
  const tabFill = b.lit ? b.base : !f.online ? P.panel2 : b.off ?? P.line;
  let s = rect(0, 0, 144, 144, 0, X.night);
  s += `<path d="M 8 36 V 18 A 10 10 0 0 1 18 8 H ${n(8 + tw - 6)} Q ${n(8 + tw)} 8 ${n(8 + tw + 4)} 16 L ${n(8 + tw + 12)} 36 Z" fill="${tabFill}"/>`;
  s += rect(8, 30, 128, 106, 14, b.lit ? P.panel2 : P.panel, `stroke="${f.online ? (b.lit ? b.base : greyOr(b, P.line)) : P.crit}" stroke-width="2"${f.online ? "" : ' stroke-dasharray="6 4"'}`);
  s += rect(9, 31, Math.min(126, tw + 10), 6, 0, tabFill);
  if (nl) s += text(20, 26 + dz(S(trole, 13.5, 17), 13.5) * 0.3, nl.lines[0]!, { size: nl.size, weight: 700, fill: b.lit || b.off ? P.bg : P.dim, role: trole });
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 50, 64, ic, 2) + badges(f, i, DARK, 40, true));
  if (i.icon) s += icon(f.icon, 20, 44, 22, ic, 2.2);
  const showLv = b.lv !== null && !b.tg;
  const top = i.icon ? 72 : 44, bottom = showLv ? 116 : 128;
  const big = fitBig(f, i, [48, 42, 38, 34, 30, 28, 24], 112, bottom - top, b.tg);
  s += words(f, big, b.tg, 19, top, bottom, "start", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 112).svg;
  if (showLv) s += rect(20, 122, 104, 4, 2, P.line) + rect(20, 122, Math.max(4, 104 * b.lv!), 4, 2, b.lit ? b.base : greyOr(b, P.muted));
  s += badges(f, i, DARK, 40, true);
  return doc(s);
}

/** Rise: a sun rising from the foot of the key - as high as the level, glowing when on - the value in the sky above it. */
function rise(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  // (1.3) as high as the level, lit or not (it rose higher for the same level when lit); full when on with no level
  const H = 12 + 38 * (b.lv ?? onFill(f, b.lit));
  const R = 96, cy = 144 - H + R;
  const defs = grad("sky", P.panel2, 1, X.night, 1) + radial("sun", [[0, b.base, 1], [1, b.base, 0.7]], 0.5, 0.1, 0.6);
  let s = rect(0, 0, 144, 144, 0, "url(#sky)");
  if (b.lit) s += rect(0, 0, 144, 144, 0, b.base, 'fill-opacity="0.08"') + `<circle cx="72" cy="${n(cy)}" r="${R + 14}" fill="${b.base}" fill-opacity="0.14"/>`;
  s += `<circle cx="72" cy="${n(cy)}" r="${R}" fill="${b.lit ? "url(#sun)" : !f.online ? P.crit : b.off ?? (b.lv !== null ? P.muted : P.line)}"${b.lit ? "" : ` fill-opacity="${!f.online ? 0.4 : b.off ? 0.5 : 1}"`}/>`;
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 22, 64, ic, 2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 14, 12, 22, ic, 2.2);
  const cap = caption(f, o, 72, 136, 124, 13.5, b.lit ? P.bg : P.text, "middle", 700);
  const top = i.icon ? 38 : 14, bottom = Math.min(144 - H, cap ? 118 - capLift(f, o, 13.5) : 138) - 6;
  const big = fitBig(f, i, [52, 46, 40, 36, 32, 28, 24], 124, bottom - top, b.tg);
  s += words(f, big, b.tg, 72, top, bottom, "middle", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 124).svg;
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Spot: a spotlight from the top shining down on the value - bright in the accent when on, faint when off. */
function spot(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const beam = b.lit ? b.base : b.off ?? P.panel2;
  const defs = grad("cone", beam, b.lit ? 0.55 : b.off ? 0.35 : 0.9, beam, 0);
  let s = rect(0, 0, 144, 144, 0, X.night);
  s += `<path d="M 60 6 L 84 6 L 138 118 L 6 118 Z" fill="url(#cone)"/>`;
  s += `<ellipse cx="72" cy="118" rx="62" ry="9" fill="${beam}" fill-opacity="${b.lit ? 0.32 : b.off ? 0.25 : 0.7}"/>`;
  s += rect(54, 0, 36, 8, 3, b.lit ? b.base : !f.online ? P.crit : b.off ?? P.line);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 14, 12, 22, ic, 2.2);
  const cap = caption(f, o, 72, 136, 124, 13.5, P.dim);
  const top = i.icon ? 38 : 16, bottom = cap ? 112 - capLift(f, o, 13.5) : 130;
  const big = fitBig(f, i, [52, 46, 40, 36, 32, 28, 24], 120, bottom - top, b.tg);
  s += words(f, big, b.tg, 72, top, bottom, "middle", ink(f, b), P.muted, b.lit ? b.base : greyOr(b, P.dim), 120).svg;
  if (b.lv !== null && !b.tg) s += rect(36, 140, 72, 3, 1.5, P.line) + rect(36, 140, Math.max(3, 72 * b.lv), 3, 1.5, b.lit ? b.base : greyOr(b, P.muted));
  s += cap;
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Button: a real key - raised when off, pressed in with a glow in the accent when on - with lamps for the level. */
function button(f: Face, o: LookOpts): string {
  const b = bits(f, o), i = b.i;
  const dy = b.lit ? 4 : 0;
  const defs = (b.lit ? grad("face", b.base, 0.42, b.base, 0.16) : grad("face", P.panel2, 1, P.panel, 1)) + grad("hi", X.white, 0.1, X.white, 0);
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(5, 5, 134, 134, 24, P.bg, `stroke="${P.line}" stroke-width="1"`);
  if (b.lit) s += rect(10, 12, 124, 122, 21, b.base, 'fill-opacity="0.25"');
  else s += rect(12, 16, 120, 118, 20, X.night);
  s += rect(12, 10 + dy, 120, 116, 20, P.panel2);
  s += rect(12, 10 + dy, 120, 116, 20, "url(#face)", `stroke="${f.online ? (b.lit ? b.base : greyOr(b, P.line)) : P.crit}" stroke-width="${b.off ? 2.5 : 1.5}"${f.online ? "" : ' stroke-dasharray="6 4"'}`);
  s += rect(16, 12 + dy, 112, 40, 18, "url(#hi)");
  const ic = iconInk(f, b, X.white, P.dim);
  // the lamps: five for a level, else one
  const cnt = b.lv !== null && !b.tg ? 5 : 1;
  const lit = b.lv !== null && !b.tg ? Math.round(b.lv * 5) : b.lit ? 1 : 0;
  const ly = 116 + dy;
  for (let k = 0; k < cnt; k++) {
    const x = 72 - ((cnt - 1) * 11) / 2 + k * 11;
    const on = f.online && k < lit;
    if (on && b.lit) s += `<circle cx="${n(x)}" cy="${ly}" r="5.5" fill="${b.base}" fill-opacity="0.3"/>`;
    s += `<circle cx="${n(x)}" cy="${ly}" r="3" fill="${on ? (b.lit ? b.base : greyOr(b, P.muted)) : !f.online ? P.crit : b.off ?? P.line}"/>`;
  }
  if (b.alone) return doc(s + icon(f.icon, 42, 34 + dy, 60, ic, 2.2) + badges(f, i, DARK, 14, true), defs);
  if (i.icon) s += icon(f.icon, 22, 20 + dy, 22, ic, 2.2);
  const cap = caption(f, o, 72, 106 + dy, 104, 13, b.lit ? P.text : P.dim);
  const top = (i.icon ? 44 : 22) + dy, bottom = (cap ? 92 - capLift(f, o, 13) : 108) + dy;
  const big = fitBig(f, i, [46, 42, 38, 34, 30, 28, 24], 104, bottom - top, b.tg);
  s += words(f, big, b.tg, 72, top, bottom, "middle", ink(f, b, X.white), b.lit ? P.text : P.muted, b.lit ? X.white : greyOr(b, P.dim), 104).svg;
  s += cap;
  s += badges(f, i, DARK, 14 + dy, true);
  return doc(s, defs);
}

// ------------------------------------------------------------------ (1.3) the name-first looks
//
// Eighteen looks that lead with the name: set big (two lines, smaller before it is cut, as the
// name's fit says), and the status right under or beside it - On / Off, the temperature with
// its unit, the watts, the brightness, the position, the mode, the countdown, the count - so
// both read at once on a 72 px key. The detail goes on a small line when there is room (a
// thermostat's target and mode first); the room only when the name takes one line.

/** What a name-first look works out first: the bits, the title it leads with, the room under it. */
interface NF extends Bits {
  /** The name, else the room (with the name hidden the room leads). */
  title: string;
  /** The room, when the name leads and the room is shown. */
  room: string;
  /** How wide the badges at the top right are (0: none). */
  bw: number;
  /** (1.3) What the title is, for its size: the name, or the room leading in its place. */
  titleRole: TextRole;
}

function nf(f: Face, o: LookOpts): NF {
  const b = bits(f, o), i = b.i;
  const title = i.name && f.name ? f.name : i.room && f.room ? f.room : "";
  const room = i.name && f.name && i.room && f.room ? f.room : "";
  const k = (f.allowed ? 0 : 1) + (f.online ? 0 : 1) + (i.battery && f.battery !== null && f.battery <= 20 ? 1 : 0) + (f.hold ? 1 : 0) + (f.taken ? 1 : 0);
  return { ...b, title, room, bw: k ? k * 26 + 4 : f.badge && bigger() ? 34 : 0, titleRole: i.name && f.name ? "name" : "room" };
}

interface NameSet { lines: string[]; size: number; role?: TextRole }

/** The title laid out as the key's name fit says: two lines by default, smaller before it is cut. */
function nameOf(b: NF, o: LookOpts, size: number, maxW: number, weight = 750, lines = 2, at100 = false): NameSet | null {
  if (!b.title) return null;
  const w = Math.max(40, maxW);
  // (1.3) in the title's own size (the layouts round it make room, or make it smaller again)
  const z = at100 ? size : S(b.titleRole, size);
  const ns = nameLines(b.title, o.fit, z, w, weight, lines);
  // wrapped, but still cut: smaller rather than cut, as fit does (these looks are for the name)
  if (o.fit === "wrap" && ns.lines.some((l) => l.endsWith("…"))) return { ...nameLines(b.title, "fit", z, w, weight, lines), role: b.titleRole };
  return { ...ns, role: b.titleRole };
}

/** (1.3) The title made smaller (from its size at 100 %) until its block is no taller than `avail` - only when some text is drawn bigger. */
function fitName(b: NF, o: LookOpts, size: number, maxW: number, weight: number, avail: number): NameSet | null {
  let ns = nameOf(b, o, size, maxW, weight);
  if (!bigger()) return ns;
  // (a bigger title gives way down to its size at 100 %, no further; other bigger text may push it smaller)
  const at1 = T[b.titleRole] > 1 ? nameOf(b, o, size, maxW, weight, 2, true) : null;
  for (let z = size - 1.5; ns && nameH(ns) > avail && z >= 11; z -= 1.5) {
    const c = nameOf(b, o, z, maxW, weight);
    if (at1 && c && c.size < at1.size) {
      if (nameH(at1) < nameH(ns)) ns = at1;
      break;
    }
    ns = c;
  }
  return ns;
}

/** How tall a name block is, from the top of its first line to below its last. */
const nameH = (ns: NameSet | null, lh = 1.1) => (ns ? ns.size * 0.74 + (ns.lines.length - 1) * ns.size * lh + ns.size * 0.24 : 0);

/** The name's lines, the first one's baseline at y. */
function linesSvg(ns: NameSet | null, x: number, y: number, anchor: "start" | "middle" | "end", fill: string, weight = 750, family?: string, lh = 1.1, extra = ""): string {
  if (!ns) return "";
  let s = "";
  ns.lines.forEach((l, k) => {
    const t = text(x, y + k * ns.size * lh, l, { size: ns.size, weight, fill, anchor, family, spacing: -0.2, role: ns.role });
    s += extra ? t.replace("<text ", "<text " + extra + " ") : t;
  });
  return s;
}

interface St {
  words: string;
  unit: string;
  size: number;
  sub: string;
  /** (1.3) The unit's size and words, the sub line's pieces and height, and what the words are. */
  usize?: number;
  utext?: string;
  subParts?: Part[];
  subH?: number;
  role?: TextRole;
  multi?: string;
}

/** (1.3) The height the sub line takes (18 at 100 %). */
const subHOf = (parts: Part[]): number => (parts.length ? 18 + dz(partsSize(parts, 12.5), 12.5) * 0.8 : 18);

/**
 * The status: the state with its unit, at the largest of `sizes` that fits `maxW`; with the state
 * hidden, the detail and the mode in its place. `sub` is the line under it: the detail and the mode.
 * A size small enough that the status and its line fit a band `band` high is chosen first.
 */
function statOf(f: Face, i: Info, sizes: number[], maxW: number, band = 999, weight = 800): St {
  if (!i.state) {
    const parts = subParts(f, i);
    const s = subline(f, i);
    if (!s) return { words: "", unit: "", size: 0, sub: "" };
    const role = parts[0]![1];
    const ok = growAll(sizes.map((a) => Math.max(14, Math.round(a * 0.72))), T[role], (z) => z / 0.72).filter((a) => a * 0.74 <= band);
    const t = fitSize(s, ok.length ? ok : [14], maxW, weight);
    return { words: t.text, unit: "", size: t.size, sub: "", role, ...(parts.length > 1 ? { multi: parts.map((p) => p[1]).join(" ") } : {}) };
  }
  const v = stateText(f);
  const unit = f.unit && f.online ? f.unit : "";
  const subP = f.kind === "thermostat" && f.online ? pairParts(i.detail ? f.detail.replace(/\s*°[CF]$/, "°") : "", i.mode ? f.mode : "") : subParts(f, i);
  const sub = subP.map((p) => p[0]).join("");
  const subH = subHOf(subP);
  const fits = sizes.filter((s) => s * 0.74 + (sub ? 18 : 0) <= band);
  const list = fits.length ? fits : [sizes[sizes.length - 1]!];
  const uw = (s: number) => (unit ? textWidth(fit(unit, 14, 44, 650), Math.max(11, s * 0.5), 600) + 4 : 0);
  const pick = (): { words: string; size: number } => {
    for (const s of list) if (textWidth(v, s, weight) + uw(s) <= maxW) return { words: v, size: s };
    const s = list[list.length - 1]!;
    return { words: fit(v, s, maxW - uw(s), weight), size: s };
  };
  const p0 = pick();
  const extra = { subParts: subP, subH, role: "value" as TextRole };
  const uk = T.unit === 1 ? 1 : S("unit", 14) / 14;
  if (T.value === 1 && uk === 1) return { words: p0.words, unit, size: p0.size, sub, ...extra };
  // (1.3) the value in its own size (as far as the band and the role's limit let it), the unit in its own
  const uz0 = Math.max(11, p0.size * 0.5);
  const grown0 = SS("value", sizes, band < 999 ? null : undefined).filter((z) => z * 0.74 + (sub ? subH : 0) <= band);
  const grown = T.value < 1 && grown0.length ? smallerThan(grown0, p0.size * T.value) : grown0;
  const utext = unit ? fit(unit, 14 * uk, 44 * uk, 650) : "";
  const r = fitWithUnit(v, grown.length ? grown : [Math.min(...SS("value", sizes))], utext, uz0, uz0 * uk, maxW, weight, 600, 4);
  return { words: r.text, unit, size: r.size, sub, ...extra, usize: r.usize, utext };
}

/** The status's words: the unit a smaller tspan, offline in red. */
function statSvg(st: St, f: Face, x: number, y: number, fill: string, unitFill: string, anchor: "start" | "middle" | "end", crit: string = P.crit, family?: string, extra = ""): string {
  if (!st.size) return "";
  const u = st.unit ? `<tspan dx="3" font-size="${n(unitSize(st))}" font-weight="700" fill="${unitFill}"${roleAttr("unit")}>${escText(st.utext ?? fit(st.unit, 14, 44, 650))}</tspan>` : "";
  let t = text(x, y, st.words, { size: st.size, weight: 800, fill: f.online ? fill : crit, anchor, family, spacing: -0.3, role: st.role ?? "value" });
  if (st.multi && roleAttr(st.role)) t = t.replace(roleAttr(st.role), ` data-role="${st.multi}"`);
  return (extra ? t.replace("<text ", "<text " + extra + " ") : t).replace(/<\/text>$/, u + "</text>");
}

/** (1.3) The unit's size beside the status (half the value's at 100 %). */
const unitSize = (st: St): number => st.usize ?? Math.max(11, st.size * 0.5);
/** How wide the status is, its unit with it. */
const statW = (st: St): number => textWidth(st.words, st.size, 800) + (st.unit ? textWidth(st.utext ?? st.unit, unitSize(st), 600) + 4 : 0);

/** The small line under the status, a little smaller before it is cut. */
function subSvg(t: string, x: number, y: number, maxW: number, fill: string, anchor: "start" | "middle" | "end" = "start", size = 12.5, family?: string, parts?: Part[]): string {
  if (!t) return "";
  // (1.3) the detail and the mode each in its own size
  return mixLine(x, y, parts && parts.length ? parts : [[t, "detail"]], [size, size * 0.9, size * 0.82], maxW, { weight: 650, fill, anchor, family }, T, (z) => z * CAPF.detail).svg;
}

/** (1.3) The room under a name in the name-first looks, in its own size. */
function roomSvg(room: string, x: number, y: number, maxW: number, fill: string, size = 12.5, anchor: "start" | "middle" | "end" = "start", family?: string): string {
  const z = S("room", size);
  return text(x, y, fit(room, z, maxW, 600), { size: z, weight: 600, fill, anchor, family, role: "room" });
}
/** How much taller the room line is than at 100 %. */
const roomD = (size = 12.5): number => dz(S("room", size), size) * 0.8;

/** The status and its small line in the band top..bottom, centred in it. Returns the status's baseline. */
function statBlock(f: Face, st: St, x: number, anchor: "start" | "middle" | "end", top: number, bottom: number, maxW: number, fill: string, unitFill: string, subFill: string,
  crit: string = P.crit, family?: string): { svg: string; y: number; end: number } {
  if (!st.size) return { svg: "", y: top, end: top };
  const sh = st.subH ?? 18;
  const sub = st.sub && st.size * 0.74 + sh <= bottom - top + 2 ? st.sub : "";
  const h = st.size * 0.74 + (sub ? sh : 0);
  const y = top + Math.max(0, (bottom - top - h) / 2) + st.size * 0.74;
  return { svg: statSvg(st, f, x, y, fill, unitFill, anchor, crit, family) + (sub ? subSvg(sub, x, y + 17 + (sh - 18), maxW, subFill, anchor, 12.5, family, st.subParts) : ""), y, end: y + (sub ? sh : 0) };
}

interface Col {
  x: number; anchor: "start" | "middle" | "end"; top: number; bottom: number; maxW: number;
  nameFill: string; statFill: string; unitFill: string; subFill: string; roomFill?: string;
  size?: number; weight?: number; family?: string; statSizes?: number[]; gap?: number; crit?: string; nameExtra?: string; statExtra?: string;
}
interface ColOut { svg: string; ns: NameSet | null; st: St; nameTop: number; nameBase: number; nameEnd: number; statY: number; end: number }

/**
 * The name, the room under it when the name takes one line, the status and its small line - stacked
 * and centred in top..bottom. Whatever does not fit goes: the room, then the status gets smaller,
 * then the small line, then the name gets smaller (never under 15 px).
 */
function column(f: Face, o: LookOpts, b: NF, c: Col): ColOut {
  const i = b.i, w = c.weight ?? 750, gap = c.gap ?? 9;
  const sizes = c.statSizes ?? [28, 25, 22, 19, 17, 15];
  let size = c.size ?? 22;
  let ns = nameOf(b, o, size, c.maxW, w);
  let st = statOf(f, i, sizes, c.maxW, 999);
  let room = b.room && ns && ns.lines.length === 1 ? b.room : "";
  let sub = st.sub;
  const H = () => nameH(ns) + (room ? 16 + roomD() : 0) + (st.size ? (ns ? gap : 0) + st.size * 0.74 : 0) + (sub ? st.subH ?? 18 : 0);
  const avail = c.bottom - c.top;
  if (H() > avail) room = "";
  for (const s of sizes) {
    if (H() <= avail || s >= st.size) continue;
    st = { ...statOf(f, i, [s], c.maxW), sub: st.sub };
  }
  if (H() > avail) sub = "";
  while (H() > avail && ns && size > 15.5) {
    size = Math.max(15.5, size - 1.5);
    ns = nameOf(b, o, size, c.maxW, w);
  }
  let y = c.top + Math.max(0, (avail - H()) / 2);
  const nameTop = y;
  let s = "";
  const nameBase = y + (ns ? ns.size * 0.74 : 0);
  if (ns) {
    s += linesSvg(ns, c.x, nameBase, c.anchor, c.nameFill, w, c.family, 1.1, c.nameExtra);
    y += nameH(ns);
  }
  const nameEnd = y;
  if (room) {
    s += roomSvg(room, c.x, y + 12 + roomD(), c.maxW, c.roomFill ?? c.subFill, 12.5, c.anchor, c.family);
    y += 16 + roomD();
  }
  let statY = y;
  if (st.size) {
    statY = y + (ns ? gap : 0) + st.size * 0.74;
    s += statSvg(st, f, c.x, statY, c.statFill, c.unitFill, c.anchor, c.crit, c.family, c.statExtra);
    y = statY;
  }
  if (sub) {
    const sh = st.subH ?? 18;
    s += subSvg(sub, c.x, y + 17 + (sh - 18), c.maxW, c.subFill, c.anchor, 12.5, c.family, st.subParts);
    y += sh;
  }
  return { svg: s, ns, st, nameTop, nameBase, nameEnd, statY, end: y };
}

/** The level as a thin bar along the foot: lit in the accent, else the off colour or grey. */
function footBar(b: NF, x: number, y: number, w: number, h = 4, track: string = P.line): string {
  if (b.lv === null) return "";
  return rect(x, y, w, h, h / 2, track) + rect(x, y, Math.max(h, w * b.lv), h, h / 2, b.lit ? b.base : greyOr(b, P.muted));
}

/** A dashed red edge for an offline key, else a solid one. */
const edge = (f: Face, b: NF, lit: string, grey: string = P.line) => (f.online ? `stroke="${b.lit ? lit : greyOr(b, grey)}"` : `stroke="${P.crit}" stroke-dasharray="6 4"`);

/** Name bar: the name on a coloured band across the top, the status big under it. */
function namebar(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const ns = b.alone ? null : nameOf(b, o, 21, 120, 750);
  const band = ns ? Math.max(42, Math.round(12 + nameH(ns) + 10)) : 24;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  s += rect(0, 0, 144, band, 0, b.lit ? b.base : f.online && b.off ? b.off : P.panel2, !b.lit && b.off ? 'fill-opacity="0.35"' : "");
  s += f.online ? rect(0, band - 3, 144, 3, 0, b.lit ? b.c : greyOr(b, P.line)) : `<path d="M 0 ${band - 1.5} H 144" stroke="${P.crit}" stroke-width="3" stroke-dasharray="6 4"/>`;
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 44, 64, ic, 2) + badges(f, i, DARK, 3, true));
  s += linesSvg(ns, 12, 12 + (ns ? ns.size * 0.74 : 0), "start", b.lit ? P.bg : P.text);
  const room = b.room && ns && ns.lines.length === 1 && band - 12 - nameH(ns) >= 14 ? b.room : "";
  const showLv = b.lv !== null;
  const top = band + 6, bottom = showLv ? 130 : 138;
  const iw = Math.max(i.icon ? 30 : 0, b.bw);
  const st = statOf(f, i, [32, 28, 25, 22, 19, 16], 120 - iw, bottom - top - (room ? 15 : 0));
  const sb = statBlock(f, st, 12, "start", top + (room ? 15 : 0), bottom, 120 - iw, ink(f, b, b.base), P.dim, P.dim);
  if (room) s += roomSvg(room, 12, top + 10, 120, P.dim, 12);
  s += sb.svg;
  if (i.icon) s += icon(f.icon, 110, b.bw ? bottom - 24 : (top + bottom) / 2 - 12, 24, ic, 2.2);
  if (showLv) s += footBar(b, 12, 134, 120);
  s += badges(f, i, DARK, band + 4, true);
  return doc(s);
}

/** Caption: the name centred and big, the status in a pill under it - filled when on. */
function captionLook(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const defs = radial("cg", [[0, b.base, 0.3], [1, b.base, 0]], 0.5, 0.3, 0.7);
  let s = rect(0, 0, 144, 144, 0, X.night);
  if (b.lit) s += rect(0, 0, 144, 144, 0, "url(#cg)");
  else if (b.off) s += rect(0, 0, 144, 144, 0, b.off, 'fill-opacity="0.06"');
  s += frame(DARK, f.online ? (b.lit ? b.c : greyOr(b, P.line)) : P.crit, b.lit ? 0.6 : 1, 1.5, 22);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 12, 11, 20, ic, 2.2);
  const top = i.icon || b.bw ? 34 : 14;
  const st = statOf(f, i, [21, 19, 17, 15], 104);
  const pillH = st.size ? st.size + 10 : 0;
  const ns = fitName(b, o, 22, 124, 750, 138 - top - (pillH ? 6 + pillH : 0));
  let sub = st.sub;
  const lv = b.lv !== null;
  const h = () => nameH(ns) + (pillH ? (ns ? 6 : 0) + pillH : 0) + (sub ? 16 + ((st.subH ?? 18) - 18) : 0);
  if (h() > 138 - top) sub = "";
  let y = top + Math.max(0, (138 - top - h()) / 2);
  s += linesSvg(ns, 72, y + (ns ? ns.size * 0.74 : 0), "middle", P.text);
  y += nameH(ns) + (ns ? 6 : 0);
  if (pillH) {
    const tw = statW(st);
    const pw = Math.min(128, tw + 26);
    const fill = b.lit ? b.base : P.panel2;
    s += rect(72 - pw / 2, y, pw, pillH, pillH / 2, fill, `${!b.lit && b.off ? 'fill-opacity="1"' : ""} ${edge(f, b, b.base, P.muted)} stroke-width="1.8"`);
    if (lv && f.online) s += rect(72 - pw / 2 + 6, y + pillH - 4, Math.max(3, (pw - 12) * b.lv!), 2.5, 1.2, b.lit ? P.bg : greyOr(b, P.dim), b.lit ? 'fill-opacity="0.55"' : "");
    s += statSvg(st, f, 72, y + pillH / 2 + st.size * 0.36, b.lit ? P.bg : f.stateColour ?? b.off ?? P.text, b.lit ? P.panel2 : P.dim, "middle");
    y += pillH;
  }
  if (sub) s += subSvg(sub, 72, y + 14 + ((st.subH ?? 18) - 18), 124, P.dim, "middle", 12.5, undefined, st.subParts);
  s += badges(f, i, DARK, 11, true);
  return doc(s, defs);
}

/** LED: the name big at the top left, a lit lamp and the status word at the foot. */
function led(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const defs = grad("lp", P.panel2, 1, P.bg, 1);
  let s = rect(0, 0, 144, 144, 0, "url(#lp)") + frame(DARK, f.online ? greyOr(b, P.line) : P.crit, 1, 1.5, 18);
  const lamp = b.lit ? b.base : !f.online ? P.crit : b.off ?? P.muted;
  if (b.alone) return doc(s + icon(f.icon, 40, 36, 64, iconInk(f, b, b.base), 2) + `<circle cx="72" cy="118" r="6" fill="${lamp}"/>` + badges(f, i, DARK, 12, true), defs);
  const st = statOf(f, i, [24, 22, 20, 18, 16], 92 - (i.icon ? 26 : 0), 40);
  const hasSt = st.size > 0;
  const statTop = hasSt ? (st.sub ? 92 : 104) : 136;
  const nameTop = b.bw ? 36 : 14;
  const ns = fitName(b, o, 23, 120, 750, statTop - 6 - nameTop);
  const nh = nameH(ns);
  // the name sits at the top; it may take the room's line when it is one line
  s += linesSvg(ns, 14, nameTop + (ns ? ns.size * 0.74 : 0), "start", P.text);
  if (b.room && ns && ns.lines.length === 1 && nameTop + nh + 16 + roomD() < statTop) s += roomSvg(b.room, 14, nameTop + nh + 12 + roomD(), 116, P.dim);
  if (hasSt) {
    const y = Math.max(statTop, nameTop + nh + 6) + st.size * 0.74;
    const cy = y - st.size * 0.36;
    if (b.lit) s += `<circle cx="22" cy="${n(cy)}" r="11" fill="${lamp}" fill-opacity="0.22"/>`;
    s += `<circle cx="22" cy="${n(cy)}" r="6.5" fill="${b.lit || !f.online || b.off ? lamp : P.bg}" stroke="${lamp}" stroke-width="2"/>`;
    if (b.lit) s += `<circle cx="20" cy="${n(cy - 2)}" r="2" fill="${X.white}" fill-opacity="0.6"/>`;
    s += statSvg(st, f, 38, y, ink(f, b, P.text), P.dim, "start");
    if (st.sub && y + (st.subH ?? 18) <= 140) s += subSvg(st.sub, 14, y + (st.subH ?? 18), 120, b.lit ? b.base : P.dim, "start", 12.5, undefined, st.subParts);
  }
  if (i.icon) s += icon(f.icon, 110, hasSt ? (st.sub ? 92 : 106) : 112, 20, iconInk(f, b, b.base), 2.2);
  if (b.lv !== null) s += rect(136, 40, 3, 90, 1.5, P.line) + rect(136, 40 + 90 * (1 - b.lv), 3, Math.max(3, 90 * b.lv), 1.5, b.lit ? b.base : greyOr(b, P.muted));
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Two rows: the name above a hairline, the status below it - the line lit in the accent when on. */
function tworows(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true));
  const st = statOf(f, i, [28, 25, 22, 19, 16], 124, 52);
  const ns = fitName(b, o, 22, 124, 750, (st.size ? 84 : 120) - 8 - (b.bw ? 32 : 8));
  const mid = ns && st.size ? Math.max(64, Math.min(84, (b.bw ? 30 : 10) + nameH(ns) + 14)) : ns ? 120 : 30;
  // the name centred above the line
  const top = b.bw ? 32 : 8;
  s += linesSvg(ns, 72, top + Math.max(0, (mid - 8 - top - nameH(ns)) / 2) + (ns ? ns.size * 0.74 : 0), "middle", P.text);
  // the hairline, broken by the icon in its middle
  const lc = f.online ? (b.lit ? b.c : greyOr(b, P.line)) : P.crit;
  const lw = b.lit ? 2.5 : 1.5;
  if (i.icon) {
    s += `<path d="M 12 ${mid} H 58 M 86 ${mid} H 132" stroke="${lc}" stroke-width="${lw}" stroke-linecap="round"${f.online ? "" : ' stroke-dasharray="5 4"'}/>`;
    s += icon(f.icon, 63, mid - 9, 18, ic, 2.2);
  } else s += `<path d="M 12 ${mid} H 132" stroke="${lc}" stroke-width="${lw}" stroke-linecap="round"${f.online ? "" : ' stroke-dasharray="5 4"'}/>`;
  if (b.lv !== null) s += `<path d="M 12 ${mid} H ${n(12 + 120 * b.lv)}" stroke="${b.lit ? b.base : greyOr(b, P.muted)}" stroke-width="${lw + 1.5}" stroke-linecap="round"/>`;
  const sb = statBlock(f, st, 72, "middle", mid + 10, 138, 124, ink(f, b, b.base), P.dim, P.dim);
  s += sb.svg;
  s += badges(f, i, DARK, 8, true);
  return doc(s);
}

/** Plate: an engraved metal nameplate with four screws, the status in a window set into it. */
function plate(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const defs = grad("pl", P.line, 1, P.panel, 1, 1, 1) + grad("pw", X.night, 1, P.bg, 1);
  let s = rect(0, 0, 144, 144, 0, X.night);
  s += rect(5, 5, 134, 134, 14, "url(#pl)", `${edge(f, b, b.c, P.muted)} stroke-width="${b.lit ? 2.5 : 1.5}"`);
  s += rect(9, 9, 126, 126, 11, "none", `stroke="${X.white}" stroke-opacity="0.07" stroke-width="1"`);
  for (const [x, y] of [[16, 16], [128, 16], [16, 128], [128, 128]] as const) {
    s += `<circle cx="${x}" cy="${y}" r="3.6" fill="${P.panel2}" stroke="${X.night}" stroke-width="1"/><path d="M ${x - 2} ${y + 2} L ${x + 2} ${y - 2}" stroke="${X.night}" stroke-width="1.2"/>`;
  }
  const ic = iconInk(f, b, b.base, P.dim);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true), defs);
  const st = statOf(f, i, [24, 22, 20, 18, 16], i.icon ? 88 : 104, 44);
  const win = st.size ? st.size * 0.74 + (st.sub ? st.subH ?? 18 : 0) + 16 : 0;
  const winTop = 132 - win;
  const top = b.bw ? 34 : 22;
  const ns = fitName(b, o, 22, 116, 800, winTop - 6 - top);
  const ny = top + Math.max(0, (winTop - 6 - top - nameH(ns)) / 2) + (ns ? ns.size * 0.74 : 0);
  // engraved: a dark cut under light letters
  s += linesSvg(ns, 72, ny + 1.2, "middle", X.night, 800);
  s += linesSvg(ns, 72, ny, "middle", b.lit ? P.text : X.silver, 800);
  if (i.icon && b.bw === 0 && ny - (ns?.size ?? 0) * 0.74 > 40) s += icon(f.icon, 62, 14, 20, ic, 2.2);
  if (win) {
    s += rect(16, winTop, 112, win, 8, "url(#pw)", `${edge(f, b, b.base)} stroke-width="1.5"`);
    if (b.lit) s += rect(17, winTop + 1, 110, win - 2, 7, b.base, 'fill-opacity="0.14"');
    else if (b.off) s += rect(17, winTop + 1, 110, win - 2, 7, b.off, 'fill-opacity="0.12"');
    const inWin = i.icon && !(b.bw === 0 && ny - (ns?.size ?? 0) * 0.74 > 40);
    s += statBlock(f, st, inWin ? 80 : 72, "middle", winTop + 8, winTop + win - 8, inWin ? 88 : 104, ink(f, b, b.base), P.dim, P.dim).svg;
    if (inWin) s += icon(f.icon, 22, winTop + win / 2 - 8, 16, ic, 2.2);
    if (b.lv !== null) s += footBar(b, 24, winTop + win - 5, 96, 2.5, P.panel2);
  }
  s += badges(f, i, DARK, 10, true);
  return doc(s, defs);
}

/** Ticker: the name over a strip along the foot that carries the status - lit in the accent when on. */
function ticker(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  const iw = i.icon ? 30 : 0;
  const st = b.alone ? null : statOf(f, i, [26, 24, 22, 20, 18], 122 - iw);
  const strip = st && st.size ? 46 : 14;
  const sy = 144 - strip;
  s += rect(0, sy, 144, strip, 0, b.lit ? b.base : P.panel2);
  if (b.off) s += rect(0, sy, 144, strip, 0, b.off, 'fill-opacity="0.3"');
  // the strip's top edge: lit as far as the level
  if (!f.online) s += `<path d="M 0 ${sy + 1.5} H 144" stroke="${P.crit}" stroke-width="3" stroke-dasharray="6 4"/>`;
  else if (b.lv !== null) s += rect(0, sy, 144, 4, 0, b.lit ? P.bg : P.line, b.lit ? 'fill-opacity="0.3"' : "") + rect(0, sy, Math.max(4, 144 * b.lv), 4, 0, b.lit ? X.white : greyOr(b, P.muted), b.lit ? 'fill-opacity="0.7"' : "");
  else s += rect(0, sy, 144, 3, 0, b.lit ? b.c : greyOr(b, P.muted));
  const ic = b.lit ? P.bg : !f.online ? P.crit : b.off ?? P.dim;
  if (b.alone) return doc(s + icon(f.icon, 40, 28, 64, iconInk(f, b, b.base), 2) + badges(f, i, DARK, 12, true));
  if (i.icon) s += icon(f.icon, 110, sy + strip / 2 - 11, 22, ic, 2.2);
  const top = b.bw ? 34 : 10;
  const sub = st!.sub;
  const ns = fitName(b, o, 22, 124, 750, sy - 4 - top - (sub ? st!.subH ?? 18 : 0));
  const room = b.room && ns && ns.lines.length === 1 ? b.room : "";
  const sh = st!.subH ?? 18;
  const extra = (sub ? sh : 0) + (room ? 16 + roomD() : 0);
  const nb = sy - 4;
  let y = top + Math.max(0, (nb - top - nameH(ns) - extra) / 2);
  s += linesSvg(ns, 12, y + (ns ? ns.size * 0.74 : 0), "start", P.text);
  y += nameH(ns);
  if (room && y + 16 + roomD() <= nb - (sub ? sh : 0)) {
    s += roomSvg(room, 12, y + 12 + roomD(), 120, P.dim);
    y += 16 + roomD();
  }
  if (sub && y + 16 + (sh - 18) <= nb) s += subSvg(sub, 12, y + 15 + (sh - 18), 120, b.lit ? b.base : P.dim, "start", 12.5, undefined, st!.subParts);
  if (st!.size) s += statSvg(st!, f, 12, sy + strip / 2 + 1.5 + st!.size * 0.36, b.lit ? P.bg : f.stateColour ?? b.off ?? P.text, b.lit ? P.panel2 : P.dim, "start");
  s += badges(f, i, DARK, 10, true);
  return doc(s);
}

/** Card: the name across the top of a card, an icon tile and the status side by side under it. */
function card(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(4, 4, 136, 136, 16, P.panel, `${edge(f, b, b.c)} stroke-width="${b.lit ? 2 : 1.2}"`);
  const ic = iconInk(f, b, b.lit ? P.bg : b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, iconInk(f, b, b.base), 2) + badges(f, i, DARK, 10, true));
  const x = i.icon ? 52 : 14, w = 132 - x;
  const st = statOf(f, i, [26, 23, 20, 18, 16], w, 44);
  const rowH = Math.max(i.icon ? 34 : 0, st.size ? st.size * 0.74 + (st.sub ? st.subH ?? 18 : 0) : 0);
  const rowTop = 132 - rowH;
  if (i.icon) {
    const ty = rowTop + rowH / 2 - 17;
    s += rect(12, ty, 34, 34, 10, b.lit ? b.base : P.panel2, !b.lit && b.off ? `stroke="${b.off}" stroke-width="1.5"` : "");
    if (b.lv !== null) s += rect(12, ty + 34 * (1 - b.lv), 34, 34 * b.lv, 10, b.lit ? X.white : greyOr(b, P.muted), `fill-opacity="${b.lit ? 0.25 : 0.35}"`);
    s += icon(f.icon, 18, ty + 6, 22, ic, 2.2);
  }
  if (st.size) s += statBlock(f, st, x, "start", rowTop, 132, Math.min(126 - x + 6, w + 6), ink(f, b, b.base), P.dim, P.dim).svg;
  const top = b.bw ? 32 : 14;
  const ns = fitName(b, o, 22, 118, 800, rowTop - 8 - top);
  const room = b.room && ns && ns.lines.length === 1 ? b.room : "";
  const H = nameH(ns) + (room ? 16 + roomD() : 0);
  const y = top + Math.max(0, (rowTop - 8 - top - H) / 2);
  s += linesSvg(ns, 14, y + (ns ? ns.size * 0.74 : 0), "start", P.text, 800);
  if (room && y + H <= rowTop - 4) s += roomSvg(room, 14, y + nameH(ns) + 12 + roomD(), 116, P.dim);
  if (ns && rowH) s += `<path d="M 14 ${n(rowTop - 7)} H 130" stroke="${P.line}" stroke-width="1"/>`;
  s += badges(f, i, DARK, 9, true);
  return doc(s);
}

/** Halves: the name on the dark top half, the status on the bottom half - filled with the accent when on. */
function halves(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, P.bg);
  const ic = iconInk(f, b, b.base);
  const st = b.alone ? null : statOf(f, i, [28, 25, 22, 19, 16], 124, 50);
  const ns = b.alone ? null : fitName(b, o, 22, 126, 750, (!st?.size ? 120 : 82) - 4 - (b.bw ? 30 : 6));
  const mid = !ns ? 50 : !st?.size ? 120 : Math.max(66, Math.min(82, Math.round((b.bw ? 30 : 8) + nameH(ns) + 10)));
  const fill = b.lit ? b.base : P.panel2;
  s += rect(0, mid, 144, 144 - mid, 0, fill);
  if (b.off) s += rect(0, mid, 144, 144 - mid, 0, b.off, 'fill-opacity="0.32"');
  if (!f.online) s += `<path d="M 0 ${mid + 1.5} H 144" stroke="${P.crit}" stroke-width="3" stroke-dasharray="6 4"/>`;
  if (b.lv !== null) s += rect(0, mid, 144 * b.lv, 4, 0, b.lit ? P.bg : greyOr(b, P.muted), b.lit ? 'fill-opacity="0.35"' : "");
  if (b.alone) return doc(s + icon(f.icon, 40, 30, 64, ic, 2) + badges(f, i, DARK, 12, true));
  const top = b.bw ? 30 : 6;
  s += linesSvg(ns, 72, top + Math.max(0, (mid - 4 - top - nameH(ns)) / 2) + (ns ? ns.size * 0.74 : 0), "middle", P.text);
  if (i.icon) s += `<g opacity="${b.lit ? 0.28 : 0.4}">` + icon(f.icon, 112, 112, 30, b.lit ? P.bg : ic, 2) + `</g>`;
  if (st) s += statBlock(f, st, 72, "middle", mid + 8, 140, 124, b.lit ? P.bg : f.stateColour ?? b.off ?? P.text, b.lit ? P.panel2 : P.dim, b.lit ? P.bg : P.dim).svg;
  s += badges(f, i, DARK, 8, true);
  return doc(s);
}

/** Stacked: the name, the status under it in the accent, a tiny icon at the foot - all centred. */
function stacked(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const defs = grad("sg", b.lit ? b.base : b.off ?? P.panel2, b.lit ? 0.28 : b.off ? 0.16 : 0.9, X.night, 0);
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(0, 0, 144, 144, 0, "url(#sg)");
  s += rect(52, 0, 40, 4, 2, f.online ? (b.lit ? b.c : greyOr(b, P.line)) : P.crit);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true), defs);
  const foot = i.icon || b.lv !== null;
  const col = column(f, o, b, { x: 72, anchor: "middle", top: b.bw ? 32 : 10, bottom: foot ? 118 : 136, maxW: 126, size: 23, nameFill: P.text, statFill: ink(f, b, b.base), unitFill: P.dim, subFill: P.dim, gap: 7 });
  s += col.svg;
  if (i.icon) s += icon(f.icon, 64, 121, 16, ic, 2.2);
  if (b.lv !== null) s += footBar(b, 44, 139, 56, 3);
  s += badges(f, i, DARK, 8, true);
  return doc(s, defs);
}

/** Corner: the name full and big, the status in a badge tucked into the bottom right corner. */
function corner(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, P.bg) + frame(DARK, f.online ? greyOr(b, P.line) : P.crit, 1, 1.5, 18);
  const ic = iconInk(f, b, b.base);
  const st = b.alone ? null : statOf(f, i, [24, 22, 20, 18, 16], 112, 40);
  let bh = 0, bwid = 0;
  if (st && st.size) {
    const tw = statW(st);
    const sw = st.sub ? Math.min(118, textWidth(st.sub, partsSize(st.subParts ?? [], 12), 650)) : 0;
    bwid = Math.min(130, Math.max(54, tw, sw) + 24);
    bh = st.size * 0.74 + (st.sub ? st.subH ?? 18 : 0) + 20;
  }
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true));
  if (i.icon) s += icon(f.icon, 13, 12, 20, ic, 2.2);
  const top = i.icon || b.bw ? 36 : 14;
  const nb = 144 - bh - 4;
  const ns = fitName(b, o, 24, 120, 800, nb - top);
  const ny = top + Math.max(0, Math.min((nb - top - nameH(ns)) / 2, 6)) + (ns ? ns.size * 0.74 : 0);
  s += linesSvg(ns, 13, ny, "start", P.text, 800);
  if (b.room && ns && ns.lines.length === 1 && ny + 20 + roomD() < nb) s += roomSvg(b.room, 13, ny + 19 + roomD(), 118, P.dim);
  if (bh) {
    const x0 = 144 - bwid, y0 = 144 - bh;
    s += `<path d="M ${n(x0)} 144 V ${n(y0 + 16)} Q ${n(x0)} ${n(y0)} ${n(x0 + 16)} ${n(y0)} H 144 V 144 Z" fill="${b.lit ? b.base : P.panel2}"/>`;
    if (b.off) s += `<path d="M ${n(x0)} 144 V ${n(y0 + 16)} Q ${n(x0)} ${n(y0)} ${n(x0 + 16)} ${n(y0)} H 144 V 144 Z" fill="${b.off}" fill-opacity="0.35" stroke="${b.off}" stroke-width="1.5"/>`;
    if (!f.online) s += `<path d="M ${n(x0)} 144 V ${n(y0 + 16)} Q ${n(x0)} ${n(y0)} ${n(x0 + 16)} ${n(y0)} H 144" fill="none" stroke="${P.crit}" stroke-width="2" stroke-dasharray="5 4"/>`;
    const y = y0 + 12 + st!.size * 0.74;
    s += statSvg(st!, f, 132, y, b.lit ? P.bg : f.stateColour ?? b.off ?? P.text, b.lit ? P.panel2 : P.dim, "end");
    if (st!.sub) s += subSvg(st!.sub, 132, y + 17 + ((st!.subH ?? 18) - 18), bwid - 22, b.lit ? P.bg : P.dim, "end", 12, undefined, st!.subParts);
    if (b.lv !== null) s += rect(x0 + 10, 139, (bwid - 20) * b.lv, 2.5, 1.2, b.lit ? P.bg : greyOr(b, P.muted), b.lit ? 'fill-opacity="0.5"' : "");
  }
  s += badges(f, i, DARK, 11, true);
  return doc(s);
}

/** Lined: the name with an accent line under it - as wide as the name when on, the level when dimmed, a stub when off. */
function lined(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.night);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + rect(44, 116, 56, 5, 2.5, b.lit ? b.base : !f.online ? P.crit : b.off ?? P.line) + badges(f, i, DARK, 12, true));
  if (i.icon) s += icon(f.icon, 14, 12, 20, ic, 2.2);
  const col = column(f, o, { ...b, room: "" }, { x: 14, anchor: "start", top: i.icon || b.bw ? 36 : 14, bottom: 136, maxW: 118, size: 23, weight: 800, nameFill: P.text, statFill: ink(f, b, P.text), unitFill: P.dim, subFill: P.dim, gap: 16, statSizes: [26, 23, 20, 18, 16] });
  if (col.ns) {
    const nw = Math.min(118, Math.max(...col.ns.lines.map((l) => textWidth(l, col.ns!.size, 800))));
    const y = col.nameEnd + 3;
    // (1.3) the level, else the name's width when on - but not under a number with no range, where it would read as full
    const w = b.lit ? (b.lv !== null ? Math.max(14, nw * b.lv) : onFill(f, true) ? nw : 22) : 22;
    if (b.lit && b.lv !== null) s += rect(14, y, nw, 5, 2.5, P.line);
    s += f.online ? rect(14, y, w, 5, 2.5, b.lit ? b.c : greyOr(b, P.muted)) : `<path d="M 14 ${n(y + 2.5)} H ${n(14 + nw)}" stroke="${P.crit}" stroke-width="3" stroke-dasharray="5 4"/>`;
  }
  s += col.svg;
  s += badges(f, i, DARK, 11, true);
  return doc(s);
}

/** Terminal: a little console window - the name, then "> status" in the accent with a block cursor when on. */
function terminal(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const green = b.lit ? b.base : !f.online ? P.crit : b.off ?? P.dim;
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(3, 3, 138, 138, 12, P.bg, `${edge(f, b, b.c)} stroke-width="1.5"`);
  s += `<path d="M 3 22 H 141" stroke="${P.line}" stroke-width="1"/>`;
  // the level: a progress line under the title bar
  if (b.lv !== null) s += rect(4, 21, Math.max(2, 136 * b.lv), 2.5, 0, green);
  for (const [x, c] of [[15, P.crit], [27, P.warn], [39, P.ok]] as const) s += `<circle cx="${x}" cy="12.5" r="3.5" fill="${c}" fill-opacity="${b.lit ? 0.9 : 0.4}"/>`;
  if (b.alone) return doc(s + icon(f.icon, 42, 44, 60, iconInk(f, b, b.base), 2) + badges(f, i, DARK, 3.5, true));
  if (i.icon) s += icon(f.icon, 118, 5, 15, iconInk(f, b, b.base), 2.2);
  // a monospace letter is wider than our measure of most letters: measure against less
  const k = 0.86;
  const ns = nameOf(b, o, 21, 120 * k, 700);
  const st = statOf(f, i, [22, 20, 18, 16], (120 - 16) * k, 50);
  const sub = st.sub;
  const H = nameH(ns) + (st.size ? 10 + st.size * 0.74 : 0) + (sub ? st.subH ?? 18 : 0);
  let y = 30 + Math.max(0, (138 - 30 - H) / 2);
  s += linesSvg(ns, 12, y + (ns ? ns.size * 0.74 : 0), "start", P.text, 700, MONO, 1.12);
  y += nameH(ns, 1.12);
  if (st.size) {
    y += 10 + st.size * 0.74;
    s += text(12, y, ">", { size: st.size, weight: 800, fill: green, family: MONO, role: st.role ?? "value" });
    s += statSvg(st, f, 12 + st.size * 0.75, y, green, P.dim, "start", P.crit, MONO);
    const cx = 12 + st.size * 0.75 + statW(st) / k + 4;
    if (b.lit && cx < 128) s += rect(cx, y - st.size * 0.72, st.size * 0.5, st.size * 0.82, 1, green, 'fill-opacity="0.75"');
  }
  if (sub && y + (st.subH ?? 18) <= 140) s += subSvg(sub, 12, y + 17 + ((st.subH ?? 18) - 18), 120 * k, P.dim, "start", 12, MONO, st.subParts);
  s += badges(f, i, DARK, 3.5, true);
  return doc(s);
}

/** Marquee: the name in lights - a ring of bulbs, lit in the accent when on - the status under it. */
function marquee(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(4, 4, 136, 136, 14, P.panel2) + rect(16, 16, 112, 112, 8, P.bg, `${edge(f, b, b.c)} stroke-width="1.2"`);
  // (1.3) as many bulbs as the level, all when on with no level - none under a number with no range
  const on = b.lit ? b.lv ?? onFill(f, true) : 0;
  const pts: [number, number][] = [];
  for (let k = 0; k < 9; k++) pts.push([10 + k * 15.5, 10]);
  for (let k = 1; k < 9; k++) pts.push([134, 10 + k * 15.5]);
  for (let k = 7; k >= 0; k--) pts.push([10 + k * 15.5, 134]);
  for (let k = 8; k >= 1; k--) pts.push([10, 10 + k * 15.5]);
  pts.forEach(([x, y], k) => {
    const lit = b.lit && k < Math.round(pts.length * on);
    if (lit) s += `<circle cx="${n(x)}" cy="${n(y)}" r="4.6" fill="${b.base}" fill-opacity="0.3"/>`;
    s += `<circle cx="${n(x)}" cy="${n(y)}" r="2.6" fill="${lit ? b.base : !f.online ? P.crit : b.off ?? P.line}"${!f.online ? ' fill-opacity="0.6"' : ""}/>`;
  });
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 42, 42, 60, ic, 2) + badges(f, i, DARK, 12, true));
  const foot = i.icon;
  const col = column(f, o, b, { x: 72, anchor: "middle", top: b.bw ? 34 : 20, bottom: foot ? 108 : 124, maxW: 104, size: 21, nameFill: b.lit ? X.white : P.text, statFill: ink(f, b, b.base), unitFill: P.dim, subFill: P.dim, gap: 7, statSizes: [24, 22, 20, 18, 16] });
  s += col.svg;
  if (foot) s += icon(f.icon, 64, 108, 16, ic, 2.2);
  s += badges(f, i, DARK, 13, true);
  return doc(s);
}

/** Widget: a phone-widget card - an icon chip and the status at the top, the name big at the foot. */
function widget(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const defs = b.lit ? grad("wg", b.base, 0.34, b.base, 0.1, 1, 1) : grad("wg", P.panel2, 1, P.panel, 1, 1, 1);
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(4, 4, 136, 136, 22, P.bg) + rect(4, 4, 136, 136, 22, "url(#wg)", `${edge(f, b, b.c)} stroke-width="1.2"`);
  if (b.off) s += rect(4, 4, 136, 136, 22, b.off, 'fill-opacity="0.1"');
  const ic = iconInk(f, b, b.lit ? P.bg : b.base);
  if (b.alone) return doc(s + `<circle cx="72" cy="72" r="38" fill="${b.lit ? b.base : P.panel2}"/>` + icon(f.icon, 50, 50, 44, ic, 2.2) + badges(f, i, DARK, 12, true), defs);
  let y = 14;
  if (i.icon) {
    s += `<circle cx="27" cy="27" r="14" fill="${b.lit ? b.base : P.panel2}"${!b.lit && b.off ? ` stroke="${b.off}" stroke-width="1.5"` : ""}/>` + icon(f.icon, 19, 19, 16, ic, 2.2);
    y = 44;
  } else if (b.bw) y = 36;
  const st = statOf(f, i, [20, 18, 17, 16, 15], 116, 40);
  const ns = fitName(b, o, 23, 120, 800, 134 - 8 - y - st.size * 0.74);
  // the name at the foot, the status over it
  const nameTop = 134 - nameH(ns);
  const sd = (st.subH ?? 18) - 18;
  const sub = st.sub && nameTop - 6 - (y + st.size * 0.74) >= 17 + sd ? st.sub : "";
  if (st.size) {
    const sy = Math.min(nameTop - 8 - (sub ? 17 + sd : 0), Math.max(y + st.size * 0.74, nameTop - 8 - (sub ? 17 + sd : 0)));
    s += statSvg(st, f, 16, sy, b.lit ? (f.stateColour ?? X.white) : f.stateColour ?? b.off ?? P.dim, b.lit ? P.text : P.muted, "start");
    if (sub) s += subSvg(sub, 16, sy + 16 + sd, 112, b.lit ? P.text : P.dim, "start", 12, undefined, st.subParts);
  }
  s += linesSvg(ns, 16, nameTop + (ns ? ns.size * 0.74 : 0), "start", b.lit ? X.white : P.text, 800);
  if (b.lv !== null) s += footBar(b, 16, 136, 112, 3);
  s += badges(f, i, DARK, 12, true);
  return doc(s, defs);
}

/** Sign: a road sign - in the accent with a dark inner border when on, grey when off - the name on it, the status under a rule. */
function sign(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const fill = b.lit ? b.base : P.panel2;
  const fg = b.lit ? P.bg : P.text;
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(3, 3, 138, 138, 16, fill);
  if (b.off) s += rect(3, 3, 138, 138, 16, b.off, 'fill-opacity="0.3"');
  s += rect(8, 8, 128, 128, 11, "none", f.online ? `stroke="${b.lit ? P.bg : b.off ?? P.dim}" stroke-width="2.5"` : `stroke="${P.crit}" stroke-width="2.5" stroke-dasharray="6 4"`);
  const ic = b.lit ? P.bg : !f.online ? P.crit : b.off ?? P.dim;
  if (b.alone) return doc(s + icon(f.icon, 42, 42, 60, ic, 2.2) + badges(f, i, DARK, 12, true));
  const st = statOf(f, i, [24, 22, 20, 18, 16], 112, 44);
  const lower = st.size ? st.size * 0.74 + (st.sub ? st.subH ?? 18 : 0) + 16 : 0;
  const rule = 130 - lower;
  if (i.icon) s += icon(f.icon, 62, 14, 20, ic, 2.2);
  const top = i.icon || b.bw ? 36 : 16;
  const ns = fitName(b, o, 22, 112, 800, rule - 4 - top);
  s += linesSvg(ns, 72, top + Math.max(0, (rule - 4 - top - nameH(ns)) / 2) + (ns ? ns.size * 0.74 : 0), "middle", fg, 800);
  if (lower) {
    s += `<path d="M 16 ${n(rule)} H 128" stroke="${fg}" stroke-opacity="0.45" stroke-width="1.5"/>`;
    if (b.lv !== null) s += `<path d="M 16 ${n(rule)} H ${n(16 + 112 * b.lv)}" stroke="${fg}" stroke-width="3" stroke-linecap="round"/>`;
    s += statBlock(f, st, 72, "middle", rule + 8, 130, 112, b.lit ? P.bg : f.stateColour ?? b.off ?? P.text, b.lit ? P.panel2 : P.dim, b.lit ? P.panel2 : P.dim).svg;
  }
  s += badges(f, i, DARK, 12, true);
  return doc(s);
}

/** Note: a ruled index card with a red margin - the name in ink, the status marked with a highlighter when on. */
function note(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i, ink2 = PAPER;
  let s = rect(0, 0, 144, 144, 0, X.paper2) + rect(3, 3, 138, 138, 6, X.paper, f.online ? `stroke="${b.lit ? b.c : greyOr(b, X.paperLine)}" stroke-width="${b.lit || b.off ? 2.5 : 1}"` : `stroke="${X.inkCrit}" stroke-width="2" stroke-dasharray="6 4"`);
  for (let y = 36; y < 140; y += 22) s += `<path d="M 4 ${y} H 140" stroke="${X.paperLine}" stroke-width="1"/>`;
  s += `<path d="M 16 4 V 140" stroke="${P.crit}" stroke-opacity="0.55" stroke-width="1.2"/>`;
  const ic = b.lit ? b.c : !f.online ? X.inkCrit : b.off ?? X.inkMuted;
  if (b.alone) return doc(s + icon(f.icon, 42, 40, 60, ic, 2) + badges(f, i, ink2, 12, true));
  const col = column(f, o, b, { x: 24, anchor: "start", top: b.bw ? 34 : 12, bottom: 136, maxW: 112, size: 22, weight: 750, nameFill: X.ink, statFill: f.stateColour && b.lit ? f.stateColour : b.lit ? X.ink : b.off ?? X.inkDim, unitFill: X.inkDim, subFill: X.inkDim, crit: X.inkCrit, statSizes: [24, 22, 20, 18, 16], gap: 10 });
  // the highlighter behind the status
  if (col.st.size && f.online) {
    const tw = statW(col.st);
    const hl = b.lit ? b.base : b.off;
    if (hl) s += rect(20, col.statY - col.st.size * 0.62, Math.min(118, tw + 10), col.st.size * 0.72, 3, hl, `fill-opacity="${b.lit ? 0.42 : 0.3}"`);
    if (b.lv !== null) s += rect(20, col.statY + 4, Math.min(118, tw + 10) * b.lv, 2.5, 1.2, b.lit ? b.base : greyOr(b, X.inkMuted));
  }
  s += col.svg;
  if (i.icon) s += icon(f.icon, 118, 114, 16, ic, 2);
  s += badges(f, i, ink2, 10, true);
  return doc(s);
}

/** Pass: a lanyard pass - a slot at the top, a coloured band with the status, the name big under it. */
function pass(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  let s = rect(0, 0, 144, 144, 0, X.night) + rect(8, 4, 128, 136, 12, P.panel, `${edge(f, b, b.c)} stroke-width="1.2"`);
  s += rect(58, 10, 28, 6, 3, X.night);
  const ic = iconInk(f, b, b.lit ? P.bg : b.base);
  const st = b.alone ? null : statOf(f, i, [22, 20, 18, 16], i.icon ? 84 : 108);
  const bandH = st && st.size ? 36 : 14;
  s += rect(9, 22, 126, bandH, 0, b.lit ? b.base : P.panel2);
  if (b.off) s += rect(9, 22, 126, bandH, 0, b.off, 'fill-opacity="0.35"');
  if (b.lv !== null) s += rect(9, 22 + bandH - 3, 126 * b.lv, 3, 0, b.lit ? P.bg : greyOr(b, P.muted), b.lit ? 'fill-opacity="0.35"' : "");
  if (b.alone) return doc(s + icon(f.icon, 44, 66, 56, iconInk(f, b, b.base), 2) + badges(f, i, DARK, 2, true));
  if (i.icon) s += icon(f.icon, 17, 22 + bandH / 2 - 9, 18, ic, 2.2);
  if (st && st.size) s += statSvg(st, f, i.icon ? 42 : 72, 22 + bandH / 2 + st.size * 0.36, b.lit ? P.bg : f.stateColour ?? b.off ?? P.text, b.lit ? P.panel2 : P.dim, i.icon ? "start" : "middle");
  const top = 22 + bandH + 6;
  const ns = fitName(b, o, 22, 116, 800, 134 - top - (st?.sub ? st.subH ?? 18 : 0));
  const sub = st?.sub ?? "";
  const roomOk = b.room && ns && ns.lines.length === 1;
  const sd = (st?.subH ?? 18) - 18;
  const extra = (sub ? 17 + sd : 0) + (roomOk ? 16 + roomD() : 0);
  const avail = 134 - top;
  const H = nameH(ns) + extra;
  let y = top + Math.max(0, (avail - Math.min(H, avail)) / 2);
  s += linesSvg(ns, 72, y + (ns ? ns.size * 0.74 : 0), "middle", P.text, 800);
  y += nameH(ns);
  if (roomOk && y + 16 + roomD() <= 134) {
    s += roomSvg(b.room, 72, y + 12 + roomD(), 112, P.dim, 12.5, "middle");
    y += 16 + roomD();
  }
  if (sub && y + 15 + sd <= 138) s += subSvg(sub, 72, y + 14 + sd, 112, b.lit ? b.base : P.dim, "middle", 12, undefined, st?.subParts);
  s += badges(f, i, DARK, 2, true);
  return doc(s);
}

/** Glow: the name itself glows in the accent when on, the status under it in the accent. */
function glow(f: Face, o: LookOpts): string {
  const b = nf(f, o), i = b.i;
  const defs = radial("gw", [[0, b.base, 0.22], [1, b.base, 0]], 0.5, 0.42, 0.6);
  let s = rect(0, 0, 144, 144, 0, X.night);
  if (b.lit) s += rect(0, 0, 144, 144, 0, "url(#gw)");
  s += f.online && b.lv !== null ? footBar(b, 30, 137.5, 84, 3) : rect(30, 138, 84, 2, 1, f.online ? (b.lit ? b.c : greyOr(b, P.line)) : P.crit);
  const ic = iconInk(f, b, b.base);
  if (b.alone) return doc(s + icon(f.icon, 40, 40, 64, ic, 2) + badges(f, i, DARK, 12, true), defs);
  if (i.icon) s += icon(f.icon, 64, b.bw ? 34 : 10, 16, ic, 2.2);
  const halo = b.lit ? `stroke="${b.base}" stroke-opacity="0.3" stroke-width="4" stroke-linejoin="round"` : "";
  const top = i.icon ? (b.bw ? 54 : 30) : b.bw ? 34 : 12;
  const st = statOf(f, i, [22, 20, 18, 16, 15], 124, 40);
  const lowerH = st.size ? 8 + st.size * 0.74 + (st.sub ? st.subH ?? 18 : 0) : 0;
  // (1.3) bigger text than the key holds: the name smaller first
  const ns = fitName(b, o, 22, 124, 750, 132 - top - lowerH);
  const H = nameH(ns) + lowerH;
  let y = top + Math.max(0, (132 - top - H) / 2);
  const ny = y + (ns ? ns.size * 0.74 : 0);
  if (halo) s += linesSvg(ns, 72, ny, "middle", b.base, 750, undefined, 1.1, halo);
  s += linesSvg(ns, 72, ny, "middle", b.lit ? X.white : b.off ?? P.text);
  y += nameH(ns);
  if (st.size) {
    const sy = y + 8 + st.size * 0.74;
    s += statSvg(st, f, 72, sy, ink(f, b, b.base), P.dim, "middle");
    if (st.sub && sy + (st.subH ?? 18) <= 140) s += subSvg(st.sub, 72, sy + 17 + ((st.subH ?? 18) - 18), 124, P.dim, "middle", 12, undefined, st.subParts);
  }
  s += badges(f, i, DARK, 10, true);
  return doc(s, defs);
}

const LOOKS: Record<string, (f: Face, o: LookOpts) => string> = {
  minimal, bigvalue, fill: solid, neon, ring, split, glass, label, dot, light, contrast,
  huge, pill, orb, tile, gauge, bars, wave, aurora, outline, mono,
  diagonal, hex, stripe, switch: toggle, lcd, dial, ticket, bubble, frame: brackets, shadow, line, tube, stamp, pastel, carbon, grid, tab, rise, spot, button,
  namebar, caption: captionLook, led, tworows, plate, ticker, card, halves, stacked, corner, lined, terminal, marquee, widget, sign, note, pass, glow,
};

/** A key in one of the looks (not Classic, which render.ts draws as 1.0 did). */
export function renderLook(theme: string, f: Face, o: LookOpts): string {
  const draw = LOOKS[theme] ?? bigvalue;
  const i = o.info;
  // nothing at all would be a blank key: the icon at least
  const info = i.icon || i.name || i.state || i.room || i.detail || i.mode || i.graph ? i : { ...i, icon: true };
  const was = T;
  T = o.ts ?? ONE;
  try {
    const svg = draw(f, { ...o, info });
    return f.badge ? svg.replace(/<\/svg>$/, unreadPill(f, f.badge, 8, T.badge) + "</svg>") : svg;
  } finally {
    T = was;
  }
}

/** (1.3) The unread pill: the count on the accent, left of any lock or hand badge, ringed in the key's dark. */
export function unreadPill(f: Pick<Face, "allowed" | "online" | "hold" | "accent">, count: number, top = 8, k = 1): string {
  const t = count > 99 ? "99+" : String(Math.max(0, Math.round(count)));
  // (1.3) the count in the badge's own size, the pill round it
  const z = grow(13, k, 13 * CAPF.badge), d = z - 13;
  const w = Math.max(24 + d, textWidth(t, z, 800) + 14);
  const shift = (f.allowed ? 0 : 22) + (f.online ? 0 : 22) + (f.hold ? 22 : 0);
  const x = 136 - shift - w;
  return rect(x - 2, top - 2, w + 4, 26 + d, 13 + d / 2, P.bg)
    + rect(x, top, w, 22 + d, 11 + d / 2, f.online ? f.accent : P.crit)
    + text(x + w / 2, top + 15.5 + d * 0.75, t, { size: z, weight: 800, fill: P.bg, anchor: "middle", role: "badge" });
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
