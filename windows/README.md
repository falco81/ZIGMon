# ZIGMon Notifier 1.2.0 (Windows)

A small tray app for Windows 10 and 11. It sits next to the clock, watches the
ZIGMon sensors you choose, and when one of them triggers (motion, a door opened,
water, smoke, gas, CO, tamper, vibration, a button press - or a **condition**
an administrator set in ZIGMon on any device, such as "temperature ≥ 25 °C" or
"preset changed to eco") it puts an alert card on top of everything in the
bottom-right corner of the monitor you choose, with the sound you choose.

## Install

1. **Download it from your ZIGMon:** Settings -> Messages -> Desktop app ->
   **Download ZIGMon Notifier** (the file's SHA-256 is shown next to the button).
   Put `ZigmonNotifier.exe` in a folder you can write to, for example
   `%LOCALAPPDATA%\Programs\ZIGMon Notifier\` (not Program Files: the app
   replaces its own file when it updates).
2. It needs the **.NET 10 Desktop Runtime** (Microsoft, free, once per
   computer). If it is missing, Windows says so on the first start and offers
   the download; by hand: https://dotnet.microsoft.com/download/dotnet/10.0 ->
   ".NET Desktop Runtime 10", Windows x64.
3. Run `ZigmonNotifier.exe`. It is a single file: no installer, no
   administrator rights.
4. Windows SmartScreen may warn about an unsigned program the first time
   ("More info" -> "Run anyway").

## Updates

New versions come with ZIGMon's own updates, and the app **updates itself from
the ZIGMon server it is connected to** - after connecting (when the server says
it has a newer version) and then every 6 hours. Every update is checked first:
the manifest (`notifier.json`) must carry a valid Ed25519 signature by
**ZIGMon's release key** (the public keys from `deploy/release-keys` are built
into the app), its product, file name and version must be right and newer than
the running one, and the download must have exactly the signed size and
SHA-256. It never goes back to an older version and never runs anything that
failed a check. The running exe is renamed to `ZigmonNotifier.exe.old`, the new
one is moved into its place and started with `--updated <old version>`; it
takes over, deletes the `.old` and shows "Updated to 1.x.y". If any step fails,
the old exe is put back.

The menu has an updates section: **Update automatically** (on by default; off:
a new version is shown and installed when you click it), **Check for updates
now**, and a status line ("Up to date – 1.2.0", "Updating to 1.3.0…", "Update
failed: <reason>"). A ZIGMon from before updates (no `app` in hello) is asked
only from "Check for updates now", and its "not known" answers count as "no
updates".

To remove it: Exit from the tray menu, switch off "Start with Windows" first if
it was on, delete the exe and `%APPDATA%\ZIGMon Notifier\`.

## Set up

1. In ZIGMon, an administrator makes a key: **Settings -> Messages -> Desktop app**.
   Choose a name (e.g. "Office PC") and, if you like, which sensors it may see.
   The key (`zmn_...`) is shown **once** - copy it.
2. The first start opens **Connection** (later: right-click the tray icon ->
   Connection...). Enter the dashboard address (`https://zigmon.example.net`)
   and paste the key, then **Test connection**. A green card shows the house,
   the ZIGMon version and the key's name. **Save and connect**.
3. Right-click -> **Watched sensors...** (or double-click the icon): switch on the
   sensors that should alert. "Also when it clears" also alerts when the sensor
   goes quiet again (door closed, dry, no motion) or a condition is no longer
   met. Each watched sensor can have **its own sound** (the drop-down under it,
   with a play button); "Default sound" uses the one from Alert settings.
4. Conditions (ZIGMon 5.58 and later) are made in ZIGMon, per key: Settings ->
   Messages -> Desktop app -> the key -> **Conditions** -> Add condition (any
   device, any attribute, > ≥ < ≤ = ≠, between, outside, contains, is on/off,
   changes, with hysteresis). They appear in Watched sensors with a gauge icon,
   the condition in words and the value now.

## Alert settings

Right-click -> **Alert settings...** (everything is saved at once and remembered):

* **Sound** - on/off; the default sound: Chime, Doorbell, Bell, Beeps, Pulse,
  Alarm, Siren, Klaxon, or **your own .wav file** (uncompressed PCM or float,
  up to 20 MB; when it cannot be read the default chime plays instead).
* **How long it plays** - once, 5 s, 15 s, 30 s, 1 min, 5 min, or until the
  alert is dismissed (it stops by itself after 30 minutes). Dismiss, Mute,
  Open ZIGMon or Esc stop it at once, and so does the last card closing.
* **Volume** - 0-100 % of the Windows volume, with a Test button.
* **Close by itself after** - never, 10 s, 30 s, 1 min, 5 min, 15 min (the time
  starts again when the sensor fires again or the mouse is over the card).
* **Show alerts on** - the primary monitor, the monitor with the mouse pointer,
  or a particular monitor (by its Windows display number; when it is unplugged,
  the primary one is used until it is back). "Show me" puts a test alert there.
* **Bring to front and take the keyboard focus.**

## Use

* **Tray icon** - the dot says how it goes: green connected, grey connecting,
  red a problem (hover for the reason), amber alerts paused.
* **Right-click** - status, Watched sensors, Connection, Pause alerts (15 min /
  1 hour / until resumed), Sound, Bring to front and take focus, Alert
  settings..., Start with Windows, Test alert, Open ZIGMon, Exit.
* **Alerts** - up to four stacked cards; a sensor that fires again updates its
  card (x2, x3 ...). Buttons: **Open ZIGMon**, **Mute 1 h** (this sensor only),
  **Dismiss** (or Esc). They show on top without taking your keyboard, and the
  taskbar button flashes; with "Bring to front and take focus" they also take
  the focus.
* Starting the exe a second time just opens the running one.
* **Test alert from ZIGMon** (1.3.0): Settings → Messages → Desktop app has a
  **Test alert** button on each key. The computer holding that key shows a
  "Test alert" at once, whatever it watches, pauses or mutes (an event of kind
  `test`, device `zigmon-test`, sent to that key only).

## Security

* **The key is read-only.** It can list the sensors it was given and receive
  their trigger events - nothing else. The administrator can revoke it in ZIGMon
  at any time; the app then shows "Key not accepted" and stops.
* **Stored encrypted.** The key is kept in `%APPDATA%\ZIGMon Notifier\settings.json`
  only as a DPAPI blob (CurrentUser scope plus app-specific entropy): only your
  Windows account on this computer can decrypt it. The window never shows it
  again - only "saved key ...xQ".
* **It travels in one place only:** the `X-Zigmon-Notifier` request header over
  HTTPS. Never in a URL, never in a log, never in an error message (anything the
  server echoes back is scrubbed).
* **HTTPS only.** Plain `http://` is refused except for `localhost`,
  `127.0.0.1` and `::1`. TLS 1.2/1.3, Windows' own certificate validation.
* **Self-made certificates** are not accepted silently. The app shows the
  certificate's subject, validity and SHA-256 fingerprint and you can choose
  **Trust this certificate** after comparing the fingerprint with the server's
  (`openssl x509 -noout -fingerprint -sha256 -in cert.pem`). From then on that
  host:port accepts *only* that exact certificate - even a different one that
  Windows would trust. If the certificate changes, the app stops and asks.
* **Redirects are never followed** (the key must not be carried to another
  host); a saved key is only ever sent to the host it was saved for.
* Answers are size-limited (2 MB), JSON is validated field by field, and every
  name from the server is cleaned (control and bidi characters removed) and
  shown as plain text only.
* "Open ZIGMon" opens only the validated dashboard address.
* No telemetry, no other network traffic: the only server the app talks to is
  your ZIGMon - updates too (`do=update`, `do=download`, with the same key
  header, certificate rules, no redirects, and the download capped at the
  signed size). No log files are written.
* Start with Windows uses one value in
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; nothing is installed
  system-wide.

## Protocol (v1)

`GET {base}/index.php?api=notifier&do=hello|sensors|wait|update|download&after=N&boot=B` with
`X-Zigmon-Notifier: zmn_...` and `User-Agent: ZigmonNotifier/1.2.0 (Windows)`.
The app long-polls `wait` (the server holds it up to 25 s; the client gives up at
60 s), continues from each answer's `seq`, re-reads `sensors` on `reset` or a new
`boot`, backs off 1, 2, 4 ... 60 s on errors, waits at least a minute on 429, and
stops on 401, a rejected certificate or a redirect until you act.

## Building

Needs the .NET 10 SDK (Linux, macOS or Windows):

```
./build.sh
```

writes `ZigmonNotifier.Core/ReleaseKeys.cs` from `../deploy/release-keys/*.pub`,
runs the tests (`ZigmonNotifier.Tests`, against an in-memory fake ZIGMon, a real
loopback HTTP listener and a real TLS server with a self-made certificate; RFC 8032
vectors and openssl-made signatures for Ed25519; the updater against a temp folder),
draws the icon (`tools/IconGen`), publishes the framework-dependent single-file
exe (deterministic: two builds give the same bytes), copies it to
`dist/ZigmonNotifier.exe` and writes `dist/notifier.json` (one line, the exact
bytes `tools/make-release.sh` signs into `dist/notifier.json.sig`), and zips
`out/ZigmonNotifier-1.2.0-win-x64.zip`. `dist/` is committed with each release.

Layout:

* `ZigmonNotifier.Core` - everything that does not need Windows: protocol
  client and long-poll loop, models and JSON validation, address and key rules,
  certificate pinning, alert filtering, settings, the icon painter and the chime,
  Ed25519 verification and the updater (verify, download, stage, swap, roll back).
* `ZigmonNotifier` - the WPF app (tray icon, menu, windows, alerts, DPAPI,
  autostart).
* `ZigmonNotifier.Tests` - xunit tests of the core.
* `tools/IconGen` - writes `ZigmonNotifier/Assets/app.ico`.
* `tools/Probe` - the core's client from the command line, for the end-to-end
  tests: `Probe <sensor>` follows the event stream; `Probe --update-check` asks
  `/update`, verifies it (embedded keys, or the `*.pub` in the folder named by
  `ZIGMON_PROBE_KEYS`) and prints `UPDATE <version> VERIFIED` and, after the
  download checked out, `DOWNLOADED <sha256>`. Both read the address and the key
  from standard input.
