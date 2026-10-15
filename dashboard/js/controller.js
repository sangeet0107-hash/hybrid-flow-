/*
 * JS port of the firmware control logic (firmware/hybrid_flow/control_logic.cpp),
 * used by the dashboard's built-in simulator. Kept equivalent to the C++ and
 * Python versions; all three pass the scenarios in tests/scenarios.json.
 */
(function (root) {
  "use strict";

  var ZONES = 2;

  var DEFAULT_CONFIG = {
    solarOnV: 18.0,
    debounceMs: 5000,
    moistureCritical: 30.0,
    moistureSolarStart: 50.0,
    moistureTarget: 60.0,
    tankOverflowPct: 95.0,
    tankResumePct: 90.0,
    tempMaxC: 45.0,
    tempMinC: 0.0,
    tempHystC: 2.0,
    inrushMs: 1000,
    dryRunA: 0.5,
    dryRunMs: 3000,
    overCurrentA: 8.0,
    noFlowLpm: 1.0,
    noFlowMs: 5000,
    startupDelayMs: 5000,
    deadTimeMs: 200,
    valveOpenMs: 1000,
    valveCloseDelayMs: 500
  };

  var SEVERITY = {
    FAULT_DRY_RUN: "crit", FAULT_OVER_CURRENT: "crit", FAULT_NO_FLOW: "crit",
    SOLAR_LOST: "warn", TANK_FULL: "warn", TEMP_ALERT: "warn", SENSOR_WARN: "warn",
    ZONE_STOPPED: "warn", MODE_HOLD: "warn"
  };

  function valid(x) { return typeof x === "number" && !isNaN(x); }
  function probeOk(m) { return valid(m) && m >= 0 && m <= 100; }

  function Controller(cfg) {
    this.cfg = Object.assign({}, DEFAULT_CONFIG, cfg || {});
    this.inp = { solarV: 0, moisture: [0, 0], tankPct: 0, tempC: 25, pumpA: 0, flowLpm: 0, tankFloatHigh: false };
    this.out = { relayGrid: false, pumpOn: false, valve: [false, false], buzzer: false, alertLed: false };
    this.totals = { solarWh: 0, gridWh: 0, litres: 0, litresZone: [0, 0], switches: 0, faults: 0 };
    this.phase = "IDLE";
    this.phaseSince = 0;
    this.source = "NONE";
    this.switchTo = "NONE";
    this.fault = "NONE";
    this.mode = "AUTO";
    this.zone = -1;
    this.lastStop = "NONE";
    this.started = false;
    this.solarAvail = false;
    this.solarCandidate = false;
    this.solarCandidateSince = 0;
    this.tankFull = false;
    this.tempAlert = false;
    this.tempWarned = false;
    this.moistureWarned = [false, false];
    this.runSince = 0;
    this.dryTiming = false;
    this.drySince = 0;
    this.noFlowTiming = false;
    this.noFlowSince = 0;
    this.chirpUntil = 0;
    this.lastMeterMs = 0;
    this.meterStarted = false;
    this.events = [];
  }

  var P = Controller.prototype;

  P.begin = function (now) {
    this.phase = "IDLE"; this.phaseSince = now;
    this.source = "NONE"; this.fault = "NONE"; this.mode = "AUTO"; this.zone = -1;
    this.started = false;
    this.out = { relayGrid: false, pumpOn: false, valve: [false, false], buzzer: false, alertLed: false };
    this.emit(now, "BOOT");
  };

  P.emit = function (now, type, zone, value, detail) {
    var e = { ms: now, type: type, zone: zone === undefined ? -1 : zone, value: value || 0 };
    if (detail) e.detail = detail;
    this.events.push(e);
  };

  P.popEvents = function () { var e = this.events; this.events = []; return e; };

  // ---------------------------------------------------------------- inputs
  P.updateSolar = function (now, v) {
    var raw = valid(v) && v > this.cfg.solarOnV;
    if (!this.started) {
      this.solarAvail = this.solarCandidate = raw;
      this.solarCandidateSince = now;
      if (raw) this.emit(now, "SOLAR_AVAILABLE", -1, v);
      return;
    }
    if (raw !== this.solarCandidate) { this.solarCandidate = raw; this.solarCandidateSince = now; }
    if (this.solarCandidate !== this.solarAvail && now - this.solarCandidateSince >= this.cfg.debounceMs) {
      this.solarAvail = this.solarCandidate;
      this.emit(now, this.solarAvail ? "SOLAR_AVAILABLE" : "SOLAR_LOST", -1, v);
    }
  };

  P.updateTank = function (now) {
    var i = this.inp, c = this.cfg;
    var high = i.tankFloatHigh || (valid(i.tankPct) && i.tankPct >= c.tankOverflowPct);
    if (!this.tankFull && high) {
      this.tankFull = true;
      this.chirpUntil = now + 300;
      this.emit(now, "TANK_FULL", -1, i.tankPct);
    } else if (this.tankFull && !i.tankFloatHigh && valid(i.tankPct) && i.tankPct < c.tankResumePct) {
      this.tankFull = false;
      this.emit(now, "TANK_OK", -1, i.tankPct);
    }
  };

  P.updateTemp = function (now) {
    var t = this.inp.tempC, c = this.cfg;
    if (!valid(t)) {
      if (!this.tempWarned) { this.tempWarned = true; this.emit(now, "SENSOR_WARN", -1, -1); }
      return;
    }
    this.tempWarned = false;
    if (!this.tempAlert && (t > c.tempMaxC || t < c.tempMinC)) {
      this.tempAlert = true;
      this.emit(now, "TEMP_ALERT", -1, t);
    } else if (this.tempAlert && t <= c.tempMaxC - c.tempHystC && t >= c.tempMinC + c.tempHystC) {
      this.tempAlert = false;
      this.emit(now, "TEMP_OK", -1, t);
    }
  };

  P.updateSensorWarnings = function (now) {
    for (var z = 0; z < ZONES; z++) {
      var m = this.inp.moisture[z];
      var bad = !probeOk(m);
      if (bad && !this.moistureWarned[z]) {
        this.moistureWarned[z] = true;
        this.emit(now, "SENSOR_WARN", z, valid(m) ? m : -1);
      } else if (!bad) {
        this.moistureWarned[z] = false;
      }
    }
  };

  // ---------------------------------------------------------------- decisions
  P.canStart = function () {
    return this.mode === "AUTO" && this.fault === "NONE" && !this.tankFull && !this.tempAlert;
  };

  P.pickJob = function () {
    var limit = this.solarAvail ? this.cfg.moistureSolarStart : this.cfg.moistureCritical;
    var best = -1, bestM = 0;
    for (var z = 0; z < ZONES; z++) {
      var m = this.inp.moisture[z];
      if (!probeOk(m)) continue;
      if (m < limit && (best < 0 || m < bestM)) { best = z; bestM = m; }
    }
    if (best < 0) return null;
    return { source: this.solarAvail ? "SOLAR" : "GRID", zone: best };
  };

  P.desiredSourceWhileRunning = function () {
    if (this.solarAvail) return "SOLAR";
    var m = this.inp.moisture[this.zone];
    if (this.source === "GRID" || (valid(m) && m < this.cfg.moistureCritical)) return "GRID";
    return "NONE";
  };

  P.stopCondition = function () {
    if (this.mode === "HOLD") return "HOLD";
    if (this.tankFull) return "TANK_FULL";
    if (this.tempAlert) return "TEMP_ALERT";
    var m = this.inp.moisture[this.zone];
    if (!probeOk(m)) return "SENSOR_INVALID";
    if (m >= this.cfg.moistureTarget) return "TARGET_REACHED";
    return "NONE";
  };

  // ---------------------------------------------------------------- transitions
  P.setPhase = function (now, p) { this.phase = p; this.phaseSince = now; };

  P.startZone = function (now, zone, src) {
    this.zone = zone;
    this.source = src;
    this.out.relayGrid = src === "GRID";
    this.out.valve = [zone === 0, zone === 1];
    this.out.pumpOn = false;
    this.lastStop = "NONE";
    this.setPhase(now, "VALVE_OPENING");
    this.emit(now, "ZONE_START", zone, this.inp.moisture[zone]);
  };

  P.beginStop = function (now, why) {
    this.out.pumpOn = false;
    this.lastStop = why;
    this.setPhase(now, "STOPPING");
    this.emit(now, why === "TARGET_REACHED" ? "ZONE_DONE" : "ZONE_STOPPED", this.zone, 0, why);
  };

  P.beginSwitch = function (now, to) {
    this.out.pumpOn = false;
    this.switchTo = to;
    this.setPhase(now, "SWITCH_BREAK");
  };

  P.trip = function (now, fault) {
    this.out.pumpOn = false;
    this.out.valve = [false, false];
    this.out.relayGrid = false;
    this.fault = fault;
    this.totals.faults++;
    this.emit(now, "FAULT_" + fault, this.zone, fault === "NO_FLOW" ? this.inp.flowLpm : this.inp.pumpA);
    this.source = "NONE";
    this.setPhase(now, "FAULT");
  };

  // ---------------------------------------------------------------- commands
  P.command = function (cmd, now) {
    if (cmd === "HOLD" && this.mode !== "HOLD") {
      this.mode = "HOLD"; this.emit(now, "MODE_HOLD");
    } else if (cmd === "AUTO" && this.mode !== "AUTO") {
      this.mode = "AUTO"; this.emit(now, "MODE_AUTO");
    } else if (cmd === "RESET_FAULT" && this.phase === "FAULT") {
      this.fault = "NONE"; this.zone = -1;
      this.setPhase(now, "IDLE");
      this.emit(now, "FAULT_CLEARED");
    }
  };

  // ---------------------------------------------------------------- main step
  P.update = function (now, inp) {
    this.inp = inp;
    this.updateSolar(now, inp.solarV);
    this.started = true;
    this.updateTank(now);
    this.updateTemp(now);
    this.updateSensorWarnings(now);
    var c = this.cfg, o = this.out, why, want;

    switch (this.phase) {
      case "IDLE": {
        o.pumpOn = false; o.valve = [false, false]; o.relayGrid = false;
        this.source = "NONE"; this.zone = -1;
        var job = this.canStart() ? this.pickJob() : null;
        if (job) this.startZone(now, job.zone, job.source);
        break;
      }
      case "VALVE_OPENING":
        why = this.stopCondition();
        if (why === "NONE" && this.desiredSourceWhileRunning() === "NONE") why = "SOLAR_LOST";
        if (why !== "NONE") {
          this.beginStop(now, why);
        } else if (now - this.phaseSince >= c.valveOpenMs) {
          o.pumpOn = true;
          this.runSince = now;
          this.dryTiming = this.noFlowTiming = false;
          this.setPhase(now, "RUNNING");
        }
        break;

      case "RUNNING": {
        var ran = now - this.runSince;
        if (ran >= c.inrushMs && inp.pumpA > c.overCurrentA) { this.trip(now, "OVER_CURRENT"); break; }
        if (ran >= c.inrushMs && inp.pumpA < c.dryRunA) {
          if (!this.dryTiming) { this.dryTiming = true; this.drySince = now; }
          if (now - this.drySince >= c.dryRunMs) { this.trip(now, "DRY_RUN"); break; }
        } else {
          this.dryTiming = false;
        }
        if (ran >= c.startupDelayMs && inp.flowLpm < c.noFlowLpm) {
          if (!this.noFlowTiming) { this.noFlowTiming = true; this.noFlowSince = now; }
          if (now - this.noFlowSince >= c.noFlowMs) { this.trip(now, "NO_FLOW"); break; }
        } else {
          this.noFlowTiming = false;
        }
        why = this.stopCondition();
        if (why !== "NONE") { this.beginStop(now, why); break; }
        want = this.desiredSourceWhileRunning();
        if (want === "NONE") { this.beginStop(now, "SOLAR_LOST"); break; }
        if (want !== this.source) this.beginSwitch(now, want);
        break;
      }
      case "SWITCH_BREAK":
        o.pumpOn = false;
        if (this.mode === "HOLD") { this.beginStop(now, "HOLD"); break; }
        if (now - this.phaseSince >= c.deadTimeMs) {
          o.relayGrid = this.switchTo === "GRID";
          this.setPhase(now, "SWITCH_SETTLE");
        }
        break;

      case "SWITCH_SETTLE":
        o.pumpOn = false;
        if (this.mode === "HOLD") { this.beginStop(now, "HOLD"); break; }
        if (now - this.phaseSince >= c.deadTimeMs) {
          this.source = this.switchTo;
          this.totals.switches++;
          this.chirpUntil = now + 200;
          this.emit(now, "SOURCE_CHANGED", this.zone, 0, this.source);
          o.pumpOn = true;
          this.runSince = now;
          this.dryTiming = this.noFlowTiming = false;
          this.setPhase(now, "RUNNING");
        }
        break;

      case "STOPPING":
        o.pumpOn = false;
        if (now - this.phaseSince >= c.valveCloseDelayMs) {
          o.valve = [false, false]; o.relayGrid = false;
          this.source = "NONE"; this.zone = -1;
          this.setPhase(now, "IDLE");
        }
        break;

      case "FAULT":
        o.pumpOn = false; o.valve = [false, false]; o.relayGrid = false;
        break;
    }

    var beep = false;
    if (this.phase === "FAULT") beep = Math.floor(now / 500) % 2 === 0;
    else if (this.tempAlert) beep = now % 2000 < 250;
    if (this.chirpUntil > now) beep = true;
    o.buzzer = beep;
    o.alertLed = this.phase === "FAULT" || this.tempAlert || this.tankFull;
    return o;
  };

  // ---------------------------------------------------------------- metering
  P.meter = function (now, volts, pf) {
    if (!this.meterStarted) { this.meterStarted = true; this.lastMeterMs = now; return; }
    var dt = Math.min(now - this.lastMeterMs, 2000);
    this.lastMeterMs = now;
    if (!this.out.pumpOn) return;
    var wh = volts * this.inp.pumpA * pf * dt / 3600000;
    if (this.source === "SOLAR") this.totals.solarWh += wh;
    else if (this.source === "GRID") this.totals.gridWh += wh;
    var litres = this.inp.flowLpm * dt / 60000;
    this.totals.litres += litres;
    if (this.zone >= 0 && this.zone < ZONES) this.totals.litresZone[this.zone] += litres;
  };

  var api = {
    Controller: Controller,
    DEFAULT_CONFIG: DEFAULT_CONFIG,
    severityOf: function (t) { return SEVERITY[t] || "info"; },
    ZONES: ZONES
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HFControl = api;
})(this);
