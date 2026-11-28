// ZIGMon ESP32 Gateway - persistent settings in NVS (Preferences, the ESP32's EEPROM).
//
// Namespace "zgw" holds the core's settings; every module has its own ("m_<id>"). All of it
// survives reboots and firmware updates, and `factory-reset` erases the whole NVS partition.
// Values are cached in RAM after begin(); callers hold the gateway lock (core_sys.h).
#pragma once

#include <Arduino.h>

namespace gw {

struct NetConfig {
  char ssid[33];
  char pass[65];      // secret: never printed, never sent to the web UI
  bool dhcp;
  uint8_t ip[4], mask[4], gw[4], dns[4];
  char hostname[33];  // mDNS name, default zigmon-gw-<mac tail>
  char name[41];      // friendly name shown to ZIGMon; default = hostname
};

namespace config {

void begin();

NetConfig& net();
bool saveNet();

// Admin password (PBKDF2-HMAC-SHA256).
bool hasPassword();
bool getPassword(uint8_t salt[16], uint8_t dk[32], uint32_t* rounds);
bool setPassword(const uint8_t salt[16], const uint8_t dk[32], uint32_t rounds);

// ZIGMon pairing.
bool paired();
const uint8_t* deviceKey();     // 32 bytes, valid while paired()
const char* zigmonName();
bool setPairing(const uint8_t key[32], const char* zigmonName);
void clearPairing();

// The TLS certificate and key (PEM, NUL-terminated).
bool loadCert(String& certPem, String& keyPem);
bool saveCert(const String& certPem, const String& keyPem);

uint8_t logLevel();
void setLogLevel(uint8_t l);

// Erases every NVS namespace (core, modules, certificate, Wi-Fi driver data) and reboots.
void factoryReset();

}  // namespace config
}  // namespace gw
