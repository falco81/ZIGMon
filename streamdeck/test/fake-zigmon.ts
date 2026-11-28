/**
 * A small fake ZIGMon for the tests and the screenshots: the deck API of contract v1 on
 * Node's http/https, with its checks in the contract's order (enabled, token, install, deck
 * approved, allowed, hold, value). Tokens here are throwaway test values.
 */
import { createHash, randomBytes } from "node:crypto";
import * as http from "node:http";
import * as https from "node:https";
import type { AddressInfo } from "node:net";

export interface FakeItem {
  id: string;
  name: string;
  room: string | null;
  kind: string;
  icon: string;
  cap: string;
  actions: string[];
  attrs: Record<string, unknown>[];
  allowed: boolean;
  hold: boolean;
  state: Record<string, unknown>;
}

export interface Seen {
  do: string;
  method: string;
  headers: http.IncomingHttpHeaders;
  query: URLSearchParams;
  body: unknown;
}

const CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

export function sampleItems(): FakeItem[] {
  const st = (o: Record<string, unknown>) => ({ on: null, value: null, value_text: "", attrs: {}, online: true, battery: null, at: 1700000000, ...o });
  return [
    { id: "Lampa", name: "Lampa obývák", room: "Obývák", kind: "socket", icon: "plug", cap: "switch", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: false, state: st({ on: true, value_text: "42 W" }) },
    { id: "zb:0xa1:state_l1", name: "Kitchen light", room: "Kitchen", kind: "light", icon: "light", cap: "switch", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: false, state: st({ on: false }) },
    {
      id: "zb:0xb2:light", name: "Desk lamp", room: "Office", kind: "dimmer", icon: "light", cap: "dim", actions: ["toggle", "on", "off", "set"],
      attrs: [{ key: "brightness", label: "Brightness", type: "number", unit: "%", min: 0, max: 100, step: 1 }], allowed: true, hold: false,
      state: st({ on: true, attrs: { brightness: 70 } }),
    },
    {
      id: "zb:0xc3:trv", name: "Bedroom radiator", room: "Bedroom", kind: "thermostat", icon: "heat", cap: "climate", actions: ["set"],
      attrs: [
        { key: "current_heating_setpoint", label: "Setpoint", type: "number", unit: "°C", min: 5, max: 30, step: 0.5 },
        { key: "system_mode", label: "Mode", type: "enum", values: ["off", "heat", "auto"] },
        { key: "preset", label: "Preset", type: "enum", values: ["comfort", "eco", "boost"] },
      ],
      allowed: true, hold: false,
      state: st({ value: 20.4, value_text: "20.4 °C", attrs: { current_heating_setpoint: 21.5, system_mode: "heat", preset: "comfort", running_state: "heat" } }),
    },
    {
      id: "zb:0xd4:cover", name: "Living room blinds", room: "Obývák", kind: "cover", icon: "cover", cap: "cover", actions: ["open", "close", "stop", "set"],
      attrs: [{ key: "position", label: "Position", type: "number", unit: "%", min: 0, max: 100, step: 1 }], allowed: true, hold: false,
      state: st({ value: 60, attrs: { position: 60 } }),
    },
    { id: "scene:3", name: "Movie night", room: "Obývák", kind: "scene", icon: "scene", cap: "scenes", actions: ["run"], attrs: [], allowed: true, hold: false, state: st({}) },
    { id: "seq:1", name: "Good morning", room: null, kind: "sequence", icon: "seq", cap: "scenes", actions: ["run"], attrs: [], allowed: true, hold: false, state: st({}) },
    { id: "sys:reboot", name: "Restart ZIGMon", room: null, kind: "system", icon: "reboot", cap: "system", actions: ["run"], attrs: [], allowed: true, hold: true, state: st({}) },
    { id: "rule:7", name: "Night mode rule", room: null, kind: "rule", icon: "rule", cap: "automations", actions: ["toggle", "on", "off"], attrs: [], allowed: false, hold: false, state: st({ on: true }) },
    { id: "Garage", name: "Garage door relay", room: "Garage", kind: "switch", icon: "", cap: "switch", actions: ["toggle", "on", "off"], attrs: [], allowed: true, hold: true, state: st({ on: false }) },
    { id: "read:0xe5:temperature", name: "Outdoor temperature", room: "Garden", kind: "reading", icon: "thermo", cap: "view", actions: [], attrs: [{ key: "temperature", label: "Temperature", type: "number", unit: "°C" }], allowed: true, hold: false, state: st({ value: 7.3, value_text: "7.3 °C" }) },
    { id: "read:0xe5:humidity", name: "Outdoor humidity", room: "Garden", kind: "reading", icon: "drop", cap: "view", actions: [], attrs: [{ key: "humidity", label: "Humidity", type: "number", unit: "%" }], allowed: true, hold: false, state: st({ value: 81, value_text: "81 %" }) },
    { id: "read:0xf6:power", name: "Heat pump power", room: "Technical room", kind: "reading", icon: "bolt", cap: "view", actions: [], attrs: [{ key: "power", label: "Power", type: "number", unit: "W" }], allowed: true, hold: false, state: st({ value: 1840, value_text: "1840 W" }) },
    { id: "read:0xa7:co2", name: "Office CO₂", room: "Office", kind: "reading", icon: "", cap: "view", actions: [], attrs: [{ key: "co2", label: "CO2", type: "number", unit: "ppm" }], allowed: true, hold: false, state: st({ value: 1320, value_text: "1320 ppm" }) },
    { id: "status:alerts", name: "Alerts", room: null, kind: "status", icon: "bell", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ value: 2, value_text: "2 open alerts" }) },
    { id: "status:blocked", name: "Blocked addresses", room: null, kind: "status", icon: "wall", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ value: 0, value_text: "" }) },
    { id: "status:proxy", name: "Proxy", room: null, kind: "status", icon: "globe", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ on: true, value_text: "Running" }) },
    { id: "status:health", name: "Health", room: null, kind: "status", icon: "heart", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ on: true, value_text: "OK" }) },
    { id: "status:gateway", name: "Gateway", room: null, kind: "status", icon: "router", cap: "status", actions: [], attrs: [], allowed: true, hold: false, state: st({ on: false, online: true, value_text: "Not answering" }) },
  ];
}

export class FakeZigmon {
  enabled = true;
  items: FakeItem[] = sampleItems();
  boot = 1732700000;
  /** As a ZIGMon newer than 5.59.0, which sends a reading's recent values when asked (false: as 5.59.0). */
  withHistory = true;
  historyAsks: { ids: string[]; span: number; points: number }[] = [];
  seq = 100;
  changes: { seq: number; id: string }[] = [];
  /** sha256(token) -> install */
  tokens = new Map<string, { install: string; revoked: boolean; decks: Map<string, boolean> }>();
  pairs = new Map<string, { secret: string; code: string; install: string; expires: number; state: string; token?: string; decks: { id: string }[] }>();
  seen: Seen[] = [];
  commands: Record<string, unknown>[] = [];
  autoApprove = false;
  pairWaitMs = 300;
  waitMs = 400;
  plugin: { version: string } | null = null;
  update: Record<string, unknown> | null = null;
  download: Buffer | null = null;
  redirectEverything = false;
  private server: http.Server | https.Server | null = null;
  private waiters = new Set<() => void>();

  port = 0;

  constructor(private readonly tls?: { key: string; cert: string }) {}

  async start(port: number): Promise<void> {
    const handler = (req: http.IncomingMessage, res: http.ServerResponse) => void this.handle(req, res);
    this.server = this.tls ? https.createServer({ key: this.tls.key, cert: this.tls.cert }, handler) : http.createServer(handler);
    await new Promise<void>((resolve, reject) => {
      this.server!.once("error", reject);
      this.server!.listen(port, "127.0.0.1", () => resolve());
    });
    this.port = (this.server.address() as AddressInfo).port;
  }

  async stop(): Promise<void> {
    for (const w of this.waiters) w();
    if (!this.server) return;
    this.server.closeAllConnections?.();
    await new Promise<void>((r) => this.server!.close(() => r()));
  }

  /** Approve every pending request (as the administrator would, with all its decks). */
  approveAll(): void {
    for (const [id, p] of this.pairs) if (p.state === "pending") this.approve(id);
  }

  approve(pairId: string): string {
    const p = this.pairs.get(pairId)!;
    const token = "zsd_" + randomBytes(30).toString("base64url").slice(0, 40);
    p.state = "approved";
    p.token = token;
    this.tokens.set(sha(token), { install: p.install, revoked: false, decks: new Map(p.decks.map((d) => [d.id, true])) });
    this.wake();
    return token;
  }

  deny(pairId: string): void {
    this.pairs.get(pairId)!.state = "denied";
    this.wake();
  }

  revokeAll(): void {
    for (const t of this.tokens.values()) t.revoked = true;
    this.wake();
  }

  setState(id: string, patch: Record<string, unknown>): void {
    const it = this.items.find((i) => i.id === id)!;
    it.state = { ...it.state, ...patch, attrs: { ...(it.state.attrs as object), ...((patch.attrs as object) ?? {}) } };
    this.seq++;
    this.changes.push({ seq: this.seq, id });
    this.wake();
  }

  private wake(): void {
    for (const w of [...this.waiters]) w();
  }

  private hold(ms: number, until: () => boolean): Promise<void> {
    return new Promise((resolve) => {
      if (until()) return resolve();
      const done = () => {
        clearTimeout(t);
        this.waiters.delete(check);
        resolve();
      };
      const check = () => {
        if (until()) done();
      };
      const t = setTimeout(done, ms);
      this.waiters.add(check);
    });
  }

  private async handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    const u = new URL(req.url ?? "/", "http://x");
    const send = (status: number, body: unknown, headers: Record<string, string> = {}) => {
      const b = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
      res.writeHead(status, { "Content-Type": Buffer.isBuffer(body) ? "application/octet-stream" : "application/json", "Content-Length": String(b.length), ...headers });
      res.end(b);
    };
    const chunks: Buffer[] = [];
    for await (const c of req) chunks.push(c as Buffer);
    let body: unknown = null;
    if (chunks.length) try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { body = "bad"; }
    const what = u.searchParams.get("do") ?? "";
    this.seen.push({ do: what, method: req.method ?? "", headers: req.headers, query: u.searchParams, body });
    if (this.redirectEverything) return send(302, {}, { Location: "https://elsewhere.example/" });
    if (u.pathname !== "/index.php" || u.searchParams.get("api") !== "deck") return send(404, { ok: false, error: "not found" });
    if (!this.enabled) return send(403, { ok: false, error: "Stream Deck control is switched off in ZIGMon", off: true });

    if (what === "pair") {
      const b = body as Record<string, unknown>;
      const pair = randomBytes(12).toString("hex");
      const secret = "zsp_" + randomBytes(30).toString("base64url").slice(0, 40);
      let code = "";
      for (let i = 0; i < 6; i++) code += CODE_CHARS[randomBytes(1)[0]! % CODE_CHARS.length];
      const expires = Math.floor(Date.now() / 1000) + 900;
      this.pairs.set(pair, { secret, code, install: String(b.install), expires, state: "pending", decks: (b.decks as { id: string }[]) ?? [] });
      if (this.autoApprove) setTimeout(() => this.approve(pair), 150);
      return send(200, { ok: true, pair, secret, code: code.slice(0, 3) + "-" + code.slice(3), expires });
    }
    if (what === "pair_wait") {
      const secret = req.headers["x-zigmon-deck-pair"];
      const entry = [...this.pairs.entries()].find(([, p]) => p.secret === secret);
      if (!entry) return send(401, { ok: false, error: "unknown pairing request" });
      const [, p] = entry;
      await this.hold(this.pairWaitMs, () => p.state !== "pending");
      if (p.state === "approved" && p.token) {
        const token = p.token;
        p.state = "done";
        return send(200, { ok: true, state: "approved", token, install: { id: p.install, name: "OFFICE-PC", caps: {}, hint: token.slice(-2) } });
      }
      return send(200, { ok: true, state: p.state === "done" ? "expired" : p.state });
    }

    // everything else needs the key
    const tok = String(req.headers["x-zigmon-deck"] ?? "");
    const inst = String(req.headers["x-zigmon-deck-install"] ?? "");
    const t = this.tokens.get(sha(tok));
    if (!t) return send(401, { ok: false, error: "This Stream Deck is not known to ZIGMon" });
    if (t.revoked) return send(401, { ok: false, error: "This Stream Deck was disconnected in ZIGMon", revoked: true });
    if (t.install !== inst) return send(401, { ok: false, error: "This Stream Deck is not known to ZIGMon" });
    for (const id of (u.searchParams.get("decks") ?? "").split(",").filter(Boolean)) if (!t.decks.has(id)) t.decks.set(id, false);

    const item = (i: FakeItem) => ({ ...i });
    switch (what) {
      case "hello":
        return send(200, {
          ok: true, api: 1, server: "zigmon", version: "5.59.0", house: "Chalupa", boot: this.boot, seq: this.seq,
          install: { id: t.install, name: "OFFICE-PC", hint: "x9", caps: { view: { on: true, all: true, targets: [] }, switch: { on: true, all: false, targets: ["Lampa", "Garage"], hold: true }, dim: { on: true, all: true, targets: [], hold: false }, climate: { on: true, all: true, targets: [], hold: false }, status: { on: true } } },
          decks: [...t.decks.entries()].map(([id, approved]) => ({ id, type: 2, name: "Deck", approved })),
          plugin: this.plugin,
        });
      case "catalog":
        return send(200, { ok: true, boot: this.boot, seq: this.seq, rooms: [{ id: "1", name: "Obývák" }, { id: "2", name: "Kitchen" }], items: this.items.map(item) });
      case "state": {
        const b = (body && typeof body === "object" ? body : {}) as { ids?: string; history?: { span?: number; points?: number } };
        const ids = (u.searchParams.get("ids") ?? b.ids ?? "").split(",");
        const items: Record<string, unknown> = {};
        for (const i of this.items) if (ids.includes(i.id)) items[i.id] = i.state;
        if (!b.history || !this.withHistory) return send(200, { ok: true, boot: this.boot, seq: this.seq, items });
        // as a ZIGMon newer than 5.59.0: the readings' recent values, thinned
        this.historyAsks.push({ ids, span: Number(b.history.span), points: Number(b.history.points) });
        const history: Record<string, unknown> = {};
        const now = Math.floor(Date.now() / 1000);
        for (const i of this.items) {
          if (!ids.includes(i.id) || (i.kind !== "reading" && i.kind !== "thermostat")) continue;
          const v = Number((i.state as Record<string, unknown>).value ?? 20);
          const n = Math.min(48, Number(b.history.points) || 48), span = Number(b.history.span) || 86400;
          history[i.id] = { span, points: Array.from({ length: n }, (_, k) => [now - span + Math.round((k * span) / n), Math.round((v + Math.sin(k / 4) * 2) * 100) / 100]) };
        }
        return send(200, { ok: true, boot: this.boot, seq: this.seq, items, history });
      }
      case "wait": {
        const after = Number(u.searchParams.get("after"));
        const boot = u.searchParams.get("boot");
        if (String(this.boot) !== boot) return send(200, { ok: true, boot: this.boot, seq: this.seq, reset: true, changes: [] });
        const ids = u.searchParams.get("ids")?.split(",");
        const relevant = () => this.changes.filter((c) => c.seq > after && (!ids || ids.includes(c.id)));
        await this.hold(this.waitMs, () => relevant().length > 0 || t.revoked);
        if (t.revoked) return send(401, { ok: false, error: "revoked", revoked: true });
        const latest = new Map<string, number>();
        for (const c of relevant()) latest.set(c.id, c.seq);
        return send(200, {
          ok: true, boot: this.boot, seq: this.seq, reset: false,
          changes: [...latest.entries()].map(([id, seq]) => ({ seq, id, state: this.items.find((i) => i.id === id)!.state })),
        });
      }
      case "do": {
        const b = (body ?? {}) as Record<string, unknown>;
        this.commands.push(b);
        const deck = String(b.deck ?? "");
        if (!t.decks.get(deck)) {
          t.decks.set(deck, false);
          return send(403, { ok: false, error: "This Stream Deck is not approved in ZIGMon yet", deck_pending: true });
        }
        const it = this.items.find((i) => i.id === b.id);
        if (!it || !it.allowed) return send(403, { ok: false, error: "Not allowed for this Stream Deck" });
        if (it.hold && !(typeof b.held_ms === "number" && b.held_ms >= 1500)) return send(409, { ok: false, error: "Hold the key to confirm", hold: true });
        const a = String(b.action);
        if (!it.actions.includes(a)) return send(400, { ok: false, error: "That item cannot " + a });
        const s = it.state as Record<string, unknown>;
        if (a === "toggle") this.setState(it.id, { on: !s.on });
        else if (a === "on" || a === "off") this.setState(it.id, { on: a === "on" });
        else if (a === "set") {
          const attr = it.attrs.find((x) => x.key === b.attr);
          if (!attr) return send(400, { ok: false, error: "no such attribute" });
          if (attr.type === "number") {
            const cur = Number((s.attrs as Record<string, unknown>)[attr.key as string] ?? 0);
            let v = typeof b.delta === "number" ? cur + b.delta : Number(b.value);
            if (!Number.isFinite(v)) return send(400, { ok: false, error: "not a number" });
            const step = Number(attr.step ?? 1);
            v = Math.min(Number(attr.max ?? Infinity), Math.max(Number(attr.min ?? -Infinity), Math.round(v / step) * step));
            this.setState(it.id, { attrs: { [attr.key as string]: v } });
          } else if (attr.type === "enum") {
            if (!(attr.values as string[]).includes(String(b.value))) return send(400, { ok: false, error: "not one of its values" });
            this.setState(it.id, { attrs: { [attr.key as string]: b.value } });
          } else this.setState(it.id, { attrs: { [attr.key as string]: b.value } });
        } else this.setState(it.id, {});
        return send(200, { ok: true, said: a + " " + it.name, state: it.state });
      }
      case "update":
        return send(200, this.update ?? { ok: true, available: false });
      case "download":
        return this.download ? send(200, this.download, { "Content-Disposition": 'attachment; filename="ZIGMon.streamDeckPlugin"' }) : send(404, { ok: false, error: "none" });
      default:
        return send(400, { ok: false, error: "unknown do" });
    }
  }
}

function sha(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

/** A Store keeping the global settings in memory, as Stream Deck would. */
export class MemoryStore {
  saved: Record<string, unknown>[] = [];
  constructor(public value: Record<string, unknown> = {}) {}
  async load(): Promise<unknown> {
    return JSON.parse(JSON.stringify(this.value));
  }
  async save(g: Record<string, unknown>): Promise<void> {
    this.value = JSON.parse(JSON.stringify(g));
    this.saved.push(this.value);
  }
}

/** A mock Stream Deck key or dial: keeps what was drawn on it. */
export class MockSurface {
  images: string[] = [];
  feedbacks: Record<string, unknown>[] = [];
  alerts = 0;
  oks = 0;
  triggers: unknown[] = [];
  constructor(readonly controller: "Keypad" | "Encoder", readonly deckId: string) {}
  setImage(i: string): void {
    this.images.push(i);
  }
  setFeedback(f: Record<string, unknown>): void {
    this.feedbacks.push(f);
  }
  setTriggerDescription(d: unknown): void {
    this.triggers.push(d);
  }
  showAlert(): void {
    this.alerts++;
  }
  showOk(): void {
    this.oks++;
  }
  /** The last key image as SVG text. */
  get svg(): string {
    const last = this.images[this.images.length - 1] ?? "";
    const b64 = last.split(",")[1] ?? "";
    return Buffer.from(b64, "base64").toString("utf8");
  }
}

export async function until(cond: () => boolean, ms = 5000, what = "condition"): Promise<void> {
  const end = Date.now() + ms;
  while (!cond()) {
    if (Date.now() > end) throw new Error("timed out waiting for " + what);
    await new Promise((r) => setTimeout(r, 15));
  }
}
