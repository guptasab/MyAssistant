"""AWS Lambda inspection skills (read-only + log tail)."""
from __future__ import annotations

import json
from myassistant.core.registry import skill
from myassistant.core.config import settings
from myassistant.skills.aws.cloudwatch import cw_filter_logs, cw_insights_query

_REQUIRES = ["aws_access_key_id", "aws_secret_access_key"]


def _lambda():
    import boto3
    return boto3.client(
        "lambda",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=getattr(settings, "aws_region", "us-east-1"),
    )


@skill(name="lambda_list",
       description="List deployed Lambda functions",
       parameters={"prefix": {"type": "string", "default": ""},
                   "limit": {"type": "integer", "default": 30}},
       requires=_REQUIRES)
def lambda_list(prefix: str = "", limit: int = 30) -> str:
    lam = _lambda()
    resp = lam.list_functions(MaxItems=limit)
    fns = resp.get("Functions", [])
    if prefix:
        fns = [f for f in fns if f["FunctionName"].startswith(prefix)]
    if not fns:
        return "(no functions found)"
    lines = []
    for f in fns:
        lines.append(f"{f['FunctionName']:40s} {f['Runtime']:12s} {f.get('LastModified','')[:10]}")
    return "\n".join(lines)


@skill(name="lambda_get_config",
       description="Get config and last deployment info for a Lambda function",
       parameters={"name": {"type": "string"}},
       requires=_REQUIRES)
def lambda_get_config(name: str) -> str:
    lam = _lambda()
    try:
        f = lam.get_function(FunctionName=name)["Configuration"]
        return json.dumps({
            "name": f["FunctionName"],
            "runtime": f.get("Runtime"),
            "memory_mb": f.get("MemorySize"),
            "timeout_s": f.get("Timeout"),
            "last_modified": f.get("LastModified"),
            "code_size_bytes": f.get("CodeSize"),
            "description": f.get("Description"),
            "handler": f.get("Handler"),
        }, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


@skill(name="lambda_tail_logs",
       description="Tail recent CloudWatch logs for a Lambda function",
       parameters={"name": {"type": "string"},
                   "minutes": {"type": "integer", "default": 30},
                   "pattern": {"type": "string", "default": ""}},
       requires=_REQUIRES)
def lambda_tail_logs(name: str, minutes: int = 30, pattern: str = "") -> str:
    group = f"/aws/lambda/{name}"
    return cw_filter_logs(group, pattern=pattern, minutes=minutes, limit=50)


@skill(name="lambda_find_errors",
       description="Find errors in Lambda logs — returns stack traces",
       parameters={"name": {"type": "string"},
                   "minutes": {"type": "integer", "default": 60}},
       requires=_REQUIRES)
def lambda_find_errors(name: str, minutes: int = 60) -> str:
    group = f"/aws/lambda/{name}"
    query = """fields @timestamp, @message
| filter @message like /ERROR|Exception|Traceback|FATAL/
| sort @timestamp desc
| limit 25"""
    return cw_insights_query(group, query, minutes=minutes)
