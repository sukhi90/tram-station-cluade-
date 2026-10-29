import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import logic

CYCLE = logic.STOP_S + logic.TRAVEL_S  # seconds per station (stop + travel)


class TestRequirements(unittest.TestCase):
    """The agreed rules of the assignment, written as plain numbers.
    If you change a rule on purpose (app/logic.py), update the number here too.
    Until you do, this test fails and deploy.sh refuses to deliver."""

    def test_line_and_timing(self):
        self.assertEqual(logic.STATIONS, 16)
        self.assertEqual(logic.STOP_S, 3)
        self.assertEqual(logic.TRAVEL_S, 5)

    def test_capacity(self):
        self.assertEqual(logic.CAPACITY, 12)


class TestLine(unittest.TestCase):
    """Behaviour that must hold for ANY number of stations or timing."""

    def test_next_station_wraps(self):
        self.assertEqual(logic.next_station(1), 2)
        self.assertEqual(logic.next_station(logic.STATIONS), 1)

    def test_full_loop_visits_all_stations_in_order(self):
        s, seen = 1, []
        for _ in range(logic.STATIONS):
            seen.append(s)
            s = logic.next_station(s)
        self.assertEqual(seen, list(range(1, logic.STATIONS + 1)))
        self.assertEqual(s, 1)

    def test_phase_durations(self):
        self.assertEqual(logic.phase_ms("STOPPED"), logic.STOP_S * 1000)
        self.assertEqual(logic.phase_ms("TRAVELING"), logic.TRAVEL_S * 1000)

    def test_capacity_is_positive(self):
        self.assertGreater(logic.CAPACITY, 0)


class TestEta(unittest.TestCase):
    def test_eta_when_stopped_at_target(self):
        self.assertEqual(logic.eta_seconds(5, 5, "STOPPED", 2), 0)

    def test_eta_next_station_while_stopped(self):
        self.assertEqual(logic.eta_seconds(6, 5, "STOPPED", 2), 2 + logic.TRAVEL_S)

    def test_eta_three_stations_ahead(self):
        self.assertEqual(logic.eta_seconds(8, 5, "STOPPED", 2), 2 + logic.TRAVEL_S + 2 * CYCLE)

    def test_eta_while_traveling(self):
        self.assertEqual(logic.eta_seconds(6, 5, "TRAVELING", 3), 3)
        self.assertEqual(logic.eta_seconds(7, 5, "TRAVELING", 3), 3 + CYCLE)

    def test_eta_full_loop(self):
        self.assertEqual(logic.eta_seconds(5, 5, "TRAVELING", 3), 3 + (logic.STATIONS - 1) * CYCLE)

    def test_wraparound(self):
        self.assertEqual(logic.eta_seconds(1, logic.STATIONS, "STOPPED", 1), 1 + logic.TRAVEL_S)


class TestPrivacy(unittest.TestCase):
    def test_anon_id_has_no_username(self):
        self.assertEqual(logic.anon_id("abcdef1234567890"), "P-ABCD")


class TestRoutesAndBoarding(unittest.TestCase):
    def test_route_simple(self):
        self.assertEqual(logic.route(2, 5), [2, 3, 4, 5])

    def test_route_wraps_around(self):
        n = logic.STATIONS
        self.assertEqual(logic.route(n - 1, 2), [n - 1, n, 1, 2])

    def test_route_rejects_unknown_station(self):
        with self.assertRaises(ValueError):
            logic.route(1, logic.STATIONS + 1)

    def test_route_length_is_never_more_than_one_loop(self):
        for a in range(1, logic.STATIONS + 1):
            for b in range(1, logic.STATIONS + 1):
                self.assertLessEqual(len(logic.route(a, b)), logic.STATIONS)

    def _rides(self, n):
        # list order is reversed on purpose: boarding must follow request time, not list order
        return [{"pk": "r%02d" % i, "created_ms": 1000 + i} for i in reversed(range(n))]

    def test_fifo_order(self):
        chosen = logic.select_boarders(self._rides(5), 3)
        self.assertEqual([r["pk"] for r in chosen], ["r00", "r01", "r02"])

    def test_capacity_limit(self):
        chosen = logic.select_boarders(self._rides(logic.CAPACITY + 2), logic.CAPACITY)
        self.assertEqual(len(chosen), logic.CAPACITY)
        self.assertEqual([r["pk"] for r in chosen], ["r%02d" % i for i in range(logic.CAPACITY)])

    def test_no_boarding_when_full(self):
        self.assertEqual(logic.select_boarders(self._rides(3), 0), [])
        self.assertEqual(logic.select_boarders(self._rides(3), -2), [])

    def test_same_millisecond_is_deterministic(self):
        rides = [{"pk": "b", "created_ms": 5}, {"pk": "a", "created_ms": 5}]
        self.assertEqual([r["pk"] for r in logic.select_boarders(rides, 2)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
