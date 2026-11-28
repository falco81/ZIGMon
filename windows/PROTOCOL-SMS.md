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
administrator under Settings → Messages → Desktop app (each key's row has three switches, and
the key's dialog a card for each). Every flag defaults to false; a key without the block may do
nothing with SMS:

```json
"sms": {"read": true, "send": true, "contacts": true}
```

The administrator's API is the existing `POST /api/notifier/keys` (session, PIN, administrator):
`create` and `update` take `"sms": {...}` (each flag true or false; anything else is 400) and
`"decks": ["<install id>", ...]` (section 3, set from the key's side). `GET /api/notifier/keys`
gives each key's `sms` (all three flags) and `decks` (`[{"id", "auto"}]`), and also `sms_ready`,
`deck_enabled` and `deck_installs` (`[{"id", "name", "computer", "sms", "auto"}]`: `sms` is whether
that installation has the cap `sms`, `auto` whether its links are automatic).

- `read`: the app sees incoming and sent SMS. Incoming ones come as events in its wait;
  `GET /api/notifier/sms?limit=50` gives the latest (`limit` 1-500, 50 when missing or not a number).
- `send`: the app may send. `POST /api/notifier/sms/send {"to": [...], "text": "...", "reply_to": "<sms id>"}`.
- `contacts`: `GET /api/notifier/contacts` gives `{"ok": true, "contacts": [...], "groups": [...]}`
  (read-only; each contact as in section 1).

Through the relay (`web/index.php`), with the key in `X-Zigmon-Notifier` as for every other road:

| relay | daemon |
|---|---|
| `GET index.php?api=notifier&do=sms&limit=50` | `GET /api/notifier/sms?limit=50` |
| `GET index.php?api=notifier&do=contacts` | `GET /api/notifier/contacts` |
| `POST index.php?api=notifier&do=sms-send` (JSON body, at most 16 KB) | `POST /api/notifier/sms/send` |

`sms-send` is the only road asked by POST: the relay answers 405 to a GET of it and to a POST of
any other `do`. The home network lock of 5.59.3 applies to all of them (403).

**Sending.** `to` is a list of numbers, `contact:<id>` (the contact's first number) and
`group:<name>` (each contact of the group, its first number). ZIGMon expands them, drops a number
that comes twice, and sends each through its own `sms_send` - its gap, its daily cap and its queue.
At most 10 recipients at once, and at most 10 messages a minute for each key (on top of ZIGMon's
own limits). `reply_to` with an empty or missing `to` answers that message's number. `text` is
1-1000 characters. The answer always has the shape of `/api/sms/send`:

```json
{"ok": true, "sent": ["+420777123456"], "failed": [], "message": "1 sent", "error": null}
```

On a refusal `ok` is false, `sent` and `failed` are empty, and `error` is a sentence the app shows
word for word. When entries of `to` name nothing (an unknown `contact:<id>`, a `group:<name>` with no
contact, something that is not a phone number), the 400 also carries `"bad_to": ["<entry>", ...]`,
each as it was given:

| status | when |
|---|---|
| 400 | empty or too long text, `to` not a list, an unknown contact or group, a recipient that is not a number, none or more than 10 recipients, a `reply_to` no longer in the history, a body that is not JSON |
| 403 | the key has no `sms.send` |
| 409 | no SMS gateway is set up |
| 429 | more than 10 messages a minute from this key |

Each send is written into the events as `SMS sent from the desktop app '<key name>' to <n>
recipient(s)[, <m> failed]`, never with the text or a number; `sms_send`'s own event for it says
`sent to …456 (desktop app)`, and nothing of it goes to the log file. The SMS tab's history keeps
the message, as for every text ZIGMon sends.

The reads are refused with 403 and `{"ok": false, "error": "This desktop app may not read SMS - ..."}`
(or `... see the contacts ...`) without their flag.

`hello` gains `"sms": {"read": bool, "send": bool, "contacts": bool, "ready": bool}`, where
`ready` means the SMS gateway is set up.

An incoming SMS in the app's wait looks like this:

```json
{"seq": 812, "at": 1764340000.1, "kind": "sms", "device": "sms", "key": "in", "active": true, "what": "sms",
 "name": "Jana Nováková", "room": null,
 "sms": {"id": "s_19ab", "from": "+420777123456", "contact": {"id": "c_5f2a9e", "name": "Jana Nováková"},
         "text": "…", "at": 1764340000}}
```

(`name` is the contact's name or `SMS`; `contact` is null for a number no contact has.) Only keys
with `sms.read` get it, and only for a message that has just come in - one ZIGMon finds already
sitting in the inbox when it starts is history, not an event. The text comes from ZIGMon's own SMS
log. ZIGMon never reads the modem again for this: the TRB140 inbox is read only to remove a
message, as before.

`GET /api/notifier/sms` gives
`{"ok": true, "ready": bool, "messages": [{"id","dir":"in"|"out","number","contact":{id,name}|null,"text","at","ok"}]}`,
newest first, with whole numbers (`ok` is null while the gateway has not answered).

## 3. The Stream Deck asks the desktop app

The deck catalogue gains these items, all under the new cap **`sms`** (off by default, granted
per installation like the others, with "Every SMS key" or only these, and Hold to confirm). They
are in the **extended** catalogue only - the same opt-in as the other 5.59.4 items (`?extended=1`,
or `"extended": true` in a POST body); a state asked for by their ids names them too. They exist
only while an SMS gateway is set up or the log holds a message, and never come through `view`: an
installation sees them only with the cap `sms` itself.

`hello`'s `features` gains `"sms"` when the SMS keys exist and the installation has the cap `sms`
(`["extended", "timer", "summaries-5.59.4", "sms"]`); otherwise it is as before.

For the inspector's picker of "New SMS", the extended catalogue of an installation with the cap
`sms` also carries, beside `items`:

```json
"sms_contacts": [{"id": "c_5f2a9e", "name": "Jana Nováková", "group": "Family", "favourite": true}],
"sms_groups": ["Family", "Work"]
```

- `sms_contacts` has no numbers, and at most 500 entries, in the address book's order.
- `sms_groups` lists the groups in use, each once, in alphabetical order.
- Without the cap, or in a catalogue that is not extended, both fields are absent.

| id | kind | press does |
|---|---|---|
| `sms:last` | `sms` | the desktop app shows the latest SMS, with Reply |
| `sms:compose` | `sms` | the desktop app opens a new message |

Both have `cap` `sms`, `actions` `["run"]` and `icon` `message`. State of both: `on` null,
`value` = how many came today, `value_text` "3 today", attrs: `last_from` (the contact's name, or
the number masked to `…123`), `last_at`, `unread` (how many came in after the newest one a desktop
app had when it last fetched `GET /api/notifier/sms`; until one has, today's count).

The command is `{"id": "sms:compose", "action": "run", "to": ["contact:c_5f2a9e", "group:Family", "+420…"]}`
or `{"id": "sms:last", "action": "run"}`. `to` is optional, and at most 20 entries. Each entry is
`contact:<id>` (that contact's first number), `group:<name>` (each contact of the group, ignoring
case) or a phone number. Entries that name nothing make it 400, with the entries in `bad_to`:

```json
{"ok": false, "error": "contact:c_0000ff is not a contact, a group or a phone number here (and 1 more)",
 "bad_to": ["contact:c_0000ff", "group:Nobody"]}
```

`to` that is not a list, or longer than 20, is 400 without `bad_to`.

ZIGMon doesn't send anything by itself. It hands the ask to the desktop app(s) **linked** to
that Stream Deck installation, as an event in their wait:

```json
{"seq": 813, "at": 1764340001.2, "kind": "deck", "device": "deck", "key": "sms", "active": true, "what": "compose"|"last",
 "name": "Stream Deck 'Office deck'", "room": null,
 "deck": {"install": "<deck install id>", "computer": "OFFICE-PC", "to": [{"id","name","number"}]}}
```

(`to` is empty for `last` and for a compose without recipients; an entry's `id` and `name` are
null for a number no contact has.) The press answers 200 `{"ok": true, "said": "asked the desktop
app 'OFFICE-PC' to write an SMS", "apps": 1, "state": {...}}` and is written into the events
without a number.

Linking: each Stream Deck installation has `apps`, a list of desktop app key ids, or none. The
administrator sets them in Settings → Messages → Stream Deck, under the installation, as
checkboxes of the desktop apps ("Desktop apps on this deck's computer"), or from the key's side
in its dialog ("Stream Deck pop-ups"). The administrator's API: `POST /api/deck/admin
{"action": "apps", "install": "<id>", "apps": ["<key id>", ...]}` (session, PIN, administrator;
an unknown key is 400), or `"apps": null` to go back to the automatic link. While `apps` is not
set, ZIGMon links the app keys whose name equals the installation's computer name, ignoring case
(shown as "(automatic: OFFICE-PC)"); once it is a list, exactly those - an empty list links none.
`GET /api/deck/admin` gives each installation's `apps` (the list, or null) and `apps_linked` (the
key ids linked now, automatic or not), and `apps` at the top (`[{"id", "name", "sms"}]`, the keys
that can be linked).

The ask goes to the linked apps that may do it - `sms.read` for `last`, `sms.send` for `compose` -
and are running (the key asked ZIGMon within the last 60 s; a waiting app asks every 25 s). Else
the command answers 409 and the key shows it, with a flag beside the words:

| error | flag | when |
|---|---|---|
| `no desktop app linked to this Stream Deck is running` | `"no_app": true` | no app is linked, none of the allowed ones is running, or the desktop app is switched off in ZIGMon |
| `the desktop app linked to this Stream Deck may not read SMS` | `"not_allowed": true` | `last`, and no linked key has `sms.read` |
| `the desktop app linked to this Stream Deck may not send SMS` | `"not_allowed": true` | `compose`, and no linked key has `sms.send` |

For example `{"ok": false, "error": "no desktop app linked to this Stream Deck is running", "apps": 0, "no_app": true}`
(`apps`: how many linked apps were considered).

A deck installation can be linked to several apps, and an app to several installations.

## 4. The desktop app's own switches (kept on the PC)

- SMS pop-ups on or off;
- answering pop-ups from the Stream Deck on or off;
- the sound for an SMS;
- where pop-ups appear (the existing monitor choice).

When the app has a switch off, it ignores the matching events. The server's permissions still
decide what is possible.
