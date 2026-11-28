// ZIGMon ESP32 Gateway - the signed ZIGMon API (contract section 5).
#include "api.h"

#include <WiFi.h>

#include "core_config.h"
#include "core_events.h"
#include "core_json.h"
#include "core_log.h"
#include "core_net.h"
#include "core_pairing.h"
#include "core_proto.h"
#include "core_registry.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace api {

static proto::ReplayRing g_replay;

void routeOf(const char* uri, char* buf, size_t cap) {
  size_t n = 0;
  while (uri[n] && uri[n] != '?' && n + 1 < cap) {
    buf[n] = uri[n];
    n++;
  }
  buf[n] = 0;
}

void command(JsonObjectConst body, https::Response& r) {
  bool ok1, ok2;
  const char* entity = jstr(body, "entity", 47, &ok1);
  const char* action = jstr(body, "action", 15, &ok2);
  if (!ok1 || !ok2 || !*entity || !*action) {
    https::error(r, 400, "entity and action are required");
    return;
  }
  JsonObjectConst args = body["args"].as<JsonObjectConst>();
  if (!body["args"].isNull() && args.isNull()) {
    https::error(r, 400, "args must be an object");
    return;
  }
  Module* m = registry::ownerOf(entity);
  if (!m) {
    https::error(r, 404, "unknown entity");
    return;
  }
  CommandResult cr = m->command(entity, action, args);
  if (cr.status == 202) {
    JsonDocument d(jsonAlloc());
    d["ok"] = true;
    d["job"] = cr.job;
    r.status = 202;
    serializeJson(d, r.body);
  } else {
    https::error(r, cr.status, cr.error.length() ? cr.error.c_str() : "failed");
  }
}

static void hello(https::Response& r) {
  JsonDocument d(jsonAlloc());
  d["v"] = GW_PROTOCOL_VERSION;
  d["id"] = gatewayId();
  d["name"] = config::net().name;
  d["fw"] = GW_FW_VERSION;
  d["model"] = chipModel();
  d["mac_tail"] = macTail();
  d["time_set"] = clockSet();
  d["uptime"] = (uint32_t)(millis() / 1000);
  d["rssi"] = net::rssi();
  d["boot"] = bootId();  // additive
  JsonArray mods = d["modules"].to<JsonArray>();  // additive: ids only
  for (size_t i = 0; i < registry::count(); i++) mods.add(registry::at(i)->id());
  serializeJson(d, r.body);
}

static void describe(https::Response& r) {
  JsonDocument d(jsonAlloc());
  registry::describe(d.to<JsonObject>());
  serializeJson(d, r.body);
}

static void state(https::Response& r) {
  JsonDocument d(jsonAlloc());
  d["v"] = 1;
  d["seq"] = events::seq();
  registry::stateAll(d["entities"].to<JsonObject>());
  serializeJson(d, r.body);
}

static bool queryU32(httpd_req_t* req, const char* key, uint32_t* out) {
  char q[96], v[16];
  if (httpd_req_get_url_query_str(req, q, sizeof q) != ESP_OK) return false;
  if (httpd_query_key_value(q, key, v, sizeof v) != ESP_OK) return false;
  return parseU32(v, out);
}

esp_err_t zigmon(httpd_req_t* req) {
  https::Response r;
  r.cacheControl = "no-store";
  char route[64];
  routeOf(req->uri, route, sizeof route);
  const bool post = req->method == HTTP_POST;
  const char* method = post ? "POST" : "GET";

  const bool isPair = strcmp(route, "/zigmon/v1/pair") == 0;
  char ts[16], nonce[40], sig[72];
  bool hTs = https::header(req, "X-Zigmon-Ts", ts, sizeof ts);
  bool hNonce = https::header(req, "X-Zigmon-Nonce", nonce, sizeof nonce);
  bool hSig = https::header(req, "X-Zigmon-Sig", sig, sizeof sig);
  // PROTOCOL.md 8.3: every answer we can sign is signed (4xx too) - whenever a device key
  // exists and the request brought a well-formed nonce. /pair is never signed (8.2).
  if (!isPair && hNonce && isHex(nonce, 32)) {
    Guard g;
    if (config::paired()) {
      r.sign = true;
      copyStr(r.nonce, sizeof r.nonce, nonce);
    }
  }

  String body;
  int st = https::readBody(req, body);
  if (st) {
    https::error(r, st, st == 413 ? "body too large (max 8 KB)" : "could not read the body");
    return https::send(req, r);
  }

  // ---- pairing: the only unsigned endpoint -------------------------------------------------
  if (isPair) {
    if (!post) {
      https::error(r, 405, "POST expected");
    } else {
      Guard g;
      pairing::handlePair(body, r);
    }
    return https::send(req, r);
  }

  bool waitForEvents = false;
  uint32_t after = 0, wait = 0;
  {
    Guard g;
    if (!config::paired()) {
      https::error(r, 401, "not paired");
      return https::send(req, r);
    }
    uint32_t reqTs = 0;
    proto::Verdict v = proto::verifyRequest(
        config::deviceKey(), g_replay, nowUnix(), method, req->uri, hTs ? ts : nullptr,
        hNonce ? nonce : nullptr, hSig ? sig : nullptr, body.c_str(), body.length(), &reqTs);
    if (v != proto::Verdict::Ok) {
      LOGW("api", "%s %s refused: %s", method, route, proto::verdictText(v));
      https::error(r, 401, proto::verdictText(v));
      return https::send(req, r);
    }
    if (!clockSet()) setClock(reqTs, "ZIGMon");  // no NTP in this home: trust the signed ts

    if (strcmp(route, "/zigmon/v1/hello") == 0 && !post) {
      hello(r);
    } else if (strcmp(route, "/zigmon/v1/describe") == 0 && !post) {
      describe(r);
    } else if (strcmp(route, "/zigmon/v1/state") == 0 && !post) {
      state(r);
    } else if (strcmp(route, "/zigmon/v1/events") == 0 && !post) {
      queryU32(req, "after", &after);
      queryU32(req, "wait", &wait);
      if (wait > GW_LONGPOLL_MAX_WAIT_S) wait = GW_LONGPOLL_MAX_WAIT_S;
      // Answer now if there is something, or `after` is not ours (another boot).
      if (wait == 0 || events::hasAfter(after) || after > events::seq()) {
        JsonDocument d(jsonAlloc());
        events::fill(after, d.to<JsonObject>());
        serializeJson(d, r.body);
      } else {
        waitForEvents = true;
      }
    } else if (strcmp(route, "/zigmon/v1/command") == 0 && post) {
      JsonDocument d(jsonAlloc());
      String err;
      if (!parseJsonObject(d, body.c_str(), body.length(), err)) https::error(r, 400, err.c_str());
      else command(d.as<JsonObjectConst>(), r);
    } else if (strcmp(route, "/zigmon/v1/unpair") == 0 && post) {
      memcpy(r.key, config::deviceKey(), 32);  // sign the answer with the key being dropped
      r.keySet = true;
      pairing::unpair("ZIGMon asked");
      r.body = "{\"ok\":true}";
    } else if (strncmp(route, "/zigmon/v1/", 11) == 0) {
      bool known = strcmp(route, "/zigmon/v1/hello") == 0 || strcmp(route, "/zigmon/v1/describe") == 0 ||
                   strcmp(route, "/zigmon/v1/state") == 0 || strcmp(route, "/zigmon/v1/events") == 0 ||
                   strcmp(route, "/zigmon/v1/command") == 0 || strcmp(route, "/zigmon/v1/unpair") == 0;
      https::error(r, known ? 405 : 404, known ? "method not allowed" : "not found");
    }
  }

  if (waitForEvents) {
    // Parked outside the lock; the waiter task answers (signed) when an event comes.
    if (events::park(req, after, wait, r.nonce)) return ESP_OK;
    JsonDocument d(jsonAlloc());
    {
      Guard g;
      events::fill(after, d.to<JsonObject>());
    }
    serializeJson(d, r.body);
  }
  esp_err_t e = https::send(req, r);
  secureZero(r.key, sizeof r.key);
  return e;
}

}  // namespace api
}  // namespace gw
