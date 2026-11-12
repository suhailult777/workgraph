"""Create the WorkGraph seed graph in a persistent Relate store."""

from __future__ import annotations

import sys

from graph.db import connect, store_path

PARTIES = [
    {"id": "party-mira", "name": "Mira Chen", "kind": "freelancer", "location": "Hyderabad"},
    {"id": "party-jules", "name": "Jules Okafor", "kind": "freelancer", "location": "Lagos"},
    {"id": "party-northwind", "name": "Northwind Studio", "kind": "client", "location": "Berlin"},
    {"id": "party-kestrel", "name": "Kestrel Labs", "kind": "client", "location": "Singapore"},
]

SKILLS = [
    {"id": "skill-design", "name": "Design systems"},
    {"id": "skill-research", "name": "User research"},
    {"id": "skill-build", "name": "Front-end build"},
]

PROJECTS = [
    {"id": "proj-harbour", "name": "Harbour rebrand", "status": "active", "client": "party-northwind"},
    {"id": "proj-atlas", "name": "Atlas dashboard", "status": "paid", "client": "party-kestrel"},
]

MILESTONES = [
    {"id": "ms-h1", "name": "Discovery", "project": "proj-harbour", "status": "PAID", "amount_cents": 180000, "skill": "skill-research"},
    {"id": "ms-h2", "name": "Design system", "project": "proj-harbour", "status": "SENT", "amount_cents": 240000, "skill": "skill-design"},
    {"id": "ms-h3", "name": "Build", "project": "proj-harbour", "status": "BLOCKED", "amount_cents": 320000, "skill": "skill-build"},
    {"id": "ms-h4", "name": "Handover", "project": "proj-harbour", "status": "BLOCKED", "amount_cents": 90000, "skill": "skill-build"},
    {"id": "ms-a1", "name": "Audit", "project": "proj-atlas", "status": "PAID", "amount_cents": 120000, "skill": "skill-research"},
    {"id": "ms-a2", "name": "Component library", "project": "proj-atlas", "status": "PAID", "amount_cents": 260000, "skill": "skill-design"},
]

# Milestone dependency edges, child -> prerequisite.
DEPENDS = [
    ("ms-h2", "ms-h1"),
    ("ms-h3", "ms-h2"),
    ("ms-h4", "ms-h3"),
    ("ms-a2", "ms-a1"),
]

INVOICES = [
    {"id": "inv-h1", "number": "WG-1001", "status": "PAID", "amount_cents": 180000, "milestone": "ms-h1"},
    {"id": "inv-h2", "number": "WG-1002", "status": "SENT", "amount_cents": 240000, "milestone": "ms-h2"},
    {"id": "inv-a1", "number": "WG-1003", "status": "PAID", "amount_cents": 120000, "milestone": "ms-a1"},
    {"id": "inv-a2", "number": "WG-1004", "status": "PAID", "amount_cents": 260000, "milestone": "ms-a2"},
]

PAYMENTS = [
    {"id": "pay-h1", "amount_cents": 180000, "method": "sample", "invoice": "inv-h1"},
    {"id": "pay-a1", "amount_cents": 120000, "method": "sample", "invoice": "inv-a1"},
    {"id": "pay-a2", "amount_cents": 260000, "method": "sample", "invoice": "inv-a2"},
]

DELIVERABLES = [
    {"id": "del-h1", "name": "Discovery notes", "milestone": "ms-h1", "payment": "pay-h1"},
    {"id": "del-a1", "name": "Audit report", "milestone": "ms-a1", "payment": "pay-a1"},
    {"id": "del-a2", "name": "Component library source", "milestone": "ms-a2", "payment": "pay-a2"},
]

WORKED_ON = [("party-mira", "proj-harbour"), ("party-jules", "proj-atlas")]
HAS_SKILL = [
    ("party-mira", "skill-design"),
    ("party-mira", "skill-research"),
    ("party-mira", "skill-build"),
    ("party-jules", "skill-research"),
    ("party-jules", "skill-design"),
]
NEEDS_SKILL = [
    ("proj-harbour", "skill-design"),
    ("proj-harbour", "skill-research"),
    ("proj-harbour", "skill-build"),
    ("proj-atlas", "skill-research"),
    ("proj-atlas", "skill-design"),
]


def seed(conn) -> dict:
    if conn.execute("MATCH (n) RETURN count(n) AS n").fetchone()["n"]:
        raise SystemExit("store already has data; refusing to seed twice")

    conn.autocommit = False
    try:
        for p in PARTIES:
            conn.execute("CREATE (:Party {id: $id, name: $name, kind: $kind, location: $location})", p)
        for s in SKILLS:
            conn.execute("CREATE (:Skill {id: $id, name: $name})", s)
        for p in PROJECTS:
            conn.execute("CREATE (:Project {id: $id, name: $name, status: $status})", p)
        for m in MILESTONES:
            conn.execute(
                "CREATE (:Milestone {id: $id, name: $name, status: $status, amount_cents: $amount_cents})",
                m,
            )
        for i in INVOICES:
            conn.execute(
                "CREATE (:Invoice {id: $id, number: $number, status: $status, amount_cents: $amount_cents})",
                i,
            )
        for p in PAYMENTS:
            conn.execute(
                "CREATE (:Payment {id: $id, amount_cents: $amount_cents, method: $method})",
                p,
            )
        for d in DELIVERABLES:
            conn.execute("CREATE (:Deliverable {id: $id, name: $name})", d)

        for client, project in [(p["client"], p["id"]) for p in PROJECTS]:
            conn.execute(
                "MATCH (c:Party {id: $client}), (p:Project {id: $project}) CREATE (c)-[:COMMISSIONED]->(p)",
                {"client": client, "project": project},
            )
        for party, project in WORKED_ON:
            conn.execute(
                "MATCH (a:Party {id: $party}), (p:Project {id: $project}) CREATE (a)-[:WORKED_ON]->(p)",
                {"party": party, "project": project},
            )
        for party, skill in HAS_SKILL:
            conn.execute(
                "MATCH (a:Party {id: $party}), (s:Skill {id: $skill}) CREATE (a)-[:HAS_SKILL]->(s)",
                {"party": party, "skill": skill},
            )
        for project, skill in NEEDS_SKILL:
            conn.execute(
                "MATCH (p:Project {id: $project}), (s:Skill {id: $skill}) CREATE (p)-[:NEEDS_SKILL]->(s)",
                {"project": project, "skill": skill},
            )
        for m in MILESTONES:
            conn.execute(
                "MATCH (p:Project {id: $project}), (m:Milestone {id: $mid}) CREATE (p)-[:HAS_MILESTONE]->(m)",
                {"project": m["project"], "mid": m["id"]},
            )
        for child, parent in DEPENDS:
            conn.execute(
                "MATCH (a:Milestone {id: $child}), (b:Milestone {id: $parent}) CREATE (a)-[:DEPENDS_ON]->(b)",
                {"child": child, "parent": parent},
            )
        for inv in INVOICES:
            conn.execute(
                "MATCH (m:Milestone {id: $milestone}), (i:Invoice {id: $id}) CREATE (m)-[:INVOICED]->(i)",
                {"milestone": inv["milestone"], "id": inv["id"]},
            )
        for pay in PAYMENTS:
            conn.execute(
                "MATCH (i:Invoice {id: $invoice}), (p:Payment {id: $id}) CREATE (i)-[:PAID_BY]->(p)",
                {"invoice": pay["invoice"], "id": pay["id"]},
            )
        for d in DELIVERABLES:
            conn.execute(
                "MATCH (m:Milestone {id: $milestone}), (d:Deliverable {id: $did}) CREATE (m)-[:PRODUCES]->(d)",
                {"milestone": d["milestone"], "did": d["id"]},
            )
            conn.execute(
                "MATCH (p:Payment {id: $payment}), (d:Deliverable {id: $did}) CREATE (p)-[:UNLOCKS]->(d)",
                {"payment": d["payment"], "did": d["id"]},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return counts(conn)


def counts(conn) -> dict:
    return {
        "nodes": conn.execute("MATCH (n) RETURN count(n) AS n").fetchone()["n"],
        "relationships": conn.execute("MATCH ()-[r]->() RETURN count(r) AS n").fetchone()["n"],
    }


def main() -> int:
    target = store_path()
    if target.exists():
        print(f"store exists: {target}")
        print("delete it only if you intend to rebuild the sample data")
        return 1
    with connect(target) as conn:
        result = seed(conn)
        conn.flush()
    print(f"seeded {target}: {result['nodes']} nodes, {result['relationships']} relationships")
    return 0


if __name__ == "__main__":
    sys.exit(main())
