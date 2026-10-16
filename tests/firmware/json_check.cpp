// Prints the firmware's own "@LIVE" and "@EVT" JSON lines (from cloud.cpp) for a
// sample state, so the dashboard's parser can be tested against the real format.
#include <math.h>
#include <stdio.h>
#include "cloud.h"

int main() {
  Snapshot s;
  s.uptimeS = 42;
  s.r.solarV = 20.1f; s.r.soil[0] = 44.5f; s.r.soil[1] = NAN; s.r.tankPct = 55;
  s.r.tempC = 30; s.r.humidity = 50; s.r.lightPct = 80; s.r.pumpA = 4.2f; s.r.flowLpm = 12;
  s.source = hf::Source::SOLAR; s.phase = hf::Phase::RUNNING; s.zone = 1;
  s.out.pumpOn = true; s.out.valve[1] = true;
  s.totals.solarWh = 1.5; s.totals.switches = 1;
  printf("@LIVE %s\n", cloud::liveJson(s).c_str());
  EventMsg e; e.type = hf::EventType::ZONE_DONE; e.zone = 1;
  e.value = static_cast<float>(hf::StopReason::TARGET_REACHED);
  printf("@EVT %s\n", cloud::eventJson(e).c_str());
  return 0;
}
