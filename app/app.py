import os, json, time, threading
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logic

REGION = os.environ.get("AWS_REGION", "us-east-1")
ddb = boto3.resource("dynamodb", region_name=REGION)
T_STATE = ddb.Table(os.environ["TABLE_STATE"])
T_RIDES = ddb.Table(os.environ["TABLE_RIDES"])
HERE = os.path.dirname(os.path.abspath(__file__))
TRAM_KEY = {"pk": "tram-1"}
ACTIVE = ["WAITING", "ON_BOARD"]


def now_ms():
    return int(time.time() * 1000)


def cond_failed(e):
    return e.response["Error"]["Code"] == "ConditionalCheckFailedException"


# ---------------------------------------------------------------- tram state
def init_state():
    try:
        T_STATE.put_item(
            Item={"pk": "tram-1", "station": 1, "phase": "STOPPED", "phase_start_ms": now_ms()},
            ConditionExpression="attribute_not_exists(pk)",
        )
        print("state initialised")
    except ClientError as e:
        if not cond_failed(e):
            raise
        print("existing state found, resuming")


def get_state():
    it = T_STATE.get_item(Key=TRAM_KEY, ConsistentRead=True)["Item"]
    return {"station": int(it["station"]), "phase": it["phase"], "phase_start_ms": int(it["phase_start_ms"])}


def snapshot():
    s = get_state()
    remaining = max(0, s["phase_start_ms"] + logic.phase_ms(s["phase"]) - now_ms()) / 1000.0
    return s, remaining


def advance():
    s = get_state()
    t = now_ms()
    dur = logic.phase_ms(s["phase"])
    if t - s["phase_start_ms"] < dur:
        return s
    start = s["phase_start_ms"] + dur
    if t - start > 16000:  # long downtime: do not replay the past
        start = t
    if s["phase"] == "STOPPED":
        new = {"station": s["station"], "phase": "TRAVELING", "phase_start_ms": start}
    else:
        new = {"station": logic.next_station(s["station"]), "phase": "STOPPED", "phase_start_ms": start}
    try:
        T_STATE.update_item(
            Key=TRAM_KEY,
            UpdateExpression="SET station=:st, phase=:ph, phase_start_ms=:ps",
            ConditionExpression="phase_start_ms = :old",
            ExpressionAttributeValues={":st": new["station"], ":ph": new["phase"], ":ps": start,
                                       ":old": s["phase_start_ms"]},
        )
        print("tram:", new["phase"], "S%02d" % new["station"])
        return new
    except ClientError as e:
        if not cond_failed(e):
            raise
        return get_state()


# --------------------------------------------------------------------- rides
def active_rides():
    items = []
    kw = {"FilterExpression": Attr("ride_status").is_in(ACTIVE)}
    while True:
        r = T_RIDES.scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            return items
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


_cache = {"t": 0.0, "v": []}


def active_rides_cached():
    if time.time() - _cache["t"] < 0.4:
        return _cache["v"]
    v = active_rides()
    _cache["t"] = time.time()
    _cache["v"] = v
    return v


def set_ride_status(ride, old, new, extra_field):
    T_RIDES.update_item(
        Key={"pk": ride["pk"]},
        UpdateExpression="SET #s=:n, " + extra_field + "=:t",
        ConditionExpression="#s=:o",
        ExpressionAttributeNames={"#s": "ride_status"},
        ExpressionAttributeValues={":n": new, ":o": old, ":t": now_ms()},
    )


def complete_ride(ride):
    try:
        set_ride_status(ride, "ON_BOARD", "COMPLETED", "completed_ms")
    except ClientError as e:
        if not cond_failed(e):
            raise
    print("completed", logic.anon_id(ride["pk"]))


def board_ride(ride):
    try:
        set_ride_status(ride, "WAITING", "ON_BOARD", "boarded_ms")
        print("boarded", logic.anon_id(ride["pk"]))
    except ClientError as e:
        if not cond_failed(e):
            raise


def process_stop(station):
    """Idempotent: runs every tick while the tram is stopped."""
    rides = active_rides()
    alighting = [r for r in rides if r["ride_status"] == "ON_BOARD" and int(r["to_station"]) == station]
    for r in alighting:
        complete_ride(r)
    on_board = sum(1 for r in rides if r["ride_status"] == "ON_BOARD") - len(alighting)
    free = logic.CAPACITY - on_board
    here = sorted((r for r in rides if r["ride_status"] == "WAITING" and int(r["from_station"]) == station),
                  key=lambda r: int(r["created_ms"]))
    for r in here[:max(free, 0)]:
        board_ride(r)


def worker():
    while True:
        try:
            s = advance()
            if s["phase"] == "STOPPED":
                process_stop(s["station"])
        except Exception as e:
            print("worker error:", e)
        time.sleep(0.25)


# --------------------------------------------------------------------- views
def public_view():
    s, remaining = snapshot()
    waiting = {str(i): [] for i in range(1, logic.STATIONS + 1)}
    on_board = []
    for r in active_rides_cached():
        aid = logic.anon_id(r["pk"])  # anonymous identifier only
        if r["ride_status"] == "WAITING":
            waiting[str(int(r["from_station"]))].append(aid)
        else:
            on_board.append(aid)
    return {
        "station": s["station"],
        "next_station": logic.next_station(s["station"]),
        "direction": "clockwise (S01 to S16, then S01)",
        "phase": s["phase"],
        "remaining_seconds": round(remaining, 1),
        "capacity": logic.CAPACITY,
        "on_board": len(on_board),
        "on_board_ids": on_board,
        "free_seats": logic.CAPACITY - len(on_board),
        "waiting": waiting,
    }


# ---------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def _raw(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/state":
                self._raw(200, json.dumps(public_view()).encode("utf-8"), "application/json")
            elif path == "/health":
                self._raw(200, b"ok", "text/plain")
            else:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    self._raw(200, f.read(), "text/html; charset=utf-8")
        except Exception as e:
            print("GET error:", e)
            self._raw(500, b'{"error": "server error"}', "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    init_state()
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
