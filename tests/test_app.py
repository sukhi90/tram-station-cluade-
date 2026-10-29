"""Milestone 5 tests: clock speed, status changes, travel restrictions, restart, security.

They run the REAL application code (app/app.py) against an in-memory DynamoDB (fake_dynamodb.py)
and a fake clock, so a whole tram lap (128 s) is simulated in milliseconds. No AWS needed."""
import hashlib
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import boto3  # noqa: E402
import logic  # noqa: E402
from fake_dynamodb import FakeDynamo, FakeStore  # noqa: E402

CYCLE = logic.STOP_S + logic.TRAVEL_S
START_T = 1_800_000_000.0


class Clock:
    """Fake time. The tests move it forward by hand."""
    def __init__(self):
        self.t = START_T

    def time(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def load_app(store, clock, fast_hash=True):
    """Import app.py as a fresh process would: new module, same 'AWS account' (store)."""
    for k in ("TABLE_STATE", "TABLE_USERS", "TABLE_SESSIONS", "TABLE_RIDES"):
        os.environ[k] = "test-" + k
    os.environ["AWS_REGION"] = "us-east-1"
    original = boto3.resource
    boto3.resource = lambda *a, **k: FakeDynamo(store)
    try:
        sys.modules.pop("app", None)
        import app
    finally:
        boto3.resource = original
    app.time = clock
    app.print = lambda *a, **k: None  # keep the test output quiet
    if fast_hash:  # PBKDF2 is deliberately slow; the tests do not need that
        app.hash_pw = lambda pw, salt: hashlib.sha256(salt + pw.encode()).hexdigest()
    return app


class Base(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.clock = Clock()
        self.app = load_app(self.store, self.clock)
        self.app.init_state()

    # -- helpers ------------------------------------------------------------
    def restart(self, fast_hash=True):
        """Simulate a crash / reboot: the process is gone, the data in DynamoDB stays."""
        self.app = load_app(self.store, self.clock, fast_hash)
        self.app.init_state()
        return self.app

    def state(self):
        return self.app.get_state()

    def run_for(self, seconds, step=0.25):
        end = self.clock.t + seconds
        while self.clock.t < end - 1e-9:
            self.clock.advance(step)
            self.app.tick()

    def run_until(self, station, phase="STOPPED", limit=1000):
        n = 0
        while True:
            st = self.state()
            if st["station"] == station and st["phase"] == phase:
                return
            n += 1
            self.assertLess(n * 0.25, limit, "tram never reached S%02d %s" % (station, phase))
            self.clock.advance(0.25)
            self.app.tick()

    def signup(self, name, pw="password1"):
        self.app.register(name, pw)
        return self.app.login(name, pw)

    def ride(self, name):
        return self.app.my_view(name)["ride"]

    def status(self, name):
        v = self.app.my_view(name)
        return v["ride"]["status"] if v["ride"] else (v["last_ride"] or {}).get("status")


# =====================================================================================
class TestClockSpeed(Base):
    """3 seconds stop, 5 seconds travel, S01..S16 then S01."""

    def test_initial_state(self):
        s = self.state()
        self.assertEqual((s["station"], s["phase"]), (1, "STOPPED"))

    def test_stop_lasts_exactly_stop_seconds(self):
        self.run_for(logic.STOP_S - 0.25)
        self.assertEqual(self.state()["phase"], "STOPPED")
        self.run_for(0.25)
        s = self.state()
        self.assertEqual((s["station"], s["phase"]), (1, "TRAVELING"))

    def test_travel_lasts_exactly_travel_seconds(self):
        self.run_until(1, "TRAVELING")
        self.run_for(logic.TRAVEL_S - 0.25)
        self.assertEqual(self.state()["phase"], "TRAVELING")
        self.run_for(0.25)
        s = self.state()
        self.assertEqual((s["station"], s["phase"]), (2, "STOPPED"))

    def test_one_lap_visits_all_stations_in_order_and_returns_to_start(self):
        seen = []
        last = 1  # the tram starts stopped at S01
        for _ in range(int(logic.STATIONS * CYCLE / 0.25)):
            self.clock.advance(0.25)
            self.app.tick()
            s = self.state()
            if s["phase"] == "STOPPED" and s["station"] != last:
                seen.append(s["station"])
                last = s["station"]
        self.assertEqual(seen, list(range(2, logic.STATIONS + 1)) + [1])
        self.assertEqual(self.clock.t - START_T, logic.STATIONS * CYCLE)

    def test_no_drift_after_ten_laps(self):
        self.run_for(10 * logic.STATIONS * CYCLE)
        s = self.state()
        self.assertEqual((s["station"], s["phase"]), (1, "STOPPED"))
        self.assertEqual(s["phase_start_ms"], int((self.clock.t) * 1000))

    def test_remaining_time_is_reported(self):
        self.run_for(1)
        v = self.app.public_view()
        self.assertEqual(v["remaining_seconds"], logic.STOP_S - 1)
        self.assertEqual(v["phase"], "STOPPED")

    def test_two_workers_cannot_advance_twice(self):
        """Conditional update: a second worker with a stale view must not move the tram again."""
        stale = self.state()
        self.clock.advance(logic.STOP_S)
        self.app.advance()  # worker 1 moves the tram
        first = self.state()
        # worker 2 acts on the stale view: its conditional update has to fail
        from botocore.exceptions import ClientError
        with self.assertRaises(ClientError):
            self.app.T_STATE.update_item(
                Key=self.app.TRAM_KEY, UpdateExpression="SET station=:st, phase=:ph, phase_start_ms=:ps",
                ConditionExpression="phase_start_ms = :old",
                ExpressionAttributeValues={":st": 9, ":ph": "STOPPED", ":ps": 1, ":old": stale["phase_start_ms"]})
        self.assertEqual(self.state(), first)


# =====================================================================================
class TestStatusChanges(Base):
    """WAITING -> ON_BOARD -> COMPLETED."""

    def test_full_lifecycle(self):
        self.signup("alice")
        self.app.create_ride("alice", 3, 5)
        self.assertEqual(self.status("alice"), "WAITING")
        self.run_until(3)
        self.assertEqual(self.status("alice"), "ON_BOARD")
        self.run_until(5)
        v = self.app.my_view("alice")
        self.assertIsNone(v["ride"])
        self.assertEqual(v["last_ride"]["status"], "COMPLETED")
        self.assertEqual(v["last_ride"]["path"], [3, 4, 5])

    def test_waiting_shows_eta_to_start_station(self):
        self.signup("alice")
        self.app.create_ride("alice", 3, 5)
        r = self.ride("alice")
        # tram stands at S01 with STOP_S left -> S02 after TRAVEL_S -> S03 one more cycle
        self.assertEqual(r["eta_seconds"], logic.STOP_S + logic.TRAVEL_S + CYCLE)
        self.assertEqual(r["eta_station"], 3)

    def test_on_board_eta_points_to_destination(self):
        self.signup("alice")
        self.app.create_ride("alice", 2, 4)
        self.run_until(2)
        r = self.ride("alice")
        self.assertEqual((r["status"], r["eta_station"]), ("ON_BOARD", 4))
        self.assertEqual(r["eta_seconds"], logic.STOP_S + logic.TRAVEL_S + CYCLE)

    def test_boarding_happens_only_at_the_start_station(self):
        self.signup("alice")
        self.app.create_ride("alice", 5, 7)
        self.run_until(4)
        self.assertEqual(self.status("alice"), "WAITING")
        self.run_until(5)
        self.assertEqual(self.status("alice"), "ON_BOARD")

    def test_new_ride_possible_after_completed(self):
        self.signup("alice")
        self.app.create_ride("alice", 2, 3)
        self.run_until(3)
        self.assertEqual(self.status("alice"), "COMPLETED")
        self.app.create_ride("alice", 6, 8)
        self.assertEqual(self.status("alice"), "WAITING")

    def test_public_view_counts_follow_the_status(self):
        self.signup("alice")
        self.signup("bob")
        self.app.create_ride("alice", 3, 6)
        self.clock.advance(0.01)
        self.app.create_ride("bob", 3, 6)
        self.app._cache["t"] = 0
        v = self.app.public_view()
        self.assertEqual(len(v["waiting"]["3"]), 2)
        self.assertEqual((v["on_board"], v["free_seats"]), (0, logic.CAPACITY))
        self.run_until(3)
        self.clock.advance(1)
        v = self.app.public_view()
        self.assertEqual(len(v["waiting"]["3"]), 0)
        self.assertEqual((v["on_board"], v["free_seats"]), (2, logic.CAPACITY - 2))
        self.run_until(6)
        self.clock.advance(1)
        v = self.app.public_view()
        self.assertEqual((v["on_board"], v["free_seats"]), (0, logic.CAPACITY))


# =====================================================================================
class TestTravelRestrictions(Base):
    def test_only_one_active_ride_per_person(self):
        self.signup("alice")
        self.app.create_ride("alice", 3, 5)
        with self.assertRaises(ValueError):
            self.app.create_ride("alice", 6, 8)

    def test_one_active_ride_also_while_on_board(self):
        self.signup("alice")
        self.app.create_ride("alice", 2, 9)
        self.run_until(2)
        with self.assertRaises(ValueError):
            self.app.create_ride("alice", 5, 6)

    def test_start_and_destination_must_differ(self):
        self.signup("alice")
        with self.assertRaises(ValueError):
            self.app.create_ride("alice", 4, 4)

    def test_stations_must_exist(self):
        self.signup("alice")
        for a, b in [(0, 3), (3, logic.STATIONS + 1), (-1, 2), ("3", 5), (None, 5), (2.5, 4), (True, 5)]:
            with self.assertRaises(ValueError, msg=str((a, b))):
                self.app.create_ride("alice", a, b)
        self.assertIsNone(self.ride("alice"))  # nothing was created

    def test_unknown_user_cannot_ride(self):
        with self.assertRaises(ValueError):
            self.app.create_ride("ghost", 2, 4)

    def test_tram_only_drives_forward(self):
        """S05 -> S03 means almost a whole lap, never backwards."""
        self.signup("alice")
        self.app.create_ride("alice", 5, 3)
        self.run_until(5)
        t0 = self.clock.t
        self.run_until(3)
        self.assertEqual(self.status("alice"), "COMPLETED")
        self.assertEqual(self.clock.t - t0, (logic.STATIONS - 2) * CYCLE)

    def test_capacity_limit_and_fifo(self):
        n = logic.CAPACITY + 2
        names = ["u%02d" % i for i in range(n)]
        for name in names:
            self.signup(name)
        for name in names:  # one after another = FIFO order
            self.app.create_ride(name, 2, 4)
            self.clock.advance(0.01)
        self.run_until(2)
        on_board = [self.status(x) == "ON_BOARD" for x in names]
        self.assertEqual(on_board, [True] * logic.CAPACITY + [False] * 2)  # the last two have to wait
        self.assertEqual(self.status(names[-1]), "WAITING")
        self.app._cache["t"] = 0
        v = self.app.public_view()
        self.assertEqual((v["on_board"], v["free_seats"]), (logic.CAPACITY, 0))
        self.run_until(4)  # everybody on board arrives, seats are free again
        self.assertTrue(all(self.status(x) == "COMPLETED" for x in names[:logic.CAPACITY]))
        self.assertEqual(self.status(names[-1]), "WAITING")
        self.run_until(2)  # next lap: the two who waited board now
        self.assertEqual([self.status(x) for x in names[-2:]], ["ON_BOARD", "ON_BOARD"])
        self.run_until(4)
        self.assertEqual([self.status(x) for x in names[-2:]], ["COMPLETED", "COMPLETED"])

    def test_passenger_never_boards_a_full_tram_even_with_many_requests(self):
        for i in range(logic.CAPACITY * 2):
            self.signup("p%02d" % i)
            self.app.create_ride("p%02d" % i, 2, 6)
            self.clock.advance(0.01)
        for _ in range(int(2 * logic.STATIONS * CYCLE / 0.25)):
            self.clock.advance(0.25)
            self.app.tick()
            on_board = sum(1 for r in self.app.active_rides() if r["ride_status"] == "ON_BOARD")
            self.assertLessEqual(on_board, logic.CAPACITY)


# =====================================================================================
class TestRestart(Base):
    """States persist through a restart: tram, rides and sessions live in DynamoDB."""

    def test_tram_position_survives_restart(self):
        self.run_until(5, "TRAVELING")
        before = self.state()
        self.restart()
        self.assertEqual(self.state(), before)

    def test_restart_does_not_reset_to_S01(self):
        self.run_until(9)
        self.restart()
        self.assertEqual(self.state()["station"], 9)

    def test_timing_continues_after_restart(self):
        self.run_until(2, "TRAVELING")
        self.run_for(2)
        self.restart()  # 2 of the 5 travel seconds are already over
        self.run_for(logic.TRAVEL_S - 2 - 0.25)
        self.assertEqual(self.state()["phase"], "TRAVELING")
        self.run_for(0.25)
        s = self.state()
        self.assertEqual((s["station"], s["phase"]), (3, "STOPPED"))

    def test_long_outage_moves_at_most_one_step_and_does_not_replay(self):
        self.run_until(6)
        before = self.state()
        self.clock.advance(3600)  # the machine was down for an hour
        self.restart()
        self.app.tick()
        after = self.state()
        self.assertIn((after["station"] - before["station"]) % logic.STATIONS, (0, 1))
        self.assertEqual(after["phase_start_ms"], self.app.now_ms())  # timing restarts cleanly

    def test_waiting_and_on_board_rides_survive_restarts(self):
        self.signup("alice")
        self.app.create_ride("alice", 3, 6)
        self.run_until(2)
        self.restart()
        self.assertEqual(self.status("alice"), "WAITING")
        self.run_until(3)
        self.assertEqual(self.status("alice"), "ON_BOARD")
        self.restart()
        self.assertEqual(self.status("alice"), "ON_BOARD")
        self.run_until(6)
        self.assertEqual(self.status("alice"), "COMPLETED")

    def test_login_session_survives_restart(self):
        token = self.signup("alice")
        self.restart()
        self.assertEqual(self.app.session_user(token), "alice")

    def test_max_one_ride_rule_survives_restart(self):
        self.signup("alice")
        self.app.create_ride("alice", 3, 6)
        self.restart()
        with self.assertRaises(ValueError):
            self.app.create_ride("alice", 7, 8)

    def test_state_is_only_in_the_database(self):
        """A brand-new process sees everything an old one wrote: nothing lives in memory or in files."""
        self.signup("alice")
        self.app.create_ride("alice", 4, 8)
        self.run_for(20)
        before = (self.state(), self.app.my_view("alice"))
        self.restart()
        self.assertEqual((self.state(), self.app.my_view("alice")), before)


# =====================================================================================
class TestSecurityAndPrivacy(Base):
    def test_password_is_stored_as_salted_hash(self):
        self.restart(fast_hash=False)  # use the real PBKDF2 here
        self.app.register("alice", "correct horse")
        item = self.app.T_USERS.get_item(Key={"pk": "alice"})["Item"]
        self.assertNotIn("correct horse", json.dumps(item, default=str))
        self.assertEqual(len(item["pw_hash"]), 64)
        self.assertEqual(len(item["salt"]), 32)
        self.app.register("bob", "correct horse")
        other = self.app.T_USERS.get_item(Key={"pk": "bob"})["Item"]
        self.assertNotEqual(item["pw_hash"], other["pw_hash"])  # different salt, different hash
        self.assertTrue(self.app.login("alice", "correct horse"))

    def test_wrong_password_and_unknown_user_are_rejected(self):
        self.signup("alice")
        with self.assertRaises(PermissionError):
            self.app.login("alice", "wrong-password")
        with self.assertRaises(PermissionError):
            self.app.login("nobody", "password1")

    def test_registration_rules(self):
        self.signup("alice")
        for name, pw in [("alice", "password1"), ("ALICE", "password1"), ("al", "password1"),
                         ("bad name!", "password1"), ("carol", "short"), (None, "password1"), ("dave", None)]:
            with self.assertRaises(ValueError, msg=str((name, pw))):
                self.app.register(name, pw)

    def test_session_expires(self):
        token = self.signup("alice")
        self.assertEqual(self.app.session_user(token), "alice")
        self.clock.advance(self.app.SESSION_TTL_S + 1)
        self.assertIsNone(self.app.session_user(token))

    def test_unknown_token_is_rejected(self):
        self.assertIsNone(self.app.session_user("not-a-token"))

    def test_public_view_has_only_anonymous_identifiers(self):
        for name in ("alice", "bob"):
            self.signup(name)
        self.app.create_ride("alice", 2, 5)
        self.clock.advance(0.01)
        self.app.create_ride("bob", 6, 9)
        self.run_until(2)
        self.clock.advance(1)
        self.app._cache["t"] = 0
        text = json.dumps(self.app.public_view())
        for secret in ("alice", "bob", "from_station", "to_station", "rider"):
            self.assertNotIn(secret, text)
        ids = self.app.public_view()["on_board_ids"]
        self.assertEqual(len(ids), 1)
        self.assertRegex(ids[0], r"^P-[0-9A-F]{4}$")

    def test_destination_of_others_is_never_public(self):
        self.signup("alice")
        self.app.create_ride("alice", 2, 11)
        self.run_until(2)
        self.app._cache["t"] = 0
        self.assertNotIn("11", json.dumps(self.app.public_view()["on_board_ids"]))
        self.assertNotIn("to", self.app.public_view())


# =====================================================================================
class TestHttpApi(Base):
    """The real HTTP handler on a local port (the same code that runs on the EC2 instance)."""

    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, token=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def js(self, *a, **k):
        code, body = self.call(*a, **k)
        return code, json.loads(body)

    def test_public_endpoints_need_no_login(self):
        code, v = self.js("GET", "/api/state")
        self.assertEqual(code, 200)
        for key in ("station", "next_station", "direction", "phase", "remaining_seconds", "on_board",
                    "free_seats", "capacity", "waiting", "stations"):
            self.assertIn(key, v)
        self.assertEqual(self.call("GET", "/health"), (200, b"ok"))
        code, page = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Tram circular route", page)

    def test_personal_endpoints_need_login(self):
        self.assertEqual(self.js("GET", "/api/me")[0], 401)
        self.assertEqual(self.js("POST", "/api/ride", {"from_station": 2, "to_station": 3})[0], 401)
        self.assertEqual(self.js("GET", "/api/me", token="bogus")[0], 401)

    def test_register_login_ride_flow(self):
        self.assertEqual(self.js("POST", "/api/register", {"username": "alice", "password": "password1"})[0], 201)
        self.assertEqual(self.js("POST", "/api/register", {"username": "alice", "password": "password1"})[0], 400)
        self.assertEqual(self.js("POST", "/api/login", {"username": "alice", "password": "nope-nope"})[0], 401)
        code, d = self.js("POST", "/api/login", {"username": "alice", "password": "password1"})
        self.assertEqual(code, 200)
        token = d["token"]
        code, me = self.js("POST", "/api/ride", {"from_station": 3, "to_station": 5}, token=token)
        self.assertEqual(code, 201)
        self.assertEqual(me["ride"]["status"], "WAITING")
        self.assertEqual(me["ride"]["path"], [3, 4, 5])
        code, err = self.js("POST", "/api/ride", {"from_station": 6, "to_station": 7}, token=token)
        self.assertEqual(code, 400)
        self.assertIn("already", err["error"])
        self.assertEqual(self.js("POST", "/api/logout", {}, token=token)[0], 200)
        self.assertEqual(self.js("GET", "/api/me", token=token)[0], 401)

    def test_bad_input_gives_400_not_a_crash(self):
        self.assertEqual(self.call("POST", "/api/register", raw=b"this is not json")[0], 400)
        self.assertEqual(self.js("POST", "/api/nothing", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
