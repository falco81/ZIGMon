// ZIGMon ESP32 Gateway - events: the seq ring plus long-poll waiters (GET /zigmon/v1/events).
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "esp_http_server.h"

namespace gw {
namespace events {

void begin();
uint32_t seq();

// Emits an event for an entity with its current STATE (serialized now, via the registry).
// what: "state" (changed), "busy" (a job started), "result" (a job ended), "added",
// "removed" (no state). Safe from any task.
void emitEntity(const char* entityId, const char* what, const char* job = "");

// {"v":1,"boot","seq","events":[{"seq","entity","state","what","job"?,"at"?}],"gap"?:true}
void fill(uint32_t after, JsonObject out);
bool hasAfter(uint32_t after);

// Hands a signed /events request to the waiter task (async request; ESP-IDF >= 5.1).
// It answers as soon as an event after `after` exists, or after waitS seconds.
// Returns false if it could not be parked (the caller answers right away).
bool park(httpd_req_t* req, uint32_t after, uint32_t waitS, const char* nonce);

}  // namespace events
}  // namespace gw
