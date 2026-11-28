// ZIGMon ESP32 Gateway - the web UI's API (/api/*): session cookie + CSRF header.
//
// Unauthenticated: GET /api/session, POST /api/setup (first run only), POST /api/login.
// Those two POSTs still need an X-Gw-Csrf header (any value): a custom header can't be sent
// cross-site without a CORS preflight, which this server never grants. Everything else needs
// a live session, and every POST the session's own CSRF token.
#include "api.h"

#include <WiFi.h>

#include "core_auth.h"
#include "core_cert.h"
#include "core_config.h"
#include "core_events.h"
#include "core_jobs.h"
#include "core_json.h"
#include "core_log.h"
#include "core_mem.h"
#include "core_net.h"
#include "core_pairing.h"
#include "core_registry.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

#include "esp_chip_info.h"

namespace gw {
namespace api {

namespace {

struct Ctx {
  httpd_req_t* req;
  const char* route;     // without "/api"
  bool post;
  JsonObjectConst in;    // parsed body (POST)
  https::Response* r;
  int slot;              // session slot
};

void ok(https::Response& r, JsonDocument& d) {
  if (d["ok"].isNull()) d["ok"] = true;
  serializeJson(d, r.body);
}

void okEmpty(https::Response& r) { r.body = "{\"ok\":true}"; }

// ---- session ----------------------------------------------------------------------------------

void sessionInfo(Ctx& c) {
  JsonDocument d(jsonAlloc());
  d["v"] = 1;
  d["password_set"] = auth::passwordSet();
  d["setup_open"] = auth::firstRunOpen();
  d["setup_left"] = auth::firstRunLeft();
  d["logged_in"] = c.slot >= 0;
  if (c.slot >= 0) d["csrf"] = auth::csrf(c.slot);
  d["lockout"] = auth::lockoutLeft();
  d["name"] = config::net().name;
  d["fw"] = GW_FW_VERSION;
  ok(*c.r, d);
}

void setup(Ctx& c) {
  if (auth::passwordSet()) { https::error(*c.r, 409, "a password is already set: log in"); return; }
  if (!auth::firstRunOpen()) {
    https::error(*c.r, 403, "the first-run window is closed: run `webinit` on the serial console");
    return;
  }
  String err;
  if (!auth::setPassword(jstr(c.in, "password", 128), err)) { https::error(*c.r, 400, err.c_str()); return; }
  char tok[33], csrf[33];
  auth::newSession(tok, csrf);
  c.r->cookie = auth::cookieFor(tok);
  JsonDocument d(jsonAlloc());
  d["csrf"] = csrf;
  ok(*c.r, d);
  secureZero(tok, sizeof tok);
}

void login(Ctx& c) {
  char tok[33], csrf[33];
  uint32_t wait = 0;
  auth::Login res = auth::login(jstr(c.in, "password", 128), tok, csrf, &wait);
  switch (res) {
    case auth::Login::Ok: {
      c.r->cookie = auth::cookieFor(tok);
      JsonDocument d(jsonAlloc());
      d["csrf"] = csrf;
      ok(*c.r, d);
      break;
    }
    case auth::Login::NoPassword:
      https::error(*c.r, 409, "no password is set yet");
      break;
    case auth::Login::Locked:
    case auth::Login::Bad: {
      JsonDocument d(jsonAlloc());
      d["ok"] = false;
      d["error"] = res == auth::Login::Locked ? "too many attempts: wait" : "wrong password";
      d["wait"] = wait;
      c.r->status = res == auth::Login::Locked ? 429 : 401;
      serializeJson(d, c.r->body);
      break;
    }
  }
  secureZero(tok, sizeof tok);
}

// ---- overview -----------------------------------------------------------------------------------

void addWifi(JsonObject w) {
  NetConfig& n = config::net();
  w["configured"] = n.ssid[0] != 0;
  w["ssid"] = n.ssid;
  w["connected"] = net::connected();
  w["ip"] = net::ip();
  w["rssi"] = net::rssi();
  w["hostname"] = n.hostname;
  w["dhcp"] = n.dhcp;
}

void overview(Ctx& c) {
  JsonDocument d(jsonAlloc());
  JsonObject g = d["gateway"].to<JsonObject>();
  g["name"] = config::net().name;
  g["id"] = gatewayId();
  g["fw"] = GW_FW_VERSION;
  g["model"] = chipModel();
  g["uptime"] = (uint32_t)(millis() / 1000);
  g["heap"] = (uint32_t)ESP.getFreeHeap();
  g["psram"] = havePsram();
  addWifi(d["wifi"].to<JsonObject>());
  JsonObject t = d["time"].to<JsonObject>();
  t["set"] = clockSet();
  t["now"] = nowUnix();
  JsonObject z = d["zigmon"].to<JsonObject>();
  z["paired"] = config::paired();
  z["name"] = config::zigmonName();
  JsonArray mods = d["modules"].to<JsonArray>();
  for (size_t i = 0; i < registry::count(); i++) {
    Module* m = registry::at(i);
    JsonObject o = mods.add<JsonObject>();
    o["id"] = m->id();
    o["name"] = m->name();
    o["version"] = m->version();
    o["icon"] = m->icon();
    m->overview(o["overview"].to<JsonObject>());
  }
  jobs::recent(d["jobs"].to<JsonArray>(), 6);
  ok(*c.r, d);
}

// ---- Wi-Fi -------------------------------------------------------------------------------------------

void ipStr(JsonObject o, const char* k, const uint8_t b[4]) {
  char s[16];
  snprintf(s, sizeof s, "%u.%u.%u.%u", b[0], b[1], b[2], b[3]);
  o[k] = s;
}

void wifiGet(Ctx& c) {
  JsonDocument d(jsonAlloc());
  JsonObject w = d.to<JsonObject>();
  addWifi(w);
  NetConfig& n = config::net();
  char m[16];
  w["password"] = maskSecret(n.pass, m, sizeof m);
  JsonObject s = w["static"].to<JsonObject>();
  ipStr(s, "ip", n.ip);
  ipStr(s, "mask", n.mask);
  ipStr(s, "gw", n.gw);
  ipStr(s, "dns", n.dns);
  ok(*c.r, d);
}

void wifiSet(Ctx& c) {
  bool okS, okP;
  const char* ssid = jstr(c.in, "ssid", 32, &okS);
  const char* pass = jstr(c.in, "password", 63, &okP);
  if (!okS || !*ssid) { https::error(*c.r, 400, "SSID: 1 to 32 bytes"); return; }
  if (!okP) { https::error(*c.r, 400, "password: at most 63 characters"); return; }
  size_t pl = strlen(pass);
  if (pl && pl < 8) { https::error(*c.r, 400, "a WPA password has at least 8 characters"); return; }
  NetConfig& n = config::net();
  bool dhcp = c.in["dhcp"] | true;
  uint8_t ip[4] = {0}, mask[4] = {0}, gw[4] = {0}, dns[4] = {0};
  if (!dhcp) {
    if (!parseIPv4(jstr(c.in, "ip", 15), ip) || !parseIPv4(jstr(c.in, "mask", 15), mask) ||
        !parseIPv4(jstr(c.in, "gw", 15), gw)) {
      https::error(*c.r, 400, "static IP: ip, mask and gateway are required");
      return;
    }
    const char* d = jstr(c.in, "dns", 15);
    if (*d && !parseIPv4(d, dns)) { https::error(*c.r, 400, "DNS: an IPv4 address"); return; }
  }
  bool sameNet = strcmp(n.ssid, ssid) == 0;
  // An empty password keeps the stored one for the same network ("unchanged").
  bool keep = pl == 0 && sameNet && !(c.in["open"] | false);
  copyStr(n.ssid, sizeof n.ssid, ssid);
  if (!keep) copyStr(n.pass, sizeof n.pass, pass);
  n.dhcp = dhcp;
  memcpy(n.ip, ip, 4);
  memcpy(n.mask, mask, 4);
  memcpy(n.gw, gw, 4);
  memcpy(n.dns, dns, 4);
  if (!config::saveNet()) { https::error(*c.r, 500, "could not save"); return; }
  LOGI("wifi", "settings changed from the web UI");
  defer(Deferred::WifiApply, 1500);  // after this answer is out
  okEmpty(*c.r);
}

void wifiScan(Ctx& c) {
  JsonDocument d(jsonAlloc());
  if (c.post) {
    d["running"] = net::scanStart();
  } else {
    JsonArray arr = d["networks"].to<JsonArray>();
    d["running"] = !net::scanGet(arr);
  }
  ok(*c.r, d);
}

// ---- ZIGMon ---------------------------------------------------------------------------------------

void zigmonGet(Ctx& c) {
  JsonDocument d(jsonAlloc());
  d["paired"] = config::paired();
  d["zigmon"] = config::zigmonName();
  d["fingerprint"] = cert::fingerprint();
  d["fingerprint_pretty"] = cert::fingerprintPretty();
  d["id"] = gatewayId();
  d["ip"] = net::ip();
  d["hostname"] = config::net().hostname;
  JsonObject p = d["pairing"].to<JsonObject>();
  p["active"] = pairing::active();
  if (pairing::active()) {
    p["code"] = pairing::code();
    p["expires_in"] = pairing::expiresIn();
  }
  p["locked_for"] = pairing::lockedFor();
  ok(*c.r, d);
}

void zigmonPair(Ctx& c) {
  String err;
  if (!pairing::start(err)) { https::error(*c.r, 429, err.c_str()); return; }
  zigmonGet(c);
}

// ---- system ---------------------------------------------------------------------------------------

struct LogCtx { JsonArray arr; };
void addLine(const char* line, void* ctx) { ((LogCtx*)ctx)->arr.add(line); }

void systemGet(Ctx& c) {
  JsonDocument d(jsonAlloc());
  d["fw"] = GW_FW_VERSION;
  d["model"] = chipModel();
  esp_chip_info_t ci;
  esp_chip_info(&ci);
  d["cores"] = ci.cores;
  d["revision"] = ci.revision;
  d["flash"] = (uint32_t)ESP.getFlashChipSize();
  d["psram"] = (uint32_t)ESP.getPsramSize();
  d["heap"] = (uint32_t)ESP.getFreeHeap();
  d["heap_min"] = (uint32_t)ESP.getMinFreeHeap();
  d["uptime"] = (uint32_t)(millis() / 1000);
  d["hostname"] = config::net().hostname;
  d["name"] = config::net().name;
  d["id"] = gatewayId();
  d["fingerprint"] = cert::fingerprint();
  d["fingerprint_pretty"] = cert::fingerprintPretty();
  d["time_set"] = clockSet();
  d["now"] = nowUnix();
  d["log_level"] = log::levelName(log::level());
  d["sdk"] = ESP.getSdkVersion();
  LogCtx lc{d["log"].to<JsonArray>()};
  log::tail(addLine, &lc, 80);
  ok(*c.r, d);
}

void systemPassword(Ctx& c) {
  if (!auth::checkPassword(jstr(c.in, "current", 128))) {
    https::error(*c.r, 403, "the current password is wrong");
    return;
  }
  String err;
  if (!auth::setPassword(jstr(c.in, "new", 128), err)) { https::error(*c.r, 400, err.c_str()); return; }
  // setPassword() logged every session out; give this browser a fresh one.
  char tok[33], csrf[33];
  auth::newSession(tok, csrf);
  c.r->cookie = auth::cookieFor(tok);
  JsonDocument d(jsonAlloc());
  d["csrf"] = csrf;
  ok(*c.r, d);
  secureZero(tok, sizeof tok);
}

void systemNames(Ctx& c) {
  bool okH, okN;
  const char* host = jstr(c.in, "hostname", 32, &okH);
  const char* name = jstr(c.in, "name", 40, &okN);
  if (!okH || (*host && !isHostLabel(host))) {
    https::error(*c.r, 400, "hostname: a-z, 0-9 and -, up to 32 characters");
    return;
  }
  if (!okN || !isCleanText(name, 40)) { https::error(*c.r, 400, "name: up to 40 printable characters"); return; }
  NetConfig& n = config::net();
  bool hostChanged = *host && strcmp(host, n.hostname) != 0;
  if (*host) copyStr(n.hostname, sizeof n.hostname, host);
  if (*name) copyStr(n.name, sizeof n.name, name);
  config::saveNet();
  if (hostChanged) defer(Deferred::MdnsRestart, 500);
  okEmpty(*c.r);
}

void systemTime(Ctx& c) {
  uint32_t t = c.in["unix"] | 0u;
  if (t < GW_CLOCK_VALID_FROM) { https::error(*c.r, 400, "unix: a current Unix time"); return; }
  setClock(t, "the web UI");
  okEmpty(*c.r);
}

void systemLog(Ctx& c) {
  log::Level l;
  if (!log::parseLevel(jstr(c.in, "level", 8), &l)) { https::error(*c.r, 400, "level: error|warn|info|debug"); return; }
  log::setLevel(l);
  config::setLogLevel(l);
  okEmpty(*c.r);
}

void systemReboot(Ctx& c) {
  defer(Deferred::Reboot, 800);
  okEmpty(*c.r);
}

void systemFactoryReset(Ctx& c) {
  // Typed confirmation, checked here too (not only in the browser).
  if (strcmp(jstr(c.in, "confirm", 32), "FACTORY RESET") != 0) {
    https::error(*c.r, 400, "type FACTORY RESET to confirm");
    return;
  }
  if (!auth::checkPassword(jstr(c.in, "password", 128))) {
    https::error(*c.r, 403, "the password is wrong");
    return;
  }
  LOGW("sys", "factory reset requested from the web UI");
  defer(Deferred::FactoryReset, 1000);
  okEmpty(*c.r);
}

// ---- modules -------------------------------------------------------------------------------------

void modulesList(Ctx& c) {
  JsonDocument d(jsonAlloc());
  JsonArray arr = d["modules"].to<JsonArray>();
  for (size_t i = 0; i < registry::count(); i++) {
    Module* m = registry::at(i);
    JsonObject o = arr.add<JsonObject>();
    o["id"] = m->id();
    o["name"] = m->name();
    o["version"] = m->version();
    o["icon"] = m->icon();
    m->overview(o["overview"].to<JsonObject>());
  }
  ok(*c.r, d);
}

void moduleGet(Ctx& c, Module* m) {
  JsonDocument d(jsonAlloc());
  JsonObject mo = d["module"].to<JsonObject>();
  mo["id"] = m->id();
  mo["name"] = m->name();
  mo["version"] = m->version();
  mo["icon"] = m->icon();
  m->settingsSchema(d["schema"].to<JsonObject>());
  m->settingsGet(d["settings"].to<JsonObject>());
  m->itemsGet(d["items"].to<JsonArray>());
  m->describe(d["entities"].to<JsonArray>());
  m->state(d["states"].to<JsonObject>());
  m->discoverGet(d["discover"].to<JsonObject>());
  ok(*c.r, d);
}

// /api/m/<id>[/settings|/items[/<item>[/delete]]|/discover]
void moduleRoute(Ctx& c) {
  const char* rest = c.route + 3;  // after "/m/"
  char id[16];
  size_t n = 0;
  while (rest[n] && rest[n] != '/' && n < sizeof id - 1) { id[n] = rest[n]; n++; }
  id[n] = 0;
  Module* m = registry::find(id);
  if (!m) { https::error(*c.r, 404, "unknown module"); return; }
  const char* sub = rest + n;  // "" or "/..."
  String err;
  if (!*sub && !c.post) { moduleGet(c, m); return; }
  if (strcmp(sub, "/settings") == 0 && c.post) {
    if (!m->settingsSet(c.in, err)) https::error(*c.r, 400, err.c_str());
    else okEmpty(*c.r);
    return;
  }
  if (strcmp(sub, "/discover") == 0) {
    if (c.post) {
      if (!m->discoverStart(err)) { https::error(*c.r, 409, err.c_str()); return; }
    }
    JsonDocument d(jsonAlloc());
    m->discoverGet(d.to<JsonObject>());
    ok(*c.r, d);
    return;
  }
  if (strncmp(sub, "/x/", 3) == 0 && isSlug(sub + 3, 24)) {
    JsonDocument d(jsonAlloc());
    JsonObject out = d.to<JsonObject>();
    int st = m->webCall(sub + 3, c.post, c.in, out, err);
    if (st >= 400) { https::error(*c.r, st, err.length() ? err.c_str() : "failed"); return; }
    c.r->status = st;
    ok(*c.r, d);
    return;
  }
  if (strcmp(sub, "/items") == 0 && c.post) {
    String saved;
    if (!m->itemSave(nullptr, c.in, saved, err)) { https::error(*c.r, 400, err.c_str()); return; }
    JsonDocument d(jsonAlloc());
    d["id"] = saved;
    ok(*c.r, d);
    return;
  }
  if (strncmp(sub, "/items/", 7) == 0 && c.post) {
    char item[32];
    const char* p = sub + 7;
    size_t k = 0;
    while (p[k] && p[k] != '/' && k < sizeof item - 1) { item[k] = p[k]; k++; }
    item[k] = 0;
    const char* tail = p + k;
    if (strcmp(tail, "/delete") == 0) {
      if (!m->itemDelete(item, err)) https::error(*c.r, 404, err.c_str());
      else okEmpty(*c.r);
      return;
    }
    if (!*tail) {
      String saved;
      if (!m->itemSave(item, c.in, saved, err)) { https::error(*c.r, 400, err.c_str()); return; }
      JsonDocument d(jsonAlloc());
      d["id"] = saved;
      ok(*c.r, d);
      return;
    }
  }
  https::error(*c.r, 404, "not found");
}

void stateGet(Ctx& c) {
  JsonDocument d(jsonAlloc());
  d["seq"] = events::seq();
  registry::stateAll(d["entities"].to<JsonObject>());
  jobs::recent(d["jobs"].to<JsonArray>(), 8);
  ok(*c.r, d);
}

}  // namespace

esp_err_t web(httpd_req_t* req) {
  https::Response r;
  char route[96];
  routeOf(req->uri + 4, route, sizeof route);  // strip "/api"
  const bool post = req->method == HTTP_POST;

  String body;
  int st = https::readBody(req, body);
  if (st) {
    https::error(r, st, st == 413 ? "body too large (max 8 KB)" : "could not read the body");
    return https::send(req, r);
  }
  JsonDocument in(jsonAlloc());
  if (post) {
    String err;
    if (body.length() == 0) body = "{}";
    if (!parseJsonObject(in, body.c_str(), body.length(), err)) {
      https::error(r, 400, err.c_str());
      return https::send(req, r);
    }
  }
  // Wipe the raw body early: it may hold a password.
  for (unsigned i = 0; i < body.length(); i++) body.setCharAt(i, 0);

  char cookie[512], tok[33], csrfHdr[40];
  https::header(req, "Cookie", cookie, sizeof cookie);
  auth::tokenFromCookie(cookie, tok);
  bool haveCsrf = https::header(req, "X-Gw-Csrf", csrfHdr, sizeof csrfHdr);

  {
    Guard g;
    Ctx c{req, route, post, in.as<JsonObjectConst>(), &r, auth::session(tok)};

    if (strcmp(route, "/session") == 0 && !post) { sessionInfo(c); goto done; }
    if (post && (strcmp(route, "/setup") == 0 || strcmp(route, "/login") == 0)) {
      if (!haveCsrf) { https::error(r, 403, "missing X-Gw-Csrf header"); goto done; }
      if (route[1] == 's') setup(c); else login(c);
      goto done;
    }
    if (c.slot < 0) {
      https::error(r, 401, auth::passwordSet() ? "log in first" : "set the admin password first");
      goto done;
    }
    if (post && !auth::csrfOk(c.slot, haveCsrf ? csrfHdr : "")) {
      https::error(r, 403, "bad CSRF token: reload the page");
      goto done;
    }

    if (strcmp(route, "/logout") == 0 && post) {
      auth::logout(c.slot);
      r.cookie = auth::cookieClear();
      okEmpty(r);
    } else if (strcmp(route, "/overview") == 0 && !post) overview(c);
    else if (strcmp(route, "/state") == 0 && !post) stateGet(c);
    else if (strcmp(route, "/command") == 0 && post) command(c.in, r);
    else if (strcmp(route, "/wifi") == 0) { if (post) wifiSet(c); else wifiGet(c); }
    else if (strcmp(route, "/wifi/scan") == 0) wifiScan(c);
    else if (strcmp(route, "/zigmon") == 0 && !post) zigmonGet(c);
    else if (strcmp(route, "/zigmon/pair") == 0 && post) zigmonPair(c);
    else if (strcmp(route, "/zigmon/cancel") == 0 && post) { pairing::cancel(); zigmonGet(c); }
    else if (strcmp(route, "/zigmon/unpair") == 0 && post) { pairing::unpair("web UI"); zigmonGet(c); }
    else if (strcmp(route, "/system") == 0 && !post) systemGet(c);
    else if (strcmp(route, "/system/password") == 0 && post) systemPassword(c);
    else if (strcmp(route, "/system/names") == 0 && post) systemNames(c);
    else if (strcmp(route, "/system/time") == 0 && post) systemTime(c);
    else if (strcmp(route, "/system/log") == 0 && post) systemLog(c);
    else if (strcmp(route, "/system/reboot") == 0 && post) systemReboot(c);
    else if (strcmp(route, "/system/factory-reset") == 0 && post) systemFactoryReset(c);
    else if (strcmp(route, "/modules") == 0 && !post) modulesList(c);
    else if (strncmp(route, "/m/", 3) == 0) moduleRoute(c);
    else https::error(r, 404, "not found");
  }
done:
  secureZero(tok, sizeof tok);
  return https::send(req, r);
}

}  // namespace api
}  // namespace gw
