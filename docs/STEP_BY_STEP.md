# How the project was built, step by step

Environment: Pluralsight AWS Cloud Sandbox, AWS CloudShell, AWS CLI, Python 3 (boto3), CloudFormation.

## Step 0 - Setup

1. Start the AWS sandbox, open the AWS Console, stay in the sandbox region (usually `us-east-1`).
2. Open **CloudShell** (the `>_` icon).
3. Get the project: `git clone https://github.com/<USER>/<REPO>.git && cd <REPO>`

Helper used below to read stack outputs:

```bash
OUT() { aws cloudformation describe-stacks --stack-name tram \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
```

## Milestone 1 - Walkable environment (a tram runs in a loop, state survives a restart)

| Requirement | Solution |
|---|---|
| Resources provisioned from project files | CloudFormation `template.yaml`, started by `deploy.sh` |
| 16 stations, 3 s stop, 5 s travel | `logic.py` constants, worker loop in `app.py` |
| Public page shows line and status | `GET /` (page) and `GET /api/state` |
| State outside worker file system | DynamoDB table; worker stores `station`, `phase`, `phase_start_ms` |

Key design decisions
- The phase start is stored as an **absolute timestamp**, so after a restart the worker computes the remaining time correctly.
- The worker runs as a **systemd service** (`Restart=always`, enabled at boot) = long-lived worker.
- Startup uses a conditional `put_item` (`attribute_not_exists`): existing state is **resumed**, never overwritten.
- State changes use a conditional update, so two workers can never advance the tram twice.
- IAM role allows only DynamoDB item operations on the four tables and read access to the app files in S3.
- Only port 80 is open. There is no SSH.

Verify
```bash
python3 -m unittest discover -s tests -v
bash deploy.sh
curl http://<PUBLIC_IP>/api/state
aws dynamodb get-item --table-name "$(OUT StateTable)" --key '{"pk":{"S":"tram-1"}}'
aws ec2 reboot-instances --instance-ids "$(OUT InstanceId)"    # wait 1-2 min, tram continues
```

## Milestone 2 - Public live operations view

| Requirement | Solution |
|---|---|
| Position, direction, remaining time | `/api/state`: `station`, `next_station`, `direction`, `remaining_seconds` |
| On board, free seats, waiting per station | `on_board`, `free_seats`, `waiting` (computed from the Rides table) |
| Continuous updates | page polls the API every second, no manual reload |
| Only anonymous identifiers | public view uses `P-XXXX` derived from the ride id, never the username |

Verify: open the URL without logging in; run `curl http://<PUBLIC_IP>/api/state` and check no username appears.

## Milestone 3 - Passenger account and entry phase

| Requirement | Solution |
|---|---|
| Registration and login | `/api/register`, `/api/login`; password stored as salted PBKDF2-SHA256 hash; session token with 24 h TTL in DynamoDB |
| Start/destination, max one active ride | `POST /api/ride`; atomic conditional update on the user item (`attribute_not_exists(active_ride)`) |
| WAITING and ETA | `GET /api/me`; ETA computed by `logic.eta_seconds` (unit tested) |
| Stop at start station -> ON_BOARD | worker checks the stopped station every 0.25 s and boards waiting rides (idempotent) |

Verify
```bash
bash smoke_test.sh http://<PUBLIC_IP>
```
The second ride request of the same user must be rejected.

## Milestone 4 - Trip end and repeated use

| Requirement | Solution |
|---|---|
| Exit at destination sets COMPLETED | worker alights passengers whose destination is the stopped station and sets `COMPLETED` |
| Comprehensible journey path | personal view shows the path S08 -> S09 -> ... -> S13, progress marks, and the path highlighted on the route circle; after arrival a "COMPLETED" summary |
| Max 12 passengers, FIFO | `CAPACITY = 12`; `logic.select_boarders` boards the earliest requests first; later ones keep WAITING |
| New ride after COMPLETED | completing a ride removes `active_ride` from the user (and keeps `last_ride` for the summary) |

Verify
```bash
python3 -m unittest discover -s tests -v          # 72 tests, includes FIFO, capacity, restart, permissions
bash deploy.sh                                     # redeploys and reboots the instance
python3 capacity_test.py http://<PUBLIC_IP>        # live proof: 12 on board, 2 waiting, COMPLETED, new ride
```

## Update workflow

Edit files in `app/`, run `bash deploy.sh`. It runs the tests first (a failing test stops the delivery),
uploads `app/` to S3, deploys the stack and reboots the instance so it loads the new version.

## Git history (one commit per step)

```bash
git log --oneline
```

## Milestone 5 - Release candidate: securely and verifiably operated

| Requirement | Solution |
|---|---|
| Tests for clock speed, status changes, travel restrictions, restart | `tests/test_app.py`: the real `app.py` runs against an in-memory DynamoDB and a fake clock (a 128 s lap in milliseconds). Classes: `TestClockSpeed`, `TestStatusChanges`, `TestTravelRestrictions`, `TestRestart`, `TestSecurityAndPrivacy`, `TestHttpApi` |
| Faulty tests prevent delivery | `deploy.sh` runs the tests first and exits before touching AWS; GitHub Actions runs them on every push |
| Minimum permissions | per-table IAM actions; `tests/test_permissions.py` compares the policy with the calls in `app.py`; port 80 only; S3 read-only on `app/*`; no keys |
| Reproducible deployment | `bash deploy.sh` from a clean clone: tests, S3, CloudFormation |
| Documentation | `docs/ARCHITECTURE.md`, `DEPLOYMENT.md`, `RECOVERY.md`, `DEMO.md`, architecture diagram |

Verify
```bash
python3 -m unittest discover -s tests -v
python3 restart_test.py http://<PUBLIC_IP>        # live: reboots the instance
python3 data_backup.py export backup.json          # sandbox-break safety copy
```

Bug found by the new tests: a ride request from an unknown user returned a server error instead of a clean 400.

## Changing the rules

See [CHANGING_THE_RULES.md](CHANGING_THE_RULES.md).
