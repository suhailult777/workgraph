# Relate setup and placement

WorkGraph uses **Relate** (`relate-db==1.0.1`) as an embedded graph database.
It is not Aura, not a hosted Neo4j account, and not a separate graph server.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\reset_seed.py --force
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8090
```

The store is `data/workgraph.rl`, committed so a judge can inspect the sample
graph without an account. Relate keeps a Windows file lock while the server is
running, so stop uvicorn before a reset or a read-only CLI query.

Read it without the app:

```powershell
relate --database data/workgraph.rl --read-only --mode table "MATCH (n) RETURN count(n) AS n"
```

Or in Python:

```python
import relate
conn = relate.connect("data/workgraph.rl", read_only=True)
print([row.data() for row in conn.execute("MATCH (n) RETURN labels(n) AS labels, count(*) AS n").fetchall()])
conn.close()
```

## What the graph stores

- `Party-[:WORKED_ON]->Project`
- `Project-[:HAS_MILESTONE]->Milestone`
- `Milestone-[:DEPENDS_ON]->Milestone`
- `Milestone-[:INVOICED]->Invoice-[:PAID_BY]->Payment-[:UNLOCKS]->Deliverable`
- `Party-[:HAS_SKILL]->Skill` and `Project-[:NEEDS_SKILL]->Skill`
- `AssistantQuota` nodes for daily assistant caps
- `PayPalOrder` nodes for sandbox order records

The seed has 28 nodes and 40 relationships. A new sample project adds four
milestones, three dependencies, two invoices, one sample payment and four
deliverables.

## Vercel deployment

Vercel Functions cannot write to the project filesystem. The app therefore:

1. Uses `/tmp/workgraph.rl` when `VERCEL` is set.
2. Downloads the latest private Vercel Blob snapshot to that path before Relate
   opens it.
3. After each write, closes Relate, reads the blob ETag and uploads with
   `x-if-match` and retry.
4. Seeds from the committed `data/workgraph.rl` if the blob does not exist.

The Linux wheel for Relate is
`relate_db-1.0.1-cp39-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`.
The Windows development wheel is not used on Vercel. Actual Vercel execution is
not verified until a deploy.

## Limits

- Relate is an experimental Neo4j Labs project, not a supported Neo4j product.
- The store is a single embedded file. It is not multi-writer.
- The Blob snapshot is the durable copy; `/tmp` is scratch.
- The Blob snapshot uses one writer at a time. `x-if-match` prevents a blind
  overwrite and retries a 412, but it does not merge two graphs. Concurrent
  Vercel instances can replace each other's snapshot. Use a transactional
  database if the graph must support concurrent writers.
- The graph is sample data only. No real payments or money are stored.
- A reset discards local sample changes. It never touches a Vercel Blob
  snapshot; use the Blob dashboard for that.
