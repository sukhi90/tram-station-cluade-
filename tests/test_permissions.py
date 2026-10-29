"""Least privilege, checked automatically: the IAM role in template.yaml must grant exactly the
DynamoDB / S3 actions the application code really uses - not one more, not one less."""
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


TEMPLATE = read("template.yaml")
APP = read("app", "app.py")

CALL_TO_ACTION = {"get_item": "dynamodb:GetItem", "put_item": "dynamodb:PutItem",
                  "update_item": "dynamodb:UpdateItem", "delete_item": "dynamodb:DeleteItem",
                  "scan": "dynamodb:Scan"}
TABLE_OF = {"STATE": "StateTable", "USERS": "UsersTable", "SESSIONS": "SessionsTable", "RIDES": "RidesTable"}


def granted():
    """{table resource name: set(actions)} from the IAM statements."""
    out = {}
    for m in re.finditer(r"- Sid: \w+\s+Effect: Allow\s+Action: \[([^\]]*)\]\s+Resource: !GetAtt (\w+)\.Arn", TEMPLATE):
        out.setdefault(m.group(2), set()).update(a.strip() for a in m.group(1).split(","))
    return out


def used():
    out = {}
    for tab, call in re.findall(r"T_(STATE|USERS|SESSIONS|RIDES)\.(\w+)\(", APP):
        out.setdefault(TABLE_OF[tab], set()).add(CALL_TO_ACTION[call])
    return out


class TestLeastPrivilege(unittest.TestCase):
    def test_every_table_grant_matches_what_the_code_uses(self):
        self.assertEqual(granted(), used())

    def test_each_table_has_its_own_statement(self):
        self.assertEqual(set(granted()), {"StateTable", "UsersTable", "SessionsTable", "RidesTable"})

    def test_only_the_rides_table_may_be_scanned(self):
        scans = [t for t, a in granted().items() if "dynamodb:Scan" in a]
        self.assertEqual(scans, ["RidesTable"])

    def test_no_wildcards_in_the_role(self):
        policy = TEMPLATE[TEMPLATE.index("tram-least-privilege"):TEMPLATE.index("WorkerProfile:")]
        self.assertNotIn("'*'", policy)
        self.assertNotIn('"*"', policy)
        self.assertNotRegex(policy, r"Action:\s*\*")
        self.assertNotRegex(policy, r"Resource:\s*\*")
        self.assertNotIn(":*", policy.replace("arn:aws:s3:::${ArtifactBucket}/app/*", ""))

    def test_s3_access_is_read_only_and_limited_to_the_app_folder(self):
        policy = TEMPLATE[TEMPLATE.index("tram-least-privilege"):TEMPLATE.index("WorkerProfile:")]
        self.assertIn("Action: s3:GetObject\n                Resource: !Sub arn:aws:s3:::${ArtifactBucket}/app/*", policy)
        for forbidden in ("s3:PutObject", "s3:DeleteObject", "s3:*"):
            self.assertNotIn(forbidden, policy)

    def test_role_can_only_be_assumed_by_ec2(self):
        trust = TEMPLATE[TEMPLATE.index("AssumeRolePolicyDocument"):TEMPLATE.index("tram-least-privilege")]
        self.assertIn("ec2.amazonaws.com", trust)
        self.assertEqual(trust.count("Service:"), 1)


class TestNetwork(unittest.TestCase):
    def test_only_http_is_open_and_ssh_is_not(self):
        sg = TEMPLATE[TEMPLATE.index("WorkerSG:"):TEMPLATE.index("WorkerInstance:")]
        self.assertEqual(re.findall(r"FromPort: (\d+)", sg), ["80"])
        self.assertEqual(re.findall(r"ToPort: (\d+)", sg), ["80"])
        self.assertNotIn("22", re.findall(r"Port: (\d+)", sg))

    def test_no_credentials_in_the_code(self):
        for name in ("app.py", "logic.py", "index.html"):
            text = read("app", name)
            self.assertNotRegex(text, r"AKIA[0-9A-Z]{16}", name)
            self.assertNotIn("aws_secret_access_key", text.lower(), name)


class TestReproducibleDeployment(unittest.TestCase):
    def test_delivery_script_runs_tests_before_anything_else(self):
        script = read("deploy.sh")
        self.assertLess(script.index("unittest discover"), script.index("aws s3"))
        self.assertLess(script.index("unittest discover"), script.index("cloudformation deploy"))
        self.assertIn("exit 1", script)
        self.assertIn("set -euo pipefail", script)

    def test_infrastructure_is_defined_in_the_template(self):
        for resource in ("AWS::DynamoDB::Table", "AWS::IAM::Role", "AWS::EC2::SecurityGroup", "AWS::EC2::Instance"):
            self.assertIn(resource, TEMPLATE)

    def test_the_worker_is_a_restarting_service_started_at_boot(self):
        self.assertIn("Restart=always", TEMPLATE)
        self.assertIn("systemctl enable --now tram", TEMPLATE)


if __name__ == "__main__":
    unittest.main()
