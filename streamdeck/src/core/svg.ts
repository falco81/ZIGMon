import { iconMarkup } from "./icons.js";
import { FONT } from "./palette.js";

/** Escapes text for SVG/XML text and attribute values. Everything from the server goes through it. */
export function esc(v: unknown): string {
  return String(v ?? "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200e\u200f\u202a-\u202e\u2066-\u2069\ufffe\uffff]/g, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** A number for an SVG attribute: finite, at most 2 decimals. */
export function n(v: number): string {
  if (!Number.isFinite(v)) return "0";
  return String(Math.round(v * 100) / 100);
}

const NARROW = new Set([..."iljI.,:;'!|`"]);
const SEMI = new Set([..."frt()[]{}-/\\ °"]);
const WIDE = new Set([..."mwMW@%"]);

/** Roughly how wide text is in Segoe UI / Inter, in px. Good enough to keep text inside a key. */
export function textWidth(text: string, size: number, weight = 600): number {
  let w = 0;
  for (const ch of text) {
    const base = ch.normalize("NFD")[0] ?? ch;
    let c: number;
    if (NARROW.has(base)) c = 0.27;
    else if (SEMI.has(base)) c = 0.36;
    else if (WIDE.has(base)) c = 0.86;
    else if (/[A-Z]/.test(base)) c = 0.66;
    else if (/[0-9]/.test(base)) c = 0.6;
    else if (/[a-z]/.test(base)) c = 0.55;
    else c = 0.62;
    w += c;
  }
  return w * size * (weight >= 650 ? 1.06 : weight >= 550 ? 1.02 : 1);
}

/** Text cut with an ellipsis to fit maxWidth. */
export function fit(text: string, size: number, maxWidth: number, weight = 600): string {
  if (textWidth(text, size, weight) <= maxWidth) return text;
  const chars = [...text];
  while (chars.length > 1 && textWidth(chars.join("") + "…", size, weight) > maxWidth) chars.pop();
  return chars.join("").trimEnd() + "…";
}

/** The largest size from `sizes` at which text fits, else the smallest with an ellipsis. */
export function fitSize(text: string, sizes: number[], maxWidth: number, weight = 700): { text: string; size: number } {
  for (const s of sizes) if (textWidth(text, s, weight) <= maxWidth) return { text, size: s };
  const s = sizes[sizes.length - 1]!;
  return { text: fit(text, s, maxWidth, weight), size: s };
}

/** Up to two lines: words wrapped at maxWidth, the second ellipsized. */
export function wrap2(text: string, size: number, maxWidth: number, weight = 600): string[] {
  if (textWidth(text, size, weight) <= maxWidth) return [text];
  const words = text.split(" ");
  let first = "";
  let i = 0;
  for (; i < words.length; i++) {
    const t = first ? first + " " + words[i] : words[i]!;
    if (textWidth(t, size, weight) > maxWidth) break;
    first = t;
  }
  if (!first) return [fit(text, size, maxWidth, weight)];
  const rest = words.slice(i).join(" ");
  return rest ? [first, fit(rest, size, maxWidth, weight)] : [first];
}

/**
 * Two lines that break where a name breaks: after a space, a hyphen, an underscore, a dot or a
 * slash ("Light-Loznice-Main" -> "Light-Loznice-" / "Main"); a word too long for a line is cut
 * between letters. The second line ends with an ellipsis only when even that does not fit.
 */
export function smartWrap(text: string, size: number, maxWidth: number, weight = 600): string[] {
  if (textWidth(text, size, weight) <= maxWidth) return [text];
  const tokens = text.split(/(?<=[\s\-_./])/);
  let first = "";
  let i = 0;
  for (; i < tokens.length; i++) {
    const t = first + tokens[i];
    if (textWidth(t.trimEnd(), size, weight) > maxWidth) break;
    first = t;
  }
  let rest: string;
  if (!first) {
    // one long word: as many letters as fit
    const chars = [...text];
    let k = 1;
    while (k < chars.length && textWidth(chars.slice(0, k + 1).join(""), size, weight) <= maxWidth) k++;
    first = chars.slice(0, k).join("");
    rest = chars.slice(k).join("");
  } else rest = tokens.slice(i).join("");
  first = first.trimEnd();
  rest = rest.trim();
  return rest ? [first, fit(rest, size, maxWidth, weight)] : [first];
}

export type NameFit = "cut" | "fit" | "wrap";

/**
 * A name laid out for `maxWidth`: cut = one line with an ellipsis; wrap = up to two lines at
 * `size`; fit = one line at the largest of a few smaller sizes, else two lines, smaller still if need be.
 */
export function nameLines(text: string, mode: NameFit, size: number, maxWidth: number, weight = 650, maxLines = 2): { lines: string[]; size: number } {
  if (mode === "cut") return { lines: [fit(text, size, maxWidth, weight)], size };
  if (maxLines < 2) {
    // one line only: smaller before it is cut
    for (const f of [1, 0.9, 0.8, 0.72]) if (textWidth(text, size * f, weight) <= maxWidth) return { lines: [text], size: size * f };
    return { lines: [fit(text, size * 0.72, maxWidth, weight)], size: size * 0.72 };
  }
  if (mode === "wrap") return { lines: smartWrap(text, size, maxWidth, weight), size };
  for (const f of [1, 0.9, 0.8]) if (textWidth(text, size * f, weight) <= maxWidth) return { lines: [text], size: size * f };
  for (const f of [1, 0.9, 0.8, 0.72]) {
    const l = smartWrap(text, size * f, maxWidth, weight);
    if (!l[1] || !l[1].endsWith("…")) return { lines: l, size: size * f };
  }
  return { lines: smartWrap(text, size * 0.72, maxWidth, weight), size: size * 0.72 };
}

/**
 * (1.3) What a piece of text on a key is, for its size: the big state or value, the name (or the
 * label), the room, the second value (the W under a light, the target, the trend, "1/3 as set"),
 * a mode or preset, the unit beside the value, and the small words of a badge (an unread count).
 */
export const TEXT_ROLES = ["value", "name", "room", "detail", "mode", "unit", "badge"] as const;
export type TextRole = (typeof TEXT_ROLES)[number];
/** Each role's size as a factor (1 = as drawn before 1.3). */
export type TextScale = Readonly<Record<TextRole, number>>;
export const ONE: TextScale = Object.freeze({ value: 1, name: 1, room: 1, detail: 1, mode: 1, unit: 1, badge: 1 });

/** Every factor is 1: nothing is drawn any differently. */
export function unscaled(t: TextScale | undefined): boolean {
  return !t || TEXT_ROLES.every((r) => t[r] === 1);
}

let tagging = false;
/** Tests only: each piece of text says its role (data-role), so its size can be checked. Off, the SVG is as before. */
export function tagRoles(on: boolean): void {
  tagging = on;
}
/** The role attribute of a text or tspan, when tagging. */
export function roleAttr(role: TextRole | undefined): string {
  return tagging && role ? ` data-role="${role}"` : "";
}

/**
 * A size scaled by its role's factor `k`. Bigger is held to `cap` (the room the layout has for it,
 * never below the size itself); a factor of 1 gives the very same number.
 */
export function grow(size: number, k: number, cap?: number): number {
  if (k === 1) return size;
  const s = size * k;
  return k > 1 && cap !== undefined ? Math.min(s, Math.max(size, cap)) : s;
}

/** The candidate sizes of a fitSize scaled alike, each held to `cap(size)` (the same array when k is 1). */
export function growAll(sizes: number[], k: number, cap?: (s: number) => number | undefined): number[] {
  if (k === 1) return sizes;
  const g = sizes.map((s) => grow(s, k, cap?.(s)));
  // bigger: the sizes at 100 % stay among the candidates, so a long text is never drawn smaller than it was
  return k > 1 ? [...new Set([...g, ...sizes])].sort((a, b) => b - a) : g;
}

/**
 * (1.3) fitSize over the candidates scaled by `k`. Smaller, the text is never bigger than `k` times
 * what it is at 100 % (a long text held back by its width at 100 % does not grow back at 50 %).
 */
export function fitSizeK(text: string, sizes: number[], k: number, maxWidth: number, weight = 700, cap?: (s: number) => number | undefined): { text: string; size: number } {
  if (k >= 1) return fitSize(text, growAll(sizes, k, cap), maxWidth, weight);
  return fitSize(text, smallerThan(growAll(sizes, k), fitSize(text, sizes, maxWidth, weight).size * k), maxWidth, weight);
}

/** Candidates no bigger than `most` (the smallest of them, if none is). */
export function smallerThan(sizes: number[], most: number): number[] {
  const l = sizes.filter((z) => z <= most + 1e-9);
  return l.length ? l : [Math.min(...sizes)];
}

/** One piece of a line of text and what it is. */
export type Part = [string, TextRole];

/**
 * (1.3) A line made of pieces of different roles - a detail and a mode ("→ 22.0 °C · Comfort"), a
 * value and its unit ("23.6 °C"). While their factors agree it is one text, fitted exactly as it was
 * (the largest of `cands` that fits, else the smallest with an ellipsis), tagged with the first
 * piece's role. Else each later piece is a tspan of its own size; the line goes a little smaller,
 * then the last piece is cut (or dropped) to keep it within maxWidth. `cap(size)` holds a bigger size.
 * Returns the svg and the size of the first piece.
 */
export function mixLine(x: number, y: number, parts: Part[], cands: number[], maxWidth: number, o: Omit<TextOpts, "size" | "role">, t: TextScale,
  cap?: (s: number) => number | undefined): { svg: string; size: number } {
  // nothing but empty pieces: an empty text, as the line was drawn before (none at all without pieces)
  const ps = parts.some((p) => p[0]) ? parts.filter((p) => p[0]) : parts.slice(0, 1);
  if (!ps.length) return { svg: "", size: 0 };
  const weight = o.weight ?? 600;
  const k0 = t[ps[0]![1]];
  if (ps.every((p) => t[p[1]] === k0)) {
    const f = fitSizeK(ps.map((p) => p[0]).join(""), cands, k0, maxWidth, weight, cap);
    let svg = text(x, y, f.text, { ...o, size: f.size, role: ps[0]![1] });
    // (tests) one text that holds several roles says so
    const roles = [...new Set(ps.map((p) => p[1]))];
    if (tagging && roles.length > 1) svg = svg.replace(roleAttr(roles[0]), ` data-role="${roles.join(" ")}"`);
    return { svg, size: f.size };
  }
  // each candidate size in turn, every piece at its own factor of it; then smaller still
  const at = (c: number) => ps.map((p) => grow(c, t[p[1]], cap?.(c)));
  let words = ps.map((p) => p[0]);
  let z = at(cands[0]!);
  const width = (ts: string[]) => ts.reduce((a, s, i) => a + textWidth(s, z[i]!, weight), 0);
  for (const c of cands.slice(1)) {
    if (width(words) <= maxWidth) break;
    z = at(c);
  }
  const last0 = at(cands[cands.length - 1]!);
  for (const f of [0.9, 0.8, 0.72]) {
    if (width(words) <= maxWidth) break;
    z = last0.map((b) => b * f);
  }
  // a first piece asked to be no smaller is never smaller than the whole line was at 100 %
  const b0 = fitSize(words.join(""), cands, maxWidth, weight).size;
  if (t[ps[0]![1]] >= 1 && z[0]! < b0) z = ps.map((p) => b0 * Math.min(1, t[p[1]]));
  while (words.length > 1 && width(words) > maxWidth) {
    const last = words.length - 1;
    const left = maxWidth - width(words.slice(0, last));
    if (left >= textWidth(" W…", z[last]!, weight)) words[last] = fit(words[last]!, z[last]!, left, weight);
    else words = words.slice(0, last);
  }
  if (words.length === 1) words[0] = fit(words[0]!, z[0]!, maxWidth, weight);
  const head = text(x, y, words[0]!, { ...o, size: z[0]!, role: ps[0]![1] });
  const tail = words.slice(1).map((w, i) => `<tspan font-size="${n(z[i + 1]!)}"${roleAttr(ps[i + 1]![1])}>${esc(w)}</tspan>`).join("");
  return { svg: tail ? head.slice(0, -7) + tail + "</text>" : head, size: z[0]! };
}

/** The detail and the mode as the pieces of one line. */
export function pairParts(d: string, m: string): Part[] {
  return d && m ? [[d, "detail"], [" · " + m, "mode"]] : d ? [[d, "detail"]] : m ? [[m, "mode"]] : [];
}

export interface TextOpts {
  size: number;
  /** (1.3) What the text is, for its size (shown only to the tests, see tagRoles). */
  role?: TextRole;
  weight?: number;
  fill: string;
  anchor?: "start" | "middle" | "end";
  family?: string;
  opacity?: number;
  spacing?: number;
}

export function text(x: number, y: number, content: string, o: TextOpts): string {
  return `<text x="${n(x)}" y="${n(y)}" font-family="${esc(o.family ?? FONT)}" font-size="${n(o.size)}" font-weight="${o.weight ?? 600}" fill="${o.fill}"`
    + (o.anchor && o.anchor !== "start" ? ` text-anchor="${o.anchor}"` : "")
    + (o.opacity !== undefined ? ` fill-opacity="${n(o.opacity)}"` : "")
    + (o.spacing ? ` letter-spacing="${n(o.spacing)}"` : "")
    + roleAttr(o.role)
    + `>${esc(content)}</text>`;
}

/** A 24x24 stroke icon placed at x,y with the given size. */
export function icon(name: string, x: number, y: number, size: number, stroke: string, width = 1.7, fallback?: string): string {
  const s = size / 24;
  return `<g transform="translate(${n(x)} ${n(y)}) scale(${String(Math.round(s * 10000) / 10000)})" fill="none" stroke="${stroke}" stroke-width="${n(width)}" stroke-linecap="round" stroke-linejoin="round">${iconMarkup(name, fallback)}</g>`;
}

/** An arc of a circle from a0 to a1 (degrees, 0 = up, clockwise). */
export function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const sweep = Math.max(0, Math.min(359.99, a1 - a0));
  const p = (a: number) => {
    const rad = ((a - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)] as const;
  };
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a0 + sweep);
  return `M ${n(x0)} ${n(y0)} A ${n(r)} ${n(r)} 0 ${sweep > 180 ? 1 : 0} 1 ${n(x1)} ${n(y1)}`;
}

export function svgDoc(w: number, h: number, body: string, defs = ""): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`
    + (defs ? `<defs>${defs}</defs>` : "") + body + `</svg>`;
}

export function dataUri(svg: string): string {
  const B = (globalThis as { Buffer?: { from(s: string, e: string): { toString(e: string): string } } }).Buffer;
  if (B) return "data:image/svg+xml;base64," + B.from(svg, "utf8").toString("base64");
  return "data:image/svg+xml;charset=utf8," + encodeURIComponent(svg);
}

/** A colour with alpha as #RRGGBBAA would not survive every renderer: use opacity attributes instead. */
export function rect(x: number, y: number, w: number, h: number, r: number, fill: string, extra = ""): string {
  return `<rect x="${n(x)}" y="${n(y)}" width="${n(w)}" height="${n(h)}" rx="${n(r)}" fill="${fill}" ${extra}/>`;
}
