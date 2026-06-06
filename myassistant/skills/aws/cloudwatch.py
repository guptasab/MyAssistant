"""AWS CloudWatch skill — query logs, run Insights, list groups."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from myassistant.core.registry import skill
from myassistant.core.config import settings

_REQUIRES = ["aws_access_key_id", "aws_secret_access_key"]


def _client(service: str):
    import boto3
    return boto3.client(
        service,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=getattr(settings, "aws_region", "us-east-1"),
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ago_ms(minutes: int) -> int:
    return _now_ms() - minutes * 60 * 1000


@skill(name="cw_list_groups",
       description="List CloudWatch log groups matching an optional prefix",
       parameters={"prefix": {"type": "string", "default": ""},
                   "limit": {"type": "integer", "default": 30}},
       requires=_REQUIRES)
def cw_list_groups(prefix: str = "", limit: int = 30) -> str:
    cw = _client("logs")
    kwargs = {"limit": limit}
    if prefix:
        kwargs["logGroupNamePrefix"] = prefix
    resp = cw.describe_log_groups(**kwargs)
    groups = [g["logGroupName"] for g in resp.get("logGroups", [])]
    return "\n".join(groups) or "(no log groups found)"


@skill(name="cw_filter_logs",
       description="Filter CloudWatch logs by pattern in the last N minutes",
       parameters={"group": {"type": "string",
                             "description": "Log group name, e.g. /aws/lambda/my-function"},
                   "pattern": {"type": "string", "default": "",
                               "description": "Filter pattern (CloudWatch syntax)"},
                   "minutes": {"type": "integer", "default": 60},
                   "limit": {"type": "integer", "default": 50}},
       requires=_REQUIRES)
def cw_filter_logs(group: str, pattern: str = "", minutes: int = 60, limit: int = 50) -> str:
    cw = _client("logs")
    kwargs: dict = dict(
        logGroupName=group,
        startTime=_ago_ms(minutes),
        endTime=_now_ms(),
        limit=limit,
    )
    if pattern:
        kwargs["filterPattern"] = pattern
    try:
        resp = cw.filter_log_events(**kwargs)
    except Exception as e:
        return f"ERROR: {e}"
    events = resp.get("events", [])
    if not events:
        return f"(no events in {group} last {minutes}min with pattern={pattern!r})"
    lines = []
    for e in events:
        ts = datetime.fromtimestamp(e["timestamp"] / 1000, tz=timezone.utc).strftime("%H:%M:%S")
        msg = e["message"].rstrip()[:200]
        lines.append(f"[{ts}] {msg}")
    return "\n".join(lines)


@skill(name="cw_insights_query",
       description="Run a CloudWatch Logs Insights query",
       parameters={"group": {"type": "string"},
                   "query": {"type": "string",
                             "description": "Insights query, e.g. 'fields @timestamp, @message | sort @timestamp desc | limit 20'"},
                   "minutes": {"type": "integer", "default": 60}},
       requires=_REQUIRES)
def cw_insights_query(group: str, query: str, minutes: int = 60) -> str:
    cw = _client("logs")
    now = int(time.time())
    start_resp = cw.start_query(
        logGroupName=group,
        startTime=now - minutes * 60,
        endTime=now,
        queryString=query,
        limit=50,
    )
    query_id = start_resp["queryId"]
    # Poll up to 30s
    for _ in range(30):
        time.sleep(1)
        result = cw.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
    if result["status"] != "Complete":
        return f"Query status: {result['status']}"
    rows = result.get("results", [])
    if not rows:
        return "(no results)"
    lines = []
    for row in rows[:40]:
        parts = {f["field"]: f["value"] for f in row}
        lines.append(json.dumps(parts, default=str))
    return "\n".join(lines)


@skill(name="cw_error_summary",
       description="Summarise ERROR/EXCEPTION lines in a log group over last N minutes",
       parameters={"group": {"type": "string"},
                   "minutes": {"type": "integer", "default": 60}},
       requires=_REQUIRES)
def cw_error_summary(group: str, minutes: int = 60) -> str:
    errors = cw_filter_logs(group, pattern="?ERROR ?Exception ?FATAL ?Traceback", minutes=minutes, limit=100)
    if errors.startswith("(no events"):
        return f"✅ No errors in {group} last {minutes}min"
    lines = errors.splitlines()
    return f"Found {len(lines)} error-related events in last {minutes}min:\n" + "\n".join(lines[:20])
