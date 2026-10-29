import os, json, time, threading, hashlib, hmac, secrets, re
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logic

REGION = os.environ.get("AWS_REGION", "us-east-1")
ddb = boto3.resource("dynamodb", region_name=REGION)
T_STATE = ddb.Table(os.environ["TABLE_STATE"])
T_USERS = ddb.Table(os.environ["TABLE_USERS"])
T_SESSIONS = ddb.Table(os.environ["TABLE_SESSIONS"])
T_RIDES = ddb.Table(os.environ["TABLE_RIDES"])
HERE = os.path.dirname(os.path.abspath(__file__))
TRAM_KEY = {"pk": "tram-1"}
USER_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
SESSION_TTL_S = 24 * 3600
ACTIVE = ["WAITING", "ON_BOARD"]
LAG_RESET_MS = 2 * (logic.STOP_S + logic.TRAVEL_S) * 1000  # after a longer outage do not replay the past


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
    st = int(it["station"])
    if not 1 <= st <= logic.STATIONS:  # the line was shortened: restart at S01
        st = 1
    return {"station": st, "phase": it["phase"], "phase_start_ms": int(it["phase_start_ms"])}


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
    if t - start > LAG_RESET_MS:  # long downtime: do not replay the past
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
    try:  # free the user for the next ride
        T_USERS.update_item(
            Key={"pk": ride["rider"]},
            UpdateExpression="REMOVE active_ride SET last_ride=:l",
            ConditionExpression="active_ride = :r",
            ExpressionAttributeValues={":r": ride["pk"], ":l": ride["pk"]},
        )
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
    here = [r for r in rides if r["ride_status"] == "WAITING" and int(r["from_station"]) == station]
    for r in logic.select_boarders(here, free):  # FIFO, max 12 passengers
        board_ride(r)


def tick():
    """One simulation step (also called directly by the tests)."""
    s = advance()
    if s["phase"] == "STOPPED":
        process_stop(s["station"])


def worker():
    while True:
        try:
            tick()
        except Exception as e:
            print("worker error:", e)
        time.sleep(0.25)


# ----------------------------------------------------------------- auth/users
def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200000).hex()


def register(username, pw):
    if not isinstance(username, str) or not USER_RE.match(username):
        raise ValueError("username: 3-20 characters, letters/digits/underscore")
    if not isinstance(pw, str) or len(pw) < 8:
        raise ValueError("password: at least 8 characters")
    salt = os.urandom(16)
    try:
        T_USERS.put_item(
            Item={"pk": username.lower(), "salt": salt.hex(), "pw_hash": hash_pw(pw, salt), "created_ms": now_ms()},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as e:
        if cond_failed(e):
            raise ValueError("username already taken")
        raise


def login(username, pw):
    u = T_USERS.get_item(Key={"pk": str(username).lower()}).get("Item")
    if not u or not hmac.compare_digest(hash_pw(str(pw), bytes.fromhex(u["salt"])), u["pw_hash"]):
        raise PermissionError("invalid username or password")
    token = secrets.token_urlsafe(24)
    T_SESSIONS.put_item(Item={"pk": token, "username": u["pk"], "expires_at": int(time.time()) + SESSION_TTL_S})
    return token


def session_user(token):
    s = T_SESSIONS.get_item(Key={"pk": token}).get("Item")
    if not s or int(s["expires_at"]) < time.time():
        return None
    return s["username"]


def create_ride(username, a, b):
    if not all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= logic.STATIONS for x in (a, b)):
        raise ValueError("stations must be numbers 1-%d" % logic.STATIONS)
    if a == b:
        raise ValueError("start and destination must differ")
    rid = secrets.token_hex(8)
    for attempt in range(2):
        try:  # atomic claim: only ONE active ride per person
            T_USERS.update_item(
                Key={"pk": username},
                UpdateExpression="SET active_ride=:r",
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(active_ride)",
                ExpressionAttributeValues={":r": rid},
            )
            break
        except ClientError as e:
            if not cond_failed(e):
                raise
            user = T_USERS.get_item(Key={"pk": username}, ConsistentRead=True).get("Item")
            if not user:
                raise ValueError("unknown user")
            cur = user.get("active_ride")
            old = T_RIDES.get_item(Key={"pk": cur}).get("Item") if cur else None
            if attempt == 0 and old and old["ride_status"] == "COMPLETED":
                T_USERS.update_item(Key={"pk": username}, UpdateExpression="REMOVE active_ride")  # stale lock
                continue
            raise ValueError("you already have an active ride")
    try:
        T_RIDES.put_item(Item={"pk": rid, "rider": username, "from_station": a, "to_station": b,
                               "ride_status": "WAITING", "created_ms": now_ms()})
    except Exception:
        T_USERS.update_item(Key={"pk": username}, UpdateExpression="REMOVE active_ride")
        raise
    _cache["t"] = 0.0


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
        "direction": "clockwise (S01 to S%02d, then S01)" % logic.STATIONS,
        "stations": logic.STATIONS,
        "stop_seconds": logic.STOP_S,
        "travel_seconds": logic.TRAVEL_S,
        "phase": s["phase"],
        "remaining_seconds": round(remaining, 1),
        "capacity": logic.CAPACITY,
        "on_board": len(on_board),
        "on_board_ids": on_board,
        "free_seats": logic.CAPACITY - len(on_board),
        "waiting": waiting,
    }


def ride_summary(r):
    a, b = int(r["from_station"]), int(r["to_station"])
    return {"status": r["ride_status"], "from_station": a, "to_station": b, "path": logic.route(a, b)}


def my_view(username):
    u = T_USERS.get_item(Key={"pk": username}, ConsistentRead=True)["Item"]
    ride = None
    last = None
    rid = u.get("active_ride")
    if rid:
        r = T_RIDES.get_item(Key={"pk": rid}, ConsistentRead=True).get("Item")
        if r and r["ride_status"] in ACTIVE:
            s, remaining = snapshot()
            target = int(r["from_station"]) if r["ride_status"] == "WAITING" else int(r["to_station"])
            ride = ride_summary(r)
            ride["eta_station"] = target
            ride["eta_seconds"] = round(logic.eta_seconds(target, s["station"], s["phase"], remaining))
    lid = u.get("last_ride")
    if lid:
        r = T_RIDES.get_item(Key={"pk": lid}).get("Item")
        if r and r["ride_status"] == "COMPLETED":
            last = ride_summary(r)
    return {"username": username, "ride": ride, "last_ride": last}


# ---------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _raw(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 10000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _user(self):
        h = self.headers.get("Authorization", "")
        return session_user(h[7:]) if h.startswith("Bearer ") else None

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/state":
                self._json(200, public_view())
            elif path == "/api/me":
                u = self._user()
                if not u:
                    self._json(401, {"error": "not logged in"})
                else:
                    self._json(200, my_view(u))
            elif path == "/health":
                self._raw(200, b"ok", "text/plain")
            else:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    self._raw(200, f.read(), "text/html; charset=utf-8")
        except Exception as e:
            print("GET error:", e)
            self._json(500, {"error": "server error"})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            d = self._body()
            if path == "/api/register":
                register(d.get("username"), d.get("password"))
                self._json(201, {"ok": True})
            elif path == "/api/login":
                self._json(200, {"token": login(d.get("username"), d.get("password"))})
            elif path == "/api/logout":
                h = self.headers.get("Authorization", "")
                if h.startswith("Bearer "):
                    T_SESSIONS.delete_item(Key={"pk": h[7:]})
                self._json(200, {"ok": True})
            elif path == "/api/ride":
                u = self._user()
                if not u:
                    raise PermissionError("not logged in")
                create_ride(u, d.get("from_station"), d.get("to_station"))
                self._json(201, my_view(u))
            else:
                self._json(404, {"error": "not found"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except PermissionError as e:
            self._json(401, {"error": str(e)})
        except Exception as e:
            print("POST error:", e)
            self._json(500, {"error": "server error"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    init_state()
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
