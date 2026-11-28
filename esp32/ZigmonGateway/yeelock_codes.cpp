// ZIGMon ESP32 Gateway - Yeelock notifications and the cloud request (portable).
#include "yeelock_codes.h"

#include <string.h>

namespace gw {
namespace yeelock {

// The Yeelock app's public OAuth client (as used by aso824/yeehack's fetch.py).
static const char* const CLIENT_ID = "yeeloc";
static const char* const CLIENT_SECRET = "adb03414981961952ccf40a1b4031d12";

Notif decodeNotif(const uint8_t* d, size_t n) {
  if (!d || !n) return Notif::None;
  switch (d[0]) {
    case 0x09: return Notif::TimeRequest;
    case 0x02: return Notif::UnlockStart;
    case 0x03: return Notif::UnlockDone;
    case 0x04: return Notif::LockStart;
    case 0x05: return Notif::LockDone;
    case 0xFF: return Notif::SignInvalid;
    case 0x25: return (n >= 2 && d[1] == 0x40) ? Notif::InvalidOpcode : Notif::Unknown;
    default: return Notif::Unknown;
  }
}

const char* notifName(Notif n) {
  switch (n) {
    case Notif::None: return "NONE";
    case Notif::TimeRequest: return "TIME_SYNC_REQ";
    case Notif::UnlockStart: return "UNLOCK_START";
    case Notif::UnlockDone: return "UNLOCK_CMP";
    case Notif::LockStart: return "LOCK_START";
    case Notif::LockDone: return "LOCK_CMP";
    case Notif::InvalidOpcode: return "INVALID_OPCODE";
    case Notif::SignInvalid: return "TX_SIGN_INVALID";
    case Notif::Unknown: return "UNKNOWN";
  }
  return "?";
}

bool Outcome::feed(Notif n, uint8_t mode) {
  switch (n) {
    case Notif::None: return false;
    case Notif::TimeRequest: timeRequested = true; return false;
    case Notif::SignInvalid: signInvalid = true; sawAny = true; return true;
    case Notif::InvalidOpcode: invalidOpcode = true; sawAny = true; return true;
    case Notif::UnlockStart:
    case Notif::LockStart: sawAny = true; return mode == 3;
    case Notif::UnlockDone: sawAny = true; unlocked = true; return mode == 1 || mode == 3;
    case Notif::LockDone:
      sawAny = true;
      locked = true;
      return mode != 1;  // lock done; open (temp unlock) ends with LOCK_CMP too
    case Notif::Unknown: sawAny = true; if (unknownCount < 255) unknownCount++; return mode == 3;
  }
  return false;
}

const char* Outcome::message(uint8_t mode) const {
  if (signInvalid) return "wrong sign key: the lock answered TX_SIGN_INVALID";
  if (invalidOpcode) return "the lock rejected the command (INVALID_OPCODE)";
  if (!sawAny) return timeRequested ? "the lock kept asking for the time (wrong sign key?)"
                                    : "no answer from the lock";
  switch (mode) {
    case 0: return locked ? "opened, locked again" : unlocked ? "opened (re-lock not reported yet)" : "accepted";
    case 1: return unlocked ? "unlocked" : "accepted (unlock not confirmed)";
    case 2: return locked ? "locked" : "accepted (lock not confirmed)";
    default: return "reachable, key OK";
  }
}

size_t formEncode(const char* s, char* out, size_t cap) {
  static const char hex[] = "0123456789ABCDEF";
  size_t n = 0;
  for (const unsigned char* p = (const unsigned char*)s; *p; p++) {
    unsigned char c = *p;
    bool plain = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                 c == '-' || c == '_' || c == '.' || c == '*';
    if (plain) {
      if (n + 1 >= cap) return (size_t)-1;
      out[n++] = (char)c;
    } else if (c == ' ') {
      if (n + 1 >= cap) return (size_t)-1;
      out[n++] = '+';
    } else {
      if (n + 3 >= cap) return (size_t)-1;
      out[n++] = '%';
      out[n++] = hex[c >> 4];
      out[n++] = hex[c & 15];
    }
  }
  if (n >= cap) return (size_t)-1;
  out[n] = 0;
  return n;
}

static bool append(char* out, size_t cap, size_t* n, const char* key, const char* value) {
  size_t kl = strlen(key);
  if (*n + kl + 2 >= cap) return false;
  if (*n) out[(*n)++] = '&';
  memcpy(out + *n, key, kl);
  *n += kl;
  out[(*n)++] = '=';
  size_t v = formEncode(value, out + *n, cap - *n);
  if (v == (size_t)-1) return false;
  *n += v;
  return true;
}

size_t buildTokenBody(const char* zone, const char* username, const char* password, char* out,
                      size_t cap) {
  size_t n = 0;
  if (!cap) return (size_t)-1;
  out[0] = 0;
  bool ok = append(out, cap, &n, "grant_type", "password") && append(out, cap, &n, "client_id", CLIENT_ID) &&
            append(out, cap, &n, "client_secret", CLIENT_SECRET) &&
            append(out, cap, &n, "username", username) && append(out, cap, &n, "password", password) &&
            append(out, cap, &n, "zone", zone);
  if (!ok) {
    memset(out, 0, cap);  // it may hold part of the password
    return (size_t)-1;
  }
  return n;
}

bool validZone(const char* z) {
  size_t n = z ? strlen(z) : 0;
  if (n < 1 || n > 4) return false;
  for (size_t i = 0; i < n; i++)
    if (z[i] < '0' || z[i] > '9') return false;
  return true;
}

bool validUsername(const char* u) {
  size_t n = u ? strlen(u) : 0;
  if (n < 4 || n > 64) return false;
  for (size_t i = 0; i < n; i++)
    if ((unsigned char)u[i] <= 0x20 || (unsigned char)u[i] == 0x7F) return false;
  return true;
}

}  // namespace yeelock
}  // namespace gw
