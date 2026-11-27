import * as http from "node:http";
import { isIP } from "node:net";
import * as tls from "node:tls";
import type { ServerAddress } from "./address.js";
import { accepted, evaluate, formatFingerprint, type Verdict } from "./tls.js";

/** The connection failed (no answer, refused, timed out, cut off...). Never carries a secret. */
export class NetError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetError";
  }
}

/** The server's certificate was not accepted; fingerprint is what the user may choose to pin. */
export class CertError extends Error {
  constructor(public readonly verdict: Verdict, public readonly fingerprint: string | null) {
    super(
      verdict === "pin-mismatch"
        ? "The server's certificate is not the one pinned for it - refused."
        : verdict === "missing"
          ? "The server sent no certificate."
          : "This computer does not trust the server's certificate.",
    );
    this.name = "CertError";
  }
}

/** ZIGMon answered, but not with 2xx. body is its JSON (if any) for the caller to read flags from. */
export class ApiError extends Error {
  constructor(public readonly status: number, public readonly body: Record<string, unknown>, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export interface HttpRequest {
  url: string;
  method: "GET" | "POST";
  headers: Record<string, string>;
  body?: Buffer;
  timeoutMs: number;
  maxBytes: number;
  /** The SHA-256 pinned for this host:port (or null). */
  pin: string | null;
  signal?: AbortSignal;
}

export interface HttpResponse {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: Buffer;
}

export interface Transport {
  request(req: HttpRequest): Promise<HttpResponse>;
}

let cachedCa: string[] | undefined;
/** Node's bundled roots plus the ones the system (Windows' certificate store) trusts. */
export function systemCa(): string[] {
  if (cachedCa) return cachedCa;
  const t = tls as unknown as { getCACertificates?: (kind: string) => string[] };
  const set = new Set<string>(tls.rootCertificates);
  try {
    for (const c of t.getCACertificates?.("system") ?? []) set.add(c);
  } catch {
    /* no system store on this platform */
  }
  cachedCa = [...set];
  return cachedCa;
}

/** What the last refused certificate was, so the property inspector can offer to pin it. */
export interface CertSeen {
  scope: string;
  fingerprint: string;
  verdict: Verdict;
  subject: string;
  issuer: string;
  validTo: string;
}

/**
 * The plugin's only way to the network: http(s) to the one address, no proxies, no redirects
 * (a 3xx is an error), a size cap, a deadline, and certificates judged by evaluate() BEFORE a
 * single byte of the request (with its key) is written.
 */
export class NodeTransport implements Transport {
  lastCert: CertSeen | null = null;
  constructor(private readonly address: ServerAddress, private readonly ca: () => string[] = systemCa) {}

  async request(req: HttpRequest): Promise<HttpResponse> {
    const u = new URL(req.url);
    if (u.protocol + "//" + u.host !== new URL(this.address.base).protocol + "//" + new URL(this.address.base).host) {
      throw new NetError("refusing to talk to another server");
    }
    const deadline = AbortSignal.timeout(req.timeoutMs);
    const signal = req.signal ? AbortSignal.any([req.signal, deadline]) : deadline;
    const socket = this.address.https ? await this.secureSocket(req.pin, signal) : undefined;
    return await new Promise<HttpResponse>((resolve, reject) => {
      const opts: http.RequestOptions = {
        host: this.address.host,
        port: this.address.port,
        path: u.pathname + u.search,
        method: req.method,
        headers: { ...req.headers, Connection: "close", ...(req.body ? { "Content-Length": String(req.body.length) } : {}) },
        signal,
      };
      if (socket) opts.createConnection = () => socket;
      else opts.agent = new http.Agent({ keepAlive: false });
      const r = http.request(opts, (res) => {
        const status = res.statusCode ?? 0;
        if (status >= 300 && status < 400) {
          res.destroy();
          reject(new NetError("ZIGMon answered with a redirect (" + status + ") - not followed. Check the address."));
          return;
        }
        const declared = Number(res.headers["content-length"] ?? "0");
        if (declared > req.maxBytes) {
          res.destroy();
          reject(new NetError("the answer is too big"));
          return;
        }
        const chunks: Buffer[] = [];
        let n = 0;
        res.on("data", (c: Buffer) => {
          n += c.length;
          if (n > req.maxBytes) {
            res.destroy();
            reject(new NetError("the answer is too big"));
            return;
          }
          chunks.push(c);
        });
        res.on("end", () => resolve({ status, headers: res.headers, body: Buffer.concat(chunks) }));
        res.on("error", (e) => reject(netError(e, signal)));
      });
      r.on("error", (e) => reject(netError(e, signal)));
      if (req.body) r.write(req.body);
      r.end();
    });
  }

  private secureSocket(pin: string | null, signal: AbortSignal): Promise<tls.TLSSocket> {
    const host = this.address.host.replace(/^\[|\]$/g, "");
    return new Promise((resolve, reject) => {
      const s = tls.connect({
        host,
        port: this.address.port,
        servername: isIP(host) ? undefined : host,
        ca: this.ca(),
        // judged below, before anything is sent: a pin must be able to accept a self-signed cert
        rejectUnauthorized: false,
        ALPNProtocols: ["http/1.1"],
        minVersion: "TLSv1.2",
      });
      const onAbort = () => {
        s.destroy();
        reject(new NetError(signal.reason?.name === "TimeoutError" ? "ZIGMon did not answer in time" : "cancelled"));
      };
      signal.addEventListener("abort", onAbort, { once: true });
      s.once("error", (e) => {
        signal.removeEventListener("abort", onAbort);
        reject(netError(e, signal));
      });
      s.once("secureConnect", () => {
        signal.removeEventListener("abort", onAbort);
        const cert = s.getPeerCertificate();
        const fp = cert && cert.fingerprint256 ? cert.fingerprint256 : null;
        let trusted = s.authorized;
        if (trusted && cert && Object.keys(cert).length > 0) {
          if (tls.checkServerIdentity(host, cert) !== undefined) trusted = false;
        }
        const verdict = evaluate(fp, trusted, pin);
        if (!accepted(verdict)) {
          s.destroy();
          this.lastCert = fp
            ? {
                scope: this.address.pinScope,
                fingerprint: formatFingerprint(fp),
                verdict,
                subject: String(cert.subject?.CN ?? "").slice(0, 120),
                issuer: String(cert.issuer?.CN ?? cert.issuer?.O ?? "").slice(0, 120),
                validTo: String(cert.valid_to ?? "").slice(0, 40),
              }
            : null;
          reject(new CertError(verdict, fp ? formatFingerprint(fp) : null));
          return;
        }
        resolve(s);
      });
    });
  }
}

function netError(e: unknown, signal: AbortSignal): Error {
  if (e instanceof NetError || e instanceof CertError) return e;
  if (signal.aborted) return new NetError(signal.reason?.name === "TimeoutError" ? "ZIGMon did not answer in time" : "cancelled");
  const code = (e as { code?: string }).code ?? "";
  const words: Record<string, string> = {
    ECONNREFUSED: "nothing answers at that address (connection refused)",
    ENOTFOUND: "that server name is not known (DNS)",
    EAI_AGAIN: "that server name could not be looked up right now",
    ETIMEDOUT: "ZIGMon did not answer in time",
    ECONNRESET: "the connection was cut off",
    EHOSTUNREACH: "that server cannot be reached",
    ENETUNREACH: "the network cannot be reached",
  };
  return new NetError(words[code] ?? (code ? "the connection failed (" + code + ")" : "the connection failed"));
}
