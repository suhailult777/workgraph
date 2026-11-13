# WorkGraph

WorkGraph is a new open agentic website for freelance work: projects, milestone
dependencies, invoices and sample payments live in a persistent Relate graph.
People and browser agents read and change the same graph.

**Status: Phase 1, milestone 3 (26-30 Nov 2026).** Local only. Not pushed,
hosted or submitted. The human UI, the graph operations and the browser
assistant are working. The assistant reads the graph, traces decline paths, and
can accept a plan or record a sample payment only after an on-screen
confirmation. Production defaults to a live server-side free model; the local
no-key demo is a labelled development fallback.

## What is here

| Path | Purpose |
| --- | --- |
| `backend/app.py` | FastAPI: health, config, projects, payments, milestones, assistant, PayPal sandbox, artifacts, React build |
| `backend/assistant.py` | Server-side OpenRouter free-model proxy with per-IP and global daily caps |
| `backend/paypal.py` | PayPal Orders v2 sandbox client, capture verification and webhook check |
| `backend/storage.py` | Local file or Vercel Blob snapshot with ETag compare-and-swap |
| `backend/demo_llm.py` | Deterministic no-key scripted model for the local demo |
| `frontend/` | React + TypeScript human UI: board, project graph, queries, payment and sandbox dialog, assistant mount |
| `public/` | Agentic Web artifacts: manifest, resolved network, links, runtime, site actions |
| `public/workgraph.hocon` | Source for the published network |
| `public/site-actions.js` | Seven registered actions: five reads, a local draft, and two confirmed writes |
| `public/page-bridge.js` | Browser functions behind the actions; reads and writes the same API as the page |
| `graph/seed.py` | Seed loader for the sample graph |
| `graph/operations.py` | Create/accept plan, preview/record payment, complete milestone, decline paths, quotas, PayPal order records |
| `graph/queries.py` | Read queries used by the agent state and paid-skill history |
| `data/workgraph.rl` | Committed Relate store (28 nodes, 40 relationships) |
| `tests/` | Graph invariants, storage, assistant, PayPal and HTTP tests |
| `tests_agent/` | Node tests with a scripted model, no provider |
| `package.json` | Node scripts: `test:agent`, `check:network` |
| `scripts/reset_seed.py` | Reset the store to the committed seed (`--force`) |
| `scripts/judge_pass.py` | Checks the local public URLs, project API, decline path and action modules |
| `docs/shots/` | Phase 1 screenshots |
| `.env.example` | Variable names only; no secrets |
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
.\.venv\Scripts\python.exe scripts\reset_seed.py --force
```

Copy `.env.example` to `.env` for live mode. Never commit the filled file.
Without `OPENROUTER_API_KEY`, production shows "not configured" instead of a
demo. For a local, labelled demo without any key:

```powershell
$env:WORKGRAPH_ASSISTANT_MOCK='1'
$env:PAYPAL_MOCK='1'
```

`WORKGRAPH_ASSISTANT_MOCK` and `PAYPAL_MOCK` are ignored when
`WORKGRAPH_ENV=production` or `VERCEL` is set. Production uses the real
server-side free-model proxy and the real PayPal sandbox only.

A read-only CLI or a reset needs the server stopped because the open connection
holds a Windows file lock. Tests never touch `data/workgraph.rl`; each test
seeds its own temporary store.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm run test:agent     # Node 22 or newer, no provider
npm run check:network
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

## Browser assistant

The assistant is mounted below the page content and opens from the **Ask**
button in the header. It runs in the visitor's browser and uses the same graph
API as the page.

- **Network:** `workgraph_coordinator` (front agent), `plan_specialist` and
  `ledger_specialist`. The HOCON is the source of truth; the JSON network and
  discovery files are generated by the vendored build script.
- **Actions:** `get_graph_state`, `search_similar_work`, `get_decline_path`,
  `propose_plan`, `fill_draft`, `accept_plan` and `record_payment`.
  `fill_draft` writes only a `sessionStorage` draft. `accept_plan` and
  `record_payment` are irreversible and the browser shows a confirmation
  dialog before any graph change. Cancel returns `cancelled` and leaves the
  graph unchanged.
- **Not registered:** `record_sample_payment`, `unlock_deliverable` and any
  card-charge tool. The assistant cannot charge a card, take real money, send
  email or call live PayPal.
- **Grounding:** instructions require a node id or invoice number for every
  project, milestone, invoice and payment fact. Answers that have no tool fact
  say they do not know.
- **Live mode:** when `/api/config` reports `assistant_live: true`, the browser
  boots the runtime against `/api/assistant`. The server calls OpenRouter with
  an allowlist of model ids ending in `:free`, falls back to the next free model
  on 429/5xx, and enforces per-IP and global daily caps. The key stays on the
  server.
- **Local demo:** with `WORKGRAPH_ASSISTANT_MOCK=1` on a development host, the
  same server endpoint uses the deterministic scripted model. The panel labels
  it `DEV` / `Local demo`. Production never selects it.
- **BYOK:** the panel accepts an OpenAI-compatible base URL, model and key. The
  key is kept in this tab's `sessionStorage` only, passed to the runtime in
  memory, and sent only to the router the visitor chooses. It is not written to
  the repo, the graph, a WorkGraph request or a log. The panel rejects the
  WorkGraph origin and loopback aliases.
- **Quota:** a 429 returns a clear message in the chat, not a silent demo.
  Counters are graph nodes keyed by a SHA-256 prefix of the IP, never the raw IP.
- **Demo queries:** decline path, paid design work, a four-step plan, a sample
  payment and a card-charge refusal. The card charge is intentionally declined.

The assistant section is also where the saved draft appears. A draft contains
milestone names and dependencies, no amounts, and has **Accept plan** and
**Clear draft** buttons. Accepting uses the same confirmation dialog.

## Live mode and configuration

`GET /api/config` returns only booleans plus the storage kind and environment:

```json
{
  "assistant_live": true,
  "paypal_sandbox_configured": true,
  "storage_kind": "vercel_blob",
  "environment": "production"
}
```

- `OPENROUTER_API_KEY`: server-side key for the free-model proxy.
- `OPENROUTER_FREE_MODELS`: comma list; ids not ending in `:free` are dropped.
- `ASSISTANT_IP_DAILY_CAP` (default 20) and `ASSISTANT_GLOBAL_DAILY_CAP`
  (default 300): durable daily counters.
- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`: sandbox only.
- `BLOB_READ_WRITE_TOKEN`, `BLOB_STORE_PATH`: durable Vercel Blob snapshot.
- `WORKGRAPH_ENV=production` or `VERCEL=1`: refuses the local demo and mock
  PayPal paths.

## PayPal sandbox

The payment dialog has a separate **PayPal sandbox checkout** section.

1. The server previews the invoice and creates an Orders v2 sandbox order.
2. The visitor approves in the sandbox, then the browser asks the server to
   capture it.
3. The server verifies the order id, `COMPLETED` status, amount and currency
   before calling `record_payment` with method `paypal_sandbox`.
4. A second capture of the same order returns `already_captured` and does not
   create a second payment.
5. `POST /api/paypal/webhook` verifies with `PAYPAL_WEBHOOK_ID` and skips
   gracefully when the id is unset.

The client refuses every host except `api-m.sandbox.paypal.com`. `PAYPAL_MOCK=1`
returns a labelled `MOCK-` order for local tests and screenshots; production
ignores it. No real money is ever used.

## Assistant artifacts

| URL | What it is |
| --- | --- |
| `/agent-manifest.json` | Network name, front agent, sample queries, live/BYOK routers, action list |
| `/workgraph.network.json` | Generated resolved network; keep three agents and the action names in sync |
| `/site-actions.js` | Registers seven actions; imports `page-bridge.js` |
| `/page-bridge.js` | Reads state, decline paths and paid work; accepts plans and records sample payments |
| `/api/graph/state` | Compact grounded state for the assistant (projects, statuses, blocked paths, invoices, skills) |
| `/api/graph/decline-path` | Every milestone blocked until one invoice is paid |
| `/api/assistant` | Server-side free-model JSON endpoint |
| `/api/assistant/chat/completions` | SSE endpoint used by the browser runtime |
| `/api/assistant/models` | Allowlisted `:free` model ids only |
| `/api/demo/llm/chat/completions` | Local-only scripted SSE fallback |

Rebuild and check the network after changing the HOCON or manifest:

```powershell
npm run check:network
```

The runtime is Apache-2.0 and is copied unchanged. Do not edit it. `site-actions.js`
and `page-bridge.js` are served as `application/javascript`; the FastAPI host
also sets that type for `.mjs` runtime modules because Windows can otherwise map
them to `text/plain` and the browser refuses the ES module.

### Graph operations and invariants

All writes live in `graph/operations.py`; the HTTP endpoints and the later site
actions call the same functions.

| Operation | Endpoint | Invariant |
| --- | --- | --- |
| List / read project | `GET /api/projects`, `GET /api/projects/{id}` | Read-only; blocked paths walk `DEPENDS_ON` to the nearest cause |
| Create sample project | `POST /api/projects` | One transaction; four milestones, three dependencies, a paid scope invoice, one open invoice, four deliverables |
| Accept plan | `POST /api/plans/accept` | Only the four-step Scope, Design, Build, Handover template; one transaction; server assigns sample amounts |
| Preview payment | `GET /api/invoices/{id}/payment-preview` | Pure read; no node, edge or status changes |
| Record sample payment | `POST /api/payments` | Amount must equal the invoice in integer cents; one new `Payment`, `PAID_BY` and `UNLOCKS` edges only for that milestone's deliverables |
| PayPal sandbox order | `POST /api/paypal/orders` | Sandbox host only; stores the order id with the invoice |
| PayPal capture | `POST /api/paypal/orders/{id}/capture` | Verifies order id, COMPLETED status, amount and currency; second capture is a no-op |
| Mark milestone done | `POST /api/milestones/{id}/complete` | Refused with 409 when blocked or when its invoice is still `SENT` |

A failed operation rolls back. Tests cover wrong amounts, a second payment,
unknown ids, blocked completion, unpaid completion and a forced mid-transaction
failure. A milestone with more than one invoice is rejected, and an invoice
linked to two milestones is rejected. Amounts are integers in sample cents;
sample payments use method `sample`, PayPal sandbox captures use
`paypal_sandbox` with the order id in `external_id`. Blocked paths use one BFS
that visits each ancestor once, so a wide DAG cannot stall the board; the API
returns at most 12 blockers per milestone.

Assistant quota counters are `AssistantQuota` nodes keyed by day plus a
SHA-256 prefix of the IP. They live in the same durable store, so a cold start
does not reset the cap. The raw IP is never stored.

### Durable snapshot storage

- Local development: the Relate file on disk, `storage_kind: local_file`.
- Production: `BLOB_READ_WRITE_TOKEN` selects a Vercel Blob snapshot. The app
  downloads it to a temporary path before opening Relate, and after every write
  closes the connection, reads the blob ETag and uploads with `If-Match`.
  A 409/412 conflict retries up to three times.
- If the blob is missing, the committed seed is copied and uploaded once.
- Tests use a fake blob transport and cover load, ETag conflict retry and a
  missing snapshot. No real blob token is read or printed.

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
| `/site-actions.js` | seven actions: graph state, similar work, decline path, plan, local draft, accept plan, record payment |
| `/page-bridge.js` | shared browser functions behind those actions |

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
- [`docs/shots/p1m2-assistant-open.png`](docs/shots/p1m2-assistant-open.png): assistant in demo mode, sample questions and BYOK panel.
- [`docs/shots/p1m2-read-answer.png`](docs/shots/p1m2-read-answer.png): grounded answer about unpaid invoices.
- [`docs/shots/p1m2-similar-work.png`](docs/shots/p1m2-similar-work.png): paid work found by skill.
- [`docs/shots/p1m2-byok-panel.png`](docs/shots/p1m2-byok-panel.png): BYOK panel with no key visible.
- [`docs/shots/p1m2-decline.png`](docs/shots/p1m2-decline.png): card-charge refusal.
- [`docs/shots/p1m2-mobile.png`](docs/shots/p1m2-mobile.png): assistant at 390.
- [`docs/shots/p1m3-confirm-dialog.png`](docs/shots/p1m3-confirm-dialog.png): confirmation dialog before a graph write.
- [`docs/shots/p1m3-cancel-unchanged.png`](docs/shots/p1m3-cancel-unchanged.png): cancel leaves the graph unchanged.
- [`docs/shots/p1m3-decline-path.png`](docs/shots/p1m3-decline-path.png): invoice decline path and paid-skill query.
- [`docs/shots/p1m3-live-badge.png`](docs/shots/p1m3-live-badge.png): LIVE badge in the header.
- [`docs/shots/p1m3-quota.png`](docs/shots/p1m3-quota.png): quota-exhausted message.
- [`docs/shots/p1m3-sandbox-checkout.png`](docs/shots/p1m3-sandbox-checkout.png): labelled mock PayPal sandbox checkout.

## Limits

The human UI writes sample ledger data only: no card fields, no real money, no
email. PayPal is sandbox only and a second capture is a no-op. The assistant
can accept a plan or record a sample payment only after the on-screen
confirmation; cancel leaves the graph unchanged. The live assistant uses
allowlisted `:free` OpenRouter models with daily caps; the local no-key demo is
a deterministic scripted model, not an LLM, and is disabled in production. A
real BYOK key stays in the tab's `sessionStorage` and goes only to the router
the visitor chooses; the panel rejects the WorkGraph origin itself. Sample
writes are same-origin only, and cross-origin POSTs are refused. Amounts are
integer cents in sample data. A browser refresh reads the same single store, not
a per-tab copy.

## Licence and disclosure

Apache-2.0. See `LICENSE` and `NOTICE`. WorkGraph reuses the author's
MilestonePay *ideas* (milestone and sample-payment UX). The live deployment also
follows MilestonePay's architecture for Vercel Blob ETag snapshots and PayPal
sandbox create/capture/verify/webhook; that code was rewritten for WorkGraph and
the MilestonePay repository was read only. No MilestonePay source or git history
was copied. The Agentic Web runtime is copied unchanged from
`cognizant-ai-labs/agentic-web`, and Relate is used as an embedded library.
