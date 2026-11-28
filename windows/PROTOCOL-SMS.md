# SMS, contacts, the desktop app and the Stream Deck together (ZIGMon 5.59.4)

The contract between ZIGMon (`zigmon.py`, `web/index.php`), the desktop app (`windows/`,
ZIGMon Notifier 1.4.0) and the Stream Deck plugin (`streamdeck/`, 1.3.0). Everything here is
additive: an older app or plugin ignores it, and a newer one with an older ZIGMon hides it.
The desktop app and the Stream Deck reach ZIGMon only from the home network (5.59.3).

## 1. Contacts (kept in ZIGMon)

Kept as meta `contacts` (JSON list), at most 2000 rows:

```json
{"id": "c_5f2a9e", "name": "Jana Nováková", "numbers": [{"label": "mobile", "number": "+420777123456"}],
 "group": "Family", "note": "", "favourite": true}
```

- `id`: `c_` + 6-12 lowercase hex, made by ZIGMon.
- `name`: 1-80 characters.
- `numbers`: 1-5 entries. Each `number` is normalised the way ZIGMon already
  normalises SMS numbers (`sms_number_for_gateway`), and each `label` is at most 20 characters.
- `group`: at most 40 characters, may be empty. `note`: at most 200 characters.
- `favourite`: a bool.
- Names are unique, ignoring case.

The administrator's API (session plus PIN, like the other settings):

- `GET /api/contacts` gives `{"ok": true, "contacts": [...], "groups": [...]}`.
- `POST /api/contacts` takes:
  - `{"action": "save", "contact": {...}}`: create when there is no id, update when there is one.
  - `{"action": "delete", "id": "..."}`
  - `{"action": "import", "format": "vcf"|"csv", "text": "...", "mode": "merge"|"replace"}` returns
    `{"ok": true, "added": n, "updated": n, "skipped": [{"line": n, "why": "..."}]}`.
- `GET /api/contacts/export?format=vcf|csv` returns a download: vCard 3.0, or CSV with the
  Google Contacts headers (`Name,Given Name,Family Name,Group Membership,Phone 1 - Type,Phone 1 - Value,...`).
- Import reads:
  - vCard 2.1, 3.0 and 4.0, from phones, Google, Outlook and iCloud: FN/N, TEL with TYPE,
    CATEGORIES, NOTE, quoted-printable, folded lines and UTF-8;
  - CSV from Google Contacts or Outlook, with `,` or `;` separators and an optional BOM.

The web UI: SMS tab → **Contacts**. It has search, groups, favourites, an editor for numbers,
import with a preview before saving, and export.

The web **Write a message** page picks its recipients from the contacts: chips with an
autocomplete over names, groups and numbers, a contact's number chosen when it has several,
or a typed number. The send API takes `to` as a list of numbers and/or `contact:<id>` /
`group:<name>`. ZIGMon expands these to numbers and drops duplicates.

## 2. The desktop app and SMS

Each desktop app key (`notifier_keys` row) gains an optional `sms` block, set by the
administrator under Settings → Messages → Desktop app. Every flag defaults to false:

```json
"sms": {"read": true, "send": true, "contacts": true}
```

- `read`: the app sees incoming and sent SMS. Incoming ones come as events in its wait;
  `GET /api/notifier/sms?limit=50` gives the latest.
- `send`: the app may send. `POST /api/notifier/sms/send {"to": [...], "text": "...", "reply_to": "<sms id>"}`.
  ZIGMon's own SMS limits and queue apply, and an event is logged as "sent from the desktop app '<name>'".
- `contacts`: `GET /api/notifier/contacts` gives the contacts (read-only).

`hello` gains `"sms": {"read": bool, "send": bool, "contacts": bool, "ready": bool}`, where
`ready` means the SMS gateway is set up.

An incoming SMS in the app's wait looks like this:

```json
{"seq": 812, "at": 1764340000.1, "kind": "sms", "device": "sms", "key": "in", "active": true, "what": "sms",
 "sms": {"id": "s_19ab", "from": "+420777123456", "contact": {"id": "c_5f2a9e", "name": "Jana Nováková"},
         "text": "…", "at": 1764340000}}
```

Only keys with `sms.read` get it. The text comes from ZIGMon's own SMS log. ZIGMon never reads
the modem again for this: the TRB140 inbox is read only to remove a message, as before.

`GET /api/notifier/sms` gives
`{"ok": true, "messages": [{"id","dir":"in"|"out","number","contact":{id,name}|null,"text","at","ok"}]}`,
newest first.

## 3. The Stream Deck asks the desktop app

The deck catalogue gains these items, all under the new cap **`sms`** (off by default, granted
per installation like the others):

| id | kind | press does |
|---|---|---|
| `sms:last` | `sms` | the desktop app shows the latest SMS, with Reply |
| `sms:compose` | `sms` | the desktop app opens a new message |

State of both: `on` null, `value` = how many came today, `value_text` "3 today", attrs:
`last_from` (the contact's name, or the number masked to `…123`), `last_at`, `unread` (the
number since the app last showed them).

The command is `{"id": "sms:compose", "action": "run", "to": ["contact:c_5f2a9e", "group:Family", "+420…"]}`
(`to` is optional and at most 20 entries) or `{"id": "sms:last", "action": "run"}`.

ZIGMon doesn't send anything by itself. It hands the ask to the desktop app(s) **linked** to
that Stream Deck installation, as an event in their wait:

```json
{"seq": 813, "kind": "deck", "device": "deck", "key": "sms", "active": true, "what": "compose"|"last",
 "deck": {"install": "<deck install id>", "computer": "OFFICE-PC", "to": [{"id","name","number"}]}}
```

Linking: each Stream Deck installation has `apps`, a list of desktop app key ids. The
administrator sets them in Settings → Messages → Stream Deck, under the installation, as
checkboxes of the desktop apps. When none are set, ZIGMon links the app keys whose name equals
the installation's computer name, ignoring case. When no linked app is waiting (online), the
command answers 409 `{"ok": false, "error": "no desktop app linked to this Stream Deck is running"}`
and the key shows it. A deck installation can be linked to several apps, and an app to several
installations.

## 4. The desktop app's own switches (kept on the PC)

- SMS pop-ups on or off;
- answering pop-ups from the Stream Deck on or off;
- the sound for an SMS;
- where pop-ups appear (the existing monitor choice).

When the app has a switch off, it ignores the matching events. The server's permissions still
decide what is possible.
