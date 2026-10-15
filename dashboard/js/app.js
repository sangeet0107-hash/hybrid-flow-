/*
 * Hybrid-Flow dashboard. Renders the device's /live document from either the
 * built-in simulator or Firebase, and sends operator commands back.
 */
(function () {
  "use strict";

  const CFG = window.HF_CONFIG;
  const DEF = window.HFControl.DEFAULT_CONFIG;
  const { DemoSource, FirebaseSource } = window.HFSources;
  const { TourRunner, TOUR } = window.HFPlant;
  const $ = (id) => document.getElementById(id);

  const store = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  };

  let source = null;
  let live = null;
  let history = [];
  let events = [];
  let tour = null;
  let tourTimer = null;
  let linkState = "demo";

  // ------------------------------------------------------------------ helpers
  const fmt = (v, d = 1) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "--");
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const pad = (n) => String(n).padStart(2, "0");
  const timeOf = (ms) => { const d = new Date(ms); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const zoneName = (z) => (z >= 1 ? `Zone ${z}` : "");
  const soilOf = (l, z) => (l && l.sensors && l.sensors.soil ? l.sensors.soil["z" + z] : null);

  // ------------------------------------------------------------------ sensor tiles
  const soilTile = (z, pin) => ({
    key: "z" + z, label: `Soil moisture · Zone ${z}`, tag: `GPIO${pin} · capacitive`, unit: "%", min: 0, max: 100, dec: 0,
    ticks: [DEF.moistureCritical, DEF.moistureSolarStart, DEF.moistureTarget],
    get: (l) => soilOf(l, z),
    tone: (v, l) => (v == null ? "crit" : l.state.valves["z" + z] ? "water" : v < DEF.moistureCritical ? "warn" : v >= DEF.moistureTarget ? "ok" : null),
    note: (v, l) => v == null ? "Probe reading invalid: zone skipped"
      : l.state.valves["z" + z] ? `Valve open · watering to ${DEF.moistureTarget} %`
      : v < DEF.moistureCritical ? `Critical: grid allowed below ${DEF.moistureCritical} %`
      : `Critical ${DEF.moistureCritical} % · target ${DEF.moistureTarget} %`
  });

  const TILES = [
    { key: "solarV", label: "Solar voltage", tag: "GPIO34 · divider", unit: "V", min: 0, max: 25, dec: 1, ticks: [DEF.solarOnV],
      get: (l) => l.sensors.solarV,
      tone: (v, l) => (l.state.solarAvailable ? "solar" : null),
      note: (v, l) => (l.state.solarAvailable ? `Above ${DEF.solarOnV} V: solar has priority` : `Below ${DEF.solarOnV} V: solar unavailable`) },
    soilTile(1, 35),
    soilTile(2, 39),
    { key: "tank", label: "Tank level", tag: "HC-SR04 · GPIO26", unit: "%", min: 0, max: 100, dec: 0, ticks: [DEF.tankResumePct, DEF.tankOverflowPct],
      get: (l) => l.sensors.tankPct,
      tone: (v, l) => (l.state.tankFull ? "warn" : v != null && v < 5 ? "crit" : "water"),
      note: (v, l) => (l.sensors.floatHigh ? "Float switch high: overflow" : `Valves close at ${DEF.tankOverflowPct} %`) },
    { key: "temp", label: "Air temperature", tag: "GPIO4 · DHT22", unit: "°C", min: -5, max: 55, dec: 1, ticks: [DEF.tempMinC, DEF.tempMaxC],
      get: (l) => l.sensors.tempC,
      tone: (v, l) => (v == null ? "crit" : l.state.tempAlert ? "warn" : null),
      note: (v, l) => `Humidity ${fmt(l.sensors.humidity, 0)} % · safe 0–45 °C` },
    { key: "light", label: "Light intensity", tag: "GPIO32 · LDR", unit: "%", min: 0, max: 100, dec: 0, ticks: [],
      get: (l) => l.sensors.lightPct,
      tone: () => null,
      note: (v) => (v == null ? "--" : v > 60 ? "Bright sun" : v > 20 ? "Overcast or low sun" : "Dark: night or heavy cloud") },
    { key: "amps", label: "Pump current", tag: "GPIO33 · ACS712-20A", unit: "A", min: 0, max: 12, dec: 2, ticks: [DEF.dryRunA, DEF.overCurrentA],
      get: (l) => l.sensors.pumpA,
      tone: (v, l) => (l.state.fault === "DRY_RUN" || l.state.fault === "OVER_CURRENT" ? "crit" : l.state.pump ? "water" : null),
      note: () => `Dry-run < ${DEF.dryRunA} A · trip > ${DEF.overCurrentA} A` },
    { key: "flow", label: "Water flow", tag: "GPIO27 · YF-S201", unit: "L/min", min: 0, max: 20, dec: 1, ticks: [DEF.noFlowLpm],
      get: (l) => l.sensors.flowLpm,
      tone: (v, l) => (l.state.fault === "NO_FLOW" ? "crit" : v > DEF.noFlowLpm ? "water" : null),
      note: () => `No-flow alarm below ${DEF.noFlowLpm} L/min` }
  ];

  function buildTiles() {
    const host = $("tiles");
    host.innerHTML = "";
    TILES.forEach((t) => {
      const el = document.createElement("div");
      el.className = "tile";
      el.id = "tile-" + t.key;
      const ticks = t.ticks.map((x) => `<i class="tick" style="left:${((x - t.min) / (t.max - t.min)) * 100}%"></i>`).join("");
      el.innerHTML = `
        <div class="tile-head"><span class="tile-label">${t.label}</span><span class="tile-tag">${t.tag}</span></div>
        <div class="tile-value"><span class="num">--</span><span class="unit">${t.unit}</span></div>
        <div class="scale"><div class="fill"></div>${ticks}</div>
        <div class="tile-note">Waiting for data</div>`;
      host.appendChild(el);
    });
  }

  function updateTiles(l) {
    TILES.forEach((t) => {
      const el = $("tile-" + t.key);
      const v = t.get(l);
      const has = typeof v === "number" && isFinite(v);
      el.querySelector(".num").textContent = has ? v.toFixed(t.dec) : "--";
      el.querySelector(".fill").style.width = has ? clamp(((v - t.min) / (t.max - t.min)) * 100, 0, 100) + "%" : "0";
      const tone = t.tone(has ? v : null, l);
      if (tone) el.dataset.tone = tone; else delete el.dataset.tone;
      el.querySelector(".tile-note").textContent = t.note(has ? v : null, l);
    });
  }

  // ------------------------------------------------------------------ summary cards
  const FAULT_TEXT = {
    DRY_RUN: ["Dry run", `Pump drew under ${DEF.dryRunA} A for ${DEF.dryRunMs / 1000} s. Check the tank and suction line, then reset.`],
    OVER_CURRENT: ["Over-current", `Current passed ${DEF.overCurrentA} A after the inrush window. Check for a jammed impeller, then reset.`],
    NO_FLOW: ["No flow", `Flow stayed under ${DEF.noFlowLpm} L/min for ${DEF.noFlowMs / 1000} s. Check for a blocked line or a leak, then reset.`]
  };
  const STOP_TEXT = {
    TARGET_REACHED: "target moisture reached", TANK_FULL: "tank full", HOLD: "operator hold",
    TEMP_ALERT: "temperature alert", SOLAR_LOST: "solar lost and zone not critical", SENSOR_INVALID: "probe reading invalid"
  };

  function updateSummary(l) {
    const s = l.state, se = l.sensors;
    const v = fmt(se.solarV, 1);

    // Power source
    const card = $("card-source");
    let word, why, tag;
    if (s.phase === "SWITCH_BREAK" || s.phase === "SWITCH_SETTLE") {
      tag = "SWITCH"; word = "CHANGEOVER";
      why = `Break-before-make: pump off, ${DEF.deadTimeMs} ms dead time each side of the relay move`;
    } else if (s.source === "SOLAR") {
      tag = "SOLAR"; word = "SOLAR";
      why = `Panel at ${v} V, above the ${DEF.solarOnV} V threshold`;
    } else if (s.source === "GRID") {
      tag = "GRID"; word = "GRID";
      why = `Solar below ${DEF.solarOnV} V and ${zoneName(s.zone)} needed water (started below ${DEF.moistureCritical} %)`;
    } else {
      tag = "NONE"; word = "STANDBY";
      if (s.fault !== "NONE") why = "Pump locked out until the fault is reset";
      else if (s.mode === "HOLD") why = "Operator hold: no zone will start";
      else if (s.tempAlert) why = "Temperature alert: irrigation paused";
      else if (s.tankFull) why = "Tank full: irrigation paused";
      else if (s.solarAvailable) why = `Solar ready at ${v} V. No zone below ${DEF.moistureSolarStart} %`;
      else why = `Solar unavailable (${v} V). Grid only for a zone below ${DEF.moistureCritical} %`;
    }
    card.dataset.source = tag;
    $("source-word").textContent = word;
    $("source-why").textContent = why;

    // Irrigation
    const pc = $("card-pump");
    const m = soilOf(l, s.zone);
    let pw = "Idle", py = "No zone is being watered";
    pc.dataset.run = "off";
    if (s.phase === "RUNNING") {
      pw = zoneName(s.zone); pc.dataset.run = "on";
      py = `${fmt(se.pumpA, 1)} A · ${fmt(se.flowLpm, 1)} L/min · soil ${fmt(m, 0)} % of ${DEF.moistureTarget} % target`;
    } else if (s.phase === "VALVE_OPENING") {
      pw = zoneName(s.zone); pc.dataset.run = "on";
      py = `Valve opening. Pump starts after ${DEF.valveOpenMs / 1000} s`;
    } else if (s.phase === "SWITCH_BREAK" || s.phase === "SWITCH_SETTLE") {
      pw = zoneName(s.zone); py = "Pump paused for the source changeover";
    } else if (s.phase === "STOPPING") {
      pw = "Stopping"; py = `Pump off. Valve closes after ${DEF.valveCloseDelayMs / 1000} s`;
    } else if (s.phase === "FAULT") {
      pw = "Stopped"; py = "Valves closed by the protection trip";
    } else if (s.lastStop && s.lastStop !== "NONE") {
      py = `Last run ended: ${STOP_TEXT[s.lastStop] || s.lastStop}`;
    }
    $("pump-word").textContent = pw;
    $("pump-why").textContent = py;

    // Protection
    const pr = $("card-protect");
    let sev = "ok", pword = "All clear", pwhy = "Dry-run, over-current and no-flow trips armed";
    const badProbe = [1, 2].filter((z) => soilOf(l, z) == null);
    if (s.fault && s.fault !== "NONE") {
      sev = "crit"; [pword, pwhy] = FAULT_TEXT[s.fault] || [s.fault, ""];
    } else if (s.tempAlert) {
      sev = "warn"; pword = "Heat alert";
      pwhy = `Air at ${fmt(se.tempC, 1)} °C, outside ${DEF.tempMinC}–${DEF.tempMaxC} °C. Irrigation paused.`;
    } else if (s.tankFull) {
      sev = "warn"; pword = "Tank full";
      pwhy = `Level at ${DEF.tankOverflowPct} % or float switch high. Valves closed until below ${DEF.tankResumePct} %.`;
    } else if (badProbe.length) {
      sev = "warn"; pword = "Sensor check";
      pwhy = `Zone ${badProbe.join(" and ")} probe reading is invalid, so that zone is skipped.`;
    }
    pr.dataset.sev = sev;
    $("protect-word").textContent = pword;
    $("protect-why").textContent = pwhy;
    $("btn-reset").hidden = !(s.fault && s.fault !== "NONE");

    // Mode
    $("card-mode").dataset.mode = s.mode;
    $("mode-word").textContent = s.mode;
    $("mode-why").textContent = s.mode === "HOLD" ? "Irrigation held by the operator" : "Controller decides when and where to water";
    $("btn-hold").disabled = s.mode === "HOLD";
    $("btn-auto").disabled = s.mode === "AUTO";
  }

  // ------------------------------------------------------------------ diagram
  function updateDiagram(l) {
    const s = l.state, se = l.sensors;
    const relayGrid = s.relay === "GRID";
    const powered = s.pump;
    const setCls = (id, cls, on) => $(id).classList.toggle(cls, !!on);

    $("sld-pv-v").textContent = `${fmt(se.solarV, 1)} V`;
    $("sld-grid-state").textContent = relayGrid && powered ? "supplying" : "standby";
    setCls("w-pv", "live-solar", !relayGrid && powered);
    setCls("w-grid", "live-grid", relayGrid && powered);
    setCls("w-ssr", "live-solar", !relayGrid && powered);
    setCls("w-ssr", "live-grid", relayGrid && powered);
    setCls("w-pump", "live-solar", !relayGrid && powered);
    setCls("w-pump", "live-grid", relayGrid && powered);

    const arm = $("relay-arm");
    arm.setAttribute("x2", 239);
    arm.setAttribute("y2", relayGrid ? 148 : 102);
    arm.classList.toggle("pos-solar", !relayGrid);
    arm.classList.toggle("pos-grid", relayGrid);
    $("sld-relay-label").textContent = relayGrid ? "grid contact" : "solar contact";

    setCls("ssr-box", "on", powered);
    $("sld-ssr").textContent = powered ? "on" : "off";
    setCls("pump-circle", "on", powered);
    setCls("pump-circle", "fault", s.fault && s.fault !== "NONE");
    setCls("impeller", "spin", powered && se.pumpA > 0.2);
    $("sld-amps").textContent = `${fmt(se.pumpA, 2)} A`;
    $("sld-flow").textContent = `${fmt(se.flowLpm, 1)} L/min`;

    const flowing = se.flowLpm > 0.5;
    setCls("p-main", "flow", flowing);
    setCls("p-man", "flow", flowing);
    setCls("p-z1", "flow", flowing && s.valves.z1);
    setCls("p-z2", "flow", flowing && s.valves.z2);
    setCls("v-z1", "open", s.valves.z1);
    setCls("v-z2", "open", s.valves.z2);
    $("sld-z1").textContent = `${fmt(soilOf(l, 1), 0)} %`;
    $("sld-z2").textContent = `${fmt(soilOf(l, 2), 0)} %`;

    const alert = (s.fault && s.fault !== "NONE") || s.tempAlert || s.tankFull;
    const acts = [
      ["CH1 source relay", relayGrid ? "GRID" : "SOLAR", relayGrid ? "grid" : "solar"],
      ["Pump SSR", powered ? "ON" : "OFF", powered ? "water" : ""],
      ["Valve · Zone 1", s.valves.z1 ? "OPEN" : "CLOSED", s.valves.z1 ? "water" : ""],
      ["Valve · Zone 2", s.valves.z2 ? "OPEN" : "CLOSED", s.valves.z2 ? "water" : ""],
      ["Buzzer + LED", s.buzzer ? "SOUNDING" : alert ? "LED ON" : "QUIET", alert ? "crit" : ""]
    ];
    $("actuators").innerHTML = acts.map(([n, st, tone]) =>
      `<li data-tone="${tone}"><span class="a-name">${n}</span><span class="a-state">${st}</span></li>`).join("");
  }

  // ------------------------------------------------------------------ energy
  function updateEnergy(l) {
    const t = l.totals || {};
    const solar = t.solarWh || 0, grid = t.gridWh || 0, total = solar + grid;
    $("eb-solar").style.width = total ? (solar / total) * 100 + "%" : "0";
    $("eb-grid").style.width = total ? (grid / total) * 100 + "%" : "0";
    $("e-solar").textContent = `${fmt(solar, 1)} Wh`;
    $("e-grid").textContent = `${fmt(grid, 1)} Wh`;
    $("s-share").textContent = total ? `${Math.round((solar / total) * 100)} %` : "--";
    $("s-litres").textContent = `${fmt(t.litres || 0, 1)} L`;
    $("s-zones").textContent = `${fmt(t.litresZ1 || 0, 1)} / ${fmt(t.litresZ2 || 0, 1)} L`;
    $("s-switches").textContent = String(t.switches || 0);
    $("s-faults").textContent = String(t.faults || 0);
    $("s-saved").textContent = `₹${((solar / 1000) * CFG.GRID_TARIFF_RS_PER_KWH).toFixed(2)}`;
  }

  // ------------------------------------------------------------------ events
  function eventText(e) {
    const z = zoneName(e.zone);
    const v = typeof e.value === "number" ? e.value : null;
    switch (e.type) {
      case "BOOT": return "Controller started";
      case "SOLAR_AVAILABLE": return `Solar available (${fmt(v, 1)} V)`;
      case "SOLAR_LOST": return `Solar below ${DEF.solarOnV} V for ${DEF.debounceMs / 1000} s (${fmt(v, 1)} V)`;
      case "SOURCE_CHANGED": return `${z}: pump changed over to ${e.detail || "the other source"}`;
      case "ZONE_START": return `${z} started at ${fmt(v, 0)} % moisture`;
      case "ZONE_DONE": return `${z} reached the ${DEF.moistureTarget} % target`;
      case "ZONE_STOPPED": return `${z} stopped: ${STOP_TEXT[e.detail] || e.detail || "condition changed"}`;
      case "FAULT_DRY_RUN": return `Dry run on ${z || "pump"}: ${fmt(v, 2)} A. Pump stopped, valves closed`;
      case "FAULT_OVER_CURRENT": return `Over-current on ${z || "pump"}: ${fmt(v, 1)} A. Pump stopped, valves closed`;
      case "FAULT_NO_FLOW": return `No flow on ${z || "pump"}: ${fmt(v, 1)} L/min. Possible blockage or leak`;
      case "FAULT_CLEARED": return "Fault reset by the operator";
      case "TANK_FULL": return `Tank full (${fmt(v, 0)} %). Valves closed`;
      case "TANK_OK": return `Tank back to ${fmt(v, 0)} %. Irrigation allowed`;
      case "TEMP_ALERT": return `Temperature ${fmt(v, 1)} °C outside ${DEF.tempMinC}–${DEF.tempMaxC} °C. Irrigation paused`;
      case "TEMP_OK": return `Temperature back to ${fmt(v, 1)} °C`;
      case "SENSOR_WARN": return e.zone >= 1 ? `${z} soil probe reading invalid` : "Temperature sensor read failed";
      case "MODE_HOLD": return "Irrigation put on hold by the operator";
      case "MODE_AUTO": return "Automatic control resumed";
      default: return e.type;
    }
  }

  function addEvents(list) {
    events = events.concat(list).sort((a, b) => a.ts - b.ts).slice(-80);
    renderEvents();
  }

  function renderEvents() {
    const host = $("events");
    if (!events.length) {
      host.innerHTML = `<li class="empty">No events yet. They appear here as the controller switches sources, starts zones or trips.</li>`;
      return;
    }
    host.innerHTML = events.slice().reverse().map((e) =>
      `<li data-sev="${e.sev}"><span class="ev-time">${timeOf(e.ts)}</span>` +
      `<span class="ev-msg">${eventText(e)}<span class="ev-type">${e.type}</span></span></li>`).join("");
  }

  // ------------------------------------------------------------------ charts
  const charts = {};

  function colorFor(src) {
    return src === "SOLAR" ? css("--solar") : src === "GRID" ? css("--grid") : css("--line-strong");
  }

  function baseOptions(yMin, yMax, unit) {
    const grid = css("--line"), text = css("--muted");
    return {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      normalized: true,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: {
        legend: { display: true, labels: { color: text, boxWidth: 12, boxHeight: 2, font: { size: 12 }, filter: (i) => !i.text.startsWith("_") } },
        tooltip: { callbacks: { title: (items) => (items.length ? timeOf(items[0].parsed.x) : "") } }
      },
      scales: {
        x: { type: "linear", grid: { color: grid }, ticks: { color: text, maxTicksLimit: 5, callback: (v) => timeOf(v).slice(0, 5) } },
        y: { min: yMin, max: yMax, grid: { color: grid }, ticks: { color: text, callback: (v) => v + " " + unit } }
      }
    };
  }

  function line(label, color, extra) {
    return Object.assign({ label, data: [], borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, tension: 0.25 }, extra || {});
  }

  function guide(label, color) {
    return line("_" + label, color, { borderDash: [5, 4], borderWidth: 1.5, tension: 0 });
  }

  function buildCharts() {
    if (!window.Chart) {
      document.querySelectorAll(".chart-box").forEach((b) => {
        b.innerHTML = `<p class="chart-fallback">Charts need the Chart.js library, which couldn't load. Check the internet connection.</p>`;
      });
      return;
    }
    Object.values(charts).forEach((c) => c.destroy());
    const solar = new Chart($("chart-solar"), {
      type: "line",
      data: { datasets: [
        line("Solar voltage", css("--solar"), { segment: { borderColor: (ctx) => colorFor(ctx.p1.raw.source) } }),
        guide("threshold", css("--muted"))
      ] },
      options: baseOptions(0, 25, "V")
    });
    solar.options.plugins.legend.display = false;
    charts.solar = solar;

    charts.soil = new Chart($("chart-soil"), {
      type: "line",
      data: { datasets: [
        line("Zone 1", css("--water")),
        line("Zone 2", css("--zone2")),
        guide("critical", css("--warn")),
        guide("target", css("--ok"))
      ] },
      options: baseOptions(0, 100, "%")
    });

    const pumpOpts = baseOptions(0, 14, "A");
    pumpOpts.scales.y2 = { position: "right", min: 0, max: 20, grid: { drawOnChartArea: false }, ticks: { color: css("--muted"), callback: (v) => v + " L/m" } };
    charts.pump = new Chart($("chart-pump"), {
      type: "line",
      data: { datasets: [
        line("Current (A)", css("--ink"), { yAxisID: "y", tension: 0 }),
        line("Flow (L/min)", css("--water"), { yAxisID: "y2", tension: 0 })
      ] },
      options: pumpOpts
    });
    renderCharts();
  }

  function trimHistory() {
    const keep = CFG.HISTORY_MINUTES * 60000;
    const newest = history.length ? history[history.length - 1].t : 0;
    history = history.filter((p) => newest - p.t <= keep);
  }

  function addPoint(p) {
    if (!p.t) return;
    const last = history[history.length - 1];
    if (last && Math.abs(last.t - p.t) < 400) return;
    history.push(p);
    if (last && p.t < last.t) history.sort((a, b) => a.t - b.t);
    trimHistory();
  }

  function mergeHistory(points) {
    const byTime = new Map(history.map((p) => [Math.round(p.t / 1000), p]));
    points.forEach((p) => { if (p.t) byTime.set(Math.round(p.t / 1000), p); });
    history = Array.from(byTime.values()).sort((a, b) => a.t - b.t);
    trimHistory();
    renderCharts();
  }

  function series(key) {
    return history.filter((p) => typeof p[key] === "number").map((p) => ({ x: p.t, y: p[key], source: p.source }));
  }

  function renderCharts() {
    if (!charts.solar || !history.length) return;
    const x0 = history[0].t, x1 = history[history.length - 1].t;
    const flat = (y) => [{ x: x0, y }, { x: x1, y }];
    charts.solar.data.datasets[0].data = series("solarV");
    charts.solar.data.datasets[1].data = flat(DEF.solarOnV);
    charts.soil.data.datasets[0].data = series("z1");
    charts.soil.data.datasets[1].data = series("z2");
    charts.soil.data.datasets[2].data = flat(DEF.moistureCritical);
    charts.soil.data.datasets[3].data = flat(DEF.moistureTarget);
    charts.pump.data.datasets[0].data = series("pumpA");
    charts.pump.data.datasets[1].data = series("flowLpm");
    Object.values(charts).forEach((c) => {
      c.options.scales.x.min = x0;
      c.options.scales.x.max = Math.max(x1, x0 + 60000);
      c.update("none");
    });
  }

  // ------------------------------------------------------------------ scenarios + tour
  const SCENARIOS = [
    ["CLOUD", "Cloud cover", "Panel under 18 V for 40 s; Zone 2 made critical"],
    ["NIGHT", "Nightfall", "Jump the field clock to 19:30"],
    ["DAY", "Daybreak", "Jump the field clock to 10:00"],
    ["DRY_TANK", "Tank runs dry", "Starts a run, then dry-run trip"],
    ["BLOCKAGE", "Blocked line", "Starts a run, then no-flow trip"],
    ["JAM", "Jammed pump", "Starts a run, then over-current trip"],
    ["HEATWAVE", "Heatwave", "Air temperature above 45 °C for 40 s"],
    ["TANK_FULL", "Tank overfill", "Tank jumps to 96 %: valves close"],
    ["WIFI_DROP", "Wi-Fi drop", "Device offline for 45 s, data buffered"],
    ["CLEAR", "Clear all", "Remove every injected condition"]
  ];

  function buildScenarios() {
    $("scenarios").innerHTML = SCENARIOS.map(([id, name, desc]) =>
      `<button class="btn scn" type="button" id="scn-${id}" data-scn="${id}"><span class="scn-name">${name}</span><span class="scn-desc">${desc}</span></button>`).join("");
    $("scenarios").addEventListener("click", (e) => {
      const b = e.target.closest("[data-scn]");
      if (!b || !source) return;
      source.scenario(b.dataset.scn).catch(showSendError);
    });
  }

  function updateScenarioState(l) {
    const active = new Set(l.simActive || []);
    SCENARIOS.forEach(([id]) => $("scn-" + id).classList.toggle("is-active", active.has(id)));
  }

  function setTourText(stepText, note) {
    $("tour-step").textContent = stepText;
    $("tour-note").textContent = note;
  }

  function startTour() {
    if (tour) return stopTour("Guided demo stopped.");
    tour = { runner: new TourRunner(), started: Date.now() };
    $("btn-tour").textContent = "Stop guided demo";
    setTourText(`Step 1 of ${TOUR.length} · waiting`, "Waiting for a zone to start watering…");
    tourTimer = setInterval(() => {
      if (!live) return;
      const step = tour.runner.poll((Date.now() - tour.started) / 1000, live.state.phase);
      if (step) {
        setTourText(`Step ${tour.runner.index} of ${TOUR.length} · ${step.action.replace("_", " ").toLowerCase()}`, step.note);
        const send = step.action === "RESET_FAULT" ? source.command("RESET_FAULT") : source.scenario(step.action);
        send.catch(showSendError);
        if (tour.runner.done()) {
          setTimeout(() => stopTour(step.note), 100);
        }
      }
    }, 500);
  }

  function stopTour(note) {
    clearInterval(tourTimer);
    tour = null;
    $("btn-tour").textContent = "Run guided demo";
    setTourText(`${TOUR.length} steps · about 6 minutes`, note);
  }

  function showSendError(err) {
    $("link-note").textContent = `Couldn't send to Firebase: ${err.message}. Check the database rules.`;
  }

  // ------------------------------------------------------------------ status + live
  const LINK_TEXT = { demo: "Demo", online: "Live", stale: "Connecting", offline: "Device offline", error: "Error" };

  function onStatus(st) {
    linkState = st.link;
    $("link-pill").dataset.link = st.link;
    $("link-text").textContent = LINK_TEXT[st.link] || st.link;
    let note = st.note || "";
    if (st.link === "offline" && st.buffered) note += ` · ${st.buffered} items buffered on the device`;
    $("link-note").textContent = note;
  }

  function onLive(l) {
    if (!l || !l.sensors || !l.state) return;
    l.state.valves = l.state.valves || { z1: false, z2: false };
    l.sensors.soil = l.sensors.soil || {};
    live = l;
    updateSummary(l);
    updateDiagram(l);
    updateTiles(l);
    updateEnergy(l);
    updateScenarioState(l);
    $("field-clock").textContent = l.simClock || timeOf(l.ts).slice(0, 5);
    $("fw-version").textContent = `fw ${l.fw || "--"} · up ${Math.round((l.uptimeS || 0) / 60)} min`;
    addPoint({ t: l.ts, solarV: l.sensors.solarV, z1: l.sensors.soil.z1, z2: l.sensors.soil.z2,
      pumpA: l.sensors.pumpA, flowLpm: l.sensors.flowLpm, source: l.state.source });
    renderCharts();
  }

  // ------------------------------------------------------------------ data source
  function readSettings() {
    const params = new URLSearchParams(location.search);
    return {
      mode: params.get("db") ? "firebase" : store.get("hf.mode") || (CFG.FIREBASE_DB_URL ? "firebase" : "demo"),
      db: params.get("db") || store.get("hf.db") || CFG.FIREBASE_DB_URL,
      device: params.get("device") || store.get("hf.device") || CFG.DEVICE_ID,
      auth: store.get("hf.auth") || CFG.FIREBASE_AUTH
    };
  }

  function connect(settings) {
    if (source) source.stop();
    if (tour) stopTour("Guided demo stopped.");
    live = null; history = []; events = [];
    renderEvents();
    renderCharts();
    $("device-chip").textContent = settings.mode === "demo" ? "hf-sim" : settings.device;
    $("sim-sub").textContent = settings.mode === "demo"
      ? "Inject conditions into the simulated farm and watch the controller respond."
      : "Sent through /sim to the device emulator. A real ESP32 ignores these; use them only with backend/emulator.";
    source = settings.mode === "firebase" && settings.db
      ? new FirebaseSource(settings.db, settings.device, settings.auth)
      : new DemoSource();
    source.start({ live: onLive, events: addEvents, history: mergeHistory, status: onStatus });
  }

  function openSettings() {
    const s = readSettings();
    $("mode-demo").checked = s.mode !== "firebase";
    $("mode-fb").checked = s.mode === "firebase";
    $("f-db").value = s.db || "";
    $("f-device").value = s.device || "hf-001";
    $("f-auth").value = s.auth || "";
    $("form-error").hidden = true;
    $("settings").showModal();
  }

  function applySettings(e) {
    e.preventDefault();
    const mode = $("mode-fb").checked ? "firebase" : "demo";
    const db = $("f-db").value.trim();
    const device = $("f-device").value.trim() || "hf-001";
    if (mode === "firebase" && !/^https:\/\/[^/]+\.(firebaseio\.com|firebasedatabase\.app)\/?$/.test(db)) {
      $("form-error").textContent = "Enter the Realtime Database URL from the Firebase console, ending in firebaseio.com or firebasedatabase.app.";
      $("form-error").hidden = false;
      return;
    }
    store.set("hf.mode", mode);
    store.set("hf.db", db);
    store.set("hf.device", device);
    store.set("hf.auth", $("f-auth").value.trim());
    if (location.search) { try { window.history.replaceState(null, "", location.pathname); } catch (err) { /* sandboxed */ } }
    $("settings").close();
    connect({ mode, db, device, auth: $("f-auth").value.trim() });
  }

  // ------------------------------------------------------------------ thresholds table
  function buildThresholds() {
    const rows = [
      ["Solar threshold", `> ${DEF.solarOnV} V for ${DEF.debounceMs / 1000} s`, "Select solar (priority 1)"],
      ["Soil critical", `< ${DEF.moistureCritical} %`, "Grid allowed for that zone (priority 2)"],
      ["Soil solar start", `< ${DEF.moistureSolarStart} %`, "Water the zone while solar is free (firmware addition)"],
      ["Soil target", `${DEF.moistureTarget} %`, "Stop the zone, move to the next"],
      ["Tank overflow", `≥ ${DEF.tankOverflowPct} %, resume < ${DEF.tankResumePct} %`, "Close valves, pump off"],
      ["Temperature range", `${DEF.tempMinC}–${DEF.tempMaxC} °C, ${DEF.tempHystC} °C hysteresis`, "Alert and pause irrigation"],
      ["Dry run", `< ${DEF.dryRunA} A for ${DEF.dryRunMs / 1000} s`, "Pump off, valves closed, alarm (latched)"],
      ["Over-current", `> ${DEF.overCurrentA} A after ${DEF.inrushMs / 1000} s inrush`, "Pump off, valves closed, alarm (latched)"],
      ["No flow", `< ${DEF.noFlowLpm} L/min for ${DEF.noFlowMs / 1000} s after ${DEF.startupDelayMs / 1000} s start-up`, "Pump off, valves closed, alarm (latched)"],
      ["Changeover dead time", `${DEF.deadTimeMs} ms each side`, "Break-before-make source switch"],
      ["Valve sequencing", `open ${DEF.valveOpenMs / 1000} s before pump, close ${DEF.valveCloseDelayMs / 1000} s after`, "No dead-heading or water hammer"]
    ];
    $("thr-body").innerHTML = rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join("");
  }

  // ------------------------------------------------------------------ boot
  function wire() {
    $("btn-hold").addEventListener("click", () => source && source.command("HOLD").catch(showSendError));
    $("btn-auto").addEventListener("click", () => source && source.command("AUTO").catch(showSendError));
    $("btn-reset").addEventListener("click", () => source && source.command("RESET_FAULT").catch(showSendError));
    $("btn-tour").addEventListener("click", startTour);
    $("open-settings").addEventListener("click", openSettings);
    $("settings-form").addEventListener("submit", applySettings);
    $("settings-cancel").addEventListener("click", () => $("settings").close());
    $("tariff-note").textContent = `Cost avoided is an estimate at ₹${CFG.GRID_TARIFF_RS_PER_KWH.toFixed(2)}/kWh of grid energy displaced by solar.`;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const rebuild = () => buildCharts();
    if (mq.addEventListener) mq.addEventListener("change", rebuild);
    new MutationObserver(rebuild).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  buildTiles();
  buildScenarios();
  buildThresholds();
  renderEvents();
  wire();
  buildCharts();
  connect(readSettings());
})();
