/**
 * 1.3, the deck SMS keys as the server has them final (windows/PROTOCOL-SMS.md 3): the address book
 * of the extended catalogue parsed strictly and with caps, what the recipient picker stores (the
 * settings accept nothing else), the refusals told by their flags (the words only as a fallback),
 * and the path where ZIGMon sends no contacts.
 */
import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import type { Command } from "../src/core/client.js";
import { recipientWord } from "../src/core/extra.js";
import { Hub as RealHub, refusalOf, type CommandResult, type Hub } from "../src/core/hub.js";
import { NodeTransport } from "../src/core/http.js";
import { cleanRecipient } from "../src/core/kinds.js";
import { catalogMessage } from "../src/core/piapi.js";
import { parseCatalog, parseItem, type Item } from "../src/core/protocol.js";
import { FakeProtector } from "../src/core/secrets.js";
import { normalizeAction } from "../src/core/settings.js";
import { chosenOf, parseSmsBook, searchBook, SMS_CONTACTS_MOST, toggled, typedNumber, type SmsBook } from "../src/core/smsbook.js";
import { ActionView, type ActionKind } from "../src/core/views.js";
import { extendedItems, FakeZigmon, MemoryStore, MockSurface, sampleBook, sampleItems, until } from "./fake-zigmon.js";

const cleanups: (() => unknown)[] = [];
after(async () => {
  for (const c of cleanups.reverse()) await c();
});

const BOOK = (): SmsBook => parseSmsBook(sampleBook())!;
const all = (): Item[] => [...sampleItems(), ...extendedItems()].map((r) => parseItem(r));
const texts = (svg: string) => [...svg.matchAll(/<text\b[^>]*>(.*?)<\/text>/gs)].map((m) => m[1]!.replace(/<[^>]+>/g, "")).join(" ");
const catalog = (extra: Record<string, unknown>) => parseCatalog({ ok: true, boot: 1, seq: 1, rooms: [], items: [], ...extra });

// ------------------------------------------------------------------ parsing

describe("SMS address book: sms_contacts and sms_groups, strictly", () => {
  it("absent, or not a list: null (no cap sms, or an older ZIGMon) - the catalogue itself still reads", () => {
    assert.equal(catalog({}).sms, null);
    assert.equal(catalog({ sms_contacts: "everyone" }).sms, null);
    assert.equal(catalog({ sms_contacts: { a: 1 } }).sms, null);
    assert.equal(catalog({ sms_groups: ["Family"] }).sms, null, "groups alone are no book");
    assert.deepEqual(catalog({ sms_contacts: [], sms_groups: [] }).sms, { contacts: [], groups: [] });
  });

  it("each contact checked: the id's shape, a name, once; no number ever kept; favourite only when true", () => {
    const b = catalog({
      sms_contacts: [
        { id: "c_5f2a9e", name: "Jana Nováková", group: "Family", favourite: true, number: "+420777123456" },
        { id: "c_5f2a9e", name: "Jana again", group: null, favourite: false },
        { id: "C_5F2A9E", name: "upper case id" },
        { id: "c_12345", name: "five hex" },
        { id: "c_0123456789abc", name: "thirteen hex" },
        { id: "c_zzzzzz", name: "not hex" },
        { id: 5, name: "number id" },
        { id: "c_aaaaaa", name: "" },
        { id: "c_bbbbbb", name: "  ‮\u0007 " },
        { id: "c_cccccc", name: "Petr‮\u0000 Novák", group: "Wo,rk", favourite: "yes" },
        { id: "c_dddddd", name: "x".repeat(90), group: "g".repeat(41) },
        { id: "c_eeeeee", name: "Forty", group: "g".repeat(40) },
        null, "c_ffffff", ["c_ffffff"],
      ],
    }).sms!;
    assert.deepEqual(b.contacts.map((c) => c.id), ["c_5f2a9e", "c_cccccc", "c_dddddd", "c_eeeeee"]);
    assert.deepEqual(b.contacts[0], { id: "c_5f2a9e", name: "Jana Nováková", group: "Family", favourite: true });
    assert.ok(!JSON.stringify(b).includes("777"), "no number is kept");
    assert.equal(b.contacts[1]!.name, "Petr Novák", "control and direction characters out");
    assert.equal(b.contacts[1]!.group, null, "a group that could not go back as group:<name> is dropped");
    assert.equal(b.contacts[1]!.favourite, false);
    assert.equal([...b.contacts[2]!.name].length, 60);
    assert.equal(b.contacts[2]!.group, null, "41 characters: dropped, never shortened");
    assert.equal(b.contacts[3]!.group, "g".repeat(40));
  });

  it("at most 500 contacts", () => {
    const many = Array.from({ length: 700 }, (_, i) => ({ id: "c_" + i.toString(16).padStart(6, "0"), name: "N" + i, group: null, favourite: false }));
    const b = catalog({ sms_contacts: many }).sms!;
    assert.equal(b.contacts.length, SMS_CONTACTS_MOST);
    assert.equal(b.contacts.at(-1)!.name, "N499");
  });

  it("groups: each once (ignoring case), bad ones dropped, at most 500; without sms_groups, the contacts' own, alphabetically", () => {
    const b = catalog({ sms_contacts: [], sms_groups: ["Work", "Family", "family", "", 7, "a;b", "<b>", "x".repeat(41), "  Neighbours  ", null] }).sms!;
    assert.deepEqual(b.groups, ["Work", "Family", "Neighbours"], "the server's order kept");
    const d = catalog({ sms_contacts: [{ id: "c_aaaaaa", name: "A", group: "Work" }, { id: "c_bbbbbb", name: "B", group: "Family" }, { id: "c_cccccc", name: "C", group: "work" }] }).sms!;
    assert.deepEqual(d.groups, ["Family", "Work"]);
    const lots = catalog({ sms_contacts: [], sms_groups: Array.from({ length: 900 }, (_, i) => "G" + i) }).sms!;
    assert.equal(lots.groups.length, 500);
  });

  it("the sample book of the fake ZIGMon reads whole", () => {
    const b = BOOK();
    assert.equal(b.contacts.length, 8);
    assert.deepEqual(b.groups, ["Family", "Neighbours", "Work"]);
    assert.deepEqual(b.contacts.filter((c) => c.favourite).map((c) => c.name), ["Jana Nováková", "Petr Novák", "Martin Svoboda"]);
  });
});

// ------------------------------------------------------------------ what the picker stores

describe("SMS picker: the stored recipients", () => {
  it("settings keep only contact:<id> (c_ and 6-12 lowercase hex), group:<name> up to 40, or a number", () => {
    const s = normalizeAction({
      smsTo: [
        "contact:c_5f2a9e", "contact:c_0123456789ab", "contact:C_5F2A9E", "contact:c_12345", "contact:c_0123456789abc", "contact:c_5f2a9e;x", "contact:", "contact:Jana",
        "group:Family", "group:" + "g".repeat(40), "group:" + "g".repeat(41), "group:", "group:a,b", "group:<b>",
        "+420 777 123 456", "(777) 123-456", "+42O777", "12", "777 123 456 ext 5", "<script>", 42, null, "contact:c_5f2a9e",
      ],
    });
    assert.deepEqual(s.smsTo, ["contact:c_5f2a9e", "contact:c_0123456789ab", "group:Family", "group:" + "g".repeat(40), "+420777123456", "777123456"]);
    assert.equal(cleanRecipient(" contact:c_abcdef "), "contact:c_abcdef");
    assert.equal(cleanRecipient("GROUP: Family"), "group:Family");
    assert.equal(normalizeAction({ smsTo: ["contact:nope"] }).smsTo, undefined);
    assert.equal(normalizeAction({ smsTo: "contact:c_5f2a9e" }).smsTo, undefined, "not a list");
    assert.equal(normalizeAction({ smsTo: Array.from({ length: 30 }, (_, i) => "contact:c_" + i.toString(16).padStart(6, "0")) }).smsTo!.length, 20);
  });

  it("the typed fallback: + and digits only", () => {
    assert.equal(typedNumber("+420 777 123 456"), "+420777123456");
    assert.equal(typedNumber("777-123-456"), "777123456");
    for (const bad of ["group:Family", "contact:c_5f2a9e", "++420", "42", "+420 777 abc", "", 777123456]) assert.equal(typedNumber(bad), null, String(bad));
  });

  it("picking toggles, never past 20", () => {
    assert.deepEqual(toggled([], "contact:c_5f2a9e"), { to: ["contact:c_5f2a9e"], full: false });
    assert.deepEqual(toggled(["contact:c_5f2a9e", "group:Work"], "contact:c_5f2a9e"), { to: ["group:Work"], full: false });
    const twenty = Array.from({ length: 20 }, (_, i) => "+42077700" + String(i).padStart(4, "0"));
    assert.deepEqual(toggled(twenty, "group:Work"), { to: twenty, full: true });
    assert.equal(toggled(twenty, twenty[3]!).to.length, 19, "one can still be removed");
  });

  it("the chips: a contact by name, a missing one says so, a group, a number in threes", () => {
    const b = BOOK();
    assert.deepEqual(chosenOf("contact:c_5f2a9e", b), { kind: "contact", label: "Jana Nováková", missing: false });
    assert.deepEqual(chosenOf("contact:c_0000ff", b), { kind: "contact", label: "missing contact", missing: true });
    assert.deepEqual(chosenOf("group:family", b), { kind: "group", label: "family", missing: false });
    assert.deepEqual(chosenOf("group:Nobody", b), { kind: "group", label: "Nobody", missing: true });
    assert.deepEqual(chosenOf("+420777123456", b), { kind: "number", label: "+420 777 123 456", missing: false });
    // without a book nothing can be said missing
    assert.deepEqual(chosenOf("contact:c_0000ff", null), { kind: "contact", label: "Contact c_0000ff", missing: false });
    assert.equal(chosenOf("group:Nobody", null).missing, false);
  });

  it("the search: names and groups, ignoring case and accents", () => {
    const b = BOOK();
    assert.deepEqual(searchBook(b, "novak").contacts.map((c) => c.name), ["Jana Nováková", "Petr Novák"]);
    assert.deepEqual(searchBook(b, "WORK").contacts.map((c) => c.name), ["Martin Svoboda", "Office reception"]);
    assert.deepEqual(searchBook(b, "WORK").groups, ["Work"]);
    assert.deepEqual(searchBook(b, "černý").contacts.map((c) => c.id), ["c_e6f708"]);
    assert.equal(searchBook(b, "  ").contacts.length, 8);
    assert.deepEqual(searchBook(b, "zzz"), { contacts: [], groups: [] });
  });

  it("the key names its recipients from the book", () => {
    const b = BOOK();
    assert.equal(recipientWord("contact:c_5f2a9e", b), "Jana Nováková");
    assert.equal(recipientWord("contact:c_0000ff", b), "missing contact");
    assert.equal(recipientWord("contact:c_0000ff", null), "contact");
    assert.equal(recipientWord("group:Work", b), "Work");
    assert.equal(recipientWord("+420777123456", b), "…456");
  });
});

// ------------------------------------------------------------------ the flags

describe("SMS refusals: the flags, the words only as a fallback", () => {
  it("each flag says what it was", () => {
    assert.deepEqual(refusalOf(409, { no_app: true }, "anything"), { why: "noapp" });
    assert.deepEqual(refusalOf(409, { not_allowed: true }, "anything"), { why: "notallowed" });
    assert.deepEqual(refusalOf(409, { nothing: true }, "anything"), { why: "nothing" });
    assert.deepEqual(refusalOf(400, { bad_to: ["contact:c_0000ff", "group:Nobody", 5, "‮"] }, "anything"), { why: "badto", bad: ["contact:c_0000ff", "group:Nobody", "5"] });
    // a flag wins over words that would say otherwise
    assert.deepEqual(refusalOf(409, { not_allowed: true }, "no desktop app linked to this Stream Deck is running"), { why: "notallowed" });
  });

  it("without a flag, the words (a ZIGMon in between); with a flag present but false, never the words", () => {
    assert.deepEqual(refusalOf(409, {}, "no desktop app linked to this Stream Deck is running"), { why: "noapp" });
    assert.deepEqual(refusalOf(409, {}, "the desktop app linked to this Stream Deck may not send SMS"), { why: "notallowed" });
    assert.deepEqual(refusalOf(409, {}, "the desktop app linked to this Stream Deck may not read SMS"), { why: "notallowed" });
    assert.deepEqual(refusalOf(409, {}, "there is no alert standing"), { why: "nothing" });
    assert.deepEqual(refusalOf(400, {}, "contact:c_0000ff is not a contact, a group or a phone number here (and 1 more)"), { why: "badto", bad: [] });
    assert.equal(refusalOf(409, { no_app: false }, "no desktop app linked to this Stream Deck is running"), null);
    assert.equal(refusalOf(409, {}, "Hold the key to confirm"), null);
    assert.equal(refusalOf(400, {}, "minutes must be 15-240"), null);
    assert.equal(refusalOf(403, { no_app: true }, "x"), null, "only a 409 is no_app");
  });

  function stub(answer: CommandResult, book: SmsBook | null = BOOK()): Hub {
    const items = new Map(all().map((i) => [i.id, i]));
    return {
      currentPhase: "online", pairCode: null, currentMessage: "",
      item: (id: string) => items.get(id), state: (id: string) => items.get(id)?.state, history: () => [], series: () => null,
      supports: () => true, deckIsApproved: () => true, resubscribe: () => undefined, retryNow: () => undefined,
      allItems: () => [...items.values()], allRooms: () => [], smsBook: () => book,
      command: async (_c: Command) => answer,
    } as unknown as Hub;
  }

  async function pressed(kind: ActionKind, settings: Record<string, unknown>, answer: CommandResult): Promise<string> {
    const s = new MockSurface("Keypad", "D");
    const v = new ActionView(kind, stub(answer), s, settings);
    cleanups.push(() => v.dispose());
    v.draw(true);
    v.keyDown();
    await new Promise((r) => setTimeout(r, kind === "security" ? 1650 : 10));
    v.keyUp();
    await new Promise((r) => setTimeout(r, kind === "security" ? 400 : 40));
    return texts(s.svg);
  }

  it("the key says each in words of its own", async () => {
    const msg = "whatever the server said";
    assert.match(await pressed("sms", {}, { ok: false, why: "noapp", message: msg }), /Desktop app not.*running/);
    assert.match(await pressed("sms", { smsMode: "compose" }, { ok: false, why: "notallowed", message: msg }), /Not allowed in.*the app/);
    const bad = await pressed("sms", { smsMode: "compose", smsTo: ["contact:c_0000ff"] }, { ok: false, why: "badto", message: msg, bad: ["contact:c_0000ff"] });
    assert.match(bad, /Unknown.*recipient/);
    assert.match(bad, /missing contact/);
    assert.match(await pressed("security", {}, { ok: false, why: "nothing", message: msg }), /No alert/);
  });
});

// ------------------------------------------------------------------ end to end, with and without the book

describe("SMS end to end against a fake ZIGMon", () => {
  async function connect(features: string[], book = true) {
    const fake = new FakeZigmon();
    fake.features = features;
    if (!book) fake.smsBook = null;
    fake.autoApprove = true;
    fake.waitMs = 200;
    await fake.start(0);
    const hub = new RealHub({
      store: new MemoryStore(), protector: new FakeProtector(), transport: (a) => new NodeTransport(a), decks: () => [{ id: "D1", type: 7, name: "+", cols: 4, rows: 2 }],
      computer: () => "PC", minBackoffMs: 50, maxBackoffMs: 200,
    });
    cleanups.push(async () => {
      hub.stop();
      await fake.stop();
    });
    await hub.start();
    await hub.connect("http://localhost:" + fake.port);
    await until(() => hub.currentPhase === "online" && hub.allItems().length > 0, 8000, "online");
    return { fake, hub };
  }
  const FULL = ["extended", "timer", "summaries-5.59.4", "sms"];

  it("with the cap sms: the book reaches the inspector, the key names the contacts, and every refusal by its flag", async () => {
    const { fake, hub } = await connect(FULL);
    assert.equal(hub.supports("sms"), true);
    assert.equal(hub.smsBook()!.contacts.length, 8);
    const m = catalogMessage(hub, "sms").sms as SmsBook;
    assert.equal(m.contacts[0]!.name, "Jana Nováková");
    assert.ok(!JSON.stringify(m).includes("+420"));
    assert.equal(catalogMessage(hub, "control").sms, undefined, "only the SMS key's inspector gets it");

    const s = new MockSurface("Keypad", "D1");
    const v = new ActionView("sms", hub, s, { smsMode: "compose", smsTo: ["contact:c_5f2a9e", "group:Work"] });
    hub.watch(v);
    cleanups.push(() => v.dispose());
    v.draw(true);
    assert.ok(v.facts()!.some(([k, t]) => k === "To" && t === "Jana Nováková, Work"), JSON.stringify(v.facts()));

    const noapp = await hub.command({ deck: "D1", id: "sms:compose", action: "run" });
    assert.equal(!noapp.ok && noapp.why, "noapp");
    fake.desktopApp = true;
    fake.desktopAppMay = false;
    const na = await hub.command({ deck: "D1", id: "sms:last", action: "run" });
    assert.equal(!na.ok && na.why, "notallowed");
    fake.desktopAppMay = true;
    const bad = await hub.command({ deck: "D1", id: "sms:compose", action: "run", to: ["contact:c_5f2a9e", "contact:c_0000ff", "group:Nobody"] });
    assert.ok(!bad.ok && bad.why === "badto");
    assert.deepEqual(!bad.ok && bad.bad, ["contact:c_0000ff", "group:Nobody"]);
    assert.ok((await hub.command({ deck: "D1", id: "sms:compose", action: "run", to: ["contact:c_5f2a9e", "group:work", "+420777123456"] })).ok);
    // acknowledging with nothing standing
    fake.setState("status:security", { value: 0, attrs: { alerts: 0 } });
    const none = await hub.command({ deck: "D1", id: "status:security", action: "ack", held_ms: 1600 });
    assert.equal(!none.ok && none.why, "nothing");
  });

  it("without the book (no cap sms, or an older ZIGMon): none is kept, the inspector is told null, the key still works", async () => {
    for (const [features, book] of [[["extended", "timer", "summaries-5.59.4"], true], [FULL, false]] as [string[], boolean][]) {
      const { fake, hub } = await connect(features, book);
      assert.equal(hub.smsBook(), null, features.join());
      assert.equal(catalogMessage(hub, "sms").sms, null);
      const v = new ActionView("sms", hub, new MockSurface("Keypad", "D1"), { smsMode: "compose", smsTo: ["contact:c_5f2a9e", "+420777123456"] });
      cleanups.push(() => v.dispose());
      assert.ok(v.facts()!.some(([k, t]) => k === "To" && t === "contact, …456"), JSON.stringify(v.facts()));
      fake.desktopApp = true;
      assert.ok((await hub.command({ deck: "D1", id: "sms:compose", action: "run", to: ["+420777123456"] })).ok);
    }
  });
});
