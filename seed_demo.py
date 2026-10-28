#!/usr/bin/env python3
"""Milestone 2 demo helper: adds anonymous demo passengers (WAITING rides) so the public view has data.
(Registration and personal rides come in Milestone 3.)

Usage:  python3 seed_demo.py <RIDES_TABLE_NAME> [count]
Table name:  aws cloudformation describe-stacks --stack-name tram \
             --query "Stacks[0].Outputs[?OutputKey=='RidesTable'].OutputValue" --output text
"""
import os, random, secrets, sys, time
import boto3

if len(sys.argv) < 2:
    sys.exit(__doc__)
table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(sys.argv[1])
count = int(sys.argv[2]) if len(sys.argv) > 2 else 8
for i in range(count):
    a = random.randint(1, 16)
    b = random.choice([s for s in range(1, 17) if s != a])
    rid = secrets.token_hex(8)
    table.put_item(Item={"pk": rid, "rider": "demo-" + rid[:4], "from_station": a, "to_station": b,
                         "ride_status": "WAITING", "created_ms": int(time.time() * 1000) + i})
    print("demo passenger P-%s waiting at S%02d" % (rid[:4].upper(), a))
