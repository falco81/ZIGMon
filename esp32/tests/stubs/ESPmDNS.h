#pragma once
#include "Arduino.h"
class MDNSResponder {
 public:
  bool begin(const String& hostName);
  void end();
  bool addService(const char* service, const char* proto, uint16_t port);
  bool addServiceTxt(const char* name, const char* proto, const char* key, const char* value);
};
extern MDNSResponder MDNS;
