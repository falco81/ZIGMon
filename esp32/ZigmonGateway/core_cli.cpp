// ZIGMon ESP32 Gateway - the serial CLI.
#include "core_cli.h"

#include <ArduinoJson.h>
#include <WiFi.h>

#include "core_auth.h"
#include "core_cert.h"
#include "core_cliline.h"
#include "core_config.h"
#include "core_json.h"
#include "core_log.h"
#include "core_mem.h"
#include "core_net.h"
#include "core_pairing.h"
#include "core_registry.h"
#include "core_sys.h"
#include "core_util.h"
#include "gw_config.h"

namespace gw {
namespace cli {

static LineEditor g_ed;
static const char* PROMPT = "zgw> ";

enum class Mode : uint8_t { Normal, Password1, Password2, Secret };
static Mode g_mode = Mode::Normal;
static char g_pw1[GW_PASSWORD_MAX + 2];
static uint32_t g_factoryArmed = 0;  // monoS() when `factory-reset` was typed
static bool g_promptShown = false;
static char g_secretPrompt[48];
static SecretFn g_secretFn = nullptr;
static void* g_secretCtx = nullptr;

static void out(const char* s, size_t n, void*) { Serial.write((const uint8_t*)s, n); }

static const char* promptText() {
  switch (g_mode) {
    case Mode::Password1: return "New admin password: ";
    case Mode::Password2: return "Repeat it: ";
    case Mode::Secret: return g_secretPrompt;
    default: return PROMPT;
  }
}

static void prompt() {
  Serial.print(promptText());
  g_promptShown = true;
}

// After a log line from another task: put the prompt and the typed text back.
static void afterLog() {
  if (!g_promptShown) return;
  g_ed.redraw(promptText());
}

void askSecret(const char* p, SecretFn fn, void* ctx) {
  copyStr(g_secretPrompt, sizeof g_secretPrompt, p);
  g_secretFn = fn;
  g_secretCtx = ctx;
  g_mode = Mode::Secret;
  g_ed.setPasswordMode(true);
}

struct Cmd {
  const char* name;
  const char* usage;
  const char* help;
};

static const Cmd kCmds[] = {
    {"help", "help [cmd]", "every command, one line each"},
    {"status", "status", "firmware, uptime, Wi-Fi, time, pairing, modules"},
    {"wifi", "wifi scan | set <ssid> [password] | forget | static <ip> <mask> <gw> [dns] | dhcp",
     "Wi-Fi: quote an SSID with spaces, e.g. wifi set \"My Home\" secret"},
    {"hostname", "hostname <name>", "mDNS name (<name>.local); default zigmon-gw-xxxxxx"},
    {"password", "password", "set the web UI's admin password (asked twice, never echoed)"},
    {"webinit", "webinit", "re-open the first-run password page for 10 minutes"},
    {"fingerprint", "fingerprint", "the HTTPS certificate's SHA-256 (compare it in ZIGMon)"},
    {"pair", "pair", "show a 6-digit pairing code for ZIGMon (10 minutes, single use)"},
    {"unpair", "unpair", "forget ZIGMon"},
    {"time", "time [unix]", "show or set the clock (UTC)"},
    {"modules", "modules", "each module, its version and its entities"},
    {"log", "log [error|warn|info|debug]", "show or set the log level; prints the recent log"},
    {"reboot", "reboot", "restart the gateway"},
    {"factory-reset", "factory-reset", "erase everything (asked twice: factory-reset, then factory-reset YES)"},
};

static void printUptime(Print& p, uint32_t s) {
  p.printf("%lud %02lu:%02lu:%02lu", (unsigned long)(s / 86400), (unsigned long)(s / 3600 % 24),
           (unsigned long)(s / 60 % 60), (unsigned long)(s % 60));
}

static void cmdHelp(int argc, char** argv) {
  if (argc >= 2) {
    for (const auto& c : kCmds)
      if (strcmp(c.name, argv[1]) == 0) {
        Serial.printf("  %s\n      %s\n", c.usage, c.help);
        return;
      }
    Module* m = registry::find(argv[1]);
    if (m) { m->cliHelp(Serial); return; }
    Serial.printf("no such command: %s\n", argv[1]);
    return;
  }
  Serial.println("Commands (help <cmd> for details):");
  for (const auto& c : kCmds) Serial.printf("  %-14s %s\n", c.name, c.help);
  for (size_t i = 0; i < registry::count(); i++) {
    Module* m = registry::at(i);
    Serial.printf("  %-14s %s module (help %s)\n", m->id(), m->name(), m->id());
  }
}

static void cmdStatus() {
  NetConfig& n = config::net();
  Serial.printf("ZIGMon Gateway %s  (%s, id %s, %s)\n", GW_FW_VERSION, chipModel(), gatewayId(),
                havePsram() ? "PSRAM" : "no PSRAM");
  Serial.print("  uptime    ");
  printUptime(Serial, millis() / 1000);
  Serial.printf("   heap %lu B free\n", (unsigned long)ESP.getFreeHeap());
  if (!n.ssid[0]) Serial.println("  wifi      not configured (wifi set <ssid> <password>)");
  else if (net::connected())
    Serial.printf("  wifi      \"%s\"  IP %s  RSSI %d dBm  %s\n", n.ssid, net::ip().c_str(), net::rssi(),
                  n.dhcp ? "DHCP" : "static");
  else Serial.printf("  wifi      \"%s\"  not connected\n", n.ssid);
  Serial.printf("  web UI    https://%s.local/  (password %s)\n", n.hostname,
                auth::passwordSet() ? "set" : "NOT SET: run `password`");
  uint32_t t = nowUnix();
  if (clockSet()) {
    time_t tt = (time_t)t;
    struct tm tm;
    gmtime_r(&tt, &tm);
    Serial.printf("  time      %04d-%02d-%02d %02d:%02d:%02d UTC (%lu)\n", tm.tm_year + 1900, tm.tm_mon + 1,
                  tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec, (unsigned long)t);
  } else {
    Serial.println("  time      not set (NTP, ZIGMon or `time <unix>` will set it)");
  }
  if (config::paired()) Serial.printf("  ZIGMon    paired with \"%s\"\n", config::zigmonName());
  else Serial.println("  ZIGMon    not paired (pair)");
  Serial.print("  modules  ");
  for (size_t i = 0; i < registry::count(); i++)
    Serial.printf(" %s %s", registry::at(i)->id(), registry::at(i)->version());
  Serial.println();
}

static bool ipArg(const char* s, uint8_t out[4], const char* what) {
  if (parseIPv4(s, out)) return true;
  Serial.printf("not an IPv4 address (%s): %s\n", what, s);
  return false;
}

static void cmdWifi(int argc, char** argv) {
  NetConfig& n = config::net();
  const char* sub = argc >= 2 ? argv[1] : "";
  if (strcmp(sub, "scan") == 0) {
    Serial.println("scanning...");
    JsonDocument d(jsonAlloc());
    JsonArray arr = d.to<JsonArray>();
    net::scanBlocking(arr);
    if (arr.size() == 0) Serial.println("  no networks found");
    for (JsonObject o : arr)
      Serial.printf("  %4d dBm  ch %2d  %s  %s\n", (int)(o["rssi"] | 0), (int)(o["ch"] | 0),
                    (o["secure"] | false) ? "WPA " : "open", (const char*)(o["ssid"] | ""));
    return;
  }
  Guard g;
  if (strcmp(sub, "set") == 0 && (argc == 3 || argc == 4)) {
    const char* ssid = argv[2];
    const char* pass = argc == 4 ? argv[3] : "";
    if (!*ssid || strlen(ssid) > 32) { Serial.println("SSID: 1 to 32 bytes"); return; }
    size_t pl = strlen(pass);
    if (pl > 63 || (pl && pl < 8)) { Serial.println("a WPA password has 8 to 63 characters"); return; }
    copyStr(n.ssid, sizeof n.ssid, ssid);
    copyStr(n.pass, sizeof n.pass, pass);
    config::saveNet();
    secureZero(argv[argc - 1], strlen(argv[argc - 1]));
    Serial.printf("saved; connecting to \"%s\" (password %s)\n", n.ssid, pl ? "set" : "none");
    net::apply();
  } else if (strcmp(sub, "forget") == 0) {
    n.ssid[0] = 0;
    secureZero(n.pass, sizeof n.pass);
    config::saveNet();
    net::apply();
    Serial.println("Wi-Fi forgotten");
  } else if (strcmp(sub, "static") == 0 && (argc == 5 || argc == 6)) {
    uint8_t ip[4], mask[4], gw4[4], dns[4] = {0};
    if (!ipArg(argv[2], ip, "ip") || !ipArg(argv[3], mask, "mask") || !ipArg(argv[4], gw4, "gw")) return;
    if (argc == 6 && !ipArg(argv[5], dns, "dns")) return;
    n.dhcp = false;
    memcpy(n.ip, ip, 4);
    memcpy(n.mask, mask, 4);
    memcpy(n.gw, gw4, 4);
    memcpy(n.dns, dns, 4);
    config::saveNet();
    Serial.println("static IP saved; reconnecting");
    net::apply();
  } else if (strcmp(sub, "dhcp") == 0) {
    n.dhcp = true;
    config::saveNet();
    Serial.println("DHCP; reconnecting");
    net::apply();
  } else {
    Serial.println("usage: wifi scan | set <ssid> [password] | forget | static <ip> <mask> <gw> [dns] | dhcp");
  }
}

static void cmdHostname(int argc, char** argv) {
  NetConfig& n = config::net();
  if (argc < 2) { Serial.printf("%s.local\n", n.hostname); return; }
  if (!isHostLabel(argv[1])) { Serial.println("a-z, 0-9 and -, up to 32 characters"); return; }
  bool nameWasHost = strcmp(n.name, n.hostname) == 0;
  copyStr(n.hostname, sizeof n.hostname, argv[1]);
  if (nameWasHost) copyStr(n.name, sizeof n.name, argv[1]);
  config::saveNet();
  net::restartMdns();
  WiFi.setHostname(n.hostname);  // DHCP hostname: from the next connection
  Serial.printf("hostname %s (https://%s.local/)\n", n.hostname, n.hostname);
}

static void cmdTime(int argc, char** argv) {
  if (argc >= 2) {
    uint32_t t;
    if (!parseU32(argv[1], &t) || t < GW_CLOCK_VALID_FROM) { Serial.println("usage: time <unix seconds, UTC>"); return; }
    setClock(t, "the CLI");
  }
  if (!clockSet()) { Serial.println("not set"); return; }
  time_t tt = (time_t)nowUnix();
  struct tm tm;
  gmtime_r(&tt, &tm);
  Serial.printf("%lu  %04d-%02d-%02d %02d:%02d:%02d UTC\n", (unsigned long)tt, tm.tm_year + 1900, tm.tm_mon + 1,
                tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec);
}

static void cmdModules() {
  JsonDocument d(jsonAlloc());
  registry::describe(d.to<JsonObject>());
  for (JsonObject m : d["modules"].as<JsonArray>()) {
    Serial.printf("%s %s - %s\n", (const char*)(m["id"] | ""), (const char*)(m["version"] | ""),
                  (const char*)(m["name"] | ""));
    JsonArray ents = m["entities"].as<JsonArray>();
    if (ents.size() == 0) Serial.println("  (no entities)");
    for (JsonObject e : ents) {
      Serial.printf("  %-28s %-8s %s  [", (const char*)(e["id"] | ""), (const char*)(e["type"] | ""),
                    (const char*)(e["name"] | ""));
      bool first = true;
      for (JsonVariant a : e["actions"].as<JsonArray>()) {
        Serial.printf(first ? "%s" : " %s", a.as<const char*>());
        first = false;
      }
      Serial.println("]");
    }
  }
}

static void logLine(const char* line, void*) { Serial.println(line); }

static void cmdLog(int argc, char** argv) {
  if (argc >= 2) {
    log::Level l;
    if (!log::parseLevel(argv[1], &l)) { Serial.println("usage: log [error|warn|info|debug]"); return; }
    log::setLevel(l);
    config::setLogLevel(l);
  }
  Serial.printf("log level %s; recent lines:\n", log::levelName(log::level()));
  log::tail(logLine, nullptr, 30);
}

static void cmdPair() {
  String err;
  if (!pairing::start(err)) { Serial.println(err); return; }
  Serial.println();
  Serial.printf("  Pairing code:  %s   (valid 10 minutes, single use)\n", pairing::code());
  Serial.printf("  Fingerprint:   %s\n", cert::fingerprintPretty().c_str());
  Serial.printf("  Address:       %s  or  %s.local\n", net::ip().c_str(), config::net().hostname);
  Serial.println("  In ZIGMon: Settings > Devices > ESP32 gateways > Add.");
  Serial.println();
}

static void cmdFactoryReset(int argc, char** argv) {
  uint32_t now = monoS();
  if (argc >= 2 && strcmp(argv[1], "YES") == 0) {
    if (g_factoryArmed && now - g_factoryArmed <= GW_FACTORY_CONFIRM_S) {
      Serial.println("Erasing everything and rebooting...");
      Serial.flush();
      config::factoryReset();
      return;
    }
    Serial.println("type `factory-reset` first, then `factory-reset YES` within 30 s");
    return;
  }
  g_factoryArmed = now;
  Serial.println("This erases Wi-Fi, the admin password, the ZIGMon pairing, every module's");
  Serial.println("settings (all locks and keys) and the certificate. To confirm, type within 30 s:");
  Serial.println("  factory-reset YES");
}

static void run(char* line) {
  char* argv[GW_CLI_MAX_ARGS];
  int argc = tokenize(line, argv, GW_CLI_MAX_ARGS);
  if (argc == -1) { Serial.println("unterminated quote"); return; }
  if (argc == -2) { Serial.println("too many arguments"); return; }
  if (argc == 0) return;
  const char* c = argv[0];
  if (strcmp(c, "help") == 0 || strcmp(c, "?") == 0) { Guard g; cmdHelp(argc, argv); }
  else if (strcmp(c, "status") == 0) { Guard g; cmdStatus(); }
  else if (strcmp(c, "wifi") == 0) cmdWifi(argc, argv);
  else if (strcmp(c, "hostname") == 0) { Guard g; cmdHostname(argc, argv); }
  else if (strcmp(c, "password") == 0) {
    g_mode = Mode::Password1;
    g_ed.setPasswordMode(true);
    Serial.println("Set the web UI's admin password (8-64 characters). Ctrl-C cancels.");
  } else if (strcmp(c, "webinit") == 0) {
    Guard g;
    if (auth::passwordSet())
      Serial.println("a password is set; `password` changes it. The first-run page is only for a new gateway.");
    else {
      auth::openFirstRun();
      Serial.printf("open https://%s.local/ (or https://%s/) within 10 minutes\n", config::net().hostname,
                    net::ip().c_str());
    }
  } else if (strcmp(c, "fingerprint") == 0) {
    Serial.printf("SHA-256 %s\n        %s\n", cert::fingerprint(), cert::fingerprintPretty().c_str());
  } else if (strcmp(c, "pair") == 0) { Guard g; cmdPair(); }
  else if (strcmp(c, "unpair") == 0) {
    Guard g;
    if (!config::paired()) Serial.println("not paired");
    else { pairing::unpair("CLI"); Serial.println("ZIGMon forgotten"); }
  } else if (strcmp(c, "time") == 0) { Guard g; cmdTime(argc, argv); }
  else if (strcmp(c, "modules") == 0) { Guard g; cmdModules(); }
  else if (strcmp(c, "log") == 0) cmdLog(argc, argv);
  else if (strcmp(c, "reboot") == 0) { Serial.println("rebooting"); Serial.flush(); delay(100); ESP.restart(); }
  else if (strcmp(c, "factory-reset") == 0) cmdFactoryReset(argc, argv);
  else {
    Module* m = registry::find(c);
    if (m) {
      Guard g;
      if (argc < 2 || !m->cliCommand(Serial, argc, argv)) m->cliHelp(Serial);
    } else {
      Serial.printf("unknown command: %s (help lists them)\n", c);
    }
  }
}

static void onPasswordLine(const char* pw) {
  if (g_mode == Mode::Password1) {
    String err;
    if (strlen(pw) < GW_PASSWORD_MIN || strlen(pw) > GW_PASSWORD_MAX) {
      Serial.println("8 to 64 characters, please. Cancelled.");
      g_mode = Mode::Normal;
      g_ed.setPasswordMode(false);
      return;
    }
    copyStr(g_pw1, sizeof g_pw1, pw);
    g_mode = Mode::Password2;
    return;
  }
  bool same = ctStrEqual(pw, strlen(pw), g_pw1, strlen(g_pw1));
  g_mode = Mode::Normal;
  g_ed.setPasswordMode(false);
  if (!same) {
    Serial.println("they differ; nothing changed");
  } else {
    Serial.println("deriving the key (PBKDF2, 10000 rounds)...");
    String err;
    Guard g;
    if (auth::setPassword(g_pw1, err)) Serial.println("admin password set; all web sessions logged out");
    else Serial.println(err);
  }
  secureZero(g_pw1, sizeof g_pw1);
}

void begin() {
  g_ed.setOutput(out, nullptr);
  size_t n = 0;
  const SecretRule* r = registry::secretRules(&n);
  g_ed.setRules(r, n);
  log::setPrintedHook(afterLog);
  Serial.println();
  Serial.println("ZIGMon Gateway CLI - type `help`.");
  prompt();
}

void loop() {
  int budget = 128;  // bytes per loop() call, so a paste can't starve the rest
  while (Serial.available() > 0 && budget-- > 0) {
    int ch = Serial.read();
    if (ch < 0) break;
    if (g_mode != Mode::Normal && (ch == 0x03)) {  // Ctrl-C cancels the password prompt
      g_mode = Mode::Normal;
      g_ed.setPasswordMode(false);
      g_ed.wipe();
      secureZero(g_pw1, sizeof g_pw1);
      g_secretFn = nullptr;
      Serial.println("^C cancelled");
      prompt();
      continue;
    }
    if (!g_ed.feed((uint8_t)ch)) continue;
    g_promptShown = false;
    if (g_ed.overflowed()) {
      Serial.printf("line too long (max %d characters)\n", GW_CLI_LINE_MAX);
      g_ed.wipe();
      prompt();
      continue;
    }
    char line[GW_CLI_LINE_MAX + 1];
    memcpy(line, g_ed.line(), g_ed.length() + 1);
    if (g_mode == Mode::Secret) {
      SecretFn fn = g_secretFn;
      void* ctx = g_secretCtx;
      g_mode = Mode::Normal;
      g_ed.setPasswordMode(false);
      g_secretFn = nullptr;
      if (fn) {
        Guard g;
        fn(line, ctx);
      }
    } else if (g_mode != Mode::Normal) {
      onPasswordLine(line);
      g_ed.wipe();
    } else {
      run(line);
    }
    secureZero(line, sizeof line);
    // Anything typed after a secret-bearing command must not linger in the editor.
    g_ed.wipe();
    prompt();
  }
  if (g_factoryArmed && monoS() - g_factoryArmed > GW_FACTORY_CONFIRM_S) g_factoryArmed = 0;
}

}  // namespace cli
}  // namespace gw
