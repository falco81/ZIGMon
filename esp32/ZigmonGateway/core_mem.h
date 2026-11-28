// ZIGMon ESP32 Gateway - memory for big buffers.
//
// On boards with PSRAM (the primary target, ESP32-S3-N16R8, has 8 MB of octal PSRAM) big,
// rarely touched buffers (the event ring, the log ring, JSON documents) go to PSRAM and leave
// internal RAM to Wi-Fi, BLE and TLS. Without PSRAM they fall back to the internal heap.
#pragma once

#include <stddef.h>

namespace gw {

void* bigAlloc(size_t n);        // zeroed; PSRAM if present, else internal heap. NULL on OOM.
void* bigRealloc(void* p, size_t n);
void bigFree(void* p);
bool havePsram();

}  // namespace gw
