#pragma once
#include "Arduino.h"
#include "WiFiClientSecure.h"
class HTTPClient {
 public:
  void setTimeout(uint16_t) {}
  bool begin(WiFiClientSecure&, const String&) { return true; }
  void addHeader(const char*, const char*) {}
  int sendRequest(const char*, const String&) { return 200; }
  String getString() { return String(); }
  void end() {}
};
