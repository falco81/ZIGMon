import type { Attr, Item } from "./protocol.js";

/** Which number attribute a dial turns, by what the action is about. */
const PREFER: Record<string, RegExp[]> = {
  dimmer: [/^brightness$/i, /bright/i, /level/i, /dim/i],
  thermostat: [/^(current_heating_setpoint|occupied_heating_setpoint|setpoint|target)$/i, /setpoint/i, /target/i, /temp/i],
  blinds: [/^position$/i, /position/i, /^(level|tilt)$/i],
  control: [/bright/i, /setpoint/i, /position/i, /level/i],
};

export function dialAttr(item: Item | undefined, purpose: keyof typeof PREFER | string): Attr | null {
  if (!item) return null;
  const nums = item.attrs.filter((a) => a.type === "number");
  if (nums.length === 0) return null;
  for (const re of PREFER[purpose] ?? []) {
    const hit = nums.find((a) => re.test(a.key));
    if (hit) return hit;
  }
  return nums[0]!;
}

export function enumAttr(item: Item | undefined, re: RegExp): Attr | null {
  if (!item) return null;
  return item.attrs.find((a) => a.type === "enum" && re.test(a.key) && a.values.length > 0) ?? null;
}

export function boolAttr(item: Item | undefined, re: RegExp): Attr | null {
  if (!item) return null;
  return item.attrs.find((a) => a.type === "bool" && re.test(a.key)) ?? null;
}

/** Decimals a step implies: 0.5 -> 1, 1 -> 0, 0.25 -> 2. */
export function decimalsOf(step: number): number {
  const s = String(step);
  const i = s.indexOf(".");
  return i < 0 ? 0 : Math.min(4, s.length - i - 1);
}

export function roundTo(v: number, step: number, base = 0): number {
  if (!(step > 0)) return v;
  const r = Math.round((v - base) / step) * step + base;
  return Number(r.toFixed(decimalsOf(step)));
}

export function clamp(v: number, min: number | null, max: number | null): number {
  let x = v;
  if (min !== null && x < min) x = min;
  if (max !== null && x > max) x = max;
  return x;
}

/**
 * One turn of a dial: `ticks` clicks of `step` each from `current`, kept within the
 * attribute's min..max and on its own step grid. delta is what ZIGMon gets: the change
 * actually made (0 when already at the end).
 */
export function stepValue(current: number, ticks: number, step: number, attr: Pick<Attr, "min" | "max" | "step">): { value: number; delta: number } {
  const grid = attr.step ?? step;
  const target = clamp(current + ticks * step, attr.min, attr.max);
  let value = roundTo(target, grid, attr.min ?? 0);
  value = clamp(value, attr.min, attr.max);
  const delta = Number((value - current).toFixed(Math.max(decimalsOf(grid), decimalsOf(step))));
  return { value, delta };
}

/** The share of min..max a value is (0..1), for bars. */
export function fraction(v: number | null, min: number | null, max: number | null): number {
  if (v === null) return 0;
  const lo = min ?? 0, hi = max ?? 100;
  if (hi <= lo) return 0;
  return Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
}

/**
 * Turns of a dial, gathered: each tick moves the shown value at once; the sum goes to
 * ZIGMon after a short pause, one request at a time, so a quick spin is one command.
 */
export class DialAccumulator {
  private pendingTicks = 0;
  private optimistic: number | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inFlight = false;

  constructor(
    private readonly send: (delta: number, value: number) => Promise<void>,
    private readonly settleMs = 140,
  ) {}

  /** The value to show now, or null when nothing is pending. */
  get shown(): number | null {
    return this.optimistic;
  }

  get busy(): boolean {
    return this.pendingTicks !== 0 || this.inFlight || this.timer !== null;
  }

  /** @returns the new value to draw at once */
  turn(ticks: number, current: number, step: number, attr: Pick<Attr, "min" | "max" | "step">): number {
    const from = this.optimistic ?? current;
    const { value } = stepValue(from, ticks, step, attr);
    this.optimistic = value;
    this.pendingTicks += ticks;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(current, attr), this.settleMs);
    return value;
  }

  private base: number | null = null;

  private async flush(current: number, _attr: Pick<Attr, "min" | "max" | "step">): Promise<void> {
    this.timer = null;
    if (this.inFlight) {
      this.timer = setTimeout(() => void this.flush(current, _attr), this.settleMs);
      return;
    }
    const target = this.optimistic;
    if (target === null) return;
    const from = this.base ?? current;
    const delta = Number((target - from).toFixed(4));
    this.pendingTicks = 0;
    if (delta === 0) {
      this.optimistic = null;
      return;
    }
    this.inFlight = true;
    this.base = target;
    try {
      await this.send(delta, target);
    } finally {
      this.inFlight = false;
      if (this.timer === null && this.pendingTicks === 0) {
        this.optimistic = null;
        this.base = null;
      }
    }
  }

  cancel(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.pendingTicks = 0;
    this.optimistic = null;
    this.base = null;
  }
}
