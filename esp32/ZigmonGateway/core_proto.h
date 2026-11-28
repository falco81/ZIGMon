// ZIGMon ESP32 Gateway - the wire protocol's crypto (contract section 2). Portable; the native
// tests assert the vectors of PROTOCOL.md section 7 against these functions.
#pragma once

#include <stdint.h>
#include <stddef.h>

#include "gw_config.h"

namespace gw {
namespace proto {

static const size_t DEVICE_KEY_LEN = 32;
static const size_t NONCE_HEX_LEN = 32;   // X-Zigmon-Nonce
static const size_t SIG_HEX_LEN = 64;     // X-Zigmon-Sig, X-Gw-Sig, pairing proof

// hex(SHA256(body)) into out[65].
void bodyHash(const void* body, size_t len, char out[65]);

// sig = hex(HMAC-SHA256(key, METHOD\nPATH\nTS\nNONCE\nhex(SHA256(body)))) into out[65].
void requestSig(const uint8_t key[DEVICE_KEY_LEN], const char* method, const char* path,
                const char* ts, const char* nonce, const void* body, size_t bodyLen,
                char out[65]);

// X-Gw-Sig = hex(HMAC-SHA256(key, "resp\n" + NONCE + "\n" + status + "\n" + hex(SHA256(body)))).
void responseSig(const uint8_t key[DEVICE_KEY_LEN], const char* nonce, int status,
                 const void* body, size_t bodyLen, char out[65]);

// proof = hex(HMAC-SHA256(code digits, "zigmon-pair-v1\n" + fingerprint + "\n" + nonce)).
void pairProof(const char* code, const char* fingerprintHex, const char* nonceHex, char out[65]);

// Constant-time check of a hex signature from the wire (either case accepted) against ours
// (lowercase). False on wrong length.
bool sigMatches(const char* theirs, const char ours[65]);

enum class Verdict : uint8_t {
  Ok,
  BadHeaders,   // missing / malformed ts, nonce or sig
  Skew,         // |ts - now| > 120 s while the clock is set
  Replay,       // nonce seen within the window, or ts below the replay floor
  BadSig,
};
const char* verdictText(Verdict v);

// Remembers nonces for GW_REPLAY_WINDOW_S (by the request's own ts, which is checked against
// the clock) in a ring of GW_REPLAY_RING entries.
//
// If the ring overflows (more than 64 requests in 5 minutes) the oldest entry is evicted and
// its ts becomes a floor: anything at or below it is refused. A replay of an evicted request
// therefore can never pass, at the cost of refusing a burst's same-second requests (ZIGMon
// retries with a fresh ts and nonce).
class ReplayRing {
 public:
  ReplayRing() { clear(); }
  void clear();
  // True (and records the nonce) if the request is fresh. nonce = 16 raw bytes.
  bool checkAndAdd(const uint8_t nonce[16], uint32_t ts);
  uint32_t floor() const { return floor_; }

 private:
  struct Entry {
    uint8_t nonce[16];
    uint32_t ts;  // 0 = empty
  };
  Entry e_[GW_REPLAY_RING];
  uint32_t floor_;
};

// The whole check for a signed request, in the order the contract states. `now` is the
// gateway's clock (Unix s). clockSet = now >= GW_CLOCK_VALID_FROM. On Ok, *tsOut holds the
// request's ts (the caller adopts it as the clock if the clock is not set).
Verdict verifyRequest(const uint8_t key[DEVICE_KEY_LEN], ReplayRing& ring, uint32_t now,
                      const char* method, const char* path, const char* tsHdr,
                      const char* nonceHdr, const char* sigHdr, const void* body, size_t bodyLen,
                      uint32_t* tsOut);

}  // namespace proto
}  // namespace gw
