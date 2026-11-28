// Syntax-check stub of ArduinoJson 7.x: the public API the firmware uses, with the same
// value/reference semantics and conversions (declarations only, never linked).
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <type_traits>

class String;

namespace ArduinoJson {

class Allocator {
 public:
  virtual void* allocate(size_t size) = 0;
  virtual void deallocate(void* ptr) = 0;
  virtual void* reallocate(void* ptr, size_t new_size) = 0;

 protected:
  ~Allocator() = default;
};

class JsonVariant;
class JsonVariantConst;
class JsonObject;
class JsonObjectConst;
class JsonArray;
class JsonArrayConst;
class JsonDocument;

class JsonVariantConst {
 public:
  JsonVariantConst();
  template <typename T> T as() const;
  template <typename T> bool is() const;
  bool isNull() const;
  JsonVariantConst operator[](const char* key) const;
  JsonVariantConst operator[](const String& key) const;
  JsonVariantConst operator[](size_t index) const;
  JsonVariantConst operator[](int index) const;
  template <typename T, typename = typename std::enable_if<!std::is_same<T, bool>::value>::type>
  operator T() const;
  operator bool() const;
  size_t size() const;
};

class JsonVariant {
 public:
  JsonVariant();
  template <typename T> T as() const;
  template <typename T> bool is() const;
  bool isNull() const;
  template <typename T> T to();
  template <typename T> T add();
  template <typename T> bool add(const T& value);
  bool add(const char* value);
  template <typename T> JsonVariant& operator=(const T& value);
  JsonVariant& operator=(const char* value);
  JsonVariant& operator=(char* value);
  JsonVariant operator[](const char* key) const;
  JsonVariant operator[](const String& key) const;
  JsonVariant operator[](size_t index) const;
  JsonVariant operator[](int index) const;
  operator JsonVariantConst() const;
  template <typename T, typename = typename std::enable_if<!std::is_same<T, bool>::value>::type>
  operator T() const;
  operator bool() const;
  size_t size() const;
};

// `variant | default`: the default's type, or const char* for a string literal.
template <typename T>
typename std::enable_if<!std::is_array<T>::value && !std::is_pointer<T>::value, T>::type operator|(
    const JsonVariantConst& v, const T& def);
const char* operator|(const JsonVariantConst& v, const char* def);
template <typename T>
typename std::enable_if<!std::is_array<T>::value && !std::is_pointer<T>::value, T>::type operator|(
    const JsonVariant& v, const T& def);
const char* operator|(const JsonVariant& v, const char* def);

class JsonPair {
 public:
  JsonVariant value() const;
};
class JsonPairConst {
 public:
  JsonVariantConst value() const;
};

template <typename V>
class Iter {
 public:
  V operator*() const;
  Iter& operator++();
  bool operator!=(const Iter&) const;
};

class JsonArrayConst {
 public:
  JsonArrayConst();
  Iter<JsonVariantConst> begin() const;
  Iter<JsonVariantConst> end() const;
  size_t size() const;
  bool isNull() const;
  JsonVariantConst operator[](size_t i) const;
  operator JsonVariantConst() const;
};

class JsonArray {
 public:
  JsonArray();
  Iter<JsonVariant> begin() const;
  Iter<JsonVariant> end() const;
  template <typename T> T add() const;
  template <typename T> bool add(const T& value) const;
  bool add(const char* value) const;
  size_t size() const;
  bool isNull() const;
  JsonVariant operator[](size_t i) const;
  operator JsonArrayConst() const;
  operator JsonVariant() const;
  operator JsonVariantConst() const;
};

class JsonObjectConst {
 public:
  JsonObjectConst();
  Iter<JsonPairConst> begin() const;
  Iter<JsonPairConst> end() const;
  JsonVariantConst operator[](const char* key) const;
  JsonVariantConst operator[](const String& key) const;
  size_t size() const;
  bool isNull() const;
  operator JsonVariantConst() const;
};

class JsonObject {
 public:
  JsonObject();
  Iter<JsonPair> begin() const;
  Iter<JsonPair> end() const;
  JsonVariant operator[](const char* key) const;
  JsonVariant operator[](const String& key) const;
  size_t size() const;
  bool isNull() const;
  void remove(const char* key) const;
  operator JsonObjectConst() const;
  operator JsonVariant() const;
  operator JsonVariantConst() const;
};

class JsonDocument {
 public:
  explicit JsonDocument(Allocator* alloc = nullptr);
  JsonDocument(const JsonDocument&);
  JsonDocument(JsonDocument&&);
  ~JsonDocument();
  template <typename T> T as() const;
  template <typename T> bool is() const;
  template <typename T> T to();
  template <typename T> T add();
  bool isNull() const;
  void clear();
  bool overflowed() const;
  size_t size() const;
  JsonVariant operator[](const char* key);
  JsonVariant operator[](const String& key);
  JsonVariant operator[](size_t index);
  JsonVariant operator[](int index);
  JsonVariantConst operator[](const char* key) const;
  operator JsonVariant();
  operator JsonVariantConst() const;
};

class DeserializationError {
 public:
  enum Code { Ok, EmptyInput, IncompleteInput, InvalidInput, NoMemory, TooDeep };
  DeserializationError();
  DeserializationError(Code c);
  explicit operator bool() const;
  Code code() const;
  const char* c_str() const;
};

namespace DeserializationOption {
class NestingLimit {
 public:
  explicit NestingLimit(uint8_t n);
};
class Filter {
 public:
  explicit Filter(JsonVariantConst v);
};
}  // namespace DeserializationOption

DeserializationError deserializeJson(JsonDocument& doc, const char* input);
DeserializationError deserializeJson(JsonDocument& doc, const char* input, size_t len);
DeserializationError deserializeJson(JsonDocument& doc, const String& input);
template <typename... Opts>
DeserializationError deserializeJson(JsonDocument& doc, const char* input, size_t len, Opts... opts);
template <typename... Opts>
DeserializationError deserializeJson(JsonDocument& doc, char* input, size_t len, Opts... opts);

size_t serializeJson(JsonVariantConst source, String& out);
size_t serializeJson(JsonVariantConst source, char* out, size_t size);
size_t measureJson(JsonVariantConst source);

}  // namespace ArduinoJson

using namespace ArduinoJson;
