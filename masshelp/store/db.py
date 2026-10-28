"""Database engine and session helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event as sa_event
from sqlmodel import Session, SQLModel, create_engine

from masshelp.store import models  # noqa: F401  (register tables)
from masshelp.store.models import Event
from masshelp.util.redact import redact_obj


class Database:
    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.url = url
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        if url.startswith("sqlite"):

            @sa_event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()

    def init(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine, expire_on_commit=False) as s:
            yield s


def log_event(session: Session, case_id: str | None, type_: str, payload: dict[str, Any] | None = None) -> None:
    """Append an audit event. Payloads are redacted before storage (R37)."""
    session.add(
        Event(case_id=case_id, type=type_, payload_json=json.dumps(redact_obj(payload or {}), default=str))
    )
    session.commit()
