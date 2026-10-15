#include "cloud.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <sys/time.h>
#include <time.h>

#include "config.h"

namespace cloud {
namespace {

SemaphoreHandle_t lock;

Snapshot liveSnap;
bool liveFresh = false;

Snapshot telemetry[TELEMETRY_BUFFER];
int tHead = 0, tCount = 0;

EventMsg events[EVENT_BUFFER];
int eHead = 0, eCount = 0;

bool cmdPending = false;
hf::Command cmdValue = hf::Command::NONE;
uint64_t lastSeq = 0;
bool seqPrimed = false;  // the first read only records the current seq, so old commands aren't replayed after a reboot

volatile bool linkUp = false;
bool timeConfigured = false;
uint32_t lastWifiTry = 0, lastLiveSent = 0, lastCmdPoll = 0;

// ---------------------------------------------------------------- JSON helpers

void num(String& s, float v, int decimals = 2) {
  if (isnan(v) || isinf(v)) s += "null";
  else s += String(v, decimals);
}

void boolean(String& s, bool v) { s += v ? "true" : "false"; }

void ts(String& s, uint64_t ms) {
  if (ms == 0) {
    s += "{\".sv\":\"timestamp\"}";  // let Firebase stamp it on arrival
  } else {
    char buf[24];
    snprintf(buf, sizeof buf, "%llu", static_cast<unsigned long long>(ms));
    s += buf;
  }
}

const char* sevName(hf::Severity v) {
  return v == hf::Severity::CRIT ? "crit" : v == hf::Severity::WARN ? "warn" : "info";
}

String liveJsonImpl(const Snapshot& x) {
  String s;
  s.reserve(900);
  s += "{\"ts\":"; ts(s, x.tsMs);
  s += ",\"uptimeS\":"; s += x.uptimeS;
  s += ",\"fw\":\"" FW_VERSION "\"";
  s += SIM_INPUTS ? ",\"inputs\":\"knobs\"" : ",\"inputs\":\"sensors\"";
  s += ",\"sensors\":{\"solarV\":"; num(s, x.r.solarV);
  s += ",\"soil\":{\"z1\":"; num(s, x.r.soil[0], 1);
  s += ",\"z2\":"; num(s, x.r.soil[1], 1);
  s += "},\"tankPct\":"; num(s, x.r.tankPct, 1);
  s += ",\"floatHigh\":"; boolean(s, x.r.floatHigh);
  s += ",\"tempC\":"; num(s, x.r.tempC, 1);
  s += ",\"humidity\":"; num(s, x.r.humidity, 1);
  s += ",\"lightPct\":"; num(s, x.r.lightPct, 0);
  s += ",\"pumpA\":"; num(s, x.r.pumpA);
  s += ",\"flowLpm\":"; num(s, x.r.flowLpm, 1);
  s += "},\"state\":{\"source\":\""; s += hf::toString(x.source);
  s += "\",\"relay\":\""; s += x.out.relayGrid ? "GRID" : "SOLAR";
  s += "\",\"pump\":"; boolean(s, x.out.pumpOn);
  s += ",\"valves\":{\"z1\":"; boolean(s, x.out.valve[0]);
  s += ",\"z2\":"; boolean(s, x.out.valve[1]);
  s += "},\"zone\":"; s += x.zone + 1;  // 1-based, 0 = none
  s += ",\"phase\":\""; s += hf::toString(x.phase);
  s += "\",\"mode\":\""; s += hf::toString(x.mode);
  s += "\",\"fault\":\""; s += hf::toString(x.fault);
  s += "\",\"solarAvailable\":"; boolean(s, x.solarAvailable);
  s += ",\"tempAlert\":"; boolean(s, x.tempAlert);
  s += ",\"tankFull\":"; boolean(s, x.tankFull);
  s += ",\"buzzer\":"; boolean(s, x.out.buzzer);
  s += ",\"lastStop\":\""; s += hf::toString(x.lastStop);
  s += "\"},\"totals\":{\"solarWh\":"; num(s, x.totals.solarWh, 2);
  s += ",\"gridWh\":"; num(s, x.totals.gridWh, 2);
  s += ",\"litres\":"; num(s, x.totals.litres, 1);
  s += ",\"litresZ1\":"; num(s, x.totals.litresZone[0], 1);
  s += ",\"litresZ2\":"; num(s, x.totals.litresZone[1], 1);
  s += ",\"switches\":"; s += x.totals.switches;
  s += ",\"faults\":"; s += x.totals.faults;
  s += "},\"net\":{\"rssi\":"; s += WiFi.RSSI();
  s += ",\"buffered\":"; s += tCount + eCount;
  s += "}}";
  return s;
}

String telemetryJson(const Snapshot& x) {
  String s;
  s.reserve(260);
  s += "{\"ts\":"; ts(s, x.tsMs);
  s += ",\"solarV\":"; num(s, x.r.solarV);
  s += ",\"z1\":"; num(s, x.r.soil[0], 1);
  s += ",\"z2\":"; num(s, x.r.soil[1], 1);
  s += ",\"tankPct\":"; num(s, x.r.tankPct, 1);
  s += ",\"tempC\":"; num(s, x.r.tempC, 1);
  s += ",\"pumpA\":"; num(s, x.r.pumpA);
  s += ",\"flowLpm\":"; num(s, x.r.flowLpm, 1);
  s += ",\"source\":\""; s += hf::toString(x.source);
  s += "\",\"pump\":"; boolean(s, x.out.pumpOn);
  s += ",\"solarWh\":"; num(s, x.totals.solarWh, 2);
  s += ",\"gridWh\":"; num(s, x.totals.gridWh, 2);
  s += ",\"litres\":"; num(s, x.totals.litres, 1);
  s += "}";
  return s;
}

String eventJsonImpl(const EventMsg& e) {
  String s;
  s.reserve(140);
  s += "{\"ts\":"; ts(s, e.tsMs);
  s += ",\"type\":\""; s += hf::toString(e.type);
  s += "\",\"sev\":\""; s += sevName(hf::severityOf(e.type));
  s += "\",\"zone\":"; s += e.zone + 1;
  s += ",\"value\":"; num(s, e.value);
  // Stop and changeover events carry an enum in value; send its name too.
  if (e.type == hf::EventType::ZONE_DONE || e.type == hf::EventType::ZONE_STOPPED) {
    s += ",\"detail\":\""; s += hf::toString(static_cast<hf::StopReason>(static_cast<int>(e.value))); s += "\"";
  } else if (e.type == hf::EventType::SOURCE_CHANGED) {
    s += ",\"detail\":\""; s += hf::toString(static_cast<hf::Source>(static_cast<int>(e.value))); s += "\"";
  }
  s += "}";
  return s;
}

// ---------------------------------------------------------------- HTTP

String url(const char* path) {
  String u = FIREBASE_DB_URL;
  u += "/devices/" DEVICE_ID "/";
  u += path;
  u += ".json";
  if (strlen(FIREBASE_AUTH) > 0) {
    u += "?auth=";
    u += FIREBASE_AUTH;
  }
  return u;
}

int request(const char* method, const char* path, const String& body, String* response = nullptr) {
  WiFiClientSecure client;
  client.setInsecure();  // demo build; load the Google root CA with setCACert() for production
  HTTPClient http;
  http.setTimeout(5000);
  if (!http.begin(client, url(path))) return -1;
  http.addHeader("Content-Type", "application/json");
  int code = http.sendRequest(method, body);
  if (response && code > 0) *response = http.getString();
  http.end();
  return code;
}

bool ok(int code) { return code >= 200 && code < 300; }

// ---------------------------------------------------------------- buffers (call with lock held)

bool peekEvent(EventMsg& e) {
  if (eCount == 0) return false;
  e = events[eHead];
  return true;
}

void dropEvent() {
  eHead = (eHead + 1) % EVENT_BUFFER;
  eCount--;
}

bool peekTelemetry(Snapshot& s) {
  if (tCount == 0) return false;
  s = telemetry[tHead];
  return true;
}

void dropTelemetry() {
  tHead = (tHead + 1) % TELEMETRY_BUFFER;
  tCount--;
}

// ---------------------------------------------------------------- commands

void pollCommand() {
  String body;
  if (!ok(request("GET", "command", "", &body))) return;
  if (body == "null") {
    seqPrimed = true;
    return;
  }
  int at = body.indexOf("\"seq\":");
  if (at < 0) return;
  uint64_t seq = strtoull(body.c_str() + at + 6, nullptr, 10);
  if (!seqPrimed) {
    lastSeq = seq;
    seqPrimed = true;
    return;
  }
  if (seq <= lastSeq) return;
  lastSeq = seq;
  hf::Command c = hf::Command::NONE;
  if (body.indexOf("\"action\":\"HOLD\"") >= 0) c = hf::Command::HOLD;
  else if (body.indexOf("\"action\":\"AUTO\"") >= 0) c = hf::Command::AUTO;
  else if (body.indexOf("\"action\":\"RESET_FAULT\"") >= 0) c = hf::Command::RESET_FAULT;
  if (c == hf::Command::NONE) return;
  xSemaphoreTake(lock, portMAX_DELAY);
  cmdValue = c;
  cmdPending = true;
  xSemaphoreGive(lock);
}

// ---------------------------------------------------------------- task

void task(void*) {
  for (;;) {
    uint32_t now = millis();
    if (WiFi.status() != WL_CONNECTED) {
      linkUp = false;
      if (lastWifiTry == 0 || now - lastWifiTry >= WIFI_RETRY_MS) {
        lastWifiTry = now;
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      }
      vTaskDelay(pdMS_TO_TICKS(250));
      continue;
    }
    if (!timeConfigured) {
      configTime(0, 0, "pool.ntp.org", "time.google.com");  // stored as UTC epoch ms
      timeConfigured = true;
    }

    bool good = true;

    // Events first, then buffered telemetry, a few per pass so live stays fresh.
    for (int i = 0; i < 5 && good; i++) {
      EventMsg e;
      xSemaphoreTake(lock, portMAX_DELAY);
      bool have = peekEvent(e);
      xSemaphoreGive(lock);
      if (!have) break;
      good = ok(request("POST", "events", eventJsonImpl(e)));
      if (good) {
        xSemaphoreTake(lock, portMAX_DELAY);
        dropEvent();
        xSemaphoreGive(lock);
      }
    }
    for (int i = 0; i < 5 && good; i++) {
      Snapshot s;
      xSemaphoreTake(lock, portMAX_DELAY);
      bool have = peekTelemetry(s);
      xSemaphoreGive(lock);
      if (!have) break;
      good = ok(request("POST", "telemetry", telemetryJson(s)));
      if (good) {
        xSemaphoreTake(lock, portMAX_DELAY);
        dropTelemetry();
        xSemaphoreGive(lock);
      }
    }

    if (good && now - lastLiveSent >= LIVE_PERIOD_MS) {
      Snapshot s;
      bool have = false;
      xSemaphoreTake(lock, portMAX_DELAY);
      if (liveFresh) {
        s = liveSnap;
        liveFresh = false;
        have = true;
      }
      xSemaphoreGive(lock);
      if (have) {
        good = ok(request("PUT", "live", liveJsonImpl(s)));
        lastLiveSent = now;
      }
    }

    if (good && now - lastCmdPoll >= COMMAND_POLL_MS) {
      lastCmdPoll = now;
      pollCommand();
    }

    linkUp = good;
    vTaskDelay(pdMS_TO_TICKS(good ? 100 : 2000));
  }
}

}  // namespace

String liveJson(const Snapshot& s) { return liveJsonImpl(s); }
String eventJson(const EventMsg& e) { return eventJsonImpl(e); }

void begin() {
  if (!CLOUD_ENABLED) return;  // no secrets.h: run offline
  lock = xSemaphoreCreateMutex();
  WiFi.mode(WIFI_STA);
  xTaskCreatePinnedToCore(task, "cloud", 12288, nullptr, 1, nullptr, 0);
}

uint64_t epochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  if (tv.tv_sec < 1700000000) return 0;  // NTP not synced yet
  return static_cast<uint64_t>(tv.tv_sec) * 1000ULL + tv.tv_usec / 1000;
}

void publishLive(const Snapshot& s) {
  if (!lock) return;
  xSemaphoreTake(lock, portMAX_DELAY);
  liveSnap = s;
  liveFresh = true;
  xSemaphoreGive(lock);
}

void queueTelemetry(const Snapshot& s) {
  if (!lock) return;
  xSemaphoreTake(lock, portMAX_DELAY);
  int tail = (tHead + tCount) % TELEMETRY_BUFFER;
  telemetry[tail] = s;
  if (tCount < TELEMETRY_BUFFER) tCount++;
  else tHead = (tHead + 1) % TELEMETRY_BUFFER;  // full: drop the oldest sample
  xSemaphoreGive(lock);
}

void queueEvent(const EventMsg& e) {
  if (!lock) return;
  xSemaphoreTake(lock, portMAX_DELAY);
  int tail = (eHead + eCount) % EVENT_BUFFER;
  events[tail] = e;
  if (eCount < EVENT_BUFFER) eCount++;
  else eHead = (eHead + 1) % EVENT_BUFFER;
  xSemaphoreGive(lock);
}

bool takeCommand(hf::Command& out) {
  if (!lock) return false;
  xSemaphoreTake(lock, portMAX_DELAY);
  bool had = cmdPending;
  if (had) {
    out = cmdValue;
    cmdPending = false;
  }
  xSemaphoreGive(lock);
  return had;
}

bool online() { return linkUp; }

int buffered() { return tCount + eCount; }

}  // namespace cloud
