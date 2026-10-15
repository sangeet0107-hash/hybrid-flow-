"""Hybrid-Flow control room: Streamlit dashboard.

    cd frontend
    pip install -r requirements.txt
    streamlit run app.py

Data sources (sidebar):
  ESP32 over USB      the real board on the USB cable; no Wi-Fi needed
  Wokwi simulator     the same firmware running in Wokwi for VS Code
  Built-in simulator  the control logic in Python, no hardware at all
  Firebase            a device publishing to the Realtime Database
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "emulator"))

import hf_view as view  # noqa: E402
from hybridflow.controller import Config  # noqa: E402
from hybridflow.plant import TOUR, TourRunner  # noqa: E402
from sources import FirebaseSource, SerialSource, SimSource, list_serial_ports  # noqa: E402

C = Config()
COL = view.COL
TARIFF_RS_PER_KWH = 7.0

st.set_page_config(page_title="Hybrid-Flow Control Room", page_icon="💧", layout="wide")
st.markdown(view.CSS, unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("mode", "sim")
ss.setdefault("port", "")
ss.setdefault("db_url", "")
ss.setdefault("device", "hf-001")
ss.setdefault("auth", "")
ss.setdefault("tour", None)
ss.setdefault("tour_text", (f"{len(TOUR)} steps · about 6 minutes",
                            "Walks through the solar-to-grid changeover, all three pump trips, "
                            "a Wi-Fi outage, a heat alert and tank overflow."))
if "source" not in ss:
    ss.source = SimSource()


def send(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as exc:  # network or USB errors
        st.toast(f"Couldn't send: {exc}")


# ------------------------------------------------------------------ sidebar

WOKWI_URL = "rfc2217://localhost:4000"
MODES = {"serial": "ESP32 over USB", "wokwi": "Wokwi simulator", "sim": "Built-in simulator",
         "firebase": "Firebase"}


def switch(mode: str, source) -> None:
    old = ss.get("source")
    if hasattr(old, "close") and old is not source:
        old.close()
    ss.mode, ss.source, ss.tour = mode, source, None
    ss.pop("last_scenario", None)
    st.rerun()


with st.sidebar:
    st.subheader("Data source")
    labels = list(MODES.values())
    choice = st.radio("Show data from", labels, index=list(MODES).index(ss.mode), label_visibility="collapsed")
    picked = list(MODES)[labels.index(choice)]

    if picked == "serial":
        ports = list_serial_ports()
        if not ports:
            st.caption("No USB serial port found. Plug in the ESP32 (data cable), "
                       "and install the CH340 or CP210x driver if Windows doesn't see it.")
            if st.button("Look again"):
                st.rerun()
        else:
            names = [f"{dev} · {desc}" for dev, desc in ports]
            idx = next((i for i, (dev, _) in enumerate(ports) if dev == ss.port), 0)
            sel = st.selectbox("Port", names, index=idx)
            port = ports[names.index(sel)][0]
            if ss.mode != "serial" or port != ss.port:
                if st.button("Connect", type="primary"):
                    ss.port = port
                    switch("serial", SerialSource.get(port))
            else:
                st.caption("Close the Arduino Serial Monitor: only one program can use the port.")
                if st.button("Click each relay (wiring test)"):
                    send(ss.source.relay_test)
    elif picked == "wokwi":
        st.caption("Run the firmware in Wokwi for VS Code (README: Wokwi), then connect. "
                   "Turn the knobs in the Wokwi window.")
        if ss.mode != "wokwi" and st.button("Connect", type="primary"):
            switch("wokwi", SerialSource.get(WOKWI_URL))
    elif picked == "firebase":
        db = st.text_input("Realtime Database URL", value=ss.db_url,
                           placeholder="https://your-project-default-rtdb.firebaseio.com")
        device = st.text_input("Device ID", value=ss.device)
        auth = st.text_input("Auth token (optional)", value=ss.auth, type="password")
        if st.button("Connect", type="primary"):
            if not db.startswith("https://") or not (".firebaseio.com" in db or ".firebasedatabase.app" in db):
                st.error("Enter the Realtime Database URL from the Firebase console.")
            else:
                ss.db_url, ss.device, ss.auth = db.strip(), device.strip() or "hf-001", auth.strip()
                switch("firebase", FirebaseSource(ss.db_url, ss.device, ss.auth))
    elif ss.mode != "sim":
        switch("sim", SimSource())
    elif st.button("Restart simulator"):
        switch("sim", SimSource())

    if ss.mode in ("serial", "wokwi"):
        st.divider()
        st.subheader("Demo with the knobs")
        st.markdown(
            "- **Soil Zone 2** low → valve relay 3 clicks, pump relay 4 a second later\n"
            "- **Soil Zone 2** past 60 % → pump stops, then the valve\n"
            "- **Solar** below ¾ turn (18 V) with a zone below 30 % → after 5 s, relay 1 to grid\n"
            "- **Current** to zero while pumping → dry-run trip in 3 s, buzzer\n"
            "- **Current** fully up → over-current trip\n"
            "- **Flow** to zero → no-flow trip after about 10 s\n"
            "- **Tank** fully up → tank full, everything stops\n\n"
            "Before **Reset fault**, turn the knob back to normal, or it trips again.")

if ss.mode in ("sim", "firebase"):
  with st.sidebar:
    st.divider()
    st.subheader("Test scenarios")
    if ss.mode == "sim":
        st.caption("Inject conditions into the simulated farm and watch the controller respond.")
    else:
        st.caption("Sent through /sim to backend/emulator. A real or Wokwi ESP32 ignores these.")
    if st.button("Stop guided demo" if ss.tour else "Run guided demo", type="primary"):
        if ss.tour:
            ss.tour = None
            ss.tour_text = (f"{len(TOUR)} steps · about 6 minutes", "Guided demo stopped.")
        else:
            ss.tour = {"runner": TourRunner(), "started": time.monotonic()}
            ss.tour_text = (f"Step 1 of {len(TOUR)} · waiting", "Waiting for a zone to start watering…")
    cols = st.columns(2)
    for i, (sid, name, desc, expect) in enumerate(view.SCENARIOS):
        if cols[i % 2].button(name, key=f"scn-{sid}", help=desc):
            send(ss.source.scenario, sid)
            ss.last_scenario = (name, expect)
            st.toast(f"{name}: {expect}")

# ------------------------------------------------------------------ charts

def _times(points):
    return [datetime.fromtimestamp(p["t"] / 1000) for p in points]


def _layout(fig, y_title, y_range):
    fig.update_layout(
        height=260, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=COL["surface"], font=dict(family="IBM Plex Sans, sans-serif", size=12, color=COL["muted"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0), hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=COL["line"], tickformat="%H:%M:%S")
    fig.update_yaxes(gridcolor=COL["line"], title_text=y_title, range=y_range)
    return fig


def solar_chart(points):
    """Solar voltage, coloured by the source powering the pump at each moment."""
    fig = go.Figure()
    names = {"SOLAR": ("On solar", COL["solar"]), "GRID": ("On grid", COL["grid"]), "NONE": ("Pump off", COL["line_strong"])}
    xs = _times(points)
    for src, (label, color) in names.items():
        ys = []
        for i, p in enumerate(points):
            mine = p["source"] == src
            # include the boundary point so segments join up
            prev = i > 0 and points[i - 1]["source"] == src
            ys.append(p["solarV"] if mine or prev else None)
        if any(y is not None for y in ys):
            fig.add_trace(go.Scatter(x=xs, y=ys, name=label, mode="lines", line=dict(color=color, width=2.5),
                                     connectgaps=False))
    fig.add_hline(y=C.solar_on_v, line_dash="dash", line_color=COL["muted"],
                  annotation_text=f"{C.solar_on_v:g} V", annotation_position="top left")
    return _layout(fig, "V", [0, 25])


def soil_chart(points):
    fig = go.Figure()
    xs = _times(points)
    fig.add_trace(go.Scatter(x=xs, y=[p["z1"] for p in points], name="Zone 1", mode="lines",
                             line=dict(color=COL["water"], width=2.5)))
    fig.add_trace(go.Scatter(x=xs, y=[p["z2"] for p in points], name="Zone 2", mode="lines",
                             line=dict(color=COL["zone2"], width=2.5)))
    fig.add_hline(y=C.moisture_critical, line_dash="dash", line_color=COL["warn"],
                  annotation_text="critical", annotation_position="bottom left")
    fig.add_hline(y=C.moisture_target, line_dash="dash", line_color=COL["ok"],
                  annotation_text="target", annotation_position="top left")
    return _layout(fig, "% VWC", [0, 100])


def pump_chart(points):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    xs = _times(points)
    fig.add_trace(go.Scatter(x=xs, y=[p["pumpA"] for p in points], name="Current (A)", mode="lines",
                             line=dict(color=COL["ink"], width=2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=xs, y=[p["flowLpm"] for p in points], name="Flow (L/min)", mode="lines",
                             line=dict(color=COL["water"], width=2)), secondary_y=True)
    _layout(fig, "A", [0, 14])
    fig.update_yaxes(title_text="L/min", range=[0, 20], secondary_y=True, showgrid=False)
    return fig


# ------------------------------------------------------------------ live view

def advance_tour(live) -> None:
    tour = ss.tour
    if not tour or not live:
        return
    step = tour["runner"].poll(time.monotonic() - tour["started"], live["state"]["phase"])
    if not step:
        return
    idx = tour["runner"].index
    ss.tour_text = (f"Step {idx} of {len(TOUR)} · {step['action'].replace('_', ' ').lower()}", step["note"])
    if step["action"] == "RESET_FAULT":
        send(ss.source.command, "RESET_FAULT")
    else:
        send(ss.source.scenario, step["action"])
    if tour["runner"].done:
        ss.tour = None


@st.fragment(run_every=1.0)
def live_view() -> None:
    src = ss.source
    src.poll()
    raw = src.live
    device = {"sim": "hf-sim", "serial": "hf-001"}.get(src.kind, ss.device)
    st.markdown(view.header_html(src.status, raw, device), unsafe_allow_html=True)

    if not raw:
        st.info(src.status.get("note", "Waiting for data"))
        return
    live = view.normalise(raw)
    advance_tour(live)
    state = live["state"]

    active = [view.SCENARIO_NAMES.get(a, a) for a in live.get("simActive") or []]
    last = ss.get("last_scenario")
    if active or last:
        lines = []
        if active:
            lines.append(f"<b>Test conditions active:</b> {view.esc(', '.join(active))}")
        if last:
            lines.append(f"<b>Last injected · {view.esc(last[0])}:</b> {view.esc(last[1])}")
        st.markdown('<div class="hf"><div class="hf-tour" style="background:#f8e6d6;margin-bottom:8px">'
                    + "<br>".join(lines) + "</div></div>", unsafe_allow_html=True)

    if ss.mode in ("sim", "firebase") and (ss.tour or ss.tour_text[1] != ""):
        step, note = ss.tour_text
        st.markdown(f'<div class="hf"><div class="hf-tour"><b>Guided demo · {view.esc(step)}</b><br>'
                    f'{view.esc(note)}</div></div>', unsafe_allow_html=True)

    # Summary cards with operator controls under them
    cards = view.status_cards(live)
    cols = st.columns(4)
    for col, card in zip(cols, cards):
        col.markdown(view.card_html(card), unsafe_allow_html=True)
    with cols[2]:
        if state["fault"] != "NONE" and st.button("Reset fault", type="primary", key="reset"):
            send(src.command, "RESET_FAULT")
    with cols[3]:
        b1, b2 = st.columns(2)
        if b1.button("Hold", key="hold", disabled=state["mode"] == "HOLD", help="Stop irrigation and keep it stopped"):
            send(src.command, "HOLD")
        if b2.button("Auto", key="auto", disabled=state["mode"] == "AUTO", help="Resume automatic control"):
            send(src.command, "AUTO")

    st.markdown(view.diagram_html(live), unsafe_allow_html=True)

    st.markdown('<div class="hf"><p class="hf-h" style="margin-top:8px">Sensors</p>'
                '<p class="hf-sub">Seven sensors, eight readings. Marks on each scale are the control thresholds.</p></div>',
                unsafe_allow_html=True)
    st.markdown(view.tiles_html(live), unsafe_allow_html=True)

    points = [p for p in src.history if p.get("t")]
    st.markdown('<div class="hf"><p class="hf-h" style="margin-top:8px">Trends</p>'
                '<p class="hf-sub">Last few minutes. Solar line colour shows the source powering the pump.</p></div>',
                unsafe_allow_html=True)
    if len(points) >= 2:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.caption("Solar voltage")
            st.plotly_chart(solar_chart(points), key="chart-solar", config={"displayModeBar": False})
        with c2:
            st.caption("Soil moisture")
            st.plotly_chart(soil_chart(points), key="chart-soil", config={"displayModeBar": False})
        with c3:
            st.caption("Pump current and flow")
            st.plotly_chart(pump_chart(points), key="chart-pump", config={"displayModeBar": False})
    else:
        st.caption("Collecting data for the charts…")

    e1, e2 = st.columns(2)
    e1.markdown(view.energy_html(live, TARIFF_RS_PER_KWH), unsafe_allow_html=True)
    e2.markdown(view.events_html(list(src.events)), unsafe_allow_html=True)

    up = live.get("uptimeS") or 0
    st.caption(f"Firmware {live.get('fw', '--')} · up {up // 60} min · last update {view.time_of(live.get('ts'))}")


live_view()

with st.expander("Control thresholds (Project Review 1, section VII-C)"):
    st.dataframe(pd.DataFrame(view.threshold_rows()), hide_index=True)
st.caption("BITE401P Embedded Systems and IoT · Project Review 1")
