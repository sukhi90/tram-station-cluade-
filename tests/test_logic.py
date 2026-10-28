import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import logic


class TestLine(unittest.TestCase):
    """Driving and simulation rules (Milestone 1)."""

    def test_line_constants(self):
        self.assertEqual(logic.STATIONS, 16)
        self.assertEqual(logic.STOP_S, 3)
        self.assertEqual(logic.TRAVEL_S, 5)

    def test_next_station_wraps(self):
        self.assertEqual(logic.next_station(1), 2)
        self.assertEqual(logic.next_station(16), 1)

    def test_full_loop_visits_all_stations_in_order(self):
        s, seen = 1, []
        for _ in range(16):
            seen.append(s)
            s = logic.next_station(s)
        self.assertEqual(seen, list(range(1, 17)))
        self.assertEqual(s, 1)

    def test_cycle_length(self):
        self.assertEqual(logic.STATIONS * (logic.STOP_S + logic.TRAVEL_S), 128)

    def test_phase_durations(self):
        self.assertEqual(logic.phase_ms("STOPPED"), 3000)
        self.assertEqual(logic.phase_ms("TRAVELING"), 5000)


class TestEta(unittest.TestCase):
    """ETA shown to the passenger (Milestone 3)."""

    def test_eta_when_stopped_at_target(self):
        self.assertEqual(logic.eta_seconds(5, 5, "STOPPED", 2), 0)

    def test_eta_next_station_while_stopped(self):
        self.assertEqual(logic.eta_seconds(6, 5, "STOPPED", 2), 7)  # 2 + 5

    def test_eta_three_stations_ahead(self):
        self.assertEqual(logic.eta_seconds(8, 5, "STOPPED", 2), 23)  # 2 + 5 + 2*(3+5)

    def test_eta_while_traveling(self):
        self.assertEqual(logic.eta_seconds(6, 5, "TRAVELING", 3), 3)
        self.assertEqual(logic.eta_seconds(7, 5, "TRAVELING", 3), 11)

    def test_eta_full_loop(self):
        self.assertEqual(logic.eta_seconds(5, 5, "TRAVELING", 3), 3 + 15 * 8)

    def test_wraparound(self):
        self.assertEqual(logic.eta_seconds(1, 16, "STOPPED", 1), 1 + 5)


class TestPrivacy(unittest.TestCase):
    def test_anon_id_has_no_username(self):
        self.assertEqual(logic.anon_id("abcdef1234567890"), "P-ABCD")


class TestMilestone4(unittest.TestCase):
    """Capacity, FIFO boarding and journey path (Milestone 4)."""

    def test_capacity_is_12(self):
        self.assertEqual(logic.CAPACITY, 12)

    def test_route_simple(self):
        self.assertEqual(logic.route(8, 13), [8, 9, 10, 11, 12, 13])

    def test_route_wraps_around(self):
        self.assertEqual(logic.route(15, 2), [15, 16, 1, 2])

    def test_route_length_is_never_more_than_one_loop(self):
        for a in range(1, 17):
            for b in range(1, 17):
                self.assertLessEqual(len(logic.route(a, b)), 16)

    def _rides(self, n):
        # created in reverse order in the list to prove sorting by time, not list order
        return [{"pk": "r%02d" % i, "created_ms": 1000 + i} for i in reversed(range(n))]

    def test_fifo_order(self):
        chosen = logic.select_boarders(self._rides(5), 3)
        self.assertEqual([r["pk"] for r in chosen], ["r00", "r01", "r02"])

    def test_capacity_limit_14_waiting_12_free(self):
        chosen = logic.select_boarders(self._rides(14), logic.CAPACITY)
        self.assertEqual(len(chosen), 12)
        self.assertEqual([r["pk"] for r in chosen], ["r%02d" % i for i in range(12)])  # r12, r13 stay

    def test_no_boarding_when_full(self):
        self.assertEqual(logic.select_boarders(self._rides(3), 0), [])
        self.assertEqual(logic.select_boarders(self._rides(3), -2), [])

    def test_same_millisecond_is_deterministic(self):
        rides = [{"pk": "b", "created_ms": 5}, {"pk": "a", "created_ms": 5}]
        self.assertEqual([r["pk"] for r in logic.select_boarders(rides, 2)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
