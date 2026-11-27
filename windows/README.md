# ZIGMon Notifier 1.0.0 (Windows)

A small tray app for Windows 10 and 11. It sits next to the clock, watches the
ZIGMon sensors you choose, and when one of them triggers (motion, a door opened,
water, smoke, gas, CO, tamper, vibration, a button press) it puts an alert card
on top of everything in the bottom-right corner, with a soft chime.

## Install

1. Unzip `ZigmonNotifier-1.0.0-win-x64.zip` anywhere you like, for example
   `%LOCALAPPDATA%\Programs\ZIGMon Notifier\`.
2. Run `ZigmonNotifier.exe`. It is a single self-contained file: no installer,
   no .NET to install, no administrator rights.
3. Windows SmartScreen may warn about an unsigned program the first time
   ("More info" -> "Run anyway").

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
   goes quiet again (door closed, dry, no motion).

## Use

* **Tray icon** - the dot says how it goes: green connected, grey connecting,
  red a problem (hover for the reason), amber alerts paused.
* **Right-click** - status, Watched sensors, Connection, Pause alerts (15 min /
  1 hour / until resumed), Sound, Bring to front and take focus, Close alerts
  after a minute, Start with Windows, Test alert, Open ZIGMon, Exit.
* **Alerts** - up to four stacked cards; a sensor that fires again updates its
  card (x2, x3 ...). Buttons: **Open ZIGMon**, **Mute 1 h** (this sensor only),
  **Dismiss** (or Esc). They show on top without taking your keyboard, and the
  taskbar button flashes; with "Bring to front and take focus" they also take
  the focus.
* Starting the exe a second time just opens the running one.

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
* No telemetry, no update checks, no other network traffic: the only server the
  app talks to is your ZIGMon. No log files are written.
* Start with Windows uses one value in
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; nothing is installed
  system-wide.

## Protocol (v1)

`GET {base}/index.php?api=notifier&do=hello|sensors|wait&after=N&boot=B` with
`X-Zigmon-Notifier: zmn_...` and `User-Agent: ZigmonNotifier/1.0.0 (Windows)`.
The app long-polls `wait` (the server holds it up to 25 s; the client gives up at
60 s), continues from each answer's `seq`, re-reads `sensors` on `reset` or a new
`boot`, backs off 1, 2, 4 ... 60 s on errors, waits at least a minute on 429, and
stops on 401, a rejected certificate or a redirect until you act.

## Building

Needs the .NET 10 SDK (Linux, macOS or Windows):

```
./build.sh
```

runs the tests (`ZigmonNotifier.Tests`, against an in-memory fake ZIGMon, a real
loopback HTTP listener and a real TLS server with a self-made certificate),
draws the icon (`tools/IconGen`) and publishes
`out/publish/ZigmonNotifier.exe` (self-contained, single file, compressed) and
`out/ZigmonNotifier-1.0.0-win-x64.zip`.

Layout:

* `ZigmonNotifier.Core` - everything that does not need Windows: protocol
  client and long-poll loop, models and JSON validation, address and key rules,
  certificate pinning, alert filtering, settings, the icon painter and the chime.
* `ZigmonNotifier` - the WPF app (tray icon, menu, windows, alerts, DPAPI,
  autostart).
* `ZigmonNotifier.Tests` - xunit tests of the core.
* `tools/IconGen` - writes `ZigmonNotifier/Assets/app.ico`.
