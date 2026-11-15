"""Retrieve a small, cited graph slice for one assistant question.

The live assistant must answer from the same Relate graph as the page. This
module scores nodes against the question, expands one hop around the best
matches, and returns a compact context block with node ids, titles and edges.
The LLM never gets the whole graph and never invents an id: the server appends a
source line when the model forgets to cite.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from graph.queries import rows

STOPWORDS = {
    "a",
    "about",
    "after",
    "again",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "been",
    "before",
    "being",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "done",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "me",
    "more",
    "most",
    "my",
    "no",
    "not",
    "now",
    "of",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "please",
    "same",
    "she",
    "should",
    "show",
    "so",
    "some",
    "such",
    "tell",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "whose",
    "why",
    "will",
    "with",
    "would",
    "yes",
    "you",
    "your",
}

STATUS_TOKENS = {
    "blocked": "BLOCKED",
    "blocks": "BLOCKED",
    "blocking": "BLOCKED",
    "unpaid": "SENT",
    "unsettled": "SENT",
    "sent": "SENT",
    "awaiting": "SENT",
    "outstanding": "SENT",
    "paid": "PAID",
    "settled": "PAID",
    "done": "DONE",
    "completed": "DONE",
    "ready": "READY",
    "active": "active",
}

KIND_TOKENS = {
    "project": "Project",
    "milestone": "Milestone",
    "invoice": "Invoice",
    "payment": "Payment",
    "deliverable": "Deliverable",
    "party": "Party",
    "client": "Party",
    "freelancer": "Party",
    "skill": "Skill",
    "order": "PayPalOrder",
}

SKIP_KINDS = {"AssistantQuota"}

ID_PREFIXES = {"wg", "inv", "ms", "pay", "del", "proj", "party", "skill", "ord", "cap"}


def _terms(question: str) -> set[str]:
    lower = question.lower()
    found: set[str] = set()
    for token in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", lower):
        if token in STOPWORDS or token in ID_PREFIXES:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        found.add(token)
        for part in re.split(r"[-_]", token):
            if len(part) >= 2 and part not in STOPWORDS and part not in ID_PREFIXES:
                found.add(part)
    return found


def _title(node: dict) -> str:
    if node.get("name"):
        return str(node["name"])
    if node.get("number"):
        return str(node["number"])
    if node.get("kind") == "Payment":
        return f"Payment {node.get('id')}"
    return str(node.get("id") or "node")


def load_nodes(conn) -> list[dict]:
    result = rows(
        conn,
        "MATCH (n) RETURN labels(n)[0] AS kind, n.id AS id, n.name AS name, "
        "n.number AS number, n.status AS status, n.amount_cents AS amount_cents, "
        "n.method AS method, n.invoice_id AS invoice_id, n.order AS sort_order",
    )
    nodes = []
    for row in result:
        kind = row.get("kind") or "Node"
        if kind in SKIP_KINDS or not row.get("id"):
            continue
        node = {
            "id": str(row["id"]),
            "kind": str(kind),
            "name": row.get("name"),
            "number": row.get("number"),
            "status": row.get("status"),
            "amount_cents": row.get("amount_cents"),
            "method": row.get("method"),
            "invoice_id": row.get("invoice_id"),
            "order": row.get("sort_order"),
        }
        if kind == "Payment" and not node["status"]:
            node["status"] = "PAID"
        node["title"] = _title(node)
        nodes.append(node)
    return nodes


def load_edges(conn) -> list[dict]:
    result = rows(
        conn,
        "MATCH (a)-[r]->(b) RETURN a.id AS source, type(r) AS type, b.id AS target",
    )
    return [
        {"source": str(row["source"]), "type": str(row["type"]), "target": str(row["target"])}
        for row in result
        if row.get("source") and row.get("target")
    ]


def _score(node: dict, question: str, terms: set[str]) -> int:
    title = node["title"].lower()
    ident = node["id"].lower()
    number = str(node.get("number") or "").lower()
    score = 0

    if ident and ident in question:
        score += 100
    if number and len(number) >= 4 and number in question:
        score += 120
    if title and title in terms:
        score += 50
    elif len(title) >= 3 and title in question:
        score += 30
    for term in terms:
        if term == ident or (number and term == number):
            score += 100
        elif term in title or term in ident or (number and term in number):
            score += 8

    kind = node["kind"].lower()
    if kind in terms or f"{kind}s" in terms:
        score += 2
    for term in terms:
        wanted = KIND_TOKENS.get(term)
        if wanted and wanted.lower() == kind:
            score += 2
        status = STATUS_TOKENS.get(term)
        if status and node.get("status") and str(node["status"]).lower() == status.lower():
            score += 2
        if term == "paid" and kind == "payment" and (
            "who" in question
            or "history" in question
            or "before" in question
            or "been paid" in question
        ):
            score += 8
        if term in {"who", "person", "freelancer", "client"} and kind == "party":
            score += 2
    if node.get("amount_cents") is not None and terms & {
        "amount",
        "amounts",
        "cents",
        "cost",
        "costs",
        "money",
        "price",
        "total",
    }:
        score += 2
    return score


def _context_node_line(node: dict) -> str:
    parts = [f"[{node['id']}]", node["kind"], f'"{node["title"]}"']
    if node.get("status"):
        parts.append(f"status={node['status']}")
    if node.get("amount_cents") is not None:
        parts.append(f"amount_cents={node['amount_cents']}")
    if node.get("method"):
        parts.append(f"method={node['method']}")
    if node.get("invoice_id"):
        parts.append(f"invoice_id={node['invoice_id']}")
    return "- " + " ".join(parts)


def _public(node: dict) -> dict:
    return {
        "id": node["id"],
        "kind": node["kind"],
        "title": node["title"],
        "status": node.get("status"),
        "amount_cents": node.get("amount_cents"),
    }


def _is_blocked_invoice_question(question: str, terms: set[str]) -> bool:
    lower = question.lower()
    asks_invoice = bool(terms & {"invoice", "invoices", "payment", "unpaid", "outstanding"})
    asks_blocked = bool(terms & {"blocked", "blocks", "blocking", "unpaid", "outstanding"})
    return asks_invoice and (asks_blocked or "until" in lower)


def _anchor_invoice(scored: list[tuple[dict, int]], question: str, terms: set[str]) -> dict | None:
    invoices = [(node, score) for node, score in scored if node["kind"] == "Invoice"]
    if not invoices:
        return None
    lower = question.lower()
    for node, _ in invoices:
        if node["id"].lower() in lower:
            return node
        number = str(node.get("number") or "").lower()
        if number and number in lower:
            return node
    if _is_blocked_invoice_question(question, terms):
        for node, _ in invoices:
            if node.get("status") == "SENT":
                return node
        return invoices[0][0]
    if invoices[0][1] >= 50:
        return invoices[0][0]
    return None


def _project_scope(project: dict, edges: list[dict], by_id: dict[str, dict]) -> set[str]:
    allowed = {
        "Project": {"HAS_MILESTONE", "NEEDS_SKILL", "COMMISSIONED", "WORKED_ON"},
        "Milestone": {"INVOICED", "PRODUCES", "DEPENDS_ON"},
        "Invoice": {"PAID_BY"},
        "Payment": {"UNLOCKS"},
    }
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["source"]].append((edge["target"], edge["type"]))
        adjacency[edge["target"]].append((edge["source"], edge["type"]))

    scope = {project["id"]}
    queue = [project["id"]]
    while queue:
        current_id = queue.pop(0)
        current = by_id.get(current_id)
        if current is None:
            continue
        edge_types = allowed.get(current["kind"])
        if not edge_types:
            continue
        for neighbor_id, edge_type in adjacency.get(current_id, []):
            if edge_type not in edge_types or neighbor_id in scope or neighbor_id not in by_id:
                continue
            scope.add(neighbor_id)
            queue.append(neighbor_id)
    return scope


def _blocked_path(
    by_id: dict[str, dict],
    edges: list[dict],
    invoice: dict,
    limit: int = 12,
) -> tuple[list[str], list[dict]]:
    """Return invoice, its milestone, project and downstream blocked milestones."""
    incoming: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        incoming[edge["target"]].append(edge)

    milestone = next(
        (
            by_id[edge["source"]]
            for edge in incoming.get(invoice["id"], [])
            if edge["type"] == "INVOICED" and edge["source"] in by_id
        ),
        None,
    )
    if milestone is None:
        return [invoice["id"]], []

    project = next(
        (
            by_id[edge["source"]]
            for edge in incoming.get(milestone["id"], [])
            if edge["type"] == "HAS_MILESTONE" and edge["source"] in by_id
        ),
        None,
    )
    dependents: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "DEPENDS_ON":
            dependents[edge["target"]].append(edge["source"])

    blocked: list[dict] = []
    visited = {milestone["id"]}
    queue = [milestone["id"]]
    while queue and len(blocked) < limit:
        parent = queue.pop(0)
        for child_id in dependents.get(parent, []):
            if child_id in visited or child_id not in by_id:
                continue
            visited.add(child_id)
            child = by_id[child_id]
            blocked.append(child)
            queue.append(child_id)

    blocked.sort(
        key=lambda node: (
            node.get("order") if node.get("order") is not None else 9999,
            node["title"].lower(),
        )
    )
    path_nodes = [invoice, milestone]
    if project is not None:
        path_nodes.append(project)
    path_nodes.extend(blocked)

    path_ids = [node["id"] for node in path_nodes]
    path_set = set(path_ids)
    path_edges = [
        edge
        for edge in edges
        if edge["source"] in path_set and edge["target"] in path_set
    ]
    return path_ids, path_edges


def retrieve_context(conn, question: str, limit: int = 8) -> dict:
    """Return the most relevant nodes, their connecting edges and a prompt block."""
    question = (question or "").strip()
    terms = _terms(question)
    nodes = load_nodes(conn)
    edges = load_edges(conn)
    by_id = {node["id"]: node for node in nodes}
    scored = [(node, _score(node, question.lower(), terms)) for node in nodes]
    scored = [(node, score) for node, score in scored if score >= 3]
    scored.sort(key=lambda item: (-item[1], item[0]["kind"], item[0]["title"].lower()))

    anchor = _anchor_invoice(scored, question, terms)
    path_ids: list[str] = []
    path_edges: list[dict] = []
    if anchor is not None:
        path_ids, path_edges = _blocked_path(by_id, edges, anchor)

    candidates = scored
    if anchor is not None:
        path_set = set(path_ids)
        project = next(
            (by_id[node_id] for node_id in path_ids if by_id[node_id]["kind"] == "Project"),
            None,
        )
        scope = _project_scope(project, edges, by_id) if project is not None else set()
        candidates = [
            (node, score)
            for node, score in scored
            if node["id"] in path_set or node["id"] in scope or score >= 50
        ]
    top = [node for node, _ in candidates[:limit]]

    if not top and not path_ids:
        return {
            "matched": [],
            "nodes": [],
            "edges": [],
            "terms": sorted(terms),
            "context": "",
        }

    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["source"]].append(edge["target"])
        adjacency[edge["target"]].append(edge["source"])

    max_nodes = min(24, max(limit + 12, 16))
    selected: dict[str, dict] = {}
    for node_id in path_ids:
        if node_id in by_id:
            selected[node_id] = by_id[node_id]
    for node in top:
        if len(selected) >= max_nodes:
            break
        selected.setdefault(node["id"], node)

    frontier: list[dict] = [by_id[node_id] for node_id in path_ids if node_id in by_id]
    frontier.extend(top[:3])
    for _ in range(2):
        next_frontier: list[dict] = []
        for node in frontier:
            for neighbor_id in adjacency.get(node["id"], []):
                if len(selected) >= max_nodes:
                    break
                neighbor = by_id.get(neighbor_id)
                if neighbor is not None and neighbor_id not in selected:
                    selected[neighbor_id] = neighbor
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if len(selected) >= max_nodes:
            break

    selected_edges = [
        edge
        for edge in edges
        if edge["source"] in selected and edge["target"] in selected
    ]
    path_edge_keys = {(edge["source"], edge["type"], edge["target"]) for edge in path_edges}
    selected_edges.sort(
        key=lambda edge: (
            0 if (edge["source"], edge["type"], edge["target"]) in path_edge_keys else 1,
            edge["source"],
            edge["type"],
            edge["target"],
        )
    )

    matched_nodes: list[dict] = []
    seen_matched: set[str] = set()
    for node_id in path_ids:
        node = by_id.get(node_id)
        if node is not None and node_id not in seen_matched:
            seen_matched.add(node_id)
            matched_nodes.append(node)
    for node in top:
        if node["id"] in seen_matched:
            continue
        if len(matched_nodes) >= max(limit, 10):
            break
        seen_matched.add(node["id"])
        matched_nodes.append(node)

    ordered = [by_id[node_id] for node_id in path_ids if node_id in by_id]
    ordered_ids = {node["id"] for node in ordered}
    ordered.extend(
        sorted(
            (node for node in selected.values() if node["id"] not in ordered_ids),
            key=lambda node: (node["kind"], node["title"].lower()),
        )
    )
    lines = [
        "Graph context for WorkGraph sample data. Amounts are integer cents.",
        "Nodes:",
    ]
    lines.extend(_context_node_line(node) for node in ordered)
    if selected_edges:
        lines.append("Edges:")
        lines.extend(
            f"- [{edge['source']}] -{edge['type']}-> [{edge['target']}]"
            for edge in selected_edges
        )
    lines.extend(
        [
            "Rules:",
            "- Answer only from these nodes and edges.",
            '- Cite each fact as [node-id] "Title".',
            '- If the context does not support an answer, reply exactly "not in the graph".',
            "- Never invent a project, milestone, invoice, amount or status.",
        ]
    )
    return {
        "matched": [_public(node) for node in matched_nodes],
        "nodes": [_public(node) for node in ordered],
        "edges": selected_edges,
        "terms": sorted(terms),
        "context": "\n".join(lines),
    }


def _normalize(text: str) -> str:
    return (
        unicodedata.normalize("NFKC", str(text or ""))
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .lower()
    )


def citations_for(answer: str, bundle: dict) -> list[dict]:
    """Return the context nodes that the answer actually cites."""
    lower = _normalize(answer)
    cited: list[dict] = []
    seen: set[str] = set()
    for node in bundle.get("nodes") or []:
        ident = str(node.get("id") or "")
        title = str(node.get("title") or "")
        if not ident or ident in seen:
            continue
        if _normalize(ident) in lower or (len(title) >= 3 and _normalize(title) in lower):
            seen.add(ident)
            cited.append(node)
    for match in re.findall(r"\[([a-zA-Z0-9][a-zA-Z0-9_-]{2,})\]", _normalize(answer)):
        if match in seen:
            continue
        for node in bundle.get("nodes") or []:
            if _normalize(node.get("id") or "") == match:
                seen.add(match)
                cited.append(node)
                break
    return cited


def source_line(bundle: dict, citations: list[dict] | None = None) -> str:
    """Compact source line for an answer that forgot to cite its nodes."""
    items = citations or (bundle.get("matched") or [])
    parts = [f'[{node["id"]}] "{node["title"]}"' for node in items[:6]]
    return "Sources: " + "; ".join(parts) if parts else ""
