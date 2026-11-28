// ZIGMon ESP32 Gateway - the event ring behind GET /zigmon/v1/events (portable, unit-tested).
//
// Each event keeps the entity's STATE as serialized JSON at the moment it happened, so a
// long poll returns exactly what changed even if the entity changed again since.
// Not thread-safe by itself: core_events.cpp wraps it in the gateway lock.
#pragma once

#include <stdint.h>
#include <stddef.h>

#include "gw_config.h"

namespace gw {

struct Event {
  uint32_t seq;            // 0 = empty slot
  uint32_t at;             // Unix s (0 if the clock was not set)
  char entity[48];         // "yeelock.front"
  char what[16];           // "state", "busy", "result", "added", "removed"
  char job[12];            // job id for "result"/"busy", else ""
  char state[GW_EVENT_STATE_MAX];  // STATE JSON, or "" (e.g. "removed")
};

class EventRing {
 public:
  EventRing() : ev_(nullptr), cap_(0), seq_(0) {}
  ~EventRing();
  bool begin(size_t capacity);   // allocates (PSRAM if present)
  // Appends and returns the new seq (1, 2, ...). The state is cut at GW_EVENT_STATE_MAX-1
  // bytes; callers keep STATE small (it is, by design: a few attrs).
  uint32_t push(const char* entity, const char* what, const char* job, const char* stateJson,
                uint32_t at);
  uint32_t seq() const { return seq_; }
  uint32_t oldestSeq() const;    // 0 if empty

  typedef void (*Visitor)(const Event& e, void* ctx);
  // Calls fn for every event with seq > after, oldest first, at most `limit`.
  // *gap = true when events after `after` were already overwritten (or `after` is from the
  // future, e.g. another boot): the caller should re-read the full state.
  size_t collect(uint32_t after, size_t limit, Visitor fn, void* ctx, bool* gap) const;
  bool hasAfter(uint32_t after) const { return seq_ > after; }

 private:
  Event* ev_;
  size_t cap_;
  uint32_t seq_;
};

}  // namespace gw
