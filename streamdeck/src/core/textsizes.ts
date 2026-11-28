/**
 * (1.3) Text sizes: each kind of text on a key (svg.ts TEXT_ROLES) has a setting of its own, a
 * percentage 50-200 in steps of 5; none is 100 %. Shared by the plugin and the property inspector.
 */
import { TEXT_ROLES, type TextRole, type TextScale } from "./svg.js";

/** (1.3) The setting of each text role's size. */
export const TEXT_KEYS: Readonly<Record<TextRole, string>> = {
  value: "textValue", name: "textName", room: "textRoom", detail: "textDetail", mode: "textMode", unit: "textUnit", badge: "textBadge",
};
export const TEXT_MIN = 50;
export const TEXT_MAX = 200;
export const TEXT_STEP = 5;

/** (1.3) A text size as stored: a whole multiple of 5 from 50 to 200, but 100 (the default) - else nothing. */
export function cleanTextSize(v: unknown): number | undefined {
  if (typeof v !== "number" || !Number.isInteger(v) || v < TEXT_MIN || v > TEXT_MAX || v % TEXT_STEP !== 0 || v === 100) return undefined;
  return v;
}

/** (1.3) The text sizes among some settings, by their keys (only the valid ones, 100 left out). */
export function textSizesOf(o: Record<string, unknown>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of TEXT_ROLES) {
    const v = cleanTextSize(o[TEXT_KEYS[r]]);
    if (v !== undefined) out[TEXT_KEYS[r]] = v;
  }
  return out;
}

/** (1.3) The factors a key draws its text at: its own sizes, else its action type's defaults, else 100 %. */
export function textScaleOf(own: Record<string, unknown>, defaults?: Record<string, unknown> | null): TextScale {
  const k = {} as Record<TextRole, number>;
  for (const r of TEXT_ROLES) {
    const key = TEXT_KEYS[r];
    const v = cleanTextSize(own[key]) ?? cleanTextSize(defaults?.[key]) ?? 100;
    k[r] = v === 100 ? 1 : v / 100;
  }
  return k;
}
