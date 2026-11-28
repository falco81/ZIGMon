import { endpoint, type Do, type ServerAddress } from "./address.js";
import { ApiError, NetError, type Transport } from "./http.js";
import {
  cleanText, parseCatalog, parseDo, parseHello, parsePairStart, parsePairWait, parseStateAnswer, parseUpdate, parseWait,
  ProtocolError, type Catalog, type DoAnswer, type Hello, type ItemAction, type PairStart, type PairWait, type StateAnswer,
  type UpdateAnswer, type WaitAnswer,
} from "./protocol.js";
import { PLUGIN_VERSION } from "./version.js";

export interface DeckInfo {
  id: string;
  type: number;
  name: string;
  cols: number;
  rows: number;
}

export interface Credentials {
  token: string;
  install: string;
}

export interface Command {
  deck: string;
  id: string;
  action: ItemAction;
  attr?: string;
  value?: number | string | boolean;
  delta?: number;
  held_ms?: number;
  /** (1.2) "By hand", as a button's: a press that leaves it on takes it over from the rules. */
  by_hand?: boolean;
  /** (1.3, ZIGMon 5.59.4) `timer`: on now, off after this many minutes (1-720); `mute`: hushed this long (15-240). */
  minutes?: number;
  /** (1.3) `sms:compose`: whom the desktop app's new message is to - numbers, `group:<name>`, `contact:<id>` (at most 20). */
  to?: string[];
}

/** (1.3) Asked of ZIGMon 5.59.4 and later only (its hello says "extended"): the summaries, `act`, `members`, `timer`. */
export interface Ask {
  extended?: boolean;
}

export const CLIENT_NAME = "ZIGMon-StreamDeck/" + PLUGIN_VERSION;
const HEADER_SAFE = /^[A-Za-z0-9_-]{1,80}$/;

/** decks=id,id and deck_info=<base64url JSON> (at most 2 KB: names are cut, then decks dropped). */
export function deckQuery(decks: DeckInfo[]): Record<string, string> {
  if (decks.length === 0) return {};
  const ids = decks.map((d) => d.id);
  let list = decks.map((d) => ({ id: d.id, type: d.type, name: cleanText(d.name, 40), cols: d.cols, rows: d.rows }));
  let info = Buffer.from(JSON.stringify(list)).toString("base64url");
  while (info.length > 2048 && list.length > 0) {
    list = list.map((d) => ({ ...d, name: cleanText(d.name, 12) }));
    info = Buffer.from(JSON.stringify(list)).toString("base64url");
    if (info.length > 2048) {
      list = list.slice(0, -1);
      info = Buffer.from(JSON.stringify(list)).toString("base64url");
    }
  }
  const q: Record<string, string> = { decks: ids.join(",") };
  if (list.length > 0) q.deck_info = info;
  return q;
}

/** The deck API, one call per method; every answer goes through protocol.ts' strict parsers. */
export class ZigmonClient {
  constructor(
    private readonly address: ServerAddress,
    private readonly transport: Transport,
    private readonly pin: () => string | null,
  ) {}

  private async call(what: Do, opts: {
    query?: Record<string, string>;
    body?: unknown;
    creds?: Credentials;
    pairSecret?: string;
    timeoutMs?: number;
    maxBytes?: number;
    signal?: AbortSignal;
    raw?: boolean;
  }): Promise<{ json: unknown; raw: Buffer }> {
    const headers: Record<string, string> = { "X-Zigmon-Client": CLIENT_NAME, Accept: opts.raw ? "application/octet-stream" : "application/json" };
    if (opts.creds) {
      if (!HEADER_SAFE.test(opts.creds.token) || !HEADER_SAFE.test(opts.creds.install)) throw new ProtocolError("the stored key is malformed");
      headers["X-Zigmon-Deck"] = opts.creds.token;
      headers["X-Zigmon-Deck-Install"] = opts.creds.install;
    }
    if (opts.pairSecret) {
      if (!HEADER_SAFE.test(opts.pairSecret)) throw new ProtocolError("the pairing secret is malformed");
      headers["X-Zigmon-Deck-Pair"] = opts.pairSecret;
    }
    let body: Buffer | undefined;
    if (opts.body !== undefined) {
      body = Buffer.from(JSON.stringify(opts.body), "utf8");
      if (body.length > 16 * 1024) throw new ProtocolError("the request is too big");
      headers["Content-Type"] = "application/json";
    }
    const res = await this.transport.request({
      url: endpoint(this.address, what, opts.query),
      method: body ? "POST" : "GET",
      headers,
      body,
      timeoutMs: opts.timeoutMs ?? 15_000,
      maxBytes: opts.maxBytes ?? 4 * 1024 * 1024,
      pin: this.pin(),
      signal: opts.signal,
    });
    if (opts.raw && res.status === 200) return { json: null, raw: res.body };
    let json: unknown = null;
    try {
      json = res.body.length ? JSON.parse(res.body.toString("utf8")) : null;
    } catch {
      json = null;
    }
    if (res.status < 200 || res.status >= 300) {
      const o = json && typeof json === "object" && !Array.isArray(json) ? (json as Record<string, unknown>) : {};
      const msg = cleanText(o.error, 200) || httpWords(res.status);
      throw new ApiError(res.status, o, msg);
    }
    if (json === null) throw new NetError("ZIGMon's answer is not JSON - is this the address of a ZIGMon dashboard?");
    return { json, raw: res.body };
  }

  async pair(install: string, computer: string, decks: DeckInfo[]): Promise<PairStart> {
    const body = {
      install, computer: cleanText(computer, 60), plugin: PLUGIN_VERSION,
      decks: decks.slice(0, 8).map((d) => ({ id: d.id, type: d.type, name: cleanText(d.name, 40), cols: d.cols, rows: d.rows })),
    };
    return parsePairStart((await this.call("pair", { body })).json);
  }

  async pairWait(secret: string, signal?: AbortSignal): Promise<PairWait> {
    return parsePairWait((await this.call("pair_wait", { pairSecret: secret, timeoutMs: 45_000, signal })).json);
  }

  async hello(creds: Credentials, decks: DeckInfo[]): Promise<Hello> {
    return parseHello((await this.call("hello", { creds, query: deckQuery(decks) })).json);
  }

  /**
   * (1.3) Extended, the question goes as a POST body with "extended": true - the PHP relay forwards
   * a body whole but drops query parameters it does not know - and everything else rides in it too.
   */
  async catalog(creds: Credentials, decks: DeckInfo[], ask: Ask = {}): Promise<Catalog> {
    if (ask.extended) return parseCatalog((await this.call("catalog", { creds, body: { extended: true, ...deckQuery(decks) }, timeoutMs: 25_000 })).json);
    return parseCatalog((await this.call("catalog", { creds, query: deckQuery(decks), timeoutMs: 25_000 })).json);
  }

  async state(creds: Credentials, ids: string[], decks: DeckInfo[] = [], ask: Ask = {}): Promise<StateAnswer> {
    if (ask.extended) return parseStateAnswer((await this.call("state", { creds, body: { extended: true, ids: ids.join(","), ...deckQuery(decks) } })).json);
    return parseStateAnswer((await this.call("state", { creds, query: { ids: ids.join(","), ...deckQuery(decks) } })).json);
  }

  /** (for Stream Deck 1.1) The states with their recent history: ZIGMon thins it to `points` over `span` seconds. */
  async history(creds: Credentials, ids: string[], span: number, points: number, decks: DeckInfo[] = [], ask: Ask = {}): Promise<StateAnswer> {
    const history = { span: Math.round(span), points: Math.round(points) };
    if (ask.extended) return parseStateAnswer((await this.call("state", { creds, body: { extended: true, ids: ids.join(","), history, ...deckQuery(decks) } })).json);
    const body = { ids: ids.join(","), history };
    return parseStateAnswer((await this.call("state", { creds, query: deckQuery(decks), body })).json);
  }

  async wait(creds: Credentials, after: number, boot: string, ids: string[], decks: DeckInfo[], signal?: AbortSignal, ask: Ask = {}): Promise<WaitAnswer> {
    if (ask.extended) {
      const body: Record<string, unknown> = { extended: true, after, boot, ...deckQuery(decks) };
      if (ids.length) body.ids = ids.join(",");
      return parseWait((await this.call("wait", { creds, body, timeoutMs: 45_000, signal })).json);
    }
    const query: Record<string, string> = { after: String(after), boot, ...deckQuery(decks) };
    if (ids.length) query.ids = ids.join(",");
    return parseWait((await this.call("wait", { creds, query, timeoutMs: 45_000, signal })).json);
  }

  async do(creds: Credentials, cmd: Command): Promise<DoAnswer> {
    return parseDo((await this.call("do", { creds, body: cmd })).json);
  }

  async update(creds: Credentials): Promise<UpdateAnswer> {
    return parseUpdate((await this.call("update", { creds })).json);
  }

  async download(creds: Credentials, maxBytes: number): Promise<Buffer> {
    return (await this.call("download", { creds, raw: true, maxBytes, timeoutMs: 60_000 })).raw;
  }
}

function httpWords(status: number): string {
  if (status === 401) return "ZIGMon does not know this Stream Deck's key";
  if (status === 403) return "ZIGMon refused";
  if (status === 404) return "There is no deck API at that address - is ZIGMon 5.59 or newer?";
  if (status === 429) return "Too many requests - ZIGMon asks to slow down";
  if (status >= 500) return "ZIGMon had a problem (" + status + ")";
  return "ZIGMon answered " + status;
}
