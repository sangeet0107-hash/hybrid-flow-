// Hybrid-Flow hardware configuration: pins, calibration and cloud timing.
// Control thresholds live in hf::Config (control_logic.h).
#pragma once

// ---------------------------------------------------------------- device
#define DEVICE_ID "hf-001"
#define FW_VERSION "0.1.0"
#define LOOP_MS 100                 // 10 Hz control loop

// ---------------------------------------------------------------- build profile
// WOKWI_SIM 1: running in the Wokwi simulator, whose relay modules switch on
// HIGH (the PlatformIO "wokwi" env sets this). The Wokwi circuit has knobs only.
#ifndef WOKWI_SIM
#define WOKWI_SIM 0
#endif
#if WOKWI_SIM && !defined(SIM_INPUTS)
#define SIM_INPUTS 1
#endif

// Each input is either its real sensor (1) or a bench knob (0).
// Default (no flags): the bench with real sensors. Soil probes, the ultrasonic
// tank level with its float switch, the DHT22 and the LDR are real; knobs stand
// in for the solar voltage, the pump current and the water flow.
// SIM_INPUTS=1: every input is a knob (Wokwi, the original six-knob bench).
// SIM_INPUTS=0: every input is real (field build, `pio run -e field`).
// Any single line below can be changed on its own, e.g. REAL_SOLAR 1 once a
// panel is wired through the 47 k / 6.8 k divider.
#if defined(SIM_INPUTS)
#define HF_PICK(bench) (!(SIM_INPUTS))
#else
#define HF_PICK(bench) (bench)
#endif
#if defined(USE_DHT22) && !defined(REAL_DHT22)
#define REAL_DHT22 USE_DHT22        // older name for the same switch
#endif

#ifndef REAL_SOLAR
#define REAL_SOLAR   HF_PICK(0)     // 0: knob on GPIO34 · 1: panel through the divider on GPIO34
#endif
#ifndef REAL_SOIL
#define REAL_SOIL    HF_PICK(1)     // 1: capacitive probes on GPIO35 / GPIO39 · 0: knobs there
#endif
#ifndef REAL_TANK
#define REAL_TANK    HF_PICK(1)     // 1: HC-SR04 on GPIO13/14 + float switch on GPIO26 · 0: knob on GPIO32
#endif
#ifndef REAL_DHT22
#define REAL_DHT22   HF_PICK(1)     // 1: DHT22 on GPIO4 (10 k pull-up to 3V3) · 0: fixed SIM_TEMP_C
#endif
#ifndef REAL_LDR
#define REAL_LDR     HF_PICK(1)     // 1: LDR divider (or module AO) on GPIO32 · 0: brightness follows the solar reading
#endif
#ifndef REAL_CURRENT
#define REAL_CURRENT HF_PICK(0)     // 0: knob on GPIO33 · 1: ACS712 on GPIO33
#endif
#ifndef REAL_FLOW
#define REAL_FLOW    HF_PICK(0)     // 0: knob on GPIO36 · 1: YF-S201 pulses on GPIO27
#endif

#define ALL_REAL  (REAL_SOLAR && REAL_SOIL && REAL_TANK && REAL_DHT22 && REAL_LDR && REAL_CURRENT && REAL_FLOW)
#define ALL_KNOBS (!REAL_SOLAR && !REAL_SOIL && !REAL_TANK && !REAL_LDR && !REAL_CURRENT && !REAL_FLOW)

#if REAL_LDR && !REAL_TANK
#error "GPIO32 can't be both the LDR and the tank knob: set REAL_TANK 1 (HC-SR04) or REAL_LDR 0"
#endif

// PUMP_ON_RELAY 1: the pump is switched by relay channel 4 (any bench build).
// 0: by the SSR-25DA (field build).
#ifndef PUMP_ON_RELAY
#if defined(SIM_INPUTS) && !(SIM_INPUTS)
#define PUMP_ON_RELAY 0
#else
#define PUMP_ON_RELAY 1
#endif
#endif

// ---------------------------------------------------------------- pins (Review 1, section VII-A)
// Analog inputs must be ADC1 pins: ADC2 is unusable while Wi-Fi is on.
#define PIN_SOLAR_V      34
#define PIN_SOIL_Z1      35
#define PIN_SOIL_Z2      39         // second probe (VN, input-only); the review table lists one soil pin
#define PIN_LDR          32
#define PIN_CURRENT      33
#define PIN_DHT          4
#define PIN_FLOAT        26         // overflow float switch to GND
#define PIN_FLOW         27         // YF-S201 pulse output, interrupt
#define PIN_US_TRIG      13         // HC-SR04 trigger
#define PIN_US_ECHO      14         // HC-SR04 echo through a 5 V -> 3.3 V divider

// Bench knobs. The solar, soil and current knobs use the sensor pins above;
// these two are extra.
#define PIN_TANK_POT     32         // tank level knob (only when REAL_TANK 0; GPIO32 is the LDR's pin)
#define PIN_FLOW_POT     36         // water flow knob on VP

#define PIN_RELAY_SOURCE 25         // CH1: de-energised = solar contact, energised = grid
#define PIN_RELAY_ZONE1  16         // CH2: Zone 1 solenoid
#define PIN_RELAY_ZONE2  17         // CH3: Zone 2 solenoid
#define PIN_PUMP_SSR     18         // pump: relay CH4 (bench) or SSR-25DA input (field)
#define PIN_BUZZER       19
#define PIN_ALERT_LED    23

#if WOKWI_SIM
#define RELAY_ACTIVE_LOW 0          // Wokwi relay modules switch on HIGH
#else
#define RELAY_ACTIVE_LOW 1          // typical 4-channel relay modules switch on LOW
#endif
#if PUMP_ON_RELAY
#define PUMP_ACTIVE_LOW RELAY_ACTIVE_LOW
#else
#define PUMP_ACTIVE_LOW 0           // SSR input is on when HIGH
#endif
#define FLOAT_ACTIVE_LOW 1          // float closes to GND at the overflow level
#define BUZZER_ACTIVE_LOW 0         // set to 1 if your buzzer module beeps when it should be quiet

// ---------------------------------------------------------------- bench knob ranges
// A knob turned fully clockwise reads this many millivolts (the ESP32 ADC
// tops out a little under 3.3 V) and maps to the maximum below.
#define KNOB_FULL_MV       3100.0f
#define SIM_SOLAR_MAX_V    25.0f    // solar knob: 0-25 V, threshold 18 V at 72 %
#define SIM_CURRENT_MAX_A  12.0f    // current knob: 0-12 A, normal ~4 A, dry < 0.5 A, trip > 8 A
#define SIM_FLOW_MAX_LPM   20.0f    // flow knob: 0-20 L/min, normal ~12, no-flow < 1
#define SIM_TEMP_C         30.0f    // used when REAL_DHT22 is 0
#define SIM_HUMIDITY       50.0f

// ---------------------------------------------------------------- calibration
// Solar divider 47 k / 6.8 k: Vin = Vadc * (47 + 6.8) / 6.8, so 26 V full scale.
// The common 30 k / 7.5 k module (ratio 5) is built for 5 V ADCs: on the
// ESP32's 3.3 V input it tops out at 16.5 V, below the 18 V threshold, and an
// open-circuit panel (~22 V) would push the pin past 3.3 V.
#define SOLAR_DIVIDER_RATIO 7.91f

// Capacitive soil probes read higher when dry. Type c in the Serial Monitor to
// see each probe's millivolts: note the reading in dry air and in a glass of
// water, then put them here.
#define SOIL_DRY_MV   2550.0f
#define SOIL_WET_MV   1150.0f
#define SOIL_MIN_VALID_MV 300.0f    // below this the probe is unplugged or shorted
#define SOIL_MAX_VALID_MV 3200.0f

// HC-SR04 mounted above the tank, distances in cm. On the bench (pump on the
// relay) the "tank" is whatever the sensor faces: 50 cm away reads empty, and a
// hand within about 7 cm reads 95 % (tank full).
#if PUMP_ON_RELAY
#define TANK_EMPTY_CM  50.0f
#define TANK_FULL_CM    5.0f
#else
#define TANK_EMPTY_CM 120.0f
#define TANK_FULL_CM   10.0f
#endif
#define TANK_ECHO_TIMEOUT_US 25000  // ~4 m round trip; nothing in range reads as empty
#define TANK_MISSES_ALLOWED  10     // keep the last good reading through 1 s of missed echoes

// ACS712-20A: 100 mV/A around a mid-supply zero. Its 5 V output is divided
// to stay under 3.3 V (10 k / 20 k -> x0.667), so multiply back by 1.5.
#define ACS_MV_PER_A        100.0f
#define ACS_DIVIDER_GAIN    1.5f
#define ACS_NOISE_FLOOR_A   0.15f
#define ACS_SAMPLE_WINDOW_MS 40     // two mains cycles at 50 Hz for the RMS

// YF-S201: pulse frequency (Hz) = 7.5 x flow (L/min)
#define FLOW_PULSES_PER_LPM 7.5f

// LDR divider: 3V3 -> LDR -> GPIO32 -> 10 k -> GND, so a higher voltage = brighter.
// Set to 1 if your circuit is the other way round (covering the LDR raises the reading).
#define LDR_INVERT 0

// Metering: the pump runs on 230 V AC from either source (the solar side
// feeds it through an inverter), so energy = 230 V x I(rms) x PF.
#define SUPPLY_VRMS   230.0f
#define POWER_FACTOR  0.8f

// ---------------------------------------------------------------- cloud
#define LIVE_PERIOD_MS       2000   // overwrite /live
#define TELEMETRY_PERIOD_MS  10000  // append to /telemetry
#define COMMAND_POLL_MS      3000   // read /command
#define WIFI_RETRY_MS        10000
#define TELEMETRY_BUFFER     180    // 30 min of samples kept while offline
#define EVENT_BUFFER         64

// Wi-Fi and Firebase credentials live in secrets.h (copy secrets.example.h).
// Without secrets.h the firmware runs offline: control, relays, buzzer and the
// USB link to the Streamlit dashboard all work; only Firebase is skipped.
#if __has_include("secrets.h")
#include "secrets.h"
#define CLOUD_ENABLED 1
#else
#define CLOUD_ENABLED 0
#define WIFI_SSID ""
#define WIFI_PASSWORD ""
#define FIREBASE_DB_URL ""
#define FIREBASE_AUTH ""
#endif

// USB link: one JSON line per second for the Streamlit dashboard ("ESP32 over USB").
#define SERIAL_JSON_PERIOD_MS 1000
