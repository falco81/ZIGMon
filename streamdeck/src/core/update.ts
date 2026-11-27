import { createHash, createPublicKey, verify, type KeyObject } from "node:crypto";
import type { UpdateAnswer } from "./protocol.js";
import { RELEASE_KEYS } from "./release-keys.generated.js";
import { compareVersions, PACKAGE_FILE, parseVersion, PLUGIN_VERSION, PRODUCT } from "./version.js";

/** An update that is not installed, with words fit to show (never anything secret). */
export class UpdateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UpdateError";
  }
}

export interface ReleaseKey {
  name: string;
  key: KeyObject;
}

export interface PluginManifest {
  product: string;
  file: string;
  version: string;
  size: number;
  sha256: string;
  requires: string;
}

export interface VerifiedUpdate {
  manifest: PluginManifest;
  keyName: string;
}

export const MAX_PACKAGE_BYTES = 50 * 1024 * 1024;
export const MAX_MANIFEST_BYTES = 4096;
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

/** A raw 32-byte Ed25519 public key as a Node key object. */
export function rawKey(hex: string): KeyObject {
  const raw = Buffer.from(hex, "hex");
  if (raw.length !== 32) throw new UpdateError("a release key is not 32 bytes");
  return createPublicKey({ key: Buffer.concat([ED25519_SPKI_PREFIX, raw]), format: "der", type: "spki" });
}

export function embeddedKeys(): ReleaseKey[] {
  return RELEASE_KEYS.map((k) => ({ name: k.name, key: rawKey(k.hex) }));
}

/** plugin.json, strictly: an object, string product/file/version/sha256/requires, an integer size, no key twice. */
export function parseManifest(bytes: Buffer): PluginManifest {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new UpdateError("the update's manifest is not text");
  }
  // JSON.parse keeps the last of a repeated key silently: refuse repeats outright
  const keys = [...text.matchAll(/"((?:[^"\\]|\\.)*)"\s*:/g)].map((m) => m[1]);
  if (new Set(keys).size !== keys.length) throw new UpdateError("the update's manifest names a key twice");
  let o: unknown;
  try {
    o = JSON.parse(text);
  } catch {
    throw new UpdateError("the update's manifest is not valid JSON");
  }
  if (o === null || typeof o !== "object" || Array.isArray(o)) throw new UpdateError("the update's manifest is not an object");
  const m = o as Record<string, unknown>;
  const s = (k: string): string => {
    if (typeof m[k] !== "string") throw new UpdateError("the update's manifest has no " + k);
    return m[k] as string;
  };
  if (typeof m.size !== "number" || !Number.isSafeInteger(m.size)) throw new UpdateError("the update's manifest has no size");
  return { product: s("product"), file: s("file"), version: s("version"), size: m.size, sha256: s("sha256"), requires: typeof m.requires === "string" ? m.requires : "" };
}

/**
 * Checks an offer: the Ed25519 signature over the manifest's exact bytes by one of the release
 * keys FIRST, then every field of the signed manifest against what was advertised.
 */
export function verifyOffer(offer: UpdateAnswer, keys: ReleaseKey[], mustBeNewerThan: string | null = PLUGIN_VERSION): VerifiedUpdate {
  if (!offer.available) throw new UpdateError("no update is offered");
  if (offer.manifest.length === 0 || offer.manifest.length > MAX_MANIFEST_BYTES) throw new UpdateError("the update's manifest is missing or too big");
  if (offer.sig.length !== 64) throw new UpdateError("the update's signature is malformed");
  if (keys.length === 0) throw new UpdateError("this build has no release key to check updates with");
  const by = keys.find((k) => {
    try {
      return verify(null, offer.manifest, k.key, offer.sig);
    } catch {
      return false;
    }
  });
  if (!by) throw new UpdateError("the update is not signed by ZIGMon's release key");

  const m = parseManifest(offer.manifest);
  if (m.product !== PRODUCT) throw new UpdateError("the update is for another product");
  if (m.file !== PACKAGE_FILE) throw new UpdateError("the update is not " + PACKAGE_FILE);
  const v = parseVersion(m.version);
  if (!v) throw new UpdateError("the update's version is not a version");
  const adv = parseVersion(offer.version);
  if (!adv || compareVersions(adv, v) !== 0) throw new UpdateError("the update's signed version is not the one advertised");
  if (mustBeNewerThan !== null && compareVersions(v, parseVersion(mustBeNewerThan)!) <= 0) {
    throw new UpdateError("the update (" + m.version + ") is not newer than this plugin");
  }
  if (m.size <= 0 || m.size > MAX_PACKAGE_BYTES) throw new UpdateError("the update's size is not believable");
  if (m.size !== offer.size) throw new UpdateError("the update's signed size is not the one advertised");
  if (!/^[0-9a-f]{64}$/.test(m.sha256)) throw new UpdateError("the update's checksum is malformed");
  if (m.sha256 !== offer.sha256) throw new UpdateError("the update's signed checksum is not the one advertised");
  return { manifest: m, keyName: by.name };
}

/** The downloaded package must be exactly what the signed manifest says. */
export function checkPackage(bytes: Buffer, v: VerifiedUpdate): void {
  if (bytes.length !== v.manifest.size) throw new UpdateError("the download is not the size the signed manifest says");
  const sha = createHash("sha256").update(bytes).digest("hex");
  if (sha !== v.manifest.sha256) throw new UpdateError("the download's checksum does not match the signed manifest");
  // a .streamDeckPlugin is a zip
  if (bytes.length < 4 || bytes.readUInt32LE(0) !== 0x04034b50) throw new UpdateError("the download is not a Stream Deck plugin package");
}

/** %TEMP%\ZIGMon-<ver>.streamDeckPlugin - the version is digits and dots only (checked above). */
export function packageFileName(version: string): string {
  if (!parseVersion(version)) throw new UpdateError("the update's version is not a version");
  return "ZIGMon-" + version + ".streamDeckPlugin";
}
