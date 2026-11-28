// ZIGMon ESP32 Gateway - crypto built on the primitives (portable; tested natively).
#include "core_crypto.h"
#include "core_util.h"

#include <string.h>

namespace gw {
namespace crypto {

void HmacSha256::update(const char* s) { update(s, strlen(s)); }

uint32_t randomBelow(uint32_t bound) {
  if (bound < 2) return 0;
  // Reject the top partial range so every value is equally likely.
  uint32_t limit = 0xFFFFFFFFu - (0xFFFFFFFFu % bound);
  for (;;) {
    uint32_t v;
    randomBytes(&v, sizeof v);
    if (v < limit) return v % bound;
  }
}

void randomHex(char* out, size_t nBytes) {
  uint8_t buf[32];
  size_t done = 0;
  while (done < nBytes) {
    size_t n = nBytes - done;
    if (n > sizeof buf) n = sizeof buf;
    randomBytes(buf, n);
    toHex(buf, n, out + 2 * done);
    done += n;
  }
  out[2 * nBytes] = 0;
  secureZero(buf, sizeof buf);
}

void pbkdf2Sha256(const uint8_t* pw, size_t pwLen, const uint8_t* salt, size_t saltLen,
                  uint32_t rounds, uint8_t* dk, size_t dkLen) {
  HmacSha256 h;
  h.begin(pw, pwLen);
  uint8_t u[SHA256_LEN], t[SHA256_LEN];
  uint32_t block = 1;
  size_t done = 0;
  while (done < dkLen) {
    uint8_t ctr[4] = {(uint8_t)(block >> 24), (uint8_t)(block >> 16), (uint8_t)(block >> 8),
                      (uint8_t)block};
    h.reset();
    h.update(salt, saltLen);
    h.update(ctr, 4);
    h.finish(u);
    memcpy(t, u, SHA256_LEN);
    for (uint32_t i = 1; i < rounds; i++) {
      h.reset();
      h.update(u, SHA256_LEN);
      h.finish(u);
      for (size_t k = 0; k < SHA256_LEN; k++) t[k] ^= u[k];
    }
    size_t n = dkLen - done;
    if (n > SHA256_LEN) n = SHA256_LEN;
    memcpy(dk + done, t, n);
    done += n;
    block++;
  }
  secureZero(u, sizeof u);
  secureZero(t, sizeof t);
}

}  // namespace crypto
}  // namespace gw
