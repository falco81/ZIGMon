/** How long a key or dial must be held when ZIGMon asks for a confirmation (`hold`). */
export const HOLD_MS = 1500;

export interface HoldHandlers {
  /** 0..1 while the ring fills. */
  progress(p: number): void;
  /** The press counts: held_ms when a hold was needed, else undefined. */
  fire(heldMs: number | undefined): void;
  /** Let go too early. */
  tooShort(): void;
}

/**
 * One press of a key or dial. Without hold it fires at once on the way down; with hold it
 * draws a filling ring and fires the moment HOLD_MS has passed (no need to let go first),
 * reporting the real time held. Letting go earlier cancels it.
 */
export class HoldPress {
  private startedAt = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private fired = false;
  private active = false;

  constructor(
    private readonly needsHold: boolean,
    private readonly h: HoldHandlers,
    private readonly now: () => number = Date.now,
    private readonly frameMs = 60,
  ) {}

  get running(): boolean {
    return this.active;
  }

  down(): void {
    if (this.active) return;
    this.active = true;
    this.fired = false;
    this.startedAt = this.now();
    if (!this.needsHold) {
      this.fired = true;
      this.h.fire(undefined);
      return;
    }
    this.h.progress(0);
    this.timer = setInterval(() => this.tick(), this.frameMs);
  }

  /** Also called by tests with a fake clock. */
  tick(): void {
    if (!this.active || this.fired) return;
    const held = this.now() - this.startedAt;
    if (held >= HOLD_MS) {
      this.stop();
      this.fired = true;
      this.h.progress(1);
      this.h.fire(held);
      return;
    }
    this.h.progress(held / HOLD_MS);
  }

  up(): void {
    if (!this.active) return;
    if (this.needsHold && !this.fired) {
      const held = this.now() - this.startedAt;
      if (held >= HOLD_MS) {
        this.tick();
      } else {
        this.stop();
        this.h.tooShort();
      }
    }
    this.stop();
    this.active = false;
  }

  cancel(): void {
    this.stop();
    this.active = false;
  }

  private stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
