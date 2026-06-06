"""Linear issue tracker."""
from __future__ import annotations

import httpx

from ram.core.config import settings
from ram.core.registry import skill


def _post(query: str, variables: dict | None = None) -> dict:
    h = {"Authorization": settings.linear_api_key, "Content-Type": "application/json"}
    r = httpx.post("https://api.linear.app/graphql", headers=h,
                   json={"query": query, "variables": variables or {}}, timeout=15)
    return r.json() if r.status_code < 300 else {"errors": [{"message": r.text}]}


@skill(name="linear_my_issues", description="List my open Linear issues.",
       requires=["linear_api_key"])
def linear_my_issues(state: str = "open") -> str:
    q = """{ viewer { assignedIssues(first: 30) { nodes {
      identifier title state { name } priority dueDate
    } } } }"""
    res = _post(q)
    if "errors" in res:
        return f"ERROR: {res['errors'][0].get('message','?')}"
    nodes = res["data"]["viewer"]["assignedIssues"]["nodes"]
    if state == "open":
        nodes = [n for n in nodes if n["state"]["name"].lower() not in ("done", "canceled")]
    return "\n".join(f"{n['identifier']:<8} P{n['priority']}  {n['state']['name']:<12} {n['title']}"
                     for n in nodes) or "(none)"


@skill(name="linear_create_issue",
       description="Create a Linear issue in a team (pass team_key like 'ENG').",
       requires=["linear_api_key"], sensitive=True)
def linear_create_issue(team_key: str, title: str, description: str = "") -> str:
    teams = _post('{ teams { nodes { id key } } }')
    team_id = next((t["id"] for t in teams["data"]["teams"]["nodes"]
                    if t["key"] == team_key), None)
    if not team_id:
        return f"team {team_key} not found"
    m = """mutation($t:String!,$d:String,$tid:String!) { issueCreate(input:{title:$t,description:$d,teamId:$tid}) {
        success issue { identifier url }
    } }"""
    res = _post(m, {"t": title, "d": description, "tid": team_id})
    iss = res.get("data", {}).get("issueCreate", {}).get("issue") or {}
    return f"{iss.get('identifier','?')} {iss.get('url','')}"
