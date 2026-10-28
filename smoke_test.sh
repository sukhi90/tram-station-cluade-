#!/bin/bash
# Milestone 2 check of the public view. Usage: bash smoke_test.sh http://<PUBLIC_IP>
URL=${1:?usage: bash smoke_test.sh http://PUBLIC_IP}
for i in 1 2 3 4 5; do
  curl -s $URL/api/state | python3 -c '
import sys, json
s = json.load(sys.stdin)
for k in ("station", "next_station", "direction", "phase", "remaining_seconds", "on_board", "free_seats", "capacity", "waiting"):
    assert k in s, "missing field: " + k
w = sum(len(v) for v in s["waiting"].values())
print("S%02d %-9s %4.1fs left | on board %d | free %d | waiting %d" % (s["station"], s["phase"], s["remaining_seconds"], s["on_board"], s["free_seats"], w))
'
  sleep 2
done
echo "public view reachable without login: OK"
