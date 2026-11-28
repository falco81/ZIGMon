# Computed values for the Stream Deck (ZIGMon 5.59.4, plugin 1.3.0)

ZIGMon computes aggregate values over the house and offers them as deck items. A new plugin
action, **Computed**, shows them with everything a Reading has: looks, colours, thresholds,
decimals, graph, text sizes and the honest scales.

The items exist only in the **extended** catalogue (the opt-in of `PROTOCOL-5.59.4.md`).
`hello.features` gains `"calc"`.

## Item ids

```
calc:<fn>:<metric>:<scope>
```

- **`fn`:**

  | fn | meaning |
  |---|---|
  | `sum` | the sum |
  | `avg` | the mean |
  | `min` | the smallest |
  | `max` | the largest |
  | `count` | how many have the metric |
  | `on` | how many are on |
  | `off` | how many are off |
  | `pct_on` | the % of them that are on |
  | `spread` | max - min |

- **`metric`:**

  | metric | unit |
  |---|---|
  | `power` | W |
  | `energy_today` | kWh |
  | `energy_total` | kWh |
  | `temperature` | °C |
  | `humidity` | % |
  | `pressure` | hPa |
  | `illuminance` | lx |
  | `co2` | ppm |
  | `battery` | % |
  | `linkquality` | |
  | `state` | (on/off: only with `on`, `off`, `pct_on`, `count`) |
  | `open` | contacts (with `count`/`on`, where on = open) |
  | `online` | devices (with `count`/`on`/`off`) |
  | `room_temperature` | °C: the members are the rooms, each with its `room:<id>` temperature (with `min`/`max`/`avg`/`spread`, scope `inside` only: "Coldest room", "Warmest room") |
  | `battery_low` | devices with a battery, on = at or below ZIGMon's battery warning (Settings, 30 % by default) (with `on`/`pct_on`: "Low batteries") |

  `room_temperature` and `battery_low` were added by the server side (see "What the server does" below).

- **`scope`:**

  | scope | what it covers |
  |---|---|
  | `all` | everything |
  | `kind=<socket\|light\|switch\|dimmer\|thermostat\|sensor\|cover>` | one kind |
  | `room=<room id>` | one room |
  | `room=<room id>,kind=<…>` | one kind in one room |
  | `outside` | the outside readings |
  | `inside` | everything except outside and the coordinator |

The catalogue lists every combination that has at least one member and makes sense: no `sum`
of temperature; `on`/`off`/`pct_on` only for `state`, `open`, `online` and `battery_low`. The plugin never
invents ids; it picks from the catalogue.

**The comma in `room=<id>,kind=<…>`.** `ids` is a comma-separated string, so this id has a comma of
its own. Send it as it is: ZIGMon puts a piece that starts with `kind=` back onto the `calc:…:room=…`
before it (`calc:sum:power:room=r1,kind=light,house:power` is two ids). Room ids that are not
`[A-Za-z0-9_.-]{1,60}` get no room scopes.

## Item fields

- `kind`: `calc`
- `cap`: `view`
- `actions`: `[]`
- `icon`: by metric
- `name`: in words, e.g. "Power · all lights", "Average temperature · Ložnice", "Lights on · Obývák"
- `room`: the room name for a room scope, else null
- `attrs`: one number attr `{key:"value", label, type:"number", unit, min, max}`. `min`/`max` give the
  honest scale where known: 0-100 for % metrics (and `pct_on`), 0..`members` for `on`/`off`/`count`,
  0-255 for `linkquality`, `min` 0 for power, energy and a `spread`, the sum of the members' max for
  power when known; otherwise `null` (never missing). ZIGMon knows no socket's maximum today, so a
  power `max` is `null`.
- `calc`: `{"fn","metric","scope","members": n, "unit": "W"}`

State:

```json
{"on": null, "value": 412.5, "value_text": "412.5 W",
 "attrs": {"value": 412.5, "members": 7, "known": 6, "min_of": "…name…", "max_of": "…name…"},
 "online": true}
```

- `known` is how many members had a value.
- `min_of` and `max_of` name the member at the extreme, for `min`/`max` (both for `spread`), at most
  60 characters, scrubbed as every deck text; `null` otherwise.
- `online` is false when `known` is 0.

## History

`deck_history` serves calc items too: the same spans (1 h / 6 h / 24 h / 7 d) and about 48
points.

- `power` over `all` and `kind=light|socket` comes from the stored samples where ZIGMon has
  them. The others come from an in-memory ring that ZIGMon fills each minute for every calc
  item a deck watches. At most 300 items are ringed; a watch keeps an item ringed for 7 days.
  History therefore starts when a deck first watches it, and the plugin then fills in from live.
- In detail: `calc:sum:power:all` has exactly `house:power`'s history. `kind=light|socket` take the
  Energy tab's hourly figures for 6 h / 24 h / 7 d; for 1 h (ZIGMon keeps no minutes per role)
  they come from the ring.
- A deck *watches* an item by naming it in the `ids` of `state` or `wait`. The ring keeps a point a
  minute for 6 h (1 h and 6 h) and a half-hourly mean for 7 days (24 h and 7 d). Points are thinned
  to the `points` asked, the newest kept as it is. ZIGMon restarted: the rings start again.

## Permissions

The `view` cap applies.

- With `view` on "every thing", every calc item is visible.
- With `view` on "only these", a calc item is visible only when it is granted by its own id.
- The value is always computed over all of the item's members. Granting the aggregate is the
  administrator's explicit choice, so a deck sees the total even if it may not see each socket.
- The admin "Only these" list groups calc items under "Computed".

## What the server does (ZIGMon 5.59.4)

Notes from the server side for the plugin: what the catalogue actually holds.

### The fns each metric offers

| metric | fns | scopes beyond `all` |
|---|---|---|
| `power` | `sum`, `avg`, `max`, `min`, `count` | kind, room, room+kind |
| `state` | `on`, `off`, `pct_on`, `count` | kind, room, room+kind |
| `energy_today` | `sum`, `max`, `min`, `avg` | kind, room, room+kind |
| `temperature` | `avg`, `min`, `max`, `spread`, `count` | kind, room, inside, outside |
| `room_temperature` | `min`, `max`, `avg`, `spread` | `inside` only (no `all`) |
| `humidity` | `avg`, `min`, `max`, `spread` | kind, room, inside, outside |
| `open` | `on`, `count` | room, inside, outside |
| `online` | `off`, `on`, `count` | kind, room |
| `battery_low` | `on`, `pct_on` | kind, room |
| `battery` | `min`, `avg`, `count` | kind, room |
| `co2`, `illuminance`, `pressure` | `avg`, `min`, `max` | room, inside, outside |
| `linkquality` | `avg`, `min`, `max` | kind, room |
| `energy_total` | `sum`, `max` | kind, room |

- `min`, `max` and `spread` need at least two members: the extremes of one are its own reading.
- A kind in a room is listed only when it is not the whole room (else it says what the room says).
- The order, and so what the cap of 600 keeps: the house (`all`), then `inside`/`outside`, then each
  kind, then each room, then each kind in a room; within each, the metrics in the order of the table.

### The members

- **Power and energy:** the metered sockets and lights (Shelly), as the dashboard's house total and
  the Energy tab count them, so `calc:sum:power:all` equals `house:power`. Their kind is `light` or
  `socket` by their role. `energy_today` is the Energy summary ZIGMon keeps warm (`null` until it is
  made; while a deck watches one, ZIGMon remakes it once a minute). `energy_total` is the meters' own
  total in kWh.
- **`state`:** every socket, light and relay item (each endpoint of a Zigbee relay is one).
- **Readings, batteries, signal, contacts, online:** every device but groups, the SMS gateway, the
  server in front and the Wi-Fi access points. A device's kind is its Zigbee items' (thermostat,
  cover, light, dimmer, switch), else `sensor`; a socket's or light's by its role. A reading of a
  device that is offline is not known (`known` leaves it out), except the weather's.
- **Outside:** the weather (open-meteo, `weather:outside`) and every device in a room whose name
  says it is out of doors: one of its words is outside, outdoor(s), garden, yard, terrace, balcony,
  patio, venku, venek, zahrada, zahradka, dvur/dvůr, terasa, balkon. The weather has readings only
  (no battery, no `online`). **Inside:** every member that is neither outside nor the coordinator.

### Names

"Power · all", "Power · lights", "Power · Obývák", "Power · lights in Obývák", "Average power",
"Highest power", "Lowest power", "Power meters", "Energy today", "Most energy today", "Energy
total", "Things on · all", "Lights on · all", "Lights on · Obývák", "Lights off", "Lights on (%)",
"Lights (count)", "Average temperature · inside", "Lowest temperature", "Highest temperature",
"Temperature spread", "Thermometers", "Coldest room", "Warmest room", "Average room temperature",
"Room temperature spread", "Average humidity", "Windows open · all", "Window sensors", "Devices
offline · all", "Thermostats offline · all", "Devices online", "Devices (count)", "Light devices
(count)", "Low batteries · all", "Low batteries (%)", "Lowest battery", "Average battery", "Battery
devices", "Average CO2", "Average illuminance", "Average pressure", "Average signal", "Weakest
signal". The part before " · " is the attr's `label`.

### Speed

The values are worked out with the rest of the catalogue (at most twice a second), from what that
pass already holds: no database read per item.
