"""FastAPI service for WorkGraph: health, graph reads/writes and artifacts."""

from __future__ import annotations

import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import relate

from backend.assistant import AssistantError, AssistantService, completion_to_sse
from backend.demo_llm import demo_reply
from backend.paypal import PayPalClient, PayPalError, verify_capture
from backend.storage import BlobStorage, LocalStorage, StorageError, build_storage
from graph.db import DEFAULT_STORE, connect
from graph.operations import (
    GraphError,
    accept_plan,
    agent_state,
    assert_store_integrity,
    claim_paypal_order,
    complete_milestone,
    consume_assistant_quota,
    create_paypal_order_record,
    create_sample_project,
    decline_path,
    find_paypal_order_by_capture,
    get_paypal_order_record,
    get_project,
    list_projects,
    mark_paypal_order_captured,
    payment_result_for_external_id,
    preview_payment,
    record_payment,
    release_paypal_order,
)
from graph.queries import BLOCKED_BY_UNPAID, PAID_SKILL_HISTORY, SUMMARY, UNLOCK_PATHS, rows
from graph.retrieval import retrieve_context

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
DIST = ROOT / "frontend" / "dist"
T = TypeVar("T")
logger = logging.getLogger(__name__)


class ProjectCreate(BaseModel):
    name: str | None = Field(default=None, max_length=80)


class PaymentCreate(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0)


class PlanStep(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    depends_on: list[str] = Field(default_factory=list)


class PlanAccept(BaseModel):
    project_name: str = Field(min_length=1, max_length=80)
    milestones: list[PlanStep]


class PayPalOrderCreate(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=80)
    return_url: str | None = Field(default=None, max_length=500)
    cancel_url: str | None = Field(default=None, max_length=500)


def _is_production() -> bool:
    return os.environ.get("WORKGRAPH_ENV", "").lower() == "production" or bool(
        os.environ.get("VERCEL")
    )


def _default_store_path() -> Path:
    return Path("/tmp/workgraph.rl") if os.environ.get("VERCEL") else DEFAULT_STORE


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


class GraphService:
    """Owns one Relate connection on a dedicated thread.

    Relate connections are thread-affine, and FastAPI runs sync handlers on a
    worker pool. One executor thread keeps every read and write on the owning
    thread, and the single connection means a write is visible to the next read.
    """

    def __init__(self, path: Path, storage: LocalStorage | BlobStorage | None = None):
        self.path = path
        self.storage = storage or LocalStorage()
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

    def _persist(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self.storage.save_from(self.path)

    def persist(self) -> None:
        if self.storage.kind == "local_file":
            return
        try:
            self._pool.submit(self._persist).result(timeout=60)
        except StorageError as exc:
            raise HTTPException(
                status_code=exc.status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

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


def create_app(
    store: Path | None = None,
    *,
    storage: LocalStorage | BlobStorage | None = None,
    assistant: AssistantService | None = None,
    paypal: PayPalClient | None = None,
) -> FastAPI:
    default_store = _default_store_path()
    path = Path(store) if store else Path(os.environ.get("WORKGRAPH_STORE", default_store))
    selected_storage = storage or build_storage()
    if selected_storage.kind != "local_file":
        try:
            selected_storage.load_to(path)
        except StorageError as exc:
            if exc.code == "blob_missing" and DEFAULT_STORE.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(DEFAULT_STORE, path)
                selected_storage.save_from(path)
            else:
                raise
    graph = GraphService(path, selected_storage)
    assistant_service = assistant or AssistantService(
        mock=bool(os.environ.get("WORKGRAPH_ASSISTANT_MOCK") == "1" and not _is_production()),
        quota=lambda ip, day, ip_cap, global_cap: graph.call(
            lambda conn: consume_assistant_quota(conn, ip, day, ip_cap, global_cap)
        ),
        retrieve=lambda question: graph.call(
            lambda conn: retrieve_context(conn, question)
        ),
    )
    paypal_client = paypal or PayPalClient(
        mock=bool(os.environ.get("PAYPAL_MOCK") == "1" and not _is_production())
    )

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
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                expected_host = request.headers.get("host", "")
                expected_scheme = request.headers.get(
                    "x-forwarded-proto", request.url.scheme
                )
                if parsed.netloc != expected_host or parsed.scheme != expected_scheme:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {
                                "code": "cross_origin_write",
                                "message": "WorkGraph writes are same-origin only.",
                            }
                        },
                    )
        return await call_next(request)
    app.state.graph = graph
    app.state.storage = selected_storage
    app.state.assistant = assistant_service
    app.state.paypal = paypal_client

    public_artifacts = (
        "/agent-manifest.json",
        "/workgraph.network.json",
        "/agent-mcp.json",
        "/links.json",
        "/workgraph.hocon",
        "/site-actions.js",
        "/page-bridge.js",
    )

    @app.middleware("http")
    async def public_artifact_cors(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if request.method in {"GET", "HEAD"} and (
            path in public_artifacts
            or path.startswith("/.well-known/")
            or path.startswith("/runtime/")
        ):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        return response

    @app.exception_handler(GraphError)
    async def graph_error(_request, exc: GraphError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(PayPalError)
    async def paypal_error(_request, exc: PayPalError) -> JSONResponse:
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
            "assistant_live": assistant_service.configured,
            "paypal_sandbox_configured": paypal_client.configured,
            "paypal_webhook_configured": paypal_client.webhook_configured,
            "storage_kind": selected_storage.kind,
        }

    @app.get("/api/config")
    def config() -> dict:
        return {
            "assistant_live": assistant_service.configured,
            "assistant_mock": bool(getattr(assistant_service, "mock", False)),
            "paypal_sandbox_configured": paypal_client.configured,
            "paypal_webhook_configured": paypal_client.webhook_configured,
            "storage_kind": selected_storage.kind,
            "environment": "production" if _is_production() else "development",
        }

    @app.get("/api/projects")
    def projects() -> dict:
        return {"projects": graph.call(list_projects)}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate | None = None) -> dict:
        name = body.name if body else None
        result = graph.call(lambda conn: create_sample_project(conn, name))
        graph.persist()
        return result

    @app.post("/api/plans/accept", status_code=201)
    def accept(body: PlanAccept) -> dict:
        result = graph.call(
            lambda conn: accept_plan(
                conn,
                body.project_name,
                [step.model_dump() for step in body.milestones],
            )
        )
        graph.persist()
        return result

    @app.get("/api/projects/{project_id}")
    def project(project_id: str) -> dict:
        return graph.call(lambda conn: get_project(conn, project_id))

    @app.get("/api/invoices/{invoice_id}/payment-preview")
    def payment_preview(invoice_id: str) -> dict:
        return graph.call(lambda conn: preview_payment(conn, invoice_id))

    @app.post("/api/payments", status_code=201)
    def payment(body: PaymentCreate) -> dict:
        result = graph.call(
            lambda conn: record_payment(conn, body.invoice_id, body.amount_cents)
        )
        graph.persist()
        return result

    @app.post("/api/milestones/{milestone_id}/complete")
    def milestone_complete(milestone_id: str) -> dict:
        result = graph.call(lambda conn: complete_milestone(conn, milestone_id))
        graph.persist()
        return result

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

    @app.get("/api/graph/decline-path")
    def graph_decline_path(invoice: str = Query(min_length=1, max_length=40)) -> dict:
        return graph.call(lambda conn: decline_path(conn, invoice))

    @app.get("/api/graph/unlocks")
    def unlocks() -> dict:
        return {"unlocks": graph.query(UNLOCK_PATHS)}

    @app.get("/api/assistant/models")
    def assistant_models() -> dict:
        return {
            "object": "list",
            "data": [
                {"id": model, "object": "model", "owned_by": "openrouter"}
                for model in app.state.assistant.models
            ],
        }

    @app.post("/api/assistant")
    def assistant_chat(payload: dict, request: Request) -> JSONResponse:
        try:
            completion = app.state.assistant.chat(payload, _client_ip(request))
        except AssistantError as exc:
            return JSONResponse(
                status_code=exc.status,
                content={"detail": {"code": exc.code, "message": exc.message}},
            )
        except Exception:
            logger.exception("assistant request failed")
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "assistant_internal",
                        "message": "The assistant failed unexpectedly. Try again shortly.",
                    }
                },
            )
        return JSONResponse(completion)

    @app.post("/api/assistant/chat/completions", include_in_schema=False)
    def assistant_completions(payload: dict, request: Request) -> Response:
        try:
            completion = app.state.assistant.chat(payload, _client_ip(request))
        except AssistantError as exc:
            return JSONResponse(
                status_code=exc.status,
                content={"detail": {"code": exc.code, "message": exc.message}},
                headers={"X-WorkGraph-Error": exc.code},
            )
        except Exception:
            logger.exception("assistant SSE request failed")
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "assistant_internal",
                        "message": "The assistant failed unexpectedly. Try again shortly.",
                    }
                },
            )
        try:
            body = completion_to_sse(completion)
        except Exception:
            logger.exception("assistant SSE serialization failed")
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "assistant_internal",
                        "message": "The assistant failed unexpectedly. Try again shortly.",
                    }
                },
            )
        return Response(
            content=body,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Nsdeploy-LLM-Route": "mock"
                if getattr(app.state.assistant, "mock", False)
                else "live",
            },
        )

    def _captured_result(record: dict, *, recovered: bool = False) -> dict:
        payment = None
        try:
            payment = graph.call(
                lambda conn: payment_result_for_external_id(conn, record["id"])
            )
        except Exception:
            payment = None
        result = {
            "already_captured": True,
            "order": record,
            "payment_id": record.get("payment_id"),
            "capture_id": record.get("capture_id"),
            "payment": payment,
        }
        if recovered:
            result["recovered"] = True
        return result

    def capture_paypal_order(order_id: str) -> dict:
        record = graph.call(lambda conn: get_paypal_order_record(conn, order_id))
        if record["status"] == "CAPTURED":
            return _captured_result(record)
        if not paypal_client.configured:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "paypal_not_configured",
                    "message": "PayPal sandbox is not configured on this deployment.",
                },
            )

        claim = graph.call(lambda conn: claim_paypal_order(conn, order_id))
        if not claim.get("claimed"):
            latest = graph.call(lambda conn: get_paypal_order_record(conn, order_id))
            if latest["status"] == "CAPTURED":
                return _captured_result(latest)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "paypal_capture_in_progress",
                    "message": "Another capture for this order is still running. Try again shortly.",
                },
            )

        try:
            try:
                preview = graph.call(
                    lambda conn: preview_payment(conn, record["invoice_id"])
                )
            except GraphError as exc:
                if exc.code not in {"already_paid", "already_unlocked"}:
                    raise
                payment = graph.call(
                    lambda conn: payment_result_for_external_id(conn, order_id)
                )
                if payment is None:
                    raise
                order = graph.call(
                    lambda conn: mark_paypal_order_captured(
                        conn, order_id, payment["payment_id"], record.get("capture_id") or ""
                    )
                )
                graph.persist()
                return {
                    "already_captured": True,
                    "recovered": True,
                    "order": order,
                    "payment_id": payment["payment_id"],
                    "payment": payment,
                }

            try:
                captured = paypal_client.capture_order(
                    order_id, record["amount_cents"], record["currency"]
                )
            except PayPalError as exc:
                if exc.code != "paypal_capture_conflict":
                    raise
                captured = paypal_client.get_order(order_id)
            capture_id = verify_capture(
                captured, order_id, record["amount_cents"], record["currency"]
            )
            payment = graph.call(
                lambda conn: record_payment(
                    conn,
                    record["invoice_id"],
                    record["amount_cents"],
                    method="paypal_sandbox",
                    external_id=order_id,
                )
            )
            order = graph.call(
                lambda conn: mark_paypal_order_captured(
                    conn, order_id, payment["payment_id"], capture_id
                )
            )
            graph.persist()
            return {
                "already_captured": False,
                "order": order,
                "capture_id": capture_id,
                "payment": payment,
                "invoice": preview["invoice"],
            }
        except Exception as exc:
            try:
                graph.call(lambda conn: release_paypal_order(conn, order_id, type(exc).__name__))
                graph.persist()
            except Exception:
                pass
            raise

    @app.post("/api/paypal/orders", status_code=201)
    def paypal_create_order(body: PayPalOrderCreate, request: Request) -> dict:
        if not paypal_client.configured:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "paypal_not_configured",
                    "message": "PayPal sandbox is not configured on this deployment.",
                },
            )
        preview = graph.call(lambda conn: preview_payment(conn, body.invoice_id))
        base = str(request.base_url).rstrip("/")
        order = paypal_client.create_order(
            preview["amount_cents"],
            "USD",
            body.invoice_id,
            body.return_url or f"{base}/paypal/return",
            body.cancel_url or f"{base}/#/projects/{preview['project']['id']}",
        )
        record = graph.call(
            lambda conn: create_paypal_order_record(
                conn,
                order["id"],
                body.invoice_id,
                preview["amount_cents"],
                "USD",
                order["approve_url"],
            )
        )
        graph.persist()
        return {
            "order": {**record, "mock": bool(order.get("mock"))},
            "approve_url": order["approve_url"],
            "invoice": preview["invoice"],
            "amount_cents": preview["amount_cents"],
        }

    @app.post("/api/paypal/orders/{order_id}/capture")
    def paypal_capture(order_id: str) -> dict:
        return capture_paypal_order(order_id)

    @app.get("/api/paypal/orders/{order_id}")
    def paypal_order(order_id: str) -> dict:
        return {"order": graph.call(lambda conn: get_paypal_order_record(conn, order_id))}

    @app.post("/api/paypal/webhook")
    async def paypal_webhook(request: Request) -> dict:
        raw = await request.body()
        if not paypal_client.webhook_configured:
            return {
                "ok": True,
                "skipped": "webhook_id_not_configured",
                "message": "Set PAYPAL_WEBHOOK_ID to verify PayPal webhook signatures.",
            }
        verified = paypal_client.verify_webhook(dict(request.headers), raw)
        if not verified:
            raise HTTPException(
                status_code=400,
                detail={"code": "paypal_webhook_invalid", "message": "Webhook verification failed."},
            )
        try:
            event = json.loads(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "paypal_webhook_invalid", "message": "Webhook body is not JSON."},
            ) from exc
        if not isinstance(event, dict):
            raise HTTPException(
                status_code=400,
                detail={"code": "paypal_webhook_invalid", "message": "Webhook body is not an object."},
            )
        if event.get("event_type") != "PAYMENT.CAPTURE.COMPLETED":
            return {"ok": True, "ignored": event.get("event_type")}
        resource = event.get("resource") or {}
        order_id = (
            (resource.get("supplementary_data") or {}).get("related_ids", {}).get("order_id")
            or resource.get("order_id")
        )
        if not order_id and resource.get("id"):
            order_id = graph.call(
                lambda conn: find_paypal_order_by_capture(conn, str(resource["id"]))
            )
        if not order_id:
            raise HTTPException(
                status_code=400,
                detail={"code": "paypal_webhook_invalid", "message": "Webhook has no order id."},
            )
        try:
            graph.call(lambda conn: get_paypal_order_record(conn, order_id))
        except GraphError as exc:
            if exc.status == 404:
                return {"ok": True, "ignored": "unknown_order", "order_id": order_id}
            raise
        try:
            return capture_paypal_order(order_id)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if exc.status_code == 409 and detail.get("code") == "paypal_capture_in_progress":
                return {"ok": True, "processing": True, "order_id": order_id}
            raise

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

    @app.get("/paypal/return", include_in_schema=False)
    def paypal_return_page():
        index = DIST / "index.html"
        if not index.exists():
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "frontend_missing", "message": "Build the frontend first."}},
            )
        return FileResponse(index, media_type="text/html")

    if (PUBLIC / "runtime").is_dir():
        app.mount(
            "/runtime",
            JavaScriptStaticFiles(directory=PUBLIC / "runtime"),
            name="runtime",
        )
    if (PUBLIC / ".well-known").is_dir():
        app.mount("/.well-known", StaticFiles(directory=PUBLIC / ".well-known"), name="well-known")
    app.mount("/", StaticFiles(directory=DIST, html=True, check_dir=False), name="frontend")

    return app


app = create_app()
