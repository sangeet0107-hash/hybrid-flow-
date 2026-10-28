#include "sensors.h"

#include <Arduino.h>
#include <math.h>

#include "config.h"

#if REAL_DHT22
#if __has_include(<DHT.h>)
#include <DHT.h>
#else
#error "REAL_DHT22 is 1: install \"DHT sensor library\" by Adafruit (Arduino IDE: Tools > Manage Libraries), or set REAL_DHT22 0 in config.h"
#endif
static DHT dht(PIN_DHT, DHT22);
#endif

#if REAL_FLOW
static volatile uint32_t flowPulses = 0;
static void IRAM_ATTR onFlowPulse() { flowPulses = flowPulses + 1; }
#endif

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
#if REAL_TANK
  pinMode(PIN_FLOAT, INPUT_PULLUP);
  pinMode(PIN_US_TRIG, OUTPUT);
  digitalWrite(PIN_US_TRIG, LOW);
  pinMode(PIN_US_ECHO, INPUT);
#endif
#if REAL_FLOW
  pinMode(PIN_FLOW, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onFlowPulse, FALLING);
#endif
#if REAL_CURRENT
  calibrateCurrentZero();
#endif
#if REAL_DHT22
  dht.begin();
  r_.tempC = NAN;
  r_.humidity = NAN;
#else
  r_.tempC = SIM_TEMP_C;
  r_.humidity = SIM_HUMIDITY;
#endif
  lastFlowMs_ = millis();
}

float Sensors::readMv(int pin, int samples) {
  uint32_t sum = 0;
  for (int i = 0; i < samples; i++) sum += analogReadMilliVolts(pin);
  return static_cast<float>(sum) / samples;
}

// Knob position from 0 (fully anticlockwise) to 1 (fully clockwise).
float Sensors::knob(int pin) {
  float f = readMv(pin, 16) / KNOB_FULL_MV;
  if (f < 0) f = 0;
  if (f > 1) f = 1;
  return f;
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
  unsigned long us = pulseIn(PIN_US_ECHO, HIGH, TANK_ECHO_TIMEOUT_US);
  if (us == 0) {
    // No echo. A single miss is common; keep the last reading for a while, then
    // report the sensor as missing so the dashboard and controller know.
    if (tankMisses_ < TANK_MISSES_ALLOWED) {
      tankMisses_++;
      return r_.tankPct;
    }
    r_.tankCm = NAN;
    return NAN;
  }
  tankMisses_ = 0;
  float cm = us * 0.0343f / 2.0f;
  r_.tankCm = cm;
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

// Knobs report in the same units the real sensor would, so the control logic
// and its thresholds are identical either way.
const Readings& Sensors::read(uint32_t now) {
  // Solar voltage
#if REAL_SOLAR
  r_.solarV = readMv(PIN_SOLAR_V, 16) / 1000.0f * SOLAR_DIVIDER_RATIO;
#else
  r_.solarV = knob(PIN_SOLAR_V) * SIM_SOLAR_MAX_V;
#endif

  // Soil moisture, both zones
#if REAL_SOIL
  r_.soilMv[0] = readMv(PIN_SOIL_Z1, 16);
  r_.soilMv[1] = readMv(PIN_SOIL_Z2, 16);
  r_.soil[0] = soilPercent(r_.soilMv[0]);
  r_.soil[1] = soilPercent(r_.soilMv[1]);
#else
  r_.soil[0] = knob(PIN_SOIL_Z1) * 100.0f;     // clockwise = wetter
  r_.soil[1] = knob(PIN_SOIL_Z2) * 100.0f;
#endif

  // Light
#if REAL_LDR
  r_.ldrMv = readMv(PIN_LDR, 8);
  float light = r_.ldrMv / 3300.0f * 100.0f;
  r_.lightPct = LDR_INVERT ? 100.0f - light : light;
#else
  float sun = r_.solarV / SIM_SOLAR_MAX_V * 100.0f;  // daylight follows the solar reading
  r_.lightPct = sun < 0 ? 0 : sun > 100 ? 100 : sun;
#endif

  // Tank level and overflow float
#if REAL_TANK
  r_.tankPct = readTankPct();
  r_.floatHigh = digitalRead(PIN_FLOAT) == (FLOAT_ACTIVE_LOW ? LOW : HIGH);
#else
  r_.tankPct = knob(PIN_TANK_POT) * 100.0f;
  r_.floatHigh = false;
#endif

  // Pump current. A knob only reads while the pump runs, like the real sensor
  // (turn it to zero for a dry run, fully up for a jam).
#if REAL_CURRENT
  r_.pumpA = readPumpA();
#else
  r_.pumpA = pumpOn_ ? knob(PIN_CURRENT) * SIM_CURRENT_MAX_A : 0.0f;
#endif

  // Water flow
#if REAL_FLOW
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
#else
  r_.flowLpm = pumpOn_ ? knob(PIN_FLOW_POT) * SIM_FLOW_MAX_LPM : 0.0f;
#endif

  // Temperature and humidity
#if REAL_DHT22
  // DHT22 can only be read about every 2 s.
  if (now - lastDhtMs_ >= 2500 || lastDhtMs_ == 0) {
    lastDhtMs_ = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    r_.tempC = t;  // NAN on a failed read; the controller raises a sensor warning
    if (!isnan(h)) r_.humidity = h;
  }
#endif
  (void)now;
  return r_;
}
