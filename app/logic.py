"""Pure functions (no AWS) - easy to unit test."""
STATIONS = 16
STOP_S = 3
TRAVEL_S = 5
CAPACITY = 6  # seats in the tram


def phase_ms(phase):
    return (STOP_S if phase == "STOPPED" else TRAVEL_S) * 1000


def next_station(s):
    return s % STATIONS + 1


def anon_id(ride_id):
    """Public anonymous identifier - derived from the ride id, never from the username."""
    return "P-" + ride_id[:4].upper()
