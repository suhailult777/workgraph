"""FastAPI service for WorkGraph: health, graph reads and public artifacts."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from graph.db import DEFAULT_STORE, connect
from graph.queries import BLOCKED_BY_UNPAID, PAID_SKILL_HISTORY, SUMMARY, UNLOCK_PATHS, rows

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
DIST = ROOT / "frontend" / "dist"


class GraphReader:
    """Owns one read-only Relate connection on a dedicated thread.

    Relate connections are thread-affine, and FastAPI runs sync handlers on a
    worker pool. One executor thread keeps every query on the owning thread.
    """

    def __init__(self, path: Path):
        self.path = path
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="relate")
        self._conn = None

    def _run(self, cypher: str, params: dict | None) -> list[dict]:
        if self._conn is None:
            self._conn = connect(self.path, read_only=True)
        return rows(self._conn, cypher, params)

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        try:
            return self._pool.submit(self._run, cypher, params).result(timeout=15)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail="graph store missing") from exc

    def close(self) -> None:
        if self._conn is not None:
            self._pool.submit(self._conn.close).result(timeout=15)
            self._conn = None
        self._pool.shutdown(wait=True)


def create_app(store: Path | None = None) -> FastAPI:
    path = Path(store) if store else Path(os.environ.get("WORKGRAPH_STORE", DEFAULT_STORE))
    reader = GraphReader(path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        reader.close()

    app = FastAPI(title="WorkGraph", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.graph = reader

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok" if path.exists() else "degraded",
            "service": "workgraph",
            "store": str(path),
            "graph_ready": path.exists(),
        }

    @app.get("/api/graph/summary")
    def summary() -> dict:
        labels = reader.query(SUMMARY)
        projects = reader.query(
            "MATCH (p:Project) RETURN p.id AS id, p.name AS name, p.status AS status ORDER BY name"
        )
        milestones = reader.query(
            "MATCH (p:Project)-[:HAS_MILESTONE]->(m:Milestone) "
            "RETURN p.name AS project, m.name AS milestone, m.status AS status "
            "ORDER BY project, milestone"
        )
        return {"labels": labels, "projects": projects, "milestones": milestones}

    @app.get("/api/graph/blocked")
    def blocked() -> dict:
        return {"blocked": reader.query(BLOCKED_BY_UNPAID)}

    @app.get("/api/graph/similar")
    def similar(skill: str = Query(min_length=1, max_length=80)) -> dict:
        return {"skill": skill, "work": reader.query(PAID_SKILL_HISTORY, {"skill": skill})}

    @app.get("/api/graph/unlocks")
    def unlocks() -> dict:
        return {"unlocks": reader.query(UNLOCK_PATHS)}

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

    if (PUBLIC / "runtime").is_dir():
        app.mount("/runtime", StaticFiles(directory=PUBLIC / "runtime"), name="runtime")
    if (PUBLIC / ".well-known").is_dir():
        app.mount("/.well-known", StaticFiles(directory=PUBLIC / ".well-known"), name="well-known")
    if DIST.is_dir():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")

    return app


app = create_app()
