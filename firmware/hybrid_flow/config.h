// Hybrid-Flow hardware configuration: pins, calibration and cloud timing.
// Control thresholds live in hf::Config (control_logic.h).
#pragma once

// ---------------------------------------------------------------- device
#define DEVICE_ID "hf-001"
#define FW_VERSION "0.1.0"
#define LOOP_MS 100                 // 10 Hz control loop

// Set to 1 to run in the Wokwi simulator (the PlatformIO "wokwi" env does this
// for you). Changes: relay modules are active-high, and pump current and flow
// come from potentiometers that read only while the pump is on.
#ifndef WOKWI_SIM
#define WOKWI_SIM 0
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
#define PIN_FLOW_POT     36         // Wokwi only: flow potentiometer on VP (no flow sensor part in Wokwi)

#define PIN_RELAY_SOURCE 25         // CH1: de-energised = solar contact, energised = grid
#define PIN_RELAY_ZONE1  16         // CH2: Zone 1 solenoid
#define PIN_RELAY_ZONE2  17         // CH3: Zone 2 solenoid
#define PIN_PUMP_SSR     18         // SSR-25DA input (through a transistor if 3.3 V is marginal)
#define PIN_BUZZER       19
#define PIN_ALERT_LED    23

#if WOKWI_SIM
#define RELAY_ACTIVE_LOW 0          // Wokwi relay modules switch on HIGH
#else
#define RELAY_ACTIVE_LOW 1          // typical 4-channel relay modules switch on LOW
#endif
#define FLOAT_ACTIVE_LOW 1          // float closes to GND at the overflow level

// ---------------------------------------------------------------- calibration
// Solar divider 47 k / 6.8 k: Vin = Vadc * (47 + 6.8) / 6.8, so 26 V full scale.
// The common 30 k / 7.5 k module (ratio 5) is built for 5 V ADCs: on the
// ESP32's 3.3 V input it tops out at 16.5 V, below the 18 V threshold, and an
// open-circuit panel (~22 V) would push the pin past 3.3 V.
#define SOLAR_DIVIDER_RATIO 7.91f

// Capacitive soil probes read higher when dry. Measure each probe in dry air
// and in a glass of water, then put the millivolt readings here.
#define SOIL_DRY_MV   2550.0f
#define SOIL_WET_MV   1150.0f
#define SOIL_MIN_VALID_MV 300.0f    // below this the probe is unplugged or shorted
#define SOIL_MAX_VALID_MV 3200.0f

// HC-SR04 mounted above the tank, distances in cm
#define TANK_EMPTY_CM 120.0f
#define TANK_FULL_CM   10.0f

// ACS712-20A: 100 mV/A around a mid-supply zero. Its 5 V output is divided
// to stay under 3.3 V (10 k / 20 k -> x0.667), so multiply back by 1.5.
#define ACS_MV_PER_A        100.0f
#define ACS_DIVIDER_GAIN    1.5f
#define ACS_NOISE_FLOOR_A   0.15f
#define ACS_SAMPLE_WINDOW_MS 40     // two mains cycles at 50 Hz for the RMS

// YF-S201: pulse frequency (Hz) = 7.5 x flow (L/min)
#define FLOW_PULSES_PER_LPM 7.5f

// LDR divider: higher voltage = brighter. Set to 1 if your circuit is the other way round.
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
#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.example.h to secrets.h and fill in your Wi-Fi and Firebase details"
#endif
