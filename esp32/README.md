# ZIGMon ESP32 Gateway

An ESP32 on your Wi-Fi that ZIGMon pairs with, detects and controls. Its features come as
**modules**; the first one is **Yeelock**, which opens Xiaomi Yeelock drawer and cabinet locks
over Bluetooth LE, several locks per gateway.

- **Secure:** HTTPS only, with a certificate the ESP makes for itself (ZIGMon pins its
  fingerprint); every ZIGMon request and every answer is signed (HMAC-SHA256, replay-proof);
  the web page has a PBKDF2-hashed admin password, sessions, CSRF tokens and a lockout.
- **Modular, with autodetect:** ZIGMon asks the gateway what it has (`/zigmon/v1/describe`) and
  shows whatever entities its modules expose, with no change in ZIGMon for a new module.
- **Everything on board:** a phone-friendly web UI, a serial CLI, settings in flash (NVS).

The wire protocol is [`PROTOCOL.md`](PROTOCOL.md) (protocol v1). Czech instructions:
[`NAVOD.md`](NAVOD.md).

> The Yeelock protocol is unofficial (community reverse engineering, credited below). Test the
> locks with the gateway before you rely on it, and keep a key.

Contents: [1 Hardware](#1-hardware) · [2 Arduino IDE](#2-arduino-ide-board-and-libraries) ·
[3 Flash](#3-flash) · [4 Wi-Fi from the CLI](#4-wi-fi-from-the-serial-cli) ·
[5 Password](#5-the-admin-password) · [6 Web UI](#6-open-the-web-ui) ·
[7 Locks](#7-add-the-locks) · [8 ZIGMon](#8-pair-with-zigmon) · [9 CLI](#9-the-serial-cli) ·
[10 Factory reset](#10-factory-reset) · [11 Troubleshooting](#11-troubleshooting) ·
[12 Security](#12-security-notes) · [13 New modules](#13-writing-a-new-module) ·
[14 Developing](#14-developing-and-tests) · [15 Credits](#15-credits)

## 1. Hardware

| | |
|---|---|
| **Primary target** | **ESP32-S3-N16R8** dev board: 16 MB flash, 8 MB octal PSRAM, BLE 5 |
| Also works | classic ESP32 (WROOM/WROVER), ESP32-C3 (anything with BLE and 4 MB+ flash) |
| Power | USB 5 V, permanently; place it within ~5-10 m of the locks |

The S3 and C3 have **BLE 5 only (no Classic Bluetooth)**. That is all the gateway needs: Yeelock
is a BLE device and NimBLE is a BLE-only stack. The firmware uses the PSRAM for its big buffers
(event and log history, JSON) and falls back to internal RAM on boards without it.

## 2. Arduino IDE: board and libraries

1. Arduino IDE 2.x: *File > Preferences > Additional boards manager URLs*:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
2. *Tools > Board > Boards Manager*: install **esp32 by Espressif Systems**, version **3.x**
   (3.0.0 or newer; the firmware targets the ESP-IDF 5 APIs of core 3.x). Core 2.x is not
   supported (see the notes in `core_https.h`, `core_cert.cpp`).
3. *Tools > Manage Libraries* (Library Manager), install exactly:

   | Library Manager name | Version | Why |
   |---|---|---|
   | **NimBLE-Arduino** by h2zero | **1.4.3** (any 1.4.x) | BLE. **Not 2.x**: its scan and client API changed. |
   | **ArduinoJson** by Benoit Blanchon | **7.4.2** (any 7.x) | JSON with size caps and filters |

   Everything else comes with the core: WiFi, Preferences, ESPmDNS, mbedTLS,
   esp_https_server / esp_http_server, esp_http_client and the certificate bundle, esp_random.
4. *Tools* menu for the **ESP32-S3-N16R8**:

   | Setting | Value |
   |---|---|
   | Board | **ESP32S3 Dev Module** |
   | Flash Size | **16MB (128Mb)** |
   | PSRAM | **OPI PSRAM** |
   | Partition Scheme | **16M Flash (3MB APP/9.9MB FATFS)** (or another 16 MB scheme with an app partition of 3 MB or more) |
   | USB CDC On Boot | **Enabled** if you use the native USB port for the CLI, **Disabled** if you use the UART port (see below) |
   | Upload Speed | **921600** |
   | CPU Frequency | 240 MHz |
   | Core Debug Level | None |

   Other boards: classic ESP32 = "ESP32 Dev Module", ESP32-C3 = "ESP32C3 Dev Module", with
   Partition Scheme **"Huge APP (3MB No OTA/1MB SPIFFS)"** (or **"Minimal SPIFFS (1.9MB APP
   with OTA)"**); the firmware is about 1.6-1.9 MB, more than the default 1.2 MB app slot.

**The two USB ports of an S3 board.** Most N16R8 boards have two USB-C sockets:

- **"USB"** (native USB of the S3, GPIO 19/20). The serial CLI appears here only with
  *USB CDC On Boot: Enabled*. Uploading works here too (if an upload fails, hold BOOT, tap
  RESET, release BOOT, upload again).
- **"COM"** / **"UART"** (a USB-serial chip wired to UART0). The CLI appears here with
  *USB CDC On Boot: Disabled*. This is the simplest choice: flash and use the CLI on the same
  port, no BOOT button needed.

Pick one and set *USB CDC On Boot* to match; with the wrong setting the board runs fine but the
serial monitor stays silent.

## 3. Flash

1. Open `esp32/ZigmonGateway/ZigmonGateway.ino` in the Arduino IDE (the folder's other `.h` /
   `.cpp` files open as tabs; `web/` holds the web UI's sources, already embedded in
   `web_assets.h`).
2. Choose the board settings above and the port, then **Upload**.
3. Open *Tools > Serial Monitor* at **115200** baud, line ending **"Newline"** (or "Both NL &
   CR"). On the first boot the gateway generates its key and certificate (a few seconds), then
   prints the CLI prompt `zgw>`.

## 4. Wi-Fi from the serial CLI

```
zgw> wifi scan
zgw> wifi set "My Home Wi-Fi" mypassword
zgw> status
```

Quote an SSID with spaces. The password is echoed as `*` while you type it and never printed.
`status` shows the IP address and the name `zigmon-gw-xxxxxx.local`. A fixed address:
`wifi static 192.168.1.50 255.255.255.0 192.168.1.1 [dns]`; back to DHCP: `wifi dhcp`.

## 5. The admin password

The web UI does nothing until a password is set. Either in the CLI:

```
zgw> password
New admin password: ************
Repeat it: ************
```

or on the web UI's first-run page, which is open only for **10 minutes after a boot** (or after
the CLI command `webinit`). 8-64 characters; it is stored only as PBKDF2-HMAC-SHA256
(10 000 rounds, random salt).

## 6. Open the web UI

1. Browse to `https://zigmon-gw-xxxxxx.local/` (or `https://<IP>/`). `http://` redirects.
2. The browser warns that the certificate is not trusted: the gateway made it itself. Before
   you accept it, **compare the fingerprint**: run `fingerprint` in the CLI and compare it
   with the certificate's SHA-256 fingerprint in the browser (click the warning / the padlock >
   certificate details). If they match, accept.
3. Log in. Five wrong passwords lock the login for 60 s, doubling up to an hour.

Pages: **Overview** (Wi-Fi, time, ZIGMon, modules, recent activity), **Wi-Fi** (scan,
choose, static IP), **ZIGMon** (pair, fingerprint, unpair), one page per **module**, and
**System** (names, password, log, reboot, factory reset).

## 7. Add the locks

Each lock needs its **serial number** (S/N: on its label, and in its BLE name `EL_<SN>`) and its
**`ble_sign_key`**, a secret the Yeelock app gets from the Yeelock cloud when the lock is added
to your account. Whoever has the key and is in BLE range can open the lock, so treat it like a
physical key. On the **Yeelock** page, *Add lock* offers three ways:

- **Account: import from my Yeelock account.** Enter the phone's country code (e.g. `420`,
  without `+`), the phone number (without the country code) and the Yeelock password. The
  gateway logs in to `api.yeeloc.com` **once, from the ESP**, over verified HTTPS (the
  certificate bundle of the core; there is no insecure fallback), lists your locks with
  "in range" / "not in range", and saves only the ones you tick. The password and the access
  token live only in RAM for the two requests and are wiped; the fetched keys are wiped from
  RAM after 10 minutes. Rate-limited to 5 tries per 10 minutes. CLI:
  `yeelock fetch 420 123456789` (asks the password without echo), then
  `yeelock import <SN>... | all`.
- **Scan:** a BLE scan lists nearby `EL_*` locks with their signal, marks those already added
  and those found in your account. Pick one to fill the S/N, then paste the key.
- **By hand:** name, S/N and the key in hex (8-32 bytes; spaces or `:` are fine). CLI:
  `yeelock add "Front drawer" <SN> <signkeyhex>`.

The manual way never contacts any cloud. If you prefer to fetch the key on a PC, the tool this
firmware's protocol knowledge comes from does it:
[aso824/yeehack](https://github.com/aso824/yeehack): `python3 yeehack.py fetch`, and it can
test the key from the PC (`yeehack.py do unlock <SN> <key>`).

**Every new lock (or new key) is checked right away:** the gateway connects, reads the battery
and sends only a time-sync packet. It never unlocks as a test. A wrong key shows as a red
*"Wrong sign key"* banner on the lock's card (the lock answered `TX_SIGN_INVALID`); "reachable,
key OK" means all is well. The *Check* button repeats it.

Each lock card shows the state (derived from the lock's own `UNLOCK_CMP` / `LOCK_CMP`
notifications), battery, signal, the last action and its result, and the buttons **Open**
(unlock, then the lock re-locks itself), **Unlock**, **Lock** and **Refresh** (battery). Open
and Unlock ask for confirmation. Settings: scan time, connect timeout, battery check interval.

The clock must be set for Yeelock commands: NTP sets it when there is internet; otherwise ZIGMon
sets it with its first signed request, or *Use this browser's time* on the Overview page.

## 8. Pair with ZIGMon

1. Web UI > **ZIGMon** > **Pair with ZIGMon** (or the CLI `pair`): a **6-digit code**, valid
   10 minutes, single use.
2. In ZIGMon: **Settings > Devices > ESP32 gateways > Add**: the gateway's address and the code.
3. ZIGMon shows the certificate fingerprint: check it matches the one on the gateway's ZIGMon
   page (or `fingerprint` in the CLI), then confirm.
4. ZIGMon detects the modules and their entities (the locks) and controls them. A lock's Open
   and Unlock are marked sensitive: ZIGMon asks for confirmation (hold-to-confirm on a Stream
   Deck).

A wrong code is spent anyway; five wrong codes lock pairing for 15 minutes. **Unpair** on the
ZIGMon page (or `unpair`) makes the gateway forget ZIGMon's key.

## 9. The serial CLI

115200 baud, one command per line; Backspace works, quotes `"..."` / `'...'` and `\` escapes
are understood, arrow keys are ignored, Ctrl-C drops the line. `help` lists everything.

| Command | Does |
|---|---|
| `help [cmd]` | every command, one line each |
| `status` | firmware, uptime, Wi-Fi (SSID, IP, RSSI), time, pairing, modules |
| `wifi scan` / `wifi set <ssid> [password]` / `wifi forget` | Wi-Fi |
| `wifi static <ip> <mask> <gw> [dns]` / `wifi dhcp` | addressing |
| `hostname <name>` | mDNS `<name>.local` |
| `password` | set the admin password (asked twice, echoed as `*`) |
| `webinit` | re-open the first-run password page for 10 minutes |
| `fingerprint` | the certificate's SHA-256 |
| `pair` / `unpair` | show a pairing code / forget ZIGMon |
| `time [unix]` | show or set the clock (UTC) |
| `modules` | each module, its version and its entities |
| `yeelock list` | the locks with battery and last result |
| `yeelock add <name> <SN> <signkeyhex>` / `yeelock key <id> <hex>` / `yeelock del <id>` | manage locks |
| `yeelock scan` | nearby `EL_*` locks (results in the log) |
| `yeelock check <id>` | reach + key test (never unlocks) |
| `yeelock do <id> open\|unlock\|lock\|battery` | run an action |
| `yeelock fetch <zone> <username>` / `yeelock import <SN>...\|all` | import from the Yeelock account |
| `log [error\|warn\|info\|debug]` | set the level, show recent lines |
| `reboot` | restart |
| `factory-reset` | erase everything (asked twice) |

## 10. Factory reset

```
zgw> factory-reset
zgw> factory-reset YES        (within 30 s)
```

or *System > Factory reset* in the web UI (type `FACTORY RESET` and the password). It erases the
whole NVS: Wi-Fi, admin password, ZIGMon pairing, every module's settings (all locks and keys)
and the certificate, then reboots as new. In ZIGMon, remove the gateway and pair it again.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Serial monitor silent | Wrong USB port for the *USB CDC On Boot* setting (section 2); baud 115200. |
| "Sketch too big" | Partition scheme with a 3 MB app slot (section 2). |
| NimBLE compile errors (`setConnectTimeout`, `getScan`...) | NimBLE-Arduino 2.x installed: install 1.4.3. |
| `httpd_req_async_handler_begin` not declared | Very old core (ESP-IDF < 5.1): add `#define GW_HTTPD_ASYNC 0` at the top of `gw_config.h`; ZIGMon then polls instead of long polling. |
| `esp_crt_bundle.h` not found / `esp_crt_bundle_attach` undefined | The core lacks the certificate bundle: `#define GW_YEELOCK_CLOUD 0` in `yeelock_cloud.h` (the manual and yeehack ways remain). |
| Browser says 431 / "header too large" | Too many cookies for the gateway's address: open it by IP or in a private window. |
| Web UI "set the admin password first" | No password and the 10-minute window passed: `password` or `webinit` in the CLI. |
| Lock "not found" | Out of range or wrong S/N; wake the lock (touch it) and *Scan*. BLE range through a drawer is ~5 m. |
| "could not connect" | The Yeelock app on a phone holds the connection: close it. |
| "Wrong sign key" | The key does not belong to this lock (or the lock was re-added to an account, which changes the key): import it again. |
| "the gateway's clock is not set" | No NTP: pair ZIGMon (it sets the time), or *Use this browser's time*. |
| ZIGMon: "certificate changed" | The gateway was factory-reset (new certificate): re-pair in ZIGMon and compare the new fingerprint. |
| Pairing "locked" | Five wrong codes: wait 15 minutes. |

## 12. Security notes

- No secret is ever printed in full (serial, web, log, API): the UI shows "set (..xy)" at most.
- NVS is not encrypted by default: someone with the board in their hands can read the keys from
  flash. Keep the gateway where strangers can't take it, or enable flash encryption + NVS
  encryption (ESP-IDF; outside the Arduino IDE's options).
- Don't expose the gateway to the internet (no port forwarding). ZIGMon reaches it on the LAN.
- Request bodies are capped at 8 KB, JSON is parsed with nesting limits, all string fields are
  length-checked, and comparisons of secrets are constant-time.

## 13. Writing a new module

A module is one class implementing `gw::Module` (`core_module.h`), in one new file, plus one
registration line in `ZigmonGateway.ino`:

```cpp
// mod_relay.cpp - a relay on a GPIO, as entity "relay.main" (type "switch").
#include "core_module.h"
#include "core_events.h"
#include "core_jobs.h"
#include <Preferences.h>

namespace gw {
namespace {
class Relay : public Module {
 public:
  const char* id() const override { return "relay"; }          // also the CLI word, NVS "m_relay"
  const char* name() const override { return "Relay"; }
  const char* version() const override { return "1.0.0"; }
  const char* icon() const override { return "switch"; }
  void begin() override {
    Preferences p; p.begin(nvsNamespace().c_str(), true); pin_ = p.getUChar("pin", 4); p.end();
    pinMode(pin_, OUTPUT);
  }
  void describe(JsonArray out) override {
    JsonObject e = out.add<JsonObject>();
    e["id"] = "relay.main"; e["module"] = "relay"; e["type"] = "switch"; e["name"] = "Relay";
    JsonArray a = e["actions"].to<JsonArray>(); a.add("on"); a.add("off");
    e["attrs"].to<JsonArray>(); e["confirm"].to<JsonArray>();
  }
  void state(JsonObject out) override { stateOf("relay.main", out["relay.main"].to<JsonObject>()); }
  bool stateOf(const char* eid, JsonObject st) override {
    st["available"] = true; st["value"] = on_ ? "on" : "off"; st["busy"] = false;
    st["attrs"].to<JsonObject>(); st["last"] = nullptr; return true;
  }
  CommandResult command(const char* eid, const char* action, JsonObjectConst) override {
    if (strcmp(action, "on") && strcmp(action, "off")) return CommandResult::fail(400, "on or off");
    char job[12]; jobs::create(eid, action, job);
    on_ = !strcmp(action, "on"); digitalWrite(pin_, on_);
    jobs::finish(job, true, on_ ? "on" : "off");               // emits the "result" event
    return CommandResult::accepted(job);
  }
  void settingsSchema(JsonObject s) override {
    JsonObject f = s["settings"].to<JsonArray>().add<JsonObject>();
    f["key"] = "pin"; f["label"] = "GPIO"; f["type"] = "number"; f["min"] = 0; f["max"] = 48;
  }
  void settingsGet(JsonObject v) override { v["pin"] = pin_; }
  bool settingsSet(JsonObjectConst in, String& err) override { /* validate, save to NVS */ return true; }
 private:
  uint8_t pin_ = 4; bool on_ = false;
};
}  // namespace
Module* relayModule() { static Relay r; return &r; }
}  // namespace gw
```

and in `ZigmonGateway.ino`: declare `namespace gw { Module* relayModule(); }` and add
`gw::registry::add(gw::relayModule());` in `registerModules()`. That's all: ZIGMon detects
`relay.main` as a switch, the web UI draws its page from the schema, `relay ...` reaches the
module's `cliCommand()`.

The contract a module keeps:

- **Entities** (`describe`): `id` = `<module>.<item>`, `type` one of `lock`, `switch`, `sensor`,
  `binary_sensor`, `button`, `cover`, `number`, `select`, `text`; `actions`; `attrs`
  (`{key,label,type,unit,min,max}`); `confirm` (actions ZIGMon must confirm). A `number` may
  carry `unit`, `min`, `max`, `step`; a `select` its `options`; a `set` action gets
  `args: {"value": v}` (PROTOCOL.md section 8).
- **STATE** (`stateOf`): `available`, `value`, `busy`, `attrs`, `last` (`action`, `ok`, `at`,
  `msg`), small (it is kept per event, up to ~380 bytes).
- **Slow work** (radio, I/O that waits): never in `command()`. Create a job
  (`jobs::create`), answer 202, do the work on a task (BLE work: a `ble::Job` subclass submitted
  with `ble::submit()`, which runs on the shared BLE task), then `jobs::finish()`. Use
  `events::emitEntity(id, "state")` for changes nobody asked for.
- **Locking:** module methods are called with the gateway lock held; `loop()` and your own tasks
  are not, so take `gw::Guard` there before touching shared state.
- **Settings schema** (`settingsSchema`): `{"settings":[FIELD...], "collection":{...}}` where
  FIELD is `{key,label,type,required,min,max,unit,pattern,help,placeholder,options}` and `type`
  is `text`, `number`, `bool`, `select`, `secret` (write-only, shown masked, empty keeps the
  stored value), `password` (sent once, never shown) or `slug`. A `collection` (`key`, `title`,
  `item`, `max`, `fields`, optional `discover`, `check`, `import`) makes the web UI draw item
  cards with add / edit / delete, a scan tab, a check button and an import flow, backed by
  `itemsGet/itemSave/itemDelete/discoverStart/discoverGet/webCall`.
- **Secrets:** never log or print them; mask with `maskSecret()`; declare CLI arguments that
  carry one in `cliSecrets()` so the CLI echoes them as `*`; wipe buffers with `secureZero()`.
- **NVS:** your namespace is `m_<id>` (`nvsNamespace()`); factory reset clears it.
- **Pins** on the ESP32-S3-N16R8: **don't use GPIO 35, 36, 37** (the octal PSRAM), nor 26-32
  (flash), 19/20 (native USB), 43/44 (UART0, the CLI on the COM port); 0, 3, 45, 46 are strapping
  pins (avoid as outputs at boot). Good free pins: 1, 2, 4-18, 21, 38-42, 47, 48 (48 drives the
  RGB LED on many boards).

## 14. Developing and tests

```
esp32/tests/run.sh                 # needs only g++ (and python3, node for the web checks)
python3 tools/esp32-embed-web.py   # after editing web/: regenerates web_assets.h
python3 esp32/tests/webmock.py 8099   # the web UI against fake data at http://127.0.0.1:8099/
```

`run.sh` builds and runs the unit tests of the portable parts (request signing and
verification, the pairing proof and gate, PBKDF2, Yeelock packets and notification decoding,
the cloud request's form encoding, the CLI tokenizer and line editor, the replay ring, the
event ring, sessions and the login throttle) against a vendored SHA-256/SHA-1, asserting the
vectors of `PROTOCOL.md` section 7; then it syntax-checks every source file for the S3, the
ESP32 and the C3 against the stub headers in `tests/stubs/` (Arduino core 3.x, ESP-IDF 5,
mbedTLS 3, NimBLE-Arduino 1.4, ArduinoJson 7); then it checks that `web_assets.h` is current and
that the served JavaScript parses.

Source map: `core_*` is the core (config, net, crypto, cert, https, auth, pairing, events, CLI,
log, jobs, BLE task, registry), `api_*` the request handlers, `mod_*` the modules, `yeelock_*`
the Yeelock protocol, `web/` the web UI.

## 15. Credits

The Yeelock protocol knowledge (packets, notification codes, GATT characteristics, the cloud
endpoints) comes from **[aso824/yeehack](https://github.com/aso824/yeehack)** (Apache-2.0)
and the original reverse engineering in **[cnrd/yeelock](https://github.com/cnrd/yeelock)**.
The firmware is an independent C++ implementation; see [`NOTICE`](NOTICE).
