// ZIGMon ESP32 Gateway - the Yeelock module (contract section 6).
//
// Drives Xiaomi Yeelock BLE locks (drawer and cabinet locks, advertised as "EL_<SN>"), up to
// MAX_LOCKS per gateway. Each lock is one entity "yeelock.<id>" of type "lock" with the
// actions open (unlock, then the lock re-locks itself), unlock, lock and refresh (battery).
//
// The protocol is unofficial and community-derived: aso824/yeehack and cnrd/yeelock did the
// reverse engineering. A lock needs no pairing; what authenticates a command is the lock's
// `ble_sign_key` (from the Yeelock cloud), which signs every packet with HMAC-SHA1.
//
// NimBLE-Arduino 1.4.x API (pinned: 2.x renamed the scan and client calls).
#include "mod_yeelock.h"

#include <NimBLEDevice.h>
#include <Preferences.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "core_ble.h"
#include "core_events.h"
#include "core_jobs.h"
#include "core_json.h"
#include "core_log.h"
#include "core_mem.h"
#include "core_sys.h"
#include "core_cli.h"
#include "core_util.h"
#include "yeelock_cloud.h"
#include "yeelock_codes.h"
#include "yeelock_proto.h"

namespace gw {
namespace {

const char* const MOD_ID = "yeelock";
const char* const kUuidCmd = "58af3dca-6fc0-4fa3-9464-74662f043a3b";
const char* const kUuidNotify = "58af3dca-6fc0-4fa3-9464-74662f043a3a";
const uint16_t kUuidBattSvc = 0x180F;
const uint16_t kUuidBattChr = 0x2A19;
const size_t MAX_LOCKS = 10;
const size_t MAX_FOUND = 16;
const uint32_t ANSWER_WAIT_MS = 4000;   // contract: collect notifications for up to 4 s

enum Value : uint8_t { V_UNKNOWN = 0, V_LOCKED = 1, V_UNLOCKED = 2 };
// The first four are the entity's actions; "check" (connect, battery, time sync only: never
// unlocks) is the web UI's / CLI's key test.
enum Act : uint8_t { A_OPEN = 0, A_UNLOCK = 1, A_LOCK = 2, A_REFRESH = 3, A_CHECK = 4 };
const char* const kActNames[] = {"open", "unlock", "lock", "refresh", "check"};
const int N_ENTITY_ACTIONS = 4;

// What went wrong last, for a clear message in the UI ("problem" in STATE.last, additive).
enum Problem : uint8_t { P_NONE = 0, P_NOT_FOUND, P_CONNECT, P_WRONG_KEY, P_PROTOCOL };
const char* const kProblemNames[] = {"", "not_found", "connect", "wrong_key", "protocol"};

const size_t CLOUD_TRIES = 5;             // cloud logins per 10 minutes
const uint32_t CLOUD_WINDOW_S = 600;
const uint32_t CLOUD_KEEP_S = 600;        // fetched keys are wiped from RAM after 10 min

struct Lock {
  bool used;
  char id[24];
  char name[41];
  char sn[21];
  uint8_t key[yeelock::KEY_MAX];
  uint8_t keyLen;
  // runtime
  char addr[18];
  uint8_t addrType;
  int battery;        // -1 unknown
  int rssi;           // 0 unknown
  Value value;
  bool available;
  uint8_t pending;    // jobs queued or running
  bool haveLast;
  uint8_t lastAct;
  bool lastOk;
  uint32_t lastAt;
  char lastMsg[96];
  Problem lastProblem;
  Problem problem;         // standing problem (wrong key from a check or an action)
  uint32_t lastBatteryMs;  // millis() of the last battery read, 0 = never
};

// NVS record of a lock (version 1). Only what the user configured; no runtime state.
struct Persist {
  uint8_t ver;
  char id[24];
  char name[41];
  char sn[21];
  uint8_t keyLen;
  uint8_t key[yeelock::KEY_MAX];
};

struct Settings {
  uint8_t ver;
  uint8_t scanS;      // BLE scan time when looking for a lock
  uint8_t connS;      // connect timeout
  uint8_t batteryH;   // idle battery refresh, 0 = off
};

struct Found {
  char sn[21];
  int rssi;
  char addr[18];
  uint8_t addrType;
};

struct Notif {
  uint8_t len;
  uint8_t data[24];
};

QueueHandle_t g_ntf = nullptr;

void onNotify(NimBLERemoteCharacteristic*, uint8_t* data, size_t len, bool) {
  Notif n;
  n.len = (uint8_t)(len > sizeof n.data ? sizeof n.data : len);
  memcpy(n.data, data, n.len);
  if (g_ntf) xQueueSend(g_ntf, &n, 0);
}

class Yeelock;
Yeelock* g_self = nullptr;

// ---------------------------------------------------------------------------------------------

class Yeelock : public Module {
 public:
  const char* id() const override { return MOD_ID; }
  const char* name() const override { return "Yeelock locks"; }
  const char* version() const override { return "1.0.0"; }
  const char* icon() const override { return "lock"; }

  void begin() override {
    g_self = this;
    memset(locks_, 0, sizeof locks_);
    set_ = Settings{1, 5, 10, 12};
    load();
    g_ntf = xQueueCreate(8, sizeof(Notif));
    if (!ble::begin()) LOGE(MOD_ID, "BLE is not available: locks can't be reached");
  }

  void loop() override;

  // ---- entities ------------------------------------------------------------------------------
  void describe(JsonArray out) override {
    for (auto& l : locks_) {
      if (!l.used) continue;
      JsonObject e = out.add<JsonObject>();
      String eid = entityId(l);
      e["id"] = eid;
      e["module"] = MOD_ID;
      e["type"] = "lock";
      e["name"] = l.name;
      JsonArray a = e["actions"].to<JsonArray>();
      for (int k = 0; k < N_ENTITY_ACTIONS; k++) a.add(kActNames[k]);
      JsonArray at = e["attrs"].to<JsonArray>();
      JsonObject b = at.add<JsonObject>();
      b["key"] = "battery";
      b["label"] = "Battery";
      b["type"] = "number";
      b["unit"] = "%";
      b["min"] = 0;
      b["max"] = 100;
      JsonObject r = at.add<JsonObject>();
      r["key"] = "rssi";
      r["label"] = "Signal";
      r["type"] = "number";
      r["unit"] = "dBm";
      JsonArray c = e["confirm"].to<JsonArray>();
      c.add("open");
      c.add("unlock");
    }
  }

  void state(JsonObject out) override {
    for (auto& l : locks_)
      if (l.used) fillState(l, out[entityId(l)].to<JsonObject>());
  }

  bool stateOf(const char* eid, JsonObject out) override {
    Lock* l = byEntity(eid);
    if (!l) return false;
    fillState(*l, out);
    return true;
  }

  CommandResult command(const char* eid, const char* action, JsonObjectConst) override {
    Lock* l = byEntity(eid);
    if (!l) return CommandResult::fail(404, "unknown entity");
    int act = parseAction(action);
    if (act < 0) return CommandResult::fail(400, "unknown action (open, unlock, lock, refresh)");
    if (!l->keyLen) return CommandResult::fail(409, "this lock has no sign key");
    if (act != A_REFRESH && !clockSet())
      return CommandResult::fail(409, "the gateway's clock is not set (Yeelock needs the time)");
    if (!ble::available()) return CommandResult::fail(409, "BLE is not available");
    char job[12];
    jobs::create(eid, kActNames[act], job);
    if (!submitAction(*l, (Act)act, job)) {
      jobs::finish(job, false, "busy");
      return CommandResult::fail(409, "busy: too many BLE jobs waiting");
    }
    return CommandResult::accepted(job);
  }

  void overview(JsonObject out) override {
    size_t n = 0, low = 0, off = 0, bad = 0;
    for (auto& l : locks_) {
      if (!l.used) continue;
      n++;
      if (l.battery >= 0 && l.battery < 20) low++;
      if (!l.available) off++;
      if (l.problem == P_WRONG_KEY) bad++;
    }
    char t[64];
    if (!n) snprintf(t, sizeof t, "No locks yet");
    else snprintf(t, sizeof t, "%u lock%s%s", (unsigned)n, n == 1 ? "" : "s",
                  bad ? ", wrong sign key" : off ? ", some unreachable" : low ? ", battery low" : "");
    out["text"] = t;
    out["level"] = !n ? "info" : (off || bad) ? "crit" : low ? "warn" : "ok";
    out["count"] = n;
  }

  // ---- settings ------------------------------------------------------------------------------
  void settingsSchema(JsonObject s) override {
    JsonArray f = s["settings"].to<JsonArray>();
    field(f, "scan_s", "Scan time", "number", "How long to look for a lock whose address is not known yet.", 2, 30, "s");
    field(f, "conn_s", "Connect timeout", "number", "Give up connecting after this long.", 3, 30, "s");
    field(f, "battery_h", "Battery check", "number", "Read every lock's battery this often when idle (0 = never).", 0, 168, "h");

    JsonObject c = s["collection"].to<JsonObject>();
    c["key"] = "locks";
    c["title"] = "Locks";
    c["item"] = "lock";
    c["max"] = MAX_LOCKS;
    c["entity_prefix"] = "yeelock.";
    JsonArray it = c["fields"].to<JsonArray>();
    JsonObject n = it.add<JsonObject>();
    n["key"] = "name"; n["label"] = "Name"; n["type"] = "text"; n["required"] = true; n["max"] = 40;
    n["placeholder"] = "Front drawer";
    JsonObject i = it.add<JsonObject>();
    i["key"] = "id"; i["label"] = "ID"; i["type"] = "slug"; i["max"] = 20; i["create_only"] = true;
    i["help"] = "Part of the entity id yeelock.<id>. Leave empty to derive it from the name.";
    JsonObject sn = it.add<JsonObject>();
    sn["key"] = "sn"; sn["label"] = "Serial number"; sn["type"] = "text"; sn["required"] = true; sn["max"] = 20;
    sn["pattern"] = "^(EL_)?[A-Za-z0-9]{4,20}$";
    sn["help"] = "As on the lock's label, or the BLE name EL_<SN> without EL_.";
    JsonObject k = it.add<JsonObject>();
    k["key"] = "key"; k["label"] = "BLE sign key"; k["type"] = "secret"; k["required"] = true; k["max"] = 100;
    k["pattern"] = "^[0-9A-Fa-f :-]{16,100}$";
    k["help"] = "ble_sign_key in hex (8-32 bytes), from yeehack fetch. Leave empty to keep the stored key.";
    JsonObject d = c["discover"].to<JsonObject>();
    d["label"] = "Scan for locks";
    d["hint"] = "Nearby Yeelocks (EL_...) appear here; pick one to fill the serial number.";

    // A key test the generic UI offers on every item and runs after an add.
    JsonObject ck = c["check"].to<JsonObject>();
    ck["call"] = "check";
    ck["label"] = "Check";
    ck["hint"] = "Connects, reads the battery and sends only a time sync: never unlocks.";

#if GW_YEELOCK_CLOUD
    // "Import from my Yeelock account": a form, then a pick list of the account's locks.
    JsonObject im = c["import"].to<JsonObject>();
    im["call"] = "cloud";
    im["label"] = "Import from my Yeelock account";
    im["help"] = "The gateway asks the Yeelock cloud (api.yeeloc.com, verified HTTPS) once for your "
                 "locks and their sign keys. Your password is used for this one request and never "
                 "stored. Adding a lock by hand (S/N + key) works without it.";
    JsonArray imf = im["fields"].to<JsonArray>();
    JsonObject z = imf.add<JsonObject>();
    z["key"] = "zone"; z["label"] = "Country code"; z["type"] = "text"; z["required"] = true;
    z["max"] = 4; z["pattern"] = "^[0-9]{1,4}$"; z["placeholder"] = "420";
    z["help"] = "Your phone's country calling code without +.";
    JsonObject u = imf.add<JsonObject>();
    u["key"] = "username"; u["label"] = "Phone number"; u["type"] = "text"; u["required"] = true;
    u["max"] = 64; u["placeholder"] = "123456789"; u["help"] = "Without the country code.";
    JsonObject pw = imf.add<JsonObject>();
    pw["key"] = "password"; pw["label"] = "Yeelock password"; pw["type"] = "password"; pw["required"] = true;
    pw["max"] = 128;
#endif
  }

  void settingsGet(JsonObject v) override {
    v["scan_s"] = set_.scanS;
    v["conn_s"] = set_.connS;
    v["battery_h"] = set_.batteryH;
  }

  bool settingsSet(JsonObjectConst in, String& err) override {
    Settings s = set_;
    if (!num(in, "scan_s", 2, 30, &s.scanS, err) || !num(in, "conn_s", 3, 30, &s.connS, err) ||
        !num(in, "battery_h", 0, 168, &s.batteryH, err))
      return false;
    set_ = s;
    save();
    return true;
  }

  // ---- items (the locks) ---------------------------------------------------------------------
  void itemsGet(JsonArray out) override {
    for (auto& l : locks_) {
      if (!l.used) continue;
      JsonObject o = out.add<JsonObject>();
      o["id"] = l.id;
      o["name"] = l.name;
      o["sn"] = l.sn;
      o["key"] = keyMask(l);
      o["entity"] = entityId(l);
      o["problem"] = kProblemNames[l.problem];
      o["in_range"] = foundSn(l.sn) != nullptr;
    }
  }

  bool itemSave(const char* itemId, JsonObjectConst in, String& savedId, String& err) override {
    bool okN, okS, okK, okI;
    const char* nm = jstr(in, "name", 40, &okN);
    const char* sn = jstr(in, "sn", 23, &okS);
    const char* key = jstr(in, "key", 100, &okK);
    const char* wantId = jstr(in, "id", 20, &okI);
    if (!okN || !*nm || !isCleanText(nm, 40)) { err = "name: 1 to 40 characters"; return false; }
    if (strncmp(sn, "EL_", 3) == 0) sn += 3;
    if (!okS || !yeelock::isValidSn(sn)) { err = "serial number: 4 to 20 letters and digits"; return false; }
    uint8_t k[yeelock::KEY_MAX];
    size_t kl = 0;
    if (!okK) { err = "sign key: too long"; return false; }
    if (*key && !(kl = yeelock::parseSignKey(key, k))) { err = "sign key: hex of 8 to 32 bytes"; return false; }
    Lock* l;
    if (itemId) {
      l = byId(itemId);
      if (!l) { err = "no such lock"; return false; }
    } else {
      if (!kl) { err = "sign key: required"; return false; }
      l = freeSlot();
      if (!l) { err = "at most 10 locks per gateway"; return false; }
    }
    for (auto& o : locks_)
      if (o.used && &o != l && strcasecmp(o.sn, sn) == 0) { err = String("serial number already used by ") + o.name; return false; }
    if (!itemId) {
      char id[24];
      if (*wantId) {
        if (!okI || !isSlug(wantId, 20)) { err = "id: a-z, 0-9, _ and -, up to 20"; return false; }
        if (byId(wantId)) { err = "id already used"; return false; }
        copyStr(id, sizeof id, wantId);
      } else {
        makeId(nm, id, sizeof id);
      }
      memset(l, 0, sizeof *l);
      l->used = true;
      copyStr(l->id, sizeof l->id, id);
      l->battery = -1;
      l->available = true;
    }
    bool snChanged = strcmp(l->sn, sn) != 0;
    copyStr(l->name, sizeof l->name, nm);
    copyStr(l->sn, sizeof l->sn, sn);
    if (kl) {
      memcpy(l->key, k, kl);
      l->keyLen = (uint8_t)kl;
      l->problem = P_NONE;
    }
    if (snChanged) l->addr[0] = 0;  // look it up again
    secureZero(k, sizeof k);
    save();
    savedId = l->id;
    LOGI(MOD_ID, "lock %s %s (SN %s)", l->id, itemId ? "updated" : "added", l->sn);
    events::emitEntity(entityId(*l).c_str(), itemId ? "state" : "added");
    // A new lock or a new key: check it right away (connect, battery, time sync; never unlocks).
    if (!itemId || kl || snChanged) startCheck(*l, nullptr);
    return true;
  }

  // Queues a key check; the result lands in STATE.last (action "check"). jobOut may be null.
  bool startCheck(Lock& l, String* jobOut) {
    if (!ble::available() || !l.keyLen) return false;
    char job[12];
    String eid = entityId(l);
    jobs::create(eid.c_str(), "check", job);
    if (!submitAction(l, A_CHECK, job)) {
      jobs::finish(job, false, "busy");
      return false;
    }
    if (jobOut) *jobOut = job;
    return true;
  }

  bool itemDelete(const char* itemId, String& err) override {
    Lock* l = byId(itemId);
    if (!l) { err = "no such lock"; return false; }
    String eid = entityId(*l);
    LOGI(MOD_ID, "lock %s deleted", l->id);
    secureZero(l, sizeof *l);
    save();
    events::emitEntity(eid.c_str(), "removed");
    return true;
  }

  bool discoverStart(String& err) override;

  void discoverGet(JsonObject out) override {
    out["running"] = scanning_;
    out["at"] = scanAt_;
    JsonArray r = out["results"].to<JsonArray>();
    for (size_t i = 0; i < nFound_; i++) {
      const Found& f = found_[i];
      JsonObject o = r.add<JsonObject>();
      o["sn"] = f.sn;
      o["label"] = String("EL_") + f.sn;
      o["detail"] = String(f.rssi) + " dBm";
      o["rssi"] = f.rssi;
      Lock* l = bySn(f.sn);
      o["known"] = l != nullptr;
      if (l) o["known_as"] = l->name;
      const yeelock::CloudLock* c = cloudSn(f.sn);
      if (c) o["in_account"] = c->name;  // matched to a lock fetched from the cloud
    }
  }

  int webCall(const char* name, bool post, JsonObjectConst in, JsonObject out, String& err) override;

  // ---- CLI -----------------------------------------------------------------------------------
  void cliHelp(Print& p) override {
    p.println("yeelock list                               the locks, with battery and last result");
    p.println("yeelock add <name> <SN> <signkeyhex>       add a lock (quote a name with spaces)");
    p.println("yeelock key <id> <signkeyhex>              replace a lock's sign key");
    p.println("yeelock del <id>                           delete a lock");
    p.println("yeelock scan                               look for nearby locks (EL_...)");
    p.println("yeelock do <id> open|unlock|lock|battery   run an action now");
    p.println("yeelock check <id>                         test reach + key (battery, time sync; never unlocks)");
#if GW_YEELOCK_CLOUD
    p.println("yeelock fetch <zone> <username>            list your Yeelock account's locks (asks the password)");
    p.println("yeelock import <SN>... | all               add fetched locks (with their sign keys)");
#endif
  }

  bool cliCommand(Print& p, int argc, char** argv) override;

  const cli::SecretRule* cliSecrets(size_t* n) override {
    static const cli::SecretRule r[] = {{"yeelock", "add", 4}, {"yeelock", "key", 3}};
    *n = 2;
    return r;
  }

  // ---- called from the BLE jobs ----------------------------------------------------------------
  void runAction(const char* lockId, Act act, const char* job);
  void runScan(uint32_t seconds);
  void scanDone(const Found* f, size_t n);
  void jobDropped(const char* lockId) {
    Guard g;
    Lock* l = byId(lockId);
    if (l && l->pending) l->pending--;
  }

 private:
  Lock locks_[MAX_LOCKS];
  Settings set_;
  Found found_[MAX_FOUND];
  size_t nFound_ = 0;
  bool scanning_ = false;
  uint32_t scanAt_ = 0;
  uint32_t lastTick_ = 0;

  // Cloud import: results (with sign keys) live in RAM only, for CLOUD_KEEP_S at most.
  yeelock::CloudLock cloud_[MAX_LOCKS * 2];
  int nCloud_ = 0;            // -1 = the last fetch failed
  bool cloudRunning_ = false;
  uint32_t cloudAt_ = 0;      // monoS() of the result
  String cloudErr_;
  uint32_t cloudTries_[CLOUD_TRIES] = {0};

 public:
  bool cloudStart(const char* zone, const char* user, const char* pass, String& err);
  void cloudFinished(yeelock::CloudLock* got, int n, const String& err);
  void cloudWipe() {
    secureZero(cloud_, sizeof cloud_);
    nCloud_ = 0;
    cloudErr_ = "";
  }
  int cloudImport(const char* const* sns, size_t n, bool all, String& err, Print* p);

 private:
  const Found* foundSn(const char* sn) const {
    for (size_t i = 0; i < nFound_; i++)
      if (strcasecmp(found_[i].sn, sn) == 0) return &found_[i];
    return nullptr;
  }
  const yeelock::CloudLock* cloudSn(const char* sn) const {
    for (int i = 0; i < nCloud_; i++)
      if (strcasecmp(cloud_[i].sn, sn) == 0) return &cloud_[i];
    return nullptr;
  }
  void cloudJson(JsonObject out);

  static String entityId(const Lock& l) { return String(MOD_ID) + "." + l.id; }

  static const char* keyMask(const Lock& l) {
    static char m[16];
    if (!l.keyLen) return "not set";
    char hex[2 * yeelock::KEY_MAX + 1];
    toHex(l.key, l.keyLen, hex);
    maskSecret(hex, m, sizeof m);
    secureZero(hex, sizeof hex);
    return m;
  }

  static int parseAction(const char* a) {
    for (int i = 0; i < 4; i++)
      if (strcmp(a, kActNames[i]) == 0) return i;
    if (strcmp(a, "battery") == 0) return A_REFRESH;  // the CLI's word for it
    return -1;
  }

  Lock* byId(const char* id) {
    if (!id) return nullptr;
    for (auto& l : locks_)
      if (l.used && strcmp(l.id, id) == 0) return &l;
    return nullptr;
  }
  Lock* bySn(const char* sn) {
    for (auto& l : locks_)
      if (l.used && strcasecmp(l.sn, sn) == 0) return &l;
    return nullptr;
  }
  Lock* byEntity(const char* eid) {
    size_t n = strlen(MOD_ID);
    if (!eid || strncmp(eid, MOD_ID, n) != 0 || eid[n] != '.') return nullptr;
    return byId(eid + n + 1);
  }
  Lock* freeSlot() {
    for (auto& l : locks_)
      if (!l.used) return &l;
    return nullptr;
  }

  void makeId(const char* name, char* out, size_t cap) {
    char base[21];
    size_t n = 0;
    bool us = false;
    for (const char* p = name; *p && n < 16; p++) {
      char c = *p;
      if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
      bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
      if (ok) { base[n++] = c; us = false; }
      else if (n && !us) { base[n++] = '_'; us = true; }
    }
    while (n && base[n - 1] == '_') n--;
    base[n] = 0;
    if (!n) copyStr(base, sizeof base, "lock");
    copyStr(out, cap, base);
    for (int i = 2; byId(out) && i < 100; i++) snprintf(out, cap, "%s_%d", base, i);
  }

  void fillState(const Lock& l, JsonObject st) {
    st["available"] = l.available;
    st["value"] = l.value == V_LOCKED ? "locked" : l.value == V_UNLOCKED ? "unlocked" : "unknown";
    st["busy"] = l.pending > 0;
    if (l.problem) st["problem"] = kProblemNames[l.problem];  // additive, e.g. "wrong_key"
    JsonObject a = st["attrs"].to<JsonObject>();
    if (l.battery >= 0) a["battery"] = l.battery; else a["battery"] = nullptr;
    if (l.rssi) a["rssi"] = l.rssi;
    if (l.haveLast) {
      JsonObject last = st["last"].to<JsonObject>();
      last["action"] = kActNames[l.lastAct];
      last["ok"] = l.lastOk;
      last["at"] = l.lastAt;
      last["msg"] = l.lastMsg;
      if (l.lastProblem) last["problem"] = kProblemNames[l.lastProblem];  // additive
    } else {
      st["last"] = nullptr;
    }
  }

  static void field(JsonArray f, const char* key, const char* label, const char* type, const char* help,
                    int mn, int mx, const char* unit) {
    JsonObject o = f.add<JsonObject>();
    o["key"] = key;
    o["label"] = label;
    o["type"] = type;
    o["help"] = help;
    o["min"] = mn;
    o["max"] = mx;
    o["unit"] = unit;
  }

  static bool num(JsonObjectConst in, const char* key, int mn, int mx, uint8_t* out, String& err) {
    JsonVariantConst v = in[key];
    if (v.isNull()) return true;  // unchanged
    if (!v.is<int>()) { err = String(key) + ": a number"; return false; }
    int x = v.as<int>();
    if (x < mn || x > mx) { err = String(key) + ": " + mn + " to " + mx; return false; }
    *out = (uint8_t)x;
    return true;
  }

  bool submitAction(Lock& l, Act act, const char* job);

  // ---- NVS ---------------------------------------------------------------------------------
  void load() {
    Preferences p;
    String ns = nvsNamespace();
    if (!p.begin(ns.c_str(), false)) return;
    if (p.getBytesLength("cfg") == sizeof(Settings)) {
      Settings s;
      p.getBytes("cfg", &s, sizeof s);
      if (s.ver == 1) set_ = s;
    }
    size_t n = 0;
    for (size_t i = 0; i < MAX_LOCKS; i++) {
      char k[4] = {'l', (char)('0' + i), 0};
      if (p.getBytesLength(k) != sizeof(Persist)) continue;
      Persist r;
      p.getBytes(k, &r, sizeof r);
      if (r.ver != 1 || !isSlug(r.id, 20) || r.keyLen > yeelock::KEY_MAX) continue;
      r.name[sizeof r.name - 1] = r.sn[sizeof r.sn - 1] = 0;
      Lock& l = locks_[n++];
      l.used = true;
      copyStr(l.id, sizeof l.id, r.id);
      copyStr(l.name, sizeof l.name, r.name);
      copyStr(l.sn, sizeof l.sn, r.sn);
      memcpy(l.key, r.key, r.keyLen);
      l.keyLen = r.keyLen;
      l.battery = -1;
      l.available = true;
      secureZero(&r, sizeof r);
    }
    p.end();
    LOGI(MOD_ID, "%u lock(s) configured", (unsigned)n);
  }

  void save() {
    Preferences p;
    String ns = nvsNamespace();
    if (!p.begin(ns.c_str(), false)) { LOGE(MOD_ID, "NVS open failed"); return; }
    p.putBytes("cfg", &set_, sizeof set_);
    size_t n = 0;
    for (auto& l : locks_) {
      if (!l.used) continue;
      Persist r;
      memset(&r, 0, sizeof r);
      r.ver = 1;
      copyStr(r.id, sizeof r.id, l.id);
      copyStr(r.name, sizeof r.name, l.name);
      copyStr(r.sn, sizeof r.sn, l.sn);
      r.keyLen = l.keyLen;
      memcpy(r.key, l.key, l.keyLen);
      char k[4] = {'l', (char)('0' + n), 0};
      p.putBytes(k, &r, sizeof r);
      secureZero(&r, sizeof r);
      n++;
    }
    for (size_t i = n; i < MAX_LOCKS; i++) {
      char k[4] = {'l', (char)('0' + i), 0};
      if (p.isKey(k)) p.remove(k);
    }
    p.end();
  }
};

// ---- BLE jobs ---------------------------------------------------------------------------------------

class ActionJob : public ble::Job {
 public:
  ActionJob(const char* lockId, Act act, const char* job) : act_(act) {
    copyStr(lock_, sizeof lock_, lockId);
    copyStr(job_, sizeof job_, job);
  }
  void run() override { g_self->runAction(lock_, act_, job_); }
  void dropped() override { g_self->jobDropped(lock_); }

 private:
  char lock_[24];
  char job_[12];
  Act act_;
};

class ScanJob : public ble::Job {
 public:
  explicit ScanJob(uint32_t s) : s_(s) {}
  void run() override { g_self->runScan(s_); }

 private:
  uint32_t s_;
};

bool Yeelock::submitAction(Lock& l, Act act, const char* job) {
  if (!ble::submit(new ActionJob(l.id, act, job))) return false;
  l.pending++;
  if (job && *job) events::emitEntity(entityId(l).c_str(), "busy", job);
  return true;
}

bool Yeelock::discoverStart(String& err) {
  if (scanning_) return true;
  if (!ble::available()) { err = "BLE is not available"; return false; }
  uint32_t s = set_.scanS < 5 ? 5 : set_.scanS;
  if (!ble::submit(new ScanJob(s * 2))) { err = "busy: too many BLE jobs waiting"; return false; }
  scanning_ = true;
  return true;
}

void Yeelock::loop() {
  // Once a minute: an idle battery check for at most one lock (only while BLE is idle).
  if (millis() - lastTick_ < 60000) return;
  lastTick_ = millis();
  Guard g;
  // Fetched cloud keys don't linger in RAM.
  if (nCloud_ && !cloudRunning_ && monoS() - cloudAt_ > CLOUD_KEEP_S) cloudWipe();
  if (!set_.batteryH || ble::busy() || ble::queued()) return;
  uint32_t every = (uint32_t)set_.batteryH * 3600UL * 1000UL;
  for (auto& l : locks_) {
    if (!l.used || !l.keyLen || l.pending) continue;
    bool due = l.lastBatteryMs == 0 ? millis() > 120000 : millis() - l.lastBatteryMs > every;
    if (!due) continue;
    l.lastBatteryMs = millis();  // don't retry every minute if it fails
    submitAction(l, A_REFRESH, "");
    return;
  }
}

// Scans for EL_* advertisements; records them in found_ and caches known locks' addresses.
// Runs on the BLE task. Returns true if `wantSn` (may be null) was seen.
static bool bleScan(Yeelock* self, uint32_t seconds, const char* wantSn, Found* hit);

struct LockCopy {
  char sn[21];
  uint8_t key[yeelock::KEY_MAX];
  uint8_t keyLen;
  char addr[18];
  uint8_t addrType;
  uint8_t scanS, connS;
};

static String hexOf(const uint8_t* d, size_t n) {
  char buf[2 * 24 + 1];
  if (n > 24) n = 24;
  toHex(d, n, buf);
  return String(buf);
}

void Yeelock::runAction(const char* lockId, Act act, const char* job) {
  LockCopy lc;
  {
    Guard g;
    Lock* l = byId(lockId);
    if (!l) {
      if (*job) jobs::finish(job, false, "the lock was deleted");
      return;
    }
    copyStr(lc.sn, sizeof lc.sn, l->sn);
    memcpy(lc.key, l->key, l->keyLen);
    lc.keyLen = l->keyLen;
    copyStr(lc.addr, sizeof lc.addr, l->addr);
    lc.addrType = l->addrType;
    lc.scanS = set_.scanS;
    lc.connS = set_.connS;
  }
  if (*job) jobs::started(job);

  bool ok = false;
  String msg;
  int battery = -1, rssi = 0;
  bool reached = false;
  Problem problem = P_NONE;
  yeelock::Outcome oc;
  // Mode byte for the outcome: 0 open, 1 unlock, 2 lock, 3 time-sync check.
  const uint8_t mode = act == A_CHECK ? 3 : (uint8_t)act;

  for (int attempt = 0; attempt < 2 && !reached; attempt++) {
    if (!lc.addr[0]) {
      Found f;
      if (!bleScan(this, lc.scanS, lc.sn, &f)) {
        msg = "lock not found (in range? right serial number?)";
        problem = P_NOT_FOUND;
        break;
      }
      copyStr(lc.addr, sizeof lc.addr, f.addr);
      lc.addrType = f.addrType;
      rssi = f.rssi;
    }
    NimBLEClient* cl = NimBLEDevice::createClient();
    cl->setConnectTimeout(lc.connS);  // seconds in NimBLE-Arduino 1.4 (ms in 2.x)
    NimBLEAddress addr(std::string(lc.addr), lc.addrType);
    if (!cl->connect(addr)) {
      NimBLEDevice::deleteClient(cl);
      msg = "could not connect (out of range, or the Yeelock app is connected)";
      problem = P_CONNECT;
      lc.addr[0] = 0;  // the cached address may be stale: rescan once
      continue;
    }
    reached = true;
    problem = P_NONE;
    if (!rssi) rssi = cl->getRssi();

    // The battery is read on every connection.
    NimBLERemoteService* bs = cl->getService(NimBLEUUID(kUuidBattSvc));
    if (bs) {
      NimBLERemoteCharacteristic* bc = bs->getCharacteristic(NimBLEUUID(kUuidBattChr));
      if (bc && bc->canRead()) {
        std::string v = bc->readValue();  // NimBLEAttValue in 1.4 converts to std::string
        if (!v.empty()) battery = (uint8_t)v[0];
      }
    }

    if (act == A_REFRESH) {
      ok = battery >= 0;
      msg = ok ? String(String("battery ") + battery + " %") : String("no battery reading");
    } else {
      NimBLERemoteCharacteristic *cmd = nullptr, *ntf = nullptr;
      NimBLEUUID uCmd(kUuidCmd), uNtf(kUuidNotify);
      std::vector<NimBLERemoteService*>* svcs = cl->getServices(true);
      for (NimBLERemoteService* s : *svcs) {
        std::vector<NimBLERemoteCharacteristic*>* chs = s->getCharacteristics(true);
        for (NimBLERemoteCharacteristic* c : *chs) {
          if (c->getUUID() == uCmd) cmd = c;
          else if (c->getUUID() == uNtf) ntf = c;
        }
      }
      if (!cmd || !ntf) {
        msg = "not a Yeelock (command characteristics missing)";
        problem = P_PROTOCOL;
      } else if (!ntf->subscribe(true, onNotify)) {
        msg = "could not subscribe to notifications";
        problem = P_PROTOCOL;
      } else {
        xQueueReset(g_ntf);
        const bool resp = cmd->canWrite();  // write with response when the lock offers it
        uint8_t pkt[yeelock::PACKET_LEN];
        String codes;
        Notif n;
        bool done = false;
        auto note = [&](const Notif& x) {
          yeelock::Notif k = yeelock::decodeNotif(x.data, x.len);
          LOGD(MOD_ID, "notification %s (%s)", hexOf(x.data, x.len).c_str(), yeelock::notifName(k));
          if (codes.length() < 48) {
            if (codes.length()) codes += ' ';
            codes += yeelock::notifName(k);
          }
          return k;
        };
        // Time sync first (and, for a check, only that: a check never unlocks).
        auto sendTime = [&]() -> bool {
          yeelock::buildTimePacket(pkt, nowUnix(), lc.key, lc.keyLen);
          return cmd->writeValue(pkt, sizeof pkt, resp);
        };
        auto sendAction = [&]() -> bool {
          yeelock::buildActionPacket(pkt, nowUnix(), (yeelock::Mode)act, lc.key, lc.keyLen);
          return cmd->writeValue(pkt, sizeof pkt, resp);
        };
        bool wrote = sendTime();
        if (wrote && mode != 3) {
          // Let the time packet's own notification (if any) arrive before the action.
          while (!done && xQueueReceive(g_ntf, &n, pdMS_TO_TICKS(300)) == pdTRUE) {
            yeelock::Notif k = note(n);
            if (k == yeelock::Notif::SignInvalid || k == yeelock::Notif::InvalidOpcode) done = oc.feed(k, mode);
          }
          if (!done) wrote = sendAction();
        }
        if (!wrote) {
          msg = "write failed";
          problem = P_PROTOCOL;
        } else {
          bool retried = false;
          // Open: the lock unlocks, waits, re-locks; allow for the re-lock after UNLOCK_CMP.
          uint32_t deadline = millis() + (mode == 3 ? 1500 : ANSWER_WAIT_MS);
          while (!done && (int32_t)(deadline - millis()) > 0) {
            if (xQueueReceive(g_ntf, &n, pdMS_TO_TICKS(deadline - millis())) != pdTRUE) break;
            yeelock::Notif k = note(n);
            if (k == yeelock::Notif::TimeRequest) {
              oc.feed(k, mode);
              if (retried || mode == 3) continue;
              retried = true;  // the lock asks for the time: once more, time then action
              if (!sendTime()) break;
              delay(300);
              if (!sendAction()) break;
              deadline = millis() + ANSWER_WAIT_MS;
              continue;
            }
            done = oc.feed(k, mode);
            if (mode == 0 && k == yeelock::Notif::UnlockDone) deadline = millis() + 8000;
          }
          if (mode == 3) {
            // A check: only a rejection is conclusive; silence after a time sync is normal.
            ok = !oc.signInvalid && !oc.invalidOpcode;
            msg = oc.signInvalid ? "reachable, but the sign key is WRONG (TX_SIGN_INVALID)"
                  : oc.invalidOpcode ? "reachable, but the lock rejected the time sync"
                  : battery >= 0 ? String(String("reachable, key OK, battery ") + battery + " %")
                                 : String("reachable, key OK");
          } else {
            ok = oc.ok();
            msg = oc.message(mode);
          }
          if (oc.signInvalid) problem = P_WRONG_KEY;
          else if (!ok) problem = P_PROTOCOL;
          if (codes.length() && mode != 3) msg += String(" [") + codes + "]";
        }
        secureZero(pkt, sizeof pkt);
      }
    }
    if (cl->isConnected()) cl->disconnect();
    NimBLEDevice::deleteClient(cl);
  }
  secureZero(lc.key, sizeof lc.key);

  {
    Guard g;
    Lock* l = byId(lockId);
    if (l) {
      if (l->pending) l->pending--;
      l->available = reached;
      if (reached) {
        copyStr(l->addr, sizeof l->addr, lc.addr);
        l->addrType = lc.addrType;
      } else {
        l->addr[0] = 0;
      }
      if (rssi) l->rssi = rssi;
      if (battery >= 0) {
        l->battery = battery;
        l->lastBatteryMs = millis();
      }
      // The value follows what the lock reported (UNLOCK_CMP / LOCK_CMP); an open ends locked.
      if (oc.locked) l->value = V_LOCKED;
      else if (oc.unlocked) l->value = act == A_OPEN ? V_LOCKED : V_UNLOCKED;
      else if (ok && act == A_UNLOCK) l->value = V_UNLOCKED;
      else if (ok && (act == A_LOCK || act == A_OPEN)) l->value = V_LOCKED;
      if (problem == P_WRONG_KEY || act == A_CHECK) l->problem = problem;
      else if (ok) l->problem = P_NONE;
      // Internal battery checks (no job) don't overwrite the user's last result.
      if (*job) {
        l->haveLast = true;
        l->lastAct = act;
        l->lastOk = ok;
        l->lastAt = nowUnix();
        l->lastProblem = problem;
        copyStr(l->lastMsg, sizeof l->lastMsg, msg.c_str());
      }
    }
  }
  if (*job) jobs::finish(job, ok, msg.c_str());
  else {
    Guard g;
    Lock* l = byId(lockId);
    if (l) events::emitEntity(entityId(*l).c_str(), "state");
  }
}

void Yeelock::scanDone(const Found* f, size_t n) {
  Guard g;
  for (size_t i = 0; i < n; i++) {
    // Cache the address of configured locks: the next command skips the scan.
    Lock* l = bySn(f[i].sn);
    if (l) {
      copyStr(l->addr, sizeof l->addr, f[i].addr);
      l->addrType = f[i].addrType;
      l->rssi = f[i].rssi;
    }
    // Merge into the discovery list (the newest RSSI wins).
    size_t k = 0;
    while (k < nFound_ && strcasecmp(found_[k].sn, f[i].sn) != 0) k++;
    if (k == nFound_) {
      if (nFound_ >= MAX_FOUND) continue;
      nFound_++;
    }
    found_[k] = f[i];
  }
}

void Yeelock::runScan(uint32_t seconds) {
  {
    Guard g;
    nFound_ = 0;  // a fresh list for the web UI
  }
  LOGI(MOD_ID, "scanning %lu s for Yeelocks...", (unsigned long)seconds);
  bleScan(this, seconds, nullptr, nullptr);
  Guard g;
  scanning_ = false;
  scanAt_ = nowUnix();
  LOGI(MOD_ID, "scan done: %u Yeelock(s) nearby", (unsigned)nFound_);
  for (size_t i = 0; i < nFound_; i++) {
    Lock* l = bySn(found_[i].sn);
    LOGI(MOD_ID, "  EL_%s  %d dBm%s%s", found_[i].sn, found_[i].rssi, l ? "  = " : "", l ? l->name : "");
  }
}

// ---- cloud import ------------------------------------------------------------------------------

struct CloudReq {
  char zone[8];
  char user[72];
  char pass[136];
};

static void cloudTask(void* arg) {
  CloudReq* r = (CloudReq*)arg;
  const size_t MAXC = MAX_LOCKS * 2;
  yeelock::CloudLock* got = (yeelock::CloudLock*)bigAlloc(sizeof(yeelock::CloudLock) * MAXC);
  String err;
  int n = -1;
  if (got) n = yeelock::cloudFetch(r->zone, r->user, r->pass, got, MAXC, err);
  else err = "out of memory";
  secureZero(r, sizeof *r);
  free(r);
  g_self->cloudFinished(got, n, err);
  if (got) {
    secureZero(got, sizeof(yeelock::CloudLock) * MAXC);
    bigFree(got);
  }
  vTaskDelete(nullptr);
}

bool Yeelock::cloudStart(const char* zone, const char* user, const char* pass, String& err) {
#if GW_YEELOCK_CLOUD
  if (cloudRunning_) { err = "an import is already running"; return false; }
  if (!yeelock::validZone(zone)) { err = "country code: 1 to 4 digits, without +"; return false; }
  if (!yeelock::validUsername(user)) { err = "phone number: without the country code"; return false; }
  size_t pl = pass ? strlen(pass) : 0;
  if (pl < 1 || pl > 128) { err = "password: 1 to 128 characters"; return false; }
  // At most CLOUD_TRIES logins per 10 minutes (each try may count against the account).
  uint32_t now = monoS();
  size_t recent = 0, oldest = 0;
  for (size_t i = 0; i < CLOUD_TRIES; i++) {
    if (cloudTries_[i] && now - cloudTries_[i] < CLOUD_WINDOW_S) recent++;
    if (cloudTries_[i] < cloudTries_[oldest]) oldest = i;
  }
  if (recent >= CLOUD_TRIES) {
    uint32_t left = CLOUD_WINDOW_S - (now - cloudTries_[oldest]);
    err = String("too many tries: wait ") + (left / 60 + 1) + " min";
    return false;
  }
  cloudTries_[oldest] = now;
  CloudReq* r = (CloudReq*)calloc(1, sizeof(CloudReq));
  if (!r) { err = "out of memory"; return false; }
  copyStr(r->zone, sizeof r->zone, zone);
  copyStr(r->user, sizeof r->user, user);
  copyStr(r->pass, sizeof r->pass, pass);
  cloudWipe();
  cloudRunning_ = true;
  // TLS needs a deep stack; the task lives only for the two requests.
  if (xTaskCreate(cloudTask, "yl_cloud", 12288, r, 2, nullptr) != pdPASS) {
    secureZero(r, sizeof *r);
    free(r);
    cloudRunning_ = false;
    err = "could not start the import";
    return false;
  }
  LOGI(MOD_ID, "cloud import started (zone %s)", zone);  // never the username or password
  return true;
#else
  err = "this firmware was built without the cloud import";
  return false;
#endif
}

void Yeelock::cloudFinished(yeelock::CloudLock* got, int n, const String& err) {
  Guard g;
  cloudRunning_ = false;
  cloudAt_ = monoS();
  secureZero(cloud_, sizeof cloud_);
  if (n < 0) {
    nCloud_ = -1;
    cloudErr_ = err;
    return;
  }
  nCloud_ = n > (int)(MAX_LOCKS * 2) ? (int)(MAX_LOCKS * 2) : n;
  memcpy(cloud_, got, sizeof(yeelock::CloudLock) * nCloud_);
  cloudErr_ = "";
  for (int i = 0; i < nCloud_; i++) {
    const yeelock::CloudLock& c = cloud_[i];
    Lock* l = bySn(c.sn);
    LOGI(MOD_ID, "  account lock \"%s\" SN %s, key %s%s%s", c.name, c.sn, c.keyLen ? "set" : "MISSING",
         foundSn(c.sn) ? ", in range" : "", l ? ", already configured" : "");
  }
  if (nCloud_) LOGI(MOD_ID, "import with: yeelock import <SN>... | all (or in the web UI)");
}

void Yeelock::cloudJson(JsonObject out) {
  out["running"] = cloudRunning_;
  if (nCloud_ < 0) out["error"] = cloudErr_;
  out["age"] = cloudAt_ ? monoS() - cloudAt_ : 0;
  out["keep"] = CLOUD_KEEP_S;
  JsonArray r = out["results"].to<JsonArray>();
  for (int i = 0; i < nCloud_; i++) {
    const yeelock::CloudLock& c = cloud_[i];
    JsonObject o = r.add<JsonObject>();
    o["sn"] = c.sn;
    o["name"] = c.name;
    char hex[2 * yeelock::KEY_MAX + 1], m[16];
    if (c.keyLen) {
      toHex(c.key, c.keyLen, hex);
      o["key"] = maskSecret(hex, m, sizeof m);
      secureZero(hex, sizeof hex);
    } else {
      o["key"] = "not set";
    }
    o["has_key"] = c.keyLen > 0;
    Lock* l = bySn(c.sn);
    o["known"] = l != nullptr;
    if (l) o["known_as"] = l->name;
    const Found* f = foundSn(c.sn);
    o["in_range"] = f != nullptr;
    if (f) o["rssi"] = f->rssi;
  }
}

int Yeelock::cloudImport(const char* const* sns, size_t n, bool all, String& err, Print* p) {
  if (nCloud_ <= 0) { err = "nothing fetched (or it expired): fetch again"; return -1; }
  int added = 0;
  for (int i = 0; i < nCloud_; i++) {
    yeelock::CloudLock& c = cloud_[i];
    bool want = all;
    for (size_t k = 0; !want && k < n; k++) want = sns[k] && strcasecmp(sns[k], c.sn) == 0;
    if (!want) continue;
    if (!c.keyLen) {
      if (p) p->printf("  %s: the account has no sign key for it, skipped\n", c.sn);
      continue;
    }
    char hex[2 * yeelock::KEY_MAX + 1];
    toHex(c.key, c.keyLen, hex);
    JsonDocument d(jsonAlloc());
    Lock* l = bySn(c.sn);
    d["name"] = l ? l->name : c.name;
    d["sn"] = c.sn;
    d["key"] = hex;
    String id, e;
    bool ok = itemSave(l ? l->id : nullptr, d.as<JsonObjectConst>(), id, e);
    d.clear();
    secureZero(hex, sizeof hex);
    if (ok) {
      added++;
      if (p) p->printf("  %s: %s as %s\n", c.sn, l ? "key updated" : "added", id.c_str());
    } else {
      if (p) p->printf("  %s: %s\n", c.sn, e.c_str());
      if (!err.length()) err = String(c.sn) + ": " + e;
    }
  }
  if (added) {
    // Done with them: keys we keep are in NVS now; wipe the RAM copies.
    cloudWipe();
  }
  return added;
}

int Yeelock::webCall(const char* name, bool post, JsonObjectConst in, JsonObject out, String& err) {
  if (strcmp(name, "check") == 0 && post) {
    Lock* l = byId(jstr(in, "id", 23));
    if (!l) { err = "no such lock"; return 404; }
    if (!l->keyLen) { err = "this lock has no sign key"; return 409; }
    String job;
    if (!startCheck(*l, &job)) { err = "busy: too many BLE jobs waiting"; return 409; }
    out["job"] = job;
    return 202;
  }
  if (strcmp(name, "cloud") == 0) {
    if (post) {
      bool okP;
      const char* pass = jstr(in, "password", 128, &okP);
      if (!okP) { err = "password: too long"; return 400; }
      if (!cloudStart(jstr(in, "zone", 4), jstr(in, "username", 64), pass, err)) return err.startsWith("too many") ? 429 : 400;
      cloudJson(out);
      return 202;
    }
    cloudJson(out);
    return 200;
  }
  if (strcmp(name, "cloud_import") == 0 && post) {
    JsonArrayConst arr = in["sns"].as<JsonArrayConst>();
    const char* sns[MAX_LOCKS * 2];
    size_t n = 0;
    for (JsonVariantConst v : arr) {
      const char* s = v.as<const char*>();
      if (s && n < MAX_LOCKS * 2) sns[n++] = s;
    }
    if (!n) { err = "choose at least one lock"; return 400; }
    int added = cloudImport(sns, n, false, err, nullptr);
    if (added < 0) return 409;
    out["added"] = added;
    if (err.length()) out["warning"] = err;
    err = "";
    return 200;
  }
  if (strcmp(name, "cloud_clear") == 0 && post) {
    cloudWipe();
    return 200;
  }
  err = "not found";
  return 404;
}

// The CLI's `yeelock fetch`: the username and zone wait here while the password is typed.
static char g_fetchZone[8], g_fetchUser[72];

static void onFetchPassword(const char* pass, void*) {
  String err;
  if (!g_self->cloudStart(g_fetchZone, g_fetchUser, pass, err)) Serial.println(err);
  else Serial.println("asking the Yeelock cloud; the locks follow in the log");
  secureZero(g_fetchUser, sizeof g_fetchUser);
}

bool Yeelock::cliCommand(Print& p, int argc, char** argv) {
  const char* sub = argv[1];
  if (strcmp(sub, "list") == 0) {
    size_t n = 0;
    for (auto& l : locks_) {
      if (!l.used) continue;
      n++;
      char bat[8];
      if (l.battery >= 0) snprintf(bat, sizeof bat, "%d%%", l.battery);
      else copyStr(bat, sizeof bat, "?");
      p.printf("  %-16s %-22s SN %-10s key %-12s battery %-4s %s\n", l.id, l.name, l.sn, keyMask(l), bat,
               l.value == V_LOCKED ? "locked" : l.value == V_UNLOCKED ? "unlocked" : "");
      if (l.haveLast)
        p.printf("  %-16s last: %s %s - %s\n", "", kActNames[l.lastAct], l.lastOk ? "ok" : "FAILED", l.lastMsg);
    }
    if (!n) p.println("  no locks yet: yeelock add <name> <SN> <signkeyhex>");
    return true;
  }
  if (strcmp(sub, "add") == 0) {
    if (argc != 5) { p.println("usage: yeelock add <name> <SN> <signkeyhex>"); return true; }
    JsonDocument d(jsonAlloc());
    d["name"] = argv[2];
    d["sn"] = argv[3];
    d["key"] = argv[4];
    String id, err;
    bool ok = itemSave(nullptr, d.as<JsonObjectConst>(), id, err);
    secureZero(argv[4], strlen(argv[4]));
    d.clear();
    if (ok) p.printf("added: %s (entity yeelock.%s)\n", id.c_str(), id.c_str());
    else p.println(err);
    return true;
  }
  if (strcmp(sub, "key") == 0) {
    if (argc != 4) { p.println("usage: yeelock key <id> <signkeyhex>"); return true; }
    Lock* l = byId(argv[2]);
    if (!l) { p.println("no such lock (yeelock list)"); return true; }
    uint8_t k[yeelock::KEY_MAX];
    size_t kl = yeelock::parseSignKey(argv[3], k);
    secureZero(argv[3], strlen(argv[3]));
    if (!kl) { p.println("sign key: hex of 8 to 32 bytes"); return true; }
    memcpy(l->key, k, kl);
    l->keyLen = (uint8_t)kl;
    secureZero(k, sizeof k);
    save();
    p.printf("key replaced for %s (%s)\n", l->id, keyMask(*l));
    return true;
  }
  if (strcmp(sub, "del") == 0) {
    if (argc != 3) { p.println("usage: yeelock del <id>"); return true; }
    String err;
    if (itemDelete(argv[2], err)) p.println("deleted");
    else p.println(err);
    return true;
  }
  if (strcmp(sub, "scan") == 0) {
    String err;
    if (!discoverStart(err)) p.println(err);
    else p.println("scanning; the results follow in the log (and on the web UI)");
    return true;
  }
  if (strcmp(sub, "check") == 0) {
    if (argc != 3) { p.println("usage: yeelock check <id>"); return true; }
    Lock* l = byId(argv[2]);
    if (!l) { p.println("no such lock (yeelock list)"); return true; }
    String job;
    if (!startCheck(*l, &job)) p.println("not possible now (no key, no BLE, or busy)");
    else p.printf("checking (job %s); the result follows in the log\n", job.c_str());
    return true;
  }
#if GW_YEELOCK_CLOUD
  if (strcmp(sub, "fetch") == 0) {
    if (argc != 4) { p.println("usage: yeelock fetch <zone> <username>   e.g. yeelock fetch 420 123456789"); return true; }
    if (!yeelock::validZone(argv[2])) { p.println("zone: the country calling code without +, e.g. 420"); return true; }
    if (!yeelock::validUsername(argv[3])) { p.println("username: the phone number without the country code"); return true; }
    copyStr(g_fetchZone, sizeof g_fetchZone, argv[2]);
    copyStr(g_fetchUser, sizeof g_fetchUser, argv[3]);
    p.println("The gateway logs in to api.yeeloc.com once (verified HTTPS); the password is not stored.");
    cli::askSecret("Yeelock password: ", onFetchPassword, nullptr);
    return true;
  }
  if (strcmp(sub, "import") == 0) {
    if (argc < 3) { p.println("usage: yeelock import <SN>... | all   (after yeelock fetch)"); return true; }
    bool all = strcmp(argv[2], "all") == 0;
    String err;
    int n = cloudImport((const char* const*)(argv + 2), (size_t)(argc - 2), all, err, &p);
    if (n < 0) p.println(err);
    else p.printf("%d lock(s) imported; each is being checked now\n", n);
    return true;
  }
#endif
  if (strcmp(sub, "do") == 0) {
    if (argc != 4) { p.println("usage: yeelock do <id> open|unlock|lock|battery"); return true; }
    String eid = String(MOD_ID) + "." + argv[2];
    CommandResult r = command(eid.c_str(), argv[3], JsonObjectConst());
    if (r.status == 202) p.printf("queued as job %s; the result follows in the log\n", r.job.c_str());
    else p.printf("refused (%d): %s\n", r.status, r.error.c_str());
    return true;
  }
  return false;
}

static bool bleScan(Yeelock* self, uint32_t seconds, const char* wantSn, Found* hit) {
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setActiveScan(true);   // the name is often only in the scan response
  scan->setInterval(45);
  scan->setWindow(30);
  NimBLEScanResults res = scan->start(seconds, false);  // blocking in 1.4
  bool got = false;
  Found tmp[MAX_FOUND];
  size_t nt = 0;
  for (int i = 0; i < (int)res.getCount(); i++) {
    NimBLEAdvertisedDevice d = res.getDevice(i);
    if (!d.haveName()) continue;
    std::string nm = d.getName();
    if (nm.size() < 4 || nm.compare(0, 3, "EL_") != 0) continue;
    std::string sn = nm.substr(3);
    if (!yeelock::isValidSn(sn.c_str()) || nt >= MAX_FOUND) continue;
    Found& f = tmp[nt++];
    copyStr(f.sn, sizeof f.sn, sn.c_str());
    f.rssi = d.getRSSI();
    copyStr(f.addr, sizeof f.addr, d.getAddress().toString().c_str());
    f.addrType = d.getAddress().getType();
    if (wantSn && strcasecmp(f.sn, wantSn) == 0) {
      got = true;
      if (hit) *hit = f;
    }
  }
  scan->clearResults();
  self->scanDone(tmp, nt);
  return got;
}

}  // namespace

Module* yeelockModule() {
  static Yeelock m;
  return &m;
}

}  // namespace gw
