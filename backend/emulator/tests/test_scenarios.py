"""Runs the shared scenarios (tests/scenarios.json) against the Python controller.

    cd backend/emulator
    python -m unittest discover -s tests -v
"""
import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from hybridflow.controller import Controller, Inputs  # noqa: E402

SPEC = json.loads((HERE.parents[2] / "tests" / "scenarios.json").read_text())

FIELD_MAP = {"solarV": "solar_v", "tankPct": "tank_pct", "tempC": "temp_c", "pumpA": "pump_a",
             "flowLpm": "flow_lpm", "floatHigh": "tank_float_high"}


def apply(inp: Inputs, overrides: dict) -> None:
    for key, value in overrides.items():
        if key in ("z1", "z2"):
            inp.moisture[0 if key == "z1" else 1] = math.nan if value is None else float(value)
        else:
            setattr(inp, FIELD_MAP[key], value)


def run(scenario: dict) -> list[str]:
    errors = []
    c = Controller()
    c.begin(0)
    inp = Inputs()
    apply(inp, SPEC["defaults"])
    apply(inp, scenario.get("init", {}))
    t, tick = 0, SPEC["tickMs"]
    volts, pf = SPEC["meter"]["volts"], SPEC["meter"]["powerFactor"]
    prev_pump = prev_relay = False

    for i, step in enumerate(scenario["steps"], start=1):
        apply(inp, step.get("in", {}))
        if step.get("cmd"):
            c.command(step["cmd"], t)
        seen = []
        for _ in range(step["ms"] // tick):
            t += tick
            o = c.update(t, inp)
            c.meter(t, volts, pf)
            if o.pump_on and not any(o.valve):
                errors.append(f"step {i}: pump on with every valve closed at {t} ms")
            if o.relay_grid != prev_relay and (o.pump_on or prev_pump):
                errors.append(f"step {i}: source relay moved while the pump was on at {t} ms")
            prev_pump, prev_relay = o.pump_on, o.relay_grid
            seen += [e["type"] for e in c.pop_events()]

        o = c.out
        actual = {
            "phase": c.phase, "source": c.source, "relay": "GRID" if o.relay_grid else "SOLAR",
            "fault": c.fault, "mode": c.mode, "pump": o.pump_on, "valve1": o.valve[0],
            "valve2": o.valve[1], "alertLed": o.alert_led, "switches": c.totals.switches,
            "solarWh": c.totals.solar_wh, "gridWh": c.totals.grid_wh, "litres": c.totals.litres,
        }
        for key, want in step.get("expect", {}).items():
            got = actual[key]
            if isinstance(want, list):
                if not (want[0] - 1e-9 <= got <= want[1] + 1e-9):
                    errors.append(f"step {i}: {key} expected {want[0]}..{want[1]}, got {got:.4f}")
            elif got != want:
                errors.append(f"step {i}: {key} expected {want}, got {got}")
        for ev in step.get("events", []):
            if ev not in seen:
                errors.append(f"step {i}: expected event {ev}")
    return errors


class SharedScenarios(unittest.TestCase):
    pass


def _make(scenario):
    def test(self):
        errors = run(scenario)
        self.assertFalse(errors, "\n" + "\n".join(errors))
    return test


for _sc in SPEC["scenarios"]:
    setattr(SharedScenarios, "test_" + _sc["name"], _make(_sc))


if __name__ == "__main__":
    unittest.main(verbosity=2)
