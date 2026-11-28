// ZIGMon ESP32 Gateway - system basics: the gateway lock, clocks, identity, deferred actions.
#pragma once

#include <Arduino.h>

namespace gw {

// ---- The gateway lock --------------------------------------------------------------------
// One recursive mutex guards all shared state (config, modules' state, sessions, events).
// It is held by the HTTPS handlers while they build a response (never while sending), by
// the CLI while a command runs and by the BLE task only while it updates state (never during
// radio work). Keep holds short.
void lockInit();
class Guard {
 public:
  Guard();
  ~Guard();

 private:
  Guard(const Guard&);
  Guard& operator=(const Guard&);
};

// ---- Clocks ----------------------------------------------------------------------------------
uint32_t monoS();            // seconds since boot + 1 (never 0); for timeouts and sessions
uint32_t nowUnix();          // wall clock, Unix s (may be "not set")
bool clockSet();             // nowUnix() >= GW_CLOCK_VALID_FROM
void setClock(uint32_t unix, const char* source);  // settimeofday + log

// ---- Identity ----------------------------------------------------------------------------
const char* gatewayId();     // 12 lowercase hex of the Wi-Fi STA MAC
const char* macTail();       // last 6 of it
const char* chipModel();     // "esp32s3" | "esp32c3" | "esp32" | CONFIG_IDF_TARGET
const char* bootId();        // 8 hex, random per boot

// ---- Deferred actions (run from loop(), after the HTTP answer is out) ------------------------
enum class Deferred : uint8_t { None, Reboot, FactoryReset, WifiApply, MdnsRestart };
void defer(Deferred what, uint32_t delayMs);
void runDeferred();          // called from loop()

}  // namespace gw
