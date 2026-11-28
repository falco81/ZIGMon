// ZIGMon ESP32 Gateway - Yeelock cloud import (see yeelock_cloud.h).
//
// Endpoints and fields as used by aso824/yeehack (fetch.py, Apache-2.0), re-implemented:
//   POST https://api.yeeloc.com/oauth/access_token  (OAuth2 password grant, form-encoded)
//   GET  https://api.yeeloc.com/lock                 (Bearer) -> [{lock_name, lock_sn, ble_sign_key}]
#include "yeelock_cloud.h"

#if GW_YEELOCK_CLOUD

#include <ArduinoJson.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"

#include "core_json.h"
#include "core_log.h"
#include "core_mem.h"
#include "core_util.h"
#include "yeelock_codes.h"

namespace gw {
namespace yeelock {

static const size_t MAX_ANSWER = 16384;

// One HTTPS exchange. The answer goes into a PSRAM buffer the caller frees (and wipes).
// Returns the HTTP status, or -1 on a transport/TLS error.
static int exchange(const char* url, bool post, const char* body, size_t bodyLen, const char* bearer,
                    char** answer, size_t* answerLen) {
  *answer = nullptr;
  *answerLen = 0;
  esp_http_client_config_t cfg = {};
  cfg.url = url;
  cfg.method = post ? HTTP_METHOD_POST : HTTP_METHOD_GET;
  cfg.timeout_ms = 15000;
  cfg.crt_bundle_attach = esp_crt_bundle_attach;  // verified TLS, hostname checked
  cfg.buffer_size = 2048;
  cfg.buffer_size_tx = 1536;
  cfg.disable_auto_redirect = true;
  esp_http_client_handle_t c = esp_http_client_init(&cfg);
  if (!c) return -1;
  esp_http_client_set_header(c, "Accept", "application/json");
  esp_http_client_set_header(c, "User-Agent", "ZIGMon-Gateway");
  if (post) esp_http_client_set_header(c, "Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
  String auth;
  if (bearer) {
    auth = String("Bearer ") + bearer;
    esp_http_client_set_header(c, "Authorization", auth.c_str());
  }
  int status = -1;
  if (esp_http_client_open(c, post ? (int)bodyLen : 0) == ESP_OK) {
    bool sent = !post || esp_http_client_write(c, body, (int)bodyLen) == (int)bodyLen;
    if (sent && esp_http_client_fetch_headers(c) >= 0) {
      status = esp_http_client_get_status_code(c);
      char* buf = (char*)bigAlloc(MAX_ANSWER + 1);
      size_t n = 0;
      if (buf) {
        for (;;) {
          int r = esp_http_client_read(c, buf + n, (int)(MAX_ANSWER - n));
          if (r <= 0) break;
          n += (size_t)r;
          if (n >= MAX_ANSWER) break;
        }
        buf[n] = 0;
        *answer = buf;
        *answerLen = n;
      }
    }
  }
  esp_http_client_close(c);
  esp_http_client_cleanup(c);
  for (unsigned i = 0; i < auth.length(); i++) auth.setCharAt(i, 0);
  return status;
}

static void dropAnswer(char* a, size_t n) {
  if (!a) return;
  secureZero(a, n);
  bigFree(a);
}

int cloudFetch(const char* zone, const char* username, const char* password, CloudLock* out,
               size_t max, String& err) {
  if (!validZone(zone)) { err = "zone: the country calling code, digits only (e.g. 420)"; return -1; }
  if (!validUsername(username)) { err = "username: the phone number without the country code"; return -1; }
  const size_t CAP = 768;
  char* body = (char*)bigAlloc(CAP);
  char* url = (char*)bigAlloc(CAP + 64);
  char token[512] = {0};
  int count = -1;
  do {
    if (!body || !url) { err = "out of memory"; break; }
    size_t bl = buildTokenBody(zone, username, password, body, CAP);
    if (bl == (size_t)-1) { err = "username or password too long"; break; }

    char* ans = nullptr;
    size_t al = 0;
    int st = exchange(CLOUD_TOKEN_URL, true, body, bl, nullptr, &ans, &al);
    // yeehack sends these as URL parameters; a server that wants them there answers
    // invalid_request to a form body. Then (only then) ask once more that way.
    if (st == 400 && ans && strstr(ans, "invalid_request")) {
      dropAnswer(ans, al);
      snprintf(url, CAP + 64, "%s?%s", CLOUD_TOKEN_URL, body);
      st = exchange(url, true, "", 0, nullptr, &ans, &al);
      secureZero(url, CAP + 64);
    }
    secureZero(body, CAP);
    if (st < 0) { dropAnswer(ans, al); err = "could not reach api.yeeloc.com (Wi-Fi? DNS? certificate?)"; break; }
    {
      JsonDocument filter;
      filter["access_token"] = true;
      filter["error"] = true;
      filter["message"] = true;
      JsonDocument d(jsonAlloc());
      DeserializationError e = ans ? deserializeJson(d, ans, al, DeserializationOption::Filter(filter))
                                   : DeserializationError(DeserializationError::EmptyInput);
      const char* t = e ? nullptr : d["access_token"].as<const char*>();
      if (st != 200 || !t || !*t || strlen(t) >= sizeof token) {
        if (st == 400 || st == 401) err = "the Yeelock account rejected the login (zone, phone number, password?)";
        else err = String("unexpected answer from the Yeelock cloud (HTTP ") + st + ")";
        d.clear();
        dropAnswer(ans, al);
        break;
      }
      copyStr(token, sizeof token, t);
      d.clear();
      dropAnswer(ans, al);
    }

    st = exchange(CLOUD_LOCKS_URL, false, nullptr, 0, token, &ans, &al);
    secureZero(token, sizeof token);
    if (st != 200 || !ans) {
      dropAnswer(ans, al);
      err = String("the lock list could not be read (HTTP ") + st + ")";
      break;
    }
    JsonDocument filter;
    filter[0]["lock_name"] = true;
    filter[0]["lock_sn"] = true;
    filter[0]["ble_sign_key"] = true;
    JsonDocument d(jsonAlloc());
    DeserializationError e = deserializeJson(d, ans, al, DeserializationOption::Filter(filter),
                                             DeserializationOption::NestingLimit(4));
    dropAnswer(ans, al);
    if (e || !d.is<JsonArray>()) { err = "unexpected lock list from the Yeelock cloud"; break; }
    count = 0;
    for (JsonObjectConst o : d.as<JsonArrayConst>()) {
      if ((size_t)count >= max) break;
      const char* sn = o["lock_sn"] | "";
      const char* nm = o["lock_name"] | "";
      const char* key = o["ble_sign_key"] | "";
      CloudLock& cl = out[count];
      memset(&cl, 0, sizeof cl);
      if (!isValidSn(sn)) continue;
      copyStr(cl.sn, sizeof cl.sn, sn);
      if (!copyStr(cl.name, sizeof cl.name, nm) || !isCleanText(cl.name, 40) || !cl.name[0])
        snprintf(cl.name, sizeof cl.name, "Yeelock %s", cl.sn);
      cl.keyLen = (uint8_t)parseSignKey(key, cl.key);  // 0 if the account has no key for it
      count++;
    }
    d.clear();
  } while (false);
  secureZero(token, sizeof token);
  if (body) { secureZero(body, CAP); bigFree(body); }
  if (url) { secureZero(url, CAP + 64); bigFree(url); }
  if (count >= 0) LOGI("yeelock", "cloud import: %d lock(s) in the account", count);
  else LOGW("yeelock", "cloud import failed: %s", err.c_str());
  return count;
}

}  // namespace yeelock
}  // namespace gw

#else  // !GW_YEELOCK_CLOUD

namespace gw {
namespace yeelock {
int cloudFetch(const char*, const char*, const char*, CloudLock*, size_t, String& err) {
  err = "this firmware was built without the cloud import (GW_YEELOCK_CLOUD 0)";
  return -1;
}
}  // namespace yeelock
}  // namespace gw

#endif
