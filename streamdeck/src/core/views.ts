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
import { LAYOUTS } from "./layouts.js";
import { ACCENTS, P, X } from "./palette.js";
import type { Attr, Item, ItemAction, ItemState } from "./protocol.js";
import {
  fmtTemp, lookFor, readingAccent, renderBlinds, renderControl, renderDimmer, renderHold, renderNotice, renderPair, renderReading, renderScene,
  renderStatus, renderThermostat, renderToast, type BlindsModel, type ClassicOpts, type ControlModel, type DimmerModel, type NoticeModel, type ReadingModel,
  type StatusModel, type ThermoModel,
} from "./render.js";
import { normalizeAction, ROOM_MODES, type ActionSettings } from "./settings.js";
import { ALL_INFO, renderDetails, renderLook, THEMES, type Face, type Info } from "./themes.js";
import type { NameFit } from "./svg.js";
import {
  blindsFeedback, controlFeedback, iconPix, pillArt, dimmerFeedback, holdArt, noticeFeedback, pairFeedback, readingFeedback, thermoFeedback, type Feedback,
} from "./strip.js";
import { dataUri, svgDoc } from "./svg.js";

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

/** The modes of a heated room as the dashboard words them. */
export const MODE_WORDS: Record<string, string> = {
  plan: "Plan", comfort: "Comfort", eco: "Eco", night: "Night", max: "Max", off: "Off", manual: "By hand",
};

/** How long a press that shows a thermostat's details keeps them on the key. */
export const DETAILS_MS = 3000;

/** The actions that do something - the hold switch is theirs; Reading and ZIGMon status only look. */
export function acts(kind: ActionKind): boolean {
  return kind !== "reading" && kind !== "status";
}

/** "14:30" for a unix time, on this computer's clock. */
export function clockOf(unix: number): string {
  const d = new Date(unix * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

export function formatNumber(v: number, decimals: number): string {
  return decimals >= 0 ? v.toFixed(decimals) : String(Math.round(v * 100) / 100);
}

/** (1.2) How long after the last "Next mode" press the mode it reached is sent. */
export const CYCLE_SETTLE_MS = 1200;

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
  /** (1.1) The details card a press shows on a thermostat, until then. */
  private detailsUntil = 0;
  private detailsTimer: ReturnType<typeof setTimeout> | null = null;
  /** The previews draw the key as another look, or lit / unlit. */
  private themeOverride: string | null = null;
  private forced: "on" | "off" | null = null;
  /** A look other than Classic was drawn on this dial's strip: Classic must put its colours back. */
  private styledStrip = false;
  /** (1.2) "Next mode" pressed round: the mode stepped to so far, shown at once and sent only once
   * the presses stop - going round to Max no longer switches the room through Off on the way. */
  private cycle: { attr: string; value: string; id: string } | null = null;
  private cycleTimer: ReturnType<typeof setTimeout> | null = null;

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
    // a new item, or a graph of another span: the hub asks again (it only restarts the wait for a new item)
    if (before !== this.settings.item || this.series().length) this.hub.resubscribe();
    if (this.surface.controller === "Encoder") void this.surface.setTriggerDescription?.(this.triggers());
    this.draw(true);
  }

  dispose(): void {
    this.disposed = true;
    this.press?.cancel();
    this.dial.cancel();
    if (this.toastTimer) clearTimeout(this.toastTimer);
    if (this.flashTimer) clearTimeout(this.flashTimer);
    if (this.detailsTimer) clearTimeout(this.detailsTimer);
    if (this.cycleTimer) clearTimeout(this.cycleTimer);
    this.cycle = null;
  }

  /** (1.1) The series this key draws, for the hub to ask ZIGMon for. */
  series(): { id: string; span: number }[] {
    const id = this.settings.item;
    if (!id || (this.kind !== "reading" && this.kind !== "thermostat")) return [];
    return this.info().graph ? [{ id, span: this.span() }] : [];
  }

  span(): number {
    return this.settings.span ?? 86400;
  }

  // ------------------------------------------------------------------ the item

  private get item(): Item | undefined {
    return this.hub.item(this.settings.item);
  }

  private get st(): ItemState | undefined {
    const st = this.hub.state(this.settings.item);
    const c = this.cycle;
    if (!st || !c || c.id !== this.settings.item) return st;
    // the mode stepped to, until it is sent and ZIGMon says where the room is
    return { ...st, attrs: { ...st.attrs, [c.attr]: c.value, by_hand: false } };
  }

  /** Hold to confirm: when ZIGMon asks for it, or when this key's own switch says so. */
  needsHold(it: Item | undefined): boolean {
    return !!it && (it.hold || (this.settings.hold === true && acts(this.kind)));
  }

  // ------------------------------------------------------------------ the look

  get theme(): string {
    return this.themeOverride ?? this.settings.theme ?? "classic";
  }

  /** What this key shows (each choice on unless switched off; a thermostat's graph off unless switched on). */
  info(): Info {
    const s = this.settings;
    return {
      icon: s.showIcon ?? true, name: s.showName ?? true, room: s.showRoom ?? true, state: s.showState ?? true, detail: s.showDetail ?? true,
      mode: s.showMode ?? true, graph: s.showGraph ?? this.kind !== "thermostat", battery: s.showBattery ?? true,
      scale: s.showScale ?? false, target: s.showTarget ?? ALL_INFO.target,
    };
  }

  /** Nothing chosen beyond 1.0's settings: Classic draws exactly as 1.0 did. */
  private plain(): boolean {
    const s = this.settings;
    if (this.theme !== "classic" || s.accent || s.nameFit || s.span) return false;
    for (const k of ["showIcon", "showName", "showState", "showDetail", "showMode", "showGraph", "showBattery", "showScale", "showTarget"]) if (s[k] !== undefined) return false;
    return !(s.label && this.kind !== "reading");
  }

  private classicOpts(): ClassicOpts {
    if (this.plain()) return {};
    return { info: this.info(), accent: this.accentOverride(), fit: (this.settings.nameFit as NameFit | undefined) ?? "cut" };
  }

  private accentOverride(): string | undefined {
    return this.settings.accent ? ACCENTS[this.settings.accent]?.colour : undefined;
  }

  private nameFit(): NameFit {
    return (this.settings.nameFit as NameFit | undefined) ?? (this.theme === "classic" ? "cut" : "fit");
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
      if (!n) fb = this.styleStrip(fb, layout);
      else if (this.styledStrip) fb = this.unstyleStrip(fb, layout);
      if (!n && this.detailsUntil > Date.now() && this.kind === "thermostat") {
        const d = this.detailRows();
        fb = { ...fb, value: { value: d[0]![1], color: P.text } };
        if ("name" in fb) fb.name = { value: d.slice(1, 3).map((r) => r[1]).filter((v) => v && v !== "—").join(" · ") };
      }
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
    if (!n && this.detailsUntil > Date.now() && this.kind === "thermostat") svg = renderDetails(this.item?.name ?? "", this.detailRows(), this.accent());
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

  /**
   * (1.1) The property inspector's Look section: this key drawn now in every look, and lit and
   * unlit in its own - all from the item's real state, by the same code that draws the key.
   */
  previewSet(): { themes: { id: string; name: string; image: string }[]; on: string; off: string; words: [string, string] } | null {
    if (this.notice()) return null;
    const keep = [this.themeOverride, this.forced] as const;
    try {
      const themes = THEMES.map((t) => {
        this.themeOverride = t.id;
        return { id: t.id, name: t.name, image: dataUri(this.keyImage()) };
      });
      this.themeOverride = keep[0];
      this.forced = "on";
      const on = dataUri(this.keyImage());
      this.forced = "off";
      const off = dataUri(this.keyImage());
      return { themes, on, off, words: ON_OFF_WORDS[this.kind] };
    } finally {
      this.themeOverride = keep[0];
      this.forced = keep[1];
    }
  }

  private accent(): string {
    const it = this.item;
    const o = this.accentOverride();
    if (o) return o;
    if (this.kind === "dimmer") return P.warn;
    if (this.kind === "thermostat") return P.orange;
    if (this.kind === "blinds") return P.purple;
    return it ? lookFor(it.kind, it.icon).accent : P.info;
  }

  private showRoom(): boolean {
    return this.settings.showRoom !== false;
  }

  private label(it: Item): string {
    return this.settings.label || it.name;
  }

  controlModel(): ControlModel {
    const it = this.item!, st = this.st ?? it.state;
    const m: ControlModel = {
      name: this.label(it), room: it.room, showRoom: this.showRoom(), kind: it.kind, icon: it.icon,
      on: st.on, valueText: st.valueText, online: st.online, battery: st.battery, hold: this.needsHold(it), allowed: it.allowed,
      taken: st.held === true,
    };
    if (this.forced) {
      m.on = this.forced === "on";
      m.online = true;
    }
    return m;
  }

  readingModel(): ReadingModel {
    const it = this.item!, st = this.st ?? it.state;
    const attr = it.attrs.find((a) => a.type === "number");
    const unit = attr?.unit ?? "";
    const look = readingAccent(attr?.key ?? it.id, unit || st.valueText);
    const v = st.value;
    const s = this.settings;
    look.accent = this.accentOverride() ?? look.accent;
    let colour = look.accent;
    if (this.forced) colour = this.forced === "on" ? P.crit : look.accent;
    else if (v !== null) {
      if ((s.critAbove !== undefined && s.critAbove !== null && v >= s.critAbove) || (s.critBelow !== undefined && s.critBelow !== null && v <= s.critBelow)) colour = P.crit;
      else if ((s.warnAbove !== undefined && s.warnAbove !== null && v >= s.warnAbove) || (s.warnBelow !== undefined && s.warnBelow !== null && v <= s.warnBelow)) colour = P.warn;
    }
    let value: string;
    if (v !== null && s.decimals !== undefined && s.decimals >= 0) value = formatNumber(v, s.decimals);
    else if (st.valueText) value = unit && st.valueText.endsWith(unit) ? st.valueText.slice(0, -unit.length).trim() : st.valueText;
    else value = v !== null ? formatNumber(v, -1) : st.on === true ? "On" : st.on === false ? "Off" : "";
    const showUnit = unit && !value.endsWith(unit) ? unit : "";
    const h = this.historyOf(it.id);
    let trend: ReadingModel["trend"] = null;
    if (h.length >= 3 && v !== null) {
      const ref = h[Math.max(0, h.length - 6)]!;
      const span = Math.max(...h) - Math.min(...h);
      const d = v - ref;
      trend = Math.abs(d) <= Math.max(1e-9, span * 0.08) ? "flat" : d > 0 ? "up" : "down";
    }
    return {
      label: s.label || it.name, value, unit: showUnit, colour, accent: look.accent, icon: look.icon, trend, history: h, online: this.forced ? true : st.online,
    };
  }

  /** The values to draw: the series ZIGMon sent (with live values since), else the few this plugin saw. */
  private historyOf(id: string): number[] {
    const hub = this.hub as Hub & { series?: Hub["series"] };
    const se = typeof hub.series === "function" ? hub.series(id, this.span()) : null;
    return se && se.length >= 2 ? se : this.hub.history(id);
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
    let modeText = [mode ? strOf(st.attrs[mode.key]) : "", preset ? strOf(st.attrs[preset.key]) : ""].filter(Boolean).join(" · ");
    const room = this.isRoom();
    if (room) modeText = this.roomModeWord();
    const m: ThermoModel = {
      name: this.label(it), current, target, unit: sp?.unit || "°C", mode: modeText, heating: heating && st.online,
      min: sp?.min ?? 5, max: sp?.max ?? 30, online: st.online, hold: this.needsHold(it), allowed: it.allowed,
    };
    if (room) m.modeFirst = true;
    if (this.info().graph) m.history = this.historyOf(it.id);
    const src = st.attrs.thermometer;
    if (typeof src === "string" && src) m.source = src;
    if (this.forced) {
      m.heating = this.forced === "on";
      m.online = true;
    }
    return m;
  }

  /** A heated room of ZIGMon's (heat:room / heat:temp), which says why it holds what it holds. */
  private isRoom(): boolean {
    const st = this.st;
    return !!st && typeof st.attrs.why === "string" && typeof st.attrs.mode === "string";
  }

  /** Comfort, Eco, Plan... and "By hand until 14:30" while a hand-set temperature holds. */
  private roomModeWord(): string {
    const a = this.st?.attrs ?? {};
    if (a.by_hand === true) return typeof a.hold_until === "number" && a.hold_until > 0 ? "By hand until " + clockOf(a.hold_until) : "By hand";
    const m = strOf(a.mode);
    return MODE_WORDS[m] ?? m;
  }

  /** The details card: mode, target, what it measures, and where. */
  detailRows(): [string, string][] {
    const m = this.thermoModel();
    const u = m.unit ? " " + m.unit : "";
    return [
      ["Mode", m.mode || "—"],
      ["Target", m.target !== null ? fmtTemp(m.target) + u : "—"],
      ["Measured", m.current !== null ? fmtTemp(m.current) + u : "—"],
      ["Thermometer", m.source ?? ""],
    ];
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
    const m: DimmerModel = {
      name: this.label(it), room: it.room, showRoom: this.showRoom(), on: shown !== null ? shown > (b?.min ?? 0) : st.on, level: f,
      levelText: st.on === false && shown === null ? "Off" : pct, online: st.online, hold: this.needsHold(it), allowed: it.allowed,
    };
    if (this.forced === "on") Object.assign(m, { on: true, online: true, level: f && f > 0 ? f : 0.8, levelText: Math.round((f && f > 0 ? f : 0.8) * 100) + "%" });
    if (this.forced === "off") Object.assign(m, { on: false, online: true, levelText: "Off" });
    return m;
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
    const m: BlindsModel = { name: this.label(it), room: it.room, showRoom: this.showRoom(), position: pos, moving, online: st.online, hold: this.needsHold(it), allowed: it.allowed };
    if (this.forced) Object.assign(m, { position: this.forced === "on" ? 100 : 0, moving: null, online: true });
    return m;
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
      } else detail = level === "ok" ? "all good" : level === "crit" ? "needs a look" : "";
    }
    if (this.forced) {
      level = this.forced === "on" ? "crit" : "ok";
      if (!look.count) value = level === "ok" ? "OK" : "Down";
    }
    return { label: this.settings.label || (it.id in STATUS_LOOK ? look.label : it.name), value, detail, level, icon: look.icon };
  }

  private sceneFlash(): "ok" | "fail" | null {
    return this.forced === "on" ? "ok" : this.forced === "off" ? null : this.flash;
  }

  private keyImage(): string {
    if (this.theme !== "classic") return renderLook(this.theme, this.face(), { info: this.info(), fit: this.nameFit() });
    const o = this.classicOpts();
    switch (this.kind) {
      case "control":
        return renderControl(this.controlModel(), o);
      case "reading":
        return renderReading(this.readingModel(), o);
      case "thermostat":
        return renderThermostat(this.thermoModel(), o);
      case "dimmer":
        return renderDimmer(this.dimmerModel(), o);
      case "blinds":
        return renderBlinds(this.blindsModel(), o);
      case "scene": {
        const it = this.item!;
        return renderScene({ name: this.label(it), room: it.room, kind: it.kind, icon: it.icon, flash: this.sceneFlash(), hold: this.needsHold(it), allowed: it.allowed }, o);
      }
      case "status":
        return renderStatus(this.statusModel(), o);
    }
  }

  /** (1.1) What the key has to say, for the looks other than Classic. */
  face(): Face {
    const it = this.item!;
    const st = this.st ?? it.state;
    const base = {
      kind: this.kind as string, room: it.room, unit: "", stateColour: null as string | null, detail: "", mode: "", level: null as number | null,
      series: [] as number[], target: null as number | null, battery: st.battery, allowed: it.allowed, hold: this.needsHold(it),
      taken: st.held === true,
    };
    const acc = this.accentOverride();
    switch (this.kind) {
      case "control": {
        const m = this.controlModel();
        const look = lookFor(it.kind, it.icon, m.on);
        const a = dialAttr(it, "control");
        const raw = this.dial.shown ?? (a ? numOf(st.attrs[a.key]) : null);
        return {
          ...base, name: m.name, icon: look.icon, accent: acc ?? look.accent, active: m.on === true && m.online, online: m.online,
          state: m.on === true ? "On" : m.on === false ? "Off" : m.valueText || "—", detail: m.on !== null ? m.valueText : "",
          level: a && raw !== null ? fraction(raw, a.min, a.max) : null,
        };
      }
      case "reading": {
        const m = this.readingModel();
        const t = m.trend === "up" ? "↑ rising" : m.trend === "down" ? "↓ falling" : m.trend === "flat" ? "→ steady" : "";
        return {
          ...base, name: m.label, icon: m.icon, accent: m.accent, active: m.colour !== m.accent, online: m.online, state: m.value, unit: m.unit,
          stateColour: m.colour, detail: t, series: m.history,
        };
      }
      case "thermostat": {
        const m = this.thermoModel();
        const u = m.unit ? " " + m.unit : "";
        const span = Math.max(0.5, m.max - m.min);
        return {
          ...base, name: m.name, icon: m.heating ? "flame" : "thermostat", accent: acc ?? (m.heating ? P.orange : P.info), active: m.heating, online: m.online,
          state: fmtTemp(m.current), unit: m.current !== null ? m.unit : "", detail: m.target !== null ? "→ " + fmtTemp(m.target) + u : "", mode: m.mode,
          level: m.target !== null ? Math.max(0, Math.min(1, (m.target - m.min) / span)) : null, series: m.history ?? [], target: m.target,
        };
      }
      case "dimmer": {
        const m = this.dimmerModel();
        const on = m.on === true && m.online;
        return {
          ...base, name: m.name, icon: on ? "bulbOn" : "bulb", accent: acc ?? P.warn, active: on, online: m.online,
          state: m.on === true ? "On" : m.on === false ? "Off" : "—", detail: m.on === true && m.levelText !== "Off" ? m.levelText : "", level: m.level,
        };
      }
      case "blinds": {
        const m = this.blindsModel();
        const p = m.position;
        const word = p === null ? "—" : p >= 99.5 ? "Open" : p <= 0.5 ? "Closed" : Math.round(p) + "%";
        return {
          ...base, name: m.name, icon: m.moving === "up" ? "blindsUp" : m.moving === "down" ? "blindsDown" : "blinds", accent: acc ?? P.purple,
          active: (p !== null && p > 0.5) || m.moving !== null, online: m.online, state: word,
          detail: m.moving === "up" ? "Opening…" : m.moving === "down" ? "Closing…" : p !== null && word !== Math.round(p) + "%" ? "" : "",
          level: p === null ? null : p / 100,
        };
      }
      case "scene": {
        const look = lookFor(it.kind, it.icon);
        const f = this.sceneFlash();
        return {
          ...base, name: this.label(it), icon: f === "ok" ? "check" : f === "fail" ? "close" : look.icon, accent: f === "fail" ? P.crit : f === "ok" ? P.ok : acc ?? look.accent,
          active: f === "ok", online: true, state: f === "ok" ? "Done" : f === "fail" ? "Failed" : "Run", stateColour: f === "fail" ? P.crit : null,
        };
      }
      case "status": {
        const m = this.statusModel();
        const c = m.level === "ok" ? acc ?? P.ok : m.level === "warn" ? P.warn : m.level === "crit" ? P.crit : P.dim;
        return {
          ...base, name: m.label, room: null, icon: m.icon, accent: c, active: m.level === "warn" || m.level === "crit", online: true,
          state: m.value, stateColour: c, detail: m.detail,
        };
      }
    }
  }

  // ------------------------------------------------------------------ the look on the touch strip

  /**
   * The choices on a dial's strip, as far as its layout goes: what is shown (a hidden part is
   * left empty), the accent (given to the feedback builders), and the look's paper behind it all,
   * its ink on the words and its tile round the icon.
   */
  private styleStrip(fb: Feedback, layout: keyof typeof LAYOUTS): Feedback {
    if (this.plain()) return this.styledStrip ? this.unstyleStrip(fb, layout) : fb;
    const i = this.info();
    const f = this.face();
    const blank = dataUri(svgDoc(4, 4, ""));
    const out: Feedback = { ...fb };
    const val = (k: string) => {
      const v = out[k];
      return typeof v === "object" && v !== null ? v : { value: v as string | number };
    };
    if (!i.name && "name" in out) out.name = { ...val("name"), value: !i.room || !f.room || this.kind === "reading" ? "" : f.room };
    else if ("name" in out && (this.kind === "control" || this.kind === "dimmer" || this.kind === "blinds")) {
      out.name = { ...val("name"), value: f.name + (i.room && f.room && this.showRoom() ? " · " + f.room : "") };
    }
    if (!i.state && "value" in out) {
      const alt = [i.detail ? f.detail : "", i.mode ? f.mode : ""].filter(Boolean).join(" · ");
      out.value = { ...val("value"), value: this.kind === "thermostat" ? "" : alt };
    } else if (!i.detail && this.kind === "control" && "value" in out) out.value = { ...val("value"), value: f.online && f.allowed ? f.state : String(val("value").value ?? "") };
    if (!i.detail && "target" in out) out.target = { ...val("target"), value: "" };
    if (!i.detail && "sub" in out) out.sub = { ...val("sub"), value: "" };
    if (!i.mode && "mode" in out) out.mode = { ...val("mode"), value: "" };
    if (!i.icon && "icon" in out) out.icon = blank;
    if (!i.graph && "art" in out && this.kind !== "thermostat") out.art = blank;
    const t = this.theme;
    if (t === "classic") {
      if (this.styledStrip) {
        out.bg = blank;
        this.recolour(out, layout, (c) => c);
      }
      return out;
    }
    this.styledStrip = true;
    const lit = f.active && f.online;
    const c = f.online ? f.accent : P.crit;
    const paperInk = t === "light" || (t === "contrast" && lit) || (t === "fill" && lit);
    const inkOf = (col: string) => {
      if (t === "light") return col === P.text ? X.ink : col === P.dim ? X.inkDim : col === P.crit ? X.inkCrit : col === P.muted ? X.inkMuted : col;
      if (paperInk) return col === P.crit ? P.bg : t === "fill" ? P.bg : X.black;
      if (t === "contrast") return col === P.dim || col === P.muted ? X.white : col === P.crit ? X.hcRed : col;
      return col;
    };
    this.recolour(out, layout, inkOf);
    out.bg = dataUri(stripPaper(t, lit, c));
    if (i.icon && "icon" in out) {
      const size = layout === "dimmer" ? 36 : layout === "reading" ? 22 : 40;
      out.icon = paperInk || t === "light"
        ? iconPix(f.icon, t === "light" ? (lit ? c : X.inkDim) : P.bg, size, t === "light" && lit ? c : undefined)
        : t === "contrast" ? iconPix(f.icon, X.white, size) : t === "minimal" || t === "mono" ? iconPix(f.icon, lit ? c : P.muted, size)
        : t === "aurora" && lit ? iconPix(f.icon, X.white, size) : iconPix(f.icon, lit ? c : P.dim, size, lit ? c : undefined);
    }
    return out;
  }

  /** The text items given a colour each: their own (or the layout's), passed through the look's ink. */
  private recolour(out: Feedback, layout: keyof typeof LAYOUTS, ink: (c: string) => string): void {
    for (const it of LAYOUTS[layout]!.items) {
      if (it.type !== "text" || !(it.key in out)) continue;
      const v = out[it.key];
      const o = typeof v === "object" && v !== null ? v : { value: v as string | number };
      out[it.key] = { ...o, color: ink(o.color ?? it.color ?? P.text) };
    }
  }

  /** Back to the layout's own colours and no paper, after a look had changed them. */
  private unstyleStrip(fb: Feedback, layout: keyof typeof LAYOUTS): Feedback {
    const out: Feedback = { ...fb, bg: dataUri(svgDoc(4, 4, "")) };
    this.recolour(out, layout, (c) => c);
    return out;
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
        const pa = this.pressAction();
        const hint = !m.allowed ? "Not allowed" : !m.online ? "Offline" : pa === "toggle" ? (m.on ? "Push to turn off" : "Push to turn on") : pa ? "Push: " + pressWord(pa).toLowerCase() : "";
        return controlFeedback(m, f, txt, hint, this.accentOverride());
      }
      case "reading":
        return readingFeedback(this.readingModel(), this.plain() ? undefined : this.info());
      case "thermostat": {
        const m = this.thermoModel();
        if (this.dial.shown !== null) m.target = this.dial.shown;
        return thermoFeedback(m, this.accentOverride(), this.plain() ? undefined : this.info());
      }
      case "dimmer":
        return dimmerFeedback(this.dimmerModel(), this.accentOverride());
      case "blinds":
        return blindsFeedback(this.blindsModel(), this.accentOverride());
      case "scene": {
        const it = this.item!;
        const fb = controlFeedback({ ...this.controlModel(), on: null, valueText: this.flash === "ok" ? "Done" : this.flash === "fail" ? "Failed" : "Push to run" }, null, "", "", this.accentOverride());
        fb.value = { value: this.flash === "ok" ? "Done ✓" : this.flash === "fail" ? "Failed" : this.label(it), color: this.flash === "ok" ? P.ok : this.flash === "fail" ? P.crit : P.text };
        fb.name = { value: it.room ?? "Scene" };
        return fb;
      }
      case "status": {
        const m = this.statusModel();
        const c = m.level === "ok" ? P.ok : m.level === "warn" ? P.warn : m.level === "crit" ? P.crit : P.dim;
        const words = { ok: "All good", warn: "Have a look", crit: "Needs attention", unknown: "Not known" };
        return {
          icon: iconPix(m.icon, c, 40, m.level === "unknown" ? undefined : c),
          name: { value: m.label },
          value: { value: m.value, color: c },
          art: pillArt(176, 30, m.detail ? m.detail.charAt(0).toUpperCase() + m.detail.slice(1) : words[m.level], c, m.level !== "unknown"),
        };
      }
    }
  }

  private triggers(): { push?: string; rotate?: string; touch?: string; longTouch?: string } {
    switch (this.kind) {
      case "control":
        return { push: pressWord(this.pressAction()), rotate: "Adjust", touch: pressWord(this.pressAction()) };
      case "reading":
        return { push: "Refresh", touch: "Refresh" };
      case "thermostat": {
        const p = this.settings.press ?? "mode";
        const push = p === "details" ? "Details" : p.startsWith("set:") ? MODE_WORDS[p.slice(4)] ?? "Mode" : p === "boost" ? "Boost" : p === "preset" ? "Next preset" : "Next mode";
        return { push: (this.needsHold(this.item) ? "Hold: " : "") + push, rotate: "Setpoint", touch: "Boost" };
      }
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
    if (this.kind === "thermostat" && this.settings.press === "details" && !this.notice()) {
      this.showDetails();
      return;
    }
    const it = this.guard();
    if (!it) return;
    const cmd = what();
    if (cmd && this.cycles(it) && cmd.attr && typeof cmd.value === "string") {
      // (1.2) stepped to at once, sent once the presses stop
      this.cycle = { attr: cmd.attr, value: cmd.value, id: it.id };
      if (this.cycleTimer) clearTimeout(this.cycleTimer);
      this.cycleTimer = setTimeout(() => {
        this.cycleTimer = null;
        const c = this.cycle;
        if (!c || this.disposed) return;
        void this.run({ id: c.id, action: "set", attr: c.attr, value: c.value }).finally(() => {
          if (this.cycle === c) this.cycle = null;
          this.draw();
        });
      }, CYCLE_SETTLE_MS);
      this.draw();
      return;
    }
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

  /** (1.2) A thermostat key that goes round its modes or presets - not one that sets one outright,
   * and not one held to confirm (each confirmed press is meant, and is sent). */
  private cycles(it: Item): boolean {
    const p = this.settings.press ?? "mode";
    return this.kind === "thermostat" && (p === "mode" || p === "preset") && !this.needsHold(it);
  }

  private pressEnd(): void {
    this.press?.up();
  }

  /** A thermostat's mode, target, measured temperature and thermometer, on the key for DETAILS_MS. */
  showDetails(): void {
    this.detailsUntil = Date.now() + DETAILS_MS;
    if (this.detailsTimer) clearTimeout(this.detailsTimer);
    this.detailsTimer = setTimeout(() => {
      this.detailsUntil = 0;
      this.draw();
    }, DETAILS_MS);
    this.draw();
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
        if (!a || a === "set" || a === "step") return null;
        // (1.2) "By hand": only a switch, and only a press that switches it, takes anything over
        return this.settings.byHand === true && it.cap === "switch" && (a === "toggle" || a === "on" || a === "off")
          ? { id: it.id, action: a, by_hand: true } : { id: it.id, action: a };
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
    if (what.startsWith("set:")) {
      // one mode outright: Comfort, Eco, Night, Max, Off, Plan or By hand
      const want = what.slice(4);
      const e = enumAttr(it, /mode/i);
      if (!e || !e.values.includes(want) || !(ROOM_MODES as readonly string[]).includes(want)) return null;
      return { id: it.id, action: "set", attr: e.key, value: want };
    }
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
      if (this.needsHold(it)) return this.showToast("Hold the dial", "to confirm", "warn");
      void this.run(cmd);
      return;
    }
    if (this.kind === "blinds" && it) {
      if (!this.guard()) return;
      if (this.needsHold(it)) return this.showToast("Hold the dial", "to confirm", "warn");
      if (it.actions.includes("stop")) void this.run({ id: it.id, action: "stop" });
      return;
    }
    // elsewhere a touch is a quick press (a hold needs the dial itself held down)
    if (it && this.needsHold(it) && acts(this.kind)) return this.showToast("Hold the dial", "to confirm", "warn");
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

const ON_OFF_WORDS: Record<ActionKind, [string, string]> = {
  control: ["On", "Off"], reading: ["Alert", "Normal"], thermostat: ["Heating", "Idle"], dimmer: ["On", "Off"], blinds: ["Open", "Closed"],
  scene: ["Done", "Ready"], status: ["Problem", "All good"],
};

/** The look's paper behind a dial's strip (200 x 100). */
function stripPaper(theme: string, lit: boolean, c: string): string {
  const g = (id: string, a: string, oa: number, b: string, ob: number) =>
    `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}" stop-opacity="${oa}"/><stop offset="1" stop-color="${b}" stop-opacity="${ob}"/></linearGradient>`;
  switch (theme) {
    case "fill":
      return svgDoc(200, 100, `<rect width="200" height="100" rx="10" fill="${lit ? "url(#p)" : P.panel2}"/>`, g("p", c, 1, c, 0.72));
    case "neon":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>` + (lit
        ? `<rect x="5" y="5" width="190" height="90" rx="14" fill="none" stroke="${c}" stroke-opacity="0.15" stroke-width="8"/><rect x="5" y="5" width="190" height="90" rx="14" fill="none" stroke="${c}" stroke-width="2"/>`
        : `<rect x="5" y="5" width="190" height="90" rx="14" fill="none" stroke="${P.muted}" stroke-opacity="0.5" stroke-width="1.4"/>`));
    case "split":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><rect width="200" height="8" fill="${lit ? c : P.panel2}"/>`);
    case "glass":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="url(#p)"/><circle cx="30" cy="20" r="80" fill="${c}" fill-opacity="${lit ? 0.22 : 0.06}"/><rect x="3" y="3" width="194" height="94" rx="14" fill="${X.white}" fill-opacity="0.05" stroke="${X.white}" stroke-opacity="0.18"/>`, g("p", P.panel2, 1, X.night, 1));
    case "light":
      return svgDoc(200, 100, `<rect width="200" height="100" rx="10" fill="${X.paper}"/>` + (lit ? `<rect width="200" height="5" fill="${c}"/>` : ""));
    case "contrast":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${lit ? X.white : X.black}"/><rect x="3" y="3" width="194" height="94" rx="10" fill="none" stroke="${lit ? X.black : X.white}" stroke-width="4"/>`);
    case "dot":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.panel}"/><circle cx="192" cy="8" r="5" fill="${lit ? c : P.muted}"/>`);
    case "ring":
    case "bigvalue":
    case "label":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/>` + (lit ? `<rect x="0" y="97" width="200" height="3" fill="${c}"/>` : ""));
    case "minimal":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>`);
    // (1.2) the clear looks
    case "huge":
    case "gauge":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>` + (lit ? `<ellipse cx="100" cy="100" rx="130" ry="60" fill="${c}" fill-opacity="0.16"/>` : ""));
    case "pill":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><rect x="3" y="3" width="194" height="94" rx="47" fill="${lit ? c : P.panel}" fill-opacity="${lit ? 0.2 : 1}" stroke="${lit ? c : P.line}" stroke-width="2"/>`);
    case "orb":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>` + (lit ? `<circle cx="30" cy="50" r="70" fill="${c}" fill-opacity="0.18"/>` : ""));
    case "tile":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><rect x="3" y="3" width="194" height="94" rx="18" fill="${P.panel2}" stroke="${lit ? c : P.line}" stroke-width="2"/>`);
    case "bars":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/>` + (lit ? `<rect x="0" y="60" width="200" height="40" fill="${c}" fill-opacity="0.12"/><rect x="0" y="96" width="200" height="4" fill="${c}"/>` : ""));
    case "wave":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>` + (lit ? `<path d="M 0 72 Q 25 64 50 72 T 100 72 T 150 72 T 200 72 V 100 H 0 Z" fill="${c}" fill-opacity="0.3"/>` : ""));
    case "aurora":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/><rect width="200" height="100" fill="url(#p)"/>`,
        lit ? g("p", c, 0.55, X.night, 0.2) : g("p", P.panel2, 1, X.night, 1));
    case "outline":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/><rect x="4" y="4" width="192" height="92" rx="16" fill="none" stroke="${lit ? c : P.line}" stroke-width="${lit ? 5 : 2}"/>`);
    case "mono":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>` + (lit ? `<rect width="200" height="100" fill="${c}" fill-opacity="0.12"/>` : ""));
    default:
      return svgDoc(4, 4, "");
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
