/**
 * What each dial shows on the Stream Deck + touch strip: setFeedback payloads for the layouts
 * in layouts.ts. Text values are plain strings (Stream Deck draws them); pictures are SVG
 * pixmaps drawn here at their rect's size. Server text is cleaned and escaped like on the keys.
 */
import { P } from "./palette.js";
import {
  blindsArt, fmtTemp, lookFor, seriesFace, sparkline, type BlindsModel, type ControlModel, type DimmerModel, type ReadingModel, type ThermoModel,
} from "./render.js";
import { arcPath, dataUri, icon, n, rect, svgDoc, text } from "./svg.js";
import { graph, type Info } from "./themes.js";

export type Feedback = Record<string, string | number | { value?: string | number; color?: string; enabled?: boolean; opacity?: number }>;

export function iconPix(name: string, colour: string, size: number, tint?: string): string {
  const pad = Math.round(size * 0.18);
  const body = (tint ? rect(0, 0, size, size, size * 0.3, tint, `fill-opacity="0.18" stroke="${tint}" stroke-opacity="0.5" stroke-width="1.2"`) : "")
    + icon(name, pad, pad, size - 2 * pad, colour, 1.9);
  return dataUri(svgDoc(size, size, body));
}

/** A slider: track, fill, knob - for brightness and positions. (1.3) `off`: the user's Off colour for an unlit one. */
export function sliderArt(w: number, h: number, f: number | null, colour: string, active: boolean, label = "", off?: string): string {
  const y = h / 2;
  const grey = !active && off ? off : P.muted;
  let s = rect(0, y - 4, w, 8, 4, P.line);
  if (f !== null) {
    const x = Math.max(8, w * f);
    s += rect(0, y - 4, x, 8, 4, active ? "url(#fill)" : grey);
    s += `<circle cx="${n(Math.min(w - 9, Math.max(9, x)))}" cy="${n(y)}" r="9" fill="${P.text}" stroke="${active ? colour : grey}" stroke-width="3"/>`;
  }
  if (label) s += text(w, y - 9, label, { size: 10, weight: 600, fill: P.dim, anchor: "end" });
  const defs = `<linearGradient id="fill" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${colour}" stop-opacity="0.55"/><stop offset="1" stop-color="${colour}"/></linearGradient>`;
  return dataUri(svgDoc(w, h, s, defs));
}

/** On/off as a pill: a dot and the word, tinted. (1.3) `off`: an unlit pill tinted with the user's Off colour. */
export function pillArt(w: number, h: number, word: string, colour: string, active: boolean, off?: string): string {
  const o = !active && off ? off : undefined;
  const s = (o ? rect(0, 2, w, h - 4, (h - 4) / 2, o, `fill-opacity="0.12" stroke="${o}" stroke-opacity="0.6" stroke-width="1.5"`)
    : rect(0, 2, w, h - 4, (h - 4) / 2, active ? colour : P.panel2, `fill-opacity="${active ? 0.2 : 1}" stroke="${active ? colour : P.line}" stroke-width="1.5"`))
    + `<circle cx="${n(h / 2 + 4)}" cy="${n(h / 2)}" r="5" fill="${active ? colour : o ?? P.muted}"/>`
    + text(h / 2 + 16, h / 2 + 5, word, { size: 14, weight: 700, fill: active ? P.text : P.dim });
  return dataUri(svgDoc(w, h, s));
}

/** The hold-to-confirm progress across the bottom of a strip. */
export function holdArt(w: number, h: number, p: number, colour: string): string {
  const s = rect(0, h / 2 - 5, w, 10, 5, P.line)
    + rect(0, h / 2 - 5, Math.max(10, w * Math.max(0, Math.min(1, p))), 10, 5, colour)
    + text(w / 2, h / 2 - 9, p >= 1 ? "Confirmed" : "Keep holding…", { size: 10, weight: 700, fill: P.text, anchor: "middle" });
  return dataUri(svgDoc(w, h, s));
}

export function controlFeedback(m: ControlModel, mainFraction: number | null, mainText: string, hint = "", accent?: string, offAccent?: string): Feedback {
  const l0 = lookFor(m.kind, m.icon, m.on);
  const look = { ...l0, accent: accent ?? l0.accent };
  const active = m.on === true && m.online;
  const off = !active && m.online ? offAccent : undefined;
  const word = !m.allowed ? "Not allowed" : !m.online ? "Offline" : m.on === true ? "On" : m.on === false ? "Off" : m.valueText || "—";
  return {
    icon: iconPix(look.icon, active ? look.accent : off ?? P.dim, 40, active ? look.accent : off),
    name: { value: m.name + (m.room && m.showRoom ? " · " + m.room : "") },
    value: { value: mainText || (m.valueText && m.on !== null && m.online && m.allowed ? word + " \u00b7 " + m.valueText : word), color: !m.online || !m.allowed ? P.crit : active ? P.text : P.dim },
    art: mainFraction !== null ? sliderArt(176, 30, mainFraction, look.accent, active || m.on === null, "", off) : pillArt(176, 30, hint || word, look.accent, active, off),
  };
}

export function readingFeedback(m: ReadingModel, info?: Info): Feedback {
  const sp = info?.scale ? graph(seriesFace(m.history, null, m.scale), info, 0, 66, 200, 30, m.colour, STRIP_INK, "sp") : sparkline(m.history, 0, 66, 200, 30, m.colour, "sp", m.scale);
  let art = sp.body;
  if (m.trend && m.online) {
    const t = m.trend === "up" ? "trendUp" : m.trend === "down" ? "trendDown" : "trendFlat";
    art += icon(t, 170, 10, 20, m.trend === "flat" ? P.muted : m.colour, 2.2);
  }
  return {
    art: dataUri(svgDoc(200, 100, art, sp.defs)),
    icon: iconPix(m.icon, m.accent, 22),
    name: { value: m.label },
    value: { value: m.online ? (m.value || "—") + (m.unit ? " " + m.unit : "") : "Offline", color: m.online ? m.colour : P.crit },
  };
}

const STRIP_INK = { bg: P.bg, bg2: P.panel2, line: P.line, text: P.text, dim: P.dim, muted: P.muted, crit: P.crit, warn: P.warn, badge: P.bg };

export function thermoFeedback(m: ThermoModel, accent?: string, info?: Info, offAccent?: string): Feedback {
  const cx = 158, cy = 54, r = 32;
  const span = Math.max(0.5, m.max - m.min);
  const f = (v: number | null) => (v === null ? 0 : Math.max(0, Math.min(1, (v - m.min) / span)));
  const a0 = -135, a1 = 135;
  const heat = accent ?? P.orange;
  const off = !m.heating && m.online ? offAccent : undefined;
  accent = m.heating ? heat : off ?? P.info;
  let s = "";
  let gdefs = "";
  if (info?.graph && (m.history?.length ?? 0) >= 2) {
    // the measured temperature behind the words, the target dashed across it
    const g = graph(seriesFace(m.history!, m.target, { unit: m.unit }), info, 4, 62, 116, 34, m.heating ? heat : off ?? P.water, STRIP_INK, "hist");
    s += `<g opacity="0.55">${g.body}</g>`;
    gdefs = g.defs;
  }
  s += `<path d="${arcPath(cx, cy, r, a0, a1)}" fill="none" stroke="${P.line}" stroke-width="7" stroke-linecap="round"/>`;
  if (m.target !== null && m.online) {
    s += `<path d="${arcPath(cx, cy, r, a0, a0 + (a1 - a0) * f(m.target))}" fill="none" stroke="url(#arc)" stroke-width="7" stroke-linecap="round"/>`;
    const ang = ((a0 + (a1 - a0) * f(m.target) - 90) * Math.PI) / 180;
    s += `<circle cx="${n(cx + r * Math.cos(ang))}" cy="${n(cy + r * Math.sin(ang))}" r="6" fill="${P.text}" stroke="${accent}" stroke-width="2.5"/>`;
  }
  if (info?.icon !== false) s += m.heating ? icon("flame", cx - 12, cy - 13, 24, heat, 2) : icon("thermo", cx - 11, cy - 12, 22, off ?? P.muted, 2);
  const defs = `<linearGradient id="arc" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="${off ?? P.info}"/><stop offset="1" stop-color="${m.heating ? heat : off ?? P.water}"/></linearGradient>` + gdefs;
  return {
    art: dataUri(svgDoc(200, 100, s, defs)),
    name: { value: m.name },
    value: { value: m.online ? fmtTemp(m.current) + (m.unit ? " " + m.unit : "") : "Offline", color: m.online ? P.text : P.crit },
    target: { value: m.online ? "→ " + fmtTemp(m.target) + (m.unit ? " " + m.unit : "") : "", color: accent },
    mode: { value: m.mode ? m.mode + (m.heating ? " · heating" : "") : m.heating ? "heating" : "" },
  };
}

export function dimmerFeedback(m: DimmerModel, accent: string = P.warn, offAccent?: string): Feedback {
  const active = m.on === true && m.online;
  const off = !active && m.online ? offAccent : undefined;
  const big = !m.allowed ? "Not allowed" : !m.online ? "Offline" : m.on === false ? "Off" : m.levelText || (m.on ? "On" : "—");
  return {
    icon: iconPix(active ? "bulbOn" : "bulb", active ? accent : off ?? P.dim, 36, active ? accent : off),
    name: { value: m.name },
    value: { value: big, color: !m.online || !m.allowed ? P.crit : active ? P.text : P.dim },
    art: sliderArt(176, 32, m.level, accent, active, "", off),
  };
}

export function blindsFeedback(m: BlindsModel, accent: string = P.purple, offAccent?: string): Feedback {
  // (1.3) closed and still: the blind in the user's Off colour
  if (offAccent && m.online && !m.moving && m.position !== null && m.position <= 0.5) accent = offAccent;
  const body = `<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1F3A5F"/><stop offset="1" stop-color="#2D4F6E"/></linearGradient></defs>`
    + blindsArt(4, 6, 44, 74, m.online ? m.position : null, accent);
  const big = !m.allowed ? "Not allowed" : !m.online ? "Offline" : m.position === null ? "—" : m.position >= 99.5 ? "Open" : m.position <= 0.5 ? "Closed" : Math.round(m.position) + "%";
  return {
    art: dataUri(svgDoc(52, 84, body)),
    name: { value: m.name },
    value: { value: big, color: !m.online || !m.allowed ? P.crit : P.text },
    sub: { value: m.moving === "up" ? "Opening…" : m.moving === "down" ? "Closing…" : m.position !== null && m.online ? "turn \u00b7 push: stop" : "" },
  };
}

/** A dial with nothing to show yet: the notice in words, the art cleared. */
export function noticeFeedback(layout: string, title: string, line: string, tone: "info" | "warn" | "crit" | "muted"): Feedback {
  const c = tone === "info" ? P.info : tone === "warn" ? P.warn : tone === "crit" ? P.crit : P.dim;
  const fb: Feedback = { name: { value: line }, value: { value: title, color: c } };
  const blank = dataUri(svgDoc(4, 4, ""));
  if (layout === "control" || layout === "dimmer") {
    fb.icon = iconPix(tone === "crit" ? "alert" : tone === "warn" ? "lock" : "zigmon", c, layout === "dimmer" ? 36 : 40);
    fb.art = blank;
  } else if (layout === "reading") {
    fb.icon = iconPix("zigmon", c, 22);
    fb.art = blank;
  } else if (layout === "thermostat") {
    fb.art = blank;
    fb.target = { value: "" };
    fb.mode = { value: "" };
  } else if (layout === "blinds") {
    fb.art = blank;
    fb.sub = { value: "" };
  }
  return fb;
}

/** The pairing code on a dial. */
export function pairFeedback(layout: string, code: string): Feedback {
  const fb = noticeFeedback(layout, code, "Pair with ZIGMon", "info");
  (fb.value as { value: string; color: string }).color = P.text;
  return fb;
}
