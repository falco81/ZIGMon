// ZIGMon ESP32 Gateway - log: a ring buffer (PSRAM if present) mirrored to the serial port.
//
// Rule for every caller: never pass a secret (Wi-Fi password, admin password, device key,
// sign keys, session tokens, pairing codes) or a request body to the log.
#pragma once

#include <Arduino.h>

namespace gw {
namespace log {

enum Level : uint8_t { L_ERROR = 0, L_WARN = 1, L_INFO = 2, L_DEBUG = 3 };

void begin();
void setLevel(Level l);
Level level();
const char* levelName(Level l);
bool parseLevel(const char* s, Level* out);

void write(Level l, const char* tag, const char* fmt, ...) __attribute__((format(printf, 3, 4)));

// Calls fn for each kept line, oldest first (at most maxLines, the newest ones).
typedef void (*LineFn)(const char* line, void* ctx);
void tail(LineFn fn, void* ctx, size_t maxLines);

// Hook for the CLI: called after a log line hit the serial port (to redraw the prompt).
typedef void (*PrintedHook)();
void setPrintedHook(PrintedHook h);

}  // namespace log
}  // namespace gw

#define LOGE(tag, ...) ::gw::log::write(::gw::log::L_ERROR, tag, __VA_ARGS__)
#define LOGW(tag, ...) ::gw::log::write(::gw::log::L_WARN, tag, __VA_ARGS__)
#define LOGI(tag, ...) ::gw::log::write(::gw::log::L_INFO, tag, __VA_ARGS__)
#define LOGD(tag, ...) ::gw::log::write(::gw::log::L_DEBUG, tag, __VA_ARGS__)
