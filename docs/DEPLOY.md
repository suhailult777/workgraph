# Deploy WorkGraph to Vercel Hobby

This repository is prepared for a Vercel Hobby deployment named `workgraph`
under team `suhailult777s-projects`. Nothing here was deployed or pushed by this
task. Grok Bot performs the push and deploy after review.

## What Vercel runs

- **FastAPI** at `backend/app.py` is the Python function. `pyproject.toml` sets
  `[tool.vercel] entrypoint = "backend.app:app"`.
- **Vite** builds `frontend/dist`. `vercel.json` runs:
  `npm --prefix frontend ci && npm --prefix frontend run build`.
- FastAPI mounts `frontend/dist` at `/`. `[tool.vercel.fastapi.static]` sets
  `cdn = true` and `exclude = true`, so Vercel promotes those files to the CDN
  while `/api/*` still reaches the function.
- The root `public/` directory is served by Vercel at the matching root paths:
  `agent-manifest.json`, the resolved network, `links.json`, `agent-mcp.json`,
  `.well-known/`, `runtime/`, `site-actions.js` and `page-bridge.js`.
- `vercel.json` adds `Access-Control-Allow-Origin: *` to those public artifacts.
- `rewrites` sends `/projects/*` and `/assistant` to `index.html` for a future
  path-based route. The current app uses hash routes, so it already works
  without a rewrite.
- `/api/*` is handled by the FastAPI function, never by the static build.

## Storage on Vercel

Vercel Functions have a read-only project filesystem. WorkGraph uses:

- `/tmp/workgraph.rl` for the live Relate file, selected automatically when
  `VERCEL` is set.
- A private Vercel Blob snapshot for durability. `backend/storage.py` downloads
  the blob to `/tmp` before Relate opens it, and after each write uploads it
  back with the Blob API's `x-if-match` ETag header and retry.
- The committed `data/workgraph.rl` is the seed if the blob does not exist yet.

`relate-db==1.0.1` publishes a
`cp39-abi3-manylinux2014_x86_64` wheel, so the native Relate extension is
available to the Vercel Linux Python runtime. This was checked by downloading
the wheel, not by deploying to Vercel. The actual Vercel execution remains
unverified until a deploy.

Create a **private** Blob store and connect it to the project so
`BLOB_READ_WRITE_TOKEN` is present. The token must contain the store id in the
usual `vercel_blob_rw_<store>_<secret>` form; `backend/storage.py` reads that id
to build the private blob URL.

### Concurrency limit

The Blob snapshot is a single-writer design. `x-if-match` stops a blind
overwrite, and a 412 is retried after reading the new ETag. It does not merge
two graphs. If two Vercel instances write at the same time, the later writer
can replace the earlier writer's snapshot. This is acceptable for the sample
app and is called out here rather than hidden. A production multi-writer graph
needs a database with transactions or a lock service.

## Environment variables

Set these in the Vercel project. Values are never committed or printed here.

| Name | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Server-side key for the free-model assistant |
| `OPENROUTER_FREE_MODELS` | Optional comma list; ids must end in `:free` |
| `ASSISTANT_IP_DAILY_CAP` | Per-IP daily cap, default 20 |
| `ASSISTANT_GLOBAL_DAILY_CAP` | Global daily cap, default 300 |
| `ASSISTANT_ATTEMPT_TIMEOUT_SECONDS` | Per-model timeout, default 22 |
| `ASSISTANT_TOTAL_TIMEOUT_SECONDS` | Overall assistant deadline, default 75 |
| `PAYPAL_CLIENT_ID` | PayPal sandbox client id |
| `PAYPAL_CLIENT_SECRET` | PayPal sandbox client secret |
| `PAYPAL_WEBHOOK_ID` | PayPal sandbox webhook id |
| `BLOB_READ_WRITE_TOKEN` | Private Vercel Blob read-write token |
| `WORKGRAPH_ENV` | Set to `production` |

Optional: `BLOB_STORE_PATH` (default `workgraph/workgraph.rl`).
`PAYPAL_MOCK` and `WORKGRAPH_ASSISTANT_MOCK` are ignored when production is
detected. Do not set them on Vercel.

## PayPal sandbox webhook

The webhook endpoint is `POST /api/paypal/webhook`. When
`PAYPAL_WEBHOOK_ID` is set, every request must carry PayPal's transmission
headers and the server asks PayPal's
`/v1/notifications/verify-webhook-signature` API before it trusts the event. A
missing or failed signature is rejected with 400. When the id is unset, the
endpoint acknowledges the request with `skipped: "webhook_id_not_configured"`
and a message; it never trusts an unsigned event.

Only `PAYMENT.CAPTURE.COMPLETED` changes the graph. The handler extracts
`resource.supplementary_data.related_ids.order_id`, finds the local
`PayPalOrder`, and runs the same capture path as the browser. `PayPalOrder`
status `CAPTURING` makes a second browser or webhook capture return `409` or
`processing` instead of writing twice. The ledger payment is also idempotent by
the external order id.

### Create the sandbox webhook

1. Open <https://developer.paypal.com/dashboard/applications/sandbox> and sign
   in to the PayPal developer account that owns the sandbox app.
2. Select the sandbox app whose client id is in `PAYPAL_CLIENT_ID`.
3. Scroll to **Webhooks** and choose **Add Webhook**.
4. Webhook URL: `https://<your-deployment>/api/paypal/webhook`.
5. Event types: tick **PAYMENT.CAPTURE.COMPLETED** only. Do not add order,
   refund or dispute events for this milestone.
6. Save the webhook, then copy the **Webhook ID** that PayPal shows.
7. Add it to the Vercel project as `PAYPAL_WEBHOOK_ID` for Production, then
   redeploy. Do not put the id in the repository.
8. Check `GET /api/config`: `paypal_webhook_configured` must be `true`.
9. Use PayPal's **Webhooks simulator** with `PAYMENT.CAPTURE.COMPLETED` and a
   real sandbox capture id, or complete one sandbox checkout and confirm the
   ledger has exactly one `paypal_sandbox` payment.

If the deployment is behind a proxy, keep the raw body untouched. The endpoint
reads `request.body()` before parsing so the event object sent for verification
matches PayPal's payload.

## Assistant timeout budget

`vercel.json` sets `maxDuration` to **300** seconds, the current Hobby default
and maximum for Node.js, Bun and Python functions with Fluid compute. The
assistant does not use the whole window: each free-model attempt defaults to 22
seconds, and one user call has an overall deadline of 75 seconds. With the
default three-model list, the worst case is about 66 seconds. Both values can be
lowered with `ASSISTANT_ATTEMPT_TIMEOUT_SECONDS` and
`ASSISTANT_TOTAL_TIMEOUT_SECONDS`.

A timeout or transport error skips to the next free model. If every model times
out, `POST /api/assistant` and the SSE route return JSON `503 upstream_timeout`
with a clear message. An unexpected exception returns JSON `500
assistant_internal`; neither route should emit a plain-text 500.

## Exact deploy commands

From `C:\Users\suhai\workgraph`:

```powershell
npx vercel@latest link --project workgraph --scope suhailult777s-projects
npx vercel@latest --prod --yes
```

The first command links the local folder to the existing project. The second
builds and deploys to production. Add the environment variables first, either
in the Vercel dashboard or with `npx vercel@latest env add NAME production`
(one name at a time; the CLI prompts for the value without echoing it).

Do not run these commands from this task. Grok Bot deploys after review.

## Clean-copy check

The deployable tree must build without `.venv`, `node_modules`, or local store
changes. From a clean checkout:

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\check_conformance
.\.venv\Scripts\python.exe -m pytest -q
```

## Post-deploy checks

1. `GET /api/config` returns `assistant_live: true`, `assistant_mock: false`,
   `paypal_sandbox_configured: true`, `paypal_webhook_configured: true`,
   `storage_kind: "vercel_blob"`, `environment: "production"`.
2. `GET /api/health` is `ok` and `graph_ready: true`.
3. `GET /agent-manifest.json` returns 200 with
   `Access-Control-Allow-Origin: *`.
4. Open `/`, `/api/projects`, a project, the assistant and the payment dialog.
5. Confirm the LIVE badge and that no demo mode appears.
6. Run one sandbox checkout end to end: create the order, approve it with the
   sandbox buyer, return to `/paypal/return`, and confirm the invoice is PAID
   with one `paypal_sandbox` payment and the deliverable unlocked.
7. Repeat the capture or replay the webhook: the ledger must still have one
   payment.
8. Run `python scripts/check_conformance --http https://<deployment>`.

## If a deploy fails

- Missing `BLOB_READ_WRITE_TOKEN`: health is degraded and the graph is missing.
  This is intentional; production must not silently use a demo.
- Missing `OPENROUTER_API_KEY`: the UI shows NOT CONFIGURED and does not mount
  the assistant. It does not fall back to the demo.
- Relate import failure: confirm the Linux wheel is in the bundle and that
  `/tmp` is used. The local Windows wheel is not evidence for the Linux runtime.
- Function bundle over 500 MB: `includeFiles` is limited to `data/**` and
  `public/**`; `[tool.vercel.fastapi.static] exclude = true` keeps the frontend
  build out of the Python bundle.
