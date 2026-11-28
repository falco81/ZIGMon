// ZIGMon ESP32 Gateway - network: Wi-Fi station, mDNS, NTP.
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

namespace gw {
namespace net {

void begin();          // Wi-Fi up (station), connects if configured
void loop();           // reconnects, starts mDNS/NTP on a new IP, logs changes
void apply();          // re-applies config::net() (after `wifi set`, the web UI, ...)
void restartMdns();

bool configured();
bool connected();
String ip();
int rssi();
String ssid();
const char* hostname();

// Wi-Fi scan. scanStart() is asynchronous; scanGet() returns false while still running.
bool scanStart();
bool scanRunning();
// Fills an array of {"ssid","rssi","secure","ch"} (strongest first, duplicates merged).
bool scanGet(JsonArray out);
// Blocking scan for the CLI (up to ~5 s).
int scanBlocking(JsonArray out);

}  // namespace net
}  // namespace gw
