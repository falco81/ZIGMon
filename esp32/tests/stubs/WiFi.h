// stub: Arduino core 3.x WiFi (WiFiSTA/WiFiScan/WiFiGeneric), the calls the firmware uses
#pragma once
#include "Arduino.h"
typedef enum { WL_IDLE_STATUS = 0, WL_NO_SSID_AVAIL = 1, WL_SCAN_COMPLETED = 2, WL_CONNECTED = 3,
               WL_CONNECT_FAILED = 4, WL_CONNECTION_LOST = 5, WL_DISCONNECTED = 6 } wl_status_t;
typedef enum { WIFI_MODE_NULL = 0, WIFI_MODE_STA, WIFI_MODE_AP, WIFI_MODE_APSTA } wifi_mode_t;
#define WIFI_STA WIFI_MODE_STA
typedef enum { WIFI_AUTH_OPEN = 0, WIFI_AUTH_WEP, WIFI_AUTH_WPA_PSK, WIFI_AUTH_WPA2_PSK } wifi_auth_mode_t;
#define WIFI_SCAN_RUNNING (-1)
#define WIFI_SCAN_FAILED (-2)
class WiFiClass {
 public:
  bool mode(wifi_mode_t);
  bool setHostname(const char* hostname);
  void persistent(bool persistent);
  bool setSleep(bool enabled);
  bool setAutoReconnect(bool autoReconnect);
  wl_status_t begin(const char* ssid, const char* passphrase = NULL, int32_t channel = 0,
                    const uint8_t* bssid = NULL, bool connect = true);
  bool config(IPAddress local_ip, IPAddress gateway, IPAddress subnet, IPAddress dns1 = (uint32_t)0x00000000,
              IPAddress dns2 = (uint32_t)0x00000000);
  bool disconnect(bool wifioff = false, bool eraseap = false, unsigned long timeoutLength = 100);
  bool reconnect();
  wl_status_t status();
  IPAddress localIP();
  String SSID() const;
  int8_t RSSI();
  int16_t scanNetworks(bool async = false, bool show_hidden = false, bool passive = false,
                       uint32_t max_ms_per_chan = 300, uint8_t channel = 0, const char* ssid = nullptr,
                       const uint8_t* bssid = nullptr);
  int16_t scanComplete();
  void scanDelete();
  String SSID(uint8_t networkItem);
  int32_t RSSI(uint8_t networkItem);
  wifi_auth_mode_t encryptionType(uint8_t networkItem);
  int32_t channel(uint8_t networkItem);
};
extern WiFiClass WiFi;
