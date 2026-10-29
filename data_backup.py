#!/usr/bin/env python3
"""Export / import of the tram data (tram state, accounts, rides) as ONE json file.
Use it before the sandbox ends, and to restore the data into a new sandbox after deploy.sh.

  python3 data_backup.py export backup.json [stack-name]
  python3 data_backup.py import backup.json [stack-name]

CloudShell: Actions -> Download file to keep backup.json on your computer.
The file contains password hashes: do NOT commit it to git (*.json backups are in .gitignore)."""
import json, os, sys
from decimal import Decimal
import boto3

if len(sys.argv) < 3 or sys.argv[1] not in ("export", "import"):
    sys.exit(__doc__)
mode, path = sys.argv[1], sys.argv[2]
stack = sys.argv[3] if len(sys.argv) > 3 else "tram"
region = os.environ.get("AWS_REGION", "us-east-1")
outs = {o["OutputKey"]: o["OutputValue"] for o in
        boto3.client("cloudformation", region_name=region).describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]}
ddb = boto3.resource("dynamodb", region_name=region)
TABLES = {"state": "StateTable", "users": "UsersTable", "rides": "RidesTable"}  # sessions are not worth keeping


def plain(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError(type(o))


if mode == "export":
    data = {}
    for key, out in TABLES.items():
        table, items, kw = ddb.Table(outs[out]), [], {}
        while True:
            r = table.scan(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        data[key] = items
        print("%-6s %d items" % (key, len(items)))
    json.dump(data, open(path, "w"), default=plain, indent=1)
    print("saved", path)
else:
    data = json.load(open(path))
    for key, out in TABLES.items():
        table = ddb.Table(outs[out])
        for it in data.get(key, []):
            table.put_item(Item=it)
        print("%-6s %d items restored" % (key, len(data.get(key, []))))
    print("done - the tram continues where the backup was taken")
