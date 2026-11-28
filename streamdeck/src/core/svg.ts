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

export interface TextOpts {
  size: number;
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
