// ZIGMon ESP32 Gateway - ArduinoJson helpers.
#include "core_json.h"

#include "gw_config.h"

namespace gw {

bool parseJsonObject(JsonDocument& doc, const char* data, size_t len, String& err) {
  if (len > GW_MAX_BODY) { err = "body too large"; return false; }
  if (len == 0) { err = "empty body"; return false; }
  DeserializationError e =
      deserializeJson(doc, data, len, DeserializationOption::NestingLimit(6));
  if (e) { err = String("bad JSON: ") + e.c_str(); return false; }
  if (!doc.is<JsonObject>()) { err = "a JSON object is expected"; return false; }
  return true;
}

const char* jstr(JsonObjectConst o, const char* key, size_t maxLen, bool* ok) {
  const char* s = o[key].as<const char*>();
  if (ok) *ok = true;
  if (!s) return "";
  if (strlen(s) > maxLen) {
    if (ok) *ok = false;
    return "";
  }
  return s;
}

}  // namespace gw
