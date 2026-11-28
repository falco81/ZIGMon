// ZIGMon ESP32 Gateway - Yeelock BLE packets (contract section 6; portable, unit-tested).
//
// The Yeelock protocol is unofficial and community-derived (reverse engineering by
// aso824/yeehack and cnrd/yeelock). Both packets are 20 bytes; ts is Unix UTC big-endian and
// the signature is a truncated HMAC-SHA1 keyed with the lock's ble_sign_key bytes.
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace gw {
namespace yeelock {

static const size_t PACKET_LEN = 20;
static const size_t KEY_MIN = 8;    // bytes
static const size_t KEY_MAX = 32;

enum Mode : uint8_t { MODE_OPEN = 0x00, MODE_UNLOCK = 0x01, MODE_LOCK = 0x02 };

// 08 40 ts(4) HMAC-SHA1(key, bytes 0-5)[0:14]
void buildTimePacket(uint8_t out[PACKET_LEN], uint32_t ts, const uint8_t* key, size_t keyLen);

// 01 50 ts(4) mode(1) HMAC-SHA1(key, bytes 0-6)[0:13]
void buildActionPacket(uint8_t out[PACKET_LEN], uint32_t ts, Mode mode, const uint8_t* key,
                       size_t keyLen);

// Parses a sign key in hex (8..32 bytes; spaces and ':' between bytes are tolerated, as keys
// are often copied from tools that group them). Returns the byte count, 0 if invalid.
size_t parseSignKey(const char* hex, uint8_t out[KEY_MAX]);

// The lock's serial number as used in its BLE name "EL_<SN>": 4..20 of [A-Za-z0-9].
bool isValidSn(const char* sn);

// Notifications: 0x09 asks for the time again; anything else answers the action.
inline bool isTimeRequest(const uint8_t* d, size_t n) { return n > 0 && d[0] == 0x09; }

}  // namespace yeelock
}  // namespace gw
