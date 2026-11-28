// ZIGMon ESP32 Gateway - jobs.
#include "core_jobs.h"

#include "core_crypto.h"
#include "core_events.h"
#include "core_log.h"
#include "core_sys.h"
#include "core_util.h"

namespace gw {
namespace jobs {

struct Job {
  char id[12];
  char entity[48];
  char action[16];
  uint8_t status;  // 0 free, 1 queued, 2 running, 3 done
  bool ok;
  char msg[96];
  uint32_t at;
  uint32_t order;
};

static Job g_jobs[KEEP];
static uint32_t g_order = 0;

static Job* byId(const char* id) {
  if (!id || !*id) return nullptr;
  for (auto& j : g_jobs)
    if (j.status && strcmp(j.id, id) == 0) return &j;
  return nullptr;
}

void create(const char* entity, const char* action, char id[12]) {
  Guard g;
  Job* slot = &g_jobs[0];
  for (auto& j : g_jobs) {
    if (!j.status) { slot = &j; break; }
    if (j.order < slot->order) slot = &j;
  }
  memset(slot, 0, sizeof *slot);
  id[0] = 'j';
  crypto::randomHex(id + 1, 4);
  copyStr(slot->id, sizeof slot->id, id);
  copyStr(slot->entity, sizeof slot->entity, entity);
  copyStr(slot->action, sizeof slot->action, action);
  slot->status = 1;
  slot->order = ++g_order;
  slot->at = nowUnix();
}

void started(const char* id) {
  Guard g;
  Job* j = byId(id);
  if (j) j->status = 2;
}

void finish(const char* id, bool ok, const char* msg) {
  Guard g;
  Job* j = byId(id);
  if (!j) return;
  j->status = 3;
  j->ok = ok;
  copyStr(j->msg, sizeof j->msg, msg);
  j->at = nowUnix();
  LOGI("job", "%s %s %s: %s%s%s", j->id, j->entity, j->action, ok ? "ok" : "FAILED",
       msg && *msg ? " - " : "", msg ? msg : "");
  events::emitEntity(j->entity, "result", j->id);
}

void recent(JsonArray out, size_t max) {
  Guard g;
  // Newest first by creation order.
  bool used[KEEP] = {false};
  for (size_t n = 0; n < max; n++) {
    int best = -1;
    for (size_t i = 0; i < KEEP; i++) {
      if (!g_jobs[i].status || used[i]) continue;
      if (best < 0 || g_jobs[i].order > g_jobs[best].order) best = (int)i;
    }
    if (best < 0) break;
    used[best] = true;
    const Job& j = g_jobs[best];
    JsonObject o = out.add<JsonObject>();
    o["id"] = j.id;
    o["entity"] = j.entity;
    o["action"] = j.action;
    o["status"] = j.status == 1 ? "queued" : j.status == 2 ? "running" : "done";
    if (j.status == 3) {
      o["ok"] = j.ok;
      o["msg"] = j.msg;
    }
    o["at"] = j.at;
  }
}

}  // namespace jobs
}  // namespace gw
