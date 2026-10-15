/*
 * Data sources for the dashboard. Both produce the same objects:
 *   live    - the device's /live document (see docs/data-model.md)
 *   events  - { ts, type, sev, zone, value, detail }
 *   history - [{ t, solarV, z1, z2, pumpA, flowLpm, source }]
 *   status  - { link: "demo" | "online" | "stale" | "offline" | "error", lastSeen, buffered, note }
 *
 * DemoSource runs the controller and farm model in the browser.
 * FirebaseSource streams from the Realtime Database REST API, so no SDK is needed.
 */
(function (root) {
  "use strict";

  var Controller = root.HFControl.Controller;
  var severityOf = root.HFControl.severityOf;
  var Plant = root.HFPlant.Plant;

  function round(x, d) {
    if (typeof x !== "number" || isNaN(x)) return null;
    var f = Math.pow(10, d === undefined ? 2 : d);
    return Math.round(x * f) / f;
  }

  // ------------------------------------------------------------------ demo

  function DemoSource() {
    this.kind = "demo";
    this.timer = null;
  }

  DemoSource.prototype.start = function (h) {
    var self = this;
    this.h = h;
    this.plant = new Plant(10.5, 0.2);
    this.ctl = new Controller();
    this.t0 = performance.now();
    this.ctl.begin(0);
    this.lastLive = -99;
    this.buffer = { events: [], points: [] };
    this.wasDown = false;
    this.pending = [];
    this.pendingScenarios = [];
    var tick = 0.1;
    this.timer = setInterval(function () { self.step(tick); }, 100);
    h.status({ link: "demo", note: "Simulated device running in your browser" });
  };

  DemoSource.prototype.stop = function () { clearInterval(this.timer); };

  DemoSource.prototype.step = function (dt) {
    var now = Math.round(performance.now() - this.t0);
    var ctl = this.ctl, plant = this.plant, h = this.h;

    this.pending.splice(0).forEach(function (c) {
      if (c === "RESET_FAULT") plant.faultReset();
      ctl.command(c, now);
    });
    this.pendingScenarios.splice(0).forEach(function (s) { plant.trigger(s); });

    var inp = plant.step(dt, ctl.out);
    ctl.update(now, inp);
    ctl.meter(now, 230, 0.8);
    this.inp = inp;

    var down = plant.wifiDown();
    var wall = Date.now();
    var events = ctl.popEvents().map(function (e) {
      var ev = { ts: wall, type: e.type, sev: severityOf(e.type), zone: e.zone + 1, value: round(e.value) || 0 };
      if (e.detail) ev.detail = e.detail;
      return ev;
    });

    if (down) {
      // Device keeps controlling; the uplink holds data until Wi-Fi returns.
      Array.prototype.push.apply(this.buffer.events, events);
      if (plant.t - this.lastLive >= 1) {
        this.lastLive = plant.t;
        this.buffer.points.push(this.point(wall));
      }
      if (!this.wasDown) this.downSince = wall;
      this.wasDown = true;
      h.status({ link: "offline", lastSeen: this.downSince,
        buffered: this.buffer.events.length + this.buffer.points.length,
        note: "Device Wi-Fi down: control continues locally, data is buffered" });
      return;
    }
    if (this.wasDown) {
      this.wasDown = false;
      if (this.buffer.events.length) h.events(this.buffer.events);
      if (this.buffer.points.length) h.history(this.buffer.points);
      this.buffer = { events: [], points: [] };
      h.status({ link: "demo", note: "Reconnected: buffered data uploaded" });
    }
    if (events.length) h.events(events);
    if (plant.t - this.lastLive >= 1) {
      this.lastLive = plant.t;
      h.live(this.livePayload(wall));
    }
  };

  DemoSource.prototype.point = function (wall) {
    var i = this.inp;
    return { t: wall, solarV: round(i.solarV), z1: round(i.moisture[0], 1), z2: round(i.moisture[1], 1),
      pumpA: round(i.pumpA), flowLpm: round(i.flowLpm, 1), source: this.ctl.source };
  };

  DemoSource.prototype.livePayload = function (wall) {
    var c = this.ctl, i = this.inp, p = this.plant, o = c.out, t = c.totals;
    return {
      ts: wall,
      uptimeS: Math.round(p.t),
      fw: "browser-sim",
      simClock: p.clockText(),
      simActive: p.active(),
      sensors: {
        solarV: round(i.solarV), soil: { z1: round(i.moisture[0], 1), z2: round(i.moisture[1], 1) },
        tankPct: round(i.tankPct, 1), floatHigh: i.tankFloatHigh, tempC: round(i.tempC, 1),
        humidity: round(p.humidity, 1), lightPct: round(p.light, 0), pumpA: round(i.pumpA),
        flowLpm: round(i.flowLpm, 1)
      },
      state: {
        source: c.source, relay: o.relayGrid ? "GRID" : "SOLAR", pump: o.pumpOn,
        valves: { z1: o.valve[0], z2: o.valve[1] }, zone: c.zone + 1, phase: c.phase, mode: c.mode,
        fault: c.fault, solarAvailable: c.solarAvail, tempAlert: c.tempAlert, tankFull: c.tankFull,
        buzzer: o.buzzer, lastStop: c.lastStop
      },
      totals: {
        solarWh: t.solarWh, gridWh: t.gridWh, litres: t.litres, litresZ1: t.litresZone[0],
        litresZ2: t.litresZone[1], switches: t.switches, faults: t.faults
      },
      net: { rssi: -60, buffered: 0 }
    };
  };

  DemoSource.prototype.command = function (action) { this.pending.push(action); return Promise.resolve(); };
  DemoSource.prototype.scenario = function (name) { this.pendingScenarios.push(name); return Promise.resolve(); };

  // ------------------------------------------------------------------ Firebase

  function FirebaseSource(dbUrl, device, auth) {
    this.kind = "firebase";
    this.base = dbUrl.replace(/\/+$/, "") + "/devices/" + encodeURIComponent(device);
    this.auth = auth || "";
    this.streams = [];
    this.live = null;
    this.stale = true;
  }

  FirebaseSource.prototype.url = function (path, query) {
    var q = [];
    if (query) q.push(query);
    if (this.auth) q.push("auth=" + encodeURIComponent(this.auth));
    return this.base + "/" + path + ".json" + (q.length ? "?" + q.join("&") : "");
  };

  function setPath(obj, path, value) {
    var parts = path.split("/").filter(Boolean);
    if (!parts.length) return value;
    obj = obj || {};
    var cur = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    if (value === null) delete cur[parts[parts.length - 1]];
    else cur[parts[parts.length - 1]] = value;
    return obj;
  }

  function mergePatch(obj, path, data) {
    obj = obj || {};
    Object.keys(data || {}).forEach(function (k) { obj = setPath(obj, path + "/" + k, data[k]); });
    return obj;
  }

  FirebaseSource.prototype.start = function (h) {
    var self = this;
    this.h = h;
    h.status({ link: "stale", note: "Connecting to Firebase…" });

    var live = new EventSource(this.url("live"));
    live.addEventListener("put", function (e) {
      var msg = JSON.parse(e.data);
      self.live = setPath(self.live, msg.path, msg.data);
      if (self.live) h.live(self.live);
    });
    live.addEventListener("patch", function (e) {
      var msg = JSON.parse(e.data);
      self.live = mergePatch(self.live, msg.path, msg.data);
      if (self.live) h.live(self.live);
    });
    live.addEventListener("auth_revoked", function () {
      h.status({ link: "error", note: "Firebase refused access: check the auth token or database rules" });
    });
    live.addEventListener("cancel", function () {
      h.status({ link: "error", note: "Firebase refused access: check the auth token or database rules" });
    });
    live.onerror = function () {
      if (live.readyState === EventSource.CLOSED) h.status({ link: "error", note: "Can't reach Firebase: check the database URL" });
    };
    this.streams.push(live);

    var seen = {};
    var ev = new EventSource(this.url("events", 'orderBy="ts"&limitToLast=60'));
    ev.addEventListener("put", function (e) {
      var msg = JSON.parse(e.data);
      var list = [];
      if (msg.path === "/") {
        Object.keys(msg.data || {}).forEach(function (k) { if (!seen[k]) { seen[k] = 1; list.push(msg.data[k]); } });
      } else if (msg.data) {
        var k = msg.path.replace(/^\//, "");
        if (!seen[k]) { seen[k] = 1; list.push(msg.data); }
      }
      list.sort(function (a, b) { return a.ts - b.ts; });
      if (list.length) h.events(list);
    });
    this.streams.push(ev);

    this.loadHistory();
    this.watchdog = setInterval(function () { self.checkStale(); }, 1000);
  };

  FirebaseSource.prototype.loadHistory = function () {
    var h = this.h;
    return fetch(this.url("telemetry", 'orderBy="ts"&limitToLast=150'))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var pts = Object.keys(data).map(function (k) {
          var d = data[k];
          return { t: d.ts, solarV: d.solarV, z1: d.z1, z2: d.z2, pumpA: d.pumpA, flowLpm: d.flowLpm, source: d.source };
        }).sort(function (a, b) { return a.t - b.t; });
        if (pts.length) h.history(pts);
      })
      .catch(function () {});
  };

  FirebaseSource.prototype.checkStale = function () {
    if (!this.live || !this.live.ts) {
      this.h.status({ link: "stale", note: "Connected. Waiting for the device to publish…" });
      return;
    }
    var age = Date.now() - this.live.ts;
    var nowStale = age > 8000;
    if (nowStale) {
      this.h.status({ link: "offline", lastSeen: this.live.ts, buffered: null,
        note: "No update from the device for " + Math.round(age / 1000) + " s" });
    } else {
      if (this.stale) this.loadHistory();  // pick up anything the device buffered while offline
      this.h.status({ link: "online", lastSeen: this.live.ts, buffered: this.live.net ? this.live.net.buffered : 0,
        note: "Streaming from Firebase" });
    }
    this.stale = nowStale;
  };

  FirebaseSource.prototype.stop = function () {
    this.streams.forEach(function (s) { s.close(); });
    clearInterval(this.watchdog);
  };

  FirebaseSource.prototype.put = function (path, body) {
    return fetch(this.url(path), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (!r.ok) throw new Error("Firebase answered " + r.status); });
  };

  FirebaseSource.prototype.command = function (action) {
    return this.put("command", { seq: Date.now(), action: action, ts: { ".sv": "timestamp" } });
  };

  FirebaseSource.prototype.scenario = function (name) {
    return this.put("sim", { seq: Date.now(), scenario: name });
  };

  root.HFSources = { DemoSource: DemoSource, FirebaseSource: FirebaseSource };
})(this);
