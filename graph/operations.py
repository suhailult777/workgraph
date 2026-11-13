"""Write-side graph operations for WorkGraph.

The same functions back the human UI today and the site actions in Phase 1b.
Every mutation runs in one Relate transaction, so a validation failure or a
write failure leaves the graph exactly as it was.
"""

from __future__ import annotations

import re
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone

class GraphError(Exception):
    """A graph operation that refused to run. Nothing was written."""

    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@contextmanager
def transaction(conn):
    """Run statements as one transaction, rolling back on any failure."""
    if not conn.autocommit:
        raise RuntimeError("transaction() cannot nest inside an open transaction")
    conn.autocommit = False
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def _fetch(conn, cypher: str, params: dict | None = None) -> list[dict]:
    return [row.data() for row in conn.execute(cypher, params or {}).fetchall()]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _invoice_status(conn, milestone_id: str) -> str | None:
    rows = _fetch(
        conn,
        "MATCH (m:Milestone {id: $id})-[:INVOICED]->(i:Invoice) "
        "RETURN i.status AS status ORDER BY i.number",
        {"id": milestone_id},
    )
    return rows[0]["status"] if rows else None


def _blocked_by(
    milestone: dict,
    parents: dict[str, list[str]],
    by_id: dict[str, dict],
) -> list[dict]:
    """Find blockers with one bounded BFS, not every root path.

    The walk visits each ancestor once, so a wide DAG cannot explode. An unpaid
    invoice is recorded with the shortest path to it. A not-done ancestor is
    recorded only when it is not already on an invoice path and no nearer
    not-done ancestor was chosen, which keeps the human UI's nearest-cause path.
    """
    start = milestone["id"]
    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    visited = {start}
    invoice_paths: list[tuple[list[str], dict]] = []
    not_done_paths: list[list[str]] = []

    while queue:
        node, path = queue.popleft()
        for parent in parents.get(node, []):
            if parent in visited:
                continue
            visited.add(parent)
            parent_path = path + [parent]
            info = by_id.get(parent)
            if info is None:
                continue
            invoice = info["invoice"]
            if invoice and invoice["status"] == "SENT":
                invoice_paths.append((parent_path, invoice))
                continue
            if info["status"] != "DONE":
                not_done_paths.append(parent_path)
            queue.append((parent, parent_path))

    invoice_nodes = {path[-1] for path, _ in invoice_paths}
    invoice_ancestors: set[str] = set()
    for path, _ in invoice_paths:
        invoice_ancestors.update(path[1:-1])

    blockers: list[dict] = []
    for path, invoice in invoice_paths:
        blockers.append(
            {
                "path": [by_id[node]["name"] for node in path],
                "reason": "unpaid_invoice",
                "invoice": invoice["number"],
                "amount_cents": invoice["amount_cents"],
            }
        )

    selected_not_done: set[str] = set()
    for path in sorted(not_done_paths, key=len):
        node = path[-1]
        if node in invoice_nodes or node in invoice_ancestors:
            continue
        if any(selected in path for selected in selected_not_done):
            continue
        selected_not_done.add(node)
        blockers.append(
            {
                "path": [by_id[item]["name"] for item in path],
                "reason": "not_done",
                "invoice": None,
                "amount_cents": None,
            }
        )

    seen: set[tuple] = set()
    unique: list[dict] = []
    for blocker in blockers:
        key = (tuple(blocker["path"]), blocker["reason"], blocker["invoice"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(blocker)
    unique.sort(
        key=lambda item: (
            0 if item["reason"] == "unpaid_invoice" else 1,
            len(item["path"]),
            item["path"],
        )
    )
    return unique[:12]


def assert_store_integrity(conn) -> None:
    """Refuse the one-to-one invoice rules everywhere a raw read is served."""
    for row in _fetch(
        conn,
        "MATCH (m:Milestone)-[:INVOICED]->(i:Invoice) "
        "RETURN m.id AS id, m.name AS name, count(i) AS invoice_count",
    ):
        if row["invoice_count"] > 1:
            raise GraphError(
                "multiple_invoices",
                f"{row['name']} has {row['invoice_count']} invoices; "
                "exactly one invoice per milestone is allowed.",
            )
    for row in _fetch(
        conn,
        "MATCH (i:Invoice)<-[:INVOICED]-(m:Milestone) "
        "RETURN i.id AS id, i.number AS number, count(m) AS milestone_count",
    ):
        if row["milestone_count"] > 1:
            raise GraphError(
                "ambiguous_invoice",
                f"Invoice {row['number']} is linked to {row['milestone_count']} milestones; "
                "exactly one is allowed.",
            )


def _recalc_statuses(conn, project_id: str) -> None:
    """Set stored milestone status from done markers, invoices and parents."""
    rows = _fetch(
        conn,
        "MATCH (p:Project {id: $pid})-[:HAS_MILESTONE]->(m:Milestone) "
        "RETURN m.id AS id, m.status AS status ORDER BY m.name",
        {"pid": project_id},
    )
    if not rows:
        return
    parents_multi: dict[str, list[str]] = {}
    for row in _fetch(
        conn,
        "MATCH (p:Project {id: $pid})-[:HAS_MILESTONE]->(m:Milestone)"
        "-[:DEPENDS_ON]->(d:Milestone) RETURN m.id AS source, d.id AS target",
        {"pid": project_id},
    ):
        parents_multi.setdefault(row["source"], []).append(row["target"])
    invoices = {
        row["milestone_id"]: row["status"]
        for row in _fetch(
            conn,
            "MATCH (p:Project {id: $pid})-[:HAS_MILESTONE]->(m:Milestone)"
            "-[:INVOICED]->(i:Invoice) RETURN m.id AS milestone_id, i.status AS status",
            {"pid": project_id},
        )
    }
    memo: dict[str, str] = {}
    status_by_id = {row["id"]: row["status"] for row in rows}

    def resolve(mid: str, seen: set[str]) -> str:
        if mid in memo:
            return memo[mid]
        if mid in seen:
            return "BLOCKED"
        stored = status_by_id.get(mid)
        if stored is None:
            return "UNKNOWN"
        if stored == "DONE":
            memo[mid] = "DONE"
            return "DONE"
        invoice = invoices.get(mid)
        if invoice == "PAID":
            memo[mid] = "PAID"
            return "PAID"
        if invoice == "SENT":
            memo[mid] = "SENT"
            return "SENT"
        if any(resolve(parent, seen | {mid}) != "DONE" for parent in parents_multi.get(mid, [])):
            memo[mid] = "BLOCKED"
            return "BLOCKED"
        memo[mid] = "READY"
        return "READY"

    for row in rows:
        status = resolve(row["id"], set())
        if status != row["status"]:
            conn.execute(
                "MATCH (m:Milestone {id: $id}) SET m.status = $status",
                {"id": row["id"], "status": status},
            )


def _load_project(conn, project_id: str) -> dict:
    projects = _fetch(
        conn,
        "MATCH (p:Project {id: $id}) RETURN p.id AS id, p.name AS name, p.status AS status",
        {"id": project_id},
    )
    if not projects:
        raise GraphError("not_found", f"Project {project_id} was not found.", 404)
    project = projects[0]
    assert_store_integrity(conn)

    parties = _fetch(
        conn,
        "MATCH (p:Project {id: $id})<-[:COMMISSIONED]-(c:Party) "
        "RETURN c.id AS id, c.name AS name, c.kind AS kind",
        {"id": project_id},
    )
    owners = _fetch(
        conn,
        "MATCH (p:Project {id: $id})<-[:WORKED_ON]-(o:Party) "
        "RETURN o.id AS id, o.name AS name, o.kind AS kind",
        {"id": project_id},
    )
    skills = [
        row["name"]
        for row in _fetch(
            conn,
            "MATCH (p:Project {id: $id})-[:NEEDS_SKILL]->(s:Skill) "
            "RETURN s.name AS name ORDER BY s.name",
            {"id": project_id},
        )
    ]

    milestone_rows = _fetch(
        conn,
        "MATCH (p:Project {id: $id})-[:HAS_MILESTONE]->(m:Milestone) "
        "RETURN m.id AS id, m.name AS name, m.status AS status, "
        "m.amount_cents AS amount_cents, m.order AS sort_order "
        "ORDER BY m.order, m.name",
        {"id": project_id},
    )

    invoice_rows = _fetch(
        conn,
        "MATCH (p:Project {id: $id})-[:HAS_MILESTONE]->(m:Milestone)"
        "-[:INVOICED]->(i:Invoice) "
        "OPTIONAL MATCH (i)-[:PAID_BY]->(pay:Payment) "
        "RETURN m.id AS milestone_id, i.id AS id, i.number AS number, "
        "i.status AS status, i.amount_cents AS amount_cents, "
        "pay.id AS payment_id, pay.amount_cents AS payment_amount, "
        "pay.method AS method, pay.recorded_at AS recorded_at "
        "ORDER BY i.number",
        {"id": project_id},
    )
    invoices_by_milestone: dict[str, list[dict]] = {}
    payments: list[dict] = []
    for row in invoice_rows:
        invoice = {
            "id": row["id"],
            "number": row["number"],
            "status": row["status"],
            "amount_cents": row["amount_cents"],
        }
        invoices_by_milestone.setdefault(row["milestone_id"], []).append(invoice)
        if row["payment_id"]:
            payments.append(
                {
                    "id": row["payment_id"],
                    "invoice_id": row["id"],
                    "invoice": row["number"],
                    "amount_cents": row["payment_amount"],
                    "method": row["method"],
                    "recorded_at": row["recorded_at"],
                }
            )

    deliverable_rows = _fetch(
        conn,
        "MATCH (p:Project {id: $id})-[:HAS_MILESTONE]->(m:Milestone)"
        "-[:PRODUCES]->(d:Deliverable) "
        "OPTIONAL MATCH (d)<-[:UNLOCKS]-(pay:Payment) "
        "RETURN m.id AS milestone_id, d.id AS id, d.name AS name, "
        "pay.id AS payment_id, pay.amount_cents AS payment_amount "
        "ORDER BY d.name",
        {"id": project_id},
    )
    deliverables_by_milestone: dict[str, list[dict]] = {}
    seen_deliverables: set[str] = set()
    for row in deliverable_rows:
        if row["id"] in seen_deliverables:
            continue
        seen_deliverables.add(row["id"])
        deliverables_by_milestone.setdefault(row["milestone_id"], []).append(
            {
                "id": row["id"],
                "name": row["name"],
                "unlocked": bool(row["payment_id"]),
                "payment_id": row["payment_id"],
            }
        )

    dependency_rows = _fetch(
        conn,
        "MATCH (p:Project {id: $id})-[:HAS_MILESTONE]->(m:Milestone)"
        "-[:DEPENDS_ON]->(d:Milestone) "
        "OPTIONAL MATCH (d)-[:INVOICED]->(i:Invoice) "
        "RETURN m.id AS source, d.id AS target, d.name AS target_name, "
        "d.status AS target_status, i.id AS invoice_id, i.number AS invoice_number, "
        "i.status AS invoice_status, i.amount_cents AS invoice_amount "
        "ORDER BY source, target, i.number",
        {"id": project_id},
    )
    parents: dict[str, list[str]] = {}
    external: dict[str, dict] = {}
    for row in dependency_rows:
        parents.setdefault(row["source"], []).append(row["target"])
        if row["target"] not in external:
            external[row["target"]] = {
                "name": row["target_name"],
                "status": row["target_status"],
                "invoices": [],
            }
        if row["invoice_id"]:
            external[row["target"]]["invoices"].append(
                {
                    "id": row["invoice_id"],
                    "number": row["invoice_number"],
                    "status": row["invoice_status"],
                    "amount_cents": row["invoice_amount"],
                }
            )
    for source, targets in parents.items():
        parents[source] = list(dict.fromkeys(targets))
    dependencies = [
        {"source": source, "target": target}
        for source, targets in parents.items()
        for target in targets
    ]
    dependencies.sort(key=lambda edge: (edge["source"], edge["target"]))

    by_id: dict[str, dict] = {}
    for row in milestone_rows:
        by_id[row["id"]] = {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "amount_cents": row["amount_cents"],
            "sort_order": row["sort_order"],
            "invoice": (invoices_by_milestone.get(row["id"]) or [None])[0],
            "deliverables": deliverables_by_milestone.get(row["id"], []),
            "parents": [],
        }
    for milestone_id, info in external.items():
        if milestone_id in by_id:
            continue
        invoices = info["invoices"]
        sent = next((invoice for invoice in invoices if invoice["status"] == "SENT"), None)
        by_id[milestone_id] = {
            "id": milestone_id,
            "name": info["name"],
            "status": info["status"],
            "amount_cents": None,
            "sort_order": 9999,
            "invoice": sent or (invoices[0] if invoices else None),
            "deliverables": [],
            "parents": [],
            "external": True,
        }

    milestones: list[dict] = []
    for row in milestone_rows:
        milestone = by_id[row["id"]]
        milestone["parents"] = [
            {"id": pid, "name": by_id[pid]["name"]} for pid in parents.get(row["id"], [])
        ]
        milestone["blocked_by"] = (
            [] if milestone["status"] == "DONE" else _blocked_by(milestone, parents, by_id)
        )
        milestone["blocked"] = bool(milestone["blocked_by"])
        invoice = milestone["invoice"]
        if milestone["status"] == "DONE":
            reason = "already_done"
        elif invoice and invoice["status"] == "SENT":
            reason = "invoice_unpaid"
        elif milestone["blocked_by"]:
            reason = "blocked"
        elif any(by_id[p]["status"] != "DONE" for p in parents.get(row["id"], [])):
            reason = "blocked"
        else:
            reason = None
        milestone["can_complete"] = reason is None
        milestone["complete_block_reason"] = reason
        milestone["can_pay"] = bool(
            invoice
            and invoice["status"] == "SENT"
            and milestone["deliverables"]
            and not any(deliverable["unlocked"] for deliverable in milestone["deliverables"])
        )
        if not invoice or invoice["status"] != "SENT":
            milestone["pay_block_reason"] = "no_open_invoice"
        elif not milestone["deliverables"]:
            milestone["pay_block_reason"] = "no_deliverable"
        elif any(deliverable["unlocked"] for deliverable in milestone["deliverables"]):
            milestone["pay_block_reason"] = "already_unlocked"
        else:
            milestone["pay_block_reason"] = None
        milestone["unlocked"] = any(d["unlocked"] for d in milestone["deliverables"])
        milestones.append(milestone)

    done = sum(1 for m in milestones if m["status"] == "DONE")
    blocked = sum(1 for m in milestones if m["blocked"])
    paid_cents = sum(
        invoice["amount_cents"]
        for invoices in invoices_by_milestone.values()
        for invoice in invoices
        if invoice["status"] == "PAID"
    )
    total_cents = sum(m["amount_cents"] for m in milestones)
    unlocked = sum(1 for m in milestones for d in m["deliverables"] if d["unlocked"])

    next_milestone = next((m for m in milestones if m["status"] != "DONE"), None)
    client = parties[0] if parties else None
    owner = owners[0] if owners else None

    graph_nodes = [
        {
            "id": project["id"],
            "kind": "Project",
            "label": project["name"],
            "status": project["status"],
            "amount_cents": None,
            "meta": " · ".join(filter(None, [client["name"] if client else None, owner["name"] if owner else None])),
        }
    ]
    graph_edges: list[dict] = []
    for party in parties:
        graph_nodes.append(
            {
                "id": party["id"],
                "kind": "Party",
                "label": party["name"],
                "status": None,
                "amount_cents": None,
                "meta": "Client",
            }
        )
        graph_edges.append({"from": party["id"], "to": project["id"], "type": "COMMISSIONED"})
    for party in owners:
        graph_nodes.append(
            {
                "id": party["id"],
                "kind": "Party",
                "label": party["name"],
                "status": None,
                "amount_cents": None,
                "meta": "Freelancer",
            }
        )
        graph_edges.append({"from": party["id"], "to": project["id"], "type": "WORKED_ON"})

    for milestone in milestones:
        meta = milestone["invoice"]["number"] if milestone["invoice"] else "No invoice"
        graph_nodes.append(
            {
                "id": milestone["id"],
                "kind": "Milestone",
                "label": milestone["name"],
                "status": milestone["status"],
                "amount_cents": milestone["amount_cents"],
                "meta": meta,
            }
        )
        graph_edges.append(
            {"from": project["id"], "to": milestone["id"], "type": "HAS_MILESTONE"}
        )
        for parent in milestone["parents"]:
            graph_edges.append({"from": milestone["id"], "to": parent["id"], "type": "DEPENDS_ON"})
        for deliverable in milestone["deliverables"]:
            graph_nodes.append(
                {
                    "id": deliverable["id"],
                    "kind": "Deliverable",
                    "label": deliverable["name"],
                    "status": "UNLOCKED" if deliverable["unlocked"] else "LOCKED",
                    "amount_cents": None,
                    "meta": milestone["name"],
                }
            )
            graph_edges.append(
                {"from": milestone["id"], "to": deliverable["id"], "type": "PRODUCES"}
            )
        if milestone["invoice"]:
            invoice = milestone["invoice"]
            graph_nodes.append(
                {
                    "id": invoice["id"],
                    "kind": "Invoice",
                    "label": invoice["number"],
                    "status": invoice["status"],
                    "amount_cents": invoice["amount_cents"],
                    "meta": milestone["name"],
                }
            )
            graph_edges.append(
                {"from": milestone["id"], "to": invoice["id"], "type": "INVOICED"}
            )
            for payment in payments:
                if payment["invoice_id"] != invoice["id"]:
                    continue
                graph_nodes.append(
                    {
                        "id": payment["id"],
                        "kind": "Payment",
                        "label": "Sample payment",
                        "status": "PAID",
                        "amount_cents": payment["amount_cents"],
                        "meta": payment["method"],
                    }
                )
                graph_edges.append(
                    {"from": invoice["id"], "to": payment["id"], "type": "PAID_BY"}
                )
                for deliverable in milestone["deliverables"]:
                    if deliverable["unlocked"]:
                        graph_edges.append(
                            {"from": payment["id"], "to": deliverable["id"], "type": "UNLOCKS"}
                        )

    return {
        "project": {
            "id": project["id"],
            "name": project["name"],
            "status": project["status"],
            "client": client["name"] if client else None,
            "owner": owner["name"] if owner else None,
            "skills": skills,
        },
        "stats": {
            "milestones": len(milestones),
            "done": done,
            "blocked": blocked,
            "paid_cents": paid_cents,
            "total_cents": total_cents,
            "unlocked_deliverables": unlocked,
        },
        "milestones": milestones,
        "dependencies": dependencies,
        "invoices": [
            invoice
            for milestone in milestones
            for invoice in ([milestone["invoice"]] if milestone["invoice"] else [])
        ],
        "payments": payments,
        "next": (
            {
                "id": next_milestone["id"],
                "name": next_milestone["name"],
                "status": next_milestone["status"],
                "amount_cents": next_milestone["amount_cents"],
            }
            if next_milestone
            else None
        ),
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
    }


def get_project(conn, project_id: str) -> dict:
    return _load_project(conn, project_id)


def list_projects(conn) -> list[dict]:
    rows = _fetch(
        conn,
        "MATCH (p:Project) RETURN p.id AS id, p.name AS name, p.status AS status ORDER BY p.name",
    )
    rows.sort(key=lambda row: (0 if row["status"] == "active" else 1, row["name"]))
    projects = []
    for row in rows:
        detail = _load_project(conn, row["id"])
        projects.append(
            {
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "client": detail["project"]["client"],
                "owner": detail["project"]["owner"],
                "milestones": detail["stats"]["milestones"],
                "done": detail["stats"]["done"],
                "blocked": detail["stats"]["blocked"],
                "paid_cents": detail["stats"]["paid_cents"],
                "total_cents": detail["stats"]["total_cents"],
                "next": detail["next"],
                "milestone_states": [
                    {"id": m["id"], "name": m["name"], "status": m["status"]}
                    for m in detail["milestones"]
                ],
            }
        )
    return projects


def agent_state(conn) -> dict:
    """Return the compact, grounded state the browser assistant reads.

    The human UI uses the richer project detail; this keeps names, statuses,
    invoice numbers, blocked paths and amounts without graph layout data.
    """
    rows = _fetch(
        conn,
        "MATCH (p:Project) RETURN p.id AS id, p.name AS name, p.status AS status ORDER BY p.name",
    )
    rows.sort(key=lambda row: (0 if row["status"] == "active" else 1, row["name"]))
    projects = []
    for row in rows:
        detail = get_project(conn, row["id"])
        projects.append(
            {
                "id": detail["project"]["id"],
                "name": detail["project"]["name"],
                "status": detail["project"]["status"],
                "client": detail["project"]["client"],
                "owner": detail["project"]["owner"],
                "stats": detail["stats"],
                "next": detail["next"],
                "milestones": [
                    {
                        "id": milestone["id"],
                        "name": milestone["name"],
                        "status": milestone["status"],
                        "amount_cents": milestone["amount_cents"],
                        "invoice": milestone["invoice"],
                        "parents": [parent["name"] for parent in milestone["parents"]],
                        "blocked_by": milestone["blocked_by"],
                        "can_complete": milestone["can_complete"],
                        "can_pay": milestone["can_pay"],
                        "deliverables": [
                            {"name": deliverable["name"], "unlocked": deliverable["unlocked"]}
                            for deliverable in milestone["deliverables"]
                        ],
                    }
                    for milestone in detail["milestones"]
                ],
                "invoices": detail["invoices"],
                "payments": detail["payments"],
            }
        )
    skills = [
        skill["name"]
        for skill in _fetch(
            conn,
            "MATCH (s:Skill) RETURN s.name AS name ORDER BY s.name",
        )
    ]
    counts = _fetch(
        conn,
        "MATCH (n) WITH labels(n) AS labels UNWIND labels AS label "
        "RETURN label, count(*) AS count ORDER BY label",
    )
    return {
        "mode": "sample",
        "note": "Sample data only. Amounts are integer cents. No real money, live PayPal or email.",
        "projects": projects,
        "skills": skills,
        "node_counts": counts,
    }


def _invoice_row(conn, invoice_id: str) -> dict:
    rows = _fetch(
        conn,
        "MATCH (i:Invoice {id: $id})<-[:INVOICED]-(m:Milestone)"
        "<-[:HAS_MILESTONE]-(p:Project) "
        "RETURN i.id AS invoice_id, i.number AS number, i.status AS status, "
        "i.amount_cents AS amount_cents, m.id AS milestone_id, m.name AS milestone_name, "
        "m.status AS milestone_status, p.id AS project_id, p.name AS project_name",
        {"id": invoice_id},
    )
    if not rows:
        raise GraphError("not_found", f"Invoice {invoice_id} was not found.", 404)
    if len(rows) > 1:
        raise GraphError(
            "ambiguous_invoice",
            f"Invoice {invoice_id} is linked to {len(rows)} milestones; "
            "exactly one is allowed.",
        )
    row = rows[0]
    invoice_count = _fetch(
        conn,
        "MATCH (m:Milestone {id: $id})-[:INVOICED]->(i:Invoice) "
        "RETURN count(i) AS invoice_count",
        {"id": row["milestone_id"]},
    )[0]["invoice_count"]
    if invoice_count > 1:
        raise GraphError(
            "multiple_invoices",
            f"{row['milestone_name']} has {invoice_count} invoices; "
            "exactly one invoice per milestone is allowed.",
        )
    return row


def _deliverable_rows(conn, milestone_id: str) -> list[dict]:
    return _fetch(
        conn,
        "MATCH (m:Milestone {id: $id})-[:PRODUCES]->(d:Deliverable) "
        "OPTIONAL MATCH (d)<-[:UNLOCKS]-(pay:Payment) "
        "RETURN d.id AS id, d.name AS name, pay.id AS payment_id ORDER BY d.name",
        {"id": milestone_id},
    )


def preview_payment(conn, invoice_id: str) -> dict:
    assert_store_integrity(conn)
    row = _invoice_row(conn, invoice_id)
    if row["status"] == "PAID":
        raise GraphError("already_paid", f"Invoice {row['number']} is already paid.")
    if row["status"] != "SENT":
        raise GraphError(
            "not_payable", f"Invoice {row['number']} is {row['status']}, not SENT."
        )

    deliverables = _deliverable_rows(conn, row["milestone_id"])
    if not deliverables:
        raise GraphError(
            "no_deliverable",
            f"{row['milestone_name']} has no deliverable to unlock.",
        )
    if any(d["payment_id"] for d in deliverables):
        raise GraphError(
            "already_unlocked",
            f"A deliverable for {row['milestone_name']} is already unlocked.",
        )

    return {
        "invoice": {
            "id": row["invoice_id"],
            "number": row["number"],
            "status": row["status"],
            "amount_cents": row["amount_cents"],
        },
        "milestone": {
            "id": row["milestone_id"],
            "name": row["milestone_name"],
            "status": row["milestone_status"],
        },
        "project": {"id": row["project_id"], "name": row["project_name"]},
        "amount_cents": row["amount_cents"],
        "deliverables": [{"id": d["id"], "name": d["name"]} for d in deliverables],
        "status_changes": [
            {"entity": f"Invoice {row['number']}", "from": row["status"], "to": "PAID"},
            {
                "entity": f"Milestone {row['milestone_name']}",
                "from": row["milestone_status"],
                "to": "DONE" if row["milestone_status"] == "DONE" else "PAID",
            },
        ],
        "edges_to_create": [
            f"Invoice {row['number']} -[:PAID_BY]-> Payment",
            *[f"Payment -[:UNLOCKS]-> {d['name']}" for d in deliverables],
        ],
        "note": (
            "Dependent milestones stay blocked until this milestone is marked done. "
            "No other deliverable is unlocked."
        ),
    }


def record_payment(conn, invoice_id: str, amount_cents: int) -> dict:
    if (
        not isinstance(amount_cents, int)
        or isinstance(amount_cents, bool)
        or amount_cents <= 0
    ):
        raise GraphError("invalid_amount", "Amount must be a positive integer number of cents.", 422)

    preview = preview_payment(conn, invoice_id)
    if amount_cents != preview["amount_cents"]:
        raise GraphError(
            "amount_mismatch",
            f"Invoice {preview['invoice']['number']} is "
            f"{preview['amount_cents']} cents; the payment was {amount_cents}.",
            422,
        )

    payment_id = _new_id("pay")
    with transaction(conn):
        conn.execute(
            "MATCH (i:Invoice {id: $id}) SET i.status = 'PAID'",
            {"id": invoice_id},
        )
        conn.execute(
            "CREATE (:Payment {id: $id, amount_cents: $amount, method: 'sample', "
            "recorded_at: $at})",
            {"id": payment_id, "amount": amount_cents, "at": _now()},
        )
        conn.execute(
            "MATCH (i:Invoice {id: $invoice}), (p:Payment {id: $payment}) "
            "CREATE (i)-[:PAID_BY]->(p)",
            {"invoice": invoice_id, "payment": payment_id},
        )
        for deliverable in preview["deliverables"]:
            conn.execute(
                "MATCH (p:Payment {id: $payment}), (d:Deliverable {id: $deliverable}) "
                "CREATE (p)-[:UNLOCKS]->(d)",
                {"payment": payment_id, "deliverable": deliverable["id"]},
            )
        _recalc_statuses(conn, preview["project"]["id"])

    detail = get_project(conn, preview["project"]["id"])
    return {
        "payment_id": payment_id,
        "invoice_id": invoice_id,
        "milestone_id": preview["milestone"]["id"],
        "amount_cents": amount_cents,
        "unlocked": preview["deliverables"],
        "project": detail,
    }


def complete_milestone(conn, milestone_id: str) -> dict:
    rows = _fetch(
        conn,
        "MATCH (m:Milestone {id: $id})<-[:HAS_MILESTONE]-(p:Project) "
        "RETURN p.id AS project_id",
        {"id": milestone_id},
    )
    if not rows:
        raise GraphError("not_found", f"Milestone {milestone_id} was not found.", 404)
    project_id = rows[0]["project_id"]
    detail = get_project(conn, project_id)
    milestone = next((m for m in detail["milestones"] if m["id"] == milestone_id), None)
    if milestone is None:
        raise GraphError("not_found", f"Milestone {milestone_id} was not found.", 404)
    if milestone["status"] == "DONE":
        raise GraphError("already_done", f"{milestone['name']} is already done.")
    if milestone["complete_block_reason"] == "invoice_unpaid":
        raise GraphError(
            "invoice_unpaid",
            f"{milestone['invoice']['number']} must be paid before "
            f"{milestone['name']} can be done.",
        )
    if milestone["blocked_by"]:
        first = milestone["blocked_by"][0]
        raise GraphError(
            "blocked",
            f"{milestone['name']} is blocked by {' → '.join(reversed(first['path']))}.",
        )

    with transaction(conn):
        conn.execute(
            "MATCH (m:Milestone {id: $id}) SET m.status = 'DONE'",
            {"id": milestone_id},
        )
        _recalc_statuses(conn, project_id)

    detail = get_project(conn, project_id)
    updated = next(m for m in detail["milestones"] if m["id"] == milestone_id)
    return {**detail, "milestone": updated}


def _next_invoice_number(conn) -> str:
    numbers = [row["number"] for row in _fetch(conn, "MATCH (i:Invoice) RETURN i.number AS number")]
    values = []
    for number in numbers:
        match = re.search(r"(\d+)$", number or "")
        if match:
            values.append(int(match.group(1)))
    return f"WG-{max(values, default=1000) + 1}"


def _ensure_reference_data(conn) -> None:
    parties = [
        {"id": "party-northwind", "name": "Northwind Studio", "kind": "client", "location": "Berlin"},
        {"id": "party-mira", "name": "Mira Chen", "kind": "freelancer", "location": "Hyderabad"},
    ]
    for party in parties:
        if not _fetch(
            conn, "MATCH (p:Party {id: $id}) RETURN p.id AS id", {"id": party["id"]}
        ):
            conn.execute(
                "CREATE (:Party {id: $id, name: $name, kind: $kind, location: $location})",
                party,
            )
    skills = [
        {"id": "skill-design", "name": "Design systems"},
        {"id": "skill-build", "name": "Front-end build"},
    ]
    for skill in skills:
        if not _fetch(
            conn, "MATCH (s:Skill {id: $id}) RETURN s.id AS id", {"id": skill["id"]}
        ):
            conn.execute("CREATE (:Skill {id: $id, name: $name})", skill)


def _unique_project_name(conn, requested: str) -> str:
    base = requested.strip()
    if not base:
        raise GraphError("invalid_name", "Project name cannot be blank.", 422)
    if len(base) > 80:
        raise GraphError("invalid_name", "Project name must be 80 characters or fewer.", 422)
    existing = {row["name"] for row in _fetch(conn, "MATCH (p:Project) RETURN p.name AS name")}
    candidate = base
    counter = 2
    while candidate in existing:
        candidate = f"{base} {counter}"
        counter += 1
    return candidate


def create_sample_project(conn, name: str | None = None) -> dict:
    assert_store_integrity(conn)
    project_name = _unique_project_name(conn, name or "Juniper launch")
    suffix = uuid.uuid4().hex[:10]
    project_id = f"proj-{suffix}"
    milestone_specs = [
        {"key": "scope", "name": "Scope", "status": "DONE", "amount": 120000, "deliverable": "Scope note"},
        {"key": "design", "name": "Design", "status": "SENT", "amount": 180000, "deliverable": "Design system kit"},
        {"key": "build", "name": "Build", "status": "BLOCKED", "amount": 240000, "deliverable": "Build preview"},
        {"key": "handover", "name": "Handover", "status": "BLOCKED", "amount": 60000, "deliverable": "Handover pack"},
    ]
    ids = {spec["key"]: f"ms-{suffix}-{index}" for index, spec in enumerate(milestone_specs, 1)}
    deliverable_ids = {
        spec["key"]: f"del-{suffix}-{index}"
        for index, spec in enumerate(milestone_specs, 1)
    }
    design_invoice_id = f"inv-{suffix}"
    scope_invoice_id = f"inv-{suffix}-scope"
    scope_payment_id = f"pay-{suffix}-scope"
    next_number = int(_next_invoice_number(conn).split("-")[1])
    scope_invoice_number = f"WG-{next_number}"
    design_invoice_number = f"WG-{next_number + 1}"

    with transaction(conn):
        _ensure_reference_data(conn)
        conn.execute(
            "CREATE (:Project {id: $id, name: $name, status: 'active'})",
            {"id": project_id, "name": project_name},
        )
        conn.execute(
            "MATCH (c:Party {id: 'party-northwind'}), (p:Project {id: $project}) "
            "CREATE (c)-[:COMMISSIONED]->(p)",
            {"project": project_id},
        )
        conn.execute(
            "MATCH (o:Party {id: 'party-mira'}), (p:Project {id: $project}) "
            "CREATE (o)-[:WORKED_ON]->(p)",
            {"project": project_id},
        )
        for skill in ("skill-design", "skill-build"):
            conn.execute(
                "MATCH (p:Project {id: $project}), (s:Skill {id: $skill}) "
                "CREATE (p)-[:NEEDS_SKILL]->(s)",
                {"project": project_id, "skill": skill},
            )
        for index, spec in enumerate(milestone_specs, 1):
            conn.execute(
                "CREATE (:Milestone {id: $id, name: $name, status: $status, "
                "amount_cents: $amount, order: $order})",
                {
                    "id": ids[spec["key"]],
                    "name": spec["name"],
                    "status": spec["status"],
                    "amount": spec["amount"],
                    "order": index,
                },
            )
            conn.execute(
                "MATCH (p:Project {id: $project}), (m:Milestone {id: $milestone}) "
                "CREATE (p)-[:HAS_MILESTONE]->(m)",
                {"project": project_id, "milestone": ids[spec["key"]]},
            )
            conn.execute(
                "CREATE (:Deliverable {id: $id, name: $name})",
                {"id": deliverable_ids[spec["key"]], "name": spec["deliverable"]},
            )
            conn.execute(
                "MATCH (m:Milestone {id: $milestone}), (d:Deliverable {id: $deliverable}) "
                "CREATE (m)-[:PRODUCES]->(d)",
                {"milestone": ids[spec["key"]], "deliverable": deliverable_ids[spec["key"]]},
            )
        for child, parent in (
            ("design", "scope"),
            ("build", "design"),
            ("handover", "build"),
        ):
            conn.execute(
                "MATCH (a:Milestone {id: $child}), (b:Milestone {id: $parent}) "
                "CREATE (a)-[:DEPENDS_ON]->(b)",
                {"child": ids[child], "parent": ids[parent]},
            )
        conn.execute(
            "CREATE (:Invoice {id: $id, number: $number, status: 'PAID', "
            "amount_cents: $amount})",
            {
                "id": scope_invoice_id,
                "number": scope_invoice_number,
                "amount": milestone_specs[0]["amount"],
            },
        )
        conn.execute(
            "MATCH (m:Milestone {id: $milestone}), (i:Invoice {id: $invoice}) "
            "CREATE (m)-[:INVOICED]->(i)",
            {"milestone": ids["scope"], "invoice": scope_invoice_id},
        )
        conn.execute(
            "CREATE (:Payment {id: $id, amount_cents: $amount, method: 'sample', "
            "recorded_at: $at})",
            {
                "id": scope_payment_id,
                "amount": milestone_specs[0]["amount"],
                "at": _now(),
            },
        )
        conn.execute(
            "MATCH (i:Invoice {id: $invoice}), (p:Payment {id: $payment}) "
            "CREATE (i)-[:PAID_BY]->(p)",
            {"invoice": scope_invoice_id, "payment": scope_payment_id},
        )
        conn.execute(
            "MATCH (p:Payment {id: $payment}), (d:Deliverable {id: $deliverable}) "
            "CREATE (p)-[:UNLOCKS]->(d)",
            {"payment": scope_payment_id, "deliverable": deliverable_ids["scope"]},
        )
        conn.execute(
            "CREATE (:Invoice {id: $id, number: $number, status: 'SENT', "
            "amount_cents: $amount})",
            {
                "id": design_invoice_id,
                "number": design_invoice_number,
                "amount": milestone_specs[1]["amount"],
            },
        )
        conn.execute(
            "MATCH (m:Milestone {id: $milestone}), (i:Invoice {id: $invoice}) "
            "CREATE (m)-[:INVOICED]->(i)",
            {"milestone": ids["design"], "invoice": design_invoice_id},
        )
        _recalc_statuses(conn, project_id)

    return get_project(conn, project_id)
