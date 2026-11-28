// ZIGMon ESP32 Gateway - web UI authentication.
#include "core_auth.h"

#include "core_authlogic.h"
#include "core_config.h"
#include "core_crypto.h"
#include "core_log.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace auth {

static SessionTable g_sessions;
static LoginThrottle g_throttle;
static uint32_t g_firstRunUntil = 0;

void begin() { g_firstRunUntil = monoS() + GW_FIRSTRUN_WINDOW_S; }

bool passwordSet() { return config::hasPassword(); }

bool firstRunOpen() { return !passwordSet() && monoS() < g_firstRunUntil; }
uint32_t firstRunLeft() { return firstRunOpen() ? g_firstRunUntil - monoS() : 0; }

void openFirstRun() {
  g_firstRunUntil = monoS() + GW_FIRSTRUN_WINDOW_S;
  LOGI("auth", "first-run page open for 10 minutes");
}

static bool validPassword(const char* pw, String& err) {
  size_t n = pw ? strlen(pw) : 0;
  if (n < GW_PASSWORD_MIN) { err = "the password needs at least 8 characters"; return false; }
  if (n > GW_PASSWORD_MAX) { err = "the password may have at most 64 characters"; return false; }
  if (!isCleanText(pw, GW_PASSWORD_MAX)) { err = "control characters are not allowed"; return false; }
  return true;
}

bool setPassword(const char* pw, String& err) {
  if (!validPassword(pw, err)) return false;
  uint8_t salt[GW_PBKDF2_SALT], dk[32];
  crypto::randomBytes(salt, sizeof salt);
  crypto::pbkdf2Sha256((const uint8_t*)pw, strlen(pw), salt, sizeof salt, GW_PBKDF2_ROUNDS, dk, 32);
  bool ok = config::setPassword(salt, dk, GW_PBKDF2_ROUNDS);
  secureZero(dk, sizeof dk);
  if (!ok) { err = "could not save to NVS"; return false; }
  g_sessions.clear();
  g_throttle.reset();
  g_firstRunUntil = 0;
  LOGI("auth", "admin password changed; all sessions logged out");
  return true;
}

bool checkPassword(const char* pw) {
  if (!pw || !passwordSet()) return false;
  uint8_t salt[16], want[32], got[32];
  uint32_t rounds = GW_PBKDF2_ROUNDS;
  if (!config::getPassword(salt, want, &rounds)) return false;
  if (rounds < 1000 || rounds > 1000000) rounds = GW_PBKDF2_ROUNDS;
  size_t n = strlen(pw);
  if (n > GW_PASSWORD_MAX) n = GW_PASSWORD_MAX;  // the derivation still runs: same timing
  crypto::pbkdf2Sha256((const uint8_t*)pw, n, salt, 16, rounds, got, 32);
  bool ok = ctEqual(got, want, 32);
  secureZero(got, sizeof got);
  secureZero(want, sizeof want);
  return ok;
}

Login login(const char* pw, char token[33], char csrfOut[33], uint32_t* waitS) {
  uint32_t now = monoS();
  *waitS = g_throttle.waitLeft(now);
  if (!passwordSet()) return Login::NoPassword;
  if (*waitS) return Login::Locked;
  if (!checkPassword(pw)) {
    g_throttle.failed(now);
    *waitS = g_throttle.waitLeft(now);
    LOGW("auth", "failed login (%lu in a row)", (unsigned long)g_throttle.fails());
    return Login::Bad;
  }
  g_throttle.succeeded();
  g_sessions.create(now, token, csrfOut);
  LOGI("auth", "web login");
  return Login::Ok;
}

void newSession(char token[33], char csrfOut[33]) { g_sessions.create(monoS(), token, csrfOut); }

int session(const char* token) { return g_sessions.find(token, monoS()); }
bool csrfOk(int slot, const char* header) { return g_sessions.csrfOk(slot, header); }
const char* csrf(int slot) { return g_sessions.csrf(slot); }
void logout(int slot) { g_sessions.remove(slot); }
void logoutAll() { g_sessions.clear(); }
uint32_t lockoutLeft() { return g_throttle.waitLeft(monoS()); }

String cookieFor(const char* token) {
  String c = "gws=";
  c += token;
  c += "; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=";
  c += String((unsigned long)GW_SESSION_TTL_S);
  return c;
}

String cookieClear() { return String("gws=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"); }

void tokenFromCookie(const char* hdr, char token[33]) {
  token[0] = 0;
  if (!hdr) return;
  const char* p = hdr;
  while (*p) {
    while (*p == ' ' || *p == ';') p++;
    if (strncmp(p, "gws=", 4) == 0) {
      p += 4;
      size_t n = 0;
      while (p[n] && p[n] != ';' && p[n] != ' ') n++;
      if (n == 32) {
        memcpy(token, p, 32);
        token[32] = 0;
        if (!isHex(token, 32, true)) token[0] = 0;
      }
      return;
    }
    while (*p && *p != ';') p++;
  }
}

}  // namespace auth
}  // namespace gw
