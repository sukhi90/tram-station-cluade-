#!/usr/bin/env python3
"""Milestone 4 acceptance test against the RUNNING tram (takes about 5 minutes).

Checks: max 12 passengers, FIFO boarding, COMPLETED at destination,
        new ride after COMPLETED, no usernames in the public view.

Usage:  python3 capacity_test.py http://<PUBLIC_IP>
"""
import json, random, sys, time, urllib.error, urllib.request

if len(sys.argv) < 2:
    sys.exit("usage: python3 capacity_test.py http://PUBLIC_IP")
BASE = sys.argv[1].rstrip("/")
N_USERS, CAP = 14, 12
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


# 1. choose a start station about 8 stops ahead of the tram, so everybody can request before it arrives
_, st = call("GET", "/api/state")
start = (st["station"] + 8 - 1) % 16 + 1
dest = (start + 1) % 16 + 1  # two stops after start
print("tram at S%02d -> test ride S%02d to S%02d" % (st["station"], start, dest))

# 2. register 14 users and request rides one after another (= FIFO order)
tag = "cap%d" % random.randint(1000, 9999)
users = []
for i in range(N_USERS):
    name = "%s_%02d" % (tag, i)
    call("POST", "/api/register", {"username": name, "password": "secret123"})
    code, d = call("POST", "/api/login", {"username": name, "password": "secret123"})
    users.append({"name": name, "token": d["token"]})
for u in users:
    code, _ = call("POST", "/api/ride", {"from_station": start, "to_station": dest}, u["token"])
    check(code == 201, "ride requested by " + u["name"] if code != 201 else "ride requested (%s)" % u["name"])
    if code != 201:
        break
print("requested rides at", time.strftime("%X"), "- waiting for the tram to arrive at S%02d ..." % start)

# 3. capacity + FIFO
full = wait_for(lambda: call("GET", "/api/state")[1]["on_board"] >= CAP, 200, "tram to fill up")
_, pub = call("GET", "/api/state")
check(pub["capacity"] == 12, "public capacity is 12")
check(pub["on_board"] == CAP and pub["free_seats"] == 0, "12 on board, 0 free seats")
stat = [call("GET", "/api/me", token=u["token"])[1]["ride"]["status"] for u in users]
check(stat[:CAP] == ["ON_BOARD"] * CAP, "first 12 requests are ON_BOARD (FIFO)")
check(stat[CAP:] == ["WAITING"] * (N_USERS - CAP), "13th and 14th request still WAITING (tram full)")
check(not any(u["name"] in json.dumps(pub) for u in users), "public view contains no usernames")

# 4. COMPLETED + new ride
def first_completed():
    d = call("GET", "/api/me", token=users[0]["token"])[1]
    return d["ride"] is None and d.get("last_ride") and d["last_ride"]["status"] == "COMPLETED"

done = wait_for(first_completed, 120, "first passenger to arrive")
check(bool(done), "ride becomes COMPLETED at the destination")
code, _ = call("POST", "/api/ride", {"from_station": 1, "to_station": 5}, users[0]["token"])
check(code == 201, "new ride possible after COMPLETED")

# 5. the two who had to wait board on the next lap
late = wait_for(lambda: (call("GET", "/api/me", token=users[12]["token"])[1].get("ride") or {}).get("status")
                in ("ON_BOARD",), 200, "13th passenger to board")
check(bool(late), "13th passenger boards on the next lap (seat free again)")

print()
print("RESULT:", "ALL TESTS PASSED" if not failures else "%d FAILED" % len(failures))
sys.exit(1 if failures else 0)
