// ZIGMon ESP32 Gateway firmware 1.0.0 (protocol v1): see esp32/README.md and esp32/PROTOCOL.md.
//
// An ESP32 on your Wi-Fi that ZIGMon pairs with, detects and controls. Its features are
// modules; the first is Yeelock (Xiaomi Yeelock BLE locks, several per gateway).
//
//   Primary target: ESP32-S3-N16R8 (16 MB flash, 8 MB octal PSRAM), board "ESP32S3 Dev Module".
//   Also: classic ESP32 and ESP32-C3 (anything with BLE).
//   Arduino core for ESP32 3.x (ESP-IDF 5); libraries: NimBLE-Arduino 1.4.x, ArduinoJson 7.x.
//
// First steps (serial monitor at 115200 baud, line ending "Newline" or "Both NL & CR"):
//   wifi set "My Wi-Fi" mypassword
//   password
//   status            -> open https://<hostname>.local/ and accept the self-signed certificate
//                        after comparing its fingerprint with `fingerprint`

#include <Arduino.h>

#include "core_auth.h"
#include "core_cert.h"
#include "core_cli.h"
#include "core_config.h"
#include "core_events.h"
#include "core_https.h"
#include "core_log.h"
#include "core_mem.h"
#include "core_net.h"
#include "core_registry.h"
#include "core_sys.h"
#include "gw_config.h"

// ---- Modules: one line each. Adding a module = its mod_<id>.cpp + one line here. -----------
#include "mod_yeelock.h"

static void registerModules() {
  gw::registry::add(gw::yeelockModule());
  // gw::registry::add(gw::relayModule());   // e.g. a future mod_relay.cpp
}

// ----------------------------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  // USB CDC (native USB on the S3/C3) needs a moment for the host to open the port.
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) delay(10);

  gw::lockInit();
  gw::log::begin();
  Serial.println();
  Serial.printf("ZIGMon Gateway %s on %s (%s)\n", GW_FW_VERSION, gw::chipModel(),
                gw::havePsram() ? "PSRAM found" : "no PSRAM");

  gw::config::begin();
  gw::log::setLevel((gw::log::Level)gw::config::logLevel());
  gw::events::begin();
  gw::auth::begin();

  registerModules();
  gw::registry::beginAll();   // modules load their NVS settings; Yeelock starts BLE

  gw::net::begin();           // Wi-Fi up (lwIP is needed by the servers)
  if (!gw::cert::ensure()) {
    LOGE("boot", "no TLS certificate: the web UI and the ZIGMon API are off");
  } else if (!gw::https::begin()) {
    LOGE("boot", "the HTTPS server did not start");
  }
  LOGI("boot", "id %s, hostname %s.local, cert %.16s...", gw::gatewayId(), gw::config::net().hostname,
       gw::cert::fingerprint());
  if (!gw::auth::passwordSet())
    LOGW("boot", "no admin password yet: run `password` here (or use the first-run page for 10 min)");
  gw::cli::begin();
}

void loop() {
  gw::cli::loop();
  gw::net::loop();
  gw::registry::loopAll();
  gw::runDeferred();
  delay(5);
}
