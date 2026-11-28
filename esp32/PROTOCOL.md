# ZIGMon ESP32 Gateway: the contract (protocol v1, ZIGMon 5.59.4, firmware 1.0.0)

This is the contract between the firmware (`esp32/ZigmonGateway/`, an Arduino IDE sketch) and
ZIGMon (`zigmon.py`, `web/index.php`). Both sides build from this document and test against the
vectors in section 7. Anything added later must be additive, so that an older ZIGMon or an older
firmware ignores what it doesn't know.

## 1. What it is

An ESP32 (classic, S3 or C3) on the home Wi-Fi. Its features come as **modules**; the first is
**Yeelock**, which drives Xiaomi Yeelock locks over BLE and handles several locks on one ESP.
ZIGMon pairs with the gateway, **detects** its modules and what they expose (**entities**),
and controls them. An entity is described generically, so a future module (a relay, a reed
contact, an IR blaster, a sensor) needs no change in ZIGMon to be shown and controlled.

## 2. Security

- **Transport: HTTPS only**, on port 443, from `esp_https_server`.
  - On first boot the firmware makes an EC P-256 key and a self-signed certificate with mbedTLS
    (CN `zigmon-gw-<last 6 hex of the MAC>`, valid 20 years) and keeps both in NVS.
  - Its **SHA-256 fingerprint** (of the DER certificate, as 64 lowercase hex) is shown by the
    serial CLI (`fingerprint`) and on the web UI's System page.
  - Port 80 serves only a redirect to https.
- **ZIGMon pins** that fingerprint when it pairs, the same way the Stream Deck plugin pins a
  self-signed certificate. A different certificate later is refused, and ZIGMon offers
  "re-pair" with a clear warning.
- **Pairing:**
  1. On the ESP (web UI → ZIGMon → "Pair with ZIGMon", or the CLI `pair`), the user gets a
     **6-digit code**, valid 10 minutes and used once.
  2. In ZIGMon (Settings → Devices → ESP32 gateways → Add), the user enters the address and
     the code. ZIGMon shows the certificate fingerprint, and the user confirms it matches the
     ESP's.
  3. ZIGMon `POST /zigmon/v1/pair` with
     `{"v":1,"nonce":"<32 hex>","proof":"<hex>","zigmon":"<ZIGMon's name>","key":"<64 hex>"}`, where:
     - `proof = HMAC-SHA256(key = the 6 code digits as ASCII, msg = "zigmon-pair-v1\n" + fingerprint + "\n" + nonce)`;
     - `key` is a fresh random 32-byte **device key** from ZIGMon.
  4. The ESP checks the proof (constant-time compare), keeps the key in NVS and answers
     `{"ok":true,"id":"<gateway id = 12 hex of the MAC>","name":...,"fw":"1.0.0"}`.
  5. The code is spent whether pairing succeeds or fails. Five wrong proofs lock pairing for
     15 minutes.
- **Every later request from ZIGMon** carries these headers:
  - `X-Zigmon-Ts`: Unix seconds;
  - `X-Zigmon-Nonce`: 32 hex characters;
  - `X-Zigmon-Sig`: the signature (below).

  The ESP rejects with 401 when:
  - the time is more than 120 s from its clock, while its clock is set;
  - it has seen the nonce in the last 300 s (it keeps a ring of 64);
  - the signature is wrong.

  While its clock is not set (`time < 1700000000`), the ESP **takes ZIGMon's `X-Zigmon-Ts` as
  its time**, but only after the signature checks. This lets Yeelock work in a home without
  internet NTP.

  The signature:

  ```
  sig = hex(HMAC-SHA256(device key, METHOD + "\n" + PATH + "\n" + TS + "\n" + NONCE + "\n" + hex(SHA256(body))))
  ```

  - PATH includes the query string, exactly as sent.
  - The body is the raw request bytes; an empty body hashes `""`.
- The ESP **signs its answers too**, so a pinned-cert failure can't be papered over:
  - `X-Gw-Sig = hex(HMAC-SHA256(device key, "resp\n" + NONCE + "\n" + status code + "\n" + hex(SHA256(response body))))`.
  - ZIGMon checks it.
- `POST /zigmon/v1/unpair` (signed) forgets the key. Factory reset forgets everything.
- **The web UI is password-protected:**
  - **Setting the password:** none is set at first. Until one is set (from the CLI
    `password`, or the web UI's first-run page), the web UI shows only "Set the admin
    password" and nothing else. The first-run page is only reachable within 10 minutes of a
    boot, or after the CLI `webinit`.
  - **Storing it:** the password is kept as PBKDF2-HMAC-SHA256 (10000 rounds, 16-byte salt),
    never in clear.
  - **Sessions:** a 128-bit random token in a `HttpOnly; Secure; SameSite=Strict` cookie,
    expiring after 12 h. At most 4 sessions; a new one evicts the oldest.
  - **Brute force:** after 5 failed logins, 60 s lockout, doubling up to 1 h.
  - **CSRF:** every POST needs the `X-Gw-Csrf` header equal to the session's CSRF token.
  - **Headers:** CSP `default-src 'self'; style-src 'self' 'unsafe-inline'`, plus
    `X-Frame-Options: DENY`.
- **Secrets** are never printed in full anywhere (serial, web, logs, API): Wi-Fi password, admin
  password, device key, Yeelock sign keys. The UI shows "set" and the last 2 characters only.
- **Settings persist in NVS** through `Preferences`, the ESP32's replacement for EEPROM:
  namespace `zgw`, plus one namespace per module (`m_yeelock`). The CLI's `factory-reset`
  (asked twice: `factory-reset` then `factory-reset YES` within 30 s) erases them all, plus the
  certificate, and reboots.

## 3. Serial CLI (115200 baud, line-based, `help` lists all)

| Command | Does |
|---|---|
| `help [cmd]` | every command, one line each |
| `status` | firmware, uptime, Wi-Fi (SSID, IP, RSSI), time synced, paired (ZIGMon name), modules |
| `wifi scan` | the networks around |
| `wifi set <ssid> [password]` | saves and connects. Quotes are allowed for spaces. |
| `wifi forget` | |
| `wifi static <ip> <mask> <gw> [dns]` / `wifi dhcp` | |
| `hostname <name>` | mDNS `<name>.local`; default `zigmon-gw-xxxxxx` |
| `password` | asks for the new admin password twice; never echoed (it echoes `*`) |
| `webinit` | re-opens the first-run password page for 10 minutes |
| `fingerprint` | the certificate SHA-256 |
| `pair` / `unpair` | shows a pairing code / forgets ZIGMon |
| `time [unix]` | shows or sets the clock |
| `modules` | each module, its version and its entities |
| `<module> ...` | the module's own commands, e.g. `yeelock list`, `yeelock add <name> <SN> <signkeyhex>`, `yeelock del <id>`, `yeelock scan`, `yeelock do <id> open\|unlock\|lock\|battery` |
| `log [error\|warn\|info\|debug]` | |
| `reboot` | |
| `factory-reset` | see above |

## 4. The web UI (HTTPS, a phone-friendly single page served from flash)

It uses a dark theme in ZIGMon's dashboard palette (bg `#0D1117`, panel `#161B22`, line
`#262C37`, text `#E6E9EF`, dim `#8B94A3`, ok `#3FB950`, warn `#D29922`, crit `#F85149`,
info `#58A6FF`), and no external resources.

Pages:
- **Overview:** Wi-Fi, time, ZIGMon pairing, the modules' cards.
- **Wi-Fi:** scan, choose, password, static IP.
- **ZIGMon:** pair (shows the code big, with a countdown), the fingerprint, unpair.
- **Modules:** each module's own page. Every module describes its settings as a small schema,
  so the UI draws forms generically.
- **System:** firmware, change password, hostname, reboot, factory reset (typed confirmation),
  and the log tail.

The Yeelock page:
- the locks, each with its name, S/N, key set/unset (last 2), battery, last action and result,
  plus buttons for Open / Unlock / Lock / Battery;
- "Add lock", with a BLE scan listing nearby `EL_*` devices to pick from;
- edit and delete.

## 5. The ZIGMon API on the ESP (all signed, JSON)

| Method, path | Answer |
|---|---|
| `GET /zigmon/v1/hello` | `{"v":1,"id","name","fw","model":"esp32\|esp32s3\|esp32c3","mac_tail":"a1b2c3","time_set":bool,"uptime":s,"rssi":dBm}` |
| `GET /zigmon/v1/describe` | `{"v":1,"modules":[{"id":"yeelock","name":"Yeelock locks","version":"1.0.0","entities":[ENTITY...]}]}` |
| `GET /zigmon/v1/state` | `{"v":1,"seq":n,"entities":{"<entity id>": STATE}}` |
| `GET /zigmon/v1/events?after=<seq>&wait=<s ≤ 25>` | long poll: `{"v":1,"boot":"<8 hex per boot>","seq":n,"events":[{"seq","entity","state":STATE,"what":"…"}]}`. A changed `boot` means re-describe. |
| `POST /zigmon/v1/command` | `{"entity","action","args":{}}` → `202 {"ok":true,"job":"<id>"}`, then the result as an event; or `4xx {"ok":false,"error":"…"}` (busy 409, unknown 404, bad 400) |
| `POST /zigmon/v1/unpair` | `{"ok":true}` |

ENTITY:

```json
{"id": "yeelock.front", "module": "yeelock", "type": "lock", "name": "Front drawer",
 "actions": ["open", "unlock", "lock", "refresh"],
 "attrs": [{"key": "battery", "label": "Battery", "type": "number", "unit": "%", "min": 0, "max": 100}],
 "confirm": ["open", "unlock"]}
```

- `type` is one of: `lock`, `switch`, `sensor`, `binary_sensor`, `button`, `cover`, `number`,
  `select`, `text`. Unknown types are shown read-only.
- `confirm` lists actions that ZIGMon should treat as sensitive: hold-to-confirm on the deck,
  a confirm dialog on the dashboard.

STATE:

```json
{"available": true, "value": "locked"|"unlocked"|"unknown", "busy": false, "attrs": {"battery": 87},
 "last": {"action": "open", "ok": true, "at": 1764340000, "msg": "…"}}
```

For a lock, `value` is derived from the last successful command; the lock itself does not report it.

## 6. The Yeelock module (BLE, NimBLE-Arduino 1.4.x)

The device is found by its advertised name `EL_<SN>`. Its address is cached and rescanned on
failure.

| Purpose | UUID |
|---|---|
| Commands (write) | `58af3dca-6fc0-4fa3-9464-74662f043a3b` |
| Notifications | `58af3dca-6fc0-4fa3-9464-74662f043a3a` |
| Battery | service `0x180F`, characteristic `0x2A19` |

The packets are 20 bytes. `ts` is Unix UTC, 4 bytes big-endian. HMAC-SHA1 is keyed with the
sign key's bytes.

- **Time:** `08 40 ts(4) HMAC(bytes 0-5)[0:14]`.
- **Action:** `01 50 ts(4) mode(1) HMAC(bytes 0-6)[0:13]`. The mode is 00 open (unlock, then
  re-lock), 01 unlock or 02 lock.

The flow:
1. Connect and subscribe.
2. Send the time packet.
3. Send the action.
4. Collect notifications for up to 4 s.
5. If one starts with `0x09`, resend the time, then the action, once.
6. A notification not starting with `0x09` counts as the answer.

Rules:
- BLE work runs on its own FreeRTOS task with a queue, so HTTPS and the CLI stay responsive.
- One BLE job at a time across all locks; the others wait in the queue (at most 8, else 409 busy).
- The battery is read on every connection, and every 12 h when idle.
- Sign keys are hex of 8-32 bytes.

## 7. Test vectors (both sides' tests use them)

- **Request signature.** Device key `000102…1f` (bytes 0..31); method `POST`; path
  `/zigmon/v1/command`; ts `1764340000`; nonce `00112233445566778899aabbccddeeff`; body
  `{"action":"unlock","entity":"yeelock.front"}`:
  - body SHA-256 = `718db82c79edadd8a8b3967f1c4d93a9075fc9f46fb21626c56bacd21c1b6ca4`
  - sig = `9477fb4d74063d5884e02f074529b34194f46ebaa6559387c286c87c182ca83b`
- **Pairing proof.** Code `482913`; fingerprint `ab` × 32; nonce `0f` × 16:
  - proof = `268cac3700bba1a1cc76025483c59235fd45de76a55bad403a3d66a597bdd59a`
- **Yeelock packets.** Sign key `00112233445566778899aabbccddeeff` (a fake key); ts `0x5c84ff2f`:
  - time packet = `08405c84ff2f55748c652e3c83fc10a7cddc7c9f`
  - unlock (mode 01) = `01505c84ff2f01674720aeda9918f538e1471bca`
- **Response signature** (additional vector, same device key `000102…1f`): nonce
  `00112233445566778899aabbccddeeff`, status `202`, body `{"ok":true,"job":"j1"}`:
  - X-Gw-Sig = `6824610d10be8ab28a3c1b7e651f4deeba285b2471073559e2db578e0f141325`
- **Yeelock packets, the other modes** (same key and ts): open (mode 00) =
  `01505c84ff2f0079fe2c69af14b432f22845a8e0`, lock (mode 02) = `01505c84ff2f026a65780114a9a0d3e21204a637`.

## 8. Details pinned down

These were left open above; both sides now do exactly this.

1. **Pairing errors.** A wrong, used, expired or missing code answers **401**
   `{"ok":false,"error":"…"}`. While pairing is locked after five wrong proofs, the answer is
   **429** `{"ok":false,"error":"pairing locked for N s","retry_in":N}`. A malformed body
   (bad JSON, wrong field lengths, `v` other than 1) answers **400**. Only a well-formed proof
   spends the code and counts towards the lockout.
2. **The `/pair` answer is not signed** (ZIGMon has no reason yet to trust the key round trip).
   ZIGMon then sends a signed `GET /zigmon/v1/hello` straight away, and a correctly signed
   answer to it is what confirms the pairing.
3. **Error answers are signed too.** Every answer to a request with a well-formed
   `X-Zigmon-Nonce` carries `X-Gw-Sig` whenever the gateway holds a device key, 4xx included
   (401 for a bad signature, 404, 405, 409, 413, …). Unsigned are only: `/pair`, and answers
   while not paired. ZIGMon trusts only the status code of an unsigned non-2xx answer and
   refuses an unsigned 2xx. `/unpair`'s answer is signed with the key it is dropping.
4. **Job ids in events.** The events a command causes carry `"job":"<id>"` (the id its 202
   returned) next to `entity`; `what` is `"busy"` when the job starts and `"result"` when it
   ends, and the result's `state.last.action` is the command's action. ZIGMon may also match by
   entity and action.
5. **`set` and number/select metadata.** A `set` action takes `args: {"value": v}`. An ENTITY may
   carry optional `options` (for `select`: strings, or `{"value","label"}`), and `unit`, `min`,
   `max` and `step` (for `number`).

Additive fields the firmware sends (older ZIGMon ignores them):

- `hello`: `boot` (the same 8 hex as the events' `boot`) and `modules` (the module ids).
- `events`: `"gap": true` when events after `after` were already dropped from the ring (or
  `after` is from another boot); re-read `/state` then. Each event may carry `at` (Unix s).
- `events.what` is also `"state"` (a change not caused by a job), `"added"` and `"removed"` (an
  entity appeared or went away: describe again).
- STATE: `problem` (e.g. `"wrong_key"`: the lock rejected the sign key) and `last.problem`
  (`not_found`, `connect`, `wrong_key`, `protocol`); Yeelock entities also carry the attr `rssi`.
- Yeelock notifications are decoded (from aso824/yeehack): `0x02` UNLOCK_START, `0x03` UNLOCK_CMP,
  `0x04` LOCK_START, `0x05` LOCK_CMP, `0x25 0x40` INVALID_OPCODE, `0xFF` TX_SIGN_INVALID (a wrong
  sign key: the job fails at once, without a retry). `value` follows UNLOCK_CMP / LOCK_CMP; an
  open (mode 00) ends with LOCK_CMP, so it ends `locked`.
- mDNS: `_https._tcp` and `_zigmon-gw._tcp` on port 443, TXT `id`, `v`, `fw`.
