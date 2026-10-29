"""Tiny in-memory stand-in for the DynamoDB Table API used by app/app.py.
It lets the tests run the REAL application code without AWS. It only understands the
expressions the app uses and raises NotImplementedError for anything else, so a new kind of
expression cannot slip through unnoticed. Numbers come back as Decimal, like in real DynamoDB."""
import copy
import re
from decimal import Decimal

from botocore.exceptions import ClientError


def _to_ddb(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_ddb(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_ddb(x) for x in v]
    return v


def _failed(op):
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException",
                                  "Message": "The conditional request failed"}}, op)


class FakeStore:
    """The 'AWS account': survives when the application is restarted."""
    def __init__(self):
        self.tables = {}


class FakeDynamo:
    def __init__(self, store):
        self.store = store

    def Table(self, name):
        return FakeTable(self.store.tables.setdefault(name, {}))


class FakeTable:
    def __init__(self, items):
        self.items = items

    # -- conditions -------------------------------------------------------
    def _check(self, cond, cur, names, vals, op):
        if not cond:
            return
        cur = cur or {}
        names, vals = names or {}, vals or {}
        for c in re.split(r"\s+AND\s+", cond.strip()):
            m = re.fullmatch(r"attribute_not_exists\((\w+)\)", c)
            if m:
                ok = m.group(1) not in cur
            elif re.fullmatch(r"attribute_exists\((\w+)\)", c):
                ok = re.fullmatch(r"attribute_exists\((\w+)\)", c).group(1) in cur
            elif re.fullmatch(r"(#?\w+)\s*=\s*(:\w+)", c):
                n, ref = re.fullmatch(r"(#?\w+)\s*=\s*(:\w+)", c).groups()
                ok = names.get(n, n) in cur and cur[names.get(n, n)] == _to_ddb(vals[ref])
            else:
                raise NotImplementedError("fake DynamoDB does not know: " + c)
            if not ok:
                raise _failed(op)

    # -- API ----------------------------------------------------------------
    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get(Key["pk"])
        return {"Item": copy.deepcopy(it)} if it is not None else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None,
                 ExpressionAttributeValues=None):
        self._check(ConditionExpression, self.items.get(Item["pk"]), ExpressionAttributeNames,
                    ExpressionAttributeValues, "PutItem")
        self.items[Item["pk"]] = _to_ddb(copy.deepcopy(Item))
        return {}

    def delete_item(self, Key):
        self.items.pop(Key["pk"], None)
        return {}

    def update_item(self, Key, UpdateExpression, ConditionExpression=None,
                    ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        names, vals = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        cur = self.items.get(Key["pk"])
        self._check(ConditionExpression, cur, names, vals, "UpdateItem")
        item = copy.deepcopy(cur) if cur is not None else {"pk": Key["pk"]}
        for kind, body in re.findall(r"(SET|REMOVE)\s+(.*?)(?=\s+(?:SET|REMOVE)\s|$)", UpdateExpression.strip()):
            for part in [p.strip() for p in body.split(",")]:
                if kind == "SET":
                    attr, ref = [x.strip() for x in part.split("=")]
                    item[names.get(attr, attr)] = _to_ddb(vals[ref])
                else:
                    item.pop(names.get(part, part), None)
        self.items[Key["pk"]] = item
        return {}

    def scan(self, FilterExpression=None, ExclusiveStartKey=None):
        out = []
        for it in self.items.values():
            if FilterExpression is not None:
                exp = FilterExpression.get_expression()
                attr, allowed = exp["values"]
                if exp["operator"] != "IN":
                    raise NotImplementedError("fake DynamoDB scan only knows IN")
                if it.get(attr.name) not in allowed:
                    continue
            out.append(copy.deepcopy(it))
        return {"Items": out}
