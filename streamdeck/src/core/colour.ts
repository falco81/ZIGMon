/**
 * (1.3) A colour the user typed or picked: exactly "#RRGGBB", kept uppercased. Shared by the
 * settings (which accept nothing else) and the property inspector's picker (which sends nothing
 * else). Only the user's own settings ever give one; nothing from the server becomes a colour.
 */

export const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/** "#RRGGBB" uppercased, or null for anything else. */
export function cleanHex(v: unknown): string | null {
  return typeof v === "string" && HEX_RE.test(v) ? v.toUpperCase() : null;
}

export interface Hsv {
  /** 0..360 */
  h: number;
  /** 0..1 */
  s: number;
  /** 0..1 */
  v: number;
}

const clamp = (a: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, a));

export function hsvToHex(c: Hsv): string {
  const h = ((c.h % 360) + 360) % 360, s = clamp(c.s, 0, 1), v = clamp(c.v, 0, 1);
  const f = (k: number) => {
    const x = (k + h / 60) % 6;
    return v - v * s * Math.max(0, Math.min(x, 4 - x, 1));
  };
  const hex = (a: number) => Math.round(a * 255).toString(16).padStart(2, "0");
  return ("#" + hex(f(5)) + hex(f(3)) + hex(f(1))).toUpperCase();
}

/** The hue, saturation and value of "#RRGGBB"; a grey keeps `hueHint` so the hue slider does not jump. */
export function hexToHsv(hex: string, hueHint = 0): Hsv {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = hueHint;
  if (d > 1e-9) {
    if (max === r) h = 60 * (((g - b) / d) % 6);
    else if (max === g) h = 60 * ((b - r) / d + 2);
    else h = 60 * ((r - g) / d + 4);
    if (h < 0) h += 360;
  }
  return { h, s: max === 0 ? 0 : d / max, v: max };
}
