// ZIGMon ESP32 Gateway - BLE: NimBLE on its own FreeRTOS task with a job queue.
//
// Every BLE operation of every module (connect, scan, ...) runs here, one at a time, so the
// HTTPS server and the CLI stay responsive and modules never fight over the radio.
// NimBLE-Arduino 1.4.x. (The ESP32-S3 and -C3 have BLE 5 only, no Classic BT: fine, NimBLE
// is BLE-only anyway.)
#pragma once

#include <Arduino.h>

#include "gw_config.h"

namespace gw {
namespace ble {

class Job {
 public:
  virtual ~Job() {}
  virtual void run() = 0;        // on the BLE task, WITHOUT the gateway lock
  virtual void dropped() {}      // called instead of run() if the job could not be queued
};

bool begin();                    // NimBLE init + the task; false if BLE is unavailable
bool available();

// Queues a job (takes ownership). False when the queue is full (GW_BLE_QUEUE): the caller
// answers 409 busy; the job is deleted.
bool submit(Job* job);
size_t queued();                 // waiting, not counting the one running
bool busy();                     // a job is running now

}  // namespace ble
}  // namespace gw
