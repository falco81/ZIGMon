/**
 * (1.3, ZIGMon 5.59.4) What the ten new actions have to say, worked out once from an item's state
 * and the key's settings: a Summary. The Classic drawing (extra-render.ts), every other look (a
 * Face, themes.ts), the touch strip and the property inspector's "Now" rows are all made from it,
 * so they say the same thing in the same words. Server text is only ever text here; colours come
 * from palette.ts or the user's own settings.
 */
import { countdown, minutesWord, spanWord, type NewKind } from "./kinds.js";
import { P, X, A } from "./palette.js";
import type { AttrValue, Item, ItemState } from "./protocol.js";
import type { Face } from "./themes.js";

export interface Member {
  item: Item;
  state: ItemState;
  index: number;
  count: number;
}

/** Everything a summary is made from. */
export interface ExtraCtx {
  kind: NewKind;
  it: Item;
  st: ItemState;
  label: string;
  /** The On / Off colours the user chose (undefined: Auto). */
  accent?: string;
  offAccent?: string;
  /** The inspector's lit / unlit previews. */
  forced: "on" | "off" | null;
  /** Unix seconds now. */
  now: number;
  /** House power: the graph's values and its span. */
  series: number[];
  span: number;
  /** Hold and grant of what a press does (an `act` grant where there is one). */
  hold: boolean;
  allowed: boolean;
  /** Timer: the minutes a press starts, and the length of the timer running (seconds) when known. */
  minutes: number;
  total: number | null;
  /** Heating: the mode stepped to and not yet sent. */
  cycle: string | null;
  /** Room on a dial: the member scrolled to. */
  member: Member | null;
  /** SMS, Write new: whom to. */
  to: string[];
  /** SMS status: the hush a press sets. */
  muteMinutes: number;
}

export type Tone = "ok" | "warn" | "crit" | "info" | "idle";

export interface Summary {
  kind: NewKind;
  name: string;
  room: string | null;
  icon: string;
  /** The colour it is drawn in when lit (the user's On colour, else its own). */
  accent: string;
  tone: Tone;
  active: boolean;
  online: boolean;
  /** The big words and their unit. */
  state: string;
  unit: string;
  /** A colour the big words must have (all good in green); null: the look's own. */
  stateColour: string | null;
  detail: string;
  mode: string;
  level: number | null;
  series: number[];
  hold: boolean;
  allowed: boolean;
  battery: number | null;
  taken: boolean;
  /** An unread count, drawn as a badge. */
  badge: number | null;
  offAccent: string | null;
  /** Per kind: the pieces its own Classic drawing and strip use. */
  x: Record<string, number | string | boolean | null | string[]>;
}

// ------------------------------------------------------------------ small readers

export const numOf = (v: AttrValue | undefined): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const strOf = (v: AttrValue | undefined): string => (typeof v === "string" ? v : "");
export const listOf = (v: AttrValue | undefined): string[] => (Array.isArray(v) ? v : []);
const intOf = (v: AttrValue | undefined): number => Math.max(0, Math.round(numOf(v) ?? 0));

/** "14:30" on this computer's clock. */
export function hhmm(unix: number): string {
  const d = new Date(unix * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

/** "14:30" today, "Mon 14:30" this week, else "3 Nov". */
export function when(unix: number | null, now: number): string {
  if (unix === null || unix <= 0) return "";
  const d = new Date(unix * 1000), n = new Date(now * 1000);
  if (d.toDateString() === n.toDateString()) return hhmm(unix);
  if (now - unix < 6 * 86400 && now >= unix) return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()] + " " + hhmm(unix);
  return d.getDate() + " " + ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
}

/** The house's watts as the key says them: "45.2" W, "452" W, "1.84" kW, "12.3" kW. */
export function fmtPower(w: number | null): { num: string; unit: string } {
  if (w === null) return { num: "—", unit: "" };
  const a = Math.abs(w);
  if (a < 10) return { num: (Math.round(w * 10) / 10).toFixed(1), unit: "W" };
  if (a < 1000) return { num: String(Math.round(w)), unit: "W" };
  if (a < 10000) return { num: (w / 1000).toFixed(2), unit: "kW" };
  return { num: (w / 1000).toFixed(1), unit: "kW" };
}

export function fmtDeg(v: number | null): string {
  return v === null ? "—" : (Math.round(v * 10) / 10).toFixed(1);
}

export const MODE_WORD: Readonly<Record<string, string>> = {
  plan: "Plan", comfort: "Comfort", eco: "Eco", night: "Night", max: "Max", off: "Off", manual: "By hand", mixed: "Mixed",
};

/** A recipient as the key and the inspector name it: "Family" for group:Family, "…456" for a number. */
export function recipientWord(r: string): string {
  if (r.startsWith("group:")) return r.slice(6);
  if (r.startsWith("contact:")) return "contact";
  return "…" + r.replace(/\D/g, "").slice(-3);
}

// ------------------------------------------------------------------ the summaries

export function summaryOf(c: ExtraCtx): Summary {
  const s = summaryRaw(c);
  // all good is said in green - unless the user chose an Off colour, which then wins
  return !s.active && s.offAccent && s.stateColour === P.ok ? { ...s, stateColour: null } : s;
}

function summaryRaw(c: ExtraCtx): Summary {
  const { it, st } = c;
  const a = st.attrs;
  const f = c.forced;
  const base: Summary = {
    kind: c.kind, name: c.label, room: it.room, icon: "sensor", accent: c.accent ?? P.info, tone: "idle", active: false,
    online: f ? true : st.online, state: "", unit: "", stateColour: null, detail: "", mode: "", level: null, series: [], hold: c.hold,
    allowed: c.allowed, battery: st.battery, taken: st.held === true, badge: null, offAccent: c.offAccent ?? null, x: {},
  };
  switch (c.kind) {
    case "power": {
      const w = f === "off" ? 0 : st.value ?? numOf(a.power);
      const p = fmtPower(w);
      const kwh = numOf(a.kwh_today);
      const on = f ? f === "on" : (w ?? 0) > 0;
      return {
        ...base, room: null, icon: "bolt", accent: c.accent ?? P.warn, tone: on ? "info" : "idle", active: on && base.online, state: p.num, unit: p.unit,
        detail: kwh !== null ? (kwh >= 100 ? Math.round(kwh) : Math.round(kwh * 10) / 10).toString() + " kWh today" : "", mode: spanWord(c.span),
        series: c.series, level: levelOfSeries(c.series),
        x: { kwh, socketsW: numOf(a.sockets_w), lightsW: numOf(a.lights_w), socketsOn: numOf(a.sockets_on), lightsOn: numOf(a.lights_on), span: spanWord(c.span) },
      };
    }
    case "security": {
      const alerts = f ? (f === "on" ? 2 : 0) : intOf(a.alerts ?? st.value);
      const blocked = numOf(a.blocked), b24 = numOf(a.blocked_24h);
      const lit = alerts > 0;
      const guard = a.guarding !== false;
      const det = [blocked !== null ? blocked + " blocked" : "", b24 !== null && b24 > 0 ? b24 + " in 24 h" : ""].filter(Boolean).join(" · ");
      return {
        ...base, room: null, icon: lit ? "shieldAlert" : "shieldOk", accent: c.accent ?? P.crit, tone: lit ? "crit" : "ok", active: lit && base.online,
        state: lit ? String(alerts) : "Quiet", unit: lit ? (alerts === 1 ? "alert" : "alerts") : "", stateColour: lit ? null : P.ok,
        detail: guard ? det || "nothing blocked" : "guard off", mode: lit && numOf(a.alerts_24h) ? intOf(a.alerts_24h) + " new today" : "",
        x: { alerts, blocked, blocked24: b24, guarding: guard, latest: strOf(a.latest), latestAt: numOf(a.latest_at) },
      };
    }
    case "heatgroup": {
      const rooms = intOf(a.rooms), calling = f ? (f === "on" ? Math.max(1, Math.ceil(rooms / 2)) : 0) : intOf(a.calling);
      const mode = c.cycle ?? (strOf(a.mode) || strOf(st.value as AttrValue) || st.valueText || "mixed");
      const lo = numOf(a.min_temperature), hi = numOf(a.max_temperature);
      const lit = calling > 0;
      const range = lo !== null && hi !== null ? (Math.abs(hi - lo) < 0.05 ? fmtDeg(lo) + "°" : fmtDeg(lo) + "–" + fmtDeg(hi) + "°") : lo !== null ? fmtDeg(lo) + "°" : "";
      return {
        ...base, room: null, icon: lit ? "flame" : "thermostat", accent: c.accent ?? P.orange, tone: lit ? "info" : "idle", active: lit && base.online,
        state: rooms ? calling + "/" + rooms : "—", unit: "", detail: range, mode: MODE_WORD[mode] ?? mode, level: rooms ? calling / rooms : null,
        x: { rooms, calling, mode, lo, hi, pending: c.cycle !== null },
      };
    }
    case "away": {
      const away = f ? f === "on" : a.away === true || (a.away === undefined && st.on === true);
      const byDates = !away && a.away_now === true;
      const lights = intOf(a.lights_on), sockets = intOf(a.sockets_on), heating = intOf(a.rooms_heating);
      const det = [lights + (lights === 1 ? " light on" : " lights on"), heating ? heating + " heating" : ""].filter(Boolean).join(" · ");
      return {
        ...base, room: null, icon: away || byDates ? "suitcase" : "home", accent: c.accent ?? A.indigo, tone: away ? "info" : "ok", active: (away || byDates) && base.online,
        state: away || byDates ? "Away" : "Home", unit: "", stateColour: away || byDates ? null : P.ok, detail: det, mode: byDates ? "by the dates" : "",
        x: { away, byDates, lights, sockets, heating },
      };
    }
    case "openings": {
      const open = f ? (f === "on" ? 1 : 0) : intOf(a.open ?? st.value);
      const sensors = intOf(a.sensors);
      const names = f === "on" ? ["Window"] : f === "off" ? [] : listOf(a.names);
      const loss = f ? false : a.heating_loss === true;
      const lit = open > 0;
      return {
        ...base, room: null, icon: lit ? "windowOpen" : "window", accent: loss ? P.crit : c.accent ?? P.warn, tone: loss ? "crit" : lit ? "warn" : "ok", active: lit && base.online,
        state: lit ? String(open) : "Closed", unit: lit ? "open" : "", stateColour: lit ? (loss ? P.crit : null) : P.ok,
        detail: lit ? names.slice(0, 2).join(", ") + (open > 2 ? " +" + (open - 2) : "") : sensors ? sensors + (sensors === 1 ? " sensor" : " sensors") : "",
        mode: loss ? "heat escaping" : "", level: sensors ? open / sensors : null,
        x: { open, sensors, names, loss },
      };
    }
    case "batteries": {
      const low = f ? (f === "on" ? 2 : 0) : intOf(a.below_20);
      const crit = f ? f === "on" : intOf(a.below_10) > 0 || strOf(a.level) === "crit";
      const pct = f === "off" ? 100 : f === "on" ? 5 : numOf(a.lowest_pct) ?? st.value;
      const who = f ? (f === "on" ? "Door sensor" : "") : strOf(a.lowest_name);
      const lit = low > 0;
      const tone: Tone = !lit ? "ok" : crit ? "crit" : "warn";
      return {
        ...base, room: null, icon: lit ? "batteryLow" : "battery", accent: c.accent ?? (crit ? P.crit : P.warn), tone, active: lit && base.online,
        state: lit ? String(low) : "All OK", unit: lit ? "low" : "", stateColour: lit ? null : P.ok,
        detail: who && pct !== null ? who + " " + Math.round(pct) + " %" : "", level: pct !== null ? Math.max(0, Math.min(1, pct / 100)) : null,
        x: { low, crit, pct, who, below10: intOf(a.below_10) },
      };
    }
    case "zigbee": {
      const on = f ? 12 : intOf(a.online_n ?? st.value), off = f ? (f === "on" ? 1 : 0) : intOf(a.offline_n);
      const who = f ? (f === "on" ? "Radiator head" : "") : strOf(a.dropped_name);
      const at = f ? null : numOf(a.dropped_at);
      const lit = off > 0;
      return {
        ...base, room: null, icon: "mesh", accent: c.accent ?? P.warn, tone: lit ? "warn" : "ok", active: lit && base.online,
        state: lit ? String(off) : String(on), unit: lit ? "offline" : "online", stateColour: lit ? null : P.ok,
        detail: who ? (lit ? who + " dropped" : "last: " + who) + (at ? " " + when(at, c.now) : "") : "", level: on + off ? on / (on + off) : null,
        x: { online: on, offline: off, who, at },
      };
    }
    case "timer": {
      const offAt = numOf(a.off_at);
      const left = offAt !== null ? offAt - c.now : 0;
      const forcedRun = f === "on";
      const running = forcedRun || (offAt !== null && left > 0 && st.on !== false);
      const total = forcedRun ? c.minutes * 60 : Math.max(left, c.total ?? c.minutes * 60);
      const rem = forcedRun ? total * 0.62 : left;
      const swOn = f ? f === "on" : st.on === true;
      return {
        ...base, icon: "stopwatch", accent: c.accent ?? P.water, tone: running ? "info" : "idle", active: running && base.online,
        state: running ? countdown(rem) : String(c.minutes), unit: running ? "" : "min",
        detail: running ? "off at " + hhmm(Math.round(c.now + rem)) : swOn ? "on now" : "off now", mode: running ? minutesWord(Math.round(total / 60)) : "",
        level: running ? Math.max(0, Math.min(1, rem / Math.max(1, total))) : null,
        x: { running, rem, total, minutes: c.minutes, swOn, offAt },
      };
    }
    case "room": {
      const t = f ? 21.5 : numOf(a.temperature) ?? st.value;
      const h = f ? 48 : numOf(a.humidity);
      const sOn = intOf(a.switches_on), sAll = intOf(a.switches), lOn = intOf(a.lights_on), lAll = intOf(a.lights);
      const heated = a.heated === true, mode = strOf(a.heat_mode), target = numOf(a.heat_target);
      const calling = f ? f === "on" : a.calling === true;
      const anyOn = f ? f === "on" : st.on === true;
      const det = [h !== null ? Math.round(h) + " %" : "", sAll ? sOn + "/" + sAll + " on" : ""].filter(Boolean).join(" · ");
      const hm = heated || f ? [MODE_WORD[mode] ?? (mode || (f ? "Comfort" : "")), target !== null ? "→ " + (Number.isInteger(target) ? target : fmtDeg(target)) + "°" : f ? "→ 21°" : ""].filter(Boolean).join(" ") : "";
      return {
        ...base, room: null, icon: calling ? "flame" : "sofa", accent: c.accent ?? (calling ? P.orange : P.info), tone: calling ? "info" : "idle", active: (calling || anyOn) && base.online,
        state: fmtDeg(t), unit: t !== null ? "°C" : "", detail: det, mode: hm,
        x: { t, h, sOn, sAll, lOn, lAll, heated, mode, target, calling, anyOn, members: intOf(a.members_n) },
      };
    }
    case "sms":
      return smsSummary(c, base);
  }
}

function smsSummary(c: ExtraCtx, base: Summary): Summary {
  const { it, st } = c;
  const a = st.attrs;
  const f = c.forced;
  const unread = f === "on" ? 2 : f === "off" ? 0 : intOf(a.unread);
  const today = f ? 3 : intOf(a.today ?? st.value);
  const from = f ? "…123" : strOf(a.last_person) || strOf(a.last_from);
  const at = f ? null : numOf(a.last_at);
  const fromLine = from ? from + (at ? " · " + when(at, c.now) : "") : today ? "" : "nothing yet";
  if (it.id === "status:sms") {
    const muted = f ? f === "on" : (numOf(a.muted_until) ?? 0) > c.now;
    const until = numOf(a.muted_until);
    const modemDown = !f && (a.modem_online === false || strOf(a.level) === "crit");
    return {
      ...base, room: null, icon: muted ? "bellOff" : "message", accent: c.accent ?? A.indigo, tone: modemDown ? "crit" : muted ? "info" : "ok", active: muted && base.online,
      state: muted ? "Muted" : String(today), unit: muted ? "" : "today", stateColour: modemDown ? P.crit : null,
      detail: muted ? (until ? "until " + hhmm(until) : "for a while") : modemDown ? "modem offline" : fromLine, mode: "",
      x: { mode: "status", muted, until, today, from, at, modemDown, text: f ? "" : strOf(a.last_text) },
    };
  }
  if (it.id === "sms:compose") {
    const to = c.to.map(recipientWord);
    return {
      ...base, room: null, icon: "send", accent: c.accent ?? P.info, tone: "info", active: unread > 0 && base.online, state: "Write", unit: "",
      detail: to.length ? "to " + to.join(", ") : "to anyone", mode: unread ? unread + " unread" : "", badge: unread || null,
      x: { mode: "compose", to, unread, today },
    };
  }
  return {
    ...base, room: null, icon: unread ? "inbox" : "message", accent: c.accent ?? P.info, tone: unread ? "info" : "idle", active: unread > 0 && base.online,
    state: String(today), unit: "today", detail: fromLine, mode: unread ? unread + " unread" : "", badge: unread || null,
    x: { mode: "last", unread, today, from, at },
  };
}

function levelOfSeries(v: number[]): number | null {
  const s = v.filter((x) => Number.isFinite(x));
  if (s.length < 2) return null;
  const hi = Math.max(...s);
  return hi > 0 ? Math.max(0, Math.min(1, s[s.length - 1]! / hi)) : 0;
}

// ------------------------------------------------------------------ for the other looks

/** A long unit word as the 41 other looks say it beside a giant number (Classic keeps the word). */
const SHORT_UNIT: Readonly<Record<string, string>> = { alerts: "", alert: "", today: "", offline: "off", online: "on" };

/** A summary as the 41 looks other than Classic draw it. */
export function faceOfSummary(s: Summary): Face {
  // the looks draw a unit beside the big words at almost half their size: only a short one fits there
  const unit = SHORT_UNIT[s.unit] ?? s.unit;
  return {
    kind: s.kind, name: s.name, room: s.room, icon: s.icon, accent: s.accent, active: s.active, state: s.state, unit,
    stateColour: s.stateColour, detail: s.detail, mode: s.mode, level: s.level, series: s.series, target: null, online: s.online,
    allowed: s.allowed, hold: s.hold, battery: s.battery, taken: s.taken, offAccent: s.offAccent, badge: s.badge,
  };
}

// ------------------------------------------------------------------ the property inspector's "Now"

/** What the inspector shows of the item now: every name, the whole latest alert, the room's members. */
export function factsOf(c: ExtraCtx, s: Summary, members: Item[] = []): [string, string][] {
  const a = c.st.attrs;
  const rows: [string, string][] = [];
  const add = (k: string, v: string | number | null | undefined) => {
    if (v !== null && v !== undefined && String(v) !== "") rows.push([k, String(v)]);
  };
  switch (c.kind) {
    case "power":
      add("Now", s.state + (s.unit ? " " + s.unit : ""));
      add("Today", s.x.kwh !== null ? s.x.kwh + " kWh" : "not counted yet");
      add("Sockets", s.x.socketsW !== null ? s.x.socketsW + " W" + (s.x.socketsOn !== null ? " · " + s.x.socketsOn + " on" : "") : null);
      add("Lights", s.x.lightsW !== null ? s.x.lightsW + " W" + (s.x.lightsOn !== null ? " · " + s.x.lightsOn + " on" : "") : null);
      break;
    case "security":
      add("Alerts standing", String(s.x.alerts) + (numOf(a.alerts_24h) !== null ? " (" + intOf(a.alerts_24h) + " in 24 h)" : ""));
      add("Latest alert", (s.x.latest as string) || "none");
      add("Raised", when(s.x.latestAt as number | null, c.now));
      add("Blocked now", s.x.blocked as number | null);
      add("Blocked in 24 h", s.x.blocked24 as number | null);
      add("Guard", s.x.guarding ? "on" : "off");
      break;
    case "heatgroup":
      add("Mode", s.mode);
      add("Rooms heating", s.state);
      add("Temperatures", s.detail ? s.detail.replace(/°$/, " °C") : null);
      break;
    case "away":
      add("Now", s.state + (s.mode ? " (" + s.mode + ")" : ""));
      add("Lights on", s.x.lights as number);
      add("Sockets on", s.x.sockets as number);
      add("Rooms heating", s.x.heating as number);
      break;
    case "openings":
      add("Open", String(s.x.open) + (s.x.sensors ? " of " + s.x.sensors : ""));
      for (const n of s.x.names as string[]) add("·", n);
      if (s.x.loss) add("Heating", "an open one is in a room calling for heat");
      break;
    case "batteries":
      add("Below 20 %", s.x.low as number);
      add("Below 10 %", s.x.below10 as number);
      add("Lowest", s.detail || null);
      break;
    case "zigbee":
      add("Online", s.x.online as number);
      add("Offline", s.x.offline as number);
      add("Last dropped", s.x.who ? s.x.who + (s.x.at ? " · " + when(s.x.at as number, c.now) : "") : null);
      break;
    case "timer":
      add("Switch", s.x.swOn ? "on" : "off");
      add("Timer", s.x.running ? countdown(s.x.rem as number) + " left · " + s.detail : "none running");
      add("A press", s.x.running ? "cancels it (off)" : "on for " + minutesWord(c.minutes));
      break;
    case "room": {
      add("Temperature", s.state !== "—" ? s.state + " °C" : null);
      add("Humidity", s.x.h !== null ? Math.round(s.x.h as number) + " %" : null);
      add("Switches on", s.x.sAll ? s.x.sOn + " of " + s.x.sAll : null);
      add("Lights on", s.x.lAll ? s.x.lOn + " of " + s.x.lAll : null);
      add("Heating", s.mode || null);
      for (const m of members.slice(0, 40)) add("·", m.name);
      break;
    }
    case "sms":
      if (s.x.mode === "status") {
        add("Today", s.x.today as number);
        add("Latest from", (s.x.from as string) || null);
        add("Latest", (s.x.text as string) || null);
        add("Modem", s.x.modemDown ? "offline" : "online");
        add("Alerts", s.x.muted ? "hushed " + s.detail : "not hushed");
      } else if (s.x.mode === "compose") {
        add("To", (s.x.to as string[]).length ? (s.x.to as string[]).join(", ") : "anyone - chosen in the desktop app");
        add("Unread", s.x.unread as number);
      } else {
        add("Today", s.x.today as number);
        add("Latest from", (s.x.from as string) || null);
        add("Unread", s.x.unread as number);
      }
      break;
  }
  return rows.slice(0, 48);
}

export { X };
