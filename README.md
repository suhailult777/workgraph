# WorkGraph

WorkGraph is a new open agentic website for freelance work: projects, milestone
dependencies, invoices and sample payments live in a persistent Relate graph.
People and browser agents read and change the same graph.

**Status: Phase 0 spikes, 12-16 Nov 2026.** Local only. Not pushed, hosted or
submitted. Phase 1 feature work has not started.

## What is here

| Path | Purpose |
| --- | --- |
| `backend/app.py` | FastAPI: health, graph reads, public artifacts, React build |
| `frontend/` | React + TypeScript skeleton (Vite) |
| `public/` | Agentic Web artifacts: manifest, resolved network, links, runtime |
| `public/workgraph.hocon` | Source for the published network |
| `graph/` | Relate seed loader and read queries |
| `data/workgraph.rl` | Committed Relate store (25 nodes, 37 relationships) |
| `tests/` | Graph, persistence and HTTP artifact tests |
| `scripts/judge_pass.py` | Checks the local public URLs |
| `probes/wasm/` | Throwaway Relate WASM probe, not part of the app |
| `vendor/` | Third-party checkouts, not tracked (see `.gitignore`) |

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8090
```

Open http://127.0.0.1:8090/. The seed store is already committed. To rebuild
it, delete `data/workgraph.rl` and run `python -m graph.seed`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\judge_pass.py   # needs the server running
```

## Relate placement and persistence

- Mode: **embedded Python** (`relate-db==1.0.1`), not Aura and not a hosted
  Neo4j account.
- Store: one persistent file, `data/workgraph.rl`, committed to the repo so a
  judge can inspect the sample graph without an LLM key.
- Why: the file survives process exit, needs no server, and is tiny (40 KB).
  The test `test_store_survives_process_exit` seeds it, closes the connection,
  then counts nodes in a separate Python process.
- Open and query it read-only:
  `relate --database data/workgraph.rl --read-only --mode table "MATCH (n) RETURN count(n) AS n"`
  (CLI), or `relate.connect("data/workgraph.rl", read_only=True)` in Python.

### WASM vs Python decision

**Decision: Python embedded FastAPI is the canonical graph for the local and
live demo. WASM is not the source of truth.**

The WASM probe passed: `@relate/relate-wasm` 1.0.1 ran in Chrome, answered an
in-memory two-hop query, and kept an OPFS store across a page reload from a
dedicated worker. It is usable.

It is still the wrong primary store for WorkGraph because:

1. OPFS is per-browser and per-origin. Two tabs, two judges or the phone and
   the laptop would see different graphs, so "the graph the human UI uses" is
   not shared.
2. The WASM package exposes only `new RelateDb()` (in-memory) and
   `RelateDb.open("opfs://...")`; there is no import path for the committed
   Python store, so the seed would have to be replayed as Cypher on first load.
3. The 6.9 MB `.wasm` download and a worker/OPFS lifecycle add demo risk for
   no scoreable gain in Phase 0.

Python embedded Relate gives one store that the API, the tests and a judge's
CLI can all read. Keep the WASM probe as an optional read-only in-tab graph
explorer for Phase 2 if time allows. Revisit only if the live host cannot keep
a writable disk and a snapshot-to-blob path is not acceptable.

## Agentic Web artifacts

| URL | File |
| --- | --- |
| `/agent-manifest.json` | `public/agent-manifest.json` |
| `/workgraph.network.json` | `public/workgraph.network.json` (generated) |
| `/links.json` | `public/links.json` |
| `/runtime/` | unchanged copy from `agentify-website` |
| `/agent-mcp.json` | generated discovery file |
| `/.well-known/nsdeploy*.json` | generated discovery files |
| `/site-actions.js` | read actions: graph state, blocked milestones, similar work |

Rebuild the network after changing the HOCON or the manifest:

```powershell
node vendor/agentic-web/skills/agentify-website/scripts/build_network.mjs public/workgraph.hocon --manifest public/agent-manifest.json
node vendor/agentic-web/skills/agentify-website/scripts/build_network.mjs public/workgraph.hocon --manifest public/agent-manifest.json --check
```

The runtime is Apache-2.0 and is copied unchanged. Do not edit it.

## Sample graph

Two clients, two freelancers, two projects, six milestones. `Harbour rebrand`
has a paid Discovery milestone and a SENT Design system invoice, so Build and
Handover are blocked one and two hops downstream. `Atlas dashboard` is fully
paid. The seed also has `Party-[:WORKED_ON]->Project`,
`Project-[:HAS_MILESTONE]->Milestone`, `Milestone-[:DEPENDS_ON]->Milestone`,
`Milestone-[:INVOICED]->Invoice-[:PAID_BY]->Payment-[:UNLOCKS]->Deliverable`,
and skill edges.

Example multi-hop question, answered by
`graph/queries.py:BLOCKED_BY_UNPAID`:

```cypher
MATCH (later:Milestone)-[:DEPENDS_ON*1..3]->(waiting:Milestone)-[:INVOICED]->(inv:Invoice)
WHERE inv.status = 'SENT'
RETURN DISTINCT later.name, waiting.name, inv.number, inv.amount_cents
```

Result: `Build` and `Handover` both wait on `Design system` (invoice `WG-1002`,
240000 cents).

## Limits

Read-only. No payment, no live LLM call, no PayPal, no email. The assistant
network is published and validated but is not mounted in the React page yet;
that is Phase 1 work. Amounts are integer cents in sample data.

## Licence and disclosure

Apache-2.0. See `LICENSE` and `NOTICE`. WorkGraph reuses the author's
MilestonePay *ideas* (milestone and sample-payment UX); no MilestonePay source
or git history was copied. The Agentic Web runtime is copied unchanged from
`cognizant-ai-labs/agentic-web`, and Relate is used as an embedded library.
