// ZIGMon ESP32 Gateway - small portable helpers.
#include "core_util.h"

#include <string.h>

namespace gw {

static const char kHex[] = "0123456789abcdef";

char* toHex(const uint8_t* in, size_t n, char* out) {
  for (size_t i = 0; i < n; i++) {
    out[2 * i] = kHex[in[i] >> 4];
    out[2 * i + 1] = kHex[in[i] & 0x0F];
  }
  out[2 * n] = 0;
  return out;
}

static int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

bool fromHex(const char* hex, size_t hexLen, uint8_t* out, size_t n) {
  if (!hex || hexLen != 2 * n) return false;
  for (size_t i = 0; i < n; i++) {
    int hi = hexVal(hex[2 * i]), lo = hexVal(hex[2 * i + 1]);
    if (hi < 0 || lo < 0) return false;
    out[i] = (uint8_t)((hi << 4) | lo);
  }
  return true;
}

bool isHex(const char* s, size_t len, bool lowerOnly) {
  if (!s) return false;
  for (size_t i = 0; i < len; i++) {
    char c = s[i];
    bool ok = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (!lowerOnly && c >= 'A' && c <= 'F');
    if (!ok) return false;
  }
  return s[len] == 0;
}

bool ctEqual(const void* a, const void* b, size_t n) {
  const volatile uint8_t* x = (const volatile uint8_t*)a;
  const volatile uint8_t* y = (const volatile uint8_t*)b;
  uint8_t d = 0;
  for (size_t i = 0; i < n; i++) d |= (uint8_t)(x[i] ^ y[i]);
  return d == 0;
}

bool ctStrEqual(const char* a, size_t alen, const char* b, size_t blen) {
  // Walk the expected length (b) every time; mismatched length still costs the same.
  uint8_t d = (uint8_t)(alen != blen);
  for (size_t i = 0; i < blen; i++) {
    uint8_t ca = (i < alen) ? (uint8_t)a[i] : 0;
    d |= (uint8_t)(ca ^ (uint8_t)b[i]);
  }
  return d == 0;
}

void secureZero(void* p, size_t n) {
  volatile uint8_t* v = (volatile uint8_t*)p;
  while (n--) *v++ = 0;
}

bool copyStr(char* dst, size_t cap, const char* src) {
  if (!cap) return false;
  if (!src) { dst[0] = 0; return true; }
  size_t n = strlen(src);
  bool fits = n < cap;
  if (!fits) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = 0;
  return fits;
}

bool isSlug(const char* s, size_t maxLen) {
  if (!s || !*s) return false;
  size_t n = strlen(s);
  if (n > maxLen) return false;
  for (size_t i = 0; i < n; i++) {
    char c = s[i];
    bool alnum = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
    if (i == 0 && !alnum) return false;
    if (!alnum && c != '_' && c != '-') return false;
  }
  return true;
}

bool isHostLabel(const char* s) {
  if (!s || !*s) return false;
  size_t n = strlen(s);
  if (n > 32 || s[0] == '-' || s[n - 1] == '-') return false;
  for (size_t i = 0; i < n; i++) {
    char c = s[i];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
  }
  return true;
}

bool isCleanText(const char* s, size_t maxBytes) {
  if (!s) return false;
  size_t n = strlen(s);
  if (n > maxBytes) return false;
  for (size_t i = 0; i < n; i++) {
    uint8_t c = (uint8_t)s[i];
    if (c < 0x20 || c == 0x7F) return false;
  }
  return true;
}

const char* maskSecret(const char* secret, char* out, size_t cap) {
  size_t n = secret ? strlen(secret) : 0;
  if (cap < 16) { if (cap) out[0] = 0; return out; }
  if (n == 0) { copyStr(out, cap, "not set"); return out; }
  if (n < 6) { copyStr(out, cap, "set"); return out; }  // too short to reveal anything
  memcpy(out, "set (..", 7);
  out[7] = secret[n - 2];
  out[8] = secret[n - 1];
  out[9] = ')';
  out[10] = 0;
  return out;
}

bool parseU32(const char* s, uint32_t* out) {
  if (!s || !*s) return false;
  uint64_t v = 0;
  for (const char* p = s; *p; p++) {
    if (*p < '0' || *p > '9') return false;
    v = v * 10 + (uint64_t)(*p - '0');
    if (v > 0xFFFFFFFFull) return false;
  }
  *out = (uint32_t)v;
  return true;
}

bool parseIPv4(const char* s, uint8_t out[4]) {
  if (!s) return false;
  int part = 0;
  uint32_t v = 0;
  int digits = 0;
  for (const char* p = s;; p++) {
    if (*p >= '0' && *p <= '9') {
      v = v * 10 + (uint32_t)(*p - '0');
      if (++digits > 3 || v > 255) return false;
    } else if (*p == '.' || *p == 0) {
      if (!digits || part > 3) return false;
      out[part++] = (uint8_t)v;
      v = 0;
      digits = 0;
      if (*p == 0) break;
    } else {
      return false;
    }
  }
  return part == 4;
}

}  // namespace gw
