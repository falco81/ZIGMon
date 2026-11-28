// ZIGMon ESP32 Gateway - events: seq ring + long-poll waiters.
#include "core_events.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "core_config.h"
#include "core_eventring.h"
#include "core_https.h"
#include "core_json.h"
#include "core_log.h"
#include "core_mem.h"
#include "core_registry.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace events {

static EventRing g_ring;
static TaskHandle_t g_task = nullptr;

struct Waiter {
  httpd_req_t* req;   // async copy, or nullptr
  uint32_t after;
  uint32_t deadline;  // monoS()
  char nonce[33];
};
static Waiter g_waiters[GW_LONGPOLL_WAITERS];

#if GW_HTTPD_ASYNC
static void waiterTask(void*);
#endif

void begin() {
  // 4x the history with PSRAM (each event is ~470 bytes).
  size_t cap = havePsram() ? GW_EVENTS_RING * 4 : GW_EVENTS_RING;
  if (!g_ring.begin(cap)) LOGE("events", "no memory for the event ring");
#if GW_HTTPD_ASYNC
  xTaskCreate(waiterTask, "gw_poll", 6144, nullptr, 4, &g_task);
#endif
}

uint32_t seq() {
  Guard g;
  return g_ring.seq();
}

bool hasAfter(uint32_t after) {
  Guard g;
  return g_ring.hasAfter(after);
}

void emitEntity(const char* entityId, const char* what, const char* job) {
  {
    Guard g;
    String state;
    if (strcmp(what, "removed") != 0) {
      JsonDocument doc(jsonAlloc());
      JsonObject st = doc.to<JsonObject>();
      if (registry::stateOf(entityId, st)) serializeJson(doc, state);
    }
    uint32_t s = g_ring.push(entityId, what, job ? job : "", state.c_str(), clockSet() ? nowUnix() : 0);
    LOGD("events", "#%lu %s %s", (unsigned long)s, entityId, what);
  }
  if (g_task) xTaskNotifyGive(g_task);
}

struct FillCtx {
  JsonArray arr;
};

static void addEvent(const Event& e, void* ctx) {
  FillCtx* c = (FillCtx*)ctx;
  JsonObject o = c->arr.add<JsonObject>();
  o["seq"] = e.seq;
  o["entity"] = e.entity;
  if (e.state[0]) {
    // Stored serialized; parse it back into the answer (small, bounded).
    JsonDocument st(jsonAlloc());
    if (!deserializeJson(st, e.state)) o["state"] = st.as<JsonObjectConst>();
    else o["state"] = nullptr;
  } else {
    o["state"] = nullptr;
  }
  o["what"] = e.what;
  if (e.job[0]) o["job"] = e.job;
  if (e.at) o["at"] = e.at;
}

void fill(uint32_t after, JsonObject out) {
  Guard g;
  out["v"] = 1;
  out["boot"] = bootId();
  out["seq"] = g_ring.seq();
  FillCtx c{out["events"].to<JsonArray>()};
  bool gap = false;
  g_ring.collect(after, 32, addEvent, &c, &gap);
  if (gap) out["gap"] = true;   // additive: missed events, re-read /state
}

#if GW_HTTPD_ASYNC

bool park(httpd_req_t* req, uint32_t after, uint32_t waitS, const char* nonce) {
  int slot = -1;
  {
    Guard g;
    for (int i = 0; i < GW_LONGPOLL_WAITERS; i++)
      if (!g_waiters[i].req) { slot = i; break; }
    if (slot < 0) return false;
    g_waiters[slot].req = (httpd_req_t*)1;  // reserve while we copy (outside the lock)
  }
  httpd_req_t* copy = nullptr;
  if (httpd_req_async_handler_begin(req, &copy) != ESP_OK || !copy) {
    Guard g;
    g_waiters[slot].req = nullptr;
    return false;
  }
  {
    Guard g;
    Waiter& w = g_waiters[slot];
    w.after = after;
    w.deadline = monoS() + waitS;
    copyStr(w.nonce, sizeof w.nonce, nonce);
    w.req = copy;
  }
  xTaskNotifyGive(g_task);
  return true;
}

static void answer(Waiter& w) {
  https::Response r;
  {
    Guard g;
    JsonDocument doc(jsonAlloc());
    fill(w.after, doc.to<JsonObject>());
    serializeJson(doc, r.body);
    r.sign = config::paired();
    copyStr(r.nonce, sizeof r.nonce, w.nonce);
  }
  https::send(w.req, r);            // outside the lock: TLS writes can be slow
  httpd_req_async_handler_complete(w.req);
}

static void waiterTask(void*) {
  for (;;) {
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(500));
    for (int i = 0; i < GW_LONGPOLL_WAITERS; i++) {
      Waiter w;
      bool due = false;
      {
        Guard g;
        Waiter& x = g_waiters[i];
        if (!x.req || x.req == (httpd_req_t*)1) continue;
        due = g_ring.hasAfter(x.after) || (int32_t)(monoS() - x.deadline) >= 0;
        if (due) {
          w = x;
          x.req = nullptr;
        }
      }
      if (due) answer(w);
    }
  }
}

#else  // no async handlers: /events always answers at once (ZIGMon simply polls)

bool park(httpd_req_t*, uint32_t, uint32_t, const char*) {
  (void)g_waiters;
  return false;
}

#endif

}  // namespace events
}  // namespace gw
