// ZIGMon ESP32 Gateway - small portable helpers (no Arduino dependency; unit-tested natively).
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace gw {

// Lowercase hex of n bytes into out (needs 2n+1 bytes). Returns out.
char* toHex(const uint8_t* in, size_t n, char* out);

// Parses exactly 2*n hex digits (either case) into n bytes. False on any bad digit or length.
bool fromHex(const char* hex, size_t hexLen, uint8_t* out, size_t n);

// True if s is exactly len characters of hex (either case). lower=true: lowercase only.
bool isHex(const char* s, size_t len, bool lowerOnly = false);

// Constant-time equality of two buffers of the same length.
bool ctEqual(const void* a, const void* b, size_t n);

// Constant-time compare of two strings: true only if both lengths and bytes match.
// The time depends on the lengths only, never on where they differ.
bool ctStrEqual(const char* a, size_t alen, const char* b, size_t blen);

// Wipes memory in a way the optimizer may not remove.
void secureZero(void* p, size_t n);

// Copies at most cap-1 bytes and terminates. Returns false if it had to truncate.
bool copyStr(char* dst, size_t cap, const char* src);

// An identifier for entities, lock ids, hostnames: [a-z0-9_-], 1..maxLen, starts alnum.
bool isSlug(const char* s, size_t maxLen);

// RFC 1123 host label: [a-z0-9-], 1..32, not starting or ending with '-'.
bool isHostLabel(const char* s);

// Printable UTF-8 text without control characters, at most maxBytes bytes.
bool isCleanText(const char* s, size_t maxBytes);

// "set (..ab)" style mask of a secret: shows the last 2 characters only, never more.
// out needs 16 bytes. Empty secret -> "not set".
const char* maskSecret(const char* secret, char* out, size_t cap);

// Parses a dotted IPv4 address. False on anything else.
bool parseIPv4(const char* s, uint8_t out[4]);

// Parses an unsigned decimal (no sign, no spaces). False on overflow or junk.
bool parseU32(const char* s, uint32_t* out);

}  // namespace gw
