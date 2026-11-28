// ZIGMon ESP32 Gateway - the Module interface.
//
// A module is one feature of the gateway (Yeelock locks today; relays, reed contacts, IR,
// sensors tomorrow). It owns entities (contract section 5: ENTITY and STATE), its settings
// (drawn generically by the web UI from settingsSchema()), optional "items" (a collection the
// user adds/edits/deletes, e.g. locks, with optional discovery, e.g. a BLE scan), its CLI
// commands, and its own NVS namespace.
//
// Adding a module = one new file (mod_<id>.cpp) + one registration line in ZigmonGateway.ino.
// See README.md, "Writing a new module".
//
// Threading: every method below is called with the gateway lock held (core_sys.h), from the
// HTTPS task, the CLI (loop task) or the BLE task. Don't block in them: hand slow work to a
// job (core_jobs.h, core_ble.h) and report the result through events::emitEntity().
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "core_cliline.h"

namespace gw {

struct CommandResult {
  int status;        // 202 accepted, 400 bad, 404 unknown, 409 busy / not possible now
  String error;      // for 4xx
  String job;        // for 202
  static CommandResult accepted(const String& job) { return CommandResult{202, String(), job}; }
  static CommandResult fail(int status, const char* error) {
    return CommandResult{status, String(error), String()};
  }
};

class Module {
 public:
  virtual ~Module() {}

  // ---- identity ----------------------------------------------------------------------------
  // [a-z0-9_], at most 13 characters (the NVS namespace "m_<id>" must fit 15). It is also the
  // entity id prefix ("<id>.<item>") and the CLI command word.
  virtual const char* id() const = 0;
  virtual const char* name() const = 0;        // "Yeelock locks"
  virtual const char* version() const = 0;     // "1.0.0"
  // A hint for the web UI's icon: lock, switch, sensor, bolt, box.
  virtual const char* icon() const { return "box"; }
  String nvsNamespace() const { return String("m_") + id(); }

  // ---- lifecycle ---------------------------------------------------------------------------
  virtual void begin() = 0;   // load settings from NVS; called once from setup()
  virtual void loop() {}      // called from loop(), WITHOUT the gateway lock

  // ---- entities (ZIGMon API) ---------------------------------------------------------------
  virtual void describe(JsonArray entities) = 0;              // append ENTITY objects
  virtual void state(JsonObject entities) = 0;                // "<entity id>": STATE, each
  virtual bool stateOf(const char* entityId, JsonObject out) = 0;
  virtual CommandResult command(const char* entityId, const char* action, JsonObjectConst args) = 0;

  // A one-line summary for the web UI's overview card: {"text": "...", "level": "ok|warn|crit"}.
  virtual void overview(JsonObject out) {}

  // ---- settings (web UI) -------------------------------------------------------------------
  // {"settings":[FIELD...], "collection":{...}}; see README.md for the FIELD format.
  virtual void settingsSchema(JsonObject schema) = 0;
  virtual void settingsGet(JsonObject values) = 0;            // secrets masked, never raw
  virtual bool settingsSet(JsonObjectConst values, String& err) = 0;

  // ---- collection (optional) ------------------------------------------------------------------
  virtual void itemsGet(JsonArray items) {}
  // itemId == nullptr: add a new item. Secret fields left empty keep their stored value.
  virtual bool itemSave(const char* itemId, JsonObjectConst item, String& savedId, String& err) {
    err = "this module has no items";
    return false;
  }
  virtual bool itemDelete(const char* itemId, String& err) {
    err = "this module has no items";
    return false;
  }
  virtual bool discoverStart(String& err) {
    err = "this module has no discovery";
    return false;
  }
  // {"running":bool,"results":[{...fields to prefill...,"label":"","detail":"","known":bool}]}
  virtual void discoverGet(JsonObject out) {}

  // ---- module-specific web calls (optional) ---------------------------------------------------
  // GET/POST /api/m/<id>/x/<name> (session + CSRF checked by the core). Fill `out`, return the
  // HTTP status (200, 202, 4xx with err). The schema's collection.import / collection.check
  // name the calls the generic web UI uses (see README.md).
  virtual int webCall(const char* name, bool post, JsonObjectConst in, JsonObject out, String& err) {
    err = "not found";
    return 404;
  }

  // ---- CLI ------------------------------------------------------------------------------------
  virtual void cliHelp(Print& out) {}
  // argv[0] is the module id. Return false if the subcommand is unknown (help is printed).
  virtual bool cliCommand(Print& out, int argc, char** argv) { return false; }
  // Arguments the CLI must echo as '*' (e.g. a sign key). nullptr if none.
  virtual const cli::SecretRule* cliSecrets(size_t* n) { *n = 0; return nullptr; }

  // ---- factory reset --------------------------------------------------------------------------
  // Default: clears the module's namespace. The core erases all of NVS afterwards anyway.
  virtual void factoryReset();
};

}  // namespace gw
