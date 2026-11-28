// Syntax-check stub of the Arduino core for ESP32 3.x (declarations only, never linked).
// Signatures follow cores/esp32 (WString.h, Print.h, HardwareSerial.h, Esp.h, IPAddress.h).
#pragma once

#include <ctype.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>

#include <string>
#include <vector>

#include "esp_err.h"
#include "esp_idf_version.h"
#include "freertos/FreeRTOS.h"
#include "sdkconfig.h"

#define PROGMEM
typedef uint8_t byte;

unsigned long millis();
unsigned long micros();
void delay(uint32_t ms);

class StringSumHelper;

class String {
 public:
  String(const char* cstr = "");
  String(const String& str);
  String(String&& rval);
  explicit String(char c);
  explicit String(unsigned char, unsigned char base = 10);
  explicit String(int, unsigned char base = 10);
  explicit String(unsigned int, unsigned char base = 10);
  explicit String(long, unsigned char base = 10);
  explicit String(unsigned long, unsigned char base = 10);
  explicit String(float, unsigned int decimalPlaces = 2);
  explicit String(double, unsigned int decimalPlaces = 2);
  explicit String(long long, unsigned char base = 10);
  explicit String(unsigned long long, unsigned char base = 10);
  ~String();

  bool reserve(unsigned int size);
  inline unsigned int length() const { return 0; }
  String& operator=(const String& rhs);
  String& operator=(const char* cstr);
  String& operator=(String&& rval);
  String& operator=(StringSumHelper&& rval);

  bool concat(const String& str);
  bool concat(const char* cstr);
  bool concat(const char* cstr, unsigned int length);
  bool concat(char c);
  bool concat(unsigned char c);
  bool concat(int num);
  bool concat(unsigned int num);
  bool concat(long num);
  bool concat(unsigned long num);

  String& operator+=(const String& rhs) { concat(rhs); return *this; }
  String& operator+=(const char* cstr) { concat(cstr); return *this; }
  String& operator+=(char c) { concat(c); return *this; }
  String& operator+=(int num) { concat(num); return *this; }
  String& operator+=(unsigned int num) { concat(num); return *this; }
  String& operator+=(long num) { concat(num); return *this; }
  String& operator+=(unsigned long num) { concat(num); return *this; }

  friend StringSumHelper& operator+(const StringSumHelper& lhs, const String& rhs);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, const char* cstr);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, char c);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, unsigned char num);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, int num);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, unsigned int num);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, long num);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, unsigned long num);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, float num);
  friend StringSumHelper& operator+(const StringSumHelper& lhs, double num);

  explicit operator bool() const;
  int compareTo(const String& s) const;
  bool equals(const String& s) const;
  bool equals(const char* cstr) const;
  bool operator==(const String& rhs) const { return equals(rhs); }
  bool operator==(const char* cstr) const { return equals(cstr); }
  bool operator!=(const String& rhs) const { return !equals(rhs); }
  bool operator!=(const char* cstr) const { return !equals(cstr); }
  bool equalsIgnoreCase(const String& s) const;
  bool startsWith(const String& prefix) const;
  bool endsWith(const String& suffix) const;

  char charAt(unsigned int index) const;
  void setCharAt(unsigned int index, char c);
  char operator[](unsigned int index) const;
  char& operator[](unsigned int index);
  const char* c_str() const { return buffer_; }

  int indexOf(char ch) const;
  int indexOf(const String& str) const;
  String substring(unsigned int beginIndex) const;
  String substring(unsigned int beginIndex, unsigned int endIndex) const;
  void replace(const String& find, const String& replace);
  void remove(unsigned int index);
  void toLowerCase();
  void toUpperCase();
  void trim();
  long toInt() const;

 private:
  char* buffer_;
};

class StringSumHelper : public String {
 public:
  StringSumHelper(const String& s) : String(s) {}
  StringSumHelper(const char* p) : String(p) {}
  StringSumHelper(char c) : String(c) {}
  StringSumHelper(unsigned char num) : String(num) {}
  StringSumHelper(int num) : String(num) {}
  StringSumHelper(unsigned int num) : String(num) {}
  StringSumHelper(long num) : String(num) {}
  StringSumHelper(unsigned long num) : String(num) {}
  StringSumHelper(float num) : String(num) {}
  StringSumHelper(double num) : String(num) {}
};

inline bool operator==(const char* a, const String& b) { return b == a; }

class Printable;

class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(uint8_t) = 0;
  virtual size_t write(const uint8_t* buffer, size_t size);
  size_t write(const char* str);
  size_t write(const char* buffer, size_t size);
  size_t printf(const char* format, ...) __attribute__((format(printf, 2, 3)));
  size_t print(const String&);
  size_t print(const char[]);
  size_t print(char);
  size_t print(unsigned char, int = 10);
  size_t print(int, int = 10);
  size_t print(unsigned int, int = 10);
  size_t print(long, int = 10);
  size_t print(unsigned long, int = 10);
  size_t print(double, int = 2);
  size_t println(const String& s);
  size_t println(const char[]);
  size_t println(char);
  size_t println(unsigned char, int = 10);
  size_t println(int, int = 10);
  size_t println(unsigned int, int = 10);
  size_t println(long, int = 10);
  size_t println(unsigned long, int = 10);
  size_t println(double, int = 2);
  size_t println(void);
  virtual void flush() {}
};

class Stream : public Print {
 public:
  virtual int available() = 0;
  virtual int read() = 0;
  virtual int peek() = 0;
};

// HardwareSerial and HWCDC/USBCDC (USB CDC On Boot) share this shape.
class HardwareSerial : public Stream {
 public:
  void begin(unsigned long baud);
  int available() override;
  int read() override;
  int peek() override;
  void flush() override;
  size_t write(uint8_t) override;
  size_t write(const uint8_t* buffer, size_t size) override;
  using Print::write;
  operator bool() const;
};
extern HardwareSerial Serial;

class IPAddress {
 public:
  IPAddress();
  IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d);
  IPAddress(uint32_t address);
  String toString() const;
  operator uint32_t() const;
};

class EspClass {
 public:
  void restart();
  uint32_t getFreeHeap();
  uint32_t getMinFreeHeap();
  uint32_t getFlashChipSize();
  uint32_t getPsramSize();
  const char* getSdkVersion();
  uint64_t getEfuseMac();
};
extern EspClass ESP;
