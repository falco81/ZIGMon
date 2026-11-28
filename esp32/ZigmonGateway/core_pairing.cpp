// ZIGMon ESP32 Gateway - pairing with ZIGMon.
#include "core_pairing.h"

#include <ArduinoJson.h>

#include "core_authlogic.h"
#include "core_cert.h"
#include "core_config.h"
#include "core_crypto.h"
#include "core_json.h"
#include "core_log.h"
#include "core_sys.h"
#include "core_util.h"

namespace gw {
namespace pairing {

static PairGate g_gate;

bool start(String& err) {
  uint32_t now = monoS();
  if (!g_gate.start(now, crypto::randomBelow(1000000))) {
    err = String("pairing is locked for ") + g_gate.lockedFor(now) + " s after 5 wrong codes";
    return false;
  }
  LOGI("pair", "pairing code issued, valid 10 minutes");  // the code itself is never logged
  return true;
}

void cancel() { g_gate.clear(); }
bool active() { return g_gate.active(monoS()); }
const char* code() { return active() ? g_gate.code() : ""; }
uint32_t expiresIn() { return g_gate.expiresIn(monoS()); }
uint32_t lockedFor() { return g_gate.lockedFor(monoS()); }

void unpair(const char* why) {
  if (!config::paired()) return;
  config::clearPairing();
  LOGW("pair", "ZIGMon forgotten (%s)", why);
}

void handlePair(const String& body, https::Response& r) {
  JsonDocument doc(jsonAlloc());
  String err;
  if (!parseJsonObject(doc, body.c_str(), body.length(), err)) {
    https::error(r, 400, err.c_str());
    return;
  }
  JsonObjectConst o = doc.as<JsonObjectConst>();
  if ((o["v"] | 0) != 1) { https::error(r, 400, "unsupported protocol version"); return; }
  const char* nonce = jstr(o, "nonce", 32);
  const char* proof = jstr(o, "proof", 64);
  const char* keyHex = jstr(o, "key", 64);
  bool nameOk;
  const char* zname = jstr(o, "zigmon", 64, &nameOk);
  uint8_t key[32];
  if (!isHex(nonce, 32) || strlen(nonce) != 32) { https::error(r, 400, "nonce: 32 hex expected"); return; }
  if (strlen(proof) != 64 || !isHex(proof, 64)) { https::error(r, 400, "proof: 64 hex expected"); return; }
  if (strlen(keyHex) != 64 || !fromHex(keyHex, 64, key, 32)) { https::error(r, 400, "key: 64 hex expected"); return; }
  if (!nameOk || !isCleanText(zname, 64)) { https::error(r, 400, "zigmon: at most 64 printable characters"); return; }
  uint8_t zero[32] = {0};
  if (ctEqual(key, zero, 32)) { https::error(r, 400, "key: all zero"); return; }

  uint32_t now = monoS();
  PairGate::Result res = g_gate.attempt(proof, cert::fingerprint(), nonce, now);
  switch (res) {
    case PairGate::OK:
      break;
    case PairGate::LOCKED: {
      // PROTOCOL.md 8.1: 429 with the seconds left as retry_in.
      uint32_t left = g_gate.lockedFor(now);
      JsonDocument e(jsonAlloc());
      e["ok"] = false;
      e["error"] = String("pairing locked for ") + left + " s";
      e["retry_in"] = left;
      r.status = 429;
      serializeJson(e, r.body);
      return;
    }
    case PairGate::NO_CODE:
      https::error(r, 401, "no pairing code is active: start pairing on the gateway first");
      return;
    case PairGate::EXPIRED:
      https::error(r, 401, "the pairing code expired: start pairing again");
      return;
    case PairGate::BAD_PROOF:
      LOGW("pair", "wrong pairing proof (the code is spent; start pairing again)");
      https::error(r, 401, "wrong code (or a different certificate): start pairing again");
      return;
  }
  bool was = config::paired();
  if (!config::setPairing(key, zname)) {
    secureZero(key, sizeof key);
    https::error(r, 500, "could not save the key");
    return;
  }
  secureZero(key, sizeof key);
  LOGI("pair", "paired with ZIGMon \"%s\"%s", zname, was ? " (replacing the previous pairing)" : "");

  JsonDocument out(jsonAlloc());
  out["ok"] = true;
  out["id"] = gatewayId();
  out["name"] = config::net().name;
  out["fw"] = GW_FW_VERSION;
  serializeJson(out, r.body);
  r.status = 200;
  // PROTOCOL.md 8.2: this answer is not signed; ZIGMon proves the key with a signed /hello.
  r.sign = false;
}

}  // namespace pairing
}  // namespace gw
