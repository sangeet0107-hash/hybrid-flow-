// Minimal host stand-ins for the Arduino-ESP32 API, used only to compile-check
// the firmware sources on a PC (make syntax). They do nothing at runtime.
#pragma once
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define FALLING 2
#define IRAM_ATTR
#define ADC_11db 3

class String {
 public:
  String() {}
  String(const char* s) : s_(s ? s : "") {}
  String(float v, int decimals) { char b[32]; snprintf(b, sizeof b, "%.*f", decimals, v); s_ = b; }
  String(double v, int decimals) { char b[32]; snprintf(b, sizeof b, "%.*f", decimals, v); s_ = b; }
  void reserve(unsigned n) { s_.reserve(n); }
  String& operator+=(const char* s) { s_ += s; return *this; }
  String& operator+=(const String& s) { s_ += s.s_; return *this; }
  String& operator+=(char c) { s_ += c; return *this; }
  String& operator+=(int v) { s_ += std::to_string(v); return *this; }
  String& operator+=(unsigned int v) { s_ += std::to_string(v); return *this; }
  String& operator+=(long v) { s_ += std::to_string(v); return *this; }
  String& operator+=(unsigned long v) { s_ += std::to_string(v); return *this; }
  bool operator==(const char* o) const { return s_ == o; }
  int indexOf(const char* sub) const { auto p = s_.find(sub); return p == std::string::npos ? -1 : (int)p; }
  const char* c_str() const { return s_.c_str(); }
 private:
  std::string s_;
};

struct SerialStub {
  void begin(unsigned long) {}
  size_t setTxBufferSize(size_t n) { return n; }
  void print(const char*) {}
  void println(const String&) {}
  int available() { return 0; }
  int read() { return -1; }
  void println(const char*) {}
  int printf(const char* fmt, ...) __attribute__((format(printf, 2, 3))) { (void)fmt; return 0; }
};
extern SerialStub Serial;

unsigned long millis();  // unsigned long on ESP32, as in the real core
void delay(uint32_t);
void delayMicroseconds(uint32_t);
void pinMode(int, int);
void digitalWrite(int, int);
int digitalRead(int);
uint32_t analogReadMilliVolts(int);
void analogReadResolution(int);
void analogSetAttenuation(int);
unsigned long pulseIn(int, int, unsigned long);
int digitalPinToInterrupt(int);
void attachInterrupt(int, void (*)(), int);
void noInterrupts();
void interrupts();

// FreeRTOS
typedef void* SemaphoreHandle_t;
typedef uint32_t TickType_t;
#define portMAX_DELAY 0xffffffffu
#define pdMS_TO_TICKS(x) (x)
SemaphoreHandle_t xSemaphoreCreateMutex();
int xSemaphoreTake(SemaphoreHandle_t, TickType_t);
int xSemaphoreGive(SemaphoreHandle_t);
void vTaskDelay(TickType_t);
int xTaskCreatePinnedToCore(void (*)(void*), const char*, uint32_t, void*, int, void*, int);
void configTime(long, int, const char*, const char*);
