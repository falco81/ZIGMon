// ZIGMon ESP32 Gateway - the wire protocol's crypto (portable).
#include "core_proto.h"

#include <stdio.h>
#include <string.h>

#include "core_crypto.h"
#include "core_util.h"

namespace gw {
namespace proto {

using crypto::HmacSha256;
using crypto::SHA256_LEN;

void bodyHash(const void* body, size_t len, char out[65]) {
  uint8_t h[SHA256_LEN];
  crypto::sha256(body ? body : "", body ? len : 0, h);
  toHex(h, SHA256_LEN, out);
}

void requestSig(const uint8_t key[DEVICE_KEY_LEN], const char* method, const char* path,
                const char* ts, const char* nonce, const void* body, size_t bodyLen,
                char out[65]) {
  char bh[65];
  bodyHash(body, bodyLen, bh);
  HmacSha256 h;
  h.begin(key, DEVICE_KEY_LEN);
  h.update(method);
  h.update("\n", 1);
  h.update(path);
  h.update("\n", 1);
  h.update(ts);
  h.update("\n", 1);
  h.update(nonce);
  h.update("\n", 1);
  h.update(bh, 64);
  uint8_t mac[SHA256_LEN];
  h.finish(mac);
  toHex(mac, SHA256_LEN, out);
}

void responseSig(const uint8_t key[DEVICE_KEY_LEN], const char* nonce, int status,
                 const void* body, size_t bodyLen, char out[65]) {
  char bh[65], st[12];
  bodyHash(body, bodyLen, bh);
  snprintf(st, sizeof st, "%d", status);
  HmacSha256 h;
  h.begin(key, DEVICE_KEY_LEN);
  h.update("resp\n", 5);
  h.update(nonce);
  h.update("\n", 1);
  h.update(st);
  h.update("\n", 1);
  h.update(bh, 64);
  uint8_t mac[SHA256_LEN];
  h.finish(mac);
  toHex(mac, SHA256_LEN, out);
}

void pairProof(const char* code, const char* fingerprintHex, const char* nonceHex, char out[65]) {
  HmacSha256 h;
  h.begin((const uint8_t*)code, strlen(code));
  h.update("zigmon-pair-v1\n", 15);
  h.update(fingerprintHex);
  h.update("\n", 1);
  h.update(nonceHex);
  uint8_t mac[SHA256_LEN];
  h.finish(mac);
  toHex(mac, SHA256_LEN, out);
}

bool sigMatches(const char* theirs, const char ours[65]) {
  if (!theirs || strlen(theirs) != SIG_HEX_LEN) return false;
  char low[65];
  for (size_t i = 0; i < SIG_HEX_LEN; i++) {
    char c = theirs[i];
    low[i] = (c >= 'A' && c <= 'F') ? (char)(c - 'A' + 'a') : c;
  }
  low[64] = 0;
  return ctEqual(low, ours, SIG_HEX_LEN);
}

const char* verdictText(Verdict v) {
  switch (v) {
    case Verdict::Ok: return "ok";
    case Verdict::BadHeaders: return "missing or malformed signature headers";
    case Verdict::Skew: return "clock skew";
    case Verdict::Replay: return "replayed nonce";
    case Verdict::BadSig: return "bad signature";
  }
  return "?";
}

void ReplayRing::clear() {
  memset(e_, 0, sizeof e_);
  floor_ = 0;
}

bool ReplayRing::checkAndAdd(const uint8_t nonce[16], uint32_t ts) {
  if (ts <= floor_) return false;
  int freeSlot = -1, oldest = -1;
  for (int i = 0; i < GW_REPLAY_RING; i++) {
    Entry& x = e_[i];
    if (x.ts == 0) { if (freeSlot < 0) freeSlot = i; continue; }
    // Expired entries (by request time) can never match again: the skew check refuses them.
    bool expired = (uint64_t)x.ts + GW_REPLAY_WINDOW_S < (uint64_t)ts;
    if (expired) { x.ts = 0; if (freeSlot < 0) freeSlot = i; continue; }
    if (memcmp(x.nonce, nonce, 16) == 0) return false;
    if (oldest < 0 || x.ts < e_[oldest].ts) oldest = i;
  }
  int slot = freeSlot;
  if (slot < 0) {  // full of live entries: evict the oldest, raise the floor past it
    slot = oldest;
    if (e_[slot].ts > floor_) floor_ = e_[slot].ts;
    if (ts <= floor_) return false;
  }
  memcpy(e_[slot].nonce, nonce, 16);
  e_[slot].ts = ts;
  return true;
}

Verdict verifyRequest(const uint8_t key[DEVICE_KEY_LEN], ReplayRing& ring, uint32_t now,
                      const char* method, const char* path, const char* tsHdr,
                      const char* nonceHdr, const char* sigHdr, const void* body, size_t bodyLen,
                      uint32_t* tsOut) {
  uint32_t ts;
  if (!tsHdr || !parseU32(tsHdr, &ts) || ts == 0 || strlen(tsHdr) > 10) return Verdict::BadHeaders;
  uint8_t nonce[16];
  if (!nonceHdr || !fromHex(nonceHdr, strlen(nonceHdr), nonce, 16)) return Verdict::BadHeaders;
  if (!sigHdr || strlen(sigHdr) != SIG_HEX_LEN) return Verdict::BadHeaders;

  bool clockSet = now >= GW_CLOCK_VALID_FROM;
  if (clockSet) {
    int64_t d = (int64_t)ts - (int64_t)now;
    if (d > GW_MAX_TS_SKEW_S || d < -GW_MAX_TS_SKEW_S) return Verdict::Skew;
  }

  // The signature is checked before the nonce is recorded, so an unauthenticated sender
  // can't flood the ring and push genuine nonces (or the floor) around.
  char ours[65];
  requestSig(key, method, path, tsHdr, nonceHdr, body, bodyLen, ours);
  if (!sigMatches(sigHdr, ours)) return Verdict::BadSig;

  if (!ring.checkAndAdd(nonce, ts)) return Verdict::Replay;
  if (tsOut) *tsOut = ts;
  return Verdict::Ok;
}

}  // namespace proto
}  // namespace gw
