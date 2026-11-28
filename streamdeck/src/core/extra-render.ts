/**
 * (1.3, ZIGMon 5.59.4) The Classic drawing of the ten new actions, in the dashboard's style of the
 * other keys (a dark panel, one accent, a stroke icon in a tinted tile, the one thing that matters
 * big), and their touch strips. Each is drawn from a Summary (extra.ts); the other 41 looks draw
 * the same Summary as a Face. Every piece of text passes through text() (escaped), every colour
 * comes from palette.ts or the user's own setting.
 */
import { P } from "./palette.js";
import { fitSized, keySvg, sized, sparkline, type ClassicOpts } from "./render.js";
import { arcPath, dataUri, fit, fitSize, icon, n, nameLines, ONE, rect, roleAttr, svgDoc, text, textWidth, type TextScale } from "./svg.js";
import { graph, type Info } from "./themes.js";
import { POWER_SCALE, type Summary, type Tone } from "./extra.js";
import type { Feedback } from "./strip.js";

const SHOW: Info = { icon: true, name: true, room: true, state: true, detail: true, mode: true, graph: true, battery: true, scale: false, target: false };
const INK = { bg: P.bg, bg2: P.panel2, line: P.line, text: P.text, dim: P.dim, muted: P.muted, crit: P.crit, warn: P.warn, badge: P.bg };

/** The colour of a tone: lit ones the summary's accent, all good green, idle grey (or the user's Off colour). */
export function toneColour(s: Summary): string {
  if (!s.online) return P.crit;
  if (s.active) return s.accent;
  if (s.offAccent) return s.offAccent;
  const t: Record<Tone, string> = { ok: P.ok, warn: P.warn, crit: P.crit, info: s.accent, idle: P.muted };
  return t[s.tone];
}

/** The icon tile: tinted with its colour when lit, in the Off colour when one is set, else a quiet panel. */
function tile(s: Summary, x = 14, y = 14, size = 46, iconName = s.icon): string {
  const c = toneColour(s);
  const lit = s.active && s.online;
  const tinted = lit || !!s.offAccent || s.tone === "ok" || !s.online;
  const fillOp = lit ? 0.2 : tinted ? 0.08 : 1;
  const ic = Math.round(size * 0.6);
  return rect(x, y, size, size, 14, tinted ? c : P.panel, `fill-opacity="${fillOp}" stroke="${tinted ? c : P.line}" stroke-opacity="${lit ? 0.6 : tinted ? 0.4 : 1}" stroke-width="1.5"`)
    + icon(iconName, x + (size - ic) / 2, y + (size - ic) / 2, ic, lit ? c : tinted ? c : P.dim, 1.9);
}

/** The badges at the top right: lock, offline, low battery, hold, taken over. Returns how many. */
function badges(s: Summary, i: Info): { svg: string; count: number } {
  let x = 128, out = "", count = 0;
  const put = (name: string, colour: string) => {
    out += icon(name, x - 18, 15, 18, colour, 2);
    x -= 22;
    count++;
  };
  if (!s.allowed) put("lock", P.crit);
  if (!s.online) put("wifiOff", P.crit);
  if (i.battery && s.battery !== null && s.battery <= 20) put("battery", s.battery <= 10 ? P.crit : P.warn);
  if (s.hold) put("hand", P.dim);
  if (s.taken) put("person", P.warn);
  return { svg: out, count };
}

/** The unread count on the corner of the tile, as an app's badge. */
function cornerBadge(s: Summary, cx: number, cy: number, T: TextScale = ONE): string {
  if (!s.badge) return "";
  const t = s.badge > 99 ? "99+" : String(s.badge);
  // (1.3) the count in the badge's own size, the pill round it
  const z = sized(T, "badge", 12), d = z - 12;
  const w = Math.max(20 + d, textWidth(t, z, 800) + 11);
  return rect(cx - w / 2 - 2, cy - 12 - d / 2, w + 4, 24 + d, 12 + d / 2, P.bg) + rect(cx - w / 2, cy - 10 - d / 2, w, 20 + d, 10 + d / 2, s.online ? s.accent : P.crit)
    + text(cx, cy + 4.3 + d * 0.36, t, { size: z, weight: 800, fill: P.bg, anchor: "middle", role: "badge" });
}

/** The big words with their unit as a smaller tspan. */
function big(s: Summary, x: number, y: number, sizes: number[], maxW: number, fill: string, anchor: "start" | "middle" = "start", T: TextScale = ONE, cap?: number): string {
  const words = s.online ? s.state || "—" : "Offline";
  const unit = s.online && s.unit ? s.unit : "";
  const us = sized(T, "unit", 15), uk = us / 15;
  const uw = unit ? textWidth(unit, us, 600) + 5 : 0;
  const vf = fitSized(T, "value", words, sizes, maxW - uw, 750, cap);
  const u = unit ? `<tspan dx="4" font-size="${n(us)}" font-weight="600" fill="${P.dim}" letter-spacing="0"${roleAttr("unit")}>${escTspan(unit, uk)}</tspan>` : "";
  return text(x, y, vf.text, { size: vf.size, weight: 750, fill: s.online ? fill : P.crit, anchor, spacing: -0.5, role: "value" }).replace(/<\/text>$/, u + "</text>");
}

function escTspan(t: string, k = 1): string {
  return text(0, 0, fit(t, 15 * k, 50 * k, 600), { size: 1, fill: P.text }).replace(/^<text[^>]*>/, "").replace(/<\/text>$/, "");
}

/** A bar of `n` segments, `lit` of them coloured (rooms heating, windows open). */
function segments(x: number, y: number, w: number, h: number, total: number, lit: number, colour: string, rest: string = P.line): string {
  const k = Math.max(1, Math.min(16, total));
  const gap = k > 10 ? 2 : 3;
  const sw = (w - gap * (k - 1)) / k;
  let out = "";
  const on = total > 16 ? Math.round((lit / total) * k) : lit;
  for (let j = 0; j < k; j++) out += rect(x + j * (sw + gap), y, sw, h, Math.min(h / 2, sw / 2), j < on ? colour : rest);
  return out;
}

/** A level bar: track, then the share in colour. */
function bar(x: number, y: number, w: number, h: number, f: number | null, colour: string, rest: string = P.line): string {
  let s = rect(x, y, w, h, h / 2, rest);
  if (f !== null) s += rect(x, y, Math.max(h, w * Math.max(0, Math.min(1, f))), h, h / 2, colour);
  return s;
}

/** The name at the foot of the key: one line, shrunk or cut as the key's setting says. */
function footName(s: Summary, o: ClassicOpts, i: Info, y = 132): string {
  if (!i.name || !s.name) return "";
  const l = nameLines(s.name, o.fit && o.fit !== "cut" ? "fit" : "cut", sized(o.ts ?? ONE, "name", 13.5, 18), 118, 650, 1);
  return text(14, y, l.lines[0]!, { size: l.size, weight: 650, fill: P.dim, role: "name" });
}

/** Where a summary's small picture goes: beside the tile, under the badges (or across the top without a tile). */
interface Mini { x: number; w: number }

/**
 * The family frame most of them share: the tile at the top left with its small picture beside it,
 * the big words, a detail line, and the name at the foot.
 */
function summaryKey(s: Summary, o: ClassicOpts, mini: (i: Info, c: string, m: Mini) => string, detailFill?: string, detailSvg?: (i: Info, c: string) => string, corner = ""): string {
  const i = o.info ?? SHOW;
  const T = o.ts ?? ONE;
  const c = toneColour(s);
  const b = badges(s, i);
  let body = i.icon ? tile(s) + corner + cornerBadge(s, 58, 16, T) : "";
  body += b.svg;
  if (s.online) body += mini(i, c, i.icon ? { x: 72, w: 58 } : { x: 14, w: 116 });
  if (i.state) body += big(s, 14, 93, [38, 32, 27, 22], 118, s.active && s.online ? P.text : s.stateColour ?? (s.offAccent ?? P.dim), "start", T, (93 - (i.icon ? 63 : 30)) / 0.74);
  const dz = sized(T, "detail", 13, 17);
  if (detailSvg) body += detailSvg(i, c);
  else if (i.detail && s.detail && s.online) body += text(14, 113 + (dz - 13) * 0.4, fit(s.detail, dz, 118, 600), { size: dz, weight: 600, fill: detailFill ?? (s.active ? c : P.dim), role: "detail" });
  body += footName(s, o, i);
  const glow = s.active && s.online ? s.accent : undefined;
  return keySvg(body, glow, "", !glow && s.online && s.offAccent ? s.offAccent : undefined);
}

// ------------------------------------------------------------------ the keys

export function renderExtra(s: Summary, o: ClassicOpts = {}): string {
  switch (s.kind) {
    case "power":
      return powerKey(s, o);
    case "away":
      return awayKey(s, o);
    case "timer":
      return timerKey(s, o);
    case "room":
      return roomKey(s, o);
    case "sms":
      if (s.x.mode === "compose") return composeKey(s, o);
      return summaryKey(s, o, (i, c, m) => {
        if (s.x.mode === "status") {
          // the modem: a lamp and a word
          if (!i.graph) return "";
          const down = s.x.modemDown === true;
          const z = sized(o.ts ?? ONE, "mode", 11.5, 14);
          return `<circle cx="${n(m.x + 5)}" cy="51" r="4.5" fill="${down ? P.crit : P.ok}"/>` + text(m.x + 14, 55, (o.ts ?? ONE).mode === 1 ? (down ? "modem off" : "modem") : fit(down ? "modem off" : "modem", z, m.w - 14, 650), { size: z, weight: 650, fill: down ? P.crit : P.muted, role: "mode" });
        }
        const mz = sized(o.ts ?? ONE, "mode", 12, 15);
        return i.mode && s.mode ? text(m.x, 55, fit(s.mode, mz, m.w, 750), { size: mz, weight: 750, fill: s.badge ? s.accent : c, role: "mode" }) : "";
      });
    case "security":
      return summaryKey(s, o, (i, c, m) => {
        // the alerts as a row of dots; quiet, a small "guarding"
        const al = Number(s.x.alerts) || 0;
        if (i.graph && al > 0) {
          const k = Math.min(Math.floor((m.w + 3) / 11), al);
          let out = "";
          for (let j = 0; j < k; j++) out += `<circle cx="${n(m.x + 4 + j * 11)}" cy="50" r="4" fill="${c}"/>`;
          return out;
        }
        const mz = sized(o.ts ?? ONE, "mode", 11.5, 14);
        if (i.mode && s.mode) return text(m.x, 55, fit(s.mode, mz, m.w, 700), { size: mz, weight: 700, fill: c, role: "mode" });
        if (i.graph && s.x.guarding) return icon("shieldOk", m.x, 43, 14, s.offAccent ?? P.ok, 2) + text(m.x + 17, 55, fit("guard", mz, m.w - 17, 650), { size: mz, weight: 650, fill: P.muted, role: "mode" });
        return "";
      }, s.active ? P.dim : undefined);
    case "heatgroup":
      return summaryKey(s, o, (i, c, m) => {
        const rooms = Number(s.x.rooms) || 0;
        return i.graph && rooms ? segments(m.x, 46, m.w, 8, rooms, Number(s.x.calling) || 0, s.active ? c : s.offAccent ?? P.orange, P.line) : "";
      }, undefined, (i, c) => {
        // the common mode in its colour (Mixed in grey), the temperatures beside it
        const md = i.mode ? s.mode : "";
        const d = i.detail ? s.detail : "";
        if (!s.online || (!md && !d)) return "";
        const T = o.ts ?? ONE;
        const mz = sized(T, "mode", 13.5, 17), dz = sized(T, "detail", 12, 15);
        const mw = md ? Math.min(80, textWidth(md, mz, 750)) : 0;
        let out = md ? text(14, 113, fit(md, mz, 80, 750), { size: mz, weight: 750, fill: s.x.mode === "mixed" ? P.dim : s.active ? c : s.offAccent ?? P.orange, role: "mode" }) : "";
        if (d) out += text(md ? 14 + mw + 8 : 14, 113, fit(d, dz, 118 - (md ? mw + 8 : 0), 600), { size: dz, weight: 600, fill: P.dim, role: "detail" });
        return out;
      });
    case "openings": {
      // heat escaping: a red flame on the tile's corner
      const loss = s.x.loss === true && s.online && (o.info ?? SHOW).mode;
      const corner = loss ? `<circle cx="58" cy="16" r="11" fill="${P.bg}"/><circle cx="58" cy="16" r="9" fill="${P.crit}"/>` + icon("flame", 51.5, 9.5, 13, P.bg, 2.2) : "";
      return summaryKey(s, o, (i, c, m) => {
        const sensors = Number(s.x.sensors) || 0;
        return i.graph && sensors ? segments(m.x, 46, m.w, 8, sensors, Number(s.x.open) || 0, c, s.active ? P.line : s.tone === "ok" && !s.offAccent ? P.ok : P.line) : "";
      }, s.x.loss ? P.crit : s.active ? P.text : undefined, undefined, corner);
    }
    case "batteries":
      return summaryKey(s, o, (i, c, m) => (i.graph && s.level !== null ? batteryBar(m.x, 43, m.w, 15, s.level, s.active ? c : s.offAccent ?? P.ok) : ""), s.active ? P.text : undefined);
    case "zigbee":
      return summaryKey(s, o, (i, c, m) => {
        if (!i.graph) return "";
        const on = Number(s.x.online) || 0, off = Number(s.x.offline) || 0;
        if (!on && !off) return "";
        const f = on / (on + off);
        return rect(m.x, 46, m.w, 8, 4, s.active ? c : P.line) + rect(m.x, 46, Math.max(8, m.w * f), 8, 4, s.offAccent && !s.active ? s.offAccent : P.ok);
      }, s.active ? P.text : undefined);
  }
}

/** A battery drawn lying down, filled to its level. */
function batteryBar(x: number, y: number, w: number, h: number, f: number, colour: string): string {
  const bw = w - 5;
  return rect(x, y, bw, h, 3.5, "none", `stroke="${P.dim}" stroke-opacity="0.7" stroke-width="1.6"`)
    + rect(x + bw + 1, y + h * 0.3, 3, h * 0.4, 1.2, P.dim)
    + rect(x + 2.5, y + 2.5, Math.max(3, (bw - 5) * f), h - 5, 2, colour);
}

/** House power: the figure big, today's kWh under it, the graph over its span at the foot. */
function powerKey(s: Summary, o: ClassicOpts): string {
  const i = o.info ?? SHOW;
  const T = o.ts ?? ONE;
  const lit = s.active && s.online;
  const c = lit ? s.accent : s.offAccent && s.online ? s.offAccent : P.muted;
  const b = badges(s, i);
  let body = i.icon ? icon("bolt", 13, 13, 22, s.online ? (lit ? s.accent : c) : P.crit, 2.1) : "";
  const nameW = 116 - (i.icon ? 26 : 0) - b.count * 22;
  if (i.name && s.name) {
    const l = nameLines(s.name, o.fit && o.fit !== "cut" ? "fit" : "cut", sized(T, "name", 13.5, 18), nameW, 600, 1);
    body += text(i.icon ? 40 : 14, 29 + (sized(T, "name", 13.5, 18) - 13.5) * 0.6, l.lines[0]!, { size: l.size, weight: 600, fill: P.dim, role: "name" });
  }
  body += b.svg;
  const gOn = i.graph && s.online;
  if (i.state) body += big(s, 14, gOn ? 74 : 86, gOn ? [42, 36, 30, 24] : [48, 42, 36, 28], 118, lit ? P.text : s.online ? P.dim : P.crit, "start", T, ((gOn ? 74 : 86) - 40) / 0.74);
  const det = i.detail && s.detail && s.online;
  const span = gOn && i.mode ? s.mode : "";
  if (det) {
    // "12.4 kWh today", or just "12.4 kWh" beside the span
    const w = span ? 92 : 118;
    const dz = sized(T, "detail", 13, 16);
    const d = textWidth(s.detail, dz, 650) <= w ? s.detail : s.detail.replace(/ today$/, "");
    body += text(14, gOn ? 93 : 110, fit(d, dz, w, 650), { size: dz, weight: 650, fill: lit ? s.accent : P.dim, role: "detail" });
  }
  // the graph's span at the right of the line over it
  const sz = sized(T, "mode", 11, 14);
  if (span) body += text(130, 93, T.mode === 1 ? span : fit(span, sz, 24, 700), { size: sz, weight: 700, fill: P.muted, anchor: "end", role: "mode" });
  let defs = "";
  if (gOn) {
    const top = det || span ? 100 : 92;
    const g = i.scale ? graph({ ...faceLite(s), kind: "reading" }, i, 14, top, 116, 128 - top, c, INK, "pw", T.detail) : sparkline(s.series, 14, top, 116, 128 - top, c, "pw", POWER_SCALE);
    body += g.body;
    defs = g.defs;
  }
  return keySvg(body, lit ? s.accent : undefined, defs, !lit && s.online && s.offAccent ? s.offAccent : undefined);
}

function faceLite(s: Summary) {
  return {
    kind: s.kind, name: "", room: null, icon: "", accent: s.accent, active: false, state: "", unit: "", stateColour: null, detail: "", mode: "",
    level: null, series: s.series, target: null, online: true, allowed: true, hold: false, battery: null, scale: POWER_SCALE,
  };
}

/** Away / Home: the house (or the suitcase) big in a ring, the word under it, what is still on below. */
function awayKey(s: Summary, o: ClassicOpts): string {
  const i = o.info ?? SHOW;
  const T = o.ts ?? ONE;
  const lit = s.active && s.online;
  const c = toneColour(s);
  const b = badges(s, i);
  const hasName = i.name && !!s.name;
  const cy = hasName ? 44 : 48;
  let body = "";
  if (i.icon) {
    body += `<circle cx="72" cy="${cy}" r="30" fill="${c}" fill-opacity="${lit ? 0.24 : 0.1}" stroke="${c}" stroke-opacity="${lit ? 0.9 : 0.5}" stroke-width="${lit ? 2.6 : 1.8}"/>`;
    if (lit) body += `<circle cx="72" cy="${cy}" r="37" fill="none" stroke="${c}" stroke-opacity="0.22" stroke-width="2"/>`;
    body += icon(s.icon, 54, cy - 18, 36, c, 2);
  }
  const top = i.icon ? cy + 50 : 70;
  if (i.state) {
    const words = s.online ? s.state : "Offline";
    const vf = fitSized(T, "value", words, [26, 22, 18], 124, 750, i.icon ? (top - cy - 32) / 0.74 : undefined);
    body += text(72, top, vf.text, { size: vf.size, weight: 750, fill: !s.online ? P.crit : lit ? P.text : s.stateColour ?? P.dim, anchor: "middle", role: "value" });
  }
  if (i.detail && s.online) {
    // what is still on: a bulb and its count, a flame and its count
    const lights = Number(s.x.lights) || 0, heat = Number(s.x.heating) || 0;
    const parts: [string, string, string][] = [["bulbOn", String(lights), lights ? P.warn : P.muted], ["flame", String(heat), heat ? P.orange : P.muted]];
    const dz = sized(T, "detail", 13, 16), mz = sized(T, "mode", 11, 13);
    const y = top + 19 + (dz - 13) * 0.4;
    const widths = parts.map(([, t]) => 15 + textWidth(t, dz, 700));
    const total = widths.reduce((a, w) => a + w, 0) + 14 * (parts.length - 1);
    let x = 72 - total / 2;
    parts.forEach(([ic, t, col], k) => {
      body += icon(ic, x, y - 11, 14, col, 2) + text(x + 16, y, t, { size: dz, weight: 700, fill: col === P.muted ? P.muted : P.text, role: "detail" });
      x += widths[k]! + 14;
    });
    if (s.mode) body += text(72, Math.min(140, y + 15 + (mz - 11) * 0.5), fit(s.mode, mz, 120, 600), { size: mz, weight: 600, fill: c, anchor: "middle", role: "mode" });
  }
  const nz = sized(T, "name", 12, 15);
  if (hasName && !(i.detail && s.mode && s.online)) body += text(72, 137, fit(s.name, nz, 124, 600), { size: nz, weight: 600, fill: P.muted, anchor: "middle", role: "name" });
  body += b.svg;
  return keySvg(body, lit ? s.accent : undefined, "", !lit && s.online && s.offAccent ? s.offAccent : undefined);
}

/** Timer: a ring that drains as the minutes go, the countdown in it; idle, the minutes a press starts. */
function timerKey(s: Summary, o: ClassicOpts): string {
  const i = o.info ?? SHOW;
  const T = o.ts ?? ONE;
  const run = s.x.running === true && s.online;
  const c = run ? s.accent : s.online && s.offAccent ? s.offAccent : P.muted;
  const hasName = (i.name && !!s.name) || (i.room && !!s.room);
  const cx = 72, cy = hasName ? 60 : 68, r = hasName ? 44 : 50;
  let body = "";
  if (i.graph) {
    body += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${P.line}" stroke-width="8"/>`;
    // the minute marks, every 5 minutes of an hour
    for (let k = 0; k < 12; k++) {
      const a = (k * 30 - 90) * Math.PI / 180;
      body += `<path d="M ${n(cx + (r - 11) * Math.cos(a))} ${n(cy + (r - 11) * Math.sin(a))} L ${n(cx + (r - 14) * Math.cos(a))} ${n(cy + (r - 14) * Math.sin(a))}" stroke="${P.muted}" stroke-opacity="${k % 3 ? 0.5 : 0.9}" stroke-width="1.6" stroke-linecap="round"/>`;
    }
    const f = run ? s.level ?? 0 : 0;
    if (run && f > 0.002) body += f >= 0.999 ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="url(#tr)" stroke-width="8"/>`
      : `<path d="${arcPath(cx, cy, r, 0, 360 * f)}" fill="none" stroke="url(#tr)" stroke-width="8" stroke-linecap="round"/>`;
    if (run) {
      const a = ((360 * f) - 90) * Math.PI / 180;
      body += `<circle cx="${n(cx + r * Math.cos(a))}" cy="${n(cy + r * Math.sin(a))}" r="5.5" fill="${P.text}" stroke="${c}" stroke-width="2.5"/>`;
    } else {
      // idle: the share of two hours the press would start, faint
      const share = Math.min(1, (Number(s.x.minutes) || 0) / 120);
      body += `<path d="${arcPath(cx, cy, r, 0, 360 * share)}" fill="none" stroke="${c}" stroke-opacity="0.35" stroke-width="8" stroke-linecap="round"/>`;
    }
  }
  if (i.icon) body += icon("stopwatch", cx - 9, cy - (i.state ? 33 : 12), 18, run ? c : s.online ? c : P.crit, 2);
  if (i.state) {
    const words = s.online ? s.state : "Offline";
    const vy = cy + (run ? 9 : 10);
    const vf = fitSized(T, "value", words, run ? [28, 24, 20, 17] : [34, 28, 22], r * 1.62, 750, (vy - (i.icon ? cy - 14 : cy - r + 14)) / 0.74);
    body += text(cx, vy, vf.text, { size: vf.size, weight: 750, fill: !s.online ? P.crit : run ? P.text : P.dim, anchor: "middle", spacing: -0.5, role: "value" });
    if (s.online && (run ? i.detail : true)) {
      // running, the time it goes off (a detail); idle, "min" - the unit of the minutes over it
      const sub = run ? s.detail.replace(/^off at /, "→ ") : "min";
      const role = run ? "detail" : "unit";
      const z = sized(T, role, 12, 16);
      body += text(cx, cy + 26 + (z - 12) * 0.6, fit(sub, z, r * 1.4, 650), { size: z, weight: 650, fill: run ? c : P.muted, anchor: "middle", role });
    }
  } else if (i.detail && s.online) {
    const z = sized(T, "detail", 12, 16);
    body += text(cx, cy + 6, fit(s.detail, z, r * 1.5, 650), { size: z, weight: 650, fill: run ? c : P.dim, anchor: "middle", role: "detail" });
  }
  if (hasName) {
    // the switch's name (its room only when the name is not shown: the key has one line for it)
    const t = i.name && s.name ? s.name : s.room ?? "";
    const role = i.name && s.name ? "name" : "room";
    const l = nameLines(t, o.fit && o.fit !== "cut" ? "fit" : "cut", sized(T, role, 13.5, 17), 124, 650, 1);
    body += text(72, 136, l.lines[0]!, { size: l.size, weight: 650, fill: P.text, anchor: "middle", role });
  }
  body += badges(s, i).svg;
  if (!run && s.online && s.x.swOn) body += `<circle cx="20" cy="20" r="5" fill="${P.ok}"/>`;
  const defs = `<linearGradient id="tr" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c}"/><stop offset="1" stop-color="${c}" stop-opacity="0.6"/></linearGradient>`;
  return keySvg(body, run ? s.accent : undefined, defs, !run && s.online && s.offAccent ? s.offAccent : undefined);
}

/** Room: its name, the temperature big, humidity and what is on, its heating at the foot. */
function roomKey(s: Summary, o: ClassicOpts): string {
  const i = o.info ?? SHOW;
  const T = o.ts ?? ONE;
  const lit = s.active && s.online;
  const calling = s.x.calling === true;
  const c = lit ? s.accent : s.online && s.offAccent ? s.offAccent : P.info;
  const b = badges(s, i);
  let body = i.icon ? icon(s.icon, 13, 12, 22, s.online ? c : P.crit, 2) : "";
  if (i.name && s.name) {
    const nz = sized(T, "name", 14, 18);
    const l = nameLines(s.name, o.fit && o.fit !== "cut" ? "fit" : "cut", nz, 116 - (i.icon ? 26 : 0) - b.count * 22, 650, 1);
    body += text(i.icon ? 40 : 14, 29 + (nz - 14) * 0.6, l.lines[0]!, { size: l.size, weight: 650, fill: P.text, role: "name" });
  }
  body += b.svg;
  if (i.state) body += big({ ...s, unit: s.unit ? "°C" : "" }, 14, 76, [44, 38, 32, 26], 118, s.online ? P.text : P.crit, "start", T, (76 - 38) / 0.74);
  const dz = sized(T, "detail", 13, 16);
  let y = 99 + (dz - 13) * 0.5;
  if (i.detail && s.online) {
    let x = 14;
    const h = s.x.h as number | null;
    if (h !== null) {
      body += icon("drop", x, y - 12, 15, P.water, 2) + text(x + 17, y, Math.round(h) + " %", { size: dz, weight: 650, fill: P.text, role: "detail" });
      x += 17 + textWidth(Math.round(h) + " %", dz, 650) + 12;
    }
    const sAll = Number(s.x.sAll) || 0;
    if (sAll) {
      const on = Number(s.x.sOn) || 0;
      body += icon(on ? "bulbOn" : "bulb", x, y - 12, 15, on ? P.warn : P.muted, 2) + text(x + 17, y, on + "/" + sAll, { size: dz, weight: 650, fill: on ? P.text : P.dim, role: "detail" });
    }
    y += 20;
  }
  if (i.mode && s.mode && s.online) {
    const fy = i.detail ? 126 : 112;
    body += rect(14, fy - 15, 116, 22, 11, calling ? P.orange : P.panel2, `fill-opacity="${calling ? 0.18 : 1}" stroke="${calling ? P.orange : P.line}" stroke-opacity="${calling ? 0.6 : 1}" stroke-width="1.2"`)
      + icon(calling ? "flame" : "thermostat", 20, fy - 11.5, 15, calling ? P.orange : P.muted, 2)
      + text(39, fy + 0.5, fitSized(T, "mode", s.mode, [12.5, 11.5, 10.5], 88, 650, 15).text, { size: fitSized(T, "mode", s.mode, [12.5, 11.5, 10.5], 88, 650, 15).size, weight: 650, fill: calling ? P.text : P.dim, role: "mode" });
  }
  return keySvg(body, lit ? s.accent : undefined, "", !lit && s.online && s.offAccent ? s.offAccent : undefined);
}

/** SMS, Write new: the send mark big in a ring, "New SMS", and whom to. */
function composeKey(s: Summary, o: ClassicOpts): string {
  const i = o.info ?? SHOW;
  const T = o.ts ?? ONE;
  const c = !s.online ? P.crit : s.active || !s.offAccent ? s.accent : s.offAccent;
  const lit = s.active && s.online;
  let body = "";
  if (i.icon) {
    body += `<circle cx="72" cy="50" r="32" fill="${c}" fill-opacity="${lit ? 0.3 : 0.14}" stroke="${c}" stroke-opacity="${lit ? 0.95 : 0.55}" stroke-width="2"/>`;
    body += icon("send", 52, 30, 40, c, 1.9);
    body += cornerBadge(s, 98, 26, T);
  }
  const lines: [string, "name" | "detail" | "value"][] = [];
  if (i.name && s.name) lines.push([s.name, "name"]);
  if (i.detail && s.detail && s.online) lines.push([s.detail, "detail"]);
  if (!s.online) lines.unshift(["Offline", "value"]);
  const y0 = i.icon ? 108 : 72;
  const z0 = lines[0] ? sized(T, lines[0][1], 15.5, 20) : 15.5;
  lines.slice(0, 2).forEach(([l, role], k) => {
    const z = k === 0 ? z0 : sized(T, role, 12.5, 16);
    body += text(72, y0 + k * 19 + (k === 0 ? (z0 - 15.5) * 0.3 : (z0 - 15.5) * 0.5 + (z - 12.5) * 0.6), fit(l, z, 126, k === 0 ? 700 : 600), { size: z, weight: k === 0 ? 700 : 600, fill: k === 0 ? (s.online ? P.text : P.crit) : P.dim, anchor: "middle", role });
  });
  body += badges(s, i).svg;
  return keySvg(body, lit ? c : undefined, "", !lit && s.online && s.offAccent ? s.offAccent : undefined);
}

// ------------------------------------------------------------------ the touch strip

/** The words for a strip's "value" and colours, the same as the key's. */
function stripValue(s: Summary): { value: string; color: string } {
  return { value: s.online ? (s.state || "—") + (s.unit ? " " + s.unit : "") : "Offline", color: !s.online ? P.crit : s.active ? P.text : s.stateColour ?? (s.offAccent ?? P.dim) };
}

export function iconPx(name: string, colour: string, size: number, tint?: string): string {
  const pad = Math.round(size * 0.18);
  const body = (tint ? rect(0, 0, size, size, size * 0.3, tint, `fill-opacity="0.18" stroke="${tint}" stroke-opacity="0.5" stroke-width="1.2"`) : "")
    + icon(name, pad, pad, size - 2 * pad, colour, 1.9);
  return dataUri(svgDoc(size, size, body));
}

/** What each new action's dial shows on the Stream Deck + strip (layouts.ts: power, summary, timer, room). */
export function extraFeedback(s: Summary, hint: string, member: { name: string; icon: string; colour: string; state: string; lit: boolean; index: number; count: number } | null): Feedback {
  const c = toneColour(s);
  const lit = s.active && s.online;
  const ic = (name: string, size: number) => iconPx(name, s.online ? c : P.crit, size, lit || s.tone === "ok" || !!s.offAccent ? c : undefined);
  switch (s.kind) {
    case "power": {
      const g = sparkline(s.series, 0, 74, 200, 24, lit ? s.accent : c, "sp", POWER_SCALE);
      return {
        art: dataUri(svgDoc(200, 100, `<g opacity="0.9">${g.body}</g>`, g.defs)),
        icon: ic("bolt", 22),
        name: { value: s.name },
        span: { value: s.mode, color: lit ? s.accent : P.muted },
        value: stripValue(s),
        sub: { value: s.detail || hint, color: lit ? s.accent : P.dim },
      };
    }
    case "timer": {
      const run = s.x.running === true && s.online;
      const cx = 160, cy = 50, r = 34;
      let art = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${P.line}" stroke-width="7"/>`;
      const f = run ? s.level ?? 0 : Math.min(1, (Number(s.x.minutes) || 0) / 120);
      if (f > 0.002) art += f >= 0.999 ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${c}" stroke-width="7"/>`
        : `<path d="${arcPath(cx, cy, r, 0, 360 * f)}" fill="none" stroke="${c}" stroke-opacity="${run ? 1 : 0.45}" stroke-width="7" stroke-linecap="round"/>`;
      art += icon("stopwatch", cx - 11, cy - 11, 22, run ? c : P.muted, 2);
      return {
        art: dataUri(svgDoc(200, 100, art)),
        name: { value: s.name },
        value: { value: s.online ? (run ? s.state : s.state + " min") : "Offline", color: !s.online ? P.crit : run ? P.text : P.dim },
        sub: { value: run ? s.detail : s.x.swOn ? "on now" : "off now", color: run ? c : P.dim },
        mode: { value: hint, color: P.dim },
      };
    }
    case "room": {
      const top = [s.name, s.state !== "—" ? s.state + " °C" : "", s.x.h !== null ? Math.round(s.x.h as number) + " %" : ""].filter(Boolean).join(" · ");
      if (!member) {
        return {
          top: { value: top },
          icon: ic(s.icon, 36),
          name: { value: s.mode || s.detail || "No items here", color: P.text },
          value: { value: s.detail && s.mode ? s.detail : s.online ? "" : "Offline", color: s.online ? P.dim : P.crit },
          art: dataUri(svgDoc(176, 16, "")),
        };
      }
      // the pager: a dot per member (a window of them round the one chosen), the count at the right
      const k = Math.min(member.count, 13);
      const startAt = Math.max(0, Math.min(member.count - k, member.index - Math.floor(k / 2)));
      const label = member.index + 1 + "/" + member.count;
      const lw = textWidth(label, 11, 700) + 8;
      const span = 176 - lw;
      let dots = "";
      for (let j = 0; j < k; j++) {
        const sel = startAt + j === member.index;
        const x = 8 + (k === 1 ? 0 : (j * (span - 16)) / Math.max(1, k - 1));
        dots += sel ? rect(x - 7, 4, 14, 8, 4, member.colour) : `<circle cx="${n(x)}" cy="8" r="3" fill="${P.muted}"/>`;
      }
      dots += text(176, 12, label, { size: 11, weight: 700, fill: P.dim, anchor: "end" });
      return {
        top: { value: top },
        icon: iconPx(member.icon, member.lit ? member.colour : P.dim, 36, member.lit ? member.colour : undefined),
        name: { value: member.name, color: P.text },
        value: { value: member.state, color: member.lit ? P.text : P.dim },
        art: dataUri(svgDoc(176, 16, dots)),
      };
    }
    default: {
      // the summary layout: the icon, the name, the big words, a detail, and a bar of its own
      let art = "";
      const W = 176, H = 16;
      if (s.online) {
        if (s.kind === "heatgroup" && Number(s.x.rooms)) art = segments(0, 4, W, 8, Number(s.x.rooms), Number(s.x.calling) || 0, lit ? c : P.orange);
        else if (s.kind === "openings" && Number(s.x.sensors)) art = segments(0, 4, W, 8, Number(s.x.sensors), Number(s.x.open) || 0, c, lit ? P.line : P.ok);
        else if (s.kind === "batteries" && s.level !== null) art = batteryBar(0, 2, W, 12, s.level, lit ? c : P.ok);
        else if (s.kind === "zigbee" && s.level !== null) art = rect(0, 4, W, 8, 4, lit ? c : P.line) + rect(0, 4, Math.max(8, W * s.level), 8, 4, P.ok);
        else if (s.kind === "security") {
          const al = Number(s.x.alerts) || 0;
          if (al) for (let j = 0; j < Math.min(14, al); j++) art += `<circle cx="${n(6 + j * 12.5)}" cy="8" r="4" fill="${c}"/>`;
          else art = bar(0, 4, W, 8, 1, P.ok, P.line);
        } else if (s.kind === "away") art = bar(0, 4, W, 8, lit ? 1 : null, c, P.line);
        else if (s.kind === "sms") art = s.badge ? segments(0, 4, W, 8, Math.min(16, Math.max(s.badge, 1)), Math.min(16, s.badge), s.accent) : bar(0, 4, W, 8, s.x.muted ? 1 : null, c, P.line);
      }
      return {
        icon: ic(s.icon, 40),
        name: { value: s.name },
        value: stripValue(s),
        sub: { value: s.online ? [s.detail, s.mode].filter(Boolean).join(" · ") || hint : "", color: lit ? c : P.dim },
        art: dataUri(svgDoc(W, H, art)),
      };
    }
  }
}
