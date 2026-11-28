// ZIGMon ESP32 Gateway - Yeelock notifications and the cloud request (portable, unit-tested).
//
// Notification codes and the Yeelock cloud endpoints are derived protocol knowledge from
// aso824/yeehack (Apache-2.0; see esp32/NOTICE). This is an independent C++ implementation.
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace gw {
namespace yeelock {

enum class Notif : uint8_t {
  None,
  TimeRequest,    // 0x09: set the time, then send the action again
  UnlockStart,    // 0x02
  UnlockDone,     // 0x03 UNLOCK_CMP: unlocked
  LockStart,      // 0x04
  LockDone,       // 0x05 LOCK_CMP: locked
  InvalidOpcode,  // 0x25 0x40
  SignInvalid,    // 0xFF TX_SIGN_INVALID: wrong sign key (never retried)
  Unknown,
};

Notif decodeNotif(const uint8_t* d, size_t n);
const char* notifName(Notif n);   // "UNLOCK_CMP", ...

// Folds the notifications of one action into its outcome.
struct Outcome {
  bool sawAny = false;       // any non-time notification
  bool unlocked = false;     // UNLOCK_CMP seen
  bool locked = false;       // LOCK_CMP seen
  bool signInvalid = false;  // 0xFF
  bool invalidOpcode = false;
  bool timeRequested = false;
  uint8_t unknownCount = 0;
  // Feeds one notification. Returns true when the action is finished for `mode`
  // (0 open: LOCK_CMP after UNLOCK_CMP, or an error; 1 unlock: UNLOCK_CMP; 2 lock: LOCK_CMP;
  //  3 time check: any answer).
  bool feed(Notif n, uint8_t mode);
  // Success as the contract defines it: an answer that is not 0x09 and not an error.
  bool ok() const { return sawAny && !signInvalid && !invalidOpcode; }
  // A short, user-facing message.
  const char* message(uint8_t mode) const;
};

// ---- Yeelock cloud (import locks and sign keys) ------------------------------------------------

static const char* const CLOUD_HOST = "api.yeeloc.com";
static const char* const CLOUD_TOKEN_URL = "https://api.yeeloc.com/oauth/access_token";
static const char* const CLOUD_LOCKS_URL = "https://api.yeeloc.com/lock";

// application/x-www-form-urlencoded encoding of s into out (cap bytes incl. NUL).
// Returns the length, or (size_t)-1 if it does not fit.
size_t formEncode(const char* s, char* out, size_t cap);

// The token request body: grant_type=password&client_id=..&client_secret=..&username=..
// &password=..&zone=.. Returns the length, or (size_t)-1 if it does not fit.
size_t buildTokenBody(const char* zone, const char* username, const char* password, char* out,
                      size_t cap);

// zone: country calling code digits (1-4, no '+'); username: the phone number (digits,
// 4-20) or an e-mail address. Basic checks before anything is sent.
bool validZone(const char* zone);
bool validUsername(const char* user);

}  // namespace yeelock
}  // namespace gw
