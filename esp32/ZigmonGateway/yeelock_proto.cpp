// ZIGMon ESP32 Gateway - Yeelock BLE packets (portable).
#include "yeelock_proto.h"

#include <string.h>

#include "core_crypto.h"
#include "core_util.h"

namespace gw {
namespace yeelock {

static void putTs(uint8_t* p, uint32_t ts) {
  p[0] = (uint8_t)(ts >> 24);
  p[1] = (uint8_t)(ts >> 16);
  p[2] = (uint8_t)(ts >> 8);
  p[3] = (uint8_t)ts;
}

void buildTimePacket(uint8_t out[PACKET_LEN], uint32_t ts, const uint8_t* key, size_t keyLen) {
  out[0] = 0x08;
  out[1] = 0x40;
  putTs(out + 2, ts);
  uint8_t mac[crypto::SHA1_LEN];
  crypto::hmacSha1(key, keyLen, out, 6, mac);
  memcpy(out + 6, mac, 14);
}

void buildActionPacket(uint8_t out[PACKET_LEN], uint32_t ts, Mode mode, const uint8_t* key,
                       size_t keyLen) {
  out[0] = 0x01;
  out[1] = 0x50;
  putTs(out + 2, ts);
  out[6] = (uint8_t)mode;
  uint8_t mac[crypto::SHA1_LEN];
  crypto::hmacSha1(key, keyLen, out, 7, mac);
  memcpy(out + 7, mac, 13);
}

size_t parseSignKey(const char* hex, uint8_t out[KEY_MAX]) {
  if (!hex) return 0;
  char clean[2 * KEY_MAX + 1];
  size_t n = 0;
  for (const char* p = hex; *p; p++) {
    char c = *p;
    if (c == ' ' || c == ':' || c == '-') continue;
    if (n >= 2 * KEY_MAX) return 0;
    clean[n++] = c;
  }
  clean[n] = 0;
  if (n % 2 || n / 2 < KEY_MIN || n / 2 > KEY_MAX) return 0;
  if (!fromHex(clean, n, out, n / 2)) return 0;
  secureZero(clean, sizeof clean);
  return n / 2;
}

bool isValidSn(const char* sn) {
  if (!sn) return false;
  size_t n = strlen(sn);
  if (n < 4 || n > 20) return false;
  for (size_t i = 0; i < n; i++) {
    char c = sn[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))) return false;
  }
  return true;
}

}  // namespace yeelock
}  // namespace gw
