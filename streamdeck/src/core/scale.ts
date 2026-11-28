/**
 * (1.3) Honest scales. Every graphic on a key that implies a magnitude - a level bar, an arc, a
 * fill, columns, a sparkline - is drawn against a real scale, never stretched from the lowest to
 * the highest value seen (which made a wobble of 0.03 °C fill the whole height):
 *   - a level (0..1) only from a real range: an attribute's min / max, a percentage, a battery;
 *   - a series against the attribute's min / max when known, else from 0 for what counts up from
 *     0 (W, kWh, lux, ppm, counts...), else at least a sensible span for the unit (4 °C, 10 %RH,
 *     10 hPa...) centred on the data - so a flat line looks flat and a real change looks its size.
 */

/** What a series measures: its unit (or "%RH" for humidity), and its true range when known. */
export interface Quantity {
  unit: string;
  min?: number | null;
  max?: number | null;
}

/** The smallest span a graph of these units shows, centred on the data. */
export const MIN_SPAN: Readonly<Record<string, number>> = {
  "°C": 4, "°F": 8, "K": 4, "%RH": 10, "hPa": 10, "mbar": 10, "kPa": 1, "mmHg": 8, "V": 10, "Hz": 1,
  "dB": 10, "dBA": 10, "dBm": 10, "pH": 1, "°": 30, "m/s": 2, "km/h": 5,
};

/** Units of what starts at 0: a graph of them stands on 0. */
const FROM_ZERO = new Set([
  "W", "kW", "MW", "Wh", "kWh", "MWh", "VA", "var", "A", "mA", "lx", "lux", "ppm", "ppb", "µg/m³", "μg/m³", "ug/m3", "mg/m³",
  "l", "L", "m³", "l/h", "l/min", "L/min", "m³/h", "mm", "mm/h", "s", "min", "h", "B", "kB", "MB", "GB", "",
]);

/** The scale (lo..hi) a series is drawn against, with `also` (a target) kept inside it. */
export function seriesScale(values: readonly number[], q: Quantity | null | undefined, also: readonly number[] = []): { lo: number; hi: number } {
  const v = [...values, ...also].filter((a) => Number.isFinite(a));
  if (!v.length) return { lo: 0, hi: 1 };
  let lo = Math.min(...v), hi = Math.max(...v);
  const unit = q?.unit ?? "";
  const min = q?.min ?? null, max = q?.max ?? (unit === "%" ? 100 : null);
  const from = min ?? (unit === "%" ? 0 : null);
  if (from !== null && max !== null && max > from) return { lo: Math.min(from, lo), hi: Math.max(max, hi) };
  if (from !== null || (FROM_ZERO.has(unit) && lo >= 0) || (!(unit in MIN_SPAN) && lo >= 0)) {
    // from 0 (or the attribute's own minimum) up to the highest value
    const base = from ?? Math.min(0, lo);
    lo = Math.min(base, lo);
    if (hi - lo < 1e-9) hi = lo + 1;
    return { lo, hi };
  }
  const need = MIN_SPAN[unit] ?? Math.max(1, (Math.abs(lo) + Math.abs(hi)) * 0.05);
  if (hi - lo < need) {
    const mid = (lo + hi) / 2;
    lo = mid - need / 2;
    hi = mid + need / 2;
  }
  return { lo, hi };
}

/** Where `v` stands in min..max (0..1), or null with no real range. */
export function levelIn(v: number | null, min: number | null | undefined, max: number | null | undefined): number | null {
  if (v === null || !Number.isFinite(v) || min === null || min === undefined || max === null || max === undefined || !(max > min)) return null;
  return Math.max(0, Math.min(1, (v - min) / (max - min)));
}

/** The true level of a reading: within its attribute's range, else as a percentage; null without either. */
export function readingLevel(v: number | null, q: Quantity): number | null {
  const own = levelIn(v, q.min, q.max);
  if (own !== null) return own;
  return q.unit === "%" || q.unit === "%RH" ? levelIn(v, q.min ?? 0, q.max ?? 100) : null;
}

/**
 * The quantity a reading measures, from its attribute: humidity as "%RH" so its graph keeps a 10 %
 * span; the attribute's min / max only when `ranged` (the value shown is that attribute's).
 */
export function quantityOf(attr: { key: string; unit?: string | null; min?: number | null; max?: number | null } | null | undefined, ranged = true): Quantity {
  const unit = attr?.unit ?? "";
  const humid = unit === "%" && !!attr && /humid/i.test(attr.key);
  return { unit: humid ? "%RH" : unit, min: ranged ? attr?.min ?? null : null, max: ranged ? attr?.max ?? null : null };
}
