"""USB / Wokwi link: parses the firmware's real serial output and drives
SerialSource through a stand-in for pyserial (no board needed).

esp32_serial_sample.txt holds lines printed by the firmware's own JSON code
(tests/firmware/json_check.cpp), plus noise the parser must skip.
"""
import sys
import time
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "backend" / "emulator"))

import hf_view as view  # noqa: E402
import sources  # noqa: E402

LINES = (HERE / "esp32_serial_sample.txt").read_text().splitlines()


class FakePort:
    """Plays back the sample lines once a second, records what is written."""
    opened = []

    def __init__(self, url=None, **kw):
        self.port, self.dtr, self.rts, self.written = url, True, True, []
        self.queue = [line.encode() + b"\n" for line in LINES]

    def open(self):
        FakePort.opened.append(self)

    def readline(self):
        if self.queue:
            return self.queue.pop(0)
        time.sleep(0.05)
        return b""

    def write(self, data):
        self.written.append(data)

    def close(self):
        pass


def install_fake_serial():
    mod = types.ModuleType("serial")
    mod.Serial = FakePort

    def for_url(url, **kw):
        p = FakePort(url)
        FakePort.opened.append(p)
        return p
    mod.serial_for_url = for_url
    sys.modules["serial"] = mod


class ParserTests(unittest.TestCase):
    def test_parses_firmware_lines_and_skips_noise(self):
        parsed = [sources.parse_serial_line(line) for line in LINES]
        kinds = [p[0] for p in parsed if p]
        self.assertEqual(kinds, ["live", "event"])
        live = parsed[2][1]
        self.assertEqual(live["inputs"], "mixed")
        self.assertEqual(live["knobs"], ["solar", "current", "flow"])
        self.assertIsNone(live["sensors"]["soil"]["z2"])   # NaN from the ESP32 arrives as null

    def test_dashboard_renders_firmware_document(self):
        live = view.normalise(sources.parse_serial_line(LINES[2])[1])
        live["ts"] = int(time.time() * 1000)
        self.assertEqual(view.status_cards(live)[0]["word"], "SOLAR")
        self.assertIn("Knob · GPIO34", view.tiles_html(live))
        ev = sources.parse_serial_line(LINES[3])[1]
        self.assertIn("reached", view.event_text(ev))


class SerialSourceTests(unittest.TestCase):
    def setUp(self):
        install_fake_serial()
        FakePort.opened.clear()

    def wait_for(self, src, cond, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            src.poll()
            if cond():
                return
            time.sleep(0.05)
        self.fail(f"timed out; status {src.status}")

    def test_usb_port_reads_live_events_and_sends_commands(self):
        src = sources.SerialSource("COM5")
        try:
            self.wait_for(src, lambda: src.live is not None and len(src.events) == 1)
            port = FakePort.opened[0]
            self.assertFalse(port.dtr)   # must not hold the ESP32 in reset
            self.assertEqual(src.status["link"], "online")
            self.assertGreater(src.live["ts"], 1_700_000_000_000)   # stamped on arrival
            self.assertEqual(len(src.history), 1)
            src.command("RESET_FAULT")
            src.command("HOLD")
            src.relay_test()
            self.assertEqual(port.written, [b"r", b"h", b"t"])
        finally:
            src.close()

    def test_wokwi_url(self):
        src = sources.SerialSource("rfc2217://localhost:4000")
        try:
            self.wait_for(src, lambda: src.live is not None)
            self.assertEqual(FakePort.opened[0].port, "rfc2217://localhost:4000")
            self.assertEqual(src.status["note"], "Wokwi simulator")
        finally:
            src.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
