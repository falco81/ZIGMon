/**
 * End to end, without the Stream Deck app: the plugin's hub and views against a fake ZIGMon
 * (Node http/https implementing the deck API), with mock keys and dials capturing what is drawn.
 * Ports 20320-20329 only.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash, generateKeyPairSync, sign, X509Certificate } from "node:crypto";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, describe, it } from "node:test";
import { parseAddress } from "../src/core/address.js";
import { CertError, NetError, NodeTransport } from "../src/core/http.js";
import { Hub, type HubDeps } from "../src/core/hub.js";
import { FakeProtector } from "../src/core/secrets.js";
import { normalizePin } from "../src/core/tls.js";
import { rawKey } from "../src/core/update.js";
import { PLUGIN_VERSION } from "../src/core/version.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { FakeZigmon, MemoryStore, MockSurface, until } from "./fake-zigmon.js";

const DECKS = [
  { id: "XL-1", type: 2, name: "Office XL", cols: 8, rows: 4 },
  { id: "PLUS-1", type: 7, name: "Stream Deck +", cols: 4, rows: 2 },
];

const cleanups: (() => unknown)[] = [];
after(async () => {
  for (const c of cleanups.reverse()) await c();
});

function newHub(store: MemoryStore, logs: string[], extra: Partial<HubDeps> = {}): Hub {
  const hub = new Hub({
    store, protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => DECKS, computer: () => "OFFICE-PC",
    log: (m) => logs.push(m), minBackoffMs: 50, maxBackoffMs: 200, ...extra,
  });
  cleanups.push(() => hub.stop());
  return hub;
}

function view(hub: Hub, kind: ActionKind, settings: Record<string, unknown>, ctl: "Keypad" | "Encoder" = "Keypad", deck = "XL-1") {
  const s = new MockSurface(ctl, deck);
  const v = new ActionView(kind, hub, s, settings);
  hub.watch(v);
  v.draw(true);
  cleanups.push(() => v.dispose());
  return { v, s };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("end to end against a fake ZIGMon", () => {
  it("pairs, shows, switches, holds, turns, updates and is revoked", async () => {
    const fake = new FakeZigmon();
    await fake.start(20320);
    cleanups.push(() => fake.stop());
    const store = new MemoryStore();
    const logs: string[] = [];
    // a throwaway release key for the update
    const { publicKey, privateKey } = generateKeyPairSync("ed25519");
    const raw = publicKey.export({ format: "der", type: "spki" }).subarray(12).toString("hex");
    const tmp = mkdtempSync(join(tmpdir(), "zigmon-deck-"));
    const opened: string[] = [];
    const hub = newHub(store, logs, { keys: [{ name: "test", key: rawKey(raw) }], tempDir: () => tmp, open: async (p) => { opened.push(p); } });
    await hub.start();
    assert.match(String(store.value.install), /^[0-9a-f]{32}$/);

    const lamp = view(hub, "control", { item: "Lampa" });
    assert.match(lamp.s.svg, /Connect/);

    // ---- pairing: the code on every key, then the administrator approves
    await hub.connect("http://localhost:" + fake.port);
    await until(() => hub.pairCode !== null, 3000, "a pairing code");
    const code = hub.pairCode!;
    await until(() => lamp.s.svg.includes(code.slice(0, 3)), 2000, "the code on the key");
    const pairReq = fake.seen.find((s) => s.do === "pair")!;
    const body = pairReq.body as Record<string, unknown>;
    assert.equal(body.install, store.value.install);
    assert.equal(body.computer, "OFFICE-PC");
    assert.equal(body.plugin, PLUGIN_VERSION);
    assert.deepEqual(body.decks, [{ id: "XL-1", type: 2, name: "Office XL", cols: 8, rows: 4 }, { id: "PLUS-1", type: 7, name: "Stream Deck +", cols: 4, rows: 2 }]);
    assert.equal(hub.status().phase, "pairing");
    assert.equal(JSON.stringify(hub.status()).includes("zsp_"), false, "the pairing secret is never shown");
    fake.approveAll();
    await until(() => hub.currentPhase === "online", 5000, "online");
    await until(() => lamp.s.svg.includes("Lampa"), 2000, "the lamp drawn");
    assert.match(String(store.value.tokenBlob), /^fake:/, "the key is kept only encrypted");
    assert.equal(JSON.stringify(store.saved).includes("zsd_"), false, "the plain key is never stored");

    const hello = fake.seen.find((s) => s.do === "hello")!;
    assert.match(String(hello.headers["x-zigmon-deck"]), /^zsd_/);
    assert.equal(hello.headers["x-zigmon-deck-install"], store.value.install);
    assert.match(String(hello.headers["x-zigmon-client"]), new RegExp("^ZIGMon-StreamDeck/" + PLUGIN_VERSION.replace(/\./g, "\\.") + "$"));
    assert.equal(hello.query.get("decks"), "XL-1,PLUS-1");
    assert.ok(hello.query.get("deck_info"));
    for (const s of fake.seen) assert.ok(!s.query.toString().includes("zsd_"), "the key is never in a URL");

    // ---- a press switches; the long poll redraws
    lamp.v.keyDown();
    lamp.v.keyUp();
    await until(() => fake.commands.length === 1, 2000, "the toggle");
    assert.deepEqual(fake.commands[0], { deck: "XL-1", id: "Lampa", action: "toggle" });
    await until(() => /Off/.test(lamp.s.svg), 2000, "Off drawn");
    fake.setState("Lampa", { on: true, value_text: "61 W" });
    await until(() => lamp.s.svg.includes("61 W"), 3000, "the live change drawn");

    // ---- hold to confirm: a quick press does nothing, a long one sends held_ms
    const garage = view(hub, "control", { item: "Garage" });
    garage.v.keyDown();
    await sleep(100);
    garage.v.keyUp();
    await sleep(100);
    assert.equal(fake.commands.length, 1, "no command for a short press");
    assert.match(garage.s.svg, /Hold to confirm/);
    garage.v.keyDown();
    await until(() => /Keep holding/.test(garage.s.svg), 1000, "the ring");
    await until(() => fake.commands.length === 2, 3000, "the held command");
    garage.v.keyUp();
    assert.equal(fake.commands[1]!.action, "toggle");
    assert.ok(Number(fake.commands[1]!.held_ms) >= 1500);

    // ZIGMon starts asking for a hold the plugin did not know of: 409, then the key knows
    fake.items.find((i) => i.id === "Lampa")!.hold = true;
    lamp.v.keyDown();
    lamp.v.keyUp();
    await until(() => hub.item("Lampa")!.hold === true, 2000, "hold learnt from the 409");
    fake.items.find((i) => i.id === "Lampa")!.hold = false;

    // ---- not allowed: nothing is sent
    const rule = view(hub, "control", { item: "rule:7" });
    const before = fake.commands.length;
    rule.v.keyDown();
    rule.v.keyUp();
    await sleep(50);
    assert.equal(fake.commands.length, before);
    assert.match(rule.s.svg, /Not allowed/);

    // ---- a dial: six clicks of 5 % become one delta, clamped by ZIGMon at 100
    const dim = view(hub, "dimmer", { item: "zb:0xb2:light" }, "Encoder", "PLUS-1");
    await until(() => hub.deckIsApproved("PLUS-1") === true, 3000, "the + known as approved");
    dim.v.rotate(3);
    dim.v.rotate(3);
    const shown = dim.s.feedbacks.at(-1)! as Record<string, { value?: string }>;
    assert.equal(shown.value!.value, "100%", "the new value is shown at once");
    await until(() => fake.commands.some((c) => c.attr === "brightness"), 2000, "the delta");
    const turn = fake.commands.filter((c) => c.attr === "brightness");
    assert.equal(turn.length, 1);
    assert.deepEqual(turn[0], { deck: "PLUS-1", id: "zb:0xb2:light", action: "set", attr: "brightness", delta: 30 });
    assert.equal((fake.items.find((i) => i.id === "zb:0xb2:light")!.state.attrs as Record<string, number>).brightness, 100);
    assert.equal(dim.s.triggers.length > 0, true);

    // a thermostat dial: half degrees
    const trv = view(hub, "thermostat", { item: "zb:0xc3:trv" }, "Encoder", "PLUS-1");
    trv.v.rotate(-2);
    await until(() => fake.commands.some((c) => c.attr === "current_heating_setpoint"), 2000, "the setpoint");
    assert.equal(fake.commands.find((c) => c.attr === "current_heating_setpoint")!.delta, -1);
    trv.v.dialDown();
    trv.v.dialUp();
    await until(() => fake.commands.some((c) => c.attr === "system_mode"), 2000, "next mode");
    assert.equal(fake.commands.find((c) => c.attr === "system_mode")!.value, "auto");

    // ---- a deck ZIGMon has not approved yet
    const stranger = view(hub, "control", { item: "zb:0xa1:state_l1" }, "Keypad", "NEW-9");
    stranger.v.keyDown();
    stranger.v.keyUp();
    await until(() => hub.deckIsApproved("NEW-9") === false, 2000, "deck pending");
    await until(() => /Approve deck/.test(stranger.s.svg), 2000, "drawn as waiting");
    assert.match(lamp.s.svg, /Lampa/, "other decks carry on");

    // ---- an update: signed manifest, sha256, saved and opened
    const pkg = Buffer.concat([Buffer.from([0x50, 0x4b, 0x03, 0x04]), Buffer.alloc(500, 7)]);
    const sha = createHash("sha256").update(pkg).digest("hex");
    const manifest = Buffer.from(JSON.stringify({ product: "ZIGMon for Stream Deck", file: "com.zigmon.streamdeck.streamDeckPlugin", version: "1.3.0", size: pkg.length, sha256: sha, requires: "Stream Deck 7.1, Windows 10/11" }) + "\n");
    fake.plugin = { version: "1.3.0" };
    fake.update = { ok: true, available: true, version: "1.3.0", size: pkg.length, sha256: sha, manifest: manifest.toString("base64"), sig: sign(null, manifest, privateKey).toString("base64") };
    fake.download = pkg;
    hub.retryNow();
    hub.stop();
    (hub as unknown as { runLoop(): void }).runLoop();
    await until(() => hub.status().update?.version === "1.3.0", 4000, "the update offered");
    await hub.installUpdate();
    assert.equal(hub.status().updating.state, "done", hub.status().updating.message);
    assert.deepEqual(opened, [join(tmp, "ZIGMon-1.3.0.streamDeckPlugin")]);
    assert.deepEqual(readFileSync(opened[0]!), pkg);
    // tampered download: refused, nothing opened
    fake.download = Buffer.concat([pkg.subarray(0, -1), Buffer.from([8])]);
    await hub.installUpdate();
    assert.equal(hub.status().updating.state, "failed");
    assert.match(hub.status().updating.message, /checksum/);
    assert.equal(opened.length, 1);

    // ---- revoked in ZIGMon: the key is forgotten, every key says so
    fake.revokeAll();
    await until(() => hub.currentPhase === "revoked", 5000, "revoked");
    await until(() => /Disconnected/.test(lamp.s.svg), 2000, "drawn as disconnected");
    assert.equal(store.value.tokenBlob, undefined);

    // ---- secrets never in the logs or the status
    const tokens = [...fake.tokens.keys()];
    assert.ok(tokens.length > 0);
    for (const l of logs) assert.ok(!/zsd_|zsp_/.test(l), "log line holds a secret: " + l);
    assert.ok(!/zsd_|zsp_/.test(JSON.stringify(hub.status())));
  });

  it("switched off in ZIGMon, and a denied request", async () => {
    const fake = new FakeZigmon();
    await fake.start(20323);
    cleanups.push(() => fake.stop());
    fake.enabled = false;
    const hub = newHub(new MemoryStore(), []);
    await hub.start();
    await hub.connect("http://127.0.0.1:" + fake.port);
    await until(() => hub.currentPhase === "off", 3000, "off");
    const k = view(hub, "scene", { item: "scene:3" });
    assert.match(k.s.svg, /Switched off/);
    fake.enabled = true;
    await hub.connect("http://127.0.0.1:" + fake.port);
    await until(() => hub.pairCode !== null, 3000, "code");
    for (const id of fake.pairs.keys()) fake.deny(id);
    await until(() => hub.currentPhase === "denied", 3000, "denied");
    assert.match(k.s.svg, /Denied/);
  });

  it("never follows a redirect", async () => {
    const fake = new FakeZigmon();
    await fake.start(20324);
    cleanups.push(() => fake.stop());
    fake.redirectEverything = true;
    const a = parseAddress("http://localhost:" + fake.port);
    assert.ok(a.ok);
    const t = new NodeTransport(a.address);
    await assert.rejects(t.request({ url: a.address.base + "/index.php?api=deck&do=hello", method: "GET", headers: {}, timeoutMs: 3000, maxBytes: 1000, pin: null }), (e: unknown) => e instanceof NetError && /redirect/.test(e.message));
    await assert.rejects(t.request({ url: "http://localhost:20399/index.php", method: "GET", headers: {}, timeoutMs: 3000, maxBytes: 1000, pin: null }), /another server/);
  });
});

// ------------------------------------------------------------------ TLS against a real handshake

function makeCert(dir: string, name: string): { key: string; cert: string; sha: string } | null {
  const r = spawnSync("openssl", [
    "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-subj", "/CN=localhost",
    "-addext", "subjectAltName=DNS:localhost", "-days", "2", "-keyout", join(dir, name + ".key"), "-out", join(dir, name + ".crt"),
  ], { stdio: "ignore", shell: false });
  if (r.status !== 0 || !existsSync(join(dir, name + ".crt"))) return null;
  const cert = readFileSync(join(dir, name + ".crt"), "utf8");
  return { key: readFileSync(join(dir, name + ".key"), "utf8"), cert, sha: normalizePin(new X509Certificate(cert).fingerprint256)! };
}

describe("TLS: system trust, else a pin the user chose", () => {
  const dir = mkdtempSync(join(tmpdir(), "zigmon-tls-"));
  const c1 = makeCert(dir, "one");
  const c2 = makeCert(dir, "two");

  it("a self-signed certificate stops before anything is sent, until it is pinned; then only that one", { skip: !c1 || !c2 ? "openssl not available" : false }, async () => {
    let fake = new FakeZigmon({ key: c1!.key, cert: c1!.cert });
    await fake.start(20321);
    cleanups.push(() => fake.stop());
    const hub = newHub(new MemoryStore(), []);
    await hub.start();
    await hub.connect("https://localhost:" + fake.port);
    await until(() => hub.currentPhase === "cert", 4000, "the certificate question");
    const st = hub.status();
    assert.equal(normalizePin(st.cert!.fingerprint), c1!.sha);
    assert.equal(st.cert!.verdict, "untrusted");
    assert.equal(fake.seen.length, 0, "not one request reached the server");
    // pin it: pairing goes on
    assert.deepEqual(await hub.pinCertificate("00:11"), { ok: false, error: "That is not the certificate the server showed - connect again." });
    assert.equal((await hub.pinCertificate(st.cert!.fingerprint)).ok, true);
    await until(() => hub.pairCode !== null, 4000, "pairing over the pinned certificate");
    assert.equal(fake.seen[0]!.do, "pair");
    // the server now shows another certificate: refused, again before anything is sent
    hub.cancelPairing();
    await fake.stop();
    fake = new FakeZigmon({ key: c2!.key, cert: c2!.cert });
    await fake.start(20321);
    cleanups.push(() => fake.stop());
    await hub.connect("https://localhost:" + fake.port);
    await until(() => hub.currentPhase === "cert", 4000, "refused");
    assert.equal(hub.status().cert!.verdict, "pin-mismatch");
    assert.equal(fake.seen.length, 0);
  });

  it("a certificate the system trusts needs no pin", { skip: !c1 ? "openssl not available" : false }, async () => {
    const fake = new FakeZigmon({ key: c1!.key, cert: c1!.cert });
    await fake.start(20322);
    cleanups.push(() => fake.stop());
    const a = parseAddress("https://localhost:" + fake.port);
    assert.ok(a.ok);
    const trusting = new NodeTransport(a.address, () => [c1!.cert]);
    const r = await trusting.request({ url: a.address.base + "/index.php?api=deck&do=hello", method: "GET", headers: {}, timeoutMs: 3000, maxBytes: 10000, pin: null });
    assert.equal(r.status, 401, "reached ZIGMon (which wants a key)");
    // ...but with a pin for some other certificate, even a trusted chain is refused
    await assert.rejects(trusting.request({ url: a.address.base + "/index.php?api=deck&do=hello", method: "GET", headers: {}, timeoutMs: 3000, maxBytes: 10000, pin: "AB".repeat(32) }), (e: unknown) => e instanceof CertError && e.verdict === "pin-mismatch");
    // and a name that does not match is not trusted
    const byIp = parseAddress("https://127.0.0.1:" + fake.port);
    assert.ok(byIp.ok);
    await assert.rejects(new NodeTransport(byIp.address, () => [c1!.cert]).request({ url: byIp.address.base + "/index.php?api=deck&do=hello", method: "GET", headers: {}, timeoutMs: 3000, maxBytes: 10000, pin: null }), (e: unknown) => e instanceof CertError && e.verdict === "untrusted");
  });
});
