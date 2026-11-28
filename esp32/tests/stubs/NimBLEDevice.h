// stub: NimBLE-Arduino 1.4.x (NimBLEDevice, NimBLEScan, NimBLEClient, NimBLERemote*)
#pragma once
#include <stdint.h>
#include <functional>
#include <string>
#include <vector>
#define BLE_ADDR_PUBLIC 0
typedef enum { ESP_PWR_LVL_N12 = 0, ESP_PWR_LVL_P3 = 5, ESP_PWR_LVL_P9 = 7 } esp_power_level_t;
typedef enum { ESP_BLE_PWR_TYPE_DEFAULT = 9 } esp_ble_power_type_t;
class NimBLEUUID {
 public:
  NimBLEUUID(const std::string& uuid);
  NimBLEUUID(uint16_t uuid);
  NimBLEUUID(const char* uuid);
  bool operator==(const NimBLEUUID& rhs) const;
};
class NimBLEAddress {
 public:
  NimBLEAddress();
  NimBLEAddress(const std::string& stringAddress, uint8_t type = BLE_ADDR_PUBLIC);
  std::string toString() const;
  uint8_t getType() const;
};
class NimBLEAttValue {
 public:
  operator std::string() const;
  const uint8_t* data() const;
  uint16_t length() const;
};
class NimBLERemoteCharacteristic;
typedef std::function<void(NimBLERemoteCharacteristic* pBLERemoteCharacteristic, uint8_t* pData, size_t length,
                           bool isNotify)> notify_callback;
class NimBLERemoteCharacteristic {
 public:
  NimBLEUUID getUUID();
  bool canRead();
  bool canWrite();
  bool canWriteNoResponse();
  bool canNotify();
  NimBLEAttValue readValue(time_t* timestamp = nullptr);
  bool writeValue(const uint8_t* data, size_t length, bool response = false);
  bool subscribe(bool notifications = true, notify_callback notifyCallback = nullptr, bool response = false);
};
class NimBLERemoteService {
 public:
  NimBLERemoteCharacteristic* getCharacteristic(const NimBLEUUID& uuid);
  std::vector<NimBLERemoteCharacteristic*>* getCharacteristics(bool refresh = false);
};
class NimBLEClient {
 public:
  bool connect(const NimBLEAddress& address, bool deleteAttributes = true);
  int disconnect(uint8_t reason = 0x13);
  bool isConnected();
  void setConnectTimeout(uint8_t timeout);
  int getRssi();
  NimBLERemoteService* getService(const NimBLEUUID& uuid);
  std::vector<NimBLERemoteService*>* getServices(bool refresh = false);
};
class NimBLEAdvertisedDevice {
 public:
  NimBLEAddress getAddress();
  std::string getName();
  int getRSSI();
  bool haveName();
};
class NimBLEScanResults {
 public:
  int getCount();
  NimBLEAdvertisedDevice getDevice(uint32_t i);
};
class NimBLEScan {
 public:
  bool start(uint32_t duration, void (*scanCompleteCB)(NimBLEScanResults), bool is_continue = false);
  NimBLEScanResults start(uint32_t duration, bool is_continue = false);
  void setActiveScan(bool active);
  void setInterval(uint16_t intervalMSecs);
  void setWindow(uint16_t windowMSecs);
  void clearResults();
};
class NimBLEDevice {
 public:
  static void init(const std::string& deviceName);
  static void setPower(esp_power_level_t powerLevel, esp_ble_power_type_t powerType = ESP_BLE_PWR_TYPE_DEFAULT);
  static NimBLEScan* getScan();
  static NimBLEClient* createClient();
  static bool deleteClient(NimBLEClient* pClient);
};
