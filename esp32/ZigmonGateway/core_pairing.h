// ZIGMon ESP32 Gateway - pairing with ZIGMon (contract section 2, "Pairing").
#pragma once

#include <Arduino.h>

#include "core_https.h"

namespace gw {
namespace pairing {

// Starts a new 6-digit code (valid 10 min, single use). False while pairing is locked.
bool start(String& err);
void cancel();
bool active();
const char* code();          // "" when none (shown on the web UI and the CLI only)
uint32_t expiresIn();
uint32_t lockedFor();

// POST /zigmon/v1/pair (unsigned: the proof is the authentication).
void handlePair(const String& body, https::Response& r);

// Forgets ZIGMon (signed /unpair, the CLI `unpair`, the web UI).
void unpair(const char* why);

}  // namespace pairing
}  // namespace gw
