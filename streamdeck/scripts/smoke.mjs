// A smoke test of the BUILT plugin (bin/plugin.js) with the real @elgato/streamdeck SDK inside it:
// plays the Stream Deck app on a local WebSocket (port 20330), registers the plugin, shows it a
// key and a dial, and checks the plugin answers with setImage / setFeedback / setTriggerDescription.
//   node scripts/smoke.mjs
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");
const here = dirname(fileURLToPath(import.meta.url));
const plugin = join(here, "..", "com.zigmon.streamdeck.sdPlugin", "bin", "plugin.js");
const PORT = 20330;
const { FakeZigmon } = await import(join(here, "..", "out", "test", "fake-zigmon.js"));
const fake = new FakeZigmon();
fake.autoApprove = true;
await fake.start(20332);

const info = {
  application: { font: "Segoe UI", language: "en", platform: "windows", platformVersion: "10.0.22631", version: "7.1.0.21000" },
  plugin: { uuid: "com.zigmon.streamdeck", version: "1.0.0.0" },
  devicePixelRatio: 2,
  colors: {},
  devices: [
    { id: "DEV-XL", name: "Office XL", size: { columns: 8, rows: 4 }, type: 2 },
    { id: "DEV-PLUS", name: "Stream Deck +", size: { columns: 4, rows: 2 }, type: 7 },
  ],
};

const wss = new WebSocketServer({ port: PORT, host: "127.0.0.1" });
const seen = [];
let connectSent = false;
let pressed = false;
let child;
const done = new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("the plugin did not draw in time; saw: " + seen.map((m) => m.event).join(", "))), 15000);
  wss.on("connection", (ws) => {
    ws.on("message", (raw) => {
      const m = JSON.parse(String(raw));
      seen.push(m);
      if (m.event === "registerPlugin") {
        const appear = (context, action, device, controller) => ws.send(JSON.stringify({
          event: "willAppear", action, context, device,
          payload: { settings: context === "ctx-key" ? { item: "Lampa" } : { item: "zb:0xc3:trv" }, coordinates: { column: 0, row: 0 }, controller, isInMultiAction: false },
        }));
        setTimeout(() => {
          appear("ctx-key", "com.zigmon.streamdeck.control", "DEV-XL", "Keypad");
          ws.send(JSON.stringify({ event: "propertyInspectorDidAppear", action: "com.zigmon.streamdeck.control", context: "ctx-key", device: "DEV-XL" }));
          appear("ctx-dial", "com.zigmon.streamdeck.thermostat", "DEV-PLUS", "Encoder");
        }, 100);
      }
      if (m.event === "getGlobalSettings") {
        ws.send(JSON.stringify({ event: "didReceiveGlobalSettings", id: m.id, payload: { settings: {} } }));
      }
      const img = seen.find((x) => x.event === "setImage" && x.context === "ctx-key");
      const fb = seen.find((x) => x.event === "setFeedback" && x.context === "ctx-dial");
      const td = seen.find((x) => x.event === "setTriggerDescription" && x.context === "ctx-dial");
      const gs = seen.find((x) => x.event === "setGlobalSettings");
      if (img && fb && td && gs && !connectSent) {
        connectSent = true;
        // the property inspector asks to connect; the fake ZIGMon approves at once
        ws.send(JSON.stringify({ event: "sendToPlugin", action: "com.zigmon.streamdeck.control", context: "ctx-key", payload: { t: "connect", address: "http://localhost:20332" } }));
      }
      const lamp = seen.filter((x) => x.event === "setImage" && x.context === "ctx-key").some((x) => Buffer.from(x.payload.image.split(",")[1], "base64").toString().includes("Lampa"));
      if (lamp && !pressed) {
        pressed = true;
        ws.send(JSON.stringify({ event: "keyDown", action: "com.zigmon.streamdeck.control", context: "ctx-key", device: "DEV-XL", payload: { settings: { item: "Lampa" }, coordinates: { column: 0, row: 0 }, isInMultiAction: false } }));
        ws.send(JSON.stringify({ event: "keyUp", action: "com.zigmon.streamdeck.control", context: "ctx-key", device: "DEV-XL", payload: { settings: { item: "Lampa" }, coordinates: { column: 0, row: 0 }, isInMultiAction: false } }));
      }
      if (pressed && fake.commands.length > 0) {
        clearTimeout(timer);
        resolve({ img, fb, td, gs });
      }
    });
  });
});

child = spawn(process.execPath, [plugin, "-port", String(PORT), "-pluginUUID", "PLUGIN-UUID", "-registerEvent", "registerPlugin", "-info", JSON.stringify(info)], { cwd: dirname(dirname(plugin)), stdio: ["ignore", "inherit", "inherit"] });
try {
  const { img, fb, td, gs } = await done;
  const svg = Buffer.from(img.payload.image.split(",")[1], "base64").toString("utf8");
  const cmd = fake.commands[0];
  if (cmd.deck !== "DEV-XL" || cmd.id !== "Lampa" || cmd.action !== "toggle") throw new Error("unexpected command " + JSON.stringify(cmd));
  const pi = seen.filter((m) => m.event === "sendToPropertyInspector").map((m) => m.payload.t);
  if (!pi.includes("status") || !pi.includes("catalog")) throw new Error("the property inspector got no status/catalog: " + pi.join(","));
  const kept = seen.filter((m) => m.event === "setGlobalSettings").map((m) => m.payload.tokenBlob).filter(Boolean);
  if (!kept.length || !kept.every((b) => /^(fake|dpapi):/.test(b))) throw new Error("the key was not kept encrypted");
  if (!svg.startsWith("<svg") || !svg.includes("Connect")) throw new Error("the key does not ask to connect: " + svg.slice(0, 120));
  if (!fb.payload.value || !/Connect/.test(JSON.stringify(fb.payload))) throw new Error("the dial does not ask to connect");
  if (!td.payload.rotate) throw new Error("no trigger description for the dial");
  if (!/^[0-9a-f]{32}$/.test(gs.payload.install ?? "")) throw new Error("no installation id kept");
  if (seen.some((m) => JSON.stringify(m).includes("zsd_"))) throw new Error("a key was sent to Stream Deck in the clear");
  console.log("smoke: the built plugin registered, drew a key and a dial, paired with a fake ZIGMon and switched a socket (" + seen.length + " messages)");
} finally {
  child.kill();
  wss.close();
  await fake.stop();
}
