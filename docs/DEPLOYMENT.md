# Deployment

Everything is created from the repository. No manual clicking in the console.

## Prerequisites
- An AWS account or Pluralsight AWS sandbox, permission for CloudFormation, EC2, DynamoDB, IAM roles, S3
- AWS CloudShell (has AWS CLI, Python 3, boto3, git)

## First deployment (about 5 minutes)

```bash
git clone https://github.com/<USER>/<REPO>.git
cd <REPO>
bash deploy.sh
```

`deploy.sh` does, in this order, and stops at the first error:
1. runs **all tests** - if one fails: `TESTS FAILED - DELIVERY BLOCKED`, nothing is changed in AWS
2. creates the S3 bucket (once), blocks public access, uploads `app/`
3. finds the default VPC and subnet
4. `aws cloudformation deploy` (tables, IAM role, security group, EC2)
5. (only if the stack already existed) reboots the instance so it loads the new code
6. prints `PUBLIC URL`

## Verify after deployment

```bash
URL=http://<PUBLIC_IP>
bash smoke_test.sh $URL                    # public view, login, ride, max one active ride
python3 capacity_test.py $URL              # capacity, FIFO, COMPLETED, new ride (3-5 min)
python3 restart_test.py $URL               # reboots the instance, state must survive (2-3 min)
```

## Update (code or rules changed)

```bash
git pull            # or edit files
bash deploy.sh      # tests -> upload -> deploy -> reboot
```

## Roll back

```bash
git log --oneline
git checkout <good-commit> -- app/ template.yaml tests/
bash deploy.sh
```

## Remove everything

```bash
aws cloudformation delete-stack --stack-name tram
aws cloudformation wait stack-delete-complete --stack-name tram
aws s3 rb s3://tram-artifacts-<ACCOUNT>-<REGION> --force
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `CREATE_FAILED` | `aws cloudformation describe-stack-events --stack-name tram --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output table` |
| IAM role not allowed in the sandbox | ask for a sandbox with IAM permissions; the role is required for DynamoDB access without keys |
| URL does not open | wait 1-2 minutes after deploy/reboot; the security group must allow TCP 80 |
| Page loads but "No connection" | instance role cannot reach DynamoDB or the table names are wrong: redeploy the stack |
| Tests fail on a rule change | expected: update `TestRequirements` in `tests/test_logic.py` (see CHANGING_THE_RULES.md) |
