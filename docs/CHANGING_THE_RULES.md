# Changing the rules (stations, timing, capacity)

All simulation rules live in **one place**: `app/logic.py`

```python
STATIONS = 16   # number of stations on the loop
STOP_S = 3      # seconds the tram stands still at a station
TRAVEL_S = 5    # seconds of travel to the next station
CAPACITY = 12   # maximum passengers on board (free seats = CAPACITY - on board)
```

Everything else reads these values: the worker, the boarding rule, the ETA, ride validation and the
web page (it asks `/api/state` how many stations there are and draws the line itself).

## What changes where

| I want to change | Edit | Effect |
|---|---|---|
| number of stations (16 -> 15) | `STATIONS` | tram loops S01..S15; page draws 15 stations; station pickers have 15 entries |
| stop time / travel time | `STOP_S`, `TRAVEL_S` | loop length = STATIONS x (STOP_S + TRAVEL_S); ETA and countdowns follow |
| passenger limit (12 -> 20, or 10) | `CAPACITY` | boarding stops when full; the page shows free seats = CAPACITY - on board |

"Free seats" is not a separate setting. It is always `CAPACITY - passengers on board`.

## Step by step (example: 15 stations, capacity 10)

1. Open CloudShell and go to the project folder: `cd ~/tram`
2. Edit the rules: `nano app/logic.py` (change the numbers, `Ctrl+O`, `Enter`, `Ctrl+X`)
   or in one command:
   ```bash
   sed -i 's/^STATIONS = .*/STATIONS = 15/; s/^CAPACITY = .*/CAPACITY = 10/' app/logic.py
   head -6 app/logic.py
   ```
3. Run the tests. **Two requirement tests now fail on purpose**, because the assignment rules in
   `TestRequirements` are written as plain numbers:
   ```bash
   python3 -m unittest discover -s tests -v
   ```
4. Update the numbers in `tests/test_logic.py`, class `TestRequirements`
   (`logic.STATIONS, 15` and `logic.CAPACITY, 10`) and run the tests again: all green.
   All other tests use the constants, so they follow automatically.
5. Deploy. `deploy.sh` runs the tests first, uploads `app/` to S3 and reboots the instance:
   ```bash
   bash deploy.sh
   ```
6. Reset old data (see below), then open the URL and check the page.
7. Optional live proof with the new values:
   ```bash
   python3 capacity_test.py http://<PUBLIC_IP> 10     # 10 = expected capacity
   ```

## Why old data must be reset

DynamoDB keeps the state from before the change. After shortening the line, a passenger who is on board
for station S16 can never get off, and the tram may be standing at a station that no longer exists.
Raising the capacity or changing the timing needs no reset, but a reset is harmless.

```bash
python3 reset_data.py               # deletes state, rides, sessions and accounts
python3 reset_data.py --keep-users  # keeps accounts, clears their rides
```
The tram starts again at S01 about one second later.

## Quick calculations

```bash
python3 -c "import sys; sys.path.insert(0,'app'); import logic as l; print(l.STATIONS*(l.STOP_S+l.TRAVEL_S), 'seconds per lap')"
```

## Things to know

- Keep `STOP_S` and `TRAVEL_S` at 1 second or more (the worker checks 4 times per second).
- The circle on the page stays readable up to about 30 stations.
- Rules are code, not runtime settings: every change goes through test -> deploy, so it is tracked in git.
  ```bash
  git add . && git commit -m "Rules: 15 stations, capacity 10" && git push
  ```
- To go back to the assignment values: `git checkout app/logic.py tests/test_logic.py`, then `bash deploy.sh`.
