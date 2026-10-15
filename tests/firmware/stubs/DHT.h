#pragma once
#define DHT22 22
class DHT {
 public:
  DHT(int, int) {}
  void begin() {}
  float readTemperature() { return 25; }
  float readHumidity() { return 50; }
};
