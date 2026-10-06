"""Hash-chained, append-only audit log. One chain per tenant."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..core import IntakeError
from ..storage.schema import AuditEntry

GENESIS = "0" * 64
ACTIONS = ("ingest", "enrich", "extract", "decide", "approve", "amend", "project")


def entry_hash(
    prev_hash: str, tenant_id: str, ts: str, actor: str, action: str, subject: str, detail: str
) -> str:
    material = json.dumps(
        [prev_hash, tenant_id, ts, actor, action, subject, detail],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("ascii")).hexdigest()


def append_in_session(
    session: Session,
    tenant_id: str,
    actor: str,
    action: str,
    subject: str,
    detail: dict[str, Any],
    *,
    now: datetime | None = None,
) -> int:
    """Append inside the caller's transaction so state and audit commit together."""
    if action not in ACTIONS or not all((tenant_id, actor, subject)):
        raise IntakeError("invalid_audit", "tenant, actor, subject and a known action required")
    last = session.scalar(
        select(AuditEntry)
        .where(AuditEntry.tenant_id == tenant_id)
        .order_by(AuditEntry.id.desc())
        .limit(1)
    )
    prev = last.hash if last is not None else GENESIS
    ts = (now or datetime.now(timezone.utc)).isoformat()
    detail_json = json.dumps(detail, sort_keys=True, ensure_ascii=True)
    row = AuditEntry(
        tenant_id=tenant_id,
        ts=ts,
        actor=actor,
        action=action,
        subject=subject,
        detail_json=detail_json,
        prev_hash=prev,
        hash=entry_hash(prev, tenant_id, ts, actor, action, subject, detail_json),
    )
    session.add(row)
    session.flush()
    return row.id


def record_audit(
    engine: Engine,
    tenant_id: str,
    actor: str,
    action: str,
    subject: str,
    detail: dict[str, Any],
    *,
    now: datetime | None = None,
) -> int:
    with Session(engine) as session, session.begin():
        if engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return append_in_session(session, tenant_id, actor, action, subject, detail, now=now)


def verify_chain(engine: Engine, tenant_id: str) -> dict[str, Any]:
    """Recompute every hash. Reports the first row that no longer matches."""
    prev = GENESIS
    count = 0
    with Session(engine) as session:
        rows = session.scalars(
            select(AuditEntry).where(AuditEntry.tenant_id == tenant_id).order_by(AuditEntry.id)
        )
        for row in rows:
            expected = entry_hash(
                prev, row.tenant_id, row.ts, row.actor, row.action, row.subject, row.detail_json
            )
            if row.prev_hash != prev or row.hash != expected:
                return {"valid": False, "entries": count, "first_invalid_id": row.id}
            prev = row.hash
            count += 1
    return {"valid": True, "entries": count, "first_invalid_id": None}
