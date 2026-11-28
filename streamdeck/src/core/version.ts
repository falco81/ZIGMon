/** The plugin's version; build.sh checks manifest.json and package.json say the same. */
export const PLUGIN_VERSION = "1.1.0";
export const PRODUCT = "ZIGMon for Stream Deck";
export const PLUGIN_UUID = "com.zigmon.streamdeck";
export const PACKAGE_FILE = "com.zigmon.streamdeck.streamDeckPlugin";

/** 1 to 4 plain numbers with dots; missing parts count as 0. null when it is not a version. */
export function parseVersion(v: unknown): number[] | null {
  if (typeof v !== "string" || v.length > 24 || !/^\d{1,9}(\.\d{1,9}){0,3}$/.test(v)) return null;
  const parts = v.split(".").map(Number);
  while (parts.length < 4) parts.push(0);
  return parts;
}

export function compareVersions(a: number[], b: number[]): number {
  for (let i = 0; i < 4; i++) if (a[i] !== b[i]) return a[i]! < b[i]! ? -1 : 1;
  return 0;
}

export function isNewer(candidate: unknown, than: string = PLUGIN_VERSION): boolean {
  const c = parseVersion(candidate), t = parseVersion(than);
  return c !== null && t !== null && compareVersions(c, t) > 0;
}
