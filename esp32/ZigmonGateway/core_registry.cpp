// ZIGMon ESP32 Gateway - the module registry.
#include "core_registry.h"

#include <Preferences.h>

#include "core_log.h"
#include "core_sys.h"
#include "core_util.h"

namespace gw {

void Module::factoryReset() {
  Preferences p;
  String ns = nvsNamespace();
  if (p.begin(ns.c_str(), false)) {
    p.clear();
    p.end();
  }
}

namespace registry {

static Module* g_mods[MAX_MODULES];
static size_t g_n = 0;

// The core's own secret arguments, then each module's.
static const cli::SecretRule kCoreRules[] = {
    {"wifi", "set", 3},   // wifi set <ssid> <password>
};
static cli::SecretRule g_rules[16];
static size_t g_nRules = 0;

static bool validId(const char* id) {
  if (!id || !*id || strlen(id) > 13) return false;
  for (const char* p = id; *p; p++)
    if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9') || *p == '_')) return false;
  return true;
}

bool add(Module* m) {
  if (!m || g_n >= MAX_MODULES || !validId(m->id()) || find(m->id())) {
    LOGE("modules", "cannot register module '%s'", m ? m->id() : "?");
    return false;
  }
  g_mods[g_n++] = m;
  return true;
}

void beginAll() {
  g_nRules = 0;
  for (const auto& r : kCoreRules) g_rules[g_nRules++] = r;
  for (size_t i = 0; i < g_n; i++) {
    Guard g;
    g_mods[i]->begin();
    size_t n = 0;
    const cli::SecretRule* r = g_mods[i]->cliSecrets(&n);
    for (size_t k = 0; r && k < n && g_nRules < sizeof g_rules / sizeof g_rules[0]; k++)
      g_rules[g_nRules++] = r[k];
    LOGI("modules", "%s %s started", g_mods[i]->id(), g_mods[i]->version());
  }
}

void loopAll() {
  for (size_t i = 0; i < g_n; i++) g_mods[i]->loop();
}

void factoryResetAll() {
  for (size_t i = 0; i < g_n; i++) g_mods[i]->factoryReset();
}

size_t count() { return g_n; }
Module* at(size_t i) { return i < g_n ? g_mods[i] : nullptr; }

Module* find(const char* id) {
  if (!id) return nullptr;
  for (size_t i = 0; i < g_n; i++)
    if (strcmp(g_mods[i]->id(), id) == 0) return g_mods[i];
  return nullptr;
}

Module* ownerOf(const char* entityId) {
  if (!entityId) return nullptr;
  const char* dot = strchr(entityId, '.');
  if (!dot || dot == entityId) return nullptr;
  size_t n = (size_t)(dot - entityId);
  for (size_t i = 0; i < g_n; i++) {
    const char* id = g_mods[i]->id();
    if (strlen(id) == n && strncmp(id, entityId, n) == 0) return g_mods[i];
  }
  return nullptr;
}

void describe(JsonObject out) {
  out["v"] = 1;
  JsonArray mods = out["modules"].to<JsonArray>();
  for (size_t i = 0; i < g_n; i++) {
    Module* m = g_mods[i];
    JsonObject o = mods.add<JsonObject>();
    o["id"] = m->id();
    o["name"] = m->name();
    o["version"] = m->version();
    m->describe(o["entities"].to<JsonArray>());
  }
}

void stateAll(JsonObject entities) {
  for (size_t i = 0; i < g_n; i++) g_mods[i]->state(entities);
}

bool stateOf(const char* entityId, JsonObject out) {
  Module* m = ownerOf(entityId);
  return m && m->stateOf(entityId, out);
}

const cli::SecretRule* secretRules(size_t* n) {
  *n = g_nRules;
  return g_rules;
}

}  // namespace registry
}  // namespace gw
