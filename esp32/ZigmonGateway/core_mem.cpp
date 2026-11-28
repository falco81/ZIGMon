// ZIGMon ESP32 Gateway - memory for big buffers (see core_mem.h).
#include "core_mem.h"

#include <stdlib.h>
#include <string.h>

#if defined(ESP_PLATFORM)
#  include "esp_heap_caps.h"
#endif

namespace gw {

bool havePsram() {
#if defined(ESP_PLATFORM)
  return heap_caps_get_total_size(MALLOC_CAP_SPIRAM) > 0;
#else
  return false;
#endif
}

void* bigAlloc(size_t n) {
  void* p = nullptr;
#if defined(ESP_PLATFORM)
  if (havePsram()) p = heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!p) p = heap_caps_malloc(n, MALLOC_CAP_8BIT);
#else
  p = malloc(n);
#endif
  if (p) memset(p, 0, n);
  return p;
}

void* bigRealloc(void* p, size_t n) {
#if defined(ESP_PLATFORM)
  void* q = nullptr;
  if (havePsram()) q = heap_caps_realloc(p, n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!q) q = heap_caps_realloc(p, n, MALLOC_CAP_8BIT);
  return q;
#else
  return realloc(p, n);
#endif
}

void bigFree(void* p) {
#if defined(ESP_PLATFORM)
  heap_caps_free(p);
#else
  free(p);
#endif
}

}  // namespace gw
