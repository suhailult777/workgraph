from pathlib import Path

from graph.db import connect
from graph.operations import create_sample_project
from graph.retrieval import citations_for, retrieve_context, source_line
from graph.seed import seed


def build_store(tmp_path: Path):
    path = tmp_path / "workgraph.rl"
    conn = connect(path)
    seed(conn)
    return conn


def test_retrieves_an_invoice_and_the_milestones_waiting_on_it(tmp_path):
    conn = build_store(tmp_path)
    try:
        bundle = retrieve_context(
            conn, "Which milestones are blocked until WG-1002 is paid?"
        )
        ids = {node["id"] for node in bundle["nodes"]}
        assert {"inv-h2", "ms-h2", "ms-h3", "ms-h4"} <= ids
        assert "[ms-h3]" in bundle["context"]
        assert "-[DEPENDS_ON]->" in bundle["context"] or "DEPENDS_ON" in bundle["context"]
        assert "amount_cents=240000" in bundle["context"]
    finally:
        conn.close()


def test_retrieves_a_skill_and_paid_history(tmp_path):
    conn = build_store(tmp_path)
    try:
        bundle = retrieve_context(conn, "Who has been paid for design systems work?")
        ids = {node["id"] for node in bundle["nodes"]}
        assert "skill-design" in ids
        assert "ms-a2" in ids or "pay-a2" in ids
        assert any(node["kind"] == "Party" for node in bundle["nodes"])
    finally:
        conn.close()


def test_an_unrelated_question_has_no_graph_match(tmp_path):
    conn = build_store(tmp_path)
    try:
        bundle = retrieve_context(conn, "What is the capital of France?")
        assert bundle["matched"] == []
        assert bundle["nodes"] == []
        assert bundle["context"] == ""
    finally:
        conn.close()


def test_citations_accept_ids_and_titles_and_source_line_uses_matched_nodes(tmp_path):
    conn = build_store(tmp_path)
    try:
        bundle = retrieve_context(conn, "Which invoice blocks the Build milestone?")
        assert "[inv-h2]" in bundle["context"]
        assert "[ms-h3]" in bundle["context"]
        answer = 'Design system [ms-h2] is blocked by invoice [inv-h2] "WG-1002".'
        cited = citations_for(answer, bundle)
        cited_ids = {node["id"] for node in cited}
        assert {"ms-h2", "inv-h2"} <= cited_ids
        line = source_line(bundle)
        assert line.startswith("Sources: [")

        unicode_answer = "Invoice inv\u2011h2 blocks Build."
        assert "inv-h2" in {node["id"] for node in citations_for(unicode_answer, bundle)}
    finally:
        conn.close()


def test_context_is_bounded(tmp_path):
    conn = build_store(tmp_path)
    try:
        bundle = retrieve_context(conn, "Show every project milestone invoice payment skill", limit=3)
        assert len(bundle["nodes"]) <= 16
        assert bundle["context"].count("amount_cents") <= 16
    finally:
        conn.close()

def test_blocked_invoice_path_survives_extra_invoices(tmp_path):
    conn = build_store(tmp_path)
    try:
        for index in range(10):
            create_sample_project(conn, f"Noise project {index}")
        conn.flush()

        bundle = retrieve_context(
            conn,
            "Which Harbour rebrand milestones are blocked until invoice WG-1002 is paid?",
        )
        ids = {node["id"] for node in bundle["nodes"]}
        assert {"inv-h2", "ms-h2", "ms-h3", "ms-h4", "proj-harbour"} <= ids
        assert "[ms-h3]" in bundle["context"]
        assert "[ms-h4]" in bundle["context"]
        assert "[inv-h2]" in bundle["context"]
        edges = {(edge["source"], edge["type"], edge["target"]) for edge in bundle["edges"]}
        assert ("ms-h2", "INVOICED", "inv-h2") in edges
        assert ("ms-h3", "DEPENDS_ON", "ms-h2") in edges
        assert ("ms-h4", "DEPENDS_ON", "ms-h3") in edges
        matched_ids = {node["id"] for node in bundle["matched"]}
        assert {"inv-h2", "ms-h3", "ms-h4"} <= matched_ids
        assert "[ms-h4]" in source_line(bundle)
    finally:
        conn.close()
