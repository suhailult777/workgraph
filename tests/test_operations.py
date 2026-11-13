"""Invariant tests for the Phase 1 graph operations.

Every test runs against a freshly seeded temporary store. The committed
``data/workgraph.rl`` is never touched.
"""

from __future__ import annotations

import pytest

from graph.db import connect
from graph.operations import (
    GraphError,
    complete_milestone,
    create_sample_project,
    get_project,
    list_projects,
    preview_payment,
    record_payment,
    transaction,
)
from graph.seed import counts, seed


@pytest.fixture()
def conn(tmp_path):
    with connect(tmp_path / "workgraph.rl") as connection:
        seed(connection)
        connection.flush()
        yield connection


def status_map(conn) -> dict[str, str]:
    rows = conn.execute("MATCH (m:Milestone) RETURN m.id AS id, m.status AS status").fetchall()
    return {r["id"]: r["status"] for r in rows}


def unlock_rows(conn) -> list[dict]:
    rows = conn.execute(
        "MATCH (p:Payment)-[:UNLOCKS]->(d:Deliverable) "
        "RETURN p.id AS payment, d.id AS deliverable ORDER BY d.id"
    ).fetchall()
    return [r.data() for r in rows]


def test_list_projects_reports_progress_and_blocks(conn):
    projects = {p["id"]: p for p in list_projects(conn)}

    harbour = projects["proj-harbour"]
    assert harbour["name"] == "Harbour rebrand"
    assert harbour["client"] == "Northwind Studio"
    assert harbour["milestones"] == 4
    assert harbour["done"] == 1
    assert harbour["blocked"] == 2
    assert harbour["paid_cents"] == 180000
    assert harbour["total_cents"] == 830000
    assert harbour["next"]["id"] == "ms-h2"

    atlas = projects["proj-atlas"]
    assert atlas["done"] == 2
    assert atlas["blocked"] == 0
    assert atlas["paid_cents"] == 380000


def test_project_detail_shows_full_blocked_paths(conn):
    project = get_project(conn, "proj-harbour")
    milestones = {m["id"]: m for m in project["milestones"]}

    build = milestones["ms-h3"]
    assert build["blocked"] is True
    assert build["blocked_by"] == [
        {
            "path": ["Build", "Design system"],
            "reason": "unpaid_invoice",
            "invoice": "WG-1002",
            "amount_cents": 240000,
        }
    ]

    handover = milestones["ms-h4"]
    assert handover["blocked_by"] == [
        {
            "path": ["Handover", "Build", "Design system"],
            "reason": "unpaid_invoice",
            "invoice": "WG-1002",
            "amount_cents": 240000,
        }
    ]

    assert milestones["ms-h1"]["blocked"] is False
    assert milestones["ms-h1"]["status"] == "DONE"
    assert milestones["ms-h1"]["can_complete"] is False
    assert milestones["ms-h2"]["can_complete"] is False
    assert milestones["ms-h3"]["can_complete"] is False


def test_project_detail_has_graph_nodes_and_edges(conn):
    project = get_project(conn, "proj-harbour")
    kinds = {n["kind"] for n in project["graph"]["nodes"]}
    assert {"Party", "Project", "Milestone", "Invoice", "Payment", "Deliverable"} <= kinds
    edge_types = {e["type"] for e in project["graph"]["edges"]}
    assert {"DEPENDS_ON", "HAS_MILESTONE", "INVOICED", "PAID_BY", "UNLOCKS", "PRODUCES"} <= edge_types


def test_payment_preview_changes_nothing(conn):
    before_nodes = counts(conn)["nodes"]
    before_edges = counts(conn)["relationships"]
    before_status = status_map(conn)

    preview = preview_payment(conn, "inv-h2")
    assert preview["invoice"]["id"] == "inv-h2"
    assert preview["milestone"]["id"] == "ms-h2"
    assert preview["amount_cents"] == 240000
    assert preview["deliverables"] == [{"id": "del-h2", "name": "Design system kit"}]
    assert preview["edges_to_create"] == [
        "Invoice WG-1002 -[:PAID_BY]-> Payment",
        "Payment -[:UNLOCKS]-> Design system kit",
    ]
    assert preview["status_changes"] == [
        {"entity": "Invoice WG-1002", "from": "SENT", "to": "PAID"},
        {"entity": "Milestone Design system", "from": "SENT", "to": "PAID"},
    ]

    assert counts(conn) == {"nodes": before_nodes, "relationships": before_edges}
    assert status_map(conn) == before_status


def test_payment_unlocks_only_the_paid_deliverable(conn):
    result = record_payment(conn, "inv-h2", 240000)

    assert result["payment_id"].startswith("pay-")
    assert counts(conn) == {"nodes": 29, "relationships": 42}
    assert status_map(conn)["ms-h2"] == "PAID"

    unlocks = unlock_rows(conn)
    assert {"payment": result["payment_id"], "deliverable": "del-h2"} in unlocks
    assert {row["deliverable"] for row in unlocks} == {"del-h1", "del-a1", "del-a2", "del-h2"}

    payment = conn.execute(
        "MATCH (p:Payment {id: $id}) RETURN p.amount_cents AS amount, p.method AS method",
        {"id": result["payment_id"]},
    ).fetchone()
    assert payment["amount"] == 240000
    assert payment["method"] == "sample"


def test_payment_amount_must_match_invoice(conn):
    before = counts(conn)
    before_status = status_map(conn)

    with pytest.raises(GraphError) as error:
        record_payment(conn, "inv-h2", 239999)
    assert error.value.code == "amount_mismatch"

    assert counts(conn) == before
    assert status_map(conn) == before_status


def test_payment_rejects_a_second_payment(conn):
    record_payment(conn, "inv-h2", 240000)
    before = counts(conn)

    with pytest.raises(GraphError) as error:
        record_payment(conn, "inv-h2", 240000)
    assert error.value.code == "already_paid"

    assert counts(conn) == before


def test_blocked_milestone_cannot_be_marked_done(conn):
    before = counts(conn)
    before_status = status_map(conn)

    with pytest.raises(GraphError) as error:
        complete_milestone(conn, "ms-h3")
    assert error.value.code == "blocked"

    assert counts(conn) == before
    assert status_map(conn) == before_status


def test_unpaid_invoice_milestone_cannot_be_marked_done(conn):
    before_status = status_map(conn)

    with pytest.raises(GraphError) as error:
        complete_milestone(conn, "ms-h2")
    assert error.value.code == "invoice_unpaid"

    assert status_map(conn) == before_status


def test_payment_then_done_unblocks_the_next_milestone(conn):
    record_payment(conn, "inv-h2", 240000)
    complete_milestone(conn, "ms-h2")

    milestones = {m["id"]: m for m in get_project(conn, "proj-harbour")["milestones"]}
    assert milestones["ms-h2"]["status"] == "DONE"
    assert milestones["ms-h3"]["status"] == "READY"
    assert milestones["ms-h3"]["blocked_by"] == []
    assert milestones["ms-h3"]["can_complete"] is True
    assert milestones["ms-h4"]["blocked_by"] == [
        {"path": ["Handover", "Build"], "reason": "not_done", "invoice": None, "amount_cents": None}
    ]

    complete_milestone(conn, "ms-h3")
    milestones = {m["id"]: m for m in get_project(conn, "proj-harbour")["milestones"]}
    assert milestones["ms-h4"]["status"] == "READY"
    assert milestones["ms-h4"]["blocked_by"] == []


def test_paid_but_unfinished_parent_still_blocks_the_child(conn):
    record_payment(conn, "inv-h2", 240000)
    milestones = {m["id"]: m for m in get_project(conn, "proj-harbour")["milestones"]}

    build = milestones["ms-h3"]
    assert build["status"] == "BLOCKED"
    assert build["can_complete"] is False
    assert build["blocked_by"] == [
        {
            "path": ["Build", "Design system"],
            "reason": "not_done",
            "invoice": None,
            "amount_cents": None,
        }
    ]

    with pytest.raises(GraphError) as error:
        complete_milestone(conn, "ms-h3")
    assert error.value.code == "blocked"


def test_cross_project_dependency_does_not_break_reads(conn):
    conn.execute(
        "CREATE (:Milestone {id: 'ms-a3', name: 'Client review', status: 'READY', "
        "amount_cents: 50000, order: 3})"
    )
    conn.execute(
        "MATCH (p:Project {id: 'proj-atlas'}), (m:Milestone {id: 'ms-a3'}) "
        "CREATE (p)-[:HAS_MILESTONE]->(m)"
    )
    conn.execute(
        "MATCH (a:Milestone {id: 'ms-a3'}), (b:Milestone {id: 'ms-h3'}) "
        "CREATE (a)-[:DEPENDS_ON]->(b)"
    )

    detail = get_project(conn, "proj-atlas")
    review = next(m for m in detail["milestones"] if m["id"] == "ms-a3")
    assert review["blocked_by"] == [
        {"path": ["Client review", "Build"], "reason": "not_done", "invoice": None, "amount_cents": None}
    ]
    assert review["can_complete"] is False
    assert {project["id"] for project in list_projects(conn)} == {"proj-atlas", "proj-harbour"}

    with pytest.raises(GraphError) as error:
        complete_milestone(conn, "ms-a3")
    assert error.value.code == "blocked"


def test_payment_does_not_demote_a_done_milestone(conn):
    conn.execute("MATCH (m:Milestone {id: 'ms-h2'}) SET m.status = 'DONE'")
    record_payment(conn, "inv-h2", 240000)
    assert status_map(conn)["ms-h2"] == "DONE"


def test_nested_transaction_is_rejected(conn):
    before = counts(conn)

    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("CREATE (:Party {id: 'party-nested', name: 'Nested'})")
            with transaction(conn):
                pass

    assert counts(conn) == before



def test_create_sample_project_writes_expected_graph(conn):
    before = counts(conn)
    project = create_sample_project(conn, "Juniper launch")

    assert project["project"]["name"] == "Juniper launch"
    assert project["project"]["status"] == "active"
    assert [m["name"] for m in project["milestones"]] == [
        "Scope",
        "Design",
        "Build",
        "Handover",
    ]
    assert [m["status"] for m in project["milestones"]] == ["DONE", "SENT", "BLOCKED", "BLOCKED"]
    assert len(project["dependencies"]) == 3
    assert project["stats"]["total_cents"] == 600000
    assert project["stats"]["paid_cents"] == 120000
    assert len(project["invoices"]) == 2
    scope = next(m for m in project["milestones"] if m["name"] == "Scope")
    assert scope["deliverables"][0]["unlocked"] is True

    after = counts(conn)
    assert after["nodes"] - before["nodes"] == 12
    assert after["relationships"] - before["relationships"] == 19

    build = next(m for m in project["milestones"] if m["name"] == "Build")
    assert build["blocked_by"][0]["reason"] == "unpaid_invoice"
    assert build["blocked_by"][0]["path"] == ["Build", "Design"]

    names = {p["name"] for p in list_projects(conn)}
    assert "Juniper launch" in names


def test_create_project_on_an_empty_store_bootstraps_parties_and_skills(tmp_path):
    with connect(tmp_path / "empty.rl") as conn:
        project = create_sample_project(conn, "First project")
        assert project["project"]["client"] == "Northwind Studio"
        assert project["project"]["owner"] == "Mira Chen"
        assert project["project"]["skills"] == ["Design systems", "Front-end build"]
        scope = next(m for m in project["milestones"] if m["name"] == "Scope")
        assert scope["status"] == "DONE"
        assert scope["deliverables"][0]["unlocked"] is True
        assert project["stats"]["paid_cents"] == 120000
        assert counts(conn) == {"nodes": 16, "relationships": 19}


def test_create_sample_project_keeps_names_unique(conn):
    first = create_sample_project(conn, "Juniper launch")
    second = create_sample_project(conn, "Juniper launch")
    assert first["project"]["id"] != second["project"]["id"]
    assert second["project"]["name"] == "Juniper launch 2"


def test_preview_unknown_invoice_is_not_found(conn):
    with pytest.raises(GraphError) as error:
        preview_payment(conn, "inv-missing")
    assert error.value.code == "not_found"


def test_payment_requires_a_positive_integer_amount(conn):
    for amount in (0, -1, 240000.5, True):
        with pytest.raises(GraphError) as error:
            record_payment(conn, "inv-h2", amount)
        assert error.value.code == "invalid_amount"


def test_transaction_rolls_back_partial_writes(conn):
    before = counts(conn)

    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("CREATE (:Party {id: 'party-ghost', name: 'Ghost'})")
            raise RuntimeError("simulated failure after a write")

    assert counts(conn) == before
    assert conn.execute("MATCH (p:Party {id: 'party-ghost'}) RETURN p").fetchall() == []
