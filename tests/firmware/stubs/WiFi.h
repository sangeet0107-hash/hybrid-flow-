#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
#define WIFI_STA 1
struct WiFiStub {
  int status() { return 0; }
  void mode(int) {}
  void begin(const char*, const char*) {}
  void disconnect() {}
  int RSSI() { return 0; }
};
extern WiFiStub WiFi;
