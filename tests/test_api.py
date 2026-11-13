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
        "get_blocked_milestones",
        "search_similar_work",
    ]


def test_network_is_resolved_json(client):
    response = client.get("/workgraph.network.json")
    assert response.status_code == 200
    network = response.json()
    names = {tool["name"] for tool in network["tools"]}
    assert names == {"workgraph_coordinator", "ledger_specialist"}
    assert network["tools"][0]["tools"] == ["ledger_specialist"]
    text = response.text
    assert '"include"' not in text and '"includes"' not in text
    assert "$" not in text  # no environment substitutions


def test_links(client):
    body = client.get("/links.json").json()
    assert body == {"version": 1, "networks": {"workgraph": {}}}


def test_runtime_files(client):
    assert client.get("/runtime/index.js").status_code == 200
    assert client.get("/runtime/README.md").status_code == 200
    assert client.get("/runtime/LICENSE.txt").status_code == 200
    assert client.get("/.well-known/nsdeploy.json").status_code == 200
    assert client.get("/agent-mcp.json").status_code == 200


def test_cors_on_public_artifacts(client):
    response = client.get("/agent-manifest.json", headers={"Origin": "https://peer.example"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_frontend_build_is_served(client):
    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        pytest.skip("frontend not built")
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<div id=\"root\">" in response.text
