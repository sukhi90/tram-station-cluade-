# Tram circular route (AWS)

A simulated tram runs a loop over 16 stations (S01 to S16, then S01): 3 seconds stop, 5 seconds travel.
Guests see a live public view. Registered passengers request a personal ride (start + destination) and
follow WAITING -> ON_BOARD -> COMPLETED live. Everything runs on AWS and is deployed from this repository.

## Architecture

![Architecture](docs/architecture.png)

```
Browser --HTTP:80--> EC2 (systemd service: worker + web server) --> DynamoDB (State, Users, Sessions, Rides)
                          ^
                          +-- app files pulled from S3 at service start (deploy.sh uploads them)
```

| Part | Purpose |
|---|---|
| CloudFormation `template.yaml` | creates tables, IAM role (least privilege), security group, EC2 |
| `app/app.py` | long-lived worker (simulation + boarding) and HTTP API |
| `app/logic.py` | pure rules: stations, timing, ETA, route, FIFO, capacity (12) |
| `app/index.html` | public live view, login, personal journey |
| DynamoDB | all state lives outside the worker file system, so a restart loses nothing |

## Quick start (AWS CloudShell)

```bash
git clone https://github.com/<USER>/<REPO>.git && cd <REPO>
bash deploy.sh        # runs the tests first (failure = no delivery), then S3 + CloudFormation; prints PUBLIC URL
```

## Tests

```bash
python3 -m unittest discover -s tests -v    # 72 tests, no AWS needed
bash smoke_test.sh http://<PUBLIC_IP>        # live: register, login, ride, max one active ride
python3 capacity_test.py http://<PUBLIC_IP>  # live: capacity limit, FIFO, COMPLETED, new ride (3-5 min)
python3 restart_test.py http://<PUBLIC_IP>   # live: reboots the instance, state must survive (2-3 min)
```

## Documentation

| | |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | diagram, components, data model, security |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | deploy, update, roll back, troubleshoot |
| [docs/RECOVERY.md](docs/RECOVERY.md) | restart, lost instance, sandbox break, backup/restore |
| [docs/DEMO.md](docs/DEMO.md) | presentation script and Q&A |
| [docs/CHANGING_THE_RULES.md](docs/CHANGING_THE_RULES.md) | stations, timing, capacity |
| [docs/STEP_BY_STEP.md](docs/STEP_BY_STEP.md) | how the project was built, milestone by milestone |

## Helper scripts

`reset_data.py` clears data after a rule change, `data_backup.py` exports/imports the data, `docs/architecture_diagram.py` redraws the diagram.

## Clean up

```bash
aws cloudformation delete-stack --stack-name tram
```
(the S3 bucket `tram-artifacts-<account>-<region>` is created by `deploy.sh` and can be emptied and deleted separately)

## Known limits

HTTP only (no TLS), single instance, DynamoDB Scan for the ride list (fine at this size).
