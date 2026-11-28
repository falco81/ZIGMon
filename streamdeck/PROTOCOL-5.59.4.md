# ZIGMon for Stream Deck: the protocol additions of ZIGMon 5.59.4

These are the notes for the plugin side of ten new actions. Everything here is **additive** to
the 5.59 / 5.59.3 protocol (`api: 1`). Every existing road, item, field and action behaves
exactly as before. A plugin that does not ask for the new parts sees nothing of them.

All of this is in **ZIGMon 5.59.4** and later.

## 0. How to tell, and how to ask

### `hello` names the features

`hello` gains one field:

```json
"features": ["extended", "timer", "summaries-5.59.4"]
```

If `features` is missing, or does not contain `"extended"`, the ZIGMon is older. Keep to the 1.2.0
behaviour then, and never send `timer`.

### Asking for the summaries ("extended")

The ten summary items (sections 1-7, 9 and 10) are left out of `catalog`, of `state` without
`ids`, and of `wait` without `ids`, unless the question asks for them:

| Where | How |
|---|---|
| Straight to the daemon | `?extended=1` on `catalog`, `state` or `wait` |
| Through the PHP relay (`index.php?api=deck&do=…`) | **POST** the road with `"extended": true` in the JSON body. The relay forwards a POST body whole, but it drops unknown query parameters, so `?extended=1` does **not** pass the relay. |

POST bodies for these roads:

```json
// catalog
{"extended": true, "decks": "C0FFEE00XL01"}

// state
{"extended": true, "ids": "house:power,room:r1", "history": {"span": 86400, "points": 48}}

// wait
{"extended": true, "after": 1234, "boot": "a1b2c3d4e5f6", "ids": "house:power,status:sms"}
```

`ids` is a **comma-separated string**, as in the query. A JSON list does not work there.
`decks` and `deck_info` are read from the body as from the query.

Rules:

- A summary named in `ids` is always answered (if the deck may see it), with or without `extended`.
- `do` reaches every item the deck may see. It needs no `extended`.
- In an extended catalogue:
  - every switch (see section 8) lists `"timer"` in its `actions`;
  - an item whose action has a capability of its own carries an `act` object (section 0.2);
  - a room carries `members` (section 9).

  These extra fields appear **only** in an extended catalogue, so a 1.2.0 plugin's catalogue has
  the same items, fields and actions as before. Two things a 1.2.0 plugin may still notice are
  both inside `state.attrs`:
  - a switch's `off_at` while a timer is pending (section 8);
  - an address scrubbed from `status:alerts`' `latest` (section 0.3).

### 0.1 The item shape

Every item has the shape it always had:

```text
{id, name, room, kind, icon, cap, actions, attrs, allowed, hold, state}
state = {on, value, value_text, attrs, online, battery, at}
```

All the new data is in `state.attrs`. A field whose value is unknown is `null`, never missing.

### 0.2 Actions with a capability of their own: `act`

The acknowledge and mute actions live on `status` items. The item is *seen* under `status`, but
its action is *granted* under `system`. The extended catalogue says so per action:

```json
"act": {"ack": {"cap": "system", "allowed": true, "hold": true}}
```

The fields:

- `allowed`: the deck's `system` capability is on, either for every item or for this item by name.
  The administrator may tick `status:security` and `status:sms` under *system* one by one.
- `hold`: always `true` for `ack`, `mute` and `unmute`. These change how the house behaves, so a
  press without `held_ms >= 1500` answers 409 `{"hold": true}`, **even when** the administrator
  switched the hold off for *system*.

Use `act[action]`, not the item's own `allowed` and `hold`, for these actions. For a `status`
item, the item's own `allowed` still means only "may be seen".

The errors, in the contract's order:

| Case | Answer |
|---|---|
| Not visible | 404 |
| No `system` capability | 403 `{"allowed": false, "cap": "system"}` |
| Not held | 409 `{"hold": true}` |
| Bad value | 400 |

### 0.3 The privacy rules

- No IP address (v4 or v6, with its port or prefix), MAC address, Zigbee IEEE address
  (`0x…` with 12-16 hex digits) or host name ever appears in the text of a new state. Each one
  becomes `…`.
  - A host name is caught when it has three or more labels, or when it ends in a common
    top-level domain (`.com`, `.cz`, `.lan`, `.local` and others).
  - `Obyvak.temperature` is kept.
- A phone number is shown as its last three digits: `…123`.
- The same scrub now applies to the existing `status:alerts`, in `state.attrs.latest`. That field
  keeps its name and type. Only an address in it becomes `…`.
- A room's `members` are item ids, which for a Zigbee thing contain its IEEE address, as the
  catalogue's own ids always have. They are therefore given in the **catalogue** (to a deck that
  may see those items), never in a state. The state carries only the count.

## 1. House power: `house:power`

| | |
|---|---|
| id | `house:power` |
| kind | `power` |
| icon | `bolt` |
| cap | `view` |
| actions | none |

`attrs` (the item's): `[{"key": "power", "label": "Power", "type": "number", "unit": "W", "min": 0, "max": null}]`

| state field | type | meaning |
|---|---|---|
| `value` | number | the house's total in W, now, as the dashboard shows it (`power_now().total`, 0.1 W) |
| `value_text` | string | `"45.2 W"` |
| `online` | bool | false when ZIGMon has no sockets at all |
| `attrs.power` | number | same as `value` |
| `attrs.kwh_today` | number \| null | today's kWh from the Energy summary ZIGMon keeps warm; null until it is made |
| `attrs.sockets_w`, `attrs.lights_w` | number | the total split by role |
| `attrs.sockets_on`, `attrs.lights_on` | int | how many metered sockets and lights are on |

History: `state` POST with `"history": {"span": s, "points": n}` and `ids` containing
`house:power`. The answer is `history["house:power"] = {"span": s, "points": [[ts, watts], …]}`:

- a span of 3600 (1 h): the house total minute by minute, from memory (the peak of each minute);
- 21600 (6 h), 86400 (24 h) and 604800 (7 d): hourly averages summed over the metered sockets,
  as the Energy tab's chart.

```json
{"id": "house:power", "name": "House power", "room": null, "kind": "power", "icon": "bolt", "cap": "view",
 "actions": [], "attrs": [{"key": "power", "label": "Power", "type": "number", "unit": "W", "min": 0, "max": null}],
 "allowed": true, "hold": false,
 "state": {"on": null, "value": 45.2, "value_text": "45.2 W",
           "attrs": {"power": 45.2, "kwh_today": 1.5, "sockets_w": 35.2, "lights_w": 10.0,
                     "sockets_on": 1, "lights_on": 0},
           "online": true, "battery": null, "at": null}}
```

## 2. Network security: `status:security`

| | |
|---|---|
| id | `status:security` |
| kind | `security` |
| icon | `shield` |
| cap | `status` (to see it) |
| actions | `["ack"]`, granted under **system**, always held (section 0.2) |

| state field | type | meaning |
|---|---|---|
| `on` | bool | true = no alert standing |
| `value` | int | alerts standing |
| `value_text` | string | `"2 standing"` / `"all quiet"` |
| `attrs.level` | string | `crit` with alerts standing, else `ok` |
| `attrs.alerts` | int | the standing alerts (the dashboard's band; they stay until someone says they have seen them) |
| `attrs.alerts_24h` | int | of them, raised in the last 24 h |
| `attrs.blocked` | int | addresses kept out now (0 when the blacklist is off) |
| `attrs.blocked_24h` | int \| null | addresses kept out in the last 24 h (the list and its history; asked of the database at most once a minute) |
| `attrs.guarding` | bool | the blacklist is on |
| `attrs.latest` | string \| null | the latest alert's text, scrubbed (section 0.3), at most 120 characters |
| `attrs.latest_at` | int \| null | when it was raised (epoch s) |

Action `ack`: body `{"deck", "id": "status:security", "action": "ack", "held_ms": 1500}`. It clears
the **latest** standing alert, the same as the dashboard's "seen" on that alert
(`/api/alerts/clear` with its id). Older alerts stay. With no alert standing it answers 409
`{"error": "there is no alert standing"}`. It writes the event
`Stream Deck '<name>' (<type>) acknowledged the latest alert`.

```json
{"id": "status:security", "name": "Network security", "room": null, "kind": "security", "icon": "shield",
 "cap": "status", "actions": ["ack"], "attrs": [], "allowed": true, "hold": false,
 "act": {"ack": {"cap": "system", "allowed": true, "hold": true}},
 "state": {"on": false, "value": 2, "value_text": "2 standing",
           "attrs": {"level": "crit", "alerts": 2, "alerts_24h": 1, "blocked": 14, "blocked_24h": 37,
                     "guarding": true,
                     "latest": "Suricata: … scanned … from … (…), call …456 at 12:30:45",
                     "latest_at": 1795874717},
           "online": true, "battery": null, "at": null}}
```

## 3. Heating in every room: `heat:group:all`

This item is present only when at least one room is heated.

| | |
|---|---|
| id | `heat:group:all` |
| kind | `heatgroup` |
| icon | `heat` |
| cap | `climate` (its hold as the administrator set it) |
| actions | `["set"]` |

`attrs`: `[{"key": "mode", "label": "Mode", "type": "enum", "values": ["plan", "comfort", "eco", "night", "max", "off", "manual"]}]`

| state field | type | meaning |
|---|---|---|
| `on` | bool | some room is calling for heat |
| `value`, `value_text` | string | the common mode, or `"mixed"` |
| `attrs.mode` | string | same |
| `attrs.rooms` | int | heated rooms |
| `attrs.calling` | int | rooms calling for heat now |
| `attrs.min_temperature`, `attrs.max_temperature` | number \| null | the lowest and highest measured room temperature (°C) |

Action `set`, with one of these bodies:

```json
{"deck": "...", "id": "heat:group:all", "action": "set", "attr": "mode", "value": "eco"}
{"deck": "...", "id": "heat:group:all", "action": "set", "attr": "mode", "delta": 1}
```

- `delta` steps through `values` from the common mode. From `mixed` it starts at `plan` for +1.
- `attr` may be left out.
- Every heated room is set to that mode one after another, on one thread, through the same road
  as `heat:room:<id>` `set` (`heat_target('room:<id>', 'set:<mode>')`). Each room writes its own
  heating event.
- An unknown mode answers 400.
- The answer comes at once, and the rooms follow within a second. Watch `wait`.

```json
{"id": "heat:group:all", "name": "Heating in every room", "kind": "heatgroup", "icon": "heat", "cap": "climate",
 "actions": ["set"], "attrs": [{"key": "mode", "label": "Mode", "type": "enum",
 "values": ["plan", "comfort", "eco", "night", "max", "off", "manual"]}], "allowed": true, "hold": false, "room": null,
 "state": {"on": true, "value": "mixed", "value_text": "mixed",
           "attrs": {"mode": "mixed", "rooms": 2, "calling": 1, "min_temperature": 15.5, "max_temperature": 21.0},
           "online": true, "battery": null, "at": null}}
```

## 4. Away / Home: `house:away`

This item is present only when the heating has heated rooms, since its switch is the heating's
away switch.

| | |
|---|---|
| id | `house:away` |
| kind | `away` |
| icon | `home` |
| cap | `climate` |
| actions | `["toggle", "on", "off"]` (exactly `heat:away`'s road) |

| state field | type | meaning |
|---|---|---|
| `on` | bool | the away switch is on |
| `value_text` | string | `"away"` / `"home"` |
| `attrs.away` | bool | the switch |
| `attrs.away_now` | bool | away in force now: the switch, or today inside the away dates |
| `attrs.lights_on` | int | lights on now (sockets with the role light, and Zigbee lights) |
| `attrs.sockets_on` | int | sockets and Zigbee switches on now |
| `attrs.rooms_heating` | int | rooms calling for heat |

The commands are the ordinary ones: `{"action": "toggle"}`, `"on"` or `"off"`. Switching the
plugin's chosen items off is the plugin's job, with ordinary commands to those items under their
own capabilities. The server does nothing more.

```json
{"id": "house:away", "name": "Away / Home", "kind": "away", "icon": "home", "cap": "climate",
 "actions": ["toggle", "on", "off"], "attrs": [], "allowed": true, "hold": false, "room": null,
 "state": {"on": false, "value": null, "value_text": "home",
           "attrs": {"away": false, "away_now": false, "lights_on": 1, "sockets_on": 1, "rooms_heating": 1},
           "online": true, "battery": null, "at": null}}
```

## 5. Windows and doors: `house:openings`

This item is present when at least one device reports `contact`.

| | |
|---|---|
| id | `house:openings` |
| kind | `openings` |
| icon | `contact` |
| cap | `view` |
| actions | none |

Each device whose report has `contact` counts, as the heating's "a window is open" reads it:

- `contact: false` = open;
- `contact: null` (not heard yet) is not counted at all.

| state field | type | meaning |
|---|---|---|
| `on` | bool | true = everything shut |
| `value` | int | how many are open |
| `value_text` | string | `"1 open"` / `"all shut"` |
| `attrs.open` | int | same |
| `attrs.sensors` | int | contact sensors heard |
| `attrs.names` | string[] | the open ones' names: at most 6, each at most 40 characters, scrubbed |
| `attrs.heating_loss` | bool | an open one is in a room that is calling for heat now. A room whose heating stops for an open window (the default) is not calling, so this is true only where it really heats. |

```json
{"id": "house:openings", "name": "Windows and doors", "kind": "openings", "icon": "contact", "cap": "view",
 "actions": [], "attrs": [], "allowed": true, "hold": false, "room": null,
 "state": {"on": false, "value": 1, "value_text": "1 open",
           "attrs": {"open": 1, "sensors": 2, "names": ["Okno loznice"], "heating_loss": true},
           "online": true, "battery": null, "at": null}}
```

## 6. Batteries: `house:batteries`

This item is present when some device reports a battery.

| | |
|---|---|
| id | `house:batteries` |
| kind | `batteries` |
| icon | `battery` |
| cap | `view` |
| actions | none |

The data is the device battery the dashboard uses (`battery`, or a Shelly's `battery.percent`).

| state field | type | meaning |
|---|---|---|
| `on` | bool | true = none below 20 % |
| `value` | int | the lowest % |
| `value_text` | string | `"5 %"` |
| `attrs.level` | string | `crit` (some below 10 %), `warn` (some below 20 %) or `ok` |
| `attrs.below_20` | int | devices below 20 % |
| `attrs.below_10` | int | devices below 10 % |
| `attrs.lowest_name` | string | the lowest one's name (at most 40 characters) |
| `attrs.lowest_pct` | int | its % |

```json
{"id": "house:batteries", "name": "Batteries", "kind": "batteries", "icon": "battery", "cap": "view",
 "actions": [], "attrs": [], "allowed": true, "hold": false, "room": null,
 "state": {"on": false, "value": 5, "value_text": "5 %",
           "attrs": {"level": "crit", "below_20": 2, "below_10": 1, "lowest_name": "Dvere", "lowest_pct": 5},
           "online": true, "battery": null, "at": null}}
```

## 7. Zigbee network: `status:zigbee`

| | |
|---|---|
| id | `status:zigbee` |
| kind | `zigbee` |
| icon | `router` |
| cap | `status` |
| actions | none |

It covers the Zigbee devices, online as the dashboard judges it: their availability, and silence
past the stale limit.

| state field | type | meaning |
|---|---|---|
| `on` | bool | true = none offline |
| `value` | int | devices online |
| `value_text` | string | `"5 online, 1 offline"` |
| `attrs.level` | string | `warn` with some offline, else `ok` |
| `attrs.online_n` | int | online |
| `attrs.offline_n` | int | offline |
| `attrs.dropped_name` | string \| null | the device that dropped off most recently (at most 40 characters) |
| `attrs.dropped_at` | int \| null | when: the moment Zigbee2MQTT said it went offline since this start of ZIGMon, else when it was last heard (epoch s) |

```json
{"id": "status:zigbee", "name": "Zigbee network", "kind": "zigbee", "icon": "router", "cap": "status",
 "actions": [], "attrs": [], "allowed": true, "hold": false, "room": null,
 "state": {"on": false, "value": 5, "value_text": "5 online, 1 offline",
           "attrs": {"level": "warn", "online_n": 5, "offline_n": 1, "dropped_name": "Hlavice",
                     "dropped_at": 1795874777},
           "online": true, "battery": null, "at": null}}
```

## 8. A timer on a switch: the action `timer`

It works on every item with `cap: "switch"` that has `toggle` among its actions: a socket, a light
(Shelly or Zigbee) or a Zigbee relay or switch. The extended catalogue lists `"timer"` in such an
item's `actions`. A 1.2.0 catalogue does not, but the action is accepted all the same.

The body:

```json
{"deck": "...", "id": "Lampa", "action": "timer", "minutes": 30, "by_hand": false, "held_ms": 0}
```

- `minutes`: a whole number from 1 to 720. Anything else, a string or a fraction included,
  answers 400.
- It turns the switch **on now**, and ZIGMon turns it **off** after the minutes. This is the
  executor's own "on for N" (`for:Nm`), kept in the store with the house's other timers (meta
  `timers`) and written at once.
  - After a restart, a timer already overdue goes off at once, and the others wait out their
    time.
  - A clock stepped by NTP moves it with the clock.
- A second `timer` on the same switch **replaces** the first.
- `off`, or a `toggle` that turns it off (the item was on), **cancels** it.
  - A `toggle` that turns it on leaves it.
  - A rule's "off for N" (its way back is *on*) is never cancelled by a deck.
- `by_hand: true`, as with on/off: the switch is taken over for the timer's length (plus 1 s) and
  given back when it goes off.
- The capability is `switch`, with its scope and hold exactly as for on/off.
- The event: `Stream Deck '<name>' (<type>) turned on Lampa for 30 min`.

The state, while a switch has a way back to off pending, carries `state.attrs.off_at` (epoch s,
rounded up). Count down to it.

- It also shows a rule's pending "on for N" on that switch, which is just as true.
- Without one pending, the key is absent, so a switch's attrs are as they always were.
- Every plugin sees `off_at`, extended or not.

```json
"state": {"on": true, "value": 0.0, "value_text": "0 W", "attrs": {"power": 0.0, "off_at": 1795875978},
          "online": true, "battery": null, "at": null, "held": false}
```

## 9. A room: `room:<id>`

There is one item per room ZIGMon knows (Settings, Rooms), and the id is ZIGMon's room id.

| | |
|---|---|
| id | `room:<room id>` |
| name | the room's name |
| room | the room's name |
| kind | `room` |
| icon | `room` |
| cap | `view` |
| actions | none |

| state field | type | meaning |
|---|---|---|
| `value` | number \| null | the room's temperature in °C: the heated room's thermometer, else the first device in the room reading one |
| `value_text` | string \| null | `"15.5 °C"` |
| `on` | bool \| null | some switch in the room is on; null when the room has no switch |
| `attrs.temperature` | number \| null | same as `value` |
| `attrs.humidity` | number \| null | the first device in the room reading humidity |
| `attrs.switches_on`, `attrs.switches` | int | sockets, lights and Zigbee switches on, out of all of them in the room |
| `attrs.lights_on`, `attrs.lights` | int | of them, the lights |
| `attrs.heated` | bool | the room is heated |
| `attrs.heat_mode` | string \| null | its heating mode (plan, comfort, eco, night, max, off, manual) |
| `attrs.heat_target` | number \| null | the temperature it wants now (°C) |
| `attrs.calling` | bool \| null | it is calling for heat |
| `attrs.members_n` | int | how many of the room's items **this deck may see** |

The extended catalogue's room item also carries, at the top level:

```json
"members": ["Lampa", "heat:temp:r1", "heat:room:r1", "zb:0x00158d0003000001:state", "read:0x00158d0003000003:contact"]
```

These are the ids of the items in that room that this deck may see (up to 200), in catalogue
order. Scroll them on a dial. Act on each with its own item, under its own capability; a room item
itself does nothing. When the room's items change (a device moved between rooms), `members_n`
changes. Fetch the catalogue again then.

```json
{"id": "room:r2", "name": "Ložnice", "room": "Ložnice", "kind": "room", "icon": "room", "cap": "view",
 "actions": [], "attrs": [], "allowed": true, "hold": false,
 "members": ["Zasuvka", "heat:temp:r2", "heat:room:r2", "read:0x00158d0003000002:temperature"],
 "state": {"on": true, "value": 15.5, "value_text": "15.5 °C",
           "attrs": {"temperature": 15.5, "humidity": 48.0, "switches_on": 1, "switches": 1, "lights_on": 0,
                     "lights": 0, "heated": true, "heat_mode": "comfort", "heat_target": 21.0, "calling": true,
                     "members_n": 4},
           "online": true, "battery": null, "at": null}}
```

## 10. Text messages: `status:sms`

This item is present when SMS is set up, or when ZIGMon's SMS log has anything.

| | |
|---|---|
| id | `status:sms` |
| kind | `sms` |
| icon | `message` |
| cap | `status` |
| actions | `["mute", "unmute"]`, granted under **system**, always held (section 0.2) |

Everything comes from ZIGMon's own SMS log, the one the SMS tab shows (meta `sms_log`). The
modem is never asked for this, and its inbox is never read for it.

| state field | type | meaning |
|---|---|---|
| `on` | bool \| null | the modem is online (null: SMS not set up) |
| `value` | int | texts received today |
| `value_text` | string | `"1 today"` |
| `online` | bool | false only when SMS is set up and the modem is offline |
| `attrs.level` | string | `ok`, `crit` (modem offline) or `unknown` |
| `attrs.modem_online` | bool \| null | what ZIGMon knows of the gateway: its last status reading is recent and not offline |
| `attrs.today` | int | texts received since midnight (local) |
| `attrs.last_from` | string \| null | the latest received text's sender, masked: `"…123"`. A network's name ("Vodafone") is kept. |
| `attrs.last_person` | string \| null | the household person ZIGMon matched that number to, if any (at most 30 characters) |
| `attrs.last_text` | string \| null | its text, scrubbed (section 0.3), at most 80 characters |
| `attrs.last_at` | int \| null | when it came (epoch s) |
| `attrs.muted_until` | int \| null | the house's alerts are hushed until then (epoch s), else null |

Mute is ZIGMon's existing hush, the system action *quiet* ("hush every alert for a while"). While
it lasts, no notification goes out by any road, and the events still record everything.

```json
{"deck": "...", "id": "status:sms", "action": "mute", "minutes": 60, "held_ms": 1500}
{"deck": "...", "id": "status:sms", "action": "unmute", "held_ms": 1500}
```

- `minutes` is a whole number from 15 to 240; anything else answers 400.
- `mute` sets the hush for that long. `unmute` ends it at once.
- The answer's state already carries the new `muted_until`.
- The events: `alerts hushed for 60 min (Stream Deck '<name>')` and
  `Stream Deck '<name>' (<type>) hushed the alerts for 60 min`.

```json
{"id": "status:sms", "name": "Text messages", "kind": "sms", "icon": "message", "cap": "status",
 "actions": ["mute", "unmute"], "attrs": [], "allowed": true, "hold": false, "room": null,
 "act": {"mute": {"cap": "system", "allowed": true, "hold": true},
         "unmute": {"cap": "system", "allowed": true, "hold": true}},
 "state": {"on": true, "value": 1, "value_text": "1 today",
           "attrs": {"level": "ok", "modem_online": true, "today": 1, "last_from": "…123", "last_person": null,
                     "last_text": "Ahoj, router … is down, see … and call me back later please, this text is longer",
                     "last_at": 1795874777, "muted_until": null},
           "online": true, "battery": null, "at": null}}
```

## Permissions, in short

| item | seen under | acts under | hold |
|---|---|---|---|
| `house:power`, `house:openings`, `house:batteries`, `room:<id>` | view | - | - |
| `status:security`, `status:zigbee`, `status:sms` | status | `ack` / `mute` / `unmute`: system | always |
| `heat:group:all`, `house:away` | climate (or view) | climate | as climate is set |
| `timer` on a switch | switch (or view) | switch | as switch is set |

- A deck that may not see an item gets 404 for it and never finds it in a catalogue, a state or a
  wait. A room's `members` and `members_n` count only what it may see.
- The defaults have not changed: view and status on, everything that acts off. Nothing new acts
  until the administrator grants it.
- No new capability was added. `system` is granted on the Stream Deck card as before, either for
  everything or for `status:security` and `status:sms` by name.

## What is not here

- **No new modem read.** The SMS item uses ZIGMon's own log only.
- **Acknowledge** clears the latest standing alert. ZIGMon has no separate "acknowledged but kept"
  state: the dashboard's "seen" removes an alert from the standing list, and so does this.
- **Blocked in the last 24 h** counts the addresses kept out since then (the list and its
  history). It is cached for a minute.
- **"Dropped off" time** is exact only for an offline report heard since ZIGMon started. Otherwise
  it is when the device was last heard.
- **Today's kWh** is null until the Energy summary has been made once after a start; ZIGMon makes
  it at startup.
