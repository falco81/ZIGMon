// ZIGMon ESP32 Gateway - request handlers.
//   api_zigmon.cpp  /zigmon/v1/*  the signed ZIGMon API (contract section 5)
//   api_web.cpp     /api/*        the web UI's API (session cookie + CSRF)
//   api_assets.cpp  everything else: the gzipped single-page web UI
#pragma once

#include <ArduinoJson.h>

#include "core_https.h"
#include "esp_http_server.h"

namespace gw {
namespace api {

esp_err_t zigmon(httpd_req_t* req);
esp_err_t web(httpd_req_t* req);
esp_err_t asset(httpd_req_t* req);

// Shared by both APIs: {"entity","action","args"} -> 202 {"ok":true,"job"} or 4xx.
void command(JsonObjectConst body, https::Response& r);

// The path without the query string, into buf.
void routeOf(const char* uri, char* buf, size_t cap);

}  // namespace api
}  // namespace gw
