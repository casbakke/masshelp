"""Reset demo state: close open cases and re-seed members and open requests.

    uv run scripts/reset_demo.py           # all demo numbers
    uv run scripts/reset_demo.py --hard    # also delete data/ (db, media, pdfs)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import select  # noqa: E402

from masshelp.masshealth_mock.service import seed_members  # noqa: E402
from masshelp.store.models import Case, CaseStatus  # noqa: E402


def reset_phone(services, phone: str | None) -> int:
    closed = 0
    with services.db.session() as s:
        query = select(Case).where(Case.status != CaseStatus.CLOSED)
        if phone:
            query = query.where(Case.phone_e164 == phone)
        for case in s.exec(query):
            case.status = CaseStatus.CLOSED
            s.add(case)
            closed += 1
        s.commit()
    seed_members(services.db, services.settings)
    return closed


def main() -> None:
    from masshelp.config import get_settings
    from masshelp.services import build_services

    ap = argparse.ArgumentParser()
    ap.add_argument("--hard", action="store_true")
    args = ap.parse_args()
    if args.hard:
        shutil.rmtree(get_settings().data_dir, ignore_errors=True)
        print("deleted data/")
    services = build_services()
    print(f"closed {reset_phone(services, None)} case(s); members re-seeded")


if __name__ == "__main__":
    main()
