"""Checks the dashboard's view logic and simulator without starting Streamlit.

    cd frontend
    python -m unittest discover -s tests -v
"""
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "backend" / "emulator"))

import hf_view as view  # noqa: E402
from sources import SimSource  # noqa: E402


def run_for(src, seconds):
    """Advance a SimSource by `seconds` of simulated time without waiting."""
    src.t0 -= seconds
    src.poll()


class SimSourceTests(unittest.TestCase):
    def test_produces_live_document_and_history(self):
        src = SimSource()
        run_for(src, 5)
        self.assertIsNotNone(src.live)
        self.assertEqual(src.live["state"]["source"], "SOLAR")
        self.assertEqual(src.live["state"]["zone"], 2)       # zone 2 starts driest
        self.assertGreaterEqual(len(src.history), 4)
        self.assertIn("ZONE_START", [e["type"] for e in src.events])

    def test_cloud_switches_critical_zone_to_grid(self):
        src = SimSource()
        run_for(src, 4)
        src.scenario("CLOUD")
        run_for(src, 7)
        self.assertEqual(src.live["state"]["source"], "GRID")
        self.assertIn("SOURCE_CHANGED", [e["type"] for e in src.events])

    def test_jam_trips_and_reset_clears(self):
        src = SimSource()
        run_for(src, 4)
        src.scenario("JAM")
        run_for(src, 2)
        self.assertEqual(src.live["state"]["fault"], "OVER_CURRENT")
        src.command("RESET_FAULT")
        run_for(src, 2)
        self.assertEqual(src.live["state"]["fault"], "NONE")

    def test_wifi_drop_buffers_then_uploads(self):
        src = SimSource()
        run_for(src, 3)
        src.scenario("WIFI_DROP")
        run_for(src, 10)
        self.assertEqual(src.status["link"], "offline")
        self.assertGreater(src.status["buffered"], 0)
        before = len(src.history)
        run_for(src, 40)
        self.assertEqual(src.status["link"], "sim")
        self.assertGreater(len(src.history), before)


class ScenarioWhilePumpIdleTests(unittest.TestCase):
    """Every scenario button must have a visible effect even if nothing is running."""

    def idle_source(self):
        src = SimSource()
        src.plant.moisture = [58.0, 58.0]          # wet soil: controller stays idle
        run_for(src, 3)
        self.assertFalse(src.live["state"]["pump"])
        return src

    def test_pump_faults_trip_from_idle(self):
        for scenario, fault, wait in (("JAM", "OVER_CURRENT", 4), ("DRY_TANK", "DRY_RUN", 8),
                                      ("BLOCKAGE", "NO_FLOW", 14)):
            src = self.idle_source()
            src.scenario(scenario)
            run_for(src, wait)
            self.assertEqual(src.live["state"]["fault"], fault, scenario)

    def test_cloud_from_idle_shows_grid_changeover(self):
        src = self.idle_source()
        src.scenario("CLOUD")
        run_for(src, 9)
        self.assertEqual(src.live["state"]["source"], "GRID")

    def test_tank_overfill_closes_valves_at_once(self):
        src = self.idle_source()
        src.scenario("TANK_FULL")
        run_for(src, 1.5)
        self.assertTrue(src.live["state"]["tankFull"])


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.src = SimSource()
        run_for(self.src, 5)
        self.live = view.normalise(self.src.live)

    def test_cards_and_html_render(self):
        cards = view.status_cards(self.live)
        self.assertEqual([c["title"] for c in cards], ["Power source", "Irrigation", "Protection", "Operator control"])
        self.assertEqual(cards[0]["word"], "SOLAR")
        for chunk in (view.diagram_html(self.live), view.tiles_html(self.live),
                      view.energy_html(self.live, 7.0), view.events_html(list(self.src.events)),
                      view.header_html(self.src.status, self.live, "hf-sim")):
            self.assertNotIn("\n", chunk)               # indented lines would become code blocks
        self.assertEqual(len(view.tiles(self.live)), 8)

    def test_every_event_type_has_text(self):
        for t in ["BOOT", "SOLAR_AVAILABLE", "SOLAR_LOST", "SOURCE_CHANGED", "ZONE_START", "ZONE_DONE",
                  "ZONE_STOPPED", "FAULT_DRY_RUN", "FAULT_OVER_CURRENT", "FAULT_NO_FLOW", "FAULT_CLEARED",
                  "TANK_FULL", "TANK_OK", "TEMP_ALERT", "TEMP_OK", "SENSOR_WARN", "MODE_HOLD", "MODE_AUTO"]:
            self.assertNotEqual(view.event_text({"type": t, "zone": 1, "value": 1.0}), t)

    def test_bench_build_labels_knobs(self):
        live = dict(self.live, inputs="knobs")
        tags = [t["tag"] for t in view.tiles(live)]
        self.assertIn("Knob · GPIO34", tags)
        self.assertIn("Knob · GPIO32", tags)
        self.assertIn("Bench build", view.header_html({"link": "online", "note": "Reading from Firebase"}, live, "hf-001"))

    def test_sparse_firebase_document(self):
        live = view.normalise({"ts": int(time.time() * 1000), "sensors": {"solarV": 12.0},
                               "state": {"fault": "NO_FLOW"}})
        cards = view.status_cards(live)
        self.assertEqual(cards[2]["word"], "No flow")
        view.diagram_html(live)
        view.tiles_html(live)


if __name__ == "__main__":
    unittest.main(verbosity=2)
