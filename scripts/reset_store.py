"""Rebuild the committed sample store.

    python scripts/reset_store.py --force

Without ``--force`` the script refuses to overwrite an existing store. Tests
never call this: they seed their own temporary stores.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.db import connect, store_path  # noqa: E402
from graph.seed import seed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace the existing store")
    args = parser.parse_args()

    target = store_path()
    if target.exists():
        if not args.force:
            print(f"refusing to replace existing store: {target}")
            print("pass --force to rebuild the sample data")
            return 1
        target.unlink()
        print(f"removed old store: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with connect(target) as conn:
        result = seed(conn)
        conn.flush()
    print(f"seeded {target}: {result['nodes']} nodes, {result['relationships']} relationships")
    return 0


if __name__ == "__main__":
    sys.exit(main())
