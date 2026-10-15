/*
 * Farm model for the dashboard's built-in simulator. A port of
 * backend/emulator/hybridflow/plant.py so Demo mode behaves like the emulator.
 */
(function (root) {
  "use strict";

  var TOUR = [
    { after: 6, when: "running", wait: 30, action: "CLOUD",
      note: "Cloud covers the panel while Zone 2 is below 30 %. After the 5 s debounce the pump changes over to grid, break-before-make." },
    { after: 95, when: "running", wait: 60, action: "DRY_TANK",
      note: "The supply tank runs dry. Pump current falls under 0.5 A and the dry-run trip stops it within 3 s." },
    { after: 8, when: "fault", wait: 0, action: "RESET_FAULT",
      note: "Operator refills the tank and resets the fault from the dashboard." },
    { after: 15, when: "running", wait: 60, action: "BLOCKAGE",
      note: "A line blocks. Current looks normal but flow stays under 1 L/min, so the no-flow check trips after the 5 s start-up delay." },
    { after: 8, when: "fault", wait: 0, action: "RESET_FAULT",
      note: "Line cleared and fault reset." },
    { after: 15, when: "any", wait: 0, action: "WIFI_DROP",
      note: "Wi-Fi drops for 45 s. Control continues on the device; telemetry is buffered and uploaded on reconnect." },
    { after: 55, when: "any", wait: 0, action: "HEATWAVE",
      note: "Air temperature passes 45 °C. Irrigation stops and the alarm sounds until it cools below 43 °C." },
    { after: 50, when: "any", wait: 0, action: "TANK_FULL",
      note: "Tank reaches 95 %. Valves close and irrigation waits until it falls below 90 %." },
    { after: 45, when: "running", wait: 60, action: "JAM",
      note: "The impeller jams. Current jumps above 8 A and the over-current trip fires once the 1 s inrush window has passed." },
    { after: 8, when: "fault", wait: 0, action: "RESET_FAULT",
      note: "Pump freed and fault reset. End of the guided demo." }
  ];

  function Plant(startHour, simMinutesPerSecond) {
    this.clockMin = (startHour === undefined ? 10.5 : startHour) * 60;
    this.speed = simMinutesPerSecond === undefined ? 0.2 : simMinutesPerSecond;
    this.moisture = [44, 20];
    this.tank = 62;
    this.cloudUntil = 0;
    this.heatUntil = 0;
    this.dryUntil = 0;
    this.overfillUntil = 0;
    this.wifiDownUntil = 0;
    this.blocked = false;
    this.jammed = false;
    this.pumpOnSince = null;
    this.t = 0;
    this.light = 0;
    this.humidity = 50;
    this.temp = 30;
  }

  var P = Plant.prototype;

  // Pump faults only show while the pump runs: if it's idle, dry Zone 1
  // below the critical level so the controller starts watering it.
  P.forceRun = function () {
    if (this.pumpOnSince === null) this.moisture[0] = Math.min(this.moisture[0], 26);
  };

  P.trigger = function (name) {
    switch (name) {
      case "CLOUD": this.cloudUntil = this.t + 40; this.moisture[1] = Math.min(this.moisture[1], 24); break;
      case "NIGHT": this.clockMin = 19.5 * 60; break;
      case "DAY": this.clockMin = 10 * 60; break;
      case "DRY_TANK": this.tank = 2; this.dryUntil = this.t + 90; this.forceRun(); break;
      case "BLOCKAGE": this.blocked = true; this.forceRun(); break;
      case "JAM": this.jammed = true; this.forceRun(); break;
      case "HEATWAVE": this.heatUntil = this.t + 40; break;
      case "TANK_FULL": this.tank = 96; this.overfillUntil = this.t + 20; break;
      case "WIFI_DROP": this.wifiDownUntil = this.t + 45; break;
      case "CLEAR":
        this.cloudUntil = this.heatUntil = this.dryUntil = this.overfillUntil = this.wifiDownUntil = 0;
        this.blocked = this.jammed = false;
        if (this.tank < 20) this.tank = 55;
        break;
    }
  };

  P.faultReset = function () {
    this.blocked = this.jammed = false;
    if (this.tank < 20) { this.tank = 55; this.dryUntil = 0; }
  };

  P.wifiDown = function () { return this.t < this.wifiDownUntil; };

  P.active = function () {
    var a = [];
    if (this.t < this.cloudUntil) a.push("CLOUD");
    if (this.t < this.heatUntil) a.push("HEATWAVE");
    if (this.t < this.dryUntil) a.push("DRY_TANK");
    if (this.t < this.overfillUntil) a.push("TANK_FULL");
    if (this.wifiDown()) a.push("WIFI_DROP");
    if (this.blocked) a.push("BLOCKAGE");
    if (this.jammed) a.push("JAM");
    return a;
  };

  P.irradiance = function () {
    var h = (this.clockMin / 60) % 24;
    var sun = h >= 6 && h <= 18 ? Math.sin(Math.PI * (h - 6) / 12) : 0;
    if (this.t < this.cloudUntil) sun *= 0.22;
    return Math.max(0, sun);
  };

  function noise(s) { return (Math.random() * 2 - 1) * s; }

  P.step = function (dt, out) {
    this.t += dt;
    this.clockMin = (this.clockMin + dt * this.speed) % 1440;
    var irr = this.irradiance();
    this.solarV = irr < 0.03 ? 0 : 22 * Math.pow(irr, 0.18) + noise(0.12);
    this.light = Math.min(100, Math.max(0, irr * 100 + noise(1.5) + 1.5));
    var heat = this.t < this.heatUntil ? 16 : 0;
    this.temp = 24 + 9 * irr + heat + noise(0.2);
    this.humidity = 72 - 28 * irr - heat + noise(0.5);

    var amps, flow;
    if (out.pumpOn) {
      if (this.pumpOnSince === null) this.pumpOnSince = this.t;
      var ran = this.t - this.pumpOnSince;
      if (ran < 0.4) { amps = 14 + noise(1); flow = 2; }
      else if (this.jammed) { amps = 11.5 + noise(0.3); flow = 0; }
      else if (this.tank < 3) { amps = 0.3 + noise(0.05); flow = 0; }
      else if (this.blocked) { amps = 3.4 + noise(0.1); flow = 0.2 + noise(0.1); }
      else { amps = 4.2 + noise(0.12); flow = 12.4 + noise(0.4) - (out.valve[0] ? 0 : 0.8); }
    } else {
      this.pumpOnSince = null;
      amps = 0; flow = 0;
    }
    this.pumpA = amps;
    this.flow = Math.max(0, flow);

    var et = (0.03 + 0.10 * irr) * (this.temp / 30);
    for (var z = 0; z < 2; z++) {
      var gain = out.valve[z] ? 0.7 * this.flow / 12 : 0;
      var dry = et * (z === 1 ? 1.3 : 1);
      this.moisture[z] = Math.min(100, Math.max(5, this.moisture[z] + (gain - dry) * dt));
    }

    var inflow;
    if (this.t < this.dryUntil) inflow = 0;
    else if (this.t < this.overfillUntil) inflow = 0.25;
    else inflow = this.tank < 75 ? 0.05 : 0;
    this.tank = Math.min(100, Math.max(0, this.tank + (inflow - 0.13 * this.flow / 12) * dt));
    if (this.tank > 88 && this.t >= this.overfillUntil) this.tank -= 0.4 * dt;

    return {
      solarV: this.solarV,
      moisture: [this.moisture[0] + noise(0.15), this.moisture[1] + noise(0.15)],
      tankPct: this.tank,
      tempC: this.temp,
      pumpA: this.pumpA,
      flowLpm: this.flow,
      tankFloatHigh: this.tank >= 98
    };
  };

  P.clockText = function () {
    var m = Math.floor(this.clockMin);
    var h = Math.floor(m / 60), mm = m % 60;
    return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
  };

  function TourRunner() { this.index = 0; this.stepStarted = 0; }
  TourRunner.prototype.done = function () { return this.index >= TOUR.length; };
  TourRunner.prototype.poll = function (elapsed, phase) {
    if (this.done()) return null;
    var step = TOUR[this.index];
    var waited = elapsed - this.stepStarted;
    if (waited < step.after) return null;
    var ok = step.when === "any" || (step.when === "running" && phase === "RUNNING") ||
             (step.when === "fault" && phase === "FAULT");
    if (ok || (waited >= step.after + step.wait && step.when !== "fault")) {
      this.index++;
      this.stepStarted = elapsed;
      return step;
    }
    return null;
  };

  var api = { Plant: Plant, TourRunner: TourRunner, TOUR: TOUR };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HFPlant = api;
})(this);
