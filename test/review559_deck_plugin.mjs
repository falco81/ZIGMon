// The plugin's own core (streamdeck/out, compiled by its tsc) against the real ZIGMon behind the
// real PHP relay - driven by test/review559_deck_plugin.py, which starts both and answers for the
// house's devices. Every check prints; the first failure ends it with exit code 1.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";

const job = JSON.parse(process.env.DECK_JOB);
const core = (m) => import(join(job.core, "src", "core", m + ".js"));
const { Hub } = await core("hub");
const { NodeTransport } = await core("http");
const { FakeProtector } = await core("secrets");
const { rawKey } = await core("update");
const { ActionView, fits } = await core("views");
const { MemoryStore, MockSurface, until } = await import(join(job.core, "test", "fake-zigmon.js"));

const BULB = job.bulb, THERMO = job.thermo, BLIND = job.blind, TEMP = job.temp;
const DECKS = [
  { id: "XL-1", type: 2, name: "Office XL", cols: 8, rows: 4 },
  { id: "PLUS-1", type: 7, name: "Stream Deck +", cols: 4, rows: 2 },
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let step = "";
const say = (s) => { step = s; console.log(s); };

async function admin(body) {
  const r = await fetch(job.daemon + "/api/deck/admin", {
    method: body ? "POST" : "GET",
    headers: { "X-Zigmon-Token": job.token, "X-Zigmon-Session": job.session, "Content-Type": "application/json", "X-Zigmon-Client": "192.168.40.10" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  assert.equal(r.status, 200, "admin " + JSON.stringify(body) + ": " + JSON.stringify(j));
  return j;
}
async function ctl(path, body) {
  const r = await fetch(job.control + path, body ? { method: "POST", body: JSON.stringify(body) } : {});
  return r.json();
}
const fired = async () => ctl("/fired");
async function firedHas(pred, what, ms = 9000) {
  const end = Date.now() + ms;
  for (;;) {
    const f = await fired();
    const hit = f.find(pred);
    if (hit) return hit;
    if (Date.now() > end) throw new Error("not fired: " + what + " - fired: " + JSON.stringify(f.slice(-6)));
    await sleep(40);
  }
}

const store = new MemoryStore();
const logs = [];
const opened = [];
const hub = new Hub({
  store, protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => DECKS, computer: () => "OFFICE-PC",
  log: (m) => logs.push(m), keys: [{ name: "throwaway", key: rawKey(job.releaseKey) }], tempDir: () => job.tmp,
  open: async (p) => { opened.push(p); }, minBackoffMs: 50, maxBackoffMs: 400,
});
const views = [];
function view(kind, settings, ctl_ = "Keypad", deck = "XL-1") {
  const s = new MockSurface(ctl_, deck);
  const v = new ActionView(kind, hub, s, settings);
  hub.watch(v);
  v.draw(true);
  views.push({ v, s, kind, settings });
  return { v, s };
}
const fbText = (s) => JSON.stringify(s.feedbacks.at(-1) ?? {});
const press = async (v, ms = 0) => { v.keyDown(); if (ms) await sleep(ms); v.keyUp(); };

try {
  say("pairing: the code on the keys, the same in ZIGMon");
  await hub.start();
  const lamp = view("control", { item: "Lampa" });
  const bulb = view("control", { item: "zb:" + BULB + ":state" });
  await hub.connect(job.relay);
  await until(() => hub.pairCode !== null, 8000, "a pairing code");
  const code = hub.pairCode;
  await until(() => lamp.s.svg.includes(code.slice(0, 3)), 3000, "the code on the key");
  let a = await admin();
  assert.equal(a.pairs.length, 1);
  assert.equal(a.pairs[0].code, code, "the code ZIGMon shows is the plugin's");
  assert.equal(a.pairs[0].computer, "OFFICE-PC");
  assert.deepEqual(a.pairs[0].decks.map((x) => [x.id, x.type, x.cols, x.rows]), [["XL-1", 2, 8, 4], ["PLUS-1", 7, 4, 2]]);
  assert.equal(hub.currentPhase, "pairing");

  say("approved with permissions - the + left unticked");
  const caps = {
    view: { on: true, all: true, targets: [] }, switch: { on: true, all: true, targets: [], hold: false },
    dim: { on: true, all: true, targets: [], hold: false }, climate: { on: true, all: true, targets: [], hold: false },
    cover: { on: true, all: true, targets: [], hold: false }, scenes: { on: true, all: true, targets: [], hold: false },
    automations: { on: false, all: false, targets: [], hold: false }, messages: { on: false, all: false, targets: [], hold: false },
    system: { on: true, all: true, targets: [], hold: true }, status: { on: true },
  };
  await admin({ action: "approve", pair: a.pairs[0].pair, decks: ["XL-1"], caps });
  await until(() => hub.currentPhase === "online", 8000, "online");
  assert.match(String(store.value.tokenBlob), /^fake:/, "the key is kept only encrypted");
  assert.ok(!JSON.stringify(store.saved).includes("zsd_"), "the plain key is never stored");
  await until(() => lamp.s.svg.includes("Lampa"), 3000, "the lamp drawn");
  // php -S (the relay here) lets one worker take two connections that arrive together, and a
  // long poll then holds the other behind it; php-fpm under nginx does not. A moment for the
  // plugin's wait to be under way before the first press.
  await sleep(800);
  const st = hub.status();
  assert.equal(st.install.name, "OFFICE-PC");
  assert.equal(st.zigmon.length > 0, true);
  assert.ok(st.items > 20, "the catalogue: " + st.items);
  assert.equal(hub.deckIsApproved("XL-1"), true);
  assert.equal(hub.deckIsApproved("PLUS-1"), false);

  say("a socket and a Zigbee light toggled; the long poll redraws");
  await press(lamp.v);
  await firedHas((f) => f[0] === "plug" && f[1] === "Lampa" && f[2] === "toggle" && f[3] === "Stream Deck 'OFFICE-PC'", "Lampa toggle");
  await until(() => hub.state("Lampa")?.on === true, 4000, "Lampa on");
  await until(() => /41 W/.test(lamp.s.svg), 3000, "Lampa's power drawn");
  await press(bulb.v);
  await firedHas((f) => f[0] === "zb" && f[1] === BULB && f[2] === "state" && f[3] === "toggle", "bulb toggle");
  await until(() => hub.state("zb:" + BULB + ":state")?.on === false, 4000, "the bulb off");
  const sock = view("control", { item: "Zasuvka" });
  await until(() => /35\.25 W|35\.3 W|35 W/.test(sock.s.svg), 3000, "the socket's watts");
  await ctl("/plug", { name: "Zasuvka", flat: { "switch.output": false, "switch.apower": 0 } });
  await until(() => hub.state("Zasuvka")?.on === false, 6000, "the change from the house, by the long poll");
  const reading = view("reading", { item: "read:" + TEMP + ":temperature" });
  await until(() => reading.s.svg.includes("21.5"), 3000, "the reading");
  await ctl("/report", { name: "Teplomer", payload: { temperature: 23.5 } });
  await until(() => reading.s.svg.includes("23.5"), 6000, "the reading redrawn");

  say("a deck not approved: deck_pending, then approved in ZIGMon");
  const dim = view("dimmer", { item: "zb:" + BULB + ":state" }, "Encoder", "PLUS-1");
  await until(() => /Approve deck/.test(fbText(dim.s)), 3000, "the + drawn as waiting");
  dim.v.rotate(1);
  await sleep(600);
  assert.ok(!(await fired()).some((f) => f[2] === "brightness"), "nothing sent from an unapproved deck");
  await admin({ action: "deck_approve", install: (await admin()).installs[0].id, deck: "PLUS-1" });
  await until(() => hub.deckIsApproved("PLUS-1") === true, 8000, "the + approved, learnt by the plugin");

  say("dials: brightness, a head's set point, a room's temperature");
  await until(() => /Off|%/.test(fbText(dim.s)), 3000, "the dimmer's level (the bulb is off)");
  dim.v.rotate(2);
  let f = await firedHas((x) => x[0] === "zb" && x[2] === "brightness", "brightness");
  const b = Number(String(f[3]).slice(4));
  assert.ok(b > 127 && b <= 254, "brightness up from 127: " + f[3]);
  await until(() => hub.state("zb:" + BULB + ":state")?.attrs.brightness === b, 4000, "the brightness back from the device");
  const trv = view("thermostat", { item: "zb:" + THERMO + ":current_heating_setpoint" }, "Encoder", "PLUS-1");
  await until(() => /20\.5/.test(fbText(trv.s)), 3000, "the head's measured temperature");
  trv.v.rotate(1);
  f = await firedHas((x) => x[0] === "zb" && x[2] === "current_heating_setpoint", "the set point");
  assert.equal(f[3], "set:21.5");
  await until(() => hub.state("zb:" + THERMO + ":current_heating_setpoint")?.attrs.current_heating_setpoint === 21.5, 4000, "set point back");
  const room = view("thermostat", { item: "heat:temp:r1" }, "Encoder", "PLUS-1");
  const wanted = hub.state("heat:temp:r1").attrs.target;
  assert.equal(typeof wanted, "number", "the room's wanted temperature: " + JSON.stringify(hub.state("heat:temp:r1")));
  room.v.rotate(-2);
  await until(() => hub.state("heat:temp:r1")?.attrs.target === wanted - 1, 6000, "the room one degree down");

  say("(1.1) a heated room's own key: its target, its mode, by hand from the dial, a mode outright");
  const rk = view("thermostat", { item: "heat:room:r2" });
  await until(() => typeof hub.state("heat:room:r2")?.attrs.target === "number", 4000, "the room's target");
  const rt = hub.state("heat:room:r2").attrs.target;
  await until(() => rk.s.svg.includes("→ " + rt.toFixed(1)) && /Plan/.test(rk.s.svg), 3000, "the target and the mode drawn: " + rt);
  const rd = view("thermostat", { item: "heat:room:r2" }, "Encoder", "PLUS-1");
  rd.v.rotate(2);
  await until(() => hub.state("heat:room:r2")?.attrs.by_hand === true && hub.state("heat:room:r2")?.attrs.target === rt + 1, 6000, "set by hand from the dial");
  await until(() => /By hand until \d\d:\d\d/.test(rk.s.svg), 3000, "by hand until, on the key");
  const rm = view("thermostat", { item: "heat:room:r2", press: "set:eco" });
  await press(rm.v);
  await until(() => hub.state("heat:room:r2")?.attrs.mode === "eco", 6000, "the room to eco");
  await until(() => /Eco/.test(rk.s.svg), 3000, "Eco on the key");
  await press(view("thermostat", { item: "heat:room:r2", press: "set:plan" }).v);
  await until(() => hub.state("heat:room:r2")?.attrs.mode === "plan", 6000, "the room back on its plan");

  say("(1.1) the graphs: ZIGMon's own history, at once");
  const rg = view("reading", { item: "read:" + TEMP + ":temperature" });
  await until(() => (hub.series("read:" + TEMP + ":temperature", 86400)?.length ?? 0) >= 40, 6000, "the reading's day from ZIGMon");
  await until(() => (rg.s.svg.match(/ L /g)?.length ?? 0) >= 40, 3000, "drawn as a line of the day");
  const rh = view("thermostat", { item: "heat:room:r2", showGraph: true, span: 21600 });
  await until(() => (hub.series("heat:room:r2", 21600)?.length ?? 0) >= 10, 6000, "the room's thermometer over six hours");

  say("the head's mode and preset cycled, its boost");
  trv.v.dialDown(); trv.v.dialUp();
  f = await firedHas((x) => x[0] === "zb" && x[2] === "system_mode", "the mode");
  assert.equal(f[3], "set:auto");
  const trvp = view("thermostat", { item: "zb:" + THERMO + ":current_heating_setpoint", press: "preset" }, "Encoder", "PLUS-1");
  trvp.v.dialDown(); trvp.v.dialUp();
  f = await firedHas((x) => x[0] === "zb" && x[2] === "preset", "the preset");
  assert.equal(f[3], "set:schedule");
  trv.v.touch(false);
  f = await firedHas((x) => x[0] === "zb" && x[2] === "boost_heating", "the boost");
  assert.equal(f[3], "set:ON");
  await until(() => hub.state("zb:" + THERMO + ":current_heating_setpoint")?.attrs.boost_heating === true, 4000, "boost back");

  say("the blinds and a scene");
  const blind = view("blinds", { item: "zb:" + BLIND + ":state" }, "Encoder", "PLUS-1");
  blind.v.dialDown(); blind.v.dialUp();
  f = await firedHas((x) => x[0] === "zb" && x[1] === BLIND && x[2] === "state", "the blinds pushed");
  assert.equal(f[3], "set:OPEN");
  await until(() => hub.state("zb:" + BLIND + ":state")?.attrs.position === 100, 4000, "opened");
  blind.v.rotate(-2);
  f = await firedHas((x) => x[0] === "zb" && x[1] === BLIND && x[2] === "position", "the blinds turned");
  assert.ok(Number(String(f[3]).slice(4)) < 100, f[3]);
  const scene = view("scene", { item: "scene:sc1" });
  await press(scene.v);
  await firedHas((x) => x[0] === "scene" && x[1] === "sc1", "the scene");
  await until(() => scene.s.images.some((i) => Buffer.from(i.split(",")[1], "base64").toString().includes("M20 6 9 17l-5-5")), 3000, "the scene's tick");

  say("the status keys");
  const stat = {};
  for (const k of ["alerts", "blocked", "proxy", "health", "gateway"]) stat[k] = view("status", { item: "status:" + k });
  await sleep(300);
  assert.match(stat.alerts.s.svg, />1</, "one alert");
  assert.match(stat.blocked.s.svg, />0</, "none blocked");
  assert.ok(stat.gateway.s.svg.length > 200);

  say("hold: system needs it - a quick press does nothing, a held one is sent with held_ms");
  const sys = view("scene", { item: "sys:refresh" });
  await press(sys.v, 100);
  await sleep(300);
  assert.ok(!(await fired()).some((x) => x[0] === "sys"), "a quick press of a held item");
  await press(sys.v, 1800);
  await firedHas((x) => x[0] === "sys" && x[1] === "refresh", "the held system action");
  say("hold asked by ZIGMon after the plugin learnt the catalogue: 409, then the key knows");
  caps.switch.hold = true;
  await admin({ action: "caps", install: (await admin()).installs[0].id, caps });
  const before = (await fired()).length;
  await press(lamp.v);
  await until(() => hub.item("Lampa")?.hold === true, 6000, "hold learnt (409 or the catalogue again)");
  await sleep(300);
  assert.equal((await fired()).length, before, "a quick press of a held item is not done");
  await press(lamp.v, 1800);
  await firedHas((x, i) => x[0] === "plug" && x[1] === "Lampa" && x[2] === "toggle", "held toggle");

  say("permissions taken away under a waiting plugin: it starts over");
  caps.scenes = { on: false, all: false, targets: [], hold: false };
  await admin({ action: "caps", install: (await admin()).installs[0].id, caps });
  await until(() => hub.item("scene:sc1")?.allowed === false, 8000, "the scene no longer allowed");
  await press(scene.v);
  await until(() => /Not allowed/.test(scene.s.svg), 3000, "drawn as not allowed");

  say("an update, signed with a throwaway key, downloaded and checked");
  await until(() => hub.status().update?.version === job.offer, 4000, "the update offered");
  await hub.installUpdate();
  assert.equal(hub.status().updating.state, "done", hub.status().updating.message);
  assert.equal(opened.length, 1);
  const got = readFileSync(opened[0]);
  assert.equal(got.length, job.plugin_size);
  assert.equal(createHash("sha256").update(got).digest("hex"), job.plugin_sha);

  say("every key of the real catalogue drawn");
  mkdirSync(job.shots, { recursive: true });
  const shots = [];
  const kindFor = (it) => it.kind === "status" ? "status" : it.kind === "reading" ? "reading" : it.kind === "thermostat" ? "thermostat"
    : it.kind === "cover" ? "blinds" : it.kind === "dimmer" ? "dimmer" : fits("scene", it) && it.actions.includes("run") ? "scene" : "control";
  const ids = [];
  for (const id of ["Lampa", "Zasuvka", "zb:" + BULB + ":state", "zb:" + BULB + ":brightness", "zb:" + THERMO + ":current_heating_setpoint",
                    "zb:" + THERMO + ":system_mode", "heat:temp:r1", "heat:room:r1", "zb:" + BLIND + ":state", "scene:sc1", "sys:refresh",
                    "read:" + TEMP + ":temperature", "read:" + TEMP + ":humidity", "status:alerts", "status:blocked", "status:proxy",
                    "status:health", "status:gateway", "tell:house", "heat:control"]) {
    const it = hub.item(id);
    if (!it) continue;
    ids.push(id);
    const k = view(kindFor(it), { item: id });
    shots.push({ name: "key-" + id.replace(/[^A-Za-z0-9]+/g, "_"), svg: k.s.svg });
  }
  for (const [n, x] of [["dimmer-plus", dim], ["thermostat-head", trv], ["thermostat-room", room], ["blinds", blind]]) {
    const uri = x.v.previewImage();
    shots.push({ name: "dial-" + n, svg: Buffer.from(uri.split(",")[1], "base64").toString("utf8") });
  }
  for (const s of shots) writeFileSync(join(job.shots, s.name + ".svg"), s.svg);
  writeFileSync(join(job.shots, "dials.json"), JSON.stringify({ dimmer: dim.s.feedbacks.at(-1), thermostat: trv.s.feedbacks.at(-1),
    room: room.s.feedbacks.at(-1), blinds: blind.s.feedbacks.at(-1) }, null, 1));
  try {
    const require = createRequire(import.meta.url);
    const { chromium } = require("playwright");
    const br = await chromium.launch();
    const p = await br.newPage({ viewport: { width: 144, height: 144 } });
    for (const s of shots) {
      await p.setContent('<html><body style="margin:0;background:#000">' + s.svg + "</body></html>");
      await p.screenshot({ path: join(job.shots, s.name + ".png") });
    }
    const all = await br.newPage({ viewport: { width: 8 * 152 + 8, height: Math.ceil(shots.length / 8) * 152 + 8 } });
    await all.setContent('<html><body style="margin:0;padding:4px;background:#111;display:flex;flex-wrap:wrap;gap:8px">'
      + shots.map((s) => '<div style="width:144px;height:144px;border-radius:14px;overflow:hidden">' + s.svg + "</div>").join("") + "</body></html>");
    await all.screenshot({ path: join(job.shots, "all-keys.png") });
    await br.close();
    console.log("  PNGs in " + job.shots);
  } catch (e) {
    console.log("  no browser for the PNGs (" + String(e).slice(0, 120) + ") - the SVGs are in " + job.shots);
  }

  say("revoked in ZIGMon: the plugin forgets its key");
  await admin({ action: "revoke", install: (await admin()).installs[0].id });
  await until(() => hub.currentPhase === "revoked", 8000, "revoked");
  await until(() => /Disconnected/.test(lamp.s.svg), 3000, "drawn as disconnected");
  assert.equal(store.value.tokenBlob, undefined, "the key is forgotten");

  say("never a secret in the plugin's log or status");
  for (const l of logs) assert.ok(!/zsd_|zsp_/.test(l), "a log line holds a secret: " + l);
  assert.ok(!/zsd_|zsp_/.test(JSON.stringify(hub.status())));
  hub.stop();
  for (const x of views) x.v.dispose();
  console.log("plugin e2e: all good");
  process.exit(0);
} catch (e) {
  console.log("FAILED at '" + step + "': " + (e && e.stack || e));
  console.log("phase " + hub.currentPhase + " " + JSON.stringify(hub.status()).slice(0, 600));
  console.log("plugin log: " + logs.slice(-8).join(" | "));
  for (const x of views.slice(0, 4)) console.log("alerts " + x.s.alerts + " images " + x.s.images.length + " key " + JSON.stringify(x.settings) + ": " + (x.s.svg.match(/>[^<>]{2,}</g) || []).join(" "));
  try { console.log("fired: " + JSON.stringify((await fired()).slice(-8))); console.log("daemon: " + (await ctl("/log")).slice(-15).join("\n")); if (process.env.DECK_STACKS) console.log("STACKS\n" + (await ctl("/stacks")).join("\n----\n")); } catch {}
  hub.stop();
  process.exit(1);
}
