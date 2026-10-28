// Hybrid-Flow control logic. See control_logic.h for the behaviour summary.
#include "control_logic.h"

namespace hf {

Controller::Controller(const Config& cfg) : cfg_(cfg) {}

void Controller::begin(uint32_t nowMs) {
  phase_ = Phase::IDLE;
  phaseSince_ = nowMs;
  source_ = Source::NONE;
  fault_ = Fault::NONE;
  mode_ = Mode::AUTO;
  zone_ = -1;
  started_ = false;
  out_ = Outputs();
  emit(nowMs, EventType::BOOT);
}

// ---------------------------------------------------------------- events

void Controller::emit(uint32_t now, EventType t, int zone, float value) {
  Event e;
  e.ms = now;
  e.type = t;
  e.zone = static_cast<int8_t>(zone);
  e.value = value;
  int tail = (evHead_ + evCount_) % EVENT_CAP;
  events_[tail] = e;
  if (evCount_ < EVENT_CAP) {
    evCount_++;
  } else {
    evHead_ = (evHead_ + 1) % EVENT_CAP;  // drop the oldest
  }
}

bool Controller::popEvent(Event& out) {
  if (evCount_ == 0) return false;
  out = events_[evHead_];
  evHead_ = (evHead_ + 1) % EVENT_CAP;
  evCount_--;
  return true;
}

// ---------------------------------------------------------------- inputs

void Controller::updateSolar(uint32_t now, float v) {
  bool raw = valid(v) && v > cfg_.solarOnV;
  if (!started_) {
    // First reading sets the state directly so the system doesn't start on
    // grid power at boot and switch to solar 5 s later.
    solarAvail_ = raw;
    solarCandidate_ = raw;
    solarCandidateSince_ = now;
    if (raw) emit(now, EventType::SOLAR_AVAILABLE, -1, v);
    return;
  }
  if (raw != solarCandidate_) {
    solarCandidate_ = raw;
    solarCandidateSince_ = now;
  }
  if (solarCandidate_ != solarAvail_ && now - solarCandidateSince_ >= cfg_.debounceMs) {
    solarAvail_ = solarCandidate_;
    emit(now, solarAvail_ ? EventType::SOLAR_AVAILABLE : EventType::SOLAR_LOST, -1, v);
  }
}

void Controller::updateTank(uint32_t now) {
  bool high = in_.tankFloatHigh || (valid(in_.tankPct) && in_.tankPct >= cfg_.tankOverflowPct);
  if (!tankFull_ && high) {
    tankFull_ = true;
    chirpUntil_ = now + 300;
    emit(now, EventType::TANK_FULL, -1, in_.tankPct);
  } else if (tankFull_ && !in_.tankFloatHigh && (!valid(in_.tankPct) || in_.tankPct < cfg_.tankResumePct)) {
    // With no level reading (ultrasonic missing or out of range) the float switch
    // alone decides, so a full tank doesn't latch forever.
    tankFull_ = false;
    emit(now, EventType::TANK_OK, -1, in_.tankPct);
  }
}

void Controller::updateTemp(uint32_t now) {
  float t = in_.tempC;
  if (!valid(t)) {
    if (!tempWarned_) {
      tempWarned_ = true;
      emit(now, EventType::SENSOR_WARN, -1, -1);  // value -1 = temperature sensor
    }
    return;  // keep the last alert state; a missing reading alone doesn't stop irrigation
  }
  tempWarned_ = false;
  if (!tempAlert_ && (t > cfg_.tempMaxC || t < cfg_.tempMinC)) {
    tempAlert_ = true;
    emit(now, EventType::TEMP_ALERT, -1, t);
  } else if (tempAlert_ && t <= cfg_.tempMaxC - cfg_.tempHystC && t >= cfg_.tempMinC + cfg_.tempHystC) {
    tempAlert_ = false;
    emit(now, EventType::TEMP_OK, -1, t);
  }
}

void Controller::updateSensorWarnings(uint32_t now) {
  for (int z = 0; z < ZONES; z++) {
    float m = in_.moisture[z];
    bool bad = !valid(m) || m < 0.0f || m > 100.0f;
    if (bad && !moistureWarned_[z]) {
      moistureWarned_[z] = true;
      emit(now, EventType::SENSOR_WARN, z, valid(m) ? m : -1);
    } else if (!bad) {
      moistureWarned_[z] = false;
    }
  }
}

// ---------------------------------------------------------------- decisions

bool Controller::canStart() const {
  return mode_ == Mode::AUTO && fault_ == Fault::NONE && !tankFull_ && !tempAlert_;
}

// Picks the driest eligible zone and the source to water it with.
bool Controller::pickJob(Source& src, int& zone) const {
  float limit = solarAvail_ ? cfg_.moistureSolarStart : cfg_.moistureCritical;
  int best = -1;
  float bestM = 0;
  for (int z = 0; z < ZONES; z++) {
    float m = in_.moisture[z];
    if (!valid(m) || m < 0.0f || m > 100.0f) continue;
    if (m < limit && (best < 0 || m < bestM)) {
      best = z;
      bestM = m;
    }
  }
  if (best < 0) return false;
  zone = best;
  src = solarAvail_ ? Source::SOLAR : Source::GRID;
  return true;
}

// While a zone runs: stay on SOLAR when available; otherwise continue on GRID
// only if we were already on grid or the zone has dropped to critical.
Source Controller::desiredSourceWhileRunning() const {
  if (solarAvail_) return Source::SOLAR;
  float m = in_.moisture[zone_];
  if (source_ == Source::GRID || (valid(m) && m < cfg_.moistureCritical)) return Source::GRID;
  return Source::NONE;
}

StopReason Controller::stopCondition() const {
  if (mode_ == Mode::HOLD) return StopReason::HOLD;
  if (tankFull_) return StopReason::TANK_FULL;
  if (tempAlert_) return StopReason::TEMP_ALERT;
  float m = in_.moisture[zone_];
  if (!valid(m) || m < 0.0f || m > 100.0f) return StopReason::SENSOR_INVALID;
  if (m >= cfg_.moistureTarget) return StopReason::TARGET_REACHED;
  return StopReason::NONE;
}

// ---------------------------------------------------------------- transitions

void Controller::setPhase(uint32_t now, Phase p) {
  phase_ = p;
  phaseSince_ = now;
}

void Controller::startZone(uint32_t now, int zone, Source src) {
  zone_ = zone;
  source_ = src;
  out_.relayGrid = (src == Source::GRID);  // pump is off, so the relay can move now
  for (int z = 0; z < ZONES; z++) out_.valve[z] = (z == zone);
  out_.pumpOn = false;
  lastStop_ = StopReason::NONE;
  setPhase(now, Phase::VALVE_OPENING);
  emit(now, EventType::ZONE_START, zone, in_.moisture[zone]);
}

void Controller::beginStop(uint32_t now, StopReason why) {
  out_.pumpOn = false;
  lastStop_ = why;
  setPhase(now, Phase::STOPPING);
  emit(now, why == StopReason::TARGET_REACHED ? EventType::ZONE_DONE : EventType::ZONE_STOPPED,
       zone_, static_cast<float>(why));
}

void Controller::beginSwitch(uint32_t now, Source to) {
  out_.pumpOn = false;  // break first
  switchTo_ = to;
  setPhase(now, Phase::SWITCH_BREAK);
}

void Controller::trip(uint32_t now, Fault f) {
  out_.pumpOn = false;
  for (int z = 0; z < ZONES; z++) out_.valve[z] = false;
  out_.relayGrid = false;
  fault_ = f;
  totals_.faults++;
  EventType t = f == Fault::DRY_RUN ? EventType::FAULT_DRY_RUN
              : f == Fault::OVER_CURRENT ? EventType::FAULT_OVER_CURRENT
              : EventType::FAULT_NO_FLOW;
  emit(now, t, zone_, f == Fault::NO_FLOW ? in_.flowLpm : in_.pumpA);
  source_ = Source::NONE;
  setPhase(now, Phase::FAULT);
}

// ---------------------------------------------------------------- commands

void Controller::command(Command c, uint32_t nowMs) {
  switch (c) {
    case Command::HOLD:
      if (mode_ != Mode::HOLD) {
        mode_ = Mode::HOLD;
        emit(nowMs, EventType::MODE_HOLD);
      }
      break;
    case Command::AUTO:
      if (mode_ != Mode::AUTO) {
        mode_ = Mode::AUTO;
        emit(nowMs, EventType::MODE_AUTO);
      }
      break;
    case Command::RESET_FAULT:
      if (phase_ == Phase::FAULT) {
        fault_ = Fault::NONE;
        zone_ = -1;
        setPhase(nowMs, Phase::IDLE);
        emit(nowMs, EventType::FAULT_CLEARED);
      }
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------- main step

const Outputs& Controller::update(uint32_t now, const Inputs& in) {
  in_ = in;
  updateSolar(now, in.solarV);
  started_ = true;
  updateTank(now);
  updateTemp(now);
  updateSensorWarnings(now);

  switch (phase_) {
    case Phase::IDLE: {
      out_.pumpOn = false;
      for (int z = 0; z < ZONES; z++) out_.valve[z] = false;
      out_.relayGrid = false;
      source_ = Source::NONE;
      zone_ = -1;
      Source src;
      int z;
      if (canStart() && pickJob(src, z)) startZone(now, z, src);
      break;
    }

    case Phase::VALVE_OPENING: {
      StopReason why = stopCondition();
      if (why == StopReason::NONE && desiredSourceWhileRunning() == Source::NONE) why = StopReason::SOLAR_LOST;
      if (why != StopReason::NONE) {
        beginStop(now, why);
      } else if (now - phaseSince_ >= cfg_.valveOpenMs) {
        out_.pumpOn = true;
        runSince_ = now;
        dryTiming_ = noFlowTiming_ = false;
        setPhase(now, Phase::RUNNING);
      }
      break;
    }

    case Phase::RUNNING: {
      uint32_t ran = now - runSince_;
      // Over-current: immediate trip once the inrush window has passed.
      if (ran >= cfg_.inrushMs && in_.pumpA > cfg_.overCurrentA) {
        trip(now, Fault::OVER_CURRENT);
        break;
      }
      // Dry run: low current sustained.
      if (ran >= cfg_.inrushMs && in_.pumpA < cfg_.dryRunA) {
        if (!dryTiming_) { dryTiming_ = true; drySince_ = now; }
        if (now - drySince_ >= cfg_.dryRunMs) { trip(now, Fault::DRY_RUN); break; }
      } else {
        dryTiming_ = false;
      }
      // No flow: pump drawing current but water isn't moving (blockage or leak).
      if (ran >= cfg_.startupDelayMs && in_.flowLpm < cfg_.noFlowLpm) {
        if (!noFlowTiming_) { noFlowTiming_ = true; noFlowSince_ = now; }
        if (now - noFlowSince_ >= cfg_.noFlowMs) { trip(now, Fault::NO_FLOW); break; }
      } else {
        noFlowTiming_ = false;
      }

      StopReason why = stopCondition();
      if (why != StopReason::NONE) { beginStop(now, why); break; }
      Source want = desiredSourceWhileRunning();
      if (want == Source::NONE) { beginStop(now, StopReason::SOLAR_LOST); break; }
      if (want != source_) beginSwitch(now, want);
      break;
    }

    case Phase::SWITCH_BREAK:
      out_.pumpOn = false;
      if (mode_ == Mode::HOLD) { beginStop(now, StopReason::HOLD); break; }
      if (now - phaseSince_ >= cfg_.deadTimeMs) {
        out_.relayGrid = (switchTo_ == Source::GRID);
        setPhase(now, Phase::SWITCH_SETTLE);
      }
      break;

    case Phase::SWITCH_SETTLE:
      out_.pumpOn = false;
      if (mode_ == Mode::HOLD) { beginStop(now, StopReason::HOLD); break; }
      if (now - phaseSince_ >= cfg_.deadTimeMs) {
        source_ = switchTo_;
        totals_.switches++;
        chirpUntil_ = now + 200;
        emit(now, EventType::SOURCE_CHANGED, zone_, static_cast<float>(source_));
        out_.pumpOn = true;
        runSince_ = now;  // re-arm the protection windows after a restart
        dryTiming_ = noFlowTiming_ = false;
        setPhase(now, Phase::RUNNING);
      }
      break;

    case Phase::STOPPING:
      out_.pumpOn = false;
      if (now - phaseSince_ >= cfg_.valveCloseDelayMs) {
        for (int z = 0; z < ZONES; z++) out_.valve[z] = false;
        out_.relayGrid = false;
        source_ = Source::NONE;
        zone_ = -1;
        setPhase(now, Phase::IDLE);
      }
      break;

    case Phase::FAULT:
      out_.pumpOn = false;
      for (int z = 0; z < ZONES; z++) out_.valve[z] = false;
      out_.relayGrid = false;
      break;
  }

  computeAlerts(now);
  return out_;
}

void Controller::computeAlerts(uint32_t now) {
  bool beep = false;
  if (phase_ == Phase::FAULT) {
    beep = (now / 500) % 2 == 0;                // 1 Hz alarm
  } else if (tempAlert_) {
    beep = (now % 2000) < 250;                  // short beep every 2 s
  }
  if (static_cast<int32_t>(chirpUntil_ - now) > 0) beep = true;
  out_.buzzer = beep;
  out_.alertLed = phase_ == Phase::FAULT || tempAlert_ || tankFull_;
}

// ---------------------------------------------------------------- metering

void Controller::meter(uint32_t now, float volts, float powerFactor) {
  if (!meterStarted_) {
    meterStarted_ = true;
    lastMeterMs_ = now;
    return;
  }
  uint32_t dtMs = now - lastMeterMs_;
  lastMeterMs_ = now;
  if (dtMs > 2000) dtMs = 2000;  // ignore gaps (e.g. after a stall)
  if (!out_.pumpOn) return;
  double hours = dtMs / 3600000.0;
  double wh = static_cast<double>(volts) * in_.pumpA * powerFactor * hours;
  if (source_ == Source::SOLAR) totals_.solarWh += wh;
  else if (source_ == Source::GRID) totals_.gridWh += wh;
  double litres = in_.flowLpm * (dtMs / 60000.0);
  totals_.litres += litres;
  if (zone_ >= 0 && zone_ < ZONES) totals_.litresZone[zone_] += litres;
}

// ---------------------------------------------------------------- strings

const char* toString(Source s) {
  switch (s) {
    case Source::SOLAR: return "SOLAR";
    case Source::GRID: return "GRID";
    default: return "NONE";
  }
}

const char* toString(Phase p) {
  switch (p) {
    case Phase::IDLE: return "IDLE";
    case Phase::VALVE_OPENING: return "VALVE_OPENING";
    case Phase::RUNNING: return "RUNNING";
    case Phase::SWITCH_BREAK: return "SWITCH_BREAK";
    case Phase::SWITCH_SETTLE: return "SWITCH_SETTLE";
    case Phase::STOPPING: return "STOPPING";
    case Phase::FAULT: return "FAULT";
  }
  return "?";
}

const char* toString(Fault f) {
  switch (f) {
    case Fault::DRY_RUN: return "DRY_RUN";
    case Fault::OVER_CURRENT: return "OVER_CURRENT";
    case Fault::NO_FLOW: return "NO_FLOW";
    default: return "NONE";
  }
}

const char* toString(Mode m) { return m == Mode::HOLD ? "HOLD" : "AUTO"; }

const char* toString(StopReason r) {
  switch (r) {
    case StopReason::TARGET_REACHED: return "TARGET_REACHED";
    case StopReason::TANK_FULL: return "TANK_FULL";
    case StopReason::HOLD: return "HOLD";
    case StopReason::TEMP_ALERT: return "TEMP_ALERT";
    case StopReason::SOLAR_LOST: return "SOLAR_LOST";
    case StopReason::SENSOR_INVALID: return "SENSOR_INVALID";
    default: return "NONE";
  }
}

const char* toString(EventType t) {
  switch (t) {
    case EventType::BOOT: return "BOOT";
    case EventType::SOLAR_AVAILABLE: return "SOLAR_AVAILABLE";
    case EventType::SOLAR_LOST: return "SOLAR_LOST";
    case EventType::SOURCE_CHANGED: return "SOURCE_CHANGED";
    case EventType::ZONE_START: return "ZONE_START";
    case EventType::ZONE_DONE: return "ZONE_DONE";
    case EventType::ZONE_STOPPED: return "ZONE_STOPPED";
    case EventType::FAULT_DRY_RUN: return "FAULT_DRY_RUN";
    case EventType::FAULT_OVER_CURRENT: return "FAULT_OVER_CURRENT";
    case EventType::FAULT_NO_FLOW: return "FAULT_NO_FLOW";
    case EventType::FAULT_CLEARED: return "FAULT_CLEARED";
    case EventType::TANK_FULL: return "TANK_FULL";
    case EventType::TANK_OK: return "TANK_OK";
    case EventType::TEMP_ALERT: return "TEMP_ALERT";
    case EventType::TEMP_OK: return "TEMP_OK";
    case EventType::SENSOR_WARN: return "SENSOR_WARN";
    case EventType::MODE_HOLD: return "MODE_HOLD";
    case EventType::MODE_AUTO: return "MODE_AUTO";
  }
  return "?";
}

Severity severityOf(EventType t) {
  switch (t) {
    case EventType::FAULT_DRY_RUN:
    case EventType::FAULT_OVER_CURRENT:
    case EventType::FAULT_NO_FLOW:
      return Severity::CRIT;
    case EventType::SOLAR_LOST:
    case EventType::TANK_FULL:
    case EventType::TEMP_ALERT:
    case EventType::SENSOR_WARN:
    case EventType::ZONE_STOPPED:
    case EventType::MODE_HOLD:
      return Severity::WARN;
    default:
      return Severity::INFO;
  }
}

}  // namespace hf
