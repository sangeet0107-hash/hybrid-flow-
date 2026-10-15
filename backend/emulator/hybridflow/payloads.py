"""Builds the JSON documents the firmware publishes (see docs/data-model.md),
so the emulator and the Streamlit simulator produce exactly the same shapes."""
from __future__ import annotations

import math
import time

from .controller import Controller, severity_of


def clean(x, digits=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), digits)


def epoch_ms() -> int:
    return int(time.time() * 1000)


def live_payload(c: Controller, plant, inp, uptime_s: int, rssi: int = -60, fw: str = "emulator-0.1.0") -> dict:
    o, t = c.out, c.totals
    return {
        "ts": epoch_ms(),
        "uptimeS": uptime_s,
        "fw": fw,
        "simClock": plant.clock_text(),
        "simActive": plant.active(),
        "sensors": {
            "solarV": clean(inp.solar_v),
            "soil": {"z1": clean(inp.moisture[0], 1), "z2": clean(inp.moisture[1], 1)},
            "tankPct": clean(inp.tank_pct, 1),
            "floatHigh": inp.tank_float_high,
            "tempC": clean(inp.temp_c, 1),
            "humidity": clean(plant.humidity, 1),
            "lightPct": clean(plant.light, 0),
            "pumpA": clean(inp.pump_a),
            "flowLpm": clean(inp.flow_lpm, 1),
        },
        "state": {
            "source": c.source,
            "relay": "GRID" if o.relay_grid else "SOLAR",
            "pump": o.pump_on,
            "valves": {"z1": o.valve[0], "z2": o.valve[1]},
            "zone": c.zone + 1,
            "phase": c.phase,
            "mode": c.mode,
            "fault": c.fault,
            "solarAvailable": c.solar_avail,
            "tempAlert": c.temp_alert,
            "tankFull": c.tank_full,
            "buzzer": o.buzzer,
            "lastStop": c.last_stop,
        },
        "totals": {
            "solarWh": clean(t.solar_wh), "gridWh": clean(t.grid_wh), "litres": clean(t.litres, 1),
            "litresZ1": clean(t.litres_zone[0], 1), "litresZ2": clean(t.litres_zone[1], 1),
            "switches": t.switches, "faults": t.faults,
        },
        "net": {"rssi": rssi, "buffered": 0},
    }


def telemetry_payload(c: Controller, inp) -> dict:
    t = c.totals
    return {
        "ts": epoch_ms(), "solarV": clean(inp.solar_v), "z1": clean(inp.moisture[0], 1),
        "z2": clean(inp.moisture[1], 1), "tankPct": clean(inp.tank_pct, 1), "tempC": clean(inp.temp_c, 1),
        "pumpA": clean(inp.pump_a), "flowLpm": clean(inp.flow_lpm, 1), "source": c.source,
        "pump": c.out.pump_on, "solarWh": clean(t.solar_wh), "gridWh": clean(t.grid_wh),
        "litres": clean(t.litres, 1),
    }


def event_payload(e: dict) -> dict:
    value = e["value"] if isinstance(e["value"], (int, float)) else 0
    body = {"ts": epoch_ms(), "type": e["type"], "sev": severity_of(e["type"]),
            "zone": e["zone"] + 1, "value": clean(value) if clean(value) is not None else 0}
    if e.get("detail"):
        body["detail"] = e["detail"]
    return body
