// ZIGMon ESP32 Gateway - log ring buffer.
#include "core_log.h"

#include <stdarg.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "core_mem.h"
#include "gw_config.h"

namespace gw {
namespace log {

static SemaphoreHandle_t g_mx = nullptr;
static char* g_ring = nullptr;    // lines x GW_LOG_LINE_LEN
static size_t g_lines = 0;        // capacity
static size_t g_next = 0;         // total lines written
static Level g_level = L_INFO;
static PrintedHook g_hook = nullptr;

void begin() {
  if (!g_mx) g_mx = xSemaphoreCreateMutex();
  if (!g_ring) {
    // 4x the lines when there is PSRAM: it costs nothing there.
    g_lines = havePsram() ? GW_LOG_LINES * 4 : GW_LOG_LINES;
    g_ring = (char*)bigAlloc(g_lines * GW_LOG_LINE_LEN);
    if (!g_ring) g_lines = 0;
  }
}

void setLevel(Level l) { g_level = l > L_DEBUG ? L_DEBUG : l; }
Level level() { return g_level; }
void setPrintedHook(PrintedHook h) { g_hook = h; }

const char* levelName(Level l) {
  switch (l) {
    case L_ERROR: return "error";
    case L_WARN: return "warn";
    case L_INFO: return "info";
    case L_DEBUG: return "debug";
  }
  return "info";
}

bool parseLevel(const char* s, Level* out) {
  if (!s) return false;
  for (uint8_t i = 0; i <= L_DEBUG; i++) {
    if (strcmp(s, levelName((Level)i)) == 0) { *out = (Level)i; return true; }
  }
  return false;
}

void write(Level l, const char* tag, const char* fmt, ...) {
  if (l > g_level) return;
  static const char kL[] = "EWID";
  char line[GW_LOG_LINE_LEN];
  unsigned long ms = millis();
  int n = snprintf(line, sizeof line, "%6lu.%01lu %c %s: ", ms / 1000, (ms / 100) % 10, kL[l], tag);
  if (n < 0) return;
  if ((size_t)n < sizeof line) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line + n, sizeof line - n, fmt, ap);
    va_end(ap);
  }
  // No control characters in the ring (a lock's notification bytes etc. come hex-encoded).
  for (char* p = line; *p; p++)
    if ((uint8_t)*p < 0x20) *p = ' ';

  if (g_mx) xSemaphoreTake(g_mx, portMAX_DELAY);
  if (g_ring && g_lines) {
    memcpy(g_ring + (g_next % g_lines) * GW_LOG_LINE_LEN, line, GW_LOG_LINE_LEN);
    g_next++;
  }
  Serial.print("\r");
  Serial.println(line);
  if (g_mx) xSemaphoreGive(g_mx);
  if (g_hook) g_hook();
}

void tail(LineFn fn, void* ctx, size_t maxLines) {
  if (!g_ring || !g_lines) return;
  if (g_mx) xSemaphoreTake(g_mx, portMAX_DELAY);
  size_t have = g_next < g_lines ? g_next : g_lines;
  size_t n = have < maxLines ? have : maxLines;
  for (size_t i = g_next - n; i < g_next; i++) fn(g_ring + (i % g_lines) * GW_LOG_LINE_LEN, ctx);
  if (g_mx) xSemaphoreGive(g_mx);
}

}  // namespace log
}  // namespace gw
