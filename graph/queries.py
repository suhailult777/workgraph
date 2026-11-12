"""Read queries used by the API and the Phase 0 tests."""

from __future__ import annotations

BLOCKED_BY_UNPAID = """
MATCH (later:Milestone)-[:DEPENDS_ON*1..3]->(waiting:Milestone)-[:INVOICED]->(inv:Invoice)
WHERE inv.status = 'SENT'
RETURN DISTINCT later.name AS blocked, waiting.name AS waiting_on,
       inv.number AS invoice, inv.amount_cents AS amount_cents
ORDER BY blocked
"""

PAID_SKILL_HISTORY = """
MATCH (skill:Skill {name: $skill})<-[:NEEDS_SKILL]-(project:Project)<-[:WORKED_ON]-(party:Party),
      (project)-[:HAS_MILESTONE]->(m:Milestone)-[:INVOICED]->(inv:Invoice)-[:PAID_BY]->(pay:Payment)
RETURN DISTINCT party.name AS party, project.name AS project,
       m.name AS milestone, pay.amount_cents AS amount_cents
ORDER BY party, milestone
"""

UNLOCK_PATHS = """
MATCH (pay:Payment)-[:UNLOCKS]->(d:Deliverable)<-[:PRODUCES]-(m:Milestone)
RETURN d.name AS deliverable, m.name AS milestone, pay.amount_cents AS paid_cents
ORDER BY deliverable
"""

SUMMARY = """
MATCH (n)
WITH labels(n) AS kinds
UNWIND kinds AS kind
RETURN kind AS label, count(*) AS count
ORDER BY label
"""


def rows(conn, cypher: str, params: dict | None = None) -> list[dict]:
    return [r.data() for r in conn.execute(cypher, params or {}).fetchall()]
