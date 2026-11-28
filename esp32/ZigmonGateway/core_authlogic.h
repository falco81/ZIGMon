// ZIGMon ESP32 Gateway - the policy parts of Auth and Pairing (portable, unit-tested).
//
// Time is injected (monotonic seconds since boot), so the rules are testable off-device and
// don't depend on the wall clock, which may not be set.
#pragma once

#include <stdint.h>
#include <stddef.h>

#include "gw_config.h"

namespace gw {

// ---- Web sessions: 4 slots, 128-bit token, own CSRF token, 12 h expiry --------------------
class SessionTable {
 public:
  static const size_t TOKEN_HEX = 32;  // 128 bits
  SessionTable() { clear(); }
  void clear();
  // New session; evicts the oldest if all slots are taken. Writes 32-hex token and csrf.
  void create(uint32_t now, char token[TOKEN_HEX + 1], char csrf[TOKEN_HEX + 1]);
  // Slot index of a live session with this token, or -1. Constant time over all slots.
  int find(const char* token, uint32_t now);
  bool csrfOk(int slot, const char* hdr) const;
  const char* csrf(int slot) const { return s_[slot].csrf; }
  void remove(int slot);
  int count(uint32_t now);

 private:
  struct Slot {
    char token[TOKEN_HEX + 1];
    char csrf[TOKEN_HEX + 1];
    uint32_t created;  // 0 = free
  };
  Slot s_[GW_MAX_SESSIONS];
};

// ---- Login brute-force throttle: 5 free failures, then 60 s, doubling up to 1 h ---------
class LoginThrottle {
 public:
  LoginThrottle() { reset(); }
  void reset() { fails_ = 0; lockedUntil_ = 0; lockS_ = 0; }
  // 0 if a login may be tried now, else the seconds left to wait.
  uint32_t waitLeft(uint32_t now) const { return now < lockedUntil_ ? lockedUntil_ - now : 0; }
  void failed(uint32_t now);
  void succeeded() { reset(); }
  uint32_t fails() const { return fails_; }

 private:
  uint32_t fails_, lockedUntil_, lockS_;
};

// ---- Pairing: 6-digit code, 10 min, single use; 5 wrong proofs lock 15 min --------------
class PairGate {
 public:
  enum Result : uint8_t { OK, NO_CODE, EXPIRED, LOCKED, BAD_PROOF };
  PairGate() { clear(); }
  void clear();
  // Starts a new code (digits from `random6`, which the caller draws from the RNG).
  // Fails (returns false) while locked.
  bool start(uint32_t now, uint32_t random6);
  const char* code() const { return code_; }
  bool active(uint32_t now) const { return code_[0] && now < expires_; }
  uint32_t expiresIn(uint32_t now) const { return active(now) ? expires_ - now : 0; }
  uint32_t lockedFor(uint32_t now) const { return now < lockedUntil_ ? lockedUntil_ - now : 0; }
  // Checks a proof. The code is spent whatever the outcome.
  Result attempt(const char* proofHex, const char* fingerprintHex, const char* nonceHex,
                 uint32_t now);

 private:
  char code_[7];
  uint32_t expires_, lockedUntil_, fails_;
};

}  // namespace gw
