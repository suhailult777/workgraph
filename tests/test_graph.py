import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from graph.db import connect
from graph.queries import BLOCKED_BY_UNPAID, PAID_SKILL_HISTORY, UNLOCK_PATHS, rows
from graph.seed import counts, seed

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "workgraph.rl"
    with connect(path) as conn:
        seed(conn)
        conn.flush()
    return path


def test_seed_shape(store):
    with connect(store, read_only=True) as conn:
        assert counts(conn) == {"nodes": 25, "relationships": 37}


def test_store_survives_process_exit(store):
    code = (
        "import relate, json, sys; "
        f"c = relate.connect({str(store)!r}, read_only=True); "
        "print(json.dumps(c.execute('MATCH (n) RETURN count(n) AS n').fetchone().data()))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"n": 25}


def test_blocked_milestones_follow_dependency_chain(store):
    with connect(store, read_only=True) as conn:
        result = rows(conn, BLOCKED_BY_UNPAID)
    assert result == [
        {"blocked": "Build", "waiting_on": "Design system", "invoice": "WG-1002", "amount_cents": 240000},
        {"blocked": "Handover", "waiting_on": "Design system", "invoice": "WG-1002", "amount_cents": 240000},
    ]


def test_paid_skill_history_is_multi_hop(store):
    with connect(store, read_only=True) as conn:
        result = rows(conn, PAID_SKILL_HISTORY, {"skill": "Design systems"})
    assert {(r["party"], r["milestone"]) for r in result} == {
        ("Jules Okafor", "Audit"),
        ("Jules Okafor", "Component library"),
        ("Mira Chen", "Discovery"),
    }


def test_payment_unlocks_deliverable(store):
    with connect(store, read_only=True) as conn:
        result = rows(conn, UNLOCK_PATHS)
    assert {r["deliverable"] for r in result} == {
        "Audit report",
        "Component library source",
        "Discovery notes",
    }
