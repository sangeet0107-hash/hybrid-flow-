// Runs the shared scenarios (tests/scenarios.json) against the firmware's
// control logic on a PC. Build and run with `make` in this folder.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include <string>
#include <vector>

#include "../../firmware/hybrid_flow/control_logic.h"

struct InSet {
  int mask;
  float solarV, z1, z2, tankPct, tempC, pumpA, flowLpm, floatHigh;
};

struct Range {
  bool on;
  double v[2];
};

struct Expect {
  const char *phase, *source, *relay, *fault, *mode;
  int pump, valve1, valve2, alertLed;
  int switches;
  bool hasSolarWh; double solarWh[2];
  bool hasGridWh; double gridWh[2];
  bool hasLitres; double litres[2];
};

struct Step {
  uint32_t ms;
  InSet in;
  const char* cmd;
  Expect ex;
  const char* events;
};

struct Scenario {
  const char* name;
  InSet init;
  const Step* steps;
  int nSteps;
};

#include "scenarios.inc"

static void apply(hf::Inputs& in, const InSet& s) {
  if (s.mask & 1) in.solarV = s.solarV;
  if (s.mask & 2) in.moisture[0] = s.z1;
  if (s.mask & 4) in.moisture[1] = s.z2;
  if (s.mask & 8) in.tankPct = s.tankPct;
  if (s.mask & 16) in.tempC = s.tempC;
  if (s.mask & 32) in.pumpA = s.pumpA;
  if (s.mask & 64) in.flowLpm = s.flowLpm;
  if (s.mask & 128) in.tankFloatHigh = s.floatHigh != 0;
}

static hf::Command parseCmd(const char* c) {
  if (!c) return hf::Command::NONE;
  if (!strcmp(c, "HOLD")) return hf::Command::HOLD;
  if (!strcmp(c, "AUTO")) return hf::Command::AUTO;
  if (!strcmp(c, "RESET_FAULT")) return hf::Command::RESET_FAULT;
  return hf::Command::NONE;
}

static int failures = 0;

static void fail(const char* sc, int step, const std::string& msg) {
  printf("  FAIL %s step %d: %s\n", sc, step + 1, msg.c_str());
  failures++;
}

static void checkStr(const char* sc, int step, const char* what, const char* want, const char* got) {
  if (want && strcmp(want, got) != 0) fail(sc, step, std::string(what) + " expected " + want + ", got " + got);
}

static void checkBool(const char* sc, int step, const char* what, int want, bool got) {
  if (want >= 0 && (want == 1) != got)
    fail(sc, step, std::string(what) + " expected " + (want ? "true" : "false") + ", got " + (got ? "true" : "false"));
}

static void checkRange(const char* sc, int step, const char* what, bool on, const double* r, double got) {
  if (on && (got < r[0] - 1e-9 || got > r[1] + 1e-9)) {
    char buf[160];
    snprintf(buf, sizeof buf, "%s expected %.3f..%.3f, got %.4f", what, r[0], r[1], got);
    fail(sc, step, buf);
  }
}

int main() {
  int passed = 0;
  for (int s = 0; s < SCENARIO_COUNT; s++) {
    const Scenario& sc = SCENARIOS[s];
    int before = failures;
    hf::Controller c;
    c.begin(0);
    hf::Inputs in;
    apply(in, DEFAULTS);
    apply(in, sc.init);
    uint32_t t = 0;
    bool prevPump = false, prevRelay = false;

    for (int i = 0; i < sc.nSteps; i++) {
      const Step& st = sc.steps[i];
      apply(in, st.in);
      std::vector<std::string> seen;
      hf::Command cmd = parseCmd(st.cmd);
      if (cmd != hf::Command::NONE) c.command(cmd, t);

      for (uint32_t k = 0; k < st.ms / TICK_MS; k++) {
        t += TICK_MS;
        const hf::Outputs& o = c.update(t, in);
        c.meter(t, METER_VOLTS, METER_PF);
        if (o.pumpOn && !o.valve[0] && !o.valve[1]) fail(sc.name, i, "pump on with every valve closed");
        if (o.relayGrid != prevRelay && (o.pumpOn || prevPump)) fail(sc.name, i, "source relay moved while the pump was on");
        prevPump = o.pumpOn;
        prevRelay = o.relayGrid;
        hf::Event e;
        while (c.popEvent(e)) seen.push_back(hf::toString(e.type));
      }

      const Expect& ex = st.ex;
      const hf::Outputs& o = c.outputs();
      checkStr(sc.name, i, "phase", ex.phase, hf::toString(c.phase()));
      checkStr(sc.name, i, "source", ex.source, hf::toString(c.source()));
      checkStr(sc.name, i, "relay", ex.relay, o.relayGrid ? "GRID" : "SOLAR");
      checkStr(sc.name, i, "fault", ex.fault, hf::toString(c.fault()));
      checkStr(sc.name, i, "mode", ex.mode, hf::toString(c.mode()));
      checkBool(sc.name, i, "pump", ex.pump, o.pumpOn);
      checkBool(sc.name, i, "valve1", ex.valve1, o.valve[0]);
      checkBool(sc.name, i, "valve2", ex.valve2, o.valve[1]);
      checkBool(sc.name, i, "alertLed", ex.alertLed, o.alertLed);
      if (ex.switches >= 0 && (uint32_t)ex.switches != c.totals().switches) {
        fail(sc.name, i, "switches expected " + std::to_string(ex.switches) + ", got " + std::to_string(c.totals().switches));
      }
      checkRange(sc.name, i, "solarWh", ex.hasSolarWh, ex.solarWh, c.totals().solarWh);
      checkRange(sc.name, i, "gridWh", ex.hasGridWh, ex.gridWh, c.totals().gridWh);
      checkRange(sc.name, i, "litres", ex.hasLitres, ex.litres, c.totals().litres);

      if (st.events && *st.events) {
        std::string list = st.events;
        size_t pos = 0;
        while (pos <= list.size()) {
          size_t comma = list.find(',', pos);
          std::string want = list.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos);
          bool found = false;
          for (auto& e : seen) found = found || e == want;
          if (!found) fail(sc.name, i, "expected event " + want);
          if (comma == std::string::npos) break;
          pos = comma + 1;
        }
      }
    }

    if (failures == before) {
      printf("  ok   %s\n", sc.name);
      passed++;
    }
  }
  printf("\n%d/%d scenarios passed (firmware C++)\n", passed, SCENARIO_COUNT);
  return failures == 0 ? 0 : 1;
}
