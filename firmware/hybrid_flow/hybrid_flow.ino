// Hybrid-Flow Smart Irrigation & Energy Manager — ESP32 firmware
// BITE401P Embedded Systems and IoT, Project Review 1
//
// Core 1 (this loop): read 7 sensors -> control logic -> drive 5 actuators at 10 Hz.
// Core 0 (cloud task): Wi-Fi, NTP and Firebase uploads, with offline buffering.
//
// Libraries: "DHT sensor library" and "Adafruit Unified Sensor" (Library Manager).
// Board: ESP32 Dev Module (esp32 by Espressif, core 2.x or 3.x).
//
// Serial monitor (115200): type h = hold, a = auto, r = reset fault, s = status.

#include "cloud.h"
#include "config.h"
#include "control_logic.h"
#include "sensors.h"

static hf::Controller controller;
static Sensors sensors;

static uint32_t lastLoopMs = 0;
static uint32_t lastLiveMs = 0;
static uint32_t lastTelemetryMs = 0;
static uint32_t lastPrintMs = 0;

static void writePin(int pin, bool on, bool activeLow) {
  digitalWrite(pin, (on != activeLow) ? HIGH : LOW);
}

// Applies outputs in a safe order: anything that turns the pump off goes
// first, anything that turns it on goes last.
static void writeOutputs(const hf::Outputs& o) {
  if (!o.pumpOn) writePin(PIN_PUMP_SSR, false, false);
  writePin(PIN_RELAY_SOURCE, o.relayGrid, RELAY_ACTIVE_LOW);
  writePin(PIN_RELAY_ZONE1, o.valve[0], RELAY_ACTIVE_LOW);
  writePin(PIN_RELAY_ZONE2, o.valve[1], RELAY_ACTIVE_LOW);
  writePin(PIN_BUZZER, o.buzzer, false);
  writePin(PIN_ALERT_LED, o.alertLed, false);
  if (o.pumpOn) writePin(PIN_PUMP_SSR, true, false);
}

static void initOutputs() {
  // Set the safe level before switching each pin to output, so nothing
  // glitches on at boot.
  const int pins[] = {PIN_PUMP_SSR, PIN_RELAY_SOURCE, PIN_RELAY_ZONE1, PIN_RELAY_ZONE2, PIN_BUZZER, PIN_ALERT_LED};
  writeOutputs(hf::Outputs());
  for (int pin : pins) pinMode(pin, OUTPUT);
  writeOutputs(hf::Outputs());
}

static Snapshot snapshot(const Readings& r) {
  Snapshot s;
  s.tsMs = cloud::epochMs();
  s.uptimeS = millis() / 1000;
  s.r = r;
  s.source = controller.source();
  s.phase = controller.phase();
  s.fault = controller.fault();
  s.mode = controller.mode();
  s.zone = static_cast<int8_t>(controller.zone());
  s.out = controller.outputs();
  s.solarAvailable = controller.solarAvailable();
  s.tempAlert = controller.tempAlert();
  s.tankFull = controller.tankFull();
  s.lastStop = controller.lastStop();
  s.totals = controller.totals();
  return s;
}

static void handleSerial(uint32_t now) {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'h') controller.command(hf::Command::HOLD, now);
    else if (c == 'a') controller.command(hf::Command::AUTO, now);
    else if (c == 'r') controller.command(hf::Command::RESET_FAULT, now);
    else if (c == 's') lastPrintMs = 0;
  }
}

static void printStatus(const Readings& r) {
  Serial.printf("[%lus] %-13s src=%-5s zone=%d pump=%d V1=%d V2=%d | solar=%.1fV soil=%.0f/%.0f%% tank=%.0f%% T=%.1fC I=%.2fA Q=%.1fL/min | %s %s\n",
                millis() / 1000, hf::toString(controller.phase()), hf::toString(controller.source()),
                controller.zone() + 1, controller.outputs().pumpOn, controller.outputs().valve[0],
                controller.outputs().valve[1], r.solarV, r.soil[0], r.soil[1], r.tankPct, r.tempC, r.pumpA,
                r.flowLpm, hf::toString(controller.fault()), cloud::online() ? "online" : "offline");
}

void setup() {
  initOutputs();  // fail-safe state first: pump off, valves closed, relay on solar contact
  Serial.begin(115200);
  delay(200);
  Serial.println("\nHybrid-Flow " FW_VERSION " (" DEVICE_ID ")");

  sensors.begin();
  controller.begin(millis());
  cloud::begin();
}

void loop() {
  uint32_t now = millis();
  if (now - lastLoopMs < LOOP_MS) return;
  lastLoopMs = now;

  handleSerial(now);
  hf::Command cmd;
  while (cloud::takeCommand(cmd)) controller.command(cmd, now);

  sensors.setPumpOn(controller.outputs().pumpOn);
  const Readings& r = sensors.read(now);
  const hf::Outputs& out = controller.update(now, r.toInputs());
  writeOutputs(out);
  controller.meter(now, SUPPLY_VRMS, POWER_FACTOR);

  hf::Event e;
  while (controller.popEvent(e)) {
    EventMsg m;
    m.tsMs = cloud::epochMs();
    m.type = e.type;
    m.zone = e.zone;
    m.value = e.value;
    cloud::queueEvent(m);
    Serial.printf("EVENT %s zone=%d value=%.2f\n", hf::toString(e.type), e.zone + 1, e.value);
  }

  if (now - lastLiveMs >= LIVE_PERIOD_MS) {
    lastLiveMs = now;
    cloud::publishLive(snapshot(r));
  }
  if (now - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    lastTelemetryMs = now;
    cloud::queueTelemetry(snapshot(r));
  }
  if (lastPrintMs == 0 || now - lastPrintMs >= 1000) {
    lastPrintMs = now;
    printStatus(r);
  }
}
