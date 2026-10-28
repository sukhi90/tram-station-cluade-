# Tram circular route (AWS)

A simulated tram runs a loop over 16 stations (S01 to S16, then S01): 3 seconds stop, 5 seconds travel.
Guests see a live public view. Registered passengers request a personal ride (start + destination) and
follow WAITING -> ON_BOARD -> COMPLETED live. Everything runs on AWS and is deployed from this repository.

## Architecture

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
python3 -m unittest discover -s tests -v   # tests run first
bash deploy.sh                              # tests + S3 upload + CloudFormation; prints PUBLIC URL
```

## Verify

```bash
bash smoke_test.sh http://<PUBLIC_IP>        # register, login, ride, max one active ride
python3 capacity_test.py http://<PUBLIC_IP>  # 12 passengers max, FIFO, COMPLETED, new ride (~5 min)
```

## Restart / recovery

```bash
aws ec2 reboot-instances --instance-ids <INSTANCE_ID>   # tram and rides continue where they were
```

Full walkthrough: [docs/STEP_BY_STEP.md](docs/STEP_BY_STEP.md)

## Clean up

```bash
aws cloudformation delete-stack --stack-name tram
```
(the S3 bucket `tram-artifacts-<account>-<region>` is created by `deploy.sh` and can be emptied and deleted separately)

## Known limits

HTTP only (no TLS), single instance, DynamoDB Scan for the ride list (fine at this size).
