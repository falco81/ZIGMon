import assert from "node:assert/strict";
import { generateKeyPairSync, sign, createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { PassThrough } from "node:stream";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { endpoint, parseAddress } from "../src/core/address.js";
import { deckQuery } from "../src/core/client.js";
import { clamp, DialAccumulator, dialAttr, roundTo, stepValue } from "../src/core/dial.js";
import { HOLD_MS, HoldPress } from "../src/core/hold.js";
import { IDLE, pairStep, pairView, type PairState } from "../src/core/pairing.js";
import {
  cleanText, parseCatalog, parseHello, parseItem, parsePairStart, parsePairWait, parseState, parseUpdate, parseWait, ProtocolError,
} from "../src/core/protocol.js";
import { DpapiProtector, DPAPI_SCRIPT, FakeProtector, powershellArgs } from "../src/core/secrets.js";
import { normalizeAction, normalizeGlobal } from "../src/core/settings.js";
import { accepted, evaluate, formatFingerprint, normalizePin, pinFor, pinMatches, withPin } from "../src/core/tls.js";
import { checkPackage, packageFileName, parseManifest, rawKey, verifyOffer, UpdateError, type ReleaseKey } from "../src/core/update.js";
import { isNewer } from "../src/core/version.js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");

// ------------------------------------------------------------------ protocol

describe("protocol", () => {
  const hello = {
    ok: true, api: 1, server: "zigmon", version: "5.59.0", house: "Chalupa", boot: 1732700000, seq: 5,
    install: { id: "0123456789abcdef0123456789abcdef", name: "OFFICE-PC", hint: "x9", caps: { view: { on: true, all: true, targets: [] }, switch: { on: true, all: false, targets: ["Lampa", 7], hold: true }, bogus: { on: true } } },
    decks: [{ id: "D1", type: 2, name: "XL", approved: true }, { id: "D2", type: 7, name: "+", approved: false }],
    plugin: { version: "1.2.0" },
  };

  it("reads hello, caps and decks", () => {
    const h = parseHello(hello);
    assert.equal(h.house, "Chalupa");
    assert.equal(h.boot, "1732700000");
    assert.deepEqual(h.install.caps.switch, { on: true, all: false, targets: ["Lampa"], hold: true });
    assert.equal("bogus" in h.install.caps, false);
    assert.deepEqual(h.decks.map((d) => d.approved), [true, false]);
    assert.equal(h.plugin?.version, "1.2.0");
  });

  it("refuses what is not ZIGMon, another API, or an error answer", () => {
    assert.throws(() => parseHello({ ...hello, server: "nginx" }), ProtocolError);
    assert.throws(() => parseHello({ ...hello, api: 2 }), /deck API 2/);
    assert.throws(() => parseHello({ ok: false, error: "nope" }), /nope/);
    assert.throws(() => parseHello([1, 2]), ProtocolError);
    assert.equal(parseHello({ ...hello, plugin: { version: "1.1; rm" } }).plugin, null);
  });

  it("cleans text: control characters, bidi overrides, length", () => {
    assert.equal(cleanText("a\u0000b\u202ec\nd", 20), "a b c d");
    assert.equal(cleanText("x".repeat(50), 10), "xxxxxxxxx…");
    assert.equal(cleanText({}, 10), "");
  });

  it("reads items leniently but safely", () => {
    const it = parseItem({
      id: "zb:0x1:brightness", name: "  Lamp\u0007 ", room: null, kind: "weird", cap: "nope", actions: ["toggle", "explode", "toggle"],
      attrs: [{ key: "brightness", type: "number", min: 100, max: 0, step: -1 }, { key: "bad key!" }], allowed: 1, hold: "yes",
      state: { on: "true", value: Infinity, value_text: "<b>", attrs: { brightness: 80, "x y": 1 }, battery: 140 },
    });
    assert.equal(it.name, "Lamp");
    assert.equal(it.kind, "other");
    assert.equal(it.cap, "view");
    assert.deepEqual(it.actions, ["toggle"]);
    assert.equal(it.attrs.length, 1);
    assert.deepEqual([it.attrs[0]!.min, it.attrs[0]!.max, it.attrs[0]!.step], [0, 100, null]);
    assert.equal(it.allowed, false);
    assert.equal(it.hold, false);
    assert.equal(it.state.on, null);
    assert.equal(it.state.value, null);
    assert.deepEqual(it.state.attrs, { brightness: 80 });
    assert.equal(it.state.battery, 100);
    assert.throws(() => parseItem({ name: "no id" }), ProtocolError);
  });

  it("a catalog keeps good items, drops bad and repeated ones", () => {
    const c = parseCatalog({ ok: true, boot: "b1", seq: 3, rooms: [{ id: 1, name: "Kitchen" }], items: [{ id: "a", name: "A" }, { nope: 1 }, { id: "a", name: "again" }, { id: "b" }] });
    assert.deepEqual(c.items.map((i) => i.id), ["a", "b"]);
    assert.equal(c.items[0]!.name, "A");
    assert.equal(c.rooms[0]!.name, "Kitchen");
  });

  it("wait answers and the pairing calls", () => {
    const w = parseWait({ ok: true, boot: 9, seq: 12, reset: false, changes: [{ seq: 11, id: "a", state: { on: true } }, { id: 5 }] });
    assert.equal(w.changes.length, 1);
    assert.equal(w.changes[0]!.state.on, true);
    const p = parsePairStart({ ok: true, pair: "0123456789abcdef01234567", secret: "zsp_" + "a".repeat(40), code: "K7Q4PX", expires: 1e9 });
    assert.equal(p.code, "K7Q-4PX");
    assert.throws(() => parsePairStart({ ok: true, pair: "x", secret: "zsp_" + "a".repeat(40), code: "K7Q-4PX", expires: 1 }), /request id/);
    assert.throws(() => parsePairStart({ ok: true, pair: "0123456789abcdef01234567", secret: "zsp_" + "a".repeat(40), code: "K0O-4PX", expires: 1 }), /code/);
    assert.equal(parsePairWait({ state: "pending" }).state, "pending");
    assert.throws(() => parsePairWait({ state: "approved" }), /no key/);
    assert.equal(parsePairWait({ state: "approved", token: "zsd_" + "b".repeat(40) }).token, "zsd_" + "b".repeat(40));
    assert.throws(() => parsePairWait({ state: "maybe" }), ProtocolError);
  });

  it("state defaults: online unless said otherwise", () => {
    const s = parseState(null);
    assert.equal(s.online, true);
    assert.equal(parseState({ online: false }).online, false);
  });

  it("update answers decode base64 and cap sizes", () => {
    const u = parseUpdate({ ok: true, available: true, version: "1.2.0", size: 10, sha256: "AB", manifest: Buffer.from("{}").toString("base64"), sig: Buffer.alloc(64).toString("base64") });
    assert.equal(u.sha256, "ab");
    assert.equal(u.sig.length, 64);
    assert.throws(() => parseUpdate({ ok: true, available: true, manifest: "!!", sig: "" }), /manifest/);
    assert.equal(parseUpdate({ ok: true, available: false }).available, false);
  });
});

// ------------------------------------------------------------------ address & queries

describe("address", () => {
  it("https only, http only to localhost", () => {
    const a = parseAddress("zigmon.example.net/");
    assert.ok(a.ok && a.address.base === "https://zigmon.example.net" && a.address.pinScope === "zigmon.example.net:443");
    const b = parseAddress("https://Host:8443/zigmon/index.php");
    assert.ok(b.ok && b.address.base === "https://host:8443/zigmon");
    assert.equal(parseAddress("http://zigmon.example.net").ok, false);
    assert.ok(parseAddress("http://localhost:20300").ok);
    for (const bad of ["", "ftp://x", "https://u:p@x", "https://x/?a=1", "https://x/#f", "https://x/a b", "https://x/../y", "https://x\\y"]) {
      assert.equal(parseAddress(bad).ok, false, bad);
    }
  });

  it("builds only the deck endpoints", () => {
    const a = parseAddress("https://z.example")!;
    assert.ok(a.ok);
    assert.equal(endpoint(a.address, "wait", { after: "3", ids: "a,b" }), "https://z.example/index.php?api=deck&do=wait&after=3&ids=a%2Cb");
    assert.throws(() => endpoint(a.address, "admin" as never));
  });

  it("deck_info stays within 2 KB", () => {
    const decks = Array.from({ length: 30 }, (_, i) => ({ id: "deck-" + i + "-" + "x".repeat(40), type: 2, name: "N".repeat(60), cols: 8, rows: 4 }));
    const q = deckQuery(decks);
    assert.ok((q.deck_info ?? "").length <= 2048);
    assert.equal(q.decks!.split(",").length, 30);
    const one = JSON.parse(Buffer.from(deckQuery([{ id: "D", type: 7, name: "My +", cols: 4, rows: 2 }]).deck_info!, "base64url").toString());
    assert.deepEqual(one, [{ id: "D", type: 7, name: "My +", cols: 4, rows: 2 }]);
  });
});

// ------------------------------------------------------------------ pairing

describe("pairing state machine", () => {
  const started = { pair: "0123456789abcdef01234567", secret: "zsp_" + "s".repeat(40), code: "K7Q-4PX", expires: 1000 };
  it("idle -> requesting -> waiting -> approved", () => {
    let s: PairState = IDLE;
    s = pairStep(s, { type: "start" });
    assert.equal(s.phase, "requesting");
    s = pairStep(s, { type: "started", answer: started });
    assert.equal(s.phase, "waiting");
    assert.deepEqual(pairView(s), { phase: "waiting", code: "K7Q-4PX", expires: 1000 });
    assert.equal(JSON.stringify(pairView(s)).includes("zsp_"), false, "the secret is never shown");
    s = pairStep(s, { type: "wait", answer: { state: "pending", token: null, install: null } });
    assert.equal(s.phase, "waiting");
    s = pairStep(s, { type: "fail", error: "net", fatal: false });
    assert.equal(s.phase === "waiting" && s.retries, 1);
    s = pairStep(s, { type: "wait", answer: { state: "approved", token: "zsd_" + "t".repeat(40), install: null } });
    assert.equal(s.phase, "approved");
  });

  it("denied, expired by the server and by the clock, fatal errors, cancel", () => {
    const w = pairStep(pairStep(IDLE, { type: "start" }), { type: "started", answer: started });
    assert.equal(pairStep(w, { type: "wait", answer: { state: "denied", token: null, install: null } }).phase, "denied");
    assert.equal(pairStep(w, { type: "wait", answer: { state: "expired", token: null, install: null } }).phase, "expired");
    assert.equal(pairStep(w, { type: "tick", now: 999_000 }).phase, "waiting");
    assert.equal(pairStep(w, { type: "tick", now: 1_000_000 }).phase, "expired");
    assert.equal(pairStep(w, { type: "fail", error: "off", fatal: true }).phase, "failed");
    assert.equal(pairStep(w, { type: "cancel" }).phase, "idle");
    assert.equal(pairStep(IDLE, { type: "wait", answer: { state: "approved", token: "zsd_" + "t".repeat(40), install: null } }).phase, "idle", "an answer without a request is ignored");
    assert.equal(pairStep(pairStep(IDLE, { type: "start" }), { type: "fail", error: "x", fatal: false }).phase, "failed");
  });
});

// ------------------------------------------------------------------ dials

describe("dial stepping", () => {
  const pct = { min: 0, max: 100, step: 1 };
  it("delta, clamp, step", () => {
    assert.deepEqual(stepValue(70, 3, 5, pct), { value: 85, delta: 15 });
    assert.deepEqual(stepValue(95, 3, 5, pct), { value: 100, delta: 5 });
    assert.deepEqual(stepValue(2, -1, 5, pct), { value: 0, delta: -2 });
    assert.deepEqual(stepValue(100, 1, 5, pct), { value: 100, delta: 0 });
    assert.deepEqual(stepValue(21.5, 1, 0.5, { min: 5, max: 30, step: 0.5 }), { value: 22, delta: 0.5 });
    assert.deepEqual(stepValue(21.3, -1, 0.5, { min: 5, max: 30, step: 0.5 }), { value: 21, delta: -0.3 });
    assert.equal(roundTo(0.1 + 0.2, 0.1), 0.3);
    assert.equal(clamp(5, null, 3), 3);
  });

  it("picks the attribute a dial turns", () => {
    const item = parseItem({ id: "t", attrs: [{ key: "system_mode", type: "enum", values: ["heat"] }, { key: "local_temperature", type: "number" }, { key: "current_heating_setpoint", type: "number" }] });
    assert.equal(dialAttr(item, "thermostat")?.key, "current_heating_setpoint");
    assert.equal(dialAttr(parseItem({ id: "x" }), "dimmer"), null);
  });

  it("gathers a quick spin into one delta", async () => {
    const sent: [number, number][] = [];
    const acc = new DialAccumulator(async (d, v) => { sent.push([d, v]); }, 20);
    assert.equal(acc.turn(1, 50, 5, pct), 55);
    assert.equal(acc.turn(2, 50, 5, pct), 65);
    assert.equal(acc.shown, 65);
    await new Promise((r) => setTimeout(r, 60));
    assert.deepEqual(sent, [[15, 65]]);
    assert.equal(acc.shown, null);
    acc.turn(-30, 65, 5, pct);
    await new Promise((r) => setTimeout(r, 60));
    assert.deepEqual(sent[1], [-65, 0]);
  });
});

// ------------------------------------------------------------------ hold

describe("hold to confirm", () => {
  it("fires at once without hold", () => {
    const ev: string[] = [];
    const p = new HoldPress(false, { progress: () => ev.push("p"), fire: (h) => ev.push("fire:" + h), tooShort: () => ev.push("short") });
    p.down();
    p.up();
    assert.deepEqual(ev, ["fire:undefined"]);
  });

  it("fills a ring and fires at 1.5 s with the time held", () => {
    let now = 0;
    const ev: (string | number)[] = [];
    const p = new HoldPress(true, { progress: (x) => ev.push(Math.round(x * 100)), fire: (h) => ev.push("fire:" + h), tooShort: () => ev.push("short") }, () => now, 1e9);
    p.down();
    now = 750;
    p.tick();
    now = HOLD_MS + 10;
    p.tick();
    p.up();
    assert.deepEqual(ev, [0, 50, 100, "fire:1510"]);
  });

  it("letting go early is not a press", () => {
    let now = 0;
    const ev: string[] = [];
    const p = new HoldPress(true, { progress: () => undefined, fire: () => ev.push("fire"), tooShort: () => ev.push("short") }, () => now, 1e9);
    p.down();
    now = 1200;
    p.up();
    assert.deepEqual(ev, ["short"]);
  });
});

// ------------------------------------------------------------------ TLS pins

describe("TLS pin logic", () => {
  const fp = "AB".repeat(32);
  it("normalises and formats", () => {
    assert.equal(normalizePin("ab:".repeat(31) + "ab"), fp);
    assert.equal(normalizePin("xyz"), null);
    assert.equal(formatFingerprint(fp).split(":").length, 32);
    assert.ok(pinMatches(formatFingerprint(fp), fp.toLowerCase()));
    assert.equal(pinMatches(fp, "CD".repeat(32)), false);
  });

  it("the one rule: system trust without a pin, only the pin with one", () => {
    assert.equal(evaluate(fp, true, null), "trusted");
    assert.equal(evaluate(fp, false, null), "untrusted");
    assert.equal(evaluate(fp, false, fp), "pinned");
    assert.equal(evaluate(fp, true, "CD".repeat(32)), "pin-mismatch", "a pin wins even over a trusted chain");
    assert.equal(evaluate(null, true, null), "missing");
    assert.ok(accepted("pinned") && accepted("trusted") && !accepted("untrusted") && !accepted("pin-mismatch"));
  });

  it("pins are per host:port", () => {
    let pins = withPin({}, "a:443", fp);
    pins = withPin(pins, "b:443", "CD".repeat(32));
    assert.equal(pinFor(pins, "a:443"), fp);
    assert.equal(pinFor(pins, "a:8443"), null);
    assert.equal(pinFor(withPin(pins, "a:443", null), "a:443"), null);
  });
});

// ------------------------------------------------------------------ settings & secrets

describe("settings", () => {
  it("global settings keep only what is expected", () => {
    const g = normalizeGlobal({ address: "https://x", install: "0123456789abcdef0123456789abcdef", tokenBlob: "zsd_plaintext", pins: { "x:443": "ab".repeat(32), bad: "nope" }, extra: 1 });
    assert.equal(g.tokenBlob, undefined, "a plain token is never accepted as the stored key");
    assert.deepEqual(g.pins, { "x:443": "AB".repeat(32) });
    assert.equal("extra" in g, false);
    assert.equal(normalizeGlobal({ install: "short" }).install, undefined);
  });

  it("action settings", () => {
    const s = normalizeAction({ item: "Lampa", press: "explode", step: "5", warnAbove: "", critAbove: "30", decimals: 9, showRoom: false });
    assert.deepEqual(s, { item: "Lampa", step: 5, critAbove: 30, showRoom: false });
    assert.deepEqual(normalizeAction(null), {});
  });

  it("the fake protector round-trips; DPAPI gets the secret on stdin only", async () => {
    const f = new FakeProtector();
    const blob = await f.protect("zsd_secret");
    assert.ok(!blob.includes("zsd_secret"));
    assert.equal(await f.unprotect(blob), "zsd_secret");
    const args = powershellArgs();
    assert.ok(!args.join(" ").includes("zsd_"));
    assert.ok(DPAPI_SCRIPT.includes("CurrentUser") && DPAPI_SCRIPT.includes("[Console]::In.ReadLine()"));
    // a fake powershell: checks how it was started and answers on stdout
    let stdinText = "", argsSeen: string[] = [], optsSeen: Record<string, unknown> = {};
    const spawn = ((cmd: string, a: string[], o: Record<string, unknown>) => {
      argsSeen = [cmd, ...a];
      optsSeen = o;
      const child = new EventEmitter() as EventEmitter & { stdin: PassThrough; stdout: PassThrough; stderr: PassThrough; kill(): void };
      child.stdin = new PassThrough();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.kill = () => undefined;
      child.stdin.on("data", (c: Buffer) => (stdinText += c));
      child.stdin.on("finish", () => {
        child.stdout.end(Buffer.from("ENCRYPTED").toString("base64"));
        setTimeout(() => child.emit("close", 0), 5);
      });
      return child;
    }) as never;
    const d = new DpapiProtector(spawn);
    const out = await d.protect("zsd_" + "k".repeat(40));
    assert.equal(out, "dpapi:" + Buffer.from("ENCRYPTED").toString("base64"));
    assert.equal(stdinText, "P " + Buffer.from("zsd_" + "k".repeat(40)).toString("base64") + "\n");
    assert.ok(!argsSeen.join(" ").includes("zsd_") && !argsSeen.join(" ").includes(Buffer.from("zsd_").toString("base64").slice(0, 4) + "a"));
    assert.equal(optsSeen.shell, false);
    await assert.rejects(d.unprotect("fake:abc"), /DPAPI/);
  });
});

// ------------------------------------------------------------------ updates & release keys

describe("updates", () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const raw = publicKey.export({ format: "der", type: "spki" }).subarray(12).toString("hex");
  const keys: ReleaseKey[] = [{ name: "test", key: rawKey(raw) }];
  const pkg = Buffer.concat([Buffer.from([0x50, 0x4b, 0x03, 0x04]), Buffer.from("zip body")]);
  const sha = createHash("sha256").update(pkg).digest("hex");
  const manifest = (o: Record<string, unknown> = {}) => Buffer.from(JSON.stringify({ product: "ZIGMon for Stream Deck", file: "com.zigmon.streamdeck.streamDeckPlugin", version: "1.4.0", size: pkg.length, sha256: sha, requires: "Stream Deck 7.1, Windows 10/11", ...o }) + "\n");
  const offer = (m: Buffer, sig = sign(null, m, privateKey), o: Record<string, unknown> = {}) => ({ available: true, version: "1.4.0", size: pkg.length, sha256: sha, manifest: m, sig, ...o });

  it("accepts a signed, matching, newer release and its package", () => {
    const v = verifyOffer(offer(manifest()), keys);
    assert.equal(v.manifest.version, "1.4.0");
    assert.equal(v.keyName, "test");
    checkPackage(pkg, v);
    assert.equal(packageFileName("1.4.0"), "ZIGMon-1.4.0.streamDeckPlugin");
    assert.throws(() => packageFileName("..\\x"), UpdateError);
  });

  it("refuses a tampered manifest, a foreign key, mismatches, old versions, a wrong package", () => {
    const m = manifest();
    const tampered = Buffer.from(m.toString().replace("1.4.0", "1.4.1"));
    assert.throws(() => verifyOffer(offer(tampered, sign(null, m, privateKey)), keys), /not signed/);
    const other = generateKeyPairSync("ed25519").privateKey;
    assert.throws(() => verifyOffer(offer(m, sign(null, m, other)), keys), /not signed/);
    assert.throws(() => verifyOffer(offer(m, undefined, { sha256: "0".repeat(64) }), keys), /checksum is not the one advertised/);
    assert.throws(() => verifyOffer(offer(m, undefined, { version: "1.5.0" }), keys), /version is not the one advertised/);
    assert.throws(() => verifyOffer(offer(m, undefined, { size: 3 }), keys), /size/);
    assert.throws(() => verifyOffer(offer(manifest({ product: "Other" })), keys), /another product/);
    assert.throws(() => verifyOffer(offer(manifest({ version: "1.0.0" }), undefined, { version: "1.0.0" }), keys), /not newer/);
    assert.throws(() => verifyOffer(offer(m, Buffer.alloc(10)), keys), /malformed/);
    const twice = Buffer.from('{"product":"ZIGMon for Stream Deck","product":"x"}');
    assert.throws(() => parseManifest(twice), /twice/);
    const v = verifyOffer(offer(m), keys);
    const bad = Buffer.from(pkg);
    bad[6] = 0;
    assert.throws(() => checkPackage(bad, v), /checksum/);
    assert.throws(() => checkPackage(pkg.subarray(1), v), /size/);
    assert.ok(isNewer("1.3.1") && !isNewer("1.0") && !isNewer("x"));
  });

  it("the embedded release keys are the ones in deploy/release-keys", async () => {
    const { RELEASE_KEYS } = await import("../src/core/release-keys.generated.js");
    const { readKeys } = await import(join(root, "scripts", "gen-release-keys.mjs"));
    const want = readKeys(join(root, "..", "deploy", "release-keys")) as { name: string; hex: string }[];
    assert.deepEqual(RELEASE_KEYS.map((k) => ({ name: k.name, hex: k.hex })), want);
    assert.ok(want.length > 0);
    for (const k of RELEASE_KEYS) rawKey(k.hex);
    // and the notifier embeds the same ones
    const cs = readFileSync(join(root, "..", "windows", "ZigmonNotifier.Core", "ReleaseKeys.cs"), "utf8");
    for (const k of want) assert.ok(cs.includes(k.hex));
  });
});
