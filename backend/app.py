"""FastAPI service for WorkGraph: health, graph reads/writes and artifacts."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, TypeVar

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import relate

from backend.demo_llm import demo_reply
from graph.db import DEFAULT_STORE, connect
from graph.operations import (
    GraphError,
    agent_state,
    assert_store_integrity,
    complete_milestone,
    create_sample_project,
    get_project,
    list_projects,
    preview_payment,
    record_payment,
)
from graph.queries import BLOCKED_BY_UNPAID, PAID_SKILL_HISTORY, SUMMARY, UNLOCK_PATHS, rows

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
DIST = ROOT / "frontend" / "dist"
T = TypeVar("T")


class ProjectCreate(BaseModel):
    name: str | None = Field(default=None, max_length=80)


class PaymentCreate(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0)


class GraphService:
    """Owns one Relate connection on a dedicated thread.

    Relate connections are thread-affine, and FastAPI runs sync handlers on a
    worker pool. One executor thread keeps every read and write on the owning
    thread, and the single connection means a write is visible to the next read.
    """

    def __init__(self, path: Path):
        self.path = path
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="relate")
        self._conn = None

    def _run(self, fn: Callable[[object], T]) -> T:
        if not self.path.exists():
            raise FileNotFoundError(str(self.path))
        if self._conn is None:
            self._conn = connect(self.path)
        return fn(self._conn)

    def call(self, fn: Callable[[object], T]) -> T:
        try:
            return self._pool.submit(self._run, fn).result(timeout=20)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "store_missing", "message": "graph store missing"},
            ) from exc
        except relate.OperationalError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "store_unavailable", "message": "graph store unavailable"},
            ) from exc

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        return self.call(lambda conn: rows(conn, cypher, params))

    def close(self) -> None:
        if self._conn is not None:
            self._pool.submit(self._conn.close).result(timeout=20)
            self._conn = None
        self._pool.shutdown(wait=True)


class JavaScriptStaticFiles(StaticFiles):
    """Serve .js and .mjs as JavaScript.

    Windows' MIME table maps .js and .mjs to text/plain on some machines, which
    makes the browser refuse an ES module import. The runtime has .mjs files, so
    set the type explicitly.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".js", ".mjs")):
            response.headers["content-type"] = "application/javascript"
        return response


def _store_label(path: Path) -> str:
    override = os.environ.get("WORKGRAPH_STORE_LABEL")
    if override:
        candidate = Path(override)
        if (
            not override.startswith(("/", "\\"))
            and not candidate.is_absolute()
            and ".." not in candidate.parts
            and ":" not in override
        ):
            return override
    try:
        if path.resolve() == DEFAULT_STORE.resolve():
            return "data/workgraph.rl"
    except OSError:
        pass
    return path.name


def create_app(store: Path | None = None) -> FastAPI:
    path = Path(store) if store else Path(os.environ.get("WORKGRAPH_STORE", DEFAULT_STORE))
    graph = GraphService(path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        graph.close()

    app = FastAPI(title="WorkGraph", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def same_origin_writes(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            host = (request.url.hostname or "").lower().rstrip(".")
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            allowed_host = host in {"localhost", "::1", "0.0.0.0", "testserver"} or host.startswith(
                "127."
            )
            if not allowed_host:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": {
                            "code": "host_not_allowed",
                            "message": "WorkGraph sample writes are local-host only.",
                        }
                    },
                )
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": {
                            "code": "cross_origin_write",
                            "message": "WorkGraph sample writes are same-origin only.",
                        }
                    },
                )
        return await call_next(request)
    app.state.graph = graph

    @app.exception_handler(GraphError)
    async def graph_error(_request, exc: GraphError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/api/health")
    def health() -> dict:
        ready = path.exists()
        if ready:
            try:
                graph.query("RETURN 1 AS ok")
            except HTTPException:
                ready = False
        return {
            "status": "ok" if ready else "degraded",
            "service": "workgraph",
            "store": _store_label(path),
            "graph_ready": ready,
        }

    @app.get("/api/projects")
    def projects() -> dict:
        return {"projects": graph.call(list_projects)}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate | None = None) -> dict:
        name = body.name if body else None
        return graph.call(lambda conn: create_sample_project(conn, name))

    @app.get("/api/projects/{project_id}")
    def project(project_id: str) -> dict:
        return graph.call(lambda conn: get_project(conn, project_id))

    @app.get("/api/invoices/{invoice_id}/payment-preview")
    def payment_preview(invoice_id: str) -> dict:
        return graph.call(lambda conn: preview_payment(conn, invoice_id))

    @app.post("/api/payments", status_code=201)
    def payment(body: PaymentCreate) -> dict:
        return graph.call(
            lambda conn: record_payment(conn, body.invoice_id, body.amount_cents)
        )

    @app.post("/api/milestones/{milestone_id}/complete")
    def milestone_complete(milestone_id: str) -> dict:
        return graph.call(lambda conn: complete_milestone(conn, milestone_id))

    @app.get("/api/graph/summary")
    def summary() -> dict:
        def read_summary(conn) -> dict:
            assert_store_integrity(conn)
            return {
                "labels": rows(conn, SUMMARY),
                "projects": rows(
                    conn,
                    "MATCH (p:Project) RETURN p.id AS id, p.name AS name, p.status AS status "
                    "ORDER BY name",
                ),
                "milestones": rows(
                    conn,
                    "MATCH (p:Project)-[:HAS_MILESTONE]->(m:Milestone) "
                    "RETURN p.name AS project, m.name AS milestone, m.status AS status "
                    "ORDER BY project, milestone",
                ),
            }

        return graph.call(read_summary)

    @app.get("/api/graph/state")
    def state() -> dict:
        return graph.call(agent_state)

    @app.get("/api/graph/blocked")
    def blocked() -> dict:
        def read_blocked(conn) -> list[dict]:
            assert_store_integrity(conn)
            return rows(conn, BLOCKED_BY_UNPAID)

        return {"blocked": graph.call(read_blocked)}

    @app.get("/api/graph/similar")
    def similar(skill: str = Query(min_length=1, max_length=80)) -> dict:
        def read_similar(conn) -> list[dict]:
            assert_store_integrity(conn)
            return rows(conn, PAID_SKILL_HISTORY, {"skill": skill})

        return {"skill": skill, "work": graph.call(read_similar)}

    @app.get("/api/graph/unlocks")
    def unlocks() -> dict:
        return {"unlocks": graph.query(UNLOCK_PATHS)}

    @app.post("/api/demo/llm/chat/completions", include_in_schema=False)
    def demo_chat(payload: dict) -> Response:
        """Deterministic OpenAI-compatible SSE endpoint for the no-key demo."""
        reply = demo_reply(payload)
        model = reply.get("model") or "workgraph-demo"
        tool_call = reply.get("tool_call")
        events = []
        if tool_call:
            events.append(
                {
                    "model": model,
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": tool_call["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tool_call["name"],
                                            "arguments": json.dumps(tool_call["arguments"]),
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
            events.append(
                {"model": model, "choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
            )
        else:
            events.append(
                {
                    "model": model,
                    "choices": [
                        {
                            "delta": {"content": reply.get("content") or ""},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        return Response(
            content=body,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Nsdeploy-LLM-Route": "demo",
            },
        )

    @app.get("/agent-manifest.json", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(PUBLIC / "agent-manifest.json", media_type="application/json")

    @app.get("/workgraph.network.json", include_in_schema=False)
    def network() -> FileResponse:
        return FileResponse(PUBLIC / "workgraph.network.json", media_type="application/json")

    @app.get("/links.json", include_in_schema=False)
    def links() -> FileResponse:
        return FileResponse(PUBLIC / "links.json", media_type="application/json")

    @app.get("/agent-mcp.json", include_in_schema=False)
    def agent_mcp() -> FileResponse:
        return FileResponse(PUBLIC / "agent-mcp.json", media_type="application/json")

    @app.get("/site-actions.js", include_in_schema=False)
    def site_actions() -> FileResponse:
        return FileResponse(PUBLIC / "site-actions.js", media_type="application/javascript")

    @app.get("/page-bridge.js", include_in_schema=False)
    def page_bridge() -> FileResponse:
        return FileResponse(PUBLIC / "page-bridge.js", media_type="application/javascript")

    if (PUBLIC / "runtime").is_dir():
        app.mount(
            "/runtime",
            JavaScriptStaticFiles(directory=PUBLIC / "runtime"),
            name="runtime",
        )
    if (PUBLIC / ".well-known").is_dir():
        app.mount("/.well-known", StaticFiles(directory=PUBLIC / ".well-known"), name="well-known")
    if DIST.is_dir():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")

    return app


app = create_app()
