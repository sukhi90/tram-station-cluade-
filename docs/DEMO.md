# Demo and presentation guide (about 10 minutes)

## Before you present (do this in the morning, it takes 10 minutes)

1. New sandbox? `git clone ... && cd <repo> && bash deploy.sh` (5 min). Note the PUBLIC URL.
2. `bash smoke_test.sh http://<IP>` - everything must say OK.
3. Open in the browser: the public page (guest) and a second window for the passenger.
4. Have these open: `docs/architecture.png`, the GitHub repo, a CloudShell tab in the project folder.
5. **Fallback:** take screenshots / a short screen recording of the working system and of `python3 -m unittest discover -s tests`
   output. The sandbox can expire; the screenshots cannot.

## Storyline

| Min | What you show | What you say |
|---|---|---|
| 1 | Assignment in one sentence | A tram loops over 16 stations; guests watch live, passengers request personal rides. Everything runs on AWS. |
| 2 | `architecture.png` | EC2 runs one Python process as a systemd service. All state is in DynamoDB. CloudFormation creates everything. Code comes from S3. IAM role instead of keys. Only port 80 is open. |
| 3 | Public page | Position, direction, remaining time, on board, free seats, waiting per station. Updates every second. Only anonymous ids. |
| 4 | Register, log in, request S02 -> S05 | Status WAITING with ETA. When the tram stops at S02: ON_BOARD. At S05: COMPLETED with the journey path. Then a new ride is possible. Second request while active is rejected (maximum one). |
| 5 | `python3 capacity_test.py` output (or start it before) | 14 users, 12 board in FIFO order, the last two wait, board on the next lap. |
| 6 | `python3 restart_test.py` or `aws ec2 reboot-instances` | The instance is rebooted; the tram continues, logins and rides survive. State is in DynamoDB, not on the disk. |
| 7 | `python3 -m unittest discover -s tests -v` | 72 tests: timing, status changes, travel restrictions, restart, security, permissions. They run against the real code with a fake clock, a whole lap takes milliseconds. |
| 8 | Break a test on purpose, run `bash deploy.sh` | `TESTS FAILED - DELIVERY BLOCKED`. Nothing reaches AWS. |
| 9 | IAM section in `ARCHITECTURE.md` | Per table only the actions the code uses. A test compares the policy with the code. |
| 10 | Limits and next steps | HTTP only (production: ALB + TLS), single instance, Scan for rides (GSI), CloudWatch alarms. |

## Break-a-test demo (step 8)

```bash
sed -i 's/^STOP_S = .*/STOP_S = 4/' app/logic.py
bash deploy.sh                       # stops: TESTS FAILED - DELIVERY BLOCKED
git checkout app/logic.py            # back to the assignment values
```

## Live rule change demo (optional)

See [CHANGING_THE_RULES.md](CHANGING_THE_RULES.md): change `CAPACITY`, tests tell you to update the requirement, deploy, `reset_data.py`.

## Questions you may get

- *Why EC2 and not Lambda?* The assignment asks for a long-lived worker; the simulation loop runs continuously.
- *What if the instance dies?* Redeploy creates a new one; the state is in DynamoDB and the tram continues.
- *How do two requests for the last seat behave?* FIFO by request time; the worker boards one passenger at a time.
- *How do you prevent two active rides?* Conditional update on the user item; it is atomic in DynamoDB.
- *Where are passwords?* Salted PBKDF2 hash only; never plain text.
- *How do you know permissions are minimal?* A test compares the role with the real API calls.
- *What does a faulty test do?* `deploy.sh` stops before anything is uploaded; GitHub Actions runs the same tests on every push.
- *What would you improve?* TLS, multi-AZ, alarms, GSI, per-user rate limiting.
