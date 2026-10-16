// Cloud link: Wi-Fi, NTP time and the Firebase Realtime Database REST API.
//
// Runs as a FreeRTOS task on core 0 so that slow HTTPS calls never delay the
// control loop on core 1. When Wi-Fi is down the controller keeps running;
// telemetry and events are buffered here and uploaded on reconnect.
#pragma once

#include <Arduino.h>
#include <stdint.h>

#include "control_logic.h"
#include "sensors.h"

struct Snapshot {
  uint64_t tsMs = 0;       // epoch ms, 0 if NTP hasn't synced yet
  uint32_t uptimeS = 0;
  Readings r;
  hf::Source source = hf::Source::NONE;
  hf::Phase phase = hf::Phase::IDLE;
  hf::Fault fault = hf::Fault::NONE;
  hf::Mode mode = hf::Mode::AUTO;
  int8_t zone = -1;
  hf::Outputs out;
  bool solarAvailable = false;
  bool tempAlert = false;
  bool tankFull = false;
  hf::StopReason lastStop = hf::StopReason::NONE;
  hf::Totals totals;
};

struct EventMsg {
  uint64_t tsMs = 0;
  hf::EventType type = hf::EventType::BOOT;
  int8_t zone = -1;
  float value = 0;
};

namespace cloud {

void begin();
uint64_t epochMs();                    // 0 until NTP has synced
void publishLive(const Snapshot& s);   // latest state, overwritten every LIVE_PERIOD_MS
void queueTelemetry(const Snapshot& s);
void queueEvent(const EventMsg& e);
bool takeCommand(hf::Command& out);    // operator command from the dashboard, if any
bool online();
int buffered();

// The same JSON documents that go to Firebase, for the USB link.
String liveJson(const Snapshot& s);
String eventJson(const EventMsg& e);

}  // namespace cloud
