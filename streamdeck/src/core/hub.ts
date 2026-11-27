import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { parseAddress, type ServerAddress } from "./address.js";
import { ZigmonClient, type Command, type Credentials, type DeckInfo } from "./client.js";
import { ApiError, CertError, NetError, type CertSeen, type Transport } from "./http.js";
import { IDLE, pairStep, pairView, type PairEvent, type PairState } from "./pairing.js";
import { cleanText, ProtocolError, type Caps, type Hello, type Item, type ItemState, type Room } from "./protocol.js";
import type { Protector } from "./secrets.js";
import { newInstallId, normalizeGlobal, type GlobalSettings } from "./settings.js";
import { pinFor, withPin } from "./tls.js";
import { checkPackage, embeddedKeys, packageFileName, UpdateError, verifyOffer, type ReleaseKey } from "./update.js";
import { isNewer, PLUGIN_VERSION } from "./version.js";

export type Phase =
  | "setup" // no address yet
  | "unpaired" // an address, no key
  | "pairing" // a code is shown, waiting for ZIGMon's administrator
  | "connecting"
  | "online"
  | "offline" // trying again (message says why)
  | "cert" // the certificate needs the user's decision
  | "off" // Stream Deck control is switched off in ZIGMon
  | "revoked" // the key was revoked (or is unknown): pair again
  | "denied"; // the pairing request was denied

export interface HubView {
  /** The items this key/dial shows. */
  ids(): string[];
  /** Redraw: state, phase or catalog changed. */
  refresh(): void;
}

export interface Store {
  load(): Promise<unknown>;
  save(g: GlobalSettings): Promise<void>;
}

export interface HubDeps {
  store: Store;
  protector: Protector;
  transport: (a: ServerAddress) => Transport & { lastCert?: CertSeen | null };
  decks: () => DeckInfo[];
  computer: () => string;
  log?: (msg: string) => void;
  /** Opens a downloaded .streamDeckPlugin (Stream Deck installs it). */
  open?: (path: string) => Promise<void>;
  tempDir?: () => string;
  keys?: ReleaseKey[];
  now?: () => number;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  /** Backoff bounds (tests shorten them). */
  minBackoffMs?: number;
  maxBackoffMs?: number;
}

export type CommandResult =
  | { ok: true; said: string; state: ItemState | null }
  | { ok: false; why: "hold" | "deck" | "denied" | "off" | "revoked" | "invalid" | "rate" | "net" | "offline"; message: string };

export interface Status {
  phase: Phase;
  message: string;
  plugin: string;
  address: string;
  house: string;
  zigmon: string;
  install: { name: string; hint: string; caps: Caps } | null;
  decks: { id: string; name: string; type: number; cols: number; rows: number; approved: boolean | null }[];
  pair: { code: string; expires: number } | null;
  cert: (CertSeen & { pinned: boolean }) | null;
  pinned: string | null;
  update: { version: string } | null;
  updating: { state: "idle" | "working" | "done" | "failed"; message: string };
  retryInMs: number | null;
  items: number;
}

const realSleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(done, ms);
    function done() {
      clearTimeout(t);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });

/**
 * The one shared connection of the plugin to ZIGMon: pairing, then hello -> catalog -> long-poll
 * wait, with a 1 s -> 60 s backoff; it keeps the items and their states and tells the views
 * when to redraw. Every key and dial talks to ZIGMon only through it.
 */
export class Hub {
  private g: GlobalSettings = { pins: {} };
  private address: ServerAddress | null = null;
  private transport: (Transport & { lastCert?: CertSeen | null }) | null = null;
  private client: ZigmonClient | null = null;
  private token: string | null = null;
  private phase: Phase = "setup";
  private message = "";
  private helloInfo: Hello | null = null;
  private items = new Map<string, Item>();
  private states = new Map<string, ItemState>();
  private rooms: Room[] = [];
  private boot = "";
  private seq = 0;
  private catalogAt = 0;
  private deckApproved = new Map<string, boolean>();
  private views = new Set<HubView>();
  private statusListeners = new Set<() => void>();
  private pair: PairState = IDLE;
  private gen = 0;
  private loopAbort: AbortController | null = null;
  private waitAbort: AbortController | null = null;
  private watchedKey = "";
  private resubTimer: ReturnType<typeof setTimeout> | null = null;
  private retryAt: number | null = null;
  private updating: Status["updating"] = { state: "idle", message: "" };
  private certSeen: CertSeen | null = null;
  private readonly now: () => number;
  private readonly sleep: (ms: number, signal: AbortSignal) => Promise<void>;
  private readonly minBackoff: number;
  private readonly maxBackoff: number;
  private loaded = false;

  constructor(private readonly d: HubDeps) {
    this.now = d.now ?? Date.now;
    this.sleep = d.sleep ?? realSleep;
    this.minBackoff = d.minBackoffMs ?? 1000;
    this.maxBackoff = d.maxBackoffMs ?? 60_000;
  }

  // ------------------------------------------------------------------ lifecycle

  async start(): Promise<void> {
    this.g = normalizeGlobal(await this.d.store.load());
    this.loaded = true;
    if (!this.g.install) {
      this.g.install = newInstallId();
      await this.persist();
    }
    if (!this.g.address) return this.setPhase("setup", "");
    const pa = parseAddress(this.g.address);
    if (!pa.ok) return this.setPhase("setup", pa.error);
    this.useAddress(pa.address);
    if (!this.g.tokenBlob) return this.setPhase("unpaired", "");
    try {
      this.token = await this.d.protector.unprotect(this.g.tokenBlob);
    } catch {
      this.token = null;
      return this.setPhase("unpaired", "The saved key could not be read on this Windows account - pair again.");
    }
    this.runLoop();
  }

  stop(): void {
    this.gen++;
    this.loopAbort?.abort();
    this.waitAbort?.abort();
    this.loopAbort = null;
    if (this.resubTimer) clearTimeout(this.resubTimer);
  }

  private useAddress(a: ServerAddress): void {
    this.address = a;
    this.transport = this.d.transport(a);
    this.client = new ZigmonClient(a, this.transport, () => pinFor(this.g.pins, a.pinScope));
  }

  private creds(): Credentials | null {
    return this.token && this.g.install ? { token: this.token, install: this.g.install } : null;
  }

  private async persist(): Promise<void> {
    await this.d.store.save({ ...this.g });
  }

  private log(msg: string): void {
    this.d.log?.(msg);
  }

  // ------------------------------------------------------------------ views

  watch(v: HubView): void {
    this.views.add(v);
    this.resubscribe();
  }

  unwatch(v: HubView): void {
    this.views.delete(v);
    this.resubscribe();
  }

  onStatus(fn: () => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  /** Watched ids changed: restart the long poll with the new list (debounced). */
  resubscribe(): void {
    if (this.resubTimer) clearTimeout(this.resubTimer);
    this.resubTimer = setTimeout(() => {
      this.resubTimer = null;
      const key = this.watchedIds().join(",");
      if (key === this.watchedKey) return;
      this.watchedKey = key;
      this.waitAbort?.abort(new Error("resubscribe"));
    }, 150);
  }

  watchedIds(): string[] {
    const s = new Set<string>();
    for (const v of this.views) for (const id of v.ids()) if (id) s.add(id);
    return [...s].sort();
  }

  private redrawAll(): void {
    for (const v of this.views) v.refresh();
    for (const f of this.statusListeners) f();
  }

  private redrawIds(ids: Set<string>): void {
    for (const v of this.views) if (v.ids().some((i) => ids.has(i))) v.refresh();
  }

  private setPhase(p: Phase, message: string): void {
    const changed = p !== this.phase || message !== this.message;
    this.phase = p;
    this.message = message;
    if (changed) this.redrawAll();
  }

  // ------------------------------------------------------------------ reading

  get currentPhase(): Phase {
    return this.phase;
  }

  get currentMessage(): string {
    return this.message;
  }

  /** The last values of an item (for sparklines and trends), oldest first. */
  history(id: string | undefined): number[] {
    return id ? this.hist.get(id) ?? [] : [];
  }

  private hist = new Map<string, number[]>();
  private lastAt = new Map<string, string>();

  private record(id: string, st: ItemState): void {
    if (st.value === null) return;
    const mark = String(st.at ?? "") + "|" + st.value;
    if (this.lastAt.get(id) === mark) return;
    this.lastAt.set(id, mark);
    const h = this.hist.get(id) ?? [];
    h.push(st.value);
    if (h.length > 60) h.splice(0, h.length - 60);
    this.hist.set(id, h);
  }

  private setState(id: string, st: ItemState): void {
    this.states.set(id, st);
    this.record(id, st);
  }

  item(id: string | undefined): Item | undefined {
    return id ? this.items.get(id) : undefined;
  }

  state(id: string | undefined): ItemState | undefined {
    return id ? this.states.get(id) ?? this.items.get(id)?.state : undefined;
  }

  allItems(): Item[] {
    return [...this.items.values()];
  }

  allRooms(): Room[] {
    return this.rooms;
  }

  get pairCode(): string | null {
    return this.pair.phase === "waiting" ? this.pair.code : null;
  }

  /** null = not known yet (no hello), true/false as ZIGMon says. */
  deckIsApproved(deckId: string): boolean | null {
    return this.deckApproved.has(deckId) ? this.deckApproved.get(deckId)! : null;
  }

  status(): Status {
    const a = this.address;
    const pin = a ? pinFor(this.g.pins, a.pinScope) : null;
    const pv = pairView(this.pair);
    return {
      phase: this.phase,
      message: this.message,
      plugin: PLUGIN_VERSION,
      address: a?.base ?? this.g.address ?? "",
      house: this.helloInfo?.house ?? "",
      zigmon: this.helloInfo?.version ?? "",
      install: this.helloInfo ? { name: this.helloInfo.install.name, hint: this.helloInfo.install.hint, caps: this.helloInfo.install.caps } : null,
      decks: this.d.decks().map((x) => ({ id: x.id, name: x.name, type: x.type, cols: x.cols, rows: x.rows, approved: this.deckIsApproved(x.id) })),
      pair: pv.code ? { code: pv.code, expires: pv.expires! } : null,
      cert: this.certSeen ? { ...this.certSeen, pinned: false } : null,
      pinned: pin ? pin.match(/../g)!.join(":") : null,
      update: this.helloInfo?.plugin && isNewer(this.helloInfo.plugin.version) ? { version: this.helloInfo.plugin.version } : null,
      updating: this.updating,
      retryInMs: this.retryAt ? Math.max(0, this.retryAt - this.now()) : null,
      items: this.items.size,
    };
  }

  // ------------------------------------------------------------------ the loop

  private runLoop(): void {
    this.stop();
    const my = ++this.gen;
    const abort = new AbortController();
    this.loopAbort = abort;
    void this.loop(my, abort.signal);
  }

  private alive(my: number): boolean {
    return my === this.gen;
  }

  private async loop(my: number, signal: AbortSignal): Promise<void> {
    let backoff = this.minBackoff;
    this.helloInfo = null;
    this.setPhase("connecting", "");
    while (this.alive(my) && !signal.aborted) {
      const creds = this.creds();
      if (!creds || !this.client) return;
      try {
        if (!this.helloInfo || this.now() - this.catalogAt > 10 * 60_000) await this.refreshAll(creds);
        if (!this.alive(my)) return;
        this.retryAt = null;
        this.certSeen = null;
        this.setPhase("online", "");
        backoff = this.minBackoff;
        const wa = new AbortController();
        this.waitAbort = wa;
        const ids = this.watchedIds();
        this.watchedKey = ids.join(",");
        let answer;
        try {
          answer = await this.client.wait(creds, this.seq, this.boot, ids, this.d.decks(), AbortSignal.any([wa.signal, signal]));
        } catch (e) {
          if (wa.signal.aborted && !signal.aborted) {
            // the watched list changed: fetch the new ones' states, then wait again at once
            await this.fetchStates(creds, ids);
            continue;
          }
          throw e;
        } finally {
          this.waitAbort = null;
        }
        if (!this.alive(my)) return;
        if (answer.reset || answer.boot !== this.boot) {
          this.helloInfo = null; // ZIGMon restarted or we fell behind: start over
          continue;
        }
        const changed = new Set<string>();
        for (const c of answer.changes) {
          this.setState(c.id, c.state);
          changed.add(c.id);
        }
        this.seq = answer.seq;
        if (changed.size) this.redrawIds(changed);
      } catch (e) {
        if (!this.alive(my) || signal.aborted) return;
        const wait = this.onLoopError(e, backoff);
        if (wait === null) return; // stopped for good (revoked, ...)
        this.retryAt = this.now() + wait;
        for (const f of this.statusListeners) f();
        await this.sleep(wait, signal);
        backoff = Math.min(this.maxBackoff, Math.max(this.minBackoff, backoff * 2));
      }
    }
  }

  private async refreshAll(creds: Credentials): Promise<void> {
    const client = this.client!;
    const decks = this.d.decks();
    const h = await client.hello(creds, decks);
    this.helloInfo = h;
    this.deckApproved = new Map(h.decks.map((x) => [x.id, x.approved]));
    const c = await client.catalog(creds, decks);
    this.items = new Map(c.items.map((i) => [i.id, i]));
    this.states = new Map();
    for (const i of c.items) this.setState(i.id, i.state);
    this.rooms = c.rooms;
    this.boot = c.boot;
    this.seq = c.seq;
    this.catalogAt = this.now();
    this.log("connected: " + this.items.size + " items");
    this.redrawAll();
  }

  private async fetchStates(creds: Credentials, ids: string[]): Promise<void> {
    if (!this.client || ids.length === 0) return;
    try {
      const s = await this.client.state(creds, ids);
      const changed = new Set<string>();
      for (const [id, st] of s.items) {
        this.setState(id, st);
        changed.add(id);
      }
      if (changed.size) this.redrawIds(changed);
    } catch {
      /* the next wait will tell */
    }
  }

  /** @returns how long to wait before the next try, or null to stop trying */
  private onLoopError(e: unknown, backoff: number): number | null {
    if (e instanceof CertError) {
      this.certSeen = this.transport?.lastCert ?? null;
      this.setPhase("cert", e.message);
      return 60_000;
    }
    if (e instanceof ApiError) {
      if (e.status === 401) {
        void this.forgetToken();
        this.setPhase("revoked", e.body.revoked === true ? "This Stream Deck was disconnected in ZIGMon." : "ZIGMon does not know this Stream Deck's key any more.");
        return null;
      }
      if (e.status === 403 && e.body.off === true) {
        this.setPhase("off", "Stream Deck control is switched off in ZIGMon (Settings → Stream Deck).");
        return 60_000;
      }
      if (e.status === 429) {
        this.setPhase("offline", e.message);
        return Math.max(backoff, 10_000);
      }
      this.setPhase("offline", e.message);
      return backoff;
    }
    const msg = e instanceof NetError || e instanceof ProtocolError ? e.message : "the connection failed";
    this.log("connection: " + msg);
    this.setPhase("offline", cleanText(msg, 160));
    return backoff;
  }

  private async forgetToken(): Promise<void> {
    this.token = null;
    delete this.g.tokenBlob;
    this.helloInfo = null;
    this.items.clear();
    this.states.clear();
    await this.persist();
  }

  // ------------------------------------------------------------------ what the property inspector asks

  /** Connect to an address: keep it, then start pairing (or reconnect when a key is kept for it). */
  async connect(addressText: string): Promise<{ ok: boolean; error?: string }> {
    if (!this.loaded) await this.start();
    const pa = parseAddress(addressText);
    if (!pa.ok) return { ok: false, error: pa.error };
    const same = this.address?.base === pa.address.base;
    this.stop();
    if (!same) {
      // a key belongs to the server it came from
      this.token = null;
      delete this.g.tokenBlob;
    }
    this.g.address = pa.address.base;
    this.useAddress(pa.address);
    this.certSeen = null;
    await this.persist();
    if (this.token) {
      this.runLoop();
      return { ok: true };
    }
    void this.startPairing();
    return { ok: true };
  }

  private pairStepTo(e: PairEvent): void {
    this.pair = pairStep(this.pair, e);
    this.redrawAll();
  }

  async startPairing(): Promise<void> {
    if (!this.client || !this.g.install) return;
    this.stop();
    const my = ++this.gen;
    const abort = new AbortController();
    this.loopAbort = abort;
    this.pairStepTo({ type: "start" });
    this.setPhase("pairing", "Asking ZIGMon…");
    try {
      const a = await this.client.pair(this.g.install, this.d.computer(), this.d.decks());
      if (!this.alive(my)) return;
      this.pairStepTo({ type: "started", answer: a });
      this.setPhase("pairing", "");
    } catch (e) {
      if (!this.alive(my)) return;
      return this.pairFailed(e);
    }
    let backoff = this.minBackoff;
    while (this.alive(my) && this.pair.phase === "waiting") {
      this.pairStepTo({ type: "tick", now: this.now() });
      if (this.pair.phase !== "waiting") break;
      try {
        const w = await this.client.pairWait(this.pair.secret, abort.signal);
        if (!this.alive(my)) return;
        this.pairStepTo({ type: "wait", answer: w });
        backoff = this.minBackoff;
      } catch (e) {
        if (!this.alive(my)) return;
        const fatal = e instanceof CertError || (e instanceof ApiError && (e.status === 403 || e.status === 404 || e.status === 401));
        this.pairStepTo({ type: "fail", error: errorWords(e), fatal });
        if (fatal) return this.pairFailed(e);
        await this.sleep(backoff, abort.signal);
        backoff = Math.min(this.maxBackoff, backoff * 2);
      }
    }
    if (!this.alive(my)) return;
    const p = this.pair;
    if (p.phase === "approved") {
      this.token = p.token;
      this.g.tokenBlob = await this.d.protector.protect(p.token);
      await this.persist();
      this.pair = IDLE;
      this.log("paired");
      this.runLoop();
    } else if (p.phase === "denied") {
      this.pair = IDLE;
      this.setPhase("denied", "ZIGMon's administrator denied this request.");
    } else if (p.phase === "expired") {
      this.pair = IDLE;
      this.setPhase("unpaired", "The code ran out before it was approved - connect again for a new one.");
    }
  }

  private pairFailed(e: unknown): void {
    this.pair = IDLE;
    if (e instanceof CertError) {
      this.certSeen = this.transport?.lastCert ?? null;
      this.setPhase("cert", e.message);
      return;
    }
    if (e instanceof ApiError && e.status === 403 && e.body.off === true) {
      this.setPhase("off", "Stream Deck control is switched off in ZIGMon - switch it on under Settings → Stream Deck, then connect again.");
      return;
    }
    this.setPhase("unpaired", errorWords(e));
  }

  cancelPairing(): void {
    this.stop();
    this.pair = IDLE;
    this.setPhase(this.address ? "unpaired" : "setup", "");
  }

  /** The user trusts the certificate they were shown: pin it for this host:port and try again. */
  async pinCertificate(fingerprint: string): Promise<{ ok: boolean; error?: string }> {
    if (!this.address) return { ok: false, error: "no address" };
    const seen = this.certSeen;
    if (!seen || seen.fingerprint !== fingerprint || seen.scope !== this.address.pinScope) {
      return { ok: false, error: "That is not the certificate the server showed - connect again." };
    }
    this.g.pins = withPin(this.g.pins, this.address.pinScope, fingerprint);
    this.certSeen = null;
    await this.persist();
    if (this.token) this.runLoop();
    else void this.startPairing();
    return { ok: true };
  }

  async unpin(): Promise<void> {
    if (!this.address) return;
    this.g.pins = withPin(this.g.pins, this.address.pinScope, null);
    await this.persist();
    if (this.token) this.runLoop();
    else this.redrawAll();
  }

  /** Forget the key (ZIGMon still lists the installation until it is revoked there). */
  async disconnect(): Promise<void> {
    this.stop();
    this.pair = IDLE;
    await this.forgetToken();
    this.deckApproved.clear();
    this.setPhase(this.address ? "unpaired" : "setup", "");
  }

  retryNow(): void {
    if (this.token) this.runLoop();
    else if (this.address) void this.startPairing();
  }

  // ------------------------------------------------------------------ commands

  async command(cmd: Command): Promise<CommandResult> {
    const creds = this.creds();
    if (!creds || !this.client) return { ok: false, why: "offline", message: "Not connected to ZIGMon" };
    try {
      const r = await this.client.do(creds, cmd);
      if (r.state) {
        this.setState(cmd.id, r.state);
        this.redrawIds(new Set([cmd.id]));
      }
      if (cmd.deck && this.deckApproved.get(cmd.deck) === false) {
        this.deckApproved.set(cmd.deck, true);
        this.redrawAll();
      }
      return { ok: true, said: r.said, state: r.state };
    } catch (e) {
      if (e instanceof ApiError) {
        const b = e.body;
        if (e.status === 409 && b.hold === true) {
          const it = this.items.get(cmd.id);
          if (it && !it.hold) {
            it.hold = true;
            this.redrawIds(new Set([cmd.id]));
          }
          return { ok: false, why: "hold", message: "Hold the key to confirm" };
        }
        if (e.status === 403 && b.deck_pending === true) {
          this.deckApproved.set(cmd.deck, false);
          this.redrawAll();
          return { ok: false, why: "deck", message: e.message };
        }
        if (e.status === 403 && b.off === true) {
          this.setPhase("off", "Stream Deck control is switched off in ZIGMon (Settings → Stream Deck).");
          return { ok: false, why: "off", message: e.message };
        }
        if (e.status === 403) {
          const it = this.items.get(cmd.id);
          if (it && it.allowed) {
            it.allowed = false;
            this.redrawIds(new Set([cmd.id]));
          }
          return { ok: false, why: "denied", message: e.message };
        }
        if (e.status === 401) {
          void this.forgetToken();
          this.stop();
          this.setPhase("revoked", b.revoked === true ? "This Stream Deck was disconnected in ZIGMon." : "ZIGMon does not know this Stream Deck's key any more.");
          return { ok: false, why: "revoked", message: e.message };
        }
        if (e.status === 429) return { ok: false, why: "rate", message: e.message };
        if (e.status === 400 || e.status === 422 || e.status === 409) return { ok: false, why: "invalid", message: e.message };
      }
      return { ok: false, why: "net", message: errorWords(e) };
    }
  }

  // ------------------------------------------------------------------ updates

  async installUpdate(): Promise<void> {
    const creds = this.creds();
    if (!creds || !this.client) return;
    const set = (state: Status["updating"]["state"], message: string) => {
      this.updating = { state, message };
      for (const f of this.statusListeners) f();
    };
    set("working", "Checking the signature…");
    try {
      const offer = await this.client.update(creds);
      const v = verifyOffer(offer, this.d.keys ?? embeddedKeys());
      set("working", "Downloading " + v.manifest.version + "…");
      const bytes = await this.client.download(creds, v.manifest.size);
      checkPackage(bytes, v);
      const dir = (this.d.tempDir ?? (() => process.env.TEMP || process.env.TMP || "."))();
      const path = join(dir, packageFileName(v.manifest.version));
      await writeFile(path, bytes);
      this.log("update " + v.manifest.version + " verified (" + v.keyName + "), opening it");
      if (this.d.open) await this.d.open(path);
      set("done", "Stream Deck is installing " + v.manifest.version + " - confirm it there.");
    } catch (e) {
      set("failed", e instanceof UpdateError ? "Not installed: " + e.message : "Not installed: " + errorWords(e));
    }
  }
}

export function errorWords(e: unknown): string {
  if (e instanceof ApiError || e instanceof NetError || e instanceof CertError || e instanceof ProtocolError || e instanceof UpdateError) {
    return cleanText(e.message, 200);
  }
  return "something went wrong";
}
