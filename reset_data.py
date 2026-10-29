#!/usr/bin/env python3
"""Clears the tram data after you changed the rules (e.g. fewer stations).

Why: rides to a removed station can never finish and would block seats forever,
and the tram may still stand at a station that no longer exists.

Usage:  python3 reset_data.py [stack-name] [--keep-users]
  default      : deletes tram state, rides, sessions AND users (accounts must be registered again)
  --keep-users : keeps the accounts, only clears their active/last ride
The tram restarts at S01 about 1 second later (the worker re-creates its state).
"""
import os, sys
import boto3

args = [a for a in sys.argv[1:] if not a.startswith("--")]
keep_users = "--keep-users" in sys.argv
stack = args[0] if args else "tram"
region = os.environ.get("AWS_REGION", "us-east-1")

cf = boto3.client("cloudformation", region_name=region)
outs = {o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]}
ddb = boto3.resource("dynamodb", region_name=region)


def items(table):
    kw = {}
    while True:
        r = table.scan(**kw)
        for it in r["Items"]:
            yield it
        if "LastEvaluatedKey" not in r:
            return
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def clear(output_key):
    table = ddb.Table(outs[output_key])
    n = 0
    for it in list(items(table)):
        table.delete_item(Key={"pk": it["pk"]})
        n += 1
    print("%-14s %d items deleted" % (output_key, n))


for key in ("RidesTable", "SessionsTable", "StateTable"):
    clear(key)
if keep_users:
    users = ddb.Table(outs["UsersTable"])
    n = 0
    for it in list(items(users)):
        users.update_item(Key={"pk": it["pk"]}, UpdateExpression="REMOVE active_ride, last_ride")
        n += 1
    print("%-14s %d accounts kept, rides cleared" % ("UsersTable", n))
else:
    clear("UsersTable")
print("done - the tram restarts at S01")
