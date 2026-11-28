// Native unit tests for the portable parts of the ZIGMon ESP32 Gateway firmware.
// Run with esp32/tests/run.sh. Asserts the vectors of esp32/PROTOCOL.md section 7.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>

#include "../ZigmonGateway/core_authlogic.h"
#include "../ZigmonGateway/core_cliline.h"
#include "../ZigmonGateway/core_crypto.h"
#include "../ZigmonGateway/core_eventring.h"
#include "../ZigmonGateway/core_proto.h"
#include "../ZigmonGateway/core_util.h"
#include "../ZigmonGateway/yeelock_proto.h"

using namespace gw;

static int g_fail = 0, g_pass = 0;

#define CHECK(cond)                                                          \
  do {                                                                       \
    if (cond) g_pass++;                                                      \
    else { g_fail++; printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); } \
  } while (0)

#define CHECK_STR(a, b)                                                                   \
  do {                                                                                    \
    std::string _a = (a), _b = (b);                                                       \
    if (_a == _b) g_pass++;                                                               \
    else { g_fail++; printf("  FAIL %s:%d: %s\n    got  %s\n    want %s\n", __FILE__, __LINE__, #a, _a.c_str(), _b.c_str()); } \
  } while (0)

static std::string hex(const uint8_t* p, size_t n) {
  char buf[256];
  toHex(p, n, buf);
  return buf;
}

// ---- section 7: request signature -----------------------------------------------------------
static void testRequestSig() {
  printf("request signature (PROTOCOL.md 7)\n");
  uint8_t key[32];
  for (int i = 0; i < 32; i++) key[i] = (uint8_t)i;
  const char* body = "{\"action\":\"unlock\",\"entity\":\"yeelock.front\"}";
  char bh[65];
  proto::bodyHash(body, strlen(body), bh);
  CHECK_STR(bh, "718db82c79edadd8a8b3967f1c4d93a9075fc9f46fb21626c56bacd21c1b6ca4");
  char sig[65];
  proto::requestSig(key, "POST", "/zigmon/v1/command", "1764340000",
                    "00112233445566778899aabbccddeeff", body, strlen(body), sig);
  CHECK_STR(sig, "9477fb4d74063d5884e02f074529b34194f46ebaa6559387c286c87c182ca83b");

  proto::bodyHash(nullptr, 0, bh);  // empty body hashes ""
  CHECK_STR(bh, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");

  // Full verification path.
  proto::ReplayRing ring;
  uint32_t ts = 0;
  const uint32_t now = 1764340010;
  proto::Verdict v = proto::verifyRequest(key, ring, now, "POST", "/zigmon/v1/command",
                                          "1764340000", "00112233445566778899aabbccddeeff", sig,
                                          body, strlen(body), &ts);
  CHECK(v == proto::Verdict::Ok);
  CHECK(ts == 1764340000u);
  // Same request again: replay.
  v = proto::verifyRequest(key, ring, now, "POST", "/zigmon/v1/command", "1764340000",
                           "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts);
  CHECK(v == proto::Verdict::Replay);
  // Uppercase signature is accepted (hex is case-insensitive on the wire).
  {
    proto::ReplayRing r2;
    std::string up = sig;
    for (auto& c : up) c = (char)toupper(c);
    v = proto::verifyRequest(key, r2, now, "POST", "/zigmon/v1/command", "1764340000",
                             "00112233445566778899aabbccddeeff", up.c_str(), body, strlen(body), &ts);
    CHECK(v == proto::Verdict::Ok);
  }
  // Tampered body, path, method, ts.
  {
    proto::ReplayRing r3;
    const char* bad = "{\"action\":\"open\",\"entity\":\"yeelock.front\"}";
    CHECK(proto::verifyRequest(key, r3, now, "POST", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, bad, strlen(bad), &ts) ==
          proto::Verdict::BadSig);
    CHECK(proto::verifyRequest(key, r3, now, "POST", "/zigmon/v1/command?x=1", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::BadSig);
    CHECK(proto::verifyRequest(key, r3, now, "GET", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::BadSig);
    CHECK(proto::verifyRequest(key, r3, now, "POST", "/zigmon/v1/command", "1764340001",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::BadSig);
    // A bad signature must not burn the nonce: the genuine request still passes afterwards.
    CHECK(proto::verifyRequest(key, r3, now, "POST", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::Ok);
  }
  // Skew: clock set, 121 s away -> refused; 120 s -> fine (sig checked after skew).
  {
    proto::ReplayRing r4;
    CHECK(proto::verifyRequest(key, r4, 1764340000 + 121, "POST", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::Skew);
    CHECK(proto::verifyRequest(key, r4, 1764340000 - 121, "POST", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::Skew);
    CHECK(proto::verifyRequest(key, r4, 1764340000 + 120, "POST", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::Ok);
  }
  // Clock not set: any ts is taken (after the signature checks).
  {
    proto::ReplayRing r5;
    CHECK(proto::verifyRequest(key, r5, 1000, "POST", "/zigmon/v1/command", "1764340000",
                               "00112233445566778899aabbccddeeff", sig, body, strlen(body), &ts) ==
          proto::Verdict::Ok);
  }
  // Malformed headers.
  {
    proto::ReplayRing r6;
    CHECK(proto::verifyRequest(key, r6, now, "POST", "/p", nullptr, "00112233445566778899aabbccddeeff",
                               sig, "", 0, &ts) == proto::Verdict::BadHeaders);
    CHECK(proto::verifyRequest(key, r6, now, "POST", "/p", "17643x0000", "00112233445566778899aabbccddeeff",
                               sig, "", 0, &ts) == proto::Verdict::BadHeaders);
    CHECK(proto::verifyRequest(key, r6, now, "POST", "/p", "1764340000", "0011", sig, "", 0, &ts) ==
          proto::Verdict::BadHeaders);
    CHECK(proto::verifyRequest(key, r6, now, "POST", "/p", "1764340000", "00112233445566778899aabbccddeefg",
                               sig, "", 0, &ts) == proto::Verdict::BadHeaders);
    CHECK(proto::verifyRequest(key, r6, now, "POST", "/p", "1764340000", "00112233445566778899aabbccddeeff",
                               "abc", "", 0, &ts) == proto::Verdict::BadHeaders);
  }
}

static void testResponseSig() {
  printf("response signature\n");
  uint8_t key[32];
  for (int i = 0; i < 32; i++) key[i] = (uint8_t)i;
  const char* body = "{\"ok\":true,\"job\":\"j1\"}";
  char sig[65];
  proto::responseSig(key, "00112233445566778899aabbccddeeff", 202, body, strlen(body), sig);
  // Computed independently with Python's hmac/hashlib.
  CHECK_STR(sig, "6824610d10be8ab28a3c1b7e651f4deeba285b2471073559e2db578e0f141325");
}

// ---- section 7: pairing proof ---------------------------------------------------------------
static void testPairing() {
  printf("pairing proof (PROTOCOL.md 7) and the pairing gate\n");
  std::string fp, nonce;
  for (int i = 0; i < 32; i++) fp += "ab";
  for (int i = 0; i < 16; i++) nonce += "0f";
  char proof[65];
  proto::pairProof("482913", fp.c_str(), nonce.c_str(), proof);
  CHECK_STR(proof, "268cac3700bba1a1cc76025483c59235fd45de76a55bad403a3d66a597bdd59a");

  PairGate g;
  CHECK(g.attempt(proof, fp.c_str(), nonce.c_str(), 100) == PairGate::NO_CODE);
  CHECK(g.start(100, 482913));
  CHECK_STR(g.code(), "482913");
  CHECK(g.active(100));
  CHECK(g.expiresIn(100) == 600);
  CHECK(g.attempt(proof, fp.c_str(), nonce.c_str(), 101) == PairGate::OK);
  // Single use.
  CHECK(g.attempt(proof, fp.c_str(), nonce.c_str(), 102) == PairGate::NO_CODE);
  // Code with leading zeros keeps 6 digits.
  CHECK(g.start(200, 42));
  CHECK_STR(g.code(), "000042");
  // Expiry: after 600 s the code is refused (and spent).
  CHECK(g.start(300, 482913));
  CHECK(g.attempt(proof, fp.c_str(), nonce.c_str(), 900) == PairGate::EXPIRED);
  CHECK(!g.active(900));
  // A wrong proof spends the code too.
  CHECK(g.start(1000, 482913));
  std::string bad(64, '0');
  CHECK(g.attempt(bad.c_str(), fp.c_str(), nonce.c_str(), 1001) == PairGate::BAD_PROOF);
  CHECK(g.attempt(proof, fp.c_str(), nonce.c_str(), 1002) == PairGate::NO_CODE);
  // Five wrong proofs lock pairing for 15 minutes.
  PairGate h;
  for (int i = 0; i < 5; i++) {
    CHECK(h.start(2000 + i, 482913));
    CHECK(h.attempt(bad.c_str(), fp.c_str(), nonce.c_str(), 2000 + i) == PairGate::BAD_PROOF);
  }
  CHECK(!h.start(2010, 482913));
  CHECK(h.lockedFor(2010) > 800);
  CHECK(h.attempt(proof, fp.c_str(), nonce.c_str(), 2010) == PairGate::LOCKED);
  CHECK(h.start(2004 + 900, 482913));
  CHECK(h.attempt(proof, fp.c_str(), nonce.c_str(), 2004 + 901) == PairGate::OK);
}

// ---- section 7: Yeelock packets -------------------------------------------------------------
static void testYeelock() {
  printf("Yeelock packets (PROTOCOL.md 7)\n");
  uint8_t key[32];
  size_t kl = yeelock::parseSignKey("00112233445566778899aabbccddeeff", key);
  CHECK(kl == 16);
  uint8_t p[20];
  yeelock::buildTimePacket(p, 0x5c84ff2f, key, kl);
  CHECK_STR(hex(p, 20), "08405c84ff2f55748c652e3c83fc10a7cddc7c9f");
  yeelock::buildActionPacket(p, 0x5c84ff2f, yeelock::MODE_UNLOCK, key, kl);
  CHECK_STR(hex(p, 20), "01505c84ff2f01674720aeda9918f538e1471bca");
  // The other modes, computed independently with Python.
  yeelock::buildActionPacket(p, 0x5c84ff2f, yeelock::MODE_OPEN, key, kl);
  CHECK_STR(hex(p, 20), "01505c84ff2f0079fe2c69af14b432f22845a8e0");
  yeelock::buildActionPacket(p, 0x5c84ff2f, yeelock::MODE_LOCK, key, kl);
  CHECK_STR(hex(p, 20), "01505c84ff2f026a65780114a9a0d3e21204a637");

  // Key parsing: case, separators, bounds.
  uint8_t k2[32];
  CHECK(yeelock::parseSignKey("00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF", k2) == 16);
  CHECK(memcmp(k2, key, 16) == 0);
  CHECK(yeelock::parseSignKey("0011223344556677", k2) == 8);       // 8 bytes: minimum
  CHECK(yeelock::parseSignKey("00112233445566", k2) == 0);         // 7 bytes
  CHECK(yeelock::parseSignKey("001122334455667", k2) == 0);        // odd
  CHECK(yeelock::parseSignKey("zz112233445566778899", k2) == 0);   // not hex
  CHECK(yeelock::parseSignKey(std::string(64, 'a').c_str(), k2) == 32);
  CHECK(yeelock::parseSignKey(std::string(66, 'a').c_str(), k2) == 0);
  CHECK(yeelock::parseSignKey("", k2) == 0);
  CHECK(yeelock::isValidSn("TEST0001"));
  CHECK(!yeelock::isValidSn("EL_TEST"));
  CHECK(!yeelock::isValidSn("abc"));
  uint8_t n9[] = {0x09, 0x01};
  CHECK(yeelock::isTimeRequest(n9, 2));
  CHECK(!yeelock::isTimeRequest(n9 + 1, 1));
}

// ---- PBKDF2 ---------------------------------------------------------------------------------
static void testPbkdf2() {
  printf("PBKDF2-HMAC-SHA256\n");
  uint8_t dk[64];
  crypto::pbkdf2Sha256((const uint8_t*)"passwd", 6, (const uint8_t*)"salt", 4, 1, dk, 64);
  // RFC 7914 section 11.
  CHECK_STR(hex(dk, 64),
            "55ac046e56e3089fec1691c22544b605f94185216dde0465e68b9d57c20dacbc49ca9cccf179b645991664b39d77ef317c71b845b1e30bd509112041d3a19783");
  crypto::pbkdf2Sha256((const uint8_t*)"password", 8, (const uint8_t*)"salt", 4, 4096, dk, 32);
  CHECK_STR(hex(dk, 32), "c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a");
  // The firmware's parameters: 10000 rounds, 16-byte salt.
  uint8_t salt[16];
  for (int i = 0; i < 16; i++) salt[i] = (uint8_t)i;
  crypto::pbkdf2Sha256((const uint8_t*)"correct horse", 13, salt, 16, GW_PBKDF2_ROUNDS, dk, 32);
  CHECK_STR(hex(dk, 32), "e515070e0353a7db013961984b87babb9edccff4aadff4d081a0cfffc316e8bf");
}

// ---- replay ring ----------------------------------------------------------------------------
static void testReplayRing() {
  printf("replay ring\n");
  proto::ReplayRing r;
  uint8_t n[16] = {0};
  uint32_t t0 = 1764340000;
  CHECK(r.checkAndAdd(n, t0));
  CHECK(!r.checkAndAdd(n, t0));          // same nonce
  CHECK(!r.checkAndAdd(n, t0 + 299));    // still within 300 s of the first
  n[0] = 1;
  CHECK(r.checkAndAdd(n, t0 + 1));
  // Fill the ring with fresh nonces (64 total), all young.
  for (int i = 2; i < GW_REPLAY_RING; i++) {
    n[0] = (uint8_t)i;
    CHECK(r.checkAndAdd(n, t0 + 2));
  }
  CHECK(r.floor() == 0);
  // 65th: evicts the oldest (ts t0) and raises the floor to t0.
  n[0] = 200;
  CHECK(r.checkAndAdd(n, t0 + 3));
  CHECK(r.floor() == t0);
  // The evicted nonce (n=0 at t0) is refused by the floor even though it left the ring.
  n[0] = 0;
  CHECK(!r.checkAndAdd(n, t0));
  // Anything at or below the floor is refused.
  n[0] = 201;
  CHECK(!r.checkAndAdd(n, t0));
  // Entries expire: 301 s later the slots are reused without raising the floor.
  proto::ReplayRing r2;
  for (int i = 0; i < GW_REPLAY_RING; i++) {
    n[0] = (uint8_t)i;
    CHECK(r2.checkAndAdd(n, t0));
  }
  n[0] = 250;
  CHECK(r2.checkAndAdd(n, t0 + 301));
  CHECK(r2.floor() == 0);
  // Old nonce at a new ts: its slot expired, so it is accepted (the skew check guards it).
  n[0] = 0;
  CHECK(r2.checkAndAdd(n, t0 + 302));
}

// ---- event ring -----------------------------------------------------------------------------
struct Collected {
  std::vector<uint32_t> seqs;
  std::vector<std::string> states;
};
static void collectFn(const Event& e, void* ctx) {
  Collected* c = (Collected*)ctx;
  c->seqs.push_back(e.seq);
  c->states.push_back(e.state);
}

static void testEventRing() {
  printf("event ring\n");
  EventRing r;
  CHECK(r.begin(4));
  bool gap = true;
  Collected c;
  CHECK(r.collect(0, 50, collectFn, &c, &gap) == 0);
  CHECK(!gap);
  CHECK(r.push("yeelock.a", "state", "", "{\"v\":1}", 0) == 1);
  CHECK(r.push("yeelock.a", "result", "j1", "{\"v\":2}", 0) == 2);
  CHECK(r.seq() == 2);
  CHECK(r.hasAfter(1));
  CHECK(!r.hasAfter(2));
  c = Collected();
  CHECK(r.collect(0, 50, collectFn, &c, &gap) == 2);
  CHECK(!gap);
  CHECK(c.seqs.size() == 2 && c.seqs[0] == 1 && c.seqs[1] == 2);
  CHECK_STR(c.states[1], "{\"v\":2}");
  c = Collected();
  CHECK(r.collect(1, 50, collectFn, &c, &gap) == 1 && c.seqs[0] == 2);
  // Overflow: capacity 4, push 3 more (seq 3..5): seq 1 is gone.
  r.push("x", "state", "", "{}", 0);
  r.push("x", "state", "", "{}", 0);
  r.push("x", "state", "", "{}", 0);
  CHECK(r.oldestSeq() == 2);
  c = Collected();
  CHECK(r.collect(1, 50, collectFn, &c, &gap) == 4);
  CHECK(!gap);  // after=1 still continuous (2 is the oldest)
  c = Collected();
  CHECK(r.collect(0, 50, collectFn, &c, &gap) == 4);
  CHECK(gap);   // seq 1 was lost
  CHECK(c.seqs.front() == 2 && c.seqs.back() == 5);
  // A seq from the future (another boot): gap, and everything we have.
  c = Collected();
  CHECK(r.collect(99, 50, collectFn, &c, &gap) == 4);
  CHECK(gap);
  // Limit.
  c = Collected();
  CHECK(r.collect(1, 2, collectFn, &c, &gap) == 2 && c.seqs[1] == 3);
  // Oversized state is dropped whole, never cut into invalid JSON.
  std::string big(GW_EVENT_STATE_MAX + 10, 'x');
  r.push("x", "state", "", big.c_str(), 0);
  c = Collected();
  r.collect(5, 50, collectFn, &c, &gap);
  CHECK(c.states.size() == 1 && c.states[0].empty());
}

// ---- CLI tokenizer and line editor ------------------------------------------------------------
static std::vector<std::string> tok(const char* s, int* rc = nullptr) {
  char buf[300];
  strcpy(buf, s);
  char* argv[GW_CLI_MAX_ARGS];
  int n = cli::tokenize(buf, argv, GW_CLI_MAX_ARGS);
  if (rc) *rc = n;
  std::vector<std::string> v;
  for (int i = 0; i < n; i++) v.push_back(argv[i]);
  return v;
}

static std::string g_echo;
static void echoFn(const char* s, size_t n, void*) { g_echo.append(s, n); }

static void testCli() {
  printf("CLI tokenizer and line editor\n");
  auto v = tok("wifi set \"My Home Net\" 'pa ss\"word'");
  CHECK(v.size() == 4);
  if (v.size() == 4) {
    CHECK_STR(v[2], "My Home Net");
    CHECK_STR(v[3], "pa ss\"word");
  }
  v = tok("   status   ");
  CHECK(v.size() == 1 && v[0] == "status");
  v = tok("a\\ b \"c\\\"d\" e\"f g\"h");
  CHECK(v.size() == 3);
  if (v.size() == 3) {
    CHECK_STR(v[0], "a b");
    CHECK_STR(v[1], "c\"d");
    CHECK_STR(v[2], "ef gh");
  }
  v = tok("x \"\" y");
  CHECK(v.size() == 3 && v[1].empty());
  int rc;
  tok("wifi set \"unterminated", &rc);
  CHECK(rc == -1);
  tok("1 2 3 4 5 6 7 8 9 10 11 12 13", &rc);
  CHECK(rc == -2);
  v = tok("");
  CHECK(v.empty());
  v = tok("yeelock add \"Front drawer\" TEST0001 00112233445566778899aabbccddeeff");
  CHECK(v.size() == 5 && v[2] == "Front drawer");

  // Secret masking rules.
  static const cli::SecretRule rules[] = {{"wifi", "set", 3}, {"yeelock", "add", 4}};
  const char* l1 = "wifi set \"My Net\" secret";
  CHECK(cli::secretFrom(l1, strlen(l1), rules, 2) == strlen("wifi set \"My Net\" "));
  const char* l2 = "wifi set \"My Net\" ";
  CHECK(cli::secretFrom(l2, strlen(l2), rules, 2) == strlen(l2));
  const char* l3 = "wifi set \"My Ne";
  CHECK(cli::secretFrom(l3, strlen(l3), rules, 2) == (size_t)-1);
  const char* l3b = "wifi set \"My ";   // the space is inside the quoted SSID
  CHECK(cli::secretFrom(l3b, strlen(l3b), rules, 2) == (size_t)-1);
  const char* l3c = "wifi set My\\ ";
  CHECK(cli::secretFrom(l3c, strlen(l3c), rules, 2) == (size_t)-1);
  const char* l4 = "wifi scan";
  CHECK(cli::secretFrom(l4, strlen(l4), rules, 2) == (size_t)-1);

  // Editor: typing with backspace, CRLF, escape sequences, masking.
  cli::LineEditor ed;
  ed.setOutput(echoFn, nullptr);
  ed.setRules(rules, 2);
  g_echo.clear();
  const char* typed = "stt\x7f" "atus\x1b[A\x1bOB\r\n";
  int lines = 0;
  for (const char* p = typed; *p; p++) lines += ed.feed((uint8_t)*p) ? 1 : 0;
  CHECK(lines == 1);
  CHECK_STR(ed.line(), "status");
  bool done;
  // Feeding the LF of CRLF must not produce an empty second line.
  CHECK(!ed.feed('x'));
  ed.reset();

  g_echo.clear();
  const char* wifi = "wifi set Home pw12\x08" "3\r";
  done = false;
  for (const char* p = wifi; *p; p++) done = ed.feed((uint8_t)*p) || done;
  CHECK(done);
  CHECK_STR(ed.line(), "wifi set Home pw13");
  CHECK(g_echo.find("pw") == std::string::npos);   // never echoed
  CHECK(g_echo.find("wifi set Home ") == 0);
  CHECK(g_echo.find("****") != std::string::npos);

  // Redraw (after a log line) masks exactly like the live echo.
  for (const char* p = "wifi set \"My Net\" abc"; *p; p++) ed.feed((uint8_t)*p);
  g_echo.clear();
  ed.redraw("> ");
  CHECK_STR(g_echo, "> wifi set \"My Net\" ***");
  ed.reset();

  // Password mode echoes '*' only.
  g_echo.clear();
  ed.setPasswordMode(true);
  for (const char* p = "hunter22\n"; *p; p++) ed.feed((uint8_t)*p);
  CHECK_STR(ed.line(), "hunter22");
  CHECK(g_echo.find("hunter") == std::string::npos);
  ed.setPasswordMode(false);

  // UTF-8: backspace drops the whole character.
  g_echo.clear();
  for (const char* p = "k\xc5\xaf\x7f" "o\r"; *p; p++) ed.feed((uint8_t)*p);
  CHECK_STR(ed.line(), "ko");

  // Ctrl-C drops the line; overflow is flagged.
  for (const char* p = "junk\x03ok\r"; *p; p++) ed.feed((uint8_t)*p);
  CHECK_STR(ed.line(), "ok");
  for (int i = 0; i < GW_CLI_LINE_MAX + 20; i++) ed.feed('a');
  ed.feed('\r');
  CHECK(ed.overflowed());
  CHECK(ed.length() == GW_CLI_LINE_MAX);
}

// ---- sessions and the login throttle --------------------------------------------------------------
static void testAuth() {
  printf("sessions, CSRF, login throttle\n");
  SessionTable t;
  char tok1[33], csrf1[33];
  t.create(10, tok1, csrf1);
  CHECK(strlen(tok1) == 32 && isHex(tok1, 32, true));
  int s = t.find(tok1, 11);
  CHECK(s >= 0);
  CHECK(t.csrfOk(s, csrf1));
  CHECK(!t.csrfOk(s, tok1));
  CHECK(!t.csrfOk(s, ""));
  CHECK(t.find("0123456789abcdef0123456789abcdef", 11) < 0);
  CHECK(t.find(tok1, 10 + GW_SESSION_TTL_S) < 0);   // 12 h later: gone
  // Four slots; a fifth evicts the oldest.
  char tk[5][33], cs[33];
  for (int i = 0; i < 5; i++) t.create(100 + i, tk[i], cs);
  CHECK(t.find(tk[0], 200) < 0);
  for (int i = 1; i < 5; i++) CHECK(t.find(tk[i], 200) >= 0);
  CHECK(t.count(200) == 4);
  t.remove(t.find(tk[1], 200));
  CHECK(t.find(tk[1], 200) < 0);

  LoginThrottle l;
  for (int i = 0; i < 4; i++) { l.failed(1000); CHECK(l.waitLeft(1000) == 0); }
  l.failed(1000);
  CHECK(l.waitLeft(1000) == 60);
  CHECK(l.waitLeft(1060) == 0);
  l.failed(1060);
  CHECK(l.waitLeft(1060) == 120);
  uint32_t now = 1200;
  for (int i = 0; i < 10; i++) { l.failed(now); now += l.waitLeft(now); }
  CHECK(l.waitLeft(now - 1) <= 3600);
  l.failed(now);
  CHECK(l.waitLeft(now) == 3600);
  l.succeeded();
  CHECK(l.waitLeft(now) == 0 && l.fails() == 0);
}

// ---- utilities --------------------------------------------------------------------------------------
static void testUtil() {
  printf("utilities\n");
  CHECK(ctEqual("abc", "abc", 3));
  CHECK(!ctEqual("abc", "abd", 3));
  CHECK(ctStrEqual("secret", 6, "secret", 6));
  CHECK(!ctStrEqual("secre", 5, "secret", 6));
  CHECK(!ctStrEqual("secrets", 7, "secret", 6));
  char m[16];
  CHECK_STR(maskSecret("", m, sizeof m), "not set");
  CHECK_STR(maskSecret("hunter22", m, sizeof m), "set (..22)");
  CHECK_STR(maskSecret("abc", m, sizeof m), "set");
  uint8_t ip[4];
  CHECK(parseIPv4("192.168.1.50", ip) && ip[0] == 192 && ip[3] == 50);
  CHECK(!parseIPv4("192.168.1", ip));
  CHECK(!parseIPv4("192.168.1.256", ip));
  CHECK(!parseIPv4("1.2.3.4.5", ip));
  CHECK(!parseIPv4("1..3.4", ip));
  CHECK(isSlug("front_drawer-2", 24));
  CHECK(!isSlug("Front", 24));
  CHECK(!isSlug("-x", 24));
  CHECK(isHostLabel("zigmon-gw-a1b2c3"));
  CHECK(!isHostLabel("zigmon-"));
  CHECK(!isHostLabel("zig.mon"));
  CHECK(isCleanText("Front drawer \xc5\xa1upl\xc3\xadk", 40));
  CHECK(!isCleanText("a\nb", 40));
  uint32_t u;
  CHECK(parseU32("4294967295", &u) && u == 4294967295u);
  CHECK(!parseU32("4294967296", &u));
  CHECK(!parseU32("-1", &u));
  uint32_t lo = 0, hi = 0;
  for (int i = 0; i < 2000; i++) {
    uint32_t r = crypto::randomBelow(10);
    if (r < 5) lo++; else hi++;
    CHECK(r < 10);
  }
  CHECK(lo > 800 && hi > 800);
  char rh[33];
  crypto::randomHex(rh, 16);
  CHECK(strlen(rh) == 32 && isHex(rh, 32, true));
}

int main() {
  testRequestSig();
  testResponseSig();
  testPairing();
  testYeelock();
  testPbkdf2();
  testReplayRing();
  testEventRing();
  testCli();
  testAuth();
  testUtil();
  printf("\n%d passed, %d failed\n", g_pass, g_fail);
  return g_fail ? 1 : 0;
}
