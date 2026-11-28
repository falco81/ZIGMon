// ZIGMon ESP32 Gateway - crypto primitives over mbedTLS (ESP32 only).
//
// mbedTLS 3.x (ESP-IDF 5, Arduino core 3.x) and 2.x (ESP-IDF 4.4, core 2.x) both have the
// mbedtls_md_* API used here, with the same signatures.
#if defined(ESP_PLATFORM)

#include "core_crypto.h"
#include "core_util.h"

#include <string.h>
#include "mbedtls/md.h"
#if __has_include("esp_random.h")
#  include "esp_random.h"  // IDF 5 (core 3.x)
#else
#  include "esp_system.h"  // IDF 4.4 (core 2.x): esp_fill_random() lives here
#endif

namespace gw {
namespace crypto {

static_assert(sizeof(mbedtls_md_context_t) <= 512, "HmacSha256 state too small");

static mbedtls_md_context_t* ctx(uint8_t* state) {
  return reinterpret_cast<mbedtls_md_context_t*>(state);
}

static void hmac(mbedtls_md_type_t t, const uint8_t* key, size_t keyLen, const void* msg,
                 size_t msgLen, uint8_t* out) {
  // One-shot; mbedtls_md_hmac() allocates and frees its own context.
  mbedtls_md_hmac(mbedtls_md_info_from_type(t), key, keyLen, (const unsigned char*)msg, msgLen,
                  out);
}

void sha256(const void* data, size_t len, uint8_t out[SHA256_LEN]) {
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const unsigned char*)data, len, out);
}

void hmacSha256(const uint8_t* key, size_t keyLen, const void* msg, size_t msgLen,
                uint8_t out[SHA256_LEN]) {
  hmac(MBEDTLS_MD_SHA256, key, keyLen, msg, msgLen, out);
}

void hmacSha1(const uint8_t* key, size_t keyLen, const void* msg, size_t msgLen,
              uint8_t out[SHA1_LEN]) {
  hmac(MBEDTLS_MD_SHA1, key, keyLen, msg, msgLen, out);
}

HmacSha256::HmacSha256() {
  memset(state_, 0, sizeof state_);
  mbedtls_md_init(ctx(state_));
}

HmacSha256::~HmacSha256() {
  mbedtls_md_free(ctx(state_));  // also wipes the key pads
}

void HmacSha256::begin(const uint8_t* key, size_t keyLen) {
  mbedtls_md_free(ctx(state_));
  mbedtls_md_init(ctx(state_));
  mbedtls_md_setup(ctx(state_), mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1 /* hmac */);
  mbedtls_md_hmac_starts(ctx(state_), key, keyLen);
}

void HmacSha256::update(const void* data, size_t len) {
  mbedtls_md_hmac_update(ctx(state_), (const unsigned char*)data, len);
}

void HmacSha256::finish(uint8_t out[SHA256_LEN]) { mbedtls_md_hmac_finish(ctx(state_), out); }

void HmacSha256::reset() { mbedtls_md_hmac_reset(ctx(state_)); }

void randomBytes(void* out, size_t len) { esp_fill_random(out, len); }

}  // namespace crypto
}  // namespace gw

#endif  // ESP_PLATFORM
