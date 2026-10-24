"""Load seed members into the database: uv run scripts/seed_db.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from masshelp.masshealth_mock.service import seed_members  # noqa: E402
from masshelp.services import build_services  # noqa: E402

if __name__ == "__main__":
    services = build_services(seed=False)
    print(f"seeded {seed_members(services.db, services.settings)} members")
