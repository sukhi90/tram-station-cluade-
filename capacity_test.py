#!/usr/bin/env python3
"""Acceptance test against the RUNNING tram: capacity, FIFO boarding, COMPLETED, new ride.
It reads stations / timing / capacity from the server, so it works after you changed the rules.
Takes about one lap of the tram plus a minute (about 3-5 minutes with the default rules).

Usage:  python3 capacity_test.py http://<PUBLIC_IP> [expected_capacity]
"""
import json, random, sys, time, urllib.error, urllib.request

if len(sys.argv) < 2:
    sys.exit("usage: python3 capacity_test.py http://PUBLIC_IP [expected_capacity]")
BASE = sys.argv[1].rstrip("/")
EXPECTED_CAP = int(sys.argv[2]) if len(sys.argv) > 2 else None
failures = []


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def wait_for(fn, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(1)
    print("TIMEOUT waiting for " + what)
    return None


# 1. read the rules from the running system
_, st = call("GET", "/api/state")
n, CAP = st["stations"], st["capacity"]
LAP = n * (st["stop_seconds"] + st["travel_seconds"])
N_USERS = CAP + 2
print("rules: %d stations, stop %ds, travel %ds, capacity %d (one lap = %ds)"
      % (n, st["stop_seconds"], st["travel_seconds"], CAP, LAP))
if EXPECTED_CAP is not None:
    check(CAP == EXPECTED_CAP, "capacity is %d as expected" % EXPECTED_CAP)

# 2. start station almost a full lap ahead, so all users can request before the tram arrives
start = (st["station"] + (n - 2) - 1) % n + 1
dest = (start + 1) % n + 1  # two stops after start
print("tram at S%02d -> test ride S%02d to S%02d, %d users" % (st["station"], start, dest, N_USERS))

tag = "cap%d" % random.randint(1000, 9999)
users = []
for i in range(N_USERS):
    name = "%s_%02d" % (tag, i)
    call("POST", "/api/register", {"username": name, "password": "secret123"})
    code, d = call("POST", "/api/login", {"username": name, "password": "secret123"})
    users.append({"name": name, "token": d["token"]})
for u in users:  # one after another = FIFO order
    code, _ = call("POST", "/api/ride", {"from_station": start, "to_station": dest}, u["token"])
    if code != 201:
        check(False, "ride request failed for " + u["name"])
        break
print("rides requested at", time.strftime("%X"), "- waiting for the tram at S%02d ..." % start)

# 3. capacity + FIFO
wait_for(lambda: call("GET", "/api/state")[1]["on_board"] >= CAP, LAP + 60, "tram to fill up")
_, pub = call("GET", "/api/state")
check(pub["on_board"] == CAP and pub["free_seats"] == 0, "%d on board, 0 free seats" % CAP)
stat = [call("GET", "/api/me", token=u["token"])[1]["ride"]["status"] for u in users]
check(stat[:CAP] == ["ON_BOARD"] * CAP, "first %d requests are ON_BOARD (FIFO)" % CAP)
check(stat[CAP:] == ["WAITING"] * (N_USERS - CAP), "the last 2 requests are still WAITING (tram full)")
check(not any(u["name"] in json.dumps(pub) for u in users), "public view contains no usernames")


# 4. COMPLETED + new ride
def first_completed():
    d = call("GET", "/api/me", token=users[0]["token"])[1]
    return d["ride"] is None and d.get("last_ride") and d["last_ride"]["status"] == "COMPLETED"


check(bool(wait_for(first_completed, LAP // 2 + 60, "first passenger to arrive")),
      "ride becomes COMPLETED at the destination")
code, _ = call("POST", "/api/ride", {"from_station": 1, "to_station": 2}, users[0]["token"])
check(code == 201, "new ride possible after COMPLETED")

# 5. the two who had to wait board on the next lap
late = wait_for(lambda: (call("GET", "/api/me", token=users[CAP]["token"])[1].get("ride") or {}).get("status")
                == "ON_BOARD", LAP + 60, "waiting passenger to board")
check(bool(late), "a waiting passenger boards on the next lap (seat free again)")

print()
print("RESULT:", "ALL TESTS PASSED" if not failures else "%d FAILED" % len(failures))
sys.exit(1 if failures else 0)
