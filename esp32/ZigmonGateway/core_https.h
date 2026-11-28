// ZIGMon ESP32 Gateway - the HTTPS server (esp_https_server): ZIGMon API + web UI on :443,
// and a plain-HTTP redirect on :80.
//
// API notes (ESP-IDF 5 / core 3.x vs ESP-IDF 4.4 / core 2.x):
//  - httpd_ssl_config_t: the server certificate is `servercert`/`servercert_len` in IDF 5;
//    in IDF 4.4 it was `cacert_pem`/`cacert_len` (which IDF 5 uses for client CAs).
//  - The PEM lengths include the terminating NUL.
//  - Long polling uses httpd_req_async_handler_begin()/complete() (IDF 5.1+); see
//    GW_HTTPD_ASYNC in gw_config.h.
#pragma once

#include <Arduino.h>

#include "esp_http_server.h"

namespace gw {
namespace https {

bool begin();

struct Response {
  int status = 200;
  String body;
  const char* contentType = "application/json";
  String cookie;                 // Set-Cookie value, if any
  bool sign = false;             // add X-Gw-Sig (ZIGMon API, when paired)
  char nonce[33] = {0};          // the request's X-Zigmon-Nonce, for the signature
  uint8_t key[32] = {0};         // signing key override (keySet), e.g. /unpair signs with
  bool keySet = false;           // the key it is about to forget
  const uint8_t* asset = nullptr;  // static file (gzipped) instead of body
  size_t assetLen = 0;
  const char* cacheControl = "no-store";
  bool html = false;             // add the page-only headers
};

// Sends r with the security headers. Safe from another task for an async request copy.
esp_err_t send(httpd_req_t* req, Response& r);

// Request header into buf; false if absent or longer than cap-1.
bool header(httpd_req_t* req, const char* name, char* buf, size_t cap);

// Reads the body (<= GW_MAX_BODY). Returns 0, or the HTTP status to answer (400/408/413).
int readBody(httpd_req_t* req, String& out);

// JSON error body {"ok":false,"error":"..."} into r.
void error(Response& r, int status, const char* msg);

const char* statusLine(int code);

}  // namespace https
}  // namespace gw
