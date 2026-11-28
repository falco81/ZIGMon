# ZIGMon for Stream Deck

Control your ZIGMon home from an Elgato **Stream Deck XL** (32 keys) or **Stream Deck +**
(8 keys, 4 dials and a touch strip), and see its state live: sockets, lights and dimmers,
heating, blinds, scenes, readings and ZIGMon's own health. Every key is drawn in ZIGMon's
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
- The other Stream Deck models work too (keys only, sized for their grid); the XL and + are
  the ones the plugin is designed for.

## 1. Download and install

1. In ZIGMon, as the administrator: **Settings → Messages → Stream Deck**.
2. Switch on **Allow Stream Deck control**.
3. Click **Download ZIGMon for Stream Deck 1.1.0**. Compare the SHA-256 shown there with the
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
**Status dot**, **Light** and **High contrast**, with an On / Off pair above them. Then an
**accent** (Auto by kind, or one of 10 colours), a **label** for every action (40 characters),
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
