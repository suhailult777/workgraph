"""Judge pass: check the local public artifacts and graph reads over HTTP.

Run the server first:
    .venv/Scripts/python.exe -m uvicorn backend.app:app --port 8090

Then:
    .venv/Scripts/python.exe scripts/judge_pass.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8090"

CHECKS = [
    ("/api/health", "application/json", "ok"),
    ("/api/config", "application/json", "assistant_live"),
    ("/api/projects", "application/json", "Harbour rebrand"),
    ("/api/projects/proj-harbour", "application/json", "Design system"),
    ("/api/graph/state", "application/json", "Harbour rebrand"),
    ("/api/graph/decline-path?invoice=WG-1002", "application/json", "blocked_count"),
    ("/agent-manifest.json", "application/json", "workgraph"),
    ("/workgraph.network.json", "application/json", "workgraph_coordinator"),
    ("/links.json", "application/json", "networks"),
    ("/agent-mcp.json", "application/json", "network"),
    ("/.well-known/nsdeploy.json", "application/json", "protocol"),
    ("/runtime/index.js", "javascript", "export"),
    ("/runtime/generated/graph.gen.mjs", "javascript", "export"),
    ("/site-actions.js", "javascript", "accept_plan"),
    ("/page-bridge.js", "javascript", "WorkGraphPage"),
    ("/", "text/html", "WorkGraph"),
]


def main() -> int:
    failed = 0
    for path, content_type, needle in CHECKS:
        try:
            with urllib.request.urlopen(BASE + path, timeout=10) as response:
                body = response.read().decode("utf-8", "replace")
                status = response.status
                ctype = response.headers.get("content-type", "")
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"FAIL {path}: {exc}")
            failed += 1
            continue
        ok = status == 200 and content_type in ctype and needle in body
        print(f"{'PASS' if ok else 'FAIL'} {path} status={status} type={ctype.split(';')[0]}")
        failed += 0 if ok else 1

    payload = json.dumps(
        {
            "model": "workgraph-demo",
            "messages": [
                {"role": "user", "content": "Which milestones are blocked by an unpaid invoice?"}
            ],
            "tools": [
                {"type": "function", "function": {"name": "website_get_graph_state"}}
            ],
            "stream": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        BASE + "/api/demo/llm/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", "replace")
            ok = response.status == 200 and "website_get_graph_state" in body
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"FAIL /api/demo/llm/chat/completions: {exc}")
        failed += 1
    else:
        print(
            "PASS /api/demo/llm/chat/completions "
            f"status=200 mock_tool_call={'website_get_graph_state' in body}"
        )
        failed += 0 if ok else 1

    if failed:
        print(f"{failed} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
