import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import logic


class TestLogic(unittest.TestCase):
    def test_next_station_wraps(self):
        self.assertEqual(logic.next_station(1), 2)
        self.assertEqual(logic.next_station(16), 1)

    def test_eta_when_stopped_at_target(self):
        self.assertEqual(logic.eta_seconds(5, 5, "STOPPED", 2), 0)

    def test_eta_next_station_while_stopped(self):
        # 2s until departure + 5s travel
        self.assertEqual(logic.eta_seconds(6, 5, "STOPPED", 2), 7)

    def test_eta_three_stations_ahead(self):
        # 2 + 5 + 2 * (3+5)
        self.assertEqual(logic.eta_seconds(8, 5, "STOPPED", 2), 23)

    def test_eta_while_traveling(self):
        self.assertEqual(logic.eta_seconds(6, 5, "TRAVELING", 3), 3)
        self.assertEqual(logic.eta_seconds(7, 5, "TRAVELING", 3), 11)

    def test_eta_full_loop(self):
        # just left station 5: must go all the way around
        self.assertEqual(logic.eta_seconds(5, 5, "TRAVELING", 3), 3 + 15 * 8)

    def test_wraparound(self):
        self.assertEqual(logic.eta_seconds(1, 16, "STOPPED", 1), 1 + 5)

    def test_anon_id_has_no_username(self):
        a = logic.anon_id("abcdef1234567890")
        self.assertEqual(a, "P-ABCD")

    def test_cycle_length(self):
        self.assertEqual(logic.STATIONS * (logic.STOP_S + logic.TRAVEL_S), 128)


if __name__ == "__main__":
    unittest.main()
