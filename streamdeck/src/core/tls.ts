import { timingSafeEqual } from "node:crypto";

/**
 * The one rule of certificates, as the notifier has it: with no pin, only what the system
 * trusts (chain and name). With a pin, only the pinned certificate - trusted chain or not.
 */
export type Verdict = "trusted" | "pinned" | "untrusted" | "pin-mismatch" | "missing";

/** 64 upper-case hex digits, or null when it is not a SHA-256 fingerprint. */
export function normalizePin(pin: unknown): string | null {
  if (typeof pin !== "string" || pin.trim() === "") return null;
  const h = pin.replace(/[:\s-]/g, "");
  if (!/^[0-9a-fA-F]{64}$/.test(h)) return null;
  return h.toUpperCase();
}

/** AB:CD:... as browsers and ZIGMon's settings show it. */
export function formatFingerprint(sha256: string): string {
  const h = normalizePin(sha256);
  if (!h) return sha256;
  return h.match(/../g)!.join(":");
}

export function pinMatches(certSha256: string | null | undefined, pin: string | null | undefined): boolean {
  const a = normalizePin(certSha256), b = normalizePin(pin);
  if (!a || !b) return false;
  return timingSafeEqual(Buffer.from(a, "hex"), Buffer.from(b, "hex"));
}

/**
 * @param certSha256 the server certificate's SHA-256 (any notation), null when there was none
 * @param systemTrusted the chain verified against the system's roots AND the name matched
 * @param pin the pin kept for this host:port, if any
 */
export function evaluate(certSha256: string | null | undefined, systemTrusted: boolean, pin: string | null | undefined): Verdict {
  if (!normalizePin(certSha256)) return "missing";
  if (normalizePin(pin)) return pinMatches(certSha256, pin) ? "pinned" : "pin-mismatch";
  return systemTrusted ? "trusted" : "untrusted";
}

export function accepted(v: Verdict): boolean {
  return v === "trusted" || v === "pinned";
}

/** A pin store kept in the global settings: host:port -> SHA-256. */
export type Pins = Record<string, string>;

export function pinFor(pins: Pins | undefined, scope: string): string | null {
  if (!pins || !Object.prototype.hasOwnProperty.call(pins, scope)) return null;
  return normalizePin(pins[scope]);
}

export function withPin(pins: Pins | undefined, scope: string, sha256: string | null): Pins {
  const out: Pins = {};
  for (const [k, v] of Object.entries(pins ?? {})) if (k !== scope && normalizePin(v)) out[k] = normalizePin(v)!;
  const n = normalizePin(sha256);
  if (n) out[scope] = n;
  return out;
}
