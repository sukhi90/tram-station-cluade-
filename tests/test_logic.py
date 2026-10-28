import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import logic


class TestLogic(unittest.TestCase):
    def test_line_constants(self):
        self.assertEqual((logic.STATIONS, logic.STOP_S, logic.TRAVEL_S), (16, 3, 5))

    def test_next_station_wraps(self):
        self.assertEqual(logic.next_station(1), 2)
        self.assertEqual(logic.next_station(16), 1)

    def test_full_loop_in_order(self):
        s, seen = 1, []
        for _ in range(16):
            seen.append(s)
            s = logic.next_station(s)
        self.assertEqual(seen, list(range(1, 17)))
        self.assertEqual(s, 1)

    def test_phase_durations(self):
        self.assertEqual(logic.phase_ms("STOPPED"), 3000)
        self.assertEqual(logic.phase_ms("TRAVELING"), 5000)

    def test_cycle_length(self):
        self.assertEqual(logic.STATIONS * (logic.STOP_S + logic.TRAVEL_S), 128)

    def test_anon_id_has_no_username(self):
        self.assertEqual(logic.anon_id("abcdef1234567890"), "P-ABCD")


if __name__ == "__main__":
    unittest.main()
