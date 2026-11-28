// ZIGMon ESP32 Gateway - the serial CLI (115200 baud; contract section 3).
#pragma once

#include <Arduino.h>

namespace gw {
namespace cli {

void begin();
void loop();       // reads Serial; runs complete lines

// For module commands that need a secret (e.g. `yeelock fetch` asks for the Yeelock account
// password): shows `prompt`, reads one line echoed as '*', then calls fn with it (under the
// gateway lock). The buffer is wiped right after fn returns. Ctrl-C cancels (fn not called).
typedef void (*SecretFn)(const char* secret, void* ctx);
void askSecret(const char* prompt, SecretFn fn, void* ctx);

}  // namespace cli
}  // namespace gw
