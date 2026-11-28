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
of temperature; `on`/`off`/`pct_on` only for `state`, `open` and `online`. The plugin never
invents ids; it picks from the catalogue.

## Item fields

- `kind`: `calc`
- `cap`: `view`
- `actions`: `[]`
- `icon`: by metric
- `name`: in words, e.g. "Power · all lights", "Average temperature · Ložnice", "Lights on · Obývák"
- `room`: the room name for a room scope, else null
- `attrs`: one number attr `{key:"value", unit, min, max}`. `min`/`max` give the honest scale where
  known: 0-100 for % metrics, 0..the sum of the members' max for power when known, otherwise absent.
- `calc`: `{"fn","metric","scope","members": n, "unit": "W"}`

State:

```json
{"on": null, "value": 412.5, "value_text": "412.5 W",
 "attrs": {"value": 412.5, "members": 7, "known": 6, "min_of": "…name…", "max_of": "…name…"},
 "online": true}
```

- `known` is how many members had a value.
- `min_of` and `max_of` name the member at the extreme, for `min`/`max`, at most 60 characters.
- `online` is false when `known` is 0.

## History

`deck_history` serves calc items too: the same spans (1 h / 6 h / 24 h / 7 d) and about 48
points.

- `power` over `all` and `kind=light|socket` comes from the stored samples where ZIGMon has
  them. The others come from an in-memory ring that ZIGMon fills each minute for every calc
  item a deck watches. At most 300 items are ringed; a watch keeps an item ringed for 7 days.
  History therefore starts when a deck first watches it, and the plugin then fills in from live.

## Permissions

The `view` cap applies.

- With `view` on "every thing", every calc item is visible.
- With `view` on "only these", a calc item is visible only when it is granted by its own id.
- The value is always computed over all of the item's members. Granting the aggregate is the
  administrator's explicit choice, so a deck sees the total even if it may not see each socket.
- The admin "Only these" list groups calc items under "Computed".
