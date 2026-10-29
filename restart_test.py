#!/usr/bin/env python3
"""LIVE restart test: reboots the EC2 instance and checks that tram, login and ride survive.
Takes about 2-3 minutes.   Usage:  python3 restart_test.py http://<PUBLIC_IP> [stack-name]"""
import json, subprocess, sys, time, urllib.error, urllib.request

if len(sys.argv) < 2:
    sys.exit("usage: python3 restart_test.py http://PUBLIC_IP [stack-name]")
BASE = sys.argv[1].rstrip("/")
STACK = sys.argv[2] if len(sys.argv) > 2 else "tram"
failures = []


def call(method, path, body=None, token=None, timeout=8):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def instance_id():
    q = "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue"
    return subprocess.check_output(["aws", "cloudformation", "describe-stacks", "--stack-name", STACK,
                                    "--query", q, "--output", "text"], text=True).strip()


_, before = call("GET", "/api/state")
n = before["stations"]
print("before restart: tram at S%02d (%s)" % (before["station"], before["phase"]))

name = "restart%d" % int(time.time())
call("POST", "/api/register", {"username": name, "password": "secret123"})
token = call("POST", "/api/login", {"username": name, "password": "secret123"})[1]["token"]
a = (before["station"] + 10 - 1) % n + 1
b = (a + 1) % n + 1
code, _ = call("POST", "/api/ride", {"from_station": a, "to_station": b}, token)
check(code == 201, "ride S%02d -> S%02d requested before the restart" % (a, b))

iid = instance_id()
print("rebooting", iid, "...")
subprocess.check_call(["aws", "ec2", "reboot-instances", "--instance-ids", iid])
time.sleep(30)
deadline = time.time() + 400
up = False
while time.time() < deadline and not up:
    try:
        up = call("GET", "/api/state", timeout=5)[0] == 200
    except Exception:
        time.sleep(5)
check(up, "application is back after the reboot")

_, after = call("GET", "/api/state")
print("after restart:  tram at S%02d (%s)" % (after["station"], after["phase"]))
moved = (after["station"] - before["station"]) % n
check(moved <= 3, "tram continued from its old position (moved %d stations), it did not restart at S01" % moved)
code, me = call("GET", "/api/me", token=token)
check(code == 200, "login session is still valid (stored in DynamoDB)")
ride = me.get("ride") if code == 200 else None
last = me.get("last_ride") if code == 200 else None
check(bool(ride) or bool(last), "the ride survived (status: %s)" % ((ride or last or {}).get("status")))

print()
print("RESULT:", "RESTART TEST PASSED" if not failures else "%d FAILED" % len(failures))
sys.exit(1 if failures else 0)
