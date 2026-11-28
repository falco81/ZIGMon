// ZIGMon ESP32 Gateway - BLE task and queue.
#include "core_ble.h"

#include <NimBLEDevice.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "core_log.h"

namespace gw {
namespace ble {

static QueueHandle_t g_q = nullptr;
static volatile bool g_running = false;
static bool g_ok = false;

static void task(void*) {
  for (;;) {
    Job* j = nullptr;
    if (xQueueReceive(g_q, &j, portMAX_DELAY) != pdTRUE || !j) continue;
    g_running = true;
    j->run();
    delete j;
    g_running = false;
  }
}

bool begin() {
  if (g_ok) return true;
  NimBLEDevice::init("");                // no advertising name: we are a central only
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);  // max TX power; drawers are often behind wood
  g_q = xQueueCreate(GW_BLE_QUEUE, sizeof(Job*));
  if (!g_q) return false;
  // Not pinned: works on the single-core C3 and the dual-core ESP32/S3 alike.
  if (xTaskCreate(task, "gw_ble", GW_BLE_TASK_STACK, nullptr, 3, nullptr) != pdPASS) return false;
  g_ok = true;
  LOGI("ble", "NimBLE ready");
  return true;
}

bool available() { return g_ok; }

bool submit(Job* job) {
  if (!g_ok || xQueueSend(g_q, &job, 0) != pdTRUE) {
    job->dropped();
    delete job;
    return false;
  }
  return true;
}

size_t queued() { return g_q ? (size_t)uxQueueMessagesWaiting(g_q) : 0; }
bool busy() { return g_running; }

}  // namespace ble
}  // namespace gw
