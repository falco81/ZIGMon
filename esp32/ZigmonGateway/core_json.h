// ZIGMon ESP32 Gateway - ArduinoJson 7 helpers: a PSRAM allocator and capped parsing.
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "core_mem.h"

namespace gw {

// JSON documents go to PSRAM when the board has it (core_mem.h), else the internal heap.
class BigAllocator : public ArduinoJson::Allocator {
 public:
  void* allocate(size_t n) override { return bigAlloc(n); }
  void deallocate(void* p) override { bigFree(p); }
  void* reallocate(void* p, size_t n) override { return bigRealloc(p, n); }
  static BigAllocator* instance() {
    static BigAllocator a;
    return &a;
  }
};

// Usage:  JsonDocument doc(jsonAlloc());
inline ArduinoJson::Allocator* jsonAlloc() { return BigAllocator::instance(); }

// Parses at most GW_MAX_BODY bytes with a nesting limit; false on any error, too-big input,
// or a non-object top level.
bool parseJsonObject(JsonDocument& doc, const char* data, size_t len, String& err);

// String field helper: returns "" when missing / not a string, and caps the length.
// ok=false if it was present but longer than maxLen bytes.
const char* jstr(JsonObjectConst o, const char* key, size_t maxLen, bool* ok = nullptr);

}  // namespace gw
