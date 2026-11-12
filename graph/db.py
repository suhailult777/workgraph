"""Relate connection helper for WorkGraph."""

from __future__ import annotations

import os
from pathlib import Path

import relate

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "workgraph.rl"


def store_path() -> Path:
    return Path(os.environ.get("WORKGRAPH_STORE", DEFAULT_STORE))


def connect(path: Path | None = None, read_only: bool = False):
    target = path or store_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    return relate.connect(str(target), read_only=read_only)
