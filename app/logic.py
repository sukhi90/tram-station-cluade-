"""Pure functions (no AWS) - easy to unit test."""
STATIONS = 16
STOP_S = 3
TRAVEL_S = 5
CAPACITY = 6  # seats in the tram


def phase_ms(phase):
    return (STOP_S if phase == "STOPPED" else TRAVEL_S) * 1000


def next_station(s):
    return s % STATIONS + 1


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


def anon_id(ride_id):
    """Public anonymous identifier - derived from the ride id, never from the username."""
    return "P-" + ride_id[:4].upper()
