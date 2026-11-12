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
    ("/agent-manifest.json", "application/json", "workgraph"),
    ("/workgraph.network.json", "application/json", "workgraph_coordinator"),
    ("/links.json", "application/json", "networks"),
    ("/agent-mcp.json", "application/json", "network"),
    ("/.well-known/nsdeploy.json", "application/json", "protocol"),
    ("/runtime/index.js", "javascript", "export"),
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
        except urllib.error.URLError as exc:
            print(f"FAIL {path}: {exc}")
            failed += 1
            continue
        ok = status == 200 and content_type in ctype and needle in body
        print(f"{'PASS' if ok else 'FAIL'} {path} status={status} type={ctype.split(';')[0]}")
        failed += 0 if ok else 1

    if failed:
        print(f"{failed} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
