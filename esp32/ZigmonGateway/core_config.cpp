// ZIGMon ESP32 Gateway - persistent settings in NVS.
#include "core_config.h"

#include <Preferences.h>
#include <WiFi.h>

#include "nvs_flash.h"

#include "core_log.h"
#include "core_registry.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace config {

// NVS keys (max 15 characters).
static const char* K_SSID = "w_ssid";
static const char* K_PASS = "w_pass";
static const char* K_DHCP = "w_dhcp";
static const char* K_IP = "w_ip";       // 16 bytes: ip, mask, gw, dns
static const char* K_HOST = "host";
static const char* K_NAME = "name";
static const char* K_PWSALT = "pw_salt";
static const char* K_PWDK = "pw_dk";
static const char* K_PWROUNDS = "pw_rounds";
static const char* K_DEVKEY = "z_key";
static const char* K_ZNAME = "z_name";
static const char* K_CERT = "tls_cert";
static const char* K_TLSKEY = "tls_key";
static const char* K_LOG = "log";

static NetConfig g_net;
static uint8_t g_key[32];
static bool g_paired = false;
static char g_zname[65];
static bool g_hasPw = false;
static uint8_t g_log = 2;

static bool open(Preferences& p, bool ro) { return p.begin(GW_NVS_NAMESPACE, ro); }

// Reads a string key into a fixed buffer; missing or too long = "".
static void getStr(Preferences& p, const char* k, char* buf, size_t cap) {
  buf[0] = 0;
  if (p.isKey(k) && p.getString(k, buf, cap) == 0) buf[0] = 0;
}

void begin() {
  memset(&g_net, 0, sizeof g_net);
  g_net.dhcp = true;
  Preferences p;
  // Read-write so the namespace exists on first boot (a read-only begin() on a missing
  // namespace fails and logs an error).
  if (!open(p, false)) {
    LOGE("config", "NVS namespace %s could not be opened", GW_NVS_NAMESPACE);
  } else {
    getStr(p, K_SSID, g_net.ssid, sizeof g_net.ssid);
    getStr(p, K_PASS, g_net.pass, sizeof g_net.pass);
    g_net.dhcp = p.getBool(K_DHCP, true);
    uint8_t ipb[16] = {0};
    if (p.getBytesLength(K_IP) == 16) p.getBytes(K_IP, ipb, 16);
    memcpy(g_net.ip, ipb, 4);
    memcpy(g_net.mask, ipb + 4, 4);
    memcpy(g_net.gw, ipb + 8, 4);
    memcpy(g_net.dns, ipb + 12, 4);
    getStr(p, K_HOST, g_net.hostname, sizeof g_net.hostname);
    getStr(p, K_NAME, g_net.name, sizeof g_net.name);
    g_hasPw = p.getBytesLength(K_PWDK) == 32 && p.getBytesLength(K_PWSALT) == 16;
    g_paired = p.getBytesLength(K_DEVKEY) == 32 && p.getBytes(K_DEVKEY, g_key, 32) == 32;
    getStr(p, K_ZNAME, g_zname, sizeof g_zname);
    g_log = p.getUChar(K_LOG, 2);
    p.end();
  }
  if (!isHostLabel(g_net.hostname)) snprintf(g_net.hostname, sizeof g_net.hostname, "zigmon-gw-%s", macTail());
  if (!g_net.name[0]) copyStr(g_net.name, sizeof g_net.name, g_net.hostname);
}

NetConfig& net() { return g_net; }

bool saveNet() {
  Preferences p;
  if (!open(p, false)) return false;
  bool ok = true;
  ok &= p.putString(K_SSID, g_net.ssid) == strlen(g_net.ssid) || !g_net.ssid[0];
  if (g_net.pass[0]) ok &= p.putString(K_PASS, g_net.pass) == strlen(g_net.pass);
  else p.remove(K_PASS);
  p.putBool(K_DHCP, g_net.dhcp);
  uint8_t ipb[16];
  memcpy(ipb, g_net.ip, 4);
  memcpy(ipb + 4, g_net.mask, 4);
  memcpy(ipb + 8, g_net.gw, 4);
  memcpy(ipb + 12, g_net.dns, 4);
  p.putBytes(K_IP, ipb, 16);
  p.putString(K_HOST, g_net.hostname);
  p.putString(K_NAME, g_net.name);
  p.end();
  if (!ok) LOGE("config", "saving the network settings failed");
  return ok;
}

bool hasPassword() { return g_hasPw; }

bool getPassword(uint8_t salt[16], uint8_t dk[32], uint32_t* rounds) {
  Preferences p;
  if (!open(p, true)) return false;
  bool ok = p.getBytes(K_PWSALT, salt, 16) == 16 && p.getBytes(K_PWDK, dk, 32) == 32;
  *rounds = p.getUInt(K_PWROUNDS, GW_PBKDF2_ROUNDS);
  p.end();
  return ok;
}

bool setPassword(const uint8_t salt[16], const uint8_t dk[32], uint32_t rounds) {
  Preferences p;
  if (!open(p, false)) return false;
  bool ok = p.putBytes(K_PWSALT, salt, 16) == 16 && p.putBytes(K_PWDK, dk, 32) == 32 &&
            p.putUInt(K_PWROUNDS, rounds) > 0;
  p.end();
  if (ok) g_hasPw = true;
  return ok;
}

bool paired() { return g_paired; }
const uint8_t* deviceKey() { return g_key; }
const char* zigmonName() { return g_zname; }

bool setPairing(const uint8_t key[32], const char* name) {
  Preferences p;
  if (!open(p, false)) return false;
  bool ok = p.putBytes(K_DEVKEY, key, 32) == 32;
  p.putString(K_ZNAME, name ? name : "");
  p.end();
  if (ok) {
    memcpy(g_key, key, 32);
    copyStr(g_zname, sizeof g_zname, name);
    g_paired = true;
  }
  return ok;
}

void clearPairing() {
  Preferences p;
  if (open(p, false)) {
    p.remove(K_DEVKEY);
    p.remove(K_ZNAME);
    p.end();
  }
  secureZero(g_key, sizeof g_key);
  g_zname[0] = 0;
  g_paired = false;
}

bool loadCert(String& certPem, String& keyPem) {
  Preferences p;
  if (!open(p, true)) return false;
  certPem = p.isKey(K_CERT) ? p.getString(K_CERT, "") : String();
  keyPem = p.isKey(K_TLSKEY) ? p.getString(K_TLSKEY, "") : String();
  p.end();
  return certPem.length() > 100 && keyPem.length() > 100;
}

bool saveCert(const String& certPem, const String& keyPem) {
  Preferences p;
  if (!open(p, false)) return false;
  bool ok = p.putString(K_CERT, certPem) == certPem.length() &&
            p.putString(K_TLSKEY, keyPem) == keyPem.length();
  p.end();
  return ok;
}

uint8_t logLevel() { return g_log; }

void setLogLevel(uint8_t l) {
  g_log = l;
  Preferences p;
  if (open(p, false)) {
    p.putUChar(K_LOG, l);
    p.end();
  }
}

void factoryReset() {
  LOGW("config", "FACTORY RESET: erasing all settings, keys and the certificate");
  // Modules first (each clears its own namespace), then the whole partition, which also
  // takes the Wi-Fi driver's saved credentials and anything a future module forgot.
  registry::factoryResetAll();
  clearPairing();
  {
    // Clear our own namespace explicitly too, in case the partition erase below is refused.
    Preferences p;
    if (open(p, false)) {
      p.clear();
      p.end();
    }
  }
  WiFi.disconnect(true, true);  // (wifioff, eraseap)
  WiFi.mode(WIFI_OFF);          // the driver lets go of its NVS handle
  delay(100);
  esp_err_t e = nvs_flash_erase();  // deinitialises the default partition first
  if (e != ESP_OK) LOGE("config", "NVS erase: %s (namespaces were cleared one by one)", esp_err_to_name(e));
  nvs_flash_init();
  secureZero(&g_net, sizeof g_net);
  delay(200);
  ESP.restart();
}

}  // namespace config
}  // namespace gw
