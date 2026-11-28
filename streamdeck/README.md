# ZIGMon for Stream Deck

Control your ZIGMon home from an Elgato **Stream Deck XL** (32 keys) or **Stream Deck +**
(8 keys, 4 dials and a touch strip), and see its state live: sockets, lights and dimmers,
heating, blinds, scenes, readings, the house's power, security, windows, batteries, rooms,
timers, SMS and ZIGMon's own health. Every key is drawn in ZIGMon's
dashboard colours and redraws the moment something changes in the house.

Nothing can be controlled unless ZIGMon allows it: Stream Deck control is switched on in
ZIGMon, each computer is paired and approved there, each Stream Deck on it is approved there,
and the administrator grants the functions one by one.

*Czech: [NAVOD.md](NAVOD.md).*

## What you need

- Windows 10 or 11 with the Stream Deck app **7.1 or newer**.
- ZIGMon **5.59 or newer**, reachable from that computer over **https** (plain http only when
  ZIGMon runs on the same computer). The graphs from ZIGMon's history and the heated rooms'
  target, mode and thermometer need a ZIGMon **newer than 5.59.0** (with 5.59.0 the rest works as in 1.0).
  The ten actions new in 1.3 need **ZIGMon 5.59.4** (the rest works with an older one as before).
- The other Stream Deck models work too (keys only, sized for their grid); the XL and + are
  the ones the plugin is designed for.

## 1. Download and install

1. In ZIGMon, as the administrator: **Settings → Messages → Stream Deck**.
2. Switch on **Allow Stream Deck control**.
3. Click **Download ZIGMon for Stream Deck 1.3.0**. Compare the SHA-256 shown there with the
   file if you like (`Get-FileHash ZIGMon.streamDeckPlugin` in PowerShell).
4. Double-click the downloaded `.streamDeckPlugin`. Stream Deck asks to install it; say yes.
   A **ZIGMon for Stream Deck** category appears in the actions list.

## 2. Pair this computer with ZIGMon

1. Drag any ZIGMon action onto a key (or a dial of the Stream Deck +) and click it to open its
   settings (the property inspector).
2. Type your dashboard address, for example `https://zigmon.example.net`, and press
   **Connect**.
3. A code like **K7Q-4PX** appears big in the settings **and on every ZIGMon key**.
4. In ZIGMon → **Settings → Messages → Stream Deck** the request appears with the computer's name, its
   Stream Decks (drawn to scale), the address it came from and the same code. Check the code
   matches, choose what this computer may do and **Approve** (with your PIN) - or **Deny**.
5. The keys come alive within a second or two. The settings now show the house, ZIGMon's
   version, your Stream Decks (approved or waiting) and a summary of what is allowed.

The code lives 15 minutes. One pairing covers every Stream Deck on this Windows account; a
Stream Deck plugged in later shows **Approve deck** on its keys until the administrator
approves it under the installation in ZIGMon.

### A self-signed certificate

If Windows does not trust ZIGMon's certificate, the settings show **Check the certificate**
with its SHA-256 fingerprint, who it is for and until when. Compare the fingerprint with the
one ZIGMon shows, then **Trust this certificate**. From then on the plugin accepts **only that
certificate** for that address - even one Windows would trust. If it ever changes, the plugin
stops and tells you (renewed certificate? compare and trust the new one; otherwise someone may
be in the way). Nothing - not even the pairing request - is sent before the certificate is
accepted.

## 3. The actions

All of them work on keys of any Stream Deck; the ones with a dial icon also work on the dials
of the Stream Deck +, where they draw their own touch-strip layout. In each one's settings
you pick the item from a searchable list grouped by room; items ZIGMon does not allow this
deck to control are shown with a lock, and a live preview shows the key.

| Action | Key | Dial (Stream Deck +) |
|---|---|---|
| **Control** | Any item ZIGMon allows: socket, light, relay, valve, rule... Icon, name, room, On/Off with a glow in the item's colour, its value (e.g. 42 W). A press toggles it (or turns it on / off / runs / opens / closes - your choice). | Push = the press, turn = its main value (brightness, setpoint, position), strip: icon, name, value, slider or state pill. |
| **Reading** | A reading, big, with its unit, a trend arrow, a sparkline of the latest values, amber/red when outside the thresholds you set. A press refreshes. | Strip: the value over a full-width sparkline. |
| **Thermostat** | An arc gauge: the current temperature in the middle, the target on the arc, a flame while heating, mode and preset. A press: next mode, next preset, boost, **show the details** or **set one mode** (your choice). | Turn = setpoint (0.1 / 0.5 / 1 ° per click), push = next mode/preset, touch = boost. Strip: current, target, mode, the arc and the flame. |
| **Light** | Bulb glowing with the brightness, the percentage and a level bar. A press switches it. | Turn = brightness (1-20 % per click), push = on/off, strip: slider. |
| **Blinds** | A window with the blind drawn at its position, Open/Closed/percentage, Opening…/Closing…. A press: open/close (by where it is), stop, open or close. | Turn = position, push = stop/open/close, touch = stop. Strip: the window. |
| **Scene** | Runs a scene, sequence or group of actions. A green tick when done, a red cross when not. | Push or touch = run. |
| **ZIGMon status** | ZIGMon's own health: open alerts, blocked addresses, the proxy, the Zigbee gateway, health - green, amber or red. | Strip: the same with a state pill. |
| **House power** *(1.3)* | The house's watts now, today's kWh, a graph over 1 h / 6 h / 24 h / 7 d. | Turn = the span. |
| **Network security** *(1.3)* | Alerts standing and addresses blocked; a red shield on an alert. Held press = acknowledge the latest. | Push (held) = acknowledge. |
| **Heating everywhere** *(1.3)* | Rooms heating n/m, the common mode or Mixed, min–max °C. Press = next mode, or one mode, for every room. | Turn / push = the mode. |
| **Away / Home** *(1.3)* | Away or Home, lights on, rooms heating. Press = switch, and turn off the switches you chose. | Push = switch. |
| **Windows & doors** *(1.3)* | How many are open and which; red when one lets the heat out. | Strip: count, names, a bar of sensors. |
| **Batteries** *(1.3)* | How many are low, the lowest by name and %. | Strip: the same with its level. |
| **Zigbee network** *(1.3)* | Online / offline, the one that dropped off last. | Strip: the same with a bar. |
| **Timer** *(1.3)* | A switch on for N minutes with a live countdown; press again = off. | Turn = minutes, push = start / cancel. |
| **Room** *(1.3)* | Temperature, humidity, what is on, its heating. | Turn = through its items, push = switch the one shown. |
| **SMS** *(1.3)* | Show the latest / write a new one in the desktop app, or the SMS status with mute (held). | Push = the same. |
| **Computed** *(1.3)* | A value ZIGMon computes over the house - total power, lights on, the coldest room... - shown as a Reading; picked with a What / How / Where builder or one of the Popular ones. | Strip: as a Reading's. |

Turning a dial moves the value on the strip at once; the clicks are gathered and sent to
ZIGMon as one change (ZIGMon keeps it within the item's range and step).

### Heating by room (1.1)

**Thermostat** also takes a room of the Heating tab (*Heating in …*), as the dashboard shows it:
the **target**, the **measured** temperature from the room's own thermometer (the one set for
the room in ZIGMon), and the **mode** in the dashboard's words - Comfort, Eco, Night, Max, Off,
Plan, By hand, and **By hand until 14:30** while a hand-set temperature holds. A press can set
one mode outright or go round all of them (Plan and By hand included); turning the dial sets
the room by hand exactly as the dashboard's *Set … by hand* slider (the same road in ZIGMon,
under the *climate* permission and its hold). **Show details (3 s)** makes a press show the
mode, target, measured temperature and thermometer on the key for three seconds instead.

Since 1.2, going round with **Next mode** steps the key at once and sends ZIGMon only the mode
you stop on, 1.2 s after the last press. Before, every mode on the way was set, so going round
to Max passed through Off and shut the room's valves on the way. A key that needs a hold to
confirm still sends each confirmed press.

Since 1.3, **Go round only these** lets Next mode (and Next preset, and the heating-everywhere key)
go round a chosen few - say Comfort, Max and Off - in their usual order; with none ticked it goes
round all of them as before. The dial of the heating-everywhere key steps through the same few.

### Graphs (1.1)

**Reading** and **Thermostat** draw a graph of **ZIGMon's own history** (what its History tab
draws), sent ready and thinned to about 48 points for the span you choose - **1 h, 6 h, 24 h or
7 d** - so it is there at once. The plugin appends the live values and asks again every few
minutes and when the span changes. Optional: min / max labels, and a thermostat's target as a
dashed line. ZIGMon 5.59.0 sends no history; then the graph grows from what the plugin sees.

### Looks (1.1)

Every action's settings have a **Look** section with live thumbnails of the item as it is now:
**Classic** (1.0's key - keys set up before 1.1 look exactly as they did), **Minimal**,
**Big value**, **Solid fill**, **Neon**, **Ring gauge**, **Two-tone**, **Glass**, **Bold label**,
**Status dot**, **Light** and **High contrast** - and ten clear ones that say one thing big
with at most one small line: **Huge**, **Pill**, **Orb**, **Tile**, **Gauge**, **Bars**,
**Wave**, **Aurora**, **Outline** and **Mono** - and twenty more as clear, each with its own
shape: **Diagonal** (a coloured corner), **Hex** (a hexagon plate), **Stripe** (a side stripe
that fills), **Switch** (a toggle switch), **LCD** (a retro screen), **Dial** (a knob in a ring
of ticks), **Ticket** (a coloured stub), **Bubble** (a speech bubble), **Frame** (corner
brackets), **Shadow** (a card with a coloured shadow), **Line** (the value on one line),
**Tube** (a thermometer tube), **Stamp** (a giant faint icon), **Pastel** (soft colour, dark
type), **Carbon** (carbon weave and a light strip), **Grid** (a grid of lamps), **Tab** (a
folder with the name on its tab), **Rise** (a rising sun), **Spot** (a spotlight) and
**Button** (a real key, pressed when on) - and eighteen name-first ones, which put the name
first, big and whole (on two lines and smaller rather than cut, as the name's fit says), with the
status right with it - On / Off, the temperature with its unit, the watts, the brightness, the
position, the mode, the countdown or the count - so both read at once even on an XL's small keys:
**Name bar** (the name on a coloured band, the status under it), **Caption** (the name centred,
the status in a pill), **LED** (the name, a lit lamp and the status), **Two rows** (the name and
the status split by a hairline), **Plate** (an engraved nameplate with a status window),
**Ticker** (the name over a status strip), **Card** (the name over an icon tile and the status),
**Halves** (the name on top, the status on a coloured half), **Stacked** (the name, the status, a
tiny icon), **Corner** (the name big, the status in a corner badge), **Lined** (the name
underlined in the accent when on), **Terminal** (a console: the name, then `> status`),
**Marquee** (the name in a ring of bulbs), **Widget** (a phone widget, the name at its foot),
**Sign** (a road sign with the name on it), **Note** (an index card, the status highlighted),
**Pass** (a lanyard pass, the name big) and **Glow** (the name itself glows when on) - 60 looks in
all, with an On / Off pair above them. Then the
**colours**, in two tabs: the **On colour** (Auto by kind) and the **Off colour** (Auto keeps the
look's own grey). Each is one of 24 named colours (the first ten as in 1.1, plus indigo, sky,
cyan, mint, lime, gold, peach, coral, rose, magenta, lavender, brown, slate and white) or a colour
of your own: the *Custom* swatch opens a picker - a saturation / brightness square, a hue bar and a
`#RRGGBB` field checked as you type - and the key, the On / Off pair and the thumbnails follow as
you drag. An off key is drawn in the Off colour where its look would be grey (border, icon, state,
tile - as fits each look, Classic and the touch strip too); items that are never on or off (a
reading, a scene, a status) take the On colour as their colour and the Off colour while idle. The
settings keep a colour's name or exactly `#RRGGBB`; anything else is dropped, and no colour ever
comes from ZIGMon. Then a **label** for every action (40 characters),
how **long names** are laid out (shrink to fit, two lines breaking at hyphens, or one line cut as
in 1.0), and **what the key shows**, each on its own: icon, name, room, state / value, the second
value (W, brightness, target, movement, trend), mode / preset, graph (history, level bar, the
blind's window) and battery - with *Everything* and *Icon only* shortcuts. Every look honours
them; offline, the lock, the hand and the hold ring stay readable in all of them. On the
Stream Deck + the look, accent and choices reach the touch strip as far as its layout allows
(its paper, the ink of its words, the icon's tile; a hidden part is left empty).

### Hold to confirm

When the administrator ticks **Hold to confirm** for a function (system actions always have
it), a short press does nothing but say **Hold to confirm**. Keep the key (or the dial) pressed:
a ring fills, and after 1.5 s the action runs - you can let go once it says *Confirmed*.

Since 1.1 any key or dial that does something can ask for it too: the **Hold to confirm
(1.5 s)** switch (the hand) in its settings. A key press, a dial push and a touch then need the
same hold with the same ring; turning a dial stays free. Where ZIGMon requires the hold the
switch shows on and locked (*ZIGMon requires it for this item*). The hand is on the key
whenever a hold applies.

### By hand (1.2, ZIGMon 5.59.3)

A **Control** key on a socket, a light or a relay has a **By hand** switch, as ZIGMon's own
buttons do. Switched on from this key, the thing is taken over: rules and schedules leave it
alone. Switched off from it, they take over again. A small figure on the key shows it is taken
over, whether by this key, another key or a button. An older ZIGMon ignores the switch.

### The ten new actions (1.3, ZIGMon 5.59.4)

Ten more actions show what ZIGMon 5.59.4 sums up for the whole house, and act on it. Each works
on keys and on the Stream Deck + dials (with a touch strip of its own), has its own Classic drawing
and every one of the 60 looks, the On / Off colours, the label, long names and the choice of what
the key shows - exactly like the actions above. Their settings show a **Now** card with what the
key has no room for (every window open, the whole latest alert, a room's items...).

They need **ZIGMon 5.59.4 or newer**: only a ZIGMon that offers them is asked for them, and with an
older one the keys say **Needs ZIGMon 5.59.4 or newer** and do nothing. The house's own summaries
need no picking: put the action on a key and it shows them (if ZIGMon lets this deck see them).

#### House power (1.3, ZIGMon 5.59.4)

The house's power now, big (**452 W**, **1.84 kW**), today's **kWh** under it and a graph over
**1 h, 6 h, 24 h or 7 d** (ZIGMon's own: the minute peaks for 1 h, hourly averages of the metered
sockets for the longer ones). Lit while anything draws power. A press refreshes it. On a dial,
**turn = the span**; the strip shows the figure over the graph. The **Now** card splits it into
sockets and lights.

#### Network security (1.3, ZIGMon 5.59.4)

The alerts standing (**2 alerts**, a dot for each) and the addresses kept out (**14 blocked ·
37 in 24 h**); the shield turns **red** on an alert, and says **Quiet** in green when there is
none. The **Now** card shows the **latest alert's text** (addresses and numbers hidden by ZIGMon)
and when it came. A press **held 1.5 s acknowledges the latest alert** - the dashboard's *seen*;
older ones stay. That needs the **System** permission for this deck (for everything, or for
*Network security* by name) and is **always held**; without it the key still shows everything
and says *needs System in ZIGMon* when pressed. With nothing standing it says *All clear*.

#### Heating everywhere (1.3, ZIGMon 5.59.4)

How many heated rooms are calling for heat (**1/4**, with a segment per room), their **common
mode** - or **Mixed** - and the lowest and highest room temperature (**18.5–21.0°**). A press:
**Next mode** for every room (shown at once and sent 1.2 s after the last press, as a
thermostat's Next mode; from Mixed it starts at Plan) or **one mode for all** (Plan, Comfort, Eco,
Night, Max, Off or By hand). On a dial, turning steps the mode the same way. Under the *climate*
permission and its hold.

#### Away / Home (1.3, ZIGMon 5.59.4)

**Away** or **Home** (the heating's away switch; *by the dates* when the away dates are in force),
with the **lights on** and the **rooms heating**. A press switches it. In the settings you can also
tick **switches and lights to turn off when going Away**: they are sent after the away switch,
each as its own command under its own permission - one this deck may not switch is skipped (the
key says how many were), and one that needs a hold makes the Away key need one when going away.
Coming home turns nothing back on.

#### Windows & doors (1.3, ZIGMon 5.59.4)

How many are **open** and which - the first one or two on the key, all of them in the **Now**
card - or **Closed** in green. A segment per contact sensor. **Red, with a flame on the tile,
when an open one is in a room that is heating** (the heat is going out of the window). A press
refreshes.

#### Batteries (1.3, ZIGMon 5.59.4)

How many batteries are **low** (below 20 %), and the lowest one by name with its per cent and a
battery drawn at its level - amber, red when one is below 10 %; **All OK** in green otherwise.

#### Zigbee network (1.3, ZIGMon 5.59.4)

The Zigbee devices **online**, or how many are **offline** (amber), with the one that **dropped
off** last and when, and a bar of online against offline.

#### Timer (1.3, ZIGMon 5.59.4)

On a switch (a socket, a light, a relay): a press turns it **on for 5, 10, 15, 30, 60 or 120
minutes** - or any number from 1 to 720 you type - and ZIGMon turns it **off** after them (even if
this computer sleeps; it is ZIGMon's own timer, kept over a restart). While it runs the key shows a
**live countdown** in a ring that drains; **a press again turns it off**, which cancels the timer.
On a dial, **turn = the minutes** (5, 10, 15, 20... up to 12 h), **push = start** (or cancel).
By hand and hold work as on Control. **Control** keys on a switch get a **Timer** press as well,
with the same minutes, and show the countdown by the state.

#### Room (1.3, ZIGMon 5.59.4)

A room at a glance: its **temperature** big, the **humidity**, how many of its switches are on
(**1/3**), and its **heating** mode and target (*Comfort → 21°*, in orange while it calls for heat).
A key press refreshes. On a Stream Deck + dial, **turn = scroll through the room's items** (the ones
ZIGMon lets this deck see, in ZIGMon's order); the strip shows the one chosen with its state and a
row of dots, and **a push switches it or runs it** with that item's own rules - its own permission,
its own hold.

#### SMS (1.3, ZIGMon 5.59.4)

One action, three modes:

- **Show latest** - texts received today, who sent the latest (a contact's name or `…123`) and
  when, with an **unread** badge. A press shows the latest SMS, with Reply, in the **ZIGMon
  desktop app linked to this Stream Deck**.
- **Write new** - a press opens a new message in that desktop app, addressed to the numbers and
  contact groups you add in the settings (`+420 777 123 456` or `group:Family`, at most 20), or to
  nobody. The deck has no list of contacts: ZIGMon finds the numbers of a group itself.
- **Status** - the latest SMS's sender (masked) and today's count, *modem offline* in red when the
  gateway is down, and **Muted until 15:47** while the alerts are hushed. A press **held 1.5 s
  mutes all alerts** for 15 min - 4 h (your choice) and, while muted, unmutes. Under **System**,
  always held.

*Show latest* and *Write new* need the **sms** permission, and ZIGMon hands them to a desktop app
linked to this Stream Deck installation (ZIGMon → Settings → Messages → Stream Deck). When none is
running the key says **No desktop app running** - *link one in ZIGMon*.

### Computed (1.3, ZIGMon 5.59.4)

A value **ZIGMon computes over the house**, shown exactly like a Reading: the big value with its
unit, the trend, the graph over 1 h / 6 h / 24 h / 7 d, your amber and red thresholds, the
decimals and your label, in every look and colour, with the same honest scales. For example the
total power of everything, the power of the lights only, how many lights are on, the average
temperature inside, the coldest room, the windows open, the devices offline, the low batteries or
today's energy.

Instead of a list of hundreds of items, the settings have a **builder**:

1. **What** - Power, Energy today, Energy total, Temperature, Rooms' temperature (one per room, inside:
   the coldest or warmest room), Humidity, Pressure, Light level, CO₂, Battery, Low battery (at or
   below ZIGMon's battery warning), Signal, On / off, Open or Online.
2. **How** - Sum, Average, Min, Max, Count, On, Off, % on or Spread (the highest minus the lowest),
   only those that make sense for it: there is no sum of temperatures.
3. **Where** - All, Inside or Outside; or one kind (lights, sockets, switches, dimmers,
   thermostats, sensors, blinds) and/or one room.

Only what ZIGMon really computes in your house can be picked; the rest is greyed out (no
"Pressure" without a barometer, no "coldest outside" with one thermometer outside). Each choice
moves the others to the nearest value there is, and the settings show its name and the value now.
**Popular** above it picks one in one click: total power, power of lights, power of sockets, lights
on, average inside, coldest room, windows open, devices offline, low batteries, energy today.
*Now* names the room or device at the extreme (the coldest room's name, the lowest battery's
device) and how many of the members had a value.

A press refreshes. The values need **ZIGMon 5.59.4** with computed values (its hello says `calc`);
an older one makes the key say **Needs ZIGMon 5.59.4 or newer**. The administrator grants them under
**view**: with *every thing*, all of them; with *only these*, each one by name (listed under
*Computed*). A granted value is always computed over all its members, even those this deck may not
see one by one.

### What the keys tell you

| Key says | Meaning |
|---|---|
| **Connect** | Not paired yet - open the key's settings. |
| the code, big | Pairing: approve it in ZIGMon. |
| **Approve deck** | This Stream Deck is not approved in ZIGMon yet. |
| **Switched off** | Stream Deck control is switched off in ZIGMon. |
| **ZIGMon offline** | No answer; the plugin tries again (1 s, 2 s, ... up to a minute). |
| **Certificate** | The server's certificate needs a decision - see above. |
| **Disconnected** | The installation was revoked in ZIGMon - pair again. |
| a lock | The item is visible but not allowed for this deck. |
| a hand | Hold to confirm. |
| **Needs ZIGMon 5.59.4 or newer** | One of the 1.3 actions on an older ZIGMon. |
| **No desktop app running** | An SMS key: no ZIGMon desktop app linked to this Stream Deck is running. |
| a number in a pill | Unread SMS. |

## Security

- **Nothing without ZIGMon's say-so**: ZIGMon checks every command - switched on, the key,
  the installation, the deck approved, the item allowed for its capability, the hold, the value.
  The plugin only draws what ZIGMon reports and asks; it never decides on its own.
- **The key** (`zsd_...`) is given once on approval and stored only encrypted with Windows
  **DPAPI** for the current user (through PowerShell's ProtectedData; the key is passed on
  stdin, never on a command line). ZIGMon itself keeps only its SHA-256. It is sent only in a
  header, never in an address, and never written to a log - the plugin logs at "info", never
  "trace".
- **https only** (http only to `localhost`), **no redirects** followed, answers size-capped
  and checked field by field; everything shown on a key is escaped.
- **Certificates**: what Windows trusts (and the name must match), or exactly the one you
  pinned.
- **Revoking** in ZIGMon stops this computer at its next request; **Disconnect** in the
  settings forgets the key here.

## Updates

When ZIGMon has a newer plugin, every action's settings show **Update to x.y.z**. Clicking it
downloads the package from ZIGMon, checks that its manifest is **signed with ZIGMon's
release key** (Ed25519; the keys are built into the plugin) and that the file's size and
SHA-256 match the signed manifest, saves it as `%TEMP%\ZIGMon-x.y.z.streamDeckPlugin` and
opens it - Stream Deck then asks you to install it. Anything that does not check out is not
opened.

## Troubleshooting

- *There is no deck API at that address*: ZIGMon is older than 5.59, or the address is not
  the dashboard's.
- *Too many requests*: pairing is limited to 10 tries an hour per address and commands to
  10 a second; wait a moment.
- *The saved key could not be read*: the settings were copied from another Windows account
  or computer - pair again.
- The plugin's log: `%APPDATA%\Elgato\StreamDeck\Plugins\com.zigmon.streamdeck.sdPlugin\logs`.

## Building (developers)

`streamdeck/build.sh` on Linux (Node.js 20+, python3): installs the exact dependencies,
embeds the release keys from `deploy/release-keys/`, draws the layouts and icons, runs the
tests (unit, rendering, end to end against a fake ZIGMon, TLS pinning with real
certificates), bundles with rollup, smoke-tests the bundle with the real SDK against a fake
Stream Deck app, then `streamdeck validate` and `streamdeck pack`, and writes
`dist/com.zigmon.streamdeck.streamDeckPlugin` and `dist/plugin.json` (signed by
`tools/make-release.sh`). The package is rewritten with fixed timestamps, so the same sources
give the same bytes. `node out/scripts/shots.js <dir>` renders the keys, the touch strip and
every property inspector to PNG (needs Playwright).
