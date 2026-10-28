"""HTML building blocks for the Streamlit dashboard.

Pure functions of the device's /live document (docs/data-model.md), kept
separate from app.py so they can be unit-tested without Streamlit.
"""
from __future__ import annotations

import html
from datetime import datetime

from hybridflow.controller import Config

C = Config()

# Palette: amber = solar, blue = grid, teal = water; orange/red only for alerts.
COL = {
    "bg": "#edf0eb", "surface": "#ffffff", "surface2": "#f5f7f3", "ink": "#17201b", "muted": "#5b6961",
    "line": "#d5dbd2", "line_strong": "#98a39b", "solar": "#b67600", "solar_soft": "#f7ebd2",
    "grid": "#2a5bd0", "grid_soft": "#e1e8fa", "water": "#0a7a75", "water_soft": "#daefed",
    "zone2": "#9b3f8c", "ok": "#2e7d45", "ok_soft": "#dff0e3", "warn": "#c25a00", "warn_soft": "#f8e6d6",
    "crit": "#c0352b", "crit_soft": "#f8e0dd",
}

FAULT_TEXT = {
    "DRY_RUN": ("Dry run", f"Pump drew under {C.dry_run_a} A for {C.dry_run_ms // 1000} s. "
                "Check the tank and suction line, then reset."),
    "OVER_CURRENT": ("Over-current", f"Current passed {C.over_current_a:g} A after the inrush window. "
                     "Check for a jammed impeller, then reset."),
    "NO_FLOW": ("No flow", f"Flow stayed under {C.no_flow_lpm:g} L/min for {C.no_flow_ms // 1000} s. "
                "Check for a blocked line or a leak, then reset."),
}
STOP_TEXT = {
    "TARGET_REACHED": "target moisture reached", "TANK_FULL": "tank full", "HOLD": "operator hold",
    "TEMP_ALERT": "temperature alert", "SOLAR_LOST": "solar lost and zone not critical",
    "SENSOR_INVALID": "probe reading invalid",
}

SCENARIOS = [  # id, button label, tooltip, what happens (shown when clicked)
    ("CLOUD", "Cloud cover", "Panel under 18 V for 40 s",
     "Solar drops below 18 V and Zone 2 is made critical. After 5 s the pump changes over to grid."),
    ("NIGHT", "Nightfall", "Field clock to 19:30",
     "Clock set to 19:30. Solar is lost after 5 s; only a zone below 30 % will run, on grid."),
    ("DAY", "Daybreak", "Field clock to 10:00",
     "Clock set to 10:00. Solar comes back after 5 s."),
    ("DRY_TANK", "Tank runs dry", "Dry-run trip",
     "Tank emptied. The pump starts on Zone 1 and trips on dry run within about 5 s."),
    ("BLOCKAGE", "Blocked line", "No-flow trip",
     "Line blocked. The pump starts on Zone 1 and trips on no flow after about 11 s."),
    ("JAM", "Jammed pump", "Over-current trip",
     "Impeller jammed. The pump starts on Zone 1 and trips on over-current after about 1 s."),
    ("HEATWAVE", "Heatwave", "Above 45 °C for 40 s",
     "Temperature jumps above 45 °C. Irrigation pauses and the alarm sounds until it cools."),
    ("TANK_FULL", "Tank overfill", "Past 95 %",
     "Tank at 96 %. Valves close until the level falls below 90 %."),
    ("WIFI_DROP", "Wi-Fi drop", "Offline 45 s, data buffered",
     "Device offline for 45 s. The dashboard shows Device offline, then catches up with the buffered data."),
    ("CLEAR", "Clear all", "Remove injected conditions", "All test conditions removed."),
]
SCENARIO_NAMES = {sid: name for sid, name, _, _ in SCENARIOS}


def esc(x) -> str:
    return html.escape(str(x))


def fmt(v, d=1) -> str:
    return f"{v:.{d}f}" if isinstance(v, (int, float)) and v == v else "--"


def time_of(ms) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S") if ms else "--:--:--"


def soil(live, z):
    return ((live.get("sensors") or {}).get("soil") or {}).get(f"z{z}")


def zone_name(z) -> str:
    return f"Zone {z}" if z and z >= 1 else ""


def normalise(live: dict) -> dict:
    """Fills in keys Firebase drops (false booleans are kept, but empty maps vanish)."""
    live = dict(live or {})
    live.setdefault("sensors", {})
    live.setdefault("state", {})
    live.setdefault("totals", {})
    live["sensors"].setdefault("soil", {})
    st = live["state"]
    st.setdefault("valves", {"z1": False, "z2": False})
    for k, v in (("source", "NONE"), ("relay", "SOLAR"), ("phase", "IDLE"), ("mode", "AUTO"),
                 ("fault", "NONE"), ("zone", 0), ("lastStop", "NONE")):
        st.setdefault(k, v)
    return live


# ------------------------------------------------------------------ CSS

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@600;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
.hf, .hf * {{ box-sizing: border-box; }}
.hf {{ font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; color: {COL['ink']}; }}
.hf-mono {{ font-family: 'IBM Plex Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
.hf-top {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:8px 16px; margin-bottom:4px; }}
.hf-brand {{ display:flex; align-items:center; gap:10px; }}
.hf-brand b {{ font: 700 28px/1 'Barlow Semi Condensed', 'Arial Narrow', sans-serif; }}
.hf-brand span {{ display:block; font-size:13px; color:{COL['muted']}; }}
.hf-meta {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:13px; color:{COL['muted']}; }}
.hf-chip {{ border:1px solid {COL['line']}; border-radius:4px; padding:2px 8px; }}
.hf-pill {{ font: 600 12px/1 'Barlow Semi Condensed', sans-serif; letter-spacing:.08em; text-transform:uppercase; padding:6px 10px; border-radius:999px; }}
.hf-note {{ font-size:13px; color:{COL['muted']}; margin:0 0 8px; }}
.hf-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }}
.hf-card {{ background:{COL['surface']}; border:1px solid {COL['line']}; border-top:4px solid {COL['line']}; border-radius:8px; padding:12px 14px; }}
.hf-eyebrow {{ font: 600 12px/1 'Barlow Semi Condensed', sans-serif; letter-spacing:.1em; text-transform:uppercase; color:{COL['muted']}; }}
.hf-word {{ font: 700 32px/1.1 'Barlow Semi Condensed', 'Arial Narrow', sans-serif; margin-top:8px; }}
.hf-why {{ font-size:13px; color:{COL['muted']}; margin-top:4px; min-height:2.6em; }}
.hf-panel {{ background:{COL['surface']}; border:1px solid {COL['line']}; border-radius:8px; padding:14px 16px; }}
.hf-h {{ font: 700 19px/1.2 'Barlow Semi Condensed', sans-serif; margin:0; }}
.hf-sub {{ font-size:13px; color:{COL['muted']}; margin:2px 0 10px; }}
.hf-scroll {{ overflow-x:auto; }}
.hf-sld {{ display:block; width:100%; min-width:620px; height:auto; }}
.hf-acts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:8px; margin-top:10px; }}
.hf-act {{ display:flex; justify-content:space-between; gap:8px; background:{COL['surface2']}; border-radius:6px; padding:7px 10px; font-size:13px; }}
.hf-act span:first-child {{ color:{COL['muted']}; }}
.hf-act b {{ font: 600 13px 'IBM Plex Mono', monospace; }}
.hf-tiles {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }}
.hf-tile {{ background:{COL['surface']}; border:1px solid {COL['line']}; border-left:4px solid {COL['line']}; border-radius:8px; padding:10px 12px; }}
.hf-tile-h {{ display:flex; justify-content:space-between; gap:6px; align-items:baseline; }}
.hf-tile-h b {{ font: 600 14px 'Barlow Semi Condensed', sans-serif; letter-spacing:.03em; }}
.hf-tile-h span {{ font: 400 11px 'IBM Plex Mono', monospace; color:{COL['muted']}; white-space:nowrap; }}
.hf-val {{ margin-top:4px; }}
.hf-val b {{ font: 500 26px/1 'IBM Plex Mono', monospace; }}
.hf-val span {{ font-size:13px; color:{COL['muted']}; margin-left:3px; }}
.hf-scale {{ position:relative; height:6px; margin:9px 0 6px; border-radius:3px; background:{COL['surface2']}; box-shadow: inset 0 0 0 1px {COL['line']}; }}
.hf-fill {{ position:absolute; left:0; top:0; bottom:0; border-radius:3px; }}
.hf-tick {{ position:absolute; top:-3px; bottom:-3px; width:2px; margin-left:-1px; background:{COL['ink']}; opacity:.55; }}
.hf-tile p {{ font-size:12px; color:{COL['muted']}; margin:0; }}
.hf-bar {{ display:flex; height:18px; border-radius:4px; overflow:hidden; background:{COL['surface2']}; box-shadow: inset 0 0 0 1px {COL['line']}; }}
.hf-stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px 16px; margin-top:12px; }}
.hf-stats div {{ border-top:1px solid {COL['line']}; padding-top:6px; }}
.hf-stats span {{ display:block; font-size:12px; color:{COL['muted']}; }}
.hf-stats b {{ font: 500 18px 'IBM Plex Mono', monospace; }}
.hf-events {{ list-style:none; margin:0; padding:0; display:grid; gap:6px; max-height:330px; overflow-y:auto; }}
.hf-events li {{ display:grid; grid-template-columns:auto 1fr; gap:10px; padding:6px 10px; border-left:3px solid {COL['line_strong']}; background:{COL['surface2']}; border-radius:0 6px 6px 0; font-size:13px; margin:0; }}
.hf-events li.warn {{ border-left-color:{COL['warn']}; }}
.hf-events li.crit {{ border-left-color:{COL['crit']}; background:{COL['crit_soft']}; }}
.hf-events time {{ font: 400 12px 'IBM Plex Mono', monospace; color:{COL['muted']}; }}
.hf-events small {{ display:block; font: 500 11px 'IBM Plex Mono', monospace; color:{COL['muted']}; }}
.hf-tour {{ background:{COL['water_soft']}; border-radius:6px; padding:10px 12px; font-size:13px; }}
.hf-tour b {{ color:{COL['water']}; font: 500 12px 'IBM Plex Mono', monospace; }}
@keyframes hfspin {{ to {{ transform: rotate(360deg); }} }}
@keyframes hfflow {{ to {{ stroke-dashoffset: -18; }} }}
.hf-spin {{ transform-origin: 476px 125px; animation: hfspin .9s linear infinite; }}
.hf-flow {{ stroke-dasharray: 10 8; animation: hfflow .8s linear infinite; }}
@media (prefers-reduced-motion: reduce) {{ .hf-spin, .hf-flow {{ animation: none; }} }}
</style>
"""


def _one_line(s: str) -> str:
    """Streamlit markdown treats indented lines as code; emit HTML on one line."""
    return "".join(line.strip() for line in s.splitlines())


# ------------------------------------------------------------------ knobs

# Readings the firmware takes from a bench knob (or, for temperature, a fixed
# value). New firmware lists them in live["knobs"]; older firmware only sent
# inputs="knobs", meaning every input was a knob.
KNOB_ORDER = ("solar", "soil", "tank", "light", "temp", "current", "flow")
KNOB_NAMES = {"solar": "solar voltage", "soil": "soil moisture", "tank": "tank level", "light": "light",
              "temp": "temperature (fixed)", "current": "pump current", "flow": "water flow"}


def knob_keys(live: dict | None) -> set[str]:
    if not live:
        return set()
    if isinstance(live.get("knobs"), list):
        return {k for k in live["knobs"] if k in KNOB_NAMES}
    if live.get("inputs") == "knobs":
        return {"solar", "soil", "tank", "light", "current", "flow"}
    return set()


def demo_markdown(live: dict | None) -> str:
    """What to do on the bench to show each behaviour, for the sensors this build has."""
    keys = knob_keys(live) if live else {"solar", "current", "flow"}
    soil = "the **Soil Zone 2** knob low" if "soil" in keys else "the **Zone 2 probe** out in dry air"
    wet = "the **Soil Zone 2** knob past 60 %" if "soil" in keys else "the **Zone 2 probe** in a glass of water"
    tank = ("the **Tank** knob fully up" if "tank" in keys
            else "a **hand within 7 cm** of the HC-SR04, or lift the **float switch**")
    lines = [
        f"- {soil[0].upper() + soil[1:]} → valve relay 3 clicks, pump relay 4 a second later",
        f"- {wet[0].upper() + wet[1:]} → pump stops, then the valve",
    ]
    if "solar" in keys:
        lines.append("- **Solar** knob below ¾ turn (18 V) with a zone below 30 % → after 5 s, relay 1 to grid")
    if "current" in keys:
        lines.append("- **Current** knob to zero while pumping → dry-run trip in 3 s, buzzer")
        lines.append("- **Current** knob fully up → over-current trip")
    if "flow" in keys:
        lines.append("- **Flow** knob to zero → no-flow trip after about 10 s")
    lines.append(f"- {tank[0].upper() + tank[1:]} → tank full, everything stops")
    if "temp" not in keys:
        lines.append("- Warm air on the **DHT22** past 45 °C → heat alert, irrigation pauses")
    if "light" not in keys:
        lines.append("- Cover the **LDR** → light reading drops (shown on the dashboard only)")
    tail = "\n\nBefore **Reset fault**, put the knob back to normal, or it trips again." if keys & {"current", "flow"} else ""
    return "\n".join(lines) + tail


# ------------------------------------------------------------------ header

LINK = {
    "sim": ("Simulator", COL["water_soft"], COL["water"]),
    "online": ("Live", COL["ok_soft"], COL["ok"]),
    "stale": ("Connecting", COL["surface2"], COL["muted"]),
    "offline": ("Device offline", COL["warn_soft"], COL["warn"]),
    "error": ("Error", COL["crit_soft"], COL["crit"]),
}


def header_html(status: dict, live: dict | None, device: str) -> str:
    label, bg, fg = LINK.get(status.get("link", "stale"), LINK["stale"])
    clock = (live or {}).get("simClock") or (time_of(live["ts"])[:5] if live and live.get("ts") else "--:--")
    note = status.get("note", "")
    keys = knob_keys(live)
    if keys:
        names = [KNOB_NAMES[k] for k in KNOB_ORDER if k in keys]
        note += " · Bench build: knobs stand in for " + ", ".join(names)
    if status.get("buffered"):
        note += f" · {status['buffered']} items buffered on the device"
    return _one_line(f"""
<div class="hf"><div class="hf-top">
<div class="hf-brand"><svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true"><circle cx="11" cy="11" r="5" fill="{COL['solar']}"/><path d="M18 26c-4 0-6-3-6-5.5 0-3 3.4-6.6 6-9.5 2.6 2.9 6 6.5 6 9.5C24 23 22 26 18 26z" fill="{COL['water']}"/></svg>
<div><b>Hybrid-Flow</b><span>Smart Irrigation &amp; Energy Manager</span></div></div>
<div class="hf-meta"><span class="hf-chip hf-mono">{esc(device)}</span>
<span class="hf-pill" style="background:{bg};color:{fg}">{label}</span>
<span class="hf-mono" title="Field time">{esc(clock)}</span></div></div>
<p class="hf-note">{esc(note)}</p></div>""")


# ------------------------------------------------------------------ status cards

def status_cards(live: dict) -> list[dict]:
    """Four summary cards: power source, irrigation, protection, operator mode."""
    s, se = live["state"], live["sensors"]
    v = fmt(se.get("solarV"), 1)
    cards = []

    if s["phase"] in ("SWITCH_BREAK", "SWITCH_SETTLE"):
        cards.append(("Power source", "CHANGEOVER", COL["warn"],
                      f"Break-before-make: pump off, {C.dead_time_ms} ms dead time each side of the relay move"))
    elif s["source"] == "SOLAR":
        cards.append(("Power source", "SOLAR", COL["solar"], f"Panel at {v} V, above the {C.solar_on_v:g} V threshold"))
    elif s["source"] == "GRID":
        cards.append(("Power source", "GRID", COL["grid"],
                      f"Solar below {C.solar_on_v:g} V and {zone_name(s['zone'])} needed water "
                      f"(started below {C.moisture_critical:g} %)"))
    else:
        if s["fault"] != "NONE":
            why = "Pump locked out until the fault is reset"
        elif s["mode"] == "HOLD":
            why = "Operator hold: no zone will start"
        elif s.get("tempAlert"):
            why = "Temperature alert: irrigation paused"
        elif s.get("tankFull"):
            why = "Tank full: irrigation paused"
        elif s.get("solarAvailable"):
            why = f"Solar ready at {v} V. No zone below {C.moisture_solar_start:g} %"
        else:
            why = f"Solar unavailable ({v} V). Grid only for a zone below {C.moisture_critical:g} %"
        cards.append(("Power source", "STANDBY", COL["line_strong"], why))

    m = soil(live, s["zone"])
    if s["phase"] == "RUNNING":
        cards.append(("Irrigation", zone_name(s["zone"]), COL["water"],
                      f"{fmt(se.get('pumpA'), 1)} A · {fmt(se.get('flowLpm'), 1)} L/min · "
                      f"soil {fmt(m, 0)} % of {C.moisture_target:g} % target"))
    elif s["phase"] == "VALVE_OPENING":
        cards.append(("Irrigation", zone_name(s["zone"]), COL["water"],
                      f"Valve opening. Pump starts after {C.valve_open_ms / 1000:g} s"))
    elif s["phase"] in ("SWITCH_BREAK", "SWITCH_SETTLE"):
        cards.append(("Irrigation", zone_name(s["zone"]), COL["warn"], "Pump paused for the source changeover"))
    elif s["phase"] == "STOPPING":
        cards.append(("Irrigation", "Stopping", COL["line_strong"],
                      f"Pump off. Valve closes after {C.valve_close_delay_ms / 1000:g} s"))
    elif s["phase"] == "FAULT":
        cards.append(("Irrigation", "Stopped", COL["crit"], "Valves closed by the protection trip"))
    else:
        last = s.get("lastStop", "NONE")
        why = f"Last run ended: {STOP_TEXT.get(last, last)}" if last != "NONE" else "No zone is being watered"
        cards.append(("Irrigation", "Idle", COL["line_strong"], why))

    bad = [z for z in (1, 2) if soil(live, z) is None]
    if s["fault"] != "NONE":
        word, why = FAULT_TEXT.get(s["fault"], (s["fault"], ""))
        cards.append(("Protection", word, COL["crit"], why))
    elif s.get("tempAlert"):
        cards.append(("Protection", "Heat alert", COL["warn"],
                      f"Air at {fmt(se.get('tempC'), 1)} °C, outside {C.temp_min_c:g}–{C.temp_max_c:g} °C. Irrigation paused."))
    elif s.get("tankFull"):
        cards.append(("Protection", "Tank full", COL["warn"],
                      f"Level at {C.tank_overflow_pct:g} % or float switch high. Valves closed until below {C.tank_resume_pct:g} %."))
    elif bad:
        cards.append(("Protection", "Sensor check", COL["warn"],
                      f"Zone {' and '.join(map(str, bad))} probe reading is invalid, so that zone is skipped."))
    else:
        cards.append(("Protection", "All clear", COL["ok"], "Dry-run, over-current and no-flow trips armed"))

    if s["mode"] == "HOLD":
        cards.append(("Operator control", "HOLD", COL["warn"], "Irrigation held by the operator"))
    else:
        cards.append(("Operator control", "AUTO", COL["line_strong"], "Controller decides when and where to water"))

    return [{"title": t, "word": w, "color": c, "why": y} for t, w, c, y in cards]


def card_html(card: dict) -> str:
    word_color = COL["ink"] if card["color"] == COL["line_strong"] else card["color"]
    bg = COL["crit_soft"] if card["color"] == COL["crit"] else COL["surface"]
    return _one_line(f"""
<div class="hf"><div class="hf-card" style="border-top-color:{card['color']};background:{bg}">
<div class="hf-eyebrow">{esc(card['title'])}</div>
<div class="hf-word" style="color:{word_color}">{esc(card['word'])}</div>
<div class="hf-why">{esc(card['why'])}</div></div></div>""")


# ------------------------------------------------------------------ diagram

def diagram_html(live: dict) -> str:
    s, se = live["state"], live["sensors"]
    grid = s["relay"] == "GRID"
    on = bool(s.get("pump"))
    src_col = COL["grid"] if grid else COL["solar"]
    wire = lambda active: src_col if active else COL["line_strong"]  # noqa: E731
    flowing = (se.get("flowLpm") or 0) > 0.5
    pipe = lambda active: (COL["water"], "hf-flow") if active else (COL["line"], "")  # noqa: E731
    fault = s["fault"] != "NONE"
    pump_stroke = COL["crit"] if fault else COL["water"] if on else COL["line_strong"]
    pump_fill = COL["crit_soft"] if fault else COL["water_soft"] if on else COL["surface2"]
    valves = s.get("valves") or {}
    arm_y = 148 if grid else 102
    z1c, z1cls = pipe(flowing and valves.get("z1"))
    z2c, z2cls = pipe(flowing and valves.get("z2"))
    mc, mcls = pipe(flowing)
    vfill = lambda o: COL["water"] if o else COL["surface"]  # noqa: E731
    vstroke = lambda o: COL["water"] if o else COL["line_strong"]  # noqa: E731
    t_title = "font:700 14px 'Barlow Semi Condensed',sans-serif;letter-spacing:.06em"
    t_sub = f"font:400 12px 'IBM Plex Sans',sans-serif;fill:{COL['muted']}"
    t_val = "font:500 14px 'IBM Plex Mono',monospace"
    t_lbl = f"font:600 12px 'Barlow Semi Condensed',sans-serif;letter-spacing:.08em;fill:{COL['muted']}"
    blk = f"fill:{COL['surface2']};stroke:{COL['line_strong']};stroke-width:1.5"

    svg = f"""
<svg class="hf-sld" viewBox="0 0 780 250" role="img" aria-label="Active power source, pump and open valves" style="fill:{COL['ink']}">
<rect x="12" y="22" width="132" height="68" rx="4" style="{blk}"/>
<path d="M24 34h30v22H24zM24 45h30M39 34v22" fill="none" stroke="{COL['line_strong']}"/>
<text x="62" y="42" style="{t_title}">PV ARRAY</text><text x="62" y="57" style="{t_sub}">via inverter</text>
<text x="24" y="80" style="{t_val}">{fmt(se.get('solarV'), 1)} V</text>
<rect x="12" y="158" width="132" height="68" rx="4" style="{blk}"/>
<path d="M26 172l10 18-10 18M36 190h18" fill="none" stroke="{COL['line_strong']}" stroke-width="2"/>
<text x="62" y="178" style="{t_title}">GRID</text><text x="62" y="193" style="{t_sub}">230 V AC</text>
<text x="24" y="216" style="{t_val}">{'supplying' if grid and on else 'standby'}</text>
<path d="M144 56H236V100" fill="none" stroke="{wire(on and not grid)}" stroke-width="3"/>
<path d="M144 192H236V150" fill="none" stroke="{wire(on and grid)}" stroke-width="3"/>
<rect x="220" y="84" width="76" height="82" rx="4" fill="none" stroke="{COL['line_strong']}" stroke-dasharray="4 4"/>
<text x="258" y="80" text-anchor="middle" style="{t_lbl}">CH1</text>
<circle cx="236" cy="100" r="4" fill="{COL['surface']}" stroke="{COL['line_strong']}" stroke-width="2"/>
<circle cx="236" cy="150" r="4" fill="{COL['surface']}" stroke="{COL['line_strong']}" stroke-width="2"/>
<circle cx="280" cy="125" r="4" fill="{COL['line_strong']}"/>
<line x1="280" y1="125" x2="239" y2="{arm_y}" stroke="{src_col}" stroke-width="4" stroke-linecap="round"/>
<text x="258" y="182" text-anchor="middle" style="{t_lbl}">{'grid contact' if grid else 'solar contact'}</text>
<path d="M284 125H332" fill="none" stroke="{wire(on)}" stroke-width="3"/>
<rect x="332" y="103" width="72" height="44" rx="4" style="fill:{COL['water_soft'] if on else COL['surface2']};stroke:{COL['water'] if on else COL['line_strong']};stroke-width:1.5"/>
<text x="368" y="122" text-anchor="middle" style="{t_title}">SSR</text>
<text x="368" y="138" text-anchor="middle" style="{t_sub}">{'on' if on else 'off'}</text>
<path d="M404 125H444" fill="none" stroke="{wire(on)}" stroke-width="3"/>
<circle cx="476" cy="125" r="31" fill="{pump_fill}" stroke="{pump_stroke}" stroke-width="2"/>
<g class="{'hf-spin' if on and (se.get('pumpA') or 0) > 0.2 else ''}" stroke="{COL['water'] if on else COL['muted']}"><path d="M476 125l0-17M476 125l15 9M476 125l-15 9" stroke-width="3" stroke-linecap="round"/></g>
<text x="476" y="176" text-anchor="middle" style="{t_lbl}">PUMP</text>
<text x="476" y="194" text-anchor="middle" style="{t_val}">{fmt(se.get('pumpA'), 2)} A</text>
<path class="{mcls}" d="M507 125H560" fill="none" stroke="{mc}" stroke-width="6"/>
<rect x="560" y="109" width="52" height="32" rx="4" style="{blk}"/>
<text x="586" y="130" text-anchor="middle" style="{t_title}">FT</text>
<text x="586" y="160" text-anchor="middle" style="{t_val}">{fmt(se.get('flowLpm'), 1)} L/min</text>
<path class="{mcls}" d="M612 125H636" fill="none" stroke="{mc}" stroke-width="6"/>
<path class="{z1cls}" d="M636 125V62H660M676 62H700" fill="none" stroke="{z1c}" stroke-width="6"/>
<path class="{z2cls}" d="M636 125V188H660M676 188H700" fill="none" stroke="{z2c}" stroke-width="6"/>
<path d="M660 52L676 72V52L660 72Z" fill="{vfill(valves.get('z1'))}" stroke="{vstroke(valves.get('z1'))}" stroke-width="2" stroke-linejoin="round"/>
<path d="M660 178L676 198V178L660 198Z" fill="{vfill(valves.get('z2'))}" stroke="{vstroke(valves.get('z2'))}" stroke-width="2" stroke-linejoin="round"/>
<text x="704" y="58" style="{t_title}">ZONE 1</text><text x="704" y="78" style="{t_val}">{fmt(soil(live, 1), 0)} %</text>
<text x="704" y="184" style="{t_title}">ZONE 2</text><text x="704" y="204" style="{t_val}">{fmt(soil(live, 2), 0)} %</text>
</svg>"""

    alert = fault or s.get("tempAlert") or s.get("tankFull")
    acts = [
        ("CH1 source relay", "GRID" if grid else "SOLAR", src_col),
        ("Pump SSR", "ON" if on else "OFF", COL["water"] if on else COL["ink"]),
        ("Valve · Zone 1", "OPEN" if valves.get("z1") else "CLOSED", COL["water"] if valves.get("z1") else COL["ink"]),
        ("Valve · Zone 2", "OPEN" if valves.get("z2") else "CLOSED", COL["water"] if valves.get("z2") else COL["ink"]),
        ("Buzzer + LED", "SOUNDING" if s.get("buzzer") else "LED ON" if alert else "QUIET",
         COL["crit"] if alert else COL["ink"]),
    ]
    acts_html = "".join(f'<div class="hf-act"><span>{n}</span><b style="color:{c}">{st}</b></div>' for n, st, c in acts)
    return _one_line(f"""
<div class="hf"><div class="hf-panel"><p class="hf-h">Power and water path</p>
<p class="hf-sub">Live single-line view: CH1 changeover relay, pump-enable SSR, pump, flow meter and zone valves</p>
<div class="hf-scroll">{svg}</div><div class="hf-acts">{acts_html}</div></div></div>""")


# ------------------------------------------------------------------ sensor tiles

def tiles(live: dict) -> list[dict]:
    s, se = live["state"], live["sensors"]
    valves = s.get("valves") or {}
    keys = knob_keys(live)   # bench build: knobs stand in for these readings
    tag = lambda key, real, knob: knob if key in keys else real  # noqa: E731
    out = []

    def add(label, tag, value, unit, lo, hi, dec, ticks, tone, note):
        out.append({"label": label, "tag": tag, "value": value, "unit": unit, "min": lo, "max": hi,
                    "dec": dec, "ticks": ticks, "tone": tone, "note": note})

    v = se.get("solarV")
    add("Solar voltage", tag("solar", "GPIO34 · divider", "Knob · GPIO34"), v, "V", 0, 25, 1, [C.solar_on_v],
        "solar" if s.get("solarAvailable") else None,
        f"Above {C.solar_on_v:g} V: solar has priority" if s.get("solarAvailable")
        else f"Below {C.solar_on_v:g} V: solar unavailable")
    for z, pin in ((1, 35), (2, 39)):
        m = soil(live, z)
        open_ = valves.get(f"z{z}")
        tone = "crit" if m is None else "water" if open_ else "warn" if m < C.moisture_critical \
            else "ok" if m >= C.moisture_target else None
        note = ("Probe reading invalid: zone skipped" if m is None
                else f"Valve open · watering to {C.moisture_target:g} %" if open_
                else f"Critical: grid allowed below {C.moisture_critical:g} %" if m < C.moisture_critical
                else f"Critical {C.moisture_critical:g} % · target {C.moisture_target:g} %")
        add(f"Soil moisture · Zone {z}", tag("soil", f"GPIO{pin} · capacitive", f"Knob · GPIO{pin}"), m, "%", 0, 100, 0,
            [C.moisture_critical, C.moisture_solar_start, C.moisture_target], tone, note)
    t = se.get("tankPct")
    add("Tank level", tag("tank", "HC-SR04 · GPIO13/14", "Knob · GPIO32"), t, "%", 0, 100, 0, [C.tank_resume_pct, C.tank_overflow_pct],
        "warn" if s.get("tankFull") else "crit" if t is not None and t < 5 else "water",
        "Float switch high: overflow" if se.get("floatHigh") else f"Valves close at {C.tank_overflow_pct:g} %")
    tc = se.get("tempC")
    add("Air temperature", tag("temp", "GPIO4 · DHT22", "Fixed value"), tc, "°C", -5, 55, 1, [C.temp_min_c, C.temp_max_c],
        "crit" if tc is None else "warn" if s.get("tempAlert") else None,
        f"Humidity {fmt(se.get('humidity'), 0)} % · safe {C.temp_min_c:g}–{C.temp_max_c:g} °C")
    lp = se.get("lightPct")
    add("Light intensity", tag("light", "GPIO32 · LDR", "From solar reading"), lp, "%", 0, 100, 0, [], None,
        "--" if lp is None else "Bright sun" if lp > 60 else "Overcast or low sun" if lp > 20 else "Dark: night or heavy cloud")
    a = se.get("pumpA")
    add("Pump current", tag("current", "GPIO33 · ACS712", "Knob · GPIO33"), a, "A", 0, 12, 2, [C.dry_run_a, C.over_current_a],
        "crit" if s["fault"] in ("DRY_RUN", "OVER_CURRENT") else "water" if s.get("pump") else None,
        f"Dry-run < {C.dry_run_a:g} A · trip > {C.over_current_a:g} A")
    f = se.get("flowLpm")
    add("Water flow", tag("flow", "GPIO27 · YF-S201", "Knob · GPIO36"), f, "L/min", 0, 20, 1, [C.no_flow_lpm],
        "crit" if s["fault"] == "NO_FLOW" else "water" if (f or 0) > C.no_flow_lpm else None,
        f"No-flow alarm below {C.no_flow_lpm:g} L/min")
    return out


TONE = {"ok": COL["ok"], "warn": COL["warn"], "crit": COL["crit"], "solar": COL["solar"], "water": COL["water"],
        None: COL["line_strong"]}


def tiles_html(live: dict) -> str:
    parts = []
    for t in tiles(live):
        v = t["value"]
        has = isinstance(v, (int, float)) and v == v
        pct = max(0.0, min(100.0, (v - t["min"]) / (t["max"] - t["min"]) * 100)) if has else 0
        col = TONE[t["tone"]]
        ticks = "".join(f'<i class="hf-tick" style="left:{(x - t["min"]) / (t["max"] - t["min"]) * 100:.1f}%"></i>'
                        for x in t["ticks"])
        bg = COL["crit_soft"] if t["tone"] == "crit" else COL["surface"]
        num = f'{v:.{t["dec"]}f}' if has else "--"
        parts.append(
            f'<div class="hf-tile" style="border-left-color:{col};background:{bg}">'
            f'<div class="hf-tile-h"><b>{esc(t["label"])}</b><span>{esc(t["tag"])}</span></div>'
            f'<div class="hf-val"><b>{num}</b><span>{t["unit"]}</span></div>'
            f'<div class="hf-scale"><div class="hf-fill" style="width:{pct:.1f}%;background:{col}"></div>{ticks}</div>'
            f'<p>{esc(t["note"])}</p></div>')
    return f'<div class="hf"><div class="hf-tiles">{"".join(parts)}</div></div>'


# ------------------------------------------------------------------ energy

def energy_html(live: dict, tariff: float) -> str:
    t = live.get("totals") or {}
    solar, grid = t.get("solarWh") or 0.0, t.get("gridWh") or 0.0
    total = solar + grid
    sp = solar / total * 100 if total else 0
    gp = grid / total * 100 if total else 0
    share = f"{round(sp)} %" if total else "--"
    stats = [
        ("Solar share", share),
        ("Water delivered", f"{fmt(t.get('litres') or 0, 1)} L"),
        ("Zone 1 / Zone 2", f"{fmt(t.get('litresZ1') or 0, 1)} / {fmt(t.get('litresZ2') or 0, 1)} L"),
        ("Source changeovers", str(t.get("switches") or 0)),
        ("Faults caught", str(t.get("faults") or 0)),
        ("Grid cost avoided", f"₹{solar / 1000 * tariff:.2f}"),
    ]
    stats_html = "".join(f"<div><span>{a}</span><b>{b}</b></div>" for a, b in stats)
    return _one_line(f"""
<div class="hf"><div class="hf-panel"><p class="hf-h">Energy and water</p>
<p class="hf-sub">Metered from pump current at 230 V, PF 0.8, since the controller started</p>
<div class="hf-bar"><div style="width:{sp:.1f}%;background:{COL['solar']}"></div><div style="width:{gp:.1f}%;background:{COL['grid']}"></div></div>
<p class="hf-note" style="margin-top:6px">Solar <b class="hf-mono">{fmt(solar, 1)} Wh</b> &nbsp;·&nbsp; Grid <b class="hf-mono">{fmt(grid, 1)} Wh</b></p>
<div class="hf-stats">{stats_html}</div>
<p class="hf-note" style="margin-top:10px">Cost avoided is an estimate at ₹{tariff:.2f}/kWh of grid energy displaced by solar.</p></div></div>""")


# ------------------------------------------------------------------ events

def event_text(e: dict) -> str:
    z = zone_name(e.get("zone"))
    v = e.get("value") if isinstance(e.get("value"), (int, float)) else None
    d = e.get("detail")
    t = e.get("type")
    texts = {
        "BOOT": "Controller started",
        "SOLAR_AVAILABLE": f"Solar available ({fmt(v, 1)} V)",
        "SOLAR_LOST": f"Solar below {C.solar_on_v:g} V for {C.debounce_ms // 1000} s ({fmt(v, 1)} V)",
        "SOURCE_CHANGED": f"{z}: pump changed over to {d or 'the other source'}",
        "ZONE_START": f"{z} started at {fmt(v, 0)} % moisture",
        "ZONE_DONE": f"{z} reached the {C.moisture_target:g} % target",
        "ZONE_STOPPED": f"{z} stopped: {STOP_TEXT.get(d, d or 'condition changed')}",
        "FAULT_DRY_RUN": f"Dry run on {z or 'pump'}: {fmt(v, 2)} A. Pump stopped, valves closed",
        "FAULT_OVER_CURRENT": f"Over-current on {z or 'pump'}: {fmt(v, 1)} A. Pump stopped, valves closed",
        "FAULT_NO_FLOW": f"No flow on {z or 'pump'}: {fmt(v, 1)} L/min. Possible blockage or leak",
        "FAULT_CLEARED": "Fault reset by the operator",
        "TANK_FULL": f"Tank full ({fmt(v, 0)} %). Valves closed",
        "TANK_OK": f"Tank back to {fmt(v, 0)} %. Irrigation allowed",
        "TEMP_ALERT": f"Temperature {fmt(v, 1)} °C outside {C.temp_min_c:g}–{C.temp_max_c:g} °C. Irrigation paused",
        "TEMP_OK": f"Temperature back to {fmt(v, 1)} °C",
        "SENSOR_WARN": f"{z} soil probe reading invalid" if z else "Temperature sensor read failed",
        "MODE_HOLD": "Irrigation put on hold by the operator",
        "MODE_AUTO": "Automatic control resumed",
    }
    return texts.get(t, str(t))


def events_html(events: list[dict]) -> str:
    if not events:
        items = '<li>No events yet. They appear here as the controller switches sources, starts zones or trips.</li>'
    else:
        items = "".join(
            f'<li class="{esc(e.get("sev", "info"))}"><time>{time_of(e.get("ts"))}</time>'
            f'<span>{esc(event_text(e))}<small>{esc(e.get("type"))}</small></span></li>'
            for e in reversed(events[-80:]))
    return _one_line(f"""
<div class="hf"><div class="hf-panel"><p class="hf-h">Event log</p>
<p class="hf-sub">Switching, protection trips and alerts, newest first</p>
<ol class="hf-events">{items}</ol></div></div>""")


# ------------------------------------------------------------------ thresholds

def threshold_rows() -> list[dict]:
    rows = [
        ("Solar threshold", f"> {C.solar_on_v:g} V for {C.debounce_ms // 1000} s", "Select solar (priority 1)"),
        ("Soil critical", f"< {C.moisture_critical:g} %", "Grid allowed for that zone (priority 2)"),
        ("Soil solar start", f"< {C.moisture_solar_start:g} %", "Water the zone while solar is free (firmware addition)"),
        ("Soil target", f"{C.moisture_target:g} %", "Stop the zone, move to the next"),
        ("Tank overflow", f"≥ {C.tank_overflow_pct:g} %, resume < {C.tank_resume_pct:g} %", "Close valves, pump off"),
        ("Temperature range", f"{C.temp_min_c:g}–{C.temp_max_c:g} °C, {C.temp_hyst_c:g} °C hysteresis", "Alert and pause irrigation"),
        ("Dry run", f"< {C.dry_run_a:g} A for {C.dry_run_ms // 1000} s", "Pump off, valves closed, alarm (latched)"),
        ("Over-current", f"> {C.over_current_a:g} A after {C.inrush_ms // 1000} s inrush", "Pump off, valves closed, alarm (latched)"),
        ("No flow", f"< {C.no_flow_lpm:g} L/min for {C.no_flow_ms // 1000} s after {C.startup_delay_ms // 1000} s start-up",
         "Pump off, valves closed, alarm (latched)"),
        ("Changeover dead time", f"{C.dead_time_ms} ms each side", "Break-before-make source switch"),
        ("Valve sequencing", f"open {C.valve_open_ms / 1000:g} s before pump, close {C.valve_close_delay_ms / 1000:g} s after",
         "No dead-heading or water hammer"),
    ]
    return [{"Parameter": a, "Value": b, "Action": c} for a, b, c in rows]
