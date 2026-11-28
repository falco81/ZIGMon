// ZIGMon ESP32 Gateway - web UI authentication: the admin password, sessions, CSRF, lockout,
// and the first-run window (contract section 2).
#pragma once

#include <Arduino.h>

namespace gw {
namespace auth {

void begin();

bool passwordSet();
// The first-run page (set the password) is reachable: no password yet, and within 10 min
// of boot or of the CLI `webinit`.
bool firstRunOpen();
uint32_t firstRunLeft();
void openFirstRun();   // CLI `webinit`

// Validates (length 8..64, printable) and stores PBKDF2(password); logs every session out.
bool setPassword(const char* pw, String& err);
bool checkPassword(const char* pw);   // constant-time compare of the derived key

enum class Login : uint8_t { Ok, Bad, Locked, NoPassword };
// On Ok writes the session cookie token and CSRF token (32 hex each).
Login login(const char* pw, char token[33], char csrf[33], uint32_t* waitS);
// Creates a session without a password check (right after first-run setup).
void newSession(char token[33], char csrf[33]);

int session(const char* token);           // slot, or -1
bool csrfOk(int slot, const char* header);
const char* csrf(int slot);
void logout(int slot);
void logoutAll();
uint32_t lockoutLeft();

// "gws=<token>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200"
String cookieFor(const char* token);
String cookieClear();
// Extracts our token from a Cookie header ("" if absent).
void tokenFromCookie(const char* cookieHdr, char token[33]);

}  // namespace auth
}  // namespace gw
