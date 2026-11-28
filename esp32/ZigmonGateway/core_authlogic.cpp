// ZIGMon ESP32 Gateway - the policy parts of Auth and Pairing (portable).
#include "core_authlogic.h"

#include <stdio.h>
#include <string.h>

#include "core_crypto.h"
#include "core_proto.h"
#include "core_util.h"

namespace gw {

// ---- SessionTable ---------------------------------------------------------------------------

void SessionTable::clear() { secureZero(s_, sizeof s_); }

void SessionTable::create(uint32_t now, char token[TOKEN_HEX + 1], char csrf[TOKEN_HEX + 1]) {
  int slot = -1;
  for (int i = 0; i < GW_MAX_SESSIONS; i++) {
    if (s_[i].created == 0 || now - s_[i].created >= GW_SESSION_TTL_S) { slot = i; break; }
  }
  if (slot < 0) {  // all live: evict the oldest
    slot = 0;
    for (int i = 1; i < GW_MAX_SESSIONS; i++)
      if (s_[i].created < s_[slot].created) slot = i;
  }
  crypto::randomHex(s_[slot].token, 16);
  crypto::randomHex(s_[slot].csrf, 16);
  s_[slot].created = now ? now : 1;
  memcpy(token, s_[slot].token, TOKEN_HEX + 1);
  memcpy(csrf, s_[slot].csrf, TOKEN_HEX + 1);
}

int SessionTable::find(const char* token, uint32_t now) {
  if (!token || strlen(token) != TOKEN_HEX) return -1;
  int found = -1;
  for (int i = 0; i < GW_MAX_SESSIONS; i++) {
    bool live = s_[i].created != 0 && now - s_[i].created < GW_SESSION_TTL_S;
    bool eq = ctEqual(s_[i].token, token, TOKEN_HEX);  // always compared: constant time
    if (live && eq) found = i;
    if (s_[i].created != 0 && !live) secureZero(&s_[i], sizeof s_[i]);  // expired
  }
  return found;
}

bool SessionTable::csrfOk(int slot, const char* hdr) const {
  if (slot < 0 || slot >= GW_MAX_SESSIONS || !hdr) return false;
  return ctStrEqual(hdr, strlen(hdr), s_[slot].csrf, TOKEN_HEX);
}

void SessionTable::remove(int slot) {
  if (slot >= 0 && slot < GW_MAX_SESSIONS) secureZero(&s_[slot], sizeof s_[slot]);
}

int SessionTable::count(uint32_t now) {
  int n = 0;
  for (int i = 0; i < GW_MAX_SESSIONS; i++)
    if (s_[i].created != 0 && now - s_[i].created < GW_SESSION_TTL_S) n++;
  return n;
}

// ---- LoginThrottle --------------------------------------------------------------------------

void LoginThrottle::failed(uint32_t now) {
  fails_++;
  if (fails_ < GW_LOGIN_FREE_FAILS) return;
  // The 5th failure locks for 60 s; each failure after a lock doubles it, up to 1 h.
  lockS_ = lockS_ == 0 ? GW_LOGIN_LOCK_BASE_S : lockS_ * 2;
  if (lockS_ > GW_LOGIN_LOCK_MAX_S) lockS_ = GW_LOGIN_LOCK_MAX_S;
  lockedUntil_ = now + lockS_;
}

// ---- PairGate -------------------------------------------------------------------------------

void PairGate::clear() {
  secureZero(code_, sizeof code_);
  expires_ = lockedUntil_ = fails_ = 0;
}

bool PairGate::start(uint32_t now, uint32_t random6) {
  if (lockedFor(now)) return false;
  snprintf(code_, sizeof code_, "%06u", (unsigned)(random6 % 1000000u));
  expires_ = now + GW_PAIR_CODE_TTL_S;
  return true;
}

PairGate::Result PairGate::attempt(const char* proofHex, const char* fingerprintHex,
                                   const char* nonceHex, uint32_t now) {
  if (lockedFor(now)) return LOCKED;
  if (!code_[0]) return NO_CODE;
  bool expired = now >= expires_;
  char ours[65];
  proto::pairProof(code_, fingerprintHex, nonceHex, ours);
  secureZero(code_, sizeof code_);  // spent, whatever happens next
  expires_ = 0;
  if (expired) return EXPIRED;
  if (!proto::sigMatches(proofHex, ours)) {
    if (++fails_ >= GW_PAIR_MAX_FAILS) {
      lockedUntil_ = now + GW_PAIR_LOCK_S;
      fails_ = 0;
    }
    return BAD_PROOF;
  }
  fails_ = 0;
  return OK;
}

}  // namespace gw
