// Hybrid-Flow control logic.
//
// This file has no Arduino dependencies on purpose: the same code runs on the
// ESP32 and in the PC unit tests (tests/firmware). The sketch reads the
// sensors, calls Controller::update() every cycle, and writes the returned
// Outputs to the relay, SSR, valves and buzzer.
//
// Behaviour follows Project Review 1 (Revised), section VII-C/D:
//   * Priority 1: SOLAR when solar voltage > 18 V (debounced 5 s)
//   * Priority 2: GRID only when solar is unavailable AND a zone is < 30 %
//   * One zone at a time; valve opens before the pump, pump stops before the valve
//   * Break-before-make changeover with a 200 ms dead time on each side
//   * Dry-run, over-current and no-flow trips latch until an operator reset
//   * Tank >= 95 % or temperature outside 0..45 C stops irrigation
#pragma once

#include <stdint.h>

namespace hf {

static const int ZONES = 2;

enum class Source : uint8_t { NONE = 0, SOLAR = 1, GRID = 2 };

enum class Phase : uint8_t {
  IDLE = 0,
  VALVE_OPENING,   // valve energised, waiting before the pump starts
  RUNNING,         // pump on, protections armed
  SWITCH_BREAK,    // pump off, waiting dead time before moving the source relay
  SWITCH_SETTLE,   // relay moved, waiting dead time before the pump restarts
  STOPPING,        // pump off, waiting before the valve closes
  FAULT            // latched pump fault; everything off until RESET_FAULT
};

enum class Fault : uint8_t { NONE = 0, DRY_RUN, OVER_CURRENT, NO_FLOW };

enum class Mode : uint8_t { AUTO = 0, HOLD };

enum class Command : uint8_t { NONE = 0, HOLD, AUTO, RESET_FAULT };

enum class StopReason : uint8_t {
  NONE = 0, TARGET_REACHED, TANK_FULL, HOLD, TEMP_ALERT, SOLAR_LOST, SENSOR_INVALID
};

enum class EventType : uint8_t {
  BOOT = 0,
  SOLAR_AVAILABLE,
  SOLAR_LOST,
  SOURCE_CHANGED,
  ZONE_START,
  ZONE_DONE,
  ZONE_STOPPED,
  FAULT_DRY_RUN,
  FAULT_OVER_CURRENT,
  FAULT_NO_FLOW,
  FAULT_CLEARED,
  TANK_FULL,
  TANK_OK,
  TEMP_ALERT,
  TEMP_OK,
  SENSOR_WARN,
  MODE_HOLD,
  MODE_AUTO
};

enum class Severity : uint8_t { INFO = 0, WARN, CRIT };

struct Config {
  // Source selection
  float solarOnV = 18.0f;          // Priority 1 threshold
  uint32_t debounceMs = 5000;      // solar availability must hold this long to change

  // Soil moisture (% volumetric water content), evaluated per zone
  float moistureCritical = 30.0f;  // below this a zone may use GRID power
  float moistureSolarStart = 50.0f;// below this a zone is watered while solar is free
  float moistureTarget = 60.0f;    // a running zone stops here

  // Tank and temperature
  float tankOverflowPct = 95.0f;
  float tankResumePct = 90.0f;     // hysteresis before irrigation resumes
  float tempMaxC = 45.0f;
  float tempMinC = 0.0f;
  float tempHystC = 2.0f;

  // Pump protection
  uint32_t inrushMs = 1000;        // motor inrush window: current trips ignored
  float dryRunA = 0.5f;
  uint32_t dryRunMs = 3000;
  float overCurrentA = 8.0f;
  float noFlowLpm = 1.0f;
  uint32_t noFlowMs = 5000;
  uint32_t startupDelayMs = 5000;  // no-flow check starts after this

  // Sequencing
  uint32_t deadTimeMs = 200;       // each side of a source changeover
  uint32_t valveOpenMs = 1000;     // valve response < 1 s per datasheet
  uint32_t valveCloseDelayMs = 500;// pump stops first, then the valve closes
};

struct Inputs {
  float solarV = 0;
  float moisture[ZONES] = {0, 0};  // % VWC; NAN when the probe reading is invalid
  float tankPct = 0;               // %; NAN when unknown
  float tempC = 25;                // NAN when the DHT22 read failed
  float pumpA = 0;                 // RMS amps from ACS712
  float flowLpm = 0;               // from YF-S201 pulses
  bool tankFloatHigh = false;      // hardware float switch (overflow backup)
};

struct Outputs {
  bool relayGrid = false;          // CH1: false = solar contact (de-energised), true = grid
  bool pumpOn = false;             // pump-enable SSR
  bool valve[ZONES] = {false, false};
  bool buzzer = false;
  bool alertLed = false;
};

struct Event {
  uint32_t ms = 0;
  EventType type = EventType::BOOT;
  int8_t zone = -1;                // 0-based zone index, -1 if not zone-specific
  float value = 0;                 // the reading that caused the event, if any
};

// Running totals for the solar-vs-grid and water-efficiency benchmarks.
struct Totals {
  double solarWh = 0;
  double gridWh = 0;
  double litres = 0;
  double litresZone[ZONES] = {0, 0};
  uint32_t switches = 0;           // source changeovers while running
  uint32_t faults = 0;
};

class Controller {
 public:
  explicit Controller(const Config& cfg = Config());

  void begin(uint32_t nowMs);
  const Outputs& update(uint32_t nowMs, const Inputs& in);
  void command(Command c, uint32_t nowMs);

  // Metering: call once per cycle after update(). volts is the pump supply
  // RMS voltage (230 V AC on both sources: the solar side feeds the AC pump
  // through an inverter).
  void meter(uint32_t nowMs, float volts, float powerFactor);

  bool popEvent(Event& out);

  const Config& config() const { return cfg_; }
  const Outputs& outputs() const { return out_; }
  const Totals& totals() const { return totals_; }
  Source source() const { return source_; }
  Phase phase() const { return phase_; }
  Fault fault() const { return fault_; }
  Mode mode() const { return mode_; }
  int zone() const { return zone_; }
  bool solarAvailable() const { return solarAvail_; }
  bool tempAlert() const { return tempAlert_; }
  bool tankFull() const { return tankFull_; }
  StopReason lastStop() const { return lastStop_; }

 private:
  bool valid(float x) const { return x == x; }  // false for NAN
  void emit(uint32_t now, EventType t, int zone = -1, float value = 0);
  void updateSolar(uint32_t now, float v);
  void updateTank(uint32_t now);
  void updateTemp(uint32_t now);
  void updateSensorWarnings(uint32_t now);
  bool canStart() const;
  bool pickJob(Source& src, int& zone) const;
  Source desiredSourceWhileRunning() const;
  StopReason stopCondition() const;
  void startZone(uint32_t now, int zone, Source src);
  void beginStop(uint32_t now, StopReason why);
  void beginSwitch(uint32_t now, Source to);
  void trip(uint32_t now, Fault f);
  void setPhase(uint32_t now, Phase p);
  void computeAlerts(uint32_t now);

  Config cfg_;
  Inputs in_;
  Outputs out_;
  Totals totals_;

  Phase phase_ = Phase::IDLE;
  uint32_t phaseSince_ = 0;
  Source source_ = Source::NONE;     // source powering the pump right now
  Source switchTo_ = Source::NONE;
  Fault fault_ = Fault::NONE;
  Mode mode_ = Mode::AUTO;
  int zone_ = -1;
  StopReason lastStop_ = StopReason::NONE;

  bool started_ = false;
  bool solarAvail_ = false;
  bool solarCandidate_ = false;
  uint32_t solarCandidateSince_ = 0;

  bool tankFull_ = false;
  bool tempAlert_ = false;
  bool tempWarned_ = false;
  bool moistureWarned_[ZONES] = {false, false};

  uint32_t runSince_ = 0;
  bool dryTiming_ = false;
  uint32_t drySince_ = 0;
  bool noFlowTiming_ = false;
  uint32_t noFlowSince_ = 0;

  uint32_t chirpUntil_ = 0;
  uint32_t lastMeterMs_ = 0;
  bool meterStarted_ = false;

  static const int EVENT_CAP = 16;
  Event events_[EVENT_CAP];
  int evHead_ = 0;
  int evCount_ = 0;
};

const char* toString(Source s);
const char* toString(Phase p);
const char* toString(Fault f);
const char* toString(Mode m);
const char* toString(EventType t);
const char* toString(StopReason r);
Severity severityOf(EventType t);

}  // namespace hf
