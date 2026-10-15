"""Python port of the firmware control logic (firmware/hybrid_flow/control_logic.cpp).

Kept line-for-line equivalent so the emulator behaves like the real ESP32.
Both are checked against the same scenarios in tests/scenarios.json.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ZONES = 2

# Phases
IDLE, VALVE_OPENING, RUNNING, SWITCH_BREAK, SWITCH_SETTLE, STOPPING, FAULT = (
    "IDLE", "VALVE_OPENING", "RUNNING", "SWITCH_BREAK", "SWITCH_SETTLE", "STOPPING", "FAULT")

SEVERITY = {
    "FAULT_DRY_RUN": "crit", "FAULT_OVER_CURRENT": "crit", "FAULT_NO_FLOW": "crit",
    "SOLAR_LOST": "warn", "TANK_FULL": "warn", "TEMP_ALERT": "warn", "SENSOR_WARN": "warn",
    "ZONE_STOPPED": "warn", "MODE_HOLD": "warn",
}


def severity_of(event_type: str) -> str:
    return SEVERITY.get(event_type, "info")


@dataclass
class Config:
    solar_on_v: float = 18.0
    debounce_ms: int = 5000
    moisture_critical: float = 30.0
    moisture_solar_start: float = 50.0
    moisture_target: float = 60.0
    tank_overflow_pct: float = 95.0
    tank_resume_pct: float = 90.0
    temp_max_c: float = 45.0
    temp_min_c: float = 0.0
    temp_hyst_c: float = 2.0
    inrush_ms: int = 1000
    dry_run_a: float = 0.5
    dry_run_ms: int = 3000
    over_current_a: float = 8.0
    no_flow_lpm: float = 1.0
    no_flow_ms: int = 5000
    startup_delay_ms: int = 5000
    dead_time_ms: int = 200
    valve_open_ms: int = 1000
    valve_close_delay_ms: int = 500


@dataclass
class Inputs:
    solar_v: float = 0.0
    moisture: list = field(default_factory=lambda: [0.0, 0.0])  # NaN = invalid probe
    tank_pct: float = 0.0
    temp_c: float = 25.0
    pump_a: float = 0.0
    flow_lpm: float = 0.0
    tank_float_high: bool = False


@dataclass
class Outputs:
    relay_grid: bool = False
    pump_on: bool = False
    valve: list = field(default_factory=lambda: [False, False])
    buzzer: bool = False
    alert_led: bool = False


@dataclass
class Totals:
    solar_wh: float = 0.0
    grid_wh: float = 0.0
    litres: float = 0.0
    litres_zone: list = field(default_factory=lambda: [0.0, 0.0])
    switches: int = 0
    faults: int = 0


def _valid(x) -> bool:
    return x is not None and not math.isnan(x)


def _probe_ok(m) -> bool:
    return _valid(m) and 0.0 <= m <= 100.0


class Controller:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.inp = Inputs()
        self.out = Outputs()
        self.totals = Totals()
        self.phase = IDLE
        self.phase_since = 0
        self.source = "NONE"
        self.switch_to = "NONE"
        self.fault = "NONE"
        self.mode = "AUTO"
        self.zone = -1
        self.last_stop = "NONE"
        self.started = False
        self.solar_avail = False
        self.solar_candidate = False
        self.solar_candidate_since = 0
        self.tank_full = False
        self.temp_alert = False
        self.temp_warned = False
        self.moisture_warned = [False] * ZONES
        self.run_since = 0
        self.dry_timing = False
        self.dry_since = 0
        self.no_flow_timing = False
        self.no_flow_since = 0
        self.chirp_until = 0
        self.last_meter_ms = 0
        self.meter_started = False
        self.events: list[dict] = []

    # ------------------------------------------------------------ events
    def begin(self, now: int) -> None:
        self.phase, self.phase_since = IDLE, now
        self.source, self.fault, self.mode, self.zone = "NONE", "NONE", "AUTO", -1
        self.started = False
        self.out = Outputs()
        self._emit(now, "BOOT")

    def _emit(self, now, etype, zone=-1, value=0.0, detail=None):
        ev = {"ms": now, "type": etype, "zone": zone, "value": value}
        if detail:
            ev["detail"] = detail
        self.events.append(ev)

    def pop_events(self) -> list[dict]:
        ev, self.events = self.events, []
        return ev

    # ------------------------------------------------------------ inputs
    def _update_solar(self, now, v):
        raw = _valid(v) and v > self.cfg.solar_on_v
        if not self.started:
            self.solar_avail = self.solar_candidate = raw
            self.solar_candidate_since = now
            if raw:
                self._emit(now, "SOLAR_AVAILABLE", -1, v)
            return
        if raw != self.solar_candidate:
            self.solar_candidate = raw
            self.solar_candidate_since = now
        if self.solar_candidate != self.solar_avail and now - self.solar_candidate_since >= self.cfg.debounce_ms:
            self.solar_avail = self.solar_candidate
            self._emit(now, "SOLAR_AVAILABLE" if self.solar_avail else "SOLAR_LOST", -1, v)

    def _update_tank(self, now):
        i = self.inp
        high = i.tank_float_high or (_valid(i.tank_pct) and i.tank_pct >= self.cfg.tank_overflow_pct)
        if not self.tank_full and high:
            self.tank_full = True
            self.chirp_until = now + 300
            self._emit(now, "TANK_FULL", -1, i.tank_pct)
        elif (self.tank_full and not i.tank_float_high and _valid(i.tank_pct)
              and i.tank_pct < self.cfg.tank_resume_pct):
            self.tank_full = False
            self._emit(now, "TANK_OK", -1, i.tank_pct)

    def _update_temp(self, now):
        t = self.inp.temp_c
        if not _valid(t):
            if not self.temp_warned:
                self.temp_warned = True
                self._emit(now, "SENSOR_WARN", -1, -1)
            return
        self.temp_warned = False
        c = self.cfg
        if not self.temp_alert and (t > c.temp_max_c or t < c.temp_min_c):
            self.temp_alert = True
            self._emit(now, "TEMP_ALERT", -1, t)
        elif self.temp_alert and c.temp_min_c + c.temp_hyst_c <= t <= c.temp_max_c - c.temp_hyst_c:
            self.temp_alert = False
            self._emit(now, "TEMP_OK", -1, t)

    def _update_sensor_warnings(self, now):
        for z in range(ZONES):
            m = self.inp.moisture[z]
            bad = not _probe_ok(m)
            if bad and not self.moisture_warned[z]:
                self.moisture_warned[z] = True
                self._emit(now, "SENSOR_WARN", z, m if _valid(m) else -1)
            elif not bad:
                self.moisture_warned[z] = False

    # ------------------------------------------------------------ decisions
    def _can_start(self):
        return self.mode == "AUTO" and self.fault == "NONE" and not self.tank_full and not self.temp_alert

    def _pick_job(self):
        limit = self.cfg.moisture_solar_start if self.solar_avail else self.cfg.moisture_critical
        best, best_m = -1, 0.0
        for z in range(ZONES):
            m = self.inp.moisture[z]
            if not _probe_ok(m):
                continue
            if m < limit and (best < 0 or m < best_m):
                best, best_m = z, m
        if best < 0:
            return None
        return ("SOLAR" if self.solar_avail else "GRID"), best

    def _desired_source_while_running(self):
        if self.solar_avail:
            return "SOLAR"
        m = self.inp.moisture[self.zone]
        if self.source == "GRID" or (_valid(m) and m < self.cfg.moisture_critical):
            return "GRID"
        return "NONE"

    def _stop_condition(self):
        if self.mode == "HOLD":
            return "HOLD"
        if self.tank_full:
            return "TANK_FULL"
        if self.temp_alert:
            return "TEMP_ALERT"
        m = self.inp.moisture[self.zone]
        if not _probe_ok(m):
            return "SENSOR_INVALID"
        if m >= self.cfg.moisture_target:
            return "TARGET_REACHED"
        return "NONE"

    # ------------------------------------------------------------ transitions
    def _set_phase(self, now, p):
        self.phase, self.phase_since = p, now

    def _start_zone(self, now, zone, src):
        self.zone, self.source = zone, src
        self.out.relay_grid = src == "GRID"
        self.out.valve = [z == zone for z in range(ZONES)]
        self.out.pump_on = False
        self.last_stop = "NONE"
        self._set_phase(now, VALVE_OPENING)
        self._emit(now, "ZONE_START", zone, self.inp.moisture[zone])

    def _begin_stop(self, now, why):
        self.out.pump_on = False
        self.last_stop = why
        self._set_phase(now, STOPPING)
        self._emit(now, "ZONE_DONE" if why == "TARGET_REACHED" else "ZONE_STOPPED", self.zone, 0, why)

    def _begin_switch(self, now, to):
        self.out.pump_on = False
        self.switch_to = to
        self._set_phase(now, SWITCH_BREAK)

    def _trip(self, now, fault):
        self.out.pump_on = False
        self.out.valve = [False] * ZONES
        self.out.relay_grid = False
        self.fault = fault
        self.totals.faults += 1
        value = self.inp.flow_lpm if fault == "NO_FLOW" else self.inp.pump_a
        self._emit(now, "FAULT_" + fault, self.zone, value)
        self.source = "NONE"
        self._set_phase(now, FAULT)

    # ------------------------------------------------------------ commands
    def command(self, cmd: str, now: int) -> None:
        if cmd == "HOLD" and self.mode != "HOLD":
            self.mode = "HOLD"
            self._emit(now, "MODE_HOLD")
        elif cmd == "AUTO" and self.mode != "AUTO":
            self.mode = "AUTO"
            self._emit(now, "MODE_AUTO")
        elif cmd == "RESET_FAULT" and self.phase == FAULT:
            self.fault = "NONE"
            self.zone = -1
            self._set_phase(now, IDLE)
            self._emit(now, "FAULT_CLEARED")

    # ------------------------------------------------------------ main step
    def update(self, now: int, inp: Inputs) -> Outputs:
        self.inp = inp
        self._update_solar(now, inp.solar_v)
        self.started = True
        self._update_tank(now)
        self._update_temp(now)
        self._update_sensor_warnings(now)
        c, o = self.cfg, self.out

        if self.phase == IDLE:
            o.pump_on = False
            o.valve = [False] * ZONES
            o.relay_grid = False
            self.source, self.zone = "NONE", -1
            job = self._pick_job() if self._can_start() else None
            if job:
                self._start_zone(now, job[1], job[0])

        elif self.phase == VALVE_OPENING:
            why = self._stop_condition()
            if why == "NONE" and self._desired_source_while_running() == "NONE":
                why = "SOLAR_LOST"
            if why != "NONE":
                self._begin_stop(now, why)
            elif now - self.phase_since >= c.valve_open_ms:
                o.pump_on = True
                self.run_since = now
                self.dry_timing = self.no_flow_timing = False
                self._set_phase(now, RUNNING)

        elif self.phase == RUNNING:
            ran = now - self.run_since
            tripped = False
            if ran >= c.inrush_ms and inp.pump_a > c.over_current_a:
                self._trip(now, "OVER_CURRENT")
                tripped = True
            if not tripped:
                if ran >= c.inrush_ms and inp.pump_a < c.dry_run_a:
                    if not self.dry_timing:
                        self.dry_timing, self.dry_since = True, now
                    if now - self.dry_since >= c.dry_run_ms:
                        self._trip(now, "DRY_RUN")
                        tripped = True
                else:
                    self.dry_timing = False
            if not tripped:
                if ran >= c.startup_delay_ms and inp.flow_lpm < c.no_flow_lpm:
                    if not self.no_flow_timing:
                        self.no_flow_timing, self.no_flow_since = True, now
                    if now - self.no_flow_since >= c.no_flow_ms:
                        self._trip(now, "NO_FLOW")
                        tripped = True
                else:
                    self.no_flow_timing = False
            if not tripped:
                why = self._stop_condition()
                if why != "NONE":
                    self._begin_stop(now, why)
                else:
                    want = self._desired_source_while_running()
                    if want == "NONE":
                        self._begin_stop(now, "SOLAR_LOST")
                    elif want != self.source:
                        self._begin_switch(now, want)

        elif self.phase == SWITCH_BREAK:
            o.pump_on = False
            if self.mode == "HOLD":
                self._begin_stop(now, "HOLD")
            elif now - self.phase_since >= c.dead_time_ms:
                o.relay_grid = self.switch_to == "GRID"
                self._set_phase(now, SWITCH_SETTLE)

        elif self.phase == SWITCH_SETTLE:
            o.pump_on = False
            if self.mode == "HOLD":
                self._begin_stop(now, "HOLD")
            elif now - self.phase_since >= c.dead_time_ms:
                self.source = self.switch_to
                self.totals.switches += 1
                self.chirp_until = now + 200
                self._emit(now, "SOURCE_CHANGED", self.zone, 0, self.source)
                o.pump_on = True
                self.run_since = now
                self.dry_timing = self.no_flow_timing = False
                self._set_phase(now, RUNNING)

        elif self.phase == STOPPING:
            o.pump_on = False
            if now - self.phase_since >= c.valve_close_delay_ms:
                o.valve = [False] * ZONES
                o.relay_grid = False
                self.source, self.zone = "NONE", -1
                self._set_phase(now, IDLE)

        elif self.phase == FAULT:
            o.pump_on = False
            o.valve = [False] * ZONES
            o.relay_grid = False

        self._compute_alerts(now)
        return o

    def _compute_alerts(self, now):
        beep = False
        if self.phase == FAULT:
            beep = (now // 500) % 2 == 0
        elif self.temp_alert:
            beep = (now % 2000) < 250
        if self.chirp_until > now:
            beep = True
        self.out.buzzer = beep
        self.out.alert_led = self.phase == FAULT or self.temp_alert or self.tank_full

    # ------------------------------------------------------------ metering
    def meter(self, now: int, volts: float, power_factor: float) -> None:
        if not self.meter_started:
            self.meter_started = True
            self.last_meter_ms = now
            return
        dt = min(now - self.last_meter_ms, 2000)
        self.last_meter_ms = now
        if not self.out.pump_on:
            return
        wh = volts * self.inp.pump_a * power_factor * dt / 3_600_000
        if self.source == "SOLAR":
            self.totals.solar_wh += wh
        elif self.source == "GRID":
            self.totals.grid_wh += wh
        litres = self.inp.flow_lpm * dt / 60_000
        self.totals.litres += litres
        if 0 <= self.zone < ZONES:
            self.totals.litres_zone[self.zone] += litres
