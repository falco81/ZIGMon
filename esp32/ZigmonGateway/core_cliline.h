// ZIGMon ESP32 Gateway - serial line editor and tokenizer (portable, unit-tested).
//
// The editor takes raw bytes from any terminal (Arduino IDE serial monitor, PuTTY, screen,
// minicom, idf.py monitor): printable text and UTF-8, Backspace (0x08) and Delete (0x7F),
// CR, LF or CRLF to end a line, Ctrl-C / Ctrl-U to drop the line, and it silently swallows
// ANSI escape sequences (arrow keys etc.).
//
// Secret arguments are echoed as '*': a whole line in password mode, or, in normal mode, the
// arguments a SecretRule names (e.g. the password in `wifi set "My Net" hunter22`).
#pragma once

#include <stdint.h>
#include <stddef.h>

#include "gw_config.h"

namespace gw {
namespace cli {

// Splits line in place into argv. Quotes: "..." and '...'; backslash escapes the next byte
// outside single quotes (so "a \"b\"" and a\ b work). Returns argc, or
//   -1 unterminated quote, -2 too many arguments.
// offsets (optional) receives each argument's start offset in the ORIGINAL line.
int tokenize(char* line, char** argv, int maxArgs, size_t* offsets = nullptr);

// "wifi set <ssid> <password>": first = {"wifi","set"}, secretArg = 3 (0-based argv index).
struct SecretRule {
  const char* w0;
  const char* w1;     // nullptr = any
  int secretArg;      // this argv index and all after it are secret
};

// Byte offset in `line` from which echo must be masked, or (size_t)-1. Tolerates a partial
// line (an unterminated quote is fine), which is what the editor has while typing.
size_t secretFrom(const char* line, size_t len, const SecretRule* rules, size_t nRules);

class LineEditor {
 public:
  typedef void (*WriteFn)(const char* s, size_t n, void* ctx);

  LineEditor()
      : doneLen_(0), password_(false), echo_(true), rules_(nullptr), nRules_(0),
        out_(nullptr), outCtx_(nullptr) {
    done_[0] = 0;
    reset();
  }
  void setOutput(WriteFn fn, void* ctx) { out_ = fn; outCtx_ = ctx; }
  void setRules(const SecretRule* r, size_t n) { rules_ = r; nRules_ = n; }
  void setPasswordMode(bool on) { password_ = on; }
  bool passwordMode() const { return password_; }
  void setEcho(bool on) { echo_ = on; }

  // Feeds one byte. Returns true when a line is complete; read it with line(), then the
  // editor is ready for the next one (the buffer stays valid until the next feed()).
  bool feed(uint8_t c);
  const char* line() const { return done_; }
  size_t length() const { return doneLen_; }
  bool overflowed() const { return overflow_; }
  void reset();
  void wipe();   // reset and zero the buffers (after a password)
  // Writes prompt + the line typed so far, masked exactly like the live echo (used to
  // restore the prompt after a log line interrupted it).
  void redraw(const char* prompt);

 private:
  void write(const char* s, size_t n) { if (out_ && echo_) out_(s, n, outCtx_); }
  bool masked(size_t at) const;

  char buf_[GW_CLI_LINE_MAX + 1];
  char done_[GW_CLI_LINE_MAX + 1];
  size_t len_, doneLen_;
  uint8_t esc_;          // 0 none, 1 after ESC, 2 in CSI, 3 after ESC O
  bool lastCR_, overflow_, password_, echo_;
  const SecretRule* rules_;
  size_t nRules_;
  WriteFn out_;
  void* outCtx_;
};

}  // namespace cli
}  // namespace gw
