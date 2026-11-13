import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from graph.db import connect
from graph.seed import seed

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path):
    path = tmp_path / "workgraph.rl"
    with connect(path) as conn:
        seed(conn)
        conn.flush()
    app = create_app(path)
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["graph_ready"] is True


def test_health_does_not_expose_an_absolute_path(client):
    body = client.get("/api/health").json()
    assert body["store"].endswith(".rl")
    assert "\\" not in body["store"] and ":" not in body["store"]


def test_health_sanitizes_an_absolute_store_label(tmp_path, monkeypatch):
    path = tmp_path / "workgraph.rl"
    with connect(path) as conn:
        seed(conn)
        conn.flush()
    monkeypatch.setenv("WORKGRAPH_STORE_LABEL", r"C:\Users\private\workgraph.rl")
    with TestClient(create_app(path)) as client:
        body = client.get("/api/health").json()
    assert body["store"] == "workgraph.rl"
    assert "\\" not in body["store"] and ":" not in body["store"]

    monkeypatch.setenv("WORKGRAPH_STORE_LABEL", "data/workgraph.rl")
    with TestClient(create_app(path)) as client:
        body = client.get("/api/health").json()
    assert body["store"] == "data/workgraph.rl"

    monkeypatch.setenv("WORKGRAPH_STORE_LABEL", "/Users/private/workgraph.rl")
    with TestClient(create_app(path)) as client:
        body = client.get("/api/health").json()
    assert body["store"] == "workgraph.rl"
    assert "/" not in body["store"]


def test_summary(client):
    body = client.get("/api/graph/summary").json()
    labels = {row["label"]: row["count"] for row in body["labels"]}
    assert labels == {
        "Deliverable": 6,
        "Invoice": 4,
        "Milestone": 6,
        "Party": 4,
        "Payment": 3,
        "Project": 2,
        "Skill": 3,
    }
    assert {p["name"] for p in body["projects"]} == {"Harbour rebrand", "Atlas dashboard"}


def test_blocked(client):
    body = client.get("/api/graph/blocked").json()
    assert body["blocked"] == [
        {"blocked": "Build", "waiting_on": "Design system", "invoice": "WG-1002", "amount_cents": 240000},
        {"blocked": "Handover", "waiting_on": "Design system", "invoice": "WG-1002", "amount_cents": 240000},
    ]


def test_graph_state_for_the_assistant(client):
    body = client.get("/api/graph/state").json()
    assert body["mode"] == "sample"
    assert body["skills"] == ["Design systems", "Front-end build", "User research"]
    projects = {project["name"]: project for project in body["projects"]}
    assert set(projects) == {"Harbour rebrand", "Atlas dashboard"}

    harbour = projects["Harbour rebrand"]
    assert harbour["stats"]["blocked"] == 2
    build = next(m for m in harbour["milestones"] if m["name"] == "Build")
    assert build["blocked_by"] == [
        {
            "path": ["Build", "Design system"],
            "reason": "unpaid_invoice",
            "invoice": "WG-1002",
            "amount_cents": 240000,
        }
    ]
    assert build["can_pay"] is False
    assert "graph" not in harbour


def test_similar(client):
    body = client.get("/api/graph/similar", params={"skill": "Design systems"}).json()
    assert body["skill"] == "Design systems"
    assert {row["party"] for row in body["work"]} == {"Mira Chen", "Jules Okafor"}


def test_projects_list(client):
    body = client.get("/api/projects").json()
    projects = {p["id"]: p for p in body["projects"]}
    assert len(projects) == 2
    assert projects["proj-harbour"]["blocked"] == 2
    assert projects["proj-harbour"]["client"] == "Northwind Studio"


def test_project_detail(client):
    response = client.get("/api/projects/proj-harbour")
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["name"] == "Harbour rebrand"
    assert len(body["milestones"]) == 4
    build = next(m for m in body["milestones"] if m["id"] == "ms-h3")
    assert build["blocked_by"][0]["invoice"] == "WG-1002"
    assert len(body["graph"]["nodes"]) >= 10
    assert all("C:" not in str(node.get("meta", "")) for node in body["graph"]["nodes"])


def test_project_detail_unknown_is_404(client):
    response = client.get("/api/projects/proj-missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_create_project(client):
    response = client.post("/api/projects", json={"name": "Willow sprint"})
    assert response.status_code == 201
    body = response.json()
    assert body["project"]["name"] == "Willow sprint"
    assert [m["name"] for m in body["milestones"]] == ["Scope", "Design", "Build", "Handover"]
    assert body["milestones"][1]["invoice"]["number"].startswith("WG-")


def test_create_project_without_a_body_uses_the_default_name(client):
    response = client.post("/api/projects")
    assert response.status_code == 201
    assert response.json()["project"]["name"] == "Juniper launch"


def test_payment_fractional_amount_is_rejected(client):
    response = client.post(
        "/api/payments", json={"invoice_id": "inv-h2", "amount_cents": 240000.5}
    )
    assert response.status_code == 422
    detail = client.get("/api/projects/proj-harbour").json()
    assert next(m for m in detail["milestones"] if m["id"] == "ms-h2")["invoice"]["status"] == "SENT"


def test_payment_preview(client):
    response = client.get("/api/invoices/inv-h2/payment-preview")
    assert response.status_code == 200
    body = response.json()
    assert body["amount_cents"] == 240000
    assert body["deliverables"] == [{"id": "del-h2", "name": "Design system kit"}]
    assert body["edges_to_create"][1] == "Payment -[:UNLOCKS]-> Design system kit"


def test_record_payment_endpoint(client):
    response = client.post(
        "/api/payments", json={"invoice_id": "inv-h2", "amount_cents": 240000}
    )
    assert response.status_code == 201
    payment_id = response.json()["payment_id"]
    assert payment_id.startswith("pay-")

    detail = client.get("/api/projects/proj-harbour").json()
    design = next(m for m in detail["milestones"] if m["id"] == "ms-h2")
    assert design["status"] == "PAID"
    assert design["unlocked"] is True
    assert design["invoice"]["status"] == "PAID"


def test_payment_wrong_amount_leaves_invoice_sent(client):
    response = client.post(
        "/api/payments", json={"invoice_id": "inv-h2", "amount_cents": 100}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "amount_mismatch"

    detail = client.get("/api/projects/proj-harbour").json()
    design = next(m for m in detail["milestones"] if m["id"] == "ms-h2")
    assert design["invoice"]["status"] == "SENT"
    assert design["status"] == "SENT"


def test_complete_blocked_milestone_is_409(client):
    response = client.post("/api/milestones/ms-h3/complete")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "blocked"


def test_complete_milestone_endpoint(client):
    client.post("/api/payments", json={"invoice_id": "inv-h2", "amount_cents": 240000})
    response = client.post("/api/milestones/ms-h2/complete")
    assert response.status_code == 200
    body = response.json()
    assert body["milestone"]["status"] == "DONE"
    build = next(m for m in body["milestones"] if m["id"] == "ms-h3")
    assert build["status"] == "READY"
    assert build["blocked_by"] == []


def test_manifest(client):
    response = client.get("/agent-manifest.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    manifest = response.json()
    assert manifest["networks"][0]["name"] == "workgraph"
    assert manifest["networks"][0]["front_man"] == "workgraph_coordinator"
    assert manifest["actions"]["agentTools"] == [
        "get_graph_state",
        "search_similar_work",
        "propose_plan",
        "fill_draft",
    ]
    assert manifest["llm_router"]["mock"] is True


def test_network_is_resolved_json(client):
    response = client.get("/workgraph.network.json")
    assert response.status_code == 200
    network = response.json()
    names = {tool["name"] for tool in network["tools"]}
    assert names == {"workgraph_coordinator", "plan_specialist", "ledger_specialist"}
    coordinator = next(tool for tool in network["tools"] if tool["name"] == "workgraph_coordinator")
    assert coordinator["tools"] == ["plan_specialist", "ledger_specialist"]
    text = response.text
    assert '"include"' not in text and '"includes"' not in text
    assert "$" not in text  # no environment substitutions


def test_links(client):
    body = client.get("/links.json").json()
    assert body == {"version": 1, "networks": {"workgraph": {}}}


def test_runtime_files(client):
    assert client.get("/runtime/index.js").status_code == 200
    assert client.get("/runtime/generated/graph.gen.mjs").status_code == 200
    assert client.get("/runtime/README.md").status_code == 200
    assert client.get("/runtime/LICENSE.txt").status_code == 200
    assert client.get("/.well-known/nsdeploy.json").status_code == 200
    assert client.get("/agent-mcp.json").status_code == 200


def test_site_action_modules_are_served_as_javascript(client):
    for path in ("/site-actions.js", "/page-bridge.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("application/javascript"), path
    assert client.get("/runtime/generated/graph.gen.mjs").headers["content-type"].startswith(
        "application/javascript"
    )


def test_cors_on_public_artifacts(client):
    response = client.get("/agent-manifest.json", headers={"Origin": "https://peer.example"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_does_not_grant_cross_origin_writes(client):
    response = client.post(
        "/api/projects",
        json={"name": "CORS test"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "cross_origin_write"
    assert "access-control-allow-origin" not in response.headers


def test_same_origin_write_is_allowed(client):
    response = client.post(
        "/api/projects",
        json={"name": "Same origin"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 201
    assert response.json()["project"]["name"] == "Same origin"


def test_write_requires_a_local_host_even_with_a_matching_origin(client):
    response = client.post(
        "/api/projects",
        json={"name": "DNS rebinding"},
        headers={"Host": "evil.example", "Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "host_not_allowed"

    response = client.post(
        "/api/projects",
        json={"name": "No origin"},
        headers={"Host": "evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "host_not_allowed"


def test_demo_router_returns_an_sse_tool_call(client):
    response = client.post(
        "/api/demo/llm/chat/completions",
        json={
            "model": "workgraph-demo",
            "messages": [
                {"role": "user", "content": "Which milestones are blocked by an unpaid invoice?"}
            ],
            "tools": [
                {"type": "function", "function": {"name": "website_get_graph_state"}},
                {"type": "function", "function": {"name": "website_search_similar_work"}},
            ],
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text
    events = [
        json.loads(line[5:].strip())
        for line in response.text.splitlines()
        if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")
    ]
    calls = [
        call
        for event in events
        for choice in event.get("choices", [])
        for call in choice.get("delta", {}).get("tool_calls", [])
    ]
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "website_get_graph_state"
    assert json.loads(calls[0]["function"]["arguments"]) == {}
    assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert response.headers["x-nsdeploy-llm-route"] == "demo"


def test_demo_router_refuses_a_card_charge(client):
    response = client.post(
        "/api/demo/llm/chat/completions",
        json={
            "model": "workgraph-demo",
            "messages": [
                {"role": "user", "content": "Record a real card payment for the design system."}
            ],
            "tools": [{"type": "function", "function": {"name": "website_get_graph_state"}}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert "can't charge a card" in response.text
    assert "website_get_graph_state" not in response.text


def test_frontend_build_is_served(client):
    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        pytest.skip("frontend not built")
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<div id=\"root\">" in response.text
