"""Pure functions (no AWS) - easy to unit test."""
STATIONS = 16
STOP_S = 3
TRAVEL_S = 5
CAPACITY = 12  # Milestone 4: maximum 12 passengers


def phase_ms(phase):
    return (STOP_S if phase == "STOPPED" else TRAVEL_S) * 1000


def next_station(s):
    return s % STATIONS + 1


def route(a, b):
    """Stations a tram passes from a to b (inclusive), always forward around the loop."""
    if not (1 <= a <= STATIONS and 1 <= b <= STATIONS):
        raise ValueError("station out of range 1-%d" % STATIONS)
    path = [a]
    while path[-1] != b:
        path.append(next_station(path[-1]))
    return path


def eta_seconds(target, station, phase, remaining):
    """Seconds until the tram is stopped at `target`.
    station/phase/remaining = current tram state (remaining = seconds left in phase)."""
    if phase == "STOPPED":
        if target == station:
            return 0
        d = (target - station) % STATIONS  # 1..15
        return remaining + TRAVEL_S + (d - 1) * (STOP_S + TRAVEL_S)
    # TRAVELING from `station` to next_station(station)
    nxt = next_station(station)
    d = (target - nxt) % STATIONS  # 0..15
    return remaining + d * (STOP_S + TRAVEL_S)


def select_boarders(waiting, free):
    """FIFO: the earliest ride requests board first, at most `free` of them."""
    if free <= 0:
        return []
    return sorted(waiting, key=lambda r: (int(r["created_ms"]), r["pk"]))[:free]


def anon_id(ride_id):
    """Public anonymous identifier - derived from the ride id, never from the username."""
    return "P-" + ride_id[:4].upper()
