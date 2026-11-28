// ZIGMon ESP32 Gateway - system basics.
#include "core_sys.h"

#include <sys/time.h>
#include <time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_timer.h"
#if __has_include("esp_mac.h")
#  include "esp_mac.h"      // IDF 5 (core 3.x)
#else
#  include "esp_system.h"   // IDF 4.4 (core 2.x)
#endif

#include "core_config.h"
#include "core_crypto.h"
#include "core_log.h"
#include "core_net.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {

static SemaphoreHandle_t g_lock = nullptr;

void lockInit() {
  if (!g_lock) g_lock = xSemaphoreCreateRecursiveMutex();
}

Guard::Guard() { xSemaphoreTakeRecursive(g_lock, portMAX_DELAY); }
Guard::~Guard() { xSemaphoreGiveRecursive(g_lock); }

uint32_t monoS() { return (uint32_t)(esp_timer_get_time() / 1000000LL) + 1; }

uint32_t nowUnix() {
  time_t t = time(nullptr);
  return t > 0 ? (uint32_t)t : 0;
}

bool clockSet() { return nowUnix() >= GW_CLOCK_VALID_FROM; }

void setClock(uint32_t unix, const char* source) {
  struct timeval tv;
  tv.tv_sec = (time_t)unix;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  LOGI("time", "clock set from %s: %lu", source, (unsigned long)unix);
}

static char g_id[13], g_tail[7], g_boot[9];

static void identityInit() {
  if (g_id[0]) return;
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  toHex(mac, 6, g_id);
  memcpy(g_tail, g_id + 6, 7);
  crypto::randomHex(g_boot, 4);
}

const char* gatewayId() { identityInit(); return g_id; }
const char* macTail() { identityInit(); return g_tail; }
const char* bootId() { identityInit(); return g_boot; }

const char* chipModel() {
#if defined(CONFIG_IDF_TARGET_ESP32S3)
  return "esp32s3";
#elif defined(CONFIG_IDF_TARGET_ESP32C3)
  return "esp32c3";
#elif defined(CONFIG_IDF_TARGET_ESP32)
  return "esp32";
#elif defined(CONFIG_IDF_TARGET)
  return CONFIG_IDF_TARGET;  // e.g. "esp32c6": not in the contract's list, shown as-is
#else
  return "esp32";
#endif
}

static volatile Deferred g_def = Deferred::None;
static volatile uint32_t g_defAt = 0;

void defer(Deferred what, uint32_t delayMs) {
  // A factory reset or reboot outranks a pending Wi-Fi change.
  if (g_def == Deferred::FactoryReset) return;
  if (g_def == Deferred::Reboot && what != Deferred::FactoryReset) return;
  g_def = what;
  g_defAt = millis() + delayMs;
}

void runDeferred() {
  if (g_def == Deferred::None || (int32_t)(millis() - g_defAt) < 0) return;
  Deferred d = g_def;
  g_def = Deferred::None;
  switch (d) {
    case Deferred::Reboot:
      LOGW("sys", "rebooting");
      delay(100);
      ESP.restart();
      break;
    case Deferred::FactoryReset:
      config::factoryReset();  // erases NVS and reboots; does not return
      break;
    case Deferred::WifiApply:
      net::apply();
      break;
    case Deferred::MdnsRestart:
      net::restartMdns();
      break;
    case Deferred::None:
      break;
  }
}

}  // namespace gw
