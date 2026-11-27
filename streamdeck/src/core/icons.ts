/**
 * Stroke icons on a 24x24 grid, drawn like ZIGMon's dashboard (web/index.php ICONS and
 * windows/ZigmonNotifier.Core/KindStyle.cs Icons): stroke 1.7, round caps and joins, no fill.
 * Each is the inner markup of an <svg viewBox="0 0 24 24">; the caller sets the stroke.
 * Only plain path/circle/rect/line elements, which every SVG renderer (Stream Deck's too) draws.
 */
export const ICONS: Readonly<Record<string, string>> = {
  // ZIGMon's own mark: a sensor sending out its waves (the notifier's Radar)
  zigmon: '<circle cx="7" cy="17" r="1.6"/><path d="M7 11a6 6 0 0 1 6 6"/><path d="M7 6a11 11 0 0 1 11 11"/>',
  bulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.4 1.1 2.2v.5h5v-.5c0-.8.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>',
  bulbOn: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 6a4.5 4.5 0 0 0-2.7 8.1c.5.4.9 1.1.9 1.7v.2h3.6v-.2c0-.6.4-1.3.9-1.7A4.5 4.5 0 0 0 12 6z"/><path d="M12 1.8v1.4M4.6 4.6l1 1M19.4 4.6l-1 1M2.5 11h1.4M20.1 11h1.4"/>',
  plug: '<path d="M9 3v6M15 3v6"/><path d="M6 9h12v3a6 6 0 0 1-12 0z"/><path d="M12 18v3"/>',
  socket: '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><circle cx="12" cy="12" r="5"/><path d="M10 11.2v1.6M14 11.2v1.6"/>',
  switch: '<rect x="3" y="7" width="18" height="10" rx="5"/><circle cx="16" cy="12" r="2.6"/>',
  power: '<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  dimmer: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  thermo: '<path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
  thermostat: '<circle cx="12" cy="12" r="8.5"/><path d="M12 12l3.2-3.2"/><circle cx="12" cy="12" r="1.2"/><path d="M7.5 16.5h9"/>',
  flame: '<path d="M12 3c1 3.5 5 5.5 5 10.5a5 5 0 0 1-10 0c0-2.5 1.5-4 2.5-5 .3 1.8 1.2 2.8 2.5 3 0-3-1-5.5 0-8.5z"/>',
  snow: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5 12 6l2.5-1.5M9.5 19.5 12 18l2.5 1.5"/>',
  blinds: '<path d="M4 4h16"/><path d="M5 4v11h14V4"/><path d="M5 7.5h14M5 11h14"/><path d="M12 15v3"/><circle cx="12" cy="19.4" r="1.2"/>',
  blindsUp: '<path d="M4 4h16"/><path d="M5 4v4h14V4"/><path d="M12 20v-8"/><path d="M8.5 15.5 12 12l3.5 3.5"/>',
  blindsDown: '<path d="M4 4h16"/><path d="M5 4v4h14V4"/><path d="M12 11v9"/><path d="M8.5 16.5 12 20l3.5-3.5"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  scene: '<path d="M4 9h16v10a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19z"/><path d="M4 9 3.2 5.6 18.8 2l.8 3.4z"/><path d="M8.6 4.6l2.2 3M13.3 3.5l2.2 3"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M18.5 16v4M16.5 18h4"/>',
  sequence: '<path d="M4 7h11"/><path d="M12 4l3 3-3 3"/><path d="M20 17H9"/><path d="M12 14l-3 3 3 3"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  rule: '<path d="M4.5 17a8 8 0 1 1 15 0"/><path d="M12 14l3.5-5"/><circle cx="12" cy="14.5" r="1.2"/><path d="M6.8 10.2l1.1.7M12 6.5v1.3M17.2 10.2l-1.1.7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  message: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M12.5 15H17"/>',
  pulse: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  gauge: '<path d="M4.5 17a8 8 0 1 1 15 0"/><path d="M12 14l-3.5-4"/><circle cx="12" cy="14.5" r="1.2"/>',
  drop: '<path d="M12 3.5c3.5 4.2 6 7.6 6 10.5a6 6 0 0 1-12 0c0-2.9 2.5-6.3 6-10.5z"/><path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  battery: '<rect x="3" y="7" width="16" height="10" rx="2"/><path d="M21 10.5v3"/><path d="M6.5 10v4M9.5 10v4"/>',
  leaf: '<path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15"/><path d="M5 19l7-7"/>',
  wind: '<path d="M3 9h11a3 3 0 1 0-3-3"/><path d="M3 15h15a3 3 0 1 1-3 3"/>',
  motion: '<circle cx="8.5" cy="5" r="2"/><path d="M8.5 8 7.5 13l2.5 2.5.5 4.5M7.5 13l-2 7M5 11l3.2-2.5L11 11"/><path d="M15 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  door: '<path d="M14 3H6v18h8"/><path d="M14 3l4 2v14l-4 2z"/><circle cx="15.5" cy="12" r="1"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  shieldOk: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.6 12.2l2.4 2.4 4.4-4.8"/>',
  shieldAlert: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M12 8.5v4"/><path d="M12 15.8h.01"/>',
  wall: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.3h18M3 14.7h18"/><path d="M9 4v5.3M15 9.3v5.4M9 14.7V20"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z"/>',
  router: '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 16.5h.01M11 16.5h.01"/><path d="M8 7l3 3 5-6"/>',
  heart: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.3 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/><path d="M7 12.5h2.5l1.2-2 2 4 1.3-2H17"/>',
  alert: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5"/><path d="M12 17.2h.01"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  unlock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
  key: '<circle cx="8" cy="12" r="3.2"/><path d="M11.2 12H21"/><path d="M17 12v3"/><path d="M20 12v2.4"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  unlink: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/><path d="M3 3l18 18"/>',
  wifi: '<path d="M2 8.5a16 16 0 0 1 20 0"/><path d="M5 12a11 11 0 0 1 14 0"/><path d="M8.5 15.5a6 6 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/>',
  wifiOff: '<path d="M5 12a11 11 0 0 1 6-2.9M15.5 10a11 11 0 0 1 3.5 2"/><path d="M8.5 15.5a6 6 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/><path d="M3 3l18 18"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  hand: '<path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11"/><path d="M12 11V4.5a1.5 1.5 0 0 1 3 0V11"/><path d="M15 11V6.5a1.5 1.5 0 0 1 3 0V13c0 4-2.5 7-6 7s-6-2.5-6-6v-3a1.5 1.5 0 0 1 3 0"/>',
  hourglass: '<path d="M7 3h10M7 21h10"/><path d="M8 3c0 5 8 5 8 9s-8 4-8 9"/><path d="M16 3c0 5-8 5-8 9s8 4 8 9"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v5h-5"/>',
  download: '<path d="M12 4v12"/><path d="M7 11l5 5 5-5"/><path d="M4 20h16"/>',
  up: '<path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>',
  down: '<path d="M12 5v14"/><path d="M19 12l-7 7-7-7"/>',
  trendUp: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  trendDown: '<path d="M3 7l6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
  trendFlat: '<path d="M3 12h16"/><path d="M15 8l4 4-4 4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  home: '<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5h4v5"/>',
  person: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.6 3.1-5.5 7-5.5s7 1.9 7 5.5"/>',
  deck: '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M6 9h2M11 9h2M16 9h2M6 12.5h2M11 12.5h2M16 12.5h2"/><path d="M7 16h10"/>',
  dial: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 3.5v3"/>',
  fan: '<circle cx="12" cy="12" r="1.6"/><path d="M12 10.4C11 7 12 3.5 15 3.5c2.5 0 2.5 3.5-1.6 7"/><path d="M13.6 12.6c3.4-.6 6.9 1 6.4 3.9-.4 2.4-3.7 1.8-6.6-1.5"/><path d="M10.6 13c-1.9 2.9-5.3 4.6-6.9 2.1-1.3-2.1 1.7-3.8 5.9-3.6"/>',
  window: '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M12 3v18M4 12h16"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  sensor: '<circle cx="12" cy="12" r="2.2"/><path d="M8 8a5.6 5.6 0 0 0 0 8M16 8a5.6 5.6 0 0 1 0 8M5 5a9.9 9.9 0 0 0 0 14M19 5a9.9 9.9 0 0 1 0 14"/>',
};

/** The dashboard's icon names (and a few others ZIGMon may send) mapped onto ours. */
const ALIASES: Readonly<Record<string, string>> = {
  light: "bulb", lamp: "bulb", lightbulb: "bulb", led: "bulb",
  outlet: "socket", relay: "switch", toggle: "switch",
  heat: "thermostat", heating: "thermostat", trv: "thermostat", climate: "thermostat",
  temp: "thermo", temperature: "thermo",
  cover: "blinds", shutter: "blinds", curtain: "blinds", blind: "blinds",
  seq: "sequence", group: "layers", agroup: "layers", sgroup: "layers", binding: "link",
  schedule: "clock", sched: "clock", timer: "clock",
  sms: "message", notify: "bell", tell: "message", mail: "message",
  system: "gear", sys: "gear", settings: "gear", reboot: "refresh", reset: "refresh",
  reading: "gauge", meter: "gauge", humidity: "drop", water: "drop", leak: "drop",
  energy: "bolt", power_meter: "bolt", zb: "bolt",
  contact: "door", smoke: "flame", gas: "flame", co: "alert", vibration: "pulse",
  button: "hand", status: "heart", health: "heart", alerts: "bell", blocked: "wall",
  proxy: "globe", sslproxy: "shield", gateway: "router", net: "router", selinux: "shieldOk",
  house: "home", room: "door", people: "person", presence: "person", warn: "alert", crit: "alert",
};

/** The markup of an icon by any name ZIGMon or the plugin uses; an unknown name is the fallback. */
export function iconMarkup(name: string | null | undefined, fallback = "sensor"): string {
  const n = String(name ?? "").trim();
  if (Object.prototype.hasOwnProperty.call(ICONS, n)) return ICONS[n]!;
  const lower = n.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(ICONS, lower)) return ICONS[lower]!;
  const alias = ALIASES[lower];
  if (alias && ICONS[alias]) return ICONS[alias]!;
  return ICONS[fallback] ?? ICONS.sensor!;
}

export function hasIcon(name: string): boolean {
  return Object.prototype.hasOwnProperty.call(ICONS, name) || Object.prototype.hasOwnProperty.call(ALIASES, name.toLowerCase());
}
