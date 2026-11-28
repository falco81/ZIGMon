// stub: Arduino core Preferences (NVS)
#pragma once
#include "Arduino.h"
class Preferences {
 public:
  bool begin(const char* name, bool readOnly = false, const char* partition_label = NULL);
  void end();
  bool clear();
  bool remove(const char* key);
  size_t putUChar(const char* key, uint8_t value);
  size_t putUInt(const char* key, uint32_t value);
  size_t putBool(const char* key, bool value);
  size_t putString(const char* key, const char* value);
  size_t putString(const char* key, String value);
  size_t putBytes(const char* key, const void* value, size_t len);
  bool isKey(const char* key);
  uint8_t getUChar(const char* key, uint8_t defaultValue = 0);
  uint32_t getUInt(const char* key, uint32_t defaultValue = 0);
  bool getBool(const char* key, bool defaultValue = false);
  size_t getString(const char* key, char* value, size_t maxLen);
  String getString(const char* key, String defaultValue = String());
  size_t getBytesLength(const char* key);
  size_t getBytes(const char* key, void* buf, size_t maxLen);
};
