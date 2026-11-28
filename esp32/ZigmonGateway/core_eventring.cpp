// ZIGMon ESP32 Gateway - the event ring (portable).
#include "core_eventring.h"

#include <string.h>

#include "core_mem.h"
#include "core_util.h"

namespace gw {

EventRing::~EventRing() {
  if (ev_) bigFree(ev_);
}

bool EventRing::begin(size_t capacity) {
  if (ev_) return true;
  ev_ = (Event*)bigAlloc(sizeof(Event) * capacity);
  if (!ev_) return false;
  cap_ = capacity;
  seq_ = 0;
  return true;
}

uint32_t EventRing::push(const char* entity, const char* what, const char* job,
                         const char* stateJson, uint32_t at) {
  if (!ev_) return seq_;
  uint32_t s = ++seq_;
  if (s == 0) s = seq_ = 1;  // 4 billion events later: wrap without using 0
  Event& e = ev_[(s - 1) % cap_];
  e.seq = s;
  e.at = at;
  copyStr(e.entity, sizeof e.entity, entity);
  copyStr(e.what, sizeof e.what, what);
  copyStr(e.job, sizeof e.job, job);
  if (!copyStr(e.state, sizeof e.state, stateJson)) e.state[0] = 0;  // never half a JSON
  return s;
}

uint32_t EventRing::oldestSeq() const {
  if (!ev_ || seq_ == 0) return 0;
  return seq_ > cap_ ? seq_ - (uint32_t)cap_ + 1 : 1;
}

size_t EventRing::collect(uint32_t after, size_t limit, Visitor fn, void* ctx, bool* gap) const {
  if (gap) *gap = false;
  if (!ev_ || seq_ == 0) {
    if (gap && after > seq_) *gap = true;
    return 0;
  }
  if (after > seq_) {
    if (gap) *gap = true;
    after = 0;  // a seq we never issued: hand over everything we still have
  }
  uint32_t first = oldestSeq();
  if (after + 1 < first) {
    if (gap) *gap = true;
    after = first - 1;
  }
  size_t n = 0;
  for (uint32_t s = after + 1; s <= seq_ && n < limit; s++) {
    const Event& e = ev_[(s - 1) % cap_];
    if (e.seq != s) continue;
    fn(e, ctx);
    n++;
  }
  return n;
}

}  // namespace gw
