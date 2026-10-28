// Hybrid-Flow Smart Irrigation & Energy Manager — ESP32 firmware
// BITE401P Embedded Systems and IoT, Project Review 1
//
// Core 1 (this loop): read the sensors -> control logic -> drive the actuators at 10 Hz.
// Core 0 (cloud task): Wi-Fi, NTP and Firebase uploads, with offline buffering.
// USB: a status line and a JSON line every second, read by the Streamlit
// dashboard ("ESP32 over USB"), so the demo needs no Wi-Fi at all.
//
// Build profile (config.h): each sensor is real or a bench knob (REAL_* switches).
// Default: real soil probes, HC-SR04 + float switch, DHT22 and LDR; knobs for
// solar voltage, pump current and water flow. SIM_INPUTS 1 = all knobs (Wokwi),
// SIM_INPUTS 0 = field build with every real sensor.
//
// Libraries: "DHT sensor library" and "Adafruit Unified Sensor" (Library Manager).
// Board: ESP32 Dev Module (esp32 by Espressif, core 2.x or 3.x).
//
// Serial commands (115200 baud, Serial Monitor or the dashboard):
//   h = hold irrigation   a = automatic control   r = reset a pump fault
//   t = click each relay in turn (wiring test)
//   i = invert relay logic (if relays are on when they should be off; remembered)
//   b = invert buzzer logic (if it beeps when it should be quiet; remembered)
//   s = print status now
//   c = print raw sensor readings (for calibrating the soil probes and tank)

#include <Preferences.h>

#include "cloud.h"
#include "config.h"
#include "control_logic.h"
#include "sensors.h"

static hf::Controller controller;
static Sensors sensors;
static Preferences prefs;

static bool relayActiveLow = RELAY_ACTIVE_LOW;
static bool pumpActiveLow = PUMP_ACTIVE_LOW;
static bool buzzerActiveLow = BUZZER_ACTIVE_LOW;

static uint32_t lastLoopMs = 0;
static uint32_t lastLiveMs = 0;
static uint32_t lastTelemetryMs = 0;
static uint32_t lastPrintMs = 0;
static uint32_t lastJsonMs = 0;

static void writePin(int pin, bool on, bool activeLow) {
  digitalWrite(pin, (on != activeLow) ? HIGH : LOW);
}

// Applies outputs in a safe order: anything that turns the pump off goes
// first, anything that turns it on goes last.
static void writeOutputs(const hf::Outputs& o) {
  if (!o.pumpOn) writePin(PIN_PUMP_SSR, false, pumpActiveLow);
  writePin(PIN_RELAY_SOURCE, o.relayGrid, relayActiveLow);
  writePin(PIN_RELAY_ZONE1, o.valve[0], relayActiveLow);
  writePin(PIN_RELAY_ZONE2, o.valve[1], relayActiveLow);
  writePin(PIN_BUZZER, o.buzzer, buzzerActiveLow);
  writePin(PIN_ALERT_LED, o.alertLed, false);
  if (o.pumpOn) writePin(PIN_PUMP_SSR, true, pumpActiveLow);
}

static void loadPolarity() {
  prefs.begin("hybridflow", false);
  bool flipRelays = prefs.getBool("flipRelays", false);
  bool flipBuzzer = prefs.getBool("flipBuzzer", false);
  relayActiveLow = RELAY_ACTIVE_LOW != flipRelays;
  pumpActiveLow = PUMP_ON_RELAY ? relayActiveLow : PUMP_ACTIVE_LOW;
  buzzerActiveLow = BUZZER_ACTIVE_LOW != flipBuzzer;
}

static void initOutputs() {
  // Set the safe level before switching each pin to output, so nothing
  // glitches on at boot.
  const int pins[] = {PIN_PUMP_SSR, PIN_RELAY_SOURCE, PIN_RELAY_ZONE1, PIN_RELAY_ZONE2, PIN_BUZZER, PIN_ALERT_LED};
  writeOutputs(hf::Outputs());
  for (int pin : pins) pinMode(pin, OUTPUT);
  writeOutputs(hf::Outputs());
}

// Clicks relays 1-4 in turn with a short beep, then returns everything to safe.
// Run at boot and on the 't' command, so a wiring fault shows immediately.
static void relayTest() {
  const int pins[] = {PIN_RELAY_SOURCE, PIN_RELAY_ZONE1, PIN_RELAY_ZONE2, PIN_PUMP_SSR};
  const char* names[] = {"1 solar/grid", "2 valve Z1", "3 valve Z2", "4 pump"};
  writeOutputs(hf::Outputs());
  for (int i = 0; i < 4; i++) {
    Serial.printf("Relay test: relay %s\n", names[i]);
    writePin(pins[i], true, i == 3 ? pumpActiveLow : relayActiveLow);
    writePin(PIN_BUZZER, true, buzzerActiveLow);
    delay(60);
    writePin(PIN_BUZZER, false, buzzerActiveLow);
    delay(340);
    writePin(pins[i], false, i == 3 ? pumpActiveLow : relayActiveLow);
    delay(150);
  }
  writeOutputs(hf::Outputs());
  Serial.println("Relay test done. Every relay should have clicked once, in order 1-2-3-4.");
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

// Raw readings for calibration: soil millivolts (dry air vs a glass of water go
// into SOIL_DRY_MV / SOIL_WET_MV), the HC-SR04 distance, the LDR and the float.
static void printRaw(const Readings& r) {
  Serial.printf("RAW soil Z1=%.0fmV Z2=%.0fmV | tank %.1fcm (%.0f%%) float=%s | LDR=%.0fmV (%.0f%%) | T=%.1fC RH=%.0f%%\n",
                r.soilMv[0], r.soilMv[1], r.tankCm, r.tankPct, r.floatHigh ? "HIGH" : "low", r.ldrMv,
                r.lightPct, r.tempC, r.humidity);
}

static void printProfile() {
  if (ALL_REAL) {
    Serial.println("Field build: every sensor is real");
    return;
  }
  struct { bool real; const char* name; } in[] = {
      {REAL_SOLAR, "solar"}, {REAL_SOIL, "soil"},       {REAL_TANK, "tank+float"}, {REAL_DHT22, "DHT22"},
      {REAL_LDR, "LDR"},     {REAL_CURRENT, "current"}, {REAL_FLOW, "flow"}};
  Serial.print("Bench build. Real:");
  for (auto& i : in) if (i.real) Serial.printf(" %s", i.name);
  Serial.print(" | knobs:");
  for (auto& i : in) if (!i.real) Serial.printf(" %s", i.name);
  Serial.println();
}

static void handleSerial(uint32_t now) {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'h') controller.command(hf::Command::HOLD, now);
    else if (c == 'a') controller.command(hf::Command::AUTO, now);
    else if (c == 'r') controller.command(hf::Command::RESET_FAULT, now);
    else if (c == 's') lastPrintMs = 0;
    else if (c == 'c') printRaw(sensors.last());
    else if (c == 't') relayTest();
    else if (c == 'i' || c == 'b') {
      const char* key = c == 'i' ? "flipRelays" : "flipBuzzer";
      prefs.putBool(key, !prefs.getBool(key, false));
      loadPolarity();
      writeOutputs(controller.outputs());
      Serial.printf("%s logic inverted and saved (relays active-%s, buzzer active-%s)\n",
                    c == 'i' ? "Relay" : "Buzzer", relayActiveLow ? "low" : "high",
                    buzzerActiveLow ? "low" : "high");
    }
  }
}

static void printStatus(const Readings& r) {
  Serial.printf("[%lus] %-13s src=%-5s zone=%d pump=%d V1=%d V2=%d | solar=%.1fV soil=%.0f/%.0f%% tank=%.0f%% T=%.1fC I=%.2fA Q=%.1fL/min | %s %s\n",
                millis() / 1000, hf::toString(controller.phase()), hf::toString(controller.source()),
                controller.zone() + 1, controller.outputs().pumpOn, controller.outputs().valve[0],
                controller.outputs().valve[1], r.solarV, r.soil[0], r.soil[1], r.tankPct, r.tempC, r.pumpA,
                r.flowLpm, hf::toString(controller.fault()),
                CLOUD_ENABLED ? (cloud::online() ? "online" : "offline") : "no-wifi");
}

void setup() {
  loadPolarity();
  initOutputs();  // fail-safe state first: pump off, valves closed, relay on solar contact
  Serial.setTxBufferSize(4096);  // JSON lines must never block the control loop
  Serial.begin(115200);
  delay(300);
  Serial.println("\nHybrid-Flow " FW_VERSION " (" DEVICE_ID ")");
  printProfile();
  Serial.println(CLOUD_ENABLED ? "Firebase upload on" : "No secrets.h: running offline (USB dashboard only)");
  Serial.println("Commands: h hold, a auto, r reset fault, t relay test, i invert relays, b invert buzzer, c raw readings");

  sensors.begin();
  relayTest();
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
    Serial.print("@EVT ");
    Serial.println(cloud::eventJson(m));
  }

  if (now - lastLiveMs >= LIVE_PERIOD_MS) {
    lastLiveMs = now;
    cloud::publishLive(snapshot(r));
  }
  if (now - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    lastTelemetryMs = now;
    cloud::queueTelemetry(snapshot(r));
  }
  if (now - lastJsonMs >= SERIAL_JSON_PERIOD_MS) {
    lastJsonMs = now;
    Serial.print("@LIVE ");
    Serial.println(cloud::liveJson(snapshot(r)));
  }
  if (lastPrintMs == 0 || now - lastPrintMs >= 1000) {
    lastPrintMs = now;
    printStatus(r);
  }
}
