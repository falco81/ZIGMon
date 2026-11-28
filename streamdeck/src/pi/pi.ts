/**
 * The property inspectors of ZIGMon for Stream Deck: one script for all seven actions
 * (the page's <body data-action="..."> says which). It talks to the Stream Deck app over its
 * WebSocket, to the plugin with sendToPlugin, and never to ZIGMon itself. Everything shown
 * that came from the server is put in with textContent, never as HTML.
 */
import { ICONS, iconMarkup } from "../core/icons.js";
import { cleanHex, hexToHsv, hsvToHex, type Hsv } from "../core/colour.js";
import { ACCENTS, colourOf, P } from "../core/palette.js";
import { lookFor } from "../core/render.js";
import { THEMES } from "../core/themes.js";

type Kind = "control" | "reading" | "thermostat" | "dimmer" | "blinds" | "scene" | "status";

interface PiAttr { key: string; label: string; type: string; unit: string; min: number | null; max: number | null; step: number | null; values: string[] }
interface PiItem {
  id: string; name: string; room: string | null; kind: string; icon: string; cap: string; allowed: boolean; hold: boolean;
  actions: string[]; attrs: PiAttr[]; valueText: string; on: boolean | null; online: boolean;
}
interface CapGrant { on: boolean; all: boolean; targets: string[]; hold: boolean }
interface Status {
  phase: string; message: string; plugin: string; address: string; house: string; zigmon: string;
  install: { name: string; hint: string; caps: Record<string, CapGrant> } | null;
  decks: { id: string; name: string; type: number; cols: number; rows: number; approved: boolean | null }[];
  pair: { code: string; expires: number } | null;
  cert: { fingerprint: string; subject: string; issuer: string; validTo: string; verdict: string; scope: string } | null;
  pinned: string | null;
  update: { version: string } | null;
  updating: { state: string; message: string };
  retryInMs: number | null;
  items: number;
}
type Settings = Record<string, string | number | boolean | null | undefined>;

const KIND = (document.body.dataset.action || "control") as Kind;

let ws: WebSocket | null = null;
let ctx = "";
let actionUuid = "";
let deviceId = "";
let settings: Settings = {};
let status: Status | null = null;
let items: PiItem[] = [];
let catalogLoaded = false;
let preview = "";
/** (1.1) The Look section's pictures, drawn by the plugin from the item's real state. */
interface Looks { themes: { id: string; name: string; image: string }[]; on: string; off: string; words: [string, string] }
let looks: Looks | null = null;
let query = "";
let pickerOpen = false;
let connOpen = false;
let addressDraft: string | null = null;
let connectError = "";
let busy = false;
let confirmDisconnect = false;

// ------------------------------------------------------------------ tiny DOM helpers

function h<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, kids?: (Node | string | null | undefined | false)[]): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const k of kids ?? []) if (k !== null && k !== undefined && k !== false) e.append(typeof k === "string" ? document.createTextNode(k) : k);
  return e;
}

/** One of our own icons (constant markup from core/icons.ts - never server text). */
function ic(name: string, cls = "", fallback = "sensor"): SVGSVGElement {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", ("i " + cls).trim());
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = iconMarkup(name, fallback);
  return s;
}

function rgba(hex: string, a: number): string {
  const v = parseInt(hex.slice(1), 16);
  return `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${a})`;
}

function tile(iconName: string, colour: string, small = false): HTMLElement {
  const t = h("div", "tile" + (small ? " sm" : ""), [ic(iconName, small ? "sm" : "")]);
  t.style.setProperty("--c", colour);
  t.style.setProperty("--cb", rgba(colour, 0.15));
  t.style.setProperty("--cl", rgba(colour, 0.4));
  return t;
}

function btn(label: string, cls: string, iconName: string | null, onClick: () => void, key?: string): HTMLButtonElement {
  const b = h("button", "btn " + cls, [iconName ? ic(iconName, "sm") : null, label]);
  b.type = "button";
  if (key) b.dataset.key = key;
  b.addEventListener("click", onClick);
  return b;
}

// ------------------------------------------------------------------ Stream Deck

function sd(o: unknown): void {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(o));
}

function toPlugin(payload: Record<string, unknown>): void {
  sd({ action: actionUuid, event: "sendToPlugin", context: ctx, payload });
}

function saveSettings(patch: Settings): void {
  settings = { ...settings, ...patch };
  for (const k of Object.keys(settings)) if (settings[k] === undefined) delete settings[k];
  sd({ event: "setSettings", context: ctx, payload: settings });
  render();
}

function onMessage(ev: MessageEvent): void {
  let m: { event?: string; payload?: Record<string, unknown> };
  try {
    m = JSON.parse(String(ev.data));
  } catch {
    return;
  }
  if (m.event === "didReceiveSettings") {
    // (1.3) while a colour is being dragged, this page's own settings are the newer ones
    if (dragging) return;
    settings = ((m.payload?.settings as Settings) ?? {});
    render();
  } else if (m.event === "sendToPropertyInspector") {
    const p = m.payload ?? {};
    if (p.t === "status") {
      const was = status?.phase;
      status = p.status as Status;
      if (status.phase !== "pairing") busy = false;
      // just connected (or reconnected): fetch what may be picked, and the key's look
      if (status.phase === "online" && was !== "online") toPlugin({ t: "catalog" });
      if (status.phase !== was) toPlugin({ t: "preview" });
    } else if (p.t === "catalog") {
      items = (p.items as PiItem[]) ?? [];
      catalogLoaded = true;
    } else if (p.t === "preview") {
      preview = typeof p.image === "string" && p.image.startsWith("data:image/svg+xml") ? p.image : "";
      looks = cleanLooks(p.looks);
      // (1.3) mid-pick the page is not rebuilt (it would drop the pointer, or what is half typed): only the pictures change
      if (picking()) {
        patchPictures();
        return;
      }
    } else if (p.t === "connect") {
      busy = false;
      connectError = p.ok ? "" : String(p.error ?? "");
      if (p.ok) addressDraft = null;
    } else if (p.t === "pin") {
      connectError = p.ok ? "" : String(p.error ?? "");
    }
    render();
  }
}

(window as unknown as Record<string, unknown>).connectElgatoStreamDeckSocket = (port: string, uuid: string, registerEvent: string, _info: string, actionInfo: string) => {
  ctx = uuid;
  try {
    const ai = JSON.parse(actionInfo) as { action: string; device: string; payload?: { settings?: Settings } };
    actionUuid = ai.action;
    deviceId = ai.device;
    settings = ai.payload?.settings ?? {};
  } catch {
    /* keep the defaults */
  }
  ws = new WebSocket("ws://127.0.0.1:" + port);
  ws.onopen = () => {
    sd({ event: registerEvent, uuid });
    toPlugin({ t: "hello" });
  };
  ws.onmessage = onMessage;
  render();
};

/** Only pictures we drew (data:image/svg+xml) and our own look names get onto the page. */
function cleanLooks(v: unknown): Looks | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const pic = (x: unknown) => (typeof x === "string" && x.startsWith("data:image/svg+xml") ? x : "");
  const known = new Map(THEMES.map((t) => [t.id, t.name]));
  const themes = Array.isArray(o.themes)
    ? o.themes.flatMap((t) => {
      const r = t as Record<string, unknown>;
      return typeof r.id === "string" && known.has(r.id) && pic(r.image) ? [{ id: r.id, name: known.get(r.id)!, image: pic(r.image) }] : [];
    })
    : [];
  const w = Array.isArray(o.words) ? o.words.map((x) => (typeof x === "string" ? x.slice(0, 20) : "")) : [];
  return { themes, on: pic(o.on), off: pic(o.off), words: [w[0] || "On", w[1] || "Off"] };
}

// ------------------------------------------------------------------ words

const PHASE: Record<string, { title: string; tone: "ok" | "warn" | "crit" | "info" | "mute"; icon: string }> = {
  setup: { title: "Not connected", tone: "mute", icon: "zigmon" },
  unpaired: { title: "Not paired yet", tone: "info", icon: "zigmon" },
  pairing: { title: "Waiting for approval", tone: "info", icon: "hourglass" },
  connecting: { title: "Connecting…", tone: "info", icon: "refresh" },
  online: { title: "Connected", tone: "ok", icon: "zigmon" },
  offline: { title: "ZIGMon is not answering", tone: "crit", icon: "wifiOff" },
  cert: { title: "Check the certificate", tone: "warn", icon: "shieldAlert" },
  off: { title: "Switched off in ZIGMon", tone: "warn", icon: "lock" },
  revoked: { title: "Disconnected by ZIGMon", tone: "crit", icon: "unlink" },
  denied: { title: "Pairing was denied", tone: "crit", icon: "close" },
};

const CAP_WORDS: [string, string, string, string][] = [
  ["view", "States & readings", "pulse", P.water],
  ["switch", "Switching", "power", P.ok],
  ["dim", "Dimming & colour", "sun", P.warn],
  ["climate", "Heating", "thermostat", P.orange],
  ["cover", "Blinds", "blinds", P.purple],
  ["scenes", "Scenes", "scene", P.purple],
  ["automations", "Automations", "rule", P.pink],
  ["messages", "Messages", "message", P.info],
  ["system", "System", "gear", P.crit],
  ["status", "ZIGMon status", "heart", P.ok],
];

const DECK_TYPES: Record<number, string> = {
  0: "Stream Deck", 1: "Stream Deck Mini", 2: "Stream Deck XL", 3: "Stream Deck Mobile", 4: "Corsair G-Keys", 5: "Stream Deck Pedal",
  6: "Corsair Voyager", 7: "Stream Deck +", 8: "SCUF controller", 9: "Stream Deck Neo", 10: "Stream Deck Studio", 11: "Virtual Stream Deck",
};

const TITLES: Record<Kind, [string, string]> = {
  control: ["What this key controls", "Any item ZIGMon allows this deck to use"],
  reading: ["The reading to show", "Big value, trend and a sparkline"],
  thermostat: ["The thermostat", "Turn: setpoint · push: mode · touch: boost"],
  dimmer: ["The light", "Turn: brightness · push: on / off"],
  blinds: ["The blinds", "Turn: position · push: stop / open / close"],
  scene: ["The scene to run", "Scenes, sequences and groups of actions"],
  status: ["What to watch", "ZIGMon's own health"],
};

// ------------------------------------------------------------------ the deck pictures

function deckPic(type: number, cols: number, rows: number): SVGSVGElement {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", "pic");
  s.setAttribute("width", "56");
  s.setAttribute("height", "40");
  s.setAttribute("viewBox", "0 0 56 40");
  let body = `<rect x="1" y="1" width="54" height="38" rx="6" fill="${P.bg}" stroke="${P.line}" stroke-width="1.5"/>`;
  if (type === 7) {
    for (let r = 0; r < 2; r++) for (let c = 0; c < 4; c++) body += `<rect x="${7 + c * 11}" y="${4 + r * 9}" width="8" height="7" rx="1.6" fill="${P.panel2}" stroke="${P.info}" stroke-opacity=".55"/>`;
    body += `<rect x="6" y="23" width="44" height="4" rx="2" fill="${P.info}" fill-opacity=".35"/>`;
    for (let c = 0; c < 4; c++) body += `<circle cx="${11 + c * 11.3}" cy="33" r="3.4" fill="${P.panel2}" stroke="${P.dim}"/>`;
  } else {
    const C = Math.max(1, Math.min(10, cols || 5)), R = Math.max(1, Math.min(6, rows || 3));
    const gw = 46 / C, gh = 30 / R, k = Math.min(gw, gh) - 1.6;
    for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) {
      body += `<rect x="${(5 + c * gw + (gw - k) / 2).toFixed(1)}" y="${(5 + r * gh + (gh - k) / 2).toFixed(1)}" width="${k.toFixed(1)}" height="${k.toFixed(1)}" rx="1.4" fill="${P.panel2}" stroke="${P.info}" stroke-opacity=".55"/>`;
    }
  }
  s.innerHTML = body;
  return s;
}

// ------------------------------------------------------------------ the connection card

function codeBlock(code: string): HTMLElement {
  const [a, b] = code.split("-");
  const k = h("div", "k", [a ?? "", h("span", "dash", ["-"]), b ?? ""]);
  return h("div", "code", [k, h("div", "l", ["Also shown on every ZIGMon key"])]);
}

function timer(expires: number): HTMLElement {
  const bar = h("i");
  const words = h("span");
  const t = h("div", "timer", [ic("clock", "sm"), h("div", "bar", [bar]), words]);
  const tick = () => {
    const left = Math.max(0, Math.round(expires - Date.now() / 1000));
    bar.style.width = Math.min(100, (left / 900) * 100) + "%";
    words.textContent = Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0") + " left";
  };
  tick();
  t.dataset.expires = String(expires);
  return t;
}

function connectForm(st: Status | null): HTMLElement[] {
  const input = h("input", "in" + (connectError ? " bad" : "")) as HTMLInputElement;
  input.type = "url";
  input.placeholder = "https://zigmon.example.net";
  input.spellcheck = false;
  input.dataset.key = "address";
  input.value = addressDraft ?? st?.address ?? "";
  input.addEventListener("input", () => {
    addressDraft = input.value;
    connectError = "";
  });
  const go = () => {
    busy = true;
    connectError = "";
    toPlugin({ t: "connect", address: input.value });
    render();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") go();
  });
  const b = btn(busy ? "Connecting…" : "Connect", "primary", "link", go, "connect");
  if (busy) b.disabled = true;
  const out: HTMLElement[] = [
    h("label", "f", ["Address of your ZIGMon dashboard"]),
    h("div", "row", [input, b]),
  ];
  if (connectError) out.push(h("div", "err", [connectError]));
  out.push(h("div", "note", [ic("info", "sm"), h("span", "", [
    "In ZIGMon, switch on ", h("b", "", ["Settings → Messages → Stream Deck → Allow Stream Deck control"]),
    " first. Connecting shows a code here and on your keys; approve it in ZIGMon.",
  ])]));
  return out;
}

function capsSummary(caps: Record<string, CapGrant>): HTMLElement {
  const wrap = h("div", "caps");
  let any = false;
  for (const [key, label, iconName, colour] of CAP_WORDS) {
    const g = caps[key];
    if (!g || !g.on) continue;
    any = true;
    const scope = key === "status" || key === "view" && g.all ? "" : g.all ? "all" : g.targets.length + (g.targets.length === 1 ? " item" : " items");
    const c = h("span", "cap", [ic(iconName, "sm"), label, scope ? h("span", "sc", [scope]) : null, g.hold ? ic("hand", "sm") : null]);
    c.style.setProperty("--c", colour);
    if (g.hold) c.title = "Hold the key 1.5 s to confirm";
    wrap.append(c);
  }
  if (!any) wrap.append(h("span", "cap off", [ic("lock", "sm"), "Nothing granted yet"]));
  return wrap;
}

function decksList(st: Status): HTMLElement {
  const list = h("div", "decks");
  for (const d of st.decks) {
    const tag = d.approved === true ? h("span", "tag ok", [ic("check", "sm"), "Approved"])
      : d.approved === false ? h("span", "tag warn", [ic("hourglass", "sm"), "Approve in ZIGMon"])
        : h("span", "tag mute", ["Not known yet"]);
    const here = d.id === deviceId;
    list.append(h("div", "deck", [
      deckPic(d.type, d.cols, d.rows),
      h("div", "grow", [h("div", "n", [d.name || DECK_TYPES[d.type] || "Stream Deck"]), h("div", "ty", [(DECK_TYPES[d.type] ?? "Stream Deck") + (d.cols && d.type !== 7 ? " · " + d.cols + "×" + d.rows : "") + (here ? " · this key" : "")]), tag]),
    ]));
  }
  if (st.decks.length === 0) list.append(h("div", "muted small", ["No Stream Deck is plugged in."]));
  return list;
}

function connectionCard(): HTMLElement {
  const st = status;
  const ph = PHASE[st?.phase ?? "setup"] ?? PHASE.setup!;
  const card = h("div", "card" + (ph.tone !== "mute" && ph.tone !== "ok" ? " tint-" + ph.tone : ""));
  const online = st?.phase === "online";
  const sub = online ? (st!.house || "ZIGMon") + (st!.zigmon ? " · ZIGMon " + st!.zigmon : "") : st?.message || (st?.address ? st.address : "ZIGMon for Stream Deck");
  const head = h("div", "head" + (online ? " collapse" : ""), [
    h("div", "mark " + (ph.tone === "mute" ? "" : ph.tone), [ic(ph.icon, "lg")]),
    h("div", "grow", [h("div", "t", [ph.title]), h("div", "s", [sub])]),
    h("span", "dot " + (ph.tone === "mute" ? "" : ph.tone)),
    online ? ic("down", "sm chev") : null,
  ]);
  card.append(head);
  if (online) {
    if (connOpen) card.classList.add("open");
    head.addEventListener("click", () => {
      connOpen = !connOpen;
      render();
    });
  }
  if (!st) {
    card.append(h("p", "muted small", ["Waiting for the plugin…"]));
    return card;
  }
  switch (st.phase) {
    case "setup":
    case "unpaired":
      card.append(...connectForm(st));
      break;
    case "pairing":
      if (st.pair) {
        card.append(codeBlock(st.pair.code));
        card.append(h("ol", "steps", [
          h("li", "", ["Open ZIGMon → ", h("b", "", ["Settings → Messages → Stream Deck"])]),
          h("li", "", ["Check the request shows ", h("b", "", [st.pair.code])]),
          h("li", "", ["Choose what this deck may do and ", h("b", "", ["Approve"])]),
        ]));
        card.append(timer(st.pair.expires));
      } else card.append(h("p", "muted", ["Asking ZIGMon for a code…"]));
      card.append(h("div", "btns", [btn("Cancel", "", "close", () => toPlugin({ t: "cancel" }))]));
      break;
    case "cert":
      if (st.cert) {
        const mismatch = st.cert.verdict === "pin-mismatch";
        card.append(h("p", "", [mismatch
          ? "The server shows a different certificate than the one you trusted. If ZIGMon's certificate was renewed, compare the new fingerprint with ZIGMon's Settings → Security; otherwise someone may be in the way."
          : "Windows does not trust this server's certificate (self-signed?). Compare its fingerprint with the one in ZIGMon before trusting it."]));
        const fpParts = st.cert.fingerprint.split(":");
        card.append(h("div", "fp", [0, 8, 16, 24].flatMap((i) => [fpParts.slice(i, i + 8).join(":"), i < 24 ? h("br") : ""])));
        const kv = h("dl", "kv", [
          h("dt", "", ["Issued to"]), h("dd", "", [st.cert.subject || "—"]),
          h("dt", "", ["Issued by"]), h("dd", "", [st.cert.issuer || "—"]),
          h("dt", "", ["Valid until"]), h("dd", "", [st.cert.validTo || "—"]),
          h("dt", "", ["For"]), h("dd", "", [st.cert.scope]),
        ]);
        card.append(kv);
        card.append(h("div", "btns", [
          btn("Trust this certificate", "warn", "shieldOk", () => toPlugin({ t: "pin", fingerprint: st.cert!.fingerprint })),
        ]));
        if (mismatch) card.append(h("div", "btns", [btn("Forget the old one", "danger", "trash", () => toPlugin({ t: "unpin" }))]));
      } else card.append(h("p", "muted", [st.message]));
      if (connectError) card.append(h("div", "err", [connectError]));
      card.append(h("div", "btns", [btn("Change address", "ghost", "edit", () => toPlugin({ t: "cancel" }))]));
      break;
    case "offline":
    case "connecting":
      if (st.retryInMs !== null) card.append(h("p", "muted small", ["Trying again in " + Math.ceil(st.retryInMs / 1000) + " s. Keys keep their last state until then."]));
      card.append(h("div", "btns", [btn("Try now", "", "refresh", () => toPlugin({ t: "retry" })), btn("Disconnect", "danger", "unlink", () => toPlugin({ t: "disconnect" }))]));
      break;
    case "off":
      card.append(h("p", "", ["The administrator has switched Stream Deck control off. In ZIGMon: ", h("b", "", ["Settings → Messages → Stream Deck → Allow Stream Deck control"]), "."]));
      card.append(h("div", "btns", [btn("Check again", "", "refresh", () => toPlugin({ t: "retry" })), btn("Disconnect", "danger", "unlink", () => toPlugin({ t: "disconnect" }))]));
      break;
    case "revoked":
    case "denied":
      card.append(h("p", "", [st.message]));
      card.append(...connectForm(st));
      break;
    case "online": {
      if (!connOpen) break;
      card.append(h("div", "facts", [
        h("div", "fact", [h("div", "a", ["House"]), h("div", "b", [st.house || "—"])]),
        h("div", "fact", [h("div", "a", ["ZIGMon"]), h("div", "b", [st.zigmon || "—"])]),
        h("div", "fact", [h("div", "a", ["Name in ZIGMon"]), h("div", "b", [st.install?.name || "—"])]),
        h("div", "fact", [h("div", "a", ["Items"]), h("div", "b", [String(st.items)])]),
      ]));
      card.append(h("div", "sep"));
      card.append(h("h2", "", [ic("deck", "sm"), "Stream Decks", h("span", "count", [String(st.decks.length)])]));
      card.append(decksList(st));
      card.append(h("div", "sep"));
      card.append(h("h2", "", [ic("key", "sm"), "Allowed by ZIGMon"]));
      card.append(capsSummary(st.install?.caps ?? {}));
      card.append(h("p", "muted small", ["Only what is allowed here can be used. The administrator changes it in ZIGMon → Settings → Messages → Stream Deck."]));
      card.append(h("div", "sep"));
      const addr = h("div", "muted small mono", [st.address]);
      card.append(addr);
      if (st.pinned) card.append(h("div", "muted small", [ic("shieldOk", "sm"), " Trusted certificate ", h("span", "mono", [st.pinned.slice(0, 23) + "…"])]));
      if (confirmDisconnect) {
        card.append(h("div", "note crit", [ic("alert", "sm"), "Forget this deck's key? You will need to pair again (and ZIGMon still lists it until revoked there)."]));
        card.append(h("div", "btns", [btn("Keep", "", null, () => { confirmDisconnect = false; render(); }), btn("Disconnect", "danger", "unlink", () => { confirmDisconnect = false; toPlugin({ t: "disconnect" }); })]));
      } else card.append(h("div", "btns", [btn("Disconnect", "danger", "unlink", () => { confirmDisconnect = true; render(); })]));
      break;
    }
  }
  return card;
}

function updateCard(): HTMLElement | null {
  const st = status;
  if (!st || (!st.update && st.updating.state === "idle")) return null;
  const u = st.updating;
  const tone = u.state === "failed" ? "tint-crit" : u.state === "done" ? "tint-ok" : "tint-info";
  const card = h("div", "card " + tone);
  const right = u.state === "working"
    ? h("span", "tag mute", [ic("hourglass", "sm"), "Working"])
    : u.state === "done" ? h("span", "tag ok", [ic("check", "sm"), "Opened"])
      : btn("Update", "primary", "download", () => toPlugin({ t: "update" }));
  card.append(h("div", "update", [
    tile("download", P.info),
    h("div", "grow", [
      h("div", "t", [st.update ? "Update to " + st.update.version : "Update"]),
      h("div", "muted small", [u.message || "Signed by ZIGMon's release key; checked before it is opened."]),
    ]),
    right,
  ]));
  return card;
}

// ------------------------------------------------------------------ the item picker

function itemColour(it: PiItem): string {
  return lookFor(it.kind, it.icon, it.on).accent;
}

function itemIcon(it: PiItem): string {
  const l = lookFor(it.kind, it.icon, it.on);
  return l.icon in ICONS || it.icon === "" ? l.icon : l.icon;
}

function highlight(text: string): (Node | string)[] {
  if (!query) return [text];
  const i = text.toLowerCase().indexOf(query.toLowerCase());
  if (i < 0) return [text];
  return [text.slice(0, i), h("mark", "", [text.slice(i, i + query.length)]), text.slice(i + query.length)];
}

function stateWord(it: PiItem): HTMLElement {
  if (!it.online) return h("span", "st", ["offline"]);
  if (it.on === true) return h("span", "st on", [it.valueText || "on"]);
  if (it.on === false) return h("span", "st", [it.valueText || "off"]);
  return h("span", "st", [it.valueText]);
}

function picker(): HTMLElement {
  const card = h("div", "card");
  const [title, lede] = TITLES[KIND];
  card.append(h("h2", "", [ic(KIND === "reading" ? "gauge" : KIND === "status" ? "heart" : "grid", "sm"), title, catalogLoaded ? h("span", "count", [String(items.length)]) : null]));
  const chosen = items.find((i) => i.id === settings.item);
  const st = status;
  if (!st || st.phase !== "online") {
    if (!catalogLoaded || items.length === 0) {
      card.append(h("div", "empty", [ic("link"), st && (st.phase === "offline" || st.phase === "connecting") ? "Waiting for ZIGMon…" : "Connect to ZIGMon above to choose."]));
      return card;
    }
  }
  if (settings.item && !pickerOpen) {
    const it = chosen;
    const row = h("div", "picked", [
      it ? tile(itemIcon(it), itemColour(it)) : tile("search", P.muted),
      h("div", "grow", [
        h("div", "n", [it ? it.name : String(settings.item)]),
        h("div", "s", [it ? [it.room, kindWord(it.kind)].filter(Boolean).join(" · ") : "Not shown to this deck by ZIGMon"]),
      ]),
      btn("Change", "", "edit", () => { pickerOpen = true; query = ""; render(); }, "change"),
    ]);
    card.append(row);
    if (it && !it.allowed) card.append(h("div", "note crit", [ic("lock", "sm"), h("span", "", ["ZIGMon does not allow this deck to control it. The administrator can grant it in ", h("b", "", ["Settings → Messages → Stream Deck → Permissions"]), "."])]));
    else if (it && it.hold) card.append(h("div", "note warn", [ic("hand", "sm"), "ZIGMon asks for a confirmation: hold the key (or the dial) for 1.5 s - a ring fills while you hold."]));
    if (preview) {
      const img = h("img") as HTMLImageElement;
      img.src = preview;
      img.alt = "";
      img.dataset.pic = "preview";
      card.append(h("div", "sep"), h("div", "preview", [img, h("div", "muted small", [lede])]));
    }
    return card;
  }
  card.append(h("p", "muted small", [lede]));
  const search = h("input", "in") as HTMLInputElement;
  search.type = "search";
  search.placeholder = "Search by name, room or kind";
  search.dataset.key = "search";
  search.value = query;
  search.addEventListener("input", () => {
    query = search.value;
    renderList();
  });
  const box = h("div", "search", [ic("search", "sm"), search]);
  card.append(box);
  const list = h("div", "list");
  list.id = "list";
  card.append(list);
  if (settings.item) card.append(h("div", "btns", [btn("Keep the current one", "ghost", "close", () => { pickerOpen = false; render(); })]));
  queueMicrotask(renderList);
  return card;
}

function kindWord(k: string): string {
  const w: Record<string, string> = {
    socket: "socket", light: "light", switch: "switch", dimmer: "dimmer", thermostat: "thermostat", cover: "blinds", scene: "scene",
    sequence: "sequence", group: "group of actions", rule: "rule", schedule: "schedule", message: "message", system: "system",
    sensor: "sensor", reading: "reading", status: "ZIGMon status",
  };
  return w[k] ?? k;
}

function renderList(): void {
  const list = document.getElementById("list");
  if (!list) return;
  list.replaceChildren();
  const q = query.trim().toLowerCase();
  const hits = items.filter((i) => !q || [i.name, i.room ?? "", kindWord(i.kind), i.id].some((s) => s.toLowerCase().includes(q)));
  if (hits.length === 0) {
    list.append(h("div", "empty", [ic("search"), q ? "Nothing matches “" + query + "”" : "ZIGMon shows nothing of this kind to this deck."]));
    return;
  }
  const groups = new Map<string, PiItem[]>();
  for (const it of hits) {
    const r = it.room ?? "";
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r)!.push(it);
  }
  const names = [...groups.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  for (const r of names) {
    const g = groups.get(r)!.sort((a, b) => Number(b.allowed) - Number(a.allowed) || a.name.localeCompare(b.name));
    list.append(h("div", "room", [ic(r ? "door" : "grid", "sm"), r || "Elsewhere", h("span", "c", [String(g.length)])]));
    for (const it of g) {
      const o = h("div", "opt" + (it.id === settings.item ? " sel" : "") + (it.allowed ? "" : " locked"), [
        tile(itemIcon(it), it.allowed ? itemColour(it) : P.muted, true),
        h("div", "grow", [h("div", "n", highlight(it.name)), h("div", "s", [kindWord(it.kind)])]),
        stateWord(it),
        !it.allowed ? h("span", "badge", [ic("lock", "sm")]) : it.hold ? h("span", "badge hold", [ic("hand", "sm")]) : null,
      ]);
      o.title = it.allowed ? (it.hold ? "Hold to confirm" : "") : "Not allowed by ZIGMon for this deck";
      o.addEventListener("click", () => {
        pickerOpen = false;
        preview = "";
        saveSettings({ item: it.id });
      });
      list.append(o);
    }
  }
}

// ------------------------------------------------------------------ per-action options

function chips(label: string, options: [string, string, string?][], current: string | undefined, key: string): HTMLElement[] {
  const wrap = h("div", "chips");
  for (const [v, word, iconName] of options) {
    const c = h("button", "chip" + (current === v ? " on" : ""), [iconName ? ic(iconName, "sm") : null, word]);
    c.type = "button";
    c.addEventListener("click", () => saveSettings({ [key]: key === "span" || key === "step" || key === "decimals" ? Number(v) : v }));
    wrap.append(c);
  }
  return [h("label", "f", [label]), wrap];
}

function numberField(label: string, key: string, placeholder: string, step = "any"): HTMLElement {
  const i = h("input", "in") as HTMLInputElement;
  i.type = "number";
  i.step = step;
  i.placeholder = placeholder;
  i.dataset.key = key;
  const v = settings[key];
  i.value = v === undefined || v === null ? "" : String(v);
  i.addEventListener("change", () => saveSettings({ [key]: i.value === "" ? undefined : Number(i.value) }));
  return h("div", "", [h("label", "f", [label]), i]);
}

function toggle(label: string, key: string, def: boolean): HTMLElement {
  const on = settings[key] === undefined ? def : settings[key] === true;
  const s = h("div", "switch" + (on ? " on" : ""), [h("span", "", [label]), h("span", "k")]);
  s.addEventListener("click", () => saveSettings({ [key]: !on }));
  return s;
}

function optionsCard(): HTMLElement | null {
  const it = items.find((i) => i.id === settings.item);
  const card = h("div", "card");
  card.append(h("h2", "", [ic("gear", "sm"), "Options"]));
  const press = settings.press as string | undefined;
  switch (KIND) {
    case "control": {
      const acts = (it?.actions ?? ["toggle", "on", "off"]).filter((a) => a !== "set" && a !== "step");
      const words: Record<string, [string, string]> = {
        toggle: ["Toggle", "switch"], on: ["Turn on", "power"], off: ["Turn off", "power"], run: ["Run", "play"], open: ["Open", "blindsUp"], close: ["Close", "blindsDown"], stop: ["Stop", "stop"],
      };
      if (acts.length) card.append(...chips("A press of the key / dial", acts.map((a) => [a, words[a]?.[0] ?? a, words[a]?.[1]] as [string, string, string?]), press ?? acts[0], "press"));
      if (it?.attrs.some((a) => a.type === "number")) card.append(numberField("Dial: change per click (empty = automatic)", "step", "auto"));
      break;
    }
    case "reading": {
      card.append(...chips("Decimals", [["-1", "As ZIGMon"], ["0", "0"], ["1", "0.0"], ["2", "0.00"]], String(settings.decimals ?? -1), "decimals"));
      card.append(h("label", "f", ["Colours: amber and red outside these"]));
      card.append(h("div", "grid2", [numberField("Amber below", "warnBelow", "—"), numberField("Amber above", "warnAbove", "—"), numberField("Red below", "critBelow", "—"), numberField("Red above", "critAbove", "—")]));
      break;
    }
    case "thermostat": {
      card.append(...chips("Push the dial / press the key", [["mode", "Next mode", "refresh"], ["preset", "Next preset", "layers"], ["boost", "Boost", "flame"], ["details", "Show details (3 s)", "info"]], press ?? "mode", "press"));
      const modes = it?.attrs.find((a) => a.type === "enum" && /mode/i.test(a.key))?.values ?? [];
      const words: Record<string, [string, string]> = {
        plan: ["Plan", "calendar"], comfort: ["Comfort", "sun"], eco: ["Eco", "leaf"], night: ["Night", "moon"], max: ["Max", "flame"], off: ["Off", "power"], manual: ["By hand", "hand"],
      };
      const set = modes.filter((m) => m in words);
      if (set.length) card.append(...chips("…or set one mode", set.map((m) => ["set:" + m, words[m]![0], words[m]![1]] as [string, string, string]), press, "press"));
      if (set.length) card.append(h("div", "note", [ic("info", "sm"), "Next mode goes round all of them, Plan and By hand included. Turning the dial sets the room by hand, as the dashboard's slider does."]));
      card.append(...chips("Setpoint per click", [["0.1", "0.1°"], ["0.5", "0.5°"], ["1", "1°"]], String(settings.step ?? "0.5"), "step"));
      card.append(h("div", "note", [ic("info", "sm"), "Touch the strip for boost (when the thermostat has one)."]));
      break;
    }
    case "dimmer":
      card.append(...chips("Brightness per click", [["1", "1%"], ["5", "5%"], ["10", "10%"], ["20", "20%"]], String(settings.step ?? "5"), "step"));
      break;
    case "blinds":
      card.append(...chips("Push the dial / press the key", [["openclose", "Open / close", "blinds"], ["stop", "Stop", "stop"], ["open", "Open", "blindsUp"], ["close", "Close", "blindsDown"]], press ?? "openclose", "press"));
      card.append(...chips("Position per click", [["5", "5%"], ["10", "10%"], ["20", "20%"], ["25", "25%"]], String(settings.step ?? "10"), "step"));
      break;
    case "scene":
    case "status":
      break;
  }
  if (KIND !== "reading" && KIND !== "status") card.append(holdSwitch(it));
  if (KIND === "control" && it && it.cap === "switch") card.append(byHandSwitch());
  if (card.childElementCount <= 1) return null;
  return card;
}

// ------------------------------------------------------------------ (1.1) the look

/** What each action calls its pieces of information, and which it has. */
const INFO: Record<Kind, [string, string, string][]> = {
  control: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showRoom", "Room", "door"], ["showState", "On / off", "power"], ["showDetail", "Value (W…)", "bolt"], ["showGraph", "Level bar", "dial"], ["showBattery", "Battery", "battery"]],
  reading: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showState", "Value", "gauge"], ["showDetail", "Trend", "trendUp"], ["showGraph", "Graph", "pulse"], ["showBattery", "Battery", "battery"]],
  thermostat: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showState", "Measured", "thermo"], ["showDetail", "Target", "thermostat"], ["showMode", "Mode / preset", "layers"], ["showGraph", "Temperature graph", "pulse"]],
  dimmer: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showRoom", "Room", "door"], ["showState", "On / off", "power"], ["showDetail", "Brightness %", "sun"], ["showGraph", "Level bar", "dial"]],
  blinds: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showRoom", "Room", "door"], ["showState", "Position", "blinds"], ["showDetail", "Moving", "down"], ["showGraph", "Window", "window"]],
  scene: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showRoom", "Room", "door"], ["showState", "Run / done", "play"]],
  status: [["showIcon", "Icon", "grid"], ["showName", "Name", "edit"], ["showState", "Value", "heart"], ["showDetail", "Detail", "info"]],
};
const SPAN_WORDS: [number, string][] = [[3600, "1 h"], [21600, "6 h"], [86400, "24 h"], [604800, "7 d"]];

function shown(key: string): boolean {
  const v = settings[key];
  if (typeof v === "boolean") return v;
  return key === "showGraph" ? KIND !== "thermostat" : key !== "showScale";
}

function picture(src: string, cls: string, pic?: string): HTMLImageElement {
  const img = h("img", cls) as HTMLImageElement;
  img.src = src;
  img.alt = "";
  if (pic) img.dataset.pic = pic;
  return img;
}

function lookCard(): HTMLElement {
  const it = items.find((i) => i.id === settings.item);
  const card = h("div", "card look-card");
  const theme = String(settings.theme ?? "classic");
  card.append(h("h2", "", [ic("sparkle", "sm"), "Look", h("span", "count", [THEMES.find((t) => t.id === theme)?.name ?? "Classic"])]));
  // lit and unlit, side by side
  if (looks && looks.on && looks.off) {
    card.append(h("div", "pair", [
      h("figure", "", [picture(looks.on, "big", "on"), h("figcaption", "", [h("span", "dot ok"), looks.words[0]])]),
      h("figure", "", [picture(looks.off, "big", "off"), h("figcaption", "", [h("span", "dot"), looks.words[1]])]),
    ]));
  }
  // every look, drawn with the item as it is now
  const grid = h("div", "looks");
  for (const t of THEMES) {
    const pic = looks?.themes.find((x) => x.id === t.id)?.image;
    const b = h("button", "look" + (t.id === theme ? " sel" : ""), [pic ? picture(pic, "", "look:" + t.id) : h("div", "ph", [ic("hourglass", "sm")]), h("span", "", [t.name])]);
    b.type = "button";
    b.title = t.name + " - " + t.hint;
    b.addEventListener("click", () => saveSettings({ theme: t.id === "classic" ? undefined : t.id }));
    grid.append(b);
  }
  card.append(grid);
  // (1.3) the colours: On and Off, by name or the user's own
  card.append(colourSection(it));
  // the label
  const lab = h("input", "in") as HTMLInputElement;
  lab.placeholder = it?.name ?? "The item's name";
  lab.maxLength = 40;
  lab.dataset.key = "label";
  lab.value = String(settings.label ?? "");
  lab.addEventListener("change", () => saveSettings({ label: lab.value.trim() || undefined }));
  card.append(h("label", "f", ["Label on the key (empty = the item's name)"]), lab);
  const fitNow = String(settings.nameFit ?? (theme === "classic" ? "cut" : "fit"));
  card.append(...chips("Long names", [["fit", "Shrink to fit", "search"], ["wrap", "Two lines", "layers"], ["cut", "One line", "edit"]], fitNow, "nameFit"));
  // what is shown
  card.append(h("div", "sep"));
  card.append(h("h2", "", [ic("info", "sm"), "Shown on the key"]));
  const wrap = h("div", "chips");
  for (const [key, word, iconName] of INFO[KIND]) {
    const on = shown(key);
    const c = h("button", "chip tog" + (on ? " on" : ""), [ic(on ? "check" : iconName, "sm"), word]);
    c.type = "button";
    c.addEventListener("click", () => saveSettings({ [key]: !on }));
    wrap.append(c);
  }
  card.append(wrap);
  const keys = INFO[KIND].map((x) => x[0]);
  card.append(h("div", "btns", [
    btn("Everything", "ghost", "grid", () => saveSettings(Object.fromEntries(keys.map((k) => [k, k === "showGraph" && KIND === "thermostat" ? true : undefined])))),
    btn("Icon only", "ghost", "sparkle", () => saveSettings(Object.fromEntries(keys.map((k) => [k, k === "showIcon"])))),
  ]));
  if ((KIND === "reading" || KIND === "thermostat") && shown("showGraph")) {
    card.append(...chips("Graph over the last", SPAN_WORDS.map(([v, w]) => [String(v), w] as [string, string]), String(settings.span ?? 86400), "span"));
    card.append(toggle("Min / max on the graph", "showScale", false));
    if (KIND === "thermostat") card.append(toggle("The target as a dashed line", "showTarget", true));
    card.append(h("p", "muted small", ["ZIGMon sends the graph ready from its own history and the key adds the live values; it is fetched again every few minutes."]));
  }
  return card;
}

// ------------------------------------------------------------------ (1.3) the colours

type ColourTab = "on" | "off";
const COLOUR_KEY: Record<ColourTab, "accent" | "accentOff"> = { on: "accent", off: "accentOff" };
/** Which of the two colours is being chosen, and whether the picker of the user's own colour is open. */
let colourTab: ColourTab = "on";
let customOpen = false;
/** The own-colour picker's colour (its hue kept through greys), and the colour it was taken from. */
let hsv: Hsv = { h: 210, s: 0.62, v: 1 };
let hsvFrom = "";
/** A pointer is dragging in the picker: the page is not rebuilt meanwhile. */
let dragging = false;
let sendTimer: ReturnType<typeof setTimeout> | null = null;
let lastSend = 0;
const SEND_EVERY_MS = 120;
/** The named colours as the grid shows them: round the colour wheel, the quiet ones last. */
const SWATCH_ORDER = ["red", "coral", "orange", "peach", "amber", "gold", "yellow", "lime", "green", "mint", "teal", "cyan", "sky", "blue",
  "indigo", "lavender", "purple", "magenta", "pink", "rose", "brown", "slate", "silver", "white"];

/** Dragging, or working in the picker with the keys: the plugin's new pictures are patched in, the page left as it is. */
function picking(): boolean {
  const a = document.activeElement;
  return dragging || (a instanceof HTMLElement && a.closest(".picker") !== null);
}

function colourSetting(tab: ColourTab): string | undefined {
  const v = settings[COLOUR_KEY[tab]];
  return typeof v === "string" ? v : undefined;
}

/** The colour Auto stands for: the item's own when on, the look's grey when off. */
function autoColour(tab: ColourTab, it: PiItem | undefined): string {
  if (tab === "off") return P.muted;
  if (KIND === "dimmer") return P.warn;
  if (KIND === "thermostat") return P.orange;
  if (KIND === "blinds") return P.purple;
  if (KIND === "reading") return P.water;
  if (KIND === "status") return P.ok;
  return it ? itemColour(it) : P.info;
}

/** What a setting is called: Auto, a colour's name, or the hex of the user's own. */
function colourWords(v: string | undefined): [string, string] {
  if (!v) return ["Auto", ""];
  const named = Object.prototype.hasOwnProperty.call(ACCENTS, v) ? ACCENTS[v] : undefined;
  if (named) return [named.name, named.colour];
  const hex = cleanHex(v);
  return hex ? ["Custom", hex] : ["Auto", ""];
}

/** A colour chosen: saved at once (a click), the page drawn again. */
function chooseColour(tab: ColourTab, v: string | undefined): void {
  if (v !== undefined && !colourOf(v)) return; // never send what the plugin would drop
  if (sendTimer) {
    clearTimeout(sendTimer);
    sendTimer = null;
  }
  saveSettings({ [COLOUR_KEY[tab]]: v });
}

/** A colour being picked (dragged, typed, nudged): sent at most every SEND_EVERY_MS, the page patched in place. */
function pickLive(tab: ColourTab, hex: string, from: "sv" | "hue" | "hex"): void {
  const c = cleanHex(hex);
  if (!c) return;
  settings = { ...settings, [COLOUR_KEY[tab]]: c };
  hsvFrom = c;
  if (!sendTimer) {
    sendTimer = setTimeout(() => {
      sendTimer = null;
      lastSend = Date.now();
      sd({ event: "setSettings", context: ctx, payload: settings });
    }, Math.max(0, SEND_EVERY_MS - (Date.now() - lastSend)));
  }
  paintColour(tab, from);
}

/** Sends what is waiting now (the drag ended). */
function flushColour(): void {
  if (!sendTimer) return;
  clearTimeout(sendTimer);
  sendTimer = null;
  lastSend = Date.now();
  sd({ event: "setSettings", context: ctx, payload: settings });
}

/** The pictures the plugin sent, put into the page as it is (no rebuild). */
function patchPictures(): void {
  const set = (k: string, src: string | undefined) => {
    if (!src) return;
    const img = document.querySelector<HTMLImageElement>(`img[data-pic="${k}"]`);
    if (img && img.src !== src) img.src = src;
  };
  set("preview", preview);
  set("on", looks?.on);
  set("off", looks?.off);
  for (const t of looks?.themes ?? []) set("look:" + t.id, t.image);
}

/** Brings the chip, the tab's dot, the swatches and the picker up to date with the colour now set. */
function paintColour(tab: ColourTab, from?: "sv" | "hue" | "hex"): void {
  const root = document.querySelector<HTMLElement>(".colours");
  if (!root) return;
  const it = items.find((i) => i.id === settings.item);
  const v = colourSetting(tab);
  const [word, hex] = colourWords(v);
  const c = hex || autoColour(tab, it);
  root.querySelector<HTMLElement>(`.seg [data-tab="${tab}"] .cdot`)?.style.setProperty("--c", c);
  const chip = root.querySelector<HTMLElement>(".cchip");
  if (chip) {
    chip.style.setProperty("--c", c);
    chip.classList.toggle("auto", !v);
    const n = chip.querySelector(".cn"), x = chip.querySelector(".cx");
    if (n) n.textContent = word;
    if (x) x.textContent = v ? hex : tab === "on" ? "the item's own" : "the look's own";
  }
  const own = !!v && !!cleanHex(v);
  root.querySelectorAll<HTMLElement>(".sw").forEach((b) => {
    const sel = b.dataset.v === (v ?? "") || (b.dataset.v === "custom" && own);
    b.classList.toggle("sel", sel);
    b.setAttribute("aria-checked", String(sel));
  });
  const cust = root.querySelector<HTMLElement>(".sw.custom");
  if (cust) {
    cust.classList.toggle("set", own);
    if (own) cust.style.setProperty("--c", hex);
  }
  const pk = root.querySelector<HTMLElement>(".picker");
  if (!pk) return;
  pk.style.setProperty("--hue", String(Math.round(hsv.h)));
  pk.style.setProperty("--c", hsvToHex(hsv));
  const svk = pk.querySelector<HTMLElement>(".sv .knob"), huek = pk.querySelector<HTMLElement>(".hue .knob");
  if (svk) {
    svk.style.left = (hsv.s * 100).toFixed(2) + "%";
    svk.style.top = ((1 - hsv.v) * 100).toFixed(2) + "%";
  }
  if (huek) huek.style.left = ((hsv.h / 360) * 100).toFixed(2) + "%";
  const sv = pk.querySelector<HTMLElement>(".sv"), hue = pk.querySelector<HTMLElement>(".hue");
  sv?.setAttribute("aria-valuetext", `saturation ${Math.round(hsv.s * 100)} %, brightness ${Math.round(hsv.v * 100)} %`);
  hue?.setAttribute("aria-valuenow", String(Math.round(hsv.h)));
  const input = pk.querySelector<HTMLInputElement>("input.hex");
  if (input && from !== "hex") {
    input.value = hsvToHex(hsv);
    input.classList.remove("bad");
    pk.querySelector(".hexerr")?.classList.add("hidden");
  }
}

/** Takes the picker's colour from the one set (or shown) now, unless it is already that colour. */
function syncHsv(tab: ColourTab, it: PiItem | undefined): void {
  const c = colourOf(colourSetting(tab)) ?? autoColour(tab, it);
  if (c.toUpperCase() !== hsvFrom) {
    hsv = hexToHsv(c, hsv.h);
    hsvFrom = c.toUpperCase();
  }
}

/** Arrow keys move between the swatches as in a grid; Home / End to the first and the last. */
function swatchKeys(grid: HTMLElement, e: KeyboardEvent): void {
  const all = Array.from(grid.querySelectorAll<HTMLElement>(".sw"));
  const me = document.activeElement as HTMLElement;
  const i = all.indexOf(me);
  if (i < 0) return;
  let to = -1;
  if (e.key === "ArrowLeft") to = i - 1;
  else if (e.key === "ArrowRight") to = i + 1;
  else if (e.key === "Home") to = 0;
  else if (e.key === "End") to = all.length - 1;
  else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
    // the nearest swatch in the row above / below
    const mid = (b: HTMLElement) => b.offsetLeft + b.offsetWidth / 2;
    const rows = [...new Set(all.map((b) => b.offsetTop))].sort((a, b) => a - b);
    const r = rows.indexOf(me.offsetTop) + (e.key === "ArrowUp" ? -1 : 1);
    if (r < 0 || r >= rows.length) return;
    const row = all.filter((b) => b.offsetTop === rows[r]);
    const best = row.reduce((a, b) => (Math.abs(mid(b) - mid(me)) < Math.abs(mid(a) - mid(me)) ? b : a));
    to = all.indexOf(best);
  } else return;
  e.preventDefault();
  all[Math.max(0, Math.min(all.length - 1, to))]!.focus();
}

/** A pointer-driven area: calls `at` with the pointer's place in it (0..1 across, 0..1 down) while pressed. */
function dragArea(el: HTMLElement, at: (x: number, y: number) => void): void {
  const place = (e: PointerEvent) => {
    const r = el.getBoundingClientRect();
    at(Math.max(0, Math.min(1, (e.clientX - r.left) / Math.max(1, r.width))), Math.max(0, Math.min(1, (e.clientY - r.top) / Math.max(1, r.height))));
  };
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    el.focus();
    dragging = true;
    try {
      el.setPointerCapture(e.pointerId);
    } catch {
      /* not a real pointer (a test) */
    }
    place(e);
  });
  el.addEventListener("pointermove", (e) => {
    if (dragging) place(e);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    flushColour();
    patchPictures();
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("lostpointercapture", end);
}

/** The picker of the user's own colour: a saturation / brightness square, a hue bar and the hex, all live. */
function ownPicker(tab: ColourTab): HTMLElement {
  const sv = h("div", "sv", [h("div", "knob")]);
  sv.tabIndex = 0;
  sv.dataset.key = "sv-" + tab;
  sv.setAttribute("role", "slider");
  sv.setAttribute("aria-label", "Saturation (left to right) and brightness (bottom to top) - arrow keys");
  dragArea(sv, (x, y) => {
    hsv = { ...hsv, s: x, v: 1 - y };
    pickLive(tab, hsvToHex(hsv), "sv");
  });
  sv.addEventListener("keydown", (e) => {
    const d = e.shiftKey ? 0.1 : 0.02;
    const k: Record<string, [number, number]> = { ArrowLeft: [-d, 0], ArrowRight: [d, 0], ArrowUp: [0, d], ArrowDown: [0, -d] };
    const m = k[e.key];
    if (!m) return;
    e.preventDefault();
    hsv = { ...hsv, s: Math.max(0, Math.min(1, hsv.s + m[0])), v: Math.max(0, Math.min(1, hsv.v + m[1])) };
    pickLive(tab, hsvToHex(hsv), "sv");
  });
  const hue = h("div", "hue", [h("div", "knob")]);
  hue.tabIndex = 0;
  hue.dataset.key = "hue-" + tab;
  hue.setAttribute("role", "slider");
  hue.setAttribute("aria-label", "Hue");
  hue.setAttribute("aria-valuemin", "0");
  hue.setAttribute("aria-valuemax", "360");
  dragArea(hue, (x) => {
    hsv = { ...hsv, h: Math.min(359.9, x * 360) };
    pickLive(tab, hsvToHex(hsv), "hue");
  });
  hue.addEventListener("keydown", (e) => {
    const d = e.shiftKey ? 15 : 2;
    const m = e.key === "ArrowLeft" || e.key === "ArrowDown" ? -d : e.key === "ArrowRight" || e.key === "ArrowUp" ? d : 0;
    if (!m) return;
    e.preventDefault();
    hsv = { ...hsv, h: (hsv.h + m + 360) % 360 };
    pickLive(tab, hsvToHex(hsv), "hue");
  });
  const input = h("input", "in hex mono") as HTMLInputElement;
  input.dataset.key = "hex-" + tab;
  input.maxLength = 7;
  input.spellcheck = false;
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Colour as #RRGGBB");
  input.value = hsvToHex(hsv);
  const err = h("div", "hexerr err hidden", ["Six hex digits, like #3FB950"]);
  input.addEventListener("input", () => {
    const t = input.value.trim();
    const c = cleanHex(t.startsWith("#") ? t : "#" + t);
    // wrong as typed so far (a letter past F, too long), or complete and still not a colour
    const bad = !c && (!/^#?[0-9a-fA-F]{0,6}$/.test(t) || t.replace("#", "").length >= 6);
    input.classList.toggle("bad", bad);
    input.classList.toggle("good", !!c);
    err.classList.toggle("hidden", !bad);
    if (!c) return;
    hsv = hexToHsv(c, hsv.h);
    pickLive(tab, c, "hex");
  });
  input.addEventListener("change", () => {
    const t = input.value.trim();
    const c = cleanHex(t.startsWith("#") ? t : "#" + t);
    if (!c) {
      input.classList.add("bad");
      err.classList.remove("hidden");
      return;
    }
    input.value = c;
    flushColour();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") input.dispatchEvent(new Event("change"));
  });
  const done = btn("Done", "ghost", "check", () => {
    customOpen = false;
    flushColour();
    render();
  }, "done-" + tab);
  const p = h("div", "picker", [sv, hue, h("div", "hexrow", [h("span", "now"), input, done]), err]);
  return p;
}

function colourSection(it: PiItem | undefined): HTMLElement {
  const tab = colourTab;
  const v = colourSetting(tab);
  const wrap = h("div", "colours");
  // the two tabs, each with its colour now
  const seg = h("div", "seg");
  seg.setAttribute("role", "tablist");
  seg.setAttribute("aria-label", "Which colour");
  for (const [t, word] of [["on", "On colour"], ["off", "Off colour"]] as [ColourTab, string][]) {
    const cv = colourSetting(t);
    const b = h("button", t === tab ? "on" : "", [h("span", "cdot" + (cv ? "" : " auto")), word]);
    b.type = "button";
    b.dataset.tab = t;
    b.dataset.key = "tab-" + t;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(t === tab));
    (b.firstChild as HTMLElement).style.setProperty("--c", colourOf(cv) ?? autoColour(t, it));
    b.addEventListener("click", () => {
      if (colourTab === t) return;
      colourTab = t;
      customOpen = false;
      render();
    });
    b.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      colourTab = colourTab === "on" ? "off" : "on";
      customOpen = false;
      render();
    });
    seg.append(b);
  }
  wrap.append(h("div", "chead", [h("label", "f", ["Colours"]), seg]));
  // what is set now
  const [word, hex] = colourWords(v);
  const chip = h("div", "cchip" + (v ? "" : " auto"), [h("span", "sq"), h("span", "cn", [word]), h("span", "cx mono", [v ? hex : tab === "on" ? "the item's own" : "the look's own"])]);
  chip.style.setProperty("--c", hex || autoColour(tab, it));
  chip.setAttribute("aria-live", "polite");
  // Auto, the named colours, the user's own
  const grid = h("div", "sws");
  grid.setAttribute("role", "radiogroup");
  grid.setAttribute("aria-label", tab === "on" ? "On colour" : "Off colour");
  const own = !!v && !!cleanHex(v);
  const sw = (cls: string, val: string, title: string, colour: string | null, kids: (Node | string)[] = []) => {
    const sel = val === "custom" ? own : (v ?? "") === val;
    const b = h("button", "sw " + cls + (sel ? " sel" : ""), kids);
    b.type = "button";
    b.title = title;
    b.dataset.v = val;
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(sel));
    b.setAttribute("aria-label", title);
    if (colour) b.style.setProperty("--c", colour);
    return b;
  };
  const auto = sw("auto", "", tab === "on" ? "Auto - the item's own colour" : "Auto - the look's own off style", autoColour(tab, it), [h("span", "", ["Auto"])]);
  auto.addEventListener("click", () => {
    customOpen = false;
    chooseColour(tab, undefined);
  });
  grid.append(auto);
  for (const id of [...SWATCH_ORDER.filter((x) => x in ACCENTS), ...Object.keys(ACCENTS).filter((x) => !SWATCH_ORDER.includes(x))]) {
    const a = ACCENTS[id]!;
    const b = sw("", id, a.name, a.colour);
    b.addEventListener("click", () => {
      customOpen = false;
      chooseColour(tab, id);
    });
    grid.append(b);
  }
  const custom = sw("custom" + (own ? " set" : "") + (customOpen ? " open" : ""), "custom", own ? "Your own colour - " + hex : "Your own colour…", own ? hex : null, [ic("edit", "sm")]);
  custom.setAttribute("aria-expanded", String(customOpen));
  custom.addEventListener("click", () => {
    customOpen = !customOpen;
    if (customOpen) syncHsv(tab, it);
    render();
  });
  grid.append(custom);
  grid.addEventListener("keydown", (e) => swatchKeys(grid, e));
  const panel = h("div", "cpanel", [chip, grid]);
  panel.setAttribute("role", "tabpanel");
  if (customOpen) {
    syncHsv(tab, it);
    panel.append(ownPicker(tab));
  }
  const noOnOff = KIND === "reading" || KIND === "scene" || KIND === "status";
  panel.append(h("p", "muted small chint", [tab === "on"
    ? "Lit, on, heating, open: the key in this colour."
    : noOnOff
      ? "This item is not on or off: the On colour is its colour, the Off colour tints what is drawn grey while it is idle."
      : "Off: the border, icon and state in this colour, as each look draws them. Auto keeps the look's own grey."]));
  wrap.append(panel);
  queueMicrotask(() => paintColour(tab));
  return wrap;
}

/** Hold to confirm, per key - on and locked where ZIGMon asks for it. */
function holdSwitch(it: PiItem | undefined): HTMLElement {
  const forced = !!it?.hold;
  const on = forced || settings.hold === true;
  const s = h("div", "switch hold" + (on ? " on" : "") + (forced ? " locked" : ""), [
    h("span", "hl", [h("span", "hand", [ic("hand")]), h("span", "", [h("b", "", ["Hold to confirm (1.5 s)"]), h("span", "muted small", [forced
      ? "ZIGMon requires it for this item"
      : "A short press does nothing; keep it pressed while the ring fills"])])]),
    forced ? ic("lock", "sm") : h("span", "k"),
  ]);
  if (!forced) s.addEventListener("click", () => saveSettings({ hold: !on || undefined }));
  return s;
}

/** (1.2) "By hand", as ZIGMon's buttons have it: the rules leave alone what this key switched on. */
function byHandSwitch(): HTMLElement {
  const on = settings.byHand === true;
  const s = h("div", "switch hold byhand" + (on ? " on" : ""), [
    h("span", "hl", [h("span", "hand", [ic("person")]), h("span", "", [h("b", "", ["By hand"]), h("span", "muted small", [
      "Switched on from this key, rules and schedules leave it alone; switched off from it, they take over again"])])]),
    h("span", "k"),
  ]);
  s.addEventListener("click", () => saveSettings({ byHand: !on || undefined }));
  return s;
}

// ------------------------------------------------------------------ the page

function render(): void {
  const app = document.getElementById("app");
  if (!app) return;
  const a = document.activeElement as HTMLElement | null;
  const focusKey = a?.dataset?.key;
  const sel = a instanceof HTMLInputElement && a.type !== "number" ? [a.selectionStart, a.selectionEnd] : null;
  const scroll = document.getElementById("list")?.scrollTop ?? 0;
  const parts: (HTMLElement | null)[] = [updateCard(), connectionCard(), picker()];
  if (settings.item && !pickerOpen) parts.push(lookCard(), optionsCard());
  parts.push(h("div", "foot", [ic("zigmon"), "ZIGMon for Stream Deck " + (status?.plugin ?? "")]));
  app.replaceChildren(...parts.filter((p): p is HTMLElement => p !== null));
  if (focusKey) {
    const e = app.querySelector<HTMLElement>(`[data-key="${focusKey}"]`);
    if (e) {
      e.focus();
      if (sel && e instanceof HTMLInputElement) try { e.setSelectionRange(sel[0] ?? null, sel[1] ?? null); } catch { /* not a text field */ }
    }
  }
  queueMicrotask(() => {
    const l = document.getElementById("list");
    if (l) l.scrollTop = scroll;
  });
}

setInterval(() => {
  const t = document.querySelector<HTMLElement>(".timer");
  if (t && t.dataset.expires) t.replaceWith(timer(Number(t.dataset.expires)));
}, 1000);

render();
