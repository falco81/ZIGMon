// ZIGMon ESP32 Gateway - serial line editor and tokenizer (portable).
#include "core_cliline.h"

#include <string.h>

#include "core_util.h"

namespace gw {
namespace cli {

static bool isSpace(char c) { return c == ' ' || c == '\t'; }

// Core tokenizer. partial=true: an unterminated quote ends the last token instead of failing.
static int tokenizeImpl(char* line, char** argv, int maxArgs, size_t* offsets, bool partial) {
  char* r = line;  // read
  char* w = line;  // write (never ahead of r: unquoting only shrinks)
  int argc = 0;
  for (;;) {
    while (isSpace(*r)) r++;
    if (!*r) break;
    if (argc >= maxArgs) return -2;
    if (offsets) offsets[argc] = (size_t)(r - line);
    argv[argc++] = w;
    char quote = 0;
    bool atEnd = false;
    for (;;) {
      char c = *r;
      if (!c) {
        if (quote && !partial) return -1;
        atEnd = true;
        break;
      }
      r++;
      if (quote == '\'') {
        if (c == '\'') quote = 0; else *w++ = c;
      } else if (c == '\\') {
        if (*r) *w++ = *r++;          // escaped byte, taken literally
      } else if (quote == '"') {
        if (c == '"') quote = 0; else *w++ = c;
      } else if (c == '"' || c == '\'') {
        quote = c;
      } else if (isSpace(c)) {
        break;                        // r is past the space now, so w < r
      } else {
        *w++ = c;
      }
    }
    *w = 0;                           // w <= r: never overwrites unread input
    if (atEnd) break;
    w++;                              // still <= r
  }
  return argc;
}

int tokenize(char* line, char** argv, int maxArgs, size_t* offsets) {
  return tokenizeImpl(line, argv, maxArgs, offsets, false);
}

// True if the first len bytes end inside an open quote or right after a backslash, i.e. the
// trailing space (if any) belongs to the current argument.
static bool endsInQuote(const char* line, size_t len) {
  char quote = 0;
  bool esc = false;
  for (size_t i = 0; i < len; i++) {
    char c = line[i];
    if (esc) { esc = false; continue; }
    if (quote == '\'') { if (c == '\'') quote = 0; continue; }
    if (c == '\\') { esc = true; continue; }
    if (quote == '"') { if (c == '"') quote = 0; continue; }
    if (c == '"' || c == '\'') quote = c;
  }
  if (quote) return true;
  // "a\ " : the space was escaped
  return len >= 2 && line[len - 2] == '\\' && isSpace(line[len - 1]);
}

size_t secretFrom(const char* line, size_t len, const SecretRule* rules, size_t nRules) {
  if (!rules || !nRules) return (size_t)-1;
  char copy[GW_CLI_LINE_MAX + 1];
  if (len > GW_CLI_LINE_MAX) len = GW_CLI_LINE_MAX;
  memcpy(copy, line, len);
  copy[len] = 0;
  char* argv[GW_CLI_MAX_ARGS];
  size_t off[GW_CLI_MAX_ARGS];
  int argc = tokenizeImpl(copy, argv, GW_CLI_MAX_ARGS, off, true);
  if (argc == -2) argc = GW_CLI_MAX_ARGS;
  if (argc < 1) return (size_t)-1;
  for (size_t i = 0; i < nRules; i++) {
    const SecretRule& r = rules[i];
    if (strcmp(argv[0], r.w0) != 0) continue;
    if (r.w1 && (argc < 2 || strcmp(argv[1], r.w1) != 0)) continue;
    if (argc > r.secretArg) return off[r.secretArg];
    // Not typed yet: if the line ends in a separator right after the argument before it,
    // the secret starts at the next byte typed.
    if (argc == r.secretArg && len > 0 && isSpace(line[len - 1]) && !endsInQuote(line, len))
      return len;
    return (size_t)-1;
  }
  return (size_t)-1;
}

void LineEditor::reset() {
  len_ = 0;
  buf_[0] = 0;
  esc_ = 0;
  overflow_ = false;
  lastCR_ = false;
}

void LineEditor::wipe() {
  secureZero(buf_, sizeof buf_);
  secureZero(done_, sizeof done_);
  doneLen_ = 0;
  reset();
}

void LineEditor::redraw(const char* prompt) {
  if (prompt) write(prompt, strlen(prompt));
  size_t from = password_ ? 0 : secretFrom(buf_, len_, rules_, nRules_);
  for (size_t i = 0; i < len_; i++) {
    if (from != (size_t)-1 && i >= from) {
      if (((uint8_t)buf_[i] & 0xC0) != 0x80) write("*", 1);
    } else {
      write(&buf_[i], 1);
    }
  }
}

bool LineEditor::masked(size_t at) const {
  if (password_) return true;
  size_t from = secretFrom(buf_, len_, rules_, nRules_);
  return from != (size_t)-1 && at >= from;
}

bool LineEditor::feed(uint8_t c) {
  // Escape sequences: ESC [ params final(0x40..0x7E) | ESC O x | ESC x
  if (esc_ == 1) { esc_ = (c == '[') ? 2 : (c == 'O') ? 3 : 0; return false; }
  if (esc_ == 2) { if (c >= 0x40 && c <= 0x7E) esc_ = 0; return false; }
  if (esc_ == 3) { esc_ = 0; return false; }
  if (c == 0x1B) { esc_ = 1; return false; }

  if (c == '\n' && lastCR_) { lastCR_ = false; return false; }  // CRLF = one line
  lastCR_ = (c == '\r');

  if (c == '\r' || c == '\n') {
    write("\r\n", 2);
    memcpy(done_, buf_, len_ + 1);
    doneLen_ = len_;
    bool over = overflow_;
    secureZero(buf_, sizeof buf_);
    reset();
    overflow_ = over;
    lastCR_ = (c == '\r');  // so the LF of a CRLF is swallowed
    return true;
  }
  if (c == 0x08 || c == 0x7F) {
    if (!len_) return false;
    // Drop one UTF-8 character: continuation bytes (10xxxxxx) and their lead byte.
    size_t n = len_;
    while (n > 0 && ((uint8_t)buf_[n - 1] & 0xC0) == 0x80) n--;
    if (n > 0) n--;
    len_ = n;
    buf_[len_] = 0;
    write("\b \b", 3);
    return false;
  }
  if (c == 0x03 || c == 0x15) {  // Ctrl-C, Ctrl-U: drop the line
    write("^C\r\n", 4);
    secureZero(buf_, sizeof buf_);
    reset();
    return false;
  }
  if (c < 0x20 && c != '\t') return false;  // other control bytes: ignored
  if (c == '\t') c = ' ';
  if (len_ >= GW_CLI_LINE_MAX) { overflow_ = true; return false; }
  buf_[len_++] = (char)c;
  buf_[len_] = 0;
  bool cont = (c & 0xC0) == 0x80;
  if (masked(len_ - 1)) {
    if (!cont) write("*", 1);
  } else {
    char ch = (char)c;
    write(&ch, 1);
  }
  return false;
}

}  // namespace cli
}  // namespace gw
