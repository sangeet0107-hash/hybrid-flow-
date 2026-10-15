# Firebase data model

Everything for one controller lives under `/devices/<deviceId>` in the Realtime Database. The ESP32 firmware, the Wokwi simulation and `backend/emulator` all write the same shapes, so the Streamlit and web dashboards work with any of them.

| Path | Written by | How | Purpose |
|---|---|---|---|
| `live` | device | `PUT` every 2 s | Latest state, overwritten each time |
| `telemetry/<pushId>` | device | `POST` every 10 s (5 s from the emulator) | History for the charts; buffered on the device while offline |
| `events/<pushId>` | device | `POST` when something happens | Switching, zone, fault and alert log |
| `command` | dashboard | `PUT` | Operator command; the device polls it every 3 s |
| `sim` | dashboard | `PUT` | Test scenario for the emulator only; real hardware ignores it |

Timestamps (`ts`) are UTC epoch milliseconds. Before the ESP32 has synced NTP it sends `{".sv": "timestamp"}` and Firebase fills in the arrival time.

## `live`

```json
{
  "ts": 1760501400000,
  "uptimeS": 3605,
  "fw": "0.1.0",
  "sensors": {
    "solarV": 19.8,
    "soil": { "z1": 44.0, "z2": 27.5 },
    "tankPct": 61.0,
    "floatHigh": false,
    "tempC": 32.4,
    "humidity": 48.0,
    "lightPct": 83,
    "pumpA": 4.21,
    "flowLpm": 12.3
  },
  "state": {
    "source": "SOLAR",
    "relay": "SOLAR",
    "pump": true,
    "valves": { "z1": false, "z2": true },
    "zone": 2,
    "phase": "RUNNING",
    "mode": "AUTO",
    "fault": "NONE",
    "solarAvailable": true,
    "tempAlert": false,
    "tankFull": false,
    "buzzer": false,
    "lastStop": "NONE"
  },
  "totals": {
    "solarWh": 66.0, "gridWh": 8.7, "litres": 64.2,
    "litresZ1": 30.1, "litresZ2": 34.1, "switches": 2, "faults": 3
  },
  "net": { "rssi": -61, "buffered": 0 }
}
```

- `sensors.*` is `null` when a reading is invalid (unplugged probe, failed DHT22 read, ultrasonic timeout).
- `state.source` is the source powering the pump right now (`SOLAR`, `GRID` or `NONE` when the pump is off). `state.relay` is the CH1 contact position.
- `state.zone` is 1 or 2, or 0 when no zone is active.
- `state.phase` is one of `IDLE`, `VALVE_OPENING`, `RUNNING`, `SWITCH_BREAK`, `SWITCH_SETTLE`, `STOPPING`, `FAULT`.
- `state.fault` is `NONE`, `DRY_RUN`, `OVER_CURRENT` or `NO_FLOW`. Faults latch until a `RESET_FAULT` command.
- `state.lastStop` explains why the last zone run ended: `TARGET_REACHED`, `TANK_FULL`, `HOLD`, `TEMP_ALERT`, `SOLAR_LOST`, `SENSOR_INVALID`.
- The emulator and the Streamlit simulator add `simClock` (field time of day) and `simActive` (injected scenarios).

## `telemetry/<pushId>`

```json
{ "ts": 1760501400000, "solarV": 19.8, "z1": 44.0, "z2": 27.5, "tankPct": 61.0, "tempC": 32.4,
  "pumpA": 4.21, "flowLpm": 12.3, "source": "SOLAR", "pump": true,
  "solarWh": 66.0, "gridWh": 8.7, "litres": 64.2 }
```

## `events/<pushId>`

```json
{ "ts": 1760501400000, "type": "SOURCE_CHANGED", "sev": "info", "zone": 2, "value": 0, "detail": "GRID" }
```

`sev` is `info`, `warn` or `crit`. Types: `BOOT`, `SOLAR_AVAILABLE`, `SOLAR_LOST`, `SOURCE_CHANGED`, `ZONE_START`, `ZONE_DONE`, `ZONE_STOPPED`, `FAULT_DRY_RUN`, `FAULT_OVER_CURRENT`, `FAULT_NO_FLOW`, `FAULT_CLEARED`, `TANK_FULL`, `TANK_OK`, `TEMP_ALERT`, `TEMP_OK`, `SENSOR_WARN`, `MODE_HOLD`, `MODE_AUTO`. `detail` carries the stop reason for `ZONE_DONE`/`ZONE_STOPPED` and the new source for `SOURCE_CHANGED`.

## `command`

```json
{ "seq": 1760501400000, "action": "HOLD", "ts": { ".sv": "timestamp" } }
```

`action` is `HOLD`, `AUTO` or `RESET_FAULT`. The device acts on a command only when `seq` is higher than the last one it saw, and ignores whatever is stored when it boots, so an old command is never replayed.

## `sim`

```json
{ "seq": 1760501400000, "scenario": "CLOUD" }
```

`scenario` is one of `CLOUD`, `NIGHT`, `DAY`, `DRY_TANK`, `BLOCKAGE`, `JAM`, `HEATWAVE`, `TANK_FULL`, `WIFI_DROP`, `CLEAR`.

## Security

`backend/firebase/database.rules.json` validates every write but lets anyone with the URL read and write `/devices`. That is fine for a demo. Before a field deployment, give each device a Firebase Auth identity and restrict `live`, `telemetry` and `events` to that device, and `command` to signed-in operators.
