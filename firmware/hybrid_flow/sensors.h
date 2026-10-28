// Sensing layer: reads the 7 sensors and converts them to engineering units.
// On the bench, knobs can stand in for any of them (REAL_* switches in config.h).
#pragma once

#include <math.h>
#include <stdint.h>

#include "control_logic.h"

struct Readings {
  float solarV = 0;        // V DC
  float soil[hf::ZONES];   // % VWC, NAN if the probe is unplugged
  float tankPct = 0;       // %, NAN if the ultrasonic sensor keeps missing
  bool floatHigh = false;  // overflow float switch
  float tempC = 0;         // NAN if the DHT22 read failed
  float humidity = 0;      // % RH
  float lightPct = 0;      // 0-100 relative brightness
  float pumpA = 0;         // A RMS
  float flowLpm = 0;       // L/min

  // Raw values for calibration (serial command c). NAN when that input is a knob.
  float soilMv[hf::ZONES] = {NAN, NAN};
  float tankCm = NAN;      // last distance measured by the HC-SR04
  float ldrMv = NAN;

  hf::Inputs toInputs() const;
};

class Sensors {
 public:
  void begin();
  // Call every control cycle. Takes up to ~30 ms with the HC-SR04 (echo wait),
  // ~45 ms more with the ACS712 (current RMS window), ~2 ms with knobs only.
  const Readings& read(uint32_t nowMs);
  const Readings& last() const { return r_; }
  // Measures the ACS712 zero point. Call with the pump off.
  void calibrateCurrentZero();
  // Tells the sensing layer whether the pump is on: the current and flow knobs
  // only read while it runs, like the real sensors.
  void setPumpOn(bool on) { pumpOn_ = on; }

 private:
  float readMv(int pin, int samples);
  float knob(int pin);
  float soilPercent(float mv);
  float readTankPct();
  float readPumpA();

  Readings r_;
  float currentZeroMv_ = 1650.0f;
  uint32_t lastDhtMs_ = 0;
  uint32_t lastFlowMs_ = 0;
  uint32_t lastFlowPulses_ = 0;
  uint8_t tankMisses_ = 0;
  bool pumpOn_ = false;
};
