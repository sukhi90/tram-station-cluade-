# Recovery

Principle: **all state is in DynamoDB, all code is in git, all infrastructure is in the template.**
The instance itself can be lost at any time.

| What happened | Effect | Recovery |
|---|---|---|
| Python process crashes | tram pauses for about 3 s | systemd `Restart=always` starts it again; state resumes |
| Instance reboots | page unavailable 1-2 min | service starts at boot (`enabled`); tram, rides and logins continue (`restart_test.py` proves it) |
| Instance is lost / replaced | page unavailable | `bash deploy.sh` (or update the stack): new instance, same tables, state continues |
| Bad release | wrong behaviour | `git checkout <good-commit> -- app/ template.yaml tests/` then `bash deploy.sh` |
| Sandbox expires (account gone) | everything deleted | new sandbox: `git clone`, `bash deploy.sh`, then restore the data backup (below) |
| Tables deleted by mistake | state lost | redeploy the stack and restore the backup |

## Data backup and restore (for the "sandbox break" case)

```bash
python3 data_backup.py export backup.json     # tram state, accounts, rides -> one file
# CloudShell: Actions -> Download file -> backup.json   (keep it safe, it contains password hashes)

# new sandbox, after bash deploy.sh:
# Actions -> Upload file -> backup.json
python3 data_backup.py import backup.json
```
After a restore the tram continues at the saved station. A long gap is not replayed.
Logins (sessions) are not restored: people log in again.

## Test the recovery

```bash
python3 restart_test.py http://<PUBLIC_IP>
```
It registers a user, requests a ride, **reboots the instance**, waits for the page and checks:
the tram continued (did not restart at S01), the login token still works, the ride is still there.

After a rule change, old data can be wiped with `python3 reset_data.py`.
