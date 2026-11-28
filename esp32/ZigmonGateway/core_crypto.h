// ZIGMon ESP32 Gateway - crypto primitives.
//
// The primitives (SHA-256, HMAC-SHA256/SHA1, random) are implemented over mbedTLS and the
// hardware RNG in core_crypto.cpp. The native unit tests link a vendored public-domain
// implementation instead (esp32/tests/shim_crypto.cpp), so everything built on top of these
// (PBKDF2, request signatures, pairing proofs, Yeelock packets) is tested off-device.
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace gw {
namespace crypto {

static const size_t SHA256_LEN = 32;
static const size_t SHA1_LEN = 20;

void sha256(const void* data, size_t len, uint8_t out[SHA256_LEN]);

void hmacSha256(const uint8_t* key, size_t keyLen, const void* msg, size_t msgLen,
                uint8_t out[SHA256_LEN]);

void hmacSha1(const uint8_t* key, size_t keyLen, const void* msg, size_t msgLen,
              uint8_t out[SHA1_LEN]);

// Incremental HMAC-SHA256 (used to sign "a\nb\nc" strings without building them).
class HmacSha256 {
 public:
  HmacSha256();
  ~HmacSha256();
  void begin(const uint8_t* key, size_t keyLen);
  void update(const void* data, size_t len);
  void update(const char* s);
  void finish(uint8_t out[SHA256_LEN]);
  // Same key, new message (cheaper than begin(): used 10000x by PBKDF2).
  void reset();

 private:
  HmacSha256(const HmacSha256&);
  HmacSha256& operator=(const HmacSha256&);
  alignas(8) uint8_t state_[512];  // backend context (mbedtls_md_context_t or the shim's)
};

// Cryptographically secure random bytes (ESP32: hardware RNG; RF is on, so it is true random).
void randomBytes(void* out, size_t len);

// Uniform random number in [0, bound) without modulo bias.
uint32_t randomBelow(uint32_t bound);

// Fills out with 2*nBytes lowercase hex characters of random data, NUL-terminated.
void randomHex(char* out, size_t nBytes);

// PBKDF2-HMAC-SHA256 (RFC 8018), portable on top of HmacSha256. dkLen <= 64.
void pbkdf2Sha256(const uint8_t* pw, size_t pwLen, const uint8_t* salt, size_t saltLen,
                  uint32_t rounds, uint8_t* dk, size_t dkLen);

}  // namespace crypto
}  // namespace gw
