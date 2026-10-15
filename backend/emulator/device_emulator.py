#!/usr/bin/env python3
"""Hybrid-Flow device emulator.

Pretends to be the ESP32: runs the same control logic against a simulated farm
and talks to Firebase exactly like the firmware does (PUT /live, POST
/telemetry and /events, poll /command). Use it to demonstrate the full
cloud pipeline and the dashboard before the hardware is wired up.

Only the Python standard library is needed.

    python device_emulator.py                         # console only, no cloud
    python device_emulator.py --db https://<project>-default-rtdb.<region>.firebasedatabase.app
    python device_emulator.py --db <url> --reset --tour
"""
from __future__ import annotations

import argparse
import collections
import sys
import threading
import time
import urllib.error

from hybridflow.controller import Controller
from hybridflow.firebase import Firebase
from hybridflow.payloads import event_payload, live_payload, telemetry_payload
from hybridflow.plant import SCENARIOS, Plant, TourRunner

SUPPLY_VRMS = 230.0
POWER_FACTOR = 0.8


# ---------------------------------------------------------------- Firebase REST

class Uplink(threading.Thread):
    """Background uploader, like the firmware's cloud task on core 0."""

    def __init__(self, fb: Firebase):
        super().__init__(daemon=True)
        self.fb = fb
        self.lock = threading.Lock()
        self.pending: collections.deque = collections.deque(maxlen=400)  # (path, body)
        self.live = None
        self.radio_off = False          # simulated Wi-Fi outage
        self.online = False
        self.commands: list[str] = []
        self.scenarios: list[str] = []
        self.last_error = ""
        self._cmd_seq = None
        self._sim_seq = None

    def post(self, path: str, body: dict) -> None:
        with self.lock:
            self.pending.append((path, body))

    def put_live(self, body: dict) -> None:
        with self.lock:
            self.live = body

    def buffered(self) -> int:
        with self.lock:
            return len(self.pending)

    def take(self):
        with self.lock:
            cmds, scen = self.commands, self.scenarios
            self.commands, self.scenarios = [], []
        return cmds, scen

    def _poll(self, path: str, attr: str, key: str, sink: list):
        data = self.fb.request("GET", path)
        seq = data.get("seq") if isinstance(data, dict) else None
        last = getattr(self, attr)
        if last is None:                    # first read: remember, don't replay
            setattr(self, attr, seq or 0)
            return
        if seq and seq > last:
            setattr(self, attr, seq)
            value = data.get(key)
            if value:
                with self.lock:
                    sink.append(value)

    def run(self):
        last_poll = 0.0
        while True:
            if self.radio_off:
                self.online = False
                time.sleep(0.25)
                continue
            try:
                for _ in range(10):
                    with self.lock:
                        item = self.pending[0] if self.pending else None
                    if item is None:
                        break
                    self.fb.request("POST", item[0], item[1])
                    with self.lock:
                        self.pending.popleft()
                with self.lock:
                    live, self.live = self.live, None
                if live is not None:
                    live["net"]["buffered"] = self.buffered()
                    self.fb.request("PUT", "live", live)
                if time.monotonic() - last_poll > 2:
                    last_poll = time.monotonic()
                    self._poll("command", "_cmd_seq", "action", self.commands)
                    self._poll("sim", "_sim_seq", "scenario", self.scenarios)
                self.online = True
                self.last_error = ""
                time.sleep(0.2)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self.online = False
                self.last_error = str(exc)
                time.sleep(3)


# ---------------------------------------------------------------- main loop

def main() -> int:
    ap = argparse.ArgumentParser(description="Hybrid-Flow ESP32 emulator")
    ap.add_argument("--db", help="Firebase Realtime Database URL (omit to run console-only)")
    ap.add_argument("--auth", help="database secret or ID token, if your rules need one")
    ap.add_argument("--device", default="hf-001", help="device id (default hf-001)")
    ap.add_argument("--speed", type=float, default=0.2, help="simulated minutes per real second (default 0.2)")
    ap.add_argument("--start-hour", type=float, default=10.5, help="simulated time of day to start at")
    ap.add_argument("--telemetry-period", type=float, default=5.0, help="seconds between telemetry samples")
    ap.add_argument("--reset", action="store_true", help="delete this device's data in Firebase first")
    ap.add_argument("--tour", action="store_true", help="trigger the demo scenarios automatically")
    ap.add_argument("--duration", type=float, default=0, help="stop after this many seconds (0 = run forever)")
    ap.add_argument("--quiet", action="store_true", help="only print events")
    args = ap.parse_args()

    plant = Plant(start_hour=args.start_hour, sim_minutes_per_second=args.speed)
    ctl = Controller()
    t0 = time.monotonic()
    ctl.begin(0)

    uplink = None
    if args.db:
        fb = Firebase(args.db, args.device, args.auth)
        try:
            if args.reset:
                fb.request("DELETE", "")
                print(f"Cleared /devices/{args.device}")
            fb.request("GET", "command")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"Can't reach Firebase at {args.db}: {exc}", file=sys.stderr)
            print("Check the URL and that the database rules are published (see README).", file=sys.stderr)
            return 1
        uplink = Uplink(fb)
        uplink.start()
        print(f"Publishing as {args.device} to {args.db}")
    else:
        print("Console-only mode. Pass --db <url> to publish to Firebase.")
    print("Scenarios can be triggered from the dashboard, or with --tour. Ctrl+C to stop.\n")

    tour = TourRunner() if args.tour else None
    last_live = last_tel = last_print = -99.0
    tick = 0.1
    next_t = time.monotonic()

    try:
        while True:
            next_t += tick
            elapsed = time.monotonic() - t0
            now_ms = int(elapsed * 1000)
            if args.duration and elapsed >= args.duration:
                break

            # Operator commands and demo scenarios
            cmds, scenarios = uplink.take() if uplink else ([], [])
            step = tour.poll(elapsed, ctl.phase) if tour else None
            if step:
                print(f"\n  >> {step['note']}")
                (cmds if step["action"] == "RESET_FAULT" else scenarios).append(step["action"])
            for cmd in cmds:
                if cmd == "RESET_FAULT":
                    plant.fault_reset()
                ctl.command(cmd, now_ms)
                print(f"  command  {cmd}")
            for name in scenarios:
                if name in SCENARIOS:
                    plant.trigger(name)
                    print(f"  scenario {name}")

            inp = plant.step(tick, ctl.out)
            ctl.update(now_ms, inp)
            ctl.meter(now_ms, SUPPLY_VRMS, POWER_FACTOR)

            if uplink:
                uplink.radio_off = plant.wifi_down
            for e in ctl.pop_events():
                zone = f" zone {e['zone'] + 1}" if e["zone"] >= 0 else ""
                detail = f" ({e['detail']})" if e.get("detail") else ""
                print(f"  EVENT {e['type']}{zone}{detail}")
                if uplink:
                    uplink.post("events", event_payload(e))

            if uplink and elapsed - last_live >= 2:
                last_live = elapsed
                rssi = -58 - int(plant.rng.random() * 8)
                uplink.put_live(live_payload(ctl, plant, inp, int(elapsed), rssi))
            if uplink and elapsed - last_tel >= args.telemetry_period:
                last_tel = elapsed
                uplink.post("telemetry", telemetry_payload(ctl, inp))

            if not args.quiet and elapsed - last_print >= 1:
                last_print = elapsed
                link = ""
                if uplink:
                    link = "online" if uplink.online else ("wifi down" if plant.wifi_down else "offline")
                    link += f" buf={uplink.buffered()}"
                print(f"{plant.clock_text()} {ctl.phase:<13} src={ctl.source:<5} zone={ctl.zone + 1} "
                      f"pump={'ON ' if ctl.out.pump_on else 'off'} | solar {inp.solar_v:5.1f} V  "
                      f"soil {inp.moisture[0]:4.1f}/{inp.moisture[1]:4.1f} %  tank {inp.tank_pct:4.1f} %  "
                      f"{inp.temp_c:4.1f} C  {inp.pump_a:4.1f} A  {inp.flow_lpm:4.1f} L/min | "
                      f"fault {ctl.fault} {link}")

            time.sleep(max(0.0, next_t - time.monotonic()))
    except KeyboardInterrupt:
        pass

    t = ctl.totals
    total = t.solar_wh + t.grid_wh
    share = 100 * t.solar_wh / total if total else 0
    print(f"\nSolar {t.solar_wh:.1f} Wh, grid {t.grid_wh:.1f} Wh ({share:.0f}% solar), "
          f"{t.litres:.1f} L delivered, {t.switches} changeovers, {t.faults} faults")
    return 0


if __name__ == "__main__":
    sys.exit(main())
