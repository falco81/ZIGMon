// Native test shim: the crypto primitives of core_crypto.h over tests/vendor/mini_sha.h.
#include "../ZigmonGateway/core_crypto.h"

#include <stdio.h>
#include <stdlib.h>
#include <new>

#include "vendor/mini_sha.h"

namespace gw {
namespace crypto {

typedef mini::Hmac<mini::Sha256, 32> H256;
typedef mini::Hmac<mini::Sha1, 20> H1;
static_assert(sizeof(H256) <= 512, "shim state too big");

void sha256(const void* data, size_t len, uint8_t out[SHA256_LEN]) {
  mini::Sha256 s;
  s.init();
  s.update(data, len);
  s.final(out);
}

void hmacSha256(const uint8_t* key, size_t keyLen, const void* msg, size_t msgLen,
                uint8_t out[SHA256_LEN]) {
  H256 h;
  h.begin(key, keyLen);
  h.update(msg, msgLen);
  h.final(out);
}

void hmacSha1(const uint8_t* key, size_t keyLen, const void* msg, size_t msgLen,
              uint8_t out[SHA1_LEN]) {
  H1 h;
  h.begin(key, keyLen);
  h.update(msg, msgLen);
  h.final(out);
}

HmacSha256::HmacSha256() { new (state_) H256(); }
HmacSha256::~HmacSha256() {}
void HmacSha256::begin(const uint8_t* key, size_t keyLen) { ((H256*)state_)->begin(key, keyLen); }
void HmacSha256::update(const void* d, size_t n) { ((H256*)state_)->update(d, n); }
void HmacSha256::finish(uint8_t out[SHA256_LEN]) { ((H256*)state_)->final(out); }
void HmacSha256::reset() { ((H256*)state_)->reset(); }

void randomBytes(void* out, size_t len) {
  FILE* f = fopen("/dev/urandom", "rb");
  if (!f || fread(out, 1, len, f) != len) abort();
  fclose(f);
}

}  // namespace crypto
}  // namespace gw
