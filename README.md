# WorkGraph

WorkGraph is a new open agentic website for freelance work: projects, milestone
dependencies, invoices and sample payments live in a persistent Relate graph.
People and browser agents read and change the same graph.

**Status: Phase 0 spikes (13-16 Nov 2026).** This repository is local only. It
is not pushed, hosted or submitted. Feature work starts in Phase 1.

## What is here

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI service: health, graph summary, static agent artifacts |
| `frontend/` | React + TypeScript skeleton (Vite) |
| `public/` | Published agentic web artifacts: manifest, network, links, runtime |
| `graph/` | Relate seed loader and queries |
| `data/` | Committed Relate store (created by the seed script) |
| `vendor/` | Third-party checkouts, not tracked by this repository |
| `tests/` | Python tests for the graph, artifacts and API |

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m graph.seed          # create data/workgraph.rl
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8090
```

Then open http://127.0.0.1:8090/ for the React build (once built) and
http://127.0.0.1:8090/agent-manifest.json for the public artifact.

## Relate persistence decision

Filled in by the Phase 0 spike. See `docs/spike-findings.md`.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
