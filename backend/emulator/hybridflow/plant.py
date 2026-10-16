"""A simple model of the farm the controller is attached to.

It stands in for the real sensors so the whole pipeline can be demonstrated
without hardware: sun and cloud drive the panel voltage, evapotranspiration
dries the soil, irrigation wets it, and the pump draws current and moves water
depending on its state (normal, dry tank, blocked line, jammed rotor).

Rates are sped up so a full irrigation cycle takes about a minute.
"""
from __future__ import annotations

import math
import random

from .controller import Inputs, Outputs

SCENARIOS = ("CLOUD", "NIGHT", "DAY", "DRY_TANK", "BLOCKAGE", "JAM", "HEATWAVE", "TANK_FULL", "WIFI_DROP", "CLEAR")

# Guided demo used by --tour and by the dashboard's "Run guided demo" button.
# Each step fires once `after` seconds have passed AND the condition holds
# (or `wait` more seconds pass without it). Actions are scenarios or the
# operator command RESET_FAULT.
TOUR = [
    {"after": 6, "when": "running", "wait": 30, "action": "CLOUD",
     "note": "Cloud covers the panel while Zone 2 is below 30 %: after the 5 s debounce the pump changes over to grid, break-before-make."},
    {"after": 95, "when": "running", "wait": 60, "action": "DRY_TANK",
     "note": "The supply tank runs dry: pump current falls under 0.5 A and the dry-run trip stops it within 3 s."},
    {"after": 8, "when": "fault", "wait": 0, "action": "RESET_FAULT",
     "note": "Operator refills the tank and resets the fault from the dashboard."},
    {"after": 15, "when": "running", "wait": 60, "action": "BLOCKAGE",
     "note": "A line blocks: current is normal but flow stays under 1 L/min, so the no-flow check trips after the 5 s start-up delay."},
    {"after": 8, "when": "fault", "wait": 0, "action": "RESET_FAULT",
     "note": "Line cleared and fault reset."},
    {"after": 15, "when": "any", "wait": 0, "action": "WIFI_DROP",
     "note": "Wi-Fi drops for 45 s. Control continues on the device; telemetry is buffered and uploaded on reconnect."},
    {"after": 55, "when": "any", "wait": 0, "action": "HEATWAVE",
     "note": "Air temperature passes 45 C: irrigation stops and the alarm sounds until it cools below 43 C."},
    {"after": 50, "when": "any", "wait": 0, "action": "TANK_FULL",
     "note": "Tank reaches 95 %: valves close and irrigation waits until it falls below 90 %."},
    {"after": 45, "when": "running", "wait": 60, "action": "JAM",
     "note": "The impeller jams: current jumps above 8 A and the over-current trip fires once the 1 s inrush window has passed."},
    {"after": 8, "when": "fault", "wait": 0, "action": "RESET_FAULT",
     "note": "Pump freed and fault reset. End of the guided demo."},
]


class Plant:
    def __init__(self, start_hour: float = 10.5, sim_minutes_per_second: float = 0.2, seed: int | None = None):
        self.rng = random.Random(seed)
        self.clock_min = start_hour * 60          # simulated time of day
        self.speed = sim_minutes_per_second
        self.moisture = [44.0, 20.0]              # % VWC; zone 2 is sandier and dries faster
        self.tank = 62.0                          # % of the supply tank
        self.inlet_on = True
        self.cloud_until = 0.0                    # real-time seconds
        self.heat_until = 0.0
        self.dry_until = 0.0
        self.overfill_until = 0.0
        self.wifi_down_until = 0.0
        self.blocked = False
        self.jammed = False
        self.pump_on_since: float | None = None
        self.t = 0.0                              # real seconds since start
        self.light = 0.0
        self.humidity = 50.0
        self.temp = 30.0
        self.solar_v = 0.0
        self.pump_a = 0.0
        self.flow = 0.0

    # ------------------------------------------------------------ scenarios
    def _force_run(self) -> None:
        """Pump faults only show while the pump runs: if it's idle, dry Zone 1
        below the critical level so the controller starts watering it."""
        if self.pump_on_since is None:
            self.moisture[0] = min(self.moisture[0], 26.0)

    def trigger(self, name: str) -> None:
        if name == "CLOUD":
            self.cloud_until = self.t + 40
            # Make Zone 2 critical so the grid changeover is visible.
            self.moisture[1] = min(self.moisture[1], 24.0)
        elif name == "NIGHT":
            self.clock_min = 19.5 * 60
        elif name == "DAY":
            self.clock_min = 10 * 60
        elif name == "DRY_TANK":
            self.tank = 2.0
            self.dry_until = self.t + 90
            self._force_run()
        elif name == "BLOCKAGE":
            self.blocked = True
            self._force_run()
        elif name == "JAM":
            self.jammed = True
            self._force_run()
        elif name == "HEATWAVE":
            self.heat_until = self.t + 40
        elif name == "TANK_FULL":
            self.tank = 96.0
            self.overfill_until = self.t + 20
        elif name == "WIFI_DROP":
            self.wifi_down_until = self.t + 45
        elif name == "CLEAR":
            self.cloud_until = self.heat_until = self.dry_until = self.overfill_until = 0
            self.wifi_down_until = 0
            self.blocked = self.jammed = False
            if self.tank < 20:
                self.tank = 55.0

    def fault_reset(self) -> None:
        """A technician fixed the cause before pressing reset."""
        self.blocked = self.jammed = False
        if self.tank < 20:
            self.tank = 55.0
            self.dry_until = 0

    @property
    def wifi_down(self) -> bool:
        return self.t < self.wifi_down_until

    def active(self) -> list[str]:
        out = []
        if self.t < self.cloud_until:
            out.append("CLOUD")
        if self.t < self.heat_until:
            out.append("HEATWAVE")
        if self.t < self.dry_until:
            out.append("DRY_TANK")
        if self.t < self.overfill_until:
            out.append("TANK_FULL")
        if self.wifi_down:
            out.append("WIFI_DROP")
        if self.blocked:
            out.append("BLOCKAGE")
        if self.jammed:
            out.append("JAM")
        return out

    # ------------------------------------------------------------ physics
    def irradiance(self) -> float:
        h = (self.clock_min / 60) % 24
        sun = math.sin(math.pi * (h - 6) / 12) if 6 <= h <= 18 else 0.0
        if self.t < self.cloud_until:
            sun *= 0.22
        return max(0.0, sun)

    def step(self, dt: float, out: Outputs) -> Inputs:
        r = self.rng
        self.t += dt
        self.clock_min = (self.clock_min + dt * self.speed) % 1440
        irr = self.irradiance()
        noise = lambda s: r.uniform(-s, s)  # noqa: E731

        self.solar_v = 0.0 if irr < 0.03 else 22.0 * irr ** 0.18 + noise(0.12)
        self.light = min(100.0, max(0.0, irr * 100 + noise(1.5) + 1.5))
        heat = 16.0 if self.t < self.heat_until else 0.0
        self.temp = 24 + 9 * irr + heat + noise(0.2)
        self.humidity = 72 - 28 * irr - heat + noise(0.5)

        # Pump hydraulics and current
        if out.pump_on:
            if self.pump_on_since is None:
                self.pump_on_since = self.t
            running_for = self.t - self.pump_on_since
            if running_for < 0.4:
                self.pump_a, self.flow = 14.0 + noise(1.0), 2.0
            elif self.jammed:
                self.pump_a, self.flow = 11.5 + noise(0.3), 0.0
            elif self.tank < 3:
                self.pump_a, self.flow = 0.3 + noise(0.05), 0.0
            elif self.blocked:
                self.pump_a, self.flow = 3.4 + noise(0.1), 0.2 + noise(0.1)
            else:
                self.pump_a = 4.2 + noise(0.12)
                self.flow = 12.4 + noise(0.4) - (0.0 if out.valve[0] else 0.8)
        else:
            self.pump_on_since = None
            self.pump_a, self.flow = 0.0, 0.0
        self.flow = max(0.0, self.flow)

        # Soil water balance (per real second)
        et = (0.03 + 0.10 * irr) * (self.temp / 30)
        for z in range(2):
            gain = 0.7 * self.flow / 12 if out.valve[z] else 0.0
            dry = et * (1.3 if z == 1 else 1.0)
            self.moisture[z] = min(100.0, max(5.0, self.moisture[z] + (gain - dry) * dt))

        # Supply tank: drained by the pump, topped up by an inlet
        if self.t < self.dry_until:
            inflow = 0.0
        elif self.t < self.overfill_until:
            inflow = 0.25
        else:
            inflow = 0.05 if self.tank < 75 else 0.0
        self.tank = min(100.0, max(0.0, self.tank + (inflow - 0.13 * self.flow / 12) * dt))
        if self.tank > 88 and self.t >= self.overfill_until:
            self.tank -= 0.4 * dt  # overflow pipe drains the excess once the inlet stops

        return Inputs(
            solar_v=self.solar_v,
            moisture=[m + noise(0.15) for m in self.moisture],
            tank_pct=self.tank,
            temp_c=self.temp,
            pump_a=self.pump_a,
            flow_lpm=self.flow,
            tank_float_high=self.tank >= 98,
        )

    def clock_text(self) -> str:
        m = int(self.clock_min)
        return f"{m // 60:02d}:{m % 60:02d}"


class TourRunner:
    """Steps through TOUR, firing each action when its time and condition are met."""

    def __init__(self):
        self.index = 0
        self.step_started = 0.0

    @property
    def done(self) -> bool:
        return self.index >= len(TOUR)

    def poll(self, elapsed: float, phase: str):
        """Returns the step to fire now, or None."""
        if self.done:
            return None
        step = TOUR[self.index]
        waited = elapsed - self.step_started
        if waited < step["after"]:
            return None
        cond = step["when"]
        ok = (cond == "any" or (cond == "running" and phase == "RUNNING")
              or (cond == "fault" and phase == "FAULT"))
        if ok or waited >= step["after"] + step["wait"] and cond != "fault":
            self.index += 1
            self.step_started = elapsed
            return step
        return None
