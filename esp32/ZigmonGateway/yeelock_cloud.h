// ZIGMon ESP32 Gateway - "Import from my Yeelock account": fetch the locks and their sign
// keys from the Yeelock cloud, once, from the ESP (the way aso824/yeehack's `fetch` does).
//
// TLS is verified against the ESP-IDF certificate bundle (esp_crt_bundle_attach); there is no
// insecure fallback. The account password and the access token live only in RAM for the two
// requests and are zeroed afterwards; they are never stored, logged or printed.
//
// Set GW_YEELOCK_CLOUD to 0 to build without it (the manual S/N + key path always remains).
#pragma once

#include <Arduino.h>

#include "yeelock_proto.h"

#ifndef GW_YEELOCK_CLOUD
#define GW_YEELOCK_CLOUD 1
#endif

namespace gw {
namespace yeelock {

struct CloudLock {
  char name[41];
  char sn[21];
  uint8_t key[KEY_MAX];
  uint8_t keyLen;
};

// Blocking (a few seconds): logs in, lists the account's locks. Returns the count (<= max),
// or -1 with a user-facing err. Wipes its copies of the password and the token.
int cloudFetch(const char* zone, const char* username, const char* password, CloudLock* out,
               size_t max, String& err);

}  // namespace yeelock
}  // namespace gw
