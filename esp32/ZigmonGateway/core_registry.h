// ZIGMon ESP32 Gateway - the module registry.
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "core_module.h"

namespace gw {
namespace registry {

static const size_t MAX_MODULES = 12;

// Registers a module (call in setup() before registry::beginAll()). False if the id is
// invalid, taken, or the registry is full.
bool add(Module* m);

void beginAll();
void loopAll();     // without the gateway lock
void factoryResetAll();

size_t count();
Module* at(size_t i);
Module* find(const char* id);
// The module that owns "<module>.<item>" (by prefix), or nullptr.
Module* ownerOf(const char* entityId);

// {"v":1,"modules":[{"id","name","version","entities":[...]}]}
void describe(JsonObject out);
// "<entity id>": STATE for every entity of every module.
void stateAll(JsonObject entities);
bool stateOf(const char* entityId, JsonObject out);

// All modules' CLI secret rules, merged with the core's (for the line editor).
const cli::SecretRule* secretRules(size_t* n);

}  // namespace registry
}  // namespace gw
