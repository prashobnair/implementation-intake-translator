"""Append-only encrypted raw-event ledger and retention body erasure."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..core import IntakeError
from .schema import RawEvent


def append_raw(
    engine: Engine,
    *,
    tenant_id: str,
    source: str,
    event_id: str,
    body: bytes,
    auth_mode: str,
    key: bytes,
) -> int:
    if not all((tenant_id, source, event_id)) or auth_mode not in (
        "hmac",
        "shared_token",
        "api_key",
    ):
        raise IntakeError("invalid_raw_event", "scope and authentication mode required")
    with Session(engine) as session, session.begin():
        row = RawEvent(
            tenant_id=tenant_id,
            source=source,
            event_id=event_id,
            received_at=datetime.now(timezone.utc),
            body_ciphertext=Fernet(key).encrypt(body),
            payload_sha256=hashlib.sha256(body).hexdigest(),
            auth_mode=auth_mode,
        )
        session.add(row)
        session.flush()
        return row.id


def purge_bodies(engine: Engine, *, tenant_id: str, before: datetime) -> int:
    """Erase ciphertext after retention; keep digest, scope, time and auth mode."""
    if not tenant_id or before.tzinfo is None:
        raise IntakeError("invalid_retention", "tenant and aware cutoff required")
    with Session(engine) as session, session.begin():
        condition = (
            (RawEvent.tenant_id == tenant_id)
            & (RawEvent.received_at < before)
            & RawEvent.body_ciphertext.is_not(None)
        )
        count = session.scalar(select(func.count()).select_from(RawEvent).where(condition)) or 0
        session.execute(update(RawEvent).where(condition).values(body_ciphertext=None))
        return count


def purge_expired_bodies(
    engine: Engine, *, tenant_id: str, days: int = 30, now: datetime | None = None
) -> int:
    if now is not None and now.tzinfo is None:
        raise IntakeError("invalid_retention", "aware current time required")
    if not 1 <= days <= 365:
        raise IntakeError("invalid_retention", "retention must be 1-365 days")
    return purge_bodies(
        engine,
        tenant_id=tenant_id,
        before=(now or datetime.now(timezone.utc)) - timedelta(days=days),
    )
