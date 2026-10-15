// Do-nothing definitions for the host stand-ins, so firmware files can be linked
// into small PC programs (see json_check.cpp).
#include "Arduino.h"
#include "WiFi.h"
SerialStub Serial;
WiFiStub WiFi;
unsigned long millis() { return 0; }
void delay(uint32_t) {}
void delayMicroseconds(uint32_t) {}
void pinMode(int, int) {}
void digitalWrite(int, int) {}
int digitalRead(int) { return 0; }
uint32_t analogReadMilliVolts(int) { return 0; }
void analogReadResolution(int) {}
void analogSetAttenuation(int) {}
unsigned long pulseIn(int, int, unsigned long) { return 0; }
int digitalPinToInterrupt(int p) { return p; }
void attachInterrupt(int, void (*)(), int) {}
void noInterrupts() {}
void interrupts() {}
SemaphoreHandle_t xSemaphoreCreateMutex() { return nullptr; }
int xSemaphoreTake(SemaphoreHandle_t, TickType_t) { return 1; }
int xSemaphoreGive(SemaphoreHandle_t) { return 1; }
void vTaskDelay(TickType_t) {}
int xTaskCreatePinnedToCore(void (*)(void*), const char*, uint32_t, void*, int, void*, int) { return 1; }
void configTime(long, int, const char*, const char*) {}
