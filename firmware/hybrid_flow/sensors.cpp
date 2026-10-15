#include "sensors.h"

#include <Arduino.h>
#include <DHT.h>
#include <math.h>

#include "config.h"

static DHT dht(PIN_DHT, DHT22);
static volatile uint32_t flowPulses = 0;

static void IRAM_ATTR onFlowPulse() { flowPulses = flowPulses + 1; }

hf::Inputs Readings::toInputs() const {
  hf::Inputs in;
  in.solarV = solarV;
  for (int z = 0; z < hf::ZONES; z++) in.moisture[z] = soil[z];
  in.tankPct = tankPct;
  in.tankFloatHigh = floatHigh;
  in.tempC = tempC;
  in.pumpA = pumpA;
  in.flowLpm = flowLpm;
  return in;
}

void Sensors::begin() {
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);  // full 0-3.3 V range on ADC1
  pinMode(PIN_FLOAT, INPUT_PULLUP);
  pinMode(PIN_FLOW, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onFlowPulse, FALLING);
  pinMode(PIN_US_TRIG, OUTPUT);
  digitalWrite(PIN_US_TRIG, LOW);
  pinMode(PIN_US_ECHO, INPUT);
  dht.begin();
  r_.tempC = NAN;
  r_.humidity = NAN;
  calibrateCurrentZero();
  lastFlowMs_ = millis();
}

float Sensors::readMv(int pin, int samples) {
  uint32_t sum = 0;
  for (int i = 0; i < samples; i++) sum += analogReadMilliVolts(pin);
  return static_cast<float>(sum) / samples;
}

void Sensors::calibrateCurrentZero() {
  // ~100 ms of samples with no load gives the sensor's mid-point.
  currentZeroMv_ = readMv(PIN_CURRENT, 400);
}

float Sensors::soilPercent(float mv) {
  if (mv < SOIL_MIN_VALID_MV || mv > SOIL_MAX_VALID_MV) return NAN;
  float pct = (SOIL_DRY_MV - mv) / (SOIL_DRY_MV - SOIL_WET_MV) * 100.0f;
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

float Sensors::readTankPct() {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);
  unsigned long us = pulseIn(PIN_US_ECHO, HIGH, 12000);  // ~2 m round trip max
  if (us == 0) return NAN;
  float cm = us * 0.0343f / 2.0f;
  float pct = (TANK_EMPTY_CM - cm) / (TANK_EMPTY_CM - TANK_FULL_CM) * 100.0f;
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

float Sensors::readPumpA() {
  // True RMS over two mains cycles: the pump current is AC.
  double sumSq = 0;
  uint32_t n = 0;
  uint32_t start = millis();
  while (millis() - start < ACS_SAMPLE_WINDOW_MS) {
    float d = analogReadMilliVolts(PIN_CURRENT) - currentZeroMv_;
    sumSq += static_cast<double>(d) * d;
    n++;
  }
  if (n == 0) return 0;
  float rmsMv = sqrtf(static_cast<float>(sumSq / n)) * ACS_DIVIDER_GAIN;
  float amps = rmsMv / ACS_MV_PER_A;
  return amps < ACS_NOISE_FLOOR_A ? 0.0f : amps;
}

const Readings& Sensors::read(uint32_t now) {
  r_.solarV = readMv(PIN_SOLAR_V, 16) / 1000.0f * SOLAR_DIVIDER_RATIO;
  r_.soil[0] = soilPercent(readMv(PIN_SOIL_Z1, 16));
  r_.soil[1] = soilPercent(readMv(PIN_SOIL_Z2, 16));

  float light = readMv(PIN_LDR, 8) / 3300.0f * 100.0f;
  r_.lightPct = LDR_INVERT ? 100.0f - light : light;

  r_.tankPct = readTankPct();
  bool floatClosed = digitalRead(PIN_FLOAT) == (FLOAT_ACTIVE_LOW ? LOW : HIGH);
  r_.floatHigh = floatClosed;

#if WOKWI_SIM
  // Pots set what the current and flow sensors would read while the pump runs.
  r_.pumpA = pumpOn_ ? readMv(PIN_CURRENT, 8) / 3300.0f * 12.0f : 0.0f;
#else
  r_.pumpA = readPumpA();
#endif

  // DHT22 can only be read about every 2 s.
  if (now - lastDhtMs_ >= 2500 || lastDhtMs_ == 0) {
    lastDhtMs_ = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    r_.tempC = t;  // NAN on a failed read; the controller raises a sensor warning
    if (!isnan(h)) r_.humidity = h;
  }

#if WOKWI_SIM
  r_.flowLpm = pumpOn_ ? readMv(PIN_FLOW_POT, 8) / 3300.0f * 20.0f : 0.0f;
  return r_;
#endif
  // Flow from pulses counted since the last call.
  uint32_t dt = now - lastFlowMs_;
  if (dt >= 500) {
    noInterrupts();
    uint32_t pulses = flowPulses;
    interrupts();
    float hz = (pulses - lastFlowPulses_) * 1000.0f / dt;
    r_.flowLpm = hz / FLOW_PULSES_PER_LPM;
    lastFlowPulses_ = pulses;
    lastFlowMs_ = now;
  }
  return r_;
}
