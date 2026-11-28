// ZIGMon ESP32 Gateway - network: Wi-Fi station, mDNS, NTP.
#include "core_net.h"

#include <ESPmDNS.h>
#include <WiFi.h>
#include <time.h>

#include "core_config.h"
#include "core_log.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace net {

static bool g_wasConnected = false;
static bool g_mdns = false;
static uint32_t g_lastAttempt = 0;
static bool g_scanning = false;

static IPAddress toIp(const uint8_t b[4]) { return IPAddress(b[0], b[1], b[2], b[3]); }

bool configured() { return config::net().ssid[0] != 0; }
bool connected() { return WiFi.status() == WL_CONNECTED; }
String ip() { return connected() ? WiFi.localIP().toString() : String(""); }
int rssi() { return connected() ? WiFi.RSSI() : 0; }
String ssid() { return connected() ? WiFi.SSID() : String(""); }
const char* hostname() { return config::net().hostname; }

static void connectNow() {
  NetConfig& c = config::net();
  if (!c.ssid[0]) return;
  if (!c.dhcp) {
    // Arduino's order is (ip, gateway, subnet, dns); the CLI takes ip mask gw [dns].
    WiFi.config(toIp(c.ip), toIp(c.gw), toIp(c.mask), toIp(c.dns[0] ? c.dns : c.gw));
  } else {
    WiFi.config(IPAddress((uint32_t)0), IPAddress((uint32_t)0), IPAddress((uint32_t)0));
  }
  LOGI("wifi", "connecting to \"%s\"", c.ssid);
  WiFi.begin(c.ssid, c.pass[0] ? c.pass : nullptr);
  g_lastAttempt = millis();
}

void begin() {
  // The hostname must be set before the station interface starts (core 3.x).
  WiFi.setHostname(config::net().hostname);
  WiFi.persistent(false);       // our NVS keeps the credentials, not the driver's
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);          // modem sleep is required while BLE is active (coexistence)
  WiFi.setAutoReconnect(true);
  if (configured()) connectNow();
  else LOGW("wifi", "not configured: use the CLI command  wifi set \"<ssid>\" <password>");
}

void apply() {
  WiFi.disconnect(false, false);
  delay(50);
  WiFi.setHostname(config::net().hostname);
  g_wasConnected = false;
  if (configured()) connectNow();
  else LOGI("wifi", "forgotten; not connecting");
  restartMdns();
}

void restartMdns() {
  if (g_mdns) {
    MDNS.end();
    g_mdns = false;
  }
  if (!connected()) return;
  if (!MDNS.begin(config::net().hostname)) {
    LOGW("mdns", "start failed");
    return;
  }
  g_mdns = true;
  MDNS.addService("https", "tcp", GW_HTTPS_PORT);
  // Lets ZIGMon find gateways on the LAN (optional; pairing uses the address).
  MDNS.addService("zigmon-gw", "tcp", GW_HTTPS_PORT);
  MDNS.addServiceTxt("zigmon-gw", "tcp", "id", gatewayId());
  MDNS.addServiceTxt("zigmon-gw", "tcp", "v", "1");
  MDNS.addServiceTxt("zigmon-gw", "tcp", "fw", GW_FW_VERSION);
  LOGI("mdns", "%s.local", config::net().hostname);
}

void loop() {
  bool now = connected();
  if (now && !g_wasConnected) {
    LOGI("wifi", "connected to \"%s\", IP %s, RSSI %d dBm", WiFi.SSID().c_str(),
         WiFi.localIP().toString().c_str(), WiFi.RSSI());
    // UTC is all we need (Yeelock and the signatures use Unix time).
    configTime(0, 0, "pool.ntp.org", "time.cloudflare.com", "time.google.com");
    restartMdns();
  } else if (!now && g_wasConnected) {
    LOGW("wifi", "disconnected");
  }
  g_wasConnected = now;
  // Auto-reconnect normally does it; this catches a stuck driver (and a first failed join).
  if (!now && configured() && !g_scanning && millis() - g_lastAttempt > 30000) connectNow();
}

bool scanStart() {
  if (g_scanning) return true;
  WiFi.scanDelete();
  int r = WiFi.scanNetworks(true /* async */, false /* hidden */);
  g_scanning = (r == WIFI_SCAN_RUNNING) || (r >= 0);
  return g_scanning;
}

bool scanRunning() { return g_scanning && WiFi.scanComplete() == WIFI_SCAN_RUNNING; }

// Simple, allocation-free: indices sorted by RSSI.
static void collectSorted(int n, JsonArray out) {
  if (n > 64) n = 64;
  uint8_t idx[64];
  for (int i = 0; i < n; i++) idx[i] = (uint8_t)i;
  for (int i = 1; i < n; i++) {
    uint8_t k = idx[i];
    int j = i - 1;
    while (j >= 0 && WiFi.RSSI(idx[j]) < WiFi.RSSI(k)) { idx[j + 1] = idx[j]; j--; }
    idx[j + 1] = k;
  }
  for (int i = 0; i < n && out.size() < 40; i++) {
    int k = idx[i];
    String s = WiFi.SSID(k);
    if (!s.length()) continue;
    bool dup = false;
    for (JsonObject o : out) {
      if (s == (const char*)(o["ssid"] | "")) { dup = true; break; }
    }
    if (dup) continue;
    JsonObject o = out.add<JsonObject>();
    o["ssid"] = s;
    o["rssi"] = WiFi.RSSI(k);
    o["secure"] = WiFi.encryptionType(k) != WIFI_AUTH_OPEN;
    o["ch"] = WiFi.channel(k);
  }
}

bool scanGet(JsonArray out) {
  int n = WiFi.scanComplete();
  if (n == WIFI_SCAN_RUNNING) return false;
  g_scanning = false;
  if (n > 0) collectSorted(n, out);
  return true;
}

int scanBlocking(JsonArray out) {
  g_scanning = true;
  int n = WiFi.scanNetworks(false, false);
  g_scanning = false;
  if (n > 0) collectSorted(n, out);
  WiFi.scanDelete();
  return n < 0 ? 0 : (int)out.size();
}

}  // namespace net
}  // namespace gw
