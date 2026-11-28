/**
 * ZIGMon for Stream Deck - the plugin's entry point. Registers the eighteen actions, connects to
 * the Stream Deck app, then starts the one shared connection to ZIGMon (core/hub.ts).
 */
import streamDeck from "@elgato/streamdeck";
import { spawn } from "node:child_process";
import { hostname, tmpdir } from "node:os";
import {
  AwayAction, BatteriesAction, BlindsAction, ComputedAction, ControlAction, DimmerAction, HeatGroupAction, OpeningsAction, PowerAction, ReadingAction, RoomAction,
  SceneAction, SecurityAction, SmsAction, StatusAction, ThermostatAction, TimerAction, ZigbeeAction,
} from "./actions/index.js";
import { useHub } from "./actions/base.js";
import { sendStatus } from "./actions/pi-bridge.js";
import type { DeckInfo } from "./core/client.js";
import { NodeTransport } from "./core/http.js";
import { Hub } from "./core/hub.js";
import { DpapiProtector, FakeProtector } from "./core/secrets.js";
import type { GlobalSettings } from "./core/settings.js";

// "info", never "trace": trace would log every message, the stored (encrypted) key among them
streamDeck.logger.setLevel("info");
const log = streamDeck.logger.createScope("zigmon");

function decks(): DeckInfo[] {
  return streamDeck.devices.toArray().map((d) => ({
    id: d.id, type: Number(d.type), name: d.name, cols: d.size?.columns ?? 0, rows: d.size?.rows ?? 0,
  }));
}

const hub = new Hub({
  store: {
    load: () => streamDeck.settings.getGlobalSettings(),
    save: (g: GlobalSettings) => streamDeck.settings.setGlobalSettings(g),
  },
  // the plugin is for Windows; elsewhere (development only) the key is merely obscured
  protector: process.platform === "win32" ? new DpapiProtector() : new FakeProtector(),
  transport: (a) => new NodeTransport(a),
  decks,
  computer: () => hostname(),
  log: (m) => log.info(m),
  tempDir: () => process.env.TEMP || tmpdir(),
  open: async (path) => {
    // Stream Deck owns .streamDeckPlugin files: opening one asks to install it
    const child = spawn("explorer.exe", [path], { detached: true, windowsHide: true, shell: false, stdio: "ignore" });
    child.on("error", () => log.warn("could not open the downloaded update"));
    child.unref();
  },
});
useHub(hub);

let pending: ReturnType<typeof setTimeout> | null = null;
hub.onStatus(() => {
  if (pending) return;
  pending = setTimeout(() => {
    pending = null;
    void sendStatus(hub).catch(() => undefined);
  }, 200);
});

streamDeck.actions.registerAction(new ControlAction());
streamDeck.actions.registerAction(new ReadingAction());
streamDeck.actions.registerAction(new ThermostatAction());
streamDeck.actions.registerAction(new DimmerAction());
streamDeck.actions.registerAction(new BlindsAction());
streamDeck.actions.registerAction(new SceneAction());
streamDeck.actions.registerAction(new StatusAction());
// (1.3, ZIGMon 5.59.4)
for (const a of [new PowerAction(), new SecurityAction(), new HeatGroupAction(), new AwayAction(), new OpeningsAction(), new BatteriesAction(),
  new ZigbeeAction(), new TimerAction(), new RoomAction(), new SmsAction(), new ComputedAction()]) streamDeck.actions.registerAction(a);

streamDeck.system.onSystemDidWakeUp(() => hub.retryNow());
streamDeck.devices.onDeviceDidConnect(() => hub.resubscribe());

await streamDeck.connect();
await hub.start();
