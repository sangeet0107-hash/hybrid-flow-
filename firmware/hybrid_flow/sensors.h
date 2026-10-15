// Sensing layer: reads the 7 sensors (or, in the bench build, the knobs that
// stand in for them) and converts them to engineering units.
#pragma once

#include <stdint.h>

#include "control_logic.h"

struct Readings {
  float solarV = 0;        // V DC
  float soil[hf::ZONES];   // % VWC, NAN if the probe is unplugged
  float tankPct = 0;       // %, NAN if the ultrasonic sensor timed out
  bool floatHigh = false;  // overflow float switch
  float tempC = 0;         // NAN if the DHT22 read failed
  float humidity = 0;      // % RH
  float lightPct = 0;      // 0-100 relative brightness
  float pumpA = 0;         // A RMS
  float flowLpm = 0;       // L/min

  hf::Inputs toInputs() const;
};

class Sensors {
 public:
  void begin();
  // Call every control cycle. About 45 ms with real sensors (current RMS window
  // + ultrasonic), about 2 ms with knobs.
  const Readings& read(uint32_t nowMs);
  // Measures the ACS712 zero point. Call with the pump off.
  void calibrateCurrentZero();
  // Tells the sensing layer whether the SSR is on (used by the Wokwi build,
  // where pots stand in for the current and flow sensors).
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
  bool pumpOn_ = false;
};
