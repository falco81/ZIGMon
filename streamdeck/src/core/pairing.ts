import type { Install, PairStart, PairWait } from "./protocol.js";

/**
 * Pairing, device-code style: ask (pair) -> show the code -> wait (pair_wait) until the
 * administrator approves or denies it in ZIGMon, or it runs out (15 min). A pure reducer,
 * so every path is testable; the hub drives it with the real calls.
 */
export type PairState =
  | { phase: "idle" }
  | { phase: "requesting" }
  | { phase: "waiting"; pair: string; secret: string; code: string; expires: number; retries: number }
  | { phase: "approved"; token: string; install: Install | null }
  | { phase: "denied" }
  | { phase: "expired" }
  | { phase: "failed"; error: string };

export type PairEvent =
  | { type: "start" }
  | { type: "started"; answer: PairStart }
  | { type: "wait"; answer: PairWait }
  | { type: "tick"; now: number }
  | { type: "fail"; error: string; fatal: boolean }
  | { type: "cancel" };

export const IDLE: PairState = { phase: "idle" };

export function pairStep(s: PairState, e: PairEvent): PairState {
  if (e.type === "cancel") return IDLE;
  switch (s.phase) {
    case "idle":
    case "denied":
    case "expired":
    case "failed":
    case "approved":
      return e.type === "start" ? { phase: "requesting" } : s;
    case "requesting":
      if (e.type === "started") {
        return { phase: "waiting", pair: e.answer.pair, secret: e.answer.secret, code: e.answer.code, expires: e.answer.expires, retries: 0 };
      }
      if (e.type === "fail") return { phase: "failed", error: e.error };
      return s;
    case "waiting":
      if (e.type === "wait") {
        const a = e.answer;
        if (a.state === "approved" && a.token) return { phase: "approved", token: a.token, install: a.install };
        if (a.state === "denied") return { phase: "denied" };
        if (a.state === "expired") return { phase: "expired" };
        return s.retries === 0 ? s : { ...s, retries: 0 };
      }
      if (e.type === "tick") return e.now >= s.expires * 1000 ? { phase: "expired" } : s;
      if (e.type === "fail") return e.fatal ? { phase: "failed", error: e.error } : { ...s, retries: s.retries + 1 };
      if (e.type === "start") return { phase: "requesting" };
      return s;
  }
}

/** What may be shown of a pairing (never the secret, never the key). */
export function pairView(s: PairState): { phase: PairState["phase"]; code?: string; expires?: number; error?: string } {
  switch (s.phase) {
    case "waiting":
      return { phase: s.phase, code: s.code, expires: s.expires };
    case "failed":
      return { phase: s.phase, error: s.error };
    default:
      return { phase: s.phase };
  }
}
