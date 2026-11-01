"""statewatch.py: chronyd nicht erreichbar ist kein Quellenwechsel (Review 2/6)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import statewatch  # noqa: E402


def ok(selected="A", mode=3):
    return {"stratum": 2, "offset": 1e-6,
            "sources": {"A": {"s": "*" if selected == "A" else "+"},
                        "B": {"s": "*" if selected == "B" else "-"}},
            "gps": {"mode": mode, "used": 8}}


def down(mode=3):
    """Messpunkt bei gescheitertem chronyc: keine Quellen, keine tracking-Werte."""
    return {"stratum": None, "offset": None, "sources": {}, "clients": 0,
            "gps": {"mode": mode, "used": 8}}


class StateWatchChronydTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.watch = statewatch.StateWatcher(lambda *a, **k: self.events.append(a))

    def feed(self, *samples):
        for s in samples:
            self.watch.sample(s)

    def kinds(self):
        return [(e[0], e[1], e[2]) for e in self.events]

    def test_chronyc_failure_is_no_source_change(self):
        self.feed(ok(), ok(), down(), down(), down(), ok(), ok())
        self.assertNotIn("source", [e[0] for e in self.events])
        self.assertEqual(self.kinds(), [("service", "warn", "chronyd nicht erreichbar"),
                                        ("service", "info", "chronyd wieder erreichbar")])

    def test_alternating_failures_no_flood(self):
        """Wie im Review: abwechselnd gute und leere Messpunkte – keine Ereignisflut."""
        self.feed(ok(), ok())
        for _ in range(10):
            self.feed(down(), ok())
        self.assertEqual(self.events, [])

    def test_unreachable_only_on_transition(self):
        self.feed(ok(), ok(), *[down() for _ in range(10)])
        self.assertEqual(self.kinds(), [("service", "warn", "chronyd nicht erreichbar")])

    def test_start_while_unreachable_is_no_event(self):
        self.feed(down(), down(), down())
        self.assertEqual(self.events, [])

    def test_source_change_across_outage(self):
        self.feed(ok("A"), ok("A"), down(), down(), ok("B"), ok("B"))
        self.assertIn(("source", "info", "Zeitquelle gewechselt: A → B"), self.kinds())

    def test_reachable_without_sources_is_unknown(self):
        """chronyd antwortet (tracking), meldet aber gerade keine Quellen: kein Ereignis."""
        empty = {"stratum": 16, "offset": 0.0, "sources": {}}
        self.feed(ok(), ok(), empty, empty, empty)
        self.assertEqual(self.events, [])

    def test_no_selected_source_still_reported(self):
        unselected = {"stratum": 16, "offset": 0.0, "sources": {"A": {"s": "?"}, "B": {"s": "?"}}}
        self.feed(ok(), ok(), unselected, unselected)
        self.assertEqual(self.kinds(), [("source", "warn", "Keine Zeitquelle mehr ausgewählt")])

    def test_gps_tracked_while_chronyd_down(self):
        self.feed(ok(mode=3), ok(mode=3), down(mode=1), down(mode=1))
        self.assertIn(("gps", "warn", "GPS-Fix verloren"), self.kinds())


if __name__ == "__main__":
    unittest.main()
