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
import { colourOf, P, X } from "./palette.js";
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
import { factsOf, faceOfSummary, recipientWord, summaryOf, type Member, type Summary } from "./extra.js";
import { extraFeedback, renderExtra } from "./extra-render.js";
import { countdown, isNewKind, itemFor, NEEDS_ZIGMON, needs, POWER_SPANS, spanWord, stepMinutes, type NewKind } from "./kinds.js";

export type ActionKind = "control" | "reading" | "thermostat" | "dimmer" | "blinds" | "scene" | "status" | NewKind;

/** (1.3) The summaries' kinds: they only tell, so a Control key is not offered them. */
const SUMMARY_KINDS = new Set(["power", "security", "heatgroup", "openings", "batteries", "zigbee", "room", "sms"]);

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
      return it.actions.length > 0 && it.kind !== "status" && !SUMMARY_KINDS.has(it.kind);
    case "reading":
      // (1.3) and what is on or off: a scene (as it leaves things, or not), a rule, a group, a switch
      return it.kind !== "status" && (it.state.value !== null || it.state.on !== null || it.kind === "scene" || it.kind === "reading" || it.kind === "sensor" || it.attrs.some((a) => a.type === "number"));
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
    // (1.3, ZIGMon 5.59.4)
    case "power":
    case "security":
    case "heatgroup":
    case "away":
    case "openings":
    case "batteries":
    case "zigbee":
    case "room":
    case "sms":
      return it.kind === kind;
    case "timer":
      return it.cap === "switch" && (it.actions.includes("timer") || it.actions.includes("toggle"));
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
  power: "", security: "", heatgroup: "", away: "", openings: "", batteries: "", zigbee: "", sms: "",
  timer: "Pick a switch",
  room: "Pick a room",
};

const LAYOUT_OF: Record<ActionKind, keyof typeof LAYOUTS> = {
  control: "control", reading: "reading", thermostat: "thermostat", dimmer: "dimmer", blinds: "blinds", scene: "control", status: "control",
  power: "power", security: "summary", heatgroup: "summary", away: "summary", openings: "summary", batteries: "summary", zigbee: "summary",
  timer: "timer", room: "room", sms: "summary",
};

/** (1.3) A summary ZIGMon has none of here: why, in its words. */
const NONE_HERE: Partial<Record<ActionKind, string[]>> = {
  heatgroup: ["no heated room", "in ZIGMon"],
  away: ["no heated room", "in ZIGMon"],
  openings: ["no window or door", "sensor reports yet"],
  batteries: ["no device", "reports a battery"],
  sms: ["SMS is not set up", "or not allowed here"],
};

const STATUS_LOOK: Record<string, { label: string; icon: string; count: "crit" | "warn" | null }> = {
  "status:alerts": { label: "Alerts", icon: "bell", count: "crit" },
  "status:blocked": { label: "Blocked addresses", icon: "wall", count: "warn" },
  "status:proxy": { label: "Proxy", icon: "globe", count: null },
  "status:health": { label: "Health", icon: "heart", count: null },
  "status:gateway": { label: "Zigbee gateway", icon: "router", count: null },
  // (1.3, ZIGMon 5.59.4) also on a ZIGMon status key
  "status:security": { label: "Network security", icon: "shield", count: "crit" },
  "status:zigbee": { label: "Zigbee network", icon: "mesh", count: null },
  "status:sms": { label: "Text messages", icon: "message", count: null },
};

/** The modes of a heated room as the dashboard words them. */
export const MODE_WORDS: Record<string, string> = {
  plan: "Plan", comfort: "Comfort", eco: "Eco", night: "Night", max: "Max", off: "Off", manual: "By hand",
};

/** How long a press that shows a thermostat's details keeps them on the key. */
export const DETAILS_MS = 3000;

/** The actions that do something - the hold switch is theirs; Reading and ZIGMon status only look. */
export function acts(kind: ActionKind): boolean {
  return kind !== "reading" && kind !== "status" && kind !== "power" && kind !== "openings" && kind !== "batteries" && kind !== "zigbee";
}

/** (1.3) The new actions that only look: a press asks again, as a Reading's does. */
function looksOnly(kind: ActionKind): boolean {
  return kind === "power" || kind === "openings" || kind === "batteries" || kind === "zigbee";
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
  /** (1.3) House power's span as the dial set it (until the key is set up again). */
  private spanTurned: number | null = null;
  /** (1.3) The Timer's minutes as the dial set them. */
  private minutesTurned: number | null = null;
  /** (1.3) A timer's whole length, by its off_at, so its ring drains from full. */
  private timerLength = new Map<number, number>();
  private timerStarted: { at: number; minutes: number } | null = null;
  /** (1.3) A countdown ticking on the key, once a second. */
  private ticker: ReturnType<typeof setInterval> | null = null;
  /** (1.3) The Room dial's member scrolled to. */
  private memberAt = 0;

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
    const id = this.itemId();
    if (!id) return [];
    // (1.3) a Room dial watches the member it shows as well
    const m = this.kind === "room" && this.surface.controller === "Encoder" ? this.member() : null;
    return m ? [id, m.item.id] : [id];
  }

  /** The item this key shows: (1.3) a new action's fixed summary or SMS mode's item, else the one picked. */
  itemId(): string | undefined {
    return isNewKind(this.kind) ? itemFor(this.kind, this.settings) : this.settings.item;
  }

  refresh(): void {
    if (this.disposed) return;
    this.draw();
  }

  setSettings(s: unknown): void {
    const before = this.itemId();
    this.settings = normalizeAction(s);
    this.dial.cancel();
    this.spanTurned = null;
    this.minutesTurned = null;
    // a new item, or a graph of another span: the hub asks again (it only restarts the wait for a new item)
    if (before !== this.itemId() || this.series().length) this.hub.resubscribe();
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
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
    this.cycle = null;
  }

  /** (1.1) The series this key draws, for the hub to ask ZIGMon for. */
  series(): { id: string; span: number }[] {
    const id = this.itemId();
    if (!id || (this.kind !== "reading" && this.kind !== "thermostat" && this.kind !== "power")) return [];
    return this.info().graph ? [{ id, span: this.span() }] : [];
  }

  span(): number {
    return this.spanTurned ?? this.settings.span ?? 86400;
  }

  // ------------------------------------------------------------------ the item

  private get item(): Item | undefined {
    return this.hub.item(this.itemId());
  }

  private get st(): ItemState | undefined {
    const st = this.hub.state(this.itemId());
    const c = this.cycle;
    if (!st || !c || c.id !== this.itemId()) return st;
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
    if (this.theme !== "classic" || s.accent || s.accentOff || s.nameFit || s.span) return false;
    for (const k of ["showIcon", "showName", "showState", "showDetail", "showMode", "showGraph", "showBattery", "showScale", "showTarget"]) if (s[k] !== undefined) return false;
    return !(s.label && this.kind !== "reading");
  }

  private classicOpts(): ClassicOpts {
    if (this.plain()) return {};
    return { info: this.info(), accent: this.accentOverride(), fit: (this.settings.nameFit as NameFit | undefined) ?? "cut", offAccent: this.offOverride() };
  }

  /** The On colour the user chose (by name, or their own #RRGGBB); none = the item's own. */
  private accentOverride(): string | undefined {
    return colourOf(this.settings.accent);
  }

  /** (1.3) The Off colour the user chose; none = the look's own off style. */
  private offOverride(): string | undefined {
    return colourOf(this.settings.accentOff);
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
    // (1.3) the new actions need a ZIGMon that offers them; an older one is never asked
    if (isNewKind(this.kind) && ph === "online" && this.hub.supports) {
      for (const f of needs(this.kind)) if (this.hub.supports(f) === false) return { icon: "download", title: "Needs ZIGMon", lines: [NEEDS_ZIGMON + " or newer"], tone: "warn" };
    }
    if (!this.itemId()) return { icon: "search", title: "Choose", lines: [NOT_CHOSEN[this.kind]], tone: "muted" };
    if (!this.item) return { icon: "search", title: "Not found", lines: NONE_HERE[this.kind] ?? ["ZIGMon does not", "show it to this deck"], tone: "muted" };
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
      this.syncTicker(!n);
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
    this.syncTicker(!n);
  }

  /** (1.3) A timer counting down redraws its key every second; none, no ticking. */
  private syncTicker(shown: boolean): void {
    const want = shown && !this.disposed && this.counting();
    if (want && !this.ticker) {
      this.ticker = setInterval(() => this.draw(), 1000);
      (this.ticker as { unref?: () => void }).unref?.();
    } else if (!want && this.ticker) {
      clearInterval(this.ticker);
      this.ticker = null;
    }
  }

  /** (1.3) Whether a way back to off is pending on this key's switch (its off_at is still to come). */
  counting(): boolean {
    if (this.kind !== "timer" && this.kind !== "control") return false;
    const st = this.st;
    const t = st && typeof st.attrs.off_at === "number" ? st.attrs.off_at : null;
    return t !== null && t > Date.now() / 1000 && st!.on !== false;
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
      return { themes, on, off, words: this.kind === "sms" ? SMS_WORDS[this.smsMode()] : ON_OFF_WORDS[this.kind] };
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
    if (isNewKind(this.kind) && it) return this.summary().accent;
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
    // (1.3) a timer running on the switch: its countdown by the state
    const offAt = numOf(st.attrs.off_at);
    if (offAt !== null && st.on === true && offAt > Date.now() / 1000) m.valueText = "⏱ " + countdown(offAt - Date.now() / 1000);
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
    // (1.3) a thing with no number - a scene, a rule, a group: its state as the value, a word under it
    if (v === null && !attr && (st.on !== null || it.kind === "scene")) {
      const lk = lookFor(it.kind, it.icon);
      const acc = this.accentOverride() ?? lk.accent;
      const n = numOf(st.attrs.members), k = numOf(st.attrs.as_set);
      const note = it.kind === "scene" && n !== null && n > 0 && k !== null ? `${k}/${n} as set` : st.valueText && !/^(on|off)$/i.test(st.valueText) ? st.valueText : "";
      return {
        label: s.label || it.name, value: st.on === true ? "On" : st.on === false ? "Off" : "—", unit: "",
        colour: this.forced === "off" || (!this.forced && st.on !== true) ? P.dim : acc, accent: acc, icon: lk.icon, trend: null, history: [],
        online: this.forced ? true : st.online, lit: this.forced ? this.forced === "on" : st.on === true, ...(note ? { note } : {}),
      };
    }
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
    // (1.3) what says it heats: a room's "calling", a head's running state or demand - never a set point
    // (current_heating_setpoint matched "heating", so a head read as heating whatever it did)
    const keys = Object.keys(st.attrs).filter((k) => !/setpoint|target|temp/i.test(k));
    const pick = (re: RegExp) => keys.find((k) => re.test(k));
    const rk = pick(/^calling$/) ?? pick(/running/i) ?? pick(/demand/i) ?? pick(/heating/i) ?? pick(/valve/i);
    const run = rk !== undefined ? ([rk, st.attrs[rk]] as const) : undefined;
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
      taken: st.held === true,
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
    if (isNewKind(this.kind)) return renderExtra(this.summary(), o);
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
        const on = it.kind !== "scene" ? null : this.forced ? this.forced === "on" : (this.st ?? it.state).on;
        return renderScene({ name: this.label(it), room: it.room, kind: it.kind, icon: it.icon, flash: this.sceneFlash(), hold: this.needsHold(it), allowed: it.allowed,
          ...(on === true || on === false ? { on } : {}) }, o);
      }
      case "status":
        return renderStatus(this.statusModel(), o);
    }
  }

  // ------------------------------------------------------------------ (1.3) the new actions

  private smsMode(): "last" | "compose" | "status" {
    const m = this.settings.smsMode;
    return m === "compose" || m === "status" ? m : "last";
  }

  /** The Timer's minutes: as the dial set them, else the key's setting, else half an hour. */
  minutes(): number {
    return this.minutesTurned ?? this.settings.minutes ?? 30;
  }

  /** The press of a new action: its item's grant for that action (an `act` grant where there is one). */
  grantFor(id: string, action: ItemAction): { allowed: boolean; hold: boolean } {
    const it = this.hub.item(id);
    if (!it) return { allowed: false, hold: false };
    const g = it.act?.[action];
    const own = this.settings.hold === true && acts(this.kind);
    return g ? { allowed: g.allowed, hold: g.hold || own } : { allowed: it.allowed, hold: it.hold || own };
  }

  /** Whether a press must be held: its own grant, and (Away) the switches it then turns off. */
  private holdFor(cmd: Omit<Command, "deck">): boolean {
    let h = this.grantFor(cmd.id, cmd.action).hold;
    if (this.kind === "away" && this.goingAway()) for (const id of this.settings.awayOff ?? []) h ||= this.hub.item(id)?.hold === true;
    return h;
  }

  private goingAway(): boolean {
    const st = this.st;
    return !!st && !(st.attrs.away === true || (st.attrs.away === undefined && st.on === true));
  }

  /** The room's members this deck may see and the plugin knows, in the catalogue's order. */
  private members(): Item[] {
    const it = this.item;
    if (!it?.members) return [];
    return it.members.map((id) => this.hub.item(id)).filter((m): m is Item => !!m);
  }

  private member(): Member | null {
    const ms = this.members();
    if (!ms.length) return null;
    const i = ((this.memberAt % ms.length) + ms.length) % ms.length;
    const m = ms[i]!;
    return { item: m, state: this.hub.state(m.id) ?? m.state, index: i, count: ms.length };
  }

  /** The timer's whole length (s), to drain its ring from: as started here, else what was left when first seen. */
  private timerTotal(st: ItemState): number | null {
    const offAt = numOf(st.attrs.off_at);
    if (offAt === null) return null;
    const known = this.timerLength.get(offAt);
    if (known !== undefined) return known;
    const now = Date.now() / 1000;
    const s = this.timerStarted;
    const total = s && Math.abs(offAt - (s.at + s.minutes * 60)) < 15 ? s.minutes * 60 : Math.max(60, Math.ceil((offAt - now) / 60) * 60);
    if (this.timerLength.size > 8) this.timerLength.clear();
    this.timerLength.set(offAt, total);
    return total;
  }

  /** (1.3) What a new action has to say now (extra.ts), for every look, the strip and the inspector. */
  summary(): Summary {
    const it = this.item!;
    const st = this.st ?? it.state;
    const cmd = this.keyCommand();
    const g = cmd ? this.grantFor(cmd.id, cmd.action) : { allowed: it.allowed, hold: false };
    const hold = cmd ? this.holdFor(cmd) : this.settings.hold === true && acts(this.kind);
    return summaryOf({
      kind: this.kind as NewKind, it, st, label: this.settings.label || it.name, accent: this.accentOverride(), offAccent: this.offOverride(),
      forced: this.forced, now: Date.now() / 1000, series: this.kind === "power" ? this.historyOf(it.id) : [], span: this.span(),
      hold: looksOnly(this.kind) ? false : hold, allowed: looksOnly(this.kind) || this.kind === "room" ? true : g.allowed,
      minutes: this.minutes(), total: this.timerTotal(st), cycle: this.cycle && this.cycle.id === it.id ? this.cycle.value : null,
      member: this.kind === "room" ? this.member() : null, to: this.settings.smsTo ?? [], book: this.hub.smsBook?.() ?? null, muteMinutes: this.settings.muteMinutes ?? 60,
    });
  }

  /** (1.3) The inspector's "Now": what the item says beyond the key (every window open, the whole latest alert...). */
  facts(): [string, string][] | null {
    if (!isNewKind(this.kind) || this.notice()) return null;
    const it = this.item!;
    const s = this.summary();
    return factsOf({ kind: this.kind, it, st: this.st ?? it.state, label: s.name, forced: null, now: Date.now() / 1000, series: [], span: this.span(),
      hold: s.hold, allowed: s.allowed, minutes: this.minutes(), total: null, cycle: null, member: null, to: this.settings.smsTo ?? [], book: this.hub.smsBook?.() ?? null, muteMinutes: 60 }, s, this.members());
  }

  /** The strip of a new action: its own layout, with what a push does. */
  private extraStrip(): Feedback {
    const s = this.summary();
    const m = this.kind === "room" ? this.member() : null;
    const hint = this.kind === "timer" ? (s.x.running ? "push = off" : "turn · push = on")
      : this.kind === "power" ? "turn: " + POWER_SPANS.map(spanWord).join(" / ") : "";
    let mem = null;
    if (m) {
      const look = lookFor(m.item.kind, m.item.icon, m.state.on);
      const word = !m.state.online ? "Offline" : m.state.on === true ? "On" : m.state.on === false ? "Off" : m.state.valueText || "—";
      const val = m.state.on !== null && m.state.valueText && m.state.online ? word + " · " + m.state.valueText : word;
      mem = { name: m.item.name, icon: look.icon, colour: look.accent, state: m.item.allowed ? val : val + " · locked", lit: m.state.on === true && m.state.online, index: m.index, count: m.count };
    }
    return extraFeedback(s, hint, mem);
  }

  /** (1.3) What a press of a new action sends. */
  private extraCommand(): Omit<Command, "deck"> | null {
    const it = this.item;
    if (!it) return null;
    const st = this.st ?? it.state;
    switch (this.kind as NewKind) {
      case "security":
        return it.actions.includes("ack") ? { id: it.id, action: "ack" } : null;
      case "heatgroup": {
        const want = this.settings.press ?? "mode";
        const e = enumAttr(it, /^mode$/) ?? enumAttr(it, /mode/i);
        if (!it.actions.includes("set")) return null;
        if (want.startsWith("set:")) {
          const m = want.slice(4);
          return (ROOM_MODES as readonly string[]).includes(m) && (!e || e.values.includes(m)) ? { id: it.id, action: "set", attr: e?.key ?? "mode", value: m } : null;
        }
        const values = e?.values.length ? e.values : [...ROOM_MODES];
        const cur = strOf(st.attrs[e?.key ?? "mode"]);
        return { id: it.id, action: "set", attr: e?.key ?? "mode", value: values[(values.indexOf(cur) + 1) % values.length]! };
      }
      case "away":
        return it.actions.includes("toggle") ? { id: it.id, action: "toggle" } : null;
      case "timer":
        return this.timerCommand(it);
      case "sms": {
        const mode = this.smsMode();
        if (mode === "status") {
          const muted = (numOf(st.attrs.muted_until) ?? 0) > Date.now() / 1000;
          if (muted) return it.actions.includes("unmute") ? { id: it.id, action: "unmute" } : null;
          return it.actions.includes("mute") ? { id: it.id, action: "mute", minutes: this.settings.muteMinutes ?? 60 } : null;
        }
        const to = this.settings.smsTo ?? [];
        return mode === "compose" && to.length ? { id: it.id, action: "run", to: to.slice(0, 20) } : { id: it.id, action: "run" };
      }
      case "room": {
        const m = this.member();
        return m ? memberCommand(m.item, m.state) : null;
      }
      default:
        return null;
    }
  }

  /** A switch's timer: on for the minutes, or (one running) off, which cancels it. */
  private timerCommand(it: Item): Omit<Command, "deck"> | null {
    if (!it.actions.includes("timer") && !it.actions.includes("toggle")) return null;
    if (this.counting()) return it.actions.includes("off") || it.actions.includes("toggle") ? { id: it.id, action: it.actions.includes("off") ? "off" : "toggle" } : null;
    const cmd: Omit<Command, "deck"> = { id: it.id, action: "timer", minutes: Math.max(1, Math.min(720, Math.round(this.minutes()))) };
    return this.settings.byHand === true && it.cap === "switch" ? { ...cmd, by_hand: true } : cmd;
  }

  /** After a press went through: Away turns off the chosen switches too; a timer remembers its length. */
  private async afterPress(cmd: Omit<Command, "deck">, r: CommandResult, held: number | undefined): Promise<void> {
    if (!r.ok) return;
    if (cmd.action === "timer" && cmd.minutes) this.timerStarted = { at: Date.now() / 1000, minutes: cmd.minutes };
    if (this.kind !== "away" || !cmd.id) return;
    const st = r.state ?? this.hub.state(cmd.id);
    const away = !!st && (st.attrs.away === true || (st.attrs.away === undefined && st.on === true));
    const extra = this.settings.awayOff ?? [];
    if (!away || !extra.length) return;
    let off = 0, refused = 0, missing = 0;
    for (const id of extra) {
      const x = this.hub.item(id);
      if (!x || !x.actions.includes("off")) {
        missing++;
        continue;
      }
      if (!x.allowed) {
        refused++;
        continue;
      }
      const c: Omit<Command, "deck"> = { id, action: "off" };
      if (held !== undefined && x.hold) c.held_ms = Math.round(held);
      const rr = await this.hub.command({ deck: this.surface.deckId, ...c });
      if (rr.ok) off++;
      else refused++;
    }
    if (refused || missing) this.showToast("Away", off + " off · " + (refused + missing) + " not", "warn", 2400);
    else this.showToast("Away", off + (off === 1 ? " switch off" : " switches off"), "ok", 1800);
  }

  /** (1.1) What the key has to say, for the looks other than Classic. */
  face(): Face {
    if (isNewKind(this.kind)) return faceOfSummary(this.summary());
    const it = this.item!;
    const st = this.st ?? it.state;
    const base = {
      kind: this.kind as string, room: it.room, unit: "", stateColour: null as string | null, detail: "", mode: "", level: null as number | null,
      series: [] as number[], target: null as number | null, battery: st.battery, allowed: it.allowed, hold: this.needsHold(it),
      taken: st.held === true, offAccent: this.offOverride() ?? null,
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
          ...base, name: m.label, icon: m.icon, accent: m.accent, active: m.lit ?? m.colour !== m.accent, online: m.online, state: m.value, unit: m.unit,
          stateColour: m.colour, detail: m.note ?? t, series: m.history,
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
        const sceneOn = it.kind !== "scene" ? null : this.forced ? this.forced === "on" : st.on;  // (1.3) a scene says whether all is as it leaves it
        return {
          ...base, name: this.label(it), icon: f === "ok" ? "check" : f === "fail" ? "close" : look.icon, accent: f === "fail" ? P.crit : f === "ok" ? P.ok : acc ?? look.accent,
          active: f === "ok" || (!f && sceneOn === true), online: true,
          state: f === "ok" ? "Done" : f === "fail" ? "Failed" : sceneOn === true ? "On" : sceneOn === false ? "Off" : "Run", stateColour: f === "fail" ? P.crit : null,
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
    // (1.3) a Room dial's "name" is the member it shows; its own name is on the top line
    if (this.kind === "room" && !i.name && "top" in out) out.top = { ...val("top"), value: "" };
    else if (this.kind === "room") { /* the member stays */ }
    else if (!i.name && "name" in out) out.name = { ...val("name"), value: !i.room || !f.room || this.kind === "reading" ? "" : f.room };
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
    const off = !lit && f.online && f.offAccent ? f.offAccent : undefined;
    const paperInk = t === "light" || (t === "contrast" && lit) || (t === "fill" && lit);
    const inkOf = (col: string) => {
      if (t === "light") return col === P.text ? X.ink : col === P.dim ? X.inkDim : col === P.crit ? X.inkCrit : col === P.muted ? X.inkMuted : col;
      if (paperInk) return col === P.crit ? P.bg : t === "fill" ? P.bg : X.black;
      if (t === "contrast") return col === P.dim || col === P.muted ? X.white : col === P.crit ? X.hcRed : col;
      return col;
    };
    this.recolour(out, layout, inkOf);
    out.bg = dataUri(stripPaper(t, lit, c));
    if (i.icon && "icon" in out && !(this.kind === "room" && this.member())) {
      const size = layout === "dimmer" || layout === "room" ? 36 : layout === "reading" || layout === "power" ? 22 : 40;
      out.icon = paperInk || t === "light"
        ? iconPix(f.icon, t === "light" ? (lit ? c : X.inkDim) : P.bg, size, t === "light" && lit ? c : undefined)
        : t === "contrast" ? iconPix(f.icon, off ?? X.white, size) : t === "minimal" || t === "mono" ? iconPix(f.icon, lit ? c : off ?? P.muted, size)
        : t === "aurora" && lit ? iconPix(f.icon, X.white, size) : iconPix(f.icon, lit ? c : off ?? P.dim, size, lit ? c : off);
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
    if (isNewKind(this.kind)) return this.extraStrip();
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
        return controlFeedback(m, f, txt, hint, this.accentOverride(), this.offOverride());
      }
      case "reading":
        return readingFeedback(this.readingModel(), this.plain() ? undefined : this.info());
      case "thermostat": {
        const m = this.thermoModel();
        if (this.dial.shown !== null) m.target = this.dial.shown;
        return thermoFeedback(m, this.accentOverride(), this.plain() ? undefined : this.info(), this.offOverride());
      }
      case "dimmer":
        return dimmerFeedback(this.dimmerModel(), this.accentOverride(), this.offOverride());
      case "blinds":
        return blindsFeedback(this.blindsModel(), this.accentOverride(), this.offOverride());
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
      // (1.3)
      case "power":
        return { push: "Refresh", rotate: "Span", touch: "Refresh" };
      case "openings":
      case "batteries":
      case "zigbee":
        return { push: "Refresh", touch: "Refresh" };
      case "security":
        return { push: "Hold: acknowledge", touch: "Hold the dial" };
      case "heatgroup": {
        const p = this.settings.press ?? "mode";
        const push = p.startsWith("set:") ? MODE_WORDS[p.slice(4)] ?? "Mode" : "Next mode";
        return { push: (this.needsHold(this.item) ? "Hold: " : "") + push, rotate: "Mode", touch: push };
      }
      case "away":
        return { push: "Away / home", touch: "Away / home" };
      case "timer":
        return { push: "Start / cancel", rotate: "Minutes", touch: "Start / cancel" };
      case "room":
        return { push: "Switch it", rotate: "Scroll", touch: "Switch it" };
      case "sms": {
        const m = this.smsMode();
        return m === "status" ? { push: "Hold: mute / unmute", touch: "Hold the dial" } : m === "compose" ? { push: "Write", touch: "Write" } : { push: "Show", touch: "Show" };
      }
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
      // (1.3) the deck's SMS keys ask the desktop app linked to this Stream Deck (by the answer's flags):
      // none is running; the linked app's key may not; an entry of To names nothing
      noapp: ["Desktop app not running", "link one in ZIGMon", "warn"],
      notallowed: ["Not allowed in the app", "grant SMS to its key", "warn"],
      badto: ["Unknown recipient", r.bad?.length ? recipientWord(r.bad[0]!, this.hub.smsBook?.() ?? null) : "check the key's To", "warn"],
    };
    // (1.3) acknowledged with nothing standing: all is well, not a failure
    if (r.why === "nothing") {
      this.showToast("No alert", "nothing standing", "ok");
      return r;
    }
    const w = words[r.why] ?? ["Failed", r.message, "crit"];
    this.showToast(w[0], w[1], w[2], r.why === "noapp" || r.why === "notallowed" || r.why === "badto" ? 3200 : 1800);
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
    if (this.kind === "reading" || this.kind === "status" || looksOnly(this.kind) || (this.kind === "room" && this.surface.controller === "Keypad")) {
      this.hub.resubscribe();
      if (this.hub.currentPhase !== "online") this.hub.retryNow();
      void this.surface.showOk?.();
      return;
    }
    if (isNewKind(this.kind)) return this.pressNew(what);
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

  /** (1.3) A press of a new action: its own grant and hold (an `act` grant for ack / mute / unmute,
   * a Room member's own), Next mode stepped and sent once it stops, Away's switches after it. */
  private pressNew(what: () => Omit<Command, "deck"> | null): void {
    if (this.notice()) {
      void this.surface.showAlert();
      return;
    }
    const cmd = what();
    if (!cmd) {
      void this.surface.showAlert();
      this.showToast(this.kind === "room" ? "Nothing here" : "Nothing to do", this.kind === "room" ? "turn to pick an item" : "this item has no such action", "warn");
      return;
    }
    const g = this.grantFor(cmd.id, cmd.action);
    if (!g.allowed) {
      void this.surface.showAlert();
      this.showToast("Not allowed", this.kind === "security" || this.kind === "sms" && this.smsMode() === "status" ? "needs System in ZIGMon" : "grant it in ZIGMon", "crit");
      return;
    }
    const held = this.holdFor(cmd);
    if (this.kind === "heatgroup" && cmd.attr && typeof cmd.value === "string" && !(this.settings.press ?? "mode").startsWith("set:") && !held) {
      this.stepCycle(cmd.id, cmd.attr, cmd.value);
      return;
    }
    this.press?.cancel();
    this.press = new HoldPress(held, {
      progress: (p) => {
        this.holdProgress = p;
        this.draw();
      },
      fire: (ms) => {
        setTimeout(() => {
          this.holdProgress = null;
          this.draw();
        }, ms === undefined ? 0 : 350);
        const c = ms === undefined ? cmd : { ...cmd, held_ms: Math.round(ms) };
        void this.run(c).then((r) => this.afterPress(c, r, ms));
      },
      tooShort: () => {
        this.holdProgress = null;
        this.showToast("Hold to confirm", "keep it pressed 1.5 s", "warn");
      },
    });
    this.press.down();
  }

  /** (1.2) A mode stepped to at once, sent CYCLE_SETTLE_MS after the last press or turn. */
  private stepCycle(id: string, attr: string, value: string): void {
    this.cycle = { attr, value, id };
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
    // (1.3) a scene now takes toggle / on / off as well: unless chosen, a press still runs it
    for (const a of (it.actions.includes("run") ? ["run", "toggle", "on"] : ["toggle", "run", "on"]) as readonly ItemAction[]) if (it.actions.includes(a)) return a;
    return it.actions[0] ?? null;
  }

  private keyCommand(): Omit<Command, "deck"> | null {
    const it = this.item;
    if (!it) return null;
    if (isNewKind(this.kind)) return this.extraCommand();
    switch (this.kind) {
      case "control": {
        const a = this.pressAction();
        if (!a || a === "set" || a === "step") return null;
        // (1.3) Timer: on for the minutes chosen, a press again cancels it
        if (a === "timer") return this.timerCommand(it);
        // (1.2) "By hand": only a switch, and only a press that switches it, takes anything over
        return this.settings.byHand === true && it.cap === "switch" && (a === "toggle" || a === "on" || a === "off")
          ? { id: it.id, action: a, by_hand: true } : { id: it.id, action: a };
      }
      case "scene": {
        // (1.3) a scene may be switched as a switch: Toggle, On or Off, if chosen; Run otherwise, as before
        const want = this.settings.press;
        if ((want === "toggle" || want === "on" || want === "off") && it.actions.includes(want)) return { id: it.id, action: want };
        return it.actions.includes("run") ? { id: it.id, action: "run" } : it.actions.includes("on") ? { id: it.id, action: "on" } : null;
      }
      case "dimmer": {
        const a: ItemAction = it.actions.includes("toggle") ? "toggle" : (this.st?.on ? "off" : "on");
        // (1.3) "By hand" on the Light action too: a light that is a switch is taken over as a Control key's
        return this.settings.byHand === true && it.cap === "switch" ? { id: it.id, action: a, by_hand: true } : { id: it.id, action: a };
      }
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
    if (isNewKind(this.kind) && !looksOnly(this.kind) && it) {
      // a quick press - one that must be held needs the dial itself held down
      const cmd = this.notice() ? null : this.keyCommand();
      if (cmd && this.grantFor(cmd.id, cmd.action).allowed && this.holdFor(cmd)) return this.showToast("Hold the dial", "to confirm", "warn");
      this.pressStart(() => this.keyCommand());
      this.pressEnd();
      return;
    }
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
    if (isNewKind(this.kind)) return this.rotateNew(ticks);
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

  /** (1.3) A turn of a new action's dial: House power's span, the Timer's minutes, a Room's member, Heating's mode. */
  private rotateNew(ticks: number): void {
    if (this.notice() || !ticks) return;
    const it = this.item!;
    switch (this.kind) {
      case "power": {
        const L = POWER_SPANS as readonly number[];
        const i = Math.max(0, L.indexOf(this.span()));
        const next = L[Math.max(0, Math.min(L.length - 1, i + Math.sign(ticks)))]!;
        if (next !== this.span()) {
          this.spanTurned = next;
          this.hub.resubscribe();
        }
        break;
      }
      case "timer":
        this.minutesTurned = stepMinutes(this.minutes(), ticks);
        break;
      case "room": {
        const n = this.members().length;
        if (!n) return this.showToast("Nothing here", "no items in this room", "warn");
        this.memberAt = (((this.memberAt + ticks) % n) + n) % n;
        this.hub.resubscribe();
        break;
      }
      case "heatgroup": {
        const e = enumAttr(it, /^mode$/) ?? enumAttr(it, /mode/i);
        if (!it.actions.includes("set")) return this.showToast("Cannot adjust", "nothing to turn here", "warn");
        if (!it.allowed) return this.showToast("Not allowed", "grant it in ZIGMon", "crit");
        if (this.needsHold(it)) return this.showToast("Hold to confirm", "use the key / push", "warn");
        const values = e?.values.length ? e.values : [...ROOM_MODES];
        const st = this.st ?? it.state;
        const cur = strOf(st.attrs[e?.key ?? "mode"]);
        const i = values.indexOf(cur);
        const j = i < 0 ? (ticks > 0 ? ticks - 1 : values.length + ticks) : i + ticks;
        this.stepCycle(it.id, e?.key ?? "mode", values[((j % values.length) + values.length) % values.length]!);
        return;
      }
      default:
        return;
    }
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
  power: ["Using power", "Nothing on"], security: ["Alerts", "Quiet"], heatgroup: ["Heating", "Idle"], away: ["Away", "Home"], openings: ["Open", "Closed"],
  batteries: ["Low", "All OK"], zigbee: ["Offline", "All online"], timer: ["Running", "Idle"], room: ["Heating / on", "Quiet"], sms: ["Unread", "Read"],
};
const SMS_WORDS: Record<"last" | "compose" | "status", [string, string]> = { last: ["Unread", "Read"], compose: ["Pressed", "Ready"], status: ["Muted", "Listening"] };

/** (1.3) A Room member's push: switched, run or turned on, by its own actions - or nothing. */
function memberCommand(m: Item, st: ItemState): Omit<Command, "deck"> | null {
  if (m.actions.includes("toggle")) return { id: m.id, action: "toggle" };
  if (m.actions.includes("run")) return { id: m.id, action: "run" };
  if (m.actions.includes("on") && m.actions.includes("off")) return { id: m.id, action: st.on ? "off" : "on" };
  if (m.actions.includes("open") && m.actions.includes("close")) return { id: m.id, action: (st.value ?? 0) >= 50 ? "close" : "open" };
  return null;
}

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
    // (1.3) twenty more
    case "diagonal":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><path d="M 0 0 H 46 L 0 46 Z" fill="${lit ? c : P.panel2}"/>`);
    case "hex":
    case "bubble":
    case "ticket":
    case "tab":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/><rect x="4" y="4" width="192" height="92" rx="14" fill="${P.panel2}" stroke="${lit ? c : P.line}" stroke-width="2"/>`);
    case "stripe":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><rect width="8" height="100" fill="${lit ? c : P.panel2}"/>`);
    case "switch":
    case "line":
    case "stamp":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${theme === "line" ? X.night : P.bg}"/><rect x="0" y="97" width="200" height="3" fill="${lit ? c : P.line}"/>`);
    case "lcd":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.panel2}"/><rect x="4" y="4" width="192" height="92" rx="8" fill="${X.night}" stroke="${lit ? c : P.line}" stroke-width="2"/>`
        + (lit ? `<rect x="5" y="5" width="190" height="90" rx="7" fill="${c}" fill-opacity="0.12"/>` : ""));
    case "dial":
    case "spot":
    case "rise":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/>` + (lit ? `<ellipse cx="100" cy="${theme === "spot" ? 0 : 100}" rx="120" ry="50" fill="${c}" fill-opacity="0.16"/>` : ""));
    case "frame":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${X.night}"/><path d="M 4 24 V 4 H 24 M 176 4 H 196 V 24 M 196 76 V 96 H 176 M 24 96 H 4 V 76" fill="none" stroke="${lit ? c : P.muted}" stroke-width="${lit ? 4 : 2}"/>`);
    case "shadow":
    case "button":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><rect x="8" y="8" width="188" height="88" rx="14" fill="${lit ? c : P.line}"${lit ? ' fill-opacity="0.5"' : ""}/><rect x="4" y="4" width="188" height="88" rx="14" fill="${P.panel2}"/>`);
    case "tube":
    case "grid":
    case "carbon":
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.bg}"/><rect x="0" y="94" width="200" height="6" fill="${lit ? c : P.panel2}"/>`);
    case "pastel":
      // dark like the others: the strip's words keep their own (light) ink
      return svgDoc(200, 100, `<rect width="200" height="100" fill="${P.panel}"/><rect width="200" height="100" fill="${lit ? c : P.panel2}" fill-opacity="${lit ? 0.18 : 1}"/>`);
    default:
      return svgDoc(4, 4, "");
  }
}

function pressWord(a: ItemAction | null): string {
  const w: Record<string, string> = { toggle: "Toggle", on: "On", off: "Off", run: "Run", open: "Open", close: "Close", stop: "Stop", timer: "Timer" };
  return a ? w[a] ?? a : "";
}

function numOf(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function strOf(v: unknown): string {
  return typeof v === "string" ? v : typeof v === "number" || typeof v === "boolean" ? String(v) : "";
}
