"""AWS X-Ray — trace search and detail for production debugging."""
from __future__ import annotations

import json
import time

from myassistant.core.registry import skill
from myassistant.core.config import settings

_REQUIRES = ["aws_access_key_id", "aws_secret_access_key"]


def _xray():
    import boto3
    return boto3.client(
        "xray",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=getattr(settings, "aws_region", "us-east-1"),
    )


@skill(name="xray_traces",
       description="Get X-Ray traces with errors for a service in last N minutes",
       parameters={"service": {"type": "string", "default": "",
                               "description": "Service name filter (empty = all)"},
                   "minutes": {"type": "integer", "default": 30},
                   "errors_only": {"type": "boolean", "default": True}},
       requires=_REQUIRES)
def xray_traces(service: str = "", minutes: int = 30, errors_only: bool = True) -> str:
    xr = _xray()
    end = time.time()
    start = end - minutes * 60
    filter_expr = "error = true" if errors_only else "responsetime > 0"
    if service:
        filter_expr += f' AND service(id(name: "{service}"))'
    try:
        resp = xr.get_trace_summaries(
            StartTime=start, EndTime=end,
            Sampling=False,
            FilterExpression=filter_expr,
        )
    except Exception as e:
        return f"ERROR: {e}"
    summaries = resp.get("TraceSummaries", [])
    if not summaries:
        return f"(no {'error ' if errors_only else ''}traces in last {minutes}min)"
    lines = []
    for t in summaries[:20]:
        tid = t.get("Id", "")
        dur = f"{t.get('Duration', 0):.3f}s"
        err = "🔴 ERROR" if t.get("HasError") else ("🟡 FAULT" if t.get("HasFault") else "🟢 OK")
        svc = ",".join(s.get("Name", "") for s in t.get("ServiceIds", []))
        lines.append(f"{tid} {dur} {err} [{svc}]")
    return "\n".join(lines)


@skill(name="xray_get_trace",
       description="Get full X-Ray trace detail including segments",
       parameters={"trace_id": {"type": "string"}},
       requires=_REQUIRES)
def xray_get_trace(trace_id: str) -> str:
    xr = _xray()
    try:
        resp = xr.batch_get_traces(TraceIds=[trace_id])
    except Exception as e:
        return f"ERROR: {e}"
    traces = resp.get("Traces", [])
    if not traces:
        return "(trace not found)"
    result = []
    for trace in traces:
        for seg in trace.get("Segments", []):
            doc = json.loads(seg.get("Document", "{}"))
            result.append(json.dumps({
                "name": doc.get("name"),
                "start": doc.get("start_time"),
                "end": doc.get("end_time"),
                "error": doc.get("error"),
                "fault": doc.get("fault"),
                "http": doc.get("http"),
                "cause": doc.get("cause", {}).get("exceptions", [])[:3],
            }, indent=2, default=str))
    return "\n---\n".join(result[:5])
