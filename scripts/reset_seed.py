"""Reset the sample store to the committed seed.

    python scripts/reset_seed.py --force

This is the documented reset path for a local judge or a fresh deployment.
Without ``--force`` it refuses to replace an existing store.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.reset_store import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
