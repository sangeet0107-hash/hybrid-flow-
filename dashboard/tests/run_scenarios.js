// Runs the shared scenarios (tests/scenarios.json) against the dashboard's JS
// controller.   node dashboard/tests/run_scenarios.js
"use strict";
const path = require("path");
const fs = require("fs");
const { Controller } = require("../js/controller.js");

const spec = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "tests", "scenarios.json"), "utf8"));

function apply(inp, o) {
  for (const [k, v] of Object.entries(o || {})) {
    if (k === "z1" || k === "z2") inp.moisture[k === "z1" ? 0 : 1] = v === null ? NaN : v;
    else if (k === "floatHigh") inp.tankFloatHigh = v;
    else inp[k] = v;
  }
}

let passed = 0;
let failed = 0;
for (const sc of spec.scenarios) {
  const errors = [];
  const c = new Controller();
  c.begin(0);
  const inp = { solarV: 0, moisture: [0, 0], tankPct: 0, tempC: 25, pumpA: 0, flowLpm: 0, tankFloatHigh: false };
  apply(inp, spec.defaults);
  apply(inp, sc.init);
  let t = 0, prevPump = false, prevRelay = false;
  sc.steps.forEach((st, idx) => {
    const i = idx + 1;
    apply(inp, st.in);
    if (st.cmd) c.command(st.cmd, t);
    const seen = [];
    for (let k = 0; k < st.ms / spec.tickMs; k++) {
      t += spec.tickMs;
      const o = c.update(t, Object.assign({}, inp, { moisture: inp.moisture.slice() }));
      c.meter(t, spec.meter.volts, spec.meter.powerFactor);
      if (o.pumpOn && !o.valve[0] && !o.valve[1]) errors.push(`step ${i}: pump on with every valve closed`);
      if (o.relayGrid !== prevRelay && (o.pumpOn || prevPump)) errors.push(`step ${i}: source relay moved while the pump was on`);
      prevPump = o.pumpOn; prevRelay = o.relayGrid;
      for (const e of c.popEvents()) seen.push(e.type);
    }
    const o = c.out;
    const actual = {
      phase: c.phase, source: c.source, relay: o.relayGrid ? "GRID" : "SOLAR", fault: c.fault, mode: c.mode,
      pump: o.pumpOn, valve1: o.valve[0], valve2: o.valve[1], alertLed: o.alertLed, switches: c.totals.switches,
      solarWh: c.totals.solarWh, gridWh: c.totals.gridWh, litres: c.totals.litres
    };
    for (const [k, want] of Object.entries(st.expect || {})) {
      const got = actual[k];
      if (Array.isArray(want)) {
        if (got < want[0] - 1e-9 || got > want[1] + 1e-9) errors.push(`step ${i}: ${k} expected ${want[0]}..${want[1]}, got ${got.toFixed(4)}`);
      } else if (got !== want) {
        errors.push(`step ${i}: ${k} expected ${want}, got ${got}`);
      }
    }
    for (const ev of st.events || []) if (!seen.includes(ev)) errors.push(`step ${i}: expected event ${ev}`);
  });
  if (errors.length) {
    failed++;
    console.log(`  FAIL ${sc.name}\n    ${errors.join("\n    ")}`);
  } else {
    passed++;
    console.log(`  ok   ${sc.name}`);
  }
}
console.log(`\n${passed}/${spec.scenarios.length} scenarios passed (dashboard JS)`);
process.exit(failed ? 1 : 0);
