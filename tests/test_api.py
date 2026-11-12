from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from graph.db import connect
from graph.seed import seed


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("store") / "workgraph.rl"
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


def test_summary(client):
    body = client.get("/api/graph/summary").json()
    labels = {row["label"]: row["count"] for row in body["labels"]}
    assert labels == {
        "Deliverable": 3,
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
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
    if not dist.exists():
        pytest.skip("frontend not built")
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<div id=\"root\">" in response.text
