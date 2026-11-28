// ZIGMon ESP32 Gateway - the HTTPS server.
#include "core_https.h"

#include <WiFi.h>

#include "esp_https_server.h"

#include "api.h"
#include "core_cert.h"
#include "core_config.h"
#include "core_log.h"
#include "core_proto.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace https {

static httpd_handle_t g_https = nullptr;
static httpd_handle_t g_http = nullptr;

const char* statusLine(int code) {
  switch (code) {
    case 200: return "200 OK";
    case 202: return "202 Accepted";
    case 204: return "204 No Content";
    case 301: return "301 Moved Permanently";
    case 400: return "400 Bad Request";
    case 401: return "401 Unauthorized";
    case 403: return "403 Forbidden";
    case 404: return "404 Not Found";
    case 405: return "405 Method Not Allowed";
    case 408: return "408 Request Timeout";
    case 409: return "409 Conflict";
    case 413: return "413 Payload Too Large";
    case 423: return "423 Locked";
    case 429: return "429 Too Many Requests";
    case 503: return "503 Service Unavailable";
    default: return "500 Internal Server Error";
  }
}

void error(Response& r, int status, const char* msg) {
  r.status = status;
  r.contentType = "application/json";
  // Hand-built: msg is our own text, but escape it anyway.
  String m;
  for (const char* p = msg; *p; p++) {
    if (*p == '"' || *p == '\\') m += '\\';
    m += ((uint8_t)*p < 0x20) ? ' ' : *p;
  }
  r.body = String("{\"ok\":false,\"error\":\"") + m + "\"}";
}

bool header(httpd_req_t* req, const char* name, char* buf, size_t cap) {
  size_t n = httpd_req_get_hdr_value_len(req, name);
  if (n == 0 || n >= cap) { buf[0] = 0; return false; }
  return httpd_req_get_hdr_value_str(req, name, buf, cap) == ESP_OK;
}

int readBody(httpd_req_t* req, String& out) {
  out = "";
  size_t len = req->content_len;
  if (len == 0) return 0;
  if (len > GW_MAX_BODY) return 413;
  if (!out.reserve(len)) return 413;
  char buf[512];
  size_t got = 0;
  int timeouts = 0;
  while (got < len) {
    size_t want = len - got;
    if (want > sizeof buf) want = sizeof buf;
    int n = httpd_req_recv(req, buf, want);
    if (n == HTTPD_SOCK_ERR_TIMEOUT) {
      if (++timeouts > 3) return 408;
      continue;
    }
    if (n <= 0) return 400;
    out.concat(buf, (unsigned int)n);
    got += (size_t)n;
  }
  return 0;
}

esp_err_t send(httpd_req_t* req, Response& r) {
  httpd_resp_set_status(req, statusLine(r.status));
  httpd_resp_set_type(req, r.contentType);
  // httpd keeps these pointers until the send below: all are literals or members of r.
  httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
  httpd_resp_set_hdr(req, "X-Frame-Options", "DENY");
  httpd_resp_set_hdr(req, "Referrer-Policy", "no-referrer");
  httpd_resp_set_hdr(req, "Cache-Control", r.cacheControl);
  if (r.html) {
    httpd_resp_set_hdr(req, "Content-Security-Policy",
                       "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
  } else {
    httpd_resp_set_hdr(req, "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
  }
  if (r.cookie.length()) httpd_resp_set_hdr(req, "Set-Cookie", r.cookie.c_str());
  char sig[65];
  if (r.sign && r.nonce[0] && (r.keySet || config::paired())) {
    proto::responseSig(r.keySet ? r.key : config::deviceKey(), r.nonce, r.status, r.body.c_str(),
                       r.body.length(), sig);
    httpd_resp_set_hdr(req, "X-Gw-Sig", sig);
  }
  if (r.asset) {
    httpd_resp_set_hdr(req, "Content-Encoding", "gzip");
    return httpd_resp_send(req, (const char*)r.asset, (ssize_t)r.assetLen);
  }
  return httpd_resp_send(req, r.body.c_str(), (ssize_t)r.body.length());
}

// ---- dispatch -----------------------------------------------------------------------------

static esp_err_t onRequest(httpd_req_t* req) {
  const char* uri = req->uri;
  if (strncmp(uri, "/zigmon/v1/", 11) == 0) return api::zigmon(req);
  if (strncmp(uri, "/api/", 5) == 0) return api::web(req);
  return api::asset(req);
}

static esp_err_t onRedirect(httpd_req_t* req) {
  // Always to our own address (never to the Host header a client sent).
  String loc = String("https://") + WiFi.localIP().toString() + "/";
  httpd_resp_set_status(req, statusLine(301));
  httpd_resp_set_hdr(req, "Location", loc.c_str());
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, "Use https", HTTPD_RESP_USE_STRLEN);
}

static bool registerAll(httpd_handle_t h, esp_err_t (*fn)(httpd_req_t*), bool post) {
  httpd_uri_t get = {};
  get.uri = "/*";
  get.method = HTTP_GET;
  get.handler = fn;
  get.user_ctx = nullptr;
  if (httpd_register_uri_handler(h, &get) != ESP_OK) return false;
  if (post) {
    httpd_uri_t p = get;
    p.method = HTTP_POST;
    if (httpd_register_uri_handler(h, &p) != ESP_OK) return false;
  }
  return true;
}

bool begin() {
  httpd_ssl_config_t conf = HTTPD_SSL_CONFIG_DEFAULT();
#if defined(ESP_IDF_VERSION_MAJOR) && ESP_IDF_VERSION_MAJOR >= 5
  conf.servercert = cert::certPem();
  conf.servercert_len = cert::certPemLen();
#else
  conf.cacert_pem = cert::certPem();        // IDF 4.4 name of the server certificate
  conf.cacert_len = cert::certPemLen();
#endif
  conf.prvtkey_pem = cert::keyPem();
  conf.prvtkey_len = cert::keyPemLen();
  conf.port_secure = GW_HTTPS_PORT;
  conf.transport_mode = HTTPD_SSL_TRANSPORT_SECURE;
  conf.httpd.uri_match_fn = httpd_uri_match_wildcard;
  conf.httpd.stack_size = GW_HTTPD_STACK;
  conf.httpd.max_open_sockets = GW_HTTPD_MAX_SOCKETS;
  conf.httpd.max_uri_handlers = 4;
  conf.httpd.max_resp_headers = 16;
  conf.httpd.lru_purge_enable = true;      // a browser's idle keep-alives make room
  conf.httpd.recv_wait_timeout = 10;
  conf.httpd.send_wait_timeout = 10;
  conf.httpd.ctrl_port = 32768;
  esp_err_t e = httpd_ssl_start(&g_https, &conf);
  if (e != ESP_OK) {
    LOGE("https", "server start failed: %s", esp_err_to_name(e));
    return false;
  }
  registerAll(g_https, onRequest, true);
  LOGI("https", "listening on :%d", GW_HTTPS_PORT);

  httpd_config_t hc = HTTPD_DEFAULT_CONFIG();
  hc.server_port = GW_HTTP_REDIRECT_PORT;
  hc.ctrl_port = 32769;                    // must differ from the HTTPS server's
  hc.uri_match_fn = httpd_uri_match_wildcard;
  hc.max_open_sockets = 2;
  hc.max_uri_handlers = 2;
  hc.stack_size = 4096;
  hc.lru_purge_enable = true;
  if (httpd_start(&g_http, &hc) == ESP_OK) registerAll(g_http, onRedirect, false);
  else LOGW("http", "redirect server on :80 not started");
  return true;
}

}  // namespace https
}  // namespace gw
