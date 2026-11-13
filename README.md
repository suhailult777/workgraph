# WorkGraph

WorkGraph is a new open agentic website for freelance work: projects, milestone
dependencies, invoices and sample payments live in a persistent Relate graph.
People and browser agents read and change the same graph.

**Status: Phase 1, milestone 1 (17-20 Nov 2026).** Local only. Not pushed,
hosted or submitted. The human UI and the graph operations behind it are
working; the assistant network is published but is not mounted in the React
page yet.

## What is here

| Path | Purpose |
| --- | --- |
| `backend/app.py` | FastAPI: health, projects, payments, milestones, artifact URLs, React build |
| `frontend/` | React + TypeScript human UI (Vite): board, project graph, payment dialog |
| `public/` | Agentic Web artifacts: manifest, resolved network, links, runtime |
| `public/workgraph.hocon` | Source for the published network |
| `graph/seed.py` | Seed loader for the sample graph |
| `graph/operations.py` | Create project, preview/record payment, complete milestone, read paths |
| `graph/queries.py` | Phase 0 read queries kept for the published agent network |
| `data/workgraph.rl` | Committed Relate store (28 nodes, 40 relationships) |
| `tests/` | Graph invariants, persistence and HTTP tests |
| `scripts/reset_store.py` | Rebuild the committed sample store (`--force`) |
| `scripts/judge_pass.py` | Checks the local public URLs and the project API |
| `docs/shots/` | Phase 1 screenshots |
| `probes/wasm/` | Throwaway Relate WASM probe, not part of the app |
| `vendor/` | Third-party checkouts, not tracked (see `.gitignore`) |

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8090
```

Open http://127.0.0.1:8090/. The seed store is committed. Rebuild it only when
you intend to discard local sample changes:

```powershell
# stop the uvicorn process first; Relate keeps a file lock on Windows
.\.venv\Scripts\python.exe scripts\reset_store.py --force
```

A read-only CLI or a reset needs the server stopped because the open connection
holds a Windows file lock. Tests never touch `data/workgraph.rl`; each test
seeds its own temporary store.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\judge_pass.py   # needs the server running
```

## Human UI

- **Board**: every project with done count, blocked count, paid total and a
  milestone status strip. The create form adds a four-milestone sample project
  with a paid scope milestone and one open invoice.
- **Project**: the graph comes first: milestones, dependency arrows, invoice,
  payment and deliverable nodes. The plan below shows each milestone's blocker
  path, and the ledger shows invoices and sample payments.
- **Payment**: "Record sample payment" opens a confirmation dialog that previews
  the exact status changes and edges to create. Cancel writes nothing.
- **Complete**: "Mark milestone done" is refused by the API while a prerequisite
  is unfinished or the milestone's own invoice is unpaid.

No absolute local paths appear in the UI. The header shows the relative store
name (`data/workgraph.rl`).

### Graph operations and invariants

All writes live in `graph/operations.py`; the HTTP endpoints and the later site
actions call the same functions.

| Operation | Endpoint | Invariant |
| --- | --- | --- |
| List / read project | `GET /api/projects`, `GET /api/projects/{id}` | Read-only; blocked paths walk `DEPENDS_ON` to the nearest cause |
| Create sample project | `POST /api/projects` | One transaction; four milestones, three dependencies, a paid scope invoice, one open invoice, four deliverables |
| Preview payment | `GET /api/invoices/{id}/payment-preview` | Pure read; no node, edge or status changes |
| Record sample payment | `POST /api/payments` | Amount must equal the invoice in integer cents; one new `Payment`, `PAID_BY` and `UNLOCKS` edges only for that milestone's deliverables |
| Mark milestone done | `POST /api/milestones/{id}/complete` | Refused with 409 when blocked or when its invoice is still `SENT` |

A failed operation rolls back. Tests cover wrong amounts, a second payment,
unknown ids, blocked completion, unpaid completion and a forced mid-transaction
failure. Amounts are integers in sample cents; method is always `sample`.

## Relate placement and persistence

- Mode: **embedded Python** (`relate-db==1.0.1`), not Aura and not a hosted
  Neo4j account.
- Store: one persistent file, `data/workgraph.rl`, committed to the repo so a
  judge can inspect the sample graph without an LLM key.
- Why: the file survives process exit, needs no server, and is small. The test
  `test_store_survives_process_exit` seeds it, closes the connection, then
  counts nodes in a separate Python process.
- Open and query it read-only:
  `relate --database data/workgraph.rl --read-only --mode table "MATCH (n) RETURN count(n) AS n"`
  (CLI), or `relate.connect("data/workgraph.rl", read_only=True)` in Python.

### WASM vs Python decision

**Decision: Python embedded FastAPI is the canonical graph for the local and
live demo. WASM is not the source of truth.** This is unchanged from Phase 0.

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
   no scoreable gain.

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
has a done Discovery milestone and a SENT Design system invoice, so Build and
Handover are blocked one and two hops downstream. `Atlas dashboard` is fully
paid and done. Each milestone has a deliverable; only paid ones are unlocked.

The seed has `Party-[:WORKED_ON]->Project`,
`Project-[:HAS_MILESTONE]->Milestone`,
`Milestone-[:DEPENDS_ON]->Milestone`,
`Milestone-[:INVOICED]->Invoice-[:PAID_BY]->Payment-[:UNLOCKS]->Deliverable`,
and skill edges.

Example multi-hop question, answered by `graph/queries.py:BLOCKED_BY_UNPAID`:

```cypher
MATCH (later:Milestone)-[:DEPENDS_ON*1..3]->(waiting:Milestone)-[:INVOICED]->(inv:Invoice)
WHERE inv.status = 'SENT'
RETURN DISTINCT later.name, waiting.name, inv.number, inv.amount_cents
```

Result: `Build` and `Handover` both wait on `Design system` (invoice `WG-1002`,
240000 cents).

## Screenshots

- [`docs/shots/p1m1-board.png`](docs/shots/p1m1-board.png): board at 1440.
- [`docs/shots/p1m1-project-graph.png`](docs/shots/p1m1-project-graph.png): project graph and dependency paths.
- [`docs/shots/p1m1-confirm-payment.png`](docs/shots/p1m1-confirm-payment.png): payment confirmation.
- [`docs/shots/p1m1-after-payment.png`](docs/shots/p1m1-after-payment.png): PAID status and the unlock edge.
- [`docs/shots/p1m1-mobile.png`](docs/shots/p1m1-mobile.png): board at 390.

## Limits

The human UI writes sample data only: no card fields, no live PayPal, no email,
no live LLM call. The assistant network is published and validated but is not
mounted in the React page yet; that is Phase 1b. Amounts are integer cents in
sample data. A browser refresh reads the same single store, not a per-tab copy.

## Licence and disclosure

Apache-2.0. See `LICENSE` and `NOTICE`. WorkGraph reuses the author's
MilestonePay *ideas* (milestone and sample-payment UX); no MilestonePay source
or git history was copied. The Agentic Web runtime is copied unchanged from
`cognizant-ai-labs/agentic-web`, and Relate is used as an embedded library.
