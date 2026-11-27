/**
 * What every key and dial does and shows, without the Stream Deck SDK: an ActionView gets a
 * Surface (setImage / setFeedback / showAlert) and the Hub, and turns presses, turns and touches
 * into deck commands. src/actions/*.ts only wire SDK events to these; the tests drive them
 * with mock surfaces.
 */
import type { Command } from "./client.js";
import { boolAttr, decimalsOf, dialAttr, DialAccumulator, enumAttr, fraction } from "./dial.js";
import { HoldPress } from "./hold.js";
import type { CommandResult, Hub, HubView } from "./hub.js";
import type { LAYOUTS } from "./layouts.js";
import { P } from "./palette.js";
import type { Attr, Item, ItemAction, ItemState } from "./protocol.js";
import {
  lookFor, readingAccent, renderBlinds, renderControl, renderDimmer, renderHold, renderNotice, renderPair, renderReading, renderScene,
  renderStatus, renderThermostat, renderToast, type BlindsModel, type ControlModel, type DimmerModel, type NoticeModel, type ReadingModel,
  type StatusModel, type ThermoModel,
} from "./render.js";
import { normalizeAction, type ActionSettings } from "./settings.js";
import {
  blindsFeedback, controlFeedback, dimmerFeedback, holdArt, noticeFeedback, pairFeedback, readingFeedback, thermoFeedback, type Feedback,
} from "./strip.js";
import { dataUri } from "./svg.js";

export type ActionKind = "control" | "reading" | "thermostat" | "dimmer" | "blinds" | "scene" | "status";

export interface Surface {
  readonly controller: "Keypad" | "Encoder";
  readonly deckId: string;
  setImage(image: string): Promise<void> | void;
  setFeedback(fb: Feedback): Promise<void> | void;
  setTriggerDescription?(d: { push?: string; rotate?: string; touch?: string; longTouch?: string }): Promise<void> | void;
  showAlert(): Promise<void> | void;
  showOk?(): Promise<void> | void;
}

/** Which items fit which action, for the property inspector's picker. */
export function fits(kind: ActionKind, it: Pick<Item, "kind" | "cap" | "actions" | "attrs" | "state">): boolean {
  switch (kind) {
    case "control":
      return it.actions.length > 0 && it.kind !== "status";
    case "reading":
      return it.kind !== "status" && (it.state.value !== null || it.kind === "reading" || it.kind === "sensor" || it.attrs.some((a) => a.type === "number"));
    case "thermostat":
      return it.kind === "thermostat" || it.cap === "climate";
    case "dimmer":
      return it.kind === "dimmer" || it.kind === "light" || it.cap === "dim";
    case "blinds":
      return it.kind === "cover" || it.cap === "cover";
    case "scene":
      return it.actions.includes("run") || ["scene", "sequence", "group", "rule", "schedule", "message", "system"].includes(it.kind);
    case "status":
      return it.kind === "status" || it.cap === "status";
  }
}

const NOT_CHOSEN: Record<ActionKind, string> = {
  control: "Pick what it switches",
  reading: "Pick a reading",
  thermostat: "Pick a thermostat",
  dimmer: "Pick a light",
  blinds: "Pick the blinds",
  scene: "Pick a scene",
  status: "Pick what to watch",
};

const LAYOUT_OF: Record<ActionKind, keyof typeof LAYOUTS> = {
  control: "control", reading: "reading", thermostat: "thermostat", dimmer: "dimmer", blinds: "blinds", scene: "control", status: "control",
};

const STATUS_LOOK: Record<string, { label: string; icon: string; count: "crit" | "warn" | null }> = {
  "status:alerts": { label: "Alerts", icon: "bell", count: "crit" },
  "status:blocked": { label: "Blocked addresses", icon: "wall", count: "warn" },
  "status:proxy": { label: "Proxy", icon: "globe", count: null },
  "status:health": { label: "Health", icon: "heart", count: null },
  "status:gateway": { label: "Zigbee gateway", icon: "router", count: null },
};

export function formatNumber(v: number, decimals: number): string {
  return decimals >= 0 ? v.toFixed(decimals) : String(Math.round(v * 100) / 100);
}

export class ActionView implements HubView {
  settings: ActionSettings;
  private press: HoldPress | null = null;
  private toast: { title: string; line: string; tone: "warn" | "crit" | "ok"; until: number } | null = null;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;
  private holdProgress: number | null = null;
  private flash: "ok" | "fail" | null = null;
  private flashTimer: ReturnType<typeof setTimeout> | null = null;
  private dial: DialAccumulator;
  private lastImage = "";
  private lastFeedback = "";
  private disposed = false;

  constructor(
    readonly kind: ActionKind,
    private readonly hub: Hub,
    readonly surface: Surface,
    settings: unknown,
  ) {
    this.settings = normalizeAction(settings);
    this.dial = new DialAccumulator((delta) => this.sendDelta(delta));
    if (surface.controller === "Encoder") void surface.setTriggerDescription?.(this.triggers());
  }

  // ------------------------------------------------------------------ HubView

  ids(): string[] {
    return this.settings.item ? [this.settings.item] : [];
  }

  refresh(): void {
    if (this.disposed) return;
    this.draw();
  }

  setSettings(s: unknown): void {
    const before = this.settings.item;
    this.settings = normalizeAction(s);
    this.dial.cancel();
    if (before !== this.settings.item) this.hub.resubscribe();
    if (this.surface.controller === "Encoder") void this.surface.setTriggerDescription?.(this.triggers());
    this.draw(true);
  }

  dispose(): void {
    this.disposed = true;
    this.press?.cancel();
    this.dial.cancel();
    if (this.toastTimer) clearTimeout(this.toastTimer);
    if (this.flashTimer) clearTimeout(this.flashTimer);
  }

  // ------------------------------------------------------------------ the item

  private get item(): Item | undefined {
    return this.hub.item(this.settings.item);
  }

  private get st(): ItemState | undefined {
    return this.hub.state(this.settings.item);
  }

  private needsHold(it: Item | undefined): boolean {
    return !!it && it.hold;
  }

  // ------------------------------------------------------------------ drawing

  /** A notice instead of the item: not connected, pairing, switched off, not approved... */
  private notice(): NoticeModel | { pair: string } | null {
    const ph = this.hub.currentPhase;
    const code = this.hub.pairCode;
    if (code) return { pair: code };
    switch (ph) {
      case "setup":
      case "unpaired":
        return { icon: "zigmon", title: "Connect", lines: ["to ZIGMon in this", "key's settings"], tone: "info" };
      case "pairing":
        return { icon: "hourglass", title: "Pairing…", lines: ["asking ZIGMon"], tone: "info" };
      case "cert":
        return { icon: "shieldAlert", title: "Certificate", lines: ["check it in the", "key's settings"], tone: "warn" };
      case "off":
        return { icon: "lock", title: "Switched off", lines: ["allow it in ZIGMon", "Settings → Stream Deck"], tone: "warn" };
      case "revoked":
        return { icon: "unlink", title: "Disconnected", lines: ["pair again in the", "key's settings"], tone: "crit" };
      case "denied":
        return { icon: "close", title: "Denied", lines: ["ZIGMon refused", "this Stream Deck"], tone: "crit" };
      case "connecting":
        if (!this.item) return { icon: "refresh", title: "Connecting…", lines: [], tone: "muted" };
        break;
      case "offline":
        return { icon: "wifiOff", title: "ZIGMon offline", lines: ["reconnecting…"], tone: "crit" };
      case "online":
        break;
    }
    if (this.hub.deckIsApproved(this.surface.deckId) === false) {
      return { icon: "deck", title: "Approve deck", lines: ["in ZIGMon →", "Settings → Stream Deck"], tone: "warn" };
    }
    if (!this.settings.item) return { icon: "search", title: "Choose", lines: [NOT_CHOSEN[this.kind]], tone: "muted" };
    if (!this.item) return { icon: "search", title: "Not found", lines: ["ZIGMon does not", "show it to this deck"], tone: "muted" };
    return null;
  }

  draw(force = false): void {
    const n = this.notice();
    if (this.surface.controller === "Encoder") {
      const layout = LAYOUT_OF[this.kind];
      let fb: Feedback;
      if (n && "pair" in n) fb = pairFeedback(layout, n.pair);
      else if (n) fb = noticeFeedback(layout, n.title, n.lines.join(" "), n.tone === "ok" ? "info" : n.tone);
      else fb = this.feedback();
      if (this.toast && this.toast.until > Date.now()) {
        fb = { ...fb, value: { value: this.toast.title, color: this.toast.tone === "ok" ? P.ok : this.toast.tone === "warn" ? P.warn : P.crit } };
        if ("name" in fb) fb.name = { value: this.toast.line };
      }
      if (this.holdProgress !== null && "art" in fb && (layout === "control" || layout === "dimmer")) {
        fb.art = holdArt(176, 30, this.holdProgress, lookFor(this.item?.kind ?? "", "").accent);
        fb.value = { value: this.holdProgress >= 1 ? "Confirmed" : "Hold…", color: P.text };
      } else if (this.holdProgress !== null) {
        fb.value = { value: this.holdProgress >= 1 ? "Confirmed" : "Hold… " + Math.round(this.holdProgress * 100) + "%", color: P.text };
      }
      const key = JSON.stringify(fb);
      if (force || key !== this.lastFeedback) {
        this.lastFeedback = key;
        void this.surface.setFeedback(fb);
      }
      return;
    }
    let svg: string;
    if (n && "pair" in n) svg = renderPair(n.pair);
    else if (n) svg = renderNotice(n);
    else svg = this.keyImage();
    if (this.holdProgress !== null) svg = renderHold(svg, this.holdProgress, this.accent());
    else if (this.toast && this.toast.until > Date.now()) svg = renderToast(svg, this.toast.title, this.toast.line, this.toast.tone);
    const img = dataUri(svg);
    if (force || img !== this.lastImage) {
      this.lastImage = img;
      void this.surface.setImage(img);
    }
  }

  /** The key as it looks now, for the property inspector's preview (keys and dials alike). */
  previewImage(): string {
    const n = this.notice();
    return dataUri(n && "pair" in n ? renderPair(n.pair) : n ? renderNotice(n) : this.keyImage());
  }

  private accent(): string {
    const it = this.item;
    if (this.kind === "dimmer") return P.warn;
    if (this.kind === "thermostat") return P.orange;
    if (this.kind === "blinds") return P.purple;
    return it ? lookFor(it.kind, it.icon).accent : P.info;
  }

  private showRoom(): boolean {
    return this.settings.showRoom !== false;
  }

  controlModel(): ControlModel {
    const it = this.item!, st = this.st ?? it.state;
    return {
      name: it.name, room: it.room, showRoom: this.showRoom(), kind: it.kind, icon: it.icon,
      on: st.on, valueText: st.valueText, online: st.online, battery: st.battery, hold: it.hold, allowed: it.allowed,
    };
  }

  readingModel(): ReadingModel {
    const it = this.item!, st = this.st ?? it.state;
    const attr = it.attrs.find((a) => a.type === "number");
    const unit = attr?.unit ?? "";
    const look = readingAccent(attr?.key ?? it.id, unit || st.valueText);
    const v = st.value;
    const s = this.settings;
    let colour = look.accent;
    if (v !== null) {
      if ((s.critAbove !== undefined && s.critAbove !== null && v >= s.critAbove) || (s.critBelow !== undefined && s.critBelow !== null && v <= s.critBelow)) colour = P.crit;
      else if ((s.warnAbove !== undefined && s.warnAbove !== null && v >= s.warnAbove) || (s.warnBelow !== undefined && s.warnBelow !== null && v <= s.warnBelow)) colour = P.warn;
    }
    let value: string;
    if (v !== null && s.decimals !== undefined && s.decimals >= 0) value = formatNumber(v, s.decimals);
    else if (st.valueText) value = unit && st.valueText.endsWith(unit) ? st.valueText.slice(0, -unit.length).trim() : st.valueText;
    else value = v !== null ? formatNumber(v, -1) : st.on === true ? "On" : st.on === false ? "Off" : "";
    const showUnit = unit && !value.endsWith(unit) ? unit : "";
    const h = this.hub.history(it.id);
    let trend: ReadingModel["trend"] = null;
    if (h.length >= 3 && v !== null) {
      const ref = h[Math.max(0, h.length - 6)]!;
      const span = Math.max(...h) - Math.min(...h);
      const d = v - ref;
      trend = Math.abs(d) <= Math.max(1e-9, span * 0.08) ? "flat" : d > 0 ? "up" : "down";
    }
    return {
      label: s.label || it.name, value, unit: showUnit, colour, accent: look.accent, icon: look.icon, trend, history: h, online: st.online,
    };
  }

  private setpointAttr(): Attr | null {
    return dialAttr(this.item, "thermostat");
  }

  thermoModel(): ThermoModel {
    const it = this.item!, st = this.st ?? it.state;
    const sp = this.setpointAttr();
    const target = sp ? numOf(st.attrs[sp.key]) : null;
    const curKey = Object.keys(st.attrs).find((k) => /local_temp|current_temp|^temperature$/i.test(k));
    const current = st.value ?? (curKey ? numOf(st.attrs[curKey]) : null);
    const mode = enumAttr(it, /mode/i), preset = enumAttr(it, /preset/i);
    const run = Object.entries(st.attrs).find(([k]) => /running|heating|demand|valve/i.test(k));
    const heating = run ? run[1] === true || run[1] === "heat" || run[1] === "heating" || (typeof run[1] === "number" && run[1] > 0) : st.on === true;
    const modeText = [mode ? strOf(st.attrs[mode.key]) : "", preset ? strOf(st.attrs[preset.key]) : ""].filter(Boolean).join(" · ");
    return {
      name: it.name, current, target, unit: sp?.unit || "°C", mode: modeText, heating: heating && st.online,
      min: sp?.min ?? 5, max: sp?.max ?? 30, online: st.online, hold: it.hold, allowed: it.allowed,
    };
  }

  private brightnessAttr(): Attr | null {
    return dialAttr(this.item, "dimmer");
  }

  dimmerModel(): DimmerModel {
    const it = this.item!, st = this.st ?? it.state;
    const b = this.brightnessAttr();
    const shown = this.dial.shown;
    const raw = shown ?? (b ? numOf(st.attrs[b.key]) : null);
    const f = raw === null || !b ? (st.on === true ? 1 : st.on === false ? 0 : null) : fraction(raw, b.min ?? 0, b.max ?? 100);
    const pct = f === null ? "" : Math.round(f * 100) + "%";
    return {
      name: it.name, room: it.room, showRoom: this.showRoom(), on: shown !== null ? shown > (b?.min ?? 0) : st.on, level: f,
      levelText: st.on === false && shown === null ? "Off" : pct, online: st.online, hold: it.hold, allowed: it.allowed,
    };
  }

  private positionAttr(): Attr | null {
    return dialAttr(this.item, "blinds");
  }

  blindsModel(): BlindsModel {
    const it = this.item!, st = this.st ?? it.state;
    const p = this.positionAttr();
    const shown = this.dial.shown;
    let pos = shown ?? (p ? numOf(st.attrs[p.key]) : null);
    if (pos !== null && p) pos = fraction(pos, p.min ?? 0, p.max ?? 100) * 100;
    if (pos === null && st.value !== null) pos = Math.max(0, Math.min(100, st.value));
    if (pos === null && st.on !== null) pos = st.on ? 100 : 0;
    const mv = Object.entries(st.attrs).find(([k]) => /moving|motor|running|state/i.test(k))?.[1];
    const moving = mv === "opening" || mv === "up" ? "up" : mv === "closing" || mv === "down" ? "down" : null;
    return { name: it.name, room: it.room, showRoom: this.showRoom(), position: pos, moving, online: st.online, hold: it.hold, allowed: it.allowed };
  }

  statusModel(): StatusModel {
    const it = this.item!, st = this.st ?? it.state;
    const look = STATUS_LOOK[it.id] ?? { label: it.name, icon: "heart", count: null };
    let level: StatusModel["level"] = "unknown";
    let value = st.valueText || (st.value !== null ? String(st.value) : st.on === true ? "OK" : st.on === false ? "Down" : "—");
    let detail = "";
    if (look.count) {
      const c = st.value ?? 0;
      level = c > 0 ? look.count : "ok";
      value = String(Math.round(c));
      detail = c > 0 ? (st.valueText || (look.count === "crit" ? "need attention" : "blocked now")) : look.count === "crit" ? "All clear" : "Nothing blocked";
      if (detail === value) detail = look.count === "crit" ? "need attention" : "blocked now";
    } else {
      level = !st.online || st.on === false ? "crit" : st.on === true ? "ok" : "unknown";
      if (st.valueText && st.valueText.length > 8) {
        detail = st.valueText;
        value = level === "ok" ? "OK" : level === "crit" ? "Down" : "—";
      } else detail = level === "ok" ? "running" : level === "crit" ? "needs a look" : "";
    }
    return { label: it.id in STATUS_LOOK ? look.label : it.name, value, detail, level, icon: look.icon };
  }

  private keyImage(): string {
    switch (this.kind) {
      case "control":
        return renderControl(this.controlModel());
      case "reading":
        return renderReading(this.readingModel());
      case "thermostat":
        return renderThermostat(this.thermoModel());
      case "dimmer":
        return renderDimmer(this.dimmerModel());
      case "blinds":
        return renderBlinds(this.blindsModel());
      case "scene": {
        const it = this.item!;
        return renderScene({ name: it.name, room: it.room, kind: it.kind, icon: it.icon, flash: this.flash, hold: it.hold, allowed: it.allowed });
      }
      case "status":
        return renderStatus(this.statusModel());
    }
  }

  private feedback(): Feedback {
    switch (this.kind) {
      case "control": {
        const m = this.controlModel();
        const a = dialAttr(this.item, "control");
        const st = this.st;
        const raw = this.dial.shown ?? (a && st ? numOf(st.attrs[a.key]) : null);
        const f = a && raw !== null ? fraction(raw, a.min, a.max) : null;
        const txt = a && raw !== null ? formatNumber(raw, decimalsOf(a.step ?? 1)) + (a.unit ? " " + a.unit : "") : "";
        return controlFeedback(m, f, txt);
      }
      case "reading":
        return readingFeedback(this.readingModel());
      case "thermostat": {
        const m = this.thermoModel();
        if (this.dial.shown !== null) m.target = this.dial.shown;
        return thermoFeedback(m);
      }
      case "dimmer":
        return dimmerFeedback(this.dimmerModel());
      case "blinds":
        return blindsFeedback(this.blindsModel());
      case "scene": {
        const it = this.item!;
        const fb = controlFeedback({ ...this.controlModel(), on: null, valueText: this.flash === "ok" ? "Done" : this.flash === "fail" ? "Failed" : "Push to run" }, null, "");
        fb.value = { value: this.flash === "ok" ? "Done ✓" : this.flash === "fail" ? "Failed" : it.name, color: this.flash === "ok" ? P.ok : this.flash === "fail" ? P.crit : P.text };
        fb.name = { value: it.room ?? "Scene" };
        return fb;
      }
      case "status": {
        const m = this.statusModel();
        const c = m.level === "ok" ? P.ok : m.level === "warn" ? P.warn : m.level === "crit" ? P.crit : P.dim;
        const fb = controlFeedback({ ...this.controlModel(), kind: "status", icon: m.icon, on: m.level === "ok" || m.level === "crit" || m.level === "warn", valueText: m.detail }, null, m.value);
        fb.value = { value: m.value + (m.detail ? "  " + m.detail : ""), color: c };
        fb.name = { value: m.label };
        return fb;
      }
    }
  }

  private triggers(): { push?: string; rotate?: string; touch?: string; longTouch?: string } {
    switch (this.kind) {
      case "control":
        return { push: pressWord(this.pressAction()), rotate: "Adjust", touch: pressWord(this.pressAction()) };
      case "reading":
        return { push: "Refresh", touch: "Refresh" };
      case "thermostat":
        return { push: "Mode / preset", rotate: "Setpoint", touch: "Boost" };
      case "dimmer":
        return { push: "On / off", rotate: "Brightness", touch: "On / off" };
      case "blinds":
        return { push: "Stop / open / close", rotate: "Position", touch: "Stop" };
      case "scene":
        return { push: "Run", touch: "Run" };
      case "status":
        return { push: "Refresh", touch: "Refresh" };
    }
  }

  // ------------------------------------------------------------------ feedback after a press

  private showToast(title: string, line: string, tone: "warn" | "crit" | "ok", ms = 1800): void {
    this.toast = { title, line, tone, until: Date.now() + ms };
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      this.toast = null;
      this.draw();
    }, ms);
    this.draw();
  }

  private flashScene(f: "ok" | "fail"): void {
    this.flash = f;
    if (this.flashTimer) clearTimeout(this.flashTimer);
    this.flashTimer = setTimeout(() => {
      this.flash = null;
      this.draw();
    }, 1500);
    this.draw();
  }

  private async run(cmd: Omit<Command, "deck">): Promise<CommandResult> {
    const r = await this.hub.command({ deck: this.surface.deckId, ...cmd });
    if (r.ok) {
      if (this.kind === "scene") this.flashScene("ok");
      return r;
    }
    if (this.kind === "scene") this.flashScene("fail");
    void this.surface.showAlert();
    const words: Record<string, [string, string, "warn" | "crit"]> = {
      hold: ["Hold to confirm", "press and hold 1.5 s", "warn"],
      deck: ["Approve this deck", "in ZIGMon first", "warn"],
      denied: ["Not allowed", "grant it in ZIGMon", "crit"],
      off: ["Switched off", "in ZIGMon", "warn"],
      revoked: ["Disconnected", "pair again", "crit"],
      invalid: ["Refused", r.message, "crit"],
      rate: ["Too fast", "wait a moment", "warn"],
      net: ["No answer", r.message, "crit"],
      offline: ["Not connected", "", "crit"],
    };
    const w = words[r.why] ?? ["Failed", r.message, "crit"];
    this.showToast(w[0], w[1], w[2]);
    return r;
  }

  /** Only allowed items do anything; the rest explain why (no request is made). */
  private guard(): Item | null {
    if (this.notice()) {
      void this.surface.showAlert();
      return null;
    }
    const it = this.item!;
    if (!it.allowed) {
      void this.surface.showAlert();
      this.showToast("Not allowed", "grant it in ZIGMon", "crit");
      return null;
    }
    return it;
  }

  /** A press of the key or the dial: what it does, through the hold ring when ZIGMon asks for it. */
  private pressStart(what: () => Omit<Command, "deck"> | null): void {
    if (this.kind === "reading" || this.kind === "status") {
      this.hub.resubscribe();
      if (this.hub.currentPhase !== "online") this.hub.retryNow();
      void this.surface.showOk?.();
      return;
    }
    const it = this.guard();
    if (!it) return;
    const cmd = what();
    if (!cmd) {
      this.showToast("Nothing to do", "this item has no such action", "warn");
      return;
    }
    this.press?.cancel();
    this.press = new HoldPress(this.needsHold(it), {
      progress: (p) => {
        this.holdProgress = p;
        this.draw();
      },
      fire: (held) => {
        setTimeout(() => {
          this.holdProgress = null;
          this.draw();
        }, held === undefined ? 0 : 350);
        void this.run(held === undefined ? cmd : { ...cmd, held_ms: Math.round(held) });
      },
      tooShort: () => {
        this.holdProgress = null;
        this.showToast("Hold to confirm", "keep it pressed 1.5 s", "warn");
      },
    });
    this.press.down();
  }

  private pressEnd(): void {
    this.press?.up();
  }

  private pressAction(): ItemAction | null {
    const it = this.item;
    const want = this.settings.press;
    if (!it) return (want as ItemAction) ?? "toggle";
    if (want && it.actions.includes(want as ItemAction)) return want as ItemAction;
    for (const a of ["toggle", "run", "on"] as const) if (it.actions.includes(a)) return a;
    return it.actions[0] ?? null;
  }

  private keyCommand(): Omit<Command, "deck"> | null {
    const it = this.item;
    if (!it) return null;
    switch (this.kind) {
      case "control": {
        const a = this.pressAction();
        return a && a !== "set" && a !== "step" ? { id: it.id, action: a } : null;
      }
      case "scene":
        return it.actions.includes("run") ? { id: it.id, action: "run" } : it.actions.includes("on") ? { id: it.id, action: "on" } : null;
      case "dimmer":
        return { id: it.id, action: it.actions.includes("toggle") ? "toggle" : (this.st?.on ? "off" : "on") };
      case "blinds":
        return this.blindsPush();
      case "thermostat":
        return this.thermoPush(this.settings.press ?? "mode");
      default:
        return null;
    }
  }

  private blindsPush(): Omit<Command, "deck"> | null {
    const it = this.item!;
    const want = this.settings.press ?? "openclose";
    if (want === "stop" || want === "open" || want === "close") return it.actions.includes(want) ? { id: it.id, action: want } : null;
    const m = this.blindsModel();
    if (m.moving && it.actions.includes("stop")) return { id: it.id, action: "stop" };
    const a: ItemAction = m.position !== null && m.position >= 50 ? "close" : "open";
    return it.actions.includes(a) ? { id: it.id, action: a } : it.actions.includes("toggle") ? { id: it.id, action: "toggle" } : null;
  }

  private thermoPush(what: string): Omit<Command, "deck"> | null {
    const it = this.item!;
    const st = this.st ?? it.state;
    if (what === "boost") {
      const b = boolAttr(it, /boost/i);
      if (b) return { id: it.id, action: "set", attr: b.key, value: st.attrs[b.key] !== true };
      const pr = enumAttr(it, /preset/i);
      if (pr && pr.values.includes("boost")) return { id: it.id, action: "set", attr: pr.key, value: "boost" };
      return null;
    }
    const e = what === "preset" ? enumAttr(it, /preset/i) ?? enumAttr(it, /mode/i) : enumAttr(it, /mode/i) ?? enumAttr(it, /preset/i);
    if (!e) return it.actions.includes("toggle") ? { id: it.id, action: "toggle" } : null;
    const cur = strOf(st.attrs[e.key]);
    const i = e.values.indexOf(cur);
    return { id: it.id, action: "set", attr: e.key, value: e.values[(i + 1) % e.values.length]! };
  }

  // ------------------------------------------------------------------ SDK events

  keyDown(): void {
    this.pressStart(() => this.keyCommand());
  }

  keyUp(): void {
    this.pressEnd();
  }

  dialDown(): void {
    this.pressStart(() => this.keyCommand());
  }

  dialUp(): void {
    this.pressEnd();
  }

  touch(_long: boolean): void {
    const it = this.item;
    if (this.kind === "thermostat" && it) {
      if (!this.guard()) return;
      const cmd = this.thermoPush("boost");
      if (!cmd) return this.showToast("No boost", "this thermostat has none", "warn");
      if (it.hold) return this.showToast("Hold the dial", "to confirm", "warn");
      void this.run(cmd);
      return;
    }
    if (this.kind === "blinds" && it) {
      if (!this.guard()) return;
      if (it.hold) return this.showToast("Hold the dial", "to confirm", "warn");
      if (it.actions.includes("stop")) void this.run({ id: it.id, action: "stop" });
      return;
    }
    // elsewhere a touch is a quick press (a hold needs the dial itself held down)
    if (it && it.hold && this.kind !== "reading" && this.kind !== "status") return this.showToast("Hold the dial", "to confirm", "warn");
    this.pressStart(() => this.keyCommand());
    this.pressEnd();
  }

  /** One turn of the dial: the value moves at once; ZIGMon gets the sum as a `delta`. */
  rotate(ticks: number): void {
    if (this.kind === "reading" || this.kind === "status" || this.kind === "scene") return;
    const it = this.guard();
    if (!it) return;
    if (it.hold) {
      this.showToast("Hold to confirm", "use the key / push", "warn");
      return;
    }
    const purpose = this.kind === "control" ? "control" : this.kind;
    const a = dialAttr(it, purpose);
    if (!a || !(it.actions.includes("set") || it.actions.includes("step"))) {
      this.showToast("Cannot adjust", "nothing to turn here", "warn");
      return;
    }
    const st = this.st ?? it.state;
    const current = numOf(st.attrs[a.key]) ?? a.min ?? 0;
    this.dial.turn(ticks, current, this.stepFor(a), a);
    this.draw();
  }

  stepFor(a: Attr): number {
    if (this.settings.step) return this.settings.step;
    if (this.kind === "thermostat") return a.step ?? 0.5;
    if (this.kind === "dimmer") return Math.max(a.step ?? 1, ((a.max ?? 100) - (a.min ?? 0)) / 20);
    if (this.kind === "blinds") return Math.max(a.step ?? 1, ((a.max ?? 100) - (a.min ?? 0)) / 10);
    const range = (a.max ?? 100) - (a.min ?? 0);
    return a.step ?? (range >= 50 ? 5 : 1);
  }

  private async sendDelta(delta: number): Promise<void> {
    const it = this.item;
    if (!it) return;
    const purpose = this.kind === "control" ? "control" : this.kind;
    const a = dialAttr(it, purpose);
    if (!a) return;
    const action: ItemAction = it.actions.includes("set") ? "set" : "step";
    await this.run({ id: it.id, action, attr: a.key, delta });
    this.draw();
  }
}

function pressWord(a: ItemAction | null): string {
  const w: Record<string, string> = { toggle: "Toggle", on: "On", off: "Off", run: "Run", open: "Open", close: "Close", stop: "Stop" };
  return a ? w[a] ?? a : "";
}

function numOf(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function strOf(v: unknown): string {
  return typeof v === "string" ? v : typeof v === "number" || typeof v === "boolean" ? String(v) : "";
}
