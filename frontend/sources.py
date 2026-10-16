"""Data sources for the Streamlit dashboard.

SimSource      runs the firmware's control logic (Python port) against the farm
               model inside the Streamlit process. No hardware or cloud needed.
FirebaseSource reads what the ESP32, the Wokwi simulation or the device
               emulator publishes to the Realtime Database, and writes
               operator commands back.

Both expose the same attributes after poll():
    live     the /live document (or None)
    history  list of {t, solarV, z1, z2, pumpA, flowLpm, source}
    events   list of {ts, type, sev, zone, value, detail}
    status   {link, note, buffered}
"""
from __future__ import annotations

import time
import urllib.error
from collections import deque

from hybridflow.controller import Controller
from hybridflow.firebase import Firebase
from hybridflow.payloads import event_payload, live_payload
from hybridflow.plant import Plant

TICK = 0.1
MAX_CATCH_UP_S = 60      # if the page was hidden, don't replay more than this
HISTORY_S = 6 * 60


def _point(live: dict) -> dict:
    se, st = live["sensors"], live["state"]
    soil = se.get("soil") or {}
    return {"t": live["ts"], "solarV": se.get("solarV"), "z1": soil.get("z1"), "z2": soil.get("z2"),
            "pumpA": se.get("pumpA"), "flowLpm": se.get("flowLpm"), "source": st.get("source", "NONE")}


class SimSource:
    kind = "sim"

    def __init__(self):
        self.plant = Plant(start_hour=10.5, sim_minutes_per_second=0.2)
        self.ctl = Controller()
        self.ctl.begin(0)
        self.t0 = time.monotonic()
        self.wall0 = time.time() * 1000
        self.sim_t = 0.0
        self.inp = None
        self.live = None
        self.history: deque = deque(maxlen=int(HISTORY_S))
        self.events: deque = deque(maxlen=80)
        self.status = {"link": "sim", "note": "Simulated device running inside the dashboard"}
        self._cmds: list[str] = []
        self._scenarios: list[str] = []
        self._held_events: list[dict] = []
        self._held_points: list[dict] = []
        self._last_point = -99.0

    def command(self, action: str) -> None:
        self._cmds.append(action)

    def scenario(self, name: str) -> None:
        self._scenarios.append(name)

    def poll(self) -> None:
        target = time.monotonic() - self.t0
        if target - self.sim_t > MAX_CATCH_UP_S:
            self.sim_t = target - MAX_CATCH_UP_S
        while self.sim_t + TICK <= target:
            self._step()

    def _step(self) -> None:
        self.sim_t += TICK
        now_ms = int(self.sim_t * 1000)
        wall = int(self.wall0 + now_ms)
        for c in self._cmds:
            if c == "RESET_FAULT":
                self.plant.fault_reset()
            self.ctl.command(c, now_ms)
        for s in self._scenarios:
            self.plant.trigger(s)
        self._cmds, self._scenarios = [], []

        self.inp = self.plant.step(TICK, self.ctl.out)
        self.ctl.update(now_ms, self.inp)
        self.ctl.meter(now_ms, 230, 0.8)

        new_events = []
        for e in self.ctl.pop_events():
            ev = event_payload(e)
            ev["ts"] = wall
            new_events.append(ev)
        snapshot = None
        if self.sim_t - self._last_point >= 1.0:
            self._last_point = self.sim_t
            snapshot = live_payload(self.ctl, self.plant, self.inp, int(self.sim_t), fw="streamlit-sim")
            snapshot["ts"] = wall

        if self.plant.wifi_down:
            # The device keeps controlling; the uplink holds data until Wi-Fi returns.
            self._held_events += new_events
            if snapshot:
                self._held_points.append(_point(snapshot))
            self.status = {"link": "offline", "buffered": len(self._held_events) + len(self._held_points),
                           "note": "Device Wi-Fi down: control continues locally, data is buffered"}
            return
        if self._held_events or self._held_points:
            self.events.extend(self._held_events)
            self.history.extend(self._held_points)
            self._held_events, self._held_points = [], []
            self.status = {"link": "sim", "note": "Reconnected: buffered data uploaded"}
        elif self.status.get("link") != "sim":
            self.status = {"link": "sim", "note": "Simulated device running inside the dashboard"}
        self.events.extend(new_events)
        if snapshot:
            self.live = snapshot
            self.history.append(_point(snapshot))


class FirebaseSource:
    kind = "firebase"

    def __init__(self, db_url: str, device: str, auth: str = ""):
        self.fb = Firebase(db_url, device, auth or None, timeout=5)
        self.live = None
        self.history: list[dict] = []
        self.events: list[dict] = []
        self.status = {"link": "stale", "note": "Connecting to Firebase…"}
        self._last_history = 0.0
        self._was_stale = True

    def command(self, action: str) -> None:
        self.fb.request("PUT", "command", {"seq": int(time.time() * 1000), "action": action,
                                           "ts": {".sv": "timestamp"}})

    def scenario(self, name: str) -> None:
        self.fb.request("PUT", "sim", {"seq": int(time.time() * 1000), "scenario": name})

    def poll(self) -> None:
        try:
            live = self.fb.request("GET", "live")
            if isinstance(live, dict) and live.get("sensors") and live.get("state"):
                self.live = live
            self.events = self.fb.latest("events", 60)
            stale = not self.live or not isinstance(self.live.get("ts"), (int, float)) \
                or time.time() * 1000 - self.live["ts"] > 8000
            if time.monotonic() - self._last_history > 5 or (self._was_stale and not stale):
                self._last_history = time.monotonic()
                pts = [{"t": d.get("ts"), "solarV": d.get("solarV"), "z1": d.get("z1"), "z2": d.get("z2"),
                        "pumpA": d.get("pumpA"), "flowLpm": d.get("flowLpm"), "source": d.get("source", "NONE")}
                       for d in self.fb.latest("telemetry", 150)]
                self.history = [p for p in pts if p["t"]]
            if self.live and not stale:
                p = _point(self.live)
                if not self.history or p["t"] > self.history[-1]["t"]:
                    self.history.append(p)
            self.history = self.history[-400:]
            self._was_stale = stale
            if not self.live:
                self.status = {"link": "stale", "note": "Connected. Waiting for the device to publish…"}
            elif stale:
                age = (time.time() * 1000 - self.live["ts"]) / 1000
                self.status = {"link": "offline", "note": f"No update from the device for {age:.0f} s"}
            else:
                self.status = {"link": "online", "buffered": (self.live.get("net") or {}).get("buffered"),
                               "note": "Reading from Firebase"}
        except urllib.error.HTTPError as exc:
            self.status = {"link": "error", "note": f"Firebase answered {exc.code}: check the database rules and auth token"}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.status = {"link": "error", "note": f"Can't reach Firebase: {exc}"}


# ---------------------------------------------------------------- USB serial

def parse_serial_line(line: str):
    """Returns ("live", doc), ("event", doc) or None for one line from the ESP32."""
    import json
    line = line.strip()
    for prefix, kind in (("@LIVE ", "live"), ("@EVT ", "event")):
        if line.startswith(prefix):
            try:
                doc = json.loads(line[len(prefix):])
            except ValueError:
                return None
            return (kind, doc) if isinstance(doc, dict) else None
    return None


def list_serial_ports() -> list[tuple[str, str]]:
    """(device, description) for each serial port, likely ESP32 ports first."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = [(p.device, p.description or p.device) for p in list_ports.comports()]
    hints = ("CH340", "CP210", "USB", "UART", "Silicon Labs", "wch")
    return sorted(ports, key=lambda p: not any(h.lower() in p[1].lower() for h in hints))


class SerialSource:
    """Reads the ESP32 directly over the USB cable. No Wi-Fi or Firebase needed.

    The firmware prints "@LIVE {json}" every second and "@EVT {json}" for each
    event; commands go back as single characters (h, a, r).
    """
    kind = "serial"
    _open_sources: dict = {}

    @classmethod
    def get(cls, port: str) -> "SerialSource":
        """One reader per port, shared by every browser tab (a port can only be opened once)."""
        src = cls._open_sources.get(port)
        if src is None or src._stop:
            src = cls._open_sources[port] = cls(port)
        return src

    def __init__(self, port: str, baud: int = 115200):
        import threading
        self.port = port
        self.baud = baud
        self.live = None
        self.history: deque = deque(maxlen=int(HISTORY_S))
        self.events: deque = deque(maxlen=80)
        self.status = {"link": "stale", "note": f"Opening {port}…"}
        self._ser = None
        self._lock = threading.Lock()
        self._last_rx = 0.0
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open(self):
        import serial
        if "://" in self.port:   # e.g. rfc2217://localhost:4000 from the Wokwi simulator
            return serial.serial_for_url(self.port, baudrate=self.baud, timeout=0.5)
        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = self.port, self.baud, 0.5
        ser.dtr = False   # don't hold the ESP32 in reset
        ser.rts = False
        ser.open()
        return ser

    def _run(self):
        while not self._stop:
            if self._ser is None:
                try:
                    self._ser = self._open()
                    self.status = {"link": "stale", "note": f"Connected to {self.port}. Waiting for the ESP32…"}
                except Exception as exc:  # port busy or unplugged
                    busy = "denied" in str(exc).lower() or "busy" in str(exc).lower()
                    if "://" in self.port:
                        note = "Can't reach the Wokwi simulator: start it in VS Code first (see README)"
                    elif busy:
                        note = f"{self.port} is in use: close the Arduino Serial Monitor"
                    else:
                        note = f"Can't open {self.port}: check the USB cable"
                    self.status = {"link": "error", "note": note}
                    time.sleep(2)
                    continue
            try:
                raw = self._ser.readline()
            except Exception:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
                self.status = {"link": "error", "note": "USB cable unplugged. Plug it back in; it reconnects by itself."}
                continue
            if not raw:
                continue
            parsed = parse_serial_line(raw.decode("utf-8", "replace"))
            if not parsed:
                continue
            kind, doc = parsed
            now_ms = int(time.time() * 1000)
            doc["ts"] = now_ms   # the ESP32 has no clock without Wi-Fi; stamp on arrival
            with self._lock:
                self._last_rx = time.monotonic()
                if kind == "live" and doc.get("sensors") and doc.get("state"):
                    self.live = doc
                    self.history.append(_point(doc))
                elif kind == "event":
                    self.events.append(doc)

    def poll(self) -> None:
        with self._lock:
            age = time.monotonic() - self._last_rx if self._last_rx else None
        if self.status.get("link") == "error" and (age is None or age > 3):
            return
        if age is None:
            return
        if age > 4:
            self.status = {"link": "offline", "note": f"No data from the ESP32 for {age:.0f} s. Is it running the Hybrid-Flow firmware?"}
        else:
            where = "Wokwi simulator" if "://" in self.port else f"ESP32 over USB ({self.port})"
            self.status = {"link": "online", "note": where}

    def _send(self, ch: str) -> None:
        if self._ser is None:
            raise RuntimeError("ESP32 not connected")
        self._ser.write(ch.encode())

    def command(self, action: str) -> None:
        self._send({"HOLD": "h", "AUTO": "a", "RESET_FAULT": "r"}[action])

    def relay_test(self) -> None:
        self._send("t")

    def scenario(self, name: str) -> None:
        raise RuntimeError("On the real board, turn the knobs instead")

    def close(self) -> None:
        self._stop = True
        if SerialSource._open_sources.get(self.port) is self:
            del SerialSource._open_sources[self.port]
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
