/**
 * (1.3, windows/PROTOCOL-SMS.md 3) ZIGMon's address book as the deck sees it - `sms_contacts`
 * (id, name, group, favourite; never a number) and `sms_groups` of the extended catalogue - parsed
 * strictly, and the few pure pieces of the SMS key's recipient picker (what a chosen entry is
 * called, the search, the typed number). Imports nothing: the plugin and the inspector share it.
 */

export interface SmsContact {
  id: string;
  name: string;
  group: string | null;
  favourite: boolean;
}

export interface SmsBook {
  contacts: SmsContact[];
  groups: string[];
}

export const SMS_CONTACTS_MOST = 500;
export const SMS_GROUPS_MOST = 500;
/** How many recipients one key may name. */
export const SMS_TO_MOST = 20;
/** A contact's id as ZIGMon makes it; anything else is not a contact. */
export const CONTACT_ID_RE = /^c_[0-9a-f]{6,12}$/;
export const GROUP_MOST = 40;

const CONTROL = /[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿￹-￻]/g;

/** A contact's name for showing: no control or direction characters, spaces folded, at most 60 characters. */
function cleanName(v: unknown): string {
  if (typeof v !== "string") return "";
  let s = v.replace(CONTROL, " ").replace(/\s+/g, " ").trim();
  if ([...s].length > 60) s = [...s].slice(0, 59).join("").trimEnd() + "…";
  return s;
}

/**
 * A group's name exactly as ZIGMon has it, or null. It goes back as `group:<name>`, so it is never
 * shortened: one empty, longer than 40 characters, with control characters or with , ; < > " is dropped.
 */
export function smsGroupName(v: unknown): string | null {
  if (typeof v !== "string") return null;
  if (new RegExp(CONTROL.source).test(v) || /[,;<>"]/.test(v)) return null;
  const t = v.replace(/\s+/g, " ").trim();
  return t && [...t].length <= GROUP_MOST ? t : null;
}

/**
 * `sms_contacts` and `sms_groups` of the extended catalogue, strictly: null when `sms_contacts` is
 * absent or not a list (no cap `sms`, or an older ZIGMon). At most 500 contacts; one without a proper
 * id or name, or seen before, is left out; a bad group is dropped (from the contact too). Without a
 * proper `sms_groups`: the groups the contacts name, alphabetically.
 */
export function parseSmsBook(o: Record<string, unknown>): SmsBook | null {
  if (!Array.isArray(o.sms_contacts)) return null;
  const contacts: SmsContact[] = [];
  const seen = new Set<string>();
  for (const raw of o.sms_contacts.slice(0, SMS_CONTACTS_MOST)) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const c = raw as Record<string, unknown>;
    if (typeof c.id !== "string" || !CONTACT_ID_RE.test(c.id) || seen.has(c.id)) continue;
    const name = cleanName(c.name);
    if (!name) continue;
    seen.add(c.id);
    contacts.push({ id: c.id, name, group: smsGroupName(c.group), favourite: c.favourite === true });
  }
  const listed = Array.isArray(o.sms_groups);
  const groups: string[] = [];
  const lower = new Set<string>();
  for (const g of listed ? (o.sms_groups as unknown[]).slice(0, SMS_GROUPS_MOST) : contacts.map((c) => c.group)) {
    const n = smsGroupName(g);
    if (n === null || lower.has(n.toLowerCase())) continue;
    lower.add(n.toLowerCase());
    groups.push(n);
  }
  if (!listed) groups.sort((a, b) => a.localeCompare(b));
  return { contacts, groups };
}

// ------------------------------------------------------------------ the picker

export interface Chosen {
  kind: "contact" | "group" | "number";
  /** What the chip says. */
  label: string;
  /** A contact no longer in the book, or a group no longer in use (only known when ZIGMon sent the book). */
  missing: boolean;
}

/** A stored recipient as the inspector's chip shows it. */
export function chosenOf(r: string, book: SmsBook | null): Chosen {
  if (r.startsWith("contact:")) {
    const id = r.slice(8);
    if (!book) return { kind: "contact", label: "Contact " + id, missing: false };
    const c = book.contacts.find((x) => x.id === id);
    return c ? { kind: "contact", label: c.name, missing: false } : { kind: "contact", label: "missing contact", missing: true };
  }
  if (r.startsWith("group:")) {
    const name = r.slice(6);
    const missing = !!book && !book.groups.some((g) => g.toLowerCase() === name.toLowerCase());
    return { kind: "group", label: name, missing };
  }
  return { kind: "number", label: spaced(r), missing: false };
}

/** "+420 777 123 456": a number in groups of three for reading (stored without spaces). */
function spaced(n: string): string {
  const plus = n.startsWith("+") ? "+" : "";
  const d = n.replace(/\D/g, "");
  if (d.length <= 4) return plus + d;
  const head = plus && d.length > 9 ? d.slice(0, d.length - 9) + " " : "";
  const rest = head ? d.slice(d.length - 9) : d;
  return plus + head + (rest.match(/.{1,3}/g) ?? []).join(" ");
}

/** A recipient picked or dropped: dropped when it is there, added at the end otherwise - never more than 20. */
export function toggled(to: readonly string[], r: string): { to: string[]; full: boolean } {
  if (to.includes(r)) return { to: to.filter((x) => x !== r), full: false };
  if (to.length >= SMS_TO_MOST) return { to: [...to], full: true };
  return { to: [...to, r], full: false };
}

/** Folded for searching: lower case, without accents ("novakova" finds "Nováková"). */
export function fold(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** The contacts and groups a search finds, by the contact's name or group and the group's name. */
export function searchBook(book: SmsBook, query: string): { contacts: SmsContact[]; groups: string[] } {
  const q = fold(query.trim());
  if (!q) return { contacts: book.contacts, groups: book.groups };
  return {
    contacts: book.contacts.filter((c) => fold(c.name).includes(q) || (c.group !== null && fold(c.group).includes(q))),
    groups: book.groups.filter((g) => fold(g).includes(q)),
  };
}

/** A phone number as typed into the fallback: + at the start and digits (spaces, dots, dashes and brackets ignored), 3-20 digits. */
export function typedNumber(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const n = v.replace(/[\s().-]/g, "");
  return /^\+?[0-9]{3,20}$/.test(n) ? n : null;
}
