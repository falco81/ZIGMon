// ZIGMon ESP32 Gateway - jobs: the ids that tie a 202 answer to its result event.
//
// A command that takes time (a BLE round trip) is accepted with 202 {"ok":true,"job":"<id>"};
// the module runs it (on the BLE task, say) and, when done, calls jobs::finish(), which
// records the outcome and emits the entity's "result" event carrying the same job id.
// The last results are kept for the web UI and the CLI.
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

namespace gw {
namespace jobs {

static const size_t KEEP = 16;

// Creates a job for entity/action; writes its id ("j" + 8 hex) into id[12].
void create(const char* entity, const char* action, char id[12]);
void started(const char* id);
// Records the outcome and emits events::emitEntity(entity, "result", id).
void finish(const char* id, bool ok, const char* msg);

// [{"id","entity","action","status":"queued|running|done","ok","msg","at"}], newest first.
void recent(JsonArray out, size_t max);

}  // namespace jobs
}  // namespace gw
