#!/bin/bash
# End-to-end test against the running tram. Usage: bash smoke_test.sh http://<PUBLIC_IP>
URL=${1:?usage: bash smoke_test.sh http://PUBLIC_IP}
U="user$RANDOM"
J='Content-Type: application/json'
echo "== 1. public state (no login)"; curl -s $URL/api/state; echo
echo "== 2. register + login"
curl -s -X POST $URL/api/register -H "$J" -d '{"username":"'$U'","password":"secret123"}'; echo
TOKEN=$(curl -s -X POST $URL/api/login -H "$J" -d '{"username":"'$U'","password":"secret123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
echo "token ok: ${TOKEN:0:6}..."
echo "== 3. /api/me without token must be 401"; curl -s -o /dev/null -w "%{http_code}\n" $URL/api/me
echo "== 4. request ride S02 -> S05"
curl -s -X POST $URL/api/ride -H "$J" -H "Authorization: Bearer $TOKEN" -d '{"from_station":2,"to_station":5}'; echo
echo "== 5. second ride must be rejected (max 1 active ride)"
curl -s -X POST $URL/api/ride -H "$J" -H "Authorization: Bearer $TOKEN" -d '{"from_station":3,"to_station":4}'; echo
echo "== 6. follow the ride (WAITING -> ON_BOARD -> no active ride)"
for i in $(seq 1 30); do
  curl -s $URL/api/me -H "Authorization: Bearer $TOKEN"; echo
  sleep 5
done
