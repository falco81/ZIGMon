/**
 * The dashboard address the user typed, checked and normalised like the notifier's ServerAddress:
 * https only (plain http only to this very computer), no user:password@, no query or fragment,
 * a trailing "/index.php" or "/" dropped. The deck API is the relay's index.php?api=deck&do=...
 */
export interface ServerAddress {
  /** e.g. "https://zigmon.example.net" or "https://host:8443/zigmon" - never ends with '/'. */
  base: string;
  host: string;
  port: number;
  https: boolean;
  /** host:port, what a certificate pin belongs to. */
  pinScope: string;
}

export const DOS = ["pair", "pair_wait", "hello", "catalog", "state", "wait", "do", "update", "download"] as const;
export type Do = (typeof DOS)[number];

export function isLocalHost(host: string): boolean {
  const h = host.trim().toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "[::1]";
}

export type AddressResult = { ok: true; address: ServerAddress } | { ok: false; error: string };

export function parseAddress(input: unknown): AddressResult {
  let s = typeof input === "string" ? input.trim() : "";
  if (s.length === 0) return { ok: false, error: "Enter the address of your ZIGMon dashboard." };
  if (s.length > 300) return { ok: false, error: "That address is too long." };
  for (const c of s) {
    const code = c.codePointAt(0)!;
    if (code <= 32 || c === "\\" || (code > 126 && !/\p{L}|\p{N}/u.test(c))) {
      return { ok: false, error: "The address has a character an address cannot have (a space or a backslash?)." };
    }
  }
  if (!s.includes("://")) s = "https://" + s;
  if (s.includes("?") || s.includes("#")) return { ok: false, error: "Use the dashboard address only, without a ?... or #... part." };
  let u: URL;
  try {
    u = new URL(s);
  } catch {
    return { ok: false, error: "That does not look like a web address (for example https://zigmon.example.net)." };
  }
  const https = u.protocol === "https:";
  if (!https && u.protocol !== "http:") return { ok: false, error: "Only https:// addresses can be used." };
  if (u.username || u.password) return { ok: false, error: "Leave the name and password out of the address - pairing does the signing in." };
  const host = u.hostname.toLowerCase();
  if (!host) return { ok: false, error: "The address has no server name." };
  if (!https && !isLocalHost(host)) {
    return { ok: false, error: "Plain http:// would send the key unprotected - use https:// (http is only allowed for localhost)." };
  }
  let path = u.pathname;
  for (;;) {
    if (path.toLowerCase().endsWith("/index.php")) path = path.slice(0, -"/index.php".length);
    else if (path.endsWith("/")) path = path.slice(0, -1);
    else break;
  }
  if (path.includes("//") || /(^|\/)\.\.?(\/|$)/.test(path)) return { ok: false, error: "The path in that address looks wrong." };
  const port = u.port ? Number(u.port) : https ? 443 : 80;
  const base = u.protocol + "//" + u.host.toLowerCase() + path;
  return { ok: true, address: { base, host, port, https, pinScope: host + ":" + port } };
}

/** {base}/index.php?api=deck&do=<do>[&query] - the only URLs the plugin ever asks for. */
export function endpoint(a: ServerAddress, what: Do, query?: Record<string, string>): string {
  if (!(DOS as readonly string[]).includes(what)) throw new RangeError("unknown deck call");
  const q = new URLSearchParams({ api: "deck", do: what });
  for (const [k, v] of Object.entries(query ?? {})) q.append(k, v);
  return a.base + "/index.php?" + q.toString();
}
